#!/usr/bin/env python3
"""MP-1236 — tests for the enhanced attribution / reporting suite (40+ tests).

NOTE on filename: the requested name ``test_performance_attribution.py`` is
already taken by the MP-585 Brinson ``spa_core.analytics.performance_attribution``
suite (127 tests). This file therefore lives under an MP-1236-scoped name and
targets the NEW reporting modules:

* spa_core.reporting.performance_attributor — protocol/strategy/timing/yield/cash
* spa_core.reporting.tear_sheet_hf          — hedge-fund tear sheet metrics
* spa_core.reporting.benchmark_comparator   — alpha / IR / days-to-significance

Pure stdlib, offline. Each test builds a controlled tmp data dir so results are
deterministic and hand-verifiable; a few smoke tests run against the real
``data/`` track to confirm the modules survive production data.
"""
from __future__ import annotations

import json
import math
import statistics
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from spa_core.reporting import _perf_common as pc
from spa_core.reporting import benchmark_comparator as bc
from spa_core.reporting import performance_attributor as pa
from spa_core.reporting import tear_sheet_hf as ts
from spa_core.paper_trading.risk_metrics import compute_risk_metrics

_REAL_DATA_DIR = str(Path(__file__).parent.parent / "data")


def _write_curve(
    data_dir: Path,
    closes: List[float],
    positions_list: Optional[List[dict]] = None,
    warmup_count: int = 0,
    open_equity: Optional[float] = None,
    apy: Optional[float] = 4.0,
) -> None:
    """Write an equity_curve_daily.json with the given close-equity series."""
    daily = []
    base = open_equity if open_equity is not None else closes[0]
    for i, close in enumerate(closes):
        bar = {
            "date": f"2026-06-{10 + i:02d}",
            "open_equity": base if i == 0 else closes[i - 1],
            "close_equity": close,
            "equity": close,
            "daily_return_pct": 0.0 if i == 0 else (close / closes[i - 1] - 1.0) * 100.0,
            "drawdown_pct": 0.0,
            "is_warmup": i < warmup_count,
        }
        if apy is not None:
            bar["apy_today"] = apy
        if positions_list is not None:
            bar["positions"] = positions_list[i]
        daily.append(bar)
    doc = {"generated_at": "2026-06-20T00:00:00+00:00", "is_demo": False, "daily": daily}
    (data_dir / "equity_curve_daily.json").write_text(json.dumps(doc), encoding="utf-8")


