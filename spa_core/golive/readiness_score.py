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

SPA-V364 -- added a FOURTH ``schedule`` component (day-counter / countdown to
the go-live ``TARGET_DATE``). It is purely INFORMATIONAL: it carries
``contributes_to_overall=False`` / ``scored=False`` and is DELIBERATELY excluded
from the operational ``overall_score`` mean and ``overall_status`` worst-of (which
remain computed over the three operational components only -- feed_health,
mev_coverage, live_apy -- so the headline number is unchanged / backwards
compatible). A top-level ``days_to_golive`` is also surfaced for the dashboard
(``None`` if the schedule component fails -- never-raise).

SPA-V368 -- persist the HISTORY of the combined go/no-go gate
(``append_combined_history`` -> ``golive_combined_verdict_history.json``) each
export cycle, mirroring the SPA-V363 score history, so the dashboard can render a
GO/NO_GO trend. Pure read-only persistence of already-emitted gate data; the
append is independently guarded and never-raise.
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

# SPA-V367 -- persist the combined go/no-go gate (SPA-V366 build_combined_golive_gate)
# to disk each export cycle so the gate is a durable artefact and not only
# computed client-side. Mirrors the SPA-V362 write_readiness_score wiring.
COMBINED_VERDICT_FILENAME = "golive_combined_verdict.json"
# SPA-V368 -- persistent combined-gate history / GO_NO_GO trend on the dashboard.
# Compact append-only log of the combined go/no-go gate over time, mirroring the
# SPA-V363 score history and SPA-V365 checklist history. Trimmed to MAX_HISTORY.
COMBINED_HISTORY_FILENAME = "golive_combined_verdict_history.json"
# Source documents the gate consolidates (read-only).
_SCORE_FILENAME = "golive_readiness_score.json"
_CHECKLIST_FILENAME = "golive_readiness.json"

__all__ = [
    "SCHEMA_VERSION",
    "TARGET_DATE",
    "HISTORY_FILENAME",
    "MAX_HISTORY",
    "COMBINED_VERDICT_FILENAME",
    "COMBINED_HISTORY_FILENAME",
    "_schedule_component",
    "build_readiness_score_document",
    "build_combined_golive_gate",
    "write_readiness_score",
    "write_combined_golive_gate",
    "append_history",
    "append_combined_history",
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


def _schedule_component() -> Dict[str, Any]:
    """schedule day-counter / countdown to the go-live ``TARGET_DATE``.

    INFORMATIONAL ONLY -- carries ``contributes_to_overall=False`` /
    ``scored=False`` and is excluded from the operational ``overall_score`` mean
    and ``overall_status`` worst-of (see ``build_readiness_score_document``).

    ``days_to_golive`` = ``(date(TARGET_DATE) - now_utc.date()).days``. The status
    is informational: ok if > 14 days out, warn in the final stretch
    (0..14 days), degraded if overdue (< 0). ``score`` (ok=100 / warn=60 /
    degraded=0) exists only for card-rendering uniformity and is NOT averaged.
    Never raises: any failure yields status="unknown", score=0 with an
    ``"error"`` note.
    """
    record: Dict[str, Any] = {
        "key": "schedule",
        "label": "Days to go-live",
        "score": 0,
        "status": "unknown",
        "target_date": TARGET_DATE,
        "contributes_to_overall": False,
        "scored": False,
    }
    try:
        target = datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()
        days = (target - datetime.now(timezone.utc).date()).days
        record["days_to_golive"] = days
        if days > 14:
            record["status"] = "ok"
            record["score"] = 100
        elif days >= 0:
            record["status"] = "warn"
            record["score"] = 60
        else:
            record["status"] = "degraded"
            record["score"] = 0
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("schedule component failed: %s", exc)
        record["status"] = "unknown"
        record["score"] = 0
        record["days_to_golive"] = None
        record["error"] = str(exc)
    return record


def build_readiness_score_document() -> Dict[str, Any]:
    """Build the full consolidated readiness-score document. Never raises.

    The three operational components (feed_health, mev_coverage, live_apy) are
    each flagged ``contributes_to_overall=True`` and the headline
    ``overall_score`` (mean) / ``overall_status`` (worst-of) are computed
    EXCLUSIVELY over those flagged components. The fourth ``schedule`` component
    (SPA-V364) is informational (``contributes_to_overall=False``) and is
    excluded from the mean/worst-of so the headline number stays backwards
    compatible.
    """
    operational = [
        _feed_health_component(),
        _mev_coverage_component(),
        _live_apy_component(),
    ]
    for record in operational:
        record["contributes_to_overall"] = True
    schedule = _schedule_component()
    components = operational + [schedule]

    # overall_* are computed ONLY over components that contribute to overall
    # (the three operational ones); schedule is excluded by design.
    scored = [c for c in components if c.get("contributes_to_overall")]
    scores = [float(c.get("score", 0) or 0) for c in scored]
    overall_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    overall_status = _worst([str(c.get("status", "unknown")) for c in scored])

    # Surface days_to_golive at top level for the dashboard (never-raise: None
    # if the schedule component failed to compute it).
    days_to_golive = schedule.get("days_to_golive")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "overall_score": overall_score,
        "overall_status": overall_status,
        "components": components,
        "target_date": TARGET_DATE,
        "days_to_golive": days_to_golive,
    }


