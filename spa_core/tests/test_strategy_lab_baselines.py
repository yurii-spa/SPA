"""
spa_core/tests/test_strategy_lab_baselines.py — tests for the engine baselines wrapped as
Strategy-Lab strategies (spa_core/strategy_lab/strategies/baselines.py).

Coverage:
  - each baseline accrues correctly over N days at its APY (matches sleeve_yield.daily_yield);
  - RWAFloor: exactly the config floor APY, ZERO drawdown, never kills;
  - EngineA drawdown-stop kill fires via the canonical risk_limits() threshold (fail-closed);
  - build_baselines() returns 4 initialised strategies at the right capital;
  - determinism (same input + state → same output);
  - offline-safe (sleeve_yield live-file reads are guarded; no exception leaks).

stdlib + pytest only. Deterministic, hermetic (no network, no required live files).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab import config as lab_config
from spa_core.paper_trading import sleeve_yield
from spa_core.strategy_lab.strategies import baselines
from spa_core.strategy_lab.strategies.baselines import (
    EngineA,
    EngineB,
    EngineC,
    RWAFloor,
    build_baselines,
)


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def _snap(date="2026-06-10", defi_apy=None):
    return MarketSnapshot(date=date, defi_apy=defi_apy or {})


def _accrue_expected(capital, apy_pct, days):
    """Reproduce N days of the SAME compounding loop the wrapper uses."""
    eq = capital
    for _ in range(days):
        eq += sleeve_yield.daily_yield(eq, apy_pct)
    return eq


# ──────────────────────────────────────────────────────────────────────────────
# import smoke
# ──────────────────────────────────────────────────────────────────────────────
def test_module_imports_clean():
    assert hasattr(baselines, "build_baselines")
    for cls in (EngineA, EngineB, EngineC, RWAFloor):
        assert cls.mandate == "stable"


def test_baseline_identity_flags():
    # The three engines ARE production baselines (not advisory); RWAFloor is a benchmark.
    assert EngineA().is_advisory is False
    assert EngineB().is_advisory is False
    assert EngineC().is_advisory is False
    assert RWAFloor().is_advisory is True
    assert EngineA.id == "engine_a"
    assert EngineB.id == "engine_b"
    assert EngineC.id == "engine_c"
    assert RWAFloor.id == "rwa_floor"


# ──────────────────────────────────────────────────────────────────────────────
# RWAFloor — exactly the floor APY, zero drawdown, never kills
# ──────────────────────────────────────────────────────────────────────────────
def test_rwa_floor_accrues_exactly_floor_apy():
    floor = lab_config.rwa_floor_apy_pct()
    s = RWAFloor()
    s.init(100_000.0, {"apy_pct": floor})
    days = 30
    for d in range(days):
        s.step(_snap(date=f"2026-06-{10 + d:02d}"))
    expected = _accrue_expected(100_000.0, floor, days)
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_rwa_floor_independent_of_market():
    """Risk-free → market APY must NOT change RWAFloor's accrual."""
    floor = lab_config.rwa_floor_apy_pct()
    a = RWAFloor(); a.init(100_000.0, {"apy_pct": floor})
    b = RWAFloor(); b.init(100_000.0, {"apy_pct": floor})
    for d in range(10):
        a.step(_snap())                                   # empty market
        b.step(_snap(defi_apy={"x": 0.20, "y": 0.25}))    # rich market (20%/25%)
    assert a.equity() == pytest.approx(b.equity(), abs=1e-9)


def test_rwa_floor_zero_drawdown_and_never_kills():
    s = RWAFloor()
    s.init(100_000.0, {"apy_pct": lab_config.rwa_floor_apy_pct()})
    for _ in range(60):
        s.step(_snap())
        kr = s.kill_check(_snap())
        assert kr.triggered is False
    m = s.metrics()
    assert m.max_drawdown_pct == pytest.approx(0.0, abs=1e-12)
    assert m.volatility_pct == pytest.approx(0.0)


