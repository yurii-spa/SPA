"""Unit tests for spa_core.analytics.yield_aggregator_comparator (MP-825).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_yield_aggregator_comparator -v
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so imports work from any cwd
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import spa_core.analytics.yield_aggregator_comparator as yac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agg(name="Yearn", underlying_apy=10.0, performance_fee_pct=20.0,
         management_fee_pct=2.0, gas_optimization_bonus=0.5,
         auto_compound_bonus=1.0, tvl_usd=5_000_000, strategy_count=10,
         audit_count=3):
    return {
        "name": name,
        "underlying_apy": underlying_apy,
        "performance_fee_pct": performance_fee_pct,
        "management_fee_pct": management_fee_pct,
        "gas_optimization_bonus": gas_optimization_bonus,
        "auto_compound_bonus": auto_compound_bonus,
        "tvl_usd": tvl_usd,
        "strategy_count": strategy_count,
        "audit_count": audit_count,
    }


class _TempDataMixin:
    """Redirects DATA_FILE to a temp directory for each test."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_data_file = yac.DATA_FILE
        yac.DATA_FILE = Path(self._tmpdir) / "aggregator_comparison_log.json"

    def tearDown(self):
        yac.DATA_FILE = self._orig_data_file
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# 1. Return-value shape
# ===========================================================================
class TestReturnShape(_TempDataMixin, unittest.TestCase):

    def _result(self):
        return yac.analyze("USDC", [_agg()])

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_has_asset_key(self):
        self.assertIn("asset", self._result())

    def test_has_aggregators_key(self):
        self.assertIn("aggregators", self._result())

    def test_has_filtered_out_key(self):
        self.assertIn("filtered_out", self._result())

    def test_has_winner_key(self):
        self.assertIn("winner", self._result())

    def test_has_highest_net_apy_key(self):
        self.assertIn("highest_net_apy", self._result())

    def test_has_most_trusted_key(self):
        self.assertIn("most_trusted", self._result())

    def test_has_market_avg_net_apy_key(self):
        self.assertIn("market_avg_net_apy", self._result())

    def test_has_timestamp_key(self):
        self.assertIn("timestamp", self._result())

    def test_timestamp_is_float(self):
        self.assertIsInstance(self._result()["timestamp"], float)

    def test_timestamp_is_recent(self):
        self.assertAlmostEqual(self._result()["timestamp"], time.time(), delta=5)

    def test_asset_preserved(self):
        r = yac.analyze("WETH", [_agg(tvl_usd=5_000_000)])
        self.assertEqual(r["asset"], "WETH")

    def test_aggregators_is_list(self):
        self.assertIsInstance(self._result()["aggregators"], list)

    def test_filtered_out_is_list(self):
        self.assertIsInstance(self._result()["filtered_out"], list)

    def test_aggregator_entry_has_rank(self):
        r = self._result()
        self.assertIn("rank", r["aggregators"][0])

    def test_aggregator_entry_has_net_apy(self):
        self.assertIn("net_apy", self._result()["aggregators"][0])

    def test_aggregator_entry_has_gross_apy(self):
        self.assertIn("gross_apy", self._result()["aggregators"][0])

    def test_aggregator_entry_has_fee_drag_pct(self):
        self.assertIn("fee_drag_pct", self._result()["aggregators"][0])

    def test_aggregator_entry_has_fee_efficiency(self):
        self.assertIn("fee_efficiency", self._result()["aggregators"][0])

    def test_aggregator_entry_has_trust_score(self):
        self.assertIn("trust_score", self._result()["aggregators"][0])

    def test_aggregator_entry_has_composite_score(self):
        self.assertIn("composite_score", self._result()["aggregators"][0])


# ===========================================================================
# 2. Gross APY calculation
# ===========================================================================
class TestGrossApy(_TempDataMixin, unittest.TestCase):

    def test_gross_apy_sums_all_bonuses(self):
        a = _agg(underlying_apy=10.0, gas_optimization_bonus=0.5,
                 auto_compound_bonus=1.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, tvl_usd=5_000_000)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["gross_apy"], 11.5, places=6)

    def test_gross_apy_no_bonuses(self):
        a = _agg(underlying_apy=8.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["gross_apy"], 8.0, places=6)

    def test_gross_apy_zero_underlying_with_bonuses(self):
        a = _agg(underlying_apy=0.0, gas_optimization_bonus=2.0,
                 auto_compound_bonus=1.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["gross_apy"], 3.0, places=6)


