"""
spa_core/tests/test_edge_multi_seam_stability.py — #157 MSS test suite.

Tests the Multi-Seam Stability script: seam generation, independence counting,
per-seam run, OOS overlap, Spearman, and the main report structure.

≥15 tests, with mutations covering critical paths.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

# ── import helpers ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import importlib.util

def _load_mss():
    spec = importlib.util.spec_from_file_location(
        "edge_mss",
        _REPO_ROOT / "scripts" / "edge_multi_seam_stability.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_crp():
    spec = importlib.util.spec_from_file_location(
        "edge_crp",
        _REPO_ROOT / "scripts" / "edge_crisis_recovery_profile.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mss():
    return _load_mss()


@pytest.fixture(scope="module")
def crp():
    return _load_crp()


@pytest.fixture(scope="module")
def data_dir():
    from spa_core.strategy_lab.aggressive_lab import fixtures
    with tempfile.TemporaryDirectory() as tmpdir:
        root = fixtures.materialize(Path(tmpdir))
        yield root


@pytest.fixture(scope="module")
def report(data_dir):
    mss = _load_mss()
    return mss.mss_report(data_dir)


# ── T01: seam grid ─────────────────────────────────────────────────────────────

def test_seam_dates_count(mss):
    """Exactly 16 monthly seams from 2024-09 to 2025-12."""
    assert len(mss.SEAM_DATES) == 16


def test_seam_dates_sorted_unique(mss):
    dates = mss.SEAM_DATES
    assert dates == sorted(set(dates))


def test_seam_dates_first_and_last(mss):
    assert mss.SEAM_DATES[0] == datetime.date(2024, 9, 1)
    assert mss.SEAM_DATES[-1] == datetime.date(2025, 12, 1)


def test_seam_dates_all_first_of_month(mss):
    for d in mss.SEAM_DATES:
        assert d.day == 1, f"{d} is not first of month"


# ── T02: independence counting ─────────────────────────────────────────────────

def test_n_independent_is_two(mss):
    """The fixture yields exactly 2 independent seam blocks."""
    n, blocks = mss._count_independent_seams(mss.SEAM_DATES)
    assert n == 2


def test_block_sizes(mss):
    """Block-1 has 14 seams; Block-2 has 2 seams."""
    _, blocks = mss._count_independent_seams(mss.SEAM_DATES)
    sizes = sorted([len(b["seam_dates"]) for b in blocks], reverse=True)
    assert sizes == [14, 2]


def test_train_crisis_set_before_eth_crash(mss):
    """Seams before eth_crash (2024-08) have empty TRAIN set."""
    seam = datetime.date(2024, 7, 1)
    cs = mss._train_crisis_set(seam)
    assert cs == ()


def test_train_crisis_set_block1(mss):
    """Seams 2024-09 through 2025-10 include only eth_crash in TRAIN."""
    for d in [datetime.date(2024, 9, 1), datetime.date(2025, 10, 1)]:
        cs = mss._train_crisis_set(d)
        assert cs == ("eth_crash_2024_08",), f"Wrong for {d}: {cs}"


def test_train_crisis_set_block2(mss):
    """Seam 2025-11 adds usde_unwind to TRAIN."""
    cs = mss._train_crisis_set(datetime.date(2025, 11, 1))
    assert "usde_unwind_2025_10" in cs
    assert "eth_crash_2024_08" in cs


def test_rseth_never_in_train(mss):
    """rseth_depeg (2026-04) is never in TRAIN for any seam ≤ 2025-12."""
    for d in mss.SEAM_DATES:
        cs = mss._train_crisis_set(d)
        assert "rseth_depeg_2026_04" not in cs, f"rseth in TRAIN for {d}"


# ── T03: Spearman ──────────────────────────────────────────────────────────────

def test_spearman_perfect_positive(mss):
    rho = mss._spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert rho is not None
    assert abs(rho - 1.0) < 1e-9


def test_spearman_perfect_negative(mss):
    rho = mss._spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert rho is not None
    assert abs(rho - (-1.0)) < 1e-9


def test_spearman_too_short(mss):
    assert mss._spearman([1.0], [1.0]) is None


# ── T04: OOS overlap ───────────────────────────────────────────────────────────

def test_oos_overlap_positive(mss):
    """Block-1 seams have high pairwise OOS overlap (> 50%)."""
    overlap = mss._oos_overlap_fraction(mss.SEAM_DATES)
    assert overlap > 0.5, f"Expected high overlap, got {overlap:.2%}"


def test_oos_overlap_less_than_one(mss):
    """OOS overlap is strictly less than 1 (seams are distinct)."""
    overlap = mss._oos_overlap_fraction(mss.SEAM_DATES)
    assert overlap < 1.0


# ── T05: report structure ──────────────────────────────────────────────────────

def test_report_n_independent(report):
    assert report["independence"]["n_independent"] == 2


def test_report_verdict_insufficient(report):
    assert report["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_report_seam_results_count(report):
    """All 16 seams should have TRAIN crises and produce results."""
    assert len(report["seam_results"]) == 16


def test_report_all_seams_have_delta(report):
    for sr in report["seam_results"]:
        assert "delta_apy" in sr
        assert isinstance(sr["delta_apy"], float)


def test_report_is_advisory_flag(report):
    assert report["is_advisory"] is True
    assert report["outside_riskpolicy"] is True


def test_report_evidence_level(report):
    assert "L0" in report["evidence_level"]
    assert "fixture" in report["evidence_level"].lower()


def test_report_block1_all_same_crisis_set(report):
    """Within Block-1, all 14 seams have the same TRAIN crisis set (eth_crash only).
    Note: CRP weights may differ within Block-1 because recovery velocity uses the
    seam date as the horizon — different seams give different post-crisis horizons."""
    block1_seams = [
        sr for sr in report["seam_results"]
        if sr["crisis_set"] == ["eth_crash_2024_08"]
    ]
    assert len(block1_seams) == 14
    for sr in block1_seams:
        assert sr["crisis_set"] == ["eth_crash_2024_08"], (
            f"Seam {sr['seam']} has unexpected crisis_set {sr['crisis_set']}"
        )


# ── T06: mutations / fail paths ────────────────────────────────────────────────

def test_missing_crp_module_raises_unmeasured(mss):
    """If CRP path doesn't exist, _load_crp_module raises Unmeasured (not FileNotFoundError)."""
    orig = mss._CRP_PATH
    try:
        mss._CRP_PATH = Path("/nonexistent/path/edge_crisis_recovery_profile.py")
        try:
            mss._load_crp_module()
            pytest.fail("Expected Unmeasured to be raised")
        except mss.Unmeasured:
            pass  # correct
        except Exception as e:
            pytest.fail(f"Expected Unmeasured, got {type(e).__name__}: {e}")
    finally:
        mss._CRP_PATH = orig


def test_run_one_seam_no_crises_returns_none(mss, data_dir):
    """Seam before any crisis window returns None."""
    crp_mod = _load_crp()
    series_map = {
        sid: crp_mod.load_backtest_series(data_dir, sid)
        for sid in mss.ELIGIBLE_BOOKS
    }
    result = mss._run_one_seam(datetime.date(2024, 7, 15), series_map, crp_mod)
    assert result is None


def test_block1_crp_beats_ew_all_seams(report):
    """Block-1: CRP should beat EW on all 14 seams (same correlated outcome)."""
    block1 = [sr for sr in report["seam_results"] if sr["crisis_set"] == ["eth_crash_2024_08"]]
    for sr in block1:
        assert sr["crp_beats_ew"], f"CRP lost to EW at seam {sr['seam']}"
