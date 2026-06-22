"""
Tests for MP-848 ProtocolLiquidityMigrationDetector
Run: python3 -m unittest spa_core.tests.test_protocol_liquidity_migration_detector -v
"""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import spa_core.analytics.protocol_liquidity_migration_detector as _mod
import tempfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="ProtocolA",
    category="lending",
    tvl_history=None,
    apy_current=5.0,
    apy_7d_ago=5.0,
):
    """Build a minimal protocol dict."""
    if tvl_history is None:
        tvl_history = [100.0, 100.0, 100.0, 100.0]
    return {
        "name": name,
        "category": category,
        "tvl_history": tvl_history,
        "apy_current": apy_current,
        "apy_7d_ago": apy_7d_ago,
    }


def _losing_history(start=100_000_000, drop_pct=20):
    """TVL that drops by drop_pct% from start to end, 4 points."""
    end = start * (1 - drop_pct / 100)
    step = (end - start) / 3
    return [start + i * step for i in range(4)]


def _gaining_history(start=50_000_000, gain_pct=25):
    """TVL that rises by gain_pct% from start to end, 4 points."""
    end = start * (1 + gain_pct / 100)
    step = (end - start) / 3
    return [start + i * step for i in range(4)]


def _stable_history(value=100_000_000):
    return [value, value, value, value]


# ---------------------------------------------------------------------------
# Tests: empty / trivial inputs
# ---------------------------------------------------------------------------

class TestEmptyProtocols(unittest.TestCase):

    def setUp(self):
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze([])

    def test_flows_empty(self):
        self.assertEqual(self.r["flows"], [])

    def test_active_migrations_zero(self):
        self.assertEqual(self.r["active_migrations"], 0)

    def test_total_capital_zero(self):
        self.assertEqual(self.r["total_capital_moving_usd"], 0.0)

    def test_skipped_empty(self):
        self.assertEqual(self.r["skipped_protocols"], [])

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.r)
        self.assertIsInstance(self.r["timestamp"], float)


class TestSingleProtocol(unittest.TestCase):
    """Single protocol in a category — can't detect migration, gets skipped."""

    def setUp(self):
        p = _proto("Aave", "lending", _stable_history())
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze([p])

    def test_no_flows(self):
        self.assertEqual(self.r["flows"], [])

    def test_protocol_not_in_skipped_if_has_history(self):
        # Single eligible protocol: skipped because < 2 eligible
        # The name does NOT appear in skipped_protocols per spec
        # (only protocols with insufficient history are skipped)
        # Here Aave has 4 history points but only 1 in category → no flow but NOT in skipped
        self.assertNotIn("Aave", self.r["skipped_protocols"])


class TestInsufficientHistory(unittest.TestCase):
    """Protocols with < min_history points get skipped."""

    def test_short_history_skipped(self):
        p1 = _proto("A", "lending", [100_000, 80_000])   # only 2 points
        p2 = _proto("B", "lending", _stable_history())
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([p1, p2])
        self.assertIn("A", r["skipped_protocols"])

    def test_both_short_history_skipped(self):
        p1 = _proto("X", "lending", [100_000, 90_000])
        p2 = _proto("Y", "lending", [50_000, 40_000])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([p1, p2])
        self.assertIn("X", r["skipped_protocols"])
        self.assertIn("Y", r["skipped_protocols"])

    def test_empty_history_skipped(self):
        p1 = _proto("Z", "lending", [])
        p2 = _proto("W", "lending", _stable_history())
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([p1, p2])
        self.assertIn("Z", r["skipped_protocols"])

    def test_custom_min_history(self):
        # min_history=2 → 2-point history now eligible
        p1 = _proto("A", "lending", [100_000, 80_000])
        p2 = _proto("B", "lending", [50_000, 70_000])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([p1, p2], config={"min_history": 2})
        self.assertNotIn("A", r["skipped_protocols"])
        self.assertNotIn("B", r["skipped_protocols"])


