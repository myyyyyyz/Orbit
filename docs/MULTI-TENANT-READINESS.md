# Orbit 多租户就绪度评估与改造建议

> 评估范围：`backend/`（FastAPI + SQLite + 嵌入式 ChromaDB）、`frontend/`（Next.js）、`docker-compose.yml`、`alembic/`
> 方法：全仓代码审计（只读）＋ 业界最佳实践检索
> 结论时间：2026-09-13

---

## 0. 一句话结论

Orbit 已经点出了**正确的多租户骨架**——JWT 携带 `user_id`/`tenant_id`、`user_{id}` 向量 collection、Knowledge Agent 治理域带 `tenant_key`、import 路径带 tenant hash。但**这套骨架只覆盖了 Knowledge Agent 治理链路**；传统 RAG 链路、语义缓存、记忆文件、用量日志、全局开关与部署层**仍是单租户假设**，其中最危险的是"**未登录即回退到全局共享空间**"。

因此改造的核心不是"加 tenant_id 字段"，而是：**先把已存在的隔离层贯通到所有链路，再补 RBAC 与按租户的基础设施隔离。**

---

## 1. 先定义"租户"——一个必须先拍板的语义问题

当前代码里 `tenant_id` **存在但从未被使用于任何过滤逻辑**（`releases.py:31` 的 `_tenant_key` 只吃 `user_id`；`store/client.py:36` 也只按 `user_id` 分 collection）。也就是说：

- 现状实际是 **"多用户单租户"**，`tenant ≡ user`；
- `users.tenant_id`、`tenants` 表、JWT 里的 `tenant_id` 全是**死字段**。

**第一个决策点**：租户是指"个人"还是"团队/组织"？

| 选择 | 含义 | 影响 |
|---|---|---|
| A. 租户 = 用户（保持现状） | 隔离粒度到人 | 改动最小，但无法做"团队共享知识库/成员协作" |
| B. 租户 = 组织（推荐） | 一个租户多个 user，共享知识库/配额/账单 | 需要把 `user_{id}` collection 升级为 `tenant_{id}`，并把所有 user_id 过滤点改为 tenant_id（user_id 退化为审计字段） |

若目标真是"卖给多个客户公司"，选 B；否则问题应表述为"多用户隔离加固"而非"多租户"。**下文按 B 给建议，A 可裁剪执行。**

---

## 2. 已有可复用资产（不要推倒重来）

| 资产 | 位置 | 说明 |
|---|---|---|
| JWT 签发与校验 | `middleware/auth.py:25-68` | HS256，写 `user_id`/`tenant_id`，7 天有效 |
| `get_current_user` / `get_optional_user` | `middleware/auth.py:74,103` | 依赖注入形态正确，是改造的支点 |
| bcrypt 密码哈希 | `multitenant/password.py:6-15` | work_factor=12 |
| 治理域全链路带租户维度 | `knowledge_agent/repository.py`、`import_repository.py`、`evaluation_repository.py`、`releases.py` | runs/imports/evaluation/releases 均有 `user_id` 或 `tenant_key` |
| staging / ready 导入路径按租户分目录 | `knowledge_agent/imports.py:39-44` | `<tenant_hash>/<import_id>`，**已做对** |
| 服务端解析 collection 名 | `store/client.py:43-52` + `staging_store.py:19-24` | 注释明确"绝不暴露给 HTTP 输入"，已防止任意 collection 访问 |
| 错误处理器生产环境不回显异常 | `middleware/error_handler.py:64` | 仅 development 回显 |

**结论：治理域（Knowledge Agent）本身可作为其他链路改造的"模板"。**

---

## 3. 差距清单（改造点 → 现状 → 风险）

### P0 — 阻断级：跨用户数据暴露 / 越权，必须最先修

