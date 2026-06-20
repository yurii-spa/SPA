"""
Tests for MP-942: DeFiNFTCollateralValuationModel
Run: python3 -m unittest spa_core.tests.test_defi_nft_collateral_valuation_model
"""

import json
import os
import sys
import unittest
import tempfile

# Ensure project root is on path
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_nft_collateral_valuation_model import (
    DeFiNFTCollateralValuationModel,
    _compute_liquidity_discount,
    _compute_rarity_premium,
    _compute_adjusted_value,
    _compute_ltv,
    _compute_liquidation_risk,
    _get_flags,
    _get_label,
    _atomic_log_write,
    DEFAULT_CONFIG,
    FLAG_ILLIQUID,
    FLAG_RARE_TRAIT,
    FLAG_STALE_PRICE,
    FLAG_LOW_LTV,
    FLAG_BLUE_CHIP,
    LABEL_EXCELLENT,
    LABEL_GOOD,
    LABEL_ACCEPTABLE,
    LABEL_RISKY,
    LABEL_UNSUITABLE,
)


def _nft(
    collection="TestCollection",
    token_id="1",
    floor=1.0,
    rarity=50,
    vol7=5.0,
    vol30=20.0,
    holders=500,
    listings=50,
    blue_chip=50,
    last_sale=1.0,
    days_since=10,
):
    return {
        "collection_name": collection,
        "token_id": token_id,
        "floor_price_eth": floor,
        "trait_rarity_score": rarity,
        "volume_7d_eth": vol7,
        "volume_30d_eth": vol30,
        "holder_count": holders,
        "listing_count": listings,
        "blue_chip_score": blue_chip,
        "last_sale_price_eth": last_sale,
        "days_since_last_sale": days_since,
    }


class TestConstants(unittest.TestCase):
    def test_flag_names(self):
        self.assertEqual(FLAG_ILLIQUID, "ILLIQUID")
        self.assertEqual(FLAG_RARE_TRAIT, "RARE_TRAIT")
        self.assertEqual(FLAG_STALE_PRICE, "STALE_PRICE")
        self.assertEqual(FLAG_LOW_LTV, "LOW_LTV_RECOMMENDED")
        self.assertEqual(FLAG_BLUE_CHIP, "BLUE_CHIP")

    def test_label_names(self):
        self.assertEqual(LABEL_EXCELLENT, "EXCELLENT")
        self.assertEqual(LABEL_GOOD, "GOOD")
        self.assertEqual(LABEL_ACCEPTABLE, "ACCEPTABLE")
        self.assertEqual(LABEL_RISKY, "RISKY")
        self.assertEqual(LABEL_UNSUITABLE, "UNSUITABLE")

    def test_default_config_keys(self):
        keys = [
            "illiquid_volume_threshold_eth",
            "rare_trait_threshold",
            "stale_days_threshold",
            "blue_chip_threshold",
            "low_ltv_threshold_pct",
            "max_rarity_premium_pct",
            "max_liquidity_discount_pct",
            "base_ltv_pct",
            "min_ltv_pct",
        ]
        for k in keys:
            self.assertIn(k, DEFAULT_CONFIG)

    def test_log_cap_100(self):
        from spa_core.analytics.defi_nft_collateral_valuation_model import LOG_CAP
        self.assertEqual(LOG_CAP, 100)


