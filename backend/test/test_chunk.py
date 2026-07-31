"""chunk/ — 文本切割模块测试"""
from app.chunk import chunk_text, _split_long_text
from app.config import settings


def test_empty_text_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text(None) == []


def test_short_text_single_chunk():
    result = chunk_text("这是一段短文本。")
    assert len(result) == 1
    assert result[0]["text"] == "这是一段短文本。"
    assert result[0]["metadata"]["chunk_index"] == 0
    assert result[0]["metadata"]["chunk_count"] == 1
    assert result[0]["metadata"]["char_count"] == len("这是一段短文本。")


def test_paragraph_split_by_blank_lines():
    text = "第一段内容。\n\n第二段内容。\n\n\n第三段内容。"
    result = chunk_text(text)
    assert len(result) == 3
    assert result[0]["text"] == "第一段内容。"
    assert result[1]["text"] == "第二段内容。"
    assert result[2]["text"] == "第三段内容。"
    # chunk_index 连续递增
    assert [c["metadata"]["chunk_index"] for c in result] == [0, 1, 2]


def test_metadata_merged():
    result = chunk_text("内容", metadata={"source": "test.md", "file_type": "markdown"})
    assert result[0]["metadata"]["source"] == "test.md"
    assert result[0]["metadata"]["file_type"] == "markdown"
    # 内置字段仍保留
    assert "chunk_index" in result[0]["metadata"]


def test_long_paragraph_split_with_overlap():
    """超长段落按句切割，相邻 chunk 存在 overlap"""
    size = settings.CHUNK_SIZE
    # 构造远超 chunk_size 的单段落（无空行），多句
    sentence = "这是一个用于测试切割逻辑的句子。"
    text = sentence * (size // len(sentence) * 3)
    result = chunk_text(text)
    assert len(result) >= 2
    for c in result:
        # 每个 chunk 不超过 size + overlap 的余量（句级切割不会精确等于 size）
        assert len(c["text"]) <= size + settings.CHUNK_OVERLAP + len(sentence)


def test_split_long_text_basic():
    chunks = _split_long_text("甲。乙。丙。丁。", chunk_size=4, overlap=0)
    assert len(chunks) >= 2
    assert "".join(chunks).replace(" ", "") != ""


def test_split_long_text_overlap_carries_context():
    text = "AAAA。BBBB。CCCC。DDDD。"
    chunks = _split_long_text(text, chunk_size=10, overlap=5)
    assert len(chunks) >= 2
    # 后续 chunk 开头包含上一 chunk 的尾部（overlap）
    assert chunks[1][:1] in chunks[0] or chunks[1][:2] in chunks[0]


def test_split_long_text_no_sentence_delimiters():
    """无句读符的极长文本兜底截断"""
    text = "x" * 3000
    chunks = _split_long_text(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 1
    assert chunks[0]


def test_chunk_size_boundary():
    """恰好等于 chunk_size 的段落不切割"""
    text = "a" * settings.CHUNK_SIZE
    result = chunk_text(text)
    assert len(result) == 1
