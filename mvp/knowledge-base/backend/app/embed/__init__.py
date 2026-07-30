"""Embedding 模块：支持 sentence-transformers（轻量本地）和 Ollama（BGE-M3）"""

import logging
import threading
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)


class EmbeddingBackend:
    """统一的 Embedding 接口"""

    def __init__(self):
        self._model = None
        self._loaded = False

    def load(self):
        raise NotImplementedError

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def is_loaded(self) -> bool:
        return self._loaded


class SentenceTransformerBackend(EmbeddingBackend):
    """使用 sentence-transformers 本地模型"""

    def load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s ...", settings.EMBED_MODEL)
            self._model = SentenceTransformer(settings.EMBED_MODEL)
            self._loaded = True
            logger.info("Embedding model loaded: %s", settings.EMBED_MODEL)
        return self

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self.load()
        # 分批编码，避免大批量文本 OOM
        batch_size = 32
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = self._model.encode(batch, normalize_embeddings=True)
            all_embeddings.extend(batch_embeddings.tolist())
        return all_embeddings


class OllamaBackend(EmbeddingBackend):
    """使用 Ollama 的 Embedding API"""

    def load(self):
        self._loaded = True
        return self

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import requests
        embeddings = []
        for text in texts:
            resp = requests.post(
                f"{settings.OLLAMA_HOST}/api/embeddings",
                json={"model": settings.EMBED_MODEL, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
        return embeddings


_backend: Optional[EmbeddingBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> EmbeddingBackend:
    """获取 Embedding 后端（线程安全懒加载）"""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                if settings.EMBED_BACKEND == "ollama":
                    _backend = OllamaBackend().load()
                else:
                    _backend = SentenceTransformerBackend().load()
    return _backend


def preload_model():
    """
    预热：在 FastAPI on_startup 事件中调用。
    确保第一个请求不需要等待模型加载（节省数秒延迟）。
    """
    logger.info("Preloading embedding model...")
    get_backend()
    logger.info("Embedding model ready.")


def encode(texts: list[str]) -> list[list[float]]:
    return get_backend().encode(texts)
