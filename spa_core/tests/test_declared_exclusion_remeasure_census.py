"""Сторож переписи «исключение объявлено СЛОВОМ, а не замером» (ADR-1120, G1092 п. 5).

Приёмка устроена так, чтобы каждая мера прибора имела контроль В ОБЕ СТОРОНЫ:
на целом контуре зелено, на КАЖДОМ порванном звене — красно, и звено НАЗВАНО
(`.claude/rules/acceptance.md` п. 3). Сцены одноразовые: живое дерево не трогается.

Несущее здесь — не число, а ТРАЕКТОРИЯ формы **22 → 1 → 0**, и каждое сужение
закреплено сценой на ИЗВЕСТНОМ члене:

* первая редакция спрашивала СВОЙ ЖЕ пустой перечень адресов мерки ⇒ предмет 22
  (тавтология: «записал ли я это у себя» вместо «есть ли мерка в дереве»);
* вторая спрашивала дерево, но только `test_*.py` ⇒ предмет 1, и тот ЛОЖНЫЙ —
  база инв. #17 читается ЧЕРЕЗ ПОМОЩНИКА;
* третья берёт помощников в охват ⇒ предмет 0 при вилке 0…9;
* четвёртая (ось C, ADR-1121) спросила ДОРОГУ ЗНАЧЕНИЯ ⇒ предмет **1**, и тот
  снова ЛОЖНЫЙ: дорога шла через ВОЗВРАТ функции ТОГО ЖЕ файла, а мера видела
  только присваивания (поправка #1267, дверь 4) ⇒ предмет **0** при вилке 0…7.

Урок один и тот же пятый раз: **дефект меры идёт в сторону НАХОДКИ**, и каждый
раз его опровергал ИЗВЕСТНЫЙ ЧЛЕН, а не вычитка.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "scripts" / "declared_exclusion_remeasure_census.py"


def _load():
    """Ввезти прибор как модуль. Нет файла ⇒ НЕ ИЗМЕРЕНО, а не зелёный скип."""
    if not TOOL.exists():
        raise AssertionError(f"НЕ ИЗМЕРЕНО: прибора нет по адресу {TOOL}")
    spec = importlib.util.spec_from_file_location("declared_exclusion_census", TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["declared_exclusion_census"] = mod
    spec.loader.exec_module(mod)
    return mod


CENSUS = _load()


def _write(root: pathlib.Path, rel: str, payload) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class ReasonAxisTests(unittest.TestCase):
    """Ось A: несёт ли СТРОКА причину — и ключ НАБОРА причиной не является."""

    def test_bare_string_rows_carry_no_reason(self):
        axis, rows, _ = CENSUS.reason_axis({"files": ["a.py", "b.py"]})
        self.assertEqual(axis, "reason_absent")
        self.assertEqual(rows, 2)

    def test_object_rows_carry_a_reason(self):
        axis, rows, _ = CENSUS.reason_axis({"members": [{"path": "a.py", "why": "x"}]})
        self.assertEqual(axis, "reason_present")
        self.assertEqual(rows, 1)

    def test_a_mapping_of_objects_carries_a_reason(self):
        """Отображение `путь → {поля}` причину НЕСЁТ.

        Первая редакция принимала только СПИСОК и отправила ДЕСЯТЬ носителей в
        ведро «строк нет» — ошибка в сторону «чисто», то есть в опасную.
        """
        axis, rows, _ = CENSUS.reason_axis({"known": {"a.py": {"why": "x"}}})
        self.assertEqual(axis, "reason_present")
        self.assertEqual(rows, 1)

    def test_mixed_rows_are_named_mixed_not_collapsed(self):
        axis, _, _ = CENSUS.reason_axis(
            {"members": [{"why": "x"}], "files": ["a.py"]})
        self.assertEqual(axis, "mixed")

    def test_meta_keys_are_not_rows(self):
        """Служебный ключ строкой исключения не является."""
        axis, rows, _ = CENSUS.reason_axis(
            {"schema": "x/1", "measured_at": "2026-11-27", "_comment": "почему"})
        self.assertEqual(axis, "no_rows")
        self.assertEqual(rows, 0)

    def test_a_meta_key_holding_a_LIST_is_still_not_rows(self):
        """РАЗЛИЧАЮЩАЯ сцена: служебный ключ со СПИСКОМ внутри.

        Сцена выше мутацию «отсев служебных ключей снят» НЕ различает и дала ей
        выжить (M12 первого прогона): её служебные значения — СКАЛЯРЫ, а строками
        становится только непустой список или словарь, поэтому отсев там ничего
        не решает. Мутация без различающей сцены ВЫЖИВАЕТ, и выжившую записывают,
        а не замазывают.
        """
        axis, rows, _ = CENSUS.reason_axis(
            {"measured_on": ["2026-11-01", "2026-11-02"], "required_fields": ["a"]})
        self.assertEqual(axis, "reason_absent",
                         "неслужебный `required_fields` обязан остаться строками")
        self.assertEqual(rows, 1, "служебный `measured_on` зачлён за строки исключений")

    def test_a_meta_key_alone_with_a_list_yields_no_rows(self):
        """Обратная половина той же пары: кроме служебного ключа нет ничего."""
        axis, rows, _ = CENSUS.reason_axis({"measured_on": ["2026-11-01"]})
        self.assertEqual(axis, "no_rows")
        self.assertEqual(rows, 0)

    def test_the_set_key_is_not_a_reason_key(self):
        """`known` — то, ЧЕМ добираются до строк, а не то, ЧЕМ строка себя объясняет.

        Зачесть ключ набора значило бы принять «сторож открыл базу» за «сторож
        перемерил причину».
        """
        keys, nameless = CENSUS.reason_keys({"known": {"a.py": {"why": "x"}}})
        self.assertEqual(keys, {"why"})
        self.assertNotIn("known", keys)
        self.assertEqual(nameless, 0)

    def test_a_reason_that_is_a_bare_value_has_no_name_and_is_counted_apart(self):
        """Форма `{путь: "причина строкой"}`: имени у причины нет вовсе."""
        keys, nameless = CENSUS.reason_keys({"known": {"a.py": "потому что"}})
        self.assertEqual(keys, set())
        self.assertEqual(nameless, 1)


class RemeasureAxisTests(unittest.TestCase):
    """Ось B: спрашивается у ДЕРЕВА, а не у своего перечня."""

    def test_a_guard_naming_a_reason_key_counts_as_remeasuring(self):
        readers, reading = CENSUS.remeasure_axis(
            "spa_core/tests/x_baseline.json", {"why"},
            {"spa_core/tests/test_x.py": {"x_baseline.json", "why"}})
        self.assertEqual(len(readers), 1)
        self.assertEqual(reading, 1)

    def test_a_guard_that_opens_the_base_but_never_reads_a_reason_is_the_subject(self):
        """Открыл базу ≠ перемерил причину — именно это и есть «слово вместо замера»."""
        readers, reading = CENSUS.remeasure_axis(
            "spa_core/tests/x_baseline.json", {"why"},
            {"spa_core/tests/test_x.py": {"x_baseline.json"}})
        self.assertEqual(len(readers), 1)
        self.assertEqual(reading, 0)

    def test_a_base_nobody_opens_has_no_readers(self):
        readers, reading = CENSUS.remeasure_axis(
            "spa_core/tests/x_baseline.json", {"why"},
            {"spa_core/tests/test_other.py": {"other.json"}})
        self.assertEqual(readers, [])
        self.assertEqual(reading, 0)

    def test_the_helper_scope_is_what_keeps_the_known_member_out_of_the_subject(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ починки: база, читаемая ЧЕРЕЗ ПОМОЩНИКА.

        Воспроизводит ложную находку второй редакции: имени базы в самом
        `test_*.py` нет, оно стои́т в `_*.py`. Сузь охват до тестов — и член
        вернётся обвинённым.
        """
        self.assertIn("spa_core/tests/_*.py", CENSUS.GUARD_GLOBS,
                      "помощники выпали из охвата — известный читатель снова "
                      "станет ложной находкой")
        readers, reading = CENSUS.remeasure_axis(
            "spa_core/tests/x_baseline.json", {"places"},
            {"spa_core/tests/_helper.py": {"x_baseline.json", "places"},
             "spa_core/tests/test_x.py": set()})
        self.assertEqual(reading, 1, "читателя-помощника ось B не увидела")

    def test_a_docstring_mention_is_not_a_call(self):
        """Прибор берёт литералы РАЗБОРОМ, и подстрока по тексту мерой не является."""
        with _Scene() as root:
            _write(root, "spa_core/tests/test_x.py",
                   '"""Докстринг называет x_baseline.json и why, но ничего не зовёт."""\n')
            lits = CENSUS.string_literals(root / "spa_core/tests/test_x.py")
            self.assertIsNotNone(lits)
            # Докстринг ЕСТЬ строковый литерал — поэтому мера обязана требовать
            # ИМЕНИ ключа отдельным литералом, а не вхождения в один абзац.
            self.assertNotIn("why", lits,
                             "упоминание внутри докстринга зачлось за имя ключа")

    def test_an_empty_guard_scope_refuses_instead_of_accusing_everyone(self):
        """Охват пуст ⇒ НЕ ИЗМЕРЕНО, а не «предмет — все».

        Без этой сцены мутация «пустой охват не останавливает замер» ВЫЖИВАЕТ
        (M17 первого прогона): ось B молча отвечает «читателя нет ни у кого» и
        обвиняет КАЖДЫЙ носитель с причиной — fail-OPEN наизнанку, фальшивое
        усиление. Спросить ось B там, где спрашивать нечем, нельзя.
        """
        with _Scene() as root:
            _write(root, "spa_core/tests/x_baseline.json",
                   {"members": [{"path": "a.py", "why": "потому"}]})
            verdicts, unmeasured, _roads = CENSUS.census(root)
            self.assertEqual(
                [v for v in verdicts if v.bucket == "subject"], [],
                "при пустом охвате прибор обвинил носитель, ничего не измерив")
            self.assertTrue(any("охват сторожей ПУСТ" in u for u in unmeasured),
                            f"пустой охват не назван причиной: {unmeasured}")

    def test_an_unparsable_guard_becomes_a_named_third_outcome(self):
        with _Scene() as root:
            _write(root, "spa_core/tests/test_broken.py", "def (((\n")
            table, unparsed = CENSUS.guard_literals(root)
            self.assertEqual(unparsed, ["spa_core/tests/test_broken.py"])
            self.assertNotIn("spa_core/tests/test_broken.py", table)


