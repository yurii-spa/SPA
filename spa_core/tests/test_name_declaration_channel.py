"""Объявление поверхности решения бывает ИМЕНЕМ, а не путём (заказ G56 п. 2).

Заказ G56 п. 2 (хвост [ADR-433](../../docs/decisions/ADR-433-the-population-of-decision-surfaces-is-declared-and-the-comparison-was-textual.md))
назвал изъян прямо: население поверхностей решения измерено ПО ПУТИ ФАЙЛА, а
`RiskConfig`, `ADAPTER_REGISTRY`, `POLLED_ADAPTERS` объявлены правилами ИМЕНЕМ —
и мера их не видит по построению. Пока зазор не назван числом, «объявлено семь»
есть нижняя граница с неизвестной величиной, а не население.

Замер 20.09 на живом дереве дал зазор **пять** и снял вывод предыдущего цикла:
старшая поверхность решения системы (`spa_core/risk/policy.py`) правилами
ОБЪЯВЛЕНА — строкой ``Не менять `RiskConfig` пороги без ADR`` в
`.claude/rules/risk-engine.md`. Её не видела мера, а не репозиторий молчал. И
вторая половина зазора оказалась не про имена вовсе: шесть из пятнадцати
абзацев с языком права изменения мера пути отбрасывает как ШИРОКИЕ, то есть до
их содержимого не доходит ни один канал. Обе половины воспроизведены сценами
ниже.

Каждый тест — обратная сторона одного правила: сцена, где канал обязан
заговорить, и соседняя, где обязан молчать.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import spa_core.monitoring.rule_second_copy_census as rsc
# Помощник сцены берётся у соседних осей, а не пишется заново: вторая копия
# правила «как выглядит дерево сцены» в приборе, который мерит вторые копии,
# была бы ровно тем дефектом, против которого он написан.
from spa_core.tests.test_decision_surface_census import _scene

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=)`
# аргументом; свежести у канала имени нет вовсе, `generated_at` в вердикте не
# участвует, и ни одна сцена не спрашивает часы машины.
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Объявление ИМЕНЕМ: язык права изменения есть, ПУТИ нет ни одного.
_BY_NAME = "Не менять `{name}` пороги без ADR.\n"
#: То же имя БЕЗ языка права изменения — обратная сторона отбора.
_NAME_MENTION_ONLY = "Модуль `{name}` удобно читать целиком.\n"


def _names(root: Path) -> dict:
    return rsc.measure(root, now=_NOW)["name_channel"]


def _row(doc: dict, path: str) -> dict:
    rows = [r for r in doc["surfaces"] if r["path"] == path]
    assert len(rows) == 1, f"{path}: строк {len(rows)}"
    return rows[0]


class ANameIsResolvedByTheTreeNotGuessed(unittest.TestCase):
    """:func:`rsc.toplevel_definitions` и :func:`rsc.resolve_declared_name`."""

    def test_class_function_and_assignment_at_top_level_are_all_indexed(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), files={
                "spa_core/thing.py": ("class RiskConfig:\n    pass\n\n\n"
                                      "def drawdown_tier():\n    return 1\n\n\n"
                                      "ADAPTER_REGISTRY = []\n"
                                      "CAP: float = 1.0\n")})
            index, read, unreadable = rsc.toplevel_definitions(root)
        self.assertEqual(unreadable, [])
        self.assertGreater(read, 0)
        for name in ("RiskConfig", "drawdown_tier", "ADAPTER_REGISTRY", "CAP"):
            self.assertEqual(index.get(name), ["spa_core/thing.py"], name)

    def test_a_name_nested_inside_a_class_is_not_a_top_level_definition(self):
        """Обратная сторона: `RiskConfig.max_apy` объявлением файла не делает."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), files={
                "spa_core/thing.py": "class Holder:\n    INNER = 1\n"})
            index, _read, _unreadable = rsc.toplevel_definitions(root)
        self.assertEqual(index.get("Holder"), ["spa_core/thing.py"])
        self.assertIsNone(index.get("INNER"))

    def test_the_population_is_the_declared_code_trees_only(self):
        """Вложенная рабочая копия именем дерева не является.

        Обход всего дерева подряд втянул бы `.claude/worktrees/` и `attic/`:
        на рабочем Маке таких чекаутов шестьдесят с лишним, и тогда КАЖДОЕ имя
        стало бы неоднозначным — прибор ответил бы о числе копий на диске.
        """
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), files={
                "spa_core/inside.py": "ONLY_HERE = 1\n",
                "attic/outside.py": "ONLY_THERE = 1\n",
                ".claude/worktrees/w/spa_core/inside.py": "ONLY_HERE = 1\n"})
            index, _read, _unreadable = rsc.toplevel_definitions(root)
        self.assertEqual(index.get("ONLY_HERE"), ["spa_core/inside.py"])
        self.assertIsNone(index.get("ONLY_THERE"))

    def test_an_unparseable_file_is_named_not_counted_as_read(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), files={
                "spa_core/broken.py": "def (:\n"})
            index, read, unreadable = rsc.toplevel_definitions(root)
        self.assertEqual([u["path"] for u in unreadable], ["spa_core/broken.py"])
        self.assertTrue(unreadable[0]["reason"])
        self.assertNotIn("broken", str(index))
        self.assertGreater(read, 0)

    def test_a_single_definition_resolves_and_says_which_file(self):
        path, outcome, why = rsc.resolve_declared_name(
            "RiskConfig", {"RiskConfig": ["spa_core/risk/policy.py"]})
        self.assertEqual(path, "spa_core/risk/policy.py")
        self.assertEqual(outcome, rsc.NAME_RESOLVED)
        self.assertIn("spa_core/risk/policy.py", why)

    def test_a_name_defined_by_many_files_names_no_surface(self):
        """`main` определён всюду: догадка о том, какой файл имели в виду, — не мера."""
        path, outcome, why = rsc.resolve_declared_name(
            "main", {"main": ["spa_core/a.py", "scripts/b.py"]})
        self.assertIsNone(path)
        self.assertEqual(outcome, rsc.NAME_AMBIGUOUS)
        self.assertIn("2", why)

    def test_a_name_absent_from_the_tree_is_its_own_outcome(self):
        path, outcome, _why = rsc.resolve_declared_name("Nope", {})
        self.assertIsNone(path)
        self.assertEqual(outcome, rsc.NAME_ABSENT)

    def test_the_three_outcomes_are_distinct(self):
        """Инв. #17 внутри прибора: «нет имени» и «имя у многих» — разные ответы."""
        self.assertEqual(len(set(rsc._NAME_OUTCOMES)), 3)


