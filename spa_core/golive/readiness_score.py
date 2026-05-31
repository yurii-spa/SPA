"""
SPA-V361 — Consolidated Go-Live operational readiness score.

Rolls THREE already-emitted operational surfaces into ONE composite score
document (``data/golive_readiness_score.json``) so the Go-Live dashboard can
show a single headline "NN/100" readiness figure instead of forcing the
operator to mentally union three separate signals:

  1. feed_health   — overall feed/covariance health
                     (``spa_core.alerts.feed_health_summary``).
  2. mev_coverage  — MEV-routing coverage of live-broadcast adapters
                     (``spa_core.execution.adapter_status`` ->
                     ``mev_protection.coverage.coverage_pct``).
  3. live_apy      — whether live APY enrichment is enabled (dry-run is the
                     expected pre-go-live posture, so ``False`` is warn, not a
                     hard fail).

This is a PURE READ-ONLY CONSOLIDATION of data those modules already emit. It
does NOT introduce a new feed-health monitor (SPA-BL-011 governance freeze is
respected) and touches NO money-moving code. It is also distinct from -- and
deliberately does NOT duplicate -- the paper-trading checklist verdict
(``spa_core/golive/checklist.py`` -> ``data/golive_readiness.json``); that is a
go/no-go checklist, whereas this is a live OPERATIONAL readiness score.

Each component contributes a sub-score (0-100) and a status; the composite
``overall_score`` is the mean of the three sub-scores and ``overall_status`` is
the worst-of the three statuses (mirroring the worst-of severity pattern in
``feed_health_summary.py``). Every component fetch is individually guarded so a
single failing source yields a component with ``status="unknown"`` / ``score=0``
and an ``"error"`` note -- the top-level build NEVER raises.

Pure stdlib, no network beyond what the underlying read-only sources already do,
deterministic on the happy path. Mirrors the standalone-aggregator pattern of
``alerts/feed_health_summary.py`` and ``execution/adapter_status.py``.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Worst-of severity ordering per the SPA-V361 spec: an unreadable source is the
# most concerning outcome.
_SEVERITY: Dict[str, int] = {"ok": 0, "warn": 1, "degraded": 2, "unknown": 3}

# Target go-live date (informational; surfaced for the dashboard countdown).
TARGET_DATE = "2026-07-15"

# Default data dir: <repo>/data (spa_core/golive/ -> parents[2] == repo root).
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# SPA-V363 -- persistent score history / trend (sparkline on the dashboard).
# Compact append-only log of the headline score over time. MAX_HISTORY ~= 30
# days at 6 export cycles/day; oldest entries are trimmed off the front.
HISTORY_FILENAME = "golive_readiness_score_history.json"
MAX_HISTORY = 180

__all__ = [
    "SCHEMA_VERSION",
    "TARGET_DATE",
    "HISTORY_FILENAME",
    "MAX_HISTORY",
    "build_readiness_score_document",
    "write_readiness_score",
    "append_history",
]


def _worst(statuses: List[str]) -> str:
    """Return the worst (highest-severity) status; ok if the list is empty."""
    worst = "ok"
    for s in statuses:
        if _SEVERITY.get(s, 0) > _SEVERITY.get(worst, 0):
            worst = s
    return worst


def _feed_health_component() -> Dict[str, Any]:
    """feed_health sub-score from the aggregated feed-health summary.

    Maps the summary's ``overall_status`` to a 0-100 score
    (ok=100, warn=60, unknown=40, degraded=0) and carries the status + counts
    through. Never raises: any failure yields status="unknown", score=0 with an
    ``"error"`` note.
    """
    record: Dict[str, Any] = {
        "key": "feed_health",
        "label": "Feed / covariance health",
        "score": 0,
        "status": "unknown",
    }
    try:
        from spa_core.alerts import feed_health_summary

        doc = feed_health_summary.build_summary_document()
        overall = str(doc.get("overall_status", "unknown"))
        score_map = {"ok": 100, "warn": 60, "unknown": 40, "degraded": 0}
        record["status"] = overall if overall in _SEVERITY else "unknown"
        record["score"] = score_map.get(overall, 40)
        record["overall_status"] = overall
        record["counts"] = doc.get("counts", {})
        record["signal_count"] = doc.get("signal_count")
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("feed_health component failed: %s", exc)
        record["status"] = "unknown"
        record["score"] = 0
        record["error"] = str(exc)
    return record


def _mev_coverage_component() -> Dict[str, Any]:
    """mev_coverage sub-score from the adapter-status MEV coverage block.

    Score = ``mev_protection.coverage.coverage_pct`` (already 0-100). Status:
    ok if >=80, warn if >=50, degraded otherwise. Never raises: any failure
    yields status="unknown", score=0 with an ``"error"`` note.
    """
    record: Dict[str, Any] = {
        "key": "mev_coverage",
        "label": "MEV-routing coverage",
        "score": 0,
        "status": "unknown",
    }
    try:
        from spa_core.execution import adapter_status

        doc = adapter_status.build_status_document()
        coverage = doc.get("mev_protection", {}).get("coverage", {})
        pct = float(coverage.get("coverage_pct", 0.0))
        record["score"] = pct
        record["coverage_pct"] = pct
        record["routed"] = coverage.get("routed")
        record["total"] = coverage.get("total")
        if pct >= 80:
            record["status"] = "ok"
        elif pct >= 50:
            record["status"] = "warn"
        else:
            record["status"] = "degraded"
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("mev_coverage component failed: %s", exc)
        record["status"] = "unknown"
        record["score"] = 0
        record["error"] = str(exc)
    return record


def _live_apy_component() -> Dict[str, Any]:
    """live_apy sub-score from the adapter-status ``live_apy_enabled`` flag.

    Dry-run (live APY disabled) is the EXPECTED pre-go-live posture, so a
    ``False`` value is treated as warn-level (score 50), not a hard fail.
    Score = 100 if enabled else 50; status: ok if enabled else warn. Never
    raises: any failure yields status="unknown", score=0 with an ``"error"``.
    """
    record: Dict[str, Any] = {
        "key": "live_apy",
        "label": "Live APY enrichment",
        "score": 0,
        "status": "unknown",
    }
    try:
        from spa_core.execution import adapter_status

        doc = adapter_status.build_status_document()
        enabled = bool(doc.get("live_apy_enabled", False))
        record["live_apy_enabled"] = enabled
        record["score"] = 100 if enabled else 50
        record["status"] = "ok" if enabled else "warn"
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("live_apy component failed: %s", exc)
        record["status"] = "unknown"
        record["score"] = 0
        record["error"] = str(exc)
    return record


def build_readiness_score_document() -> Dict[str, Any]:
    """Build the full consolidated readiness-score document. Never raises."""
    components = [
        _feed_health_component(),
        _mev_coverage_component(),
        _live_apy_component(),
    ]
    scores = [float(c.get("score", 0) or 0) for c in components]
    overall_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    overall_status = _worst([str(c.get("status", "unknown")) for c in components])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "overall_score": overall_score,
        "overall_status": overall_status,
        "components": components,
        "target_date": TARGET_DATE,
    }


def append_history(doc: Dict[str, Any], data_dir: Optional[str] = None) -> None:
    """Append a compact record of ``doc`` to the score-history log. Never raises.

    Reads the existing history (``<data_dir>/golive_readiness_score_history.json``
    or ``DEFAULT_DATA_DIR / HISTORY_FILENAME`` when ``data_dir`` is None), appends
    a small ``{generated_at, overall_score, overall_status}`` record, dedups on
    ``generated_at`` (a same-timestamp re-run replaces the last record rather than
    duplicating it), trims to the last ``MAX_HISTORY`` records and writes it back.
    A missing or corrupt history file is treated as an empty list -- any failure
    is swallowed (logged at debug) so it can never break the main score write.
    """
    try:
        target = (
            Path(data_dir) / HISTORY_FILENAME
            if data_dir is not None
            else DEFAULT_DATA_DIR / HISTORY_FILENAME
        )
        history: List[Dict[str, Any]] = []
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    history = loaded
            except Exception:  # noqa: BLE001 -- corrupt file -> start fresh
                history = []
        record = {
            "generated_at": doc.get("generated_at"),
            "overall_score": doc.get("overall_score"),
            "overall_status": doc.get("overall_status"),
        }
        if history and history[-1].get("generated_at") == record["generated_at"]:
            history[-1] = record
        else:
            history.append(record)
        history = history[-MAX_HISTORY:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("append_history failed: %s", exc)
        return


def write_readiness_score(out_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Build the score document and write it to ``out_path`` (default
    ``<repo>/data/golive_readiness_score.json``). Also appends a compact record
    to the score-history log next to it (SPA-V363). Returns the document.
    """
    target = (
        Path(out_path)
        if out_path is not None
        else DEFAULT_DATA_DIR / "golive_readiness_score.json"
    )
    doc = build_readiness_score_document()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    # History append is independently guarded so a history failure can never
    # break the (already-completed) main score write.
    try:
        append_history(doc, data_dir=str(target.parent))
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("readiness history append failed: %s", exc)
    return doc


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate Go-Live operational readiness into one score."
    )
    parser.add_argument("--json", action="store_true", help="print the document")
    parser.add_argument(
        "--write",
        nargs="?",
        const="",
        default=None,
        help="write data/golive_readiness_score.json (optional explicit PATH)",
    )
    args = parser.parse_args(argv)
    if args.write is not None:
        out = args.write or None
        doc = write_readiness_score(out)
    else:
        doc = build_readiness_score_document()
    if args.json or args.write is None:
        print(json.dumps(doc, indent=2))
    else:
        print(
            f"overall_score={doc['overall_score']} "
            f"overall_status={doc['overall_status']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
