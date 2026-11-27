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
* третья берёт помощников в охват ⇒ предмет 0 при вилке 0…9.
"""

from __future__ import annotations

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
            verdicts, unmeasured = CENSUS.census(root)
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
        verdicts, _ = CENSUS.census(ROOT)
        broken = CENSUS.check_known_members(verdicts)
        self.assertEqual(broken, [],
                         f"контроль известных членов не сошёлся: {broken}")

    def test_unmeasured_is_reported_apart_and_never_as_zero(self):
        _, unmeasured = CENSUS.census(ROOT)
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


if __name__ == "__main__":
    unittest.main()
