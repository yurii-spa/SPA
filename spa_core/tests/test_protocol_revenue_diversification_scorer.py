"""
Tests for MP-908: ProtocolRevenueDiversificationScorer
Run with: python3 -m unittest spa_core.tests.test_protocol_revenue_diversification_scorer
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from spa_core.analytics.protocol_revenue_diversification_scorer import (
    ProtocolRevenueDiversificationScorer,
    _compute_diversification_score,
    _compute_flags,
    _compute_hhi,
    _compute_price_independence_score,
    _compute_revenue_label,
    _compute_revenue_stability_score,
    _effective_total_revenue,
    _get_primary_source,
    _score_protocol,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _src(source_type="fees", monthly_usd=100_000.0, trend="stable"):
    return {"source_type": source_type, "monthly_usd": monthly_usd, "trend": trend}


def _make_protocol(
    name="Proto-A",
    sources=None,
    total_revenue=None,
    age_months=24.0,
    chain_count=3,
    user_count=10_000,
    token_price_dependency=0.2,
):
    if sources is None:
        sources = [
            _src("fees", 60_000.0, "stable"),
            _src("interest", 30_000.0, "growing"),
            _src("liquidations", 10_000.0, "stable"),
        ]
    p = {
        "name": name,
        "revenue_sources": sources,
        "age_months": age_months,
        "chain_count": chain_count,
        "user_count": user_count,
        "token_price_dependency": token_price_dependency,
    }
    if total_revenue is not None:
        p["total_monthly_revenue_usd"] = total_revenue
    else:
        p["total_monthly_revenue_usd"] = sum(s["monthly_usd"] for s in sources)
    return p


# ─────────────────────────────────────────────────────────────────
# 1. _compute_hhi
# ─────────────────────────────────────────────────────────────────

class TestComputeHHI(unittest.TestCase):

    def test_single_source_equals_10000(self):
        sources = [_src("fees", 100_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        self.assertAlmostEqual(hhi, 10_000.0)

    def test_two_equal_sources(self):
        sources = [_src("fees", 50_000.0), _src("interest", 50_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        # (50%)^2 + (50%)^2 = 2500 + 2500 = 5000
        self.assertAlmostEqual(hhi, 5_000.0)

    def test_four_equal_sources(self):
        sources = [_src(f"t{i}", 25_000.0) for i in range(4)]
        hhi = _compute_hhi(sources, 100_000.0)
        # 4 * (25%)^2 = 4 * 625 = 2500
        self.assertAlmostEqual(hhi, 2_500.0)

    def test_ten_equal_sources(self):
        sources = [_src(f"t{i}", 10_000.0) for i in range(10)]
        hhi = _compute_hhi(sources, 100_000.0)
        # 10 * (10%)^2 = 10 * 100 = 1000
        self.assertAlmostEqual(hhi, 1_000.0)

    def test_empty_sources_returns_10000(self):
        hhi = _compute_hhi([], 100_000.0)
        self.assertAlmostEqual(hhi, 10_000.0)

    def test_zero_total_revenue_returns_10000(self):
        sources = [_src("fees", 100_000.0)]
        hhi = _compute_hhi(sources, 0.0)
        self.assertAlmostEqual(hhi, 10_000.0)

    def test_hhi_in_range(self):
        sources = [_src("fees", 70_000.0), _src("interest", 30_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        self.assertGreaterEqual(hhi, 0.0)
        self.assertLessEqual(hhi, 10_000.0)

    def test_highly_concentrated(self):
        # 90/10 split → HHI = 90^2 + 10^2 = 8100 + 100 = 8200
        sources = [_src("fees", 90_000.0), _src("interest", 10_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        self.assertAlmostEqual(hhi, 8_200.0)

    def test_negative_monthly_usd_treated_as_zero(self):
        sources = [_src("fees", -50_000.0), _src("interest", 100_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        # Only interest contributes: (100%)^2 = 10000
        self.assertAlmostEqual(hhi, 10_000.0)

    def test_returns_float(self):
        sources = [_src("fees", 100_000.0)]
        hhi = _compute_hhi(sources, 100_000.0)
        self.assertIsInstance(hhi, float)

    def test_three_sources_different_shares(self):
        # 60/30/10 split → 60^2 + 30^2 + 10^2 = 3600 + 900 + 100 = 4600
        sources = [
            _src("fees", 60_000.0),
            _src("interest", 30_000.0),
            _src("liquidations", 10_000.0),
        ]
        hhi = _compute_hhi(sources, 100_000.0)
        self.assertAlmostEqual(hhi, 4_600.0)


# ─────────────────────────────────────────────────────────────────
# 2. _compute_diversification_score
# ─────────────────────────────────────────────────────────────────

class TestComputeDiversificationScore(unittest.TestCase):

    def test_hhi_10000_gives_0(self):
        self.assertAlmostEqual(_compute_diversification_score(10_000.0), 0.0)

    def test_hhi_0_gives_100(self):
        self.assertAlmostEqual(_compute_diversification_score(0.0), 100.0)

    def test_hhi_5000_gives_50(self):
        self.assertAlmostEqual(_compute_diversification_score(5_000.0), 50.0)

    def test_hhi_2500_gives_75(self):
        self.assertAlmostEqual(_compute_diversification_score(2_500.0), 75.0)

    def test_score_in_range(self):
        for hhi in [0, 1000, 2500, 5000, 7500, 10000]:
            score = _compute_diversification_score(float(hhi))
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_higher_hhi_lower_score(self):
        s1 = _compute_diversification_score(1_000.0)
        s2 = _compute_diversification_score(5_000.0)
        s3 = _compute_diversification_score(9_000.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)

    def test_returns_float(self):
        self.assertIsInstance(_compute_diversification_score(3000.0), float)


# ─────────────────────────────────────────────────────────────────
# 3. _compute_revenue_stability_score
# ─────────────────────────────────────────────────────────────────

class TestComputeRevenueStabilityScore(unittest.TestCase):

    def test_all_growing(self):
        sources = [_src("fees", 50_000.0, "growing"), _src("interest", 50_000.0, "growing")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertAlmostEqual(score, 100.0)

    def test_all_declining(self):
        sources = [_src("fees", 50_000.0, "declining"), _src("interest", 50_000.0, "declining")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertAlmostEqual(score, 20.0)

    def test_all_stable(self):
        sources = [_src("fees", 50_000.0, "stable"), _src("interest", 50_000.0, "stable")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertAlmostEqual(score, 70.0)

    def test_mixed_trends_weighted(self):
        # 90% growing (100) + 10% declining (20) → weighted = 90*100 + 10*20 = 9200 / 100 = 92.0
        sources = [
            _src("fees", 90_000.0, "growing"),
            _src("interest", 10_000.0, "declining"),
        ]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertAlmostEqual(score, 92.0, places=1)

    def test_empty_sources(self):
        score = _compute_revenue_stability_score([], 100_000.0)
        self.assertAlmostEqual(score, 0.0)

    def test_zero_total_revenue(self):
        sources = [_src("fees", 50_000.0, "growing")]
        score = _compute_revenue_stability_score(sources, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_unknown_trend_treated_as_stable(self):
        sources = [_src("fees", 100_000.0, "unknown_trend")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertAlmostEqual(score, 70.0)

    def test_score_in_range(self):
        sources = [_src("fees", 60_000.0, "growing"), _src("interest", 40_000.0, "declining")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        sources = [_src("fees", 100_000.0, "stable")]
        score = _compute_revenue_stability_score(sources, 100_000.0)
        self.assertIsInstance(score, float)


# ─────────────────────────────────────────────────────────────────
# 4. _compute_price_independence_score
# ─────────────────────────────────────────────────────────────────

class TestComputePriceIndependenceScore(unittest.TestCase):

    def test_zero_dependency_gives_100(self):
        self.assertAlmostEqual(_compute_price_independence_score(0.0), 100.0)

    def test_full_dependency_gives_0(self):
        self.assertAlmostEqual(_compute_price_independence_score(1.0), 0.0)

    def test_half_dependency_gives_50(self):
        self.assertAlmostEqual(_compute_price_independence_score(0.5), 50.0)

    def test_low_dependency_high_score(self):
        score = _compute_price_independence_score(0.1)
        self.assertAlmostEqual(score, 90.0)

    def test_high_dependency_low_score(self):
        score = _compute_price_independence_score(0.9)
        self.assertAlmostEqual(score, 10.0)

    def test_clamped_above_1(self):
        score = _compute_price_independence_score(1.5)
        self.assertAlmostEqual(score, 0.0)

    def test_clamped_below_0(self):
        score = _compute_price_independence_score(-0.5)
        self.assertAlmostEqual(score, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_price_independence_score(0.3), float)

    def test_score_in_range(self):
        for dep in [0.0, 0.25, 0.5, 0.75, 1.0]:
            score = _compute_price_independence_score(dep)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)


# ─────────────────────────────────────────────────────────────────
# 5. _compute_revenue_label
# ─────────────────────────────────────────────────────────────────

class TestComputeRevenueLabel(unittest.TestCase):

    def test_single_source(self):
        label = _compute_revenue_label(10_000.0, 1)
        self.assertEqual(label, "SINGLE_SOURCE")

    def test_zero_sources_single_source(self):
        label = _compute_revenue_label(10_000.0, 0)
        self.assertEqual(label, "SINGLE_SOURCE")

    def test_high_hhi_concentrated(self):
        # HHI ≥ 5000, source_count > 1
        label = _compute_revenue_label(7_000.0, 2)
        self.assertEqual(label, "CONCENTRATED")

    def test_moderate_hhi(self):
        # HHI between 2500 and 5000
        label = _compute_revenue_label(3_500.0, 3)
        self.assertEqual(label, "MODERATE")

    def test_diversified_hhi(self):
        # HHI between 1500 and 2500
        label = _compute_revenue_label(2_000.0, 4)
        self.assertEqual(label, "DIVERSIFIED")

    def test_highly_diversified_hhi(self):
        # HHI < 1500
        label = _compute_revenue_label(800.0, 8)
        self.assertEqual(label, "HIGHLY_DIVERSIFIED")

    def test_valid_labels_returned(self):
        valid = {"SINGLE_SOURCE", "CONCENTRATED", "MODERATE", "DIVERSIFIED", "HIGHLY_DIVERSIFIED"}
        test_cases = [(10000, 1), (7000, 2), (3500, 3), (2000, 4), (800, 8)]
        for hhi, cnt in test_cases:
            label = _compute_revenue_label(float(hhi), cnt)
            self.assertIn(label, valid)

    def test_exact_5000_boundary_concentrated(self):
        # HHI == 5000 → CONCENTRATED
        label = _compute_revenue_label(5_000.0, 3)
        self.assertEqual(label, "CONCENTRATED")

    def test_exact_2500_boundary_moderate(self):
        label = _compute_revenue_label(2_500.0, 3)
        self.assertEqual(label, "MODERATE")

    def test_exact_1500_boundary_diversified(self):
        label = _compute_revenue_label(1_500.0, 5)
        self.assertEqual(label, "DIVERSIFIED")

    def test_returns_string(self):
        label = _compute_revenue_label(5_000.0, 3)
        self.assertIsInstance(label, str)


# ─────────────────────────────────────────────────────────────────
# 6. _get_primary_source
# ─────────────────────────────────────────────────────────────────

class TestGetPrimarySource(unittest.TestCase):

    def test_single_source(self):
        sources = [_src("fees", 100_000.0)]
        primary = _get_primary_source(sources)
        self.assertEqual(primary["source_type"], "fees")

    def test_picks_highest_revenue(self):
        sources = [
            _src("fees", 60_000.0),
            _src("interest", 30_000.0),
            _src("liquidations", 10_000.0),
        ]
        primary = _get_primary_source(sources)
        self.assertEqual(primary["source_type"], "fees")

    def test_empty_sources_returns_none(self):
        primary = _get_primary_source([])
        self.assertIsNone(primary)

    def test_all_equal_returns_any(self):
        sources = [_src(f"t{i}", 50_000.0) for i in range(3)]
        primary = _get_primary_source(sources)
        self.assertIsNotNone(primary)

    def test_returns_dict(self):
        sources = [_src("fees", 100_000.0)]
        primary = _get_primary_source(sources)
        self.assertIsInstance(primary, dict)


# ─────────────────────────────────────────────────────────────────
# 7. _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def _no_flags_protocol(self):
        return {
            "token_price_dependency": 0.2,
            "primary_source": _src("fees", 100_000.0, "stable"),
            "age_months": 24.0,
            "chain_count": 3,
            "hhi": 4_000.0,
        }

    def test_no_flags(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "stable"), 24.0, 3, 4_000.0)
        self.assertEqual(flags, [])

    def test_token_price_dependent_flag(self):
        flags = _compute_flags(0.8, _src("fees", 100_000.0, "stable"), 24.0, 3, 3_000.0)
        self.assertIn("TOKEN_PRICE_DEPENDENT", flags)

    def test_declining_primary_flag(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "declining"), 24.0, 3, 3_000.0)
        self.assertIn("DECLINING_PRIMARY", flags)

    def test_young_protocol_flag(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "stable"), 3.0, 3, 3_000.0)
        self.assertIn("YOUNG_PROTOCOL", flags)

    def test_single_chain_flag(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "stable"), 24.0, 1, 3_000.0)
        self.assertIn("SINGLE_CHAIN", flags)

    def test_high_hhi_flag(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "stable"), 24.0, 3, 6_000.0)
        self.assertIn("HIGH_HHI", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(0.9, _src("fees", 100_000.0, "declining"), 2.0, 1, 8_000.0)
        self.assertIn("TOKEN_PRICE_DEPENDENT", flags)
        self.assertIn("DECLINING_PRIMARY", flags)
        self.assertIn("YOUNG_PROTOCOL", flags)
        self.assertIn("SINGLE_CHAIN", flags)
        self.assertIn("HIGH_HHI", flags)

    def test_no_primary_source_no_declining_flag(self):
        flags = _compute_flags(0.2, None, 24.0, 3, 3_000.0)
        self.assertNotIn("DECLINING_PRIMARY", flags)

    def test_exact_dependency_threshold_not_flagged(self):
        # 0.7 is NOT > 0.7 → no flag
        flags = _compute_flags(0.7, None, 24.0, 3, 3_000.0)
        self.assertNotIn("TOKEN_PRICE_DEPENDENT", flags)

    def test_returns_list(self):
        flags = _compute_flags(0.2, None, 24.0, 3, 3_000.0)
        self.assertIsInstance(flags, list)

    def test_growing_primary_no_declining_flag(self):
        flags = _compute_flags(0.2, _src("fees", 100_000.0, "growing"), 24.0, 3, 3_000.0)
        self.assertNotIn("DECLINING_PRIMARY", flags)

    def test_zero_chain_count_single_chain(self):
        flags = _compute_flags(0.2, None, 24.0, 0, 3_000.0)
        self.assertIn("SINGLE_CHAIN", flags)

    def test_exactly_6_months_not_young(self):
        # age=6 is NOT < 6 → no YOUNG_PROTOCOL
        flags = _compute_flags(0.2, None, 6.0, 3, 3_000.0)
        self.assertNotIn("YOUNG_PROTOCOL", flags)


# ─────────────────────────────────────────────────────────────────
# 8. _effective_total_revenue
# ─────────────────────────────────────────────────────────────────

class TestEffectiveTotalRevenue(unittest.TestCase):

    def test_uses_explicit_total(self):
        p = {"total_monthly_revenue_usd": 500_000.0, "revenue_sources": [_src("fees", 100_000.0)]}
        self.assertAlmostEqual(_effective_total_revenue(p), 500_000.0)

    def test_computes_from_sources_if_missing(self):
        p = {"revenue_sources": [_src("fees", 60_000.0), _src("interest", 40_000.0)]}
        self.assertAlmostEqual(_effective_total_revenue(p), 100_000.0)

    def test_zero_explicit_total(self):
        p = {"total_monthly_revenue_usd": 0.0}
        self.assertAlmostEqual(_effective_total_revenue(p), 0.0)

    def test_negative_explicit_total_falls_back(self):
        # Negative explicit → falls back to computing from sources
        p = {
            "total_monthly_revenue_usd": -100.0,
            "revenue_sources": [_src("fees", 50_000.0)],
        }
        self.assertAlmostEqual(_effective_total_revenue(p), 50_000.0)

    def test_no_sources_and_no_total(self):
        p = {}
        self.assertAlmostEqual(_effective_total_revenue(p), 0.0)


# ─────────────────────────────────────────────────────────────────
# 9. _score_protocol
# ─────────────────────────────────────────────────────────────────

class TestScoreProtocol(unittest.TestCase):

    def test_returns_dict(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        for k in [
            "name", "herfindahl_index", "diversification_score",
            "revenue_stability_score", "price_independence_score",
            "revenue_label", "flags", "source_count", "total_monthly_revenue_usd",
            "age_months", "chain_count", "user_count", "primary_source_type",
            "source_summary",
        ]:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_name_preserved(self):
        p = _make_protocol(name="AaveV3")
        result = _score_protocol(p, {})
        self.assertEqual(result["name"], "AaveV3")

    def test_hhi_in_range(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertGreaterEqual(result["herfindahl_index"], 0.0)
        self.assertLessEqual(result["herfindahl_index"], 10_000.0)

    def test_diversification_score_in_range(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertGreaterEqual(result["diversification_score"], 0.0)
        self.assertLessEqual(result["diversification_score"], 100.0)

    def test_stability_score_in_range(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertGreaterEqual(result["revenue_stability_score"], 0.0)
        self.assertLessEqual(result["revenue_stability_score"], 100.0)

    def test_price_independence_in_range(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertGreaterEqual(result["price_independence_score"], 0.0)
        self.assertLessEqual(result["price_independence_score"], 100.0)

    def test_revenue_label_is_valid(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        valid = {"SINGLE_SOURCE", "CONCENTRATED", "MODERATE", "DIVERSIFIED", "HIGHLY_DIVERSIFIED"}
        self.assertIn(result["revenue_label"], valid)

    def test_flags_is_list(self):
        p = _make_protocol()
        result = _score_protocol(p, {})
        self.assertIsInstance(result["flags"], list)

    def test_source_count_correct(self):
        sources = [_src("fees"), _src("interest"), _src("liquidations")]
        p = _make_protocol(sources=sources)
        result = _score_protocol(p, {})
        self.assertEqual(result["source_count"], 3)

    def test_young_protocol_flagged(self):
        p = _make_protocol(age_months=2.0)
        result = _score_protocol(p, {})
        self.assertIn("YOUNG_PROTOCOL", result["flags"])

    def test_single_chain_flagged(self):
        p = _make_protocol(chain_count=1)
        result = _score_protocol(p, {})
        self.assertIn("SINGLE_CHAIN", result["flags"])

    def test_token_price_dependent_flagged(self):
        p = _make_protocol(token_price_dependency=0.9)
        result = _score_protocol(p, {})
        self.assertIn("TOKEN_PRICE_DEPENDENT", result["flags"])

    def test_primary_source_type_correct(self):
        sources = [_src("fees", 70_000.0), _src("interest", 30_000.0)]
        p = _make_protocol(sources=sources)
        result = _score_protocol(p, {})
        self.assertEqual(result["primary_source_type"], "fees")

    def test_source_summary_length(self):
        sources = [_src("fees"), _src("interest")]
        p = _make_protocol(sources=sources)
        result = _score_protocol(p, {})
        self.assertEqual(len(result["source_summary"]), 2)

    def test_source_summary_share_pcts_sum_to_100(self):
        sources = [
            _src("fees", 60_000.0),
            _src("interest", 30_000.0),
            _src("liquidations", 10_000.0),
        ]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = _score_protocol(p, {})
        total_pct = sum(s["share_pct"] for s in result["source_summary"])
        self.assertAlmostEqual(total_pct, 100.0, places=1)

    def test_empty_sources_handled(self):
        p = _make_protocol(sources=[], total_revenue=0.0)
        result = _score_protocol(p, {})
        self.assertIsInstance(result, dict)
        self.assertEqual(result["source_count"], 0)

    def test_single_source_single_source_label(self):
        sources = [_src("fees", 100_000.0)]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = _score_protocol(p, {})
        self.assertEqual(result["revenue_label"], "SINGLE_SOURCE")

    def test_high_dependency_low_independence(self):
        p = _make_protocol(token_price_dependency=0.95)
        result = _score_protocol(p, {})
        self.assertLess(result["price_independence_score"], 10.0)


# ─────────────────────────────────────────────────────────────────
# 10. ProtocolRevenueDiversificationScorer.score()
# ─────────────────────────────────────────────────────────────────

class TestScoreMethod(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "revenue_diversification_log.json")
        self.config = {"data_file": self.data_file}
        self.scorer = ProtocolRevenueDiversificationScorer()

    def test_empty_protocols_returns_valid(self):
        result = self.scorer.score([], self.config)
        self.assertIn("protocols", result)
        self.assertEqual(result["protocol_count"], 0)

    def test_single_protocol(self):
        protocols = [_make_protocol()]
        result = self.scorer.score(protocols, self.config)
        self.assertEqual(result["protocol_count"], 1)
        self.assertEqual(len(result["protocols"]), 1)

    def test_multiple_protocols(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(5)]
        result = self.scorer.score(protocols, self.config)
        self.assertEqual(result["protocol_count"], 5)

    def test_aggregates_present(self):
        protocols = [_make_protocol()]
        result = self.scorer.score(protocols, self.config)
        agg = result["aggregates"]
        for k in ["most_diversified", "least_diversified", "average_hhi", "average_diversification", "highly_diversified_count"]:
            self.assertIn(k, agg)

    def test_average_hhi_correct(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(3)]
        result = self.scorer.score(protocols, self.config)
        expected_avg = sum(r["herfindahl_index"] for r in result["protocols"]) / 3
        self.assertAlmostEqual(result["aggregates"]["average_hhi"], expected_avg, places=1)

    def test_average_diversification_correct(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(4)]
        result = self.scorer.score(protocols, self.config)
        expected_avg = sum(r["diversification_score"] for r in result["protocols"]) / 4
        self.assertAlmostEqual(result["aggregates"]["average_diversification"], expected_avg, places=1)

    def test_most_diversified_lowest_hhi(self):
        # P0: single source (high HHI), P1: many sources (low HHI)
        p_concentrated = _make_protocol(name="Concentrated", sources=[_src("fees", 100_000.0)])
        p_diversified = _make_protocol(name="Diversified", sources=[_src(f"t{i}", 10_000.0) for i in range(10)])
        result = self.scorer.score([p_concentrated, p_diversified], self.config)
        self.assertEqual(result["aggregates"]["most_diversified"], "Diversified")

    def test_least_diversified_highest_hhi(self):
        p_concentrated = _make_protocol(name="Concentrated", sources=[_src("fees", 100_000.0)])
        p_diversified = _make_protocol(name="Diversified", sources=[_src(f"t{i}", 10_000.0) for i in range(10)])
        result = self.scorer.score([p_concentrated, p_diversified], self.config)
        self.assertEqual(result["aggregates"]["least_diversified"], "Concentrated")

    def test_highly_diversified_count(self):
        # Protocol with HHI < 1500 → HIGHLY_DIVERSIFIED
        p_hd = _make_protocol(name="HD", sources=[_src(f"t{i}", 10_000.0) for i in range(10)])
        p_conc = _make_protocol(name="Conc", sources=[_src("fees", 100_000.0)])
        result = self.scorer.score([p_hd, p_conc], self.config)
        self.assertEqual(result["aggregates"]["highly_diversified_count"], 1)

    def test_timestamp_present(self):
        result = self.scorer.score([], self.config)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_log_file_created(self):
        self.scorer.score([_make_protocol()], self.config)
        self.assertTrue(os.path.exists(self.data_file))

    def test_log_file_valid_json(self):
        self.scorer.score([_make_protocol()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_appends_entries(self):
        for _ in range(3):
            self.scorer.score([_make_protocol()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_log_ring_buffer_capped_at_100(self):
        for _ in range(105):
            self.scorer.score([_make_protocol()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_entry_has_aggregates(self):
        self.scorer.score([_make_protocol()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIn("aggregates", log[0])

    def test_log_entry_has_ts(self):
        self.scorer.score([_make_protocol()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIn("ts", log[0])

    def test_config_none_handled(self):
        with patch.object(ProtocolRevenueDiversificationScorer, "_write_log"):
            result = self.scorer.score([_make_protocol()], None)
        self.assertIsInstance(result, dict)

    def test_protocols_list_ordered(self):
        names = [f"P{i}" for i in range(4)]
        protocols = [_make_protocol(name=n) for n in names]
        result = self.scorer.score(protocols, self.config)
        result_names = [p["name"] for p in result["protocols"]]
        self.assertEqual(result_names, names)

    def test_highly_diversified_count_zero_when_none(self):
        # All single-source → no HIGHLY_DIVERSIFIED
        protocols = [_make_protocol(sources=[_src("fees", 100_000.0)]) for _ in range(3)]
        result = self.scorer.score(protocols, self.config)
        self.assertEqual(result["aggregates"]["highly_diversified_count"], 0)


# ─────────────────────────────────────────────────────────────────
# 11. Edge cases & integration
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "revenue_diversification_log.json")
        self.config = {"data_file": self.data_file}
        self.scorer = ProtocolRevenueDiversificationScorer()

    def test_all_zero_revenue_sources(self):
        sources = [_src("fees", 0.0), _src("interest", 0.0)]
        p = _make_protocol(sources=sources, total_revenue=0.0)
        result = self.scorer.score([p], self.config)
        self.assertIsInstance(result, dict)

    def test_corrupt_log_file_reset(self):
        with open(self.data_file, "w") as f:
            f.write("{{bad json")
        result = self.scorer.score([_make_protocol()], self.config)
        self.assertIsInstance(result, dict)

    def test_many_sources(self):
        sources = [_src(f"type_{i}", float(10_000 + i * 1000)) for i in range(20)]
        total = sum(s["monthly_usd"] for s in sources)
        p = _make_protocol(sources=sources, total_revenue=total)
        result = self.scorer.score([p], self.config)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["protocols"][0]["source_count"], 20)

    def test_ten_protocols_aggregates(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(10)]
        result = self.scorer.score(protocols, self.config)
        self.assertEqual(result["protocol_count"], 10)
        self.assertGreater(result["aggregates"]["average_hhi"], 0.0)

    def test_all_equal_hhi_any_name_returned(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(3)]
        result = self.scorer.score(protocols, self.config)
        names = {p["name"] for p in protocols}
        self.assertIn(result["aggregates"]["most_diversified"], names)
        self.assertIn(result["aggregates"]["least_diversified"], names)

    def test_protocol_with_declining_primary_revenue_flagged(self):
        sources = [
            _src("fees", 90_000.0, "declining"),
            _src("interest", 10_000.0, "stable"),
        ]
        p = _make_protocol(sources=sources)
        result = self.scorer.score([p], self.config)
        self.assertIn("DECLINING_PRIMARY", result["protocols"][0]["flags"])

    def test_very_old_protocol_no_young_flag(self):
        p = _make_protocol(age_months=60.0)
        result = self.scorer.score([p], self.config)
        self.assertNotIn("YOUNG_PROTOCOL", result["protocols"][0]["flags"])

    def test_all_growing_high_stability(self):
        sources = [_src(f"t{i}", 50_000.0, "growing") for i in range(2)]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = self.scorer.score([p], self.config)
        self.assertAlmostEqual(result["protocols"][0]["revenue_stability_score"], 100.0)

    def test_hhi_consistency_with_diversification_score(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(3)]
        result = self.scorer.score(protocols, self.config)
        for r in result["protocols"]:
            expected_div = _compute_diversification_score(r["herfindahl_index"])
            self.assertAlmostEqual(r["diversification_score"], expected_div, places=1)

    def test_source_summary_has_source_type(self):
        sources = [_src("fees", 60_000.0), _src("interest", 40_000.0)]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = self.scorer.score([p], self.config)
        for s in result["protocols"][0]["source_summary"]:
            self.assertIn("source_type", s)

    def test_source_summary_has_trend(self):
        sources = [_src("fees", 60_000.0, "growing"), _src("interest", 40_000.0, "declining")]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = self.scorer.score([p], self.config)
        trends = {s["trend"] for s in result["protocols"][0]["source_summary"]}
        self.assertIn("growing", trends)
        self.assertIn("declining", trends)

    def test_zero_chain_count_single_chain_flagged(self):
        p = _make_protocol(chain_count=0)
        result = self.scorer.score([p], self.config)
        self.assertIn("SINGLE_CHAIN", result["protocols"][0]["flags"])

    def test_five_sources_low_hhi(self):
        sources = [_src(f"t{i}", 20_000.0) for i in range(5)]
        p = _make_protocol(sources=sources, total_revenue=100_000.0)
        result = self.scorer.score([p], self.config)
        # 5 equal sources → HHI = 5 * (20%)^2 = 5 * 400 = 2000
        self.assertAlmostEqual(result["protocols"][0]["herfindahl_index"], 2_000.0, places=0)


if __name__ == "__main__":
    unittest.main()
