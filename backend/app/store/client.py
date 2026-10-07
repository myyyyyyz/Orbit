"""ChromaDB 客户端与 Collection 管理（线程安全单例、多租户隔离）"""

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


def collection_name(user_id: Optional[int] = None) -> str:
    """解析用户对应的 Collection 名称（多租户隔离的唯一事实源）。

    - user_id=1:    `user_1`（登录用户专属）
    - user_id=None: 匿名沙箱（`settings.ANON_COLLECTION`）

    ⚠️ 匿名**绝不**回退到全局 `settings.CHROMA_COLLECTION`（`documents`）。
    那是所有匿名访客共享的历史空间，一旦回退，任意未登录访客都能读取、
    写入并删除其中的全部内容——这与"多租户隔离"直接冲突。
    """
    return f"user_{user_id}" if user_id else settings.ANON_COLLECTION


def get_collection(user_id: Optional[int] = None) -> chromadb.Collection:
    """获取 Collection（名称由 collection_name() 统一解析）。"""
    return get_client().get_or_create_collection(
        name=collection_name(user_id),
        metadata={"hnsw:space": "cosine"},
    )


def get_collection_by_name(collection_name: str) -> chromadb.Collection:
    """按名称打开 Collection（服务端解析后的名称）。

    注意：绝不将此函数直接暴露给 HTTP 输入——collection 名称必须
    由服务端代码解析（如 active index 版本机制），防止任意 Collection 访问。
    """
    return get_client().get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
