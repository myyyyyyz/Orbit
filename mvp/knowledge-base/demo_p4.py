#!/usr/bin/env python3
"""
P4 验证脚本 — 小白体验 + 企业能力

验证 6 个模块:
1. 新手引导：角色选择 → 推荐 Skill
2. 混合存储：文件类型 → 自动路由存储策略
3. 多用户隔离：注册 A/B 用户 → 独立 collection
4. 长期记忆：保存画像+项目 → 跨会话恢复
5. Obsidian MCP：Logos 笔记写入（验证 your-memory 输出）
6. 多模态：图片/Excel 文件路由（OCR 接口预留）
"""

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import pathlib

BASE_URL = "http://localhost:8001"

def api_get(path):
    resp = urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30)
    return json.loads(resp.read())

def api_post(path, body):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def print_result(label, value, passed=None):
    icon = "✅ " if passed is True else ("❌ " if passed is False else "  ")
    print(f"  {icon}{label}: {value}")


def main():
    print_section("P4 验证 — 小白体验 + 企业能力")
    all_passed = True

    # ════════════════════════════════════════════════
    # Module 1: 新手引导
    # ════════════════════════════════════════════════
    print_section("Module 1: 新手引导（角色选择 → 推荐 Skill）")

    template = api_get("/api/onboarding/template")
    print_result("引导标题", template["title"])
    print_result("可选角色数", len(template["roles"]))
    for role in template["roles"]:
        print(f"    {role['icon']} {role['label']} ({role['key']}) — {role['desc'][:30]}...")

    # 选择开发者角色
    dev_config = api_get("/api/onboarding/roles/developer")
    has_skills = len(dev_config.get("recommended_skills", [])) > 0
    print_result("开发者推荐 Skills", dev_config.get("recommended_skills"), has_skills)
    print_result("默认偏好", json.dumps(dev_config.get("default_preferences"), ensure_ascii=False))
    print_result("快捷操作", [a[:20] for a in dev_config.get("quick_actions", [])])

    # 选择企业用户角色
    ent_config = api_get("/api/onboarding/roles/enterprise")
    print_result("企业用户推荐 Skills", ent_config.get("recommended_skills"), len(ent_config.get("recommended_skills", [])) > 0)

    passed = has_skills and len(template["roles"]) >= 4
    if not passed: all_passed = False
    print_result("新手引导", "PASS" if passed else "FAIL", passed)

    # ════════════════════════════════════════════════
    # Module 2: 混合存储路由
    # ════════════════════════════════════════════════
    print_section("Module 2: 混合存储（文件类型 → 存储策略）")

    test_files = [
        ("产品手册.md", "这是一个产品手册，介绍恋心记录的功能和用法。", "rag"),
        ("租赁合同.pdf", "甲方：张三，乙方：李四。合同编号：HT-2026-001。双方签署盖章。", "original"),
        ("销售数据.xlsx", "sheet1 sheet2 row column 单元格 行 列", "structured"),
        ("架构设计.md", "系统架构依赖关系：前端依赖后端API，后端依赖数据库。负责人：张三。", "rag"),
        ("产品截图.png", "", "multimodal"),
        ("工具脚本.py", "def hello(): print('hello')", "rag"),
    ]

    storage_pass = True
    for filename, text, expected_strategy in test_files:
        result = api_post("/api/storage/analyze", {
            "filename": filename,
            "text": text,
            "file_size": len(text),
        })
        strategy = result["strategy"]
        content_type = result["content_type"]
        match = strategy == expected_strategy
        if not match:
            storage_pass = False
        print_result(f"{filename}", f"→ {strategy} ({content_type})", match)

    if not storage_pass: all_passed = False
    print_result("混合存储", "PASS" if storage_pass else "FAIL", storage_pass)

    # ════════════════════════════════════════════════
    # Module 3: 多用户隔离
    # ════════════════════════════════════════════════
    print_section("Module 3: 多用户/企业隔离")

    # 注册用户 A
    user_a = api_post("/api/auth/register", {
        "username": f"test_user_a_{int(time.time())}",
        "password": "pass123",
    })
    print_result("注册用户 A", f"id={user_a['user_id']} collection={user_a['collection_name']}", True)

    # 注册用户 B
    user_b = api_post("/api/auth/register", {
        "username": f"test_user_b_{int(time.time())}",
        "password": "pass123",
    })
    print_result("注册用户 B", f"id={user_b['user_id']} collection={user_b['collection_name']}", True)

    # 验证 collection 隔离
    coll_a = user_a["collection_name"]
    coll_b = user_b["collection_name"]
    isolated = coll_a != coll_b
    print_result("Collection 隔离", f"A={coll_a} B={coll_b}", isolated)

    # 登录验证
    login_result = api_post("/api/auth/login", {
        "username": user_a["username"] if "username" in user_a else "",
        "password": "pass123",
    })

    # 获取用户信息
    me = api_get(f"/api/auth/me/{user_a['user_id']}")
    print_result("用户信息", f"username={me['username']} role={me['role']}", me["user_id"] == user_a["user_id"])

    if not isolated: all_passed = False
    print_result("多用户隔离", "PASS" if isolated else "FAIL", isolated)

    # ════════════════════════════════════════════════
    # Module 4: 长期记忆（跨会话恢复）
    # ════════════════════════════════════════════════
    print_section("Module 4: 长期记忆（跨会话上下文恢复）")

    user_id = user_a["user_id"]

    # 保存用户画像
    api_post("/api/memory/profile", {
        "user_id": user_id,
        "role": "developer",
        "preferences": {"output_format": "code_first", "code_comments": "chinese"},
        "common_skills": ["master", "review", "ponytail"],
        "output_style": "concise",
    })
    print_result("保存用户画像", f"role=developer skills=3", True)

    # 保存项目上下文
    api_post("/api/memory/project", {
        "user_id": user_id,
        "project_name": "LoveDiary",
        "tech_stack": "FastAPI + SQLite + Vanilla JS",
        "current_progress": "P3 完成，P4 进行中",
        "key_decisions": ["用 FastAPI 而非 Flask", "SQLite 而非 PostgreSQL"],
    })
    print_result("保存项目上下文", "project=LoveDiary", True)

    # 保存对话摘要
    api_post("/api/memory/summary", {
        "user_id": user_id,
        "summary": "完成了 P4 新手引导、混合存储、多用户、长期记忆模块的验证。",
        "key_points": ["新手引导 5 角色", "混合存储 4 策略", "多用户 Collection 隔离", "长期记忆跨会话恢复"],
    })
    print_result("保存对话摘要", "4 个关键点", True)

    # 跨会话恢复
    restored = api_get(f"/api/memory/restore/{user_id}")
    has_context = restored.get("has_context", False)
    profile = restored.get("user_profile", {})
    project = restored.get("current_project", {})
    summaries = restored.get("recent_summaries", [])

    print_result("上下文恢复", f"has_context={has_context}", has_context)
    print_result("  画像", f"role={profile.get('role')} skills={profile.get('common_skills')}", profile.get("role") == "developer")
    print_result("  项目", f"name={project.get('project_name')} progress={project.get('current_progress')}", project.get("project_name") == "LoveDiary")
    print_result("  摘要", f"{len(summaries)} 条", len(summaries) >= 1)

    memory_pass = has_context and profile.get("role") == "developer" and project.get("project_name") == "LoveDiary"
    if not memory_pass: all_passed = False
    print_result("长期记忆", "PASS" if memory_pass else "FAIL", memory_pass)

    # ════════════════════════════════════════════════
    # Module 5: Obsidian MCP（Logos 笔记写入）
    # ════════════════════════════════════════════════
    print_section("Module 5: Obsidian MCP（Logos 笔记）")

    logos_result = api_post("/api/knowledge/logos", {
        "conversation": f"P4 验证完成。用户 {user_id} 选择了 developer 角色，项目 LoveDiary 进展到 P4。测试了新手引导、混合存储路由、多用户隔离、长期记忆恢复。",
        "start_time": time.strftime("%H:%M"),
    })
    memory_file = logos_result.get("file", "")
    file_exists = pathlib.Path(memory_file).exists() if memory_file else False
    print_result("Logos 写入", logos_result.get("message"), file_exists)
    print_result("文件路径", memory_file)
    print_result("总结长度", f"{logos_result.get('summary_length', 0)} 字符")

    if not file_exists: all_passed = False
    print_result("Obsidian/Logos", "PASS" if file_exists else "FAIL", file_exists)

    # ════════════════════════════════════════════════
    # Module 6: 多模态（文件路由预留）
    # ════════════════════════════════════════════════
    print_section("Module 6: 多模态（图片/Excel 路由）")

    # 图片路由
    img_result = api_post("/api/storage/analyze", {"filename": "photo.jpg", "text": "", "file_size": 500000})
    img_route = img_result["strategy"] == "multimodal"
    print_result("图片 → multimodal", f"strategy={img_result['strategy']} actions={img_result['actions']}", img_route)

    # Excel 路由
    xls_result = api_post("/api/storage/analyze", {"filename": "data.xlsx", "text": "", "file_size": 100000})
    xls_route = xls_result["strategy"] == "structured"
    print_result("Excel → structured", f"strategy={xls_result['strategy']} actions={xls_result['actions']}", xls_route)

    multimodal_pass = img_route and xls_route
    if not multimodal_pass: all_passed = False
    print_result("多模态路由", "PASS" if multimodal_pass else "FAIL", multimodal_pass)

    # ════════════════════════════════════════════════
    # 最终结果
    # ════════════════════════════════════════════════
    print_section("P4 验收结果")

    modules = [
        ("新手引导", passed),
        ("混合存储", storage_pass),
        ("多用户隔离", isolated),
        ("长期记忆", memory_pass),
        ("Obsidian/Logos", file_exists),
        ("多模态路由", multimodal_pass),
    ]

    for name, p in modules:
        print_result(name, "✅ PASS" if p else "❌ FAIL", p)

    passed_count = sum(1 for _, p in modules if p)
    print(f"\n  总计: {passed_count}/{len(modules)} 模块通过")

    return 0 if all_passed and passed_count >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
