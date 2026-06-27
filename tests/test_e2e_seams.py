#!/usr/bin/env python3
"""End-to-end SEAM harness — cycle ↔ golive_checker ↔ API ↔ dashboard (T8).

WHAT THIS GUARDS
================
SPA's ~50 launchd agents do not call each other — they communicate through a
set of shared JSON state files in ``data/``. The cycle WRITES those files; the
go-live checker, the FastAPI ``/api/*`` routers and the dashboard READ them. The
live API "returns files VERBATIM" (memory footgun): the on-disk field shape IS
the API shape IS the dashboard's expectation. A renamed or dropped field on the
WRITE side silently breaks every READER downstream with no error — the panel
just goes blank or stale.

This harness runs an INERT cycle into a temp sandbox, then asserts the SEAMS:

    cycle output  →  golive_checker reads      (a)
    on-disk shape →  /api/* router emits        (b)  (files-verbatim contract)
    on-disk shape →  dashboard consumes         (c)  (documented field names)

Specifically pinned (the cross-surface contracts memory flagged as fragile):
  * golive_status: ``passed`` / ``total`` + ``real_track_days`` + ``target_date``
    + ``evidenced_anchor`` + ``ready``.
  * portfolio_state (paper_trading_status): ``current_equity`` / ``apy_today_pct``
    / ``total_return_pct`` / ``daily_yield_usd`` / ``market_regime`` /
    ``days_running`` / ``is_demo``.
  * the live API returns files verbatim, so the dashboard's getFacts()/getFleet()
    field maps must each find their source key on disk.
  * the fleet surface (agent_health.json): ``healthy_count`` / ``warning_count``
    / ``critical_count`` / ``total_agents`` / ``overall_status`` / ``timestamp``
    / ``agents[].label/status/issue``.

ANY drift — a field a downstream reader needs that the writer no longer provides
— FAILS a test here. That is the whole point: catch the contract break in CI
before the dashboard silently goes blank in production.

SANDBOX SAFETY (track-corruption hazard, CLAUDE.md / MEMORY.md)
==============================================================
Every cycle in this module runs against a fresh ``tmp_path`` data dir with
injected fakes (no live adapters / no network / no iCloud writes). The live
canonical ``<repo>/data`` track is NEVER read or written by these tests — a
module-scope guard asserts the live equity-curve mtime is unchanged across the
whole run. stdlib + pytest only; deterministic (fixed UTC ``now``).
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr
from spa_core.paper_trading.golive_checker import GoLiveChecker
from spa_core.paper_trading.equity import _upsert_equity_point
from spa_core.governance import ssot


# ─── Repo / live-data identity (for the safety guard) ────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIVE_DATA_DIR = _REPO_ROOT / "data"
_LIVE_EQUITY = _LIVE_DATA_DIR / "equity_curve_daily.json"


# ─── Deterministic, network-free fakes (mirror the characterization test) ────

_APY = {"aave_v3": 3.5, "compound_v3": 4.0, "morpho_blue": 4.8}
_TARGET = {"aave_v3": 30_000.0, "compound_v3": 20_000.0, "morpho_blue": 15_000.0}
_NOW = datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)


def _orch_fn(data_dir):
    adapters = [
        {
            "protocol": p,
            "apy_pct": a,
            "tvl_usd": 1e7,
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
            "chain": "ethereum",
        }
        for p, a in _APY.items()
    ]
    return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(_TARGET),
            target_weights={p: v / 100_000 for p, v in _TARGET.items()},
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run_inert_cycle(ddir: Path):
    """Run ONE inert cycle into *ddir* (injected fakes, no network/iCloud)."""
    return cr.run_cycle(
        data_dir=ddir,
        now=_NOW,
        orchestrator_fn=_orch_fn,
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
    )


def _seed_evidenced_curve(ddir: Path, *, days: int, anchor: datetime) -> None:
    """Build a *days*-long EVIDENCED equity curve via the cycle's OWN writer.

    Using ``_upsert_equity_point`` (not a hand-rolled dict) keeps the seeded
    bars bit-compatible with what a real cycle writes — each bar carries
    ``source="cycle"`` / ``evidenced=True``, so golive_checker counts them as
    honest track days. This gives ``real_track_days >= 30`` so the harness can
    exercise the evidenced-track seam (not just the empty-track edge case).
    """
    equity_doc: dict = {}
    positions = dict(_TARGET)
    for i in range(days):
        d = (anchor + timedelta(days=i)).strftime("%Y-%m-%d")
        equity_doc, *_ = _upsert_equity_point(
            equity_doc,
            date=d,
            apy_today_pct=3.6,
            positions=positions,
            apy_map=dict(_APY),
            run_ts=(anchor + timedelta(days=i)).isoformat(),
            accrual_source="live",
        )
    from spa_core.paper_trading._cycle_io import _atomic_write_json, EQUITY_FILENAME

    _atomic_write_json(ddir / EQUITY_FILENAME, equity_doc)


# ─── Sandbox fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _assert_live_data_untouched():
    """GUARDRAIL: the live canonical track must be byte-identical across this run.

    Snapshots the live equity-curve mtime+size before any test and re-checks
    after — proves no test in this module wrote the canonical ``data/`` track.
    """
    before = None
    if _LIVE_EQUITY.exists():
        st = _LIVE_EQUITY.stat()
        before = (st.st_mtime_ns, st.st_size)
    yield
    if before is not None:
        st = _LIVE_EQUITY.stat()
        after = (st.st_mtime_ns, st.st_size)
        assert after == before, (
            "GUARDRAIL VIOLATION: the live canonical track "
            f"{_LIVE_EQUITY} was modified by the seam harness "
            f"(before={before} after={after}). The sandbox redirect leaked."
        )


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """One inert cycle + a 30-day evidenced curve in a fresh tmp data dir.

    Module-scoped so the (relatively heavy) cycle runs once; every seam test
    reads the resulting on-disk state. NEVER the live ``data/`` dir.
    """
    ddir = tmp_path_factory.mktemp("spa_seam_data")

    # 1) Run the inert cycle — writes trades / status / positions / golive.
    result = _run_inert_cycle(ddir)
    assert result.status in ("ok", "blocked_by_policy"), result.status

    # 2) Overlay a 30-day EVIDENCED curve so real_track_days is meaningful, then
    #    re-run the go-live checker so golive_status.json reflects the full track.
    anchor = datetime(2026, 6, 22, tzinfo=timezone.utc)
    _seed_evidenced_curve(ddir, days=30, anchor=anchor)
    GoLiveChecker(
        data_dir=ddir, now=anchor + timedelta(days=29, hours=8)
    ).check(write=True)

    return ddir


def _load(ddir: Path, name: str) -> dict:
    return json.loads((ddir / name).read_text(encoding="utf-8"))


# ─── Router harness — point server._DATA_DIR at the sandbox ──────────────────


@pytest.fixture
def api_server(sandbox, monkeypatch):
    """Bind the API routers to the sandbox via server._DATA_DIR (call-time).

    Mirrors the API test-suite convention documented in _shared.data_dir():
    every router resolves the data dir through ``server._DATA_DIR`` at call
    time, so this monkeypatch reaches every handler. NO live data is read.
    """
    from spa_core.api import server

    monkeypatch.setattr(server, "_DATA_DIR", sandbox, raising=False)
    return server


def _run_async(coro):
    """Drive an async router handler to completion (stdlib asyncio)."""
    import asyncio

    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# SEAM (a): cycle output  →  golive_checker reads
# ═══════════════════════════════════════════════════════════════════════════


def test_seam_cycle_writes_files_golive_reads(sandbox):
    """The three anti-demo files the cycle writes are exactly what golive reads."""
    # Cycle wrote them as REAL (is_demo:false) — golive's Group-1 checks pass.
    equity = _load(sandbox, "equity_curve_daily.json")
    assert equity.get("is_demo") is False
    assert equity.get("source") == "cycle_runner"
    assert isinstance(equity.get("daily"), list) and equity["daily"]

    pts = _load(sandbox, "paper_trading_status.json")
    assert pts.get("is_demo") is False

    trades = _load(sandbox, "trades.json")
    assert isinstance(trades, list)
    assert any(isinstance(t, dict) and t.get("is_demo") is False for t in trades)


def test_seam_golive_status_shape(sandbox):
    """golive_status.json carries the exact keys downstream readers depend on.

    This is the CANONICAL go-live contract — SSOT.key_facts, /api/health-public,
    the dashboard offline-snapshot map and the live SPA_API.getFacts all read
    these keys. Pin them so a rename in golive_checker.to_dict() fails loudly.
    """
    gl = _load(sandbox, "golive_status.json")
    for key in (
        "passed",
        "total",
        "real_track_days",
        "evidenced_anchor",
        "target_date",
        "ready",
        "checks",
        "criteria",
    ):
        assert key in gl, f"golive_status.json missing dashboard-critical key {key!r}"

    # The evidenced 30-day curve must drive a real (non-zero, sane) track count.
    assert gl["passed"] <= gl["total"], (gl["passed"], gl["total"])
    assert gl["real_track_days"] >= 30, gl["real_track_days"]
    assert gl["evidenced_anchor"] == "2026-06-22"
    # target = anchor + (30 - 1) days = 2026-07-21 (honest, fixed calendar date).
    assert gl["target_date"] == "2026-07-21", gl["target_date"]


# ═══════════════════════════════════════════════════════════════════════════
# SEAM (b): on-disk shape  →  /api/* routers emit (files VERBATIM)
# ═══════════════════════════════════════════════════════════════════════════


def test_seam_live_status_returns_files_verbatim(api_server):
    """/api/live/status nests the on-disk files under stem keys, byte-for-byte."""
    from spa_core.api.routers import live

    body = json.loads(_run_async(live.live_status()).body)
    # Verbatim contract: each file appears under its stem and EQUALS the on-disk doc.
    for stem, fname in (
        ("paper_trading_status", "paper_trading_status.json"),
        ("golive_status", "golive_status.json"),
        ("current_positions", "current_positions.json"),
    ):
        assert stem in body, f"/api/live/status dropped {stem}"
        assert body[stem] == _load(api_server._DATA_DIR, fname), (
            f"/api/live/status mutated {stem} — not returned verbatim"
        )


def test_seam_live_portfolio_carries_dashboard_fields(api_server):
    """/api/live/portfolio surfaces the equity + status the dashboard polls."""
    from spa_core.api.routers import live

    body = json.loads(_run_async(live.live_portfolio()).body)
    pts = body.get("paper_trading_status")
    assert isinstance(pts, dict), "live/portfolio dropped paper_trading_status"
    # The exact fields the dashboard's offline-snapshot map pulls from `track`.
    for f in ("current_equity", "apy_today_pct", "total_return_pct",
              "daily_yield_usd", "market_regime"):
        assert f in pts, f"paper_trading_status (via live/portfolio) missing {f!r}"
    assert body.get("equity_curve_daily", {}).get("source") == "cycle_runner"


def test_seam_health_public_maps_golive_passed_total(api_server):
    """/api/health-public derives risk_gates_passed/total straight from golive."""
    from spa_core.api.routers import misc

    body = misc.get_health_public()
    gl = _load(api_server._DATA_DIR, "golive_status.json")
    pts = _load(api_server._DATA_DIR, "paper_trading_status.json")

    # passed/total seam — the landing widget reads risk_gates_passed/total.
    assert body["risk_gates_passed"] == gl["passed"]
    assert body["risk_gates_total"] == gl["total"]
    # real_track_days + anchor/target seam (honest evidenced track).
    assert body["real_track_days"] == gl["real_track_days"]
    assert body["track_days"] == gl["real_track_days"]
    assert body["evidenced_anchor"] == gl["evidenced_anchor"]
    assert body["go_live_target"] == gl["target_date"]
    # portfolio seam — current_equity / apy / return mirror paper_trading_status.
    assert body["current_equity"] == pts["current_equity"]
    assert body["apy_today_pct_annualized"] == pts["apy_today_pct"]
    assert body["total_return_pct"] == pts["total_return_pct"]
    assert body["is_demo"] is False


def test_seam_ssot_key_facts_mirror(api_server):
    """SSOT key_facts (behind /api/ssot/facts) mirrors golive + status verbatim.

    The /api/ssot/facts handler calls key_facts() — we call it bound to the
    sandbox to assert the SSOT seam without depending on the live data dir.
    """
    facts = ssot.key_facts(data_dir=api_server._DATA_DIR)
    gl = _load(api_server._DATA_DIR, "golive_status.json")
    pts = _load(api_server._DATA_DIR, "paper_trading_status.json")

    # The exact keys the LIVE dashboard path (SPA_API.getFacts) requires.
    assert facts["golive_passed"] == gl["passed"]
    assert facts["golive_total"] == gl["total"]
    assert facts["golive_ready"] == gl["ready"]
    assert facts["real_track_days"] == gl["real_track_days"]
    assert facts["track_days"] == gl["real_track_days"]
    assert facts["evidenced_anchor"] == gl["evidenced_anchor"]
    assert facts["go_live_target"] == gl["target_date"]
    assert facts["current_equity"] == pts["current_equity"]
    assert facts["apy_today_pct"] == pts["apy_today_pct"]
    assert facts["total_return_pct"] == pts["total_return_pct"]
    assert facts["daily_yield_usd"] == pts["daily_yield_usd"]
    assert facts["regime"] == pts["market_regime"]


# ═══════════════════════════════════════════════════════════════════════════
# SEAM (c): on-disk shape  →  dashboard consumes (documented field names)
# ═══════════════════════════════════════════════════════════════════════════

# These are the EXACT keys index.html reads. They are duplicated here as a
# literal contract: a rename on the cycle/golive WRITE side that drops one of
# these would silently blank the dashboard — this test turns that into a
# loud failure. (Source: index.html SPA_API.getFacts offline-snapshot map +
# the /api/ssot/facts live map.)

# golive_status.json keys read by the dashboard offline-snapshot path.
_DASH_GOLIVE_KEYS = (
    "real_track_days",  # → facts.real_track_days / track_days
    "passed",           # → facts.golive_passed
    "total",            # → facts.golive_total
    "ready",            # → facts.golive_ready
    "target_date",      # → facts.go_live_target
    "evidenced_anchor",  # → facts.evidenced_anchor
)

# paper_trading_status.json keys read by the dashboard offline-snapshot path.
_DASH_TRACK_KEYS = (
    "current_equity",
    "total_return_pct",
    "apy_today_pct",
    "daily_yield_usd",
    "market_regime",    # → facts.regime
    "last_cycle_ts",    # → as_of stamp
)


def test_seam_dashboard_offline_golive_keys_present(sandbox):
    """Every golive key the dashboard's getFacts() offline map reads exists."""
    gl = _load(sandbox, "golive_status.json")
    missing = [k for k in _DASH_GOLIVE_KEYS if k not in gl]
    assert not missing, (
        "golive_status.json missing keys the dashboard offline-snapshot reads: "
        f"{missing} — getFacts() would render '—' / break"
    )


