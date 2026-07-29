---
name: knowledge-qa
type: benchmark-scene
description: 知识库问答验证 — 上传文档后 AI 基于知识库回答问题并引用原文
---

# 知识库问答验证

## 0. 对比维度声明

- 维度 1：文档类型（PDF / MD / TXT）
- 维度 2：检索精度（回答是否引用原文）
- 维度 3：文档数量（1 份 / 5 份 / 10 份）

## 1. 场景类型

```yaml
type: backend
  # 纯后端验证，不涉及前端 UI
```

## 2. Dev Server 配置

```yaml
dev_server:
  knowledge_base:
    start_command: "cd ../mvp/knowledge-base/backend && uvicorn app.main:app --reload --port 8001"
    url: "http://localhost:8001"
    health_check: "curl -s http://localhost:8001/health"
  timeout_seconds: 30
```

---

## 3. Trigger（触发条件）

- 用户上传文档后提问
- 或 loop-state.md 中 status=pending 的 knowledge-qa 任务

---

## 4. Verify（验证规则）

### Gate G1: 知识库服务可用
- 验证内容：
  ```
  curl http://localhost:8001/health
  curl http://localhost:8001/api/knowledge/stats
  ```
- 通过标准：返回 `{"status": "ok"}` 和统计信息

### Gate G2: 文档上传与索引
- 验证内容：
  ```
  # 上传测试 MD 文档
  curl -X POST http://localhost:8001/api/knowledge/upload-text \
    "?text=恋心记录是一个情侣Web应用，支持时间线、纪念日倒计时、图片上传、实时定位功能。后端使用FastAPI，前端使用原生HTML/CSS/JS。" \
    "&source=lovediary-readme"
  # 验证索引
  curl http://localhost:8001/api/knowledge/stats
  ```
- 通过标准：stats.total_chunks >= 1

### Gate G3: 语义检索
- 验证内容：
  ```
  curl "http://localhost:8001/api/knowledge/search?q=恋心记录有哪些功能"
  ```
- 通过标准：返回的 result.text 包含"时间线"、"纪念日"等关键词

### Gate G4: 引用原文
- 验证内容：检索结果中 text 字段是原始文档内容
- 通过标准：可以追溯到原文

---

## 5. Fallback（失败处理）

| Gate 失败 | 动作 |
|-----------|------|
| G1 FAIL | 检查知识库服务日志 |
| G2 FAIL | 检查文件解析和切割逻辑 |
| G3 FAIL | 检查 Embedding 和检索参数 |
| G4 FAIL | 检查 chunk 存储完整性 |
