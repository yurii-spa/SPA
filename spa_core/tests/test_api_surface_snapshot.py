"""
test_api_surface_snapshot.py — GOLDEN-REFERENCE surface contract for the SPA API.

This is the load-bearing safety net for the P3-7 router split (server.py → tagged
APIRouters). The SPA API is the LIVE public surface that the site + other systems
consume, so the refactor MUST be behavior-preserving. This test pins:

  1. the full ROUTE TABLE (path, methods, name) — must be identical before/after
     the split. A frozen golden snapshot is checked into this file; any drift
     (added/removed/renamed/re-method'd route) fails loudly.
  2. a representative RESPONSE SHAPE (sorted top-level keys) for one endpoint per
     tag group, served against a hermetic empty data dir so the graceful-fallback
     payloads are exercised — the same fallback the site depends on.

Hermetic + deterministic: _DATA_DIR is redirected to an empty tmp dir so every
endpoint hits its missing-file fallback branch (which must stay byte-stable).
Read-only. No network (live-APY adapters are exercised separately; here the
roster endpoint is shape-checked only on its key set, tolerant of count).

If you intentionally add/remove an endpoint, update GOLDEN_ROUTES below in the
same commit — that is the explicit, reviewed contract change.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


# ── Golden route table ──────────────────────────────────────────────────────────
# (path, sorted-methods-tuple) for every APP route. Starlette mount/internal
# routes (openapi, docs, redoc, swagger oauth, static) are filtered out below so
# this list is exactly the handler surface other systems hit.
# Captured from server.py PRIOR to the router split — the identical-surface oracle.
GOLDEN_ROUTES = {
    ("/api/agent/thought", ("POST",)),
    ("/api/aggressive-lab/annual-contrast", ("GET",)),
    ("/api/aggressive-lab/scorecard", ("GET",)),
    ("/api/aggressive-lab/strategy/{strategy_id}", ("GET",)),
    ("/api/apy/history/{protocol_key}", ("GET",)),
    ("/api/apy/trends", ("GET",)),
    ("/api/backtest", ("GET",)),
    ("/api/backtest/compare", ("GET",)),
    ("/api/backtest/replay", ("GET",)),
    ("/api/backtest/summary", ("GET",)),
    ("/api/chat", ("POST",)),
    ("/api/competitive-watch", ("GET",)),
    # DFB — DeFi Board (LANE 2): public risk-first pool analytics, read-only/GET/fail-CLOSED.
    ("/api/dfb/pools", ("GET",)),
    ("/api/dfb/pool/{pool_id}", ("GET",)),
    ("/api/dfb/pool/{pool_id}/history", ("GET",)),
    ("/api/dfb/pool/{pool_id}/proof", ("GET",)),
    ("/api/dfb/summary", ("GET",)),
    # DFB Month-2: trends (Lane A), alerts (Lane B), read-only portfolio lens (Lane C, flag-gated)
    ("/api/dfb/pool/{pool_id}/trend", ("GET",)),
    ("/api/dfb/alerts", ("GET",)),
    ("/api/dfb/pool/{pool_id}/alerts", ("GET",)),
    ("/api/dfb/portfolio/{address}", ("GET",)),
    # DFB Month-3: the risk-graded Data API v1 surface (SPA_DFB_DATA_API flag-gated)
    ("/api/dfb/v1", ("GET",)),
    ("/api/dfb/v1/pools", ("GET",)),
    ("/api/dfb/v1/pool/{pool_id}", ("GET",)),
    ("/api/dfb/v1/pool/{pool_id}/history", ("GET",)),
    ("/api/dfb/v1/refusals", ("GET",)),
    ("/api/dfb/v1/screener", ("GET",)),
    ("/api/events", ("GET",)),
    ("/api/events/history", ("GET",)),
    ("/api/execution/readiness", ("GET",)),
    ("/api/governance", ("GET",)),
    ("/api/health-public", ("GET",)),
    ("/api/live/agents", ("GET",)),
    ("/api/live/data/{filename}", ("GET",)),
    ("/api/live/fleet", ("GET",)),
    ("/api/live/health", ("GET",)),
    ("/api/live/ping", ("GET",)),
    ("/api/live/portfolio", ("GET",)),
    ("/api/live/safety", ("GET",)),
    ("/api/live/status", ("GET",)),
    ("/api/live/system", ("GET",)),
    ("/api/optimization", ("GET",)),
    ("/api/optimizer-ab", ("GET",)),
    ("/api/captured-book", ("GET",)),
    ("/api/redteam", ("GET",)),
    ("/api/pools", ("GET",)),
    ("/api/portfolio", ("GET",)),
    ("/api/positions", ("GET",)),
    ("/api/rates-desk/anchors", ("GET",)),
    ("/api/rates-desk/decisions", ("GET",)),
    ("/api/rates-desk/exit-nav", ("GET",)),
    ("/api/rates-desk/full-chain", ("GET",)),
    ("/api/rates-desk/full-chain/{surface}", ("GET",)),
    ("/api/rates-desk/opportunities", ("GET",)),
    ("/api/rates-desk/proof", ("GET",)),
    ("/api/rates-desk/refusals", ("GET",)),
    ("/api/rates-desk/surface", ("GET",)),
    ("/api/rates-desk/track", ("GET",)),
    ("/api/refusal", ("GET",)),
    ("/api/risk", ("GET",)),
    ("/api/rwa-safety-board", ("GET",)),
    ("/api/rwa-nav-curve", ("GET",)),
    ("/api/ssot/facts", ("GET",)),
    ("/api/status", ("GET",)),
    ("/api/trades", ("GET",)),
    ("/api/strategy-lab", ("GET",)),
    ("/api/strategy-lab/promotion", ("GET",)),
    ("/api/tier1/attribution", ("GET",)),
    ("/api/tier1/benchmark", ("GET",)),
    ("/api/tier1/correlation", ("GET",)),
    ("/api/tier1/gate", ("GET",)),
    ("/api/tier1/limits", ("GET",)),
    ("/api/tier1/monte-carlo", ("GET",)),
    ("/api/tier1/nav", ("GET",)),
    ("/api/tier1/packages", ("GET",)),
    ("/api/tier1/regime", ("GET",)),
    ("/api/tier1/reverse-stress", ("GET",)),
    ("/api/tier1/status", ("GET",)),
    ("/api/tier1/var", ("GET",)),
    ("/api/tier1/verdict", ("GET",)),
    ("/api/tier1/walk-forward", ("GET",)),
    ("/api/tournament", ("GET",)),
    ("/api/tournament/status", ("GET",)),
    # Lane C (Layer-3 moat) — the underwriting report surface is FLAG-GATED (SPA_UNDERWRITING_PUBLISH);
    # the ROUTES always exist (registered at import) but 404 until the owner flips the flag.
    ("/api/underwriting/report", ("GET",)),
    ("/api/underwriting/proof", ("GET",)),
    ("/api/underwriting/full-chain", ("GET",)),
    ("/api/v1/adapters", ("GET",)),
    ("/api/v1/day30", ("GET",)),  # WS5 — day-30 readiness artifact (auto/verifiable/hash-anchored)
    ("/api/v1/evidence", ("GET",)),
    ("/api/v1/golive", ("GET",)),
    ("/api/v1/status", ("GET",)),
    ("/health", ("GET",)),
    ("/ws/agents", ("GET",)),  # websocket route reports as GET in Starlette
}


def _filter_internal(path: str) -> bool:
    """Keep handler routes; drop FastAPI/Starlette built-ins."""
    return path not in {
        "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect",
    }


def _walk_routes(routes):
    """Recursively yield (path, methods) over app.routes, expanding included routers.

    Newer FastAPI (>=0.115) includes a router lazily as a single `_IncludedRouter`
    proxy whose real sub-routes hang off `.original_router.routes` (older FastAPI
    flattens everything onto app.routes directly). We expand the proxy so the flat
    handler surface is enumerated regardless of monolith-vs-included-router
    structure — exactly the property this snapshot must be invariant to.
    """
    for r in routes:
        inner = getattr(r, "original_router", None)  # _IncludedRouter (FastAPI >=0.115)
        if inner is not None:
            yield from _walk_routes(inner.routes)
            continue
        path = getattr(r, "path", None)
        if not path or not _filter_internal(path):
            continue
        methods = getattr(r, "methods", None)
        if methods is None:  # websocket route
            yield (path, ("GET",))
        else:
            yield (path, tuple(sorted(m for m in methods if m != "HEAD")))


def _app_route_table() -> set:
    return set(_walk_routes(server.app.routes))


def test_route_table_identical_to_golden():
    """The full route table (path+methods) must match the frozen golden set exactly."""
    actual = _app_route_table()
    missing = GOLDEN_ROUTES - actual
    extra = actual - GOLDEN_ROUTES
    assert not missing, f"routes DISAPPEARED after refactor: {sorted(missing)}"
    assert not extra, f"routes ADDED/CHANGED after refactor: {sorted(extra)}"


def test_route_count_stable():
    """The flat handler surface (expanded across included routers) is the invariant.

    82 HTTP handlers + 1 websocket (/ws/agents) = 83 entries in GOLDEN_ROUTES. This
    is structure-independent (monolith routes vs lazily-included routers) because
    _walk_routes expands `_IncludedRouter` proxies. The launch target
    `spa_core.api.server:app` is unaffected — `app` is still defined in server.py.
    (Most recent HTTP handlers: the DFB — DeFi Board LANE-2 surface — /api/dfb/pools,
    /api/dfb/pool/{pool_id}, /api/dfb/pool/{pool_id}/history, /api/dfb/pool/{pool_id}/proof,
    /api/dfb/summary — the public risk-first pool analytics (read-only/GET/fail-CLOSED:
    every pool A/B/C/D + exit-liquidity-by-size + refusal verdict + a re-derivable proof
    hash; missing data → honest "unavailable"; unknown pool_id → 404; serves Lane 1's
    overlay verbatim, never forks the risk math). Before them the owner's Annual-Contrast
    SURFACE (/api/aggressive-lab/annual-contrast), the Lane 3 Aggressive-Lab SURFACE
    (/api/aggressive-lab/scorecard + /strategy/{id}), and the Lane C underwriting-report
    surface (/api/underwriting/report + /proof + /full-chain), FLAG-GATED OFF by default
    (SPA_UNDERWRITING_PUBLISH).)
    """
    assert len(_app_route_table()) == 93


def test_openapi_path_count_stable():
    """The OpenAPI schema (the canonical served HTTP surface) lists all HTTP paths."""
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        paths = c.get("/openapi.json").json()["paths"]
    assert len(paths) == 92  # 92 HTTP handlers; /ws/agents is a websocket (not an OpenAPI path)


# ── Representative response-shape snapshot (one endpoint per tag group) ──────────
# Each value is the sorted tuple of TOP-LEVEL keys the graceful (empty-data-dir)
# fallback returns. These shapes are what the site renders against — they must be
# byte-stable across the refactor.
SHAPE_GOLDEN = {
    "/health": ("status", "timestamp", "version"),
    # /api/governance is a pure _load_json fallback (no PaperTrader dependency) →
    # a deterministic, environment-independent shape oracle for the "data" group.
    "/api/governance": ("dual_control_posture", "generated_at", "policy"),
    "/api/tier1/nav": ("computed_nav_usd", "generated_at", "meta", "reconciliation_ok"),
    "/api/strategy-lab": (
        "generated_at", "meta", "rwa_floor_pct", "strategies",
        "window_end", "window_start",
    ),
    "/api/aggressive-lab/scorecard": (
        "advisory", "available", "generated_at", "live_eligible", "meta", "model",
        "n_strategies", "note", "outside_riskpolicy", "owner_select_enabled",
        "owner_selectable", "rwa_floor_pct", "strategies", "trustworthy",
        "unavailable_reason",
    ),
    "/api/aggressive-lab/annual-contrast": (
        "advisory", "as_of", "available", "generated_at", "live_eligible", "meta",
        "model", "n_strategies", "note", "notional_usd", "outside_riskpolicy",
        "owner_select_enabled", "owner_selectable", "proof_hash", "risk_class_legend",
        "stable_apy_pct", "stable_apy_source", "strategies", "stress_windows",
        "unavailable_reason",
    ),
    "/api/rates-desk/surface": (
        "as_of", "generated_at", "hedge_available", "meta", "mode",
        "quotes", "underlying_risk",
    ),
    "/api/refusal": (
        "advisory", "generated_at", "latest_date", "model",
        "thresholds", "underlyings", "verdict_counts",
    ),
    "/api/tournament": ("live", "mass_results", "meta", "server_time", "shadow_paper", "tournament", "trustworthy"),
    # DFB (LANE 2): the screener fallback shape against an empty data dir (honest "unavailable").
    "/api/dfb/pools": (
        "available", "disclaimer", "generated_at", "is_advisory", "model",
        "n_pools", "note", "pools", "reproduce",
    ),
    "/api/v1/evidence": ("data", "source", "timestamp"),
    "/api/live/ping": ("ok", "ts", "version"),
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with the data dir redirected to an EMPTY hermetic tmp dir, so every
    endpoint takes its missing-file graceful-fallback branch."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


@pytest.mark.parametrize("path,expected_keys", sorted(SHAPE_GOLDEN.items()))
def test_response_shape_snapshot(client, path, expected_keys):
    """Each representative endpoint returns 200 with the exact graceful-fallback key set."""
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} → {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert isinstance(body, dict), f"{path} returned non-dict {type(body)}"
    assert tuple(sorted(body.keys())) == expected_keys, (
        f"{path} top-level keys drifted:\n"
        f"  got:      {tuple(sorted(body.keys()))}\n"
        f"  expected: {expected_keys}"
    )
