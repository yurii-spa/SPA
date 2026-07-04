"""
spa_core/academy/api/middleware.py

Two pure-ASGI middlewares for the Academy sub-application:

  * :class:`SeedPhraseGuard` — a safety/education tripwire. It inspects the JSON
    body of mutating requests and rejects (HTTP 400) any payload that appears to
    carry a raw private key (``0x`` + 64 hex) or a BIP39 seed phrase (>=12 words,
    >=80% of them in the BIP39 English wordlist). The rejected content is NEVER
    logged — only an ``action=seed_phrase_rejected`` audit row with no payload.
    A single top-level ``tx_hash`` field holding a valid 64-hex value is exempt
    (legitimate on-chain proof), but a nested or mis-keyed 64-hex is not.

  * :class:`AcademyRateLimit` — deterministic per-scope token-bucket throttling,
    reusing the proven ``RateLimiterStore`` from ``spa_core/api/rate_limit.py``.
    Login is limited per-IP AND per-email; register per-IP; verify/quiz per
    user-id; everything else a generous per-IP default. A trip → 429 +
    ``Retry-After`` and an ``action=lockout`` audit row.

Why pure ASGI (not BaseHTTPMiddleware): both middlewares must read the request
body and forward it downstream. BaseHTTPMiddleware's stream handling makes that
fragile; buffering the ASGI ``receive`` messages and replaying them is explicit
and version-robust.

LLM FORBIDDEN — deterministic security/safety-domain module, no model calls.
Academy stage 3.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events, sessions
from spa_core.api.rate_limit import RateLimiterStore, _trust_forwarded

_FALSEY = {"0", "false", "off", "no"}

# ── BIP39 wordlist (official English 2048) ──────────────────────────────────
_WORDLIST_PATH = Path(__file__).resolve().parent / "bip39_english.txt"


def _load_bip39() -> frozenset:
    try:
        raw = _WORDLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(w.strip().lower() for w in raw.split() if w.strip())


BIP39_WORDLIST = _load_bip39()

# 0x + exactly 64 hex nibbles == a 32-byte private key OR a tx hash.
_HEX64_ANYWHERE = re.compile(r"0x[0-9a-fA-F]{64}")
_HEX64_EXACT = re.compile(r"^0x[0-9a-fA-F]{64}$")
# 0x + exactly 130 hex nibbles == a 65-byte ECDSA (EIP-191/EIP-4361) signature.
# A signature is public cryptographic material, NOT a secret — but it embeds a
# 64-hex run, so an exact-length top-level `signature` field is exempt from the
# private-key tripwire (a raw 32-byte key never matches this 130-hex shape).
_SIG_HEX_EXACT = re.compile(r"^0x[0-9a-fA-F]{130}$")

# Body size we are willing to buffer+scan (auth payloads are tiny). Larger
# bodies are forwarded unscanned rather than buffered into memory.
_MAX_SCAN_BYTES = 256 * 1024


# ── Seed-phrase / private-key detection ─────────────────────────────────────


def _looks_like_seed_phrase(text: str) -> bool:
    """True if *text* looks like a BIP39 mnemonic (>=12 words, >=80% in list)."""
    words = text.split()
    if len(words) < 12 or not BIP39_WORDLIST:
        return False
    hits = sum(1 for w in words if w.lower() in BIP39_WORDLIST)
    return hits >= 0.8 * len(words)


def _is_secret_string(value: str) -> bool:
    """True if *value* embeds a private key or reads as a seed phrase."""
    if _HEX64_ANYWHERE.search(value):
        return True
    return _looks_like_seed_phrase(value)


def _scan_nested(value) -> bool:
    """Recursively scan a non-top-level value (no tx_hash exemption here)."""
    if isinstance(value, str):
        return _is_secret_string(value)
    if isinstance(value, dict):
        return any(_scan_nested(v) for v in value.values())
    if isinstance(value, list):
        return any(_scan_nested(v) for v in value)
    return False


def scan_payload(obj) -> bool:
    """Return True if *obj* (parsed JSON) carries a rejected secret.

    Only a single **top-level** ``tx_hash`` field with a valid 64-hex value, or
    a top-level ``signature`` field with a valid 130-hex (65-byte) value, is
    exempt; a nested tx_hash/signature, or a 64-hex under any other key, is
    rejected.
    """
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                if key == "tx_hash" and _HEX64_EXACT.match(val):
                    continue  # legitimate on-chain proof — exempt
                if key == "signature" and _SIG_HEX_EXACT.match(val):
                    continue  # legitimate SIWE signature — exempt
                if _is_secret_string(val):
                    return True
            elif _scan_nested(val):
                return True
        return False
    return _scan_nested(obj)


# ── ASGI body buffering helpers ─────────────────────────────────────────────


async def _buffer_body(receive):
    """Drain the ASGI receive channel, returning (body_bytes, disconnected)."""
    body = b""
    while True:
        message = await receive()
        mtype = message.get("type")
        if mtype == "http.request":
            body += message.get("body", b"")
            if not message.get("more_body", False):
                return body, False
        elif mtype == "http.disconnect":
            return body, True


def _replay_receive(body: bytes):
    """Return a receive() that yields *body* once, then http.disconnect."""
    state = {"sent": False}

    async def receive():
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _header(scope, name: bytes) -> Optional[str]:
    for key, val in scope.get("headers", []):
        if key == name:
            try:
                return val.decode("latin-1")
            except Exception:  # noqa: BLE001
                return None
    return None


def _client_ip(scope) -> str:
    """Spoof-resistant client key (CF-Connecting-IP → XFF → socket peer)."""
    if _trust_forwarded():
        cf = _header(scope, b"cf-connecting-ip")
        if cf and cf.strip():
            return cf.strip()
        xff = _header(scope, b"x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def _db_from_scope(scope) -> Optional[AcademyDB]:
    """Best-effort AcademyDB from the mounted sub-app's state (or None)."""
    app = scope.get("app")
    db_path = getattr(getattr(app, "state", None), "db_path", None) if app else None
    if not db_path:
        db_path = os.environ.get("SPA_ACADEMY_DB")
    if not db_path:
        return None
    try:
        return AcademyDB(db_path=db_path)
    except Exception:  # noqa: BLE001
        return None


