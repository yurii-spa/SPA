"""
spa_core/alerts/apy_drift_alert.py — MP-1491 (Sprint v11.07)

Alerts when strategy APY drifts significantly from expected range.
Sends Telegram alert if APY drops > 20% from 7-day average.

Pure stdlib. Offline-safe (Telegram call wrapped in try/except).
Atomic writes only. LLM FORBIDDEN.
"""
from __future__ import annotations

import datetime
import logging
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.alerts.apy_drift")

APY_DRIFT_THRESHOLD = 0.20   # 20% relative drop triggers alert
LOOKBACK_DAYS = 7
OUTPUT_PATH = "data/apy_drift_alerts.json"


class APYDriftAlert(BaseAnalytics):
    """Monitors APY drift for all active strategies.

    Usage::
        alert = APYDriftAlert(base_dir="/path/to/repo")
        alerts = alert.run_all_strategies({"S0": 0.048, "S1": 0.031})
    """

    OUTPUT_PATH = OUTPUT_PATH

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._data: Dict = {
            "alerts": [],
            "last_check": None,
            "strategies": {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_drift(self, strategy_id: str, current_apy: float) -> Optional[Dict]:
        """Check if current APY has drifted from the 7-day average.

        Returns alert dict if drift > threshold, else None.
        """
        history = self._get_apy_history(strategy_id)
        if len(history) < 3:
            log.debug("Not enough history for %s (%d pts)", strategy_id, len(history))
            return None

        window = history[-LOOKBACK_DAYS:]
        avg_7d = sum(window) / len(window)

        if avg_7d == 0:
            log.debug("avg_7d is 0 for %s — skipping", strategy_id)
            return None

        drift = (avg_7d - current_apy) / avg_7d
        if drift > APY_DRIFT_THRESHOLD:
            severity = "HIGH" if drift > 0.40 else "MEDIUM"
            alert: Dict = {
                "strategy": strategy_id,
                "current_apy": current_apy,
                "avg_7d_apy": avg_7d,
                "drift_pct": drift * 100,
                "severity": severity,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
            log.warning(
                "APY drift alert %s: current=%.4f avg_7d=%.4f drift=%.1f%% sev=%s",
                strategy_id,
                current_apy,
                avg_7d,
                drift * 100,
                severity,
            )
            return alert

        return None

    def run_all_strategies(self, strategy_apys: Dict[str, float]) -> List[Dict]:
        """Check all strategies. Returns list of triggered alerts."""
        alerts: List[Dict] = []

        for strategy_id, current_apy in strategy_apys.items():
            alert = self.check_drift(strategy_id, current_apy)
            if alert:
                alerts.append(alert)
                self._send_telegram_alert(alert)

        self._data["alerts"] = alerts
        self._data["last_check"] = datetime.datetime.utcnow().isoformat()
        atomic_save(self._data, self._path(OUTPUT_PATH))
        return alerts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_apy_history(self, strategy_id: str) -> List[float]:
        """Reads APY history from data/strategy_apy_history.json."""
        path = self._path("data/strategy_apy_history.json")
        data = atomic_load(path, default={})
        entry = data.get(strategy_id, {})
        history = entry.get("apy_history", [])
        return [float(v) for v in history if v is not None]

    def _send_telegram_alert(self, alert: Dict) -> bool:
        """Sends Telegram alert for APY drift. Fail-safe."""
        try:
            from spa_core.alerts.telegram_client import send_message  # type: ignore

            msg = (
                f"⚠️ APY Drift Alert — {alert['strategy']}\n"
                f"Current: {alert['current_apy']:.2%}\n"
                f"7d avg: {alert['avg_7d_apy']:.2%}\n"
                f"Drift: -{alert['drift_pct']:.1f}%\n"
                f"Severity: {alert['severity']}"
            )
            return send_message(msg)
        except Exception as exc:
            log.warning("Telegram send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # BaseAnalytics required
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict:
        return self._data


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    base = "." if len(sys.argv) < 2 else sys.argv[1]
    checker = APYDriftAlert(base_dir=base)

    # Try to load current APYs from paper_trading_status.json
    status_path = checker._path("data/paper_trading_status.json")
    status = atomic_load(status_path, default={})
    strategies = status.get("strategy_apys", {})

    if not strategies:
        print("No strategy_apys in paper_trading_status.json — nothing to check.")
        sys.exit(0)

    alerts = checker.run_all_strategies(strategies)
    if alerts:
        print(f"Triggered {len(alerts)} APY drift alert(s):")
        for a in alerts:
            print(f"  [{a['severity']}] {a['strategy']}: drift={a['drift_pct']:.1f}%")
    else:
        print("No APY drift alerts triggered.")
    sys.exit(0)
