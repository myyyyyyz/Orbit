"""RAG strategy configuration models."""
from typing import Optional
from pydantic import BaseModel, Field


class ChunkPatch(BaseModel):
    chunk_size: Optional[int] = Field(default=None, ge=50, le=5000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=500)


class StoragePatch(BaseModel):
    pass


class RetrievalPatch(BaseModel):
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    search_mode: Optional[str] = None
    rerank_enabled: Optional[bool] = None


class StrategyPatch(BaseModel):
    chunk: Optional[ChunkPatch] = None
    storage: Optional[StoragePatch] = None
    retrieval: Optional[RetrievalPatch] = None

    # 注意：**没有 embed 段**。Embedding 只有一个实现（ONNX + all-MiniLM-L6-v2），
    # 且更换模型会改变向量维度 / 必须重建整个向量库，因此不做运行时可选配置。
    # 历史上这里有 EmbedPatch(embedding_model)，配合前端一个"Embedding 模型"下拉框，
    # 会造成"改得动但改不生效"的错觉；换模型请走发版流程而非该接口。


# Patch 字段名 → settings 属性名映射（命名不一致的字段）
# 顶层字段名（如 chunk_size / top_k）是**前端扁平结构**的兼容入口：
# 前端 StrategyPanel 提交的是扁平对象，pydantic 默认会静默忽略未知顶层字段，
# 于是这里显式声明，让扁平的 chunk_size / chunk_overlap / top_k / search_mode
# 也能真正落到对应 section 上（历史上它们会被静默丢弃，保存像成功但什么都没变）。
_FLAT_FIELD_TO_SECTION = {
    "chunk_size": "chunk",
    "chunk_overlap": "chunk",
    "top_k": "retrieval",
    "search_mode": "retrieval",
    "rerank_enabled": "retrieval",
}

_FIELD_ALIASES = {
    "chunk_size": "size",          # ChunkStrategy.size
    "chunk_overlap": "overlap",    # ChunkStrategy.overlap
    "search_mode": "method",       # RetrievalStrategy.method
}


def _apply_section(target: object, patch: Optional[BaseModel]) -> None:
    """Apply non-None fields from a Pydantic patch to a target object via setattr."""
    if patch is None:
        return
    for field_name, value in patch.model_dump(exclude_none=True).items():
        setattr(target, _FIELD_ALIASES.get(field_name, field_name), value)


def normalize_flat_patch(patch: dict) -> dict:
    """把前端的扁平 patch 归一到嵌套结构：{chunk_size: 800} → {chunk: {chunk_size: 800}}。

    已是嵌套结构或未知字段原样保留 —— 未知字段交由 pydantic 校验/忽略，不在此处报错。
    """
    nested: dict = {}
    passthrough: dict = {}
    for key, value in patch.items():
        section = _FLAT_FIELD_TO_SECTION.get(key)
        if section is None:
            passthrough[key] = value
        else:
            nested.setdefault(section, {})[key] = value

    result = dict(passthrough)
    for section, fields in nested.items():
        existing = result.get(section)
        if isinstance(existing, dict):
            result[section] = {**fields, **existing}
        else:
            result[section] = fields
    return result
