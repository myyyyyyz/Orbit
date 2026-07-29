# 如何使用这个 Agent Team

## 快速开始

在 CodeBuddy 对话中说：

```
加载 loop-engine skill，跑一次 Loop。
```

Skill 加载后自动走完 Planner → Builder → Reviewer 全流程。

## 新增场景

在 `.codebuddy/scenes/` 下创建新文件，填三个插槽：

```yaml
---
name: 新场景
type: benchmark-scene
---

## 1. Trigger（触发条件）
## 2. Verify（验证规则 + Gate 定义）
## 3. Fallback（失败处理）
```

不需要改任何 Agent 或 Skill。骨架自动读取场景 manifest。

## 手动启动 Planner

```python
Task(
  subagent_name="planner",
  description="规划 ...",
  prompt="..."
)
```

## Agent 模型配置

每个 Agent 的 frontmatter 中可指定 `model` 字段：
- `planner.md` → 默认 `inherit`（跟随当前），推荐用 `gemini-3.0-flash`（只读+快+便宜）
- `builder.md` → 默认 `inherit`
- `reviewer.md` → 默认 `inherit`

## 文件路径约定

| 用途 | 路径 |
|------|------|
| 持久状态 | `.codebuddy/memory/loop-state.md` |
| 执行计划 | `.codebuddy/memory/loop-plan.md`（临时） |
| 执行记录 | `.codebuddy/memory/loop-builder-output.md`（临时） |
| 验证报告 | `.codebuddy/memory/loop-review-result.md`（临时） |
