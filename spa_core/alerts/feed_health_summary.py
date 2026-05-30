"""
SPA-V347 — Aggregated APY-feed / covariance health summary.

Consolidates the NINE independent feed/covariance health signals tracked by
``spa_core/alerts/risk_monitor.py`` into ONE dashboard-ready status document
(``data/feed_health_summary.json``).

Each underlying monitor persists a small state file in ``data/`` with a
consecutive-degradation streak counter:

  1. covariance_health_state.json              — alert_covariance_degraded   (>=3)
  2. apy_feed_health_state.json                — alert_apy_feed_stale         (>=2)
  3. apy_feed_protocol_health_state.json       — alert_apy_feed_protocol_drop (>=1)
  4. apy_feed_tvl_health_state.json            — alert_apy_feed_tvl_drop      (>=1)
  5. apy_feed_anomaly_health_state.json        — alert_apy_feed_protocol_anomaly (>=1)
  6. apy_feed_schema_health_state.json         — alert_apy_feed_schema_drift  (>=1)
  7. apy_feed_protocol_stale_health_state.json — alert_apy_feed_protocol_stale(>=1)
  8. apy_feed_bounds_health_state.json         — alert_apy_feed_value_bounds  (>=1)
  9. apy_feed_monotonicity_health_state.json   — alert_apy_feed_date_monotonicity (>=1)

This module reads those state files (graceful on miss/corrupt), classifies each
signal as ok / warn / degraded / unknown against the monitor's OWN alert
threshold (mirrored verbatim), and rolls them up into a single
``overall_status`` (worst-of). It exists so the dashboard can show ONE health
badge instead of forcing the operator to mentally union six separate alerts.

Pure stdlib, no network, never raises on the happy path. Mirrors the
standalone-aggregator pattern of ``execution/adapter_status.py`` and
``analytics/covariance_export.py``.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Worst-of severity ordering. ``unknown`` ranks above ``ok`` (an unreadable
# state file is more concerning than a clean one) but below an active warn.
_SEVERITY: Dict[str, int] = {"ok": 0, "unknown": 1, "warn": 2, "degraded": 3}

# Registry: (key, state filename, human label, streak field, alert threshold).
# Thresholds mirror the ``should_alert = n >= …`` rules in risk_monitor.py.
SIGNALS: Tuple[Tuple[str, str, str, str, int], ...] = (
    ("covariance", "covariance_health_state.json",
     "Covariance source", "consecutive_degraded", 3),
    ("apy_feed_stale", "apy_feed_health_state.json",
     "APY feed staleness", "consecutive_stale", 2),
    ("protocol_drop", "apy_feed_protocol_health_state.json",
     "Protocol-count drop", "consecutive_drops", 1),
    ("tvl_drop", "apy_feed_tvl_health_state.json",
     "TVL drop", "consecutive_drops", 1),
    ("protocol_anomaly", "apy_feed_anomaly_health_state.json",
     "Per-protocol anomaly", "consecutive_anomalies", 1),
    ("schema_drift", "apy_feed_schema_health_state.json",
     "Feed schema drift", "consecutive_drifts", 1),
    ("protocol_stale", "apy_feed_protocol_stale_health_state.json",
     "Per-protocol staleness", "consecutive_stale", 1),
    ("value_bounds", "apy_feed_bounds_health_state.json",
     "Value bounds", "consecutive_bounds", 1),
    ("date_monotonicity", "apy_feed_monotonicity_health_state.json",
     "Date monotonicity", "consecutive_mono", 1),
)

# Default data dir: <repo>/data (spa_core/alerts/ -> parents[2] == repo root).
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

__all__ = [
    "SCHEMA_VERSION",
    "SIGNALS",
    "classify_streak",
    "evaluate_signal",
    "collect_feed_health",
    "build_summary_document",
    "write_feed_health_summary",
]


def classify_streak(streak: int, threshold: int) -> str:
    """ok if no streak, degraded at/above threshold, warn in between."""
    try:
        s = int(streak)
        t = int(threshold)
    except (TypeError, ValueError):
        return "unknown"
    if s <= 0:
        return "ok"
    if s >= t:
        return "degraded"
    return "warn"


def evaluate_signal(
    data_dir: Path,
    key: str,
    filename: str,
    label: str,
    streak_field: str,
    threshold: int,
) -> Dict[str, Any]:
    """
    Read one monitor's state file and classify it. Never raises.

    Missing state file == healthy (monitors treat a fresh/absent state as a
    zero streak). A present-but-unreadable file == ``unknown`` (we cannot
    verify freshness, so we surface it rather than silently calling it ok).
    """
    record: Dict[str, Any] = {
        "key": key,
        "label": label,
        "state_file": filename,
        "threshold": int(threshold),
        "streak": 0,
        "status": "ok",
        "last_alerted_cycle": None,
        "updated_at": None,
        "present": False,
    }
    try:
        path = Path(data_dir) / filename
        if not path.exists():
            # Monitor has never recorded degradation -> healthy.
            return record
        record["present"] = True
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            record["status"] = "unknown"
            return record
        streak = data.get(streak_field, 0)
        record["streak"] = int(streak) if isinstance(streak, (int, float)) else 0
        record["status"] = classify_streak(record["streak"], threshold)
        record["last_alerted_cycle"] = data.get("last_alerted_cycle")
        record["updated_at"] = data.get("updated_at")
    except Exception as exc:  # corrupt JSON, unreadable, etc.
        log.debug("evaluate_signal(%s): %s", key, exc)
        record["status"] = "unknown"
    return record


def _worst(statuses: List[str]) -> str:
    """Return the worst (highest-severity) status; ok if the list is empty."""
    worst = "ok"
    for s in statuses:
        if _SEVERITY.get(s, 0) > _SEVERITY.get(worst, 0):
            worst = s
    return worst


def collect_feed_health(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Evaluate all registered signals against ``data_dir``. Never raises."""
    d = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    out: List[Dict[str, Any]] = []
    for key, filename, label, streak_field, threshold in SIGNALS:
        out.append(
            evaluate_signal(d, key, filename, label, streak_field, threshold)
        )
    return out


def build_summary_document(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Build the full dashboard-ready summary document. Never raises."""
    signals = collect_feed_health(data_dir)
    counts: Dict[str, int] = {"ok": 0, "warn": 0, "degraded": 0, "unknown": 0}
    for s in signals:
        counts[s.get("status", "ok")] = counts.get(s.get("status", "ok"), 0) + 1
    overall = _worst([s.get("status", "ok") for s in signals])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "overall_status": overall,
        "signal_count": len(signals),
        "counts": counts,
        "signals": signals,
    }


def write_feed_health_summary(
    out_path: Optional[str] = None,
    *,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Build the summary and write it to ``out_path`` (default
    ``<data_dir>/feed_health_summary.json``). Returns the document.
    """
    d = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    target = Path(out_path) if out_path is not None else d / "feed_health_summary.json"
    doc = build_summary_document(d)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate APY-feed / covariance health into one summary."
    )
    parser.add_argument("--data-dir", default=None, help="state-file directory")
    parser.add_argument("--json", action="store_true", help="print the document")
    parser.add_argument(
        "--write",
        nargs="?",
        const="",
        default=None,
        help="write data/feed_health_summary.json (optional explicit PATH)",
    )
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else None
    if args.write is not None:
        out = args.write or None
        doc = write_feed_health_summary(out, data_dir=data_dir)
    else:
        doc = build_summary_document(data_dir)
    if args.json or args.write is None:
        print(json.dumps(doc, indent=2))
    else:
        print(f"overall_status={doc['overall_status']} counts={doc['counts']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