class TestLiquidityDiscount(unittest.TestCase):
    def test_high_volume_low_discount(self):
        nft = _nft(vol7=50.0, vol30=200.0, holders=1000, listings=200)
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertLess(d, 20.0)

    def test_zero_volume_high_discount(self):
        nft = _nft(vol7=0.0, vol30=0.0, holders=100, listings=0)
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertGreater(d, 25.0)

    def test_below_illiquid_threshold(self):
        nft = _nft(vol7=0.5, vol30=2.0, holders=100, listings=5)
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertGreater(d, 10.0)

    def test_above_illiquid_threshold(self):
        nft = _nft(vol7=2.0, vol30=10.0, holders=200, listings=20)
        d_high = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        nft2 = _nft(vol7=0.1, vol30=0.5, holders=200, listings=2)
        d_low = _compute_liquidity_discount(nft2, DEFAULT_CONFIG)
        self.assertLess(d_high, d_low)

    def test_discount_bounded(self):
        nft = _nft(vol7=0.0, vol30=0.0, holders=1, listings=0)
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertGreaterEqual(d, 0.0)
        self.assertLessEqual(d, DEFAULT_CONFIG["max_liquidity_discount_pct"])

    def test_custom_max_discount(self):
        nft = _nft(vol7=0.0, vol30=0.0, holders=1, listings=0)
        cfg = {**DEFAULT_CONFIG, "max_liquidity_discount_pct": 20.0}
        d = _compute_liquidity_discount(nft, cfg)
        self.assertLessEqual(d, 20.0)

    def test_returns_float(self):
        nft = _nft()
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertIsInstance(d, float)

    def test_high_listing_ratio(self):
        nft = _nft(holders=100, listings=100, vol7=5.0, vol30=20.0)
        d = _compute_liquidity_discount(nft, DEFAULT_CONFIG)
        self.assertLessEqual(d, 25.0)


class TestRarityPremium(unittest.TestCase):
    def test_zero_rarity(self):
        nft = _nft(rarity=0)
        p = _compute_rarity_premium(nft, DEFAULT_CONFIG)
        self.assertAlmostEqual(p, 0.0, places=4)

    def test_max_rarity(self):
        nft = _nft(rarity=100)
        p = _compute_rarity_premium(nft, DEFAULT_CONFIG)
        self.assertAlmostEqual(p, DEFAULT_CONFIG["max_rarity_premium_pct"], places=4)

    def test_mid_rarity(self):
        nft = _nft(rarity=50)
        p = _compute_rarity_premium(nft, DEFAULT_CONFIG)
        self.assertGreater(p, 0.0)
        self.assertLess(p, DEFAULT_CONFIG["max_rarity_premium_pct"])

    def test_monotone_increasing(self):
        premiums = [_compute_rarity_premium(_nft(rarity=r), DEFAULT_CONFIG) for r in [0, 25, 50, 75, 100]]
        for i in range(len(premiums) - 1):
            self.assertLessEqual(premiums[i], premiums[i + 1])

    def test_custom_max_premium(self):
        nft = _nft(rarity=100)
        cfg = {**DEFAULT_CONFIG, "max_rarity_premium_pct": 25.0}
        p = _compute_rarity_premium(nft, cfg)
        self.assertAlmostEqual(p, 25.0, places=4)

    def test_returns_float(self):
        nft = _nft(rarity=60)
        self.assertIsInstance(_compute_rarity_premium(nft, DEFAULT_CONFIG), float)

    def test_rarity_80_gt_half_max(self):
        nft = _nft(rarity=80)
        p = _compute_rarity_premium(nft, DEFAULT_CONFIG)
        self.assertGreater(p, DEFAULT_CONFIG["max_rarity_premium_pct"] / 2)


class TestAdjustedValue(unittest.TestCase):
    def test_zero_floor(self):
        nft = _nft(floor=0.0)
        v = _compute_adjusted_value(nft, 10.0, 5.0)
        self.assertAlmostEqual(v, 0.0)

    def test_basic_calculation(self):
        nft = _nft(floor=10.0)
        # adjusted = 10 * 1.10 * 0.90 = 9.9
        v = _compute_adjusted_value(nft, 10.0, 10.0)
        self.assertAlmostEqual(v, 9.9, places=4)

    def test_no_discount_no_premium(self):
        nft = _nft(floor=5.0)
        v = _compute_adjusted_value(nft, 0.0, 0.0)
        self.assertAlmostEqual(v, 5.0)

    def test_rarity_premium_increases_value(self):
        nft = _nft(floor=1.0)
        v_no_premium = _compute_adjusted_value(nft, 0.0, 0.0)
        v_with_premium = _compute_adjusted_value(nft, 20.0, 0.0)
        self.assertGreater(v_with_premium, v_no_premium)

    def test_discount_reduces_value(self):
        nft = _nft(floor=1.0)
        v_no_discount = _compute_adjusted_value(nft, 0.0, 0.0)
        v_with_discount = _compute_adjusted_value(nft, 0.0, 30.0)
        self.assertLess(v_with_discount, v_no_discount)

    def test_always_nonneg(self):
        nft = _nft(floor=1.0)
        v = _compute_adjusted_value(nft, 0.0, 100.0)
        self.assertGreaterEqual(v, 0.0)

    def test_returns_float(self):
        nft = _nft(floor=2.5)
        self.assertIsInstance(_compute_adjusted_value(nft, 5.0, 5.0), float)


