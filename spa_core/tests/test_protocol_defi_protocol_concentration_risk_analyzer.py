"""
Tests for MP-1137: ProtocolDeFiProtocolConcentrationRiskAnalyzer
>=110 test cases using unittest only.
Tempfile-based log isolation — production data/ is never touched.
Pure stdlib.  Python 3.9 compatible.
"""

import json
import os
import tempfile
import unittest
from typing import Any, Dict

from spa_core.analytics.protocol_defi_protocol_concentration_risk_analyzer import (
    LABEL_CONCENTRATED_MAX,
    LABEL_GOOD_DIVERSIFICATION_MAX,
    LABEL_MODERATE_CONCENTRATION_MAX,
    LABEL_WELL_DIVERSIFIED_MAX,
    LOG_MAX_ENTRIES,
    REQUIRED_POSITION_FIELDS,
    WEIGHT_CHAIN,
    WEIGHT_PROTOCOL,
    WEIGHT_YIELD_TYPE,
    ProtocolDeFiProtocolConcentrationRiskAnalyzer,
    _atomic_write,
    _blended_apy,
    _concentration_label,
    _concentration_score,
    _group_by,
    _hhi,
    _load_log,
    _validate_positions,
    _validate_total,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol_name: str = "Aave",
    chain: str = "Ethereum",
    yield_type: str = "lending",
    value_usd: float = 10_000.0,
    apy_pct: float = 5.0,
) -> Dict[str, Any]:
    return {
        "protocol_name": protocol_name,
        "chain": chain,
        "yield_type": yield_type,
        "value_usd": value_usd,
        "apy_pct": apy_pct,
    }


def _mk_analyzer(tmp_dir: str) -> ProtocolDeFiProtocolConcentrationRiskAnalyzer:
    log = os.path.join(tmp_dir, "pca_log.json")
    return ProtocolDeFiProtocolConcentrationRiskAnalyzer(log_path=log)


# Two identical 50/50 protocols across the same chain / yield type
EQUAL_TWO = [
    _pos("Aave", "Ethereum", "lending", 50_000.0, 4.0),
    _pos("Compound", "Ethereum", "lending", 50_000.0, 5.0),
]

# Single protocol — maximum concentration
SINGLE = [_pos("Aave", "Ethereum", "lending", 100_000.0, 6.0)]


# ===========================================================================
# TestValidatePositions
# ===========================================================================

class TestValidatePositions(unittest.TestCase):
    """20 tests for _validate_positions."""

    def test_empty_list_passes(self):
        _validate_positions([])  # no exception

    def test_single_valid_position(self):
        _validate_positions([_pos()])

    def test_multiple_valid_positions(self):
        _validate_positions([_pos(), _pos("Compound"), _pos("Morpho")])

    def test_positions_not_list_raises(self):
        with self.assertRaises(TypeError):
            _validate_positions({"a": 1})  # type: ignore

    def test_position_not_dict_raises(self):
        with self.assertRaises(TypeError):
            _validate_positions(["not_a_dict"])  # type: ignore

    def test_missing_protocol_name_raises(self):
        p = _pos()
        del p["protocol_name"]
        with self.assertRaises(ValueError):
            _validate_positions([p])

    def test_missing_chain_raises(self):
        p = _pos()
        del p["chain"]
        with self.assertRaises(ValueError):
            _validate_positions([p])

    def test_missing_yield_type_raises(self):
        p = _pos()
        del p["yield_type"]
        with self.assertRaises(ValueError):
            _validate_positions([p])

    def test_missing_value_usd_raises(self):
        p = _pos()
        del p["value_usd"]
        with self.assertRaises(ValueError):
            _validate_positions([p])

    def test_missing_apy_pct_raises(self):
        p = _pos()
        del p["apy_pct"]
        with self.assertRaises(ValueError):
            _validate_positions([p])

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_positions([_pos(protocol_name="")])

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_positions([_pos(protocol_name="  ")])

    def test_empty_chain_raises(self):
        with self.assertRaises(ValueError):
            _validate_positions([_pos(chain="")])

    def test_empty_yield_type_raises(self):
        with self.assertRaises(ValueError):
            _validate_positions([_pos(yield_type="")])

    def test_negative_value_usd_raises(self):
        with self.assertRaises(ValueError):
            _validate_positions([_pos(value_usd=-1.0)])

    def test_zero_value_usd_ok(self):
        _validate_positions([_pos(value_usd=0.0)])  # allowed

    def test_required_fields_constant(self):
        self.assertIn("protocol_name", REQUIRED_POSITION_FIELDS)
        self.assertIn("chain", REQUIRED_POSITION_FIELDS)
        self.assertIn("yield_type", REQUIRED_POSITION_FIELDS)
        self.assertIn("value_usd", REQUIRED_POSITION_FIELDS)
        self.assertIn("apy_pct", REQUIRED_POSITION_FIELDS)

    def test_extra_fields_pass(self):
        p = _pos()
        p["extra_field"] = "ignored"
        _validate_positions([p])

    def test_validate_total_zero_raises(self):
        with self.assertRaises(ValueError):
            _validate_total(0.0)

    def test_validate_total_negative_raises(self):
        with self.assertRaises(ValueError):
            _validate_total(-100.0)


