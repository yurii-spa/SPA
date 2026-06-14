"""Tests for ProtocolConcentrationRisk (MP-603).

Groups:
    TestProtocolMap         (8)  — PROTOCOL_MAP coverage
    TestInferProtocol      (12)  — prefix matching, fallback, edge cases
    TestGroupByProtocol    (10)  — grouping correctness
    TestComputeExposure    (15)  — TVL, weight, risk_level, chains
    TestComputeHHI         (10)  — HHI edge cases
    TestGenerateReport     (15)  — sorting, warnings, concentration_score
    TestGetSafeAllocationCaps (8) — caps by risk_level
    TestSaveReport          (5)  — atomic write, ring-buffer
    TestFormatTelegramMessage (5) — ≤1500 chars, content
    TestToDict              (2)  — JSON-serializable

Total: 90 tests.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_concentration_risk import (
    PROTOCOL_MAP,
    _SORTED_PROTOCOL_KEYS,
    ConcentrationReport,
    ProtocolConcentrationRisk,
    ProtocolExposure,
    _extract_apy,
    _extract_chains,
    _extract_tvl,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(
    tier: str = "T1",
    tvl: float = 10_000_000.0,
    apy: float = 4.5,
    chains: list | None = None,
) -> dict:
    d: dict = {"tier": tier, "tvl_usd": tvl, "apy_pct": apy}
    if chains:
        d["chains"] = chains
    return d


def _make_pcr(tmp_dir: str) -> ProtocolConcentrationRisk:
    return ProtocolConcentrationRisk(data_path=tmp_dir)


# ---------------------------------------------------------------------------
# TestProtocolMap
# ---------------------------------------------------------------------------


class TestProtocolMap(unittest.TestCase):
    """PROTOCOL_MAP covers all essential protocols."""

    def test_aave_present(self):
        self.assertIn("aave", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["aave"], "aave")

    def test_morpho_present(self):
        self.assertIn("morpho", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["morpho"], "morpho")

    def test_compound_present(self):
        self.assertIn("compound", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["compound"], "compound")

    def test_spark_makerdao(self):
        self.assertIn("spark", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["spark"], "makerdao")

    def test_sky_makerdao(self):
        self.assertIn("sky", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["sky"], "makerdao")

    def test_sdai_makerdao(self):
        self.assertIn("sdai", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["sdai"], "makerdao")

    def test_susds_makerdao(self):
        self.assertIn("susds", PROTOCOL_MAP)
        self.assertEqual(PROTOCOL_MAP["susds"], "makerdao")

    def test_map_values_are_strings(self):
        for k, v in PROTOCOL_MAP.items():
            self.assertIsInstance(v, str, f"PROTOCOL_MAP['{k}'] is not str")


# ---------------------------------------------------------------------------
# TestInferProtocol
# ---------------------------------------------------------------------------


class TestInferProtocol(unittest.TestCase):
    """infer_protocol: prefix matching, fallback, edge cases."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def test_aave_v3(self):
        self.assertEqual(self.pcr.infer_protocol("aave_v3"), "aave")

    def test_aave_v3_arbitrum(self):
        self.assertEqual(self.pcr.infer_protocol("aave_v3_arbitrum"), "aave")

    def test_aave_v3_polygon(self):
        self.assertEqual(self.pcr.infer_protocol("aave_v3_polygon"), "aave")

    def test_morpho_blue_base(self):
        self.assertEqual(self.pcr.infer_protocol("morpho_blue_base"), "morpho")

    def test_compound_v3(self):
        self.assertEqual(self.pcr.infer_protocol("compound_v3"), "compound")

    def test_spark_susds(self):
        self.assertEqual(self.pcr.infer_protocol("spark_susds"), "makerdao")

    def test_sdai(self):
        self.assertEqual(self.pcr.infer_protocol("sdai"), "makerdao")

    def test_sfrax_adapter(self):
        self.assertEqual(self.pcr.infer_protocol("sfrax_adapter"), "frax")

    def test_pendle_yt(self):
        self.assertEqual(self.pcr.infer_protocol("pendle_yt"), "pendle")

    def test_fallback_first_word(self):
        # Unknown protocol → first segment before '_'
        result = self.pcr.infer_protocol("unknown_protocol_xyz")
        self.assertEqual(result, "unknown")

    def test_empty_string(self):
        self.assertEqual(self.pcr.infer_protocol(""), "unknown")

    def test_none_returns_unknown(self):
        # None is not a str → unknown
        self.assertEqual(self.pcr.infer_protocol(None), "unknown")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestGroupByProtocol
