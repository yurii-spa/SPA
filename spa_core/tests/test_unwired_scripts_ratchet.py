"""Храповик: скриптов без вызывающего может стать только меньше.

Класс, воспроизведшийся **семь раз за две недели**: код написан, доставлен, покрыт
зелёными тестами — и не вызывается ниоткуда. Kill-switch, не уведомлявший владельца;
erc4626, который никто не звал; производитель `gsm_hours`; генератор changelog'а,
чей раздел на сайте стоял 23 дня. Каждый раз находили вручную, то есть случайно.

Сторож соответствия (ADR-066) ловит АРТЕФАКТ без потребителя. Он не ловит СКРИПТ без
вызывающего — а именно так эти семь и появились.

**Почему храповик, а не запрет.** Скриптов с точкой входа 172, вызывающего нет у 88.
Запрет в лоб покрасил бы половину набора и научил бы его отключать — проект это уже
проходил с литеральными датами (`test_frozen_date_ratchet.py`), и решение там то же:
база зафиксирована и может только уменьшаться.

**База — не список багов.** Часть этих скриптов запускают руками по случаю, и это
нормально. База означает ровно одно: «вызывающий НЕ НАЙДЕН». Разбирать её по одному —
отдельная работа; задача храповика в том, чтобы она не росла.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.tests._unwired import entrypoint_scripts, unwired_scripts

_BASELINE = Path(__file__).resolve().parent / "unwired_scripts_baseline.json"


def _baseline() -> set:
    return set(json.loads(_BASELINE.read_text(encoding="utf-8"))["scripts"])


class TestRatchet(unittest.TestCase):

    def test_no_NEW_unwired_script_appears(self):
        """Главная проверка: новый скрипт обязан быть подключён при рождении."""
        new = sorted(set(unwired_scripts()) - _baseline())
        self.assertEqual(new, [], (
            "новые скрипты с точкой входа, которых никто не вызывает: "
            f"{new}. Подключи их (plist / обёртка / вызов из цикла) либо, если "
            "скрипт запускается руками, объясни это в карточке — но НЕ добавляй "
            "в базу, чтобы погасить падение."))

    def test_the_baseline_does_not_list_scripts_that_are_now_wired(self):
        """Половина, без которой храповик не храповик.

        Как только скрипт подключили, он обязан УЙТИ из базы. Иначе база
        превратится в мусорный список, и первая проверка перестанет что-либо
        значить.
        """
        stale = sorted(_baseline() - set(unwired_scripts()))
        self.assertEqual(stale, [], (
            f"эти скрипты уже подключены — удали их из базы: {stale}"))

    def test_the_baseline_only_names_real_scripts(self):
        """Опечатка в базе тихо ослабила бы проверку на один скрипт."""
        known = {p.stem for p in entrypoint_scripts()}
        ghosts = sorted(_baseline() - known)
        self.assertEqual(ghosts, [], f"в базе имена, которых нет в scripts/: {ghosts}")


class TestTheDetectorItself(unittest.TestCase):
    """Положительный контроль: проверка обязана уметь видеть настоящую связь."""

    def test_a_script_referenced_by_a_wrapper_is_not_reported(self):
        """`run_daily_paper_cycle.sh` зовёт `code_sync_from_origin.sh` — связь есть.

        Берём заведомо подключённый скрипт: если детектор объявит и его сиротой,
        значит он не умеет видеть вызовы вовсе, и вся база — шум.
        """
        wired = {p.stem for p in entrypoint_scripts()} - set(unwired_scripts())
        self.assertTrue(wired, "детектор не нашёл НИ ОДНОГО подключённого скрипта")

    def test_it_does_not_count_tests_as_callers(self):
        """Тест вызывает деталь; вопрос храповика — включена ли она в проводку."""
        import inspect

        from spa_core.tests import _unwired
        src = inspect.getsource(_unwired.unwired_scripts)
        self.assertIn('"/tests/" not in str(p)', inspect.getsource(_unwired),
                      "тесты обязаны быть исключены из числа вызывающих")
        self.assertIn("hay", src)


if __name__ == "__main__":
    unittest.main()