class TestLTV(unittest.TestCase):
    def test_blue_chip_high_gives_high_ltv(self):
        nft = _nft(blue_chip=90, days_since=5, vol7=50.0, vol30=200.0)
        ltv = _compute_ltv(nft, 10.0, 5.0, DEFAULT_CONFIG)
        self.assertGreater(ltv, DEFAULT_CONFIG["min_ltv_pct"])

    def test_stale_price_reduces_ltv(self):
        nft_fresh = _nft(days_since=5)
        nft_stale = _nft(days_since=90)
        ltv_fresh = _compute_ltv(nft_fresh, 0.0, 5.0, DEFAULT_CONFIG)
        ltv_stale = _compute_ltv(nft_stale, 0.0, 5.0, DEFAULT_CONFIG)
        self.assertGreater(ltv_fresh, ltv_stale)

    def test_high_discount_reduces_ltv(self):
        nft = _nft()
        ltv_low = _compute_ltv(nft, 0.0, 5.0, DEFAULT_CONFIG)
        ltv_high = _compute_ltv(nft, 0.0, 35.0, DEFAULT_CONFIG)
        self.assertGreater(ltv_low, ltv_high)

    def test_ltv_bounded_above(self):
        nft = _nft(blue_chip=100, days_since=0)
        ltv = _compute_ltv(nft, 50.0, 0.0, DEFAULT_CONFIG)
        self.assertLessEqual(ltv, DEFAULT_CONFIG["base_ltv_pct"])

    def test_ltv_bounded_below(self):
        nft = _nft(blue_chip=0, days_since=365)
        ltv = _compute_ltv(nft, 0.0, 40.0, DEFAULT_CONFIG)
        self.assertGreaterEqual(ltv, DEFAULT_CONFIG["min_ltv_pct"])

    def test_returns_float(self):
        nft = _nft()
        self.assertIsInstance(_compute_ltv(nft, 5.0, 10.0, DEFAULT_CONFIG), float)

    def test_rarity_premium_improves_ltv(self):
        nft = _nft()
        ltv_no_rarity = _compute_ltv(nft, 0.0, 10.0, DEFAULT_CONFIG)
        ltv_with_rarity = _compute_ltv(nft, 30.0, 10.0, DEFAULT_CONFIG)
        self.assertGreaterEqual(ltv_with_rarity, ltv_no_rarity)