class TestPerfCommon(unittest.TestCase):
    """Shared helpers: loading, rebuild, return math."""

    def test_01_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pc.load_equity_curve(d), [])

    def test_02_load_corrupt_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "equity_curve_daily.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(pc.load_equity_curve(d), [])

    def test_03_real_track_filters_warmup(self):
        bars = [{"is_warmup": True}, {"is_warmup": True}, {"is_warmup": False}]
        self.assertEqual(len(pc.real_track_bars(bars)), 1)

    def test_04_real_track_falls_back_when_all_warmup(self):
        bars = [{"is_warmup": True}, {"is_warmup": True}]
        self.assertEqual(len(pc.real_track_bars(bars)), 2)

    def test_05_rebuild_seed_bar_is_zero(self):
        curve = pc.rebuild_curve([
            {"date": "d1", "open_equity": 100.0, "close_equity": 100.0},
            {"date": "d2", "close_equity": 101.0},
        ])
        self.assertEqual(curve[0]["daily_return_pct"], 0.0)
        self.assertAlmostEqual(curve[1]["daily_return_pct"], 1.0, places=6)

    def test_06_rebuild_empty_input(self):
        self.assertEqual(pc.rebuild_curve([]), [])

    def test_07_rebuild_recomputes_clean_drawdown(self):
        # Monotonic rise → no drawdown, even if source bars claimed otherwise.
        curve = pc.rebuild_curve([
            {"date": "d1", "open_equity": 100.0, "close_equity": 100.0, "drawdown_pct": -5.0},
            {"date": "d2", "close_equity": 101.0, "drawdown_pct": -9.0},
        ])
        self.assertTrue(all(b["drawdown_pct"] == 0.0 for b in curve))

    def test_08_rebuild_real_drawdown(self):
        curve = pc.rebuild_curve([
            {"date": "d1", "open_equity": 100.0, "close_equity": 100.0},
            {"date": "d2", "close_equity": 90.0},
        ])
        self.assertAlmostEqual(curve[1]["drawdown_pct"], -10.0, places=6)

    def test_09_daily_returns_excludes_seed(self):
        curve = pc.rebuild_curve([
            {"date": "d1", "open_equity": 100.0, "close_equity": 100.0},
            {"date": "d2", "close_equity": 101.0},
            {"date": "d3", "close_equity": 102.01},
        ])
        self.assertEqual(len(pc.daily_returns_pct(curve)), 2)

    def test_10_compound_return_pct_known(self):
        # +10% then +10% compounds to +21%.
        self.assertAlmostEqual(pc.compound_return_pct([10.0, 10.0]), 21.0, places=6)

    def test_11_annualize_constant_daily(self):
        # 365 days of exactly 0% → 0% annualized.
        self.assertAlmostEqual(pc.annualize_return_pct([0.0] * 365), 0.0, places=6)

    def test_12_annualize_empty_is_none(self):
        self.assertIsNone(pc.annualize_return_pct([]))

    def test_13_rnd_propagates_none(self):
        self.assertIsNone(pc.rnd(None))
        self.assertEqual(pc.rnd(1.23456, 2), 1.23)


class TestProtocolAttribution(unittest.TestCase):
    """Capital-weighted protocol attribution and its sum invariant."""

    def test_14_single_protocol_gets_all(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0],
                         positions_list=[{"aave": 100.0}, {"aave": 101.0}])
            doc = pa.build_attribution(d)
            pa_block = doc["protocol_attribution"]
            self.assertEqual(len(pa_block["breakdown"]), 1)
            self.assertAlmostEqual(pa_block["breakdown"][0]["share_of_total_pct"], 100.0, places=3)

    def test_15_attribution_sums_to_total(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.5],
                         positions_list=[{"a": 60.0, "b": 40.0},
                                         {"a": 60.0, "b": 41.0},
                                         {"a": 61.0, "b": 41.5}])
            pab = pa.build_attribution(d)["protocol_attribution"]
            self.assertAlmostEqual(pab["sum_of_contributions_pct"],
                                   pab["total_return_pct_additive"], places=6)

    def test_16_attribution_sums_real_data(self):
        pab = pa.build_attribution(_REAL_DATA_DIR)["protocol_attribution"]
        self.assertAlmostEqual(pab["sum_of_contributions_pct"],
                               pab["total_return_pct_additive"], places=6)

    def test_17_fifty_fifty_split_equal_contrib(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 102.0],
                         positions_list=[{"a": 50.0, "b": 50.0}, {"a": 51.0, "b": 51.0}])
            bd = {r["protocol"]: r["contribution_pct"]
                  for r in pa.build_attribution(d)["protocol_attribution"]["breakdown"]}
            self.assertAlmostEqual(bd["a"], bd["b"], places=6)

    def test_18_shares_sum_to_100(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0],
                         positions_list=[{"a": 70.0, "b": 30.0},
                                         {"a": 70.0, "b": 31.0},
                                         {"a": 71.0, "b": 31.0}])
            shares = [r["share_of_total_pct"]
                      for r in pa.build_attribution(d)["protocol_attribution"]["breakdown"]]
            self.assertAlmostEqual(sum(shares), 100.0, places=2)

    def test_19_breakdown_sorted_desc(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0],
                         positions_list=[{"big": 90.0, "small": 10.0},
                                         {"big": 90.9, "small": 10.1}])
            contribs = [r["contribution_pct"]
                        for r in pa.build_attribution(d)["protocol_attribution"]["breakdown"]]
            self.assertEqual(contribs, sorted(contribs, reverse=True))

    def test_20_empty_data_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            doc = pa.build_attribution(d)
            self.assertEqual(doc["protocol_attribution"]["breakdown"], [])
            self.assertTrue(doc["notes"])

    def test_21_avg_weight_reasonable(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0],
                         positions_list=[{"a": 25.0, "b": 75.0}, {"a": 25.0, "b": 76.0}])
            bd = {r["protocol"]: r["avg_weight_pct"]
                  for r in pa.build_attribution(d)["protocol_attribution"]["breakdown"]}
            self.assertGreater(bd["b"], bd["a"])