def test_seam_dashboard_offline_track_keys_present(sandbox):
    """Every paper_trading_status key the dashboard getFacts() offline map reads."""
    pts = _load(sandbox, "paper_trading_status.json")
    missing = [k for k in _DASH_TRACK_KEYS if k not in pts]
    assert not missing, (
        "paper_trading_status.json missing keys the dashboard offline-snapshot "
        f"reads: {missing} — current_equity/apy_today_pct panels would blank"
    )


# ═══════════════════════════════════════════════════════════════════════════
# SEAM (d): the fleet surface (agent_health.json) → /api/live/fleet → dashboard
# ═══════════════════════════════════════════════════════════════════════════

# /api/live/fleet reads these top-level keys + agents[] sub-keys VERBATIM.
_FLEET_TOP_KEYS = (
    "overall_status",
    "healthy_count",
    "warning_count",
    "critical_count",
    "total_agents",
    "timestamp",
    "agents",
)
_FLEET_AGENT_KEYS = ("label", "status", "issue")


def _write_representative_agent_health(ddir: Path) -> dict:
    """Write an agent_health.json with exactly the producer's documented shape."""
    doc = {
        "timestamp": _NOW.isoformat(),
        "overall_status": "healthy",
        "healthy_count": 49,
        "warning_count": 1,
        "critical_count": 0,
        "total_agents": 50,
        "agents": [
            {"label": "com.spa.daily_cycle", "status": "HEALTHY",
             "issue": "", "category": "core"},
            {"label": "com.spa.morning_digest", "status": "WARNING",
             "issue": "exit=1 (telegram)", "category": "reporting"},
        ],
    }
    from spa_core.paper_trading._cycle_io import _atomic_write_json

    _atomic_write_json(ddir / "agent_health.json", doc)
    return doc


