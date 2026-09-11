"""Владелец видит «н/д», а не «$0.00», когда числа в снимке нет (ADR-344).

Инвариант #17 в самом видимом месте: бот — канал, которым владелец смотрит на
трек. Строка `float(st.get("current_equity", 0.0) or 0.0)` показывала **$0.00**
и при пустом снимке, и при настоящем нуле, и отличить одно от другого владелец
не мог ничем.

Часов в тестах нет: сцены — это документы на диске, вердикт от календаря не зависит.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.telegram import bot as B


class Formatters(unittest.TestCase):
    def test_absence_renders_as_not_available(self):
        self.assertEqual(B._na_usd(None), "н/д")
        self.assertEqual(B._na_pct(None), "н/д")

    def test_a_measured_zero_still_renders_as_zero(self):
        self.assertEqual(B._na_usd(0.0), "$0.00")
        self.assertEqual(B._na_pct(0.0), "0.00%")
        self.assertEqual(B._na_pct(0.0, 3), "0.000%")


class StatusAndToday(unittest.TestCase):
    """Сцены `/status` и `/today` на снимке БЕЗ полей и на снимке с нулями."""

    def _bot(self, data_dir: Path):
        bot = object.__new__(B.TelegramBot)   # без поллера: нужен только рендер
        self.sent: list = []
        bot.send_message = lambda text, chat_id=None, **kw: self.sent.append(text)
        bot._status_keyboard = lambda: None
        return bot

    def _run(self, status_doc, method):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "paper_trading_status.json").write_text(json.dumps(status_doc),
                                                         encoding="utf-8")
            with mock.patch.object(B, "DATA_DIR", d), \
                    mock.patch.object(B, "KILL_SWITCH_FILE", d / "kill_switch_active.json"):
                getattr(self._bot(d), method)("chat")
        return self.sent[-1] if self.sent else ""

    def test_status_without_equity_says_not_available(self):
        text = self._run({}, "cmd_status")
        self.assertIn("Equity: н/д", text)
        self.assertNotIn("Equity: $0.00", text)

    def test_status_with_a_measured_zero_shows_zero(self):
        text = self._run({"current_equity": 0.0, "total_return_pct": 0.0,
                          "apy_today_pct": 0.0, "daily_yield_usd": 0.0}, "cmd_status")
        self.assertIn("Equity: $0.00", text)
        self.assertIn("APY Today: 0.00%", text)

    def test_today_without_numbers_says_not_available(self):
        text = self._run({}, "cmd_today")
        self.assertIn("н/д", text)
        self.assertNotIn("APY Today: 0.00%", text)

    def test_today_with_measured_zeroes_shows_them(self):
        text = self._run({"daily_return_pct": 0.0, "daily_yield_usd": 0.0,
                          "apy_today_pct": 0.0, "current_equity": 100_000.0},
                         "cmd_today")
        self.assertIn("APY Today: 0.00%", text)
        self.assertIn("Equity: $100,000.00", text)


if __name__ == "__main__":
    unittest.main()
