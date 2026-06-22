"""
tests/test_protocol_data_audit.py — 35 tests for ProtocolDataAudit (MP-1331 v9.47)

Coverage:
  T01–T05   Constructor and basic setup
  T06–T10   run_audit() return structure
  T11–T15   by_protocol entry fields
  T16–T20   summary counts and consistency
  T21–T25   top_priorities() behaviour
  T26–T28   priority_score() ordering
  T29–T33   acquisition_roadmap() structure
  T34       save() atomic write
  T35       to_markdown() content

Conventions:
  - stdlib only (unittest, tempfile, json, os)
  - Atomic save tested in isolated tempdir — never touches real data/
  - All 35 tests are independent and self-contained

Run:
    python3 -m unittest tests/test_protocol_data_audit.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile

# Ensure repo root is on sys.path regardless of cwd
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_data_audit import ProtocolDataAudit


# ══════════════════════════════════════════════════════════════════════════════
# T01–T05  Constructor and basic setup
# ══════════════════════════════════════════════════════════════════════════════

class TestConstructor(unittest.TestCase):

    def test_T01_instantiates_without_args(self):
        """ProtocolDataAudit() можно создать без аргументов."""
        audit = ProtocolDataAudit()
        self.assertIsInstance(audit, ProtocolDataAudit)

    def test_T02_default_base_dir_is_dot(self):
        """Дефолтный base_dir = '.'"""
        audit = ProtocolDataAudit()
        self.assertEqual(audit._base_dir, ".")

    def test_T03_custom_base_dir_stored(self):
        """Кастомный base_dir сохраняется."""
        audit = ProtocolDataAudit(base_dir="/tmp/spa_test")
        self.assertEqual(audit._base_dir, "/tmp/spa_test")

    def test_T04_run_audit_is_callable(self):
        """run_audit() — callable метод."""
        audit = ProtocolDataAudit()
        self.assertTrue(callable(audit.run_audit))

    def test_T05_run_audit_returns_dict(self):
        """run_audit() возвращает dict."""
        audit = ProtocolDataAudit()
        result = audit.run_audit()
        self.assertIsInstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# T06–T10  run_audit() return structure
# ══════════════════════════════════════════════════════════════════════════════

class TestRunAuditStructure(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.result = self.audit.run_audit()

    def test_T06_has_by_protocol_key(self):
        """Результат содержит ключ 'by_protocol'."""
        self.assertIn("by_protocol", self.result)

    def test_T07_has_summary_key(self):
        """Результат содержит ключ 'summary'."""
        self.assertIn("summary", self.result)

    def test_T08_has_top_10_priorities_key(self):
        """Результат содержит ключ 'top_10_priorities'."""
        self.assertIn("top_10_priorities", self.result)

    def test_T09_has_estimated_days_key(self):
        """Результат содержит ключ 'estimated_days_to_full_coverage'."""
        self.assertIn("estimated_days_to_full_coverage", self.result)

    def test_T10_by_protocol_is_nonempty_dict(self):
        """'by_protocol' — непустой dict."""
        bp = self.result["by_protocol"]
        self.assertIsInstance(bp, dict)
        self.assertGreater(len(bp), 0)


# ══════════════════════════════════════════════════════════════════════════════
# T11–T15  by_protocol entry fields
# ══════════════════════════════════════════════════════════════════════════════

class TestByProtocolEntries(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.result = self.audit.run_audit()
        # Pick a deterministic entry present in every run
        self.entry = self.result["by_protocol"]["morpho_steakhouse"]

    def test_T11_entry_has_source_state(self):
        """Каждая запись имеет 'source_state' (str)."""
        self.assertIsInstance(self.entry["source_state"], str)
        self.assertTrue(len(self.entry["source_state"]) > 0)

    def test_T12_entry_has_strategies_list(self):
        """Каждая запись имеет 'strategies' (list)."""
        self.assertIsInstance(self.entry["strategies"], list)

    def test_T13_entry_has_total_weight_float(self):
        """'total_weight_across_strategies' — float ≥ 0."""
        w = self.entry["total_weight_across_strategies"]
        self.assertIsInstance(w, float)
        self.assertGreaterEqual(w, 0.0)

    def test_T14_entry_has_priority_score_float(self):
        """'priority_score' — float ≥ 0."""
        score = self.entry["priority_score"]
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)

    def test_T15_entry_has_action_needed_str_or_none(self):
        """'action_needed' — str или None."""
        action = self.entry["action_needed"]
        self.assertTrue(action is None or isinstance(action, str))


# ══════════════════════════════════════════════════════════════════════════════
# T16–T20  summary counts and consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestSummary(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.result = self.audit.run_audit()
        self.summary = self.result["summary"]

    def test_T16_summary_has_total_protocols(self):
        """summary содержит 'total_protocols' (int > 0)."""
        total = self.summary["total_protocols"]
        self.assertIsInstance(total, int)
        self.assertGreater(total, 0)

    def test_T17_summary_clean_gt_zero(self):
        """summary['clean'] > 0 — есть хотя бы один чистый источник."""
        self.assertGreater(self.summary["clean"], 0)

    def test_T18_summary_source_needed_gt_zero(self):
        """summary['source_needed'] > 0 — есть протоколы без источника."""
        self.assertGreater(self.summary["source_needed"], 0)

    def test_T19_summary_categories_sum_to_total(self):
        """clean + pending + research_only + source_needed = total_protocols."""
        s = self.summary
        cat_sum = s["clean"] + s["pending"] + s["research_only"] + s["source_needed"]
        self.assertEqual(cat_sum, s["total_protocols"])

    def test_T20_acquisition_backlog_equals_non_clean(self):
        """acquisition_backlog = pending + research_only + source_needed."""
        s = self.summary
        expected = s["pending"] + s["research_only"] + s["source_needed"]
        self.assertEqual(s["acquisition_backlog"], expected)


# ══════════════════════════════════════════════════════════════════════════════
# T21–T25  top_priorities() behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestTopPriorities(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.audit.run_audit()

    def test_T21_top_priorities_10_returns_le_10(self):
        """top_priorities(10) возвращает ≤ 10 элементов."""
        top = self.audit.top_priorities(10)
        self.assertIsInstance(top, list)
        self.assertLessEqual(len(top), 10)

    def test_T22_top_priorities_5_returns_le_5(self):
        """top_priorities(5) возвращает ≤ 5 элементов."""
        top = self.audit.top_priorities(5)
        self.assertLessEqual(len(top), 5)

    def test_T23_top_priorities_sorted_descending(self):
        """Элементы top_priorities отсортированы по score убыванию."""
        top = self.audit.top_priorities(10)
        scores = [e["priority_score"] for e in top]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_T24_each_top_entry_has_required_fields(self):
        """Каждый элемент top_priorities имеет protocol_id, source_state, priority_score, action_needed."""
        top = self.audit.top_priorities(10)
        self.assertGreater(len(top), 0)
        for entry in top:
            for field in ("protocol_id", "source_state", "priority_score", "action_needed"):
                self.assertIn(field, entry, msg=f"Missing field '{field}' in {entry}")

    def test_T25_source_needed_score_gt_clean_no_strategies(self):
        """SOURCE_NEEDED протокол с весом в стратегии > CLEAN без стратегий."""
        # pendle_yt is SOURCE_NEEDED in S7 (weight 0.40) — score = 0.40*10 + 20 = 24.0
        # aave_v2_usdc is CLEAN_INCLUDED with no active strategies — score = 0.0
        score_needed = self.audit.priority_score("pendle_yt")
        score_clean  = self.audit.priority_score("aave_v2_usdc")
        self.assertGreater(score_needed, score_clean)


# ══════════════════════════════════════════════════════════════════════════════
# T26–T28  priority_score() ordering
# ══════════════════════════════════════════════════════════════════════════════

class TestPriorityScore(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()

    def test_T26_priority_score_returns_float(self):
        """priority_score() возвращает float."""
        score = self.audit.priority_score("morpho_steakhouse")
        self.assertIsInstance(score, float)

    def test_T27_source_needed_beats_clean_no_coverage(self):
        """SOURCE_NEEDED (с penalty) > CLEAN без стратегий."""
        # gmx_btc_exposure: SOURCE_NEEDED in S20 research → 0.20*5 + 20 = 21.0
        # compound_v2_usdc: CLEAN, no active strategies → 0.0
        self.assertGreater(
            self.audit.priority_score("gmx_btc_exposure"),
            self.audit.priority_score("compound_v2_usdc"),
        )

    def test_T28_more_strategies_higher_score_same_state(self):
        """Протокол в большем числе стратегий > протокол в меньшем (одинаковое состояние)."""
        # compound_v3 CLEAN in 6 production strategies
        # aave_mainnet CLEAN in 1 production strategy
        score_many = self.audit.priority_score("compound_v3")
        score_one  = self.audit.priority_score("aave_mainnet")
        self.assertGreater(score_many, score_one)


# ══════════════════════════════════════════════════════════════════════════════
# T29–T33  acquisition_roadmap() structure
# ══════════════════════════════════════════════════════════════════════════════

class TestAcquisitionRoadmap(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.audit.run_audit()
        self.roadmap = self.audit.acquisition_roadmap()

    def test_T29_roadmap_returns_list(self):
        """acquisition_roadmap() возвращает list."""
        self.assertIsInstance(self.roadmap, list)

    def test_T30_roadmap_has_priority_field(self):
        """Каждый элемент roadmap имеет 'priority' (int ≥ 1)."""
        self.assertGreater(len(self.roadmap), 0)
        for item in self.roadmap:
            self.assertIn("priority", item)
            self.assertIsInstance(item["priority"], int)
            self.assertGreaterEqual(item["priority"], 1)

    def test_T31_roadmap_has_action_field(self):
        """Каждый элемент roadmap имеет 'action' (непустой str)."""
        for item in self.roadmap:
            self.assertIn("action", item)
            self.assertIsInstance(item["action"], str)
            self.assertGreater(len(item["action"]), 0)

    def test_T32_roadmap_has_effort_field(self):
        """'effort' — одно из LOW/MEDIUM/HIGH."""
        valid_efforts = {"LOW", "MEDIUM", "HIGH"}
        for item in self.roadmap:
            self.assertIn("effort", item)
            self.assertIn(item["effort"], valid_efforts)

    def test_T33_roadmap_has_impact_float(self):
        """'impact' — float ≥ 0 (APY% потенциал)."""
        for item in self.roadmap:
            self.assertIn("impact", item)
            self.assertIsInstance(item["impact"], float)
            self.assertGreaterEqual(item["impact"], 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# T34  save() atomic write
# ══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def test_T34_save_creates_valid_json_atomically(self):
        """save() создаёт валидный JSON-файл атомарно (через mkstemp + os.replace)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = ProtocolDataAudit(base_dir=tmpdir)
            relative_path = "data/research/protocol_data_audit.json"
            audit.save(path=relative_path)

            target = os.path.join(tmpdir, relative_path)
            self.assertTrue(
                os.path.exists(target),
                msg=f"Expected file at {target} but it does not exist",
            )
            # File is valid JSON with expected structure
            with open(target, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("by_protocol", data)
            self.assertIn("summary", data)
            self.assertIn("top_10_priorities", data)
            # No leftover temp files
            tmp_leftovers = [
                f for f in os.listdir(os.path.dirname(target))
                if f.startswith(".tmp_protocol_audit_")
            ]
            self.assertEqual(tmp_leftovers, [],
                             msg="Atomic tmp file was not cleaned up")


# ══════════════════════════════════════════════════════════════════════════════
# T35  to_markdown() content
# ══════════════════════════════════════════════════════════════════════════════

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.audit = ProtocolDataAudit()
        self.audit.run_audit()
        self.md = self.audit.to_markdown()

    def test_T35_to_markdown_contains_key_protocols(self):
        """to_markdown() содержит ключевые протоколы и разделы отчёта."""
        self.assertIsInstance(self.md, str)
        self.assertGreater(len(self.md), 200)
        # Required sections
        self.assertIn("# Protocol Data Audit Report", self.md)
        self.assertIn("## Summary", self.md)
        self.assertIn("## Top 10 Priority Protocols", self.md)
        self.assertIn("## Acquisition Roadmap", self.md)
        # Key protocols must appear
        for protocol in ("morpho_steakhouse", "pendle_yt", "gmx_btc_exposure", "compound_v3"):
            self.assertIn(protocol, self.md,
                          msg=f"Protocol '{protocol}' missing from markdown output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
