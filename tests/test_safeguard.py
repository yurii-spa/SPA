"""
tests/test_safeguard.py

30 tests for spa_core/safety/safeguard.py

Coverage:
  - @live_trading_forbidden → LiveTradingForbiddenError always
  - @live_trading_forbidden preserves __name__ and __doc__ (functools.wraps)
  - @require_gate → LiveTradingForbiddenError if gate LOCKED
  - @require_gate passes through when gate is active
  - @research_only() → function executes normally
  - @research_only("X") → _research_only == True, _adapter_name set
  - is_research_only() → True/False
  - Combination scenarios

MP-1402 (v10.18) — stdlib only.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from spa_core.safety.safeguard import (
    is_research_only,
    live_trading_forbidden,
    require_gate,
    research_only,
)
from spa_core.safety.live_trading_gate import LiveTradingGate
from spa_core.utils.errors import LiveTradingForbiddenError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _valid_sha256() -> str:
    return hashlib.sha256(b"owner-acceptance-doc").hexdigest()


def _activated_gate(tmp_dir: str) -> LiveTradingGate:
    """Return an activated LiveTradingGate for testing @require_gate."""
    gate = LiveTradingGate(base_dir=tmp_dir)
    state = gate._load()
    state.update({
        "owner_acceptance": True,
        "paper_trading_complete": True,
        "pre_launch_validation": True,
    })
    gate._state = state
    gate._save()
    gate._state = None
    gate.activate(_valid_sha256(), "test activation")
    return gate


# ─────────────────────────────────────────────────────────────────────────────
# @live_trading_forbidden tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveTradingForbiddenDecorator(unittest.TestCase):

    # 1
    def test_live_trading_forbidden_raises_always(self):
        @live_trading_forbidden
        def do_trade():
            return "executed"

        with self.assertRaises(LiveTradingForbiddenError):
            do_trade()

    # 2
    def test_live_trading_forbidden_error_type(self):
        @live_trading_forbidden
        def execute_swap(amount):
            pass

        exc = None
        try:
            execute_swap(100)
        except LiveTradingForbiddenError as e:
            exc = e
        self.assertIsNotNone(exc)
        self.assertIsInstance(exc, LiveTradingForbiddenError)

    # 3
    def test_live_trading_forbidden_preserves_name(self):
        @live_trading_forbidden
        def place_order(size, price):
            """Place a real order."""
            pass

        self.assertEqual(place_order.__name__, "place_order")

    # 4
    def test_live_trading_forbidden_preserves_doc(self):
        @live_trading_forbidden
        def send_transaction():
            """Send a blockchain transaction."""
            pass

        self.assertEqual(send_transaction.__doc__, "Send a blockchain transaction.")

    # 5
    def test_live_trading_forbidden_any_positional_args(self):
        @live_trading_forbidden
        def transfer(from_addr, to_addr, amount, token):
            pass

        with self.assertRaises(LiveTradingForbiddenError):
            transfer("0xA", "0xB", 1000, "USDC")

    # 6
    def test_live_trading_forbidden_no_args(self):
        @live_trading_forbidden
        def close_all():
            pass

        with self.assertRaises(LiveTradingForbiddenError):
            close_all()

    # 7
    def test_live_trading_forbidden_kwargs(self):
        @live_trading_forbidden
        def approve_transfer(amount=0, token="USDC"):
            pass

        with self.assertRaises(LiveTradingForbiddenError):
            approve_transfer(amount=500, token="DAI")

    # 8
    def test_live_trading_forbidden_error_code(self):
        @live_trading_forbidden
        def rebalance():
            pass

        try:
            rebalance()
        except LiveTradingForbiddenError as exc:
            self.assertEqual(exc.code, "LIVE_TRADING_FORBIDDEN")

    # 9
    def test_live_trading_forbidden_gate_attr_is_function_name(self):
        @live_trading_forbidden
        def execute_rebalance():
            pass

        try:
            execute_rebalance()
        except LiveTradingForbiddenError as exc:
            self.assertEqual(exc.gate, "execute_rebalance")

    # 10
    def test_live_trading_forbidden_class_method(self):
        class Executor:
            @live_trading_forbidden
            def send(self, amount):
                return amount

        ex = Executor()
        with self.assertRaises(LiveTradingForbiddenError):
            ex.send(100)

    # 11
    def test_live_trading_forbidden_body_unreachable(self):
        """The original function body must never execute."""
        side_effects = []

        @live_trading_forbidden
        def dangerous():
            side_effects.append("executed")

        try:
            dangerous()
        except LiveTradingForbiddenError:
            pass
        self.assertEqual(side_effects, [])


# ─────────────────────────────────────────────────────────────────────────────
# @require_gate tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRequireGateDecorator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 12
    def test_require_gate_raises_when_locked(self):
        import spa_core.safety.live_trading_gate as mod
        original = mod._gate
        mod._gate = LiveTradingGate(base_dir=self.tmp)
        try:
            @require_gate
            def do_live():
                return "live"

            with self.assertRaises(LiveTradingForbiddenError):
                do_live()
        finally:
            mod._gate = original

    # 13
    def test_require_gate_passes_when_gate_active(self):
        """When gate is active, @require_gate lets the function run."""
        import spa_core.safety.live_trading_gate as mod
        original = mod._gate
        gate = _activated_gate(self.tmp)
        mod._gate = gate
        try:
            @require_gate
            def do_live():
                return "success"

            result = do_live()
            self.assertEqual(result, "success")
        finally:
            mod._gate = original

    # 14
    def test_require_gate_preserves_name(self):
        @require_gate
        def process_trade(order_id):
            """Process a real trade."""
            pass

        self.assertEqual(process_trade.__name__, "process_trade")

    # 15
    def test_require_gate_preserves_doc(self):
        @require_gate
        def settle_position():
            """Settle an open position."""
            pass

        self.assertEqual(settle_position.__doc__, "Settle an open position.")

    # 16
    def test_require_gate_preserves_return_value(self):
        import spa_core.safety.live_trading_gate as mod
        original = mod._gate
        gate = _activated_gate(self.tmp)
        mod._gate = gate
        try:
            @require_gate
            def compute_pnl(entry, exit_):
                return exit_ - entry

            self.assertEqual(compute_pnl(100, 150), 50)
        finally:
            mod._gate = original

    # 17
    def test_require_gate_with_args_and_kwargs(self):
        import spa_core.safety.live_trading_gate as mod
        original = mod._gate
        gate = _activated_gate(self.tmp)
        mod._gate = gate
        try:
            @require_gate
            def order(amount, token, *, slippage=0.01):
                return {"amount": amount, "token": token, "slippage": slippage}

            result = order(500, "USDC", slippage=0.005)
            self.assertEqual(result["amount"], 500)
            self.assertEqual(result["slippage"], 0.005)
        finally:
            mod._gate = original

    # 18
    def test_require_gate_error_code(self):
        import spa_core.safety.live_trading_gate as mod
        original = mod._gate
        mod._gate = LiveTradingGate(base_dir=self.tmp)
        try:
            @require_gate
            def locked_action():
                pass

            try:
                locked_action()
            except LiveTradingForbiddenError as exc:
                self.assertEqual(exc.code, "LIVE_TRADING_FORBIDDEN")
        finally:
            mod._gate = original


# ─────────────────────────────────────────────────────────────────────────────
# @research_only tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResearchOnlyDecorator(unittest.TestCase):

    # 19
    def test_research_only_function_executes(self):
        @research_only()
        def fetch_apy():
            return 0.05

        result = fetch_apy()
        self.assertEqual(result, 0.05)

    # 20
    def test_research_only_returns_value(self):
        @research_only("Aave")
        def get_tvl():
            return 1_000_000

        self.assertEqual(get_tvl(), 1_000_000)

    # 21
    def test_research_only_attr_research_only(self):
        @research_only("GMX")
        def analyze():
            pass

        self.assertTrue(analyze._research_only)

    # 22
    def test_research_only_attr_adapter_name(self):
        @research_only("GoldProxy")
        def gold_apy():
            return 0.03

        self.assertEqual(gold_apy._adapter_name, "GoldProxy")

    # 23
    def test_research_only_default_adapter_name_empty(self):
        @research_only()
        def generic():
            pass

        self.assertEqual(generic._adapter_name, "")

    # 24
    def test_research_only_preserves_name(self):
        @research_only("Morpho")
        def morpho_yield():
            """Morpho yield fetch."""
            pass

        self.assertEqual(morpho_yield.__name__, "morpho_yield")

    # 25
    def test_research_only_preserves_doc(self):
        @research_only("Compound")
        def compound_rate():
            """Fetch Compound borrow rate."""
            pass

        self.assertEqual(compound_rate.__doc__, "Fetch Compound borrow rate.")

    # 26
    def test_research_only_with_exception_propagates(self):
        @research_only("BadAdapter")
        def broken_fetch():
            raise RuntimeError("network error")

        with self.assertRaises(RuntimeError):
            broken_fetch()

    # 27
    def test_research_only_multiple_calls(self):
        call_count = []

        @research_only("Counter")
        def counted():
            call_count.append(1)
            return len(call_count)

        self.assertEqual(counted(), 1)
        self.assertEqual(counted(), 2)
        self.assertEqual(counted(), 3)

    # 28
    def test_research_only_different_adapters(self):
        @research_only("AdapterA")
        def fn_a():
            return "a"

        @research_only("AdapterB")
        def fn_b():
            return "b"

        self.assertEqual(fn_a._adapter_name, "AdapterA")
        self.assertEqual(fn_b._adapter_name, "AdapterB")
        self.assertEqual(fn_a(), "a")
        self.assertEqual(fn_b(), "b")


# ─────────────────────────────────────────────────────────────────────────────
# is_research_only() tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIsResearchOnly(unittest.TestCase):

    # 29
    def test_is_research_only_true(self):
        @research_only("TestAdapter")
        def decorated():
            pass

        self.assertTrue(is_research_only(decorated))

    # 30
    def test_is_research_only_false_for_plain_function(self):
        def plain():
            pass

        self.assertFalse(is_research_only(plain))

    def test_is_research_only_false_for_forbidden(self):
        @live_trading_forbidden
        def forbidden_fn():
            pass

        self.assertFalse(is_research_only(forbidden_fn))

    def test_is_research_only_false_for_lambda(self):
        fn = lambda x: x  # noqa: E731
        self.assertFalse(is_research_only(fn))

    def test_is_research_only_no_arg_decorator(self):
        @research_only()
        def no_adapter():
            pass

        self.assertTrue(is_research_only(no_adapter))


if __name__ == "__main__":
    unittest.main(verbosity=2)
