"""查询期检索计划：LLM 调度 + 轻量混合检索(RRF 融合) + 改写/子问题/迭代执行。

设计要点
--------
- plan_retrieval(): 有 LLM_API_KEY 时调用 LLM 产出结构化 RetrievalPlan；
  无 key 或解析失败 → 返回确定性默认计划（retrieve=True, vector, 无改写）。
  这与 router/_llm_classify、stream_ask 的"无 key 走 fallback"行为一致。
- execute_retrieval_plan(): 按 plan 改写 query、子问题并行检索、混合融合、
  按 top_k/threshold 过滤、max_iterations 迭代累积去重重排，返回 chunks。
- 混合检索不引入独立关键词索引：向量召回 top_k*2 候选后算词面 BM25 风格分，
  与向量分做 RRF 融合重排（支撑 strategy=vector/hybrid/keyword）。
"""

import json
import logging
import os
import re
import urllib.request
from typing import Optional

from pydantic import BaseModel, Field

from ..search import search

logger = logging.getLogger(__name__)

# 注意：本模块不依赖 app.config，避免导入时拉起 chroma/heavy 依赖；
# 默认阈值与 top_k 用下方常量，LLM 调用读环境变量。

# 默认相关度阈值（与 stream/service.py 的 MIN_RELEVANCE_SCORE 对齐）
DEFAULT_THRESHOLD = 0.3
DEFAULT_TOP_K = 5

_STRATEGY_ALLOWED = ("vector", "hybrid", "keyword")


# ─────────────────────────────────────────────────────────────────────────
# 决策模型
# ─────────────────────────────────────────────────────────────────────────
class RetrievalPlan(BaseModel):
    """LLM 产出的检索计划（已做清洗与边界收敛）。"""

    retrieve: bool = True
    strategy: str = "vector"          # vector | hybrid | keyword
    rewritten_query: Optional[str] = None
    subquestions: list[str] = Field(default_factory=list)
    top_k: int = DEFAULT_TOP_K
    threshold: float = DEFAULT_THRESHOLD
    max_iterations: int = 1
    use_tools: bool = False           # v2 预留：真实工具调用层尚未接入


def _default_plan() -> RetrievalPlan:
    return RetrievalPlan(
        retrieve=True,
        strategy="vector",
        rewritten_query=None,
        subquestions=[],
        top_k=DEFAULT_TOP_K,
        threshold=DEFAULT_THRESHOLD,
        max_iterations=1,
        use_tools=False,
    )


def _sanitize_plan(data: dict) -> RetrievalPlan:
    """把 LLM 返回的任意 dict 收敛成合法 RetrievalPlan；任何异常→默认计划。"""
    try:
        retrieve = bool(data.get("retrieve", True))

        strategy = str(data.get("strategy", "vector")).lower()
        if strategy not in _STRATEGY_ALLOWED:
            strategy = "vector"

        rq = data.get("rewritten_query")
        rewritten = rq.strip() if isinstance(rq, str) and rq.strip() else None

        subs = [
            s.strip()
            for s in (data.get("subquestions") or [])
            if isinstance(s, str) and s.strip()
        ]

        top_k = int(data.get("top_k", DEFAULT_TOP_K))
        top_k = max(1, min(50, top_k))

        threshold = float(data.get("threshold", DEFAULT_THRESHOLD))
        threshold = max(0.0, min(1.0, threshold))

        mi = int(data.get("max_iterations", 1))
        mi = max(1, min(5, mi))

        use_tools = bool(data.get("use_tools", False))

        return RetrievalPlan(
            retrieve=retrieve,
            strategy=strategy,
            rewritten_query=rewritten,
            subquestions=subs,
            top_k=top_k,
            threshold=threshold,
            max_iterations=mi,
            use_tools=use_tools,
        )
    except Exception:
        logger.debug("retrieval plan sanitize failed, use default", exc_info=True)
        return _default_plan()


_PLANNER_SYSTEM = """你是一个 RAG 检索调度器。根据用户问题，决定如何检索知识库。
只输出一个 JSON 对象，不要任何解释或 markdown。字段说明：
{
  "retrieve": true 或 false,          // 常识/闲聊/与知识库无关→false（直接对话，不检索）
  "strategy": "vector"|"hybrid"|"keyword",  // 偏关键词/专有名词/缩写→hybrid 或 keyword；语义问题→vector
  "rewritten_query": "改写后的检索问句，无需改写则 null",  // 口语化/有歧义时改写成精准检索句
  "subquestions": ["子问题1","子问题2"],   // 复杂复合问题拆成并行子问题；无则 []
  "top_k": 5,                         // 召回条数，1-20
  "threshold": 0.3,                   // 相关度阈值，0-1，越高越严格
  "max_iterations": 1,               // 迭代检索次数，1-3（先检索再据结果补检索）
  "use_tools": false                 // 是否需要调用外部工具（数据库/API），默认 false
}
示例：闲聊"你好" → {"retrieve":false,"strategy":"vector","rewritten_query":null,"subquestions":[],"top_k":5,"threshold":0.3,"max_iterations":1,"use_tools":false}
示例：复合问"对比 A 和 B 的优缺点并给部署步骤" → {"retrieve":true,"strategy":"hybrid","rewritten_query":null,"subquestions":["A 的优缺点","B 的优缺点","A/B 部署步骤"],"top_k":8,"threshold":0.25,"max_iterations":2,"use_tools":false}"""


