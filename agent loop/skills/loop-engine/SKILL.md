---
name: loop-engine
description: 调度 Planner→Builder→Reviewer 三个 sub-agent 协作完成 Loop 任务。声明式调度，按 scene manifest 的 trigger/verify/fallback 规则运行。强制 Discovery + Validation Hook，checkpoint 必须用户签字。
type: harness
---

# Loop Engine — 声明式调度器（v3）

> **v3 核心变化**（vs v2）：
> 1. 全局硬约束从"10 小时 / `--limit 3`"改为**读 `project_spec.effort_tier` 三档**（quick_check / dev / full）
> 2. 增加**强制 Discovery Hook**（Phase 0）+ **Validation Hook**（每个 checkpoint 后）
> 3. **checkpoint 必须用户签字**才能继续（obra mandatory workflow）
> 4. Reviewer 改为**两阶段审**（Spec Compliance + Code Quality）
> 5. 引入 `runtime_spec.findings_snapshots` 结构化注入机制（AIF Handoff BLOCKING_FINDINGS_SNAPSHOT）
> 6. ★ **多维度完成标准**：`completion_dimensions`（B 起步 + A 兜底），ALL_PASS = Gate PASS + 所有维度验证

---

## 1. 全局约束（骨架层）

```yaml
global_constraints:
  branch_safety:    # ★ 分支安全铁律
    source: project_spec.project.branch
    rules:
      - "绝不在 master/main 分支上直接改代码"
      - "Builder 动代码前必须 git branch --show-current 校验"
      - "不在主分支 → CRITICAL_FAIL，立即停止"
      - "永不 push 到 master/main"
      - "用户未指定分支 → Master 自动创建 llm-{描述}-{日期}"

  effort_tier:
    source: project_spec.effort_tier
    rule: "quick_check/dev 可自决，full 必须 checkpoint 签字"
  
  forbidden_paths:
    source: project_spec.forbidden_paths.hard
    rule: "Planner / Builder / Reviewer 触碰即 CRITICAL_FAIL"
  
  methodology_must_read:
    - docs/dev/BUG_HUNTING_METHODOLOGY.md    # L1-L4
    - docs/dev/function_node_testing_methodology.md    # 小点测试 + AST
    - .codebuddy/memory/lessons-learned.md    # L-001/L-002
  
  two_stage_review:    # obra 核心
    stage_1: Spec Compliance（任务 A 验收 + 任务 B 信号 + 任务 B' 回填）
    stage_2: Code Quality（任务 C 方法论 + 任务 D 拿不准上交）
  
  grounding_layer:    # Spec Kit Agents 论文
    discovery_hook: Phase 0    # 每 phase 前的只读探针
    validation_hook: 每个 checkpoint 后    # 机械校验，不允许"看着对"
  
  completion_dimensions:    # 多维度完成标准
    source: project_spec.completion_dimensions
    rule: "ALL_PASS = 所有 Gate PASS + 所有 dimension 已验证"
    rule: "缺维度覆盖 → 退回 Planner 补 Gate"
    rule: "维度有覆盖但无证据 → 退回 Reviewer 重审"
    rule: "critical 维度缺覆盖 → CRITICAL_FAIL"

  iteration_limit:    # ★ 防死循环
    max_per_case: 3              # 单个 case 内 Planner→Builder→Reviewer 退回最多 3 次
    counter: "loop-state.md → current_task.iteration_count"
    on_exceed: "CRITICAL_FAIL — 升级给人，输出退回历史摘要"
```

**禁止在骨架层硬编码任何项目专属内容**（如 `--limit 3`、`recall/fp_rate`、`10 小时`）——这是 v3 根本规则。

---

## 2. 调度规则

### 步骤 0：Master Bootstrap（仅项目冷启动）

> **触发条件**：`project-spec.md` 包含 `<待定>` 占位符。
> **机制**：在进入标准 Loop 前，先与用户对齐需求，填满所有占位符。

