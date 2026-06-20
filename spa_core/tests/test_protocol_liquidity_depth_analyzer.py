"""
Tests for MP-785: ProtocolLiquidityDepthAnalyzer
≥65 unit tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_liquidity_depth_analyzer import (
    LOG_CAP,
    DEPTH_ADEQUATE,
    DEPTH_DEEP,
    DEPTH_INSUFFICIENT,
    DEPTH_THIN,
    ProtocolLiquidityDepthAnalyzer,
    _atomic_append,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MID = 1.0
POS = 1_000_000.0  # 1M USD position


def _make_book(
    bid_count: int = 10,
    bid_size_each: float = 500_000.0,
    ask_count: int = 10,
    ask_size_each: float = 500_000.0,
    mid: float = MID,
    pos: float = POS,
    protocol: str = "Aave",
) -> dict:
    bids = [(round(mid - i * 0.0005, 6), bid_size_each) for i in range(bid_count)]
    asks = [(round(mid + i * 0.0005, 6), ask_size_each) for i in range(1, ask_count + 1)]
    return {
        "protocol": protocol,
        "bids": bids,
        "asks": asks,
        "mid_price": mid,
        "position_size_usd": pos,
    }


def _thin_book(pos: float = POS) -> dict:
    bids = [(0.999, 100_000.0)]
    asks = [(1.001, 100_000.0)]
    return {"protocol": "Thin", "bids": bids, "asks": asks, "mid_price": 1.0, "position_size_usd": pos}


def _analyzer(**kw) -> ProtocolLiquidityDepthAnalyzer:
    return ProtocolLiquidityDepthAnalyzer(**kw)


# ---------------------------------------------------------------------------
# Tests: basic structure
# ---------------------------------------------------------------------------

class TestAnalyzeBasicStructure(unittest.TestCase):
    # T001
    def test_analyze_returns_dict(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIsInstance(r, dict)

    # T002
    def test_result_has_timestamp(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("timestamp", r)

    # T003
    def test_result_has_protocol(self):
        a = _analyzer()
        r = a.analyze(_make_book(protocol="Compound"))
        self.assertEqual(r["protocol"], "Compound")

    # T004
    def test_result_has_bid_depth_usd(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("bid_depth_usd", r)

    # T005
    def test_result_has_ask_depth_usd(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("ask_depth_usd", r)

    # T006
    def test_result_has_spread_bps(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("spread_bps", r)

    # T007
    def test_result_has_market_impact_bps(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("market_impact_bps", r)

    # T008
    def test_result_has_can_exit_in_1pct(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("can_exit_in_1pct", r)

    # T009
    def test_result_has_depth_rating(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("depth_rating", r)

    # T010
    def test_result_has_mid_price(self):
        a = _analyzer()
        r = a.analyze(_make_book(mid=2.5))
        self.assertAlmostEqual(r["mid_price"], 2.5, places=4)

    # T011
    def test_result_has_position_size_usd(self):
        a = _analyzer()
        r = a.analyze(_make_book(pos=500_000))
        self.assertAlmostEqual(r["position_size_usd"], 500_000.0, places=0)

    # T012
    def test_result_has_ratio_bid_to_position(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIn("ratio_bid_to_position", r)


# ---------------------------------------------------------------------------
# Tests: bid/ask depth within 1%
# ---------------------------------------------------------------------------

class TestDepthCalculations(unittest.TestCase):
    # T013
    def test_bid_depth_sums_within_1pct(self):
        a = _analyzer()
        # 2 bids within 1% of mid=1.0: prices 0.999, 0.9995 → both ≥ 0.99
        bids = [(0.999, 200_000.0), (0.9995, 300_000.0), (0.98, 999_000.0)]
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["bid_depth_usd"], 500_000.0, places=0)

    # T014
    def test_bid_outside_band_excluded(self):
        a = _analyzer()
        bids = [(0.98, 999_999.0)]  # 2% below mid → excluded
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["bid_depth_usd"], 0.0, places=0)

    # T015
    def test_ask_depth_sums_within_1pct(self):
        a = _analyzer()
        asks = [(1.005, 400_000.0), (1.009, 100_000.0), (1.02, 999_000.0)]
        ob = {"protocol": "X", "bids": [], "asks": asks, "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["ask_depth_usd"], 500_000.0, places=0)

    # T016
    def test_empty_bids_gives_zero_depth(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [], "asks": [(1.001, 100_000)], "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertEqual(r["bid_depth_usd"], 0.0)

    # T017
    def test_empty_asks_gives_zero_ask_depth(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [(0.999, 100_000)], "asks": [], "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertEqual(r["ask_depth_usd"], 0.0)

    # T018
    def test_zero_mid_price_no_crash(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [(0, 100_000)], "asks": [(0, 100_000)], "mid_price": 0.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertIsInstance(r, dict)

    # T019
    def test_bid_depth_non_negative(self):
        a = _analyzer()
        r = a.analyze(_thin_book())
        self.assertGreaterEqual(r["bid_depth_usd"], 0.0)


# ---------------------------------------------------------------------------
# Tests: spread
# ---------------------------------------------------------------------------

class TestSpread(unittest.TestCase):
    # T020
    def test_spread_bps_formula(self):
        a = _analyzer()
        bids = [(0.999, 100_000)]
        asks = [(1.001, 100_000)]
        ob = {"protocol": "X", "bids": bids, "asks": asks, "mid_price": 1.0, "position_size_usd": 10_000}
        r = a.analyze(ob)
        # spread = (1.001 - 0.999)/1.0 * 10000 = 20 bps
        self.assertAlmostEqual(r["spread_bps"], 20.0, places=2)

    # T021
    def test_spread_zero_when_no_bids_asks(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [], "asks": [], "mid_price": 1.0, "position_size_usd": 10_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["spread_bps"], 0.0, places=4)

    # T022
    def test_spread_non_negative(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertGreaterEqual(r["spread_bps"], 0.0)


# ---------------------------------------------------------------------------
# Tests: market impact
# ---------------------------------------------------------------------------

class TestMarketImpact(unittest.TestCase):
    # T023
    def test_market_impact_zero_on_empty_bids(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [], "asks": [], "mid_price": 1.0, "position_size_usd": 10_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["market_impact_bps"], 0.0, places=4)

    # T024
    def test_market_impact_high_when_depth_insufficient(self):
        a = _analyzer()
        # Position much larger than depth → high impact
        bids = [(0.999, 1_000.0)]
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 10_000_000}
        r = a.analyze(ob)
        self.assertGreater(r["market_impact_bps"], 0.0)

    # T025
    def test_market_impact_low_when_depth_ample(self):
        a = _analyzer()
        # All fills at very close prices
        bids = [(1.0 - i * 0.00001, 1_000_000.0) for i in range(10)]
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 100_000}
        r = a.analyze(ob)
        self.assertGreaterEqual(r["market_impact_bps"], 0.0)

    # T026
    def test_get_market_impact_before_analyze(self):
        a = _analyzer()
        self.assertAlmostEqual(a.get_market_impact(), 0.0, places=4)

    # T027
    def test_get_market_impact_after_analyze(self):
        a = _analyzer()
        a.analyze(_make_book())
        impact = a.get_market_impact()
        self.assertIsInstance(impact, float)
        self.assertGreaterEqual(impact, 0.0)

    # T028
    def test_market_impact_is_float(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIsInstance(r["market_impact_bps"], float)


# ---------------------------------------------------------------------------
# Tests: can_exit_in_1pct
# ---------------------------------------------------------------------------

class TestCanExitIn1Pct(unittest.TestCase):
    # T029
    def test_can_exit_true_when_depth_exceeds_position(self):
        a = _analyzer()
        bids = [(0.999, 2_000_000.0)]
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 500_000}
        r = a.analyze(ob)
        self.assertTrue(r["can_exit_in_1pct"])

    # T030
    def test_can_exit_false_when_depth_insufficient(self):
        a = _analyzer()
        bids = [(0.999, 10_000.0)]  # only 10k in band
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 500_000}
        r = a.analyze(ob)
        self.assertFalse(r["can_exit_in_1pct"])

    # T031
    def test_can_exit_true_when_zero_position(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [], "asks": [], "mid_price": 1.0, "position_size_usd": 0}
        r = a.analyze(ob)
        self.assertTrue(r["can_exit_in_1pct"])

    # T032
    def test_can_exit_is_bool(self):
        a = _analyzer()
        r = a.analyze(_make_book())
        self.assertIsInstance(r["can_exit_in_1pct"], bool)


# ---------------------------------------------------------------------------
# Tests: depth rating
# ---------------------------------------------------------------------------

class TestDepthRating(unittest.TestCase):
    # T033
    def test_rating_deep_10x(self):
        a = _analyzer()
        bids = [(0.999, 10_500_000.0)]  # 10.5x position
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": POS}
        r = a.analyze(ob)
        self.assertEqual(r["depth_rating"], DEPTH_DEEP)

    # T034
    def test_rating_adequate_5x(self):
        a = _analyzer()
        bids = [(0.999, 6_000_000.0)]  # 6x position
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": POS}
        r = a.analyze(ob)
        self.assertEqual(r["depth_rating"], DEPTH_ADEQUATE)

    # T035
    def test_rating_thin_2x(self):
        a = _analyzer()
        bids = [(0.999, 3_000_000.0)]  # 3x position
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": POS}
        r = a.analyze(ob)
        self.assertEqual(r["depth_rating"], DEPTH_THIN)

    # T036
    def test_rating_insufficient_below_2x(self):
        a = _analyzer()
        bids = [(0.999, 500_000.0)]  # 0.5x position
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": POS}
        r = a.analyze(ob)
        self.assertEqual(r["depth_rating"], DEPTH_INSUFFICIENT)

    # T037
    def test_rating_deep_zero_position(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [], "asks": [], "mid_price": 1.0, "position_size_usd": 0}
        r = a.analyze(ob)
        self.assertEqual(r["depth_rating"], DEPTH_DEEP)

    # T038
    def test_get_depth_rating_before_analyze(self):
        a = _analyzer()
        self.assertEqual(a.get_depth_rating(), DEPTH_INSUFFICIENT)

    # T039
    def test_get_depth_rating_after_analyze(self):
        a = _analyzer()
        a.analyze(_make_book())
        rating = a.get_depth_rating()
        self.assertIn(rating, [DEPTH_DEEP, DEPTH_ADEQUATE, DEPTH_THIN, DEPTH_INSUFFICIENT])

    # T040
    def test_rate_depth_boundaries(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        self.assertEqual(P._rate_depth(10_000_000, 1_000_000), DEPTH_DEEP)
        self.assertEqual(P._rate_depth(9_999_999, 1_000_000), DEPTH_ADEQUATE)
        self.assertEqual(P._rate_depth(5_000_000, 1_000_000), DEPTH_ADEQUATE)
        self.assertEqual(P._rate_depth(4_999_999, 1_000_000), DEPTH_THIN)
        self.assertEqual(P._rate_depth(2_000_000, 1_000_000), DEPTH_THIN)
        self.assertEqual(P._rate_depth(1_999_999, 1_000_000), DEPTH_INSUFFICIENT)
        self.assertEqual(P._rate_depth(0, 1_000_000), DEPTH_INSUFFICIENT)

    # T041
    def test_depth_constants_distinct(self):
        ratings = {DEPTH_DEEP, DEPTH_ADEQUATE, DEPTH_THIN, DEPTH_INSUFFICIENT}
        self.assertEqual(len(ratings), 4)

    # T042
    def test_depth_constants_are_strings(self):
        self.assertIsInstance(DEPTH_DEEP, str)
        self.assertIsInstance(DEPTH_ADEQUATE, str)
        self.assertIsInstance(DEPTH_THIN, str)
        self.assertIsInstance(DEPTH_INSUFFICIENT, str)


# ---------------------------------------------------------------------------
# Tests: ratio_bid_to_position
# ---------------------------------------------------------------------------

class TestRatio(unittest.TestCase):
    # T043
    def test_ratio_correct(self):
        a = _analyzer()
        bids = [(0.999, 5_000_000.0)]
        ob = {"protocol": "X", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 1_000_000}
        r = a.analyze(ob)
        self.assertAlmostEqual(r["ratio_bid_to_position"], 5.0, places=2)

    # T044
    def test_ratio_none_when_zero_position(self):
        a = _analyzer()
        ob = {"protocol": "X", "bids": [(0.999, 100_000)], "asks": [], "mid_price": 1.0, "position_size_usd": 0}
        r = a.analyze(ob)
        self.assertIsNone(r["ratio_bid_to_position"])


# ---------------------------------------------------------------------------
# Tests: persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # T045
    def test_save_before_analyze_raises(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        with self.assertRaises(SPAError):
            a.save()

    # T046
    def test_save_creates_file(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        a.analyze(_make_book())
        a.save()
        path = os.path.join(self.tmpdir, "liquidity_depth_log.json")
        self.assertTrue(os.path.exists(path))

    # T047
    def test_save_returns_string_path(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        a.analyze(_make_book())
        path = a.save()
        self.assertIsInstance(path, str)

    # T048
    def test_save_content_is_list(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        a.analyze(_make_book())
        a.save()
        path = os.path.join(self.tmpdir, "liquidity_depth_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    # T049
    def test_save_appends_multiple(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        a.analyze(_make_book(protocol="A"))
        a.save()
        a.analyze(_make_book(protocol="B"))
        a.save()
        path = os.path.join(self.tmpdir, "liquidity_depth_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    # T050
    def test_ring_buffer_caps_at_100(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir=self.tmpdir)
        for i in range(110):
            a.analyze(_make_book())
            a.save()
        path = os.path.join(self.tmpdir, "liquidity_depth_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    # T051
    def test_save_with_data_dir_arg(self):
        a = ProtocolLiquidityDepthAnalyzer()
        a.analyze(_make_book())
        path = a.save(data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(path))

    # T052
    def test_atomic_append_helper_creates_file(self):
        path = os.path.join(self.tmpdir, "test.json")
        _atomic_append(path, {"x": 42}, cap=10)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["x"], 42)

    # T053
    def test_atomic_append_caps(self):
        path = os.path.join(self.tmpdir, "test.json")
        for i in range(15):
            _atomic_append(path, {"i": i}, cap=5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    # T054
    def test_atomic_append_recovers_corrupt(self):
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("INVALID{{{{")
        _atomic_append(path, {"ok": True}, cap=10)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"ok": True}])

    # T055
    def test_log_cap_constant_is_100(self):
        self.assertEqual(LOG_CAP, 100)


# ---------------------------------------------------------------------------
# Tests: edge cases / misc
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    # T056
    def test_missing_protocol_defaults(self):
        a = _analyzer()
        r = a.analyze({"bids": [], "asks": [], "mid_price": 1.0, "position_size_usd": 100_000})
        self.assertEqual(r["protocol"], "unknown")

    # T057
    def test_large_position_no_crash(self):
        a = _analyzer()
        r = a.analyze(_make_book(pos=100_000_000))
        self.assertIsInstance(r, dict)

    # T058
    def test_many_bid_levels_aggregated(self):
        a = _analyzer()
        bids = [(round(0.9999 - i * 0.0000001, 8), 100.0) for i in range(1000)]
        ob = {"protocol": "Dense", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 1_000}
        r = a.analyze(ob)
        self.assertGreater(r["bid_depth_usd"], 0.0)

    # T059
    def test_analyze_updates_last_result(self):
        a = _analyzer()
        a.analyze(_make_book(protocol="A"))
        self.assertIsNotNone(a._last_result)
        a.analyze(_make_book(protocol="B"))
        self.assertEqual(a._last_result["protocol"], "B")

    # T060
    def test_data_dir_init(self):
        a = ProtocolLiquidityDepthAnalyzer(data_dir="/tmp/spa")
        self.assertEqual(a._data_dir, "/tmp/spa")

    # T061
    def test_analyze_is_idempotent(self):
        a = _analyzer()
        r1 = a.analyze(_make_book())
        r2 = a.analyze(_make_book())
        self.assertEqual(r1["bid_depth_usd"], r2["bid_depth_usd"])

    # T062
    def test_spread_bps_positive_when_bid_lt_ask(self):
        a = _analyzer()
        bids = [(0.998, 100_000)]
        asks = [(1.002, 100_000)]
        ob = {"protocol": "X", "bids": bids, "asks": asks, "mid_price": 1.0, "position_size_usd": 10_000}
        r = a.analyze(ob)
        self.assertGreater(r["spread_bps"], 0.0)

    # T063
    def test_all_rating_values_reachable(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        pos = 1_000_000
        self.assertEqual(P._rate_depth(0, pos), DEPTH_INSUFFICIENT)
        self.assertEqual(P._rate_depth(2_000_000, pos), DEPTH_THIN)
        self.assertEqual(P._rate_depth(5_000_000, pos), DEPTH_ADEQUATE)
        self.assertEqual(P._rate_depth(10_000_000, pos), DEPTH_DEEP)

    # T064
    def test_impact_500_bps_flag_when_underfilled(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        impact = P._calc_market_impact(
            [(0.999, 100.0)],  # tiny depth
            1_000_000_000,     # huge position
            1.0,
            "exit",
        )
        self.assertEqual(impact, 500.0)

    # T065
    def test_impact_zero_when_zero_mid_price(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        impact = P._calc_market_impact([(0.999, 1_000_000)], 100_000, 0.0, "exit")
        self.assertEqual(impact, 0.0)

    # T066
    def test_impact_zero_when_empty_bids(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        impact = P._calc_market_impact([], 100_000, 1.0, "exit")
        self.assertEqual(impact, 0.0)

    # T067
    def test_impact_zero_when_zero_position(self):
        from spa_core.analytics.protocol_liquidity_depth_analyzer import ProtocolLiquidityDepthAnalyzer as P
        impact = P._calc_market_impact([(0.999, 1_000_000)], 0, 1.0, "exit")
        self.assertEqual(impact, 0.0)

    # T068
    def test_full_deep_book_low_impact(self):
        a = _analyzer()
        # 20 bid levels at essentially mid
        bids = [(1.0 - i * 0.00001, 1_000_000.0) for i in range(20)]
        ob = {"protocol": "Deep", "bids": bids, "asks": [], "mid_price": 1.0, "position_size_usd": 500_000}
        r = a.analyze(ob)
        # Impact should be very small (< 5 bps)
        self.assertLess(r["market_impact_bps"], 5.0)


if __name__ == "__main__":
    unittest.main()
