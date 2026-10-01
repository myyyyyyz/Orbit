"""Embedding 后端实现（单一实现：chromadb 内置 ONNX Runtime）。

为什么是 ONNX：
- 同一个模型 `all-MiniLM-L6-v2`（384 维），只是推理引擎从 PyTorch 换成 ONNX
  Runtime → **现有向量库不需要重建**；
- `onnxruntime` / `tokenizers` / `tqdm` 本来就是 chromadb 0.5.5 的必需依赖，
  等于"已经付过钱"，删掉 sentence-transformers 不新增任何依赖；
- 去掉 sentence-transformers 即去掉 torch，连带去掉 nvidia-*（3.2GB）与
  triton（0.9GB）——线上是纯 CPU 机器，这些一个字节都用不到。

模型来源：`https://chroma-onnx-models.s3.amazonaws.com/...`（不走 HuggingFace，
所以国内机器不需要 HF_ENDPOINT 镜像）。首次下载约 80MB，之后落缓存目录复用。
"""

import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

# 模型维度（all-MiniLM-L6-v2）。现有向量库按此维度建立，更换模型必须重建索引。
EMBED_DIM = 384


class EmbeddingBackend:
    """统一的 Embedding 接口"""

    def __init__(self):
        self._model = None
        self._loaded = False

    def load(self):
        raise NotImplementedError

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def is_loaded(self) -> bool:
        return self._loaded


class OnnxBackend(EmbeddingBackend):
    """chromadb 自带 ONNX Runtime 实现（all-MiniLM-L6-v2, 384 维）"""

    def load(self):
        if self._model is None:
            # 延迟导入：让 `import app.embed` 本身不拉起 onnxruntime
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
                ONNXMiniLM_L6_V2,
            )

            # 默认下载路径是 Path.home()/.cache/...（容器里是 /home/orbit，属可写层，
            # 重建镜像即丢失）。改到数据卷，下载一次长期复用。
            cache_dir = Path(settings.EMBED_CACHE_DIR)
            cache_dir.mkdir(parents=True, exist_ok=True)
            ONNXMiniLM_L6_V2.DOWNLOAD_PATH = cache_dir

            logger.info(
                "Loading embedding model: %s (onnx, cache=%s) ...",
                settings.EMBED_MODEL,
                cache_dir,
            )
            self._model = ONNXMiniLM_L6_V2()
            self._loaded = True
            logger.info("Embedding model loaded: %s (onnx)", settings.EMBED_MODEL)
        return self

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self.load()
        # 模型内部已按 batch_size=32 分批，并做 mean pooling + L2 归一化，
        # 与原先 sentence-transformers 的 normalize_embeddings=True 等价。
        vectors = self._model(list(texts))
        return [[float(x) for x in vec] for vec in vectors]
