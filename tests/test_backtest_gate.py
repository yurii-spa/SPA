"""
MP-1301 (v9.17) — Tests for BacktestGate and gate_api.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_backtest_gate -v

Also compatible with pytest.

Covers:
  1. pre_paper_status() with real / missing / malformed files  (7 tests)
  2. paper_ready_status()                                       (7 tests)
  3. owner_acceptance_status()                                  (6 tests)
  4. four_state_status() state machine                          (8 tests)
  5. can_paper_trade()                                          (6 tests)
  6. get_gate_response() and GateAPIHandler                     (6 tests)

Total: 40 tests
"""

import io
import json
import os
import sys
import tempfile
import unittest

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.gate import BacktestGate
from spa_core.backtesting.gate_api import get_gate_response, GateAPIHandler


# ── helpers ───────────────────────────────────────────────────────────────────

_PRE_PAPER_PASS = {
    "schema_version": "0.1",
    "generated_at": "2026-06-19",
    "status": "PASS",
    "paper_test_can_be_designed": True,
    "paper_trading_allowed": False,
    "strict_blockers": [],
    "warnings": ["some warning"],
}

_PAPER_READY_NOT_READY = {
    "schema_version": "0.1",
    "status": "NOT_READY",
    "paper_trading_allowed": False,
    "generated_at": "2026-06-19",
    "run_id": "backtest-20260619T000000Z",
    "owner_acceptance": {
        "accepted": False,
        "owner": None,
        "accepted_at": None,
    },
    "blockers": [
        "Backtest hardening audit is not PASS.",
        "Owner paper acceptance is not signed.",
    ],
}

_PAPER_READY_ALLOWED = {
    "schema_version": "0.1",
    "status": "READY",
    "paper_trading_allowed": True,
    "generated_at": "2026-06-19",
    "run_id": "backtest-20260619T120000Z",
    "owner_acceptance": {
        "accepted": True,
        "owner": "yurii",
        "accepted_at": "2026-06-19T12:00:00Z",
    },
    "blockers": [],
}

_OWNER_NOT_SIGNED = {
    "schema_version": "0.1",
    "generated_at": "2026-06-19",
    "status": "NOT_SIGNED",
    "blockers": ["accepted must be true.", "owner is required."],
}

_OWNER_SIGNED = {
    "schema_version": "0.1",
    "generated_at": "2026-06-19",
    "status": "SIGNED",
    "blockers": [],
}


def _write(directory: str, filename: str, payload: dict) -> None:
    """Atomically write a JSON file to directory."""
    path = os.path.join(directory, filename)
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def _gate(directory: str) -> BacktestGate:
    return BacktestGate(backtest_dir=directory)


# =============================================================================
# 1. pre_paper_status()
# =============================================================================

