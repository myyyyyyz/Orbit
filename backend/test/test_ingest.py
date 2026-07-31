"""ingest/ — 文件解析模块测试"""
import os
import pytest

from app.ingest import (
    get_file_type, parse_markdown, parse_text, parse_pdf,
    parse_file, SUPPORTED_TYPES, PARSERS,
)


def test_supported_types():
    assert SUPPORTED_TYPES == {".pdf": "pdf", ".md": "markdown", ".txt": "text", ".markdown": "markdown"}


def test_get_file_type():
    assert get_file_type("doc.pdf") == "pdf"
    assert get_file_type("README.MD") == "markdown"   # 大小写不敏感
    assert get_file_type("notes.markdown") == "markdown"
    assert get_file_type("a.txt") == "text"
    assert get_file_type("archive.zip") is None
    assert get_file_type("noext") is None


def test_parsers_mapping_covers_supported_types():
    assert set(PARSERS.keys()) == set(SUPPORTED_TYPES.values())


def test_parse_markdown(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("# 标题\n\n正文内容", encoding="utf-8")
    assert parse_markdown(str(f)) == "# 标题\n\n正文内容"


def test_parse_text(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("纯文本内容", encoding="utf-8")
    assert parse_text(str(f)) == "纯文本内容"


def test_parse_pdf(monkeypatch, tmp_path):
    """mock PdfReader 验证多页拼接逻辑"""
    class FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakeReader:
        def __init__(self, filepath):
            self.pages = [FakePage("第一页"), FakePage(""), FakePage("第二页")]

    monkeypatch.setattr("PyPDF2.PdfReader", FakeReader)
    result = parse_pdf(str(tmp_path / "fake.pdf"))
    assert result == "第一页\n\n第二页"  # 空页被跳过，双换行拼接


def test_parse_file_markdown(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Hello", encoding="utf-8")
    text, file_type = parse_file(str(f))
    assert text == "# Hello"
    assert file_type == "markdown"


def test_parse_file_unsupported_raises(tmp_path):
    f = tmp_path / "doc.xyz"
    f.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        parse_file(str(f))
