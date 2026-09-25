"""PDF 摄取策略 pdf_vision_v1：

页内图片检测 → 复杂度分流 → 简单图 OCR / 复杂图视觉 LLM →
文本按标题分章 + 长段重叠切块。

依赖 PyMuPDF（fitz）做页面渲染/内嵌图提取/按字号识别标题；缺失时自动
回退到纯 PyPDF2 文本切块，保证摄取链路不硬挂。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.chunk import chunk_text
from app.knowledge_agent.executors import vision_utils
from app.knowledge_agent.executors.base import ChunkDraft, ExecutionBlocked, build_chunks
from app.knowledge_agent.models import CorpusProfile, KnowledgeChunk

logger = logging.getLogger(__name__)

_PLAIN_HEADING_RATIO = 1.15  # 字号 ≥ 正文中位数 * 该比例 视为标题
_MAX_HEADING_LEN = 80  # 超过该长度的块不当作标题（避免整段被误判）
_HEADING_STACK_DEPTH = 4  # 面包屑最多保留的层级数


class PdfVisionExecutor:
    strategy_id = "pdf_vision_v1"

    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        try:
            import fitz  # PyMuPDF
        except Exception as exc:  # noqa: BLE001
            logger.debug("PyMuPDF unavailable, fallback to plain text: %s", exc)
            return self._execute_plain(source, profile=profile, run_id=run_id)

        doc = fitz.open(source)
        try:
            return self._execute_doc(doc, profile=profile, run_id=run_id)
        finally:
            doc.close()

    # ---- 主路径：PyMuPDF ----
    def _execute_doc(
        self, doc, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        body_size = self._body_font_size(doc)

        drafts: list[ChunkDraft] = []
        headings: list[str] = []
        section_path: tuple[str, ...] = ()
        section_lines: list[str] = []

        def flush_section() -> None:
            section = "\n".join(section_lines).strip()
            if not section:
                return
            label = "/".join(section_path) or "root"
            for part_index, part in enumerate(chunk_text(section)):
                drafts.append(
                    ChunkDraft(
                        text=part["text"],
                        locator=f"heading:{label}:part:{part_index}",
                        heading_path=section_path,
                        metadata={"block_type": "section", "extraction_method": "pdf_text"},
                    )
                )

        for page_number, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            images = page.get_images(full=True)
            image_dominated = bool(images) and len(text) < vision_utils.IMAGE_TEXT_THRESHOLD

            # 1) 页内图片检测 → 复杂度分流 → OCR / 视觉 LLM
            if images:
                for img_idx, img in enumerate(images):
                    chunk = self._build_image_chunk(doc, page_number, img[0], img_idx)
                    if chunk is not None:
                        drafts.append(chunk)

            # 2) 文本按标题分章（整页是图的页面跳过纯文本，避免与图片提取重复）
            if text and not image_dominated:
                for block in page.get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    spans = [
                        s
                        for line in block.get("lines", [])
                        for s in line.get("spans", [])
                        if s.get("text", "").strip()
                    ]
                    if not spans:
                        continue
                    block_text = " ".join(s.get("text", "").strip() for s in spans).strip()
                    if not block_text:
                        continue
                    max_size = max((s.get("size", 0) or 0) for s in spans)
                    is_bold = any(s.get("flags", 0) & 2 for s in spans)
                    is_heading = (
                        body_size > 0
                        and (max_size >= body_size * _PLAIN_HEADING_RATIO or is_bold)
                        and len(block_text) <= _MAX_HEADING_LEN
                        and not block_text.endswith(("。", ".", "；", ";", "：", ":"))
                    )
                    if is_heading:
                        flush_section()
                        headings.append(block_text)
                        section_path = tuple(headings[-_HEADING_STACK_DEPTH:])
                        section_lines = [block_text]
                    else:
                        section_lines.append(block_text)

        flush_section()
        chunks = build_chunks(drafts, profile=profile, run_id=run_id, strategy_id=self.strategy_id)
        if not chunks:
            raise ExecutionBlocked("pdf_vision_empty")
        return chunks

    def _build_image_chunk(self, doc, page_number: int, xref: int, img_idx: int):
        try:
            img_bytes = doc.extract_image(xref).get("image")
        except Exception as exc:  # noqa: BLE001
            logger.debug("extract_image failed xref=%s: %s", xref, exc)
            return None
        if not img_bytes:
            return None

        metrics = vision_utils.analyze_image_complexity(img_bytes)
        if metrics.get("is_complex"):
            content = vision_utils.vision_describe(img_bytes)
            route = "vision"
        else:
            content = vision_utils.ocr_image(img_bytes)
            route = "ocr"

        # 简单图 OCR 失败再退视觉 LLM；视觉也失败则记录占位，不丢弃页面
        if not content:
            if route == "ocr":
                content = vision_utils.vision_describe(img_bytes) or ""
                route = "vision" if content else "ocr"
            if not content:
                content = "[图片内容未能提取：OCR 与视觉 LLM 均不可用]"
                route = "unavailable"

        if not content.strip():
            return None

        return ChunkDraft(
            text=content.strip(),
            locator=f"page:{page_number}:image:{img_idx}",
            page=page_number,
            metadata={
                "block_type": "image",
                "image_route": route,
                "extraction_method": route,
                **{f"img_{k}": v for k, v in metrics.items() if k != "error"},
            },
        )

    @staticmethod
    def _body_font_size(doc) -> float:
        sizes: list[float] = []
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            sizes.append(span.get("size", 0) or 0)
        if not sizes:
            return 0.0
        median = sorted(sizes)[len(sizes) // 2]
        return float(median)

    # ---- 回退路径：无 PyMuPDF 时纯文本切分（无图片/标题识别）----
    def _execute_plain(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        from PyPDF2 import PdfReader

        drafts: list[ChunkDraft] = []
        for page_number, page in enumerate(PdfReader(str(source)).pages, start=1):
            text = page.extract_text() or ""
            for part_index, part in enumerate(chunk_text(text)):
                drafts.append(
                    ChunkDraft(
                        text=part["text"],
                        locator=f"page:{page_number}:part:{part_index}",
                        page=page_number,
                        metadata={"extraction_method": "pdf_text", "fallback": "no_pymupdf"},
                    )
                )
        chunks = build_chunks(drafts, profile=profile, run_id=run_id, strategy_id=self.strategy_id)
        if not chunks:
            raise ExecutionBlocked("pdf_vision_empty")
        return chunks
