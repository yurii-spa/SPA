"""
MP-787 — unit tests for ProtocolInsuranceScorer.
≥65 tests, unittest only, stdlib only.
"""

import json
import math
import os
import sys
import tempfile
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.protocol_insurance_scorer import (
    ProtocolInsuranceScorer,
    _coverage_score,
    _treasury_score,
    _bug_bounty_score,
    _timelock_score,
    _protection_tier,
    _COVERAGE_MAX,
    _TREASURY_MAX,
    _BUG_BOUNTY_MAX,
    _TIMELOCK_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(**kwargs):
    base = {
        "protocol": "TestProto",
        "has_insurance": True,
        "insurance_coverage_pct": 50.0,
        "insurance_provider": "Nexus Mutual",
        "treasury_usd": 10_000_000.0,
        "tvl_usd": 100_000_000.0,
        "bug_bounty_usd": 500_000.0,
        "has_timelock": True,
        "timelock_days": 5,
    }
    base.update(kwargs)
    return base


def _scorer(tmp_dir):
    return ProtocolInsuranceScorer(data_dir=tmp_dir)


# ---------------------------------------------------------------------------
# 1. _coverage_score
# ---------------------------------------------------------------------------

class TestCoverageScore(unittest.TestCase):

    def test_full_coverage_max_pts(self):
        # 100% coverage → 100 * 0.4 = 40, capped at 40
        self.assertAlmostEqual(_coverage_score(True, 100.0), _COVERAGE_MAX, places=4)

    def test_zero_coverage_zero_pts(self):
        self.assertAlmostEqual(_coverage_score(True, 0.0), 0.0, places=4)

    def test_no_insurance_zero_pts(self):
        self.assertAlmostEqual(_coverage_score(False, 80.0), 0.0, places=4)

    def test_50pct_coverage_gives_20_pts(self):
        # 50 * 0.4 = 20
        self.assertAlmostEqual(_coverage_score(True, 50.0), 20.0, places=4)

    def test_80pct_coverage_gives_32_pts(self):
        self.assertAlmostEqual(_coverage_score(True, 80.0), 32.0, places=4)

    def test_25pct_coverage_gives_10_pts(self):
        self.assertAlmostEqual(_coverage_score(True, 25.0), 10.0, places=4)

    def test_cap_at_40(self):
        self.assertLessEqual(_coverage_score(True, 100.0), _COVERAGE_MAX)
        self.assertLessEqual(_coverage_score(True, 150.0), _COVERAGE_MAX)

    def test_returns_float(self):
        self.assertIsInstance(_coverage_score(True, 50.0), float)

    def test_no_insurance_true_but_pct_zero(self):
        self.assertAlmostEqual(_coverage_score(True, 0.0), 0.0, places=4)


# ---------------------------------------------------------------------------
# 2. _treasury_score
# ---------------------------------------------------------------------------

class TestTreasuryScore(unittest.TestCase):

    def test_20pct_ratio_gives_30_pts(self):
        # ratio = 0.20 → log10(1+1)/log10(2)*30 = 1.0/1.0*30 = 30
        score = _treasury_score(20_000_000, 100_000_000)
        self.assertAlmostEqual(score, _TREASURY_MAX, places=3)

    def test_zero_treasury_gives_zero(self):
        self.assertAlmostEqual(_treasury_score(0, 100_000_000), 0.0, places=4)

    def test_zero_tvl_gives_zero(self):
        self.assertAlmostEqual(_treasury_score(10_000_000, 0), 0.0, places=4)

    def test_capped_at_30(self):
        # Very high treasury/TVL
        score = _treasury_score(1_000_000_000, 100_000_000)
        self.assertLessEqual(score, _TREASURY_MAX)

    def test_higher_ratio_higher_score(self):
        s1 = _treasury_score(1_000_000, 100_000_000)   # 1%
        s2 = _treasury_score(10_000_000, 100_000_000)  # 10%
        s3 = _treasury_score(20_000_000, 100_000_000)  # 20%
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)

    def test_log_scale_50pct_more_than_half_max(self):
        # 50% ratio is double the 20% → should give more than 30, but capped
        score = _treasury_score(50_000_000, 100_000_000)
        self.assertAlmostEqual(score, _TREASURY_MAX, places=1)

    def test_10pct_ratio_gives_positive(self):
        score = _treasury_score(10_000_000, 100_000_000)
        self.assertGreater(score, 0.0)
        self.assertLess(score, _TREASURY_MAX)

    def test_negative_treasury_gives_zero(self):
        self.assertAlmostEqual(_treasury_score(-1, 100_000_000), 0.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_treasury_score(1_000_000, 10_000_000), float)


