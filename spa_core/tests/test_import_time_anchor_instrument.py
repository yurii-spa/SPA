#!/usr/bin/env python3
"""Сторож сторожа: умеет ли прибор `import_time_anchor_bombs` отличить бомбу от честного теста.

Предмет — класс, найденный 12.09: якорь времени вида ``NOW = now_utc()`` на уровне модуля
вычисляется на СБОРЕ набора, а субъект спрашивает часы в момент ВЫПОЛНЕНИЯ. В одиночном
прогоне между ними доли секунды, в полном — полтора часа; запись «120 секунд назад»
оказывается старше получасового окна, и тест краснеет от длительности прогона. Храповик
``frozen_date_baseline.json`` этот фитиль не видит по построению: литеральной даты здесь нет.

Проверка идёт на СИНТЕТИЧЕСКИХ сценах в ``tmp_path``, а не на живом наборе: полный замер
класса стоит две минуты и поднимает второй pytest в том же дереве — это отдельный
инструмент, запускаемый шагом цикла (1г), а не шаг набора.

**Обе стороны обязательны, и вторая важнее.** У прибора уже было ДВЕ неверных редакции,
и обе были зелены на своей же первой стороне:

1. состаривание якоря тест-модуля рассинхронизировало его со значениями по умолчанию
   (``def _beacon(..., now=FIXED_NOW)`` связывается на импорте) — прибор объявил бомбами
   **14 тестов из 14**, у которых часы честно инъектированы;
2. сдвиг часов у одного лишь продукта (тест-помощники исключены) объявлял бомбой ВЕРНУЮ
   починку: она берёт якорь в момент утверждения и обязана получить то же «сейчас», что и
   субъект.

Поэтому сцены здесь три: бомба (обязана быть найдена), починенная бомба и честно
инъектированные часы (обе обязаны остаться чистыми).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "_iab", ROOT / "scripts" / "import_time_anchor_bombs.py")
iab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iab)

#: Задержка сцены — заведомо шире получасового окна дедупа, как и в живом полном прогоне.
LAG_MIN = 95.0

_BOMB = '''
from datetime import timedelta
import json
from spa_core.alerts import telegram_client as tc
from spa_core.tests._freshness import now_utc

NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ — предмет класса


def test_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    p = tmp_path / "alert_history.json"
    p.write_text(json.dumps({"entries": [
        {"ts": (NOW - timedelta(seconds=120)).isoformat(),
         "preview": "повтор"[:tc._PREVIEW_LEN], "ok": True}]}), encoding="utf-8")
    monkeypatch.setattr(tc, "_HISTORY_STATE", p)
    assert tc._duplicate_recently("повтор") is True
'''

#: Та же сцена с починкой: якорь связывается ПЕРЕД тестом, утверждение не тронуто.
_FIXED = _BOMB.replace(
    "NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ — предмет класса",
    "import pytest\n\nNOW = now_utc()\n\n\n"
    "@pytest.fixture(autouse=True)\ndef _anchor():\n    global NOW\n    NOW = now_utc()")

#: Честно инъектированные часы: субъект получает время АРГУМЕНТОМ и часов не спрашивает.
#: Значение по умолчанию связано на импорте — ровно та форма, на которой прибор ошибся.
_INJECTED = '''
from datetime import timedelta
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()


def _age_hours(stamp, now=FIXED_NOW):
    return (now - stamp).total_seconds() / 3600.0


def test_scene():
    assert _age_hours(FIXED_NOW - timedelta(minutes=1)) < 0.5
'''


def _scene(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / f"test_{name}.py"
    p.write_text(body, encoding="utf-8")
    return str(p)


class TheInstrumentTellsABombFromAnHonestTest(unittest.TestCase):
    """Обе стороны: находит настоящую бомбу и молчит на честных часах."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="spa_anchor_scene_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _verdicts(self, body: str, name: str):
        f = [_scene(self.tmp, name, body)]
        return iab.outcomes(f, 0.0, ROOT), iab.outcomes(f, LAG_MIN, ROOT)

    def test_a_real_bomb_is_found(self):
        """Положительный контроль: без него прибор — украшение."""
        base, aged = self._verdicts(_BOMB, "bomb")
        self.assertEqual(base.get("__passed__"), "1",
                         "сцена обязана быть зелёной БЕЗ задержки, иначе она сломана, а не бомба")
        self.assertTrue(any(v == "FAILED" for k, v in aged.items() if k != "__passed__"),
                        "прибор не увидел бомбу — он не отвечает на свой вопрос")

    def test_the_fix_is_not_called_a_bomb(self):
        """Починка обязана пройти: иначе прибор требует ослабить верный тест."""
        base, aged = self._verdicts(_FIXED, "fixed")
        self.assertEqual((base.get("__passed__"), aged.get("__passed__")), ("1", "1"),
                         "верная починка объявлена бомбой — это ошибка ВТОРОЙ редакции прибора")

    def test_an_injected_clock_is_not_called_a_bomb(self):
        """Ошибка ПЕРВОЙ редакции: 14 ложных находок из 14 на этой самой форме."""
        base, aged = self._verdicts(_INJECTED, "injected")
        self.assertEqual((base.get("__passed__"), aged.get("__passed__")), ("1", "1"),
                         "часы инъектированы — длительность прогона не имеет права на них влиять")


class TheInstrumentRefusesInsteadOfGuessing(unittest.TestCase):
    """Инв. #17: не измерено — отдельный исход с названной причиной, а не «чисто»."""

    def test_an_empty_population_is_a_refusal_not_a_clean_answer(self):
        import tempfile
        empty = Path(tempfile.mkdtemp(prefix="spa_anchor_empty_"))
        with self.assertRaises(iab.NotMeasured) as ctx:
            iab.bombs(LAG_MIN, root=empty)
        self.assertIn("население", str(ctx.exception))

    def test_an_unparsable_test_file_is_a_refusal(self):
        import tempfile
        broken = Path(tempfile.mkdtemp(prefix="spa_anchor_broken_"))
        (broken / "spa_core" / "tests").mkdir(parents=True)
        (broken / "spa_core" / "tests" / "test_broken.py").write_text(
            "def f(:\n", encoding="utf-8")
        with self.assertRaises(iab.NotMeasured) as ctx:
            iab.anchored_at_import(broken)
        self.assertIn("не разобраны", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
