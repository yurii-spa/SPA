# LLM_FORBIDDEN
"""DFB Data API (Month-3 Lane-1) — the risk-graded, key-gated DEVELOPER surface.

> "DeBank Cloud sells you the RAW data. DFB sells you the RISK TRUTH + the proof."

This is the *on-identity monetization* surface for DFB: a versioned, documented,
API-key-gated developer API that exposes the SAME per-pool risk overlay the public
``/api/dfb/*`` router serves — but as a clean, stable, programmatic product
(``/api/dfb/v1/*``). Risk-graded data (A/B/C/D + exit-liquidity-by-size + the
deterministic refusal verdict + a reproducible proof hash) is scarcer and more
defensible than raw yield data (DefiLlama gives raw; DFB gives the risk truth).

NO-FORK: this router does NOT re-read or re-derive anything. It calls the existing
``spa_core.api.routers.dfb`` reader helpers (``_read_pools_list`` etc.) so the v1
payload is BYTE-IDENTICAL to the public overlay — there is exactly one source of the
graded universe, and the developer API cannot diverge from it (a red-team test
asserts byte-equality). This is a clean re-presentation, never a second copy.

FLAG-GATE (owner-gated public launch — ``SPA_DFB_DATA_API``, default OFF)
========================================================================
The whole ``/api/dfb/v1/*`` surface only exists when ``SPA_DFB_DATA_API`` is a
truthy value. The router is conditionally mounted by ``server.py``: flag OFF → the
router is NEVER included → every ``/api/dfb/v1/*`` path is a **total 404** (no
endpoint reachable, no surface leak). This is the same owner-gate posture as the
underwriting router. Building the product behind a flag is autonomous; **the public
LAUNCH (issuing keys, billing, SLA, ToS) is OWNER-GATED** — that is owner infra +
a commercial decision, documented in ``docs/DFB_DATA_API.md``.

AUTH — fail-CLOSED, never silently open
=======================================
Every ``/api/dfb/v1/*`` request requires a valid API key (``X-API-Key: <key>`` or
``Authorization: Bearer <hmac-token>``), verified by the SAME ``api_security``
credential core the rest of the app uses (key from ``SPA_API_KEY`` env → macOS
Keychain, NEVER hardcoded). Fail-CLOSED rule:

  * flag ON + key configured + valid credential  → 200 (served, risk-graded)
  * flag ON + key configured + missing/bad/spoofed credential → 401
  * flag ON + NO key configured                  → 401 (never silently open!)
  * flag OFF                                       → 404 (router not mounted)

Unlike ``api_security.require_api_key`` (which becomes a no-op when
``SPA_API_REQUIRE_AUTH`` is OFF — appropriate for the public dashboard's write
endpoints), the Data API ALWAYS enforces the key: a paid product surface is never
opened by a dev-mode flag.

RATE LIMITING — per-key tiers (free / pro)
==========================================
A per-API-KEY (not per-IP) token bucket gates throughput, reusing the proven
``RateLimiterStore`` from ``rate_limit.py``. Two conceptual tiers (free / pro) with
owner-tunable env limits; an unknown key defaults to the free tier. A key that
floods → 429 + Retry-After. (The app-wide per-IP middleware still applies on top.)

POSTURE: read-only, GET-only, deterministic, fail-CLOSED, LLM-FORBIDDEN, no
``execution/`` import, never writes a file. Advisory stamps on every payload.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request, status

from spa_core.api._shared import now, read_state, scrub_nonfinite
from spa_core.api.auth import get_auth

# NO-FORK: reuse the public router's readers + helpers so the v1 surface is
# byte-identical to /api/dfb/* (one source of the graded universe).
from spa_core.api.routers import dfb as _dfb

log = logging.getLogger("spa.api.dfb_data_api")

router = APIRouter(tags=["dfb-data-api"])

_API_VERSION = "v1"
_FLAG_ENV = "SPA_DFB_DATA_API"
_TRUTHY = {"1", "true", "on", "yes"}

# ── Advisory envelope (every payload) ──────────────────────────────────────────
_DISCLAIMER = (
    "DFB Data API — read-only RISK-GRADED analytics. Advisory, NOT financial advice, "
    "NOT a recommendation, NOT realized capital. The risk overlay (A/B/C/D class, "
    "exit-liquidity-by-size, refusal verdict) is deterministic and LLM-free; "
    "exit-liquidity is a CONSERVATIVE lower bound or a visible hole, never a fabricated "
    "fill. Each row carries a reproducible proof_hash — don't trust us, check us."
)


# ══════════════════════════════════════════════════════════════════════════════
# Flag gate
# ══════════════════════════════════════════════════════════════════════════════
def data_api_enabled() -> bool:
    """True iff the owner has flipped ``SPA_DFB_DATA_API`` to a truthy value.

    Default OFF. ``server.py`` reads this at import time and only INCLUDES the
    router when it is True, so flag-OFF means the whole ``/api/dfb/v1/*`` surface
    is a total 404 (no endpoint exists). Read here too so a hot test that mounts
    the router directly still fail-closes."""
    return os.environ.get(_FLAG_ENV, "").strip().lower() in _TRUTHY


# ══════════════════════════════════════════════════════════════════════════════
# Per-key rate limiting (free / pro tiers) — reuse RateLimiterStore
# ══════════════════════════════════════════════════════════════════════════════
def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


# Owner-tunable per-key limits (safe defaults). Free is generous enough for
# evaluation; pro is the paid tier. These are CONCEPTUAL tiers until the
# owner-gated launch wires real key→tier issuance (see docs/DFB_DATA_API.md).
_FREE_PER_MIN = _int_env("SPA_DFB_API_FREE_PER_MIN", 30)
_PRO_PER_MIN = _int_env("SPA_DFB_API_PRO_PER_MIN", 600)

# Which keys map to the PRO tier — a comma-separated allow-list of key *fingerprints*
# (sha256(key)[:16]), NEVER the raw keys (secrets never live in code/env-as-plaintext-list
# is the owner's call at launch). An unknown/unlisted key → FREE tier (fail to the
# cheaper tier, never the more permissive one).
def _pro_fingerprints() -> set[str]:
    raw = os.environ.get("SPA_DFB_API_PRO_KEYS", "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


_RATE_STORE = None  # lazy RateLimiterStore (free tier)
_PRO_RATE_STORE = None


def _rate_store():
    global _RATE_STORE
    if _RATE_STORE is None:
        from spa_core.api.rate_limit import RateLimiterStore
        _RATE_STORE = RateLimiterStore(
            capacity=_FREE_PER_MIN, refill_rate=_FREE_PER_MIN, refill_interval=60.0
        )
    return _RATE_STORE


def _pro_rate_store():
    global _PRO_RATE_STORE
    if _PRO_RATE_STORE is None:
        from spa_core.api.rate_limit import RateLimiterStore
        _PRO_RATE_STORE = RateLimiterStore(
            capacity=_PRO_PER_MIN, refill_rate=_PRO_PER_MIN, refill_interval=60.0
        )
    return _PRO_RATE_STORE


def _reset_rate_stores() -> None:
    """Test hook — clear per-key buckets so a flood test starts fresh."""
    global _RATE_STORE, _PRO_RATE_STORE
    _RATE_STORE = None
    _PRO_RATE_STORE = None


def _key_fingerprint(raw_key: bytes | str) -> str:
    """A non-reversible, log/rate-safe id for a key (NEVER the raw key)."""
    b = raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key
    return hashlib.sha256(b).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════
# Auth — the key gate (fail-CLOSED, ALWAYS enforced when the surface is live)
# ══════════════════════════════════════════════════════════════════════════════
def _present_credential(request: Request) -> str | None:
    """Return the raw X-API-Key or the bearer token presented, else None."""
    x = request.headers.get("x-api-key")
    if x and x.strip():
        return x.strip()
    authz = request.headers.get("authorization")
    if authz and authz.strip().lower().startswith("bearer "):
        return authz.strip()
    return None


def _authorize(request: Request) -> str:
    """Enforce the API key + per-key rate limit. Returns the key fingerprint on success.

    Raises:
      * 404 — flag OFF (defense-in-depth; server.py also won't mount the router).
      * 401 — no key configured (fail-CLOSED, never silently open), OR a missing /
        invalid / spoofed credential.
      * 429 — the per-key rate limit (tiered) is exceeded.
    """
    # Defense-in-depth: even if mounted, refuse when the flag is OFF.
    if not data_api_enabled():
        raise HTTPException(status_code=404, detail={
            "error": "dfb_data_api_disabled",
            "note": f"The DFB Data API is owner-gated ({_FLAG_ENV}) and is OFF. "
                    f"This surface does not exist (fail-CLOSED).",
        })

    auth = get_auth()
    # Fail-CLOSED: a live surface with NO key configured locks EVERYONE out (401),
    # it never silently opens. (A paid product surface is not opened by absence.)
    if not auth.has_key():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "api_key_required",
                    "note": "DFB Data API requires an API key, but none is configured "
                            "on the server (fail-CLOSED — the surface is never silently "
                            "opened). Configure SPA_API_KEY (env → Keychain)."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    cred = _present_credential(request)
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized",
                    "note": "Missing API key. Send X-API-Key: <key> or "
                            "Authorization: Bearer <token>."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify: accept the raw key (X-API-Key, constant-time compare) or an HMAC bearer.
    key = auth._key  # bytes, loaded from env/Keychain, never hardcoded
    matched_key: bytes | None = None
    if cred.lower().startswith("bearer "):
        if auth.verify_bearer(cred):
            matched_key = key
    else:
        if key is not None and hmac.compare_digest(cred.encode("utf-8"), key):
            matched_key = key

    if matched_key is None:
        # A spoofed / rotated / wrong key is rejected here (constant-time, no leak).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key",
                    "note": "The presented API key/token is not valid (fail-CLOSED)."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    fp = _key_fingerprint(matched_key)

    # Per-key tiered rate limit. Unknown key → FREE tier (the cheaper tier).
    is_pro = fp in _pro_fingerprints()
    store = _pro_rate_store() if is_pro else _rate_store()
    if not store.allow(fp):
        retry = int(store.reset_after(fp)) + 1
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded",
                    "tier": "pro" if is_pro else "free",
                    "note": "Per-key rate limit exceeded — slow down or upgrade tier."},
            headers={"Retry-After": str(retry)},
        )
    return fp


def _envelope(payload: dict, key_fp: str) -> dict:
    """Stamp the standard Data-API envelope (version + advisory + key fp) onto a payload."""
    payload.setdefault("api_version", _API_VERSION)
    payload.setdefault("is_advisory", True)
    payload["disclaimer"] = _DISCLAIMER
    payload["key"] = key_fp  # the NON-reversible fingerprint, for the caller's own logs
    payload["served_at"] = now()
    return scrub_nonfinite(payload)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1/pools — the risk-graded universe (byte-identical to /api/dfb/pools)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1/pools")
def v1_pools(request: Request):
    """The full RISK-GRADED pool universe — every followed market with its complete
    overlay row (A/B/C/D class · exit-liquidity-by-size · refusal verdict · row_hash).

    NO-FORK: served byte-identical to the public ``/api/dfb/pools`` (same reader).
    Key-gated + rate-limited. Fail-CLOSED: a missing/corrupt universe → 200 with an
    honest empty list (NEVER fabricated rows)."""
    fp = _authorize(request)
    pools = _dfb._read_pools_list()
    return _envelope({
        "endpoint": "pools",
        "available": bool(pools),
        "n_pools": len(pools),
        "pools": pools,
    }, fp)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1/pool/{pool_id} — one pool's full overlay + proof (404 unknown)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1/pool/{pool_id}")
def v1_pool(pool_id: str, request: Request):
    """ONE pool's full risk overlay — class + exit-liquidity schedule + refusal
    decomposition + proof_hash, served VERBATIM (NO-FORK; same data the public
    detail endpoint serves). Fail-CLOSED: invalid/unknown pool_id → 404 (a guess
    is a lie; absence is honest)."""
    fp = _authorize(request)
    if not _dfb._valid_pool_id(pool_id):
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool", "pool_id": pool_id,
            "note": "fail-CLOSED: invalid pool_id; no pool is fabricated."})
    raw = read_state(f"dfb/pool/{pool_id}.json", None)
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool", "pool_id": pool_id,
            "note": "fail-CLOSED: no overlay for this pool_id; absence is honest, not a guess."})
    raw["endpoint"] = "pool"
    return _envelope(raw, fp)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1/pool/{pool_id}/history — proof-chained historical series
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1/pool/{pool_id}/history")
def v1_pool_history(
    pool_id: str,
    request: Request,
    limit: int = Query(default=365, ge=1, le=2000),
):
    """ONE pool's proof-chained HISTORY (APY/TVL/refusal-state over time), verified
    as one chain. NO-FORK: delegates to the public history reader so the chain badge
    + series are byte-identical. Fail-CLOSED: invalid pool_id → 404; absent history
    → 200 + vacuously-valid empty chain."""
    fp = _authorize(request)
    # Reuse the public handler's exact logic (it raises 404 on a bad id) — no fork.
    body = _dfb.get_dfb_pool_history(pool_id, limit=limit)
    if isinstance(body, dict):
        body = dict(body)
        body["endpoint"] = "history"
    return _envelope(body, fp)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1/refusals — the REFUSED-pools feed (the differentiator)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1/refusals")
def v1_refusals(request: Request):
    """The REFUSED-POOLS FEED — every pool the deterministic desk would REFUSE,
    with its reason code + tail-veto flag + proof_hash. **This is the differentiator**:
    no incumbent publishes a programmatic "pools the desk refuses" feed.

    NO-FORK: derived (filter only, NO risk math) from the same ``/api/dfb/pools``
    universe. Fail-CLOSED: a missing universe → 200 with an honest empty feed."""
    fp = _authorize(request)
    pools = _dfb._read_pools_list()
    refused = []
    for p in pools:
        refusal = p.get("refusal")
        if isinstance(refusal, dict) and refusal.get("verdict") == "REFUSE":
            refused.append({
                "pool_id": p.get("pool_id"),
                "protocol": p.get("protocol"),
                "chain": p.get("chain"),
                "asset": p.get("asset"),
                "risk_class": p.get("risk_class"),
                "refusal": refusal,
                "structural_haircut": p.get("structural_haircut"),
                "total_haircut": p.get("total_haircut"),
                "as_of": p.get("as_of"),
                "row_hash": p.get("row_hash"),
            })
    return _envelope({
        "endpoint": "refusals",
        "available": bool(pools),
        "n_refused": len(refused),
        "n_universe": len(pools),
        "refusals": refused,
        "note": (
            None if pools
            else "DFB universe unavailable — no refusals can be derived (fail-CLOSED, "
                 "not an empty 'all clear')."
        ),
    }, fp)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1/screener — filtered query (risk_class / refused / chain)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1/screener")
def v1_screener(
    request: Request,
    risk_class: str = Query(default="", description="Filter by A|B|C|D (comma-separated ok)."),
    refused: str = Query(default="", description="true|false — only refused / only non-refused."),
    chain: str = Query(default="", description="Filter by chain (e.g. ethereum, arbitrum)."),
    protocol: str = Query(default="", description="Filter by protocol (e.g. aave_v3)."),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """FILTERED screener query over the risk-graded universe — by risk_class, refused
    state, chain, and/or protocol. Pure FILTER over the same overlay rows (NO-FORK,
    NO risk math). Fail-CLOSED: unknown filter values simply match nothing (an empty
    result is honest, never a fabricated row)."""
    fp = _authorize(request)
    pools = _dfb._read_pools_list()

    wanted_classes = {c.strip().upper() for c in risk_class.split(",") if c.strip()}
    refused_flag = refused.strip().lower()
    want_chain = chain.strip().lower()
    want_protocol = protocol.strip().lower()

    out = []
    for p in pools:
        if wanted_classes and str(p.get("risk_class", "")).upper() not in wanted_classes:
            continue
        if refused_flag in _TRUTHY or refused_flag == "false" or refused_flag == "no":
            ref = p.get("refusal")
            is_ref = isinstance(ref, dict) and ref.get("verdict") == "REFUSE"
            if refused_flag in _TRUTHY and not is_ref:
                continue
            if refused_flag in {"false", "no"} and is_ref:
                continue
        if want_chain and str(p.get("chain", "")).lower() != want_chain:
            continue
        if want_protocol and str(p.get("protocol", "")).lower() != want_protocol:
            continue
        out.append(p)

    out = out[:limit]
    return _envelope({
        "endpoint": "screener",
        "available": bool(pools),
        "filters": {"risk_class": sorted(wanted_classes) or None,
                    "refused": refused_flag or None,
                    "chain": want_chain or None,
                    "protocol": want_protocol or None},
        "n_matched": len(out),
        "n_universe": len(pools),
        "pools": out,
    }, fp)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/dfb/v1 — the surface index (self-describing; still key-gated)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/dfb/v1")
def v1_index(request: Request):
    """Self-describing index of the v1 Data API surface (key-gated). The honest pitch
    + the endpoint catalog + the reproduce story. See docs/DFB_DATA_API.md."""
    fp = _authorize(request)
    return _envelope({
        "endpoint": "index",
        "product": "DFB Data API",
        "pitch": "The risk truth + the proof, not just the yield.",
        "endpoints": {
            "GET /api/dfb/v1/pools": "the full risk-graded universe",
            "GET /api/dfb/v1/pool/{id}": "one pool's full overlay + proof",
            "GET /api/dfb/v1/pool/{id}/history": "proof-chained historical series",
            "GET /api/dfb/v1/refusals": "the refused-pools feed (the differentiator)",
            "GET /api/dfb/v1/screener": "filtered query (risk_class/refused/chain/protocol)",
        },
        "auth": "X-API-Key: <key>  OR  Authorization: Bearer <hmac-token>",
        "docs": "docs/DFB_DATA_API.md",
        "owner_gated_launch": (
            "The API is BUILT and flag-gated (SPA_DFB_DATA_API). The PUBLIC LAUNCH "
            "(key issuance, billing, SLA, ToS) is OWNER-GATED — not auto-activated."
        ),
    }, fp)
