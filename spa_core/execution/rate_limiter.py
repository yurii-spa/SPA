"""
spa_core/execution/rate_limiter.py — MP-411

Execution Rate Limits & Cooldowns.

Rules:
  1. Max daily reallocation: ≤ 30% of total AUM in a rolling calendar day
  2. Min cooldown: 4 hours between rebalance operations (anti-flapping)
  3. Max protocols changed per operation: ≤ 3
  4. Emergency circuit breaker: portfolio drawdown > 5% in 24 h → freeze 24 h

State is persisted atomically to data/rate_limiter_state.json.

Pure stdlib — no external dependencies.
LLM usage: FORBIDDEN (this module is in the execution domain).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────

COOLDOWN_SECONDS: int = 4 * 3600          # 4 hours
MAX_DAILY_REALLOC_FRACTION: float = 0.30  # 30 % of AUM
MAX_PROTOCOLS_PER_OP: int = 3
CIRCUIT_BREAKER_DRAWDOWN: float = 0.05    # 5 % portfolio drawdown in 24 h
CIRCUIT_BREAKER_FREEZE_SECONDS: int = 24 * 3600  # freeze 24 h after trigger

_DEFAULT_STATE_PATH = Path("data/rate_limiter_state.json")

_EMPTY_STATE: dict = {
    "last_rebalance_ts": None,
    "daily_moved_usdc": 0.0,
    "daily_reset_ts": None,
    "circuit_breaker_until": None,
}


# ── RateLimiter ───────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Stateful rate-limiter for virtual rebalance operations.

    Usage:
        rl = RateLimiter()
        allowed, reason = rl.check_rebalance_allowed(snapshot)
        if allowed:
            # ... perform rebalance ...
            rl.record_rebalance(amount_usdc=5000.0)
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._state_path: Path = Path(config_path) if config_path else _DEFAULT_STATE_PATH
        self._state: dict = self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def check_rebalance_allowed(self, portfolio_snapshot: dict) -> tuple[bool, str]:
        """
        Evaluate all rate-limiting rules against the current portfolio state.

        Args:
            portfolio_snapshot: dict with at minimum:
                {
                  "total_aum_usdc": float,          # total portfolio value
                  "proposed_move_usdc": float,       # gross USDC to move this op
                  "protocols_changed": int,          # number of protocols touched
                  "drawdown_24h_pct": float,         # optional; 0.0 if absent
                }

        Returns:
            (True, "allowed") or (False, "<reason>")
        """
        now = time.time()

        # Refresh daily counter if calendar day has rolled over
        self._maybe_reset_daily(now)

        state = self._state

        # ── 1. Circuit breaker ────────────────────────────────────────────────
        cb_until = state.get("circuit_breaker_until")
        if cb_until is not None and now < cb_until:
            until_str = _ts_to_iso(cb_until)
            return False, f"circuit_breaker_active: frozen until {until_str}"

        # ── 2. Min cooldown ───────────────────────────────────────────────────
        last_ts = state.get("last_rebalance_ts")
        if last_ts is not None:
            elapsed = now - last_ts
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                return False, f"cooldown_active: {remaining}s remaining (need {COOLDOWN_SECONDS}s gap)"

        # ── 3. Max protocols per operation ────────────────────────────────────
        protocols_changed: int = int(portfolio_snapshot.get("protocols_changed", 0))
        if protocols_changed > MAX_PROTOCOLS_PER_OP:
            return (
                False,
                f"too_many_protocols: {protocols_changed} > max {MAX_PROTOCOLS_PER_OP}",
            )

        # ── 4. Daily reallocation cap ─────────────────────────────────────────
        total_aum: float = float(portfolio_snapshot.get("total_aum_usdc", 0.0))
        proposed: float = float(portfolio_snapshot.get("proposed_move_usdc", 0.0))

        if total_aum > 0.0:
            daily_cap_usdc: float = total_aum * MAX_DAILY_REALLOC_FRACTION
            already_moved: float = float(state.get("daily_moved_usdc", 0.0))
            if already_moved + proposed > daily_cap_usdc:
                return (
                    False,
                    (
                        f"daily_limit_exceeded: already_moved={already_moved:.2f} "
                        f"proposed={proposed:.2f} cap={daily_cap_usdc:.2f} "
                        f"(30% of AUM {total_aum:.2f})"
                    ),
                )

        # ── 5. Circuit-breaker trigger (drawdown check — activates for NEXT op) ─
        drawdown_24h: float = float(portfolio_snapshot.get("drawdown_24h_pct", 0.0))
        if drawdown_24h > CIRCUIT_BREAKER_DRAWDOWN:
            # Trigger freeze, but still allow current snapshot evaluation to pass.
            # (The circuit breaker fires *after* this check for a consistent
            # semantics: "we noticed the breach, we are now freezing".)
            freeze_until = now + CIRCUIT_BREAKER_FREEZE_SECONDS
            self._state["circuit_breaker_until"] = freeze_until
            self._save_state()
            until_str = _ts_to_iso(freeze_until)
            return (
                False,
                (
                    f"circuit_breaker_triggered: drawdown {drawdown_24h*100:.2f}% "
                    f"> {CIRCUIT_BREAKER_DRAWDOWN*100:.0f}%, frozen until {until_str}"
                ),
            )

        return True, "allowed"

    def record_rebalance(self, amount_usdc: float) -> None:
        """
        Record a completed rebalance. Updates last_rebalance_ts and
        accumulates daily_moved_usdc. Persists state atomically.

        Args:
            amount_usdc: gross USDC volume moved (always positive).
        """
        now = time.time()
        self._maybe_reset_daily(now)

        self._state["last_rebalance_ts"] = now
        self._state["daily_moved_usdc"] = (
            float(self._state.get("daily_moved_usdc", 0.0)) + abs(amount_usdc)
        )
        self._save_state()

    def get_status(self) -> dict:
        """
        Return a human-readable snapshot of current rate-limiting state.

        Returns dict with:
          last_rebalance_ts, last_rebalance_iso, seconds_since_last,
          cooldown_remaining_s, daily_moved_usdc, daily_reset_iso,
          circuit_breaker_active, circuit_breaker_until_iso
        """
        now = time.time()
        self._maybe_reset_daily(now)

        state = self._state
        last_ts = state.get("last_rebalance_ts")
        cb_until = state.get("circuit_breaker_until")
        daily_reset = state.get("daily_reset_ts")

        seconds_since = (now - last_ts) if last_ts is not None else None
        cooldown_remaining = (
            max(0.0, COOLDOWN_SECONDS - seconds_since)
            if seconds_since is not None
            else None
        )

        return {
            "last_rebalance_ts": last_ts,
            "last_rebalance_iso": _ts_to_iso(last_ts) if last_ts else None,
            "seconds_since_last": seconds_since,
            "cooldown_remaining_s": cooldown_remaining,
            "daily_moved_usdc": float(state.get("daily_moved_usdc", 0.0)),
            "daily_reset_ts": daily_reset,
            "daily_reset_iso": _ts_to_iso(daily_reset) if daily_reset else None,
            "circuit_breaker_active": (
                cb_until is not None and now < cb_until
            ),
            "circuit_breaker_until": cb_until,
            "circuit_breaker_until_iso": _ts_to_iso(cb_until) if cb_until else None,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load persisted state or return a fresh empty state."""
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            # Merge with empty state to ensure all keys are present
            merged = dict(_EMPTY_STATE)
            merged.update(loaded)
            return merged
        except FileNotFoundError:
            return dict(_EMPTY_STATE)
        except (json.JSONDecodeError, OSError):
            return dict(_EMPTY_STATE)

    def _save_state(self) -> None:
        """Atomically persist current state to disk (tmp + os.replace)."""
        state_path = self._state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, state_path)
        except OSError:
            # Best-effort: if we can't persist, the in-memory state still works
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _maybe_reset_daily(self, now: float) -> None:
        """
        Reset daily_moved_usdc at UTC midnight (rolling calendar day).
        Idempotent within the same UTC day.
        """
        daily_reset_ts = self._state.get("daily_reset_ts")

        if daily_reset_ts is None:
            # First run — set reset point to start of today UTC
            self._state["daily_reset_ts"] = _start_of_utc_day(now)
            self._state["daily_moved_usdc"] = 0.0
            self._save_state()
            return

        # If current time is past the next reset boundary, roll over
        next_reset = daily_reset_ts + 86400  # 24 h
        if now >= next_reset:
            # Advance reset_ts to today's start (handles multi-day gaps)
            self._state["daily_reset_ts"] = _start_of_utc_day(now)
            self._state["daily_moved_usdc"] = 0.0
            self._save_state()


# ── Utility functions ─────────────────────────────────────────────────────────

def _ts_to_iso(ts: float) -> str:
    """Convert a Unix timestamp to an ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _start_of_utc_day(ts: float) -> float:
    """Return the Unix timestamp of midnight UTC for the day containing *ts*."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()
