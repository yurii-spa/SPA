"""
MP-1300 (v9.16) — Tests for PointInTimeWhitelist and PITEngine.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_point_in_time_whitelist -v

Also compatible with pytest.

Covers:
  1. Default launch dates are correct              (15 tests)
  2. is_eligible before / on / after launch        (12 tests)
  3. eligible_protocols for historical dates        (7 tests)
  4. ineligible_reason strings                      (7 tests)
  5. coverage_stats computation                     (9 tests)
  6. Edge cases: unknown protocol, boundary date    (6 tests)
  7. PITEngine filtering & filter_stats             (8 tests)

Total: 64 tests
"""

import os
import sys
import unittest
from datetime import date, timedelta

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.point_in_time_whitelist import (
    PointInTimeWhitelist,
    _DEFAULT_LAUNCH_DATES,
)
from spa_core.backtesting.pit_engine import PITEngine


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_row(protocol_key: str, ts: str, apy: float = 5.0, tvl: float = 50_000_000.0, tier: str = "T1") -> dict:
    return {
        "timestamp": ts,
        "protocol_key": protocol_key,
        "apy": apy,
        "tvl_usd": tvl,
        "tier": tier,
    }


def _day(base: str, delta: int) -> str:
    """Return base date ± delta days as YYYY-MM-DD."""
    d = date.fromisoformat(base)
    return (d + timedelta(days=delta)).isoformat()


# =============================================================================
# 1. Default launch dates
# =============================================================================

class TestDefaultLaunchDates(unittest.TestCase):
    """Verify the built-in launch-date table has expected values."""

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    # T01 — count
    def test_01_default_table_has_15_protocols(self):
        self.assertEqual(len(self.wl), 15)

    # T02-T16 — individual dates
    def test_02_aave_v2_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["aave_v2_usdc"], "2020-12-17")

    def test_03_compound_v2_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["compound_v2_usdc"], "2018-09-27")

    def test_04_aave_v3_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["aave_v3_usdc"], "2022-03-16")

    def test_05_compound_v3_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["compound_v3_usdc"], "2022-08-26")

    def test_06_morpho_blue(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["morpho_blue"], "2023-11-07")

    def test_07_morpho_steakhouse_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["morpho_steakhouse_usdc"], "2024-01-15")

    def test_08_yearn_v2_yvusdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["yearn_v2_yvusdc"], "2020-07-17")

    def test_09_yearn_v3_yvusdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["yearn_v3_yvusdc"], "2023-06-01")

    def test_10_euler_v2_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["euler_v2_usdc"], "2024-02-06")

    def test_11_sky_susds(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["sky_susds"], "2024-09-01")

    def test_12_pendle_pt_susde(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["pendle_pt_susde_mar2025"], "2024-11-01")

    def test_13_sfrax_usdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["sfrax_usdc"], "2023-03-01")

    def test_14_maple_syrupusdc(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["maple_syrupusdc"], "2024-06-01")

    def test_15_aave_v3_base(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["aave_v3_base"], "2023-08-09")

    def test_16_morpho_blue_base(self):
        self.assertEqual(_DEFAULT_LAUNCH_DATES["morpho_blue_base"], "2023-12-01")


# =============================================================================
# 2. is_eligible — before / on / after launch
# =============================================================================

class TestIsEligible(unittest.TestCase):

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    # aave_v3_usdc launched 2022-03-16
    def test_17_aave_v3_before_launch_false(self):
        self.assertFalse(self.wl.is_eligible("aave_v3_usdc", "2022-03-15"))

    def test_18_aave_v3_on_launch_day_true(self):
        self.assertTrue(self.wl.is_eligible("aave_v3_usdc", "2022-03-16"))

    def test_19_aave_v3_after_launch_true(self):
        self.assertTrue(self.wl.is_eligible("aave_v3_usdc", "2023-01-01"))

    # morpho_steakhouse launched 2024-01-15
    def test_20_morpho_steakhouse_one_day_before_false(self):
        self.assertFalse(self.wl.is_eligible("morpho_steakhouse_usdc", "2024-01-14"))

    def test_21_morpho_steakhouse_on_launch_true(self):
        self.assertTrue(self.wl.is_eligible("morpho_steakhouse_usdc", "2024-01-15"))

    # compound_v2 launched 2018-09-27 — oldest protocol
    def test_22_compound_v2_before_2018_false(self):
        self.assertFalse(self.wl.is_eligible("compound_v2_usdc", "2018-09-26"))

    def test_23_compound_v2_on_launch_true(self):
        self.assertTrue(self.wl.is_eligible("compound_v2_usdc", "2018-09-27"))

    def test_24_compound_v2_recent_date_true(self):
        self.assertTrue(self.wl.is_eligible("compound_v2_usdc", "2026-01-01"))

    # sky_susds launched 2024-09-01
    def test_25_sky_susds_in_2023_false(self):
        self.assertFalse(self.wl.is_eligible("sky_susds", "2023-12-31"))

    def test_26_sky_susds_on_launch_true(self):
        self.assertTrue(self.wl.is_eligible("sky_susds", "2024-09-01"))

    # euler_v2 launched 2024-02-06
    def test_27_euler_v2_day_before_false(self):
        self.assertFalse(self.wl.is_eligible("euler_v2_usdc", "2024-02-05"))

    def test_28_euler_v2_on_launch_true(self):
        self.assertTrue(self.wl.is_eligible("euler_v2_usdc", "2024-02-06"))


