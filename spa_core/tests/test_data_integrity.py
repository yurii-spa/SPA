"""Tests for spa_core.audit.data_integrity (Data Integrity Sentinel, SPA-V430).

Run with: python3 -m unittest spa_core.tests.test_data_integrity -v

Чистый unittest (НЕ pytest), БЕЗ сети, вся персистентность — в tempdir.
Покрытие (60+ кейсов):
  - equity_continuity: ok/warn/fail/skip, gap ровно 2 дня → warn, >2 → fail,
    дубли/невозрастание → fail, is_demo (бар и верхний уровень) → fail,
    нечисловые equity → warn;
  - positions_consistency: границы допусков РОВНО 0.5% (ok) / РОВНО 2% (warn),
    отрицательные позиции → fail, отсутствующий capital/cash → warn;
  - allocation_policy_bounds: cap T1 0.40 / строгий T2 0.20 для unknown,
    сумма весов > 1+1e-6 → fail, отрицательный/нечисловой вес;
  - freshness: age ровно T → ok, чуть больше → warn, ровно 2T → warn,
    больше 2T → fail, битый timestamp → warn, Z-суффикс, ключ timestamp;
  - anchor_coverage: исключение сегодняшнего UTC-дня и дней до
    real_track_start, отсутствующий якорь → warn, discrepancy → fail;
  - schema_sanity: битый JSON / не тот верхний тип / *.tmp-огрызки → fail;
  - агрегация: fail > warn > ok, skip НЕ ухудшает, counts, advisory-поля,
    никогда не raise на мусоре;
  - персист: атомарность (нет *.tmp), идемпотентность --run ×2 байт-в-байт,
    ротация истории ровно 500, битый статус-файл толерантен;
  - CLI: --check не пишет, --run пишет, exit 0 всегда, мусорные аргументы →
    ERROR в stderr без трейсбека;
  - гигиена: нет импортов LLM SDK / web3 / requests / сети (через
    find_forbidden_imports из spa_core/ci/llm_forbidden_lint.py).
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.audit import data_integrity as di

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)  # «сегодня» = 2026-06-12


def _bar(date: str, close: float = 100000.0, **extra) -> dict:
    bar = {"date": date, "close_equity": close, "equity": close,
           "daily_return_pct": 0.01}
    bar.update(extra)
    return bar


def _equity_doc(*bars: dict, **top) -> dict:
    doc = {"source": "cycle_runner", "is_demo": False, "daily": list(bars)}
    doc.update(top)
    return doc


def _positions_doc(positions: dict, capital: float = 100000.0,
                   cash: float = 0.0, **extra) -> dict:
    doc = {"capital_usd": capital, "cash_usd": cash, "positions": positions}
    doc.update(extra)
    return doc


def _orch_doc(**tiers: str) -> dict:
    return {"adapters": [{"protocol": p, "tier": t} for p, t in tiers.items()]}


def _run_cli(args: list) -> tuple:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = di.main(args)
    return code, stdout.getvalue(), stderr.getvalue()


class _TmpDirCase(unittest.TestCase):
    """База: изолированный data_dir в tempdir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="spa_di_test_")
        self.ddir = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name: str, obj) -> Path:
        path = self.ddir / name
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return path

    def write_raw(self, name: str, text: str) -> Path:
        path = self.ddir / name
        path.write_text(text, encoding="utf-8")
        return path


# ─── Чек 1: equity_continuity ────────────────────────────────────────────────


