"""
spa_core/tests/test_rate_limiter.py — MP-411

Comprehensive tests for RateLimiter (40+ tests).

Coverage:
  - check_rebalance_allowed: allowed path, cooldown block, daily cap block,
    circuit-breaker block/trigger, protocol-count block
  - record_rebalance: accumulation, persistence
  - daily reset logic (same day, next day, multi-day gap)
  - circuit breaker: activation, expiry, freeze window
  - state persistence: write + read round-trip
  - edge cases: zero AUM, first rebalance ever, exactly at limits,
    day boundary, circuit-breaker expiry timing
"""

from __future__ import annotations

import json
import os
import time
import tempfile
import unittest
from pathlib import Path

from spa_core.execution.rate_limiter import (
    CIRCUIT_BREAKER_DRAWDOWN,
    CIRCUIT_BREAKER_FREEZE_SECONDS,
    COOLDOWN_SECONDS,
    MAX_PROTOCOLS_PER_OP,
    RateLimiter,
    _start_of_utc_day,
    _ts_to_iso,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_snapshot(
    total_aum: float = 100_000.0,
    proposed: float = 1_000.0,
    protocols: int = 1,
    drawdown_24h: float = 0.0,
) -> dict:
    return {
        "total_aum_usdc": total_aum,
        "proposed_move_usdc": proposed,
        "protocols_changed": protocols,
        "drawdown_24h_pct": drawdown_24h,
    }


class TempStateLimiter(RateLimiter):
    """RateLimiter that auto-creates a temp file per test."""

    def __init__(self, initial_state: dict | None = None):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        if initial_state is not None:
            json.dump(initial_state, self._tmp)
        else:
            json.dump({}, self._tmp)
        self._tmp.flush()
        self._tmp.close()
        super().__init__(config_path=Path(self._tmp.name))

    def cleanup(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass


# ── Test: import & instantiation ──────────────────────────────────────────────

class TestImport(unittest.TestCase):
    def test_import_from_package(self):
        from spa_core.execution.rate_limiter import RateLimiter as RL
        self.assertIsNotNone(RL)

    def test_import_from_execution_init(self):
        from spa_core.execution import RateLimiter as RL
        self.assertIsNotNone(RL)

    def test_instantiate_with_temp_path(self):
        rl = TempStateLimiter()
        self.assertIsNotNone(rl)
        rl.cleanup()


# ── Test: check_rebalance_allowed — happy path ────────────────────────────────

class TestCheckAllowed(unittest.TestCase):
    def setUp(self):
        self.rl = TempStateLimiter()

    def tearDown(self):
        self.rl.cleanup()

    def test_first_rebalance_ever_is_allowed(self):
        snap = _make_snapshot()
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed)
        self.assertEqual(reason, "allowed")

    def test_zero_proposed_is_allowed(self):
        snap = _make_snapshot(proposed=0.0)
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed)

    def test_exactly_at_daily_cap_is_allowed(self):
        # 30% of 100k = 30k; propose 30k exactly → allowed
        snap = _make_snapshot(total_aum=100_000.0, proposed=30_000.0)
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)

    def test_one_protocol_allowed(self):
        snap = _make_snapshot(protocols=1)
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed)

    def test_three_protocols_allowed(self):
        snap = _make_snapshot(protocols=MAX_PROTOCOLS_PER_OP)
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed)

    def test_zero_aum_skips_daily_cap(self):
        # AUM=0 → cap math skipped, should still allow
        snap = _make_snapshot(total_aum=0.0, proposed=999_999.0)
        allowed, reason = self.rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)


# ── Test: cooldown block ───────────────────────────────────────────────────────

