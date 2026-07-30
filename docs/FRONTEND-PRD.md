# Orbit 前端交互系统 — 产品需求文档 (PRD)

> 版本: v1.0  
> 日期: 2026-07-30  
> 关联: Orbit v1.0 后端已就绪  
> 设计技能: taste-skill + ui-ux-pro-max

---

## 1. 项目背景

Orbit 后端已具备完整能力（知识库 RAG + Agent Loop 协作框架 + 多租户认证），但用户只能通过 `curl`、Bash CLI、Python Demo 脚本与系统交互。目标用户（中小微企业、个人用户）无法使用。

**核心问题**：没有前端，Orbit 只是框架，不是产品。

## 2. 产品目标

为 Orbit 构建一个 **AI Agent 端到端系统** 的 Web 前端交互界面，让用户：

- 🗣️ **通过自然语言交流思路**，让 AI 理解意图并自主委派 Agent
- 📚 **可视化管理知识库**：拖拽上传文档、查看索引状态、手动搜索
- 👁️ **观察 Agent 执行过程**：实时查看 Planner 计划、Builder 进度、Reviewer 报告
- ⚙️ **配置与调优**：模型选择、RAG 策略参数、知识库设置

## 3. 用户画像

| 角色 | 需求 | 频率 |
|------|------|------|
| **小微企业主** | 上传公司文档，用自然语言查询业务知识 | 每日 |
| **独立开发者** | 描述项目需求，让 Agent 自动规划、编码、审查 | 按项目 |
| **产品经理** | 交流产品思路，生成结构化 Spec，跟踪 Agent 执行 | 每周 |
| **学生/研究者** | 上传论文资料，RAG 问答，知识整理 | 每日 |

## 4. 功能模块

### 4.1 Chat 交互区（核心）

**定位**：用户与 Orbit 交互的主界面，类 ChatGPT 对话体验 + Agent 增强。

**功能清单**：

| 编号 | 功能 | 说明 | 优先级 |
|:---:|------|------|:---:|
| C1 | 流式对话 | SSE 实时流式输出，逐字显示，Markdown 渲染 | P0 |
| C2 | 意图识别展示 | 显示 AI 识别到的用户意图（问答/委派/知识库操作） | P0 |
| C3 | 来源引用 | 知识库回答附带来源文档片段和高亮引用 | P0 |
| C4 | Agent 委派面板 | 当用户"帮我想个方案"时，展示"已委派给 Planner → 等待计划..." | P1 |
| C5 | 推理过程可视化 | 展示 AI 思考链（Chain-of-Thought），折叠显示 | P1 |
| C6 | 多轮对话上下文 | 会话历史管理，支持新建/切换/删除会话 | P0 |
| C7 | 消息操作 | 复制、重新生成、反馈（👍👎） | P1 |
| C8 | 工具调用卡片 | 当 AI 调用工具时，卡片展示调用参数和结果 | P1 |
| C9 | 代码块增强 | 语法高亮、一键复制、文件路径标注 | P0 |
| C10 | 附件输入 | 支持粘贴图片、拖拽文件到输入框 | P2 |

### 4.2 知识库管理面板

**定位**：可视化文档上传、索引管理、搜索测试。

**功能清单**：

| 编号 | 功能 | 说明 | 优先级 |
|:---:|------|------|:---:|
| K1 | 文件拖拽上传 | 支持 PDF / MD / TXT / 图片，批量上传，进度条 | P0 |
| K2 | 文档列表 | 已索引文档表格：文件名、大小、索引时间、状态 | P0 |
| K3 | 文档删除 | 单个/批量删除，同步清理向量索引 | P1 |
| K4 | 手动搜索 | 关键词搜索知识库，显示 Top-K 结果和相似度 | P1 |
| K5 | 策略可视化 | RAG 策略参数面板：Chunk 大小、Overlap、Top-K 等 | P1 |
| K6 | 索引状态 | 文档总数、向量总数、存储大小仪表盘 | P2 |
| K7 | 存储路由 | 展示不同文件类型的存储策略（原样/RAG/SQL/OCR） | P2 |

