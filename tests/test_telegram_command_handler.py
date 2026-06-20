#!/usr/bin/env python3
"""
tests/test_telegram_command_handler.py — MP-1492 (Sprint v11.08)

Unit tests for spa_core/telegram/command_handler.py
25 tests, pure stdlib, offline.

Groups:
    A. Module structure / COMMANDS map      (4 tests)
    B. handle() routing                      (5 tests)
    C. _cmd_system_status                    (5 tests)
    D. _cmd_golive_score                     (4 tests)
    E. _cmd_current_apy                      (4 tests)
    F. Other commands + edge cases           (3 tests)
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from spa_core.telegram.command_handler import CommandHandler, COMMANDS  # noqa: E402


def _make_handler(tmp_path: pathlib.Path) -> CommandHandler:
    return CommandHandler(base_dir=str(tmp_path))


def _write_json(tmp_path: pathlib.Path, rel_path: str, data: dict) -> None:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Module structure / COMMANDS map
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleStructure(unittest.TestCase):

    def test_A1_commands_dict_exists(self):
        self.assertIsInstance(COMMANDS, dict)
        self.assertGreater(len(COMMANDS), 0)

    def test_A2_required_commands_present(self):
        required = {"/status", "/golive", "/apy", "/evidence", "/strategies", "/help"}
        self.assertTrue(required.issubset(set(COMMANDS.keys())))

    def test_A3_handler_instantiates(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = CommandHandler(base_dir=tmp)
            self.assertEqual(h.base_dir, tmp)

    def test_A4_handle_method_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = CommandHandler(base_dir=tmp)
            self.assertTrue(callable(h.handle))


# ═══════════════════════════════════════════════════════════════════════════
# Group B — handle() routing
# ═══════════════════════════════════════════════════════════════════════════

class TestHandleRouting(unittest.TestCase):

    def test_B1_empty_command_returns_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h.handle("")
            self.assertIn("Commands", result)

    def test_B2_unknown_command_returns_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h.handle("/unknownxxx")
            self.assertIn("Commands", result)

    def test_B3_help_command_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h.handle("/help")
            self.assertIn("/status", result)
            self.assertIn("/golive", result)

    def test_B4_command_with_arguments_strips_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h.handle("/help extra args")
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)

    def test_B5_handle_returns_string_always(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            for cmd in ["/status", "/golive", "/apy", "/evidence", "/strategies", "/help"]:
                result = h.handle(cmd)
                self.assertIsInstance(result, str, f"Expected str for {cmd}")


# ═══════════════════════════════════════════════════════════════════════════
# Group C — _cmd_system_status
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemStatus(unittest.TestCase):

    def test_C1_status_without_data_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h._cmd_system_status()
            self.assertIn("SPA System Status", result)

    def test_C2_status_reads_done_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "KANBAN.json", {"done_count": 1185, "sprint_completed": "v11.07"})
            h = _make_handler(tp)
            result = h._cmd_system_status()
            self.assertIn("1185", result)

    def test_C3_status_reads_sprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "KANBAN.json", {"done_count": 10, "sprint_completed": "v11.07"})
            h = _make_handler(tp)
            result = h._cmd_system_status()
            self.assertIn("v11.07", result)

    def test_C4_status_includes_paper_trading(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h._cmd_system_status()
            self.assertIn("Paper Trading", result)

    def test_C5_status_reads_pnl_from_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/paper_trading_status.json", {
                "total_capital_usd": 102000,
                "total_pnl_pct": 2.0,
            })
            h = _make_handler(tp)
            result = h._cmd_system_status()
            self.assertIn("102,000", result)


# ═══════════════════════════════════════════════════════════════════════════
# Group D — _cmd_golive_score
# ═══════════════════════════════════════════════════════════════════════════

class TestGoLiveScore(unittest.TestCase):

    def test_D1_golive_returns_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h._cmd_golive_score()
            self.assertIsInstance(result, str)

    def test_D2_golive_fallback_reads_golive_status_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/golive_status.json", {
                "passed": 16,
                "total": 26,
                "ready": False,
            })
            h = _make_handler(tp)
            # Patch golive readiness report import to fail
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                result = h._cmd_golive_score()
            self.assertIn("16", result)

    def test_D3_golive_shows_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/golive_status.json", {"passed": 5, "total": 26, "ready": False})
            h = _make_handler(tp)
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                result = h._cmd_golive_score()
            self.assertIn("NOT READY", result)

    def test_D4_golive_shows_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/golive_status.json", {"passed": 26, "total": 26, "ready": True})
            h = _make_handler(tp)
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                result = h._cmd_golive_score()
            self.assertIn("READY", result)


# ═══════════════════════════════════════════════════════════════════════════
# Group E — _cmd_current_apy
# ═══════════════════════════════════════════════════════════════════════════

class TestCurrentApy(unittest.TestCase):

    def test_E1_apy_no_positions_returns_graceful(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            result = h._cmd_current_apy()
            self.assertIn("APY", result)

    def test_E2_apy_reads_from_status_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/paper_trading_status.json", {
                "positions": [
                    {"protocol_key": "Aave V3", "current_value_usd": 40000, "current_apy": 4.2},
                ]
            })
            h = _make_handler(tp)
            result = h._cmd_current_apy()
            self.assertIn("Aave V3", result)

    def test_E3_apy_includes_weighted_avg(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/paper_trading_status.json", {
                "positions": [
                    {"protocol_key": "Compound", "current_value_usd": 50000, "current_apy": 4.8},
                ]
            })
            h = _make_handler(tp)
            result = h._cmd_current_apy()
            self.assertIn("weighted avg", result)

    def test_E4_apy_falls_back_to_current_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/current_positions.json", {
                "positions": [
                    {"protocol_key": "Morpho", "current_value_usd": 30000, "current_apy": 6.5},
                ]
            })
            h = _make_handler(tp)
            result = h._cmd_current_apy()
            self.assertIn("Morpho", result)


# ═══════════════════════════════════════════════════════════════════════════
# Group F — Other commands + edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestOtherCommands(unittest.TestCase):

    def test_F1_evidence_returns_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            # equity_curve_daily.json as list
            curve = [{"date": f"2026-06-{i:02d}", "equity": 100000} for i in range(1, 12)]
            _write_json(tp, "data/equity_curve_daily.json", curve)
            h = _make_handler(tp)
            result = h._cmd_evidence_progress()
            self.assertIn("11", result)  # 11 days

    def test_F2_strategies_returns_tournament_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/tournament_results.json", {
                "strategies": {
                    "S8": {"sharpe": 2.1, "apy": 0.275},
                    "S9": {"sharpe": 1.3, "apy": 0.058},
                }
            })
            h = _make_handler(tp)
            result = h._cmd_strategy_tournament()
            self.assertIn("Tournament", result)
            self.assertIn("S8", result)

    def test_F3_handle_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = _make_handler(pathlib.Path(tmp))
            for cmd in ["/status", "/golive", "/apy", "/evidence", "/strategies", "/help", "/invalid"]:
                try:
                    result = h.handle(cmd)
                    self.assertIsInstance(result, str)
                except Exception as exc:
                    self.fail(f"handle({cmd!r}) raised: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
