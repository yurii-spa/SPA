"""
MP-434: Tests for checkpoint_7day.py
10 тестов автоматической валидации 7-Day Checkpoint.

Совместимость: unittest (stdlib) + pytest.
Запуск:
    python3 -m pytest  tests/test_checkpoint_7day.py -v
    python3 -m unittest tests/test_checkpoint_7day.py -v  (без pytest)

Тесты:
  1.  test_gap_check_no_gaps          — gap_monitor ok → pass
  2.  test_gap_check_with_gap         — gap_detected=True → fail
  3.  test_equity_floor_pass          — equity > 95k → pass
  4.  test_equity_floor_fail          — equity < 95k → fail
  5.  test_sharpe_check_pass          — S7>=0.8, S5>=0.9, S5>=1.0 PROMOTE → pass
  6.  test_sharpe_check_fail          — S7<0.8 → warning присутствует
  7.  test_files_existence            — все файлы → pass; один отсутствует → fail
  8.  test_telegram_send_on_fail      — mock: при fail отправляется FAILED
  9.  test_summary_output_format      — summary содержит ожидаемые строки
  10. test_exit_code_on_fail          — run_checkpoint() → 1 при fail
"""

from __future__ import annotations

import json
import sys
import unittest
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

# Добавляем корень репо в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.checkpoint_7day import (
    check_equity,
    check_files,
    check_gaps,
    check_sharpe,
    format_summary,
    overall_pass,
    run_checkpoint,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def make_gap_monitor(data_dir: Path, gap: bool = False, hours: float = 10.0) -> None:
    write_json(data_dir / "gap_monitor.json", {
        "gap_detected": gap,
        "hours_since_last_entry": hours,
        "status": "gap" if gap else "ok",
        "message": "Gap!" if gap else "Норма",
    })


def make_paper_evidence(data_dir: Path, days_data: list[dict] | None = None) -> None:
    write_json(data_dir / "paper_evidence.json", {
        "schema_version": "1.0",
        "start_date": "2026-06-12",
        "days": days_data or [],
    })


def make_tournament_ranking(data_dir: Path, strategies: list[dict]) -> None:
    write_json(data_dir / "tournament_ranking.json", {
        "generated_at": "2026-06-19",
        "winner": strategies[0]["id"] if strategies else "S7",
        "strategies": strategies,
    })


def make_paper_trading_status(data_dir: Path, equity: float,
                               kill_switch: bool = False, apy: float = 8.0) -> None:
    write_json(data_dir / "paper_trading_status.json", {
        "is_demo": False,
        "current_equity": equity,
        "kill_switch_active": kill_switch,
        "apy_today_pct": apy,
        "kill_switch_reason": "all triggers clear",
    })


def make_critical_files(data_dir: Path, missing: list[str] | None = None) -> None:
    miss = set(missing or [])
    for fname in ["golive_status.json", "paper_evidence.json",
                  "tournament_ranking.json", "adapter_status.json"]:
        if fname not in miss:
            write_json(data_dir / fname, {"ok": True})


# ─── Base test class with temp dir ────────────────────────────────────────────