# ---------------------------------------------------------------------------
# 3. _bug_bounty_score
# ---------------------------------------------------------------------------

class TestBugBountyScore(unittest.TestCase):

    def test_1m_bounty_gives_20_pts(self):
        # log10(1+1)/log10(2)*20 = 1.0*20 = 20
        score = _bug_bounty_score(1_000_000)
        self.assertAlmostEqual(score, _BUG_BOUNTY_MAX, places=3)

    def test_zero_bounty_gives_zero(self):
        self.assertAlmostEqual(_bug_bounty_score(0), 0.0, places=4)

    def test_negative_bounty_gives_zero(self):
        self.assertAlmostEqual(_bug_bounty_score(-100), 0.0, places=4)

    def test_capped_at_20(self):
        score = _bug_bounty_score(100_000_000)
        self.assertLessEqual(score, _BUG_BOUNTY_MAX)

    def test_higher_bounty_higher_score(self):
        s1 = _bug_bounty_score(10_000)
        s2 = _bug_bounty_score(100_000)
        s3 = _bug_bounty_score(1_000_000)
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)

    def test_500k_bounty_positive(self):
        score = _bug_bounty_score(500_000)
        self.assertGreater(score, 0.0)
        self.assertLess(score, _BUG_BOUNTY_MAX)

    def test_100k_bounty_less_than_1m(self):
        self.assertLess(_bug_bounty_score(100_000), _bug_bounty_score(1_000_000))

    def test_returns_float(self):
        self.assertIsInstance(_bug_bounty_score(500_000), float)


# ---------------------------------------------------------------------------
# 4. _timelock_score
# ---------------------------------------------------------------------------

class TestTimelockScore(unittest.TestCase):

    def test_no_timelock_gives_zero(self):
        self.assertAlmostEqual(_timelock_score(False, 30), 0.0, places=4)

    def test_10_days_gives_10_pts(self):
        self.assertAlmostEqual(_timelock_score(True, 10), 10.0, places=4)

    def test_5_days_gives_5_pts(self):
        self.assertAlmostEqual(_timelock_score(True, 5), 5.0, places=4)

    def test_more_than_10_days_capped_at_10(self):
        self.assertAlmostEqual(_timelock_score(True, 30), 10.0, places=4)
        self.assertAlmostEqual(_timelock_score(True, 100), 10.0, places=4)

    def test_zero_days_with_timelock_gives_zero(self):
        self.assertAlmostEqual(_timelock_score(True, 0), 0.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_timelock_score(True, 5), float)

    def test_capped_at_10(self):
        score = _timelock_score(True, 9999)
        self.assertLessEqual(score, _TIMELOCK_MAX)


# ---------------------------------------------------------------------------
# 5. _protection_tier
# ---------------------------------------------------------------------------

class TestProtectionTier(unittest.TestCase):

    def test_fortress_at_80(self):
        self.assertEqual(_protection_tier(80.0), "FORTRESS")

    def test_fortress_at_100(self):
        self.assertEqual(_protection_tier(100.0), "FORTRESS")

    def test_fortress_at_95(self):
        self.assertEqual(_protection_tier(95.0), "FORTRESS")

    def test_protected_at_60(self):
        self.assertEqual(_protection_tier(60.0), "PROTECTED")

    def test_protected_at_79(self):
        self.assertEqual(_protection_tier(79.9), "PROTECTED")

    def test_partial_at_40(self):
        self.assertEqual(_protection_tier(40.0), "PARTIAL")

    def test_partial_at_59(self):
        self.assertEqual(_protection_tier(59.9), "PARTIAL")

    def test_exposed_at_0(self):
        self.assertEqual(_protection_tier(0.0), "EXPOSED")

    def test_exposed_at_39(self):
        self.assertEqual(_protection_tier(39.9), "EXPOSED")

    def test_boundary_80_is_fortress(self):
        self.assertEqual(_protection_tier(80.0), "FORTRESS")

    def test_boundary_60_is_protected(self):
        self.assertEqual(_protection_tier(60.0), "PROTECTED")

    def test_boundary_40_is_partial(self):
        self.assertEqual(_protection_tier(40.0), "PARTIAL")