### 4.3 Agent 观察台

**定位**：实时查看 Agent Loop 的执行状态和产出。

**功能清单**：

| 编号 | 功能 | 说明 | 优先级 |
|:---:|------|------|:---:|
| A1 | Agent 状态流 | 时间线展示 Agent 调度：Master 对齐 → Planner 出计划 → Builder 执行 → Reviewer 审查 | P1 |
| A2 | 计划预览 | Planner 产出的执行计划和影响面分析，结构化卡片展示 | P1 |
| A3 | 代码 Diff 视图 | Builder 修改的代码变更，前后对比，支持行内高亮 | P1 |
| A4 | 审查报告 | Reviewer 产出的问题清单，按严重度分类（Critical/Warning/Suggestion） | P1 |
| A5 | 审批操作 | 对关键步骤进行人工确认（Approve / Reject / Rework） | P2 |
| A6 | 迭代计数 | 显示当前 case 退回次数和熔断状态（MAX_ITER=3） | P2 |

### 4.4 设置面板

**定位**：用户配置 LLM、知识库策略、账户信息。

**功能清单**：

| 编号 | 功能 | 说明 | 优先级 |
|:---:|------|------|:---:|
| S1 | 模型配置 | 选择 LLM Provider（OpenAI / Ollama / 自定义），输入 API Key | P0 |
| S2 | 路由策略 | 配置三档模型路由（fast / balanced / strong）的模型分配 | P1 |
| S3 | RAG 策略调参 | 可视化调整 Chunk 大小、Overlap、Top-K、检索模式 | P1 |
| S4 | 账户管理 | 注册/登录/登出、Token 管理、多用户切换 | P0 |
| S5 | 新手引导 | 首次使用时的角色选择和 Skill 推荐 | P2 |

## 5. 技术方案

### 5.1 技术选型

| 层 | 选择 | 理由 |
|----|------|------|
| 框架 | **Next.js 15** (App Router) | 全栈能力、SSR 可选、Vercel AI SDK 原生支持 |
| AI SDK | **Vercel AI SDK v6** | 原生 SSE 流式消费 `useChat`，工具调用可视化，与 Orbit 后端 SSE 协议天然对接 |
| UI 组件 | **assistant-ui** + **shadcn/ui** | assistant-ui 提供 Agent Chat 专用组件（推理链、工具卡片）；shadcn/ui 提供通用 UI |
| 样式 | **Tailwind CSS v4** | taste-skill 和 ui-ux-pro-max 默认技术栈 |
| 状态管理 | **React Context + SWR** | 轻量，避免引入 Redux 复杂度 |
| 动画 | **GSAP / Framer Motion** | taste-skill 要求高质量动效 |
| 部署 | **Vercel** (前端) + 已有 FastAPI (后端) | 前端薄层，后端不变 |

### 5.2 架构

```
┌───────────────────────────────────────────────────────┐
│                   Next.js Frontend                     │
│                                                        │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ Chat UI │  │ KB Panel │  │ Agent Obs│  │Settings│ │
│  │ (assist │  │ (upload/ │  │ (timeline│  │(model/ │ │
│  │ ant-ui) │  │  search) │  │ /diff)   │  │ config)│ │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│       │            │             │             │       │
│     Vercel AI SDK (useChat / streamText)              │
│       │            │             │             │       │
├───────┼────────────┼─────────────┼─────────────┼───────┤
│       ▼            ▼             ▼             ▼       │
│           FastAPI Backend (已有, 不变)                 │
│                                                        │
│  /api/knowledge/ask/stream  (SSE 流式)                │
│  /api/knowledge/search       (语义检索)               │
│  /api/knowledge/upload       (文件上传)               │
│  /api/knowledge/strategy      (RAG 策略)              │
│  /api/auth/login|register     (认证)                  │
│  /health                      (健康检查)              │
└───────────────────────────────────────────────────────┘
```