# ===========================================================================
# TestHHI
# ===========================================================================

class TestHHI(unittest.TestCase):
    """15 tests for _hhi."""

    def test_single_group_hhi_is_one(self):
        # All value in one group → share=1 → HHI=1
        groups = {"Aave": 100_000.0}
        self.assertAlmostEqual(_hhi(groups, 100_000.0), 1.0)

    def test_two_equal_groups_hhi(self):
        # Each share = 0.5 → HHI = 0.5^2 + 0.5^2 = 0.5
        groups = {"A": 50_000.0, "B": 50_000.0}
        self.assertAlmostEqual(_hhi(groups, 100_000.0), 0.5)

    def test_four_equal_groups_hhi(self):
        # Each share = 0.25 → HHI = 4 * 0.0625 = 0.25
        groups = {str(i): 25_000.0 for i in range(4)}
        self.assertAlmostEqual(_hhi(groups, 100_000.0), 0.25)

    def test_ten_equal_groups_hhi(self):
        groups = {str(i): 10_000.0 for i in range(10)}
        self.assertAlmostEqual(_hhi(groups, 100_000.0), 0.10)

    def test_empty_groups_returns_zero(self):
        self.assertAlmostEqual(_hhi({}, 100_000.0), 0.0)

    def test_hhi_always_0_to_1(self):
        for n in [1, 2, 5, 10, 20]:
            groups = {str(i): 100.0 for i in range(n)}
            h = _hhi(groups, float(n) * 100.0)
            self.assertGreaterEqual(h, 0.0)
            self.assertLessEqual(h, 1.0)

    def test_larger_total_dilutes_hhi(self):
        # Same groups, larger total (cash in portfolio) → lower HHI
        groups = {"Aave": 50_000.0}
        h_small = _hhi(groups, 50_000.0)   # share=1, HHI=1
        h_large = _hhi(groups, 100_000.0)  # share=0.5, HHI=0.25
        self.assertGreater(h_small, h_large)

    def test_80_20_split(self):
        # 80% in A, 20% in B → HHI = 0.64 + 0.04 = 0.68
        groups = {"A": 80_000.0, "B": 20_000.0}
        self.assertAlmostEqual(_hhi(groups, 100_000.0), 0.68)

    def test_hhi_is_rounded(self):
        groups = {"A": 100_000.0}
        h = _hhi(groups, 100_000.0)
        self.assertEqual(round(h, 6), h)

    def test_hhi_sum_less_than_one_when_cash(self):
        # positions total 60k, portfolio 100k → HHI based on portfolio
        groups = {"A": 60_000.0}
        h = _hhi(groups, 100_000.0)
        self.assertAlmostEqual(h, 0.36)

    def test_zero_group_value_does_not_raise(self):
        groups = {"A": 0.0, "B": 100_000.0}
        h = _hhi(groups, 100_000.0)
        self.assertAlmostEqual(h, 1.0)

    def test_total_less_than_one_edge(self):
        groups = {"A": 0.5}
        h = _hhi(groups, 1.0)
        self.assertAlmostEqual(h, 0.25)

    def test_single_tiny_group(self):
        groups = {"A": 1.0}
        h = _hhi(groups, 1_000_000.0)
        self.assertAlmostEqual(h, 1e-12)

    def test_three_groups_33pct_each(self):
        # 33333.33 each → shares ≈ 1/3 each → HHI ≈ 1/3
        v = 100_000.0 / 3.0
        groups = {"A": v, "B": v, "C": v}
        h = _hhi(groups, 100_000.0)
        self.assertAlmostEqual(h, 1.0 / 3.0, places=4)

    def test_hhi_equals_sum_of_squared_shares(self):
        groups = {"A": 40_000.0, "B": 35_000.0, "C": 25_000.0}
        total = 100_000.0
        expected = sum((v / total) ** 2 for v in groups.values())
        self.assertAlmostEqual(_hhi(groups, total), round(expected, 6))


