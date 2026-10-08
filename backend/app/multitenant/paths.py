"""租户作用域下的文件系统路径（上传 / 记忆 / 工作区）。

目录布局（拼在 ``DATA_DIR`` 之下，全由服务端拼接、不接受客户端输入）::

    DATA_DIR/
    ├── tenants/{tenant_id}/              ← 组织共享空间
    │   ├── uploads/                      ← 组织共享文档原件
    │   ├── memory/                       ← 组织级记忆（如后续需要）
    │   └── users/{user_id}/              ← 成员私有空间
    │       ├── uploads/                  ← 个人私有文档原件
    │       └── memory/YYYY-MM-DD.md      ← 个人对话记忆
    ├── anon/                             ← 匿名访客沙箱
    └── chroma_db/                        ← 向量库（collection 内部分区）

所有分段经 :func:`app.multitenant.naming.slug` 消毒，不可能出现 ``..`` 穿越。
"""

from pathlib import Path
from typing import Optional

from ..config import DATA_DIR
from .context import PERSONAL, TenantScope, get_current_scope


def _resolve(scope: Optional[TenantScope]) -> TenantScope:
    return scope if scope is not None else get_current_scope()


def scope_root(scope: Optional[TenantScope] = None) -> Path:
    """该作用域的根目录。"""
    return Path(DATA_DIR) / _resolve(scope).rel_path


def uploads_dir(scope: Optional[TenantScope] = None, *, create: bool = True) -> Path:
    """上传原件目录。"""
    path = scope_root(scope) / "uploads"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def memory_dir(scope: Optional[TenantScope] = None, *, create: bool = True) -> Path:
    """对话记忆目录（人机双读的 Markdown）。"""
    path = scope_root(scope) / "memory"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_memory_dir(scope: Optional[TenantScope] = None, *, create: bool = True) -> Path:
    """**个人**记忆目录（与作用域无关，始终按"人"落盘）。

    记忆是"某个人的对话"，即便当次查询发生在组织共享作用域下也应落个人目录，
    否则同组织成员的对话总结会混进同一个文件——这正是改造前
    "所有用户写同一份 memory/YYYY-MM-DD.md"的翻版。

    匿名访客落 ``anon/memory``；极端情况下（有租户但缺 user_id）退回作用域根目录。
    """
    resolved = _resolve(scope)

    if resolved.is_anonymous:
        path = Path(DATA_DIR) / "anon" / "memory"
    elif resolved.user_id is None:
        path = scope_root(resolved) / "memory"
    else:
        # 复用一个"个人作用域"来算路径，避免在这里再写一遍目录规则
        personal = TenantScope(resolved.tenant_id, resolved.user_id, PERSONAL)
        path = scope_root(personal) / "memory"

    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
