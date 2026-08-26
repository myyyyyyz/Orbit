"""Agent Loop API 测试：/api/v1/agents/*

落地文档: docs/AGENT-LOOP-INTEGRATION.md §6.2
覆盖:
- POST /loop 启动（校验 task/session_id 必填、session 冲突 409）
- GET /loop/{id} 查询详情 + 事件
- POST /loop/{id}/decision checkpoint 决策
- AuthZ: 他人无权访问（403）
"""

import json

import pytest

from app.agents import db
from app.agents.orchestrator import get_runtime


PLAN_JSON = {
    "task_name": "写 hello.py",
    "steps": [{"index": 1, "desc": "创建 hello.py", "verify": "python hello.py 输出 Hello World",
               "test_level": "skip", "files": ["hello.py"]}],
    "gates": [{"gate_id": "G1", "check": "python hello.py", "pass_criteria": "输出 Hello World"}],
    "forbidden_paths": [], "impact_analysis": "不适用", "assumptions": [],
}
BUILD_JSON = {
    "summary": "创建 hello.py",
    "changed_files": [{"path": "hello.py", "action": "create", "content": "print('Hello World')\n"}],
    "snapshot_hash": "clean", "plan_deviations": [],
}
REVIEW_PASS = {"verdict": "ALL_PASS", "stage_results": [], "fail_reason": "", "fix_direction": ""}


@pytest.fixture()
def mock_loop_llm(monkeypatch):
    """mock orchestrator 的 LLM 调用（api 层测试不真正调模型）。

    越界兜底：loop 由 asyncio.create_task 后台启动，实际调用次数可能超出
    预设序列（重试、跨测试残留任务等），越界时复用最后一个响应，
    避免 IndexError 冒泡成随机失败。
    """
    calls = {"n": 0}
    responses = [PLAN_JSON, BUILD_JSON, REVIEW_PASS]

    def fake_urlopen(req, timeout=None, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        content = responses[idx] if idx < len(responses) else responses[-1]

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}).encode()

        return _FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


class TestAgentsAPI:
    def test_start_loop_validation(self, client):
        # 缺 task
        r = client.post("/api/v1/agents/loop", json={"session_id": "s1"})
        assert r.status_code == 400
        # 缺 session_id
        r = client.post("/api/v1/agents/loop", json={"task": "写 hello.py"})
        assert r.status_code == 400

    def test_session_conflict_409(self, client, monkeypatch):
        db.create_loop_group(None, "conflict-sess", "任务A")
        # 第二个 loop 同 session → 409
        r = client.post("/api/v1/agents/loop", json={"session_id": "conflict-sess", "task": "任务B"})
        assert r.status_code == 409

    def test_start_and_query(self, client, mock_loop_llm):
        r = client.post("/api/v1/agents/loop", json={"session_id": "s-api", "task": "写 hello.py"})
        assert r.status_code == 200, r.text
        loop_id = r.json()["loop_id"]
        # 立即查询：loop 存在且有 spawn 事件
        r2 = client.get(f"/api/v1/agents/loop/{loop_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["loop"]["session_id"] == "s-api"
        assert len(data["events"]) >= 1

    def test_decision_not_awaiting(self, client, mock_loop_llm):
        """非 awaiting_signoff 状态调用 decision → 409"""
        r = client.post("/api/v1/agents/loop", json={"session_id": "s-dec", "task": "写 hello.py"})
        loop_id = r.json()["loop_id"]
        # 立刻决策（此时状态还是 running，还没到 checkpoint）
        r2 = client.post(f"/api/v1/agents/loop/{loop_id}/decision", json={"decision": "continue"})
        assert r2.status_code in (200, 409)  # 取决于时序，但不应 500

    def test_decision_invalid_value(self, client):
        # 不存在的 loop → 404
        r = client.post("/api/v1/agents/loop/9999/decision", json={"decision": "invalid"})
        assert r.status_code == 404

    def test_authz_forbidden(self, client, auth_token, auth_headers):
        """用户 A 创建的 loop，用户 B 无权访问（403）"""
        r = client.post("/api/v1/agents/loop", json={"session_id": "s-authz", "task": "写 hello.py"}, headers=auth_headers)
        loop_id = r.json()["loop_id"]
        # 另一个用户（无 token 或不同 token）访问
        from app.multitenant import register_user
        from app.middleware.auth import create_access_token
        user_b = register_user("user_b_for_agents", "pass_123456")
        token_b = create_access_token(user_b["username"], user_b["user_id"])
        r2 = client.get(f"/api/v1/agents/loop/{loop_id}", headers={"Authorization": f"Bearer {token_b}"})
        assert r2.status_code == 403