# ===========================================================================
# TestGroupBy
# ===========================================================================

class TestGroupBy(unittest.TestCase):
    """10 tests for _group_by."""

    def test_single_position(self):
        positions = [_pos("Aave", value_usd=10_000.0)]
        groups = _group_by(positions, "protocol_name")
        self.assertEqual(groups, {"Aave": 10_000.0})

    def test_two_same_protocol_summed(self):
        positions = [
            _pos("Aave", value_usd=10_000.0),
            _pos("Aave", value_usd=5_000.0),
        ]
        groups = _group_by(positions, "protocol_name")
        self.assertAlmostEqual(groups["Aave"], 15_000.0)

    def test_two_different_protocols(self):
        positions = [_pos("Aave", value_usd=10_000.0), _pos("Compound", value_usd=8_000.0)]
        groups = _group_by(positions, "protocol_name")
        self.assertEqual(len(groups), 2)
        self.assertAlmostEqual(groups["Aave"], 10_000.0)
        self.assertAlmostEqual(groups["Compound"], 8_000.0)

    def test_empty_positions_returns_empty(self):
        self.assertEqual(_group_by([], "protocol_name"), {})

    def test_group_by_chain(self):
        positions = [
            _pos(chain="Ethereum", value_usd=40_000.0),
            _pos(chain="Arbitrum", value_usd=30_000.0),
            _pos(chain="Ethereum", value_usd=30_000.0),
        ]
        groups = _group_by(positions, "chain")
        self.assertAlmostEqual(groups["Ethereum"], 70_000.0)
        self.assertAlmostEqual(groups["Arbitrum"], 30_000.0)

    def test_group_by_yield_type(self):
        positions = [
            _pos(yield_type="lending", value_usd=50_000.0),
            _pos(yield_type="staking", value_usd=30_000.0),
            _pos(yield_type="lending", value_usd=20_000.0),
        ]
        groups = _group_by(positions, "yield_type")
        self.assertAlmostEqual(groups["lending"], 70_000.0)
        self.assertAlmostEqual(groups["staking"], 30_000.0)

    def test_zero_value_still_included(self):
        positions = [_pos("ZeroProto", value_usd=0.0)]
        groups = _group_by(positions, "protocol_name")
        self.assertIn("ZeroProto", groups)
        self.assertAlmostEqual(groups["ZeroProto"], 0.0)

    def test_key_is_string_coerced(self):
        positions = [_pos("Aave")]
        groups = _group_by(positions, "protocol_name")
        self.assertIn("Aave", groups)

    def test_multiple_chains_grouped_correctly(self):
        positions = [
            _pos(chain="ETH", value_usd=10.0),
            _pos(chain="ARB", value_usd=20.0),
            _pos(chain="OPT", value_usd=30.0),
        ]
        groups = _group_by(positions, "chain")
        self.assertEqual(len(groups), 3)

    def test_sum_of_groups_equals_sum_of_values(self):
        positions = [
            _pos("A", value_usd=10_000.0), _pos("B", value_usd=20_000.0),
            _pos("A", value_usd=5_000.0),
        ]
        groups = _group_by(positions, "protocol_name")
        self.assertAlmostEqual(sum(groups.values()), 35_000.0)


# ===========================================================================
# TestBlendedAPY
# ===========================================================================