# ---------------------------------------------------------------------------
# 6. score() — structure and values
# ---------------------------------------------------------------------------

class TestScoreStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _scorer(self.tmp)

    def test_returns_dict(self):
        result = self.scorer.score(_make_data())
        self.assertIsInstance(result, dict)

    def test_has_all_required_keys(self):
        result = self.scorer.score(_make_data())
        for k in [
            "protocol", "coverage_score", "treasury_score",
            "bug_bounty_score", "timelock_score",
            "total_insurance_score", "protection_tier", "computed_at",
        ]:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_total_equals_sum_of_components(self):
        result = self.scorer.score(_make_data())
        component_sum = (
            result["coverage_score"]
            + result["treasury_score"]
            + result["bug_bounty_score"]
            + result["timelock_score"]
        )
        self.assertAlmostEqual(result["total_insurance_score"], component_sum, places=3)

    def test_total_never_exceeds_100(self):
        # Extreme values to push past 100
        data = _make_data(
            has_insurance=True, insurance_coverage_pct=100,
            treasury_usd=500_000_000, tvl_usd=100_000_000,
            bug_bounty_usd=100_000_000,
            has_timelock=True, timelock_days=100,
        )
        result = self.scorer.score(data)
        self.assertLessEqual(result["total_insurance_score"], 100.0)

    def test_all_zeros_gives_exposed_tier(self):
        data = _make_data(
            has_insurance=False, insurance_coverage_pct=0,
            treasury_usd=0, tvl_usd=1_000_000,
            bug_bounty_usd=0,
            has_timelock=False, timelock_days=0,
        )
        result = self.scorer.score(data)
        self.assertEqual(result["protection_tier"], "EXPOSED")
        self.assertAlmostEqual(result["total_insurance_score"], 0.0, places=4)

    def test_protocol_preserved(self):
        result = self.scorer.score(_make_data(protocol="Aave V3"))
        self.assertEqual(result["protocol"], "Aave V3")

    def test_computed_at_is_iso_string(self):
        result = self.scorer.score(_make_data())
        self.assertIn("T", result["computed_at"])

    def test_treasury_ratio_computed(self):
        data = _make_data(treasury_usd=20_000_000, tvl_usd=100_000_000)
        result = self.scorer.score(data)
        self.assertAlmostEqual(result["treasury_tvl_ratio"], 0.20, places=4)


# ---------------------------------------------------------------------------
# 7. Protection tier integration
# ---------------------------------------------------------------------------

class TestProtectionTierIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _scorer(self.tmp)

    def test_fortress_protocol(self):
        data = _make_data(
            has_insurance=True, insurance_coverage_pct=100.0,
            treasury_usd=30_000_000, tvl_usd=100_000_000,
            bug_bounty_usd=1_000_000,
            has_timelock=True, timelock_days=10,
        )
        result = self.scorer.score(data)
        self.assertEqual(result["protection_tier"], "FORTRESS")

    def test_exposed_protocol(self):
        data = _make_data(
            has_insurance=False, insurance_coverage_pct=0,
            treasury_usd=0, tvl_usd=50_000_000,
            bug_bounty_usd=0,
            has_timelock=False, timelock_days=0,
        )
        result = self.scorer.score(data)
        self.assertEqual(result["protection_tier"], "EXPOSED")


# ---------------------------------------------------------------------------
# 8. get_protection_tier() and get_score_breakdown()
# ---------------------------------------------------------------------------

