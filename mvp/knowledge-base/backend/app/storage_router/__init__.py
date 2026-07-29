"""
混合存储路由模块

根据文档类型自动选择最佳存储策略：
- 原样存储：合同、发票、合规文件（需原文溯源）
- RAG 向量化：手册、FAQ、文档（需语义检索）
- 结构化提取：表格、表单、数据（需字段查询）
- 知识图谱：关系型数据（人员、项目依赖）

Knowledge Agent 参照 rag-optimization-guide.md 做最终决策。
"""

import os
from typing import Optional


# ── 存储策略定义 ──────────────────────────────────

STORAGE_STRATEGIES = {
    "rag": {
        "desc": "RAG 向量化存储",
        "suitable": ["产品手册", "FAQ", "技术文档", "会议纪要", "Markdown", "教程"],
        "not_suitable": ["合同", "发票", "表格数据"],
    },
    "original": {
        "desc": "原样存储 + 全文索引",
        "suitable": ["合同", "发票", "合规文件", "法律文书", "证书", "报告"],
        "not_suitable": ["FAQ", "短文本"],
    },
    "structured": {
        "desc": "结构化提取到 SQLite",
        "suitable": ["Excel", "CSV", "表格", "表单", "数据库导出", "价格表"],
        "not_suitable": ["长文本", "合同"],
    },
    "graph": {
        "desc": "知识图谱（Neo4j/JSON Graph）",
        "suitable": ["组织架构", "项目依赖", "供应商关系", "人员关系"],
        "not_suitable": ["纯文本", "表格"],
    },
}


# ── 文件类型 → 存储策略映射 ──────────────────────

FILE_TYPE_ROUTING = {
    # 文档类 → RAG
    ".md": "rag",
    ".markdown": "rag",
    ".txt": "rag",
    ".pdf": "rag",  # PDF 默认 RAG，但如果是合同/发票则 original

    # 表格类 → 结构化
    ".xlsx": "structured",
    ".xls": "structured",
    ".csv": "structured",
    ".tsv": "structured",

    # 图片类 → 多模态（OCR + RAG）
    ".jpg": "multimodal",
    ".jpeg": "multimodal",
    ".png": "multimodal",
    ".gif": "multimodal",
    ".webp": "multimodal",

    # 代码类 → RAG
    ".py": "rag",
    ".js": "rag",
    ".ts": "rag",
    ".java": "rag",
    ".go": "rag",

    # 数据类 → 结构化
    ".json": "structured",
    ".xml": "structured",
}


# ── 内容特征 → 策略调整 ──────────────────────────

CONTRACT_KEYWORDS = ["合同", "协议", "甲方", "乙方", "合同编号", "签署", "盖章", "invoice", "发票", "收据"]
TABLE_INDICATORS = ["sheet", "table", "row", "column", "单元格", "行", "列"]
RELATIONSHIP_INDICATORS = ["上级", "下级", "依赖", "关联", "负责人", "汇报", "parent", "child", "depends"]


def detect_content_type(text: str, filename: str = "") -> str:
    """
    分析内容特征，判断文档类型。
    返回: "contract" | "table" | "relationship" | "document" | "code" | "image"
    """
    if not text:
        text = ""

    text_lower = text.lower()

    # 合同/法律文件
    contract_score = sum(1 for kw in CONTRACT_KEYWORDS if kw in text_lower)
    if contract_score >= 2:
        return "contract"

    # 关系型数据
    relation_score = sum(1 for kw in RELATIONSHIP_INDICATORS if kw in text_lower)
    if relation_score >= 3:
        return "relationship"

    # 表格数据
    table_score = sum(1 for kw in TABLE_INDICATORS if kw in text_lower)
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".xlsx", ".xls", ".csv", ".tsv") or table_score >= 2:
        return "table"

    # 代码
    code_extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c"}
    if ext in code_extensions:
        return "code"

    # 图片
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    if ext in image_extensions:
        return "image"

    # 默认：普通文档
    return "document"


def route_storage(filename: str, text: str = "", file_size: int = 0) -> dict:
    """
    混合存储路由：根据文件类型 + 内容特征选择最佳存储策略。

    返回:
    {
        "strategy": "rag" | "original" | "structured" | "graph" | "multimodal",
        "reason": str,
        "content_type": str,
        "actions": list[str],   # 需要执行的操作步骤
    }
    """
    content_type = detect_content_type(text, filename)
    ext = os.path.splitext(filename)[1].lower()

    # ── 策略决策 ──
    if content_type == "contract":
        strategy = "original"
        reason = "合同/法律文件，需原文溯源，原样存储 + 全文索引"
        actions = ["保存原始文件", "建立全文索引", "不做切割"]
    elif content_type == "table":
        strategy = "structured"
        reason = "表格数据，结构化提取到 SQLite，支持字段查询"
        actions = ["解析表格结构", "提取字段到 SQLite", "保留原始文件备份"]
    elif content_type == "relationship":
        strategy = "graph"
        reason = "关系型数据，适合知识图谱存储"
        actions = ["提取实体和关系", "构建图谱节点和边", "保留原文备份"]
    elif content_type == "image":
        strategy = "multimodal"
        reason = "图片文件，OCR 提取文字后走 RAG"
        actions = ["OCR 提取文字", "文字走 RAG 向量化", "保留原图"]
    elif content_type == "code":
        strategy = "rag"
        reason = "代码文件，按函数/类切割后 RAG"
        actions = ["按代码结构切割", "RAG 向量化", "保留源文件"]
    else:
        # 普通文档 → RAG
        strategy = "rag"
        reason = "普通文档，语义切割后 RAG 向量化"
        actions = ["语义切割", "RAG 向量化", "保留原文"]

    return {
        "strategy": strategy,
        "reason": reason,
        "content_type": content_type,
        "actions": actions,
        "file_extension": ext,
        "file_size": file_size,
    }


def get_strategy_info() -> dict:
    """获取所有存储策略信息"""
    return {
        "strategies": STORAGE_STRATEGIES,
        "file_routing": FILE_TYPE_ROUTING,
        "total_strategies": len(STORAGE_STRATEGIES) + 1,  # +1 for multimodal
    }