```yaml
master_bootstrap:
  trigger: "grep '<待定>' project/project-spec.md 有结果"

  actions:
    1. "通知用户：'检测到 project-spec.md 有待定项，需要先对齐需求'"
    2. "加载 agents/master.md，启动 Master Agent"
    3. "Master Agent 按以下流程执行："
       - "阶段 A：读取现状，列出所有 <待定> 占位符"
       - "阶段 B：调用 master skill 搜索最佳实践"
       - "阶段 C：逐占位符与用户迭代对话，填满 spec"
       - "阶段 D：产出完整 project-spec.md / scenes / runtime-spec.md / loop-state.md"
    4. "用户说'开始写代码'后，Master Agent 收敛退出"
    5. "Controller 继续进入步骤 1"

  forbid: "未填满 <待定> 直接跳到步骤 1"
  forbid: "Master Agent 自行判定'差不多了'就启动 Loop"
```

---

### 步骤 1：读状态
读 `.codebuddy/memory/loop-state.md`

### 步骤 2：确定场景
扫描 `.codebuddy/scenes/` 下所有场景 manifest，匹配 loop-state.md 中 status=pending 的任务。

### 步骤 3：Phase 0（强制 Discovery Hook）

> **来源**：Spec Kit Agents 论文的 Phase-Scoped Context-Grounding Layer（arXiv:2604.05278）。
> **机制**：每个 phase 前必须做的"只读探针"，**AI 跳不过**。

```yaml
phase_0_actions:
  must_do:
    - 读 project-spec.md → 确定 effort_tier / 禁止触碰 / 必读沉淀 / completion_dimensions
    - 读 scene manifest → 触发条件 / Gate / 变更范围
    - **强制问用户三问（Q1-Q3）**：
        Q1: contract.acceptance 可测量吗？（每条都要 metric + threshold）
        Q2: 有哪些脚本不报错但人能看出的隐藏问题？（转化为 signal_id + check_method）
        Q3: 已知坑 / 边界 case？（转化为 acceptance 或 signal）
    - 读 completion_dimensions.dimensions，检查本轮任务是否覆盖所有维度
    - 如果本轮任务无法覆盖某维度 → 标注"延后验证"，写入 runtime-spec
    - 把答案写入 runtime-spec.md（第 1/2/3 节）
  
  forbid: "loop 不允许跳过 Phase 0 直接开干"
  forbid: "loop 不允许凭空补'用户没说但我觉得应该有'的字段"
```

**如果用户没填 Q2 / Q3**：
- 明确告知"spec 不完整，需要你补充"
- **不**自动补，等用户回答再继续

### 步骤 4：Spawn Planner（只读）

```yaml
task:
  subagent_name: planner
  description: 规划本轮执行
  prompt: |
    ## 当前状态
    {loop-state.md 内容}

    ## 场景定义
    {匹配到的 scene manifest 内容}

    ## 项目约束
    {project-spec.md 的关键约束：effort_tier / 禁止触碰 / 必读沉淀}

    ## 任务契约
    {runtime-spec.md 第 1 节 contract}

    ## 必读沉淀
    {L-001/L-002 等 lessons}

    ## 你的任务
    产出执行计划写入 .codebuddy/memory/loop-plan.md
```

### 步骤 5：Controller 抽查（审证据）

读 loop-plan.md，检查：
- `project.branch` 是否已确认（非 `<待定>`、非空）？（未确认 → 拒绝，回到 Master）
- 禁止触碰是否和 `project_spec.forbidden_paths.hard` 一致？（不一致 → 拒绝）
- Gate 是否每条可执行？（无 → 拒绝）
- 变更范围是否在场景定义内？（超出 → 拒绝）
- effort_tier 是否被保留（不被偷偷改成 full）？
- **维度覆盖**：每条 `completion_dimensions.dimensions` 是否至少被一条 Gate 覆盖？缺覆盖 → 退回 Planner 补 Gate
- **非产物维度**：日志/配置/稳定性等维度是否有独立验证 Gate（不依赖产物推断）？无 → 退回 Planner 补
- **★ 影响面分析**：计划涉及任何标识符修改（函数名/类型名/类名/变量名）时，是否已产出影响面分析？缺 → 退回 Planner 补充
- **★ [待确认] 处理**：影响面分析中每个 [待确认] 是否有对应处理策略（作为验证 Gate / 标注风险接受 / 询问用户）？未处理 → 退回 Planner
- **★ 测试分级合理性**：代码修改步骤是否标注了 test_level？skip/smoke 的理由是否成立？不合理 → 退回 Planner 修正

### 步骤 6：Spawn Builder

