"""MP-350 tests — spa_core/paper_trading/daily_report.py.

Все вызовы telegram_client и DailyReportBuilder замокированы.
Реальных Keychain-запросов и HTTP-вызовов нет.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from spa_core.paper_trading.daily_report import (
    SENTINEL_FILENAME,
    _build_message,
    _mark_sent,
    _should_send,
    run_daily_report,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ─── _should_send ─────────────────────────────────────────────────────────────


class TestShouldSend(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)

    def test_no_sentinel_returns_true(self):
        self.assertTrue(_should_send(self.data_dir, force_send=False))

    def test_sentinel_with_old_date_returns_true(self):
        _write(self.data_dir / SENTINEL_FILENAME, "2000-01-01")
        self.assertTrue(_should_send(self.data_dir, force_send=False))

    def test_sentinel_with_today_returns_false(self):
        _write(self.data_dir / SENTINEL_FILENAME, date.today().isoformat())
        self.assertFalse(_should_send(self.data_dir, force_send=False))

    def test_force_send_overrides_today_sentinel(self):
        _write(self.data_dir / SENTINEL_FILENAME, date.today().isoformat())
        self.assertTrue(_should_send(self.data_dir, force_send=True))

    def test_force_send_true_without_sentinel(self):
        self.assertTrue(_should_send(self.data_dir, force_send=True))

    def test_corrupt_sentinel_returns_true(self):
        _write(self.data_dir / SENTINEL_FILENAME, "not-a-date")
        # Any "non-today" stored date → should_send=True
        self.assertTrue(_should_send(self.data_dir, force_send=False))


# ─── _mark_sent ───────────────────────────────────────────────────────────────


class TestMarkSent(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)

    def test_writes_today_isodate(self):
        _mark_sent(self.data_dir)
        content = (self.data_dir / SENTINEL_FILENAME).read_text(encoding="utf-8").strip()
        self.assertEqual(content, date.today().isoformat())

    def test_overwrites_existing_sentinel(self):
        _write(self.data_dir / SENTINEL_FILENAME, "2000-01-01")
        _mark_sent(self.data_dir)
        content = (self.data_dir / SENTINEL_FILENAME).read_text(encoding="utf-8").strip()
        self.assertEqual(content, date.today().isoformat())

    def test_creates_missing_dir(self):
        deep = self.data_dir / "subdir" / "nested"
        _mark_sent(deep)
        self.assertTrue((deep / SENTINEL_FILENAME).exists())


# ─── _build_message ───────────────────────────────────────────────────────────


class TestBuildMessage(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)

    def test_returns_string(self):
        # DailyReportBuilder works on empty data_dir → returns fallback message
        msg = _build_message(self.data_dir)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_contains_date(self):
        msg = _build_message(self.data_dir)
        today = date.today().isoformat()
        self.assertIn(today, msg)

    def test_builder_exception_returns_fallback(self):
        """If DailyReportBuilder raises, _build_message returns a safe fallback."""
        with patch(
            "spa_core.alerts.daily_report.DailyReportBuilder",
            side_effect=RuntimeError("builder boom"),
        ):
            msg = _build_message(self.data_dir)
        self.assertIn("SPA Daily Report", msg)
        self.assertIn("⚠️", msg)

    def test_mock_builder_message_returned(self):
        mock_builder = MagicMock()
        mock_builder.return_value.build_report.return_value = "MOCK_MSG"
        with patch("spa_core.alerts.daily_report.DailyReportBuilder", mock_builder):
            msg = _build_message(self.data_dir)
        self.assertEqual(msg, "MOCK_MSG")
        mock_builder.assert_called_once_with(self.data_dir)


# ─── run_daily_report ─────────────────────────────────────────────────────────


_FAKE_MSG = "📊 <b>SPA Daily Report — 2026-06-12</b>\n\n💰 Portfolio: $100,000"


def _patch_builder(msg: str = _FAKE_MSG):
    """Patch DailyReportBuilder to return a fixed message.

    DailyReportBuilder is lazy-imported inside _build_message, so we patch it
    at its canonical source (spa_core.alerts.daily_report).
    """
    mock_builder = MagicMock()
    mock_builder.return_value.build_report.return_value = msg
    return patch("spa_core.alerts.daily_report.DailyReportBuilder", mock_builder)


def _patch_telegram(ok: bool = True):
    """Patch telegram_client.send_message to return ok.

    Patch the function on the real module rather than swapping the whole module
    in sys.modules: _send_telegram does ``from spa_core.alerts import
    telegram_client``, which binds the package attribute and bypasses a
    sys.modules swap once the package is imported.
    """
    return patch("spa_core.alerts.telegram_client.send_message", return_value=ok)


class TestRunDailyReport(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)

    # ── dry_run=True ─────────────────────────────────────────────────────────

    def test_dry_run_returns_dict(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIsInstance(r, dict)

    def test_dry_run_sent_is_false(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertFalse(r["sent"])

    def test_dry_run_flag_in_result(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertTrue(r["dry_run"])

    def test_dry_run_no_sentinel_written(self):
        with _patch_builder():
            run_daily_report(self.data_dir, dry_run=True)
        self.assertFalse((self.data_dir / SENTINEL_FILENAME).exists())

    def test_dry_run_no_telegram_call(self):
        import sys
        mock_tc = MagicMock()
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            run_daily_report(self.data_dir, dry_run=True)
        mock_tc.send_message.assert_not_called()

    def test_dry_run_message_in_result(self):
        with _patch_builder(_FAKE_MSG):
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertEqual(r["message"], _FAKE_MSG)

    # ── normal send (dry_run=False) ───────────────────────────────────────────

    def test_normal_send_returns_dict(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            r = run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertIsInstance(r, dict)

    def test_normal_send_sent_true_on_success(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            r = run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertTrue(r["sent"])

    def test_normal_send_writes_sentinel_on_success(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertTrue((self.data_dir / SENTINEL_FILENAME).exists())

    def test_normal_send_no_sentinel_on_failure(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = False
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertFalse((self.data_dir / SENTINEL_FILENAME).exists())

    def test_normal_send_error_in_result_on_failure(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = False
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            r = run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertFalse(r["sent"])
        self.assertIsNotNone(r["error"])

    # ── rate-limiting (should_send=False) ────────────────────────────────────

    def test_already_sent_today_skipped(self):
        _write(self.data_dir / SENTINEL_FILENAME, date.today().isoformat())
        mock_tc = MagicMock()
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            r = run_daily_report(self.data_dir, dry_run=False, force_send=False)
        self.assertTrue(r["skipped"])
        self.assertFalse(r["sent"])
        mock_tc.send_message.assert_not_called()

    def test_force_send_bypasses_rate_limit(self):
        _write(self.data_dir / SENTINEL_FILENAME, date.today().isoformat())
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            r = run_daily_report(self.data_dir, dry_run=False, force_send=True)
        self.assertFalse(r["skipped"])
        mock_tc.send_message.assert_called_once()

    # ── fail-safe ─────────────────────────────────────────────────────────────

    def test_telegram_exception_does_not_raise(self):
        mock_tc = MagicMock()
        mock_tc.send_message.side_effect = RuntimeError("network down")
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            try:
                r = run_daily_report(self.data_dir, dry_run=False, force_send=True)
            except Exception as exc:
                self.fail(f"run_daily_report raised unexpectedly: {exc}")
        self.assertFalse(r["sent"])

    def test_empty_data_dir_does_not_raise(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            try:
                r = run_daily_report(self.data_dir, dry_run=True)
            except Exception as exc:
                self.fail(f"run_daily_report raised unexpectedly: {exc}")
        self.assertIsInstance(r, dict)

    # ── result keys ──────────────────────────────────────────────────────────

    def test_result_has_sent_key(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIn("sent", r)

    def test_result_has_dry_run_key(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIn("dry_run", r)

    def test_result_has_skipped_key(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIn("skipped", r)

    def test_result_has_message_key(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIn("message", r)

    def test_result_has_error_key(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIn("error", r)

    def test_dry_run_error_is_none(self):
        with _patch_builder():
            r = run_daily_report(self.data_dir, dry_run=True)
        self.assertIsNone(r["error"])

    # ── keychain / no hardcoded secrets ──────────────────────────────────────

    def test_telegram_client_send_message_called_with_text(self):
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(_FAKE_MSG), patch(
            "spa_core.alerts.telegram_client.send_message", mock_tc.send_message
        ):
            run_daily_report(self.data_dir, dry_run=False, force_send=True)
        # _send_telegram calls send_message(text, parse_mode="HTML")
        mock_tc.send_message.assert_called_once_with(_FAKE_MSG, parse_mode="HTML")

    def test_no_token_in_source(self):
        """Убеждаемся что в исходнике нет хардкода токена."""
        import spa_core.paper_trading.daily_report as mod
        src = mod.__file__
        with open(src, encoding="utf-8") as fh:
            code = fh.read()
        for kw in ("bot_token", "BOT_TOKEN", "AAAA", "sendMessage?bot"):
            self.assertNotIn(kw, code, f"Suspicious hardcoded value '{kw}' found in source")


# ─── CLI smoke test ───────────────────────────────────────────────────────────


class TestCLI(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)

    def test_dry_run_flag_exits_zero(self):
        from spa_core.paper_trading.daily_report import main
        with _patch_builder():
            rc = main(["--dry-run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_test_send_flag_exits_zero_on_success(self):
        from spa_core.paper_trading.daily_report import main
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = True
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            rc = main(["--test-send", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_test_send_flag_exits_nonzero_on_failure(self):
        from spa_core.paper_trading.daily_report import main
        mock_tc = MagicMock()
        mock_tc.send_message.return_value = False
        with _patch_builder(), patch("spa_core.alerts.telegram_client.send_message", mock_tc.send_message):
            rc = main(["--test-send", "--data-dir", str(self.data_dir)])
        self.assertNotEqual(rc, 0)

    def test_rate_limited_exits_zero(self):
        """Already-sent today → skip, exit 0."""
        _write(self.data_dir / SENTINEL_FILENAME, date.today().isoformat())
        from spa_core.paper_trading.daily_report import main
        with _patch_builder():
            rc = main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