class _Scene:
    """Одноразовое дерево: живое дерево прибор не трогает."""

    def __enter__(self) -> pathlib.Path:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix="declexcl_")
        return pathlib.Path(self._tmp.name)

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()


class KnownMemberControlTests(unittest.TestCase):
    """Контроль ДО чисел: форма, потерявшая известного члена, ПОДМЕНЯЕТ класс."""

    def test_the_control_names_members_in_both_directions(self):
        buckets = set(CENSUS.KNOWN_MEMBERS.values())
        self.assertIn("remeasured", buckets)
        self.assertIn("reason_absent", buckets)
        self.assertGreaterEqual(
            len(CENSUS.KNOWN_MEMBERS), 4,
            "контроль в одну сторону контролем не является")

    def test_a_lost_known_member_refuses_with_code_2_and_no_numbers(self):
        """Потерян член ⇒ код 2 И НИ ОДНОГО ЧИСЛА о классе."""
        broken = CENSUS.check_known_members([])
        self.assertEqual(len(broken), len(CENSUS.KNOWN_MEMBERS))
        self.assertTrue(all("ПОТЕРЯН" in row for row in broken))

    def test_a_member_in_the_wrong_bucket_is_refused_too(self):
        key = next(iter(CENSUS.KNOWN_MEMBERS))
        wrong = CENSUS.Verdict(key, "json", "no_rows", 0, "—")
        broken = CENSUS.check_known_members([wrong])
        self.assertTrue(any(key in row and "ведро" in row for row in broken))

    def test_both_known_carriers_are_declared(self):
        """Носителей ДВА: форма, видящая только JSON, теряет член ADR-1117."""
        carriers = {("python" if "::" in k else "json")
                    for k in CENSUS.KNOWN_MEMBERS}
        self.assertEqual(carriers, {"json", "python"})