class TestOtherAttributionComponents(unittest.TestCase):
    """Strategy, timing, yield-vs-benchmark, cash-drag components."""

    def test_22_strategy_attribution_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0])
            sa = pa.build_attribution(d)["strategy_attribution"]
            self.assertFalse(sa["available"])

    def test_23_strategy_attribution_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0])
            (Path(d) / "tournament_results.json").write_text(
                json.dumps({"results": [{"strategy": "S8", "score": 1.2, "sharpe": 2.0, "apy": 27.5}]}),
                encoding="utf-8")
            sa = pa.build_attribution(d)["strategy_attribution"]
            self.assertTrue(sa["available"])
            self.assertEqual(sa["strategies"][0]["strategy"], "S8")

    def test_24_timing_effect_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.5, 104.0])
            te = pa.build_attribution(d)["timing_effect"]
            self.assertTrue(te["available"])
            self.assertIn("timing_effect_pct", te)

    def test_25_timing_constant_returns_zero(self):
        # Perfectly constant daily returns → actual == TWAP → timing ~ 0.
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.01, 103.0301])
            te = pa.build_attribution(d)["timing_effect"]
            self.assertAlmostEqual(te["timing_effect_pct"], 0.0, places=6)

    def test_26_yield_vs_benchmark_excess(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0])
            yb = pa.build_attribution(d)["yield_vs_benchmark"]
            self.assertEqual(yb["benchmark_apy_pct"], pc.TBILL_APY_PCT)
            self.assertAlmostEqual(
                yb["excess_return_pct"],
                yb["spa_annualized_return_pct"] - pc.TBILL_APY_PCT, places=4)

    def test_27_cash_drag_formula(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0], apy=4.0)
            cd = pa.build_attribution(d)["cash_drag"]
            # 5% buffer * 4.0% deployed APY = 0.20 pct points.
            self.assertAlmostEqual(cd["annual_cash_drag_pct"], 0.20, places=4)

    def test_28_cash_drag_no_apy(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0], apy=None)
            cd = pa.build_attribution(d)["cash_drag"]
            self.assertFalse(cd["available"])

    def test_29_idempotent_write(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0],
                         positions_list=[{"a": 100.0}, {"a": 101.0}])
            doc = pa.build_attribution(d)
            first = pa.write_attribution(doc, d)
            self.assertTrue(first["changed"])
            second = pa.write_attribution(pa.build_attribution(d), d)
            self.assertFalse(second["changed"])  # content unchanged → no rewrite


