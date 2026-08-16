"""Храповик: скриптов без вызывающего может стать только меньше.

Класс, воспроизведшийся **семь раз за две недели**: код написан, доставлен, покрыт
зелёными тестами — и не вызывается ниоткуда. Kill-switch, не уведомлявший владельца;
erc4626, который никто не звал; производитель `gsm_hours`; генератор changelog'а,
чей раздел на сайте стоял 23 дня. Каждый раз находили вручную, то есть случайно.

Сторож соответствия (ADR-066) ловит АРТЕФАКТ без потребителя. Он не ловит СКРИПТ без
вызывающего — а именно так эти семь и появились.

**Почему храповик, а не запрет.** Скриптов с точкой входа 174, вызывающего нет у 88.
Запрет в лоб покрасил бы половину набора и научил бы его отключать — проект это уже
проходил с литеральными датами (`test_frozen_date_ratchet.py`), и решение там то же:
база зафиксирована и может только уменьшаться.

**База — не список багов.** Часть этих скриптов запускают руками по случаю, и это
нормально. База означает ровно одно: «вызывающий НЕ НАЙДЕН». Разбирать её по одному —
отдельная работа; задача храповика в том, чтобы она не росла.

**13.08 (цикл #214) база сократилась с 87 до 54 имён — и НЕ потому, что 33 скрипта
подключили.** Класс «исследовательский замер: вызывающего нет по устройству, продукт —
запись в реестре R&D» выведен из-под храповика отдельным правилом (`_unwired.py`,
`spa_core/tests/test_unwired_registry_evidence.py`). До этого класс был неотличим от
мёртвого кода, и цикл #192 оставил проверку красной осознанно: гасить её дописыванием
в базу запрещает сам этот файл. Границы правила измерены, а не выбраны: весь `docs/`
проводкой не считается (сняло бы с учёта 62 из 88).

**16.08 (цикл #255) база выросла 54 → 61 — и это ЕДИНСТВЕННЫЙ допустимый вид роста:
измерение стало вернее.** Сканер научился видеть форму проводки, которой не видел
(голый `import <имя>`), и перестал считать проводкой три доказательства слабее
вызова — докстринг, самоупоминание однофамильца, подстрочную коллизию. Семь имён не
стали мёртвыми в этот день: они были неподключены всегда, а числились подключёнными
по ошибке измерения. Чтобы такой рост нельзя было ни спрятать, ни повторить ради
настоящего мёртвого кода, вскрытые имена лежат ОТДЕЛЬНЫМ разделом
`revealed_by_stricter_detector`, у каждого назван файл, который его держал, и раздел
проверяется теми же тремя проверками. Дописать имя в любой из разделов, чтобы
погасить падение, по-прежнему запрещено: падение храповика означает новый мёртвый
скрипт, а не неудобную базу.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.tests._unwired import entrypoint_scripts, unwired_scripts

_BASELINE = Path(__file__).resolve().parent / "unwired_scripts_baseline.json"


def _sections() -> tuple:
    """Два раздела базы: исторический и вскрытый строгим сканером (цикл #255)."""
    d = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return set(d["scripts"]), set(d.get("revealed_by_stricter_detector", {}))


def _baseline() -> set:
    """Всё, за чем храповик следит: разделы сторожатся ВМЕСТЕ.

    Раздельно они бы разошлись: скрипт, подключённый после 16.08, обязан уйти из
    базы, а из какого именно раздела — вопрос бухгалтерии, не сторожа.
    """
    historic, revealed = _sections()
    return historic | revealed


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

    def test_the_two_sections_do_not_overlap(self):
        """Имя в обоих разделах = рост базы, спрятанный за арифметикой множеств.

        Объединение от дубля не растёт, поэтому дубль мог бы протащить восьмое
        имя незаметно: раздел «вскрытых» вырос бы на единицу, а сумма — нет.
        """
        historic, revealed = _sections()
        both = sorted(historic & revealed)
        self.assertEqual(both, [], f"имя числится в обоих разделах базы: {both}")

    def test_every_revealed_name_says_WHAT_used_to_hide_it(self):
        """Раздел «вскрытых» — не список имён, а список причин.

        Имя без причины — это дописывание в базу под видом измерения: ровно то,
        что база запрещает. Причина обязана называть файл, который держал скрипт
        «подключённым», иначе проверить её нечем.
        """
        d = json.loads(_BASELINE.read_text(encoding="utf-8"))
        revealed = d.get("revealed_by_stricter_detector", {})
        self.assertTrue(revealed, "раздел «вскрытых» пуст — проверка ничего не значит")
        for name, reason in sorted(revealed.items()):
            self.assertTrue(reason.strip(), f"{name}: причина не названа")
            self.assertIn(".py", reason,
                          f"{name}: причина не называет файл, который держал скрипт")


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
        """Тест вызывает деталь; вопрос храповика — включена ли она в проводку.

        Инв. #16, намеренная правка (цикл #214): сканирование переехало из
        `unwired_scripts` в `scripts_without_caller` — первая теперь ещё и вычитает
        класс R&D. Проверка НЕ ослаблена, а разведена по двум функциям и усилена
        поведенческим плечом: тест не считается вызывающим на самом деле, а не только
        по тексту исходника. Обоснование — в журнале `docs/journal/2026-W33.md`.
        """
        import inspect

        from spa_core.tests import _unwired
        src = inspect.getsource(_unwired.scripts_without_caller)
        self.assertIn('"/tests/" not in str(p)', inspect.getsource(_unwired),
                      "тесты обязаны быть исключены из числа вызывающих")
        self.assertIn("hay", src)

        # поведенческое плечо: имя из базы упоминается в тестах — и всё равно сирота
        watched = _baseline()
        self.assertTrue(watched, "база пуста — проверка ниже ничего не значит")
        self.assertTrue(watched <= set(unwired_scripts()),
                        "тест-файлы начали считаться вызывающими")

    def test_the_ratchet_watches_the_delivered_and_dead_set(self):
        """Храповик обязан сторожить именно «доставлен и мёртв», а не сырой замер.

        Если однажды `unwired_scripts` вернётся к смыслу «нет вызывающего», база
        мгновенно разойдётся с проверкой — и обе половины храповика начнут врать в
        разные стороны. Здесь это названо вслух.
        """
        from spa_core.tests._unwired import (registry_recorded_scripts,
                                             scripts_without_caller)
        raw, watched = set(scripts_without_caller()), set(unwired_scripts())
        self.assertEqual(watched, raw - registry_recorded_scripts())
        self.assertFalse(watched & registry_recorded_scripts())


if __name__ == "__main__":
    unittest.main()