class LiveTreeTests(unittest.TestCase):
    """Замер на ЖИВОМ дереве: контроль сходится и вилка называется."""

    def test_the_control_holds_on_the_live_tree(self):
        verdicts, _unmeasured, roads = CENSUS.census(ROOT)
        broken = CENSUS.check_known_members(verdicts, roads)
        self.assertEqual(broken, [],
                         f"контроль известных членов не сошёлся: {broken}")

    def test_unmeasured_is_reported_apart_and_never_as_zero(self):
        _verdicts, unmeasured, _roads = CENSUS.census(ROOT)
        text, code = CENSUS.render(ROOT)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("ВИЛКА населения предмета", text)
        if unmeasured:
            self.assertEqual(code, 1,
                             "неразобранное обязано давать находку, а не ноль")

    def test_the_named_debt_of_the_python_carrier_is_printed(self):
        text, _ = CENSUS.render(ROOT)
        self.assertIn("полнота перечня Python-носителей НЕ ИЗМЕРЕНА", text)

    def test_the_prober_only_reads(self):
        text, _ = CENSUS.render(ROOT)
        self.assertIn("Прибор только ЧИТАЕТ", text)

    def test_an_unreadable_named_tree_is_code_2(self):
        rc = CENSUS.main(["--repo-root", "/nonexistent/declexcl/tree"])
        self.assertEqual(rc, 2, "нечитаемое НАЗВАННОЕ дерево обязано давать код 2")

    def test_the_exclusion_from_the_surface_is_measured_not_asserted(self):
        """«Не база исключений» объявляется с замером, а не словом «не нужно»."""
        for rel in CENSUS.NOT_AN_EXCLUSION_BASE:
            ok, detail = CENSUS._carrier_is_not_an_exclusion_base(ROOT, rel)
            self.assertTrue(ok, f"{rel}: объявлено «не база», а замер спорит — {detail}")

    def test_a_carrier_WITH_a_guard_reader_is_refused_as_not_an_exclusion_base(self):
        """ОБРАТНАЯ половина пары выше, и без неё замер снимается молча.

        Сцена выше проверяет только сторону «да, не база», поэтому мутация
        «возвращать True всегда» её НЕ различает и ВЫЖИЛА (M14 первого прогона).
        Здесь носитель ЧИТАЕТСЯ сторожем — и ответ обязан быть ОТРИЦАТЕЛЬНЫМ.
        """
        with _Scene() as root:
            _write(root, "spa_core/tests/some_baseline.json", {"files": ["a.py"]})
            _write(root, "spa_core/tests/test_reads_it.py",
                   'BASE = "some_baseline.json"\n')
            ok, detail = CENSUS._carrier_is_not_an_exclusion_base(
                root, "spa_core/tests/some_baseline.json")
            self.assertFalse(
                ok, "носитель, который ЧИТАЕТ сторож, объявлен «не базой» — "
                    "замер исключения снят молча")
            self.assertIn("читателей-сторожей", detail)


