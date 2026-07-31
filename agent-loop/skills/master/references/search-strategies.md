# 搜索策略详情

## 策略 1：Bug / 报错排查

### 搜索流程
1. **GitHub Issues**：搜索完整错误信息（用引号精确匹配）
   - 搜索范围：项目自身的 Issues + 依赖库的 Issues
   - 重点看：Closed Issues、带 PR 链接的 Issues
2. **Stack Overflow**：搜索错误信息的核心部分（去除路径、行号等本地信息）
   - 看高票答案的解决方案和评论区讨论
3. **SegmentFault**：搜索中文错误信息或中文技术方案的异常

### 判断标准
- 多个 GitHub Issue 指向同一修复方案 → 大概率正确
- Stack Overflow 答案票数 > 50 → 有参考价值
- 近 1 年内更新的答案优先

## 策略 2：最佳实践 / 技术选型

### 搜索流程
1. **GitHub**：搜索相关主题的顶级项目（按 Star 排序）
   - 看 README 中的 "Why" 和对比章节
   - 看 example/ 和 demo/ 目录理解推荐用法
   - 看项目的 Star 趋势（是否仍在活跃增长）
2. **InfoQ**：搜索架构案例和技术决策分析
3. **掘金**：搜索中文环境下的落地经验和踩坑总结

### 判断标准
- GitHub Star > 1000 且在持续增长 → 社区认可
- InfoQ 文章来自大厂架构师 → 权威参考
- 多个独立来源推荐同一实践 → 行业共识

## 策略 3：性能优化

### 搜索流程
1. **GitHub**：搜索 benchmark/ 目录和性能相关的 Issue/PR
   - 看项目自己的 benchmark 数据
   - 看社区贡献的性能对比（如 "X vs Y performance"）
2. **Stack Overflow**：搜索具体的慢查询或性能瓶颈关键词
3. **博客园 / DZone**：搜索深度性能调优文章

### 判断标准
- Benchmark 数据可复现（有明确的环境说明）
- 优化方案的 trade-off 被讨论过（没有完美方案）

## 策略 4：架构设计

### 搜索流程
1. **InfoQ**：搜索相关架构案例
2. **Medium / High Scalability**：搜索系统设计文章
3. **阿里云 / 腾讯云开发者社区**：搜索企业级架构实践

### 判断标准
- 文章描述了具体的业务量和 QPS（不是凭空设计）
- 有架构图和数据流说明
- 讨论了 trade-off 和失败尝试

## 策略 5：安全相关

### 搜索流程
1. **GitHub Security Advisories**：搜索相关依赖的已知漏洞
2. **OWASP**：搜索漏洞类型的防护指南
3. **CVE Details**：查询 CVE 编号的详细信息

### 判断标准
- CVE 评分 > 7.0 必须处理
- OWASP 推荐的防护方案是行业标准

## 策略 0：AI / Agent / LLM / RAG（最高优先级 — 覆盖通用搜索规则）

### 核心原则
**AI 领域的搜索规则与通用技术相反。GitHub 不是第一搜索源。**
AI 领域按周迭代，官方厂商文档和 Blog 是唯一权威的最新实践来源。

### 搜索流程（严格执行顺序）

**第 1 步：厂商官方源（至少 3 家，必须）**

按以下顺序搜索，找到相关官方文档或 Blog 文章：

1. **OpenAI** — `site:platform.openai.com {keyword}` 或 `site:cookbook.openai.com {keyword}`
2. **Anthropic** — `site:docs.anthropic.com {keyword}` 或 `site:anthropic.com/engineering {keyword}`
3. **AWS** — `site:aws.amazon.com/blogs/machine-learning {keyword}` 或 `site:docs.aws.amazon.com/bedrock {keyword}`
4. **Google** — `site:ai.google.dev {keyword}` 或 `site:deepmind.google {keyword}`
5. **Microsoft** — `site:learn.microsoft.com/en-us/azure/ai-services {keyword}`
6. **Meta** — `site:ai.meta.com/blog {keyword}` 或 `site:llama.meta.com {keyword}`

**第 2 步：GitHub 实现验证（基于第 1 步发现的关键词）**

基于官方最佳实践中的具体技术名词/方案名搜索：
- 搜索官方推荐的 SDK/框架的 GitHub 项目（如 `anthropic-sdk-python`、`openai-python`）
- 搜索官方 Cookbook/示例的 GitHub 仓库（如 `openai-cookbook`、`generative-ai`）
- 搜索官方 Blog 中提到的参考实现的 GitHub 项目
- 重点看：项目的 Star 趋势、最近 Issue（确认是否有已知问题）、最新 Release 版本号

**第 3 步：社区交叉验证**

- **Dev.to**：搜索 "{技术名} tutorial {年份}" — 找最新实战经验
- **Medium**：搜索 "{技术名} production" — 找生产环境踩坑
- **Hacker News**：搜索技术名 — 看社区讨论和争议点
- **Reddit r/MachineLearning / r/LocalLLaMA**：搜索具体问题 — 找社区实战反馈

