"""
tests/test_research_scenario_matrix.py

40 unit tests for spa_core/backtesting/research_scenario_matrix.py

Coverage:
  - run_rs001_scenarios(): count, structure, verdict logic, worst-case
  - run_rs002_scenarios(): count, structure, IL presence, worst-case
  - RS-002 worst vs RS-001 worst
  - summary_table(): shape, bounds, positive_pct
  - save(): atomic (tmp+replace), directory creation
  - to_markdown_summary(): RS001 / RS002 presence
  - run_all(): count, speed (<3s), idempotent

Date: 2026-06-19 (MP-1313, Sprint v9.29)
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
import tempfile
from pathlib import Path

# Make sure spa_core is importable from the project root
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.backtesting.research_scenario_matrix import ResearchScenarioMatrix


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fresh() -> ResearchScenarioMatrix:
    return ResearchScenarioMatrix()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. RS-001 scenario count
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS001Count(unittest.TestCase):

    def test_rs001_exactly_60_scenarios(self):
        m = _fresh()
        result = m.run_rs001_scenarios()
        self.assertEqual(len(result), 60)

    def test_rs001_all_strategy_tag_rs001(self):
        m = _fresh()
        result = m.run_rs001_scenarios()
        for s in result:
            self.assertEqual(s["strategy"], "RS-001")

    def test_rs001_unique_scenario_ids(self):
        m = _fresh()
        result = m.run_rs001_scenarios()
        ids = [s["scenario_id"] for s in result]
        self.assertEqual(len(set(ids)), 60)

    def test_rs001_ids_prefixed_correctly(self):
        m = _fresh()
        result = m.run_rs001_scenarios()
        for s in result:
            self.assertTrue(s["scenario_id"].startswith("RS001-"),
                            f"Bad id: {s['scenario_id']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RS-001 scenario structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS001Structure(unittest.TestCase):

    def setUp(self):
        self.m = _fresh()
        self.scenarios = self.m.run_rs001_scenarios()

    def test_rs001_has_net_apy_key(self):
        for s in self.scenarios:
            self.assertIn("net_apy", s)

    def test_rs001_has_gross_apy_key(self):
        for s in self.scenarios:
            self.assertIn("gross_apy", s)

    def test_rs001_has_verdict_key(self):
        for s in self.scenarios:
            self.assertIn("verdict", s)

    def test_rs001_has_risk_score_key(self):
        for s in self.scenarios:
            self.assertIn("risk_score", s)

    def test_rs001_has_btc_move_key(self):
        for s in self.scenarios:
            self.assertIn("btc_move", s)

    def test_rs001_il_drag_is_zero(self):
        """RS-001 has no LP components — IL drag should be 0."""
        for s in self.scenarios:
            self.assertEqual(s["il_drag"], 0.0,
                             f"Expected il_drag=0 for RS-001 but got {s['il_drag']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. RS-001 verdict logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS001Verdict(unittest.TestCase):

    def setUp(self):
        self.scenarios = _fresh().run_rs001_scenarios()

    def test_rs001_verdict_positive_when_net_apy_positive(self):
        for s in self.scenarios:
            if s["net_apy"] > 0:
                self.assertEqual(s["verdict"], "POSITIVE",
                                 f"net_apy={s['net_apy']} should be POSITIVE")

    def test_rs001_verdict_negative_when_net_apy_negative(self):
        for s in self.scenarios:
            if s["net_apy"] < 0:
                self.assertEqual(s["verdict"], "NEGATIVE",
                                 f"net_apy={s['net_apy']} should be NEGATIVE")

    def test_rs001_verdict_only_valid_values(self):
        valid = {"POSITIVE", "NEGATIVE"}
        for s in self.scenarios:
            self.assertIn(s["verdict"], valid)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RS-002 scenario count
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS002Count(unittest.TestCase):

    def test_rs002_exactly_60_scenarios(self):
        m = _fresh()
        result = m.run_rs002_scenarios()
        self.assertEqual(len(result), 60)

    def test_rs002_all_strategy_tag_rs002(self):
        m = _fresh()
        result = m.run_rs002_scenarios()
        for s in result:
            self.assertEqual(s["strategy"], "RS-002")

    def test_rs002_unique_scenario_ids(self):
        m = _fresh()
        result = m.run_rs002_scenarios()
        ids = [s["scenario_id"] for s in result]
        self.assertEqual(len(set(ids)), 60)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RS-002 scenario structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS002Structure(unittest.TestCase):

    def setUp(self):
        self.scenarios = _fresh().run_rs002_scenarios()

    def test_rs002_has_net_apy_key(self):
        for s in self.scenarios:
            self.assertIn("net_apy", s)

    def test_rs002_has_verdict_key(self):
        for s in self.scenarios:
            self.assertIn("verdict", s)

    def test_rs002_has_il_drag_key(self):
        for s in self.scenarios:
            self.assertIn("il_drag", s)

    def test_rs002_has_vol_annual_key(self):
        for s in self.scenarios:
            self.assertIn("vol_annual", s)

    def test_rs002_has_range_width_key(self):
        for s in self.scenarios:
            self.assertIn("range_width", s)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RS-002 verdict logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS002Verdict(unittest.TestCase):

    def setUp(self):
        self.scenarios = _fresh().run_rs002_scenarios()

    def test_rs002_verdict_positive_when_net_apy_positive(self):
        for s in self.scenarios:
            if s["net_apy"] > 0:
                self.assertEqual(s["verdict"], "POSITIVE")

    def test_rs002_verdict_negative_when_net_apy_negative(self):
        for s in self.scenarios:
            if s["net_apy"] < 0:
                self.assertEqual(s["verdict"], "NEGATIVE")

    def test_rs002_verdict_only_valid_values(self):
        valid = {"POSITIVE", "NEGATIVE"}
        for s in self.scenarios:
            self.assertIn(s["verdict"], valid)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. IL drag in RS-002
# ═══════════════════════════════════════════════════════════════════════════════

class TestRS002ILDrag(unittest.TestCase):

    def setUp(self):
        self.scenarios = _fresh().run_rs002_scenarios()

    def test_rs002_btc_crash_narrow_range_has_il_drag(self):
        """BTC -50%, narrow range (±10%), high vol should have significant IL drag."""
        crash_narrow = [
            s for s in self.scenarios
            if s["btc_move"] == -50.0 and s.get("range_width") == 10.0
        ]
        self.assertTrue(len(crash_narrow) > 0, "No -50%/narrow scenarios found")
        for s in crash_narrow:
            self.assertGreater(s["il_drag"], 0.0,
                               "Expected positive IL drag for crash+narrow scenario")

    def test_rs002_net_apy_le_gross_apy(self):
        """Net APY must be <= gross APY (IL drag is always non-negative)."""
        for s in self.scenarios:
            self.assertLessEqual(
                s["net_apy"], s["gross_apy"] + 1e-6,  # small float tolerance
                f"net_apy {s['net_apy']} > gross_apy {s['gross_apy']}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Worst-case comparison: RS-002 << RS-001 at BTC -50% narrow
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorstCaseComparison(unittest.TestCase):

    def test_rs002_worst_crash_narrow_worse_than_rs001_worst(self):
        """
        RS-002 worst scenario at BTC -50%, narrow range (±10%) should have
        net_apy significantly lower than RS-001 worst scenario at BTC -50%.
        Concentrated LP has much higher downside in crashes.
        """
        m = _fresh()
        rs001 = m.run_rs001_scenarios()
        rs002 = m.run_rs002_scenarios()

        # RS-001 worst at BTC -50%
        rs001_crash = [s for s in rs001 if s["btc_move"] == -50.0]
        self.assertTrue(rs001_crash)
        rs001_worst = min(s["net_apy"] for s in rs001_crash)

        # RS-002 worst at BTC -50%, narrow range
        rs002_crash_narrow = [
            s for s in rs002
            if s["btc_move"] == -50.0 and s.get("range_width") == 10.0
        ]
        self.assertTrue(rs002_crash_narrow, "No RS-002 crash+narrow scenarios")
        rs002_worst = min(s["net_apy"] for s in rs002_crash_narrow)

        self.assertLess(rs002_worst, rs001_worst,
                        f"Expected RS-002 worst ({rs002_worst:.2f}%) < "
                        f"RS-001 worst ({rs001_worst:.2f}%) at BTC -50%")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. summary_table()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSummaryTable(unittest.TestCase):

    def setUp(self):
        self.m = _fresh()
        self.m.run_all()
        self.st = self.m.summary_table()

    def test_summary_table_has_rs001_key(self):
        self.assertIn("rs001", self.st)

    def test_summary_table_has_rs002_key(self):
        self.assertIn("rs002", self.st)

    def test_summary_rs001_count_60(self):
        self.assertEqual(self.st["rs001"]["count"], 60)

    def test_summary_rs002_count_60(self):
        self.assertEqual(self.st["rs002"]["count"], 60)

    def test_summary_positive_pct_between_0_and_100(self):
        for key in ("rs001", "rs002"):
            pct = self.st[key]["positive_pct"]
            self.assertGreaterEqual(pct, 0.0, f"{key} positive_pct < 0")
            self.assertLessEqual(pct, 100.0, f"{key} positive_pct > 100")

    def test_summary_worst_le_avg_le_best(self):
        for key in ("rs001", "rs002"):
            s = self.st[key]
            self.assertLessEqual(s["worst_net_apy"], s["avg_net_apy"] + 1e-6,
                                 f"{key}: worst > avg")
            self.assertLessEqual(s["avg_net_apy"], s["best_net_apy"] + 1e-6,
                                 f"{key}: avg > best")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. save() — atomic write
# ═══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def test_save_creates_file(self):
        m = _fresh()
        m.run_all()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "subdir", "out.json")
            m.save(dest)
            self.assertTrue(os.path.exists(dest), f"File not created at {dest}")

    def test_save_creates_parent_dirs(self):
        m = _fresh()
        m.run_all()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "deep", "nested", "dir", "rs.json")
            m.save(dest)
            self.assertTrue(os.path.exists(dest))

    def test_save_valid_json(self):
        m = _fresh()
        m.run_all()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "rs.json")
            m.save(dest)
            with open(dest, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("rs001", data)
            self.assertIn("rs002", data)

    def test_save_total_scenarios_in_json(self):
        m = _fresh()
        m.run_all()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "rs.json")
            m.save(dest)
            with open(dest, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["total_scenarios"], 120)

    def test_save_atomic_no_tmp_leftover(self):
        """No .rsmatrix_tmp_ files should remain after successful save."""
        m = _fresh()
        m.run_all()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "rs.json")
            m.save(dest)
            leftovers = [f for f in os.listdir(td) if f.startswith(".rsmatrix_tmp_")]
            self.assertEqual(leftovers, [], f"Tmp files left: {leftovers}")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. to_markdown_summary()
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkdownSummary(unittest.TestCase):

    def setUp(self):
        self.m = _fresh()
        self.m.run_all()
        self.md = self.m.to_markdown_summary()

    def test_markdown_contains_rs001(self):
        self.assertIn("RS001", self.md)

    def test_markdown_contains_rs002(self):
        self.assertIn("RS002", self.md)

    def test_markdown_is_string(self):
        self.assertIsInstance(self.md, str)

    def test_markdown_has_table_separator(self):
        self.assertIn("|", self.md)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. run_all() — count and speed
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunAll(unittest.TestCase):

    def test_run_all_total_120_scenarios(self):
        m = _fresh()
        result = m.run_all()
        self.assertEqual(result["total_scenarios"], 120)

    def test_run_all_rs001_count_60(self):
        m = _fresh()
        result = m.run_all()
        self.assertEqual(result["rs001_count"], 60)

    def test_run_all_rs002_count_60(self):
        m = _fresh()
        result = m.run_all()
        self.assertEqual(result["rs002_count"], 60)

    def test_run_all_completes_under_3_seconds(self):
        """No real IO in scenario matrix — must be fast."""
        m = _fresh()
        t0 = time.time()
        m.run_all()
        elapsed = time.time() - t0
        self.assertLess(elapsed, 3.0,
                        f"run_all() took {elapsed:.2f}s — expected < 3s")

    def test_run_all_has_summary_key(self):
        m = _fresh()
        result = m.run_all()
        self.assertIn("summary", result)

    def test_run_all_has_generated_at(self):
        m = _fresh()
        result = m.run_all()
        self.assertIn("generated_at", result)

    def test_run_all_idempotent_count(self):
        """Calling run_all() twice should still return 120 scenarios."""
        m = _fresh()
        m.run_all()
        result2 = m.run_all()
        self.assertEqual(result2["total_scenarios"], 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
