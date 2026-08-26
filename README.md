<div align="center">

<br/>

# 星轨 Orbit

**AI Agent 端到端系统 — 让 AI 自主完成从需求到交付的全流程**

[![Tests](https://img.shields.io/badge/tests-407%20passed-22c55e)]()
[![Frontend](https://img.shields.io/badge/frontend-36%20passed-22c55e)]()
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-3b82f6)]()
[![License](https://img.shields.io/badge/license-MIT-8195ad)]()

</div>

---

## 项目简介

**星轨（Orbit）** 是一套面向中小微企业与个人的 AI Agent 端到端系统。用户只需描述"想做什么"，AI 即可自主完成 **需求对齐 → 规划 → 编码 → 审查 → 交付** 的全流程闭环。

四大核心引擎：

| 引擎 | 能力 |
|------|------|
| **Agent Loop** | Master → Planner → Builder → Reviewer → User Agent 五角色状态机，生成-评估分离 |
| **RAG 知识引擎** | Knowledge Agent 驱动的"策略规划→执行→评测→发布"可审计闭环 |
| **智能调度** | 三级级联意图路由、语义缓存、混合存储路由、安全分类器 |
| **工程化体系** | 测试 / 认证 / 可靠性 / 交付 / 可观测性五大支柱 |

---

## 快速开始

### 方式一：Docker（推荐）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入：
#   LLM_API_KEY  — 你的模型 API Key
#   SECRET_KEY   — python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. 一键启动
docker compose up -d --build

# 3. 访问
# 前端 http://localhost:3000
# API 文档 http://localhost:8001/docs
```

数据持久化在 `orbit_data` 卷中（向量库、SQLite、上传文件、用量日志）。

### 方式二：本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
export LLM_API_KEY=sk-xxx
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 -m uvicorn app.main:app --port 8001 --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

> 服务启动时会强制校验 `LLM_API_KEY`、`SECRET_KEY`、`CORS_ORIGINS`，缺失或不安全时**拒绝启动**而非静默降级。

### 配置模型

打开 `http://localhost:3000` → 左侧 **设置** → 展开模型卡片 → 填入 API Key 与模型名。

API Key 仅存于浏览器 `localStorage`，前端通过 `X-API-Key` 请求头传给后端，后端据此调用 LLM，**不落库**。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│              Next.js 16 Frontend (:3000)                 │
│   对话 │ 知识工作台 │ 语义搜索 │ 策略配置 │ 设置        │
├─────────────────────────────────────────────────────────┤
│               FastAPI Backend (:8001)                    │
│   RAG 检索 │ LLM 生成 │ SSE 流式 │ 多租户 │ Agent Loop  │
├─────────────────────────────────────────────────────────┤
│                      数据层                              │
│   ChromaDB (HNSW 向量) │ SQLite (Alembic 迁移) │ 文件   │
├─────────────────────────────────────────────────────────┤
│                    可观测性                              │
│   structlog │ X-Request-ID │ Prometheus │ Sentry        │
└─────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
Orbit/
├── backend/                   # FastAPI 后端
│   ├── app/
│   │   ├── main.py            # 应用入口（lifespan / 中间件 / 路由注册）
│   │   ├── config.py          # RAG 四大策略 + 启动时配置校验
│   │   ├── logging_config.py  # structlog 结构化日志
│   │   ├── chunk/             # 文本切割（语义段落 + 长句重叠）
│   │   ├── embed/             # 向量化（sentence-transformers / Ollama / OpenAI）
│   │   ├── store/             # ChromaDB（多租户 Collection 隔离）
│   │   ├── search/            # 语义检索（Active Index 版本解析）
│   │   ├── cache/             # 语义缓存（Faiss 加速 + 自适应阈值）
│   │   ├── router/            # 模型路由（规则→语义→LLM 三层级联）
│   │   ├── generate/          # 非流式 RAG 生成
│   │   ├── stream/            # SSE 流式（7 阶段事件）
│   │   ├── knowledge_agent/   # 策略规划 → 执行 → 评测 → 发布
│   │   ├── agents/            # Agent Loop 编排 + 安全门控 + effects
│   │   ├── memory/            # 六层记忆金字塔
│   │   ├── multitenant/       # bcrypt + JWT + 租户隔离
│   │   ├── middleware/        # 认证 / request-id / 全局异常
│   │   ├── monitoring/        # Prometheus + Sentry（可选依赖）
│   │   └── llm/               # 客户端 + 重试 + 熔断 + Fallback
│   ├── alembic/               # 数据库迁移版本
│   ├── test/                  # 59 文件 / 407 用例
│   └── Dockerfile
│
├── frontend/                  # Next.js 16 + Tailwind v4
│   ├── src/app/               # 路由 + 设计系统（globals.css）
│   ├── src/components/        # 对话 / 知识工作台 / 侧边栏 / 设置 …
│   ├── src/lib/               # API 客户端（统一 /api/v1 前缀）
│   ├── test/ + src/**/*.test  # 36 用例
│   └── Dockerfile             # 多阶段构建（standalone）
│
├── agent-loop/                # Agent 角色定义 / 场景 / 技能 / 运行时记忆
├── knowledge/                 # 多格式测试资产 + 评测标签
├── docs/                      # 工程化与 RAG 专题文档
├── docker-compose.yml         # 一键编排
├── gate.yaml                  # Agent 安全门控（黑名单 / 命令白名单）
├── loop-constraints.md        # Loop 行为约束（预算 / 时间 / 碰撞 / 升级）
└── .env.example               # 环境变量模板
```

---

## API 端点

全部业务接口统一 `/api/v1` 前缀；`/health` 与 `/metrics` 不带版本号。

### 基础

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 深度健康检查（ChromaDB / SQLite / LLM Key） |
| `/metrics` | GET | Prometheus 指标（需 `ENABLE_PROMETHEUS=1`） |
| `/api/v1/auth/register` | POST | 注册（5 次/分钟限流） |
| `/api/v1/auth/login` | POST | 登录（5 次/分钟限流） |
| `/api/v1/auth/me` | GET | 当前用户信息 |

### 知识库

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/knowledge/upload` | POST | 上传并索引（legacy 单文件入口） |
| `/api/v1/knowledge/search` | GET | 语义搜索 |
| `/api/v1/knowledge/source` | DELETE | 按来源删除该文档全部 chunk |
| `/api/v1/knowledge/ask` | POST | RAG 问答 |
| `/api/v1/knowledge/ask/stream` | GET | SSE 流式问答 |
| `/api/v1/knowledge/strategy` | GET/PATCH | RAG 策略管理 |
| `/api/v1/knowledge/usage` | GET | Token 用量与成本估算 |
| `/api/v1/knowledge/cache/stats` | GET | 语义缓存命中率 |

### Knowledge Agent 治理流程

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/knowledge/plan-folder` | POST | 生成策略 dry-run（不写向量库） |
| `/api/v1/knowledge/imports` | POST | 创建本地文件夹导入批次 |
| `/api/v1/knowledge/imports/{id}/files` | POST | 上传单个受控相对路径文件 |
| `/api/v1/knowledge/imports/{id}/complete` | POST | 校验并冻结批次 |
| `/api/v1/knowledge/runs` | GET | 分页查询本租户 KnowledgeRun |
| `/api/v1/knowledge/runs/{id}/approve` | POST | 校验源文件未变更后批准 |
| `/api/v1/knowledge/runs/{id}/execute` | POST | 执行并写入隔离 staging |
| `/api/v1/knowledge/runs/{id}/evaluate` | POST | 离线检索评测 |
| `/api/v1/knowledge/runs/{id}/promote` | POST | 门禁通过后原子发布 |
| `/api/v1/knowledge/runs/{id}/rollback` | POST | 回滚到上一版本 |
| `/api/v1/knowledge/active-version` | GET | 查询当前活动索引版本 |

### Agent Loop

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/agents/loop` | POST | 启动 Loop |
| `/api/v1/agents/loop/pause-all` | GET/POST | 全局暂停开关（kill switch） |
| `/api/v1/agents/loop/{id}` | GET | Loop 详情 + 事件流 |
| `/api/v1/agents/loop/{id}/events` | GET | SSE 实时事件 |
| `/api/v1/agents/loop/{id}/decision` | POST | Checkpoint 决策 |
| `/api/v1/agents/schedules` | GET/POST | 定时调度管理 |

完整交互式文档：启动后访问 `http://localhost:8001/docs`。

---

## Knowledge Agent 工作流

把"上传后统一切片"升级为可审计的策略治理流程：

```
Markdown / Word / Excel / PDF
        ↓  确定性文件画像 + 有界内容证据
Knowledge Agent 推荐 RAG 策略
        ↓  策略目录校验 + 规则兜底（AI 失败不阻塞）
FolderPlan → KnowledgeRun → 人工审批（SHA-256 重校验）
        ↓  多格式 Executor → 确定性 KnowledgeChunk
按租户与 run_id 隔离的 staging collection
        ↓  Source Hit@5 / MRR / nDCG 离线评测门禁
SQLite 事务原子发布活动索引 → Search / Ask 零改动生效
        ↓  效果不佳可一键回滚上一版本
```

**已支持**：`.md` / `.docx` / `.xlsx` / `.pdf`（含扫描件 OCR 路径，需配置 OCR Adapter）。

### 使用方式

1. 登录后进入 **知识库** → 默认打开 `RAG Workbench`
2. 选择服务器 `knowledge/` 相对目录，或上传本地文件夹
3. 本地导入限制：单文件 ≤ 25 MiB，单批次 ≤ 250 MiB / 500 文件
4. 冻结后生成 dry-run，审阅 Agent 建议、规则兜底与强制复核项
5. 显式审批 → 执行隔离索引 → 离线评测（通过才可发布）
6. 发布后 Search / Ask 原子切换；必要时回滚

页面仅在 `localStorage` 保存最近 Run ID，不保存文件内容、评测报告或向量。

---

## Agent Loop

五角色通过结构化 JSON 通信，跨 session 持久化：

| Agent | 职责 | 权限 |
|-------|------|------|
| **Master** | 需求对齐，大白话 → 结构化 Spec | 一次性 |
| **Planner** | 执行计划 + 影响面分析 | 只读 |
| **Builder** | 按计划落盘代码 | 可读写 |
| **Reviewer** | 两阶段审查（Spec + Quality） | 只读 |
| **User Agent** | UX 截图审查（前端场景） | 只读 |

**五层安全护栏**：约束注入 → Gate denylist 机械拦截 → git worktree 隔离 → 命令白名单与 Shell 注入防护 → 迭代熔断与分支锁并发控制。

**六层记忆金字塔**：L0 文件记忆 → L1 会话内存 → L2 事件溯源 → L3 对话摘要 → L4 持久画像 → L5 STATE 脊柱。

---

## 工程化体系

| 支柱 | 实现 |
|------|------|
| **测试** | 407 后端 + 36 前端用例；conftest 临时目录隔离、Mock LLM 按角色路由 |
| **认证** | bcrypt(rounds=12) + JWT(HS256) + 参数化查询；可选/强制双模认证 |
| **可靠性** | tenacity 指数退避 + pybreaker 熔断 + Fallback 模型三级联动 |
| **交付** | Alembic 迁移 + Docker 多阶段构建 + GitHub Actions 三版本矩阵 CI |
| **可观测性** | structlog JSON 日志 + X-Request-ID 全链路 + Prometheus + Sentry |

详见 [`docs/engineering/`](docs/engineering/) 与 [`docs/rag/`](docs/rag/)。

---

## 环境变量

完整列表见 [`.env.example`](.env.example)。关键项：

| 变量 | 必填 | 说明 |
|------|:----:|------|
| `LLM_API_KEY` | ✅ | 模型 API Key，缺失则拒绝启动 |
| `SECRET_KEY` | ✅ | JWT 签名密钥（≥ 32 字符） |
| `CORS_ORIGINS` | ✅ | 允许的前端来源，不可用 `*` |
| `LLM_BASE_URL` | | OpenAI 兼容端点，默认 DeepSeek |
| `LLM_FALLBACK_MODEL` | | 主模型不可用时的备用模型 |
| `DATA_DIR` | | 数据根目录，Docker 内为 `/app/data` |
| `KNOWLEDGE_ROOT` | | 知识源根目录，Agent 只能在此范围规划 |
| `ENABLE_PROMETHEUS` | | 设为 `1` 开启 `/metrics` |
| `SENTRY_DSN` | | 配置后自动上报未处理异常 |

---

## 开发调试

```bash
# 后端测试
cd backend && python3 -m pytest test/ -q

# 前端测试 / 构建
cd frontend && npm test && npm run build

# RAG 问答
curl -X POST http://localhost:8001/api/v1/knowledge/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-xxx" \
  -H "X-LLM-Model: deepseek-chat" \
  -d '{"question": "hello"}'

# SSE 流式
curl -N "http://localhost:8001/api/v1/knowledge/ask/stream?q=hello" \
  -H "X-API-Key: sk-xxx"

# 离线生成策略计划（显式禁用 Agent，始终不写向量库）
curl -X POST http://localhost:8001/api/v1/knowledge/plan-folder \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"path":"fixtures","use_agent":false}'
```

审批前服务会重新扫描完整文件清单并比较 SHA-256；文件新增、删除、重命名或内容变化都会将运行标记为 `invalidated`，需重新规划。执行成功响应中的 `staging_collection` / `chunk_count` / `vector_store_writes` 仅用于审计，**不代表已发布**——只有评测通过并显式 `promote` 后 Search / Ask 才会使用该版本。

---

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | Next.js 16 · TypeScript · Tailwind v4 · Motion · Lucide |
| 后端 | FastAPI · Python 3.10+ · Pydantic v2 · Uvicorn |
| 向量库 | ChromaDB（HNSW + cosine） |
| 关系库 | SQLite + Alembic |
| Embedding | sentence-transformers / Ollama / OpenAI |
| 可靠性 | tenacity · pybreaker |
| 可观测性 | structlog · Prometheus · Sentry |
| 测试 | pytest · Vitest · Testing Library |

---

## License

MIT