class TestGetters(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _scorer(self.tmp)

    def test_protection_tier_none_before_score(self):
        self.assertIsNone(self.scorer.get_protection_tier())

    def test_score_breakdown_none_before_score(self):
        self.assertIsNone(self.scorer.get_score_breakdown())

    def test_get_protection_tier_returns_string(self):
        self.scorer.score(_make_data())
        tier = self.scorer.get_protection_tier()
        self.assertIsInstance(tier, str)
        self.assertIn(tier, ["FORTRESS", "PROTECTED", "PARTIAL", "EXPOSED"])

    def test_get_score_breakdown_keys(self):
        self.scorer.score(_make_data())
        bd = self.scorer.get_score_breakdown()
        for k in ("protocol", "coverage_score", "treasury_score",
                   "bug_bounty_score", "timelock_score",
                   "total_insurance_score", "protection_tier", "score_max"):
            self.assertIn(k, bd)

    def test_score_max_correct(self):
        self.scorer.score(_make_data())
        bd = self.scorer.get_score_breakdown()
        self.assertEqual(bd["score_max"]["coverage"],   40)
        self.assertEqual(bd["score_max"]["treasury"],   30)
        self.assertEqual(bd["score_max"]["bug_bounty"], 20)
        self.assertEqual(bd["score_max"]["timelock"],   10)
        self.assertEqual(bd["score_max"]["total"],      100)

    def test_tier_reflects_latest_score(self):
        # First call: well-insured
        self.scorer.score(_make_data(
            has_insurance=True, insurance_coverage_pct=100,
            treasury_usd=200_000_000, tvl_usd=100_000_000,
            bug_bounty_usd=1_000_000,
            has_timelock=True, timelock_days=10,
        ))
        tier1 = self.scorer.get_protection_tier()
        # Second call: bare
        self.scorer.score(_make_data(
            has_insurance=False, insurance_coverage_pct=0,
            treasury_usd=0, tvl_usd=100_000_000,
            bug_bounty_usd=0, has_timelock=False, timelock_days=0,
        ))
        tier2 = self.scorer.get_protection_tier()
        self.assertNotEqual(tier1, tier2)
        self.assertEqual(tier2, "EXPOSED")


# ---------------------------------------------------------------------------
# 9. Validation errors
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _scorer(self.tmp)

    def _missing(self, key):
        data = _make_data()
        del data[key]
        with self.assertRaises(ValueError):
            self.scorer.score(data)

    def test_missing_protocol(self):
        self._missing("protocol")

    def test_missing_has_insurance(self):
        self._missing("has_insurance")

    def test_missing_insurance_coverage_pct(self):
        self._missing("insurance_coverage_pct")

    def test_missing_insurance_provider(self):
        self._missing("insurance_provider")

    def test_missing_treasury_usd(self):
        self._missing("treasury_usd")

    def test_missing_tvl_usd(self):
        self._missing("tvl_usd")

    def test_missing_bug_bounty_usd(self):
        self._missing("bug_bounty_usd")

    def test_missing_has_timelock(self):
        self._missing("has_timelock")

    def test_missing_timelock_days(self):
        self._missing("timelock_days")

    def test_coverage_pct_above_100_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(insurance_coverage_pct=101.0))

    def test_coverage_pct_negative_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(insurance_coverage_pct=-1.0))

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(tvl_usd=-100))

    def test_negative_treasury_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(treasury_usd=-100))

    def test_negative_bug_bounty_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(bug_bounty_usd=-100))

    def test_negative_timelock_days_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score(_make_data(timelock_days=-1))

    def test_zero_tvl_allowed(self):
        # tvl_usd=0 is edge case: treasury_score = 0
        result = self.scorer.score(_make_data(tvl_usd=0, treasury_usd=0))
        self.assertAlmostEqual(result["treasury_score"], 0.0, places=4)


# ---------------------------------------------------------------------------
# 10. Ring-buffer log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _scorer(self.tmp)

    def test_log_file_created_after_score(self):
        self.scorer.score(_make_data())
        log_path = os.path.join(self.tmp, "protocol_insurance_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        self.scorer.score(_make_data())
        log_path = os.path.join(self.tmp, "protocol_insurance_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows(self):
        self.scorer.score(_make_data())
        self.scorer.score(_make_data())
        log = self.scorer.get_log()
        self.assertEqual(len(log), 2)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            self.scorer.score(_make_data(protocol=f"Proto{i}"))
        log = self.scorer.get_log()
        self.assertEqual(len(log), 100)

    def test_ring_buffer_most_recent_kept(self):
        for i in range(105):
            self.scorer.score(_make_data(protocol=f"Proto{i}"))
        log = self.scorer.get_log()
        self.assertEqual(log[-1]["protocol"], "Proto104")

    def test_get_log_empty_initially(self):
        log = self.scorer.get_log()
        self.assertEqual(log, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