def build_combined_golive_gate(
    score_doc: Optional[Dict[str, Any]],
    checklist_doc: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """SPA-V366 — fuse the two independent go-live axes into one go/no-go gate.

    The dashboard surfaces two DELIBERATELY DISTINCT readiness axes (kept as
    separate data sources by design -- see this module's docstring):

      * operational readiness  -- ``golive_readiness_score.json`` (this module):
        ``overall_status`` / ``overall_score`` over feed_health + mev_coverage +
        live_apy.
      * paper-trading checklist -- ``golive_readiness.json``
        (``spa_core/golive`` checklist): ``verdict`` + criteria PASS/total.

    This is a PURE PRESENTATION-LAYER consolidation: it reads the two
    already-emitted documents and answers the single operator question "are we
    GO for go-live?" without merging the underlying data sources (so neither
    ``overall_score`` nor the checklist verdict is mutated). The gate is ``GO``
    ONLY when operational readiness is ``ok`` AND the checklist verdict is
    ``READY``; otherwise ``NO_GO`` with each limiting axis named in ``blocking``.

    Pure, deterministic, never raises -- any failure (or both inputs None)
    yields a safe ``NO_GO`` gate with ``blocking=["error"]`` (or the missing-axis
    reasons). It is NOT a new feed-health monitor (SPA-BL-011 respected) and
    touches NO money-moving code.
    """
    gate: Dict[str, Any] = {
        "gate": "NO_GO",
        "operational_status": "unknown",
        "operational_score": None,
        "checklist_verdict": None,
        "criteria_passed": None,
        "criteria_total": None,
        "blocking": [],
    }
    try:
        # --- operational readiness axis ---
        op_status = "unknown"
        op_score = None
        if isinstance(score_doc, dict):
            op_status = str(score_doc.get("overall_status", "unknown")).lower()
            if op_status not in _SEVERITY:
                op_status = "unknown"
            op_score = score_doc.get("overall_score")
        gate["operational_status"] = op_status
        gate["operational_score"] = op_score
        operational_ok = op_status == "ok"

        # --- paper-trading checklist axis ---
        verdict = None
        passed = None
        total = None
        if isinstance(checklist_doc, dict):
            raw = checklist_doc.get("verdict")
            verdict = str(raw).upper() if raw is not None else None
            criteria = checklist_doc.get("criteria")
            if isinstance(criteria, list):
                total = len(criteria)
                passed = sum(
                    1
                    for c in criteria
                    if isinstance(c, dict)
                    and str(c.get("status", "")).lower().startswith("pass")
                )
        gate["checklist_verdict"] = verdict
        gate["criteria_passed"] = passed
        gate["criteria_total"] = total
        checklist_ready = verdict == "READY"

        # --- combined gate ---
        blocking: List[str] = []
        if not operational_ok:
            blocking.append("operational readiness %s" % op_status)
        if not checklist_ready:
            blocking.append("checklist %s" % (verdict or "unknown").lower())
        gate["blocking"] = blocking
        gate["gate"] = "GO" if (operational_ok and checklist_ready) else "NO_GO"
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("build_combined_golive_gate failed: %s", exc)
        gate["gate"] = "NO_GO"
        gate["blocking"] = ["error"]
        gate["error"] = str(exc)
    return gate


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


def append_combined_history(
    doc: Dict[str, Any], data_dir: Optional[str] = None
) -> None:
    """SPA-V368 -- append a compact record of the combined gate to its history log.

    Mirror of ``append_history``: reads the existing combined-gate history
    (``<data_dir>/golive_combined_verdict_history.json`` or
    ``DEFAULT_DATA_DIR / COMBINED_HISTORY_FILENAME`` when ``data_dir`` is None),
    appends a small ``{generated_at, gate, operational_status, checklist_verdict}``
    record, dedups on ``generated_at`` (a same-timestamp re-run replaces the last
    record rather than duplicating it), trims to the last ``MAX_HISTORY`` records
    and writes it back. A missing or corrupt history file is treated as an empty
    list -- any failure is swallowed (logged at debug) so it can never break the
    main combined-gate write.
    """
    try:
        target = (
            Path(data_dir) / COMBINED_HISTORY_FILENAME
            if data_dir is not None
            else DEFAULT_DATA_DIR / COMBINED_HISTORY_FILENAME
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
            "gate": doc.get("gate"),
            "operational_status": doc.get("operational_status"),
            "checklist_verdict": doc.get("checklist_verdict"),
        }
        if history and history[-1].get("generated_at") == record["generated_at"]:
            history[-1] = record
        else:
            history.append(record)
        history = history[-MAX_HISTORY:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("append_combined_history failed: %s", exc)
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


def _read_json_or_none(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON object from ``path``; return None on missing/corrupt/non-dict.

    Helper for the combined-gate writer: the two source documents are produced
    earlier in the same export cycle, but a missing or malformed file must not
    abort the gate -- ``build_combined_golive_gate`` already degrades a ``None``
    input to a safe ``NO_GO``.
    """
    try:
        if not path.exists():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except Exception as exc:  # noqa: BLE001 -- corrupt/unreadable -> None
        log.debug("combined-gate source read failed (%s): %s", path, exc)
        return None


def write_combined_golive_gate(
    out_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """SPA-V367 -- persist the combined go/no-go gate as a durable artefact.

    Reads the two already-emitted source documents
    (``golive_readiness_score.json`` and ``golive_readiness.json``) from
    ``data_dir`` (defaults to the output dir, i.e. ``out_path``'s parent, else
    ``DEFAULT_DATA_DIR``), runs the pure SPA-V366 ``build_combined_golive_gate``
    over them and writes the result to ``out_path`` (default
    ``<data_dir>/golive_combined_verdict.json``). A ``schema_version`` and a
    ``generated_at`` timestamp are added so the persisted gate matches the shape
    of the other readiness artefacts.

    This is a PURE read-only consolidation (no money-moving code, not a new
    feed-health monitor -- SPA-BL-011 respected); it does not mutate or merge the
    source documents. Missing/corrupt sources degrade to a safe ``NO_GO`` gate
    rather than raising. Returns the persisted gate document.
    """
    target = (
        Path(out_path)
        if out_path is not None
        else (
            (Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR)
            / COMBINED_VERDICT_FILENAME
        )
    )
    source_dir = (
        Path(data_dir) if data_dir is not None else target.parent
    )
    score_doc = _read_json_or_none(source_dir / _SCORE_FILENAME)
    checklist_doc = _read_json_or_none(source_dir / _CHECKLIST_FILENAME)
    gate = build_combined_golive_gate(score_doc, checklist_doc)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        **gate,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    # SPA-V368 -- history append is independently guarded so a history failure
    # can never break the (already-completed) main combined-gate write.
    try:
        append_combined_history(doc, data_dir=str(target.parent))
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("combined-gate history append failed: %s", exc)
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
