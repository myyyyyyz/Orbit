---
name: user-reviewer
description: >
  UX 审查 Skill。使用多模态模型 + 截图工具，
  从用户视角和设计师视角审查前端实现质量。
  包含退避协议：同一问题 2 轮修不好升级给人。
type: skill
---

# User Reviewer — UX 审查 Skill

> 本 Skill 被 User Agent（`agents/user.md`）加载使用。
> 提供截图 SOP、检查清单和退避协议。

---

## 1. 截图 SOP

```yaml
screenshot_procedure:
  tool: "agent-browser | playwright-cli"

  must_capture:
    full_page:
      - "桌面端视口（1920x1080）"
      - "移动端视口（375x812）"
    key_interactions:
      - "导航/菜单展开状态"
      - "表单填写状态（含校验错误）"
      - "模态框/弹窗"
      - "加载中/空数据/错误状态"
    edge_cases:
      - "超长文本截断"
      - "特殊字符渲染"
      - "暗色模式（如项目支持）"

  output:
    directory: ".codebuddy/screenshots/{task_id}/"
    naming: "{viewport}_{component}_{state}.png"
```

---

## 2. UX 检查清单

### 用户视角

| ID | 检查项 | 严重度 | 参考标准 |
|----|--------|--------|----------|
| U01 | 核心操作路径 ≤ 3 步完成 | high | Nielsen Usability Heuristics |
| U02 | 重要信息一屏可见（无需滚动） | medium | Above the fold 原则 |
| U03 | 按钮/链接的点击区域 ≥ 44x44px | medium | WCAG 2.1 (mobile) |
| U04 | 文字对比度 ≥ 4.5:1（正文） | high | WCAG AA |
| U05 | 表单有清晰的 label 和错误提示 | high | 表单 UX 最佳实践 |
| U06 | 加载状态有视觉反馈 | medium | UX 反馈原则 |
| U07 | 空状态有引导文案（非空白页） | medium | Empty state design |
| U08 | 404/500 错误页有返回路径 | low | Error page design |

### 设计师视角

| ID | 检查项 | 严重度 | 参考标准 |
|----|--------|--------|----------|
| D01 | 间距系统统一（8px 倍数或一致基准） | high | Design system spacing |
| D02 | 字体层级分明（≤ 4 级字号） | medium | Typography hierarchy |
| D03 | 颜色使用符合设计系统 | high | Design token 一致性 |
| D04 | 组件状态完整（hover/active/disabled/loading/empty） | high | Component spec |
| D05 | 无布局溢出（flex/grid 未 wrap 导致） | high | CSS layout 审查 |
| D06 | 动画流畅（≥ 30fps，无 jank） | medium | 60fps rendering |
| D07 | 响应式断点正确（无中间态坏掉） | high | Responsive breakpoints |
| D08 | 暗色模式色彩映射正确 | medium | Dark mode conversion |

---

## 3. 退避协议

```yaml
escalation:
  max_retry: 2                  # 同一 UX 问题最多重试 2 轮
  tracking_key: "{issue_id}_{checkpoint_id}"

  on_second_consecutive_fail:
    signal: UX_ESCALATE
    controller_action:
      - "暂停 Agent Loop"
      - "输出 FAIL 报告到用户"
      - "报告包含："
        - "问题截图（标注区域）"
        - "代码位置：文件路径 + 行号范围"
        - "根因：这段代码为什么导致 UX 问题"
        - "建议方向（非必须，可选）"
    user_options:
      - "继续修（手动指定方向）"
      - "接受现状（创建 debt ticket）"
      - "调整 spec（降级或移除该检查项）"
```

---

## 4. 输出格式（loop-user-review.md）

```yaml
format_spec:
  header:
    task_id: "{task_id}"
    scene: "{scene_name}"
    model: "{用户选择的多模态模型}"
    timestamp: "{ISO 8601}"
    screenshot_dir: ".codebuddy/screenshots/{task_id}/"

  summary:
    user_perspective_pass_rate: "{X}/{Y}"
    designer_perspective_pass_rate: "{X}/{Y}"
    overall: PASS | FAIL

  issues:
    - id: "{U01 | D01}"
      perspective: "user | designer"
      description: "{一句话}"
      severity: "critical | high | medium | low"
      screenshot: "{截图文件名}"
      code_locations:
        - file: "{路径}"
          line_range: "{起始-结束}"
          reason: "{为什么这段代码导致问题}"
      fix_suggestion: "{可选}"

  escalation:
    is_escalation: false | true
    retry_count: "{本轮次数}"
    previous_attempts: "[{历史记录}]"
```

---

## 5. 专业前端知识注入

User Agent 加载本 Skill 后自动获得以下前端知识上下文：

- **CSS 盒模型**：margin/border/padding/content 边界识别
- **Flexbox/Grid**：对齐、溢出、wrap 行为判断
- **响应式设计**：breakpoint、viewport、media query 审查
- **WCAG 2.1 AA**：对比度、可聚焦、语义化 HTML、ARIA
- **设计系统**：token 一致性（颜色/间距/字体/圆角/阴影）
- **性能渲染**：CLS（布局偏移）、FOUC（闪烁）、jank 识别
- **组件边界**：React/Vue 组件边界、props 传递、状态驱动 UI
- **跨浏览器**：常见兼容性问题（Safari flex gap、iOS scroll 等）
