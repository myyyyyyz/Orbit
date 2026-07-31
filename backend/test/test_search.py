"""search/ — 语义检索模块测试"""
import uuid

from app.search import search, search_formatted, _get_cached_count, _invalidate_count_cache, _count_cache
from app.store import add_documents, get_collection


def _seed(source, texts):
    add_documents([{"text": t, "metadata": {"source": source}} for t in texts])


def test_search_empty_collection():
    assert search("任意查询") == []


def test_search_top_k_zero():
    source = "pytest_k0_" + uuid.uuid4().hex[:8]
    _seed(source, ["一些内容"])
    assert search("内容", top_k=0) == []
    assert search("内容", top_k=-1) == []


def test_search_returns_relevant_first():
    source = "pytest_rel_" + uuid.uuid4().hex[:8]
    _seed(source, [
        "Python 是一种解释型编程语言，强调代码可读性",
        "今天超市苹果打折促销",
        "FastAPI 是现代 Python Web 框架，支持异步",
    ])
    results = search("Python 编程语言特性", top_k=3)
    assert len(results) == 3
    assert results[0]["metadata"]["source"] == source
    assert "Python" in results[0]["text"]
    # 按相似度降序
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_result_structure():
    source = "pytest_struct_" + uuid.uuid4().hex[:8]
    _seed(source, ["结构测试文本"])
    results = search("结构测试", top_k=1)
    assert len(results) == 1
    item = results[0]
    assert set(item.keys()) == {"text", "metadata", "score"}
    assert 0.0 <= item["score"] <= 1.0  # 1 - cosine distance


def test_search_top_k_limits_results():
    source = "pytest_limit_" + uuid.uuid4().hex[:8]
    _seed(source, [f"文档片段编号 {i}" for i in range(6)])
    assert len(search("文档片段", top_k=3)) == 3


def test_search_user_isolation():
    source = "pytest_siso_" + uuid.uuid4().hex[:8]
    _seed(source, ["全局文档"])
    add_documents([{"text": "用户9私有", "metadata": {"source": source}}], user_id=9)
    assert len(search("文档", user_id=None)) >= 1
    results_user9 = search("私有", user_id=9)
    assert all(r["metadata"]["source"] == source for r in results_user9)


def test_search_formatted_empty():
    assert search_formatted("查询") == "（知识库中未找到相关内容）"


def test_search_formatted_structure():
    source = "pytest_fmt_" + uuid.uuid4().hex[:8]
    _seed(source, ["格式化输出测试内容"])
    text = search_formatted("格式化输出", top_k=1)
    assert text.startswith("## 知识库检索结果")
    assert "结果 1" in text
    assert "相关度" in text
    assert source in text


def test_count_cache_invalidation():
    """_get_cached_count 缓存与 _invalidate_count_cache 失效"""
    _count_cache.clear()
    col = get_collection(None)
    name = "documents"
    _get_cached_count(col, name)
    assert name in _count_cache
    _invalidate_count_cache(name)
    assert name not in _count_cache
    # 全部失效
    _get_cached_count(col, name)
    _invalidate_count_cache()
    assert _count_cache == {}
