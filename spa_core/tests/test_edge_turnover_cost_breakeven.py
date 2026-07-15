"""
Deterministic invariants for Idea #10 — Turnover-Cost Break-Even
(scripts/edge_turnover_cost_breakeven.py).

Honest claims asserted as structural invariants (not brittle exact numbers):

  1. run_analysis() is deterministic and returns the expected shape.
  2. At ZERO cost the causal overlay reproduces the #9 edge (Calmar > static #3).
  3. MONOTONICITY: net Calmar is non-increasing as cost rises. This is the critical
     regression guard — the FIRST implementation charged cost on the equity that drives
     the drawdown signal, creating a spurious switch-cascade (a cliff + chaotic,
     non-monotone Calmar). The fix decides the regime on the gross path and treats cost
     as a separate drag; that MUST produce a monotone curve.
  4. The overlay is RARE-SWITCHING (few switches over the backtest) — the property that
     makes it cost-robust.
  5. Break-even cost, if within the grid, is strictly positive.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2]
           / "scripts" / "edge_turnover_cost_breakeven.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("edge_turnover_cost_breakeven", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def result(mod):
    try:
        return mod.run_analysis()
    except RuntimeError as exc:
        pytest.skip(f"aggressive_lab fixture unavailable: {exc}")


def test_shape(result):
    for k in ("dates", "static", "rows", "breakeven_bps"):
        assert k in result
    assert len(result["rows"]) >= 5
    assert result["rows"][0]["cost_bps"] == 0.0


def test_deterministic(mod, result):
    r2 = mod.run_analysis()
    for a, b in zip(result["rows"], r2["rows"]):
        assert a["calmar"] == pytest.approx(b["calmar"], rel=1e-9)


def test_zero_cost_reproduces_edge(result):
    """At 0 cost the overlay must beat static #3 (the #9 edge, pre-cost)."""
    cal0 = result["rows"][0]["calmar"]
    cal_static = result["static"]["calmar"]
    assert isinstance(cal0, float) and isinstance(cal_static, float)
    assert cal0 > cal_static


def test_calmar_monotone_non_increasing_in_cost(result):
    """
    REGRESSION GUARD: cost-as-drag on a fixed weight path must give a MONOTONE curve.
    A non-monotone Calmar means the pathological cost→signal feedback has returned.
    """
    cals = [r["calmar"] for r in result["rows"]]
    for i in range(1, len(cals)):
        prev, cur = cals[i - 1], cals[i]
        if isinstance(prev, float) and isinstance(cur, float):
            assert cur <= prev + 1e-9, (
                f"net Calmar rose from {prev} to {cur} as cost increased "
                f"(cost {result['rows'][i-1]['cost_bps']}→{result['rows'][i]['cost_bps']}bp) "
                "— cost-feedback pathology re-introduced"
            )


def test_rare_switching(result):
    """The cost-robustness rests on switching rarely."""
    n_sw = result["rows"][0]["n_switches"]
    assert 0 < n_sw < 50, f"expected a rare-switching overlay, got {n_sw} switches"


def test_breakeven_positive_if_present(result):
    be = result["breakeven_bps"]
    if be is not None:
        assert be > 0.0
