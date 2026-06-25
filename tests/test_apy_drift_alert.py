#!/usr/bin/env python3
"""
tests/test_apy_drift_alert.py — MP-1491 (Sprint v11.07)

Unit tests for spa_core/alerts/apy_drift_alert.py
30 tests, pure stdlib, offline, no Telegram network calls.

Groups:
    A. Module structure and imports          (4 tests)
    B. _get_apy_history                      (4 tests)
    C. check_drift — basic threshold logic   (6 tests)
    D. check_drift — severity routing        (4 tests)
    E. run_all_strategies                    (5 tests)
    F. Telegram send (mocked)                (4 tests)
    G. save / to_dict                        (3 tests)
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

# ---------------------------------------------------------------------------
# Patch Telegram before any import of alert modules.
#
# This patch lives in sys.modules; without a matching stop it would leak a
# MagicMock telegram_client into every test that runs after this module (e.g.
# test_protocol_report's send_protocol_report would see a send_message that
# always returns True). setUpModule/tearDownModule (honoured by both unittest
# and pytest) scope the patch to this module's run only, restoring the real
# telegram_client afterwards.
# ---------------------------------------------------------------------------
_tg_patcher = unittest.mock.patch.dict(
    "sys.modules",
    {
        "spa_core.alerts.telegram_client": unittest.mock.MagicMock(
            send_message=unittest.mock.MagicMock(return_value=True),
        ),
    },
)


def setUpModule():
    """Start the sys.modules patch before this module's tests run."""
    _tg_patcher.start()


def tearDownModule():
    """Stop the patch so the real telegram_client is restored for the rest of
    the test session (prevents cross-module pollution)."""
    _tg_patcher.stop()


# Import under the patch so module-level references resolve against the mock,
# then stop it; setUpModule re-applies it for the duration of the run.
_tg_patcher.start()
from spa_core.alerts.apy_drift_alert import (  # noqa: E402
    APY_DRIFT_THRESHOLD,
    LOOKBACK_DAYS,
    APYDriftAlert,
)
_tg_patcher.stop()


def _make_alert(tmp_path: pathlib.Path) -> APYDriftAlert:
    return APYDriftAlert(base_dir=str(tmp_path))


def _write_history(tmp_path: pathlib.Path, strategy_id: str, history: list) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hist_file = data_dir / "strategy_apy_history.json"
    existing = json.loads(hist_file.read_text()) if hist_file.exists() else {}
    existing[strategy_id] = {"apy_history": history}
    hist_file.write_text(json.dumps(existing))


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Module structure
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleStructure(unittest.TestCase):

    def test_A1_constants_exist(self):
        self.assertAlmostEqual(APY_DRIFT_THRESHOLD, 0.20)
        self.assertEqual(LOOKBACK_DAYS, 7)

    def test_A2_class_inherits_base_analytics(self):
        from spa_core.base import BaseAnalytics
        self.assertTrue(issubclass(APYDriftAlert, BaseAnalytics))

    def test_A3_output_path_defined(self):
        self.assertIn("apy_drift", APYDriftAlert.OUTPUT_PATH)

    def test_A4_default_data_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = APYDriftAlert(base_dir=tmp)
            d = a.to_dict()
            self.assertIn("alerts", d)
            self.assertIn("last_check", d)
            self.assertIn("strategies", d)
            self.assertIsInstance(d["alerts"], list)


# ═══════════════════════════════════════════════════════════════════════════
# Group B — _get_apy_history
# ═══════════════════════════════════════════════════════════════════════════

class TestGetApyHistory(unittest.TestCase):

    def test_B1_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _make_alert(pathlib.Path(tmp))
            self.assertEqual(a._get_apy_history("S0"), [])

    def test_B2_returns_correct_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S1", [0.04, 0.045, 0.05, 0.048])
            a = _make_alert(tp)
            result = a._get_apy_history("S1")
            self.assertEqual(result, [0.04, 0.045, 0.05, 0.048])

    def test_B3_missing_strategy_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.05, 0.05, 0.05])
            a = _make_alert(tp)
            self.assertEqual(a._get_apy_history("S99"), [])

    def test_B4_filters_none_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            data_dir = tp / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            hist = data_dir / "strategy_apy_history.json"
            hist.write_text(json.dumps({"S2": {"apy_history": [0.05, None, 0.04]}}))
            a = _make_alert(tp)
            result = a._get_apy_history("S2")
            self.assertEqual(result, [0.05, 0.04])


# ═══════════════════════════════════════════════════════════════════════════
# Group C — check_drift basic threshold logic
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckDriftBasic(unittest.TestCase):

    def test_C1_insufficient_history_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.05, 0.05])  # < 3
            a = _make_alert(tp)
            self.assertIsNone(a.check_drift("S0", 0.03))

    def test_C2_no_drift_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.05] * 7)
            a = _make_alert(tp)
            result = a.check_drift("S0", 0.049)  # <20% drift
            self.assertIsNone(result)

    def test_C3_significant_drift_returns_alert_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.05] * 7)
            a = _make_alert(tp)
            result = a.check_drift("S0", 0.03)  # 40% drop
            self.assertIsNotNone(result)
            self.assertIsInstance(result, dict)

    def test_C4_alert_contains_correct_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S3", [0.06] * 5)
            a = _make_alert(tp)
            result = a.check_drift("S3", 0.03)
            self.assertIsNotNone(result)
            self.assertEqual(result["strategy"], "S3")

    def test_C5_alert_contains_drift_pct(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S4", [0.10] * 7)
            a = _make_alert(tp)
            result = a.check_drift("S4", 0.05)  # 50% drop
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result["drift_pct"], 50.0, places=1)

    def test_C6_zero_avg_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S5", [0.0] * 5)
            a = _make_alert(tp)
            self.assertIsNone(a.check_drift("S5", 0.0))


