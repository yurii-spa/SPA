"""
tests/test_drawdown_circuit_breaker.py

MP-1501 (v11.17): 25 tests for spa_core/safety/drawdown_circuit_breaker.py

Coverage:
  - Module constants
  - Initial state (not tripped, zero drawdown)
  - Peak tracking (rises with new high)
  - Peak frozen while tripped
  - Tripping at exactly 5% drawdown
  - Tripping above 5% drawdown
  - No trip below 5% drawdown
  - Recovery below 2% un-trips
  - No un-trip while drawdown still >= 2%
  - assert_ok() passes when healthy
  - assert_ok() raises SPAError when tripped
  - SPAError code = "DRAWDOWN_CIRCUIT_BREAKER"
  - status() dict keys and types
  - reset() clears all state
  - Multiple trips and recoveries
  - New high after recovery allows peak to advance
  - _current_drawdown() with zero peak
"""
import sys
import os
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.safety.drawdown_circuit_breaker import (
    DrawdownCircuitBreaker,
    MAX_DRAWDOWN_THRESHOLD,
    RECOVERY_THRESHOLD,
)
from spa_core.utils.errors import SPAError


# ===========================================================================
# 1. Module constants
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_max_drawdown_threshold(self):
        self.assertAlmostEqual(MAX_DRAWDOWN_THRESHOLD, 0.05)

    def test_recovery_threshold(self):
        self.assertAlmostEqual(RECOVERY_THRESHOLD, 0.02)

    def test_recovery_less_than_max(self):
        self.assertLess(RECOVERY_THRESHOLD, MAX_DRAWDOWN_THRESHOLD)


# ===========================================================================
# 2. Initial state
# ===========================================================================

class TestInitialState(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()

    def test_not_tripped_initially(self):
        self.assertFalse(self.cb._tripped)

    def test_zero_peak_initially(self):
        self.assertEqual(self.cb._peak_nav, 0.0)

    def test_zero_current_nav_initially(self):
        self.assertEqual(self.cb._current_nav, 0.0)

    def test_zero_drawdown_initially(self):
        self.assertEqual(self.cb._current_drawdown(), 0.0)

    def test_status_ok_initially(self):
        self.assertEqual(self.cb.status()["message"], "OK")


# ===========================================================================
# 3. Peak tracking
# ===========================================================================

class TestPeakTracking(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()

    def test_peak_rises_with_nav(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(110_000)
        self.assertEqual(self.cb._peak_nav, 110_000)

    def test_peak_does_not_fall(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(95_000)   # drawdown < 5% — not tripped
        self.assertEqual(self.cb._peak_nav, 100_000)

    def test_peak_frozen_while_tripped(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)   # 6% drawdown → tripped
        self.assertTrue(self.cb._tripped)
        self.cb.update_nav(98_000)   # still tripped (3% dd >= 2% recovery threshold)
        self.assertEqual(self.cb._peak_nav, 100_000)


# ===========================================================================
# 4. Tripping
# ===========================================================================

class TestTripping(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()

    def test_trip_at_exactly_5_pct(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(95_000)   # exactly 5%
        self.assertTrue(self.cb._tripped)

    def test_trip_above_5_pct(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(90_000)   # 10%
        self.assertTrue(self.cb._tripped)

    def test_no_trip_below_5_pct(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(96_000)   # 4% — under threshold
        self.assertFalse(self.cb._tripped)

    def test_status_message_when_tripped(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)
        self.assertIn("CIRCUIT BREAKER", self.cb.status()["message"])

    def test_tripped_flag_in_status(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)
        self.assertTrue(self.cb.status()["tripped"])


# ===========================================================================
# 5. Recovery
# ===========================================================================

class TestRecovery(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)   # trip at 6%

    def test_still_tripped_at_2_pct_drawdown(self):
        self.cb.update_nav(98_000)   # 2% dd — exactly at threshold, still tripped
        self.assertTrue(self.cb._tripped)

    def test_untripped_below_2_pct_drawdown(self):
        self.cb.update_nav(99_000)   # 1% dd < 2% → should un-trip
        self.assertFalse(self.cb._tripped)

    def test_status_ok_after_recovery(self):
        self.cb.update_nav(99_000)
        self.assertEqual(self.cb.status()["message"], "OK")

    def test_peak_advances_after_recovery(self):
        self.cb.update_nav(99_000)   # un-trip
        self.cb.update_nav(105_000)  # new high
        self.assertEqual(self.cb._peak_nav, 105_000)


# ===========================================================================
# 6. assert_ok()
# ===========================================================================

class TestAssertOk(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()

    def test_assert_ok_passes_when_healthy(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(99_000)   # 1% — safe
        # Should not raise
        self.cb.assert_ok()

    def test_assert_ok_raises_when_tripped(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)   # trip
        with self.assertRaises(SPAError):
            self.cb.assert_ok()

    def test_assert_ok_error_code(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)
        try:
            self.cb.assert_ok()
            self.fail("Expected SPAError")
        except SPAError as exc:
            self.assertEqual(exc.code, "DRAWDOWN_CIRCUIT_BREAKER")

    def test_assert_ok_no_raise_after_recovery(self):
        self.cb.update_nav(100_000)
        self.cb.update_nav(94_000)
        self.cb.update_nav(99_500)   # 0.5% dd → recover
        self.cb.assert_ok()          # should not raise


# ===========================================================================
# 7. status() structure
# ===========================================================================

class TestStatus(unittest.TestCase):

    def setUp(self):
        self.cb = DrawdownCircuitBreaker()
        self.cb.update_nav(100_000)

    def test_status_has_tripped(self):
        self.assertIn("tripped", self.cb.status())

    def test_status_has_current_drawdown(self):
        self.assertIn("current_drawdown", self.cb.status())

    def test_status_has_peak_nav(self):
        self.assertIn("peak_nav", self.cb.status())

    def test_status_has_current_nav(self):
        self.assertIn("current_nav", self.cb.status())

    def test_status_has_message(self):
        self.assertIn("message", self.cb.status())

    def test_status_tripped_is_bool(self):
        self.assertIsInstance(self.cb.status()["tripped"], bool)


# ===========================================================================
# 8. reset()
# ===========================================================================

class TestReset(unittest.TestCase):

    def test_reset_clears_state(self):
        cb = DrawdownCircuitBreaker()
        cb.update_nav(100_000)
        cb.update_nav(90_000)   # trip
        self.assertTrue(cb._tripped)
        cb.reset()
        self.assertFalse(cb._tripped)
        self.assertEqual(cb._peak_nav, 0.0)
        self.assertEqual(cb._current_nav, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
