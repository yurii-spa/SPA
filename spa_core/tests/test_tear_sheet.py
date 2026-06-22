"""Тесты MP-501 — публичный ежемесячный tear-sheet (spa_core/reporting/tear_sheet.py).

unittest (НЕ pytest), без сети; вся персистентность — только в tempdir.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.governance.capital_ladder import detect_incidents
from spa_core.reporting import tear_sheet as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "spa_core" / "reporting" / "tear_sheet.py"

MONTH = "2026-05"

# 12 дневных return'ов мая (>= PSR_MIN_RETURNS=10, PSR вычислим):
# первые три дают известные net/drawdown/incident вручную.
MAY_RETURNS = [1.0, -1.5, 0.5, 0.1, 0.2, -0.1, 0.3, 0.05, 0.15, -0.05, 0.2, 0.1]


def _make_equity_doc() -> dict:
    daily = [
        # глобальный seed-бар (его 0.0 — заглушка, исключается из метрик)
        {"date": "2026-04-30", "daily_return_pct": 0.0,
         "open_equity": 100000.0, "low_equity": 100000.0},
    ]
    for i, ret in enumerate(MAY_RETURNS, start=1):
        bar = {"date": f"2026-05-{i:02d}", "daily_return_pct": ret}
        if i == 2:  # инцидент: -1.5% close-to-close + intraday open→low 1.5%
            bar["open_equity"] = 101000.0
            bar["low_equity"] = 99485.0
        daily.append(bar)
    daily.append({"date": "2026-06-01", "daily_return_pct": 0.2})
    return {
        "is_demo": False,
        "execution_mode": "read_only_simulation",
        "summary": {"end_equity": 100017.3},
        "daily": daily,
    }


EQUITY_DOC = _make_equity_doc()

POSITIONS_DOC = {
    "generated_at": "2026-05-31T23:59:00+00:00",
    "capital_usd": 100000.0,
    "deployed_usd": 95000.0,
    "cash_usd": 5000.0,
    "positions": {
        "aave_v3": 40000.0,
        "compound_v3": 30000.0,
        "maple": 25000.0,
    },
}

ORCH_DOC = {
    "adapters": [
        {"protocol": "aave_v3", "tier": "T1"},
        {"protocol": "compound_v3", "tier": "T1"},
        {"protocol": "morpho_blue", "tier": "T2"},
    ],
}

LADDER_DOC = {
    "current_level": 0,
    "level_code": "L0",
    "level_name": "paper",
    "aum_cap_usd": 100000.0,
    "aum_usd": 100017.3,
    "track_days": 23,
    "incidents_total": 1,
}

ANCHORS_DOC = {
    "schema_version": 1,
    "anchors": [
        {"date": "2026-05-02", "merkle_root": "ab" * 32, "leaf_count": 3,
         "published": False, "tx_hash": None},
        {"date": "2026-05-03", "merkle_root": None, "leaf_count": 0,
         "published": False, "tx_hash": None},
        {"date": "2026-06-11", "merkle_root": "cd" * 32, "leaf_count": 5,
         "published": True, "tx_hash": "0xdead"},
    ],
}

PT_DOC = {
    "is_demo": False,
    "execution_mode": "read_only_simulation",
    "paper_start_date": "2026-04-30",
    "days_running": 23,
}

GOLIVE_DOC = {"ready": True, "timestamp": "2026-05-31T23:59:00+00:00"}

TRADES_DOC = [
    {"trade_id": "T001", "ts": "2026-05-02T10:00:00+00:00", "type": "rebalance"},
    {"trade_id": "T002", "ts": "2026-05-20T10:00:00+00:00", "type": "rebalance"},
    {"trade_id": "T003", "ts": "2026-06-01T10:00:00+00:00", "type": "rebalance"},
]


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _compound(returns) -> float:
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    return (growth - 1.0) * 100.0


class TearSheetBase(unittest.TestCase):
    """Общий tempdir-каркас: data_dir + reports_dir, никакой записи в репо."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.reports_dir = Path(self._tmp.name) / "reports"
        self.data_dir.mkdir(parents=True)

    def write_all_sources(self):
        _write_json(self.data_dir / ts.EQUITY_FILENAME, EQUITY_DOC)
        _write_json(self.data_dir / ts.POSITIONS_FILENAME, POSITIONS_DOC)
        _write_json(self.data_dir / ts.ORCH_STATUS_FILENAME, ORCH_DOC)
        _write_json(self.data_dir / ts.LADDER_STATUS_FILENAME, LADDER_DOC)
        _write_json(self.data_dir / ts.ANCHORS_FILENAME, ANCHORS_DOC)
        _write_json(self.data_dir / ts.PT_STATUS_FILENAME, PT_DOC)
        _write_json(self.data_dir / ts.GOLIVE_STATUS_FILENAME, GOLIVE_DOC)
        _write_json(self.data_dir / ts.TRADES_FILENAME, TRADES_DOC)

    def no_tmp_leftovers(self):
        for root in (self.data_dir, self.reports_dir):
            if not root.exists():
                continue
            stray = [p for p in root.rglob("*") if p.name.endswith(".tmp")]
            self.assertEqual(stray, [], f"stray tmp files: {stray}")