### 判断标准（与通用策略不同！）

- **厂商官方 Blog/Docs** ≥ 任何 GitHub 项目（AI 领域厂商文档 > 开源项目）
- 官方 Suggested/Recommended 标记的实践 → 直接采纳
- 多家厂商（≥2 家）推荐同一模式 → 行业最佳实践
- GitHub AI 项目 Star 数 > 1000 但超过 6 个月未更新 → 可能已过时
- 社区文章超过 6 个月 → 必须检查是否仍适用
- 如果问题涉及特定模型（如 Claude API）→ 该模型厂商的建议权重最高

### AI 子场景特别策略

| 子场景 | 额外搜索源 | 注意 |
|--------|----------|------|
| Prompt 工程 | Anthropic Prompt Library, OpenAI Cookbook | 不同模型 Prompt 策略可能不同 |
| AI Agent 设计 | Anthropic Engineering Blog, LangChain/LlamaIndex Docs, Microsoft AutoGen | 先看官方 Agent 设计哲学，再看框架实现 |
| RAG 系统 | LlamaIndex Docs, LangChain Docs, Cohere Blog | 关注 Chunking 策略和 Embedding 选型 |
| AI SDK/API 使用 | 对应厂商的 SDK GitHub 仓库 Issues | Issue 区是最新问题的第一手来源 |
| 模型微调 | Hugging Face Forums, 对应厂商官方微调指南 | 关注硬件需求和成本估算 |
| AI 安全 | Anthropic Research Blog, OpenAI Safety, OWASP LLM Top 10 | 安全是快速演进的子领域 |
| 多模态 AI | Google Gemini Docs, OpenAI Vision Docs | 各家多模态能力差异很大 |
| **Agent Harness** | **Anthropic Engineering Blog → GitHub (shanraisshan/obra/affaan-m) → Settings参考** | **Claude Code 独家生态，Anthropic 是唯一第一方权威** |

### Agent Harness 专项搜索流程

Agent Harness 指 Claude Code 的代理基础设施：hooks、settings.json、tool 权限、
context: fork、sub-agent 调度、PreToolUse/PostToolUse 等。这是 Anthropic/Claude Code
的独家生态，第三方框架（LangChain/AutoGen 等）不适用。

**第 1 步：Anthropic 官方（唯一第一方权威）**
1. `site:anthropic.com/engineering "claude code" {keyword}` — 新特性、设计哲学
2. `site:docs.anthropic.com {keyword}` — API 层面的 agent 定义
3. Anthropic 的 Claude Code Changelog — 版本更新带来的 harness 变化

**第 2 步：GitHub 高星最佳实践仓库**
- `shanraisshan/claude-code-best-practice` (32K Stars) — 86+ tips，skills 规范
- `obra/superpowers` (135K Stars) — TDD 驱动 skill 开发
- `affaan-m/everything-claude-code` (176K Stars) — 48 agents, 182 skills
- `MuhammadUsmanGM/claude-code-best-practices` — 30+ guides, 11 templates
- `onmyway133/awesome-claude-code` — 精选列表
- `spences10/claude-skills-cli` — 渐进式加载校验工具

**第 3 步：社区**
- `site:dev.to "claude code" {keyword}` — 实战踩坑
- Hacker News 搜索 Claude Code — 社区讨论和争议

**注意**：Agent Harness 不需要查 OpenAI/AWS/Google/Meta 等其他厂商 —
各家的 agent 基础设施互不兼容，实践不能跨厂商迁移。

### 时效性铁律
- **近 1 个月内** → 高度相关，直接参考
- **1-3 个月内** → 检查是否有更新的替代方案
- **3-6 个月内** → 交叉验证 API 版本是否仍兼容
- **超过 6 个月** → 默认标记为"可能过时"，查找更新版本
- **超过 1 年** → 几乎肯定已过时，仅作历史参考

## 策略 6：前端 / UI

### 搜索流程
1. **GitHub**：搜索相关组件库和 UI 框架
2. **MDN**：查 Web API 兼容性和标准用法
3. **CSS-Tricks / Smashing Magazine**：搜索布局/响应式/动画最佳实践
4. **掘金**：搜索中文前端实战经验

### 判断标准
- MDN 是 Web 标准的权威来源
- GitHub Star 反映社区认可度
- CSS-Tricks 的技巧通常可直接落地

## 搜索技巧通用规则

1. **精确搜索用引号**：`"exact error message"`
2. **排除用减号**：`keyword -excluded_word`
3. **站内搜索用 site:**：`site:github.com keyword`
4. **限定时间**：优先选择近 1 年的结果
5. **多关键词组合**：先用具体短语，搜不到再拆成通用关键词
6. **交叉验证**：同一结论在 2 个以上平台出现才视为可靠