class TestEquityContinuity(unittest.TestCase):
    def test_missing_doc_skip(self):
        res = di.check_equity_continuity(None)
        self.assertEqual(res["status"], "skip")

    def test_skip_has_note(self):
        res = di.check_equity_continuity(None)
        self.assertTrue(any("missing" in n for n in res["notes"]))

    def test_no_daily_section_skip(self):
        res = di.check_equity_continuity({"source": "cycle_runner"})
        self.assertEqual(res["status"], "skip")

    def test_ok_consecutive_days(self):
        doc = _equity_doc(_bar("2026-06-10"), _bar("2026-06-11"),
                          _bar("2026-06-12"))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["details"]["bars"], 3)

    def test_single_bar_ok(self):
        res = di.check_equity_continuity(_equity_doc(_bar("2026-06-10")))
        self.assertEqual(res["status"], "ok")

    def test_empty_daily_ok_with_note(self):
        res = di.check_equity_continuity(_equity_doc())
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("empty" in n for n in res["notes"]))

    def test_gap_exactly_2_days_warn(self):
        doc = _equity_doc(_bar("2026-06-10"), _bar("2026-06-12"))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "warn")
        self.assertEqual(len(res["details"]["gaps_warn"]), 1)

    def test_gap_3_days_fail(self):
        doc = _equity_doc(_bar("2026-06-10"), _bar("2026-06-13"))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["details"]["gaps_fail"][0]["days"], 3)

    def test_duplicate_dates_fail(self):
        doc = _equity_doc(_bar("2026-06-10"), _bar("2026-06-10"))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "fail")
        self.assertIn("2026-06-10", res["details"]["duplicates"])

    def test_dates_decreasing_fail(self):
        doc = _equity_doc(_bar("2026-06-11"), _bar("2026-06-10"))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "fail")
        self.assertTrue(res["details"]["order_violations"])

    def test_is_demo_bar_fail(self):
        doc = _equity_doc(_bar("2026-06-10"), _bar("2026-06-11", is_demo=True))
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "fail")
        self.assertIn("2026-06-11", res["details"]["demo_bars"])

    def test_top_level_is_demo_fail(self):
        doc = _equity_doc(_bar("2026-06-10"), is_demo=True)
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "fail")

    def test_non_numeric_equity_warn(self):
        doc = _equity_doc(
            _bar("2026-06-10"),
            {"date": "2026-06-11", "close_equity": "garbage", "equity": None},
        )
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "warn")
        self.assertIn("2026-06-11", res["details"]["non_numeric_equity"])

    def test_invalid_bar_date_warn(self):
        doc = _equity_doc(_bar("2026-06-10"), {"date": "not-a-date"})
        res = di.check_equity_continuity(doc)
        self.assertEqual(res["status"], "warn")


# ─── Чек 2: positions_consistency ────────────────────────────────────────────


class TestPositionsConsistency(unittest.TestCase):
    def test_missing_doc_skip(self):
        res = di.check_positions_consistency(None)
        self.assertEqual(res["status"], "skip")
        self.assertTrue(res["notes"])

    def test_exact_sum_ok(self):
        doc = _positions_doc({"aave_v3": 60000.0, "maple": 35000.0}, cash=5000.0)
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "ok")
        self.assertAlmostEqual(res["details"]["deviation_pct"], 0.0)

    def test_deviation_exactly_0_5_pct_ok(self):
        # 99000 + 1500 = 100500 → отклонение РОВНО 0.5% → ещё ok (граница).
        doc = _positions_doc({"aave_v3": 99000.0}, cash=1500.0)
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "ok")

    def test_deviation_1_pct_warn(self):
        doc = _positions_doc({"aave_v3": 99000.0}, cash=2000.0)  # 101000 → 1%
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")

    def test_deviation_exactly_2_pct_warn(self):
        # 102000 → отклонение РОВНО 2% → ещё warn (граница).
        doc = _positions_doc({"aave_v3": 100000.0}, cash=2000.0)
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")

    def test_deviation_over_2_pct_fail(self):
        doc = _positions_doc({"aave_v3": 100000.0}, cash=2100.0)  # 2.1%
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "fail")

    def test_negative_position_fail(self):
        doc = _positions_doc({"aave_v3": 100500.0, "maple": -500.0})
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "fail")
        self.assertIn("maple", res["details"]["negative_positions"])

    def test_missing_capital_warn(self):
        doc = {"cash_usd": 0.0, "positions": {"aave_v3": 1.0}}
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")
        self.assertIsNone(res["details"]["deviation_pct"])

    def test_missing_cash_warn_note(self):
        doc = {"capital_usd": 100000.0, "positions": {"aave_v3": 100000.0}}
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")
        self.assertTrue(any("cash_usd" in n for n in res["notes"]))

    def test_non_numeric_position_warn(self):
        doc = _positions_doc({"aave_v3": 100000.0, "maple": "oops"})
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")

    def test_positions_not_dict_warn(self):
        doc = {"capital_usd": 100000.0, "cash_usd": 100000.0, "positions": [1, 2]}
        res = di.check_positions_consistency(doc)
        self.assertEqual(res["status"], "warn")


