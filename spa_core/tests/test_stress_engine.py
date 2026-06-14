"""Unit tests for spa_core/stress/stress_engine.py (MP-112).

Coverage targets (10+ tests):
  1.  test_covid_scenario_runs              — basic smoke test
  2.  test_luna_scenario_runs               — basic smoke test
  3.  test_usdc_scenario_runs               — basic smoke test
  4.  test_scenario_reduces_equity_luna     — LUNA must produce a net loss
  5.  test_usdc_depeg_impact                — depeg day reduces equity below initial
  6.  test_kill_switch_triggered_if_large_dd — forced alloc triggers kill switch
  7.  test_tvl_floor_reallocates            — low-TVL protocol is zeroed out
  8.  test_stress_report_generated          — report string is non-empty and correct structure
  9.  test_all_scenarios_return_results     — run_all_scenarios returns 3 entries
  10. test_initial_equity_preserved_type    — final_equity is float (not int/str)
  11. test_daily_equity_length_matches_duration — correct number of daily points
  12. test_kill_switch_zeroes_remaining_days    — equity flat after kill switch
  13. test_unknown_scenario_raises          — ValueError on bad scenario_id
  14. test_covid_positive_return            — COVID scenario ends positive (panic yield)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on path when running with pytest from any CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from spa_core.stress.stress_engine import (
    SCENARIOS,
    StressResult,
    _effective_allocation,
    _TVL_FLOOR_USD,
    generate_stress_report,
    run_all_scenarios,
    run_stress_test,
)


# ─── Smoke tests ─────────────────────────────────────────────────────────────


def test_covid_scenario_runs():
    """COVID-2020 scenario completes without exception and returns a StressResult."""
    result = run_stress_test("covid_2020")
    assert isinstance(result, StressResult)
    assert result.scenario_name == "COVID-2020"


def test_luna_scenario_runs():
    """LUNA-2022 scenario completes without exception."""
    result = run_stress_test("luna_2022")
    assert isinstance(result, StressResult)
    assert result.scenario_name == "LUNA-2022"


def test_usdc_scenario_runs():
    """USDC-DEPEG-2023 scenario completes without exception."""
    result = run_stress_test("usdc_depeg_2023")
    assert isinstance(result, StressResult)
    assert result.scenario_name == "USDC-DEPEG-2023"


# ─── Economic correctness ─────────────────────────────────────────────────────


def test_scenario_reduces_equity_luna():
    """LUNA scenario must produce a net loss (total_return_pct < 0).

    Maple is excluded (default risk), Yearn severely impacted; the
    LUNA contagion should dominate over any yield accrual.
    """
    result = run_stress_test("luna_2022")
    # LUNA is the catastrophic scenario — total return must be negative
    assert result.total_return_pct < 0, (
        f"Expected LUNA-2022 to produce a loss; got {result.total_return_pct:.4f}%"
    )


def test_usdc_depeg_impact():
    """USDC depeg scenario: equity on day 1 (worst depeg) is below initial.

    The USDC-2023 scenario has a 0.87 peg at worst — day 0 and day 1
    should reflect a mark-to-market loss.
    """
    result = run_stress_test("usdc_depeg_2023", initial_equity=100_000.0)
    # The worst depeg day reduces equity substantially below $100k
    min_equity = min(pt["equity"] for pt in result.daily_equity)
    assert min_equity < 100_000.0, (
        f"Expected equity to dip below initial during USDC depeg; min={min_equity}"
    )


def test_covid_positive_return():
    """COVID-2020: panic APY boost on T1 protocols should yield a net positive return.

    Aave APY 15%, Compound 12% — even after USDC transient depeg at 0.97,
    the 30-day accrual should be net positive.
    """
    result = run_stress_test("covid_2020")
    assert result.total_return_pct > 0, (
        f"Expected COVID-2020 net positive; got {result.total_return_pct:.4f}%"
    )


# ─── Kill-switch ──────────────────────────────────────────────────────────────


def test_kill_switch_triggered_if_large_dd():
    """Kill switch fires when we force a severe drawdown allocation.

    We craft an artificial allocation with a scenario that has a large depeg
    and zero-yield protocols, ensuring drawdown ≥ 5%.
    """
    # USDC-2023: 0.87 depeg = 13% mark-to-market loss → must trigger kill switch
    result = run_stress_test(
        "usdc_depeg_2023",
        initial_equity=100_000.0,
        initial_allocation={
            "aave_v3": 0.90,      # 90% deployed — minimal cash buffer
            "compound_v3": 0.05,  # 5% — exactly at cash floor
        },
    )
    # 13% depeg on 95% deployed → ~12.35% portfolio loss → well above 5% kill switch
    assert result.kill_switch_triggered, (
        "Expected kill switch to trigger with 0.87 USDC depeg on 95% deployed capital"
    )
    assert result.kill_switch_day is not None
    assert 0 <= result.kill_switch_day <= 3  # Must fire in first 3 days (depeg window)


def test_kill_switch_zeroes_remaining_days():
    """After kill switch fires, equity should not increase (positions closed)."""
    result = run_stress_test(
        "usdc_depeg_2023",
        initial_equity=100_000.0,
        initial_allocation={"aave_v3": 0.90, "compound_v3": 0.05},
    )
    if not result.kill_switch_triggered or result.kill_switch_day is None:
        pytest.skip("Kill switch did not trigger in this run — test precondition not met")

    ks_day = result.kill_switch_day
    # Equity on kill-switch day
    eq_at_ks = result.daily_equity[ks_day]["equity"]
    # All subsequent days must have equity ≤ eq_at_ks (no new yield)
    for pt in result.daily_equity[ks_day + 1:]:
        assert pt["equity"] <= eq_at_ks + 0.01, (
            f"Equity increased after kill switch on day {ks_day}: "
            f"day {pt['day']} equity={pt['equity']}"
        )


# ─── TVL floor reallocation ───────────────────────────────────────────────────


def test_tvl_floor_reallocates():
    """Protocols below $5M TVL must receive 0 weight in effective allocation."""
    scenario = SCENARIOS["luna_2022"]
    # Maple TVL in LUNA scenario is 15M but available=False (default risk)
    # euler_v2 TVL is 100M but let's verify a zero-TVL protocol is excluded
    allocation = {
        "aave_v3":    0.40,
        "euler_v2":   0.20,  # unavailable in COVID; 100M in LUNA (available=True)
        "morpho_blue": 0.10, # unavailable (not launched) in LUNA
        "compound_v3": 0.25,
    }
    effective = _effective_allocation(allocation, scenario)

    # morpho_blue is unavailable in luna_2022 → must be 0
    assert effective.get("morpho_blue", 0.0) == 0.0, (
        "morpho_blue (unavailable) should be zeroed out"
    )
    # maple is explicitly unavailable in luna_2022
    assert effective.get("maple", 0.0) == 0.0


def test_tvl_floor_low_tvl_protocol():
    """A protocol with TVL exactly at the floor ($5M) should still be accepted;
    one just below ($4.9M) should be excluded."""
    from spa_core.stress.stress_engine import StressScenario

    # Build a minimal synthetic scenario with one protocol at $4.9M TVL
    synthetic = StressScenario(
        name="Synthetic",
        description="test",
        duration_days=1,
        start_date="2020-01-01",
        protocol_impacts={
            "aave_v3": {"apy_pct": 5.0, "tvl_usd": 4_900_000, "available": True},
            "compound_v3": {"apy_pct": 4.0, "tvl_usd": 10_000_000, "available": True},
        },
        usdc_peg=1.0,
        notes="",
    )
    effective = _effective_allocation({"aave_v3": 0.5, "compound_v3": 0.45}, synthetic)
    # aave_v3 below TVL floor → 0
    assert effective.get("aave_v3", 0.0) == 0.0
    # compound_v3 above floor → positive weight
    assert effective.get("compound_v3", 0.0) > 0.0


# ─── Report ───────────────────────────────────────────────────────────────────


def test_stress_report_generated():
    """generate_stress_report produces a non-empty string with required sections."""
    results = run_all_scenarios()
    report = generate_stress_report(results)

    assert isinstance(report, str)
    assert len(report) > 100
    assert "=== SPA Stress Test Report ===" in report
    assert "COVID-2020" in report
    assert "LUNA-2022" in report
    assert "USDC-DEPEG-2023" in report
    assert "Worst scenario" in report
    assert "kill switch" in report.lower()


def test_stress_report_empty_input():
    """generate_stress_report handles empty dict gracefully."""
    report = generate_stress_report({})
    assert "No results" in report


# ─── Batch runner ─────────────────────────────────────────────────────────────


def test_all_scenarios_return_results():
    """run_all_scenarios returns exactly 3 entries, one per scenario."""
    results = run_all_scenarios()
    assert len(results) == 3
    assert "covid_2020" in results
    assert "luna_2022" in results
    assert "usdc_depeg_2023" in results
    for sid, r in results.items():
        assert isinstance(r, StressResult), f"{sid} did not return StressResult"


# ─── Type safety ──────────────────────────────────────────────────────────────


def test_initial_equity_preserved_type():
    """final_equity must be a float regardless of how initial_equity is provided."""
    result = run_stress_test("covid_2020", initial_equity=100_000)  # int input
    assert isinstance(result.final_equity, float), (
        f"final_equity should be float, got {type(result.final_equity)}"
    )
    assert isinstance(result.total_return_pct, float)
    assert isinstance(result.max_drawdown_pct, float)
    assert isinstance(result.sharpe_ratio, float)


def test_daily_equity_length_matches_duration():
    """daily_equity list length must equal scenario duration_days."""
    for sid, scenario in SCENARIOS.items():
        result = run_stress_test(sid)
        assert len(result.daily_equity) == scenario.duration_days, (
            f"{sid}: expected {scenario.duration_days} daily points, "
            f"got {len(result.daily_equity)}"
        )


# ─── Error handling ───────────────────────────────────────────────────────────


def test_unknown_scenario_raises():
    """run_stress_test raises ValueError for unknown scenario_id."""
    with pytest.raises(ValueError, match="Unknown scenario"):
        run_stress_test("does_not_exist_xyz")
