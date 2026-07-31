# Master — 让 AI 成为真正的技术大师

> **English**: Master — Turn Your AI into a True Technical Master

---

## 简介 / Overview

**Master** 是一个用于联网搜索的 Skill。当您询问技术相关的问题时，它让 AI 自动从 GitHub 及全球专业平台搜索最佳实践和解决方案——您的 AI 不再只是一名助手，而是一名真正的 Master。

**Master** is a web-search Skill. When you ask technical questions, it instructs the AI to automatically search GitHub and global professional platforms for best practices and solutions—your AI becomes a true Master, not just an assistant.

---

## 核心特性 / Key Features

| 特性 Feature | 说明 Description |
|-------------|----------------|
| 🔍 智能触发 Smart Trigger | 技术问题、Bug 修复、最佳实践、技术选型等场景自动触发 Automatically triggered by technical questions, bug fixes, best practices, and tech decisions |
| 🎯 分层搜索 Tiered Search | L0 代码开源 → L1 垂直领域 → L2 全球社区 → L3 国内实战 → L4 厂商官方 Five-tier search from code to vendor official |
| 🤖 AI 领域特化 AI Specialization | AI/Agent/LLM/RAG/Harness 问题优先搜索厂商官方源，GitHub 次之 AI-related issues prioritize vendor official sources |
| 🧠 知识内化 Knowledge Internalization | 搜索精华自动转化为记忆，下次直接复用 Search results are converted into reusable memories |
| ⏱️ 时效控制 Time Awareness | 通用技术优先近 1 年，AI 技术优先近 3 个月 Prioritizes recent content; 3 months for AI, 1 year for general tech |

---

## 搜索优先级 / Search Priority

### 通用技术 / General Technology

```
GitHub → 垂直领域专业站 → 全球技术社区 → 国内实战平台 → 厂商官方社区
```

- **第一轮**: 同时搜索 GitHub + 问题所属垂直领域站
- **第二轮**: 扩展至全球技术社区
- **第三轮**: 国内平台与厂商社区交叉验证

### AI / Agent / LLM / RAG / Harness

```
厂商官方 (OpenAI/Anthropic/AWS/Google/Microsoft/Meta) → GitHub → 全球技术社区
```

- **第一轮**: 同时搜索至少 3 家厂商官方源
- **第二轮**: GitHub 实现验证
- **第三轮**: Dev.to / Medium / Hacker News 交叉验证

---

## 平台目录 / Platform Catalog

| 层级 Tier | 类别 Category | 代表平台 Platforms | 适用场景 Scenarios |
|-----------|--------------|-------------------|------------------|
| **L0** | 代码与开源 Code & Open Source | GitHub, GitLab, Gitee | 所有技术问题的第一搜索源 First source for all tech issues |
| **L1** | 垂直领域 Vertical | CSS-Tricks, DevOps Weekly, LeetCode | 细分领域的专业最佳实践 Domain-specific best practices |
| **L2** | 全球深度社区 Global Communities | Stack Overflow, InfoQ, Dev.to, Medium, HN | 高质量问答、架构案例 Quality Q&A and architecture cases |
| **L3** | 国内实战平台 China Platforms | 掘金, 博客园, SegmentFault, CSDN | 中文环境落地方案 Chinese localization solutions |
| **L4** | 厂商官方社区 Vendor Communities | 阿里云, 腾讯云, 华为云 | 云原生、企业级架构 Cloud-native and enterprise architecture |

---

## 搜索策略 / Search Strategies

| 问题类型 Issue Type | 搜索路径 Search Path |
|--------------------|---------------------|
| Bug / 报错 | GitHub Issues → Stack Overflow → SegmentFault |
| 最佳实践 / 技术选型 Best Practices / Selection | GitHub README → InfoQ → 掘金 |
| 性能优化 Performance | GitHub Benchmark → Stack Overflow → 博客园 |
| 架构设计 Architecture | InfoQ → Medium → 阿里云/腾讯云社区 |
| 安全相关 Security | GitHub Security Advisories → OWASP → CVE |
| 前端/UI Frontend | GitHub Components → CSS-Tricks → 掘金 |
| DevOps/运维 | DevOps Weekly → GitHub Actions → 华为云社区 |
| 算法/面试 Algorithms | LeetCode → AcWing → 牛客 |
| **AI/Agent/LLM/RAG/Harness** | **OpenAI/Anthropic/AWS/Google/Microsoft/Meta 官方 → GitHub → Dev.to/Medium/HN** |

---

## 触发条件 / Trigger Conditions

以下场景自动触发搜索：

The following scenarios automatically trigger search:

- 技术问题 / Technical questions: "怎么做" / "how to"
- 最佳实践 / Best practices: "最佳实践" / "best practice"
- 方案对比 / Comparison: "有没有更好的方案" / "better approach"
- 性能优化 / Optimization: "怎么优化" / "how to optimize"
- Bug 修复 / Bug fixes: "这个 bug 怎么修" / "how to fix this bug"
- 技术选型 / Tech selection: "推荐什么技术/工具/框架" / "recommend a tool/framework"
- 架构设计 / Architecture design
- 安全加固 / Security hardening
- AI/Agent/LLM/RAG/Prompt 工程 / AI SDK 相关问题
- Agent Harness 基础设施问题 (hooks/settings/tool 编排/context fork/sub-agent 调度)

> ⚠️ **禁止触发 / Not triggered**: 纯业务讨论、非技术性需求澄清 Pure business discussions, non-technical requirement clarification

