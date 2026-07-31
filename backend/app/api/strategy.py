"""RAG 策略路由: /api/knowledge/strategy"""
import copy
from datetime import datetime
from fastapi import APIRouter, Body, HTTPException

from ..config import settings, RAGStrategy
from ..schemas.strategy import StrategyPatch, _apply_section

router = APIRouter(prefix="/api/knowledge", tags=["strategy"])


def _strategy_to_dict() -> dict:
    s = settings.rag
    return {
        "version": s.version,
        "chunk": {
            "method": s.chunk.method,
            "size": s.chunk.size,
            "overlap": s.chunk.overlap,
            "parent_child_enabled": s.chunk.parent_child_enabled,
            "parent_size": s.chunk.parent_size,
            "min_size": s.chunk.min_size,
            "table_preserve": s.chunk.table_preserve,
        },
        "embed": {
            "backend": s.embed.backend,
            "model": s.embed.model,
            "normalize": s.embed.normalize,
            "ollama_host": s.embed.ollama_host,
        },
        "storage": {
            "distance_metric": s.storage.distance_metric,
            "hnsw_M": s.storage.hnsw_M,
            "hnsw_ef_construction": s.storage.hnsw_ef_construction,
            "hnsw_ef_search": s.storage.hnsw_ef_search,
            "collection": s.storage.collection,
        },
        "retrieval": {
            "method": s.retrieval.method,
            "bm25_weight": s.retrieval.bm25_weight,
            "rerank_enabled": s.retrieval.rerank_enabled,
            "query_rewrite_enabled": s.retrieval.query_rewrite_enabled,
            "top_k": s.retrieval.top_k,
            "multi_hop_enabled": s.retrieval.multi_hop_enabled,
            "score_threshold": s.retrieval.score_threshold,
            "dedup": s.retrieval.dedup,
        },
    }


def _apply_strategy_patch(strategy: RAGStrategy, patch: dict):
    validated = StrategyPatch(**patch)
    apply_map = {
        "chunk": strategy.chunk,
        "embed": strategy.embed,
        "storage": strategy.storage,
        "retrieval": strategy.retrieval,
    }
    for section_name, section_patch in validated.model_dump(exclude_unset=True).items():
        if section_patch is not None and section_name in apply_map:
            _apply_section(apply_map[section_name], getattr(validated, section_name))


def _diff_strategy(before: dict, after: dict) -> list:
    changes = []

    def _compare(section: str, b: dict, a: dict):
        for key in b:
            if key in a and b[key] != a[key]:
                changes.append({"field": f"{section}.{key}", "before": b[key], "after": a[key]})

    _compare("chunk", before["chunk"], after["chunk"])
    _compare("embed", before["embed"], after["embed"])
    _compare("storage", before["storage"], after["storage"])
    _compare("retrieval", before["retrieval"], after["retrieval"])
    return changes


@router.get("/strategy")
def api_get_strategy():
    s = _strategy_to_dict()
    s["_defaults_note"] = "所有字段均有默认值。PATCH 可部分更新。embed 大类变更需用户确认。"
    s["_readonly"] = ["version"]
    s["_auto_apply_fields"] = [
        "retrieval.*", "chunk.method", "chunk.overlap", "chunk.min_size", "storage.hnsw_ef_search",
    ]
    s["_requires_confirm_fields"] = [
        "embed.*", "chunk.size", "chunk.parent_child_enabled", "storage.distance_metric",
    ]
    return s


@router.patch("/strategy")
def api_patch_strategy(patch: dict = Body(...)):
    before = copy.deepcopy(_strategy_to_dict())
    try:
        _apply_strategy_patch(settings.rag, patch)
    except Exception as e:
        raise HTTPException(400, f"策略更新失败: {str(e)}")

    settings.rag.version = datetime.now().strftime("%Y%m%d") + "-" + \
        str(int(settings.rag.version.split("-")[-1]) + 1).zfill(2)
    after = _strategy_to_dict()
    return {"status": "ok", "version": settings.rag.version, "changes": _diff_strategy(before, after)}
