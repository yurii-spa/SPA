"""Ни один живой производитель не смеет слать КРИТИЧЕСКОЕ через отставленный канал.

Это храповик на КЛАСС, а не на случай. Класс успел выстрелить трижды:

* **10.08, стоп-кран** (`cycle_runner`) — `category="p0"` через `TelegramManager`;
* **10.08, внутридневная проверка** (`cycle_health_monitor`) — то же, и без дублёрки;
* **12.08, здоровье системы** (`scripts/run_health_check.py`) — то же, плюс
  ложный диагноз «cooldown active» поверх.

Каждый раз чинили ЭКЗЕМПЛЯР и заводили тест ровно на него. Следующий
экземпляр рождался в стороне и жил до очередного разбора: тест, написанный
под один файл, ничего не знает о соседнем. Сторож обязан быть ШИРЕ подопечного
(урок #197) — поэтому здесь проверяется всё дерево сразу.

**Почему `TelegramManager` — это про молчание.** Он отставлен в ходе Phase-1
Telegram rebuild: `_send_raw` ВСЕГДА возвращает False и уводит текст в суточный
дайджест. Отправка через него не падает и не жалуется — она просто не
происходит. Единственная инстанция push'а — `spa_core.telegram.push_policy`
с закрытым Tier-1 whitelist.

**Как меряем — AST, а не grep.** Комментарии и строки-рассказы о дефекте
(а их в этих файлах много, и это правильно) для AST невидимы: `TelegramManager`
ищется как ИМЯ в исполняемом коде, `"p0"` — как строковый литерал, равный `p0`
целиком. Иначе храповик краснел бы на разборе аварии ровно тогда, когда авария
устранена, — а ложный отказ учит отключать проверку.

**База может только уменьшаться.** Добавлять сюда файл, чтобы погасить
падение, — запрещено: это и есть тот самый способ, которым класс выживал.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCANNED_ROOTS = ("spa_core", "scripts")

# Каталоги, которые не являются живыми производителями тревог.
_SKIPPED_PARTS = ("/tests/", "/test_", "/__pycache__/")

# Сам отставленный модуль — ПРЕДМЕТ проверки, а не её нарушитель: он обязан
# упоминать и собственный класс, и категорию `p0`, которую демоцирует.
_SUBJECT = "spa_core/alerts/telegram_manager.py"

# ── БАЗА (может только уменьшаться) ─────────────────────────────────────────
# Пусто. После цикла #205 в дереве нет ни одного живого производителя, который
# слал бы критическое через отставленный канал. Если тест покраснел — починить
# производителя, а не дописать его сюда.
BASELINE: frozenset[str] = frozenset()

_CRITICAL_CATEGORIES = {"p0"}


def _iter_modules():
    for root in _SCANNED_ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if any(part in f"/{rel}" for part in _SKIPPED_PARTS):
                continue
            if rel == _SUBJECT:
                continue
            yield rel, path


def _offenders_in(source: str) -> tuple[bool, bool]:
    """`(зовёт отставленный менеджер?, несёт критическую категорию?)`.

    Обе половины — по исполняемому коду. Строка сравнивается на РАВЕНСТВО
    `"p0"`: рассказ про `category="p0"` внутри пояснения — не вызов.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, False

    uses_manager = False
    critical_category = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "TelegramManager":
            uses_manager = True
        elif isinstance(node, ast.Attribute) and node.attr == "TelegramManager":
            uses_manager = True
        elif isinstance(node, ast.alias) and node.name == "TelegramManager":
            uses_manager = True
        elif isinstance(node, ast.Constant) and node.value in _CRITICAL_CATEGORIES:
            critical_category = True
    return uses_manager, critical_category


def _scan() -> set[str]:
    found: set[str] = set()
    for rel, path in _iter_modules():
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "TelegramManager" not in src:
            continue  # дешёвый отсев до разбора AST
        uses_manager, critical = _offenders_in(src)
        if uses_manager and critical:
            found.add(rel)
    return found


class TestNoCriticalAlertRidesTheRetiredChannel(unittest.TestCase):

    def test_the_tree_has_no_offender_outside_the_baseline(self):
        offenders = _scan()
        new = offenders - BASELINE

        self.assertEqual(
            new, set(),
            "критическая тревога уходит через ОТСТАВЛЕННЫЙ канал (он всегда "
            "возвращает False и уводит текст в суточный дайджест). Канонический "
            "путь — spa_core.telegram.push_policy.push_critical с ключом из "
            "Tier-1 whitelist. Дописывать файл в BASELINE ЗАПРЕЩЕНО: именно так "
            f"класс и выживал трижды. Нарушители: {sorted(new)}",
        )

    def test_the_baseline_only_shrinks(self):
        """Запись в базе, которой больше нет в дереве, обязана быть удалена.

        Иначе база превращается в вечное разрешение: файл починили, а строка
        осталась и молча укрывает следующего нарушителя с тем же именем.
        """
        stale = BASELINE - _scan()

        self.assertEqual(
            stale, set(),
            f"эти файлы больше не нарушают — убрать из BASELINE: {sorted(stale)}",
        )


class TestTheRatchetActuallySeesTheBug(unittest.TestCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ. Проверка, не видевшая поломки, — украшение."""

    def test_the_pre_fix_shape_is_caught(self):
        """Дословная форма дефекта 12.08 (цикл #205) до починки."""
        offending = (
            'from spa_core.alerts.telegram_manager import TelegramManager\n'
            'def alert(report, overall):\n'
            '    category = "p0" if overall == "CRITICAL" else "alert"\n'
            '    mgr = TelegramManager()\n'
            '    return mgr.send("health", category=category)\n'
        )

        self.assertEqual(_offenders_in(offending), (True, True))

    def test_the_literal_call_shape_is_caught(self):
        """И прямая форма — без переменной-посредника."""
        offending = (
            'from spa_core.alerts import telegram_manager\n'
            'telegram_manager.TelegramManager().send("x", category="p0")\n'
        )

        self.assertEqual(_offenders_in(offending), (True, True))

    def test_a_story_about_the_bug_is_not_the_bug(self):
        """Контроль В ОБРАТНУЮ СТОРОНУ: разбор аварии краснить не должен.

        Ровно на этом ложном отказе сторож стал бы вредителем: файлы с честным
        разбором (`cycle_runner`, `cycle_health_monitor`, `kill_switch_alert`)
        упоминают и класс, и категорию — в комментариях.
        """
        innocent = (
            '"""Здесь стоял TelegramManager с category="p0" — он отставлен."""\n'
            '# TelegramManager(category="p0") больше не зовётся\n'
            'from spa_core.telegram import push_policy\n'
            'push_policy.push_critical("kill_switch", "CRITICAL", "t", "b")\n'
        )

        self.assertEqual(_offenders_in(innocent), (False, False))

    def test_the_digest_category_is_not_an_offence(self):
        """Дайджест через отставленный менеджер — законно: он туда и уводит."""
        legitimate = (
            'from spa_core.alerts.telegram_manager import TelegramManager\n'
            'TelegramManager().send("сводка", category="daily")\n'
        )

        uses_manager, critical = _offenders_in(legitimate)
        self.assertTrue(uses_manager)
        self.assertFalse(critical)

    def test_the_scan_actually_reaches_the_tree(self):
        """Сканер, ничего не читающий, «зелен» всегда. Мерим, что он смотрит."""
        seen = [rel for rel, _ in _iter_modules()]

        self.assertGreater(len(seen), 200, "обход дерева подозрительно пуст")
        self.assertIn("scripts/run_health_check.py", seen)
        self.assertNotIn(_SUBJECT, seen)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