# ═══════════════════════════════════════════════════════════════════════════
# Group D — check_drift severity routing
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckDriftSeverity(unittest.TestCase):

    def test_D1_medium_severity_between_20_and_40_pct(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S6", [0.10] * 7)
            a = _make_alert(tp)
            result = a.check_drift("S6", 0.075)  # 25% drop → MEDIUM
            self.assertIsNotNone(result)
            self.assertEqual(result["severity"], "MEDIUM")

    def test_D2_high_severity_above_40_pct(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S7", [0.10] * 7)
            a = _make_alert(tp)
            result = a.check_drift("S7", 0.05)  # 50% drop → HIGH
            self.assertIsNotNone(result)
            self.assertEqual(result["severity"], "HIGH")

    def test_D3_alert_contains_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S8", [0.08] * 5)
            a = _make_alert(tp)
            result = a.check_drift("S8", 0.04)
            self.assertIsNotNone(result)
            self.assertIn("timestamp", result)
            self.assertIsInstance(result["timestamp"], str)

    def test_D4_alert_contains_all_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S9", [0.06] * 5)
            a = _make_alert(tp)
            result = a.check_drift("S9", 0.03)
            required = {"strategy", "current_apy", "avg_7d_apy", "drift_pct", "severity", "timestamp"}
            self.assertEqual(set(result.keys()), required)


# ═══════════════════════════════════════════════════════════════════════════
# Group E — run_all_strategies
# ═══════════════════════════════════════════════════════════════════════════

class TestRunAllStrategies(unittest.TestCase):

    def test_E1_returns_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            result = a.run_all_strategies({})
            self.assertIsInstance(result, list)

    def test_E2_no_alerts_when_no_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            result = a.run_all_strategies({"S0": 0.05, "S1": 0.04})
            self.assertEqual(result, [])

    def test_E3_returns_triggered_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.10] * 7)
            a = _make_alert(tp)
            result = a.run_all_strategies({"S0": 0.05})  # 50% drop
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["strategy"], "S0")

    def test_E4_updates_last_check_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            a.run_all_strategies({})
            self.assertIsNotNone(a._data["last_check"])

    def test_E5_saves_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            a.run_all_strategies({})
            out = tp / APYDriftAlert.OUTPUT_PATH
            self.assertTrue(out.exists())


# ═══════════════════════════════════════════════════════════════════════════
# Group F — Telegram send (mocked)
# ═══════════════════════════════════════════════════════════════════════════

class TestTelegramSend(unittest.TestCase):

    def test_F1_send_telegram_alert_called_on_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.10] * 7)
            a = _make_alert(tp)
            with unittest.mock.patch.object(a, "_send_telegram_alert", return_value=True) as mock_send:
                a.run_all_strategies({"S0": 0.05})
                mock_send.assert_called_once()

    def test_F2_send_not_called_when_no_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_history(tp, "S0", [0.05] * 7)
            a = _make_alert(tp)
            with unittest.mock.patch.object(a, "_send_telegram_alert", return_value=True) as mock_send:
                a.run_all_strategies({"S0": 0.049})
                mock_send.assert_not_called()

    def test_F3_send_telegram_returns_false_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            alert = {
                "strategy": "S0",
                "current_apy": 0.03,
                "avg_7d_apy": 0.05,
                "drift_pct": 40.0,
                "severity": "HIGH",
                "timestamp": "2026-06-20T08:00:00",
            }
            with unittest.mock.patch.dict("sys.modules", {"spa_core.alerts.telegram_client": None}):
                result = a._send_telegram_alert(alert)
                self.assertFalse(result)

    def test_F4_send_telegram_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            alert = {
                "strategy": "S1",
                "current_apy": 0.02,
                "avg_7d_apy": 0.05,
                "drift_pct": 60.0,
                "severity": "HIGH",
                "timestamp": "2026-06-20T08:00:00",
            }
            # Should never raise, even if telegram is broken
            try:
                a._send_telegram_alert(alert)
            except Exception as exc:
                self.fail(f"_send_telegram_alert raised: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# Group G — save / to_dict
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveToDict(unittest.TestCase):

    def test_G1_to_dict_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = APYDriftAlert(base_dir=tmp)
            self.assertIsInstance(a.to_dict(), dict)

    def test_G2_save_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            a = _make_alert(tp)
            a.run_all_strategies({})
            out = tp / APYDriftAlert.OUTPUT_PATH
            loaded = json.loads(out.read_text())
            self.assertIn("alerts", loaded)

    def test_G3_lookback_uses_last_7_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            # 10-entry history: first 3 are very low, last 7 are 0.10
            _write_history(tp, "S0", [0.001, 0.001, 0.001, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10])
            a = _make_alert(tp)
            # current APY 0.08 → only 20% drop from 7d avg of 0.10 — borderline
            result = a.check_drift("S0", 0.079)
            # 0.10 * 0.20 = 0.02 → avg - current = 0.021 > threshold
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
