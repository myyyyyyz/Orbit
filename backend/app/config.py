"""
RAG 策略配置文件。

所有策略都有一个通用默认值，Knowledge Agent 可以在运行时根据实际数据动态调整。
策略调整通过 Python 运行时修改 settings.rag.xxx 或 API 参数覆盖。
"""

import os
import sys
from typing import Optional, Literal

from .env_loader import load_env

# 幂等：正常情况下 app/__init__.py 已加载过。此处显式调用是为了保证
# 「单独 import app.config」时 DATA_DIR / DATABASE_URL 等也已就绪。
load_env()

# ─────────────────────────────────────────────────────────────
# 数据根目录解析
#
# 优先级：DATA_DIR 环境变量 > 项目根 data/
# 项目根 = 本文件（backend/app/config.py）向上两级。
# Docker 场景请显式设置 DATA_DIR=/app/data，与 volume 挂载点保持一致。
# ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

DATA_DIR = os.path.abspath(
    os.getenv("DATA_DIR") or os.path.join(_PROJECT_ROOT, "data")
)


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
    """Embedding 策略 —— 单一实现，不做后端可选。

    历史上这里声明了三个后端（sentence-transformers / ollama / openai），
    但只有第一个真正存在实现：embed/core.py 只判断 `== "ollama"`，其余值
    **全部**落到 SentenceTransformerBackend —— 于是 `EMBED_BACKEND=openai`
    既不报错也不生效，只是静默用了本地小模型。这与项目「不降级假装成功」
    的原则相悖，因此直接收敛为一个后端。

    现在统一为 chromadb 自带的 ONNX Runtime 实现，跑的还是同一个模型
    `all-MiniLM-L6-v2`（384 维）—— 因此**现有向量库无需重建**，
    但不再需要 sentence-transformers/torch，镜像少约 5GB
    （torch 会拖进 nvidia-* 3.2GB + triton 0.9GB，而线上机器无 GPU）。
    """

    # 后端固定为 chromadb 内置的 ONNX Runtime 实现（唯一取值）
    backend: Literal["onnx"] = "onnx"

    # 模型固定为 chromadb ONNX 包内自带的 all-MiniLM-L6-v2（384 维）。
    # 该字段仅用于对外展示；模型实体由 ONNX 后端固定加载，不可通过配置替换。
    model: str = "all-MiniLM-L6-v2"

    # 是否做向量归一化（cosine 检索要求归一化）
    # ONNX 后端内部已做 L2 归一化，此项保留作为策略语义标记
    normalize: bool = True

    # ONNX 模型缓存目录（→ <DATA_DIR>/.cache/...，落在数据卷）
    # 必须指向数据卷：容器可写层是临时的，否则每次重建镜像都要重新下载 80MB
    cache_dir: str = os.path.join(
        DATA_DIR, ".cache", "chroma", "onnx_models", "all-MiniLM-L6-v2"
    )


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

    # Collection 名称（全局库：历史遗留的共享空间，仅系统级使用）
    collection: str = "documents"

    # 匿名（未登录）用户的独立向量空间。
    # ⚠️ 绝不与 collection 取同一个值——否则任意未登录访客都能读写、甚至
    # 删除全局库中的全部内容（含早期未做用户隔离时上传的数据）。
    anon_collection: str = os.getenv("ANON_COLLECTION", "anon_sandbox")

    # 持久化目录 → 统一输出到 <DATA_DIR>/chroma_db
    persist_dir: str = os.path.join(DATA_DIR, "chroma_db")


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
    UPLOAD_DIR: str = os.path.join(DATA_DIR, "uploads")
    MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20 MB

    # 数据库 URL 抽象（默认 SQLite，生产可切 PostgreSQL）
    # 例: DATABASE_URL=postgresql://user:pass@host:5432/db
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(os.path.dirname(__file__), '..', 'multitenant.db')}",
    )

    # 兼容旧接口
    @property
    def CHROMA_PERSIST_DIR(self) -> str:
        return self.rag.storage.persist_dir

    @property
    def CHROMA_COLLECTION(self) -> str:
        return self.rag.storage.collection

    @property
    def ANON_COLLECTION(self) -> str:
        """匿名访客的独立向量空间（不得等于 CHROMA_COLLECTION）。"""
        return self.rag.storage.anon_collection

    @property
    def EMBED_BACKEND(self) -> str:
        return self.rag.embed.backend

    @property
    def EMBED_MODEL(self) -> str:
        return self.rag.embed.model

    @property
    def EMBED_CACHE_DIR(self) -> str:
        return self.rag.embed.cache_dir

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


