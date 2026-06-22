"""
Tests for MP-816 ProtocolUpgradeImpactAnalyzer
≥65 test cases — unittest only (no third-party deps).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_upgrade_impact_analyzer import (
    analyze,
    init_log,
    _load_log,
    _save_log,
    _pct_change,
    _classify_outcome,
    _classify_track_record,
    _build_recommendation,
    _compute_risk_score,
)


def _upgrade(
    name="TestUpgrade",
    date="2024-01-01",
    utype="feature",
    apy_before=5.0,
    apy_after=6.0,
    tvl_before=100_000_000.0,
    tvl_after=120_000_000.0,
    had_incident=False,
    audited=True,
):
    return {
        "name": name,
        "date": date,
        "type": utype,
        "apy_before": apy_before,
        "apy_after": apy_after,
        "tvl_before_usd": tvl_before,
        "tvl_after_usd": tvl_after,
        "had_incident": had_incident,
        "audited": audited,
    }


def _pending_upgrade(name="Pending", utype="security", apy_before=5.0, tvl_before=1e8, audited=True):
    return {
        "name": name,
        "date": "2025-06-01",
        "type": utype,
        "apy_before": apy_before,
        "apy_after": None,
        "tvl_before_usd": tvl_before,
        "tvl_after_usd": None,
        "had_incident": False,
        "audited": audited,
    }


class TestImports(unittest.TestCase):
    """Verify module imports work (the _clamp_not_present import above will fail
    gracefully — we just test public symbols here)."""

    def test_analyze_callable(self):
        self.assertTrue(callable(analyze))

    def test_pct_change_callable(self):
        self.assertTrue(callable(_pct_change))

    def test_classify_outcome_callable(self):
        self.assertTrue(callable(_classify_outcome))

    def test_classify_track_record_callable(self):
        self.assertTrue(callable(_classify_track_record))

    def test_build_recommendation_callable(self):
        self.assertTrue(callable(_build_recommendation))

    def test_compute_risk_score_callable(self):
        self.assertTrue(callable(_compute_risk_score))


class TestPctChange(unittest.TestCase):
    def test_positive_increase(self):
        r = _pct_change(100.0, 120.0)
        self.assertAlmostEqual(r, 20.0)

    def test_positive_decrease(self):
        r = _pct_change(100.0, 80.0)
        self.assertAlmostEqual(r, -20.0)

    def test_zero_before_returns_none(self):
        self.assertIsNone(_pct_change(0.0, 100.0))

    def test_none_before_returns_none(self):
        self.assertIsNone(_pct_change(None, 100.0))

    def test_none_after_returns_none(self):
        self.assertIsNone(_pct_change(100.0, None))

    def test_both_none_returns_none(self):
        self.assertIsNone(_pct_change(None, None))

    def test_no_change(self):
        r = _pct_change(100.0, 100.0)
        self.assertAlmostEqual(r, 0.0)

    def test_apy_impact_calculation(self):
        # apy 5.0 → 6.0 = +20%
        r = _pct_change(5.0, 6.0)
        self.assertAlmostEqual(r, 20.0)


class TestClassifyOutcome(unittest.TestCase):
    def test_incident_always_incident(self):
        r = _classify_outcome(True, 6.0, 120e6, 20.0, 20.0)
        self.assertEqual(r, "INCIDENT")

    def test_incident_overrides_positive(self):
        r = _classify_outcome(True, 10.0, 200e6, 50.0, 100.0)
        self.assertEqual(r, "INCIDENT")

    def test_pending_both_none(self):
        r = _classify_outcome(False, None, None, None, None)
        self.assertEqual(r, "PENDING")

    def test_positive_by_apy(self):
        r = _classify_outcome(False, 6.0, 120e6, 20.0, 5.0)
        self.assertEqual(r, "POSITIVE")

    def test_positive_by_tvl(self):
        r = _classify_outcome(False, 5.5, 120e6, 1.0, 20.0)
        self.assertEqual(r, "POSITIVE")

    def test_negative_by_apy(self):
        r = _classify_outcome(False, 4.0, 90e6, -20.0, -10.0)
        self.assertEqual(r, "NEGATIVE")

    def test_negative_by_tvl(self):
        r = _classify_outcome(False, 5.0, 80e6, 0.0, -20.0)
        self.assertEqual(r, "NEGATIVE")

    def test_neutral_small_changes(self):
        r = _classify_outcome(False, 5.2, 103e6, 3.0, 2.0)
        self.assertEqual(r, "NEUTRAL")

    def test_boundary_apy_exactly_5(self):
        # apy_impact == 5 → not > 5 → not POSITIVE by apy alone
        r = _classify_outcome(False, 5.25, 103e6, 5.0, 2.0)
        # tvl_impact=2 < 10 → NEUTRAL
        self.assertEqual(r, "NEUTRAL")

    def test_boundary_tvl_exactly_10(self):
        # tvl_impact == 10 → not > 10 → NEUTRAL
        r = _classify_outcome(False, 5.2, 110e6, 2.0, 10.0)
        self.assertEqual(r, "NEUTRAL")


class TestClassifyTrackRecord(unittest.TestCase):
    def test_excellent_zero_incidents_positive_apy(self):
        self.assertEqual(_classify_track_record(0.0, 5.0), "EXCELLENT")

    def test_excellent_zero_incidents_none_apy(self):
        self.assertEqual(_classify_track_record(0.0, None), "EXCELLENT")

    def test_excellent_zero_incidents_zero_apy(self):
        self.assertEqual(_classify_track_record(0.0, 0.0), "EXCELLENT")

    def test_not_excellent_zero_incidents_negative_apy(self):
        # incident_rate=0 but avg_apy_impact < 0 → not EXCELLENT → GOOD (rate < 10)
        self.assertEqual(_classify_track_record(0.0, -5.0), "GOOD")

    def test_good_low_incident_rate(self):
        self.assertEqual(_classify_track_record(9.9, 5.0), "GOOD")

    def test_mixed_mid_incident_rate(self):
        self.assertEqual(_classify_track_record(10.0, 0.0), "MIXED")

    def test_mixed_high_but_below_25(self):
        self.assertEqual(_classify_track_record(24.9, 0.0), "MIXED")

    def test_poor_high_incident_rate(self):
        self.assertEqual(_classify_track_record(25.0, 0.0), "POOR")

    def test_poor_very_high(self):
        self.assertEqual(_classify_track_record(100.0, 0.0), "POOR")


class TestBuildRecommendation(unittest.TestCase):
    def test_excellent_no_pending(self):
        r = _build_recommendation("EXCELLENT", 0)
        self.assertIn("minimal risk", r)

    def test_excellent_with_pending(self):
        r = _build_recommendation("EXCELLENT", 2)
        self.assertIn("monitor", r.lower())

    def test_good(self):
        r = _build_recommendation("GOOD", 0)
        self.assertIn("Good", r)
        self.assertIn("monitor", r.lower())

    def test_mixed(self):
        r = _build_recommendation("MIXED", 0)
        self.assertIn("caution", r.lower())

    def test_poor(self):
        r = _build_recommendation("POOR", 0)
        self.assertIn("high caution", r.lower())


class TestComputeRiskScore(unittest.TestCase):
    def test_perfect_history_low_score(self):
        # 100% audited, 0% incidents, 10 completed
        score = _compute_risk_score(100.0, 0.0, 10)
        # 50 - 30 + 0 - 20 = 0
        self.assertEqual(score, 0)

    def test_no_history_default_50(self):
        # 0% audited, 0% incidents, 0 completed
        score = _compute_risk_score(0.0, 0.0, 0)
        # 50 - 0 + 0 - 0 = 50
        self.assertEqual(score, 50)

    def test_high_incident_rate_high_score(self):
        # 0% audited, 50% incident, 0 completed
        score = _compute_risk_score(0.0, 50.0, 0)
        # 50 + 50 = 100
        self.assertEqual(score, 100)

    def test_clamped_to_100(self):
        score = _compute_risk_score(0.0, 200.0, 0)
        self.assertEqual(score, 100)

    def test_clamped_to_0(self):
        score = _compute_risk_score(100.0, 0.0, 100)
        self.assertEqual(score, 0)

    def test_completed_cap_at_10(self):
        # min(10*2, 20) = 20 vs min(11*2, 20) = 20 — both max out at 20
        s10 = _compute_risk_score(0.0, 0.0, 10)
        s11 = _compute_risk_score(0.0, 0.0, 11)
        self.assertEqual(s10, s11)

    def test_is_int(self):
        score = _compute_risk_score(50.0, 5.0, 3)
        self.assertIsInstance(score, int)


class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_empty_history_structure(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"], [])

    def test_empty_statistics_zeros(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        s = r["statistics"]
        self.assertEqual(s["total_upgrades"], 0)
        self.assertEqual(s["completed"], 0)
        self.assertEqual(s["pending"], 0)
        self.assertEqual(s["incident_rate_pct"], 0.0)
        self.assertEqual(s["audited_pct"], 0.0)
        self.assertIsNone(s["avg_apy_impact_pct"])
        self.assertIsNone(s["avg_tvl_impact_pct"])

    def test_empty_track_record_excellent(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["track_record"], "EXCELLENT")

    def test_empty_risk_score_50(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_risk_score"], 50)

    def test_empty_protocol_preserved(self):
        r = analyze("morpho", [], log_path=self.log, persist=False)
        self.assertEqual(r["protocol"], "morpho")

    def test_empty_timestamp_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)


class TestAnalyzeCompleted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_single_positive_upgrade(self):
        u = _upgrade(apy_before=5.0, apy_after=6.5, tvl_before=1e8, tvl_after=1.2e8)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["outcome"], "POSITIVE")
        self.assertEqual(h["status"], "COMPLETED")

    def test_apy_impact_calculated(self):
        u = _upgrade(apy_before=5.0, apy_after=6.0)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertAlmostEqual(h["apy_impact_pct"], 20.0)

    def test_tvl_impact_calculated(self):
        u = _upgrade(tvl_before=100e6, tvl_after=120e6)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertAlmostEqual(h["tvl_impact_pct"], 20.0)

    def test_negative_upgrade(self):
        u = _upgrade(apy_before=6.0, apy_after=4.0, tvl_before=1e8, tvl_after=8e7)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["outcome"], "NEGATIVE")

    def test_neutral_upgrade(self):
        u = _upgrade(apy_before=5.0, apy_after=5.1, tvl_before=1e8, tvl_after=1.02e8)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["outcome"], "NEUTRAL")

    def test_incident_upgrade(self):
        u = _upgrade(had_incident=True)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["outcome"], "INCIDENT")

    def test_statistics_completed_count(self):
        upgrades = [_upgrade(), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(r["statistics"]["completed"], 2)

    def test_statistics_total_count(self):
        upgrades = [_upgrade(), _upgrade(), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(r["statistics"]["total_upgrades"], 3)

    def test_incident_rate_single(self):
        u = _upgrade(had_incident=True)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["incident_rate_pct"], 100.0)

    def test_incident_rate_half(self):
        upgrades = [_upgrade(had_incident=True), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["incident_rate_pct"], 50.0)

    def test_incident_rate_zero(self):
        upgrades = [_upgrade(), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["incident_rate_pct"], 0.0)

    def test_audited_pct_all(self):
        upgrades = [_upgrade(audited=True), _upgrade(audited=True)]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["audited_pct"], 100.0)

    def test_audited_pct_none(self):
        upgrades = [_upgrade(audited=False), _upgrade(audited=False)]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["audited_pct"], 0.0)

    def test_audited_pct_half(self):
        upgrades = [_upgrade(audited=True), _upgrade(audited=False)]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["audited_pct"], 50.0)

    def test_avg_apy_impact(self):
        # 20% and -10% → avg = 5%
        upgrades = [
            _upgrade(apy_before=5.0, apy_after=6.0),   # +20%
            _upgrade(apy_before=10.0, apy_after=9.0),  # -10%
        ]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["avg_apy_impact_pct"], 5.0)

    def test_avg_tvl_impact(self):
        upgrades = [
            _upgrade(tvl_before=100e6, tvl_after=120e6),  # +20%
            _upgrade(tvl_before=100e6, tvl_after=100e6),  # 0%
        ]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["statistics"]["avg_tvl_impact_pct"], 10.0)


class TestAnalyzePending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_pending_upgrade_status(self):
        u = _pending_upgrade()
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["status"], "PENDING")

    def test_pending_upgrade_outcome(self):
        u = _pending_upgrade()
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertEqual(h["outcome"], "PENDING")

    def test_pending_apy_impact_none(self):
        u = _pending_upgrade()
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertIsNone(h["apy_impact_pct"])

    def test_pending_tvl_impact_none(self):
        u = _pending_upgrade()
        r = analyze("aave", [u], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        self.assertIsNone(h["tvl_impact_pct"])

    def test_pending_count_in_statistics(self):
        upgrades = [_pending_upgrade(), _pending_upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(r["statistics"]["pending"], 2)

    def test_all_pending_avg_impacts_none(self):
        r = analyze("aave", [_pending_upgrade()], log_path=self.log, persist=False)
        self.assertIsNone(r["statistics"]["avg_apy_impact_pct"])
        self.assertIsNone(r["statistics"]["avg_tvl_impact_pct"])

    def test_all_pending_incident_rate_zero(self):
        r = analyze("aave", [_pending_upgrade()], log_path=self.log, persist=False)
        self.assertEqual(r["statistics"]["incident_rate_pct"], 0.0)

    def test_mixed_completed_and_pending(self):
        upgrades = [_upgrade(), _pending_upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        s = r["statistics"]
        self.assertEqual(s["completed"], 1)
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["total_upgrades"], 2)


class TestTrackRecordAndRisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_excellent_no_incidents_positive_apy(self):
        u = _upgrade(apy_before=5.0, apy_after=6.0, audited=True)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["track_record"], "EXCELLENT")

    def test_poor_high_incidents(self):
        upgrades = [_upgrade(had_incident=True), _upgrade(had_incident=True), _upgrade(had_incident=True), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        # 3/4 = 75% incidents → POOR
        self.assertEqual(r["track_record"], "POOR")

    def test_mixed_track_record(self):
        upgrades = [
            _upgrade(had_incident=True),
            _upgrade(), _upgrade(), _upgrade(), _upgrade(),
            _upgrade(), _upgrade(), _upgrade(), _upgrade(), _upgrade(),
        ]
        # 1/10 = 10% → MIXED
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(r["track_record"], "MIXED")

    def test_risk_score_is_int(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIsInstance(r["upgrade_risk_score"], int)

    def test_risk_score_in_range(self):
        for _ in range(5):
            r = analyze("aave", [_upgrade()], log_path=self.log, persist=False)
            self.assertGreaterEqual(r["upgrade_risk_score"], 0)
            self.assertLessEqual(r["upgrade_risk_score"], 100)

    def test_risk_score_lower_for_audited_clean_history(self):
        clean = [_upgrade(audited=True)] * 5  # 5 completed, all audited, no incidents
        dirty = [_upgrade(audited=False, had_incident=True)] * 1
        r_clean = analyze("aave", clean, log_path=self.log, persist=False)
        r_dirty = analyze("aave", dirty, log_path=self.log, persist=False)
        self.assertLess(r_clean["upgrade_risk_score"], r_dirty["upgrade_risk_score"])


class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_excellent_no_pending_recommendation(self):
        u = _upgrade(audited=True)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        # EXCELLENT + 0 pending → "minimal risk"
        self.assertIn("minimal risk", r["recommendation"])

    def test_poor_recommendation(self):
        upgrades = [_upgrade(had_incident=True), _upgrade(had_incident=True), _upgrade(had_incident=True), _upgrade()]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertIn("high caution", r["recommendation"].lower())

    def test_recommendation_is_string(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIsInstance(r["recommendation"], str)


class TestReturnSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_top_level_keys_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        required = {"protocol", "upgrade_history", "statistics", "track_record",
                    "upgrade_risk_score", "recommendation", "timestamp"}
        self.assertTrue(required.issubset(r.keys()))

    def test_statistics_keys_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        s = r["statistics"]
        required = {"total_upgrades", "completed", "pending", "incident_rate_pct",
                    "audited_pct", "avg_apy_impact_pct", "avg_tvl_impact_pct"}
        self.assertTrue(required.issubset(s.keys()))

    def test_upgrade_history_entry_keys(self):
        r = analyze("aave", [_upgrade()], log_path=self.log, persist=False)
        h = r["upgrade_history"][0]
        required = {"name", "type", "date", "status", "apy_impact_pct", "tvl_impact_pct", "outcome"}
        self.assertTrue(required.issubset(h.keys()))

    def test_track_record_valid_enum(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIn(r["track_record"], {"EXCELLENT", "GOOD", "MIXED", "POOR"})

    def test_outcome_valid_enum(self):
        valid = {"POSITIVE", "NEUTRAL", "NEGATIVE", "INCIDENT", "PENDING"}
        for outcome_type in [
            _upgrade(),
            _upgrade(had_incident=True),
            _pending_upgrade(),
            _upgrade(apy_before=5.0, apy_after=4.0, tvl_before=1e8, tvl_after=8e7),
        ]:
            r = analyze("aave", [outcome_type], log_path=self.log, persist=False)
            self.assertIn(r["upgrade_history"][0]["outcome"], valid)

    def test_status_valid_enum(self):
        r = analyze("aave", [_upgrade()], log_path=self.log, persist=False)
        self.assertIn(r["upgrade_history"][0]["status"], {"COMPLETED", "PENDING"})


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_persist_true_creates_log(self):
        analyze("aave", [], log_path=self.log, persist=True)
        self.assertTrue(os.path.exists(self.log))

    def test_persist_false_no_file(self):
        analyze("aave", [], log_path=self.log, persist=False)
        self.assertFalse(os.path.exists(self.log))

    def test_persist_appends(self):
        analyze("aave", [], log_path=self.log, persist=True)
        analyze("compound", [], log_path=self.log, persist=True)
        entries = _load_log(self.log)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap(self):
        for i in range(110):
            analyze(f"proto_{i}", [], log_path=self.log, persist=True)
        entries = _load_log(self.log)
        self.assertLessEqual(len(entries), 100)

    def test_log_is_valid_json(self):
        analyze("aave", [], log_path=self.log, persist=True)
        with open(self.log, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_init_log_creates_file(self):
        path = os.path.join(self.tmp, "init_test.json")
        init_log(path)
        self.assertTrue(os.path.exists(path))

    def test_init_log_empty_list(self):
        path = os.path.join(self.tmp, "init_test2.json")
        init_log(path)
        data = _load_log(path)
        self.assertEqual(data, [])

    def test_load_log_missing_file_empty(self):
        path = os.path.join(self.tmp, "missing.json")
        self.assertEqual(_load_log(path), [])

    def test_load_log_corrupted_empty(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as fh:
            fh.write("{{invalid}}")
        self.assertEqual(_load_log(path), [])

    def test_save_load_roundtrip(self):
        path = os.path.join(self.tmp, "rt.json")
        entries = [{"foo": "bar"}]
        _save_log(path, entries)
        self.assertEqual(_load_log(path), entries)


class TestUpgradeTypes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_security_upgrade_type_preserved(self):
        u = _upgrade(utype="security")
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"][0]["type"], "security")

    def test_migration_upgrade_type_preserved(self):
        u = _upgrade(utype="migration")
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"][0]["type"], "migration")

    def test_date_preserved(self):
        u = _upgrade(date="2024-06-15")
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"][0]["date"], "2024-06-15")

    def test_name_preserved(self):
        u = _upgrade(name="V3 Security Patch")
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"][0]["name"], "V3 Security Patch")


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "upgrade_impact_log.json")

    def test_zero_tvl_before_impact_none(self):
        u = _upgrade(tvl_before=0.0, tvl_after=100e6)
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertIsNone(r["upgrade_history"][0]["tvl_impact_pct"])

    def test_many_upgrades(self):
        upgrades = [_upgrade() for _ in range(50)]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(r["statistics"]["total_upgrades"], 50)

    def test_config_none_ok(self):
        r = analyze("aave", [], config=None, log_path=self.log, persist=False)
        self.assertIsNotNone(r)

    def test_empty_name_upgrade(self):
        u = _upgrade(name="")
        r = analyze("aave", [u], log_path=self.log, persist=False)
        self.assertEqual(r["upgrade_history"][0]["name"], "")

    def test_upgrade_history_length_matches_input(self):
        upgrades = [_upgrade(), _pending_upgrade(), _upgrade(had_incident=True)]
        r = analyze("aave", upgrades, log_path=self.log, persist=False)
        self.assertEqual(len(r["upgrade_history"]), 3)


if __name__ == "__main__":
    unittest.main()
