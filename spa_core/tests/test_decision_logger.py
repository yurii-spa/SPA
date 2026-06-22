"""
spa_core/tests/test_decision_logger.py

Tests for DecisionLogger (spa_core/agents/decision_logger.py).

MP-1461 (v10.77) — Sprint 3: agents/ coverage.

Approach: patch spa_core.agents.decision_logger.get_connection at the point of
use (unittest.mock.patch) so the module-level import is properly intercepted.

Run:
    python3 -m unittest spa_core.tests.test_decision_logger -v
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Bootstrap database mock before importing DecisionLogger ───────────────────

_mock_db = types.ModuleType("database")
_mock_init_db = types.ModuleType("database.init_db")
_mock_init_db.get_db_path = lambda: "/tmp/test_spa.db"
_mock_init_db.get_connection = MagicMock()  # overridden per test
_mock_db.init_db = _mock_init_db
sys.modules.setdefault("database", _mock_db)
sys.modules.setdefault("database.init_db", _mock_init_db)

from spa_core.agents.decision_logger import DecisionLogger, POLICY_VERSION


# ─── Context-manager mock connection factory ──────────────────────────────────

def _make_mock_conn(lastrowid=1):
    """Return a context-manager compatible DB connection mock."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.lastrowid = lastrowid
    cursor.fetchall.return_value = []
    cursor.description = [("col",)]
    conn.execute.return_value = cursor
    conn.__enter__ = lambda self: self
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ─── DecisionLogger Init Tests ────────────────────────────────────────────────

class TestDecisionLoggerInit(unittest.TestCase):

    def test_default_agent_name(self):
        dl = DecisionLogger()
        self.assertEqual(dl.agent_name, "UnknownAgent")

    def test_custom_agent_name(self):
        dl = DecisionLogger(agent_name="TraderAgent")
        self.assertEqual(dl.agent_name, "TraderAgent")

    def test_default_strategy_id(self):
        dl = DecisionLogger()
        self.assertEqual(dl.strategy_id, "paper-v1")

    def test_custom_strategy_id(self):
        dl = DecisionLogger(strategy_id="s1_conservative")
        self.assertEqual(dl.strategy_id, "s1_conservative")

    def test_db_path_stored(self):
        dl = DecisionLogger(db_path="/tmp/test.db")
        self.assertEqual(str(dl.db_path), "/tmp/test.db")

    def test_db_path_from_function_fallback(self):
        dl = DecisionLogger()
        self.assertIsNotNone(dl.db_path)

    def test_policy_version_constant(self):
        self.assertIsInstance(POLICY_VERSION, str)
        self.assertGreater(len(POLICY_VERSION), 0)


# ─── DecisionLogger.log() Tests ───────────────────────────────────────────────

_DL_MOD = "spa_core.agents.decision_logger"


