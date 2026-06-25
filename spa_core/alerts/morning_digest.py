"""
spa_core/alerts/morning_digest.py — MP-1493 (Sprint v11.09)

Morning digest — sent at 08:05 UTC (after daily cycle at 08:00).
Summarises: overnight APY changes, evidence progress, any active alerts.

Invoked from launchd com.spa.morning_digest (08:05 daily).
Pure stdlib. Offline-safe. Atomic writes. LLM FORBIDDEN.
"""
from __future__ import annotations

import datetime
import html
import logging
from typing import Dict, List, Optional

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

    # Real paper track started 2026-06-10; everything before is demo/teardown.
    PAPER_REAL_START = "2026-06-10"

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
        """Build the morning digest message string.

        Never raises: every data helper is wrapped so a missing/renamed/corrupt
        state file degrades to a neutral default rather than crashing the digest.
        Dynamic values (strategy IDs like ``aave_v3``, alert text) are
        HTML-escaped so the message is safe under ``parse_mode="HTML"`` — the
        legacy Telegram Markdown parser 400s on ``_`` and ``<>``.
        """
        today = datetime.date.today().isoformat()

        golive_score = self._safe(self._get_golive_score, 0)
        evidence = self._safe(
            self._get_evidence_progress, {"effective_cycles": 0.0, "target": 30.0}
        )
        best_apy = self._safe(self._get_best_apy, 0.0)
        best_strategy = self._safe(self._get_best_strategy, "—")
        alerts = self._safe(self._get_pending_alerts, [])

        lines = [
            f"☀️ SPA Morning Digest — {today}",
            "",
            f"📊 GoLive Score: {golive_score}/100",
            f"📈 Best APY: {best_apy:.2%} ({html.escape(str(best_strategy))})",
            f"🧾 Evidence: {evidence['effective_cycles']:.1f}/{evidence['target']} pts",
            "",
        ]

        if alerts:
            lines.append(f"⚠️ Alerts: {len(alerts)} active")
            for a in alerts[:3]:
                msg = a.get("message", str(a)) if isinstance(a, dict) else str(a)
                lines.append(f"  • {html.escape(msg[:60])}")
        else:
            lines.append("✅ No active alerts")

        return "\n".join(lines)

    @staticmethod
    def _safe(fn, default):
        """Call ``fn()`` and return its result, or ``default`` on any error.

        Fail-safe wrapper so a single missing/corrupt data file can never abort
        the whole digest. Deterministic — LLM FORBIDDEN.
        """
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - intentional broad fail-safe
            log.warning("morning_digest helper %s failed: %s", getattr(fn, "__name__", fn), exc)
            return default

    def send(self) -> bool:
        """Compose and send the morning digest via Telegram. Fail-safe."""
        try:
            from spa_core.alerts.telegram_client import send_message  # type: ignore

            msg = self.compose()
            result = send_message(msg, parse_mode="HTML")

            self._data["last_sent"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
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
        """Return dict with effective_cycles and target.

        Counts only honest track days (>= PAPER_REAL_START); pre-teardown
        demo bars in the equity curve are excluded.
        """
        curve = atomic_load(
            self._path("data/equity_curve_daily.json"), default=[]
        )
        if isinstance(curve, dict):
            # Live shape uses "daily"; older snapshots used "entries".
            curve = curve.get("daily", curve.get("entries", []))

        honest = [
            e
            for e in curve
            if isinstance(e, dict) and e.get("date", "") >= self.PAPER_REAL_START
        ]
        days = len(honest) if honest else len(curve)
        return {"effective_cycles": float(days), "target": 30.0}

    def _get_best_apy(self) -> float:
        """Return the highest APY (as a fraction, e.g. 0.045) among positions.

        Positions may be a list of dicts (with per-position ``current_apy``)
        or a ``{protocol: amount}`` dict that carries no APY. When no
        per-position APY is available, fall back to the portfolio's blended
        expected APY, normalising percent values (e.g. 4.47) to a fraction.
        """
        status = atomic_load(
            self._path("data/paper_trading_status.json"), default={}
        )
        positions = status.get("positions", [])
        if not positions:
            pos_data = atomic_load(
                self._path("data/current_positions.json"), default={}
            )
            positions = pos_data.get("positions", [])
        else:
            pos_data = {}

        # List-of-dicts shape carries per-position APY.
        if isinstance(positions, list):
            apys = [
                p.get("current_apy", 0) or 0
                for p in positions
                if isinstance(p, dict)
            ]
            if apys:
                return max(apys)

        # Dict-shaped positions ({protocol: amount}) have no APY → fall back
        # to the blended expected/realised APY (stored as a percent).
        if not pos_data:
            pos_data = atomic_load(
                self._path("data/current_positions.json"), default={}
            )
        blended = (
            pos_data.get("tuner_expected_apy")
            or status.get("apy_today_pct")
            or 0.0
        )
        # Normalise percent (e.g. 4.47) to fraction (0.0447).
        return blended / 100.0 if blended > 1 else blended

    def _get_best_strategy(self) -> str:
        """Return strategy ID with highest APY from tournament results.

        Handles both the list shape (``[{strategy_id, net_apy, ...}]``) and a
        legacy ``{id: {apy}}`` dict shape.
        """
        results = atomic_load(
            self._path("data/tournament_results.json"), default={}
        )
        strategies = results.get("strategies", results.get("results", {}))
        if not strategies:
            return "—"

        def _apy(entry: Dict) -> float:
            return (
                entry.get("net_apy")
                or entry.get("apy")
                or entry.get("composite_score")
                or 0
            )

        if isinstance(strategies, list):
            best = max(
                (s for s in strategies if isinstance(s, dict)),
                key=_apy,
                default={},
            )
            return best.get("strategy_id") or best.get("id") or "—"

        best = max(
            strategies.items(),
            key=lambda x: _apy(x[1]) if isinstance(x[1], dict) else 0,
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

    args = sys.argv[1:]
    # --dry / --check: compose and print WITHOUT sending to Telegram (used by
    # tests/CI and for safe manual inspection). Any non-flag arg is base_dir.
    dry = any(a in ("--dry", "--check", "--dry-run") for a in args)
    positional = [a for a in args if not a.startswith("-")]
    base = positional[0] if positional else "."

    digest = MorningDigest(base_dir=base)
    msg = digest.compose()
    print(msg)
    print()

    if dry:
        print("dry-run → not sent")
        sys.exit(0)

    ok = digest.send()
    print(f"send() → {ok}")
    # Telegram delivery is best-effort and fail-safe: a failed send (e.g. no
    # Keychain creds, network down, flood guard) must NOT crash the launchd
    # agent with exit=1. The digest's job — composing the message — succeeded.
    sys.exit(0)
