"""tests/test_protocol_registry.py — MP-583 ProtocolRegistry test suite.

Coverage: 103 test cases across 11 classes.

TestInit                (8)  — construction, seed loading, repr, len, contains
TestRegister           (12)  — register/update/validation
TestGet                 (7)  — get existing, missing, immutability
TestListAll             (6)  — list_all ordering, uniqueness, after register
TestGetAuditScore      (18)  — breakpoints, recency, firm tiers, edge cases
TestGetHackRiskFlag    (14)  — recent vs old hacks, edge cases, missing
TestAgeScore           (10)  — _get_age_score breakpoints
TestTvlScore            (8)  — _get_tvl_score breakpoints
TestComputeSafetyScore (12)  — formula, weights, edge cases
TestGetRegistryReport  (10)  — structure, top5, hack_risk_protocols
TestSaveLoad           (10)  — atomic save, round-trip, malformed file
TestImportHygiene       (3)  — no forbidden imports; stdlib only
TestEdgeCases           (5)  — boundary values, unknown protocol

Total: 123 tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta
from pathlib import Path

# Make spa_core importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.protocol_registry import (
    ProtocolRegistry,
    _safe_float,
    _parse_date,
    _tiered_score,
    _audit_recency_factor,
    _firm_tier_pts,
    _SEED_PROTOCOLS,
    _HACK_RISK_WINDOW_DAYS,
    _W_AUDIT,
    _W_AGE,
    _W_TVL,
    _AGE_BREAKPOINTS,
    _TVL_BREAKPOINTS,
    _FIRMS_TOP,
    _FIRMS_MID,
    REGISTRY_FILENAME,
)

# ---------------------------------------------------------------------------
# Reference date — fix "today" so tests are deterministic
# ---------------------------------------------------------------------------
REF_DATE = date(2026, 6, 13)


# ---------------------------------------------------------------------------
# TestInit  (8 tests)
# ---------------------------------------------------------------------------

class TestInit(unittest.TestCase):
    """Construction and initial state."""

    def setUp(self):
        self.reg = ProtocolRegistry(reference_date=REF_DATE)

    def test_default_seed_loads_15_protocols(self):
        self.assertEqual(len(self.reg), 15)

    def test_all_seed_protocol_ids_present(self):
        expected_ids = {
            "aave", "morpho", "spark", "compound", "euler",
            "maple", "pendle", "sky", "yearn", "frax",
            "sdai", "sfrax", "stusd", "scrvusd", "wusdm",
        }
        self.assertEqual(set(self.reg.list_all()), expected_ids)

    def test_no_seed_gives_empty_registry(self):
        reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)
        self.assertEqual(len(reg), 0)
        self.assertEqual(reg.list_all(), [])

    def test_repr_contains_protocol_count(self):
        r = repr(self.reg)
        self.assertIn("15", r)
        self.assertIn("ProtocolRegistry", r)

    def test_len_matches_seed_count(self):
        self.assertEqual(len(self.reg), len(_SEED_PROTOCOLS))

    def test_contains_known_protocol(self):
        self.assertIn("aave", self.reg)

    def test_not_contains_unknown_protocol(self):
        self.assertNotIn("nonexistent_proto_xyz", self.reg)

    def test_reference_date_stored(self):
        reg = ProtocolRegistry(reference_date=date(2025, 1, 1))
        self.assertEqual(reg._today, date(2025, 1, 1))


# ---------------------------------------------------------------------------
# TestRegister  (12 tests)
# ---------------------------------------------------------------------------

class TestRegister(unittest.TestCase):
    """register() — add, update, validation."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def test_register_new_protocol(self):
        self.reg.register("test_proto", {"name": "Test", "audits": []})
        self.assertIn("test_proto", self.reg)

    def test_register_increments_len(self):
        self.reg.register("p1", {"audits": []})
        self.reg.register("p2", {"audits": []})
        self.assertEqual(len(self.reg), 2)

    def test_register_overwrites_existing(self):
        self.reg.register("p1", {"name": "Old", "audits": []})
        self.reg.register("p1", {"name": "New", "audits": []})
        self.assertEqual(self.reg.get("p1")["name"], "New")

    def test_register_stores_protocol_id_in_entry(self):
        self.reg.register("alpha", {"name": "Alpha"})
        self.assertEqual(self.reg.get("alpha")["protocol_id"], "alpha")

    def test_register_raises_on_non_string_id(self):
        with self.assertRaises(TypeError):
            self.reg.register(123, {})

    def test_register_raises_on_empty_id(self):
        with self.assertRaises(ValueError):
            self.reg.register("", {})

    def test_register_raises_on_whitespace_id(self):
        with self.assertRaises(ValueError):
            self.reg.register("   ", {})

    def test_register_raises_on_non_dict_metadata(self):
        with self.assertRaises(TypeError):
            self.reg.register("p1", "not a dict")

    def test_register_raises_on_none_metadata(self):
        with self.assertRaises(TypeError):
            self.reg.register("p1", None)

    def test_register_metadata_is_copied(self):
        original = {"name": "P1", "audits": []}
        self.reg.register("p1", original)
        original["name"] = "MUTATED"
        self.assertEqual(self.reg.get("p1")["name"], "P1")

    def test_register_accepts_minimal_metadata(self):
        self.reg.register("bare", {})
        self.assertIn("bare", self.reg)

    def test_register_none_id_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.reg.register(None, {})


