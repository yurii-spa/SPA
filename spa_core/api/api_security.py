"""Auth wiring for the public :8765 FastAPI app (WS2 — Round-2 security).

The repo already shipped a complete HMAC auth core in ``spa_core/api/auth.py``
(``APIAuth``: key from ``SPA_API_KEY`` env → macOS Keychain, timestamped token
gen/verify, bearer extraction). It sat UNWIRED — no endpoint enforced it. This
module turns it into a FastAPI dependency that gates the MUTATING / LLM endpoints
(``POST /api/chat``, ``POST /api/agent/thought``, ``WS /ws/agents``) while leaving
every GET proof/data/live endpoint fully public (the "don't trust us, check us"
surface + the live dashboard depend on those staying open).

Flag (owner-tunable)
====================
``SPA_API_REQUIRE_AUTH`` — controls enforcement on writes/LLM:
  * unset / "1" / "true" / "on"  → ENFORCED (recommended default-ON for writes)
  * "0" / "false" / "off"        → bypass (dev only; logged once at WARNING)

Accepted credentials (either):
  * ``Authorization: Bearer <token>``  (HMAC token from APIAuth.generate_token)
  * ``X-API-Key: <raw key>``           (the configured SPA_API_KEY itself)

Fail-CLOSED: when enforcement is ON and no ``SPA_API_KEY`` is configured, the
gated endpoints return 401 (they cannot be called) rather than silently opening.
A missing/invalid credential → 401. The secret is read from Keychain/env at
runtime; it is NEVER hardcoded.

LLM FORBIDDEN — security domain; no model calls here.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import HTTPException, Request, WebSocket, status

from spa_core.api.auth import get_auth

log = logging.getLogger("spa.api.security")

_FALSEY = {"0", "false", "off", "no"}


def require_auth_enabled() -> bool:
    """True iff write/LLM endpoints must enforce auth (default ON)."""
    raw = os.environ.get("SPA_API_REQUIRE_AUTH", "").strip().lower()
    if raw in _FALSEY:
        return False
    return True  # default-ON, and any non-falsey value (incl. unset) → ON


def _credential_ok(authorization: str | None, x_api_key: str | None) -> bool:
    """Return True iff a valid bearer token OR the raw API key is presented.

    Both checks fail-closed when no key is configured (``APIAuth`` has no key →
    ``verify_*`` returns False / key compare is impossible).
    """
    auth = get_auth()
    if not auth.has_key():
        # Fail-CLOSED: enforcement requested but no secret → nobody gets in.
        return False
    # 1) HMAC bearer token
    if auth.verify_bearer(authorization):
        return True
    # 2) Raw API key via X-API-Key (constant-time compare).
    if x_api_key:
        key = auth._key  # bytes; loaded from env/Keychain, never hardcoded
        if key is not None and hmac.compare_digest(
            x_api_key.strip().encode("utf-8"), key
        ):
            return True
    return False


_warned_bypass = False


def _log_bypass_once() -> None:
    global _warned_bypass
    if not _warned_bypass:
        log.warning(
            "SPA_API_REQUIRE_AUTH is OFF — write/LLM endpoints are UNPROTECTED "
            "(dev mode). Set SPA_API_REQUIRE_AUTH=1 in production."
        )
        _warned_bypass = True


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: gate a mutating/LLM endpoint behind the API key.

    Raises 401 when enforcement is ON and the credential is missing/invalid (or
    no key is configured — fail-closed). A no-op when the flag is OFF.
    """
    if not require_auth_enabled():
        _log_bypass_once()
        return
    authorization = request.headers.get("authorization")
    x_api_key = request.headers.get("x-api-key")
    if not _credential_ok(authorization, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized",
                    "detail": "valid API key required for this endpoint"},
            headers={"WWW-Authenticate": "Bearer"},
        )


async def ws_authorized(websocket: WebSocket) -> bool:
    """Check WS credentials. Returns True if allowed; caller must close on False.

    Accepts the same credentials as HTTP, read from the upgrade-request headers
    or a ``?token=``/``?api_key=`` query param (browsers cannot set WS headers).
    No-op (always True) when enforcement is OFF.
    """
    if not require_auth_enabled():
        _log_bypass_once()
        return True
    authorization = websocket.headers.get("authorization")
    x_api_key = websocket.headers.get("x-api-key")
    if not authorization:
        tok = websocket.query_params.get("token")
        if tok:
            authorization = f"Bearer {tok}"
    if not x_api_key:
        x_api_key = websocket.query_params.get("api_key")
    return _credential_ok(authorization, x_api_key)
