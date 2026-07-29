"""搜索模块：向量检索 + 结果后处理"""

from ..config import settings
from ..embed import encode
from ..store import get_collection


def search(query: str, top_k: int = None) -> list[dict]:
    """
    语义搜索知识库。
    返回: [{"text": str, "metadata": dict, "score": float}, ...]
    """
    if top_k is None:
        top_k = settings.TOP_K
    if top_k < 1:
        return []

    collection = get_collection()

    if collection.count() == 0:
        return []

    # 查询向量化
    query_embedding = encode([query])[0]

    # 语义检索
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    items = []
    for i in range(len(results["ids"][0])):
        distance = results["distances"][0][i] if results["distances"] else 1.0
        score = 1.0 - distance  # cosine distance → similarity
        items.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "score": round(score, 4),
        })

    # 按相似度降序
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def search_formatted(query: str, top_k: int = None) -> str:
    """
    搜索并返回格式化文本，可直接注入 Agent 上下文。
    """
    items = search(query, top_k)
    if not items:
        return "（知识库中未找到相关内容）"

    lines = ["## 知识库检索结果\n"]
    for i, item in enumerate(items, 1):
        source = item["metadata"].get("source", "未知")
        lines.append(f"### 结果 {i}（相关度: {item['score']:.0%} | 来源: {source}）")
        lines.append(item["text"])
        lines.append("")

    return "\n".join(lines)
