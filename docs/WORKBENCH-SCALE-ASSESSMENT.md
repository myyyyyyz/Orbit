# Orbit 演进评估：从「单副本 RAG 应用」到「高并发高可用的 AI 工作台」

**评估日期**：2026-09-28
**代码基线**：分支 `dev/optimize`
**目标形态**：类 WorkBuddy 的 AI 工作台（多租户、多会话、多任务并行）+ 高并发 / 高可用
**评估方式**：全仓源码通读 + 关键路径代码定位（未安装依赖、未修改业务代码）

---

## 0. 一句话结论

> **Orbit 的代码质量与安全基本功明显高于同类项目，但它的架构是「单机单进程的 RAG 应用」，不是「多租户 SaaS 工作台」。**
> 现有代码里存在 **5 类硬并发天花板** 和 **7 处进程内状态**，它们共同锁死了「副本数 = 1」。
> 要做成 WorkBuddy 那种工作台，**存储层改造（向量库服务化 + PostgreSQL + Redis）是绕不过去的前置项**，其余都是在此之上的增量。

**当前能撑多少并发（推算）**：

| 场景 | 并发上限 | 卡在哪 |
|---|---:|---|
| 非流式 `/ask` | ~40 | anyio 默认线程池 40，`def api_ask` 每请求占 1 线程直到 LLM 返回 |
| 流式 `/ask/stream` | ~40（且更糟） | 同步生成器走 `iterate_in_threadpool`，**线程被占用整个流时长（10–60s）** |
| Agent Loop SSE | 进程内队列 | 只在本进程有效，跨副本断流 |
| 写入（上传/索引/发布） | 1 | SQLite 单写者 + ChromaDB 单进程锁 |

**最危险的一条**：`/health` 是 `def`（走线程池）。当 40 个线程被 SSE 长连接占满时，**存活探针也会排队超时** → 编排器判定不健康 → 重启 → 正在跑的 Loop 全丢。这是「高并发下雪崩」的直接引信。

---

## 1. 现状盘点：已经做对的地基（不要重复造）

这块必须写清楚，否则容易把已完成的工作又排一遍期。

### 1.1 已完成的上线加固（见 `docs/PRODUCTION-READINESS.md`）

2026-09-25 那轮体检发现的 4 个 P0 已全部修复并补了回归测试：

| 原 P0 | 现状 |
|---|---|
| 全局异常处理器抛 `TypeError` | ✅ 三类 handler 统一注册 + 显式补 `X-Request-ID` |
| Fallback 复用同一 `call_fn` | ✅ 新增 `fallback_call_fn` 参数，无构造器时**如实失败**不复刻请求 |
| 流式缓存跨租户串味 | ✅ `stream/service.py:_cache_namespace()` 与租户 + 活跃索引版本绑定 |
| Agent Loop 阻塞事件循环 | ✅ `_run_verification` / `_apply_build` 已包 `asyncio.to_thread` |

### 1.2 质量确实高的部分（改造时要保住）

- **Knowledge Agent 发布流程**（`knowledge_agent/releases.py`）：`BEGIN IMMEDIATE` + `generation` 版本号 + `rowcount` CAS 校验，原子发布/回滚设计正确，是全仓最扎实的一块。
- **SQL 100% 参数化**，抽查无拼接、无 N+1。
- **SQLite 连接工厂**（`sqlite_utils.py`）：WAL + busy_timeout(15s) + synchronous=NORMAL + 外键开关，已统一。
- **调度器多副本去重**（`schedule.py`）：`db.claim_schedule()` 用 `next_run_at` 做 CAS 抢占，**多副本下已安全**，无需再改。
- **安全门控**：Gate denylist、命令白名单 + `shell=False`、路径穿越双重校验、Agent 落盘根目录白名单。
- **可观测性骨架**：structlog + `X-Request-ID` contextvars + Prometheus + Sentry 已就位。

> 结论：**不需要重写，需要在正确的地方「拆」和「外置」。**

---

## 2. 差距一：高并发 — 5 个硬瓶颈

### 🔴 H1｜线程池是隐性并发天花板（最致命）

**证据**：
- `api/knowledge.py:160` `def api_ask`（同步）→ 内部 `generate_answer` → `urllib.request.urlopen`，**整个 LLM 等待期占用 1 个线程**
- `api/knowledge.py:221` `def api_ask_stream` → `StreamingResponse(stream_ask(...))`，`stream_ask` 是**同步生成器**（`stream/service.py:49`），Starlette 用 `iterate_in_threadpool` 迭代 → **线程被占用整个流时长**
- `backend/Dockerfile` 末尾 `--workers 1`
- anyio 默认线程池上限 **40**

