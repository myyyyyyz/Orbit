# Orbit 多租户改造方案 v1

> 前置文档：`docs/MULTI-TENANT-READINESS.md`（差距清单与信源）、`docs/WORKBENCH-SCALE-ASSESSMENT.md`（并发/高可用）
> 本方案回答：**租户怎么建、数据存哪里、隔离靠什么兜底、先做哪一步**
> 基线：`dev/optimize` @ `80744bd`｜时间：2026-10-01

---

## 0. 结论先行

| 问题 | 答案 |
|---|---|
| 这台服务器能跑数据库吗 | **能**。部署后仍剩约 870MB 可用内存，但已在用 861MB swap，属于"能跑、别再加料"的上限 |
| 建议的数据库 | **PostgreSQL 16，作为 compose 里第 3 个服务**，不买 TencentDB（2C2G 阶段不值得多花钱+多一跳网络） |
| 多租户主方案 | **Pool 变体 + 四层隔离**：DB 用 RLS 兜底、向量库按租户分 collection、文件按租户分目录、缓存/记忆/用量带租户命名空间 |
| 第一优先动作 | **不是建库**，而是堵 7 处 P0 跨租户泄漏（匿名回退全局等）。建库是第二条腿，**不是前提** |
| 工程量 | Phase 0 约 1–2 天（纯收口）；Phase 2（上 PG+RLS）是"改半个数据访问层"量级，建议等 Phase 0/1 落地并验证后再启动 |

**一句话**：先把**已有的隔离骨架贯通到所有链路**（便宜、立刻消除高风险），再把**数据库换成 Postgres 并用 RLS 做物理兜底**（贵、但有不可绕过性）。

---

## 1. 资源可行性（2026-10-01 实测）

| 项 | 数值 | 判读 |
|---|---|---|
| 内存 | 总 1967MB / **可用 1121MB**（利用率 43–44%，24h 极稳） | 比 9/29 复查多出 ~160MB |
| Swap | 4GB 总，**已用 861MB** | ⚠️ 已在借 swap，说明工作集已略超物理内存 |
| 磁盘 | 50G 用 **25G，剩 23G（53%）** | 比 9/29 的 33G/69% 释放了 8G |
| CPU | 2 核，日常 **~2%**，构建时才冲高 | 完全够 |
| 容器 | `orbit-frontend` + `orbit-backend`（均 healthy） | 无 DB / 无 Redis |
| 磁盘构成 | containerd 11G + docker 7.1G + hermes-agent 3.9G + orbit 16M | 容器镜像才是磁盘主力，Orbit 本体只占 16M |

### Postgres 内存预算（调优后）

| 配置 | 值 | 说明 |
|---|---|---|
| `shared_buffers` | 192MB | 约总内存 10%，2C2G 阶段的推荐上限 |
| `effective_cache_size` | 512MB | 只影响计划器估算，不实占 |
| `work_mem` | 4MB | 单排序/哈希操作，太高×并发会爆 |
| `maintenance_work_mem` | 48MB | VACUUM / CREATE INDEX |
| `max_connections` | 20 | 应用侧配 PgBouncer 或把池压到 ~8 |
| **实测常驻 RSS** | **约 180–250MB** | 含 1 个 backend 进程 + shared memory |

**部署后预算**：1121MB − 220MB(Postgres) ≈ **900MB 可用**。可行，但要把 `docker-compose.yml` 里的 `mem_limit` / `shm_size` 显式钉住，避免 OOM killer 误杀 backend。

---

## 2. 目标架构：四层隔离

一个请求的租户身份**只在认证层确定一次**，然后沿四条链路传播，每条链路都有独立的强制点：

| 层 | 隔离载体 | 强制点 | 现状 |
|---|---|---|---|
| ① 数据层 | PostgreSQL **RLS** | `tenant_id = current_setting('app.tenant_id')` | ❌ 无（SQLite 无 RLS） |
| ② 向量层 | Chroma **collection per tenant** | collection 名 `t_{tenant_id}` | 🟡 已按 `user_{id}`，需升粒度 |
| ③ 文件层 | `DATA_DIR/tenants/{tenant_id}/...` | 路径由服务端拼接，**不接受客户端输入** | 🟡 `imports.py` 已有 tenant_hash 分目录 |
| ④ 进程内状态 | cache key / 记忆路径 / 用量记录 **带租户前缀** | 显式传 namespace | ❌ 无（P0 泄漏点） |

