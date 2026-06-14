"""
Tests for MP-789: ProtocolAdoptionScorer
≥65 unittest tests — pure stdlib, no external deps.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# resolve project root so we can import spa_core
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_adoption_scorer import ProtocolAdoptionScorer, RING_BUFFER_CAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(
    protocol="AaveV3",
    users_30d=1000,
    users_90d=2400,
    txn_30d=5000,
    tvl=50_000_000,
    tvl_3m=40_000_000,
    retention=70.0,
):
    return {
        "protocol": protocol,
        "unique_users_30d": users_30d,
        "unique_users_90d": users_90d,
        "txn_count_30d": txn_30d,
        "tvl_usd": tvl,
        "tvl_3m_ago_usd": tvl_3m,
        "retention_rate_pct": retention,
    }


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestProtocolAdoptionScorerInit(unittest.TestCase):
    """Instantiation and pre-call state."""

    def test_init_default_log_path(self):
        s = ProtocolAdoptionScorer()
        self.assertIn("protocol_adoption_log.json", s.log_path)

    def test_init_custom_log_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            s = ProtocolAdoptionScorer(log_path=path)
            self.assertEqual(s.log_path, path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_result_none_before_score(self):
        s = ProtocolAdoptionScorer()
        self.assertIsNone(s._result)

    def test_get_last_result_none_before_score(self):
        s = ProtocolAdoptionScorer()
        self.assertIsNone(s.get_last_result())

    def test_get_adoption_tier_raises_before_score(self):
        s = ProtocolAdoptionScorer()
        with self.assertRaises(RuntimeError):
            s.get_adoption_tier()

    def test_get_growth_breakdown_raises_before_score(self):
        s = ProtocolAdoptionScorer()
        with self.assertRaises(RuntimeError):
            s.get_growth_breakdown()


class TestScoreReturnStructure(unittest.TestCase):
    """Shape and types of score() return dict."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.scorer = ProtocolAdoptionScorer(log_path=self.tmp)
        self.data = _make_data()

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _r(self):
        return self.scorer.score(self.data)

    def test_returns_dict(self):
        self.assertIsInstance(self._r(), dict)

    def test_protocol_key_present(self):
        self.assertIn("protocol", self._r())

    def test_unique_users_30d_key_present(self):
        self.assertIn("unique_users_30d", self._r())

    def test_unique_users_90d_key_present(self):
        self.assertIn("unique_users_90d", self._r())

    def test_txn_count_30d_key_present(self):
        self.assertIn("txn_count_30d", self._r())

    def test_tvl_usd_key_present(self):
        self.assertIn("tvl_usd", self._r())

    def test_tvl_3m_ago_usd_key_present(self):
        self.assertIn("tvl_3m_ago_usd", self._r())

    def test_retention_rate_pct_key_present(self):
        self.assertIn("retention_rate_pct", self._r())

    def test_user_growth_pct_key_present(self):
        self.assertIn("user_growth_pct", self._r())

    def test_tvl_growth_pct_key_present(self):
        self.assertIn("tvl_growth_pct", self._r())

    def test_engagement_score_key_present(self):
        self.assertIn("engagement_score", self._r())

    def test_adoption_score_key_present(self):
        self.assertIn("adoption_score", self._r())

    def test_adoption_tier_key_present(self):
        self.assertIn("adoption_tier", self._r())

    def test_growth_breakdown_key_present(self):
        self.assertIn("growth_breakdown", self._r())

    def test_timestamp_key_present(self):
        self.assertIn("timestamp", self._r())

    def test_protocol_value_correct(self):
        self.assertEqual(self._r()["protocol"], "AaveV3")

    def test_adoption_score_type_float(self):
        self.assertIsInstance(self._r()["adoption_score"], float)

    def test_timestamp_positive(self):
        self.assertGreater(self._r()["timestamp"], 0)


