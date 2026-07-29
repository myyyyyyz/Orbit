"""Embedding 模块：支持 sentence-transformers（轻量本地）和 Ollama（BGE-M3）"""

from typing import Optional
from ..config import settings


class EmbeddingBackend:
    """统一的 Embedding 接口"""

    def __init__(self):
        self._model = None

    def load(self):
        raise NotImplementedError

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class SentenceTransformerBackend(EmbeddingBackend):
    """使用 sentence-transformers 本地模型"""

    def load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.EMBED_MODEL)
        return self

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self.load()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()


class OllamaBackend(EmbeddingBackend):
    """使用 Ollama 的 Embedding API"""

    def load(self):
        # Ollama 不需要预加载模型
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


def get_backend() -> EmbeddingBackend:
    global _backend
    if _backend is None:
        if settings.EMBED_BACKEND == "ollama":
            _backend = OllamaBackend().load()
        else:
            _backend = SentenceTransformerBackend().load()
    return _backend


def encode(texts: list[str]) -> list[list[float]]:
    return get_backend().encode(texts)
