#!/usr/bin/env python3
"""Tests for the CAPM Risk-Decomposition Analyzer (SPA-V465 / MP-150).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math (period_returns / flat_daily_return /
covariance / ols_capm), the full metric battery on a varying benchmark
(Jensen's alpha, Treynor, Modigliani M2, appraisal ratio, systematic/specific
variance decomposition), the flat-default-benchmark degeneracy, verdict bands
at the documented thresholds, the low-sample guard, insufficient-data +
never-raise / fuzz tolerance, reuse-by-import (content_fingerprint + equity
helper), atomic write_status idempotency / rotation, CLI behaviour (direct +
subprocess), and import hygiene.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from spa_core.paper_trading import capm_decomposition as capm_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(capm_mod.__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dates(n):
    """n consecutive ISO dates starting 2026-01-01 (28-day month wrap)."""
    out = []
    for i in range(n):
        day = 1 + i
        month = 1 + (day - 1) // 28
        d = 1 + (day - 1) % 28
        out.append(f"2026-{month:02d}-{d:02d}")
    return out


def _equity_from_returns(returns, start=100.0):
    """Equity levels reconstructing the given simple period returns."""
    levels = [start]
    for r in returns:
        levels.append(levels[-1] * (1.0 + r))
    return levels


def _equity_doc(levels, dates=None, is_demo=None):
    """Build an equity_curve_daily.json-shaped dict from equity levels."""
    if dates is None:
        dates = _dates(len(levels))
    daily = [
        {"date": dates[i], "close_equity": float(levels[i])}
        for i in range(len(levels))
    ]
    doc = {"source": "test", "daily": daily}
    if is_demo is not None:
        doc["is_demo"] = is_demo
    return doc


def _write_equity(data_dir, doc):
    (Path(data_dir) / capm_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _build_from_returns(data_dir, returns, benchmark_returns=None, **kw):
    levels = _equity_from_returns(returns)
    _write_equity(data_dir, _equity_doc(levels, **kw))
    return capm_mod.build_capm_decomposition(
        data_dir, benchmark_returns=benchmark_returns
    )


def _varying_bench(n, seed=7, scale=0.01):
    """A reproducible varying benchmark series of n daily returns."""
    rnd = random.Random(seed)
    return [rnd.uniform(-scale, scale) for _ in range(n)]


def _linear_portfolio(rm, beta, alpha):
    """Portfolio returns that sit EXACTLY on rp = alpha + beta*rm (zero
    residual w.r.t. the simple line through the benchmark; with rf=0 this is
    also the CAPM line, so OLS recovers beta and alpha exactly)."""
    return [alpha + beta * m for m in rm]


# A canonical varying-benchmark scenario reused across tests. The portfolio is
# an exact linear function of the benchmark (rp = alpha + beta*rm), so with
# rf=0 OLS recovers beta/alpha exactly and the residuals are ~0.
_N = 60
_BENCH = _varying_bench(_N, seed=11, scale=0.02)
_BETA = 1.25
_ALPHA = 0.0005
_PORT = _linear_portfolio(_BENCH, _BETA, _ALPHA)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: period_returns
# ─────────────────────────────────────────────────────────────────────────────

class TestPeriodReturns(unittest.TestCase):
    def test_hand_example(self):
        series = [("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]
        r = capm_mod.period_returns(series)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        self.assertAlmostEqual(r[1], -0.10, places=12)

    def test_len_is_n_minus_1(self):
        series = [(f"d{i}", 100.0 + i) for i in range(10)]
        self.assertEqual(len(capm_mod.period_returns(series)), 9)

    def test_empty_and_single(self):
        self.assertEqual(capm_mod.period_returns([]), [])
        self.assertEqual(capm_mod.period_returns([("d0", 100.0)]), [])

    def test_skips_nonpositive_prev(self):
        series = [("d0", 0.0), ("d1", 100.0), ("d2", 110.0)]
        r = capm_mod.period_returns(series)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        for v in r:
            self.assertTrue(math.isfinite(v))

    def test_no_inf_or_nan(self):
        series = [("d0", 100.0), ("d1", 50.0), ("d2", 75.0), ("d3", 75.0)]
        for v in capm_mod.period_returns(series):
            self.assertTrue(math.isfinite(v))


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: flat_daily_return
# ─────────────────────────────────────────────────────────────────────────────

class TestFlatDailyReturn(unittest.TestCase):
    def test_hand_example(self):
        # (1.04) ** (1/365) - 1
        self.assertAlmostEqual(
            capm_mod.flat_daily_return(4.0, 365),
            (1.04) ** (1.0 / 365) - 1.0, places=15,
        )

    def test_zero_rate(self):
        self.assertEqual(capm_mod.flat_daily_return(0.0, 365), 0.0)

    def test_nonpositive_periods(self):
        self.assertEqual(capm_mod.flat_daily_return(4.0, 0), 0.0)
        self.assertEqual(capm_mod.flat_daily_return(4.0, -5), 0.0)

    def test_compounds_back_to_annual(self):
        d = capm_mod.flat_daily_return(4.0, 365)
        self.assertAlmostEqual((1.0 + d) ** 365 - 1.0, 0.04, places=12)

    def test_default_periods(self):
        self.assertAlmostEqual(
            capm_mod.flat_daily_return(4.0),
            capm_mod.flat_daily_return(4.0, 365), places=15,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: covariance
# ─────────────────────────────────────────────────────────────────────────────

class TestCovariance(unittest.TestCase):
    def test_matches_statistics_pvariance_on_self(self):
        xs = [0.01, -0.02, 0.03, 0.0, 0.015]
        mx = statistics.fmean(xs)
        self.assertAlmostEqual(
            capm_mod.covariance(xs, xs, mx, mx),
            statistics.pvariance(xs), places=15,
        )

    def test_hand_example(self):
        xs = [1.0, 2.0, 3.0]
        ys = [2.0, 4.0, 6.0]
        mx = statistics.fmean(xs); my = statistics.fmean(ys)
        # cov = mean((x-2)(y-4)) = mean([(-1)(-2),0,(1)(2)]) = mean([2,0,2]) = 4/3
        self.assertAlmostEqual(
            capm_mod.covariance(xs, ys, mx, my), 4.0 / 3.0, places=12
        )

    def test_empty_is_zero(self):
        self.assertEqual(capm_mod.covariance([], [], 0.0, 0.0), 0.0)

    def test_symmetric(self):
        xs = [0.1, -0.2, 0.3]; ys = [0.05, 0.1, -0.1]
        mx = statistics.fmean(xs); my = statistics.fmean(ys)
        self.assertAlmostEqual(
            capm_mod.covariance(xs, ys, mx, my),
            capm_mod.covariance(ys, xs, my, mx), places=15,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: ols_capm
# ─────────────────────────────────────────────────────────────────────────────

class TestOlsCapm(unittest.TestCase):
    def test_recovers_beta_alpha_on_linear(self):
        rm = _varying_bench(40, seed=3, scale=0.02)
        rp = _linear_portfolio(rm, 1.5, 0.001)
        fit = capm_mod.ols_capm(rp, rm, 0.0)
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit["beta"], 1.5, places=9)
        self.assertAlmostEqual(fit["alpha_daily"], 0.001, places=9)
        # exact linear -> residuals ~ 0
        for e in fit["residuals"]:
            self.assertAlmostEqual(e, 0.0, places=9)

    def test_correlation_perfect_for_positive_beta(self):
        rm = _varying_bench(40, seed=4, scale=0.02)
        rp = _linear_portfolio(rm, 2.0, 0.0)
        fit = capm_mod.ols_capm(rp, rm, 0.0)
        self.assertAlmostEqual(fit["correlation"], 1.0, places=9)

    def test_correlation_negative_beta(self):
        rm = _varying_bench(40, seed=5, scale=0.02)
        rp = _linear_portfolio(rm, -1.0, 0.0)
        fit = capm_mod.ols_capm(rp, rm, 0.0)
        self.assertAlmostEqual(fit["correlation"], -1.0, places=9)

    def test_beta_hand_example(self):
        rp = [0.02, -0.01, 0.03, 0.0]
        rm = [0.01, -0.02, 0.02, 0.0]
        fit = capm_mod.ols_capm(rp, rm, 0.0)
        self.assertAlmostEqual(fit["beta"], 0.00022499999999999997 / 0.00021875, places=9)
        self.assertAlmostEqual(fit["alpha_daily"], 0.0074285714285714285, places=12)

    def test_rf_cancels_in_beta(self):
        rm = _varying_bench(30, seed=6, scale=0.02)
        rp = _linear_portfolio(rm, 1.3, 0.0008)
        f0 = capm_mod.ols_capm(rp, rm, 0.0)
        f1 = capm_mod.ols_capm(rp, rm, 0.0002)
        # beta is independent of Rf (Rf is constant -> cancels in cov/var)
        self.assertAlmostEqual(f0["beta"], f1["beta"], places=12)

    def test_zero_variance_benchmark_none(self):
        rp = [0.01, 0.02, -0.01, 0.0]
        rm = [0.0001] * 4  # flat -> var 0
        self.assertIsNone(capm_mod.ols_capm(rp, rm, 0.0001))

    def test_misaligned_none(self):
        self.assertIsNone(capm_mod.ols_capm([0.1, 0.2], [0.1], 0.0))

    def test_empty_none(self):
        self.assertIsNone(capm_mod.ols_capm([], [], 0.0))


# ─────────────────────────────────────────────────────────────────────────────
# build: full metric battery on a varying benchmark
# ─────────────────────────────────────────────────────────────────────────────

class TestVaryingBenchmark(unittest.TestCase):
    def _build(self, returns=None, bench=None, **kw):
        if returns is None:
            returns = _PORT
        if bench is None:
            bench = _BENCH
        with tempfile.TemporaryDirectory() as d:
            return _build_from_returns(d, returns, benchmark_returns=bench, **kw)

    def test_available_and_kind(self):
        res = self._build()
        self.assertTrue(res["available"])
        self.assertEqual(res["benchmark_kind"], "explicit")

    def test_beta_recovered(self):
        res = self._build()
        self.assertAlmostEqual(res["beta"], _BETA, places=6)

    def test_alpha_recovered(self):
        # The CAPM intercept for an exact simple-line portfolio rp=alpha+beta*rm
        # is alpha + rf_daily*(beta-1) (Rf is constant; the slope is beta but the
        # excess-return intercept shifts by rf*(beta-1)).
        res = self._build()
        rf_daily = capm_mod.flat_daily_return(capm_mod.DEFAULT_RISK_FREE_APY, 365)
        exp_alpha = _ALPHA + rf_daily * (_BETA - 1.0)
        self.assertAlmostEqual(res["jensen_alpha_daily"], exp_alpha, places=8)

    def test_alpha_annualized_geometric(self):
        res = self._build()
        rf_daily = capm_mod.flat_daily_return(capm_mod.DEFAULT_RISK_FREE_APY, 365)
        exp_alpha = _ALPHA + rf_daily * (_BETA - 1.0)
        exp = ((1.0 + exp_alpha) ** 365 - 1.0) * 100.0
        self.assertAlmostEqual(res["jensen_alpha_annualized_pct"], round(exp, 8), places=6)

    def test_correlation_perfect(self):
        res = self._build()
        self.assertAlmostEqual(res["correlation"], 1.0, places=6)

    def test_systematic_specific_split(self):
        # exact linear portfolio -> residuals ~ 0 -> specific_variance ~ 0,
        # capm_r_squared ~ 1, pct_systematic ~ 100
        res = self._build()
        self.assertAlmostEqual(res["specific_variance"], 0.0, places=8)
        self.assertAlmostEqual(res["capm_r_squared"], 1.0, places=6)
        self.assertAlmostEqual(res["pct_systematic_risk"], 100.0, places=4)

    def test_systematic_variance_value(self):
        res = self._build()
        var_m = statistics.pvariance(_BENCH)
        self.assertAlmostEqual(res["systematic_variance"], round(_BETA ** 2 * var_m, 8), places=8)

    def test_treynor_defined_positive_beta(self):
        res = self._build()
        self.assertIsNotNone(res["treynor_ratio"])

    def test_treynor_none_for_nonpositive_beta(self):
        # negative-beta portfolio -> Treynor None + note
        bench = _varying_bench(_N, seed=21, scale=0.02)
        port = _linear_portfolio(bench, -0.8, 0.0)
        res = self._build(returns=port, bench=bench)
        self.assertIsNone(res["treynor_ratio"])
        self.assertTrue(any("Treynor ratio undefined" in n for n in res["notes"]))

    def test_m2_defined(self):
        res = self._build()
        self.assertIsNotNone(res["modigliani_m2_pct"])
        self.assertIsNotNone(res["m2_alpha_pct"])

    def test_m2_formula(self):
        res = self._build()
        var_m = statistics.pvariance(_BENCH)
        rf_daily = capm_mod.flat_daily_return(capm_mod.DEFAULT_RISK_FREE_APY, 365)
        mean_p = statistics.fmean(_PORT)
        std_p = statistics.pstdev(_PORT)
        sharpe = (mean_p - rf_daily) / std_p
        rf_ann = (1.0 + rf_daily) ** 365 - 1.0
        sigma_b = math.sqrt(var_m) * math.sqrt(365) * 100.0
        exp_m2 = rf_ann * 100.0 + sharpe * sigma_b
        self.assertAlmostEqual(res["modigliani_m2_pct"], round(exp_m2, 8), places=5)

    def test_appraisal_defined_when_residual(self):
        # add idiosyncratic noise so residuals are non-zero
        bench = _varying_bench(_N, seed=31, scale=0.02)
        rnd = random.Random(99)
        port = [0.0003 + 1.1 * m + rnd.uniform(-0.005, 0.005) for m in bench]
        res = self._build(returns=port, bench=bench)
        self.assertIsNotNone(res["appraisal_ratio"])
        self.assertGreater(res["specific_variance"], 0.0)
        self.assertLess(res["capm_r_squared"], 1.0)

    def test_sharpe_portfolio_present(self):
        res = self._build()
        self.assertIsNotNone(res["sharpe_portfolio_daily"])

    def test_rf_fields(self):
        res = self._build()
        self.assertEqual(res["risk_free_annual_pct"], 4.0)
        self.assertAlmostEqual(
            res["risk_free_daily"],
            round(capm_mod.flat_daily_return(4.0, 365), 8), places=10,
        )

    def test_all_floats_rounded_8dp(self):
        res = self._build()
        for key in ("beta", "jensen_alpha_daily", "systematic_variance",
                    "specific_variance"):
            v = res[key]
            if v is not None:
                # 8-dp rounding -> at most 8 decimals
                self.assertEqual(round(v, 8), v)

    def test_headline_keys_present(self):
        res = self._build()
        for key in ("beta", "correlation", "jensen_alpha_daily",
                    "jensen_alpha_annualized_pct", "treynor_ratio",
                    "modigliani_m2_pct", "m2_alpha_pct", "appraisal_ratio",
                    "systematic_variance", "specific_variance",
                    "capm_r_squared", "pct_systematic_risk",
                    "sharpe_portfolio_daily", "portfolio_annualized_pct",
                    "benchmark_annualized_pct", "risk_free_annual_pct",
                    "risk_free_daily", "benchmark_kind", "count_returns",
                    "n_observations", "start_date", "end_date", "is_demo",
                    "verdict", "verdict_reason", "notes"):
            self.assertIn(key, res)

    def test_counts_consistent(self):
        res = self._build()
        self.assertEqual(res["count_returns"], _N)
        self.assertEqual(res["n_observations"], _N)

    def test_bench_truncation_alignment(self):
        # a shorter benchmark truncates BOTH series to the shorter length
        short_bench = _BENCH[:30]
        res = self._build(bench=short_bench)
        self.assertEqual(res["count_returns"], 30)


# ─────────────────────────────────────────────────────────────────────────────
# build: flat default benchmark (degenerate / zero variance)
# ─────────────────────────────────────────────────────────────────────────────

class TestFlatBenchmark(unittest.TestCase):
    def _build(self, returns=None):
        if returns is None:
            returns = [0.01, -0.005] * 15  # 30 returns
        with tempfile.TemporaryDirectory() as d:
            return _build_from_returns(d, returns)  # benchmark_returns=None

    def test_available_true(self):
        res = self._build()
        self.assertTrue(res["available"])

    def test_kind_flat(self):
        res = self._build()
        self.assertEqual(res["benchmark_kind"], "flat_risk_free")

    def test_all_decomposition_none(self):
        res = self._build()
        for key in ("beta", "correlation", "jensen_alpha_daily",
                    "jensen_alpha_annualized_pct", "treynor_ratio",
                    "modigliani_m2_pct", "m2_alpha_pct", "appraisal_ratio",
                    "systematic_variance", "specific_variance",
                    "capm_r_squared", "pct_systematic_risk"):
            self.assertIsNone(res[key], key)

    def test_verdict_ok(self):
        res = self._build()
        self.assertEqual(res["verdict"], "ok")

    def test_flat_note_present(self):
        res = self._build()
        self.assertTrue(any(
            "flat risk-free benchmark has zero variance" in n
            and "requires a varying benchmark series" in n
            for n in res["notes"]
        ))

    def test_portfolio_stats_still_present(self):
        # portfolio-only stats are defined even with a flat benchmark
        res = self._build()
        self.assertIsNotNone(res["portfolio_annualized_pct"])
        self.assertIsNotNone(res["sharpe_portfolio_daily"])
        self.assertIsNotNone(res["risk_free_daily"])


# ─────────────────────────────────────────────────────────────────────────────
# build: verdict bands (on Jensen's annualized alpha)
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBands(unittest.TestCase):
    def _build(self, port, bench):
        with tempfile.TemporaryDirectory() as d:
            return _build_from_returns(d, port, benchmark_returns=bench)

    def test_ok_positive_alpha(self):
        # large positive daily alpha -> annualized alpha well above ALPHA_OK_PCT
        bench = _varying_bench(_N, seed=41, scale=0.02)
        port = _linear_portfolio(bench, 1.0, 0.0005)  # ~20%/yr alpha
        res = self._build(port, bench)
        self.assertEqual(res["verdict"], "ok")
        self.assertGreaterEqual(res["jensen_alpha_annualized_pct"], capm_mod.ALPHA_OK_PCT)
        self.assertIn("positive risk-adjusted excess return", res["verdict_reason"])

    def test_ok_near_zero_alpha(self):
        # tiny alpha -> annualized in the neutral band
        bench = _varying_bench(_N, seed=42, scale=0.02)
        port = _linear_portfolio(bench, 1.0, 0.00001)
        res = self._build(port, bench)
        self.assertEqual(res["verdict"], "ok")
        self.assertLess(res["jensen_alpha_annualized_pct"], capm_mod.ALPHA_OK_PCT)
        self.assertGreater(res["jensen_alpha_annualized_pct"], capm_mod.ALPHA_WARN_PCT)
        self.assertIn("near zero", res["verdict_reason"])

    def test_warn_negative_alpha(self):
        # strongly negative daily alpha -> annualized alpha below ALPHA_WARN_PCT
        bench = _varying_bench(_N, seed=43, scale=0.02)
        port = _linear_portfolio(bench, 1.0, -0.0005)
        res = self._build(port, bench)
        self.assertEqual(res["verdict"], "warn")
        self.assertLessEqual(res["jensen_alpha_annualized_pct"], capm_mod.ALPHA_WARN_PCT)

    def test_verdict_in_ok_warn_only(self):
        for seed, alpha in ((51, 0.0005), (52, 0.0), (53, -0.0005)):
            bench = _varying_bench(_N, seed=seed, scale=0.02)
            port = _linear_portfolio(bench, 1.0, alpha)
            res = self._build(port, bench)
            with self.subTest(seed=seed):
                self.assertIn(res["verdict"], ("ok", "warn"))

    def test_verdict_reason_always_present(self):
        bench = _varying_bench(_N, seed=44, scale=0.02)
        port = _linear_portfolio(bench, 1.0, -0.0005)
        res = self._build(port, bench)
        self.assertTrue(res["verdict_reason"])

    def test_low_sample_guard_note(self):
        # < MIN_SAMPLE_GUARD (40) returns -> the thin-evidence note fires
        bench = _varying_bench(25, seed=45, scale=0.02)
        port = _linear_portfolio(bench, 1.0, 0.0005)
        res = self._build(port, bench)
        self.assertLess(res["n_observations"], capm_mod.MIN_SAMPLE_GUARD)
        self.assertTrue(any("low-sample guard" in n for n in res["notes"]))
        self.assertIn(res["verdict"], ("ok", "warn"))

    def test_no_low_sample_note_when_enough(self):
        bench = _varying_bench(_N, seed=46, scale=0.02)  # 60 >= 40
        port = _linear_portfolio(bench, 1.0, 0.0005)
        res = self._build(port, bench)
        self.assertFalse(any("low-sample guard" in n for n in res["notes"]))


# ─────────────────────────────────────────────────────────────────────────────
# build: insufficient data + degenerate
# ─────────────────────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_insufficient_returns(self):
        # 19 returns (< MIN_OBS=20)
        returns = [0.01, -0.01] * 9 + [0.02]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(res["n_observations"], 19)

    def test_insufficient_aligned_benchmark(self):
        # enough portfolio returns but a too-short benchmark truncates below MIN_OBS
        returns = [0.01, -0.005] * 15  # 30 returns
        bench = _varying_bench(10, seed=61, scale=0.02)  # 10 < MIN_OBS
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns, benchmark_returns=bench)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")

    def test_empty_equity(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = capm_mod.build_capm_decomposition(d)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")

    def test_schema_stable_when_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = capm_mod.build_capm_decomposition(d)
        for key in ("available", "beta", "correlation", "jensen_alpha_daily",
                    "jensen_alpha_annualized_pct", "treynor_ratio",
                    "modigliani_m2_pct", "m2_alpha_pct", "appraisal_ratio",
                    "systematic_variance", "specific_variance",
                    "capm_r_squared", "pct_systematic_risk",
                    "sharpe_portfolio_daily", "portfolio_annualized_pct",
                    "benchmark_annualized_pct", "risk_free_annual_pct",
                    "risk_free_daily", "benchmark_kind", "count_returns",
                    "n_observations", "start_date", "end_date", "verdict",
                    "verdict_reason", "notes", "meta"):
            self.assertIn(key, res)


# ─────────────────────────────────────────────────────────────────────────────
# is_demo passthrough
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    def test_is_demo_true(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _PORT, benchmark_returns=_BENCH, is_demo=True)
        self.assertIs(res["is_demo"], True)

    def test_is_demo_false(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _PORT, benchmark_returns=_BENCH, is_demo=False)
        self.assertIs(res["is_demo"], False)

    def test_is_demo_absent_none(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _PORT, benchmark_returns=_BENCH)
        self.assertIsNone(res["is_demo"])


# ─────────────────────────────────────────────────────────────────────────────
# never-raise / tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverRaise(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            res = capm_mod.build_capm_decomposition(d)
        self.assertFalse(res["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / capm_mod.EQUITY_FILENAME).write_text("{not json", encoding="utf-8")
            res = capm_mod.build_capm_decomposition(d)
        self.assertFalse(res["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / capm_mod.EQUITY_FILENAME).write_text("123", encoding="utf-8")
            res = capm_mod.build_capm_decomposition(d)
        self.assertFalse(res["available"])

    def test_list_root(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [{"date": dt, "close_equity": 100.0 + i}
                    for i, dt in enumerate(_dates(30))]
            (Path(d) / capm_mod.EQUITY_FILENAME).write_text(
                json.dumps(bars), encoding="utf-8"
            )
            res = capm_mod.build_capm_decomposition(d)
        # a bare list IS accepted by extract_equity_series -> available (flat
        # default benchmark -> decomposition None but available True)
        self.assertTrue(res["available"])

    def test_garbage_bars(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"daily": ["nope", 7, None, {"date": "bad"}, {}]}
            _write_equity(d, doc)
            res = capm_mod.build_capm_decomposition(d)
        self.assertFalse(res["available"])

    def test_fuzz_never_raises(self):
        rnd = random.Random(13)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / capm_mod.EQUITY_FILENAME
            for _ in range(40):
                kind = rnd.randint(0, 4)
                if kind == 0:
                    p.write_text("", encoding="utf-8")
                elif kind == 1:
                    p.write_text("{", encoding="utf-8")
                elif kind == 2:
                    p.write_text(json.dumps({"daily": rnd.random()}), encoding="utf-8")
                elif kind == 3:
                    bars = [{"date": "2026-01-01", "close_equity": rnd.uniform(-5, 100)}
                            for _ in range(rnd.randint(0, 50))]
                    p.write_text(json.dumps({"daily": bars}), encoding="utf-8")
                else:
                    levels = [rnd.uniform(50, 150) for _ in range(rnd.randint(0, 60))]
                    p.write_text(json.dumps(_equity_doc(levels)), encoding="utf-8")
                # exercise both the flat and the varying-benchmark paths
                bench = None if rnd.random() < 0.5 else _varying_bench(
                    rnd.randint(0, 60), seed=rnd.randint(0, 999), scale=0.02
                )
                res = capm_mod.build_capm_decomposition(d, benchmark_returns=bench)
                self.assertIn("verdict", res)
                self.assertIn(res["verdict"], ("ok", "warn"))

    def test_fuzz_benchmark_values_never_raise(self):
        # extreme / pathological benchmark values must not raise
        rnd = random.Random(77)
        returns = [0.01, -0.005] * 20  # 40 returns
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, _equity_doc(_equity_from_returns(returns)))
            for _ in range(30):
                bench = [rnd.choice([-1.0, 0.0, 0.0001, 5.0, rnd.uniform(-1, 1)])
                         for _ in range(rnd.randint(0, 45))]
                res = capm_mod.build_capm_decomposition(d, benchmark_returns=bench)
                self.assertIn(res["verdict"], ("ok", "warn"))


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import (single source of truth)
# ─────────────────────────────────────────────────────────────────────────────

class TestReuseByImport(unittest.TestCase):
    def test_content_fingerprint_is_tear_sheet_object(self):
        self.assertIs(capm_mod.content_fingerprint, tear_sheet.content_fingerprint)

    def test_extract_equity_series_is_drawdown_object(self):
        self.assertIs(
            capm_mod.extract_equity_series, drawdown_analytics.extract_equity_series
        )

    def test_fingerprint_ignores_volatile_fields(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _PORT, benchmark_returns=_BENCH)
            a = dict(res)
            b = dict(res)
            b["meta"] = dict(b["meta"])
            b["meta"]["generated_at"] = "DIFFERENT"
            b["history"] = [{"x": 1}]
            self.assertEqual(
                capm_mod.content_fingerprint(a), capm_mod.content_fingerprint(b)
            )

    def test_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _PORT, benchmark_returns=_BENCH)
            a = dict(res)
            b = dict(res)
            b["beta"] = 99.0
            self.assertNotEqual(
                capm_mod.content_fingerprint(a), capm_mod.content_fingerprint(b)
            )


# ─────────────────────────────────────────────────────────────────────────────
# write_status: idempotency / rotation / atomicity
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStatus(unittest.TestCase):
    def _good_result(self, d):
        return _build_from_returns(d, _PORT, benchmark_returns=_BENCH)

    def test_written_then_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            self.assertEqual(capm_mod.write_status(res, d), "DATA_WRITTEN")
            # re-build with a flat benchmark deterministically (build itself
            # writes nothing); fresh generated_at but identical content.
            res2 = capm_mod.build_capm_decomposition(d, benchmark_returns=_BENCH)
            self.assertEqual(capm_mod.write_status(res2, d), "DATA_UNCHANGED")

    def test_md5_identical_on_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            capm_mod.write_status(res, d)
            p = Path(d) / capm_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            res2 = capm_mod.build_capm_decomposition(d, benchmark_returns=_BENCH)
            capm_mod.write_status(res2, d)
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            capm_mod.write_status(res, d)
            leftovers = list(Path(d).glob(".tmp_capm_decomposition_*"))
            self.assertEqual(leftovers, [])

    def test_history_rotation_exactly_max(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / capm_mod.STATUS_FILENAME
            base = self._good_result(d)
            big_hist = [{"_fingerprint": f"x{i}", "beta": i}
                        for i in range(capm_mod.HISTORY_MAX + 50)]
            seed = dict(base)
            seed["_fingerprint"] = "SEED_DIFFERENT"
            seed["history"] = big_hist
            out.write_text(json.dumps(seed), encoding="utf-8")
            changed = dict(base)
            changed["beta"] = 99.0
            self.assertEqual(capm_mod.write_status(changed, d), "DATA_WRITTEN")
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(doc["history"]), capm_mod.HISTORY_MAX)

    def test_tolerates_broken_previous(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / capm_mod.STATUS_FILENAME
            _write_equity(d, _equity_doc(_equity_from_returns(_PORT)))
            res = capm_mod.build_capm_decomposition(d, benchmark_returns=_BENCH)
            out.write_text("{garbage", encoding="utf-8")
            self.assertEqual(capm_mod.write_status(res, d), "DATA_WRITTEN")

    def test_creates_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "nested" / "data"
            _write_equity(d, _equity_doc(_equity_from_returns(_PORT)))
            res = capm_mod.build_capm_decomposition(d, benchmark_returns=_BENCH)
            self.assertEqual(capm_mod.write_status(res, sub), "DATA_WRITTEN")
            self.assertTrue((sub / capm_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# CLI: direct main(argv) + subprocess
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def _seed(self, d):
        # CLI uses the flat default benchmark (build with benchmark_returns=None)
        _write_equity(d, _equity_doc(_equity_from_returns([0.01, -0.005] * 20)))

    def test_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = capm_mod.main(["--check", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / capm_mod.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = capm_mod.main(["--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / capm_mod.STATUS_FILENAME).exists())

    def test_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = capm_mod.main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / capm_mod.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            capm_mod.main(["--run", "--data-dir", d])
            p = Path(d) / capm_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            capm_mod.main(["--run", "--data-dir", d])
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_conflict_check_run(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = capm_mod.main(["--check", "--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / capm_mod.STATUS_FILENAME).exists())

    def test_unknown_args(self):
        rc = capm_mod.main(["--frobnicate"])
        self.assertEqual(rc, 0)

    def test_subprocess_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.capm_decomposition",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("[capm_decomposition]", proc.stdout)

    def test_subprocess_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.capm_decomposition",
                 "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertTrue((Path(d) / capm_mod.STATUS_FILENAME).exists())

    def test_subprocess_garbage_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / capm_mod.EQUITY_FILENAME).write_text("{bad", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.capm_decomposition",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_conflict_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.capm_decomposition",
                 "--check", "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertFalse((Path(d) / capm_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# import hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = Path(capm_mod.__file__).read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(src, capm_mod.__file__)
        self.assertEqual(violations, [])

    def test_no_forbidden_text(self):
        # Strip the module docstring before scanning: the prose disclaimer
        # legitimately lists the forbidden module names and must not be flagged.
        src = Path(capm_mod.__file__).read_text(encoding="utf-8")
        body = src
        if '"""' in src:
            parts = src.split('"""')
            if len(parts) >= 3:
                body = '"""'.join(parts[2:])
        for needle in ("import requests", "import socket", "import subprocess",
                       "subprocess.", "eval(", "exec(", "import web3",
                       "anthropic", "import numpy", "import pandas"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, body)

    def test_py_compile_both(self):
        import py_compile
        for fname in ("paper_trading/capm_decomposition.py",
                      "tests/test_capm_decomposition.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