# ──────────────────────────────────────────────────────────────────────────────
# EngineA — accrues at blended stable APY from market.defi_apy; config fallback
# ──────────────────────────────────────────────────────────────────────────────
def test_engine_a_accrues_at_market_blended_apy():
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})
    # defi_apy is decimal per the MarketSnapshot contract → 0.05 == 5% APY.
    market = _snap(defi_apy={"aave": 0.05, "compound": 0.05})
    days = 20
    for _ in range(days):
        s.step(market)
    expected = _accrue_expected(100_000.0, 5.0, days)  # blended median = 5%
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_engine_a_falls_back_to_config_floor_when_no_market():
    """No defi_apy supplied (offline) → accrue at config rwa_floor, not zero."""
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})
    days = 15
    for _ in range(days):
        s.step(_snap(defi_apy={}))
    expected = _accrue_expected(100_000.0, lab_config.rwa_floor_apy_pct(), days)
    assert s.equity() == pytest.approx(expected, abs=1e-6)
    assert s.equity() > 100_000.0  # actually accrued (not flat)


def test_engine_a_drawdown_stop_kill_via_risk_limits():
    """Force a drawdown past the canonical max_drawdown_stop and confirm the kill fires."""
    stop = lab_config.risk_limits()["max_drawdown_stop"]  # 0.05
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})
    # Drive a peak, then push equity below peak by MORE than the stop fraction.
    s._peak = 100_000.0
    s._equity = 100_000.0 * (1.0 - (stop + 0.01))  # 6% drawdown when stop is 5%
    kr = s.kill_check(_snap())
    assert kr.triggered is True
    assert "drawdown" in kr.reason
    # Once killed the book is flat (no further accrual).
    eq_before = s.equity()
    s.step(_snap(defi_apy={"aave": 0.10}))
    assert s.equity() == pytest.approx(eq_before, abs=1e-9)


def test_engine_a_no_kill_below_stop():
    stop = lab_config.risk_limits()["max_drawdown_stop"]
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})
    s._peak = 100_000.0
    s._equity = 100_000.0 * (1.0 - (stop - 0.01))  # 4% drawdown < 5% stop
    kr = s.kill_check(_snap())
    assert kr.triggered is False


def test_kill_check_fail_closed_on_error(monkeypatch):
    """If risk_limits() raises, kill_check must fail CLOSED (triggered=True)."""
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})

    def _boom():
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(lab_config, "risk_limits", _boom)
    kr = s.kill_check(_snap())
    assert kr.triggered is True
    assert "fail-closed" in kr.reason


# ──────────────────────────────────────────────────────────────────────────────
# EngineB / EngineC — reproduce sleeve_yield accrual; offline-safe
# ──────────────────────────────────────────────────────────────────────────────
def test_engine_b_accrues_at_sleeve_hy_apy_offline():
    """No market band → EngineB uses sleeve_yield.hy_target_apy_pct() (its floor offline)."""
    hy_apy = sleeve_yield.hy_target_apy_pct()  # HY_FLOOR offline (no live file)
    s = EngineB()
    s.init(20_000.0, {"capital_usd": 20_000})
    days = 30
    for _ in range(days):
        s.step(_snap(defi_apy={}))
    expected = _accrue_expected(20_000.0, hy_apy, days)
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_engine_b_prefers_market_hy_band():
    """When the live producer only has its floor, a supplied HY band drives accrual."""
    s = EngineB()
    s.init(20_000.0, {"capital_usd": 20_000})
    # 0.12 decimal == 12% > HY_BAND_MIN (6%).
    market = _snap(defi_apy={"pendle": 0.12, "morpho": 0.12})
    days = 10
    for _ in range(days):
        s.step(market)
    # Only asserts the band path when the live producer is at its floor (offline default).
    if abs(sleeve_yield.hy_target_apy_pct() - sleeve_yield.HY_FLOOR) < 1e-9:
        expected = _accrue_expected(20_000.0, 12.0, days)
        assert s.equity() == pytest.approx(expected, abs=1e-6)
    else:
        assert s.equity() > 20_000.0  # live data present: still accrues meaningfully


