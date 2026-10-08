"""search/ — 语义检索模块测试（按 TenantScope 分区）"""
import uuid

from app.multitenant import TenantScope
from app.search import search, search_formatted, _get_cached_count, _invalidate_count_cache, _count_cache
from app.store import add_documents, get_collection

ANON = TenantScope()
TENANT_A = "org_search_a"
TENANT_B = "org_search_b"


def _shared(tenant=TENANT_A, user_id=1):
    return TenantScope(tenant, user_id, "shared")


def _personal(tenant=TENANT_A, user_id=1):
    return TenantScope(tenant, user_id, "personal")


def _seed(source, texts, scope=ANON):
    add_documents([{"text": t, "metadata": {"source": source}} for t in texts], scope)


def test_search_empty_collection():
    assert search("任意查询", scope=ANON) == []


def test_search_top_k_zero():
    source = "pytest_k0_" + uuid.uuid4().hex[:8]
    _seed(source, ["一些内容"])
    assert search("内容", top_k=0, scope=ANON) == []
    assert search("内容", top_k=-1, scope=ANON) == []


def test_search_returns_relevant_first():
    source = "pytest_rel_" + uuid.uuid4().hex[:8]
    _seed(source, [
        "Python 是一种解释型编程语言，强调代码可读性",
        "今天超市苹果打折促销",
        "FastAPI 是现代 Python Web 框架，支持异步",
    ])
    results = search("Python 编程语言特性", top_k=3, scope=ANON)
    assert len(results) == 3
    assert results[0]["metadata"]["source"] == source
    assert "Python" in results[0]["text"]
    # 按相似度降序
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_result_structure():
    source = "pytest_struct_" + uuid.uuid4().hex[:8]
    _seed(source, ["结构测试文本"])
    results = search("结构测试", top_k=1, scope=ANON)
    assert len(results) == 1
    item = results[0]
    # metadata 里额外标注来源作用域，便于前端区分组织/个人文档
    assert set(item.keys()) == {"text", "metadata", "score"}
    assert item["metadata"]["scope"] == "shared"
    assert 0.0 <= item["score"] <= 1.0  # 1 - cosine distance


def test_search_top_k_limits_results():
    source = "pytest_limit_" + uuid.uuid4().hex[:8]
    _seed(source, [f"文档片段编号 {i}" for i in range(6)])
    assert len(search("文档片段", top_k=3, scope=ANON)) == 3


def test_search_isolated_between_organizations():
    """跨组织不可见：A 组织写入的内容，B 组织搜不到。"""
    source = "pytest_org_" + uuid.uuid4().hex[:8]
    _seed(source, ["A 组织的内部规范文档"], _shared(TENANT_A, 1))

    hit_a = search("内部规范文档", scope=_shared(TENANT_A, 1))
    assert any(r["metadata"]["source"] == source for r in hit_a)
    assert search("内部规范文档", scope=_shared(TENANT_B, 9)) == []


def test_logged_in_user_reads_shared_plus_own_personal():
    """已登录成员：组织共享文档与自己的私有文档都能被检索到。"""
    shared_source = "pytest_org_shared_" + uuid.uuid4().hex[:8]
    personal_source = "pytest_my_private_" + uuid.uuid4().hex[:8]
    _seed(shared_source, ["组织共享的部署手册内容"], _shared(TENANT_A, 1))
    _seed(personal_source, ["我的私有笔记内容"], _personal(TENANT_A, 1))

    results = search("内容", top_k=10, scope=_shared(TENANT_A, 1))
    sources = {r["metadata"]["source"] for r in results}
    assert shared_source in sources
    assert personal_source in sources


def test_personal_documents_invisible_to_colleagues():
    """同组织成员之间：A 的私有文档 B 搜不到，但组织共享文档都能搜到。"""
    shared_source = "pytest_team_" + uuid.uuid4().hex[:8]
    private_source = "pytest_a_only_" + uuid.uuid4().hex[:8]
    _seed(shared_source, ["团队共享的接口约定"], _shared(TENANT_A, 1))
    _seed(private_source, ["甲的个人草稿，不应被同事看到"], _personal(TENANT_A, 1))

    colleague = search("内容", top_k=10, scope=_shared(TENANT_A, 2))
    sources = {r["metadata"]["source"] for r in colleague}
    assert shared_source in sources
    assert private_source not in sources


def test_anonymous_never_sees_tenant_data():
    source = "pytest_anon_" + uuid.uuid4().hex[:8]
    _seed(source, ["租户的机密内容"], _shared(TENANT_A, 1))
    assert search("机密内容", scope=ANON) == []


def test_search_formatted_empty():
    assert search_formatted("查询", scope=ANON) == "（知识库中未找到相关内容）"


def test_search_formatted_structure():
    source = "pytest_fmt_" + uuid.uuid4().hex[:8]
    _seed(source, ["格式化输出测试内容"])
    text = search_formatted("格式化输出", top_k=1, scope=ANON)
    assert text.startswith("## 知识库检索结果")
    assert "结果 1" in text
    assert "相关度" in text


def test_search_formatted_marks_shared_and_personal():
    shared_source = "pytest_fmt_shared_" + uuid.uuid4().hex[:8]
    personal_source = "pytest_fmt_priv_" + uuid.uuid4().hex[:8]
    _seed(shared_source, ["组织共享的格式化文本"], _shared(TENANT_A, 1))
    _seed(personal_source, ["个人私有的格式化文本"], _personal(TENANT_A, 1))

    text = search_formatted("格式化文本", top_k=5, scope=_shared(TENANT_A, 1))
    assert "组织共享" in text
    assert "我的文档" in text


def test_count_cache_invalidation():
    """_get_cached_count 缓存与 _invalidate_count_cache 失效"""
    _count_cache.clear()
    col = get_collection(ANON)
    name = "documents"
    _get_cached_count(col, name)
    assert name in _count_cache
    _invalidate_count_cache(name)
    assert name not in _count_cache
    # 全部失效
    _get_cached_count(col, name)
    _invalidate_count_cache()
    assert _count_cache == {}

