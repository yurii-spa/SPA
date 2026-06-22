"""
Tests for MP-711: ProtocolDominanceAnalyzer
≥65 unittest cases covering shares, HHI, market structure, moat, dynamics,
warnings, persistence, edge cases.
"""

import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_dominance_analyzer import (
    ProtocolMarketShare,
    DominanceReport,
    compute_shares,
    compute_hhi,
    analyze,
    compare_categories,
    save_results,
    load_history,
    MAX_ENTRIES,
    _market_structure,
    _moat_score,
    _category_health,
    _build_warnings,
)

# Convenience type
ProtocolRaw = tuple  # (protocol, tvl, growth, users, revenue)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

LENDING_4 = [
    ("Aave V3",     5_000_000_000,  10.0, 50000, 2_000_000.0),
    ("Compound V3", 1_500_000_000,   5.0, 15000,   500_000.0),
    ("Morpho",        800_000_000,  35.0,  8000,   200_000.0),
    ("Euler V2",      300_000_000,  -5.0,  3000,    50_000.0),
]

EQUAL_4 = [
    ("A", 1_000_000.0, 0.0, 0, 0.0),
    ("B", 1_000_000.0, 0.0, 0, 0.0),
    ("C", 1_000_000.0, 0.0, 0, 0.0),
    ("D", 1_000_000.0, 0.0, 0, 0.0),
]

SINGLE = [("OnlyOne", 5_000_000_000.0, 5.0, 100, 1_000_000.0)]


# ---------------------------------------------------------------------------
# compute_shares
# ---------------------------------------------------------------------------

class TestComputeShares(unittest.TestCase):

    def test_shares_sum_to_100(self):
        shares = compute_shares(LENDING_4, "lending")
        total = sum(p.market_share_pct for p in shares)
        self.assertAlmostEqual(total, 100.0, places=5)

    def test_equal_protocols_25_each(self):
        shares = compute_shares(EQUAL_4, "lending")
        for p in shares:
            self.assertAlmostEqual(p.market_share_pct, 25.0, places=5)

    def test_single_protocol_100_pct(self):
        shares = compute_shares(SINGLE, "lending")
        self.assertAlmostEqual(shares[0].market_share_pct, 100.0, places=5)

    def test_category_assigned(self):
        shares = compute_shares(SINGLE, "dex")
        self.assertEqual(shares[0].category, "dex")

    def test_tvl_preserved(self):
        shares = compute_shares(SINGLE, "lending")
        self.assertAlmostEqual(shares[0].tvl_usd, 5_000_000_000.0)

    def test_growth_preserved(self):
        shares = compute_shares(LENDING_4, "lending")
        protocols_by_name = {p.protocol: p for p in shares}
        self.assertAlmostEqual(protocols_by_name["Morpho"].tvl_30d_growth_pct, 35.0)

    def test_user_count_preserved(self):
        shares = compute_shares(LENDING_4, "lending")
        protocols_by_name = {p.protocol: p for p in shares}
        self.assertEqual(protocols_by_name["Aave V3"].user_count, 50000)

    def test_revenue_preserved(self):
        shares = compute_shares(LENDING_4, "lending")
        protocols_by_name = {p.protocol: p for p in shares}
        self.assertAlmostEqual(protocols_by_name["Aave V3"].revenue_30d_usd, 2_000_000.0)

    def test_correct_leader_share(self):
        # Aave = 5B out of 7.6B
        shares = compute_shares(LENDING_4, "lending")
        total = sum(p.tvl_usd for p in shares)
        expected = 5_000_000_000 / total * 100
        protocols_by_name = {p.protocol: p for p in shares}
        self.assertAlmostEqual(protocols_by_name["Aave V3"].market_share_pct, expected, places=4)


# ---------------------------------------------------------------------------
# compute_hhi
# ---------------------------------------------------------------------------

