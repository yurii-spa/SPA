"""
Tests for MP-901 DeFiLiquidityMigrationDetector.
Run: python3 -m unittest spa_core.tests.test_defi_liquidity_migration_detector -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on path when run directly
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.defi_liquidity_migration_detector import (
    _atomic_write,
    _append_log,
    _build_migration_pairs,
    _ecosystem_impact_score,
    _flags,
    _migration_signal,
    _read_log,
    _recommendation,
    _risk_signal,
    _tvl_change,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="Proto",
    tvl_7d=1_000_000.0,
    tvl_now=1_000_000.0,
    inflow=None,
    outflow=None,
    reason="ORGANIC",
):
    return {
        "name": name,
        "tvl_7d_ago_usd": tvl_7d,
        "tvl_current_usd": tvl_now,
        "inflow_sources": inflow or [],
        "outflow_destinations": outflow or [],
        "tvl_change_reason": reason,
    }


def _snap(*protos):
    return {"protocols": list(protos)}


# ---------------------------------------------------------------------------
# 1. _tvl_change
# ---------------------------------------------------------------------------

class TestTvlChange(unittest.TestCase):
    def test_no_change(self):
        p = _proto(tvl_7d=1e6, tvl_now=1e6)
        usd, pct = _tvl_change(p)
        self.assertAlmostEqual(usd, 0.0)
        self.assertAlmostEqual(pct, 0.0)

    def test_positive_change(self):
        p = _proto(tvl_7d=1e6, tvl_now=1.25e6)
        usd, pct = _tvl_change(p)
        self.assertAlmostEqual(usd, 250_000.0)
        self.assertAlmostEqual(pct, 25.0)

    def test_negative_change(self):
        p = _proto(tvl_7d=2e6, tvl_now=1e6)
        usd, pct = _tvl_change(p)
        self.assertAlmostEqual(usd, -1_000_000.0)
        self.assertAlmostEqual(pct, -50.0)

    def test_zero_prev_tvl(self):
        p = _proto(tvl_7d=0, tvl_now=500_000)
        usd, pct = _tvl_change(p)
        self.assertAlmostEqual(usd, 500_000.0)
        self.assertAlmostEqual(pct, 0.0)

    def test_both_zero(self):
        p = _proto(tvl_7d=0, tvl_now=0)
        usd, pct = _tvl_change(p)
        self.assertAlmostEqual(usd, 0.0)
        self.assertAlmostEqual(pct, 0.0)

    def test_small_change(self):
        p = _proto(tvl_7d=1_000_000, tvl_now=1_050_000)
        _, pct = _tvl_change(p)
        self.assertAlmostEqual(pct, 5.0)

    def test_exact_10pct_drop(self):
        p = _proto(tvl_7d=1_000_000, tvl_now=900_000)
        _, pct = _tvl_change(p)
        self.assertAlmostEqual(pct, -10.0)


# ---------------------------------------------------------------------------
# 2. _migration_signal
# ---------------------------------------------------------------------------

class TestMigrationSignal(unittest.TestCase):
    def test_strong_inflow(self):
        self.assertEqual(_migration_signal(25.0), "STRONG_INFLOW")

    def test_strong_inflow_exactly_above_20(self):
        self.assertEqual(_migration_signal(20.1), "STRONG_INFLOW")

    def test_inflow(self):
        self.assertEqual(_migration_signal(15.0), "INFLOW")

    def test_inflow_boundary_above_10(self):
        self.assertEqual(_migration_signal(10.1), "INFLOW")

    def test_stable_positive(self):
        self.assertEqual(_migration_signal(5.0), "STABLE")

    def test_stable_zero(self):
        self.assertEqual(_migration_signal(0.0), "STABLE")

    def test_stable_negative(self):
        self.assertEqual(_migration_signal(-5.0), "STABLE")

    def test_stable_boundary_minus_10(self):
        self.assertEqual(_migration_signal(-10.0), "STABLE")

    def test_outflow(self):
        self.assertEqual(_migration_signal(-15.0), "OUTFLOW")

    def test_outflow_boundary(self):
        self.assertEqual(_migration_signal(-20.0), "OUTFLOW")

    def test_strong_outflow(self):
        self.assertEqual(_migration_signal(-25.0), "STRONG_OUTFLOW")

    def test_strong_outflow_large(self):
        self.assertEqual(_migration_signal(-99.9), "STRONG_OUTFLOW")


# ---------------------------------------------------------------------------
# 3. _ecosystem_impact_score
# ---------------------------------------------------------------------------

class TestEcosystemImpactScore(unittest.TestCase):
    def test_zero_all(self):
        self.assertEqual(_ecosystem_impact_score(0.0, 0, 0), 0)

    def test_basic_positive(self):
        # abs(20)*2 + 1*5 + 0*5 = 45
        self.assertEqual(_ecosystem_impact_score(20.0, 1, 0), 45)

    def test_capped_at_100(self):
        self.assertEqual(_ecosystem_impact_score(100.0, 10, 10), 100)

    def test_negative_pct_abs(self):
        # abs(-30)*2 + 0*5 + 2*5 = 60+10 = 70
        self.assertEqual(_ecosystem_impact_score(-30.0, 0, 2), 70)

    def test_floor_at_zero(self):
        self.assertEqual(_ecosystem_impact_score(0.0, 0, 0), 0)

    def test_source_count_bonus(self):
        # abs(0)*2 + 3*5 + 0*5 = 15
        self.assertEqual(_ecosystem_impact_score(0.0, 3, 0), 15)

    def test_dest_count_bonus(self):
        # abs(0)*2 + 0*5 + 4*5 = 20
        self.assertEqual(_ecosystem_impact_score(0.0, 0, 4), 20)


# ---------------------------------------------------------------------------
# 4. _risk_signal
# ---------------------------------------------------------------------------

class TestRiskSignal(unittest.TestCase):
    def test_flee_risk_strong_outflow_migration(self):
        self.assertEqual(_risk_signal("STRONG_OUTFLOW", "MIGRATION"), "FLEE_RISK")

    def test_flee_risk_outflow_migration(self):
        self.assertEqual(_risk_signal("OUTFLOW", "MIGRATION"), "FLEE_RISK")

    def test_opportunity_strong_inflow(self):
        self.assertEqual(_risk_signal("STRONG_INFLOW", "ORGANIC"), "OPPORTUNITY")

    def test_growing_inflow(self):
        self.assertEqual(_risk_signal("INFLOW", "ORGANIC"), "GROWING")

    def test_monitor_outflow_organic(self):
        self.assertEqual(_risk_signal("OUTFLOW", "ORGANIC"), "MONITOR")

    def test_monitor_strong_outflow_organic(self):
        self.assertEqual(_risk_signal("STRONG_OUTFLOW", "ORGANIC"), "MONITOR")

    def test_stable(self):
        self.assertEqual(_risk_signal("STABLE", "ORGANIC"), "STABLE")

    def test_stable_market_move(self):
        self.assertEqual(_risk_signal("STABLE", "MARKET_MOVE"), "STABLE")


# ---------------------------------------------------------------------------
# 5. _flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_no_flags(self):
        self.assertEqual(_flags(0.0, "ORGANIC", 10.0), [])

    def test_significant_outflow(self):
        flags = _flags(-15.0, "ORGANIC", 10.0)
        self.assertIn("SIGNIFICANT_OUTFLOW", flags)

    def test_rapid_growth(self):
        flags = _flags(25.0, "ORGANIC", 10.0)
        self.assertIn("RAPID_GROWTH", flags)

    def test_migration_driven(self):
        flags = _flags(0.0, "MIGRATION", 10.0)
        self.assertIn("MIGRATION_DRIVEN", flags)

    def test_unknown_cause(self):
        flags = _flags(0.0, "UNKNOWN", 10.0)
        self.assertIn("UNKNOWN_CAUSE", flags)

    def test_multiple_flags(self):
        flags = _flags(-20.0, "MIGRATION", 10.0)
        self.assertIn("SIGNIFICANT_OUTFLOW", flags)
        self.assertIn("MIGRATION_DRIVEN", flags)

    def test_rapid_growth_boundary(self):
        # exactly 2x significant_pct → flag
        flags = _flags(20.1, "ORGANIC", 10.0)
        self.assertIn("RAPID_GROWTH", flags)

    def test_no_rapid_growth_at_boundary(self):
        # exactly 20 → NOT > 20 → no RAPID_GROWTH
        flags = _flags(20.0, "ORGANIC", 10.0)
        self.assertNotIn("RAPID_GROWTH", flags)


# ---------------------------------------------------------------------------
# 6. _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_opportunity_no_sources(self):
        rec = _recommendation("OPPORTUNITY", 30.0, [], [])
        self.assertIn("30.0", rec)
        self.assertIn("Organic growth", rec)

    def test_opportunity_with_sources(self):
        rec = _recommendation("OPPORTUNITY", 25.5, ["Aave", "Compound"], [])
        self.assertIn("Aave", rec)
        self.assertIn("Compound", rec)

    def test_opportunity_truncates_sources(self):
        rec = _recommendation("OPPORTUNITY", 25.0, ["A", "B", "C"], [])
        self.assertNotIn("C", rec)

    def test_growing(self):
        rec = _recommendation("GROWING", 12.0, [], [])
        self.assertIn("12.0", rec)

    def test_stable(self):
        rec = _recommendation("STABLE", 3.0, [], [])
        self.assertIn("Stable", rec)
        self.assertIn("3.0", rec)

    def test_monitor(self):
        rec = _recommendation("MONITOR", -15.0, [], [])
        self.assertIn("declining", rec)
        self.assertIn("-15.0", rec)

    def test_flee_risk_with_dests(self):
        rec = _recommendation("FLEE_RISK", -25.0, [], ["Morpho", "Euler"])
        self.assertIn("Morpho", rec)
        self.assertIn("Euler", rec)

    def test_flee_risk_no_dests(self):
        rec = _recommendation("FLEE_RISK", -25.0, [], [])
        self.assertIn("unknown destinations", rec)

    def test_flee_risk_truncates_dests(self):
        rec = _recommendation("FLEE_RISK", -25.0, [], ["A", "B", "C"])
        self.assertNotIn("C", rec)


# ---------------------------------------------------------------------------
# 7. _build_migration_pairs
# ---------------------------------------------------------------------------

class TestBuildMigrationPairs(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_build_migration_pairs([], set()), [])

    def test_confirmed_pair(self):
        protos = [
            _proto("Aave", outflow=["Morpho"]),
            _proto("Morpho"),
        ]
        names = {"Aave", "Morpho"}
        pairs = _build_migration_pairs(protos, names)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["source"], "Aave")
        self.assertEqual(pairs[0]["destination"], "Morpho")
        self.assertEqual(pairs[0]["implied_flow_type"], "CONFIRMED")

    def test_reported_pair(self):
        protos = [_proto("Aave", outflow=["Unknown Proto"])]
        names = {"Aave"}
        pairs = _build_migration_pairs(protos, names)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["implied_flow_type"], "REPORTED")

    def test_multiple_outflows(self):
        protos = [_proto("Aave", outflow=["Morpho", "Compound", "External"])]
        names = {"Aave", "Morpho", "Compound"}
        pairs = _build_migration_pairs(protos, names)
        self.assertEqual(len(pairs), 3)
        types = {p["destination"]: p["implied_flow_type"] for p in pairs}
        self.assertEqual(types["Morpho"], "CONFIRMED")
        self.assertEqual(types["Compound"], "CONFIRMED")
        self.assertEqual(types["External"], "REPORTED")

    def test_no_outflows_skipped(self):
        protos = [_proto("Aave", outflow=[])]
        names = {"Aave"}
        pairs = _build_migration_pairs(protos, names)
        self.assertEqual(pairs, [])


# ---------------------------------------------------------------------------
# 8. analyze() — structure & types
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):
    def test_empty_protocols(self):
        result = analyze({"protocols": []})
        self.assertEqual(result["protocols"], [])
        self.assertEqual(result["migration_pairs"], [])
        self.assertAlmostEqual(result["net_ecosystem_flow"], 0.0)
        self.assertIsNone(result["biggest_gainer"])
        self.assertIsNone(result["biggest_loser"])
        self.assertIn("timestamp", result)

    def test_missing_protocols_key(self):
        result = analyze({})
        self.assertEqual(result["protocols"], [])

    def test_none_protocols(self):
        result = analyze({"protocols": None})
        self.assertEqual(result["protocols"], [])

    def test_single_protocol_keys(self):
        result = analyze(_snap(_proto("Aave", tvl_7d=1e6, tvl_now=1.2e6)))
        p = result["protocols"][0]
        for key in (
            "name", "tvl_change_usd", "tvl_change_pct", "migration_signal",
            "inflow_source_count", "outflow_destination_count", "migration_type",
            "ecosystem_impact_score", "risk_signal", "flags", "recommendation",
        ):
            self.assertIn(key, p, f"Missing key: {key}")

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze(_snap(_proto()))
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# 9. analyze() — calculations
# ---------------------------------------------------------------------------

class TestAnalyzeCalculations(unittest.TestCase):
    def test_net_ecosystem_flow_two_protos(self):
        result = analyze(_snap(
            _proto("A", tvl_7d=1_000_000, tvl_now=800_000),
            _proto("B", tvl_7d=500_000, tvl_now=700_000),
        ))
        # -200_000 + 200_000 = 0
        self.assertAlmostEqual(result["net_ecosystem_flow"], 0.0)

    def test_net_ecosystem_flow_positive(self):
        result = analyze(_snap(
            _proto("A", tvl_7d=1e6, tvl_now=1.5e6),
            _proto("B", tvl_7d=1e6, tvl_now=1.2e6),
        ))
        self.assertAlmostEqual(result["net_ecosystem_flow"], 700_000.0)

    def test_biggest_gainer(self):
        result = analyze(_snap(
            _proto("A", tvl_7d=1e6, tvl_now=1.3e6),   # +30%
            _proto("B", tvl_7d=1e6, tvl_now=1.5e6),   # +50%
            _proto("C", tvl_7d=1e6, tvl_now=0.9e6),   # -10%
        ))
        self.assertEqual(result["biggest_gainer"], "B")

    def test_biggest_loser(self):
        result = analyze(_snap(
            _proto("A", tvl_7d=1e6, tvl_now=1.3e6),
            _proto("B", tvl_7d=1e6, tvl_now=0.7e6),   # -30%
            _proto("C", tvl_7d=1e6, tvl_now=0.9e6),
        ))
        self.assertEqual(result["biggest_loser"], "B")

    def test_single_proto_gainer_equals_loser(self):
        result = analyze(_snap(_proto("Aave", tvl_7d=1e6, tvl_now=1.2e6)))
        self.assertEqual(result["biggest_gainer"], "Aave")
        self.assertEqual(result["biggest_loser"], "Aave")

    def test_migration_signal_in_result(self):
        result = analyze(_snap(_proto("X", tvl_7d=1e6, tvl_now=1.25e6)))
        self.assertEqual(result["protocols"][0]["migration_signal"], "STRONG_INFLOW")

    def test_zero_prev_tvl_no_change_pct(self):
        result = analyze(_snap(_proto("X", tvl_7d=0, tvl_now=500_000)))
        p = result["protocols"][0]
        self.assertAlmostEqual(p["tvl_change_pct"], 0.0)
        self.assertEqual(p["migration_signal"], "STABLE")

    def test_flee_risk_in_result(self):
        result = analyze(_snap(
            _proto("Aave", tvl_7d=1e6, tvl_now=700_000, reason="MIGRATION")
        ))
        p = result["protocols"][0]
        self.assertEqual(p["risk_signal"], "FLEE_RISK")

    def test_opportunity_in_result(self):
        result = analyze(_snap(
            _proto("Morpho", tvl_7d=1e6, tvl_now=1_300_000, reason="ORGANIC")
        ))
        p = result["protocols"][0]
        self.assertEqual(p["risk_signal"], "OPPORTUNITY")

    def test_inflow_source_count(self):
        result = analyze(_snap(
            _proto("Morpho", inflow=["Aave", "Compound"])
        ))
        self.assertEqual(result["protocols"][0]["inflow_source_count"], 2)

    def test_outflow_dest_count(self):
        result = analyze(_snap(
            _proto("Aave", outflow=["Morpho", "Euler", "Compound"])
        ))
        self.assertEqual(result["protocols"][0]["outflow_destination_count"], 3)

    def test_migration_type_pass_through(self):
        result = analyze(_snap(_proto("X", reason="MARKET_MOVE")))
        self.assertEqual(result["protocols"][0]["migration_type"], "MARKET_MOVE")

    def test_impact_score_bounded(self):
        result = analyze(_snap(_proto("X", tvl_7d=1e6, tvl_now=0, reason="MIGRATION")))
        score = result["protocols"][0]["ecosystem_impact_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# 10. analyze() — custom config
# ---------------------------------------------------------------------------

class TestAnalyzeConfig(unittest.TestCase):
    def test_custom_significant_pct_higher_threshold(self):
        # -15% change, default threshold 10 → SIGNIFICANT_OUTFLOW
        # with threshold 20 → no flag
        result_default = analyze(
            _snap(_proto("X", tvl_7d=1e6, tvl_now=850_000, reason="ORGANIC")),
            config={"significant_change_pct": 10.0},
        )
        result_high = analyze(
            _snap(_proto("X", tvl_7d=1e6, tvl_now=850_000, reason="ORGANIC")),
            config={"significant_change_pct": 20.0},
        )
        self.assertIn("SIGNIFICANT_OUTFLOW", result_default["protocols"][0]["flags"])
        self.assertNotIn("SIGNIFICANT_OUTFLOW", result_high["protocols"][0]["flags"])

    def test_config_none_uses_default(self):
        result = analyze(_snap(_proto()), config=None)
        self.assertIsInstance(result, dict)

    def test_config_empty_uses_default(self):
        result = analyze(_snap(_proto()), config={})
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# 11. Migration pairs in analyze()
# ---------------------------------------------------------------------------

class TestAnalyzeMigrationPairs(unittest.TestCase):
    def test_pairs_confirmed(self):
        result = analyze(_snap(
            _proto("Aave", outflow=["Morpho"]),
            _proto("Morpho"),
        ))
        self.assertEqual(len(result["migration_pairs"]), 1)
        self.assertEqual(result["migration_pairs"][0]["implied_flow_type"], "CONFIRMED")

    def test_pairs_reported(self):
        result = analyze(_snap(
            _proto("Aave", outflow=["ExternalProto"]),
        ))
        self.assertEqual(result["migration_pairs"][0]["implied_flow_type"], "REPORTED")

    def test_no_pairs_when_no_outflows(self):
        result = analyze(_snap(_proto("Aave"), _proto("Morpho")))
        self.assertEqual(result["migration_pairs"], [])


# ---------------------------------------------------------------------------
# 12. Persistence helpers
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def _tmpdir(self):
        d = tempfile.mkdtemp()
        return d

    def test_atomic_write_and_read_log(self):
        d = self._tmpdir()
        path = os.path.join(d, "test_log.json")
        _atomic_write(path, [{"a": 1}])
        data = _read_log(path)
        self.assertEqual(data, [{"a": 1}])

    def test_read_log_missing_file(self):
        d = self._tmpdir()
        path = os.path.join(d, "nonexistent.json")
        self.assertEqual(_read_log(path), [])

    def test_read_log_invalid_json(self):
        d = self._tmpdir()
        path = os.path.join(d, "bad.json")
        with open(path, "w") as f:
            f.write("NOT JSON{{}")
        self.assertEqual(_read_log(path), [])

    def test_read_log_non_list_json(self):
        d = self._tmpdir()
        path = os.path.join(d, "obj.json")
        _atomic_write(path, {"key": "val"})
        self.assertEqual(_read_log(path), [])

    def test_append_log_creates_file(self):
        d = self._tmpdir()
        path = os.path.join(d, "new_log.json")
        _append_log(path, {"x": 1})
        data = _read_log(path)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 1)

    def test_append_log_ring_buffer_cap(self):
        d = self._tmpdir()
        path = os.path.join(d, "ring.json")
        for i in range(110):
            _append_log(path, {"i": i})
        data = _read_log(path)
        self.assertEqual(len(data), 100)
        # Most recent entries kept
        self.assertEqual(data[-1]["i"], 109)
        self.assertEqual(data[0]["i"], 10)

    def test_append_log_multiple(self):
        d = self._tmpdir()
        path = os.path.join(d, "multi.json")
        _append_log(path, {"n": 1})
        _append_log(path, {"n": 2})
        data = _read_log(path)
        self.assertEqual(len(data), 2)

    def test_atomic_write_creates_dirs(self):
        d = self._tmpdir()
        path = os.path.join(d, "sub", "dir", "file.json")
        _atomic_write(path, [])
        self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# 13. Full integration scenario
# ---------------------------------------------------------------------------

class TestIntegrationScenario(unittest.TestCase):
    def test_three_protocol_migration_scenario(self):
        snap = {
            "protocols": [
                {
                    "name": "Aave V3",
                    "tvl_7d_ago_usd": 10_000_000,
                    "tvl_current_usd": 7_500_000,
                    "inflow_sources": [],
                    "outflow_destinations": ["Morpho Blue", "Compound V3"],
                    "tvl_change_reason": "MIGRATION",
                },
                {
                    "name": "Morpho Blue",
                    "tvl_7d_ago_usd": 2_000_000,
                    "tvl_current_usd": 3_000_000,
                    "inflow_sources": ["Aave V3"],
                    "outflow_destinations": [],
                    "tvl_change_reason": "MIGRATION",
                },
                {
                    "name": "Compound V3",
                    "tvl_7d_ago_usd": 5_000_000,
                    "tvl_current_usd": 5_500_000,
                    "inflow_sources": ["Aave V3"],
                    "outflow_destinations": [],
                    "tvl_change_reason": "ORGANIC",
                },
            ]
        }
        result = analyze(snap)

        aave = next(p for p in result["protocols"] if p["name"] == "Aave V3")
        morpho = next(p for p in result["protocols"] if p["name"] == "Morpho Blue")
        compound = next(p for p in result["protocols"] if p["name"] == "Compound V3")

        # Aave: -25% MIGRATION → FLEE_RISK
        self.assertAlmostEqual(aave["tvl_change_pct"], -25.0)
        self.assertEqual(aave["risk_signal"], "FLEE_RISK")
        self.assertIn("SIGNIFICANT_OUTFLOW", aave["flags"])
        self.assertIn("MIGRATION_DRIVEN", aave["flags"])

        # Morpho: +50% MIGRATION → OPPORTUNITY
        self.assertAlmostEqual(morpho["tvl_change_pct"], 50.0)
        self.assertEqual(morpho["risk_signal"], "OPPORTUNITY")

        # Compound: +10% → exactly at boundary of STABLE (spec: > 10 for INFLOW)
        self.assertAlmostEqual(compound["tvl_change_pct"], 10.0)
        self.assertEqual(compound["migration_signal"], "STABLE")
        self.assertEqual(compound["risk_signal"], "STABLE")

        # Pairs: Aave→Morpho (CONFIRMED), Aave→Compound (CONFIRMED)
        self.assertEqual(len(result["migration_pairs"]), 2)

        # Net flow: -2.5M + 1M + 0.5M = -1M
        self.assertAlmostEqual(result["net_ecosystem_flow"], -1_000_000.0)

        # Gainer = Morpho, Loser = Aave
        self.assertEqual(result["biggest_gainer"], "Morpho Blue")
        self.assertEqual(result["biggest_loser"], "Aave V3")

    def test_stable_ecosystem_no_flags(self):
        snap = {
            "protocols": [
                _proto("A", tvl_7d=1e6, tvl_now=1_050_000, reason="ORGANIC"),
                _proto("B", tvl_7d=1e6, tvl_now=980_000, reason="ORGANIC"),
            ]
        }
        result = analyze(snap)
        for p in result["protocols"]:
            self.assertEqual(p["migration_signal"], "STABLE")
            self.assertEqual(p["flags"], [])

    def test_result_is_serializable(self):
        result = analyze(_snap(
            _proto("Aave", tvl_7d=5e6, tvl_now=4e6, reason="MIGRATION",
                   outflow=["Morpho"]),
            _proto("Morpho", tvl_7d=2e6, tvl_now=3e6, inflow=["Aave"]),
        ))
        # Must not raise
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["biggest_loser"], "Aave")

    def test_empty_snapshot_all_none(self):
        result = analyze({"protocols": []})
        self.assertIsNone(result["biggest_gainer"])
        self.assertIsNone(result["biggest_loser"])
        self.assertAlmostEqual(result["net_ecosystem_flow"], 0.0)
        self.assertEqual(result["migration_pairs"], [])

    def test_unknown_reason_flag(self):
        result = analyze(_snap(_proto("X", reason="UNKNOWN")))
        self.assertIn("UNKNOWN_CAUSE", result["protocols"][0]["flags"])

    def test_market_move_reason_no_migration_flag(self):
        result = analyze(_snap(_proto("X", reason="MARKET_MOVE")))
        self.assertNotIn("MIGRATION_DRIVEN", result["protocols"][0]["flags"])
        self.assertNotIn("UNKNOWN_CAUSE", result["protocols"][0]["flags"])

    def test_recommendation_not_empty(self):
        result = analyze(_snap(_proto("X", tvl_7d=1e6, tvl_now=0.5e6, reason="MIGRATION")))
        rec = result["protocols"][0]["recommendation"]
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_flags_is_list(self):
        result = analyze(_snap(_proto()))
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_ecosystem_impact_bounded_in_full_run(self):
        result = analyze(_snap(_proto("X", tvl_7d=1, tvl_now=1_000_000_000)))
        score = result["protocols"][0]["ecosystem_impact_score"]
        self.assertLessEqual(score, 100)
        self.assertGreaterEqual(score, 0)


if __name__ == "__main__":
    unittest.main()
