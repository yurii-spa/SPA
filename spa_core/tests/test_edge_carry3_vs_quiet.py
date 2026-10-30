"""Controls for registry #150 — CARRY-3+cash vs QUIET-N (заказ #149).

Every test here is a positive control: it either verifies the instrument's core
invariant, or it breaks one named wire and confirms the instrument notices.
None asserts on a printed substring (ADR-333) — each calls the real internal
functions of `scripts/edge_carry3_vs_quiet.py` on a deterministic input scene.

FROZEN-DATE-OK: synthetic-axis — all dates come from the fixture (_BACKTEST_START
is 2024-07-01, _BACKTEST_END is 2026-05-31, both constants in the fixture module
itself). The script imports no time/datetime clock and takes no `now` argument;
no verdict can change because the calendar moved.
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_carry3_vs_quiet.py"

# Ensure spa_core is importable (needed when the fixture is loaded inside the script)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mod():
    if "_carry3_under_test" in sys.modules:
        return sys.modules["_carry3_under_test"]
    spec = importlib.util.spec_from_file_location("_carry3_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_carry3_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestFixtureLoads(unittest.TestCase):
    """The fixture must load and return the expected 5-book roster."""

    def test_fixture_loads_five_eligible_books(self):
        m = _mod()
        fix = m._load_fixture()
        # All five ELIGIBLE_BOOKS must have backtest equity
        for book in m.ELIGIBLE_BOOKS:
            eq = m._backtest_equity(fix, book)
            self.assertGreater(len(eq), 0, f"{book} has no backtest equity")

    def test_thin_new_excluded_from_eligible(self):
        m = _mod()
        self.assertNotIn("thin_new", m.ELIGIBLE_BOOKS)


class TestPeriodMetrics(unittest.TestCase):
    """_period_metrics must return correct APY and maxDD on deterministic inputs."""

    def _make_linear(self, start_val: float, n: int, daily_r: float):
        d = datetime.date(2024, 1, 1)
        series = []
        eq = start_val
        for i in range(n):
            series.append((d + datetime.timedelta(days=i), eq))
            eq *= (1 + daily_r)
        return series

    def test_flat_equity_zero_drawdown(self):
        m = _mod()
        series = [(datetime.date(2024, 1, 1) + datetime.timedelta(days=i), 100.0)
                  for i in range(100)]
        apy, mdd = m._period_metrics(series, datetime.date(2024, 1, 1),
                                     datetime.date(2024, 4, 9))
        self.assertAlmostEqual(mdd, 0.0, places=6)

    def test_monotone_rising_zero_drawdown(self):
        m = _mod()
        series = self._make_linear(100.0, 365, 0.0003)
        apy, mdd = m._period_metrics(series, series[0][0], series[-1][0])
        self.assertAlmostEqual(mdd, 0.0, places=6)
        self.assertGreater(apy, 0.0)

    def test_single_day_loss_reflected_in_mdd(self):
        m = _mod()
        # Equity rises then drops 5%
        base = [(datetime.date(2024, 1, 1) + datetime.timedelta(days=i), 100.0 * (1.001 ** i))
                for i in range(50)]
        # Append a single-day 5% drop
        last_d, last_e = base[-1]
        base.append((last_d + datetime.timedelta(days=1), last_e * 0.95))
        _, mdd = m._period_metrics(base, base[0][0], base[-1][0])
        self.assertGreater(mdd, 4.0)  # at least a ~5% drawdown

    def test_insufficient_data_returns_none(self):
        m = _mod()
        series = [(datetime.date(2024, 1, 1), 100.0)]
        apy, mdd = m._period_metrics(series, datetime.date(2024, 1, 1),
                                     datetime.date(2024, 1, 1))
        self.assertIsNone(apy)
        self.assertIsNone(mdd)


class TestPortfolioBuilder(unittest.TestCase):
    """_ew_portfolio_equity must correctly compound per-book daily returns."""

    def _make_constant_return(self, r: float, start: datetime.date,
                              n: int) -> list:
        """Build a deterministic equity series with constant daily return r."""
        eq = 1.0
        series = [(start, eq)]
        for i in range(1, n + 1):
            eq *= (1 + r)
            series.append((start + datetime.timedelta(days=i), eq))
        return series

    def test_single_book_ew_matches_book_return(self):
        m = _mod()
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 4, 9)
        series = self._make_constant_return(0.001, start, 99)
        series_map = {"a": series}
        port = m._ew_portfolio_equity(series_map, ["a"], None, start, end)
        papy, pmdd = m._portfolio_metrics(port)
        # Direct metrics on the raw series in the same window
        rapy, rmdd = m._period_metrics(series, start, end)
        self.assertAlmostEqual(papy, rapy, places=4)
        self.assertAlmostEqual(pmdd, rmdd, places=4)

    def test_ew_two_identical_books_matches_one(self):
        m = _mod()
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 4, 9)
        series = self._make_constant_return(0.001, start, 99)
        series_map = {"a": series, "b": series}
        port = m._ew_portfolio_equity(series_map, ["a", "b"], None, start, end)
        papy, pmdd = m._portfolio_metrics(port)
        rapy, rmdd = m._period_metrics(series, start, end)
        self.assertAlmostEqual(papy, rapy, places=3)
        self.assertAlmostEqual(pmdd, rmdd, places=3)

    def test_cash_arm_earns_zero(self):
        m = _mod()
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 4, 9)
        series = self._make_constant_return(0.001, start, 99)
        series_map = {"a": series}
        # 50% book + 50% cash
        wts = {"a": 0.5, "__cash__": 0.5}
        port = m._ew_portfolio_equity(series_map, ["a"], wts, start, end)
        papy, _ = m._portfolio_metrics(port)
        rapy, _ = m._period_metrics(series, start, end)
        # Portfolio APY should be materially lower than full book APY due to 50% cash drag.
        # Exact half-APY doesn't hold because compounding: (1+r)^365 * 0.5 ≠ (1+r/2)^365.
        # With r=0.001/day, full-book ≈44%, half-weight ≈20%, so papy is in (rapy*0.3, rapy*0.7).
        self.assertGreater(papy, rapy * 0.3)
        self.assertLess(papy, rapy * 0.7)


class TestCarryAndQuietComposition(unittest.TestCase):
    """On fixture, verify that QUIET-2 and CARRY-3 differ in composition on seam 2025-06-30."""

    def test_quiet2_and_carry3_are_not_the_same_set_on_seam1(self):
        m = _mod()
        fix = m._load_fixture()
        seam_date = datetime.date(2025, 6, 30)
        train_start = datetime.date(2024, 7, 1)

        # Compute TRAIN maxDD per eligible book
        series_map = {b: m._backtest_equity(fix, b) for b in m.ELIGIBLE_BOOKS}
        train_mdd = {}
        for b in m.ELIGIBLE_BOOKS:
            _, mdd = m._period_metrics(series_map[b], train_start, seam_date)
            if mdd is not None:
                train_mdd[b] = mdd

        valid = sorted([(b, d) for b, d in train_mdd.items() if b != "variant_d"],
                       key=lambda x: x[1])
        quiet_2 = {b for b, _ in valid[:2]}
        carry_3 = set(m.CARRY_3_BOOKS)
        # On fixture seam 2025-06-30 the two selectors must be different
        self.assertNotEqual(quiet_2, carry_3,
                            "QUIET-2 should differ from CARRY-3 on seam 2025-06-30")

    def test_quiet2_outperforms_carry3cash_on_seam1(self):
        """On seam 2025-06-30, QUIET-2 APY should be materially higher than CARRY-3+25%cash APY."""
        m = _mod()
        fix = m._load_fixture()
        seam_date = datetime.date(2025, 6, 30)
        train_start = datetime.date(2024, 7, 1)
        test_start = seam_date + datetime.timedelta(days=1)
        test_end = datetime.date(2026, 5, 31)

        series_map = {b: m._backtest_equity(fix, b) for b in m.ELIGIBLE_BOOKS}

        # Build QUIET-2
        train_mdd = {}
        for b in m.ELIGIBLE_BOOKS:
            _, mdd = m._period_metrics(series_map[b], train_start, seam_date)
            if mdd is not None:
                train_mdd[b] = mdd
        valid = sorted([(b, d) for b, d in train_mdd.items() if b != "variant_d"],
                       key=lambda x: x[1])
        quiet_2 = [b for b, _ in valid[:2]]

        # QUIET-2 portfolio
        q2_eq = m._ew_portfolio_equity(series_map, quiet_2, None, test_start, test_end)
        q2_apy, _ = m._portfolio_metrics(q2_eq)

        # CARRY-3+25%cash portfolio
        c3 = list(m.CARRY_3_BOOKS)
        wts = {b: (1 - m.CASH_FRACTION) / len(c3) for b in c3}
        wts["__cash__"] = m.CASH_FRACTION
        c3_eq = m._ew_portfolio_equity(series_map, c3, wts, test_start, test_end)
        c3_apy, _ = m._portfolio_metrics(c3_eq)

        self.assertIsNotNone(q2_apy)
        self.assertIsNotNone(c3_apy)
        # QUIET-2 should materially outperform CARRY-3+cash on this seam
        self.assertGreater(q2_apy - c3_apy, 5.0,
                           "QUIET-2 should be >5pp APY better than CARRY-3+cash on seam 2025-06-30")

    def test_quiet2_underperforms_carry3cash_on_seam2(self):
        """On seam 2026-01-01, CARRY-3+cash should outperform QUIET-2 (lrt_carry trap)."""
        m = _mod()
        fix = m._load_fixture()
        seam_date = datetime.date(2026, 1, 1)
        train_start = datetime.date(2024, 7, 1)
        test_start = seam_date + datetime.timedelta(days=1)
        test_end = datetime.date(2026, 5, 31)

        series_map = {b: m._backtest_equity(fix, b) for b in m.ELIGIBLE_BOOKS}

        # Build QUIET-2 for seam 2026-01-01
        train_mdd = {}
        for b in m.ELIGIBLE_BOOKS:
            _, mdd = m._period_metrics(series_map[b], train_start, seam_date)
            if mdd is not None:
                train_mdd[b] = mdd
        valid = sorted([(b, d) for b, d in train_mdd.items() if b != "variant_d"],
                       key=lambda x: x[1])
        quiet_2 = [b for b, _ in valid[:2]]

        # lrt_carry should be in QUIET-2 on seam 2026-01-01 (its rsETH depeg is in TEST)
        self.assertIn("lrt_carry", quiet_2,
                      "lrt_carry should appear 'quiet' in TRAIN on seam 2026-01-01")

        # QUIET-2 portfolio
        q2_eq = m._ew_portfolio_equity(series_map, quiet_2, None, test_start, test_end)
        q2_apy, _ = m._portfolio_metrics(q2_eq)

        # CARRY-3+25%cash portfolio
        c3 = list(m.CARRY_3_BOOKS)
        wts = {b: (1 - m.CASH_FRACTION) / len(c3) for b in c3}
        wts["__cash__"] = m.CASH_FRACTION
        c3_eq = m._ew_portfolio_equity(series_map, c3, wts, test_start, test_end)
        c3_apy, _ = m._portfolio_metrics(c3_eq)

        self.assertIsNotNone(q2_apy)
        self.assertIsNotNone(c3_apy)
        # On seam 2026-01-01 CARRY-3+cash should beat QUIET-2
        self.assertGreater(c3_apy - q2_apy, 1.0,
                           "CARRY-3+cash should outperform QUIET-2 on seam 2026-01-01")

    def test_selectors_outside_toll_both_seams(self):
        """On both seams, ΔAPY between QUIET-2 and CARRY-3+cash must exceed the 96bp toll."""
        m = _mod()
        fix = m._load_fixture()

        for seam_str in m.SEAMS:
            seam_date = datetime.date.fromisoformat(seam_str)
            train_start = datetime.date(2024, 7, 1)
            test_start = seam_date + datetime.timedelta(days=1)
            test_end = datetime.date(2026, 5, 31)
            if test_start > test_end:
                continue

            series_map = {b: m._backtest_equity(fix, b) for b in m.ELIGIBLE_BOOKS}
            train_mdd = {}
            for b in m.ELIGIBLE_BOOKS:
                _, mdd = m._period_metrics(series_map[b], train_start, seam_date)
                if mdd is not None:
                    train_mdd[b] = mdd
            valid = sorted([(b, d) for b, d in train_mdd.items() if b != "variant_d"],
                           key=lambda x: x[1])
            quiet_2 = [b for b, _ in valid[:2]]

            q2_eq = m._ew_portfolio_equity(series_map, quiet_2, None, test_start, test_end)
            q2_apy, _ = m._portfolio_metrics(q2_eq)

            c3 = list(m.CARRY_3_BOOKS)
            wts = {b: (1 - m.CASH_FRACTION) / len(c3) for b in c3}
            wts["__cash__"] = m.CASH_FRACTION
            c3_eq = m._ew_portfolio_equity(series_map, c3, wts, test_start, test_end)
            c3_apy, _ = m._portfolio_metrics(c3_eq)

            self.assertIsNotNone(q2_apy, f"seam {seam_str}: QUIET-2 APY is None")
            self.assertIsNotNone(c3_apy, f"seam {seam_str}: CARRY-3+cash APY is None")

            diff = abs(q2_apy - c3_apy)
            toll_pct = m.TOLL_FRAC * 100
            self.assertGreater(diff, toll_pct,
                               f"seam {seam_str}: ΔAPY={diff:.2f}pp not > toll={toll_pct:.2f}pp — "
                               "selectors should be distinguishable")


if __name__ == "__main__":
    unittest.main()
