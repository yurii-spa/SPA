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

    def test_named_exemption_is_stamped_into_the_card_and_lets_it_move(self):
        """Маршрутизатор приёма (#55): освобождение НАЗВАНО и видно в самой карточке."""
        path = _card(self.tmp, "inbox-golosovoe-zadanie")
        q.set_status(path, "in-progress", acceptance_exempt="intake route: task")
        text = open(path, encoding="utf-8").read()
        self.assertIn("status: in-progress", text)
        self.assertIn('acceptance_exempt: "intake route: task"', text)

    def test_empty_exemption_is_not_an_exemption(self):
        path = _card(self.tmp, "inbox-pustaya-prichina")
        with self.assertRaises(q.AcceptanceCriterionMissing):
            q.set_status(path, "in-progress", acceptance_exempt="   ")

    def test_ingested_is_intake_not_work(self):
        path = _card(self.tmp, "inbox-otvet-prinyat")
        q.set_status(path, "ingested")

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
