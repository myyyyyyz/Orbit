"""embed/ — Embedding 模块测试（真实 ONNX 模型，模块级只加载一次）

模型来自 chromadb 自带的 ONNX 包（all-MiniLM-L6-v2, 384 维），首次运行会下载
约 80MB 到 EMBED_CACHE_DIR。CI 若无法访问该下载源，会表现为测试失败而非跳过——
这是刻意的：embedding 不可用时整个 RAG 检索链路都是坏的，不该被静默放过。
"""
import pytest

from app.embed import EMBED_DIM, OnnxBackend, encode, get_backend


@pytest.fixture(scope="module", autouse=True)
def _load_model_once():
    """模块级预热，避免每个测试重复触发加载逻辑"""
    get_backend()


def test_backend_is_onnx_singleton():
    b1 = get_backend()
    b2 = get_backend()
    assert b1 is b2
    assert b1.is_loaded
    assert isinstance(b1, OnnxBackend)


def test_encode_empty_list():
    assert encode([]) == []


def test_encode_single_text():
    result = encode(["知识库问答系统"])
    assert len(result) == 1
    assert len(result[0]) == EMBED_DIM == 384
    assert all(isinstance(x, float) for x in result[0])


def test_encode_batch():
    result = encode(["文本一", "文本二", "文本三"])
    assert len(result) == 3
    # 不同文本向量不同
    assert result[0] != result[1]


def test_encode_normalized():
    """ONNX 后端内部做 L2 归一化 → 向量模长为 1（cosine 检索的前提）"""
    vec = encode(["归一化测试"])[0]
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_encode_semantic_similarity():
    """语义相近的文本 cosine 相似度应高于无关文本"""
    a, b, c = encode(["如何重置密码", "忘记密码怎么办", "今天天气真好"])

    def cosine(x, y):
        return sum(p * q for p, q in zip(x, y))  # 已归一化，点积即 cosine

    assert cosine(a, b) > cosine(a, c)


def test_encode_exceeds_internal_batch_size():
    """超过内部 batch_size=32 的批量编码正常工作"""
    texts = [f"测试文本 {i}" for i in range(40)]
    result = encode(texts)
    assert len(result) == 40
    assert all(len(v) == EMBED_DIM for v in result)


def test_cache_dir_is_under_data_dir():
    """模型缓存必须落在数据卷内，否则每次重建镜像都要重新下载 80MB"""
    from app.config import DATA_DIR, settings

    assert settings.EMBED_CACHE_DIR.startswith(DATA_DIR)
