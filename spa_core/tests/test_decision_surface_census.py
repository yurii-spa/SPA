"""Население ПОВЕРХНОСТЕЙ РЕШЕНИЯ объявлено, а не известно автору (заказ G55 п. 1).

Заказ G55 п. 1 (хвост [ADR-432](../../docs/decisions/ADR-432-the-right-to-fix-was-asked-of-one-surface-out-of-two.md))
назвал изъян прямо: право чинить спрашивается у ДВУХ поверхностей решения, а
сколько их в репозитории — не измерено ни разу; витрина порогов найдена потому,
что о ней ЗНАЛ автор третьей оси. Пока население не названо, «право чинить
спрошено» есть утверждение об известных поверхностях, а не обо всех.

Каждый тест ниже — обратная сторона одного правила: сцена, где перепись обязана
заговорить, и соседняя, где обязана молчать. Отдельно проверяется то, что
замер вскрыл по дороге: сверка величины шла ТЕКСТОМ, и ответ на вопрос «кому
принадлежит это число» зависел от того, поставил автор десятичную точку или
нет (:func:`rsc.value_key`).
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import spa_core.monitoring.rule_second_copy_census as rsc
# Помощник сцены берётся у соседней оси, а не пишется заново: вторая копия
# правила «как выглядит дерево сцены» в приборе, который мерит вторые копии,
# была бы ровно тем дефектом, против которого он написан.
from spa_core.tests.test_rule_second_copy_peer_axis import _tree

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=)`
# аргументом; свежести у переписи нет вовсе, `generated_at` в вердикте не
# участвует, и ни одна сцена не спрашивает часы машины.
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Правило-объявление сцены: путь назван вместе с языком ПРАВА ИЗМЕНЕНИЯ.
_DECLARING = ("Числа этого файла — род «решение»: `{path}` меняется только "
              "новым ADR.\n")
#: То же упоминание БЕЗ права изменения. Обратная сторона отбора.
_MENTION_ONLY = "Страница берёт числа из `{path}` — это удобно.\n"


def _scene(base: Path, *, rules: dict | None = None, claude: str | None = None,
           files: dict | None = None, **kw) -> Path:
    """Дерево сцены плюс ТЕКСТЫ ПРАВИЛ, которыми объявляются поверхности.

    `_tree` общий, и его поведение не меняется ни на байт: правила и файлы
    дописываются рядом. Пути здесь пишутся как есть (`spa_core/caps.json`), а
    не склейкой `__`: расширение у файла сцены — часть предмета (шкаф `.json`
    и модуль `.py` читаются разными разборщиками), и потерять его молча
    значило бы мерить пустое дерево вместо сцены.
    """
    root = _tree(base, **kw)
    if claude is not None:
        (root / rsc.RULE_TEXT).write_text(claude, encoding="utf-8")
    if rules:
        rules_dir = root / rsc.RULE_DIR
        rules_dir.mkdir(parents=True, exist_ok=True)
        for name, text in rules.items():
            (rules_dir / name).write_text(text, encoding="utf-8")
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _surfaces(root: Path) -> dict:
    return rsc.measure(root, now=_NOW)["decision_surfaces"]


def _by_path(doc: dict, path: str) -> dict:
    rows = [r for r in doc["surfaces"] if r["path"] == path]
    assert len(rows) == 1, f"{path}: строк {len(rows)}"
    return rows[0]


class TheValueOfANumberIsNotItsSpelling(unittest.TestCase):
    """Канонический ключ величины (:func:`rsc.value_key`).

    Дефект, ради которого функция заведена, измерен на живом дереве 20.09:
    девять пар меняли ответ о праве чинить из-за формы литерала, а не из-за
    величины. Это свойство ПРИБОРА, выданное за свойство дерева, — тот же
    класс, что структурный ноль ADR-431.
    """

    def test_every_spelling_of_one_number_gives_one_key(self):
        keys = {rsc.value_key(v) for v in
                ("5000000", "5000000.0", "5_000_000", "5e6", 5000000, 5e6)}
        self.assertEqual(len(keys), 1, keys)

    def test_a_non_number_keeps_its_text(self):
        self.assertEqual(rsc.value_key("'SILENT'"), "'SILENT'")
        self.assertEqual(rsc.value_key("v1.0"), "v1.0")
        self.assertEqual(rsc.value_key("(0, 8, 13)"), "(0, 8, 13)")

    def test_declared_names_answers_by_value_not_by_text(self):
        mapping = {rsc.value_key(10.0): ["kill_switch.hard_kill_pct"]}
        self.assertEqual(rsc.declared_names(mapping, "10"),
                         ["kill_switch.hard_kill_pct"])
        self.assertEqual(rsc.declared_names(mapping, "10.0"),
                         ["kill_switch.hard_kill_pct"])

    def test_declared_names_still_answers_a_hand_built_mapping(self):
        """Сцена, подающая словарь руками, не обязана знать про ключи."""
        self.assertEqual(rsc.declared_names({"v1.0": ["version"]}, "v1.0"),
                         ["version"])

    def test_declared_names_is_silent_where_the_value_is_absent(self):
        self.assertEqual(rsc.declared_names({"10.0": ["x"]}, "11"), [])

    def test_the_threshold_with_underscores_is_found_by_the_plain_number(self):
        """`min_tvl_usd = 5_000_000` против `MIN_ELIGIBLE_TVL = 5000000.0`.

        Ровно эта пара уходила МЛАДШЕЙ поверхности решения (замер 20.09).
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core" / "risk").mkdir(parents=True)
            (root / "spa_core" / "risk" / "policy.py").write_text(
                "min_tvl_usd: float = 5_000_000\n", encoding="utf-8")
            thresholds = rsc.risk_policy_thresholds(root)
        self.assertEqual(rsc.declared_names(thresholds, "5000000.0"),
                         ["min_tvl_usd"])

    def test_a_string_version_is_not_a_threshold(self):
        """Обратная сторона: строка порогом не становится ни при какой сверке."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core" / "risk").mkdir(parents=True)
            (root / "spa_core" / "risk" / "policy.py").write_text(
                "version: str = 'v1.0'\nmin_cash_pct: float = 0.05\n",
                encoding="utf-8")
            thresholds = rsc.risk_policy_thresholds(root)
        self.assertEqual(rsc.declared_names(thresholds, "'v1.0'"), [])
        self.assertEqual(rsc.declared_names(thresholds, "0.05"), ["min_cash_pct"])

    def test_the_shelf_answers_a_whole_number_written_with_a_point(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "landing" / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "constitution.json").write_text(
                json.dumps({"kill_switch": {"hard_kill_pct": 10.0}}),
                encoding="utf-8")
            values, unread = rsc.constitution_values(root)
        self.assertIsNone(unread)
        self.assertEqual(rsc.declared_names(values, "10"),
                         ["kill_switch.hard_kill_pct"])


class ADeclarationIsAParagraphOfARuleWithTheRightToChange(unittest.TestCase):
    """Что считается ОБЪЯВЛЕНИЕМ поверхности, и что им не считается."""

    def test_a_path_named_with_the_right_to_change_is_a_candidate(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          rules={"caps.md": _DECLARING.format(
                              path="spa_core/caps.json")},
                          files={"spa_core/caps.json": '{"cap_pct": 7.5}'})
            doc = _surfaces(root)
        row = _by_path(doc, "spa_core/caps.json")
        self.assertEqual(row["kind"], rsc.SURFACE_SHELF)
        evidence = row["declared_by"][0]
        self.assertEqual(evidence["text"], ".claude/rules/caps.md")
        self.assertEqual(evidence["line"], 1)
        self.assertIn("caps.json", evidence["quote"])

    def test_a_path_named_without_the_right_to_change_is_not_a_candidate(self):
        """Обратная сторона: упоминание объявлением не является."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          rules={"caps.md": _MENTION_ONLY.format(
                              path="spa_core/caps.json")},
                          files={"spa_core/caps.json": '{"cap_pct": 7.5}'})
            doc = _surfaces(root)
        self.assertEqual([r["path"] for r in doc["surfaces"]
                          if r["path"] == "spa_core/caps.json"], [])

    def test_a_wide_paragraph_is_not_a_declaration_and_is_counted(self):
        """Строка реестра называет всё подряд — и это НЕ улика, но и не тишина."""
        wide = ("x" * (rsc.MAX_DECLARING_LINE + 1)
                + " `spa_core/caps.json` меняется только новым ADR\n")
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"caps.md": wide},
                          files={"spa_core/caps.json": '{"cap_pct": 7.5}'})
            doc = _surfaces(root)
        self.assertEqual(doc["candidates"], 0)
        self.assertEqual(doc["paragraphs_skipped_wide"], 1)

    def test_a_long_paragraph_is_not_a_declaration_either(self):
        long_block = "\n".join(
            ["строка нарратива"] * (rsc.MAX_DECLARING_PARAGRAPH + 1)
            + ["`spa_core/caps.json` меняется только новым ADR"]) + "\n"
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"caps.md": long_block},
                          files={"spa_core/caps.json": '{"cap_pct": 7.5}'})
            doc = _surfaces(root)
        self.assertEqual(doc["candidates"], 0)
        self.assertEqual(doc["paragraphs_skipped_wide"], 1)

    def test_a_relative_tail_is_resolved_by_the_tree(self):
        """Правило пишет `lib/constitution.json` — хвост, а не путь от корня."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"site.md": _DECLARING.format(
                path="lib/constitution.json")})
            doc = _surfaces(root)
        row = _by_path(doc, rsc.CONSTITUTION_FILE)
        self.assertEqual(row["declared_by"][0]["named_as"],
                         "lib/constitution.json")
        self.assertIn("хвост разрешён", row["declared_by"][0]["resolution"])

    def test_an_ambiguous_tail_is_its_own_outcome(self):
        """«Неоднозначен» и «в дереве нет» — разные ответы (инв. #17)."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"caps.md": _DECLARING.format(
                path="lib/caps.json")},
                files={"spa_core/lib/caps.json": '{"a": 1}',
                       "scripts/lib/caps.json": '{"a": 1}'})
            doc = _surfaces(root)
        row = _by_path(doc, "lib/caps.json")
        self.assertFalse(row["declared_by"][0]["resolved"])
        self.assertIn("неоднозначен", row["declared_by"][0]["resolution"])

    def test_a_declared_path_absent_from_the_tree_is_named_not_dropped(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"caps.md": _DECLARING.format(
                path="spa_core/nowhere.json")})
            doc = _surfaces(root)
        row = _by_path(doc, "spa_core/nowhere.json")
        self.assertEqual(row["kind"], rsc.SURFACE_ABSENT)
        self.assertIn("нет", row["reason"])

    def test_without_any_rule_text_the_population_is_unmeasured(self):
        """Третий исход целиком: «правил не прочитано» ≠ «поверхностей нет»."""
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp))
            doc = _surfaces(root)
        self.assertEqual(doc["verdict"], rsc.SURFACES_UNMEASURED)
        self.assertEqual(doc["candidates"], 0)
        self.assertNotIn("surfaces_with_numbers", doc)

    def test_claude_md_is_a_declaring_text_too(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          claude=_DECLARING.format(path="spa_core/caps.json"),
                          files={"spa_core/caps.json": '{"cap_pct": 7.5}'})
            doc = _surfaces(root)
        self.assertEqual(_by_path(doc, "spa_core/caps.json")["declared_by"][0]
                         ["text"], rsc.RULE_TEXT)


