"""Loop 编排器：Master→Planner→Builder→Reviewer 状态机（asyncio 后台任务）。

落地文档: docs/AGENT-LOOP-INTEGRATION.md §6.4
设计要点:
- 每个 loop 一个 LoopRuntime，持有事件队列（SSE 推送）与 checkpoint 事件（等待用户决策）。
- LLM 调用为阻塞 urllib，用 asyncio.to_thread 包装，避免阻塞事件循环。
- Builder 落盘走 D4：git stash create 快照 + gate.yaml denylist 机械拦截 + 受控路径写入。
- 迭代熔断 MAX_ITER=3，超限升级 CRITICAL_FAIL。
- P0-1: gate.yaml 路径 denylist 机械执行。
- P1-4: run_log 结构化运行日志。
- P1-5: 分支锁碰撞检测。
- P1-6: 空 watchlist early exit。
"""

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..llm import get_llm_config, resolve_api_key, build_chat_request
from . import db
from .budget import BudgetExhausted, LoopBudget, LoopPaused, Usage, extract_usage, get_loop_budget
from .critique import generate_critique
from .effects import apply_build_files, revert_effects
from .gate import LoopGate
from .prompts import MASTER_PROMPT, PLANNER_PROMPT, BUILDER_PROMPT, REVIEWER_PROMPT, USER_AGENT_PROMPT
from .registry import default_registry
from .schemas import Plan, BuildOutput, ReviewResult, UxReviewResult, Verdict
from .state import load_project_state, update_state_after_loop, prune_state, check_graduation_demotion, get_graduation_status, save_project_state
from .worktree import Worktree, is_git_repo

logger = logging.getLogger(__name__)

MAX_ITER = 3

# 允许的 Builder 落盘根目录（安全边界）：环境变量 AGENTS_PROJECT_ROOT，默认 Orbit 项目根
# 从 backend/app/agents/ 到 Orbit 根需要 3 层 ..（agents → app → backend → Orbit）
_AGENTS_ROOT = os.getenv("AGENTS_PROJECT_ROOT") or os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


class LoopRuntime:
    """单个 loop 的运行时状态：事件队列 + checkpoint 同步原语。"""

    def __init__(self, loop_id: int):
        self.loop_id = loop_id
        self.events: asyncio.Queue = asyncio.Queue()  # None = sentinel（结束）
        self.checkpoint_event = asyncio.Event()
        self.decision: Optional[dict] = None  # checkpoint 决策结果


# 全局 runtime 注册表（单进程内存态，重启后回放 DB 恢复）
_runtimes: dict[int, LoopRuntime] = {}


def get_runtime(loop_id: int) -> LoopRuntime:
    runtime = _runtimes.get(loop_id)
    if not runtime:
        runtime = LoopRuntime(loop_id)
        _runtimes[loop_id] = runtime
    return runtime


# ── 事件写入：DB 持久化 + 队列推送（P2-10: 通知过滤）─────────────────

# 需要主动通知的事件类型
NOTIFY_EVENTS = {
    "checkpoint", "escalation", "budget_warning", "budget_exhausted",
    "loop_failed", "denylist_hit", "done", "error", "paused",
}

# 静默事件（不触发通知）
SILENT_EVENTS = {
    "spawn", "plan", "builder_done", "verdict", "ux_review", "memory_injected",
    "budget", "retry", "worktree_created", "worktree_merged", "report",
    "loop_idle", "master_done",
}


async def _emit(loop_id: int, agent: str, event_type: str, payload: dict, notify: Optional[bool] = None):
    """写事件到 DB + 推送到该 loop 的 SSE 队列。

    P2-10: notify 参数可覆盖通知过滤。默认根据 event_type 自动判断：
    - NOTIFY_EVENTS 中的类型设置 notify=True
    - SILENT_EVENTS 中的类型设置 notify=False
    """
    if notify is None:
        notify = event_type in NOTIFY_EVENTS

    seq = db.add_loop_event(loop_id, agent, event_type, payload)
    runtime = _runtimes.get(loop_id)
    if runtime:
        await runtime.events.put({
            "agent": agent, "event_type": event_type, "payload": payload, "seq": seq,
            "notify": notify,
        })


async def _finish(loop_id: int, status: str):
    """结束 loop：补发终态事件 + 更新状态 + 归档（P3）+ 放 sentinel + 延迟清理 runtime。

    Bug #8 修复：所有终态统一在此 emit done/error 事件（原来部分调用点只调 _finish
    不发事件，导致前端 SSE 收不到终态，UI 永远显示"进行中"）。
    注：done/error 事件用于 SSE 端点 break，可能已由调用点手动 emit（幂等）。
    """
    if status == "done":
        await _emit(loop_id, "system", "done", {"status": "done"})
    else:
        await _emit(loop_id, "system", "error", {"message": f"Loop 终止（{status}）"})
    db.update_loop_group(loop_id, status=status, current_agent="")
    # P3: 从事件流渲染 markdown 归档（产物不是载体，落地文档 §6.7）
    try:
        _archive_loop(loop_id)
    except Exception:
        logger.exception("Loop %s 归档失败", loop_id)
    runtime = _runtimes.get(loop_id)
    if runtime:
        await runtime.events.put(None)

    async def _cleanup():
        await asyncio.sleep(60)
        _runtimes.pop(loop_id, None)

    asyncio.create_task(_cleanup())


# ── P3: markdown 归档 ────────────────────────────────────────────

