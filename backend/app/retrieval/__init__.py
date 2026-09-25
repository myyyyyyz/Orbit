"""查询期自适应 RAG 调度器（RetrievalPlanner）。

替代原摄取期 knowledge_agent 的"选切分策略"职责：在用户提问时，
用 LLM 规划检索方式（是否检索 / 向量·混合·关键词 / 改写 / 子问题 /
top_k / 阈值 / 迭代），再驱动 search() 执行。无 API key 或调用失败时
确定性降级为默认计划，保证链路不出错。
"""

from .planner import (
    RetrievalPlan,
    plan_retrieval,
    execute_retrieval_plan,
)

__all__ = [
    "RetrievalPlan",
    "plan_retrieval",
    "execute_retrieval_plan",
]