class TestComputeHhi(unittest.TestCase):

    def test_single_protocol_hhi_1(self):
        self.assertAlmostEqual(compute_hhi([100.0]), 1.0, places=5)

    def test_two_equal_hhi_0_5(self):
        self.assertAlmostEqual(compute_hhi([50.0, 50.0]), 0.5, places=5)

    def test_four_equal_hhi_0_25(self):
        self.assertAlmostEqual(compute_hhi([25.0, 25.0, 25.0, 25.0]), 0.25, places=5)

    def test_empty_hhi_0(self):
        self.assertAlmostEqual(compute_hhi([]), 0.0, places=5)

    def test_concentrated_market_high_hhi(self):
        # 90% + 10% → (0.9)² + (0.1)² = 0.81 + 0.01 = 0.82
        self.assertAlmostEqual(compute_hhi([90.0, 10.0]), 0.82, places=5)

    def test_competitive_market_low_hhi(self):
        # 10 equal protocols at 10% each → 10 * 0.01 = 0.1
        self.assertAlmostEqual(compute_hhi([10.0] * 10), 0.10, places=5)


# ---------------------------------------------------------------------------
# _market_structure
# ---------------------------------------------------------------------------

class TestMarketStructure(unittest.TestCase):

    def test_monopoly(self):
        self.assertEqual(_market_structure(75.0, 15.0, 80.0), "MONOPOLY")

    def test_duopoly_top2_over_80(self):
        # top1=45, top2=40 → top1+top2=85>80, top1<70 → DUOPOLY
        self.assertEqual(_market_structure(45.0, 40.0, 90.0), "DUOPOLY")

    def test_oligopoly_cr4_over_70(self):
        # top1=30, top2=25 → top1+top2=55<80; cr4=75>70 → OLIGOPOLY
        self.assertEqual(_market_structure(30.0, 25.0, 75.0), "OLIGOPOLY")

    def test_competitive(self):
        self.assertEqual(_market_structure(20.0, 18.0, 60.0), "COMPETITIVE")

    def test_monopoly_boundary_above(self):
        self.assertEqual(_market_structure(71.0, 15.0, 75.0), "MONOPOLY")

    def test_not_monopoly_at_70(self):
        # top1=70 is not > 70
        result = _market_structure(70.0, 15.0, 80.0)
        self.assertNotEqual(result, "MONOPOLY")


# ---------------------------------------------------------------------------
# _moat_score
# ---------------------------------------------------------------------------

