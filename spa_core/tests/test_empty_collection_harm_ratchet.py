#!/usr/bin/env python3
"""Храповик класса «перечень ИЗМЕРЕН вредным пустым» (ADR-944).

# LLM_FORBIDDEN

База `empty_collection_harm_baseline.json` может **только УБЫВАТЬ**. Дописывать в неё
запись, чтобы погасить падение, ЗАПРЕЩЕНО — тот же порядок, что у
`frozen_date_baseline.json`, `tree_content_class_baseline.json`,
`ci_only_red_class_baseline.json` (инв. #16).

**Направление храповика выбрано, а не угадано.** Проверять «все предметы переписи
объявлены» было бы неверно: предмет есть ВЕРХНЯЯ граница вреда (571 на 07.11), а
дефектов среди них меньше, и требовать от базы полноты значило бы ЗАСТАВИТЬ дописывать
в неё — ровно против чего храповик написан. Поэтому контракт обратный и односторонний:
**каждая запись базы обязана ОСТАВАТЬСЯ предметом переписи.** Появилось противоядие —
перечень ушёл из предмета, и запись обязана УЙТИ из базы: это и есть убывание.

Цена: 1 перепись дерева (замер 07.11 — 44 с). Третий исход громкий: перепись не
измерилась ⇒ падать с названной причиной, а не судить о пустоте (инв. #17).
"""

from __future__ import annotations

import unittest

from spa_core.monitoring import declared_collection_census as census_mod
from spa_core.tests import _empty_collection_harm as harm


