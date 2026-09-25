# Orbit 全栈架构体检报告

**体检日期**：2026-09-25
**体检对象**：`Orbit` 全栈应用（Next.js 16 前端 + FastAPI 后端 + SQLite/ChromaDB 双库）
**代码基线**：分支 `dev/optimize`，工作区含 6 个改动文件 + 4 个未跟踪文件（PDF vision executor 开发中）
**体检方式**：静态通读 + 关键结论**实证复现**（不安装依赖、不修改业务代码）
**结论一句话**：**架构骨架与安全编码基本功明显高于普通项目，但存在 4 处 P0 级"实现与声称不符"的缺陷，其中 3 处集中在异常/降级/隔离这三条最不该出错的路径上。**

---

## 一、体检结论摘要

### 1.1 分层与工程稳健性评分

| 维度 | 评级 | 核心结论 |
|------|:----:|---------|
| 分层架构 | **B+** | 三层骨架清晰、无越界写 SQL；但 `api_ask`/`api_upload` 把业务编排写进控制器，且非流式/流式两条同源链路放置位置不对称 |
| 配置管理 | **C** | 多事实源、默认值三处不一、本地开发根本不加载 `.env`、`SECRET_KEY` 存在两套相反策略 |
| 错误处理 | **D** | 全局异常处理器**实证会抛 `TypeError` 而失效**，内含死代码分支，错误响应契约前后端不一致 |
| 日志与追踪 | **A−** | structlog + `contextvars` + `X-Request-ID` 全链路，细节到位；仅异常路径失效、CORS 缺 `expose_headers` |
| 认证 | **C+** | bcrypt(12) + JWT(HS256) 基本功扎实；但无刷新令牌、无撤销、7 天长效、令牌落 localStorage |
| 授权（RBAC） | **F** | `users.role` 字段存在但**全仓零校验**——只有认证，没有授权 |
| 数据访问 | **C+** | 参数化 SQL 极其干净、无 N+1；但 Alembic 只覆盖 3 张表、无 WAL/超时/连接池、业务层反复触发迁移 |
| 并发与异步 | **D+** | LLM 调用用 `asyncio.to_thread` **做对了**；但 `subprocess` 验证命令、文档解析、embedding 直接在事件循环里跑 |
| 实时能力 | **B−** | SSE 实现方式正确（同步生成器 → Starlette 线程池）；但无心跳/断线重连协议，线程池是隐性并发天花板 |
| 生产加固 | **C** | 有 Prometheus/Sentry/限流/Docker/深度健康检查；缺 `/ready`、优雅停机、`degraded` 状态码、后端安全头、多副本调度去重 |
| 测试 | **B** | 59 文件 / 344 个 test 函数，隔离与 Mock 到位；但**异常处理、限流、授权三条路径零覆盖** |
| 前后端集成 | **C+** | API 客户端统一、Base URL 走环境变量、`AbortController` 可取消；但零重试、无 401 处理、无离线提示、错误契约不匹配 |

### 1.2 问题分布

```
P0 ████████  4 项   阻断生产可用性或正确性
P1 ██████████████  8 项   安全、健壮性、可运维性缺口
P2 ██████  若干     分层瑕疵与工程细节
```

---

## 二、架构总览

### 2.1 三层结构（骨架正确）

