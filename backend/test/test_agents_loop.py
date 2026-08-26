"""Agent Loop orchestrator 端到端测试（mock LLM，不依赖外部 API）。

落地文档: docs/AGENT-LOOP-INTEGRATION.md §6.4
覆盖:
- Planner→Builder→Reviewer 直线跑通 → ALL_PASS → CP2 签字 → done
- PARTIAL_FAIL → 退回 Builder 重试 → 最终 ALL_PASS
- CRITICAL_FAIL → 立即终止 → failed
- 迭代熔断（MAX_ITER 超限）
"""

import json
import asyncio
import uuid

import pytest

from app.agents import db
from app.agents.orchestrator import run_loop, get_runtime, MAX_ITER


PLAN_JSON = {
    "task_name": "写 hello.py",
    "steps": [
        {"index": 1, "desc": "创建 hello.py", "verify": "python hello.py 输出 Hello World",
         "test_level": "skip", "files": ["hello.py"]}
    ],
    "gates": [{"gate_id": "G1", "check": "python hello.py", "pass_criteria": "输出 Hello World"}],
    "forbidden_paths": [],
    "impact_analysis": "不适用",
    "assumptions": ["无"],
}

BUILD_JSON = {
    "summary": "创建 hello.py",
    "changed_files": [{"path": "hello.py", "action": "create", "content": "print('Hello World')\n"}],
    "snapshot_hash": "clean",
    "plan_deviations": [],
}

REVIEW_PASS = {"verdict": "ALL_PASS", "stage_results": [{"stage": "1", "item": "G1", "result": "PASS", "evidence": "python hello.py 输出 Hello World"}], "fail_reason": "", "fix_direction": ""}
REVIEW_PARTIAL = {"verdict": "PARTIAL_FAIL", "stage_results": [], "fail_reason": "G1 未过", "fix_direction": "修正 hello.py 输出"}


async def _run_loop_with_decisions(loop_id, api_key, model, decisions=None):
    """同时启动 run_loop 与决策监听器（两者必须同事件循环）。"""
    decisions = decisions or []
    runtime = get_runtime(loop_id)
    idx = {"n": 0}  # 可变容器：避免闭包内 i += 1 触发 UnboundLocalError

    async def _driver():
        while True:
            item = await runtime.events.get()
            if item is None:
                return db.get_loop_group(loop_id)
            if item["event_type"] == "checkpoint":
                decision = decisions[idx["n"]] if idx["n"] < len(decisions) else "continue"
                idx["n"] += 1
                # adjust 决策带调整意见（Bug #14 测试）
                note = "不要修改 config.py" if decision == "adjust" else ""
                db.add_loop_event(loop_id, "user", "user_decision", {"decision": decision, "note": note})
                runtime.decision = {"decision": decision, "note": note}
                runtime.checkpoint_event.set()

    loop_task = asyncio.create_task(run_loop(loop_id, api_key, model, None))
    driver_task = asyncio.create_task(_driver())
    await loop_task
    return await driver_task


class TestLoopArchive:
    """P3: markdown 归档（loop 结束后自动生成 data/agent-loops/{loop_id}.md）"""

    def test_archive_content(self, tmp_path, monkeypatch):
        from app.agents.orchestrator import _archive_loop, _AGENTS_ROOT

        # 指向临时目录，避免污染真实 data/
        monkeypatch.setattr("app.agents.orchestrator._AGENTS_ROOT", str(tmp_path))

        loop_id = db.create_loop_group(None, "sess-arch", "写 hello.py")
        db.add_loop_event(loop_id, "system", "spawn", {"agent": "loop", "task": "写 hello.py"})
        db.add_loop_event(loop_id, "planner", "plan", {
            "task_name": "写 hello.py",
            "steps": [{"index": 1, "desc": "创建 hello.py", "verify": "python hello.py", "test_level": "skip", "files": ["hello.py"]}],
            "gates": [],
        })
        db.add_loop_event(loop_id, "builder", "builder_done", {"summary": "创建 hello.py", "changed_files": [{"path": "hello.py", "action": "create"}]})
        db.add_loop_event(loop_id, "reviewer", "verdict", {"verdict": "ALL_PASS", "stage_results": [{"stage": "1", "item": "G1", "result": "PASS", "evidence": "ok"}]})
        db.add_loop_event(loop_id, "user", "user_decision", {"decision": "approve"})
        db.add_loop_event(loop_id, "system", "done", {})
        db.update_loop_group(loop_id, status="done")

        path = _archive_loop(loop_id)
        assert path.endswith(f"agent-loops/{loop_id}.md")
        content = (tmp_path / "data" / "agent-loops" / f"{loop_id}.md").read_text(encoding="utf-8")
        # 应包含核心章节
        assert "# Agent Loop" in content
        assert "## 执行计划" in content
        assert "## 验证结果" in content
        assert "## 事件时间线" in content
        assert "ALL_PASS" in content
        assert "用户: approve" in content


