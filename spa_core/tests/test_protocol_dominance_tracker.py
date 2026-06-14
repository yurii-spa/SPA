"""
Tests for MP-799 ProtocolDominanceTracker
Run: python3 -m unittest spa_core/tests/test_protocol_dominance_tracker.py
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# Ensure repo root is on path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_dominance_tracker import (
    analyze,
    save_snapshot,
    load_log,
    _atomic_write,
    _read_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lending_pair(a_tvl, b_tvl, a_7d=None, b_7d=None):
    """Two lending protocols."""
    pa = {"name": "Aave", "category": "lending", "tvl_usd": a_tvl}
    pb = {"name": "Compound", "category": "lending", "tvl_usd": b_tvl}
    if a_7d is not None:
        pa["tvl_7d_ago_usd"] = a_7d
    if b_7d is not None:
        pb["tvl_7d_ago_usd"] = b_7d
    return [pa, pb]


# ---------------------------------------------------------------------------
# 1. Basic structure
# ---------------------------------------------------------------------------

class TestAnalyzeReturnStructure(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            {"name": "Aave", "category": "lending", "tvl_usd": 6_000_000},
            {"name": "Compound", "category": "lending", "tvl_usd": 4_000_000},
        ]

    def test_returns_dict(self):
        self.assertIsInstance(analyze(self.protocols), dict)

    def test_top_level_keys(self):
        r = analyze(self.protocols)
        for k in ("total_tvl_usd", "by_category", "concentration_alerts",
                   "diversification_opportunities", "timestamp"):
            self.assertIn(k, r)

    def test_timestamp_is_float(self):
        r = analyze(self.protocols)
        self.assertIsInstance(r["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(self.protocols)
        self.assertGreaterEqual(r["timestamp"], before)

    def test_total_tvl_correct(self):
        r = analyze(self.protocols)
        self.assertAlmostEqual(r["total_tvl_usd"], 10_000_000, places=0)

    def test_by_category_has_lending(self):
        r = analyze(self.protocols)
        self.assertIn("lending", r["by_category"])

    def test_category_keys(self):
        r = analyze(self.protocols)
        cat = r["by_category"]["lending"]
        for k in ("total_tvl_usd", "protocols", "category_hhi",
                   "concentration_level", "leader", "leader_share_pct"):
            self.assertIn(k, cat)

    def test_protocols_list_type(self):
        r = analyze(self.protocols)
        self.assertIsInstance(r["by_category"]["lending"]["protocols"], list)

    def test_protocol_row_keys(self):
        r = analyze(self.protocols)
        row = r["by_category"]["lending"]["protocols"][0]
        for k in ("name", "tvl_usd", "market_share_pct",
                   "tvl_change_7d_pct", "share_change_7d_ppt",
                   "dominance_status"):
            self.assertIn(k, row)

    def test_concentration_alerts_is_list(self):
        r = analyze(self.protocols)
        self.assertIsInstance(r["concentration_alerts"], list)

    def test_diversification_opportunities_is_list(self):
        r = analyze(self.protocols)
        self.assertIsInstance(r["diversification_opportunities"], list)


# ---------------------------------------------------------------------------
# 2. Market share calculations
# ---------------------------------------------------------------------------

class TestMarketShare(unittest.TestCase):

    def test_shares_sum_to_100(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        total = sum(r["market_share_pct"] for r in rows)
        self.assertAlmostEqual(total, 100.0, places=4)

    def test_dominant_has_correct_share(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        # sorted desc so first is Aave with 60%
        self.assertAlmostEqual(rows[0]["market_share_pct"], 60.0, places=4)

    def test_minority_has_correct_share(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        self.assertAlmostEqual(rows[1]["market_share_pct"], 40.0, places=4)

    def test_single_protocol_100_pct(self):
        r = analyze([{"name": "Aave", "category": "lending", "tvl_usd": 1_000_000}])
        rows = r["by_category"]["lending"]["protocols"]
        self.assertAlmostEqual(rows[0]["market_share_pct"], 100.0, places=4)

    def test_zero_tvl_category(self):
        r = analyze([{"name": "Aave", "category": "lending", "tvl_usd": 0}])
        rows = r["by_category"]["lending"]["protocols"]
        self.assertAlmostEqual(rows[0]["market_share_pct"], 0.0, places=4)

    def test_sorted_by_tvl_desc(self):
        protocols = _lending_pair(4_000_000, 6_000_000)
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        self.assertEqual(rows[0]["name"], "Compound")  # higher TVL first

    def test_three_protocols_shares_sum_to_100(self):
        protocols = [
            {"name": "A", "category": "dex", "tvl_usd": 1_000_000},
            {"name": "B", "category": "dex", "tvl_usd": 2_000_000},
            {"name": "C", "category": "dex", "tvl_usd": 3_000_000},
        ]
        rows = analyze(protocols)["by_category"]["dex"]["protocols"]
        self.assertAlmostEqual(sum(r["market_share_pct"] for r in rows), 100.0, places=3)

    def test_equal_share_two_protocols(self):
        protocols = _lending_pair(5_000_000, 5_000_000)
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        for r in rows:
            self.assertAlmostEqual(r["market_share_pct"], 50.0, places=4)


# ---------------------------------------------------------------------------
# 3. 7-day change fields
# ---------------------------------------------------------------------------

class TestSevenDayChange(unittest.TestCase):

    def test_no_7d_data_is_none(self):
        r = analyze(_lending_pair(6_000_000, 4_000_000))
        for row in r["by_category"]["lending"]["protocols"]:
            self.assertIsNone(row["tvl_change_7d_pct"])
            self.assertIsNone(row["share_change_7d_ppt"])

    def test_tvl_change_positive(self):
        r = analyze(_lending_pair(6_000_000, 4_000_000, a_7d=5_000_000))
        rows = {r["name"]: r for r in r["by_category"]["lending"]["protocols"]}
        self.assertAlmostEqual(rows["Aave"]["tvl_change_7d_pct"], 20.0, places=4)

    def test_tvl_change_negative(self):
        r = analyze(_lending_pair(4_000_000, 6_000_000, a_7d=5_000_000))
        rows = {rv["name"]: rv for rv in r["by_category"]["lending"]["protocols"]}
        self.assertAlmostEqual(rows["Aave"]["tvl_change_7d_pct"], -20.0, places=4)

    def test_share_change_present_when_7d_given(self):
        r = analyze(_lending_pair(6_000_000, 4_000_000, a_7d=5_000_000, b_7d=5_000_000))
        rows = {rv["name"]: rv for rv in r["by_category"]["lending"]["protocols"]}
        self.assertIsNotNone(rows["Aave"]["share_change_7d_ppt"])

    def test_tvl_7d_zero_gives_zero_change(self):
        r = analyze(_lending_pair(6_000_000, 4_000_000, a_7d=0))
        rows = {rv["name"]: rv for rv in r["by_category"]["lending"]["protocols"]}
        self.assertAlmostEqual(rows["Aave"]["tvl_change_7d_pct"], 0.0, places=4)


# ---------------------------------------------------------------------------
# 4. Dominance status
# ---------------------------------------------------------------------------

class TestDominanceStatus(unittest.TestCase):

    def _status(self, share_pct, total=100_000):
        tvl = share_pct / 100.0 * total
        rest = total - tvl
        if rest <= 0:
            protocols = [{"name": "A", "category": "lending", "tvl_usd": tvl}]
        else:
            protocols = [
                {"name": "A", "category": "lending", "tvl_usd": tvl},
                {"name": "B", "category": "lending", "tvl_usd": rest},
            ]
        rows = analyze(protocols)["by_category"]["lending"]["protocols"]
        return {r["name"]: r["dominance_status"] for r in rows}

    def test_dominant_at_50_pct(self):
        self.assertEqual(self._status(50)["A"], "DOMINANT")

    def test_dominant_at_51_pct(self):
        self.assertEqual(self._status(51)["A"], "DOMINANT")

    def test_major_at_20_pct(self):
        self.assertEqual(self._status(20)["A"], "MAJOR")

    def test_major_at_49_pct(self):
        self.assertEqual(self._status(49)["A"], "MAJOR")

    def test_minor_at_5_pct(self):
        self.assertEqual(self._status(5)["A"], "MINOR")

    def test_minor_at_19_pct(self):
        self.assertEqual(self._status(19)["A"], "MINOR")

    def test_niche_at_4_pct(self):
        self.assertEqual(self._status(4)["A"], "NICHE")

    def test_niche_at_zero(self):
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 0},
            {"name": "B", "category": "lending", "tvl_usd": 100_000},
        ]
        rows = {r["name"]: r for r in analyze(protocols)["by_category"]["lending"]["protocols"]}
        self.assertEqual(rows["A"]["dominance_status"], "NICHE")

    def test_custom_dominance_threshold(self):
        protocols = _lending_pair(60_000, 40_000)
        r = analyze(protocols, config={"dominance_threshold": 65.0})
        rows = {rv["name"]: rv for rv in r["by_category"]["lending"]["protocols"]}
        # 60% < 65% threshold → not DOMINANT
        self.assertNotEqual(rows["Aave"]["dominance_status"], "DOMINANT")

    def test_custom_dominance_threshold_triggers(self):
        protocols = _lending_pair(70_000, 30_000)
        r = analyze(protocols, config={"dominance_threshold": 65.0})
        rows = {rv["name"]: rv for rv in r["by_category"]["lending"]["protocols"]}
        self.assertEqual(rows["Aave"]["dominance_status"], "DOMINANT")


# ---------------------------------------------------------------------------
# 5. HHI calculation
# ---------------------------------------------------------------------------

class TestHHI(unittest.TestCase):

    def test_single_protocol_hhi_is_1(self):
        r = analyze([{"name": "A", "category": "lending", "tvl_usd": 1_000_000}])
        self.assertAlmostEqual(r["by_category"]["lending"]["category_hhi"], 1.0, places=4)

    def test_two_equal_protocols_hhi(self):
        # HHI = 0.5^2 + 0.5^2 = 0.5
        r = analyze(_lending_pair(500_000, 500_000))
        self.assertAlmostEqual(r["by_category"]["lending"]["category_hhi"], 0.5, places=4)

    def test_hhi_is_non_negative(self):
        r = analyze(_lending_pair(6_000_000, 4_000_000))
        self.assertGreaterEqual(r["by_category"]["lending"]["category_hhi"], 0.0)

    def test_hhi_at_most_1(self):
        r = analyze(_lending_pair(9_000_000, 1_000_000))
        self.assertLessEqual(r["by_category"]["lending"]["category_hhi"], 1.0 + 1e-9)

    def test_four_equal_protocols_hhi(self):
        # 4 * (0.25)^2 = 0.25
        protocols = [{"name": str(i), "category": "dex", "tvl_usd": 250_000} for i in range(4)]
        r = analyze(protocols)
        self.assertAlmostEqual(r["by_category"]["dex"]["category_hhi"], 0.25, places=4)

    def test_hhi_60_40_split(self):
        # 0.6^2 + 0.4^2 = 0.36 + 0.16 = 0.52
        r = analyze(_lending_pair(60_000, 40_000))
        self.assertAlmostEqual(r["by_category"]["lending"]["category_hhi"], 0.52, places=4)


# ---------------------------------------------------------------------------
# 6. Concentration level
# ---------------------------------------------------------------------------

class TestConcentrationLevel(unittest.TestCase):

    def test_monopolistic_single_protocol(self):
        r = analyze([{"name": "A", "category": "lending", "tvl_usd": 1_000_000}])
        self.assertEqual(r["by_category"]["lending"]["concentration_level"], "MONOPOLISTIC")

    def test_competitive_many_equal(self):
        # 10 equal → HHI = 10 * 0.01 = 0.10 ≤ 0.20
        protocols = [{"name": str(i), "category": "yield", "tvl_usd": 100_000} for i in range(10)]
        r = analyze(protocols)
        self.assertEqual(r["by_category"]["yield"]["concentration_level"], "COMPETITIVE")

    def test_moderate_four_equal(self):
        # HHI = 0.25 → MODERATE (> 0.2)
        protocols = [{"name": str(i), "category": "dex", "tvl_usd": 250_000} for i in range(4)]
        r = analyze(protocols)
        self.assertEqual(r["by_category"]["dex"]["concentration_level"], "MODERATE")

    def test_concentrated_two_protocols(self):
        # 60/40 → HHI=0.52 → CONCENTRATED (>0.4, ≤0.7)
        r = analyze(_lending_pair(60_000, 40_000))
        self.assertEqual(r["by_category"]["lending"]["concentration_level"], "CONCENTRATED")

    def test_monopolistic_hhi_above_07(self):
        # 90/10 → HHI = 0.81 + 0.01 = 0.82
        r = analyze(_lending_pair(90_000, 10_000))
        self.assertEqual(r["by_category"]["lending"]["concentration_level"], "MONOPOLISTIC")

    def test_six_equal_competitive(self):
        # 6 equal → HHI = 6 * (1/6)^2 ≈ 0.167 → COMPETITIVE (≤ 0.20)
        protocols = [{"name": str(i), "category": "stablecoin", "tvl_usd": 200_000} for i in range(6)]
        r = analyze(protocols)
        self.assertEqual(r["by_category"]["stablecoin"]["concentration_level"], "COMPETITIVE")


# ---------------------------------------------------------------------------
# 7. Leader fields
# ---------------------------------------------------------------------------

class TestLeader(unittest.TestCase):

    def test_leader_is_highest_tvl(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        cat = analyze(protocols)["by_category"]["lending"]
        self.assertEqual(cat["leader"], "Aave")

    def test_leader_share_correct(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        cat = analyze(protocols)["by_category"]["lending"]
        self.assertAlmostEqual(cat["leader_share_pct"], 60.0, places=4)

    def test_single_protocol_is_leader(self):
        r = analyze([{"name": "A", "category": "dex", "tvl_usd": 1_000_000}])
        self.assertEqual(r["by_category"]["dex"]["leader"], "A")

    def test_leader_share_100_when_single(self):
        r = analyze([{"name": "A", "category": "dex", "tvl_usd": 1_000_000}])
        self.assertAlmostEqual(r["by_category"]["dex"]["leader_share_pct"], 100.0, places=4)


# ---------------------------------------------------------------------------
# 8. Total TVL
# ---------------------------------------------------------------------------

class TestTotalTVL(unittest.TestCase):

    def test_total_tvl_sums_all_categories(self):
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 5_000_000},
            {"name": "B", "category": "dex", "tvl_usd": 3_000_000},
        ]
        r = analyze(protocols)
        self.assertAlmostEqual(r["total_tvl_usd"], 8_000_000, places=0)

    def test_total_tvl_zero_for_empty(self):
        r = analyze([])
        self.assertAlmostEqual(r["total_tvl_usd"], 0.0, places=0)

    def test_total_tvl_negative_tvl_clamped(self):
        protocols = [{"name": "A", "category": "lending", "tvl_usd": -1_000_000}]
        r = analyze(protocols)
        self.assertGreaterEqual(r["total_tvl_usd"], 0.0)

    def test_category_tvl_correct(self):
        protocols = _lending_pair(6_000_000, 4_000_000)
        cat = analyze(protocols)["by_category"]["lending"]
        self.assertAlmostEqual(cat["total_tvl_usd"], 10_000_000, places=0)


# ---------------------------------------------------------------------------
# 9. Multi-category support
# ---------------------------------------------------------------------------

class TestMultiCategory(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            {"name": "Aave", "category": "lending", "tvl_usd": 10_000_000},
            {"name": "Uniswap", "category": "dex", "tvl_usd": 5_000_000},
            {"name": "Yearn", "category": "yield", "tvl_usd": 2_000_000},
            {"name": "USDC", "category": "stablecoin", "tvl_usd": 8_000_000},
        ]

    def test_four_categories_present(self):
        r = analyze(self.protocols)
        for cat in ("lending", "dex", "yield", "stablecoin"):
            self.assertIn(cat, r["by_category"])

    def test_categories_independent(self):
        r = analyze(self.protocols)
        # each category's protocols sum to its own total
        for cat, data in r["by_category"].items():
            expected = sum(p["tvl_usd"] for p in self.protocols if p["category"] == cat)
            self.assertAlmostEqual(data["total_tvl_usd"], expected, places=0)

    def test_single_protocol_per_category_is_monopolistic(self):
        r = analyze(self.protocols)
        for cat in ("lending", "dex", "yield", "stablecoin"):
            self.assertEqual(r["by_category"][cat]["concentration_level"], "MONOPOLISTIC")

    def test_unknown_category_mapped_to_other(self):
        protocols = [{"name": "X", "category": "exotic", "tvl_usd": 100_000}]
        r = analyze(protocols)
        self.assertIn("other", r["by_category"])


# ---------------------------------------------------------------------------
# 10. Concentration alerts
# ---------------------------------------------------------------------------

class TestConcentrationAlerts(unittest.TestCase):

    def test_dominant_generates_alert(self):
        protocols = _lending_pair(60_000, 40_000)
        r = analyze(protocols)
        alerts = r["concentration_alerts"]
        self.assertTrue(any("Aave" in a and "lending" in a for a in alerts))

    def test_no_alert_when_no_dominant(self):
        # 40/60 → neither reaches 50%
        protocols = _lending_pair(40_000, 60_000)
        r = analyze(protocols)
        # Compound is 60%, so it IS dominant by default threshold 50%
        alerts = r["concentration_alerts"]
        self.assertTrue(any("Compound" in a for a in alerts))

    def test_monopolistic_category_alert(self):
        r = analyze([{"name": "A", "category": "lending", "tvl_usd": 1_000_000}])
        alerts = r["concentration_alerts"]
        self.assertTrue(any("MONOPOLISTIC" in a for a in alerts))

    def test_alert_contains_share_percentage(self):
        protocols = _lending_pair(60_000, 40_000)
        r = analyze(protocols)
        alerts = r["concentration_alerts"]
        dominant_alert = [a for a in alerts if "Aave" in a]
        self.assertTrue(len(dominant_alert) > 0)
        self.assertIn("60.0%", dominant_alert[0])

    def test_no_alert_for_niche_protocol(self):
        protocols = [
            {"name": "Big", "category": "lending", "tvl_usd": 95_000},
            {"name": "Small", "category": "lending", "tvl_usd": 5_000},
        ]
        r = analyze(protocols)
        alerts = r["concentration_alerts"]
        self.assertFalse(any("Small" in a and "dominates" in a for a in alerts))

    def test_multiple_categories_generate_multiple_alerts(self):
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 1_000_000},
            {"name": "B", "category": "dex", "tvl_usd": 1_000_000},
        ]
        r = analyze(protocols)
        # Both single-protocol categories → both MONOPOLISTIC → alerts
        self.assertGreaterEqual(len(r["concentration_alerts"]), 2)


# ---------------------------------------------------------------------------
# 11. Diversification opportunities
# ---------------------------------------------------------------------------

class TestDiversificationOpportunities(unittest.TestCase):

    def test_competitive_category_in_opportunities(self):
        # 10 equal protocols in dex → COMPETITIVE
        protocols = [{"name": str(i), "category": "dex", "tvl_usd": 100_000} for i in range(10)]
        r = analyze(protocols)
        self.assertIn("dex", r["diversification_opportunities"])

    def test_monopolistic_not_in_opportunities(self):
        r = analyze([{"name": "A", "category": "lending", "tvl_usd": 1_000_000}])
        self.assertNotIn("lending", r["diversification_opportunities"])

    def test_empty_opportunities_when_all_concentrated(self):
        protocols = _lending_pair(90_000, 10_000)
        r = analyze(protocols)
        self.assertNotIn("lending", r["diversification_opportunities"])


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_protocols_list(self):
        r = analyze([])
        self.assertEqual(r["total_tvl_usd"], 0.0)
        self.assertEqual(r["by_category"], {})
        self.assertEqual(r["concentration_alerts"], [])
        self.assertEqual(r["diversification_opportunities"], [])

    def test_none_config_uses_defaults(self):
        r = analyze(_lending_pair(60_000, 40_000), config=None)
        self.assertIn("concentration_level", r["by_category"]["lending"])

    def test_empty_config_uses_defaults(self):
        r = analyze(_lending_pair(60_000, 40_000), config={})
        self.assertIn("concentration_level", r["by_category"]["lending"])

    def test_all_zero_tvl(self):
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 0},
            {"name": "B", "category": "lending", "tvl_usd": 0},
        ]
        r = analyze(protocols)
        for row in r["by_category"]["lending"]["protocols"]:
            self.assertAlmostEqual(row["market_share_pct"], 0.0, places=4)

    def test_large_numbers(self):
        protocols = [{"name": "A", "category": "lending", "tvl_usd": 1e15}]
        r = analyze(protocols)
        self.assertGreater(r["total_tvl_usd"], 0)

    def test_float_tvl_values(self):
        protocols = _lending_pair(3_141_592.65, 2_718_281.83)
        r = analyze(protocols)
        self.assertGreater(r["total_tvl_usd"], 0)

    def test_missing_name_defaults_to_empty_string(self):
        protocols = [{"category": "lending", "tvl_usd": 1_000_000}]
        r = analyze(protocols)
        rows = r["by_category"]["lending"]["protocols"]
        self.assertEqual(rows[0]["name"], "")

    def test_missing_category_defaults_to_other(self):
        protocols = [{"name": "X", "tvl_usd": 1_000_000}]
        r = analyze(protocols)
        self.assertIn("other", r["by_category"])

    def test_missing_tvl_defaults_to_zero(self):
        protocols = [{"name": "A", "category": "lending"}]
        r = analyze(protocols)
        self.assertAlmostEqual(r["total_tvl_usd"], 0.0, places=0)


# ---------------------------------------------------------------------------
# 13. Persistence – save_snapshot and load_log
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.write(b"[]")
        self.tmp.close()
        self.log_path = self.tmp.name

    def tearDown(self):
        os.unlink(self.log_path)

    def test_save_creates_entry(self):
        result = analyze(_lending_pair(6_000_000, 4_000_000))
        save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 1)

    def test_load_returns_list(self):
        log = load_log(self.log_path)
        self.assertIsInstance(log, list)

    def test_multiple_saves_accumulate(self):
        result = analyze(_lending_pair(6_000_000, 4_000_000))
        for _ in range(3):
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 3)

    def test_ring_buffer_caps_at_100(self):
        result = analyze(_lending_pair(6_000_000, 4_000_000))
        for _ in range(105):
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 100)

    def test_ring_buffer_keeps_last_100(self):
        for i in range(105):
            result = analyze(_lending_pair(float(i) * 1_000 + 1, 1.0))
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 100)

    def test_nonexistent_log_returns_empty(self):
        log = load_log("/tmp/_nonexistent_spa_test_xyz_9999.json")
        self.assertEqual(log, [])

    def test_save_snapshot_content_correct(self):
        result = analyze(_lending_pair(6_000_000, 4_000_000))
        save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertIn("by_category", log[0])
        self.assertIn("total_tvl_usd", log[0])

    def test_atomic_write_creates_valid_json(self):
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(self.log_path, data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_load_from_corrupted_file_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not valid json {{")
        log = load_log(self.log_path)
        self.assertEqual(log, [])

    def test_load_from_non_list_json_returns_empty(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "value"}, f)
        log = load_log(self.log_path)
        self.assertEqual(log, [])


# ---------------------------------------------------------------------------
# 14. Custom config
# ---------------------------------------------------------------------------

class TestCustomConfig(unittest.TestCase):

    def test_lower_dominance_threshold_marks_more_as_dominant(self):
        # 35% share → MAJOR at default 50%, DOMINANT at threshold 30%
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 35_000},
            {"name": "B", "category": "lending", "tvl_usd": 65_000},
        ]
        r_default = analyze(protocols)
        r_custom = analyze(protocols, config={"dominance_threshold": 30.0})
        rows_d = {x["name"]: x for x in r_default["by_category"]["lending"]["protocols"]}
        rows_c = {x["name"]: x for x in r_custom["by_category"]["lending"]["protocols"]}
        # 35% < 50% → not DOMINANT with default
        self.assertNotEqual(rows_d["A"]["dominance_status"], "DOMINANT")
        # 35% > 30% → DOMINANT with custom threshold
        self.assertEqual(rows_c["A"]["dominance_status"], "DOMINANT")

    def test_monopoly_threshold_in_config(self):
        # Config is accepted without error
        r = analyze(_lending_pair(80_000, 20_000), config={"monopoly_threshold": 75.0})
        self.assertIn("concentration_level", r["by_category"]["lending"])

    def test_config_dominance_affects_alerts(self):
        # 40% is not DOMINANT at 50%, but IS DOMINANT at 35%
        protocols = _lending_pair(40_000, 60_000)
        r = analyze(protocols, config={"dominance_threshold": 35.0})
        alerts = r["concentration_alerts"]
        self.assertTrue(any("Aave" in a for a in alerts))


# ---------------------------------------------------------------------------
# 15. Category TVL independence
# ---------------------------------------------------------------------------

class TestCategoryIndependence(unittest.TestCase):

    def test_cross_category_shares_do_not_pollute(self):
        protocols = [
            {"name": "Aave", "category": "lending", "tvl_usd": 8_000_000},
            {"name": "BigDex", "category": "dex", "tvl_usd": 2_000_000},
        ]
        r = analyze(protocols)
        lending_rows = {x["name"]: x for x in r["by_category"]["lending"]["protocols"]}
        self.assertAlmostEqual(lending_rows["Aave"]["market_share_pct"], 100.0, places=4)

    def test_total_tvl_includes_all_categories(self):
        protocols = [
            {"name": "A", "category": "lending", "tvl_usd": 4_000_000},
            {"name": "B", "category": "dex", "tvl_usd": 6_000_000},
        ]
        r = analyze(protocols)
        self.assertAlmostEqual(r["total_tvl_usd"], 10_000_000, places=0)


if __name__ == "__main__":
    unittest.main()