```yaml
task:
  subagent_name: builder
  description: 按计划执行修改
  prompt: |
    ## 执行计划
    {loop-plan.md 内容}

    ## 项目约束
    {project-spec.md 关键约束}

    ## effort_tier
    {runtime-spec.md 第 3 节}

    ## 必读沉淀
    {L-001/L-002}

    ## 你的任务
    严格按计划执行，写入 .codebuddy/memory/loop-builder-output.md
```

### 步骤 7：Spawn Reviewer（两阶段 + 重构影响面）

```yaml
task:
  subagent_name: reviewer
  description: 两阶段验证 Builder 输出（含维度覆盖 + 重构影响面）
  prompt: |
    ## 验证标准
    {loop-plan.md 的 Gate 章节 + 维度覆盖矩阵 + ★ 影响面分析}

    ## Builder 做了什么
    {loop-builder-output.md 内容（含 Plan 偏离章节）}

    ## 项目约束
    {project-spec.md}

    ## 完成维度
    {project-spec.md completion_dimensions.dimensions}

    ## 任务契约
    {runtime-spec.md 第 1 节}

    ## AI 看不见信号清单
    {runtime-spec.md 第 2 节}

    ## 待检查的 findings（checkpoint 回填，结构化注入）
    {runtime-spec.md 第 4 节 unresolved 部分，注入到 prompt header}

    ## 你的任务
    四部分审：
    Stage 0.5: 维度覆盖检查（逐 dimension 验证有 Gate 覆盖 + 有独立证据）
    Stage 0.6: ★ 重构影响面验证（涉及标识符变更时强制执行 — 调用方类型检查/测试回归/隐式依赖/Plan 偏离）
    Stage 1: Spec Compliance（任务 A 逐条 acceptance + 任务 B 逐 signal_id + 任务 B' 逐 snapshot_id）
    Stage 2: Code Quality（任务 C 方法论遵循 + 任务 D 拿不准上交）
    写入 .codebuddy/memory/loop-review-result.md
```

### 步骤 7.5：Spawn User Agent（仅前端/全栈场景）

> **触发条件**：步骤 7 Reviewer 输出 ALL_PASS **且** scene.type 为 `frontend` 或 `fullstack`。
> **机制**：代码通过后，从用户和设计师视角审查前端 UX 质量。

```yaml
user_agent:
  trigger:
    - "步骤 7 Reviewer 结论为 ALL_PASS"
    - "scene.type == 'frontend' OR scene.type == 'fullstack'"
  skip_if: "scene.type == 'backend'"    # 后端项目直接跳到步骤 8

  pre_spawn:
    dev_server_check:
      rule: "User Agent 截图依赖运行中的 dev server"
      steps:
        - "读取 scene manifest 的 dev_server.start_command / dev_server.url / dev_server.health_check"
        - "如已定义：Controller 执行 start_command 启动 dev server，轮询 health_check 直到通过或超时"
        - "如未定义：询问用户 'UX 审查需要 dev server 运行，请提供启动命令，或确认跳过 UX 审查'"
        - "dev server 启动失败或超时 → 跳过 User Agent，标记 [UX_SKIPPED: dev server unavailable]"
    model_selection: "ask_user"
    prompt_to_user: "代码审查已通过。是否需要进行前端 UX 审查？请选择多模态模型：{列出可用模型}"

  spawn:
    subagent_name: user-agent
    description: UX 审查（用户视角 + 设计师视角）
    prompt: |
      ## 本轮目标
      {loop-plan.md 内容}

      ## 代码审查结果
      {loop-review-result.md 内容}

      ## 场景定义
      {scene manifest 内容}

      ## 历史 UX 问题
      {loop-state.md 中本场景的 UX 失败记录}

      ## 你的任务
      1. 使用 agent-browser 或 playwright-cli 对目标页面截图
      2. 从用户视角审查（可用性/清晰度/一致性/无障碍/响应式/错误处理）
      3. 从设计师视角审查（布局/字体/颜色/组件状态/动画/极端数据）
      4. 写入 memory/loop-user-review.md
      5. 如果同一问题连续 2 轮 FAIL → 输出 UX_ESCALATE 信号
```

### 步骤 8：决策