class TestLiquidationRisk(unittest.TestCase):
    def test_liquid_blue_chip_low_risk(self):
        nft = _nft(vol7=50.0, blue_chip=90, days_since=5)
        risk = _compute_liquidation_risk(nft, 5.0, 55.0, DEFAULT_CONFIG)
        self.assertLess(risk, 30.0)

    def test_illiquid_high_risk(self):
        nft = _nft(vol7=0.0, blue_chip=0, days_since=60)
        risk = _compute_liquidation_risk(nft, 35.0, 10.0, DEFAULT_CONFIG)
        self.assertGreater(risk, 30.0)

    def test_risk_bounded(self):
        nft = _nft(vol7=0.0, blue_chip=0, days_since=365)
        risk = _compute_liquidation_risk(nft, 40.0, 5.0, DEFAULT_CONFIG)
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 100.0)

    def test_stale_increases_risk(self):
        nft_fresh = _nft(days_since=5, vol7=2.0)
        nft_stale = _nft(days_since=90, vol7=2.0)
        r_fresh = _compute_liquidation_risk(nft_fresh, 10.0, 40.0, DEFAULT_CONFIG)
        r_stale = _compute_liquidation_risk(nft_stale, 10.0, 40.0, DEFAULT_CONFIG)
        self.assertLess(r_fresh, r_stale)

    def test_returns_float(self):
        nft = _nft()
        self.assertIsInstance(_compute_liquidation_risk(nft, 10.0, 40.0, DEFAULT_CONFIG), float)

    def test_high_discount_increases_risk(self):
        nft = _nft(vol7=5.0, days_since=10, blue_chip=50)
        r_low = _compute_liquidation_risk(nft, 5.0, 50.0, DEFAULT_CONFIG)
        r_high = _compute_liquidation_risk(nft, 35.0, 25.0, DEFAULT_CONFIG)
        self.assertLess(r_low, r_high)


class TestFlags(unittest.TestCase):
    def test_illiquid_flag(self):
        nft = _nft(vol7=0.5)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_ILLIQUID, flags)

    def test_no_illiquid_flag(self):
        nft = _nft(vol7=5.0)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_ILLIQUID, flags)

    def test_rare_trait_flag(self):
        nft = _nft(rarity=90)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_RARE_TRAIT, flags)

    def test_no_rare_trait_flag(self):
        nft = _nft(rarity=50)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_RARE_TRAIT, flags)

    def test_stale_price_flag(self):
        nft = _nft(days_since=40)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_STALE_PRICE, flags)

    def test_no_stale_price_flag(self):
        nft = _nft(days_since=10)
        flags = _get_flags(nft, 40.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_STALE_PRICE, flags)

    def test_low_ltv_flag(self):
        nft = _nft()
        flags = _get_flags(nft, 20.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_LOW_LTV, flags)

    def test_no_low_ltv_flag(self):
        nft = _nft()
        flags = _get_flags(nft, 50.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_LOW_LTV, flags)

    def test_blue_chip_flag(self):
        nft = _nft(blue_chip=80)
        flags = _get_flags(nft, 50.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_BLUE_CHIP, flags)

    def test_no_blue_chip_flag(self):
        nft = _nft(blue_chip=50)
        flags = _get_flags(nft, 50.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_BLUE_CHIP, flags)

    def test_multiple_flags(self):
        nft = _nft(vol7=0.1, rarity=85, days_since=60, blue_chip=80)
        flags = _get_flags(nft, 20.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_ILLIQUID, flags)
        self.assertIn(FLAG_RARE_TRAIT, flags)
        self.assertIn(FLAG_STALE_PRICE, flags)
        self.assertIn(FLAG_LOW_LTV, flags)
        self.assertIn(FLAG_BLUE_CHIP, flags)

    def test_returns_list(self):
        nft = _nft()
        self.assertIsInstance(_get_flags(nft, 40.0, DEFAULT_CONFIG), list)