class SpaTestCase(unittest.TestCase):
    """Base class: создаёт/удаляет tmp data_dir для каждого теста."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name) / "data"
        self.data_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()


# ═══════════════════════════════════════════════════════════════════════════
# 1. test_gap_check_no_gaps
# ═══════════════════════════════════════════════════════════════════════════

class TestGapCheck(SpaTestCase):

    def test_gap_check_no_gaps(self):
        """gap_monitor.json без пробела, paper_evidence с двумя последовательными днями → pass."""
        make_gap_monitor(self.data_dir, gap=False, hours=14.0)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": 100_020, "apy_pct": 7.5},
            {"date": "2026-06-13", "equity_value": 100_040, "apy_pct": 7.6},
        ])

        result = check_gaps(self.data_dir)

        self.assertEqual(result["status"], "pass", f"Expected pass, got: {result}")
        self.assertFalse(result["gap_detected"])
        self.assertEqual(result["days_tracked"], 2)

    # ─── 2. test_gap_check_with_gap ──────────────────────────────────────────

    def test_gap_check_with_gap(self):
        """gap_monitor.json с gap_detected=True → fail."""
        make_gap_monitor(self.data_dir, gap=True, hours=50.0)

        result = check_gaps(self.data_dir)

        self.assertEqual(result["status"], "fail", f"Expected fail, got: {result}")
        self.assertTrue(result["gap_detected"])

    def test_gap_check_hours_threshold(self):
        """Последняя запись > 26 часов назад → fail."""
        make_gap_monitor(self.data_dir, gap=False, hours=30.0)

        result = check_gaps(self.data_dir)

        self.assertEqual(result["status"], "fail")
        self.assertIn("30.0h", result["detail"])

    def test_gap_in_paper_evidence_dates(self):
        """Пробел в датах paper_evidence (пропуск 2 дней) → fail."""
        make_gap_monitor(self.data_dir, gap=False, hours=5.0)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": 100_010, "apy_pct": 7.0},
            {"date": "2026-06-15", "equity_value": 100_030, "apy_pct": 7.0},  # пропуск
        ])

        result = check_gaps(self.data_dir)

        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["gap_detected"])


# ═══════════════════════════════════════════════════════════════════════════
# 3–4. test_equity_floor_pass / fail
# ═══════════════════════════════════════════════════════════════════════════

class TestEquityFloor(SpaTestCase):

    def test_equity_floor_pass(self):
        """Equity $100,245 >= $95,000 → status pass."""
        make_paper_trading_status(self.data_dir, equity=100_245.0, apy=9.8)

        result = check_equity(self.data_dir)

        self.assertEqual(result["status"], "pass", f"Expected pass, got: {result}")
        self.assertEqual(result["current_equity"], 100_245.0)

    def test_equity_floor_fail(self):
        """Equity $92,000 < $95,000 → status fail с ALERT."""
        make_paper_trading_status(self.data_dir, equity=92_000.0, apy=3.0)

        result = check_equity(self.data_dir)

        self.assertEqual(result["status"], "fail", f"Expected fail, got: {result}")
        self.assertTrue(
            "ALERT" in result["detail"] or "floor" in result["detail"].lower()
        )

    def test_equity_kill_switch_active(self):
        """Kill switch active → status fail."""
        make_paper_trading_status(self.data_dir, equity=100_000.0, kill_switch=True)

        result = check_equity(self.data_dir)

        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["kill_switch_active"])

    def test_equity_apy_low_warn(self):
        """APY 2% < 5% при equity > floor → warn (не fail по equity)."""
        make_paper_trading_status(self.data_dir, equity=98_000.0, apy=2.0)

        result = check_equity(self.data_dir)

        self.assertIn(result["status"], ("pass", "warn"))
        self.assertEqual(result["apy_7d_pct"], 2.0)


# ═══════════════════════════════════════════════════════════════════════════
# 5–6. test_sharpe_check_pass / fail
# ═══════════════════════════════════════════════════════════════════════════

class TestSharpeCheck(SpaTestCase):

    def _good_strategies(self):
        return [
            {"id": "S7", "sharpe": 0.96, "name": "Pendle YT+PT Aggressive"},
            {"id": "S5", "sharpe": 1.02, "name": "Pendle PT Enhanced"},
            {"id": "S6", "sharpe": 0.92, "name": "Max Diversified"},
        ]

    def test_sharpe_check_pass(self):
        """S7=0.96>=0.8, S5=1.02>=0.9 и PROMOTE candidate → pass, нет warnings."""
        make_tournament_ranking(self.data_dir, self._good_strategies())

        result = check_sharpe(self.data_dir)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["warnings"], [])
        promo_ids = [p["id"] for p in result["promote_candidates"]]
        self.assertIn("S5", promo_ids)

    def test_sharpe_check_fail_s7_low(self):
        """S7=0.5 < 0.8 → warning в списке."""
        make_tournament_ranking(self.data_dir, [
            {"id": "S7", "sharpe": 0.5, "name": "Pendle YT+PT Aggressive"},
            {"id": "S5", "sharpe": 0.85, "name": "Pendle PT Enhanced"},
        ])

        result = check_sharpe(self.data_dir)

        s7_warns = [w for w in result["warnings"] if "S7" in w]
        self.assertGreater(len(s7_warns), 0, f"Expected S7 warning, got: {result['warnings']}")

    def test_sharpe_no_promote_candidates(self):
        """Все Sharpe < 1.0 → promote_candidates пуст."""
        make_tournament_ranking(self.data_dir, [
            {"id": "S7", "sharpe": 0.85, "name": "S7"},
            {"id": "S5", "sharpe": 0.91, "name": "S5"},
        ])

        result = check_sharpe(self.data_dir)

        self.assertEqual(result["promote_candidates"], [])

    def test_sharpe_missing_file(self):
        """tournament_ranking.json отсутствует → warn."""
        # файл НЕ создаём

        result = check_sharpe(self.data_dir)

        self.assertEqual(result["status"], "warn")


# ═══════════════════════════════════════════════════════════════════════════
# 7. test_files_existence
# ═══════════════════════════════════════════════════════════════════════════

class TestFilesExistence(SpaTestCase):

    def test_all_files_present(self):
        """Все 4 критических файла → pass."""
        make_critical_files(self.data_dir)

        result = check_files(self.data_dir)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["missing"], [])
        self.assertEqual(len(result["found"]), 4)

    def test_missing_one_file(self):
        """adapter_status.json отсутствует → fail."""
        make_critical_files(self.data_dir, missing=["adapter_status.json"])

        result = check_files(self.data_dir)

        self.assertEqual(result["status"], "fail")
        self.assertIn("adapter_status.json", result["missing"])

    def test_missing_multiple_files(self):
        """Два файла отсутствуют → оба в missing."""
        make_critical_files(
            self.data_dir,
            missing=["golive_status.json", "paper_evidence.json"]
        )

        result = check_files(self.data_dir)

        self.assertEqual(result["status"], "fail")
        self.assertIn("golive_status.json", result["missing"])
        self.assertIn("paper_evidence.json", result["missing"])


# ═══════════════════════════════════════════════════════════════════════════
# 8. test_telegram_send_on_fail
# ═══════════════════════════════════════════════════════════════════════════

class TestTelegramOnFail(SpaTestCase):

    def _prepare_data(self, equity: float = 100_500.0, gap: bool = False,
                      apy: float = 9.0) -> None:
        """Создаёт полный набор data-файлов для run_checkpoint."""
        make_paper_trading_status(self.data_dir, equity=equity, apy=apy)
        make_gap_monitor(self.data_dir, gap=gap, hours=5.0)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": 100_010, "apy_pct": 9.0},
        ])
        make_tournament_ranking(self.data_dir, [
            {"id": "S7", "sharpe": 0.9, "name": "S7"}
        ])
        make_critical_files(self.data_dir)
        # Перезаписываем paper_evidence и tournament_ranking (поверх заглушек)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": 100_010, "apy_pct": 9.0},
        ])
        make_tournament_ranking(self.data_dir, [
            {"id": "S7", "sharpe": 0.9, "name": "S7"}
        ])

    def test_telegram_send_on_fail(self):
        """При fail run_checkpoint() вызывает notify с 'FAILED'."""
        self._prepare_data(equity=50_000.0)  # ниже floor → fail

        sent: list[str] = []
        import scripts.checkpoint_7day as mod
        original = mod.notify_telegram
        mod.notify_telegram = lambda msg: (sent.append(msg), True)[1]
        try:
            code = run_checkpoint(data_dir=self.data_dir)
        finally:
            mod.notify_telegram = original

        self.assertEqual(code, 1)
        self.assertEqual(len(sent), 1)
        self.assertTrue(
            "FAILED" in sent[0] or "⚠️" in sent[0],
            f"Expected FAILED/⚠️ in message, got: {sent[0][:100]}"
        )

    def test_telegram_send_on_pass(self):
        """При pass run_checkpoint() шлёт 'PASSED' сообщение."""
        self._prepare_data(equity=100_500.0)

        sent: list[str] = []
        import scripts.checkpoint_7day as mod
        original = mod.notify_telegram
        mod.notify_telegram = lambda msg: (sent.append(msg), True)[1]
        try:
            code = run_checkpoint(data_dir=self.data_dir)
        finally:
            mod.notify_telegram = original

        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)
        self.assertTrue(
            "PASSED" in sent[0] or "✅" in sent[0],
            f"Expected PASSED/✅ in message, got: {sent[0][:100]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 9. test_summary_output_format
# ═══════════════════════════════════════════════════════════════════════════

class TestSummaryFormat(unittest.TestCase):

    def _make_checks(self, equity: float = 100_245.0, apy: float = 9.8,
                     best_sharpe: float = 0.97,
                     promote: list | None = None) -> tuple:
        gaps = {
            "name": "gap_check", "status": "pass",
            "days_tracked": 7, "gap_detected": False, "detail": "OK"
        }
        sharpe = {
            "name": "sharpe_check", "status": "pass",
            "best_sharpe_id": "S7", "best_sharpe_val": best_sharpe,
            "promote_candidates": promote or [],
            "warnings": [], "detail": ""
        }
        eq = {
            "name": "equity_floor", "status": "pass",
            "current_equity": equity,
            "return_pct": (equity - 100_000) / 100_000 * 100,
            "apy_7d_pct": apy,
            "kill_switch_active": False, "detail": "OK"
        }
        files = {
            "name": "files_existence", "status": "pass",
            "found": ["golive_status.json", "paper_evidence.json",
                      "tournament_ranking.json", "adapter_status.json"],
            "missing": [], "detail": "All 4 critical files present"
        }
        return gaps, sharpe, eq, files

    def test_summary_contains_key_lines(self):
        """Summary содержит все ключевые строки из spec."""
        gaps, sharpe, eq, files = self._make_checks()
        summary = format_summary(gaps, sharpe, eq, files, today=date(2026, 6, 19))

        for line in [
            "=== SPA 7-Day Checkpoint (2026-06-19) ===",
            "Days tracked:",
            "Gap-free:",
            "Equity:",
            "APY (7d):",
            "Best Sharpe:",
            "Kill-switch:",
            "GoLive status:",
        ]:
            self.assertIn(line, summary, f"Missing line in summary: '{line}'")

    def test_summary_promote_candidate_shown(self):
        """Если PROMOTE candidate есть → отображается в summary."""
        promote = [{"id": "S5", "sharpe": 1.02}]
        gaps, sharpe, eq, files = self._make_checks(promote=promote)
        summary = format_summary(gaps, sharpe, eq, files, today=date(2026, 6, 19))

        self.assertIn("S5", summary)
        self.assertIn("1.02", summary)

    def test_summary_equity_formatted(self):
        """Equity отображается с $ и запятыми."""
        gaps, sharpe, eq, files = self._make_checks(equity=100_245.50)
        summary = format_summary(gaps, sharpe, eq, files, today=date(2026, 6, 19))

        self.assertIn("$100,245.50", summary)

    def test_summary_gap_fail_shows_no(self):
        """Если gap_check fail → в summary ❌ NO."""
        gaps, sharpe, eq, files = self._make_checks()
        gaps["status"] = "fail"
        gaps["detail"] = "Gap detected"

        summary = format_summary(gaps, sharpe, eq, files, today=date(2026, 6, 19))

        self.assertIn("❌", summary)


# ═══════════════════════════════════════════════════════════════════════════
# 10. test_exit_code_on_fail
# ═══════════════════════════════════════════════════════════════════════════

class TestExitCode(SpaTestCase):

    def _prepare(self, equity: float, gap: bool = False) -> None:
        make_paper_trading_status(self.data_dir, equity=equity, apy=9.0)
        make_gap_monitor(self.data_dir, gap=gap, hours=5.0)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": equity, "apy_pct": 9.0},
        ])
        make_tournament_ranking(self.data_dir, [{"id": "S7", "sharpe": 0.9, "name": "S7"}])
        make_critical_files(self.data_dir)
        make_paper_evidence(self.data_dir, [
            {"date": "2026-06-12", "equity_value": equity, "apy_pct": 9.0},
        ])
        make_tournament_ranking(self.data_dir, [{"id": "S7", "sharpe": 0.9, "name": "S7"}])

    def test_exit_code_zero_on_all_pass(self):
        """Все проверки pass → exit code 0."""
        self._prepare(equity=100_500.0)

        import scripts.checkpoint_7day as mod
        original = mod.notify_telegram
        mod.notify_telegram = lambda msg: True
        try:
            code = run_checkpoint(data_dir=self.data_dir)
        finally:
            mod.notify_telegram = original

        self.assertEqual(code, 0)

    def test_exit_code_one_on_fail(self):
        """Equity ниже floor ($80k) → exit code 1."""
        self._prepare(equity=80_000.0)

        import scripts.checkpoint_7day as mod
        original = mod.notify_telegram
        mod.notify_telegram = lambda msg: True
        try:
            code = run_checkpoint(data_dir=self.data_dir)
        finally:
            mod.notify_telegram = original

        self.assertEqual(code, 1)

    def test_overall_pass_helper_all_pass(self):
        """overall_pass с пустыми fail → True, []."""
        checks = [
            {"name": "a", "status": "pass", "detail": "ok"},
            {"name": "b", "status": "warn", "detail": "warning"},
        ]
        ok, failures = overall_pass(checks)
        self.assertTrue(ok)
        self.assertEqual(failures, [])

    def test_overall_pass_helper_with_fail(self):
        """overall_pass с одним fail → False, failures содержит имя."""
        checks = [
            {"name": "equity_floor", "status": "fail", "detail": "too low"},
            {"name": "gap_check",    "status": "pass", "detail": "ok"},
        ]
        ok, failures = overall_pass(checks)
        self.assertFalse(ok)
        self.assertTrue(any("equity_floor" in f for f in failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
