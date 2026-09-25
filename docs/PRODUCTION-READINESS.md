# Orbit 上线加固说明（2026-09-25）

> 对应体检报告 `docs/ARCHITECTURE-HEALTH-CHECK-2026-09-25.md`。
> 本文件记录：**改了什么、为什么这么改、上线前必须做什么、还有哪些约束没解决**。

---

## 1. 已修复项

### P0（4 处「声称与实现不符」）

| # | 问题 | 修复 | 位置 | 验证 |
|---|------|------|------|------|
| P0-1 | 全局异常处理器实测抛 `TypeError`；且只注册了 `Exception`，`HTTPException` 走 FastAPI 默认处理器 → 丢失 `request_id`，统一结构失效 | 改用 structlog logger；新增 `register_exception_handlers()` 同时注册 `StarletteHTTPException` / `RequestValidationError` / `Exception` 三类 handler；并显式给错误响应补 `X-Request-ID` 头（兜底 handler 在最外层，请求 ID 中间件无机会注入） | `backend/app/middleware/error_handler.py`、`main.py` | `test_p0_hardening.py::test_http_exception_uses_unified_structure` 等 6 例 |
| P0-2 | Fallback 复用同一个 `call_fn` → 发出的是一字不差的同一请求；熔断 open 仍死打故障端点；`model_used` 透传假模型名给前端 | `call_llm_with_retry` 新增 `fallback_call_fn`；调用方用 fallback 的 `base_url/model/api_key` **重建**请求（新增 `get_fallback_llm_config` / `build_chat_call` / `LLM_FALLBACK_BASE_URL`）；**没有 fallback 构造器时如实失败**，不复刻请求假装降级；`model_used` 仅在 fallback 真成功后上报 | `backend/app/llm/{retry,client,__init__}.py`、`generate/service.py`、`stream/service.py` | `test_p0_hardening.py::test_fallback_call_fn_is_actually_used` 等 7 例 |
| P0-3 | 流式路径 `cache_get/put` 未传 namespace → 全租户共享一份缓存，B 用户会拿到 A 的答案且无报错 | 新增 `_cache_namespace(user_id, ...)`（与租户 + 活跃索引版本绑定），流式路径与非流式对齐；异常时退化为按 `user_id` 隔离而非全局 | `backend/app/stream/service.py` | `test_p0_hardening.py::test_cache_isolated_by_namespace`、`test_stream.py::test_cache_lookup_uses_tenant_namespace` |
| P0-4 | `_run_verification`（同步 subprocess，最坏 90s+）/ `_apply_build`（git stash）直接跑在 async 里 → 冻结事件循环，所有 SSE 与请求停摆 | 两处调用点（共 3 处）改为 `await asyncio.to_thread(...)`，与同文件对 LLM 调用已有的处理保持一致 | `backend/app/agents/orchestrator.py` | 代码路径一致性 + 现有 loop 测试 |

### 上线就绪度

| 项 | 修复 |
|---|---|
| `.env` 本地不加载 | 新增 `app/env_loader.py`，`app/__init__.py` 与 `config.py` 最早期加载；`python-dotenv` 优先，缺失时内置最小解析器（不覆盖已存在的真实环境变量） |
| `SECRET_KEY` 两套相反策略 | 统一：生产缺失/过短 → **拒绝启动**；非生产 → 告警 + 进程内随机 key（`get_secret_key()` 为唯一入口） |
| 主模型默认值三处不一 | 统一为 `client.DEFAULT_LLM_MODEL = "deepseek-chat"`（与 compose / `.env.example` 对齐），其他模块引用常量 |
| `/health` 恒 200、无 `/ready` | 拆分职责：`/health` 存活探针（极简、恒 200）、`/health/detail` 依赖明细（恒 200，body 表达健康度）、`/ready` 就绪探针（关键依赖不可用 → **503**）。compose healthcheck 改用 `/ready` |
| 不调 `stop_scheduler()` | lifespan 关闭阶段调用；`ENABLE_SCHEDULER=0` 可在多副本中只让一个副本跑调度 |
| 调度器无分布式锁 | 新增 `db.claim_schedule()`：以 `next_run_at` 做 CAS 原子抢占，同一次到期只有一个副本能触发 |
| cron 逐分钟扫描阻塞 | `compute_next_run` 改为「按天推进 + 命中日取最早时刻」，复杂度 O(2,100,000) → O(1,461)；实测最坏耗时从 ~581ms 降到 <1ms |

### 安全