```
┌──────────────────────────────────────────────────────────────────┐
│  前端  Next.js 16 + TS + Tailwind v4          frontend/src/      │
│  app/page.tsx（单页壳）  components/（9 个功能域）  lib/api.ts    │
└───────────────────────────────┬──────────────────────────────────┘
                                │ fetch + Bearer / X-API-Key / X-LLM-Model
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  控制器层  backend/app/api/*.py  +  agents/api.py    （12 个 router）│
│  仅做参数解析 / 鉴权依赖注入 / 调用服务 / 格式化响应                  │
└───────────────────────────────┬──────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  服务层（业务逻辑）                                                  │
│  stream/service.py      RAG 流式编排（缓存→规划→检索→路由→生成）      │
│  generate/service.py    RAG 非流式生成                              │
│  retrieval/planner.py   查询期自适应调度                            │
│  router/                三级级联模型路由                            │
│  knowledge_agent/       摄取治理（画像→策略→执行→评测→发布）          │
│  agents/orchestrator.py 五 Agent Loop 编排（1471 行）               │
│  memory/  cache/  llm/  embed/  chunk/  ingest/                     │
└───────────────────────────────┬──────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  仓储层                                                            │
│  knowledge_agent/repository.py  agents/db.py  multitenant/db.py    │
│  memory/db.py  store/client.py  store/documents.py                 │
└───────────────────────────────┬──────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  数据层   双库 + 双目录                                             │
│  SQLite  backend/multitenant.db   （Alembic 仅管 users/tenants/    │
│                                    sessions ③张表）                │
│  ChromaDB  <DATA_DIR>/chroma_db   （按 user_{id} 分 collection）    │
│  ⚠ 两套数据目录约定不统一（DATA_DIR 是项目根 data/）                 │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 关键运行形态

| 项 | 事实 |
|---|---|
| 并发模型 | **单进程 asyncio**；多 Loop 是事件循环上的多个任务，`_runtimes` 是进程内内存字典 |
| 阻塞 I/O 处理 | 两条不同策略：**同步 `def` 端点**由 FastAPI 丢线程池（正确）；**`async def` 端点 + 阻塞调用**会卡死事件循环（缺陷所在） |
| SSE | `stream_ask` 是**同步生成器**，Starlette 用 `iterate_in_threadpool` 迭代 → 不卡事件循环 ✅ |
| 多副本假设 | 隐含**单进程**：`_runtimes`（SSE 队列）、语义缓存、熔断器、限流计数、调度器**全部进程内** |

---

## 三、P0 级问题（4 项）

> 以下四项均已通过读源码 + 实证复现确认，非推测。

### P0-1 全局异常处理器实际失效，错误响应契约前后端不一致

**文件**：`backend/app/middleware/error_handler.py:22-67`、`backend/app/main.py:104`

**证据 A（实证复现）**：`error_handler.py:19` 取的是**标准库 logger**（`logging.getLogger(__name__)`），却在 `:36-42`、`:52-58` 用 structlog 的 kwargs 风格写日志：

```python
logger.warning("http_exception", status_code=exc.status_code, request_id=..., path=...)
```

我把这一行在 Python 3.13 实跑，结果：

```
TypeError: Logger._log() got an unexpected keyword argument 'status_code'
```

标准库 `logging` **不接受**任意结构化成对参数（只认 `exc_info`/`extra`/`stack_info`/`stacklevel`）。**handler 内部两条日志语句都会抛异常。**
对比：项目其余位置都正确使用了自研 structlog 封装（`llm/retry.py:38`、`generate/service.py:19`、`stream/service.py:29`）。

**证据 B（代码语义）**：`main.py:104` 用 `app.add_exception_handler(Exception, global_exception_handler)` 注册。Starlette 在 `build_middleware_stack` 中会把 `key in (500, Exception)` 的处理器**提升为最外层 `ServerErrorMiddleware` 的兜底 handler**，其余才交给内层 `ExceptionMiddleware`。而 FastAPI 在 `setup()` 里已为 `HTTPException` 注册了自己的默认处理器。
→ 因此 `error_handler.py:35` 的 `isinstance(exc, StarletteHTTPException)` 分支**永远不会被执行，是死代码**。

**后果链**：

1. HTTPException（400/401/404）走 FastAPI 默认格式 `{"detail": ...}` → **不含 `request_id`**；
2. 真正的未处理异常走 global handler → `logger.error(...)` 抛 `TypeError` → handler 自身崩溃 → 由 uvicorn 兜底 → 返回**非结构化 500**，`request_id` 传不回客户端；
3. 前端 `frontend/src/lib/api.ts:62-63` 只读 `error.detail` → 与后端 global handler 的 `{error, detail, request_id}` 结构**对不上**，退化为显示 `HTTP 500`；遇 FastAPI 422 时 `detail` 是**数组**，`new Error(array)` 会渲染成 `[object Object]`。

**为什么长期没被发现**：`backend/test/` 中**没有任何 error_handler / 全局异常的测试用例**（`test_main.py` 只覆盖 `/health`、`X-Request-ID`、CORS）。而异常路径失效不影响正常返回，线上表现为"偶发 500 且查不到 request_id"。

---

### P0-2 LLM Fallback 与熔断器形同虚设，且返回的 model 字段失真

**文件**：`backend/app/llm/retry.py:136-212`，调用方 `backend/app/generate/service.py:67-70`、`backend/app/stream/service.py:145-148`

**根因**：`call_llm_with_retry` 的 fallback 分支（`retry.py:203-204`）复用了**同一个 `call_fn`**：

```python
decorated_fallback = retry_decorator(_breaker_fallback.call)
result = decorated_fallback(call_fn)      # ← 还是那个 call_fn
```

而调用方传入的是已固化主模型的闭包：

```python
# generate/service.py:58-63  先用主模型+主Key构造 req
req = build_chat_request(base_url, api_key, {"model": model, ...})
# :67-70
result = call_llm_with_retry(
    call_fn=lambda: urllib.request.urlopen(req, timeout=30),
    model_name=model,
)
```

**三重后果**：

1. `LLM_FALLBACK_MODEL` / `LLM_FALLBACK_API_KEY` **只出现在日志字符串里，从未真正应用到请求** → fallback 形同虚设；
2. 主模型熔断器 open 时（`retry.py:171-177`），代码"跳到 fallback 分支"，但发出的仍是主模型的 `req` → **熔断完全不产生保护作用**，会持续打同一台已知故障端点；
3. `retry.py:206` 返回 `model_used = fallback_model`，一路透传到响应 `model` 字段（`generate/service.py:88`）→ **前端展示的模型名是假的**。

**影响面**：`POST /api/v1/knowledge/ask` 与 `GET /api/v1/knowledge/ask/stream` 两条主链路。
**佐证**：`docs/engineering/05-LLM调用可靠性.md:89-91` 描述的设计意图与实现不符——文档是设计，代码没落地。

---

### P0-3 流式问答的语义缓存跨租户串味（静默数据泄露）

**文件**：`backend/app/stream/service.py:49`（读）、`:171`（写）

```python
cached = cache_get(question)          # :49  ← 没有 namespace
...
cache_put(question, full_answer, sources, final_model)   # :171 ← 没有 namespace
```

**对照组**：非流式路径**做对了** —— `api/knowledge.py:132-135` 显式构造并传入命名空间：

```python
cache_namespace = f"{user_id}:{active_version.collection_name}"
cached = cache_get(question, namespace=cache_namespace)
```

**后果**：流式路径下所有用户共用一份缓存 key 空间。用户 B 提一个与用户 A 相似的问题，会**直接拿到 A 的答案及其 `sources` 引用**。这属于跨租户数据泄露，而且是**静默错误**——响应看起来"又快又准"，不会有任何报错。

**讽刺点**：README 与项目记忆都把"多租户隔离"列为已完成能力，`cache/` 模块也**早已支持** `namespace` 参数，只是流式调用点忘了传。

---

### P0-4 Agent Loop 阻塞事件循环，导致全局卡死

**文件**：`backend/app/agents/orchestrator.py:414-485`（`_run_verification`）、`:716-748`（`_apply_build`）；调用点 `:780`、`:1119`、`:1232`

**事实**：

- `_run_verification` 是**同步函数**，内部 `subprocess.run(..., timeout=_VERIFY_TIMEOUT, shell=False)`（`:467`），而 `_VERIFY_TIMEOUT = 30`（`:333`），且对命令列表**逐条串行**（`:439-484`）→ **最坏 30s × N 条命令**；
- 它被 `async def _execute_verification_with_approval`（`:753`）在 `:780` **直接同步调用**，没有 `await asyncio.to_thread(...)`；
- `_apply_build` 同样同步（内含 `subprocess.run(["git","-C",target,"stash","create"], timeout=10)`，`:732`），在 `:1119`、`:1232` 被直接同步调用；
- `run_loop` 是 `async def`（`:811`），运行在事件循环上。

**反差点（说明这是疏漏而非设计取向）**：同一文件对 LLM 阻塞调用**做得非常正确**——`:639`、`:922`、`:947` 全部用 `await asyncio.to_thread(...)`，文件头 `:6` 还专门写了注释：

> `- LLM 调用为阻塞 urllib，用 asyncio.to_thread 包装，避免阻塞事件循环。`

**后果**：一次 Loop 跑到验证阶段（典型如 `npm run build`、`pytest`），**整个 FastAPI 事件循环被冻结最长 90s+**，期间**所有其他用户的请求、所有 SSE 流全部停摆**。对一个主打"并发多 Loop + 实时事件流"的系统，这是最致命的一处。

---

## 四、P1 级问题（8 项）

### P1-1 认证：无刷新令牌、无撤销、7 天长效、无 RBAC

**文件**：`backend/app/middleware/auth.py:26,42-53`；`backend/alembic/versions/f7a4c3a193d7_initial_schema.py:31`

| 缺口 | 证据 |
|---|---|
| 访问令牌长效 | `auth.py:26` `ACCESS_TOKEN_EXPIRE_DAYS = 7` |
| 无刷新令牌 | 全仓 grep `refresh_token` → **零命中**；payload 无 `jti`、无 `type` 区分 |
| 无撤销机制 | `logout` 仅删前端 localStorage（`auth-context.tsx:43-48`），后端无吊销入口；令牌被盗后 **7 天内无法失效** |
| **无授权（RBAC）** | `users.role` 字段存在（迁移 `:31`）但全仓 grep `require_role\|RBAC` → **零命中**。`get_current_user` 只验签名，**所有端点对任意登录用户一视同仁** |

**最具体的风险**：管理类端点无区别保护 —— 全局 kill switch `GET/POST /api/v1/agents/loop/pause-all`、项目工具策略 `PUT /api/v1/agents/tool-policy`，任何普通注册用户都能调用。

**与规范冲突**：规范要求"访问令牌短时效 + 刷新令牌服务端存储"与"RBAC 权限控制"，两项均未实现。

### P1-2 令牌存于 localStorage

**文件**：`frontend/src/lib/api.ts:10`、`frontend/src/lib/auth-context.tsx:27,37,44`

规范明确"令牌禁止存入 localStorage，也不得放入 URL 查询参数"。当前 `orbit_token` 存 localStorage，任何 XSS 即可全量窃取一个 7 天有效的令牌。而前端安全头里**没有 CSP**（`next.config.ts:19-34` 有 X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy，**无 Content-Security-Policy**）→ XSS 防线偏薄。

**说明**：这是"无状态 Bearer"架构的必然结果，不是随手写错。要修需配合 httpOnly Cookie + CSRF 方案，或后端提供 refresh 端点并把 access token 收短。

### P1-3 前端零重试、无 401 处理、无离线提示

**文件**：`frontend/src/lib/api.ts:31-67`

| 规范要求 | 现状 |
|---|---|
| 4xx 不重试、5xx 自动重试 ≤3 次 | **无任何重试逻辑** |
| 401 自动刷新并重试 | **零实现**（全仓 grep `401` 无命中） |
| fetch 失败显示离线提示 | `request()` **无 try/catch**，网络断开抛原生 `TypeError` 给调用方 |
| API 错误映射为可读文案 | 仅 `new Error(error.detail \|\| HTTP ${status})`，且结构假设与后端不符（见 P0-1） |

**另外两处**：
- **SSE 超时语义错位**：`api.ts:136-138` 的 60s 定时器在响应头返回后立即 `clearTimeout`（`:144`）→ 实际是"建连超时"，**不约束生成时长**，与命名意图不符；
- **事件类型判定依赖巧合**：`api.ts:169` `if (data.message) onError?.(...)` 把任何带 `message` 字段的事件一律当错误。当前恰好只有 `error` 事件带该字段，但后端一旦在正常事件里加 `message` 就会误报。前端**完全忽略 `event:` 行**，只靠 payload 形状区分事件类型。

### P1-4 配置管理多事实源 + 本地开发不加载 .env

**(a) `.env` 在本地模式下根本不会被读取**
全仓 grep `load_dotenv|dotenv` 只命中 `agent-loop/` 下一个第三方 skill 文档；`requirements.txt` 也**没有** `python-dotenv`。
但 `.env.example:3` 写着"复制为 .env 后填入真实值"，README 方式二又要求 `export LLM_API_KEY=...`。**两种说法打架**：照 `.env.example` 做本地开发，`config.py:226-266` 会因 `LLM_API_KEY` 为空直接 `sys.exit(1)`。（Docker 路径没问题，compose 会注入 `.env`。）

**(b) 同一变量默认值三处不一**

| 变量 | `.env.example:15` / `docker-compose.yml:31` | `llm/retry.py:48` | `llm/client.py:14` |
|---|---|---|---|
| 主模型 | `deepseek-chat` | `deepseek-v4-pro` | `gpt-4o-mini` |

同一份代码在不同启动路径下默认模型不同，排障时极易误判。

**(c) `SECRET_KEY` 两套相反策略**
- `config.py:239-244`：长度 < 16 字符 → 收集错误，`sys.exit(1)` **拒绝启动**；
- `middleware/auth.py:28-35`：缺失 → **自造随机密钥，仅打 warning**。

且 `auth.py` 是**模块导入期**执行，其 import 发生在 `main.py:17`，**早于 lifespan 校验**。正常情况下会被后续校验拦住，但这是明确的"双重事实源 + 相反策略"。

**(d) 其他重复读取与不一致**
- `CORS_ORIGINS` 被读两遍（`config.py:247` 与 `main.py:107`）；
- `DATABASE_URL` 默认值不一致：`config.py:179-182` 是**绝对路径** `backend/multitenant.db`，`.env.example:38` 是**相对路径** `sqlite:///./multitenant.db` → **随 CWD 漂移**，从项目根启动和从 `backend/` 启动会落到不同文件。

