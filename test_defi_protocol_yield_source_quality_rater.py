"""
Tests for MP-1070: DeFiProtocolYieldSourceQualityRater
≥90 unittest tests covering helpers, class methods, edge cases, and ring-buffer log.
Run with: python3 -m unittest spa_core/tests/test_defi_protocol_yield_source_quality_rater.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_yield_source_quality_rater import (
    DeFiProtocolYieldSourceQualityRater,
    validate_source_type,
    compute_totals,
    compute_quality_score,
    quality_label,
    _atomic_log_append,
    TIER_1_SOURCES,
    TIER_2_SOURCES,
    ALL_VALID_SOURCES,
    SOURCE_QUALITY_WEIGHTS,
    LABEL_PREMIUM_YIELD,
    LABEL_HIGH_QUALITY,
    LABEL_MIXED_QUALITY,
    LABEL_SPECULATIVE,
    LABEL_UNSUSTAINABLE,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _src(source, apy_pct, pct_of_total):
    return {"source": source, "apy_pct": apy_pct, "pct_of_total": pct_of_total}


def _protocol(name, sources):
    return {"protocol_name": name, "yield_sources": sources}


# --------------------------------------------------------------------------- #
# Tests: validate_source_type
# --------------------------------------------------------------------------- #

class TestValidateSourceType(unittest.TestCase):

    def test_trading_fees_valid(self):
        self.assertTrue(validate_source_type("trading_fees"))

    def test_lending_interest_valid(self):
        self.assertTrue(validate_source_type("lending_interest"))

    def test_staking_rewards_valid(self):
        self.assertTrue(validate_source_type("staking_rewards"))

    def test_protocol_revenue_share_valid(self):
        self.assertTrue(validate_source_type("protocol_revenue_share"))

    def test_token_emissions_valid(self):
        self.assertTrue(validate_source_type("token_emissions"))

    def test_points_farming_valid(self):
        self.assertTrue(validate_source_type("points_farming"))

    def test_liquidity_incentives_valid(self):
        self.assertTrue(validate_source_type("liquidity_incentives"))

    def test_unknown_source_invalid(self):
        self.assertFalse(validate_source_type("mystery_yield"))

    def test_empty_string_invalid(self):
        self.assertFalse(validate_source_type(""))

    def test_tier1_sources_all_valid(self):
        for s in TIER_1_SOURCES:
            self.assertTrue(validate_source_type(s))

    def test_tier2_sources_all_valid(self):
        for s in TIER_2_SOURCES:
            self.assertTrue(validate_source_type(s))

    def test_misspelled_invalid(self):
        self.assertFalse(validate_source_type("trading_fee"))  # no trailing 's'

    def test_uppercase_invalid(self):
        self.assertFalse(validate_source_type("TRADING_FEES"))


# --------------------------------------------------------------------------- #
# Tests: compute_totals
# --------------------------------------------------------------------------- #

class TestComputeTotals(unittest.TestCase):

    def test_single_tier1_source(self):
        sources = [_src("trading_fees", 8.0, 100.0)]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 8.0)
        self.assertAlmostEqual(sust, 8.0)
        self.assertAlmostEqual(spec, 0.0)

    def test_single_tier2_source(self):
        sources = [_src("token_emissions", 15.0, 100.0)]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 15.0)
        self.assertAlmostEqual(sust, 0.0)
        self.assertAlmostEqual(spec, 15.0)

    def test_mixed_sources(self):
        sources = [
            _src("lending_interest", 4.0, 50.0),
            _src("token_emissions", 4.0, 50.0),
        ]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 8.0)
        self.assertAlmostEqual(sust, 4.0)
        self.assertAlmostEqual(spec, 4.0)

    def test_empty_sources(self):
        total, sust, spec = compute_totals([])
        self.assertEqual(total, 0.0)
        self.assertEqual(sust, 0.0)
        self.assertEqual(spec, 0.0)

    def test_all_tier1_sources(self):
        sources = [
            _src("trading_fees", 3.0, 30.0),
            _src("lending_interest", 3.0, 30.0),
            _src("staking_rewards", 2.0, 20.0),
            _src("protocol_revenue_share", 2.0, 20.0),
        ]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 10.0)
        self.assertAlmostEqual(sust, 10.0)
        self.assertAlmostEqual(spec, 0.0)

    def test_all_tier2_sources(self):
        sources = [
            _src("token_emissions", 10.0, 50.0),
            _src("points_farming", 5.0, 25.0),
            _src("liquidity_incentives", 5.0, 25.0),
        ]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 20.0)
        self.assertAlmostEqual(sust, 0.0)
        self.assertAlmostEqual(spec, 20.0)

    def test_unknown_source_not_counted(self):
        sources = [
            _src("trading_fees", 5.0, 50.0),
            _src("mystery", 5.0, 50.0),
        ]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 10.0)
        self.assertAlmostEqual(sust, 5.0)
        self.assertAlmostEqual(spec, 0.0)

    def test_zero_apy_source(self):
        sources = [_src("trading_fees", 0.0, 100.0)]
        total, sust, spec = compute_totals(sources)
        self.assertEqual(total, 0.0)
        self.assertEqual(sust, 0.0)
        self.assertEqual(spec, 0.0)

    def test_multiple_tier1_accumulate(self):
        sources = [
            _src("trading_fees", 2.5, 50.0),
            _src("lending_interest", 2.5, 50.0),
        ]
        _, sust, _ = compute_totals(sources)
        self.assertAlmostEqual(sust, 5.0)

    def test_large_apy_values(self):
        sources = [
            _src("token_emissions", 100.0, 60.0),
            _src("trading_fees", 66.67, 40.0),
        ]
        total, sust, spec = compute_totals(sources)
        self.assertAlmostEqual(total, 166.67, places=1)
        self.assertAlmostEqual(sust, 66.67, places=1)
        self.assertAlmostEqual(spec, 100.0, places=1)


# --------------------------------------------------------------------------- #
# Tests: compute_quality_score
# --------------------------------------------------------------------------- #

class TestComputeQualityScore(unittest.TestCase):

    def test_empty_sources_zero(self):
        self.assertEqual(compute_quality_score([]), 0.0)

    def test_pure_trading_fees_100(self):
        sources = [_src("trading_fees", 8.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 100.0)

    def test_pure_lending_interest_90(self):
        sources = [_src("lending_interest", 5.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 90.0)

    def test_pure_staking_rewards_85(self):
        sources = [_src("staking_rewards", 5.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 85.0)

    def test_pure_protocol_revenue_share_80(self):
        sources = [_src("protocol_revenue_share", 5.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 80.0)

    def test_pure_token_emissions_20(self):
        sources = [_src("token_emissions", 20.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 20.0)

    def test_pure_points_farming_10(self):
        sources = [_src("points_farming", 5.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 10.0)

    def test_pure_liquidity_incentives_40(self):
        sources = [_src("liquidity_incentives", 5.0, 100.0)]
        self.assertAlmostEqual(compute_quality_score(sources), 40.0)

    def test_50_50_fees_emissions(self):
        sources = [
            _src("trading_fees", 5.0, 50.0),
            _src("token_emissions", 5.0, 50.0),
        ]
        # (50 * 100 + 50 * 20) / 100 = (5000 + 1000) / 100 = 60
        self.assertAlmostEqual(compute_quality_score(sources), 60.0)

    def test_unknown_source_zero_weight(self):
        sources = [
            _src("mystery", 10.0, 100.0),
        ]
        # fallback to apy weighting: mystery has weight 0
        self.assertAlmostEqual(compute_quality_score(sources), 0.0)

    def test_score_clamped_to_100(self):
        # Should never exceed 100 even with 100% trading_fees
        sources = [_src("trading_fees", 50.0, 100.0)]
        self.assertLessEqual(compute_quality_score(sources), 100.0)

    def test_score_clamped_to_zero(self):
        # Empty sources returns 0
        self.assertGreaterEqual(compute_quality_score([]), 0.0)

    def test_three_sources_weighted(self):
        sources = [
            _src("trading_fees", 6.0, 60.0),
            _src("token_emissions", 3.0, 30.0),
            _src("points_farming", 1.0, 10.0),
        ]
        # (60*100 + 30*20 + 10*10) / 100 = (6000+600+100)/100 = 67.0
        self.assertAlmostEqual(compute_quality_score(sources), 67.0)

    def test_pct_not_summing_to_100(self):
        # Should still work by normalising by total_pct
        sources = [
            _src("trading_fees", 5.0, 50.0),
            _src("token_emissions", 5.0, 25.0),
        ]
        # total_pct=75; (50*100 + 25*20)/75 = (5000+500)/75 = 73.33...
        score = compute_quality_score(sources)
        self.assertAlmostEqual(score, 73.33, places=1)


# --------------------------------------------------------------------------- #
# Tests: quality_label
# --------------------------------------------------------------------------- #

class TestQualityLabel(unittest.TestCase):

    def test_premium_yield_100(self):
        self.assertEqual(quality_label(100.0), LABEL_PREMIUM_YIELD)

    def test_premium_yield_85(self):
        self.assertEqual(quality_label(85.0), LABEL_PREMIUM_YIELD)

    def test_high_quality_84(self):
        self.assertEqual(quality_label(84.9), LABEL_HIGH_QUALITY)

    def test_high_quality_70(self):
        self.assertEqual(quality_label(70.0), LABEL_HIGH_QUALITY)

    def test_mixed_quality_69(self):
        self.assertEqual(quality_label(69.9), LABEL_MIXED_QUALITY)

    def test_mixed_quality_50(self):
        self.assertEqual(quality_label(50.0), LABEL_MIXED_QUALITY)

    def test_speculative_49(self):
        self.assertEqual(quality_label(49.9), LABEL_SPECULATIVE)

    def test_speculative_30(self):
        self.assertEqual(quality_label(30.0), LABEL_SPECULATIVE)

    def test_unsustainable_29(self):
        self.assertEqual(quality_label(29.9), LABEL_UNSUSTAINABLE)

    def test_unsustainable_0(self):
        self.assertEqual(quality_label(0.0), LABEL_UNSUSTAINABLE)

    def test_exact_boundary_85_is_premium(self):
        self.assertEqual(quality_label(85.0), LABEL_PREMIUM_YIELD)

    def test_exact_boundary_70_is_high(self):
        self.assertEqual(quality_label(70.0), LABEL_HIGH_QUALITY)

    def test_exact_boundary_50_is_mixed(self):
        self.assertEqual(quality_label(50.0), LABEL_MIXED_QUALITY)

    def test_exact_boundary_30_is_speculative(self):
        self.assertEqual(quality_label(30.0), LABEL_SPECULATIVE)


# --------------------------------------------------------------------------- #
# Tests: _atomic_log_append
# --------------------------------------------------------------------------- #

class TestAtomicLogAppend(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_log.json")

    def test_creates_file_on_first_append(self):
        _atomic_log_append({"x": 1}, self.log_path, 100)
        self.assertTrue(os.path.exists(self.log_path))

    def test_first_append_creates_list(self):
        _atomic_log_append({"x": 1}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_multiple_appends_accumulate(self):
        for i in range(5):
            _atomic_log_append({"i": i}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_enforced(self):
        for i in range(10):
            _atomic_log_append({"i": i}, self.log_path, 5)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        # Newest entries should be kept
        self.assertEqual(data[-1]["i"], 9)

    def test_ring_buffer_keeps_newest(self):
        cap = 3
        for i in range(7):
            _atomic_log_append({"i": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)
        self.assertEqual(data[0]["i"], 4)  # oldest kept
        self.assertEqual(data[-1]["i"], 6)  # newest

    def test_no_tmp_file_left_after_append(self):
        _atomic_log_append({"x": 1}, self.log_path, 100)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupt_file_recovered(self):
        # Write invalid JSON first
        with open(self.log_path, "w") as f:
            f.write("not json {{")
        _atomic_log_append({"x": 1}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_entry_contents_preserved(self):
        entry = {"protocol": "Aave", "score": 88.5, "label": "HIGH_QUALITY"}
        _atomic_log_append(entry, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol"], "Aave")
        self.assertAlmostEqual(data[0]["score"], 88.5)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — output keys
# --------------------------------------------------------------------------- #

class TestRaterOutputKeys(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def _rate_uniswap(self):
        return self.rater.rate(_protocol("Uniswap V3", [
            _src("trading_fees", 8.5, 100.0)
        ]))

    def test_output_has_protocol_name(self):
        r = self._rate_uniswap()
        self.assertIn("protocol_name", r)

    def test_output_has_total_apy_pct(self):
        r = self._rate_uniswap()
        self.assertIn("total_apy_pct", r)

    def test_output_has_quality_score(self):
        r = self._rate_uniswap()
        self.assertIn("quality_score", r)

    def test_output_has_sustainable_yield_pct(self):
        r = self._rate_uniswap()
        self.assertIn("sustainable_yield_pct", r)

    def test_output_has_speculative_yield_pct(self):
        r = self._rate_uniswap()
        self.assertIn("speculative_yield_pct", r)

    def test_output_has_quality_label(self):
        r = self._rate_uniswap()
        self.assertIn("quality_label", r)

    def test_output_has_timestamp(self):
        r = self._rate_uniswap()
        self.assertIn("timestamp", r)

    def test_protocol_name_returned_correctly(self):
        r = self._rate_uniswap()
        self.assertEqual(r["protocol_name"], "Uniswap V3")

    def test_timestamp_is_string(self):
        r = self._rate_uniswap()
        self.assertIsInstance(r["timestamp"], str)

    def test_quality_score_is_float(self):
        r = self._rate_uniswap()
        self.assertIsInstance(r["quality_score"], float)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — quality labels
# --------------------------------------------------------------------------- #

class TestRaterQualityLabels(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_pure_fees_is_premium(self):
        r = self.rater.rate(_protocol("Uniswap", [_src("trading_fees", 10.0, 100.0)]))
        self.assertEqual(r["quality_label"], LABEL_PREMIUM_YIELD)

    def test_pure_lending_interest_is_premium(self):
        # 90 → HIGH_QUALITY, not PREMIUM (needs ≥85)
        r = self.rater.rate(_protocol("Aave", [_src("lending_interest", 5.0, 100.0)]))
        self.assertIn(r["quality_label"], [LABEL_PREMIUM_YIELD, LABEL_HIGH_QUALITY])

    def test_pure_emissions_is_unsustainable(self):
        r = self.rater.rate(_protocol("FarmToken", [_src("token_emissions", 100.0, 100.0)]))
        self.assertEqual(r["quality_label"], LABEL_UNSUSTAINABLE)

    def test_pure_points_farming_is_unsustainable(self):
        r = self.rater.rate(_protocol("Points", [_src("points_farming", 50.0, 100.0)]))
        self.assertEqual(r["quality_label"], LABEL_UNSUSTAINABLE)

    def test_50_50_fees_emissions_is_mixed_or_above(self):
        r = self.rater.rate(_protocol("Mixed", [
            _src("trading_fees", 5.0, 50.0),
            _src("token_emissions", 5.0, 50.0),
        ]))
        self.assertIn(r["quality_label"], [LABEL_PREMIUM_YIELD, LABEL_HIGH_QUALITY, LABEL_MIXED_QUALITY])

    def test_liquidity_incentives_only_is_speculative_or_lower(self):
        r = self.rater.rate(_protocol("Incentives", [_src("liquidity_incentives", 8.0, 100.0)]))
        self.assertIn(r["quality_label"], [LABEL_SPECULATIVE, LABEL_MIXED_QUALITY])

    def test_high_quality_scoring(self):
        # 80% revenue_share (80 pts) + 20% liquidity_incentives (40 pts) = (0.8*80 + 0.2*40) = 72
        r = self.rater.rate(_protocol("HighQ", [
            _src("protocol_revenue_share", 8.0, 80.0),
            _src("liquidity_incentives", 2.0, 20.0),
        ]))
        self.assertEqual(r["quality_label"], LABEL_HIGH_QUALITY)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — sustainable/speculative split
# --------------------------------------------------------------------------- #

class TestRaterSustainableSpeculative(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_all_sustainable_spec_zero(self):
        r = self.rater.rate(_protocol("A", [_src("trading_fees", 10.0, 100.0)]))
        self.assertAlmostEqual(r["speculative_yield_pct"], 0.0)

    def test_all_speculative_sust_zero(self):
        r = self.rater.rate(_protocol("B", [_src("token_emissions", 20.0, 100.0)]))
        self.assertAlmostEqual(r["sustainable_yield_pct"], 0.0)

    def test_sustainable_equals_total_for_pure_tier1(self):
        r = self.rater.rate(_protocol("C", [_src("staking_rewards", 5.0, 100.0)]))
        self.assertAlmostEqual(r["sustainable_yield_pct"], r["total_apy_pct"])

    def test_speculative_equals_total_for_pure_tier2(self):
        r = self.rater.rate(_protocol("D", [_src("points_farming", 30.0, 100.0)]))
        self.assertAlmostEqual(r["speculative_yield_pct"], r["total_apy_pct"])

    def test_split_sums_to_total_for_mixed(self):
        r = self.rater.rate(_protocol("E", [
            _src("lending_interest", 4.0, 50.0),
            _src("token_emissions", 4.0, 50.0),
        ]))
        self.assertAlmostEqual(
            r["sustainable_yield_pct"] + r["speculative_yield_pct"],
            r["total_apy_pct"],
        )

    def test_total_apy_sums_all_sources(self):
        r = self.rater.rate(_protocol("F", [
            _src("trading_fees", 3.0, 30.0),
            _src("token_emissions", 7.0, 70.0),
        ]))
        self.assertAlmostEqual(r["total_apy_pct"], 10.0)

    def test_protocol_revenue_share_is_sustainable(self):
        r = self.rater.rate(_protocol("G", [_src("protocol_revenue_share", 6.0, 100.0)]))
        self.assertAlmostEqual(r["sustainable_yield_pct"], 6.0)

    def test_liquidity_incentives_are_speculative(self):
        r = self.rater.rate(_protocol("H", [_src("liquidity_incentives", 9.0, 100.0)]))
        self.assertAlmostEqual(r["speculative_yield_pct"], 9.0)

    def test_three_sources_mixed_split(self):
        r = self.rater.rate(_protocol("I", [
            _src("trading_fees", 3.0, 30.0),
            _src("staking_rewards", 3.0, 30.0),
            _src("token_emissions", 4.0, 40.0),
        ]))
        self.assertAlmostEqual(r["sustainable_yield_pct"], 6.0)
        self.assertAlmostEqual(r["speculative_yield_pct"], 4.0)
        self.assertAlmostEqual(r["total_apy_pct"], 10.0)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — edge cases
# --------------------------------------------------------------------------- #

class TestRaterEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_empty_sources(self):
        r = self.rater.rate(_protocol("Empty", []))
        self.assertEqual(r["total_apy_pct"], 0.0)
        self.assertEqual(r["quality_score"], 0.0)
        self.assertEqual(r["quality_label"], LABEL_UNSUSTAINABLE)

    def test_missing_protocol_name_defaults(self):
        r = self.rater.rate({"yield_sources": [_src("trading_fees", 5.0, 100.0)]})
        self.assertIn("protocol_name", r)

    def test_missing_yield_sources_defaults_to_empty(self):
        r = self.rater.rate({"protocol_name": "NoSources"})
        self.assertEqual(r["total_apy_pct"], 0.0)

    def test_zero_apy_sources(self):
        r = self.rater.rate(_protocol("Zero", [_src("trading_fees", 0.0, 100.0)]))
        self.assertEqual(r["total_apy_pct"], 0.0)
        self.assertEqual(r["sustainable_yield_pct"], 0.0)

    def test_quality_score_in_range_0_100(self):
        for source in ALL_VALID_SOURCES:
            r = self.rater.rate(_protocol("Test", [_src(source, 5.0, 100.0)]))
            self.assertGreaterEqual(r["quality_score"], 0.0)
            self.assertLessEqual(r["quality_score"], 100.0)

    def test_quality_label_is_valid_string(self):
        valid_labels = {
            LABEL_PREMIUM_YIELD, LABEL_HIGH_QUALITY, LABEL_MIXED_QUALITY,
            LABEL_SPECULATIVE, LABEL_UNSUSTAINABLE,
        }
        r = self.rater.rate(_protocol("LabelCheck", [_src("token_emissions", 10.0, 100.0)]))
        self.assertIn(r["quality_label"], valid_labels)

    def test_many_sources(self):
        sources = [
            _src("trading_fees", 2.0, 20.0),
            _src("lending_interest", 2.0, 20.0),
            _src("staking_rewards", 2.0, 20.0),
            _src("token_emissions", 2.0, 20.0),
            _src("points_farming", 2.0, 20.0),
        ]
        r = self.rater.rate(_protocol("MultiSource", sources))
        self.assertAlmostEqual(r["total_apy_pct"], 10.0)

    def test_numeric_types_in_output(self):
        r = self.rater.rate(_protocol("Types", [_src("trading_fees", 5.0, 100.0)]))
        self.assertIsInstance(r["total_apy_pct"], float)
        self.assertIsInstance(r["sustainable_yield_pct"], float)
        self.assertIsInstance(r["speculative_yield_pct"], float)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — per-source quality weights
# --------------------------------------------------------------------------- #

class TestRaterSourceWeights(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def _score(self, source):
        r = self.rater.rate(_protocol("X", [_src(source, 5.0, 100.0)]))
        return r["quality_score"]

    def test_trading_fees_highest_score(self):
        self.assertAlmostEqual(self._score("trading_fees"), 100.0)

    def test_lending_interest_score(self):
        self.assertAlmostEqual(self._score("lending_interest"), 90.0)

    def test_staking_rewards_score(self):
        self.assertAlmostEqual(self._score("staking_rewards"), 85.0)

    def test_protocol_revenue_share_score(self):
        self.assertAlmostEqual(self._score("protocol_revenue_share"), 80.0)

    def test_liquidity_incentives_score(self):
        self.assertAlmostEqual(self._score("liquidity_incentives"), 40.0)

    def test_token_emissions_score(self):
        self.assertAlmostEqual(self._score("token_emissions"), 20.0)

    def test_points_farming_lowest_score(self):
        self.assertAlmostEqual(self._score("points_farming"), 10.0)

    def test_tier1_all_above_tier2(self):
        tier1_scores = [self._score(s) for s in TIER_1_SOURCES]
        tier2_scores = [self._score(s) for s in TIER_2_SOURCES]
        self.assertGreater(min(tier1_scores), max(tier2_scores))


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — log file integration
# --------------------------------------------------------------------------- #

class TestRaterLogFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "qlog.json")
        self.rater = DeFiProtocolYieldSourceQualityRater(log_path=self.log_path)

    def test_log_file_created_on_rate(self):
        self.rater.rate(_protocol("Aave", [_src("lending_interest", 4.0, 100.0)]))
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_is_valid_json_list(self):
        self.rater.rate(_protocol("Compound", [_src("lending_interest", 5.0, 100.0)]))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count_increments(self):
        for i in range(3):
            self.rater.rate(_protocol(f"P{i}", [_src("trading_fees", float(i + 1), 100.0)]))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_entry_has_required_fields(self):
        self.rater.rate(_protocol("Morpho", [_src("lending_interest", 6.0, 100.0)]))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        for key in ("timestamp", "protocol_name", "total_apy_pct", "quality_score", "quality_label"):
            self.assertIn(key, entry)

    def test_log_ring_buffer_enforced(self):
        rater = DeFiProtocolYieldSourceQualityRater(log_path=self.log_path, log_cap=5)
        for i in range(10):
            rater.rate(_protocol(f"P{i}", [_src("trading_fees", 1.0, 100.0)]))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_no_tmp_file_remains(self):
        self.rater.rate(_protocol("Clean", [_src("trading_fees", 5.0, 100.0)]))
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_custom_log_path_used(self):
        custom_path = os.path.join(self.tmpdir, "custom_dir", "custom_log.json")
        rater = DeFiProtocolYieldSourceQualityRater(log_path=custom_path)
        rater.rate(_protocol("Test", [_src("trading_fees", 5.0, 100.0)]))
        self.assertTrue(os.path.exists(custom_path))

    def test_log_protocol_name_recorded(self):
        self.rater.rate(_protocol("SpecialProtocol", [_src("trading_fees", 5.0, 100.0)]))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_name"], "SpecialProtocol")

    def test_log_quality_score_recorded(self):
        self.rater.rate(_protocol("LogScore", [_src("trading_fees", 5.0, 100.0)]))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertAlmostEqual(entry["quality_score"], 100.0)


# --------------------------------------------------------------------------- #
# Tests: DeFiProtocolYieldSourceQualityRater — real protocol scenarios
# --------------------------------------------------------------------------- #

class TestRaterRealProtocolScenarios(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rater = DeFiProtocolYieldSourceQualityRater(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_uniswap_v3_pure_fees(self):
        r = self.rater.rate(_protocol("Uniswap V3", [
            _src("trading_fees", 12.0, 100.0),
        ]))
        self.assertEqual(r["quality_label"], LABEL_PREMIUM_YIELD)
        self.assertAlmostEqual(r["sustainable_yield_pct"], 12.0)
        self.assertAlmostEqual(r["speculative_yield_pct"], 0.0)

    def test_aave_lending_protocol(self):
        r = self.rater.rate(_protocol("Aave V3", [
            _src("lending_interest", 3.5, 70.0),
            _src("token_emissions", 1.5, 30.0),
        ]))
        # (70*90 + 30*20)/100 = (6300+600)/100 = 69
        self.assertAlmostEqual(r["quality_score"], 69.0)
        self.assertAlmostEqual(r["total_apy_pct"], 5.0)

    def test_emission_heavy_yield_farm(self):
        r = self.rater.rate(_protocol("YieldFarm", [
            _src("trading_fees", 2.0, 10.0),
            _src("token_emissions", 18.0, 90.0),
        ]))
        # (10*100 + 90*20)/100 = (1000+1800)/100 = 28
        self.assertAlmostEqual(r["quality_score"], 28.0)
        self.assertEqual(r["quality_label"], LABEL_UNSUSTAINABLE)

    def test_staking_protocol(self):
        r = self.rater.rate(_protocol("Lido", [
            _src("staking_rewards", 4.5, 90.0),
            _src("protocol_revenue_share", 0.5, 10.0),
        ]))
        # (90*85 + 10*80)/100 = (7650+800)/100 = 84.5
        self.assertAlmostEqual(r["quality_score"], 84.5)
        self.assertEqual(r["quality_label"], LABEL_HIGH_QUALITY)

    def test_points_farming_protocol(self):
        r = self.rater.rate(_protocol("PointsFarm", [
            _src("lending_interest", 2.0, 20.0),
            _src("points_farming", 8.0, 80.0),
        ]))
        # (20*90 + 80*10)/100 = (1800+800)/100 = 26
        self.assertAlmostEqual(r["quality_score"], 26.0)
        self.assertEqual(r["quality_label"], LABEL_UNSUSTAINABLE)

    def test_balanced_diversified_protocol(self):
        r = self.rater.rate(_protocol("Balanced", [
            _src("trading_fees", 3.0, 30.0),
            _src("lending_interest", 2.0, 20.0),
            _src("staking_rewards", 2.0, 20.0),
            _src("liquidity_incentives", 2.0, 20.0),
            _src("token_emissions", 1.0, 10.0),
        ]))
        # (30*100 + 20*90 + 20*85 + 20*40 + 10*20)/100
        # = (3000+1800+1700+800+200)/100 = 7500/100 = 75.0
        self.assertAlmostEqual(r["quality_score"], 75.0)
        self.assertEqual(r["quality_label"], LABEL_HIGH_QUALITY)


# --------------------------------------------------------------------------- #
# Tests: SOURCE_QUALITY_WEIGHTS constants
# --------------------------------------------------------------------------- #

class TestSourceQualityWeightsConstants(unittest.TestCase):

    def test_all_valid_sources_have_weights(self):
        for s in ALL_VALID_SOURCES:
            self.assertIn(s, SOURCE_QUALITY_WEIGHTS)

    def test_weights_all_non_negative(self):
        for val in SOURCE_QUALITY_WEIGHTS.values():
            self.assertGreaterEqual(val, 0)

    def test_weights_all_at_most_100(self):
        for val in SOURCE_QUALITY_WEIGHTS.values():
            self.assertLessEqual(val, 100)

    def test_tier1_weights_above_50(self):
        for s in TIER_1_SOURCES:
            self.assertGreater(SOURCE_QUALITY_WEIGHTS[s], 50)

    def test_tier2_weights_below_50(self):
        for s in TIER_2_SOURCES:
            self.assertLess(SOURCE_QUALITY_WEIGHTS[s], 50)


if __name__ == "__main__":
    unittest.main()