class TestTearSheet(unittest.TestCase):
    """Hedge-fund tear sheet metrics, including known-result verification."""

    def test_30_sharpe_matches_formula(self):
        # Verify the tear sheet's Sharpe equals the explicit annualised formula.
        closes = [100.0, 101.0, 100.5, 102.0, 101.8, 103.0]
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), closes)
            doc = ts.build_tear_sheet(d)
            curve = pc.rebuild_curve(pc.real_track_bars(pc.load_equity_curve(d)))
            returns = pc.daily_returns_pct(curve)
            ann_ret = pc.annualize_return_pct(returns)
            ann_vol = statistics.pstdev(returns) * math.sqrt(pc.ANNUALIZATION_DAYS)
            expected = (ann_ret - pc.RISK_FREE_ANNUAL_PCT) / ann_vol
            self.assertAlmostEqual(doc["ratios"]["sharpe_ratio"], expected, places=3)

    def test_31_sharpe_matches_risk_metrics(self):
        closes = [100.0, 101.0, 100.5, 102.0, 101.8, 103.0]
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), closes)
            curve = pc.rebuild_curve(pc.real_track_bars(pc.load_equity_curve(d)))
            rm = compute_risk_metrics(curve, risk_free_annual_pct=pc.RISK_FREE_ANNUAL_PCT)
            doc = ts.build_tear_sheet(d)
            self.assertEqual(doc["ratios"]["sharpe_ratio"], rm["sharpe_ratio"])

    def test_32_zero_vol_sharpe_none(self):
        # Constant returns → zero volatility → Sharpe undefined (None), no crash.
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.01, 103.0301])
            doc = ts.build_tear_sheet(d)
            self.assertIsNone(doc["ratios"]["sharpe_ratio"])

    def test_33_calmar_zero_drawdown(self):
        # Monotonic rise → max drawdown 0 → Calmar undefined (None), not a crash.
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0, 103.0])
            doc = ts.build_tear_sheet(d)
            self.assertEqual(doc["drawdown"]["max_drawdown_pct"], 0.0)
            self.assertIsNone(doc["ratios"]["calmar_ratio"])

    def test_34_calmar_with_drawdown(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 110.0, 99.0, 105.0])
            doc = ts.build_tear_sheet(d)
            self.assertLess(doc["drawdown"]["max_drawdown_pct"], 0.0)
            self.assertIsNotNone(doc["ratios"]["calmar_ratio"])

    def test_35_win_rate_all_positive(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0, 103.0])
            self.assertEqual(ts.build_tear_sheet(d)["returns"]["win_rate_pct"], 100.0)

    def test_36_drawdown_episode_count(self):
        # One dip then recovery → exactly one underwater episode.
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 110.0, 105.0, 108.0, 120.0])
            dd = ts.build_tear_sheet(d)["drawdown"]
            self.assertEqual(dd["num_episodes"], 1)
            self.assertGreaterEqual(dd["avg_drawdown_duration_days"], 1.0)

    def test_37_max_drawdown_usd(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 110.0, 99.0])  # peak 110 → 99 = -$11
            self.assertAlmostEqual(ts.build_tear_sheet(d)["drawdown"]["max_drawdown_usd"],
                                   -11.0, places=2)

    def test_38_rolling_sharpe_short_track_empty(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0])
            rs = ts.build_tear_sheet(d)["rolling_sharpe_30d"]
            self.assertEqual(rs["series"], [])
            self.assertIn("< 30", rs["note"])

    def test_39_rolling_sharpe_long_track(self):
        closes = [100.0 * (1.001 ** i) for i in range(40)]  # 40 days, varies slightly
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), closes)
            rs = ts.build_tear_sheet(d)["rolling_sharpe_30d"]
            # 40 bars → 39 returns → 39 - 30 + 1 = 10 windows.
            self.assertEqual(len(rs["series"]), 10)

    def test_40_monthly_table(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0])
            months = ts.build_tear_sheet(d)["monthly_returns"]
            self.assertEqual(months[0]["month"], "2026-06")

    def test_41_tear_sheet_real_data_smoke(self):
        doc = ts.build_tear_sheet(_REAL_DATA_DIR)
        self.assertEqual(doc["meta"]["module"], "tear_sheet_hf")
        self.assertIn("sharpe_ratio", doc["ratios"])