class TheKindOfACandidateIsMeasured(unittest.TestCase):
    """Род объявленного файла — замер, а не расширение."""

    def test_a_document_with_a_freshness_stamp_is_a_measurement(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="spa_core/snap.json")},
                files={"spa_core/snap.json": json.dumps(
                    {"generated_at": "2026-01-01", "rate_pct": 5.3})})
            doc = _surfaces(root)
        row = _by_path(doc, "spa_core/snap.json")
        self.assertEqual(row["kind"], rsc.SURFACE_MEASUREMENT)
        self.assertIn("generated_at", row["reason"])
        self.assertNotIn("numbers", row)

    def test_a_guard_file_is_not_an_authority(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="spa_core/tests/test_caps.py")},
                files={"spa_core/tests/test_caps.py": "CAP = 7.5\n"})
            doc = _surfaces(root)
        row = _by_path(doc, "spa_core/tests/test_caps.py")
        self.assertEqual(row["kind"], rsc.SURFACE_GUARD)

    def test_a_broken_document_is_unreadable_not_empty(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="spa_core/caps.json")},
                files={"spa_core/caps.json": "{ не json"})
            doc = _surfaces(root)
        row = _by_path(doc, "spa_core/caps.json")
        self.assertEqual(row["kind"], rsc.SURFACE_UNREADABLE)
        self.assertIn("Error", row["reason"])

    def test_a_python_module_is_read_by_its_top_level_numbers(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="scripts/caps.py")},
                files={"scripts/caps.py":
                       "CAP_PCT = 7.5\n_PRIVATE = 9.9\nFLAG = True\n"})
            doc = _surfaces(root)
        row = _by_path(doc, "scripts/caps.py")
        self.assertEqual(row["kind"], rsc.SURFACE_SHELF)
        self.assertEqual(row["numbers"], 1)

    def test_a_flag_is_not_a_number_in_a_shelf(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="spa_core/caps.json")},
                files={"spa_core/caps.json": json.dumps({"enabled": True})})
            doc = _surfaces(root)
        self.assertEqual(_by_path(doc, "spa_core/caps.json")["numbers"], 0)