# ===========================================================================
# 3. Fee-drag calculation
# ===========================================================================
class TestFeeDrag(_TempDataMixin, unittest.TestCase):

    def test_fee_drag_formula(self):
        # fee_drag = (underlying * perf_fee/100) + mgmt_fee
        # = (10 * 20/100) + 2 = 4
        a = _agg(underlying_apy=10.0, performance_fee_pct=20.0,
                 management_fee_pct=2.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["fee_drag_pct"], 4.0, places=6)

    def test_fee_drag_zero_perf_fee(self):
        a = _agg(underlying_apy=10.0, performance_fee_pct=0.0,
                 management_fee_pct=1.5, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["fee_drag_pct"], 1.5, places=6)

    def test_fee_drag_zero_mgmt_fee(self):
        a = _agg(underlying_apy=10.0, performance_fee_pct=10.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["fee_drag_pct"], 1.0, places=6)

    def test_fee_drag_zero_fees(self):
        a = _agg(underlying_apy=10.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["fee_drag_pct"], 0.0, places=6)


# ===========================================================================
# 4. Net APY calculation
# ===========================================================================
class TestNetApy(_TempDataMixin, unittest.TestCase):

    def test_net_apy_gross_minus_drag(self):
        # gross = 10 + 0.5 + 1 = 11.5; drag = (10*20/100)+2 = 4; net = 7.5
        a = _agg(underlying_apy=10.0, performance_fee_pct=20.0,
                 management_fee_pct=2.0, gas_optimization_bonus=0.5,
                 auto_compound_bonus=1.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["net_apy"], 7.5, places=6)

    def test_net_apy_no_fees(self):
        a = _agg(underlying_apy=8.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=1.0,
                 auto_compound_bonus=0.5)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["net_apy"], 9.5, places=6)

    def test_net_apy_can_be_negative(self):
        a = _agg(underlying_apy=1.0, performance_fee_pct=0.0,
                 management_fee_pct=3.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertLess(r["aggregators"][0]["net_apy"], 0)


# ===========================================================================
# 5. Fee efficiency
# ===========================================================================
class TestFeeEfficiency(_TempDataMixin, unittest.TestCase):

    def test_fee_efficiency_formula(self):
        # gross=11.5, net=7.5, efficiency=7.5/11.5*100≈65.22
        a = _agg(underlying_apy=10.0, performance_fee_pct=20.0,
                 management_fee_pct=2.0, gas_optimization_bonus=0.5,
                 auto_compound_bonus=1.0)
        r = yac.analyze("X", [a])
        expected = 7.5 / 11.5 * 100
        self.assertAlmostEqual(r["aggregators"][0]["fee_efficiency"], expected, places=4)

    def test_fee_efficiency_zero_fees(self):
        a = _agg(underlying_apy=8.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["fee_efficiency"], 100.0, places=4)

    def test_fee_efficiency_zero_gross_apy_returns_zero(self):
        a = _agg(underlying_apy=0.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertEqual(r["aggregators"][0]["fee_efficiency"], 0.0)


# ===========================================================================
# 6. Trust score
# ===========================================================================
class TestTrustScore(_TempDataMixin, unittest.TestCase):

    def _ts(self, audit_count, strategy_count, tvl_usd):
        a = _agg(audit_count=audit_count, strategy_count=strategy_count,
                 tvl_usd=tvl_usd, performance_fee_pct=0.0, management_fee_pct=0.0)
        r = yac.analyze("X", [a])
        return r["aggregators"][0]["trust_score"]

    def test_trust_score_is_int(self):
        self.assertIsInstance(self._ts(2, 5, 5_000_000), int)

    def test_trust_score_capped_at_100(self):
        self.assertLessEqual(self._ts(10, 100, 1_000_000_000), 100)

    def test_trust_score_min_is_nonneg(self):
        self.assertGreaterEqual(self._ts(0, 0, 1_000_000), 0)

    def test_trust_score_audit_contribution(self):
        ts0 = self._ts(0, 0, 1_000_000)
        ts1 = self._ts(1, 0, 1_000_000)
        self.assertEqual(ts1 - ts0, 15)

    def test_trust_score_strategy_contribution_capped_at_25(self):
        ts4 = self._ts(0, 4, 1_000_000)
        ts5 = self._ts(0, 5, 1_000_000)
        ts6 = self._ts(0, 6, 1_000_000)
        ts100 = self._ts(0, 100, 1_000_000)
        # strategy_count=4 → 20; strategy_count=5 → 25 (cap); 6 and 100 also cap at 25
        self.assertGreater(ts5, ts4)    # 4*5=20 < 5*5=25
        self.assertEqual(ts6, ts5)      # both hit the 25-cap
        self.assertEqual(ts100, ts5)    # same cap

    def test_trust_score_tvl_log_component(self):
        # tvl=1M+0 → log10(1+1)*20≈6.02, int=6
        # tvl=10M → log10(10+1)*20≈20.83, int=20
        ts_1m = self._ts(0, 0, 1_000_000)
        ts_10m = self._ts(0, 0, 10_000_000)
        self.assertGreater(ts_10m, ts_1m)

    def test_trust_score_tvl_log_component_capped_at_30(self):
        ts_huge = self._ts(0, 0, 10_000_000_000)
        ts_1b = self._ts(0, 0, 1_000_000_000)
        # both should max out at 30 for the log component; trust_score equal
        self.assertEqual(ts_huge, ts_1b)

    def test_trust_score_formula_manual(self):
        # audit=2, strategy=5, tvl=5M
        # log10(5+1)*20 = log10(6)*20 ≈ 15.56, int=15
        # 2*15 + min(5*5,25) + 15 = 30 + 25 + 15 = 70
        expected = 2 * 15 + min(5 * 5, 25) + int(min(math.log10(5.0 + 1) * 20, 30))
        self.assertEqual(self._ts(2, 5, 5_000_000), expected)


# ===========================================================================
# 7. Composite score and ranking
# ===========================================================================
class TestCompositeAndRank(_TempDataMixin, unittest.TestCase):

    def test_composite_score_formula(self):
        a = _agg(underlying_apy=10.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0, audit_count=0, strategy_count=0,
                 tvl_usd=1_000_000)
        r = yac.analyze("X", [a])
        entry = r["aggregators"][0]
        expected_composite = entry["net_apy"] * (entry["trust_score"] / 100.0)
        self.assertAlmostEqual(entry["composite_score"], expected_composite, places=8)

    def test_single_agg_rank_is_1(self):
        r = yac.analyze("X", [_agg()])
        self.assertEqual(r["aggregators"][0]["rank"], 1)

    def test_rank_ordered_by_composite_score_desc(self):
        a1 = _agg(name="A", underlying_apy=5.0, audit_count=1, tvl_usd=5_000_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0, strategy_count=1)
        a2 = _agg(name="B", underlying_apy=20.0, audit_count=3, tvl_usd=10_000_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0, strategy_count=5)
        r = yac.analyze("X", [a1, a2])
        ranks = {e["name"]: e["rank"] for e in r["aggregators"]}
        self.assertLess(ranks["B"], ranks["A"])  # B has higher composite_score

    def test_ranks_are_sequential(self):
        aggs = [_agg(name=f"A{i}", underlying_apy=float(i),
                     performance_fee_pct=0.0, management_fee_pct=0.0,
                     gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
                for i in range(1, 5)]
        r = yac.analyze("X", aggs)
        ranks = sorted(e["rank"] for e in r["aggregators"])
        self.assertEqual(ranks, list(range(1, 5)))

    def test_rank_1_has_highest_composite(self):
        aggs = [_agg(name=f"A{i}", underlying_apy=float(i) * 3,
                     performance_fee_pct=0.0, management_fee_pct=0.0,
                     gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
                for i in range(1, 4)]
        r = yac.analyze("X", aggs)
        composites = [(e["rank"], e["composite_score"]) for e in r["aggregators"]]
        rank1 = max(composites, key=lambda x: x[1])[0]
        self.assertEqual(rank1, 1)


# ===========================================================================
# 8. Winner / highlights
# ===========================================================================
class TestWinnerHighlights(_TempDataMixin, unittest.TestCase):

    def test_winner_is_highest_composite(self):
        a1 = _agg(name="Low", underlying_apy=3.0, performance_fee_pct=0.0,
                  management_fee_pct=0.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0, audit_count=1, tvl_usd=2_000_000)
        a2 = _agg(name="High", underlying_apy=20.0, performance_fee_pct=0.0,
                  management_fee_pct=0.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0, audit_count=3, tvl_usd=10_000_000)
        r = yac.analyze("X", [a1, a2])
        self.assertEqual(r["winner"], "High")

    def test_highest_net_apy_name(self):
        a1 = _agg(name="LowFee", underlying_apy=8.0, performance_fee_pct=0.0,
                  management_fee_pct=0.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0)
        a2 = _agg(name="HighFee", underlying_apy=12.0, performance_fee_pct=50.0,
                  management_fee_pct=3.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0)
        r = yac.analyze("X", [a1, a2])
        # net_apy: LowFee=8.0, HighFee=12-6-3=3.0 → LowFee wins net_apy
        self.assertEqual(r["highest_net_apy"], "LowFee")

    def test_most_trusted_name(self):
        a1 = _agg(name="LowTrust", underlying_apy=5.0, audit_count=0,
                  strategy_count=0, tvl_usd=1_100_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
        a2 = _agg(name="HighTrust", underlying_apy=2.0, audit_count=5,
                  strategy_count=10, tvl_usd=100_000_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
        r = yac.analyze("X", [a1, a2])
        self.assertEqual(r["most_trusted"], "HighTrust")

    def test_market_avg_net_apy_single(self):
        a = _agg(underlying_apy=10.0, performance_fee_pct=0.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["market_avg_net_apy"], 10.0, places=4)

    def test_market_avg_net_apy_multiple(self):
        a1 = _agg(name="A", underlying_apy=10.0, performance_fee_pct=0.0,
                  management_fee_pct=0.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0)
        a2 = _agg(name="B", underlying_apy=6.0, performance_fee_pct=0.0,
                  management_fee_pct=0.0, gas_optimization_bonus=0.0,
                  auto_compound_bonus=0.0)
        r = yac.analyze("X", [a1, a2])
        self.assertAlmostEqual(r["market_avg_net_apy"], 8.0, places=4)


# ===========================================================================
# 9. TVL filter
# ===========================================================================
class TestTvlFilter(_TempDataMixin, unittest.TestCase):

    def test_agg_below_default_min_tvl_filtered(self):
        a = _agg(tvl_usd=500_000)  # below 1_000_000
        r = yac.analyze("X", [a])
        self.assertEqual(r["aggregators"], [])
        self.assertIn("Yearn", r["filtered_out"])

    def test_agg_at_exactly_min_tvl_passes(self):
        a = _agg(tvl_usd=1_000_000)
        r = yac.analyze("X", [a])
        self.assertEqual(len(r["aggregators"]), 1)
        self.assertEqual(r["filtered_out"], [])

    def test_all_filtered_out_winner_none(self):
        a = _agg(tvl_usd=100_000)
        r = yac.analyze("X", [a])
        self.assertIsNone(r["winner"])

    def test_all_filtered_out_highest_net_apy_none(self):
        a = _agg(tvl_usd=100_000)
        r = yac.analyze("X", [a])
        self.assertIsNone(r["highest_net_apy"])

    def test_all_filtered_out_most_trusted_none(self):
        a = _agg(tvl_usd=100_000)
        r = yac.analyze("X", [a])
        self.assertIsNone(r["most_trusted"])

    def test_all_filtered_out_market_avg_zero(self):
        a = _agg(tvl_usd=100_000)
        r = yac.analyze("X", [a])
        self.assertEqual(r["market_avg_net_apy"], 0.0)

    def test_all_filtered_out_aggregators_empty(self):
        a = _agg(tvl_usd=100_000)
        r = yac.analyze("X", [a])
        self.assertEqual(r["aggregators"], [])

    def test_custom_min_tvl_filters_correctly(self):
        low = _agg(name="Low", tvl_usd=2_000_000)
        high = _agg(name="High", tvl_usd=5_000_000)
        r = yac.analyze("X", [low, high], config={"min_tvl_usd": 3_000_000})
        names = [e["name"] for e in r["aggregators"]]
        self.assertIn("High", names)
        self.assertNotIn("Low", names)
        self.assertIn("Low", r["filtered_out"])

    def test_empty_aggregators_list(self):
        r = yac.analyze("X", [])
        self.assertEqual(r["aggregators"], [])
        self.assertIsNone(r["winner"])

    def test_some_pass_some_filtered(self):
        a1 = _agg(name="Pass", tvl_usd=2_000_000)
        a2 = _agg(name="Fail", tvl_usd=500_000)
        r = yac.analyze("X", [a1, a2])
        self.assertEqual(len(r["aggregators"]), 1)
        self.assertEqual(len(r["filtered_out"]), 1)
        self.assertEqual(r["filtered_out"][0], "Fail")

    def test_config_none_uses_default(self):
        a = _agg(tvl_usd=500_000)
        r = yac.analyze("X", [a], config=None)
        self.assertEqual(r["aggregators"], [])

    def test_config_empty_dict_uses_default(self):
        a = _agg(tvl_usd=500_000)
        r = yac.analyze("X", [a], config={})
        self.assertEqual(r["aggregators"], [])


# ===========================================================================
# 10. Ring-buffer / persistence
# ===========================================================================
class TestRingBuffer(_TempDataMixin, unittest.TestCase):

    def test_log_file_created_after_analyze(self):
        yac.analyze("X", [_agg()])
        self.assertTrue(yac.DATA_FILE.exists())

    def test_log_file_is_valid_json(self):
        yac.analyze("X", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entry(self):
        yac.analyze("X", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_grows_with_multiple_calls(self):
        yac.analyze("X", [_agg()])
        yac.analyze("Y", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_caps_at_100(self):
        for i in range(105):
            yac.analyze(f"A{i}", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(105):
            yac.analyze(f"ASSET_{i}", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        # Last entry should be ASSET_104
        self.assertEqual(data[-1]["asset"], "ASSET_104")

    def test_atomic_write_no_tmp_left(self):
        yac.analyze("X", [_agg()])
        tmp = yac.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_log_entry_contains_asset(self):
        yac.analyze("MYASSET", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(data[0]["asset"], "MYASSET")

    def test_log_entry_contains_timestamp(self):
        yac.analyze("X", [_agg()])
        with open(yac.DATA_FILE) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_data_dir_created_if_missing(self):
        import shutil
        shutil.rmtree(yac.DATA_FILE.parent, ignore_errors=True)
        yac.analyze("X", [_agg()])
        self.assertTrue(yac.DATA_FILE.exists())


# ===========================================================================
# 11. Edge cases
# ===========================================================================
class TestEdgeCases(_TempDataMixin, unittest.TestCase):

    def test_five_aggregators_all_ranked(self):
        aggs = [_agg(name=f"P{i}", underlying_apy=float(i) + 1,
                     performance_fee_pct=0.0, management_fee_pct=0.0,
                     gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
                for i in range(5)]
        r = yac.analyze("X", aggs)
        self.assertEqual(len(r["aggregators"]), 5)

    def test_high_perf_fee_lowers_net_apy(self):
        a_hf = _agg(name="HighFee", underlying_apy=10.0, performance_fee_pct=50.0,
                    management_fee_pct=0.0, gas_optimization_bonus=0.0,
                    auto_compound_bonus=0.0)
        a_lf = _agg(name="LowFee", underlying_apy=10.0, performance_fee_pct=5.0,
                    management_fee_pct=0.0, gas_optimization_bonus=0.0,
                    auto_compound_bonus=0.0)
        r = yac.analyze("X", [a_hf, a_lf])
        by_name = {e["name"]: e for e in r["aggregators"]}
        self.assertGreater(by_name["LowFee"]["net_apy"], by_name["HighFee"]["net_apy"])

    def test_trust_score_never_exceeds_100(self):
        a = _agg(audit_count=10, strategy_count=100, tvl_usd=10_000_000_000)
        r = yac.analyze("X", [a])
        self.assertLessEqual(r["aggregators"][0]["trust_score"], 100)

    def test_trust_score_never_negative(self):
        a = _agg(audit_count=0, strategy_count=0, tvl_usd=1_000_001)
        r = yac.analyze("X", [a])
        self.assertGreaterEqual(r["aggregators"][0]["trust_score"], 0)

    def test_aggregate_name_preserved(self):
        a = _agg(name="MySpecialAgg")
        r = yac.analyze("X", [a])
        self.assertEqual(r["aggregators"][0]["name"], "MySpecialAgg")

    def test_composite_score_of_rank_1_gte_rank_2(self):
        aggs = [_agg(name=f"A{i}", underlying_apy=float(i + 1),
                     performance_fee_pct=0.0, management_fee_pct=0.0,
                     gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
                for i in range(3)]
        r = yac.analyze("X", aggs)
        by_rank = {e["rank"]: e for e in r["aggregators"]}
        self.assertGreaterEqual(by_rank[1]["composite_score"],
                                by_rank[2]["composite_score"])

    def test_winner_is_none_empty_list(self):
        r = yac.analyze("X", [])
        self.assertIsNone(r["winner"])

    def test_filtered_out_preserves_all_below_tvl(self):
        aggs = [_agg(name=f"S{i}", tvl_usd=100_000) for i in range(4)]
        r = yac.analyze("X", aggs)
        self.assertEqual(len(r["filtered_out"]), 4)

    def test_trust_score_max_strategy_component_is_25(self):
        # strategy_count=5 → 25, strategy_count=6 → still 25
        a5 = _agg(name="A", strategy_count=5, audit_count=0, tvl_usd=1_000_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
        a6 = _agg(name="B", strategy_count=6, audit_count=0, tvl_usd=1_000_000,
                  performance_fee_pct=0.0, management_fee_pct=0.0,
                  gas_optimization_bonus=0.0, auto_compound_bonus=0.0)
        r5 = yac.analyze("X", [a5])
        r6 = yac.analyze("X", [a6])
        self.assertEqual(r5["aggregators"][0]["trust_score"],
                         r6["aggregators"][0]["trust_score"])

    def test_net_apy_zero_when_fee_equals_gross(self):
        # underlying=10, perf_fee=100%, mgmt_fee=0 → drag=10, gross=10, net=0
        a = _agg(underlying_apy=10.0, performance_fee_pct=100.0,
                 management_fee_pct=0.0, gas_optimization_bonus=0.0,
                 auto_compound_bonus=0.0)
        r = yac.analyze("X", [a])
        self.assertAlmostEqual(r["aggregators"][0]["net_apy"], 0.0, places=6)

    def test_result_agg_list_not_includes_filtered(self):
        p = _agg(name="Pass", tvl_usd=5_000_000)
        f = _agg(name="Fail", tvl_usd=500)
        r = yac.analyze("X", [p, f])
        names = [e["name"] for e in r["aggregators"]]
        self.assertNotIn("Fail", names)


# ===========================================================================
# 12. Module constants
# ===========================================================================
class TestConstants(_TempDataMixin, unittest.TestCase):

    def test_default_min_tvl_is_1m(self):
        self.assertEqual(yac.DEFAULT_MIN_TVL_USD, 1_000_000.0)

    def test_max_entries_is_100(self):
        self.assertEqual(yac.MAX_ENTRIES, 100)

    def test_data_file_path_contains_aggregator(self):
        self.assertIn("aggregator", str(yac.DATA_FILE))


if __name__ == "__main__":
    unittest.main()
