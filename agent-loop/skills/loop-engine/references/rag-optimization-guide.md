# RAG 策略优化指南

> **目标读者**: Knowledge Agent
> **用途**: 指导 Knowledge Agent 分析实际文档特征，动态调整 RAG 策略
> **原则**: 默认值覆盖 80% 场景，优化只在当前策略明显不适用时触发
>
> **信源与更新**:
> - 厂商官方: Anthropic Contextual Retrieval, OpenAI Cookbook, Meta BGE 论文 [🔒 A 级]
> - 行业实践: 掘金 RAG 架构设计全景 (2026-04), LangCopilot Chunking Guide (2026-02) [✅ B 级]
> - 内部沉淀: Agent 笔记 / RAG 子目录 18 篇 [⚠️ C 级]
> - 验证周期: AI/RAG 领域 3 个月重新验证

---

## 1. 策略调整总决策树

Knowledge Agent 在每次索引批次完成后，按以下决策树逐层检查：

```
┌─ 索引完成 ─────────────────────────────────────────┐
│                                                    │
│ 第一层：文档特征分析                                 │
│ ├─ 中文占比 > 60% 且 on MiniLM？                   │
│ │   → §2.1 Embedding 建议                          │
│ ├─ 文档结构特征？（MD/标题 vs 纯文本 vs 代码）        │
│ │   → §2.2 Chunking 建议                          │
│ ├─ 术语/代码/编号密度？                             │
│ │   → §2.3 检索方法建议                            │
│ └─ 统计全部通过 → 默认策略合适                       │
│                                                    │
│ 第二层：检索质量监控（每 50 次查询后）               │
│ ├─ top-1 分数 < 0.3 持续 > 20 次？                 │
│ │   → §3.1 排查流程                               │
│ ├─ top-1/2/3 分数差 < 0.05？                       │
│ │   → §3.2 启用 Rerank                            │
│ ├─ 用户反馈"不对"频率增高？                         │
│ │   → §3.1 五步排查法                              │
│ └─ 全部正常 → 策略有效                              │
│                                                    │
│ 第三层：定期审计（每周或每 200 次查询）              │
│ ├─ RAGAS 评测基线是否退化？                         │
│ │   → §3.4 定向优化                                │
│ └─ 文档增量 > 原库 50%？                            │
│     → 重新分析文档特征                               │
└────────────────────────────────────────────────────┘
```

### 不可自动调整的事项（必须用户确认）

| 调整 | 原因 | 影响 |
|------|------|------|
| 切换 Embedding 模型 | 需重新索引全部文档 | 全量重索引 |
| 改变 chunk_size | 需重新切割和索引 | 全量重索引 |
| 启用 parent_child | 需重新切割（两套粒度） | 全量重索引 + 存储翻倍 |
| 切换到 OpenAI 后端 | 产生 API 费用 | 持续成本 |
| 改变 distance_metric | cosine → l2/ip 向量不兼容 | 全量重索引 |

### 可自动执行的调整

| 调整 | 原因 |
|------|------|
| top_k, score_threshold | 仅影响检索返回数量 |
| bm25_weight, retrieval.method | 仅影响检索排序，不需重索引 |
| rerank_enabled | 仅影响后处理 |
| query_rewrite_enabled | 仅影响查询预处理 |
| dedup, chunk.overlap, chunk.min_size | 小参数调优 |

---

## 2. 文档特征分析与策略匹配

### 2.1 Embedding 策略

**默认**: `sentence-transformers / all-MiniLM-L6-v2`

**分析维度**:

```python
def analyze_embedding_need(texts: list[str]) -> dict:
    chinese_chars = sum(1 for t in texts for c in t if '\u4e00' <= c <= '\u9fff')
    total_chars = sum(len(t) for t in texts)
    cn_ratio = chinese_chars / total_chars if total_chars > 0 else 0

    total_chunks = 估算现有 chunks 数
    needs_rerank = 是否需要高精度（法律/医疗/客服）

    return {
        "chinese_ratio": cn_ratio,
        "recommend_model": _pick_model(cn_ratio, total_chunks, needs_rerank),
    }
```

**选型决策表**:

| 中文占比 | 规模 | 精度要求 | 推荐模型 | 维度 | 说明 |
|---------|------|---------|---------|:---:|------|
| > 60% | 任意 | 高 | `bge-m3` (Ollama) | 1024 | 中文多语言 SOTA |
| > 60% | 任意 | 中 | `BAAI/bge-large-zh-v1.5` (sentence-transformers) | 1024 | 中文专用，免 Ollama |
| 30-60% | 任意 | 任意 | `bge-m3` | 1024 | 多语言最优 |
| < 30% | < 10万 chunks | 中 | `all-MiniLM-L6-v2`（默认） | 384 | 英文轻量，内存友好 |
| < 30% | > 10万 chunks | 高 | `text-embedding-3-large` (OpenAI) | 3072 | 最高精度，有成本 |

**模型选型关键点**:
- **对称 vs 非对称**: RAG 场景优先非对称模型（E5、BGE 系列），Query 和 Document 用不同编码器优化 [🔒 A 级: BGE 论文]
- **向量不兼容**: 换模型后旧向量与新向量不在同一空间，必须全部重新索引 [⚠️ C 级: Agent 笔记]
- **双塔 + 单塔组合**: 双塔检索 Top-50~100（快），单塔 Cross-Encoder 重排序（准），精度提升约 20%（NDCG@10: 0.65 → 0.78）[✅ B 级: 掘金]
- **BGE 专用前缀**: 使用 BGE 模型时，query 前加 `"为这个句子生成表示以用于检索相关文章："` 前缀 [🔒 A 级: BGE 官方]

### 2.2 Chunking 策略

**默认**: `semantic, size=500, overlap=50, parent_child_enabled=False`

**12 种策略对比** [✅ B 级: LangCopilot + 掘金]:

| 策略 | 适用场景 | 不适用场景 | 生产推荐度 |
|------|---------|-----------|:--:|
| **递归字符切割** | **通用首选，最佳平衡点** | — | ⭐⭐⭐⭐⭐ |
| **语义切割** | 高质量问答/研究论文（准确率提升 ~70%） | 计算资源有限 | ⭐⭐⭐⭐ |
| **结构感知切割** | Markdown/HTML 格式良好的文档 | 无结构化标记的文本 | ⭐⭐⭐⭐ |
| **父子分块** | **生产环境推荐**，兼顾精度和上下文 | 短文档（< 500 字）/ FAQ | ⭐⭐⭐⭐⭐ |
| **Token 切割** | 严格 Token 预算 / 多语言 | 语义要求高的场景 | ⭐⭐⭐ |
| **固定大小** | 原型验证 / 日志 / 代码 | 自然语言文档 | ⭐⭐ |
| **基于句子** | 法律文档 / 新闻 | 长句密集的文档 | ⭐⭐⭐ |
| **上下文检索** | 消除块歧义（Anthropic 推荐） | 简单文档 | ⭐⭐⭐⭐ |
| **晚期分块** | 长技术文档 / 交叉引用多 | 需要长上下文嵌入模型 | ⭐⭐⭐ |
| **跨粒度检索** | 信息密度不均的长文档 | 实现复杂度高 | ⭐⭐⭐ |
| **混合分块** | 多格式混合文档 | 简单统一格式 | ⭐⭐⭐ |
| **代理式分块** | 极度混乱文本（实验性） | 生产环境（极慢） | ⭐ |

**文档特征 → 策略匹配**:

```python
def pick_chunk_strategy(doc_analysis: dict) -> str:
    """
    doc_analysis = {
        "avg_length": 平均字符数,
        "has_structure": 是否有标题/大纲,
        "content_type": "technical"|"narrative"|"code"|"faq"|"legal",
        "chinese_ratio": 中文占比,
    }
    """
    if doc_analysis["has_structure"]:
        # 有 Markdown 标题 / HTML 标签 → 结构感知切割
        return "structure_aware"

    if doc_analysis["content_type"] == "faq":
        # FAQ 短问答 → 固定大小，小 chunk
        return "fixed_size_small"

    if doc_analysis["avg_length"] > 3000:
        # 长文档 → 父子分块（子 500 / 父 2000）
        return "parent_child"

    if doc_analysis["chinese_ratio"] > 0.6:
        # 中文文档 → 递归切割，显式传入中文分隔符列表
        # 分隔符优先级: "\n\n" → "\n" → "。" → "！" → "？" → "，" → "、"
        return "recursive_cn"

    # 默认：递归字符切割
    return "recursive"
```