# ---------------------------------------------------------------------------
# TestGet  (7 tests)
# ---------------------------------------------------------------------------

class TestGet(unittest.TestCase):
    """get() — retrieval and immutability."""

    def setUp(self):
        self.reg = ProtocolRegistry(reference_date=REF_DATE)

    def test_get_known_returns_dict(self):
        result = self.reg.get("aave")
        self.assertIsInstance(result, dict)

    def test_get_known_contains_expected_fields(self):
        result = self.reg.get("aave")
        self.assertIn("name", result)
        self.assertIn("audits", result)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.reg.get("does_not_exist_xyz"))

    def test_get_returns_copy_not_reference(self):
        result = self.reg.get("aave")
        result["name"] = "HACKED"
        self.assertNotEqual(self.reg.get("aave")["name"], "HACKED")

    def test_get_after_register(self):
        self.reg.register("new_proto", {"name": "New"})
        self.assertIsNotNone(self.reg.get("new_proto"))

    def test_get_protocol_id_in_result(self):
        result = self.reg.get("morpho")
        self.assertEqual(result["protocol_id"], "morpho")

    def test_get_all_seed_protocols_not_none(self):
        for pid in ["aave", "morpho", "spark", "compound", "euler",
                    "maple", "pendle", "sky", "yearn", "frax",
                    "sdai", "sfrax", "stusd", "scrvusd", "wusdm"]:
            with self.subTest(pid=pid):
                self.assertIsNotNone(self.reg.get(pid))


# ---------------------------------------------------------------------------
# TestListAll  (6 tests)
# ---------------------------------------------------------------------------