class TheShiftOfEachSurfaceIsMeasured(unittest.TestCase):
    """Сколько пар сменили бы форму починки у КАЖДОЙ поверхности."""

    #: Пара «сторож × исполнитель» с величиной, которую объявит сцена.
    _GUARD = "CAP = 7.5\n\n\ndef test_it():\n    assert CAP == 7.5\n"
    _EXEC = "CAP = 7.5\n"

    def _pair_scene(self, tmp: str, *, declared: str, shelf: str | None =
                    '{"tvl_floor_usd": 1234567.0}') -> dict:
        root = _scene(Path(tmp), shelf=shelf,
                      rules={"s.md": _DECLARING.format(path="scripts/caps.py")},
                      files={"spa_core/tests/test_cap.py": self._GUARD,
                             "spa_core/cap.py": self._EXEC,
                             "scripts/caps.py": declared})
        return _surfaces(root)

    def test_an_unasked_surface_that_names_a_free_pair_is_a_shift(self):
        with TemporaryDirectory() as tmp:
            doc = self._pair_scene(tmp, declared="CAP_PCT = 7.5\n")
        self.assertEqual(doc["verdict"], rsc.SURFACES_SHIFT)
        row = _by_path(doc, "scripts/caps.py")
        self.assertFalse(row["asked_today"])
        self.assertEqual(row["would_move"], 1)
        self.assertEqual(row["would_move_names"], ["CAP = 7.5"])
        self.assertEqual(doc["would_move_total"], 1)

    def test_a_surface_naming_a_pair_that_is_already_the_owners_does_not_move_it(self):
        """Обратная сторона: пара уже у владельца ⇒ двигать нечего, но мера кусается."""
        with TemporaryDirectory() as tmp:
            doc = self._pair_scene(tmp, declared="CAP_PCT = 7.5\n",
                                   shelf='{"cap_pct": 7.5}')
        row = _by_path(doc, "scripts/caps.py")
        self.assertEqual(row["matches"], 1)
        self.assertEqual(row["would_move"], 0)
        self.assertEqual(doc["verdict"], rsc.SURFACES_NO_SHIFT)
        self.assertIn("кусается", doc["reason"])

    def test_a_surface_naming_nothing_moves_nothing(self):
        with TemporaryDirectory() as tmp:
            doc = self._pair_scene(tmp, declared="OTHER = 999.25\n")
        row = _by_path(doc, "scripts/caps.py")
        self.assertEqual(row["matches"], 0)
        self.assertEqual(row["would_move"], 0)
        self.assertEqual(doc["verdict"], rsc.SURFACES_NO_SHIFT)

    def test_without_a_single_numeric_finding_the_answer_is_not_no_shift(self):
        """«Сравнивать было нечего» — свой исход, а не «сдвига нет»."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          rules={"s.md": _DECLARING.format(path="scripts/caps.py")},
                          files={"scripts/caps.py": "CAP_PCT = 7.5\n"})
            doc = _surfaces(root)
        self.assertEqual(doc["numeric_rows"], 0)
        self.assertEqual(doc["verdict"], rsc.SURFACES_NOTHING_COMPARABLE)

    def test_the_population_of_the_shift_is_all_three_axes(self):
        """Пара оси ИСПОЛНИТЕЛЕЙ считается так же, как пара первой оси."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp),
                          rules={"s.md": _DECLARING.format(path="scripts/caps.py")},
                          files={"spa_core/left.py": "PEER_CAP = 3.25\n",
                                 "spa_core/right.py": "PEER_CAP = 3.25\n",
                                 "scripts/caps.py": "CAP_PCT = 3.25\n"})
            doc = _surfaces(root)
        row = _by_path(doc, "scripts/caps.py")
        self.assertEqual(row["would_move_names"], ["PEER_CAP = 3.25"])


