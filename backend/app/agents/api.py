"""Agent Loop API 路由: /api/agents/*

落地文档: docs/AGENT-LOOP-INTEGRATION.md §6.2
- POST /loop            启动 loop（显式触发，D6）
- GET  /loop/{id}       查询 loop + 事件（刷新恢复）
- GET  /loop/{id}/events SSE 事件流（回放 DB 已有事件 + 订阅实时事件）
- POST /loop/{id}/decision  checkpoint 决策（D7 两处暂停的交互）
- GET  /loops           当前用户 loop 列表
- GET/POST/PATCH/DELETE /schedules   定时触发器
- GET/POST /loop/pause-all           全局暂停开关
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import DATA_DIR
from ..middleware.auth import get_optional_user
from ..stream.sse import _sse
from . import db
from .budget import DEFAULT_LOOP_TOKEN_BUDGET, set_loop_budget, get_pause_all, set_pause_all
from .orchestrator import run_loop, get_runtime
from .schedule import compute_next_run, validate_cron
from .schemas import LoopScheduleIn, LoopScheduleOut, GlobalSwitchOut, MetricsSummary, GraduationStatus
from .state import load_project_state, get_graduation_status, save_project_state

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _check_loop_access(loop: Optional[dict], current_user: Optional[dict]):
    """AuthZ（安全规则 #3）：loop 归属校验。匿名 loop（user_id 为空）仅本人/任意登录用户可见。"""
    if not loop:
        raise HTTPException(404, "loop 不存在")
    loop_user = loop.get("user_id")
    current_id = current_user["user_id"] if current_user else None
    if loop_user is not None and loop_user != current_id:
        raise HTTPException(403, "无权访问该 loop")


