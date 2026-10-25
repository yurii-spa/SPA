"""Контроль пробы `answer_list_order_names_its_caller` — в ОБЕ стороны.

Заказ **G801 п. 2** приказа владельца «Portfolio CIO».

## Чего требует заказ и почему этого нельзя было измерить

Заказ велит после первого живого такта ступени сверить ТРИ вещи, и вторая из
них — «что отметка ``generated_at`` принадлежит прогону МОСТА (а не чьей-то
руке)». На документе переписи порядка этот вопрос был НЕИЗМЕРИМ ПО ПОСТРОЕНИЮ,
и это уже измерено однажды: ADR-411 (заказ G36 п. 1) разобрал ровно такое же
наблюдение у соседа и назвал его односторонность — ``generated_at`` есть ЧАСЫ,
а не звавший, поэтому отметка сменится ОДИНАКОВО при зове ступенью и при зове
рукой. Отметка НЕ сменилась ⇒ ступень молчит (вывод верен); сменилась ⇒ не
известно НИЧЕГО.

## Почему проба, а не «тест есть — значит работает»

`.claude/rules/acceptance.md` п. 3: проба меряет ИСХОД, не структуру, и
регистрируется только с тестом, где она зелена на целом контуре и КРАСНА на
каждом порванном звене — с названным звеном. Поэтому здесь по сцене на звено:

| звено | как молчит, если порвано |
|---|---|
| поля нет вовсе | читатель принял бы молчание за «звал мост» |
| поле есть, звавший НЕ ИЗМЕРЕН | третий исход выдан за ответ |
| запись — КОНСТАНТА | оба зова называются одинаково: ответ на чужой вопрос |
| запись не о звавшем | имя названо, но не то, которым звали |
| строки отчёта молчат | запись есть, читателя нет (класс ADR-345) |
| строки отчёта — константа | «назвал» подстрокой, вердикт не зависит от зова |
| строк отчёта нет вовсе | НЕ ИЗМЕРЕНО, а не «читателя нет» (инв. #17) |

Целый контур меряется НАСТОЯЩИМИ подпроцессами через НАСТОЯЩИЕ двери: признак
берётся у процесса, и подстановка ``main_file=`` проверяла бы РАЗБОР своего же
входа, а не исход.

Литеральных дат и литеральных pid здесь нет: якорь времени живёт в бегуне
пробы, об ОС этот файл не спрашивает ничего.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import card_acceptance as ca

PROBE = "answer_list_order_names_its_caller"
ONE = "alo_caller_scene_one.py"
TWO = "alo_caller_scene_two.py"


def _scene(entry: str | None, *, measured: bool = True,
           lines: list | None = None, record: object = "default") -> dict:
    """Сцена-ответ одного прогона: запись о звавшем + строки отчёта.

    `record="default"` значит «собери запись из `entry`/`measured`»; любое другое
    значение кладётся в документ ДОСЛОВНО — так строятся сцены «поля нет вовсе» и
    «поле не словарь».
    """
    if record == "default":
        record = ({"schema": "call_provenance.v1", "measured": True,
                   "entry": entry, "inside_tree": False, "doors_agree": True}
                  if measured else
                  {"schema": "call_provenance.v1", "measured": False,
                   "reason": "точка входа не прочитана ни одной дверью"})
    scene: dict = {"lines": (["перепись порядка списков ответа (x): UNMEASURED",
                              f"  [ЗВАВШИЙ] позван из точки входа `{entry}`"]
                             if lines is None else lines)}
    if record is not None:
        scene["invoked_by"] = record
    return scene


class ProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Каждое звено рвётся по отдельности, и причина НАЗЫВАЕТ его."""

    def _verdict(self, scenes):
        return ca.PROBES[PROBE](None, scenes=scenes)

    def test_the_probe_is_registered_under_its_name(self):
        self.assertIn(PROBE, ca.PROBES)

    def test_a_document_without_the_record_is_not_satisfied(self):
        status, why = self._verdict([_scene(ONE, record=None), _scene(TWO)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("invoked_by", why)

    def test_an_unmeasured_record_is_not_passed_off_as_an_answer(self):
        status, why = self._verdict([_scene(ONE, measured=False), _scene(TWO)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("НЕ ИЗМЕРИЛ", why)

    def test_a_constant_record_names_both_calls_the_same_and_fails(self):
        """КОНСТАНТА проходит «поле есть» и валит «различает зовы».

        Ровно эту форму имеет `generated_by` соседа: имя самого производителя,
        один и тот же ответ при любом зове.
        """
        status, why = self._verdict([_scene(ONE), _scene(ONE)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("одинаково", why)

    def test_a_record_that_names_someone_else_fails(self):
        status, why = self._verdict([_scene("findings_bridge.py"), _scene(TWO)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("не о звавшем", why)

    def test_a_record_nobody_prints_fails_as_a_finding_without_a_reader(self):
        status, why = self._verdict([
            _scene(ONE, lines=["перепись порядка списков ответа (x): UNMEASURED"]),
            _scene(TWO)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("читателя", why)

    def test_the_probe_does_not_pass_on_a_substring(self):
        """ADR-333: строка, называющая ОБА имени, вердикта не покупает.

        Отрисовка-константа содержит нужную подстроку в каждом прогоне, и
        наивная проба («имя встречается») была бы зелена. Вердикт обязан
        зависеть от ЗОВА, поэтому сцены сравниваются между собой.
        """
        constant = [f"  [ЗВАВШИЙ] позван из `{ONE}` либо `{TWO}`"]
        status, why = self._verdict([_scene(ONE, lines=constant),
                                     _scene(TWO, lines=constant)])
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("совпали", why)

    def test_missing_report_lines_are_unmeasured_not_a_verdict(self):
        """Третий исход: строк НЕТ — это «измерить нечем», а не «читателя нет»."""
        scene = _scene(ONE)
        scene.pop("lines")
        status, why = self._verdict([scene, _scene(TWO)])
        self.assertEqual(status, ca.UNMEASURED, why)

    def test_a_broken_runner_is_unmeasured_not_a_disagreement(self):
        """«Нечем измерить» согласием не печатается НИКОГДА (fail-OPEN тише)."""
        status, why = self._verdict([_scene(ONE)])
        self.assertEqual(status, ca.UNMEASURED, why)

    def test_the_whole_contour_is_satisfied(self):
        status, why = self._verdict([_scene(ONE), _scene(TWO)])
        self.assertEqual(status, ca.SATISFIED, why)


class ProbeIsGreenOnTheRealContour(unittest.TestCase):
    """Положительный контроль НАСТОЯЩИМИ дверями, без инъекции сцен."""

    def test_two_real_entry_points_give_opposite_names(self):
        status, why = ca.PROBES[PROBE](None)
        self.assertEqual(status, ca.SATISFIED, why)
        self.assertIn(ONE, why)
        self.assertIn(TWO, why)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