**根因**：`config.py` 用普通 class + 散落的 `os.getenv`，**没有采用集中的类型化配置对象** —— 尽管 `requirements.txt:7` 已经装了 `pydantic-settings==2.6.0`。

### P1-5 可观测性与生命周期：health 语义、优雅停机、调度器多副本

**文件**：`backend/app/main.py:78-79,138-185`、`backend/app/agents/schedule.py:81-128,140`

- **`/health` 永远返回 200**：`main.py:178-185` 计算了 `status: degraded`，但**HTTP 状态码恒为 200** → 负载均衡 / K8s **无法据此摘流量**。且**没有 `/ready` 就绪探针**（规范要求 health + ready 两个端点）。
- **`/health` 的 `llm_api` 是伪探测**：`main.py:169-176` 只判断环境变量有没有值（注释也承认不产生真实调用），但字段名与取值是 `llm_api: ok / unreachable`，**误导运维**。
- **优雅停机缺失**：`main.py:78-79` lifespan 的 `yield` 之后只有一行日志。`agents/schedule.py:140` 定义了 `stop_scheduler()` 但**全仓无调用点**，调度任务从未被停；DB 连接、后台任务均未收尾。
- **调度器多副本重复触发**：`schedule.py:107-128` 是纯进程内 asyncio 循环，每个 worker 各跑一份，`db.get_due_schedules` **无分布式锁、无 leader 选举** → 多进程部署下**同一 schedule 被触发 N 次**。
- **cron 计算同步阻塞（实测）**：`schedule.py:81-96` 的 `compute_next_run` 从当前分钟**逐分钟线性扫描**最多 4 年。我复刻该算法实测：

  | cron 表达式 | 迭代次数 | 耗时 |
  |---|---|---|
  | `* * * * *` | 1 | 0.2 ms |
  | `0 9 * * 1` | 5,348 | 1.6 ms |
  | `0 0 1 1 *` | 140,168 | 38 ms |
  | `0 0 29 2 *` | 750,728 | 207 ms |
  | **永不匹配（如 2/31）** | **2,108,160（扫满 4 年）** | **581 ms** |

  这是**同步 CPU 占用且直接在事件循环里**，每个稀有 cron 每分钟全量卡一次。

