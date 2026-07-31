"""embed/ — Embedding 模块测试（真实 sentence-transformers 模型，session 级加载）"""
import pytest

from app.embed import encode, get_backend, SentenceTransformerBackend, OllamaBackend


@pytest.fixture(scope="module", autouse=True)
def _load_model_once():
    """模块级预热，避免每个测试重复触发加载逻辑"""
    get_backend()


def test_backend_singleton():
    b1 = get_backend()
    b2 = get_backend()
    assert b1 is b2
    assert b1.is_loaded


def test_encode_empty_list():
    assert encode([]) == []


def test_encode_single_text():
    result = encode(["知识库问答系统"])
    assert len(result) == 1
    assert len(result[0]) == 384  # all-MiniLM-L6-v2 维度
    assert all(isinstance(x, float) for x in result[0])


def test_encode_batch():
    result = encode(["文本一", "文本二", "文本三"])
    assert len(result) == 3
    # 不同文本向量不同
    assert result[0] != result[1]


def test_encode_normalized():
    """normalize_embeddings=True → 向量模长为 1"""
    vec = encode(["归一化测试"])[0]
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_encode_semantic_similarity():
    """语义相近的文本 cosine 相似度应高于无关文本"""
    a, b, c = encode(["如何重置密码", "忘记密码怎么办", "今天天气真好"])
    def cosine(x, y):
        return sum(p * q for p, q in zip(x, y))  # 已归一化，点积即 cosine
    assert cosine(a, b) > cosine(a, c)


def test_sentence_transformer_backend_encode_batches():
    """超过 batch_size=32 的批量编码正常工作"""
    backend = get_backend()
    if not isinstance(backend, SentenceTransformerBackend):
        pytest.skip("当前后端不是 sentence-transformers")
    texts = [f"测试文本 {i}" for i in range(40)]
    result = backend.encode(texts)
    assert len(result) == 40


def test_ollama_backend_interface():
    """OllamaBackend 接口契约（不实际调用服务）"""
    backend = OllamaBackend()
    assert backend.encode([]) == []
    assert backend.load().is_loaded
