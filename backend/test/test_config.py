"""config.py — Settings 配置与兼容属性测试"""
from app.config import settings, Settings, RAGStrategy


def test_settings_singleton_exists():
    assert settings is not None
    assert isinstance(settings.rag, RAGStrategy)


def test_compat_properties():
    """旧接口 property 与 rag 子策略一致"""
    assert settings.CHROMA_PERSIST_DIR == settings.rag.storage.persist_dir
    assert settings.CHROMA_COLLECTION == settings.rag.storage.collection
    assert settings.EMBED_BACKEND == settings.rag.embed.backend
    assert settings.EMBED_MODEL == settings.rag.embed.model
    assert settings.OLLAMA_HOST == settings.rag.embed.ollama_host
    assert settings.CHUNK_SIZE == settings.rag.chunk.size
    assert settings.CHUNK_OVERLAP == settings.rag.chunk.overlap
    assert settings.TOP_K == settings.rag.retrieval.top_k


def test_default_strategy_values():
    s = Settings()
    assert s.rag.chunk.method == "semantic"
    assert s.rag.chunk.size == 500
    assert s.rag.chunk.overlap == 50
    assert s.rag.embed.backend == "sentence-transformers"
    assert s.rag.storage.distance_metric == "cosine"
    assert s.rag.retrieval.top_k == 5
    assert s.rag.retrieval.score_threshold == 0.0
    assert s.MAX_FILE_SIZE == 20 * 1024 * 1024


def test_database_url_from_env():
    """conftest 已注入临时 DATABASE_URL"""
    assert "orbit_test_" in settings.DATABASE_URL
    assert settings.DATABASE_URL.startswith("sqlite:///")