**后果**：第 41 个并发请求开始排队，且 `/health`、`/ready` 同为 `def`，也被卷入排队 → 探针超时 → 重启风暴。

**修法（按性价比排序）**：
1. **立刻可做**：把 `/health`、`/ready`、`/health/detail` 改成 `async def`（它们无阻塞 IO），让探针永远不被线程池卡住。1 小时，收益极高。
2. 显式配置线程池：`anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.getenv("WORKER_THREADS", "64"))`，并暴露为环境变量。
3. **根本解**：见 H2，把 LLM 调用换成 async，线程就不再是瓶颈。

---

### 🔴 H2｜LLM 调用用 `urllib`，无连接池、无并发上限

**证据**：
- `llm/client.py:82` `urllib.request.urlopen(req, timeout=timeout)`
- 全仓 8 处同步 `urllib.request.urlopen`：`retrieval/planner.py:158`、`router/llm.py:61`、`orchestrator.py:624`、`storage_router/routing.py:127`、`memory/file_memory.py:228`、`api/logos.py:80`、`executors/vision_utils.py:180`
- `requirements.txt` 里有 `httpx==0.27.2`，**却没用在 LLM 调用上**

**后果**：
- 每次调用新建 TCP + TLS 握手（无连接复用）
- 无全局并发上限 → LLM 厂商返回 429 时仍继续猛打
- 无连接池指标，无法观测在途请求数

**修法**：
```python
# 单例 AsyncClient，全局复用
_client = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    timeout=httpx.Timeout(connect=5, read=60, write=10, pool=5),
)
```
- 迁移后 `/ask` 与 `/ask/stream` 改成 `async def`，单 worker 可承载**数千**并发在途 LLM 请求（瓶颈转移到厂商限流）
- 加**并发闸门**：`asyncio.Semaphore(LLM_MAX_CONCURRENT)` + 队列深度指标，超限快速失败（429/503）而非无限堆积

---

### 🔴 H3｜单次提问串行触发 3 次 LLM 调用

**证据**（流式链路 `stream/service.py`）：
1. `:84` `plan_retrieval()` → `retrieval/planner.py:158` 同步 LLM，timeout **20s**
2. `:112` `route_model()` → 第三级 `router/llm.py:61` 同步 LLM，timeout **10s**
3. `:177` 主生成，timeout **60s**

**后果**：一个问题最长阻塞 **90s**，且前两次是"为了决定怎么问"的元调用，用户无感却付了双倍延迟和费用。

**修法**：
- 对 planner / router 结果做**短期缓存**（同一问题前缀 + 租户维度，TTL 5min）
- planner 与检索**并行**发起：先按默认计划检索，planner 返回后再决定是否补检索
- 提供 `LLM_PLANNER_ENABLED=0` 开关，高并发场景直接走确定性默认计划

---

### 🟠 H4｜Embedding 编码是 CPU 密集，且抢 GIL

**证据**：`embed/core.py` 单例 `_backend`；`api/knowledge.py:95` 用 `asyncio.to_thread(add_documents)`（已移出事件循环 ✅），但 sentence-transformers 前向推理**持有 GIL**。
默认模型 `all-MiniLM-L6-v2`，主生成任务的 tokenizer/推理穿插会让请求延迟抖动。

**修法**：
- 长期：把 embedding 抽成**独立服务**（Text Embeddings Inference / Infinity），HTTP 调用，可独立扩缩容
- 中期：批量化 + 请求合并（micro-batching），减少小请求开销
- 短期：上传/索引链路走**后台任务队列**，用户不必同步等待

---

### 🟠 H5｜`resolve_active_version` 每次请求都读库

**证据**：`search/__init__.py` → `knowledge_agent/releases.py:get_active_index()`；被 `api_knowledge.py:168`、`stream/service.py:42`（缓存 namespace）在每个请求调用。

**修法**：加 5–10s TTL 的进程内缓存，key = `(tenant_key)`，失效由 `promote/rollback` 主动清除。改动小、收益直接。

---

## 3. 差距二：高可用 — 7 处进程内状态 + 存储层

`docs/PRODUCTION-READINESS.md §3` 已承认"架构隐含单副本假设"，这里给出**逐项的断裂点与修法**。

