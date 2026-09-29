"""Embedding 模块：单一实现，chromadb 内置 ONNX Runtime（all-MiniLM-L6-v2）

实现拆分为：backends（后端实现类）、core（懒加载/预热/入口），此处仅做导出。
"""
from .backends import EMBED_DIM, EmbeddingBackend, OnnxBackend
from .core import _backend, get_backend, preload_model, encode

__all__ = [
    "EMBED_DIM",
    "EmbeddingBackend",
    "OnnxBackend",
    "_backend",
    "get_backend",
    "preload_model",
    "encode",
]
