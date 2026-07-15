"""
Deterministic invariants for Idea #9 — Causal Drawdown-State Overlay
(scripts/edge_causal_drawdown_overlay.py).

These are the HONEST claims the backtest makes, asserted as structural invariants
(orderings + signs), not brittle exact numbers, so they survive fixture refresh:

  1. run_analysis() is deterministic and returns the expected shape.
  2. The causal (no-oracle) controller BEATS static #3 risk-adjusted  → the edge is real.
  3. The oracle #7 (look-ahead) Calmar EXCEEDS the causal #9 Calmar    → look-ahead premium > 0
     (i.e. the arc's headline Calmar is NOT live-attainable).
  4. Causality: the best causal row actually enters DEFEND (regime detection fires).
  5. Weights are the SAME sleeves as #3/#7/#8 (only the control method changed).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2]
           / "scripts" / "edge_causal_drawdown_overlay.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("edge_causal_drawdown_overlay", _SCRIPT)
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
    except RuntimeError as exc:  # fixture unavailable in a stripped checkout
        pytest.skip(f"aggressive_lab fixture unavailable: {exc}")


def test_result_shape(result):
    for k in ("dates", "static", "oracle_defense", "sweep", "best"):
        assert k in result, f"missing key {k}"
    assert len(result["dates"]) > 300, "backtest window suspiciously short"
    assert result["sweep"], "empty parameter sweep"
    assert result["best"] is not None


def test_deterministic(mod, result):
    # re-run: same static/oracle/best Calmar (no RNG, no wall-clock)
    r2 = mod.run_analysis()
    assert r2["static"]["calmar"] == pytest.approx(result["static"]["calmar"], rel=1e-9)
    assert r2["oracle_defense"]["calmar"] == pytest.approx(
        result["oracle_defense"]["calmar"], rel=1e-9)
    assert r2["best"]["calmar"] == pytest.approx(result["best"]["calmar"], rel=1e-9)


def test_causal_edge_survives_beats_static(result):
    """The core honest claim: the no-oracle controller still beats static #3."""
    cal_static = result["static"]["calmar"]
    cal_best = result["best"]["calmar"]
    assert isinstance(cal_static, float) and isinstance(cal_best, float)
    assert cal_best > cal_static, (
        f"causal #9 Calmar {cal_best} did not beat static #3 {cal_static} — "
        "if this ever flips, the arc's edge does NOT survive causal detection (update the verdict)"
    )


def test_oracle_overstates_live_attainable(result):
    """Look-ahead premium is strictly positive: oracle #7 Calmar > causal #9 Calmar."""
    cal_oracle = result["oracle_defense"]["calmar"]
    cal_best = result["best"]["calmar"]
    assert isinstance(cal_oracle, float) and isinstance(cal_best, float)
    assert cal_oracle > cal_best, (
        "oracle #7 should exceed causal #9 (knowing crisis dates is an advantage); "
        "if not, the look-ahead-premium framing is wrong"
    )
    # the premium is economically meaningful, not a rounding artifact
    assert (cal_oracle - cal_best) > 1.0


def test_regime_detection_fires(result):
    """The best causal row must actually detect drawdown and enter DEFEND."""
    counts = result["best"]["counts"]
    assert counts.get("DEFEND", 0) > 0, "causal controller never de-risked — signal never fired"
    assert counts.get("CRUISE", 0) > 0, "controller never cruised — degenerate"


def test_weights_reuse_validated_sleeves(mod):
    assert mod.WEIGHTS_CRUISE == [0.25, 0.50, 0.25]   # #3
    assert mod.WEIGHTS_DEFEND == [0.05, 0.25, 0.70]   # #7
    assert mod.WEIGHTS_HARVEST == [0.40, 0.45, 0.15]  # #8