# ---------------------------------------------------------------------------


class TestGroupByProtocol(unittest.TestCase):
    """group_by_protocol: correct grouping."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def _data(self, ids):
        return {i: {"tier": "T1"} for i in ids}

    def test_single_protocol(self):
        data = self._data(["aave_v3", "aave_v3_arbitrum", "aave_v3_polygon"])
        groups = self.pcr.group_by_protocol(data)
        self.assertIn("aave", groups)
        self.assertEqual(len(groups["aave"]), 3)

    def test_two_protocols(self):
        data = self._data(["aave_v3", "compound_v3"])
        groups = self.pcr.group_by_protocol(data)
        self.assertIn("aave", groups)
        self.assertIn("compound", groups)

    def test_makerdao_consolidation(self):
        data = self._data(["sdai", "spark_susds", "sky_usds"])
        groups = self.pcr.group_by_protocol(data)
        self.assertIn("makerdao", groups)
        self.assertEqual(len(groups["makerdao"]), 3)

    def test_unknown_adapter_lands_in_unknown_or_custom(self):
        data = self._data(["zzz_adapter"])
        groups = self.pcr.group_by_protocol(data)
        # Should be grouped under some key, not raise
        all_ids = [i for ids in groups.values() for i in ids]
        self.assertIn("zzz_adapter", all_ids)

    def test_empty_returns_empty(self):
        groups = self.pcr.group_by_protocol({})
        self.assertEqual(groups, {})

    def test_each_adapter_appears_exactly_once(self):
        ids = ["aave_v3", "morpho_blue", "compound_v3", "yearn_v3", "euler_v2"]
        data = self._data(ids)
        groups = self.pcr.group_by_protocol(data)
        all_ids = [i for grp in groups.values() for i in grp]
        self.assertEqual(sorted(all_ids), sorted(ids))

    def test_hyphen_normalised(self):
        # Adapter IDs with hyphens are normalised before matching
        pcr = ProtocolConcentrationRisk()
        data = {"aave-v3": {"tier": "T1"}}
        groups = pcr.group_by_protocol(data)
        all_ids = [i for ids in groups.values() for i in ids]
        self.assertIn("aave-v3", all_ids)

    def test_groups_values_are_lists(self):
        data = self._data(["aave_v3", "morpho_blue"])
        groups = self.pcr.group_by_protocol(data)
        for v in groups.values():
            self.assertIsInstance(v, list)

    def test_pendle_and_euler_separate(self):
        data = self._data(["pendle_yt", "euler_v2"])
        groups = self.pcr.group_by_protocol(data)
        self.assertIn("pendle", groups)
        self.assertIn("euler", groups)

    def test_morpho_blue_base_grouped_with_morpho(self):
        data = self._data(["morpho_blue", "morpho_blue_base", "morpho_steakhouse"])
        groups = self.pcr.group_by_protocol(data)
        self.assertIn("morpho", groups)
        self.assertEqual(len(groups["morpho"]), 3)


# ---------------------------------------------------------------------------
# TestComputeExposure
# ---------------------------------------------------------------------------


class TestComputeExposure(unittest.TestCase):
    """compute_exposure: TVL aggregation, weight, risk_level, chains."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def test_tvl_aggregation(self):
        data = {
            "aave_v3": _make_adapter(tvl=30_000_000),
            "aave_v3_arbitrum": _make_adapter(tvl=20_000_000),
        }
        exp = self.pcr.compute_exposure("aave", ["aave_v3", "aave_v3_arbitrum"], data, 100_000_000)
        self.assertAlmostEqual(exp.total_tvl_usd, 50_000_000.0)

    def test_portfolio_weight_pct(self):
        data = {
            "aave_v3": _make_adapter(tvl=40_000_000),
        }
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertAlmostEqual(exp.portfolio_weight_pct, 40.0, places=2)

    def test_risk_level_low(self):
        data = {"aave_v3": _make_adapter(tvl=10_000_000)}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertEqual(exp.risk_level, "LOW")

    def test_risk_level_medium(self):
        data = {"aave_v3": _make_adapter(tvl=30_000_000)}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertEqual(exp.risk_level, "MEDIUM")

    def test_risk_level_high(self):
        data = {"aave_v3": _make_adapter(tvl=45_000_000)}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertEqual(exp.risk_level, "HIGH")

    def test_risk_level_critical(self):
        data = {"aave_v3": _make_adapter(tvl=65_000_000)}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertEqual(exp.risk_level, "CRITICAL")

    def test_chains_unique(self):
        data = {
            "aave_v3": _make_adapter(chains=["ethereum"]),
            "aave_v3_arbitrum": _make_adapter(chains=["arbitrum"]),
            "aave_v3_polygon": _make_adapter(chains=["polygon"]),
        }
        exp = self.pcr.compute_exposure(
            "aave",
            ["aave_v3", "aave_v3_arbitrum", "aave_v3_polygon"],
            data,
            100_000_000,
        )
        self.assertEqual(sorted(exp.chains), ["arbitrum", "ethereum", "polygon"])

    def test_chains_deduplicated(self):
        data = {
            "aave_v3": _make_adapter(chains=["ethereum"]),
            "aave_v3_b": _make_adapter(chains=["ethereum"]),  # same chain
        }
        exp = self.pcr.compute_exposure("aave", ["aave_v3", "aave_v3_b"], data, 100_000_000)
        self.assertEqual(exp.chains.count("ethereum"), 1)

    def test_avg_apy_computed(self):
        data = {
            "a1": _make_adapter(apy=4.0),
            "a2": _make_adapter(apy=6.0),
        }
        exp = self.pcr.compute_exposure("aave", ["a1", "a2"], data, 100_000_000)
        self.assertAlmostEqual(exp.avg_apy_pct, 5.0, places=3)

    def test_zero_total_tvl_weight_zero(self):
        data = {"aave_v3": _make_adapter(tvl=10_000_000)}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 0.0)
        self.assertEqual(exp.portfolio_weight_pct, 0.0)

    def test_adapter_count(self):
        data = {k: _make_adapter() for k in ["a", "b", "c"]}
        exp = self.pcr.compute_exposure("aave", ["a", "b", "c"], data, 100_000_000)
        self.assertEqual(exp.adapter_count, 3)

    def test_risk_note_cross_chain(self):
        data = {
            "a1": _make_adapter(chains=["ethereum"]),
            "a2": _make_adapter(chains=["arbitrum"]),
            "a3": _make_adapter(chains=["polygon"]),
        }
        exp = self.pcr.compute_exposure(
            "aave", ["a1", "a2", "a3"], data, 100_000_000
        )
        # cross-chain note when ≥ CROSS_CHAIN_MIN chains
        self.assertIn("chain", exp.risk_note.lower())

    def test_risk_note_single_adapter(self):
        data = {"aave_v3": _make_adapter()}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertIn("1 adapter", exp.risk_note)

    def test_adapter_ids_sorted(self):
        data = {k: _make_adapter() for k in ["z_adapter", "a_adapter", "m_adapter"]}
        exp = self.pcr.compute_exposure("proto", ["z_adapter", "a_adapter", "m_adapter"], data, 100_000_000)
        self.assertEqual(exp.adapter_ids, sorted(exp.adapter_ids))

    def test_protocol_field(self):
        data = {"aave_v3": _make_adapter()}
        exp = self.pcr.compute_exposure("aave", ["aave_v3"], data, 100_000_000)
        self.assertEqual(exp.protocol, "aave")