### 🔴 S1｜`_runtimes`：Agent Loop 事件队列在进程内

**证据**：`agents/orchestrator.py:60` `_runtimes: dict[int, LoopRuntime] = {}`

**三个具体断裂点**：
1. **跨副本断流**：Loop 在副本 A 跑，SSE 连到副本 B → `get_runtime(loop_id)` 在 B 上**新建空 runtime**（`orchestrator.py:63-68`），永远收不到事件，前端卡在"进行中"。
2. **Checkpoint 永久挂起（最隐蔽）**：`agents/api.py:229` `api_loop_decision` 调 `get_runtime()` 拿到的是**本进程**的 runtime；若 loop 在另一个副本，设置的 `checkpoint_event` 唤醒的是空气 → **orchestrator 永远等待，loop 永久卡死**。
3. **重启即失联**：`asyncio.create_task(run_loop(...))`（`agents/api.py:98`）**未持有任务引用**（GC 风险），进程重启后 loop 静默消失，DB 里 `status` 卡在 `running` 无人回收。

**修法（推荐方案：Loop 执行与 API 分离）**：
- 引入**任务队列**（Arq / RQ / Celery + Redis），`POST /loop` 只投递任务 + 写 DB
- 独立 **loop-worker** 进程消费，事件写入 DB（`loop_events` 表已有）+ Redis pub/sub 广播
- SSE 端点改为「DB 游标轮询 + Redis 订阅」，天然支持**多副本、断线重连、刷新恢复**
- 补**心跳 + 超时重投**：worker 定期更新 `heartbeat_at`，超时任务标记 `failed` 并重投

---

### 🔴 S2｜其余 6 处进程内状态（统一外置 Redis）

| 状态 | 位置 | 多副本后果 | 修法 |
|---|---|---|---|
| `_revoked` 令牌撤销表 | `middleware/auth.py:86` | 副本 A 登出，副本 B 仍认旧令牌（**安全**） | Redis Set + TTL = exp |
| `_cache` 语义缓存 | `cache/storage.py:21` | 命中率降到 1/N；知识更新后其他副本仍返回旧答案 | Redis（向量部分保留本地 Faiss 或改用向量库存缓存） |
| slowapi 限流计数 | `rate_limit.py:38`（`memory://`） | 限额被放大 N 倍 | `storage_uri=redis://` |
| `_breaker` 熔断器 | `llm/retry.py:107` | 每个副本各自累计 5 次才熔断 | Redis 共享计数，或接受"每副本独立"但记录副本维度指标 |
| `_count_cache` | `search/core.py:12` | 仅统计不准，无正确性风险 | 可保留 |
| `_client` ChromaDB 单例 | `store/client.py:11` | 见 S3 | 见 S3 |

---

### 🔴 S3｜ChromaDB `PersistentClient` 锁死单进程（水平扩展的关键前置）

**证据**：`store/client.py:21` `chromadb.PersistentClient(path=...)`；`Dockerfile` `--workers 1`。

**后果**：多个 worker / 副本同时打开同一目录会产生写冲突与不一致；**无法水平扩展**，向量检索能力无法随流量增长。

**修法（三选一）**：
1. **Chroma 服务化**：`chromadb.HttpClient(host=...)` + 独立 chroma-server 容器（改动最小，保留现有 API）
2. **换 Qdrant**（推荐）：原生分布式/分片/副本，支持 payload 过滤做租户隔离，有官方 Helicone/云托管
3. 换 Milvus / Weaviate（更重，适合超大规模）

> 注意：租户隔离目前靠 `user_{id}` 分 collection（`store/client.py:36`）。数据量上来后 collection 数量会爆炸，建议改为**单 collection + tenant_id payload 过滤**。

---

### 🟠 S4｜SQLite 单写者

现状已开 WAL，读并发 OK，但**写仍串行**。Knowledge Agent 的 execute/evaluate/promote 是重写入，多租户并发导入会撞 `busy_timeout`。

**修法**：`config.py:_resolve_db_path()` 已预留 PostgreSQL 路径。迁 PG 时顺带把 **Agent Loop 表 / Memory 表纳入 Alembic**（目前 schema 事实源分裂，`alembic downgrade` 无法真正回滚全库）。

---

### 🟠 S5｜数据在 Docker 本地卷，无法多节点共享

- `docker-compose.yml:19` `orbit_data:/app/data`（含 SQLite + chroma_db + uploads）
- `./knowledge:/app/knowledge:ro`

