"""store/ — ChromaDB 存储模块测试（临时目录隔离）"""
import uuid

from app.store import get_client, get_collection, add_documents, delete_by_source, get_stats
from app.config import settings


def _doc(text, source):
    return {"text": text, "metadata": {"source": source}}


def test_client_singleton_threadsafe():
    assert get_client() is get_client()


def test_client_uses_temp_persist_dir():
    """确认测试用的是临时目录而非真实 data/"""
    assert "orbit_test_" in settings.CHROMA_PERSIST_DIR


def test_get_collection_global_and_user_scoped():
    global_col = get_collection(None)
    user_col = get_collection(42)
    assert global_col.name == settings.CHROMA_COLLECTION
    assert user_col.name == "user_42"
    assert global_col.name != user_col.name


def test_add_documents_empty():
    assert add_documents([]) == 0
    assert add_documents([], user_id=1) == 0


def test_add_and_count():
    source = "pytest_store_" + uuid.uuid4().hex[:8]
    docs = [_doc("向量数据库是存储高维向量的系统", source), _doc("余弦相似度衡量向量方向差异", source)]
    count = add_documents(docs)
    assert count == 2
    assert get_collection(None).count() == 2


def test_add_documents_metadata_preserved():
    source = "pytest_meta_" + uuid.uuid4().hex[:8]
    add_documents([_doc("元数据测试", source)])
    results = get_collection(None).get(where={"source": source})
    assert len(results["ids"]) == 1
    assert results["metadatas"][0]["source"] == source


def test_delete_by_source():
    source = "pytest_del_" + uuid.uuid4().hex[:8]
    add_documents([_doc("待删除一", source), _doc("待删除二", source)])
    assert get_collection(None).count() == 2
    delete_by_source(source)
    assert get_collection(None).count() == 0


def test_delete_by_source_nonexistent_no_error():
    delete_by_source("pytest_不存在的来源")  # 不应抛异常


def test_user_collection_isolation():
    """用户 collection 数据互不可见"""
    source = "pytest_iso_" + uuid.uuid4().hex[:8]
    add_documents([_doc("用户1的私有文档", source)], user_id=1)
    add_documents([_doc("用户2的私有文档", source)], user_id=2)
    assert get_collection(1).count() == 1
    assert get_collection(2).count() == 1
    assert get_collection(None).count() == 0  # 全局库无数据


def test_get_stats():
    stats = get_stats()
    assert stats["collection"] == settings.CHROMA_COLLECTION
    assert "total_chunks" in stats
    assert "orbit_test_" in stats["persist_dir"]

    stats_user = get_stats(user_id=7)
    assert stats_user["collection"] == "user_7"
