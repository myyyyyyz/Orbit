"""
RAG 策略配置文件。

所有策略都有一个通用默认值，Knowledge Agent 可以在运行时根据实际数据动态调整。
策略调整通过 Python 运行时修改 settings.rag.xxx 或 API 参数覆盖。
"""

import os
from typing import Optional, Literal


class ChunkStrategy:
    """切割策略"""

    # 切割方法
    # "semantic": 按段落/标题切割（适合格式好的文档）
    # "fixed_size": 固定长度切割（适合无格式纯文本）
    method: Literal["semantic", "fixed_size"] = "semantic"

    # 每个 chunk 的最大字符数
    # 中文约 1 char ≈ 1-2 tokens；英文约 1 char ≈ 0.25 tokens
    # 默认 500 适合中文中等段落，英文可上调至 1500
    size: int = 500

    # chunk 间重叠字符数
    # 默认 10% overlap，防止关键信息落在分界处
    overlap: int = 50

    # 父子 chunk 模式
    # True: 索引小块（子），检索时返回大块（父），兼顾精度和上下文完整性
    # False: 仅索引和返回同一 chunk
    # 适用场景：长文档、法律合同、论文
    # 不适用：FAQ、短问答、API 文档
    parent_child_enabled: bool = False

    # 父子模式下，父 chunk 大小（子 chunk 大小仍由 size 控制）
    parent_size: int = 2000

    # 最小 chunk 字符数（低于此值不单独成 chunk，合并到上下文）
    min_size: int = 50

    # 表格/代码等特殊内容是否独立成 chunk
    # True: 表格内容不做切割，整表作为单个 chunk
    table_preserve: bool = True


class EmbedStrategy:
    """Embedding 策略"""

    # 后端
    # "sentence-transformers": 轻量本地，适合英文 / 小规模
    # "ollama": BGE-M3 等模型，中文最优，需本地运行 Ollama
    # "openai": OpenAI text-embedding-3-large，最强但需 API key
    backend: Literal["sentence-transformers", "ollama", "openai"] = "sentence-transformers"

    # 模型名
    # sentence-transformers: "all-MiniLM-L6-v2" (384维, 轻量) / "BAAI/bge-large-zh-v1.5" (1024维, 中文)
    # ollama: "bge-m3" (1024维, 多语言最优)
    # openai: "text-embedding-3-large"
    model: str = "all-MiniLM-L6-v2"

    # 是否做向量归一化
    # cosine 检索时必须为 True
    normalize: bool = True

    # Ollama host（仅 backend=ollama 时有效）
    ollama_host: str = "http://localhost:11434"


class StorageStrategy:
    """存储策略"""

    # 向量距离度量
    # "cosine": 余弦相似度（默认，语义相似度最常用）
    # "l2": 欧氏距离（对绝对位置敏感）
    # "ip": 内积（需向量未归一化时效果最佳）
    distance_metric: Literal["cosine", "l2", "ip"] = "cosine"

    # HNSW 索引参数
    # M: 每层连接数，越大越精确但内存越大，默认 16
    hnsw_M: int = 16
    # ef_construction: 构建时搜索深度，越大越精确但构建越慢，默认 100
    hnsw_ef_construction: int = 100
    # ef_search: 检索时搜索深度，默认 10
    hnsw_ef_search: int = 10

    # Collection 名称
    collection: str = "documents"

    # 持久化目录
    persist_dir: str = os.path.join(os.path.dirname(__file__), "..", "chroma_data")


class RetrievalStrategy:
    """检索策略"""

    # 检索方法
    # "vector": 纯向量检索（默认，通用场景）
    # "hybrid": 向量检索 + BM25 关键词检索（适合有明确术语/关键词的场景）
    # "parent_child": 索引小块检索小块，返回对应大块（需 parent_child_enabled）
    method: Literal["vector", "hybrid", "parent_child"] = "vector"

    # 混合检索中 BM25 的权重
    # 0.0 = 纯向量，1.0 = 纯关键词
    # 默认 0.3，当文档有大量专有名词/编号时上调
    bm25_weight: float = 0.3

    # 检索后是否用 Reranker 精排
    # True: 检索 Top-K*2 → Reranker → 返回 Top-K
    # Reranker 用 cross-encoder 模型（如 bge-reranker-v2-m3）
    rerank_enabled: bool = False

    # 是否启用查询改写
    # True: 用户口语化问题 → LLM 改写为精确检索查询 → 检索
    # 适合客服 / FAQ 场景，用戶問題可能很隨意
    query_rewrite_enabled: bool = False

    # 返回结果数
    top_k: int = 5

    # 多轮检索（Multi-hop）
    # True: 先检索大纲/摘要 → 再检索细节
    # 适合：复杂问题需要多步推理
    multi_hop_enabled: bool = False

    # 相似度阈值（0.0 ~ 1.0）
    # 低于此分数的结果不返回
    # 0.0 = 不限制；0.5 = 相关度低于 50% 不返回
    score_threshold: float = 0.0

    # 去重策略
    # "none": 不去重
    # "exact": 完全相同的 chunk 去重
    # "near": 近似去重（Jaccard 相似度 > 0.8 视为重复）
    dedup: Literal["none", "exact", "near"] = "none"


class RAGStrategy:
    """RAG 总策略"""

    chunk: ChunkStrategy = ChunkStrategy()
    embed: EmbedStrategy = EmbedStrategy()
    storage: StorageStrategy = StorageStrategy()
    retrieval: RetrievalStrategy = RetrievalStrategy()

    # 策略版本号（Knowledge Agent 每次修改后递增）
    # 格式: YYYYMMDD-NN
    version: str = "20260715-01"


class Settings:
    """全局设置"""

    rag: RAGStrategy = RAGStrategy()

    # Upload
    UPLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "..", "uploads")
    MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20 MB

    # 兼容旧接口
    @property
    def CHROMA_PERSIST_DIR(self) -> str:
        return self.rag.storage.persist_dir

    @property
    def CHROMA_COLLECTION(self) -> str:
        return self.rag.storage.collection

    @property
    def EMBED_BACKEND(self) -> str:
        return self.rag.embed.backend

    @property
    def EMBED_MODEL(self) -> str:
        return self.rag.embed.model

    @property
    def OLLAMA_HOST(self) -> str:
        return self.rag.embed.ollama_host

    @property
    def CHUNK_SIZE(self) -> int:
        return self.rag.chunk.size

    @property
    def CHUNK_OVERLAP(self) -> int:
        return self.rag.chunk.overlap

    @property
    def TOP_K(self) -> int:
        return self.rag.retrieval.top_k


settings = Settings()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.rag.storage.persist_dir, exist_ok=True)