def _archive_loop(loop_id: int) -> str:
    """把 loop 事件流渲染为人类可读的 markdown，写入 data/agent-loops/{loop_id}.md。

    归档是审计/展示产物（保留原 agent-loop 设计"可回溯、可人工介入"的优点），
    运行时通信仍只走结构化事件（loop_events 表）。
    """
    loop = db.get_loop_group(loop_id)
    events = db.get_loop_events(loop_id)
    if not loop:
        raise FileNotFoundError(f"loop {loop_id} 不存在")

    archive_dir = Path(_AGENTS_ROOT) / "data" / "agent-loops"
    archive_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Agent Loop #{loop_id} 归档",
        "",
        f"- **任务**: {loop['task_desc']}",
        f"- **状态**: {loop['status']}",
        f"- **Session**: {loop['session_id']}",
        f"- **迭代次数**: {loop['iteration_count']}",
        f"- **归档时间**: {datetime.now().isoformat()}",
        "",
        "---",
        "",
    ]

    plan_section = None
    verdict_section = None
    timeline: list[str] = []

    for ev in events:
        p = ev.get("payload") or {}
        when = ev.get("created_at", "")[:19]
        tag = f"- `{ev['event_type']}` ({ev['agent']}, {when})"

        if ev["event_type"] == "plan":
            plan_section = _render_plan(p)
            timeline.append(tag + " — Planner 产出计划")
        elif ev["event_type"] == "builder_done":
            timeline.append(tag + f" — {_shorten(p.get('summary', ''), 80)}")
        elif ev["event_type"] == "verdict":
            verdict_section = _render_verdict(p)
            timeline.append(tag + f" — {p.get('verdict')}")
        elif ev["event_type"] == "checkpoint":
            timeline.append(tag + f" — ⏸ {_shorten(p.get('title', ''), 60)}")
        elif ev["event_type"] == "user_decision":
            timeline.append(tag + f" — 用户: {p.get('decision')}")
        elif ev["event_type"] == "error":
            timeline.append(tag + f" — ❌ {_shorten(p.get('message', ''), 80)}")
        elif ev["event_type"] == "done":
            timeline.append(tag + " — ✅ 完成")
        else:
            timeline.append(tag)

    if plan_section:
        lines.append("## 执行计划")
        lines.append("")
        lines.append(plan_section)
        lines.append("")
    if verdict_section:
        lines.append("## 验证结果")
        lines.append("")
        lines.append(verdict_section)
        lines.append("")

    lines.append("## 事件时间线")
    lines.append("")
    lines.extend(timeline)
    lines.append("")

    content = "\n".join(lines)
    out = archive_dir / f"{loop_id}.md"
    out.write_text(content, encoding="utf-8")
    logger.info("Loop %s 归档完成: %s", loop_id, out)
    return str(out)


def _render_plan(p: dict) -> str:
    """把 plan 事件 payload 渲染为 markdown 小节。"""
    out = [f"**任务**: {p.get('task_name', '')}", ""]
    steps = p.get("steps") or []
    for s in steps:
        idx = s.get("index", "")
        out.append(f"### Step {idx}: {s.get('desc', '')}")
        out.append("")
        out.append(f"- 成功标准: `{s.get('verify', '')}`")
        out.append(f"- 测试级别: `{s.get('test_level', '')}`")
        files = s.get("files") or []
        if files:
            out.append(f"- 涉及文件: {', '.join(files)}")
        out.append("")
    gates = p.get("gates") or []
    if gates:
        out.append("**质量门禁**")
        out.append("")
        for g in gates:
            out.append(f"- `{g.get('gate_id', '')}` {g.get('check', '')} → PASS 条件: {g.get('pass_criteria', '')}")
        out.append("")
    return "\n".join(out)


def _render_verdict(p: dict) -> str:
    """把 verdict 事件 payload 渲染为 markdown 小节。"""
    out = [f"**结论**: `{p.get('verdict', '')}`", ""]
    if p.get("fail_reason"):
        out.append(f"- 失败原因: {p.get('fail_reason')}")
    if p.get("fix_direction"):
        out.append(f"- 修复方向: {p.get('fix_direction')}")
    stages = p.get("stage_results") or []
    if stages:
        out.append("")
        out.append("| 阶段 | 检查项 | 结果 | 证据 |")
        out.append("|------|--------|------|------|")
        for s in stages:
            out.append(f"| {s.get('stage', '')} | {s.get('item', '')} | {s.get('result', '')} | {s.get('evidence', '')} |")
        out.append("")
    return "\n".join(out)