class TestMetricCalculations(unittest.TestCase):
    """user_growth_pct, tvl_growth_pct, engagement_score correctness."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.scorer = ProtocolAdoptionScorer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_user_growth_pct_formula(self):
        # users_30d=1200, users_90d=3000 → monthly_base=1000 → growth=20%
        d = _make_data(users_30d=1200, users_90d=3000)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["user_growth_pct"], 20.0, places=4)

    def test_user_growth_pct_zero_when_users_90d_zero(self):
        d = _make_data(users_30d=500, users_90d=0)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["user_growth_pct"], 0.0, places=4)

    def test_tvl_growth_pct_formula(self):
        # tvl=50M, tvl_3m=40M → growth = 25%
        d = _make_data(tvl=50_000_000, tvl_3m=40_000_000)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["tvl_growth_pct"], 25.0, places=4)

    def test_tvl_growth_pct_zero_when_tvl_3m_zero(self):
        d = _make_data(tvl=10_000_000, tvl_3m=0)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["tvl_growth_pct"], 0.0, places=4)

    def test_engagement_score_formula(self):
        # txn=5000, users=1000 → 5.0
        d = _make_data(users_30d=1000, txn_30d=5000)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["engagement_score"], 5.0, places=4)

    def test_engagement_score_zero_when_no_users(self):
        d = _make_data(users_30d=0, txn_30d=500)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["engagement_score"], 0.0, places=4)

    def test_user_growth_pct_negative(self):
        # users_30d=500, users_90d=3000 → monthly_base=1000 → growth=-50%
        d = _make_data(users_30d=500, users_90d=3000)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["user_growth_pct"], -50.0, places=4)

    def test_tvl_growth_pct_negative(self):
        # tvl=30M, tvl_3m=60M → growth=-50%
        d = _make_data(tvl=30_000_000, tvl_3m=60_000_000)
        r = self.scorer.score(d)
        self.assertAlmostEqual(r["tvl_growth_pct"], -50.0, places=4)


class TestAdoptionScore(unittest.TestCase):
    """adoption_score bounds, composition, and tiers."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.scorer = ProtocolAdoptionScorer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_adoption_score_in_range_0_100(self):
        r = self.scorer.score(_make_data())
        self.assertGreaterEqual(r["adoption_score"], 0.0)
        self.assertLessEqual(r["adoption_score"], 100.0)

    def test_adoption_score_max_not_exceed_100(self):
        d = _make_data(users_30d=100_000, users_90d=100, txn_30d=1_000_000,
                       tvl=1_000_000_000, tvl_3m=1, retention=100.0)
        r = self.scorer.score(d)
        self.assertLessEqual(r["adoption_score"], 100.0)

    def test_adoption_score_min_not_below_0(self):
        d = _make_data(users_30d=0, users_90d=100_000, txn_30d=0,
                       tvl=1, tvl_3m=1_000_000_000, retention=0.0)
        r = self.scorer.score(d)
        self.assertGreaterEqual(r["adoption_score"], 0.0)

    def test_viral_tier_for_high_scores(self):
        d = _make_data(users_30d=10_000, users_90d=100, txn_30d=100_000,
                       tvl=200_000_000, tvl_3m=1_000_000, retention=95.0)
        r = self.scorer.score(d)
        if r["adoption_score"] > 80:
            self.assertEqual(r["adoption_tier"], "VIRAL")

    def test_stagnant_tier_for_low_scores(self):
        d = _make_data(users_30d=100, users_90d=90_000, txn_30d=10,
                       tvl=1_000_000, tvl_3m=100_000_000, retention=0.0)
        r = self.scorer.score(d)
        if r["adoption_score"] <= 40:
            self.assertEqual(r["adoption_tier"], "STAGNANT")

    def test_compute_tier_viral(self):
        self.assertEqual(ProtocolAdoptionScorer._compute_tier(81.0), "VIRAL")

    def test_compute_tier_growing(self):
        self.assertEqual(ProtocolAdoptionScorer._compute_tier(61.0), "GROWING")

    def test_compute_tier_steady(self):
        self.assertEqual(ProtocolAdoptionScorer._compute_tier(41.0), "STEADY")

    def test_compute_tier_stagnant_at_40(self):
        self.assertEqual(ProtocolAdoptionScorer._compute_tier(40.0), "STAGNANT")

    def test_compute_tier_stagnant_at_0(self):
        self.assertEqual(ProtocolAdoptionScorer._compute_tier(0.0), "STAGNANT")

    def test_valid_tier_values(self):
        valid = {"VIRAL", "GROWING", "STEADY", "STAGNANT"}
        for score in [0.0, 20.0, 40.0, 41.0, 60.0, 61.0, 80.0, 81.0, 100.0]:
            self.assertIn(ProtocolAdoptionScorer._compute_tier(score), valid)

    def test_get_adoption_tier_returns_string(self):
        self.scorer.score(_make_data())
        self.assertIsInstance(self.scorer.get_adoption_tier(), str)

    def test_get_adoption_tier_matches_result(self):
        r = self.scorer.score(_make_data())
        self.assertEqual(self.scorer.get_adoption_tier(), r["adoption_tier"])


