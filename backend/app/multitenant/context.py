"""请求级租户上下文（多租户隔离的身份传播层）。

设计原则（呼应 docs/MULTI-TENANT-PLAN.md 第 2 节）：

1. **身份只在认证层确定一次** —— 由 `middleware/auth.py` 从验签后的 JWT claim
   写入 ContextVar，随后四条链路（数据 / 向量 / 文件 / 进程内状态）各自读取。
2. **永不信任 body / query / 自定义 header 里的 tenant_id** —— 那是可伪造的输入。
3. **fail-closed** —— 解析不到租户身份就落到匿名沙箱（看不到任何真实租户数据），
   绝不静默回退到全局库或"默认租户"。

`TenantScope` 是不可变值对象，同时承担三个职责（保持三者永远一致）：
- 向量库 Collection 名
- 文件系统相对目录
- 缓存 key / 用量记录的命名空间
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

from ..logging_config import get_logger
from .naming import (
    anon_collection,
    personal_collection,
    safe_dir_name,
    shared_collection,
)

logger = get_logger(__name__)

# ── scope 取值 ─────────────────────────────────────
SHARED = "shared"      # 组织共享：租户内所有成员可见
PERSONAL = "personal"  # 成员私有：仅本人可见
VALID_SCOPES = (SHARED, PERSONAL)


@dataclass(frozen=True)
class TenantScope:
    """一次请求 / 一次数据访问的租户作用域。

    - ``tenant_id is None`` → 匿名沙箱（fail-closed 的落点）
    - ``scope == SHARED``   → 组织共享库
    - ``scope == PERSONAL`` → 成员私有库（要求 tenant_id 与 user_id 同时存在）
    """

    tenant_id: Optional[str] = None
    user_id: Optional[int] = None
    scope: str = SHARED

    def __post_init__(self) -> None:
        if self.scope not in VALID_SCOPES:
            raise ValueError(f"未知 scope: {self.scope!r}（可选: {VALID_SCOPES}）")
        if self.scope == PERSONAL and (not self.tenant_id or self.user_id is None):
            raise ValueError("personal scope 需要同时具备 tenant_id 与 user_id")
        if self.tenant_id is not None and not str(self.tenant_id).strip():
            raise ValueError("tenant_id 不能为空字符串")

    # ── 派生标识 ────────────────────────────────────

    @property
    def is_anonymous(self) -> bool:
        return not self.tenant_id

    @property
    def is_personal(self) -> bool:
        return self.scope == PERSONAL

    @property
    def collection(self) -> str:
        """该作用域对应的 ChromaDB Collection 名。"""
        if self.is_anonymous:
            return anon_collection()
        if self.is_personal:
            return personal_collection(self.tenant_id, self.user_id)
        return shared_collection(self.tenant_id)

    @property
    def storage_key(self) -> str:
        """进程内状态 / 数据库行归属用的命名空间键（缓存 key、用量归属、release 记录）。

        与 :attr:`collection` 分开：`storage_key` 允许冒号等可读字符，
        只用于字符串拼接与等值比较，不受 ChromaDB 命名约束。
        """
        if self.is_anonymous:
            return "anon"
        if self.is_personal:
            return f"t:{self.tenant_id}:u:{self.user_id}"
        return f"t:{self.tenant_id}"

    @property
    def rel_path(self) -> str:
        """文件系统相对目录（拼在 DATA_DIR 之下）。

        一律由服务端拼接、不接受客户端输入，且各段经 :func:`slug` 消毒，
        不可能出现 ``..`` 穿越。
        """
        if self.is_anonymous:
            return "anon"
        tenant = safe_dir_name(self.tenant_id)
        if self.is_personal:
            return f"tenants/{tenant}/users/{self.user_id}"
        return f"tenants/{tenant}"

    @property
    def read_key(self) -> str:
        """读取链路的命名空间键（缓存 key 前缀、用量归属）。

        与 :attr:`storage_key` 的关键区别：**必须区分到人**。

        读取时会同时检索"组织共享 ∪ 本人私有"，两路合并后才生成答案，
        所以答案的依赖集合由 (tenant, user) 共同决定。若只按租户分命名空间，
        同组织的成员 B 会命中 A 基于**A 的私有文档**生成的缓存答案——
        那就是一次跨用户内容泄露。因此这里带 user 维度。
        """
        if self.is_anonymous:
            return "anon"
        if self.user_id is None:
            return f"t:{self.tenant_id}"
        return f"t:{self.tenant_id}:u:{self.user_id}"

    @property
    def tenant_prefix(self) -> str:
        """租户级前缀 —— 清除"组织共享库变更"影响到的全部成员缓存时使用。"""
        return f"t:{self.tenant_id}:"

    def describe(self) -> dict:
        """对外可安全暴露的描述（不含任何数据内容）。"""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "scope": self.scope,
            "anonymous": self.is_anonymous,
        }


ANON_SCOPE = TenantScope()


def scope_for(
    tenant_id: Optional[str],
    user_id: Optional[int] = None,
    scope: str = SHARED,
) -> TenantScope:
    """构造作用域；缺租户身份时**降级为匿名**（fail-closed）。

    登录用户理论上一定有 tenant_id（注册即建/入租户，迁移也已回填）。
    真出现缺失（脏数据 / 手工插入）时降级到匿名沙箱并告警，
    绝不退化成"查全表"或"用默认租户"。
    """
    if not tenant_id:
        if user_id is not None:
            logger.warning(
                "tenant_missing_for_user",
                user_id=user_id,
                hint="用户无 tenant_id，已降级到匿名沙箱（fail-closed）",
            )
        return ANON_SCOPE
    if scope == PERSONAL and user_id is None:
        return TenantScope(tenant_id=tenant_id, user_id=None, scope=SHARED)
    return TenantScope(tenant_id=str(tenant_id), user_id=user_id, scope=scope)


def scope_from_user(user: Optional[dict], scope: str = SHARED) -> TenantScope:
    """从认证依赖返回的 user dict 构造作用域。"""
    if not user:
        return ANON_SCOPE
    return scope_for(user.get("tenant_id"), user.get("user_id"), scope)


def read_scopes(base: Optional[TenantScope] = None) -> tuple[TenantScope, ...]:
    """解析一次**读取**实际要覆盖的作用域集合。

    产品语义（用户明确要求）：组织内共享文档 + 自己的私有文档，
    提问时两者都要能被检索到。

    - 匿名 → 只有匿名沙箱
    - 已登录 → 组织共享库 + （本人）私有库
    """
    resolved = base or get_current_scope()
    if resolved.is_anonymous:
        return (resolved,)
    scopes = [TenantScope(resolved.tenant_id, resolved.user_id, SHARED)]
    if resolved.user_id is not None:
        scopes.append(TenantScope(resolved.tenant_id, resolved.user_id, PERSONAL))
    return tuple(scopes)


# ── ContextVar（请求作用域）─────────────────────────
#
# FastAPI 的依赖与端点函数在同一个 asyncio Task / 线程上下文中执行，
# ContextVar 天然随请求生效、请求结束自动回收，无需手动清理，
# 也不会像模块级全局变量那样跨请求残留（那正是"租户 A 拿到租户 B 身份"
# 最隐蔽的成因）。

_current_scope: ContextVar[Optional[TenantScope]] = ContextVar(
    "orbit_tenant_scope", default=None
)


def set_current_scope(scope: TenantScope) -> Token:
    """写入当前请求的租户作用域，返回可用于回滚的 token。"""
    return _current_scope.set(scope)


def get_current_scope() -> TenantScope:
    """读取当前请求的租户作用域；未设置时返回匿名沙箱（fail-closed）。"""
    return _current_scope.get() or ANON_SCOPE


def reset_current_scope(token: Token) -> None:
    _current_scope.reset(token)


def clear_current_scope() -> None:
    """清空上下文（仅供测试使用）。"""
    _current_scope.set(None)
