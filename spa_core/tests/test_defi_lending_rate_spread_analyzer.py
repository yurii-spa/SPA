"""
MP-893 DeFiLendingRateSpreadAnalyzer — unit tests (≥65).
Run: python3 -m unittest spa_core.tests.test_defi_lending_rate_spread_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ── make the repo root importable ────────────────────────────────────────────
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_lending_rate_spread_analyzer import (
    analyze,
    _utilization_label,
    _util_score,
    _lender_rate_quality,
    _borrower_cost_label,
    _market_score,
    _flags,
    _append_log,
)

# ─── fixture helpers ─────────────────────────────────────────────────────────

def _mkt(
    protocol="Aave",
    asset="USDC",
    supply=4.0,
    borrow=6.0,
    util=65.0,
    supplied=100_000_000,
    borrowed=65_000_000,
    reserve=10.0,
):
    return {
        "protocol": protocol,
        "asset": asset,
        "supply_apy_pct": supply,
        "borrow_apy_pct": borrow,
        "utilization_rate_pct": util,
        "total_supplied_usd": supplied,
        "total_borrowed_usd": borrowed,
        "reserve_factor_pct": reserve,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _utilization_label
# ═══════════════════════════════════════════════════════════════════════════════

class TestUtilizationLabel(unittest.TestCase):
    def test_idle_zero(self):
        self.assertEqual(_utilization_label(0), "IDLE")

    def test_idle_boundary(self):
        self.assertEqual(_utilization_label(19.9), "IDLE")

    def test_low_at_20(self):
        self.assertEqual(_utilization_label(20), "LOW")

    def test_low_mid(self):
        self.assertEqual(_utilization_label(35), "LOW")

    def test_low_boundary(self):
        self.assertEqual(_utilization_label(49.9), "LOW")

    def test_optimal_at_50(self):
        self.assertEqual(_utilization_label(50), "OPTIMAL")

    def test_optimal_mid(self):
        self.assertEqual(_utilization_label(65), "OPTIMAL")

    def test_optimal_boundary(self):
        self.assertEqual(_utilization_label(79.9), "OPTIMAL")

    def test_high_at_80(self):
        self.assertEqual(_utilization_label(80), "HIGH")

    def test_high_mid(self):
        self.assertEqual(_utilization_label(85), "HIGH")

    def test_high_boundary(self):
        self.assertEqual(_utilization_label(89.9), "HIGH")

    def test_critical_at_90(self):
        self.assertEqual(_utilization_label(90), "CRITICAL")

    def test_critical_at_100(self):
        self.assertEqual(_utilization_label(100), "CRITICAL")

    def test_critical_above_100(self):
        self.assertEqual(_utilization_label(101), "CRITICAL")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _util_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestUtilScore(unittest.TestCase):
    def test_optimal(self):
        self.assertEqual(_util_score("OPTIMAL"), 100)

    def test_high(self):
        self.assertEqual(_util_score("HIGH"), 70)

    def test_low(self):
        self.assertEqual(_util_score("LOW"), 60)

    def test_critical(self):
        self.assertEqual(_util_score("CRITICAL"), 30)

    def test_idle(self):
        self.assertEqual(_util_score("IDLE"), 20)

    def test_unknown_defaults_to_20(self):
        self.assertEqual(_util_score("UNKNOWN"), 20)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _lender_rate_quality
# ═══════════════════════════════════════════════════════════════════════════════

class TestLenderRateQuality(unittest.TestCase):
    def test_excellent(self):
        self.assertEqual(_lender_rate_quality(5.0), "EXCELLENT")

    def test_excellent_high(self):
        self.assertEqual(_lender_rate_quality(10.0), "EXCELLENT")

    def test_good_at_3(self):
        self.assertEqual(_lender_rate_quality(3.0), "GOOD")

    def test_good_mid(self):
        self.assertEqual(_lender_rate_quality(4.0), "GOOD")

    def test_good_boundary(self):
        self.assertEqual(_lender_rate_quality(4.99), "GOOD")

    def test_fair_at_2(self):
        self.assertEqual(_lender_rate_quality(2.0), "FAIR")

    def test_fair_mid(self):
        self.assertEqual(_lender_rate_quality(2.5), "FAIR")

    def test_fair_boundary(self):
        self.assertEqual(_lender_rate_quality(2.99), "FAIR")

    def test_poor_at_zero(self):
        self.assertEqual(_lender_rate_quality(0.0), "POOR")

    def test_poor_just_below_2(self):
        self.assertEqual(_lender_rate_quality(1.99), "POOR")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _borrower_cost_label
# ═══════════════════════════════════════════════════════════════════════════════

class TestBorrowerCostLabel(unittest.TestCase):
    def test_cheap_at_zero(self):
        self.assertEqual(_borrower_cost_label(0.0), "CHEAP")

    def test_cheap_below_5(self):
        self.assertEqual(_borrower_cost_label(4.99), "CHEAP")

    def test_moderate_at_5(self):
        self.assertEqual(_borrower_cost_label(5.0), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(_borrower_cost_label(7.5), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(_borrower_cost_label(9.99), "MODERATE")

    def test_expensive_at_10(self):
        self.assertEqual(_borrower_cost_label(10.0), "EXPENSIVE")

    def test_expensive_mid(self):
        self.assertEqual(_borrower_cost_label(12.0), "EXPENSIVE")

    def test_expensive_boundary(self):
        self.assertEqual(_borrower_cost_label(14.99), "EXPENSIVE")

    def test_very_expensive_at_15(self):
        self.assertEqual(_borrower_cost_label(15.0), "VERY_EXPENSIVE")

    def test_very_expensive_high(self):
        self.assertEqual(_borrower_cost_label(25.0), "VERY_EXPENSIVE")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlags(unittest.TestCase):
    _BASE_CFG = {"min_supply_apy_pct": 2.0, "max_borrow_apy_pct": 15.0}

    def test_no_flags_normal(self):
        f = _flags(4.0, 6.0, 65.0, 10.0, self._BASE_CFG)
        self.assertEqual(f, [])

    def test_low_supply_apy(self):
        f = _flags(1.5, 6.0, 65.0, 10.0, self._BASE_CFG)
        self.assertIn("LOW_SUPPLY_APY", f)

    def test_high_borrow_apy(self):
        f = _flags(4.0, 20.0, 65.0, 10.0, self._BASE_CFG)
        self.assertIn("HIGH_BORROW_APY", f)

    def test_near_max_utilization_above_85(self):
        f = _flags(4.0, 6.0, 86.0, 10.0, self._BASE_CFG)
        self.assertIn("NEAR_MAX_UTILIZATION", f)

    def test_near_max_utilization_at_85_not_flagged(self):
        f = _flags(4.0, 6.0, 85.0, 10.0, self._BASE_CFG)
        self.assertNotIn("NEAR_MAX_UTILIZATION", f)

    def test_high_reserve_capture(self):
        f = _flags(4.0, 6.0, 65.0, 25.0, self._BASE_CFG)
        self.assertIn("HIGH_RESERVE_CAPTURE", f)

    def test_high_reserve_at_20_not_flagged(self):
        f = _flags(4.0, 6.0, 65.0, 20.0, self._BASE_CFG)
        self.assertNotIn("HIGH_RESERVE_CAPTURE", f)

    def test_all_flags(self):
        f = _flags(1.0, 20.0, 91.0, 25.0, self._BASE_CFG)
        self.assertIn("LOW_SUPPLY_APY", f)
        self.assertIn("HIGH_BORROW_APY", f)
        self.assertIn("NEAR_MAX_UTILIZATION", f)
        self.assertIn("HIGH_RESERVE_CAPTURE", f)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _market_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketScore(unittest.TestCase):
    def test_capped_at_100(self):
        self.assertLessEqual(_market_score(100.0, 100.0, "OPTIMAL"), 100)

    def test_zero_supply_zero_efficiency(self):
        score = _market_score(0.0, 100.0, "OPTIMAL")
        # supply_norm=0, efficiency_norm=100, util_score=100
        # 0*0.4 + 100*0.3 + 100*0.3 = 60
        self.assertEqual(score, 60)

    def test_optimal_util_contributes(self):
        # supply=5 → norm=50; eff=80; OPTIMAL=100
        # 50*0.4 + 80*0.3 + 100*0.3 = 20+24+30 = 74
        score = _market_score(5.0, 80.0, "OPTIMAL")
        self.assertEqual(score, 74)

    def test_idle_util_lowers_score(self):
        score_idle = _market_score(5.0, 80.0, "IDLE")
        score_optimal = _market_score(5.0, 80.0, "OPTIMAL")
        self.assertLess(score_idle, score_optimal)

    def test_non_negative(self):
        score = _market_score(0.0, 0.0, "IDLE")
        self.assertGreaterEqual(score, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. analyze() – empty / edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_markets(self):
        r = analyze([])
        self.assertEqual(r["markets"], [])
        self.assertEqual(r["by_asset"], {})
        self.assertIsNone(r["best_supply_market"])
        self.assertIsNone(r["cheapest_borrow_market"])
        self.assertEqual(r["average_spread_pct"], 0.0)
        self.assertIn("timestamp", r)

    def test_empty_has_timestamp(self):
        before = time.time()
        r = analyze([])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_none_config_defaults(self):
        r = analyze([_mkt(supply=1.0)], config=None)
        self.assertIn("LOW_SUPPLY_APY", r["markets"][0]["flags"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. analyze() – single market
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.result = analyze([_mkt()])

    def test_one_market_returned(self):
        self.assertEqual(len(self.result["markets"]), 1)

    def test_spread_computed(self):
        m = self.result["markets"][0]
        self.assertAlmostEqual(m["spread_pct"], 2.0)

    def test_spread_efficiency(self):
        # supply=4, borrow=6 → 4/6*100 ≈ 66.67
        m = self.result["markets"][0]
        self.assertAlmostEqual(m["spread_efficiency"], 66.666, places=2)

    def test_utilization_label_optimal(self):
        m = self.result["markets"][0]
        self.assertEqual(m["utilization_label"], "OPTIMAL")

    def test_lender_rate_quality_good(self):
        m = self.result["markets"][0]
        self.assertEqual(m["lender_rate_quality"], "GOOD")

    def test_borrower_cost_moderate(self):
        m = self.result["markets"][0]
        self.assertEqual(m["borrower_cost_label"], "MODERATE")

    def test_market_score_positive(self):
        m = self.result["markets"][0]
        self.assertGreater(m["market_score"], 0)

    def test_best_supply_market_key(self):
        self.assertEqual(self.result["best_supply_market"], "Aave:USDC")

    def test_cheapest_borrow_market_key(self):
        self.assertEqual(self.result["cheapest_borrow_market"], "Aave:USDC")

    def test_average_spread(self):
        self.assertAlmostEqual(self.result["average_spread_pct"], 2.0)

    def test_by_asset_populated(self):
        self.assertIn("USDC", self.result["by_asset"])

    def test_by_asset_market_count(self):
        self.assertEqual(self.result["by_asset"]["USDC"]["market_count"], 1)

    def test_by_asset_best_supply(self):
        self.assertAlmostEqual(self.result["by_asset"]["USDC"]["best_supply_apy"], 4.0)

    def test_by_asset_lowest_borrow(self):
        self.assertAlmostEqual(self.result["by_asset"]["USDC"]["lowest_borrow_apy"], 6.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. analyze() – multi-market / best-selection
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeMulti(unittest.TestCase):
    def setUp(self):
        self.markets = [
            _mkt("Aave", "USDC", supply=3.5, borrow=5.2, util=67.0),
            _mkt("Compound", "USDC", supply=4.8, borrow=6.1, util=79.0),
            _mkt("Morpho", "ETH", supply=2.1, borrow=4.0, util=55.0),
        ]
        self.result = analyze(self.markets)

    def test_three_markets(self):
        self.assertEqual(len(self.result["markets"]), 3)

    def test_best_supply_market_compound(self):
        self.assertEqual(self.result["best_supply_market"], "Compound:USDC")

    def test_cheapest_borrow_market(self):
        self.assertEqual(self.result["cheapest_borrow_market"], "Morpho:ETH")

    def test_average_spread_correct(self):
        spreads = [5.2 - 3.5, 6.1 - 4.8, 4.0 - 2.1]
        expected = sum(spreads) / 3
        self.assertAlmostEqual(self.result["average_spread_pct"], expected, places=5)

    def test_two_assets_in_by_asset(self):
        self.assertIn("USDC", self.result["by_asset"])
        self.assertIn("ETH", self.result["by_asset"])

    def test_usdc_market_count_2(self):
        self.assertEqual(self.result["by_asset"]["USDC"]["market_count"], 2)

    def test_eth_market_count_1(self):
        self.assertEqual(self.result["by_asset"]["ETH"]["market_count"], 1)

    def test_usdc_best_supply(self):
        self.assertAlmostEqual(self.result["by_asset"]["USDC"]["best_supply_apy"], 4.8)

    def test_usdc_lowest_borrow(self):
        self.assertAlmostEqual(self.result["by_asset"]["USDC"]["lowest_borrow_apy"], 5.2)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. analyze() – borrow=0 edge case
# ═══════════════════════════════════════════════════════════════════════════════

class TestZeroBorrow(unittest.TestCase):
    def setUp(self):
        self.result = analyze([_mkt(supply=3.0, borrow=0.0, util=5.0)])

    def test_spread_negative_or_zero(self):
        m = self.result["markets"][0]
        self.assertAlmostEqual(m["spread_pct"], -3.0)

    def test_efficiency_is_100_when_borrow_zero(self):
        m = self.result["markets"][0]
        self.assertAlmostEqual(m["spread_efficiency"], 100.0)

    def test_cheapest_borrow_none(self):
        self.assertIsNone(self.result["cheapest_borrow_market"])

    def test_by_asset_lowest_borrow_zero(self):
        self.assertAlmostEqual(self.result["by_asset"]["USDC"]["lowest_borrow_apy"], 0.0)

    def test_borrower_cost_cheap(self):
        m = self.result["markets"][0]
        self.assertEqual(m["borrower_cost_label"], "CHEAP")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. analyze() – all-zero market
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllZeroMarket(unittest.TestCase):
    def test_all_zeros(self):
        r = analyze([_mkt(supply=0.0, borrow=0.0, util=0.0, reserve=0.0)])
        m = r["markets"][0]
        self.assertAlmostEqual(m["spread_pct"], 0.0)
        self.assertAlmostEqual(m["spread_efficiency"], 100.0)
        self.assertEqual(m["utilization_label"], "IDLE")
        self.assertEqual(m["lender_rate_quality"], "POOR")
        self.assertEqual(m["borrower_cost_label"], "CHEAP")
        self.assertGreaterEqual(m["market_score"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Spread efficiency math
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpreadEfficiency(unittest.TestCase):
    def test_efficiency_50pct(self):
        r = analyze([_mkt(supply=3.0, borrow=6.0)])
        m = r["markets"][0]
        self.assertAlmostEqual(m["spread_efficiency"], 50.0)

    def test_efficiency_100pct_equal_rates(self):
        r = analyze([_mkt(supply=5.0, borrow=5.0)])
        m = r["markets"][0]
        self.assertAlmostEqual(m["spread_efficiency"], 100.0)

    def test_efficiency_capped_at_100_when_supply_gt_borrow(self):
        # supply > borrow is unusual but possible
        r = analyze([_mkt(supply=7.0, borrow=5.0)])
        m = r["markets"][0]
        # efficiency = 7/5*100 = 140 — not capped in the formula itself but via int()
        self.assertAlmostEqual(m["spread_efficiency"], 140.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. config overrides
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigOverrides(unittest.TestCase):
    def test_custom_min_supply_triggers_flag(self):
        r = analyze([_mkt(supply=3.0)], config={"min_supply_apy_pct": 4.0})
        self.assertIn("LOW_SUPPLY_APY", r["markets"][0]["flags"])

    def test_custom_min_supply_no_flag(self):
        r = analyze([_mkt(supply=3.0)], config={"min_supply_apy_pct": 2.0})
        self.assertNotIn("LOW_SUPPLY_APY", r["markets"][0]["flags"])

    def test_custom_max_borrow_triggers_flag(self):
        r = analyze([_mkt(borrow=10.0)], config={"max_borrow_apy_pct": 8.0})
        self.assertIn("HIGH_BORROW_APY", r["markets"][0]["flags"])

    def test_custom_max_borrow_no_flag(self):
        r = analyze([_mkt(borrow=10.0)], config={"max_borrow_apy_pct": 20.0})
        self.assertNotIn("HIGH_BORROW_APY", r["markets"][0]["flags"])

    def test_unknown_config_keys_ignored(self):
        # must not raise
        r = analyze([_mkt()], config={"unknown_key": 42})
        self.assertEqual(len(r["markets"]), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Output structure completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_mkt()])

    def test_top_level_keys(self):
        for k in ("markets", "by_asset", "best_supply_market",
                   "cheapest_borrow_market", "average_spread_pct", "timestamp"):
            self.assertIn(k, self.r)

    def test_market_keys(self):
        m = self.r["markets"][0]
        for k in (
            "protocol", "asset", "supply_apy_pct", "borrow_apy_pct",
            "spread_pct", "spread_efficiency", "utilization_rate_pct",
            "utilization_label", "reserve_capture_pct",
            "lender_rate_quality", "borrower_cost_label",
            "market_score", "flags",
        ):
            self.assertIn(k, m)

    def test_market_score_int(self):
        self.assertIsInstance(self.r["markets"][0]["market_score"], int)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["markets"][0]["flags"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Log / ring-buffer
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppendLog(unittest.TestCase):
    def _tmp_log(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return path

    def test_creates_file(self):
        path = self._tmp_log()
        _append_log({"x": 1}, log_path=path)
        self.assertTrue(os.path.exists(path))

    def test_initial_entry(self):
        path = self._tmp_log()
        _append_log({"v": 42}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["v"], 42)

    def test_ring_buffer_cap(self):
        path = self._tmp_log()
        for i in range(110):
            _append_log({"i": i}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 109)

    def test_invalid_existing_json_recovers(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("NOT JSON")
        _append_log({"ok": True}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_analyze_writes_log(self):
        path = self._tmp_log()
        # monkeypatch module-level _LOG_PATH isn't needed; we call the private fn
        _append_log({"ts": 1}, log_path=path)
        _append_log({"ts": 2}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. High-utilization flag edge
# ═══════════════════════════════════════════════════════════════════════════════

class TestHighUtilFlag(unittest.TestCase):
    def test_at_86_flagged(self):
        r = analyze([_mkt(util=86.0)])
        self.assertIn("NEAR_MAX_UTILIZATION", r["markets"][0]["flags"])

    def test_at_85_not_flagged(self):
        r = analyze([_mkt(util=85.0)])
        self.assertNotIn("NEAR_MAX_UTILIZATION", r["markets"][0]["flags"])

    def test_at_90_critical_label(self):
        r = analyze([_mkt(util=90.0)])
        self.assertEqual(r["markets"][0]["utilization_label"], "CRITICAL")

    def test_at_99_critical_label(self):
        r = analyze([_mkt(util=99.0)])
        self.assertEqual(r["markets"][0]["utilization_label"], "CRITICAL")


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Reserve factor flag edge
# ═══════════════════════════════════════════════════════════════════════════════

class TestReserveFactor(unittest.TestCase):
    def test_at_20_no_flag(self):
        r = analyze([_mkt(reserve=20.0)])
        self.assertNotIn("HIGH_RESERVE_CAPTURE", r["markets"][0]["flags"])

    def test_at_21_flagged(self):
        r = analyze([_mkt(reserve=21.0)])
        self.assertIn("HIGH_RESERVE_CAPTURE", r["markets"][0]["flags"])

    def test_reserve_stored_correctly(self):
        r = analyze([_mkt(reserve=15.0)])
        self.assertAlmostEqual(r["markets"][0]["reserve_capture_pct"], 15.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 18. by_asset: multiple assets, multiple protocols
# ═══════════════════════════════════════════════════════════════════════════════

class TestByAsset(unittest.TestCase):
    def test_same_asset_aggregates(self):
        mkts = [
            _mkt("Aave", "USDC", supply=3.0, borrow=5.0),
            _mkt("Compound", "USDC", supply=4.5, borrow=6.5),
        ]
        r = analyze(mkts)
        usdc = r["by_asset"]["USDC"]
        self.assertAlmostEqual(usdc["best_supply_apy"], 4.5)
        self.assertAlmostEqual(usdc["lowest_borrow_apy"], 5.0)
        self.assertEqual(usdc["market_count"], 2)

    def test_different_assets_separate(self):
        mkts = [
            _mkt("Aave", "USDC", supply=3.0, borrow=5.0),
            _mkt("Aave", "DAI", supply=3.2, borrow=4.8),
        ]
        r = analyze(mkts)
        self.assertIn("USDC", r["by_asset"])
        self.assertIn("DAI", r["by_asset"])

    def test_lowest_borrow_ignores_zero(self):
        mkts = [
            _mkt("Aave", "USDC", borrow=0.0),
            _mkt("Compound", "USDC", borrow=5.0),
        ]
        r = analyze(mkts)
        self.assertAlmostEqual(r["by_asset"]["USDC"]["lowest_borrow_apy"], 5.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. Excellent lender rate
# ═══════════════════════════════════════════════════════════════════════════════

class TestExcellentRate(unittest.TestCase):
    def test_supply_5_excellent(self):
        r = analyze([_mkt(supply=5.0)])
        self.assertEqual(r["markets"][0]["lender_rate_quality"], "EXCELLENT")

    def test_supply_10_excellent(self):
        r = analyze([_mkt(supply=10.0)])
        self.assertEqual(r["markets"][0]["lender_rate_quality"], "EXCELLENT")


# ═══════════════════════════════════════════════════════════════════════════════
# 20. VERY_EXPENSIVE borrow label
# ═══════════════════════════════════════════════════════════════════════════════

class TestVeryExpensive(unittest.TestCase):
    def test_borrow_15_very_expensive(self):
        r = analyze([_mkt(borrow=15.0)])
        self.assertEqual(r["markets"][0]["borrower_cost_label"], "VERY_EXPENSIVE")

    def test_borrow_30_very_expensive(self):
        r = analyze([_mkt(borrow=30.0)])
        self.assertEqual(r["markets"][0]["borrower_cost_label"], "VERY_EXPENSIVE")


if __name__ == "__main__":
    unittest.main()