### P1-6 上传/索引链路在 async 端点里做阻塞 CPU 工作

**文件**：`backend/app/api/knowledge.py:34-86`；`backend/app/store/documents.py:26`

`async def api_upload`（`:35`）内部串行执行三件重 CPU 工作：
- `:55` `parse_file(...)` —— 文档解析
- `:62` `chunk_text(...)` —— 文本切分
- `:67` `add_documents(...)` → `store/documents.py:26` `encode(texts)` —— **sentence-transformers 前向推理**

**对比强烈**：同文件其余端点都是 `def`（由 FastAPI 自动丢线程池，**正确**）——`:90 api_search`、`:123 api_ask`、`:183 api_ask_stream`。**唯独两个上传端点写成 `async def` 却在内部做重 CPU 工作** → 阻塞事件循环。

**附带说明（这处做得对，值得肯定）**：`stream_ask` 是**同步生成器**，Starlette 的 `StreamingResponse` 会用 `iterate_in_threadpool` 迭代它，因此其中的 `urllib` 阻塞调用**不会**卡事件循环 ✅。代价是每个并发流占用一个线程池线程（anyio 默认上限 40）→ 这是**隐性并发天花板**，不是 bug 但需知晓。

### P1-7 数据库层：无 WAL/超时、业务层反复触发迁移、注册竞态