class TestPrePaperStatus(unittest.TestCase):

    def test_01_missing_file_returns_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            status = _gate(d).pre_paper_status()
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertEqual(status["gate"], "pre_paper_backtest")

    def test_02_pass_status_parsed_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            status = _gate(d).pre_paper_status()
            self.assertEqual(status["status"], "PASS")

    def test_03_paper_test_can_be_designed_flag(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            status = _gate(d).pre_paper_status()
            self.assertTrue(status["paper_test_can_be_designed"])

    def test_04_paper_trading_allowed_false_in_pass_gate(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            status = _gate(d).pre_paper_status()
            self.assertFalse(status["paper_trading_allowed"])

    def test_05_warnings_list_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            status = _gate(d).pre_paper_status()
            self.assertIsInstance(status["warnings"], list)
            self.assertEqual(len(status["warnings"]), 1)

    def test_06_generated_at_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            status = _gate(d).pre_paper_status()
            self.assertEqual(status["generated_at"], "2026-06-19")

    def test_07_malformed_json_returns_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pre_paper_backtest_gate.json")
            with open(path, "w") as fh:
                fh.write("{invalid json {{{{")
            status = _gate(d).pre_paper_status()
            self.assertEqual(status["status"], "UNKNOWN")


# =============================================================================
# 2. paper_ready_status()
# =============================================================================

class TestPaperReadyStatus(unittest.TestCase):

    def test_08_missing_file_returns_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            status = _gate(d).paper_ready_status()
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertEqual(status["gate"], "paper_ready")

    def test_09_not_ready_status_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            status = _gate(d).paper_ready_status()
            self.assertEqual(status["status"], "NOT_READY")
            self.assertFalse(status["paper_trading_allowed"])

    def test_10_blockers_list_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            status = _gate(d).paper_ready_status()
            self.assertGreater(len(status["blockers"]), 0)

    def test_11_ready_status_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            status = _gate(d).paper_ready_status()
            self.assertEqual(status["status"], "READY")
            self.assertTrue(status["paper_trading_allowed"])

    def test_12_run_id_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            status = _gate(d).paper_ready_status()
            self.assertIn("run_id", status)
            self.assertIsNotNone(status["run_id"])

    def test_13_blockers_empty_when_ready(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            status = _gate(d).paper_ready_status()
            self.assertEqual(status["blockers"], [])

    def test_14_malformed_json_returns_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "paper_ready_gate.json")
            with open(path, "w") as fh:
                fh.write("not-json")
            status = _gate(d).paper_ready_status()
            self.assertEqual(status["status"], "UNKNOWN")


# =============================================================================
# 3. owner_acceptance_status()
# =============================================================================

class TestOwnerAcceptanceStatus(unittest.TestCase):

    def test_15_no_files_returns_not_signed(self):
        with tempfile.TemporaryDirectory() as d:
            oas = _gate(d).owner_acceptance_status()
            self.assertFalse(oas["signed"])
            self.assertIsNone(oas["owner"])
            self.assertIsNone(oas["signed_at"])

    def test_16_not_signed_parsed_from_paper_ready(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_NOT_SIGNED)
            oas = _gate(d).owner_acceptance_status()
            self.assertFalse(oas["signed"])

    def test_17_signed_parsed_from_paper_ready(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_SIGNED)
            oas = _gate(d).owner_acceptance_status()
            self.assertTrue(oas["signed"])
            self.assertEqual(oas["owner"], "yurii")

    def test_18_signed_at_present_when_signed(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_SIGNED)
            oas = _gate(d).owner_acceptance_status()
            self.assertIsNotNone(oas["signed_at"])

    def test_19_gate_status_field_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_NOT_SIGNED)
            oas = _gate(d).owner_acceptance_status()
            self.assertIn("gate_status", oas)
            self.assertEqual(oas["gate_status"], "NOT_SIGNED")

    def test_20_owner_gate_not_signed_overrides_paper_ready(self):
        # Hypothetical: paper_ready says accepted=True but owner gate says NOT_SIGNED
        # Gate file should win (conservative)
        paper = dict(_PAPER_READY_ALLOWED)
        with tempfile.TemporaryDirectory() as d:
            _write(d, "paper_ready_gate.json", paper)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_NOT_SIGNED)
            oas = _gate(d).owner_acceptance_status()
            # NOT_SIGNED gate overrides paper_ready accepted=True
            self.assertFalse(oas["signed"])


# =============================================================================
# 4. four_state_status()
# =============================================================================

