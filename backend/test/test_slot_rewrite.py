"""槽位 → 检索 query 改写 + 元数据过滤（slot_rewrite 模块）"""
import pytest

from app.retrieval.slot_rewrite import (
    rewrite_query_with_slots,
    build_metadata_filter,
)
from app.knowledge_agent.staging_store import _derive_doc_type


# ── query 改写：核心不变量是「不制造噪声」──

def test_no_slots_returns_original():
    assert rewrite_query_with_slots("什么是 RAG？", {}) == "什么是 RAG？"
    assert rewrite_query_with_slots("什么是 RAG？", None) == "什么是 RAG？"


def test_slot_already_in_query_not_duplicated():
    """槽位值已出现在原query 中 → 不重复注入（重复只会稀释 embedding 信号）"""
    q = "部署文档在哪"
    out = rewrite_query_with_slots(q, {"doc_type": "部署文档"})
    assert out == q
    assert out.count("部署文档") == 1


def test_missing_slot_gets_natural_language_append():
    """真正缺失的槽位才补，且必须是自然语言而非 key:value 串"""
    q = "这个报错了"
    out = rewrite_query_with_slots(q, {"error": "NullPointerException"})
    assert "NullPointerException" in out
    assert "error:" not in out and "error=" not in out


def test_time_slot_appended():
    out = rewrite_query_with_slots("有哪些接口文档", {"time": "上周"})
    assert "上周" in out


def test_rewrite_never_deletes_original_words():
    """改写只做追加，绝不删改用户原话"""
    q = "帮我看看它上周的部署文档呢"
    out = rewrite_query_with_slots(q, {"time": "上周", "doc_type": "部署文档"})
    for token in ("帮我看看", "部署文档"):
        assert token in out


def test_rewrite_is_idempotent():
    """对同一 query 反复改写不应无限膨胀"""
    q = "这个报错了"
    once = rewrite_query_with_slots(q, {"error": "NullPointerException"})
    twice = rewrite_query_with_slots(once, {"error": "NullPointerException"})
    assert once == twice


# ── 元数据过滤：只对确认存在的字段生成 where ──

def test_metadata_filter_requires_declared_field():
    """字段未声明时不生成 where（否则旧索引会过滤不到任何东西）"""
    assert build_metadata_filter({"doc_type": "部署文档"}, set()) is None
    assert build_metadata_filter({"doc_type": "部署文档"}, None) is None


def test_metadata_filter_built_when_field_declared():
    where = build_metadata_filter({"doc_type": "部署文档"}, {"doc_type"})
    assert where == {"doc_type": "部署文档"}


def test_metadata_filter_none_when_no_matching_slot():
    assert build_metadata_filter({"time": "上周"}, {"doc_type"}) is None


# ── 摄取期 doc_type 推导 ──

@pytest.mark.parametrize("path,expected", [
    ("docs/部署手册.md", "部署文档"),
    ("接口文档.md", "接口文档"),
    ("api-guide.md", "接口文档"),
    ("架构设计.md", "架构文档"),
    ("需求文档.md", "需求文档"),
    ("weekly.md", "file:md"),
    ("noext", "unknown"),
    ("", "unknown"),
])
def test_derive_doc_type(path, expected):
    assert _derive_doc_type(path) == expected


def test_derive_doc_type_never_returns_none():
    """ChromaDB 要求 metadata 值为非 None 标量——None 会被丢字段导致 where 失效"""
    for p in ["", "a", "x.pdf", "docs/周报.md", "\\win\\path\\部署.md"]:
        assert _derive_doc_type(p) is not None