**文件**：`backend/app/multitenant/db.py:40-47,56-64`、`backend/app/multitenant/users.py:14-23`

- **每个连接都是裸 `sqlite3.connect`**（`db.py:44-47`），且 `agents/db.py`、`memory/db.py` 各自重复实现 → **无连接池、无 WAL、无 `busy_timeout`**。SQLite 默认 journal 模式下并发写会直接抛 `database is locked`。规范要求"配置连接池、多步写入使用事务"。
- **迁移由业务函数反复触发**：`init_db()` 被 `register_user` / `login_user` / `get_user_by_id` / `save_session` / `get_session` 等**每个仓储函数**调用（`users.py:11,36,57`、`sessions.py:11,27,40`），靠模块级 `_migrated` 标记兜底（`db.py:40-41,56-64`，注释解释了历史上并发 `KeyError: 'config'` 的原因）。
  → 架构上是**业务层反向依赖基础设施初始化**；且 `_migrated` 是**进程内**标记，多 worker 各跑一次迁移。
- **注册存在 TOCTOU**：`users.py:14-23` 先 `SELECT` 查重、再 `INSERT`，两步之间**无事务**。并发注册同名用户时可能双双通过检查 → 依赖 `username TEXT UNIQUE`（迁移 `:29`）在 INSERT 时兜底抛 `IntegrityError`，但**该异常未被捕获**，会向上抛成 500。
- **Alembic 只覆盖 3 张表**：迁移文件头 `:7-8` 明说 Agent Loop 表、Memory 表**由各模块独立 init 管理**，不在 Alembic 版本管理内 → **schema 事实源分裂**，`alembic downgrade` 无法真正回滚全库。规范要求"数据库变更一律通过可回滚的迁移"，此处只做了一半。
- **SQL 质量正面评价**：我抽查 `multitenant/*`、`agents/db.py`、`knowledge_agent/repository.py`、`memory/*` —— **全部参数化，无一处字符串拼接 SQL**，也**未发现 N+1 查询**（都是单行 `fetchone` 或单条列表查询）。这块做得很好。

