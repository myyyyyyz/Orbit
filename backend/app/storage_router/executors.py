"""存储策略执行：original / structured / rag / multimodal / graph"""

import os
from datetime import datetime


def execute_strategy(route_result: dict, filepath: str, text: str = "", scope=None) -> dict:
    """
    根据路由结果执行实际操作。

    Args:
        route_result: route_storage() 的返回值
        filepath: 已保存的临时文件路径
        text: 已提取的文本内容（可选）
        scope: TenantScope；决定向量化结果落哪个知识库（不传取请求级上下文）

    Returns:
        {"status": "ok", "details": {...}} 或 {"status": "error", "message": ...}
    """
    strategy = route_result["strategy"]
    filename = os.path.basename(filepath)
    results = {"strategy": strategy, "actions_performed": []}

    try:
        if strategy == "original":
            # 原样保存 + 全文索引
            results.update(_execute_original(filepath, filename, scope))
            results["actions_performed"].append("fulltext_index")

        elif strategy == "structured":
            # 结构化提取到 SQLite
            results.update(_execute_structured(filepath, filename))
            results["actions_performed"].append("structured_import")

        elif strategy == "rag":
            # 向量化入库（已有文本时直接入库）
            if text:
                results.update(_execute_rag(filepath, filename, text, scope))
            else:
                results.update({"status": "skipped", "message": "无文本内容，跳过 RAG 索引"})
            results["actions_performed"].append("rag_index")

        elif strategy == "multimodal":
            # OCR + RAG
            results.update(_execute_multimodal(filepath, filename, text, scope))
            results["actions_performed"].append("ocr_extraction")

        elif strategy == "graph":
            # 知识图谱
            results.update(_execute_graph(filepath, filename, text, scope))
            results["actions_performed"].append("graph_build")

        else:
            results.update({"status": "error", "message": f"未知策略: {strategy}"})

    except Exception as e:
        results["status"] = "error"
        results["message"] = str(e)

    return results


def _execute_original(filepath: str, filename: str, scope=None) -> dict:
    """原样保存 + 全文索引（简单版：写入 ChromaDB 整篇不切割）"""
    from ..store import add_documents

    # 读取文件全文
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        full_text = f.read()

    # 作为单个 chunk 入库
    add_documents([{"text": full_text, "metadata": {
        "source": filename,
        "storage": "original",
        "filepath": filepath,
    }}], scope)

    return {
        "status": "ok",
        "message": f"原样保存 {filename}，已建立全文索引",
        "chars": len(full_text),
    }


def _execute_structured(filepath: str, filename: str) -> dict:
    """结构化提取：Excel/CSV → SQLite"""
    import sqlite3

    ext = os.path.splitext(filename)[1].lower()
    db_path = os.path.join(os.path.dirname(filepath), "..", "structured_data.db")

    if ext in (".csv", ".tsv"):
        # CSV 解析
        import csv
        delimiter = "\t" if ext == ".tsv" else ","
        conn = sqlite3.connect(db_path)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader, None)
            if not headers:
                return {"status": "error", "message": "CSV 文件无表头"}

            table_name = _safe_table_name(filename)
            conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
            cols = ", ".join(f'"{h}" TEXT' for h in headers)
            conn.execute(f"CREATE TABLE [{table_name}] ({cols})")

            placeholders = ", ".join("?" * len(headers))
            rows = [tuple(row[:len(headers)]) for row in reader if any(row)]
            conn.executemany(f"INSERT INTO [{table_name}] VALUES ({placeholders})", rows)
            conn.commit()
            conn.close()
            return {"status": "ok", "message": f"CSV → SQLite 表 [{table_name}]", "rows": len(rows)}

    elif ext in (".xlsx", ".xls"):
        # Excel 解析
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            tables = {}
            conn = sqlite3.connect(db_path)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                headers = [str(h) if h else f"col_{i}" for i, h in enumerate(rows[0])]
                table_name = _safe_table_name(f"{filename}_{sheet_name}")
                conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
                cols = ", ".join(f'"{h}" TEXT' for h in headers)
                conn.execute(f"CREATE TABLE [{table_name}] ({cols})")
                data_rows = [tuple(r[:len(headers)]) for r in rows[1:] if any(v for v in r if v is not None)]
                placeholders = ", ".join("?" * len(headers))
                conn.executemany(f"INSERT INTO [{table_name}] VALUES ({placeholders})", data_rows)
                tables[sheet_name] = len(data_rows)
            conn.commit()
            conn.close()
            wb.close()
            return {"status": "ok", "message": f"Excel → SQLite", "sheets": tables}
        except ImportError:
            return {"status": "error", "message": "缺少 openpyxl 库，无法解析 Excel"}
    else:
        return {"status": "error", "message": f"不支持的结构化文件类型: {ext}"}


def _execute_rag(filepath: str, filename: str, text: str, scope=None) -> dict:
    """文本走 RAG 向量化"""
    from ..chunk import chunk_text
    from ..store import add_documents

    chunks = chunk_text(text, metadata={
        "source": filename,
        "storage": "rag",
        "filepath": filepath,
    })
    if chunks:
        count = add_documents(chunks, scope)
        return {"status": "ok", "message": f"RAG 索引完成", "chunks": count}
    return {"status": "error", "message": "文本切割失败"}


def _execute_multimodal(filepath: str, filename: str, text: str = "", scope=None) -> dict:
    """多模态：OCR 提取文字 + RAG"""
    ocr_text = ""

    # 尝试 OCR（如果安装了 PIL + pytesseract）
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        try:
            from PIL import Image
            img = Image.open(filepath)
            try:
                import pytesseract
                ocr_text = pytesseract.image_to_string(img)
            except ImportError:
                ocr_text = f"[图片文件: {filename}，OCR 库未安装，仅保留元数据]"
            img.close()
        except ImportError:
            ocr_text = f"[图片文件: {filename}]"

    # 即使没 OCR，也将图片元数据入库
    if not ocr_text.strip():
        ocr_text = text or f"[图片文件: {filename}]"

    return _execute_rag(filepath, filename, ocr_text, scope)


def _execute_graph(filepath: str, filename: str, text: str = "", scope=None) -> dict:
    """知识图谱：简单版 JSON 保存"""
    import json as json_module
    graph_dir = os.path.join(os.path.dirname(filepath), "..", "graph_data")
    os.makedirs(graph_dir, exist_ok=True)

    graph_file = os.path.join(graph_dir, f"{os.path.splitext(filename)[0]}.json")
    data = {
        "source": filename,
        "text": text[:5000],
        "entities": [],  # 后续由 Knowledge Agent 提取
        "relations": [],
        "created_at": datetime.now().isoformat(),
    }
    with open(graph_file, "w", encoding="utf-8") as f:
        json_module.dump(data, f, ensure_ascii=False, indent=2)

    # 同时做 RAG 方便搜索
    return _execute_rag(filepath, filename, text, scope)


def _safe_table_name(filename: str) -> str:
    """安全表名：仅保留字母数字下划线"""
    import re
    name = os.path.splitext(os.path.basename(filename))[0]
    name = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', name)
    return f"data_{name[:50]}"