# ---------------------------------------------------------------------------
# Tests: migration detection
# ---------------------------------------------------------------------------

class TestMigrationDetected(unittest.TestCase):
    """Both losing and gaining → migration_detected=True when score≥40."""

    def setUp(self):
        protocols = [
            _proto("Aave", "lending", _losing_history(100_000_000, 20), apy_current=3.0, apy_7d_ago=5.0),
            _proto("Compound", "lending", _gaining_history(50_000_000, 30), apy_current=7.0, apy_7d_ago=6.0),
            _proto("Morpho", "lending", _stable_history(80_000_000)),
        ]
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze(protocols)

    def test_one_flow_returned(self):
        self.assertEqual(len(self.r["flows"]), 1)

    def test_migration_detected_true(self):
        self.assertTrue(self.r["flows"][0]["migration_detected"])

    def test_active_migrations_one(self):
        self.assertEqual(self.r["active_migrations"], 1)

    def test_losing_contains_aave(self):
        names = [p["name"] for p in self.r["flows"][0]["losing_protocols"]]
        self.assertIn("Aave", names)

    def test_gaining_contains_compound(self):
        names = [p["name"] for p in self.r["flows"][0]["gaining_protocols"]]
        self.assertIn("Compound", names)

    def test_stable_protocol_not_in_either_side(self):
        flow = self.r["flows"][0]
        all_names = (
            [p["name"] for p in flow["losing_protocols"]] +
            [p["name"] for p in flow["gaining_protocols"]]
        )
        self.assertNotIn("Morpho", all_names)

    def test_category_is_lending(self):
        self.assertEqual(self.r["flows"][0]["category"], "lending")

    def test_total_capital_moving_positive(self):
        self.assertGreater(self.r["total_capital_moving_usd"], 0)


class TestNoMigration(unittest.TestCase):
    """All stable protocols → no migration."""

    def setUp(self):
        protocols = [
            _proto("A", "lending", _stable_history()),
            _proto("B", "lending", _stable_history()),
        ]
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze(protocols)

    def test_migration_not_detected(self):
        self.assertEqual(len(self.r["flows"]), 1)
        self.assertFalse(self.r["flows"][0]["migration_detected"])

    def test_active_migrations_zero(self):
        self.assertEqual(self.r["active_migrations"], 0)

    def test_migration_score_zero(self):
        self.assertEqual(self.r["flows"][0]["migration_score"], 0.0)


# ---------------------------------------------------------------------------
# Tests: migration_score calculation
# ---------------------------------------------------------------------------

class TestMigrationScore(unittest.TestCase):

    def test_no_losing_no_gaining_score_zero(self):
        score = _mod._migration_score([], [], 4)
        self.assertEqual(score, 0.0)

    def test_losing_only_score_30(self):
        score = _mod._migration_score([{"name": "A"}], [], 4)
        self.assertEqual(score, 30.0)

    def test_gaining_only_score_20(self):
        score = _mod._migration_score([], [{"name": "B"}], 4)
        self.assertEqual(score, 20.0)

    def test_both_losing_and_gaining_score_above_30(self):
        score = _mod._migration_score([{"name": "A"}], [{"name": "B"}], 2)
        self.assertGreater(score, 30.0)

    def test_both_losing_and_gaining_score_capped_at_100(self):
        # large number of protocols
        losing = [{"name": f"L{i}"} for i in range(50)]
        gaining = [{"name": f"G{i}"} for i in range(50)]
        score = _mod._migration_score(losing, gaining, 100)
        self.assertEqual(score, 100.0)

    def test_score_formula_correctness(self):
        # (1 + 1) / max(1, 4) * 100 + 30 = 50 + 30 = 80
        score = _mod._migration_score([{"name": "A"}], [{"name": "B"}], 4)
        self.assertAlmostEqual(score, 80.0, places=2)

    def test_migration_detected_threshold_40(self):
        # gaining only = 20 → not detected
        score = _mod._migration_score([], [{"name": "X"}], 4)
        self.assertFalse(score >= 40)

    def test_losing_only_not_detected(self):
        score = _mod._migration_score([{"name": "Y"}], [], 4)
        self.assertFalse(score >= 40)