def _log_safe(db: Optional[AcademyDB], action: str, **kw) -> None:
    if db is None:
        return
    try:
        events.log_event(db, action, **kw)
    except Exception:  # noqa: BLE001
        pass


# ── SeedPhraseGuard ─────────────────────────────────────────────────────────


class SeedPhraseGuard:
    """Reject mutating JSON requests that carry a private key / seed phrase."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in ("POST", "PUT"):
            return await self.app(scope, receive, send)

        ctype = (_header(scope, b"content-type") or "").lower()
        if "application/json" not in ctype:
            return await self.app(scope, receive, send)

        body, disconnected = await _buffer_body(receive)
        replay = _replay_receive(body)
        if disconnected:
            return await self.app(scope, replay, send)

        # Never fail on a non-JSON / oversized body — just forward it.
        if len(body) > _MAX_SCAN_BYTES or not body:
            return await self.app(scope, replay, send)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return await self.app(scope, replay, send)

        if scan_payload(parsed):
            db = _db_from_scope(scope)
            # NEVER log the offending content — only the bare action.
            _log_safe(db, "seed_phrase_rejected", ip=_client_ip(scope))
            response = JSONResponse(
                {
                    "error": "SEED_PHRASE_REJECTED",
                    "message": (
                        "Never paste a private key or seed phrase into any web "
                        "form — not this one, not any other. A seed phrase is "
                        "the master key to your funds; anyone who sees it can "
                        "drain your wallet. This request was blocked and its "
                        "contents were NOT stored. Sign in your own wallet "
                        "instead; the Academy never needs your secret."
                    ),
                },
                status_code=400,
            )
            return await response(scope, replay, send)

        return await self.app(scope, replay, send)


# ── AcademyRateLimit ────────────────────────────────────────────────────────


def _make_store(capacity: int, per_window: int, window_s: float) -> RateLimiterStore:
    return RateLimiterStore(
        capacity=capacity, refill_rate=per_window, refill_interval=window_s
    )


class AcademyRateLimit:
    """Per-scope token-bucket rate limiting for the Academy sub-app.

    Buckets (capacity == window budget, refilled once per window):
      - /auth/login    : 5 / 900s  per IP  AND  per email
      - /auth/register : 5 / 900s  per IP
      - /verify/*      : 10 / 3600s per user_id
      - /quiz/*        : 20 / 3600s per user_id
      - everything else: 60 / 60s  per IP
    """

    def __init__(self, app) -> None:
        self.app = app
        self._login = _make_store(5, 5, 900.0)
        self._register = _make_store(5, 5, 900.0)
        self._verify = _make_store(10, 10, 3600.0)
        self._quiz = _make_store(20, 20, 3600.0)
        self._default = _make_store(60, 60, 60.0)

    # NOTE: paths seen here are RELATIVE to the mount point ("/auth/login",
    # not "/academy/auth/login"), because Starlette rewrites the path when it
    # routes into a mounted sub-app.
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        if os.environ.get("SPA_ACADEMY_RATE_LIMIT", "").strip().lower() in _FALSEY:
            return await self.app(scope, receive, send)
        method = scope.get("method")
        if method == "OPTIONS":  # never throttle CORS preflight
            return await self.app(scope, receive, send)

        path = scope.get("path", "") or ""
        ip = _client_ip(scope)

        # Login needs the email from the body → buffer + replay.
        if path == "/auth/login" or path.endswith("/auth/login"):
            body, disconnected = await _buffer_body(receive)
            receive = _replay_receive(body)
            email = _extract_email(body)
            keys = [(self._login, f"login:ip:{ip}")]
            if email:
                keys.append((self._login, f"login:email:{email}"))
            denied = self._first_denied(keys)
            if denied is not None:
                return await self._reject(scope, receive, send, denied)
            return await self.app(scope, receive, send)

        # Non-login routes: no body needed.
        if path == "/auth/register" or path.endswith("/auth/register"):
            store, key = self._register, f"register:ip:{ip}"
        elif "/verify/" in path or path.endswith("/verify") or path.startswith("/verify"):
            uid = _user_id_from_scope(scope)
            store, key = self._verify, f"verify:uid:{uid if uid is not None else ip}"
        elif "/quiz/" in path or path.endswith("/quiz") or path.startswith("/quiz"):
            uid = _user_id_from_scope(scope)
            store, key = self._quiz, f"quiz:uid:{uid if uid is not None else ip}"
        else:
            store, key = self._default, f"default:ip:{ip}"

        if not store.allow(key):
            return await self._reject(scope, receive, send, (store, key))
        return await self.app(scope, receive, send)

    @staticmethod
    def _first_denied(keys):
        """Consume a token from each (store, key); return the first denial."""
        for store, key in keys:
            if not store.allow(key):
                return (store, key)
        return None

    async def _reject(self, scope, receive, send, store_key) -> None:
        store, key = store_key
        retry = int(store.reset_after(key)) + 1
        _log_safe(_db_from_scope(scope), "lockout", ip=_client_ip(scope))
        response = JSONResponse(
            {
                "error": "rate_limit_exceeded",
                "detail": "too many requests — slow down and try again later",
            },
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
        await response(scope, receive, send)


def _extract_email(body: bytes) -> Optional[str]:
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        email = data.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


def _user_id_from_scope(scope) -> Optional[int]:
    """Resolve the acting user_id from the session cookie (best effort)."""
    db = _db_from_scope(scope)
    if db is None:
        return None
    try:
        request = Request(scope)
        raw = request.cookies.get("academy_session")
        if not raw:
            return None
        session = sessions.get_session(db, raw)
        return int(session["user_id"]) if session else None
    except Exception:  # noqa: BLE001
        return None