# ---------------------------------------------------------------------------
# TestComputeHHI
# ---------------------------------------------------------------------------


class TestComputeHHI(unittest.TestCase):
    """compute_hhi: edge cases and mathematical correctness."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def _exp(self, protocol: str, weight: float) -> ProtocolExposure:
        return ProtocolExposure(
            protocol=protocol,
            adapter_ids=[],
            adapter_count=0,
            total_tvl_usd=0.0,
            avg_apy_pct=0.0,
            chains=[],
            portfolio_weight_pct=weight,
            risk_level="LOW",
            risk_note="",
        )

    def test_single_protocol_100pct(self):
        exposures = [self._exp("aave", 100.0)]
        self.assertAlmostEqual(self.pcr.compute_hhi(exposures), 1.0, places=5)

    def test_two_equal_protocols(self):
        exposures = [self._exp("aave", 50.0), self._exp("morpho", 50.0)]
        self.assertAlmostEqual(self.pcr.compute_hhi(exposures), 0.5, places=5)

    def test_four_equal_protocols(self):
        exposures = [self._exp(f"p{i}", 25.0) for i in range(4)]
        self.assertAlmostEqual(self.pcr.compute_hhi(exposures), 0.25, places=5)

    def test_empty_returns_zero(self):
        self.assertEqual(self.pcr.compute_hhi([]), 0.0)

    def test_hhi_clamped_to_one(self):
        # Edge case: weight slightly > 100 due to floating point
        exposures = [self._exp("aave", 100.001)]
        hhi = self.pcr.compute_hhi(exposures)
        self.assertLessEqual(hhi, 1.0)

    def test_hhi_non_negative(self):
        exposures = [self._exp("aave", 0.0)]
        self.assertGreaterEqual(self.pcr.compute_hhi(exposures), 0.0)

    def test_hhi_ten_equal_protocols(self):
        exposures = [self._exp(f"p{i}", 10.0) for i in range(10)]
        self.assertAlmostEqual(self.pcr.compute_hhi(exposures), 0.1, places=5)

    def test_hhi_asymmetric(self):
        # 80/20 split: (0.8)^2 + (0.2)^2 = 0.64 + 0.04 = 0.68
        exposures = [self._exp("aave", 80.0), self._exp("morpho", 20.0)]
        self.assertAlmostEqual(self.pcr.compute_hhi(exposures), 0.68, places=5)

    def test_hhi_returns_float(self):
        exposures = [self._exp("aave", 50.0), self._exp("morpho", 50.0)]
        self.assertIsInstance(self.pcr.compute_hhi(exposures), float)

    def test_hhi_sum_less_100_still_works(self):
        # If weights don't sum to 100 (cash held out), HHI is still computed
        exposures = [self._exp("aave", 40.0), self._exp("morpho", 30.0)]
        hhi = self.pcr.compute_hhi(exposures)
        expected = (0.4 ** 2) + (0.3 ** 2)
        self.assertAlmostEqual(hhi, expected, places=5)


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------


class TestGenerateReport(unittest.TestCase):
    """generate_report: sorting, warnings, concentration_score."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def _adapter_data(self, specs: dict) -> dict:
        """specs: {adapter_id: (tvl, apy, chains)}"""
        return {
            aid: _make_adapter(tvl=tvl, apy=apy, chains=chains)
            for aid, (tvl, apy, chains) in specs.items()
        }

    def test_empty_adapter_data_returns_empty_report(self):
        report = self.pcr.generate_report({})
        self.assertEqual(report.total_protocols, 0)
        self.assertEqual(report.total_adapters, 0)

    def test_exposures_sorted_desc_by_weight(self):
        data = self._adapter_data({
            "aave_v3": (60_000_000, 4.0, ["ethereum"]),
            "morpho_blue": (30_000_000, 5.0, ["ethereum"]),
            "compound_v3": (10_000_000, 4.8, ["ethereum"]),
        })
        report = self.pcr.generate_report(data)
        weights = [e.portfolio_weight_pct for e in report.exposures]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_top_protocol_is_largest(self):
        data = self._adapter_data({
            "aave_v3": (60_000_000, 4.0, ["ethereum"]),
            "compound_v3": (40_000_000, 4.8, ["ethereum"]),
        })
        report = self.pcr.generate_report(data)
        self.assertEqual(report.top_protocol, "aave")
        self.assertAlmostEqual(report.top_protocol_weight_pct, 60.0, places=1)

    def test_concentration_score_single_protocol(self):
        data = {"aave_v3": _make_adapter(tvl=100_000_000)}
        report = self.pcr.generate_report(data)
        self.assertAlmostEqual(report.concentration_score, 1.0, places=4)

    def test_concentration_score_two_equal(self):
        data = self._adapter_data({
            "aave_v3": (50_000_000, 4.0, []),
            "compound_v3": (50_000_000, 4.8, []),
        })
        report = self.pcr.generate_report(data)
        self.assertAlmostEqual(report.concentration_score, 0.5, places=4)

    def test_warnings_generated_for_high(self):
        # 45% → HIGH threshold
        data = {"aave_v3": _make_adapter(tvl=45_000_000)}
        report = self.pcr.generate_report(data)
        self.assertTrue(len(report.warnings) > 0)
        combined = " ".join(report.warnings).lower()
        self.assertIn("aave", combined)

    def test_no_warnings_for_low_risk(self):
        # Each protocol < 25% → LOW across the board → no warnings
        data = {
            "aave_v3": _make_adapter(tvl=20_000_000),
            "compound_v3": _make_adapter(tvl=20_000_000),
            "morpho_blue": _make_adapter(tvl=20_000_000),
            "pendle_yt": _make_adapter(tvl=20_000_000),
            "euler_v2": _make_adapter(tvl=20_000_000),
        }
        report = self.pcr.generate_report(data)
        self.assertEqual(report.warnings, [])

    def test_total_adapters_count(self):
        data = {f"adapter_{i}": _make_adapter() for i in range(5)}
        report = self.pcr.generate_report(data)
        self.assertEqual(report.total_adapters, 5)

    def test_total_tvl_sum(self):
        data = {
            "aave_v3": _make_adapter(tvl=30_000_000),
            "compound_v3": _make_adapter(tvl=20_000_000),
        }
        report = self.pcr.generate_report(data)
        self.assertAlmostEqual(report.total_tvl_usd, 50_000_000.0, places=1)

    def test_overall_risk_not_empty(self):
        data = {"aave_v3": _make_adapter(tvl=10_000_000)}
        report = self.pcr.generate_report(data)
        self.assertIn(report.overall_risk, ("LOW", "MEDIUM", "HIGH"))

    def test_generated_at_is_iso8601(self):
        data = {"aave_v3": _make_adapter()}
        report = self.pcr.generate_report(data)
        self.assertIn("T", report.generated_at)
        self.assertTrue(report.generated_at.endswith("+00:00") or "Z" in report.generated_at)

    def test_cross_chain_warning_for_3_chains(self):
        data = {
            "aave_v3": _make_adapter(tvl=15_000_000, chains=["ethereum"]),
            "aave_v3_arbitrum": _make_adapter(tvl=10_000_000, chains=["arbitrum"]),
            "aave_v3_polygon": _make_adapter(tvl=10_000_000, chains=["polygon"]),
        }
        report = self.pcr.generate_report(data)
        combined = " ".join(report.warnings).lower()
        # Aave exposure is ~35% → MEDIUM, and spans 3 chains → cross-chain warning
        self.assertIn("chain", combined)

    def test_makerdao_consolidation_in_report(self):
        data = {
            "sdai": _make_adapter(tvl=10_000_000),
            "spark_susds": _make_adapter(tvl=10_000_000),
        }
        report = self.pcr.generate_report(data)
        protocols = [e.protocol for e in report.exposures]
        self.assertIn("makerdao", protocols)

    def test_exposures_list_type(self):
        data = {"aave_v3": _make_adapter()}
        report = self.pcr.generate_report(data)
        self.assertIsInstance(report.exposures, list)

    def test_warnings_list_type(self):
        data = {"aave_v3": _make_adapter(tvl=50_000_000)}
        report = self.pcr.generate_report(data)
        self.assertIsInstance(report.warnings, list)


