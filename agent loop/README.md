# Agent Loop — 多智能体协作开发框架

```
Planner (只读) → Builder (执行) → Reviewer (验证) → 🔄 Looping
     ↑                                              |
     └──────────────────────────────────────────────┘
   Master (冷启动) ←  ←  ←  ←  ← User Agent (UX 审查)
```

核心思想：**生成-评估严格分离**。Planner 只分析不写代码，Builder 只执行不评估，Reviewer 只验证不修改。

支持多种运行方式，不绑定特定平台。

---

## 快速开始

### 方式一：CodeBuddy（全自动）

将内容复制到目标项目的 `.codebuddy/` 下，在 CodeBuddy 对话中运行：

```
加载 loop-engine skill，跑一次 Loop。
```

不填任何配置也会自动启动 Master Agent 引导你完成初始化。

### 方式二：任何 LLM CLI（如 Claude Code / Gemini CLI / Codex CLI）

```
# 把整个框架当作上下文喂给模型
cat agents/README.md agents/PROTOCOL.md skills/loop-engine/SKILL.md | llm-cli -s "请按此协议执行一次 Loop，当前项目路径: $PWD"
```

模型会按照 SKILL.md 的 12 步流程逐级执行。关键在于 LLM CLI 具备文件读写和命令执行能力，能自主完成 Planner→Builder→Reviewer 的接力。

### 方式三：手动模式（人做 Controller）

```
# 1. 人读协议，理解流程
cat agents/PROTOCOL.md

# 2. 扮演 Controller
- 把 agents/planner.md 给 LLM → 产出 loop-plan.md
- 把 agents/builder.md + loop-plan.md 给 LLM → 产出修改
- 把 agents/reviewer.md + plan + output 给 LLM → 验证结果
```

适合不想折腾自动化的场景。只需一个能读 markdown 的 LLM 对话窗口。

### 方式四：CLI Runner（bash 脚本，零依赖）

```bash
chmod +x run-loop.sh
./run-loop.sh --api anthropic --model claude-sonnet-4-20250514
```