class TestRunVerification:
    """P4: Builder 验证命令执行（安全边界）"""

    def _run(self, commands, project_dir, tmp_path):
        from app.agents import orchestrator as orch

        real_resolve = orch._resolve_safe_project_dir

        def fake_resolve(pd):
            root = str(tmp_path)
            import os as _os
            if not pd:
                return None
            target = _os.path.realpath(_os.path.join(root, pd))
            if _os.path.commonpath([root, target]) != root:
                return None
            return target

        # 替换函数引用（避免环境变量在模块导入时被缓存的问题），用完恢复
        orch._resolve_safe_project_dir = fake_resolve
        try:
            return orch._run_verification(commands, project_dir)
        finally:
            orch._resolve_safe_project_dir = real_resolve

    def test_whitelisted_cmd_ok(self, tmp_path):
        import sys
        # 注意：命令在 target = <root>/sub 目录下执行，文件必须放这里
        sub = tmp_path / "sub"
        sub.mkdir(exist_ok=True)
        (sub / "hello.py").write_text("print('Hello World')\n", encoding="utf-8")
        # 用当前解释器路径（sys.executable）而非 "python3"，避免 PATH 差异
        res = self._run([f"{sys.executable} hello.py"], "sub", tmp_path)
        assert res and res[0]["ok"] is True
        assert "Hello World" in res[0]["output"]

    def test_blocked_bin_rejected(self, tmp_path):
        res = self._run(["rm -rf /tmp/evil"], "sub", tmp_path)
        assert res and res[0]["ok"] is False
        assert "不在白名单" in res[0]["error"] or "拒绝执行" in res[0]["error"]

    def test_non_whitelist_rejected(self, tmp_path):
        res = self._run(["powershell hello"], "sub", tmp_path)
        assert res and res[0]["ok"] is False
        assert "拒绝执行" in res[0]["error"]

    def test_out_of_root_rejected(self, tmp_path):
        res = self._run(["python3 hello.py"], "../outside", tmp_path)
        assert res and res[0]["ok"] is False
        assert "越界" in res[0]["error"]

    def test_empty_commands(self, tmp_path):
        assert self._run([], "sub", tmp_path) == []


class TestMasterBootstrap:
    """P4: Master 冷启动需求对齐"""

    def test_bootstrap_saves_context(self, monkeypatch):
        from app.agents import orchestrator as orch

        master_out = {
            "project_name": "纪念日提醒",
            "tech_stack": "python",
            "current_progress": "实现倒计时功能",
            "key_decisions": [{"decision": "用 Flask", "reason": "轻量"}],
            "assumptions": ["需要邮件通知"],
        }
        captured = {}

        # mock LLM：返回结构化 JSON（P5 新增 usage）
        monkeypatch.setattr(
            "app.agents.orchestrator._call_llm_sync",
            lambda prompt, ctx, key, model: (json.dumps(master_out, ensure_ascii=False), {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}),
        )
        # mock save_project_context：捕获参数
        import app.memory.project as mp

        def fake_save(user_id, project_name, tech_stack=None, current_progress=None, key_decisions=None):
            captured.update({
                "user_id": user_id,
                "project_name": project_name,
                "tech_stack": tech_stack,
                "current_progress": current_progress,
                "key_decisions": key_decisions,
            })

        monkeypatch.setattr(mp, "save_project_context", fake_save)

        result, _ = orch._master_bootstrap("实现纪念日提醒", "sk-test", "deepseek-chat", 7)

        assert "Master 需求对齐" in result
        assert captured["project_name"] == "纪念日提醒"
        assert captured["user_id"] == 7
        assert captured["key_decisions"][0]["decision"] == "用 Flask"

    def test_bootstrap_invalid_json(self, monkeypatch):
        from app.agents import orchestrator as orch

        monkeypatch.setattr(
            "app.agents.orchestrator._call_llm_sync",
            lambda *a, **k: ("not json at all", {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}),
        )
        assert orch._master_bootstrap("任务", "sk-test", "deepseek-chat", None) == ("", {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10})