class TestCooldown(unittest.TestCase):
    def test_blocked_if_within_cooldown(self):
        rl = TempStateLimiter()
        # Record a rebalance just 1 second ago
        recent_ts = time.time() - 60
        rl._state["last_rebalance_ts"] = recent_ts
        rl._save_state()

        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertFalse(allowed)
        self.assertIn("cooldown_active", reason)
        rl.cleanup()

    def test_allowed_after_cooldown_expires(self):
        rl = TempStateLimiter()
        # Rebalance happened COOLDOWN_SECONDS + 1 ago
        old_ts = time.time() - (COOLDOWN_SECONDS + 1)
        rl._state["last_rebalance_ts"] = old_ts
        rl._save_state()

        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertTrue(allowed, reason)
        rl.cleanup()

    def test_cooldown_reason_contains_remaining_seconds(self):
        rl = TempStateLimiter()
        rl._state["last_rebalance_ts"] = time.time() - 60
        rl._save_state()

        _, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertIn("remaining", reason)
        rl.cleanup()

    def test_exactly_at_cooldown_boundary_allowed(self):
        rl = TempStateLimiter()
        # Exactly COOLDOWN_SECONDS ago → elapsed == COOLDOWN_SECONDS → NOT < → allowed
        rl._state["last_rebalance_ts"] = time.time() - COOLDOWN_SECONDS
        rl._save_state()

        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertTrue(allowed, reason)
        rl.cleanup()


# ── Test: daily reallocation cap ──────────────────────────────────────────────

class TestDailyCap(unittest.TestCase):
    def test_blocked_when_daily_cap_exceeded(self):
        rl = TempStateLimiter()
        # Already moved 29k, cap is 30k, proposing 2k more → should block
        rl._state["daily_moved_usdc"] = 29_000.0
        rl._state["daily_reset_ts"] = _start_of_utc_day(time.time())
        rl._save_state()

        snap = _make_snapshot(total_aum=100_000.0, proposed=2_000.0)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertFalse(allowed)
        self.assertIn("daily_limit_exceeded", reason)
        rl.cleanup()

    def test_allowed_when_under_daily_cap(self):
        rl = TempStateLimiter()
        rl._state["daily_moved_usdc"] = 10_000.0
        rl._state["daily_reset_ts"] = _start_of_utc_day(time.time())
        rl._save_state()

        snap = _make_snapshot(total_aum=100_000.0, proposed=5_000.0)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)
        rl.cleanup()

    def test_daily_cap_reason_contains_usdc_values(self):
        rl = TempStateLimiter()
        rl._state["daily_moved_usdc"] = 29_000.0
        rl._state["daily_reset_ts"] = _start_of_utc_day(time.time())
        rl._save_state()

        _, reason = rl.check_rebalance_allowed(
            _make_snapshot(total_aum=100_000.0, proposed=2_000.0)
        )
        self.assertIn("cap=", reason)
        rl.cleanup()

    def test_exactly_at_cap_not_exceeded(self):
        rl = TempStateLimiter()
        # already_moved=0, proposed=30_000 → exactly at cap → allowed
        rl._state["daily_moved_usdc"] = 0.0
        rl._state["daily_reset_ts"] = _start_of_utc_day(time.time())
        rl._save_state()

        snap = _make_snapshot(total_aum=100_000.0, proposed=30_000.0)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)
        rl.cleanup()


# ── Test: max protocols ────────────────────────────────────────────────────────

class TestMaxProtocols(unittest.TestCase):
    def test_four_protocols_blocked(self):
        rl = TempStateLimiter()
        snap = _make_snapshot(protocols=MAX_PROTOCOLS_PER_OP + 1)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertFalse(allowed)
        self.assertIn("too_many_protocols", reason)
        rl.cleanup()

    def test_max_protocols_allowed(self):
        rl = TempStateLimiter()
        snap = _make_snapshot(protocols=MAX_PROTOCOLS_PER_OP)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)
        rl.cleanup()

    def test_zero_protocols_allowed(self):
        rl = TempStateLimiter()
        snap = _make_snapshot(protocols=0)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)
        rl.cleanup()


# ── Test: circuit breaker ─────────────────────────────────────────────────────

