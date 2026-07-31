"""混合存储路由: /api/storage/*"""
from fastapi import APIRouter, Body, HTTPException

from ..storage_router import route_storage, get_strategy_info, detect_content_type

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/strategies")
def api_storage_strategies():
    return get_strategy_info()


@router.post("/analyze")
def api_storage_analyze(body: dict = Body(...)):
    filename = body.get("filename", "")
    text = body.get("text", "")
    file_size = body.get("file_size", 0)
    if not filename:
        raise HTTPException(400, "文件名不能为空")
    result = route_storage(filename, text, file_size)
    return result
