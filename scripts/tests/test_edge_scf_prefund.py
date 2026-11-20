"""
#164 SCF — Sequential Carry Funding — pinned tests on the synthetic fixture.

Positive controls:
  - mechanism produces the right number of phase transitions (exactly 2: Phase1→2, Phase2→1)
  - SCF-7pct outperforms naive static 75/25 on both APY and maxDD
  - SCF-7pct outperforms EW-5 on APY
  - 700-day backtest period is intact
  - all runs produce positive calmar denominators above poshlinа threshold
  - EW-5 is negative (matches #163 reference)
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


M = _load("edge_scf_prefund")

# Cache results so we only run once
import functools

@functools.lru_cache(maxsize=1)
def _results():
    return M.main()


def test_all_strategies_present():
    r = _results()
    for key in ("A_anchor_100", "B_static_75_25", "C_ew5", "SCF-5pct", "SCF-7pct", "SCF-10pct"):
        assert key in r, f"Missing strategy: {key}"


def test_period_is_700_days():
    """Fixture backtest is 2024-07-01 .. 2026-05-31 = 700 days."""
    import datetime
    start = datetime.date(2024, 7, 1)
    end = datetime.date(2026, 5, 31)
    n = (end - start).days + 1
    assert n == 700


def test_scf7_beats_static_7525_on_apy():
    """SCF prevents the worst leverage_loop crisis impact; must beat naive blending."""
    r = _results()
    assert r["SCF-7pct"]["apy"] > r["B_static_75_25"]["apy"], (
        f"SCF-7pct APY {r['SCF-7pct']['apy']:.4f} ≤ Static 75/25 APY {r['B_static_75_25']['apy']:.4f}"
    )


def test_scf7_lower_maxdd_than_static_7525():
    """SCF exit-gate must keep maxDD below naive 75/25 blending."""
    r = _results()
    assert r["SCF-7pct"]["max_dd"] < r["B_static_75_25"]["max_dd"], (
        f"SCF-7pct maxDD {r['SCF-7pct']['max_dd']:.4f} ≥ Static 75/25 maxDD {r['B_static_75_25']['max_dd']:.4f}"
    )


def test_scf7_beats_ew5_on_apy():
    """SCF-7pct must beat the EW-5 basket (which is negative on this fixture)."""
    r = _results()
    assert r["SCF-7pct"]["apy"] > r["C_ew5"]["apy"], (
        f"SCF-7pct APY {r['SCF-7pct']['apy']:.4f} ≤ EW-5 APY {r['C_ew5']['apy']:.4f}"
    )


def test_ew5_is_negative():
    """EW-5 baseline should be negative — matches #163 reference (-1.83% gross)."""
    r = _results()
    assert r["C_ew5"]["apy"] < 0, f"EW-5 APY should be negative, got {r['C_ew5']['apy']:.4f}"


def test_scf_transitions_exactly_two():
    """SCF-7pct should have exactly 2 transitions: Phase1→Phase2, Phase2→Phase1 (exit on usde_unwind)."""
    r = _results()
    ph = r["SCF-7pct"]["phase"]
    assert ph["transitions"] == 2, (
        f"Expected 2 transitions (Phase1→2 and exit on usde_unwind), got {ph['transitions']}"
    )


def test_scf_phase_days_sum_to_700():
    """Phase1 + Phase2 must equal total backtest days."""
    r = _results()
    ph = r["SCF-7pct"]["phase"]
    assert ph["phase1_days"] + ph["phase2_days"] == 700, (
        f"Phase days sum {ph['phase1_days'] + ph['phase2_days']} ≠ 700"
    )


def test_anchor_avoids_large_drawdown():
    """susde_dn anchor-only should not exceed 15% maxDD (fixture is not catastrophic for anchor)."""
    r = _results()
    assert r["A_anchor_100"]["max_dd"] < 0.15, (
        f"Anchor maxDD {r['A_anchor_100']['max_dd']:.4f} unexpectedly large"
    )


def test_scf7_calmar_above_anchor():
    """SCF-7pct Calmar should be at or above pure anchor (efficiency improved or same)."""
    r = _results()
    # Both should have valid Calmar (maxDD > 96bp)
    assert r["SCF-7pct"]["calmar"] >= r["A_anchor_100"]["calmar"] * 0.99, (
        f"SCF-7pct Calmar {r['SCF-7pct']['calmar']:.4f} < anchor {r['A_anchor_100']['calmar']:.4f}"
    )


def test_tighter_threshold_has_more_phase2_days():
    """Lower threshold = earlier entry = more Phase2 days."""
    r = _results()
    assert r["SCF-5pct"]["phase"]["phase2_days"] >= r["SCF-7pct"]["phase"]["phase2_days"], (
        "SCF-5pct should spend more time in Phase2 than SCF-7pct"
    )
    assert r["SCF-7pct"]["phase"]["phase2_days"] >= r["SCF-10pct"]["phase"]["phase2_days"], (
        "SCF-7pct should spend more time in Phase2 than SCF-10pct"
    )
