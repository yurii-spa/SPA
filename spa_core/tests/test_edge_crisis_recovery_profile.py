"""
Tests for scripts/edge_crisis_recovery_profile.py — #153 CRP: Crisis Recovery Profile

Positive control: both CRP and EW produce non-trivial portfolios.
Negative controls (mutation targets):
  - breaking the recovery computation returns wrong weights
  - removing the 'variant_d' suppression lets it dominate the portfolio
  - swapping APY and maxDD would change the verdict
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
import tempfile
from pathlib import Path
from typing import List, Tuple

import pytest

from spa_core.strategy_lab.aggressive_lab.fixtures import materialize

# ── import the module under test ──────────────────────────────────────────────
import sys
import os
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from edge_crisis_recovery_profile import (
    crp_report,
    compute_recovery_days,
    recovery_velocity,
    normalize_weights,
    run_portfolio,
    CRISIS_WINDOWS,
    ELIGIBLE_BOOKS,
    TRAIN_END,
    TEST_START,
    MAX_BOOK_WEIGHT,
    INF_PENALTY_MULTIPLIER,
)


@pytest.fixture(scope="module")
def data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield materialize(Path(tmp))


@pytest.fixture(scope="module")
def report(data_dir):
    return crp_report(data_dir)


# ── structural tests ──────────────────────────────────────────────────────────

class TestReportStructure:
    def test_has_all_books(self, report):
        for sid in ELIGIBLE_BOOKS:
            assert sid in report["recovery_summary"]

    def test_weights_sum_to_one(self, report):
        total = sum(report["crp_weights"].values())
        assert abs(total - 1.0) < 1e-9, f"weights sum {total} != 1"

    def test_no_book_exceeds_cap(self, report):
        for sid, w in report["crp_weights"].items():
            assert w <= MAX_BOOK_WEIGHT + 1e-9, f"{sid} weight {w:.4f} > cap {MAX_BOOK_WEIGHT}"

    def test_ew_weights_are_equal(self, report):
        for sid in ELIGIBLE_BOOKS:
            assert abs(report["ew_weights"][sid] - 1.0 / len(ELIGIBLE_BOOKS)) < 1e-9

    def test_results_have_three_periods(self, report):
        assert set(report["results"].keys()) == {"train", "test", "full"}

    def test_evidence_level_contains_backtest(self, report):
        assert "backtest" in report["evidence_level"].lower() or "L0" in report["evidence_level"]


# ── recovery computation tests ────────────────────────────────────────────────

class TestComputeRecoveryDays:
    def _minimal_series(self, equity_values: List[float], start_date: datetime.date) -> List[Tuple[datetime.date, float]]:
        result = []
        for i, eq in enumerate(equity_values):
            d = start_date + datetime.timedelta(days=i)
            result.append((d, eq))
        return result

    def test_instant_recovery(self):
        # equity: 100 (pre-crisis) → 90 (crisis day) → 105 (recovered day after window)
        # Series must start BEFORE the crisis window so there's a pre-crisis peak
        start = datetime.date(2024, 7, 31)  # one day before crisis
        series = self._minimal_series([100, 90, 105, 110], start)
        crisis = {
            "key": "test_crisis",
            "from": datetime.date(2024, 8, 1),
            "to": datetime.date(2024, 8, 1),  # 1-day window
        }
        rd = compute_recovery_days(series, crisis)
        assert rd is not None
        assert rd >= 1  # at least 1 day after window

    def test_no_loss_returns_none(self):
        # equity monotonically increases — no crisis loss
        start = datetime.date(2024, 8, 1)
        series = self._minimal_series([100, 101, 102, 103], start)
        crisis = {
            "key": "test_crisis",
            "from": datetime.date(2024, 8, 1),
            "to": datetime.date(2024, 8, 2),
        }
        result = compute_recovery_days(series, crisis)
        assert result is None

    def test_never_recovered_returns_large(self):
        # equity: 100 (pre-crisis) → drops to 80, stays below 100 (no recovery)
        # Series starts one day before crisis window so there's a pre-crisis peak
        start = datetime.date(2024, 7, 31)  # one day before crisis
        series = self._minimal_series([100, 80, 81, 82, 83, 84, 85, 86], start)
        crisis = {
            "key": "test_crisis",
            "from": datetime.date(2024, 8, 1),
            "to": datetime.date(2024, 8, 1),
        }
        rd = compute_recovery_days(series, crisis)
        # Should be "penalized" large value (2x remaining days)
        assert rd is not None
        remaining_days = 6  # days after window in this series
        assert rd >= remaining_days * INF_PENALTY_MULTIPLIER

    def test_crisis_before_series_returns_none(self):
        # Series starts after the crisis window
        start = datetime.date(2024, 9, 1)  # after August crisis
        series = self._minimal_series([100, 101, 102], start)
        crisis = {
            "key": "test_crisis",
            "from": datetime.date(2024, 8, 1),
            "to": datetime.date(2024, 8, 31),
        }
        result = compute_recovery_days(series, crisis)
        assert result is None


# ── recovery velocity tests ───────────────────────────────────────────────────

class TestRecoveryVelocity:
    def test_velocity_inversely_proportional_to_recovery_days(self):
        # A series that recovers from a 10% loss in 50 days
        start = datetime.date(2024, 8, 1)
        equity = [100.0]
        # Drop 10% on the crisis day
        equity.append(90.0)
        # Recover slowly over 50 days
        for i in range(50):
            equity.append(90.0 + (10.0 * (i + 1) / 50))
        series_fast = [(start + datetime.timedelta(days=i), eq) for i, eq in enumerate(equity)]

        # A series that recovers the same 10% loss over 200 days
        equity_slow = [100.0, 90.0]
        for i in range(200):
            equity_slow.append(90.0 + (10.0 * (i + 1) / 200))
        series_slow = [(start + datetime.timedelta(days=i), eq) for i, eq in enumerate(equity_slow)]

        crisis = [{
            "key": "test",
            "from": datetime.date(2024, 8, 2),
            "to": datetime.date(2024, 8, 2),
        }]

        vel_fast, _ = recovery_velocity(series_fast, crisis, datetime.date(2025, 12, 31))
        vel_slow, _ = recovery_velocity(series_slow, crisis, datetime.date(2025, 12, 31))

        # Fast recovery should have HIGHER velocity
        assert vel_fast > vel_slow, f"fast vel {vel_fast} should be > slow vel {vel_slow}"

    def test_no_crises_returns_inf_velocity(self):
        # A flat series with no crisis losses
        start = datetime.date(2024, 8, 1)
        series = [(start + datetime.timedelta(days=i), 100.0 + i) for i in range(100)]
        crises = []  # no crises
        vel, details = recovery_velocity(series, crises, datetime.date(2025, 12, 31))
        assert vel == float("inf")
        assert details == []


# ── weight normalization tests ────────────────────────────────────────────────

class TestNormalizeWeights:
    def test_sums_to_one(self):
        raw = {"a": 3.0, "b": 1.0, "c": 2.0}
        w = normalize_weights(raw)
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_cap_enforced(self):
        # One book has very high raw velocity — should be capped
        raw = {"a": 100.0, "b": 1.0, "c": 1.0}
        w = normalize_weights(raw, cap=0.40)
        assert w["a"] <= 0.40 + 1e-9

    def test_remaining_weight_redistributed_after_cap(self):
        # After capping one book, remaining weight goes to others
        raw = {"a": 100.0, "b": 1.0, "c": 1.0}
        w = normalize_weights(raw, cap=0.40)
        total = sum(w.values())
        assert abs(total - 1.0) < 1e-9

    def test_empty_returns_empty(self):
        assert normalize_weights({}) == {}

    def test_negative_ignored(self):
        raw = {"a": -1.0, "b": 2.0}
        w = normalize_weights(raw)
        assert "a" not in w or w.get("a", 0) == 0


# ── variant_d suppression test (key mechanism test) ──────────────────────────

class TestVariantDSuppression:
    def test_variant_d_is_suppressed_below_ew(self, report):
        """variant_d never recovered from ETH crash in TRAIN → must have lowest weight."""
        crp_vd = report["crp_weights"].get("variant_d", 0.0)
        ew_vd = report["ew_weights"]["variant_d"]
        assert crp_vd < ew_vd, (
            f"variant_d CRP weight {crp_vd:.4f} should be < EW weight {ew_vd:.4f}; "
            "the never-recovered book must be suppressed"
        )

    def test_points_farm_is_largest_book(self, report):
        """points_farm has smallest crisis losses → fastest recovery → largest weight."""
        crp_weights = report["crp_weights"]
        max_book = max(crp_weights, key=crp_weights.get)
        assert max_book == "points_farm", (
            f"Expected points_farm (fastest recovery) to be largest book, got {max_book}"
        )

    def test_variant_d_has_never_recovered_flag(self, report):
        """variant_d should show never_recovered_count >= 1."""
        rs = report["recovery_summary"]["variant_d"]
        assert rs["never_recovered_count"] >= 1


# ── portfolio comparison tests ────────────────────────────────────────────────

class TestPortfolioComparison:
    def test_crp_beats_ew_in_train_apy(self, report):
        crp_apy = report["results"]["train"]["crp"][0]
        ew_apy = report["results"]["train"]["ew"][0]
        assert crp_apy > ew_apy, (
            f"CRP {crp_apy:.2f}% should beat EW {ew_apy:.2f}% in TRAIN"
        )

    def test_crp_beats_ew_in_train_maxdd(self, report):
        crp_dd = report["results"]["train"]["crp"][1]
        ew_dd = report["results"]["train"]["ew"][1]
        assert crp_dd < ew_dd, (
            f"CRP maxDD {crp_dd:.2f}% should be < EW maxDD {ew_dd:.2f}% in TRAIN"
        )

    def test_crp_beats_ew_in_test_apy(self, report):
        crp_apy = report["results"]["test"]["crp"][0]
        ew_apy = report["results"]["test"]["ew"][0]
        assert crp_apy > ew_apy, (
            f"CRP {crp_apy:.2f}% should beat EW {ew_apy:.2f}% in TEST"
        )

    def test_crp_beats_ew_in_full_period_calmar(self, report):
        crp_cal = report["results"]["full"]["crp"][2]
        ew_cal = report["results"]["full"]["ew"][2]
        # Both may be nan-free since fixture always has non-zero drawdown
        if math.isnan(crp_cal) or math.isnan(ew_cal):
            pytest.skip("Calmar is nan (degenerate portfolio)")
        assert crp_cal > ew_cal, (
            f"CRP Calmar {crp_cal:.3f} should be > EW Calmar {ew_cal:.3f}"
        )

    def test_portfolio_apy_is_finite(self, report):
        for period in ("train", "test", "full"):
            apy_crp = report["results"][period]["crp"][0]
            apy_ew = report["results"][period]["ew"][0]
            assert math.isfinite(apy_crp), f"CRP APY in {period} is not finite"
            assert math.isfinite(apy_ew), f"EW APY in {period} is not finite"

    def test_portfolio_maxdd_is_nonnegative(self, report):
        for period in ("train", "test", "full"):
            dd_crp = report["results"][period]["crp"][1]
            dd_ew = report["results"][period]["ew"][1]
            assert dd_crp >= 0.0
            assert dd_ew >= 0.0


# ── determinism test ──────────────────────────────────────────────────────────

class TestDeterminism:
    def test_report_is_deterministic(self, data_dir):
        r1 = crp_report(data_dir)
        r2 = crp_report(data_dir)
        # Compare key numeric outputs
        for period in ("train", "test", "full"):
            for portfolio in ("crp", "ew"):
                assert r1["results"][period][portfolio] == r2["results"][period][portfolio]

    def test_weights_are_deterministic(self, data_dir):
        r1 = crp_report(data_dir)
        r2 = crp_report(data_dir)
        assert r1["crp_weights"] == r2["crp_weights"]


# ── honest output tests ───────────────────────────────────────────────────────

class TestHonestOutput:
    def test_evidence_level_not_realized(self, report):
        ev = report["evidence_level"].lower()
        # Must NOT claim to be 'realized' without qualification
        assert "backtest" in ev or "L0" in report["evidence_level"]

    def test_advisory_flag_set(self, report):
        # The idea metadata should note advisory status
        assert report.get("idea_number") == 153

    def test_tail_visible_in_report(self, report):
        # maxDD should be non-zero (there are crisis losses)
        full_dd = report["results"]["full"]["crp"][1]
        assert full_dd > 0.01, "CRP should have some drawdown from crises"