class TestBlendedAPY(unittest.TestCase):
    """10 tests for _blended_apy."""

    def test_single_position(self):
        positions = [_pos(value_usd=10_000.0, apy_pct=5.0)]
        self.assertAlmostEqual(_blended_apy(positions, 10_000.0), 5.0)

    def test_equal_weights_average(self):
        positions = [
            _pos(value_usd=10_000.0, apy_pct=4.0),
            _pos(value_usd=10_000.0, apy_pct=6.0),
        ]
        self.assertAlmostEqual(_blended_apy(positions, 20_000.0), 5.0)

    def test_unequal_weights(self):
        # 80% in 4% + 20% in 10% → 0.8*4 + 0.2*10 = 3.2 + 2 = 5.2
        positions = [
            _pos(value_usd=80_000.0, apy_pct=4.0),
            _pos(value_usd=20_000.0, apy_pct=10.0),
        ]
        self.assertAlmostEqual(_blended_apy(positions, 100_000.0), 5.2)

    def test_zero_total_returns_zero(self):
        positions = [_pos(value_usd=0.0, apy_pct=10.0)]
        self.assertAlmostEqual(_blended_apy(positions, 0.0), 0.0)

    def test_empty_positions_total_zero(self):
        self.assertAlmostEqual(_blended_apy([], 0.0), 0.0)

    def test_zero_apy(self):
        positions = [_pos(value_usd=10_000.0, apy_pct=0.0)]
        self.assertAlmostEqual(_blended_apy(positions, 10_000.0), 0.0)

    def test_high_apy(self):
        positions = [_pos(value_usd=5_000.0, apy_pct=30.0)]
        self.assertAlmostEqual(_blended_apy(positions, 5_000.0), 30.0)

    def test_three_positions_weighted(self):
        positions = [
            _pos(value_usd=50_000.0, apy_pct=3.0),
            _pos(value_usd=30_000.0, apy_pct=6.0),
            _pos(value_usd=20_000.0, apy_pct=12.0),
        ]
        total = 100_000.0
        expected = (50_000*3 + 30_000*6 + 20_000*12) / total
        self.assertAlmostEqual(_blended_apy(positions, total), expected)

    def test_blended_apy_uses_position_value_not_portfolio_total(self):
        # total_invested != total_portfolio_usd (cash difference)
        positions = [_pos(value_usd=50_000.0, apy_pct=8.0)]
        # blended_apy should use 50_000 as denominator, not 100_000
        self.assertAlmostEqual(_blended_apy(positions, 50_000.0), 8.0)

    def test_result_rounded(self):
        positions = [_pos(value_usd=1.0, apy_pct=1.0 / 3.0)]
        result = _blended_apy(positions, 1.0)
        self.assertEqual(round(result, 6), result)


# ===========================================================================
# TestConcentrationScore
# ===========================================================================