# ═══════════════════ ось C: дорога ЗНАЧЕНИЯ (ADR-1121) ════════════════════════


class NamelessSetKindTests(unittest.TestCase):
    """Род БЕЗЫМЯННОГО значения решается ТИПОМ, а не словом о наборе."""

    def test_string_values_are_a_reason(self):
        got = CENSUS.nameless_sets({"known": {"a.py::x": "потому что"}})
        self.assertEqual(got, {"known": "reason_string"})

    def test_number_values_are_a_tally_not_a_reason(self):
        """Счётчик причиной не является — обвинить его значило бы ошибиться
        в сторону НАХОДКИ. Замер #1266: таких носителей среди девяти «не
        измеренных» было ШЕСТЬ."""
        got = CENSUS.nameless_sets({"operand": {"carries": 3, "missing": 9}})
        self.assertEqual(got, {"operand": "tally"})

    def test_list_values_are_content_not_a_reason(self):
        got = CENSUS.nameless_sets({"undeclared_top": {"a.json": ["x", "y"]}})
        self.assertEqual(got, {"undeclared_top": "listing"})

    def test_mixed_values_NAME_their_composition(self):
        """`mixed` обязан назвать состав: по нему решается, несёт ли набор причину."""
        got = CENSUS.nameless_sets({"axis": {"n": 1, "why": "строкой"}})
        self.assertEqual(got, {"axis": "mixed:reason_string+tally"})
        self.assertIn("reason_string", got["axis"])

    def test_a_set_of_OBJECTS_is_not_nameless(self):
        """Причина ИМЕНОВАНА ⇒ это ось B, и ось C её не судит."""
        self.assertEqual(CENSUS.nameless_sets({"known": {"a.py": {"why": "x"}}}), {})

    def test_meta_keys_are_not_nameless_sets(self):
        self.assertEqual(CENSUS.nameless_sets({"notes": {"a": "b"}, "_x": {"c": "d"}}),
                         {})


class CarrierAnchorTests(unittest.TestCase):
    """Опознавательные знаки носителя: имя файла И объявленная схема."""

    def test_the_schema_is_an_anchor_too(self):
        """Без схемы известный член выпал бы из читателей ВОВСЕ.

        `scripts/python_git_ref_provenance.py` имени файла не называет: путь
        приходит в `--baseline`, а документ опознаётся литералом схемы.
        """
        got = CENSUS.carrier_anchors("scripts/x_baseline.json",
                                     {"schema": "x-baseline/2"})
        self.assertEqual(got, {"x_baseline.json", "x-baseline/2"})

    def test_a_carrier_without_a_schema_has_one_anchor(self):
        self.assertEqual(CENSUS.carrier_anchors("a/b_baseline.json", {"rows": []}),
                         {"b_baseline.json"})

    def test_an_empty_schema_is_not_an_anchor(self):
        """Пустая схема опознавательным знаком не является: иначе читателем
        стал бы любой файл со строкой `""`."""
        self.assertEqual(CENSUS.carrier_anchors("a/b_baseline.json",
                                                {"schema": "   "}),
                         {"b_baseline.json"})


class ProseIsNotAReaderTests(unittest.TestCase):
    """Упоминание в ПРОЗЕ читателем не делает (дословный урок ADR-1116)."""

    def test_a_docstring_mention_is_not_naming_the_carrier(self):
        tree = ast.parse('"""см. scripts/x_baseline.json"""\nY = 1\n')
        self.assertFalse(CENSUS.names_the_carrier(tree, {"x_baseline.json"}))

    def test_a_literal_in_code_IS_naming_the_carrier(self):
        """Обратная половина пары: без неё отсев прозы снимал бы ось целиком."""
        tree = ast.parse('P = "scripts/x_baseline.json"\n')
        self.assertTrue(CENSUS.names_the_carrier(tree, {"x_baseline.json"}))

    def test_a_bare_string_statement_is_prose_too(self):
        tree = ast.parse('Y = 1\n"scripts/x_baseline.json"\n')
        self.assertFalse(CENSUS.names_the_carrier(tree, {"x_baseline.json"}))


class ComputedKeyTests(unittest.TestCase):
    """Вычисленный ключ: раскрыт по литеральному перечню либо НЕ ИЗМЕРЕН."""

    def test_a_loop_over_a_literal_tuple_is_expanded(self):
        tree = ast.parse('for s in ("a", "b"):\n    pass\n')
        self.assertEqual(CENSUS.loop_literal_vars(tree), {"s": {"a", "b"}})

    def test_a_passthrough_wrapper_does_not_hide_the_literals(self):
        tree = ast.parse('for s in sorted(("a", "b")):\n    pass\n')
        self.assertEqual(CENSUS.loop_literal_vars(tree), {"s": {"a", "b"}})

    def test_a_loop_over_a_computed_iterable_yields_nothing(self):
        """Третий исход, а не догадка: перечня нет ⇒ ключ не раскрыт."""
        tree = ast.parse('for s in sections():\n    pass\n')
        self.assertEqual(CENSUS.loop_literal_vars(tree), {})