class TheAskedSurfacesAreCheckedForBeingDeclared(unittest.TestCase):
    """Спрашиваемая поверхность обязана быть объявлена — или это находка."""

    def test_a_declared_asked_surface_carries_its_evidence(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path=rsc.CONSTITUTION_FILE)})
            doc = _surfaces(root)
        asked = {r["path"]: r for r in doc["asked"]}
        self.assertTrue(asked[rsc.CONSTITUTION_FILE]["declared_by_rules"])
        self.assertEqual(
            asked[rsc.CONSTITUTION_FILE]["evidence"][0]["text"],
            ".claude/rules/s.md")

    def test_an_asked_surface_named_nowhere_is_named_as_such(self):
        """Сегодняшний замер живого дерева: `spa_core/risk/policy.py`."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path=rsc.CONSTITUTION_FILE)})
            doc = _surfaces(root)
        asked = {r["path"]: r for r in doc["asked"]}
        self.assertFalse(asked[rsc.RISK_POLICY_MODULE]["declared_by_rules"])
        self.assertEqual(asked[rsc.RISK_POLICY_MODULE]["mentions_in_rules"], 0)

    def test_named_without_authority_is_not_the_same_as_never_named(self):
        """Два разных ответа, и слить их значило бы потерять сильный."""
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _MENTION_ONLY.format(
                path=rsc.RISK_POLICY_MODULE)})
            doc = _surfaces(root)
        asked = {r["path"]: r for r in doc["asked"]}
        self.assertFalse(asked[rsc.RISK_POLICY_MODULE]["declared_by_rules"])
        self.assertEqual(asked[rsc.RISK_POLICY_MODULE]["mentions_in_rules"], 1)


class TheAdrChannelIsRejectedByMeasurement(unittest.TestCase):
    """Канал ADR отвергнут числом, а не вкусом."""

    def test_the_narrative_of_an_adr_is_counted_and_not_declared(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp))
            adr = root / "docs" / "decisions"
            adr.mkdir(parents=True)
            (adr / "ADR-001-x.md").write_text(
                "Файл `data/track.json` не менять без владельца.\n",
                encoding="utf-8")
            (adr / "INDEX.md").write_text("| ADR-001 | " + "y" * 500 + " |\n",
                                          encoding="utf-8")
            doc = _surfaces(root)
        channel = doc["adr_channel"]
        self.assertEqual(channel["files"], 1)
        self.assertEqual(channel["named_paths"], 1)
        self.assertEqual(channel["artifact_paths"], 1)
        self.assertEqual(channel["registry_long_lines"], 1)
        self.assertEqual([r["path"] for r in doc["surfaces"]], [])

    def test_a_missing_registry_is_a_reason_not_a_zero(self):
        with TemporaryDirectory() as tmp:
            doc = _surfaces(_scene(Path(tmp)))
        channel = doc["adr_channel"]
        self.assertIsNone(channel["registry_long_lines"])
        self.assertIsNotNone(channel["registry_unreadable"])


class TheReportSaysAllOfIt(unittest.TestCase):
    """Число, не напечатанное шагом 0-офис, читателя не имеет."""

    def _lines(self, doc: dict) -> list:
        return rsc.report(doc)

    def test_the_verdict_and_the_population_are_printed(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="scripts/caps.py")},
                files={"scripts/caps.py": "CAP_PCT = 7.5\n"})
            doc = rsc.measure(root, now=_NOW)
        lines = self._lines(doc)
        self.assertTrue(any("[ПОВЕРХНОСТИ РЕШЕНИЯ]" in l for l in lines))
        self.assertTrue(any("scripts/caps.py" in l and "[ШКАФ]" in l
                            for l in lines))

    def test_an_asked_but_undeclared_surface_gets_its_own_line(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path=rsc.CONSTITUTION_FILE)})
            doc = rsc.measure(root, now=_NOW)
        lines = self._lines(doc)
        self.assertTrue(any("[СПРАШИВАЕТСЯ, НО НЕ ОБЪЯВЛЕН]" in l
                            and rsc.RISK_POLICY_MODULE in l for l in lines))

    def test_a_document_without_the_coordinate_says_not_measured(self):
        """Инв. #17 внутри отчёта: отсутствие координаты ≠ «поверхностей нет»."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_scene(Path(tmp)), now=_NOW)
        doc.pop("decision_surfaces")
        lines = self._lines(doc)
        self.assertTrue(any("[ПОВЕРХНОСТИ РЕШЕНИЯ] НЕ ИЗМЕРЕНЫ" in l
                            for l in lines))

    def test_the_blindness_is_printed_too(self):
        with TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), rules={"s.md": _DECLARING.format(
                path="scripts/caps.py")},
                files={"scripts/caps.py": "CAP_PCT = 7.5\n"})
            doc = rsc.measure(root, now=_NOW)
        self.assertTrue(any("[СЛЕПОТА]" in l for l in self._lines(doc)))


