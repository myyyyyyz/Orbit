"""multitenant/ — 多租户模块测试（SQLite 已隔离到临时目录）"""
import uuid

from app.multitenant import (
    init_db, register_user, login_user, get_user_by_id,
    get_user_collection, save_session, get_session, get_latest_session,
    _hash_password, _verify_password,
)


def _uname(prefix="pytest_mt"):
    return prefix + "_" + uuid.uuid4().hex[:8]


def test_init_db_idempotent():
    init_db()
    init_db()  # 重复初始化不报错


def test_password_hash_and_verify():
    h = _hash_password("my_secret_123")
    assert h != "my_secret_123"
    assert h.startswith("$2b$")
    assert _verify_password("my_secret_123", h)
    assert not _verify_password("wrong_password", h)


def test_password_hash_truncates_72_bytes():
    """bcrypt 72 字节限制：超长密码截断后不报错"""
    long_pwd = "a" * 200
    h = _hash_password(long_pwd)
    assert _verify_password("a" * 72, h)


def test_register_user_success():
    username = _uname()
    result = register_user(username, "pass123", tenant_id="org_1")
    assert result["username"] == username
    assert result["user_id"] > 0
    assert result["tenant_id"] == "org_1"
    assert result["collection_name"] == f"user_{result['user_id']}"


def test_register_duplicate_username():
    username = _uname()
    register_user(username, "pass123")
    result = register_user(username, "other_pass")
    assert result == {"error": "用户名已存在"}


def test_login_success():
    username = _uname()
    register_user(username, "correct_pass")
    result = login_user(username, "correct_pass")
    assert result is not None
    assert result["username"] == username
    assert result["role"] == "user"
    assert result["collection_name"].startswith("user_")


def test_login_wrong_password():
    username = _uname()
    register_user(username, "correct_pass")
    assert login_user(username, "wrong_pass") is None


def test_login_nonexistent_user():
    assert login_user(_uname("nobody"), "pass") is None


def test_get_user_by_id():
    username = _uname()
    reg = register_user(username, "pass123")
    user = get_user_by_id(reg["user_id"])
    assert user["username"] == username
    assert "password_hash" in user  # 内部字段存在（API 层负责过滤）
    assert get_user_by_id(999999) is None


def test_get_user_collection():
    assert get_user_collection(5) == "user_5"


def test_session_lifecycle():
    reg = register_user(_uname(), "pass123")
    uid = reg["user_id"]
    sid = save_session(uid, "项目上下文：Orbit 开发中")
    assert len(sid) == 16  # token_hex(8)

    s = get_session(sid)
    assert s["context"] == "项目上下文：Orbit 开发中"
    assert s["user_id"] == uid

    latest = get_latest_session(uid)
    assert latest["id"] == sid


def test_get_session_nonexistent():
    assert get_session("no_such_session") is None


def test_get_latest_session_empty():
    reg = register_user(_uname(), "pass123")
    # 新用户无会话（注意：auth_token fixture 的 pytest_user 可能有）
    assert get_latest_session(reg["user_id"]) is None
