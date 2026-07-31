"""storage_router/ — 混合存储路由模块测试"""
import os
import sqlite3

from app.storage_router import (
    detect_content_type, route_storage, get_strategy_info,
    execute_strategy, _safe_table_name,
    STORAGE_STRATEGIES, FILE_TYPE_ROUTING,
)


# ── detect_content_type ──

def test_detect_contract():
    text = "本合同由甲方与乙方签署，合同编号 HT-2026，双方盖章生效"
    assert detect_content_type(text) == "contract"


def test_detect_contract_needs_two_keywords():
    """仅 1 个合同关键词不判定为合同"""
    assert detect_content_type("这份文件提到了合同一词") != "contract"


def test_detect_relationship():
    text = "张三的上级是李四，李四依赖王五负责的项目，组织架构中赵六汇报给上级钱七，各部门关联紧密"
    assert detect_content_type(text) == "relationship"


def test_detect_table_by_extension():
    assert detect_content_type("", "data.csv") == "table"
    assert detect_content_type("", "报表.xlsx") == "table"


def test_detect_code():
    assert detect_content_type("def foo(): pass", "main.py") == "code"
    assert detect_content_type("", "app.ts") == "code"


def test_detect_image():
    assert detect_content_type("", "photo.png") == "image"
    assert detect_content_type("", "scan.jpg") == "image"


def test_detect_document_default():
    assert detect_content_type("这是一篇普通的产品介绍文档") == "document"
    assert detect_content_type("", "readme.md") == "document"


def test_detect_none_text():
    assert detect_content_type(None, "file.md") == "document"


# ── route_storage ──

def test_route_contract_to_original():
    r = route_storage("合同.pdf", "甲方乙方签署的合同，盖章生效", 1024)
    assert r["strategy"] == "original"
    assert r["content_type"] == "contract"
    assert "保存原始文件" in r["actions"]
    assert r["file_extension"] == ".pdf"
    assert r["file_size"] == 1024


def test_route_csv_to_structured():
    r = route_storage("价格表.csv", "name,price\n苹果,5")
    assert r["strategy"] == "structured"
    assert r["content_type"] == "table"


def test_route_md_to_rag():
    r = route_storage("手册.md", "# 产品手册\n使用说明")
    assert r["strategy"] == "rag"
    assert "语义切割" in r["actions"]


def test_route_image_to_multimodal():
    r = route_storage("扫描件.png", "")
    assert r["strategy"] == "multimodal"


def test_route_relationship_to_graph():
    text = "上级 下级 依赖 关联 负责人 汇报"
    r = route_storage("组织架构.md", text)
    assert r["strategy"] == "graph"


# ── get_strategy_info ──

def test_get_strategy_info():
    info = get_strategy_info()
    assert set(info["strategies"].keys()) == {"rag", "original", "structured", "graph"}
    assert info["file_routing"][".md"] == "rag"
    assert info["file_routing"][".csv"] == "structured"
    assert info["total_strategies"] == len(STORAGE_STRATEGIES) + 1
    assert FILE_TYPE_ROUTING[".py"] == "rag"


# ── _safe_table_name ──

def test_safe_table_name():
    assert _safe_table_name("data.csv") == "data_data"
    assert _safe_table_name("my-file (v2).xlsx") == "data_my_file__v2_"
    assert _safe_table_name("价格表.csv") == "data_价格表"  # 中文保留


def test_safe_table_name_length_limit():
    name = _safe_table_name("a" * 200 + ".csv")
    assert len(name) <= 5 + 50  # "data_" + 50 字符截断


# ── execute_strategy ──

def test_execute_rag_strategy(tmp_path):
    f = tmp_path / "uploads"
    f.mkdir()
    doc = f / "文档.md"
    doc.write_text("# Orbit 介绍\n\nAI Agent 端到端系统，支持知识库检索。", encoding="utf-8")
    route = route_storage("文档.md", doc.read_text(encoding="utf-8"))
    result = execute_strategy(route, str(doc), doc.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["chunks"] >= 1
    assert "rag_index" in result["actions_performed"]


def test_execute_rag_without_text_skipped(tmp_path):
    route = {"strategy": "rag", "content_type": "document", "actions": [], "reason": ""}
    f = tmp_path / "empty.md"
    f.write_text("x", encoding="utf-8")
    result = execute_strategy(route, str(f), "")
    assert result["status"] == "skipped"


def test_execute_structured_csv(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    csv_file = uploads / "价格表.csv"
    csv_file.write_text("名称,价格\n苹果,5\n香蕉,3\n", encoding="utf-8")
    route = route_storage("价格表.csv", csv_file.read_text(encoding="utf-8"))
    result = execute_strategy(route, str(csv_file))
    assert result["status"] == "ok"
    assert result["rows"] == 2
    # SQLite 落在 uploads 的上级目录
    db = tmp_path / "structured_data.db"
    assert db.exists()
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT * FROM [data_价格表]").fetchall()
    conn.close()
    assert rows == [("苹果", "5"), ("香蕉", "3")]


def test_execute_structured_csv_no_header(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    csv_file = uploads / "empty.csv"
    csv_file.write_text("", encoding="utf-8")
    route = {"strategy": "structured", "content_type": "table", "actions": [], "reason": ""}
    result = execute_strategy(route, str(csv_file))
    assert result["status"] == "error"


def test_execute_original_strategy(tmp_path):
    f = tmp_path / "合同.txt"
    f.write_text("甲方乙方签署的合同，双方盖章生效，合同编号001", encoding="utf-8")
    route = route_storage("合同.txt", f.read_text(encoding="utf-8"))
    result = execute_strategy(route, str(f))
    assert result["status"] == "ok"
    assert result["chars"] > 0


def test_execute_unknown_strategy():
    route = {"strategy": "no_such", "content_type": "?", "actions": [], "reason": ""}
    result = execute_strategy(route, "/tmp/whatever.md")
    assert result["status"] == "error"
    assert "未知策略" in result["message"]


def test_execute_strategy_exception_caught():
    """文件不存在等异常被捕获返回 error 而非抛出"""
    route = {"strategy": "original", "content_type": "contract", "actions": [], "reason": ""}
    result = execute_strategy(route, "/nonexistent/path/file.txt")
    assert result["status"] == "error"
    assert "message" in result