**修法**：上传文件 → 对象存储（COS/OSS/S3）；关系数据 → 托管 PG；向量 → 独立服务。本地卷只留缓存。

---

### 🟠 S6｜SSE 无心跳、无断线重连

**证据**：`stream/sse.py:6` 只有 `event:`/`data:` 两行，**没有 `id:`、`retry:`、心跳注释行**。全仓 grep `Last-Event-ID` / `heartbeat` 零命中。

**后果**：反向代理（Nginx 默认 60s）会静默切断空闲连接；客户端断网后无法续传。

**修法**：`_sse()` 增加 `id: {seq}` 与 `retry: 3000`；每 15s 发 `: ping\n\n`；前端读取 `Last-Event-ID` 并在重连时带上，后端从该 seq 回放（`loop_events` 表已支持）。

---

### 🟠 S7｜无反向代理 / TLS / 负载均衡

`docker-compose.yml` 直接暴露 8001 / 3000。生产需 Caddy（自动 TLS）或 Nginx，并透传 `X-Forwarded-For`（配合已有的 `TRUST_PROXY_HEADERS=1`）。

---

## 4. 差距三：WorkBuddy 式工作台 — 产品能力差距

WorkBuddy 的核心形态是「**工作区 + 多会话 + 技能/连接器 + 自动化 + 产物**」。逐项对照：

| WorkBuddy 能力 | Orbit 现状 | 差距等级 |
|---|---|---|
| **多会话列表 / 服务端持久化** | ❌ `page.tsx:26` `useState<Conversation[]>`，**刷新即丢**，无服务端会话表 | 🔴 P0 |
| **工作区（Workspace）概念** | ❌ 只有 user/tenant，无「空间→资源」分组 | 🔴 P0 |
| **多用户协作 / 共享** | ❌ 无成员、无共享、无评论 | 🟠 P1 |
| **技能 / 插件 / MCP 连接器** | ⚠️ `agent-loop/skills/` 是**文件级**定义，无运行时插件宿主、无 MCP 客户端 | 🟠 P1 |
| **自动化中心** | ⚠️ `schedules` 有 CRUD + CAS 抢占，但无运行历史 UI、无失败告警、无手动重跑 | 🟠 P1 |
| **产物 / 文件管理** | ⚠️ 有 uploads + 知识库，无产物预览、版本、下载中心 | 🟡 P2 |
| **通知中心** | ❌ `orchestrator.py:74` 定义了 `NOTIFY_EVENTS` 但**无任何投递通道** | 🟡 P2 |
| **用量 / 配额 / 计费** | ⚠️ 有 `usage` 统计，无租户配额硬限制 | 🟠 P1 |
| **真正的多路由前端** | ❌ `src/app/` 只有 `layout.tsx` + `page.tsx` 单页壳，无深链、无代码分割 | 🔴 P0 |
| **服务端托管 LLM 密钥** | ❌ API Key 存 `localStorage`，每请求明文 `X-API-Key` 传输 | 🔴 P0（多人场景必改） |

### 4.1 前端架构的三个必改项

1. **引入路由**：至少 `/chat/:sessionId`、`/knowledge`、`/automations`、`/settings`；配合 Next.js App Router 做代码分割与服务端数据获取。
2. **引入数据层**：TanStack Query（缓存、失效、乐观更新、重试）+ Zustand（UI 状态）。当前 `fetch` 直调散在各组件，无法做缓存失效与多端同步。
3. **API Base 改为相对路径**：`api.ts:3` `NEXT_PUBLIC_API_URL` 是**构建期内联**的（见 `frontend/Dockerfile` 注释），换环境必须重新 build。改为 `/api` + 反向代理，一次构建多环境部署。

### 4.2 数据模型需要新增的表

```
workspaces (id, owner_id, name, created_at)
workspace_members (workspace_id, user_id, role)      # owner/admin/member/viewer
conversations (id, workspace_id, user_id, title, ...)  # 会话服务端持久化
messages (id, conversation_id, role, content, sources, model, tokens, created_at)
automation_runs (id, schedule_id, status, started_at, ended_at, error)  # 自动化运行历史
notifications (id, user_id, type, payload, read_at)
artifacts (id, workspace_id, kind, storage_key, version, ...)
tenant_quotas (tenant_id, daily_tokens, max_concurrent_loops, ...)
```

---

## 5. 分阶段路线图

> 原则：**先解除并发天花板（低成本高收益），再做存储外置（解锁水平扩展），最后叠产品能力。**

