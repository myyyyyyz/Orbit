"""性能相关路由: /api/knowledge/cache/*, /api/knowledge/router/*"""
from fastapi import APIRouter, Body, Depends, HTTPException

from ..middleware.auth import get_current_user, require_role
from ..router import route_model, detect_intent, MODEL_PRESETS
from ..cache import stats as cache_stats, clear as cache_clear

router = APIRouter(prefix="/api/v1/knowledge", tags=["performance"])


@router.get("/cache/stats")
def api_cache_stats(current_user: dict = Depends(get_current_user)):
    """缓存统计：需登录。匿名可读会泄露全站缓存规模与命中率。"""
    return cache_stats()


@router.delete("/cache")
def api_cache_clear(admin: dict = Depends(require_role("admin"))):
    """清空**全局**语义缓存——影响所有用户，属管理操作，仅 admin 可调。

    历史缺陷：无任何认证依赖，匿名 DELETE 即可清空全站缓存（等于给所有人
    一个"让全站缓存失效"的开关）。
    """
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
