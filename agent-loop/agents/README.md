# Loop Agent Team — 架构总览

> 受 Anthropic Harness Design 启发：Master-Planner-Builder-Reviewer-User 五 Agent 架构
> 核心原则：**Builder 和 Reviewer 必须是两个不同的 Agent。**

## 目录结构

```
.codebuddy/
├── agents/                    ← Agent 定义（frontmatter + prompt）
│   ├── README.md             ← 本文件
│   ├── PROTOCOL.md           ← 通信协议（文件交接规则）
│   ├── master.md             ← Master Agent（冷启动需求对齐）
│   ├── planner.md            ← Planner Agent（只读，产出计划）
│   ├── builder.md            ← Builder Agent（读写，执行计划）
│   ├── reviewer.md           ← Reviewer Agent（验证 Gate）
│   └── user.md               ← User Agent（前端 UX 审查）
│
├── scenes/                   ← 场景插槽（新增场景只改这里）
│   └── _template.md          ← 场景模板
│
├── skills/
│   ├── loop-engine/
│   │   └── SKILL.md          ← Harness 调度器
│   └── user-reviewer/
│       └── SKILL.md          ← UX 审查 Skill
│
└── memory/
    └── loop-state.md         ← 持久状态
```

## Team 组成

```
Harness Skill (Controller，你加载它)
    │
    ├─→ Master Agent     (permissionMode: default，仅冷启动)
    │   职责：与用户对齐需求，将大白话翻译为结构化 Spec
    │         + B 起步：问用户"什么才算做完"
    │         + A 兜底：根据 project_type 补全遗漏维度
    │   输出：project/project-spec.md（含 completion_dimensions）+ scenes/ + runtime-spec.md
    │
    ├─→ Planner Agent     (permissionMode: plan，只读)
    │   职责：分析状态，产出执行计划 + 维度覆盖矩阵 + ★ 影响面分析
    │   输出：memory/loop-plan.md（含 Gate→维度 映射 + 标识符影响面 + [待确认]清单）
    │
    ├─→ Builder Agent     (permissionMode: default，可读写)
    │   职责：严格按计划执行，★ 替换前原地对比（禁止盲替）
    │   输入：memory/loop-plan.md（含影响面分析）
    │   输出：memory/loop-builder-output.md（含 Plan 偏离记录）
    │
    ├─→ Reviewer Agent    (permissionMode: default)
    │   职责：持怀疑态度，Stage 0.5 维度覆盖 + ★ Stage 0.6 重构影响面 + Stage 1 Spec + Stage 2 质量
    │   输入：memory/loop-plan.md + memory/loop-builder-output.md
    │   输出：memory/loop-review-result.md（含维度覆盖 + 影响面验证证据）
    │
    └─→ User Agent        (permissionMode: default，仅前端/全栈场景)
        职责：截图 + 多模态审查 UX（用户视角 + 设计师视角）
        输入：memory/loop-review-result.md + scenes/{scene}.md
        输出：memory/loop-user-review.md
```

## 文件通信协议

五个 Agent 不直接对话。通过文件交接：

```
project-spec.md        Master → Controller     "项目是什么 + 什么才算做完"
loop-plan.md           Planner → Builder       "你要做什么 + 验证哪些维度 + 影响面分析"
loop-builder-output.md Builder → Reviewer      "我做了什么 + Plan 偏离记录"
loop-review-result.md  Reviewer → Controller   "代码验证结果 + 维度覆盖 + 影响面验证证据"
loop-user-review.md    User Agent → Controller "UX 审查结果"
loop-state.md          Controller 读写          "循环状态"
```

## 场景接入成本

新增场景只需在 `.codebuddy/scenes/` 下创建一个文件，填四个插槽：

1. **type** — frontend / backend / fullstack（决定是否触发 User Agent）
2. **Trigger** — 什么时候触发
3. **Verify** — 每条 Gate 的验证命令和通过标准
4. **Fallback** — 每条 Gate 失败时的处理

其余全部由 harness 骨架自动处理。

## 关键设计决策

| 决策 | 理由 |
|------|------|
| Planner 用 plan 权限 | 只读，强制精力在分析而非动手 |
| Builder/Reviewer 分离 | 消除自我评估偏差 |
| Reviewer 被调校为"持怀疑态度" | Anthropic 发现 Agent 会盲目赞扬自己产出 |
| Master 仅冷启动触发 | 需求对齐是一次性的，后续 Loop 不需再翻译 |
| User Agent 仅前端/全栈 | 后端项目没有 UI 可审 |
| User Agent 模型由用户选 | 多模态模型能力差异大，不写死 |
| UX 退避 2 轮升级 | 防止 AI 修 Bug 死循环，决策权交还人 |
| 文件通信 | 跨 session 持久化，失败可回溯 |
| 场景插槽 | 骨架复用，新场景零代码接入 |
| Controller 抽查 | 防止 Reviewer 系统性放水 |
| **多维度完成** | ALL_PASS ≠ 产物正确。日志/配置/稳定性/性能等维度各自独立验证 |
| ★ **影响面分析** | Plan 阶段搜索所有调用点差异，阻断 AI 在不确定时做假设 |
| ★ **原地对比** | Builder 替换前对照 Plan 验证上下文，防止盲替引入 bug |
| ★ **重构影响面验证** | Reviewer Stage 0.6 验证所有调用方类型/测试/隐式依赖 |
| ★ **测试分级** | Planner 按步骤复杂度标注 test_level（full/smoke/skip），简单函数不强制写测试 |
| ★ **迭代熔断** | 单 case 内 Planner→Builder→Reviewer 退回最多 3 次，超限 CRITICAL_FAIL |
| ★ **执行前快照** | Builder 动代码前 git stash create，发现偏离可回滚到执行前状态 |
