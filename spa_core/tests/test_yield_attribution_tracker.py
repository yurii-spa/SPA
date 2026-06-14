"""Unit tests for YieldAttributionTracker (MP-600).

Runs: python3 -m unittest spa_core.tests.test_yield_attribution_tracker -v

Groups
------
TestAdapterContribution          (10) — dataclass fields, types, formulae
TestAttributionReport            (10) — report fields, breakdowns
TestLoadPositions                (12) — file sources, simulation, edge cases
TestLoadAdapterData              (8)  — parsing adapter_status, skip rules
TestComputeContribution          (15) — yield / weight / contribution formulae
TestComputeDiversificationScore  (12) — HHI, edge cases
TestGenerateReport               (15) — full pipeline correctness
TestGetRebalanceSuggestions      (8)  — rebalance hint logic
TestSaveReport                   (5)  — atomic write, ring-buffer
TestFormatTelegramMessage        (5)  — length, content
TestToDict                       (5)  — JSON-serialisable, completeness
                                 ---
Total                            105
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap path so imports work when run directly or via pytest
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.yield_attribution_tracker import (  # noqa: E402
    AdapterContribution,
    AttributionReport,
    YieldAttributionTracker,
    _extract_apy,
    _extract_chain,
    _extract_tier,
    _safe_float,
    RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data_dir(tmp_dir: str) -> Path:
    p = Path(tmp_dir) / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_tracker(data_dir: str) -> YieldAttributionTracker:
    return YieldAttributionTracker(data_path=data_dir)


def _make_adapter_status(adapters: dict) -> dict:
    """Wrap adapters dict in a minimal adapter_status structure."""
    return adapters  # top-level entries with tier key


def _make_contribution(
    adapter_id: str = "aave_v3",
    chain: str = "ethereum",
    tier: str = "T1",
    weight_pct: float = 50.0,
    allocated_usd: float = 50_000.0,
    apy_pct: float = 4.0,
    daily_yield_usd: float = 5.479,
    annual_yield_usd: float = 2000.0,
    contribution_pct: float = 50.0,
) -> AdapterContribution:
    return AdapterContribution(
        adapter_id=adapter_id,
        chain=chain,
        tier=tier,
        weight_pct=weight_pct,
        allocated_usd=allocated_usd,
        apy_pct=apy_pct,
        daily_yield_usd=daily_yield_usd,
        annual_yield_usd=annual_yield_usd,
        contribution_pct=contribution_pct,
    )


# ===========================================================================
# 1. TestAdapterContribution
# ===========================================================================

class TestAdapterContribution(unittest.TestCase):
    """(10) AdapterContribution dataclass."""

    def test_fields_exist(self):
        """All required fields present."""
        c = _make_contribution()
        for attr in (
            "adapter_id", "chain", "tier", "weight_pct", "allocated_usd",
            "apy_pct", "daily_yield_usd", "annual_yield_usd", "contribution_pct",
        ):
            self.assertTrue(hasattr(c, attr), f"Missing field: {attr}")

    def test_field_types(self):
        c = _make_contribution()
        self.assertIsInstance(c.adapter_id, str)
        self.assertIsInstance(c.chain, str)
        self.assertIsInstance(c.tier, str)
        self.assertIsInstance(c.weight_pct, float)
        self.assertIsInstance(c.allocated_usd, float)
        self.assertIsInstance(c.apy_pct, float)
        self.assertIsInstance(c.daily_yield_usd, float)
        self.assertIsInstance(c.annual_yield_usd, float)
        self.assertIsInstance(c.contribution_pct, float)

    def test_daily_yield_formula(self):
        """daily_yield ≈ allocated * apy / 100 / 365"""
        allocated = 36_500.0
        apy = 3.65
        expected_daily = allocated * apy / 100.0 / 365.0
        c = _make_contribution(allocated_usd=allocated, apy_pct=apy, daily_yield_usd=expected_daily)
        self.assertAlmostEqual(c.daily_yield_usd, expected_daily, places=6)

    def test_annual_yield_formula(self):
        """annual_yield = allocated * apy / 100"""
        allocated = 50_000.0
        apy = 5.0
        expected = allocated * apy / 100.0
        c = _make_contribution(allocated_usd=allocated, apy_pct=apy, annual_yield_usd=expected)
        self.assertAlmostEqual(c.annual_yield_usd, expected, places=4)

    def test_single_adapter_weight_100(self):
        """Single adapter occupies 100% of portfolio weight."""
        c = _make_contribution(weight_pct=100.0)
        self.assertAlmostEqual(c.weight_pct, 100.0)

    def test_single_adapter_contribution_100(self):
        """Single adapter contributes 100% of portfolio yield."""
        c = _make_contribution(contribution_pct=100.0)
        self.assertAlmostEqual(c.contribution_pct, 100.0)

    def test_zero_apy_zero_yields(self):
        c = _make_contribution(apy_pct=0.0, daily_yield_usd=0.0, annual_yield_usd=0.0)
        self.assertEqual(c.daily_yield_usd, 0.0)
        self.assertEqual(c.annual_yield_usd, 0.0)

    def test_to_dict_returns_dict(self):
        c = _make_contribution()
        d = c.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("adapter_id", d)
        self.assertIn("contribution_pct", d)

    def test_to_dict_json_serializable(self):
        c = _make_contribution()
        js = json.dumps(c.to_dict())
        self.assertIn("aave_v3", js)

    def test_chain_tier_stored(self):
        c = _make_contribution(chain="arbitrum", tier="T2")
        self.assertEqual(c.chain, "arbitrum")
        self.assertEqual(c.tier, "T2")


# ===========================================================================
# 2. TestAttributionReport
# ===========================================================================

class TestAttributionReport(unittest.TestCase):
    """(10) AttributionReport dataclass."""

    def _build_report(self, contributions=None):
        c1 = _make_contribution("aave", "ethereum", "T1", 60.0, 60_000, 5.0, 8.219, 3000.0, 60.0)
        c2 = _make_contribution("compound", "ethereum", "T1", 40.0, 40_000, 4.0, 4.38, 1600.0, 40.0)
        contribs = contributions if contributions is not None else [c1, c2]
        return AttributionReport(
            generated_at="2026-06-13T00:00:00+00:00",
            total_allocated_usd=100_000.0,
            total_daily_yield_usd=12.599,
            total_annual_yield_usd=4600.0,
            effective_apy_pct=4.6,
            contributions=contribs,
            top_contributor="aave",
            top_by_apy="aave",
            chain_breakdown={"ethereum": {"allocated_usd": 100_000.0, "annual_yield_usd": 4600.0, "weight_pct": 100.0}},
            tier_breakdown={"T1": {"allocated_usd": 100_000.0, "annual_yield_usd": 4600.0, "weight_pct": 100.0}},
            diversification_score=0.48,
        )

    def test_fields_exist(self):
        r = self._build_report()
        for attr in (
            "generated_at", "total_allocated_usd", "total_daily_yield_usd",
            "total_annual_yield_usd", "effective_apy_pct", "contributions",
            "top_contributor", "top_by_apy", "chain_breakdown",
            "tier_breakdown", "diversification_score",
        ):
            self.assertTrue(hasattr(r, attr))

    def test_chain_breakdown_structure(self):
        r = self._build_report()
        for chain_val in r.chain_breakdown.values():
            self.assertIn("allocated_usd", chain_val)
            self.assertIn("annual_yield_usd", chain_val)
            self.assertIn("weight_pct", chain_val)

    def test_tier_breakdown_structure(self):
        r = self._build_report()
        for tier_val in r.tier_breakdown.values():
            self.assertIn("allocated_usd", tier_val)
            self.assertIn("annual_yield_usd", tier_val)
            self.assertIn("weight_pct", tier_val)

    def test_effective_apy_type(self):
        r = self._build_report()
        self.assertIsInstance(r.effective_apy_pct, float)

    def test_top_contributor_is_string(self):
        r = self._build_report()
        self.assertIsInstance(r.top_contributor, str)

    def test_diversification_score_range(self):
        r = self._build_report()
        self.assertGreaterEqual(r.diversification_score, 0.0)
        self.assertLessEqual(r.diversification_score, 1.0)

    def test_chain_breakdown_weight_sums_to_100(self):
        r = self._build_report()
        total = sum(v["weight_pct"] for v in r.chain_breakdown.values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_tier_breakdown_weight_sums_to_100(self):
        r = self._build_report()
        total = sum(v["weight_pct"] for v in r.tier_breakdown.values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_empty_contributions(self):
        r = self._build_report(contributions=[])
        self.assertEqual(r.contributions, [])

    def test_to_dict_works(self):
        r = self._build_report()
        d = r.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("contributions", d)


# ===========================================================================
# 3. TestLoadPositions
# ===========================================================================

class TestLoadPositions(unittest.TestCase):
    """(12) load_positions() — file sources, simulation, edge cases."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    # ---- current_positions.json ---

    def test_load_from_current_positions(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 30_000.0, "compound_v3": 20_000.0}},
        )
        pos = self._tracker().load_positions()
        self.assertIn("aave_v3", pos)
        self.assertAlmostEqual(pos["aave_v3"], 30_000.0)

    def test_load_returns_dict(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 50_000.0}},
        )
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)

    def test_load_skips_negative_allocations(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": -1000.0, "compound_v3": 50_000.0}},
        )
        pos = self._tracker().load_positions()
        self.assertNotIn("aave_v3", pos)
        self.assertIn("compound_v3", pos)

    def test_load_skips_zero_allocations(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 0.0, "compound_v3": 50_000.0}},
        )
        pos = self._tracker().load_positions()
        self.assertNotIn("aave_v3", pos)

    # ---- paper_positions.json takes priority ---

    def test_paper_positions_priority(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 30_000.0}},
        )
        _write_json(
            self._data_dir / "paper_positions.json",
            {"positions": {"morpho": 70_000.0}},
        )
        pos = self._tracker().load_positions()
        self.assertIn("morpho", pos)
        self.assertNotIn("aave_v3", pos)

    # ---- simulation fallback ---

    def test_fallback_simulation_no_file(self):
        """No position files → simulation returns non-empty dict."""
        _write_json(
            self._data_dir / "adapter_status.json",
            {"aave_v3": {"tier": "T1", "apy_pct": 4.0, "tvl_usd": 10_000_000}},
        )
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)
        self.assertTrue(len(pos) > 0)

    def test_simulation_sums_near_default_portfolio(self):
        """Simulated positions sum to ≈ 95% of DEFAULT_PORTFOLIO_USD."""
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "aave_v3": {"tier": "T1", "apy_pct": 4.0, "tvl_usd": 10_000_000},
                "compound_v3": {"tier": "T1", "apy_pct": 5.0, "tvl_usd": 20_000_000},
            },
        )
        pos = self._tracker().load_positions()
        total = sum(pos.values())
        self.assertAlmostEqual(total, 95_000.0, delta=1.0)

    def test_simulation_no_adapter_data(self):
        """No adapter file → empty simulation."""
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)

    # ---- edge cases ---

    def test_empty_positions_file(self):
        """positions key is empty dict → fallback to simulation."""
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {}},
        )
        # Simulation also has no data → returns {}
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)

    def test_corrupt_json(self):
        """Corrupt JSON → silently skipped, falls back."""
        (self._data_dir / "current_positions.json").write_text(
            "{broken json", encoding="utf-8"
        )
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)

    def test_missing_positions_key(self):
        """File without 'positions' key → skipped."""
        _write_json(
            self._data_dir / "current_positions.json",
            {"capital": 100_000.0},
        )
        pos = self._tracker().load_positions()
        self.assertIsInstance(pos, dict)

    def test_positions_values_positive_floats(self):
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 31_946.82}},
        )
        pos = self._tracker().load_positions()
        for v in pos.values():
            self.assertGreater(v, 0.0)
            self.assertIsInstance(v, float)