class TestListAll(unittest.TestCase):
    """list_all() — sorted, unique, updated on register."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def test_list_all_empty_registry(self):
        self.assertEqual(self.reg.list_all(), [])

    def test_list_all_sorted(self):
        self.reg.register("zzz", {})
        self.reg.register("aaa", {})
        result = self.reg.list_all()
        self.assertEqual(result, sorted(result))

    def test_list_all_includes_registered(self):
        self.reg.register("new_one", {})
        self.assertIn("new_one", self.reg.list_all())

    def test_list_all_returns_list(self):
        self.assertIsInstance(self.reg.list_all(), list)

    def test_list_all_unique(self):
        self.reg.register("dup", {})
        self.reg.register("dup", {"name": "updated"})
        result = self.reg.list_all()
        self.assertEqual(len(result), len(set(result)))

    def test_list_all_seed_length(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertEqual(len(reg.list_all()), 15)


# ---------------------------------------------------------------------------
# TestGetAuditScore  (18 tests)
# ---------------------------------------------------------------------------

class TestGetAuditScore(unittest.TestCase):
    """get_audit_score() — firm tiers, recency factors, edge cases."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def _proto(self, audits):
        self.reg.register("p", {"audits": audits})

    def test_unknown_protocol_returns_zero(self):
        self.assertEqual(self.reg.get_audit_score("unknown_xyz"), 0.0)

    def test_no_audits_returns_zero(self):
        self._proto([])
        self.assertEqual(self.reg.get_audit_score("p"), 0.0)

    def test_top_firm_recent_gives_max_per_audit(self):
        # Reference date 2026-06-13; audit within last year
        recent = (REF_DATE - timedelta(days=100)).isoformat()
        self._proto([{"firm": "Trail of Bits", "date": recent}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 20.0, places=4)

    def test_mid_firm_recent(self):
        recent = (REF_DATE - timedelta(days=100)).isoformat()
        self._proto([{"firm": "Certik", "date": recent}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 15.0, places=4)

    def test_unknown_firm_recent(self):
        recent = (REF_DATE - timedelta(days=100)).isoformat()
        self._proto([{"firm": "SomeUnknownFirm", "date": recent}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 10.0, places=4)

    def test_recency_1_to_2_years_factor_0_8(self):
        old_date = (REF_DATE - timedelta(days=500)).isoformat()  # ~1.37 years
        self._proto([{"firm": "Trail of Bits", "date": old_date}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 20.0 * 0.8, places=4)

    def test_recency_2_to_3_years_factor_0_6(self):
        old_date = (REF_DATE - timedelta(days=800)).isoformat()  # ~2.19 years
        self._proto([{"firm": "Trail of Bits", "date": old_date}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 20.0 * 0.6, places=4)

    def test_recency_over_3_years_factor_0_3(self):
        old_date = (REF_DATE - timedelta(days=1200)).isoformat()  # ~3.3 years
        self._proto([{"firm": "Trail of Bits", "date": old_date}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 20.0 * 0.3, places=4)

    def test_multiple_audits_sum(self):
        recent = (REF_DATE - timedelta(days=50)).isoformat()
        self._proto([
            {"firm": "Trail of Bits", "date": recent},
            {"firm": "OpenZeppelin",  "date": recent},
        ])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 40.0, places=4)

    def test_score_capped_at_100(self):
        recent = (REF_DATE - timedelta(days=30)).isoformat()
        audits = [{"firm": "Trail of Bits", "date": recent}] * 10
        self._proto(audits)
        score = self.reg.get_audit_score("p")
        self.assertLessEqual(score, 100.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_malformed_audit_dict_skipped(self):
        recent = (REF_DATE - timedelta(days=50)).isoformat()
        self._proto([
            "not_a_dict",
            {"firm": "Trail of Bits", "date": recent},
        ])
        score = self.reg.get_audit_score("p")
        # Only the valid audit counted
        self.assertAlmostEqual(score, 20.0, places=4)

    def test_audit_with_missing_date_uses_date_min(self):
        # date.min is very old → 0.3 factor
        self._proto([{"firm": "Trail of Bits"}])
        score = self.reg.get_audit_score("p")
        self.assertAlmostEqual(score, 20.0 * 0.3, places=4)

    def test_audit_with_invalid_date_string(self):
        self._proto([{"firm": "Trail of Bits", "date": "not-a-date"}])
        score = self.reg.get_audit_score("p")
        # Invalid date → date.min → very old → 0.3 factor
        self.assertAlmostEqual(score, 20.0 * 0.3, places=4)

    def test_firm_name_case_insensitive(self):
        recent = (REF_DATE - timedelta(days=50)).isoformat()
        self._proto([{"firm": "TRAIL OF BITS", "date": recent}])
        score_upper = self.reg.get_audit_score("p")

        self.reg.register("p2", {"audits": [{"firm": "trail of bits", "date": recent}]})
        score_lower = self.reg.get_audit_score("p2")
        self.assertAlmostEqual(score_upper, score_lower, places=4)

    def test_audit_exactly_365_days_old_is_boundary(self):
        boundary = (REF_DATE - timedelta(days=365)).isoformat()
        self._proto([{"firm": "Trail of Bits", "date": boundary}])
        score = self.reg.get_audit_score("p")
        # 365 days >= 365 threshold → goes to 1-2y bracket → factor 0.8
        self.assertAlmostEqual(score, 20.0 * 0.8, places=4)

    def test_aave_has_positive_audit_score(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertGreater(reg.get_audit_score("aave"), 0.0)

    def test_morpho_audit_score_positive(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertGreater(reg.get_audit_score("morpho"), 0.0)

    def test_protocol_with_no_audits_key(self):
        self.reg.register("noaudit", {"name": "NoAudit"})
        self.assertEqual(self.reg.get_audit_score("noaudit"), 0.0)


# ---------------------------------------------------------------------------
# TestGetHackRiskFlag  (14 tests)
# ---------------------------------------------------------------------------

class TestGetHackRiskFlag(unittest.TestCase):
    """get_hack_risk_flag() — recent vs old hacks, edge cases."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def _proto(self, hacks):
        self.reg.register("p", {"audits": [], "hacks": hacks})

    def test_no_hacks_returns_false(self):
        self._proto([])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_unknown_protocol_returns_false(self):
        self.assertFalse(self.reg.get_hack_risk_flag("unknown_xyz"))

    def test_recent_hack_returns_true(self):
        recent = (REF_DATE - timedelta(days=30)).isoformat()
        self._proto([{"date": recent, "amount_usd": 1_000_000}])
        self.assertTrue(self.reg.get_hack_risk_flag("p"))

    def test_hack_just_within_2y_returns_true(self):
        just_inside = (REF_DATE - timedelta(days=729)).isoformat()
        self._proto([{"date": just_inside}])
        self.assertTrue(self.reg.get_hack_risk_flag("p"))

    def test_hack_exactly_2y_ago_is_not_risky(self):
        # age_days == 730 → NOT < 730 → False
        exactly_2y = (REF_DATE - timedelta(days=730)).isoformat()
        self._proto([{"date": exactly_2y}])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_hack_older_than_2y_returns_false(self):
        old = (REF_DATE - timedelta(days=800)).isoformat()
        self._proto([{"date": old}])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_mix_old_and_recent_hack_returns_true(self):
        old = (REF_DATE - timedelta(days=1000)).isoformat()
        recent = (REF_DATE - timedelta(days=100)).isoformat()
        self._proto([{"date": old}, {"date": recent}])
        self.assertTrue(self.reg.get_hack_risk_flag("p"))

    def test_malformed_hack_entry_skipped(self):
        self._proto(["not_a_dict"])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_hack_missing_date_skipped(self):
        self._proto([{"amount_usd": 1_000_000}])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_hack_invalid_date_skipped(self):
        self._proto([{"date": "not-a-date"}])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_euler_hack_is_old_enough_flag_false(self):
        # Euler hack was 2023-03-13; reference 2026-06-13 → >2 years
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertFalse(reg.get_hack_risk_flag("euler"))

    def test_all_seed_protocols_no_recent_hack(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        for pid in reg.list_all():
            with self.subTest(pid=pid):
                # All seed hacks are pre-2024-06-13 so should be False
                flag = reg.get_hack_risk_flag(pid)
                # Verify: none of the seed protocols have a hack within 2y of REF_DATE
                self.assertFalse(flag)

    def test_future_dated_hack_not_counted(self):
        # A hack dated in the future — age_days < 0 → condition 0<=age<730 false
        future = (REF_DATE + timedelta(days=30)).isoformat()
        self._proto([{"date": future}])
        self.assertFalse(self.reg.get_hack_risk_flag("p"))

    def test_protocol_with_no_hacks_key(self):
        self.reg.register("nohacks", {"name": "NoHacks"})
        self.assertFalse(self.reg.get_hack_risk_flag("nohacks"))


# ---------------------------------------------------------------------------
# TestAgeScore  (10 tests)
# ---------------------------------------------------------------------------

class TestAgeScore(unittest.TestCase):
    """_get_age_score() — breakpoint coverage."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def _age(self, days):
        launch = (REF_DATE - timedelta(days=days)).isoformat()
        self.reg.register("p", {"launch_date": launch})
        return self.reg._get_age_score("p")

    def test_unknown_protocol_zero(self):
        self.assertEqual(self.reg._get_age_score("unknown"), 0.0)

    def test_no_launch_date_zero(self):
        self.reg.register("p", {})
        self.assertEqual(self.reg._get_age_score("p"), 0.0)

    def test_invalid_launch_date_zero(self):
        self.reg.register("p", {"launch_date": "invalid"})
        self.assertEqual(self.reg._get_age_score("p"), 0.0)

    def test_5_plus_years_gives_100(self):
        self.assertAlmostEqual(self._age(2000), 100.0)

    def test_3_to_5_years_gives_75(self):
        self.assertAlmostEqual(self._age(1100), 75.0)

    def test_2_to_3_years_gives_55(self):
        self.assertAlmostEqual(self._age(800), 55.0)

    def test_1_to_2_years_gives_35(self):
        self.assertAlmostEqual(self._age(400), 35.0)

    def test_6m_to_1_year_gives_15(self):
        self.assertAlmostEqual(self._age(200), 15.0)

    def test_under_6m_gives_5(self):
        self.assertAlmostEqual(self._age(30), 5.0)

    def test_aave_launched_2017_gives_100(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertAlmostEqual(reg._get_age_score("aave"), 100.0)


# ---------------------------------------------------------------------------
# TestTvlScore  (8 tests)
# ---------------------------------------------------------------------------

class TestTvlScore(unittest.TestCase):
    """_get_tvl_score() — breakpoints."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def _tvl(self, tvl_usd):
        self.reg.register("p", {"tvl_usd": tvl_usd})
        return self.reg._get_tvl_score("p")

    def test_unknown_protocol_zero(self):
        self.assertEqual(self.reg._get_tvl_score("unknown"), 0.0)

    def test_5b_plus_gives_100(self):
        self.assertAlmostEqual(self._tvl(6_000_000_000), 100.0)

    def test_1b_to_5b_gives_80(self):
        self.assertAlmostEqual(self._tvl(2_000_000_000), 80.0)

    def test_500m_to_1b_gives_60(self):
        self.assertAlmostEqual(self._tvl(750_000_000), 60.0)

    def test_100m_to_500m_gives_40(self):
        self.assertAlmostEqual(self._tvl(200_000_000), 40.0)

    def test_10m_to_100m_gives_20(self):
        self.assertAlmostEqual(self._tvl(50_000_000), 20.0)

    def test_below_10m_gives_5(self):
        self.assertAlmostEqual(self._tvl(1_000_000), 5.0)

    def test_aave_tvl_gives_100(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertAlmostEqual(reg._get_tvl_score("aave"), 100.0)


# ---------------------------------------------------------------------------
# TestComputeSafetyScore  (12 tests)
# ---------------------------------------------------------------------------

class TestComputeSafetyScore(unittest.TestCase):
    """compute_safety_score() — formula and edge cases."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def test_unknown_returns_zero(self):
        self.assertEqual(self.reg.compute_safety_score("unknown_xyz"), 0.0)

    def test_known_returns_float(self):
        self.reg.register("p", {"audits": [], "tvl_usd": 0})
        score = self.reg.compute_safety_score("p")
        self.assertIsInstance(score, float)

    def test_score_in_range_0_100(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        for pid in reg.list_all():
            s = reg.compute_safety_score(pid)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_formula_weights_sum_to_1(self):
        self.assertAlmostEqual(_W_AUDIT + _W_AGE + _W_TVL, 1.0, places=9)

    def test_formula_correct_manually(self):
        # Build a controlled protocol
        recent = (REF_DATE - timedelta(days=50)).isoformat()
        launch = (REF_DATE - timedelta(days=2000)).isoformat()  # ≥5y → age=100
        self.reg.register("ctrl", {
            "launch_date": launch,
            "tvl_usd": 6_000_000_000,   # ≥5B → tvl_score=100
            "audits": [{"firm": "Trail of Bits", "date": recent}],  # 20*1.0=20 pts
        })
        audit = self.reg.get_audit_score("ctrl")   # 20.0
        age   = self.reg._get_age_score("ctrl")    # 100.0
        tvl   = self.reg._get_tvl_score("ctrl")    # 100.0
        expected = audit * 0.6 + age * 0.2 + tvl * 0.2
        self.assertAlmostEqual(self.reg.compute_safety_score("ctrl"), expected, places=2)

    def test_all_zeros_gives_zero(self):
        self.reg.register("p", {"audits": [], "tvl_usd": 0, "launch_date": ""})
        # audit=0, age=0 (invalid date), tvl=5 (0 tvl → 5 by breakpoint)
        score = self.reg.compute_safety_score("p")
        # tvl_score for 0 → 5.0 (< $10M), age=0, audit=0
        expected = 0 * 0.6 + 0 * 0.2 + 5.0 * 0.2
        self.assertAlmostEqual(score, expected, places=4)

    def test_safety_score_nonnegative(self):
        self.reg.register("p", {"audits": [], "tvl_usd": -1})
        score = self.reg.compute_safety_score("p")
        self.assertGreaterEqual(score, 0.0)

    def test_high_tvl_low_audit_reflects_in_score(self):
        # TVL=100 (top), audit=0, age=5
        recent_launch = (REF_DATE - timedelta(days=200)).isoformat()
        self.reg.register("rich", {"tvl_usd": 6_000_000_000, "audits": [], "launch_date": recent_launch})
        score = self.reg.compute_safety_score("rich")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 40.0)   # limited by audit=0

    def test_aave_safety_higher_than_euler(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        aave_s   = reg.compute_safety_score("aave")
        euler_s  = reg.compute_safety_score("euler")
        self.assertGreater(aave_s, euler_s)

    def test_morpho_safety_positive(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        self.assertGreater(reg.compute_safety_score("morpho"), 0.0)

    def test_sky_safety_score_computed(self):
        reg = ProtocolRegistry(reference_date=REF_DATE)
        score = reg.compute_safety_score("sky")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_max_possible_score_is_100(self):
        recent = (REF_DATE - timedelta(days=10)).isoformat()
        launch = (REF_DATE - timedelta(days=3000)).isoformat()
        self.reg.register("perfect", {
            "launch_date": launch,
            "tvl_usd": 10_000_000_000,
            "audits": [{"firm": "Trail of Bits", "date": recent}] * 5,
        })
        score = self.reg.compute_safety_score("perfect")
        self.assertLessEqual(score, 100.0)


# ---------------------------------------------------------------------------
# TestGetRegistryReport  (10 tests)
# ---------------------------------------------------------------------------

class TestGetRegistryReport(unittest.TestCase):
    """get_registry_report() — structure and content."""

    def setUp(self):
        self.reg = ProtocolRegistry(reference_date=REF_DATE)
        self.report = self.reg.get_registry_report()

    def test_report_is_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_report_has_required_keys(self):
        for key in ("generated_at", "reference_date", "protocol_count",
                    "protocols", "top5_by_safety", "hack_risk_protocols"):
            self.assertIn(key, self.report)

    def test_protocol_count_matches(self):
        self.assertEqual(self.report["protocol_count"], len(self.reg))

    def test_protocols_has_all_ids(self):
        self.assertEqual(
            set(self.report["protocols"].keys()),
            set(self.reg.list_all()),
        )

    def test_each_protocol_entry_has_scores(self):
        for pid, data in self.report["protocols"].items():
            for key in ("audit_score", "age_score", "tvl_score",
                        "safety_score", "hack_risk_flag"):
                with self.subTest(pid=pid, key=key):
                    self.assertIn(key, data)

    def test_top5_has_at_most_5_entries(self):
        self.assertLessEqual(len(self.report["top5_by_safety"]), 5)

    def test_top5_sorted_descending(self):
        scores = [item["safety_score"] for item in self.report["top5_by_safety"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_hack_risk_protocols_is_list(self):
        self.assertIsInstance(self.report["hack_risk_protocols"], list)

    def test_no_hack_risk_protocols_for_seed_data(self):
        # All seed hacks are > 2 years old relative to REF_DATE
        self.assertEqual(self.report["hack_risk_protocols"], [])

    def test_reference_date_in_report(self):
        self.assertEqual(self.report["reference_date"], REF_DATE.isoformat())


# ---------------------------------------------------------------------------
# TestSaveLoad  (10 tests)
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):
    """save_registry() / load_registry() — persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reg = ProtocolRegistry(data_dir=self.tmpdir, reference_date=REF_DATE)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        self.reg.save_registry()
        self.assertTrue(Path(self.tmpdir, REGISTRY_FILENAME).exists())

    def test_save_returns_path_string(self):
        path = self.reg.save_registry()
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.exists(path))

    def test_saved_file_is_valid_json(self):
        self.reg.save_registry()
        raw = Path(self.tmpdir, REGISTRY_FILENAME).read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertIsInstance(data, dict)

    def test_saved_file_has_registry_key(self):
        self.reg.save_registry()
        raw = json.loads(Path(self.tmpdir, REGISTRY_FILENAME).read_text("utf-8"))
        self.assertIn("registry", raw)

    def test_round_trip_preserves_all_protocols(self):
        self.reg.save_registry()

        reg2 = ProtocolRegistry(data_dir=self.tmpdir, seed=False, reference_date=REF_DATE)
        count = reg2.load_registry()
        self.assertEqual(count, 15)
        self.assertEqual(set(reg2.list_all()), set(self.reg.list_all()))

    def test_load_adds_custom_protocol(self):
        self.reg.register("custom_abc", {"name": "Custom", "audits": []})
        self.reg.save_registry()

        reg2 = ProtocolRegistry(data_dir=self.tmpdir, seed=False, reference_date=REF_DATE)
        reg2.load_registry()
        self.assertIn("custom_abc", reg2)

    def test_load_missing_file_returns_zero(self):
        reg = ProtocolRegistry(data_dir=self.tmpdir, seed=False, reference_date=REF_DATE)
        count = reg.load_registry()
        self.assertEqual(count, 0)

    def test_load_malformed_json_returns_zero(self):
        bad_path = Path(self.tmpdir, REGISTRY_FILENAME)
        bad_path.write_text("NOT JSON {{{{", encoding="utf-8")
        reg = ProtocolRegistry(data_dir=self.tmpdir, seed=False, reference_date=REF_DATE)
        count = reg.load_registry()
        self.assertEqual(count, 0)

    def test_load_wrong_root_type_returns_zero(self):
        bad_path = Path(self.tmpdir, REGISTRY_FILENAME)
        bad_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        reg = ProtocolRegistry(data_dir=self.tmpdir, seed=False, reference_date=REF_DATE)
        count = reg.load_registry()
        self.assertEqual(count, 0)

    def test_no_tmp_files_left_after_save(self):
        self.reg.save_registry()
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


# ---------------------------------------------------------------------------
# TestImportHygiene  (3 tests)
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    """Ensure no forbidden imports exist in the module source."""

    def _src(self) -> str:
        import spa_core.analytics.protocol_registry as mod
        import inspect
        return inspect.getsource(mod)

    def test_no_external_library_imports(self):
        src = self._src()
        for lib in ("requests", "web3", "numpy", "pandas", "scipy",
                    "openai", "anthropic", "aiohttp", "httpx"):
            with self.subTest(lib=lib):
                self.assertNotIn(f"import {lib}", src)

    def test_no_forbidden_domain_imports(self):
        src = self._src()
        for domain in ("execution", "monitoring", "feed_health"):
            with self.subTest(domain=domain):
                self.assertNotIn(f"from spa_core.{domain}", src)
                self.assertNotIn(f"import spa_core.{domain}", src)

    def test_no_eval_exec_in_module(self):
        src = self._src()
        self.assertNotIn("eval(", src)
        self.assertNotIn("exec(", src)


# ---------------------------------------------------------------------------
# TestEdgeCases  (5 tests)
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Boundary value and miscellaneous edge cases."""

    def setUp(self):
        self.reg = ProtocolRegistry(seed=False, reference_date=REF_DATE)

    def test_safe_float_bool_returns_default(self):
        self.assertEqual(_safe_float(True, 99.0), 99.0)
        self.assertEqual(_safe_float(False, 42.0), 42.0)

    def test_safe_float_valid_string(self):
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_safe_float_invalid_string(self):
        self.assertEqual(_safe_float("abc", -1.0), -1.0)

    def test_parse_date_valid(self):
        self.assertEqual(_parse_date("2024-03-15"), date(2024, 3, 15))

    def test_parse_date_invalid_returns_date_min(self):
        self.assertEqual(_parse_date("bad-date"), date.min)


# ---------------------------------------------------------------------------
# Helper function tests (10 tests)
# ---------------------------------------------------------------------------

class TestHelperFunctions(unittest.TestCase):
    """Unit tests for module-level helper functions."""

    def test_firm_tier_pts_top(self):
        self.assertAlmostEqual(_firm_tier_pts("Trail of Bits"), 20.0)

    def test_firm_tier_pts_top_case_insensitive(self):
        self.assertAlmostEqual(_firm_tier_pts("OPENZEPPELIN"), 20.0)

    def test_firm_tier_pts_mid(self):
        self.assertAlmostEqual(_firm_tier_pts("certik"), 15.0)

    def test_firm_tier_pts_unknown(self):
        self.assertAlmostEqual(_firm_tier_pts("SomeRandomFirm"), 10.0)

    def test_audit_recency_under_1y(self):
        self.assertAlmostEqual(_audit_recency_factor(100), 1.0)

    def test_audit_recency_1_to_2_y(self):
        self.assertAlmostEqual(_audit_recency_factor(500), 0.8)

    def test_audit_recency_2_to_3_y(self):
        self.assertAlmostEqual(_audit_recency_factor(800), 0.6)

    def test_audit_recency_over_3_y(self):
        self.assertAlmostEqual(_audit_recency_factor(1200), 0.3)

    def test_tiered_score_first_match(self):
        bps = ((100, 10.0), (50, 5.0), (0, 1.0))
        self.assertAlmostEqual(_tiered_score(150.0, bps), 10.0)

    def test_tiered_score_no_match_returns_zero(self):
        bps = ((100, 10.0),)
        self.assertAlmostEqual(_tiered_score(50.0, bps), 0.0)


# ---------------------------------------------------------------------------
# TestSeedDataIntegrity  (10 tests)
# ---------------------------------------------------------------------------

class TestSeedDataIntegrity(unittest.TestCase):
    """Validate seed data quality and structure."""

    def setUp(self):
        self.reg = ProtocolRegistry(reference_date=REF_DATE)

    def test_all_seed_protocols_have_name(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertIn("name", entry)
                self.assertIsInstance(entry["name"], str)

    def test_all_seed_protocols_have_tier(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertIn("tier", entry)
                self.assertIn(entry["tier"], ("T1", "T2", "T3"))

    def test_all_seed_protocols_have_audits_list(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertIn("audits", entry)
                self.assertIsInstance(entry["audits"], list)

    def test_all_seed_protocols_have_hacks_list(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertIn("hacks", entry)
                self.assertIsInstance(entry["hacks"], list)

    def test_all_seed_protocols_have_positive_tvl(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertGreater(_safe_float(entry.get("tvl_usd", 0)), 0)

    def test_t1_protocols_have_higher_tvl_than_t2_on_average(self):
        t1_tvl = [self.reg.get(p)["tvl_usd"] for p in self.reg.list_all()
                  if self.reg.get(p).get("tier") == "T1"]
        t2_tvl = [self.reg.get(p)["tvl_usd"] for p in self.reg.list_all()
                  if self.reg.get(p).get("tier") == "T2"]
        avg_t1 = sum(t1_tvl) / len(t1_tvl)
        avg_t2 = sum(t2_tvl) / len(t2_tvl)
        self.assertGreater(avg_t1, avg_t2)

    def test_safety_scores_all_positive(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                self.assertGreater(self.reg.compute_safety_score(pid), 0.0)

    def test_all_protocols_have_launch_date(self):
        for pid in self.reg.list_all():
            with self.subTest(pid=pid):
                entry = self.reg.get(pid)
                self.assertIn("launch_date", entry)
                parsed = _parse_date(entry["launch_date"])
                self.assertNotEqual(parsed, date.min)

    def test_morpho_launched_after_2023(self):
        entry = self.reg.get("morpho")
        launch = _parse_date(entry["launch_date"])
        self.assertGreater(launch.year, 2023)

    def test_sky_launched_before_2020(self):
        entry = self.reg.get("sky")
        launch = _parse_date(entry["launch_date"])
        self.assertLess(launch.year, 2020)


if __name__ == "__main__":
    unittest.main(verbosity=2)