# ─── Чек 3: allocation_policy_bounds ─────────────────────────────────────────


class TestAllocationPolicyBounds(unittest.TestCase):
    def test_missing_doc_skip(self):
        res = di.check_allocation_policy_bounds(None, None)
        self.assertEqual(res["status"], "skip")

    def test_no_target_weights_skip(self):
        res = di.check_allocation_policy_bounds({"foo": 1}, None)
        self.assertEqual(res["status"], "skip")

    def test_within_caps_ok(self):
        alloc = {"target_weights": {"aave_v3": 0.35, "yearn_v3": 0.15}}
        res = di.check_allocation_policy_bounds(
            alloc, _orch_doc(aave_v3="T1", yearn_v3="T2"))
        self.assertEqual(res["status"], "ok")

    def test_t1_weight_at_cap_ok(self):
        alloc = {"target_weights": {"aave_v3": 0.40}}
        res = di.check_allocation_policy_bounds(alloc, _orch_doc(aave_v3="T1"))
        self.assertEqual(res["status"], "ok")

    def test_t1_weight_above_cap_fail(self):
        alloc = {"target_weights": {"aave_v3": 0.41}}
        res = di.check_allocation_policy_bounds(alloc, _orch_doc(aave_v3="T1"))
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["details"]["violations"][0]["kind"], "cap_exceeded")

    def test_unknown_tier_strict_t2_cap_fail(self):
        alloc = {"target_weights": {"mystery": 0.25}}
        res = di.check_allocation_policy_bounds(alloc, _orch_doc(aave_v3="T1"))
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["details"]["weights"]["mystery"]["tier"], "unknown")

    def test_unknown_tier_at_t2_cap_ok(self):
        alloc = {"target_weights": {"mystery": 0.20}}
        res = di.check_allocation_policy_bounds(alloc, None)
        self.assertEqual(res["status"], "ok")

    def test_t2_weight_above_cap_fail(self):
        alloc = {"target_weights": {"yearn_v3": 0.21}}
        res = di.check_allocation_policy_bounds(alloc, _orch_doc(yearn_v3="T2"))
        self.assertEqual(res["status"], "fail")

    def test_sum_above_one_fail(self):
        alloc = {"target_weights": {"a": 0.35, "b": 0.35, "c": 0.35}}
        res = di.check_allocation_policy_bounds(
            alloc, _orch_doc(a="T1", b="T1", c="T1"))
        self.assertEqual(res["status"], "fail")
        self.assertTrue(any("sum of weights" in n for n in res["notes"]))

    def test_sum_exactly_one_ok(self):
        alloc = {"target_weights": {"a": 0.40, "b": 0.20, "c": 0.20, "d": 0.20}}
        res = di.check_allocation_policy_bounds(
            alloc, _orch_doc(a="T1", b="T2", c="T2", d="T2"))
        self.assertEqual(res["status"], "ok")

    def test_orch_missing_noted(self):
        alloc = {"target_weights": {"a": 0.10}}
        res = di.check_allocation_policy_bounds(alloc, None)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("unknown" in n for n in res["notes"]))

    def test_negative_weight_fail(self):
        alloc = {"target_weights": {"a": -0.1}}
        res = di.check_allocation_policy_bounds(alloc, None)
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["details"]["violations"][0]["kind"], "negative_weight")

    def test_non_numeric_weight_warn(self):
        alloc = {"target_weights": {"a": "lots"}}
        res = di.check_allocation_policy_bounds(alloc, None)
        self.assertEqual(res["status"], "warn")


# ─── Чек 4: freshness ────────────────────────────────────────────────────────


