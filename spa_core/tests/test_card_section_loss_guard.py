# -*- coding: utf-8 -*-
"""Сторож потери РАЗДЕЛОВ карточки у двери доставки (цикл #874, ADR-729).

Каждый тест — реальное состояние, а не выдумка:

* `2427751a6` (07.10) — потеря разделов с ШЕСТИ карточек владельца, из них
  `…-petli-com-spa-tier1-2`: 114 строк → 39, прежняя мера (записи цикла) молчит;
* `### Что осталось по ТЗ (обновлено этим циклом)` → `(обновлено циклом #820)` —
  форма, встреченная в истории 7 раз (5 из них на стоячем приказе владельца):
  карточка при этом РАСТЁТ, и отказ здесь означал бы `--allow-overwrite` каждый
  цикл, то есть лазейку под рукой;
* `_BOARD.md` — производный индекс со ЖИВЫМ счётчиком в заголовке
  (`(726)` → `(727)`): 52 ноты и ноль отказов на 118 парах истории.

Времени в тестах нет; живое дерево не трогается (байты берутся из фикстур).
"""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FIX = _ROOT / "spa_core" / "tests" / "fixtures" / "card_section_loss"
CARD = ("nimbalyst-local/tracker/"
        "owner-decision-kritichnaya-nahodka-petli-com-spa-tier1-2.md")
SHA = "2427751a6" + "0" * 31


def _pusher():
    spec = importlib.util.spec_from_file_location("_pusher_c874_guard",
                                                  _ROOT / "push_to_github.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RealLossIsRefused(unittest.TestCase):

    def setUp(self):
        self.p = _pusher()
        self.before = (_FIX / "owner_2427751a6_before.md").read_bytes()
        self.after = (_FIX / "owner_2427751a6_after.md").read_bytes()

    def test_the_pair_really_shrinks_the_card(self):
        """Предпосылка батареи ИЗМЕРЕНА, а не объявлена."""
        delta = self.after.count(b"\n") - self.before.count(b"\n")
        self.assertEqual(delta, -75)

    def test_the_old_measure_is_silent_on_this_pair(self):
        """Иначе батарея мерила бы сторожа #858, а не новый класс."""
        self.assertEqual(
            self.p.guard_cycle_record_loss(CARD, self.before, self.after, SHA), "")

    def test_the_door_refuses(self):
        with self.assertRaises(self.p.CardSectionLossRefused) as ctx:
            self.p.guard_content_loss(CARD, self.before, self.after, SHA)
        text = str(ctx.exception)
        self.assertIn("#466", text, "отказ обязан НАЗВАТЬ пропавшие разделы")
        self.assertIn("-75", text, "отказ обязан назвать усадку — вторую улику")

    def test_refusal_is_a_divergence_refusal(self):
        """Дверь ловит общий класс отказов, а не каждый по имени."""
        self.assertTrue(issubclass(self.p.CardSectionLossRefused,
                                   self.p.DivergenceRefused))

    def test_allow_overwrite_is_the_conscious_override(self):
        self.assertEqual(
            self.p.guard_card_section_loss(CARD, self.before, self.after, SHA,
                                           allow_overwrite=True), "")


class WhatMustNotRefuse(unittest.TestCase):

    def setUp(self):
        self.p = _pusher()
        self.before = (_FIX / "owner_2427751a6_before.md").read_bytes()

    def test_pure_append_is_silent(self):
        grown = self.before + "\n## Дописанный раздел\n\nтело\n".encode("utf-8")
        self.assertEqual(self.p.guard_content_loss(CARD, self.before, grown, SHA), "")

    def test_rewritten_heading_on_a_grown_card_is_named_not_refused(self):
        head = "## Исполнено (интерактивная сессия, 2026-09-03T13:41Z)".encode("utf-8")
        self.assertIn(head, self.before)
        grown = (self.before.replace(
            head, head + " (обновлено циклом #874)".encode("utf-8")
            + "\n\nпереписанное тело\n".encode("utf-8"), 1)
            + ("дописанное тело\n" * 30).encode("utf-8"))
        note = self.p.guard_card_section_loss(CARD, self.before, grown, SHA)
        self.assertTrue(note.strip(), "исход обязан быть НАЗВАН (инв. #17)")
        self.assertIn("ВЫРОС", note)

    def test_byte_identical_rename_is_named_as_rename(self):
        head = "## Исполнено (интерактивная сессия, 2026-09-03T13:41Z)".encode("utf-8")
        renamed = self.before.replace(head, "## Исполнено".encode("utf-8"), 1)
        note = self.p.guard_card_section_loss(CARD, self.before, renamed, SHA)
        self.assertIn("переименован", note)

    def test_generated_board_is_out_of_the_class(self):
        after = (_FIX / "owner_2427751a6_after.md").read_bytes()
        board = "nimbalyst-local/tracker/_BOARD.md"
        self.assertEqual(self.p.guard_content_loss(board, self.before, after, SHA), "")

    def test_a_non_card_path_is_out_of_the_class(self):
        after = (_FIX / "owner_2427751a6_after.md").read_bytes()
        self.assertEqual(
            self.p.guard_card_section_loss("docs/STATE.md", self.before, after, SHA), "")

    def test_a_file_absent_on_remote_has_nothing_to_lose(self):
        after = (_FIX / "owner_2427751a6_after.md").read_bytes()
        self.assertEqual(
            self.p.guard_card_section_loss(CARD, None, after, None), "")


class ThirdOutcome(unittest.TestCase):
    """«Не измерено» отличимо и от «чисто», и от «потеря» (инв. #17)."""

    def setUp(self):
        self.p = _pusher()
        self.after = (_FIX / "owner_2427751a6_after.md").read_bytes()

    def test_unread_remote_is_named_not_silent(self):
        note = self.p.guard_card_section_loss(CARD, None, self.after, SHA)
        self.assertIn("НЕ ИЗМЕРЕНА", note)
        self.assertIn("не «чисто»", note)

    def test_unread_remote_does_not_refuse_every_card(self):
        """Отказ по этой ветке остановил бы доставку ЛЮБОЙ карточки, ничего не измерив.

        Граница названа вслух: тетради при том же чтении по-прежнему защищает
        `guard_cycle_record_loss` (он отказывает, когда НАША копия доказывает
        тетрадь), поэтому здесь нота, а не отказ.
        """
        try:
            self.p.guard_card_section_loss(CARD, None, self.after, SHA)
        except Exception as exc:        # noqa: BLE001
            self.fail(f"ветка «remote не прочитан» отказала: {exc}")


if __name__ == "__main__":
    unittest.main()
