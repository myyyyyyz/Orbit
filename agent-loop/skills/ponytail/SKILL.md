---
name: ponytail
description: >
  让 Builder Agent 像最懒的资深开发者一样思考。强制走决策阶梯：
  YAGNI → 已有代码 → 标准库 → 原生 → 已安装依赖 → 一行 → 最少代码。
  代码量减少 ~54%，token 减少 ~22%，安全 100% 保持。
type: skill
license: MIT
source: https://github.com/DietrichGebert/ponytail (61k stars)
---

# Ponytail — 懒惰资深开发者模式

> 最好的代码是从未写过的代码。

## Agent Loop 集成点

本 skill 被 **Builder Agent** 在编码时加载，**Reviewer Agent** 在审查时加载。

### Builder 使用方式

Builder 收到 Plan 中的每个代码修改步骤后，先走决策阶梯再动手：

```
收到任务 → 理解问题（读代码、追踪流程）→ 爬决策阶梯 → 写入 ponytail: 注释 → 输出
```

### Reviewer 使用方式

Reviewer 在所有验证阶段完成后，额外增加一个"过度工程检测"pass：
- 新引入的抽象层是否只有一个实现？
- 新加的依赖是否可以用 stdlib/原生功能替代？
- 手写代码是否重复了标准库能力？

---

## 决策阶梯

```
1. 这需要存在吗？               → YAGNI → 跳过
2. 代码库里已经有了？            → 复用
3. 标准库能做？                 → 用 stdlib
4. 原生平台功能能覆盖？          → 用原生（<input type="date"> / CSS / DB constraint）
5. 已安装的依赖能解决？          → 用它，不加新依赖
6. 能一行搞定？                 → 就一行
7. 都不行：满足需求的最少代码
```

**Bug 修复 = 根因修复，非症状修复**。搜遍所有调用方，在共享函数里修一次。

## 强度级别

| 级别 | 行为 |
|------|------|
| **lite** | 按要求构建，但用一行指出更懒的方案 |
| **full**（默认）| 阶梯强制执行，最短 diff + 最短解释 |
| **ultra** | YAGNI 极端主义，删除优先，一行搞定 + 质疑需求 |

Agent Loop 默认使用 **full** 级别。

## 核心文件

- `AGENTS.md` — 通用 agent 规则（被 Copilot/CodeWhale 等直接读取）
- `skills/ponytail/SKILL.md` — Builder 用，决策阶梯 + 输出 + 强度控制
- `skills/ponytail-review/SKILL.md` — Reviewer 用，过度工程审查