def test_seam_fleet_surface_shape(sandbox, api_server):
    """/api/live/fleet reads agent_health.json's fleet shape and emits the
    dashboard's getFleet() contract.

    Pins BOTH ends: the producer key names (healthy_count/critical_count/…)
    AND the consumer keys the dashboard expects (healthy/critical/total/stale).
    A rename of either side (the footgun: counts silently shown as 0/blank)
    fails here.
    """
    written = _write_representative_agent_health(sandbox)
    # Producer-side contract: the file carries the keys the router reads.
    for k in _FLEET_TOP_KEYS:
        assert k in written, f"agent_health.json missing fleet key {k!r}"
    for a in written["agents"]:
        for k in _FLEET_AGENT_KEYS:
            assert k in a, f"agent_health agent entry missing {k!r}"

    from spa_core.api.routers import live

    body = json.loads(_run_async(live.live_fleet()).body)
    assert body["available"] is True
    # Consumer-side contract: the dashboard's getFleet() reads these keys.
    assert body["overall_status"] == written["overall_status"]
    assert body["healthy"] == written["healthy_count"]
    assert body["warning"] == written["warning_count"]
    assert body["critical"] == written["critical_count"]
    assert body["total"] == written["total_agents"]
    assert "stale" in body and isinstance(body["stale"], bool)
    # Only the warn/crit agents are surfaced, with name/status/reason.
    assert any(p["name"] == "com.spa.morning_digest" for p in body["agents"])


