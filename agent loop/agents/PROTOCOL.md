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

---

## 未来扩展：从文件通信到消息队列

当前 Agent 间通过 `memory/loop-*.md` 文件通信，适合单机部署。当需要多机并行运行不同 Agent 时，有以下升级路径：

### 阶段 1：Redis Pub/Sub（分布式文件替代）

将 `memory/` 目录内容替换为 Redis 键值存储：

```
memory/loop-plan.md         → redis GET orbit:{task_id}:plan
memory/loop-builder-output.md → redis GET orbit:{task_id}:builder_output
memory/loop-review-result.md → redis GET orbit:{task_id}:review
memory/loop-state.md         → redis GET orbit:{task_id}:state
```

- **优点**：改动最小，保持架构语义不变；支持多机共享
- **实现**：`run-loop.sh` 中的 `cat` / `echo` → `redis-cli GET/SET`
- **适合**：2-5 台机器的小规模分布式部署

### 阶段 2：NATS / RabbitMQ 事件驱动（异步 Agent 调度）

以任务为事件驱动 Agent 生命周期：

```
计划完成 → AgentOrchestrator.PlanCompleted Event
  → Builder Agent 订阅 → 生成代码 → Builder.OutputReady Event
    → Reviewer Agent 订阅 → 审查 → Reviewer.Verdict Event
      → Controller 根据判决决定继续/退回/升级
```

- **优点**：解耦 Agent 生命周期，支持动态扩缩；失败自动重试
- **实现**：用 Python `asyncio` + `nats-py` 替换 bash 脚本编排
- **适合**：10+ 台机器、多个任务并行的中大型部署

### 阶段 3：Temporal / Cadence（工作流引擎）

以 Durable Execution 引擎管理整个 Agent Loop 状态机：

```
Workflow: CodeReviewLoop
  ├─ Activity: PlanTask
  ├─ Activity: BuildTask
  ├─ Activity: ReviewTask
  └─ Signal: UserApproval
```

- **优点**：自动重试、超时管理、断点恢复、可观测性内建
- **实现**：将 `run-loop.sh` 逻辑翻译为 Temporal Workflow
- **适合**：企业级部署，需要 SLA 保障

### 迁移建议

1. **先保持文件协议**：当前项目规模，文件通信足够
2. **引入 `PROJECT_DIR` 配置**：已在 `run-loop.sh` 中支持 `--project` 参数
3. **MAX_ITER 可配置**：通过 `--max-iter N` 或 `MAX_ITER` 环境变量调整
4. **结构保持**：无论后端是文件/Redis/Temporal，`loop-plan.md`、`loop-builder-output.md`、`loop-review-result.md` 的语义不变
5. **安全**：始终从 `LLM_API_KEY` 环境变量读取密钥，不传命令行参数