| 项 | 修复 |
|---|---|
| 零 RBAC | 新增 `require_role()`（每次请求回查 DB 取权威角色，查询失败 fail-closed）；`POST /agents/loop/pause-all`（全局急停）改为 admin only + 审计日志。新增 `python -m app.admin_cli promote/demote/list` 作为角色引导路径 |
| 7 天长效令牌、无撤销 | Access Token 降到 **60 分钟**（`ACCESS_TOKEN_EXPIRE_MINUTES`），新增 Refresh Token（7 天，`REFRESH_TOKEN_EXPIRE_DAYS`）；两者用 `type` 声明严格隔离（refresh 不能当 access 用，反之亦然）；`jti` + 进程内撤销表，`POST /auth/logout` 立即失效；`/auth/refresh` 轮换 refresh（旧的一次性作废，防重放） |
| 全仓无安全响应头 | 新增 `SecurityHeadersMiddleware`（纯 ASGI，不干扰 SSE）：`X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` / `Permissions-Policy` / `CSP`，生产额外 HSTS |
| 两个 Limiter 实例 | 统一为 `app/rate_limit.py` 唯一实例；支持 `TRUST_PROXY_HEADERS=1` 在反代后按 `X-Forwarded-For` 分桶（默认关闭，避免伪造）；给 `/knowledge/ask`、`/knowledge/ask/stream`、`/knowledge/upload*`、`/agents/loop` 补上限流 |
| Agent Loop 可写任意绝对路径 | `_resolve_safe_project_dir` 引入允许根白名单（`AGENT_ALLOWED_ROOTS` / `KNOWLEDGE_ROOT`）；生产环境未配置白名单时**拒绝一切绝对路径**（此前任何登录用户都能让 Builder 往 `/etc`、`~` 落盘） |

### 健壮性 / 前端

| 项 | 修复 |
|---|---|
| SQLite 无 WAL / busy_timeout | 新增 `app/sqlite_utils.connect()`：WAL + busy_timeout(15s) + synchronous=NORMAL + foreign_keys（生产 ON，非生产 OFF，可覆盖）；接入多租户主库与记忆库 |
| 上传端点 async 做重活 | 解析 / 切分 / embedding / 写库统一 `asyncio.to_thread`；`preload_model` 同样移出事件循环 |
| 缓存无事件驱动失效 | 新增 `cache.purge_user()`，上传 / 删除文档后清空该用户全部缓存条目（此前用户上传新文档后仍会命中"上传前"的旧答案，且无任何报错） |
| 前端零重试 / 无 401 / 无超时 | `api.ts` 增加：`ApiError`（带 status + request_id）、30s 超时中断、幂等请求网络/5xx 单次重试、401 自动用 refresh 续期并重放（并发 401 合并为一个刷新）、统一错误信息提取（兼容 `{error,detail}`/校验数组）；SSE 统一走 `consumeSSE`（401 重试 + 120s 超时 + 半包处理） |
| 令牌存 localStorage | **保留**（见 §3 已知约束）。改为 httpOnly cookie 需要 CSRF 方案与全量前端改造，本轮不动 |

### 部署级（真实启动冒烟时新发现，非体检清单内）

这两条是**实际把服务跑起来**做端到端冒烟才暴露的，静态审读看不出来。

| 项 | 问题 | 修复 |
|---|---|---|
| **Alembic 迁移库 ≠ 运行时库** | `alembic.ini` 里 `sqlalchemy.url = sqlite:///../multitenant.db` 是**相对进程 CWD** 解析的；运行时库路径 `multitenant.DB_PATH` 由 `settings.DATABASE_URL` 相对 `__file__` 解析，与 CWD 无关。**未显式设置 `DATABASE_URL` 时二者分叉**：迁移把 `users/sessions/tenants` 建到 CWD 相对路径（如仓库根），应用却去读另一个库 → 注册/登录直接 500 `no such table: users`。compose 与 `conftest.py:20` 都显式设了 `DATABASE_URL`，所以**只在"本地直连 uvicorn / 非 compose 部署"时才炸** —— 典型"容器能跑、裸机上线就崩"。实测复现：repo 根多出一个只含初始 schema 的孤儿 `multitenant.db`，而 `backend/multitenant.db` 里没有 `users` 表。 | `multitenant/db.py::init_db()` 改为**无条件**用 `settings.DATABASE_URL` 覆盖 alembic 的 `sqlalchemy.url`（该值本身已实现"环境变量优先"，不丢优先级）。以它为唯一事实源后，迁移目标库与运行时库恒等，且与 CWD 无关。回归测试 `test_p0_hardening.py::test_init_db_migrates_the_same_file_runtime_reads` |
| **注册接口不返回 `role`** | `users.role` 的 schema 默认值是 `'user'`。`login_user` 返回 `row["role"]` → `'user'`；但 `register_user` 的返回体**没有 `role` 字段** → 注册接口响应 `role: null`。前端 `auth-form.tsx` 会把 `null` 当角色存下（并清掉 `orbit_role`），表现为"同一账号刚注册后看不到角色相关 UI、重新登录后才出现"。 | `register_user` 插入后**回读** `role`/`tenant_id` 再返回（不硬编码 `'user'`，保证与登录路径一致且适配不同默认值）。回归测试 `test_p0_hardening.py::test_register_reports_same_role_as_login` |

