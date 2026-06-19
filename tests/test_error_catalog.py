"""
tests/test_error_catalog.py

MP-1415 (v10.31) — SPAError Adoption: 30 тестов.

Проверяет:
  1. Иерархию исключений (GateError/SourceError/etc. ← SPAError ← Exception)
  2. Утилиты: safe_call(), require_gate()
  3. Поля .code и .details на всех subclass
  4. Мигрированные бизнес-логические raise в core модулях

Запуск:
    python3 -m unittest tests.test_error_catalog -v
    python3 tests/test_error_catalog.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.utils.errors import (
    SPAError,
    GateError,
    SourceError,
    ValidationError,
    KANBANError,
    AdapterError,
    ConfigError,
    AtomicWriteError,
    RegistryError,
    RiskPolicyError,
    AllocationError,
    LiveTradingForbiddenError,
    safe_call,
    require_gate,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Иерархия: subclasses ← SPAError ← Exception
# ─────────────────────────────────────────────────────────────────────────────

class TestSPAErrorHierarchy(unittest.TestCase):
    """Tests 1-9: SPAError is a proper Exception; all subclasses inherit correctly."""

    def test_01_spa_error_is_exception(self):
        """SPAError can be caught as Exception."""
        with self.assertRaises(Exception):
            raise SPAError("test", code="TEST")

    def test_02_gate_error_is_spa_error(self):
        """GateError is a subclass of SPAError."""
        err = GateError("backtest", "FAIL")
        self.assertIsInstance(err, SPAError)
        self.assertIsInstance(err, Exception)

    def test_03_source_error_is_spa_error(self):
        """SourceError is a subclass of SPAError."""
        err = SourceError("defillama", "unreachable")
        self.assertIsInstance(err, SPAError)

    def test_04_live_trading_forbidden_is_spa_error(self):
        """LiveTradingForbiddenError is a subclass of SPAError."""
        err = LiveTradingForbiddenError("paper_ready")
        self.assertIsInstance(err, SPAError)

    def test_05_config_error_is_spa_error(self):
        """ConfigError is a subclass of SPAError."""
        err = ConfigError("GITHUB_PAT", "not found")
        self.assertIsInstance(err, SPAError)

    def test_06_registry_error_is_spa_error(self):
        """RegistryError is a subclass of SPAError."""
        err = RegistryError("adapter not found", code="REGISTRY_ERROR")
        self.assertIsInstance(err, SPAError)

    def test_07_allocation_error_is_spa_error(self):
        """AllocationError is a subclass of SPAError."""
        err = AllocationError("bad model", code="UNKNOWN_ALLOCATION_MODEL")
        self.assertIsInstance(err, SPAError)

    def test_08_adapter_error_is_spa_error(self):
        """AdapterError is a subclass of SPAError."""
        err = AdapterError("aave_v3", "TVL below floor")
        self.assertIsInstance(err, SPAError)

    def test_09_risk_policy_error_is_spa_error(self):
        """RiskPolicyError is a subclass of SPAError."""
        err = RiskPolicyError("drawdown exceeded", code="RISK_POLICY_ERROR")
        self.assertIsInstance(err, SPAError)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Поля .code и .details
# ─────────────────────────────────────────────────────────────────────────────

class TestSPAErrorFields(unittest.TestCase):
    """Tests 10-17: .code and .details fields are set correctly."""

    def test_10_spa_error_code_present(self):
        """SPAError.code is set from kwarg."""
        err = SPAError("msg", code="MY_CODE")
        self.assertEqual(err.code, "MY_CODE")

    def test_11_spa_error_default_code(self):
        """SPAError.code defaults to SPA_UNKNOWN when not provided."""
        err = SPAError("msg")
        self.assertEqual(err.code, "SPA_UNKNOWN")

    def test_12_spa_error_details_present(self):
        """SPAError.details is set from kwarg."""
        err = SPAError("msg", code="X", details={"k": "v"})
        self.assertEqual(err.details, {"k": "v"})

    def test_13_spa_error_details_default_empty(self):
        """SPAError.details defaults to empty dict."""
        err = SPAError("msg")
        self.assertEqual(err.details, {})

    def test_14_gate_error_code_auto(self):
        """GateError auto-generates code as GATE_{GATE}_{STATUS}."""
        err = GateError("paper_ready", "FAIL")
        self.assertEqual(err.code, "GATE_PAPER_READY_FAIL")

    def test_15_source_error_details(self):
        """SourceError.details contains source_id and reason."""
        err = SourceError("defillama", "timeout")
        self.assertIn("source_id", err.details)
        self.assertIn("reason", err.details)
        self.assertEqual(err.details["source_id"], "defillama")

    def test_16_config_error_details(self):
        """ConfigError.details contains key and reason."""
        err = ConfigError("TELEGRAM_TOKEN", "not in keychain")
        self.assertEqual(err.details["key"], "TELEGRAM_TOKEN")
        self.assertEqual(err.details["reason"], "not in keychain")

    def test_17_to_dict_keys(self):
        """SPAError.to_dict() returns error/code/message/details keys."""
        err = SPAError("boom", code="BOOM", details={"x": 1})
        d = err.to_dict()
        for key in ("error", "code", "message", "details"):
            self.assertIn(key, d)
        self.assertEqual(d["code"], "BOOM")
        self.assertEqual(d["details"], {"x": 1})


# ─────────────────────────────────────────────────────────────────────────────
# 3. safe_call()
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeCall(unittest.TestCase):
    """Tests 18-22: safe_call() behaviour."""

    def test_18_safe_call_success(self):
        """safe_call returns the function result on success."""
        result = safe_call(lambda: 42)
        self.assertEqual(result, 42)

    def test_19_safe_call_returns_default_on_error(self):
        """safe_call returns default when function raises."""
        result = safe_call(lambda: 1 / 0, default=-1)
        self.assertEqual(result, -1)

    def test_20_safe_call_default_is_none(self):
        """safe_call default is None when not specified."""
        result = safe_call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIsNone(result)

    def test_21_safe_call_no_raise(self):
        """safe_call never propagates exceptions."""
        try:
            safe_call(lambda: (_ for _ in ()).throw(SPAError("bad", code="X")))
        except Exception as exc:
            self.fail(f"safe_call raised unexpectedly: {exc}")

    def test_22_safe_call_with_args(self):
        """safe_call passes positional and keyword args to the function."""
        def add(a, b):
            return a + b
        result = safe_call(add, 3, 4)
        self.assertEqual(result, 7)


# ─────────────────────────────────────────────────────────────────────────────
# 4. require_gate()
# ─────────────────────────────────────────────────────────────────────────────

class TestRequireGate(unittest.TestCase):
    """Tests 23-25: require_gate() raises LiveTradingForbiddenError on non-PASS."""

    def test_23_require_gate_pass_does_not_raise(self):
        """require_gate("PASS", ...) does not raise."""
        require_gate("PASS", "live")  # must not raise

    def test_24_require_gate_fail_raises(self):
        """require_gate("FAIL", ...) raises LiveTradingForbiddenError."""
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("FAIL", "paper_ready")

    def test_25_require_gate_not_ready_raises(self):
        """require_gate("NOT_READY", ...) raises LiveTradingForbiddenError."""
        with self.assertRaises(LiveTradingForbiddenError):
            require_gate("NOT_READY", "live")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Мигрированные функции бросают правильный тип
# ─────────────────────────────────────────────────────────────────────────────

class TestMigratedRaises(unittest.TestCase):
    """Tests 26-30: migrated business logic raises correct SPAError subclass."""

    def test_26_strategy_registry_duplicate_raises_registry_error(self):
        """StrategyRegistry.register() raises RegistryError on duplicate ID."""
        from spa_core.strategies.strategy_registry import StrategyRegistry, StrategyMeta

        registry = StrategyRegistry()
        meta_a = StrategyMeta(
            id="s_test",
            name="Test Strategy A",
            type="lending",
            risk_tier="T1",
            target_apy_min=2.0,
            target_apy_max=8.0,
            max_drawdown_pct=5.0,
            description="test",
            module="spa_core.strategies.s0_conservative",
            handler_class="ConservativeLending",
        )
        meta_b = StrategyMeta(
            id="s_test",
            name="Test Strategy B (different)",
            type="lending",
            risk_tier="T1",
            target_apy_min=2.0,
            target_apy_max=9.0,
            max_drawdown_pct=5.0,
            description="different",
            module="spa_core.strategies.s0_conservative",
            handler_class="ConservativeLending",
        )
        registry.register(meta_a)
        with self.assertRaises(RegistryError) as ctx:
            registry.register(meta_b)
        self.assertEqual(ctx.exception.code, "STRATEGY_DUPLICATE_ID")

    def test_27_allocator_unknown_model_raises_allocation_error(self):
        """StrategyAllocator.allocate() raises AllocationError for unknown model."""
        from spa_core.allocator.allocator import StrategyAllocator

        allocator = StrategyAllocator()
        with self.assertRaises(AllocationError) as ctx:
            allocator.allocate(model="nonexistent_model_xyz")
        self.assertEqual(ctx.exception.code, "UNKNOWN_ALLOCATION_MODEL")

    def test_28_price_feeds_eth_call_http_raises_source_error(self):
        """PriceFeedFetcher._eth_call() raises SourceError on HTTP failure."""
        import urllib.error
        from spa_core.data_pipeline.price_feeds import PriceFeedFetcher

        fetcher = PriceFeedFetcher()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with self.assertRaises(SourceError) as ctx:
                fetcher._eth_call("https://fake-rpc.example", "0x0", "0x1234")
        self.assertIn("chainlink_rpc", ctx.exception.details.get("source_id", ""))

    def test_29_keychain_missing_raises_config_error(self):
        """keychain.get_jwt_secret() raises ConfigError when secret not found."""
        from spa_core.family_fund.api import keychain as kc

        kc.reset_cache()
        with patch.object(kc, "_read_from_keychain", return_value=None), \
             patch.dict("os.environ", {kc.ENV_FALLBACK: ""}):
            with self.assertRaises(ConfigError) as ctx:
                kc.get_jwt_secret()
            self.assertEqual(ctx.exception.code, "CONFIG_ERROR")
        kc.reset_cache()

    def test_30_message_bus_unknown_topic_raises_registry_error(self):
        """MessageBus.publish() raises RegistryError on unknown topic."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spa_core"))

        from spa_core.message_bus.bus import MessageBus

        # We don't need a real DB — the topic check fires before any DB call
        bus = MessageBus.__new__(MessageBus)
        with self.assertRaises(RegistryError) as ctx:
            bus.publish("TOTALLY_UNKNOWN_TOPIC_XYZ", "test", {})
        self.assertEqual(ctx.exception.code, "UNKNOWN_TOPIC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
