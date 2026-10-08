"""ChromaDB 客户端与 Collection 管理（线程安全单例、多租户隔离）。

Collection 命名规则集中在 `app.multitenant.naming`，本模块只负责把
`TenantScope` 映射成 ChromaDB Collection。**不要**在这里再写一份命名逻辑——
历史上 `store/client.py` 与 `knowledge_agent/releases.py` 各维护了一份
`user_{id}` 规则，漏改一处就跨租户串库。
"""

import threading
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from ..config import settings


_client = None
_client_lock = threading.Lock()


def get_client() -> chromadb.ClientAPI:
    """获取 ChromaDB 客户端（线程安全单例）"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = chromadb.PersistentClient(
                    path=settings.CHROMA_PERSIST_DIR,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
    return _client


def resolve_scope(scope=None):
    """解析本次访问的作用域；未显式传入时读取请求级租户上下文。

    读取上下文这一路径是**有意**的：身份只在认证层确定一次，深层的检索 /
    入库代码无需层层透传参数，也不会因为忘了传就落到全局库——
    拿不到上下文时 `get_current_scope()` 返回匿名沙箱（fail-closed）。
    """
    if scope is not None:
        return scope
    from ..multitenant.context import get_current_scope

    return get_current_scope()


def collection_name(scope=None) -> str:
    """解析作用域对应的 Collection 名称（多租户隔离的唯一事实源）。

    - 组织共享 → ``t_<tenant>``
    - 成员私有 → ``p_<tenant:user>``
    - 匿名     → ``settings.ANON_COLLECTION``（独立沙箱）

    ⚠️ 匿名**绝不**回退到全局 `settings.CHROMA_COLLECTION`（`documents`）。
    那是所有匿名访客共享的历史空间，一旦回退，任意未登录访客都能读取、
    写入并删除其中的全部内容——这与"多租户隔离"直接冲突。
    """
    return resolve_scope(scope).collection


def get_collection(scope=None) -> chromadb.Collection:
    """获取 Collection（名称由 collection_name() 统一解析）。"""
    return get_client().get_or_create_collection(
        name=collection_name(scope),
        metadata={"hnsw:space": "cosine"},
    )


def get_collection_by_name(name: str) -> chromadb.Collection:
    """按名称打开 Collection（名称必须由服务端解析，不接受 HTTP 输入）。

    注意：绝不将此函数直接暴露给 HTTP 输入——collection 名称必须
    由服务端代码解析（如 active index 版本机制），防止任意 Collection 访问。
    """
    return get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
