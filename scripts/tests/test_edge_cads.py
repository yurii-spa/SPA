"""
#119 CADS — Crisis-Adaptive Drawdown Stop — pinned tests on the synthetic fixture.

Each test is a positive control: plant the property, check the instrument sees it;
or plant a violation, check the instrument refuses / does not degrade.

Causal invariants verified by mutation: the stop trigger checks PAST HWM vs TODAY's
price; the reallocation targets are chosen from rolling Calmar computed on past data only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_t_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load("edge_cads")


# ── Basic sanity ──────────────────────────────────────────────────────────────

def test_run_returns_required_keys():
    r = C.run_cads()
    for key in ("apy_bt", "max_dd_bt", "calmar_bt",
                "baseline_apy_bt", "baseline_max_dd_bt", "baseline_calmar_bt",
                "stop_events", "reentry_events", "portfolio_curve", "n_days"):
        assert key in r, f"Missing key: {key}"


def test_backtest_length_matches_fixture():
    r = C.run_cads()
    assert r["n_days"] == 700, f"Expected 700 backtest days, got {r['n_days']}"


def test_portfolio_curve_starts_at_one():
    r = C.run_cads()
    assert abs(r["portfolio_curve"][0] - 1.0) < 1e-6, \
        f"Portfolio must start normalised to 1.0, got {r['portfolio_curve'][0]}"


# ── Core mechanism: CADS beats equal-weight baseline ─────────────────────────

def test_cads_calmar_beats_equal_weight_baseline():
    """CADS Calmar must be strictly better than the naive equal-weight basket."""
    r = C.run_cads()
    assert r["calmar_bt"] > r["baseline_calmar_bt"], (
        f"CADS Calmar {r['calmar_bt']} should exceed baseline {r['baseline_calmar_bt']}"
    )


def test_cads_reduces_max_drawdown_vs_baseline():
    """The per-strategy stop must reduce portfolio max-drawdown."""
    r = C.run_cads()
    assert r["max_dd_bt"] < r["baseline_max_dd_bt"], (
        f"CADS maxDD {r['max_dd_bt']}% should be less than baseline {r['baseline_max_dd_bt']}%"
    )


def test_cads_apy_positive_when_baseline_negative():
    """On the fixture the naive equal-weight APY is negative; CADS must be positive."""
    r = C.run_cads()
    assert r["baseline_apy_bt"] < 0, "Precondition: baseline APY should be negative on this fixture"
    assert r["apy_bt"] > 0, f"CADS APY should be positive, got {r['apy_bt']}%"


# ── Stop events occur for the expected strategies ─────────────────────────────

def test_variant_d_stopped_in_eth_crash():
    """variant_d (18% stress hit) must trigger a stop in the eth_crash_2024_08 window."""
    r = C.run_cads()
    stopped_ids = [sid for _, sid, _ in r["stop_events"]]
    assert "variant_d" in stopped_ids, "variant_d must be stopped during eth_crash window"


def test_leverage_loop_stopped_in_usde_unwind():
    """leverage_loop (28% stress hit) must trigger a stop in usde_unwind_2025_10."""
    r = C.run_cads()
    stopped_ids = [sid for _, sid, _ in r["stop_events"]]
    assert "leverage_loop" in stopped_ids, "leverage_loop must be stopped during usde_unwind"


def test_lrt_carry_stopped_in_rseth_depeg():
    """lrt_carry (22% stress hit) must trigger a stop in rseth_depeg_2026_04."""
    r = C.run_cads()
    stopped_ids = [sid for _, sid, _ in r["stop_events"]]
    assert "lrt_carry" in stopped_ids, "lrt_carry must be stopped during rseth_depeg"


# ── Causality: stop must not precede the strategy's own HWM ──────────────────

def test_stop_dd_is_positive_fraction():
    """Every stop event must record a positive drawdown (strategy is below its HWM)."""
    r = C.run_cads()
    for date, sid, dd_pct in r["stop_events"]:
        assert dd_pct > 0, f"Stop on {date} for {sid} has non-positive DD {dd_pct}"


# ── Helpers: cagr and max_drawdown ───────────────────────────────────────────

def test_cagr_flat_line_is_zero():
    assert C.cagr(1.0, 1.0, 365) == pytest.approx(0.0, abs=1e-9)


def test_cagr_doubles_in_one_year():
    assert C.cagr(1.0, 2.0, 365) == pytest.approx(1.0, rel=1e-6)


def test_max_drawdown_monotone_rise_is_zero():
    assert C.max_drawdown([1.0, 1.1, 1.2, 1.3]) == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_single_drop():
    # Falls from 1.0 to 0.8: DD = 20%
    assert C.max_drawdown([1.0, 0.8]) == pytest.approx(0.2, rel=1e-6)


# ── Rolling Calmar: no lookahead (causal) ─────────────────────────────────────

def test_rolling_calmar_uses_only_past_data():
    """Inserting a future shock AFTER day_idx must not change the Calmar for day_idx."""
    prices_no_shock = [1.0 + i * 0.001 for i in range(100)]
    prices_with_future_shock = prices_no_shock[:] + [0.5]  # shock at index 100, beyond idx=99

    cal_no_shock = C.rolling_calmar(prices_no_shock, 99, 60)
    cal_with_future = C.rolling_calmar(prices_with_future_shock, 99, 60)
    # Both must be identical — the future shock at index 100 must not affect day 99
    assert cal_no_shock == pytest.approx(cal_with_future, rel=1e-9)


def test_rolling_calmar_is_zero_for_short_window():
    # Fewer than 5 days → returns 0.0 (not enough data)
    assert C.rolling_calmar([1.0, 1.1, 1.0], 2, 60) == pytest.approx(0.0, abs=1e-9)


# ── Re-entry events are valid ─────────────────────────────────────────────────

def test_reentry_occurs_after_stop():
    """Every re-entry must be for a strategy that was previously stopped."""
    r = C.run_cads()
    stopped_ids = {sid for _, sid, _ in r["stop_events"]}
    reentered_ids = {sid for _, sid, _ in r["reentry_events"]}
    assert reentered_ids.issubset(stopped_ids), \
        f"Re-entry for strategy not in stopped set: {reentered_ids - stopped_ids}"


def test_reentry_dd_is_below_re_entry_pct():
    """Re-entry DD must satisfy the hysteresis condition (<= RE_ENTRY_PCT)."""
    r = C.run_cads()
    threshold = r["re_entry_pct"] * 100  # convert to percent
    for date, sid, dd_pct in r["reentry_events"]:
        assert dd_pct <= threshold + 0.1, (  # tiny float tolerance
            f"Re-entry on {date} for {sid}: DD={dd_pct}% exceeds threshold {threshold}%"
        )
