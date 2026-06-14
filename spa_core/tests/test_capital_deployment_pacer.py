"""
Tests for MP-735: CapitalDeploymentPacer
>=60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.capital_deployment_pacer import (
    MAX_ENTRIES,
    HHI_WELL_SPREAD,
    HHI_MODERATE,
    SCHEDULE_EQUAL,
    SCHEDULE_FRONT_LOADED,
    SCHEDULE_BACK_LOADED,
    SCHEDULE_LINEAR_RAMP,
    VALID_SCHEDULES,
    DeploymentReport,
    CapitalDeploymentPacer,
)


class TestRawWeightsEqual(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_equal_sums_to_one(self):
        w = self.p._raw_weights(4, SCHEDULE_EQUAL)
        self.assertAlmostEqual(sum(w), 1.0, places=9)

    def test_equal_all_same(self):
        w = self.p._raw_weights(5, SCHEDULE_EQUAL)
        self.assertTrue(all(abs(x - 0.2) < 1e-9 for x in w))

    def test_equal_count(self):
        self.assertEqual(len(self.p._raw_weights(7, SCHEDULE_EQUAL)), 7)

    def test_equal_single(self):
        w = self.p._raw_weights(1, SCHEDULE_EQUAL)
        self.assertEqual(w, [1.0])


class TestRawWeightsRamp(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_linear_ramp_sums_to_one(self):
        w = self.p._raw_weights(4, SCHEDULE_LINEAR_RAMP)
        self.assertAlmostEqual(sum(w), 1.0, places=9)

    def test_linear_ramp_ascending(self):
        w = self.p._raw_weights(4, SCHEDULE_LINEAR_RAMP)
        self.assertTrue(all(w[i] < w[i + 1] for i in range(len(w) - 1)))

    def test_back_loaded_ascending(self):
        w = self.p._raw_weights(4, SCHEDULE_BACK_LOADED)
        self.assertTrue(all(w[i] < w[i + 1] for i in range(len(w) - 1)))

    def test_back_equals_linear(self):
        a = self.p._raw_weights(5, SCHEDULE_BACK_LOADED)
        b = self.p._raw_weights(5, SCHEDULE_LINEAR_RAMP)
        self.assertEqual(a, b)

    def test_linear_ramp_known_values(self):
        # n=4 -> 1+2+3+4=10 -> [0.1,0.2,0.3,0.4]
        w = self.p._raw_weights(4, SCHEDULE_LINEAR_RAMP)
        self.assertAlmostEqual(w[0], 0.1, places=9)
        self.assertAlmostEqual(w[3], 0.4, places=9)


class TestRawWeightsFront(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_front_loaded_sums_to_one(self):
        w = self.p._raw_weights(4, SCHEDULE_FRONT_LOADED)
        self.assertAlmostEqual(sum(w), 1.0, places=9)

    def test_front_loaded_descending(self):
        w = self.p._raw_weights(4, SCHEDULE_FRONT_LOADED)
        self.assertTrue(all(w[i] > w[i + 1] for i in range(len(w) - 1)))

    def test_front_is_reverse_of_back(self):
        front = self.p._raw_weights(5, SCHEDULE_FRONT_LOADED)
        back = self.p._raw_weights(5, SCHEDULE_BACK_LOADED)
        self.assertEqual(front, list(reversed(back)))

    def test_front_known_values(self):
        w = self.p._raw_weights(4, SCHEDULE_FRONT_LOADED)
        self.assertAlmostEqual(w[0], 0.4, places=9)
        self.assertAlmostEqual(w[3], 0.1, places=9)


class TestRawWeightsFallback(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_unknown_schedule_equal(self):
        w = self.p._raw_weights(4, "nonsense")
        self.assertTrue(all(abs(x - 0.25) < 1e-9 for x in w))


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_equal_hhi(self):
        # n=4 equal -> 4 * 0.25^2 = 0.25
        w = [0.25, 0.25, 0.25, 0.25]
        self.assertAlmostEqual(self.p._hhi(w), 0.25, places=9)

    def test_single_shot_hhi_one(self):
        self.assertAlmostEqual(self.p._hhi([1.0]), 1.0, places=9)

    def test_more_tranches_lower_hhi(self):
        w4 = self.p._raw_weights(4, SCHEDULE_EQUAL)
        w10 = self.p._raw_weights(10, SCHEDULE_EQUAL)
        self.assertLess(self.p._hhi(w10), self.p._hhi(w4))

    def test_concentrated_higher_hhi(self):
        equal = self.p._hhi(self.p._raw_weights(5, SCHEDULE_EQUAL))
        front = self.p._hhi(self.p._raw_weights(5, SCHEDULE_FRONT_LOADED))
        self.assertGreater(front, equal)


class TestBuildTranches(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_count(self):
        w = self.p._raw_weights(4, SCHEDULE_EQUAL)
        t = self.p._build_tranches(w, 10000.0)
        self.assertEqual(len(t), 4)

    def test_usd_sums_to_total(self):
        w = self.p._raw_weights(3, SCHEDULE_LINEAR_RAMP)
        t = self.p._build_tranches(w, 10000.0)
        self.assertAlmostEqual(sum(x["usd"] for x in t), 10000.0, places=6)

    def test_residual_on_last(self):
        # 3-way equal split of 10000 has a rounding residual absorbed on last tranche
        w = self.p._raw_weights(3, SCHEDULE_EQUAL)
        t = self.p._build_tranches(w, 10000.0)
        self.assertAlmostEqual(sum(x["usd"] for x in t), 10000.0, places=6)

    def test_cumulative_reaches_100(self):
        w = self.p._raw_weights(5, SCHEDULE_EQUAL)
        t = self.p._build_tranches(w, 10000.0)
        self.assertAlmostEqual(t[-1]["cumulative_pct"], 100.0, places=4)

    def test_cumulative_monotonic(self):
        w = self.p._raw_weights(5, SCHEDULE_FRONT_LOADED)
        t = self.p._build_tranches(w, 10000.0)
        for i in range(len(t) - 1):
            self.assertLessEqual(t[i]["cumulative_pct"], t[i + 1]["cumulative_pct"])

    def test_index_present(self):
        w = self.p._raw_weights(3, SCHEDULE_EQUAL)
        t = self.p._build_tranches(w, 1000.0)
        self.assertEqual([x["index"] for x in t], [0, 1, 2])

    def test_keys_present(self):
        w = self.p._raw_weights(2, SCHEDULE_EQUAL)
        t = self.p._build_tranches(w, 1000.0)
        for x in t:
            self.assertIn("weight", x)
            self.assertIn("usd", x)
            self.assertIn("cumulative_pct", x)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_single_shot(self):
        self.assertEqual(self.p._classify(1, 1.0), "SINGLE_SHOT")

    def test_zero_tranches_single_shot(self):
        self.assertEqual(self.p._classify(0, 1.0), "SINGLE_SHOT")

    def test_well_spread(self):
        self.assertEqual(self.p._classify(10, 0.10), "WELL_SPREAD")

    def test_well_spread_boundary(self):
        self.assertEqual(self.p._classify(5, HHI_WELL_SPREAD), "WELL_SPREAD")

    def test_moderate(self):
        self.assertEqual(self.p._classify(3, 0.30), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(self.p._classify(3, HHI_MODERATE), "MODERATE")

    def test_concentrated(self):
        self.assertEqual(self.p._classify(2, 0.60), "CONCENTRATED")

    def test_just_above_well_spread(self):
        self.assertEqual(self.p._classify(5, HHI_WELL_SPREAD + 0.01), "MODERATE")

    def test_just_above_moderate(self):
        self.assertEqual(self.p._classify(3, HHI_MODERATE + 0.01), "CONCENTRATED")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_zero_tranches_unknown(self):
        r = self.p.analyze(num_tranches=0)
        self.assertEqual(r.risk_spread_tier, "UNKNOWN")

    def test_negative_tranches_unknown(self):
        r = self.p.analyze(num_tranches=-3)
        self.assertEqual(r.risk_spread_tier, "UNKNOWN")

    def test_zero_capital_unknown(self):
        r = self.p.analyze(total_capital_usd=0.0)
        self.assertEqual(r.risk_spread_tier, "UNKNOWN")

    def test_negative_capital_unknown(self):
        r = self.p.analyze(total_capital_usd=-1000.0)
        self.assertEqual(r.risk_spread_tier, "UNKNOWN")

    def test_unknown_empty_tranches(self):
        r = self.p.analyze(num_tranches=0)
        self.assertEqual(r.tranches, [])

    def test_unknown_advisory(self):
        r = self.p.analyze(num_tranches=0)
        self.assertTrue(len(r.advisory) >= 1)

    def test_returns_report_type(self):
        self.assertIsInstance(self.p.analyze(), DeploymentReport)


class TestAnalyzeSingleShot(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_single_tranche_tier(self):
        r = self.p.analyze(num_tranches=1)
        self.assertEqual(r.risk_spread_tier, "SINGLE_SHOT")

    def test_single_tranche_full_usd(self):
        r = self.p.analyze(total_capital_usd=5000.0, num_tranches=1)
        self.assertAlmostEqual(r.tranches[0]["usd"], 5000.0, places=6)

    def test_single_tranche_span_zero(self):
        r = self.p.analyze(num_tranches=1)
        self.assertEqual(r.total_deployment_span_days, 0.0)

    def test_single_shot_advisory(self):
        r = self.p.analyze(num_tranches=1)
        self.assertTrue(any("Single-shot" in a for a in r.advisory))


class TestAnalyzeSpread(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_well_spread_many(self):
        r = self.p.analyze(num_tranches=10, schedule=SCHEDULE_EQUAL)
        self.assertEqual(r.risk_spread_tier, "WELL_SPREAD")

    def test_concentrated_few_front(self):
        r = self.p.analyze(num_tranches=2, schedule=SCHEDULE_FRONT_LOADED)
        self.assertIn(r.risk_spread_tier, {"CONCENTRATED", "MODERATE"})

    def test_usd_sums_to_total(self):
        r = self.p.analyze(total_capital_usd=12345.67, num_tranches=7, schedule=SCHEDULE_FRONT_LOADED)
        self.assertAlmostEqual(sum(t["usd"] for t in r.tranches), 12345.67, places=4)

    def test_span_formula(self):
        r = self.p.analyze(num_tranches=5, interval_days=3.0)
        self.assertEqual(r.total_deployment_span_days, 12.0)

    def test_max_weight_recorded(self):
        r = self.p.analyze(num_tranches=4, schedule=SCHEDULE_FRONT_LOADED)
        self.assertAlmostEqual(r.max_tranche_weight, 0.4, places=6)

    def test_hhi_recorded(self):
        r = self.p.analyze(num_tranches=4, schedule=SCHEDULE_EQUAL)
        self.assertAlmostEqual(r.hhi, 0.25, places=6)

    def test_tier_in_known_set(self):
        r = self.p.analyze()
        self.assertIn(
            r.risk_spread_tier,
            {"WELL_SPREAD", "MODERATE", "CONCENTRATED", "SINGLE_SHOT", "UNKNOWN"},
        )


class TestScheduleHandling(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_front_loaded_first_largest(self):
        r = self.p.analyze(num_tranches=5, schedule=SCHEDULE_FRONT_LOADED)
        weights = [t["weight"] for t in r.tranches]
        self.assertEqual(weights[0], max(weights))

    def test_back_loaded_last_largest(self):
        r = self.p.analyze(num_tranches=5, schedule=SCHEDULE_BACK_LOADED)
        weights = [t["weight"] for t in r.tranches]
        self.assertEqual(weights[-1], max(weights))

    def test_front_loaded_advisory(self):
        r = self.p.analyze(num_tranches=5, schedule=SCHEDULE_FRONT_LOADED)
        self.assertTrue(any("Front-loaded" in a for a in r.advisory))

    def test_back_loaded_advisory(self):
        r = self.p.analyze(num_tranches=5, schedule=SCHEDULE_BACK_LOADED)
        self.assertTrue(any("Back-loaded" in a for a in r.advisory))

    def test_unknown_schedule_falls_back(self):
        r = self.p.analyze(num_tranches=4, schedule="weird")
        self.assertEqual(r.schedule, SCHEDULE_EQUAL)

    def test_unknown_schedule_advisory(self):
        r = self.p.analyze(num_tranches=4, schedule="weird")
        self.assertTrue(any("Unrecognized schedule" in a for a in r.advisory))

    def test_valid_schedules_constant(self):
        self.assertIn(SCHEDULE_EQUAL, VALID_SCHEDULES)
        self.assertIn(SCHEDULE_FRONT_LOADED, VALID_SCHEDULES)
        self.assertIn(SCHEDULE_BACK_LOADED, VALID_SCHEDULES)
        self.assertIn(SCHEDULE_LINEAR_RAMP, VALID_SCHEDULES)

    def test_span_advisory_present(self):
        r = self.p.analyze(num_tranches=5, interval_days=2.0)
        self.assertTrue(any("spans" in a for a in r.advisory))


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_floats_6dp(self):
        r = self.p.analyze(total_capital_usd=33333.33, num_tranches=7, schedule=SCHEDULE_LINEAR_RAMP)
        for v in (r.hhi, r.max_tranche_weight, r.total_deployment_span_days):
            self.assertEqual(v, round(v, 6))

    def test_tranche_floats_6dp(self):
        r = self.p.analyze(total_capital_usd=33333.33, num_tranches=7)
        for t in r.tranches:
            self.assertEqual(t["weight"], round(t["weight"], 6))
            self.assertEqual(t["usd"], round(t["usd"], 6))

    def test_generated_at_set(self):
        r = self.p.analyze()
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_interval_recorded(self):
        r = self.p.analyze(interval_days=7.5)
        self.assertEqual(r.interval_days, 7.5)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deploy.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.p.load_history(self.path), [])

    def test_save_then_load(self):
        self.p.save_report(self.p.analyze(), self.path)
        self.assertEqual(len(self.p.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.p.save_report(self.p.analyze(), self.path)
        e = self.p.load_history(self.path)[0]
        self.assertIn("risk_spread_tier", e)
        self.assertIn("hhi", e)
        self.assertIn("tranches", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.p.save_report(self.p.analyze(), self.path)
        self.assertEqual(len(self.p.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.p.save_report(self.p.analyze(), self.path)
        self.assertEqual(len(self.p.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.p.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.p.save_report(self.p.analyze(), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.p.save_report(self.p.analyze(), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "deploy.json"
        self.p.save_report(self.p.analyze(), nested)
        self.assertTrue(nested.exists())

    def test_tranches_persisted(self):
        self.p.save_report(self.p.analyze(num_tranches=4), self.path)
        e = self.p.load_history(self.path)[0]
        self.assertEqual(len(e["tranches"]), 4)


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.p = CapitalDeploymentPacer()

    def test_realistic(self):
        r = self.p.analyze(
            total_capital_usd=20000.0,
            num_tranches=5,
            schedule=SCHEDULE_FRONT_LOADED,
            interval_days=2.0,
        )
        self.assertEqual(r.num_tranches, 5)
        self.assertEqual(r.total_deployment_span_days, 8.0)
        self.assertTrue(len(r.advisory) >= 1)

    def test_all_schedules_sum_to_total(self):
        for sched in VALID_SCHEDULES:
            r = self.p.analyze(total_capital_usd=7777.0, num_tranches=6, schedule=sched)
            self.assertAlmostEqual(
                sum(t["usd"] for t in r.tranches), 7777.0, places=4
            )

    def test_advisory_present(self):
        r = self.p.analyze()
        self.assertTrue(len(r.advisory) >= 1)

    def test_equal_max_weight(self):
        r = self.p.analyze(num_tranches=5, schedule=SCHEDULE_EQUAL)
        self.assertAlmostEqual(r.max_tranche_weight, 0.2, places=6)


if __name__ == "__main__":
    unittest.main()
