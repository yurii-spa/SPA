"""MP-016b: Tests for spa_core/alerts/bot_commands.py

Covers:
  * calculate_period_returns with various data sets (empty, 1-day, 7-day, 30-day)
  * _send_with_keyboard — reply_markup (inline keyboard) present in payload
  * _answer_callback_query — called before reply on callback_query
  * _process_update — callback_query path calls answerCallbackQuery then send
  * _process_update — message path (non-/start) sends welcome + keyboard
  * _get_token / _get_chat_id — mock subprocess (Keychain)
  * run_polling — fail-safe when Keychain unavailable
  * run_polling — offset persisted after processing updates

Run:
  python3 -m pytest spa_core/tests/test_bot_commands.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from datetime import datetime, timedelta

# Make the project root importable
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import spa_core.alerts.bot_commands as bc


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_curve(n: int, start_equity: float = 100_000.0, daily_return: float = 0.1) -> list:
    """Build a synthetic equity curve of n bars ending today."""
    bars = []
    today = datetime.today()
    equity = start_equity
    for i in range(n):
        date = (today - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d")
        prev = equity
        equity = round(equity * (1 + daily_return / 100.0), 2)
        bars.append({
            "date": date,
            "equity": equity,
            "close_equity": equity,
            "daily_return_pct": daily_return if i > 0 else 0.0,
        })
    return bars


# ─── Test 1: calculate_period_returns — empty curve ──────────────────────────


class TestCalculatePeriodReturnsEmpty(unittest.TestCase):
    def test_empty_returns_zeros(self):
        result = bc.calculate_period_returns([])
        self.assertEqual(result["today_pct"], 0.0)
        self.assertEqual(result["week_pct"], 0.0)
        self.assertEqual(result["month_pct"], 0.0)
        self.assertEqual(result["year_pct"], 0.0)
        self.assertEqual(result["alltime_pct"], 0.0)
        self.assertEqual(result["profitable_7d"], 0)
        self.assertEqual(result["profitable_30d"], 0)
        self.assertIsNone(result["best_day_7d_date"])


# ─── Test 2: calculate_period_returns — single bar ───────────────────────────


class TestCalculatePeriodReturnsSingleBar(unittest.TestCase):
    def test_single_bar(self):
        curve = [{"date": "2026-06-10", "equity": 100_100.0, "daily_return_pct": 0.0}]
        result = bc.calculate_period_returns(curve)
        # alltime: start == end since only 1 bar
        self.assertEqual(result["alltime_pct"], 0.0)
        self.assertEqual(result["week_pct"], 0.0)   # no prior bars


# ─── Test 3: calculate_period_returns — 7-day window ─────────────────────────


class TestCalculatePeriodReturns7Days(unittest.TestCase):
    def test_week_return_correct(self):
        curve = _make_curve(10, start_equity=100_000.0, daily_return=0.1)
        result = bc.calculate_period_returns(curve)
        # week_pct should be positive (equity grew)
        self.assertGreater(result["week_pct"], 0.0)
        self.assertGreater(result["alltime_pct"], 0.0)
        # profitable_7d: last 7 bars all have 0.1% return
        self.assertGreaterEqual(result["profitable_7d"], 6)


# ─── Test 4: calculate_period_returns — 30-day window ────────────────────────


class TestCalculatePeriodReturns30Days(unittest.TestCase):
    def test_month_return_correct(self):
        curve = _make_curve(35, start_equity=100_000.0, daily_return=0.05)
        result = bc.calculate_period_returns(curve)
        self.assertGreater(result["month_pct"], 0.0)
        self.assertGreater(result["alltime_pct"], result["month_pct"])
        self.assertGreater(result["profitable_30d"], 25)


# ─── Test 5: inline keyboard present in _send_with_keyboard payload ──────────


class TestSendWithKeyboardPayload(unittest.TestCase):
    def test_keyboard_in_payload(self):
        """reply_markup must be present and contain inline_keyboard."""
        captured = {}

        def fake_api_post(token, method, payload):
            captured.update({"method": method, "payload": payload})
            return {"ok": True}

        with mock.patch.object(bc, "_api_post", side_effect=fake_api_post):
            bc._send_with_keyboard("TOKEN", "CHAT_ID", "hello")

        self.assertIn("reply_markup", captured["payload"])
        rm = json.loads(captured["payload"]["reply_markup"])
        self.assertIn("inline_keyboard", rm)
        # Verify structure: 3 rows
        self.assertEqual(len(rm["inline_keyboard"]), 3)
        # Row 0 has two buttons
        self.assertEqual(len(rm["inline_keyboard"][0]), 2)
        # Row 2 has one button
        self.assertEqual(len(rm["inline_keyboard"][2]), 1)

    def test_keyboard_callback_data_values(self):
        """All expected callback_data strings must be present."""
        captured = {}

        def fake_api_post(token, method, payload):
            captured.update({"payload": payload})
            return {"ok": True}

        with mock.patch.object(bc, "_api_post", side_effect=fake_api_post):
            bc._send_with_keyboard("TOKEN", "CHAT_ID", "hello")

        rm = json.loads(captured["payload"]["reply_markup"])
        flat = [btn["callback_data"] for row in rm["inline_keyboard"] for btn in row]
        expected = {"cmd_now", "cmd_week", "cmd_month", "cmd_year", "cmd_status"}
        self.assertEqual(set(flat), expected)


# ─── Test 6: answerCallbackQuery called BEFORE send on callback_query ─────────


class TestAnswerCallbackQueryCalled(unittest.TestCase):
    def test_answer_called_before_send(self):
        """answerCallbackQuery must be invoked before _send_with_keyboard."""
        call_order = []

        def fake_answer(token, cq_id):
            call_order.append("answer")
            return True

        def fake_send(token, chat_id, text):
            call_order.append("send")
            return True

        update = {
            "update_id": 1,
            "callback_query": {
                "id": "cq123",
                "data": "cmd_now",
                "message": {"chat": {"id": 999}},
            },
        }

        with mock.patch.object(bc, "_answer_callback_query", side_effect=fake_answer), \
             mock.patch.object(bc, "_send_with_keyboard", side_effect=fake_send), \
             mock.patch.object(bc, "_cmd_now_text", return_value="snapshot"):
            bc._process_update("TOKEN", "CHAT_ID", update)

        self.assertEqual(call_order, ["answer", "send"],
                         "answerCallbackQuery must be called BEFORE _send_with_keyboard")


# ─── Test 7: Keychain mock — _get_token and _get_chat_id ─────────────────────


class TestKeychainMock(unittest.TestCase):
    def test_get_token_reads_keychain(self):
        """_get_token should call subprocess with the right service name."""
        fake_proc = mock.MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "fake_token\n"

        with mock.patch("spa_core.alerts.bot_commands.subprocess.run", return_value=fake_proc) as m_run:
            token = bc._get_token()
        self.assertEqual(token, "fake_token")
        args = m_run.call_args[0][0]
        self.assertIn("TELEGRAM_BOT_TOKEN_SPA", args)

    def test_get_chat_id_reads_keychain(self):
        fake_proc = mock.MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "12345678\n"

        with mock.patch("spa_core.alerts.bot_commands.subprocess.run", return_value=fake_proc):
            cid = bc._get_chat_id()
        self.assertEqual(cid, "12345678")

    def test_get_token_missing_raises_environment_error(self):
        fake_proc = mock.MagicMock()
        fake_proc.returncode = 44  # security tool returns non-zero when not found
        fake_proc.stdout = ""

        with mock.patch("spa_core.alerts.bot_commands.subprocess.run", return_value=fake_proc):
            with self.assertRaises(EnvironmentError):
                bc._get_token()


# ─── Test 8: run_polling fail-safe — missing credentials ─────────────────────


class TestRunPollingFailSafe(unittest.TestCase):
    def test_no_crash_when_keychain_unavailable(self):
        """run_polling must return silently (not raise) when credentials absent."""
        with mock.patch.object(bc, "_get_token", side_effect=EnvironmentError("no cred")):
            try:
                bc.run_polling()  # must not raise
            except Exception as exc:
                self.fail(f"run_polling raised unexpectedly: {exc}")

    def test_no_crash_on_network_error(self):
        """run_polling must return silently when getUpdates fails."""
        with mock.patch.object(bc, "_get_token", return_value="T"), \
             mock.patch.object(bc, "_get_chat_id", return_value="C"), \
             mock.patch.object(bc, "_api_get", side_effect=OSError("network down")):
            try:
                bc.run_polling()
            except Exception as exc:
                self.fail(f"run_polling raised unexpectedly: {exc}")


# ─── Test 9: run_polling persists offset ─────────────────────────────────────


class TestRunPollingOffsetPersisted(unittest.TestCase):
    def test_offset_incremented_after_updates(self):
        """After processing update_id=42, offset file must contain 43."""
        fake_resp = {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "message": {"chat": {"id": 999}, "text": "/start"},
                }
            ],
        }

        written_offsets = []

        def fake_write_offset(offset):
            written_offsets.append(offset)

        with mock.patch.object(bc, "_get_token", return_value="T"), \
             mock.patch.object(bc, "_get_chat_id", return_value="999"), \
             mock.patch.object(bc, "_api_get", return_value=fake_resp), \
             mock.patch.object(bc, "_read_offset", return_value=0), \
             mock.patch.object(bc, "_write_offset", side_effect=fake_write_offset), \
             mock.patch.object(bc, "_send_with_keyboard", return_value=True):
            bc.run_polling()

        self.assertEqual(written_offsets, [43], "offset must be update_id + 1")


# ─── Test 10: _process_update — message /start sends keyboard ────────────────


class TestProcessUpdateMessage(unittest.TestCase):
    def test_start_message_sends_keyboard(self):
        """A /start message should trigger _send_with_keyboard."""
        sent = []

        def fake_send(token, chat_id, text):
            sent.append({"chat_id": chat_id, "text": text})
            return True

        update = {
            "update_id": 1,
            "message": {"chat": {"id": 777}, "text": "/start"},
        }

        with mock.patch.object(bc, "_send_with_keyboard", side_effect=fake_send):
            bc._process_update("T", "DEFAULT", update)

        self.assertEqual(len(sent), 1)
        self.assertIn("SPA Bot", sent[0]["text"])


# ─── Test 11: calculate_period_returns — no week data defaults to 0 ──────────


class TestCalculatePeriodReturnsShortCurve(unittest.TestCase):
    def test_no_week_data_returns_zero(self):
        """A 2-bar curve has no data 7 days ago → week_pct == 0.0."""
        curve = [
            {"date": "2026-06-09", "equity": 100_000.0, "daily_return_pct": 0.0},
            {"date": "2026-06-10", "equity": 100_100.0, "daily_return_pct": 0.1},
        ]
        result = bc.calculate_period_returns(curve)
        self.assertEqual(result["week_pct"], 0.0)
        self.assertAlmostEqual(result["alltime_pct"], 0.1, places=2)


if __name__ == "__main__":
    unittest.main()
