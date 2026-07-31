---
name: project-spec
description: 项目级静态 spec。恋爱情侣记录 Web 应用。骨架与项目之间的唯一接缝。
type: project-injection
---

# 恋心记录 (LoveDiary) — 项目级静态 Spec

> **职责**：本文件是**骨架与项目之间的唯一接缝**。
> - 骨架（`agents/`、`skills/loop-engine/`）从这里读约束
> - 换项目 = 改这一个文件 + `scenes/`，骨架一字不动

---

## 1. 项目身份

```yaml
project:
  name: LoveDiary
  domain: 情感记录 / 社交工具 / 生活记录
  description: 一款专为情侣设计的甜蜜记录 Web 应用，支持记录恋爱点滴、纪念日倒计时、共同回忆时间线
  owner: LoveDiary Team
  branch: master
```

---

## 2. effort_tier（替代硬编码 `--limit N`）

| 档位 | limit | 耗时预估 | 何时用 | 谁决定 |
|------|------:|---------:|--------|--------|
| **quick_check** | 5 | 秒级 | 单点验证、bug 修复确认 | Builder / Planner 自决 |
| **dev** | 20 | 分钟级 | 开发自测 | Builder / Planner 自决 |
| **full** | null（全部） | 小时级 | 全量验证 | **用户签字** |

**铁律**：
- `quick_check` / `dev` 可由 Builder / Planner 自动选择
- `full` 必须经 checkpoint 注入 → 用户明确签字才能继续

---

## 3. completion_dimensions（什么才算做完）

```yaml
completion_dimensions:
  project_type: fullstack
  dimensions:
    - dimension_id: D1
      name: 视觉还原
      description: UI 温暖浪漫，配色柔和（粉色系+暖渐变），圆角卡片+微动画，非千篇一律模板风
      check_method: 截图对比设计意图，检查配色、字体、动画
      priority: critical
      source: user_defined
    - dimension_id: D2
      name: 多端兼容
      description: 手机/平板/桌面端均正常显示
      check_method: 多视口截图验证（375px / 768px / 1440px）
      priority: critical
      source: user_defined
    - dimension_id: D3
      name: 核心功能完整
      description: 时间线、发布瞬间（含图片上传）、纪念日倒计时三大核心功能可用
      check_method: 逐功能手动测试，检查数据是否正确读写
      priority: critical
      source: user_defined
    - dimension_id: D4
      name: 数据安全
      description: 用户数据隔离，未授权不可访问他人内容；敏感信息不暴露在 URL/日志
      check_method: 无 token 请求测试、跨用户数据访问测试、日志 grep 敏感字段
      priority: critical
      source: user_defined
    - dimension_id: D5
      name: 图片上传
      description: 支持上传图片关联到瞬间，预览和存储正常
      check_method: 上传多种格式/大小图片，验证存储和回显
      priority: critical
      source: user_defined
    - dimension_id: D6
      name: 实时定位
      description: 支持获取和展示位置信息，关联到瞬间记录
      check_method: 模拟位置数据，验证存储和地图/文字展示
      priority: high
      source: user_defined
    - dimension_id: D7
      name: 前端性能
      description: 首屏加载 < 2s，操作响应 < 300ms
      check_method: Lighthouse 或手动计时
      priority: high
      source: auto_suggest
    - dimension_id: D8
      name: 状态完整性
      description: loading/empty/error/成功 所有状态正确展示
      check_method: 模拟各状态截图验证
      priority: high
      source: auto_suggest
    - dimension_id: U1
      name: 可维护性
      description: 代码结构清晰，前后端分离，有基本注释
      check_method: 代码审查
      priority: medium
      source: auto_suggest
```

---

## 4. 验证机制

```yaml
verification:
  primary_indicator:
    - 所有页面可正常加载
    - 数据增删改查正确
    - 响应式布局正常
  tests:
    path: tests/
    strategy: 手动验收测试
    pattern: "test_*.py"
```

---

## 5. 禁止触碰（隔离已有代码）

```yaml
forbidden_paths:
  hard: []
  review_only: []
  free:
    - ../mvp/lovediary/backend/
    - ../mvp/lovediary/frontend/
    - .codebuddy/
```

---

## 6. 必读沉淀（Agent 决策前必读）

| 文档 | 内容 | 何时读 |
|------|------|--------|
| `.codebuddy/memory/lessons-learned.md` | 踩坑记录 | Planner 产出 plan 前 / Builder 自检 |
| `skills/fastapi-fba/skills/fba/SKILL.md` | FastAPI 架构最佳实践 | Builder 写后端代码前 |
| `skills/frontend-design/SKILL.md` | 前端设计美学指南 | Builder 写前端代码前 |

---

## 7. Checkpoint（必须用户签字）

```yaml
checkpoint:
  interval: 1
  must_sign: true
  pause_protocol:
    - 产出一页摘要（做了什么 + 效果 + 待确认）
    - 等待用户明确回复"继续"
  forbid: "AI 不允许'看着没问题就自动继续'"
```

---

## 8. AI 看不见信号模板

```yaml
ai_invisible_signals_template:
  fields:
    - signal_id
    - desc
    - check_method
    - severity
  populate:
    initial: Phase 0 Q2
    growth: 每个 checkpoint
```

---

## 9. 失败处理（Fallback）

| 结论 | 动作 |
|------|------|
| ALL_PASS | 所有 Gate PASS + 所有 dimension 已验证 → 标记完成 |
| PARTIAL_FAIL | 退回 Builder 修复，最多 3 次 |
| CRITICAL_FAIL | 暂停，输出给人 |
