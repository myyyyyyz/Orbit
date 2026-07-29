# Master Skill 使用示例

## 自动触发场景

Master Skill 由 AI 根据 `description` 中的触发条件自动识别调用。以下场景会自动触发：

### 示例 1：Bug 修复
**用户输入**：
```
这个 bug 怎么修？RuntimeError: Event loop is closed
```

**AI 行为**：
1. 自动触发 Master Skill
2. 搜索 GitHub Issues：`"Event loop is closed" type:issues`
3. 搜索 Stack Overflow 高票答案
4. 给出修复方案并标注来源

**预期输出**：
```
这个问题通常出现在异步代码中重复使用了已关闭的事件循环。

根据 [GitHub Issue python/cpython#XXXX](链接) 和 [Stack Overflow 高票答案](链接)：

解决方案：
1. 使用 asyncio.new_event_loop() 创建新循环
2. 或用 asyncio.run() 替代直接操作 loop
3. 检查是否有同步代码混用了异步 API

来源：GitHub Issues（2025-12）+ Stack Overflow（2026-01）
```

### 示例 2：技术选型
**用户输入**：
```
推荐一个 Python 的 HTTP 客户端库，要支持异步
```

**AI 行为**：
1. 自动触发 Master Skill
2. 搜索 GitHub：`http client python async language:python&sort=stars`
3. 搜索 InfoQ / Medium 架构对比文章
4. 给出选型结论

**预期输出**：
```
根据 GitHub Star 趋势（2026-05）和 [Medium 对比文章](链接)：

| 库 | Stars | 异步支持 | 推荐场景 |
|---|---|---|---|
| httpx | 15K+ | ✅ 原生 | 现代项目首选 |
| aiohttp | 15K+ | ✅ 原生 | 需要服务端功能时 |
| requests | 65K+ | ❌ 需配合 | 仅同步场景 |

推荐：httpx
- 同时支持 sync/async API
- 与 requests API 兼容
- 活跃维护，近 3 个月有更新

来源：GitHub（2026-05）+ [InfoQ 评测](链接)
```

### 示例 3：AI 相关问题
**用户输入**：
```
怎么设计一个带记忆功能的 AI Agent？
```

**AI 行为**：
1. 自动触发 Master Skill（AI 专项规则）
2. 第一轮搜索至少 3 家厂商官方：
   - Anthropic Engineering Blog: `site:anthropic.com/engineering "agent memory"`
   - OpenAI Cookbook: `site:cookbook.openai.com "memory"`
   - LangChain Docs: `site:python.langchain.com "memory"`
3. 第二轮 GitHub 验证：`"agent memory" implementation`
4. 第三轮社区交叉验证

**预期输出**：
```
根据 Anthropic Engineering Blog（2026-04）、OpenAI Cookbook（2026-03）和 LangChain Docs：

AI Agent 记忆设计的三种模式：
1. **短期记忆（Context Window）**：将历史对话直接放入 prompt
2. **长期记忆（Vector Store）**：用 RAG 检索相关历史信息
3. **混合记忆（Summary + RAG）**：先摘要再检索，平衡精度与成本

Anthropic 推荐（2026-04）：
- 简单任务：直接用 context window
- 复杂任务：RAG + 结构化记忆（entity-based memory）

实现参考：
- GitHub: langchain-ai/langchain（memory 模块）
- GitHub: microsoft/autogen（group chat memory）

来源：
- [Anthropic Engineering Blog, 2026-04](链接)
- [OpenAI Cookbook, 2026-03](链接)
- [LangChain Docs](链接)
- GitHub 实现验证（2026-05）
```

---

## 手动触发场景

在 CodeBuddy CLI 中，可以直接输入 `/master` 强制触发：

```bash
# 强制触发 Master Skill 进行搜索
/master 帮我分析这个报错

# 强制触发并带上下文
/master 搜索 Go 微服务最佳实践
```

在 IDE 中，AI 自动识别后会在回复中标注：
```
🤖 [Master Skill 已触发] 正在搜索...
```