def _shorten(text: str, n: int) -> str:
    text = str(text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


# ── STATE / project name 推断 ──────────────────────────────────

_CONSTRAINTS_FILENAME = "loop-constraints.md"


def _load_constraints(project_dir: str) -> str:
    """P1-3: 加载 loop-constraints.md，作为 LLM 上下文的约束片段。

    优先从项目目录读取；不存在时使用内嵌默认约束。
    """
    if project_dir:
        path = os.path.join(project_dir, _CONSTRAINTS_FILENAME)
        if os.path.exists(path):
            try:
                return open(path, "r", encoding="utf-8").read()
            except Exception as e:
                logger.warning("读取 loop-constraints.md 失败: %s", e)

    # 默认约束（与 loop-constraints.md 模板一致）
    return """# Agent Loop 约束
## Push & Merge
- 推送前必须告知用户
- 禁止自动合并到 main 分支
## Paths
- 禁止编辑 .env, .env.*, auth/, payments/, secrets/
- 禁止编辑基础设施配置
## Code
- 修改代码后必须运行测试
- 禁止禁用测试
- 每个问题最多 3 次修复尝试
## Budget
- Token 达到上限 80% 时切换仅报告模式
- 如果 loop-pause-all 激活，立即退出
## Collision
- 同一分支每小时最多一个 action loop
- triage 模式不占用分支锁"""


def _should_early_exit(plan: Plan, mode: str) -> bool:
    """P1-6: 判断是否应该 early exit（空 watchlist，无需修改）。"""
    if not plan.steps:
        return True
    # 检查是否所有步骤都是 skip 且没有实际文件操作
    all_skip = all(s.test_level == "skip" for s in plan.steps)
    no_files = all(not s.files for s in plan.steps)
    return all_skip and no_files


def _infer_project_name(task_desc: str, project_dir: str) -> str:
    """从项目目录或任务描述推断 project_name。"""
    if project_dir:
        base = os.path.basename(os.path.realpath(project_dir))
        if base and base != ".":
            return base
    return (task_desc or "untitled").strip().split()[0][:40]


# ── P4: Builder 命令执行验证 ─────────────────────────────────────

# 命令白名单（安全规则 #2 RCE 防护）：只允许无副作用的验证性命令
# 第一段必须是白名单中的程序；禁止 shell 管道/重定向（禁用 shell=True）
_VERIFY_ALLOWED_BINS = {
    "python3", "python", "node", "npm", "npx", "pytest", "go", "goose",
    "grep", "cat", "ls", "find", "head", "tail", "wc", "echo", "diff",
    "git", "date", "pwd",
}
# 明确禁止的二进制（防 RCE/破坏）
_VERIFY_BLOCKED_BINS = {
    "rm", "mv", "cp", "dd", "mkfs", "fdisk", "shutdown", "reboot",
    "kill", "curl", "wget", "bash", "sh", "zsh", "python3.12", "pip",
}

_VERIFY_TIMEOUT = 30          # 单命令超时（秒）
_VERIFY_OUTPUT_MAX = 4000     # 输出截断（字符）


def _run_verification(commands: list[str], project_dir: str) -> list[dict]:
    """安全执行 Builder 的验证命令，返回逐条结果 [{command, ok, output, error}]。

    安全设计（安全规则 #2 RCE）：
    - 不经过 shell（shlex.split 直接 exec，禁用 shell=True 杜绝管道/重定向注入）
    - 二进制白名单 + 黑名单双校验
    - 仅在已校验的 project_dir 内执行
    - 单命令超时 + 输出截断
    """
    if not commands:
        return []
    target = _resolve_safe_project_dir(project_dir)
    if not target:
        return [{"command": c, "ok": False, "output": "", "error": "project_dir 未配置或越界，拒绝执行"} for c in commands]
    os.makedirs(target, exist_ok=True)  # cwd 必须存在，否则 subprocess 抛 FileNotFoundError

    results = []
    for raw in commands:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            argv = shlex.split(raw)
        except ValueError as e:
            results.append({"command": raw, "ok": False, "output": "", "error": f"命令解析失败: {e}"})
            continue
        if not argv:
            continue
        bin_name = os.path.basename(argv[0])
        if bin_name in _VERIFY_BLOCKED_BINS or bin_name not in _VERIFY_ALLOWED_BINS:
            results.append({"command": raw, "ok": False, "output": "", "error": f"命令 {bin_name} 不在白名单内，拒绝执行"})
            continue

        try:
            proc = subprocess.run(
                argv, cwd=target, capture_output=True, text=True,
                timeout=_VERIFY_TIMEOUT, shell=False,
            )
            out = (proc.stdout or "")[: _VERIFY_OUTPUT_MAX]
            err = (proc.stderr or "")[: _VERIFY_OUTPUT_MAX]
            results.append({
                "command": raw,
                "ok": proc.returncode == 0,
                "output": out,
                "error": err if proc.returncode != 0 else "",
            })
        except subprocess.TimeoutExpired:
            results.append({"command": raw, "ok": False, "output": "", "error": f"超时（>{_VERIFY_TIMEOUT}s）"})
        except FileNotFoundError:
            results.append({"command": raw, "ok": False, "output": "", "error": f"程序不存在: {bin_name}"})
        except Exception as e:  # noqa: BLE001
            results.append({"command": raw, "ok": False, "output": "", "error": str(e)})
    return results


# ── P4: Master 冷启动 ───────────────────────────────────────────

def _master_bootstrap(task_desc: str, api_key: str, model: str, user_id: Optional[int],
                      budget: Optional[LoopBudget] = None) -> tuple[str, dict]:
    """Master 冷启动需求对齐（P4）。

    当用户无项目上下文时调用：一次 LLM 对齐产出结构化 project 上下文，
    保存到 memory.project_context，返回注入 Planner 的上下文片段与 usage。
    """
    raw, usage = _call_llm_sync(MASTER_PROMPT, f"## 任务\n{task_desc}", api_key, model)
    if budget:
        budget.record("master", Usage(**usage))
    data = _parse_json(raw) or {}
    if not data:
        return "", usage

    # 保存项目上下文（供后续会话 restore_context 复用）
    if user_id:
        try:
            from ..memory.project import save_project_context
            save_project_context(
                user_id,
                project_name=data.get("project_name") or task_desc[:40],
                tech_stack=data.get("tech_stack"),
                current_progress=data.get("current_progress") or task_desc,
                key_decisions=data.get("key_decisions") or [],
            )
        except Exception as e:
            logger.warning("Master 保存项目上下文失败: %s", e)

    return (
        "## Master 需求对齐（冷启动）\n"
        f"{json.dumps(data, ensure_ascii=False, indent=2)}"
    ), usage


# ── P4: User Agent UX 审查 ─────────────────────────────────────

# 前端相关文件特征（用于判断是否值得跑 UX 审查）
_FRONTEND_MARKERS = (".tsx", ".jsx", ".vue", ".svelte", ".html", ".css", ".scss")

# playwright 可选依赖探测（避免硬依赖；不可用时 UX_SKIPPED 优雅降级）
def _playwright_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("playwright") is not None
    except Exception:
        return False


def _take_screenshots(project_dir: str, urls: list[str]) -> list[str]:
    """可选：用 playwright 对目标页面截图（playwright 可用且 urls 非空时）。"""
    if not _playwright_available() or not urls:
        return []
    shots: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
        from pathlib import Path as P

        target = _resolve_safe_project_dir(project_dir)
        if not target:
            return []
        out_dir = P(target) / ".orbit-screenshots"
        out_dir.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            for i, url in enumerate(urls[:3]):
                try:
                    page.goto(url, timeout=15000)
                    page.wait_for_timeout(800)
                    path = str(out_dir / f"ux-{i}.png")
                    page.screenshot(path=path, full_page=False)
                    shots.append(path)
                except Exception as e:
                    logger.warning("截图失败 %s: %s", url, e)
            browser.close()
    except Exception as e:
        logger.warning("playwright 截图失败（跳过）: %s", e)
    return shots


def _is_frontend_task(build: "BuildOutput") -> bool:
    files = [f.get("path", "") for f in build.changed_files]
    return any(any(marker in f.lower() for marker in _FRONTEND_MARKERS) for f in files)


def _run_ux_review(build: "BuildOutput", task_desc: str, api_key: str, model: str,
                   budget: Optional[LoopBudget] = None) -> tuple["Optional[UxReviewResult]", dict]:
    """User Agent UX 审查（P4-4）。

    - 非前端任务 → 返回 UX_SKIPPED（不阻塞 loop）
    - 前端任务 → LLM 双视角审查；playwright 可用时附带截图路径
    """
    if not _is_frontend_task(build):
        return UxReviewResult(overall="UX_SKIPPED", summary="非前端任务，跳过 UX 审查"), {}

    ctx = (
        f"## 任务\n{task_desc}\n\n"
        f"## Builder 变更文件\n{json.dumps(build.changed_files, ensure_ascii=False, indent=2)}"
    )
    try:
        raw, usage = _call_llm_sync(USER_AGENT_PROMPT, ctx, api_key, model)
        if budget:
            budget.record("user", Usage(**usage))
        data = _parse_json(raw)
        if not data:
            return UxReviewResult(overall="UX_SKIPPED", summary="UX 审查输出无法解析"), usage
        ux, err = _validate_model(data, UxReviewResult)
        if ux is None:
            return UxReviewResult(overall="UX_SKIPPED", summary=f"UX 审查 schema 校验失败: {err}"), usage

        # 可选截图（dev server 存在时才有意义；此处留空由上层决定）
        return ux, usage
    except Exception as e:
        logger.warning("UX 审查异常（降级 UX_SKIPPED）: %s", e)
        return UxReviewResult(overall="UX_SKIPPED", summary=f"UX 审查异常: {e}"), {}


# ── LLM 调用 ────────────────────────────────────────────────────

def _call_llm_sync(agent_prompt: str, user_context: str, api_key: str, model: str) -> tuple[str, dict]:
    """同步 LLM 调用（OpenAI 兼容协议），返回 (content, usage)。"""
    _, base_url, model_name = get_llm_config(model)
    api_key = resolve_api_key(api_key)
    req = build_chat_request(base_url, api_key, {
        "model": model_name,
        "messages": [
            {"role": "system", "content": agent_prompt},
            {"role": "user", "content": user_context},
        ],
        "temperature": 0.3,
        "max_tokens": 8000,
        "stream": False,
    })
    import urllib.request
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    usage = extract_usage(data, user_context)
    return content, usage.to_dict()


async def _call_agent_llm(agent_prompt: str, user_context: str, api_key: str, model: str,
                          budget: Optional[LoopBudget] = None, agent_label: str = "agent") -> str:
    """异步包装：LLM 调用放线程池，不阻塞事件循环。

    如果传入 budget，自动记录 token 消耗并检查预算/kill switch。
    """
    if budget:
        budget.check_pause()
    content, usage_dict = await asyncio.to_thread(_call_llm_sync, agent_prompt, user_context, api_key, model)
    if budget:
        usage = Usage(**usage_dict)
        budget.record(agent_label, usage)
    return content


def _parse_json(text: str):
    """容错 JSON 解析（R1）：直接解析 → 提取 ```json 代码块 → 提取第一个 {...}。"""
    text = text.strip()
    # 尝试 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试 2: 提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 尝试 3: 提取第一个 {...}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _validate_model(data: dict, model_cls):
    """用 Pydantic 校验并归一化；失败返回 (None, 错误信息)。"""
    try:
        return model_cls(**data), ""
    except Exception as e:
        return None, str(e)


# ── P3: test_level 分层辅助 ─────────────────────────────────────

_LEVEL_RANK = {"skip": 0, "smoke": 1, "full": 2}


def _max_test_level(plan: Plan) -> str:
    """取计划中所有步骤的最高 test_level（用于分层 gate 校验）。"""
    if not plan.steps:
        return "skip"
    return max((s.test_level.value for s in plan.steps), key=lambda v: _LEVEL_RANK.get(v, 0))


# ── Builder 落盘（D4: 直接落盘 + git 快照兜底）──────────────────

def _resolve_safe_project_dir(project_dir: str) -> Optional[str]:
    """解析落盘目录并校验无路径穿越（安全规则 #6）。

    - 相对路径：限制在 _AGENTS_ROOT 下。
    - 绝对路径：允许用户显式指定目录（如真实项目路径），但 realpath 必须落在该路径下。
    """
    if not project_dir:
        return None
    if os.path.isabs(project_dir):
        real = os.path.realpath(project_dir)
        target = os.path.realpath(os.path.join(real, "."))
        if os.path.commonpath([real, target]) != real:
            logger.warning("拒绝越界落盘目录: %s", project_dir)
            return None
        return target
    root = os.path.realpath(_AGENTS_ROOT)
    target = os.path.realpath(os.path.join(root, project_dir))
    if os.path.commonpath([root, target]) != root:
        logger.warning("拒绝越界落盘目录: %s (root=%s)", project_dir, root)
        return None
    return target


def _apply_build(build: BuildOutput, project_dir: str) -> dict:
    """把 Builder 的 changed_files 落盘。返回 {applied, skipped, snapshot_hash, effects}。

    落盘前执行 git stash create 记录快照（原 builder.md:29-37 设计）。
    P1: 落盘过程通过 effects 模块记录结构化副作用（含原文），支持精确回滚。
    """
    target = _resolve_safe_project_dir(project_dir)
    if not target:
        return {"applied": False, "skipped": len(build.changed_files), "snapshot_hash": "clean",
                "effects": [], "reason": "project_dir 为空或越界，未落盘"}

    os.makedirs(target, exist_ok=True)

    # git 快照（D4）：若目标在 git 仓库内
    snapshot = "clean"
    try:
        res = subprocess.run(
            ["git", "-C", target, "stash", "create"],
            capture_output=True, text=True, timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            snapshot = res.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning("git stash create 失败: %s", e)

    # P1: 结构化落盘 + effect 记录（含路径穿越防护）
    result = apply_build_files(build.changed_files, target)
    return {
        "applied": result["applied"],
        "skipped": result["skipped"],
        "snapshot_hash": snapshot,
        "effects": result["effects"],
    }


# ── Checkpoint ───────────────────────────────────────────────────

async def _wait_decision(loop_id: int, title: str, payload: dict) -> dict:
    """暂停等待用户 checkpoint 决策（D7）。返回用户 decision dict。

    注意 clear 必须在 emit 之前：决策方（测试/API）可能在任何时刻 set，
    若先 emit 再 clear 会把决策信号清掉，导致永久等待。
    """
    runtime = _runtimes.get(loop_id)
    runtime.checkpoint_event.clear()
    runtime.decision = None

    db.update_loop_group(loop_id, status="awaiting_signoff", current_agent="system")
    await _emit(loop_id, "system", "checkpoint", {"title": title, **payload})

    await runtime.checkpoint_event.wait()
    return runtime.decision or {"decision": "continue", "note": ""}


# ── 主流程 ───────────────────────────────────────────────────────

async def run_loop(
    loop_id: int, api_key: str, model: str, user_id: Optional[int] = None,
    role_models: Optional[dict] = None,
    mode: str = "interactive",
    project_name: str = "",
):
    """Loop 主流程（后台任务入口）。

    P4: role_models = {"planner": "gpt-4o-mini", ...} 每个 agent 独立模型（per-role）。
    缺省回退到全局 model，再由 get_llm_config 回退环境变量。

    新增:
    - mode: interactive（默认）/ L1（report，只读分析+更新STATE）/ L2（action，需用户确认后落盘）
    - project_name: 用于读写 project STATE。
    """
    loop_group = db.get_loop_group(loop_id)
    if not loop_group:
        return
    task_desc = loop_group["task_desc"]
    project_dir = loop_group["project_dir"] or ""
    role_models = role_models or {}
    get_runtime(loop_id)

    budget = LoopBudget(loop_id=loop_id, budget=get_loop_budget(loop_id))
    # 尝试从任务/项目目录推断 project_name
    project_name = project_name or _infer_project_name(task_desc, project_dir)
    project_state = load_project_state(user_id, project_name, project_dir)
    # P1: 最近一次落盘的 effects（异常终止时用于精确回滚）
    last_effects: list[dict] = []

    # P0-2: 清理 STATE 过时数据
    project_state = prune_state(project_state)

    # P0-1: 加载安全门控
    gate = LoopGate(project_dir)
    gate.load()

    # P1-3: 加载用户约束
    constraints_text = _load_constraints(project_dir)

    # P1-5: 分支锁碰撞检测（action 模式）
    branch_name = "main"
    try:
        from .worktree import get_main_branch
        branch_name = get_main_branch(project_dir) if project_dir and is_git_repo(project_dir) else "main"
    except Exception:
        pass
    lock_acquired = False
    if mode in ("L2", "interactive"):
        lock_acquired = db.acquire_branch_lock(project_dir, branch_name, loop_id)
        if not lock_acquired:
            logger.warning("Loop %s: 分支 %s 已被其他 loop 占用，跳过", loop_id, branch_name)
            await _emit(loop_id, "system", "loop_skipped", {
                "reason": f"分支 {branch_name} 已被其他 loop 占用",
                "collision": True,
            })
            await _finish(loop_id, "failed")
            return
        project_state.acting_on = f"branch:{branch_name}:loop:{loop_id}"

    # P1-4: 创建 run_log
    run_log_id = db.create_run_log(
        loop_id=loop_id,
        loop_group_id=loop_id,
        user_id=user_id or 0,
        project_name=project_name,
        pattern="schedule" if "schedule-" in loop_group.get("session_id", "") else "manual",
        started_at=datetime.now().isoformat(),
    )
    run_log_start = datetime.now()

    await _emit(loop_id, "system", "spawn", {"agent": "loop", "task": task_desc, "time": datetime.now().isoformat()})

    try:
        # ── Phase 0: 上下文注入（复用 memory/restore.py）+ STATE 脊柱 + 约束 ──
        context_bits = []
        has_project = False
        if user_id:
            try:
                from ..memory import restore_context
                ctx = restore_context(user_id)
                if ctx.get("has_context"):
                    context_bits.append(
                        f"## 用户上下文\n{json.dumps({'profile': ctx['user_profile'], 'project': ctx['current_project']}, ensure_ascii=False)}"
                    )
                    has_project = bool(ctx.get("current_project"))
            except Exception as e:
                logger.warning("上下文恢复失败: %s", e)

        # 注入 durable STATE（约束/未解决问题/历史 critique）
        context_bits.append(project_state.summary_text())

        # P1-3: 注入用户约束
        context_bits.append(constraints_text)

        # P2: 注入可用技能清单（registry 服务发现，供 Planner 按需选用）
        try:
            context_bits.append(f"## 可用技能\n{default_registry().skills_summary()}")
        except Exception as e:  # noqa: BLE001
            logger.warning("技能注册表加载失败（跳过注入）: %s", e)

        # P6: 文件记忆注入（扫描→小模型选择→预算注入→过期警告）
        try:
            from ..memory.file_memory import build_file_memory_context
            fm_root = project_dir if (project_dir and os.path.isdir(project_dir)) else os.getenv("FILE_MEMORY_ROOT", "")
            if not fm_root and os.path.isdir(os.path.join(_AGENTS_ROOT, "data", "memory")):
                fm_root = os.path.join(_AGENTS_ROOT, "data", "memory")
            if fm_root and os.path.isdir(fm_root):
                fm_ctx, fm_stats = await asyncio.to_thread(
                    build_file_memory_context,
                    task_desc, fm_root, api_key, model, loop_group["session_id"],
                    (lambda u: budget.record("memory", Usage(**u))) if budget else None,
                )
                if fm_ctx:
                    context_bits.append(fm_ctx)
                    await _emit(loop_id, "system", "memory_injected", {
                        "root": fm_stats.get("root"),
                        "scanned": fm_stats.get("scanned"),
                        "selected": fm_stats.get("selected"),
                        "injected_bytes": fm_stats.get("injected_bytes"),
                        "stale": fm_stats.get("stale"),
                    })
        except Exception as e:
            logger.warning("文件记忆注入失败（跳过）: %s", e)

        context_bits.append(f"## 任务\n{task_desc}")
        user_context = "\n\n".join(context_bits)

        # P4: Master 冷启动 — 用户无项目上下文时先做需求对齐
        if user_id and not has_project:
            db.update_loop_group(loop_id, current_agent="master")
            await _emit(loop_id, "master", "spawn", {"mode": "cold_start", "model": role_models.get("master") or model})
            try:
                master_bits, _ = await asyncio.to_thread(
                    _master_bootstrap, task_desc, api_key, model, user_id, budget
                )
                if master_bits:
                    # Bug #15: 用 master_done 而非通用 done（否则前端 buildSteps 无法识别完成）
                    await _emit(loop_id, "master", "master_done", {})
                    user_context += "\n\n" + master_bits
            except Exception as e:
                logger.warning("Master 冷启动失败（跳过，继续 Planner）: %s", e)

        wt = None
        # ── spawn Planner（含 CP1 调整循环）──
        # Bug #14: adjust 决策必须带 note 退回 Planner 重新规划，而非直接继续
        adjust_notes: list[str] = []
        while True:
            db.update_loop_group(loop_id, current_agent="planner")
            await _emit(loop_id, "planner", "spawn", {"model": role_models.get("planner") or model})
            planner_ctx = user_context
            if adjust_notes:
                planner_ctx += "\n\n## 用户调整意见（覆盖原计划的约束）\n" + "\n".join(
                    f"- {n}" for n in adjust_notes
                )
            raw_plan = await _call_agent_llm(PLANNER_PROMPT, planner_ctx, api_key, role_models.get("planner") or model,
                                             budget=budget, agent_label="planner")
            plan_data = _parse_json(raw_plan)
            if plan_data is None:
                raise RuntimeError("Planner 输出无法解析为 JSON")
            plan, err = _validate_model(plan_data, Plan)
            if plan is None:
                raise RuntimeError(f"Planner 输出不符合 Plan schema: {err}")

            db.update_loop_group(loop_id, plan_json=plan.model_dump_json())
            await _emit(loop_id, "planner", "plan", {
                "task_name": plan.task_name,
                "steps": [s.model_dump() for s in plan.steps],
                "gates": [g.model_dump() for g in plan.gates],
                "adjust_notes": adjust_notes,
            })

            # CP1: 计划确认
            decision = await _wait_decision(loop_id, "计划已产出，是否开始执行？", {
                "options": ["continue", "adjust", "rollback"],
                "plan": plan.model_dump(),
            })
            if decision["decision"] == "rollback":
                await _finish(loop_id, "failed")
                return
            if decision["decision"] == "adjust":
                note = (decision.get("note") or "").strip()
                if not note:
                    # 空意见：视为继续（前端已要求必填，双保险）
                    break
                adjust_notes.append(note)
                await _emit(loop_id, "planner", "plan_adjusted", {"note": note})
                continue  # 退回 Planner 重新规划
            break  # continue

        # P1-6: Early exit — 空 watchlist 直接退出
        if _should_early_exit(plan, mode):
            await _emit(loop_id, "system", "loop_idle", {
                "reason": "Planner 未发现需要处理的问题",
                "mode": mode,
            })
            db.update_run_log(run_log_id,
                finished_at=datetime.now().isoformat(),
                duration_s=(datetime.now() - run_log_start).total_seconds(),
                items_found=0, files_changed=0, iterations=0,
                outcome="success",
                total_tokens=budget.used.total_tokens,
                prompt_tokens=budget.used.prompt_tokens,
                completion_tokens=budget.used.completion_tokens,
            )
            update_state_after_loop(
                user_id, project_name, project_dir,
                status="idle",
                summary="Planner 未发现需要处理的问题",
                open_problems=[],
                new_constraints=plan.forbidden_paths,
                tokens_used=budget.used.total_tokens,
            )
            if lock_acquired:
                db.release_branch_lock(project_dir, branch_name)
            await _emit(loop_id, "system", "done", {"mode": mode, "status": "idle_noop"})
            await _finish(loop_id, "done")
            return

        # ── L1 Report Mode：只读分析 + 更新 STATE，不落盘 ──
        if mode == "L1":
            report_summary = f"L1 report: {plan.task_name}; {len(plan.steps)} steps planned"
            await _emit(loop_id, "system", "report", {
                "summary": report_summary,
                "plan": plan.model_dump(),
            })
            update_state_after_loop(
                user_id, project_name, project_dir,
                status="report",
                summary=report_summary,
                open_problems=[s.desc for s in plan.steps if s.test_level != "skip"],
                new_constraints=plan.forbidden_paths,
                tokens_used=budget.used.total_tokens,
            )
            db.update_run_log(run_log_id,
                finished_at=datetime.now().isoformat(),
                duration_s=(datetime.now() - run_log_start).total_seconds(),
                items_found=len(plan.steps), files_changed=0, iterations=0,
                outcome="success",
                total_tokens=budget.used.total_tokens,
                prompt_tokens=budget.used.prompt_tokens,
                completion_tokens=budget.used.completion_tokens,
            )
            if lock_acquired:
                db.release_branch_lock(project_dir, branch_name)
            await _emit(loop_id, "system", "done", {"mode": "L1", "status": "report"})
            await _finish(loop_id, "done")
            return

        # 阶段性汇报预算
        async def _emit_budget():
            await _emit(loop_id, "system", "budget", budget.summary())

        # ── spawn Builder ──
        db.update_loop_group(loop_id, current_agent="builder")
        await _emit(loop_id, "builder", "spawn", {"model": role_models.get("builder") or model})
        build_ctx = f"## 执行计划\n{json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)}\n\n## 任务\n{task_desc}"
        raw_build = await _call_agent_llm(BUILDER_PROMPT, build_ctx, api_key, role_models.get("builder") or model,
                                          budget=budget, agent_label="builder")
        build_data = _parse_json(raw_build)
        if build_data is None:
            raise RuntimeError("Builder 输出无法解析为 JSON")
        build, err = _validate_model(build_data, BuildOutput)
        if build is None:
            raise RuntimeError(f"Builder 输出不符合 BuildOutput schema: {err}")

        # P5: Worktree 隔离 — 在独立 git worktree 落盘，失败即弃
        worktree_path = project_dir
        wt = None
        if is_git_repo(project_dir):
            try:
                wt = Worktree(project_dir, loop_id)
                worktree_path = wt.create()
                await _emit(loop_id, "system", "worktree_created", {"path": worktree_path})
            except Exception as e:
                logger.warning("创建 worktree 失败，回退到主目录落盘: %s", e)
                wt = None

        # P0-1: Gate 机械检查 — Builder 落盘前拦截 denylist 文件
        gate_result = gate.check_build(build.changed_files)
        if not gate_result.passed:
            logger.warning("Loop %s: Gate denylist 命中: %s", loop_id,
                           [(h["path"], h["pattern"]) for h in gate_result.hits])
            await _emit(loop_id, "system", "denylist_hit", {
                "hits": gate_result.hits,
                "action": gate.on_hit.get("action", "abort_immediately"),
            }, notify=True)
            if gate_result.abort:
                if wt:
                    wt.discard()
                db.update_run_log(run_log_id,
                    finished_at=datetime.now().isoformat(),
                    duration_s=(datetime.now() - run_log_start).total_seconds(),
                    denylist_hits=len(gate_result.hits),
                    outcome="failed",
                    total_tokens=budget.used.total_tokens,
                )
                if lock_acquired:
                    db.release_branch_lock(project_dir, branch_name)
                await _emit(loop_id, "system", "error", {
                    "message": f"Gate 拦截: Builder 尝试修改 denylist 中的文件 {[h['path'] for h in gate_result.hits]}"
                }, notify=True)
                await _finish(loop_id, "failed")
                return

        apply_result = _apply_build(build, worktree_path)
        last_effects = apply_result.get("effects", [])
        # P4: 执行 Builder 的验证命令，产出 Reviewer 证据
        verify_results = _run_verification(build.verification_commands, worktree_path)
        # P3: 测试分层校验（test_level → 验证充分性证据）
        verify_gate = gate.check_verification(build.verification_commands, _max_test_level(plan))
        await _emit(loop_id, "builder", "builder_done", {
            "summary": build.summary,
            "changed_files": build.changed_files,
            "plan_deviations": build.plan_deviations,
            "apply": apply_result,
            "verification": verify_results,
            "verification_gate": {
                "passed": verify_gate.passed,
                "warnings": verify_gate.warnings,
                "test_level": _max_test_level(plan),
            },
        })
        await _emit_budget()

        # ── spawn Reviewer（迭代熔断：PARTIAL_FAIL 退回 Builder ≤3 次）──
        iteration = 0
        while True:
            iteration += 1
            db.update_loop_group(loop_id, current_agent="reviewer")
            await _emit(loop_id, "reviewer", "spawn", {"iteration": iteration, "model": role_models.get("reviewer") or model})
            review_ctx = (
                f"## 执行计划\n{json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)}\n\n"
                f"## Builder 输出\n{json.dumps(build.model_dump(), ensure_ascii=False, indent=2)}\n\n"
                f"## 实际执行证据（命令输出）\n{json.dumps(verify_results, ensure_ascii=False, indent=2)}\n\n"
                f"## 测试分层校验（P3）\n{json.dumps({'passed': verify_gate.passed, 'warnings': verify_gate.warnings, 'test_level': _max_test_level(plan)}, ensure_ascii=False, indent=2)}"
            )
            raw_review = await _call_agent_llm(REVIEWER_PROMPT, review_ctx, api_key, role_models.get("reviewer") or model,
                                               budget=budget, agent_label="reviewer")
            review_data = _parse_json(raw_review)
            if review_data is None:
                raise RuntimeError("Reviewer 输出无法解析为 JSON")
            review, err = _validate_model(review_data, ReviewResult)
            if review is None:
                raise RuntimeError(f"Reviewer 输出不符合 ReviewResult schema: {err}")

            await _emit(loop_id, "reviewer", "verdict", {
                "verdict": review.verdict.value,
                "stage_results": [s.model_dump() for s in review.stage_results],
                "fail_reason": review.fail_reason,
                "fix_direction": review.fix_direction,
            })
            await _emit_budget()

            if review.verdict == Verdict.ALL_PASS:
                break
            if review.verdict == Verdict.CRITICAL_FAIL or iteration >= MAX_ITER:
                # 迭代熔断：升级给人（Bug #12: 带详细失败原因，供前端 UX 呈现）
                await _emit(loop_id, "system", "loop_failed", {
                    "verdict": review.verdict.value,
                    "fail_reason": review.fail_reason,
                    "fix_direction": review.fix_direction,
                    "iteration": iteration,
                    "max_iter": MAX_ITER,
                }, notify=True)
                db.update_run_log(run_log_id,
                    finished_at=datetime.now().isoformat(),
                    duration_s=(datetime.now() - run_log_start).total_seconds(),
                    items_found=len(plan.steps),
                    files_changed=len(build.changed_files),
                    iterations=iteration,
                    outcome="failed",
                    total_tokens=budget.used.total_tokens,
                    prompt_tokens=budget.used.prompt_tokens,
                    completion_tokens=budget.used.completion_tokens,
                    escalations=1,
                )
                if lock_acquired:
                    db.release_branch_lock(project_dir, branch_name)
                await _finish(loop_id, "failed")
                return
            # PARTIAL_FAIL → 退回 Builder 修复（把 fix_direction 带回 Builder）
            db.update_loop_group(loop_id, iteration_count=iteration, current_agent="builder")
            await _emit(loop_id, "system", "retry", {
                "iteration": iteration,
                "max_iter": MAX_ITER,
                "fix_direction": review.fix_direction,
            })
            build_ctx += f"\n\n## Reviewer 退回意见\n{review.fix_direction}"
            raw_build = await _call_agent_llm(BUILDER_PROMPT, build_ctx, api_key, role_models.get("builder") or model,
                                          budget=budget, agent_label="builder")
            build_data = _parse_json(raw_build)
            if build_data is None:
                raise RuntimeError("Builder 退回修复输出无法解析为 JSON")
            build, err = _validate_model(build_data, BuildOutput)
            if build is None:
                raise RuntimeError(f"Builder 退回修复不符合 BuildOutput schema: {err}")
            # P0-1: 退回重试同样做 gate 检查
            gate_result = gate.check_build(build.changed_files)
            if not gate_result.passed and gate_result.abort:
                if wt:
                    wt.discard()
                db.update_run_log(run_log_id,
                    finished_at=datetime.now().isoformat(),
                    duration_s=(datetime.now() - run_log_start).total_seconds(),
                    denylist_hits=len(gate_result.hits),
                    iterations=iteration,
                    outcome="failed",
                    total_tokens=budget.used.total_tokens,
                )
                if lock_acquired:
                    db.release_branch_lock(project_dir, branch_name)
                await _emit(loop_id, "system", "denylist_hit", {"hits": gate_result.hits}, notify=True)
                await _emit(loop_id, "system", "error", {"message": "Gate 拦截重试"}, notify=True)
                await _finish(loop_id, "failed")
                return
            apply_result = _apply_build(build, worktree_path)
            last_effects = apply_result.get("effects", [])
            # P4: 退回重试后同样执行验证命令
            verify_results = _run_verification(build.verification_commands, worktree_path)
            # P3: 退回重试后同样做测试分层校验
            verify_gate = gate.check_verification(build.verification_commands, _max_test_level(plan))
            await _emit(loop_id, "builder", "builder_done", {
                "summary": build.summary,
                "changed_files": build.changed_files,
                "plan_deviations": build.plan_deviations,
                "apply": apply_result,
                "verification": verify_results,
                "verification_gate": {
                    "passed": verify_gate.passed,
                    "warnings": verify_gate.warnings,
                    "test_level": _max_test_level(plan),
                },
            })

        # ── P4: User Agent UX 审查（Reviewer ALL_PASS 后触发）──
        # 非前端任务 → UX_SKIPPED 不阻塞；前端任务 → 文本视角审查 + 可选的 playwright 截图
        db.update_loop_group(loop_id, current_agent="user")
        await _emit(loop_id, "user", "spawn", {"model": role_models.get("user") or model})
        # 同步函数：LLM 调用在线程池外直连（同 _master_bootstrap 模式）
        ux_result, _ = await asyncio.to_thread(
            _run_ux_review, build, task_desc, api_key, role_models.get("user") or model, budget
        )
        await _emit(loop_id, "user", "ux_review", ux_result.model_dump() if ux_result else {"overall": "UX_SKIPPED"})
        await _emit_budget()

        if ux_result and ux_result.overall == "FAIL":
            # UX 失败：退回 Builder（带审查意见），同问题 2 轮升级（简化：直接升级给人）
            await _emit(loop_id, "user", "ux_escalate", {
                "summary": ux_result.summary,
                "fail_checks": [
                    {"perspective": "user" if c in ux_result.user_perspective else "designer",
                     "checkpoint": c.checkpoint, "issue": c.issue, "locations": c.code_locations}
                    for c in ux_result.user_perspective + ux_result.designer_perspective if c.result == "FAIL"
                ],
            }, notify=True)
            db.update_run_log(run_log_id,
                finished_at=datetime.now().isoformat(),
                duration_s=(datetime.now() - run_log_start).total_seconds(),
                items_found=len(plan.steps),
                files_changed=len(build.changed_files),
                iterations=iteration,
                outcome="failed",
                total_tokens=budget.used.total_tokens,
                prompt_tokens=budget.used.prompt_tokens,
                completion_tokens=budget.used.completion_tokens,
                escalations=1,
            )
            if lock_acquired:
                db.release_branch_lock(project_dir, branch_name)
            await _finish(loop_id, "failed")
            return

        # ── CP2: 最终签字（D7）──
        # L2 action 模式：需要用户确认；其余正常确认
        decision = await _wait_decision(loop_id, "全部完成，是否标记完成？", {
            "options": ["approve", "reject"],
            "final_summary": {
                "task": task_desc,
                "plan_steps": len(plan.steps),
                "changed_files": [f.get("path") for f in build.changed_files],
                "verdict": review.verdict.value,
            },
        })
        if decision["decision"] == "approve":
            # P5: 用户确认后，把 worktree 合并回主分支
            merge_info = {"ok": True, "output": "no worktree"}
            if wt and wt.worktree_path:
                merge_info = wt.apply_to_main()
                wt.discard()
                await _emit(loop_id, "system", "worktree_merged", merge_info)
                if not merge_info.get("ok"):
                    await _emit(loop_id, "system", "error", {"message": f"worktree 合并失败: {merge_info.get('output')}"})
                    db.update_run_log(run_log_id,
                        finished_at=datetime.now().isoformat(),
                        duration_s=(datetime.now() - run_log_start).total_seconds(),
                        items_found=len(plan.steps),
                        files_changed=len(build.changed_files),
                        iterations=iteration,
                        outcome="failed",
                        human_decision="approved",
                        total_tokens=budget.used.total_tokens,
                        prompt_tokens=budget.used.prompt_tokens,
                        completion_tokens=budget.used.completion_tokens,
                    )
                    if lock_acquired:
                        db.release_branch_lock(project_dir, branch_name)
                    await _finish(loop_id, "failed")
                    return

            await _emit(loop_id, "system", "done", {"verdict": review.verdict.value})
            await _finish(loop_id, "done")

            # P5: 更新 STATE + Post-Run Critique
            try:
                critique = generate_critique(task_desc, plan.model_dump(), build.model_dump(),
                                             review.model_dump(), ux_result.model_dump() if ux_result else None,
                                             project_state, budget)
                summary = f"Loop completed: {build.summary or review.verdict.value}"
                update_state_after_loop(
                    user_id, project_name, project_dir,
                    status="done",
                    summary=summary,
                    open_problems=[r.fail_reason for r in review.stage_results if r.status != "PASS"],
                    new_constraints=plan.forbidden_paths + (critique.get("adjustment_suggestions") or []),
                    tokens_used=budget.used.total_tokens,
                    critique=critique,
                )
            except Exception as e:
                logger.warning("更新 STATE/critique 失败: %s", e)

            # P1-4: 完成 run_log
            db.update_run_log(run_log_id,
                finished_at=datetime.now().isoformat(),
                duration_s=(datetime.now() - run_log_start).total_seconds(),
                items_found=len(plan.steps),
                files_changed=len(build.changed_files),
                iterations=iteration,
                outcome="success",
                human_decision="approved",
                total_tokens=budget.used.total_tokens,
                prompt_tokens=budget.used.prompt_tokens,
                completion_tokens=budget.used.completion_tokens,
                denylist_hits=len(gate_result.hits),
                escalations=1 if review.verdict == Verdict.CRITICAL_FAIL else 0,
            )

            # P2-8: 降级检查（loop 完成后评估）
            try:
                token_pct = budget.used.total_tokens / max(budget.budget, 1)
                # 从 run_logs 计算近期升级次数
                recent_logs = db.get_run_logs(user_id or 0, project_name, days=2, limit=10)
                recent_escalations = sum(1 for rl in recent_logs if rl.get("escalations", 0) > 0)
                new_level = check_graduation_demotion(
                    project_state, 0.0, token_pct, recent_escalations
                )
                if new_level:
                    logger.warning("Loop %s: 触发降级 %s -> %s", loop_id, project_state.graduation_level, new_level)
                    project_state.graduation_level = new_level
                    project_state.graduation_progress = {
                        "demoted_at": datetime.now().isoformat(),
                        "reason": f"降级自 {project_state.graduation_level} 到 {new_level}",
                    }
                    await _emit(loop_id, "system", "graduation_demoted", {
                        "from_level": project_state.graduation_level,
                        "to_level": new_level,
                    }, notify=True)
            except Exception as e:
                logger.warning("降级检查失败: %s", e)

            # P1-5: 释放分支锁
            if lock_acquired:
                project_state.acting_on = None
                db.release_branch_lock(project_dir, branch_name)
                save_project_state(user_id, project_state)

        else:
            if wt:
                wt.discard()
            db.update_run_log(run_log_id,
                finished_at=datetime.now().isoformat(),
                duration_s=(datetime.now() - run_log_start).total_seconds(),
                items_found=len(plan.steps),
                files_changed=len(build.changed_files),
                iterations=iteration,
                outcome="failed",
                human_decision="rejected",
                total_tokens=budget.used.total_tokens,
                prompt_tokens=budget.used.prompt_tokens,
                completion_tokens=budget.used.completion_tokens,
            )
            if lock_acquired:
                db.release_branch_lock(project_dir, branch_name)
            await _emit(loop_id, "system", "error", {"message": "用户拒绝签字"})
            await _finish(loop_id, "failed")

    except BudgetExhausted as e:
        logger.warning("Loop %s token 预算耗尽: %s/%s", loop_id, e.used, e.budget)
        if wt:
            wt.discard()
        await _emit(loop_id, "system", "budget_exhausted", {"used": e.used, "budget": e.budget}, notify=True)
        db.update_run_log(run_log_id,
            finished_at=datetime.now().isoformat(),
            duration_s=(datetime.now() - run_log_start).total_seconds(),
            outcome="paused",
            budget_warnings=1,
            total_tokens=budget.used.total_tokens,
            prompt_tokens=budget.used.prompt_tokens,
            completion_tokens=budget.used.completion_tokens,
        )
        if lock_acquired:
            db.release_branch_lock(project_dir, branch_name)
        await _finish(loop_id, "paused")

    except LoopPaused:
        logger.warning("Loop %s 被全局 pause-all 暂停", loop_id)
        if wt:
            # 不丢弃 worktree，可能后续恢复
            pass
        await _emit(loop_id, "system", "paused", {"reason": "loop-pause-all"}, notify=True)
        db.update_run_log(run_log_id,
            finished_at=datetime.now().isoformat(),
            duration_s=(datetime.now() - run_log_start).total_seconds(),
            outcome="paused",
            total_tokens=budget.used.total_tokens,
        )
        # 不释放分支锁（可能后续恢复）
        await _finish(loop_id, "paused")

    except Exception as e:
        logger.exception("Loop %s 执行异常", loop_id)
        if wt:
            wt.discard()
        elif last_effects:
            # P1: 非 worktree（直接落盘）场景 → 精确回滚已应用的副作用
            try:
                rv = revert_effects(last_effects, worktree_path)
                logger.info("Loop %s 已回滚 %d 个副作用 (failed=%d)",
                            loop_id, rv["reverted"], len(rv["failed"]))
            except Exception as re:  # noqa: BLE001
                logger.warning("Loop %s effects 回滚失败: %s", loop_id, re)
        await _emit(loop_id, "system", "error", {"message": str(e)}, notify=True)
        db.update_run_log(run_log_id,
            finished_at=datetime.now().isoformat(),
            duration_s=(datetime.now() - run_log_start).total_seconds(),
            outcome="failed",
            total_tokens=budget.used.total_tokens,
            prompt_tokens=budget.used.prompt_tokens,
            completion_tokens=budget.used.completion_tokens,
            escalations=1,
        )
        if lock_acquired:
            db.release_branch_lock(project_dir, branch_name)
        await _finish(loop_id, "failed")