class TestCircuitBreaker(unittest.TestCase):
    def test_circuit_breaker_triggers_on_high_drawdown(self):
        rl = TempStateLimiter()
        # drawdown > 5% → should return False with trigger message
        snap = _make_snapshot(drawdown_24h=0.06)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertFalse(allowed)
        self.assertIn("circuit_breaker_triggered", reason)
        rl.cleanup()

    def test_circuit_breaker_persists_after_trigger(self):
        rl = TempStateLimiter()
        snap = _make_snapshot(drawdown_24h=0.06)
        rl.check_rebalance_allowed(snap)  # triggers

        # Fresh instance from same state file
        rl2 = RateLimiter(config_path=rl._state_path)
        allowed, reason = rl2.check_rebalance_allowed(_make_snapshot())
        self.assertFalse(allowed)
        self.assertIn("circuit_breaker_active", reason)
        rl.cleanup()

    def test_circuit_breaker_blocks_all_until_expiry(self):
        rl = TempStateLimiter()
        # Manually set circuit_breaker_until to future
        rl._state["circuit_breaker_until"] = time.time() + 3600
        rl._save_state()

        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertFalse(allowed)
        self.assertIn("circuit_breaker_active", reason)
        rl.cleanup()

    def test_circuit_breaker_expires_after_freeze_window(self):
        rl = TempStateLimiter()
        # Set circuit_breaker_until to the past → expired
        rl._state["circuit_breaker_until"] = time.time() - 1
        rl._save_state()

        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertTrue(allowed, reason)
        rl.cleanup()

    def test_circuit_breaker_freeze_duration_is_24h(self):
        rl = TempStateLimiter()
        snap = _make_snapshot(drawdown_24h=0.10)
        now_before = time.time()
        rl.check_rebalance_allowed(snap)
        now_after = time.time()

        frozen_until = rl._state.get("circuit_breaker_until")
        self.assertIsNotNone(frozen_until)
        expected_lo = now_before + CIRCUIT_BREAKER_FREEZE_SECONDS
        expected_hi = now_after + CIRCUIT_BREAKER_FREEZE_SECONDS
        self.assertGreaterEqual(frozen_until, expected_lo)
        self.assertLessEqual(frozen_until, expected_hi)
        rl.cleanup()

    def test_circuit_breaker_not_triggered_at_exactly_5pct(self):
        rl = TempStateLimiter()
        # Exactly 5% → NOT > CIRCUIT_BREAKER_DRAWDOWN → should not trigger
        snap = _make_snapshot(drawdown_24h=CIRCUIT_BREAKER_DRAWDOWN)
        allowed, reason = rl.check_rebalance_allowed(snap)
        self.assertTrue(allowed, reason)
        rl.cleanup()

    def test_circuit_breaker_reason_includes_until_timestamp(self):
        rl = TempStateLimiter()
        rl._state["circuit_breaker_until"] = time.time() + 7200
        rl._save_state()

        _, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertIn("frozen until", reason)
        rl.cleanup()


# ── Test: record_rebalance ────────────────────────────────────────────────────

class TestRecordRebalance(unittest.TestCase):
    def test_record_updates_last_ts(self):
        rl = TempStateLimiter()
        before = time.time()
        rl.record_rebalance(1000.0)
        after = time.time()

        ts = rl._state["last_rebalance_ts"]
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)
        rl.cleanup()

    def test_record_accumulates_daily_moved(self):
        rl = TempStateLimiter()
        rl.record_rebalance(1_000.0)
        rl.record_rebalance(2_500.0)

        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 3_500.0, places=2)
        rl.cleanup()

    def test_record_persists_to_disk(self):
        rl = TempStateLimiter()
        rl.record_rebalance(5_000.0)

        # Read state file directly
        with open(rl._state_path) as f:
            state_on_disk = json.load(f)

        self.assertAlmostEqual(state_on_disk["daily_moved_usdc"], 5_000.0, places=2)
        self.assertIsNotNone(state_on_disk["last_rebalance_ts"])
        rl.cleanup()

    def test_record_uses_absolute_value(self):
        rl = TempStateLimiter()
        rl.record_rebalance(-1_000.0)  # negative → treated as 1000
        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 1_000.0, places=2)
        rl.cleanup()

    def test_record_triggers_daily_reset_if_needed(self):
        rl = TempStateLimiter()
        # Set reset_ts to yesterday → record should roll over
        rl._state["daily_reset_ts"] = time.time() - 90_000  # >24h ago
        rl._state["daily_moved_usdc"] = 99_999.0
        rl._save_state()

        rl.record_rebalance(1_000.0)

        # After rollover, daily_moved should only reflect the new record
        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 1_000.0, places=2)
        rl.cleanup()


# ── Test: daily reset logic ────────────────────────────────────────────────────

