"""Положительные контроли исходной пробы `cockpit_voice_loop_closed` (ADR-763, карточка
`inbox-skvoznoi-put-iz-pulta-golos-kartochka-is`).

По образцу `test_tier_loop_probe.py`: на целом контуре проба зелёная, на КАЖДОМ порванном звене —
красная с названным звеном, подстрокой не проходит (ADR-333), живой трекер/исходящие не трогает.
Звенья, которые рвутся по отдельности (заказ ARB 16.10):

  * нет идемпотентности отправки пульта;
  * приём теряет уведомление;
  * карточку берут в работу без пробы;
  * «сделано» до того, как проба подтвердила результат;
  * второе исполнение при повторной доставке;
  * ошибка без причины / без следующего шага;
  * плюс: модуля закрытия нет вовсе (состояние `origin/main` до этой правки) и третий исход.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import hashlib
import os
import sys
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import intake as oi
from spa_core.owner_queue import queue as q
from spa_core.studio_os import mission_intake as mi
from spa_core.studio_os import owner_view as ov

NAME = "cockpit_voice_loop_closed"
TRACKER = os.path.join(ca.REPO_ROOT, "nimbalyst-local", "tracker")
OUTBOX = os.path.join(ca.REPO_ROOT, "data", "intake_outbox.json")


def _digest(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def _probe():
    return ca._probe_cockpit_voice_loop(None)


class Registered(unittest.TestCase):
    def test_probe_is_in_the_registry_and_validates(self):
        self.assertIn(NAME, ca.PROBES)
        self.assertIsNone(ca.validate_spec(NAME))


class ShippedTree(unittest.TestCase):
    def test_loop_is_closed_on_the_shipped_code(self):
        before_cards = sorted(os.listdir(TRACKER)) if os.path.isdir(TRACKER) else []
        before_outbox = _digest(OUTBOX)
        verdict, detail = _probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        # Живой трекер и живые исходящие не тронуты: сцена одноразовая.
        self.assertEqual(before_cards, sorted(os.listdir(TRACKER)) if os.path.isdir(TRACKER) else [])
        self.assertEqual(before_outbox, _digest(OUTBOX))

    def test_through_the_registry_dispatch(self):
        verdict, detail = ca.run_probe(NAME)
        self.assertEqual(verdict, ca.SATISFIED, detail)


class BrokenLinks(unittest.TestCase):
    """Каждое звено порвано по отдельности — проба обязана назвать именно его."""

    def _red(self, needle):
        verdict, detail = _probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(needle, detail)
        return detail

    def test_no_submission_idempotency(self):
        with mock.patch.object(mi, "find_submission", lambda *a, **k: None):
            self._red("звено 1")

    def test_intake_loses_the_notice(self):
        with mock.patch.object(oi, "_outbox_put", lambda *a, **k: None):
            self._red("звено 2")

    def test_card_taken_without_a_probe(self):
        with mock.patch.object(q, "has_acceptance_criterion", lambda fm: True):
            self._red("БЕЗ пробы")

    def test_done_before_the_probe_is_satisfied(self):
        with mock.patch.object(cl, "_accepts", lambda verdict: True):
            self._red("звено 4")

    @staticmethod
    def _leaky_claim():
        real = cl._claim

        def leaky(path, executor, claim):
            try:
                real(path, executor, claim)
            except cl.TakeRefused:
                pass                     # захват, который НЕ исключает другого исполнителя
        return leaky

    def test_second_execution_on_duplicate_delivery(self):
        """Оба слоя порваны: проверка статуса/захвата в карточке И исключающий захват шага 0b."""
        with mock.patch.object(cl, "_exclusive", lambda *a, **k: "take"), \
                mock.patch.object(cl, "_claim", self._leaky_claim()):
            self._red("второе исполнение")

    def test_redelivery_to_the_same_executor_is_a_noop_not_a_rerun(self):
        """Без проверки статуса в карточке захват того же исполнителя проходит (это его захват) —
        и повторная доставка запускает исполнение заново. Проба обязана это назвать."""
        with mock.patch.object(cl, "_exclusive", lambda *a, **k: "take"):
            detail = self._red("второе исполнение")
        self.assertIn("executor-a", detail)

    def test_a_leaky_claim_alone_is_still_caught_by_the_card_check(self):
        """Захват, не исключающий другого, сам по себе второго исполнения не открывает: карточка в
        работе у другого исполнителя отказывает по статусу (второй слой)."""
        with mock.patch.object(cl, "_claim", self._leaky_claim()):
            self.assertEqual(_probe()[0], ca.SATISFIED)

    def test_error_without_reason_or_next_step(self):
        blank = {k: ("", "") for k in ov._NOT_ACCEPTED_DEFAULT}
        blank_cl = {k: ("", "") for k in cl.REASON_RU}
        with mock.patch.dict(ov._NOT_ACCEPTED_DEFAULT, blank), mock.patch.dict(cl.REASON_RU, blank_cl):
            self._red("без причины")

    def test_reason_present_but_next_step_dropped(self):
        with mock.patch.dict(ov._NOT_ACCEPTED_DEFAULT,
                             {k: (v[0], "") for k, v in ov._NOT_ACCEPTED_DEFAULT.items()}), \
                mock.patch.dict(cl.REASON_RU, {k: (v[0], "") for k, v in cl.REASON_RU.items()}):
            self._red("следующего шага")

    def test_not_accepted_notice_on_every_remeasure_is_spam(self):
        real = cl._record_not_accepted

        def spam(path, kind, detail, now, outbox_path, next_step=None):
            real(path, kind, detail, now, outbox_path, next_step)
            oi._outbox_put(f"{path.name}#spam{now.timestamp()}", "спам", now, outbox_path)
            return True
        with mock.patch.object(cl, "_record_not_accepted", spam):
            self._red("вместо одного")

    def test_done_notice_duplicated_by_sweep(self):
        real = cl._ensure_done_notice

        def always(path, now, outbox_path):
            real(path, now, outbox_path)
            oi._outbox_put(f"{path.name}#again{now.timestamp()}", "сделано ещё раз", now, outbox_path)
            return True
        with mock.patch.object(cl, "_ensure_done_notice", always):
            self._red("звено 5")

    def test_name_in_prose_is_not_the_structured_row(self):
        """ADR-333: «Мои записи» с правильными словами, но без структурного исхода — красно."""
        real = ov._record_outcome

        def prose_only(r):
            o = real(r)
            o["kind"] = "unknown"
            return o
        with mock.patch.object(ov, "_record_outcome", prose_only):
            self._red("Мои записи")


class OriginControl(unittest.TestCase):
    def test_without_the_closing_module_the_loop_is_not_closed(self):
        """Состояние `origin/main` до этой правки: двери закрытия пробой нет — красно, звено названо."""
        import spa_core.owner_queue as pkg
        saved = pkg.cockpit_loop
        del pkg.cockpit_loop
        try:
            with mock.patch.dict(sys.modules, {"spa_core.owner_queue.cockpit_loop": None}):
                verdict, detail = _probe()
        finally:
            pkg.cockpit_loop = saved
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("не построено", detail)


class ThirdOutcome(unittest.TestCase):
    def test_claim_guard_unloadable_is_unmeasured(self):
        with mock.patch.object(ca, "REPO_ROOT", "/nonexistent-spa-root"):
            verdict, detail = _probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", detail)

    def test_scene_crash_is_unmeasured_never_a_verdict(self):
        def boom(*a, **k):
            raise RuntimeError("приём недоступен")
        with mock.patch.object(oi, "run_note_intake", boom):
            verdict, detail = _probe()
        self.assertEqual(verdict, ca.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