class TestFreshness(_TmpDirCase):
    def _write_ts(self, name: str, age_hours: float, key: str = "generated_at"):
        ts = (NOW - timedelta(hours=age_hours)).isoformat()
        self.write(name, {key: ts})

    def test_all_missing_skip(self):
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "skip")

    def test_fresh_ok(self):
        for name in di.FRESHNESS_THRESHOLDS_HOURS:
            self._write_ts(name, 1.0)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_age_exactly_threshold_ok(self):
        self._write_ts(di.ORCH_STATUS_FILENAME, 26.0)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_just_over_threshold_warn(self):
        self._write_ts(di.ORCH_STATUS_FILENAME, 26.5)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "warn")

    def test_age_exactly_2x_threshold_warn(self):
        self._write_ts(di.ORCH_STATUS_FILENAME, 52.0)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "warn")

    def test_over_2x_threshold_fail(self):
        self._write_ts(di.ORCH_STATUS_FILENAME, 52.5)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "fail")

    def test_risk_scores_48h_threshold(self):
        self._write_ts(di.RISK_SCORES_FILENAME, 47.0)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_broken_timestamp_warn(self):
        self.write(di.ORCH_STATUS_FILENAME, {"generated_at": "not-a-timestamp"})
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "warn")

    def test_missing_timestamp_key_warn(self):
        self.write(di.ORCH_STATUS_FILENAME, {"foo": "bar"})
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "warn")

    def test_z_suffix_parsed_ok(self):
        ts = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write(di.RISK_SCORES_FILENAME, {"generated_at": ts})
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_golive_timestamp_key_accepted(self):
        self._write_ts(di.GOLIVE_STATUS_FILENAME, 1.0, key="timestamp")
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_paper_trading_last_cycle_ts_accepted(self):
        self._write_ts(di.PT_STATUS_FILENAME, 1.0, key="last_cycle_ts")
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")

    def test_missing_files_do_not_worsen_present_ok(self):
        self._write_ts(di.ORCH_STATUS_FILENAME, 1.0)
        res = di.check_freshness(self.ddir, NOW)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("missing" in n for n in res["notes"]))


# ─── Чек 5: anchor_coverage ──────────────────────────────────────────────────


def _anchor(date: str, note: str = "on-chain publication pending") -> dict:
    return {"date": date, "merkle_root": "ab" * 32, "leaf_count": 1,
            "published": False, "tx_hash": None, "note": note}


class TestAnchorCoverage(unittest.TestCase):
    EQUITY = _equity_doc(_bar("2026-06-10"), _bar("2026-06-11"),
                         _bar("2026-06-12"))

    def test_anchors_missing_skip(self):
        res = di.check_anchor_coverage(self.EQUITY, None, NOW)
        self.assertEqual(res["status"], "skip")

    def test_equity_missing_skip(self):
        res = di.check_anchor_coverage(None, {"anchors": []}, NOW)
        self.assertEqual(res["status"], "skip")

    def test_anchors_not_a_list_skip(self):
        res = di.check_anchor_coverage(self.EQUITY, {"anchors": "junk"}, NOW)
        self.assertEqual(res["status"], "skip")

    def test_full_coverage_ok(self):
        anchors = {"anchors": [_anchor("2026-06-10"), _anchor("2026-06-11")]}
        res = di.check_anchor_coverage(self.EQUITY, anchors, NOW)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["details"]["required_days"],
                         ["2026-06-10", "2026-06-11"])

    def test_missing_day_warn(self):
        anchors = {"anchors": [_anchor("2026-06-11")]}
        res = di.check_anchor_coverage(self.EQUITY, anchors, NOW)
        self.assertEqual(res["status"], "warn")
        self.assertEqual(res["details"]["missing_days"], ["2026-06-10"])

    def test_today_utc_excluded(self):
        # Бар 2026-06-12 == «сегодня» по NOW → якорь за него НЕ требуется.
        anchors = {"anchors": [_anchor("2026-06-10"), _anchor("2026-06-11")]}
        res = di.check_anchor_coverage(self.EQUITY, anchors, NOW)
        self.assertNotIn("2026-06-12", res["details"]["required_days"])

    def test_days_before_track_start_excluded(self):
        equity = _equity_doc(_bar("2026-06-08"), _bar("2026-06-09"),
                             _bar("2026-06-10"), _bar("2026-06-11"))
        anchors = {"anchors": [_anchor("2026-06-10"), _anchor("2026-06-11")]}
        res = di.check_anchor_coverage(equity, anchors, NOW)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["details"]["required_days"],
                         ["2026-06-10", "2026-06-11"])

    def test_discrepancy_note_fail(self):
        anchors = {"anchors": [
            _anchor("2026-06-10"),
            _anchor("2026-06-11",
                    note="pending; discrepancy: recomputed root 'x' != anchored"),
        ]}
        res = di.check_anchor_coverage(self.EQUITY, anchors, NOW)
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["details"]["discrepancy_days"], ["2026-06-11"])

    def test_no_completed_days_ok_note(self):
        equity = _equity_doc(_bar("2026-06-12"))  # только сегодняшний бар
        res = di.check_anchor_coverage(equity, {"anchors": []}, NOW)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("no completed" in n for n in res["notes"]))