# =============================================================================
# 3. eligible_protocols — historical snapshots
# =============================================================================

class TestEligibleProtocols(unittest.TestCase):

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    def test_29_early_2019_only_compound_v2(self):
        eligible = self.wl.eligible_protocols("2019-01-01")
        self.assertIn("compound_v2_usdc", eligible)
        # aave_v2 not yet live
        self.assertNotIn("aave_v2_usdc", eligible)
        self.assertNotIn("aave_v3_usdc", eligible)

    def test_30_2021_aave_v2_and_compound_v2(self):
        eligible = self.wl.eligible_protocols("2021-06-01")
        self.assertIn("compound_v2_usdc", eligible)
        self.assertIn("aave_v2_usdc", eligible)
        self.assertIn("yearn_v2_yvusdc", eligible)
        # aave_v3 not yet
        self.assertNotIn("aave_v3_usdc", eligible)

    def test_31_2022_includes_aave_v3(self):
        eligible = self.wl.eligible_protocols("2022-12-01")
        self.assertIn("aave_v3_usdc", eligible)
        self.assertIn("compound_v3_usdc", eligible)
        # morpho_blue not yet
        self.assertNotIn("morpho_blue", eligible)

    def test_32_2025_all_15_eligible(self):
        eligible = self.wl.eligible_protocols("2025-01-01")
        self.assertEqual(len(eligible), 15)

    def test_33_eligible_returns_sorted_list(self):
        eligible = self.wl.eligible_protocols("2025-06-01")
        self.assertEqual(eligible, sorted(eligible))

    def test_34_empty_on_very_early_date(self):
        eligible = self.wl.eligible_protocols("2010-01-01")
        self.assertEqual(eligible, [])

    def test_35_morpho_blue_base_eligible_after_dec_2023(self):
        before = self.wl.eligible_protocols("2023-11-30")
        after = self.wl.eligible_protocols("2023-12-01")
        self.assertNotIn("morpho_blue_base", before)
        self.assertIn("morpho_blue_base", after)


# =============================================================================
# 4. ineligible_reason
# =============================================================================

class TestIneligibleReason(unittest.TestCase):

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    def test_36_eligible_returns_empty_string(self):
        reason = self.wl.ineligible_reason("aave_v3_usdc", "2023-01-01")
        self.assertEqual(reason, "")

    def test_37_unknown_protocol_reason(self):
        reason = self.wl.ineligible_reason("unknown_protocol", "2023-01-01")
        self.assertIn("not in whitelist", reason)
        self.assertIn("unknown_protocol", reason)

    def test_38_pre_launch_reason_contains_launch_date(self):
        reason = self.wl.ineligible_reason("aave_v3_usdc", "2021-01-01")
        self.assertIn("2022-03-16", reason)
        self.assertIn("2021-01-01", reason)

    def test_39_pre_launch_reason_contains_protocol_name(self):
        reason = self.wl.ineligible_reason("morpho_blue", "2023-01-01")
        self.assertIn("morpho_blue", reason)

    def test_40_on_launch_day_reason_empty(self):
        reason = self.wl.ineligible_reason("morpho_blue", "2023-11-07")
        self.assertEqual(reason, "")

    def test_41_reason_for_day_before_launch_non_empty(self):
        reason = self.wl.ineligible_reason("euler_v2_usdc", "2024-02-05")
        self.assertNotEqual(reason, "")

    def test_42_unknown_protocol_has_reason_even_future_date(self):
        reason = self.wl.ineligible_reason("fake_protocol_xyz", "2099-01-01")
        self.assertIn("not in whitelist", reason)


# =============================================================================
# 5. coverage_stats
# =============================================================================

