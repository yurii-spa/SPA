"""Per-IP rate limiting for the public :8765 FastAPI app (WS2 — Round-2 security).

The public API was previously reachable with ZERO rate limit on every endpoint,
including the LLM-backed ``POST /api/chat`` (an open budget-burn / DoS vector).
This module adds a deterministic, stdlib-only, fail-CLOSED-friendly per-IP
TokenBucket limiter wired as ASGI/Starlette middleware.

Design
======
* Reuses the proven ``TokenBucket`` / ``RateLimiterStore`` algorithm from
  ``spa_core/family_fund/api/rate_limiter.py`` (ported here so the public app does
  NOT import the Family-Fund cabinet package). Pure stdlib (threading + time).
* Per-client-IP bucket. A flood from one IP → ``429 Too Many Requests`` with a
  ``Retry-After`` header; other IPs are unaffected.
* Two tiers:
    - a generous DEFAULT bucket for all routes (cheap GET proof/data/live
      endpoints + the dashboard's ~15s polling must never trip it), and
    - a STRICT bucket for the expensive LLM / write POSTs
      (``/api/chat``, ``/api/agent/thought``) — the real budget-burn surface.
* GET proof/data/live endpoints stay fully functional: the default budget is far
  above the dashboard's polling rate.

All limits are env-tunable (owner knobs) but ship with safe defaults.

LLM FORBIDDEN — this is a deterministic security-domain module; it never imports
an LLM SDK and makes no model calls.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("spa.api.rate_limit")

_FALSEY = {"0", "false", "off", "no"}


# ─── TokenBucket (ported from family_fund/api/rate_limiter.py) ─────────────────


@dataclass
class TokenBucket:
    """capacity — burst; refill_rate tokens per refill_interval seconds."""

    capacity: int
    refill_rate: int
    refill_interval: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed >= self.refill_interval:
            cycles = int(elapsed // self.refill_interval)
            self._tokens = min(
                float(self.capacity), self._tokens + cycles * self.refill_rate
            )
            self._last_refill += cycles * self.refill_interval

    def allow(self, cost: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    @property
    def remaining(self) -> int:
        with self._lock:
            self._refill()
            return int(self._tokens)

    @property
    def reset_after(self) -> float:
        """Seconds until the next refill cycle."""
        with self._lock:
            return max(
                0.0, self._last_refill + self.refill_interval - time.monotonic()
            )


class RateLimiterStore:
    """Holds per-key (per-IP) buckets that all share the same parameters."""

    def __init__(
        self, capacity: int, refill_rate: int, refill_interval: float = 1.0
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self._buckets: dict[str, TokenBucket] = {}
        self._store_lock = threading.Lock()

    def get_bucket(self, key: str) -> TokenBucket:
        with self._store_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    capacity=self.capacity,
                    refill_rate=self.refill_rate,
                    refill_interval=self.refill_interval,
                )
                self._buckets[key] = bucket
            return bucket

    def allow(self, key: str, cost: int = 1) -> bool:
        return self.get_bucket(key).allow(cost)

    def reset_after(self, key: str) -> float:
        return self.get_bucket(key).reset_after

    def cleanup(self) -> None:
        """Drop buckets at full capacity (idle clients) to bound memory."""
        with self._store_lock:
            full = [
                k for k, b in self._buckets.items() if b.remaining >= self.capacity
            ]
            for k in full:
                del self._buckets[k]

    def reset(self) -> None:
        """Full reset (tests)."""
        with self._store_lock:
            self._buckets.clear()


# ─── Tunable limits (owner knobs, safe defaults) ──────────────────────────────


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return val if val > 0 else default
    except ValueError:
        return default


# Default bucket — covers GET proof/data/live + dashboard polling. The dashboard
# polls ~every 15s (≈4 req/min); 120/min burst leaves enormous headroom.
DEFAULT_CAPACITY = _int_env("SPA_RATE_LIMIT_DEFAULT_BURST", 120)
DEFAULT_REFILL = _int_env("SPA_RATE_LIMIT_DEFAULT_PER_MIN", 120)

# Strict bucket — expensive LLM / write POSTs (budget-burn surface).
WRITE_CAPACITY = _int_env("SPA_RATE_LIMIT_WRITE_BURST", 10)
WRITE_REFILL = _int_env("SPA_RATE_LIMIT_WRITE_PER_MIN", 20)

# Paths that get the STRICT bucket (LLM / write / content-injection surface).
_STRICT_PATHS: tuple[str, ...] = ("/api/chat", "/api/agent/thought")


# ─── Middleware ───────────────────────────────────────────────────────────────


def _trust_forwarded() -> bool:
    """True iff we sit behind a trusted reverse proxy (Cloudflare tunnel).

    Default ON: production fronts this app with cloudflared, so the trustworthy
    client identity is ``CF-Connecting-IP`` / the first ``X-Forwarded-For`` hop.
    Set ``SPA_TRUST_PROXY=0`` for a directly-exposed deployment.
    """
    raw = os.environ.get("SPA_TRUST_PROXY", "").strip().lower()
    return raw not in _FALSEY


def _client_ip(request: Request) -> str:
    """Per-client rate-limit key — SPOOF-RESISTANT.

    RESIDUAL-GAP FIX (red-team): naively trusting a client-supplied
    ``X-Forwarded-For`` let an attacker rotate the header to mint a fresh bucket
    per request and bypass the limiter entirely. We only honor a forwarding
    header when ``SPA_TRUST_PROXY`` is on (Cloudflare front), and then prefer
    ``CF-Connecting-IP`` (set by Cloudflare, NOT the client) over the first XFF
    hop. When not behind a trusted proxy, the client-supplied header is ignored
    and the socket peer is used. Deterministic, never raises.
    """
    if _trust_forwarded():
        # CF-Connecting-IP is stamped by Cloudflare and cannot be spoofed by the
        # origin client (Cloudflare overwrites any client-supplied value).
        cf = request.headers.get("cf-connecting-ip")
        if cf and cf.strip():
            return cf.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    client = request.client
    return client.host if client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token-bucket rate limiting. A flood → 429 + Retry-After.

    Two stores: a generous default for read/proof endpoints (so the public
    "check us" surface + dashboard polling never trip), and a strict store for
    the LLM/write POSTs. WebSocket upgrades bypass this HTTP middleware and are
    auth-gated at the handler instead.
    """

    def __init__(
        self,
        app,
        *,
        default_store: RateLimiterStore | None = None,
        write_store: RateLimiterStore | None = None,
    ) -> None:
        super().__init__(app)
        self._default = default_store or RateLimiterStore(
            capacity=DEFAULT_CAPACITY,
            refill_rate=DEFAULT_REFILL,
            refill_interval=60.0,
        )
        self._write = write_store or RateLimiterStore(
            capacity=WRITE_CAPACITY,
            refill_rate=WRITE_REFILL,
            refill_interval=60.0,
        )

    def _store_for(self, path: str):
        if any(path.startswith(p) for p in _STRICT_PATHS):
            return self._write
        return self._default

    async def dispatch(self, request: Request, call_next):
        # Kill-switch for test suites / dev: SPA_RATE_LIMIT_ENABLED=0 disables
        # throttling entirely (default ON). Read per-request so a test conftest
        # can flip it without rebuilding the app singleton. Production leaves it
        # ON, so the protection is live by default.
        if os.environ.get("SPA_RATE_LIMIT_ENABLED", "").strip().lower() in _FALSEY:
            return await call_next(request)

        # Never throttle CORS preflight — it carries no auth and must succeed so
        # the browser can learn the policy (the policy itself blocks rogue origins).
        if request.method == "OPTIONS":
            return await call_next(request)

        ip = _client_ip(request)
        store = self._store_for(request.url.path)
        if not store.allow(ip):
            retry = int(store.reset_after(ip)) + 1
            log.warning(
                "rate limit: 429 for %s on %s", ip, request.url.path
            )
            return JSONResponse(
                {"error": "rate_limit_exceeded",
                 "detail": "too many requests — slow down"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