class TestMoatScore(unittest.TestCase):

    def test_moat_capped_at_100(self):
        leader = ProtocolMarketShare(
            protocol="X", category="lending",
            tvl_usd=1e10, market_share_pct=100.0,
            tvl_30d_growth_pct=0.0, user_count=0,
            revenue_30d_usd=1_000_000_000.0,   # huge revenue
        )
        score = _moat_score(leader, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_zero_revenue_lower_score(self):
        leader_no_revenue = ProtocolMarketShare(
            protocol="X", category="lending",
            tvl_usd=1e9, market_share_pct=50.0,
            tvl_30d_growth_pct=0.0, user_count=0,
            revenue_30d_usd=0.0,
        )
        leader_with_revenue = ProtocolMarketShare(
            protocol="X", category="lending",
            tvl_usd=1e9, market_share_pct=50.0,
            tvl_30d_growth_pct=0.0, user_count=0,
            revenue_30d_usd=10_000_000.0,
        )
        score_no = _moat_score(leader_no_revenue, 0.5)
        score_with = _moat_score(leader_with_revenue, 0.5)
        self.assertGreater(score_with, score_no)

    def test_moat_formula(self):
        leader = ProtocolMarketShare(
            protocol="X", category="lending",
            tvl_usd=1e9, market_share_pct=60.0,
            tvl_30d_growth_pct=0.0, user_count=0,
            revenue_30d_usd=500_000.0,
        )
        hhi = 0.4
        revenue_score = min(100.0, 500_000.0 / 1_000_000.0)  # 0.5
        expected = 60.0 * 0.4 + (1.0 - hhi) * 30.0 + revenue_score * 0.3
        self.assertAlmostEqual(_moat_score(leader, hhi), min(100.0, expected), places=4)


# ---------------------------------------------------------------------------
# _category_health
# ---------------------------------------------------------------------------

class TestCategoryHealth(unittest.TestCase):

    def test_healthy(self):
        self.assertEqual(_category_health(0.20), "HEALTHY")

    def test_concentrated(self):
        self.assertEqual(_category_health(0.35), "CONCENTRATED")

    def test_dominated(self):
        self.assertEqual(_category_health(0.60), "DOMINATED")

    def test_boundary_healthy_concentrated(self):
        # hhi=0.25 is not < 0.25, not < 0.50 → not HEALTHY, but < 0.50 → CONCENTRATED
        self.assertEqual(_category_health(0.25), "CONCENTRATED")

    def test_boundary_concentrated_dominated(self):
        # hhi=0.50 is not < 0.50 → DOMINATED
        self.assertEqual(_category_health(0.50), "DOMINATED")


# ---------------------------------------------------------------------------
# _build_warnings
# ---------------------------------------------------------------------------

class TestBuildWarnings(unittest.TestCase):

    def _proto(self, name, growth):
        return ProtocolMarketShare(
            protocol=name, category="lending",
            tvl_usd=1e9, market_share_pct=50.0,
            tvl_30d_growth_pct=growth,
            user_count=0, revenue_30d_usd=0.0,
        )

    def test_single_protocol_dominance_warning(self):
        protos = [self._proto("A", 0.0)]
        warns = _build_warnings(65.0, protos)
        self.assertIn("single protocol dominance", warns)

    def test_no_dominance_warning_below_60(self):
        protos = [self._proto("A", 0.0)]
        warns = _build_warnings(55.0, protos)
        self.assertNotIn("single protocol dominance", warns)

    def test_rapid_challenger_growth(self):
        protos = [self._proto("A", 10.0), self._proto("B", 60.0)]
        warns = _build_warnings(30.0, protos)
        self.assertIn("rapid challenger growth", warns)

    def test_no_rapid_growth_at_50(self):
        # boundary: growth must be > 50
        protos = [self._proto("A", 50.0)]
        warns = _build_warnings(30.0, protos)
        self.assertNotIn("rapid challenger growth", warns)

    def test_tvl_outflow_warning(self):
        protos = [self._proto("A", -25.0)]
        warns = _build_warnings(30.0, protos)
        self.assertIn("major TVL outflow detected", warns)

    def test_no_outflow_at_minus_20(self):
        protos = [self._proto("A", -20.0)]
        warns = _build_warnings(30.0, protos)
        self.assertNotIn("major TVL outflow detected", warns)

    def test_no_warnings(self):
        protos = [self._proto("A", 10.0)]
        warns = _build_warnings(30.0, protos)
        self.assertEqual(warns, [])

    def test_multiple_warnings_combined(self):
        protos = [self._proto("A", 60.0), self._proto("B", -30.0)]
        warns = _build_warnings(70.0, protos)
        self.assertIn("single protocol dominance", warns)
        self.assertIn("rapid challenger growth", warns)
        self.assertIn("major TVL outflow detected", warns)


# ---------------------------------------------------------------------------
# analyze()
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):

    def test_returns_dominance_report(self):
        report = analyze("lending", LENDING_4)
        self.assertIsInstance(report, DominanceReport)

    def test_protocols_sorted_by_tvl_desc(self):
        report = analyze("lending", LENDING_4)
        tvls = [p.tvl_usd for p in report.protocols]
        self.assertEqual(tvls, sorted(tvls, reverse=True))

    def test_market_leader_is_highest_tvl(self):
        report = analyze("lending", LENDING_4)
        self.assertEqual(report.market_leader, "Aave V3")

    def test_challenger_is_second_tvl(self):
        report = analyze("lending", LENDING_4)
        self.assertEqual(report.challenger, "Compound V3")

    def test_challenger_none_for_single_protocol(self):
        report = analyze("lending", SINGLE)
        self.assertEqual(report.challenger, "none")

    def test_fastest_grower(self):
        report = analyze("lending", LENDING_4)
        self.assertEqual(report.fastest_grower, "Morpho")

    def test_total_tvl_correct(self):
        report = analyze("lending", LENDING_4)
        expected = sum(p[1] for p in LENDING_4)
        self.assertAlmostEqual(report.total_tvl_usd, expected, places=1)

    def test_hhi_range(self):
        report = analyze("lending", LENDING_4)
        self.assertGreater(report.hhi, 0.0)
        self.assertLessEqual(report.hhi, 1.0)

    def test_single_protocol_hhi_1(self):
        report = analyze("lending", SINGLE)
        self.assertAlmostEqual(report.hhi, 1.0, places=5)

    def test_equal_protocols_hhi_0_25(self):
        report = analyze("lending", EQUAL_4)
        self.assertAlmostEqual(report.hhi, 0.25, places=5)

    def test_top1_share_pct_correct(self):
        report = analyze("lending", EQUAL_4)
        self.assertAlmostEqual(report.top1_share_pct, 25.0, places=5)

    def test_top3_share_for_equal(self):
        report = analyze("lending", EQUAL_4)
        self.assertAlmostEqual(report.top3_share_pct, 75.0, places=5)

    def test_cr4_for_four_equal(self):
        report = analyze("lending", EQUAL_4)
        self.assertAlmostEqual(report.cr4, 100.0, places=5)

    def test_cr4_for_single(self):
        report = analyze("lending", SINGLE)
        self.assertAlmostEqual(report.cr4, 100.0, places=5)

    def test_market_structure_monopoly_single(self):
        report = analyze("lending", SINGLE)
        self.assertEqual(report.market_structure, "MONOPOLY")

    def test_market_structure_competitive_equal4(self):
        report = analyze("lending", EQUAL_4)
        # cr4=100>70, top1=25, top1+top2=50 → OLIGOPOLY
        self.assertEqual(report.market_structure, "OLIGOPOLY")

    def test_market_structure_competitive_many(self):
        # 10 equal protocols → share=10 each, cr4=40 → COMPETITIVE
        protos = [(f"P{i}", 1_000_000.0, 0.0, 0, 0.0) for i in range(10)]
        report = analyze("lending", protos)
        self.assertEqual(report.market_structure, "COMPETITIVE")

    def test_category_health_dominated_for_single(self):
        report = analyze("lending", SINGLE)
        self.assertEqual(report.category_health, "DOMINATED")

    def test_category_health_healthy_for_10_equal(self):
        protos = [(f"P{i}", 1_000_000.0, 0.0, 0, 0.0) for i in range(10)]
        report = analyze("lending", protos)
        self.assertEqual(report.category_health, "HEALTHY")

    def test_warnings_list_type(self):
        report = analyze("lending", LENDING_4)
        self.assertIsInstance(report.warnings, list)

    def test_saved_to_set(self):
        report = analyze("lending", LENDING_4)
        self.assertIn("protocol_dominance_log.json", report.saved_to)

    def test_moat_score_range(self):
        report = analyze("lending", LENDING_4)
        self.assertGreaterEqual(report.moat_score, 0.0)
        self.assertLessEqual(report.moat_score, 100.0)