class _Road:
    """Одноразовая сцена оси C: носитель + читатели, живое дерево не трогается."""

    REL = "scripts/scene_baseline.json"

    def __init__(self, doc, readers):
        self.doc = doc
        self.readers = readers

    def __enter__(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix="declexcl_road_")
        self.root = pathlib.Path(self._tmp.name)
        _write(self.root, self.REL, self.doc)
        for rel, text in self.readers.items():
            _write(self.root, rel, text)
        CENSUS._TREE_CACHE.clear()
        CENSUS._READER_FACTS.clear()
        return self

    def __exit__(self, *exc):
        CENSUS._TREE_CACHE.clear()
        CENSUS._READER_FACTS.clear()
        self._tmp.cleanup()

    def ask(self):
        sets = CENSUS.nameless_sets(self.doc)
        anchors = CENSUS.carrier_anchors(self.REL, self.doc)
        index, _unreadable = CENSUS.anchor_index(self.root, anchors)
        road, proofs, bad, _keys = CENSUS.value_road(
            self.root, self.REL, self.doc, sets, index)
        return road, proofs, bad


_DOC = {"known": {"a.py::x": "длинная причина"}}


class ValueRoadTests(unittest.TestCase):
    """Ось C на целом контуре зелена, на КАЖДОМ порванном звене — красна."""

    def test_items_with_the_value_USED_is_a_value_road(self):
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    for name, why in sorted(d["known"].items()):\n'
            '        assert why.strip(), name\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(proofs)
        self.assertEqual([], bad)

    def test_membership_on_KEYS_only_is_NOT_a_value_road(self):
        """Порванное звено: `f in base` читает КЛЮЧИ. Это и есть предмет —
        дословная форма `lint_forbidden_imports.py` (известный член)."""
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check(f):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    base = d.get("known", {})\n'
            '    return f in base\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_KEYS, road)
        self.assertEqual([], bad)

    def test_a_carrier_nobody_names_in_code_is_a_separate_outcome(self):
        """«Сироту» нельзя звать предметом: это ДРУГОЙ класс."""
        with _Road(_DOC, {"spa_core/tests/test_scene.py": "X = 1\n"}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_NONE, road)
        self.assertEqual([], bad)

    def test_a_computed_key_that_cannot_be_opened_is_UNMEASURED(self):
        """Третий исход (инв. #17): ни «читает», ни «не читает»."""
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check(section):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    return list(d.get(section).items())\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_UNMEASURED, road)
        self.assertTrue(any("НЕ РАСКРЫТ" in row for row in bad))

    def test_a_computed_key_FROM_A_LITERAL_TUPLE_is_a_value_road(self):
        """Обратная половина пары выше — и ровно форма известного члена
        (`for _sect in ("admitted_after_migration", "unresolved")`)."""
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    for sect in ("known", "other"):\n'
            '        for name, why in (d.get(sect) or {}).items():\n'
            '            assert isinstance(why, str), name\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("known" in p for p in proofs))

    def test_items_whose_VALUE_is_discarded_is_not_a_value_road(self):
        """`.items()` есть, а значение нигде не читается — присутствие зова
        дорогой значения не является."""
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    for name, unused in d["known"].items():\n'
            '        assert name\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertNotEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("нигде не читается" in row for row in bad))

    def test_reaching_INTO_a_row_by_subscript_is_a_value_road(self):
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check(name):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    return d["known"]["a.py::x"]\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("чтение ИЗ строки" in p for p in proofs))

    def test_the_SCHEMA_door_finds_a_reader_that_never_names_the_file(self):
        """Вторая дверь опознания. Сузь её — и известный член (прибор
        провенанса) выпадет из читателей ВОВСЕ, то есть класс ПОДМЕНИТСЯ."""
        doc = dict(_DOC, schema="scene-baseline/1")
        reader = (
            'import json, pathlib\n'
            'SCHEMA = "scene-baseline/1"\n'
            'def check(argv_path):\n'
            '    b = json.loads(pathlib.Path(argv_path).read_text("utf-8"))\n'
            '    if b.get("schema") != SCHEMA:\n'
            '        return 2\n'
            '    for name, why in b.get("known", {}).items():\n'
            '        assert why.strip(), name\n'
            '    return 0\n')
        with _Road(doc, {"scripts/instrument.py": reader}) as scene:
            scene.REL = _Road.REL
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("instrument.py" in p for p in proofs))

    def test_a_reader_that_only_MENTIONS_the_carrier_in_prose_is_not_a_reader(self):
        reader = ('"""Читает scripts/scene_baseline.json — но не читает."""\n'
                  'X = 1\n')
        with _Road(_DOC, {"scripts/prose.py": reader}) as scene:
            road, _proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_NONE, road)

    def test_an_unparsable_reader_is_a_named_third_outcome(self):
        with _Road(_DOC, {"scripts/broken.py":
                          'P = "scripts/scene_baseline.json"\ndef (\n'}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_UNMEASURED, road)
        self.assertTrue(any("не разобран" in row for row in bad))


