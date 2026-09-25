"""全局限流器（唯一实例）。

历史缺陷：`main.py` 与 `api/auth.py` 各自 `Limiter(...)` 建了一个实例，
导致 `X-RateLimit-*` 响应头注入失败、内存计数器被复制两份、
且"给某个实例调参"并不影响真正生效的那个。

实现说明：slowapi 的 `@limiter.limit(...)` 走 `in_middleware=False` 分支，
由装饰器自身绑定的 Limiter 判定，**不依赖** SlowAPIMiddleware，也不要求与
`app.state.limiter` 同实例——所以限流一直是生效的。但为了头注入与计数的一致性，
仍然应统一为一个实例。
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _client_key(request: Request) -> str:
    """限流分桶键。

    默认按客户端 IP。部署在反向代理（Nginx / 网关）之后时，
    `get_remote_address` 拿到的是代理地址，会让限流退化成"全局限额误伤所有用户"。
    此时显式设置 `TRUST_PROXY_HEADERS=1`，改用 `X-Forwarded-For` 的第一段。

    之所以要显式开关：XFF 是客户端可伪造的头，无条件信任等于把限流交给攻击者。
    """
    if os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes"):
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_key)
