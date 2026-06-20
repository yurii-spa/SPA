"""
tests/test_error_code_reference.py

MP-1434 (v10.50) — Error Code Reference comprehensive tests.

20 tests covering:
  - All SPAError subclasses import correctly
  - safe_call() absorbs exceptions, returns default
  - require_gate() raises LiveTradingForbiddenError on non-PASS
  - LiveTradingForbiddenError is subclass of SPAError
  - Error codes are non-None for migrated modules
  - docs/ERROR_CODE_REFERENCE.md exists and contains the table
  - Error hierarchy and to_dict() serialization
  - safe_call() with keyword args
  - GateError auto-generates correct code
  - SourceError, AdapterError, ConfigError carry structured details
  - NOT_INITIALIZED code for analytics modules
  - SPAError is Exception subclass
  - ValidationError, KANBANError, AtomicWriteError, AllocationError, RegistryError
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure project root is on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.utils.errors import (
    AdapterError,
    AllocationError,
    AtomicWriteError,
    ConfigError,
    GateError,
    KANBANError,
    LiveTradingForbiddenError,
    RegistryError,
    RiskPolicyError,
    SPAError,
    SourceError,
    ValidationError,
    require_gate,
    safe_call,
)


# ─────────────────────────────────────────────────────────────────────────────
# T01: All SPAError subclasses import without error
# ─────────────────────────────────────────────────────────────────────────────
class TestImports(unittest.TestCase):
    """T01 — all error classes importable."""

    def test_t01_all_classes_importable(self):
        classes = [
            SPAError, GateError, SourceError, ValidationError, KANBANError,
            AdapterError, ConfigError, AtomicWriteError, RegistryError,
            RiskPolicyError, AllocationError, LiveTradingForbiddenError,
        ]
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, Exception))


# ─────────────────────────────────────────────────────────────────────────────
# T02: SPAError is subclass of Exception
# ─────────────────────────────────────────────────────────────────────────────
class TestSPAErrorBase(unittest.TestCase):

    def test_t02_spaerror_is_exception(self):
        self.assertTrue(issubclass(SPAError, Exception))

    def test_t03_all_subclasses_are_spaerror(self):
        subclasses = [
            GateError, SourceError, ValidationError, KANBANError,
            AdapterError, ConfigError, AtomicWriteError, RegistryError,
            RiskPolicyError, AllocationError, LiveTradingForbiddenError,
        ]
        for cls in subclasses:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, SPAError), f"{cls.__name__} must be SPAError subclass")

    def test_t04_spaerror_default_code(self):
        err = SPAError("test message")
        self.assertEqual(err.code, "SPA_UNKNOWN")

    def test_t05_spaerror_custom_code_not_none(self):
        err = SPAError("msg", code="NOT_INITIALIZED")
        self.assertIsNotNone(err.code)
        self.assertEqual(err.code, "NOT_INITIALIZED")

    def test_t06_spaerror_to_dict_keys(self):
        err = SPAError("problem", code="TEST_CODE", details={"x": 1})
        d = err.to_dict()
        self.assertIn("error", d)
        self.assertIn("code", d)
        self.assertIn("message", d)
        self.assertIn("details", d)
        self.assertEqual(d["code"], "TEST_CODE")


# ─────────────────────────────────────────────────────────────────────────────
# T07–T08: safe_call() absorbs exceptions, returns default
# ─────────────────────────────────────────────────────────────────────────────
class TestSafeCall(unittest.TestCase):

    def test_t07_safe_call_absorbs_exception_returns_default(self):
        def boom():
            raise SPAError("fail", code="SOME_CODE")

        result = safe_call(boom, default="fallback", log_error=False)
        self.assertEqual(result, "fallback")

    def test_t08_safe_call_returns_value_on_success(self):
        def ok(x, y=0):
            return x + y

        result = safe_call(ok, 3, y=4, log_error=False)
        self.assertEqual(result, 7)

    def test_t09_safe_call_absorbs_any_exception(self):
        def bad():
            raise ValueError("raw error")

        result = safe_call(bad, default=None, log_error=False)
        self.assertIsNone(result)

    def test_t10_safe_call_default_is_none_by_default(self):
        def fail():
            raise RuntimeError("oops")

        result = safe_call(fail, log_error=False)
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# T11–T12: require_gate() behaviour
# ─────────────────────────────────────────────────────────────────────────────
class TestRequireGate(unittest.TestCase):

    def test_t11_require_gate_pass_does_not_raise(self):
        # Should not raise
        require_gate("PASS", "live")

    def test_t12_require_gate_non_pass_raises_live_trading_forbidden(self):
        for status in ["FAIL", "NOT_READY", "UNKNOWN", "BLOCKED", ""]:
            with self.subTest(status=status):
                with self.assertRaises(LiveTradingForbiddenError):
                    require_gate(status, "live")


# ─────────────────────────────────────────────────────────────────────────────
# T13: LiveTradingForbiddenError carries gate + code
# ─────────────────────────────────────────────────────────────────────────────
class TestLiveTradingForbiddenError(unittest.TestCase):

    def test_t13_live_trading_forbidden_code(self):
        err = LiveTradingForbiddenError("paper_ready")
        self.assertEqual(err.code, "LIVE_TRADING_FORBIDDEN")
        self.assertEqual(err.gate, "paper_ready")
        self.assertIn("paper_ready", err.details.get("gate", ""))

    def test_t14_live_trading_forbidden_is_spaerror(self):
        err = LiveTradingForbiddenError("test_gate")
        self.assertIsInstance(err, SPAError)


# ─────────────────────────────────────────────────────────────────────────────
# T15: GateError auto-generates correct code
# ─────────────────────────────────────────────────────────────────────────────
class TestGateError(unittest.TestCase):

    def test_t15_gate_error_code_auto_generated(self):
        err = GateError("live", "BLOCKED")
        self.assertEqual(err.code, "GATE_LIVE_BLOCKED")
        self.assertEqual(err.gate, "live")
        self.assertEqual(err.status, "BLOCKED")


# ─────────────────────────────────────────────────────────────────────────────
# T16: Structured details in SourceError / AdapterError / ConfigError
# ─────────────────────────────────────────────────────────────────────────────
class TestStructuredErrors(unittest.TestCase):

    def test_t16_source_error_details(self):
        err = SourceError("chainlink_rpc", "timeout")
        self.assertEqual(err.source_id, "chainlink_rpc")
        self.assertEqual(err.reason, "timeout")
        self.assertIn("source_id", err.details)

    def test_t17_adapter_error_details(self):
        err = AdapterError("compound_v3", "TVL missing")
        self.assertEqual(err.adapter_id, "compound_v3")
        self.assertEqual(err.reason, "TVL missing")
        self.assertEqual(err.code, "ADAPTER_ERROR")

    def test_t18_config_error_details(self):
        err = ConfigError("GITHUB_PAT_SPA", "not found in Keychain")
        self.assertEqual(err.key, "GITHUB_PAT_SPA")
        self.assertEqual(err.reason, "not found in Keychain")
        self.assertEqual(err.code, "CONFIG_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# T19: NOT_INITIALIZED code in migrated analytics modules
# ─────────────────────────────────────────────────────────────────────────────
class TestNotInitializedCode(unittest.TestCase):

    def test_t19_analytics_not_initialized_raises_spaerror_with_code(self):
        from spa_core.analytics.protocol_adoption_scorer import ProtocolAdoptionScorer
        s = ProtocolAdoptionScorer()
        with self.assertRaises(SPAError) as ctx:
            s.get_adoption_tier()
        self.assertEqual(ctx.exception.code, "NOT_INITIALIZED")
        self.assertIsNotNone(ctx.exception.code)


# ─────────────────────────────────────────────────────────────────────────────
# T20: ERROR_CODE_REFERENCE.md exists and contains the error table
# ─────────────────────────────────────────────────────────────────────────────
class TestErrorCodeReferenceDoc(unittest.TestCase):

    def test_t20_error_code_reference_md_exists_and_has_table(self):
        ref_path = os.path.join(_ROOT, "docs", "ERROR_CODE_REFERENCE.md")
        self.assertTrue(
            os.path.isfile(ref_path),
            f"ERROR_CODE_REFERENCE.md not found at {ref_path}",
        )
        with open(ref_path, encoding="utf-8") as fh:
            content = fh.read()
        # Must have version header
        self.assertIn("Version:", content)
        # Must have error hierarchy section
        self.assertIn("SPAError", content)
        self.assertIn("GateError", content)
        self.assertIn("LiveTradingForbiddenError", content)
        # Must have a markdown table (pipe character rows)
        table_rows = [ln for ln in content.splitlines() if ln.strip().startswith("|")]
        self.assertGreater(len(table_rows), 5, "ERROR_CODE_REFERENCE.md must contain a multi-row table")
        # Must contain key codes
        self.assertIn("NOT_INITIALIZED", content)
        self.assertIn("LIVE_TRADING_FORBIDDEN", content)
        self.assertIn("ADAPTER_ERROR", content)
        self.assertIn("CONFIG_ERROR", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
