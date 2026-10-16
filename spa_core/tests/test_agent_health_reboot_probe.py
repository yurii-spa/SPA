"""Положительные контроли исходной пробы `agent_health_reboot_false_alarm_closed`
(карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`, ADR-208).

Проба без контроля в обе стороны — украшение (`.claude/rules/deployment.md`): здесь
показано, что на починенном коде она зелёная, а на КАЖДОМ порванном звене — красная
с названным звеном, и что подстрокой она не проходит (ADR-333).

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW передаётся в пробу параметром now=, момент
# загрузки, квитанции и mtime журналов сцены выводятся из него же внутри пробы.
"""
from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest import mock

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import card_acceptance as ca

NAME = "agent_health_reboot_false_alarm_closed"
NOW = dt.datetime(2026, 10, 15, 21, 21, 20, tzinfo=dt.timezone.utc)
DATA = os.path.join(ca.REPO_ROOT, "data")


def _run():
    return ca._probe_agent_health_reboot_false_alarm(None, now=NOW)


class Registered(unittest.TestCase):
    def test_probe_is_in_the_registry_and_validates(self):
        self.assertIn(NAME, ca.PROBES)
        self.assertIsNone(ca.validate_spec(NAME))


class ShippedCode(unittest.TestCase):
    def test_green_on_the_fixed_code(self):
        before = sorted(os.listdir(DATA)) if os.path.isdir(DATA) else []
        verdict, detail = _run()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn(ca.REBOOT_PROBE_RECEIPT_AGENT + "=receipt", detail)
        # Живое data/ не тронуто: дерево пробы одноразовое.
        self.assertEqual(before, sorted(os.listdir(DATA)) if os.path.isdir(DATA) else [])

    def test_through_the_registry_dispatch(self):
        verdict, _ = ca.run_probe(NAME)
        self.assertEqual(verdict, ca.SATISFIED)


class BrokenLinks(unittest.TestCase):
    """Каждое звено порвано по отдельности — проба обязана назвать именно его."""

    def test_receipt_ignored_is_named(self):
        none = lambda *a, **k: ahm.ReceiptReading(ahm.RECEIPT_NONE, None, "")  # noqa: E731
        with mock.patch.object(ahm, "read_success_receipt", none):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("квитанция", detail)

    def test_reboot_window_removed_is_named(self):
        with mock.patch.object(ahm, "first_run_window_min", lambda plist, thr: -1.0):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("окно после загрузки", detail)

    def test_missed_run_masked_is_named(self):
        with mock.patch.object(ahm, "first_run_window_min", lambda plist, thr: 1e9):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("пропуск", detail)

    def test_warning_churn_resending_is_named(self):
        """Отпечаток прежней формы (все предупреждения в нём) — повтор той же тревоги."""
        with mock.patch.object(ahm, "alert_fingerprint",
                               lambda r: "|".join(sorted(ahm._stable_issue_keys(r))) or None):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("повтор", detail)

    def test_running_without_result_accepted_is_named(self):
        real = ahm._judge_by_receipt

        def lenient(health, issues, receipt, log_age, threshold, window, since_boot):
            if health.pid:  # живой PID принят за успех — прежняя ошибка класса
                health.evidence = ahm.EVIDENCE_RECEIPT
                return
            real(health, issues, receipt, log_age, threshold, window, since_boot)

        with mock.patch.object(ahm, "_judge_by_receipt", lenient):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("процесс без результата", detail)

    def test_issue_text_without_status_is_not_satisfied(self):
        """ADR-333: слова «no successful result» в issue при статусе OK — не CRITICAL.
        Проба сравнивает ПОЛЕ status, а не текст."""
        real = ahm._judge_by_receipt

        def text_only(health, issues, receipt, log_age, threshold, window, since_boot):
            before = health.status
            real(health, issues, receipt, log_age, threshold, window, since_boot)
            health.status = before  # текст остался, статус — нет

        with mock.patch.object(ahm, "_judge_by_receipt", text_only):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("пропуск", detail)


class ThirdOutcome(unittest.TestCase):
    def test_probe_crash_is_unmeasured_never_a_verdict(self):
        def boom(*a, **k):
            raise RuntimeError("пульс недоступен")
        with mock.patch.object(ahm, "check_agent", boom):
            verdict, detail = ca.run_probe(NAME)
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertTrue(detail)

    def test_host_log_collision_is_unmeasured(self):
        real_exists = os.path.exists
        target = f"/tmp/spa_{ca.REBOOT_PROBE_RECEIPT_AGENT[len('com.spa.'):]}.log"
        with mock.patch.object(ca.os.path, "exists",
                               lambda p: True if p == target else real_exists(p)):
            verdict, detail = _run()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("НЕ ОБЕСПЕЧЕНА", detail)


if __name__ == "__main__":
    unittest.main()