class OnlyTheLanguageOfTheRightToChangeDeclares(unittest.TestCase):
    """Отбор абзаца — тот же, что у канала пути, и он обязан работать."""

    _FILE = {"spa_core/thing.py": "class Thing:\n    pass\n"}

    def test_a_name_in_a_paragraph_with_the_language_declares(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp),
                                rules={"s.md": _BY_NAME.format(name="Thing")},
                                files=self._FILE))
        self.assertEqual(_row(doc, "spa_core/thing.py")["kind"],
                         rsc.SURFACE_SHELF)

    def test_the_same_name_without_the_language_declares_nothing(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp), rules={"s.md": _NAME_MENTION_ONLY.format(name="Thing")},
                files=self._FILE))
        self.assertEqual([r["path"] for r in doc["surfaces"]], [])
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_NOTHING_NAMED)

    def test_a_backticked_call_is_not_a_name(self):
        """`observed(doc, key)` называет ВЫЗОВ, а не объявление."""
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp),
                rules={"s.md": "Не менять `Thing(doc, key)` без ADR.\n"},
                files=self._FILE))
        self.assertEqual([r["path"] for r in doc["surfaces"]], [])

    def test_a_dotted_module_name_is_not_a_name_at_all_not_a_missing_one(self):
        """Остаток слепоты объявлен, а не умолчан — и это ДВА разных ответа.

        Поверхности не будет в обоих случаях, поэтому «нет строки» свойство не
        пинит: разрешить точки в имени сцена переживёт. Отличает их СЧЁТЧИК —
        `spa_core.thing.Thing` не есть «имя, которого нет в дереве», это вовсе
        не имя, и смешать их значило бы завести в приборе тот самый исход
        «не измерено, выданное за измеренный ноль».
        """
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp),
                rules={"s.md": "Не менять `spa_core.thing.Thing` без ADR.\n"},
                files=self._FILE))
        self.assertEqual([r["path"] for r in doc["surfaces"]], [])
        self.assertEqual(doc["by_outcome"][rsc.NAME_ABSENT], 0)
        self.assertEqual(sum(doc["by_outcome"].values()), 0)
        self.assertTrue(any("ИМЕНЕМ МОДУЛЯ" in b for b in doc["blind"]),
                        doc["blind"])


