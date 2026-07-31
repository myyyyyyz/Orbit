"""文件解析模块：支持 PDF、Markdown、TXT"""

import os
from typing import Optional


SUPPORTED_TYPES = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".txt": "text",
    ".markdown": "markdown",
}


def get_file_type(filename: str) -> Optional[str]:
    ext = os.path.splitext(filename)[1].lower()
    return SUPPORTED_TYPES.get(ext)


def parse_pdf(filepath: str) -> str:
    """解析 PDF 文件，提取纯文本"""
    from PyPDF2 import PdfReader
    reader = PdfReader(filepath)
    texts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def parse_markdown(filepath: str) -> str:
    """读取 Markdown 文件，保留原始格式"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def parse_text(filepath: str) -> str:
    """读取纯文本文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


PARSERS = {
    "pdf": parse_pdf,
    "markdown": parse_markdown,
    "text": parse_text,
}


def parse_file(filepath: str) -> tuple[str, str]:
    """
    解析文件，返回 (文本内容, 文件类型)
    """
    file_type = get_file_type(filepath)
    if not file_type:
        raise ValueError(f"不支持的文件类型: {os.path.splitext(filepath)[1]}")

    parser = PARSERS[file_type]
    text = parser(filepath)
    return text, file_type