# ─── validate_month ──────────────────────────────────────────────────────────


class TestValidateMonth(unittest.TestCase):
    def test_valid_month_passes(self):
        self.assertEqual(ts.validate_month("2026-05"), "2026-05")

    def test_garbage_string_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month("garbage")

    def test_month_13_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month("2026-13")

    def test_single_digit_month_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month("2026-6")

    def test_full_date_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month("2026-06-01")

    def test_non_string_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month(202606)

    def test_month_00_raises(self):
        with self.assertRaises(ValueError):
            ts.validate_month("2026-00")


# ─── фильтрация месяца ───────────────────────────────────────────────────────


class TestMonthFiltering(unittest.TestCase):
    def test_filter_picks_only_month(self):
        bars = ts.filter_month_bars(EQUITY_DOC["daily"], MONTH)
        self.assertEqual(len(bars), len(MAY_RETURNS))
        self.assertEqual(bars[0]["date"], "2026-05-01")
        self.assertEqual(bars[-1]["date"], f"2026-05-{len(MAY_RETURNS):02d}")

    def test_filter_ignores_garbage_entries(self):
        daily = [{"date": "2026-05-01", "daily_return_pct": 1.0},
                 "junk", 42, None,
                 {"date": "not-a-date"}, {"no_date": True}]
        bars = ts.filter_month_bars(daily, MONTH)
        self.assertEqual(len(bars), 1)

    def test_filter_sorted_by_date(self):
        daily = [{"date": "2026-05-09"}, {"date": "2026-05-01"}]
        bars = ts.filter_month_bars(daily, MONTH)
        self.assertEqual([b["date"] for b in bars],
                         ["2026-05-01", "2026-05-09"])

    def test_filter_non_list_input(self):
        self.assertEqual(ts.filter_month_bars({"a": 1}, MONTH), [])
        self.assertEqual(ts.filter_month_bars(None, MONTH), [])

    def test_series_excludes_global_seed_bar(self):
        # seed 2026-04-30 не в месяце; но если месяц = месяцу seed-бара,
        # его 0.0 всё равно исключается
        series = ts.monthly_return_series(EQUITY_DOC["daily"], "2026-04")
        self.assertEqual(series, [])

    def test_series_includes_month_first_bar_when_seed_earlier(self):
        series = ts.monthly_return_series(EQUITY_DOC["daily"], MONTH)
        self.assertEqual([r for _, r in series], MAY_RETURNS)
        self.assertEqual(series[0][0], "2026-05-01")

    def test_series_skips_non_numeric_returns(self):
        daily = [
            {"date": "2026-04-30", "daily_return_pct": 0.0},
            {"date": "2026-05-01", "daily_return_pct": "oops"},
            {"date": "2026-05-02", "daily_return_pct": True},
            {"date": "2026-05-03", "daily_return_pct": 0.3},
        ]
        series = ts.monthly_return_series(daily, MONTH)
        self.assertEqual(series, [("2026-05-03", 0.3)])

    def test_series_non_list_input(self):
        self.assertEqual(ts.monthly_return_series(None, MONTH), [])


# ─── компаундинг / drawdown ──────────────────────────────────────────────────


class TestCompounding(unittest.TestCase):
    def test_two_days_compound(self):
        self.assertAlmostEqual(ts.compound_return_pct([1.0, 1.0]), 2.01, places=10)

    def test_empty_returns_none(self):
        self.assertIsNone(ts.compound_return_pct([]))

    def test_negative_compound(self):
        expected = (1.01 * 0.985 * 1.005 - 1.0) * 100.0
        self.assertAlmostEqual(
            ts.compound_return_pct([1.0, -1.5, 0.5]), expected, places=10)

    def test_wipeout_capped_at_minus_100(self):
        self.assertEqual(ts.compound_return_pct([-100.0, 5.0]), -100.0)