**Chunk Size 与 Overlap 经验值** [✅ B 级: LangCopilot 2026-02 验证]:

| 场景 | chunk_size | overlap | 说明 |
|------|:---:|:---:|------|
| 通用默认 | 500 字 | 50 (10%) | 中文约 500-1000 字符 |
| Token 精确控制 | 256-512 tokens | 50-100 tokens | 黄金区间 |
| 短 FAQ | 200-300 字 | 20-30 | 问答通常很短 |
| 长技术文档（父子-子） | 500 字 | 50 | 子 chunk 做检索 |
| 长技术文档（父子-父） | 2000 字 | 0 | 父 chunk 提供上下文 |
| 法律/合同 | 800-1000 字 | 100-150 | 条款需完整上下文 |

**中文适配要点** [⚠️ C 级: Agent 笔记]:
- 中文分隔符必须自定义: `["\n\n", "\n", "。", "！", "？", "，", "、", "；"]`
- 中文 chunk_size 比英文小（中文信息密度更高）
- BGE 系列模型注意窗口限制（BGE-small-zh: 512 tokens → chunk 留 20% 余量，设 400 tokens）

**上下文检索（Contextual Retrieval）** [🔒 A 级: Anthropic]:

Anthropic 提出的策略——给每个 chunk 加上上下文描述，让它在脱离原文后仍能自解释：
```
原文: "该参数默认值为 30"
上下文化后: "文档: API参考手册 > 第3章 配置 > 超时设置
该参数默认值为 30 秒"
```
- 上下文来源：文件标题 + 章节路径 + 1-2 句摘要
- 上下文长度：50-150 tokens
- 嵌入时使用"上下文 + chunk 原文"，存储时只保留原文
- 成本低，效果显著（消除块脱离原文后的歧义）

### 2.3 检索策略

**默认**: `method=vector, top_k=5, score_threshold=0, bm25_weight=0.3`

**术语密度 → 检索方法**:

```python
def pick_retrieval_method(term_density: float, query_pattern: str) -> str:
    """
    term_density: 专有名词/代码/编号的出现频率
    query_pattern: "natural_language" | "keyword_heavy" | "mixed"
    """
    if term_density > 0.08:          # 高术语密度
        return "hybrid"              # 必须混合检索
    if term_density > 0.04:
        return "hybrid"              # 建议混合检索
    if query_pattern == "keyword_heavy":
        return "hybrid"
    return "vector"                  # 默认纯向量
```

**混合检索核心机制** [✅ B 级: 掘金]:

| 组件 | 说明 |
|------|------|
| **Dense（向量）** | 语义相似度，适合自然语言问答、模糊查询、跨表述问题 |
| **Sparse（BM25）** | 关键词匹配，适合专业术语、代码、编号精准查询 |
| **融合公式** | `score = α × vector_score + (1-α) × BM25_score` |
| **RRF（推荐）** | `score = 1/(rank + k)` 各自排 top-20 → RRF 合并 → top-10 |
| **α 建议值** | 通用 0.7（偏语义）；术语密集 0.5（平衡）；代码查询 0.3（偏关键词）|

**BM25 参数调优** [⚠️ C 级: Agent 笔记]:
- `k1`（词频饱和）: 默认 1.2，关键词权重极高时可上调至 1.5-2.0
- `b`（长度归一化）: 默认 0.75，短文档多时下调至 0.5（减少惩罚）

**Reranker 使用时机** [✅ B 级: 掘金 + LangCopilot]:

| 条件 | 动作 |
|------|------|
| top-1 与 top-3 分数差 < 0.05（难以区分） | 启用 rerank |
| 用户对答案忠实度要求高（法律/医疗/客服） | 始终启用 rerank |
| FAITHFULNESS 指标 < 0.8 | 启用 rerank |
| 推荐模型 | `BAAI/bge-reranker-v2-m3`（中文多语言） |
| 检索流程 | 第一阶段检索 Top-50~100 → Reranker 精排 → Top-5~10 返回 |

**Query 改写方法** [⚠️ C 级: Agent 笔记]:

| 方法 | 原理 | 适用场景 | 开销 |
|------|------|---------|:--:|
| **HyDE** | LLM 生成假设答案 → 用假设答案检索 | Query 与文档写法差异大 | 中（一次 LLM 调用） |
| **子查询分解** | 复杂问题拆成多个子问题分别检索 | 多步推理需求 | 中-高 |
| **Query Rewriting** | LLM 改写为更精准的检索查询 | 用户输入口语化 | 低-中 |
| **Reverse HyDE** | 为每个 chunk 生成假设问题 → 匹配 query | 精度要求极高 | 高（离线预处理） |

**启用条件**: 当检测到 50%+ 查询为口语化自然语言（含"怎么"、"为什么"、"什么是"等）时启用 query_rewrite

### 2.4 存储与索引策略

**默认**: `distance_metric=cosine, HNSW_M=16, ef_construction=100, ef_search=10`

**索引算法选择** [⚠️ C 级: Agent 笔记]:

| 算法 | 适用规模 | 精度 | 内存 | 适合场景 |
|------|---------|:---:|:---:|------|
| **FLAT（暴力）** | < 1 万向量 | 100% | 低 | 法律/医疗高精度场景 |
| **HNSW（默认）** | 1 万-1000 万 | 95-99% | 中-高 | **通用推荐** |
| **IVF_PQ** | > 1000 万 | 90-95% | 低 | 超大规模 |

**HNSW 参数**:
- `M`: 每层连接数。默认 16。索引慢 → 降到 8；追求精度 → 升到 32
- `ef_construction`: 构建探索深度。默认 100。构建太慢 → 降到 50；精度不够 → 升到 200
- `ef_search`: 检索探索深度。默认 10。检索太快但不准 → 升到 20-50

**距离度量**:
- `cosine`: RAG 场景固定默认，适用于归一化向量 [⚠️ C 级: Agent 笔记]
- `l2`: 需要绝对距离阈值过滤时
- `ip`: 向量未归一化时（不推荐）

---

## 3. 运行中优化

### 3.1 RAG 排查五步法

当检索质量持续不佳时，按此流程排查 [⚠️ C 级: Agent 笔记]:

```
Step 1: 答案在不在知识库？
  → 用关键词人工搜索文档原文
  → 搜不到 → 文档缺失，扩充知识库
  → 搜得到 → 进入 Step 2

Step 2: Chunking 有没有把答案切碎？
  → 检查检索出的 chunk 是否完整
  → chunk 太小（< 100 字且不完整）→ 增大 chunk_size 或启用 parent_child
  → chunk 太大（> 1000 字，含多个不同主题）→ 减小 chunk_size 或换语义切割

Step 3: 用户问法和文档写法差别大？
  → 对比 query 词汇和文档词汇
  → 差异大 → 启用 query_rewrite 或 HyDE
  → 有大量同义词/缩写 → 启用混合检索（BM25 + 向量）

Step 4: Embedding 模型够不够用？
  → 构建小规模评测集（50-100 条 QA 对）
  → 计算准召率（Precision/Recall）
  → 召回率 < 0.7 → 换更强的 Embedding 模型
  → 中文占比高但用英文模型 → 必须换 BGE 系列

Step 5: 排序太靠后？
  → 正确结果在检索列表但排名 > top-5
  → → 启用 Reranker（bge-reranker-v2-m3）
  → → 或增大 top_k 到 10-15
```

### 3.2 检索质量信号

Knowledge Agent 在每次检索后收集以下信号用于优化决策:

```python
retrieval_signal = {
    "query": str,
    "query_length": int,
    "query_type": "natural_language" | "keyword" | "code" | "short",
    "top1_score": float,
    "top3_score_gap": float,      # top1 - top3 分数差
    "avg_score": float,           # top-k 平均分
    "user_feedback": "positive" | "negative" | None,
    "user_retry": bool,           # 用户是否重新查了
    "latency_ms": int,
}
```

**优化触发条件**:

| 信号 | 条件 | 动作 |
|------|------|------|
| 低质量 | top1_score < 0.3 连续 20 次 | 触发五步排查 |
| 难以区分 | top3_score_gap < 0.05 | 启用 rerank |
| 查询过短 | avg query_length < 5 字 | 启用 query_rewrite |
| 查询口语化 | natural_language 占比 > 50% | 启用 query_rewrite |
| 用户负面 | user_feedback=negative 连续 5 次 | 主动询问用户具体问题 |
| 延迟高 | latency_ms > 2000 | 减少 top_k 或关闭 rerank |

