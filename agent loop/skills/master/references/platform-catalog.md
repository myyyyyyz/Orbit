# 技术搜索平台目录

## L0-AI：AI/Agent 厂商官方源（AI 问题的第一搜索源）

> 适用条件：问题涉及 AI/LLM/Agent/RAG/Prompt 工程/AI SDK 等 AI 相关技术时，
> 以下平台为**第一搜索源**，优先级高于 GitHub。

### OpenAI
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| Platform Docs | platform.openai.com/docs | API 使用、模型能力、Function Calling、Assistants API |
| Cookbook | cookbook.openai.com | 官方代码示例、RAG 实践、Embedding 使用 |
| Blog | openai.com/blog | 新模型发布、能力更新、安全实践 |
| GitHub | github.com/openai/openai-cookbook | Cookbook 源码、社区贡献示例 |
| GitHub | github.com/openai/openai-python | Python SDK 源码、Issue 讨论 |

### Anthropic
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| Claude Docs | docs.anthropic.com | API 参考、模型对比、Prompt 工程、Tool Use、Caching |
| Engineering Blog | anthropic.com/engineering | **Agent Harness 第一权威** — Agent Skills、Claude Code 最佳实践、Hooks/Settings 设计 |
| Research Blog | anthropic.com/research | AI 安全、Alignment、前沿能力研究 |
| Customer Stories | anthropic.com/customers | 企业落地案例、生产环境实践 |
| GitHub | github.com/anthropics/anthropic-sdk-python | Python SDK 源码、示例 |

### AWS (Amazon)
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| AI/ML Blog | aws.amazon.com/blogs/machine-learning | 生产环境 AI 实践、Bedrock 最佳实践 |
| Bedrock Docs | docs.aws.amazon.com/bedrock | Agent、RAG、Knowledge Base、Guardrails |
| SageMaker Docs | docs.aws.amazon.com/sagemaker | 模型训练、推理部署、MLOps |
| AWS Samples | github.com/aws-samples | 官方 AI/ML 参考架构和示例代码 |

### Google
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| Google AI Blog | ai.googleblog.com | Google AI 研究与应用进展 |
| DeepMind Blog | deepmind.google/discover/blog | 前沿 AI 研究、AlphaFold/Gemini 进展 |
| Gemini Docs | ai.google.dev/gemini-api/docs | Gemini API 使用、多模态、Function Calling |
| Vertex AI Docs | cloud.google.com/vertex-ai/docs | 企业级 AI 平台、Agent Builder |
| Generative AI Samples | github.com/GoogleCloudPlatform/generative-ai | 官方代码示例和最佳实践 |

### Microsoft
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| AI Blog | blogs.microsoft.com/ai | 微软 AI 战略、Copilot 生态 |
| DevBlogs AI | devblogs.microsoft.com | 开发者向 AI 技术深度文章 |
| Azure AI Docs | learn.microsoft.com/en-us/azure/ai-services | Azure OpenAI、AI Search、AI Agent |
| Semantic Kernel | learn.microsoft.com/en-us/semantic-kernel | AI Agent 编排框架最佳实践 |
| AutoGen | github.com/microsoft/autogen | 多 Agent 对话框架 |

### Meta
| 资源 | 网址 | 搜索时机 |
|------|------|---------|
| Meta AI Blog | ai.meta.com/blog | Llama 模型发布、开源 AI 进展 |
| Llama Docs | llama.meta.com/docs | Llama 模型使用、微调、部署指南 |
| GitHub | github.com/meta-llama | Llama 模型源码、示例、工具链 |

---

## L0：代码与开源（通用技术的第一搜索源）

> ⚠️ AI/Harness 问题时此层级降为第二轮（详见 L0-AI）

### Agent Harness 专项（Claude Code 生态的高星最佳实践仓库）
| 仓库 | Stars | 内容 | 搜索时机 |
|------|-------|------|---------|
| shanraisshan/claude-code-best-practice | 32K | 86+ tips、skills 规范、frontmatter 字段 | Skill 设计、Harness 配置 |
| obra/superpowers | 135K | TDD 驱动 skill 开发、评测框架 | Skill 评测、行为调优 |
| affaan-m/everything-claude-code | 176K | 48 agents, 182 skills | Agent 角色参考、编排模式 |
| MuhammadUsmanGM/claude-code-best-practices | — | 30+ guides, 11 templates | Skill 模板、入门指南 |
| onmyway133/awesome-claude-code | — | 精选列表 | 发现新工具/技巧 |
| spences10/claude-skills-cli | — | 渐进式加载校验 | Skill 结构校验 |
| kingbootoshi/directional-prompting | — | Outcome-First 方法 | Prompt 工程方法论 |
| applied-artificial-intelligence/claude-code-toolkit | — | 工作流→记忆→过渡 | 工作流模式参考 |
| datawhalechina/hello-agents | — | Skill 设计中文深度解析 | 中文 AI Agent 教程 |

### 通用代码与开源

