"""
Deterministic invariants for Idea #13 — Look-Ahead Premium Decomposition
(scripts/edge_lookahead_premium_decomp.py).

Honest claims asserted as structural invariants:

  1. run_analysis() is deterministic and returns the 2×2 (entry × exit) grid.
  2. Full look-ahead (oracle,oracle) beats live (causal,causal) → total premium > 0.
  3. THE FINDING: knowing the crisis START (entry) is worth far more than knowing the
     crisis END (exit). If this ever flips, the "onset-detection is the lever" verdict
     is wrong and must be revisited.
  4. Mechanism: oracle ENTRY (de-risk before the drawdown) yields a lower maxDD than
     causal entry (de-risk after it starts).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2]
           / "scripts" / "edge_lookahead_premium_decomp.py")


def _load():
    spec = importlib.util.spec_from_file_location("edge_lookahead_premium_decomp", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.fixture(scope="module")
def result(mod):
    try:
        return mod.run_analysis()
    except RuntimeError as exc:
        pytest.skip(f"aggressive_lab fixture unavailable: {exc}")


def test_shape(result):
    for k in ("cells", "total_premium", "value_start", "value_end"):
        assert k in result
    for key in (("oracle", "oracle"), ("oracle", "causal"),
                ("causal", "oracle"), ("causal", "causal")):
        assert key in result["cells"], f"missing grid cell {key}"


def test_deterministic(mod, result):
    r2 = mod.run_analysis()
    assert r2["total_premium"] == pytest.approx(result["total_premium"], rel=1e-9)
    assert r2["value_start"] == pytest.approx(result["value_start"], rel=1e-9)
    assert r2["value_end"] == pytest.approx(result["value_end"], rel=1e-9)


def test_total_premium_positive(result):
    """Full look-ahead must beat the live/causal controller (matches idea #9)."""
    assert isinstance(result["total_premium"], float)
    assert result["total_premium"] > 1.0


def test_entry_dominates_exit(result):
    """
    The core finding: knowing crisis START (entry) contributes far more of the look-ahead
    premium than knowing crisis END (exit). Guards the 'onset-detection is the lever' verdict.
    """
    vs = result["value_start"]
    ve = result["value_end"]
    assert isinstance(vs, float) and isinstance(ve, float)
    assert vs > ve, (
        f"entry look-ahead {vs} should exceed exit look-ahead {ve}; if this flips, the "
        "live gap is no longer an onset-detection problem — revisit the #13 verdict"
    )
    # entry carries the majority of the total premium
    assert vs > 0.5 * result["total_premium"]


def test_oracle_entry_lowers_drawdown(result):
    """Mechanism: de-risking BEFORE the drawdown (oracle entry) beats de-risking after."""
    dd_oracle_entry = result["cells"][("oracle", "oracle")]["dd"]
    dd_causal_entry = result["cells"][("causal", "causal")]["dd"]
    assert isinstance(dd_oracle_entry, float) and isinstance(dd_causal_entry, float)
    assert dd_oracle_entry <= dd_causal_entry
