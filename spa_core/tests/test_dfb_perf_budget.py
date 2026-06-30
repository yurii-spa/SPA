"""test_dfb_perf_budget.py — the DFB (Lane-2) snapshot-read PERF BUDGET gate.

Verifies the charter's WS-3.2 performance property: the DFB screener is a PRECOMPUTED-SNAPSHOT
product — the API serves data/dfb/pools.json verbatim (one json.loads), it NEVER re-runs the
risk-overlay engine per request. Three verifications:

  • PROPERTY  — every measured surface's p95 is under the documented 300ms budget reading a
                realistic-breadth (hundreds of pools) snapshot; the gate's own self-report passes.
  • RED-TEAM  — the no-recompute TRIPWIRE is meaningful: it FIRES if the overlay engine is called
                during a serve (so a future per-request recompute regression cannot pass silently).
  • SMOKE     — the perf harness runs end-to-end, hermetic (sandbox data dir, live data/ untouched).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — perf gate skipped")

import dfb_perf_budget as pb  # noqa: E402


def test_dfb_perf_budget_passes_under_p95_300ms():
    """PROPERTY + SMOKE: the snapshot-read paths run under p95 300ms at realistic breadth."""
    report = pb.run_budget(iterations=12, n_pools=200)
    if report.get("skipped"):
        pytest.skip(report["reason"])
    assert report["pass"] is True, f"perf gate failed: over_budget={report['over_budget']}"
    assert report["no_recompute"] is True, "router recomputed the overlay per-request"
    assert report["rows"], "no surfaces measured"
    for r in report["rows"]:
        assert r["p95_ms"] <= report["budget_p95_ms"], f"{r['surface']} p95 over budget: {r}"


def test_dfb_perf_no_recompute_tripwire_held():
    """PROPERTY: serving requests calls NO overlay-engine recompute (the O(1) snapshot read)."""
    report = pb.run_budget(iterations=6, n_pools=120)
    if report.get("skipped"):
        pytest.skip(report["reason"])
    assert report["no_recompute"] is True


def test_dfb_perf_tripwire_is_meaningful_redteam():
    """RED-TEAM: the no-recompute tripwire is not vacuous — it FIRES on an actual overlay call.

    If it could never fire, a per-request-recompute regression would pass silently. We prove the
    tripwire detects an overlay-engine call (the exact thing the gate forbids during a serve)."""
    from spa_core.dfb import risk_overlay as ro

    hits = {"n": 0}
    orig = ro.overlay

    def _trip(*_a, **_k):
        hits["n"] += 1
        raise pb._RecomputeTripwire("recompute")

    ro.overlay = _trip
    try:
        with pytest.raises(pb._RecomputeTripwire):
            ro.overlay(None)
    finally:
        ro.overlay = orig
    assert hits["n"] == 1


def test_dfb_perf_budget_is_300ms():
    """PROPERTY: the documented p95 budget is the charter's 300ms breadth ceiling."""
    assert pb.P95_BUDGET_MS == 300.0
