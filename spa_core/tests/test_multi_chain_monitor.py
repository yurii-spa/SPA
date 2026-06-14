"""Tests for spa_core/analytics/multi_chain_monitor.py — MP-590.

Usage:
    python3 -m unittest spa_core.tests.test_multi_chain_monitor -v

All tests use mock/temp data — do NOT depend on real adapter_status.json.
95 test cases across 9 test classes.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.analytics.multi_chain_monitor import (
    SUPPORTED_CHAINS,
    L2_CHAINS,
    ChainSnapshot,
    MultiChainMonitor,
    MultiChainReport,
    _normalize_chain,
    _extract_apy,
    _extract_risk_score,
    _extract_tvl,
    _extract_gas_savings,
    _extract_peg_healthy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_status(entries: dict | None = None, adapters: list | None = None) -> dict:
    """Build a minimal adapter_status.json dict for tests."""
    result: dict = {}
    if entries:
        result.update(entries)
    if adapters is not None:
        result["adapters"] = adapters
    return result


def _write_status(tmp_dir: str, status: dict) -> str:
    """Write adapter_status.json to tmp_dir and return its path."""
    path = os.path.join(tmp_dir, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(status, fh)
    return path


def _make_monitor(tmp_dir: str, status: dict) -> MultiChainMonitor:
    """Convenience: write status to tmp_dir and return a Monitor for it."""
    path = _write_status(tmp_dir, status)
    return MultiChainMonitor(data_path=path)


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

MOCK_ENTRIES = {
    "aave_opt": {
        "chain": "optimism", "tier": "T1",
        "apy_pct": 6.0, "tvl_usd": 600_000_000, "risk_score": 0.25,
        "gas_savings_pct": 95.0, "usdc_price": 1.0,
    },
    "morpho_base": {
        "chain": "base", "tier": "T2",
        "apy_pct": 7.5, "tvl_usd": 180_000_000, "risk_score": 0.38,
        "gas_advantage_usd": 0.095, "gas_base_usd": 0.005,
    },
    "aave_base": {
        "chain": "base", "tier": "T2",
        "apy_pct": 4.5, "tvl_usd": 400_000_000, "risk_score": 0.35,
    },
    "compound_arb": {
        "chain": "arbitrum", "tier": "T1",
        "apy_pct": 5.8, "tvl_usd": 1_000_000_000, "risk_score": 0.22,
        "gas_savings_pct": 90.0,
    },
    "aave_eth": {
        "chain": "ethereum", "tier": "T1",
        "apy_pct": 4.2, "tvl_usd": 5_000_000_000, "risk_score": 0.20,
    },
    "compound_eth": {
        "chain": "ethereum", "tier": "T1",
        "apy_pct": 4.8, "tvl_usd": 2_800_000_000, "risk_score": 0.28,
    },
}


# ===========================================================================
# TestChainSnapshot
# ===========================================================================

class TestChainSnapshot(unittest.TestCase):
    """12 tests — fields, types, default values."""

    def _make(self, **kwargs) -> ChainSnapshot:
        defaults = dict(
            chain="ethereum", adapter_count=2, avg_apy_pct=5.0,
            best_apy_pct=6.0, best_adapter="aave", avg_risk_score=0.25,
            total_tvl_usd=1_000_000.0, avg_gas_savings_pct=0.0,
            healthy_count=2, timestamp="2026-01-01T00:00:00+00:00",
        )
        defaults.update(kwargs)
        return ChainSnapshot(**defaults)

    def test_chain_field_stored(self):
        s = self._make(chain="base")
        self.assertEqual(s.chain, "base")

    def test_adapter_count_int(self):
        s = self._make(adapter_count=5)
        self.assertIsInstance(s.adapter_count, int)
        self.assertEqual(s.adapter_count, 5)

    def test_avg_apy_pct_float(self):
        s = self._make(avg_apy_pct=4.75)
        self.assertIsInstance(s.avg_apy_pct, float)
        self.assertAlmostEqual(s.avg_apy_pct, 4.75)

    def test_best_apy_pct_float(self):
        s = self._make(best_apy_pct=8.0)
        self.assertAlmostEqual(s.best_apy_pct, 8.0)

    def test_best_adapter_str(self):
        s = self._make(best_adapter="morpho_base")
        self.assertEqual(s.best_adapter, "morpho_base")

    def test_avg_risk_score_float(self):
        s = self._make(avg_risk_score=0.35)
        self.assertIsInstance(s.avg_risk_score, float)

    def test_total_tvl_usd_float(self):
        s = self._make(total_tvl_usd=999_999.99)
        self.assertAlmostEqual(s.total_tvl_usd, 999_999.99)

    def test_avg_gas_savings_pct_zero_for_l1(self):
        s = self._make(chain="ethereum", avg_gas_savings_pct=0.0)
        self.assertEqual(s.avg_gas_savings_pct, 0.0)

    def test_avg_gas_savings_pct_l2(self):
        s = self._make(chain="optimism", avg_gas_savings_pct=95.0)
        self.assertEqual(s.avg_gas_savings_pct, 95.0)

    def test_healthy_count_nonnegative(self):
        s = self._make(healthy_count=0)
        self.assertGreaterEqual(s.healthy_count, 0)

    def test_timestamp_string(self):
        s = self._make(timestamp="2026-06-13T10:00:00+00:00")
        self.assertIsInstance(s.timestamp, str)
        self.assertIn("2026", s.timestamp)

    def test_snapshot_inequality(self):
        s1 = self._make(chain="base", avg_apy_pct=5.0)
        s2 = self._make(chain="optimism", avg_apy_pct=6.0)
        self.assertNotEqual(s1.chain, s2.chain)
        self.assertNotEqual(s1.avg_apy_pct, s2.avg_apy_pct)


# ===========================================================================
# TestMultiChainReport
# ===========================================================================

class TestMultiChainReport(unittest.TestCase):
    """10 tests — report fields, best_chain, l2_premium_pct."""

    def _make_snap(self, chain: str, count: int, avg_apy: float) -> ChainSnapshot:
        return ChainSnapshot(
            chain=chain, adapter_count=count, avg_apy_pct=avg_apy,
            best_apy_pct=avg_apy + 1.0, best_adapter="adapter_x",
            avg_risk_score=0.30, total_tvl_usd=1_000_000.0,
            avg_gas_savings_pct=0.0 if chain == "ethereum" else 90.0,
            healthy_count=count,
            timestamp="2026-01-01T00:00:00+00:00",
        )

    def _make_report(self, **overrides) -> MultiChainReport:
        snaps = {c: self._make_snap(c, 2, 5.0) for c in SUPPORTED_CHAINS}
        defaults = dict(
            generated_at="2026-01-01T00:00:00+00:00",
            chains=snaps, best_chain="ethereum",
            best_adapter_overall="aave", best_apy_overall=6.0,
            total_adapters=10, total_tvl_usd=1_000_000.0,
            l2_premium_pct=0.5,
        )
        defaults.update(overrides)
        return MultiChainReport(**defaults)

    def test_generated_at_string(self):
        r = self._make_report()
        self.assertIsInstance(r.generated_at, str)

    def test_chains_dict_keys(self):
        r = self._make_report()
        for chain in SUPPORTED_CHAINS:
            self.assertIn(chain, r.chains)

    def test_best_chain_is_string(self):
        r = self._make_report(best_chain="base")
        self.assertEqual(r.best_chain, "base")

    def test_best_adapter_overall_string(self):
        r = self._make_report(best_adapter_overall="morpho_base")
        self.assertEqual(r.best_adapter_overall, "morpho_base")

    def test_best_apy_overall_float(self):
        r = self._make_report(best_apy_overall=7.5)
        self.assertAlmostEqual(r.best_apy_overall, 7.5)

    def test_total_adapters_nonneg(self):
        r = self._make_report(total_adapters=12)
        self.assertGreaterEqual(r.total_adapters, 0)

    def test_total_tvl_nonneg(self):
        r = self._make_report(total_tvl_usd=5_000_000.0)
        self.assertGreaterEqual(r.total_tvl_usd, 0.0)

    def test_l2_premium_can_be_negative(self):
        r = self._make_report(l2_premium_pct=-1.5)
        self.assertEqual(r.l2_premium_pct, -1.5)

    def test_l2_premium_positive(self):
        r = self._make_report(l2_premium_pct=2.3)
        self.assertGreater(r.l2_premium_pct, 0)

    def test_chains_snapshot_types(self):
        r = self._make_report()
        for snap in r.chains.values():
            self.assertIsInstance(snap, ChainSnapshot)


# ===========================================================================
# TestLoadAdapterStatus
# ===========================================================================

class TestLoadAdapterStatus(unittest.TestCase):
    """10 tests — file loading edge cases."""

    def test_loads_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_status(tmp, {"key": "value"})
            m = MultiChainMonitor(data_path=path)
            data = m.load_adapter_status()
            self.assertEqual(data, {"key": "value"})

    def test_missing_file_returns_empty(self):
        m = MultiChainMonitor(data_path="/nonexistent/path/adapter_status.json")
        data = m.load_adapter_status()
        self.assertEqual(data, {})

    def test_empty_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "adapter_status.json")
            open(path, "w").close()  # empty file
            m = MultiChainMonitor(data_path=path)
            data = m.load_adapter_status()
            self.assertEqual(data, {})

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "adapter_status.json")
            with open(path, "w") as fh:
                fh.write("{invalid json")
            m = MultiChainMonitor(data_path=path)
            data = m.load_adapter_status()
            self.assertEqual(data, {})

    def test_json_array_returns_empty(self):
        """Top-level list (not dict) → returns {}."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_status(tmp, [1, 2, 3])  # type: ignore[arg-type]
            with open(path, "w") as fh:
                json.dump([1, 2, 3], fh)
            m = MultiChainMonitor(data_path=path)
            data = m.load_adapter_status()
            self.assertEqual(data, {})

    def test_valid_adapters_key_loaded(self):
        status = _make_status(adapters=[{"protocol_key": "aave-v3", "chains": ["ethereum"]}])
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            data = m.load_adapter_status()
            self.assertIn("adapters", data)
            self.assertEqual(len(data["adapters"]), 1)

    def test_protocol_entries_loaded(self):
        status = _make_status(entries={
            "my_adapter": {"chain": "base", "apy_pct": 5.0, "tier": "T2"}
        })
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            data = m.load_adapter_status()
            self.assertIn("my_adapter", data)

    def test_never_raises_on_permission_error(self):
        """Even if path is a directory, returns {}."""
        with tempfile.TemporaryDirectory() as tmp:
            m = MultiChainMonitor(data_path=tmp)  # directory, not a file
            data = m.load_adapter_status()
            self.assertEqual(data, {})

    def test_returns_full_dict(self):
        status = MOCK_ENTRIES.copy()
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            data = m.load_adapter_status()
            self.assertIsInstance(data, dict)
            self.assertGreater(len(data), 0)

    def test_unicode_content_loaded(self):
        status = {"протокол": {"chain": "ethereum", "apy_pct": 3.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            data = m.load_adapter_status()
            self.assertIn("протокол", data)


# ===========================================================================
# TestGetChainSnapshot
# ===========================================================================

class TestGetChainSnapshot(unittest.TestCase):
    """15 tests — snapshot computation for various chains / data combinations."""

    def test_empty_chain_returns_zero_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            snap = m.get_chain_snapshot("polygon")
            self.assertEqual(snap.adapter_count, 0)

    def test_empty_chain_zero_apy(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            snap = m.get_chain_snapshot("polygon")
            self.assertEqual(snap.avg_apy_pct, 0.0)
            self.assertEqual(snap.best_apy_pct, 0.0)

    def test_empty_chain_empty_best_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            snap = m.get_chain_snapshot("polygon")
            self.assertEqual(snap.best_adapter, "")

    def test_single_adapter_ethereum(self):
        status = {"eth_adapter": {"chain": "ethereum", "apy_pct": 4.2, "tier": "T1", "tvl_usd": 1_000_000}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("ethereum")
            self.assertEqual(snap.adapter_count, 1)
            self.assertAlmostEqual(snap.avg_apy_pct, 4.2)
            self.assertAlmostEqual(snap.best_apy_pct, 4.2)

    def test_single_adapter_best_equals_avg(self):
        status = {"base_a": {"chain": "base", "apy_pct": 7.0, "tier": "T2"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("base")
            self.assertAlmostEqual(snap.avg_apy_pct, snap.best_apy_pct)

    def test_multiple_adapters_avg_apy(self):
        status = {
            "a": {"chain": "base", "apy_pct": 4.0, "tier": "T2"},
            "b": {"chain": "base", "apy_pct": 6.0, "tier": "T2"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("base")
            self.assertAlmostEqual(snap.avg_apy_pct, 5.0)

    def test_multiple_adapters_best_apy(self):
        status = {
            "a": {"chain": "arbitrum", "apy_pct": 5.0, "tier": "T1"},
            "b": {"chain": "arbitrum", "apy_pct": 9.0, "tier": "T2"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("arbitrum")
            self.assertAlmostEqual(snap.best_apy_pct, 9.0)
            self.assertEqual(snap.best_adapter, "b")

    def test_total_tvl_sum(self):
        status = {
            "a": {"chain": "base", "apy_pct": 4.0, "tier": "T2", "tvl_usd": 100_000},
            "b": {"chain": "base", "apy_pct": 6.0, "tier": "T2", "tvl_usd": 200_000},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("base")
            self.assertAlmostEqual(snap.total_tvl_usd, 300_000.0)

    def test_healthy_count_all_healthy(self):
        status = {
            "a": {"chain": "optimism", "apy_pct": 4.0, "tier": "T1", "usdc_price": 1.0},
            "b": {"chain": "optimism", "apy_pct": 5.0, "tier": "T1", "usdc_price": 0.999},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("optimism")
            self.assertEqual(snap.healthy_count, 2)

    def test_healthy_count_depeg_detected(self):
        status = {
            "a": {"chain": "optimism", "apy_pct": 4.0, "tier": "T1", "usdc_price": 0.98},  # depeg
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("optimism")
            self.assertEqual(snap.healthy_count, 0)

    def test_chain_normalization_alias(self):
        status = {"arb_a": {"network": "arbitrum", "apy_pct": 5.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("arb")  # alias
            self.assertEqual(snap.adapter_count, 1)

    def test_gas_savings_default_ethereum(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            snap = m.get_chain_snapshot("ethereum")
            self.assertEqual(snap.avg_gas_savings_pct, 0.0)

    def test_gas_savings_l2_default_optimism(self):
        status = {"op_a": {"chain": "optimism", "apy_pct": 5.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("optimism")
            self.assertGreater(snap.avg_gas_savings_pct, 0.0)

    def test_gas_savings_explicit_field(self):
        status = {"op_a": {
            "chain": "optimism", "apy_pct": 5.0, "tier": "T1",
            "gas_savings_pct": 95.0,
        }}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            snap = m.get_chain_snapshot("optimism")
            self.assertAlmostEqual(snap.avg_gas_savings_pct, 95.0)

    def test_timestamp_iso_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            snap = m.get_chain_snapshot("ethereum")
            # Should be parseable as ISO datetime
            dt = datetime.fromisoformat(snap.timestamp.replace("Z", "+00:00"))
            self.assertIsInstance(dt, datetime)


# ===========================================================================
# TestGetReport
# ===========================================================================

class TestGetReport(unittest.TestCase):
    """12 tests — full report correctness."""

    def test_all_chains_in_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            for chain in SUPPORTED_CHAINS:
                self.assertIn(chain, report.chains)

    def test_report_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            self.assertIsInstance(report, MultiChainReport)

    def test_best_chain_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            self.assertIn(report.best_chain, SUPPORTED_CHAINS)

    def test_best_chain_has_highest_avg_apy(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            best_snap = report.chains[report.best_chain]
            for chain, snap in report.chains.items():
                if snap.adapter_count > 0:
                    self.assertLessEqual(snap.avg_apy_pct, best_snap.avg_apy_pct)

    def test_best_adapter_overall_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            self.assertNotEqual(report.best_adapter_overall, "")

    def test_best_apy_overall_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            self.assertGreater(report.best_apy_overall, 0.0)

    def test_total_adapters_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            expected = sum(s.adapter_count for s in report.chains.values())
            self.assertEqual(report.total_adapters, expected)

    def test_total_tvl_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            self.assertGreater(report.total_tvl_usd, 0.0)

    def test_empty_data_report_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            report = m.get_report()
            self.assertEqual(report.total_adapters, 0)
            self.assertEqual(report.best_chain, "ethereum")

    def test_l2_premium_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            # L2 chains have entries, so l2_premium should be non-zero
            self.assertIsInstance(report.l2_premium_pct, float)

    def test_l2_premium_no_l2_data(self):
        # Only ethereum entries → l2_premium = 0.0
        status = {"eth_a": {"chain": "ethereum", "apy_pct": 4.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            report = m.get_report()
            self.assertEqual(report.l2_premium_pct, 0.0)

    def test_report_generated_at_valid_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            report = m.get_report()
            dt = datetime.fromisoformat(report.generated_at.replace("Z", "+00:00"))
            self.assertIsInstance(dt, datetime)


# ===========================================================================
# TestGetL2Opportunities
# ===========================================================================

class TestGetL2Opportunities(unittest.TestCase):
    """10 tests — filter, sort, edge cases."""

    def test_returns_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities()
            self.assertIsInstance(opps, list)

    def test_all_are_l2(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            for opp in opps:
                self.assertIn(opp["chain"], L2_CHAINS)

    def test_min_apy_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=6.0)
            for opp in opps:
                self.assertGreaterEqual(opp["apy_pct"], 6.0)

    def test_sorted_desc(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            apys = [o["apy_pct"] for o in opps]
            self.assertEqual(apys, sorted(apys, reverse=True))

    def test_empty_result_high_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=999.0)
            self.assertEqual(opps, [])

    def test_opportunity_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            if opps:
                required = {"chain", "adapter", "apy_pct", "risk_score", "tvl_usd", "gas_savings_pct"}
                self.assertTrue(required.issubset(set(opps[0].keys())))

    def test_no_l2_data_empty_result(self):
        status = {"eth_a": {"chain": "ethereum", "apy_pct": 5.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            self.assertEqual(opps, [])

    def test_default_threshold_5pct(self):
        status = {
            "b_low": {"chain": "base", "apy_pct": 3.0, "tier": "T2"},
            "b_high": {"chain": "base", "apy_pct": 7.0, "tier": "T2"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            opps = m.get_l2_opportunities()  # default 5.0%
            self.assertEqual(len(opps), 1)
            self.assertAlmostEqual(opps[0]["apy_pct"], 7.0)

    def test_zero_threshold_includes_all_l2(self):
        status = {
            "a": {"chain": "base", "apy_pct": 0.5, "tier": "T2"},
            "b": {"chain": "arbitrum", "apy_pct": 1.0, "tier": "T1"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            self.assertEqual(len(opps), 2)

    def test_gas_savings_pct_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            opps = m.get_l2_opportunities(min_apy_pct=0.0)
            for opp in opps:
                self.assertIsInstance(opp["gas_savings_pct"], float)


# ===========================================================================
# TestGetBestPerChain
# ===========================================================================

class TestGetBestPerChain(unittest.TestCase):
    """10 tests — best adapter per chain."""

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            result = m.get_best_per_chain()
            self.assertIsInstance(result, dict)

    def test_keys_are_supported_chains(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            result = m.get_best_per_chain()
            for chain in result:
                self.assertIn(chain, SUPPORTED_CHAINS)

    def test_empty_chains_not_in_result(self):
        status = {"eth_a": {"chain": "ethereum", "apy_pct": 4.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            result = m.get_best_per_chain()
            # polygon has no data
            self.assertNotIn("polygon", result)

    def test_best_adapter_value_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            result = m.get_best_per_chain()
            for chain, entry in result.items():
                self.assertIn("adapter", entry)
                self.assertIn("apy_pct", entry)
                self.assertIn("risk_score", entry)

    def test_correct_best_ethereum(self):
        # compound_eth has 4.8 > aave_eth 4.2
        status = {
            "aave_eth": {"chain": "ethereum", "apy_pct": 4.2, "tier": "T1"},
            "compound_eth": {"chain": "ethereum", "apy_pct": 4.8, "tier": "T1"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            result = m.get_best_per_chain()
            self.assertEqual(result["ethereum"]["adapter"], "compound_eth")

    def test_correct_best_base(self):
        # morpho_base 7.5 > aave_base 4.5
        status = {
            "aave_base": {"chain": "base", "apy_pct": 4.5, "tier": "T2"},
            "morpho_base": {"chain": "base", "apy_pct": 7.5, "tier": "T2"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            result = m.get_best_per_chain()
            self.assertEqual(result["base"]["adapter"], "morpho_base")
            self.assertAlmostEqual(result["base"]["apy_pct"], 7.5)

    def test_single_adapter_is_best(self):
        status = {"only_one": {"chain": "optimism", "apy_pct": 5.0, "tier": "T1"}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            result = m.get_best_per_chain()
            self.assertEqual(result["optimism"]["adapter"], "only_one")

    def test_empty_data_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            result = m.get_best_per_chain()
            self.assertEqual(result, {})

    def test_risk_score_present(self):
        status = {"x": {"chain": "arbitrum", "apy_pct": 5.0, "tier": "T1", "risk_score": 0.22}}
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, status)
            result = m.get_best_per_chain()
            self.assertAlmostEqual(result["arbitrum"]["risk_score"], 0.22)

    def test_full_mock_has_multiple_chains(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            result = m.get_best_per_chain()
            # We have: ethereum, arbitrum, base, optimism in MOCK_ENTRIES
            for chain in ("ethereum", "arbitrum", "base", "optimism"):
                self.assertIn(chain, result)


# ===========================================================================
# TestSaveReport
# ===========================================================================

class TestSaveReport(unittest.TestCase):
    """8 tests — atomic write, ring-buffer, path returned."""

    def test_returns_path_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            path = m.save_report()
            self.assertIsInstance(path, str)

    def test_file_exists_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            path = m.save_report()
            self.assertTrue(os.path.isfile(path))

    def test_saved_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            path = m.save_report()
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)

    def test_saved_file_has_latest_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            path = m.save_report()
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("latest", data)

    def test_ring_buffer_max_30(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            # Save 35 times
            for _ in range(35):
                path = m.save_report()
            with open(path) as fh:
                data = json.load(fh)
            self.assertLessEqual(len(data["snapshots"]), 30)

    def test_ring_buffer_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            for _ in range(5):
                path = m.save_report()
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["snapshots"]), 5)

    def test_custom_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = _write_status(tmp, MOCK_ENTRIES)
            m = MultiChainMonitor(data_path=status_path)
            out = os.path.join(tmp, "custom_report.json")
            returned = m.save_report(output_path=out)
            self.assertEqual(returned, out)
            self.assertTrue(os.path.isfile(out))

    def test_no_tmp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            m.save_report()
            # .tmp file should be cleaned up
            tmp_files = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


# ===========================================================================
# TestToDict
# ===========================================================================

class TestToDict(unittest.TestCase):
    """8 tests — all fields present, JSON serializable."""

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            self.assertIsInstance(d, dict)

    def test_top_level_keys(self):
        required = {
            "generated_at", "chains", "best_chain",
            "best_adapter_overall", "best_apy_overall",
            "total_adapters", "total_tvl_usd", "l2_premium_pct",
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            self.assertTrue(required.issubset(set(d.keys())))

    def test_chains_has_all_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            for chain in SUPPORTED_CHAINS:
                self.assertIn(chain, d["chains"])

    def test_chain_entry_fields(self):
        required = {
            "chain", "adapter_count", "avg_apy_pct", "best_apy_pct",
            "best_adapter", "avg_risk_score", "total_tvl_usd",
            "avg_gas_savings_pct", "healthy_count", "timestamp",
        }
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            snap = d["chains"]["base"]
            self.assertTrue(required.issubset(set(snap.keys())))

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            # Should not raise
            serialized = json.dumps(d)
            self.assertIsInstance(serialized, str)

    def test_total_adapters_nonneg(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            self.assertGreaterEqual(d["total_adapters"], 0)

    def test_best_apy_matches_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, MOCK_ENTRIES)
            d = m.to_dict()
            report = m.get_report()
            self.assertAlmostEqual(d["best_apy_overall"], report.best_apy_overall)

    def test_empty_data_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp, {})
            d = m.to_dict()
            self.assertIsInstance(d, dict)
            self.assertEqual(d["total_adapters"], 0)


# ===========================================================================
# TestHelperFunctions (bonus)
# ===========================================================================

class TestHelperFunctions(unittest.TestCase):
    """8 extra tests — internal helper functions."""

    def test_normalize_chain_ethereum(self):
        self.assertEqual(_normalize_chain("mainnet"), "ethereum")
        self.assertEqual(_normalize_chain("ETH"), "ethereum")
        self.assertEqual(_normalize_chain("Ethereum"), "ethereum")

    def test_normalize_chain_arbitrum(self):
        self.assertEqual(_normalize_chain("arb"), "arbitrum")
        self.assertEqual(_normalize_chain("Arbitrum-One"), "arbitrum")

    def test_normalize_chain_base(self):
        self.assertEqual(_normalize_chain("Base"), "base")

    def test_normalize_chain_optimism(self):
        self.assertEqual(_normalize_chain("OP"), "optimism")

    def test_normalize_chain_unknown(self):
        result = _normalize_chain("unknown_chain")
        self.assertEqual(result, "unknown_chain")

    def test_extract_apy_prefers_apy_pct(self):
        entry = {"apy_pct": 5.0, "apy": 3.0}
        self.assertAlmostEqual(_extract_apy(entry), 5.0)

    def test_extract_apy_bool_rejected(self):
        entry = {"apy_pct": True}
        self.assertEqual(_extract_apy(entry), 0.0)

    def test_extract_peg_healthy_default_safe(self):
        self.assertTrue(_extract_peg_healthy({}))
        self.assertTrue(_extract_peg_healthy({"usdc_price": 1.001}))
        self.assertFalse(_extract_peg_healthy({"usdc_price": 0.97}))


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
