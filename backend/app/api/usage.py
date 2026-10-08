"""P2-3: Token 用量的实时 API 端点。

返回当日 token 消耗、按模型拆分、成本估算。
由前端仪表盘调用，与生成服务中的 token 记录联动。

多租户口径（本轮改造后再收紧一层）
----------------------------------
每条记录都带 ``tenant_id`` + ``user_id`` 归属；读取时只汇总**当前请求方所属租户**
的记录。历史实现只按 user_id 过滤且限额是全局的——同一个组织里 A 用完额度
会拖住 B，而且组织管理员看不到本组织的汇总。

匿名访客只看到匿名记录（``tenant_id`` 为 None），不会触达任何租户的消耗。
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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
    tenant_id: Optional[str] = None
    scope: str = "tenant"


def _get_today_iso() -> str:
    """返回当天 ISO 日期字符串，格式 YYYY-MM-DD。"""
    return datetime.now().strftime("%Y-%m-%d")


def _read_today_usage(
    user_id: Optional[int] = None, tenant_id: Optional[str] = None
) -> list[dict]:
    """读取当天属于该租户（或该匿名请求方）的用量记录。

    归属判定：
    - 提供 ``tenant_id`` → 只取同租户记录（含该租户内所有成员，组织级汇总）
    - 未提供（匿名）    → 只取 ``tenant_id`` 为空且 ``user_id`` 相等的记录。

    历史上这里不带任何过滤，任何用户都能看到**全站**消耗与成本。
    """
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
                except json.JSONDecodeError:
                    continue
                if rec.get("date") != today:
                    continue
                if tenant_id:
                    if rec.get("tenant_id") != tenant_id:
                        continue
                else:
                    # 匿名：既无租户归属，又要与自己那一条对齐
                    if rec.get("tenant_id") or rec.get("user_id") != user_id:
                        continue
                records.append(rec)
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
def get_usage(current_user: Optional[dict] = Depends(get_optional_user)):
    """获取当日 Token 用量汇总（**仅当前请求方所属租户**）。

    历史缺陷：入参名写成 `user_id: Optional[int] = Depends(get_optional_user)`，
    实际注入的是整个 user dict；且 `_read_today_usage()` 不带过滤，返回**全站**
    当日用量——任何用户都能看到别人的消耗与成本。
    """
    tenant_id = current_user.get("tenant_id") if current_user else None
    user_id = current_user.get("user_id") if current_user else None
    records = _read_today_usage(user_id=user_id, tenant_id=tenant_id)

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

    # 预算告警：**按租户**计的每日上限（历史上是按全站计的，一个组织跑满
    # 会让所有组织一起收到告警）。
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
        tenant_id=tenant_id,
        scope="tenant" if tenant_id else "anonymous",
    )


def log_token_usage(model: str, prompt_tokens: int, completion_tokens: int,
                    status: str = "success", user_id: Optional[int] = None,
                    tenant_id: Optional[str] = None) -> None:
    """记录一次 LLM 调用的 token 消耗到用量文件。

    供 generate/service.py 在 LLM 调用完成后调用。
    ``tenant_id`` + ``user_id`` 决定这条记录归属谁；两者都缺省则记为匿名。
    """
    rec = {
        "date": _get_today_iso(),
        "timestamp": time.time(),
        "tenant_id": tenant_id,
        "user_id": user_id,
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