class LiveControlOnTheRealTree(unittest.TestCase):
    """Замер этого репозитория — и он обязан быть непустым и укусчивым."""

    @classmethod
    def setUpClass(cls):
        cls.doc = rsc.measure(Path(rsc._ROOT), now=_NOW)["decision_surfaces"]

    def test_the_population_is_declared_and_non_empty(self):
        self.assertNotEqual(self.doc["verdict"], rsc.SURFACES_UNMEASURED)
        self.assertGreater(self.doc["candidates"], 0)
        for row in self.doc["surfaces"]:
            self.assertIn(row["kind"], rsc._SURFACE_KINDS)
            self.assertTrue(row["declared_by"])

    def test_the_measure_bites_here(self):
        """Ноль сдвига обязан стоять рядом с доказательством укуса."""
        shelves = [r for r in self.doc["surfaces"]
                   if r["kind"] == rsc.SURFACE_SHELF]
        self.assertTrue(shelves)
        self.assertGreater(sum(r["matches"] for r in shelves), 0)

    def test_the_senior_surface_is_asked_but_not_declared(self):
        """Сегодняшняя находка: старшая поверхность живёт в константе прибора.

        Тест пинит не «ноль», а ОТВЕТ: правила не называют
        `spa_core/risk/policy.py` ни разу. Появится строка в правиле —
        тест покраснеет, и это верно: находка закроется, а замер обязан
        перестать утверждать закрытое.
        """
        asked = {r["path"]: r for r in self.doc["asked"]}
        self.assertFalse(asked[rsc.RISK_POLICY_MODULE]["declared_by_rules"])
        self.assertEqual(asked[rsc.RISK_POLICY_MODULE]["mentions_in_rules"], 0)
        self.assertTrue(asked[rsc.CONSTITUTION_FILE]["declared_by_rules"])


if __name__ == "__main__":
    unittest.main()
