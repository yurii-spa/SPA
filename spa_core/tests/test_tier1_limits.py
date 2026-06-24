"""Tests for spa_core/backtesting/tier1/limits.py — institutional limits overlay."""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.backtesting.tier1 import limits as lim


# No TVL map → single-pool-liquidity check is skipped, isolating the weight/HHI/cash limits.
_NO_TVL: dict = {}


def test_clean_allocation_passes():
    # 4 T1/T2 protocols + ample cash; diversified → no breach.
    alloc = {"aave_v3": 0.35, "compound_v3": 0.20, "spark_susds": 0.20,
             "morpho_steakhouse": 0.15, "cash": 0.10}
    r = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    assert r["passes"] is True
    assert r["breaches"] == []
    assert r["cash_weight"] >= lim.MIN_CASH
    assert r["hhi"] <= lim.HHI_MAX


def test_over_concentration_breaches_per_protocol_and_hhi():
    alloc = {"aave_v3": 0.90, "cash": 0.10}
    r = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    assert r["passes"] is False
    kinds = {b["limit"] for b in r["breaches"]}
    assert "per_protocol_max" in kinds   # 90% > 40% T1 cap
    assert "hhi_max" in kinds            # HHI ~0.81 > 0.25
    assert r["max_protocol_weight"] > 0.40
    assert r["hhi"] > lim.HHI_MAX


def test_low_cash_breaches():
    # spread across enough T1 protocols so only the cash buffer fails.
    alloc = {"aave_v3": 0.34, "compound_v3": 0.33, "spark_susds": 0.31, "cash": 0.02}
    r = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    kinds = {b["limit"] for b in r["breaches"]}
    assert "min_cash" in kinds
    assert r["passes"] is False
    cash_breach = next(b for b in r["breaches"] if b["limit"] == "min_cash")
    assert cash_breach["value"] < lim.MIN_CASH


def test_t2_aggregate_over_50_breaches():
    # all-T2, each ≤20% per-protocol cap, but aggregate 60% > 50% T2 cap.
    alloc = {"morpho_steakhouse": 0.20, "euler_v2": 0.20, "yearn_v3": 0.20, "cash": 0.40}
    r = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    kinds = {b["limit"] for b in r["breaches"]}
    assert "t2_aggregate_max" in kinds
    t2 = next(b for b in r["breaches"] if b["limit"] == "t2_aggregate_max")
    assert t2["value"] > lim.TIER_AGGREGATE_MAX["T2"]
    # none of the per-protocol caps should fire here
    assert "per_protocol_max" not in kinds


def test_single_pool_liquidity_breach_with_tvl():
    # tiny pool: 30% of $100k = $30k > 2% of $1M TVL ($20k) → liquidity breach.
    alloc = {"aave_v3": 0.30, "compound_v3": 0.30, "spark_susds": 0.30, "cash": 0.10}
    tvl = {"aave_v3": 1_000_000.0, "compound_v3": 1e12, "spark_susds": 1e12}
    r = lim.check_allocation(alloc, aum_usd=100000, tvl_map=tvl)
    liq = [b for b in r["breaches"] if b["limit"] == "single_pool_liquidity"]
    assert any(b["protocol"] == "aave_v3" for b in liq)


def test_usd_amount_allocation_normalized():
    # raw USD amounts must normalize identically to fractions.
    alloc_usd = {"aave_v3": 35000, "compound_v3": 20000, "spark_susds": 20000,
                 "morpho_steakhouse": 15000, "cash": 10000}
    alloc_frac = {"aave_v3": 0.35, "compound_v3": 0.20, "spark_susds": 0.20,
                  "morpho_steakhouse": 0.15, "cash": 0.10}
    a = lim.check_allocation(alloc_usd, tvl_map=_NO_TVL)
    b = lim.check_allocation(alloc_frac, tvl_map=_NO_TVL)
    assert a["hhi"] == b["hhi"]
    assert a["tier_weights"] == b["tier_weights"]
    assert a["cash_weight"] == b["cash_weight"]


def test_implicit_cash_from_shortfall():
    # no cash key, weights sum to 0.5 → remainder is NOT auto-cash (normalized to 1.0).
    # Here values are fractions summing <1; _normalize divides by total so cash stays 0.
    alloc = {"aave_v3": 0.25, "compound_v3": 0.25}
    r = lim.check_allocation(alloc, tvl_map=_NO_TVL)
    # normalized to 0.5/0.5 → cash 0 → min_cash breach
    assert r["cash_weight"] == 0.0
    assert any(b["limit"] == "min_cash" for b in r["breaches"])


def test_determinism():
    alloc = {"aave_v3": 0.30, "compound_v3": 0.20, "maple": 0.15, "cash": 0.35}
    r1 = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    r2 = lim.check_allocation(alloc, aum_usd=100000, tvl_map=_NO_TVL)
    assert r1 == r2


def test_hhi_formula():
    # 50/50 two-protocol → HHI = 0.25 + 0.25 = 0.5; cash excluded.
    r = lim.check_allocation({"aave_v3": 0.5, "compound_v3": 0.5}, tvl_map=_NO_TVL)
    assert r["hhi"] == 0.5
    assert r["effective_holdings"] == 2.0


def test_build_report_structure():
    rep = lim.build_report(write=False)
    for key in ("generated_at", "model", "llm_forbidden", "is_gate", "version",
                "limits", "aum_usd", "current_portfolio", "validated_strategies", "summary"):
        assert key in rep, key
    assert rep["is_gate"] is False
    assert rep["llm_forbidden"] is True
    cur = rep["current_portfolio"]
    for key in ("passes", "breaches", "hhi", "tier_weights", "max_protocol_weight",
                "breach_count", "cash_weight"):
        assert key in cur, key
    assert isinstance(rep["validated_strategies"], list)
    s = rep["summary"]
    assert s["strategies_checked"] == len(rep["validated_strategies"])
    assert 0 <= s["strategies_passing"] <= s["strategies_checked"]


def test_build_report_writes_atomically(tmp_path, monkeypatch):
    out = tmp_path / "tier1_limits.json"
    monkeypatch.setattr(lim, "_OUT", out)
    monkeypatch.setattr(lim, "_DATA", tmp_path)
    rep = lim.build_report(write=True)
    assert out.exists()
    import json
    on_disk = json.loads(out.read_text())
    assert on_disk["version"] == rep["version"]
    # no leftover temp files
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tier1_limits_")]
    assert leftovers == []
