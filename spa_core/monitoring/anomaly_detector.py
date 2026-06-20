#!/usr/bin/env python3
"""Anomaly detector (MP-1579 / Improvement 4).

Compares the current cycle's snapshot against the previous one and raises an
alert for any of four anomaly classes:

  * ``apy_spike``     — a protocol's APY jumped to more than 2× its prior value
                         (likely a data error / mis-parse upstream).
  * ``apy_zero``      — a protocol's APY dropped to 0 from a positive value
                         (likely an adapter failure / dead feed).
  * ``position_zero`` — a held position suddenly went to 0 USD
                         (possible liquidation / forced exit signal).
  * ``equity_drop``   — portfolio equity fell more than 1 % in a single cycle.

Each detected anomaly is logged, alerted to Telegram, and appended to
``data/anomaly_log.json`` (ring-buffer).

Design / safety
===============
* STRICTLY READ-ONLY / MONITORING. Reads JSON, sends an alert, writes its own
  log file. Touches NO allocator / risk / execution state and NO capital.
* No LLM — ``monitoring`` is in ``LLM_FORBIDDEN_AGENTS``. Pure deterministic
  thresholds.
* Stdlib only. Atomic writes. Fail-safe: bad/missing data yields zero
  anomalies rather than raising; a Telegram failure never raises.

CLI
===
    python3 -m spa_core.monitoring.anomaly_detector --check     # detect + print, no write/alert
    python3 -m spa_core.monitoring.anomaly_detector --run       # + log + telegram
    python3 -m spa_core.monitoring.anomaly_detector --run --no-telegram
    python3 -m spa_core.monitoring.anomaly_detector --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Thresholds (deterministic)
APY_SPIKE_MULTIPLE = 2.0     # new APY > 2× old APY → spike
EQUITY_DROP_PCT = 1.0        # single-cycle equity drop beyond this % → alert
_MIN_APY_FOR_SPIKE = 0.01    # ignore spikes from near-zero baselines (noise)

ANOMALY_LOG_CAP = 200        # ring-buffer size for data/anomaly_log.json

# Anomaly kinds
KIND_APY_SPIKE = "apy_spike"
KIND_APY_ZERO = "apy_zero"
KIND_POSITION_ZERO = "position_zero"
KIND_EQUITY_DROP = "equity_drop"

SEVERITY = {
    KIND_APY_SPIKE: "warning",
    KIND_APY_ZERO: "critical",
    KIND_POSITION_ZERO: "critical",
    KIND_EQUITY_DROP: "critical",
}


@dataclass
class Anomaly:
    kind: str
    severity: str
    subject: str         # protocol name or "portfolio"
    message: str
    old_value: float = 0.0
    new_value: float = 0.0
    detected_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── helpers ────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path, default: Any) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("anomaly_detector: unreadable %s (%s)", path, exc)
        return default


def _as_apy_map(snapshot: Any) -> Dict[str, float]:
    """Normalise an adapter/APY snapshot into ``{protocol: apy_pct}``."""
    out: Dict[str, float] = {}

    def _apy(d: dict):
        return d.get("apy", d.get("apy_pct", d.get("net_apy")))

    if isinstance(snapshot, dict):
        protos = snapshot.get("protocols")
        if isinstance(protos, list):
            for p in protos:
                if isinstance(p, dict):
                    name = p.get("name") or p.get("protocol") or p.get("id")
                    if name is not None:
                        out[str(name)] = _coerce_float(_apy(p))
        else:
            for name, p in snapshot.items():
                if isinstance(p, dict):
                    out[str(name)] = _coerce_float(_apy(p))
                else:
                    out[str(name)] = _coerce_float(p)
    elif isinstance(snapshot, list):
        for p in snapshot:
            if isinstance(p, dict):
                name = p.get("name") or p.get("protocol") or p.get("id")
                if name is not None:
                    out[str(name)] = _coerce_float(_apy(p))
    return out


# ─── detection (pure) ───────────────────────────────────────────────────────


def detect_apy_anomalies(
    prev_apys: Dict[str, float],
    curr_apys: Dict[str, float],
) -> List[Anomaly]:
    """APY spikes (>2×) and zero-drops (positive → 0) across protocols."""
    anomalies: List[Anomaly] = []
    prev = {k: _coerce_float(v) for k, v in (prev_apys or {}).items()}
    curr = {k: _coerce_float(v) for k, v in (curr_apys or {}).items()}
    for proto, new_v in curr.items():
        old_v = prev.get(proto)
        if old_v is None:
            continue  # newly added protocol — no baseline to compare
        # spike: positive baseline, new > 2× old
        if old_v >= _MIN_APY_FOR_SPIKE and new_v > APY_SPIKE_MULTIPLE * old_v:
            anomalies.append(Anomaly(
                kind=KIND_APY_SPIKE,
                severity=SEVERITY[KIND_APY_SPIKE],
                subject=proto,
                message=(f"APY spike on {proto}: {old_v:.2f}% → {new_v:.2f}% "
                         f"(>{APY_SPIKE_MULTIPLE:g}×) — possible data error"),
                old_value=round(old_v, 6),
                new_value=round(new_v, 6),
                detected_at=_utc_now_iso(),
            ))
        # zero-drop: was positive, now exactly 0
        elif old_v > 0 and new_v == 0:
            anomalies.append(Anomaly(
                kind=KIND_APY_ZERO,
                severity=SEVERITY[KIND_APY_ZERO],
                subject=proto,
                message=(f"APY dropped to 0 on {proto} (was {old_v:.2f}%) "
                         "— possible adapter failure"),
                old_value=round(old_v, 6),
                new_value=0.0,
                detected_at=_utc_now_iso(),
            ))
    return anomalies


def detect_position_anomalies(
    prev_positions: Dict[str, float],
    curr_positions: Dict[str, float],
) -> List[Anomaly]:
    """Held positions that suddenly went to 0 USD (liquidation signal)."""
    anomalies: List[Anomaly] = []
    prev = {k: _coerce_float(v) for k, v in (prev_positions or {}).items()}
    curr = {k: _coerce_float(v) for k, v in (curr_positions or {}).items()}
    for proto, old_v in prev.items():
        if old_v <= 0:
            continue
        new_v = curr.get(proto, 0.0)
        if new_v == 0:
            anomalies.append(Anomaly(
                kind=KIND_POSITION_ZERO,
                severity=SEVERITY[KIND_POSITION_ZERO],
                subject=proto,
                message=(f"Position on {proto} dropped to $0 "
                         f"(was ${old_v:,.2f}) — possible liquidation"),
                old_value=round(old_v, 6),
                new_value=0.0,
                detected_at=_utc_now_iso(),
            ))
    return anomalies


def detect_equity_drop(prev_equity: float, curr_equity: float) -> List[Anomaly]:
    """Single-cycle equity drop beyond ``EQUITY_DROP_PCT``."""
    prev = _coerce_float(prev_equity)
    curr = _coerce_float(curr_equity)
    if prev <= 0:
        return []
    drop_pct = (prev - curr) / prev * 100.0
    if drop_pct > EQUITY_DROP_PCT:
        return [Anomaly(
            kind=KIND_EQUITY_DROP,
            severity=SEVERITY[KIND_EQUITY_DROP],
            subject="portfolio",
            message=(f"Equity dropped {drop_pct:.2f}% in one cycle "
                     f"(${prev:,.2f} → ${curr:,.2f})"),
            old_value=round(prev, 2),
            new_value=round(curr, 2),
            detected_at=_utc_now_iso(),
        )]
    return []


# ─── The detector ───────────────────────────────────────────────────────────


class AnomalyDetector:
    """Detects, alerts and logs anomalies between two cycle snapshots."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        sender: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._sender = sender

    # -- detect ---------------------------------------------------------------

    def detect(
        self,
        *,
        prev_apys: Optional[Dict[str, float]] = None,
        curr_apys: Optional[Dict[str, float]] = None,
        prev_positions: Optional[Dict[str, float]] = None,
        curr_positions: Optional[Dict[str, float]] = None,
        prev_equity: float = 0.0,
        curr_equity: float = 0.0,
    ) -> List[Anomaly]:
        out: List[Anomaly] = []
        out += detect_apy_anomalies(prev_apys or {}, curr_apys or {})
        out += detect_position_anomalies(prev_positions or {}, curr_positions or {})
        out += detect_equity_drop(prev_equity, curr_equity)
        return out

    def detect_from_state(self) -> List[Anomaly]:
        """Read current + previous snapshots from data/ and detect. Fail-safe."""
        snap = _read_json(self.data_dir / "anomaly_snapshot.json", {})
        status = _read_json(self.data_dir / "paper_trading_status.json", {})
        adapters = _read_json(self.data_dir / "adapter_snapshot.json", {})
        equity = _read_json(self.data_dir / "equity_curve_daily.json", {})

        curr_apys = _as_apy_map(adapters)
        curr_positions = {}
        curr_equity = 0.0
        if isinstance(status, dict):
            curr_positions = status.get("current_positions") or {}
            curr_equity = _coerce_float(status.get("current_equity"))
        if not curr_equity and isinstance(equity, dict):
            daily = equity.get("daily")
            if isinstance(daily, list) and daily and isinstance(daily[-1], dict):
                curr_equity = _coerce_float(daily[-1].get("equity"))

        prev = snap if isinstance(snap, dict) else {}
        return self.detect(
            prev_apys=prev.get("apys") or {},
            curr_apys=curr_apys,
            prev_positions=prev.get("positions") or {},
            curr_positions=curr_positions,
            prev_equity=_coerce_float(prev.get("equity")),
            curr_equity=curr_equity,
        )

    # -- alert ----------------------------------------------------------------

    @staticmethod
    def format_alert(anomaly: Anomaly) -> str:
        icon = "🚨" if anomaly.severity == "critical" else "⚠️"
        return (f"{icon} <b>SPA Anomaly [{anomaly.kind}]</b>\n"
                f"{anomaly.message}")

    def _default_sender(self, text: str) -> bool:
        try:
            from spa_core.telegram.bot import TelegramBot
            bot = TelegramBot()
            if not bot.token or not bot.chat_id:
                return False
            resp = bot.send_message(text, parse_mode="HTML")
            return bool(resp and resp.get("ok"))
        except Exception as exc:  # noqa: BLE001
            log.warning("anomaly_detector: telegram failed (%s)", exc)
            return False

    def alert(self, anomalies: List[Anomaly]) -> int:
        """Send a Telegram alert per anomaly. Returns count successfully sent."""
        sender = self._sender or self._default_sender
        sent = 0
        for a in anomalies:
            log.warning("ANOMALY %s/%s: %s", a.kind, a.severity, a.message)
            try:
                if sender(self.format_alert(a)):
                    sent += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("anomaly_detector: sender raised (%s)", exc)
        return sent

    # -- log ------------------------------------------------------------------

    def log_anomalies(self, anomalies: List[Anomaly]) -> None:
        """Append anomalies to data/anomaly_log.json (ring-buffer)."""
        if not anomalies:
            return
        path = self.data_dir / "anomaly_log.json"
        doc = _read_json(path, {})
        if not isinstance(doc, dict):
            doc = {}
        entries = doc.get("anomalies")
        if not isinstance(entries, list):
            entries = []
        entries.extend(a.to_dict() for a in anomalies)
        if len(entries) > ANOMALY_LOG_CAP:
            entries = entries[-ANOMALY_LOG_CAP:]
        doc["anomalies"] = entries
        doc["last_updated"] = _utc_now_iso()
        doc["count"] = len(entries)
        try:
            atomic_save(doc, str(path))
        except OSError as exc:
            log.warning("anomaly_detector: log write failed (%s)", exc)

    # -- orchestrate ----------------------------------------------------------

    def run(self, *, alert: bool = True, write: bool = True) -> Dict[str, Any]:
        anomalies = self.detect_from_state()
        sent = 0
        if alert and anomalies:
            sent = self.alert(anomalies)
        if write:
            self.log_anomalies(anomalies)
        return {
            "count": len(anomalies),
            "telegram_sent": sent,
            "anomalies": [a.to_dict() for a in anomalies],
        }


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anomaly_detector",
        description="Detect cycle anomalies (read-only, monitoring).",
    )
    parser.add_argument("--run", action="store_true", help="detect + log + telegram")
    parser.add_argument("--check", action="store_true",
                        help="detect + print only (no log, no alert)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="with --run: log but skip Telegram")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    det = AnomalyDetector(data_dir=Path(args.data_dir) if args.data_dir else None)

    if args.run:
        result = det.run(alert=not args.no_telegram, write=True)
    else:
        anomalies = det.detect_from_state()
        result = {"count": len(anomalies),
                  "anomalies": [a.to_dict() for a in anomalies]}

    print(f"anomalies detected: {result['count']}")
    for a in result["anomalies"]:
        print(f"  [{a['severity']}] {a['kind']}: {a['message']}")
    if args.run:
        print(f"(telegram_sent={result.get('telegram_sent', 0)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
