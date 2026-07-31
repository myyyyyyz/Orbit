"""性能相关路由: /api/knowledge/cache/*, /api/knowledge/router/*"""
from fastapi import APIRouter, Body, HTTPException

from ..router import route_model, detect_intent, MODEL_PRESETS
from ..cache import stats as cache_stats, clear as cache_clear

router = APIRouter(prefix="/api/knowledge", tags=["performance"])


@router.get("/cache/stats")
def api_cache_stats():
    return cache_stats()


@router.delete("/cache")
def api_cache_clear():
    cache_clear()
    return {"status": "ok", "message": "缓存已清空"}


@router.get("/router/models")
def api_router_models():
    return MODEL_PRESETS


@router.post("/router/predict")
def api_router_predict(body: dict = Body(...)):
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "查询不能为空")
    intent = detect_intent(query)
    route = route_model(query)
    return {
        "query": query,
        "intent": intent,
        "tier": route.tier,
        "model": route.model,
        "reason": route.reason,
        "confidence": route.confidence,
        "needs_clarification": route.needs_clarification,
        "clarification_question": route.clarification_question if route.needs_clarification else "",
    }