读 loop-review-result.md 的总体结论。如果步骤 7.5 已执行，还需读 loop-user-review.md：

| 结论 | 动作 |
|------|------|
| ALL_PASS | 所有 Gate PASS + 所有 dimension 已验证 + Stage 0.6 无遗漏（如有）→ 标记任务完成，推进下一个 case |
| PARTIAL_FAIL | iteration_count +1；如超 max_per_case → CRITICAL_FAIL；否则按 scene manifest 的 Fallback 处理 |
| CRITICAL_FAIL | 暂停，输出给人 |
| DIMENSION_UNCOVERED | iteration_count +1；如超 max_per_case → CRITICAL_FAIL；否则退回 Planner 补充 Gate（不重跑 Builder） |
| IMPACT_UNVERIFIED | iteration_count +1；如超 max_per_case → CRITICAL_FAIL；否则退回 Planner 补充影响面分析 |
| UX_ESCALATE | 暂停 Loop，输出问题截图 + 代码位置 + 根因分析给人决策 |

> **★ 迭代熔断**：每次退回 Planner（DIMENSION_UNCOVERED / IMPACT_UNVERIFIED / PARTIAL_FAIL 需要重新规划时），
> Controller 递增 `loop-state.md → current_task.iteration_count`。
> 超过 `global_constraints.iteration_limit.max_per_case`（默认 3）→ 直接 CRITICAL_FAIL，
> 输出历次退回原因摘要给人，不再自动重试。

> **ALL_PASS 新定义**：仅当以下**四个条件同时满足**时才算 ALL_PASS：
> 1. 所有 Gate 全部 PASS
> 2. 每条 `completion_dimensions.dimensions` 至少被一条 Gate 覆盖
> 3. 非产物维度（日志/配置/稳定性等）有独立验证证据，不依赖产物推断
> 4. ★ Stage 0.6 重构影响面验证（如适用）：所有调用方类型检查通过 + 已有测试回归通过 + 无未处理的 Plan 偏离

### 步骤 9：Checkpoint（强制，每 N case + 必须用户签字）

> **注意**：如果步骤 8 触发 UX_ESCALATE，Checkpoint 暂停逻辑优先交给用户决策，而非常规 Checkpoint 流程。

> **来源**：obra mandatory workflow + 用户原话"每 10 个 case 停下问用户"。
> **机制**：每跑 N case（默认 10，从 `project_spec.checkpoint.interval` 读），强制暂停。

```yaml
checkpoint_protocol:
  trigger: "已完成 case_count % interval == 0"
  
  pause_actions:
    - Controller 产出一页摘要：
      * 累计 PASS/FAIL 数
      * 任务 D 拿不准的 case 列表
      * 新发现的隐藏信号（追加到 runtime-spec.ai_invisible_signals）
      * 指标趋势（是否漂移）
    - 暂停所有 sub-agent spawn
    - 把摘要呈现给用户
  
  user_signoff_required: true
  signoff_options:
    - "继续" → 进入下一个 N case
    - "调整：{说明}" → 回填新信号到 runtime-spec，回到步骤 4
    - "回退：{说明}" → 标记 CRITICAL_FAIL，输出给人
  
  forbid: "AI 不允许'看着没问题就自动继续'"
```

### 步骤 10：Validation Hook（每个 checkpoint 后强制执行）

> **来源**：Spec Kit Agents 论文的 Validation Hook。
> **机制**：在推进下一批 case 前，对 runtime-spec 整体做一次"机械校验"。

```yaml
validation_hook:
  must_check:
    - ai_invisible_signals 每条都有 check_method（不允许"看看代码"）
    - findings_snapshots[resolved=false] 都被任务 B' 检查过
    - acceptance 每条都有 metric + threshold
    - 两阶段审 evidence 非空
    - completion_dimensions.dimensions 每条在 Reviewer 报告中有独立验证证据
    - 非产物维度证据不依赖产物推断（如"产物正确 → 日志无异常"不算证据）
    - ★ 影响面分析中 [待确认] 项是否已在 Reviewer 报告中得到验证
    - ★ Builder 标注的 Plan 偏离是否已在 Reviewer Stage 0.6 中得到处理
  
  fail_action: "暂停，回退到步骤 4"
```

### 步骤 11：G9 用户最终签字（最后一道闸）

