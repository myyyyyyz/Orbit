# Orbit 上线部署记录（腾讯云轻量应用服务器）

> 部署日期：2026-09-25 ｜ 分支：`dev/optimize`
> 访问地址：**http://111.230.136.238**

---

## 1. 部署拓扑

```
                     互联网（80 端口）
                            │
                    ┌───────▼────────┐
                    │  Caddy (宿主)   │  反向代理
                    └───┬────────┬───┘
       /api/*、/health* │        │ 其余请求
                /ready  │        │
              ┌─────────▼──┐  ┌──▼──────────┐
              │ orbit-backend│  │orbit-frontend│
              │  FastAPI:8001│  │Next.js:3000  │
              └──────┬───────┘  └──────────────┘
                     │
              ┌──────▼────────────────────────┐
              │ Docker 卷 orbit_orbit_data     │
              │  /app/data/multitenant.db      │  SQLite（用户/会话/Agent 状态）
              │  /app/data/chroma_db           │  ChromaDB 向量库
              │  /app/data/uploads             │  上传文件
              │  /app/data/.cache/huggingface  │  embedding 模型缓存
              └───────────────────────────────┘
```

**同源设计**：前端与 API 都从 80 端口进出，天然没有跨域问题，只需放通一个端口。

| 组件 | 位置 | 说明 |
|---|---|---|
| 服务器 | 广州 · `lhins-mm3daxmx` | 2 核 2G / 50G SSD / 4Mbps |
| 仓库 | `/opt/orbit` | 从 GitHub `dev/optimize` 克隆 |
| 配置 | `/opt/orbit/.env` | 权限 600，**不入仓库** |
| 反代 | `/etc/caddy/Caddyfile` | 宿主 Caddy，占用 80 |
| 容器 | `orbit-backend` / `orbit-frontend` | 均 `restart: unless-stopped` |

---

## 2. 部署要点（踩过的坑）

### 2.1 `alembic.ini` 与实际库路径分叉（已在代码中修复）

`alembic.ini` 的 `sqlalchemy.url = sqlite:///../multitenant.db` **相对进程 CWD** 解析，而应用库路径由 `settings.DATABASE_URL` **相对 `__file__`** 解析。未设 `DATABASE_URL` 时二者指向不同文件 → 迁移建表到一个库、应用读另一个库 → 注册报 `no such table: users`。

- compose 中已显式设置 `DATABASE_URL: sqlite:////app/data/multitenant.db`，容器路径下不会触发
- 代码侧 `init_db()` 已改为无条件用 `settings.DATABASE_URL` 覆盖该值

### 2.2 依赖下载必须走国内镜像（否则构建以小时计）

| 源 | 镜像地址 | 效果 |
|---|---|---|
| apt (宿主/容器) | `mirrors.tencentyun.com` | 内网直连 |
| PyPI | `https://mirrors.tencentyun.com/pypi/simple/` | 实测 **100–300 MB/s** |
| npm | `https://registry.npmmirror.com` | 公网，受 4Mbps 限制 |
| Docker Hub | `https://mirror.ccs.tencentyun.com` | 内网加速 |

通过 `docker-compose.yml` 的 build args 注入（默认留空 → 官方源，CI 行为不变）：

```bash
# .env
DEBIAN_MIRROR=mirrors.tencentyun.com
PIP_INDEX_URL=https://mirrors.tencentyun.com/pypi/simple/
NPM_REGISTRY=https://registry.npmmirror.com
```

### 2.3 HuggingFace 不可达（不修则服务起不来）

实测 `https://huggingface.co` 在该机器上**超时（HTTP 000）**，而 `https://hf-mirror.com` 正常（0.4s）。后端启动时 `preload_model()` 会加载 `all-MiniLM-L6-v2`，直连官方源必然失败。

compose 已为 backend 设置 `HF_ENDPOINT`（默认 `https://hf-mirror.com`）。

### 2.4 2G 内存的前端构建风险

内存账：`Mem 1967MB + Swap 4035MB`。宿主机 `docker compose build` 是**串行**执行前后端，构建期没有运行中的服务抢内存，实测 Next.js 编译峰值未触发 OOM（编译仅 19 秒）。