**设计原则**（呼应 READINESS 报告的信源结论）：
- 租户身份**只能来自验签后的 Token claim**，永不信任 body / query / 裸 header；解析不到就 **fail-closed（403/空结果）**，绝不静默查全表。
- 每层都**独立生效**：RLS 挡住漏写 WHERE 的 SQL；collection 分区挡住向量串库；目录分区挡住文件串读。任意一层出 bug，其余层仍在。

---

## 3. 数据层设计（核心）

### 3.1 先定语义：tenant_id 是 TEXT，不是 int

现有 schema 已经定了：`tenants.id TEXT PRIMARY KEY`、`users.tenant_id TEXT`（`alembic/versions/f7a4c3a193d7_initial_schema.py:38-46`），JWT 里也是字符串（如 `org_123`，`middleware/auth.py:146`）。

⚠️ **上一轮讨论中"RLS 用 `::int` 转换"的说法是错的** —— 必须按 **TEXT** 比较，否则 `current_setting` 的类型转换会在部分租户 ID 上直接抛错。

### 3.2 租户粒度决策

| 方案 | 含义 | 建议 |
|---|---|---|
| A. 租户 = 用户 | 隔离到人，`tenant_id` 退化为 user_id | 只在"不打算做团队协作"时选 |
| **B. 租户 = 组织（推荐）** | 一租户多 user，共享知识库/配额/账单 | 要做成对外产品就选它 |

**本方案按 B 展开**；选 A 可裁剪掉"共享 collection / 配额 / 成员管理"部分。

### 3.3 表归属：哪些表进 PG、哪些不进

Orbit 现在有 **3 套 SQLite**，路径解析方式还不一致 —— 这是迁库前必须先统一的：

| 库 | 表 | 路径来源 | 是否在数据卷 |
|---|---|---|---|
| `multitenant.db` | users / tenants / sessions / **loop_groups / loop_events / run_logs** | `settings.DATABASE_URL`（`multitenant/db.py:18`，合法） | ✅ `/app/data/` |
| `memory.db` | user_profile / project_context / conversation_summary | **硬编码** `../../memory.db`（`memory/db.py:8`） | ❌ 落在 `/app/memory.db`，**不在卷里** |
| Knowledge Agent audit | `knowledge_agent_runs` 等 | 调用方传 Path（`repository.py:27`） | 🟡 需确认 |

> 🔧 **顺带修的 bug**：`app/memory/db.py:8` 硬编码路径导致 `memory.db` 落在容器内非卷目录，容器重建即丢。即便不上 PG，也应改为 `DATA_DIR` 派生。

**迁移范围建议**：进 PG 的是 **"共享/跨租户需要查询与计量"的表** —— users、tenants、sessions、loop_*、run_logs、usage_events、api_keys。
**保留 SQLite 的是"单租户自包含"的数据** —— Knowledge Agent 审计、memory 结构化数据，可改为**每租户一个文件**（`tenants/{t}/orbit.db`），天然隔离、零改造成本。

### 3.4 PostgreSQL Schema（DDL 草案）

```sql
-- ── 身份域（不开 RLS：登录时尚无租户上下文）──────────────
CREATE TABLE tenants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'free',
    max_collections INTEGER NOT NULL DEFAULT 5,
    max_storage_mb  INTEGER NOT NULL DEFAULT 500,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    context    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_tenant ON sessions(tenant_id);

-- ── 租户业务域（全部带 tenant_id，全部开 RLS）──────────────
-- 示例：Agent Loop
CREATE TABLE loop_groups (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id      BIGINT REFERENCES users(id) ON DELETE SET NULL,
    session_id   TEXT UNIQUE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    current_agent TEXT,
    iteration_count INTEGER NOT NULL DEFAULT 0,
    task_desc    TEXT,
    project_dir  TEXT,
    plan_json    JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_loop_groups_tenant ON loop_groups(tenant_id);

CREATE TABLE loop_events (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    loop_id    BIGINT NOT NULL REFERENCES loop_groups(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    agent      TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_loop_events_tenant ON loop_events(tenant_id, loop_id, seq);

-- 用量事件（替代全局 usage.jsonl，支持按租户计量/限额）
CREATE TABLE usage_events (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id       BIGINT REFERENCES users(id) ON DELETE SET NULL,
    model         TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(12,6) NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_usage_tenant_day ON usage_events(tenant_id, created_at);
```

