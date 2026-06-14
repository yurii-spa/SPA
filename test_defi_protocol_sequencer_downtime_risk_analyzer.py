"""
MP-1024 Tests: DeFiProtocolSequencerDowntimeRiskAnalyzer
>=45 tests, unittest only, stdlib only.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_sequencer_downtime_risk_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_sequencer_downtime_risk_analyzer import (
    DeFiProtocolSequencerDowntimeRiskAnalyzer,
    _atomic_write,
    _load_ring_buffer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pos(
    name="POS1",
    protocol="Aave V3",
    chain="Arbitrum",
    is_single_sequencer=True,
    has_grace_period=True,
    grace_period_minutes=30,
    historical_downtime_minutes_30d=30,
    max_single_outage_minutes=60,
    health_factor=1.5,
    has_force_inclusion=True,
    force_inclusion_delay_hours=24,
    uptime_feed_integrated=True,
    decentralized_sequencer_roadmap=True,
):
    return {
        "name": name,
        "protocol": protocol,
        "chain": chain,
        "is_single_sequencer": is_single_sequencer,
        "has_grace_period": has_grace_period,
        "grace_period_minutes": grace_period_minutes,
        "historical_downtime_minutes_30d": historical_downtime_minutes_30d,
        "max_single_outage_minutes": max_single_outage_minutes,
        "health_factor": health_factor,
        "has_force_inclusion": has_force_inclusion,
        "force_inclusion_delay_hours": force_inclusion_delay_hours,
        "uptime_feed_integrated": uptime_feed_integrated,
        "decentralized_sequencer_roadmap": decentralized_sequencer_roadmap,
    }


def _resilient_pos(name="Resilient"):
    return _make_pos(
        name=name,
        is_single_sequencer=False,
        has_grace_period=True,
        historical_downtime_minutes_30d=0,
        max_single_outage_minutes=0,
        health_factor=5.0,
        has_force_inclusion=True,
        force_inclusion_delay_hours=1,
        uptime_feed_integrated=True,
        decentralized_sequencer_roadmap=True,
    )


def _critical_pos(name="Critical"):
    return _make_pos(
        name=name,
        is_single_sequencer=True,
        has_grace_period=False,
        historical_downtime_minutes_30d=900,
        max_single_outage_minutes=400,
        health_factor=1.01,
        has_force_inclusion=False,
        force_inclusion_delay_hours=0,
        uptime_feed_integrated=False,
        decentralized_sequencer_roadmap=False,
    )


class TestAtomicWrite(unittest.TestCase):
    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [{"a": 1}])
            self.assertTrue(os.path.exists(path))

    def test_write_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, {"key": "value"})

    def test_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, [1])
            _atomic_write(path, [2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [2, 3])

    def test_write_creates_missing_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub1", "sub2", "data.json")
            _atomic_write(path, {"ok": True})
            self.assertTrue(os.path.exists(path))


class TestLoadRingBuffer(unittest.TestCase):
    def test_load_empty_on_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            result = _load_ring_buffer(os.path.join(d, "missing.json"), 100)
            self.assertEqual(result, [])

    def test_load_respects_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "buf.json")
            _atomic_write(path, list(range(200)))
            result = _load_ring_buffer(path, 50)
            self.assertEqual(len(result), 50)

    def test_load_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("not json")
            self.assertEqual(_load_ring_buffer(path, 10), [])


class TestDowntimeFrequencyScore(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_zero_downtime(self):
        self.assertEqual(
            self.an._downtime_frequency_score(_make_pos(historical_downtime_minutes_30d=0)),
            0.0)

    def test_negative_downtime_clipped(self):
        score = self.an._downtime_frequency_score(
            _make_pos(historical_downtime_minutes_30d=-50))
        self.assertEqual(score, 0.0)

    def test_saturates_at_720(self):
        score = self.an._downtime_frequency_score(
            _make_pos(historical_downtime_minutes_30d=720))
        self.assertAlmostEqual(score, 100.0)

    def test_above_720_capped(self):
        score = self.an._downtime_frequency_score(
            _make_pos(historical_downtime_minutes_30d=5000))
        self.assertLessEqual(score, 100.0)

    def test_monotonic(self):
        s1 = self.an._downtime_frequency_score(
            _make_pos(historical_downtime_minutes_30d=100))
        s2 = self.an._downtime_frequency_score(
            _make_pos(historical_downtime_minutes_30d=300))
        self.assertGreater(s2, s1)

    def test_missing_field_zero(self):
        self.assertEqual(self.an._downtime_frequency_score({}), 0.0)


class TestLiquidationExposureScore(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_high_hf_low_exposure(self):
        score = self.an._liquidation_exposure_score(
            _make_pos(health_factor=5.0, is_single_sequencer=False, has_grace_period=True))
        self.assertEqual(score, 0.0)

    def test_near_one_high_exposure(self):
        score = self.an._liquidation_exposure_score(
            _make_pos(health_factor=1.0, is_single_sequencer=False, has_grace_period=True))
        self.assertGreater(score, 90.0)

    def test_hf_zero_max_exposure(self):
        score = self.an._liquidation_exposure_score(
            _make_pos(health_factor=0.0))
        self.assertEqual(score, 100.0)

    def test_negative_hf_max(self):
        score = self.an._liquidation_exposure_score(
            _make_pos(health_factor=-1.0))
        self.assertEqual(score, 100.0)

    def test_missing_hf_baseline(self):
        pos = _make_pos()
        del pos["health_factor"]
        pos["is_single_sequencer"] = False
        pos["has_grace_period"] = True
        score = self.an._liquidation_exposure_score(pos)
        self.assertAlmostEqual(score, 50.0)

    def test_amplified_by_single_sequencer_no_grace(self):
        base = self.an._liquidation_exposure_score(
            _make_pos(health_factor=2.0, is_single_sequencer=False, has_grace_period=True))
        amp = self.an._liquidation_exposure_score(
            _make_pos(health_factor=2.0, is_single_sequencer=True, has_grace_period=False))
        self.assertGreater(amp, base)

    def test_monotonic_in_hf(self):
        s_low = self.an._liquidation_exposure_score(_make_pos(health_factor=1.2))
        s_high = self.an._liquidation_exposure_score(_make_pos(health_factor=2.5))
        self.assertGreater(s_low, s_high)

    def test_clipped_0_100(self):
        score = self.an._liquidation_exposure_score(
            _make_pos(health_factor=1.0, is_single_sequencer=True, has_grace_period=False))
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)


class TestEscapeHatchScore(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_no_protection(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=False, uptime_feed_integrated=False,
                      decentralized_sequencer_roadmap=False))
        self.assertEqual(score, 0.0)

    def test_uptime_feed_only(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=False, uptime_feed_integrated=True,
                      decentralized_sequencer_roadmap=False))
        self.assertAlmostEqual(score, 30.0)

    def test_roadmap_only(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=False, uptime_feed_integrated=False,
                      decentralized_sequencer_roadmap=True))
        self.assertAlmostEqual(score, 20.0)

    def test_force_inclusion_zero_delay_full(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=True, force_inclusion_delay_hours=0,
                      uptime_feed_integrated=False, decentralized_sequencer_roadmap=False))
        self.assertAlmostEqual(score, 50.0)

    def test_long_delay_reduces_force_inclusion(self):
        short = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=True, force_inclusion_delay_hours=0,
                      uptime_feed_integrated=False, decentralized_sequencer_roadmap=False))
        long = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=True, force_inclusion_delay_hours=240,
                      uptime_feed_integrated=False, decentralized_sequencer_roadmap=False))
        self.assertGreater(short, long)

    def test_all_protection_high(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=True, force_inclusion_delay_hours=0,
                      uptime_feed_integrated=True, decentralized_sequencer_roadmap=True))
        self.assertAlmostEqual(score, 100.0)

    def test_capped_at_100(self):
        score = self.an._escape_hatch_score(
            _make_pos(has_force_inclusion=True, force_inclusion_delay_hours=0,
                      uptime_feed_integrated=True, decentralized_sequencer_roadmap=True))
        self.assertLessEqual(score, 100.0)


class TestCentralizationScore(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_single_seq_no_roadmap_max(self):
        score = self.an._centralization_score(
            _make_pos(is_single_sequencer=True, decentralized_sequencer_roadmap=False))
        self.assertAlmostEqual(score, 100.0)

    def test_single_seq_with_roadmap(self):
        score = self.an._centralization_score(
            _make_pos(is_single_sequencer=True, decentralized_sequencer_roadmap=True))
        self.assertAlmostEqual(score, 60.0)

    def test_no_single_no_roadmap(self):
        score = self.an._centralization_score(
            _make_pos(is_single_sequencer=False, decentralized_sequencer_roadmap=False))
        self.assertAlmostEqual(score, 40.0)

    def test_decentralized_with_roadmap_zero(self):
        score = self.an._centralization_score(
            _make_pos(is_single_sequencer=False, decentralized_sequencer_roadmap=True))
        self.assertEqual(score, 0.0)


class TestNetDowntimeRiskScore(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_resilient_low(self):
        score = self.an._net_downtime_risk_score(_resilient_pos())
        self.assertLess(score, 20.0)

    def test_critical_high(self):
        score = self.an._net_downtime_risk_score(_critical_pos())
        self.assertGreaterEqual(score, 60.0)

    def test_clipped_0(self):
        score = self.an._net_downtime_risk_score(_resilient_pos())
        self.assertGreaterEqual(score, 0.0)

    def test_clipped_100(self):
        score = self.an._net_downtime_risk_score(_critical_pos())
        self.assertLessEqual(score, 100.0)

    def test_escape_hatch_reduces_risk(self):
        with_hatch = _critical_pos()
        with_hatch["has_force_inclusion"] = True
        with_hatch["uptime_feed_integrated"] = True
        with_hatch["decentralized_sequencer_roadmap"] = True
        s_no = self.an._net_downtime_risk_score(_critical_pos())
        s_yes = self.an._net_downtime_risk_score(with_hatch)
        self.assertLess(s_yes, s_no)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_resilient(self):
        self.assertEqual(self.an._classification(10), "RESILIENT")

    def test_low_risk(self):
        self.assertEqual(self.an._classification(25), "LOW_RISK")

    def test_moderate_risk(self):
        self.assertEqual(self.an._classification(45), "MODERATE_RISK")

    def test_high_risk(self):
        self.assertEqual(self.an._classification(65), "HIGH_RISK")

    def test_critical_exposure(self):
        self.assertEqual(self.an._classification(85), "CRITICAL_EXPOSURE")


class TestGrade(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_grade_a(self):
        self.assertEqual(self.an._grade(10), "A")

    def test_grade_b(self):
        self.assertEqual(self.an._grade(30), "B")

    def test_grade_c(self):
        self.assertEqual(self.an._grade(50), "C")

    def test_grade_d(self):
        self.assertEqual(self.an._grade(70), "D")

    def test_grade_f(self):
        self.assertEqual(self.an._grade(90), "F")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer()

    def test_single_sequencer_flag(self):
        self.assertIn("SINGLE_SEQUENCER",
                      self.an._compute_flags(_make_pos(is_single_sequencer=True)))

    def test_no_grace_period_flag(self):
        self.assertIn("NO_GRACE_PERIOD",
                      self.an._compute_flags(_make_pos(has_grace_period=False)))

    def test_near_liquidation_flag(self):
        self.assertIn("NEAR_LIQUIDATION",
                      self.an._compute_flags(_make_pos(health_factor=1.05)))

    def test_no_near_liquidation_when_hf_zero(self):
        # hf must be > 0 for the flag
        self.assertNotIn("NEAR_LIQUIDATION",
                         self.an._compute_flags(_make_pos(health_factor=0.0)))

    def test_no_escape_hatch_flag(self):
        flags = self.an._compute_flags(
            _make_pos(has_force_inclusion=False, uptime_feed_integrated=False,
                      decentralized_sequencer_roadmap=False))
        self.assertIn("NO_ESCAPE_HATCH", flags)

    def test_frequent_downtime_flag(self):
        self.assertIn("FREQUENT_DOWNTIME",
                      self.an._compute_flags(_make_pos(historical_downtime_minutes_30d=90)))

    def test_no_frequent_downtime_below_threshold(self):
        self.assertNotIn("FREQUENT_DOWNTIME",
                         self.an._compute_flags(_make_pos(historical_downtime_minutes_30d=30)))

    def test_long_max_outage_flag(self):
        self.assertIn("LONG_MAX_OUTAGE",
                      self.an._compute_flags(_make_pos(max_single_outage_minutes=200)))

    def test_uptime_feed_protected_flag(self):
        self.assertIn("UPTIME_FEED_PROTECTED",
                      self.an._compute_flags(_make_pos(uptime_feed_integrated=True)))

    def test_force_inclusion_available_flag(self):
        self.assertIn("FORCE_INCLUSION_AVAILABLE",
                      self.an._compute_flags(_make_pos(has_force_inclusion=True)))

    def test_decentralization_planned_flag(self):
        self.assertIn("DECENTRALIZATION_PLANNED",
                      self.an._compute_flags(_make_pos(decentralized_sequencer_roadmap=True)))

    def test_insufficient_data_flag(self):
        self.assertIn("INSUFFICIENT_DATA", self.an._compute_flags({"name": "X"}))

    def test_no_insufficient_data_with_fields(self):
        self.assertNotIn("INSUFFICIENT_DATA", self.an._compute_flags(_make_pos()))

    def test_flags_is_list(self):
        self.assertIsInstance(self.an._compute_flags(_make_pos()), list)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.an = DeFiProtocolSequencerDowntimeRiskAnalyzer(data_dir=self.tmpdir)
        self.config = {"data_dir": self.tmpdir}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        self.assertIsInstance(self.an.analyze([_make_pos()], self.config), dict)

    def test_analyzed_positions_key(self):
        self.assertIn("analyzed_positions", self.an.analyze([_make_pos()], self.config))

    def test_aggregates_key(self):
        self.assertIn("aggregates", self.an.analyze([_make_pos()], self.config))

    def test_metadata_key(self):
        self.assertIn("metadata", self.an.analyze([_make_pos()], self.config))

    def test_count_matches_input(self):
        positions = [_make_pos(name=f"P{i}") for i in range(5)]
        result = self.an.analyze(positions, self.config)
        self.assertEqual(len(result["analyzed_positions"]), 5)

    def test_empty_positions(self):
        result = self.an.analyze([], self.config)
        self.assertEqual(result["aggregates"]["avg_net_downtime_risk"], 0.0)
        self.assertEqual(result["aggregates"]["critical_count"], 0)
        self.assertEqual(result["aggregates"]["resilient_count"], 0)

    def test_log_file_created(self):
        self.an.analyze([_make_pos()], self.config)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "sequencer_downtime_risk_log.json")))

    def test_log_is_valid_json_list(self):
        self.an.analyze([_make_pos()], self.config)
        with open(os.path.join(self.tmpdir, "sequencer_downtime_risk_log.json")) as f:
            self.assertIsInstance(json.load(f), list)

    def test_log_grows(self):
        self.an.analyze([_make_pos()], self.config)
        self.an.analyze([_make_pos()], self.config)
        with open(os.path.join(self.tmpdir, "sequencer_downtime_risk_log.json")) as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_log_respects_cap(self):
        for _ in range(110):
            self.an.analyze([_make_pos()], self.config)
        with open(os.path.join(self.tmpdir, "sequencer_downtime_risk_log.json")) as f:
            self.assertLessEqual(len(json.load(f)), 100)

    def test_position_has_required_fields(self):
        result = self.an.analyze([_make_pos()], self.config)
        p = result["analyzed_positions"][0]
        for field in [
            "name", "protocol", "chain", "downtime_frequency_score",
            "liquidation_exposure_score", "escape_hatch_score",
            "centralization_score", "net_downtime_risk_score",
            "classification", "grade", "flags",
        ]:
            self.assertIn(field, p)

    def test_aggregates_required_fields(self):
        agg = self.an.analyze([_make_pos()], self.config)["aggregates"]
        for field in [
            "safest_position", "riskiest_position", "avg_net_downtime_risk",
            "critical_count", "resilient_count",
        ]:
            self.assertIn(field, agg)

    def test_metadata_mp(self):
        result = self.an.analyze([_make_pos()], self.config)
        self.assertEqual(result["metadata"]["mp"], "MP-1024")

    def test_metadata_module(self):
        result = self.an.analyze([_make_pos()], self.config)
        self.assertEqual(result["metadata"]["module"],
                         "DeFiProtocolSequencerDowntimeRiskAnalyzer")

    def test_metadata_position_count(self):
        positions = [_make_pos(name=f"P{i}") for i in range(7)]
        result = self.an.analyze(positions, self.config)
        self.assertEqual(result["metadata"]["position_count"], 7)

    def test_metadata_timestamp(self):
        result = self.an.analyze([_make_pos()], self.config)
        self.assertIn("timestamp", result["metadata"])

    def test_resilient_classification_in_result(self):
        result = self.an.analyze([_resilient_pos()], self.config)
        self.assertEqual(result["analyzed_positions"][0]["classification"], "RESILIENT")

    def test_critical_classification_in_result(self):
        result = self.an.analyze([_critical_pos()], self.config)
        self.assertEqual(result["analyzed_positions"][0]["classification"],
                         "CRITICAL_EXPOSURE")

    def test_riskiest_safest(self):
        result = self.an.analyze(
            [_resilient_pos("Safe"), _critical_pos("Risky")], self.config)
        self.assertEqual(result["aggregates"]["riskiest_position"], "Risky")
        self.assertEqual(result["aggregates"]["safest_position"], "Safe")

    def test_critical_count(self):
        result = self.an.analyze(
            [_critical_pos("C1"), _critical_pos("C2"), _resilient_pos("R")], self.config)
        self.assertEqual(result["aggregates"]["critical_count"], 2)

    def test_resilient_count(self):
        result = self.an.analyze(
            [_resilient_pos("R1"), _resilient_pos("R2"), _critical_pos("C")], self.config)
        self.assertEqual(result["aggregates"]["resilient_count"], 2)

    def test_avg_in_range(self):
        positions = [_make_pos(name=f"P{i}") for i in range(5)]
        avg = self.an.analyze(positions, self.config)["aggregates"]["avg_net_downtime_risk"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_net_score_in_range(self):
        result = self.an.analyze([_critical_pos()], self.config)
        score = result["analyzed_positions"][0]["net_downtime_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_missing_optional_fields_no_error(self):
        result = self.an.analyze([{"name": "Min"}], self.config)
        self.assertIn("analyzed_positions", result)

    def test_insufficient_data_in_result(self):
        result = self.an.analyze([{"name": "Min"}], self.config)
        self.assertIn("INSUFFICIENT_DATA", result["analyzed_positions"][0]["flags"])

    def test_name_preserved(self):
        result = self.an.analyze([_make_pos(name="MyPos")], self.config)
        self.assertEqual(result["analyzed_positions"][0]["name"], "MyPos")

    def test_deterministic(self):
        pos = _make_pos()
        r1 = self.an.analyze([pos], self.config)
        r2 = self.an.analyze([pos], self.config)
        self.assertAlmostEqual(
            r1["analyzed_positions"][0]["net_downtime_risk_score"],
            r2["analyzed_positions"][0]["net_downtime_risk_score"])

    def test_grade_valid(self):
        valid = {"A", "B", "C", "D", "F"}
        positions = [_make_pos(name=f"P{i}") for i in range(5)]
        result = self.an.analyze(positions, self.config)
        for p in result["analyzed_positions"]:
            self.assertIn(p["grade"], valid)

    def test_classification_valid(self):
        valid = {"RESILIENT", "LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "CRITICAL_EXPOSURE"}
        positions = [_make_pos(name=f"P{i}") for i in range(5)]
        result = self.an.analyze(positions, self.config)
        for p in result["analyzed_positions"]:
            self.assertIn(p["classification"], valid)

    def test_no_config_uses_default(self):
        an = DeFiProtocolSequencerDowntimeRiskAnalyzer(data_dir=self.tmpdir)
        result = an.analyze([_make_pos()], {})
        self.assertIn("analyzed_positions", result)

    def test_log_entry_fields(self):
        self.an.analyze([_make_pos()], self.config)
        with open(os.path.join(self.tmpdir, "sequencer_downtime_risk_log.json")) as f:
            entry = json.load(f)[-1]
        for field in ["timestamp", "position_count", "avg_net_downtime_risk",
                      "critical_count", "resilient_count"]:
            self.assertIn(field, entry)

    def test_default_constructor(self):
        an = DeFiProtocolSequencerDowntimeRiskAnalyzer()
        self.assertIsNotNone(an.data_dir)

    def test_config_data_dir_override(self):
        with tempfile.TemporaryDirectory() as d2:
            self.an.analyze([_make_pos()], {"data_dir": d2})
            self.assertTrue(os.path.exists(
                os.path.join(d2, "sequencer_downtime_risk_log.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
