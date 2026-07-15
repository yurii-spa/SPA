"""
Deterministic invariants for the Idea #9 per-crisis ROBUSTNESS re-validation
(scripts/edge_causal_window_robustness.py).

This is a generalization audit of an EXISTING edge, not a new idea. The invariants pin the honest
finding as a regression tripwire:

  1. run_analysis() is deterministic and structurally complete.
  2. The fixture spans all three crisis windows (attribution is total, not partial).
  3. The aggregate #9 causal edge exists (causal Calmar > static Calmar) — consistent with the #9 suite.
  4. THE FINDING: the edge GENERALIZES — causal preserves more capital in >= 2 of the 3 crises
     (verdict ROBUST), so the aggregate advantage is NOT a single-crisis artifact. If a fixture
     change ever drops this below 2, the edge became concentrated/overfit and the #9 claim must
     be re-examined — this test is the tripwire.
  5. verdict is consistent with n_causal_advantage (no scoring/label drift).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2]
           / "scripts" / "edge_causal_window_robustness.py")


def _load():
    spec = importlib.util.spec_from_file_location("edge_causal_window_robustness", _SCRIPT)
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
    for k in ("n_windows_covered", "n_causal_advantage", "verdict",
              "aggregate_static_calmar", "aggregate_causal_calmar", "rows"):
        assert k in result
    assert result["verdict"] in ("ROBUST", "CONCENTRATED", "NONE")
    assert len(result["rows"]) == 3


def test_deterministic(mod, result):
    r2 = mod.run_analysis()
    assert r2["verdict"] == result["verdict"]
    assert r2["n_causal_advantage"] == result["n_causal_advantage"]
    assert r2["aggregate_causal_calmar"] == pytest.approx(result["aggregate_causal_calmar"], rel=1e-9)


def test_all_three_windows_covered(result):
    """The fixture spans 2024-08, 2025-10, 2026-04 — attribution is total, not partial."""
    assert result["n_windows_covered"] == 3
    assert all(r.get("covered") for r in result["rows"])


def test_aggregate_causal_edge_exists(result):
    """Consistent with the #9 suite: the best causal controller beats the static blend on Calmar."""
    assert result["aggregate_causal_calmar"] > result["aggregate_static_calmar"]


def test_edge_generalizes_not_concentrated(result):
    """
    THE FINDING (regression tripwire): causal preserves more capital in >= 2 of 3 crises, so the
    aggregate #9 edge is NOT a single-crisis artifact. If this ever drops below 2, the edge became
    concentrated/overfit — revisit the #9 claim before trusting its aggregate Calmar.
    """
    assert result["n_causal_advantage"] >= 2
    assert result["verdict"] == "ROBUST"


def test_verdict_consistent_with_count(result):
    adv = result["n_causal_advantage"]
    expected = "ROBUST" if adv >= 2 else "CONCENTRATED" if adv == 1 else "NONE"
    assert result["verdict"] == expected