### P1-8 限流：能生效，但语义有隐患

> **先纠正一个容易误判的点**：我通读了 slowapi 源码确认，`@limiter.limit(...)` 装饰器走的是 `in_middleware=False` 分支，用**装饰器自己绑定的 `Limiter` 实例**判定，**不依赖 `SlowAPIMiddleware`**，也不要求与 `app.state.limiter` 同实例。因此 `api/auth.py:15,33` 的 `@limiter.limit("5/minute")` **是生效的**。（`main.py` 未注册 `SlowAPIMiddleware` 本身不构成缺陷——它只影响 `default_limits`。）

**但仍有三处隐患**：

1. **两个 Limiter 实例**：`main.py:96` 建 `limiter` 并挂到 `app.state.limiter`；`api/auth.py:11` 又建了一个独立 `limiter`。slowapi 内置的 `_rate_limit_exceeded_handler` 会用 `request.app.state.limiter` 注入响应头 → **实例不匹配，`X-RateLimit-*` 头不会正确下发**；`default_limits` 等全局能力也永远接不上。
2. **存储是进程内存**（slowapi 默认 `memory://`）→ 多 worker 下"5 次/分钟"实际变成 "5 × N 次/分钟"。
3. **key 用 `get_remote_address`**（`api/auth.py:11`）→ 部署在反向代理后若未透传 `X-Forwarded-For` 且未配 `ProxyHeadersMiddleware`，**所有请求会被识别成同一个内网 IP**，限流退化为全局限额，**误伤所有用户**。

**为什么长期没被发现**：`backend/test/conftest.py:92` 显式关闭了限流（`auth_api.limiter.enabled = False`），这条路径**零测试覆盖**。

---

## 五、P2 级问题（分层瑕疵与工程细节）

### P2-1 分层瑕疵：控制器承载业务逻辑，且两条同源链路不对称

`backend/app/api/knowledge.py:122-179` 的 `api_ask` 里塞了约 55 行业务编排：缓存读 → 检索 → 路由决策 → key/model 解析 → 生成 → 缓存写回。

对比流式路径把这些**正确地**放在服务层 `stream/service.py:stream_ask` ✅。

→ **同一件事（RAG 问答编排）存在两套放置位置**，非流式那套写在了控制器里，违反"控制器只解析请求、调用服务、格式化响应；服务层不依赖请求/响应对象"。同类问题见 `api/knowledge.py:34-72` 的 `api_upload`（落盘 → 解析 → 切分 → 入库全在控制器里）。

### P2-2 封装与工程细节

