"""P2-3: Token 用量的实时 API 端点。

返回当日 token 消耗、按模型拆分、成本估算。
由前端仪表盘调用，与生成服务中的 token 记录联动。
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from ..config import DATA_DIR
from ..middleware.auth import get_optional_user

router = APIRouter(prefix="/api/v1/knowledge", tags=["usage"])

# 用量记录文件路径（统一由 config.DATA_DIR 解析，支持 DATA_DIR 环境变量覆盖）
USAGE_LOG_PATH = os.path.join(DATA_DIR, "usage.jsonl")


class ModelUsage(BaseModel):
    model: str
    tokens: int
    calls: int
    cost_estimate: float


class UsageResponse(BaseModel):
    date: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    by_model: list[ModelUsage]
    limit_warning: bool
    limit_percent: float


def _get_today_iso() -> str:
    """返回当天 ISO 日期字符串，格式 YYYY-MM-DD。"""
    return datetime.now().strftime("%Y-%m-%d")


def _read_today_usage() -> list[dict]:
    """读取当天用量记录。"""
    today = _get_today_iso()
    records = []
    os.makedirs(os.path.dirname(USAGE_LOG_PATH), exist_ok=True)
    try:
        with open(USAGE_LOG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("date") == today:
                        records.append(rec)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return records


# 模型价格（每百万 token，USD）
# 实际价格请根据使用的模型更新
MODEL_PRICES = {
    "deepseek-v4-pro": {"prompt": 2.00, "completion": 8.00},
    "deepseek-chat": {"prompt": 0.27, "completion": 1.10},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """估算 LLM 调用成本。"""
    prices = MODEL_PRICES.get(model, {"prompt": 1.0, "completion": 4.0})
    cost = (prompt_tokens / 1_000_000) * prices["prompt"] + (completion_tokens / 1_000_000) * prices["completion"]
    return round(cost, 6)


@router.get("/usage", response_model=UsageResponse)
def get_usage(user_id: Optional[int] = Depends(get_optional_user)):
    """获取当日 Token 用量汇总。

    返回格式：
        {
            "date": "2026-08-11",
            "prompt_tokens": 15000,
            "completion_tokens": 8000,
            "total_tokens": 23000,
            "estimated_cost_usd": 0.05,
            "by_model": [...],
            "limit_warning": false,
            "limit_percent": 5.0
        }
    """
    records = _read_today_usage()

    total_prompt = 0
    total_completion = 0
    model_stats: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "calls": 0, "cost": 0.0})

    for rec in records:
        prompt = rec.get("prompt_tokens", 0)
        completion = rec.get("completion_tokens", 0)
        model = rec.get("model", "unknown")

        total_prompt += prompt
        total_completion += completion
        model_stats[model]["tokens"] += prompt + completion
        model_stats[model]["calls"] += 1
        model_stats[model]["cost"] += _estimate_cost(model, prompt, completion)

    total_tokens = total_prompt + total_completion
    total_cost = round(sum(m["cost"] for m in model_stats.values()), 6)

    # 预算告警：每日默认上限 1M token
    daily_limit = int(os.getenv("LLM_DAILY_LIMIT_TOKENS", "1000000"))
    limit_percent = round((total_tokens / daily_limit) * 100, 1) if daily_limit else 0
    limit_warning = limit_percent >= 80

    by_model = [
        ModelUsage(
            model=model,
            tokens=stats["tokens"],
            calls=stats["calls"],
            cost_estimate=round(stats["cost"], 6),
        )
        for model, stats in sorted(model_stats.items(), key=lambda x: -x[1]["cost"])
    ]

    return UsageResponse(
        date=_get_today_iso(),
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        total_tokens=total_tokens,
        estimated_cost_usd=total_cost,
        by_model=by_model,
        limit_warning=limit_warning,
        limit_percent=limit_percent,
    )


def log_token_usage(model: str, prompt_tokens: int, completion_tokens: int, status: str = "success") -> None:
    """记录一次 LLM 调用的 token 消耗到用量文件。

    供 generate/service.py 和 stream/service.py 在 LLM 调用完成后调用。
    """
    rec = {
        "date": _get_today_iso(),
        "timestamp": time.time(),
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "status": status,
    }

    os.makedirs(os.path.dirname(USAGE_LOG_PATH), exist_ok=True)
    try:
        with open(USAGE_LOG_PATH, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 不要因用量记录失败而阻塞主业务
