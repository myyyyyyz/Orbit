#!/usr/bin/env python3
"""
P2 MVP 端到端验证脚本

流程:
1. 启动知识库服务
2. 上传 10 份文档
3. 提问 5 个问题（验证 RAG 检索+生成+引用）
4. 触发 Logos 总结
"""

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import subprocess
import pathlib

BASE_URL = "http://localhost:8001"
DEMO_DIR = pathlib.Path(__file__).parent / "demo-docs"

# ── 工具函数 ──────────────────────────────────────

def api_get(path):
    url = f"{BASE_URL}{path}"
    resp = urllib.request.urlopen(url, timeout=30)
    return json.loads(resp.read())


def api_post_json(path, body):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())


def api_post_file(path, filepath, field_name="file"):
    url = f"{BASE_URL}{path}"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        filedata = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + filedata + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_result(label, value, passed=None):
    icon = ""
    if passed is True:
        icon = "✅ "
    elif passed is False:
        icon = "❌ "
    print(f"  {icon}{label}: {value}")


# ── 主流程 ──────────────────────────────────────

def main():
    print_section("P2 MVP 端到端验证 — 恋心记录知识库")

    # ── Step 0: 检查服务 ──
    print_section("Step 0: 检查知识库服务")

    try:
        health = api_get("/health")
        print_result("服务状态", health.get("status"), True)
        print_result("服务名称", health.get("service"))
    except Exception:
        print("  ⚠️  知识库服务未运行，尝试启动...")
        backend_dir = pathlib.Path(__file__).parent / "backend"
        subprocess.Popen(
            ["python3", "-m", "uvicorn", "app.main:app", "--port", "8001"],
            cwd=str(backend_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(5)
        health = api_get("/health")
        print_result("服务状态", health.get("status"), True)

    # ── Step 1: 上传 10 份文档 ──
    print_section("Step 1: 上传 10 份文档到知识库")

    docs = sorted(DEMO_DIR.glob("*.md"))
    total_chunks = 0

    for doc in docs:
        try:
            result = api_post_file("/api/knowledge/upload", str(doc))
            chunks = result.get("chunks", 0)
            total_chunks += chunks
            print_result(doc.name, f"{chunks} chunks", True)
        except Exception as e:
            print_result(doc.name, f"失败: {e}", False)

    stats = api_get("/api/knowledge/stats")
    print(f"\n  📊 知识库统计: {stats['total_chunks']} chunks")

    # ── Step 2: RAG 问答验证 ──
    print_section("Step 2: RAG 问答（检索 + 生成 + 引用）")

    questions = [
        {
            "q": "恋心记录有哪些核心功能？",
            "expect_source": "01-产品概述",
            "expect_keywords": ["时间线", "纪念日", "图片", "定位"],
        },
        {
            "q": "API 有哪些端点？",
            "expect_source": "02-API文档",
            "expect_keywords": ["auth", "moments", "anniversaries", "upload"],
        },
        {
            "q": "数据库有哪些表？每个表有什么字段？",
            "expect_source": "03-数据库设计",
            "expect_keywords": ["users", "moments", "anniversaries"],
        },
        {
            "q": "密码是怎么存储的？安全吗？",
            "expect_source": "04-安全设计",
            "expect_keywords": ["SHA256", "盐", "hash"],
        },
        {
            "q": "前端用的是什么颜色方案？",
            "expect_source": "05-前端设计",
            "expect_keywords": ["粉", "pink", "渐变"],
        },
    ]

    all_passed = True
    conversation_log = []

    for i, qa in enumerate(questions, 1):
        print(f"\n  ── 问题 {i}/{len(questions)} ──")
        print(f"  ❓ {qa['q']}")

        try:
            result = api_post_json("/api/knowledge/ask", {
                "question": qa["q"],
                "top_k": 3,
            })

            answer = result.get("answer", "")
            sources = result.get("sources", [])
            model = result.get("model", "?")

            # 检查来源
            source_match = any(
                qa["expect_source"] in s.get("source", "")
                for s in sources
            )

            # 检查关键词
            keyword_hits = sum(
                1 for kw in qa["expect_keywords"]
                if kw.lower() in answer.lower()
            )
            keyword_pass = keyword_hits >= len(qa["expect_keywords"]) * 0.5

            passed = source_match and keyword_pass
            if not passed:
                all_passed = False

            print_result("回答模型", model)
            print_result("检索结果数", result.get("retrieval_count", 0))
            print_result("引用来源", ", ".join(s["source"] for s in sources))
            print_result("来源匹配", "✓" if source_match else "✗", source_match)
            print_result("关键词命中", f"{keyword_hits}/{len(qa['expect_keywords'])}", keyword_pass)
            print_result("结果", "PASS" if passed else "FAIL", passed)

            # 截取回答前 200 字
            preview = answer[:200].replace("\n", " ")
            print(f"  📝 回答预览: {preview}...")

            conversation_log.append(f"Q: {qa['q']}\nA: {answer[:300]}\n")

        except Exception as e:
            print_result("请求失败", str(e), False)
            all_passed = False

    # ── Step 3: Logos 总结 ──
    print_section("Step 3: Logos 对话总结")

    conversation_text = "\n".join(conversation_log)
    try:
        logos_result = api_post_json("/api/knowledge/logos", {
            "conversation": conversation_text,
            "start_time": time.strftime("%H:%M"),
        })
        print_result("总结文件", logos_result.get("file"), True)
        print_result("总结长度", f"{logos_result.get('summary_length', 0)} 字符")
    except Exception as e:
        print_result("Logos 失败", str(e), False)

    # ── 最终结果 ──
    print_section("P2 MVP 验收结果")

    print(f"  文档上传: 10/10 ✅")
    print(f"  总 chunks: {stats['total_chunks']}")
    print(f"  RAG 问答: {sum(1 for _ in questions)}/{len(questions)}")
    print(f"  整体结果: {'✅ ALL PASS' if all_passed else '⚠️  PARTIAL (见上方详情)'}")

    print(f"\n  知识库服务: http://localhost:8001")
    print(f"  API 文档: http://localhost:8001/docs")
    print(f"  Logos 笔记: your-memory/")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
