"""Embedding 入口：单一后端（ONNX）、线程安全懒加载、预热、encode"""

import logging
import threading
from typing import Optional

from ..config import settings
from .backends import EMBED_DIM, EmbeddingBackend, OnnxBackend

logger = logging.getLogger(__name__)

_backend: Optional[EmbeddingBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> EmbeddingBackend:
    """获取 Embedding 后端（线程安全懒加载）。

    后端为单一实现：不再根据 settings.EMBED_BACKEND 分支 —— 见 config.EmbedStrategy
    的说明（历史上的多后端声明里有未实现的选项，会静默回退，反而更危险）。
    """
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = OnnxBackend().load()
    return _backend


def preload_model():
    """
    预热：在 FastAPI on_startup 事件中调用。
    确保第一个请求不需要等待模型加载（节省数秒延迟）。
    首次运行还包含一次模型下载（约 80MB），故启动可能多花 1~3 分钟。
    """
    logger.info("Preloading embedding model...")
    get_backend()
    logger.info("Embedding model ready.")


def encode(texts: list[str]) -> list[list[float]]:
    return get_backend().encode(texts)


__all__ = ["EMBED_DIM", "EmbeddingBackend", "OnnxBackend", "get_backend", "preload_model", "encode"]
