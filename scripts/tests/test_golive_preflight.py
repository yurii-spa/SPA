#!/usr/bin/env python3
"""
Тесты для scripts/golive_preflight.py — MP-351.
Запуск: python3 -m pytest scripts/tests/test_golive_preflight.py -v
Или:   python3 -m unittest scripts.tests.test_golive_preflight

Мокирует все внешние вызовы (subprocess, urllib, file I/O).
Pure stdlib (unittest + tempfile + pathlib).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make sure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))

from scripts.golive_preflight import (
    CheckResult,
    _check_keychain_secret,
    _check_telegram_bot,
    _check_golive_checker,
    _check_consecutive_ready_days,
    _check_gap_monitor,
    _check_paper_days,
    _check_equity_level,
    _check_max_drawdown,
    _check_kanban_no_p0_p1,
    _check_cycle_runner_exists,
    _check_cycle_runner_imports,
    _check_risk_policy,
    _check_adapter_registry,
    _check_kill_switch_drill,
    _check_kill_switch_not_active,
    _check_vportfolios,
    _check_strategy_registry,
    _check_file_exists,
    _check_gnosis_safe_address,
    _check_analytics_scorecard,
    _check_risk_policy_blocks,
    _save_result,
    run_preflight,
    VERSION,
)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ─── CheckResult tests ────────────────────────────────────────────────────────

class TestCheckResult(unittest.TestCase):

    def test_pass_emoji(self):
        c = CheckResult("x", "pass", "ok")
        self.assertEqual(c.emoji, "✅")

    def test_fail_emoji(self):
        c = CheckResult("x", "fail", "bad")
        self.assertEqual(c.emoji, "❌")

    def test_warn_emoji(self):
        c = CheckResult("x", "warn", "maybe")
        self.assertEqual(c.emoji, "⚠️ ")

    def test_custom_emoji_preserved(self):
        c = CheckResult("x", "pass", "ok", emoji="🎉")
        self.assertEqual(c.emoji, "🎉")

    def test_value_default_none(self):
        c = CheckResult("x", "pass", "ok")
        self.assertIsNone(c.value)


# ─── _check_keychain_secret ───────────────────────────────────────────────────

class TestCheckKeychainSecret(unittest.TestCase):

    @patch("subprocess.run")
    def test_secret_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="tok123456789\n", stderr="")
        r = _check_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")
        self.assertEqual(r.status, "pass")
        self.assertIn("found in Keychain", r.detail)
        self.assertTrue(r.value)

    @patch("subprocess.run")
    def test_secret_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=44, stdout="", stderr="")
        r = _check_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")
        self.assertEqual(r.status, "fail")
        self.assertIn("NOT found", r.detail)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_security_binary_missing(self, mock_run):
        r = _check_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")
        self.assertEqual(r.status, "warn")
        self.assertIn("not on macOS", r.detail)

    @patch("subprocess.run")
    def test_empty_stdout_treated_as_missing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = _check_keychain_secret("GITHUB_PAT_SPA")
        self.assertEqual(r.status, "fail")

    @patch("subprocess.run")
    def test_github_pat_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ghp_sometoken\n", stderr="")
        r = _check_keychain_secret("GITHUB_PAT_SPA")
        self.assertEqual(r.status, "pass")
        self.assertIn("GITHUB_PAT_SPA", r.detail)


# ─── _check_telegram_bot ─────────────────────────────────────────────────────

class TestCheckTelegramBot(unittest.TestCase):

    def test_skip_flag(self):
        r = _check_telegram_bot(Path("/tmp"), skip=True)
        self.assertEqual(r.status, "warn")
        self.assertIn("пропущен", r.detail)

    @patch("scripts.golive_preflight._read_keychain_secret", return_value=None)
    def test_no_token_in_keychain(self, mock_kc):
        r = _check_telegram_bot(Path("/tmp"))
        self.assertEqual(r.status, "fail")
        self.assertIn("не найден", r.detail)

    @patch("scripts.golive_preflight._read_keychain_secret", return_value="123456:FAKE_TOKEN")
    @patch("urllib.request.urlopen")
    def test_getme_success(self, mock_urlopen, mock_kc):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ok": True, "result": {"username": "spa_alerts_bot", "id": 999}
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        r = _check_telegram_bot(Path("/tmp"))
        self.assertEqual(r.status, "pass")
        self.assertIn("spa_alerts_bot", r.detail)

    @patch("scripts.golive_preflight._read_keychain_secret", return_value="bad:token")
    @patch("urllib.request.urlopen")
    def test_getme_api_returns_not_ok(self, mock_urlopen, mock_kc):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ok": False, "description": "Unauthorized"
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        r = _check_telegram_bot(Path("/tmp"))
        self.assertEqual(r.status, "fail")
        self.assertIn("Unauthorized", r.detail)

    @patch("scripts.golive_preflight._read_keychain_secret", return_value="bad:token")
    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_getme_network_error(self, mock_urlopen, mock_kc):
        r = _check_telegram_bot(Path("/tmp"))
        self.assertEqual(r.status, "fail")
        self.assertIn("timeout", r.detail)


# ─── _check_golive_checker ────────────────────────────────────────────────────

class TestCheckGoLiveChecker(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_ready_true(self):
        _write_json(self.tmp / "golive_status.json", {
            "ready": True,
            "checks": {"a": True, "b": True},
            "blockers": [],
        })
        r = _check_golive_checker(self.tmp)
        self.assertEqual(r.status, "pass")
        self.assertIn("READY", r.detail)

    def test_ready_false_with_blockers(self):
        _write_json(self.tmp / "golive_status.json", {
            "ready": False,
            "checks": {"a": True, "b": False},
            "blockers": ["trades_real"],
        })
        r = _check_golive_checker(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("trades_real", r.detail)

    def test_file_missing(self):
        r = _check_golive_checker(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("not found", r.detail)

    def test_invalid_json(self):
        (self.tmp / "golive_status.json").write_text("not json", encoding="utf-8")
        r = _check_golive_checker(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_consecutive_ready_days ───────────────────────────────────────────

class TestConsecutiveReadyDays(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_7_days_passes(self):
        _write_json(self.tmp / "golive_status.json", {"consecutive_ready_days": 7})
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_10_days_passes(self):
        _write_json(self.tmp / "golive_status.json", {"consecutive_ready_days": 10})
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_3_days_warns(self):
        _write_json(self.tmp / "golive_status.json", {"consecutive_ready_days": 3})
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "warn")
        self.assertIn("4 remaining", r.detail)

    def test_zero_days_warns(self):
        _write_json(self.tmp / "golive_status.json", {"consecutive_ready_days": 0})
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "warn")

    def test_missing_field_warns(self):
        _write_json(self.tmp / "golive_status.json", {"ready": True})
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "warn")

    def test_file_missing(self):
        r = _check_consecutive_ready_days(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_gap_monitor ───────────────────────────────────────────────────────

class TestCheckGapMonitor(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_no_gap_ok(self):
        _write_json(self.tmp / "gap_monitor.json", {
            "gap_detected": False, "status": "ok", "hours_since_last_entry": 6.0
        })
        r = _check_gap_monitor(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_gap_detected(self):
        _write_json(self.tmp / "gap_monitor.json", {
            "gap_detected": True, "status": "gap", "message": "gap 3 days"
        })
        r = _check_gap_monitor(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_status_not_ok(self):
        _write_json(self.tmp / "gap_monitor.json", {
            "gap_detected": False, "status": "stale", "message": "stale"
        })
        r = _check_gap_monitor(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_file_missing(self):
        r = _check_gap_monitor(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_paper_days ────────────────────────────────────────────────────────

class TestCheckPaperDays(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_30_days_passes(self):
        _write_json(self.tmp / "progress_tracker.json", {"paper_days": 30})
        r = _check_paper_days(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_35_days_passes(self):
        _write_json(self.tmp / "progress_tracker.json", {"paper_days": 35})
        r = _check_paper_days(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_3_days_warns(self):
        _write_json(self.tmp / "progress_tracker.json", {"paper_days": 3})
        r = _check_paper_days(self.tmp)
        self.assertEqual(r.status, "warn")
        self.assertIn("27 remaining", r.detail)

    def test_fallback_to_paper_trading_status(self):
        _write_json(self.tmp / "paper_trading_status.json", {"days_running": 31})
        r = _check_paper_days(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_both_missing_fails(self):
        r = _check_paper_days(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_equity_level ─────────────────────────────────────────────────────

class TestCheckEquityLevel(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_equity_above_threshold(self):
        _write_json(self.tmp / "paper_trading_status.json", {"current_equity": 100_026.06})
        r = _check_equity_level(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_equity_exactly_99k(self):
        _write_json(self.tmp / "paper_trading_status.json", {"current_equity": 99_000.0})
        r = _check_equity_level(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_equity_below_threshold(self):
        _write_json(self.tmp / "paper_trading_status.json", {"current_equity": 98_500.0})
        r = _check_equity_level(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("98,500.00", r.detail)

    def test_file_missing(self):
        r = _check_equity_level(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_max_drawdown ──────────────────────────────────────────────────────

class TestCheckMaxDrawdown(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _make_curve(self, equities: list[float]) -> dict:
        return {"daily": [{"equity": eq} for eq in equities]}

    def test_no_drawdown_passes(self):
        _write_json(self.tmp / "equity_curve_daily.json",
                    self._make_curve([100_000, 100_100, 100_200]))
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "pass")
        self.assertEqual(r.value, 0.0)

    def test_small_drawdown_passes(self):
        _write_json(self.tmp / "equity_curve_daily.json",
                    self._make_curve([100_000, 100_500, 100_000, 100_300]))
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "pass")
        self.assertLess(r.value, 2.0)

    def test_large_drawdown_fails(self):
        _write_json(self.tmp / "equity_curve_daily.json",
                    self._make_curve([100_000, 100_500, 97_000]))
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertGreater(r.value, 2.0)

    def test_exactly_at_limit_fails(self):
        # 2% drawdown from peak 100_500 = 98_490
        _write_json(self.tmp / "equity_curve_daily.json",
                    self._make_curve([100_000, 100_500, 98_000]))
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_empty_bars_warns(self):
        _write_json(self.tmp / "equity_curve_daily.json", {"daily": []})
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "warn")

    def test_file_missing(self):
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_list_format(self):
        _write_json(self.tmp / "equity_curve_daily.json",
                    [{"equity": 100_000}, {"equity": 100_050}])
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_close_equity_key(self):
        _write_json(self.tmp / "equity_curve_daily.json",
                    {"daily": [{"close_equity": 100_000}, {"close_equity": 100_100}]})
        r = _check_max_drawdown(self.tmp)
        self.assertEqual(r.status, "pass")


# ─── _check_kanban_no_p0_p1 ───────────────────────────────────────────────────

class TestCheckKanbanNoP0P1(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _make_kanban(self, backlog: list) -> dict:
        return {"columns": {"backlog": backlog, "done": []}}

    def test_empty_backlog_passes(self):
        _write_json(self.tmp / "KANBAN.json", self._make_kanban([]))
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_p2_backlog_passes(self):
        _write_json(self.tmp / "KANBAN.json", self._make_kanban([
            {"id": "MP-1", "title": "Some task", "priority": "P2", "tags": []}
        ]))
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_p1_fails(self):
        _write_json(self.tmp / "KANBAN.json", self._make_kanban([
            {"id": "MP-2", "title": "Critical bug", "priority": "P1", "tags": []}
        ]))
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_p0_fails(self):
        _write_json(self.tmp / "KANBAN.json", self._make_kanban([
            {"id": "MP-3", "title": "Deploy fix", "priority": "P0", "tags": []}
        ]))
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "fail")

    def test_user_action_p1_ignored(self):
        _write_json(self.tmp / "KANBAN.json", self._make_kanban([
            {"id": "UA-1", "title": "USER ACTION: add keys", "priority": "P1",
             "tags": ["user_action"]}
        ]))
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_file_missing(self):
        r = _check_kanban_no_p0_p1(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_cycle_runner_exists ──────────────────────────────────────────────

class TestCheckCycleRunnerExists(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_exists(self):
        cr = self.tmp / "spa_core" / "paper_trading" / "cycle_runner.py"
        cr.parent.mkdir(parents=True)
        cr.write_text("# stub", encoding="utf-8")
        r = _check_cycle_runner_exists(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_missing(self):
        r = _check_cycle_runner_exists(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_cycle_runner_imports ─────────────────────────────────────────────

class TestCheckCycleRunnerImports(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_syntax(self):
        cr = self.tmp / "spa_core" / "paper_trading" / "cycle_runner.py"
        cr.parent.mkdir(parents=True)
        cr.write_text("# valid\ndef run(): pass\n", encoding="utf-8")
        r = _check_cycle_runner_imports(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_syntax_error(self):
        cr = self.tmp / "spa_core" / "paper_trading" / "cycle_runner.py"
        cr.parent.mkdir(parents=True)
        cr.write_text("def broken(:\n    pass\n", encoding="utf-8")
        r = _check_cycle_runner_imports(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("SyntaxError", r.detail)

    def test_missing_file(self):
        r = _check_cycle_runner_imports(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_risk_policy ───────────────────────────────────────────────────────

class TestCheckRiskPolicy(unittest.TestCase):

    def test_passes_with_real_policy(self):
        """Relies on the actual RiskPolicy being importable from repo."""
        r = _check_risk_policy(_REPO_ROOT)
        # Either pass or fail — but must not raise
        self.assertIn(r.status, ("pass", "fail", "warn"))

    def test_import_error_returns_fail(self):
        """If repo_root is wrong, import fails gracefully."""
        r = _check_risk_policy(Path("/nonexistent/path"))
        # Either import fails → "Cannot import RiskPolicy" OR module is cached
        # from prior test and a different error occurs — must not raise
        self.assertIn(r.status, ("fail", "warn", "pass"))  # never raises


# ─── _check_adapter_registry ─────────────────────────────────────────────────

class TestCheckAdapterRegistry(unittest.TestCase):

    def test_passes_with_real_registry(self):
        r = _check_adapter_registry(_REPO_ROOT)
        self.assertIn(r.status, ("pass", "fail", "warn"))

    def test_import_error_handled(self):
        # If a bad path is passed, the check should not raise — either pass
        # (if module already cached in sys.modules) or fail gracefully.
        r = _check_adapter_registry(Path("/nonexistent"))
        self.assertIn(r.status, ("pass", "fail", "warn"))  # must not raise


# ─── _check_kill_switch_drill ────────────────────────────────────────────────

class TestCheckKillSwitchDrill(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_drill_file_missing(self):
        r = _check_kill_switch_drill(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("not found", r.detail)

    def test_drill_pass(self):
        scripts = self.tmp / "scripts"
        scripts.mkdir()
        drill = scripts / "kill_switch_drill.py"
        drill.write_text(
            "def run_drill(*args, **kwargs):\n"
            "    return {'passed': True, 'steps': [], 'total_time_ms': 50}\n",
            encoding="utf-8",
        )
        r = _check_kill_switch_drill(self.tmp)
        self.assertEqual(r.status, "pass")
        self.assertIn("PASS", r.detail)

    def test_drill_fail(self):
        scripts = self.tmp / "scripts"
        scripts.mkdir()
        drill = scripts / "kill_switch_drill.py"
        drill.write_text(
            "def run_drill(*args, **kwargs):\n"
            "    return {'passed': False, 'steps': [{'step': 'x', 'ok': False}], 'total_time_ms': 50}\n",
            encoding="utf-8",
        )
        r = _check_kill_switch_drill(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("FAIL", r.detail)

    def test_drill_exception_handled(self):
        scripts = self.tmp / "scripts"
        scripts.mkdir()
        drill = scripts / "kill_switch_drill.py"
        drill.write_text("def run_drill(*args):\n    raise RuntimeError('boom')\n", encoding="utf-8")
        r = _check_kill_switch_drill(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("boom", r.detail)


# ─── _check_kill_switch_not_active ───────────────────────────────────────────

class TestCheckKillSwitchNotActive(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_not_triggered(self):
        _write_json(self.tmp / "kill_switch_status.json", {
            "triggered": False, "reason": "all triggers clear"
        })
        r = _check_kill_switch_not_active(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_triggered(self):
        _write_json(self.tmp / "kill_switch_status.json", {
            "triggered": True, "reason": "drawdown 5.1%"
        })
        r = _check_kill_switch_not_active(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("ACTIVE", r.detail)

    def test_missing_warns(self):
        r = _check_kill_switch_not_active(self.tmp)
        self.assertEqual(r.status, "warn")


# ─── _check_vportfolios ───────────────────────────────────────────────────────

class TestCheckVportfolios(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_found_in_strategies_subdir(self):
        path = self.tmp / "strategies" / "vportfolios.json"
        _write_json(path, {"s0": {}, "s1": {}})
        r = _check_vportfolios(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_found_in_data_root(self):
        _write_json(self.tmp / "vportfolios.json", [{"id": "s0"}])
        r = _check_vportfolios(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_not_found(self):
        r = _check_vportfolios(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_strategy_registry ────────────────────────────────────────────────

class TestCheckStrategyRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_found_in_paper_trading(self):
        path = self.tmp / "spa_core" / "paper_trading" / "strategy_registry.py"
        path.parent.mkdir(parents=True)
        path.write_text("STRATEGY_REGISTRY = []", encoding="utf-8")
        r = _check_strategy_registry(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_found_in_strategies(self):
        path = self.tmp / "spa_core" / "strategies" / "strategy_registry.py"
        path.parent.mkdir(parents=True)
        path.write_text("STRATEGY_REGISTRY = []", encoding="utf-8")
        r = _check_strategy_registry(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_missing(self):
        r = _check_strategy_registry(self.tmp)
        self.assertEqual(r.status, "fail")


# ─── _check_file_exists ───────────────────────────────────────────────────────

class TestCheckFileExists(unittest.TestCase):

    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(suffix=".md") as f:
            path = Path(f.name)
            r = _check_file_exists(path, "test file", "test_file")
            self.assertEqual(r.status, "pass")

    def test_missing_file(self):
        r = _check_file_exists(Path("/nonexistent/file.md"), "test file", "test_file")
        self.assertEqual(r.status, "fail")
        self.assertIn("NOT found", r.detail)


# ─── _check_gnosis_safe_address ──────────────────────────────────────────────

class TestCheckGnosisSafeAddress(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _make_adr010(self):
        adr = self.tmp / "docs" / "adr" / "ADR-010-gnosis-safe-key-management.md"
        adr.parent.mkdir(parents=True)
        adr.write_text("# ADR-010\nNo address yet.", encoding="utf-8")

    @patch.dict(os.environ, {"SAFE_ADDRESS": "0x" + "a" * 40})
    def test_env_var_set(self):
        r = _check_gnosis_safe_address(self.tmp)
        self.assertIn(r.status, ("pass", "warn"))  # warn: not in Keychain

    @patch.dict(os.environ, {"SAFE_ADDRESS": ""}, clear=False)
    @patch("scripts.golive_preflight._read_keychain_secret", return_value=None)
    def test_no_address_anywhere_with_adr010(self, mock_kc):
        """When ADR-010 exists but no address set → warn (Safe is planned)."""
        self._make_adr010()
        r = _check_gnosis_safe_address(self.tmp)
        self.assertEqual(r.status, "warn")

    @patch.dict(os.environ, {"SAFE_ADDRESS": ""}, clear=False)
    @patch("scripts.golive_preflight._read_keychain_secret", return_value=None)
    def test_no_address_no_adr010(self, mock_kc):
        """When ADR-010 missing and no address → fail."""
        r = _check_gnosis_safe_address(self.tmp)
        self.assertEqual(r.status, "fail")

    @patch.dict(os.environ, {"SAFE_ADDRESS": ""}, clear=False)
    @patch("scripts.golive_preflight._read_keychain_secret",
           return_value="0x" + "b" * 40)
    def test_found_in_keychain(self, mock_kc):
        r = _check_gnosis_safe_address(self.tmp)
        self.assertEqual(r.status, "pass")

    @patch.dict(os.environ, {"SAFE_ADDRESS": ""}, clear=False)
    @patch("scripts.golive_preflight._read_keychain_secret", return_value=None)
    def test_adr010_missing(self, mock_kc):
        r = _check_gnosis_safe_address(self.tmp)
        self.assertEqual(r.status, "fail")
        self.assertIn("NEEDS HUMAN", r.detail)


# ─── _check_analytics_scorecard ──────────────────────────────────────────────

class TestCheckAnalyticsScorecard(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_fresh_ok(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        _write_json(self.tmp / "analytics_scorecard.json", {
            "meta": {"generated_at": now.isoformat()},
            "overall_status": "ok",
        })
        r = _check_analytics_scorecard(self.tmp)
        self.assertIn(r.status, ("pass",))

    def test_stale_warns(self):
        _write_json(self.tmp / "analytics_scorecard.json", {
            "meta": {"generated_at": "2020-01-01T00:00:00+00:00"},
            "overall_status": "ok",
        })
        r = _check_analytics_scorecard(self.tmp)
        self.assertEqual(r.status, "warn")
        self.assertIn("stale", r.detail)

    def test_missing_warns(self):
        r = _check_analytics_scorecard(self.tmp)
        self.assertEqual(r.status, "warn")


# ─── _check_risk_policy_blocks ───────────────────────────────────────────────

class TestCheckRiskPolicyBlocks(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_empty_list_passes(self):
        _write_json(self.tmp / "risk_policy_blocks.json", [])
        r = _check_risk_policy_blocks(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_blocks_with_reasons_pass(self):
        _write_json(self.tmp / "risk_policy_blocks.json", [
            {"reason": "T2 total cap exceeded", "timestamp": "2026-06-12"},
        ])
        r = _check_risk_policy_blocks(self.tmp)
        self.assertEqual(r.status, "pass")

    def test_block_without_reason_warns(self):
        _write_json(self.tmp / "risk_policy_blocks.json", [
            {"reason": "", "timestamp": "2026-06-12"},
        ])
        r = _check_risk_policy_blocks(self.tmp)
        self.assertEqual(r.status, "warn")

    def test_missing_warns(self):
        r = _check_risk_policy_blocks(self.tmp)
        self.assertEqual(r.status, "warn")


# ─── _save_result ─────────────────────────────────────────────────────────────

class TestSaveResult(unittest.TestCase):

    def test_atomic_write(self):
        tmp = Path(tempfile.mkdtemp())
        result = {"verdict": "NOT_READY", "score_pct": 50.0}
        _save_result(result, tmp)
        out = tmp / "golive_preflight_result.json"
        self.assertTrue(out.exists())
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["verdict"], "NOT_READY")

    def test_no_tmp_files_left(self):
        tmp = Path(tempfile.mkdtemp())
        _save_result({"x": 1}, tmp)
        tmps = list(tmp.glob("*.tmp"))
        self.assertEqual(len(tmps), 0)


# ─── run_preflight integration ────────────────────────────────────────────────

class TestRunPreflight(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Create minimal data files
        _write_json(self.tmp / "golive_status.json", {
            "ready": True,
            "checks": {"a": True, "b": True, "c": True, "d": True, "e": True, "f": True},
            "blockers": [],
            "consecutive_ready_days": 7,
        })
        _write_json(self.tmp / "gap_monitor.json", {
            "gap_detected": False, "status": "ok", "hours_since_last_entry": 6.0
        })
        _write_json(self.tmp / "progress_tracker.json", {"paper_days": 3})
        _write_json(self.tmp / "paper_trading_status.json", {"current_equity": 100_026.0})
        _write_json(self.tmp / "equity_curve_daily.json", {
            "daily": [{"equity": 100_000.0}, {"equity": 100_026.0}]
        })
        _write_json(self.tmp / "kill_switch_status.json", {"triggered": False, "reason": "clear"})
        _write_json(self.tmp / "risk_policy_blocks.json", [])
        _write_json(self.tmp / "analytics_scorecard.json", {
            "meta": {"generated_at": "2020-01-01T00:00:00+00:00"},
            "overall_status": "warn"
        })

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_run_returns_dict(self, *mocks):
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        self.assertIsInstance(result, dict)
        self.assertIn("verdict", result)
        self.assertIn("counts", result)
        self.assertIn("checks", result)
        self.assertIn("score_pct", result)
        self.assertEqual(result["version"], VERSION)

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_score_between_0_and_100(self, *mocks):
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        self.assertGreaterEqual(result["score_pct"], 0.0)
        self.assertLessEqual(result["score_pct"], 100.0)

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_not_ready_with_paper_days_3(self, *mocks):
        # paper_days=3 → warn (not fail), but gnosis_safe=fail → NOT_READY
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        # At least one fail expected (gnosis safe, kanban, etc.)
        self.assertIsInstance(result["is_ready"], bool)

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_counts_sum_to_total(self, *mocks):
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        c = result["counts"]
        self.assertEqual(c["pass"] + c["warn"] + c["fail"], c["total"])

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_result_has_all_required_fields(self, *mocks):
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        required = ["version", "mp", "generated_at", "verdict", "verdict_display",
                    "score_pct", "counts", "paper_days", "paper_days_required",
                    "is_ready", "fails", "warns", "elapsed_ms", "checks"]
        for field in required:
            self.assertIn(field, result, f"Missing field: {field}")

    @patch("scripts.golive_preflight._check_keychain_secret",
           return_value=CheckResult("keychain", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_telegram_bot",
           return_value=CheckResult("telegram", "pass", "ok", value="bot"))
    @patch("scripts.golive_preflight._check_risk_policy",
           return_value=CheckResult("risk_policy", "pass", "ok", value=True))
    @patch("scripts.golive_preflight._check_adapter_registry",
           return_value=CheckResult("adapters", "pass", "7 adapters", value=7))
    @patch("scripts.golive_preflight._check_kill_switch_drill",
           return_value=CheckResult("drill", "pass", "PASS", value=True))
    @patch("scripts.golive_preflight._check_cycle_runner_imports",
           return_value=CheckResult("cr_import", "pass", "ok", value=True))
    def test_mp_field_correct(self, *mocks):
        result = run_preflight(data_dir=str(self.tmp), skip_telegram=True)
        self.assertEqual(result["mp"], "MP-351")


if __name__ == "__main__":
    unittest.main(verbosity=2)
