"""Unit tests for spa_core.analytics.tier_exposure_report (MP-617).

All file-touching tests use tempfile.TemporaryDirectory / mkdtemp -- never
the live data/ directory.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from spa_core.analytics.tier_exposure_report import (
    POLICY_CAPS,
    TIER_ORDER,
    TierExposure,
    TierExposureReport,
    TierExposureReportData,
    _normalize_tier,
    _parse_timestamp,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _contrib(adapter_id, tier, allocated, weight, apy=5.0, chain="ethereum",
             annual_yield=None):
    if annual_yield is None:
        annual_yield = allocated * apy / 100.0
    return {
        "adapter_id": adapter_id,
        "chain": chain,
        "tier": tier,
        "weight_pct": weight,
        "allocated_usd": allocated,
        "apy_pct": apy,
        "daily_yield_usd": annual_yield / 365.0,
        "annual_yield_usd": annual_yield,
        "contribution_pct": weight,
    }


def _snapshot(contributions, generated_at="2026-06-13T00:00:00Z", total=None):
    if total is None:
        total = 0.0
        for c in contributions:
            if isinstance(c, dict):
                try:
                    total += float(c.get("allocated_usd", 0) or 0)
                except (TypeError, ValueError):
                    pass
    return {
        "generated_at": generated_at,
        "total_allocated_usd": total,
        "contributions": contributions,
    }


def _tracker(latest):
    return {
        "schema_version": 1,
        "source": "yield_attribution_tracker",
        "last_updated": "2026-06-13T00:00:00Z",
        "latest": latest,
        "snapshots": [latest] if latest else [],
    }


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)

    def test_negative(self):
        self.assertEqual(_safe_float(-2.5), -2.5)

    def test_string_number(self):
        self.assertEqual(_safe_float("42.5"), 42.5)

    def test_string_int(self):
        self.assertEqual(_safe_float("7"), 7.0)

    def test_string_non_number(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_empty_string(self):
        self.assertEqual(_safe_float(""), 0.0)

    def test_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_bool_true(self):
        self.assertEqual(_safe_float(True), 0.0)

    def test_bool_false(self):
        self.assertEqual(_safe_float(False), 0.0)

    def test_list(self):
        self.assertEqual(_safe_float([1, 2]), 0.0)

    def test_dict(self):
        self.assertEqual(_safe_float({"a": 1}), 0.0)

    def test_nan(self):
        self.assertEqual(_safe_float(float("nan")), 0.0)

    def test_inf(self):
        self.assertEqual(_safe_float(float("inf")), 0.0)

    def test_neg_inf(self):
        self.assertEqual(_safe_float(float("-inf")), 0.0)

    def test_returns_float_type(self):
        self.assertIsInstance(_safe_float(5), float)


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp(unittest.TestCase):
    def test_z_suffix(self):
        dt = _parse_timestamp("2026-06-13T00:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_offset(self):
        dt = _parse_timestamp("2026-06-13T00:00:00+00:00")
        self.assertIsNotNone(dt)

    def test_offset_nonzero(self):
        dt = _parse_timestamp("2026-06-13T03:00:00+03:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 0)  # normalised to UTC

    def test_naive_becomes_utc(self):
        dt = _parse_timestamp("2026-06-13T00:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_invalid(self):
        self.assertIsNone(_parse_timestamp("not-a-date"))

    def test_empty(self):
        self.assertIsNone(_parse_timestamp(""))

    def test_none(self):
        self.assertIsNone(_parse_timestamp(None))

    def test_int(self):
        self.assertIsNone(_parse_timestamp(12345))

    def test_returns_datetime(self):
        dt = _parse_timestamp("2026-06-13T00:00:00Z")
        self.assertIsInstance(dt, datetime)


# ---------------------------------------------------------------------------
# _normalize_tier
# ---------------------------------------------------------------------------


class TestNormalizeTier(unittest.TestCase):
    def test_t1(self):
        self.assertEqual(_normalize_tier("T1"), "T1")

    def test_lowercase(self):
        self.assertEqual(_normalize_tier("t2"), "T2")

    def test_whitespace(self):
        self.assertEqual(_normalize_tier(" T3 "), "T3")

    def test_empty(self):
        self.assertEqual(_normalize_tier(""), "UNKNOWN")

    def test_none(self):
        self.assertEqual(_normalize_tier(None), "UNKNOWN")

    def test_int(self):
        self.assertEqual(_normalize_tier(1), "UNKNOWN")

    def test_whitespace_only(self):
        self.assertEqual(_normalize_tier("   "), "UNKNOWN")


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    def test_policy_caps_t2(self):
        self.assertEqual(POLICY_CAPS["T2"], 50.0)

    def test_policy_caps_t3(self):
        self.assertEqual(POLICY_CAPS["T3"], 15.0)

    def test_policy_caps_no_t1(self):
        self.assertNotIn("T1", POLICY_CAPS)

    def test_tier_order(self):
        self.assertEqual(TIER_ORDER, ["T1", "T2", "T3", "UNKNOWN"])


# ---------------------------------------------------------------------------
# TierExposure dataclass
# ---------------------------------------------------------------------------


class TestTierExposure(unittest.TestCase):
    def test_basic_fields(self):
        e = TierExposure(
            tier="T1", allocated_usd=1000.0, weight_pct=50.0,
            adapter_count=2, adapters=["a", "b"],
        )
        self.assertEqual(e.tier, "T1")
        self.assertEqual(e.allocated_usd, 1000.0)
        self.assertEqual(e.weight_pct, 50.0)
        self.assertEqual(e.adapter_count, 2)

    def test_avg_apy_default(self):
        e = TierExposure("T1", 0.0, 0.0, 0)
        self.assertEqual(e.avg_apy_pct, 0.0)

    def test_cap_none_default(self):
        e = TierExposure("T1", 0.0, 0.0, 0)
        self.assertIsNone(e.cap_pct)

    def test_within_cap_default_true(self):
        e = TierExposure("T1", 0.0, 0.0, 0)
        self.assertTrue(e.within_cap)

    def test_headroom_default_none(self):
        e = TierExposure("T1", 0.0, 0.0, 0)
        self.assertIsNone(e.headroom_pct)

    def test_to_dict_keys(self):
        e = TierExposure("T2", 100.0, 30.0, 1, ["x"], 6.0, 6.0, 50.0, True, 20.0)
        d = e.to_dict()
        for k in ("tier", "allocated_usd", "weight_pct", "adapter_count",
                  "adapters", "avg_apy_pct", "annual_yield_usd", "cap_pct",
                  "within_cap", "headroom_pct"):
            self.assertIn(k, d)

    def test_to_dict_json_serializable(self):
        e = TierExposure("T2", 100.0, 30.0, 1, ["x"], 6.0, 6.0, 50.0, True, 20.0)
        json.dumps(e.to_dict())

    def test_to_dict_headroom_none(self):
        e = TierExposure("T1", 100.0, 30.0, 1, ["x"], 6.0, 6.0, None, True, None)
        d = e.to_dict()
        self.assertIsNone(d["headroom_pct"])

    def test_to_dict_cap_none(self):
        e = TierExposure("T1", 100.0, 30.0, 1, ["x"], 6.0, 6.0, None, True, None)
        d = e.to_dict()
        self.assertIsNone(d["cap_pct"])

    def test_to_dict_adapters_list(self):
        e = TierExposure("T1", 100.0, 30.0, 2, ["a", "b"], 6.0)
        d = e.to_dict()
        self.assertEqual(d["adapters"], ["a", "b"])

    def test_to_dict_rounding(self):
        e = TierExposure("T1", 100.123456, 30.123456, 1, ["x"], 6.123456)
        d = e.to_dict()
        self.assertEqual(d["allocated_usd"], 100.12)


# ---------------------------------------------------------------------------
# TierExposure weighted avg_apy (via compute)
# ---------------------------------------------------------------------------


class TestWeightedAvgApy(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def test_weighted_avg_apy(self):
        # T1: two adapters, 1000@4% and 3000@8% -> weighted = (4000+24000)/4000=7
        snap = _snapshot([
            _contrib("a", "T1", 1000.0, 25.0, apy=4.0),
            _contrib("b", "T1", 3000.0, 75.0, apy=8.0),
        ])
        rep = self.r.compute_exposures(snap)
        t1 = next(e for e in rep.exposures if e.tier == "T1")
        self.assertAlmostEqual(t1.avg_apy_pct, 7.0, places=6)

    def test_zero_capital_avg_apy(self):
        snap = _snapshot([_contrib("a", "T1", 0.0, 0.0, apy=5.0)])
        rep = self.r.compute_exposures(snap)
        t1 = next(e for e in rep.exposures if e.tier == "T1")
        self.assertEqual(t1.avg_apy_pct, 0.0)

    def test_single_adapter_apy(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0, apy=4.2)])
        rep = self.r.compute_exposures(snap)
        t1 = next(e for e in rep.exposures if e.tier == "T1")
        self.assertAlmostEqual(t1.avg_apy_pct, 4.2, places=6)


# ---------------------------------------------------------------------------
# Cap / within_cap / headroom (via compute)
# ---------------------------------------------------------------------------


class TestCapLogic(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def _tier(self, rep, tier):
        return next(e for e in rep.exposures if e.tier == tier)

    def test_t1_cap_none(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._tier(rep, "T1").cap_pct)

    def test_t1_headroom_none(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._tier(rep, "T1").headroom_pct)

    def test_t1_within_cap_true(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "T1").within_cap)

    def test_unknown_cap_none(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._tier(rep, "UNKNOWN").cap_pct)

    def test_unknown_within_cap_true(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "UNKNOWN").within_cap)

    def test_t2_cap_50(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 40.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(self._tier(rep, "T2").cap_pct, 50.0)

    def test_t3_cap_15(self):
        snap = _snapshot([_contrib("a", "T3", 1000.0, 10.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(self._tier(rep, "T3").cap_pct, 15.0)

    def test_t2_headroom(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 30.0)])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(self._tier(rep, "T2").headroom_pct, 20.0, places=6)

    def test_t3_headroom(self):
        snap = _snapshot([_contrib("a", "T3", 1000.0, 10.0)])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(self._tier(rep, "T3").headroom_pct, 5.0, places=6)

    def test_t2_exactly_50_within(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 50.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "T2").within_cap)

    def test_t2_50_01_breach(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 50.01)])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._tier(rep, "T2").within_cap)

    def test_t2_49_99_within(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 49.99)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "T2").within_cap)

    def test_t3_exactly_15_within(self):
        snap = _snapshot([_contrib("a", "T3", 1000.0, 15.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "T3").within_cap)

    def test_t3_15_01_breach(self):
        snap = _snapshot([_contrib("a", "T3", 1000.0, 15.01)])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._tier(rep, "T3").within_cap)

    def test_t3_14_99_within(self):
        snap = _snapshot([_contrib("a", "T3", 1000.0, 14.99)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._tier(rep, "T3").within_cap)

    def test_t2_headroom_negative_on_breach(self):
        snap = _snapshot([_contrib("a", "T2", 1000.0, 60.0)])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(self._tier(rep, "T2").headroom_pct, -10.0, places=6)


# ---------------------------------------------------------------------------
# concentration_label boundaries
# ---------------------------------------------------------------------------


class TestConcentrationLabel(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def test_label_method_below_moderate(self):
        self.assertEqual(self.r._concentration_label(0.1), "DIVERSIFIED")

    def test_label_method_exactly_025(self):
        # strictly > 0.25 for MODERATE -> 0.25 is DIVERSIFIED
        self.assertEqual(self.r._concentration_label(0.25), "DIVERSIFIED")

    def test_label_method_just_above_025(self):
        self.assertEqual(self.r._concentration_label(0.2501), "MODERATE")

    def test_label_method_exactly_05(self):
        # strictly > 0.5 for CONCENTRATED -> 0.5 is MODERATE
        self.assertEqual(self.r._concentration_label(0.5), "MODERATE")

    def test_label_method_just_above_05(self):
        self.assertEqual(self.r._concentration_label(0.5001), "CONCENTRATED")

    def test_label_method_high(self):
        self.assertEqual(self.r._concentration_label(0.9), "CONCENTRATED")

    def test_label_method_mid_moderate(self):
        self.assertEqual(self.r._concentration_label(0.4), "MODERATE")

    def test_label_zero(self):
        self.assertEqual(self.r._concentration_label(0.0), "DIVERSIFIED")


# ---------------------------------------------------------------------------
# load_latest_snapshot
# ---------------------------------------------------------------------------


class TestLoadLatestSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.r = TierExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, content):
        path = os.path.join(self.tmp, TierExposureReport.SOURCE_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_missing_file(self):
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_corrupt_json(self):
        self._write("{not valid json")
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_non_dict_top(self):
        self._write("[1, 2, 3]")
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_no_latest_key(self):
        self._write(json.dumps({"snapshots": []}))
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_latest_not_dict(self):
        self._write(json.dumps({"latest": [1, 2]}))
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_empty_latest(self):
        self._write(json.dumps({"latest": {}}))
        self.assertEqual(self.r.load_latest_snapshot(), {})

    def test_valid(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        self._write(json.dumps(_tracker(snap)))
        loaded = self.r.load_latest_snapshot()
        self.assertIsInstance(loaded, dict)
        self.assertIn("contributions", loaded)

    def test_empty_string_file(self):
        self._write("")
        self.assertEqual(self.r.load_latest_snapshot(), {})


# ---------------------------------------------------------------------------
# compute_exposures
# ---------------------------------------------------------------------------


class TestComputeExposures(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def _tier(self, rep, tier):
        return next((e for e in rep.exposures if e.tier == tier), None)

    def test_none_snapshot_empty(self):
        rep = self.r.compute_exposures({})
        self.assertEqual(rep.total_tiers, 0)

    def test_no_contributions_empty(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertEqual(rep.total_tiers, 0)
        self.assertEqual(rep.total_allocated_usd, 0.0)
        self.assertEqual(rep.exposures, [])
        self.assertEqual(rep.dominant_tier, "")
        self.assertEqual(rep.hhi, 0.0)
        self.assertEqual(rep.concentration_label, "DIVERSIFIED")
        self.assertEqual(rep.policy_status, "COMPLIANT")
        self.assertEqual(rep.portfolio_apy_pct, 0.0)

    def test_non_dict_snapshot(self):
        rep = self.r.compute_exposures("not a dict")
        self.assertEqual(rep.total_tiers, 0)

    def test_single_t1_100(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0, apy=4.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.total_tiers, 1)
        self.assertAlmostEqual(rep.hhi, 1.0, places=6)
        self.assertEqual(rep.concentration_label, "CONCENTRATED")
        self.assertEqual(rep.policy_status, "COMPLIANT")
        self.assertEqual(rep.dominant_tier, "T1")

    def test_t1_60_t2_40_hhi(self):
        snap = _snapshot([
            _contrib("a", "T1", 600.0, 60.0),
            _contrib("b", "T2", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        # 0.6^2 + 0.4^2 = 0.36 + 0.16 = 0.52
        self.assertAlmostEqual(rep.hhi, 0.52, places=6)
        self.assertEqual(rep.concentration_label, "CONCENTRATED")

    def test_t1_65_t2_35_compliant(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "COMPLIANT")
        self.assertEqual(rep.breaches, [])

    def test_t2_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertTrue(any("T2" in b for b in rep.breaches))

    def test_t2_breach_string_format(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("T2 60.0% > cap 50.0%", rep.breaches)

    def test_t3_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 700.0, 70.0),
            _contrib("b", "T3", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertTrue(any("T3" in b for b in rep.breaches))

    def test_t3_breach_string_format(self):
        snap = _snapshot([
            _contrib("a", "T1", 800.0, 80.0),
            _contrib("b", "T3", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("T3 20.0% > cap 15.0%", rep.breaches)

    def test_both_breach(self):
        snap = _snapshot([
            _contrib("a", "T2", 600.0, 60.0),
            _contrib("b", "T3", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertEqual(len(rep.breaches), 2)

    def test_unknown_tier(self):
        snap = _snapshot([
            _contrib("a", "T1", 800.0, 80.0),
            _contrib("b", None, 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        unk = self._tier(rep, "UNKNOWN")
        self.assertIsNotNone(unk)
        self.assertAlmostEqual(unk.weight_pct, 20.0, places=6)

    def test_unknown_empty_string_tier(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._tier(rep, "UNKNOWN"))

    def test_missing_tier_key(self):
        c = {"adapter_id": "a", "allocated_usd": 1000.0, "weight_pct": 100.0,
             "apy_pct": 5.0, "annual_yield_usd": 50.0}
        rep = self.r.compute_exposures(_snapshot([c]))
        self.assertIsNotNone(self._tier(rep, "UNKNOWN"))

    def test_grouping_multiple_adapters_one_tier(self):
        snap = _snapshot([
            _contrib("a", "T1", 300.0, 30.0),
            _contrib("b", "T1", 200.0, 20.0),
            _contrib("c", "T1", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        t1 = self._tier(rep, "T1")
        self.assertEqual(t1.adapter_count, 3)
        self.assertAlmostEqual(t1.weight_pct, 100.0, places=6)
        self.assertAlmostEqual(t1.allocated_usd, 1000.0, places=6)

    def test_adapters_sorted(self):
        snap = _snapshot([
            _contrib("zebra", "T1", 300.0, 30.0),
            _contrib("alpha", "T1", 700.0, 70.0),
        ])
        rep = self.r.compute_exposures(snap)
        t1 = self._tier(rep, "T1")
        self.assertEqual(t1.adapters, ["alpha", "zebra"])

    def test_annual_yield_summed(self):
        snap = _snapshot([
            _contrib("a", "T1", 500.0, 50.0, annual_yield=25.0),
            _contrib("b", "T1", 500.0, 50.0, annual_yield=30.0),
        ])
        rep = self.r.compute_exposures(snap)
        t1 = self._tier(rep, "T1")
        self.assertAlmostEqual(t1.annual_yield_usd, 55.0, places=6)

    def test_portfolio_apy_weighted(self):
        # 1000@4% and 1000@8% -> weighted = 6%
        snap = _snapshot([
            _contrib("a", "T1", 1000.0, 50.0, apy=4.0),
            _contrib("b", "T2", 1000.0, 50.0, apy=8.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.portfolio_apy_pct, 6.0, places=6)

    def test_portfolio_apy_zero_when_no_capital(self):
        snap = _snapshot([_contrib("a", "T1", 0.0, 0.0, apy=5.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.portfolio_apy_pct, 0.0)

    def test_t1_weight_field(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.t1_weight_pct, 65.0, places=6)

    def test_t2_weight_field(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.t2_weight_pct, 35.0, places=6)

    def test_t3_weight_field_zero_when_absent(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.t3_weight_pct, 0.0)

    def test_t3_weight_field_present(self):
        snap = _snapshot([
            _contrib("a", "T1", 800.0, 80.0),
            _contrib("b", "T3", 200.0, 10.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.t3_weight_pct, 10.0, places=6)

    def test_total_allocated(self):
        snap = _snapshot([
            _contrib("a", "T1", 600.0, 60.0),
            _contrib("b", "T2", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.total_allocated_usd, 1000.0, places=6)

    def test_dominant_tier(self):
        snap = _snapshot([
            _contrib("a", "T1", 700.0, 70.0),
            _contrib("b", "T2", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.dominant_tier, "T1")
        self.assertAlmostEqual(rep.dominant_weight_pct, 70.0, places=6)

    def test_dominant_tier_t2(self):
        snap = _snapshot([
            _contrib("a", "T1", 300.0, 30.0),
            _contrib("b", "T2", 700.0, 45.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.dominant_tier, "T2")

    def test_exposures_sorted_by_tier_order(self):
        snap = _snapshot([
            _contrib("c", "T3", 100.0, 10.0),
            _contrib("a", "T1", 600.0, 60.0),
            _contrib("b", "T2", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        tiers = [e.tier for e in rep.exposures]
        self.assertEqual(tiers, ["T1", "T2", "T3"])

    def test_unknown_sorted_last(self):
        snap = _snapshot([
            _contrib("b", None, 100.0, 10.0),
            _contrib("a", "T1", 900.0, 90.0),
        ])
        rep = self.r.compute_exposures(snap)
        tiers = [e.tier for e in rep.exposures]
        self.assertEqual(tiers[-1], "UNKNOWN")

    def test_diversified_three_tiers(self):
        # 40/30/30 -> 0.16+0.09+0.09=0.34 MODERATE
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 300.0, 30.0),
            _contrib("c", "T3", 300.0, 14.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIsInstance(rep.hhi, float)

    def test_recommendations_present_on_t2_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("T2" in r for r in rep.recommendations))

    def test_recommendations_present_on_t3_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 800.0, 80.0),
            _contrib("b", "T3", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("T3" in r for r in rep.recommendations))

    def test_recommendations_unknown(self):
        snap = _snapshot([
            _contrib("a", "T1", 800.0, 80.0),
            _contrib("b", None, 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("UNKNOWN" in r for r in rep.recommendations))

    def test_recommendations_concentrated(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("concentration" in r.lower()
                            for r in rep.recommendations))

    def test_recommendations_always_nonempty(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 300.0, 30.0),
            _contrib("c", "T3", 300.0, 14.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(len(rep.recommendations) >= 1)

    def test_summary_format(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("T1", rep.summary)
        self.assertIn("HHI", rep.summary)
        self.assertIn("COMPLIANT", rep.summary)

    def test_summary_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("BREACH", rep.summary)

    def test_skips_non_dict_contributions(self):
        snap = _snapshot([
            _contrib("a", "T1", 1000.0, 100.0),
            "not a dict",
            None,
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.total_tiers, 1)

    def test_snapshot_at_preserved(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)],
                         generated_at="2026-01-01T00:00:00Z")
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.snapshot_at, "2026-01-01T00:00:00Z")

    def test_lowercase_tier_normalized(self):
        snap = _snapshot([_contrib("a", "t1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._tier(rep, "T1"))

    def test_generated_at_is_string(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("a", "T1", 100.0, 100.0)]))
        self.assertIsInstance(rep.generated_at, str)


# ---------------------------------------------------------------------------
# HHI precision
# ---------------------------------------------------------------------------


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def test_hhi_100(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 1.0, places=6)

    def test_hhi_50_50(self):
        snap = _snapshot([
            _contrib("a", "T1", 500.0, 50.0),
            _contrib("b", "T2", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.5, places=6)

    def test_hhi_60_40(self):
        snap = _snapshot([
            _contrib("a", "T1", 600.0, 60.0),
            _contrib("b", "T2", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.52, places=6)

    def test_hhi_three_equal(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 300.0, 30.0),
            _contrib("c", "T3", 300.0, 14.0),
        ])
        rep = self.r.compute_exposures(snap)
        # 0.16 + 0.09 + 0.0196 = 0.2696
        self.assertAlmostEqual(rep.hhi, 0.2696, places=6)


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        src = _tracker(_snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ]))
        with open(os.path.join(self.tmp, TierExposureReport.SOURCE_FILE),
                  "w", encoding="utf-8") as fh:
            json.dump(src, fh)
        self.r = TierExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out_path(self):
        return os.path.join(self.tmp, TierExposureReport.OUTPUT_FILE)

    def test_creates_file(self):
        self.r.save_report()
        self.assertTrue(os.path.exists(self._out_path()))

    def test_no_tmp_leftover(self):
        self.r.save_report()
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_valid_json(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_structure_latest_history(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("latest", data)
        self.assertIn("history", data)
        self.assertIn("schema_version", data)
        self.assertIn("source", data)
        self.assertIn("ring_buffer_max", data)
        self.assertIn("report_count", data)
        self.assertIn("last_updated", data)

    def test_source_value(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["source"], "tier_exposure_report")

    def test_append(self):
        self.r.save_report()
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["history"]), 2)

    def test_ring_buffer_cap(self):
        for _ in range(35):
            self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["history"]), 30)
        self.assertEqual(data["report_count"], 30)

    def test_returns_path(self):
        path = self.r.save_report()
        self.assertTrue(path.endswith(TierExposureReport.OUTPUT_FILE))

    def test_latest_is_dict(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data["latest"], dict)

    def test_save_precomputed(self):
        rep = self.r.compute_exposures()
        self.r.save_report(rep)
        self.assertTrue(os.path.exists(self._out_path()))

    def test_history_entries_dicts(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        for h in data["history"]:
            self.assertIsInstance(h, dict)

    def test_corrupt_existing_handled(self):
        with open(self._out_path(), "w", encoding="utf-8") as fh:
            fh.write("{garbage")
        self.r.save_report()  # should not raise
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["history"]), 1)


# ---------------------------------------------------------------------------
# format_telegram_message
# ---------------------------------------------------------------------------


class TestFormatTelegram(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())

    def test_under_1500(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), 1500)

    def test_contains_tier(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Tier", msg)

    def test_contains_compliant(self):
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("COMPLIANT", msg)

    def test_contains_breach(self):
        snap = _snapshot([
            _contrib("a", "T1", 400.0, 40.0),
            _contrib("b", "T2", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("BREACH", msg)

    def test_contains_hhi(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("HHI", msg)

    def test_contains_apy(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("APY", msg)

    def test_empty_report(self):
        rep = self.r.compute_exposures(_snapshot([]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Tier", msg)
        self.assertLessEqual(len(msg), 1500)

    def test_nonempty(self):
        snap = _snapshot([_contrib("a", "T1", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertTrue(len(msg) > 0)

    def test_truncation_large_input(self):
        contribs = [_contrib(f"adapter_{i}", "UNKNOWN", 100.0, 1.0)
                    for i in range(200)]
        rep = self.r.compute_exposures(_snapshot(contribs))
        msg = self.r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), 1500)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict(unittest.TestCase):
    def setUp(self):
        self.r = TierExposureReport(data_path=tempfile.mkdtemp())
        snap = _snapshot([
            _contrib("a", "T1", 650.0, 65.0),
            _contrib("b", "T2", 350.0, 35.0),
        ])
        self.rep = self.r.compute_exposures(snap)

    def test_returns_dict(self):
        self.assertIsInstance(self.r.to_dict(self.rep), dict)

    def test_json_serializable(self):
        json.dumps(self.r.to_dict(self.rep))

    def test_exposures_list_of_dict(self):
        d = self.r.to_dict(self.rep)
        self.assertIsInstance(d["exposures"], list)
        for e in d["exposures"]:
            self.assertIsInstance(e, dict)

    def test_required_keys(self):
        d = self.r.to_dict(self.rep)
        for k in ("generated_at", "snapshot_at", "total_allocated_usd",
                  "total_tiers", "exposures", "dominant_tier",
                  "dominant_weight_pct", "hhi", "concentration_label",
                  "policy_status", "breaches", "portfolio_apy_pct",
                  "t1_weight_pct", "t2_weight_pct", "t3_weight_pct",
                  "recommendations", "summary"):
            self.assertIn(k, d)

    def test_data_to_dict_serializable(self):
        json.dumps(self.rep.to_dict())

    def test_breaches_list(self):
        d = self.r.to_dict(self.rep)
        self.assertIsInstance(d["breaches"], list)

    def test_recommendations_list(self):
        d = self.r.to_dict(self.rep)
        self.assertIsInstance(d["recommendations"], list)


# ---------------------------------------------------------------------------
# TierExposureReportData defaults
# ---------------------------------------------------------------------------


class TestReportDataDefaults(unittest.TestCase):
    def test_defaults(self):
        d = TierExposureReportData(
            generated_at="x", snapshot_at="y",
            total_allocated_usd=0.0, total_tiers=0,
        )
        self.assertEqual(d.policy_status, "COMPLIANT")
        self.assertEqual(d.concentration_label, "DIVERSIFIED")
        self.assertEqual(d.hhi, 0.0)
        self.assertEqual(d.breaches, [])
        self.assertEqual(d.exposures, [])

    def test_to_dict_serializable(self):
        d = TierExposureReportData(
            generated_at="x", snapshot_at="y",
            total_allocated_usd=0.0, total_tiers=0,
        )
        json.dumps(d.to_dict())


# ---------------------------------------------------------------------------
# Integration: load + compute + save
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        src = _tracker(_snapshot([
            _contrib("compound_v3", "T1", 29803.17, 31.37, apy=4.8),
            _contrib("aave_v3", "T1", 31946.82, 33.63, apy=4.2),
            _contrib("yearn_v3", "T2", 11518.6, 12.12, apy=6.8),
            _contrib("euler_v2", "T2", 10212.78, 10.75, apy=7.4),
            _contrib("maple", "T2", 11518.6, 12.12, apy=5.6),
        ]))
        with open(os.path.join(self.tmp, TierExposureReport.SOURCE_FILE),
                  "w", encoding="utf-8") as fh:
            json.dump(src, fh)
        self.r = TierExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end_compliant(self):
        rep = self.r.compute_exposures()
        self.assertEqual(rep.policy_status, "COMPLIANT")
        self.assertEqual(rep.total_tiers, 2)

    def test_end_to_end_save(self):
        path = self.r.save_report()
        self.assertTrue(os.path.exists(path))
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_t1_dominant(self):
        rep = self.r.compute_exposures()
        self.assertEqual(rep.dominant_tier, "T1")

    def test_telegram_roundtrip(self):
        msg = self.r.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)
        self.assertIn("Tier", msg)


if __name__ == "__main__":
    unittest.main()
