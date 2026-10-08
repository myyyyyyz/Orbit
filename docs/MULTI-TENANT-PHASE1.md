# 多租户 Phase 1 交付说明（组织 + 个人私有空间）

> 状态：**已完成**（2026-10-08，分支 `dev/optimize`）
> 前置文档：[MULTI-TENANT-PLAN.md](./MULTI-TENANT-PLAN.md)（四层隔离设计与分阶段路线）、
> [MULTI-TENANT-PHASE0-FIXES.md](./MULTI-TENANT-PHASE0-FIXES.md)（Phase 0 直接漏洞修复）

## 1. 本轮目标

把已经存在但**从未参与隔离**的 `tenants` / `users.tenant_id` 骨架真正接通：
一套部署服务多个组织，组织之间数据、检索结果、缓存、用量、文件、记忆全部隔离。

用户确认的隔离口径是**两级粒度**：

- **组织共享**：同一组织内所有成员都能检索的文档（`t_{org}`）
- **个人私有**：只有本人能检索的文档（`p_{org}:{user}`）
- **读取语义**：一次检索 = 「组织共享库 ∪ 本人私有库」，不是二选一
- **匿名**：落在独立匿名沙箱，**不会**回退到全局库，也不会看到任何组织的数据

## 2. 核心抽象：TenantScope

`app/multitenant/context.py` 的 `TenantScope` 是不可变值对象（`frozen dataclass`），
同时承担四个职责，避免"同一个概念在多处各写一遍命名规则"的分叉：

| 派生属性 | 形态 | 用途 |
| --- | --- | --- |
| `collection` | `t_{org}` / `p_{org}:{user}` / `anon` | ChromaDB collection 名 |
| `storage_key` | `t:{org}` / `t:{org}:u:{user}` | 写入侧命名空间（缓存、用量、版本登记） |
| `read_key` | 同 `storage_key` | 读取侧命名空间（**含 user 维度**） |
| `tenant_prefix` | `t:{org}:` | 按组织批量清理（如某组织全部缓存） |
| `rel_path` | `tenants/{org}/users/{u}` / `anon` | 文件系统相对目录（拼在 `DATA_DIR` 下） |

**为什么 `read_key` 必须含 user 维度**：读取时是「组织共享 ∪ 本人私有」的合并结果，
若缓存只按租户隔离，同组织成员 A 提问命中的可能是由 B 的私有文档生成的答案。

命名统一走 `app/multitenant/naming.py`：`slug()` 保证 `[a-zA-Z0-9._-]`、3–63 字符、
首尾字母数字，对含非法字符的输入追加短哈希保证**不同输入不撞名**（ChromaDB 的硬约束）。

**fail-closed**：解析不到租户身份时落 `ANON_SCOPE`，绝不静默回退到全局库或"默认租户"。

## 3. 数据模型与迁移

迁移 `c4f1a9d27b30_tenant_membership.py`（Revises `f7a4c3a193d7`）：

1. `tenants` 加 `invite_code` / `owner_user_id` / `updated_at`，并回填邀请码 + 唯一索引
2. `users` 加 `tenant_role`（`owner` / `admin` / `member`），与平台级 `role` **分离**
3. `sessions` 加 `tenant_id`
4. **回填历史用户**：为每个尚无租户的用户创建 `org_u{id}` 组织并置为 `owner`，
   `sessions.tenant_id` 跟随其所属用户

### 迁移真实验证（非静态审读）

用临时库真实分段执行（先到旧 revision → 种入历史数据 → 升到 head）：

```
users:     (1,legacy_a,org_u1,owner) (2,legacy_b,org_u2,owner)
tenants:   org_legacy(invite_code 已回填) org_u1(owner=1) org_u2(owner=2)
sessions:  s1 → org_u1
无租户用户数 = 0 ；无邀请码租户数 = 0
```

## 4. 各层落点

| 层 | 落点 | 行为 |
| --- | --- | --- |
| 向量层 | `store/client.py`（`collection_name(scope)` 单一事实源）、`store/documents.py` | 按 scope 决定 collection；`delete_by_source` 返回删除条数 |
| 检索层 | `search/core.py`（跨 `read_scopes()` 合并）、`search/format.py` | 合并「共享 ∪ 私有」，结果标注「组织共享 / 我的文档」 |
| 版本发布 | `knowledge_agent/releases.py` | `_tenant_key(scope)=storage_key`，每个作用域独立 active 指针与回滚历史 |
| 文件层 | `multitenant/paths.py` | `DATA_DIR/tenants/{org}/users/{user}/...`；**记忆始终按人落盘** |
| 缓存层 | `cache/storage.py`（`purge_prefix`） | 命名空间 `{read_key}\|{collection}`，前缀清理不误伤其他组织/成员 |
| 用量层 | `api/usage.py` | `log_token_usage(..., tenant_id=)`，按租户汇总当日用量 |
| 记忆层 | `api/logos.py` | 写入当前用户自己的 memory 目录，不再共用一个 `memory/YYYY-MM-DD.md` |

