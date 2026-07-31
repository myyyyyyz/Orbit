---
name: scene-template
type: benchmark-scene
description: 场景模板。复制此文件创建新场景。所有 limit/耗时从 project-spec.md effort_tier 读取，不在此硬编码。
---

# {场景名称}

## 0. 对比维度声明（必填，来自 L-001）

> 本场景的核心对比维度是什么？用户会同时变化的有哪些字段？
> key / 分组 / 报告目录必须包含这些维度，否则数据会冲突或失真。

- 维度 1：{如 scan_model / review_model / prompt_id / rule_id}
- 维度 2：
- 维度 3：
- 用户自定义 label：{如 prompt-model 中的 name 字段}

## 1. 场景类型（必填）

> 决定 Loop Engine 是否启动 User Agent 进行 UX 审查。

```yaml
type: frontend | backend | fullstack
  # frontend:  纯前端项目，触发 User Agent
  # backend:   纯后端项目，跳过 User Agent
  # fullstack: 全栈项目，有前端 UI，触发 User Agent
```

## 2. Dev Server 配置（仅 frontend / fullstack 场景必填）

> User Agent 截图需要 dev server 运行。Controller 在 spawn User Agent 前自动启动。

```yaml
dev_server:
  start_command: "{如 npm run dev / python manage.py runserver}"
  url: "{如 http://localhost:3000}"
  health_check: "{如 curl -s -o /dev/null -w '%{http_code}' http://localhost:3000}"
  timeout_seconds: 30
```

---

## 3. Trigger（触发条件）

什么时候触发此场景：
- loop-state.md 中 status=pending 的 {任务类型} 任务
- 或用户显式请求 "{场景关键词}"

## 4. Verify（验证规则）

每条 Gate 包含：验证内容（可执行命令）、通过标准。

### Gate G1: {名称}
- 验证内容：
- 通过标准：

### Gate G2: {名称}
- 验证内容：
- 通过标准：

## 5. Fallback（失败处理）

| Gate 失败 | 动作 |
|-----------|------|
| G{n} FAIL | {重试次数、参数调整、升级给人} |

## 变更范围

- 允许修改的文件：
- 最大修改文件数：
- 允许的修改类型：

## effort_tier 约束

> **禁止在此硬编码 `--limit N` 或耗时**。所有评测命令的 limit 从 `project-spec.md` 的 `effort_tier` 读取：
> - `quick_check` → 秒级验证（limit 从 `effort_tier.quick_check.limit` 读）
> - `dev` → 分钟级自测（limit 从 `effort_tier.dev.limit` 读）
> - `full` → 全量验证（需用户 checkpoint 签字）
>
> Reviewer 发现 Gate 命令中硬编码了 limit 值（而非引用 effort_tier）即判 CRITICAL_FAIL。
