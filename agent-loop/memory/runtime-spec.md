---
name: runtime-spec
description: 任务级动态 spec。Phase 0 产出 + checkpoint 回填。本文件随任务生命周期变化。
type: runtime-contract
tags: [runtime, contract, ai-invisible-signals, checkpoint]
aliases: [Runtime Spec, 运行时契约, 任务动态契约]
---

# Runtime Spec — 当前任务的动态契约

> **来源**：Spec Kit Agents 论文的 "Phase-Scoped Context-Grounding" 层（arXiv:2604.05278）。
> **职责**：把"AI 看不见的信号"显式外化，让 Reviewer 按 signal_id 机械匹配。
> **生命周期**：任务启动 → Phase 0 初始化 → 每 checkpoint 回填 → 任务完成归档

---

## 0. 文件状态

```yaml
spec:
  task_id: {task_id}
  scene: {scene_name}          # 从 scenes/ 匹配
  created_at: {ISO 8601}
  updated_at: {ISO 8601}
  version: 1                   # 每次 checkpoint 回填 +1
  reviewer_untrusted: false    # 连续两轮放水则置 true
```

---

## 1. Contract（任务契约）

> **来源**：场景 manifest（`scenes/{scene}.md`）+ 用户 Phase 0 Q1 答案。
> **原则**：每条 `acceptance` 必须可测量（bswen blog），否则 Reviewer 无法验证。

```yaml
contract:
  input:                       # 从 scene manifest 复制
    description: "{一句话描述输入是什么}"
    fields:
      - name: {field_name}
        type: {string|int|float|list|dict}
        constraint: {可选 / 必填 / 范围}
  
  output:                      # 从 scene manifest 复制
    description: "{一句话描述输出应该是什么}"
    fields:
      - name: {field_name}
        type: {...}
        constraint: {...}
  
  acceptance:                  # 可测量验收标准（Phase 0 必填）
    - name: {acceptance_name}
      metric: {recall | fp_rate | file_exists | exit_code | ...}
      threshold: {具体的可比较值}
      baseline: {历史值或 null}
      source: {scene_manifest | user_phase0_q3}  # 追溯来源
```

---

## 2. AI 看不见信号清单（v3 核心）

> **铁律**：没写进此清单的，AI 不强行猜（猜了就是幻觉）；
> 写进此清单的，Reviewer 任务 B 必须**逐 signal_id**机械匹配，给证据，不允许"看着没问题"。

```yaml
ai_invisible_signals:
  - signal_id: S001
    desc: "{一句话描述}"
    check_method: "{grep 模式 / AST 调用 / 文件存在 / 函数返回值}"
    severity: critical|high|medium
    example: "{真实案例，可选}"
    source: {Phase0 | checkpoint_n | user_initiative}    # 追溯来源
    added_at: {ISO 8601}
  
  - signal_id: S002
    ...
```

**填充流程**：
1. Phase 0 阶段，Controller 问用户 Q2"哪些问题脚本不报错但人能看出"
2. 用户回答后，Controller 把每条转化为上述 schema 写入
3. 后续 checkpoint 你发现新问题时，**只追加不修改**（保留历史）

**初始模板来源**：`.codebuddy/project/project-spec.md` 第 7 节 `ai_invisible_signals_template`。

---

## 3. Effort Tier（本任务用哪个档）

> **来源**：`project-spec.md` 第 2 节。

```yaml
effort_tier:
  current: quick_check|dev|full
  reasoning: "{为什么选这个档}"
  limit: {5 | 20 | null}
  full_signoff_user: {user_id_or_null}    # full 时必填，否则 null
  full_signoff_at: {ISO 8601 or null}
```

---

## 4. Findings Snapshots（结构化注入，checkpoint 回填）

> **来源**：AIF Handoff 的 BLOCKING_FINDINGS_SNAPSHOT 模式。
> **机制**：你 checkpoint 暂停时说"这 10 个里我看出的问题"，不是大段散文，而是**结构化 findings ID**。
> 新一轮 Reviewer 拿到的是结构化注入（不是上下文模糊匹配）。

```yaml
findings_snapshots:
  - snapshot_id: F001                      # 自动生成 F + 序号
    severity: critical|high|medium
    case_ids:                              # 哪些 case 触发了
      - {case_id_1}
      - {case_id_2}
    signal_ref: S001                       # 关联到第 2 节的 signal_id（可空）
    desc: "{一句话}"
    discovered_at: {ISO 8601}
    discovered_in: "{checkpoint_1 | checkpoint_2 | ...}"
    resolved: false
    resolution: null                       # resolved=true 时填：{fixed_in_task: ..., verified_by: ...}
```

**消费方式**：
- 新一轮 Reviewer 启动时，从本节读 `findings_snapshots[resolved=false]` 列表
- 以 `FINDINGS_TO_CHECK` 形式注入 Reviewer prompt header
- 验证后把 `resolution` 填上

---

## 5. Reviewer 两阶段结果（obra two-stage review）

> **来源**：obra/superpowers 的 Two-Stage Review。
> Stage 1 = 事实判断（做没做）；Stage 2 = 价值判断（做得好不好）。**不要混在一起审**。

```yaml
review:
  stage_1_spec_compliance:
    A_acceptance_match:                    # 任务 A：对照 contract.acceptance
      result: PASS|FAIL
      evidence: "{逐条证据}"
    B_invisible_signals:                   # 任务 B：对照 ai_invisible_signals
      result: PASS|FAIL
      evidence: "{逐 signal_id 匹配}"
    B_prime_findings_snapshots:            # 任务 B'：checkpoint 回填的 findings
      result: PASS|FAIL
      evidence: "{逐 snapshot_id 验证}"
  
  stage_2_code_quality:
    C_methodology:                         # 任务 C：L1-L4 + 小点测试 + AST 契约
      result: PASS|FAIL
      evidence: "{方法论遵循情况}"
    D_unsure:                              # 任务 D：拿不准的 case 上交（防放水）
      case_ids: [...]
      reason: "{为什么拿不准}"
  
  overall: ALL_PASS | PARTIAL_FAIL | CRITICAL_FAIL
```

---

## 6. Checkpoint 历史

```yaml
checkpoints:
  - checkpoint_id: CP1
    triggered_at: {ISO 8601}
    case_count_so_far: 10
    summary: "{一页摘要}"
    new_signals_added: [S002, S003]        # 本轮新增的 signal
    user_signoff: pending|approved|adjust|rollback
    user_response: "{用户原话或 null}"
  
  - checkpoint_id: CP2
    ...
```

---

## 7. 升级路径

当以下情况发生，Controller 把本文件归档到 `.codebuddy/memory/archive/runtime-spec_<task_id>.md`，并清空当前文件：
- 任务完成（ALL_PASS + 用户最终签字）
- 任务失败需要重启（PARTIAL_FAIL / CRITICAL_FAIL）
- 项目切换（domain 变了）

---

## 附：填表检查清单

填本文件前，确认：
- [ ] 第 1 节 contract 全部来自场景 manifest，没凭空生成
- [ ] 第 2 节每条 signal 都有 `check_method`（不是"看看代码"）
- [ ] 第 3 节 `full_signoff_*` 字段（full 时必填，否则 null）
- [ ] 第 4 节每个 snapshot 至少关联一个 `signal_ref` 或 `case_ids`
- [ ] 第 5 节 evidence 不是空字符串
- [ ] 第 6 节 checkpoint 每次必填，包括 `user_signoff`