### 阶段 0 · 止血（1–2 天，立刻可做）

| # | 动作 | 涉及文件 | 收益 |
|---|---|---|---|
| 1 | 三个探针改 `async def` | `main.py:207/217/233` | 消除「SSE 占满线程池 → 探针超时 → 重启」 |
| 2 | 线程池上限可配 + 暴露指标 | `main.py` lifespan | 并发天花板从隐式变显式 |
| 3 | SSE 增加 `id:` / `retry:` / 心跳 | `stream/sse.py`、`agents/api.py` | 反代下不再静默断流 |
| 4 | `resolve_active_version` 加短 TTL 缓存 | `search/__init__.py` | 每请求省一次 SQLite 往返 |
| 5 | 把 CI 真正跑绿 | `.github/workflows/ci.yml` | 触发分支已修为 `dev/optimize` 并已生效，当前 4 个 job 全红（pytest 缺 sentence-transformers、前端 lint 未过），需逐个修红后作为后续所有改造的回归网 |

### 阶段 1 · 并发模型改造（1 周）

| # | 动作 | 收益 |
|---|---|---|
| 6 | `urllib` → 共享 `httpx.AsyncClient`（8 处调用点） | 连接复用；单 worker 并发从 ~40 → 数千 |
| 7 | `/ask`、`/ask/stream` 改 `async def` + async 生成器 | 线程不再是瓶颈 |
| 8 | 全局 LLM 并发闸门（Semaphore + 队列深度指标 + 超限 503） | 背压保护，防雪崩 |
| 9 | planner / router 结果短期缓存 + `LLM_PLANNER_ENABLED` 开关 | 单请求延迟 90s → 60s 以内，省 token |

### 阶段 2 · 存储与状态外置（2–3 周，解锁水平扩展）

| # | 动作 | 收益 |
|---|---|---|
| 10 | 引入 Redis：`_revoked`、限流计数、语义缓存、事件广播 | 副本数可 > 1 |
| 11 | ChromaDB 服务化（HttpClient）或换 Qdrant | 向量层可独立扩缩容 |
| 12 | SQLite → PostgreSQL；Agent Loop / Memory 表纳入 Alembic | 写并发 + schema 单一事实源 |
| 13 | 任务队列（Arq/RQ）+ 独立 loop-worker；SSE 改 DB 游标 + pub/sub | 修复 checkpoint 跨副本挂死；Loop 崩溃可恢复 |
| 14 | 上传文件 → 对象存储 | 多节点共享，无状态化 |
| 15 | Caddy/Nginx 反代 + TLS + `X-Forwarded-For` | 生产入口合规 |

### 阶段 3 · 工作台产品能力（3–4 周）

| # | 动作 |
|---|---|
| 16 | 会话/消息服务端持久化 + 多端同步（新增 `conversations` / `messages`） |
| 17 | Workspace 模型 + 成员角色 + 资源共享 |
| 18 | 前端迁 App Router 多路由 + TanStack Query（会话深链、乐观更新） |
| 19 | LLM 密钥服务端托管（租户级加密存储，前端不再传 `X-API-Key`） |
| 20 | 自动化中心：运行历史、手动重跑、失败告警 |
| 21 | 通知中心（接 `NOTIFY_EVENTS`） |
| 22 | 技能/连接器运行时（MCP 客户端 + 插件宿主） |
| 23 | 租户配额（日 token、并发 Loop 数）硬限制 |

### 阶段 4 · 可观测与运维闭环（持续）

| # | 动作 |
|---|---|
| 24 | Prometheus + Grafana + 告警规则（重点：线程池使用率、队列深度、LLM 在途数、P99 延迟、SSE 连接数） |
| 25 | 日志聚合（Loki/ELK），`X-Request-ID` 贯穿检索 |
| 26 | 定期备份 + 恢复演练（PG PITR + 对象存储版本化 + 向量库快照） |
| 27 | 压测基线：定义并固化「单副本 QPS / P99」指标，作为扩容依据 |

---

## 6. 目标架构