| # | 改造点 | 现状（已验证的代码事实） | 风险 |
|---|---|---|---|
| 1 | **匿名回退全局知识库** | `api/knowledge.py` 全部端点用 `get_optional_user`（`:24,35,79,94,105,116,123,187`），`user_id=None` 时 `store/client.py:36` 落到全局 collection `"documents"` → **匿名用户可读写、并可删除他人片段** | 高 |
| 2 | **流式链路缓存无租户隔离** | `stream/service.py:49` `cache_get(question)`、`:171` `cache_put(question, ...)` **未传 namespace**；非流式已隔离（`api/knowledge.py:132` `f"{user_id}:{collection}"`） | 高 |
| 3 | **对话总结写入全局单文件** | `api/logos.py:99-116` 所有用户（含匿名）追加到同一 `data/memory/YYYY-MM-DD.md`，并按文件名做"第 N 次对话"计数 → **A 的对话内容 B 能看到** | 高 |
| 4 | **用量统计全局、无租户维度** | `api/usage.py:23` 单个 `usage.jsonl`；`log_token_usage`（`:153`）不写 `user_id`；`get_usage`（`:91`）返回**全站**当日 token/成本；`:127` 日限额 `LLM_DAILY_LIMIT_TOKENS` 是**全局**的 | 高 |
| 5 | **任意文件读取** | `agents/api.py:358-377` `/memory/scan` 的 `root` 直接取 `query_params`，无白名单、无鉴权 → 可扫服务器任意目录并回显内容 | 高 |
| 6 | **全局开关无鉴权** | `agents/api.py:105-114` `/loop/pause-all` 无鉴权 → 任何人可暂停**所有用户**的 Agent Loop | 高 |
| 7 | **策略/缓存管理端点无鉴权** | `api/strategy.py:79-104`（PATCH 直接改全局 `settings.rag`）、`api/performance.py:10-18`（清空全局缓存） | 高 |
| 8 | **列表接口匿名越权** | `agents/api.py:265` `api_list_loops` 用 `get_optional_user`，匿名时 `list_loop_groups(None)` 返回**全部用户**的 loop | 高 |
| 9 | **无 RBAC** | `users.role` 字段存在但全库未用于鉴权（`api/auth.py:56` 仅回显） | 高 |
| 10 | **前端密钥明文存 localStorage** | `frontend/src/lib/api.ts:13-20` 的 `orbit_llm_models_v2`/`orbit_llm_key`、`settings-panel.tsx:141-147`；XSS 即失守（详见 `docs/` 安全讨论） | 高 |

### P1 — 重要：正确性与资源公平

| # | 改造点 | 现状 | 风险 |
|---|---|---|---|
| 11 | uploads 无用户维度 | `config.py:174` 扁平目录 `<DATA_DIR>/uploads/<uuid>_<原名>`，原始文件无 user 元数据 | 中 |
| 12 | Agent Loop 项目目录无租户维度 | `agents/api.py:574-587` 回退 `~/OrbitProjects/<project_name>` → 不同用户同名 project **命中同一目录** | 中 |
| 13 | 匿名 loop 归属未校验 | `agents/api.py:34-41` `user_id` 为空的 loop，任何登录/匿名用户可访问 | 中 |
| 14 | 匿名共享缓存命名空间 | `api/knowledge.py:132` 匿名时统一为 `"None:documents"` | 中 |
| 15 | BYOK 被绕过 | `api/logos.py:57` 无视 `X-API-Key`，强制用服务端共享 `LLM_API_KEY` → **租户请求消耗平台配额** | 中 |
| 16 | 流式错误直接回显 | `stream/service.py:196,204` 把 `str(e)` 作为 SSE message 下发 | 中 |
| 17 | `/health` 匿名回显内部组件状态 | `main.py:138-185` | 低 |
| 18 | 数据库三份 SQLite、无连接池 | `memory.db` **硬编码** `backend/memory.db`（`memory/db.py:7`），不受 `DATABASE_URL` 控制；另有 `multitenant.db`、运行时 `structured_data.db` | 中 |

### P2 — 规模化：水平扩展与噪声邻居

| # | 改造点 | 现状 | 风险 |
|---|---|---|---|
| 19 | 进程级全局单例 | `settings`（`config.py:218`）、语义缓存 `_cache`（`cache/storage.py:21`）、熔断器 `_breaker`（`llm/retry.py:98-108`）、Chroma client（`store/client.py:11`）→ 多副本不一致；**一个租户的失败会熔断全体** | 中 |
| 20 | 单进程全局调度器 | `main.py:69-76` + `agents/db.py:500-512` 全量扫描所有用户 schedules | 中 |
| 21 | 单实例部署 | `docker-compose.yml` 无 Redis、无独立 DB、嵌入式 Chroma，SQLite 单文件共享 | 中 |
| 22 | Agent Loop 执行不可信代码**无沙箱** | `agents/worktree.py:58-64` 只在宿主目录建 worktree，**无进程/网络/文件系统边界** → 见 §4.6，这是多租户化的**最大新增风险** | 高（多租户后） |
| 23 | 部署缺陷 | `docker-compose.yml:20` 把 `./knowledge` 挂 `:ro`，而 imports 需写 `knowledge/imports/...` → 容器内导入必失败 | 低 |