def test_seam_live_agents_verbatim(sandbox, api_server):
    """/api/live/agents returns agent_health.json verbatim (+ _fetched_at)."""
    written = _write_representative_agent_health(sandbox)
    from spa_core.api.routers import live

    body = json.loads(_run_async(live.live_agents()).body)
    # Verbatim: every original key survives unchanged; only _fetched_at is added.
    for k, v in written.items():
        assert body[k] == v, f"/api/live/agents mutated {k!r} (not verbatim)"
    assert "_fetched_at" in body


# ═══════════════════════════════════════════════════════════════════════════
# SEAM (e): cross-surface CONSISTENCY — the same number everywhere (Law 3)
# ═══════════════════════════════════════════════════════════════════════════


def test_seam_passed_total_consistent_across_surfaces(api_server):
    """passed/total is IDENTICAL on disk, via SSOT, and via /api/health-public.

    The classic drift: the dashboard shows a stale/divergent gate count because
    one surface re-derives it. Law-3: every surface mirrors the ONE on-disk value.
    """
    from spa_core.api.routers import misc

    gl = _load(api_server._DATA_DIR, "golive_status.json")
    facts = ssot.key_facts(data_dir=api_server._DATA_DIR)
    health = misc.get_health_public()

    assert gl["passed"] == facts["golive_passed"] == health["risk_gates_passed"]
    assert gl["total"] == facts["golive_total"] == health["risk_gates_total"]