# ── P1-3: 环境配置启动时验证 ──

class ConfigError(RuntimeError):
    """启动配置错误：拒绝启动，避免带着半配置状态对外提供服务。"""


def is_production() -> bool:
    return os.getenv("ENV", "development").lower() in ("prod", "production")


def _validate_config_on_startup():
    """启动时校验关键配置，缺失或无效则拒绝启动。

    在 lifespan 中调用，确保问题尽早暴露而非静默降级。

    策略统一说明（历史上 auth.py 与 config.py 对 SECRET_KEY 采取了两套**相反**策略：
    config 缺了就拒绝启动，auth.py 缺了就自造随机 key）：
    - 生产环境（ENV=production）：SECRET_KEY 缺失/过短 → 拒绝启动。
    - 非生产环境：仅告警（由 middleware/auth.py 生成开发用随机 key）。
    """
    errors = []
    warnings = []

    # LLM API Key
    llm_api_key = os.getenv("LLM_API_KEY", "").strip()
    if not llm_api_key:
        errors.append("LLM_API_KEY 未设置。请在 .env 文件中配置 LLM_API_KEY。")

    # JWT Secret Key —— 生产环境强校验，非生产仅告警
    jwt_secret = os.getenv("SECRET_KEY", "").strip()
    if len(jwt_secret) < 32:
        msg = (
            f"SECRET_KEY 未设置或长度不足（当前 {len(jwt_secret)} 字符，生产环境需 >= 32）。"
            "生成方式：python3 -c \"import secrets; print(secrets.token_hex(32))\"。"
            "变更 SECRET_KEY 会导致所有已签发 Token 立即失效。"
        )
        if is_production():
            errors.append(msg)
        else:
            warnings.append(msg + "（当前为开发环境，将使用进程内随机密钥，重启后 Token 失效）")

    # Fallback 模型自洽性：配了 fallback 模型就必须有 key，否则降级不可能生效
    fb_model = (os.getenv("LLM_FALLBACK_MODEL") or "").strip()
    fb_key = (os.getenv("LLM_FALLBACK_API_KEY") or "").strip()
    if fb_model and not (fb_key or llm_api_key):
        errors.append("配置了 LLM_FALLBACK_MODEL 但没有任何可用 API Key，降级无法生效。")

    # CORS Origins（生产环境不应使用通配符 *）
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    if "*" in cors_origins:
        errors.append("CORS_ORIGINS 不应包含通配符 *（安全风险）。请指定具体域名。")

    # ChromaDB 持久化目录
    persist_dir = settings.rag.storage.persist_dir
    if not os.path.isdir(persist_dir):
        try:
            os.makedirs(persist_dir, exist_ok=True)
        except OSError as e:
            errors.append(f"无法创建 ChromaDB 持久化目录 {persist_dir}: {e}")

    for w in warnings:
        print(f"[config][warn] {w}", file=sys.stderr)

    if errors:
        print("\n" + "=" * 60, file=sys.stderr)
        print(" 配置错误 — 服务拒绝启动", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for i, err in enumerate(errors, 1):
            print(f" [{i}] {err}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        # 抛 ConfigError 而非 sys.exit：在 ASGI lifespan 中 SystemExit 会被 uvicorn
        # 以不容易定位的形式吞掉/打印，异常更适合作为失败信号。
        raise ConfigError("；".join(errors))

