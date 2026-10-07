# 多租户 P0 修复记录（Phase 0）

> 分支 `dev/optimize`，提交 `d794572`（代码与测试）、`6239a6e`（文档）
> 范围：Phase 0 全部 6 项 + `memory.db` 路径修复
> 前置：`docs/MULTI-TENANT-READINESS.md`（差距清单）、`docs/MULTI-TENANT-PLAN.md`（方案）
> 测试：**389 passed / 0 failed / 100 errors**（100 errors 为沙箱环境限制，见文末）

---

## 1. 匿名空间隔离（最高危）

**问题**：`user_id=None` 时所有读写落到**全局共享**的 `documents` collection，任何未登录访客都能写入、并删除他人上传的内容；该库还含早期未做隔离时上传的历史数据。

**修法**：引入"命名唯一事实源"，匿名不再回退全局库。

| 文件 | 改动 |
|---|---|
| `app/config.py` | 新增 `anon_collection`（env `ANON_COLLECTION`，默认 `anon_sandbox`）+ `Settings.ANON_COLLECTION` property |
| `app/store/client.py` | 新增 `collection_name(user_id)`：登录→`user_{id}`，匿名→`ANON_COLLECTION`；`get_collection` 改为复用它 |
| `app/store/documents.py` | 三处内联的 collection 名拼接改为 `collection_name(user_id)` |
| `app/store/__init__.py` | 导出 `collection_name` |
| `app/knowledge_agent/releases.py` | `_legacy_collection(None)` 不再回退 `CHROMA_COLLECTION`；`_tenant_key(None)` 由 `"global"` 改为 `"anon"` |

**注意**：`_tenant_key` 改名后，历史 `tenant_key='global'` 的 release 记录不再被读取（匿名会回退到匿名沙箱）。这是**安全方向**的失联，不会造成泄漏。

---

## 2. 写类端点强制登录

**问题**：`upload` / `upload-text` / `delete` 使用 `get_optional_user`，匿名即可写入全局共享库并删除他人内容。

**修法**：三个端点改 `Depends(get_current_user)`，匿名 401。读类端点（`stats` / `search` / `context` / `ask` / `ask/stream`）**保留匿名**——前端有"跳过登录"入口，匿名体验需要保留，其数据落在独立沙箱。

> 写入是持久化副作用，不能以"体验"为名对匿名开放；读取只影响本次请求，可以。

---

## 3. 对话记忆按用户隔离

**问题**：`api/logos.py` 所有用户（含匿名）追加到同一个 `data/memory/YYYY-MM-DD.md`，甲的对话总结乙能读到，且"第 N 次对话"计数是全站共享的。

**修法**：落 `<DATA_DIR>/memory/users/{scope}/YYYY-MM-DD.md`，`scope = user_{id}` 或 `anon`。

**同步修复的越权**：`/memory/scan` 与 `/memory/select` 此前把 query/body 里的 `root` 直接当路径扫描（**任意目录内容探测**，可枚举文件并读取前 30 行），且无认证。现改为：

- 需登录（`get_current_user`）
- 默认 root = **当前用户自己的**记忆目录
- 自定义 root 必须落在白名单内（当前用户目录 + `FILE_MEMORY_ROOT`），否则 403

---

## 4. 用量记录加归属

**问题**（三个）：

1. `get_usage` 签名写成 `user_id: Optional[int] = Depends(get_optional_user)` —— 注入的其实是整个 user dict；
2. `_read_today_usage()` 不做任何过滤，返回**全站**当日用量与成本；
3. 日限额是全局的。

**修法**：`log_token_usage(..., user_id=)` 写入归属字段；`_read_today_usage(user_id)` 严格相等过滤（缺字段按匿名处理）。限额暂留全局，注释标明待 `tenants` 表启用后切换。

**顺带发现**：`log_token_usage` 在此之前**从未被任何代码调用**（只有定义）。已在 `generate/service.py` 的非流式成功路径接上（延迟导入避免循环依赖，写入失败不影响主流程）。

