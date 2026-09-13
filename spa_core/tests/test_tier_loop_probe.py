"""Положительные контроли исходной пробы `tier_promotion_loop_closed` (ADR-208, карточка
`inbox-mashinnaya-priemka-obyazatelna-ishodnaya`).

Проба без контроля в обе стороны — украшение (`.claude/rules/deployment.md`): здесь
показано, что на целом дереве она зелёная, а на КАЖДОМ порванном звене — красная с
названным звеном, и что подстрокой она не проходит (ADR-333).

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW передаётся в пробу параметром now=, все отметки
# отчёта куратора выводятся из него же внутри пробы.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import findings_bridge as fb

NOW = dt.datetime(2026, 9, 13, 8, 0, tzinfo=dt.timezone.utc)
KEY = f"tier_promote:{ca.TIER_PROBE_PROTO}"
TRACKER = os.path.join(ca.REPO_ROOT, "nimbalyst-local", "tracker")
STATE = os.path.join(ca.REPO_ROOT, fb.STATE_REL)


def _digest(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


class Registered(unittest.TestCase):
    def test_probe_is_in_the_registry_and_validates(self):
        self.assertIn("tier_promotion_loop_closed", ca.PROBES)
        self.assertIsNone(ca.validate_spec("tier_promotion_loop_closed"))


class ShippedTree(unittest.TestCase):
    def test_loop_is_closed_on_the_shipped_code(self):
        before_cards = sorted(os.listdir(TRACKER)) if os.path.isdir(TRACKER) else []
        before_state = _digest(STATE)
        verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn(KEY, detail)
        # Живой трекер и живое состояние моста не тронуты: дерево пробы одноразовое.
        after_cards = sorted(os.listdir(TRACKER)) if os.path.isdir(TRACKER) else []
        self.assertEqual(before_cards, after_cards)
        self.assertEqual(before_state, _digest(STATE))

    def test_through_the_registry_dispatch(self):
        verdict, _ = ca.run_probe("tier_promotion_loop_closed")
        self.assertEqual(verdict, ca.SATISFIED)


class BrokenLinks(unittest.TestCase):
    """Каждое звено контура порвано по отдельности — проба обязана назвать именно его."""

    def test_reader_removed_means_no_card(self):
        real = fb.collect_findings

        def without_tier(root):
            findings, unread = real(root)
            return [f for f in findings if not str(f.get("key", "")).startswith("tier_promote:")], unread

        with mock.patch.object(fb, "collect_findings", without_tier):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("разомкнут", detail)
        self.assertIn(KEY, detail)

    def test_candidate_escalated_to_owner_is_not_the_loop(self):
        real = fb.collect_findings

        def as_critical(root):
            findings, unread = real(root)
            for f in findings:
                if str(f.get("key", "")).startswith("tier_promote:"):
                    f["severity"] = "CRITICAL"
            return findings, unread

        with mock.patch.object(fb, "collect_findings", as_critical):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("владельцу", detail)

    def test_auto_close_broken_is_named(self):
        with mock.patch.object(fb, "card_is_untouched", lambda _p: False):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("авто-закрытие", detail)

    def test_briefing_section_dropped_is_named(self):
        mod = ca._briefing_module()
        with mock.patch.object(mod, "build_tier_curator_section", lambda: "## 🎚️ Тир-куратор\n- кандидатов на подъём: **нет**."):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("второй читатель", detail)

    def test_name_in_prose_is_not_a_table_row(self):
        """ADR-333: приёмка подстрокой оставалась зелёной при удалении ключа. Имя
        протокола в прозе секции — не строка таблицы, и проба обязана это различать."""
        mod = ca._briefing_module()
        prose = (f"## 🎚️ Тир-куратор\n- про {ca.TIER_PROBE_PROTO} T3 T2 написано словами, "
                 f"таблицы нет\n")
        with mock.patch.object(mod, "build_tier_curator_section", lambda: prose):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("строки таблицы", detail)

    def test_wrong_tier_cells_are_not_satisfied(self):
        mod = ca._briefing_module()
        table = (f"## 🎚️ Тир-куратор\n| кандидат на подъём | сейчас | цель | владелец? |\n|---|---|---|---|\n"
                 f"| {ca.TIER_PROBE_PROTO} | T2 | T1 | да |\n")
        with mock.patch.object(mod, "build_tier_curator_section", lambda: table):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("ожидалось", detail)


class ThirdOutcome(unittest.TestCase):
    def test_probe_crash_is_unmeasured_never_a_verdict(self):
        def boom(*a, **k):
            raise RuntimeError("мост недоступен")
        with mock.patch.object(fb, "run_bridge", boom):
            verdict, detail = ca.run_probe("tier_promotion_loop_closed")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("упала", detail)

    def test_briefing_unloadable_is_unmeasured(self):
        def no_module():
            raise ImportError("scripts/update_system_briefing.py не грузится")
        with mock.patch.object(ca, "_briefing_module", no_module):
            verdict, detail = ca._probe_tier_promotion_loop(None, now=NOW)
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("брифинга", detail)


if __name__ == "__main__":
    unittest.main()
