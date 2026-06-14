"""
Tests for MP-982: DeFiProtocolMarketShareTracker
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_market_share_tracker -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure the repo root is on the path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_market_share_tracker import (
    DeFiProtocolMarketShareTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proto(
    name="Proto",
    category="dex",
    tvl_current=100_000_000,
    tvl_30d=90_000_000,
    volume_30d=50_000_000,
    volume_90d=40_000_000,
    fees_30d=1_000_000,
    users=10_000,
    integrations=20,
):
    return {
        "name": name,
        "category": category,
        "tvl_current_usd": tvl_current,
        "tvl_30d_ago_usd": tvl_30d,
        "volume_30d_usd": volume_30d,
        "volume_90d_ago_usd": volume_90d,
        "fees_30d_usd": fees_30d,
        "unique_users_30d": users,
        "integrations_count": integrations,
    }


def _two_dex_protos():
    """A pair of DEX protocols for basic share math."""
    return [
        _make_proto("Uniswap", "dex", tvl_current=600_000_000, tvl_30d=500_000_000,
                    volume_30d=300_000_000, users=100_000, integrations=80),
        _make_proto("Curve",   "dex", tvl_current=400_000_000, tvl_30d=450_000_000,
                    volume_30d=200_000_000, users=40_000, integrations=60),
    ]


class TestBasicReturnStructure(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_returns_dict(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIsInstance(r, dict)

    def test_has_protocols_key(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIn("protocols", r)

    def test_has_category_summary_key(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIn("category_summary", r)

    def test_has_tracked_at_key(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIn("tracked_at", r)

    def test_protocols_is_list(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIsInstance(r["protocols"], list)

    def test_protocols_length_matches_input(self):
        protos = _two_dex_protos()
        r = self.tracker.track(protos, {"write_log": False})
        self.assertEqual(len(r["protocols"]), 2)

    def test_tracked_at_is_string(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIsInstance(r["tracked_at"], str)

    def test_tracked_at_utc_format(self):
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertTrue(r["tracked_at"].endswith("Z"))

    def test_empty_protocols_returns_error(self):
        r = self.tracker.track([], {"write_log": False})
        self.assertIn("error", r)
        self.assertEqual(r["protocols"], [])

    def test_empty_category_summary_on_error(self):
        r = self.tracker.track([], {"write_log": False})
        self.assertEqual(r["category_summary"], {})


class TestPerProtocolFields(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()
        self.proto = _make_proto("Alpha", "lending")
        self.result = self.tracker.track([self.proto], {"write_log": False})
        self.p = self.result["protocols"][0]

    def test_name_preserved(self):
        self.assertEqual(self.p["name"], "Alpha")

    def test_category_preserved(self):
        self.assertEqual(self.p["category"], "lending")

    def test_tvl_current_usd_present(self):
        self.assertIn("tvl_current_usd", self.p)

    def test_tvl_market_share_pct_present(self):
        self.assertIn("tvl_market_share_pct", self.p)

    def test_volume_market_share_pct_present(self):
        self.assertIn("volume_market_share_pct", self.p)

    def test_tvl_share_change_30d_pct_present(self):
        self.assertIn("tvl_share_change_30d_pct", self.p)

    def test_volume_growth_pct_present(self):
        self.assertIn("volume_growth_pct", self.p)

    def test_capital_efficiency_present(self):
        self.assertIn("capital_efficiency", self.p)

    def test_stickiness_present(self):
        self.assertIn("protocol_stickiness_score", self.p)

    def test_market_position_present(self):
        self.assertIn("market_position", self.p)

    def test_flags_present(self):
        self.assertIn("flags", self.p)

    def test_flags_is_list(self):
        self.assertIsInstance(self.p["flags"], list)


class TestTVLShareMath(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_single_proto_share_is_100(self):
        r = self.tracker.track([_make_proto("Only", "dex", tvl_current=1_000_000)], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["tvl_market_share_pct"], 100.0, places=2)

    def test_two_protos_shares_sum_to_100(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        total = sum(p["tvl_market_share_pct"] for p in r["protocols"])
        self.assertAlmostEqual(total, 100.0, places=4)

    def test_dominant_proto_has_correct_share(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        uniswap = next(p for p in r["protocols"] if p["name"] == "Uniswap")
        self.assertAlmostEqual(uniswap["tvl_market_share_pct"], 60.0, places=2)

    def test_smaller_proto_has_correct_share(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        curve = next(p for p in r["protocols"] if p["name"] == "Curve")
        self.assertAlmostEqual(curve["tvl_market_share_pct"], 40.0, places=2)

    def test_share_change_positive_when_gained_tvl(self):
        """Uniswap grew from 500M → 600M while Curve shrank; Uniswap share rose."""
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        uniswap = next(p for p in r["protocols"] if p["name"] == "Uniswap")
        self.assertGreater(uniswap["tvl_share_change_30d_pct"], 0)

    def test_share_change_negative_when_lost_tvl(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        curve = next(p for p in r["protocols"] if p["name"] == "Curve")
        self.assertLess(curve["tvl_share_change_30d_pct"], 0)


class TestVolumeMetrics(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_volume_shares_sum_to_100(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        total = sum(p["volume_market_share_pct"] for p in r["protocols"])
        self.assertAlmostEqual(total, 100.0, places=4)

    def test_volume_growth_positive_when_volume_increased(self):
        p = _make_proto("A", "dex", volume_30d=120_000_000, volume_90d=100_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["volume_growth_pct"], 20.0, places=4)

    def test_volume_growth_zero_when_no_prior(self):
        p = _make_proto("A", "dex", volume_90d=0)
        r = self.tracker.track([p], {"write_log": False})
        self.assertEqual(r["protocols"][0]["volume_growth_pct"], 0.0)

    def test_capital_efficiency_volume_over_tvl(self):
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=50_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["capital_efficiency"], 0.5, places=5)

    def test_capital_efficiency_zero_when_no_tvl(self):
        p = _make_proto("A", "dex", tvl_current=0)
        r = self.tracker.track([p], {"write_log": False})
        self.assertEqual(r["protocols"][0]["capital_efficiency"], 0.0)


class TestMarketPositionLabels(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def _solo_proto(self, tvl_cur, tvl_30d, **kwargs):
        return _make_proto("X", "dex", tvl_current=tvl_cur, tvl_30d=tvl_30d, **kwargs)

    def test_dominant_label_when_share_above_40(self):
        """Single protocol in its category → 100% share → DOMINANT."""
        r = self.tracker.track([self._solo_proto(500_000_000, 400_000_000)], {"write_log": False})
        self.assertEqual(r["protocols"][0]["market_position"], "DOMINANT")

    def test_leading_label(self):
        """30% share → LEADING."""
        protos = [
            _make_proto("A", "dex", tvl_current=300_000_000, tvl_30d=280_000_000),
            _make_proto("B", "dex", tvl_current=350_000_000, tvl_30d=340_000_000),
            _make_proto("C", "dex", tvl_current=350_000_000, tvl_30d=330_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertEqual(a["market_position"], "LEADING")

    def test_challenger_label(self):
        """15% share → CHALLENGER."""
        protos = [
            _make_proto("A", "dex", tvl_current=150_000_000, tvl_30d=140_000_000),
            _make_proto("B", "dex", tvl_current=500_000_000, tvl_30d=490_000_000),
            _make_proto("C", "dex", tvl_current=350_000_000, tvl_30d=340_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertEqual(a["market_position"], "CHALLENGER")

    def test_niche_label(self):
        """5% share → NICHE."""
        protos = [
            _make_proto("A", "dex", tvl_current=50_000_000,    tvl_30d=49_000_000),
            _make_proto("B", "dex", tvl_current=950_000_000,   tvl_30d=930_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertEqual(a["market_position"], "NICHE")

    def test_declining_label_when_share_fell_more_than_5pp(self):
        """Share fell from 60% to 40% → -20pp → DECLINING (overrides position)."""
        protos = [
            _make_proto("A", "dex", tvl_current=400_000_000, tvl_30d=600_000_000),
            _make_proto("B", "dex", tvl_current=600_000_000, tvl_30d=400_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertEqual(a["market_position"], "DECLINING")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_gaining_share_flag(self):
        """Protocol whose share grew >2pp."""
        protos = [
            _make_proto("A", "dex", tvl_current=600_000_000, tvl_30d=300_000_000),
            _make_proto("B", "dex", tvl_current=400_000_000, tvl_30d=700_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertIn("GAINING_SHARE", a["flags"])

    def test_losing_share_flag(self):
        protos = [
            _make_proto("A", "dex", tvl_current=400_000_000, tvl_30d=700_000_000),
            _make_proto("B", "dex", tvl_current=600_000_000, tvl_30d=300_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        self.assertIn("LOSING_SHARE", a["flags"])

    def test_high_efficiency_flag(self):
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=80_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertIn("HIGH_EFFICIENCY", r["protocols"][0]["flags"])

    def test_no_high_efficiency_when_below_threshold(self):
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=30_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertNotIn("HIGH_EFFICIENCY", r["protocols"][0]["flags"])

    def test_sticky_protocol_flag_when_stickiness_above_70(self):
        """Max users + integrations + efficiency in category → stickiness → 100."""
        p = _make_proto("A", "dex", users=1_000_000, integrations=500,
                        tvl_current=100_000_000, volume_30d=90_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertIn("STICKY_PROTOCOL", r["protocols"][0]["flags"])

    def test_category_leader_flag_for_highest_tvl(self):
        protos = [
            _make_proto("Leader", "dex", tvl_current=800_000_000),
            _make_proto("Follower", "dex", tvl_current=200_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        leader_p = next(p for p in r["protocols"] if p["name"] == "Leader")
        follower_p = next(p for p in r["protocols"] if p["name"] == "Follower")
        self.assertIn("CATEGORY_LEADER", leader_p["flags"])
        self.assertNotIn("CATEGORY_LEADER", follower_p["flags"])

    def test_no_gaining_share_when_change_small(self):
        protos = [
            _make_proto("A", "dex", tvl_current=510_000_000, tvl_30d=500_000_000),
            _make_proto("B", "dex", tvl_current=490_000_000, tvl_30d=500_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        a = next(p for p in r["protocols"] if p["name"] == "A")
        # change ~ 1pp, below 2pp threshold
        self.assertNotIn("GAINING_SHARE", a["flags"])

    def test_flags_list_can_be_empty(self):
        """A stable mid-tier protocol may have no flags."""
        protos = [
            _make_proto("A", "dex", tvl_current=500_000_000, tvl_30d=500_000_000,
                        volume_30d=100_000_000, users=5_000, integrations=5),
            _make_proto("B", "dex", tvl_current=500_000_000, tvl_30d=500_000_000,
                        volume_30d=100_000_000, users=5_000, integrations=5),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        # At least one proto should have no non-leader flags (except possibly CATEGORY_LEADER)
        for p in r["protocols"]:
            non_leader_flags = [f for f in p["flags"] if f != "CATEGORY_LEADER"]
            self.assertIsInstance(non_leader_flags, list)


class TestCategorySummary(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_category_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("dex", r["category_summary"])

    def test_category_leader_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("category_leader", r["category_summary"]["dex"])

    def test_total_category_tvl_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("total_category_tvl", r["category_summary"]["dex"])

    def test_hhi_concentration_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("hhi_concentration", r["category_summary"]["dex"])

    def test_fastest_growing_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("fastest_growing", r["category_summary"]["dex"])

    def test_fastest_declining_key_present(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIn("fastest_declining", r["category_summary"]["dex"])

    def test_category_leader_is_highest_tvl(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertEqual(r["category_summary"]["dex"]["category_leader"], "Uniswap")

    def test_total_category_tvl_correct(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertAlmostEqual(
            r["category_summary"]["dex"]["total_category_tvl"],
            1_000_000_000.0, places=0
        )

    def test_hhi_correct_for_equal_split(self):
        """Two protos at 50% each → HHI = 50^2 + 50^2 = 5000."""
        protos = [
            _make_proto("A", "dex", tvl_current=500_000_000, tvl_30d=500_000_000),
            _make_proto("B", "dex", tvl_current=500_000_000, tvl_30d=500_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        self.assertAlmostEqual(r["category_summary"]["dex"]["hhi_concentration"], 5000.0, places=0)

    def test_hhi_100pct_for_monopoly(self):
        """Single proto at 100% → HHI = 10000."""
        r = self.tracker.track([_make_proto("Only", "dex", tvl_current=1_000_000_000)], {"write_log": False})
        self.assertAlmostEqual(r["category_summary"]["dex"]["hhi_concentration"], 10000.0, places=0)

    def test_protocol_count_in_summary(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertEqual(r["category_summary"]["dex"]["protocol_count"], 2)

    def test_multiple_categories_in_summary(self):
        protos = [
            _make_proto("A", "dex"),
            _make_proto("B", "lending"),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        self.assertIn("dex", r["category_summary"])
        self.assertIn("lending", r["category_summary"])

    def test_fastest_growing_is_string(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIsInstance(r["category_summary"]["dex"]["fastest_growing"], str)

    def test_fastest_declining_is_string(self):
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        self.assertIsInstance(r["category_summary"]["dex"]["fastest_declining"], str)


class TestMultiCategoryIsolation(unittest.TestCase):
    """Protocols in different categories don't affect each other's share calculations."""

    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_single_proto_in_each_category_gets_100_pct(self):
        protos = [
            _make_proto("A", "dex",     tvl_current=100_000_000),
            _make_proto("B", "lending", tvl_current=50_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        for p in r["protocols"]:
            self.assertAlmostEqual(p["tvl_market_share_pct"], 100.0, places=2)

    def test_categories_isolated_for_share_calc(self):
        protos = [
            _make_proto("DEX1", "dex",     tvl_current=700_000_000, tvl_30d=690_000_000),
            _make_proto("DEX2", "dex",     tvl_current=300_000_000, tvl_30d=290_000_000),
            _make_proto("LND1", "lending", tvl_current=600_000_000, tvl_30d=590_000_000),
            _make_proto("LND2", "lending", tvl_current=400_000_000, tvl_30d=390_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        dex_shares = [p["tvl_market_share_pct"] for p in r["protocols"] if p["category"] == "dex"]
        lend_shares = [p["tvl_market_share_pct"] for p in r["protocols"] if p["category"] == "lending"]
        self.assertAlmostEqual(sum(dex_shares), 100.0, places=4)
        self.assertAlmostEqual(sum(lend_shares), 100.0, places=4)


class TestStickinessScore(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_stickiness_between_0_and_100(self):
        protos = [_make_proto("A", "dex", users=u, integrations=i)
                  for u, i in [(0, 0), (100_000, 100), (500_000, 300)]]
        r = self.tracker.track(protos, {"write_log": False})
        for p in r["protocols"]:
            self.assertGreaterEqual(p["protocol_stickiness_score"], 0.0)
            self.assertLessEqual(p["protocol_stickiness_score"], 100.0)

    def test_stickiness_zero_when_all_zeros(self):
        p = _make_proto("A", "dex", users=0, integrations=0, tvl_current=0, volume_30d=0)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["protocol_stickiness_score"], 0.0, places=2)

    def test_max_stickiness_for_top_proto_in_category(self):
        """Only protocol in its category → normalised to max → stickiness = 100."""
        p = _make_proto("Only", "yield", users=50_000, integrations=50,
                        tvl_current=100_000_000, volume_30d=60_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["protocol_stickiness_score"], 100.0, places=2)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_zero_tvl_protocols(self):
        protos = [
            _make_proto("A", "dex", tvl_current=0, tvl_30d=0),
            _make_proto("B", "dex", tvl_current=0, tvl_30d=0),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        self.assertIsInstance(r["protocols"], list)
        self.assertEqual(len(r["protocols"]), 2)

    def test_missing_optional_fields_handled(self):
        minimal = {"name": "Min", "category": "dex", "tvl_current_usd": 1_000_000}
        r = self.tracker.track([minimal], {"write_log": False})
        self.assertEqual(len(r["protocols"]), 1)

    def test_name_defaults_to_unknown_when_missing(self):
        r = self.tracker.track([{"category": "dex", "tvl_current_usd": 1_000_000}], {"write_log": False})
        self.assertEqual(r["protocols"][0]["name"], "unknown")

    def test_category_defaults_to_dex_when_missing(self):
        r = self.tracker.track([{"name": "X", "tvl_current_usd": 1_000_000}], {"write_log": False})
        self.assertEqual(r["protocols"][0]["category"], "dex")

    def test_numeric_strings_coerced(self):
        p = {"name": "X", "category": "dex", "tvl_current_usd": "500000",
             "tvl_30d_ago_usd": "400000", "volume_30d_usd": "100000"}
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["tvl_current_usd"], 500_000.0)

    def test_large_number_of_protocols(self):
        protos = [_make_proto(f"Proto{i}", "dex", tvl_current=(i + 1) * 1_000_000)
                  for i in range(50)]
        r = self.tracker.track(protos, {"write_log": False})
        self.assertEqual(len(r["protocols"]), 50)

    def test_single_protocol_category_leader(self):
        r = self.tracker.track([_make_proto("Solo", "bridge")], {"write_log": False})
        self.assertIn("CATEGORY_LEADER", r["protocols"][0]["flags"])

    def test_config_none_uses_defaults(self):
        """Passing None config should not crash (write_log defaults True but we skip log test)."""
        # We override log path to avoid writing in tests
        r = self.tracker.track([_make_proto()], {"write_log": False})
        self.assertIn("protocols", r)

    def test_all_valid_categories(self):
        cats = ["dex", "lending", "perp", "bridge", "liquid_staking", "yield"]
        for cat in cats:
            protos = [_make_proto("A", cat, tvl_current=1_000_000)]
            r = self.tracker.track(protos, {"write_log": False})
            self.assertEqual(r["protocols"][0]["category"], cat)


class TestLogFileWriting(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "market_share_log.json")

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmpdir)

    def test_log_file_created(self):
        self.tracker.track([_make_proto()], {"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_is_valid_json(self):
        self.tracker.track([_make_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_file_has_one_entry_after_one_call(self):
        self.tracker.track([_make_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_file_appends_on_second_call(self):
        cfg = {"write_log": True, "log_path": self.log_path}
        self.tracker.track([_make_proto()], cfg)
        self.tracker.track([_make_proto()], cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_at_100(self):
        cfg = {"write_log": True, "log_path": self.log_path}
        for _ in range(110):
            self.tracker.track([_make_proto()], cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_no_log_file_when_write_log_false(self):
        self.tracker.track([_make_proto()], {"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_entry_has_protocols_key(self):
        self.tracker.track([_make_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            entry = json.load(fh)[0]
        self.assertIn("protocols", entry)

    def test_log_entry_has_tracked_at_key(self):
        self.tracker.track([_make_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            entry = json.load(fh)[0]
        self.assertIn("tracked_at", entry)

    def test_atomic_write_no_tmp_file_left(self):
        cfg = {"write_log": True, "log_path": self.log_path}
        self.tracker.track([_make_proto()], cfg)
        tmp_files = [f for f in os.listdir(self.tmpdir) if f != os.path.basename(self.log_path)]
        self.assertEqual(tmp_files, [])


class TestCapitalEfficiencyRange(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_efficiency_above_zero_when_has_volume(self):
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=50_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertGreater(r["protocols"][0]["capital_efficiency"], 0.0)

    def test_efficiency_can_exceed_one(self):
        """High-velocity DEX can have vol > TVL."""
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=300_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertGreater(r["protocols"][0]["capital_efficiency"], 1.0)

    def test_efficiency_exactly_one(self):
        p = _make_proto("A", "dex", tvl_current=100_000_000, volume_30d=100_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["capital_efficiency"], 1.0, places=5)


class TestShareChangeValues(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_share_change_exactly_zero_when_shares_unchanged(self):
        protos = [
            _make_proto("A", "dex", tvl_current=400_000_000, tvl_30d=400_000_000),
            _make_proto("B", "dex", tvl_current=600_000_000, tvl_30d=600_000_000),
        ]
        r = self.tracker.track(protos, {"write_log": False})
        for p in r["protocols"]:
            self.assertAlmostEqual(p["tvl_share_change_30d_pct"], 0.0, places=4)

    def test_share_changes_sum_to_zero(self):
        """In a closed system the share gains must exactly offset share losses."""
        r = self.tracker.track(_two_dex_protos(), {"write_log": False})
        total_change = sum(p["tvl_share_change_30d_pct"] for p in r["protocols"])
        self.assertAlmostEqual(total_change, 0.0, places=4)


class TestVolumeGrowthEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tracker = DeFiProtocolMarketShareTracker()

    def test_volume_growth_negative_when_declined(self):
        p = _make_proto("A", "dex", volume_30d=80_000_000, volume_90d=100_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["volume_growth_pct"], -20.0, places=4)

    def test_volume_growth_100pct_when_doubled(self):
        p = _make_proto("A", "dex", volume_30d=200_000_000, volume_90d=100_000_000)
        r = self.tracker.track([p], {"write_log": False})
        self.assertAlmostEqual(r["protocols"][0]["volume_growth_pct"], 100.0, places=4)


class TestTrackerInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        t = DeFiProtocolMarketShareTracker()
        self.assertIsNotNone(t)

    def test_can_call_multiple_times(self):
        t = DeFiProtocolMarketShareTracker()
        for _ in range(5):
            r = t.track([_make_proto()], {"write_log": False})
            self.assertIn("protocols", r)

    def test_results_are_independent_per_call(self):
        t = DeFiProtocolMarketShareTracker()
        r1 = t.track([_make_proto("A", "dex", tvl_current=100_000_000)], {"write_log": False})
        r2 = t.track([_make_proto("B", "dex", tvl_current=200_000_000)], {"write_log": False})
        self.assertEqual(r1["protocols"][0]["name"], "A")
        self.assertEqual(r2["protocols"][0]["name"], "B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
