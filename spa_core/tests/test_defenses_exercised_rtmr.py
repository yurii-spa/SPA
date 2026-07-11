"""Tests for the Q2-13 RTMR defenses-exercised report (scripts/defenses_exercised_rtmr.py).

Verifies every RTMR reaction fires at the right de-risk action through the production reaction engine,
the de-risk-only invariant holds, the fail-closed (stale→FREEZE) + no-over-reaction (info→none) + systemic
(→MARKET_EXIT) + no-cascade-on-stale cases are all asserted. Deterministic; no network.
"""
import importlib

from spa_core.monitoring import reaction as R

der = importlib.import_module("scripts.defenses_exercised_rtmr")


def test_all_rtmr_reactions_fire():
    rep = der.run()
    assert rep["all_fired"] is True
    assert rep["scenarios_fired"] == rep["scenarios_total"]
    assert rep["scenarios_total"] >= 12


def test_critical_de_risk_actions_present():
    rep = der.run()
    by = {r["scenario"]: r for r in rep["scenarios"]}
    # spot-check the headline reactions
    assert any(r["expected"] == R.FULL_EXIT and r["fired"] for r in rep["scenarios"])
    assert any(r["expected"] == R.FREEZE and r["fired"] for r in rep["scenarios"])
    assert any(r["expected"] == R.MARKET_EXIT and r["fired"] for r in rep["scenarios"])


def test_stale_sensor_freezes_fail_closed():
    rep = der.run()
    stale = next(r for r in rep["scenarios"] if "stale/blind" in r["scenario"])
    assert stale["expected"] == R.FREEZE and stale["actual"] == R.FREEZE


def test_info_does_not_over_react():
    rep = der.run()
    info = next(r for r in rep["scenarios"] if "info fresh" in r["scenario"])
    assert info["expected"] == "NONE" and info["actual"] == "NONE"


def test_stale_scopes_do_not_cascade_systemic():
    rep = der.run()
    row = next(r for r in rep["scenarios"] if "STALE scopes" in r["scenario"])
    assert row["actual"] == "no_market_exit" and row["fired"]


def test_de_risk_only_invariant_advisory():
    rep = der.run()
    assert "enforced" in rep["de_risk_only_invariant"]
    assert rep["is_advisory"] is True and rep["llm_forbidden"] is True