# ---------------------------------------------------------------------------
# compare_categories
# ---------------------------------------------------------------------------

class TestCompareCategories(unittest.TestCase):

    def test_sorted_by_hhi_desc(self):
        r1 = analyze("lending", SINGLE)        # hhi=1.0
        r2 = analyze("dex", EQUAL_4)           # hhi=0.25
        result = compare_categories([r2, r1])
        self.assertAlmostEqual(result[0].hhi, 1.0, places=4)
        self.assertAlmostEqual(result[1].hhi, 0.25, places=4)

    def test_empty_list(self):
        self.assertEqual(compare_categories([]), [])

    def test_single_element(self):
        r = analyze("lending", SINGLE)
        self.assertEqual(compare_categories([r]), [r])


# ---------------------------------------------------------------------------
# Persistence and ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_dominance.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_load_round_trip(self):
        report = analyze("lending", LENDING_4, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["category"], "lending")

    def test_multiple_saves(self):
        for cat in ["lending", "dex", "cdp"]:
            report = analyze(cat, LENDING_4, data_file=self.data_file)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_at_100(self):
        for i in range(110):
            protos = [("A", float(1_000_000 + i), 0.0, 0, 0.0)]
            report = analyze("lending", protos, data_file=self.data_file)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            protos = [("A", float(1_000_000 + i), float(i), 0, 0.0)]
            report = analyze("lending", protos, data_file=self.data_file)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        # Last entry should have tvl_30d_growth_pct for the last protocol = 104
        last_protocol = history[-1]["protocols"][0]
        self.assertAlmostEqual(last_protocol["tvl_30d_growth_pct"], 104.0)

    def test_load_nonexistent_returns_empty(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        result = load_history(data_file=missing)
        self.assertEqual(result, [])

    def test_load_corrupted_json_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("not valid json [[[")
        result = load_history(data_file=self.data_file)
        self.assertEqual(result, [])

    def test_atomic_write_no_tmp_file_remaining(self):
        report = analyze("lending", LENDING_4, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        tmp_file = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_file.exists())

    def test_protocols_list_in_saved_json(self):
        report = analyze("lending", LENDING_4, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertIsInstance(history[0]["protocols"], list)
        self.assertEqual(len(history[0]["protocols"]), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
