"""Контроль пробы `door_sites_operand_agrees` (карточка
`inbox-operand-summa-ishodov-dveri-razoshelsya`, цикл #926).

# LLM_FORBIDDEN

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом,
где она зелена на целом контуре и КРАСНА на каждом порванном звене — с названным
звеном, — и где она не проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, есть украшение.

Главная сцена здесь — `test_a_compensating_loss_is_named_though_the_total_is
_unchanged`: `sites −1` рядом с `out_of_subject +1` даёт ТОТ ЖЕ итог, а площадка
при этом ПОТЕРЯНА. Ровно этого прежний храповик (сверка одного ИТОГА) увидеть не
мог по построению, и ровно ради запрета на молчаливую потерю он написан.

Вторая по важности — `test_a_reprinted_total_does_not_pass`: объявить итог и не
тронуть слагаемые было бы честным выходом наружу, если бы объявление не
сверялось само с собой.
"""
from __future__ import annotations

import json
import unittest

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES,
                                                 SATISFIED, UNMEASURED)
from spa_core.tests import _fixture_schema_gap as gap

PROBE_NAME = "door_sites_operand_agrees"

#: Скелет замера: пять ведер с РАЗНЫМИ счётами нарочно — равные счёта не
#: различили бы перепутанные местами ведра (урок #786).
_WHOLE = {"sites": 7, "unmeasured": 3, "out_of_subject": 5,
          "built_by_call": 11, "mutation_unmodelled": 2}


def _census(**over):
    counts = dict(_WHOLE)
    counts.update(over)
    return gap.Census(files_scanned=13,
                      **{name: ["x"] * n for name, n in counts.items()})


def _baseline(counts=None, total=None, **over):
    counts = dict(_WHOLE if counts is None else counts)
    counts.update(over)
    doc = {"door_sites": counts,
           "door_sites_total": sum(counts.values()) if total is None else total}
    return doc


def _probe(**kw):
    return PROBES[PROBE_NAME](None, **kw)


class WholeContour(unittest.TestCase):
    """Целый контур — и НАСТОЯЩЕЕ дерево, и собранная сцена."""

    def test_the_assembled_whole_contour_is_satisfied(self) -> None:
        verdict, why = _probe(census=_census(), baseline=_baseline())
        self.assertEqual(SATISFIED, verdict, why)
        self.assertIn("СЛОЖЕН из них", why)
        # Итог назван слагаемыми, а не одним числом: иначе вердикт нечем
        # проверить читателю.
        for name, n in _WHOLE.items():
            self.assertIn(f"{name} {n}", why)

    def test_the_real_tree_is_satisfied(self) -> None:
        """Положительный контроль на ЖИВОМ дереве — это и есть приёмка карточки.

        Без него батарея говорила бы только о собранных сценах, а предмет
        карточки — операнд ЭТОГО репозитория.
        """
        verdict, why = _probe()
        self.assertEqual(SATISFIED, verdict, why)


