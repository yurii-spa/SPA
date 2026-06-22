"""
Tests for MP-913: ProtocolDAOTreasuryAnalyzer
Run with: python3 -m unittest spa_core.tests.test_protocol_dao_treasury_analyzer
Target: ≥ 85 tests
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_dao_treasury_analyzer import (
    ProtocolDAOTreasuryAnalyzer,
    _compute_runway,
    _compute_diversification_score,
    _compute_concentration_risk,
    _treasury_label,
    _compute_treasury,
    _atomic_write,
    _load_log,
    _append_log,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _treasury(
    protocol="TestDAO",
    total_usd=50_000_000.0,
    native_token_pct=50.0,
    stablecoins_usd=10_000_000.0,
    eth_btc_usd=5_000_000.0,
    other_assets_usd=5_000_000.0,
    monthly_burn=200_000.0,
    gov_proposals=5,
    last_div_days=90,
):
    return {
        "protocol": protocol,
        "total_usd": total_usd,
        "native_token_pct": native_token_pct,
        "stablecoins_usd": stablecoins_usd,
        "eth_btc_usd": eth_btc_usd,
        "other_assets_usd": other_assets_usd,
        "monthly_runway_burn_usd": monthly_burn,
        "governance_proposals_30d": gov_proposals,
        "last_diversification_date_days_ago": last_div_days,
    }


# ── Runway ────────────────────────────────────────────────────────────────────


class TestRunwayCalculation(unittest.TestCase):

    def test_basic_runway(self):
        # (10M + 5M) / 200k = 75 months
        r = _compute_runway(10_000_000, 5_000_000, 200_000)
        self.assertAlmostEqual(r, 75.0, places=4)

    def test_zero_burn_returns_none(self):
        r = _compute_runway(10_000_000, 5_000_000, 0.0)
        self.assertIsNone(r)

    def test_negative_burn_returns_none(self):
        r = _compute_runway(10_000_000, 5_000_000, -100)
        self.assertIsNone(r)

    def test_high_burn_short_runway(self):
        # (1M + 0) / 500k = 2 months
        r = _compute_runway(1_000_000, 0, 500_000)
        self.assertAlmostEqual(r, 2.0, places=4)

    def test_runway_uses_stablecoins_and_eth_btc_only(self):
        """other_assets not included in runway calculation."""
        r = _compute_runway(
            stablecoins_usd=0,
            eth_btc_usd=0,
            monthly_burn_usd=100_000,
        )
        self.assertAlmostEqual(r, 0.0, places=6)

    def test_runway_no_reserves_is_zero(self):
        r = _compute_runway(0, 0, 100_000)
        self.assertAlmostEqual(r, 0.0, places=6)

    def test_runway_very_long(self):
        r = _compute_runway(1_000_000_000, 0, 1_000)
        self.assertAlmostEqual(r, 1_000_000.0, places=2)

    def test_runway_exactly_12_months(self):
        r = _compute_runway(12_000, 0, 1_000)
        self.assertAlmostEqual(r, 12.0, places=6)

    def test_runway_stablecoins_only(self):
        r = _compute_runway(6_000_000, 0, 500_000)
        self.assertAlmostEqual(r, 12.0, places=6)

    def test_runway_eth_btc_only(self):
        r = _compute_runway(0, 6_000_000, 500_000)
        self.assertAlmostEqual(r, 12.0, places=6)

    def test_runway_combined(self):
        r = _compute_runway(3_000_000, 3_000_000, 500_000)
        self.assertAlmostEqual(r, 12.0, places=6)

    def test_runway_less_than_6_months(self):
        r = _compute_runway(2_000_000, 0, 500_000)
        self.assertAlmostEqual(r, 4.0, places=6)
        self.assertLess(r, 6.0)

    def test_runway_precision(self):
        r = _compute_runway(7_500_000, 2_500_000, 333_333)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 10_000_000 / 333_333, places=3)


# ── Diversification Score ─────────────────────────────────────────────────────


class TestDiversificationScore(unittest.TestCase):

    def test_score_perfect_no_native(self):
        s = _compute_diversification_score(0.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(s, 100.0, places=4)

    def test_score_at_70pct_native_no_penalty(self):
        s = _compute_diversification_score(70.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(s, 100.0, places=4)

    def test_score_exactly_70_no_penalty(self):
        """70 % native → still 100 (threshold is strictly > 70)."""
        s = _compute_diversification_score(70.0, 500_000, 500_000)
        self.assertEqual(s, 100.0)

    def test_score_71_pct_has_penalty(self):
        s = _compute_diversification_score(71.0, 500_000, 500_000)
        self.assertLess(s, 100.0)
        # penalty = (71-70)*2 = 2 → score = 98
        self.assertAlmostEqual(s, 98.0, places=4)

    def test_score_80pct_native_penalty(self):
        # penalty = (80-70)*2 = 20 → score = 80
        s = _compute_diversification_score(80.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(s, 80.0, places=4)

    def test_score_100pct_native_max_penalty(self):
        # penalty = (100-70)*2 = 60 → score = 40 (before other penalties)
        s = _compute_diversification_score(100.0, 0, 0)
        # Also: no stables (-10), no ETH/BTC (-10) → 40 - 10 - 10 = 20
        self.assertAlmostEqual(s, 20.0, places=4)

    def test_score_clamped_at_zero(self):
        """Score never goes below 0."""
        s = _compute_diversification_score(100.0, 0, 0)
        self.assertGreaterEqual(s, 0.0)

    def test_score_clamped_at_100(self):
        """Score never exceeds 100."""
        s = _compute_diversification_score(0.0, 1_000_000, 1_000_000)
        self.assertLessEqual(s, 100.0)

    def test_score_penalty_no_stablecoins(self):
        # No stables: -10 points
        s_with = _compute_diversification_score(50.0, 1_000_000, 1_000_000)
        s_without = _compute_diversification_score(50.0, 0, 1_000_000)
        self.assertAlmostEqual(s_with - s_without, 10.0, places=4)

    def test_score_penalty_no_eth_btc(self):
        # No ETH/BTC: -10 points
        s_with = _compute_diversification_score(50.0, 1_000_000, 1_000_000)
        s_without = _compute_diversification_score(50.0, 1_000_000, 0)
        self.assertAlmostEqual(s_with - s_without, 10.0, places=4)

    def test_score_max_when_well_diversified(self):
        s = _compute_diversification_score(30.0, 5_000_000, 3_000_000)
        self.assertEqual(s, 100.0)

    def test_score_decreases_with_more_native(self):
        s50 = _compute_diversification_score(50.0, 1_000_000, 1_000_000)
        s80 = _compute_diversification_score(80.0, 1_000_000, 1_000_000)
        self.assertGreater(s50, s80)

    def test_score_50pct_native_no_penalty(self):
        s = _compute_diversification_score(50.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(s, 100.0, places=4)

    def test_score_native_pct_clamped_at_100(self):
        """native_pct > 100 should be treated as 100."""
        s = _compute_diversification_score(150.0, 0, 0)
        # (100-70)*2 = 60 penalty → 100-60-10-10 = 20 → clamp = 20
        self.assertGreaterEqual(s, 0.0)

    def test_score_native_pct_negative_clamped_at_zero(self):
        s = _compute_diversification_score(-10.0, 1_000_000, 1_000_000)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)


# ── Concentration Risk ────────────────────────────────────────────────────────


class TestConcentrationRisk(unittest.TestCase):

    def test_basic_concentration_risk(self):
        r = _compute_concentration_risk(50.0)
        self.assertAlmostEqual(r, 50.0, places=4)

    def test_100pct_native_risk_100(self):
        r = _compute_concentration_risk(100.0)
        self.assertAlmostEqual(r, 100.0, places=4)

    def test_zero_native_risk_0(self):
        r = _compute_concentration_risk(0.0)
        self.assertAlmostEqual(r, 0.0, places=4)

    def test_clamped_at_100(self):
        r = _compute_concentration_risk(150.0)
        self.assertEqual(r, 100.0)

    def test_50pct_native(self):
        r = _compute_concentration_risk(50.0)
        self.assertEqual(r, 50.0)

    def test_80pct_native(self):
        r = _compute_concentration_risk(80.0)
        self.assertEqual(r, 80.0)

    def test_not_negative(self):
        r = _compute_concentration_risk(-5.0)
        self.assertEqual(r, 0.0)

    def test_intermediate_values(self):
        for pct in [10, 25, 40, 55, 70, 85, 95]:
            with self.subTest(pct=pct):
                r = _compute_concentration_risk(float(pct))
                self.assertAlmostEqual(r, float(pct), places=4)


# ── Treasury Label ────────────────────────────────────────────────────────────


class TestTreasuryLabel(unittest.TestCase):

    def test_label_very_healthy(self):
        # score=85, runway=40
        label = _treasury_label(85.0, 40.0)
        self.assertEqual(label, "VERY_HEALTHY")

    def test_label_healthy(self):
        # score=65, runway=30
        label = _treasury_label(65.0, 30.0)
        self.assertEqual(label, "HEALTHY")

    def test_label_adequate(self):
        # score=40, runway=18
        label = _treasury_label(40.0, 18.0)
        self.assertEqual(label, "ADEQUATE")

    def test_label_watch(self):
        label = _treasury_label(40.0, 8.0)
        self.assertEqual(label, "WATCH")

    def test_label_critical(self):
        label = _treasury_label(40.0, 3.0)
        self.assertEqual(label, "CRITICAL")

    def test_label_very_healthy_infinite_runway(self):
        label = _treasury_label(90.0, None)
        self.assertEqual(label, "VERY_HEALTHY")

    def test_label_healthy_infinite_runway(self):
        label = _treasury_label(65.0, None)
        self.assertEqual(label, "HEALTHY")

    def test_label_adequate_infinite_runway_low_score(self):
        label = _treasury_label(40.0, None)
        self.assertEqual(label, "ADEQUATE")

    def test_label_boundary_36m_runway_high_score(self):
        label = _treasury_label(80.0, 36.0)
        self.assertEqual(label, "VERY_HEALTHY")

    def test_label_boundary_35m_runway_high_score(self):
        # score=80 but runway just under 36 → not VERY_HEALTHY
        label = _treasury_label(80.0, 35.9)
        self.assertNotEqual(label, "VERY_HEALTHY")

    def test_label_boundary_24m_runway_good_score(self):
        label = _treasury_label(60.0, 24.0)
        self.assertEqual(label, "HEALTHY")

    def test_label_boundary_23m_runway_good_score(self):
        label = _treasury_label(60.0, 23.0)
        self.assertNotEqual(label, "HEALTHY")

    def test_label_boundary_12m_runway(self):
        label = _treasury_label(40.0, 12.0)
        self.assertEqual(label, "ADEQUATE")

    def test_label_boundary_6m_runway(self):
        label = _treasury_label(40.0, 6.0)
        self.assertEqual(label, "WATCH")

    def test_label_below_6m_is_critical(self):
        label = _treasury_label(40.0, 5.9)
        self.assertEqual(label, "CRITICAL")

    def test_label_high_native_low_score_affects_label(self):
        # score = 20 (100 % native, no stable, no eth), runway = 50
        # Not VERY_HEALTHY (score < 80), not HEALTHY (score < 60)
        # runway > 12 → ADEQUATE
        label = _treasury_label(20.0, 50.0)
        self.assertEqual(label, "ADEQUATE")


# ── Flags ─────────────────────────────────────────────────────────────────────


class TestFlags(unittest.TestCase):

    def _flags(self, **kwargs):
        t = _treasury(**kwargs)
        return _compute_treasury(t)["flags"]

    def test_flag_native_heavy(self):
        flags = self._flags(native_token_pct=80.0)
        self.assertIn("NATIVE_HEAVY", flags)

    def test_flag_native_heavy_boundary_71pct(self):
        flags = self._flags(native_token_pct=71.0)
        self.assertIn("NATIVE_HEAVY", flags)

    def test_flag_no_native_heavy_at_70pct(self):
        flags = self._flags(native_token_pct=70.0)
        self.assertNotIn("NATIVE_HEAVY", flags)

    def test_flag_no_native_heavy_below_70(self):
        flags = self._flags(native_token_pct=50.0)
        self.assertNotIn("NATIVE_HEAVY", flags)

    def test_flag_short_runway(self):
        # runway = 0 + 0 / 200k = 0 months
        flags = self._flags(stablecoins_usd=0, eth_btc_usd=0, monthly_burn=200_000)
        self.assertIn("SHORT_RUNWAY", flags)

    def test_flag_short_runway_11m(self):
        # 11 months → SHORT_RUNWAY
        flags = self._flags(stablecoins_usd=11_000_000, eth_btc_usd=0, monthly_burn=1_000_000)
        self.assertIn("SHORT_RUNWAY", flags)

    def test_flag_no_short_runway_at_12m(self):
        # exactly 12 months → not SHORT_RUNWAY
        flags = self._flags(stablecoins_usd=12_000_000, eth_btc_usd=0, monthly_burn=1_000_000)
        self.assertNotIn("SHORT_RUNWAY", flags)

    def test_flag_no_short_runway_zero_burn(self):
        flags = self._flags(monthly_burn=0.0)
        self.assertNotIn("SHORT_RUNWAY", flags)

    def test_flag_never_diversified(self):
        flags = self._flags(last_div_days=400)
        self.assertIn("NEVER_DIVERSIFIED", flags)

    def test_flag_never_diversified_boundary(self):
        flags = self._flags(last_div_days=366)
        self.assertIn("NEVER_DIVERSIFIED", flags)

    def test_flag_no_never_diversified_recently(self):
        flags = self._flags(last_div_days=100)
        self.assertNotIn("NEVER_DIVERSIFIED", flags)

    def test_flag_no_never_diversified_exactly_365(self):
        flags = self._flags(last_div_days=365)
        self.assertNotIn("NEVER_DIVERSIFIED", flags)

    def test_flag_inactive_governance(self):
        flags = self._flags(gov_proposals=0)
        self.assertIn("INACTIVE_GOVERNANCE", flags)

    def test_flag_active_governance(self):
        flags = self._flags(gov_proposals=3)
        self.assertNotIn("INACTIVE_GOVERNANCE", flags)

    def test_flag_active_governance_exactly_1(self):
        flags = self._flags(gov_proposals=1)
        self.assertNotIn("INACTIVE_GOVERNANCE", flags)

    def test_flag_large_treasury(self):
        flags = self._flags(total_usd=200_000_000)
        self.assertIn("LARGE_TREASURY", flags)

    def test_flag_no_large_treasury(self):
        flags = self._flags(total_usd=50_000_000)
        self.assertNotIn("LARGE_TREASURY", flags)

    def test_flag_large_treasury_boundary(self):
        # Exactly 100M: not large (strictly >)
        flags = self._flags(total_usd=100_000_000)
        self.assertNotIn("LARGE_TREASURY", flags)

    def test_flag_large_treasury_above_boundary(self):
        flags = self._flags(total_usd=100_000_001)
        self.assertIn("LARGE_TREASURY", flags)

    def test_flag_multiple_flags(self):
        flags = self._flags(
            native_token_pct=90.0,
            stablecoins_usd=0,
            eth_btc_usd=0,
            monthly_burn=500_000,
            gov_proposals=0,
            last_div_days=400,
        )
        self.assertIn("NATIVE_HEAVY", flags)
        self.assertIn("SHORT_RUNWAY", flags)
        self.assertIn("NEVER_DIVERSIFIED", flags)
        self.assertIn("INACTIVE_GOVERNANCE", flags)

    def test_flag_no_flags_when_healthy(self):
        flags = self._flags(
            native_token_pct=30.0,
            stablecoins_usd=20_000_000,
            eth_btc_usd=5_000_000,
            monthly_burn=100_000,
            gov_proposals=5,
            last_div_days=30,
            total_usd=50_000_000,
        )
        self.assertEqual(flags, [])


# ── Analyze (full pipeline) ───────────────────────────────────────────────────


class TestAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "test_dao_log.json")
        self.analyzer = ProtocolDAOTreasuryAnalyzer(data_file=self.data_file)

    def _single(self, **kwargs):
        t = _treasury(**kwargs)
        return self.analyzer.analyze([t], {"write_log": False})

    def test_analyze_returns_dict(self):
        r = self._single()
        self.assertIsInstance(r, dict)

    def test_analyze_returns_timestamp(self):
        r = self._single()
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_analyze_returns_treasuries_list(self):
        r = self._single()
        self.assertIn("treasuries", r)
        self.assertEqual(len(r["treasuries"]), 1)

    def test_analyze_returns_errors_list(self):
        r = self._single()
        self.assertIn("errors", r)
        self.assertIsInstance(r["errors"], list)

    def test_analyze_returns_aggregates(self):
        r = self._single()
        self.assertIn("aggregates", r)

    def test_analyze_single_treasury(self):
        t = _treasury(protocol="AAVE", total_usd=500_000_000)
        r = self.analyzer.analyze([t], {"write_log": False})
        self.assertEqual(r["treasuries"][0]["protocol"], "AAVE")

    def test_analyze_multiple_treasuries(self):
        ts = [_treasury(protocol=f"DAO_{i}") for i in range(4)]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(len(r["treasuries"]), 4)

    def test_analyze_empty_list(self):
        r = self.analyzer.analyze([], {"write_log": False})
        self.assertEqual(r["aggregates"]["treasury_count"], 0)
        self.assertIsNone(r["aggregates"]["healthiest_treasury"])
        self.assertIsNone(r["aggregates"]["most_critical"])

    def test_analyze_healthiest_treasury(self):
        ts = [
            _treasury(protocol="GOOD", native_token_pct=20.0,
                      stablecoins_usd=50_000_000, eth_btc_usd=10_000_000),
            _treasury(protocol="BAD", native_token_pct=95.0,
                      stablecoins_usd=0, eth_btc_usd=0),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(r["aggregates"]["healthiest_treasury"], "GOOD")

    def test_analyze_most_critical(self):
        ts = [
            _treasury(protocol="GOOD", stablecoins_usd=50_000_000, monthly_burn=100_000),
            _treasury(protocol="BAD", stablecoins_usd=0, eth_btc_usd=0, monthly_burn=500_000),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(r["aggregates"]["most_critical"], "BAD")

    def test_analyze_total_ecosystem_usd(self):
        ts = [
            _treasury(protocol="A", total_usd=100_000_000),
            _treasury(protocol="B", total_usd=200_000_000),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertAlmostEqual(r["aggregates"]["total_ecosystem_usd"], 300_000_000.0, places=2)

    def test_analyze_average_runway_months(self):
        # A: (10M+5M)/200k = 75 months; B: 0/200k = 0 months
        ts = [
            _treasury(protocol="A", stablecoins_usd=10_000_000,
                      eth_btc_usd=5_000_000, monthly_burn=200_000),
            _treasury(protocol="B", stablecoins_usd=0,
                      eth_btc_usd=0, monthly_burn=200_000),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertAlmostEqual(r["aggregates"]["average_runway_months"], 37.5, places=4)

    def test_analyze_average_runway_excludes_infinite(self):
        """Infinite runway (zero burn) treasuries excluded from average."""
        ts = [
            _treasury(protocol="INF", monthly_burn=0),  # infinite
            _treasury(protocol="FIN", stablecoins_usd=12_000_000,
                      eth_btc_usd=0, monthly_burn=1_000_000),  # 12 months
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        # Only FIN (12m) in average
        self.assertAlmostEqual(r["aggregates"]["average_runway_months"], 12.0, places=4)

    def test_analyze_critical_count(self):
        ts = [
            _treasury(protocol="CRIT1", stablecoins_usd=0, eth_btc_usd=0, monthly_burn=500_000),
            _treasury(protocol="CRIT2", stablecoins_usd=0, eth_btc_usd=0, monthly_burn=500_000),
            _treasury(protocol="HEALTHY", stablecoins_usd=100_000_000, monthly_burn=100_000),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(r["aggregates"]["critical_count"], 2)

    def test_analyze_write_log_true_creates_file(self):
        t = _treasury()
        self.analyzer.analyze([t], {"write_log": True})
        self.assertTrue(os.path.exists(self.data_file))

    def test_analyze_write_log_false_no_file(self):
        t = _treasury()
        self.analyzer.analyze([t], {"write_log": False})
        self.assertFalse(os.path.exists(self.data_file))

    def test_analyze_write_log_default_is_true(self):
        t = _treasury()
        self.analyzer.analyze([t], {})
        self.assertTrue(os.path.exists(self.data_file))

    def test_analyze_error_handling_non_dict(self):
        r = self.analyzer.analyze(["not_a_dict"], {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 1)
        self.assertEqual(r["aggregates"]["treasury_count"], 0)

    def test_analyze_raises_typeerror_list(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not_a_list", {})

    def test_analyze_raises_typeerror_config(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([], "not_a_dict")

    def test_analyze_treasury_not_dict_recorded_as_error(self):
        r = self.analyzer.analyze([42, _treasury()], {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 1)
        self.assertEqual(r["aggregates"]["treasury_count"], 1)

    def test_analyze_with_zero_total_usd(self):
        t = _treasury(total_usd=0.0, stablecoins_usd=0, eth_btc_usd=0, monthly_burn=0)
        r = self.analyzer.analyze([t], {"write_log": False})
        self.assertEqual(len(r["errors"]), 0)
        self.assertEqual(r["treasuries"][0]["total_usd"], 0.0)

    def test_analyze_critical_count_is_correct(self):
        ts = [
            _treasury(protocol="A", stablecoins_usd=0, eth_btc_usd=0, monthly_burn=1_000_000),
            _treasury(protocol="B", stablecoins_usd=0, eth_btc_usd=0, monthly_burn=1_000_000),
        ]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(r["aggregates"]["critical_count"], 2)

    def test_analyze_label_in_result(self):
        r = self._single()
        t = r["treasuries"][0]
        self.assertIn("label", t)
        self.assertIn(t["label"],
                      ["VERY_HEALTHY", "HEALTHY", "ADEQUATE", "WATCH", "CRITICAL"])

    def test_analyze_all_metric_fields_present(self):
        r = self._single()
        t = r["treasuries"][0]
        for field in ("runway_months", "diversification_score",
                      "concentration_risk", "label", "flags"):
            self.assertIn(field, t)

    def test_analyze_flags_is_list(self):
        r = self._single()
        self.assertIsInstance(r["treasuries"][0]["flags"], list)

    def test_analyze_treasury_count(self):
        ts = [_treasury() for _ in range(6)]
        r = self.analyzer.analyze(ts, {"write_log": False})
        self.assertEqual(r["aggregates"]["treasury_count"], 6)


# ── Compute Treasury unit tests ───────────────────────────────────────────────


class TestComputeTreasury(unittest.TestCase):

    def _r(self, **kwargs):
        return _compute_treasury(_treasury(**kwargs))

    def test_runway_stored(self):
        r = self._r(stablecoins_usd=10_000_000, eth_btc_usd=5_000_000, monthly_burn=200_000)
        self.assertAlmostEqual(r["runway_months"], 75.0, places=4)

    def test_runway_none_when_zero_burn(self):
        r = self._r(monthly_burn=0.0)
        self.assertIsNone(r["runway_months"])

    def test_diversification_score_range(self):
        r = self._r()
        self.assertGreaterEqual(r["diversification_score"], 0.0)
        self.assertLessEqual(r["diversification_score"], 100.0)

    def test_concentration_risk_range(self):
        r = self._r()
        self.assertGreaterEqual(r["concentration_risk"], 0.0)
        self.assertLessEqual(r["concentration_risk"], 100.0)

    def test_label_valid_value(self):
        r = self._r()
        self.assertIn(r["label"], ["VERY_HEALTHY", "HEALTHY", "ADEQUATE", "WATCH", "CRITICAL"])

    def test_protocol_preserved(self):
        r = self._r(protocol="UNISWAP")
        self.assertEqual(r["protocol"], "UNISWAP")

    def test_total_usd_preserved(self):
        r = self._r(total_usd=999_999_999.0)
        self.assertEqual(r["total_usd"], 999_999_999.0)

    def test_flags_is_list(self):
        r = self._r()
        self.assertIsInstance(r["flags"], list)


# ── Log file ──────────────────────────────────────────────────────────────────


class TestLogFile(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "dao_log.json")

    def test_log_creates_file(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_appends_entries(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury()], {"write_log": True})
        a.analyze([_treasury()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 2)

    def test_log_ring_buffer_cap_100(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        for _ in range(110):
            a.analyze([_treasury()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertLessEqual(len(log), 100)

    def test_log_entry_has_timestamp(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertIn("timestamp", log[-1])

    def test_log_entry_has_treasury_count(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury(), _treasury()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertEqual(log[-1]["treasury_count"], 2)

    def test_log_entry_has_total_ecosystem_usd(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury(total_usd=123_456_789)], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertIn("total_ecosystem_usd", log[-1])

    def test_log_entry_has_critical_count(self):
        a = ProtocolDAOTreasuryAnalyzer(data_file=self.log_path)
        a.analyze([_treasury()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertIn("critical_count", log[-1])

    def test_atomic_write(self):
        _atomic_write(self.log_path, [{"ok": True}])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"ok": True}])

    def test_corrupt_json_returns_empty_list(self):
        with open(self.log_path, "w") as f:
            f.write("{broken json]]]")
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_missing_file_returns_empty_list(self):
        result = _load_log("/no/such/path.json")
        self.assertEqual(result, [])

    def test_append_log_adds_to_existing(self):
        _atomic_write(self.log_path, [{"a": 1}])
        _append_log(self.log_path, {"b": 2})
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[1]["b"], 2)

    def test_non_list_json_loads_as_empty(self):
        _atomic_write(self.log_path, {"not": "list"})
        result = _load_log(self.log_path)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