### 3.3 语义缓存

当检测到相同/高度相似查询频繁出现时，建议启用 [✅ B 级: 掘金]:

```
缓存 Key: query embedding 的近似匹配（cosine > 0.95 视为相同查询）
缓存 Value: 已格式化的检索结果
TTL: 1 小时（文档未更新时）
收益: 响应降至 50ms 内，成本降 30%-50%
```

### 3.4 RAGAS 评测体系

定期（每周 / 每 200 次查询）运行评测 [✅ B 级: 掘金 + ⚠️ C 级: Agent 笔记]:

**核心指标**:

| 指标 | 定义 | 目标 | 偏低时的优化方向 |
|------|------|:--:|------|
| **Context Recall** | 答案所需信息是否全部在检索结果中 | > 0.8 | 增加 top_k / 换 Embedding 模型 / 启用混合检索 |
| **Context Precision** | 相关文档是否排在检索结果前列 | > 0.8 | 启用 Reranker / 调 BM25 权重 |
| **Faithfulness** | 答案是否完全基于检索上下文（有无幻觉） | > 0.9 | 改进 chunking 质量 / 启用 Reranker / 加 System Prompt |
| **Answer Relevance** | 答案是否直接回答了问题 | > 0.8 | 改进 Prompt 模板 / 更换生成模型 |
| **Answer Correctness** | 答案与标准答案的匹配程度 | > 0.8 | 整体优化 |

**评测驱动优化闭环**: 根据指标短板 → 定向调整策略 → 重新评测 → 对比基线 → 确认提升

**F1 值与 MRR 目标** [⚠️ C 级: Agent 笔记]:
- F1 > 0.8（精准率 × 召回率 / (精准率 + 召回率)）
- MRR > 0.7（第一个相关文档的排名倒数平均）

---

## 4. 策略切换详细指南

### 4.1 Chunking 切换

| 当前策略 | 触发条件 | 切换目标 | 操作 |
|---------|---------|---------|------|
| semantic | 文档无结构 + 含大量代码 | recursive | `PATCH {chunk: {method: "recursive"}}` auto |
| semantic | 文档 MD 格式 + 有标题层级 | structure_aware | `PATCH {chunk: {method: "semantic"}}` auto |
| 无 parent_child | avg_length > 3000 字 | 启用 parent_child | `PATCH {chunk: {parent_child_enabled: true, parent_size: 2000}}` 需确认 |
| chunk_size=500 | avg_length < 300 字 | size=200-300 | `PATCH {chunk: {size: 250}}` 需确认 |
| chunk_size=500 | avg_length > 5000 字 | size=800-1000 | `PATCH {chunk: {size: 800}}` 需确认 |
| overlap=50 | 句子被切碎占比 > 10% | overlap=100 (20%) | `PATCH {chunk: {overlap: 100}}` auto |

### 4.2 Embedding 切换

| 当前 | 触发条件 | 切换目标 | 操作 |
|------|---------|---------|------|
| MiniLM | 中文 > 60% + Ollama 可用 | bge-m3 | `PATCH {embed: {backend: "ollama", model: "bge-m3"}}` **需确认** |
| MiniLM | 中文 > 60% + 无 Ollama | bge-large-zh-v1.5 | `PATCH {embed: {model: "BAAI/bge-large-zh-v1.5"}}` **需确认** |
| MiniLM | 英文 < 10万 chunks + 精度不足 | text-embedding-3-large | `PATCH {embed: {backend: "openai", model: "text-embedding-3-large"}}` **需确认** |

### 4.3 检索切换

| 当前 | 触发条件 | 切换目标 | 操作 |
|------|---------|---------|------|
| vector | 术语密度 > 5% | hybrid | `PATCH {retrieval: {method: "hybrid", bm25_weight: 0.3}}` auto |
| hybrid (α=0.7) | 术语密度 > 10% | α=0.5 | `PATCH {retrieval: {bm25_weight: 0.5}}` auto |
| rerank=false | top3_score_gap < 0.05 | rerank=true | `PATCH {retrieval: {rerank_enabled: true}}` auto |
| top_k=5 | query_length < 5 字 | top_k=8-10 | `PATCH {retrieval: {top_k: 8}}` auto |
| top_k=5 | 用户常翻到第 2 页 | top_k=8-10 | `PATCH {retrieval: {top_k: 10}}` auto |
| query_rewrite=false | 口语化查询 > 50% | rewrite=true | `PATCH {retrieval: {query_rewrite_enabled: true}}` auto |
| score_threshold=0 | 低相关度结果太多 | threshold=0.3 | `PATCH {retrieval: {score_threshold: 0.3}}` auto |

