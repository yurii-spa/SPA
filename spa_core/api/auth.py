"""
API Authentication module — MP-1529 (v11.45).

Current policy:
  - All /api/v1/* GET endpoints are PUBLIC (read-only, no auth required).
  - /admin/* endpoints require a valid HMAC-signed token.
  - Future: /api/v1/family_fund/* will require JWT (Family Fund cabinet).

Token format:  <unix_timestamp>.<hex_hmac_sha256_signature>
Key source:    SPA_API_KEY env var  →  macOS Keychain "SPA_API_KEY"

Rate limiting:
  - Stub only in v11.45; enforcement will be added via middleware in v11.50+.
  - In-memory sliding-window counters (per IP) for future middleware wiring.

IMPORTANT: LLM FORBIDDEN in auth/risk/execution domains (prompt injection risk).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import defaultdict, deque
from typing import Optional

log = logging.getLogger("spa.api.auth")

# ── constants ─────────────────────────────────────────────────────────────────

# Paths that require a valid token
PROTECTED_PREFIXES: tuple[str, ...] = ("/admin/", "/api/v1/admin/")

# Read-only public paths — never require auth
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/v1/status",
    "/api/v1/golive",
    "/api/v1/adapters",
    "/api/v1/evidence",
    "/api/portfolio",
    "/api/positions",
    "/api/pools",
    "/api/risk",
    "/api/trades",
    "/api/backtest",
    "/api/optimization",
    "/api/status",
    "/api/events",
    "/api/apy",
    "/docs",
    "/openapi.json",
    "/redoc",
)

# Token timestamp tolerance: ±300 seconds
TOKEN_WINDOW_SECONDS = 300

# Rate limit stub: max requests per window per IP (not enforced yet, v11.50+)
_RATE_LIMIT_MAX = 100
_RATE_LIMIT_WINDOW = 60  # seconds


# ── main auth class ───────────────────────────────────────────────────────────

class APIAuth:
    """
    Simple HMAC-based API authentication for protected endpoints.

    Key loading order:
      1. SPA_API_KEY environment variable
      2. macOS Keychain service "SPA_API_KEY" (via spa_core.utils.keychain)

    If no key is found, protected endpoints return 401.
    Public read-only endpoints are never blocked.
    """

    def __init__(self) -> None:
        self._key: Optional[bytes] = self._load_key()
        self._rate_counters: dict[str, deque] = defaultdict(lambda: deque())

    # ── key management ────────────────────────────────────────────────────────

    def _load_key(self) -> Optional[bytes]:
        """Load API key from environment or Keychain. Returns None if not found."""
        env_key = os.environ.get("SPA_API_KEY", "").strip()
        if env_key:
            log.debug("APIAuth: key loaded from SPA_API_KEY env var")
            return env_key.encode("utf-8")

        try:
            from spa_core.utils.keychain import get_secret
            secret = get_secret("SPA_API_KEY")
            if secret:
                log.debug("APIAuth: key loaded from macOS Keychain")
                return secret.encode("utf-8") if isinstance(secret, str) else secret
        except Exception as e:
            log.debug(f"APIAuth: Keychain unavailable ({e})")

        log.warning("APIAuth: no SPA_API_KEY found — protected endpoints will return 401")
        return None

    def has_key(self) -> bool:
        """Return True if an API key is configured."""
        return self._key is not None

    # ── path classification ───────────────────────────────────────────────────

    def is_protected(self, path: str) -> bool:
        """Return True if the path requires authentication."""
        return any(path.startswith(p) for p in PROTECTED_PREFIXES)

    def is_public(self, path: str) -> bool:
        """Return True if the path is explicitly public (no auth ever needed)."""
        return any(path.startswith(p) for p in PUBLIC_PREFIXES)

    # ── token generation & verification ──────────────────────────────────────

    def generate_token(self, timestamp: Optional[int] = None) -> str:
        """
        Generate a timestamped HMAC-SHA256 token.

        Format: "<unix_timestamp>.<hex_signature>"

        Raises ValueError if no key is configured.
        """
        if not self._key:
            raise ValueError("No API key configured — cannot generate token")
        ts = str(timestamp if timestamp is not None else int(time.time()))
        sig = hmac.new(self._key, ts.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{ts}.{sig}"

    def verify_token(self, token: str) -> bool:
        """
        Verify an HMAC token.

        Returns True iff:
          - Key is configured
          - Token format is "<timestamp>.<hex_sig>"
          - Signature matches
          - Timestamp is within TOKEN_WINDOW_SECONDS of now
        """
        if not self._key:
            return False
        if not token or not isinstance(token, str):
            return False

        parts = token.split(".", 1)
        if len(parts) != 2:
            return False

        ts_str, sig = parts

        # Check timestamp first (cheap)
        try:
            ts = int(ts_str)
        except ValueError:
            return False

        now = int(time.time())
        if abs(now - ts) > TOKEN_WINDOW_SECONDS:
            log.debug(f"APIAuth: token timestamp drift {now - ts}s > {TOKEN_WINDOW_SECONDS}s")
            return False

        # Constant-time signature comparison
        expected = hmac.new(self._key, ts_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def verify_bearer(self, authorization_header: Optional[str]) -> bool:
        """
        Extract and verify a 'Bearer <token>' Authorization header.

        Returns True if token is valid.
        """
        if not authorization_header:
            return False
        parts = authorization_header.strip().split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return self.verify_token(parts[1])

    # ── rate limiting stub ────────────────────────────────────────────────────

    def check_rate_limit(self, client_ip: str) -> bool:
        """
        Sliding-window rate limit check (stub — not enforced yet).

        Returns True if the request is within the allowed rate.
        Will be wired into FastAPI middleware in v11.50+.
        """
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW
        dq = self._rate_counters[client_ip]

        # Evict timestamps outside the window
        while dq and dq[0] < window_start:
            dq.popleft()

        if len(dq) >= _RATE_LIMIT_MAX:
            log.warning(f"APIAuth: rate limit would trigger for {client_ip} ({len(dq)} req/{_RATE_LIMIT_WINDOW}s)")
            return False

        dq.append(now)
        return True

    def reset_rate_counter(self, client_ip: str) -> None:
        """Reset rate counter for an IP (used in tests)."""
        if client_ip in self._rate_counters:
            del self._rate_counters[client_ip]


# ── module-level singleton ────────────────────────────────────────────────────
# Instantiated lazily to avoid Keychain access at import time.
_auth_instance: Optional[APIAuth] = None


def get_auth() -> APIAuth:
    """Return (or create) the module-level APIAuth singleton."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = APIAuth()
    return _auth_instance