def test_engine_c_accrues_at_sleeve_lp_apy_offline():
    lp_apy = sleeve_yield.lp_target_apy_pct()  # LP_FLOOR offline
    s = EngineC()
    s.init(10_000.0, {"capital_usd": 10_000})
    days = 30
    for _ in range(days):
        s.step(_snap(defi_apy={}))
    expected = _accrue_expected(10_000.0, lp_apy, days)
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_engine_c_il_gap_documented_in_metrics():
    s = EngineC()
    s.init(10_000.0, {"capital_usd": 10_000})
    s.step(_snap(defi_apy={}))
    m = s.metrics()
    assert m.extra["il_modeled"] is False
    assert m.extra["il_drawdown_pct"] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# positions / metrics shape
# ──────────────────────────────────────────────────────────────────────────────
def test_single_synthetic_position_tracks_equity():
    s = EngineB()
    s.init(20_000.0, {"capital_usd": 20_000})
    for _ in range(5):
        s.step(_snap(defi_apy={}))
    pos = s.positions()
    assert len(pos) == 1
    assert pos[0].asset == "engine_b"
    assert pos[0].kind == "lending"
    assert pos[0].notional_usd == pytest.approx(s.equity(), abs=1e-6)


def test_metrics_net_apy_partial_is_sane():
    s = EngineA()
    s.init(100_000.0, {"capital_usd": 100_000})
    for _ in range(365):
        s.step(_snap(defi_apy={"aave": 0.05}))
    m = s.metrics()
    # ~5% APY accrued over a full year (compounding → a touch above 5%).
    assert m.net_apy_pct == pytest.approx(5.0, abs=0.3)


# ──────────────────────────────────────────────────────────────────────────────
# determinism
# ──────────────────────────────────────────────────────────────────────────────
def test_determinism_same_input_same_output():
    def run():
        s = EngineA()
        s.init(100_000.0, {"capital_usd": 100_000})
        for d in range(40):
            s.step(_snap(date=f"2026-06-{(d % 28) + 1:02d}", defi_apy={"aave": 0.05}))
        return s.equity()

    assert run() == run()


# ──────────────────────────────────────────────────────────────────────────────
# build_baselines factory
# ──────────────────────────────────────────────────────────────────────────────
def test_build_baselines_returns_four_initialised_at_right_capital():
    out = build_baselines()
    assert set(out.keys()) == {"engine_a", "engine_b", "engine_c", "rwa_floor"}
    assert out["engine_a"].equity() == pytest.approx(100_000.0)
    assert out["engine_b"].equity() == pytest.approx(20_000.0)
    assert out["engine_c"].equity() == pytest.approx(10_000.0)
    assert out["rwa_floor"].equity() == pytest.approx(100_000.0)
    for s in out.values():
        assert len(s.positions()) == 1


def test_build_baselines_accepts_explicit_config():
    cfg = lab_config.load_config()
    out = build_baselines(cfg)
    assert out["engine_b"].equity() == pytest.approx(20_000.0)


def test_build_baselines_fail_closed_on_missing_block():
    bad = {"strategies": {"engine_a": {"capital_usd": 1}}}  # missing engine_b/c/rwa_floor
    with pytest.raises(lab_config.ConfigError):
        build_baselines(bad)


def test_build_baselines_fail_closed_on_missing_capital():
    bad = {
        "strategies": {
            "engine_a": {},  # no capital_usd
            "engine_b": {"capital_usd": 20000},
            "engine_c": {"capital_usd": 10000},
            "rwa_floor": {"capital_usd": 100000, "apy_pct": 4.5},
        }
    }
    with pytest.raises(lab_config.ConfigError):
        build_baselines(bad)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
