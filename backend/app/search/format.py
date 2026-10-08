"""检索结果格式化输出"""

from .core import search


def search_formatted(query: str, top_k: int = None, scope=None) -> str:
    """
    搜索并返回格式化文本，可直接注入 Agent 上下文。

    scope 为 TenantScope 或 None（None 时取请求级租户上下文）。
    """
    items = search(query, top_k, scope)
    if not items:
        return "（知识库中未找到相关内容）"

    lines = ["## 知识库检索结果\n"]
    for i, item in enumerate(items, 1):
        metadata = item.get("metadata") or {}
        source = metadata.get("source_path") or metadata.get("source", "未知")
        scope_label = "组织共享" if metadata.get("scope") == "shared" else "我的文档"
        lines.append(f"### 结果 {i}（相关度: {item['score']:.0%} | 来源: {source} | {scope_label}）")
        lines.append(item["text"])
        lines.append("")

    return "\n".join(lines)
