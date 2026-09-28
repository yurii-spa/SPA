"""Контроль пробы `carried_release_is_one_condition` (ADR-501, `.claude/rules/acceptance.md` §3).

Проба меряет ИСХОД, поэтому и контроль её — по исходу: зелена на целом контуре и
**красна на КАЖДОМ порванном звене, с названным звеном**. Проба без такого контроля —
украшение: снявшая её мутация ничего не покрасит.

Отдельно проверяется, что проба **не проходит подстрокой** (ADR-333): вердикт —
значение, а не текст, в котором что-то нашлось.
"""
from __future__ import annotations

import unittest
from unittest import mock

from spa_core.monitoring.card_acceptance import PROBES

_PROBE = "carried_release_is_one_condition"


class ProbeIsGreenOnTheWholeContour(unittest.TestCase):
    def test_whole_contour_is_satisfied(self) -> None:
        verdict, why = PROBES[_PROBE](None)
        self.assertEqual(verdict, "satisfied", why)


class ProbeIsRedOnEachBrokenLink(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и проба обязана назвать именно его."""

    def test_two_copies_again_is_not_satisfied(self) -> None:
        """Сторож читает свою функцию — ровно тот дефект, ради которого писан ADR-501."""
        import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
        with mock.patch.object(ratchet, "carried_release", lambda *a, **k: (None, "своя копия")):
            verdict, why = PROBES[_PROBE](None)
        self.assertEqual(verdict, "not_satisfied")
        self.assertIn("НЕ ту функцию", why)

    def test_a_promised_path_that_frees_the_carrier_is_not_satisfied(self) -> None:
        """Опт-аут: любая строка `carried_to` гасит вопрос о критерии."""
        import spa_core.owner_queue.queue as q
        import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
        from pathlib import Path
        optout = lambda t, c=None, **k: ((Path(str(t)), "") if t else (None, "пусто"))  # noqa: E731
        with mock.patch.object(q, "carried_release", optout), \
             mock.patch.object(ratchet, "carried_release", optout):
            verdict, why = PROBES[_PROBE](None)
        self.assertEqual(verdict, "not_satisfied")
        self.assertIn("опт-аут", why)

    def test_a_refused_LEGITIMATE_carrier_is_not_satisfied(self) -> None:
        """Обратная сторона: условие строже правила — тоже дефект, а не строгость."""
        import spa_core.owner_queue.queue as q
        import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
        deny = lambda *a, **k: (None, "отказ всему")  # noqa: E731
        with mock.patch.object(q, "carried_release", deny), \
             mock.patch.object(ratchet, "carried_release", deny):
            verdict, why = PROBES[_PROBE](None)
        self.assertEqual(verdict, "not_satisfied")
        self.assertIn("НЕ освобождён", why)

    def test_a_missing_condition_is_UNMEASURED_not_clean(self) -> None:
        """Третий исход: прибора нет ⇒ про предмет не измерено НИЧЕГО (инв. #17)."""
        import builtins
        real = builtins.__import__

        def _boom(name, *a, **k):
            if name == "spa_core.owner_queue.queue":
                raise ImportError("условия нет")
            return real(name, *a, **k)

        with mock.patch.object(builtins, "__import__", _boom):
            verdict, why = PROBES[_PROBE](None)
        self.assertEqual(verdict, "unmeasured", why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)


class ProbeDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: вердикт — значение, а не текст, в котором нашлась подстрока."""

    def test_the_word_satisfied_inside_a_reason_is_not_a_verdict(self) -> None:
        verdict, why = PROBES[_PROBE](None)
        self.assertIn(verdict, {"satisfied", "not_satisfied", "unmeasured"})
        self.assertNotEqual(verdict, why, "вердикт и причина слиты — исход читался бы текстом")

    def test_not_satisfied_is_not_read_as_satisfied(self) -> None:
        """`'satisfied' in 'not_satisfied'` истинно — сравнение обязано быть по значению."""
        import spa_core.owner_queue.queue as q
        import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
        deny = lambda *a, **k: (None, "отказ всему")  # noqa: E731
        with mock.patch.object(q, "carried_release", deny), \
             mock.patch.object(ratchet, "carried_release", deny):
            verdict, _ = PROBES[_PROBE](None)
        self.assertNotEqual(verdict, "satisfied")
        self.assertTrue(verdict.startswith("not_"))


if __name__ == "__main__":
    unittest.main()