class HarmBaselineRatchet(unittest.TestCase):
    """Перепись зовётся ОДИН раз на класс: она стоит секунды, а вопросов к ней три."""

    @classmethod
    def setUpClass(cls):
        cls.doc = harm.load_baseline()
        cls.result = census_mod.census()
        cls.rows = {harm.key(r["module"], r["name"]): r for r in cls.result["rows"]}
        cls.signal = harm.production(
            [r for r in cls.result["rows"] if r["subject"]])
        cls.production = {
            harm.key(r["module"], r["name"]): r["production"]
            for r in cls.signal["rows"]
        }

    def test_the_census_itself_was_measured(self):
        """«Не измерено» нулём не считается: перепись, не прочитавшая файл, не вправе
        отвечать о предмете — иначе запись базы «уже не предмет» означала бы «прибор
        ослеп», а храповик велел бы её снять."""
        self.assertFalse(
            self.result["unmeasured"],
            "перепись НЕ ИЗМЕРЕНА: "
            f"объявления {self.result['unparsable_declaration_files']} · "
            f"читатели {self.result['unparsable_reader_files']}")

    def test_every_declared_entry_still_exists_in_the_tree(self):
        missing = [
            entry for entry in self.doc["harmful"]
            if harm.key(entry["module"], entry["name"]) not in self.rows
        ]
        self.assertEqual(
            missing, [],
            "объявление класса называет перечни, которых в дереве НЕТ — "
            "перенесены или переименованы; запись обязана быть снята или поправлена")

    def test_every_declared_entry_is_still_a_subject_of_the_census(self):
        """Единственное разрешённое движение базы — ВНИЗ: перечень, получивший
        противоядие, выходит из предмета, и его запись обязана уйти."""
        fixed = [
            f"{entry['module']}::{entry['name']}"
            for entry in self.doc["harmful"]
            if not self.rows[harm.key(entry["module"], entry["name"])]["subject"]
        ]
        self.assertEqual(
            fixed, [],
            "у этих перечней появилось противоядие — они больше не предмет переписи. "
            "СНЯТЬ их из `harmful` в empty_collection_harm_baseline.json "
            f"(база может только убывать): {fixed}")

    def test_every_declared_entry_came_from_the_prioritised_population(self):
        """Запись базы обязана происходить из признака, которым её искали. Запись,
        признаку не отвечающая, пришла мимо замера — и это дефект ОБЪЯВЛЕНИЯ, а не
        повод расширить признак молча."""
        stray = {
            f"{entry['module']}::{entry['name']}":
                self.production.get(harm.key(entry["module"], entry["name"]), "НЕТ В ПРИЗНАКЕ")
            for entry in self.doc["harmful"]
            if self.production.get(harm.key(entry["module"], entry["name"])) != "produces"
        }
        self.assertEqual(
            stray, {},
            "записи базы не отвечают признаку `production == produces`, которым класс "
            f"мерили: {stray}")

    def test_the_signal_population_has_all_three_outcomes_distinguishable(self):
        """Признак обязан уметь сказать «не измерено» — иначе его молчание неотличимо
        от «вреда нет» (инв. #17)."""
        tally = self.signal["tally"]
        self.assertEqual(set(tally), set(harm.PRODUCTION_OUTCOMES))
        self.assertEqual(sum(tally.values()), self.result["subject"],
                         "признак обязан ответить о КАЖДОМ предмете переписи")
        self.assertGreater(tally["produces"], 0, "признак не нашёл ни одного кандидата — "
                                                 "это сам по себе повод перемерить прибор")

    def test_the_recorded_direction_agrees_with_the_LIVE_instrument(self):
        """Род вреда у записи сверяется ПАРИТЕТОМ с прибором, а не литералом в базе.

        Литерал краснел бы от своего же производителя — дефект, уже оплаченный
        (`observed_floor`, цикл #1055): число выводится прибором, и держать его копию
        значило бы завести второе место. Паритет же краснеет РОВНО когда род СМЕНИЛСЯ,
        а смена рода означает, что сменилось и лекарство (ADR-945).
        """
        live = {
            harm.key(row["module"], row["name"]): row["direction"]
            for row in harm.direction(
                [r for r in self.result["rows"] if r["subject"]]) ["rows"]
        }
        drifted = {
            f"{entry['module']}::{entry['name']}":
                f"объявлено {entry.get('направление')!r}, прибор отвечает "
                f"{live.get(harm.key(entry['module'], entry['name']))!r}"
            for entry in self.doc["harmful"]
            if entry.get("направление")
            != live.get(harm.key(entry["module"], entry["name"]))
        }
        self.assertEqual(
            drifted, {},
            "род вреда у записи РАСХОДИТСЯ с живым прибором — сменилась форма чтения, "
            f"а значит и лекарство: {drifted}")

    def test_the_direction_axis_has_all_four_outcomes_distinguishable(self):
        """Ось обязана уметь сказать «не измерено» — иначе её молчание неотличимо от
        «направления нет» (инв. #17). И обязана ответить о КАЖДОМ кандидате признака:
        ось, отвечающая о части, назвала бы долю от неизвестного знаменателя."""
        candidates = [
            row for row in self.result["rows"]
            if row["subject"]
            and self.production.get(harm.key(row["module"], row["name"])) == "produces"
        ]
        result = harm.direction(candidates)
        self.assertEqual(set(result["tally"]), set(harm.DIRECTION_OUTCOMES))
        self.assertEqual(sum(result["tally"].values()), len(candidates),
                         "ось обязана ответить о КАЖДОМ кандидате признака")
        self.assertGreater(result["tally"]["fewer"], 0,
                           "ось не нашла ни одной ТИХОЙ пустоты — это повод перемерить "
                           "прибор, а не вывод о дереве")

    def test_the_direction_scope_is_named_not_implied(self):
        """Область замера направления — ЧАСТЬ объявления, как и у мутационного замера:
        исходы из одной области читались бы как «во всём дереве столько»."""
        scope = self.doc["scope"].get("направление")
        self.assertIsInstance(scope, dict, "замер направления не объявлен вовсе")
        for field in ("прибор", "измерено_на_коммите", "измерено", "область",
                      "кандидатов", "исходы", "почему_НЕ_ИЗМЕРЕНО", "НЕ_ЗАКРЫТО"):
            self.assertIn(field, scope, f"замер направления без поля {field!r}")
        self.assertEqual(set(scope["исходы"]), set(harm.DIRECTION_OUTCOMES),
                         "объявленные исходы обязаны совпасть с перечнем прибора")
        self.assertTrue(str(scope["НЕ_ЗАКРЫТО"]).strip(),
                        "незакрытая часть замера обязана быть НАЗВАНА")

    def test_the_scope_of_the_measurement_is_named_not_implied(self):
        """Область замера — ЧАСТЬ объявления: `harmful` из одного пакета читалось бы
        как «во всём дереве столько», а это другое утверждение."""
        scope = self.doc["scope"]
        for field in ("пакет", "признак_отбора", "мутация", "прогон", "измерено", "НЕ_ЗАКРЫТО"):
            self.assertIn(field, scope, f"область замера без поля {field!r}")
        self.assertTrue(str(scope["НЕ_ЗАКРЫТО"]).strip(),
                        "незакрытая часть замера обязана быть НАЗВАНА, а не подразумеваться")


if __name__ == "__main__":
    unittest.main()
