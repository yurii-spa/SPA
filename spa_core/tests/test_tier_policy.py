"""Tests for the 6mo-M1 #1 enforced per-tier policy (spa_core/strategy_lab/aggressive_lab/tier_policy.py).

Verifies each tier's enforced band, the Conservative→RiskPolicy-v1.0 delegation, fail-CLOSED on unknown
tier / malformed descriptor, determinism, and the isolation invariant (#3): tier_policy must NOT import
spa_core.execution (the advisory rulebook can never reach the live execution path). No network.
"""
import pytest

from spa_core.strategy_lab.aggressive_lab import tier_policy as tp


def test_aggressive_requires_tail_but_allows_loops():
    ok = tp.validate_book("aggressive", {"risk_class": "D", "leverage": 4.0,
                                         "tail_overlay_present": True, "uses_points_lrt_loops": True})
    assert ok["ok"] is True
    bad = tp.validate_book("aggressive", {"risk_class": "D", "tail_overlay_present": False})
    assert bad["ok"] is False
    assert any("tail" in v for v in bad["violations"])


def test_aggressive_rejects_out_of_band_class():
    r = tp.validate_book("aggressive", {"risk_class": "A", "tail_overlay_present": True})
    assert r["ok"] is False
    assert any("risk_class" in v for v in r["violations"])


def test_balanced_caps_leverage_and_requires_hedge_or_guard():
    r = tp.validate_book("balanced", {"risk_class": "C", "leverage": 3.0, "tail_overlay_present": True})
    assert r["ok"] is False
    assert any("leverage" in v for v in r["violations"])
    assert any("hedge" in v or "depeg" in v for v in r["violations"])
    # hedged + within leverage + tail shown → ok
    assert tp.validate_book("balanced", {"risk_class": "B", "leverage": 1.8,
                                         "hedged": True, "tail_overlay_present": True})["ok"] is True
    # a depeg_guard also satisfies the requirement
    assert tp.validate_book("balanced", {"risk_class": "C", "leverage": 2.0,
                                         "depeg_guard": True, "tail_overlay_present": True})["ok"] is True


def test_balanced_forbids_loops():
    r = tp.validate_book("balanced", {"risk_class": "C", "leverage": 2.0, "hedged": True,
                                      "tail_overlay_present": True, "uses_points_lrt_loops": True})
    assert r["ok"] is False
    assert any("loops" in v or "LRT" in v or "points" in v for v in r["violations"])


def test_conservative_delegates_to_riskpolicy_and_forbids_leverage():
    ok = tp.validate_book("conservative", {"risk_class": "A", "leverage": 1.0})
    assert ok["ok"] is True
    assert ok["delegates_to_riskpolicy"] is True
    assert ok["riskpolicy_version"] == "v1.0"
    lev = tp.validate_book("conservative", {"risk_class": "A", "leverage": 2.0})
    assert lev["ok"] is False
    assert any("leverage" in v or "RiskPolicy" in v for v in lev["violations"])


def test_unknown_tier_fail_closed():
    r = tp.validate_book("mystery", {})
    assert r["ok"] is False
    assert any("unknown tier" in v for v in r["violations"])


def test_malformed_descriptor_fail_closed():
    # missing risk_class + non-numeric leverage → violations, never a crash or silent pass
    r = tp.validate_book("balanced", {"leverage": "lots"})
    assert r["ok"] is False
    assert isinstance(r["violations"], list) and r["violations"]


def test_tier_of_risk_class():
    assert tp.tier_of_risk_class("A") == "conservative"
    assert tp.tier_of_risk_class("B") == "balanced"
    assert tp.tier_of_risk_class("C") == "balanced"   # dual-eligible → safer default
    assert tp.tier_of_risk_class("D") == "aggressive"
    assert tp.tier_of_risk_class("Z") is None


def test_deterministic():
    d = {"risk_class": "C", "leverage": 2.0, "hedged": True, "tail_overlay_present": True}
    assert tp.validate_book("balanced", d) == tp.validate_book("balanced", d)


def test_isolation_no_execution_import():
    """#3 isolation invariant: the tier rulebook must never import the live execution path."""
    import sys
    import importlib
    # (re)import fresh and assert no spa_core.execution.* got pulled in by importing tier_policy
    mod = importlib.reload(tp)
    src = __import__("inspect").getsource(mod)
    assert "spa_core.execution" not in src
    # and nothing execution-shaped is resident as a direct attribute of the module
    assert not any(getattr(v, "__module__", "").startswith("spa_core.execution")
                   for v in vars(mod).values() if hasattr(v, "__module__"))