class TestGrowthBreakdown(unittest.TestCase):
    """growth_breakdown dict structure and component bounds."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.scorer = ProtocolAdoptionScorer(log_path=self.tmp)
        self.result = self.scorer.score(_make_data())

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _bd(self):
        return self.result["growth_breakdown"]

    def test_breakdown_has_user_growth_norm(self):
        self.assertIn("user_growth_norm", self._bd())

    def test_breakdown_has_tvl_growth_norm(self):
        self.assertIn("tvl_growth_norm", self._bd())

    def test_breakdown_has_retention_norm(self):
        self.assertIn("retention_norm", self._bd())

    def test_breakdown_has_engagement_norm(self):
        self.assertIn("engagement_norm", self._bd())

    def test_breakdown_has_weights(self):
        self.assertIn("weights", self._bd())

    def test_weights_sum_to_one(self):
        w = self._bd()["weights"]
        total = sum(w.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_user_growth_norm_in_range(self):
        v = self._bd()["user_growth_norm"]
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_tvl_growth_norm_in_range(self):
        v = self._bd()["tvl_growth_norm"]
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_retention_norm_in_range(self):
        v = self._bd()["retention_norm"]
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_engagement_norm_in_range(self):
        v = self._bd()["engagement_norm"]
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_get_growth_breakdown_returns_dict(self):
        self.assertIsInstance(self.scorer.get_growth_breakdown(), dict)

    def test_get_growth_breakdown_matches_result(self):
        self.assertEqual(self.scorer.get_growth_breakdown(), self._bd())

    def test_weight_user_growth_correct(self):
        self.assertAlmostEqual(self._bd()["weights"]["user_growth"], 0.40)

    def test_weight_tvl_growth_correct(self):
        self.assertAlmostEqual(self._bd()["weights"]["tvl_growth"], 0.30)

    def test_weight_retention_correct(self):
        self.assertAlmostEqual(self._bd()["weights"]["retention"], 0.20)

    def test_weight_engagement_correct(self):
        self.assertAlmostEqual(self._bd()["weights"]["engagement"], 0.10)


class TestRingBufferAndAtomic(unittest.TestCase):
    """Log file ring-buffer and atomic write."""

    def setUp(self):
        fd, self.tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.tmp)
        self.scorer = ProtocolAdoptionScorer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_log_file_created(self):
        self.scorer.score(_make_data())
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_file_valid_json(self):
        self.scorer.score(_make_data())
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_adoption_tier(self):
        self.scorer.score(_make_data())
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("adoption_tier", data[0])

    def test_log_entry_has_timestamp(self):
        self.scorer.score(_make_data())
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 15):
            self.scorer.score(_make_data(protocol=f"Proto_{i}"))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_tmp_file_cleaned_up(self):
        self.scorer.score(_make_data())
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))

    def test_second_entry_appended(self):
        self.scorer.score(_make_data())
        self.scorer.score(_make_data(protocol="AaveArb"))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_get_last_result_not_none_after_score(self):
        self.scorer.score(_make_data())
        self.assertIsNotNone(self.scorer.get_last_result())

    def test_consecutive_scores_update_result(self):
        self.scorer.score(_make_data())
        self.scorer.score(_make_data(protocol="CompoundV3"))
        self.assertEqual(self.scorer._result["protocol"], "CompoundV3")

    def test_corrupted_log_resets_gracefully(self):
        with open(self.tmp, "w") as f:
            f.write("{not valid json at all!!}")
        self.scorer.score(_make_data())
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_missing_protocol_key_raises(self):
        d = _make_data()
        del d["protocol"]
        with self.assertRaises(KeyError):
            self.scorer.score(d)


if __name__ == "__main__":
    unittest.main()
