"""安全响应头中间件。

以**纯 ASGI** 实现而非 BaseHTTPMiddleware：后者会在响应体外套一层缓冲迭代器，
对 SSE 长连接（/knowledge/ask/stream、/agents/loop/{id}/events）有额外风险。
这里只在 `http.response.start` 消息上补齐响应头，完全不触碰 body 流。
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import is_production

# 与 CORS 预检无关；这些头由服务端统一注入
_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # API 服务不渲染第三方内容；Swagger UI 需要 inline script/style，故用较宽松的 CSP
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                               "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
}

_HSTS = {"Strict-Transport-Security": "max-age=31536000; includeSubDomains"}


class SecurityHeadersMiddleware:
    """给所有 HTTP 响应注入安全头（不覆盖已存在的同名头）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(_BASE_HEADERS)
        if is_production():
            # 仅在生产返回 HSTS：本地 http 开发环境返回 HSTS 会让浏览器把
            # localhost 钉死为 https，反而制造"打不开"的告警。
            headers.update(_HSTS)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = MutableHeaders(scope=message)
                for key, value in headers.items():
                    if key not in raw:
                        raw[key] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)