class TestConcentrationScore(unittest.TestCase):
    """14 tests for _concentration_score."""

    def test_all_zeros(self):
        self.assertEqual(_concentration_score(0.0, 0.0, 0.0), 0)

    def test_all_ones(self):
        # 1*50 + 1*30 + 1*20 = 100
        self.assertEqual(_concentration_score(1.0, 1.0, 1.0), 100)

    def test_only_protocol_hhi(self):
        # hhi_protocol=1, others=0 → 50
        self.assertEqual(_concentration_score(1.0, 0.0, 0.0), 50)

    def test_only_chain_hhi(self):
        self.assertEqual(_concentration_score(0.0, 1.0, 0.0), 30)

    def test_only_yield_type_hhi(self):
        self.assertEqual(_concentration_score(0.0, 0.0, 1.0), 20)

    def test_equal_weights_sum_to_100(self):
        self.assertEqual(WEIGHT_PROTOCOL + WEIGHT_CHAIN + WEIGHT_YIELD_TYPE, 100.0)

    def test_two_equal_protocols_one_chain(self):
        # hhi_protocol=0.5, hhi_chain=1 (all ETH), hhi_yield=1 (all lending)
        score = _concentration_score(0.5, 1.0, 1.0)
        expected = int(0.5 * 50 + 1.0 * 30 + 1.0 * 20)
        self.assertEqual(score, expected)

    def test_score_truncates_not_rounds(self):
        # 0.3*50 + 0.3*30 + 0.3*20 = 15+9+6 = 30
        self.assertEqual(_concentration_score(0.3, 0.3, 0.3), 30)

    def test_score_clamped_max_100(self):
        self.assertEqual(_concentration_score(1.5, 1.5, 1.5), 100)

    def test_score_clamped_min_0(self):
        self.assertEqual(_concentration_score(-0.1, 0.0, 0.0), 0)

    def test_score_is_int(self):
        self.assertIsInstance(_concentration_score(0.5, 0.5, 0.5), int)

    def test_score_monotone_with_protocol_hhi(self):
        scores = [_concentration_score(h, 0.5, 0.5) for h in [0, 0.25, 0.5, 0.75, 1.0]]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_partial_concentration(self):
        # hhi_protocol=0.5, hhi_chain=0.5, hhi_yield=0.5
        expected = int(0.5*50 + 0.5*30 + 0.5*20)  # int(50) = 50
        self.assertEqual(_concentration_score(0.5, 0.5, 0.5), expected)

    def test_small_concentration(self):
        # 10 equal protocols, 3 chains, 2 yield types
        # hhi_prot=0.1, hhi_chain≈0.333, hhi_yield=0.5
        score = _concentration_score(0.1, 1/3, 0.5)
        expected = int(0.1*50 + (1/3)*30 + 0.5*20)
        self.assertEqual(score, expected)


# ===========================================================================
# TestConcentrationLabel
# ===========================================================================

class TestConcentrationLabel(unittest.TestCase):
    """12 tests for _concentration_label."""

    def test_score_0_well_diversified(self):
        self.assertEqual(_concentration_label(0), "WELL_DIVERSIFIED")

    def test_score_20_well_diversified(self):
        self.assertEqual(_concentration_label(20), "WELL_DIVERSIFIED")

    def test_score_21_good(self):
        self.assertEqual(_concentration_label(21), "GOOD_DIVERSIFICATION")

    def test_score_40_good(self):
        self.assertEqual(_concentration_label(40), "GOOD_DIVERSIFICATION")

    def test_score_41_moderate(self):
        self.assertEqual(_concentration_label(41), "MODERATE_CONCENTRATION")

    def test_score_60_moderate(self):
        self.assertEqual(_concentration_label(60), "MODERATE_CONCENTRATION")

    def test_score_61_concentrated(self):
        self.assertEqual(_concentration_label(61), "CONCENTRATED")

    def test_score_80_concentrated(self):
        self.assertEqual(_concentration_label(80), "CONCENTRATED")

    def test_score_81_single_point(self):
        self.assertEqual(_concentration_label(81), "SINGLE_POINT_OF_FAILURE")

    def test_score_100_single_point(self):
        self.assertEqual(_concentration_label(100), "SINGLE_POINT_OF_FAILURE")

    def test_label_constants_correct(self):
        self.assertEqual(LABEL_WELL_DIVERSIFIED_MAX, 20)
        self.assertEqual(LABEL_GOOD_DIVERSIFICATION_MAX, 40)
        self.assertEqual(LABEL_MODERATE_CONCENTRATION_MAX, 60)
        self.assertEqual(LABEL_CONCENTRATED_MAX, 80)

    def test_all_valid_labels_covered(self):
        valid = {
            "WELL_DIVERSIFIED", "GOOD_DIVERSIFICATION",
            "MODERATE_CONCENTRATION", "CONCENTRATED", "SINGLE_POINT_OF_FAILURE",
        }
        for s in range(0, 101, 10):
            self.assertIn(_concentration_label(s), valid)


# ===========================================================================
# TestAnalyzeOutputs
# ===========================================================================