# ===========================================================================
# 4. TestLoadAdapterData
# ===========================================================================

class TestLoadAdapterData(unittest.TestCase):
    """(8) load_adapter_data() — parsing adapter_status.json."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def test_missing_file_returns_empty(self):
        data = self._tracker().load_adapter_data()
        self.assertEqual(data, {})

    def test_returns_dict(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {"aave_v3": {"tier": "T1", "apy_pct": 4.0}},
        )
        data = self._tracker().load_adapter_data()
        self.assertIsInstance(data, dict)

    def test_entries_with_tier_included(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {"aave_v3": {"tier": "T1", "apy_pct": 4.0}},
        )
        data = self._tracker().load_adapter_data()
        self.assertIn("aave_v3", data)

    def test_skip_non_adapter_keys(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "generated_at": "2026-06-13",
                "mev_protection": {"enabled": False},
                "aave_v3": {"tier": "T1", "apy_pct": 4.0},
            },
        )
        data = self._tracker().load_adapter_data()
        self.assertNotIn("generated_at", data)
        self.assertNotIn("mev_protection", data)
        self.assertIn("aave_v3", data)

    def test_entries_without_tier_skipped(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "aave_v3": {"tier": "T1", "apy_pct": 4.0},
                "some_metadata": {"value": 42},   # no "tier"
            },
        )
        data = self._tracker().load_adapter_data()
        self.assertNotIn("some_metadata", data)

    def test_adapters_array_processed(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "adapters": [
                    {"protocol_key": "compound-v3", "tier": "T1", "mock_apy": {"ethereum": {"USDC": 4.8}}},
                ]
            },
        )
        data = self._tracker().load_adapter_data()
        self.assertTrue("compound-v3" in data or "compound_v3" in data)

    def test_corrupt_json_returns_empty(self):
        (self._data_dir / "adapter_status.json").write_text("{bad", encoding="utf-8")
        data = self._tracker().load_adapter_data()
        self.assertEqual(data, {})

    def test_apy_extractable(self):
        _write_json(
            self._data_dir / "adapter_status.json",
            {"compound_v3": {"tier": "T1", "apy_pct": 5.2}},
        )
        data = self._tracker().load_adapter_data()
        apy = _extract_apy(data["compound_v3"])
        self.assertAlmostEqual(apy, 5.2)


# ===========================================================================
# 5. TestComputeContribution
# ===========================================================================

class TestComputeContribution(unittest.TestCase):
    """(15) compute_contribution() — yield / weight / contribution formulae."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        self._tracker = _make_tracker(str(self._data_dir))

    def _adapter(self, apy=5.0, chain="ethereum", tier="T1", tvl=1e7):
        return {"tier": tier, "apy_pct": apy, "chain": chain, "tvl_usd": tvl}

    def test_daily_yield_formula(self):
        data = self._adapter(apy=3.65)
        c = self._tracker.compute_contribution("x", 36_500.0, data, 36_500.0)
        expected_daily = 36_500.0 * 3.65 / 100.0 / 365.0
        self.assertAlmostEqual(c.daily_yield_usd, expected_daily, places=5)

    def test_annual_yield_formula(self):
        data = self._adapter(apy=5.0)
        c = self._tracker.compute_contribution("x", 50_000.0, data, 50_000.0)
        expected_annual = 50_000.0 * 5.0 / 100.0
        self.assertAlmostEqual(c.annual_yield_usd, expected_annual, places=2)

    def test_weight_pct_single_adapter(self):
        data = self._adapter()
        c = self._tracker.compute_contribution("x", 100_000.0, data, 100_000.0)
        self.assertAlmostEqual(c.weight_pct, 100.0, places=4)

    def test_weight_pct_two_adapters(self):
        data = self._adapter()
        c = self._tracker.compute_contribution("x", 40_000.0, data, 100_000.0)
        self.assertAlmostEqual(c.weight_pct, 40.0, places=4)

    def test_contribution_pct_single_adapter(self):
        """One adapter → 100% of total yield."""
        data = self._adapter(apy=4.0)
        daily = 100_000.0 * 4.0 / 100.0 / 365.0
        c = self._tracker.compute_contribution("x", 100_000.0, data, 100_000.0, daily)
        self.assertAlmostEqual(c.contribution_pct, 100.0, places=3)

    def test_contribution_pct_two_adapters_proportional(self):
        data = self._adapter(apy=4.0)
        daily_adapter = 60_000.0 * 4.0 / 100.0 / 365.0
        total_daily = 100_000.0 * 4.0 / 100.0 / 365.0  # same APY → proportional by allocation
        c = self._tracker.compute_contribution("x", 60_000.0, data, 100_000.0, total_daily)
        self.assertAlmostEqual(c.contribution_pct, 60.0, places=3)

    def test_zero_total_allocated_weight_pct(self):
        data = self._adapter()
        c = self._tracker.compute_contribution("x", 0.0, data, 0.0)
        self.assertEqual(c.weight_pct, 0.0)

    def test_zero_total_daily_yield_contribution_pct(self):
        data = self._adapter(apy=0.0)
        c = self._tracker.compute_contribution("x", 50_000.0, data, 100_000.0, 0.0)
        self.assertEqual(c.contribution_pct, 0.0)

    def test_apy_pct_extracted_from_data(self):
        data = {"tier": "T1", "apy_pct": 7.5, "chain": "ethereum"}
        c = self._tracker.compute_contribution("x", 10_000.0, data, 10_000.0)
        self.assertAlmostEqual(c.apy_pct, 7.5, places=2)

    def test_chain_extracted_from_data(self):
        data = {"tier": "T2", "apy_pct": 6.0, "chain": "arbitrum"}
        c = self._tracker.compute_contribution("x", 10_000.0, data, 10_000.0)
        self.assertEqual(c.chain, "arbitrum")

    def test_tier_extracted_from_data(self):
        data = {"tier": "T2", "apy_pct": 6.0, "chain": "ethereum"}
        c = self._tracker.compute_contribution("x", 10_000.0, data, 10_000.0)
        self.assertEqual(c.tier, "T2")

    def test_unknown_adapter_fallback(self):
        """Empty data → 0 APY, unknown chain/tier."""
        c = self._tracker.compute_contribution("x", 10_000.0, {}, 10_000.0)
        self.assertEqual(c.apy_pct, 0.0)
        self.assertEqual(c.chain, "unknown")
        self.assertEqual(c.tier, "unknown")

    def test_rounding_applied(self):
        data = self._adapter(apy=5.123456789)
        c = self._tracker.compute_contribution("x", 33_333.333, data, 100_000.0)
        # Should be rounded to 4 decimal places
        self.assertEqual(c.apy_pct, round(5.123456789, 4))

    def test_large_allocation(self):
        data = self._adapter(apy=4.0)
        c = self._tracker.compute_contribution("x", 1_000_000.0, data, 1_000_000.0)
        self.assertGreater(c.daily_yield_usd, 0)

    def test_contribution_pct_sum_two_adapters(self):
        """contribution_pct sums to 100% for two adapters."""
        data1 = self._adapter(apy=4.0)
        data2 = self._adapter(apy=6.0)
        daily1 = 60_000.0 * 4.0 / 100.0 / 365.0
        daily2 = 40_000.0 * 6.0 / 100.0 / 365.0
        total_daily = daily1 + daily2
        c1 = self._tracker.compute_contribution("a1", 60_000.0, data1, 100_000.0, total_daily)
        c2 = self._tracker.compute_contribution("a2", 40_000.0, data2, 100_000.0, total_daily)
        self.assertAlmostEqual(c1.contribution_pct + c2.contribution_pct, 100.0, places=3)