class TestDailyReset(unittest.TestCase):
    def test_daily_reset_on_first_call(self):
        rl = TempStateLimiter()
        # Force daily_reset_ts to None → first call sets it
        rl._state["daily_reset_ts"] = None
        rl._maybe_reset_daily(time.time())

        self.assertIsNotNone(rl._state["daily_reset_ts"])
        rl.cleanup()

    def test_no_reset_within_same_day(self):
        rl = TempStateLimiter()
        today_start = _start_of_utc_day(time.time())
        rl._state["daily_reset_ts"] = today_start
        rl._state["daily_moved_usdc"] = 5_000.0
        rl._save_state()

        # Call within same day
        rl._maybe_reset_daily(time.time())
        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 5_000.0, places=2)
        rl.cleanup()

    def test_reset_after_one_day(self):
        rl = TempStateLimiter()
        rl._state["daily_reset_ts"] = time.time() - 90_000  # >24h ago
        rl._state["daily_moved_usdc"] = 9_999.0
        rl._save_state()

        rl._maybe_reset_daily(time.time())
        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 0.0, places=2)
        rl.cleanup()

    def test_reset_after_multi_day_gap(self):
        rl = TempStateLimiter()
        rl._state["daily_reset_ts"] = time.time() - (3 * 86400)  # 3 days ago
        rl._state["daily_moved_usdc"] = 50_000.0
        rl._save_state()

        rl._maybe_reset_daily(time.time())
        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 0.0, places=2)
        rl.cleanup()

    def test_daily_reset_ts_advances_to_today(self):
        rl = TempStateLimiter()
        rl._state["daily_reset_ts"] = time.time() - 90_000
        rl._save_state()

        now = time.time()
        rl._maybe_reset_daily(now)

        expected = _start_of_utc_day(now)
        self.assertAlmostEqual(rl._state["daily_reset_ts"], expected, delta=1)
        rl.cleanup()


# ── Test: state persistence (write + read round-trip) ─────────────────────────

