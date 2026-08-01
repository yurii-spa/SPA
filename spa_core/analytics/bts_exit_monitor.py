"""
bts_exit_monitor.py — BTS Exit Monitor.

Checks active basis trades for exit conditions.
Advisory only — produces exit SIGNALS, never executes.

Exit conditions:
  - FUNDING_REVERSAL: perp_funding_annual < -0.05
  - SPREAD_COMPRESSED: net_spread_bps < 10
  - STALE_DATA: perp_funding_rates.json is stale
  - MANUAL_KILL: bts_kill_switch.json active

Atomic writes: tmp-file + os.replace. stdlib only.
Never raises exceptions outward (fail-safe).

Honesty contract (cycle #78). The funding payload is read through
`spa_core.feeds.funding_schema` — the same reader `bts_monitor` uses, deliberately in
one place, because these two modules carried an identical defect and fixing one would
have left its twin alive. Before that, both asked for `rates` / `generated_at`, keys the
producer never writes, so this monitor published `clear: True, 0 signals` about exit
conditions it had not evaluated once. Now: an unmeasurable check is listed verbatim in
`unchecked[]` (never promoted to a signal — severities and thresholds are untouched),
and a crashed run publishes `clear: null`, not `clear: True`.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer,
    BasisTradeInput,
    BasisTradeResult,
)
from spa_core.feeds.funding_schema import feed_age_seconds, read_rates
from spa_core.utils.atomic import atomic_save, atomic_load

log = logging.getLogger("spa.analytics.bts_exit_monitor")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

EXIT_FILE = "bts_exit_signals.json"
FUNDING_FILE = "perp_funding_rates.json"
KILL_SWITCH_FILE = "bts_kill_switch.json"
ACTIVE_TRADES_FILE = "bts_active_trades.json"

FUNDING_REVERSAL_THRESHOLD = -0.05
SPREAD_FLOOR_BPS = 10.0
STALE_AFTER_S = 1800
EVENTS_MAX = 50


@dataclass
class BTSExitSignal:
    asset: str
    reason: str
    current_funding_annual: float
    current_net_spread_bps: float
    severity: str

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "reason": self.reason,
            "current_funding_annual": round(self.current_funding_annual, 6),
            "current_net_spread_bps": round(self.current_net_spread_bps, 1),
            "severity": self.severity,
        }


class BTSExitMonitor:
    """
    Checks basis trade positions for exit conditions.

    Advisory only — emits exit signals, never executes.
    Reads funding rates and kill switch status.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        analyzer: Optional[BasisTradeAnalyzer] = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._exit_path = self._data_dir / EXIT_FILE
        self._funding_path = self._data_dir / FUNDING_FILE
        self._kill_switch_path = self._data_dir / KILL_SWITCH_FILE
        self._active_trades_path = self._data_dir / ACTIVE_TRADES_FILE
        self._analyzer = analyzer or BasisTradeAnalyzer()

    def _kill_switch_active(self) -> bool:
        """Back-compat wrapper: the flag only, the "could not read it" reason discarded."""
        return self._kill_switch_read()[0]

    def _kill_switch_read(self) -> Tuple[bool, Optional[str]]:
        """(active, unchecked reason).

        An ABSENT file means "not armed" — that is the documented semantics of this
        BTS-local manual flag and it stays exactly as it was. A file that exists but
        cannot be read, or holds something other than a mapping, is NOT "off": that is
        an unmeasured check and it is now said out loud. This does not touch the global
        two-tier kill-switch (`spa_core/governance/kill_switch.py`) in any way.
        """
        if not self._kill_switch_path.exists():
            return False, None
        try:
            data = atomic_load(str(self._kill_switch_path), default=None)
        except Exception as exc:
            return False, f"BTS kill-switch file unreadable: {exc}"
        if data is None:
            return False, (
                f"BTS kill-switch file {self._kill_switch_path.name} exists but read "
                f"back as nothing"
            )
        if isinstance(data, dict):
            return bool(data.get("active", False)), None
        return False, (
            f"BTS kill-switch file holds {type(data).__name__}, not a mapping — "
            f"'active' NOT MEASURED"
        )

    def _load_funding_data(self) -> Optional[dict]:
        try:
            data = atomic_load(str(self._funding_path), default=None)
            if not data:
                return None
            return data
        except Exception:
            return None

    def _is_funding_stale(self, funding_data: Optional[dict]) -> bool:
        """Back-compat wrapper: the verdict only, the "could not read it" reason discarded."""
        return self._funding_stale_read(funding_data)[0]

    def _funding_stale_read(
        self, funding_data: Optional[dict]
    ) -> Tuple[bool, Optional[str]]:
        """(stale, unchecked reason). Threshold STALE_AFTER_S is unchanged.

        Pre-#78 this asked for `generated_at`, which the live feed never writes, so the
        age arm never ran and every live payload came back "fresh" by default. Now the
        age is read from what the producer actually writes, and an age that cannot be
        computed is reported instead of passing for fresh.
        """
        if funding_data is None:
            return True, None
        if funding_data.get("stale", False):
            return True, None
        age = feed_age_seconds(funding_data)
        if age.measured and age.age_seconds is not None:
            return age.age_seconds > STALE_AFTER_S, None
        return False, f"feed age NOT MEASURED — {age.unchecked}"

    def _load_active_trades(self) -> List[dict]:
        try:
            data = atomic_load(str(self._active_trades_path), default=None)
            if data is None:
                return []
            if isinstance(data, dict):
                return data.get("trades", [])
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def evaluate_conditions(
        self,
        funding_data: Optional[dict],
    ) -> List[BTSExitSignal]:
        """Exit signals only. See `evaluate_with_reasons` for what was NOT measured."""
        return self.evaluate_with_reasons(funding_data)[0]

    def evaluate_with_reasons(
        self,
        funding_data: Optional[dict],
    ) -> Tuple[List[BTSExitSignal], List[str]]:
        """(signals, verbatim reasons for checks that could not be performed).

        Severities and thresholds are untouched: an unmeasured check never becomes a
        signal here. It is reported alongside, so "no exit signals" can no longer be
        read as "everything was checked and is fine".
        """
        signals: List[BTSExitSignal] = []
        unchecked: List[str] = []

        kill_active, kill_unchecked = self._kill_switch_read()
        if kill_unchecked:
            unchecked.append(kill_unchecked)
        if kill_active:
            signals.append(BTSExitSignal(
                asset="ALL",
                reason="MANUAL_KILL",
                current_funding_annual=0.0,
                current_net_spread_bps=0.0,
                severity="CRITICAL",
            ))

        is_stale, stale_unchecked = self._funding_stale_read(funding_data)
        if stale_unchecked:
            unchecked.append(stale_unchecked)
        if is_stale:
            signals.append(BTSExitSignal(
                asset="ALL",
                reason="STALE_DATA",
                current_funding_annual=0.0,
                current_net_spread_bps=0.0,
                severity="HIGH",
            ))
            return signals, unchecked

        if funding_data is None:
            return signals, unchecked

        rates_read = read_rates(funding_data)
        if not rates_read.measured:
            log.info("Exit conditions NOT MEASURED: %s", rates_read.unchecked)
            unchecked.append(
                f"per-asset exit conditions NOT MEASURED — {rates_read.unchecked}"
            )
            return signals, unchecked
        rates = rates_read.rates
        tracked = ("ETH", "BTC", "SOL")

        for asset in tracked:
            rate_info = rates.get(asset)
            if not rate_info:
                continue

            funding_annual = rate_info.get("funding_rate_annual")
            if funding_annual is None:
                continue

            try:
                funding_annual = float(funding_annual)
            except (ValueError, TypeError):
                continue

            default_spot = 0.05
            inp = BasisTradeInput(
                asset=asset,
                spot_yield_annual=default_spot,
                perp_funding_annual=funding_annual,
                execution_cost_bps=20.0,
                capital_usd=20000.0,
            )
            result = self._analyzer.analyze(inp)
            net_spread = result.net_spread_bps

            if funding_annual < FUNDING_REVERSAL_THRESHOLD:
                signals.append(BTSExitSignal(
                    asset=asset,
                    reason="FUNDING_REVERSAL",
                    current_funding_annual=funding_annual,
                    current_net_spread_bps=net_spread,
                    severity="CRITICAL",
                ))
            elif funding_annual < 0:
                signals.append(BTSExitSignal(
                    asset=asset,
                    reason="FUNDING_NEGATIVE",
                    current_funding_annual=funding_annual,
                    current_net_spread_bps=net_spread,
                    severity="HIGH",
                ))

            if net_spread < SPREAD_FLOOR_BPS:
                already_has = any(
                    s.asset == asset and s.reason in ("FUNDING_REVERSAL", "FUNDING_NEGATIVE")
                    for s in signals
                )
                signals.append(BTSExitSignal(
                    asset=asset,
                    reason="SPREAD_COMPRESSED",
                    current_funding_annual=funding_annual,
                    current_net_spread_bps=net_spread,
                    severity="HIGH" if not already_has else "MEDIUM",
                ))

        return signals, unchecked

    def _save_exit_signals(
        self,
        signals: List[BTSExitSignal],
        unchecked: Optional[List[str]] = None,
        measured: bool = True,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        unchecked = list(unchecked or [])
        # `clear` is a claim: "checked, nothing says exit". When the check did not run
        # (a crash), there is no such claim to make — None, never True.
        is_clear: Optional[bool] = (len(signals) == 0) if measured else None

        payload = {
            "timestamp": now_iso,
            "active_signals": [s.to_dict() for s in signals],
            "clear": is_clear,
            "signal_count": len(signals),
            "unchecked": unchecked,
            "measured": measured,
        }
        try:
            atomic_save(payload, str(self._exit_path))
        except Exception as exc:
            log.error("Failed to save exit signals: %s", exc)

    def run(self) -> dict:
        try:
            funding_data = self._load_funding_data()
            signals, unchecked = self.evaluate_with_reasons(funding_data)
            self._save_exit_signals(signals, unchecked)

            report = {
                "signal_count": len(signals),
                "clear": len(signals) == 0,
                "signals": [s.to_dict() for s in signals],
                "unchecked": unchecked,
                "status": "unchecked" if unchecked else "ok",
            }
            log.info(
                "BTS exit monitor: %d signals, %d unchecked", len(signals), len(unchecked)
            )
            return report

        except Exception as exc:
            log.error("BTS exit monitor failed: %s", exc)
            # A crashed run used to publish `clear: True` — "no reason to exit" about a
            # check that never finished. It now refuses (fail-CLOSED, invariant #2).
            self._save_exit_signals([], [f"exit check crashed: {exc}"], measured=False)
            return {
                "signal_count": 0,
                "clear": None,
                "signals": [],
                "unchecked": [f"exit check crashed: {exc}"],
                "status": "error",
                "error": str(exc),
            }


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="BTS Exit Monitor")
    parser.add_argument("--run", action="store_true", help="Run exit check")
    parser.add_argument("--check", action="store_true", help="Read-only check")
    args = parser.parse_args()

    if args.run or args.check:
        monitor = BTSExitMonitor()
        result = monitor.run()
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(0)