# ---------------------------------------------------------------------------
# TestGetSafeAllocationCaps
# ---------------------------------------------------------------------------


class TestGetSafeAllocationCaps(unittest.TestCase):
    """get_safe_allocation_caps: caps match risk levels."""

    def setUp(self):
        self.pcr = ProtocolConcentrationRisk()

    def test_low_risk_cap_40(self):
        # aave = 10M / 100M = 10% → LOW → cap 40%
        data = {
            "aave_v3": _make_adapter(tvl=10_000_000),
            "compound_v3": _make_adapter(tvl=50_000_000),
            "morpho_blue": _make_adapter(tvl=40_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        self.assertIn("aave", caps)
        self.assertEqual(caps["aave"], 40.0)

    def test_medium_risk_cap_30(self):
        # aave = 30M / 100M = 30% → MEDIUM → cap 30%
        data = {
            "aave_v3": _make_adapter(tvl=30_000_000),
            "compound_v3": _make_adapter(tvl=40_000_000),
            "morpho_blue": _make_adapter(tvl=30_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        self.assertIn("aave", caps)
        self.assertEqual(caps["aave"], 30.0)

    def test_high_risk_cap_20(self):
        # aave = 45M / 100M = 45% → HIGH → cap 20%
        data = {
            "aave_v3": _make_adapter(tvl=45_000_000),
            "compound_v3": _make_adapter(tvl=30_000_000),
            "morpho_blue": _make_adapter(tvl=25_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        self.assertIn("aave", caps)
        self.assertEqual(caps["aave"], 20.0)

    def test_critical_risk_cap_10(self):
        # aave = 65M / 100M = 65% → CRITICAL → cap 10%
        data = {
            "aave_v3": _make_adapter(tvl=65_000_000),
            "compound_v3": _make_adapter(tvl=20_000_000),
            "morpho_blue": _make_adapter(tvl=15_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        self.assertIn("aave", caps)
        self.assertEqual(caps["aave"], 10.0)

    def test_all_protocols_covered(self):
        data = {
            "aave_v3": _make_adapter(tvl=10_000_000),
            "compound_v3": _make_adapter(tvl=10_000_000),
            "morpho_blue": _make_adapter(tvl=10_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        self.assertIn("aave", caps)
        self.assertIn("compound", caps)
        self.assertIn("morpho", caps)

    def test_caps_are_floats(self):
        data = {"aave_v3": _make_adapter(tvl=10_000_000)}
        caps = self.pcr.get_safe_allocation_caps(data)
        for v in caps.values():
            self.assertIsInstance(v, float)

    def test_empty_data_returns_empty(self):
        caps = self.pcr.get_safe_allocation_caps({})
        self.assertEqual(caps, {})

    def test_multiple_adapters_same_protocol_one_cap(self):
        data = {
            "aave_v3": _make_adapter(tvl=10_000_000),
            "aave_v3_arbitrum": _make_adapter(tvl=5_000_000),
        }
        caps = self.pcr.get_safe_allocation_caps(data)
        # aave total = 15M / 15M = 100% → CRITICAL → 10%
        # But wait, total_tvl is also 15M, so weight = 100% → CRITICAL
        self.assertIn("aave", caps)
        self.assertEqual(caps["aave"], 10.0)


# ---------------------------------------------------------------------------
# TestSaveReport
# ---------------------------------------------------------------------------


class TestSaveReport(unittest.TestCase):
    """save_report: atomic write, ring-buffer, file creation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_adapter_status(self):
        """Write a minimal adapter_status.json to tmp dir."""
        data = {
            "generated_at": "2026-06-13T00:00:00+00:00",
            "adapters": [
                {
                    "protocol_key": "aave-v3",
                    "tier": "T1",
                    "tvl_usd": 10_000_000,
                    "apy_pct": 4.5,
                    "chains": ["ethereum"],
                }
            ],
        }
        path = Path(self.tmp) / "adapter_status.json"
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_file_created(self):
        self._make_adapter_status()
        pcr = _make_pcr(self.tmp)
        path = pcr.save_report()
        self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        self._make_adapter_status()
        pcr = _make_pcr(self.tmp)
        pcr.save_report()
        tmps = list(Path(self.tmp).glob(".concentration_risk.json.*.tmp"))
        self.assertEqual(len(tmps), 0)

    def test_ring_buffer_max_30(self):
        self._make_adapter_status()
        pcr = _make_pcr(self.tmp)
        for _ in range(35):
            pcr.save_report()
        raw = json.loads((Path(self.tmp) / "concentration_risk.json").read_text())
        self.assertLessEqual(len(raw["snapshots"]), 30)

    def test_custom_output_path(self):
        self._make_adapter_status()
        pcr = _make_pcr(self.tmp)
        custom = os.path.join(self.tmp, "custom_out.json")
        path = pcr.save_report(output_path=custom)
        self.assertEqual(path, custom)
        self.assertTrue(os.path.exists(custom))

    def test_output_is_valid_json(self):
        self._make_adapter_status()
        pcr = _make_pcr(self.tmp)
        path = pcr.save_report()
        content = Path(path).read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertIn("latest", parsed)
        self.assertIn("snapshots", parsed)


# ---------------------------------------------------------------------------
# TestFormatTelegramMessage
# ---------------------------------------------------------------------------


class TestFormatTelegramMessage(unittest.TestCase):
    """format_telegram_message: length, content."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Write adapter_status.json
        data = {
            "generated_at": "2026-06-13T00:00:00+00:00",
            "adapters": [
                {
                    "protocol_key": "aave-v3",
                    "tier": "T1",
                    "tvl_usd": 50_000_000,
                    "apy_pct": 4.5,
                    "chains": ["ethereum", "arbitrum", "polygon"],
                },
                {
                    "protocol_key": "compound-v3",
                    "tier": "T1",
                    "tvl_usd": 30_000_000,
                    "apy_pct": 4.8,
                    "chains": ["ethereum"],
                },
                {
                    "protocol_key": "morpho-blue",
                    "tier": "T2",
                    "tvl_usd": 20_000_000,
                    "apy_pct": 5.5,
                    "chains": ["ethereum"],
                },
            ],
        }
        (Path(self.tmp) / "adapter_status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        self.pcr = _make_pcr(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_length_max_1500(self):
        msg = self.pcr.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_top_protocol(self):
        msg = self.pcr.format_telegram_message()
        self.assertIn("aave", msg.lower())

    def test_contains_risk_level(self):
        msg = self.pcr.format_telegram_message()
        self.assertTrue(
            any(r in msg for r in ("LOW", "MEDIUM", "HIGH", "CRITICAL")),
        )

    def test_returns_string(self):
        msg = self.pcr.format_telegram_message()
        self.assertIsInstance(msg, str)

    def test_not_empty(self):
        msg = self.pcr.format_telegram_message()
        self.assertGreater(len(msg), 0)


# ---------------------------------------------------------------------------
# TestToDict
# ---------------------------------------------------------------------------


class TestToDict(unittest.TestCase):
    """to_dict: JSON-serializable, required keys present."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        data = {
            "generated_at": "2026-06-13T00:00:00+00:00",
            "adapters": [
                {
                    "protocol_key": "aave-v3",
                    "tier": "T1",
                    "tvl_usd": 10_000_000,
                    "apy_pct": 4.5,
                    "chains": ["ethereum"],
                }
            ],
        }
        (Path(self.tmp) / "adapter_status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        self.pcr = _make_pcr(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_serializable(self):
        d = self.pcr.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)

    def test_required_keys_present(self):
        d = self.pcr.to_dict()
        for key in (
            "generated_at",
            "total_protocols",
            "total_adapters",
            "total_tvl_usd",
            "concentration_score",
            "top_protocol",
            "top_protocol_weight_pct",
            "overall_risk",
            "warnings",
            "exposures",
        ):
            self.assertIn(key, d, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
