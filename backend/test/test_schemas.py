"""schemas/strategy.py — 策略 Patch 模型测试"""
import pytest
from pydantic import ValidationError

from app.schemas.strategy import (
    StrategyPatch,
    ChunkPatch,
    RetrievalPatch,
    _apply_section,
    normalize_flat_patch,
)


def test_empty_patch_valid():
    patch = StrategyPatch()
    assert patch.chunk is None
    assert patch.retrieval is None


def test_chunk_patch_validation_bounds():
    assert ChunkPatch(chunk_size=50).chunk_size == 50
    assert ChunkPatch(chunk_size=5000).chunk_size == 5000
    with pytest.raises(ValidationError):
        ChunkPatch(chunk_size=10)      # 低于下限 50
    with pytest.raises(ValidationError):
        ChunkPatch(chunk_size=99999)   # 超过上限 5000
    with pytest.raises(ValidationError):
        ChunkPatch(chunk_overlap=501)  # 超过上限 500


def test_retrieval_patch_bounds():
    assert RetrievalPatch(top_k=1).top_k == 1
    assert RetrievalPatch(top_k=50).top_k == 50
    with pytest.raises(ValidationError):
        RetrievalPatch(top_k=0)
    with pytest.raises(ValidationError):
        RetrievalPatch(top_k=51)


def test_apply_section_none_patch_noop():
    class Target:
        size = 500
    _apply_section(Target, None)
    assert Target.size == 500


def test_apply_section_applies_only_non_none_fields():
    class Target:
        def __init__(self):
            self.top_k = 5
            self.rerank_enabled = False

    target = Target()
    patch = RetrievalPatch(top_k=10)  # rerank_enabled 未设置
    _apply_section(target, patch)
    assert target.top_k == 10
    assert target.rerank_enabled is False  # 未被 None 覆盖


def test_strategy_patch_from_dict():
    patch = StrategyPatch(**{"chunk": {"chunk_size": 300}, "retrieval": {"top_k": 10}})
    assert patch.chunk.chunk_size == 300
    assert patch.retrieval.top_k == 10
    # embed 段已移除：embedding 是单一实现，换模型必须重建向量库，不做运行时配置
    assert not hasattr(patch, "embed")


def test_normalize_flat_patch_nests_frontend_payload():
    """前端 StrategyPanel 提交的是扁平对象，必须被归一到嵌套 section。

    回归：此前顶层未知字段被 pydantic 静默忽略，保存请求返回 200 但什么都没变。
    """
    assert normalize_flat_patch({"chunk_size": 800, "top_k": 10}) == {
        "chunk": {"chunk_size": 800},
        "retrieval": {"top_k": 10},
    }
    # 已是嵌套结构的原样保留；两种形式混用时按字段合并
    assert normalize_flat_patch({"retrieval": {"top_k": 3}, "search_mode": "hybrid"}) == {
        "retrieval": {"search_mode": "hybrid", "top_k": 3},
    }
    # 未知字段透传，交由 pydantic 校验/忽略，不在此处报错
    assert normalize_flat_patch({"nope": 1}) == {"nope": 1}


def test_normalize_flat_patch_then_validate():
    """归一化后的扁平 payload 必须能真正落到 settings 对象上（端到端最小复现）。"""
    class _Chunk:
        size = 500
        overlap = 50

    class _Retrieval:
        top_k = 5

    class _Target:
        chunk = _Chunk()
        retrieval = _Retrieval()

    target = _Target()
    validated = StrategyPatch(**normalize_flat_patch({"chunk_size": 900, "top_k": 7}))
    _apply_section(target.chunk, validated.chunk)
    _apply_section(target.retrieval, validated.retrieval)
    assert target.chunk.size == 900
    assert target.chunk.overlap == 50  # 未提交的字段不被覆盖
    assert target.retrieval.top_k == 7


def test_apply_section_field_alias_mapping():
    """字段名与目标属性名不一致时通过别名映射（回归：chunk_size → size）"""
    class FakeChunkStrategy:
        def __init__(self):
            self.size = 500
            self.overlap = 50

    target = FakeChunkStrategy()
    _apply_section(target, ChunkPatch(chunk_size=800, chunk_overlap=100))
    assert target.size == 800
    assert target.overlap == 100
    assert not hasattr(target, "chunk_size")  # 不应产生错误属性
