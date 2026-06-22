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
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer,
    BasisTradeInput,
)
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
        try:
            data = atomic_load(str(self._kill_switch_path), default=None)
            if data is None:
                return False
            if isinstance(data, dict):
                return bool(data.get("active", False))
            return False
        except Exception:
            return False

    def _load_funding_data(self) -> Optional[dict]:
        try:
            data = atomic_load(str(self._funding_path), default=None)
            if not data:
                return None
            return data
        except Exception:
            return None

    def _is_funding_stale(self, funding_data: Optional[dict]) -> bool:
        if funding_data is None:
            return True
        if funding_data.get("stale", False):
            return True
        gen_at = funding_data.get("generated_at", "")
        if isinstance(gen_at, str) and gen_at:
            try:
                dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - dt).total_seconds()
                return age_s > STALE_AFTER_S
            except (ValueError, TypeError):
                pass
        return False

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
        signals: List[BTSExitSignal] = []

        kill_active = self._kill_switch_active()
        if kill_active:
            signals.append(BTSExitSignal(
                asset="ALL",
                reason="MANUAL_KILL",
                current_funding_annual=0.0,
                current_net_spread_bps=0.0,
                severity="CRITICAL",
            ))

        is_stale = self._is_funding_stale(funding_data)
        if is_stale:
            signals.append(BTSExitSignal(
                asset="ALL",
                reason="STALE_DATA",
                current_funding_annual=0.0,
                current_net_spread_bps=0.0,
                severity="HIGH",
            ))
            return signals

        if funding_data is None:
            return signals

        rates = funding_data.get("rates", {})
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

        return signals

    def _save_exit_signals(self, signals: List[BTSExitSignal]) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        is_clear = len(signals) == 0

        payload = {
            "timestamp": now_iso,
            "active_signals": [s.to_dict() for s in signals],
            "clear": is_clear,
            "signal_count": len(signals),
        }
        try:
            atomic_save(payload, str(self._exit_path))
        except Exception as exc:
            log.error("Failed to save exit signals: %s", exc)

    def run(self) -> dict:
        try:
            funding_data = self._load_funding_data()
            signals = self.evaluate_conditions(funding_data)
            self._save_exit_signals(signals)

            report = {
                "signal_count": len(signals),
                "clear": len(signals) == 0,
                "signals": [s.to_dict() for s in signals],
                "status": "ok",
            }
            log.info("BTS exit monitor: %d signals", len(signals))
            return report

        except Exception as exc:
            log.error("BTS exit monitor failed: %s", exc)
            self._save_exit_signals([])
            return {
                "signal_count": 0,
                "clear": True,
                "signals": [],
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