class ValueRoadControlTests(unittest.TestCase):
    """Контроль САМОЙ оси C — ДО чисел и в ОБЕ стороны."""

    def test_the_table_holds_the_value_side_and_a_SCENE_holds_the_other(self):
        """Сторону `keys` в ДЕРЕВЕ сегодня не держит ни один носитель.

        После двери 4 (поправка #1267) предмет класса ПУСТ: единственный
        кандидат `scripts/forbidden_import_baseline.json` читает причину за
        возвратом функции. Вписать в таблицу носителя, которого мера в это
        ведро не кладёт, значило бы объявить контролем собственное ожидание —
        поэтому вторая сторона держится СЦЕНОЙ на настоящем приборе, и этот
        тест закрепляет, что сцена отвечает, а не что она написана.
        """
        values = set(CENSUS.KNOWN_VALUE_ROAD.values())
        self.assertIn(CENSUS.ROAD_VALUE, values)
        self.assertNotIn(CENSUS.ROAD_KEYS, values,
                         "появился настоящий предмет — его место в таблице, "
                         "а не только в сцене")
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check(f):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    return f in d.get("known", {})\n')
        with _Road(_DOC, {"spa_core/tests/test_scene.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_KEYS, road,
                         "сцена стороны `keys` не отвечает — контроля этой "
                         "стороны нет ни в таблице, ни в сцене")
        self.assertEqual([], bad)

    def test_the_door_4_member_is_pinned_in_BOTH_control_tables(self):
        """Поправка #1267 закреплена, а не оставлена на вычитку.

        Член прочитан В КОДЕ: `scripts/lint_forbidden_imports.py:269` печатает
        `baseline[f.key]`, то есть ЗНАЧЕНИЕ. Верни сюда `subject`/`keys` — и
        прибор снова объявит предметом файл, который причину читает.
        """
        self.assertEqual("value_read",
                         CENSUS.KNOWN_MEMBERS["scripts/forbidden_import_baseline.json"])
        self.assertEqual(CENSUS.ROAD_VALUE,
                         CENSUS.KNOWN_VALUE_ROAD["scripts/forbidden_import_baseline.json"])

    def test_a_missing_road_answer_refuses_with_no_numbers(self):
        """Ось C НЕ СПРОШЕНА — это отказ, а не молчаливое «сошлось»."""
        verdicts = [CENSUS.Verdict(k, "json", v, 0, "—")
                    for k, v in CENSUS.KNOWN_MEMBERS.items()]
        broken = CENSUS.check_known_members(verdicts, {})
        self.assertEqual(len(broken), len(CENSUS.KNOWN_VALUE_ROAD))
        self.assertTrue(all("НЕ СПРОШЕНА" in row for row in broken))

    def test_a_wrong_road_answer_is_refused(self):
        verdicts = [CENSUS.Verdict(k, "json", v, 0, "—")
                    for k, v in CENSUS.KNOWN_MEMBERS.items()]
        roads = {k: CENSUS.ROAD_NONE for k in CENSUS.KNOWN_VALUE_ROAD}
        broken = CENSUS.check_known_members(verdicts, roads)
        self.assertTrue(all("дорога значения" in row for row in broken))

    def test_the_bucket_control_still_holds_when_roads_are_right(self):
        """Оси контроля НЕЗАВИСИМЫ: сошлась одна — числа всё равно не выдаются."""
        roads = dict(CENSUS.KNOWN_VALUE_ROAD)
        broken = CENSUS.check_known_members([], roads)
        self.assertEqual(len(broken), len(CENSUS.KNOWN_MEMBERS))


class FieldDoorTests(unittest.TestCase):
    """Дверь 3: имя ПОЛЯ, объявленное литералом носителя в этом же файле."""

    READER = (
        'import json, pathlib\n'
        'class _Stub:\n'
        '    DECL = "scripts/scene_baseline.json"\n'
        'def check(mod):\n'
        '    d = json.loads((pathlib.Path("/t") / mod.DECL).read_text("utf-8"))\n'
        '    for name, why in d["known"].items():\n'
        '        assert why.strip(), name\n')

    def test_a_document_opened_through_ANOTHER_modules_field_is_found(self):
        """Без этой двери мера даёт ЛОЖНУЮ НАХОДКУ.

        Замер #1266: `test_unfinished_work_probe.py` объявляет путь полем
        заглушки, а открывает документ полем ЧУЖОГО модуля
        (`census.DECLARATION_REL`) — и первая редакция объявила носитель
        предметом при читаемых построчно `axis_one.rows`.
        """
        with _Road(_DOC, {"spa_core/tests/test_field.py": self.READER}) as scene:
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(proofs)

    def test_the_door_needs_the_literal_IN_THIS_FILE(self):
        """Обратная половина: поле с тем же именем, но литерала носителя в файле
        НЕТ ⇒ опознавать нечем, и дверь молчит (иначе она открывалась бы на
        любое поле с похожим именем)."""
        reader = self.READER.replace('"scripts/scene_baseline.json"',
                                     '"scripts/other_file.json"')
        with _Road(_DOC, {"spa_core/tests/test_field.py": reader}) as scene:
            road, _proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_NONE, road)

    def test_the_field_names_are_measured_from_assignments(self):
        tree = ast.parse('class A:\n    REL = "scripts/scene_baseline.json"\n')
        pairs = CENSUS._assign_pairs(tree)
        got = CENSUS.attr_anchors(pairs, {"scene_baseline.json"},
                                  CENSUS._prose_ids(tree))
        self.assertEqual(got, {"REL"})