class TestDrawdown(unittest.TestCase):
    def test_known_drawdown(self):
        # путь: +10% → пик; затем -5%, -5% → просадка = 1 - 0.95*0.95 = 9.75%
        dd = ts.max_drawdown_from_returns([10.0, -5.0, -5.0])
        self.assertAlmostEqual(dd, -(1 - 0.95 * 0.95) * 100.0, places=10)

    def test_all_gains_zero_drawdown(self):
        self.assertEqual(ts.max_drawdown_from_returns([0.1, 0.2, 0.3]), 0.0)

    def test_empty_zero(self):
        self.assertEqual(ts.max_drawdown_from_returns([]), 0.0)


# ─── PSR ─────────────────────────────────────────────────────────────────────


class TestPSR(unittest.TestCase):
    def _expected_psr(self, vals, sr_star=0.0):
        """Независимое вычисление PSR по формуле Bailey & López de Prado."""
        n = len(vals)
        mean = statistics.fmean(vals)
        sd = statistics.pstdev(vals)
        sr = mean / sd
        m3 = sum((v - mean) ** 3 for v in vals) / n
        m4 = sum((v - mean) ** 4 for v in vals) / n
        skew = m3 / sd ** 3
        kurt = m4 / sd ** 4  # non-excess γ4
        v = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
        z = (sr - sr_star) * math.sqrt(n - 1) / math.sqrt(v)
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    def test_known_vector(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        res = ts.compute_psr(vals)
        self.assertAlmostEqual(res["psr"], round(self._expected_psr(vals), 6),
                               places=6)
        self.assertGreater(res["psr"], 0.99)
        self.assertIsNone(res["note"])

    def test_skewed_vector_matches_formula(self):
        vals = [0.5, 0.1, -0.2, 0.3, 2.0, -0.1, 0.05, 0.4, -0.3, 0.25, 0.6]
        res = ts.compute_psr(vals)
        self.assertAlmostEqual(res["psr"], round(self._expected_psr(vals), 6),
                               places=6)

    def test_psr_in_unit_interval(self):
        vals = [0.1, -0.2, 0.3, 0.05, 0.2, -0.1, 0.15, 0.4, -0.05, 0.1]
        res = ts.compute_psr(vals)
        self.assertGreaterEqual(res["psr"], 0.0)
        self.assertLessEqual(res["psr"], 1.0)

    def test_empty_none(self):
        res = ts.compute_psr([])
        self.assertIsNone(res["psr"])
        self.assertEqual(res["num_returns"], 0)
        self.assertIn("insufficient data", res["note"])

    def test_single_value_none(self):
        self.assertIsNone(ts.compute_psr([0.5])["psr"])

    def test_short_series_below_min_none_with_note(self):
        # ровно min−1 (9 < 10) → честный None + note, ничего не выдумывается
        vals = [0.1, 0.2, -0.1, 0.3, 0.05, 0.15, -0.05, 0.2, 0.1]
        self.assertEqual(len(vals), ts.PSR_MIN_RETURNS - 1)
        res = ts.compute_psr(vals)
        self.assertIsNone(res["psr"])
        self.assertIn("insufficient data", res["note"])
        self.assertEqual(res["min_returns"], ts.PSR_MIN_RETURNS)

    def test_exactly_min_returns_computed(self):
        vals = [0.1, 0.2, -0.1, 0.3, 0.05, 0.15, -0.05, 0.2, 0.1, 0.25]
        self.assertEqual(len(vals), ts.PSR_MIN_RETURNS)
        res = ts.compute_psr(vals)
        self.assertIsNotNone(res["psr"])

    def test_custom_min_returns_override(self):
        vals = [1.0, 2.0, 3.0]
        res = ts.compute_psr(vals, min_returns=3)
        self.assertAlmostEqual(res["psr"], round(self._expected_psr(vals), 6),
                               places=6)

    def test_flat_series_none(self):
        res = ts.compute_psr([0.5] * 12)
        self.assertIsNone(res["psr"])
        self.assertIsNone(res["sharpe_daily"])
        self.assertIn("zero variance", res["note"])

    def test_non_list_input(self):
        res = ts.compute_psr(None)
        self.assertIsNone(res["psr"])
        self.assertIn("invalid input", res["note"])

    def test_garbage_entries_filtered(self):
        res = ts.compute_psr(["x", True, None, 1.0])
        self.assertEqual(res["num_returns"], 1)
        self.assertIsNone(res["psr"])

    def test_benchmark_above_sharpe_gives_low_psr(self):
        vals = [0.1, 0.2, 0.15, 0.05, 0.12, 0.18, 0.07, 0.11, 0.14, 0.09]
        sr = statistics.fmean(vals) / statistics.pstdev(vals)
        res = ts.compute_psr(vals, benchmark_sr=sr + 1.0)
        self.assertLess(res["psr"], 0.5)

    def test_norm_cdf_midpoint(self):
        self.assertAlmostEqual(ts._norm_cdf(0.0), 0.5, places=12)


# ─── Exposure ────────────────────────────────────────────────────────────────


class TestExposure(unittest.TestCase):
    def test_shares_against_capital(self):
        exp = ts.build_exposure(POSITIONS_DOC, ORCH_DOC)
        self.assertTrue(exp["available"])
        self.assertAlmostEqual(exp["by_protocol"]["aave_v3"]["share_pct"], 40.0)
        self.assertAlmostEqual(exp["by_protocol"]["maple"]["share_pct"], 25.0)

    def test_cash_pct(self):
        exp = ts.build_exposure(POSITIONS_DOC, ORCH_DOC)
        self.assertAlmostEqual(exp["cash_pct"], 5.0)

    def test_tier_mapping(self):
        exp = ts.build_exposure(POSITIONS_DOC, ORCH_DOC)
        self.assertEqual(exp["by_protocol"]["aave_v3"]["tier"], "T1")
        self.assertEqual(exp["by_protocol"]["maple"]["tier"], "unknown")

    def test_tier_aggregation(self):
        exp = ts.build_exposure(POSITIONS_DOC, ORCH_DOC)
        self.assertAlmostEqual(exp["by_tier"]["T1"], 70.0)
        self.assertAlmostEqual(exp["by_tier"]["unknown"], 25.0)

    def test_missing_orchestrator_all_unknown(self):
        exp = ts.build_exposure(POSITIONS_DOC, None)
        self.assertTrue(all(i["tier"] == "unknown"
                            for i in exp["by_protocol"].values()))

    def test_garbage_positions_doc_unavailable(self):
        for doc in (None, [], "junk", {"positions": "junk"}):
            exp = ts.build_exposure(doc, ORCH_DOC)
            self.assertFalse(exp["available"], doc)

    def test_garbage_position_values_skipped(self):
        doc = {"capital_usd": 100.0,
               "positions": {"a": 50.0, "b": "x", "c": True, "d": -5.0}}
        exp = ts.build_exposure(doc, None)
        self.assertEqual(list(exp["by_protocol"]), ["a"])

    def test_no_capital_falls_back_to_sum(self):
        doc = {"positions": {"a": 75.0, "b": 25.0}}
        exp = ts.build_exposure(doc, None)
        self.assertAlmostEqual(exp["by_protocol"]["a"]["share_pct"], 75.0)


# ─── Merkle-якоря месяца ─────────────────────────────────────────────────────


class TestAnchors(unittest.TestCase):
    def test_month_filter(self):
        anchors = ts.collect_month_anchors(ANCHORS_DOC, MONTH)
        self.assertEqual([a["date"] for a in anchors],
                         ["2026-05-02", "2026-05-03"])

    def test_published_flag_honest(self):
        anchors = ts.collect_month_anchors(ANCHORS_DOC, "2026-06")
        self.assertTrue(anchors[0]["published"])
        anchors_may = ts.collect_month_anchors(ANCHORS_DOC, MONTH)
        self.assertFalse(anchors_may[0]["published"])

    def test_null_root_preserved(self):
        anchors = ts.collect_month_anchors(ANCHORS_DOC, MONTH)
        self.assertIsNone(anchors[1]["merkle_root"])

    def test_garbage_doc_empty(self):
        for doc in (None, [], "junk", {"anchors": "junk"},
                    {"anchors": [1, "x", {"date": "bad"}]}):
            self.assertEqual(ts.collect_month_anchors(doc, MONTH), [], doc)

    def test_sorted_by_date(self):
        doc = {"anchors": [{"date": "2026-05-09"}, {"date": "2026-05-01"}]}
        anchors = ts.collect_month_anchors(doc, MONTH)
        self.assertEqual([a["date"] for a in anchors],
                         ["2026-05-01", "2026-05-09"])


# ─── build_tear_sheet ────────────────────────────────────────────────────────


class TestBuildTearSheet(TearSheetBase):
    def test_sections_present(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        for section in ("meta", "performance", "risk", "exposure",
                        "incidents", "proof_of_track", "capital_ladder",
                        "notes"):
            self.assertIn(section, doc)

    def test_meta_fields(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        meta = doc["meta"]
        self.assertEqual(meta["period"], MONTH)
        self.assertIs(meta["is_demo"], False)
        self.assertIs(meta["advisory_only"], True)
        self.assertEqual(meta["source_files"], list(ts.SOURCE_FILES))
        self.assertIn("generated_at", meta)

    def test_happy_path_metrics(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        perf, risk = doc["performance"], doc["risk"]
        self.assertEqual(perf["num_days_in_month"], len(MAY_RETURNS))
        self.assertEqual(perf["num_return_days"], len(MAY_RETURNS))
        self.assertAlmostEqual(perf["net_return_pct"],
                               _compound(MAY_RETURNS), places=5)
        self.assertIsNotNone(risk["sharpe_ratio"])
        self.assertIsNotNone(risk["sortino_ratio"])
        self.assertIsNotNone(risk["psr"]["psr"])

    def test_max_drawdown_within_month(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        # после +1% пика: -1.5% → просадка -1.5% (дальше ряд восстанавливается)
        self.assertAlmostEqual(doc["risk"]["max_drawdown_pct"], -1.5, places=4)

    def test_apy_annualization(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        n = len(MAY_RETURNS)
        growth = 1.0 + _compound(MAY_RETURNS) / 100.0
        expected = (growth ** (365.0 / n) - 1.0) * 100.0
        self.assertAlmostEqual(doc["performance"]["annualized_apy_pct"],
                               expected, places=2)
        self.assertEqual(doc["performance"]["annualization_days"], 365)

    def test_incidents_detected_via_capital_ladder(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertEqual(doc["incidents"]["count"], 1)
        item = doc["incidents"]["items"][0]
        self.assertEqual(item["date"], "2026-05-02")
        # совпадает с прямым вызовом detect_incidents (переиспользование)
        bars = ts.filter_month_bars(EQUITY_DOC["daily"], MONTH)
        self.assertEqual(doc["incidents"]["items"], detect_incidents(bars))

    def test_incident_threshold_exactly_one_percent(self):
        # граница: ровно -1.0% close-to-close — это уже инцидент («≥»)
        daily = [
            {"date": "2026-04-30", "daily_return_pct": 0.0},
            {"date": "2026-05-01", "daily_return_pct": -1.0},
            {"date": "2026-05-02", "daily_return_pct": -0.999999},
        ]
        _write_json(self.data_dir / ts.EQUITY_FILENAME, {"daily": daily})
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertEqual(doc["incidents"]["count"], 1)
        self.assertEqual(doc["incidents"]["items"][0]["date"], "2026-05-01")

    def test_incidents_outside_month_excluded(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period="2026-06", data_dir=self.data_dir)
        self.assertEqual(doc["incidents"]["count"], 0)
        self.assertEqual(doc["incidents"]["items"], [])

    def test_zero_variance_sharpe_sortino_none(self):
        daily = [{"date": "2026-04-30", "daily_return_pct": 0.0}] + [
            {"date": f"2026-05-{i:02d}", "daily_return_pct": 0.5}
            for i in range(1, 13)
        ]
        _write_json(self.data_dir / ts.EQUITY_FILENAME, {"daily": daily})
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["risk"]["sharpe_ratio"])
        self.assertIsNone(doc["risk"]["psr"]["psr"])
        self.assertEqual(doc["risk"]["daily_volatility_pct"], 0.0)

    def test_short_series_psr_none_with_note(self):
        daily = [
            {"date": "2026-04-30", "daily_return_pct": 0.0},
            {"date": "2026-05-01", "daily_return_pct": 0.4},
            {"date": "2026-05-02", "daily_return_pct": -0.2},
        ]
        _write_json(self.data_dir / ts.EQUITY_FILENAME, {"daily": daily})
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["risk"]["psr"]["psr"])
        self.assertTrue(any("PSR" in n for n in doc["notes"]))

    def test_exposure_and_ladder_and_anchors(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertTrue(doc["exposure"]["available"])
        self.assertEqual(doc["capital_ladder"]["level_code"], "L0")
        self.assertEqual(doc["proof_of_track"]["anchors_count"], 2)
        self.assertEqual(doc["meta"]["track"]["days_running"], 23)
        self.assertTrue(doc["meta"]["track"]["golive_ready"])

    def test_proof_of_track_latest_root(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        # последний якорь мая — 2026-05-03 с root=None (честно)
        self.assertIsNone(doc["proof_of_track"]["latest_root"])
        doc_june = ts.build_tear_sheet(period="2026-06", data_dir=self.data_dir)
        self.assertEqual(doc_june["proof_of_track"]["latest_root"], "cd" * 32)

    def test_proof_of_track_missing_file(self):
        doc = ts.build_tear_sheet(period="2025-01", data_dir=self.data_dir)
        self.assertEqual(doc["proof_of_track"]["anchors_count"], 0)
        self.assertIsNone(doc["proof_of_track"]["latest_root"])
        self.assertTrue(
            any(ts.ANCHORS_FILENAME in n for n in doc["notes"]))

    def test_trades_counted_for_month(self):
        self.write_all_sources()
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertEqual(doc["performance"]["num_trades"], 2)

    def test_trades_missing_honest_none(self):
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["performance"]["num_trades"])
        self.assertTrue(
            any(ts.TRADES_FILENAME in n for n in doc["notes"]))

    def test_golive_missing_honest_none(self):
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["meta"]["track"]["golive_ready"])

    def test_missing_equity_honest_no_data(self):
        # equity-файла нет вовсе
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertEqual(doc["performance"]["num_days_in_month"], 0)
        self.assertIsNone(doc["performance"]["net_return_pct"])
        self.assertIsNone(doc["risk"]["sharpe_ratio"])
        self.assertIsNone(doc["risk"]["psr"]["psr"])
        self.assertTrue(
            any(ts.EQUITY_FILENAME in n for n in doc["notes"]))

    def test_corrupt_equity_file_tolerated(self):
        (self.data_dir / ts.EQUITY_FILENAME).write_text(
            "{not json!!!", encoding="utf-8")
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["performance"]["net_return_pct"])
        self.assertTrue(
            any("missing/unreadable" in n for n in doc["notes"]))

    def test_corrupt_all_sources_never_raise(self):
        for name in ts.SOURCE_FILES:
            (self.data_dir / name).write_text("garbage{{{", encoding="utf-8")
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertEqual(doc["meta"]["period"], MONTH)
        self.assertFalse(doc["exposure"]["available"])
        self.assertIsNone(doc["capital_ladder"])

    def test_default_period_is_current_utc_month(self):
        doc = ts.build_tear_sheet(data_dir=self.data_dir)
        self.assertEqual(doc["meta"]["period"], ts.current_month_utc())

    def test_ladder_missing_noted(self):
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIsNone(doc["capital_ladder"])
        self.assertTrue(
            any(ts.LADDER_STATUS_FILENAME in n for n in doc["notes"]))

    def test_disclaimer_present(self):
        doc = ts.build_tear_sheet(period=MONTH, data_dir=self.data_dir)
        self.assertIn("NOT investment advice", doc["meta"]["disclaimer"])


# ─── запись выходов / markdown ───────────────────────────────────────────────


class TestOutputs(TearSheetBase):
    def _run(self, month=MONTH):
        doc = ts.build_tear_sheet(period=month, data_dir=self.data_dir)
        return ts.write_outputs(doc, data_dir=self.data_dir,
                                reports_dir=self.reports_dir)

    def test_run_writes_both_files(self):
        self.write_all_sources()
        paths = self._run()
        self.assertTrue(Path(paths["json"]).exists())
        self.assertTrue(Path(paths["markdown"]).exists())
        self.assertEqual(Path(paths["json"]).name, "tear_sheet_latest.json")
        self.assertEqual(Path(paths["markdown"]).name,
                         f"tear_sheet_{MONTH}.md")
        self.assertTrue(paths["changed"])

    def test_no_tmp_leftovers(self):
        self.write_all_sources()
        self._run()
        self.no_tmp_leftovers()

    def test_json_output_valid_and_machine_readable(self):
        self.write_all_sources()
        paths = self._run()
        doc = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["source"], "tear_sheet")
        self.assertEqual(doc["schema_version"], ts.SCHEMA_VERSION)
        self.assertEqual(doc["meta"]["period"], MONTH)

    def test_markdown_expected_sections(self):
        self.write_all_sources()
        paths = self._run()
        md = Path(paths["markdown"]).read_text(encoding="utf-8")
        for section in (
            f"# SPA — Публичный tear-sheet за {MONTH}",
            "Дисклеймер",
            "## Метрики",
            "## Exposure (на конец месяца)",
            "## Инциденты",
            "## Proof-of-Track (Merkle roots)",
            "## Capital Ladder",
        ):
            self.assertIn(section, md)

    def test_markdown_contains_merkle_root_and_incident(self):
        self.write_all_sources()
        paths = self._run()
        md = Path(paths["markdown"]).read_text(encoding="utf-8")
        self.assertIn("ab" * 32, md)
        self.assertIn("2026-05-02", md)

    def test_markdown_honest_no_data_on_empty(self):
        paths = self._run()
        md = Path(paths["markdown"]).read_text(encoding="utf-8")
        self.assertIn("н/д", md)
        self.assertIn("нет данных", md)

    def test_markdown_no_raw_none(self):
        # отсутствующие метрики — «н/д», сырой 'None' в markdown недопустим
        for build in (lambda: self._run(),):
            paths = build()
            md = Path(paths["markdown"]).read_text(encoding="utf-8")
            self.assertNotIn("None", md)
        self.write_all_sources()
        paths = self._run("2026-06")
        md = Path(paths["markdown"]).read_text(encoding="utf-8")
        self.assertNotIn("None", md)

    def test_idempotent_rerun_single_file_per_month(self):
        self.write_all_sources()
        self._run()
        paths = self._run()
        md_files = list(self.reports_dir.glob("*.md"))
        self.assertEqual(len(md_files), 1)
        doc = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["meta"]["period"], MONTH)
        self.no_tmp_leftovers()

    def test_idempotent_rerun_byte_identical(self):
        # повторный прогон того же месяца с теми же данными
        # байт-в-байт не меняет ни JSON, ни markdown
        self.write_all_sources()
        p1 = self._run()
        json_bytes = Path(p1["json"]).read_bytes()
        md_bytes = Path(p1["markdown"]).read_bytes()
        p2 = self._run()
        self.assertFalse(p2["changed"])
        self.assertEqual(Path(p2["json"]).read_bytes(), json_bytes)
        self.assertEqual(Path(p2["markdown"]).read_bytes(), md_bytes)

    def test_generated_at_preserved_when_unchanged(self):
        self.write_all_sources()
        p1 = self._run()
        gen1 = json.loads(Path(p1["json"]).read_text(encoding="utf-8"))[
            "meta"]["generated_at"]
        p2 = self._run()
        gen2 = json.loads(Path(p2["json"]).read_text(encoding="utf-8"))[
            "meta"]["generated_at"]
        self.assertEqual(gen1, gen2)

    def test_changed_data_updates_file_and_history(self):
        self.write_all_sources()
        self._run()
        doc1 = json.loads(
            (self.data_dir / ts.STATUS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(doc1["history"]), 1)
        # данные меняются → контент другой → history растёт
        changed = dict(POSITIONS_DOC)
        changed["positions"] = {"aave_v3": 95000.0}
        _write_json(self.data_dir / ts.POSITIONS_FILENAME, changed)
        self._run()
        doc2 = json.loads(
            (self.data_dir / ts.STATUS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(doc2["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self.write_all_sources()
        # предзаполняем статус с history на пределе и ДРУГИМ контентом
        stale = {"meta": {"period": "2020-01"},
                 "history": [{"period": "2020-01", "n": i} for i in range(520)]}
        _write_json(self.data_dir / ts.STATUS_FILENAME, stale)
        self._run()
        doc = json.loads(
            (self.data_dir / ts.STATUS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(doc["history"]), ts.HISTORY_MAX)
        # последняя запись — свежий прогон
        self.assertEqual(doc["history"][-1]["period"], MONTH)

    def test_corrupt_previous_status_tolerated(self):
        self.write_all_sources()
        (self.data_dir / ts.STATUS_FILENAME).write_text(
            "{broken json", encoding="utf-8")
        paths = self._run()
        self.assertTrue(paths["changed"])
        doc = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["meta"]["period"], MONTH)
        self.assertEqual(len(doc["history"]), 1)

    def test_md_recreated_if_deleted_even_unchanged(self):
        self.write_all_sources()
        p1 = self._run()
        Path(p1["markdown"]).unlink()
        p2 = self._run()
        self.assertFalse(p2["changed"])
        self.assertTrue(Path(p2["markdown"]).exists())

    def test_content_fingerprint_ignores_volatile(self):
        a = {"meta": {"period": MONTH, "generated_at": "t1"},
             "history": [1], "x": 1}
        b = {"meta": {"period": MONTH, "generated_at": "t2"},
             "history": [2], "x": 1}
        self.assertEqual(ts.content_fingerprint(a), ts.content_fingerprint(b))
        c = dict(a, x=2)
        self.assertNotEqual(ts.content_fingerprint(a), ts.content_fingerprint(c))
        self.assertNotEqual(ts.content_fingerprint(None), ts.content_fingerprint(a))

    def test_two_months_two_files(self):
        self.write_all_sources()
        self._run(MONTH)
        self._run("2026-06")
        names = sorted(p.name for p in self.reports_dir.glob("*.md"))
        self.assertEqual(names,
                         ["tear_sheet_2026-05.md", "tear_sheet_2026-06.md"])


# ─── trades count ────────────────────────────────────────────────────────────


class TestTradesCount(unittest.TestCase):
    def test_counts_only_month(self):
        self.assertEqual(ts.count_month_trades(TRADES_DOC, MONTH), 2)
        self.assertEqual(ts.count_month_trades(TRADES_DOC, "2026-06"), 1)

    def test_dict_wrapper_supported(self):
        self.assertEqual(
            ts.count_month_trades({"trades": TRADES_DOC}, MONTH), 2)

    def test_missing_none(self):
        self.assertIsNone(ts.count_month_trades(None, MONTH))

    def test_garbage_doc_none(self):
        self.assertIsNone(ts.count_month_trades("junk", MONTH))
        self.assertIsNone(ts.count_month_trades({"trades": "junk"}, MONTH))

    def test_garbage_entries_skipped(self):
        doc = [42, "x", None, {"no_ts": 1},
               {"ts": "2026-05-09T00:00:00+00:00"}]
        self.assertEqual(ts.count_month_trades(doc, MONTH), 1)

    def test_timestamp_field_fallback(self):
        doc = [{"timestamp": "2026-05-01T00:00:00+00:00"}]
        self.assertEqual(ts.count_month_trades(doc, MONTH), 1)

    def test_empty_list_zero(self):
        self.assertEqual(ts.count_month_trades([], MONTH), 0)


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(TearSheetBase):
    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ts.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_check_default_exit0_empty_data(self):
        rc, out, err = self._main(
            ["--month", MONTH, "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        json.loads(out)  # печатает валидный JSON

    def test_check_does_not_write(self):
        self.write_all_sources()
        rc, _, _ = self._main(
            ["--check", "--month", MONTH, "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / ts.STATUS_FILENAME).exists())
        self.assertFalse(self.reports_dir.exists())

    def test_run_exit0_writes_files(self):
        self.write_all_sources()
        rc, out, err = self._main(
            ["--run", "--month", MONTH, "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("written", out)
        self.assertTrue((self.data_dir / ts.STATUS_FILENAME).exists())
        self.assertTrue(
            (self.reports_dir / f"tear_sheet_{MONTH}.md").exists())

    def test_run_twice_idempotent(self):
        self.write_all_sources()
        for _ in range(2):
            rc, _, err = self._main(
                ["--run", "--month", MONTH, "--data-dir", str(self.data_dir),
                 "--reports-dir", str(self.reports_dir)])
            self.assertEqual(rc, 0)
            self.assertNotIn("Traceback", err)
        self.assertEqual(len(list(self.reports_dir.glob("*.md"))), 1)
        self.no_tmp_leftovers()

    def test_run_empty_data_exit0(self):
        rc, _, err = self._main(
            ["--run", "--month", MONTH, "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)

    def test_garbage_month_exit0_stderr(self):
        rc, _, err = self._main(
            ["--run", "--month", "garbage", "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)
        # ничего не записано
        self.assertFalse((self.data_dir / ts.STATUS_FILENAME).exists())
        self.assertFalse(self.reports_dir.exists())

    def test_subprocess_no_traceback(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.reporting.tear_sheet",
             "--check", "--month", MONTH,
             "--data-dir", str(self.data_dir),
             "--reports-dir", str(self.reports_dir)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)


# ─── гигиена ─────────────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    FORBIDDEN_PREFIXES = (
        "anthropic", "openai", "langchain", "litellm",
        "google.generativeai", "requests", "web3", "urllib.request",
        "socket", "http.client", "pandas", "numpy",
    )

    def _imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
        return mods

    def test_no_forbidden_imports(self):
        for mod in self._imports():
            for bad in self.FORBIDDEN_PREFIXES:
                self.assertFalse(
                    mod == bad or mod.startswith(bad + "."),
                    f"forbidden import {mod}",
                )

    def test_llm_forbidden_lint_clean(self):
        # тот же AST-сканер, что в CI (как в test_proof_of_track)
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(
            MODULE_PATH.read_text(encoding="utf-8"), "tear_sheet.py")
        self.assertEqual(violations, [])

    def test_reuses_capital_ladder_and_risk_metrics(self):
        mods = self._imports()
        self.assertIn("spa_core.governance.capital_ladder", mods)
        self.assertIn("spa_core.paper_trading.risk_metrics", mods)

    def test_disclaimer_mentions_paper_track(self):
        self.assertIn("Paper track", ts.DISCLAIMER)

    def test_constants(self):
        self.assertEqual(ts.STATUS_FILENAME, "tear_sheet_latest.json")
        self.assertEqual(ts.MD_FILENAME_TPL.format(month="2026-06"),
                         "tear_sheet_2026-06.md")
        self.assertEqual(ts.HISTORY_MAX, 500)
        self.assertEqual(ts.PSR_MIN_RETURNS, 10)
        self.assertEqual(ts.TRADES_FILENAME, "trades.json")


if __name__ == "__main__":
    unittest.main()
