# KnowledgeRun 生命周期与审批完整性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在第二阶段 `FolderPlan` 基础上增加持久化运行状态、合法状态转换和源文件未变化校验，形成第三阶段 3.1 的安全审批入口。

**Architecture:** `run_state.py` 只负责纯状态规则，`repository.py` 负责 SQLite 状态持久化和原子转换，`approval.py` 负责重新扫描文件并编排审批，现有 `knowledge_plan.py` 暴露查询和审批 API。整个增量继续复用 `scan_folder()` 和现有审计表，不接触向量存储。

**Tech Stack:** Python 3.12、Pydantic 2、FastAPI、SQLite、pytest

---

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `backend/app/knowledge_agent/models.py` | 定义 `RunStatus`、扩展 `FolderPlan`、定义运行摘要 |
| `backend/app/knowledge_agent/run_state.py` | 保存状态转换白名单和纯校验函数 |
| `backend/app/knowledge_agent/repository.py` | 迁移运行表、读取运行、保存并原子转换状态 |
| `backend/app/knowledge_agent/approval.py` | 比较当前文件清单与计划哈希并批准或失效 |
| `backend/app/knowledge_agent/pipeline.py` | 生成相对文件夹路径和初始状态 |
| `backend/app/api/knowledge_plan.py` | 暴露运行查询和批准端点 |
| `backend/test/test_knowledge_run_state.py` | 验证初始状态与转换白名单 |
| `backend/test/test_knowledge_run_repository.py` | 验证状态持久化、租户隔离和原子转换 |
| `backend/test/test_knowledge_run_approval.py` | 验证文件变化导致失效 |
| `backend/test/test_knowledge_plan_api.py` | 验证查询、批准和冲突响应 |

## Task 1：纯状态模型

**Files:**

- Create: `backend/app/knowledge_agent/run_state.py`
- Modify: `backend/app/knowledge_agent/models.py`
- Create: `backend/test/test_knowledge_run_state.py`

- [x] **Step 1：先写失败测试**

```python
import pytest

from app.knowledge_agent.run_state import InvalidRunTransition, initial_status, transition_status


def test_initial_status_requires_review_when_any_document_requires_it():
    assert initial_status([False, True]) == "review_required"
    assert initial_status([False, False]) == "planned"


def test_only_whitelisted_run_transition_is_allowed():
    assert transition_status("planned", "approved") == "approved"
    with pytest.raises(InvalidRunTransition):
        transition_status("planned", "promoted")
```

- [x] **Step 2：运行测试并确认 RED**

Run:

```powershell
python -m pytest test/test_knowledge_run_state.py -q --noconftest
```

Expected: FAIL，提示 `app.knowledge_agent.run_state` 不存在。

- [x] **Step 3：实现最小状态白名单**

```python
ALLOWED_TRANSITIONS = {
    "planned": frozenset({"approved", "rejected", "invalidated"}),
    "review_required": frozenset({"approved", "rejected", "invalidated"}),
    "approved": frozenset({"indexing", "invalidated"}),
    "indexing": frozenset({"evaluating", "failed"}),
    "evaluating": frozenset({"promoted", "failed"}),
    "promoted": frozenset({"rolled_back"}),
}


class InvalidRunTransition(ValueError):
    pass


def initial_status(review_flags):
    return "review_required" if any(review_flags) else "planned"


def transition_status(current, target):
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidRunTransition(f"不允许从 {current} 转换为 {target}")
    return target
```

- [x] **Step 4：运行测试并确认 GREEN**

Expected: `2 passed`。

- [x] **Step 5：提交状态模型**

```powershell
git add backend/app/knowledge_agent/models.py backend/app/knowledge_agent/run_state.py backend/test/test_knowledge_run_state.py
git commit -m "feat: define knowledge run lifecycle"
```

## Task 2：状态持久化与原子转换

**Files:**

- Modify: `backend/app/knowledge_agent/repository.py`
- Modify: `backend/app/knowledge_agent/pipeline.py`
- Create: `backend/test/test_knowledge_run_repository.py`

- [x] **Step 1：先写失败测试**

```python
from pathlib import Path

from app.knowledge_agent.pipeline import plan_folder
from app.knowledge_agent.repository import get_run, transition_run


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_plan_persists_initial_status_and_folder_path(tmp_path):
    database = tmp_path / "audit.sqlite3"
    plan = plan_folder(FIXTURES, knowledge_root=FIXTURES.parent, database_path=database)
    saved = get_run(plan.run_id, database_path=database, user_id=None)
    assert saved.status == plan.status
    assert saved.folder_path == "fixtures"


def test_transition_run_rejects_a_stale_expected_status(tmp_path):
    database = tmp_path / "audit.sqlite3"
    plan = plan_folder(FIXTURES, knowledge_root=FIXTURES.parent, database_path=database)
    transition_run(plan.run_id, target="approved", expected=plan.status, database_path=database, user_id=None)
    assert transition_run(plan.run_id, target="approved", expected=plan.status, database_path=database, user_id=None) is False
```

- [x] **Step 2：运行测试并确认 RED**

Expected: FAIL，因为运行记录没有 `status`、`folder_path` 和读取接口。

- [x] **Step 3：迁移表并实现条件更新**

为 `knowledge_agent_runs` 增加 `folder_path`、`status`、`updated_at`、`approved_at`；`save_plan()` 保存计划状态；`transition_run()` 使用以下条件更新：

```sql
UPDATE knowledge_agent_runs
SET status = ?, updated_at = datetime('now'),
    approved_at = CASE WHEN ? = 'approved' THEN datetime('now') ELSE approved_at END
WHERE run_id = ? AND user_id IS ? AND status = ?
```

