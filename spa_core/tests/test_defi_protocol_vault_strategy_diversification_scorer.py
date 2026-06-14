"""
MP-1038 DeFiProtocolVaultStrategyDiversificationScorer — unit tests (≥90)
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_strategy_diversification_scorer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_vault_strategy_diversification_scorer import (
    analyze,
    log_result,
    DeFiProtocolVaultStrategyDiversificationScorer,
    _aggregate_weights,
    _hhi,
    _protocol_weights,
    _chain_weights,
    _yield_type_weights,
    _protocol_hhi,
    _chain_hhi,
    _yield_type_hhi,
    _combined_hhi,
    _diversification_score,
    _concentration_warnings,
    _weighted_apy,
    _label,
    _DEFAULT_MAX_PROTOCOL_PCT,
    _DEFAULT_MAX_CHAIN_PCT,
    _DEFAULT_MAX_YIELD_TYPE_PCT,
    _THRESHOLD_WELL_DIVERSIFIED,
    _THRESHOLD_GOOD_MIX,
    _THRESHOLD_MODERATE,
    _THRESHOLD_CONCENTRATED,
    _LOG_RING_SIZE,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SINGLE = [
    {"protocol": "Aave", "chain": "Ethereum", "yield_type": "lending",
     "weight_pct": 100.0, "apy_pct": 4.0},
]

_EQUAL_TWO = [
    {"protocol": "Aave",     "chain": "Ethereum", "yield_type": "lending",
     "weight_pct": 50.0, "apy_pct": 4.0},
    {"protocol": "Compound", "chain": "Ethereum", "yield_type": "lending",
     "weight_pct": 50.0, "apy_pct": 5.0},
]

_DIVERSE_SIX = [
    {"protocol": "Aave",    "chain": "Ethereum", "yield_type": "lending",  "weight_pct": 20.0, "apy_pct": 3.5},
    {"protocol": "Compound","chain": "Ethereum", "yield_type": "lending",  "weight_pct": 15.0, "apy_pct": 4.8},
    {"protocol": "Morpho",  "chain": "Ethereum", "yield_type": "lending",  "weight_pct": 15.0, "apy_pct": 6.5},
    {"protocol": "Yearn",   "chain": "Ethereum", "yield_type": "vault",    "weight_pct": 20.0, "apy_pct": 5.2},
    {"protocol": "Euler",   "chain": "Arbitrum", "yield_type": "lending",  "weight_pct": 15.0, "apy_pct": 5.8},
    {"protocol": "Pendle",  "chain": "Arbitrum", "yield_type": "pt_yield", "weight_pct": 15.0, "apy_pct": 12.0},
]


# ===========================================================================
# _aggregate_weights
# ===========================================================================

class TestAggregateWeights(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_aggregate_weights([], "protocol"), {})

    def test_single_entry(self):
        r = _aggregate_weights([{"protocol": "Aave", "weight_pct": 50.0}], "protocol")
        self.assertAlmostEqual(r["Aave"], 50.0)

    def test_sums_same_key(self):
        data = [
            {"protocol": "Aave", "weight_pct": 30.0},
            {"protocol": "Aave", "weight_pct": 20.0},
        ]
        r = _aggregate_weights(data, "protocol")
        self.assertAlmostEqual(r["Aave"], 50.0)

    def test_different_keys(self):
        data = [
            {"protocol": "Aave",     "weight_pct": 40.0},
            {"protocol": "Compound", "weight_pct": 60.0},
        ]
        r = _aggregate_weights(data, "protocol")
        self.assertAlmostEqual(r["Aave"], 40.0)
        self.assertAlmostEqual(r["Compound"], 60.0)

    def test_chain_key(self):
        data = [
            {"chain": "Ethereum", "weight_pct": 70.0},
            {"chain": "Arbitrum", "weight_pct": 30.0},
        ]
        r = _aggregate_weights(data, "chain")
        self.assertAlmostEqual(r["Ethereum"], 70.0)

    def test_missing_key_falls_back_to_unknown(self):
        r = _aggregate_weights([{"weight_pct": 100.0}], "protocol")
        self.assertIn("unknown", r)

    def test_missing_weight_treated_as_zero(self):
        r = _aggregate_weights([{"protocol": "X"}], "protocol")
        self.assertAlmostEqual(r["X"], 0.0)

    def test_numeric_coercion(self):
        data = [{"protocol": "X", "weight_pct": "25.5"}]
        r = _aggregate_weights(data, "protocol")
        self.assertAlmostEqual(r["X"], 25.5)

    def test_three_protocols(self):
        data = [
            {"protocol": "A", "weight_pct": 33.0},
            {"protocol": "B", "weight_pct": 33.0},
            {"protocol": "C", "weight_pct": 34.0},
        ]
        r = _aggregate_weights(data, "protocol")
        self.assertEqual(len(r), 3)

    def test_total_sums_to_100(self):
        r = _aggregate_weights(_DIVERSE_SIX, "protocol")
        self.assertAlmostEqual(sum(r.values()), 100.0)


# ===========================================================================
# _hhi
# ===========================================================================

class TestHHI(unittest.TestCase):
    def test_empty_dict(self):
        self.assertEqual(_hhi({}), 0.0)

    def test_single_entry_equals_one(self):
        self.assertAlmostEqual(_hhi({"A": 100.0}), 1.0)

    def test_two_equal_is_half(self):
        self.assertAlmostEqual(_hhi({"A": 50.0, "B": 50.0}), 0.5)

    def test_four_equal(self):
        d = {"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0}
        self.assertAlmostEqual(_hhi(d), 0.25)

    def test_zero_total_returns_zero(self):
        self.assertEqual(_hhi({"A": 0.0, "B": 0.0}), 0.0)

    def test_bounds_between_zero_and_one(self):
        v = _hhi({"A": 60.0, "B": 40.0})
        self.assertGreater(v, 0.0)
        self.assertLessEqual(v, 1.0)

    def test_unequal_higher_than_equal(self):
        equal = _hhi({"A": 50.0, "B": 50.0})
        unequal = _hhi({"A": 80.0, "B": 20.0})
        self.assertGreater(unequal, equal)

    def test_order_invariant(self):
        a = _hhi({"X": 30.0, "Y": 70.0})
        b = _hhi({"Y": 70.0, "X": 30.0})
        self.assertAlmostEqual(a, b)

    def test_five_equal(self):
        d = {str(i): 20.0 for i in range(5)}
        self.assertAlmostEqual(_hhi(d), 0.20)


# ===========================================================================
# _protocol_hhi / _chain_hhi / _yield_type_hhi
# ===========================================================================

class TestDimensionHHI(unittest.TestCase):
    def test_protocol_hhi_single_allocation(self):
        self.assertAlmostEqual(_protocol_hhi(_SINGLE), 1.0)

    def test_chain_hhi_all_same_chain(self):
        # All on Ethereum → chain HHI = 1
        self.assertAlmostEqual(_chain_hhi(_SINGLE), 1.0)

    def test_yield_type_hhi_all_same(self):
        data = [
            {"protocol": "A", "chain": "E", "yield_type": "lending", "weight_pct": 50.0, "apy_pct": 4.0},
            {"protocol": "B", "chain": "E", "yield_type": "lending", "weight_pct": 50.0, "apy_pct": 5.0},
        ]
        self.assertAlmostEqual(_yield_type_hhi(data), 1.0)

    def test_protocol_hhi_two_equal(self):
        self.assertAlmostEqual(_protocol_hhi(_EQUAL_TWO), 0.5)

    def test_chain_hhi_two_equal_chains(self):
        data = [
            {"protocol": "A", "chain": "Eth",     "yield_type": "l", "weight_pct": 50.0, "apy_pct": 4.0},
            {"protocol": "B", "chain": "Arbitrum", "yield_type": "l", "weight_pct": 50.0, "apy_pct": 4.0},
        ]
        self.assertAlmostEqual(_chain_hhi(data), 0.5)

    def test_empty_allocations(self):
        self.assertEqual(_protocol_hhi([]), 0.0)
        self.assertEqual(_chain_hhi([]), 0.0)
        self.assertEqual(_yield_type_hhi([]), 0.0)


# ===========================================================================
# _combined_hhi
# ===========================================================================

class TestCombinedHHI(unittest.TestCase):
    def test_empty(self):
        self.assertAlmostEqual(_combined_hhi([]), 0.0)

    def test_single_alloc_is_one(self):
        # protocol=1, chain=1, yield_type=1 → combined = 1
        self.assertAlmostEqual(_combined_hhi(_SINGLE), 1.0)

    def test_diverse_less_than_single(self):
        self.assertLess(_combined_hhi(_DIVERSE_SIX), _combined_hhi(_SINGLE))

    def test_returns_float(self):
        self.assertIsInstance(_combined_hhi(_DIVERSE_SIX), float)

    def test_average_of_three(self):
        # all three dims = 0.5 → combined = 0.5
        data = [
            {"protocol": "A", "chain": "C1", "yield_type": "l", "weight_pct": 50.0, "apy_pct": 4.0},
            {"protocol": "B", "chain": "C2", "yield_type": "v", "weight_pct": 50.0, "apy_pct": 5.0},
        ]
        c = _combined_hhi(data)
        # protocol HHI = 0.5, chain HHI = 0.5, yield_type HHI = 0.5 → avg = 0.5
        self.assertAlmostEqual(c, 0.5)


# ===========================================================================
# _diversification_score
# ===========================================================================

class TestDiversificationScore(unittest.TestCase):
    def test_hhi_one_gives_zero(self):
        self.assertAlmostEqual(_diversification_score(1.0), 0.0)

    def test_hhi_zero_gives_hundred(self):
        self.assertAlmostEqual(_diversification_score(0.0), 100.0)

    def test_hhi_half_gives_fifty(self):
        self.assertAlmostEqual(_diversification_score(0.5), 50.0)

    def test_clamped_below_zero(self):
        self.assertEqual(_diversification_score(1.5), 0.0)

    def test_clamped_above_hundred(self):
        self.assertEqual(_diversification_score(-0.5), 100.0)

    def test_monotone_decreasing(self):
        scores = [_diversification_score(h) for h in [0.1, 0.3, 0.6, 0.9]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_returns_float(self):
        self.assertIsInstance(_diversification_score(0.5), float)


# ===========================================================================
# _concentration_warnings
# ===========================================================================

class TestConcentrationWarnings(unittest.TestCase):
    def _call(self, pw, cw, yw, mp=40.0, mc=60.0, my=70.0):
        return _concentration_warnings(pw, cw, yw, mp, mc, my)

    def test_no_warnings_when_all_under_threshold(self):
        r = self._call({"Aave": 35.0}, {"Eth": 55.0}, {"lending": 65.0})
        self.assertEqual(r, [])

    def test_protocol_warning_triggered(self):
        r = self._call({"Aave": 45.0}, {}, {})
        self.assertTrue(any("Protocol" in w and "Aave" in w for w in r))

    def test_chain_warning_triggered(self):
        r = self._call({}, {"Ethereum": 70.0}, {})
        self.assertTrue(any("Chain" in w and "Ethereum" in w for w in r))

    def test_yield_type_warning_triggered(self):
        r = self._call({}, {}, {"lending": 80.0})
        self.assertTrue(any("Yield type" in w and "lending" in w for w in r))

    def test_multiple_warnings(self):
        r = self._call({"Aave": 50.0}, {"Ethereum": 70.0}, {"lending": 90.0})
        self.assertEqual(len(r), 3)

    def test_exactly_at_threshold_no_warning(self):
        r = self._call({"Aave": 40.0}, {}, {})
        self.assertEqual(r, [])

    def test_one_above_threshold(self):
        r = self._call({"Aave": 40.1}, {}, {})
        self.assertEqual(len(r), 1)

    def test_empty_dicts(self):
        self.assertEqual(self._call({}, {}, {}), [])

    def test_custom_threshold(self):
        r = self._call({"Aave": 25.0}, {}, {}, mp=20.0)
        self.assertEqual(len(r), 1)


# ===========================================================================
# _weighted_apy
# ===========================================================================

class TestWeightedAPY(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_weighted_apy([]), 0.0)

    def test_single_equals_its_apy(self):
        data = [{"weight_pct": 100.0, "apy_pct": 5.0}]
        self.assertAlmostEqual(_weighted_apy(data), 5.0)

    def test_equal_weights_averages(self):
        data = [
            {"weight_pct": 50.0, "apy_pct": 4.0},
            {"weight_pct": 50.0, "apy_pct": 6.0},
        ]
        self.assertAlmostEqual(_weighted_apy(data), 5.0)

    def test_unequal_weights(self):
        data = [
            {"weight_pct": 80.0, "apy_pct": 4.0},
            {"weight_pct": 20.0, "apy_pct": 9.0},
        ]
        expected = (80 * 4 + 20 * 9) / 100
        self.assertAlmostEqual(_weighted_apy(data), expected, places=5)

    def test_zero_weight_skipped(self):
        data = [
            {"weight_pct": 0.0, "apy_pct": 99.0},
            {"weight_pct": 100.0, "apy_pct": 5.0},
        ]
        self.assertAlmostEqual(_weighted_apy(data), 5.0)

    def test_diverse_six_positive(self):
        self.assertGreater(_weighted_apy(_DIVERSE_SIX), 0.0)


# ===========================================================================
# _label
# ===========================================================================

class TestLabel(unittest.TestCase):
    def test_single_point_exposure_at_zero(self):
        self.assertEqual(_label(0.0), "SINGLE_POINT_EXPOSURE")

    def test_single_point_exposure_just_below_concentrated(self):
        self.assertEqual(_label(_THRESHOLD_CONCENTRATED - 0.01), "SINGLE_POINT_EXPOSURE")

    def test_concentrated_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_CONCENTRATED), "CONCENTRATED")

    def test_concentrated_mid(self):
        self.assertEqual(_label(30.0), "CONCENTRATED")

    def test_moderate_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_MODERATE), "MODERATE_CONCENTRATION")

    def test_moderate_mid(self):
        self.assertEqual(_label(50.0), "MODERATE_CONCENTRATION")

    def test_good_mix_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_GOOD_MIX), "GOOD_MIX")

    def test_good_mix_mid(self):
        self.assertEqual(_label(70.0), "GOOD_MIX")

    def test_well_diversified_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_WELL_DIVERSIFIED), "WELL_DIVERSIFIED")

    def test_well_diversified_at_100(self):
        self.assertEqual(_label(100.0), "WELL_DIVERSIFIED")

    def test_all_five_labels_reachable(self):
        labels = {_label(s) for s in [0.0, 25.0, 50.0, 70.0, 90.0]}
        self.assertEqual(len(labels), 5)


# ===========================================================================
# analyze()
# ===========================================================================

class TestAnalyze(unittest.TestCase):
    def test_empty_allocations_returns_dict(self):
        r = analyze([])
        self.assertIsInstance(r, dict)

    def test_empty_allocations_score_zero(self):
        self.assertEqual(analyze([])["diversification_score"], 0.0)

    def test_empty_allocations_label_single_point(self):
        self.assertEqual(analyze([])["label"], "SINGLE_POINT_EXPOSURE")

    def test_empty_allocations_hhi_zero(self):
        self.assertEqual(analyze([])["herfindahl_index"], 0.0)

    def test_empty_allocations_apy_zero(self):
        self.assertEqual(analyze([])["weighted_apy_pct"], 0.0)

    def test_single_alloc_hhi_one(self):
        r = analyze(_SINGLE)
        self.assertAlmostEqual(r["herfindahl_index"], 1.0, places=5)

    def test_single_alloc_score_zero(self):
        r = analyze(_SINGLE)
        self.assertAlmostEqual(r["diversification_score"], 0.0, places=4)

    def test_single_alloc_label_single_point(self):
        r = analyze(_SINGLE)
        self.assertEqual(r["label"], "SINGLE_POINT_EXPOSURE")

    def test_single_alloc_warning_triggered(self):
        r = analyze(_SINGLE)
        self.assertGreater(len(r["concentration_warnings"]), 0)

    def test_diverse_six_score_higher_than_single(self):
        r_div = analyze(_DIVERSE_SIX)
        r_sin = analyze(_SINGLE)
        self.assertGreater(r_div["diversification_score"], r_sin["diversification_score"])

    def test_diverse_six_contains_all_keys(self):
        r = analyze(_DIVERSE_SIX)
        for key in (
            "n_allocations", "protocol_weights", "chain_weights", "yield_type_weights",
            "protocol_hhi", "chain_hhi", "yield_type_hhi", "herfindahl_index",
            "diversification_score", "concentration_warnings", "weighted_apy_pct",
            "label", "timestamp",
        ):
            self.assertIn(key, r)

    def test_n_allocations_correct(self):
        self.assertEqual(analyze(_DIVERSE_SIX)["n_allocations"], 6)

    def test_weighted_apy_positive(self):
        self.assertGreater(analyze(_DIVERSE_SIX)["weighted_apy_pct"], 0.0)

    def test_protocol_weights_sum_to_100(self):
        r = analyze(_DIVERSE_SIX)
        self.assertAlmostEqual(sum(r["protocol_weights"].values()), 100.0, places=5)

    def test_chain_weights_sum_to_100(self):
        r = analyze(_DIVERSE_SIX)
        self.assertAlmostEqual(sum(r["chain_weights"].values()), 100.0, places=5)

    def test_yield_type_weights_sum_to_100(self):
        r = analyze(_DIVERSE_SIX)
        self.assertAlmostEqual(sum(r["yield_type_weights"].values()), 100.0, places=5)

    def test_custom_thresholds_affect_warnings(self):
        # Very low protocol threshold → should trigger warning for 100% single allocation
        r = analyze(_SINGLE, max_single_protocol_pct=10.0)
        self.assertTrue(any("Protocol" in w for w in r["concentration_warnings"]))

    def test_high_threshold_no_warning(self):
        r = analyze(_SINGLE, max_single_protocol_pct=100.0,
                    max_single_chain_pct=100.0, max_single_yield_type_pct=100.0)
        self.assertEqual(r["concentration_warnings"], [])

    def test_timestamp_is_float(self):
        r = analyze(_SINGLE)
        self.assertIsInstance(r["timestamp"], float)

    def test_timestamp_positive(self):
        self.assertGreater(analyze(_SINGLE)["timestamp"], 0.0)

    def test_protocol_hhi_matches_individual(self):
        r = analyze(_DIVERSE_SIX)
        expected = _protocol_hhi(_DIVERSE_SIX)
        self.assertAlmostEqual(r["protocol_hhi"], expected, places=5)

    def test_all_same_protocol_hhi_one(self):
        data = [
            {"protocol": "Aave", "chain": "E1", "yield_type": "l1", "weight_pct": 50.0, "apy_pct": 4.0},
            {"protocol": "Aave", "chain": "E2", "yield_type": "l2", "weight_pct": 50.0, "apy_pct": 5.0},
        ]
        r = analyze(data)
        self.assertAlmostEqual(r["protocol_hhi"], 1.0, places=5)

    def test_label_well_diversified_for_very_diverse(self):
        # 10 equal entries across 10 protocols, 10 chains, 10 yield types → near-perfect
        data = [
            {"protocol": f"P{i}", "chain": f"C{i}", "yield_type": f"Y{i}",
             "weight_pct": 10.0, "apy_pct": 5.0}
            for i in range(10)
        ]
        r = analyze(data)
        self.assertEqual(r["label"], "WELL_DIVERSIFIED")

    def test_score_between_zero_and_100(self):
        r = analyze(_DIVERSE_SIX)
        self.assertGreaterEqual(r["diversification_score"], 0.0)
        self.assertLessEqual(r["diversification_score"], 100.0)

    def test_hhi_between_zero_and_one(self):
        r = analyze(_DIVERSE_SIX)
        self.assertGreaterEqual(r["herfindahl_index"], 0.0)
        self.assertLessEqual(r["herfindahl_index"], 1.0)

    def test_default_thresholds_stored_in_result(self):
        r = analyze(_SINGLE)
        self.assertEqual(r["max_single_protocol_pct"], _DEFAULT_MAX_PROTOCOL_PCT)
        self.assertEqual(r["max_single_chain_pct"], _DEFAULT_MAX_CHAIN_PCT)
        self.assertEqual(r["max_single_yield_type_pct"], _DEFAULT_MAX_YIELD_TYPE_PCT)

    def test_concentration_warnings_is_list(self):
        self.assertIsInstance(analyze(_SINGLE)["concentration_warnings"], list)


# ===========================================================================
# DeFiProtocolVaultStrategyDiversificationScorer class
# ===========================================================================

class TestScorerClass(unittest.TestCase):
    def test_instantiation_defaults(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        self.assertEqual(s.max_single_protocol_pct, _DEFAULT_MAX_PROTOCOL_PCT)
        self.assertEqual(s.max_single_chain_pct, _DEFAULT_MAX_CHAIN_PCT)
        self.assertEqual(s.max_single_yield_type_pct, _DEFAULT_MAX_YIELD_TYPE_PCT)

    def test_instantiation_custom(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer(30.0, 50.0, 60.0)
        self.assertEqual(s.max_single_protocol_pct, 30.0)

    def test_score_returns_dict(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        r = s.score(_DIVERSE_SIX)
        self.assertIsInstance(r, dict)

    def test_score_empty(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        r = s.score([])
        self.assertEqual(r["n_allocations"], 0)

    def test_score_same_as_analyze(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        r1 = s.score(_DIVERSE_SIX)
        r2 = analyze(_DIVERSE_SIX)
        self.assertEqual(r1["diversification_score"], r2["diversification_score"])
        self.assertEqual(r1["label"], r2["label"])

    def test_custom_thresholds_propagated(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer(
            max_single_protocol_pct=10.0, max_single_chain_pct=10.0, max_single_yield_type_pct=10.0
        )
        r = s.score(_SINGLE)
        self.assertGreater(len(r["concentration_warnings"]), 0)

    def test_score_n_allocations(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        self.assertEqual(s.score(_DIVERSE_SIX)["n_allocations"], 6)

    def test_score_label_type(self):
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        self.assertIsInstance(s.score(_SINGLE)["label"], str)

    def test_score_well_diversified_label(self):
        data = [
            {"protocol": f"P{i}", "chain": f"C{i}", "yield_type": f"Y{i}",
             "weight_pct": 10.0, "apy_pct": 5.0}
            for i in range(10)
        ]
        s = DeFiProtocolVaultStrategyDiversificationScorer()
        self.assertEqual(s.score(data)["label"], "WELL_DIVERSIFIED")


# ===========================================================================
# log_result()
# ===========================================================================

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def _log_path(self):
        return os.path.join(self._dir, "vault_strategy_diversification_log.json")

    def _run_analyze_and_log(self, allocs=None):
        r = analyze(allocs or _DIVERSE_SIX)
        log_result(r, data_dir=self._dir)
        return r

    def test_creates_file(self):
        self._run_analyze_and_log()
        self.assertTrue(os.path.isfile(self._log_path()))

    def test_file_is_valid_json(self):
        self._run_analyze_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_one_entry_after_one_call(self):
        self._run_analyze_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_accumulates_entries(self):
        for _ in range(5):
            self._run_analyze_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(_LOG_RING_SIZE + 10):
            self._run_analyze_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_RING_SIZE)

    def test_entry_has_required_keys(self):
        self._run_analyze_and_log()
        with open(self._log_path()) as f:
            entry = json.load(f)[0]
        for key in (
            "timestamp", "n_allocations", "herfindahl_index",
            "diversification_score", "weighted_apy_pct", "label", "n_warnings",
        ):
            self.assertIn(key, entry)

    def test_label_value_is_string(self):
        self._run_analyze_and_log()
        with open(self._log_path()) as f:
            entry = json.load(f)[0]
        self.assertIsInstance(entry["label"], str)

    def test_overwrites_corrupt_file(self):
        with open(self._log_path(), "w") as f:
            f.write("not json!!")
        self._run_analyze_and_log()   # should not raise
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_data_dir(self):
        subdir = os.path.join(self._dir, "nested", "dir")
        r = analyze(_DIVERSE_SIX)
        log_result(r, data_dir=subdir)
        self.assertTrue(os.path.isdir(subdir))


# ===========================================================================
# Edge / integration cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_all_same_protocol_chain_yield_type(self):
        data = [
            {"protocol": "Aave", "chain": "Ethereum", "yield_type": "lending",
             "weight_pct": 50.0, "apy_pct": 4.0},
            {"protocol": "Aave", "chain": "Ethereum", "yield_type": "lending",
             "weight_pct": 50.0, "apy_pct": 5.0},
        ]
        r = analyze(data)
        # All three HHIs = 1 → combined = 1 → score = 0
        self.assertAlmostEqual(r["herfindahl_index"], 1.0, places=5)
        self.assertAlmostEqual(r["diversification_score"], 0.0, places=4)

    def test_two_protocols_same_chain_same_yield(self):
        r = analyze(_EQUAL_TWO)
        # protocol HHI=0.5, chain HHI=1, yield_type HHI=1 → combined=5/6≈0.833
        self.assertAlmostEqual(r["protocol_hhi"], 0.5, places=5)
        self.assertAlmostEqual(r["chain_hhi"], 1.0, places=5)

    def test_zero_apy_allocations(self):
        data = [{"protocol": "A", "chain": "E", "yield_type": "l", "weight_pct": 100.0, "apy_pct": 0.0}]
        r = analyze(data)
        self.assertAlmostEqual(r["weighted_apy_pct"], 0.0)

    def test_high_apy_entry(self):
        data = [{"protocol": "A", "chain": "E", "yield_type": "l", "weight_pct": 100.0, "apy_pct": 50.0}]
        r = analyze(data)
        self.assertAlmostEqual(r["weighted_apy_pct"], 50.0)

    def test_large_number_of_allocations(self):
        data = [
            {"protocol": f"P{i}", "chain": f"C{i}", "yield_type": f"Y{i}",
             "weight_pct": 1.0, "apy_pct": 5.0}
            for i in range(100)
        ]
        r = analyze(data)
        self.assertGreater(r["diversification_score"], 90.0)

    def test_partial_weight_allocations(self):
        # Weights don't sum to 100 — weighted_apy still computed correctly
        data = [
            {"protocol": "A", "chain": "E", "yield_type": "l", "weight_pct": 40.0, "apy_pct": 4.0},
            {"protocol": "B", "chain": "E", "yield_type": "l", "weight_pct": 60.0, "apy_pct": 6.0},
        ]
        r = analyze(data)
        expected = (40 * 4 + 60 * 6) / 100
        self.assertAlmostEqual(r["weighted_apy_pct"], expected, places=5)

    def test_concentration_warning_message_format(self):
        r = analyze(_SINGLE, max_single_protocol_pct=50.0)
        # 100% > 50% → warning for protocol
        proto_warns = [w for w in r["concentration_warnings"] if "Protocol" in w]
        self.assertGreater(len(proto_warns), 0)
        self.assertIn("100.0%", proto_warns[0])

    def test_three_chain_split(self):
        data = [
            {"protocol": f"P{i}", "chain": f"C{i}", "yield_type": "l",
             "weight_pct": 33.33, "apy_pct": 5.0}
            for i in range(3)
        ]
        r = analyze(data)
        self.assertAlmostEqual(r["chain_hhi"], 1.0 / 3, places=2)

    def test_no_warnings_for_well_diversified_set(self):
        data = [
            {"protocol": f"P{i}", "chain": f"C{i}", "yield_type": f"Y{i}",
             "weight_pct": 10.0, "apy_pct": 5.0}
            for i in range(10)
        ]
        r = analyze(data)
        self.assertEqual(r["concentration_warnings"], [])

    def test_result_is_serializable(self):
        r = analyze(_DIVERSE_SIX)
        r.pop("allocations")   # contains original dicts — keep serializable subset
        try:
            json.dumps(r)
        except TypeError as e:
            self.fail(f"Result not JSON serializable: {e}")


if __name__ == "__main__":
    unittest.main()
