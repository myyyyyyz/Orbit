"""
LLM API 调用可靠性保障：重试 + 熔断 + Fallback。

核心策略：
- 指数退避重试（tenacity）：临时故障（网络超时、429 限流）自动重试
- 熔断器（pybreaker）：连续失败 N 次后短暂拒绝所有请求，防止雪崩
- Fallback 模型：主模型不可用时自动切换到备用模型

Usage:
    from .retry import call_llm_with_retry
    result = call_llm_with_retry(
        call_fn=lambda: urllib.request.urlopen(primary_req, timeout=30),
        fallback_call_fn=lambda: urllib.request.urlopen(fallback_req, timeout=30),
        model_name="deepseek-chat",
        fallback_model="gpt-4o-mini",
    )

⚠️ 关键约束：fallback_call_fn 必须是**用 fallback 模型/Key 重建的请求**。
历史缺陷：旧实现直接复用 call_fn，而调用方闭包里 req 已固化了主模型与主 Key，
导致 fallback 发出的是一字不差的同一个请求、熔断 open 时仍然死打故障端点，
且 `model_used` 会把 fallback 模型名透传给前端——前端看到的模型名是假的。
**没有 fallback_call_fn 时本模块不会伪装降级**，直接抛 LLMCallFailedError。
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Callable, Optional

import pybreaker
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
    after_log,
)

# 使用 structlog 结构化日志
from ..logging_config import get_logger
from .client import DEFAULT_LLM_MODEL

logger = get_logger(__name__)

# 保留标准 logging 引用供 tenacity 的 before_sleep_log/after_log 使用
_stdlib_logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════

# 主模型配置（默认值与 .env.example / docker-compose 对齐，见 client.DEFAULT_LLM_MODEL）
LLM_PRIMARY_MODEL = os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL
LLM_FALLBACK_MODEL = (os.getenv("LLM_FALLBACK_MODEL") or "").strip()
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "") or os.getenv("LLM_API_KEY", "")

# 重试配置
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_MIN_WAIT = float(os.getenv("LLM_RETRY_MIN_WAIT", "1.0"))  # 秒
LLM_RETRY_MAX_WAIT = float(os.getenv("LLM_RETRY_MAX_WAIT", "30.0"))  # 秒

# 熔断器配置
LLM_CB_FAIL_MAX = int(os.getenv("LLM_CB_FAIL_MAX", "5"))  # 连续失败 N 次后熔断
LLM_CB_TIMEOUT = int(os.getenv("LLM_CB_TIMEOUT", "60"))  # 熔断后 N 秒尝试恢复


# ═══════════════════════════════════════════════
# 可重试异常判断
# ═══════════════════════════════════════════════

def _is_retryable(exception: Exception) -> bool:
    """判断异常是否可重试。

    可重试：网络超时、服务暂时不可用、限流（429）、服务器错误（5xx）
    不可重试：认证失败（401）、权限不足（403）、请求格式错误（400）
    """
    # urllib 错误
    if isinstance(exception, urllib.error.URLError):
        return True
    if isinstance(exception, urllib.error.HTTPError):
        code = getattr(exception, "code", 0)
        # 429 Too Many Requests / 5xx Server Error 可重试
        return code == 429 or (500 <= code < 600)
    if isinstance(exception, TimeoutError):
        return True
    if isinstance(exception, ConnectionError):
        return True

    # 检查异常消息
    msg = str(exception).lower()
    retryable_keywords = ["timeout", "connection", "rate limit", "too many requests", "server error", "service unavailable"]
    for keyword in retryable_keywords:
        if keyword in msg:
            return True

    return False


# ═══════════════════════════════════════════════
# 熔断器
# ═══════════════════════════════════════════════

_breaker = pybreaker.CircuitBreaker(
    fail_max=LLM_CB_FAIL_MAX,
    reset_timeout=LLM_CB_TIMEOUT,
    name="llm_api",
)

_breaker_fallback = pybreaker.CircuitBreaker(
    fail_max=LLM_CB_FAIL_MAX,
    reset_timeout=LLM_CB_TIMEOUT,
    name="llm_api_fallback",
)


def _is_circuit_open() -> bool:
    """检查主模型熔断器是否开启。"""
    return _breaker.current_state == "open"


def reset_circuit_breakers() -> None:
    """把两个熔断器复位为 closed。

    熔断器是模块级全局状态，会跨测试用例累积失败计数——一旦某个用例把
    熔断器打到 open，后续用例会全部走 fallback 分支，产生与代码无关的随机失败。
    测试夹具应在每个用例后调用本函数。
    """
    for breaker in (_breaker, _breaker_fallback):
        try:
            breaker.close()
        except Exception:  # noqa: BLE001 - 复位失败不应影响测试主流程
            pass


# ═══════════════════════════════════════════════
# 重试装饰器
# ═══════════════════════════════════════════════

def _create_retry_decorator():
    """创建 tenacity 重试装饰器。"""
    return retry(
        stop=stop_after_attempt(LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=LLM_RETRY_MIN_WAIT, max=LLM_RETRY_MAX_WAIT),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(_stdlib_logger, logging.WARNING),
        after=after_log(_stdlib_logger, logging.DEBUG),
        reraise=True,
    )


# ═══════════════════════════════════════════════
# 核心调用函数
# ═══════════════════════════════════════════════

def call_llm_with_retry(
    call_fn: Callable[[], Any],
    fallback_call_fn: Optional[Callable[[], Any]] = None,
    model_name: Optional[str] = None,
    fallback_model: Optional[str] = None,
    fallback_api_key: Optional[str] = None,
) -> dict:
    """
    带重试和熔断保护的 LLM API 调用。

    调用流程：
    1. 检查主模型熔断器 → 若已熔断，直接走 fallback
    2. 调用主模型（带指数退避重试）
    3. 主模型失败 → 用 fallback_call_fn 切换到 fallback 模型

    参数:
        call_fn: 无参 callable，执行主模型 HTTP 请求
        fallback_call_fn: 无参 callable，执行 **fallback 模型** 的 HTTP 请求。
            必须由调用方用 fallback 的 base_url/model/api_key 重建；
            为 None 时不做降级（绝不复用 call_fn 冒充降级）。
        model_name: 主模型名称（用于日志与 model_used 上报）
        fallback_model: Fallback 模型名（默认用全局配置）
        fallback_api_key: Fallback 模型的 API Key（默认用全局配置）

    返回:
        {"success": True, "data": {...}, "model_used": "xxx"}

    抛出:
        LLMCallFailedError: 所有重试和 fallback 都失败
    """
    model_name = model_name or LLM_PRIMARY_MODEL
    fallback_model = fallback_model or LLM_FALLBACK_MODEL or None
    fallback_api_key = fallback_api_key or LLM_FALLBACK_API_KEY

    retry_decorator = _create_retry_decorator()
    last_error = None  # 捕获最后一次错误

    # ── 步骤 1: 尝试主模型 ──
    try:
        if _breaker.current_state == "open":
            logger.warning(
                "circuit_breaker_open",
                model=model_name,
                message="主模型熔断器已开启，跳过主模型调用",
            )
            raise pybreaker.CircuitBreakerError("主模型熔断器已开启")
        else:
            decorated_call = retry_decorator(_breaker.call)
            result = decorated_call(call_fn)
            logger.info("llm_call_success", model=model_name)
            return {"success": True, "data": result, "model_used": model_name}

    except pybreaker.CircuitBreakerError as e:
        last_error = e
        logger.warning("circuit_breaker_rejected", model=model_name)
    except Exception as e:
        last_error = e
        logger.error("llm_primary_failed", model=model_name, error=str(e)[:200])

    # ── 步骤 2: Fallback（必须是用 fallback 模型重建的请求）──
    if fallback_call_fn is None:
        logger.warning(
            "llm_fallback_skipped",
            reason="no_fallback_call_fn",
            model=model_name,
            detail="调用方未提供用 fallback 模型重建的请求，不做降级以免重复打同一故障端点",
        )
        raise LLMCallFailedError(
            f"LLM 调用失败（未配置 fallback 请求构造器）: "
            f"{str(last_error)[:500] if last_error else '未知错误'}"
        ) from last_error

    if not fallback_api_key:
        logger.warning("llm_fallback_skipped", reason="no_fallback_api_key", model=model_name)
        raise LLMCallFailedError(
            f"LLM 调用失败（fallback 未配置 API Key）: "
            f"{str(last_error)[:500] if last_error else '未知错误'}"
        ) from last_error

    logger.warning("llm_fallback_attempt", fallback_model=fallback_model)

    try:
        if _breaker_fallback.current_state == "open":
            logger.warning("circuit_breaker_open", model=fallback_model, breaker="fallback")
            raise pybreaker.CircuitBreakerError("Fallback 熔断器已开启")

        decorated_fallback = retry_decorator(_breaker_fallback.call)
        result = decorated_fallback(fallback_call_fn)
        logger.info("llm_fallback_success", model=fallback_model)
        # 只有 fallback 请求真的成功返回，才允许把 fallback 模型名上报给前端
        return {"success": True, "data": result, "model_used": fallback_model}

    except Exception as e:
        logger.critical("llm_all_failed", primary=model_name, fallback=fallback_model, error=str(e)[:200])
        raise LLMCallFailedError(
            f"主模型 {model_name} 和 fallback {fallback_model} 均调用失败: {str(e)[:200]}"
        ) from e


class LLMCallFailedError(Exception):
    """LLM 调用完全失败（主模型 + fallback 均不可用）。"""
    pass
