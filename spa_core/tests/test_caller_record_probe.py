"""Контроль в обе стороны для пробы `tact_stage_names_its_caller` (ADR-805).

Порядок `.claude/rules/acceptance.md` п. 3: проба регистрируется только с тестом,
где она ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене — с названным
звеном, — и где подстрока вердикта не покупает (ADR-333).

Звенья рвутся подменой СЦЕНЫ, а не правкой прибора: сцена есть вход пробы, и
подмена оставляет предметом пробы её собственное суждение. Правка прибора
проверяла бы прибор, то есть отвечала бы на ЧУЖОЙ вопрос.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from spa_core.monitoring import card_acceptance as ca
from spa_core.tests import _caller_record_gap as crg

PROBE = "tact_stage_names_its_caller"


def _census_of(labels: dict) -> crg.Census:
    """Перепись, собранная ПРЯМО из ярлыков: `{имя: ведро}`."""
    buckets: dict[str, list] = {name: [] for name in crg.OPERAND_BUCKETS}
    for name, bucket in labels.items():
        buckets[bucket].append(crg.Stage(
            name, f"{name}.py", bucket,
            "подменённая сцена" if bucket == "unmeasured" else None))
    return crg.Census(carries=tuple(buckets["carries"]),
                      missing=tuple(buckets["missing"]),
                      no_tact=tuple(buckets["no_tact"]),
                      unmeasured=tuple(buckets["unmeasured"]),
                      stages_declared=len(labels))


def _scenes(script):
    """Сцена, отвечающая по ЗАКАЗАННЫМ ярлыкам вместо настоящего разбора."""
    def build(sources: dict):
        labels, problems, unmeasured = script(sorted(sources))
        census = _census_of(labels)
        return census, crg.Verdict(crg.operand(census), {}, (),
                                   unmeasured=unmeasured, problems=list(problems))
    return build


def _honest(names):
    """Ярлыки, какие даёт НАСТОЯЩИЙ прибор на каждой из пяти сцен пробы."""
    truth = {"alpha": "missing", "beta": "carries", "gamma": "missing",
             "delta": "missing", "epsilon": "no_tact", "zeta": "unmeasured"}
    labels = {n: truth[n] for n in names}
    problems = [f"  ПОЯВИЛАСЬ {n} ({n}.py): …"
                for n, b in labels.items() if b == "missing"]
    unmeasured = ("ступени НЕ ИЗМЕРЕНЫ (zeta: подменённая сцена)"
                  if "zeta" in labels else None)
    return labels, problems, unmeasured


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):

    def test_the_real_instrument_satisfies_the_probe(self):
        verdict, say = ca.PROBES[PROBE](None)
        self.assertEqual("satisfied", verdict, say)
        self.assertIn("класс закрыт ОДНИМ читателем", say)

    def test_an_honest_substitute_scene_also_satisfies(self):
        """Положительный контроль самой подмены: сцена, отвечающая КАК прибор,
        пробу проходит. Без него «красна на всём» было бы неотличимо от
        «сломана проводка подмены»."""
        verdict, say = ca.PROBES[PROBE](None, scenes=_scenes(_honest))
        self.assertEqual("satisfied", verdict, say)


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):

    def _broken(self, script):
        return ca.PROBES[PROBE](None, scenes=_scenes(script))

    def test_a_tact_stage_without_a_record_counted_as_carrying(self):
        def script(names):
            labels, problems, un = _honest(names)
            if "alpha" in labels:
                labels["alpha"] = "carries"
                problems = []
            return labels, problems, un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("в класс не попала", say)

    def test_a_class_measured_but_not_named_by_the_verdict(self):
        def script(names):
            labels, problems, un = _honest(names)
            return labels, ([] if "alpha" in labels else problems), un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("вердикт ступень НЕ НАЗЫВАЕТ", say)

    def test_a_record_named_only_as_a_substring_closing_the_class(self):
        def script(names):
            labels, problems, un = _honest(names)
            if "gamma" in labels:
                labels["gamma"] = "carries"
            return labels, problems, un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("ПОДСТРОКОЙ", say)

    def test_a_caller_declared_as_a_parameter_closing_the_class(self):
        def script(names):
            labels, problems, un = _honest(names)
            if "delta" in labels:
                labels["delta"] = "carries"
            return labels, problems, un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("ПАРАМЕТРОМ", say)

    def test_a_tact_named_only_in_prose_dragged_into_the_population(self):
        def script(names):
            labels, problems, un = _honest(names)
            if "epsilon" in labels:
                labels["epsilon"] = "missing"
                problems = [f"  ПОЯВИЛАСЬ epsilon (epsilon.py): …"]
            return labels, problems, un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("в прозе", say)

    def test_an_absent_module_reported_as_a_missing_record(self):
        def script(names):
            labels, problems, un = _honest(names)
            if "zeta" in labels:
                labels["zeta"] = "missing"
                problems, un = ["  ПОЯВИЛАСЬ zeta (zeta.py): …"], None
            return labels, problems, un
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("третьим исходом", say)

    def test_an_unmeasured_stage_whose_verdict_stays_silent(self):
        def script(names):
            labels, problems, un = _honest(names)
            return labels, problems, (None if "zeta" in labels else un)
        verdict, say = self._broken(script)
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("вердикт об этом молчит", say)


class TheProbeDoesNotPassOnASubstring(unittest.TestCase):
    """ADR-333: вердикт покупается ведром, а не текстом рядом."""

    def test_a_scene_that_only_mentions_the_right_words_is_red(self):
        def script(names):
            labels = {n: "carries" for n in names}
            return labels, ["  ПОЯВИЛАСЬ alpha · ПОДСТРОКОЙ · в прозе · "
                            "третьим исходом · вердикт об этом молчит"], None
        verdict, say = ca.PROBES[PROBE](None, scenes=_scenes(script))
        self.assertEqual("not_satisfied", verdict, say)


class TheProbeRefusesWhatItCannotMeasure(unittest.TestCase):

    def test_an_unreadable_baseline_is_unmeasured_not_satisfied(self):
        root = pathlib.Path(crg.__file__).resolve().parents[2]
        base = root / "spa_core" / "tests" / "caller_record_baseline.json"
        saved = base.read_bytes()
        try:
            base.write_text("не документ", encoding="utf-8")
            verdict, say = ca.PROBES[PROBE](None)
            self.assertEqual("unmeasured", verdict, say)
            self.assertIn("база не прочитана", say)
        finally:
            base.write_bytes(saved)

    def test_a_baseline_that_parses_but_is_not_a_document_is_unmeasured(self):
        """Дыра покрытия, найденная мутацией #14 замера ADR-805.

        Сцена «нечитаемая база» выше задевает ветку РАЗБОРА JSON, а не ветку
        `live_verdict.unmeasured`: «не документ» не парсится вовсе, и проба
        выходит раньше. Поэтому мутация «НЕЧЕМ ИЗМЕРИТЬ выдано за согласие»
        переживала ВСЮ батарею — то есть того перевода не стерёг никто. База,
        которая ПАРСИТСЯ и документом не является, доводит до нужной ветки.
        """
        root = pathlib.Path(crg.__file__).resolve().parents[2]
        base = root / "spa_core" / "tests" / "caller_record_baseline.json"
        saved = base.read_bytes()
        try:
            base.write_text("[]", encoding="utf-8")
            verdict, say = ca.PROBES[PROBE](None)
            self.assertEqual("unmeasured", verdict, say)
            self.assertIn("замер на живом дереве", say)
            self.assertIn("не документом", say)
        finally:
            base.write_bytes(saved)

    def test_a_live_tree_that_disagrees_with_the_baseline_is_not_satisfied(self):
        root = pathlib.Path(crg.__file__).resolve().parents[2]
        base = root / "spa_core" / "tests" / "caller_record_baseline.json"
        saved = base.read_bytes()
        try:
            doc = json.loads(saved.decode("utf-8"))
            doc["missing"] = doc["missing"][1:]
            doc["missing_total"] = len(doc["missing"])
            base.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            verdict, say = ca.PROBES[PROBE](None)
            self.assertEqual("not_satisfied", verdict, say)
            self.assertIn("замер разошёлся с объявлением", say)
        finally:
            base.write_bytes(saved)

    def test_a_missing_instrument_is_not_satisfied_with_a_named_reason(self):
        """Состояние ДО работы цикла: прибора нет, класс живёт прозой ADR."""
        import builtins  # noqa: PLC0415
        real = builtins.__import__

        def refuse(name, *a, **kw):
            if name == "spa_core.tests" and "_caller_record_gap" in (a[2] or ()):
                raise ImportError("cannot import name '_caller_record_gap'")
            return real(name, *a, **kw)
        builtins.__import__ = refuse
        try:
            verdict, say = ca.PROBES[PROBE](None)
        finally:
            builtins.__import__ = real
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("прибора переписи нет", say)
        self.assertIn("читателя не имеет", say)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
