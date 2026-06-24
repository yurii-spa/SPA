"""
spa_core/tests/test_tier1_var.py — tests for the Tier-1 VaR/CVaR module.

Pure stdlib, deterministic. Validates the core VaR invariants (VaR <= CVaR, monotone in
confidence), determinism, that principal VaR is meaningful (> 0) for a T2-heavy allocation,
and that build_report produces a well-formed structure.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math

from spa_core.backtesting.tier1 import var as var_mod


# Deterministic synthetic daily-return series with real dispersion (so VaR is non-trivial).
def _synthetic_returns(n: int = 250) -> list:
    out = []
    for i in range(n):
        # bounded oscillation around a small positive mean (mimics yield wobble)
        out.append(0.0002 + 0.0005 * math.sin(i * 0.37) - 0.0003 * math.cos(i * 0.11))
    return out


def test_var_le_cvar_95():
    """CVaR (mean of the worst tail) is at least as large as VaR (the tail cutoff)."""
    r = _synthetic_returns()
    res = var_mod.var_cvar(r, conf=0.95)
    assert res["cvar_pct"] >= res["var_pct"] - 1e-9
    # both methods individually
    assert res["cvar_historical_pct"] >= res["var_historical_pct"] - 1e-9
    assert res["cvar_parametric_pct"] >= res["var_parametric_pct"] - 1e-9


def test_var_le_cvar_99():
    r = _synthetic_returns()
    res = var_mod.var_cvar(r, conf=0.99)
    assert res["cvar_pct"] >= res["var_pct"] - 1e-9


def test_99_var_ge_95_var():
    """Higher confidence => larger (worse) VaR, for both methods."""
    r = _synthetic_returns()
    v95 = var_mod.var_cvar(r, conf=0.95)
    v99 = var_mod.var_cvar(r, conf=0.99)
    assert v99["var_parametric_pct"] >= v95["var_parametric_pct"] - 1e-9
    assert v99["var_historical_pct"] >= v95["var_historical_pct"] - 1e-9
    assert v99["cvar_parametric_pct"] >= v95["cvar_parametric_pct"] - 1e-9


def test_var_cvar_empty():
    res = var_mod.var_cvar([], conf=0.95)
    assert res["method"] == "empty"
    assert res["var_pct"] == 0.0 and res["cvar_pct"] == 0.0


def test_var_cvar_determinism():
    r = _synthetic_returns()
    a = var_mod.var_cvar(r, conf=0.95)
    b = var_mod.var_cvar(r, conf=0.95)
    assert a == b


def test_method_selection_threshold():
    """>=20 obs uses historical, fewer uses parametric."""
    big = var_mod.var_cvar(_synthetic_returns(50), conf=0.95)
    small = var_mod.var_cvar(_synthetic_returns(5), conf=0.95)
    assert big["method"] == "historical"
    assert small["method"] == "parametric_normal"


def test_principal_var_positive_for_t2_heavy():
    """A T2-heavy allocation must produce a meaningful (> 0) principal VaR."""
    alloc = {"morpho_steakhouse": 0.5, "euler_v2": 0.3, "maple": 0.2}
    p95 = var_mod.principal_var(alloc, conf=0.95)
    p99 = var_mod.principal_var(alloc, conf=0.99)
    assert p95["principal_var_pct"] > 0.0
    assert p99["principal_var_pct"] > 0.0
    assert p99["principal_var_pct"] >= p95["principal_var_pct"] - 1e-9
    assert p95["expected_loss_pct"] > 0.0


def test_principal_var_zero_for_cash():
    res = var_mod.principal_var({"cash": 1.0}, conf=0.95)
    assert res["principal_var_pct"] == 0.0
    assert res["expected_loss_pct"] == 0.0


def test_principal_var_t3_worse_than_t1():
    """Higher-tier (riskier) allocations carry a larger principal VaR."""
    t1 = var_mod.principal_var({"aave_v3": 1.0}, conf=0.99)
    t3 = var_mod.principal_var({"pendle": 1.0}, conf=0.99)
    assert t3["principal_var_pct"] > t1["principal_var_pct"]


def test_strategy_risk_structure_and_determinism():
    alloc = {"morpho_steakhouse": 0.6, "aave_v3": 0.2, "cash": 0.2}
    a = var_mod.strategy_risk(alloc)
    b = var_mod.strategy_risk(alloc)
    assert a == b  # deterministic
    for key in ("yield_var_95", "yield_cvar_95", "principal_var_95",
                "principal_var_99", "combined_annual_risk_pct", "tier_mix",
                "tail_risk_pct"):
        assert key in a
    # combined risk is the principal VaR @99 (the binding number)
    assert a["combined_annual_risk_pct"] == a["principal_var_99"]
    # principal VaR dwarfs yield VaR for this asset class
    assert a["principal_var_99"] >= a["yield_var_99"]


def test_yield_var_le_cvar_in_strategy_risk():
    alloc = {"morpho_steakhouse": 0.5, "euler_v2": 0.5}
    a = var_mod.strategy_risk(alloc)
    assert a["yield_cvar_95"] >= a["yield_var_95"] - 1e-9
    assert a["yield_var_99"] >= a["yield_var_95"] - 1e-9


def test_build_report_structure():
    rep = var_mod.build_report(write=False)
    for key in ("generated_at", "model", "version", "llm_forbidden",
                "validated_count", "strategies", "scenario_calibration"):
        assert key in rep
    assert rep["model"] == "tier1_var"
    assert rep["llm_forbidden"] is True
    assert isinstance(rep["strategies"], list)
    for s in rep["strategies"]:
        assert "id" in s and "risk" in s and "allocation" in s
        r = s["risk"]
        assert "principal_var_99" in r and "yield_var_95" in r
        assert r["combined_annual_risk_pct"] >= 0.0


def test_build_report_writes_atomically(tmp_path, monkeypatch):
    """build_report(write=True) writes a valid JSON file via tmp+replace."""
    import json
    out = tmp_path / "tier1_var.json"
    monkeypatch.setattr(var_mod, "_OUT", out)
    monkeypatch.setattr(var_mod, "_DATA", tmp_path)
    rep = var_mod.build_report(write=True)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["validated_count"] == rep["validated_count"]
    assert loaded["model"] == "tier1_var"
