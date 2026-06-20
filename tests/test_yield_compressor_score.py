"""
tests/test_yield_compressor_score.py

MP-1437 — 20 tests for YieldCompressorScore (spa_core/analytics/yield_compressor_score.py)
Sprint v10.53
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.yield_compressor_score import (
    YieldCompressorScore,
    REGIME_EXPANDING,
    REGIME_STABLE,
    REGIME_COMPRESSING,
    REGIME_SEVERELY_COMPRESSED,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROTOCOLS_COMPRESSING = [
    {"protocol": "Aave V3",    "apy_30d_ago": 4.2,  "apy_now": 3.5,  "tvl_usd": 8_000_000, "category": "lending"},
    {"protocol": "Compound",   "apy_30d_ago": 5.8,  "apy_now": 4.8,  "tvl_usd": 6_000_000, "category": "lending"},
    {"protocol": "Morpho",     "apy_30d_ago": 7.1,  "apy_now": 6.5,  "tvl_usd": 5_500_000, "category": "curated-vault"},
]

_PROTOCOLS_EXPANDING = [
    {"protocol": "Aave V3",    "apy_30d_ago": 3.0,  "apy_now": 5.0,  "tvl_usd": 8_000_000, "category": "lending"},
    {"protocol": "Compound",   "apy_30d_ago": 4.0,  "apy_now": 6.0,  "tvl_usd": 6_000_000, "category": "lending"},
]


class TestInstantiation(unittest.TestCase):
    """TC-YCS-01..03: Class instantiation."""

    def test_01_default_instantiation(self):
        """Default instantiation succeeds."""
        ycs = YieldCompressorScore()
        self.assertIsInstance(ycs, YieldCompressorScore)

    def test_02_custom_data_dir_stored(self):
        """Custom data_dir is stored."""
        ycs = YieldCompressorScore(data_dir="/tmp/test")
        self.assertEqual(ycs._data_dir, "/tmp/test")

    def test_03_last_result_initially_none(self):
        """_last_result is None before compute()."""
        ycs = YieldCompressorScore()
        self.assertIsNone(ycs._last_result)


class TestComputeEmpty(unittest.TestCase):
    """TC-YCS-04..05: compute() with empty input."""

    def test_04_empty_protocols_returns_stable(self):
        """compute([]) returns STABLE regime and score ~50."""
        ycs = YieldCompressorScore()
        result = ycs.compute([])
        self.assertEqual(result["market"]["compression_regime"], REGIME_STABLE)
        self.assertAlmostEqual(result["market"]["market_compression_score"], 50.0, places=1)

    def test_05_empty_protocols_zero_protocol_count(self):
        """compute([]) sets protocol_count=0."""
        ycs = YieldCompressorScore()
        result = ycs.compute([])
        self.assertEqual(result["market"]["protocol_count"], 0)


class TestComputeReturnStructure(unittest.TestCase):
    """TC-YCS-06..10: compute() return structure."""

    def setUp(self):
        self.ycs = YieldCompressorScore()
        self.result = self.ycs.compute(_PROTOCOLS_COMPRESSING)

    def test_06_result_has_required_keys(self):
        """Result contains per_protocol, market, outliers, timestamp."""
        for key in ("timestamp", "per_protocol", "market", "outliers"):
            self.assertIn(key, self.result)

    def test_07_per_protocol_length_matches_input(self):
        """len(per_protocol) == len(input protocols)."""
        self.assertEqual(len(self.result["per_protocol"]), len(_PROTOCOLS_COMPRESSING))

    def test_08_compression_pct_positive_when_apy_dropped(self):
        """compression_pct > 0 when apy_now < apy_30d_ago."""
        for entry in self.result["per_protocol"]:
            self.assertGreater(entry["compression_pct"], 0.0)

    def test_09_market_score_in_range_0_100(self):
        """market_compression_score ∈ [0, 100]."""
        score = self.result["market"]["market_compression_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_10_protocol_count_correct(self):
        """protocol_count matches input length."""
        self.assertEqual(self.result["market"]["protocol_count"], len(_PROTOCOLS_COMPRESSING))


class TestRegimeClassification(unittest.TestCase):
    """TC-YCS-11..14: Regime classification via _score_to_regime."""

    def test_11_score_below_25_is_expanding(self):
        """Score < 25 → EXPANDING."""
        regime = YieldCompressorScore._score_to_regime(10.0)
        self.assertEqual(regime, REGIME_EXPANDING)

    def test_12_score_25_to_49_is_stable(self):
        """Score in [25, 50) → STABLE."""
        regime = YieldCompressorScore._score_to_regime(40.0)
        self.assertEqual(regime, REGIME_STABLE)

    def test_13_score_50_to_75_is_compressing(self):
        """Score in [50, 75] → COMPRESSING."""
        regime = YieldCompressorScore._score_to_regime(60.0)
        self.assertEqual(regime, REGIME_COMPRESSING)

    def test_14_score_above_75_is_severely_compressed(self):
        """Score > 75 → SEVERELY_COMPRESSED."""
        regime = YieldCompressorScore._score_to_regime(90.0)
        self.assertEqual(regime, REGIME_SEVERELY_COMPRESSED)


class TestGetMarketRegime(unittest.TestCase):
    """TC-YCS-15..16: get_market_regime()."""

    def test_15_before_compute_returns_stable(self):
        """get_market_regime() before compute() returns STABLE (default)."""
        ycs = YieldCompressorScore()
        self.assertEqual(ycs.get_market_regime(), REGIME_STABLE)

    def test_16_after_compute_returns_correct_regime(self):
        """get_market_regime() matches market.compression_regime after compute()."""
        ycs = YieldCompressorScore()
        result = ycs.compute(_PROTOCOLS_COMPRESSING)
        self.assertEqual(ycs.get_market_regime(), result["market"]["compression_regime"])


class TestGetCompressedOutliers(unittest.TestCase):
    """TC-YCS-17..18: get_compressed_outliers()."""

    def test_17_before_compute_returns_empty_list(self):
        """get_compressed_outliers() returns [] before compute()."""
        ycs = YieldCompressorScore()
        self.assertEqual(ycs.get_compressed_outliers(), [])

    def test_18_expansion_regime_no_outliers(self):
        """Expanding protocols (apy_now > apy_30d_ago) → 0 outliers."""
        ycs = YieldCompressorScore()
        ycs.compute(_PROTOCOLS_EXPANDING)
        self.assertEqual(ycs.get_compressed_outliers(), [])


class TestSaveAndLoad(unittest.TestCase):
    """TC-YCS-19..20: save/load round-trip."""

    def test_19_save_before_compute_raises_SPAError(self):
        """save() before compute() raises SPAError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ycs = YieldCompressorScore(data_dir=tmpdir)
            with self.assertRaises(SPAError):
                ycs.save(data_dir=tmpdir)

    def test_20_save_and_load_roundtrip(self):
        """compute() + save() writes JSON ring-buffer; reload verifies protocol_count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ycs = YieldCompressorScore(data_dir=tmpdir)
            result = ycs.compute(_PROTOCOLS_COMPRESSING)
            log_path = ycs.save(data_dir=tmpdir)

            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r") as fh:
                log = json.load(fh)

            self.assertIsInstance(log, list)
            self.assertGreater(len(log), 0)
            saved = log[-1]
            self.assertEqual(
                saved["market"]["protocol_count"],
                result["market"]["protocol_count"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