---

## 4. 最佳实践参考（含信源等级）

> 信源等级：**A** = 一手官方文档/标准；**B** = 主流大厂工程博客或成熟项目官方文档；**C** = 个人博客/社区（仅作补充）。

### 4.1 隔离模型选型：Pool / Bridge / Silo

AWS SaaS Lens 把多租户隔离形式化为三种模型，这是选型的行业通用词汇：

| 模型 | 机制 | 隔离强度 | 成本 | 适用 |
|---|---|---|---|---|
| **Pool** | 共享库共享表 + `tenant_id` 列 + RLS | 逻辑隔离 | 最低（每租户边际成本≈0） | 早期 SaaS、SMB 高密度 |
| **Bridge** | 标准租户 Pool，企业租户 Silo | 混合 | 中 | 同时有 SMB 与企业客户 |
| **Silo** | 每租户独立实例/库/命名空间 | 物理隔离 | 随租户线性增长 | 金融/政企/合规（HIPAA、数据驻留） |

**对 Orbit 的建议**：现阶段选 **Pool 的变体——"collection/目录级隔离"**（即把现在的 `user_{id}` 升级为 `tenant_{id}`），因为已按 collection 隔离，改造成本最低；等到出现强合规客户再对个别租户升 Bridge。

- 🔒 **A**：[AWS SaaS Lens – Well-Architected](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/saas-lens/wellarchitected-saas-lens.pdf)（定义了 Silo/Pool/Bridge、Tenant Isolation、Noisy Neighbor 等标准词汇）
- 🔒 **A**：[5 multi-tenant SaaS architecture best practices (AWS)](https://go.aws/3RomDlD)（2025 视角：把 tenant context 定义在 IAM 层、按定价映射隔离层级、按租户成本归因）
- ⚠️ C（中文对照）：[多租户数据隔离三种模式](https://blog.csdn.net/wzx_cx/article/details/162798561)

### 4.2 租户上下文：从"可信来源"派生，**永远不要信任客户端**

**核心原则**：tenant/user 身份必须来自**经过签名校验的 token claim 或会话**，绝不能来自 body / query / 裸 header。

**Orbit 现状其实是达标的**：`user_id` 只来自 JWT payload（`middleware/auth.py:96-117`），全仓未见从 body/query 读 user_id。这是值得保持的优点，务必不要为了"方便"退化。

推荐形态（FastAPI）：用**依赖注入**返回强类型 `TenantContext`，而不是把租户塞进中间件 + 全局 `ContextVar`：

```python
# ✅ 显式、可测、fail-closed
async def get_tenant_context(cred=Depends(HTTPBearer())) -> TenantContext:
    payload = jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])
    return TenantContext(tenant_id=payload["tenant_id"], user_id=payload["user_id"],
                         role=payload.get("role", "member"))

@app.get("/documents")
async def list_docs(ctx: TenantContext = Depends(get_tenant_context)):
    ...  # ctx 在签名里显式可见，测试可直接 override
```

**关键细节**：
- **Fail-closed**：解析不到租户就 `403`，绝不"静默按 None 查全表"。这正是 Orbit 当前 P0#1 的反面教材。
- **不要用中间件 + ContextVar 做租户隔离**：隐式依赖难调试、异步子任务不传递 context、类型不安全。
- 若确需 ContextVar（如后台任务），用 `contextvars` 并**在 `finally` 里 `reset(token)`**，后台任务用 `tenant_scope()` 显式包裹。

- ⚠️ C：[FastAPI DI for Multi-Tenant Request Context](https://dev.to/uaslimcreate/fastapi-dependency-injection-for-multi-tenant-request-context-avoiding-the-global-state-trap-484a)（CI/CD 与 fail-closed 讲得清楚）
- ✅ **B**：[fastapi-tenancy 官方文档](https://fastapi-tenancy.readthedocs.io/en/latest/)（`tenant_scope`、per-request context、四种隔离策略的开源参考实现）

### 4.3 数据库层：让隔离"即使写错代码也不漏"

仅靠应用层 `WHERE tenant_id=?` 是脆弱的——**一次漏写就是一个数据泄露**。数据库原生 RLS 提供"不可绕过"的兜底：

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
  FOR ALL USING (tenant_id = current_setting('app.tenant_id')::int)
  WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
-- 连接后：SET LOCAL app.tenant_id = '<id>';  （必须在事务内）
```

**要点**：① `FORCE ROW LEVEL SECURITY` 关闭表 owner 绕过；② 用 `SET LOCAL` 而不是 `SET`，因为 PgBouncer transaction 模式下 session 级设置不保留；③ 复合索引 `(tenant_id, ...)` 保证性能。

**对 Orbit 的落地含义**：SQLite 无 RLS，若近期不迁 Postgres，可用**"所有查询强制经统一 Repository 函数"**来模拟（在唯一入口注入 `AND tenant_id=?`），把"漏写"的概率压到最低。

- 🔒 **A**：[OWASP LLM08:2025 Vector and Embedding Weaknesses](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/)（明确"permission-aware vector store""strict logical and access partitioning"）
- ✅ **B**：[PostgreSQL RLS 多租户实现指南](https://www.wellally.tech/zh/blog/postgres-multi-tenant-database-row-level-security)（`SET LOCAL` + `WITH CHECK` 完整示例）
- ⚠️ C：[Multi-Tenant SaaS with NestJS + Prisma + Postgres RLS](https://js.elitedev.in/js/build-multi-tenant-saas-with-nestjs-prisma-postgresql-complete-rls-implementation-guide-c377189c/)

### 4.4 向量库 / RAG 隔离：**在存储层分区，而不是在查询层过滤**

这是对 Orbit 最直接相关的一条。业界对"多租户 RAG"的主流结论：

| 模式 | 隔离强度 | 何时用 |
|---|---|---|
| **每租户独立 collection**（Orbit 现路线） | 最强（物理无交集） | 租户数几十~几百、有高价值/合规客户 —— **推荐默认** |
| 共享 collection + `tenant_id` 过滤 | 强（依赖每次查询都过滤对） | 租户数上万、共享库维护成本敏感 |
| 每租户独立集群 | 最强 | 最高敏感度客户，愿意付费 |

**关键警示**：共享索引 + `WHERE tenant_id=X` 仍可能被**时序侧信道**和**实现 bug**击穿——**分区要下沉到存储层，而非停在查询层**。

- 🔒 **A**：[Multi-tenant RAG with Amazon Bedrock Knowledge Bases (AWS ML Blog)](https://aws.amazon.com/blogs/machine-learning/multi-tenant-rag-with-amazon-bedrock-knowledge-bases)（用 Silo/Pool/Bridge 给出三种 RAG 隔离架构，并列出四大设计考量：租户隔离、租户差异性、租户管理简易度、成本效率）
- ✅ **B**：[Designing Multi-Tenancy RAG with Milvus (Zilliz)](https://zilliz.com/blog/build-multi-tenancy-rag-with-milvus-best-practices-part-one)（database/collection/partition 三粒度隔离）
- ⚠️ C：[Multi-Tenant RAG Isolation](https://gigagpu.com/multi-tenant-rag-isolation)（"per-tenant collection by default" + GDPR 一键删除）

### 4.5 语义缓存：租户前缀是"不可协商的基线"

Orbit 的 `stream/service.py:49,171` 恰好命中了这个坑。业界共识：

- **缓存 key 必须带租户命名空间**（`{tenant_hash}:{model}:{prompt_hash}`），且**在存储层分区**，不是 lookup 时过滤；
- **逐租户 eviction 配额 + TTL**：全局 LRU 会让高流量租户驱逐低流量租户的条目（软 DoS），也可能让数据超出留存承诺；
- **共享前缀缓存（KV-cache）跨租户可被"投毒"**：A 的缓存前缀可能被 B 命中，恶意者可构造 prompt 污染其他租户的输出。

- ⚠️ C：[KV-cache poisoning: securing multi-tenant LLM APIs](https://mvpfactory.io/blog/kv-cache-poisoning-and-prompt-injection-in-production-llm-apis-rate-limiting)（缓存投毒三向量与分级缓解）
- ✅ **B**：[Semantic Caching: When Text Stops Being the Right Cache Key (TrueFoundry)](https://www.truefoundry.com/blog/semantic-caching-llm-gateway)（"租户 A 收到为租户 B 生成的缓存响应不是 bug，是 breach"；两级隔离：user/virtual-account 自动隔离 + 自定义 namespace）
- ⚠️ C：[Semantic Caching for LLMs（dev.to）](https://dev.to/kuldeep_paul/semantic-caching-for-llms-how-it-works-and-when-it-returns-the-wrong-answer-5d3o)（强制 metadata namespacing 清单：tenant + model + system-prompt-hash）

### 4.6 Agent 执行沙箱：Orbit 多租户化的**最大新增风险**

Orbit 的 Agent Loop 会**写文件、建 worktree、执行代码**（`agents/worktree.py`）。单用户时这是"自己跑自己的代码"；多租户后就是**不可信代码执行**——一次提示注入可能让某租户的 Agent 读到其他租户的数据或平台密钥。

业界纵深防御栈（由弱到强）：
`namespace+cgroups`（共享内核，最弱）→ **安全容器 Kata Containers** → **微虚拟机 Firecracker / gVisor**（独立内核，冷启 <150ms，Agent 沙箱首选）→ 传统 VM（最慢最重）。

工程要点：
- **控制面/数据面解耦**：控制面管生命周期与鉴权，数据面每租户独立容器隔离；
- **出口默认拒绝**：网络 egress 白名单（允许 PyPI/HTTPS，拦截裸 socket），防横向移动；
- **预热池**：消除冷启动（Agent 调用稀疏突发）；
- **信任边界**：受信 Agent Loop 持业务密钥，**沙箱只拿租户环境级密钥，绝不暴露平台敏感信息**；
- **文件策略**：读"默认允许 + 敏感路径拒绝"（`.ssh/.aws/.env`），写"默认拒绝 + 仅工作目录允许"。

- 🔒 **A**：[Running Agents on Kubernetes with Agent Sandbox (Kubernetes Blog)](https://www.kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox)（Sandbox CRD，原生支持 gVisor/Kata，面向多租户不可信执行）
- 🔒 **A**：[Run Untrusted AI Agent Code Safely with Azure Container Apps Sandboxes (InfoQ 报道微软官方)](https://www.infoq.com/news/2026/06/untrusted-ai-agents-sandboxes/)（microVM + egress 默认拒绝 + AST 扫描 + 工具白名单）
- ✅ **B**：[虚拟机 & 容器 多租户智能体的沙箱设计方案（腾讯云开发者社区）](https://developer.cloud.tencent.cn/article/2662744)
- ⚠️ C：[AI Agent Sandbox 架构与企业实践](https://wengjialin.com/blog/agent-sandbox)（K8s + bwrap 分层、warm pool、共享文件系统按 tenant/user/sandbox 隔离）

### 4.7 计量、配额与噪声邻居

- **按租户计量**：每次 LLM 调用必须落 `tenant_id`，才能做成本归因与配额（对应 P0#4）。
- **分层限流**：per-tenant token bucket（按订阅档位），在网关层拦，别等打到 DB。
- **超时护栏**：`statement_timeout` / `idle_in_transaction_session_timeout`，防一个租户占死连接。
- **按租户观测**：只看全局 P99 会掩盖"某租户因夜间批量任务飙到 2s"——**必须按租户看延迟**。

- 🔒 **A**：[5 multi-tenant SaaS best practices (AWS)](https://go.aws/3RomDlD)（per-tenant cost attribution、govern AI workloads per tenant）
- ⚠️ C：[Ilir Ivezaj — Multi-Tenant SaaS Architecture](https://ilirivezaj.com/insights/multi-tenant-architecture)（噪声邻居四层防御）

---

## 5. 目标架构（分层隔离图）

```
┌─────────────────────────────────────────────────────────────┐
│  接入层：JWT(tenant_id/role) → 依赖注入 TenantContext（fail-closed）│
├─────────────────────────────────────────────────────────────┤
│  应用层：所有 handler 显式 Depends(TenantContext)；RBAC 校验 role  │
├─────────────────────────────────────────────────────────────┤
│  数据层：统一 Repository，强制注入 tenant 过滤                        │
│    · 关系库：加 tenant_id 列；迁 Postgres 后用 RLS 兜底              │
│    · 向量库：collection = tenant_{id}（现 user_{id} 升级）          │
│    · 对象存储：uploads/tenant_{id}/...                             │
├─────────────────────────────────────────────────────────────┤
│  缓存层：key = {tenant_hash}:{model}:{prompt_hash}；逐租户 TTL/配额   │
├─────────────────────────────────────────────────────────────┤
│  执行层：Agent Loop 落地沙箱（microVM/Firecracker）+ egress 白名单    │
├─────────────────────────────────────────────────────────────┤
│  观测层：用量/日志/指标全部带 tenant_id，按租户核算与告警              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 落地路线图

**Step 1（P0，可独立发布）— 堵住"匿名 = 全局共享"**
1. `api/knowledge.py` 全部 `get_optional_user` → `get_current_user`；匿名直接 401。
2. 给 `api/strategy.py`、`api/performance.py`、`agents/api.py` 的 `pause-all` / `memory/scan` / `list_loops` 补 `Depends(get_current_user)`（`memory/scan` 额外加路径白名单）。
3. `stream/service.py` 的 `cache_get/cache_put` 补 namespace（对齐 `api/knowledge.py:132`）。
4. `api/logos.py` 的记忆文件路径加入 `tenant_hash`（或直接取消该文件，只保留 `conversation_summary` 表）。

**Step 2（P1）— 正确性与资源归因**
5. `usage.jsonl` 加 `user_id`/`tenant_id` 字段，`get_usage` 按调用者过滤；日限额改租户级。
6. 启用 RBAC：把 `users.role` 接进依赖（`require_role("admin")`）。
7. `uploads/` 与 `_resolve_project_dir` 加租户命名空间。
8. `api/logos.py:57` 支持 BYOK，或明确标注"消耗平台配额"。

**Step 3（P2）— 规模化与安全加固**
9. 迁移到 Postgres + RLS（或退而求其次：统一 Repository 强制过滤）；`memory.db` 改由 `DATABASE_URL` 派生。
10. 引入 Redis（缓存/限流/分布式锁），消除进程内单例。
11. Agent Loop 落地沙箱 + egress 白名单（若对多租户开放 Agent 执行，此项**不可省略**）。
12. 前端 JWT 迁 HttpOnly Cookie；BYOK 改服务端加密托管（见安全专题）。

---

## 7. 参考来源汇总

| 主题 | 来源 | 等级 |
|---|---|---|
| 隔离模型 Pool/Bridge/Silo | [AWS SaaS Lens](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/saas-lens/wellarchitected-saas-lens.pdf) | A |
| 2025 多租户五大实践 | [AWS Blog](https://go.aws/3RomDlD) | A |
| 多租户 RAG 三模式 | [AWS ML Blog – Bedrock KB](https://aws.amazon.com/blogs/machine-learning/multi-tenant-rag-with-amazon-bedrock-knowledge-bases) | A |
| 向量/嵌入弱点与租户隔离 | [OWASP LLM08:2025](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/) | A |
| Agent 沙箱（K8s 原生） | [Kubernetes Blog](https://www.kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox) | A |
| Agent 沙箱（托管 microVM） | [InfoQ / Azure ACA Sandboxes](https://www.infoq.com/news/2026/06/untrusted-ai-agents-sandboxes/) | A/B |
| Postgres RLS 多租户 | [wellally RLS 指南](https://www.wellally.tech/zh/blog/postgres-multi-tenant-database-row-level-security) | B |
| 向量库多租户策略 | [Zilliz – Milvus](https://zilliz.com/blog/build-multi-tenancy-rag-with-milvus-best-practices-part-one) | B |
| 语义缓存租户隔离 | [TrueFoundry](https://www.truefoundry.com/blog/semantic-caching-llm-gateway) | B |
| FastAPI 租户上下文 | [fastapi-tenancy](https://fastapi-tenancy.readthedocs.io/en/latest/) | B |
| 缓存投毒 | [MVP Factory](https://mvpfactory.io/blog/kv-cache-poisoning-and-prompt-injection-in-production-llm-apis-rate-limiting) | C |
| FastAPI DI 模式 | [dev.to](https://dev.to/uaslimcreate/fastapi-dependency-injection-for-multi-tenant-request-context-avoiding-the-global-state-trap-484a) | C |
| 租户沙箱（中文） | [腾讯云开发者社区](https://developer.cloud.tencent.cn/article/2662744) | B |

> ⚠️ 本报告为公开资料与代码审计整理，涉及安全与合规的部分（认证、密钥托管、数据隔离、行业合规）**部署前需经安全/合规专家审校**，不构成专业安全审计结论。