class TestDecisionLoggerLog(unittest.TestCase):

    def _make_dl(self, lastrowid=1):
        conn = _make_mock_conn(lastrowid=lastrowid)
        dl = DecisionLogger(db_path="/tmp/test.db", agent_name="TestAgent")
        return dl, conn

    def test_log_returns_row_id(self):
        dl, conn = self._make_dl(lastrowid=7)
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log("ALLOCATE", "Test reasoning")
        self.assertEqual(result, 7)

    def test_log_never_raises_on_db_error(self):
        dl, _ = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", side_effect=RuntimeError("DB down")):
            result = dl.log("ALLOCATE", "reasoning")
        self.assertEqual(result, -1)

    def test_log_with_protocol_key(self):
        dl, conn = self._make_dl(lastrowid=3)
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log("ALLOCATE", "OK", protocol_key="aave-v3")
        self.assertEqual(result, 3)

    def test_log_with_all_params(self):
        dl, conn = self._make_dl(lastrowid=5)
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log(
                "ALLOCATE",
                "Good APY",
                protocol_key="morpho",
                amount_usd=40_000.0,
                data_snapshot={"apy": 6.5},
                risk_check_result="approved",
                outcome="success",
            )
        self.assertEqual(result, 5)

    def test_log_calls_execute_with_insert(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            dl.log("PASS", "Too low APY")
        # verify INSERT was called
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        self.assertIn("INSERT", sql)

    def test_log_params_include_agent_name(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            dl.log("HOLD", "No action needed")
        params = conn.execute.call_args[0][1]
        self.assertIn("TestAgent", params)

    def test_log_params_include_policy_version(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            dl.log("ALLOCATE", "reasons")
        params = conn.execute.call_args[0][1]
        self.assertIn(POLICY_VERSION, params)

    def test_log_params_include_decision_type(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            dl.log("REBALANCE", "drift detected")
        params = conn.execute.call_args[0][1]
        self.assertIn("REBALANCE", params)

    def test_log_snapshot_serialized_to_str(self):
        dl, conn = self._make_dl()
        snapshot = {"protocol": "aave", "apy": 5.0}
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            dl.log("ALLOCATE", "ok", data_snapshot=snapshot)
        params = conn.execute.call_args[0][1]
        # snapshot should be a JSON string in params
        snapshot_param = [p for p in params if isinstance(p, str) and "aave" in p]
        self.assertGreater(len(snapshot_param), 0)


# ─── DecisionLogger typed methods ─────────────────────────────────────────────

class TestDecisionLoggerTypedMethods(unittest.TestCase):

    def _make_dl(self):
        conn = _make_mock_conn(lastrowid=1)
        dl = DecisionLogger(db_path="/tmp/test.db", agent_name="TraderAgent")
        return dl, conn

    def test_log_allocate_returns_positive_id(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log_allocate("aave-v3", 40_000.0, 4.2, "T1", "APY OK",
                                     risk_approved=True)
        self.assertGreater(result, 0)

    def test_log_allocate_risk_rejected(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log_allocate("euler-v2", 10_000.0, 8.0, "T2",
                                     "High APY", risk_approved=False)
        self.assertGreater(result, 0)

    def test_log_pass_returns_positive_id(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log_pass("euler-v2", "APY too low")
        self.assertGreater(result, 0)

    def test_log_pass_with_optional_apy(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.log_pass("euler-v2", "APY too low", apy=0.5)
        self.assertGreater(result, 0)

    def test_log_rebalance_returns_positive_id(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            # log_rebalance(from_protocol, to_protocol, amount_usd, reasoning)
            result = dl.log_rebalance("aave-v3", "morpho-blue", 5_000.0, "APY gap")
        self.assertGreater(result, 0)

    def test_log_alert_returns_positive_id(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            # log_alert(alert_type, severity, details)
            result = dl.log_alert("TVL_DROP", "WARNING", {"message": "TVL -35%"})
        self.assertGreater(result, 0)

    def test_log_hold_returns_positive_id(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            # log_hold(protocol_key, reasoning, current_apy)
            result = dl.log_hold("aave-v3", "No rebalance needed", 4.2)
        self.assertGreater(result, 0)

    def test_log_allocate_never_raises(self):
        dl, _ = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", side_effect=RuntimeError("crash")):
            result = dl.log_allocate("aave-v3", 40_000.0, 4.2, "T1", "test",
                                     risk_approved=True)
        self.assertEqual(result, -1)

    def test_log_pass_never_raises(self):
        dl, _ = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", side_effect=RuntimeError("crash")):
            result = dl.log_pass("aave-v3", "reason")
        self.assertEqual(result, -1)


# ─── DecisionLogger.get_recent / get_by_protocol ─────────────────────────────

class TestDecisionLoggerQueries(unittest.TestCase):

    def _make_dl(self):
        conn = _make_mock_conn()
        conn.execute.return_value.fetchall.return_value = []
        conn.execute.return_value.description = [("col",)]
        dl = DecisionLogger(db_path="/tmp/test.db")
        return dl, conn

    def test_get_recent_returns_list(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.get_recent()
        self.assertIsInstance(result, list)

    def test_get_recent_never_raises(self):
        dl, _ = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", side_effect=RuntimeError("db")):
            result = dl.get_recent()
        self.assertIsInstance(result, list)

    def test_get_by_protocol_returns_list(self):
        dl, conn = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", return_value=conn):
            result = dl.get_by_protocol("aave-v3")
        self.assertIsInstance(result, list)

    def test_get_by_protocol_never_raises(self):
        dl, _ = self._make_dl()
        with patch(f"{_DL_MOD}.get_connection", side_effect=RuntimeError("db")):
            result = dl.get_by_protocol("aave-v3")
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
