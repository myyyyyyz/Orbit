# AGENTS.md — Orbit 项目规范（面向任意 AI 编程工具）

> 任何 AI 编码助手（CodeBuddy / Claude Code / Gemini CLI / Codex 等）首次接触本项目时，
> 必须先读取本文件与下方"机器可读约束"。这些约束对 Orbit 自身的 Agent Loop 与外部 AI 工具一视同仁。

## 项目身份

- **Orbit（星轨）**：AI Agent 端到端系统 — 需求对齐 → 规划 → 编码 → 审查 → 交付 全流程闭环。
- 技术栈：前端 Next.js 16 + TS + Tailwind v4（`frontend/`）；后端 FastAPI + Python 3.9+（`backend/`）；
  向量库 ChromaDB + SQLite；Agent 编排自研五 Agent（`backend/app/agents/` + `agent-loop/`）。
- 架构与运行方式见 `README.md`；Agent Loop 协议见 `agent-loop/README.md`。

## 机器可读约束（改动代码前必须遵守）

| 文件 | 作用 | 何时生效 |
|------|------|---------|
| `gate.yaml` | denylist（禁止触碰路径）+ allowed_commands（命令白名单）+ test_levels（测试分层） | 每次 loop 运行前读取；Builder 落盘前机械校验 |
| `loop-constraints.md` | Push/Merge、Paths、Code、Budget、Collision、Escalation 硬约束 | 每次 loop 运行前读取；违反即中止 |
| `agent-loop/project/project-spec.md` | 项目身份 + effort_tier + completion_dimensions + forbidden_paths | 每次 loop 规划前读取 |

## 硬性规则（违反任一 → 立即停止并告知用户）

1. **禁止触碰**：`.env*`、`auth/`、`payments/`、`billing/`、`secrets/`、`certs/`、`terraform/`、
   `infrastructure/`、CI/CD 部署配置、数据库迁移。详见 `gate.yaml` denylist。
2. **分支安全**：绝不在 `master`/`main` 上直接改代码；改动前必须 `git branch --show-current` 校验。
3. **测试纪律**：修改代码后必须运行测试；禁止禁用测试或删除现有测试来让 CI 变绿。
4. **命令安全**：只允许 `gate.yaml` allowed_commands 与 orchestrator `_VERIFY_ALLOWED_BINS` 白名单内的
   验证性命令；禁止 `rm`/`mv`/`cp`/`curl`/`wget`/shell 管道/重定向。
5. **迭代熔断**：单个 case 内 Planner→Builder→Reviewer 退回最多 3 次，超限升级给人，不无限重试。
6. **人工闸门**：Checkpoint 必须用户签字才能继续；AI 不允许"看着没问题就自动继续"。
7. **生成-评估分离**：Builder 不评价自己的产出，Reviewer 不修发现的问题。
8. **可逆性**：每次 Builder 落盘必须可回滚（git worktree / git stash / effects 记录）。

## 开发约定

- 修改后端：`cd backend && python3 -m pytest test/ -q`
- 修改前端：`cd frontend && npm run lint && npm test`
- 新 Agent 能力 → 以 skill 形式放 `agent-loop/skills/`（带 frontmatter manifest，见 registry）
- 新任务场景 → 复制 `agent-loop/scenes/_template.md`

## 知识入口

- 架构总览：`README.md` → 目录结构
- Loop 编排协议：`backend/app/agents/orchestrator.py`（事件版）+ `agent-loop/skills/loop-engine/SKILL.md`（文件版）
- Schema 唯一事实源：`backend/app/agents/schemas.py`
- 安全门控实现：`backend/app/agents/gate.py`