## 5. 认证与授权

- 令牌 claim 带 `tenant_id` / `tenant_role`；**授权判定一律回查数据库**，不信任令牌快照
- `middleware/auth.py::bind_scope(user, scope)` 把身份写入请求级 `ContextVar`，
  下游检索/入库/文件/缓存/用量统一读取，**不再层层透传参数**（漏传就会落到全局库）
- `require_tenant_role("owner", "admin")` 管组织内权限，与平台级 `require_role` 互不继承
  （平台管理员 ≠ 所有组织的 owner）
- ⚠️ `get_current_user` **不回查 DB**，只读令牌 → 因此 `/auth/join` 必须**换发令牌**
  （已有回归用例 `test_join_rotates_token_to_new_tenant` 锁定该行为）

## 6. API 变更

新增 `/api/v1/tenants/*`：

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| GET | `/tenants/me` | 登录 |
| GET | `/tenants/me/members` | 登录（不回传凭据字段） |
| PATCH | `/tenants/me`（改名） | owner / admin |
| POST | `/tenants/me/invite-code`（轮换） | owner / admin |
| PATCH | `/tenants/me/members/{user_id}`（改角色） | 仅 owner，含"最后一个 owner 不可降级"保护 |

变更的既有接口：

- `POST /auth/register` 新增可选 `org_name`（新建组织）/ `invite_code`（加入组织）
- `POST /auth/join` **换发令牌**（旧 Token 的 `tenant_id` 是加入前组织的快照）
- `POST /auth/login`、`GET /auth/me` 返回体新增 `tenant_role` / `tenant_name` / `invite_code` / `collections`
- 知识库写类端点新增 `scope` 查询参数（`shared` 默认 / `personal`）
  —— **scope 只是"写到哪"的选择器，不是身份来源**，客户端无法用它越权

## 7. 前端入口

| 位置 | 改动 |
| --- | --- |
| `lib/api.ts` | `Collections` / `TenantSummary` / `TenantMember` 类型；`auth.join`；`tenants` API；知识库写操作支持 `scope` |
| `lib/auth-context.tsx` | 会话里持久化组织信息（`orbit_tenant`），注册/登录/加入组织三条路径统一写入 |
| `components/auth/auth-form.tsx` | 注册可选填「组织名 / 邀请码」，附行为说明 |
| `components/knowledge-base/kb-panel.tsx` | 「组织共享 / 仅我的」空间切换（匿名禁用私有），上传与删除按空间执行 |
| `components/settings/tenant-panel.tsx`（新） | 组织名、邀请码（复制/重置）、成员列表与角色、用邀请码加入其他组织 |

## 8. 测试与验证

| 检查 | 结果 |
| --- | --- |
| 后端全量 | **442 passed / 0 failed**（101 个 ERROR 为本机沙箱 tmpdir 权限限制，与代码无关） |
| 前端 typecheck | 通过 |
| 前端 lint | 0 error（3 个既有 warning） |
| 前端测试 | 36 passed |
| alembic 迁移 | 空库 + 带历史数据两条路径均实跑通过 |

新增/重写的隔离回归用例覆盖：跨组织不可见、同组织私有不可见、
匿名沙箱不回退全局库、缓存前缀清理不误伤、个人作用域独立版本登记、
`scope` 参数无法伪造租户身份、logos 记忆跨租户物理隔离。

**测试环境隔离补丁**：`conftest.py` 之前漏了 `DATA_DIR`——
它是 `app.config` 的模块级常量，不覆盖会让"记忆文件/用量日志/租户目录"写进真实 `data/`
并跨次运行累积（曾表现为"logos 用户隔离用例失败"，实为测试自身污染）。

## 9. 未做（后续阶段）

- **Phase 2**：Postgres + RLS 下沉到数据库层；需 `set_config(..., is_local=true)` 规避连接池泄漏
- **Phase 3**：配额计量、任务沙箱、Redis 化进程内状态（当前架构隐含**副本数必须 = 1**）
- 组织解散 / 成员退出 / 个人数据导出
- 前端知识库 Workbench（`knowledge-workbench/*`）尚未接 `scope` 选择

## 10. 已知缺口（未在本轮修）

- ⚠️ `/api/v1/knowledge/strategy` 的 GET 与 PATCH **仍无鉴权依赖**（与 pause-all 同类问题，优先项）
- `app/memory/db.py` 路径虽已改由 `DATA_DIR` 派生，但容器内落在 `/app/memory.db`（**不在数据卷**），容器重建即丢
- 令牌仍存 localStorage
- embedding 仍是英文模型 `all-MiniLM-L6-v2`（中文检索一般，换模型需重建向量库）
