"""Unit tests for spa_core.analytics.chain_exposure_report (MP-620).

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

from spa_core.analytics.chain_exposure_report import (
    CHAIN_CONCENTRATION_CAP,
    CHAIN_ORDER,
    L2_CHAINS,
    ChainExposure,
    ChainExposureReport,
    ChainExposureReportData,
    _normalize_chain,
    _parse_timestamp,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _contrib(adapter_id, chain, allocated, weight, apy=5.0, tier="T1",
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
# _normalize_chain
# ---------------------------------------------------------------------------


class TestNormalizeChain(unittest.TestCase):
    def test_ethereum(self):
        self.assertEqual(_normalize_chain("ethereum"), "ethereum")

    def test_uppercase(self):
        self.assertEqual(_normalize_chain("ETHEREUM"), "ethereum")

    def test_mixed_case(self):
        self.assertEqual(_normalize_chain("Arbitrum"), "arbitrum")

    def test_whitespace(self):
        self.assertEqual(_normalize_chain(" base "), "base")

    def test_empty(self):
        self.assertEqual(_normalize_chain(""), "UNKNOWN")

    def test_none(self):
        self.assertEqual(_normalize_chain(None), "UNKNOWN")

    def test_int(self):
        self.assertEqual(_normalize_chain(1), "UNKNOWN")

    def test_whitespace_only(self):
        self.assertEqual(_normalize_chain("   "), "UNKNOWN")

    def test_list(self):
        self.assertEqual(_normalize_chain(["ethereum"]), "UNKNOWN")


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    def test_cap_ethereum(self):
        self.assertEqual(CHAIN_CONCENTRATION_CAP["ethereum"], 70.0)

    def test_cap_only_ethereum(self):
        self.assertEqual(list(CHAIN_CONCENTRATION_CAP.keys()), ["ethereum"])

    def test_cap_no_arbitrum(self):
        self.assertNotIn("arbitrum", CHAIN_CONCENTRATION_CAP)

    def test_l2_chains(self):
        self.assertEqual(
            L2_CHAINS, {"arbitrum", "base", "optimism", "polygon"}
        )

    def test_l2_no_ethereum(self):
        self.assertNotIn("ethereum", L2_CHAINS)

    def test_chain_order(self):
        self.assertEqual(
            CHAIN_ORDER,
            ["ethereum", "arbitrum", "base", "optimism", "polygon", "UNKNOWN"],
        )

    def test_chain_order_unknown_last(self):
        self.assertEqual(CHAIN_ORDER[-1], "UNKNOWN")

    def test_chain_order_ethereum_first(self):
        self.assertEqual(CHAIN_ORDER[0], "ethereum")


# ---------------------------------------------------------------------------
# ChainExposure dataclass
# ---------------------------------------------------------------------------


class TestChainExposure(unittest.TestCase):
    def test_basic_fields(self):
        e = ChainExposure(
            chain="ethereum", allocated_usd=1000.0, weight_pct=50.0,
            adapter_count=2, adapters=["a", "b"],
        )
        self.assertEqual(e.chain, "ethereum")
        self.assertEqual(e.allocated_usd, 1000.0)
        self.assertEqual(e.weight_pct, 50.0)
        self.assertEqual(e.adapter_count, 2)

    def test_avg_apy_default(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertEqual(e.avg_apy_pct, 0.0)

    def test_is_l2_default(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertFalse(e.is_l2)

    def test_cap_none_default(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertIsNone(e.cap_pct)

    def test_within_cap_default_true(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertTrue(e.within_cap)

    def test_headroom_default_none(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertIsNone(e.headroom_pct)

    def test_annual_yield_default(self):
        e = ChainExposure("ethereum", 0.0, 0.0, 0)
        self.assertEqual(e.annual_yield_usd, 0.0)

    def test_to_dict_keys(self):
        e = ChainExposure("ethereum", 100.0, 30.0, 1, ["x"], 6.0, 6.0,
                          False, 70.0, True, 40.0)
        d = e.to_dict()
        for k in ("chain", "allocated_usd", "weight_pct", "adapter_count",
                  "adapters", "avg_apy_pct", "annual_yield_usd", "is_l2",
                  "cap_pct", "within_cap", "headroom_pct"):
            self.assertIn(k, d)

    def test_to_dict_json_serializable(self):
        e = ChainExposure("ethereum", 100.0, 30.0, 1, ["x"], 6.0, 6.0,
                          False, 70.0, True, 40.0)
        json.dumps(e.to_dict())

    def test_to_dict_headroom_none(self):
        e = ChainExposure("arbitrum", 100.0, 30.0, 1, ["x"], 6.0, 6.0,
                          True, None, True, None)
        d = e.to_dict()
        self.assertIsNone(d["headroom_pct"])

    def test_to_dict_cap_none(self):
        e = ChainExposure("arbitrum", 100.0, 30.0, 1, ["x"], 6.0, 6.0,
                          True, None, True, None)
        d = e.to_dict()
        self.assertIsNone(d["cap_pct"])

    def test_to_dict_adapters_list(self):
        e = ChainExposure("ethereum", 100.0, 30.0, 2, ["a", "b"], 6.0)
        d = e.to_dict()
        self.assertEqual(d["adapters"], ["a", "b"])

    def test_to_dict_is_l2_bool(self):
        e = ChainExposure("arbitrum", 100.0, 30.0, 1, ["x"], 6.0, 6.0, True)
        d = e.to_dict()
        self.assertTrue(d["is_l2"])

    def test_to_dict_rounding(self):
        e = ChainExposure("ethereum", 100.123456, 30.123456, 1, ["x"], 6.123456)
        d = e.to_dict()
        self.assertEqual(d["allocated_usd"], 100.12)


# ---------------------------------------------------------------------------
# is_l2 via compute
# ---------------------------------------------------------------------------


class TestIsL2(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def _chain(self, rep, chain):
        return next((e for e in rep.exposures if e.chain == chain), None)

    def test_ethereum_not_l2(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._chain(rep, "ethereum").is_l2)

    def test_arbitrum_l2(self):
        snap = _snapshot([_contrib("a", "arbitrum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "arbitrum").is_l2)

    def test_base_l2(self):
        snap = _snapshot([_contrib("a", "base", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "base").is_l2)

    def test_optimism_l2(self):
        snap = _snapshot([_contrib("a", "optimism", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "optimism").is_l2)

    def test_polygon_l2(self):
        snap = _snapshot([_contrib("a", "polygon", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "polygon").is_l2)

    def test_unknown_not_l2(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._chain(rep, "UNKNOWN").is_l2)


# ---------------------------------------------------------------------------
# weighted avg_apy (via compute)
# ---------------------------------------------------------------------------


class TestWeightedAvgApy(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def test_weighted_avg_apy(self):
        # ethereum: 1000@4% and 3000@8% -> weighted = (4000+24000)/4000 = 7
        snap = _snapshot([
            _contrib("a", "ethereum", 1000.0, 25.0, apy=4.0),
            _contrib("b", "ethereum", 3000.0, 75.0, apy=8.0),
        ])
        rep = self.r.compute_exposures(snap)
        eth = next(e for e in rep.exposures if e.chain == "ethereum")
        self.assertAlmostEqual(eth.avg_apy_pct, 7.0, places=6)

    def test_zero_capital_avg_apy(self):
        snap = _snapshot([_contrib("a", "ethereum", 0.0, 0.0, apy=5.0)])
        rep = self.r.compute_exposures(snap)
        eth = next(e for e in rep.exposures if e.chain == "ethereum")
        self.assertEqual(eth.avg_apy_pct, 0.0)

    def test_single_adapter_apy(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0, apy=4.2)])
        rep = self.r.compute_exposures(snap)
        eth = next(e for e in rep.exposures if e.chain == "ethereum")
        self.assertAlmostEqual(eth.avg_apy_pct, 4.2, places=6)


# ---------------------------------------------------------------------------
# Cap / within_cap / headroom (via compute) -- ethereum only
# ---------------------------------------------------------------------------


class TestCapLogic(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def _chain(self, rep, chain):
        return next(e for e in rep.exposures if e.chain == chain)

    def test_arbitrum_cap_none(self):
        snap = _snapshot([_contrib("a", "arbitrum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._chain(rep, "arbitrum").cap_pct)

    def test_arbitrum_headroom_none(self):
        snap = _snapshot([_contrib("a", "arbitrum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._chain(rep, "arbitrum").headroom_pct)

    def test_arbitrum_within_cap_true(self):
        snap = _snapshot([_contrib("a", "arbitrum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "arbitrum").within_cap)

    def test_base_cap_none(self):
        snap = _snapshot([_contrib("a", "base", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._chain(rep, "base").cap_pct)

    def test_unknown_cap_none(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNone(self._chain(rep, "UNKNOWN").cap_pct)

    def test_unknown_within_cap_true(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "UNKNOWN").within_cap)

    def test_ethereum_cap_70(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(self._chain(rep, "ethereum").cap_pct, 70.0)

    def test_ethereum_headroom(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(
            self._chain(rep, "ethereum").headroom_pct, 10.0, places=6
        )

    def test_ethereum_exactly_70_within(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 700.0, 70.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "ethereum").within_cap)

    def test_ethereum_70_01_breach(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 7001.0, 70.01),
            _contrib("b", "arbitrum", 2999.0, 29.99),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._chain(rep, "ethereum").within_cap)

    def test_ethereum_69_99_within(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 6999.0, 69.99),
            _contrib("b", "arbitrum", 3001.0, 30.01),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(self._chain(rep, "ethereum").within_cap)

    def test_ethereum_headroom_negative_on_breach(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 800.0, 80.0),
            _contrib("b", "arbitrum", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(
            self._chain(rep, "ethereum").headroom_pct, -10.0, places=6
        )

    def test_ethereum_100_breach(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(self._chain(rep, "ethereum").within_cap)


# ---------------------------------------------------------------------------
# concentration_label boundaries
# ---------------------------------------------------------------------------


class TestConcentrationLabel(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

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

    def test_label_one(self):
        self.assertEqual(self.r._concentration_label(1.0), "CONCENTRATED")


# ---------------------------------------------------------------------------
# load_latest_snapshot
# ---------------------------------------------------------------------------


class TestLoadLatestSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.r = ChainExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, content):
        path = os.path.join(self.tmp, ChainExposureReport.SOURCE_FILE)
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
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
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
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def _chain(self, rep, chain):
        return next((e for e in rep.exposures if e.chain == chain), None)

    def test_none_snapshot_empty(self):
        rep = self.r.compute_exposures({})
        self.assertEqual(rep.total_chains, 0)

    def test_no_contributions_empty(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertEqual(rep.total_chains, 0)
        self.assertEqual(rep.total_allocated_usd, 0.0)
        self.assertEqual(rep.exposures, [])
        self.assertEqual(rep.dominant_chain, "")
        self.assertEqual(rep.hhi, 0.0)
        self.assertEqual(rep.concentration_label, "DIVERSIFIED")
        self.assertEqual(rep.policy_status, "COMPLIANT")
        self.assertEqual(rep.portfolio_apy_pct, 0.0)
        self.assertEqual(rep.l2_weight_pct, 0.0)
        self.assertEqual(rep.ethereum_weight_pct, 0.0)

    def test_empty_report_valid_recommendations(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertTrue(len(rep.recommendations) >= 1)

    def test_non_dict_snapshot(self):
        rep = self.r.compute_exposures("not a dict")
        self.assertEqual(rep.total_chains, 0)

    def test_single_ethereum_100(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0, apy=4.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.total_chains, 1)
        self.assertAlmostEqual(rep.hhi, 1.0, places=6)
        self.assertEqual(rep.concentration_label, "CONCENTRATED")
        # 100% > 70% cap -> BREACH
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertEqual(rep.dominant_chain, "ethereum")

    def test_ethereum_60_arbitrum_40_compliant(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        # 0.6^2 + 0.4^2 = 0.36 + 0.16 = 0.52
        self.assertAlmostEqual(rep.hhi, 0.52, places=6)
        self.assertEqual(rep.concentration_label, "CONCENTRATED")
        self.assertEqual(rep.policy_status, "COMPLIANT")

    def test_ethereum_80_breach(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 800.0, 80.0),
            _contrib("b", "arbitrum", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertTrue(any("ethereum" in b for b in rep.breaches))

    def test_ethereum_breach_string_format(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 750.0, 75.0),
            _contrib("b", "arbitrum", 250.0, 25.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("ethereum 75.0% > cap 70.0%", rep.breaches)

    def test_l2_only_ethereum_weight_zero(self):
        snap = _snapshot([
            _contrib("a", "arbitrum", 500.0, 50.0),
            _contrib("b", "base", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.ethereum_weight_pct, 0.0)
        self.assertAlmostEqual(rep.l2_weight_pct, 100.0, places=6)
        self.assertEqual(rep.policy_status, "COMPLIANT")

    def test_l2_weight_sum(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
            _contrib("c", "base", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.l2_weight_pct, 50.0, places=6)

    def test_ethereum_weight_field(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 650.0, 65.0),
            _contrib("b", "arbitrum", 350.0, 35.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.ethereum_weight_pct, 65.0, places=6)

    def test_unknown_chain(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 800.0, 80.0),
            _contrib("b", None, 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        unk = self._chain(rep, "UNKNOWN")
        self.assertIsNotNone(unk)
        self.assertAlmostEqual(unk.weight_pct, 20.0, places=6)

    def test_unknown_empty_string_chain(self):
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._chain(rep, "UNKNOWN"))

    def test_missing_chain_key(self):
        c = {"adapter_id": "a", "allocated_usd": 1000.0, "weight_pct": 100.0,
             "apy_pct": 5.0, "annual_yield_usd": 50.0}
        rep = self.r.compute_exposures(_snapshot([c]))
        self.assertIsNotNone(self._chain(rep, "UNKNOWN"))

    def test_lowercase_chain_normalized(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._chain(rep, "ethereum"))

    def test_uppercase_chain_normalized(self):
        snap = _snapshot([_contrib("a", "ETHEREUM", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._chain(rep, "ethereum"))

    def test_mixed_case_chain_normalized(self):
        snap = _snapshot([_contrib("a", "Arbitrum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIsNotNone(self._chain(rep, "arbitrum"))

    def test_grouping_multiple_adapters_one_chain(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 300.0, 30.0),
            _contrib("b", "ethereum", 200.0, 20.0),
            _contrib("c", "ethereum", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        eth = self._chain(rep, "ethereum")
        self.assertEqual(eth.adapter_count, 3)
        self.assertAlmostEqual(eth.weight_pct, 100.0, places=6)
        self.assertAlmostEqual(eth.allocated_usd, 1000.0, places=6)

    def test_adapters_sorted(self):
        snap = _snapshot([
            _contrib("zebra", "ethereum", 300.0, 30.0),
            _contrib("alpha", "ethereum", 700.0, 70.0),
        ])
        rep = self.r.compute_exposures(snap)
        eth = self._chain(rep, "ethereum")
        self.assertEqual(eth.adapters, ["alpha", "zebra"])

    def test_annual_yield_summed(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0, annual_yield=25.0),
            _contrib("b", "ethereum", 500.0, 50.0, annual_yield=30.0),
        ])
        rep = self.r.compute_exposures(snap)
        eth = self._chain(rep, "ethereum")
        self.assertAlmostEqual(eth.annual_yield_usd, 55.0, places=6)

    def test_portfolio_apy_weighted(self):
        # 1000@4% and 1000@8% -> weighted = 6%
        snap = _snapshot([
            _contrib("a", "ethereum", 1000.0, 50.0, apy=4.0),
            _contrib("b", "arbitrum", 1000.0, 50.0, apy=8.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.portfolio_apy_pct, 6.0, places=6)

    def test_portfolio_apy_zero_when_no_capital(self):
        snap = _snapshot([_contrib("a", "ethereum", 0.0, 0.0, apy=5.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.portfolio_apy_pct, 0.0)

    def test_total_allocated(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.total_allocated_usd, 1000.0, places=6)

    def test_dominant_chain(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 700.0, 70.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.dominant_chain, "ethereum")
        self.assertAlmostEqual(rep.dominant_weight_pct, 70.0, places=6)

    def test_dominant_chain_arbitrum(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 300.0, 30.0),
            _contrib("b", "arbitrum", 700.0, 70.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.dominant_chain, "arbitrum")

    def test_exposures_sorted_by_chain_order(self):
        snap = _snapshot([
            _contrib("c", "base", 100.0, 10.0),
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
        ])
        rep = self.r.compute_exposures(snap)
        chains = [e.chain for e in rep.exposures]
        self.assertEqual(chains, ["ethereum", "arbitrum", "base"])

    def test_full_chain_order(self):
        snap = _snapshot([
            _contrib("e", "polygon", 100.0, 10.0),
            _contrib("d", "optimism", 100.0, 10.0),
            _contrib("c", "base", 100.0, 10.0),
            _contrib("b", "arbitrum", 100.0, 10.0),
            _contrib("a", "ethereum", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        chains = [e.chain for e in rep.exposures]
        self.assertEqual(
            chains,
            ["ethereum", "arbitrum", "base", "optimism", "polygon"],
        )

    def test_unknown_sorted_last(self):
        snap = _snapshot([
            _contrib("b", None, 100.0, 10.0),
            _contrib("a", "ethereum", 900.0, 90.0),
        ])
        rep = self.r.compute_exposures(snap)
        chains = [e.chain for e in rep.exposures]
        self.assertEqual(chains[-1], "UNKNOWN")

    def test_unknown_sorted_after_l2(self):
        snap = _snapshot([
            _contrib("c", None, 100.0, 10.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
            _contrib("a", "ethereum", 600.0, 60.0),
        ])
        rep = self.r.compute_exposures(snap)
        chains = [e.chain for e in rep.exposures]
        self.assertEqual(chains, ["ethereum", "arbitrum", "UNKNOWN"])

    def test_skips_non_dict_contributions(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 1000.0, 100.0),
            "not a dict",
            None,
        ])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.total_chains, 1)

    def test_snapshot_at_preserved(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)],
                         generated_at="2026-01-01T00:00:00Z")
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.snapshot_at, "2026-01-01T00:00:00Z")

    def test_generated_at_is_string(self):
        rep = self.r.compute_exposures(
            _snapshot([_contrib("a", "ethereum", 100.0, 100.0)])
        )
        self.assertIsInstance(rep.generated_at, str)

    def test_diversified_label(self):
        # 20 each over 5 chains -> 5 * 0.04 = 0.2 DIVERSIFIED
        snap = _snapshot([
            _contrib("a", "ethereum", 200.0, 20.0),
            _contrib("b", "arbitrum", 200.0, 20.0),
            _contrib("c", "base", 200.0, 20.0),
            _contrib("d", "optimism", 200.0, 20.0),
            _contrib("e", "polygon", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.2, places=6)
        self.assertEqual(rep.concentration_label, "DIVERSIFIED")

    def test_unknown_breach_none(self):
        # UNKNOWN has no cap so cannot breach
        snap = _snapshot([_contrib("a", "", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.policy_status, "COMPLIANT")


# ---------------------------------------------------------------------------
# recommendations
# ---------------------------------------------------------------------------


class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def test_rec_on_ethereum_breach(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("ethereum" in r.lower()
                            for r in rep.recommendations))

    def test_rec_on_high_concentration(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        # HHI 0.52 -> CONCENTRATED
        self.assertTrue(any("concentration" in r.lower()
                            for r in rep.recommendations))

    def test_rec_no_l2(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("L2" in r for r in rep.recommendations))

    def test_rec_unknown_chain(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
            _contrib("c", None, 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(any("UNKNOWN" in r for r in rep.recommendations))

    def test_rec_always_nonempty(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
            _contrib("c", "base", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertTrue(len(rep.recommendations) >= 1)

    def test_rec_l2_present_no_no_l2_note(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertFalse(any("No L2 exposure" in r
                             for r in rep.recommendations))


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def test_summary_format(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertIn("ethereum", rep.summary)
        self.assertIn("L2", rep.summary)
        self.assertIn("HHI", rep.summary)
        self.assertIn("COMPLIANT", rep.summary)

    def test_summary_breach(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertIn("BREACH", rep.summary)


# ---------------------------------------------------------------------------
# HHI precision
# ---------------------------------------------------------------------------


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def test_hhi_100(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 1.0, places=6)

    def test_hhi_50_50(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 500.0, 50.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.5, places=6)

    def test_hhi_60_40(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.52, places=6)

    def test_hhi_three_chains(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 500.0, 50.0),
            _contrib("b", "arbitrum", 300.0, 30.0),
            _contrib("c", "base", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        # 0.25 + 0.09 + 0.04 = 0.38
        self.assertAlmostEqual(rep.hhi, 0.38, places=6)

    def test_hhi_five_equal(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 200.0, 20.0),
            _contrib("b", "arbitrum", 200.0, 20.0),
            _contrib("c", "base", 200.0, 20.0),
            _contrib("d", "optimism", 200.0, 20.0),
            _contrib("e", "polygon", 200.0, 20.0),
        ])
        rep = self.r.compute_exposures(snap)
        self.assertAlmostEqual(rep.hhi, 0.2, places=6)


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        src = _tracker(_snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ]))
        with open(os.path.join(self.tmp, ChainExposureReport.SOURCE_FILE),
                  "w", encoding="utf-8") as fh:
            json.dump(src, fh)
        self.r = ChainExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _out_path(self):
        return os.path.join(self.tmp, ChainExposureReport.OUTPUT_FILE)

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
        self.assertEqual(data["source"], "chain_exposure_report")

    def test_ring_buffer_max_value(self):
        self.r.save_report()
        with open(self._out_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["ring_buffer_max"], 30)

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
        self.assertTrue(path.endswith(ChainExposureReport.OUTPUT_FILE))

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

    def test_no_tmp_leftover_many(self):
        for _ in range(5):
            self.r.save_report()
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# format_telegram_message
# ---------------------------------------------------------------------------


class TestFormatTelegram(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())

    def test_under_1500(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), 1500)

    def test_contains_chain(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Chain", msg)

    def test_contains_compliant(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("COMPLIANT", msg)

    def test_contains_breach(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("BREACH", msg)

    def test_contains_hhi(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("HHI", msg)

    def test_contains_apy(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("APY", msg)

    def test_contains_l2(self):
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
        ])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("L2", msg)

    def test_empty_report(self):
        rep = self.r.compute_exposures(_snapshot([]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Chain", msg)
        self.assertLessEqual(len(msg), 1500)

    def test_nonempty(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertTrue(len(msg) > 0)

    def test_truncation_large_input(self):
        contribs = [_contrib(f"adapter_{i}", f"chain_{i}", 100.0, 1.0)
                    for i in range(200)]
        rep = self.r.compute_exposures(_snapshot(contribs))
        msg = self.r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), 1500)

    def test_breach_lists_breaches(self):
        snap = _snapshot([_contrib("a", "ethereum", 1000.0, 100.0)])
        rep = self.r.compute_exposures(snap)
        msg = self.r.format_telegram_message(rep)
        self.assertIn("cap", msg)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict(unittest.TestCase):
    def setUp(self):
        self.r = ChainExposureReport(data_path=tempfile.mkdtemp())
        snap = _snapshot([
            _contrib("a", "ethereum", 600.0, 60.0),
            _contrib("b", "arbitrum", 400.0, 40.0),
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
                  "total_chains", "exposures", "dominant_chain",
                  "dominant_weight_pct", "hhi", "concentration_label",
                  "policy_status", "breaches", "portfolio_apy_pct",
                  "l2_weight_pct", "ethereum_weight_pct",
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

    def test_exposure_dict_has_is_l2(self):
        d = self.r.to_dict(self.rep)
        for e in d["exposures"]:
            self.assertIn("is_l2", e)


# ---------------------------------------------------------------------------
# ChainExposureReportData defaults
# ---------------------------------------------------------------------------


class TestReportDataDefaults(unittest.TestCase):
    def test_defaults(self):
        d = ChainExposureReportData(
            generated_at="x", snapshot_at="y",
            total_allocated_usd=0.0, total_chains=0,
        )
        self.assertEqual(d.policy_status, "COMPLIANT")
        self.assertEqual(d.concentration_label, "DIVERSIFIED")
        self.assertEqual(d.hhi, 0.0)
        self.assertEqual(d.breaches, [])
        self.assertEqual(d.exposures, [])
        self.assertEqual(d.l2_weight_pct, 0.0)
        self.assertEqual(d.ethereum_weight_pct, 0.0)

    def test_to_dict_serializable(self):
        d = ChainExposureReportData(
            generated_at="x", snapshot_at="y",
            total_allocated_usd=0.0, total_chains=0,
        )
        json.dumps(d.to_dict())


# ---------------------------------------------------------------------------
# Integration: load + compute + save
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # All-ethereum portfolio mirroring the live snapshot.
        src = _tracker(_snapshot([
            _contrib("compound_v3", "ethereum", 29803.17, 31.37, apy=4.8),
            _contrib("aave_v3", "ethereum", 31946.82, 33.63, apy=4.2),
            _contrib("yearn_v3", "ethereum", 11518.6, 12.12, apy=6.8),
            _contrib("euler_v2", "ethereum", 10212.78, 10.75, apy=7.4),
            _contrib("maple", "ethereum", 11518.6, 12.13, apy=5.6),
        ]))
        with open(os.path.join(self.tmp, ChainExposureReport.SOURCE_FILE),
                  "w", encoding="utf-8") as fh:
            json.dump(src, fh)
        self.r = ChainExposureReport(data_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end_all_ethereum_breach(self):
        rep = self.r.compute_exposures()
        # 100% ethereum > 70% cap -> BREACH, HHI ~ 1.0 CONCENTRATED
        self.assertEqual(rep.policy_status, "BREACH")
        self.assertEqual(rep.total_chains, 1)
        self.assertAlmostEqual(rep.hhi, 1.0, places=4)
        self.assertEqual(rep.concentration_label, "CONCENTRATED")

    def test_end_to_end_save(self):
        path = self.r.save_report()
        self.assertTrue(os.path.exists(path))
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_dominant_ethereum(self):
        rep = self.r.compute_exposures()
        self.assertEqual(rep.dominant_chain, "ethereum")

    def test_telegram_roundtrip(self):
        msg = self.r.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)
        self.assertIn("Chain", msg)

    def test_l2_weight_zero(self):
        rep = self.r.compute_exposures()
        self.assertEqual(rep.l2_weight_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