# ─── Чек 6: schema_sanity ────────────────────────────────────────────────────


class TestSchemaSanity(_TmpDirCase):
    def test_empty_dir_skip(self):
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "skip")

    def test_all_valid_ok(self):
        for name in di.EXPECTED_TOP_TYPES:
            self.write(name, {"x": 1})
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "ok")

    def test_unparseable_json_fail(self):
        self.write_raw(di.EQUITY_FILENAME, "{not json!!!")
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "fail")
        self.assertTrue(any("unparseable" in n for n in res["notes"]))

    def test_wrong_top_type_fail(self):
        self.write(di.POSITIONS_FILENAME, [1, 2, 3])  # ожидается dict
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "fail")

    def test_tmp_leftover_fail(self):
        self.write(di.EQUITY_FILENAME, {"daily": []})
        self.write_raw(".equity_curve_daily.json.abc123.tmp", "{half-writ")
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "fail")
        self.assertTrue(res["details"]["tmp_files"])

    def test_tmp_alone_fail_even_without_artifacts(self):
        self.write_raw("stray.tmp", "junk")
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "fail")

    def test_missing_files_noted_not_fail(self):
        self.write(di.EQUITY_FILENAME, {"daily": []})
        res = di.check_schema_sanity(self.ddir)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("missing" in n for n in res["notes"]))


# ─── Агрегация ───────────────────────────────────────────────────────────────


class TestAggregation(_TmpDirCase):
    def test_empty_dir_all_skip_verdict_ok(self):
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertEqual(doc["verdict"], "ok")
        self.assertEqual(doc["counts"]["skip"], 6)
        self.assertEqual(doc["counts"]["fail"], 0)

    def test_six_checks_present(self):
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        names = [c["check"] for c in doc["checks"]]
        self.assertEqual(names, [
            "equity_continuity", "positions_consistency",
            "allocation_policy_bounds", "freshness", "anchor_coverage",
            "schema_sanity",
        ])

    def test_counts_sum_to_six(self):
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertEqual(sum(doc["counts"].values()), 6)

    def test_advisory_fields(self):
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertIs(doc["advisory_only"], True)
        self.assertEqual(doc["execution_mode"], "read_only")
        self.assertIn("generated_at", doc)

    def test_warn_verdict(self):
        # Только positions с отклонением 1% → warn; остальное skip.
        self.write(di.POSITIONS_FILENAME,
                   _positions_doc({"aave_v3": 99000.0}, cash=2000.0))
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertEqual(doc["verdict"], "warn")

    def test_fail_beats_warn(self):
        self.write(di.POSITIONS_FILENAME,
                   _positions_doc({"aave_v3": 99000.0}, cash=2000.0))  # warn
        self.write(di.EQUITY_FILENAME,
                   _equity_doc(_bar("2026-06-10", is_demo=True)))      # fail
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertEqual(doc["verdict"], "fail")

    def test_skip_does_not_worsen_ok(self):
        # Один реальный ok-чек + остальные skip → вердикт ok.
        self.write(di.POSITIONS_FILENAME,
                   _positions_doc({"aave_v3": 95000.0}, cash=5000.0))
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        self.assertEqual(doc["verdict"], "ok")

    def test_never_raises_on_corrupt_inputs(self):
        for name in di.EXPECTED_TOP_TYPES:
            self.write_raw(name, "TOTAL{{{garbage")
        doc = di.run_integrity_checks(self.tmp, now=NOW)  # не должен raise
        self.assertEqual(doc["verdict"], "fail")  # schema_sanity ловит мусор

    def test_never_raises_on_weird_data_dir(self):
        weird = self.ddir / "im_a_file_not_a_dir"
        weird.write_text("x", encoding="utf-8")
        doc = di.run_integrity_checks(str(weird), now=NOW)  # не должен raise
        self.assertIn(doc["verdict"], ("ok", "warn", "fail"))

    def test_naive_now_treated_as_utc(self):
        doc = di.run_integrity_checks(self.tmp,
                                      now=datetime(2026, 6, 12, 12, 0, 0))
        self.assertEqual(doc["verdict"], "ok")

    def test_worst_helper_ranking(self):
        self.assertEqual(di._worst("ok", "warn", "fail"), "fail")
        self.assertEqual(di._worst("ok", "warn"), "warn")
        self.assertEqual(di._worst("skip", "skip"), "ok")
        self.assertEqual(di._worst("skip", "fail"), "fail")


