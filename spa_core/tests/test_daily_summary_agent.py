"""Tests for spa_core.agents.daily_summary_agent (MP-1578 / Improvement 3).

25 unit tests across:
  - TestRankStrategies     (5)
  - TestKeyRisks           (5)
  - TestBuildSummary       (6)
  - TestFormatTelegram     (4)
  - TestSendSaveRun        (5)

Run:
  python3 -m unittest spa_core.tests.test_daily_summary_agent -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.agents.daily_summary_agent import (
    DailySummaryAgent,
    _derive_key_risks,
    _max_position_pct,
    _rank_strategies,
    main,
)


class TestRankStrategies(unittest.TestCase):
    def test_ranks_by_net_apy(self):
        t = {"strategies": [
            {"strategy_id": "S1", "net_apy": 3.0, "composite_score": 0.1},
            {"strategy_id": "S2", "net_apy": 8.0, "composite_score": 0.2},
            {"strategy_id": "S3", "net_apy": 1.0, "composite_score": 0.3},
        ]}
        r = _rank_strategies(t)
        self.assertEqual(r["best"]["strategy_id"], "S2")
        self.assertEqual(r["worst"]["strategy_id"], "S3")

    def test_tiebreak_on_composite(self):
        t = {"strategies": [
            {"strategy_id": "A", "net_apy": 0.0, "composite_score": 0.5},
            {"strategy_id": "B", "net_apy": 0.0, "composite_score": 0.9},
        ]}
        r = _rank_strategies(t)
        self.assertEqual(r["best"]["strategy_id"], "B")
        self.assertEqual(r["worst"]["strategy_id"], "A")

    def test_empty_strategies(self):
        r = _rank_strategies({"strategies": []})
        self.assertIsNone(r["best"]["strategy_id"])
        self.assertIsNone(r["worst"]["strategy_id"])

    def test_missing_key(self):
        r = _rank_strategies({})
        self.assertIsNone(r["best"]["strategy_id"])

    def test_skips_non_dict_entries(self):
        t = {"strategies": ["bad", {"strategy_id": "S1", "net_apy": 5.0}]}
        r = _rank_strategies(t)
        self.assertEqual(r["best"]["strategy_id"], "S1")


class TestKeyRisks(unittest.TestCase):
    def test_kill_switch_flagged(self):
        risks = _derive_key_risks(
            {"kill_switch_active": True, "kill_switch_reason": "drawdown"}, {}, {})
        self.assertTrue(any("Kill switch" in r for r in risks))

    def test_drawdown_flagged(self):
        risks = _derive_key_risks(
            {}, {"summary": {"max_drawdown_pct": -3.0}}, {})
        self.assertTrue(any("drawdown" in r.lower() for r in risks))

    def test_concentration_flagged(self):
        risks = _derive_key_risks(
            {"current_positions": {"a": 50000, "b": 50000}}, {}, {})
        self.assertTrue(any("Concentration" in r for r in risks))

    def test_golive_blockers_flagged(self):
        risks = _derive_key_risks({}, {}, {"blockers": ["autopush_installed: missing"]})
        self.assertTrue(any("GoLive blocker" in r for r in risks))

    def test_all_clear(self):
        risks = _derive_key_risks(
            {"current_positions": {"a": 34, "b": 33, "c": 33}},
            {"summary": {"max_drawdown_pct": -0.1}},
            {"blockers": []})
        self.assertEqual(risks, [])


class TestMaxPositionPct(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_max_position_pct({"a": 40, "b": 60}), 60.0, places=4)

    def test_empty(self):
        self.assertEqual(_max_position_pct({}), 0.0)


class TestBuildSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)

    def _w(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_missing_all_files_safe(self):
        agent = DailySummaryAgent(data_dir=self.dir)
        s = agent.build_summary()
        self.assertIn("day_N", s)
        self.assertEqual(s["day_N"], 0)
        self.assertEqual(s["key_risks"], [])

    def test_day_n_from_status(self):
        self._w("paper_trading_status.json", {"days_running": 11})
        agent = DailySummaryAgent(data_dir=self.dir)
        self.assertEqual(agent.build_summary()["day_N"], 11)

    def test_equity_from_status(self):
        self._w("paper_trading_status.json",
                {"current_equity": 100120.13, "apy_today_pct": 4.39})
        s = DailySummaryAgent(data_dir=self.dir).build_summary()
        self.assertAlmostEqual(s["equity"], 100120.13, places=2)
        self.assertAlmostEqual(s["paper_apy"], 4.39, places=2)

    def test_equity_fallback_to_curve(self):
        self._w("equity_curve_daily.json",
                {"summary": {"end_equity": 99999.0, "total_return_pct": -0.001}})
        s = DailySummaryAgent(data_dir=self.dir).build_summary()
        self.assertAlmostEqual(s["equity"], 99999.0, places=2)

    def test_golive_status_string(self):
        self._w("golive_status.json", {"ready": False, "passed": 25, "total": 26})
        s = DailySummaryAgent(data_dir=self.dir).build_summary()
        self.assertEqual(s["golive_status"], "25/26 NOT READY")
        self.assertFalse(s["golive_ready"])

    def test_best_worst_from_tournament(self):
        self._w("tournament_results.json", {"strategies": [
            {"strategy_id": "S1", "net_apy": 2.0, "composite_score": 0.3},
            {"strategy_id": "S8", "net_apy": 9.0, "composite_score": 0.5}]})
        s = DailySummaryAgent(data_dir=self.dir).build_summary()
        self.assertEqual(s["best_strategy"]["strategy_id"], "S8")
        self.assertEqual(s["worst_strategy"]["strategy_id"], "S1")


class TestFormatTelegram(unittest.TestCase):
    def _summary(self, **kw):
        base = {
            "date": "2026-06-21", "day_N": 12, "equity": 100120.13,
            "paper_apy": 4.39, "total_return_pct": 0.12,
            "best_strategy": {"strategy_id": "S8", "net_apy": 9.0, "composite_score": 0.5},
            "worst_strategy": {"strategy_id": "S1", "net_apy": 2.0, "composite_score": 0.3},
            "golive_status": "25/26 NOT READY", "golive_ready": False,
            "key_risks": [],
        }
        base.update(kw)
        return base

    def test_contains_day_and_equity(self):
        txt = DailySummaryAgent.format_telegram(self._summary())
        self.assertIn("Day 12", txt)
        self.assertIn("100,120.13", txt)

    def test_html_bold_tags(self):
        txt = DailySummaryAgent.format_telegram(self._summary())
        self.assertIn("<b>", txt)

    def test_risks_listed(self):
        txt = DailySummaryAgent.format_telegram(
            self._summary(key_risks=["Kill switch active: drawdown"]))
        self.assertIn("Key risks", txt)
        self.assertIn("Kill switch", txt)

    def test_no_risks_message(self):
        txt = DailySummaryAgent.format_telegram(self._summary(key_risks=[]))
        self.assertIn("No key risks", txt)


class TestSendSaveRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)
        self.sent = []

    def _fake_sender(self, text):
        self.sent.append(text)
        return True

    def test_send_uses_injected_sender(self):
        agent = DailySummaryAgent(data_dir=self.dir, sender=self._fake_sender)
        ok = agent.send_telegram({"day_N": 1, "key_risks": []})
        self.assertTrue(ok)
        self.assertEqual(len(self.sent), 1)

    def test_sender_failure_returns_false(self):
        agent = DailySummaryAgent(data_dir=self.dir, sender=lambda t: False)
        self.assertFalse(agent.send_telegram({"day_N": 1, "key_risks": []}))

    def test_sender_exception_swallowed(self):
        def boom(_):
            raise RuntimeError("network down")
        agent = DailySummaryAgent(data_dir=self.dir, sender=boom)
        self.assertFalse(agent.send_telegram({"day_N": 1, "key_risks": []}))

    def test_save_writes_dated_file(self):
        agent = DailySummaryAgent(data_dir=self.dir, sender=self._fake_sender)
        summary = {"date": "2026-06-21", "day_N": 5, "key_risks": []}
        path = agent.save(summary)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "2026-06-21.json")
        self.assertEqual(json.loads(path.read_text())["day_N"], 5)

    def test_run_end_to_end(self):
        (self.dir / "paper_trading_status.json").write_text(
            json.dumps({"days_running": 7, "current_equity": 100000}), encoding="utf-8")
        agent = DailySummaryAgent(data_dir=self.dir, sender=self._fake_sender)
        result = agent.run(send=True, write=True)
        self.assertTrue(result["telegram_sent"])
        self.assertEqual(len(self.sent), 1)
        files = list((self.dir / "daily_summaries").glob("*.json"))
        self.assertEqual(len(files), 1)


class TestCLI(unittest.TestCase):
    def test_main_check_exit_zero(self):
        tmp = tempfile.mkdtemp()
        self.assertEqual(main(["--check", "--data-dir", tmp]), 0)


if __name__ == "__main__":
    unittest.main()
