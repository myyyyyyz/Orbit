"""PDF 内嵌图片的复杂度分析与 OCR / 视觉 LLM 提取工具。

所有第三方依赖（Pillow / pytesseract / urllib）均延迟导入，缺依赖时
优雅降级，不阻塞整个摄取链路。视觉 LLM 复用用户配置的 LLM_API_KEY /
LLM_BASE_URL / LLM_MODEL_VISION（OpenAI 兼容 /chat/completions，支持 image_url）。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ---- 可调阈值（可用 env 覆盖）----
IMAGE_TEXT_THRESHOLD = int(os.getenv("PDF_IMAGE_TEXT_THRESHOLD", "50"))
COMPLEX_COLOR_THRESHOLD = float(os.getenv("PDF_COMPLEX_COLOR_THRESHOLD", "0.55"))
COMPLEX_EDGE_THRESHOLD = float(os.getenv("PDF_COMPLEX_EDGE_THRESHOLD", "0.15"))
COMPLEX_LINE_THRESHOLD = float(os.getenv("PDF_COMPLEX_LINE_THRESHOLD", "0.12"))
_ANALYSIS_MAX_SIZE = 512  # 复杂度分析前最长边缩放，控制开销


def _pil_from_bytes(image_bytes: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(image_bytes))


def _downscale(img, max_size: int = _ANALYSIS_MAX_SIZE):
    if max(img.size) <= max_size:
        return img
    ratio = max_size / max(img.size)
    return img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)))


def analyze_image_complexity(image_bytes: bytes) -> dict:
    """分析图片复杂度，返回 {color_complexity, edge_density, line_density, is_complex[, error]}。

    - color_complexity: 量化颜色分布的归一化香农熵（0~1），高=照片/富图
    - edge_density: 梯度大于阈值的像素占比，高=细节多
    - line_density: 通过行/列边缘像素投影估计的直线密度，高=图表/表格/线框
    - is_complex: 颜色复杂 或 线密度高 → 走视觉 LLM；否则走 OCR
    """

    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        return {
            "color_complexity": 0.0,
            "edge_density": 0.0,
            "line_density": 0.0,
            "is_complex": False,
            "error": "pillow_unavailable",
        }

    try:
        img = _downscale(_pil_from_bytes(image_bytes).convert("RGB"))
    except Exception as exc:  # noqa: BLE001
        return {
            "color_complexity": 0.0,
            "edge_density": 0.0,
            "line_density": 0.0,
            "is_complex": False,
            "error": f"decode_error:{exc}",
        }

    w, h = img.size
    px = list(img.getdata())

    # 颜色复杂度：量化到 5bit/通道后统计唯一色，算归一化熵
    quant: dict[int, int] = {}
    for r, g, b in px:
        key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        quant[key] = quant.get(key, 0) + 1
    total = len(px)
    ent = 0.0
    for c in quant.values():
        p = c / total
        ent -= p * math.log2(p)
    max_ent = math.log2(len(quant)) if len(quant) > 1 else 1.0
    color_complexity = ent / max_ent if max_ent > 0 else 0.0

    # 边缘密度：水平+垂直一阶梯度的绝对值超过阈值比例
    gray = [(r * 299 + g * 587 + b * 114) // 1000 for (r, g, b) in px]
    gw = [gray[i * w + (j + 1)] - gray[i * w + j] for i in range(h) for j in range(w - 1)]
    gv = [gray[(i + 1) * w + j] - gray[i * w + j] for i in range(h - 1) for j in range(w)]
    edge_thresh = 40
    edge_h = sum(1 for d in gw if abs(d) > edge_thresh)
    edge_v = sum(1 for d in gv if abs(d) > edge_thresh)
    edge_density = (edge_h + edge_v) / (len(gw) + len(gv)) if (len(gw) + len(gv)) else 0.0

    # 线密度：行/列边缘像素投影，超过均值 3 倍且占该行/列一定比例算一条线
    row_edge = [sum(1 for j in range(w - 1) if abs(gw[i * (w - 1) + j]) > edge_thresh) for i in range(h)]
    col_edge = [sum(1 for i in range(h - 1) if abs(gv[i * w + j]) > edge_thresh) for j in range(w)]
    mean_row = sum(row_edge) / h if h else 0
    mean_col = sum(col_edge) / w if w else 0
    line_rows = sum(1 for v in row_edge if v > 3 * mean_row and v > 0.25 * w)
    line_cols = sum(1 for v in col_edge if v > 3 * mean_col and v > 0.25 * h)
    line_density = (line_rows + line_cols) / (h + w) if (h + w) else 0.0

    is_complex = (color_complexity >= COMPLEX_COLOR_THRESHOLD) or (edge_density >= COMPLEX_EDGE_THRESHOLD)
    return {
        "color_complexity": round(color_complexity, 3),
        "edge_density": round(edge_density, 4),
        "line_density": round(line_density, 3),
        "is_complex": bool(is_complex),
    }


def ocr_image(image_bytes: bytes) -> str:
    """简单图片走 OCR（pytesseract）。依赖或二进制缺失时返回空串。"""

    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:  # noqa: BLE001
        logger.debug("OCR unavailable: %s", exc)
        return ""

    try:
        img = _pil_from_bytes(image_bytes)
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("OCR failed: %s", exc)
        return ""


def vision_describe(image_bytes: bytes, prompt: Optional[str] = None) -> Optional[str]:
    """复杂图片调视觉 LLM（OpenAI 兼容接口，使用用户配置的 apikey）。

    无 apikey / 调用失败 → 返回 None（调用方据此降级）。
    """

    api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        return None
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("LLM_MODEL_VISION") or os.getenv("LLM_MODEL_FAST", "gpt-4o-mini")
    prompt = prompt or (
        "请详细描述这张图片的内容，并尽可能完整地提取其中的全部文字"
        "（保留原有结构与排版）。如果图片是图表/流程图/截图，请说明其含义。"
        "只输出内容本身，不要多余解释。"
    )

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": 1500,
            "temperature": 0,
        }
    ).encode()

    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("vision LLM failed: %s", exc)
        return None