> 附：本次冒烟曾在仓库根误建一个孤儿 `multitenant.db`（只含初始 schema、全表 0 行），已移至 `/tmp/orbit-stray-multitenant.db.bak`。修复后不会再产生。

---

## 2. 上线前必做

### 2.1 必配环境变量

```bash
# 密钥（生产强制，缺失直接拒绝启动）
ENV=production
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
LLM_API_KEY=sk-xxxx

# 域名（生产禁止 *）
CORS_ORIGINS=https://your-domain.com

# Fallback（可选，但配了就必须给 key 且建议显式给 base_url）
LLM_FALLBACK_MODEL=gpt-4o-mini
LLM_FALLBACK_API_KEY=sk-yyyy
LLM_FALLBACK_BASE_URL=https://api.openai.com/v1/chat/completions

# Agent Loop 落盘白名单（生产必须配置）
AGENT_ALLOWED_ROOTS=/app/knowledge

# 反向代理后必须置 1，否则限流按代理 IP 分桶会误伤全部用户
TRUST_PROXY_HEADERS=1

# 令牌时效
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
```

### 2.2 引导第一个管理员

RBAC 上线后默认角色为 `user`，`pause-all` 等管理接口无人可调，需要显式提升：

```bash
cd backend && python -m app.admin_cli promote <your-username>
```

### 2.3 部署形态

- **单副本**：可直接上（默认 `ENABLE_SCHEDULER=1`）。
- **多副本**：①只在一个副本置 `ENABLE_SCHEDULER=1`（DB 抢占可兜底，但省掉无谓轮询）；②**必须**先把 §3 的进程内状态外置，否则 SSE 会断流、语义缓存与令牌撤销表不共享。

### 2.4 冒烟验证

```bash
# 1) 存活 / 就绪
curl -s localhost:8001/health          # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/ready   # 200

# 2) 注册（密码 >= 8 位）→ 拿到 access + refresh，且 role 必须是 "user"
curl -s -X POST localhost:8001/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"smoke","password":"smoke12345"}'
# 期望含："role":"user"、"expires_in":3600、access_token、refresh_token
# 若 role 为 null → 说明 §1「部署级」的注册契约回归了

# 2b) 确认迁移库与运行时库是同一个文件（最关键的一项）
#     未设 DATABASE_URL 启动后，users 表必须出现在应用实际读写的那一个库里
grep -o 'sqlite:///[^"]*' backend/app/config.py   # 解析出运行时路径
# 该路径对应的文件里应有 users/sessions/tenants + alembic_version

# 3) 未授权访问管理接口应 401/403
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8001/api/v1/agents/loop/pause-all \
  -H 'Content-Type: application/json' -d '{"paused":true}'   # 401

# 4) 业务错误应带统一结构与 request_id
curl -s localhost:8001/api/v1/knowledge/ask -X POST \
  -H 'Content-Type: application/json' -d '{"question":""}' | python -m json.tool
# {"error":"问题不能为空","request_id":"..."}

# 5) 登出后同一 access_token 应立即失效
```

### 2.5 回归测试

```bash
cd backend
# 轻量集（无需 chromadb / sentence-transformers），覆盖全部 P0、部署级与安全改动
python -m pytest test/test_p0_hardening.py test/test_middleware_auth.py test/test_generate.py -q
# 核心集（需 chromadb，覆盖 app 级：lifespan / 路由 / 探针 / 流式）
python -m pytest test/test_main.py test/test_api_auth.py test/test_stream.py \
  test/test_p0_hardening.py test/test_middleware_auth.py test/test_generate.py \
  test/test_multitenant.py test/test_config.py test/test_router.py test/test_schemas.py -q
# 全量（需完整依赖）
python -m pytest test/ -q
```

> 本次验证：核心集 **152 passed / 0 failed**。`test_cache.py` 单列时因缺真实
> `sentence-transformers`（会拉 PyTorch）而报导入错误，属环境依赖缺失、非回归。

---

## 3. 已知约束（**未**解决，上线前需知悉）

