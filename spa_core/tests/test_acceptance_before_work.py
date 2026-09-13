"""Положительные контроли правила приёмки (`.claude/rules/acceptance.md`, п. 1–2):
inbox-карточка уходит из приёма только с машинным критерием, и проба карточки в работе
не заменяется. Каждый тест — способ, которым очередь могла бы пропустить самосертификацию.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.owner_queue import queue as q

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLI = os.path.join(_REPO, "scripts", "orchestrator_queue.py")


def _card(tmp, name, *, kind="inbox", status="new", probe=None, finding_key=None):
    fm = ["trackerStatus:", f"  type: {kind}", f'title: "проверочная {name}"', f"status: {status}"]
    if probe:
        fm.append(f"acceptance_probe: {probe}")
    if finding_key:
        fm.append(f'finding_key: "{finding_key}"')
    path = os.path.join(tmp, f"{name}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(fm) + "\n---\n\n## тело\n")
    return path


class TakingIntoWork(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def test_inbox_without_criterion_is_refused(self):
        path = _card(self.tmp, "inbox-bez-kriteriya")
        with self.assertRaises(q.AcceptanceCriterionMissing) as cm:
            q.set_status(path, "in-progress")
        self.assertIn("orchestrator_queue.py probe", str(cm.exception))
        self.assertIn("status: new", open(path, encoding="utf-8").read())   # карточка не тронута

    def test_inbox_with_probe_goes_into_work(self):
        path = _card(self.tmp, "inbox-s-proboi", probe="tier_promotion_loop_closed")
        q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_bridge_card_with_finding_key_goes_into_work(self):
        path = _card(self.tmp, "inbox-ot-mosta", finding_key="tier_promote:x")
        q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_intake_moves_are_free(self):
        path = _card(self.tmp, "inbox-v-bekloge")
        q.set_status(path, "backlog")
        q.set_status(path, "new")

    def test_closing_without_criterion_is_refused_too(self):
        # `new -> done` в обход работы — та же самосертификация.
        path = _card(self.tmp, "inbox-srazu-done")
        with self.assertRaises(q.AcceptanceCriterionMissing):
            q.set_status(path, "done")

    def test_baseline_card_is_exempt(self):
        path = _card(self.tmp, "inbox-staraya")
        with mock.patch.object(q, "_inbox_acceptance_baseline", lambda: {"inbox-staraya.md"}):
            q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_non_inbox_types_are_not_the_subject(self):
        path = _card(self.tmp, "agent-zadacha", kind="agent-task")
        q.set_status(path, "in-progress")

    def test_unreadable_baseline_is_loud_not_a_silent_refusal(self):
        path = _card(self.tmp, "inbox-baza-propala")
        import io
        err = io.StringIO()
        with mock.patch.object(q, "_inbox_acceptance_baseline", lambda: None), \
                mock.patch("sys.stderr", err):
            q.set_status(path, "in-progress")
        self.assertIn("НЕ ИЗМЕРЕНО", err.getvalue())

    def test_cli_refuses_with_exit_2(self):
        path = _card(self.tmp, "inbox-cli")
        r = subprocess.run([sys.executable, _CLI, "set-status", path, "in-progress"],
                           capture_output=True, text=True, timeout=120, cwd=_REPO)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)
        self.assertIn("status: new", open(path, encoding="utf-8").read())


class ProbeIsFrozenInWork(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def test_changing_the_probe_of_a_card_in_work_is_refused(self):
        path = _card(self.tmp, "inbox-v-rabote", status="in-progress", probe="tier_promotion_loop_closed")
        with self.assertRaises(q.AcceptanceCriterionLocked):
            q.set_acceptance_probe(path, "lead_channel_wiring_ok")
        self.assertIn("acceptance_probe: tier_promotion_loop_closed", open(path, encoding="utf-8").read())

    def test_same_probe_restated_is_not_a_change(self):
        path = _card(self.tmp, "inbox-ta-zhe", status="in-progress", probe="tier_promotion_loop_closed")
        q.set_acceptance_probe(path, "tier_promotion_loop_closed")

    def test_adding_a_probe_to_a_baseline_card_in_work_is_allowed(self):
        path = _card(self.tmp, "inbox-bez-proby-v-rabote", status="in-progress")
        q.set_acceptance_probe(path, "tier_promotion_loop_closed")
        self.assertIn("acceptance_probe: tier_promotion_loop_closed", open(path, encoding="utf-8").read())

    def test_probe_of_a_card_in_intake_may_change(self):
        path = _card(self.tmp, "inbox-eshche-nichya", probe="tier_promotion_loop_closed")
        q.set_acceptance_probe(path, "lead_channel_wiring_ok")

    def test_cli_refuses_with_exit_2(self):
        path = _card(self.tmp, "inbox-cli-lock", status="blocked", probe="tier_promotion_loop_closed")
        r = subprocess.run([sys.executable, _CLI, "probe", path, "lead_channel_wiring_ok"],
                           capture_output=True, text=True, timeout=120, cwd=_REPO)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)


if __name__ == "__main__":
    unittest.main()


class ACarrierIsRetiredNotTakenIntoWork(unittest.TestCase):
    """ADR-375: приём гасит НОСИТЕЛЬ, назвав предмет, куда уехало содержимое.

    Правило машинной приёмки написано про «карточку БЕРУТ В РАБОТУ без мерки». Приём
    заданий делает другое: идея уезжает в заметку, вопрос — в карточку владельцу, а
    сама inbox-карточка гасится как отработавший носитель. Требовать у носителя пробу
    не к чему: его приёмка ровно одна — содержимое теперь лежит ВОТ ЗДЕСЬ.

    **Освобождение обязано быть ЗАРАБОТАННЫМ, а не флагом-доверием.** Первая редакция
    приняла бы `carried_to` по имени, без проверки, — и мутация, снявшая проверку
    существования, ничего не покрасила: то есть отличить заработанное освобождение от
    опт-аута было нечем. Эти два теста и есть та разница.
    """

    def _card(self, tmp: Path) -> Path:
        p = tmp / "inbox-nositel.md"
        p.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: \"н\"\nstatus: new\n---\n\nтекст\n",
                     encoding="utf-8")
        return p

    def test_a_named_but_MISSING_target_does_not_free_the_carrier(self):
        """Имя без файла — обещание, а не приёмка."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, AcceptanceCriterionMissing
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            with self.assertRaises(AcceptanceCriterionMissing) as ctx:
                set_status(card, "done", carried_to=Path(tmp) / "ничего-нет.md")
            self.assertIn("carried_to", str(ctx.exception))

    def test_an_existing_target_frees_the_carrier(self):
        """Обратная сторона: предмет существует — носитель гасится."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, load_card
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            target = Path(tmp) / "docs-ideas-zametka.md"
            target.write_text("# идея\n", encoding="utf-8")
            set_status(card, "done", carried_to=target)
            self.assertEqual(load_card(card).status, "done")

    def test_without_carried_to_the_rule_still_refuses(self):
        """Контроль на сам механизм: без носителя правило обязано работать как прежде."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, AcceptanceCriterionMissing
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            with self.assertRaises(AcceptanceCriterionMissing):
                set_status(card, "done")