def plan_retrieval(question: str, user_id: Optional[int] = None,
                   api_key: Optional[str] = None) -> RetrievalPlan:
    """规划本次提问的检索方式。best-effort：任何失败都降级为默认计划。"""
    key = api_key or os.getenv("LLM_API_KEY", "")
    if not key:
        return _default_plan()

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("LLM_MODEL_FAST", os.getenv("LLM_MODEL", "gpt-4o-mini"))

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
            content = result["choices"][0]["message"]["content"]
            data = json.loads(content)
            return _sanitize_plan(data)
    except Exception:
        logger.debug("retrieval planner LLM call failed, use default plan", exc_info=True)
        return _default_plan()


# ─────────────────────────────────────────────────────────────────────────
# 轻量词面打分 + RRF 融合（混合检索，无需独立索引）
# ─────────────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _lexical_score(doc: str, query_tokens: list[str]) -> float:
    """BM25 风格词面相关度（归一化词频，按命中的查询词数归一）。"""
    if not query_tokens:
        return 0.0
    doc_tokens = _tokenize(doc)
    if not doc_tokens:
        return 0.0
    counter = {}
    for t in doc_tokens:
        counter[t] = counter.get(t, 0) + 1
    doc_len = len(doc_tokens)
    raw = 0.0
    hits = 0
    for qt in set(query_tokens):
        tf = counter.get(qt, 0)
        if tf:
            raw += tf / doc_len
            hits += 1
    # 归一化：避免长文档因总词频高而虚高
    return raw / hits if hits else 0.0


def _rrf_fuse(items: list[dict], query: str, top_k: int, strategy: str) -> list[dict]:
    """向量分 + 词面分做 RRF 融合重排。

    - vector: 直接按向量顺序返回（融合即恒等）
    - hybrid: 向量分与词面分等权融合
    - keyword: 仅用词面分（向量仅作候选召回）
    """
    if not items:
        return []
    if strategy == "vector":
        return items[:top_k]

    q_tokens = _tokenize(query)
    lex_scores = [(_lexical_score(it.get("text", ""), q_tokens), i) for i, it in enumerate(items)]

    vec_order = sorted(range(len(items)), key=lambda i: items[i]["score"], reverse=True)
    lex_order = sorted(range(len(items)), key=lambda i: lex_scores[i][0], reverse=True)

    K = 60.0
    vec_rank = {idx: r for r, idx in enumerate(vec_order)}
    lex_rank = {idx: r for r, idx in enumerate(lex_order)}

    fused = []
    for i, it in enumerate(items):
        vs = 1.0 / (K + vec_rank[i]) if strategy in ("hybrid", "vector") else 0.0
        ls = 1.0 / (K + lex_rank[i]) if strategy in ("hybrid", "keyword") else 0.0
        fused.append((it, vs + ls))

    fused.sort(key=lambda x: x[1], reverse=True)
    return [it for it, _ in fused[:top_k]]


# ─────────────────────────────────────────────────────────────────────────
# 计划执行器：改写 / 子问题 / 迭代 / 融合 / 过滤
# ─────────────────────────────────────────────────────────────────────────
def execute_retrieval_plan(question: str, user_id: Optional[int] = None,
                           plan: Optional[RetrievalPlan] = None,
                           api_key: Optional[str] = None) -> list[dict]:
    """按 RetrievalPlan 执行检索，返回过滤+重排后的 chunks 列表。"""
    if plan is None:
        plan = _default_plan()

    if not plan.retrieve:
        return []

    base_q = plan.rewritten_query or question
    queries = [base_q]
    for sq in plan.subquestions:
        if sq and sq != base_q:
            queries.append(sq)

    over_fetch = max(plan.top_k, 1) * 2  # 过召回供融合/迭代
    iterations = max(1, plan.max_iterations)

    collected: dict[str, dict] = {}
    seen_texts: set[str] = set()

    for _ in range(iterations):
        for q in queries:
            items = search(q, over_fetch, user_id)
            if not items:
                continue
            fused = _rrf_fuse(items, q, over_fetch, plan.strategy)
            for item in fused:
                t = item.get("text", "")
                if t and t not in seen_texts:
                    seen_texts.add(t)
                    collected[t] = item
        # 已有足够高相关候选则提前结束迭代
        if len(collected) >= plan.top_k:
            break

    result = [it for it in collected.values() if it.get("score", 0.0) >= plan.threshold]
    result.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return result[:plan.top_k]
