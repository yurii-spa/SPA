"""Связность базы знаний — число, а не ощущение (ADR-154).

27.08 сессия трижды не нашла существующее: ADR-125 о старте трёх пакетов, файлы
`hy/lp_paper_trading.json`, ключ `daily_history`. Каждый раз вывод был «этого нет»,
а правильный — «не знаю, где смотреть».

Замер объяснил почему: **1100 заметок, 841 связь, 903 сироты — связность 17.9 %**.
Девять документов из десяти не связаны ни с чем, и найти их можно только угадав имя.
Обратная сторона: `docs/decisions/INDEX.md` держит 109 связей, то есть доступ к решениям
опирается на один файл — в тот же день пушер остановил отправку его локальной версии
с 43 строками вместо 111.

Отдельный урок в самом замере: первая версия считала только `[[wiki]]`-ссылки и дала
41 связь — «граф пустой». Настоящих связей 3288, они записаны обычным markdown. Проверка
одного написания и вывод об отсутствии явления — та же ошибка, что и три предыдущие.
Поэтому тест ниже требует ОБА написания.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_knowledge_graph.py"


def _mod():
    spec = importlib.util.spec_from_file_location("kg", str(_SCRIPT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestBothLinkStyles(unittest.TestCase):
    """Сердце дефекта первой версии."""

    def setUp(self):
        self.m = _mod()

    def _graph(self, files: dict) -> dict:
        with TemporaryDirectory() as t:
            for name, body in files.items():
                p = Path(t) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
            return self.m.build(t)

    def test_wiki_links_are_counted(self):
        g = self._graph({"a.md": "см. [[b]]", "b.md": "текст"})
        self.assertEqual(g["links"], 1)
        self.assertEqual(g["orphans"], 1, "источник ссылки сам остаётся сиротой")

    def test_markdown_links_are_counted_too(self):
        """У нас их 3288 против 41 wiki — версия без них дала неверный ответ."""
        g = self._graph({"a.md": "см. [подробнее](b.md)", "b.md": "текст"})
        self.assertEqual(g["links"], 1)

    def test_a_linked_note_is_not_an_orphan(self):
        g = self._graph({"a.md": "[x](b.md)", "b.md": "т"})
        self.assertEqual(g["linked"], 1)

    def test_connectivity_is_a_percentage_of_reachable_notes(self):
        g = self._graph({"a.md": "[x](b.md)", "b.md": "т", "c.md": "одинокая"})
        self.assertEqual(g["notes"], 3)
        self.assertAlmostEqual(g["connectivity_pct"], 33.3, places=1)


class TestHonestEdges(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_hubs_are_reported_because_they_are_failure_points(self):
        """Концентратор — точка отказа знания, его надо видеть поимённо."""
        with TemporaryDirectory() as t:
            Path(t, "index.md").write_text("[a](a.md) [b](b.md) [c](c.md)", encoding="utf-8")
            for n in "abc":
                Path(t, f"{n}.md").write_text("т", encoding="utf-8")
            g = self.m.build(t)
        self.assertEqual(g["hubs"][0]["note"], "index.md")
        self.assertEqual(g["hubs"][0]["out"], 3)

    def test_copies_of_the_tree_are_excluded(self):
        """worktrees/ и attic/ удвоили бы счёт и исказили долю."""
        self.assertIn("worktrees", self.m.SKIP_DIRS)
        self.assertIn("attic", self.m.SKIP_DIRS)

    def test_an_empty_tree_does_not_divide_by_zero(self):
        with TemporaryDirectory() as t:
            g = self.m.build(t)
        self.assertEqual(g["notes"], 0)
        self.assertEqual(g["connectivity_pct"], 0.0)


class TestBriefingSection(unittest.TestCase):

    def test_missing_data_is_UNCHECKED_not_healthy(self):
        """«Файла нет» ≠ «со связностью всё хорошо» (инвариант #17)."""
        spec = importlib.util.spec_from_file_location(
            "briefing", str(_SCRIPT.parent / "update_system_briefing.py"))
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        from unittest import mock
        with mock.patch.object(b, "read_json", return_value={}):
            out = b.build_knowledge_graph_section()
        self.assertIn("НЕ ИЗМЕРЕНО", out)


if __name__ == "__main__":
    unittest.main()


class TestMandatoryRulesReachable(unittest.TestCase):
    """Обязательное правило обязано быть достижимо по ссылке (ADR-154).

    Замер 27.08: 22 инструкции из 38 недостижимы, и среди них **все четыре правила
    `.claude/rules/`** — те, которые `CLAUDE.md` объявляет обязательными к прочтению.
    Они были упомянуты обратными кавычками, то есть как текст пути: для графа, для
    Obsidian и для любого обхода по связям их не существовало.

    Отдельно — дефект самого генератора: каталоги с точки исключались, поэтому
    `.claude/rules/` не попадали в замер ВООБЩЕ. Связность 17.9 % была посчитана без
    самых обязывающих документов.

    Общая связность может быть любой — база знаний растёт быстрее, чем связывается.
    Недостижимое ПРАВИЛО — дефект: сессия узнает о нём, только угадав путь, а
    угадывание сегодня подвело четыре раза подряд.
    """

    def setUp(self):
        self.m = _mod()

    def test_dot_claude_is_not_excluded(self):
        """Сердце дефекта генератора: правила обязаны попадать в замер."""
        self.assertNotIn(".claude", self.m.SKIP_DIRS)
        with TemporaryDirectory() as t:
            d = Path(t, ".claude", "rules")
            d.mkdir(parents=True)
            (d / "x.md").write_text("правило", encoding="utf-8")
            g = self.m.build(t)
        self.assertEqual(g["notes"], 1, "правило в .claude/ обязано быть посчитано")

    def test_the_root_itself_is_not_required_to_be_linked(self):
        """`CLAUDE.md` — корень: его загружают по соглашению, а не по ссылке.

        Требовать ссылку на корень значило бы искать вход в дом изнутри дома, и
        метрика вечно показывала бы один ложный дефект.
        """
        with TemporaryDirectory() as t:
            Path(t, "CLAUDE.md").write_text("корень", encoding="utf-8")
            g = self.m.build(t)
        self.assertEqual(g["mandatory_unreachable"], [])

    def test_an_unlinked_rule_is_reported_by_name(self):
        """Отказ обязан называть, ЧТО недостижимо — иначе чинить вслепую."""
        with TemporaryDirectory() as t:
            d = Path(t, ".claude", "rules"); d.mkdir(parents=True)
            (d / "risk.md").write_text("правило", encoding="utf-8")
            Path(t, "CLAUDE.md").write_text("текст без ссылок", encoding="utf-8")
            g = self.m.build(t)
        self.assertIn(".claude/rules/risk.md", g["mandatory_unreachable"])

    def test_a_linked_rule_is_reachable(self):
        """Обратный контроль: со ссылкой правило перестаёт быть недостижимым."""
        with TemporaryDirectory() as t:
            d = Path(t, ".claude", "rules"); d.mkdir(parents=True)
            (d / "risk.md").write_text("правило", encoding="utf-8")
            Path(t, "CLAUDE.md").write_text(
                "см. [risk](.claude/rules/risk.md)", encoding="utf-8")
            g = self.m.build(t)
        self.assertEqual(g["mandatory_unreachable"], [])

    def test_the_live_repo_has_all_rules_reachable(self):
        """Положительный контроль на ЖИВОМ дереве — иначе тест проверял бы фикстуру."""
        g = self.m.build()
        self.assertGreaterEqual(g["mandatory_rules"], 4, "правила обязаны находиться")
        self.assertEqual(g["mandatory_unreachable"], [],
                         "недостижимое обязательное правило — дефект")
