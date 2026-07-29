# Agent 间通信协议

## 文件传递图

```
┌─────────────────────────────────────────────────────────┐
│                    loop-state.md                        │
│   (持久化，跨轮次)                                        │
│   - 任务队列 + 状态                                       │
│   - 历史失败记录                                          │
│   - 禁止触碰列表                                          │
│   - 连续失败计数                                          │
│   - Reviewer 准确率追踪                                   │
│                                                         │
│   读：Controller, Planner                               │
│   写：Controller                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    loop-plan.md                         │
│   (临时，本轮有效)                                        │
│   - 任务名称 + 触发原因                                    │
│   - 假设与 Trade-off（如有）                               │
│   - ★ 影响面分析（标识符 + 调用点 + [待确认]清单）          │
│   - 禁止触碰（从 state 复制）                              │
│   - 执行步骤（具体到文件级）                                │
│   - 验证 Gate（每条可执行）                                │
│   - 维度覆盖矩阵                                          │
│   - 变更范围                                              │
│                                                         │
│   写：Planner                                            │
│   读：Controller, Builder, Reviewer                     │
│   清理：Controller（本轮结束后删除）                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│               loop-builder-output.md                    │
│   (临时，本轮有效)                                        │
│   - 每条步骤做了什么                                       │
│   - 修改了哪些文件（路径 + 简述）                           │
│   - 自检：是否执行了替换前原地对比                           │
│   - 自检：是否触碰禁止目录                                  │
│   - 自检：是否超出变更范围                                  │
│   - ★ Plan 偏离（如适用）                                  │
│                                                         │
│   写：Builder                                            │
│   读：Controller, Reviewer                              │
│   清理：Controller（本轮结束后删除）                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│               loop-review-result.md                     │
│   (临时，本轮有效)                                        │
│   - 总体结论 (ALL_PASS/PARTIAL_FAIL/CRITICAL_FAIL/       │
│               DIMENSION_UNCOVERED/IMPACT_UNVERIFIED)     │
│   - 边界检查结果                                          │
│   - Stage 0.5: 维度覆盖检查                               │
│   - ★ Stage 0.6: 重构影响面验证（如适用）                  │
│   - Stage 1: Spec Compliance（任务 A+B+B'）              │
│   - Stage 2: Code Quality（任务 C+D）                    │
│   - 指标对比                                              │
│   - 如果 FAIL：失败原因 + 修复方向 + 对应 stage/signal     │
│                                                         │
│   写：Reviewer                                           │
│   读：Controller, User Agent                             │
│   清理：Controller（本轮结束后删除）                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│               loop-user-review.md                       │
│   (临时，本轮有效，仅前端/全栈场景)                         │
│   - 总体结论 (PASS/FAIL/UX_ESCALATE)                     │
│   - 用户视角审查：逐检查项 PASS/FAIL + 证据                 │
│   - 设计师视角审查：逐检查项 PASS/FAIL + 证据               │
│   - 每条 FAIL 的代码位置（文件+行号）                       │
│   - 截图路径                                              │
│   - 退避计数和升级历史                                    │
│                                                         │
│   写：User Agent                                         │
│   读：Controller                                         │
│   清理：Controller（本轮结束后删除）                        │
└─────────────────────────────────────────────────────────┘
```

## 为什么用文件而不是内存

| 方式 | 优点 | 缺点 |
|------|------|------|
| 内存传递 | 快，无 IO | 不同 session 看不到；死了就没了 |
| 文件传递 | 跨 session 持久化；失败可回溯；Controller 可抽查 | 需要读写和解析 |

Agent 各有独立 session（通过 Task 工具 spawn），它们在内存里不共享任何东西。文件是唯一的共享状态。

## 临时文件清理规则

Controller 在每轮循环结束后：
1. 读 loop-review-result.md 获取结论
2. 将结论写入 loop-state.md
3. **ALL_PASS 时**：删除 loop-plan.md / loop-builder-output.md / loop-review-result.md / loop-user-review.md
4. **FAIL / UX_ESCALATE / CRITICAL_FAIL 时**：将临时文件归档到 `.codebuddy/memory/archive/{task_id}/`，**不删除**——下一轮 Planner/Builder/Reviewer 需要完整上下文（上一轮的 Plan 偏离、Builder 执行记录、Reviewer 逐条证据）
5. **任务最终完成**（ALL_PASS + 用户签字）后，清理对应归档目录

User Agent 的截图保留在 `.codebuddy/screenshots/{task_id}/`，直到用户确认可清理。