# ===========================================================================
# 6. TestComputeDiversificationScore
# ===========================================================================

class TestComputeDiversificationScore(unittest.TestCase):
    """(12) compute_diversification_score() — HHI and edge cases."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        self._tracker = _make_tracker(str(self._data_dir))

    def _contrib(self, weight: float) -> AdapterContribution:
        return _make_contribution(weight_pct=weight)

    def test_empty_returns_zero(self):
        score = self._tracker.compute_diversification_score([])
        self.assertEqual(score, 0.0)

    def test_single_adapter_low_score(self):
        """One adapter at 100% → HHI = 1.0 → score = 0.0."""
        score = self._tracker.compute_diversification_score([self._contrib(100.0)])
        self.assertAlmostEqual(score, 0.0, places=5)

    def test_two_equal_adapters(self):
        """2 × 50% → HHI = 0.5 → score = 0.5."""
        cs = [self._contrib(50.0), self._contrib(50.0)]
        score = self._tracker.compute_diversification_score(cs)
        self.assertAlmostEqual(score, 0.5, places=5)

    def test_four_equal_adapters(self):
        """4 × 25% → HHI = 0.25 → score = 0.75."""
        cs = [self._contrib(25.0) for _ in range(4)]
        score = self._tracker.compute_diversification_score(cs)
        self.assertAlmostEqual(score, 0.75, places=5)

    def test_ten_equal_adapters(self):
        """10 × 10% → HHI = 0.10 → score = 0.90."""
        cs = [self._contrib(10.0) for _ in range(10)]
        score = self._tracker.compute_diversification_score(cs)
        self.assertAlmostEqual(score, 0.90, places=5)

    def test_score_between_zero_and_one(self):
        for weights in ([100.0], [50.0, 50.0], [33.3, 33.3, 33.4]):
            cs = [self._contrib(w) for w in weights]
            score = self._tracker.compute_diversification_score(cs)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_more_adapters_higher_score(self):
        cs2 = [self._contrib(50.0), self._contrib(50.0)]
        cs4 = [self._contrib(25.0) for _ in range(4)]
        s2 = self._tracker.compute_diversification_score(cs2)
        s4 = self._tracker.compute_diversification_score(cs4)
        self.assertGreater(s4, s2)

    def test_returns_float(self):
        score = self._tracker.compute_diversification_score([self._contrib(100.0)])
        self.assertIsInstance(score, float)

    def test_unequal_distribution_score(self):
        """80/20 split: HHI = 0.64+0.04 = 0.68 → score ≈ 0.32."""
        cs = [self._contrib(80.0), self._contrib(20.0)]
        score = self._tracker.compute_diversification_score(cs)
        expected = 1.0 - (0.8**2 + 0.2**2)
        self.assertAlmostEqual(score, expected, places=5)

    def test_hhi_formula(self):
        weights = [30.0, 30.0, 40.0]
        cs = [self._contrib(w) for w in weights]
        hhi = sum((w / 100.0) ** 2 for w in weights)
        expected_score = 1.0 - hhi
        score = self._tracker.compute_diversification_score(cs)
        self.assertAlmostEqual(score, expected_score, places=5)

    def test_zero_weight_adapters_handled(self):
        cs = [self._contrib(100.0), self._contrib(0.0)]
        score = self._tracker.compute_diversification_score(cs)
        # 100%/0%: HHI = 1.0 → score = 0.0
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_score_clamped_to_range(self):
        # Even with numerical noise, result should be [0, 1]
        cs = [self._contrib(99.9999), self._contrib(0.0001)]
        score = self._tracker.compute_diversification_score(cs)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ===========================================================================
# 7. TestGenerateReport
# ===========================================================================

class TestGenerateReport(unittest.TestCase):
    """(15) generate_report() — full pipeline correctness."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        self._adapter_status = {
            "aave_v3":     {"tier": "T1", "apy_pct": 4.0,  "chain": "ethereum"},
            "compound_v3": {"tier": "T1", "apy_pct": 5.0,  "chain": "ethereum"},
            "yearn_v3":    {"tier": "T2", "apy_pct": 6.5,  "chain": "ethereum"},
        }
        _write_json(self._data_dir / "adapter_status.json", self._adapter_status)
        self._positions = {
            "aave_v3":     40_000.0,
            "compound_v3": 35_000.0,
            "yearn_v3":    20_000.0,
        }

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def test_returns_attribution_report(self):
        r = self._tracker().generate_report(self._positions)
        self.assertIsInstance(r, AttributionReport)

    def test_total_allocated_correct(self):
        r = self._tracker().generate_report(self._positions)
        self.assertAlmostEqual(r.total_allocated_usd, 95_000.0, places=1)

    def test_total_daily_yield_correct(self):
        r = self._tracker().generate_report(self._positions)
        expected = (
            40_000.0 * 4.0 / 100.0 / 365.0
            + 35_000.0 * 5.0 / 100.0 / 365.0
            + 20_000.0 * 6.5 / 100.0 / 365.0
        )
        self.assertAlmostEqual(r.total_daily_yield_usd, expected, places=4)

    def test_total_annual_yield_correct(self):
        r = self._tracker().generate_report(self._positions)
        expected = 40_000.0 * 0.04 + 35_000.0 * 0.05 + 20_000.0 * 0.065
        self.assertAlmostEqual(r.total_annual_yield_usd, expected, places=2)

    def test_effective_apy_computed(self):
        r = self._tracker().generate_report(self._positions)
        total_annual = 40_000.0 * 0.04 + 35_000.0 * 0.05 + 20_000.0 * 0.065
        expected_apy = total_annual / 95_000.0 * 100.0
        self.assertAlmostEqual(r.effective_apy_pct, expected_apy, places=2)

    def test_top_contributor_is_highest_contribution(self):
        r = self._tracker().generate_report(self._positions)
        top_c = max(r.contributions, key=lambda c: c.contribution_pct)
        self.assertEqual(r.top_contributor, top_c.adapter_id)

    def test_top_by_apy_is_highest_apy(self):
        r = self._tracker().generate_report(self._positions)
        top_apy = max(r.contributions, key=lambda c: c.apy_pct)
        self.assertEqual(r.top_by_apy, top_apy.adapter_id)

    def test_chain_breakdown_aggregated(self):
        r = self._tracker().generate_report(self._positions)
        # All on ethereum
        self.assertIn("ethereum", r.chain_breakdown)
        self.assertAlmostEqual(r.chain_breakdown["ethereum"]["allocated_usd"], 95_000.0, places=0)

    def test_tier_breakdown_aggregated(self):
        r = self._tracker().generate_report(self._positions)
        self.assertIn("T1", r.tier_breakdown)
        self.assertIn("T2", r.tier_breakdown)

    def test_contributions_sorted_descending(self):
        r = self._tracker().generate_report(self._positions)
        pcts = [c.contribution_pct for c in r.contributions]
        self.assertEqual(pcts, sorted(pcts, reverse=True))

    def test_empty_positions_report(self):
        r = self._tracker().generate_report({})
        self.assertEqual(r.total_allocated_usd, 0.0)
        self.assertEqual(r.contributions, [])

    def test_passed_positions_used(self):
        custom = {"aave_v3": 100_000.0}
        r = self._tracker().generate_report(custom)
        self.assertAlmostEqual(r.total_allocated_usd, 100_000.0, places=0)
        self.assertEqual(len(r.contributions), 1)

    def test_diversification_computed(self):
        r = self._tracker().generate_report(self._positions)
        self.assertGreater(r.diversification_score, 0.0)
        self.assertLessEqual(r.diversification_score, 1.0)

    def test_no_adapter_data_zero_yields(self):
        """Missing adapter_status → contributions with 0 APY."""
        (self._data_dir / "adapter_status.json").unlink()
        r = self._tracker().generate_report(self._positions)
        for c in r.contributions:
            self.assertEqual(c.apy_pct, 0.0)

    def test_contribution_pct_sums_to_100(self):
        r = self._tracker().generate_report(self._positions)
        if r.contributions:
            total = sum(c.contribution_pct for c in r.contributions)
            self.assertAlmostEqual(total, 100.0, places=2)


