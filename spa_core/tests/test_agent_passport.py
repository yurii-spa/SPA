"""Агент без паспорта — не элемент системы, а демонстрация (ADR-154).

Рамка из книги «Бизнес, понятный машинам» (гл. 03, 26): агент — это должность, разобранная
до исполнимой функции. У неё есть цель, права, формат результата, критерии качества и
условия передачи человеку. «Если роль не получает понятный вход или её результат никто не
использует, это не элемент системы, а отдельная демонстрация.»

Замер 27.08 по `architecture/manifest.json`: из 95 агентов полный паспорт у **24**,
частичный у 47, отсутствует у 24. Три четверти флота описаны не до конца — и понять, кто из
них в потоке ценности, нельзя. Отдельно: 88 скриптов с точкой входа не вызывает никто.

Ключевое требование к отказу: он обязан НАЗЫВАТЬ недостающие поля. «Нет паспорта» — диагноз
без лечения; такой отказ обходят, а не исполняют.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring.agent_passport import (
    FULL, MISSING, PARTIAL, REQUIRED_FIELDS, audit, missing_fields, passport_state,
)


def _agent(**passport) -> dict:
    return {"label": "com.spa.x", "passport": passport}


_ALL = {k: "заполнено" for k in REQUIRED_FIELDS}


class TestThreeStates(unittest.TestCase):
    """Три состояния, а не два (инвариант #17)."""

    def test_full_passport(self):
        self.assertEqual(passport_state(_agent(**_ALL)), FULL)

    def test_no_passport_at_all(self):
        self.assertEqual(passport_state({"label": "x"}), MISSING)

    def test_partial_is_its_own_state_not_missing(self):
        """Начатая и брошенная работа обязана быть видна отдельно.

        Иначе 47 частичных паспортов вечно будут считаться либо готовыми, либо
        несуществующими — и прогресс по ним не измерить.
        """
        a = _agent(goal="цель", rights="права")
        self.assertEqual(passport_state(a), PARTIAL)
        self.assertNotEqual(passport_state(a), MISSING)

    def test_blank_strings_do_not_count_as_filled(self):
        """Пустая строка — это незаполненное поле, а не заполненное пустотой."""
        a = _agent(**{**_ALL, "goal": "   "})
        self.assertEqual(passport_state(a), PARTIAL)

    def test_a_non_dict_passport_is_missing_not_a_crash(self):
        self.assertEqual(passport_state({"label": "x", "passport": "текст"}), MISSING)


class TestRefusalIsActionable(unittest.TestCase):
    """Отказ обязан говорить, ЧТО чинить."""

    def test_missing_fields_are_named(self):
        got = missing_fields(_agent(goal="цель"))
        self.assertIn("rights", got)
        self.assertIn("limits", got)
        self.assertNotIn("goal", got)

    def test_a_complete_passport_names_nothing(self):
        self.assertEqual(missing_fields(_agent(**_ALL)), [])


class TestAudit(unittest.TestCase):
    """Сводка — числами, иначе прогресс не измерить."""

    def test_counts_split_by_state(self):
        r = audit([_agent(**_ALL), _agent(goal="ц"), {"label": "z"}])
        self.assertEqual((r["full"], r["partial"], r["missing"]), (1, 1, 1))
        self.assertEqual(r["total"], 3)

    def test_labels_are_returned_for_follow_up(self):
        """Без имён сводка бесполезна: чинить придётся вслепую."""
        r = audit([{"label": "com.spa.a"}])
        self.assertIn("com.spa.a", r["labels"][MISSING])

    def test_the_real_manifest_is_measured_not_assumed(self):
        """Положительный контроль на живом манифесте: числа берутся из файла."""
        r = audit()
        self.assertGreater(r["total"], 50, "манифест обязан читаться")
        self.assertEqual(r["full"] + r["partial"] + r["missing"], r["total"],
                         "каждый агент обязан попасть ровно в одно состояние")


if __name__ == "__main__":
    unittest.main()