class AnswerAboutAnotherSetTests(unittest.TestCase):
    """Дорога значения зачитывается ТОЛЬКО у набора, который причину НЕСЁТ."""

    def test_a_value_road_on_a_TALLY_set_is_not_an_answer_about_the_reason(self):
        """Класс ADR-1072 на новом месте: «ответ о ДРУГОМ наборе».

        Носитель несёт причину в `измерено_на`, а `.items()` читают у счётчика
        `файлы` — и первая редакция объявила это «значение читают», ни разу не
        спросив о причине.
        """
        doc = {"блок": {"коммит": "abc", "дата": "2026-11-27"},
               "файлы": {"a.py": 1, "b.py": 2}}
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    for name, count in d["файлы"].items():\n'
            '        assert count >= 0, name\n')
        with _Road(doc, {"scripts/w.py": reader}) as scene:
            sets = CENSUS.nameless_sets(doc)
            anchors = CENSUS.carrier_anchors(_Road.REL, doc)
            index, _u = CENSUS.anchor_index(scene.root, anchors)
            road, _proofs, _bad, keys = CENSUS.value_road(
                scene.root, _Road.REL, doc, sets, index)
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertEqual({"файлы"}, keys)
        bearing = {k for k, kind in sets.items() if "reason_string" in kind}
        self.assertEqual({"блок"}, bearing)
        self.assertEqual(set(), keys & bearing,
                         "дорога значения зачтена у набора, причину НЕ несущего")