1. **架构隐含单副本假设**：以下状态都在进程内内存，多 worker / 多副本下不共享：
   - `agents/orchestrator._runtimes`（SSE 事件队列 / checkpoint）→ 跨 worker 会断流
   - `cache.storage._cache`（语义缓存）
   - `middleware.auth._revoked`（登出撤销表）→ 登出后其它副本仍认旧令牌
   - `rate_limit` 的内存计数器 → 限额被放大 N 倍
   - 扩展路径：统一外置 Redis（pub/sub + 共享 KV）。

2. **令牌仍存 localStorage**：存在 XSS 窃取风险。改为 httpOnly cookie 需同时引入 CSRF 方案并改造全部前端调用点，属于独立迭代。

3. **数据库仍是 SQLite**：已开 WAL + busy_timeout，但写并发上限依然存在；`config.DATABASE_URL` 已预留 PostgreSQL 路径（`_resolve_db_path` 目前只支持 `sqlite:///`，切换需要改动）。

4. **分支锁 `acquire_branch_lock` 是 read-then-write**（TOCTOU）：单进程下安全，多进程下可能双抢。

5. **无后台管理界面**：角色管理依赖 `admin_cli`（有意为之，避免引入未加固的 Web 管理面）。

6. **测试环境限制**：`test_cache.py` 依赖真实 `sentence-transformers` 编码器；`conftest.py` 已放宽对 `app.search`（→ chromadb）的硬依赖，使轻量单测可在最小依赖下运行。

---

## 4. 行为变更（兼容性）

改动会改变既有对外行为，升级前需确认：

| 变更 | 影响 |
|---|---|
| 登录/注册响应新增 `refresh_token`、`expires_in`；`access_token` 时效 7 天 → 60 分钟 | 老客户端若只存 access_token 且不做刷新，60 分钟后会 401 |
| 登出语义变化 | `POST /api/v1/auth/logout` 现在会真正撤销令牌 |
| 500 响应结构 | 由非结构化/崩溃变为 `{error, detail?, request_id}`；`HTTPException` 响应新增 `request_id` 字段（`detail` 字段保留，前端兼容） |
| `/health` 语义 | 由"依赖明细"变为"存活探针"；依赖明细移至 `/health/detail`（前端已同步） |
| 注册密码最短长度 | 6 → 8 位（仅注册；登录不校验长度，存量短密码用户不受影响） |
| cron `day_of_week` 语义 | 对齐标准 cron：**0 = 周日**（此前实现里 0 实际是周一，与 `7→0` 的归一逻辑自相矛盾）。存量 schedule 的触发日可能相对此前偏移一天，需复核 |
| Agent Loop 绝对路径 | 生产环境未配置 `AGENT_ALLOWED_ROOTS` 时拒绝绝对路径（相对路径仍限制在 `AGENTS_PROJECT_ROOT` 内） |

---

## 5. 上线检查清单

- [ ] `ENV=production`，`SECRET_KEY` ≥ 32 字符且已妥善保管（变更即全员掉线）
- [ ] `LLM_API_KEY` 已配置；若配了 fallback，`LLM_FALLBACK_API_KEY` 与 `LLM_FALLBACK_BASE_URL` 均已配置
- [ ] `CORS_ORIGINS` 为真实域名、无 `*`
- [ ] `AGENT_ALLOWED_ROOTS` 已配置且**不含**敏感目录
- [ ] 反代后 `TRUST_PROXY_HEADERS=1`；代理已透传 `X-Forwarded-For`
- [ ] 已创建 admin 账号（`python -m app.admin_cli promote`）
- [ ] 副本数 = 1，或已完成 §3-1 的状态外置
- [ ] `/ready` 返回 200，compose healthcheck 使用 `/ready`
- [ ] **确认迁移库 = 运行时库**：未设 `DATABASE_URL` 启动一次，注册后才能查得到用户（见 §2.4-2b）。该库是 `settings.DATABASE_URL` 解析出的那个文件；Docker 下由 compose 固定为 `/app/data/multitenant.db`
- [ ] **备份范围按实际路径核对**：`DATABASE_URL` 指向的 SQLite 文件（含 `-wal`/`-shm`）+ `DATA_DIR`（`chroma_db/`、`uploads/`、日志）+ `memory.db`。**不要想当然地只备 `data/`** —— 未设 `DATABASE_URL` 时该库在 `backend/multitenant.db`
- [ ] 冒烟脚本全部通过（含注册响应 `role == "user"`）
- [ ] 监控已开：`ENABLE_PROMETHEUS=1` / `SENTRY_DSN`（可选但建议）
- [ ] 已确认 §4 行为变更对现有客户端可见且可接受
