"""In-memory sliding-window rate limiter middleware.

Keyed by API key when present, else client IP. Suitable for a single
Railway instance; swap the store for Redis (same interface) before scaling
to multiple instances.
"""

import time
import threading
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

EXEMPT_PATHS = {"/", "/health", "/health/db", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit_per_minute: int = None):
        super().__init__(app)
        self.limit = limit_per_minute if limit_per_minute is not None else settings.RATE_LIMIT_PER_MINUTE
        self._hits = {}  # key -> deque[timestamps]
        self._lock = threading.Lock()

    def _key(self, request: Request) -> str:
        api_key = request.headers.get("x-api-key")
        if api_key:
            return f"key:{api_key[:16]}"
        fwd = request.headers.get("x-forwarded-for")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
        return f"ip:{ip}"

    async def dispatch(self, request: Request, call_next):
        if self.limit <= 0 or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        now = time.time()
        key = self._key(request)
        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= self.limit:
                retry_after = max(1, int(60 - (now - window[0])))
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "RATE_LIMITED",
                                       "message": "Too many requests. Slow down.",
                                       "details": {"limit_per_minute": self.limit}}},
                    headers={"Retry-After": str(retry_after),
                             "X-RateLimit-Limit": str(self.limit),
                             "X-RateLimit-Remaining": "0"},
                )
            window.append(now)
            remaining = self.limit - len(window)
            # Opportunistic cleanup of dead keys to bound memory
            if len(self._hits) > 10000:
                for k in [k for k, dq in self._hits.items() if not dq or dq[-1] <= now - 120][:5000]:
                    self._hits.pop(k, None)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
