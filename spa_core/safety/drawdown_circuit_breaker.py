"""
spa_core/safety/drawdown_circuit_breaker.py

Drawdown circuit breaker — pauses rebalancing if portfolio drawdown exceeds
threshold. Integrates with LiveTradingGate.

MP-1501 (v11.17) — stdlib only, no external dependencies, LLM FORBIDDEN.

Thresholds:
  MAX_DRAWDOWN_THRESHOLD = 5%   — trips the breaker
  RECOVERY_THRESHOLD     = 2%   — drawdown must fall below this to un-trip

Lifecycle:
  1. Call update_nav(current_nav) on each equity-curve point.
  2. Breaker auto-trips when drawdown >= 5%.
  3. Once tripped: NAV must exceed peak*(1-RECOVERY_THRESHOLD) before reset.
  4. Call assert_ok() at the top of any rebalancing logic; it raises GateError
     if the breaker is active.

Usage:
    cb = DrawdownCircuitBreaker()
    cb.update_nav(100_000)
    cb.update_nav(94_000)    # drawdown = 6% → tripped
    cb.assert_ok()           # raises GateError
"""
from __future__ import annotations

from spa_core.utils.errors import SPAError

__all__ = [
    "DrawdownCircuitBreaker",
    "MAX_DRAWDOWN_THRESHOLD",
    "RECOVERY_THRESHOLD",
]

MAX_DRAWDOWN_THRESHOLD: float = 0.05   # 5% drawdown trips the breaker
RECOVERY_THRESHOLD: float = 0.02       # 2% recovery needed to un-trip


class DrawdownCircuitBreaker:
    """
    Monitors portfolio NAV and pauses rebalancing on severe drawdown.

    State machine:
      OK      → drawdown < MAX_DRAWDOWN_THRESHOLD → stay OK
      OK      → drawdown >= MAX_DRAWDOWN_THRESHOLD → TRIPPED
      TRIPPED → new peak NAV (full recovery above peak) → OK
      TRIPPED → drawdown falls below RECOVERY_THRESHOLD → OK
      TRIPPED → drawdown >= RECOVERY_THRESHOLD → stay TRIPPED

    Peak NAV is updated whenever current NAV exceeds the stored peak
    (only while the breaker is NOT tripped — peak is frozen while tripped).
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = base_dir
        self._peak_nav: float = 0.0
        self._current_nav: float = 0.0
        self._tripped: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_nav(self, current_nav: float) -> dict:
        """
        Updates current NAV and re-evaluates circuit breaker state.

        Peak NAV tracking:
          - If not tripped and current > peak → update peak.
          - If tripped and drawdown < RECOVERY_THRESHOLD → un-trip and
            allow peak update on the next call.

        Args:
            current_nav: Current portfolio NAV in any consistent unit (USD).

        Returns:
            status() dict reflecting the updated state.
        """
        self._current_nav = current_nav

        if not self._tripped:
            # Update peak while circuit is healthy
            if current_nav > self._peak_nav:
                self._peak_nav = current_nav
            # Check whether we just breached the drawdown threshold
            if self._current_drawdown() >= MAX_DRAWDOWN_THRESHOLD:
                self._tripped = True
        else:
            # Already tripped — check for recovery
            if self._current_drawdown() < RECOVERY_THRESHOLD:
                self._tripped = False
                # After recovery allow peak to advance again
                if current_nav > self._peak_nav:
                    self._peak_nav = current_nav

        return self.status()

    def reset(self) -> None:
        """
        Hard resets the circuit breaker (for testing / manual override).
        Clears peak, current NAV, and tripped flag.
        """
        self._peak_nav = 0.0
        self._current_nav = 0.0
        self._tripped = False

    def status(self) -> dict:
        """
        Returns the current state as a JSON-serialisable dict.

        Keys:
          tripped          — bool; True if rebalancing is paused
          current_drawdown — fractional drawdown from peak (0.06 = 6%)
          peak_nav         — highest NAV seen while circuit was healthy
          current_nav      — most recently reported NAV
          message          — human-readable status string
        """
        return {
            "tripped": self._tripped,
            "current_drawdown": round(self._current_drawdown(), 8),
            "peak_nav": self._peak_nav,
            "current_nav": self._current_nav,
            "message": (
                "CIRCUIT BREAKER ACTIVE — rebalancing paused"
                if self._tripped
                else "OK"
            ),
        }

    def assert_ok(self) -> None:
        """
        Raises SPAError if the circuit breaker is tripped.

        Call this at the top of any rebalancing / allocation logic.

        Raises:
            SPAError: code="DRAWDOWN_CIRCUIT_BREAKER" when tripped.
        """
        if self._tripped:
            raise SPAError(
                f"Drawdown circuit breaker tripped: "
                f"{self._current_drawdown():.1%} drawdown from peak",
                code="DRAWDOWN_CIRCUIT_BREAKER",
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _current_drawdown(self) -> float:
        """Fractional drawdown from peak. Returns 0.0 if peak is zero."""
        if self._peak_nav == 0.0:
            return 0.0
        return (self._peak_nav - self._current_nav) / self._peak_nav
