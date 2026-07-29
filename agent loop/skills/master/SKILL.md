---
name: master
description: >-
  遇到技术问题时，自动从 GitHub 及全球专业平台搜索最佳实践和解决方案。
  触发于用户提出技术问题、询问"怎么做"、"最佳实践"、"有没有更好的方案"、
  "怎么优化"、"这个 bug 怎么修"、"推荐什么技术/工具/框架"等。
  触发于需要做技术选型、架构设计、性能调优、安全加固等决策场景。
  触发于代码审查中发现可疑模式需要外部参考验证时。
  触发于 AI/Agent/LLM/RAG/大模型/Prompt 工程/AI SDK 等 AI 相关技术问题。
  触发于 Agent Harness（hooks/settings/tool 编排/context fork/sub-agent 调度等）基础设施问题。
  禁止在纯业务讨论、非技术性需求澄清时触发。
allowed-tools: Read, Write(memory/*), Grep, Glob, WebFetch, WebSearch, Bash(curl:*)
user-invocable: true
disable-model-invocation: false
---

# Master — 技术知识获取与内化

> **能力边界声明 / Capability Boundary**
>
> 本 Skill 是**行业研究脚手架**，不是行业真理机。它提供的是基于公开网络资料的最佳实践整理，适合快速建立领域认知框架、生成垂直 agent 的第一版 skill、辅助技术决策参考。
>
> **不适合**：直接用于高风险决策（医疗诊断、金融投资、法律合规、安全审计等）、替代真实专家判断、或作为强事实准确性的唯一依据。所有输出必须经过人工审校后再用于生产环境。

## 核心原则

遇到任何技术问题，先搜索再回答。你不是在凭记忆回答，你是在做研究。

**研究铁律**：每条技术结论必须有可追溯的信源支撑。没有信源支撑的观点必须明确标注为"推测"。

### 通用原则：GitHub 永远是第一搜索源

搜到的精华，转化为记忆，下次直接用。

### AI/Agent/Harness 相关例外

**当问题涉及 AI/LLM/Agent/RAG/Prompt 工程/AI SDK/Agent Harness 等 AI 相关技术时，搜索优先级反转：**

```
厂商官方（OpenAI/Anthropic/AWS/Google/Microsoft/Meta）→ GitHub → 开发者社区
```

AI 领域变化极快（周级别迭代），厂商官方博客和文档是唯一权威的最新实践来源。
Agent Harness（hooks、settings、tool 编排、context: fork 等）的权威参考来自 Anthropic Engineering Blog 和 Claude Code 官方文档。
GitHub 上的 AI 项目可能基于过时的 API 版本或已被官方推翻的实践。
其他开发者社区的内容在 AI 领域滞后严重，仅作补充参考。

## 模糊边界处理 / Ambiguous Boundary Handling

技术问题与设计讨论之间没有清晰边界。当遇到以下**模糊场景**时，**禁止直接跳过**——必须先触发，然后让用户决定。

### 识别"模糊场景"

以下情况是关键信号，表示问题可能包含技术搜索价值：

| 信号 | 示例 | 判断 |
|------|------|------|
| 讨论涉及具体技术名词 | "Agent 记忆管理方案" | ✅ 触发，先问 |
| 讨论涉及架构/设计模式 | "这个系统怎么分层" | ✅ 触发，先问 |
| 用户说"讨论一下"/"帮我设计" | "帮我设计一个缓存方案" | ✅ 触发，先问 |
| 纯业务逻辑、非技术性 | "这个需求的业务背景是..." | ❌ 不触发 |
| 项目管理/流程 | "排期怎么安排" | ❌ 不触发 |
| 闲聊/主观评价 | "这个框架好不好用" | ✅ 触发，先问 |

### 触发后行为

当判定为模糊场景时，**先触发 skill，再执行以下流程**：

```
检测到模糊场景
  → 不直接搜索（避免浪费搜索在用户可能不需要的方向）
  → 用一句话确认用户意图并向用户提问
  → 格式：
    "你的问题涉及 [技术领域]，需要我先搜索 [关键主题] 的业界最佳实践再回答吗？"
  → 等待用户回复：
    - 用户说"好/搜/做/对" → 立即执行完整搜索流程
    - 用户说"不用/先讨论" → 跳过搜索，直接基于现有知识讨论
    - 用户说其他 → 按回复内容重新判断
```

### 判断原则

**宁可多问一句，不要沉默跳过**。如果连 AI 自己都不确定该不该搜，那说明这个问题有搜索价值，把选择权交给用户。

关键词触发：用户的问题中如果包含"设计"/"方案"/"架构"/"怎么处理"/"讨论"，且问题核心是技术性的 → 触发模糊场景流程。

## 搜索优先级

### 通用技术（不可违反）

```
GitHub → 垂直领域专业站 → 全球技术社区 → 国内实战平台 → 厂商官方社区
```

第一轮必须同时搜索 GitHub + 问题所属的垂直领域站。
如果第一轮搜索结果不足以给出确定答案，再扩展到其他平台。

### AI/Agent/Harness/LMM 相关（不可违反）

```
厂商官方 → GitHub → 全球技术社区
```

第一轮必须同时搜索以下官方源中的至少 3 家：
- **OpenAI**（平台文档 + Cookbook + Blog）
- **Anthropic**（Claude Docs + Research Blog + Customer Stories）— **Agent Harness 权威源**
- **AWS**（Amazon AI/ML Blog + Bedrock Docs + SageMaker Docs）
- **Google**（Google AI Blog + DeepMind Blog + Gemini Docs + Vertex AI Docs）
- **Microsoft**（Microsoft AI Blog + Azure AI Docs + Semantic Kernel Docs）
- **Meta**（Meta AI Blog + Llama Docs）

特别地，Agent Harness 问题：
**优先查 Anthropic Engineering Blog + Claude Docs → GitHub shanraisshan/obra 等最佳实践仓库 → 社区**

第二轮基于第一轮中发现的最佳实践关键词，搜索 GitHub 上的实现和验证。
第三轮搜索 Dev.to、Medium、Hacker News 等社区的实战经验进行交叉验证。

## 平台目录与搜索策略

- 完整平台目录见 `references/platform-catalog.md`
- 详细搜索策略见 `references/search-strategies.md`
- 搜索质量自检清单见 `references/quality-checklist.md`
- 记忆转化指南见 `references/memory-conversion.md`

简要速查：

| 问题类型 | 搜索路径 |
|---------|---------|
| Bug / 报错 | GitHub Issues → Stack Overflow → SegmentFault |
| 最佳实践 / 技术选型 | GitHub 项目 README/代码 → InfoQ → 掘金 |
| 性能优化 | GitHub 项目 benchmark → Stack Overflow → 博客园 |
| 架构设计 | InfoQ → Medium → 阿里云/腾讯云开发者社区 |
| 安全相关 | GitHub Security Advisories → OWASP → CVE 数据库 |
| **AI/Agent/LLM/RAG/Harness** | **OpenAI/Anthropic/AWS/Google/Microsoft/Meta 官方（≥3家） → GitHub → Dev.to/Medium/HN** |

## 信源可信度分级 / Source Credibility Tiers

为对抗"看起来很专业"的幻觉，所有引用必须标注信源等级。无法达到最低信源要求的结论必须明确拒绝回答或标注为"未验证"。

| 等级 | 标识 | 定义 | 示例 | 可信度权重 |
|------|------|------|------|-----------|
| **A** | 🔒 权威 | 一手官方文档、厂商技术博客、标准组织规范、经同行评审的论文 | OpenAI Platform Docs、Anthropic Engineering Blog、RFC 文档、IEEE 论文 | 最高 |
| **B** | ✅ 可信 | 知名技术社区高票答案、主流大厂工程博客、成熟项目的官方文档 | Stack Overflow 100+ 票答案、GitHub 官方 Docs、AWS/Google 工程博客 | 高 |
| **C** | ⚠️ 参考 | 个人技术博客、社区讨论、未经验证的 GitHub 项目 | 掘金/个人博客、GitHub <100 Star 项目、Reddit 讨论 | 中等 |
| **D** | ❓ 推测 | 无明确来源的观点、AI 生成内容、论坛闲聊 | ChatGPT 回答（无引用）、知乎匿名回答、未标注出处的文章 | 低 |

### 引用最低标准

| 场景 | 最低信源要求 |
|------|-------------|
| 技术选型建议 | ≥1 个 A 级 + ≥1 个 B 级 |
| Bug 修复方案 | ≥1 个 B 级（GitHub Issue / Stack Overflow 高票） |
| 性能数据 | ≥1 个 A 级或 ≥2 个 B 级（需可复现） |
| 安全相关结论 | ≥1 个 A 级（OWASP / CVE / 厂商安全公告） |
| AI/Agent 实践 | ≥1 个 A 级（厂商官方 Docs/Blog） |
| 架构设计建议 | ≥1 个 A 级 + ≥2 个 B 级 |

**不满足最低标准的处理**：
- 直接告知用户："当前搜索结果不足以给出确定结论，建议咨询 [该领域] 专家。"
- 如果必须回答，开头明确标注：**⚠️ 以下结论基于有限信源（仅 C/D 级），仅供参考，未经充分验证。**

## 不确定内容处理 / Handling Uncertainty

当遇到以下情况时，AI 必须拒绝给出确定答案，而非编造：

| 情况 | 处理方式 |
|------|---------|
| 搜索结果互相矛盾且无法判断 | 列出各方观点，标注差异，说明"目前社区尚无统一结论" |
| 搜索不到任何 A/B 级信源 | 明确告知用户搜索局限性，建议人工调研 |
| 涉及封闭领域（医疗/金融/法律/强监管行业） | 直接拒绝，提示"本领域需要专业资质，建议咨询持证专家" |
| 信息明显过时（超过时效限制） | 标注"可能过时"，建议用户重新搜索最新资料 |
| 问题超出当前模型知识截止日且搜索失败 | 明确告知"无法获取最新信息"，不凭记忆回答 |

## 高风险领域警告 / High-Risk Domain Warning

以下领域即使搜索结果充足，也必须附加**免责声明**：

- **医疗/健康**：任何代码涉及医疗数据处理、诊断辅助、药物计算
- **金融/投资**：涉及交易算法、风险评估、合规检查
- **法律/合规**：涉及隐私政策、数据合规（GDPR/等保）、许可证解释
- **安全/军工**：涉及加密实现、身份认证、访问控制
- **自动驾驶/工业控制**：涉及人身安全的关键系统

**免责声明模板**：
```
⚠️ 本领域涉及 [医疗/金融/法律/安全等]，需要专业资质审核。
以下内容为公开技术资料整理，不构成专业建议，部署前务必经 [该领域] 专家审校。
```

## 搜索方法要点

### GitHub 搜索（必须的第一步）

- 搜索项目：`github.com/search?q={keyword}+language:{lang}&type=repositories&s=stars`
- 搜索 Issue：`github.com/search?q={error_message}&type=issues`
- 搜索代码：`github.com/search?q={keyword}&type=code`
- 精确匹配用引号：`"IndexError: list index out of range"`
- Issue 搜索是最快找到 Bug 解决方案的方式

### AI 厂商官方搜索（AI/Agent 问题的必须第一步）

| 厂商 | 搜索格式 |
|------|---------|
| OpenAI | `site:platform.openai.com {keyword}` / `site:cookbook.openai.com {keyword}` |
| Anthropic | `site:docs.anthropic.com {keyword}` / `site:anthropic.com/engineering {keyword}` |
| AWS | `site:aws.amazon.com/blogs/machine-learning {keyword}` |
| Google | `site:ai.google.dev {keyword}` / `site:blog.google/technology/ai {keyword}` |
| Microsoft | `site:learn.microsoft.com/en-us/azure/ai-services {keyword}` |
| Meta | `site:ai.meta.com/blog {keyword}` |

### 时间限定

- **通用技术**：优先近 1 年内的内容。老技术（如 C++、Linux 内核）可放宽。
- **AI/Agent/LMM 相关**：必须优先近 3 个月内的内容。超过 6 个月必须交叉验证，超过 1 年直接标记"可能过时"。

## Skill 老化检测与维护 / Skill Aging & Maintenance

生成的记忆和结论会随时间失效。每次使用记忆前，执行老化检测：

| 领域 | 有效期 | 老化处理 |
|------|--------|---------|
| AI/Agent/LLM | 3 个月 | 超过 3 个月 → 重新搜索验证后再使用 |
| 前端/云原生 | 6 个月 | 超过 6 个月 → 检查是否有新版本/替代方案 |
| 后端/数据库 | 1 年 | 超过 1 年 → 验证是否仍适用 |
| 安全/合规 | 实时 | 每次使用前必须重新搜索最新漏洞/法规 |
| 基础设施（Linux/网络） | 2 年 | 超过 2 年 → 检查是否有重大变更 |

**老化检测流程**：
1. 读取记忆时，先查看其中的`搜索时间`字段
2. 计算距今时长，对照上表判断是否超期
3. 超期记忆：**标注"[可能过时]"** + **重新搜索验证** + **更新记忆文件**
4. 更新时在记忆文件头部追加：`> 📅 更新记录：YYYY-MM-DD 重新验证，结论 [不变/已更新/已废弃]`

**废弃记忆处理**：
- 被证实已过时 → 移动到 `memory/archive/` 目录，文件名加 `.deprecated`
- 不要直接删除，保留历史痕迹

## 会话记忆卡片 / Session Memory Card

每次 master 搜索完成并输出回答后，**必须在回复末尾追加记忆卡片**。这是强制行为，不可省略。

### 卡片格式

```markdown
📌 **会话记忆**
| 主题 | 卡片 |
|------|------|
| {主题} | {一句话精炼核心结论：包含了什么、怎么用、为什么} — [来源标题](URL) {A/B/C}级 |

（3-5 张卡片为佳，最多 5 张；优先放 A/B 级信源的卡片）
```

模板示例：

```markdown
📌 **会话记忆**
| 主题 | 卡片 |
|------|------|
| Agent 记忆架构 | 三层记忆模型（工作/情景/语义）+ Mem0 落地 — [Anthropic Engineering](https://anthropic.com/engineering/memory) A级 |
| LLM 上下文管理 | 长上下文不如短上下文+摘要：实测超过 64K token 后检索精度下降 30% — [OpenAI Cookbook](https://cookbook.openai.com/examples/context-window) A级 |
| RAG Chunking | 推荐 256-512 tokens/chunk，overlap 10-20%，语义切割优于固定长度 — [LlamaIndex Docs](https://docs.llamaindex.ai/en/stable/optimizing/chunking) B级 |
```

### 写作规则

| 规则 | 说明 |
|------|------|
| **一句话原则** | 每条卡片一句话，包含"是什么 + 怎么用 + 为什么"三个要素 |
| **来源必有 URL** | 每条卡片必须附完整 URL，不允许只有平台名 |
| **信源等级必标** | 每条卡片末尾标注 A/B/C 级 |
| **最多 5 张** | 精炼为上，超过 5 张说明提炼不够 |
| **优先高信源** | A 级卡片优先保留；C 级卡片仅在无更好信源时保留 |
| **agent 友好** | 固定表格格式，agent 后续可直接检索"👇"后的卡片区域 |

### 卡片在输出中的位置

AI 的回复遵循以下结构（不可颠倒）：

```
1. 正文回答（常规 Markdown）
2. --- 分隔线
3. 📌 **会话记忆** 卡片表格
```

卡片既是人类可读的总结，也是 agent 在当前会话中可回溯的锚点。后续对话中如果话题相关，agent 应自动引用卡片中的结论和来源。

## 记忆转化

### 该记什么

| 类型 | 记忆示例 | 保存位置 |
|------|---------|---------|
| 解决方案 | "处理 [某问题] 的标准解法是 [方案]，参考 [链接]" | `memory/` |
| 技术选型结论 | "[场景] 下推荐用 [工具X] 而非 [工具Y]，原因：..." | `memory/` |
| 架构模式 | "[某架构模式] 的适用场景和落地要点" | `memory/` |
| 常见陷阱 | "使用 [某技术] 时常犯错误：..., 正确做法：..." | `memory/` |
| 性能基线 | "[某场景] 的性能基线参考值" | `memory/` |

### 记忆格式

```markdown
---
name: {记忆名称}
description: {一句话描述，用于未来检索}
type: reference
credibility: {A/B/C}        # 信源最高等级（见"信源可信度分级"）
validity: {3m/6m/1y/2y}     # 预计有效期，对应老化检测表
last-verified: YYYY-MM-DD   # 上次验证/更新时间
---

## 来源
- [平台名] [文章/项目名](链接) — 等级: {A/B/C}
- [平台名] [文章/项目名](链接) — 等级: {A/B/C}
- 搜索时间: YYYY-MM-DD

## 核心要点
（3-5 条要点，每条要点尽量标注支撑信源等级）

## 适用场景
（什么时候可以应用这个知识）

## 不适用场景
（什么时候不能用——比"适用场景"更重要，防止滥用）

## 更新记录
- YYYY-MM-DD: 初次记录
- YYYY-MM-DD: 重新验证，结论 [不变/已更新/已废弃]
```

转化后更新 `MEMORY.md` 索引。

## 搜索质量自检

回答用户技术问题前，检查 `references/quality-checklist.md`。

核心检查项：
- [ ] GitHub 是否已搜索（必须）
- [ ] 搜索结果是否包含近 1 年内的内容
- [ ] 答案是否有来源引用（必须标注来源链接）
- [ ] 是否将可复用的知识写入记忆（精华必须记）
- [ ] 不同平台方案是否交叉验证（有冲突时必须说明）

AI/Agent 问题额外检查：
- [ ] 是否至少搜索了 3 家官方厂源
- [ ] AI 内容是否优先近 3 个月
- [ ] 是否以官方文档/Blog 为权威参考
- [ ] 超过 6 个月的 AI 内容是否交叉验证

## 不做什么

### 通用禁止
- 不跳过 GitHub 搜索——即使你"知道"答案
- 不凭记忆回答技术问题——先搜索确认最新实践
- 不引用过时方案（>3 年的文章，除非是老技术且至今无更好方案）
- 不在搜索结果矛盾时强行给出单一答案——列出各方观点，标注差异
- 不在没有来源引用的情况下给出技术建议
- 不把临时的项目配置当作通用知识记入记忆

### AI/Agent/Harness 相关额外禁止
- **不把 GitHub 项目作为 AI/Harness 问题的第一参考**——先查厂商官方
- **不引用超过 6 个月的 AI/Harness 实践而不做交叉验证**
- **不在 AI/Harness 问题上仅凭 Stack Overflow/掘金等社区回答给出结论**
- **不同时搜索多家官方厂源**——至少搜 3 家，避免单一厂商视角偏差
- **Agent Harness 问题不跳过 Anthropic Engineering Blog**
