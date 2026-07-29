---
name: obsidian-skills
description: >
  Obsidian 官方技能包（39k⭐）。5 个技能：obsidian-markdown（wikilinks/callouts/properties）、
  obsidian-cli（vault 命令行操作）、defuddle（网页提取清洁 markdown）、
  json-canvas（画布）、obsidian-bases（数据库）。Agent Loop 使用前三个。
type: skill
license: MIT
source: https://github.com/kepano/obsidian-skills
author: kepano (Obsidian CEO)
---

# Obsidian Skills — Agent Loop 适配

## Agent Loop 集成点

| Skill | 谁用 | 何时用 |
|-------|------|--------|
| `obsidian-markdown` | Builder | 写入 `memory/lessons/*.md`、`memory/concepts/*.md` 时，生成正确的 wikilinks、callouts、frontmatter |
| `obsidian-cli` | Reviewer | 验证 vault 健康度：`obsidian backlinks` 检查孤页、`obsidian tags` 检查标签覆盖、`obsidian search` 检索记忆 |
| `defuddle` | Master / Planner | 用 `defuddle parse <url> --md` 替代 WebFetch，提取清洁内容节省 token |

## 工作流示例

### Builder 写入新 Lesson

```bash
# Builder 使用 obsidian-markdown 规范创建：
# memory/lessons/L-003.md

---
title: "空值检查遗漏导致 Crash"
tags: [bug, null-check, runtime]
aliases: [L-003, null-pointer-crash]
type: lesson
severity: high
related:
  - "[[L-001]]"       # 相关经验
  - "[[concepts/null-safety]]"
---

> [!danger] 根因
> 函数 `processData()` 未对 `input.data` 做空值检查，上游传入 `None` 时崩溃。

## 影响面
所有调用 `processData()` 的 3 个文件均受影响。

## 修复
# ponytail: 一行 guard，多个调用方共用
if input.data is None:
    return default_result
```

### Reviewer 验证 Vault 健康度

```bash
# 检查孤页（无入链的 Lessons，说明未被引用）
obsidian backlinks file="lessons/L-003"

# 标签分布概览
obsidian tags sort=count counts

# 语义搜索已有经验
obsidian search query="null check crash handler" limit=5
```

### Master 搜资料并沉淀

```bash
# 用 defuddle 替代 WebFetch，拿到清洁 markdown
defuddle parse https://blog.example.com/best-practices --md -o raw/article-001.md

# 然后 Builder 执行 ingest：读 raw/ → 写 concepts/ + 更新 index.md
```

## 安装依赖

```bash
# obsidian-cli 需要 Obsidian 正在运行
# defuddle 需要全局安装
npm install -g defuddle
```

## 核心文件

- `skills/obsidian-markdown/SKILL.md` — wikilinks、callouts、properties、embeds
- `skills/obsidian-cli/SKILL.md` — vault 搜索、backlinks、标签统计
- `skills/defuddle/SKILL.md` — 网页 → 清洁 markdown
- `skills/json-canvas/SKILL.md` — 知识图谱画布（可选）
- `skills/obsidian-bases/SKILL.md` — 数据库操作（可选）