class TestLabel(unittest.TestCase):
    def test_excellent_label(self):
        label = _get_label(55.0, 15.0, [])
        self.assertEqual(label, LABEL_EXCELLENT)

    def test_excellent_requires_no_illiquid(self):
        label = _get_label(55.0, 15.0, [FLAG_ILLIQUID])
        self.assertNotEqual(label, LABEL_EXCELLENT)

    def test_excellent_requires_no_stale(self):
        label = _get_label(55.0, 15.0, [FLAG_STALE_PRICE])
        self.assertNotEqual(label, LABEL_EXCELLENT)

    def test_good_label(self):
        label = _get_label(45.0, 35.0, [])
        self.assertEqual(label, LABEL_GOOD)

    def test_good_no_stale_required(self):
        label = _get_label(45.0, 35.0, [FLAG_STALE_PRICE])
        self.assertNotEqual(label, LABEL_GOOD)

    def test_acceptable_label(self):
        label = _get_label(30.0, 55.0, [FLAG_ILLIQUID])
        self.assertEqual(label, LABEL_ACCEPTABLE)

    def test_risky_label(self):
        label = _get_label(15.0, 75.0, [FLAG_ILLIQUID, FLAG_STALE_PRICE])
        self.assertEqual(label, LABEL_RISKY)

    def test_unsuitable_label(self):
        label = _get_label(5.0, 90.0, [FLAG_ILLIQUID, FLAG_STALE_PRICE, FLAG_LOW_LTV])
        self.assertEqual(label, LABEL_UNSUITABLE)

    def test_label_returns_string(self):
        self.assertIsInstance(_get_label(40.0, 30.0, []), str)


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_creates_file(self):
        _atomic_log_write({"a": 1}, self.tmp, 100)
        self.assertTrue(os.path.exists(self.tmp))

    def test_reads_back_correct(self):
        _atomic_log_write({"x": 42}, self.tmp, 100)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 42)

    def test_appends_multiple(self):
        for i in range(5):
            _atomic_log_write({"i": i}, self.tmp, 100)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(10):
            _atomic_log_write({"i": i}, self.tmp, 5)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertEqual(data[-1]["i"], 9)

    def test_tmp_file_cleaned_up(self):
        _atomic_log_write({"a": 1}, self.tmp, 100)
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))