class TestCoverageStats(unittest.TestCase):

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    def test_43_compound_v2_full_coverage_any_recent_range(self):
        # compound_v2 launched 2018 — should be 100% from 2020 onward
        stats = self.wl.coverage_stats(["compound_v2_usdc"], "2020-01-01", "2020-12-31")
        s = stats["compound_v2_usdc"]
        self.assertEqual(s["eligible_days"], s["total_days"])
        self.assertEqual(s["pct"], 100.0)

    def test_44_aave_v3_partial_coverage_in_2022(self):
        # aave_v3 launched 2022-03-16, checking whole year 2022
        stats = self.wl.coverage_stats(["aave_v3_usdc"], "2022-01-01", "2022-12-31")
        s = stats["aave_v3_usdc"]
        # Jan 1 to Mar 15 = 74 days ineligible
        self.assertGreater(s["eligible_days"], 0)
        self.assertLess(s["eligible_days"], s["total_days"])
        self.assertGreater(s["pct"], 0.0)
        self.assertLess(s["pct"], 100.0)

    def test_45_morpho_steakhouse_zero_coverage_before_launch(self):
        # morpho_steakhouse launched 2024-01-15
        stats = self.wl.coverage_stats(["morpho_steakhouse_usdc"], "2023-01-01", "2023-12-31")
        s = stats["morpho_steakhouse_usdc"]
        self.assertEqual(s["eligible_days"], 0)
        self.assertEqual(s["pct"], 0.0)

    def test_46_unknown_protocol_zero_coverage(self):
        stats = self.wl.coverage_stats(["unknown_xyz"], "2020-01-01", "2025-01-01")
        s = stats["unknown_xyz"]
        self.assertEqual(s["eligible_days"], 0)
        self.assertEqual(s["pct"], 0.0)

    def test_47_total_days_correct_for_one_day_range(self):
        stats = self.wl.coverage_stats(["aave_v3_usdc"], "2023-06-15", "2023-06-15")
        s = stats["aave_v3_usdc"]
        self.assertEqual(s["total_days"], 1)
        self.assertEqual(s["eligible_days"], 1)

    def test_48_multi_protocol_stats(self):
        protos = ["compound_v2_usdc", "aave_v3_usdc", "morpho_blue"]
        stats = self.wl.coverage_stats(protos, "2024-01-01", "2024-12-31")
        # compound_v2 should be 100%
        self.assertEqual(stats["compound_v2_usdc"]["pct"], 100.0)
        # aave_v3 also 100% (launched 2022)
        self.assertEqual(stats["aave_v3_usdc"]["pct"], 100.0)
        # morpho_blue also 100% (launched Nov 2023)
        self.assertEqual(stats["morpho_blue"]["pct"], 100.0)

    def test_49_end_before_start_returns_zero(self):
        stats = self.wl.coverage_stats(["aave_v3_usdc"], "2025-01-01", "2024-01-01")
        s = stats["aave_v3_usdc"]
        self.assertEqual(s["eligible_days"], 0)
        self.assertEqual(s["total_days"], 0)
        self.assertEqual(s["pct"], 0.0)

    def test_50_coverage_stats_exact_eligible_days(self):
        # sky_susds launched 2024-09-01; check range 2024-08-01 to 2024-09-30
        # Aug has 31 days → 31 days ineligible
        # Sep 1 to Sep 30 = 30 days eligible
        # total 61 days; eligible = 30
        stats = self.wl.coverage_stats(["sky_susds"], "2024-08-01", "2024-09-30")
        s = stats["sky_susds"]
        self.assertEqual(s["total_days"], 61)
        self.assertEqual(s["eligible_days"], 30)

    def test_51_coverage_pct_rounded_to_one_decimal(self):
        stats = self.wl.coverage_stats(["aave_v3_usdc"], "2022-01-01", "2022-12-31")
        pct = stats["aave_v3_usdc"]["pct"]
        # Should be a float with at most 1 decimal place
        self.assertIsInstance(pct, float)
        self.assertEqual(round(pct, 1), pct)


# =============================================================================
# 6. Edge cases
# =============================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.wl = PointInTimeWhitelist()

    def test_52_unknown_protocol_is_eligible_false(self):
        self.assertFalse(self.wl.is_eligible("random_unknown_protocol", "2024-01-01"))

    def test_53_unknown_protocol_not_in_eligible_list(self):
        eligible = self.wl.eligible_protocols("2025-01-01")
        self.assertNotIn("random_unknown_protocol", eligible)

    def test_54_custom_launch_dates_override(self):
        custom = {"my_proto": "2025-01-01"}
        wl = PointInTimeWhitelist(launch_dates=custom)
        self.assertFalse(wl.is_eligible("my_proto", "2024-12-31"))
        self.assertTrue(wl.is_eligible("my_proto", "2025-01-01"))
        # default protocols NOT present
        self.assertFalse(wl.is_eligible("aave_v3_usdc", "2025-01-01"))

    def test_55_contains_operator(self):
        self.assertIn("aave_v3_usdc", self.wl)
        self.assertNotIn("nonexistent_protocol", self.wl)

    def test_56_launch_date_returns_none_for_unknown(self):
        self.assertIsNone(self.wl.launch_date("ghost_protocol"))

    def test_57_launch_date_returns_correct_string(self):
        self.assertEqual(self.wl.launch_date("aave_v3_usdc"), "2022-03-16")

    def test_58_known_protocols_sorted(self):
        protos = self.wl.known_protocols()
        self.assertEqual(protos, sorted(protos))