| 项 | 位置 | 说明 |
|---|---|---|
| 导入私有函数 | `main.py:156` | `from .multitenant import _get_db` 用于健康检查 → 破坏封装，应暴露 `ping()` |
| 空包文件 | `middleware/__init__.py` | 仅 1 行，包级无导出，`main.py` 只能逐子模块 import |
| 任务引用未持有 | `orchestrator.py:131` | `asyncio.create_task(_cleanup())` 不保存引用 → 任务可能被 GC 提前回收（asyncio 已知陷阱） |
| 丢弃异常头 | `error_handler.py:43-49` | 返回 HTTPException 时未带 `exc.headers` → 401 的 `WWW-Authenticate` 丢失 |
| 追踪头未暴露 | `main.py:108-119` | CORS 缺 `expose_headers=["X-Request-ID"]` → 后端贯穿的 request_id **前端读不到**（前端也确实没用） |
| 重试判定脆弱 | `llm/retry.py:66-91` | `_is_retryable` 用**异常消息子串匹配**（`if "connection" in msg`）；且 `_breaker` 是进程级单例，多 worker 各自熔断 |
| 前端错误提示 | `api.ts:62-63` | 422 时 `detail` 是数组 → 渲染成 `[object Object]` |
| 测试口径 | `README.md:9` | README 称 407 用例，我统计到 344 个 `def test_`（参数化可能解释差异，仅作口径提示） |

---

## 六、做对的地方（这份报告必须平衡呈现）

骨架性优点不是客套，它们决定了上面这些缺陷**都是可修的局部问题，而非推倒重来的架构病**：

1. **应用入口干净**：`main.py` 185 行只做组装，路由按域拆成 12 个 router，无业务逻辑。
2. **三层骨架正确**：`api/`（控制器）→ 服务层（`stream/`、`generate/`、`retrieval/`、`router/`、`knowledge_agent/`、`agents/`）→ 仓储层（`*/repository.py`、`*/db.py`）。**没有出现控制器直接写 SQL 的越界**。
3. **安全编码基本功扎实**：
   - 全仓 SQL **100% 参数化**，抽查无一处拼接；
   - 上传做 `os.path.basename` 消毒 + 类型白名单 + 大小限制（`api/knowledge.py:41-49`）；
   - 落盘有路径穿越防护，用 `os.path.realpath` + `os.path.commonpath` 双重校验（`orchestrator.py:700-713`）；
   - 命令执行 `shell=False` + 二进制黑白名单双闸 + 30s 超时 + 输出截断（`orchestrator.py:322,333,414-485`）—— Agent 自动化里最危险的一环防住了。
4. **结构化日志 + 全链路追踪完整**：`request_id.py` 用 structlog `contextvars` 绑定，`:41` 请求结束清理 context 防串号 —— 这个细节很多人会漏。
5. **可靠性骨架齐备**：tenacity 指数退避 + pybreaker 熔断 + Fallback 三级联动；`_is_retryable` 对 429/5xx/超时与 401/403/400 的区分是**正确**的（`retry.py:66-91`）。
6. **Agent Loop 的 LLM 并发处理正确**：`orchestrator.py:639,922,947` 全部 `await asyncio.to_thread(...)`，且文件头写明了理由。
7. **前端亦有安全基线**：`next.config.ts:19-34` 已配 4 个安全响应头 + `poweredByHeader: false` + 生产剔除 `console`（保留 error/warn）；SSE 用 `AbortController` 支持取消（`chat-interface.tsx:151-152`）。
8. **密码与令牌细节**：bcrypt rounds=12（`password.py:10`）；`verify_access_token` **特意不加 `lru_cache`** 并写明了安全理由（`auth.py:62-65`）—— 仓库里这类"知道自己在权衡什么"的注释不少，是成熟度的体现。

---

## 七、改进建议（按 ROI 排序）

### 第一梯队：半天内可完成，收益最高

| # | 动作 | 涉及文件 | 预估 |
|---|---|---|---|
| 1 | **修异常处理器**：`import logging` → 改用 `from ..logging_config import get_logger`；补 `RequestValidationError` 处理器；统一错误响应为 `{error, code, message, request_id}`；返回时带上 `exc.headers` | `middleware/error_handler.py` | 2h |
| 2 | **修 Fallback**：把 `call_fn` 改为接收 `(model, api_key)` 的**工厂函数**，主/备各构造一次请求；或由调用方提供 `build_fn` | `llm/retry.py` + 2 个调用点 | 3h |
| 3 | **流式缓存补 namespace**：与 `api/knowledge.py:132` 对齐 | `stream/service.py:49,171` | 15min |
| 4 | **验证命令下线程池**：`_run_verification` / `_apply_build` 调用点包 `await asyncio.to_thread(...)` | `orchestrator.py:780,1119,1232` | 30min |
| 5 | **上传端点改 `def`**（或内部包 `to_thread`） | `api/knowledge.py:35,76` | 20min |
| 6 | **注册加事务/捕获 IntegrityError** | `multitenant/users.py:14-23` | 30min |

### 第二梯队：1–2 天