### 4.4 存储切换

| 当前 | 触发条件 | 切换目标 | 操作 |
|------|---------|---------|------|
| HNSW M=16 | chunks > 50 万 | M=32 | `PATCH {storage: {hnsw_M: 32}}` auto |
| HNSW ef=10 | 检索结果不稳定 | ef=20 | `PATCH {storage: {hnsw_ef_search: 20}}` auto |
| cosine | — | 不改 | — |

---

## 5. 策略建议输出格式

Knowledge Agent 给出的策略调整建议，用此结构化格式输出:

```markdown
╔══════════════════════════════════════════════╗
║  📊 RAG 策略分析报告                          ║
╠══════════════════════════════════════════════╣
║  分析时间: 2026-07-15 10:30                   ║
║  文档数: 10  | Chunks: 45  | 中文占比: 72%     ║
║  平均文档长度: 3200 字  | 术语密度: 8%         ║
║  策略版本: 20260715-01                        ║
╠══════════════════════════════════════════════╣
║                                                ║
║  ✅ 自动应用的调整（已生效）:                   ║
║    retrieval.method: vector → hybrid           ║
║    retrieval.bm25_weight: 0.0 → 0.3            ║
║      理由: 术语密度 8%，含大量专有名词           ║
║                                                ║
║  ⚠️  需要你确认的调整:                           ║
║                                                ║
║  ① embed.model: MiniLM → BGE-M3               ║
║     理由: 中文占比 72%，MiniLM 精度不足          ║
║     影响: 需要重新索引全部 45 个 chunks         ║
║     前提: 需要运行 Ollama (ollama pull bge-m3) ║
║     精度预期: 中文检索提升 30-50%               ║
║                                                ║
║  ② chunk.parent_child_enabled: false → true    ║
║     理由: 平均文档 3200 字，长文档检索需完整上下文 ║
║     影响: 需要重新切割和索引（存储约翻倍）        ║
║                                                ║
║  💡 可选优化（低优先级）:                        ║
║    retrieval.rerank_enabled → true              ║
║      理由: 当前 top-3 分数差 0.04，难以区分      ║
║      影响: 检索延迟 +100ms，精度提升约 20%       ║
║                                                ║
╚══════════════════════════════════════════════╝
```

---

## 6. 生产部署检查清单

每隔一段时间 Knowledge Agent 应检查以下项 [✅ B 级: 掘金生产级 Checklist]:

- [ ] Chunking 策略与文档类型匹配，chunk_size 经实验验证
- [ ] 混合检索（BM25 + 向量）已启用（术语密度 > 5% 或用户反馈检索不准时）
- [ ] Reranker 已配置（精度要求高时）
- [ ] 语义缓存已启用（重复查询多时）
- [ ] 检索延迟 < 500ms（超时则减少 top_k 或索引优化）
- [ ] 向量数据库正常（ChromaDB 文件未损坏）
- [ ] RAGAS 评测基线已建立，最近一次评测无退化
- [ ] 多租户数据隔离正常（企业用户场景）
- [ ] 增量更新流程正常（文档变更后重新索引及时）

---

## 7. 与 Agent 记忆系统的联动

RAG 知识库是 Agent 记忆系统的一部分 [⚠️ C 级: Agent 笔记 / Memory 四层架构]:

```
Agent 记忆四层架构:
  L1: 当前对话上下文（完整保留）
  L2: 用户长期事实（结构化数据卡）
  L3: 近期对话摘要（压缩存储）
  L4: 知识库 & 成功/失败案例（RAG 向量检索）← 本指南覆盖
```

**联动规则**:
- Logos 总结的笔记 → 自动入库到知识库（source: "logos-daily"）
- 用户明确说"记住这个" → 高优先级索引（加 metadata priority=high）
- 连续 5 次未被检索到的 chunk → 标记冷数据，降低检索权重
- 用户反馈"不对"后重新检索成功的 chunk → 加 metadata verified=true
