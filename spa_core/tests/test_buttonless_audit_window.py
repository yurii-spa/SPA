"""Утверждение о полноте над КОЛЬЦЕВЫМ журналом обязано назвать своё окно.

Второй носитель класса ADR-322, найденный переписью #563 (заказ #562).

`_scan_channel_buttons` был fail-CLOSED по каждому отказу, который автор себе
представил: журнала нет, журнал не читается, скан упал — у всех троих
`measured=False` и причина словами. Не представлен был ровно один: журнал **на
месте, читается и выглядит целым, а на деле срезан**. `alert_history.json` есть
кольцевой буфер `max_entries=500`, и на день замера он ПОЛОН — 500 из 500,
раньше 2026-08-16 журнал не помнит ничего, а сам этот день срезан с головы.

Над таким журналом печаталось «сообщения с вариантами: N, все с кнопками» — и
читалось как «такого не бывало», а означало «в пределах удержанного окна».

FROZEN-DATE-OK: даты здесь — ПРЕДМЕТ проверки. Сравниваются они только между
собой (минимальная = граница окна), стенных часов ни одна ветка не читает,
понятия свежести у измерителя окна нет.
"""
# FROZEN-DATE-OK: даты здесь ЕСТЬ ПРЕДМЕТ проверки — измеритель окна сравнивает их
# только между собой (минимальная = граница журнала), стенных часов не читает,
# понятия свежести у него нет. Календарь сдвинется — вердикт не изменится.
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.owner_decision_pending import _journal_window, _scan_channel_buttons
from spa_core.telegram.buttonless_audit import scan, summary_line


def _entry(**kw):
    base = {"ts": "2026-08-16T09:00:00+00:00", "ok": True, "preview": "текст"}
    base.update(kw)
    return base


def _clean_report(window=None):
    """Отчёт, в котором нечего находить: ровно та ветка, что утверждает полноту."""
    rep = scan([_entry(offers_choice=True, buttons=True)])
    assert rep["buttonless_count"] == 0
    if window is not None:
        rep["window"] = window
    return rep


class TotalityClaimNamesItsWindow(unittest.TestCase):

    def test_saturated_window_qualifies_the_clean_verdict(self):
        """Положительный контроль: ровно та строка, что печаталась без оговорки."""
        line = summary_line(_clean_report({
            "measured": True, "saturated": True, "boundary_day": "2026-08-16",
            "declared_cap": 500, "records": 500}))
        self.assertIn("все с кнопками", line)          # находок и правда нет
        self.assertIn("окно журнала СРЕЗАНО", line)     # но полнота — лишь внутри окна
        self.assertIn("2026-08-16", line)

    def test_whole_journal_adds_no_noise(self):
        """Окно названо и НЕ полно ⇒ утверждение о полноте верно как есть.

        Без этого контроля оговорка была бы истинной по построению и висела бы
        над любым журналом — то есть перестала бы что-либо означать.
        """
        line = summary_line(_clean_report({
            "measured": True, "saturated": False, "boundary_day": "2026-08-16",
            "declared_cap": 500, "records": 12}))
        self.assertIn("все с кнопками", line)
        self.assertNotIn("окно журнала", line)

    def test_missing_window_block_is_named_unmeasured(self):
        """Отчёт старого образца не имеет права выглядеть как доказанно целый."""
        line = summary_line(_clean_report())
        self.assertIn("окно журнала НЕ ИЗМЕРЕНО", line)

    def test_unnamed_window_is_not_reported_as_whole(self):
        line = summary_line(_clean_report({
            "measured": True, "saturated": None, "boundary_day": "2026-08-16"}))
        self.assertIn("окно журнала НЕ НАЗВАНО", line)

    def test_failed_window_measurement_carries_its_reason(self):
        line = summary_line(_clean_report({"measured": False, "reason": "буфер не прочитан"}))
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("буфер не прочитан", line)


class WindowMeasuredAtTheRealCaller(unittest.TestCase):
    """Эффект проверяется ТЕМ ЖЕ вызовом, каким его получает шаг 0-офис."""

    def _data_dir(self, td, entries, **doc_extra):
        data = Path(td)
        doc = {"entries": entries}
        doc.update(doc_extra)
        (data / "alert_history.json").write_text(json.dumps(doc), encoding="utf-8")
        return data

    def test_saturated_journal_reports_a_truncated_window(self):
        entries = [_entry(ts=f"2026-08-{16 + i // 3:02d}T0{i % 3}:00:00+00:00",
                          offers_choice=True, buttons=True) for i in range(9)]
        with tempfile.TemporaryDirectory() as td:
            out = _scan_channel_buttons(self._data_dir(td, entries, max_entries=9))
        self.assertTrue(out["measured"])
        win = out["window"]
        self.assertIs(win["saturated"], True)
        self.assertEqual(win["boundary_day"], "2026-08-16")
        self.assertTrue(win["boundary_day_records_is_floor"])
        self.assertIn("окно журнала СРЕЗАНО", summary_line(out))

    def test_unsaturated_journal_reports_a_whole_window(self):
        entries = [_entry(offers_choice=True, buttons=True) for _ in range(3)]
        with tempfile.TemporaryDirectory() as td:
            out = _scan_channel_buttons(self._data_dir(td, entries, max_entries=500))
        self.assertIs(out["window"]["saturated"], False)
        self.assertFalse(out["window"]["boundary_day_records_is_floor"])

    def test_journal_without_a_declared_cap_is_third_outcome(self):
        entries = [_entry(offers_choice=True, buttons=True) for _ in range(3)]
        with tempfile.TemporaryDirectory() as td:
            out = _scan_channel_buttons(self._data_dir(td, entries))
        self.assertIsNone(out["window"]["saturated"])
        self.assertIsNot(out["window"]["saturated"], False)

    def test_window_measurement_never_breaks_the_guard(self):
        """Уточнение не имеет права уронить сторожа, который оно уточняет."""
        self.assertFalse(_journal_window(object(), "не список")["measured"] is None)
        self.assertIsInstance(_journal_window({"entries": []}, []), dict)

    def test_missing_journal_is_still_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as td:
            out = _scan_channel_buttons(Path(td))
        self.assertFalse(out["measured"])
        self.assertIn("отсутствует", out["reason"])


if __name__ == "__main__":
    unittest.main()
