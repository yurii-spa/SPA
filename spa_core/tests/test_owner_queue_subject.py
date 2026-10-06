"""`spa_core.owner_queue.subject` — ОДНА общая тема ADR-285 (C5, ADR-580).

Замер A5_owner_control.md (2026-10-05): Mission Control и Director угадывали тему
каждый своим словарём ключевых слов и расходились на тех же карточках — «Закрыть три
PR» получала «1 · real money» у Mission Control (слово «ключ» в тексте), Director
звал её дефектом очереди. Этот модуль заменяет оба угадывателя: тема — объявленное
поле `subject:`, а не слова тела.
"""
from __future__ import annotations

import unittest

from spa_core.owner_queue import subject as s


class TestSubjectOf(unittest.TestCase):

    def test_declared_money_is_read(self):
        self.assertEqual(s.subject_of({"subject": "money"}), s.MONEY)
        self.assertEqual(s.subject_of({"subject": "1"}), s.MONEY)

    def test_declared_public_numbers(self):
        self.assertEqual(s.subject_of({"subject": "public_numbers_naming_legal"}),
                         s.PUBLIC_NUMBERS_NAMING_LEGAL)
        self.assertEqual(s.subject_of({"subject": "legal"}), s.PUBLIC_NUMBERS_NAMING_LEGAL)

    def test_declared_irreversible_and_physical(self):
        self.assertEqual(s.subject_of({"subject": "irreversible"}), s.IRREVERSIBLE)
        self.assertEqual(s.subject_of({"subject": "physical"}), s.PHYSICAL_ACTION)

    def test_missing_field_is_unknown_not_guessed(self):
        """Регрессия: прежний Mission Control давал «1 · real money» карточке «Закрыть
        три PR» ровно потому, что в тексте встречается слово «ключ». Без объявленного
        поля `subject` новая функция НИКОГДА не смотрит на title/body."""
        fm = {"title": "Закрыть три PR", "body": "у PAT не хватает прав (ключ)"}
        self.assertEqual(s.subject_of(fm), s.UNKNOWN)

    def test_blank_and_unrecognized_values_are_unknown(self):
        self.assertEqual(s.subject_of({"subject": ""}), s.UNKNOWN)
        self.assertEqual(s.subject_of({"subject": "кто-знает-что"}), s.UNKNOWN)
        self.assertEqual(s.subject_of({}), s.UNKNOWN)
        self.assertEqual(s.subject_of(None), s.UNKNOWN)

    def test_quoted_frontmatter_value_is_unquoted(self):
        self.assertEqual(s.subject_of({"subject": '"money"'}), s.MONEY)


class TestMissionControlLabel(unittest.TestCase):

    def test_known_subjects_render_with_their_number(self):
        self.assertEqual(s.mission_control_label({"subject": "money"}), "1 · real money")
        self.assertEqual(s.mission_control_label({"subject": "irreversible"}),
                         "3 · irreversible / external")

    def test_undeclared_renders_as_UNKNOWN_literal(self):
        self.assertEqual(s.mission_control_label({"title": "ключ"}), "UNKNOWN")


class TestDirectorSubject(unittest.TestCase):

    def test_declared_subject_maps_to_directors_numeric_code(self):
        code, basis, why = s.director_subject({"subject": "money"})
        self.assertEqual(code, "1")
        self.assertEqual(basis, "DECLARED")
        self.assertIn("subject", why)

    def test_physical_action_folds_into_directors_code_3(self):
        code, _, _ = s.director_subject({"subject": "physical"})
        self.assertEqual(code, "3")

    def test_missing_subject_is_UNDECLARED_with_NOT_DECLARED_basis(self):
        """Director раньше ставил basis='HEURISTIC' даже когда угадать не удавалось.
        Теперь отсутствие объявления само по себе названо — это НЕ угадано, а отсутствует.

        # CHANGED (integration review F2, 2026-10-05 — journal 2026-W40): code was
        # asserted as "NONE". That collided with the OTHER "NONE" Director already
        # uses (heuristic sources answering "no subject matched" -> CLASS_SYSTEM,
        # work for the agent), so classify_item folded EVERY undeclared owner card
        # into "work for the agent" and hid them from "ждёт вашего решения" (prod
        # tracker measurement: 2 -> 0). The code is now the distinct "UNDECLARED",
        # which classify_item routes to CLASS_UNKNOWN (visible to the owner). This is
        # a tightening to the fixed behaviour, not a relaxation.
        """
        code, basis, why = s.director_subject({"title": "что угодно"})
        self.assertEqual(code, "UNDECLARED")
        self.assertEqual(basis, "NOT_DECLARED")
        self.assertIn("не объявила", why)


if __name__ == "__main__":
    unittest.main()