class TestUserAgent:
    """P4: User Agent UX 审查"""

    def test_non_frontend_skipped(self):
        from app.agents.orchestrator import _run_ux_review
        build = {"changed_files": [{"path": "main.py", "action": "create", "content": ""}]}
        from app.agents.schemas import BuildOutput
        result, _ = _run_ux_review(BuildOutput(**build), "写后端", "sk", "m")
        assert result.overall == "UX_SKIPPED"

    def test_frontend_fail_escalates(self, monkeypatch):
        from app.agents.orchestrator import _run_ux_review
        from app.agents.schemas import BuildOutput

        ux_out = {
            "overall": "FAIL",
            "user_perspective": [
                {"checkpoint": "usability", "result": "FAIL", "issue": "按钮无反馈",
                 "severity": "high", "code_locations": [{"file": "app.tsx", "line_range": "10-15", "reason": "无 loading 态"}]}
            ],
            "designer_perspective": [],
            "screenshot_paths": [],
            "summary": "存在 UX 问题",
        }
        monkeypatch.setattr(
            "app.agents.orchestrator._call_llm_sync",
            lambda *a, **k: (json.dumps(ux_out, ensure_ascii=False), {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}),
        )
        build = {"changed_files": [{"path": "app.tsx", "action": "create", "content": "<button>点我</button>"}]}
        result, _ = _run_ux_review(BuildOutput(**build), "写前端页面", "sk", "m")
        assert result.overall == "FAIL"
        assert result.user_perspective[0].code_locations[0]["file"] == "app.tsx"


class TestAdjustLoop:
    """Bug #14: CP1 adjust 决策 → 带 note 退回 Planner 重新规划"""

    def test_adjust_replans_then_continue(self, monkeypatch):
        from app.agents import db

        # 两次 plan（第二次体现调整意见）+ builder + reviewer
        plan_v1 = dict(PLAN_JSON)
        plan_v1["task_name"] = "写 hello.py"
        plan_v2 = dict(PLAN_JSON)
        plan_v2["task_name"] = "写 hello.py（已调整）"
        responses = [plan_v1, plan_v2, BUILD_JSON, REVIEW_PASS]

        calls = {"n": 0}
        captured_ctx = []

        def fake_urlopen(req, timeout=None, **kwargs):
            idx = calls["n"]
            calls["n"] += 1
            # 记录每次 LLM 的 user context（验证调整意见注入）
            body = json.loads(req.data.decode())
            captured_ctx.append(body["messages"][1]["content"])
            return _FakeResp(responses[idx])

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        loop_id = db.create_loop_group(None, "sess-adjust", "写 hello.py")
        # 决策序列：第一次 checkpoint=adjust(带note)，第二次 checkpoint=continue，第三次=approve
        loop = asyncio.run(_run_loop_with_decisions(
            loop_id, "sk-test", "deepseek-chat",
            ["adjust", "continue", "approve"],
        ))
        assert loop["status"] == "done"
        # 两次 Planner + builder + reviewer = 至少 4 次 LLM 调用
        assert len(captured_ctx) >= 4
        # 第二次 planner 上下文应包含调整意见
        assert any("调整意见" in c and "不要修改 config.py" in c for c in captured_ctx)
        # 事件流应有 plan_adjusted
        assert any(e["event_type"] == "plan_adjusted" for e in db.get_loop_events(loop_id))