class PositionCapTests(unittest.TestCase):
    """Предел различаемых положений: перебор ⇒ НЕ ИЗМЕРЕНО, а не усечение."""

    def test_an_exploding_position_set_is_a_named_third_outcome(self):
        """Усечение молча превратило бы «не досчитали» в «не читает».

        Замер #1266: без предела набор положений рос произведением ключей, и на
        `card_acceptance.py` прибор съел 7 ГиБ и не ответил ВОВСЕ.
        """
        keys = [f"k{i}" for i in range(CENSUS._POSITION_CAP + 8)]
        tuple_src = ", ".join(f'"{k}"' for k in keys)
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            f'    for a in ({tuple_src}):\n'
            '        for name, why in d[a].items():\n'
            '            assert why\n')
        with _Road(_DOC, {"scripts/big.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_UNMEASURED, road)
        self.assertTrue(bad)

    def test_the_cap_does_not_fire_on_an_ordinary_reader(self):
        """Обратная половина: обычный читатель предела не достигает."""
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def check():\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    for name, why in d["known"].items():\n'
            '        assert why\n')
        with _Road(_DOC, {"scripts/small.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertEqual([], bad)


if __name__ == "__main__":
    unittest.main()


class ReturnDoorTests(unittest.TestCase):
    """Дверь 4 (поправка #1267): ВОЗВРАТ функции того же файла.

    Замер, из-за которого дверь понадобилась: ось C объявила ПРЕДМЕТОМ
    `scripts/forbidden_import_baseline.json`, написав «значение не читает
    никто». Чтение там есть и стои́т в `main()` —
    `print(f"ИЗВЕСТНОЕ  {f} — {baseline[f.key]}")`, — а набор выбирается
    ВНУТРИ помощника `load_baseline` и уходит наружу `return`. Мера видела
    только присваивания, поэтому дорога рвалась на границе ФУНКЦИИ, и граница
    СВОЕЙ меры была выдана за находку о мире (урок ADR-1074/ADR-1116).

    Каждая сцена ниже — на НАСТОЯЩЕМ приборе, живое дерево не трогается.
    """

    #: Дословная форма известного члена: литерал → помощник → `return` → чтение.
    LINT_SHAPE = (
        'import json, os\n'
        'REL = "scripts/scene_baseline.json"\n'
        'def load_baseline(root):\n'
        '    path = os.path.join(root, REL)\n'
        '    with open(path, encoding="utf-8") as fh:\n'
        '        doc = json.load(fh)\n'
        '    return doc.get("known", {})\n'
        'def main(root, findings):\n'
        '    baseline = load_baseline(root)\n'
        '    for f in findings:\n'
        '        print(f"ИЗВЕСТНОЕ {f} — {baseline[f.key]}")\n'
    )

    def test_a_reason_read_BEHIND_a_function_return_is_a_value_road(self):
        with _Road(_DOC, {"scripts/scene_lint.py": self.LINT_SHAPE}) as scene:
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("known" in p for p in proofs), proofs)

    def test_the_SAME_shape_without_the_value_read_stays_KEYS(self):
        """Порванное звено: дверь 4 не выдаёт «значение» всем, кто зовёт помощника.

        Без этой сцены дверь могла бы зеленить любой файл с `return` — то есть
        стать тем самым молчаливым зачтением, против которого ось и написана.
        """
        reader = self.LINT_SHAPE.replace(
            '        print(f"ИЗВЕСТНОЕ {f} — {baseline[f.key]}")',
            '        print(f.key in baseline)')
        self.assertNotEqual(reader, self.LINT_SHAPE, "сцена не изменилась")
        with _Road(_DOC, {"scripts/scene_lint.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_KEYS, road)
        self.assertEqual([], bad)

    def test_a_NESTED_function_return_is_not_attributed_to_the_outer(self):
        """Вложенная функция возвращает СВОЁ.

        Приписать её возврат внешней значило бы расширить дорогу значения туда,
        где её нет: зов внешней функции отдаёт НЕ набор.
        """
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def outer():\n'
            '    def inner():\n'
            '        doc = json.loads(P.read_text(encoding="utf-8"))\n'
            '        return doc.get("known", {})\n'
            '    return 0\n'
            'def use(k):\n'
            '    return outer()[k]\n')
        with _Road(_DOC, {"scripts/scene_nested.py": reader}) as scene:
            road, proofs, _bad = scene.ask()
        # Сцена обязана РАЗЛИЧАТЬ: `doc` связан отдельным присваиванием, поэтому
        # у возврата ВЛОЖЕННОЙ функции положение набора РАЗРЕШИМО. Сними
        # отсечение вложенных — и `outer()[k]` станет дорогой ЗНАЧЕНИЯ. Первая
        # редакция сцены писала `return json.loads(...)["known"]` одним
        # выражением: обёртка `json.loads` рвала цепь положений, вердикт
        # мутанта выходил `unmeasured`, и МУТАЦИЯ ВЫЖИВАЛА при верном коде.
        self.assertEqual(CENSUS.ROAD_KEYS, road,
                         f"возврат ВЛОЖЕННОЙ функции приписан внешней: {proofs}")

    def test_a_computed_key_on_the_WHOLE_document_stays_UNMEASURED(self):
        """Третий исход остался третьим исходом.

        Шаг ВНУТРЬ разрешён только у УЖЕ опознанного набора. На положении всего
        документа вычисленный ключ по-прежнему значит «какой это набор — НЕ
        ИЗВЕСТНО»: смягчи и здесь — и ось начнёт отвечать «читает» про любой
        набор любого носителя.
        """
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def use(section, k):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    return d[section][k]\n')
        with _Road(_DOC, {"scripts/scene_doc.py": reader}) as scene:
            road, _proofs, bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_UNMEASURED, road)
        self.assertTrue(any("НЕ РАСКРЫТ" in row for row in bad), bad)

    def test_a_step_INSIDE_a_named_set_with_a_computed_key_IS_a_value_road(self):
        """Обратная половина той же пары: набор НАЗВАН, ключ вычислен.

        Какой бы ключ ни стоял, полученное есть ЗНАЧЕНИЕ строки ЭТОГО набора.
        """
        reader = (
            'import json, pathlib\n'
            'P = pathlib.Path("scripts/scene_baseline.json")\n'
            'def use(k):\n'
            '    d = json.loads(P.read_text(encoding="utf-8"))\n'
            '    return d["known"][k]\n')
        with _Road(_DOC, {"scripts/scene_inside.py": reader}) as scene:
            road, proofs, _bad = scene.ask()
        self.assertEqual(CENSUS.ROAD_VALUE, road)
        self.assertTrue(any("ключ вычислен" in p for p in proofs), proofs)

    def test_the_return_pairs_are_measured_not_asserted(self):
        """Перечень возвратов — РАЗБОР, а не перечисление имён в голове."""
        tree = ast.parse(self.LINT_SHAPE)
        pairs = dict(CENSUS._return_pairs(tree))
        self.assertIn(CENSUS._RET + "load_baseline", pairs)
        self.assertNotIn(CENSUS._RET + "main", pairs,
                         "у `main` возврата нет — его не должно быть и в паре")


class ControlLineTests(unittest.TestCase):
    """Строка о контроле — ЗАМЕР состава таблицы, а не слово «обе стороны»."""

    def test_a_missing_side_is_NAMED_not_implied(self):
        line = CENSUS.control_line({"a": "x"}, {"a": CENSUS.ROAD_VALUE})
        self.assertIn(CENSUS.ROAD_VALUE, line)
        self.assertIn("СЦЕНОЙ", line,
                      "сторона в таблице одна, а строка об этом молчит")

    def test_both_sides_present_say_so_without_the_caveat(self):
        line = CENSUS.control_line(
            {"a": "x", "b": "y"},
            {"a": CENSUS.ROAD_VALUE, "b": CENSUS.ROAD_KEYS})
        self.assertIn(CENSUS.ROAD_KEYS, line)
        self.assertNotIn("СЦЕНОЙ", line,
                         "обе стороны в таблице, а строка всё равно оправдывается")