class TestAnalyzeOutputs(unittest.TestCase):
    """28 tests for ProtocolDeFiProtocolConcentrationRiskAnalyzer.analyze()."""

    EXPECTED_KEYS = {
        "num_positions", "hhi_protocol", "hhi_chain", "hhi_yield_type",
        "largest_position_pct", "largest_protocol", "blended_apy_pct",
        "concentration_score", "concentration_label", "generated_at",
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _mk_analyzer(self.tmp)

    def test_all_keys_present(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertEqual(set(r.keys()), self.EXPECTED_KEYS)

    def test_num_positions_correct(self):
        r = self.a.analyze(EQUAL_TWO, 100_000.0)
        self.assertEqual(r["num_positions"], 2)

    def test_num_positions_single(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertEqual(r["num_positions"], 1)

    def test_num_positions_empty(self):
        r = self.a.analyze([], 100_000.0)
        self.assertEqual(r["num_positions"], 0)

    def test_single_protocol_hhi_is_one(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], 1.0)

    def test_two_equal_hhi_protocol(self):
        r = self.a.analyze(EQUAL_TWO, 100_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], 0.5)

    def test_single_chain_hhi_is_one(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertAlmostEqual(r["hhi_chain"], 1.0)

    def test_two_equal_chains_hhi(self):
        positions = [
            _pos("Aave", "Ethereum", "lending", 50_000.0),
            _pos("Compound", "Arbitrum", "lending", 50_000.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertAlmostEqual(r["hhi_chain"], 0.5)

    def test_single_yield_type_hhi_is_one(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertAlmostEqual(r["hhi_yield_type"], 1.0)

    def test_largest_protocol_single(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertEqual(r["largest_protocol"], "Aave")

    def test_largest_protocol_from_two(self):
        positions = [
            _pos("Aave", value_usd=70_000.0),
            _pos("Compound", value_usd=30_000.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertEqual(r["largest_protocol"], "Aave")

    def test_largest_position_pct_single(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertAlmostEqual(r["largest_position_pct"], 100.0)

    def test_largest_position_pct_70_30(self):
        positions = [
            _pos("Aave", value_usd=70_000.0),
            _pos("Compound", value_usd=30_000.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertAlmostEqual(r["largest_position_pct"], 70.0)

    def test_blended_apy_single(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertAlmostEqual(r["blended_apy_pct"], 6.0)

    def test_blended_apy_two_equal(self):
        # 50k@4% + 50k@5% = 4.5%
        r = self.a.analyze(EQUAL_TWO, 100_000.0)
        self.assertAlmostEqual(r["blended_apy_pct"], 4.5)

    def test_concentration_score_single_protocol(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        # hhi_prot=1, hhi_chain=1, hhi_yield=1 → 100
        self.assertEqual(r["concentration_score"], 100)

    def test_concentration_label_single_protocol(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertEqual(r["concentration_label"], "SINGLE_POINT_OF_FAILURE")

    def test_generated_at_is_string(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertIsInstance(r["generated_at"], str)

    def test_concentration_score_is_int(self):
        r = self.a.analyze(EQUAL_TWO, 100_000.0)
        self.assertIsInstance(r["concentration_score"], int)

    def test_well_diversified_label(self):
        # 10 protocols, 5 chains, 3 yield types → low HHIs
        positions = [
            _pos(f"Proto{i}", f"Chain{i % 5}", f"yt{i % 3}", 10_000.0)
            for i in range(10)
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertIn(r["concentration_label"],
                      {"WELL_DIVERSIFIED", "GOOD_DIVERSIFICATION"})

    def test_empty_positions_zero_score(self):
        r = self.a.analyze([], 100_000.0)
        self.assertEqual(r["concentration_score"], 0)
        self.assertEqual(r["concentration_label"], "WELL_DIVERSIFIED")

    def test_hhi_values_0_to_1(self):
        r = self.a.analyze(EQUAL_TWO, 100_000.0)
        for key in ("hhi_protocol", "hhi_chain", "hhi_yield_type"):
            self.assertGreaterEqual(r[key], 0.0)
            self.assertLessEqual(r[key], 1.0)

    def test_cash_dilutes_hhi(self):
        # Same position, different total_portfolio_usd
        positions = [_pos("Aave", value_usd=50_000.0)]
        r_no_cash = self.a.analyze(positions, 50_000.0)    # 100% deployed
        r_with_cash = self.a.analyze(positions, 100_000.0) # 50% in cash
        self.assertGreater(r_no_cash["hhi_protocol"], r_with_cash["hhi_protocol"])

    def test_multi_chain_lowers_chain_hhi(self):
        positions = [
            _pos("Aave", "Ethereum", value_usd=50_000.0),
            _pos("Compound", "Arbitrum", value_usd=50_000.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertLess(r["hhi_chain"], 1.0)

    def test_multi_yield_type_lowers_yield_hhi(self):
        positions = [
            _pos("Aave", "Ethereum", "lending", 50_000.0),
            _pos("Lido", "Ethereum", "staking", 50_000.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertLess(r["hhi_yield_type"], 1.0)

    def test_protocol_name_in_result(self):
        r = self.a.analyze(SINGLE, 100_000.0)
        self.assertEqual(r["largest_protocol"], "Aave")

    def test_zero_value_positions_not_affect_blended_apy(self):
        positions = [
            _pos("Aave", value_usd=100_000.0, apy_pct=5.0),
            _pos("Zero", value_usd=0.0, apy_pct=100.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertAlmostEqual(r["blended_apy_pct"], 5.0)

    def test_largest_protocol_with_zero_value_tied(self):
        positions = [
            _pos("Aave", value_usd=0.0),
            _pos("Compound", value_usd=0.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        # Both zero, max() picks one; just ensure it's non-empty str
        self.assertIsInstance(r["largest_protocol"], str)


# ===========================================================================
# TestLogging
# ===========================================================================

class TestLogging(unittest.TestCase):
    """16 tests for analyze_and_log, get_log, and ring-buffer behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "pca_log.json")
        self.a = ProtocolDeFiProtocolConcentrationRiskAnalyzer(log_path=self.log_path)

    def test_log_starts_empty(self):
        self.assertEqual(self.a.get_log(), [])

    def test_single_entry_logged(self):
        self.a.analyze_and_log(SINGLE, 100_000.0)
        self.assertEqual(len(self.a.get_log()), 1)

    def test_logged_entry_has_expected_keys(self):
        self.a.analyze_and_log(SINGLE, 100_000.0)
        entry = self.a.get_log()[0]
        self.assertIn("concentration_score", entry)
        self.assertIn("hhi_protocol", entry)

    def test_multiple_entries_accumulate(self):
        for _ in range(5):
            self.a.analyze_and_log(EQUAL_TWO, 100_000.0)
        self.assertEqual(len(self.a.get_log()), 5)

    def test_ring_buffer_caps_at_100(self):
        for i in range(105):
            self.a.analyze_and_log([_pos(f"P{i}", value_usd=10_000.0)], 100_000.0)
        self.assertEqual(len(self.a.get_log()), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_last_entries(self):
        for i in range(105):
            self.a.analyze_and_log([_pos(f"P{i}", value_usd=10_000.0)], 100_000.0)
        log = self.a.get_log()
        self.assertEqual(log[-1]["largest_protocol"], "P104")

    def test_log_file_is_valid_json(self):
        self.a.analyze_and_log(SINGLE, 100_000.0)
        with open(self.log_path, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_persists_across_instances(self):
        self.a.analyze_and_log(SINGLE, 100_000.0)
        a2 = ProtocolDeFiProtocolConcentrationRiskAnalyzer(log_path=self.log_path)
        self.assertEqual(len(a2.get_log()), 1)

    def test_corrupted_log_gracefully_recovered(self):
        with open(self.log_path, "w") as fh:
            fh.write("NOT JSON{{")
        self.a.analyze_and_log(SINGLE, 100_000.0)
        self.assertEqual(len(self.a.get_log()), 1)

    def test_missing_log_get_log_returns_empty(self):
        log = _load_log(os.path.join(self.tmp, "nonexistent.json"))
        self.assertEqual(log, [])

    def test_analyze_and_log_returns_same_fields(self):
        r1 = self.a.analyze(EQUAL_TWO, 100_000.0)
        r2 = self.a.analyze_and_log(EQUAL_TWO, 100_000.0)
        self.assertEqual(r1["concentration_score"], r2["concentration_score"])
        self.assertEqual(r1["hhi_protocol"], r2["hhi_protocol"])

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmp, "atomic_test.json")
        _atomic_write(path, [{"x": 42}])
        self.assertTrue(os.path.isfile(path))

    def test_atomic_write_no_tmp_files_left(self):
        path = os.path.join(self.tmp, "atomic2.json")
        _atomic_write(path, [])
        tmp_files = [f for f in os.listdir(self.tmp) if f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [])

    def test_exact_100_no_trim(self):
        for i in range(100):
            self.a.analyze_and_log([_pos(f"P{i}")], 100_000.0)
        self.assertEqual(len(self.a.get_log()), 100)

    def test_101st_trims_oldest(self):
        for i in range(101):
            self.a.analyze_and_log([_pos(f"P{i}", value_usd=10_000.0)], 100_000.0)
        log = self.a.get_log()
        self.assertEqual(len(log), 100)
        self.assertEqual(log[0]["largest_protocol"], "P1")

    def test_log_result_json_serializable(self):
        result = self.a.analyze_and_log(EQUAL_TWO, 100_000.0)
        serialized = json.dumps(result)  # should not raise
        self.assertIsInstance(serialized, str)


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    """10 edge and boundary tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _mk_analyzer(self.tmp)

    def test_large_portfolio(self):
        positions = [_pos("Aave", value_usd=1e9)]
        r = self.a.analyze(positions, 1e9)
        self.assertEqual(r["concentration_score"], 100)

    def test_tiny_position(self):
        positions = [_pos("Aave", value_usd=0.01)]
        r = self.a.analyze(positions, 1_000_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], (0.01 / 1_000_000.0) ** 2)

    def test_20_equal_protocols_low_hhi(self):
        positions = [_pos(f"P{i}", f"C{i % 5}", f"yt{i % 4}", 5_000.0) for i in range(20)]
        r = self.a.analyze(positions, 100_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], 0.05)

    def test_concentration_score_0_to_100_range(self):
        for n in [1, 2, 5, 10, 20]:
            positions = [_pos(f"P{i}", f"C{i}", f"yt{i}", 10_000.0) for i in range(n)]
            r = self.a.analyze(positions, float(n) * 10_000.0)
            self.assertGreaterEqual(r["concentration_score"], 0)
            self.assertLessEqual(r["concentration_score"], 100)

    def test_label_always_valid_string(self):
        valid = {
            "WELL_DIVERSIFIED", "GOOD_DIVERSIFICATION",
            "MODERATE_CONCENTRATION", "CONCENTRATED", "SINGLE_POINT_OF_FAILURE",
        }
        for positions in [[], SINGLE, EQUAL_TWO]:
            r = self.a.analyze(positions, 100_000.0)
            self.assertIn(r["concentration_label"], valid)

    def test_largest_protocol_empty_positions(self):
        r = self.a.analyze([], 100_000.0)
        self.assertEqual(r["largest_protocol"], "")
        self.assertAlmostEqual(r["largest_position_pct"], 0.0)

    def test_hhi_all_zeros_when_no_positions(self):
        r = self.a.analyze([], 100_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], 0.0)
        self.assertAlmostEqual(r["hhi_chain"], 0.0)
        self.assertAlmostEqual(r["hhi_yield_type"], 0.0)

    def test_identical_protocol_different_chains_one_protocol_hhi(self):
        # Same protocol on 3 chains → protocol HHI = 1 (all same name)
        positions = [
            _pos("Aave", "Ethereum", "lending", 33_333.0),
            _pos("Aave", "Arbitrum", "lending", 33_333.0),
            _pos("Aave", "Optimism", "lending", 33_334.0),
        ]
        r = self.a.analyze(positions, 100_000.0)
        self.assertAlmostEqual(r["hhi_protocol"], 1.0, places=3)

    def test_log_max_entries_constant(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)

    def test_weight_constants(self):
        self.assertAlmostEqual(WEIGHT_PROTOCOL, 50.0)
        self.assertAlmostEqual(WEIGHT_CHAIN, 30.0)
        self.assertAlmostEqual(WEIGHT_YIELD_TYPE, 20.0)
        self.assertAlmostEqual(WEIGHT_PROTOCOL + WEIGHT_CHAIN + WEIGHT_YIELD_TYPE, 100.0)


if __name__ == "__main__":
    unittest.main()
