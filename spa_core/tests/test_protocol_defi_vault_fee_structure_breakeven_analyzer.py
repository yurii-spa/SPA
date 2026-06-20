"""
MP-1005 Tests: ProtocolDeFiVaultFeeStructureBreakevenAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_vault_fee_structure_breakeven_analyzer -v
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.protocol_defi_vault_fee_structure_breakeven_analyzer import (
    ProtocolDeFiVaultFeeStructureBreakevenAnalyzer,
)


def make_vault(**kwargs):
    defaults = {
        "name": "Vault-A",
        "protocol": "YieldVault",
        "gross_apy_pct": 30.0,
        "management_fee_pct": 2.0,
        "performance_fee_pct": 20.0,
        "hurdle_rate_pct": 5.0,
        "aum_usd": 10_000_000.0,
        "peer_avg_total_fee_load_pct": 25.0,
        "target_net_apy_pct": 20.0,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_vault()])
        self.assertEqual(r["vault_count"], 1)
        v = r["vaults"][0]
        for k in (
            "name", "protocol", "gross_apy_pct", "management_fee_pct",
            "performance_fee_pct", "hurdle_rate_pct", "profit_above_hurdle_pct",
            "perf_fee_drag_pct", "total_fee_drag_pct", "net_apy_pct",
            "effective_fee_load_pct", "required_gross_apy_pct",
            "management_fee_usd", "performance_fee_usd", "total_fee_usd",
            "net_yield_usd", "fee_value_score", "grade", "classification", "flags",
        ):
            self.assertIn(k, v)

    def test_aggregate_keys(self):
        r = self.az.analyze([make_vault()])
        agg = r["aggregates"]
        for k in (
            "best_vault", "worst_vault", "average_fee_value_score",
            "overpriced_count", "net_negative_count",
        ):
            self.assertIn(k, agg)

    def test_timestamp_present(self):
        r = self.az.analyze([make_vault()])
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["vault_count"], 0)
        self.assertIsNone(r["aggregates"]["average_fee_value_score"])
        self.assertIsNone(r["aggregates"]["best_vault"])

    def test_vault_count_multi(self):
        r = self.az.analyze([make_vault(), make_vault(name="B"), make_vault(name="C")])
        self.assertEqual(r["vault_count"], 3)


class TestCoreMath(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_profit_above_hurdle(self):
        # gross 30 - hurdle 5 = 25
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertAlmostEqual(v["profit_above_hurdle_pct"], 25.0, places=4)

    def test_perf_fee_drag(self):
        # 25 * 20% = 5
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertAlmostEqual(v["perf_fee_drag_pct"], 5.0, places=4)

    def test_total_fee_drag(self):
        # mgmt 2 + perf 5 = 7
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertAlmostEqual(v["total_fee_drag_pct"], 7.0, places=4)

    def test_net_apy(self):
        # 30 - 7 = 23
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertAlmostEqual(v["net_apy_pct"], 23.0, places=4)

    def test_effective_fee_load_known_value(self):
        # 7 / 30 * 100 = 23.3333...
        v = self.az.analyze([make_vault()])["vaults"][0]
        expected = 7.0 / 30.0 * 100.0
        self.assertAlmostEqual(v["effective_fee_load_pct"], round(expected, 4), places=4)

    def test_required_gross_roundtrip(self):
        # required gross should net exactly the target when re-run as gross
        v = self.az.analyze([make_vault(target_net_apy_pct=20.0)])["vaults"][0]
        g = v["required_gross_apy_pct"]
        self.assertIsNotNone(g)
        # recompute net from g
        check = self.az.analyze([make_vault(gross_apy_pct=g)])["vaults"][0]
        self.assertAlmostEqual(check["net_apy_pct"], 20.0, places=2)

    def test_required_gross_formula(self):
        # g = (t + m - h*f/100) / (1 - f/100)
        # = (20 + 2 - 5*0.2) / (1 - 0.2) = (20+2-1)/0.8 = 21/0.8 = 26.25
        v = self.az.analyze([make_vault(target_net_apy_pct=20.0)])["vaults"][0]
        self.assertAlmostEqual(v["required_gross_apy_pct"], 26.25, places=4)

    def test_dollar_figures(self):
        # aum 10M: mgmt 2% = 200k, perf 5% = 500k, total 7% = 700k, net 23% = 2.3M
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertAlmostEqual(v["management_fee_usd"], 200_000.0, places=2)
        self.assertAlmostEqual(v["performance_fee_usd"], 500_000.0, places=2)
        self.assertAlmostEqual(v["total_fee_usd"], 700_000.0, places=2)
        self.assertAlmostEqual(v["net_yield_usd"], 2_300_000.0, places=2)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_gross_below_hurdle_no_perf_fee(self):
        # gross 3 < hurdle 5 -> profit above hurdle 0 -> no perf fee
        v = self.az.analyze([make_vault(gross_apy_pct=3.0)])["vaults"][0]
        self.assertEqual(v["profit_above_hurdle_pct"], 0.0)
        self.assertEqual(v["perf_fee_drag_pct"], 0.0)

    def test_zero_gross_effective_load_guarded(self):
        # no crash when gross == 0
        v = self.az.analyze([make_vault(gross_apy_pct=0.0, management_fee_pct=0.0,
                                        performance_fee_pct=0.0)])["vaults"][0]
        self.assertEqual(v["classification"], "INSUFFICIENT_DATA")

    def test_no_target_no_required_gross(self):
        vault = make_vault()
        del vault["target_net_apy_pct"]
        v = self.az.analyze([vault])["vaults"][0]
        self.assertIsNone(v["required_gross_apy_pct"])

    def test_perf_fee_100_required_gross_none(self):
        # 100% perf fee -> denominator zero -> no finite gross reaches target
        v = self.az.analyze([make_vault(performance_fee_pct=100.0,
                                        target_net_apy_pct=20.0)])["vaults"][0]
        self.assertIsNone(v["required_gross_apy_pct"])

    def test_perf_fee_clamped(self):
        v = self.az.analyze([make_vault(performance_fee_pct=150.0)])["vaults"][0]
        self.assertEqual(v["performance_fee_pct"], 100.0)

    def test_default_hurdle_zero(self):
        vault = make_vault()
        del vault["hurdle_rate_pct"]
        v = self.az.analyze([vault])["vaults"][0]
        self.assertEqual(v["hurdle_rate_pct"], 0.0)

    def test_negative_management_fee_floored(self):
        v = self.az.analyze([make_vault(management_fee_pct=-5.0)])["vaults"][0]
        self.assertEqual(v["management_fee_pct"], 0.0)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_excellent_value(self):
        # low fees: load <= 15%
        v = self.az.analyze([make_vault(
            gross_apy_pct=30.0, management_fee_pct=0.5,
            performance_fee_pct=10.0, hurdle_rate_pct=10.0,
        )])["vaults"][0]
        self.assertEqual(v["classification"], "EXCELLENT_VALUE")

    def test_fair(self):
        # load in (15, 30]
        v = self.az.analyze([make_vault()])["vaults"][0]
        self.assertEqual(v["classification"], "FAIR")

    def test_expensive(self):
        # load in (30, 50]
        v = self.az.analyze([make_vault(
            gross_apy_pct=20.0, management_fee_pct=2.0,
            performance_fee_pct=30.0, hurdle_rate_pct=0.0,
        )])["vaults"][0]
        self.assertEqual(v["classification"], "EXPENSIVE")

    def test_overpriced(self):
        # load > 50% but net still positive
        v = self.az.analyze([make_vault(
            gross_apy_pct=10.0, management_fee_pct=3.0,
            performance_fee_pct=40.0, hurdle_rate_pct=0.0,
        )])["vaults"][0]
        self.assertEqual(v["classification"], "OVERPRICED")

    def test_value_destructive(self):
        # net negative
        v = self.az.analyze([make_vault(
            gross_apy_pct=2.0, management_fee_pct=5.0,
            performance_fee_pct=0.0, hurdle_rate_pct=0.0,
        )])["vaults"][0]
        self.assertEqual(v["classification"], "VALUE_DESTRUCTIVE")

    def test_insufficient_data(self):
        v = self.az.analyze([make_vault(
            gross_apy_pct=0.0, management_fee_pct=0.0, performance_fee_pct=0.0,
        )])["vaults"][0]
        self.assertEqual(v["classification"], "INSUFFICIENT_DATA")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_insufficient_data_flag(self):
        v = self.az.analyze([make_vault(
            gross_apy_pct=0.0, management_fee_pct=0.0, performance_fee_pct=0.0,
        )])["vaults"][0]
        self.assertIn("INSUFFICIENT_DATA", v["flags"])

    def test_net_negative_flag(self):
        v = self.az.analyze([make_vault(
            gross_apy_pct=2.0, management_fee_pct=5.0, performance_fee_pct=0.0,
        )])["vaults"][0]
        self.assertIn("NET_NEGATIVE", v["flags"])

    def test_above_peer_fees_flag(self):
        # effective load 23.33% > peer 10%
        v = self.az.analyze([make_vault(peer_avg_total_fee_load_pct=10.0)])["vaults"][0]
        self.assertIn("ABOVE_PEER_FEES", v["flags"])

    def test_below_peer_fees_flag(self):
        # effective load 23.33% < peer 40%
        v = self.az.analyze([make_vault(peer_avg_total_fee_load_pct=40.0)])["vaults"][0]
        self.assertIn("BELOW_PEER_FEES", v["flags"])

    def test_high_management_fee_flag(self):
        v = self.az.analyze([make_vault(management_fee_pct=2.5)])["vaults"][0]
        self.assertIn("HIGH_MANAGEMENT_FEE", v["flags"])

    def test_high_performance_fee_flag(self):
        v = self.az.analyze([make_vault(performance_fee_pct=25.0)])["vaults"][0]
        self.assertIn("HIGH_PERFORMANCE_FEE", v["flags"])

    def test_no_hurdle_flag(self):
        v = self.az.analyze([make_vault(performance_fee_pct=20.0,
                                        hurdle_rate_pct=0.0)])["vaults"][0]
        self.assertIn("NO_HURDLE", v["flags"])

    def test_manager_takes_majority_flag(self):
        v = self.az.analyze([make_vault(
            gross_apy_pct=10.0, management_fee_pct=3.0,
            performance_fee_pct=40.0, hurdle_rate_pct=0.0,
        )])["vaults"][0]
        self.assertIn("MANAGER_TAKES_MAJORITY", v["flags"])

    def test_no_peer_flags_when_absent(self):
        vault = make_vault()
        del vault["peer_avg_total_fee_load_pct"]
        v = self.az.analyze([vault])["vaults"][0]
        self.assertNotIn("ABOVE_PEER_FEES", v["flags"])
        self.assertNotIn("BELOW_PEER_FEES", v["flags"])


class TestScoreAndGrade(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_score_bounds(self):
        for mgmt, perf in ((0.0, 0.0), (2.0, 20.0), (5.0, 50.0)):
            v = self.az.analyze([make_vault(
                management_fee_pct=mgmt, performance_fee_pct=perf,
            )])["vaults"][0]
            self.assertGreaterEqual(v["fee_value_score"], 0.0)
            self.assertLessEqual(v["fee_value_score"], 100.0)

    def test_lower_fees_score_higher(self):
        cheap = self.az.analyze([make_vault(
            management_fee_pct=0.5, performance_fee_pct=10.0, hurdle_rate_pct=10.0,
        )])["vaults"][0]
        pricey = self.az.analyze([make_vault(
            gross_apy_pct=10.0, management_fee_pct=3.0,
            performance_fee_pct=40.0, hurdle_rate_pct=0.0,
        )])["vaults"][0]
        self.assertGreater(cheap["fee_value_score"], pricey["fee_value_score"])

    def test_below_peer_boosts_score(self):
        below = self.az.analyze([make_vault(peer_avg_total_fee_load_pct=60.0)])["vaults"][0]
        above = self.az.analyze([make_vault(peer_avg_total_fee_load_pct=5.0)])["vaults"][0]
        self.assertGreater(below["fee_value_score"], above["fee_value_score"])

    def test_grade_thresholds(self):
        self.assertEqual(self.az._grade(95.0), "A")
        self.assertEqual(self.az._grade(90.0), "A")
        self.assertEqual(self.az._grade(80.0), "B")
        self.assertEqual(self.az._grade(75.0), "B")
        self.assertEqual(self.az._grade(65.0), "C")
        self.assertEqual(self.az._grade(60.0), "C")
        self.assertEqual(self.az._grade(50.0), "D")
        self.assertEqual(self.az._grade(45.0), "D")
        self.assertEqual(self.az._grade(10.0), "F")


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_best_worst_counts(self):
        r = self.az.analyze([
            make_vault(name="cheap", management_fee_pct=0.5,
                       performance_fee_pct=10.0, hurdle_rate_pct=10.0),
            make_vault(name="destructive", gross_apy_pct=2.0,
                       management_fee_pct=5.0, performance_fee_pct=0.0),
        ])
        agg = r["aggregates"]
        self.assertEqual(agg["best_vault"]["name"], "cheap")
        self.assertEqual(agg["worst_vault"]["name"], "destructive")
        self.assertGreaterEqual(agg["net_negative_count"], 1)

    def test_overpriced_count(self):
        r = self.az.analyze([
            make_vault(name="op", gross_apy_pct=10.0, management_fee_pct=3.0,
                       performance_fee_pct=40.0, hurdle_rate_pct=0.0),
        ])
        self.assertGreaterEqual(r["aggregates"]["overpriced_count"], 1)

    def test_average_score(self):
        r = self.az.analyze([make_vault(), make_vault(name="B")])
        scores = [v["fee_value_score"] for v in r["vaults"]]
        self.assertAlmostEqual(
            r["aggregates"]["average_fee_value_score"],
            round(sum(scores) / len(scores), 4), places=4
        )


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = ProtocolDeFiVaultFeeStructureBreakevenAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_vault()], config={"write_log": True, "data_dir": d})
            path = os.path.join(d, "vault_fee_structure_breakeven_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_no_log_without_flag(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_vault()], config={"data_dir": d})
            path = os.path.join(d, "vault_fee_structure_breakeven_log.json")
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_caps_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(103):
                self.az.analyze([make_vault()], config={"write_log": True, "data_dir": d})
            with open(os.path.join(d, "vault_fee_structure_breakeven_log.json")) as f:
                self.assertEqual(len(json.load(f)), 100)

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "vault_fee_structure_breakeven_log.json")
            with open(path, "w") as f:
                f.write("garbage")
            self.az.analyze([make_vault()], config={"write_log": True, "data_dir": d})
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)


if __name__ == "__main__":
    unittest.main()
