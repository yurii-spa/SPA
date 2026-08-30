"""Деловая цель агента не может начинаться с ключа командной строки.

Авария 31.08, и автор её — я сам. Чиня открытый порт у `com.spa.dashboard`, я дописал
в шапку обёртки примечание «`--bind 127.0.0.1` ОБЯЗАТЕЛЕН: http.server по умолчанию
слушает ВСЕ интерфейсы». Выводитель паспортов берёт ПЕРВУЮ прозаическую строку шапки,
отбрасывая строки про механизм запуска. Раньше вся шапка была про запуск и цель честно
НЕ выводилась; моя проза оказалась первой подходящей — и стала «деловой целью».

Вреда два, и второй хуже первого:
  1. в паспорте появилась строка, ничего не говорящая о деле агента;
  2. агент молча ушёл из списка «без деловой цели» — пробел не закрылся, а СПРЯТАЛСЯ.

Признак выбран узкий и не гадательный: цель, начинающаяся с `-` или `--`, — это
примечание к реализации, а не назначение. Расширять эвристику «на вкус» нельзя:
проверка, красящая исправное, живёт до первого неудобного случая.
"""
import importlib.util
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FAP = _ROOT / "scripts" / "fill_agent_passports.py"
# Точный текст, ставший «целью» 31.08 — положительный контроль.
_REGRESSION = "--bind 127.0.0.1 ОБЯЗАТЕЛЕН: http.server по умолчанию слушает ВСЕ интерфейсы."
_FLAGLIKE = re.compile(r"^-{1,2}[A-Za-z]")


def _deriver():
    spec = importlib.util.spec_from_file_location("fap_under_test", _FAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDerivedGoalIsNotAnImplementationNote(unittest.TestCase):

    @unittest.skipUnless(_FAP.is_file(), "выводитель паспортов недоступен")
    def test_no_wrapper_yields_a_flaglike_goal(self):
        m = _deriver()
        bad = []
        wrappers = sorted((_ROOT / "scripts").glob("agent_*.sh"))
        for f in wrappers:
            goal = (m.goal_from_wrapper_header(str(f)) or "").strip()
            if goal and _FLAGLIKE.match(goal):
                bad.append((f.name, goal[:60]))
        self.assertEqual(bad, [], f"примечание к реализации выдано за деловую цель: {bad}")
        # Контроль на украшение: если обёрток нет, проверка выше пуста и бессмысленна.
        self.assertTrue(wrappers, "не найдено ни одной обёртки agent_*.sh")

    def test_the_regression_text_is_recognised(self):
        """Прямой контроль признака на настоящем тексте аварии."""
        self.assertTrue(
            _FLAGLIKE.match(_REGRESSION),
            "признак не узнаёт текст, который 31.08 стал целью — проверка бесполезна")

    def test_a_real_goal_is_not_flagged(self):
        """Обратный контроль: нормальная формулировка не должна ловиться."""
        for good in (
            "отдаёт файлы проекта по HTTP на 127.0.0.1:8767 — локальная витрина",
            "ЦЕЛЬ: считает дневной отчёт и шлёт владельцу",
            "e-mail digest for the owner",
        ):
            self.assertFalse(_FLAGLIKE.match(good), f"ложное срабатывание на: {good}")


if __name__ == "__main__":
    unittest.main()