| 平台 | 网址 | 定位 | 搜索时机 |
|------|------|------|---------|
| **GitHub** | github.com | 全球最大开源平台，代码/Issue/Discussion | **所有问题的第一步** |
| GitLab | gitlab.com | 开源 + 企业内部代码托管 | GitHub 搜不到时补充 |
| Gitee | gitee.com | 国内开源平台，国产项目集中 | 国产技术、信创场景 |

## L1：垂直领域专业站（细分领域最优实践）

### 前端
| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| CSS-Tricks | css-tricks.com | CSS/布局/响应式问题 |
| Smashing Magazine | smashingmagazine.com | 前端架构、性能、工程化 |
| MDN Web Docs | developer.mozilla.org | Web API/标准/兼容性 |

### 后端/架构
| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| The New Stack | thenewstack.io | 云原生、容器、微服务 |
| DZone | dzone.com | Java/后端设计模式、性能 |
| High Scalability | highscalability.com | 高并发/大规模系统架构 |

### DevOps/运维
| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| DevOps Weekly | devopsweekly.com | CI/CD、K8s、自动化 |
| Linux Journal | linuxjournal.com | Linux 底层优化、运维 |

### 安全
| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| OWASP | owasp.org | Web 安全标准、漏洞防护 |
| CVE Details | cvedetails.com | 漏洞查询 |

### 算法
| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| LeetCode | leetcode.com | 算法题解、面试 |
| AcWing | acwing.com | 算法竞赛、高效刷题 |

## L2：全球深度技术社区（高质量、英文）

| 平台 | 网址 | 定位 | 搜索时机 |
|------|------|------|---------|
| **Stack Overflow** | stackoverflow.com | 全球程序员问答 | Bug/报错/标准实现 |
| **InfoQ** | infoq.com | 架构与技术趋势 | 架构学习、技术选型 |
| **Dev.to** | dev.to | 开发者原创社区 | 实战经验、踩坑分享 |
| **Medium** | medium.com | 深度技术博客 | 系统学习、架构设计 |
| **Hacker News** | news.ycombinator.com | 极客资讯+讨论 | 技术趋势、行业共识 |

## L3：国内实战平台（中文、接地气）

| 平台 | 网址 | 定位 | 搜索时机 |
|------|------|------|---------|
| **掘金** | juejin.cn | 中文第一开发者社区 | 实战、面试、落地经验 |
| **博客园** | cnblogs.com | 深度长文社区 | 底层原理、架构、性能 |
| **SegmentFault** | segmentfault.com | 中文技术问答 | 中文疑难问题、标准方案 |
| **开源中国** | oschina.net | 国内开源大本营 | 国产开源、本土化方案 |
| **CSDN** | blog.csdn.net | 国内最大 IT 社区 | 入门、中文资料 |

## L4：厂商官方社区（权威、生产环境实践）

| 平台 | 网址 | 搜索时机 |
|------|------|---------|
| 阿里云开发者社区 | developer.aliyun.com | 云原生、大数据、AI 实践 |
| 腾讯云开发者社区 | cloud.tencent.com/developer | 后端、微信生态、AI |
| 华为云开发者社区 | developer.huaweicloud.com | 企业架构、高可用、安全 |

## L5：官方文档（权威参考）

| 类型 | 搜索路径 |
|------|---------|
| 语言/框架官方文档 | `{技术名}.org` 或 `docs.{技术名}.org` |
| Python 包文档 | `pypi.org/project/{包名}` |
| npm 包文档 | `npmjs.com/package/{包名}` |
| 云产品文档 | 对应云平台的 help/文档中心 |

---

## 搜索组合速查

| 问题类型 | 第一轮（必须） | 第二轮（补充） |
|---------|-------------|-------------|
| Bug/报错 | GitHub Issues + Stack Overflow | SegmentFault + 官方文档 |
| 最佳实践 | GitHub README + InfoQ | 掘金 + Medium |
| 技术选型 | GitHub Star 对比 + Hacker News | InfoQ + 掘金 |
| 性能调优 | GitHub benchmark + Stack Overflow | 博客园 + DZone |
| 架构设计 | InfoQ + High Scalability | 阿里云/腾讯云社区 |
| 安全漏洞 | GitHub Security + OWASP | CVE + 安全社区 |
| 前端/UI | GitHub 组件库 + MDN | CSS-Tricks + 掘金 |
| DevOps | DevOps Weekly + GitHub Actions | 华为云社区 |
| 算法 | LeetCode | AcWing |
| 国产技术 | 开源中国 + Gitee | 华为云/阿里云社区 |
| **AI/Agent/LLM/Harness** | **OpenAI/Anthropic/AWS/Google/Microsoft/Meta 官方（≥3家）** | **GitHub 实现验证 + Dev.to/Medium/HN 交叉验证** |
| **Agent Harness（Claude Code）** | **Anthropic Engineering Blog（独家第一方）** | **GitHub 高星仓库（shanraisshan/obra 等）** |