> `datetime('now')` → `now()`、`AUTOINCREMENT` → `BIGSERIAL`、`TEXT` 时间戳 → `TIMESTAMPTZ`：**SQLite 方言不能直接跑在 PG 上**，必须写新迁移，不要改已有的 `f7a4c3a193d7`（会破坏已部署实例）。

### 3.5 RLS 策略（关键）

```sql
-- 1) 应用角色：非 owner、非超级用户、无 BYPASSRLS
CREATE ROLE orbit_app LOGIN PASSWORD '...';
CREATE ROLE orbit_migrator LOGIN PASSWORD '...';   -- 表 owner，跑 alembic
GRANT CONNECT ON DATABASE orbit TO orbit_app;
GRANT USAGE ON SCHEMA public TO orbit_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO orbit_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO orbit_app;

-- 2) 对每张租户业务表启用 RLS（示例：loop_groups）
ALTER TABLE loop_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE loop_groups FORCE  ROW LEVEL SECURITY;   -- owner 也受限

CREATE POLICY tenant_isolation ON loop_groups
    FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
```

**三个必须说清的安全属性：**

1. **`current_setting(..., true)` 的第二参数必须是 `true`**。它让"未设置时返回 NULL"而不是抛异常。于是 `tenant_id = NULL` → 不匹配任何行 → **fail-closed**。若省略 `true`，未设置上下文时整条 SQL 报错 —— 看似更安全，实则会打挂所有后台任务（定时器、迁移、健康探针）。

2. **必须 `FORCE ROW LEVEL SECURITY`**。只 `ENABLE` 的话，**表 owner 仍然绕过策略**；而迁移角色往往是 owner，会造成"测试时隔离生效、线上因连接角色不同而失效"的诡异差异。

3. **应用连接必须是普通角色**。超级用户和带 `BYPASSRLS` 的角色**永远绕过 RLS**，与 policy 无关。所以 `orbit_app` 不能是 owner，也不能是 superuser —— 这是 RLS 能否真正兜底的前提。

### 3.6 租户上下文注入（最容易写错的一处）

⚠️ **连接池下的经典陷阱**：用 `SET app.tenant_id = ...`（会话级）设置 GUC，连接**归还池后不会自动清除** → 下一个请求复用该连接时**继承了上一个租户的身份** → 这就是"租户 A 读到租户 B 数据"的隐蔽成因。

正确做法：**事务级设置**（`SET LOCAL` 等价于 `set_config(..., is_local => true)`），并在 SQLAlchemy 的 `begin` 事件里注入：

```python
# app/multitenant/tenant_context.py（草案）
from contextvars import ContextVar
from sqlalchemy import event

current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)

@event.listens_for(engine, "begin")
def _inject_tenant(conn):
    tid = current_tenant.get()
    if tid is None:
        return          # 不设置 → RLS 下看不到任何行（fail-closed）
    conn.exec_driver_sql(
        "SELECT set_config('app.tenant_id', %s, true)",  # is_local=true → 事务结束自动失效
        (tid,),
    )
```

配合 HTTP 层：认证依赖拿到 `tenant_id` 后**在同一个请求作用域**写 ContextVar（FastAPI 的依赖与 ContextVar 天然同作用域），请求结束自动回收 —— 无需手动清理，也不会跨请求残留。

**禁止**：任何从 body / query / 自定义 header 读取 `tenant_id` 的写法。

### 3.7 为什么要 RLS（而不是"每个 WHERE 都记得写 tenant_id"）

- 全仓现在有大量裸 `sqlite3` + 手写 SQL（如 `knowledge_agent/repository.py:27`），**漏写一处 WHERE 就是一次跨租户泄漏**，而这类错误在 code review 中极难发现。
- RLS 是**数据库层强制**：漏写 WHERE 的 SQL 依然只能看到本租户行。这是"应用层自律"与"物理兜底"的本质差别。
- 代价：所有数据访问要从裸 `sqlite3` 迁到 SQLAlchemy/psycopg（占位符 `?`→`%s`、方言差异），**这是本方案最大的工程量来源**。

---

## 4. 其余三条链路的改造

### 4.1 向量层（`store/client.py`）

```python
# 现在： store/client.py:36
collection_name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION
# 目标：
collection_name = f"t_{tenant_id}"                      # 团队共享库
# （可选）f"t_{tenant_id}__u_{user_id}"                 # 个人私有库
```

