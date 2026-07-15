"""
Deterministic invariants for Idea #14 — Leading-Signal Entry (causal vol vs drawdown)
(scripts/edge_leading_vol_entry.py).

Honest claims asserted as structural invariants:

  1. run_analysis() is deterministic and returns the references + vol-entry sweep.
  2. Ordering sanity: static #3 < causal #9 < oracle-entry ceiling (the #9/#13 frame holds).
  3. THE FINDING: single-leg realized-vol entry recovers only a SMALL fraction of the
     onset premium (best recovery is modest, not a near-full close). If a future fixture
     makes vol strongly leading, this flips — and the "use an EXOGENOUS onset signal, not
     own realized vol" conclusion must be revisited.
  4. Causality guard: _rolling_vol[i] uses only returns[:i] (no same-day / future info).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2]
           / "scripts" / "edge_leading_vol_entry.py")


def _load():
    spec = importlib.util.spec_from_file_location("edge_leading_vol_entry", _SCRIPT)
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
    for k in ("static_calmar", "causal9", "oracle_entry", "rows", "best"):
        assert k in result
    assert len(result["rows"]) >= 6
    assert result["best"] is not None


def test_deterministic(mod, result):
    r2 = mod.run_analysis()
    assert r2["best"]["calmar"] == pytest.approx(result["best"]["calmar"], rel=1e-9)
    assert r2["causal9"]["calmar"] == pytest.approx(result["causal9"]["calmar"], rel=1e-9)


def test_reference_ordering(result):
    """static #3 < causal #9 < oracle-entry ceiling — the #9/#13 frame this idea sits in."""
    s = result["static_calmar"]
    c9 = result["causal9"]["calmar"]
    oe = result["oracle_entry"]["calmar"]
    assert all(isinstance(x, float) for x in (s, c9, oe))
    assert s < c9 < oe


def test_vol_entry_recovers_little_of_onset_gap(result):
    """
    The honest finding: single-leg realized vol does NOT strongly lead drawdown here, so it
    recovers only a small fraction of the (oracle − #9) onset gap. Guards the conclusion that
    the onset signal must be EXOGENOUS (peg/oracle/liquidity), not the book's own vol.
    """
    rec = result["best"]["recovered"]
    assert isinstance(rec, float)
    assert rec < 0.2, (
        f"vol entry recovered {rec:.1%} of the onset gap; if this ever exceeds ~20%, "
        "single-leg vol became a strong leading signal — revisit the #14 verdict"
    )


def test_causal_rolling_vol_no_lookahead(mod):
    """_rolling_vol[i] must depend only on returns before i (strictly trailing)."""
    base = [0.0, 0.01, -0.02, 0.03, -0.01, 0.05, 0.0, 0.0]
    v_base = mod._rolling_vol(base, 3)
    # perturbing return at index k must NOT change vol[j] for any j <= k
    perturbed = list(base)
    perturbed[5] = 0.99
    v_pert = mod._rolling_vol(perturbed, 3)
    for j in range(6):  # indices 0..5 use only returns[:j] ⊆ returns[:6], unaffected by idx 5
        assert v_base[j] == pytest.approx(v_pert[j]), f"vol[{j}] leaked future return at idx 5"
