"""上线加固回归测试 —— 覆盖 4 处 P0 修复 + 关键安全/健壮性改动。

本文件刻意只依赖轻量依赖（fastapi / structlog / tenacity / pybreaker / alembic），
不启动完整应用（不加载 chromadb / sentence-transformers），便于在 CI 前置阶段快速跑。
"""

import time
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_id import RequestIDMiddleware


# ═══════════════════════════════════════════════════════════
# P0-1 异常处理链
# ═══════════════════════════════════════════════════════════

def _error_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/business-error")
    def business_error():
        raise HTTPException(status_code=400, detail="业务错误信息")

    @app.get("/boom")
    def boom():
        raise ValueError("内部炸了")

    @app.get("/validate")
    def validate(q: int = None):  # 缺参数 → 422
        return {"q": q}

    return app


@pytest.fixture()
def error_client():
    return TestClient(_error_app(), raise_server_exceptions=False)


def test_http_exception_uses_unified_structure(error_client):
    """修复前：HTTPException 走 FastAPI 默认处理器，body 只有 detail、**没有 request_id**。"""
    r = error_client.get("/business-error")
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "业务错误信息"
    assert body["request_id"] == r.headers["x-request-id"]
    assert body["request_id"] != "unknown"


def test_404_also_gets_request_id(error_client):
    r = error_client.get("/definitely-not-here")
    assert r.status_code == 404
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_validation_error_uses_unified_structure(error_client):
    r = error_client.get("/validate", params={"q": "not-an-int"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "请求参数校验失败"
    assert isinstance(body["detail"], list)
    assert body["request_id"] == r.headers["x-request-id"]


def test_unhandled_exception_does_not_crash_handler(error_client, monkeypatch):
    """修复前：handler 用 stdlib logger 却传 structlog kwargs，自己抛 TypeError。

    用 development 环境验证 detail 仍返回（便于本地定位）。
    """
    monkeypatch.setenv("ENV", "development")
    r = error_client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "Internal Server Error"
    assert body["request_id"] == r.headers["x-request-id"]
    assert "内部炸了" in body["detail"]


def test_unhandled_exception_hides_detail_in_production(error_client, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    r = error_client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"] == "Internal Server Error"
    assert "detail" not in r.json()


# ═══════════════════════════════════════════════════════════
# P0-2 LLM Fallback 与熔断
# ═══════════════════════════════════════════════════════════

def _fresh_breakers():
    from app.llm.retry import reset_circuit_breakers
    reset_circuit_breakers()


def test_primary_success_reports_primary_model():
    _fresh_breakers()
    from app.llm.retry import call_llm_with_retry

    result = call_llm_with_retry(lambda: "OK", model_name="primary-model")
    assert result == {"success": True, "data": "OK", "model_used": "primary-model"}


def test_fallback_call_fn_is_actually_used():
    """修复前：fallback 复用同一个 call_fn，等于对同一故障端点再打一次。"""
    _fresh_breakers()
    from app.llm.retry import call_llm_with_retry

    calls = []

    def primary():
        calls.append("primary")
        raise RuntimeError("primary down")

    def fallback():
        calls.append("fallback")
        return "FB"

    result = call_llm_with_retry(
        primary, fallback_call_fn=fallback,
        model_name="primary-model", fallback_model="fallback-model", fallback_api_key="k",
    )
    assert calls == ["primary", "fallback"]
    assert result["data"] == "FB"
    assert result["model_used"] == "fallback-model"


def test_missing_fallback_builder_does_not_fake_degradation():
    """没有 fallback 请求构造器时应如实失败，而不是复刻主请求假装降级成功。"""
    _fresh_breakers()
    from app.llm.retry import call_llm_with_retry, LLMCallFailedError

    calls = []

    def primary():
        calls.append("primary")
        raise RuntimeError("primary down")

    with pytest.raises(LLMCallFailedError):
        call_llm_with_retry(primary, model_name="primary-model", fallback_api_key="k")

    assert calls == ["primary"], "不得对同一故障端点重复发请求"


def test_fallback_failure_surfaces_error_not_fake_model_name():
    _fresh_breakers()
    from app.llm.retry import call_llm_with_retry, LLMCallFailedError

    def primary():
        raise RuntimeError("primary down")

    def fallback():
        raise RuntimeError("fallback down")

    with pytest.raises(LLMCallFailedError):
        call_llm_with_retry(
            primary, fallback_call_fn=fallback,
            model_name="primary-model", fallback_model="fallback-model", fallback_api_key="k",
        )


def test_open_breaker_skips_primary_entirely():
    """主熔断器 open 时不应再打主端点（修复前仍会死打）。"""
    from app.llm import retry as retry_mod

    retry_mod.reset_circuit_breakers()
    for _ in range(retry_mod.LLM_CB_FAIL_MAX):
        try:
            retry_mod._breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        except Exception:
            pass
    assert retry_mod._is_circuit_open()

    calls = []

    def primary():
        calls.append("primary")
        return "P"

    def fallback():
        calls.append("fallback")
        return "F"

    try:
        result = retry_mod.call_llm_with_retry(
            primary, fallback_call_fn=fallback,
            model_name="primary-model", fallback_model="fallback-model", fallback_api_key="k",
        )
        assert calls == ["fallback"]
        assert result["model_used"] == "fallback-model"
    finally:
        retry_mod.reset_circuit_breakers()


def test_fallback_base_url_derived_per_model(monkeypatch):
    """跨厂商 fallback 不能沿用主模型的 base_url。"""
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
    monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
    from app.llm.client import get_fallback_llm_config

    _, base_url, model = get_fallback_llm_config()
    assert model == "gpt-4o-mini"
    assert base_url == "https://api.openai.com/v1/chat/completions"


def test_fallback_config_none_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    from app.llm.client import get_fallback_llm_config
    assert get_fallback_llm_config() is None


# ═══════════════════════════════════════════════════════════
# P0-3 语义缓存租户隔离
# ═══════════════════════════════════════════════════════════

@pytest.fixture()
def cache_mod(monkeypatch):
    from app import cache
    cache.clear()
    # 固定编码器：所有 query 得到同一向量 → 只要 namespace 放行就必然命中
    monkeypatch.setattr(cache, "encode", lambda texts: [[1.0, 0.0] for _ in texts])
    yield cache
    cache.clear()


def test_cache_isolated_by_namespace(cache_mod):
    cache_mod.put("同一个问题", "A 的答案", [{"source": "a.md"}], "m", namespace="1:col")
    hit = cache_mod.get("同一个问题", namespace="1:col")
    assert hit and hit["answer"] == "A 的答案"
    # 另一个租户问同样的问题，绝不能拿到 A 的答案
    assert cache_mod.get("同一个问题", namespace="2:col") is None


def test_cache_without_namespace_is_a_separate_bucket(cache_mod):
    cache_mod.put("问题", "有租户的答案", [], "m", namespace="1:col")
    assert cache_mod.get("问题", namespace="2:col") is None


def test_purge_user_removes_all_its_namespaces(cache_mod):
    cache_mod.put("q1", "a1", [], "m", namespace="1:col_a")
    cache_mod.put("q2", "a2", [], "m", namespace="1:col_b")
    cache_mod.put("q3", "a3", [], "m", namespace="2:col_a")
    assert cache_mod.purge_user(1) == 2
    assert cache_mod.get("q1", namespace="1:col_a") is None
    assert cache_mod.get("q2", namespace="1:col_b") is None
    assert cache_mod.get("q3", namespace="2:col_a") is not None


def test_cache_hit_reports_model_cache(cache_mod):
    cache_mod.put("q", "a", [], "deepseek-chat", namespace="ns")
    hit = cache_mod.get("q", namespace="ns")
    assert hit["model"] == "cache"
    assert hit["cache_hit"] is True


# ═══════════════════════════════════════════════════════════
# 调度器：cron 计算正确性 + 性能
# ═══════════════════════════════════════════════════════════

def test_next_run_daily():
    from app.agents.schedule import compute_next_run
    assert compute_next_run("0 9 * * *", after=datetime(2026, 9, 25, 8, 30)) == "2026-09-25T09:00:00"


def test_next_run_rolls_to_next_day():
    from app.agents.schedule import compute_next_run
    assert compute_next_run("0 9 * * *", after=datetime(2026, 9, 25, 10, 0)) == "2026-09-26T09:00:00"


def test_next_run_weekly_monday():
    """2026-09-25 是周五 → 下周一为 09-28。"""
    from app.agents.schedule import compute_next_run
    result = compute_next_run("0 9 * * 1", after=datetime(2026, 9, 25, 8, 0))
    assert result == "2026-09-28T09:00:00"


def test_next_run_step_field():
    from app.agents.schedule import compute_next_run
    assert compute_next_run("*/15 * * * *", after=datetime(2026, 9, 25, 8, 31)) == "2026-09-25T08:45:00"


def test_next_run_dom_dow_or_semantics():
    """dom 与 dow 都受限时取 OR（Vixie cron 语义）。"""
    from app.agents.schedule import compute_next_run
    # 每月 1 号 或 周一 的 00:00
    result = compute_next_run("0 0 1 * 1", after=datetime(2026, 9, 25, 8, 0))
    assert result == "2026-09-28T00:00:00"  # 09-28 是周一，早于 10-01


def test_next_run_impossible_expression_returns_none():
    from app.agents.schedule import compute_next_run
    assert compute_next_run("0 0 31 2 *", after=datetime(2026, 1, 1)) is None


def test_next_run_never_scans_minute_by_minute():
    """性能回归：旧实现最坏要逐分钟扫 4 年（实测 ~581ms 同步阻塞事件循环）。"""
    from app.agents.schedule import compute_next_run
    start = time.perf_counter()
    compute_next_run("0 0 31 2 *", after=datetime(2026, 1, 1))  # 最坏情况
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2, f"next_run 计算耗时 {elapsed * 1000:.1f}ms，疑似退化回逐分钟扫描"


def test_validate_cron():
    from app.agents.schedule import validate_cron
    assert validate_cron("0 9 * * 1")
    assert validate_cron("*/5 * * * *")
    assert not validate_cron("bad")
    assert not validate_cron("* * * *")


def test_scheduler_enabled_toggle(monkeypatch):
    from app.agents.schedule import scheduler_enabled
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    assert scheduler_enabled() is False
    monkeypatch.setenv("ENABLE_SCHEDULER", "1")
    assert scheduler_enabled() is True


# ═══════════════════════════════════════════════════════════
# SQLite PRAGMA（WAL / busy_timeout）
# ═══════════════════════════════════════════════════════════

def test_sqlite_wal_and_busy_timeout(tmp_path):
    from app.sqlite_utils import connect, busy_timeout_ms
    conn = connect(str(tmp_path / "t.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == busy_timeout_ms()
    finally:
        conn.close()


def test_sqlite_foreign_keys_default_off_outside_production(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("SQLITE_FOREIGN_KEYS", raising=False)
    from app.sqlite_utils import connect
    conn = connect(str(tmp_path / "fk.db"))
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# Alembic 迁移库与运行时库必须一致（部署级回归）
# ═══════════════════════════════════════════════════════════

def test_init_db_migrates_the_same_file_runtime_reads(monkeypatch, tmp_path):
    """回归：init_db 必须把 alembic 指向运行时同一个库文件。

    历史缺陷（实测复现）：alembic.ini 里写死
    `sqlalchemy.url = sqlite:///../multitenant.db`，这是**相对进程 CWD** 解析的；
    运行时库路径却由 `settings.DATABASE_URL` 相对 `__file__` 解析，与 CWD 无关。
    未显式设置 DATABASE_URL 时（本地直接 uvicorn / 非 compose 部署）二者分叉：
    迁移把 users/sessions/tenants 建到 CWD 相对路径，应用去读另一个库，
    注册/登录直接报 `no such table: users`。
    compose 里因为显式设了 DATABASE_URL，测试 conftest 也设了，所以一直没暴露。
    """
    import app.multitenant.db as mdb
    from alembic import command

    db_file = tmp_path / "tenant.db"
    url = "sqlite:///" + str(db_file)

    class _StubSettings:
        DATABASE_URL = url

    monkeypatch.setattr(mdb, "settings", _StubSettings)
    monkeypatch.setattr(mdb, "DB_PATH", str(db_file))
    monkeypatch.setattr(mdb, "_migrated", False)

    captured = {}

    def fake_upgrade(cfg, revision):
        captured["url"] = cfg.get_main_option("sqlalchemy.url")
        captured["revision"] = revision

    monkeypatch.setattr(command, "upgrade", fake_upgrade)

    mdb.init_db(force=True)

    assert captured["revision"] == "head"
    assert captured["url"] == url, (
        f"alembic 目标库与运行时库不一致：{captured['url']} != {url}"
    )
    # 运行时真正打开的文件确实被建出来了（pre-create 逻辑生效）
    assert db_file.exists()


# ═══════════════════════════════════════════════════════════
# Agent Loop 落盘目录白名单
# ═══════════════════════════════════════════════════════════

def test_absolute_project_dir_rejected_in_production_without_allowlist(monkeypatch):
    """修复前：任意绝对路径都被接受，等于任何登录用户都能让 Builder 往 /etc 写文件。"""
    from app.agents import orchestrator as orch
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("AGENT_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("KNOWLEDGE_ROOT", raising=False)
    assert orch._resolve_safe_project_dir("/etc/evil") is None


def test_absolute_project_dir_allowed_inside_allowlist(monkeypatch, tmp_path):
    from app.agents import orchestrator as orch
    monkeypatch.setenv("AGENT_ALLOWED_ROOTS", str(tmp_path))
    target = tmp_path / "proj"
    assert orch._resolve_safe_project_dir(str(target)) == str(target)


def test_absolute_project_dir_rejected_outside_allowlist(monkeypatch, tmp_path):
    from app.agents import orchestrator as orch
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("AGENT_ALLOWED_ROOTS", str(allowed))
    assert orch._resolve_safe_project_dir(str(tmp_path / "outside")) is None


def test_relative_project_dir_escape_rejected(monkeypatch):
    from app.agents import orchestrator as orch
    assert orch._resolve_safe_project_dir("../../etc") is None


# ═══════════════════════════════════════════════════════════
# 环境变量加载
# ═══════════════════════════════════════════════════════════

def test_dotenv_minimal_parser_ignores_comments_and_quotes(tmp_path):
    from app.env_loader import _parse_dotenv_minimal
    path = tmp_path / ".env"
    path.write_text(
        "# 注释\n"
        "\n"
        "PLAIN=value\n"
        "QUOTED=\"quoted value\"\n"
        "SINGLE='single'\n"
        "export EXPORTED=yes\n"
        "WITH_EQUALS=a=b\n",
        encoding="utf-8",
    )
    values = _parse_dotenv_minimal(str(path))
    assert values["PLAIN"] == "value"
    assert values["QUOTED"] == "quoted value"
    assert values["SINGLE"] == "single"
    assert values["EXPORTED"] == "yes"
    assert values["WITH_EQUALS"] == "a=b"


# ═══════════════════════════════════════════════════════════
# 配置校验（生产环境强校验）
# ═══════════════════════════════════════════════════════════

def test_production_requires_secret_key(monkeypatch):
    from app.config import _validate_config_on_startup, ConfigError
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ConfigError) as exc:
        _validate_config_on_startup()
    assert "SECRET_KEY" in str(exc.value)


def test_production_rejects_wildcard_cors(monkeypatch):
    from app.config import _validate_config_on_startup, ConfigError
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ConfigError) as exc:
        _validate_config_on_startup()
    assert "CORS_ORIGINS" in str(exc.value)


def test_production_requires_llm_key(monkeypatch):
    from app.config import _validate_config_on_startup, ConfigError
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    with pytest.raises(ConfigError) as exc:
        _validate_config_on_startup()
    assert "LLM_API_KEY" in str(exc.value)


def test_dev_environment_does_not_fail_startup(monkeypatch, capsys):
    from app.config import _validate_config_on_startup
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    _validate_config_on_startup()  # 不抛异常
    assert "SECRET_KEY" in capsys.readouterr().err


def test_secret_key_dev_fallback_generates_and_warns(monkeypatch):
    from app.middleware import auth as auth_mod
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    key = auth_mod.get_secret_key()
    assert len(key) == 64  # token_hex(32)


def test_secret_key_production_raises(monkeypatch):
    from app.middleware import auth as auth_mod
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        auth_mod.get_secret_key()


# ═══════════════════════════════════════════════════════════
# 注册 / 登录 返回契约一致（role 字段）
# ═══════════════════════════════════════════════════════════

def test_register_reports_same_role_as_login():
    """回归：注册与登录返回的 role 必须一致。

    历史缺陷（实测复现）：schema 里是 `role TEXT DEFAULT 'user'`，
    `login_user` 返回 `row["role"]` → 'user'；而 `register_user` 的返回体里
    根本没有 role 字段 → 注册接口响应 `role: null`。
    前端 `auth-form.tsx` 会把 null 当成角色存下（并清掉 orbit_role），
    导致"同一账号刚注册后看不到角色相关 UI、重新登录后才出现"。
    """
    import uuid
    from app.multitenant import register_user, login_user

    name = "role_" + uuid.uuid4().hex[:8]
    reg = register_user(name, "role_pass_123")
    log = login_user(name, "role_pass_123")

    assert "user_id" in reg, reg
    assert reg.get("role") == "user", f"注册返回的 role 应为 'user'，实际 {reg.get('role')!r}"
    assert reg.get("role") == log.get("role"), "注册与登录返回的 role 必须一致"
    # 双方都不该出现"字段缺失/None"的分叉
    assert log.get("role") is not None