class TheWideParagraphIsTheOtherHalfOfTheGap(unittest.TestCase):
    """Замер 20.09: шесть из пятнадцати объявлений мера пути НЕ ЧИТАЕТ вовсе.

    Форма воспроизведена дословно: маркированный список
    `.claude/rules/risk-engine.md` идёт без пустых строк, поэтому абзацем
    оказывается весь список — семнадцать строк при пределе
    :data:`rsc.MAX_DECLARING_PARAGRAPH` = 14. В нём стоят И путь, И имя, и
    канал пути молчит об обоих.
    """

    _NAME = "RiskConfig"
    _PATH = "spa_core/governance/kill_switch.py"

    def _wide(self) -> str:
        head = ("- **RiskPolicy v1.0 — единственный hard-гейт.** "
                f"Не менять `{self._NAME}` пороги без ADR.\n"
                f"- Стоп-кран живёт в `{self._PATH}`.\n")
        filler = "".join(f"- строка списка {i}\n"
                         for i in range(rsc.MAX_DECLARING_PARAGRAPH + 1))
        return head + filler

    def _files(self) -> dict:
        return {"spa_core/risk/policy.py": "class RiskConfig:\n    pass\n",
                self._PATH: "HARD_KILL_PCT = 10.0\n"}

    def test_the_path_channel_does_not_read_a_wide_paragraph_at_all(self):
        """Положительный контроль на аварию: путь В АБЗАЦЕ ЕСТЬ, канал нем."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"risk-engine.md": self._wide()},
                          files=self._files())
            doc = rsc.measure(root, now=_NOW)["decision_surfaces"]
        self.assertNotIn(self._PATH, [r["path"] for r in doc["surfaces"]])
        self.assertGreaterEqual(doc["paragraphs_skipped_wide"], 1)

    def test_the_name_channel_reads_it_and_says_the_paragraph_was_wide(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp),
                                rules={"risk-engine.md": self._wide()},
                                files=self._files()))
        row = _row(doc, "spa_core/risk/policy.py")
        where = row["declared_by"][0]
        self.assertEqual(where["named_as"], self._NAME)
        self.assertTrue(where["paragraph_wide"])
        self.assertTrue(where["paragraph_has_path"])

    def test_the_wide_authority_paragraphs_are_counted_separately(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp),
                                rules={"risk-engine.md": self._wide()},
                                files=self._files()))
        self.assertEqual(doc["paragraphs_wide_with_authority"], 1)
        self.assertEqual(doc["paragraphs_authority"], 1)
        self.assertGreaterEqual(doc["paragraphs_wide_total"], 1)

    def test_a_narrow_paragraph_is_not_counted_as_wide(self):
        """Обратная сторона: предел не объявляет широким всё подряд."""
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp), rules={"s.md": _BY_NAME.format(name="RiskConfig")},
                files=self._files()))
        self.assertEqual(doc["paragraphs_wide_with_authority"], 0)
        self.assertEqual(doc["paragraphs_authority"], 1)


class TheGapIsWhatThePathChannelDidNotKnow(unittest.TestCase):
    """`gap` считает ДОБАВЛЕННОЕ, а не всё названное именем."""

    _FILES = {"scripts/caps.py": "CAP_PCT = 7.5\n"}

    def test_a_surface_the_path_channel_already_found_is_not_in_the_gap(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp), rules={"s.md": (
                "Числа `scripts/caps.py` — род «решение»: меняется только новым "
                "ADR, и не менять `CAP_PCT` руками.\n")}, files=self._FILES))
        self.assertEqual(doc["gap"], 0)
        self.assertEqual(doc["already_declared_by_path"], ["scripts/caps.py"])
        self.assertEqual([r["path"] for r in doc["surfaces"]], [])

    def test_the_same_name_without_the_path_beside_it_is_a_gap_of_one(self):
        """Обратная сторона: убрать путь из абзаца — и поверхность новая."""
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp),
                                rules={"s.md": _BY_NAME.format(name="CAP_PCT")},
                                files=self._FILES))
        self.assertEqual(doc["gap"], 1)
        self.assertEqual(doc["already_declared_by_path"], [])
        self.assertEqual([r["path"] for r in doc["surfaces"]],
                         ["scripts/caps.py"])


class TheShiftOfTheNameChannelIsMeasured(unittest.TestCase):
    """Кусается ли добавленное — тем же вопросом, что у канала пути."""

    _GUARD = "CAP = 7.5\n\n\ndef test_it():\n    assert CAP == 7.5\n"
    _EXEC = "CAP = 7.5\n"

    def _scene_for(self, tmp: str, *, declared: str,
                   shelf: str | None = '{"tvl_floor_usd": 1234567.0}') -> dict:
        root = _scene(Path(tmp), shelf=shelf,
                      rules={"s.md": _BY_NAME.format(name="CAP_PCT")},
                      files={"spa_core/tests/test_cap.py": self._GUARD,
                             "spa_core/cap.py": self._EXEC,
                             "scripts/caps.py": declared})
        return _names(root)

    def test_an_unasked_surface_named_only_by_name_is_a_shift(self):
        with TemporaryDirectory() as tmp:
            doc = self._scene_for(tmp, declared="CAP_PCT = 7.5\n")
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_SHIFT)
        row = _row(doc, "scripts/caps.py")
        self.assertFalse(row["asked_today"])
        self.assertEqual(row["would_move"], 1)
        self.assertEqual(row["would_move_names"], ["CAP = 7.5"])
        self.assertEqual(doc["would_move_total"], 1)

    def test_a_pair_already_the_owners_does_not_move_but_the_measure_bites(self):
        with TemporaryDirectory() as tmp:
            doc = self._scene_for(tmp, declared="CAP_PCT = 7.5\n",
                                  shelf='{"cap_pct": 7.5}')
        row = _row(doc, "scripts/caps.py")
        self.assertEqual(row["matches"], 1)
        self.assertEqual(row["would_move"], 0)
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_NO_SHIFT)
        self.assertIn("кусается", doc["reason"])

    def test_a_surface_naming_nothing_moves_nothing_and_says_so(self):
        with TemporaryDirectory() as tmp:
            doc = self._scene_for(tmp, declared="CAP_PCT = 999.25\n")
        row = _row(doc, "scripts/caps.py")
        self.assertEqual(row["matches"], 0)
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_NO_SHIFT)
        self.assertIn("укуса", doc["reason"])

    def test_the_value_is_keyed_by_its_value_not_by_its_spelling(self):
        """Дефект G55 не вернулся через новый канал.

        Расходиться обязаны обе записи сразу: `5_000_000` у находки против
        `5000000.0` у поверхности — ровно та пара, что уходила МЛАДШЕЙ
        поверхности, пока сверка шла текстом литерала. Сцена, где отличается
        только сторона поверхности, свойство НЕ пинит: канонический ключ
        считается там при любой сверке.
        """
        both = "CAP = 5_000_000\n"
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          rules={"s.md": _BY_NAME.format(name="CAP_PCT")},
                          files={"spa_core/tests/test_cap.py":
                                 both + "\n\ndef test_it():\n    assert CAP\n",
                                 "spa_core/cap.py": both,
                                 "scripts/caps.py": "CAP_PCT = 5000000.0\n"})
            doc = _names(root)
        self.assertEqual(_row(doc, "scripts/caps.py")["matches"], 1)


class TheChannelHasItsOwnErrorRate(unittest.TestCase):
    """Контроль базовой частоты: подтверждающий прибор обязан её предъявить.

    Без контроля «канал имени нашёл пять» неотличимо от «обратные кавычки
    разрешаются с такой частотой в любом абзаце».
    """

    def test_paragraphs_without_the_language_feed_the_control_not_the_finding(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp),
                rules={"s.md": _NAME_MENTION_ONLY.format(name="Thing")},
                files={"spa_core/thing.py": "class Thing:\n    pass\n"}))
        self.assertEqual(doc["control_paragraphs"], 1)
        self.assertEqual(doc["control_names"], 1)
        self.assertEqual(doc["control_resolved_single"], 1)
        self.assertEqual(doc["by_outcome"][rsc.NAME_RESOLVED], 0)

    def test_an_authority_paragraph_does_not_feed_the_control(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(
                Path(tmp), rules={"s.md": _BY_NAME.format(name="Thing")},
                files={"spa_core/thing.py": "class Thing:\n    pass\n"}))
        self.assertEqual(doc["control_paragraphs"], 0)
        self.assertEqual(doc["control_resolved_single"], 0)
        self.assertEqual(doc["by_outcome"][rsc.NAME_RESOLVED], 1)


class NothingNamedIsNotTheSameAsNotMeasured(unittest.TestCase):
    """Инв. #17 у самого канала: три исхода, и их нельзя смешивать."""

    def test_a_tree_without_rule_texts_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), files={"spa_core/thing.py": "X = 1\n"})
            doc = rsc.name_channel(root, [], path_candidates=[])
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_UNMEASURED)
        self.assertIn("не прочитан", doc["reason"])
        self.assertEqual(doc["texts_read"], 0)

    def test_a_tree_without_python_files_is_unmeasured_for_another_reason(self):
        """Разрешать имена нечем — и это ДРУГОЙ отказ, а не тот же."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / rsc.RULE_TEXT).write_text(_BY_NAME.format(name="Thing"),
                                              encoding="utf-8")
            doc = rsc.name_channel(root, [], path_candidates=[])
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_UNMEASURED)
        self.assertIn("разрешать имена нечем", doc["reason"])
        self.assertEqual(doc["files_read"], 0)

    def test_rules_read_but_nothing_named_is_a_verdict_of_its_own(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp),
                                rules={"s.md": "Инвариант: не менять руками.\n"},
                                files={"spa_core/thing.py": "X = 1\n"}))
        self.assertEqual(doc["verdict"], rsc.NAME_CHANNEL_NOTHING_NAMED)
        self.assertGreaterEqual(doc["paragraphs_authority"], 1)

    def test_the_four_verdicts_are_distinct(self):
        self.assertEqual(len({rsc.NAME_CHANNEL_SHIFT, rsc.NAME_CHANNEL_NO_SHIFT,
                              rsc.NAME_CHANNEL_NOTHING_NAMED,
                              rsc.NAME_CHANNEL_UNMEASURED}), 4)


class TheChannelReachesTheReader(unittest.TestCase):
    """Число, не доехавшее до шага 0-офис, не измерено ни для кого."""

    def _doc(self, tmp: str) -> dict:
        return rsc.measure(
            _scene(Path(tmp), rules={"s.md": _BY_NAME.format(name="CAP_PCT")},
                   files={"scripts/caps.py": "CAP_PCT = 7.5\n"}), now=_NOW)

    def test_measure_carries_the_channel(self):
        with TemporaryDirectory() as tmp:
            doc = self._doc(tmp)
        self.assertIn("name_channel", doc)
        self.assertEqual(doc["name_channel"]["gap"], 1)

    def test_the_report_names_the_verdict_and_the_declaring_line(self):
        with TemporaryDirectory() as tmp:
            lines = rsc.report(self._doc(tmp))
        text = "\n".join(lines)
        self.assertIn("[КАНАЛ ИМЕНИ]", text)
        self.assertIn("[ИМЕНЕМ · ШКАФ] scripts/caps.py", text)
        self.assertIn("`CAP_PCT`", text)
        self.assertIn("[ШИРОКИЕ АБЗАЦЫ]", text)

    def test_a_document_without_the_coordinate_says_so_instead_of_being_silent(self):
        """Инв. #17 у читателя: отсутствие координаты — не «сдвига нет»."""
        with TemporaryDirectory() as tmp:
            doc = self._doc(tmp)
        doc.pop("name_channel")
        text = "\n".join(rsc.report(doc))
        self.assertIn("[КАНАЛ ИМЕНИ] НЕ ИЗМЕРЕН", text)

    def test_the_error_rate_line_refuses_when_there_is_no_control(self):
        with TemporaryDirectory() as tmp:
            doc = self._doc(tmp)
        doc["name_channel"]["control_paragraphs"] = 0
        text = "\n".join(rsc.report(doc))
        self.assertIn("[ЧАСТОТА ОШИБКИ] НЕ ИЗМЕРЕНА", text)

    def test_the_error_rate_line_states_the_enrichment_when_there_is_one(self):
        with TemporaryDirectory() as tmp:
            doc = self._doc(tmp)
        doc["name_channel"].update({"control_paragraphs": 100,
                                    "control_resolved_single": 5,
                                    "paragraphs_authority": 10,
                                    "by_outcome": {rsc.NAME_RESOLVED: 5}})
        text = "\n".join(rsc.report(doc))
        self.assertIn("обогащает в 10.0 раз(а)", text)