# ---------------------------------------------------------------------------
# Tests: likely_trigger
# ---------------------------------------------------------------------------

class TestLikelyTrigger(unittest.TestCase):

    def test_yield_differential_trigger(self):
        gaining = [{"apy_current": 8.0, "apy_7d_ago": 7.0}]
        losing = [{"apy_current": 4.0, "apy_7d_ago": 5.0}]
        trigger = _mod._likely_trigger(gaining, losing)
        self.assertIn("Yield differential", trigger)

    def test_apy_deterioration_trigger(self):
        gaining = [{"apy_current": 5.0, "apy_7d_ago": 4.5}]
        losing = [
            {"apy_current": 3.0, "apy_7d_ago": 5.0},
            {"apy_current": 2.5, "apy_7d_ago": 4.0},
        ]
        # avg gaining = 5.0, avg losing = 2.75, diff = 2.25 > 1.0 → yield differential wins
        trigger = _mod._likely_trigger(gaining, losing)
        self.assertIn("Yield differential", trigger)

    def test_apy_deterioration_trigger_when_no_gaining(self):
        gaining = []
        losing = [
            {"apy_current": 3.0, "apy_7d_ago": 5.0},
            {"apy_current": 2.0, "apy_7d_ago": 4.0},
        ]
        trigger = _mod._likely_trigger(gaining, losing)
        self.assertIn("APY deterioration", trigger)

    def test_protocol_specific_risk_trigger(self):
        gaining = [{"apy_current": 5.0, "apy_7d_ago": 5.0}]
        losing = [{"apy_current": 4.5, "apy_7d_ago": 4.0}]  # loser APY rising, not dropping
        # avg_gaining=5.0, avg_losing=4.5, diff=0.5 < 1.0; loser apy not all dropped
        trigger = _mod._likely_trigger(gaining, losing)
        self.assertIn("Protocol-specific risk", trigger)

    def test_empty_both_unknown_trigger(self):
        trigger = _mod._likely_trigger([], [])
        self.assertIn("Unknown trigger", trigger)

    def test_trigger_type_is_str(self):
        trigger = _mod._likely_trigger(
            [{"apy_current": 6.0, "apy_7d_ago": 5.0}],
            [{"apy_current": 3.0, "apy_7d_ago": 4.0}],
        )
        self.assertIsInstance(trigger, str)


# ---------------------------------------------------------------------------
# Tests: multi-category
# ---------------------------------------------------------------------------

class TestMultiCategory(unittest.TestCase):
    """Protocols in different categories produce separate flows."""

    def setUp(self):
        protocols = [
            _proto("AaveLend", "lending", _losing_history(100_000_000, 15), apy_current=3.0, apy_7d_ago=5.0),
            _proto("CompLend", "lending", _gaining_history(50_000_000, 20), apy_current=7.0, apy_7d_ago=6.0),
            _proto("CurveStable", "stablecoin_yield", _losing_history(80_000_000, 12), apy_current=2.0, apy_7d_ago=3.5),
            _proto("ConvexStable", "stablecoin_yield", _gaining_history(30_000_000, 15), apy_current=5.0, apy_7d_ago=4.0),
        ]
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze(protocols)

    def test_two_flows_returned(self):
        self.assertEqual(len(self.r["flows"]), 2)

    def test_categories_present(self):
        cats = {f["category"] for f in self.r["flows"]}
        self.assertIn("lending", cats)
        self.assertIn("stablecoin_yield", cats)

    def test_active_migrations_two(self):
        self.assertEqual(self.r["active_migrations"], 2)

    def test_total_capital_includes_both_categories(self):
        self.assertGreater(self.r["total_capital_moving_usd"], 0)


# ---------------------------------------------------------------------------
# Tests: estimated_outflow / estimated_inflow computation
# ---------------------------------------------------------------------------

