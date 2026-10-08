"""槽位 → 检索 query 改写。

设计要点（与"把 key:value 直接拼进 embedding 文本"的区别）：

向量检索吃的是**整体语义相似度**，不是关键词命中。把 ``time:上周 doc_type:部署文档``
这种键值串塞进要 encode 的文本，只会增加噪声 token、稀释真正的检索意图，
而且槽位值本身几乎已经原样存在于用户 query 里，边际收益接近零。

所以本模块只做一件事：**把槽位还原成自然语言片段，仅在原始 query 缺少对应
信息时才补写**（补主语、消解指代、把相对时间锚定为绝对时间）。
最终改写结果是纯自然语言，可安全送进 embedding。
"""

from typing import Optional

# 相对时间 → 绝对日期锚定（让 embedding 能理解"上周"到底指哪段时间）
_RELATIVE_TIME = {
    "前天": "前天",
    "昨天": "昨天",
    "今天": "今天",
    "上周": "上周",
    "本周": "本周",
    "这周": "本周",
    "上个月": "上个月",
    "本月": "本月",
    "去年": "去年",
    "今年": "今年",
    "最近": "最近",
    "近期": "最近",
    "刚才": "刚才",
}

# 可以安全拼进检索 query 的槽位（值本身是自然语言，不产生噪声）
_QUERY_SAFE_SLOTS = ("doc_type", "time", "path", "error", "language", "entity")


def rewrite_query_with_slots(query: str, slots: dict) -> str:
    """
    用槽位改写检索 query：补主语/时间，但**不制造噪声**。

    规则（保守优先，宁可不改也不要改坏）：
    1. 只补 ``_QUERY_SAFE_SLOTS`` 里值本身是自然语言的槽位；
    2. **槽位值已出现在原query 中就跳过**——embedding 已经能看到它，重复只会稀释信号；
    3. 只做"尾部追加补语"，绝不删除或改写用户原话。

    返回答题串；无可补时原样返回 query。
    """
    if not slots:
        return query

    additions = []
    for name in _QUERY_SAFE_SLOTS:
        value = slots.get(name)
        if not value:
            continue
        # 已存在于原 query → embedding 本就能看到，不重复注入
        if str(value) in query:
            continue
        if name == "time":
            # 相对时间锚定：把"上周"补成明确的相对时间表述
            anchored = _RELATIVE_TIME.get(str(value))
            if anchored:
                additions.append(anchored)
        elif name == "path":
            additions.append(f"文件 {value}")
        elif name == "error":
            additions.append(f"报错 {value}")
        else:
            additions.append(str(value))

    if not additions:
        return query
    return f"{query} {' '.join(additions)}"


def build_metadata_filter(slots: dict, chunk_metadata_keys: set = None) -> Optional[dict]:
    """
    把槽位翻译成 ChromaDB ``where`` 过滤条件（元数据精确过滤，非 embedding）。

    仅当 ``chunk_metadata_keys`` 声明了该字段时才生成过滤——避免对不存在的
    metadata 字段做where 过滤导致检索直接报错或返回空。
    调用方需确保入库时确实写入了对应字段。
    """
    if not slots or not chunk_metadata_keys:
        return None

    where = {}
    # doc_type 直连
    doc_type = slots.get("doc_type")
    if doc_type and "doc_type" in chunk_metadata_keys:
        where["doc_type"] = doc_type
    return where or None