> ⚠️ **流式路径仍不记录**：SSE chunk 默认不返回 usage，需请求体带 `stream_options={"include_usage": true}`，而该参数并非所有 OpenAI 兼容厂商都支持（不支持的会直接 400）。未确认部署厂商支持前不开启，也不做静默估算以免污染用量口径。

---

## 5. 无鉴权端点收口

| 端点 | 原状 | 现在 |
|---|---|---|
| `GET /knowledge/strategy` | 匿名可读 | 需登录 |
| `PATCH /knowledge/strategy` | **匿名可改全局 RAG 策略** | 需 `admin` |
| `GET /knowledge/cache/stats` | 匿名可读 | 需登录 |
| `DELETE /knowledge/cache` | **匿名可清空全站缓存** | 需 `admin` |
| `GET /agents/memory/scan` | 匿名 + 任意路径 | 需登录 + root 白名单 |
| `POST /agents/memory/select` | 匿名 + 任意路径 | 需登录 + root 白名单 |
| `GET /agents/loops` | 匿名返回**全部用户**的 loop | 匿名只返回 `user_id IS NULL` 的 loop |

`list_loop_groups(user_id, *, include_all=False)`：`user_id=None` 且非 `include_all` 时按 `WHERE user_id IS NULL` 过滤；`include_all=True` 仅供系统级调用。

**此前已修、无需重复**：`pause-all` 的 GET（`get_current_user`）与 POST（`require_role("admin")`）；流式缓存的 namespace（`stream/service.py` 已有 `_cache_namespace()`）。

---

## 6. memory.db 路径

**问题**：`app/memory/db.py` 硬编码 `os.path.dirname(__file__)/../../memory.db` → 容器内解析为 `/app/memory.db`，而数据卷只挂了 `/app/data`，**记忆库不在卷内，容器重建即丢**。

**修法**：`DB_PATH = os.path.join(DATA_DIR, "memory.db")`。

> 部署注意：线上若有旧的 `/app/memory.db`，需手工搬到 `<DATA_DIR>/memory.db`，否则历史记忆/画像读不到。

---

## 7. 验收方法

**自动化**：`cd backend && python3 -m pytest test/ -q` → 389 passed / 0 failed。

本次新增的回归防线：

- `test_anon_collection_never_falls_back_to_global` —— 匿名 collection 名绝不等于全局库
- `test_write_endpoints_require_login` —— 三个写类端点匿名 401
- `test_anon_search_uses_isolated_sandbox` —— 匿名检索看不到登录用户的内容
- `test_strategy_requires_auth` —— GET 401 / 普通用户 403 / admin 200
- `test_cache_clear_requires_admin` —— 匿名 401、普通用户 403
- `test_logos_isolates_per_user` —— 登录用户的总结不落进匿名目录

**手工验证**（部署后）：

```bash
# 1. 匿名写 → 401
curl -X POST "$HOST/api/v1/knowledge/upload-text?text=x"

# 2. 匿名改全局策略 → 401
curl -X PATCH "$HOST/api/v1/knowledge/strategy" -d '{"retrieval":{"top_k":10}}'

# 3. 匿名清缓存 → 401
curl -X DELETE "$HOST/api/v1/knowledge/cache"

# 4. 匿名查 loop 列表 → 不应出现他人 loop
curl "$HOST/api/v1/agents/loops"
```

---

## 8. 关于测试中的 100 个 errors

全部为环境限制，**非代码问题**：WorkBuddy 沙箱拦截 pytest 临时目录创建 ——

```
PermissionError: EEXIST: file already exists, mkdir '/private/var/folders/.../pytest-of-root'
  at .../cli/vendor/shim/sitecustomize.py:501
```

已用 `git worktree add /tmp/orbit-base HEAD` 在**改动前的干净树**上跑同一批用例对照，报错一致，证明与本次改动无关。

---

## 9. 未做（后续）

- 未 push（等待确认）。
- 线上旧 `data/memory/*.md` 与 `backend/memory.db` 需手工迁移到新位置。
- 按租户配额仍未启用（`tenants.max_*` 列未接）。
- 流式 token 用量未记录（见 §4）。
- Postgres + RLS、匿名会话级沙箱、Agent 沙箱隔离属 Phase 1/2（见 `docs/MULTI-TENANT-PLAN.md`）。