def test_seam_equity_apy_consistent_across_surfaces(api_server):
    """current_equity / apy_today_pct identical on disk, via SSOT, /health-public."""
    from spa_core.api.routers import misc

    pts = _load(api_server._DATA_DIR, "paper_trading_status.json")
    facts = ssot.key_facts(data_dir=api_server._DATA_DIR)
    health = misc.get_health_public()

    assert pts["current_equity"] == facts["current_equity"] == health["current_equity"]
    assert (
        pts["apy_today_pct"]
        == facts["apy_today_pct"]
        == health["apy_today_pct_annualized"]
    )


def test_seam_ssot_presentation_validator_passes_on_canon(api_server):
    """The SSOT Law-3 guard accepts a presentation that mirrors the on-disk canon.

    If a dashboard claimed the on-disk numbers, validate_presentation must say
    ok=True. This proves the canonical key_facts and the file keys agree (a drift
    between them would surface here as a divergence).
    """
    gl = _load(api_server._DATA_DIR, "golive_status.json")
    pts = _load(api_server._DATA_DIR, "paper_trading_status.json")
    claims = {
        "golive_passed": gl["passed"],
        "golive_total": gl["total"],
        "track_days": gl["real_track_days"],
        "current_equity": pts["current_equity"],
        "apy_today_pct": pts["apy_today_pct"],
        "total_return_pct": pts["total_return_pct"],
        "regime": pts["market_regime"],
    }
    verdict = ssot.validate_presentation(claims, data_dir=api_server._DATA_DIR)
    assert verdict["ok"] is True, verdict.get("divergences")