### 5.3 SSE 流式对接

Orbit 后端 stream 模块使用 7 阶段 SSE 事件流：

```
event: status    → data: {"stage": "searching", ...}
event: status    → data: {"stage": "generating", ...}
event: token     → data: {"text": "根据..."}
event: reference → data: {"source": "...", "chunk": "..."}
event: done      → data: {"model": "gpt-4o"}
```

前端 Vercel AI SDK 使用自定义 `fetch` 对接：

```typescript
// app/api/chat/route.ts (Next.js Route Handler → 转发到 FastAPI)
import { streamText } from 'ai';

// 或直接用 useChat hook 指向 FastAPI
const { messages, input, handleSubmit } = useChat({
  api: 'http://localhost:8001/api/knowledge/ask/stream',
  headers: { Authorization: `Bearer ${token}` }
});
```

## 6. UI/UX 设计方向

> 基于 taste-skill + ui-ux-pro-max 的设计能力定义

### 6.1 设计语言

| 属性 | 选择 | 来源 |
|------|------|------|
| **风格** | Modern Soft UI（现代柔和） | ui-ux-pro-max Style #12 |
| **配色** | 深色主题为主，低饱和度蓝紫调 | ui-ux-pro-max SaaS Palette #3 |
| **字体** | Inter (正文) + JetBrains Mono (代码) | ui-ux-pro-max Font Pair #7 |
| **圆角** | 12px 卡片，8px 按钮（柔和但不幼稚） | taste-skill spacing guide |
| **阴影** | 微影（`0 1px 3px rgba(0,0,0,0.08)`），避免 box-shadow 泛滥 | taste-skill anti-slop rules |
| **动效** | 低强度（hover 0.15s ease-out，页面切换 fade），避免眼花缭乱 | taste-skill motion knob = low |
| **图标** | Lucide Icons（线性，2px stroke） | shadcn/ui 默认 |

### 6.2 布局

