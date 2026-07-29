# Logos

> AI Coding 时代的个人知识收集器。捕捉散落在对话中的设计思路、灵光一现、最佳实践，日积月累成只属于你的知识护城河。

## 快速开始

```bash
git clone https://github.com/myyyyyyz/logos-aicoding.git skills/logos/
```

在 AI 对话中说：

> **"logos"** 或 **"记录本次对话"**

AI 会回顾本轮对话，打捞出重要的想法、决策和灵感，写入 `logos/your-memory/YYYY-MM-DD.md`。

## 为什么需要 Logos

AI Coding 的对话流里，散落着大量珍贵的东西：

> "这个设计为什么是合理的"  
> "AI 说这里有个反模式要注意"  
> "我突然想到一个更好的方案"  
> "这个配置坑踩过了，记住别踩第二次"

这些东西稍纵即逝。聊完就忘，下次遇到同样的坑还得重来。

Logos 就是你的"小跟班"。每次对话结束时帮你打捞这些碎片。**灵感比工作量重要**——即使今天一行代码没写，有好的想法也要记下来。

日积月累，这些碎片会拼成只属于你的知识图谱。这就是 AI 时代每个人的护城河。

## 30 秒看效果

```text
logos/your-memory/2026-07-02.md

# 2026年07月02日

### 18:20 ~ 18:55 | 第 1 次对话

#### 💎 灵感与收获
 来自用户：
  - 把 session-journal 改名为 logos，因为 λόγος 意味着"有意义的言说"——这正是 skill 在做的事
  - 更进一步：不只是记录，而是收集——像在海边捡贝壳

 来自 AI：
  - Skill 类项目的第一版要写清楚"自动化由谁触发、上下文从哪里来"——否则用户会把 prompt 能力误解成已落地的执行器能力

 踩坑提醒：
  - YAML frontmatter 的多行 `>-` 在有些解析器中不兼容中文标点，用 `|-` 代替

#### 🎯 关键决策
| 决策 | 原因 |
|------|------|
| README 顶部加 Quick Start | 参考 obra/superpowers、anthropics/skills 模式 |
| "经验沉淀"改"灵感与收获" | 更准确表达核心价值：打捞想法，不写流水账 |

#### 📋 需求概述
...

#### 📝 对话摘要
...
```

完整示例：[examples/daily/2026-07-02.md](examples/daily/2026-07-02.md)

## 日志内容

| 区块 | 内容 | 优先级 |
|------|------|--------|
| 💎 灵感与收获 | 设计巧思、最佳实践、灵光一现（标注来源） | ⭐ 最重要 |
| 🎯 关键决策 | 技术选型、方案取舍及原因 | 高 |
| 📋 需求概述 | 本轮对话的核心目标 | 中 |
| 📝 对话摘要 | 做了什么、解决了什么 | 中 |
| 📦 产物清单 | 文件变更 | 低 |
| ⚠️ 待办 / 遗留 | 未完成事项 | 低 |

同日多段对话追加到同一文件，自动递增 `第 N 次对话` 编号。

## 各平台安装速查

| 工具 | 安装路径 | 如何触发 |
|------|---------|---------|
| Claude Code | `.claude/skills/logos/` | 说 `logos`，或配 Stop hook |
| Codex CLI | `.codex/skills/logos/` | 说 `logos`，或配 automation |
| Cursor | `.cursor/skills/logos/` | 说 `logos` |
| CodeBuddy | `.codebuddy/skills/logos/` | 说 `logos`，或配定时任务 |
| Antigravity | 项目 skills 目录 | 说 `logos` |
| OpenCode | `skills/logos/` | 说 `logos` |

## 自动触发（可选）

配置 Hook 实现对话结束自动记录：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "command": "请执行 logos skill，打捞本轮对话中的灵感和重要决策"
      }
    ]
  }
}
```

## 隐私与安全

写入前自动脱敏：不记录 API Key、Token、密码、私钥。敏感内容用 `[REDACTED]` 替代。

## 验证

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate.ps1
```

## 文件结构

```text
logos/
├── SKILL.md
├── README.md
├── references/
│   └── template.md
├── examples/
│   └── daily/
│       └── 2026-07-02.md
└── scripts/
    ├── write.py          # 记忆写入器，时间由系统硬控
    └── validate.ps1
```