class TestBenchmarkComparator(unittest.TestCase):
    """Alpha, information ratio, days-to-significance."""

    def test_42_alpha_is_spa_minus_benchmark(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0])
            doc = bc.build_comparison(d)
            spa = doc["spa_annualized_return_pct"]
            tbill = next(c for c in doc["comparisons"] if c["benchmark"] == "US T-Bills")
            self.assertAlmostEqual(tbill["alpha_pct"], spa - pc.TBILL_APY_PCT, places=4)

    def test_43_all_benchmarks_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0])
            names = {c["benchmark"] for c in bc.build_comparison(d)["comparisons"]}
            self.assertEqual(
                names, {"US T-Bills", "ETH staking (stETH)", "AAVE conservative", "SPA target"})

    def test_44_spa_target_alpha_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0])
            self_cmp = next(c for c in bc.build_comparison(d)["comparisons"]
                            if c["benchmark"] == "SPA target")
            self.assertAlmostEqual(self_cmp["alpha_pct"], 0.0, places=2)

    def test_45_alpha_values_valid_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0, 103.0])
            for c in bc.build_comparison(d)["comparisons"]:
                self.assertIsInstance(c["alpha_pct"], float)
                self.assertTrue(math.isfinite(c["alpha_pct"]))

    def test_46_days_to_significance_formula(self):
        # Build a track that beats stETH; verify the N = (z·s/m)^2 projection.
        closes = [100.0, 101.0, 100.8, 102.0, 101.5, 103.0, 102.5, 104.0]
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), closes)
            doc = bc.build_comparison(d)
            curve = pc.rebuild_curve(pc.real_track_bars(pc.load_equity_curve(d)))
            spa_returns = pc.daily_returns_pct(curve)
            bench_daily = pc.STETH_APY_PCT / pc.ANNUALIZATION_DAYS
            excess = [r - bench_daily for r in spa_returns]
            m, s = statistics.fmean(excess), statistics.pstdev(excess)
            cmp = next(c for c in doc["comparisons"] if c["benchmark"] == "ETH staking (stETH)")
            if m > 0 and s > 0:
                expected = int(math.ceil((bc.Z_95_ONE_SIDED * s / m) ** 2))
                self.assertEqual(cmp["days_to_95_significance"], expected)

    def test_47_underperform_no_significance(self):
        # Tiny positive yield, far below the 5% T-Bill → never beats it.
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0 + 0.001 * i for i in range(6)])
            tbill = next(c for c in bc.build_comparison(d)["comparisons"]
                         if c["benchmark"] == "US T-Bills")
            self.assertLess(tbill["alpha_pct"], 0.0)
            self.assertIsNone(tbill["days_to_95_significance"])
            self.assertFalse(tbill["significant_at_95_now"])

    def test_48_information_ratio_present_when_variance(self):
        closes = [100.0, 101.0, 100.5, 102.0, 101.0, 103.0]
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), closes)
            cmp = next(c for c in bc.build_comparison(d)["comparisons"]
                       if c["benchmark"] == "ETH staking (stETH)")
            self.assertIsNotNone(cmp["information_ratio"])

    def test_49_empty_data_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            doc = bc.build_comparison(d)
            self.assertEqual(len(doc["comparisons"]), 4)
            self.assertTrue(doc["notes"])

    def test_50_benchmark_real_data_smoke(self):
        doc = bc.build_comparison(_REAL_DATA_DIR)
        self.assertIsNotNone(doc["spa_annualized_return_pct"])
        self.assertEqual(len(doc["comparisons"]), 4)


class TestCLIs(unittest.TestCase):
    """CLI entry points exit 0 even on junk args (advisory contract)."""

    def test_51_attributor_junk_args_exit0(self):
        self.assertEqual(pa.main(["--nonsense"]), 0)

    def test_52_tear_sheet_check_exit0(self):
        self.assertEqual(ts.main(["--check", "--data-dir", _REAL_DATA_DIR]), 0)

    def test_53_benchmark_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            _write_curve(Path(d), [100.0, 101.0, 102.0])
            self.assertEqual(bc.main(["--run", "--data-dir", d]), 0)
            self.assertTrue((Path(d) / "benchmark_comparison.json").exists())


if __name__ == "__main__":
    unittest.main()