class TestStatePersistence(unittest.TestCase):
    def test_empty_state_file_uses_defaults(self):
        rl = TempStateLimiter(initial_state={})
        self.assertIsNone(rl._state.get("last_rebalance_ts"))
        self.assertEqual(rl._state.get("daily_moved_usdc", 0.0), 0.0)
        rl.cleanup()

    def test_round_trip_after_record(self):
        rl = TempStateLimiter()
        rl.record_rebalance(7_777.0)
        saved_ts = rl._state["last_rebalance_ts"]
        state_path = rl._state_path

        # Load from disk with a fresh instance
        rl2 = RateLimiter(config_path=state_path)
        self.assertAlmostEqual(rl2._state["daily_moved_usdc"], 7_777.0, places=2)
        self.assertAlmostEqual(rl2._state["last_rebalance_ts"], saved_ts, delta=0.01)
        rl.cleanup()

    def test_corrupted_state_file_falls_back_to_defaults(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("INVALID JSON {{{{")
            tmp_path = Path(f.name)

        rl = RateLimiter(config_path=tmp_path)
        self.assertIsNone(rl._state.get("last_rebalance_ts"))
        self.assertEqual(rl._state.get("daily_moved_usdc", 0.0), 0.0)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    def test_missing_state_file_falls_back_to_defaults(self):
        rl = RateLimiter(config_path=Path("/tmp/__nonexistent_spa_state_xyz__.json"))
        self.assertIsNone(rl._state.get("last_rebalance_ts"))

    def test_atomic_write_uses_tmp_then_replace(self):
        rl = TempStateLimiter()
        state_path = rl._state_path
        rl.record_rebalance(100.0)

        # Tmp file should be gone (replaced)
        tmp_path = state_path.with_suffix(".json.tmp")
        self.assertFalse(tmp_path.exists(), "tmp file should have been replaced")
        rl.cleanup()


# ── Test: get_status ──────────────────────────────────────────────────────────

class TestGetStatus(unittest.TestCase):
    def test_status_keys_present(self):
        rl = TempStateLimiter()
        status = rl.get_status()
        expected_keys = {
            "last_rebalance_ts",
            "last_rebalance_iso",
            "seconds_since_last",
            "cooldown_remaining_s",
            "daily_moved_usdc",
            "daily_reset_ts",
            "daily_reset_iso",
            "circuit_breaker_active",
            "circuit_breaker_until",
            "circuit_breaker_until_iso",
        }
        self.assertTrue(expected_keys.issubset(set(status.keys())))
        rl.cleanup()

    def test_no_last_rebalance_shows_none(self):
        rl = TempStateLimiter()
        status = rl.get_status()
        self.assertIsNone(status["last_rebalance_ts"])
        self.assertIsNone(status["last_rebalance_iso"])
        self.assertIsNone(status["cooldown_remaining_s"])
        rl.cleanup()

    def test_circuit_breaker_inactive_by_default(self):
        rl = TempStateLimiter()
        status = rl.get_status()
        self.assertFalse(status["circuit_breaker_active"])
        rl.cleanup()

    def test_status_reflects_recent_rebalance(self):
        rl = TempStateLimiter()
        rl.record_rebalance(3_000.0)
        status = rl.get_status()
        self.assertAlmostEqual(status["daily_moved_usdc"], 3_000.0, places=2)
        self.assertIsNotNone(status["last_rebalance_ts"])
        self.assertIsNotNone(status["last_rebalance_iso"])
        rl.cleanup()

    def test_cooldown_remaining_is_positive_after_recent_rebalance(self):
        rl = TempStateLimiter()
        rl.record_rebalance(500.0)
        status = rl.get_status()
        self.assertGreater(status["cooldown_remaining_s"], 0)
        rl.cleanup()


# ── Test: utility functions ────────────────────────────────────────────────────

class TestUtilityFunctions(unittest.TestCase):
    def test_ts_to_iso_format(self):
        ts = 1_700_000_000.0
        iso = _ts_to_iso(ts)
        self.assertRegex(iso, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_start_of_utc_day_is_midnight(self):
        now = time.time()
        start = _start_of_utc_day(now)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(start, tz=timezone.utc)
        self.assertEqual(dt.hour, 0)
        self.assertEqual(dt.minute, 0)
        self.assertEqual(dt.second, 0)

    def test_start_of_utc_day_same_day_idempotent(self):
        now = time.time()
        s1 = _start_of_utc_day(now)
        s2 = _start_of_utc_day(s1)
        self.assertAlmostEqual(s1, s2, delta=1)


# ── Test: integration — full rebalance flow ────────────────────────────────────

class TestIntegration(unittest.TestCase):
    def test_full_rebalance_cycle_then_blocked_by_cooldown(self):
        rl = TempStateLimiter()

        # Step 1: allowed
        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertTrue(allowed, reason)

        # Step 2: record it
        rl.record_rebalance(5_000.0)

        # Step 3: immediately check again → blocked by cooldown
        allowed, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertFalse(allowed)
        self.assertIn("cooldown_active", reason)
        rl.cleanup()

    def test_multiple_records_accumulate_correctly(self):
        rl = TempStateLimiter()
        for amount in [1_000.0, 2_000.0, 3_000.0]:
            rl._state["last_rebalance_ts"] = None  # bypass cooldown
            rl._save_state()
            rl.record_rebalance(amount)

        self.assertAlmostEqual(rl._state["daily_moved_usdc"], 6_000.0, places=2)
        rl.cleanup()

    def test_circuit_breaker_blocks_subsequent_check(self):
        rl = TempStateLimiter()

        # Trigger via high drawdown
        rl.check_rebalance_allowed(_make_snapshot(drawdown_24h=0.10))

        # Subsequent check (no drawdown) still blocked
        allowed, reason = rl.check_rebalance_allowed(_make_snapshot(drawdown_24h=0.0))
        self.assertFalse(allowed)
        self.assertIn("circuit_breaker_active", reason)
        rl.cleanup()

    def test_priority_order_circuit_breaker_before_cooldown(self):
        """Circuit breaker should be checked before cooldown."""
        rl = TempStateLimiter()
        # Both circuit breaker active AND within cooldown
        rl._state["circuit_breaker_until"] = time.time() + 3600
        rl._state["last_rebalance_ts"] = time.time() - 60
        rl._save_state()

        _, reason = rl.check_rebalance_allowed(_make_snapshot())
        self.assertIn("circuit_breaker_active", reason)
        rl.cleanup()


if __name__ == "__main__":
    unittest.main()