```
┌──────────────────────────────────────────────────┐
│  Sidebar (260px)      │  Main Content             │
│                        │                          │
│  ┌──────────────────┐  │  ┌────────────────────┐  │
│  │ 🔵 Orbit         │  │  │  Chat Messages     │  │
│  │──────────────────│  │  │  ┌──────────────┐  │  │
│  │ 📝 新对话         │  │  │  │ User Bubble  │  │  │
│  │──────────────────│  │  │  └──────────────┘  │  │
│  │ 📚 知识库         │  │  │  ┌──────────────┐  │  │
│  │ 👁 Agent 观察台   │  │  │  │  AI Response  │  │  │
│  │ ⚙️ 设置           │  │  │  │  + Sources    │  │  │
│  │──────────────────│  │  │  └──────────────┘  │  │
│  │ 历史对话           │  │  │                    │  │
│  │ - 项目方案讨论     │  │  ├────────────────────┤  │
│  │ - 产品需求分析     │  │  │  Input Box         │  │
│  │ - API 文档查询    │  │  │  [📎] [@] [发送]   │  │
│  └──────────────────┘  │  └────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### 6.3 关键交互

1. **输入框增强**：类似 Notion 的 `/` 命令面板
   - `/kb` → 切换到知识库查询模式
   - `/agent` → 委派 Agent 任务
   - `/file` → 上传文件到知识库

2. **Agent 状态卡片**：当 AI 正在调用 Agent 时，对话中插入实时更新的状态卡片
   ```
   ┌─────────────────────────────────┐
   │ 🤖 Planner 正在分析...          │
   │ ████████░░░░ 80%               │
   │ 影响面分析：3 个模块受影响       │
   │ [查看计划草案]                  │
   └─────────────────────────────────┘
   ```

3. **引用悬浮卡**：鼠标悬停在引用编号上，弹出原文片段
   ```
   ┌─────────────────────┐
   │ 📄 销售策略_v3.pdf   │
   │ "...Q2 目标增长 15%..."│
   │ 相似度: 0.94         │
   │ [跳转到原文]          │
   └─────────────────────┘
   ```

## 7. 分阶段交付计划

### Phase 1 — 基础对话 + 知识库（2 周）

- [ ] Next.js 项目初始化 + 项目结构
- [ ] Chat UI：流式对话、Markdown 渲染、代码块
- [ ] 用户认证：注册/登录/Token 管理
- [ ] 知识库上传：拖拽上传、进度条
- [ ] 知识库文档列表
- [ ] 设置：模型配置、API Key 管理

### Phase 2 — Agent 增强（2 周）

- [ ] Agent 观察台：时间线视图
- [ ] 推理过程可视化
- [ ] 工具调用卡片
- [ ] Agent 计划/审查预览
- [ ] 来源引用悬浮卡
- [ ] 搜索面板

### Phase 3 — 完善体验（1 周）

- [ ] 代码 Diff 对比视图
- [ ] 审批操作（Approve/Reject）
- [ ] 新手引导
- [ ] RAG 策略可视化配置
- [ ] 反馈系统
- [ ] 响应式适配（移动端）

## 8. 成功指标

| 指标 | 目标 |
|------|------|
| 非技术用户 5 分钟上手 | 首次对话完成率 > 90% |
| 文件上传成功率 | > 99% |
| 首 Token 响应时间 | < 1s（SSE 流式） |
| 知识库搜索结果 | 展示时间 < 500ms |
| 前端构建大小（gzip） | < 200KB（首屏） |

## 9. 开发规范要求

**所有前端开发（包括但不限于界面布局、组件实现、样式调整、交互设计、增删改功能模块）必须调用以下两个 skill：**

| Skill | 何时调用 | 作用 |
|-------|---------|------|
| **taste-skill** | 每个 UI 页面/组件开发前 | 防止生成千篇一律（slop）的界面，自动推断设计语言，把控布局、间距、动效、反 slop 规则 |
| **ui-ux-pro-max** | 设计决策前（配色/字体/风格选择） | 基于 57 种风格 + 95 套调色板 + 56 组字体搭配的知识库，为当前产品类型推荐匹配的设计系统 |

**强制要求：**
- ✅ 任何前端代码产出前，必须先加载 taste-skill 和 ui-ux-pro-max 进行设计指导
- ✅ 设计 Token（配色 / 字体 / 间距 / 圆角 / 阴影）由 ui-ux-pro-max 搜索脚本生成，保持全站统一
- ✅ 组件样式需通过 taste-skill 的反 slop 审计（布局合理性、间距比例、动效强度）
- ❌ 禁止不经过 skill 指导直接手写 UI 样式（避免不一致、低质量界面）
- ⚠️ 若 skill 指导与具体实现冲突，以 skill 的设计准则为准，并在 PR 中说明偏差原因

**调用示例：**
```
# 开发知识库上传组件前
> 使用 taste-skill 设计上传拖拽区的视觉和交互
> 使用 ui-ux-pro-max 搜索「文件管理类 SaaS」的推荐配色和排版
```

## 10. 风险与依赖

| 风险 | 缓解措施 |
|------|---------|
| SSE 协议对接兼容性 | 使用标准 SSE `text/event-stream`，不依赖私有协议 |
| Agent Loop 状态同步 | 基于文件通信协议的 Agent 状态通过轮询后端 `/agent/status` 获取 |
| 后端 CORS 配置 | FastAPI 已支持 CORS，配置 `allow_origins` 指向前端域名 |
| taste-skill 设计一致性 | 使用 ui-ux-pro-max 的搜索脚本生成统一设计 Token |
