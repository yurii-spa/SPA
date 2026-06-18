"""Middleware: rate limiting (TokenBucket) + request-id.

Лимиты per-IP:
  - /auth/*  → 5 req/min (защита от brute-force)
  - остальное → 60 req/min

За Cloudflare Tunnel реальный IP в заголовке CF-Connecting-IP.
"""
from __future__ import annotations

import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from .rate_limiter import RateLimiterStore

# 5 req/min: capacity 5, +5 каждые 60 c
_auth_limiter = RateLimiterStore(capacity=5, refill_rate=5, refill_interval=60.0)
# 60 req/min: capacity 60, +60 каждые 60 c
_api_limiter = RateLimiterStore(capacity=60, refill_rate=60, refill_interval=60.0)


def reset_limiters() -> None:
    """Сбрасывает оба лимитера (для тестов)."""
    _auth_limiter.reset()
    _api_limiter.reset()


def _client_ip(request: Request) -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.split(",")[0].strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _limiter_for(path: str) -> RateLimiterStore:
    return _auth_limiter if path.startswith("/auth") else _api_limiter


async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    limiter = _limiter_for(path)
    key = _client_ip(request)
    bucket = limiter.get_bucket(key)

    if not bucket.allow():
        retry = int(bucket.reset_after) + 1
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests",
                },
                "retry_after": retry,
                "request_id": getattr(request.state, "request_id", None),
            },
            headers={
                "Retry-After": str(retry),
                "X-RateLimit-Limit": str(bucket.capacity),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry)),
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(bucket.capacity)
    response.headers["X-RateLimit-Remaining"] = str(bucket.remaining)
    return response


async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
