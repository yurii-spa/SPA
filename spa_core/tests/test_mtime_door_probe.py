#!/usr/bin/env python3
"""Контроль пробы приёмки `mtime_half_injection_population_is_measured`.

`.claude/rules/acceptance.md` §3: новая проба регистрируется ТОЛЬКО с тестом, где она
зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с названным звеном, — и
где она НЕ проходит подстрокой (ADR-333).

Звенья контура, каждое со своим тестом ниже:

1. прибор называет ЧЛЕНОМ сцену в форме аварии 24.11 (ADR-1086);
2. прибор НЕ обвиняет лечение (сцену с закреплённой отметкой);
3. переход вердикта у члена — РОВНО `PASSED → FAILED`, а не любая смена;
4. известный член класса лежит ВНУТРИ измеренного предмета (урок ADR-1074);
5. ось одного хопа что-то ОТСЕКАЕТ (иначе она ничего не меряет);
6. неответ прибора и сломанная предпосылка ⇒ `unmeasured` с названной причиной.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.tests import _mtime_clock_door as door

PROBE_NAME = "mtime_half_injection_population_is_measured"
REPO = Path(__file__).resolve().parents[2]

#: Дверь снимается ДО любой подмены. Зови патченную — и помощник сцены уйдёт в
#: рекурсию через самого себя: замер #1233 дал ровно `maximum recursion depth
#: exceeded`, и прибор доложил его как «поверхность не разобрана», то есть
#: НЕ ИЗМЕРЕНО по ЧУЖОЙ причине. Это тот же класс, что дефект самого прибора
#: (ключ пути через подменённую дверь), только у сцены.
_REAL_MEASURE = door.measure_surface


def _run():
    return ca.PROBES[PROBE_NAME](None, repo_root=str(REPO))


class _Patched:
    """Порвать РОВНО одно звено прибора и вернуть всё на место."""

    def __init__(self, **kw):
        self.kw = kw
        self.old: dict = {}

    def __enter__(self):
        for name, value in self.kw.items():
            self.old[name] = getattr(door, name)
            setattr(door, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.old.items():
            setattr(door, name, value)
        return False


def _surface_rows():
    """Настоящая поверхность — считается ОДИН раз на класс тестов (она не дешёвая)."""
    if not hasattr(_surface_rows, "_cache"):
        _surface_rows._cache = _REAL_MEASURE(REPO)
    return list(_surface_rows._cache)


class TheProbeIsGreenOnTheWholeCircuit(unittest.TestCase):
    def test_the_whole_circuit_satisfies(self):
        status, reason = _run()
        self.assertEqual(status, ca.SATISFIED, reason)
        # вердикт берётся ЗНАЧЕНИЕМ, и причина НАЗЫВАЕТ числа, а не хвалит себя
        self.assertIn("член 1", reason)
        self.assertIn("предмет", reason)


class EachTornLinkIsRedWithItsName(unittest.TestCase):

    def test_a_prober_that_does_not_see_the_accident_is_not_satisfied(self):
        """Звено 1: прибор молчит о форме аварии ⇒ он украшение, а не сторож."""
        real = door.differential

        def blind(tree, files, **kw):
            doc = real(tree, files, **kw)
            doc["verdict"] = {}
            doc["candidates"] = {}
            return doc

        with _Patched(differential=blind):
            status, reason = _run()
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("НЕ названа членом", reason)

    def test_a_prober_that_accuses_the_cure_is_not_satisfied(self):
        """Звено 2: прибор обвиняет ПОЧИНЕННЫЙ код ⇒ учит снимать лечение."""
        real = door.differential

        def trigger_happy(tree, files, **kw):
            doc = real(tree, files, **kw)
            if not doc.get("candidates"):
                doc["candidates"] = {f"{files[0]}::test_archive_is_fresh":
                                     ["PASSED", "FAILED"]}
            return doc

        with _Patched(differential=trigger_happy):
            status, reason = _run()
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("ПОЧИНЕННЫЙ", reason)

    def test_a_change_other_than_passed_to_failed_is_not_satisfied(self):
        """Звено 3: «вердикт дрогнул» НЕ равно «сцена покраснела от календаря»."""
        real = door.differential

        def sideways(tree, files, **kw):
            doc = real(tree, files, **kw)
            for n in list(doc.get("candidates", {})):
                doc["candidates"][n] = ["PASSED", "SKIPPED"]
            return doc

        with _Patched(differential=sideways):
            status, reason = _run()
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("PASSED→FAILED", reason)

    def test_losing_the_known_member_is_not_satisfied(self):
        """Звено 4: форма, потерявшая известного члена, ПОДМЕНЯЕТ класс (ADR-1074)."""
        known = "spa_core/tests/test_mission_control_contract.py"

        def without_known(root, *a, **kw):
            rows = []
            for v in _surface_rows():
                if v.path == known:
                    v = door.FileVerdict(path=v.path, surface=door.NO_READER,
                                         write_lines=v.write_lines,
                                         pin_lines=v.pin_lines)
                rows.append(v)
            return rows

        with _Patched(measure_surface=without_known):
            status, reason = _run()
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("известный член класса", reason)

    def test_a_hop_axis_that_cuts_nothing_is_not_satisfied(self):
        """Звено 5: ось, не отсёкшая ни одного файла, ничего не меряет."""
        def everything_is_subject(root, *a, **kw):
            return [door.FileVerdict(path=v.path, surface=door.IN_SURFACE,
                                     write_lines=v.write_lines,
                                     pin_lines=v.pin_lines,
                                     reader_hits=("x",))
                    for v in _surface_rows()
                    if v.surface in {door.IN_SURFACE, door.NO_READER}]

        with _Patched(measure_surface=everything_is_subject):
            status, reason = _run()
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("ось одного хопа", reason)


class TheThirdOutcomeIsNeverSilent(unittest.TestCase):

    def test_a_prober_that_does_not_answer_is_unmeasured(self):
        def boom(*a, **kw):
            raise RuntimeError("прибор не ответил")

        with _Patched(differential=boom):
            status, reason = _run()
        self.assertEqual(status, ca.UNMEASURED, reason)
        self.assertIn("НЕ ИЗМЕРЕНО", reason)

    def test_a_broken_precondition_is_unmeasured_not_a_finding(self):
        """Канарейка / пустая поверхность ⇒ ответа о классе НЕТ (инв. #17)."""
        real = door.differential

        def canary_broken(tree, files, **kw):
            doc = real(tree, files, **kw)
            doc["unmeasured"] = [{"what": "канарейка прозрачности",
                                  "reason": "контроль: объявлена сломанной"}]
            return doc

        with _Patched(differential=canary_broken):
            status, reason = _run()
        self.assertEqual(status, ca.UNMEASURED, reason)
        self.assertIn("канарейка", reason)

    def test_an_unreadable_surface_is_unmeasured(self):
        def with_unmeasured(root, *a, **kw):
            rows = _surface_rows()
            return rows + [door.FileVerdict(path="spa_core/tests/test_x.py",
                                            surface=door.UNMEASURED,
                                            reason="контроль: не разобран")]

        with _Patched(measure_surface=with_unmeasured):
            status, reason = _run()
        self.assertEqual(status, ca.UNMEASURED, reason)
        self.assertIn("прочитана не целиком", reason)


class TheProbeDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: вердикт берётся ЗНАЧЕНИЕМ прибора, а не словом в прозе."""

    def test_prose_that_claims_success_does_not_satisfy(self):
        def liar(tree, files, **kw):
            return {"files": list(files), "stages": {}, "unmeasured": [],
                    "candidates": {},
                    "verdict": {"всё закрыто, класс измерен, members=1": "member"}}

        with _Patched(differential=liar):
            status, reason = _run()
        # Проба требует НАБЛЮДЕНИЕ, а не слово: у названного члена обязан быть
        # переход вердикта. Проза его не предъявляет — и краснеет РАНЬШЕ, чем
        # дойдёт до звена о лечении.
        self.assertEqual(status, ca.NOT_SATISFIED, reason)
        self.assertIn("не предъявив наблюдения", reason)


class TheProbeIsDeclaredInTheRegistry(unittest.TestCase):
    def test_the_name_is_in_PROBES(self):
        self.assertIn(PROBE_NAME, ca.PROBES)

    def test_the_probe_accepts_the_repo_root_input(self):
        """Дерево — ВХОД, а не умолчание: иначе проба отвечает о ЧУЖОМ дереве."""
        import inspect
        sig = inspect.signature(ca.PROBES[PROBE_NAME])
        self.assertIn("repo_root", sig.parameters)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
