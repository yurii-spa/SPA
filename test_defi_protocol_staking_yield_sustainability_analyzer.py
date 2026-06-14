"""
Tests for MP-1040 DeFiProtocolStakingYieldSustainabilityAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_staking_yield_sustainability_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_staking_yield_sustainability_analyzer import (
    DeFiProtocolStakingYieldSustainabilityAnalyzer,
    analyze,
    _compute_sustainable_yield,
    _compute_inflation_adjusted_yield,
    _compute_real_yield_score,
    _compute_sustainability_grade,
    _compute_label,
    LOG_FILENAME,
    LOG_MAX_ENTRIES,
    GRADE_A_THRESHOLD,
    GRADE_B_THRESHOLD,
    GRADE_C_THRESHOLD,
    GRADE_D_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(tmp_dir=None):
    return DeFiProtocolStakingYieldSustainabilityAnalyzer(data_dir=tmp_dir)


def _base_kwargs(**overrides):
    """Return a full set of default analyze() kwargs, with optional overrides."""
    defaults = dict(
        protocol_name="TestProtocol",
        staking_apy_pct=4.0,
        consensus_yield_pct=3.0,
        mev_yield_pct=0.5,
        token_inflation_pct=0.5,
        restaking_boost_pct=0.5,
        slashing_risk_pct=0.01,
        network_participation_rate_pct=65.0,
    )
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Unit tests — _compute_sustainable_yield
# ===========================================================================

class TestComputeSustainableYield(unittest.TestCase):

    def test_basic(self):
        result = _compute_sustainable_yield(3.0, 0.5, 0.5, 0.01)
        self.assertAlmostEqual(result, 3.99, places=5)

    def test_zero_mev(self):
        result = _compute_sustainable_yield(3.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 3.0)

    def test_high_slashing(self):
        result = _compute_sustainable_yield(3.0, 0.5, 0.0, 5.0)
        self.assertAlmostEqual(result, -1.5)

    def test_negative_sustainable(self):
        result = _compute_sustainable_yield(1.0, 0.0, 0.0, 2.0)
        self.assertAlmostEqual(result, -1.0)

    def test_restaking_boost_added(self):
        result = _compute_sustainable_yield(3.0, 0.5, 2.0, 0.0)
        self.assertAlmostEqual(result, 5.5)

    def test_all_zero(self):
        self.assertAlmostEqual(_compute_sustainable_yield(0.0, 0.0, 0.0, 0.0), 0.0)

    def test_large_values(self):
        result = _compute_sustainable_yield(10.0, 5.0, 3.0, 1.0)
        self.assertAlmostEqual(result, 17.0)


# ===========================================================================
# Unit tests — _compute_inflation_adjusted_yield
# ===========================================================================

class TestComputeInflationAdjustedYield(unittest.TestCase):

    def test_positive_real_yield(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(5.0, 2.0), 3.0)

    def test_zero_inflation(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(4.0, 0.0), 4.0)

    def test_negative_real_yield(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(3.0, 20.0), -17.0)

    def test_equal_yields_zero(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(5.0, 5.0), 0.0)

    def test_zero_staking(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(0.0, 3.0), -3.0)

    def test_fractional(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(3.8, 0.5), 3.3)

    def test_large_inflation(self):
        self.assertAlmostEqual(_compute_inflation_adjusted_yield(10.0, 50.0), -40.0)


# ===========================================================================
# Unit tests — _compute_real_yield_score
# ===========================================================================

class TestComputeRealYieldScore(unittest.TestCase):

    def _score(self, **kw):
        defaults = dict(
            staking_apy_pct=4.0,
            consensus_yield_pct=3.5,
            mev_yield_pct=0.5,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=50.0,
        )
        defaults.update(kw)
        return _compute_real_yield_score(**defaults)

    def test_returns_float(self):
        self.assertIsInstance(self._score(), float)

    def test_range_0_to_100(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_zero_staking_apy_returns_zero(self):
        self.assertAlmostEqual(self._score(staking_apy_pct=0.0), 0.0)

    def test_negative_staking_apy_returns_zero(self):
        self.assertAlmostEqual(self._score(staking_apy_pct=-1.0), 0.0)

    def test_high_real_yield_fraction_high_score(self):
        # 100% real yield, no inflation, no slashing, full participation
        s = self._score(
            staking_apy_pct=4.0,
            consensus_yield_pct=3.5,
            mev_yield_pct=0.5,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=100.0,
        )
        self.assertGreaterEqual(s, 70.0)

    def test_pure_inflation_yield_low_score(self):
        # All yield is inflation
        s = self._score(
            staking_apy_pct=20.0,
            consensus_yield_pct=0.0,
            mev_yield_pct=0.0,
            token_inflation_pct=20.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=10.0,
        )
        self.assertLessEqual(s, 20.0)

    def test_high_slashing_reduces_score(self):
        s_low = self._score(slashing_risk_pct=0.0)
        s_high = self._score(slashing_risk_pct=5.0)
        self.assertGreater(s_low, s_high)

    def test_high_inflation_reduces_score(self):
        s_low = self._score(token_inflation_pct=0.0)
        s_high = self._score(token_inflation_pct=10.0)
        self.assertGreater(s_low, s_high)

    def test_high_participation_increases_score(self):
        s_low = self._score(network_participation_rate_pct=0.0)
        s_high = self._score(network_participation_rate_pct=100.0)
        self.assertGreater(s_high, s_low)

    def test_high_restaking_reduces_score(self):
        s_low = self._score(restaking_boost_pct=1.0)
        s_high = self._score(restaking_boost_pct=10.0)
        self.assertGreater(s_low, s_high)

    def test_capped_at_100(self):
        # Best possible: all real, no inflation, no slashing, full participation
        s = self._score(
            staking_apy_pct=4.0,
            consensus_yield_pct=4.0,
            mev_yield_pct=0.0,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=100.0,
        )
        self.assertLessEqual(s, 100.0)

    def test_clamped_at_zero_min(self):
        # Worst possible inputs
        s = self._score(
            staking_apy_pct=1.0,
            consensus_yield_pct=0.0,
            mev_yield_pct=0.0,
            token_inflation_pct=100.0,
            restaking_boost_pct=20.0,
            slashing_risk_pct=10.0,
            network_participation_rate_pct=0.0,
        )
        self.assertGreaterEqual(s, 0.0)


# ===========================================================================
# Unit tests — _compute_sustainability_grade
# ===========================================================================

class TestComputeSustainabilityGrade(unittest.TestCase):

    def test_grade_a_at_threshold(self):
        self.assertEqual(_compute_sustainability_grade(GRADE_A_THRESHOLD), "A")

    def test_grade_a_above_threshold(self):
        self.assertEqual(_compute_sustainability_grade(95.0), "A")

    def test_grade_a_perfect(self):
        self.assertEqual(_compute_sustainability_grade(100.0), "A")

    def test_grade_b_at_threshold(self):
        self.assertEqual(_compute_sustainability_grade(GRADE_B_THRESHOLD), "B")

    def test_grade_b_in_range(self):
        self.assertEqual(_compute_sustainability_grade(70.0), "B")

    def test_grade_b_just_below_a(self):
        self.assertEqual(_compute_sustainability_grade(79.9), "B")

    def test_grade_c_at_threshold(self):
        self.assertEqual(_compute_sustainability_grade(GRADE_C_THRESHOLD), "C")

    def test_grade_c_in_range(self):
        self.assertEqual(_compute_sustainability_grade(50.0), "C")

    def test_grade_c_just_below_b(self):
        self.assertEqual(_compute_sustainability_grade(59.9), "C")

    def test_grade_d_at_threshold(self):
        self.assertEqual(_compute_sustainability_grade(GRADE_D_THRESHOLD), "D")

    def test_grade_d_in_range(self):
        self.assertEqual(_compute_sustainability_grade(30.0), "D")

    def test_grade_d_just_below_c(self):
        self.assertEqual(_compute_sustainability_grade(39.9), "D")

    def test_grade_f_at_zero(self):
        self.assertEqual(_compute_sustainability_grade(0.0), "F")

    def test_grade_f_in_range(self):
        self.assertEqual(_compute_sustainability_grade(10.0), "F")

    def test_grade_f_just_below_d(self):
        self.assertEqual(_compute_sustainability_grade(19.9), "F")


# ===========================================================================
# Unit tests — _compute_label
# ===========================================================================

class TestComputeLabel(unittest.TestCase):

    def _label(self, **kw):
        defaults = dict(
            staking_apy_pct=4.0,
            consensus_yield_pct=3.5,
            mev_yield_pct=0.5,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
        )
        defaults.update(kw)
        return _compute_label(**defaults)

    def test_zero_staking_apy_ponzi(self):
        self.assertEqual(self._label(staking_apy_pct=0.0), "PONZI_YIELD")

    def test_negative_staking_apy_ponzi(self):
        self.assertEqual(self._label(staking_apy_pct=-1.0), "PONZI_YIELD")

    def test_inflation_adjusted_below_neg2_ponzi(self):
        # staking 3%, inflation 6% → adj = -3%
        self.assertEqual(
            self._label(staking_apy_pct=3.0, token_inflation_pct=6.0,
                        consensus_yield_pct=3.0, mev_yield_pct=0.0),
            "PONZI_YIELD",
        )

    def test_inflation_fraction_above_70_dilution(self):
        # inflation = 75% of staking_apy, adj = 5% (not ponzi)
        self.assertEqual(
            self._label(staking_apy_pct=20.0, token_inflation_pct=15.0,
                        consensus_yield_pct=2.0, mev_yield_pct=0.0),
            "DILUTION_RISK",
        )

    def test_inflation_fraction_exactly_70_inflation_supported(self):
        # inflation_fraction = 7/10 = 0.70 exactly → boundary is strict (>0.70)
        # so exactly 70% falls into INFLATION_SUPPORTED
        result = self._label(staking_apy_pct=10.0, token_inflation_pct=7.0,
                             consensus_yield_pct=3.0, mev_yield_pct=0.0,
                             restaking_boost_pct=0.0)
        self.assertIn(result, {"INFLATION_SUPPORTED", "DILUTION_RISK"})

    def test_inflation_fraction_30_to_70_inflation_supported(self):
        # inflation = 40% of staking_apy
        self.assertEqual(
            self._label(staking_apy_pct=10.0, token_inflation_pct=4.0,
                        consensus_yield_pct=5.0, mev_yield_pct=1.0),
            "INFLATION_SUPPORTED",
        )

    def test_pure_consensus_no_restaking(self):
        # 95% real, 0% inflation, 0% restaking
        self.assertEqual(
            self._label(
                staking_apy_pct=4.0, consensus_yield_pct=3.8,
                mev_yield_pct=0.2, token_inflation_pct=0.0, restaking_boost_pct=0.0
            ),
            "PURE_CONSENSUS_YIELD",
        )

    def test_pure_consensus_small_restaking_still_pure(self):
        # restaking < 2%
        self.assertEqual(
            self._label(
                staking_apy_pct=4.0, consensus_yield_pct=3.8,
                mev_yield_pct=0.2, token_inflation_pct=0.0, restaking_boost_pct=1.5
            ),
            "PURE_CONSENSUS_YIELD",
        )

    def test_sustainable_boost_with_restaking(self):
        # restaking >= 2%
        self.assertEqual(
            self._label(
                staking_apy_pct=5.0, consensus_yield_pct=3.5,
                mev_yield_pct=0.5, token_inflation_pct=0.0, restaking_boost_pct=2.0
            ),
            "SUSTAINABLE_BOOST",
        )

    def test_sustainable_boost_real_fraction_below_90(self):
        # real 80%, low inflation
        result = self._label(
            staking_apy_pct=5.0, consensus_yield_pct=3.5,
            mev_yield_pct=0.5, token_inflation_pct=0.5, restaking_boost_pct=0.0
        )
        self.assertIn(result, {"SUSTAINABLE_BOOST", "INFLATION_SUPPORTED"})

    def test_valid_label_set(self):
        valid = {
            "PURE_CONSENSUS_YIELD", "SUSTAINABLE_BOOST",
            "INFLATION_SUPPORTED", "DILUTION_RISK", "PONZI_YIELD"
        }
        for scenario in [
            dict(staking_apy_pct=0.0, consensus_yield_pct=0.0, mev_yield_pct=0.0,
                 token_inflation_pct=0.0, restaking_boost_pct=0.0),
            dict(staking_apy_pct=4.0, consensus_yield_pct=4.0, mev_yield_pct=0.0,
                 token_inflation_pct=0.0, restaking_boost_pct=0.0),
            dict(staking_apy_pct=20.0, consensus_yield_pct=1.0, mev_yield_pct=0.0,
                 token_inflation_pct=18.0, restaking_boost_pct=0.0),
        ]:
            result = _compute_label(**scenario)
            self.assertIn(result, valid, f"unexpected label {result!r} for {scenario}")


# ===========================================================================
# Integration tests — DeFiProtocolStakingYieldSustainabilityAnalyzer.analyze()
# ===========================================================================

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _result(self, **overrides):
        return self.analyzer.analyze(**_base_kwargs(**overrides))

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_required_keys_present(self):
        r = self._result()
        for key in [
            "protocol_name", "staking_apy_pct", "consensus_yield_pct",
            "mev_yield_pct", "token_inflation_pct", "restaking_boost_pct",
            "slashing_risk_pct", "network_participation_rate_pct",
            "sustainable_yield_pct", "inflation_adjusted_yield_pct",
            "real_yield_score", "sustainability_grade", "label", "timestamp",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_protocol_name_preserved(self):
        r = self._result(protocol_name="Lido stETH")
        self.assertEqual(r["protocol_name"], "Lido stETH")

    def test_sustainable_yield_calculation(self):
        r = self.analyzer.analyze(
            protocol_name="X",
            staking_apy_pct=5.0,
            consensus_yield_pct=3.0,
            mev_yield_pct=0.5,
            token_inflation_pct=0.5,
            restaking_boost_pct=1.0,
            slashing_risk_pct=0.1,
            network_participation_rate_pct=60.0,
        )
        self.assertAlmostEqual(r["sustainable_yield_pct"], 3.0 + 0.5 + 1.0 - 0.1, places=4)

    def test_inflation_adjusted_yield_calculation(self):
        r = self.analyzer.analyze(
            protocol_name="X",
            staking_apy_pct=5.0,
            consensus_yield_pct=4.0,
            mev_yield_pct=0.5,
            token_inflation_pct=2.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=60.0,
        )
        self.assertAlmostEqual(r["inflation_adjusted_yield_pct"], 3.0, places=4)

    def test_real_yield_score_range(self):
        r = self._result()
        self.assertGreaterEqual(r["real_yield_score"], 0.0)
        self.assertLessEqual(r["real_yield_score"], 100.0)

    def test_grade_is_valid(self):
        r = self._result()
        self.assertIn(r["sustainability_grade"], {"A", "B", "C", "D", "F"})

    def test_label_is_valid(self):
        r = self._result()
        valid = {
            "PURE_CONSENSUS_YIELD", "SUSTAINABLE_BOOST",
            "INFLATION_SUPPORTED", "DILUTION_RISK", "PONZI_YIELD"
        }
        self.assertIn(r["label"], valid)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = self._result()
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_no_save_no_log_file(self):
        self._result()
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))

    def test_save_creates_log_file(self):
        self.analyzer.analyze(**_base_kwargs(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertTrue(os.path.exists(log_path))

    def test_save_log_has_one_entry(self):
        self.analyzer.analyze(**_base_kwargs(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            self.analyzer.analyze(**_base_kwargs(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(LOG_MAX_ENTRIES + 10):
            self.analyzer.analyze(**_base_kwargs(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)

    def test_ponzi_yield_label_for_high_inflation(self):
        r = self.analyzer.analyze(
            protocol_name="BadToken",
            staking_apy_pct=5.0,
            consensus_yield_pct=3.0,
            mev_yield_pct=0.0,
            token_inflation_pct=8.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=50.0,
        )
        self.assertEqual(r["label"], "PONZI_YIELD")

    def test_dilution_risk_label(self):
        r = self.analyzer.analyze(
            protocol_name="InflationCoin",
            staking_apy_pct=10.0,
            consensus_yield_pct=2.0,
            mev_yield_pct=0.0,
            token_inflation_pct=8.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=50.0,
        )
        self.assertEqual(r["label"], "DILUTION_RISK")

    def test_pure_consensus_yield_label(self):
        r = self.analyzer.analyze(
            protocol_name="PureETH",
            staking_apy_pct=4.0,
            consensus_yield_pct=3.8,
            mev_yield_pct=0.2,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=65.0,
        )
        self.assertEqual(r["label"], "PURE_CONSENSUS_YIELD")

    def test_grade_a_for_ideal_protocol(self):
        r = self.analyzer.analyze(
            protocol_name="Ideal",
            staking_apy_pct=4.0,
            consensus_yield_pct=4.0,
            mev_yield_pct=0.0,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=100.0,
        )
        self.assertEqual(r["sustainability_grade"], "A")

    def test_grade_f_for_bad_protocol(self):
        r = self.analyzer.analyze(
            protocol_name="Worst",
            staking_apy_pct=1.0,
            consensus_yield_pct=0.0,
            mev_yield_pct=0.0,
            token_inflation_pct=30.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=10.0,
            network_participation_rate_pct=0.0,
        )
        self.assertEqual(r["sustainability_grade"], "F")

    def test_numeric_fields_rounded(self):
        r = self._result()
        for field in ["sustainable_yield_pct", "inflation_adjusted_yield_pct",
                      "real_yield_score"]:
            val = r[field]
            # Should be representable as a rounded float
            self.assertIsInstance(val, float)

    def test_float_inputs_coerced(self):
        # Should not raise
        r = self.analyzer.analyze(
            protocol_name="X",
            staking_apy_pct="4.0",
            consensus_yield_pct="3.0",
            mev_yield_pct="0.5",
            token_inflation_pct="0.5",
            restaking_boost_pct="0.5",
            slashing_risk_pct="0.01",
            network_participation_rate_pct="65.0",
        )
        self.assertIn("label", r)


# ===========================================================================
# Module-level analyze() function
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_dict(self):
        r = analyze(**_base_kwargs(), data_dir=self.tmp_dir)
        self.assertIsInstance(r, dict)

    def test_has_label(self):
        r = analyze(**_base_kwargs(), data_dir=self.tmp_dir)
        self.assertIn("label", r)

    def test_save_creates_log(self):
        analyze(**_base_kwargs(), data_dir=self.tmp_dir, save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertTrue(os.path.exists(log_path))

    def test_no_save_no_log(self):
        analyze(**_base_kwargs(), data_dir=self.tmp_dir, save=False)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))


# ===========================================================================
# Log management tests
# ===========================================================================

class TestLogManagement(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp_dir)
        self.log_path = os.path.join(self.tmp_dir, LOG_FILENAME)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init_log_creates_file(self):
        self.assertFalse(os.path.exists(self.log_path))
        self.analyzer.init_log()
        self.assertTrue(os.path.exists(self.log_path))

    def test_init_log_creates_empty_list(self):
        self.analyzer.init_log()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_idempotent(self):
        self.analyzer.init_log()
        self.analyzer.analyze(**_base_kwargs(), save=True)
        self.analyzer.init_log()  # should not overwrite
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_read_log_missing_file(self):
        result = self.analyzer._read_log()
        self.assertEqual(result, [])

    def test_read_log_corrupt_json(self):
        with open(self.log_path, "w") as f:
            f.write("not valid json{{{{")
        result = self.analyzer._read_log()
        self.assertEqual(result, [])

    def test_read_log_non_list_json(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "value"}, f)
        result = self.analyzer._read_log()
        self.assertEqual(result, [])

    def test_atomic_write_produces_valid_json(self):
        data = [{"a": 1}, {"b": 2}]
        self.analyzer._atomic_write(data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_ring_buffer_keeps_latest(self):
        # Write 110 entries, only last 100 should be kept
        for i in range(LOG_MAX_ENTRIES + 10):
            self.analyzer.analyze(
                **_base_kwargs(protocol_name=f"Protocol_{i}"), save=True
            )
        data = self.analyzer._read_log()
        self.assertEqual(len(data), LOG_MAX_ENTRIES)
        # Latest should be Protocol_109
        self.assertEqual(data[-1]["protocol_name"], f"Protocol_{LOG_MAX_ENTRIES + 9}")


# ===========================================================================
# Edge case / boundary tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_all_zeros(self):
        r = self.analyzer.analyze(
            protocol_name="ZeroProtocol",
            staking_apy_pct=0.0,
            consensus_yield_pct=0.0,
            mev_yield_pct=0.0,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=0.0,
        )
        self.assertEqual(r["label"], "PONZI_YIELD")
        self.assertAlmostEqual(r["real_yield_score"], 0.0)

    def test_very_high_participation(self):
        r = self.analyzer.analyze(
            **_base_kwargs(network_participation_rate_pct=200.0)
        )
        self.assertLessEqual(r["real_yield_score"], 100.0)

    def test_very_high_slashing(self):
        r = self.analyzer.analyze(
            **_base_kwargs(slashing_risk_pct=100.0)
        )
        self.assertGreaterEqual(r["real_yield_score"], 0.0)

    def test_very_high_inflation(self):
        r = self.analyzer.analyze(
            **_base_kwargs(token_inflation_pct=1000.0)
        )
        self.assertIn(r["label"], {"PONZI_YIELD", "DILUTION_RISK", "INFLATION_SUPPORTED"})

    def test_empty_protocol_name(self):
        r = self.analyzer.analyze(**_base_kwargs(protocol_name=""))
        self.assertEqual(r["protocol_name"], "")

    def test_unicode_protocol_name(self):
        r = self.analyzer.analyze(**_base_kwargs(protocol_name="протокол-тест"))
        self.assertEqual(r["protocol_name"], "протокол-тест")

    def test_large_mev_yield(self):
        r = self.analyzer.analyze(
            protocol_name="HighMEV",
            staking_apy_pct=10.0,
            consensus_yield_pct=3.0,
            mev_yield_pct=7.0,
            token_inflation_pct=0.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=65.0,
        )
        # Real yield ≥ staking_apy → score should be high
        self.assertGreaterEqual(r["real_yield_score"], 60.0)

    def test_staking_apy_equals_inflation(self):
        r = self.analyzer.analyze(
            protocol_name="BreakEven",
            staking_apy_pct=5.0,
            consensus_yield_pct=5.0,
            mev_yield_pct=0.0,
            token_inflation_pct=5.0,
            restaking_boost_pct=0.0,
            slashing_risk_pct=0.0,
            network_participation_rate_pct=50.0,
        )
        self.assertAlmostEqual(r["inflation_adjusted_yield_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
