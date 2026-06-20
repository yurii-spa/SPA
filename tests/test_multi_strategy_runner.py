#!/usr/bin/env python3
"""
tests/test_multi_strategy_runner.py — MP-1451 (Sprint v10.67)

Test suite for spa_core/paper_trading/multi_strategy_runner.py.

Tests:
  A. Instantiation & basic API (A1–A4)
  B. run_day — happy path (B1–B4)
  C. get_rankings (C1–C3)
  D. export_results — atomic write (D1–D5)
  E. Atomic migration — uses atomic_save (E1–E2)

Pure stdlib. No network. Offline.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner, RANKING_FILENAME
from spa_core.paper_trading.strategy_registry import S0_CONSERVATIVE_T1, S1_BALANCED


# Minimal APY map covering strategies S0 and S1
_APY_MAP = {
    "aave_v3":    3.5,
    "compound_v3": 4.8,
    "morpho_blue": 6.5,
    "yearn_v3":    5.2,
    "euler_v2":    4.1,
    "maple":       7.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Instantiation & basic API
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_A1_can_instantiate_with_strategy_list(self):
        """MultiStrategyRunner can be created with a list of StrategyConfig."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        self.assertIsNotNone(runner)

    def test_A2_empty_strategy_list_accepted(self):
        """MultiStrategyRunner accepts empty strategy list."""
        runner = MultiStrategyRunner([])
        self.assertIsNotNone(runner)

    def test_A3_get_active_strategies_returns_active(self):
        """get_active_strategies returns only active strategies."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        active = runner.get_active_strategies()
        self.assertIsInstance(active, list)
        for cfg in active:
            self.assertEqual(cfg.status, "active")

    def test_A4_get_allocation_map_returns_dict(self):
        """get_allocation_map returns a dict after run_day."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        runner.run_day(_APY_MAP)
        alloc = runner.get_allocation_map()
        self.assertIsInstance(alloc, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — run_day
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunDay(unittest.TestCase):

    def test_B1_run_day_returns_dict(self):
        """run_day returns a dict of protocol→apy."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        result = runner.run_day(_APY_MAP)
        self.assertIsInstance(result, dict)

    def test_B2_run_day_multiple_strategies(self):
        """run_day works with multiple strategies without crashing."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        result = runner.run_day(_APY_MAP)
        self.assertIsInstance(result, dict)

    def test_B3_run_day_multiple_times(self):
        """run_day can be called multiple times to accumulate history."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        for _ in range(5):
            runner.run_day(_APY_MAP)
        alloc = runner.get_allocation_map()
        self.assertIsInstance(alloc, dict)

    def test_B4_get_total_yield_after_run(self):
        """get_total_yield returns a float >= 0 after run_day."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day(_APY_MAP)
        total = runner.get_total_yield()
        self.assertIsInstance(total, float)
        self.assertGreaterEqual(total, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — get_rankings
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRankings(unittest.TestCase):

    def test_C1_rankings_returns_list(self):
        """get_rankings() returns a list."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day(_APY_MAP)
        rankings = runner.get_rankings()
        self.assertIsInstance(rankings, list)

    def test_C2_ranking_items_have_required_keys(self):
        """Each ranking entry has rank, strategy_id, composite_score, net_apy."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        for _ in range(3):
            runner.run_day(_APY_MAP)
        rankings = runner.get_rankings()
        for item in rankings:
            self.assertIn("rank", item)
            self.assertIn("strategy_id", item)
            self.assertIn("composite_score", item)
            self.assertIn("net_apy", item)

    def test_C3_ranks_are_sequential_from_one(self):
        """Ranks start at 1 and are sequential."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        for _ in range(3):
            runner.run_day(_APY_MAP)
        rankings = runner.get_rankings()
        ranks = sorted(r["rank"] for r in rankings)
        self.assertEqual(ranks, list(range(1, len(rankings) + 1)))


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — export_results (atomic write)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExportResults(unittest.TestCase):

    def test_D1_export_creates_file(self):
        """export_results creates the target JSON file."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        runner.run_day(_APY_MAP)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "tournament_ranking.json"
            runner.export_results(path)
            self.assertTrue(path.exists())

    def test_D2_exported_file_is_valid_json(self):
        """The exported file contains valid JSON."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day(_APY_MAP)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "ranking.json"
            runner.export_results(path)
            data = json.loads(path.read_text())
            self.assertIn("strategies", data)
            self.assertIn("timestamp", data)

    def test_D3_exported_doc_has_total_active(self):
        """Exported JSON contains total_active and weighted_apy."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day(_APY_MAP)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "ranking.json"
            runner.export_results(path)
            data = json.loads(path.read_text())
            self.assertIn("total_active", data)
            self.assertIn("weighted_apy", data)

    def test_D4_no_tmp_files_after_export(self):
        """export_results leaves no .tmp files."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        runner.run_day(_APY_MAP)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "ranking.json"
            runner.export_results(path)
            tmp_files = list(pathlib.Path(d).glob("*.tmp*"))
            self.assertEqual(len(tmp_files), 0)

    def test_D5_export_creates_parent_dirs(self):
        """export_results creates nested parent directories if needed."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        runner.run_day(_APY_MAP)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "nested" / "deep" / "ranking.json"
            runner.export_results(path)
            self.assertTrue(path.exists())


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — Atomic migration verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_E1_atomic_save_imported_after_migration(self):
        """multi_strategy_runner.py imports atomic_save after migration (MP-1451)."""
        src = (_REPO / "spa_core" / "paper_trading" / "multi_strategy_runner.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "atomic_save", src,
            "export_results should use atomic_save after migration — run migration first"
        )

    def test_E2_from_atomic_import_present(self):
        """multi_strategy_runner.py has 'from spa_core.utils.atomic import' after migration."""
        src = (_REPO / "spa_core" / "paper_trading" / "multi_strategy_runner.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from spa_core.utils.atomic import", src,
                      "Migration adds 'from spa_core.utils.atomic import atomic_save'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
