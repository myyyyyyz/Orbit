"""文本切割模块"""

import re
from ..config import settings


def chunk_text(text: str, metadata: dict = None) -> list[dict]:
    """
    将文本按语义段落切割为 chunks。
    优先按段落（空行）切割，超长段落再按句分割。
    """
    if not text or not text.strip():
        return []

    chunk_size = settings.CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP

    # Step 1: 按空行分段落
    paragraphs = re.split(r'\n\s*\n', text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            chunks.append(para)
        else:
            # 超长段落：按句号、换行再切
            sub_chunks = _split_long_text(para, chunk_size, overlap)
            chunks.extend(sub_chunks)

    # 构建带元数据的 chunk 列表
    result = []
    for i, chunk_text in enumerate(chunks):
        chunk_meta = {
            "chunk_index": i,
            "chunk_count": len(chunks),
            "char_count": len(chunk_text),
        }
        if metadata:
            chunk_meta.update(metadata)
        result.append({"text": chunk_text, "metadata": chunk_meta})

    return result


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """将超长文本按句分割，带重叠"""
    # 按句子分割
    sentences = re.split(r'(?<=[。！？.!?\n])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) <= chunk_size:
            current += sent
        else:
            if current:
                chunks.append(current.strip())
            # 重叠：保留上一段末尾作为上下文
            if chunks and overlap > 0:
                current = current[-overlap:] + sent if len(current) >= overlap else sent
            else:
                current = sent

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text[:chunk_size]]