```
                    ┌──────────────────────────┐
   浏览器 ──────────▶│  Caddy (TLS / 反代 / LB)  │
                    └────────┬─────────────────┘
                    /api/*   │   /* 
              ┌──────────────┴───────────────┐
              ▼                              ▼
   ┌────────────────────┐        ┌────────────────────┐
   │  Backend  ×N       │        │  Frontend ×N       │
   │  (async, 无状态)    │        │  (Next standalone) │
   │  async httpx + 闸门 │        └────────────────────┘
   └───┬────────────┬───┘
       │            │                    ┌──────────────────┐
       │            └──── pub/sub ─────▶│  Redis            │
       │                                │  撤销表/限流/缓存  │
       │            ┌──────────────────▶│  事件广播          │
       │            │                   └──────────────────┘
       │            ▼
       │   ┌──────────────────┐        ┌──────────────────┐
       │   │  Worker ×M       │        │  任务队列          │
       │   │  Agent Loop 执行  │◀───────│  (Arq / RQ)      │
       │   │  摄入 / 评测 /    │        └──────────────────┘
       │   │  发布 / Embedding │
       │   └────────┬─────────┘
       ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐
  │PostgreSQL│ │ Qdrant / │ │ 对象存储  │ │ Embedding  │
  │(关系+任务)│ │ Chroma Svr│ │ (上传/产物)│ │  Service   │
  └──────────┘ └──────────┘ └──────────┘ └────────────┘
```

关键约束：**Backend 与 Worker 都必须是无状态的**——任何进程内可变状态都是扩展的敌人。

---

## 7. 验收指标（改完之后怎么证明有效）

| 指标 | 当前（推算） | 阶段 1 后 | 阶段 2 后 |
|---|---:|---:|---:|
| 单副本 `/ask` 并发 | ~40 | 1000+ | 1000+（受 LLM 厂商限流） |
| 单副本 SSE 并发 | ~40（占满线程） | 1000+ | 1000+ |
| P99 `/ask` 延迟 | 90s（含 planner+router） | ≤60s | ≤60s |
| 副本数 | **必须 = 1** | 必须 = 1 | **可 ≥ 3** |
| Loop 跨副本可用性 | ❌ 断流 / checkpoint 挂死 | ❌ | ✅ |
| 进程重启后 Loop | ❌ 静默丢失 | ❌ | ✅ 可恢复 |
| 探针被线程池饿死 | ❌ 会 | ✅ 不会 | ✅ 不会 |

**压测建议**：用 `locust` 或 `k6` 打 `/ask/stream`，观测 Prometheus 的线程池使用率、LLM 在途数、队列深度三条曲线，确认在饱和点之前是**排队**而不是**超时**。

---

## 8. 优先级建议（如果只能做三件事）

1. **探针改 `async def`**（1 小时）—— 消除唯一的「雪崩引信」
2. **`urllib` → 共享 `AsyncClient` + 并发闸门**（1 周）—— 并发天花板从 40 提升到千级，是本报告 ROI 最高的一项
3. **ChromaDB 服务化 + Redis 外置进程内状态**（2–3 周）—— 这是从「单机应用」变成「可水平扩展服务」的分水岭，其余所有高并发/高可用工作都依赖它

---

## 附：本次评估涉及的证据文件

| 结论 | 证据位置 |
|---|---|
| 同步端点占线程池 | `api/knowledge.py:160, 221`；`Dockerfile:--workers 1` |
| 同步生成器 → 线程池 | `stream/service.py:49`；`api/knowledge.py:231` |
| 阻塞 urllib 8 处 | `llm/client.py:82`、`retrieval/planner.py:158`、`router/llm.py:61`、`orchestrator.py:624`、`storage_router/routing.py:127`、`memory/file_memory.py:228`、`api/logos.py:80`、`executors/vision_utils.py:180` |
| 三次串行 LLM | `stream/service.py:84, 112, 177` |
| `_runtimes` 进程内 | `agents/orchestrator.py:60`；`get_runtime` 会自动新建 `:63-68` |
| checkpoint 跨副本挂死 | `agents/api.py:229` `api_loop_decision` |
| Loop 任务未持有引用 | `agents/api.py:98` `asyncio.create_task` |
| 撤销表 / 缓存 / 限流进程内 | `middleware/auth.py:86`、`cache/storage.py:21`、`rate_limit.py:38` |
| ChromaDB 单进程 | `store/client.py:21` |
| SSE 无心跳/断线重连 | `stream/sse.py:6` |
| 会话仅前端内存 | `frontend/src/app/page.tsx:26` |
| API Base 构建期内联 | `frontend/src/lib/api.ts:3`；`frontend/Dockerfile` ARG |
| 调度器已安全（无需改） | `agents/schedule.py:163` `db.claim_schedule` CAS |
| 发布原子性已正确（保持） | `knowledge_agent/releases.py:114` `BEGIN IMMEDIATE` |