---

## 记忆转化 / Knowledge Memory

搜索完成后，精华自动转化为可复用记忆：

After searching, the results are converted into reusable memories:

| 记忆类型 Memory Type | 示例 Example |
|---------------------|-------------|
| 解决方案 Solutions | "处理 [某问题] 的标准解法是 [方案]" |
| 技术选型结论 Tech Selection | "[场景] 下推荐用 [工具X] 而非 [工具Y]" |
| 架构模式 Architecture Patterns | "[某架构模式] 的适用场景和落地要点" |
| 常见陷阱 Common Pitfalls | "使用 [某技术] 时常犯错误..." |
| 性能基线 Performance Baselines | "[某场景] 的性能基线参考值" |

---

## 质量自检 / Quality Checklist

回答前必须检查：

Before answering, the AI checks:

- [ ] GitHub 是否已搜索 / GitHub searched
- [ ] 搜索结果是否包含近 1 年内的内容 / Results within 1 year
- [ ] 答案是否有来源引用 / Sources cited
- [ ] 是否将精华写入记忆 / Knowledge saved to memory
- [ ] 不同平台方案是否交叉验证 / Cross-validated across platforms

AI/Agent 相关问题额外检查：

Additional checks for AI/Agent issues:

- [ ] 是否至少搜索了 3 家官方厂源 / Searched at least 3 vendor sources
- [ ] AI 内容是否优先近 3 个月 / AI content within 3 months
- [ ] 是否以官方文档为权威参考 / Official docs as authoritative reference
- [ ] 超过 6 个月的 AI 内容是否交叉验证 / Content >6 months cross-validated

---

## CLI 安装与使用 / CLI Installation & Usage

### 安装方式 / Installation

CodeBuddy CLI 会自动扫描以下目录的 `SKILL.md`，**无需手动注册**：

CodeBuddy CLI automatically scans the following directories for `SKILL.md`, **no manual registration needed**:

| 级别 Level | 路径 Path | 作用范围 Scope |
|------|------|----------|
| **项目级 Project** | `<project>/.codebuddy/skills/master/` | 仅当前项目可用，优先级最高 Current project only, highest priority |
| **用户级 User** | `~/.codebuddy/skills/master/` | 当前用户全局可用 Available globally for current user |

**快速安装 / Quick Install**：

```bash
# 方式一：项目级安装（推荐，团队共享）
mkdir -p /your/project/.codebuddy/skills/master
cp SKILL.md /your/project/.codebuddy/skills/master/
cp -r references /your/project/.codebuddy/skills/master/

# 方式二：用户级安装（个人全局使用）
mkdir -p ~/.codebuddy/skills/master
cp SKILL.md ~/.codebuddy/skills/master/
cp -r references ~/.codebuddy/skills/master/
```

### 调用方式 / How to Invoke

#### A. AI 自动识别（默认）
进入项目目录后直接提问技术问题，AI 会根据 `description` 自动匹配并加载 Master Skill：

```bash
cd /your/project
codebuddy
> 怎么优化这个 SQL 查询？
# AI 自动触发 master → 搜索 GitHub/Stack Overflow → 给出优化方案
```

#### B. 手动强制触发
在 CLI 中输入 `/` + skill 名称强制调用：

```bash
/master
/master 帮我分析这个报错 IndexError: list index out of range
```

适用场景：
- 需要强制使用某个 Skill，不想依赖 AI 自动判断
- 想明确看到搜索过程

#### C. 单次命令模式（非交互）
```bash
# 直接提问并退出（需加 -y 跳过权限确认）
codebuddy -p "推荐一个 Go 的 ORM 框架" -y

# 管道输入（如分析日志）
cat error.log | codebuddy -p "分析这些错误" -y
```

#### D. 查看已加载的 Skill
```bash
/skills
```

输出分组显示：
- **User skills**: `~/.codebuddy/skills/` 下的技能
- **Project skills**: `.codebuddy/skills/` 下的技能

### 常见问题 / FAQ

| 问题 Issue | 解决方式 Solution |
|-----------|-----------------|
| Skill 没被自动触发 | 检查 `description` 是否准确描述了使用场景；尝试用 `/master` 手动触发 |
| 无法手动调用 | 确认目录名是否为 `master`；检查是否设置了 `user-invocable: false` |
| 搜索工具报错 | 检查 `allowed-tools` 是否包含 `WebFetch` 和 `WebSearch` |
| 项目级和用户级冲突 | 项目级 skill 优先级更高，会覆盖用户级同名 skill |

---

## 文件结构 / File Structure

```
master/
├── SKILL.md                          # Skill 定义文件 / Skill definition
├── README.md                         # 本文件 / This file
├── references/
│   ├── platform-catalog.md           # 完整平台目录 / Full platform catalog
│   ├── search-strategies.md          # 详细搜索策略 / Detailed search strategies
│   ├── quality-checklist.md          # 完整质量自检清单 / Full quality checklist
│   └── memory-conversion.md          # 记忆转化指南 / Memory conversion guide
├── scripts/
│   └── search_dispatcher.py          # 搜索调度脚本 / Search dispatcher script
└── examples/
    └── usage-examples.md             # 使用示例 / Usage examples
```

---

## 原则 / Principles

> **遇到任何技术问题，先搜索再回答。你不是在凭记忆回答，你是在做研究。**
>
> **When facing any technical issue, search first, then answer. You are not answering from memory—you are conducting research.**
---