# ─── Персист ─────────────────────────────────────────────────────────────────


class TestPersistence(_TmpDirCase):
    def test_run_writes_status_file(self):
        doc = di.run_integrity_checks(self.tmp, now=NOW)
        out = di.write_status(doc, data_dir=self.tmp)
        self.assertTrue(out["changed"])
        self.assertTrue((self.ddir / di.STATUS_FILENAME).is_file())

    def test_status_file_schema(self):
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        saved = json.loads((self.ddir / di.STATUS_FILENAME)
                           .read_text(encoding="utf-8"))
        for key in ("generated_at", "verdict", "checks", "counts",
                    "advisory_only", "execution_mode", "history"):
            self.assertIn(key, saved)
        self.assertEqual(len(saved["history"]), 1)

    def test_idempotent_second_write_unchanged(self):
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        first = (self.ddir / di.STATUS_FILENAME).read_bytes()
        doc2 = di.run_integrity_checks(self.tmp,
                                       now=NOW + timedelta(minutes=5))
        out = di.write_status(doc2, data_dir=self.tmp)
        self.assertFalse(out["changed"])
        self.assertEqual((self.ddir / di.STATUS_FILENAME).read_bytes(), first)

    def test_generated_at_preserved_when_unchanged(self):
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        di.write_status(
            di.run_integrity_checks(self.tmp, now=NOW + timedelta(hours=1)),
            data_dir=self.tmp)
        saved = json.loads((self.ddir / di.STATUS_FILENAME)
                           .read_text(encoding="utf-8"))
        self.assertEqual(saved["generated_at"], NOW.isoformat())

    def test_history_appends_on_content_change(self):
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        self.write(di.POSITIONS_FILENAME,
                   _positions_doc({"aave_v3": 95000.0}, cash=5000.0))
        di.write_status(
            di.run_integrity_checks(self.tmp, now=NOW + timedelta(hours=1)),
            data_dir=self.tmp)
        saved = json.loads((self.ddir / di.STATUS_FILENAME)
                           .read_text(encoding="utf-8"))
        self.assertEqual(len(saved["history"]), 2)

    def test_history_rotation_500(self):
        prev = {
            "schema_version": di.SCHEMA_VERSION,
            "source": di.SOURCE_NAME,
            "generated_at": "2026-06-01T00:00:00+00:00",
            "verdict": "fail",  # другой fingerprint, чем у пустой папки
            "counts": {"ok": 0, "warn": 0, "fail": 6, "skip": 0},
            "checks": [{"check": "old", "status": "fail"}],
            "advisory_only": True,
            "execution_mode": "read_only",
            "history": [
                {"generated_at": f"old-{i}", "verdict": "ok", "counts": {}}
                for i in range(500)
            ],
        }
        self.write(di.STATUS_FILENAME, prev)
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        saved = json.loads((self.ddir / di.STATUS_FILENAME)
                           .read_text(encoding="utf-8"))
        self.assertEqual(len(saved["history"]), 500)
        self.assertEqual(saved["history"][-1]["generated_at"], NOW.isoformat())
        self.assertEqual(saved["history"][0]["generated_at"], "old-1")

    def test_broken_existing_status_tolerated(self):
        self.write_raw(di.STATUS_FILENAME, "{broken!!!")
        out = di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                              data_dir=self.tmp)
        self.assertTrue(out["changed"])
        saved = json.loads((self.ddir / di.STATUS_FILENAME)
                           .read_text(encoding="utf-8"))
        self.assertEqual(len(saved["history"]), 1)

    def test_no_tmp_leftovers_after_write(self):
        di.write_status(di.run_integrity_checks(self.tmp, now=NOW),
                        data_dir=self.tmp)
        self.assertEqual(list(self.ddir.glob("*.tmp")), [])

    def test_fingerprint_ignores_generated_at_and_age_hours(self):
        d1 = {"generated_at": "a", "checks": [{"age_hours": 1.0, "x": 1}],
              "history": [1]}
        d2 = {"generated_at": "b", "checks": [{"age_hours": 9.9, "x": 1}],
              "history": [2, 3]}
        self.assertEqual(di.content_fingerprint(d1), di.content_fingerprint(d2))

    def test_fingerprint_detects_real_change(self):
        d1 = {"verdict": "ok"}
        d2 = {"verdict": "fail"}
        self.assertNotEqual(di.content_fingerprint(d1),
                            di.content_fingerprint(d2))

    def test_fingerprint_invalid_input(self):
        self.assertEqual(di.content_fingerprint(None), "<invalid>")


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpDirCase):
    def test_check_does_not_write_exit_0(self):
        code, out, _ = _run_cli(["--check", "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertFalse((self.ddir / di.STATUS_FILENAME).exists())
        doc = json.loads(out)
        self.assertEqual(doc["source"], "data_integrity")

    def test_default_mode_is_check(self):
        code, out, _ = _run_cli(["--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertFalse((self.ddir / di.STATUS_FILENAME).exists())
        json.loads(out)  # печатает валидный JSON

    def test_run_writes_exit_0(self):
        code, out, _ = _run_cli(["--run", "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertTrue((self.ddir / di.STATUS_FILENAME).is_file())
        self.assertIn("verdict=", out)

    def test_run_twice_idempotent_bytes(self):
        _run_cli(["--run", "--data-dir", self.tmp])
        first = (self.ddir / di.STATUS_FILENAME).read_bytes()
        code, out, _ = _run_cli(["--run", "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("unchanged", out)
        self.assertEqual((self.ddir / di.STATUS_FILENAME).read_bytes(), first)

    def test_garbage_args_error_stderr_exit_0(self):
        code, out, err = _run_cli(["--bogus-flag", "wat"])
        self.assertEqual(code, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", out + err)

    def test_check_and_run_mutually_exclusive_no_traceback(self):
        code, out, err = _run_cli(["--check", "--run"])
        self.assertEqual(code, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", out + err)

    def test_run_real_warn_fail_listed(self):
        self.write(di.EQUITY_FILENAME,
                   _equity_doc(_bar("2026-06-01"), _bar("2026-06-05")))  # gap fail
        code, out, _ = _run_cli(["--run", "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("[FAIL] equity_continuity", out)


# ─── Гигиена модуля (SPA-BL-011 / LLM_FORBIDDEN) ─────────────────────────────


class TestModuleHygiene(unittest.TestCase):
    SOURCE = Path(di.__file__).read_text(encoding="utf-8")

    def test_no_llm_sdk_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(self.SOURCE, "data_integrity.py")
        self.assertEqual(violations, [])

    def test_no_web3_or_network_imports(self):
        import ast
        tree = ast.parse(self.SOURCE)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                if node.module:
                    imported.add(node.module.split(".")[0])
        for banned in ("web3", "requests", "urllib", "socket", "http",
                       "anthropic", "openai", "langchain", "litellm"):
            self.assertNotIn(banned, imported, f"запрещённый импорт: {banned}")

    def test_only_stdlib_imports(self):
        import ast
        # "spa_core" allows the canonical atomic-write helper
        # (spa_core.utils.atomic — itself pure stdlib). Heavy / network /
        # LLM deps remain banned by test_no_web3_or_network_imports and
        # test_no_llm_sdk_imports above.
        allowed = {"argparse", "json", "logging", "math", "os", "sys",
                   "tempfile", "datetime", "pathlib", "typing", "__future__",
                   "spa_core"}
        tree = ast.parse(self.SOURCE)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                if node.module:
                    imported.add(node.module.split(".")[0])
        self.assertTrue(imported <= allowed,
                        f"непрошеные импорты: {imported - allowed}")

    def test_module_never_imports_risk_policy(self):
        self.assertNotIn("from spa_core.risk", self.SOURCE)
        self.assertNotIn("import spa_core.risk", self.SOURCE)


if __name__ == "__main__":
    unittest.main()
