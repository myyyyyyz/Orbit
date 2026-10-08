"""多租户隔离载体的命名规则（Collection / 目录）—— 唯一事实源。

所有"按租户 / 按用户分区"的名字都必须经由本模块生成，**禁止**在各处手写
`f"user_{id}"` 之类的字符串。历史事故：`store/client.py` 与
`knowledge_agent/releases.py` 各自维护了一份命名规则（`user_{id}` /
`_legacy_collection`），漏改一处就会跨租户串库。

命名空间设计（两级粒度，对应"组织共享 + 个人私有"）：

- 匿名（未登录）→ ``settings.ANON_COLLECTION``，独立沙箱，**永不**回退到全局库
- 组织共享     → ``t_<tenant>``    —— 租户内所有成员可见
- 成员私有     → ``p_<tenant:user>`` —— 仅该成员可见

两个前缀（``t_`` / ``p_``）不同，保证"共享库名"与"私有库名"不可能撞名。
"""

import hashlib
import re
from typing import Optional

# ChromaDB Collection 名称约束：3–63 字符，仅 [a-zA-Z0-9._-]，首尾须字母数字
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")

# 单段最大长度：2 字符前缀 + 40 字符段 = 42 < 63，留足余量
_MAX_SEGMENT = 40


def slug(value: object) -> str:
    """把任意标识符规范成可安全嵌入 Collection 名 / 目录名的一段。

    规则：
    1. 非法字符替换为 ``-``，首尾裁掉 ``-`` / ``.`` / ``_``
    2. 发生过替换、或原文超长时追加短哈希 —— 保证**不同输入不撞名**
       （单纯截断会丢双射性，两个不同 tenant_id 可能规范到同一个名字）
    3. 保证首尾为字母数字，满足 ChromaDB 约束

    例子：``org_acme`` → ``org_acme``；``org/acme`` → ``org-acme-3f2a1b0c94``
    """
    raw = "" if value is None else str(value)
    cleaned = _UNSAFE.sub("-", raw).strip("-._")

    if not cleaned or cleaned != raw or len(cleaned) > _MAX_SEGMENT:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
        head = cleaned[: _MAX_SEGMENT - len(digest) - 1].strip("-._") or "t"
        cleaned = f"{head}-{digest}"

    if not cleaned[0].isalnum():
        cleaned = "t" + cleaned
    if not cleaned[-1].isalnum():
        cleaned = cleaned + "z"
    return cleaned


def shared_collection(tenant_id: str) -> str:
    """组织共享知识库 → ``t_<tenant>``（租户内成员均可读写）。"""
    return f"t_{slug(tenant_id)}"


def personal_collection(tenant_id: str, user_id: object) -> str:
    """成员私有知识库 → ``p_<tenant:user>``（仅该成员可见）。

    把 tenant 与 user 拼成一个字符串再 slug，而不是分别 slug 后截断：
    分段截断会丢双射性（``("a", "b:c")`` 与 ``("a:b", "c")`` 会被规范成同一段）。
    """
    return f"p_{slug(f'{tenant_id}:{user_id}')}"


def safe_dir_name(value: object) -> str:
    """目录名安全化（与 Collection 名同一套规则，避免路径穿越）。"""
    return slug(value)


def anon_collection() -> str:
    """匿名沙箱 Collection 名（延迟读取 settings，便于测试覆盖）。"""
    from ..config import settings

    return settings.ANON_COLLECTION


def legacy_global_collection() -> str:
    """历史遗留的全局共享库名（``documents``）。

    仅用于**只读兼容**与迁移脚本；运行时任何链路都不得再写入或回退到它。
    """
    from ..config import settings

    return settings.CHROMA_COLLECTION


def normalize_scope(value: Optional[str]) -> str:
    """把外部传入的 scope 参数归一化，非法值一律回落到 ``shared``。

    注意：这是**取值归一化**，不是鉴权。个人库是否可用仍由登录态决定
    （未登录时 ``personal`` 会被降级为匿名沙箱，见 ``context.TenantScope``）。
    """
    return "personal" if str(value or "").strip().lower() == "personal" else "shared"