# =============================================================================
# 7. PITEngine — filtering and filter_stats
# =============================================================================

class TestPITEngine(unittest.TestCase):
    """Integration tests for PITEngine wrapping BacktestEngine."""

    def _make_history(self, protocol_key: str, start: str, days: int,
                      apy: float = 5.0, tvl: float = 50_000_000.0, tier: str = "T1"):
        """Generate a simple history of rows for one protocol."""
        rows = []
        d = date.fromisoformat(start)
        for _ in range(days):
            rows.append({
                "timestamp": d.isoformat(),
                "protocol_key": protocol_key,
                "apy": apy,
                "tvl_usd": tvl,
                "tier": tier,
            })
            d += timedelta(days=1)
        return rows

    def test_59_empty_history_returns_empty_result(self):
        engine = PITEngine()
        result = engine.run([])
        self.assertEqual(result.days, 0)
        self.assertEqual(result.equity_curve, [])

    def test_60_pre_launch_rows_are_dropped(self):
        # aave_v3_usdc launched 2022-03-16
        # Feed 10 days before launch — all should be dropped
        history = self._make_history("aave_v3_usdc", "2022-03-06", 10)
        engine = PITEngine()
        engine.run(history)
        stats = engine.filter_stats()
        self.assertEqual(stats["kept_rows"], 0)
        self.assertEqual(stats["dropped_rows"], 10)

    def test_61_post_launch_rows_are_kept(self):
        # 10 days after launch
        history = self._make_history("aave_v3_usdc", "2022-03-17", 10)
        engine = PITEngine()
        engine.run(history)
        stats = engine.filter_stats()
        self.assertEqual(stats["kept_rows"], 10)
        self.assertEqual(stats["dropped_rows"], 0)

    def test_62_mixed_rows_partial_filter(self):
        # 5 days before + 5 days on/after launch of aave_v3_usdc (2022-03-16)
        before = self._make_history("aave_v3_usdc", "2022-03-11", 5)  # Mar 11-15
        after = self._make_history("aave_v3_usdc", "2022-03-16", 5)   # Mar 16-20
        history = before + after
        engine = PITEngine()
        engine.run(history)
        stats = engine.filter_stats()
        self.assertEqual(stats["total_rows"], 10)
        self.assertEqual(stats["kept_rows"], 5)
        self.assertEqual(stats["dropped_rows"], 5)

    def test_63_unknown_protocol_rows_dropped(self):
        history = self._make_history("completely_unknown_xyz", "2024-01-01", 30)
        engine = PITEngine()
        engine.run(history)
        stats = engine.filter_stats()
        self.assertEqual(stats["dropped_rows"], 30)
        self.assertEqual(stats["kept_rows"], 0)

    def test_64_filter_stats_per_protocol_breakdown(self):
        # compound_v2 launched 2018-09-27 → all rows kept
        # morpho_blue launched 2023-11-07 → rows before dropped
        hist_c2 = self._make_history("compound_v2_usdc", "2022-01-01", 10)
        hist_mb = self._make_history("morpho_blue", "2023-01-01", 10)  # all before launch
        engine = PITEngine()
        engine.run(hist_c2 + hist_mb)
        stats = engine.filter_stats()
        self.assertEqual(stats["per_protocol"]["compound_v2_usdc"]["kept"], 10)
        self.assertEqual(stats["per_protocol"]["compound_v2_usdc"]["dropped"], 0)
        self.assertEqual(stats["per_protocol"]["morpho_blue"]["kept"], 0)
        self.assertEqual(stats["per_protocol"]["morpho_blue"]["dropped"], 10)

    def test_65_filter_stats_empty_before_run(self):
        engine = PITEngine()
        stats = engine.filter_stats()
        self.assertEqual(stats, {})

    def test_66_result_has_backtest_result_attributes(self):
        # A short valid history post-launch
        history = self._make_history("compound_v2_usdc", "2022-01-01", 30)
        engine = PITEngine()
        result = engine.run(history)
        self.assertTrue(hasattr(result, "equity_curve"))
        self.assertTrue(hasattr(result, "trades"))
        self.assertTrue(hasattr(result, "metrics"))
        self.assertTrue(hasattr(result, "days"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