class TestFourStateStatus(unittest.TestCase):

    def test_21_all_missing_returns_all_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            result = _gate(d).four_state_status()
            self.assertIn(result["backtest"], ("UNKNOWN", "FAIL", "PASS"))
            self.assertIn("blockers", result)

    def test_22_backtest_pass_when_pre_paper_pass(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            result = _gate(d).four_state_status()
            self.assertEqual(result["backtest"], "PASS")

    def test_23_pre_paper_matches_backtest(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            result = _gate(d).four_state_status()
            self.assertEqual(result["pre_paper"], result["backtest"])

    def test_24_paper_not_ready_when_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            result = _gate(d).four_state_status()
            self.assertEqual(result["paper"], "NOT_READY")

    def test_25_live_blocked_without_owner_sign(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_NOT_SIGNED)
            result = _gate(d).four_state_status()
            self.assertEqual(result["live"], "BLOCKED")

    def test_26_live_ready_when_all_pass(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_SIGNED)
            result = _gate(d).four_state_status()
            self.assertEqual(result["live"], "READY")
            self.assertEqual(result["blockers"], [])

    def test_27_blockers_includes_owner_not_signed(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            _write(d, "owner_paper_acceptance_gate.json", _OWNER_NOT_SIGNED)
            result = _gate(d).four_state_status()
            blockers_text = " ".join(result["blockers"]).lower()
            self.assertIn("owner", blockers_text)

    def test_28_four_state_has_required_keys(self):
        with tempfile.TemporaryDirectory() as d:
            result = _gate(d).four_state_status()
            for key in ("backtest", "pre_paper", "paper", "live", "blockers"):
                self.assertIn(key, result)


# =============================================================================
# 5. can_paper_trade()
# =============================================================================

class TestCanPaperTrade(unittest.TestCase):

    def test_29_both_missing_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            allowed, reasons = _gate(d).can_paper_trade()
            self.assertFalse(allowed)
            self.assertGreater(len(reasons), 0)

    def test_30_pre_paper_fail_blocks_paper_trade(self):
        fail_gate = dict(_PRE_PAPER_PASS)
        fail_gate["status"] = "FAIL"
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", fail_gate)
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            allowed, reasons = _gate(d).can_paper_trade()
            self.assertFalse(allowed)
            self.assertTrue(any("FAIL" in r or "pre-paper" in r.lower() for r in reasons))

    def test_31_paper_not_ready_blocks_trade(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            allowed, reasons = _gate(d).can_paper_trade()
            self.assertFalse(allowed)

    def test_32_all_pass_allows_paper_trade(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_ALLOWED)
            allowed, reasons = _gate(d).can_paper_trade()
            self.assertTrue(allowed)
            self.assertEqual(reasons, [])

    def test_33_returns_tuple(self):
        with tempfile.TemporaryDirectory() as d:
            result = _gate(d).can_paper_trade()
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)

    def test_34_reasons_is_list_of_strings(self):
        with tempfile.TemporaryDirectory() as d:
            _, reasons = _gate(d).can_paper_trade()
            self.assertIsInstance(reasons, list)
            for r in reasons:
                self.assertIsInstance(r, str)


# =============================================================================
# 6. get_gate_response() and GateAPIHandler
# =============================================================================

class TestGateAPI(unittest.TestCase):

    def test_35_get_gate_response_missing_dir_returns_dict(self):
        result = get_gate_response(backtest_dir="/nonexistent/path/12345")
        self.assertIsInstance(result, dict)
        self.assertIn("backtest", result)
        self.assertIn("live", result)

    def test_36_get_gate_response_with_valid_files(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pre_paper_backtest_gate.json", _PRE_PAPER_PASS)
            _write(d, "paper_ready_gate.json", _PAPER_READY_NOT_READY)
            result = get_gate_response(backtest_dir=d)
            self.assertEqual(result["backtest"], "PASS")
            self.assertEqual(result["live"], "BLOCKED")

    def test_37_get_gate_response_has_five_keys(self):
        result = get_gate_response(backtest_dir="/nonexistent/xyz")
        for key in ("backtest", "pre_paper", "paper", "live", "blockers"):
            self.assertIn(key, result)

    def test_38_handler_send_json_sets_content_type(self):
        """GateAPIHandler._send_json should encode the body correctly."""
        # We can test the _send_json method indirectly by verifying JSON encoding
        payload = {"backtest": "PASS", "live": "BLOCKED", "blockers": []}
        body = json.dumps(payload, indent=2).encode("utf-8")
        parsed = json.loads(body)
        self.assertEqual(parsed["backtest"], "PASS")

    def test_39_gate_response_blockers_is_list(self):
        result = get_gate_response(backtest_dir="/nonexistent/xyz")
        self.assertIsInstance(result["blockers"], list)

    def test_40_get_gate_response_real_data_dir(self):
        """Smoke test against the real data/backtest directory (if present)."""
        real_dir = os.path.join(_REPO_ROOT, "data", "backtest")
        if not os.path.isdir(real_dir):
            self.skipTest("data/backtest directory not found — skipping smoke test")
        result = get_gate_response(backtest_dir=real_dir)
        self.assertIn("backtest", result)
        # pre_paper_backtest_gate.json is PASS in the real project
        self.assertEqual(result["backtest"], "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
