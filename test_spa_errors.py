"""
tests/test_spa_errors.py

Unit tests for spa_core/utils/errors.py — SPA error catalog.

Tests:
  1-5:   SPAError base class — code, details, to_dict, repr, inheritance
  6-9:   GateError — code generation, gate/status attrs, to_dict
  10-12: SourceError — details["source_id"], message, attr
  13-15: ValidationError — field in message, details, attr
  16-17: KANBANError — inherits SPAError, custom code
  18-19: AdapterError — adapter_id in details, message
  20-21: ConfigError — key/reason attrs
  22-23: AtomicWriteError — path attr, code
  24-25: LiveTradingForbiddenError — gate attr, LIVE_TRADING_FORBIDDEN code
  26-27: safe_call — returns default on exception, does not raise
  28-29: require_gate — PASS does not raise, non-PASS raises
  30:    all exception classes are subclasses of SPAError

MP-1382 (v9.98) — stdlib unittest, no external dependencies.
"""

import logging
import sys
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.utils.errors import (
    SPAError,
    GateError,
    SourceError,
    ValidationError,
    KANBANError,
    AdapterError,
    ConfigError,
    AtomicWriteError,
    LiveTradingForbiddenError,
    safe_call,
    require_gate,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SPAError — base class
# ─────────────────────────────────────────────────────────────────────────────

class TestSPAError(unittest.TestCase):

    def test_01_spa_error_is_exception(self):
        err = SPAError("something went wrong")
        self.assertIsInstance(err, Exception)

    def test_02_spa_error_default_code_is_not_empty(self):
        err = SPAError("msg")
        self.assertIsInstance(err.code, str)
        self.assertGreater(len(err.code), 0)

    def test_03_spa_error_custom_code_is_preserved(self):
        err = SPAError("msg", code="MY_CODE")
        self.assertEqual(err.code, "MY_CODE")

    def test_04_spa_error_details_default_is_dict(self):
        err = SPAError("msg")
        self.assertIsInstance(err.details, dict)

    def test_05_spa_error_to_dict_has_required_keys(self):
        err = SPAError("hello", code="TEST_CODE", details={"k": "v"})
        d = err.to_dict()
        self.assertIn("error", d)
        self.assertIn("code", d)
        self.assertIn("message", d)
        self.assertIn("details", d)
        self.assertEqual(d["code"], "TEST_CODE")
        self.assertEqual(d["message"], "hello")
        self.assertEqual(d["details"], {"k": "v"})


# ─────────────────────────────────────────────────────────────────────────────
# 2. GateError
# ─────────────────────────────────────────────────────────────────────────────

class TestGateError(unittest.TestCase):

    def test_06_gate_error_inherits_spa_error(self):
        err = GateError("backtest", "FAIL")
        self.assertIsInstance(err, SPAError)

    def test_07_gate_error_code_includes_gate_and_status(self):
        err = GateError("backtest", "FAIL")
        self.assertIn("BACKTEST", err.code)
        self.assertIn("FAIL", err.code)

    def test_08_gate_error_gate_attr_preserved(self):
        err = GateError("paper_ready", "NOT_READY")
        self.assertEqual(err.gate, "paper_ready")
        self.assertEqual(err.status, "NOT_READY")

    def test_09_gate_error_to_dict_contains_gate_and_status(self):
        err = GateError("live", "BLOCKED")
        d = err.to_dict()
        self.assertEqual(d["details"]["gate"], "live")
        self.assertEqual(d["details"]["status"], "BLOCKED")


# ─────────────────────────────────────────────────────────────────────────────
# 3. SourceError
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceError(unittest.TestCase):

    def test_10_source_error_inherits_spa_error(self):
        err = SourceError("sky_susds", "HTTP 503")
        self.assertIsInstance(err, SPAError)

    def test_11_source_error_source_id_in_details(self):
        err = SourceError("aave_v3_usdc", "timeout")
        self.assertEqual(err.details["source_id"], "aave_v3_usdc")

    def test_12_source_error_message_contains_source_id(self):
        err = SourceError("compound_v3", "bad schema")
        self.assertIn("compound_v3", str(err))


# ─────────────────────────────────────────────────────────────────────────────
# 4. ValidationError
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationError(unittest.TestCase):

    def test_13_validation_error_inherits_spa_error(self):
        err = ValidationError("clean_pct", 1.5, "must be in [0, 1]")
        self.assertIsInstance(err, SPAError)

    def test_14_validation_error_field_in_message(self):
        err = ValidationError("apy", -5, "must be non-negative")
        self.assertIn("apy", str(err))

    def test_15_validation_error_details_has_field_and_value(self):
        err = ValidationError("tvl", 0, "must be > 0")
        self.assertEqual(err.details["field"], "tvl")
        self.assertIn("value", err.details)
        self.assertEqual(err.field, "tvl")
        self.assertEqual(err.value, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. KANBANError
# ─────────────────────────────────────────────────────────────────────────────

class TestKANBANError(unittest.TestCase):

    def test_16_kanban_error_inherits_spa_error(self):
        err = KANBANError("KANBAN parse failed")
        self.assertIsInstance(err, SPAError)

    def test_17_kanban_error_custom_code_preserved(self):
        err = KANBANError("oops", code="KANBAN_PARSE_ERROR")
        self.assertEqual(err.code, "KANBAN_PARSE_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# 6. AdapterError
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterError(unittest.TestCase):

    def test_18_adapter_error_inherits_spa_error(self):
        err = AdapterError("morpho_steakhouse", "missing field")
        self.assertIsInstance(err, SPAError)

    def test_19_adapter_error_adapter_id_in_details_and_message(self):
        err = AdapterError("aave_v3", "timeout after 10s")
        self.assertEqual(err.details["adapter_id"], "aave_v3")
        self.assertIn("aave_v3", str(err))
        self.assertEqual(err.adapter_id, "aave_v3")


# ─────────────────────────────────────────────────────────────────────────────
# 7. ConfigError
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigError(unittest.TestCase):

    def test_20_config_error_inherits_spa_error(self):
        err = ConfigError("GITHUB_PAT_SPA", "not found")
        self.assertIsInstance(err, SPAError)

    def test_21_config_error_key_and_reason_attrs(self):
        err = ConfigError("TELEGRAM_TOKEN", "empty string")
        self.assertEqual(err.key, "TELEGRAM_TOKEN")
        self.assertEqual(err.reason, "empty string")


# ─────────────────────────────────────────────────────────────────────────────
# 8. AtomicWriteError
# ─────────────────────────────────────────────────────────────────────────────

class TestAtomicWriteError(unittest.TestCase):

    def test_22_atomic_write_error_inherits_spa_error(self):
        err = AtomicWriteError("data/trades.json", "permission denied")
        self.assertIsInstance(err, SPAError)

    def test_23_atomic_write_error_path_attr(self):
        err = AtomicWriteError("data/equity_curve_daily.json", "disk full")
        self.assertEqual(err.path, "data/equity_curve_daily.json")
        self.assertEqual(err.code, "ATOMIC_WRITE_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# 9. LiveTradingForbiddenError
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveTradingForbiddenError(unittest.TestCase):

    def test_24_live_trading_forbidden_inherits_spa_error(self):
        err = LiveTradingForbiddenError("backtest")
        self.assertIsInstance(err, SPAError)

    def test_25_live_trading_forbidden_code_and_gate(self):
        err = LiveTradingForbiddenError("paper_ready")
        self.assertEqual(err.code, "LIVE_TRADING_FORBIDDEN")
        self.assertEqual(err.gate, "paper_ready")
        self.assertIn("paper_ready", str(err))


# ─────────────────────────────────────────────────────────────────────────────
# 10. safe_call
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeCall(unittest.TestCase):

    def test_26_safe_call_returns_default_on_exception(self):
        def boom():
            raise RuntimeError("kaboom")

        result = safe_call(boom, default="fallback", log_error=False)
        self.assertEqual(result, "fallback")

    def test_27_safe_call_does_not_raise(self):
        def boom():
            raise ValueError("nope")

        try:
            safe_call(boom, default=None, log_error=False)
        except Exception as e:
            self.fail(f"safe_call raised unexpectedly: {e}")

    def test_27b_safe_call_returns_func_result_on_success(self):
        def good():
            return 42

        result = safe_call(good, default=0, log_error=False)
        self.assertEqual(result, 42)

    def test_27c_safe_call_passes_args_to_func(self):
        def add(a, b):
            return a + b

        result = safe_call(add, 3, 7, default=-1, log_error=False)
        self.assertEqual(result, 10)

    def test_27d_safe_call_none_default_when_omitted(self):
        def boom():
            raise KeyError("x")

        result = safe_call(boom, log_error=False)
        self.assertIsNone(result)

    def test_27e_safe_call_logs_warning_by_default(self):
        """safe_call emits at least one log record when log_error=True."""
        import logging

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = Capture()
        logging.getLogger("spa.safe_call").addHandler(handler)
        try:
            safe_call(lambda: (_ for _ in ()).throw(RuntimeError("x")),
                      default=None, log_error=True)
        finally:
            logging.getLogger("spa.safe_call").removeHandler(handler)

        self.assertGreater(len(records), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 11. require_gate
# ─────────────────────────────────────────────────────────────────────────────

class TestRequireGate(unittest.TestCase):

    def test_28_require_gate_pass_does_not_raise(self):
        try:
            require_gate("PASS", "backtest")
        except Exception as e:
            self.fail(f"require_gate('PASS', ...) raised: {e}")

    def test_29_require_gate_not_ready_raises_live_trading_forbidden(self):
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("NOT_READY", "paper")

    def test_29b_require_gate_fail_raises(self):
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("FAIL", "backtest")

    def test_29c_require_gate_unknown_raises(self):
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("UNKNOWN", "live")

    def test_29d_require_gate_blocked_raises(self):
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("BLOCKED", "live")


# ─────────────────────────────────────────────────────────────────────────────
# 12. All exception classes are subclasses of SPAError
# ─────────────────────────────────────────────────────────────────────────────

class TestInheritanceContract(unittest.TestCase):

    def test_30_all_domain_exceptions_inherit_from_spa_error(self):
        domain_exceptions = [
            GateError("x", "y"),
            SourceError("x", "y"),
            ValidationError("x", 0, "y"),
            KANBANError("x"),
            AdapterError("x", "y"),
            ConfigError("x", "y"),
            AtomicWriteError("x", "y"),
            LiveTradingForbiddenError("x"),
        ]
        for exc in domain_exceptions:
            with self.subTest(exc=type(exc).__name__):
                self.assertIsInstance(exc, SPAError)
                self.assertIsInstance(exc, Exception)
                # Every domain exception must have a non-empty code
                self.assertIsInstance(exc.code, str)
                self.assertGreater(len(exc.code), 0)
                # to_dict() must return a dict with the required keys
                d = exc.to_dict()
                for key in ("error", "code", "message", "details"):
                    self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