```yaml
final_signoff:
  trigger: "所有 case 跑完"
  
  actions:
    - Controller 产出最终摘要（全量指标 + 沉淀物清单）
    - 等待用户明确签字"标记完成"
    - 用户签字 → 归档 runtime-spec 到 .codebuddy/memory/archive/
    - 用户不签字 → 标记 CRITICAL_FAIL
  
  forbid: "AI 不允许'自动标记 done'——这是最后一道闸门"
```

### 步骤 12：收尾

- 更新 loop-state.md
- **触发 Logos**：调用 Logos Skill 对本次 Loop 完整对话进行总结，写入 `your-memory/YYYY-MM-DD.md`。记录：
  - 本轮任务的目标与结果
  - 关键决策与技术选型
  - Builder 遇到的技术难点与解决方案
  - Reviewer 发现的问题与修复记录
  - 灵感与收获
- **ALL_PASS 时**：删除临时文件（loop-plan.md / loop-builder-output.md / loop-review-result.md / loop-user-review.md）
- **FAIL / UX_ESCALATE / CRITICAL_FAIL 时**：将临时文件归档到 `.codebuddy/memory/archive/{task_id}/`，**不删除**——下一轮 Planner/Builder/Reviewer 需要完整上下文（上一轮 Plan 偏离、Builder 执行记录、Reviewer 证据）
- **任务最终完成**（ALL_PASS + 用户签字）后，清理对应归档目录
- runtime-spec.md 保留（供下次任务参考）
- 如果步骤 7.5 截图已保存，保留截图目录供人工复查

---

## 3. Controller 抽查规则（审证据，不重跑）

本项目评测耗时长、日志数千行，Controller **不重跑**验证命令（重跑会让主上下文被日志撑爆、成本翻倍）。改为**审证据**：

- 检查 `loop-review-result.md` 里每条 PASS 是否贴了**真实证据**：实际命令（含 effort_tier）、指标数字、文件路径
- 证据缺失 / 自相矛盾 / 指标与结论不符 → 判定 Reviewer 失职，记入 `runtime-spec.reviewer_untrusted=true`，本轮结果不可信
- 仅当证据严重存疑时，才针对**单条** Gate 抽查重跑（同样按 effort_tier）
- 连续两次发现 Reviewer 放水 → 下轮强化 Reviewer 的怀疑 prompt
- ★ **影响面抽查**：如果 Plan 涉及标识符修改，抽查 Reviewer Stage 0.6 是否验证了所有调用方
- ★ **Plan 偏离抽查**：如果 Builder 标注了偏离，抽查 Reviewer 是否读到了偏离章节并做了判断

---

## 4. 架构原则

- **生成-评估分离**：Builder 和 Reviewer 永远不是同一个 Agent
- **只读 Planner**：plan 类型 sub-agent 确保规划阶段不开始改代码
- **上下文重置**：每轮 spawn 新 sub-agent，不带历史上下文（避免污染）
- **文件通信**：Agent 间通过 state/plan/output/review 四个文件交接，跨 session 可回溯
- **Mandatory workflow**：Discovery / Validation Hook / Checkpoint 必须签字 —— 不是"建议"，是系统级约束
- **Spec-driven grounding**：所有"AI 看不见"信号显式外化，AI 按 signal_id 机械匹配
- **多维度完成**：ALL_PASS ≠ 产物正确。日志/配置/稳定性/性能等维度各自独立验证，不听推断
- **骨架/项目分离**：骨架层零项目味，换项目 = 改 `project-spec.md` + `scenes/`，骨架一字不动
- **思考先行**：Planner 必须显式声明假设、暴露 trade-off、拒绝模糊。不确认不下笔。
- **目标驱动**：每个执行步骤必须带可验证的成功标准（verify），不允许"确认功能正常"。
- **极简 + 手术式**：Builder 只写最少必要代码，不顺手重构，不格式化相邻代码。diff 每行都能追溯到 plan。
- **生成-评估分离**：Builder 不评自己的工作，Reviewer 不修发现的问题。判与做永远不同 Agent。
- **★ 影响面反幻觉**：Planner 搜索所有调用点差异 → Builder 替换前原地对比 → Reviewer 验证调用方类型/测试/隐式依赖。三道防线阻断 AI 在不确定时用概率填补空白。