class TestModelValueEmptyInput(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_empty_list_returns_dict(self):
        result = self.model.value([], {})
        self.assertIsInstance(result, dict)

    def test_empty_nfts_key_present(self):
        result = self.model.value([], {})
        self.assertIn("nfts", result)
        self.assertEqual(result["nfts"], [])

    def test_empty_aggregates_present(self):
        result = self.model.value([], {})
        self.assertIn("aggregates", result)

    def test_empty_total_value_zero(self):
        result = self.model.value([], {})
        self.assertEqual(result["aggregates"]["total_portfolio_value_eth"], 0.0)

    def test_empty_excellent_count_zero(self):
        result = self.model.value([], {})
        self.assertEqual(result["aggregates"]["excellent_count"], 0)

    def test_empty_best_worst_none(self):
        result = self.model.value([], {})
        self.assertIsNone(result["aggregates"]["best_collateral"])
        self.assertIsNone(result["aggregates"]["worst_collateral"])


class TestModelValueSingleNFT(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_single_nft_result_structure(self):
        result = self.model.value([_nft()], {})
        self.assertEqual(len(result["nfts"]), 1)
        nft_result = result["nfts"][0]
        for key in ["collection_name", "token_id", "floor_price_eth", "rarity_premium_pct",
                    "liquidity_discount_pct", "adjusted_value_eth", "ltv_recommended_pct",
                    "liquidation_risk_score", "collateral_label", "flags"]:
            self.assertIn(key, nft_result)

    def test_single_nft_label_valid(self):
        result = self.model.value([_nft()], {})
        label = result["nfts"][0]["collateral_label"]
        self.assertIn(label, [LABEL_EXCELLENT, LABEL_GOOD, LABEL_ACCEPTABLE, LABEL_RISKY, LABEL_UNSUITABLE])

    def test_single_nft_adjusted_value_positive(self):
        result = self.model.value([_nft(floor=2.0)], {})
        self.assertGreater(result["nfts"][0]["adjusted_value_eth"], 0.0)

    def test_single_nft_ltv_in_range(self):
        result = self.model.value([_nft()], {})
        ltv = result["nfts"][0]["ltv_recommended_pct"]
        self.assertGreaterEqual(ltv, DEFAULT_CONFIG["min_ltv_pct"])
        self.assertLessEqual(ltv, DEFAULT_CONFIG["base_ltv_pct"])

    def test_single_nft_risk_in_range(self):
        result = self.model.value([_nft()], {})
        risk = result["nfts"][0]["liquidation_risk_score"]
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 100.0)

    def test_single_nft_flags_list(self):
        result = self.model.value([_nft()], {})
        self.assertIsInstance(result["nfts"][0]["flags"], list)

    def test_timestamp_present(self):
        result = self.model.value([_nft()], {})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


class TestModelValueMultipleNFTs(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log)
        self.nfts = [
            _nft("Bored Apes", "1", floor=80.0, rarity=90, vol7=50, vol30=200, blue_chip=95, days_since=3),
            _nft("CryptoPunks", "42", floor=50.0, rarity=60, vol7=20, vol30=80, blue_chip=85, days_since=7),
            _nft("Goblintown", "99", floor=0.1, rarity=10, vol7=0.05, vol30=0.2, blue_chip=10, days_since=60),
        ]

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_count_matches(self):
        result = self.model.value(self.nfts, {})
        self.assertEqual(len(result["nfts"]), 3)
        self.assertEqual(result["aggregates"]["nft_count"], 3)

    def test_total_value_positive(self):
        result = self.model.value(self.nfts, {})
        self.assertGreater(result["aggregates"]["total_portfolio_value_eth"], 0.0)

    def test_best_collateral_has_structure(self):
        result = self.model.value(self.nfts, {})
        best = result["aggregates"]["best_collateral"]
        for key in ["collection", "token_id", "label", "ltv"]:
            self.assertIn(key, best)

    def test_worst_collateral_has_structure(self):
        result = self.model.value(self.nfts, {})
        worst = result["aggregates"]["worst_collateral"]
        for key in ["collection", "token_id", "label", "ltv"]:
            self.assertIn(key, worst)

    def test_best_ltv_gte_worst_ltv(self):
        result = self.model.value(self.nfts, {})
        best_ltv = result["aggregates"]["best_collateral"]["ltv"]
        worst_ltv = result["aggregates"]["worst_collateral"]["ltv"]
        self.assertGreaterEqual(best_ltv, worst_ltv)

    def test_average_ltv_in_range(self):
        result = self.model.value(self.nfts, {})
        avg = result["aggregates"]["average_recommended_ltv"]
        self.assertGreater(avg, 0.0)
        self.assertLessEqual(avg, DEFAULT_CONFIG["base_ltv_pct"])

    def test_excellent_count_nonneg(self):
        result = self.model.value(self.nfts, {})
        self.assertGreaterEqual(result["aggregates"]["excellent_count"], 0)

    def test_excellent_count_lte_total(self):
        result = self.model.value(self.nfts, {})
        self.assertLessEqual(result["aggregates"]["excellent_count"], 3)

    def test_blue_chip_nft_excellent_or_good(self):
        result = self.model.value(self.nfts, {})
        bored_ape = result["nfts"][0]
        self.assertIn(bored_ape["collateral_label"], [LABEL_EXCELLENT, LABEL_GOOD])

    def test_illiquid_nft_risky_or_unsuitable(self):
        result = self.model.value(self.nfts, {})
        goblin = result["nfts"][2]
        self.assertIn(goblin["collateral_label"], [LABEL_RISKY, LABEL_UNSUITABLE, LABEL_ACCEPTABLE])

    def test_illiquid_nft_has_flag(self):
        result = self.model.value(self.nfts, {})
        goblin = result["nfts"][2]
        self.assertIn(FLAG_ILLIQUID, goblin["flags"])

    def test_stale_nft_has_flag(self):
        result = self.model.value(self.nfts, {})
        goblin = result["nfts"][2]
        self.assertIn(FLAG_STALE_PRICE, goblin["flags"])

    def test_log_written(self):
        self.model.value(self.nfts, {})
        self.assertTrue(os.path.exists(self.tmp_log))


class TestLogRingBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log, log_cap=5)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_log_capped(self):
        for _ in range(10):
            self.model.value([_nft()], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_entries_have_timestamp(self):
        self.model.value([_nft()], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entries_have_nft_count(self):
        self.model.value([_nft(), _nft("B", "2")], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["nft_count"], 2)


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_custom_base_ltv(self):
        cfg = {"base_ltv_pct": 80.0}
        result = self.model.value([_nft(blue_chip=90, days_since=5, vol7=50, vol30=200)], cfg)
        ltv = result["nfts"][0]["ltv_recommended_pct"]
        self.assertLessEqual(ltv, 80.0)

    def test_custom_blue_chip_threshold(self):
        nft = _nft(blue_chip=60)
        cfg = {"blue_chip_threshold": 55}
        result = self.model.value([nft], cfg)
        self.assertIn(FLAG_BLUE_CHIP, result["nfts"][0]["flags"])

    def test_custom_stale_days(self):
        nft = _nft(days_since=15)
        cfg = {"stale_days_threshold": 10}
        result = self.model.value([nft], cfg)
        self.assertIn(FLAG_STALE_PRICE, result["nfts"][0]["flags"])

    def test_none_config_uses_defaults(self):
        result = self.model.value([_nft()], None)
        self.assertIsInstance(result, dict)

    def test_custom_rare_trait_threshold(self):
        nft = _nft(rarity=60)
        cfg = {"rare_trait_threshold": 55}
        result = self.model.value([nft], cfg)
        self.assertIn(FLAG_RARE_TRAIT, result["nfts"][0]["flags"])

    def test_custom_illiquid_threshold(self):
        nft = _nft(vol7=3.0)
        cfg = {"illiquid_volume_threshold_eth": 5.0}
        result = self.model.value([nft], cfg)
        self.assertIn(FLAG_ILLIQUID, result["nfts"][0]["flags"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.model = DeFiNFTCollateralValuationModel(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_zero_floor_price(self):
        result = self.model.value([_nft(floor=0.0)], {})
        self.assertAlmostEqual(result["nfts"][0]["adjusted_value_eth"], 0.0)

    def test_very_large_floor(self):
        result = self.model.value([_nft(floor=10000.0)], {})
        self.assertGreater(result["nfts"][0]["adjusted_value_eth"], 0.0)

    def test_rarity_100_has_flag(self):
        result = self.model.value([_nft(rarity=100)], {})
        self.assertIn(FLAG_RARE_TRAIT, result["nfts"][0]["flags"])

    def test_very_old_nft_has_stale_flag(self):
        result = self.model.value([_nft(days_since=365)], {})
        self.assertIn(FLAG_STALE_PRICE, result["nfts"][0]["flags"])

    def test_blue_chip_100_has_flag(self):
        result = self.model.value([_nft(blue_chip=100)], {})
        self.assertIn(FLAG_BLUE_CHIP, result["nfts"][0]["flags"])

    def test_single_nft_best_worst_same(self):
        result = self.model.value([_nft(collection="A")], {})
        best = result["aggregates"]["best_collateral"]
        worst = result["aggregates"]["worst_collateral"]
        self.assertEqual(best["collection"], worst["collection"])

    def test_missing_keys_handled(self):
        # Minimal NFT with almost no keys
        nft_minimal = {"collection_name": "X", "token_id": "0"}
        result = self.model.value([nft_minimal], {})
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result["nfts"]), 1)

    def test_rarity_premium_capped(self):
        nft = _nft(rarity=100)
        p = _compute_rarity_premium(nft, DEFAULT_CONFIG)
        self.assertLessEqual(p, DEFAULT_CONFIG["max_rarity_premium_pct"] + 0.001)

    def test_adjusted_value_with_both_premium_and_discount(self):
        nft = _nft(floor=10.0)
        v = _compute_adjusted_value(nft, 20.0, 10.0)
        # 10 * 1.2 * 0.9 = 10.8
        self.assertAlmostEqual(v, 10.8, places=4)

    def test_result_is_deterministic(self):
        nfts = [_nft("A", "1"), _nft("B", "2")]
        r1 = self.model.value(nfts, {})
        r2 = self.model.value(nfts, {})
        # Adjusted values should be equal
        self.assertAlmostEqual(
            r1["nfts"][0]["adjusted_value_eth"],
            r2["nfts"][0]["adjusted_value_eth"]
        )


if __name__ == "__main__":
    unittest.main()
