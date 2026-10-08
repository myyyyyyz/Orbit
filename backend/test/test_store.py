"""store/ — ChromaDB 存储模块测试（临时目录隔离）

多租户后 collection 由 `TenantScope` 解析，不再有 `user_{id}` 这种写法：
- 组织共享 → `t_<tenant>`
- 成员私有 → `p_<tenant>:<user>`
- 匿名     → `settings.ANON_COLLECTION`
"""
import uuid

from app.config import settings
from app.multitenant import TenantScope
from app.store import (
    add_documents,
    collection_name,
    delete_by_source,
    get_client,
    get_collection,
    get_stats,
)

ANON = TenantScope()
TENANT_A = "org_pytest_a"
TENANT_B = "org_pytest_b"


def _shared(tenant=TENANT_A, user_id=1):
    return TenantScope(tenant, user_id, "shared")


def _personal(tenant=TENANT_A, user_id=1):
    return TenantScope(tenant, user_id, "personal")


def _doc(text, source):
    return {"text": text, "metadata": {"source": source}}


def test_client_singleton_threadsafe():
    assert get_client() is get_client()


def test_client_uses_temp_persist_dir():
    """确认测试用的是临时目录而非真实 data/"""
    assert "orbit_test_" in settings.CHROMA_PERSIST_DIR


def test_anon_collection_never_falls_back_to_global():
    """匿名必须落在独立沙箱，**绝不能**是全局 `documents` 库。

    回归：历史实现 `f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION`
    会让所有未登录访客共享全局 collection —— 任意匿名访客可读写、并删除
    他人上传的内容。
    """
    assert collection_name(ANON) == settings.ANON_COLLECTION
    assert collection_name(ANON) != settings.CHROMA_COLLECTION


def test_shared_and_personal_collections_are_distinct():
    """组织共享库与个人私有库必须是两个不同的名字（前缀 t_ / p_）。"""
    shared = collection_name(_shared())
    personal = collection_name(_personal())

    assert shared == "t_org_pytest_a"
    assert personal.startswith("p_")
    assert shared != personal
    assert shared != settings.ANON_COLLECTION
    assert personal != settings.ANON_COLLECTION


def test_collection_names_never_collide_across_tenants_or_users():
    """不同租户 / 不同成员解析出的库名两两不同（防止串库）。"""
    names = {
        collection_name(_shared(TENANT_A, 1)),
        collection_name(_shared(TENANT_B, 1)),
        collection_name(_personal(TENANT_A, 1)),
        collection_name(_personal(TENANT_A, 2)),
        collection_name(_personal(TENANT_B, 1)),
        collection_name(ANON),
    }
    assert len(names) == 6


def test_chroma_name_length_within_limit():
    """ChromaDB 约束：名称 ≤ 63 字符（超长租户/用户 id 也必须合规）。"""
    long_scope = TenantScope("org_" + "x" * 120, 12345678901234567890, "personal")
    name = collection_name(long_scope)
    assert 3 <= len(name) <= 63
    assert name[0].isalnum() and name[-1].isalnum()


def test_get_collection_scoping():
    anon_col = get_collection(ANON)
    shared_col = get_collection(_shared())
    personal_col = get_collection(_personal())

    assert anon_col.name == settings.ANON_COLLECTION
    assert shared_col.name == "t_org_pytest_a"
    assert len({anon_col.name, shared_col.name, personal_col.name}) == 3


def test_add_documents_empty():
    assert add_documents([]) == 0
    assert add_documents([], _shared()) == 0


def test_add_and_count():
    source = "pytest_store_" + uuid.uuid4().hex[:8]
    docs = [_doc("向量数据库是存储高维向量的系统", source), _doc("余弦相似度衡量向量方向差异", source)]
    count = add_documents(docs, ANON)
    assert count == 2
    assert get_collection(ANON).count() == 2


def test_add_documents_metadata_preserved():
    source = "pytest_meta_" + uuid.uuid4().hex[:8]
    add_documents([_doc("元数据测试", source)], ANON)
    results = get_collection(ANON).get(where={"source": source})
    assert len(results["ids"]) == 1
    assert results["metadatas"][0]["source"] == source


def test_delete_by_source():
    source = "pytest_del_" + uuid.uuid4().hex[:8]
    add_documents([_doc("待删除一", source), _doc("待删除二", source)], ANON)
    assert get_collection(ANON).count() == 2
    assert delete_by_source(source, ANON) == 2
    assert get_collection(ANON).count() == 0


def test_delete_by_source_nonexistent_no_error():
    assert delete_by_source("pytest_不存在的来源", ANON) == 0  # 不应抛异常


def test_delete_only_touches_same_scope():
    """删除只作用于当前作用域：删组织共享文档不能把个人私有文档一起删掉。"""
    source = "pytest_scope_del_" + uuid.uuid4().hex[:8]
    add_documents([_doc("组织共享文档", source)], _shared())
    add_documents([_doc("个人私有文档", source)], _personal())

    delete_by_source(source, _shared())

    assert get_collection(_shared()).count() == 0
    assert get_collection(_personal()).count() == 1


def test_tenant_isolation_between_organizations():
    """跨组织不可见：A 组织上传的内容，B 组织的库计数为 0。"""
    source = "pytest_org_iso_" + uuid.uuid4().hex[:8]
    add_documents([_doc("A 组织的机密文档", source)], _shared(TENANT_A, 1))
    add_documents([_doc("B 组织的机密文档", source)], _shared(TENANT_B, 9))

    assert get_collection(_shared(TENANT_A, 1)).count() == 1
    assert get_collection(_shared(TENANT_B, 9)).count() == 1
    assert get_collection(ANON).count() == 0


def test_personal_scope_isolation_inside_same_org():
    """同组织的两个成员：个人私有库互不可见。"""
    source = "pytest_priv_iso_" + uuid.uuid4().hex[:8]
    add_documents([_doc("成员1的私有文档", source)], _personal(TENANT_A, 1))
    add_documents([_doc("成员2的私有文档", source)], _personal(TENANT_A, 2))

    assert get_collection(_personal(TENANT_A, 1)).count() == 1
    assert get_collection(_personal(TENANT_A, 2)).count() == 1
    # 共享库仍是空的（私有写入不会污染共享库）
    assert get_collection(_shared(TENANT_A, 1)).count() == 0


def test_get_stats():
    stats = get_stats(ANON)
    assert stats["collection"] == settings.ANON_COLLECTION
    assert stats["tenant_id"] is None
    assert "total_chunks" in stats
    assert "orbit_test_" in stats["persist_dir"]

    stats_shared = get_stats(_shared())
    assert stats_shared["collection"] == "t_org_pytest_a"
    assert stats_shared["tenant_id"] == TENANT_A
    assert stats_shared["scope"] == "shared"
