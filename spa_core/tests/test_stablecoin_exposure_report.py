"""Unit tests for spa_core.analytics.stablecoin_exposure_report (MP-611).

All file-touching tests use tempfile.TemporaryDirectory -- never the live data/.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone

from spa_core.analytics.stablecoin_exposure_report import (
    ADAPTER_STABLECOIN_MAP,
    StablecoinExposure,
    StablecoinExposureReport,
    StablecoinExposureReportData,
    resolve_stablecoin,
)


def _contrib(adapter_id, allocated, weight, apy=5.0, chain="ethereum"):
    return {
        "adapter_id": adapter_id,
        "chain": chain,
        "tier": "core",
        "weight_pct": weight,
        "allocated_usd": allocated,
        "apy_pct": apy,
        "annual_yield_usd": allocated * apy / 100.0,
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


def _tracker(snapshots):
    return {
        "schema_version": 1,
        "source": "yield_attribution_tracker",
        "last_updated": "2026-06-13T00:00:00Z",
        "snapshots": snapshots,
    }


# ---------------------------------------------------------------------------
# resolve_stablecoin
# ---------------------------------------------------------------------------


class TestResolveStablecoinExact(unittest.TestCase):
    def test_compound_v3(self):
        self.assertEqual(resolve_stablecoin("compound_v3"), "USDC")

    def test_aave_v3(self):
        self.assertEqual(resolve_stablecoin("aave_v3"), "USDC")

    def test_euler_v2(self):
        self.assertEqual(resolve_stablecoin("euler_v2"), "USDC")

    def test_maple(self):
        self.assertEqual(resolve_stablecoin("maple"), "USDC")

    def test_yearn_v3(self):
        self.assertEqual(resolve_stablecoin("yearn_v3"), "USDC")

    def test_frax(self):
        self.assertEqual(resolve_stablecoin("frax"), "FRAX")

    def test_sfrax(self):
        self.assertEqual(resolve_stablecoin("sfrax"), "FRAX")

    def test_sdai(self):
        self.assertEqual(resolve_stablecoin("sdai"), "DAI")

    def test_spark_susds(self):
        self.assertEqual(resolve_stablecoin("spark_susds"), "USDS")

    def test_scrvusd(self):
        self.assertEqual(resolve_stablecoin("scrvusd"), "crvUSD")

    def test_susde(self):
        self.assertEqual(resolve_stablecoin("susde"), "USDe")

    def test_wusdm(self):
        self.assertEqual(resolve_stablecoin("wusdm"), "USDM")

    def test_stusd(self):
        self.assertEqual(resolve_stablecoin("stusd"), "USDC")

    def test_pendle_pt(self):
        self.assertEqual(resolve_stablecoin("pendle_pt"), "USDC")

    def test_morpho_blue(self):
        self.assertEqual(resolve_stablecoin("morpho_blue"), "USDC")

    def test_all_map_keys_resolve(self):
        for k, v in ADAPTER_STABLECOIN_MAP.items():
            self.assertEqual(resolve_stablecoin(k), v)


class TestResolveStablecoinCaseInsensitive(unittest.TestCase):
    def test_upper(self):
        self.assertEqual(resolve_stablecoin("COMPOUND_V3"), "USDC")

    def test_mixed(self):
        self.assertEqual(resolve_stablecoin("Aave_V3"), "USDC")

    def test_frax_upper(self):
        self.assertEqual(resolve_stablecoin("FRAX"), "FRAX")

    def test_sdai_upper(self):
        self.assertEqual(resolve_stablecoin("SDAI"), "DAI")


class TestResolveStablecoinPrefix(unittest.TestCase):
    def test_prefix_aave_v3_suffix(self):
        # "aave_v3_v2" startswith "aave_v3"
        self.assertEqual(resolve_stablecoin("aave_v3_v2"), "USDC")

    def test_prefix_frax_suffix(self):
        self.assertEqual(resolve_stablecoin("frax_lend"), "FRAX")

    def test_prefix_susde(self):
        self.assertEqual(resolve_stablecoin("susde_vault"), "USDe")

    def test_prefix_case_insensitive(self):
        self.assertEqual(resolve_stablecoin("MAPLE_POOL"), "USDC")


class TestResolveStablecoinUnknown(unittest.TestCase):
    def test_unknown_string(self):
        self.assertEqual(resolve_stablecoin("totally_new_proto"), "UNKNOWN")

    def test_empty(self):
        self.assertEqual(resolve_stablecoin(""), "UNKNOWN")

    def test_none(self):
        self.assertEqual(resolve_stablecoin(None), "UNKNOWN")

    def test_int(self):
        self.assertEqual(resolve_stablecoin(123), "UNKNOWN")

    def test_list(self):
        self.assertEqual(resolve_stablecoin(["x"]), "UNKNOWN")

    def test_no_prefix_match(self):
        self.assertEqual(resolve_stablecoin("zzz_unknown"), "UNKNOWN")


# ---------------------------------------------------------------------------
# StablecoinExposure
# ---------------------------------------------------------------------------


class TestStablecoinExposure(unittest.TestCase):
    def test_to_dict_keys(self):
        e = StablecoinExposure("USDC", 1000.0, 50.0, 2, ["aave_v3", "maple"], 4.5)
        d = e.to_dict()
        for key in ("symbol", "allocated_usd", "weight_pct", "adapter_count",
                    "adapters", "avg_apy_pct"):
            self.assertIn(key, d)

    def test_to_dict_values(self):
        e = StablecoinExposure("USDC", 1000.0, 50.0, 2, ["aave_v3", "maple"], 4.5)
        d = e.to_dict()
        self.assertEqual(d["symbol"], "USDC")
        self.assertAlmostEqual(d["allocated_usd"], 1000.0)
        self.assertAlmostEqual(d["weight_pct"], 50.0)
        self.assertEqual(d["adapter_count"], 2)
        self.assertEqual(d["adapters"], ["aave_v3", "maple"])
        self.assertAlmostEqual(d["avg_apy_pct"], 4.5)

    def test_to_dict_adapters_is_list(self):
        e = StablecoinExposure("USDC", 1.0, 1.0, 1, ["a"], 1.0)
        self.assertIsInstance(e.to_dict()["adapters"], list)

    def test_to_dict_json_serializable(self):
        e = StablecoinExposure("USDC", 1.0, 1.0, 1, ["a"], 1.0)
        json.dumps(e.to_dict())

    def test_zero_capital_default_apy(self):
        e = StablecoinExposure("USDC", 0.0, 0.0, 0, [], 0.0)
        self.assertEqual(e.avg_apy_pct, 0.0)

    def test_rounding(self):
        e = StablecoinExposure("USDC", 1000.123456, 50.123456, 1, ["a"], 4.987654)
        d = e.to_dict()
        self.assertEqual(d["allocated_usd"], 1000.12)
        self.assertEqual(d["weight_pct"], 50.1235)
        self.assertEqual(d["avg_apy_pct"], 4.9877)


# ---------------------------------------------------------------------------
# StablecoinExposureReportData verdict boundaries
# ---------------------------------------------------------------------------


class TestConcentrationLabel(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_concentrated_above_half(self):
        self.assertEqual(self.r._concentration_label(0.6), "CONCENTRATED")

    def test_boundary_exactly_half_is_moderate(self):
        # strict > 0.5 for CONCENTRATED
        self.assertEqual(self.r._concentration_label(0.5), "MODERATE")

    def test_moderate_above_quarter(self):
        self.assertEqual(self.r._concentration_label(0.3), "MODERATE")

    def test_boundary_exactly_quarter_is_diversified(self):
        self.assertEqual(self.r._concentration_label(0.25), "DIVERSIFIED")

    def test_diversified_low(self):
        self.assertEqual(self.r._concentration_label(0.1), "DIVERSIFIED")

    def test_zero_is_diversified(self):
        self.assertEqual(self.r._concentration_label(0.0), "DIVERSIFIED")

    def test_one_is_concentrated(self):
        self.assertEqual(self.r._concentration_label(1.0), "CONCENTRATED")

    def test_just_above_half(self):
        self.assertEqual(self.r._concentration_label(0.5001), "CONCENTRATED")

    def test_just_above_quarter(self):
        self.assertEqual(self.r._concentration_label(0.2501), "MODERATE")


class TestContagionRisk(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_critical_above_80(self):
        self.assertEqual(self.r._contagion_risk(85.0), "CRITICAL")

    def test_boundary_exactly_80_is_high(self):
        self.assertEqual(self.r._contagion_risk(80.0), "HIGH")

    def test_just_above_80(self):
        self.assertEqual(self.r._contagion_risk(80.01), "CRITICAL")

    def test_high_above_60(self):
        self.assertEqual(self.r._contagion_risk(70.0), "HIGH")

    def test_boundary_exactly_60_is_moderate(self):
        self.assertEqual(self.r._contagion_risk(60.0), "MODERATE")

    def test_just_above_60(self):
        self.assertEqual(self.r._contagion_risk(60.01), "HIGH")

    def test_moderate_above_40(self):
        self.assertEqual(self.r._contagion_risk(50.0), "MODERATE")

    def test_boundary_exactly_40_is_low(self):
        self.assertEqual(self.r._contagion_risk(40.0), "LOW")

    def test_just_above_40(self):
        self.assertEqual(self.r._contagion_risk(40.01), "MODERATE")

    def test_low(self):
        self.assertEqual(self.r._contagion_risk(20.0), "LOW")

    def test_zero_is_low(self):
        self.assertEqual(self.r._contagion_risk(0.0), "LOW")

    def test_hundred_is_critical(self):
        self.assertEqual(self.r._contagion_risk(100.0), "CRITICAL")


# ---------------------------------------------------------------------------
# load_latest_snapshot
# ---------------------------------------------------------------------------


class TestLoadLatestSnapshot(unittest.TestCase):
    def _reporter(self, tmp):
        return StablecoinExposureReport(data_path=tmp)

    def test_missing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_corrupt_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                f.write("{not valid json")
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_non_dict_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump([1, 2, 3], f)
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_no_snapshots_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump({"foo": "bar"}, f)
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_snapshots_not_list(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump({"snapshots": "nope"}, f)
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_empty_snapshot_list(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([]), f)
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_snapshots_all_non_dict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump({"snapshots": [1, "x", None]}, f)
            r = self._reporter(tmp)
            self.assertEqual(r.load_latest_snapshot(), {})

    def test_valid_returns_last(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            s1 = _snapshot([_contrib("aave_v3", 100, 100)], "2026-06-11T00:00:00Z")
            s2 = _snapshot([_contrib("maple", 200, 100)], "2026-06-12T00:00:00Z")
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([s1, s2]), f)
            r = self._reporter(tmp)
            got = r.load_latest_snapshot()
            self.assertEqual(got["generated_at"], "2026-06-12T00:00:00Z")

    def test_valid_single(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            s1 = _snapshot([_contrib("aave_v3", 100, 100)])
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([s1]), f)
            r = self._reporter(tmp)
            got = r.load_latest_snapshot()
            self.assertEqual(len(got["contributions"]), 1)


# ---------------------------------------------------------------------------
# compute_exposures
# ---------------------------------------------------------------------------


class TestComputeExposuresEmpty(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_none_contributions(self):
        rep = self.r.compute_exposures({"generated_at": "2026-06-13T00:00:00Z"})
        self.assertEqual(rep.total_stablecoins, 0)
        self.assertEqual(rep.dominant_stablecoin, "")
        self.assertEqual(rep.hhi, 0.0)
        self.assertEqual(rep.contagion_risk, "LOW")
        self.assertEqual(rep.concentration_label, "DIVERSIFIED")

    def test_empty_list(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertEqual(rep.total_stablecoins, 0)

    def test_empty_dict(self):
        rep = self.r.compute_exposures({})
        self.assertEqual(rep.total_stablecoins, 0)

    def test_non_dict_snapshot(self):
        rep = self.r.compute_exposures("not a dict")
        self.assertEqual(rep.total_stablecoins, 0)

    def test_empty_has_recommendations(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertTrue(len(rep.recommendations) >= 1)

    def test_empty_summary_meaningful(self):
        rep = self.r.compute_exposures(_snapshot([]))
        self.assertIn("no data", rep.summary.lower())

    def test_empty_snapshot_at_preserved(self):
        rep = self.r.compute_exposures(
            {"generated_at": "2026-06-13T00:00:00Z", "contributions": []}
        )
        self.assertEqual(rep.snapshot_at, "2026-06-13T00:00:00Z")


class TestComputeExposuresSingle(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_single_100pct(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        self.assertEqual(rep.total_stablecoins, 1)
        self.assertEqual(rep.dominant_stablecoin, "USDC")
        self.assertAlmostEqual(rep.dominant_weight_pct, 100.0)

    def test_single_hhi_one(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        self.assertAlmostEqual(rep.hhi, 1.0, places=6)

    def test_single_critical(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        self.assertEqual(rep.contagion_risk, "CRITICAL")

    def test_single_concentrated(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        self.assertEqual(rep.concentration_label, "CONCENTRATED")

    def test_single_total_allocated(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1234.5, 100)]))
        self.assertAlmostEqual(rep.total_allocated_usd, 1234.5)

    def test_single_avg_apy(self):
        rep = self.r.compute_exposures(
            _snapshot([_contrib("aave_v3", 1000, 100, apy=4.2)])
        )
        self.assertAlmostEqual(rep.exposures[0].avg_apy_pct, 4.2)

    def test_single_critical_has_recommendation(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        self.assertTrue(any("depeg" in r.lower() or "risk" in r.lower()
                            for r in rep.recommendations))


class TestComputeExposuresGrouping(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_two_usdc_adapters_group(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("maple", 500, 50),
        ]))
        self.assertEqual(rep.total_stablecoins, 1)
        self.assertEqual(rep.dominant_stablecoin, "USDC")
        self.assertAlmostEqual(rep.dominant_weight_pct, 100.0)

    def test_group_adapter_count(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("maple", 500, 50),
        ]))
        self.assertEqual(rep.exposures[0].adapter_count, 2)

    def test_group_adapters_sorted(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("maple", 500, 50),
            _contrib("aave_v3", 500, 50),
        ]))
        self.assertEqual(rep.exposures[0].adapters, ["aave_v3", "maple"])

    def test_group_allocated_summed(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 300, 50),
            _contrib("maple", 700, 50),
        ]))
        self.assertAlmostEqual(rep.exposures[0].allocated_usd, 1000.0)

    def test_weighted_avg_apy(self):
        # 750@4% + 250@8% -> weighted = (750*4 + 250*8)/1000 = 5.0
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 750, 75, apy=4.0),
            _contrib("maple", 250, 25, apy=8.0),
        ]))
        self.assertAlmostEqual(rep.exposures[0].avg_apy_pct, 5.0, places=6)

    def test_two_distinct_stablecoins(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("frax", 500, 50),
        ]))
        self.assertEqual(rep.total_stablecoins, 2)

    def test_two_50_50_hhi(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("frax", 500, 50),
        ]))
        self.assertAlmostEqual(rep.hhi, 0.5, places=6)

    def test_two_50_50_concentration_moderate(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("frax", 500, 50),
        ]))
        # hhi == 0.5 -> not > 0.5 -> MODERATE
        self.assertEqual(rep.concentration_label, "MODERATE")

    def test_two_50_50_contagion_moderate(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 500, 50),
            _contrib("frax", 500, 50),
        ]))
        self.assertEqual(rep.contagion_risk, "MODERATE")

    def test_dominant_is_largest(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 700, 70),
            _contrib("frax", 300, 30),
        ]))
        self.assertEqual(rep.dominant_stablecoin, "USDC")
        self.assertAlmostEqual(rep.dominant_weight_pct, 70.0)

    def test_exposures_sorted_desc(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("frax", 300, 30),
            _contrib("aave_v3", 700, 70),
        ]))
        weights = [e.weight_pct for e in rep.exposures]
        self.assertEqual(weights, sorted(weights, reverse=True))


class TestComputeExposuresDiversified(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_many_small_diversified(self):
        # 5 distinct stablecoins at 20% each -> hhi = 5*0.04 = 0.2
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        self.assertAlmostEqual(rep.hhi, 0.2, places=6)
        self.assertEqual(rep.concentration_label, "DIVERSIFIED")

    def test_many_small_contagion_low(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        self.assertEqual(rep.contagion_risk, "LOW")

    def test_diversified_recommendation_ok(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        joined = " ".join(rep.recommendations).lower()
        self.assertIn("diversif", joined)

    def test_total_stablecoins_five(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        self.assertEqual(rep.total_stablecoins, 5)


class TestComputeExposuresUnknown(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_unknown_in_unknown_weight(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 700, 70),
            _contrib("brand_new_proto", 300, 30),
        ]))
        self.assertAlmostEqual(rep.unknown_weight_pct, 30.0)

    def test_unknown_symbol_present(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("brand_new_proto", 1000, 100),
        ]))
        symbols = [e.symbol for e in rep.exposures]
        self.assertIn("UNKNOWN", symbols)

    def test_unknown_recommendation(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 700, 70),
            _contrib("brand_new_proto", 300, 30),
        ]))
        joined = " ".join(rep.recommendations).lower()
        self.assertIn("adapter_stablecoin_map", joined)

    def test_no_unknown_zero(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 1000, 100),
        ]))
        self.assertEqual(rep.unknown_weight_pct, 0.0)


class TestComputeExposuresHHIExact(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_hhi_60_40(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        self.assertAlmostEqual(rep.hhi, 0.36 + 0.16, places=6)

    def test_hhi_70_30(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 700, 70),
            _contrib("frax", 300, 30),
        ]))
        self.assertAlmostEqual(rep.hhi, 0.49 + 0.09, places=6)

    def test_hhi_three_equal(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 100, 33.3333333),
            _contrib("frax", 100, 33.3333333),
            _contrib("sdai", 100, 33.3333334),
        ]))
        self.assertAlmostEqual(rep.hhi, 0.33333, places=3)

    def test_hhi_range(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 800, 80),
            _contrib("frax", 200, 20),
        ]))
        self.assertGreaterEqual(rep.hhi, 0.0)
        self.assertLessEqual(rep.hhi, 1.0)


class TestComputeExposuresMalformed(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_non_dict_contribution_skipped(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 1000, 100),
            "not a dict",
        ]))
        self.assertEqual(rep.total_stablecoins, 1)

    def test_bad_numeric_values(self):
        snap = _snapshot([{
            "adapter_id": "aave_v3",
            "weight_pct": "bad",
            "allocated_usd": "bad",
            "apy_pct": "bad",
        }])
        rep = self.r.compute_exposures(snap)
        # weights are 0, so still produces a group with 0 weight
        self.assertEqual(rep.total_stablecoins, 1)
        self.assertAlmostEqual(rep.exposures[0].weight_pct, 0.0)

    def test_missing_adapter_id(self):
        snap = _snapshot([{"weight_pct": 100, "allocated_usd": 1000, "apy_pct": 5}])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.dominant_stablecoin, "UNKNOWN")

    def test_zero_capital_group_apy_zero(self):
        snap = _snapshot([{
            "adapter_id": "aave_v3",
            "weight_pct": 100,
            "allocated_usd": 0,
            "apy_pct": 5,
        }])
        rep = self.r.compute_exposures(snap)
        self.assertEqual(rep.exposures[0].avg_apy_pct, 0.0)


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_z_suffix(self):
        dt = self.r._parse_timestamp("2026-06-13T00:00:00Z")
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_offset(self):
        dt = self.r._parse_timestamp("2026-06-13T00:00:00+00:00")
        self.assertIsNotNone(dt.tzinfo)

    def test_naive_becomes_utc(self):
        dt = self.r._parse_timestamp("2026-06-13T00:00:00")
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_invalid_returns_now(self):
        dt = self.r._parse_timestamp("garbage")
        self.assertIsInstance(dt, datetime)

    def test_none_returns_now(self):
        dt = self.r._parse_timestamp(None)
        self.assertIsInstance(dt, datetime)

    def test_empty_returns_now(self):
        dt = self.r._parse_timestamp("")
        self.assertIsInstance(dt, datetime)


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


class TestSaveReport(unittest.TestCase):
    def _setup_tracker(self, tmp):
        snap = _snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ])
        with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
            json.dump(_tracker([snap]), f)

    def test_creates_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            r.save_report()
            leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_valid_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            with open(path) as f:
                data = json.load(f)
            self.assertIn("latest", data)
            self.assertIn("history", data)

    def test_schema_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["source"], "stablecoin_exposure_report")

    def test_ring_buffer_caps_30(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            for _ in range(35):
                r.save_report()
            path = os.path.join(tmp, "stablecoin_exposure.json")
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data["history"]), 30)
            self.assertEqual(len(data["history"]), 30)

    def test_count_matches_history(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            for _ in range(3):
                r.save_report()
            path = os.path.join(tmp, "stablecoin_exposure.json")
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["count"], len(data["history"]))

    def test_second_save_appends(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            r.save_report()
            r.save_report()
            path = os.path.join(tmp, "stablecoin_exposure.json")
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data["history"]), 2)

    def test_returns_correct_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            self.assertTrue(path.endswith("stablecoin_exposure.json"))

    def test_latest_has_dominant(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["latest"]["dominant_stablecoin"], "USDC")

    def test_save_with_explicit_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            r = StablecoinExposureReport(data_path=tmp)
            rep = r.compute_exposures()
            path = r.save_report(rep)
            self.assertTrue(os.path.exists(path))

    def test_corrupt_existing_history_recovers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_tracker(tmp)
            with open(os.path.join(tmp, "stablecoin_exposure.json"), "w") as f:
                f.write("{corrupt")
            r = StablecoinExposureReport(data_path=tmp)
            path = r.save_report()
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data["history"]), 1)


# ---------------------------------------------------------------------------
# format_telegram_message
# ---------------------------------------------------------------------------


class TestTelegramMessage(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_length_cap(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), 1500)

    def test_contains_dominant(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("USDC", msg)

    def test_contains_hhi(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("HHI", msg)

    def test_contains_contagion(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Contagion", msg)

    def test_empty_message(self):
        rep = self.r.compute_exposures(_snapshot([]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("No allocation data", msg)

    def test_critical_shows_warn(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("CRITICAL", msg)

    def test_low_shows_ok(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("LOW", msg)

    def test_top_three_only(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 200, 20),
            _contrib("frax", 200, 20),
            _contrib("sdai", 200, 20),
            _contrib("susde", 200, 20),
            _contrib("scrvusd", 200, 20),
        ]))
        msg = self.r.format_telegram_message(rep)
        # Only top 3 listed as bullets
        self.assertEqual(msg.count("  - "), 3)

    def test_no_arg_loads_from_disk(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot([_contrib("aave_v3", 1000, 100)])
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([snap]), f)
            r = StablecoinExposureReport(data_path=tmp)
            msg = r.format_telegram_message()
            self.assertIn("USDC", msg)

    def test_unknown_shown(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("brand_new", 400, 40),
        ]))
        msg = self.r.format_telegram_message(rep)
        self.assertIn("Unknown", msg)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict(unittest.TestCase):
    def setUp(self):
        self.r = StablecoinExposureReport(data_path="data")

    def test_json_serializable(self):
        rep = self.r.compute_exposures(_snapshot([
            _contrib("aave_v3", 600, 60),
            _contrib("frax", 400, 40),
        ]))
        d = self.r.to_dict(rep)
        json.dumps(d)

    def test_required_keys(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        d = self.r.to_dict(rep)
        for key in ("generated_at", "snapshot_at", "total_allocated_usd",
                    "total_stablecoins", "exposures", "dominant_stablecoin",
                    "dominant_weight_pct", "hhi", "concentration_label",
                    "contagion_risk", "unknown_weight_pct", "recommendations",
                    "summary"):
            self.assertIn(key, d)

    def test_exposures_list_of_dict(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        d = self.r.to_dict(rep)
        self.assertIsInstance(d["exposures"], list)
        self.assertIsInstance(d["exposures"][0], dict)

    def test_exposure_dict_keys(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        d = self.r.to_dict(rep)
        exp = d["exposures"][0]
        for key in ("symbol", "allocated_usd", "weight_pct", "adapter_count",
                    "adapters", "avg_apy_pct"):
            self.assertIn(key, exp)

    def test_recommendations_is_list(self):
        rep = self.r.compute_exposures(_snapshot([_contrib("aave_v3", 1000, 100)]))
        d = self.r.to_dict(rep)
        self.assertIsInstance(d["recommendations"], list)

    def test_no_arg_computes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot([_contrib("aave_v3", 1000, 100)])
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([snap]), f)
            r = StablecoinExposureReport(data_path=tmp)
            d = r.to_dict()
            self.assertEqual(d["dominant_stablecoin"], "USDC")

    def test_data_class_to_dict_direct(self):
        rep = StablecoinExposureReportData(
            generated_at="2026-06-13T00:00:00+00:00",
            snapshot_at="2026-06-13T00:00:00Z",
            total_allocated_usd=1000.0,
            total_stablecoins=1,
        )
        d = rep.to_dict()
        self.assertEqual(d["total_stablecoins"], 1)


# ---------------------------------------------------------------------------
# Integration via disk
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    def test_full_cycle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot([
                _contrib("compound_v3", 300, 30, apy=4.8),
                _contrib("aave_v3", 300, 30, apy=4.2),
                _contrib("yearn_v3", 200, 20, apy=6.8),
                _contrib("euler_v2", 200, 20, apy=7.4),
            ])
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([snap]), f)
            r = StablecoinExposureReport(data_path=tmp)
            rep = r.compute_exposures()
            # All USDC
            self.assertEqual(rep.dominant_stablecoin, "USDC")
            self.assertAlmostEqual(rep.dominant_weight_pct, 100.0)
            self.assertEqual(rep.contagion_risk, "CRITICAL")
            path = r.save_report(rep)
            self.assertTrue(os.path.exists(path))
            msg = r.format_telegram_message(rep)
            self.assertLessEqual(len(msg), 1500)

    def test_load_compute_consistency(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot([_contrib("frax", 1000, 100)])
            with open(os.path.join(tmp, "yield_attribution_tracker.json"), "w") as f:
                json.dump(_tracker([snap]), f)
            r = StablecoinExposureReport(data_path=tmp)
            rep = r.compute_exposures()
            self.assertEqual(rep.dominant_stablecoin, "FRAX")


if __name__ == "__main__":
    unittest.main()
