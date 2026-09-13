"""Брифинг обязан иметь секцию тир-куратора — второй читатель tier_curator_report.json.

# LLM_FORBIDDEN

Разбор 11.09 (`docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md` §3.1): 13 секций брифинга, куратора
среди них не было. Секция, не попавшая в сборку, не существует для читателя (урок #144) —
поэтому проверяется и вызов в main(), а не только наличие функции. Три исхода отчёта
различимы (инв. #17): нет файла · нет метки · есть.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

from spa_core.tests._freshness import ts

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update_system_briefing.py"


def _mod():
    spec = importlib.util.spec_from_file_location("briefing_tc", str(_SCRIPT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TierCuratorSectionWired(unittest.TestCase):
    def setUp(self):
        self.m = _mod()

    def test_it_is_wired_into_the_briefing(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn('build_tier_curator_section() +', src,
                      "секция обязана вызываться в main(), а не только существовать")

    def test_missing_report_is_named_not_glossed(self):
        with mock.patch.object(self.m, "read_json", return_value={}):
            out = self.m.build_tier_curator_section()
        self.assertIn("отсутствует", out)
        self.assertNotIn("кандидатов на подъём: **нет**", out)   # «нет файла» ≠ «нет кандидатов»

    def test_report_without_stamp_says_unmeasured(self):
        with mock.patch.object(self.m, "read_json", return_value={"verdicts": {}, "summary": {}}):
            out = self.m.build_tier_curator_section()
        self.assertIn("НЕ измерена", out)

    def test_candidate_is_listed_with_target_and_gate(self):
        # Относительная отметка (deployment.md, приём №2): дата не предмет теста —
        # секция только печатает метку, свежесть по ней не судит.
        doc = {"generated_at": ts(hours_ago=1),
               "verdicts": {"susde": {"verdict": "PROMOTE_CANDIDATE", "current_tier": "T3",
                                      "target_tier": "T2", "owner_gated": False},
                            "maple": {"verdict": "PROMOTE_CANDIDATE", "current_tier": "T2",
                                      "target_tier": "T1", "owner_gated": True}},
               "summary": {"total": 2, "keep": 0, "demote_signal": 0, "promote_candidate": 2,
                           "unchecked": 0, "held_flagged": ["pendle"]}}
        with mock.patch.object(self.m, "read_json", return_value=doc):
            out = self.m.build_tier_curator_section()
        self.assertIn("| susde | T3 | T2 |", out)
        self.assertIn("| maple | T2 | T1 | да", out)
        self.assertIn("pendle", out)
        self.assertIn("НЕ меняет ярлык", out)


if __name__ == "__main__":
    unittest.main()
