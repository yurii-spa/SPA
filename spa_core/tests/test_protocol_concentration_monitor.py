"""
Tests for MP-678: ProtocolConcentrationMonitor
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.protocol_concentration_monitor import (
    DEFAULT_SINGLE_PROTOCOL_CAP_PCT,
    HHI_CONCENTRATED,
    HHI_DIVERSIFIED,
    HHI_MODERATE,
    MAX_ENTRIES,
    ConcentrationReport,
    PositionExposure,
    ProtocolConcentrationMonitor,
)


def _exp(protocol="aave_v3", value_usd=100_000.0) -> PositionExposure:
    return PositionExposure(protocol=protocol, value_usd=value_usd)


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_empty(self):
        self.assertEqual(self.m._aggregate([]), {})

    def test_single(self):
        self.assertEqual(self.m._aggregate([_exp("a", 100)]), {"a": 100})

    def test_sum_same_protocol(self):
        agg = self.m._aggregate([_exp("a", 100), _exp("a", 50)])
        self.assertEqual(agg, {"a": 150})

    def test_distinct(self):
        agg = self.m._aggregate([_exp("a", 100), _exp("b", 50)])
        self.assertEqual(agg, {"a": 100, "b": 50})

    def test_ignores_zero(self):
        self.assertEqual(self.m._aggregate([_exp("a", 0)]), {})

    def test_ignores_negative(self):
        self.assertEqual(self.m._aggregate([_exp("a", -10)]), {})

    def test_mixed_signs(self):
        agg = self.m._aggregate([_exp("a", 100), _exp("a", -10)])
        self.assertEqual(agg, {"a": 100})


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_single_protocol_max(self):
        self.assertEqual(self.m._hhi([100.0]), 10000.0)

    def test_two_equal(self):
        self.assertEqual(self.m._hhi([50.0, 50.0]), 5000.0)

    def test_four_equal(self):
        self.assertEqual(self.m._hhi([25.0, 25.0, 25.0, 25.0]), 2500.0)

    def test_ten_equal(self):
        self.assertEqual(self.m._hhi([10.0] * 10), 1000.0)

    def test_rounding(self):
        # 33.333333 -> squared sums ~ 3333.33...
        val = self.m._hhi([100.0 / 3] * 3)
        self.assertAlmostEqual(val, 3333.333333, places=3)


class TestEffectiveProtocols(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_single(self):
        self.assertEqual(self.m._effective_protocols([1.0]), 1.0)

    def test_two_equal(self):
        self.assertEqual(self.m._effective_protocols([0.5, 0.5]), 2.0)

    def test_four_equal(self):
        self.assertEqual(self.m._effective_protocols([0.25] * 4), 4.0)

    def test_empty(self):
        self.assertEqual(self.m._effective_protocols([]), 0.0)

    def test_skewed_less_than_count(self):
        eff = self.m._effective_protocols([0.9, 0.1])
        self.assertLess(eff, 2.0)
        self.assertGreater(eff, 1.0)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_diversified(self):
        self.assertEqual(self.m._classify(1000.0), "DIVERSIFIED")

    def test_diversified_boundary_below(self):
        self.assertEqual(self.m._classify(HHI_DIVERSIFIED - 0.01), "DIVERSIFIED")

    def test_moderate_at_boundary(self):
        self.assertEqual(self.m._classify(HHI_DIVERSIFIED), "MODERATE")

    def test_moderate(self):
        self.assertEqual(self.m._classify(2000.0), "MODERATE")

    def test_concentrated_at_boundary(self):
        self.assertEqual(self.m._classify(HHI_MODERATE), "CONCENTRATED")

    def test_concentrated(self):
        self.assertEqual(self.m._classify(4000.0), "CONCENTRATED")

    def test_critical_at_boundary(self):
        self.assertEqual(self.m._classify(HHI_CONCENTRATED), "CRITICAL")

    def test_critical(self):
        self.assertEqual(self.m._classify(10000.0), "CRITICAL")


class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_empty_list(self):
        r = self.m.analyze([])
        self.assertEqual(r.concentration_level, "UNKNOWN")
        self.assertEqual(r.total_value_usd, 0.0)
        self.assertEqual(r.num_protocols, 0)
        self.assertIsNone(r.max_exposure_protocol)
        self.assertEqual(r.breaches, [])

    def test_all_zero(self):
        r = self.m.analyze([_exp("a", 0), _exp("b", 0)])
        self.assertEqual(r.concentration_level, "UNKNOWN")

    def test_all_negative(self):
        r = self.m.analyze([_exp("a", -5)])
        self.assertEqual(r.concentration_level, "UNKNOWN")

    def test_empty_has_advisory(self):
        r = self.m.analyze([])
        self.assertTrue(any("No positive" in a for a in r.advisory))

    def test_empty_has_timestamp(self):
        r = self.m.analyze([])
        self.assertTrue(r.generated_at.endswith("Z"))


class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_single_critical(self):
        r = self.m.analyze([_exp("a", 100_000)])
        self.assertEqual(r.concentration_level, "CRITICAL")
        self.assertEqual(r.hhi, 10000.0)
        self.assertEqual(r.num_protocols, 1)
        self.assertEqual(r.max_exposure_protocol, "a")
        self.assertEqual(r.max_exposure_pct, 100.0)

    def test_single_breach(self):
        r = self.m.analyze([_exp("a", 100_000)])
        self.assertIn("a", r.breaches)

    def test_single_effective_one(self):
        r = self.m.analyze([_exp("a", 100_000)])
        self.assertEqual(r.effective_protocols, 1.0)


class TestAnalyzeDiversified(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_ten_equal_diversified(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(10)]
        r = self.m.analyze(exps)
        self.assertEqual(r.concentration_level, "DIVERSIFIED")
        self.assertEqual(r.hhi, 1000.0)
        self.assertEqual(r.num_protocols, 10)

    def test_ten_equal_no_breach(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(10)]
        r = self.m.analyze(exps)
        self.assertEqual(r.breaches, [])

    def test_ten_equal_effective(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(10)]
        r = self.m.analyze(exps)
        self.assertAlmostEqual(r.effective_protocols, 10.0, places=4)

    def test_max_pct_ten_equal(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(10)]
        r = self.m.analyze(exps)
        self.assertAlmostEqual(r.max_exposure_pct, 10.0, places=4)


class TestAnalyzeCap(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_default_cap_value(self):
        self.assertEqual(DEFAULT_SINGLE_PROTOCOL_CAP_PCT, 25.0)

    def test_breach_above_cap(self):
        # a=60%, b=40% -> both breach 25%
        r = self.m.analyze([_exp("a", 60), _exp("b", 40)])
        self.assertEqual(r.breaches, ["a", "b"])

    def test_breaches_sorted(self):
        r = self.m.analyze([_exp("zeta", 60), _exp("alpha", 40)])
        self.assertEqual(r.breaches, ["alpha", "zeta"])

    def test_no_breach_under_cap(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(5)]  # 20% each
        r = self.m.analyze(exps)
        self.assertEqual(r.breaches, [])

    def test_exactly_at_cap_no_breach(self):
        # 25% exactly should NOT breach (> cap, not >=)
        exps = [_exp(f"p{i}", 25_000) for i in range(4)]
        r = self.m.analyze(exps)
        self.assertEqual(r.breaches, [])

    def test_custom_cap(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(5)]  # 20% each
        r = self.m.analyze(exps, single_protocol_cap_pct=15.0)
        self.assertEqual(len(r.breaches), 5)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_critical_advisory(self):
        r = self.m.analyze([_exp("a", 100_000)])
        self.assertTrue(any("CRITICAL" in a for a in r.advisory))

    def test_concentrated_advisory(self):
        # hhi ~ 4000 between 2500 and 5000: a=50,b=30,c=20 -> 2500+900+400=3800
        r = self.m.analyze([_exp("a", 50), _exp("b", 30), _exp("c", 20)])
        self.assertEqual(r.concentration_level, "CONCENTRATED")
        self.assertTrue(any("concentrated" in a.lower() for a in r.advisory))

    def test_breach_advisory_mentions_protocol(self):
        r = self.m.analyze([_exp("a", 60), _exp("b", 40)])
        self.assertTrue(any("'a'" in a or "'b'" in a for a in r.advisory))

    def test_diversified_within_cap_note(self):
        exps = [_exp(f"p{i}", 10_000) for i in range(10)]
        r = self.m.analyze(exps)
        self.assertTrue(any("within" in a for a in r.advisory))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "conc.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing(self):
        self.assertEqual(self.m.load_history(self.path), [])

    def test_save_then_load(self):
        r = self.m.analyze([_exp("a", 100)])
        self.m.save_report(r, self.path)
        hist = self.m.load_history(self.path)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["concentration_level"], "CRITICAL")

    def test_append(self):
        for _ in range(3):
            self.m.save_report(self.m.analyze([_exp("a", 100)]), self.path)
        self.assertEqual(len(self.m.load_history(self.path)), 3)

    def test_ring_buffer(self):
        for i in range(MAX_ENTRIES + 10):
            self.m.save_report(self.m.analyze([_exp("a", 100 + i)]), self.path)
        self.assertEqual(len(self.m.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("not json{")
        self.assertEqual(self.m.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.m.save_report(self.m.analyze([_exp("a", 100)]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_atomic_valid_json(self):
        self.m.save_report(self.m.analyze([_exp("a", 100)]), self.path)
        with open(self.path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_entry_keys(self):
        self.m.save_report(self.m.analyze([_exp("a", 100)]), self.path)
        entry = self.m.load_history(self.path)[0]
        for k in ("hhi", "effective_protocols", "breaches", "advisory"):
            self.assertIn(k, entry)


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.m = ProtocolConcentrationMonitor()

    def test_total_value(self):
        r = self.m.analyze([_exp("a", 60_000), _exp("b", 40_000)])
        self.assertEqual(r.total_value_usd, 100_000.0)

    def test_max_protocol_identified(self):
        r = self.m.analyze([_exp("a", 60_000), _exp("b", 40_000)])
        self.assertEqual(r.max_exposure_protocol, "a")

    def test_report_type(self):
        r = self.m.analyze([_exp("a", 100)])
        self.assertIsInstance(r, ConcentrationReport)

    def test_aggregation_in_analyze(self):
        # same protocol twice should aggregate to one
        r = self.m.analyze([_exp("a", 50), _exp("a", 50)])
        self.assertEqual(r.num_protocols, 1)
        self.assertEqual(r.total_value_usd, 100.0)

    def test_moderate_band(self):
        # 5 protocols: 30/25/20/15/10 -> 900+625+400+225+100=2250 MODERATE
        r = self.m.analyze(
            [_exp("a", 30), _exp("b", 25), _exp("c", 20), _exp("d", 15), _exp("e", 10)]
        )
        self.assertEqual(r.concentration_level, "MODERATE")

    def test_pct_sums_to_100(self):
        r = self.m.analyze([_exp("a", 60), _exp("b", 40)])
        # max pct is 60
        self.assertAlmostEqual(r.max_exposure_pct, 60.0, places=4)


if __name__ == "__main__":
    unittest.main()