class TestLoopOrchestrator:
    def _patch_llm(self, monkeypatch, responses):
        """按 Agent 角色路由响应，与调用顺序解耦。

        为什么不按调用次序：API 层测试用 asyncio.create_task 启动 loop，
        且 client fixture 是 session 级，后台 loop 会跨测试存活。这些泄漏
        调用会打乱共享的次序计数器，导致本测试的 Planner 拿到 Reviewer 的
        响应（表现为随机 status=failed）。
        改为按 system prompt 里的角色标识分派，每个角色维护独立序列，
        角色之间互不干扰；序列耗尽时复用该角色最后一个响应。
        """
        # 按响应形状归类到角色（plan 有 steps / build 有 changed_files / review 有 verdict）
        buckets: dict[str, list] = {"planner": [], "builder": [], "reviewer": []}
        for item in responses:
            if "verdict" in item:
                buckets["reviewer"].append(item)
            elif "changed_files" in item:
                buckets["builder"].append(item)
            else:
                buckets["planner"].append(item)

        cursors = {role: 0 for role in buckets}

        # 各角色 prompt 都以「你是 Agent Loop 团队的 X。」开头；
        # 不能用子串匹配（Builder / User Agent 的 prompt 正文也会提到 Reviewer）
        role_markers = (
            ("你是 Agent Loop 团队的 Reviewer", "reviewer"),
            ("你是 Agent Loop 团队的 Builder", "builder"),
            ("你是 Agent Loop 团队的 Planner", "planner"),
        )

        def fake_call_llm_sync(agent_prompt, user_context, api_key, model):
            role = None
            for marker, name in role_markers:
                if marker in agent_prompt:
                    role = name
                    break
            if role is None:
                # Master / User Agent 等其他角色：返回空 JSON，不消耗任何序列
                return "{}", {"total_tokens": 10}

            seq = buckets[role]
            if not seq:
                raise AssertionError(f"测试未为角色 {role} 提供 mock 响应")
            idx = min(cursors[role], len(seq) - 1)
            cursors[role] += 1
            content = seq[idx]
            return json.dumps(content, ensure_ascii=False), {"total_tokens": 100}

        monkeypatch.setattr(
            "app.agents.orchestrator._call_llm_sync", fake_call_llm_sync
        )

    def _run(self, monkeypatch, session, responses, decisions):
        self._patch_llm(monkeypatch, responses)
        # 每个测试用唯一 project_dir：分支锁 key 为 branch-lock:{basename}:{branch}，
        # 若共享 project_dir="" 则所有 loop 测试争抢同一把锁，残留锁会让后续
        # loop 被 skip（status=failed），造成随机失败。唯一目录从根上消除竞争。
        project_dir = f"/tmp/orbit-test-{session}-{uuid.uuid4().hex[:8]}"
        loop_id = db.create_loop_group(None, session, "写 hello.py", project_dir)
        return loop_id, asyncio.run(_run_loop_with_decisions(loop_id, "sk-test", "deepseek-chat", decisions))

    def test_happy_path_all_pass(self, monkeypatch):
        loop_id, loop = self._run(monkeypatch, "sess-happy", [PLAN_JSON, BUILD_JSON, REVIEW_PASS], ["continue", "approve"])
        assert loop["status"] == "done"
        # 事件序列应包含完整链路
        types = [e["event_type"] for e in db.get_loop_events(loop_id)]
        assert "spawn" in types and "plan" in types and "verdict" in types and "done" in types

    def test_happy_path_checkpoint_approve(self, monkeypatch):
        loop_id, loop = self._run(monkeypatch, "sess-approve", [PLAN_JSON, BUILD_JSON, REVIEW_PASS], ["continue", "approve"])
        assert loop["status"] == "done"

    def test_partial_fail_then_pass(self, monkeypatch):
        loop_id, loop = self._run(
            monkeypatch,
            "sess-retry", [PLAN_JSON, BUILD_JSON, REVIEW_PARTIAL, BUILD_JSON, REVIEW_PASS],
            ["continue", "approve"],
        )
        assert loop["status"] == "done"
        # 应有 retry 事件
        assert any(e["event_type"] == "retry" for e in db.get_loop_events(loop_id))

    def test_critical_fail_terminates(self, monkeypatch):
        REVIEW_CRIT = {"verdict": "CRITICAL_FAIL", "stage_results": [], "fail_reason": "越界", "fix_direction": ""}
        loop_id, loop = self._run(monkeypatch, "sess-crit", [PLAN_JSON, BUILD_JSON, REVIEW_CRIT], ["continue"])
        assert loop["status"] == "failed"

    def test_iteration_breaker(self, monkeypatch):
        # 永远 PARTIAL_FAIL → 熔断（MAX_ITER 次后 failed）
        responses = [PLAN_JSON, BUILD_JSON]
        for _ in range(MAX_ITER):
            responses.extend([REVIEW_PARTIAL, BUILD_JSON])
        loop_id, loop = self._run(monkeypatch, "sess-fuse", responses, ["continue"])
        assert loop["status"] == "failed"


class _FakeResp:
    """非流式 LLM 响应（orchestrator 用 stream=False）。"""

    def __init__(self, content):
        self._data = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._data).encode()
