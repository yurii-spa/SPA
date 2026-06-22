"""
spa_core/alerts/morning_digest.py — MP-1493 (Sprint v11.09)

Morning digest — sent at 08:05 UTC (after daily cycle at 08:00).
Summarises: overnight APY changes, evidence progress, any active alerts.

Invoked from launchd com.spa.morning_digest (08:05 daily).
Pure stdlib. Offline-safe. Atomic writes. LLM FORBIDDEN.
"""
from __future__ import annotations

import datetime
import logging
from typing import Dict, List

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_load

log = logging.getLogger("spa.alerts.morning_digest")

OUTPUT_PATH = "data/morning_digest.json"


class MorningDigest(BaseAnalytics):
    """Composes and sends the daily morning digest via Telegram.

    Usage::
        md = MorningDigest(base_dir="/path/to/repo")
        md.send()
    """

    OUTPUT_PATH = OUTPUT_PATH

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        import os as _os
        self._base_dir = _os.path.abspath(base_dir)
        self._data: Dict = {
            "last_sent": None,
            "last_digest": "",
            "send_count": 0,
        }

    def _path(self, relative: str) -> str:
        """Resolve relative path against repo root. Overrides BaseAnalytics._path for safety."""
        import os as _os
        return _os.path.join(self._base_dir, relative)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose(self) -> str:
        """Build the morning digest message string."""
        today = datetime.date.today().isoformat()

        golive_score = self._get_golive_score()
        evidence = self._get_evidence_progress()
        best_apy = self._get_best_apy()
        best_strategy = self._get_best_strategy()
        alerts = self._get_pending_alerts()

        lines = [
            f"☀️ SPA Morning Digest — {today}",
            "",
            f"📊 GoLive Score: {golive_score}/100",
            f"📈 Best APY: {best_apy:.2%} ({best_strategy})",
            f"🧾 Evidence: {evidence['effective_cycles']:.1f}/{evidence['target']} pts",
            "",
        ]

        if alerts:
            lines.append(f"⚠️ Alerts: {len(alerts)} active")
            for a in alerts[:3]:
                msg = a.get("message", str(a))
                lines.append(f"  • {msg[:60]}")
        else:
            lines.append("✅ No active alerts")

        return "\n".join(lines)

    def send(self) -> bool:
        """Compose and send the morning digest via Telegram. Fail-safe."""
        try:
            from spa_core.alerts.telegram_client import send_message  # type: ignore

            msg = self.compose()
            result = send_message(msg)

            self._data["last_sent"] = datetime.datetime.utcnow().isoformat()
            self._data["last_digest"] = msg
            self._data["send_count"] = self._data.get("send_count", 0) + 1
            self.save()

            return result
        except Exception as exc:
            log.warning("Morning digest send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_golive_score(self) -> int:
        """Return GoLive score (0–100). Uses readiness report if available."""
        try:
            from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport  # type: ignore

            r = GoLiveReadinessReport(self.base_dir)
            return int(r.generate_report().get("total_score", 0))
        except Exception:
            pass

        # Fallback: derive from golive_status.json
        status = atomic_load(self._path("data/golive_status.json"), default={})
        passed = status.get("passed", 0)
        total = status.get("total", 26)
        if total:
            return int(passed / total * 100)
        return 0

    def _get_evidence_progress(self) -> Dict:
        """Return dict with effective_cycles and target."""
        curve = atomic_load(
            self._path("data/equity_curve_daily.json"), default=[]
        )
        if isinstance(curve, dict):
            curve = curve.get("entries", [])

        days = len(curve)
        return {"effective_cycles": float(days), "target": 30.0}

    def _get_best_apy(self) -> float:
        """Return the highest APY among active positions."""
        status = atomic_load(
            self._path("data/paper_trading_status.json"), default={}
        )
        positions = status.get("positions", [])
        if not positions:
            pos_data = atomic_load(
                self._path("data/current_positions.json"), default={}
            )
            positions = pos_data.get("positions", [])

        if not positions:
            return 0.0

        return max(
            (p.get("current_apy", 0) or 0) for p in positions
        )

    def _get_best_strategy(self) -> str:
        """Return strategy ID with highest APY from tournament results."""
        results = atomic_load(
            self._path("data/tournament_results.json"), default={}
        )
        strategies = results.get("strategies", results.get("results", {}))
        if not strategies:
            return "—"

        best = max(
            strategies.items(),
            key=lambda x: x[1].get("apy", 0) if isinstance(x[1], dict) else 0,
            default=(None, {}),
        )
        return best[0] or "—"

    def _get_pending_alerts(self) -> List[Dict]:
        """Return recent APY drift alerts (last run)."""
        data = atomic_load(
            self._path("data/apy_drift_alerts.json"), default={}
        )
        raw = data.get("alerts", [])
        # Normalise to list of dicts with a "message" key
        result: List[Dict] = []
        for a in raw:
            if isinstance(a, dict):
                if "message" not in a:
                    strat = a.get("strategy", "?")
                    drift = a.get("drift_pct", 0)
                    a = dict(a, message=f"APY drift {strat}: -{drift:.1f}%")
                result.append(a)
        return result

    # ------------------------------------------------------------------
    # BaseAnalytics required
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict:
        return self._data


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    base = "." if len(sys.argv) < 2 else sys.argv[1]
    digest = MorningDigest(base_dir=base)
    msg = digest.compose()
    print(msg)
    print()
    ok = digest.send()
    print(f"send() → {ok}")
    sys.exit(0 if ok else 1)
