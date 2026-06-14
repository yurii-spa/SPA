"""
MP-966 Tests: DeFiStablecoinReserveQualityScorer
Run: python3 -m unittest spa_core.tests.test_defi_stablecoin_reserve_quality_scorer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_stablecoin_reserve_quality_scorer import (
    DeFiStablecoinReserveQualityScorer,
)


def make_coin(**kwargs):
    defaults = {
        "name": "USDC",
        "issuer": "Circle",
        "collateralization_ratio_pct": 101.0,
        "cash_pct": 20.0,
        "tbills_pct": 78.0,
        "crypto_pct": 0.0,
        "algo_pct": 0.0,
        "other_pct": 2.0,
        "attestation_age_days": 10.0,
        "attestation_frequency_days": 30.0,
        "redemption_available": True,
        "redemption_fee_pct": 0.0,
        "redemption_time_days": 1.0,
        "largest_custodian_pct": 30.0,
        "regulated": True,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_coin()])
        self.assertEqual(r["stablecoin_count"], 1)
        s = r["stablecoins"][0]
        for k in (
            "backing_quality_score", "grade", "classification", "flags",
            "composition_score", "buffer_score", "attestation_score",
            "redemption_score", "custodian_score", "regulation_score",
        ):
            self.assertIn(k, s)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["stablecoin_count"], 0)
        self.assertIsNone(r["aggregates"]["best_backed"])

    def test_score_in_range(self):
        r = self.az.analyze([make_coin()])
        self.assertGreaterEqual(r["stablecoins"][0]["backing_quality_score"], 0.0)
        self.assertLessEqual(r["stablecoins"][0]["backing_quality_score"], 100.0)

    def test_timestamp_present(self):
        r = self.az.analyze([make_coin()])
        self.assertIn("timestamp", r)


class TestComposition(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_tbills_beat_algo(self):
        good = self.az.analyze([make_coin(tbills_pct=100, cash_pct=0, other_pct=0)])
        bad = self.az.analyze([make_coin(algo_pct=100, tbills_pct=0, cash_pct=0, other_pct=0)])
        self.assertGreater(
            good["stablecoins"][0]["composition_score"],
            bad["stablecoins"][0]["composition_score"],
        )

    def test_all_tbills_high_composition(self):
        r = self.az.analyze([make_coin(tbills_pct=100, cash_pct=0, other_pct=0)])
        self.assertAlmostEqual(r["stablecoins"][0]["composition_score"], 100.0, places=2)

    def test_all_algo_low_composition(self):
        r = self.az.analyze([make_coin(algo_pct=100, tbills_pct=0, cash_pct=0, other_pct=0)])
        self.assertAlmostEqual(r["stablecoins"][0]["composition_score"], 10.0, places=2)

    def test_zero_composition_data(self):
        r = self.az.analyze([make_coin(
            cash_pct=0, tbills_pct=0, crypto_pct=0, algo_pct=0, other_pct=0,
            collateralization_ratio_pct=0,
        )])
        self.assertEqual(r["stablecoins"][0]["composition_score"], 0.0)
        self.assertIn("INSUFFICIENT_DATA", r["stablecoins"][0]["flags"])

    def test_crypto_heavy_flag(self):
        r = self.az.analyze([make_coin(crypto_pct=70, tbills_pct=30, cash_pct=0, other_pct=0)])
        self.assertIn("CRYPTO_HEAVY", r["stablecoins"][0]["flags"])

    def test_algo_dependent_flag(self):
        r = self.az.analyze([make_coin(algo_pct=30, tbills_pct=70, cash_pct=0, other_pct=0)])
        self.assertIn("ALGO_DEPENDENT", r["stablecoins"][0]["flags"])


class TestCollateralBuffer(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_overcollateralized_buffer_positive(self):
        r = self.az.analyze([make_coin(collateralization_ratio_pct=110)])
        self.assertAlmostEqual(r["stablecoins"][0]["collateral_buffer_pct"], 10.0, places=3)

    def test_undercollateralized_flag_and_class(self):
        r = self.az.analyze([make_coin(collateralization_ratio_pct=95)])
        s = r["stablecoins"][0]
        self.assertIn("UNDERCOLLATERALIZED", s["flags"])
        self.assertEqual(s["classification"], "UNDERCOLLATERALIZED")

    def test_higher_collat_higher_buffer_score(self):
        low = self.az.analyze([make_coin(collateralization_ratio_pct=100)])
        high = self.az.analyze([make_coin(collateralization_ratio_pct=130)])
        self.assertGreater(
            high["stablecoins"][0]["buffer_score"],
            low["stablecoins"][0]["buffer_score"],
        )

    def test_buffer_score_clamped(self):
        r = self.az.analyze([make_coin(collateralization_ratio_pct=500)])
        self.assertLessEqual(r["stablecoins"][0]["buffer_score"], 100.0)


class TestAttestation(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_fresh_beats_stale(self):
        fresh = self.az.analyze([make_coin(attestation_age_days=5, attestation_frequency_days=30)])
        stale = self.az.analyze([make_coin(attestation_age_days=300, attestation_frequency_days=30)])
        self.assertGreater(
            fresh["stablecoins"][0]["attestation_score"],
            stale["stablecoins"][0]["attestation_score"],
        )

    def test_stale_attestation_flag(self):
        r = self.az.analyze([make_coin(attestation_age_days=200, attestation_frequency_days=30)])
        self.assertIn("STALE_ATTESTATION", r["stablecoins"][0]["flags"])

    def test_no_stale_flag_when_fresh(self):
        r = self.az.analyze([make_coin(attestation_age_days=10, attestation_frequency_days=30)])
        self.assertNotIn("STALE_ATTESTATION", r["stablecoins"][0]["flags"])


class TestRedemption(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_no_redemption_zero_score_and_flag(self):
        r = self.az.analyze([make_coin(redemption_available=False)])
        s = r["stablecoins"][0]
        self.assertEqual(s["redemption_score"], 0.0)
        self.assertIn("NO_REDEMPTION", s["flags"])

    def test_high_fee_flag(self):
        r = self.az.analyze([make_coin(redemption_fee_pct=0.6)])
        self.assertIn("HIGH_REDEMPTION_FEE", r["stablecoins"][0]["flags"])

    def test_instant_redemption_high_score(self):
        r = self.az.analyze([make_coin(redemption_available=True, redemption_fee_pct=0.0, redemption_time_days=0)])
        self.assertAlmostEqual(r["stablecoins"][0]["redemption_score"], 100.0, places=2)

    def test_slow_redemption_lower_score(self):
        fast = self.az.analyze([make_coin(redemption_time_days=1)])
        slow = self.az.analyze([make_coin(redemption_time_days=7)])
        self.assertGreater(
            fast["stablecoins"][0]["redemption_score"],
            slow["stablecoins"][0]["redemption_score"],
        )


class TestCustodianRegulation(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_custodian_concentration_flag(self):
        r = self.az.analyze([make_coin(largest_custodian_pct=70)])
        self.assertIn("CUSTODIAN_CONCENTRATION", r["stablecoins"][0]["flags"])

    def test_diversified_higher_custodian_score(self):
        conc = self.az.analyze([make_coin(largest_custodian_pct=80)])
        div = self.az.analyze([make_coin(largest_custodian_pct=20)])
        self.assertGreater(
            div["stablecoins"][0]["custodian_score"],
            conc["stablecoins"][0]["custodian_score"],
        )

    def test_unregulated_flag(self):
        r = self.az.analyze([make_coin(regulated=False)])
        self.assertIn("UNREGULATED", r["stablecoins"][0]["flags"])

    def test_regulated_score_higher(self):
        reg = self.az.analyze([make_coin(regulated=True)])
        unreg = self.az.analyze([make_coin(regulated=False)])
        self.assertGreater(
            reg["stablecoins"][0]["regulation_score"],
            unreg["stablecoins"][0]["regulation_score"],
        )


class TestGradeClassification(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_high_quality_grades_well(self):
        r = self.az.analyze([make_coin(
            collateralization_ratio_pct=105, tbills_pct=95, cash_pct=5,
            crypto_pct=0, algo_pct=0, other_pct=0,
            attestation_age_days=5, attestation_frequency_days=30,
            redemption_available=True, redemption_fee_pct=0.0, redemption_time_days=0,
            largest_custodian_pct=20, regulated=True,
        )])
        s = r["stablecoins"][0]
        self.assertIn(s["grade"], ("A", "B"))
        self.assertIn(s["classification"], ("FULLY_BACKED", "WELL_BACKED"))

    def test_poor_quality_grades_low(self):
        r = self.az.analyze([make_coin(
            collateralization_ratio_pct=98, algo_pct=80, tbills_pct=20,
            cash_pct=0, crypto_pct=0, other_pct=0,
            attestation_age_days=400, attestation_frequency_days=180,
            redemption_available=False, largest_custodian_pct=90, regulated=False,
        )])
        s = r["stablecoins"][0]
        self.assertIn(s["grade"], ("D", "F"))

    def test_grade_monotonic(self):
        scores = [95, 80, 65, 50, 20]
        grades = [self.az._grade(s) for s in scores]
        self.assertEqual(grades, ["A", "B", "C", "D", "F"])

    def test_weak_when_algo_majority(self):
        r = self.az.analyze([make_coin(
            collateralization_ratio_pct=120, algo_pct=60, tbills_pct=40,
            cash_pct=0, crypto_pct=0, other_pct=0,
        )])
        self.assertEqual(r["stablecoins"][0]["classification"], "WEAK")


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_best_worst_identified(self):
        good = make_coin(name="GOOD", tbills_pct=100, cash_pct=0, other_pct=0,
                         collateralization_ratio_pct=110, regulated=True)
        bad = make_coin(name="BAD", algo_pct=100, tbills_pct=0, cash_pct=0, other_pct=0,
                        collateralization_ratio_pct=95, regulated=False,
                        redemption_available=False)
        r = self.az.analyze([good, bad])
        self.assertEqual(r["aggregates"]["best_backed"]["name"], "GOOD")
        self.assertEqual(r["aggregates"]["worst_backed"]["name"], "BAD")

    def test_undercollateralized_count(self):
        r = self.az.analyze([
            make_coin(name="A", collateralization_ratio_pct=95),
            make_coin(name="B", collateralization_ratio_pct=110),
        ])
        self.assertEqual(r["aggregates"]["undercollateralized_count"], 1)

    def test_average_in_range(self):
        r = self.az.analyze([make_coin(), make_coin(name="X", algo_pct=50, tbills_pct=50, cash_pct=0, other_pct=0)])
        avg = r["aggregates"]["average_backing_quality_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = DeFiStablecoinReserveQualityScorer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_coin()], {"write_log": True, "data_dir": d})
            path = os.path.join(d, "stablecoin_reserve_quality_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(self.az.LOG_CAP + 10):
                self.az.analyze([make_coin()], {"write_log": True, "data_dir": d})
            with open(os.path.join(d, "stablecoin_reserve_quality_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), self.az.LOG_CAP)

    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_coin()], {"data_dir": d})
            self.assertFalse(os.path.exists(os.path.join(d, "stablecoin_reserve_quality_log.json")))


if __name__ == "__main__":
    unittest.main()
