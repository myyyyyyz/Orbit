"""pdf_vision_v1 策略 + vision_utils 的单元测试与集成测试。

依赖（PyMuPDF / Pillow / reportlab）在 requirements.txt 中声明；无 LLM key
或 tesseract 时图片块会落到 unavailable 路由而非报错，本测试据此断言。
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw

from app.knowledge_agent.executors import vision_utils
from app.knowledge_agent.executors.pdf_vision import PdfVisionExecutor
from app.knowledge_agent.models import CorpusProfile


def _profile() -> CorpusProfile:
    return CorpusProfile(
        source_path="sample.pdf",
        source_hash="a" * 64,
        file_type="pdf",
        page_count=1,
        text_extraction_ratio=0.9,
        image_count=1,
    )


# ---------- vision_utils 复杂度分析 ----------

def _png_bytes(make_fn) -> bytes:
    img = Image.new("RGB", (400, 300), "white")
    make_fn(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_colorful_image_is_complex():
    def noisy(img):
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    metrics = vision_utils.analyze_image_complexity(_png_bytes(noisy))
    assert metrics["is_complex"] is True
    assert metrics["color_complexity"] > 0.5


def test_plain_white_image_is_simple():
    metrics = vision_utils.analyze_image_complexity(_png_bytes(lambda img: None))
    assert metrics["is_complex"] is False
    assert metrics["color_complexity"] == 0.0


def test_diagram_with_lines_is_complex():
    def grid(img):
        draw = ImageDraw.Draw(img)
        for i in range(0, 400, 20):
            draw.line([(i, 0), (i, 300)], fill="black", width=2)
        for j in range(0, 300, 20):
            draw.line([(0, j), (400, j)], fill="black", width=2)

    metrics = vision_utils.analyze_image_complexity(_png_bytes(grid))
    assert metrics["is_complex"] is True


# ---------- pdf_vision_v1 executor ----------

def _make_pdf_with_heading_and_image(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate

    # 构造一张"彩色噪点图"作为内嵌图（复杂度高 → vision 路由）
    noise = Image.new("RGB", (300, 200))
    px = noise.load()
    for y in range(noise.height):
        for x in range(noise.width):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img_buf = io.BytesIO()
    noise.save(img_buf, format="PNG")

    # 用 ASCII 标题/正文，避免 reportlab 默认字体无法嵌入中文导致提取乱码
    styles = getSampleStyleSheet()
    heading = ParagraphStyle("Heading", parent=styles["Heading1"], fontSize=18)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build(
        [
            Paragraph("Chapter 1 System Overview", heading),
            Paragraph(
                "This system ingests knowledge bases. The following paragraph is sample "
                "body text used to verify that PDF text is split into chunks with a "
                "hierarchical heading path after vision-aware sectioning.",
                body,
            ),
            RLImage(io.BytesIO(img_buf.getvalue()), width=240, height=160),
        ]
    )


def test_pdf_vision_executor_splits_headings_and_extracts_image(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf_with_heading_and_image(pdf_path)

    chunks = PdfVisionExecutor().execute(pdf_path, profile=_profile(), run_id="r1")

    # 至少应有标题章节切片 + 一个图片切片
    section_chunks = [c for c in chunks if c.metadata.get("block_type") == "section"]
    image_chunks = [c for c in chunks if c.metadata.get("block_type") == "image"]
    assert section_chunks, "应当产出按标题分章的文本切片"
    assert image_chunks, "应当产出图片切片"

    # 标题章节带有层级路径（含 "Chapter 1 System Overview"）
    assert any("Chapter 1 System Overview" in c.heading_path for c in section_chunks)

    # 图片切片路由落在一个合法值，且不因无 OCR/LLM 而崩溃
    assert image_chunks[0].metadata["image_route"] in {"ocr", "vision", "unavailable"}
    assert image_chunks[0].page == 1


def test_pdf_vision_executor_falls_back_without_pymupdf(tmp_path, monkeypatch):
    # 模拟 PyMuPDF 不可用 → 应回退到纯 PyPDF2 文本切分而非抛错
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fitz" or name.startswith("fitz."):
            raise ImportError("fitz disabled in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    pdf_path = tmp_path / "sample.pdf"
    _make_pdf_with_heading_and_image(pdf_path)

    chunks = PdfVisionExecutor().execute(pdf_path, profile=_profile(), run_id="r2")
    assert chunks, "无 PyMuPDF 时仍应产出纯文本切片"
    assert all(c.metadata.get("fallback") == "no_pymupdf" for c in chunks)