Runner 用 `curl` 直接调 LLM API，依次 spawn Planner → Builder → Reviewer，文件通信。详见 [run-loop.sh](#cli-runner)。

---

## 架构

```
┌─────────────┐    loop-plan.md     ┌─────────────┐
│   Planner   │ ───────────────────→│   Builder   │
│  (只读分析)  │                      │  (执行修改)  │
└─────────────┘                      └──────┬──────┘
                                            │
                                    loop-builder-output.md
                                            │
                                            ↓
┌─────────────┐    loop-review-result.md  ┌─────────────┐
│  Controller │ ←───────────────────────│   Reviewer  │
│  (调度/决策)  │                          │  (两阶段验证) │
└─────────────┘                           └─────────────┘
```

| Agent | 角色 | 通信方式 |
|-------|------|---------|
| **Master** | 冷启动需求对齐，一次性 | → 产出 project-spec.md + scenes/ |
| **Planner** | 只读，分析状态 + 影响面 → 产出计划 | → 写 loop-plan.md |
| **Builder** | 严格按计划修改代码 | → 写 loop-builder-output.md |
| **Reviewer** | 两阶段验证（Spec + 质量） | → 写 loop-review-result.md |
| **User Agent** | 前端 UX 截图审查（条件触发） | → 写 loop-user-review.md |
| **Controller** | 调度器，不参与推理 | 读写 state，spawn/kill 子 agent |

五个 Agent 之间**不直接对话**，通过临时 markdown 文件接力。这种设计让流程可回溯、可中断恢复、可人工介入。

---

## 目录结构

```
.
├── agents/                   ← Agent 定义（每个 .md 就是一个 Agent）
│   ├── master.md             ← Master：需求对齐（一次性冷启动）
│   ├── planner.md            ← Planner：只读分析，产出执行计划
│   ├── builder.md            ← Builder：严格按计划修改代码
│   ├── reviewer.md           ← Reviewer：两阶段验证输出
│   ├── user.md               ← User Agent：前端 UX 审查（可选）
│   ├── PROTOCOL.md           ← 通信协议：文件接力规则
│   ├── HOWTO.md              ← 使用指南
│   └── README.md             ← Agent 目录说明
│
├── scenes/                   ← 场景插槽
│   └── _template.md          ← 场景模板，复制后填三个插槽
│
├── skills/                   ← 可复用 Skill 包
│   ├── loop-engine/          ← Controller 调度器
│   │   └── SKILL.md          ← 完整的 12 步调度协议
│   ├── master/               ← 搜索最佳实践的 Skill
│   │   ├── SKILL.md
│   │   ├── scripts/           ← 搜索脚本
│   │   └── references/        ← 平台目录、搜索策略等
│   ├── user-reviewer/        ← UX 审查 Skill
│   │   └── SKILL.md
│   └── ponytail/             ← ★ 懒人开发模式（61k⭐）
│       ├── SKILL.md           ← 适配层：Builder 用决策阶梯，Reviewer 用过度工程检测
│       └── skills/            ← 原始 ponytail + ponytail-review SKILL
│   └── obsidian-skills/      ← ★ Obsidian 官方技能（39k⭐）
│       ├── SKILL.md           ← 适配层：Builder 写 wikilinks，Reviewer 验 vault，Master 用 defuddle
│       └── skills/            ← obsidian-markdown / obsidian-cli / defuddle / json-canvas / obsidian-bases
│
├── project/                  ← 项目级配置（换项目只改这里）
│   └── project-spec.md       ← 项目身份 + effort_tier + 完成维度
│
├── memory/                   ← 运行时状态
│   ├── loop-state.md         ← 任务队列与历史
│   ├── runtime-spec.md       ← 当前任务动态契约
│   └── lessons-learned.md    ← 踩坑记录
│
├── run-loop.sh               ← CLI Runner（零依赖 bash 脚本）
├── README.md                 ← 本文件
└── .gitignore
```

---

## 核心概念

### 目标驱动（Goal-Driven）

每个执行步骤都必须带 **有验证方法**（verify）。不写模糊的"修复问题"，要写：

```
步骤 2: [test_level=skip] 修改 src/api.py 第 88 行，加空值检查 [免测: 单行防御性检查]
         → verify: python tests/runner/test_repro.py 输出 PASS
```

### 测试分级（Test Level）

不是所有代码改动都要写测试。Planner 根据复杂度标注：

| test_level | 适用场景 | Builder 行为 |
|-----------|---------|-------------|
| `full` | 核心路径/状态变更/多分支 | 写完整单元测试 + Gate |
| `smoke` | 中等逻辑/配置变更 | 跑已有测试 Gate |
| `skip` | ≤10 行/纯转换/常量文案 | 不写测试，注明免测理由 |

### 多维度完成

ALL_PASS ≠ 产物正确。日志健康度、配置完整性、稳定性、性能等维度各自独立验证，不依赖"产物正确→推断没问题"。

### 影响面搜索

修改函数/配置/schema/环境变量/import 路径/共享常量前，必须搜索所有引用点，标注调用上下文差异，阻断盲改风险。

### 迭代熔断

单 case 内 Planner→Builder→Reviewer 被退回最多 3 次，超限直接 CRITICAL_FAIL 升级给人，防止死循环。

---

## 场景接入

创建新场景只需两步：

```bash
# 1. 从模板复制
cp scenes/_template.md scenes/bug_fix.md

# 2. 编辑，填四个必填项：
#    - type: frontend | backend | fullstack
#    - Trigger: 什么条件下触发
#    - Verify: 每条 Gate 的验证命令和通过标准
#    - Fallback: 每条 Gate 失败的处理
```

场景文件只声明"做什么"和"怎么验证"，不关心具体 Agent 如何执行。骨架自动读取。

---

## CLI Runner

`run-loop.sh` 是一个零依赖的 bash 脚本，用 `curl` 直接调用 LLM API，无需 CodeBuddy 或其他框架。

### 前提

- 有任意一个 LLM 的 API Key（Anthropic / OpenAI / 兼容 OpenAI 的端点）
- 设置环境变量：`export LLM_API_KEY=sk-xxx`

### 用法

```bash
# Anthropic
./run-loop.sh --api anthropic --model claude-sonnet-4-20250514

# OpenAI
./run-loop.sh --api openai --model gpt-4o

# 自定义端点（兼容 OpenAI 的 API）
./run-loop.sh --api openai --base-url https://your-endpoint/v1

# 指定项目路径（默认当前目录）
./run-loop.sh --project /path/to/my-project
```

### Runner 做了什么

1. 读 `project/project-spec.md` 获取项目信息
2. 读 `scenes/` 匹配状态为 pending 的场景
3. 将 `agents/planner.md` + 项目状态 → API → 产出 `memory/loop-plan.md`
4. 将 `agents/builder.md` + plan → API → 执行修改 + 产出 `memory/loop-builder-output.md`
5. 将 `agents/reviewer.md` + plan + output → API → 产出 `memory/loop-review-result.md`
6. 读结论：PASS → 下一个 case；FAIL → 重试或升级
7. 每 N 次 checkpoint 后暂停，等待用户确认

---

## Obsidian 集成

所有 memory 文件是标准 markdown + YAML frontmatter，可以**直接在 Obsidian 中管理**。

### 打开方式

```bash
# 方案 A：将 .codebuddy 设为独立 vault
# Obsidian → 打开本地文件夹 → 选择 .codebuddy/

# 方案 B：符号链接到已有 vault
ln -s /path/to/project/.codebuddy/memory ~/my-vault/agent-loop
```

### Obsidian 能做什么

| 功能 | 用法 |
|------|------|
| **Graph View** | `Ctrl+G` 查看 runtime-spec / loop-state / lessons-learned 之间的关联 |
| **标签筛选** | 侧边栏点击 `#state` / `#runtime` / `#lessons` 快速定位 |
| **双向链接** | `[[runtime-spec.md]]` 引用跨文件跳转 |
| **Dashboard** | 打开 `memory/dashboard.md` 总览全部 |
| **属性面板** | `Cmd+;` 编辑 frontmatter 的 tags / aliases |
| **模板** | 创建新 lessons 时从已有记录复制 |

### 已标记的标签

```
#runtime       #state      #lessons
#contract      #queue      #knowledge
#checkpoint    #history    #experience
#dashboard     #index      #overview
```

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **生成-评估分离** | Builder 和 Reviewer 永远是不同角色，消除自我评估偏差 |
| **文件通信** | Agent 间通过文件交接，跨 session 持久化，失败可回溯 |
| **只读 Planner** | 规划阶段不开始改代码 |
| **骨架/项目分离** | 换项目 = 改 `project-spec.md` + `scenes/`，骨架一字不动 |
| **上下文重置** | 每轮 spawn 新 Agent，不带历史上下文（避免污染） |
| **强制暂停** | Checkpoint 必须用户签字才能继续，AI 不自动推进 |
| **多维度完成** | 日志/配置/稳定性/性能各自独立验证，不听推断 |
| **分级测试** | 简单函数不强制写测试，降低框架摩擦 |
| **迭代熔断** | 单 case 最多退回 3 次，超限升级给人 |
| **执行前快照** | Builder 动代码前 `git stash create`，偏离时可回滚 |
| **Ponytail 决策阶梯** | Builder 每次编码前爬 7 级阶梯（YAGNI→复用→stdlib→原生→依赖→一行→最少），代码量 -54%，安全 100% |
