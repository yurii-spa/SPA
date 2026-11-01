"""Контроль пробы `fixture_gap_class_is_empty` — в ОБЕ стороны.

# LLM_FORBIDDEN

Правило приёмки, п. 3 (`.claude/rules/acceptance.md`): проба регистрируется
только с тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном
звене — с НАЗВАННЫМ звеном, — и где она НЕ проходит подстрокой (ADR-333).

Авария, которую проба воспроизводит (замер цикла #1002, ADR-887): храповик
`test_fixture_schema_gap_ratchet.py` стоял красен на чистом `origin/main` с
цикла #966 по #1002, и красен ТРЕМЯ тестами, за которыми ДВА РАЗНЫХ вопроса —
«жив ли класс» (население 12) и «не пропала ли площадка» (операнд 136 против
128). Сосед `door_sites_operand_agrees` отвечает на ВТОРОЙ; на первый до этого
цикла не отвечала ни одна проба, и закрыть его можно было ходом, которого не
ловил никто: дописать шесть имён в `keys` базы.

Три звена контура, и каждое рвётся ОТДЕЛЬНОЙ сценой с НЕРАВНЫМИ счётами:
население · освобождение без причины · непустая база. Плюс третий исход
(инв. #17) — у него СВОИ сцены, и «нечем измерить» согласием не печатается.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from spa_core.monitoring.card_acceptance import (
    NOT_SATISFIED, PROBES, SATISFIED, UNMEASURED,
)
from spa_core.tests import _fixture_schema_gap as gap

_PROBE = "fixture_gap_class_is_empty"
_ARTIFACT = "shadow_trigger_evaluation.json"


def _site(*, line: int, missing: tuple[str, ...] = ("trim_optimum_census",),
          exempt: str | None = None) -> gap.Site:
    return gap.Site(file="spa_core/tests/test_scene.py", line=line,
                    artifact=_ARTIFACT, missing=missing, declared=13,
                    exempt_reason=exempt)


def _census(*, population: int = 0, exempt: int = 1,
            bare: int = 0) -> gap.Census:
    """Замер-сцена: ВЫЧИСЛЯЕМЫЕ свойства `Census` остаются настоящими.

    Подменяется ВХОД прибора (площадки), а не его вывод: `population` и
    `exempt` — свойства класса `Census`, и сцена их не переписывает. Иначе
    проба проверяла бы свой же вход.
    """
    sites = [_site(line=100 + n) for n in range(population)]
    sites += [_site(line=200 + n, exempt="предмет сцены") for n in range(exempt)]
    return gap.Census(
        files_scanned=65, sites=sites,
        marker_without_reason=[("spa_core/tests/test_scene.py", 300 + n)
                               for n in range(bare)])


def _baseline(**over) -> dict:
    base = {"keys": {}, "door_sites_total": 136,
            "door_sites": {name: 0 for name in gap.OPERAND_BUCKETS}}
    base.update(over)
    return base


def _ask(**kw):
    return PROBES[_PROBE](None, **kw)


class TheWholeCircuitIsSatisfied(unittest.TestCase):

    def test_an_empty_class_with_an_empty_base_is_satisfied(self) -> None:
        verdict, why = _ask(census=_census(), baseline=_baseline())
        self.assertEqual(verdict, SATISFIED, why)

    def test_the_satisfied_reason_names_the_MEASURED_numbers(self) -> None:
        """Согласие печатает замер, а не постоянную строку.

        Без этого теста проба могла бы «проходить подстрокой»: вернуть один и
        тот же текст на любом замере. Две сцены с РАЗНЫМ числом освобождений
        обязаны дать РАЗНЫЕ строки.
        """
        _, one = _ask(census=_census(exempt=1), baseline=_baseline())
        _, many = _ask(census=_census(exempt=7), baseline=_baseline())
        self.assertNotEqual(one, many)
        self.assertIn("1", one)
        self.assertIn("7", many)

    def test_the_probe_is_registered_under_its_declared_name(self) -> None:
        self.assertIn(_PROBE, PROBES)


class EachTornLinkIsRefusedAndNamed(unittest.TestCase):
    """Счёты у сцен НЕРАВНЫЕ — иначе сцены неразличимы (урок #786)."""

    def test_a_live_population_is_refused_and_the_site_is_named(self) -> None:
        verdict, why = _ask(census=_census(population=2), baseline=_baseline())
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("население класса 2", why)
        self.assertIn("test_scene.py:100", why)

    def test_a_marker_without_a_reason_is_refused(self) -> None:
        verdict, why = _ask(census=_census(bare=3), baseline=_baseline())
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("без причины", why)
        self.assertIn("test_scene.py:300", why)

    def test_a_non_empty_base_is_refused_even_at_zero_population(self) -> None:
        """Главное звено: класс ПУСТ, а база ВЫРОСЛА — и это по-прежнему отказ.

        Ровно этот ход и был доступным выходом до ADR-887: дописать имена в
        `keys`, получить население 0 и зелёный главный храповик при живом вреде.
        """
        verdict, why = _ask(
            census=_census(),
            baseline=_baseline(keys={f"{_ARTIFACT}::a": 5}))
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("НЕ ПУСТА", why)
        self.assertIn(f"{_ARTIFACT}::a", why)

    def test_the_three_links_are_distinguishable_from_one_another(self) -> None:
        """Три отказа — ТРИ РАЗНЫЕ строки, а не одно слово «не сошлось»."""
        reasons = {
            _ask(census=_census(population=2), baseline=_baseline())[1],
            _ask(census=_census(bare=3), baseline=_baseline())[1],
            _ask(census=_census(), baseline=_baseline(keys={"a::b": 1}))[1],
        }
        self.assertEqual(len(reasons), 3, reasons)

    def test_all_three_broken_at_once_are_all_named(self) -> None:
        """Назван ПЕРВЫЙ отказ — значит остальные два невидимы (урок #843)."""
        verdict, why = _ask(
            census=_census(population=1, bare=1),
            baseline=_baseline(keys={"a::b": 1}))
        self.assertEqual(verdict, NOT_SATISFIED, why)
        for fragment in ("НЕ ПУСТА", "без причины", "население класса"):
            self.assertIn(fragment, why)


class TheThirdOutcomeIsItsOwnVerdict(unittest.TestCase):
    """«Нечем измерить» согласием не печатается НИКОГДА (инв. #17)."""

    def test_a_census_without_a_single_door_file_is_unmeasured(self) -> None:
        census = _census()
        census.files_scanned = 0
        verdict, why = _ask(census=census, baseline=_baseline())
        self.assertEqual(verdict, UNMEASURED, why)
        self.assertIn("ни один тест-файл", why)

    def test_a_census_without_a_resolved_site_is_unmeasured(self) -> None:
        verdict, why = _ask(census=gap.Census(files_scanned=65),
                            baseline=_baseline())
        self.assertEqual(verdict, UNMEASURED, why)
        self.assertIn("ни одна площадка", why)

    def test_a_baseline_without_keys_as_a_dict_is_unmeasured(self) -> None:
        for broken in ({}, {"keys": []}, {"keys": "нет"}):
            with self.subTest(baseline=broken):
                verdict, why = _ask(census=_census(), baseline=broken)
                self.assertEqual(verdict, UNMEASURED, why)
                self.assertIn("`keys`", why)

    def test_a_baseline_that_is_not_a_document_is_unmeasured(self) -> None:
        verdict, why = _ask(census=_census(), baseline="не документ")
        self.assertEqual(verdict, UNMEASURED, why)
        self.assertIn("не документом", why)

    def test_an_unmeasured_verdict_never_reads_as_satisfied(self) -> None:
        """Отрицательный контроль третьего исхода: он не согласие и не отказ."""
        verdict, _ = _ask(census=gap.Census(files_scanned=0),
                          baseline=_baseline())
        self.assertNotEqual(verdict, SATISFIED)
        self.assertNotEqual(verdict, NOT_SATISFIED)


class ThePopulationIsNotTakenOnTrustFromTheScene(unittest.TestCase):
    """Проба обязана спрашивать ПРИБОР, а не поле сцены.

    Сцена здесь подменяет ВХОД (список площадок), а `population` / `exempt` —
    вычисляемые свойства `Census`. Если проба начнёт читать подставленное число
    вместо свойства, эти два теста разойдутся.
    """

    def test_an_exempt_site_is_not_counted_as_population(self) -> None:
        census = gap.Census(files_scanned=65,
                            sites=[_site(line=10, exempt="предмет сцены")])
        self.assertEqual(len(census.population), 0)
        verdict, why = _ask(census=census, baseline=_baseline())
        self.assertEqual(verdict, SATISFIED, why)

    def test_the_same_site_without_a_reason_IS_population(self) -> None:
        census = gap.Census(files_scanned=65, sites=[_site(line=10)])
        self.assertEqual(len(census.population), 1)
        verdict, why = _ask(census=census, baseline=_baseline())
        self.assertEqual(verdict, NOT_SATISFIED, why)


class TheLiveTreeAgrees(unittest.TestCase):
    """Проба на СВОЁМ дереве: предмет у замера есть, и вердикт определён."""

    def test_the_live_verdict_is_one_of_the_three_and_carries_numbers(self) -> None:
        verdict, why = _ask()
        self.assertIn(verdict, {SATISFIED, NOT_SATISFIED, UNMEASURED}, why)
        self.assertTrue(why.strip(), "вердикт без причины вердиктом не является")


@dataclass
class _Frozen:
    """Положительный контроль ДОСЛОВНОЙ аварии цикла #966…#1002.

    Двенадцать площадок одного артефакта, ни одной освобождённой — то
    состояние, в котором `origin/main` стоял 36 циклов. Числа взяты из замера
    (`spa_core/tests/fixture_schema_gap_baseline.json`, поправка ADR-887), а не
    из головы.
    """

    population: int = 12
    exempt: int = 31


class TheIncidentOfCycle966IsReproduced(unittest.TestCase):

    def test_the_incident_shape_is_refused_with_its_number(self) -> None:
        shape = _Frozen()
        verdict, why = _ask(
            census=_census(population=shape.population, exempt=shape.exempt),
            baseline=_baseline())
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn(f"население класса {shape.population}", why)

    def test_the_cure_of_cycle_1002_turns_the_same_shape_green(self) -> None:
        """Та же сцена, РОВНО одно отличие: 12 площадок освобождены с причиной."""
        shape = _Frozen()
        verdict, why = _ask(
            census=_census(population=0,
                           exempt=shape.exempt + shape.population),
            baseline=_baseline())
        self.assertEqual(verdict, SATISFIED, why)
        self.assertIn(str(shape.exempt + shape.population), why)


if __name__ == "__main__":          # pragma: no cover
    unittest.main()
