---
name: couple-diary-mvp
type: benchmark-scene
description: 恋爱情侣记录 Web 应用 MVP — 时间线 + 发布瞬间(含图片) + 纪念日倒计时 + 实时定位
---

# 恋心记录 MVP

## 0. 对比维度声明

- 维度 1：页面功能（时间线 / 发布 / 纪念日）
- 维度 2：设备尺寸（手机 / 平板 / 桌面）
- 维度 3：数据状态（空 / 有数据 / 错误）

## 1. 场景类型

```yaml
type: fullstack
  # 有 FastAPI 后端 + 前端 UI，触发 User Agent UX 审查
```

## 2. Dev Server 配置

```yaml
dev_server:
  backend:
    start_command: "cd ../mvp/lovediary/backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    url: "http://localhost:8000"
    health_check: "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health"
  frontend:
    start_command: "cd ../mvp/lovediary/frontend && python3 -m http.server 3000"
    url: "http://localhost:3000"
    health_check: "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000"
  timeout_seconds: 30
```

---

## 3. Trigger（触发条件）

- 用户发起："帮我搭建一个恋爱情侣记录网站"
- 或 loop-state.md 中 status=pending 的 couple-diary 任务

---

## 4. Verify（验证规则）

### Gate G1: 后端 API 可用
- 验证内容：
  ```
  # 健康检查
  curl http://localhost:8000/health
  # 创建瞬间
  curl -X POST http://localhost:8000/api/moments \
    -H "Content-Type: application/json" \
    -d '{"title":"第一次约会","content":"在西湖边散步，夕阳很美","date":"2025-06-15","tags":["约会","西湖"]}'
  # 获取时间线
  curl http://localhost:8000/api/moments
  # 获取纪念日
  curl http://localhost:8000/api/anniversaries
  ```
- 通过标准：所有端点返回 200，数据正确读写

### Gate G2: 前端页面可访问
- 验证内容：
  ```
  # 首页加载
  curl -s http://localhost:3000 | head -20
  ```
- 通过标准：返回完整 HTML，包含时间线、发布入口、纪念日展示

### Gate G3: 前后端联通
- 验证内容：前端页面正常加载后端数据（时间线有数据展示）
- 通过标准：前端能成功调用后端 API 并渲染数据

### Gate G4: 响应式布局
- 验证内容：手机 (375px) / 平板 (768px) / 桌面 (1440px) 三个视口截图
- 通过标准：三视口下布局均正常，无溢出、无重叠

### Gate G5: UI 设计品质
- 验证内容：配色温暖浪漫（粉色系+暖渐变+圆角卡片），非千篇一律模板，有恋爱氛围感
- 通过标准：User Agent UX 审查通过（检查配色、排版、微交互）

### Gate G6: 数据安全
- 验证内容：
  ```
  # 无 token 访问应被拒绝
  curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/moments
  # 跨用户数据不应泄露
  ```
- 通过标准：未授权请求返回 401/403，不同用户数据隔离

### Gate G7: 图片上传
- 验证内容：
  ```
  # 上传带图片的瞬间
  curl -X POST http://localhost:8000/api/moments \
    -F "title=我们的照片" \
    -F "content=在西湖边的合影" \
    -F "date=2025-06-15" \
    -F "image=@test.jpg"
  # 获取时间线，验证图片可回显
  ```
- 通过标准：图片上传成功，前端可正常展示图片

### Gate G8: 实时定位
- 验证内容：
  ```
  # 创建带位置的瞬间
  curl -X POST http://localhost:8000/api/moments \
    -H "Content-Type: application/json" \
    -d '{"title":"西湖","content":"雷峰塔下","date":"2025-06-15","latitude":30.2417,"longitude":120.1485,"location_name":"杭州西湖"}'
  # 获取时间线，验证位置信息展示
  ```
- 通过标准：位置数据正确存储，前端可以地图或文字形式展示

---

## 5. Fallback（失败处理）

| Gate 失败 | 动作 |
|-----------|------|
| G1 FAIL | 检查 FastAPI 代码逻辑，修复后重试（最多 3 次） |
| G2 FAIL | 检查前端文件结构，修复后重试（最多 3 次） |
| G3 FAIL | 检查前后端 API 路径是否匹配、CORS 配置 |
| G4 FAIL | 调整 CSS/布局，修复后重试 |
| G5 FAIL | 参考 frontend-design skill 调整设计，User Agent 重新审查 |
| G6 FAIL | 检查认证中间件、数据隔离逻辑 |
| G7 FAIL | 检查文件上传接口、存储路径 |
| G8 FAIL | 检查位置字段定义和前端渲染 |

## 变更范围

- 允许修改的文件：`../mvp/lovediary/backend/` 整个目录、`../mvp/lovediary/frontend/` 整个目录
- 最大修改文件数：不限
- 允许的修改类型：新建文件、修改文件

## effort_tier 约束

- 首次开发：`dev`（分钟级自测）
- 最终验收：`full`（需用户 checkpoint 签字）
