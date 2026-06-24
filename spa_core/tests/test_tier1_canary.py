"""Tests for spa_core/backtesting/tier1/canary.py — CANARY stage of the promotion pipeline."""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.backtesting.tier1 import canary


_AUM = 100000.0


def _gate_eligible() -> set:
    g = canary._load(canary._GATE, {})
    return set(g.get("eligible_for_paper", []))


def test_candidates_subset_of_gate_eligible():
    cands = set(canary.canary_candidates())
    assert cands <= _gate_eligible(), "canary candidates must have passed the paper gate"


def test_candidates_meet_entry_criteria():
    vidx = canary._verdict_index()
    for sid in canary.canary_candidates():
        row = vidx.get(sid)
        assert row is not None
        assert row.get("validated") is True
        assert row.get("oos_holds") is not False
        assert row.get("capacity_ok") is not False
        assert (row.get("net_apy_pct") or 0) > 0
        assert canary._paper_days(row) >= canary.CANARY_MIN_DAYS


def test_canary_allocation_within_per_canary_cap():
    alloc = canary.canary_allocation("s_any", _AUM)
    assert alloc["capital_usd"] <= canary.CANARY_MAX_CAPITAL_PCT * _AUM + 1e-6
    assert alloc["capital_pct"] == canary.CANARY_MAX_CAPITAL_PCT


def test_total_across_canaries_within_aggregate_cap():
    cands = canary.canary_candidates()
    total = sum(canary.canary_allocation(sid, _AUM)["capital_usd"] for sid in cands)
    assert total <= canary.CANARY_MAX_TOTAL_PCT * _AUM + 1e-6


def test_allocation_within_limits_flag_respects_aggregate():
    # per-canary cap (1%) * 5% aggregate cap → at most 5 canaries fit; with the current
    # (small) candidate set within_limits must hold.
    for sid in canary.canary_candidates():
        a = canary.canary_allocation(sid, _AUM)
        assert a["within_limits"] is True


def test_narrowed_limits_are_tighter_than_full():
    from spa_core.backtesting.tier1 import limits as lim
    for tier, full_cap in lim.PER_PROTOCOL_MAX.items():
        assert canary.CANARY_PER_PROTOCOL_MAX[tier] < full_cap + 1e-12
        assert canary.CANARY_PER_PROTOCOL_MAX[tier] == full_cap / 2.0
    for tier, full_cap in lim.TIER_AGGREGATE_MAX.items():
        assert canary.CANARY_TIER_AGGREGATE_MAX[tier] < full_cap + 1e-12
    assert canary.CANARY_MIN_CASH > lim.MIN_CASH


def test_graduation_always_requires_human_gate():
    # across a wide range of inputs, the human gate is ALWAYS required
    for days in (0, 5, 14, 30, 60, 365):
        for metrics in ({}, {"realized_apy_pct": 5.0, "drawdown_pct": 0.5},
                        {"realized_apy_pct": -3.0}, {"drawdown_pct": 50.0}):
            g = canary.graduation_check("s_x", days, metrics)
            assert g["requires_human_gate"] is True


def test_ready_for_full_needs_graduate_days():
    healthy = {"realized_apy_pct": 4.0, "drawdown_pct": 0.5}
    below = canary.graduation_check("s_x", canary.CANARY_GRADUATE_DAYS - 1, healthy)
    assert below["ready_for_full"] is False
    at = canary.graduation_check("s_x", canary.CANARY_GRADUATE_DAYS, healthy)
    assert at["ready_for_full"] is True
    # still requires a human even when ready
    assert at["requires_human_gate"] is True


def test_ready_for_full_blocked_by_bad_live_metrics():
    enough = canary.CANARY_GRADUATE_DAYS + 5
    neg_apy = canary.graduation_check("s_x", enough, {"realized_apy_pct": -1.0})
    assert neg_apy["ready_for_full"] is False
    deep_dd = canary.graduation_check(
        "s_x", enough, {"drawdown_pct": canary.CANARY_MAX_DRAWDOWN_PCT + 1.0})
    assert deep_dd["ready_for_full"] is False
    # no metrics + enough days → metrics are neutral → ready
    none_metrics = canary.graduation_check("s_x", enough, {})
    assert none_metrics["ready_for_full"] is True


def test_build_report_structure():
    rep = canary.build_report(write=False, aum_usd=_AUM)
    for key in ("generated_at", "model", "stage", "pipeline", "llm_forbidden", "advisory",
                "is_gate", "version", "aum_usd", "config", "candidates", "candidate_count",
                "candidate_detail", "blocked", "summary", "note"):
        assert key in rep, key
    assert rep["stage"] == "canary"
    assert rep["llm_forbidden"] is True
    assert rep["advisory"] is True
    assert rep["is_gate"] is False
    cfg = rep["config"]
    for key in ("max_capital_pct_per_canary", "max_total_pct_all_canaries",
                "min_days_to_enter", "graduate_days_to_full", "narrowed_limits"):
        assert key in cfg, key
    assert rep["candidate_count"] == len(rep["candidate_detail"]) == len(rep["candidates"])
    # every candidate detail carries a graduation block that requires a human gate
    for r in rep["candidate_detail"]:
        assert r["graduation"]["requires_human_gate"] is True
    # candidates must be a subset of the paper-eligible set
    assert set(rep["candidates"]) <= _gate_eligible()


def test_build_report_writes_atomically(tmp_path, monkeypatch):
    out = tmp_path / "tier1_canary.json"
    monkeypatch.setattr(canary, "_OUT", out)
    rep = canary.build_report(write=True, aum_usd=_AUM)
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["version"] == rep["version"]
    assert on_disk["stage"] == "canary"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tier1_canary_")]
    assert leftovers == []


def test_determinism():
    a1 = canary.canary_candidates()
    a2 = canary.canary_candidates()
    assert a1 == a2
    r1 = canary.canary_allocation("s27_stablecoin_carry", _AUM)
    r2 = canary.canary_allocation("s27_stablecoin_carry", _AUM)
    assert r1 == r2
    g1 = canary.graduation_check("s_x", 40, {"realized_apy_pct": 3.0})
    g2 = canary.graduation_check("s_x", 40, {"realized_apy_pct": 3.0})
    assert g1 == g2


def test_zero_aum_safe():
    a = canary.canary_allocation("s_x", 0.0)
    assert a["capital_usd"] == 0.0
    assert a["within_limits"] is True