已额外创建 `/swap2.img`（2G）作为缓冲，写入 `/etc/fstab` 持久化。

### 2.5 镜像体积

`orbit-backend` 约 **10.5GB** —— `sentence-transformers` 会拉取带 CUDA 依赖的 PyTorch。机器无 GPU，这些库不会被使用。若需瘦身，可在 Dockerfile 中改用 CPU-only 源：

```dockerfile
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
```

（会显著减小镜像与构建时间，但需注意与 `sentence-transformers` 的版本兼容。）

---

## 3. 日常运维

所有命令在服务器 `/opt/orbit` 目录下执行。

### 查看状态

```bash
docker compose ps                    # 容器状态（含 healthy）
docker compose logs -f backend       # 后端日志（structlog JSON）
docker compose logs -f frontend
curl -s localhost/ready              # 就绪探针
curl -s localhost/health/detail      # 依赖明细
free -m; df -h /                     # 资源余量
```

### 更新代码（发布新版本）

```bash
cd /opt/orbit
git pull origin dev/optimize
docker compose build backend frontend   # 依赖未变时秒级完成
docker compose up -d                    # 滚动重建变更的容器
docker compose ps
```

### 重启 / 停止

```bash
docker compose restart backend    # 只重启后端
docker compose down               # 停止（数据卷保留）
docker compose up -d              # 启动
```

### 备份数据

所有持久化数据都在 Docker 卷 `orbit_orbit_data`：

```bash
docker run --rm -v orbit_orbit_data:/data -v /root/backup:/backup alpine \
  tar czf /backup/orbit-$(date +%F).tar.gz -C /data .
```

### 初始管理员

```bash
docker compose exec backend python -m app.admin_cli promote <username>
docker compose exec backend python -m app.admin_cli list
```

---

## 4. 已知约束（上线前请知悉）

| 约束 | 说明 | 影响 |
|---|---|---|
| **单副本假设** | SSE 运行时队列、语义缓存、令牌撤销表、限流计数器都在**进程内内存** | **必须保持副本数 = 1**；扩容需先外置 Redis |
| Access Token 时效 | 60 分钟（原 7 天），前端已实现 401 自动刷新 | 不做刷新的老客户端 60 分钟后会 401 |
| 令牌存储 | 仍存 localStorage | 存在 XSS 窃取风险，改 httpOnly cookie 需 CSRF 方案 |
| 数据库 | SQLite（单文件） | 并发写受限；多实例部署需换 PostgreSQL |
| 内存余量 | 2G 总内存，服务常驻约 1.2G | 高峰并发或大文件上传可能触发 swap |
| 带宽 | 4Mbps | 首次拉代码/镜像较慢；已配镜像源规避 |
| `/health` 语义 | 变为纯存活探针，恒 200 | 判断依赖健康请用 `/health/detail` 或 `/ready` |
| cron `day_of_week` | 语义修正为 **0 = 周日** | 存量定时任务触发日可能偏移一天，需复核 |
| 实例到期 | **2026-10-25**（手动续费） | 到期后服务中断 |

---

## 5. 本次部署验证结果

从**外部网络**实测（非服务器本机）：

| 验证项 | 结果 |
|---|---|
| `/` 前端页面 | HTTP 200，23406 字节，0.24s |
| `/health` 存活探针 | 200 `{"status":"ok"}` |
| `/health/detail` 依赖明细 | 200 `chromadb: ok, sqlite: ok, llm_api: ok` |
| `/ready` 就绪探针 | 200 |
| 注册接口 | 200，返回 `role='user'` + access/refresh 双令牌，`expires_in=3600` |
| 登录 / `/auth/me` | 200 |
| RBAC（普通用户调管理接口） | **403**，含统一错误结构与 `request_id` |
| 匿名调管理接口 | **401** |
| 知识库 API | 200，反代连通 |
| 安全响应头 | `X-Frame-Options` / `X-Content-Type-Options` / `Referrer-Policy` / `Permissions-Policy` 均存在 |