@router.post("/loop")
async def api_start_loop(
    body: dict = Body(...),
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """启动一个 Agent Loop（显式触发，D6）。"""
    task = (body.get("task") or "").strip()
    if not task:
        raise HTTPException(400, "任务描述不能为空")
    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(400, "session_id 不能为空")

    # 并发冲突检查（R5）：同一 session 不能同时跑两个活跃 loop
    active = db.get_active_loop(session_id)
    if active:
        raise HTTPException(409, f"该会话已有进行中的 loop (#{active['id']})")

    user_id = current_user["user_id"] if current_user else None
    project_dir = (body.get("project_dir") or "").strip()

    loop_id = db.create_loop_group(user_id, session_id, task, project_dir)

    # 读取前端 API Key / 模型（X-API-Key / X-LLM-Model，与 RAG 同链路）
    api_key = request.headers.get("X-API-Key") or None
    model = request.headers.get("X-LLM-Model") or None

    # P4: per-role 模型（X-LLM-Model-Planner / X-LLM-Model-Builder / X-LLM-Model-Reviewer）
    # 缺省回退到全局 X-LLM-Model，再回退环境变量（orchestrator 内处理）
    role_models: dict[str, str] = {}
    for role in ("planner", "builder", "reviewer"):
        rm = request.headers.get(f"X-LLM-Model-{role.title()}")
        if rm:
            role_models[role] = rm

    # P5: 支持 L1(report)/L2(action) 模式 + project_name + token 预算
    mode = (body.get("mode") or "interactive").strip()
    if mode not in ("interactive", "L1", "L2"):
        raise HTTPException(400, "mode 必须是 interactive/L1/L2 之一")
    project_name = (body.get("project_name") or "").strip()
    budget_limit = body.get("budget_limit")
    try:
        budget_limit = int(budget_limit) if budget_limit is not None else DEFAULT_LOOP_TOKEN_BUDGET
    except (TypeError, ValueError):
        budget_limit = DEFAULT_LOOP_TOKEN_BUDGET
    set_loop_budget(loop_id, budget_limit)

    # 后台任务运行（不阻塞请求）
    asyncio.create_task(
        run_loop(loop_id, api_key, model, user_id, role_models=role_models,
                 mode=mode, project_name=project_name)
    )

    return {"loop_id": loop_id, "status": "running", "message": "Agent Loop 已启动"}


@router.get("/loop/{loop_id}")
def api_get_loop(loop_id: int, current_user: Optional[dict] = Depends(get_optional_user)):
    """查询 loop 详情 + 全部事件（前端刷新后重放恢复，R4）。"""
    loop = db.get_loop_group(loop_id)
    _check_loop_access(loop, current_user)
    return {
        "loop": loop,
        "events": db.get_loop_events(loop_id),
    }


@router.get("/loop/{loop_id}/events")
async def api_loop_events(
    loop_id: int,
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """SSE 事件流：先回放 DB 已有事件（刷新恢复），再订阅实时事件直到 loop 结束。"""
    loop = db.get_loop_group(loop_id)
    _check_loop_access(loop, current_user)

    runtime = get_runtime(loop_id)

    async def gen():
        # 回放已有事件（按 seq 顺序）
        for ev in db.get_loop_events(loop_id):
            if await request.is_disconnected():
                return
            yield _sse(ev["event_type"], {
                "seq": ev["seq"],
                "agent": ev["agent"],
                "payload": ev["payload"] or {},
            })
        # 若 loop 已结束，无需订阅实时事件
        if loop["status"] in ("done", "failed"):
            return
        # 订阅实时事件（None = sentinel 结束）
        while True:
            if await request.is_disconnected():
                return
            item = await runtime.events.get()
            if item is None:
                break
            yield _sse(item["event_type"], {
                "seq": item["seq"],
                "agent": item["agent"],
                "payload": item["payload"] or {},
            })
            if item["event_type"] == "done" or item["event_type"] == "error":
                # 再放回一个 sentinel 供后续 SSE 连接收尾
                await runtime.events.put(None)
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/loop/{loop_id}/decision")
async def api_loop_decision(
    loop_id: int,
    body: dict = Body(...),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Checkpoint 决策（D7）：continue / adjust / rollback / approve / reject。"""
    loop = db.get_loop_group(loop_id)
    _check_loop_access(loop, current_user)
    if loop["status"] != "awaiting_signoff":
        raise HTTPException(409, "当前 loop 不在等待决策状态")

    decision = (body.get("decision") or "").strip()
    note = (body.get("note") or "").strip()
    if decision not in ("continue", "adjust", "rollback", "approve", "reject"):
        raise HTTPException(400, f"无效决策: {decision}")

    db.add_loop_event(loop_id, "user", "user_decision", {"decision": decision, "note": note})

    # 唤醒等待中的 orchestrator
    runtime = get_runtime(loop_id)
    runtime.decision = {"decision": decision, "note": note}
    runtime.checkpoint_event.set()

    return {"status": "ok", "decision": decision, "message": "决策已记录"}


@router.get("/loops")
def api_list_loops(current_user: Optional[dict] = Depends(get_optional_user)):
    """当前用户的 loop 列表（schedule 触发后可据此查看）。"""
    user_id = current_user["user_id"] if current_user else None
    return {"loops": db.list_loop_groups(user_id)}


# ── Schedule endpoints ─────────────────────────────────────────────

@router.get("/schedules")
def api_list_schedules(current_user: Optional[dict] = Depends(get_optional_user)):
    """列出当前用户的定时 schedule。"""
    user_id = current_user["user_id"] if current_user else None
    return {"schedules": db.list_schedules(user_id)}


@router.post("/schedules", response_model=LoopScheduleOut)
async def api_create_schedule(
    body: LoopScheduleIn,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """创建 schedule。mode=L1 只读报告；mode=L2 行动模式（需用户确认）。"""
    user_id = current_user["user_id"] if current_user else None
    if not user_id:
        raise HTTPException(401, "需登录后创建 schedule")
    if not validate_cron(body.cron_expr):
        raise HTTPException(400, f"无效 cron 表达式: {body.cron_expr}")
    next_run = compute_next_run(body.cron_expr)
    sid = db.create_schedule(
        user_id=user_id,
        project_name=body.project_name,
        task_prompt=body.task_prompt,
        cron_expr=body.cron_expr,
        mode=body.mode,
        enabled=body.enabled,
        next_run_at=next_run,
    )
    row = db.get_schedule(sid)
    return LoopScheduleOut(**_schedule_row_to_out(row))


@router.patch("/schedules/{schedule_id}")
async def api_update_schedule(
    schedule_id: int,
    body: dict = Body(...),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    user_id = current_user["user_id"] if current_user else None
    row = db.get_schedule(schedule_id)
    if not row:
        raise HTTPException(404, "schedule 不存在")
    if row["user_id"] != user_id:
        raise HTTPException(403, "无权修改该 schedule")
    updates = {}
    if "task_prompt" in body:
        updates["task_prompt"] = str(body["task_prompt"])
    if "cron_expr" in body:
        if not validate_cron(body["cron_expr"]):
            raise HTTPException(400, f"无效 cron 表达式: {body['cron_expr']}")
        updates["cron_expr"] = body["cron_expr"]
        updates["next_run_at"] = compute_next_run(body["cron_expr"])
    if "mode" in body:
        if body["mode"] not in ("L1", "L2"):
            raise HTTPException(400, "mode 必须是 L1 或 L2")
        updates["mode"] = body["mode"]
    if "enabled" in body:
        updates["enabled"] = int(bool(body["enabled"]))
    if updates:
        db.update_schedule(schedule_id, **updates, updated_at=datetime.now().isoformat())
    return db.get_schedule(schedule_id)


@router.delete("/schedules/{schedule_id}")
async def api_delete_schedule(
    schedule_id: int,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    user_id = current_user["user_id"] if current_user else None
    row = db.get_schedule(schedule_id)
    if not row:
        raise HTTPException(404, "schedule 不存在")
    if row["user_id"] != user_id:
        raise HTTPException(403, "无权删除该 schedule")
    db.delete_schedule(schedule_id)
    return {"status": "ok"}


# ── Global kill switch endpoints ───────────────────────────────────

@router.get("/loop/pause-all")
def api_get_pause_all():
    return GlobalSwitchOut(key="loop-pause-all", value=get_pause_all())


@router.post("/loop/pause-all")
async def api_set_pause_all(body: dict = Body(...)):
    value = bool(body.get("paused", False))
    set_pause_all(value)
    return GlobalSwitchOut(key="loop-pause-all", value=value)


@router.get("/memory/scan")
def api_memory_scan(
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """P6：扫描记忆目录（只读前 30 行/文件，不调用 LLM），返回元数据清单。

    query: root=记忆目录绝对路径；缺省回退 FILE_MEMORY_ROOT / data/memory。
    """
    from ..memory.file_memory import scan_memory_files, build_listing
    from ..llm.client import get_llm_config

    root = (request.query_params.get("root") or "").strip()
    if not root:
        root = os.getenv("FILE_MEMORY_ROOT", "") or os.path.join(
            DATA_DIR, "memory"
        )
    files = scan_memory_files(root)
    return {
        "root": os.path.realpath(root) if root else "",
        "scanned": len(files),
        "listing": build_listing(files),
        "files": [{
            "path": f["rel_path"],
            "type": f["type"],
            "mtime": f["mtime"].isoformat() if f["mtime"] else None,
        } for f in files],
    }


@router.post("/memory/select")
async def api_memory_select(
    body: dict = Body(...),
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """P6：query + 记忆清单 → 小模型选择最相关记忆（宁缺毋滥 + 后校验 + 预算注入预览）。

    body: {query, root?, model?}；header X-API-Key 传 key。
    """
    from ..memory.file_memory import scan_memory_files, select_relevant, build_file_memory_context
    from ..llm.client import get_llm_config

    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    root = (body.get("root") or "").strip()
    if not root:
        root = os.getenv("FILE_MEMORY_ROOT", "") or os.path.join(
            DATA_DIR, "memory"
        )
    api_key = request.headers.get("X-API-Key") or None
    model = (body.get("model") or "").strip() or request.headers.get("X-LLM-Model") or None
    session_id = (body.get("session_id") or "").strip()

    files = scan_memory_files(root)
    selected, sel_stats = select_relevant(query, files, api_key, model, root)
    # 注入预览（不真正累加会话预算，仅展示）
    injected, stats = build_file_memory_context(
        query, root, api_key, model, session_id="",
    )
    return {
        "root": root,
        "scanned": sel_stats.get("scanned", 0),
        "selected": sel_stats.get("selected", 0),
        "selected_files": [f["rel_path"] for f in selected],
        "injected_preview": injected[:2000],
        "stats": {k: v for k, v in stats.items() if k not in ("root",)},
    }


@router.get("/state/{project_name}")
def api_get_project_state(
    project_name: str,
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """读取项目 STATE 摘要（DB 优先，STATE.md 兜底）。"""
    user_id = current_user["user_id"] if current_user else None
    project_dir = (request.query_params.get("project_dir") or "").strip()
    state = load_project_state(user_id, project_name, project_dir)
    return {
        "project_name": state.project_name,
        "project_dir": state.project_dir,
        "run_count": state.run_count,
        "token_consumption_total": state.token_consumption_total,
        "last_run_at": state.last_run_at,
        "last_loop_result": state.last_loop_result,
        "open_problems": state.open_problems,
        "constraints": state.constraints,
        "critiques": state.critiques,
        "summary_text": state.summary_text(),
    }


# ── P2-9: Metrics endpoints ─────────────────────────────────────

@router.get("/metrics/summary", response_model=MetricsSummary)
def api_metrics_summary(
    project_name: str = "",
    days: int = 7,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """聚合指标：成功率、误报率、平均耗时、token 消耗等。"""
    user_id = current_user["user_id"] if current_user else None
    if not user_id:
        raise HTTPException(401, "需登录后查看指标")
    metrics = db.get_run_log_metrics(user_id, project_name, days)
    return MetricsSummary(**metrics)


@router.get("/metrics/daily")
def api_metrics_daily(
    project_name: str = "",
    days: int = 7,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """按日分组的指标。"""
    user_id = current_user["user_id"] if current_user else None
    if not user_id:
        raise HTTPException(401, "需登录后查看指标")
    return {"daily": db.get_daily_metrics(user_id, project_name, days)}


@router.get("/run-logs")
def api_run_logs(
    project_name: str = "",
    days: int = 7,
    limit: int = 50,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """P1-4: 查询结构化运行日志。"""
    user_id = current_user["user_id"] if current_user else None
    if not user_id:
        raise HTTPException(401, "需登录后查看运行日志")
    logs = db.get_run_logs(user_id, project_name, days, limit)
    return {"run_logs": logs}


# ── P2-8: Graduation endpoints ─────────────────────────────────

@router.get("/graduation/{project_name}", response_model=GraduationStatus)
def api_graduation_status(
    project_name: str,
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """查询项目 L1→L2→L3 毕业进度。"""
    user_id = current_user["user_id"] if current_user else None
    project_dir = (request.query_params.get("project_dir") or "").strip()
    state = load_project_state(user_id, project_name, project_dir)
    # 从 run_logs 获取误报率
    false_positive_rate = 0.0
    if user_id:
        try:
            metrics = db.get_run_log_metrics(user_id, project_name, days=14)
            false_positive_rate = metrics.get("false_positive_rate", 0.0)
        except Exception:
            pass
    return GraduationStatus(**get_graduation_status(state, false_positive_rate))


@router.post("/graduation/{project_name}/progress")
async def api_update_graduation_progress(
    project_name: str,
    body: dict = Body(...),
    request: Request = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """手动更新毕业进度中的检查项。"""
    user_id = current_user["user_id"] if current_user else None
    if not user_id:
        raise HTTPException(401, "需登录后更新毕业进度")
    project_dir = (request.query_params.get("project_dir") or body.get("project_dir", "") or "").strip()
    state = load_project_state(user_id, project_name, project_dir)
    for key in ("verifier_tested", "denylist_configured", "denylist_in_gate",
                "auto_merge_safe", "kill_switch_ready", "human_gate_documented",
                "audit_score", "l2_incidents"):
        if key in body:
            state.graduation_progress[key] = body[key]
    save_project_state(user_id, state)
    return {"status": "ok", "project_name": project_name, "progress": state.graduation_progress}


def _schedule_row_to_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_name": row["project_name"],
        "task_prompt": row["task_prompt"],
        "cron_expr": row["cron_expr"],
        "mode": row["mode"],
        "enabled": bool(row["enabled"]),
        "last_run_at": row.get("last_run_at"),
        "next_run_at": row.get("next_run_at"),
        "created_at": row.get("created_at"),
    }


# ── Schedule trigger callback（由 scheduler loop 调用）─────────────

def trigger_schedule(schedule: dict):
    """Schedule 到期触发：创建 loop 并后台运行。"""
    user_id = schedule["user_id"]
    project_name = schedule["project_name"]
    task = schedule["task_prompt"]
    mode = schedule["mode"]
    session_id = f"schedule-{schedule['id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    project_dir = _resolve_project_dir(user_id, project_name)
    loop_id = db.create_loop_group(user_id, session_id, task, project_dir)
    set_loop_budget(loop_id, DEFAULT_LOOP_TOKEN_BUDGET)
    asyncio.create_task(
        run_loop(loop_id, api_key=None, model=None, user_id=user_id,
                 role_models={}, mode=mode, project_name=project_name)
    )


def _resolve_project_dir(user_id: int, project_name: str) -> str:
    """根据 project_name 推断项目目录（优先内存中上下文，其次默认路径）。"""
    from pathlib import Path
    try:
        from ..memory.restore import restore_context
        ctx = restore_context(user_id)
        proj = ctx.get("current_project") or {}
        if proj.get("name") == project_name and proj.get("path"):
            return proj["path"]
    except Exception:
        pass
    # 默认：工作区/用户项目名（可自定义）
    workspace = Path.home() / "OrbitProjects"
    return str(workspace / project_name)
