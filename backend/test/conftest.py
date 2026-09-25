"""
pytest 全局配置 — 测试环境隔离

核心原则：所有测试数据落在临时目录，绝不污染真实 data/ 与数据库。
- ChromaDB  → 临时目录（patch settings.rag.storage.persist_dir，须在 store 初始化前）
- SQLite    → 临时目录（DATABASE_URL 环境变量，须在 import app.config 前设置）
- memory.db → 临时目录（patch app.memory.DB_PATH）
- uploads/  → 临时目录（patch settings.UPLOAD_DIR，logos 输出随之隔离）
- LLM 调用  → mock urllib.request.urlopen（mock_llm fixture）
- 限流      → 禁用（slowapi 5/minute 会阻塞重复注册/登录测试）
"""

import os
import sys
import json
import tempfile

# ── 环境变量必须在任何 app 模块 import 之前设置 ──
TEST_ROOT = tempfile.mkdtemp(prefix="orbit_test_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TEST_ROOT, "tenant.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.pop("LLM_API_KEY", None)   # 确保无 key 场景确定
os.environ.pop("LLM_MODEL", None)
os.environ.pop("LLM_BASE_URL", None)
os.environ["PYTEST_RUNNING"] = "1"    # P1-3: 跳过生产级配置验证

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from app.config import settings  # noqa: E402

# ── 存储路径全部指向临时目录（store._client 单例首次初始化时生效）──
settings.rag.storage.persist_dir = os.path.join(TEST_ROOT, "chroma_db")
settings.UPLOAD_DIR = os.path.join(TEST_ROOT, "uploads")
os.makedirs(settings.rag.storage.persist_dir, exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

import app.memory.db as memory_db  # noqa: E402

memory_db.DB_PATH = os.path.join(TEST_ROOT, "memory.db")


# ── 状态清理：每个测试后清空共享状态 ──
#
# 分支锁写在 SQLite 的 global_switches 表，所有 loop 测试若共享同一
# project_dir 则锁 key 相同，残留锁会让后续 loop 被 skip（status=failed）。
# 根治手段是让每个 loop 测试使用唯一 project_dir（见 unique_project_dir
# fixture），此处的清理作为兜底。

def _purge_branch_locks() -> None:
    """删除全部残留分支锁（所有 loop 测试共享 project_dir=""，锁 key 相同）。"""
    try:
        from app.agents import db as agents_db
        conn = agents_db._get_db()
        conn.execute("DELETE FROM global_switches WHERE key LIKE 'branch-lock:%'")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _purge_collections_and_cache() -> None:
    """清空语义缓存与 ChromaDB collection，并同步失效 count 缓存。"""
    from app.cache import clear as cache_clear
    cache_clear()
    try:
        from app.store import get_client
        client = get_client()
        for col in client.list_collections():
            # chromadb 0.5+ 返回 Collection 对象，旧版返回 str
            client.delete_collection(col if isinstance(col, str) else col.name)
    except Exception:
        pass
    # collections 删除后必须同步失效 search 的 count 缓存（5s TTL），
    # 否则空库判断失效 → n_results=0 的 query 报错
    # 注意：app.search 会连带 import chromadb，轻量单测环境下可能不可用，
    # 因此这里不能让它把整个测试会话带崩。
    try:
        from app.search import _invalidate_count_cache
        _invalidate_count_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    _purge_collections_and_cache()
    _purge_branch_locks()
    _reset_global_state()


def _reset_global_state() -> None:
    """复位跨用例累积的模块级全局状态。

    - LLM 熔断器：失败计数累积到阈值后会打开，导致后续用例静默走 fallback 分支。
    - 令牌撤销表：某个用例登出后会把 jti 永久留在撤销表里。
    """
    try:
        from app.llm.retry import reset_circuit_breakers
        reset_circuit_breakers()
    except Exception:
        pass
    try:
        from app.middleware.auth import reset_revocation_store
        reset_revocation_store()
    except Exception:
        pass


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient（触发 lifespan：初始化 DB + 预热 embedding 模型）"""
    import app.api.auth as auth_api
    auth_api.limiter.enabled = False  # 测试环境禁用注册/登录限流

    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_token():
    """直接创建测试用户并签发 token（绕过 API 限流，唯一用户名避免冲突）"""
    import uuid
    from app.multitenant import register_user
    from app.middleware.auth import create_access_token
    username = "pytest_" + uuid.uuid4().hex[:8]
    result = register_user(username, "pytest_pass_123")
    assert "user_id" in result, result
    return create_access_token(username, result["user_id"])


@pytest.fixture()
def auth_headers(auth_token):
    return {"Authorization": "Bearer " + auth_token}


@pytest.fixture()
def mock_llm(monkeypatch):
    """
    Mock urllib.request.urlopen，拦截所有 LLM HTTP 调用。
    返回 recorder 便于断言请求内容；可自定义响应。
    """
    recorder = {"requests": [], "response_content": "这是 Mock LLM 的回答", "sse_tokens": ["你好", "，世界"]}

    class FakeResp:
        def __init__(self, data, lines=None):
            self._data = data
            self._lines = lines

        def read(self):
            return json.dumps(self._data).encode()

        def __iter__(self):
            """流式模式：逐行 yield SSE"""
            return iter(self._lines or [])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None, **kwargs):
        body = {}
        if getattr(req, "data", None):
            try:
                body = json.loads(req.data.decode())
            except Exception:
                pass
        recorder["requests"].append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})

        if body.get("stream"):
            # SSE 流式响应
            lines = []
            for tok in recorder["sse_tokens"]:
                chunk = {"choices": [{"delta": {"content": tok}}]}
                lines.append(("data: " + json.dumps(chunk, ensure_ascii=False)).encode())
            lines.append(b"data: [DONE]")
            return FakeResp(None, lines=lines)

        return FakeResp({"choices": [{"message": {"content": recorder["response_content"]}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return recorder