- **不要保留 `else settings.CHROMA_COLLECTION` 这条回退分支** —— 它就是 P0-1 的成因（无身份 → 落全局库）。
- Chroma collection 命名约束：3–63 字符、仅 `[a-zA-Z0-9._-]`、首尾须字母数字。UUID 形式的 `tenant_id` 可直接用（`t_` + 36 字符 = 38，合规）；非安全字符要先 hash。
- **存量迁移**：`user_{id}` → `t_{tenant_id}`。用 `collection.modify(name=...)` 改名（同进程内最快），或按 embedding 原样 replay。迁移前**先备份 `chroma_db` 目录**。

### 4.2 文件层

```
DATA_DIR/
├── tenants/
│   └── {tenant_id}/
│       ├── uploads/
│       ├── staging/{import_id}/
│       ├── releases/
│       └── memory/YYYY-MM-DD.md
└── chroma_db/
```

`knowledge_agent/imports.py:39-44` 已经在用 `<tenant_hash>/<import_id>`，**把它的做法推广到 uploads / releases / memory 即可**，不需要新发明。

### 4.3 进程内状态（当前 P0 泄漏集中区）

| 链路 | 现状（行号引自 READINESS 报告） | 改造 |
|---|---|---|
| 流式缓存 | `stream/service.py:49,171` `cache_get/put` 未传 namespace | key 改 `f"t:{tenant_id}:{user_id}:{qhash}"`；非流式侧 `api/knowledge.py:132` 已有先例，直接对齐 |
| 对话记忆 | `api/logos.py:99-116` 所有用户写同一 `memory/YYYY-MM-DD.md` | 落 `DATA_DIR/tenants/{tenant_id}/memory/` |
| 用量 | `api/usage.py:23` 单文件、`log_token_usage` 不写归属、`:127` 限额全局 | 写 `usage_events` 表（带 tenant_id），限额改按租户读 |
| 全局开关 | `agents/api.py:105-114` pause-all 无鉴权 | 已用 `require_role` 可覆盖，补依赖即可 |
| 文件读取 | `agents/api.py:358-377` `/memory/scan` 的 `root` 直接取 query | 加白名单 + 鉴权；路径必须在租户根内 |

---

## 5. 鉴权收口（Phase 0 的核心）

当前 `api/knowledge.py` 全部端点用 `get_optional_user`，`user_id=None` 时落到全局 collection，**匿名可读写、可删他人片段**。

**推荐处理**：

| 端点类别 | 处理 |
|---|---|
| 写入 / 删除 / 列表 | 改 `get_current_user`（**强制登录**），无身份 → 401 |
| 纯演示只读（若确需匿名） | 映射到独立的 `anon` 租户，且该租户**只读**、**不含任何真实租户数据** |

**不要**采用"匿名就查全表"或"匿名就用默认租户"—— 这两种写法在多租户下都等价于数据泄露。

同时注意：`get_options_user` 那类"可选认证"依赖本身没问题，问题在**下游把它当成了默认权限**。改造时逐个端点确认语义，不要全局替换了事。

---

## 6. Agent 沙箱与配额（多租户后的新增风险）

Agent Loop 会**写文件、执行代码**（`agents/worktree.py`）。单用户无所谓，多租户后就是"未授权代码执行"。

**近期可做（应用层）**：
- `AGENT_ALLOWED_ROOTS` 从全局白名单改为**租户根目录**（`DATA_DIR/tenants/{t}/workspace`），路径校验叠加租户前缀，拒绝越界。
- worktree / 中间产物全部落租户目录；`project_dir` 落库前做规范化 + 前缀校验。
- 每租户并发 loop 数上限（`tenants` 表加 `max_concurrent_loops`）。

**长期（基础设施层）**，按纵深防御栈逐级替换：`namespace + cgroups` → `gVisor / Kata` → `Firecracker microVM`，并**默认拒绝 egress**、沙箱内只注入租户级密钥。2C2G 单机阶段先做应用层，等有真实不可信租户再上隔离运行时。

---

## 7. 分阶段落地路线

### Phase 0 — 收口（1–2 天，不改架构，立即消除高风险）

| # | 动作 | 验收 |
|---|---|---|
| 1 | `store/client.py` 去掉全局回退；`api/knowledge.py` 写入类端点改强制登录 | 匿名请求 401；无身份请求不再命中任何 collection |
| 2 | 流式缓存 key 加租户/用户 namespace | 两个用户问同一问题，命中各自的缓存条目 |
| 3 | 记忆文件落租户目录；顺带修 `memory/db.py:8` 硬编码路径 | 容器 `docker compose down && up` 后记忆不丢 |
| 4 | 用量记录写 `user_id`/`tenant_id`，限额改按租户 | 用量面板按租户可查；A 用完额度不影响 B |
| 5 | 无鉴权端点补 `require_role`；`/memory/scan` 加白名单 | 匿名调用 401/403 |
| 6 | 回归测试：**新增"跨租户不可见"用例**（A 的文档 B 检索不到） | 测试留作长期防线 |