class TheRefutedClaimOfTheEarlierCycleIsWithdrawn(unittest.TestCase):
    """ADR-433 писал «старшая поверхность не объявлена НИКЕМ». Это был вывод о КАНАЛЕ.

    Сцена воспроизводит ровно ту форму: путь `spa_core/risk/policy.py` в
    текстах правил не встречается ни разу, а имя `RiskConfig` — встречается,
    рядом с языком права изменения.
    """

    _RULES = {"risk-engine.md": ("- RiskPolicy v1.0 — единственный hard-гейт.\n"
                                 "- Не менять `RiskConfig` пороги без ADR.\n")}
    _FILES = {"spa_core/risk/policy.py": "class RiskConfig:\n    min_x = 1\n"}

    def test_the_path_channel_still_says_the_path_is_never_named(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules=self._RULES, files=self._FILES)
            doc = rsc.measure(root, now=_NOW)["decision_surfaces"]
        asked = [a for a in doc["asked"] if a["path"] == rsc.RISK_POLICY_MODULE]
        self.assertEqual(len(asked), 1)
        self.assertFalse(asked[0]["declared_by_rules"])
        self.assertEqual(asked[0]["mentions_in_rules"], 0)

    def test_the_name_channel_finds_the_declaration_the_path_channel_missed(self):
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp), rules=self._RULES, files=self._FILES))
        row = _row(doc, rsc.RISK_POLICY_MODULE)
        self.assertEqual(row["declared_by"][0]["named_as"], "RiskConfig")
        self.assertEqual(row["declared_by"][0]["text"],
                         f"{rsc.RULE_DIR}/risk-engine.md")
        self.assertTrue(row["asked_today"])

    def test_an_asked_surface_cannot_move_a_pair_by_construction(self):
        """И это не «сдвига нет»: у спрашиваемой поверхности он нулевой всегда."""
        with TemporaryDirectory() as tmp:
            doc = _names(_scene(Path(tmp), rules=self._RULES, files=self._FILES))
        self.assertEqual(_row(doc, rsc.RISK_POLICY_MODULE)["would_move"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
