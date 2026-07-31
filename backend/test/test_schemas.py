"""schemas/strategy.py — 策略 Patch 模型测试"""
import pytest
from pydantic import ValidationError

from app.schemas.strategy import StrategyPatch, ChunkPatch, RetrievalPatch, _apply_section


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
    assert patch.embed is None


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