7. **配置收敛单一事实源**：迁移到 `pydantic-settings` 的 `Settings` 类，把 `LLM_*`、`SECRET_KEY`、`CORS_ORIGINS`、`DATABASE_URL` 全部纳入并在启动时统一校验；消灭 `auth.py` 的随机密钥兜底；统一三处模型默认值；`DATABASE_URL` 改绝对路径或显式说明 CWD 依赖。
8. **本地开发体验**：装 `python-dotenv` 并在 `config.py` 顶部 `load_dotenv()`（或修正 `.env.example:3` 的措辞，明确 `.env` 仅供 Docker）。
9. **补齐生命周期**：新增 `/ready`；`/health` 在 `degraded` 时返回 503；lifespan 收尾调用 `stop_scheduler()` 并关闭资源。
10. **前端集成加固**：`request()` 加 5xx 指数退避重试（≤3 次，4xx 不重试）、401 处理、`navigator.onLine` 离线提示；错误解析兼容 `{detail}` / `{error,message}` / 数组三种形态。

### 第三梯队：架构级，需排期

11. **RBAC**：新增 `require_role(...)` 依赖，至少保护 `pause-all`、`tool-policy`、`schedules` 等管理端点。
12. **令牌模型**：access token 收短到 15min + 服务端存储的 refresh token（httpOnly Cookie）+ 撤销列表；同步解决 localStorage 问题。
13. **多副本就绪**：`_runtimes`（SSE 队列）外置 Redis + pub/sub；语义缓存、限流计数、熔断器状态外置；调度器加分布式锁或独立为单副本进程。这是把当前"隐含单进程假设"显式化的关键一步。
14. **SQLite 加固**：统一连接工厂，开启 `PRAGMA journal_mode=WAL` + `busy_timeout`；把 Agent Loop / Memory 表纳入 Alembic 版本管理。
15. **cron 计算替换**：`compute_next_run` 改为按字段直接进位计算（O(1)）或引入成熟库，消除同步阻塞。

---

## 八、附录：体检方法与已核实的证据

**未做的事（刻意约束）**：未安装任何依赖、未修改任何业务代码、未改变仓库状态。所有结论来自源码通读 + 独立复现。

**实证复现清单**：

| 结论 | 复现方式 | 结果 |
|---|---|---|
| P0-1 日志语句抛 TypeError | 在 Python 3.13 直接调用 `logging.getLogger().warning("x", status_code=404)` | `TypeError: Logger._log() got an unexpected keyword argument 'status_code'` ✅ |
| P1-5 cron 扫描成本 | 复刻 `schedule.py:81-96` 算法并计时 5 组表达式 | 38ms ~ 581ms，永不匹配表达式扫满 2,108,160 次迭代 ✅ |
| P1-8 限流是否失效 | 通读 slowapi `extension.py` 的 `limit` / `_check_request_limit` / `__evaluate_limits` | 装饰器用自身 `self`，**不依赖** middleware 与 `app.state.limiter` → 限流生效，**修正了初判** ✅ |
| P0-4 阻塞点定位 | 脚本扫描 `orchestrator.py` 全部函数：含 `subprocess.run` / `urllib` 的函数 + 其 async/sync 属性 + 调用行号 | 命中 `_run_verification`(sync, 调用点 780)、`_apply_build`(sync, 调用点 1119/1232) ✅ |
| P1-4 `.env` 不加载 | 全仓 grep `load_dotenv\|dotenv` + 检查 `requirements.txt` | 仅命中无关文档，`python-dotenv` 未安装 ✅ |
| P1-1 无 RBAC | 全仓 grep `require_role\|RBAC\|refresh_token` | 零命中 ✅ |
| P1-7 SQL 安全性 | 抽查 4 个仓储模块全部 SQL 语句 | 100% 参数化，无 N+1 ✅ |

**未能验证的项（需运行环境）**：P0-1 的"中间件栈提升"结论基于 Starlette `build_middleware_stack` 的源码语义（本机无 `fastapi`/`starlette` 可执行环境）。建议修复后**加一个断言 404 返回体含 `request_id` 的测试**来固化。

**建议补充的测试**（当前三条路径零覆盖）：
1. 异常路径：断言 `HTTPException` 与未处理异常的响应体都含 `request_id`，且格式一致；
2. 限流路径：`conftest.py:92` 之外，单独跑一次不关闭限流的用例，断言第 6 次请求返回 429；
3. 授权路径：断言普通用户调用 `pause-all` / `tool-policy` 返回 403；
4. 缓存隔离：两个用户用相似问题分别请求 `/ask/stream`，断言答案不串。