class BrokenLinks(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и вердикт НАЗЫВАЕТ, какое именно."""

    def test_an_appearance_moves_the_total_and_is_refused(self) -> None:
        verdict, why = _probe(census=_census(sites=9), baseline=_baseline())
        self.assertEqual(NOT_SATISFIED, verdict, why)
        self.assertIn("измерено 30", why)
        self.assertIn("объявлено 28", why)
        self.assertIn("sites", why)

    def test_a_compensating_loss_is_named_though_the_total_is_unchanged(self) -> None:
        """ГЛАВНАЯ сцена: итог тот же, а площадка ПРОПАЛА."""
        verdict, why = _probe(
            census=_census(sites=6, out_of_subject=6), baseline=_baseline())
        self.assertEqual(NOT_SATISFIED, verdict, why)
        # Направление пришпилено К СВОЕМУ ведру целой строкой, а не словами
        # врассыпную: при компенсации в тексте есть ОБА слова, и проверка
        # «есть ПРОПАЛА и есть ПОЯВИЛАСЬ» пережила бы перепутанные местами
        # направления — мутация именно это и показала (ADR-803, первый проход).
        self.assertIn("`sites`: объявлено 7, измерено 6 ⇒ площадка ПРОПАЛА (-1)",
                      why)
        self.assertIn("`out_of_subject`: объявлено 5, измерено 6 ⇒ площадка "
                      "ПОЯВИЛАСЬ (+1)", why)

    def test_a_reprinted_total_does_not_pass(self) -> None:
        """Итог объявлен, слагаемые не тронуты — объявление спорит само с собой."""
        verdict, why = _probe(census=_census(sites=9),
                              baseline=_baseline(total=30))
        self.assertEqual(NOT_SATISFIED, verdict, why)
        self.assertIn("не сходится САМО С СОБОЙ", why)
        self.assertIn("перепечатан, а не сложен", why)

    def test_a_missing_decomposition_is_the_third_outcome(self) -> None:
        """Итог сошёлся, разложения нет ⇒ «нечем измерить», а не согласие."""
        doc = _baseline()
        doc.pop("door_sites")
        verdict, why = _probe(census=_census(), baseline=doc)
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("ПОТЕРЯННОЙ площадке", why)

    def test_an_incomplete_decomposition_is_the_third_outcome(self) -> None:
        doc = _baseline()
        doc["door_sites"].pop("built_by_call")
        doc["door_sites_total"] = sum(doc["door_sites"].values())
        verdict, why = _probe(census=_census(built_by_call=0), baseline=doc)
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("built_by_call", why)
        self.assertIn("сумма неполна", why)

    def test_an_unknown_outcome_in_the_decomposition_is_the_third_outcome(self) -> None:
        doc = _baseline()
        doc["door_sites"]["invented_outcome"] = 0
        verdict, why = _probe(census=_census(), baseline=doc)
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("invented_outcome", why)
        self.assertIn("OPERAND_BUCKETS", why)

    def test_a_missing_total_is_the_third_outcome(self) -> None:
        doc = _baseline()
        doc.pop("door_sites_total")
        verdict, why = _probe(census=_census(), baseline=doc)
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("door_sites_total", why)

    def test_a_total_of_the_wrong_type_is_the_third_outcome(self) -> None:
        """`observed` судит и РОД значения: строка «121» числом не является."""
        verdict, why = _probe(census=_census(), baseline=_baseline(total="28"))
        self.assertEqual(UNMEASURED, verdict, why)


class NothingToMeasure(unittest.TestCase):
    """«Предмета нет» никогда не печатается согласием (инв. #17)."""

    def test_no_file_calls_the_door(self) -> None:
        verdict, why = _probe(census=gap.Census(files_scanned=0),
                              baseline=_baseline())
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("нулём это не считается", why)

    def test_no_site_is_resolved_to_a_document(self) -> None:
        verdict, why = _probe(census=_census(sites=0), baseline=_baseline())
        self.assertEqual(UNMEASURED, verdict, why)
        self.assertIn("подделка доказательства", why)

    def test_an_unreadable_baseline_is_the_third_outcome(self) -> None:
        """База, которой нечем быть словарём, — третий исход, а не ноль."""
        verdict, why = _probe(census=_census(), baseline={})
        self.assertEqual(UNMEASURED, verdict, why)


class NotBySubstring(unittest.TestCase):
    """ADR-333: вердикт решает ЗАМЕР, а не присутствие слова."""

    def test_the_probe_is_reachable_by_name_from_the_registry(self) -> None:
        self.assertIn(PROBE_NAME, PROBES)
        self.assertNotIn(PROBE_NAME + "_x", PROBES)

    def test_the_declared_name_of_an_outcome_does_not_decide_the_verdict(self) -> None:
        """Слово «satisfied» внутри базы согласия не даёт."""
        doc = _baseline(sites=99)
        doc["_"] = "satisfied: операнд двери сошёлся по ведрам и СЛОЖЕН из них"
        verdict, _why = _probe(census=_census(), baseline=doc)
        self.assertEqual(NOT_SATISFIED, verdict)

    def test_the_declaration_is_read_as_json_not_as_text(self) -> None:
        """Та же база, поданная ТЕКСТОМ, согласия не даёт — читается документ."""
        doc = _baseline()
        verdict, _why = _probe(census=_census(), baseline=json.dumps(doc))
        self.assertEqual(UNMEASURED, verdict)


class TheOperandNamesEveryOutcome(unittest.TestCase):
    """Перечень ведер — ОДИН, и он обязан покрывать все исходы двери."""

    def test_every_bucket_exists_on_the_census(self) -> None:
        census = gap.Census()
        for name in gap.OPERAND_BUCKETS:
            self.assertIsInstance(getattr(census, name), list, name)

    def test_the_operand_helper_agrees_with_the_bucket_list(self) -> None:
        census = _census()
        self.assertEqual(_WHOLE, gap.operand(census))
        self.assertEqual(tuple(gap.operand(census)), gap.OPERAND_BUCKETS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