# ===========================================================================
# 8. TestGetRebalanceSuggestions
# ===========================================================================

class TestGetRebalanceSuggestions(unittest.TestCase):
    """(8) get_rebalance_suggestions() — rebalance hint logic."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def _setup_positions_and_adapters(self, positions, adapter_apys):
        status = {
            aid: {"tier": "T1", "apy_pct": apy, "chain": "ethereum"}
            for aid, apy in adapter_apys.items()
        }
        _write_json(self._data_dir / "adapter_status.json", status)
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": positions},
        )

    def test_returns_list(self):
        self._setup_positions_and_adapters(
            {"aave_v3": 95_000.0}, {"aave_v3": 5.0}
        )
        result = self._tracker().get_rebalance_suggestions()
        self.assertIsInstance(result, list)

    def test_empty_positions_no_suggestions(self):
        result = self._tracker().get_rebalance_suggestions()
        self.assertEqual(result, [])

    def test_balanced_no_suggestions(self):
        """Equal contributions → no suggestions."""
        self._setup_positions_and_adapters(
            {"a": 50_000.0, "b": 50_000.0},
            {"a": 5.0, "b": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=5.0)
        # Both at 50%, min=5% → no underweight (50 >= 5), so no suggestions
        self.assertEqual(result, [])

    def test_underweight_generates_increase(self):
        """Tiny adapter → increase suggestion."""
        self._setup_positions_and_adapters(
            {"big": 95_000.0, "tiny": 100.0},
            {"big": 5.0, "tiny": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=5.0)
        actions = [s["action"] for s in result]
        self.assertIn("increase", actions)

    def test_overweight_generates_decrease(self):
        """Dominant adapter → decrease suggestion."""
        self._setup_positions_and_adapters(
            {"big": 95_000.0, "tiny": 100.0},
            {"big": 5.0, "tiny": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=5.0)
        actions = [s["action"] for s in result]
        self.assertIn("decrease", actions)

    def test_suggestion_has_required_fields(self):
        self._setup_positions_and_adapters(
            {"big": 95_000.0, "tiny": 100.0},
            {"big": 5.0, "tiny": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=5.0)
        for s in result:
            self.assertIn("action", s)
            self.assertIn("adapter_id", s)
            self.assertIn("reason", s)
            self.assertIn("current_contribution_pct", s)

    def test_custom_target_min(self):
        """Target_min = 20%: two adapters of 50/50 → no underweight."""
        self._setup_positions_and_adapters(
            {"a": 50_000.0, "b": 50_000.0},
            {"a": 5.0, "b": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=20.0)
        # 50% > 2*20%=40% → a and b are both overweight, BUT no underweight → no suggestions
        self.assertEqual(result, [])

    def test_no_overweight_no_suggestions(self):
        """All adapters below overweight threshold and above underweight → no suggestions."""
        self._setup_positions_and_adapters(
            {"a": 25_000.0, "b": 25_000.0, "c": 25_000.0, "d": 25_000.0},
            {"a": 5.0, "b": 5.0, "c": 5.0, "d": 5.0},
        )
        result = self._tracker().get_rebalance_suggestions(target_min_contribution_pct=5.0)
        # Each at 25% contribution; 5% min → not underweight; 25% < 2*5%=10% is FALSE
        # 25% > 10% → overweight, but no underweight → no suggestions
        self.assertEqual(result, [])


# ===========================================================================
# 9. TestSaveReport
# ===========================================================================

class TestSaveReport(unittest.TestCase):
    """(5) save_report() — atomic write, ring-buffer, return value."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        _write_json(
            self._data_dir / "adapter_status.json",
            {"aave_v3": {"tier": "T1", "apy_pct": 4.0, "chain": "ethereum"}},
        )
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 95_000.0}},
        )

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def test_creates_file(self):
        t = self._tracker()
        path = t.save_report()
        self.assertTrue(os.path.exists(path))

    def test_returns_string_path(self):
        t = self._tracker()
        path = t.save_report()
        self.assertIsInstance(path, str)

    def test_no_tmp_files_leftover(self):
        t = self._tracker()
        t.save_report()
        tmp_files = [f for f in os.listdir(str(self._data_dir)) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_capped_at_30(self):
        t = self._tracker()
        for _ in range(RING_BUFFER_MAX + 5):
            t.save_report()
        out_path = self._data_dir / "yield_attribution_tracker.json"
        data = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertLessEqual(len(data["snapshots"]), RING_BUFFER_MAX)

    def test_custom_output_path(self):
        t = self._tracker()
        custom = str(self._data_dir / "custom_attr.json")
        path = t.save_report(output_path=custom)
        self.assertTrue(os.path.exists(custom))
        self.assertEqual(path, custom)


# ===========================================================================
# 10. TestFormatTelegramMessage
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):
    """(5) format_telegram_message() — length, content."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "aave_v3":     {"tier": "T1", "apy_pct": 4.0,  "chain": "ethereum"},
                "compound_v3": {"tier": "T1", "apy_pct": 5.0,  "chain": "ethereum"},
            },
        )
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 50_000.0, "compound_v3": 45_000.0}},
        )

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def test_returns_string(self):
        msg = self._tracker().format_telegram_message()
        self.assertIsInstance(msg, str)

    def test_length_under_1500(self):
        msg = self._tracker().format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_effective_apy(self):
        msg = self._tracker().format_telegram_message()
        self.assertTrue(
            "APY" in msg or "apy" in msg.lower(),
            f"APY not in message: {msg!r}",
        )

    def test_contains_diversification_score(self):
        msg = self._tracker().format_telegram_message()
        # diversification_score is a float between 0 and 1
        self.assertIn("Diversification", msg)

    def test_contains_top_contributors(self):
        msg = self._tracker().format_telegram_message()
        self.assertIn("contributor", msg.lower())


# ===========================================================================
# 11. TestToDict
# ===========================================================================

class TestToDict(unittest.TestCase):
    """(5) to_dict() — JSON-serialisable, completeness."""

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._data_dir = _make_data_dir(self._td)
        _write_json(
            self._data_dir / "adapter_status.json",
            {
                "aave_v3": {"tier": "T1", "apy_pct": 4.0, "chain": "ethereum"},
                "yearn_v3": {"tier": "T2", "apy_pct": 6.5, "chain": "ethereum"},
            },
        )
        _write_json(
            self._data_dir / "current_positions.json",
            {"positions": {"aave_v3": 60_000.0, "yearn_v3": 35_000.0}},
        )

    def _tracker(self) -> YieldAttributionTracker:
        return _make_tracker(str(self._data_dir))

    def test_returns_dict(self):
        d = self._tracker().to_dict()
        self.assertIsInstance(d, dict)

    def test_json_serializable(self):
        d = self._tracker().to_dict()
        js = json.dumps(d)  # should not raise
        self.assertIsInstance(js, str)

    def test_has_contributions_key(self):
        d = self._tracker().to_dict()
        self.assertIn("contributions", d)
        self.assertIsInstance(d["contributions"], list)

    def test_has_effective_apy_key(self):
        d = self._tracker().to_dict()
        self.assertIn("effective_apy_pct", d)

    def test_has_all_report_fields(self):
        d = self._tracker().to_dict()
        for field_name in (
            "generated_at", "total_allocated_usd", "total_daily_yield_usd",
            "total_annual_yield_usd", "effective_apy_pct",
            "top_contributor", "top_by_apy",
            "chain_breakdown", "tier_breakdown", "diversification_score",
            "contributions",
        ):
            self.assertIn(field_name, d, f"Missing field: {field_name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