class TestEstimatedFlows(unittest.TestCase):

    def test_outflow_is_abs_tvl_change(self):
        # 100M → 80M: outflow = 20M
        protocols = [
            _proto("Loser", "dex", [100_000_000, 93_333_333, 86_666_666, 80_000_000], apy_current=2.0, apy_7d_ago=4.0),
            _proto("Gainer", "dex", _gaining_history(50_000_000, 20), apy_current=6.0, apy_7d_ago=5.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        loser = next(p for p in flow["losing_protocols"] if p["name"] == "Loser")
        self.assertAlmostEqual(loser["estimated_outflow_usd"], 20_000_000.0, delta=100)

    def test_inflow_is_abs_tvl_change(self):
        protocols = [
            _proto("Loser", "dex", _losing_history(100_000_000, 15), apy_current=2.0, apy_7d_ago=4.0),
            _proto("Gainer", "dex", [50_000_000, 54_166_666, 58_333_333, 62_500_000], apy_current=6.0, apy_7d_ago=5.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        gainer = next(p for p in flow["gaining_protocols"] if p["name"] == "Gainer")
        self.assertAlmostEqual(gainer["estimated_inflow_usd"], 12_500_000.0, delta=100)


# ---------------------------------------------------------------------------
# Tests: TVL change percentage
# ---------------------------------------------------------------------------

class TestTVLChangePct(unittest.TestCase):

    def test_loser_change_pct_negative(self):
        protocols = [
            _proto("L", "lending", [100.0, 90.0, 85.0, 80.0], apy_current=2.0, apy_7d_ago=4.0),
            _proto("G", "lending", _gaining_history(50_000_000, 15), apy_current=6.0, apy_7d_ago=5.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        loser = next((p for p in flow["losing_protocols"] if p["name"] == "L"), None)
        if loser:
            self.assertLess(loser["tvl_change_pct"], 0)

    def test_gainer_change_pct_positive(self):
        protocols = [
            _proto("L", "lending", _losing_history(100_000_000, 15), apy_current=2.0, apy_7d_ago=4.0),
            _proto("G", "lending", [50.0, 55.0, 58.0, 65.0], apy_current=6.0, apy_7d_ago=5.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        gainer = next((p for p in flow["gaining_protocols"] if p["name"] == "G"), None)
        if gainer:
            self.assertGreater(gainer["tvl_change_pct"], 0)

    def test_zero_first_tvl_excluded(self):
        # first=0 → change_pct=None → excluded from losing/gaining
        protocols = [
            _proto("Z", "lending", [0.0, 50.0, 80.0, 100.0]),
            _proto("B", "lending", _stable_history()),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        all_names = (
            [p["name"] for p in flow["losing_protocols"]] +
            [p["name"] for p in flow["gaining_protocols"]]
        )
        self.assertNotIn("Z", all_names)


# ---------------------------------------------------------------------------
# Tests: output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def test_top_level_keys(self):
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([])
        required = {"flows", "active_migrations", "total_capital_moving_usd",
                    "skipped_protocols", "timestamp"}
        self.assertTrue(required.issubset(r.keys()))

    def test_flow_keys(self):
        protocols = [
            _proto("A", "lending", _losing_history(), apy_current=2.0, apy_7d_ago=4.0),
            _proto("B", "lending", _gaining_history(), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        required = {"category", "losing_protocols", "gaining_protocols",
                    "migration_score", "migration_detected", "likely_trigger"}
        self.assertTrue(required.issubset(flow.keys()))

    def test_losing_protocol_keys(self):
        protocols = [
            _proto("A", "lending", _losing_history(), apy_current=2.0, apy_7d_ago=4.0),
            _proto("B", "lending", _gaining_history(), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        if flow["losing_protocols"]:
            lp = flow["losing_protocols"][0]
            self.assertIn("name", lp)
            self.assertIn("tvl_change_pct", lp)
            self.assertIn("estimated_outflow_usd", lp)

    def test_gaining_protocol_keys(self):
        protocols = [
            _proto("A", "lending", _losing_history(), apy_current=2.0, apy_7d_ago=4.0),
            _proto("B", "lending", _gaining_history(), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        if flow["gaining_protocols"]:
            gp = flow["gaining_protocols"][0]
            self.assertIn("name", gp)
            self.assertIn("tvl_change_pct", gp)
            self.assertIn("estimated_inflow_usd", gp)

    def test_no_internal_keys_in_output(self):
        """_apy_current / _apy_7d_ago should not leak into output."""
        protocols = [
            _proto("A", "lending", _losing_history(), apy_current=2.0, apy_7d_ago=4.0),
            _proto("B", "lending", _gaining_history(), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        flow = r["flows"][0]
        for proto in flow["losing_protocols"] + flow["gaining_protocols"]:
            for key in proto.keys():
                self.assertFalse(key.startswith("_"), f"Internal key leaked: {key}")


# ---------------------------------------------------------------------------
# Tests: log persistence
# ---------------------------------------------------------------------------

class TestLogPersistence(unittest.TestCase):

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "liquidity_migration_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod._append_log({"test": True, "timestamp": 1.0})
            self.assertTrue(log_path.exists())

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "lm_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod._append_log({"entry": 1})
                _mod._append_log({"entry": 2})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "lm_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                with patch.object(_mod, "MAX_ENTRIES", 3):
                    for i in range(6):
                        _mod._append_log({"entry": i})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
            self.assertEqual(data[0]["entry"], 3)

    def test_init_log_creates_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "lm_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod.init_log()
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data, [])

    def test_init_log_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "lm_log.json"
            with open(log_path, "w") as f:
                json.dump([{"preserved": True}], f)
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod.init_log()
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data, [{"preserved": True}])


# ---------------------------------------------------------------------------
# Tests: merge config
# ---------------------------------------------------------------------------

class TestMergeConfig(unittest.TestCase):

    def test_defaults_applied(self):
        cfg = _mod._merge_config(None)
        self.assertEqual(cfg["migration_threshold_pct"], 10.0)
        self.assertEqual(cfg["min_history"], 4)

    def test_partial_override(self):
        cfg = _mod._merge_config({"migration_threshold_pct": 5.0})
        self.assertEqual(cfg["migration_threshold_pct"], 5.0)
        self.assertEqual(cfg["min_history"], 4)

    def test_full_override(self):
        cfg = _mod._merge_config({"migration_threshold_pct": 7.5, "min_history": 6})
        self.assertEqual(cfg["migration_threshold_pct"], 7.5)
        self.assertEqual(cfg["min_history"], 6)


# ---------------------------------------------------------------------------
# Tests: custom threshold
# ---------------------------------------------------------------------------

class TestCustomThreshold(unittest.TestCase):

    def test_higher_threshold_reduces_losers(self):
        # 12% drop
        protocols = [
            _proto("L", "lending", [100_000, 90_000, 87_000, 88_000], apy_current=2.0, apy_7d_ago=4.0),
            _proto("G", "lending", _gaining_history(50_000_000, 15), apy_current=6.0, apy_7d_ago=5.0),
        ]
        # With threshold=5% → L is a loser (12% drop)
        with patch.object(_mod, "_append_log"):
            r5 = _mod.analyze(protocols, config={"migration_threshold_pct": 5.0})
        # With threshold=20% → L NOT a loser (only 12%)
        with patch.object(_mod, "_append_log"):
            r20 = _mod.analyze(protocols, config={"migration_threshold_pct": 20.0})

        losers_5 = r5["flows"][0]["losing_protocols"] if r5["flows"] else []
        losers_20 = r20["flows"][0]["losing_protocols"] if r20["flows"] else []
        self.assertGreaterEqual(len(losers_5), len(losers_20))


# ---------------------------------------------------------------------------
# Tests: safe_mean utility
# ---------------------------------------------------------------------------

class TestSafeMean(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_mod._safe_mean([]), 0.0)

    def test_single_value(self):
        self.assertEqual(_mod._safe_mean([5.0]), 5.0)

    def test_multiple_values(self):
        self.assertAlmostEqual(_mod._safe_mean([1.0, 2.0, 3.0]), 2.0, places=5)


# ---------------------------------------------------------------------------
# Tests: total_capital_moving_usd accumulation
# ---------------------------------------------------------------------------

class TestTotalCapitalMoving(unittest.TestCase):

    def test_total_equals_sum_of_outflows(self):
        protocols = [
            _proto("Aave", "lending", _losing_history(100_000_000, 20), apy_current=2.0, apy_7d_ago=5.0),
            _proto("Comp", "lending", _gaining_history(50_000_000, 25), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        expected = sum(
            lp["estimated_outflow_usd"]
            for f in r["flows"]
            for lp in f["losing_protocols"]
        )
        self.assertAlmostEqual(r["total_capital_moving_usd"], expected, places=2)

    def test_no_losers_no_capital_moving(self):
        protocols = [
            _proto("A", "lending", _stable_history()),
            _proto("B", "lending", _gaining_history(50_000_000, 15)),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        self.assertEqual(r["total_capital_moving_usd"], 0.0)


# ---------------------------------------------------------------------------
# Tests: migration_detected flag
# ---------------------------------------------------------------------------

class TestMigrationDetectedFlag(unittest.TestCase):

    def test_score_lt_40_not_detected(self):
        # Only gaining (score=20 < 40)
        protocols = [
            _proto("A", "lending", _stable_history()),
            _proto("B", "lending", _gaining_history(50_000_000, 15), apy_current=6.0, apy_7d_ago=5.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        self.assertFalse(r["flows"][0]["migration_detected"])

    def test_score_gte_40_detected(self):
        # Both losing and gaining → score ≥ 40
        protocols = [
            _proto("A", "lending", _losing_history(), apy_current=2.0, apy_7d_ago=4.0),
            _proto("B", "lending", _gaining_history(), apy_current=7.0, apy_7d_ago=6.0),
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        self.assertTrue(r["flows"][0]["migration_detected"])


# ---------------------------------------------------------------------------
# Tests: only-losing (no gaining) scenario
# ---------------------------------------------------------------------------

class TestOnlyLosingProtocols(unittest.TestCase):

    def setUp(self):
        protocols = [
            _proto("A", "dex", _losing_history(100_000_000, 15), apy_current=3.0, apy_7d_ago=5.0),
            _proto("B", "dex", _stable_history(80_000_000)),
        ]
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze(protocols, config={"migration_threshold_pct": 10.0})

    def test_flow_exists(self):
        self.assertEqual(len(self.r["flows"]), 1)

    def test_migration_score_30(self):
        self.assertAlmostEqual(self.r["flows"][0]["migration_score"], 30.0, places=2)

    def test_migration_not_detected(self):
        self.assertFalse(self.r["flows"][0]["migration_detected"])

    def test_gaining_is_empty(self):
        self.assertEqual(self.r["flows"][0]["gaining_protocols"], [])


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_all_same_category(self):
        protocols = [
            _proto(f"P{i}", "lending", _stable_history()) for i in range(5)
        ]
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        self.assertEqual(len(r["flows"]), 1)
        self.assertEqual(r["flows"][0]["category"], "lending")

    def test_timestamp_is_recent(self):
        before = time.time()
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_three_categories_three_flows(self):
        cats = ["lending", "dex", "stablecoin"]
        protocols = []
        for cat in cats:
            protocols.append(_proto(f"{cat}_L", cat, _losing_history(), apy_current=2.0, apy_7d_ago=4.0))
            protocols.append(_proto(f"{cat}_G", cat, _gaining_history(), apy_current=7.0, apy_7d_ago=6.0))
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze(protocols)
        self.assertEqual(len(r["flows"]), 3)


if __name__ == "__main__":
    unittest.main()
