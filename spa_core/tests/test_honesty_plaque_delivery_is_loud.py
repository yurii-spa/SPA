"""Провал доставки таблички честности обязан быть слышен.

Замерено 09.08. У сайта есть правило честности: если показанная доходность выше
живого расчёта, сторож вешает табличку «данные под сомнением». Правило сработало и
записало флаг — **но на сайт табличка не уехала, молча**:

* публичный сайт: **5.2 %**, таблички нет;
* живой расчёт в тот же момент: **4.83 %**;
* у нас на диске: `degraded: true` — система считала сайт уже помеченным.

Причина в коде: обе ветки звали пушер и **не читали код возврата**, после чего
печатали «+ pushed» безусловно. Пуш упирался в стража перезаписи, возвращал отказ,
и отказ не читал никто.

Класс, который проект закрывает годами: сторож честно отвечает на свой вопрос («флаг
записан»), а читают его как ответ на нужный («табличка на сайте»). Лечится не
эскалацией, а тем, что провал перестаёт быть тихим.

Эти тесты НЕ решают owner-gated половину (пропуск таблички через гейт — решение
владельца). Они закрывают только молчание, которого не решал никто.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "site_freshness_monitor", str(_REPO / "scripts" / "site_freshness_monitor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFailureIsLoud(unittest.TestCase):

    def setUp(self):
        self.mod = _load()

    def _run(self, rc: int, fn: str, snap: dict):
        """Прогон ветки доставки при условии «доставить ОТСЮДА можно».

        Почему условие теперь названо вслух (цикл #228, 14.08; инвариант #16 —
        изменение теста намеренное и обоснованное). Все четыре проверки ниже — про
        одно: пушер ОТРАБОТАЛ и вернул код. Раньше это подразумевалось молча, а
        снимок жил во временном каталоге — то есть тест описывал среду, в которой
        доставка невозможна в принципе, и при этом требовал поведения «пушер
        сходил». Пока веток было две, разницы не было; с 14.08 она есть и стоит
        владельцу четырёх одинаковых тревог в сутки (см.
        ``test_site_freshness_delivery_route.py``). Предусловие зафиксировано
        явно — проверки при этом НЕ ослаблены: ни один ассерт не изменён и не снят,
        добавилась только среда, в которой они осмысленны.
        """
        alerts = []
        with TemporaryDirectory() as t:
            path = Path(t) / "track_snapshot.json"
            path.write_text(json.dumps(snap), encoding="utf-8")
            with mock.patch.object(self.mod, "_SNAP", path), \
                 mock.patch.object(self.mod, "_delivery_possible",
                                   lambda *a, **k: (True, "")), \
                 mock.patch.object(self.mod, "_alert", lambda r: alerts.append(r)), \
                 mock.patch.object(self.mod.subprocess, "run",
                                   return_value=mock.Mock(returncode=rc)):
                getattr(self.mod, fn)()
            written = json.loads(path.read_text(encoding="utf-8"))
        return alerts, written

    def test_a_refused_push_raises_an_alert(self):
        """Сердце дефекта: отказ обязан дойти до человека."""
        alerts, _ = self._run(5, "_apply_degrade", {"degraded": False})
        self.assertTrue(alerts, "отказ доставки обязан поднимать тревогу")
        blob = json.dumps(alerts, ensure_ascii=False)
        self.assertIn("HONESTY_PLAQUE_UNDELIVERED", blob)

    def test_a_successful_push_is_silent(self):
        """Тревога на успехе обесценила бы тревогу на провале."""
        alerts, _ = self._run(0, "_apply_degrade", {"degraded": False})
        self.assertEqual(alerts, [])

    def test_the_recovery_branch_is_guarded_too(self):
        """Обе ветки — иначе копии разойдутся при первой правке."""
        alerts, _ = self._run(5, "_clear_degrade", {"degraded": True})
        self.assertTrue(alerts, "снятие таблички обязано проверяться так же, как постановка")

    def test_the_local_flag_still_records_the_truth(self):
        """Провал доставки не отменяет верного локального вывода.

        Флаг остаётся: система ЗНАЕТ, что расхождение есть. Проблема была не в
        знании, а в том, что незнание сайта никому не сообщалось.
        """
        _, written = self._run(5, "_apply_degrade", {"degraded": False})
        self.assertIs(written["degraded"], True)


class TestBothBranchesUseOneHelper(unittest.TestCase):
    """Две копии контракта расходятся при первой правке — здесь копия одна."""

    def test_no_direct_pusher_call_remains(self):
        text = (_REPO / "scripts" / "site_freshness_monitor.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("push_to_github_batch.py"), 1,
                         "вызов пушера обязан остаться единственным — в помощнике")


if __name__ == "__main__":
    unittest.main()