返回 `cursor.rowcount == 1`，让调用方识别并发或重复操作。

- [x] **Step 4：运行仓储测试和既有流水线测试**

Run:

```powershell
python -m pytest test/test_knowledge_run_repository.py test/test_knowledge_agent_pipeline.py -q --noconftest
```

Expected: 全部通过。

- [x] **Step 5：提交仓储增量**

```powershell
git add backend/app/knowledge_agent/repository.py backend/app/knowledge_agent/pipeline.py backend/test/test_knowledge_run_repository.py
git commit -m "feat: persist knowledge run status"
```

## Task 3：审批时源文件完整性校验

**Files:**

- Create: `backend/app/knowledge_agent/approval.py`
- Create: `backend/test/test_knowledge_run_approval.py`

- [x] **Step 1：先写批准成功和文件变化的失败测试**

```python
import shutil
from pathlib import Path

from app.knowledge_agent.approval import approve_run
from app.knowledge_agent.pipeline import plan_folder


SOURCE_FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def make_plan(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    copied_fixtures = knowledge_root / "fixtures"
    shutil.copytree(SOURCE_FIXTURES, copied_fixtures)
    database = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        copied_fixtures,
        knowledge_root=knowledge_root,
        database_path=database,
        user_id=None,
    )
    return plan, database, knowledge_root, copied_fixtures


def test_approve_run_when_source_manifest_is_unchanged(tmp_path):
    plan, database, knowledge_root, _ = make_plan(tmp_path)
    approved = approve_run(plan.run_id, knowledge_root=knowledge_root, database_path=database, user_id=None)
    assert approved.status == "approved"


def test_approve_run_invalidates_plan_when_source_changes(tmp_path):
    plan, database, knowledge_root, copied_fixtures = make_plan(tmp_path)
    (copied_fixtures / "clean-policy.md").write_text("changed", encoding="utf-8")
    invalidated = approve_run(plan.run_id, knowledge_root=knowledge_root, database_path=database, user_id=None)
    assert invalidated.status == "invalidated"
```

- [x] **Step 2：运行测试并确认 RED**

Expected: FAIL，提示 `app.knowledge_agent.approval` 不存在。

- [x] **Step 3：实现审批服务**

```python
def approve_run(run_id, *, knowledge_root, database_path, user_id):
    run = get_run(run_id, database_path=database_path, user_id=user_id)
    if run is None:
        raise RunNotFound(run_id)
    stored = load_source_hashes(run_id, database_path=database_path, user_id=user_id)
    current = {p.source_path: p.source_hash for p in scan_folder(knowledge_root / run.folder_path)}
    target = "approved" if current == stored else "invalidated"
    transition_status(run.status, target)
    if not transition_run(run_id, target=target, expected=run.status, database_path=database_path, user_id=user_id):
        raise RunStateConflict(run_id)
    updated = get_run(run_id, database_path=database_path, user_id=user_id)
    if updated is None:
        raise RunNotFound(run_id)
    return updated
```

- [x] **Step 4：运行审批测试并确认 GREEN**

Expected: 审批成功、内容变化、新增文件和删除文件测试全部通过。

- [x] **Step 5：提交审批服务**

```powershell
git add backend/app/knowledge_agent/approval.py backend/test/test_knowledge_run_approval.py
git commit -m "feat: approve immutable knowledge plans"
```

## Task 4：查询与审批 API

**Files:**

- Modify: `backend/app/api/knowledge_plan.py`
- Modify: `backend/test/test_knowledge_plan_api.py`
- Modify: `README.md`

- [x] **Step 1：先写 API 失败测试**

```python
def test_run_can_be_read_and_approved(client, auth_headers):
    planned = client.post("/api/knowledge/plan-folder", json={"path":"fixtures","use_agent":False}, headers=auth_headers)
    run_id = planned.json()["run_id"]
    assert client.get(f"/api/knowledge/runs/{run_id}", headers=auth_headers).json()["status"] in {"planned", "review_required"}
    approved = client.post(f"/api/knowledge/runs/{run_id}/approve", headers=auth_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
```

- [x] **Step 2：运行测试并确认 RED**

Expected: FAIL，查询和批准端点返回 404/405。

- [x] **Step 3：实现端点与错误映射**

新增：

```text
GET  /api/knowledge/runs/{run_id}
POST /api/knowledge/runs/{run_id}/approve
```

不存在或跨租户返回 `404`；文件变化后返回 `409` 并携带 `status=invalidated`；非法或并发状态转换返回 `409`。响应不得包含绝对文件路径或原始内容样本。

- [x] **Step 4：运行 API 与 Knowledge Agent 完整回归**

Run:

```powershell
python -m pytest test/test_knowledge_run_state.py test/test_knowledge_run_repository.py test/test_knowledge_run_approval.py test/test_knowledge_agent_pipeline.py test/test_knowledge_plan_api.py -q --noconftest
```

Expected: 全部通过且 `vector_store_writes` 仍为 `0`。

- [x] **Step 5：检查边界并提交**

```powershell
git diff --check
git grep -n "app.store\|chromadb\|add_documents" -- backend/app/knowledge_agent backend/app/api/knowledge_plan.py
git add backend/app/api/knowledge_plan.py backend/test/test_knowledge_plan_api.py README.md
git commit -m "feat: expose knowledge run approval"
```

预期 grep 没有新增向量写入引用。

## 最终回归与推送

- [x] 运行第二阶段 25 个 Knowledge Agent 测试和本计划新增测试。
- [x] 确认 `backend/.pydeps/`、已有 PR 文档删除和未跟踪中文总结没有进入暂存区。
- [ ] 推送 `dev/knowledge`，让现有草稿 PR 自动更新。