> Phase 0 完成后，READINESS 报告里 7 条 P0 全部关闭，且**不需要 Postgres**。

### Phase 1 — 租户模型贯通（3–5 天）

- 引入 `tenant_context.py`（ContextVar + 请求作用域注入）
- 业务表统一补 `tenant_id`，写入路径全部从上下文取（禁止参数传入）
- Chroma collection 升为 `t_{tenant_id}`，写迁移脚本 + 备份
- `imports.py` 的租户目录模式推广到 uploads/releases/memory
- 补 `tenant` 管理接口（建租户 / 加成员 / 配额）

**验收**：租户 A 的用户登录后，无论走 RAG、Agent Loop、记忆还是用量，都无法触达租户 B 的任何数据。

### Phase 2 — Postgres + RLS（工程量最大，建议 Phase 0/1 验证后再启动）

1. **打快照**（改数据前留回滚点）
2. compose 加 `postgres:16-alpine` 服务 + 调优参数 + 独立数据卷 + `mem_limit: 320m`
3. 建角色（`orbit_app` 普通角色 / `orbit_migrator` owner）+ 新 alembic 迁移（PG 方言）
4. 开启 RLS（`ENABLE` + `FORCE`）+ 逐表 policy
5. 接入 `event.listens_for(engine, "begin")` 注入 `set_config(..., true)`
6. **数据迁移**：单机单副本场景建议**停服迁移**（比双写简单得多）：停 backend → 导出 SQLite → 转换载入 PG → 切 `DATABASE_URL` → 起服务 → 冒烟
7. 配 `pg_dump` 每日备份（磁盘已用 53%，PG 会持续增长）

**验收**：用 `orbit_app` 角色手动执行**故意漏写 WHERE 的 SQL**，确认只能看到本租户行 —— 这是 RLS 真正生效的唯一可信证明。

### Phase 3 — 配额、可观测与沙箱

- 按租户配额（`max_collections` / `max_storage_mb` / `max_concurrent_loops`）真实生效
- 指标按 `tenant_id` 打标签（**只看全局 P99 会掩盖单租户飙高**）
- Redis 替换进程内状态（撤销表 / 限流 / 缓存），消除"副本数必须 = 1"的约束
- Agent 运行时隔离升级

---

## 8. 风险清单

| 风险 | 等级 | 说明与对策 |
|---|---|---|
| 内存已借 swap | 中 | 加 PG 后 swap 压力上升。对策：钉死 `mem_limit`；观察 `docker stats` 与 `MemAvailable` |
| 磁盘 53% 且 PG 会增长 | 中 | 立即配 `pg_dump` + 定期清理构建缓存（本轮已释放 8G） |
| `SET` 误用导致跨租户串号 | **高** | 必须 `SET LOCAL` / `set_config(..., true)`；连接池下会话级 `SET` 是隐蔽灾难 |
| RLS 因角色不当而形同虚设 | **高** | 应用必须用非 owner、非 superuser、非 BYPASSRLS 角色；用"漏写 WHERE"测试证明 |
| 全量迁 PG 工作量被低估 | 中 | 裸 `sqlite3` → SQLAlchemy 是主要工作量；未迁完前**不要**半途切换 `DATABASE_URL` |
| 存量向量库改号 | 中 | 迁移前备份 `chroma_db`；`user_{id}` → `t_{tenant_id}` 需 user→tenant 映射 |
| 项目自身规矩 | — | `gate.yaml` 把 `**/migrations/**`、`.env*` 列为 denylist（`enforcement: reject`）；改这两类**需显式授权** |

---

## 9. 立即可以做的三件事

1. **打快照**（改任何数据前留回滚点）—— 零风险、一分钟。
2. **执行 Phase 0 的第 1–2 项**（去全局回退 + 缓存 namespace）—— 当前最高性价比的两个修复，改动小、覆盖最高危泄露路径。
3. **确认租户粒度**（租户=人 还是 租户=组织）—— 这一个决定会影响 Phase 1 之后所有设计，越早拍板越好。
