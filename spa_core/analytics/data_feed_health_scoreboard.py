"""Data Feed Health Scoreboard (MP-623).

Advisory / read-only analytics module: aggregates the 8 per-check APY-feed
health-state files (``data/apy_feed_*_health_state.json``) into a single
data-quality scoreboard.  For each check it classifies a per-check status of
HEALTHY / DEGRADED / CRITICAL from the consecutive-failure counter, applies a
staleness check on ``updated_at`` (a feed older than STALENESS_HOURS is flagged
stale and floored to at-least DEGRADED), and rolls everything up into an overall
grade with a health score.

This complements AlertThresholdManager (MP-622) and FullPortfolioMasterReport
(MP-621) in the SPA analytics line.

Design constraints (SPA-BL-011)
-------------------------------
* Pure stdlib -- no numpy/pandas/requests/web3/openai, no pip deps.
* Advisory / read-only -- never touches allocator / risk / execution / monitoring.
* Atomic writes -- tmp + os.replace on every JSON update; no .tmp leftovers.
* Fail-safe reads -- missing / corrupt / non-dict JSON -> consecutive=0, never raises.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.data_feed_health_scoreboard --check
    python3 -m spa_core.analytics.data_feed_health_scoreboard --run
    python3 -m spa_core.analytics.data_feed_health_scoreboard --run --data-dir /path/to/data

MP-623.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Per-check registry: (check_name, filename, counter_key).  Order defines the
# scoreboard iteration order and the tie-break order for ``worst_check``.
CHECK_REGISTRY: List[Dict[str, str]] = [
    {
        "check_name": "feed_freshness",
        "filename": "apy_feed_health_state.json",
        "counter_key": "consecutive_stale",
    },
    {
        "check_name": "anomaly",
        "filename": "apy_feed_anomaly_health_state.json",
        "counter_key": "consecutive_anomalies",
    },
    {
        "check_name": "bounds",
        "filename": "apy_feed_bounds_health_state.json",
        "counter_key": "consecutive_bounds",
    },
    {
        "check_name": "tvl_drop",
        "filename": "apy_feed_tvl_health_state.json",
        "counter_key": "consecutive_drops",
    },
    {
        "check_name": "schema_drift",
        "filename": "apy_feed_schema_health_state.json",
        "counter_key": "consecutive_drifts",
    },
    {
        "check_name": "monotonicity",
        "filename": "apy_feed_monotonicity_health_state.json",
        "counter_key": "consecutive_mono",
    },
    {
        "check_name": "protocol_count",
        "filename": "apy_feed_protocol_health_state.json",
        "counter_key": "consecutive_drops",
    },
    {
        "check_name": "protocol_stale",
        "filename": "apy_feed_protocol_stale_health_state.json",
        "counter_key": "consecutive_stale",
    },
]

# Classification thresholds on the consecutive-failure counter.
#   consecutive == 0            -> HEALTHY
#   1 <= consecutive < 3        -> DEGRADED
#   consecutive >= 3            -> CRITICAL
DEGRADED_THRESHOLD = 1
CRITICAL_THRESHOLD = 3

# Feed staleness: an ``updated_at`` older than this many hours floors a check
# to at-least DEGRADED.
STALENESS_HOURS = 24.0

# Status labels.
_HEALTHY = "HEALTHY"
_DEGRADED = "DEGRADED"
_CRITICAL = "CRITICAL"

# Per-status emoji for Telegram output.
_STATUS_EMOJI = {
    _HEALTHY: "🟢",
    _DEGRADED: "🟡",
    _CRITICAL: "🔴",
}


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _safe_int(val: Any) -> int:
    """Coerce a value to a non-degenerate int; bool / non-number / None -> 0.

    ``bool`` is handled *before* the numeric branch (``True``/``False`` would
    otherwise coerce to 1/0).  NaN / inf / unparseable -> 0.
    """
    if isinstance(val, bool):
        return 0
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(f):
        return 0
    return int(f)


def _safe_float(val: Any) -> float:
    """Coerce a value to a finite float; bool / non-number / None -> 0.0."""
    if isinstance(val, bool):
        return 0.0
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _parse_timestamp(s: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp to a UTC-aware datetime.

    Normalises a trailing 'Z' to '+00:00'.  Naive timestamps are assumed UTC.
    On failure (or non-string / empty), returns ``None``.
    """
    if isinstance(s, str) and s:
        try:
            normalized = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CheckStatus:
    """Health status of a single feed check.

    Attributes
    ----------
    check_name        : Logical check name (e.g. "feed_freshness").
    filename          : Source health-state filename.
    consecutive_count : Consecutive-failure counter from the source file.
    last_alerted_cycle: ``last_alerted_cycle`` from the source file.
    updated_at        : Raw ``updated_at`` string, or None when absent.
    age_hours         : Hours since ``updated_at``, or None when no timestamp.
    is_stale          : True when age_hours > STALENESS_HOURS.
    status            : "HEALTHY" / "DEGRADED" / "CRITICAL".
    note              : Free-text note (fail-safe diagnostics, staleness, etc.).
    """

    check_name: str
    filename: str
    consecutive_count: int
    last_alerted_cycle: int
    updated_at: Optional[str]
    age_hours: Optional[float]
    is_stale: bool
    status: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "check_name": self.check_name,
            "filename": self.filename,
            "consecutive_count": self.consecutive_count,
            "last_alerted_cycle": self.last_alerted_cycle,
            "updated_at": self.updated_at,
            "age_hours": (
                round(self.age_hours, 4) if self.age_hours is not None else None
            ),
            "is_stale": self.is_stale,
            "status": self.status,
            "note": self.note,
        }


@dataclass
class ScoreboardReport:
    """Full data-feed health scoreboard.

    Attributes
    ----------
    generated_at   : ISO-8601 UTC timestamp when this report was produced.
    checks_total   : Number of checks evaluated.
    healthy_count  : Count of HEALTHY checks.
    degraded_count : Count of DEGRADED checks.
    critical_count : Count of CRITICAL checks.
    stale_count    : Count of checks flagged stale.
    overall_status : "HEALTHY" / "DEGRADED" / "CRITICAL".
    worst_check    : Name of the most-degraded check ("" when all clean).
    health_score   : healthy_count / checks_total, in [0.0, 1.0].
    checks         : Per-check CheckStatus list (registry order).
    summary        : One-line human-readable summary.
    """

    generated_at: str
    checks_total: int
    healthy_count: int
    degraded_count: int
    critical_count: int
    stale_count: int
    overall_status: str
    worst_check: str
    health_score: float
    checks: List[CheckStatus] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (checks as list of dict)."""
        return {
            "generated_at": self.generated_at,
            "checks_total": self.checks_total,
            "healthy_count": self.healthy_count,
            "degraded_count": self.degraded_count,
            "critical_count": self.critical_count,
            "stale_count": self.stale_count,
            "overall_status": self.overall_status,
            "worst_check": self.worst_check,
            "health_score": round(self.health_score, 4),
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# DataFeedHealthScoreboard
# ---------------------------------------------------------------------------


class DataFeedHealthScoreboard:
    """Aggregate the 8 APY-feed health-state files into a unified scoreboard.

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing the source health-state files and where the
        output is written.  Defaults to the repo ``data/`` directory.
    now : datetime, optional
        Injectable "current time" (UTC-aware) for deterministic staleness
        tests.  Defaults to ``datetime.now(timezone.utc)``.
    """

    OUTPUT_FILE: str = "data_feed_health_scoreboard.json"
    RING_BUFFER_SIZE: int = 48

    def __init__(
        self,
        data_path: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)
        self._now = now

    # -----------------------------------------------------------------------
    # Time helper
    # -----------------------------------------------------------------------

    def _resolve_now(self) -> datetime:
        """Return the injected ``now`` (UTC) or the live UTC time."""
        if self._now is not None:
            now = self._now
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            return now.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # Classification
    # -----------------------------------------------------------------------

    @staticmethod
    def _classify(consecutive: int, is_stale: bool) -> str:
        """Classify a check from its consecutive counter and staleness flag.

        CRITICAL when consecutive >= CRITICAL_THRESHOLD; otherwise DEGRADED
        when consecutive >= DEGRADED_THRESHOLD or the feed is stale; otherwise
        HEALTHY.
        """
        if consecutive >= CRITICAL_THRESHOLD:
            return _CRITICAL
        if consecutive >= DEGRADED_THRESHOLD or is_stale:
            return _DEGRADED
        return _HEALTHY

    # -----------------------------------------------------------------------
    # Per-check loading
    # -----------------------------------------------------------------------

    def load_check(
        self, check_name: str, filename: str, counter_key: str
    ) -> CheckStatus:
        """Load and classify a single feed check (fail-safe).

        Missing / unreadable / non-dict source -> consecutive=0,
        updated_at=None, with an explanatory note.  Computes ``age_hours`` and
        ``is_stale`` from ``updated_at`` against the resolved ``now``.
        """
        path = self.data_dir / filename
        notes: List[str] = []

        raw: Optional[dict] = None
        if not path.exists():
            notes.append("source file missing")
        else:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                loaded = None
                notes.append("source file unreadable/corrupt")
            if loaded is not None:
                if isinstance(loaded, dict):
                    raw = loaded
                else:
                    notes.append("source file is not a JSON object")

        if raw is None:
            raw = {}

        consecutive = _safe_int(raw.get(counter_key))
        last_alerted_cycle = _safe_int(raw.get("last_alerted_cycle"))

        updated_at_raw = raw.get("updated_at")
        updated_at: Optional[str] = (
            updated_at_raw if isinstance(updated_at_raw, str) and updated_at_raw
            else None
        )

        age_hours: Optional[float] = None
        is_stale = False
        if updated_at is None:
            notes.append("no updated_at timestamp")
        else:
            parsed = _parse_timestamp(updated_at)
            if parsed is None:
                notes.append("unparseable updated_at timestamp")
                updated_at = None
            else:
                delta = self._resolve_now() - parsed
                age_hours = delta.total_seconds() / 3600.0
                is_stale = age_hours > STALENESS_HOURS
                if is_stale:
                    notes.append(f"feed stale ({age_hours:.1f}h old)")

        status = self._classify(consecutive, is_stale)
        note = "; ".join(notes)

        return CheckStatus(
            check_name=check_name,
            filename=filename,
            consecutive_count=consecutive,
            last_alerted_cycle=last_alerted_cycle,
            updated_at=updated_at,
            age_hours=age_hours,
            is_stale=is_stale,
            status=status,
            note=note,
        )

    # -----------------------------------------------------------------------
    # Report generation
    # -----------------------------------------------------------------------

    def generate_report(self) -> ScoreboardReport:
        """Build the full scoreboard report across CHECK_REGISTRY."""
        checks: List[CheckStatus] = []
        for entry in CHECK_REGISTRY:
            checks.append(
                self.load_check(
                    check_name=entry["check_name"],
                    filename=entry["filename"],
                    counter_key=entry["counter_key"],
                )
            )

        checks_total = len(checks)
        healthy_count = sum(1 for c in checks if c.status == _HEALTHY)
        degraded_count = sum(1 for c in checks if c.status == _DEGRADED)
        critical_count = sum(1 for c in checks if c.status == _CRITICAL)
        stale_count = sum(1 for c in checks if c.is_stale)

        if critical_count > 0:
            overall_status = _CRITICAL
        elif degraded_count > 0:
            overall_status = _DEGRADED
        else:
            overall_status = _HEALTHY

        # Worst check = max consecutive_count, first-by-registry-order on ties;
        # "" when every counter is 0.
        worst_check = ""
        worst_count = 0
        for c in checks:
            if c.consecutive_count > worst_count:
                worst_count = c.consecutive_count
                worst_check = c.check_name
        if worst_count == 0:
            worst_check = ""

        health_score = (
            healthy_count / checks_total if checks_total > 0 else 0.0
        )

        summary = (
            f"Feeds: {healthy_count} healthy / {degraded_count} degraded / "
            f"{critical_count} critical, overall={overall_status}"
        )

        return ScoreboardReport(
            generated_at=self._resolve_now().isoformat(),
            checks_total=checks_total,
            healthy_count=healthy_count,
            degraded_count=degraded_count,
            critical_count=critical_count,
            stale_count=stale_count,
            overall_status=overall_status,
            worst_check=worst_check,
            health_score=health_score,
            checks=checks,
            summary=summary,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(
        self, report: Optional[ScoreboardReport] = None
    ) -> str:
        """Atomically save the report, maintaining a ring-buffer of 48.

        Returns the absolute path of the written file.
        """
        if report is None:
            report = self.generate_report()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.data_dir / self.OUTPUT_FILE

        # Load existing ring-buffer.
        history: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    hist = existing.get("history", [])
                    if isinstance(hist, list):
                        history = [h for h in hist if isinstance(h, dict)]
            except (ValueError, OSError):
                pass

        report_dict = report.to_dict()
        history.append(report_dict)
        history = history[-self.RING_BUFFER_SIZE:]

        out: Dict[str, Any] = {
            "schema_version": 1,
            "source": "data_feed_health_scoreboard",
            "ring_buffer_max": self.RING_BUFFER_SIZE,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp + os.replace.
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(
        self, report: Optional[ScoreboardReport] = None
    ) -> str:
        """Format a Telegram-ready message (<=1500 chars)."""
        if report is None:
            report = self.generate_report()

        lines: List[str] = [
            f"🩺 Data Feed Health — {report.overall_status}",
            f"H {report.healthy_count} / D {report.degraded_count} / "
            f"C {report.critical_count}  (score {report.health_score:.2f})",
        ]

        if report.overall_status == _HEALTHY:
            lines.append("✅ All feeds healthy")
        else:
            for c in report.checks:
                if c.status == _HEALTHY:
                    continue
                emoji = _STATUS_EMOJI.get(c.status, "❓")
                detail = f"consec={c.consecutive_count}"
                if c.is_stale:
                    detail += ", stale"
                lines.append(f"{emoji} {c.check_name}: {c.status} ({detail})")
            if report.stale_count:
                lines.append(f"⏱ stale feeds: {report.stale_count}")

        if report.worst_check:
            lines.append(f"worst: {report.worst_check}")

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(
        self, report: Optional[ScoreboardReport] = None
    ) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the report."""
        if report is None:
            report = self.generate_report()
        return report.to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPA Data Feed Health Scoreboard (MP-623) -- aggregate 8 "
            "apy_feed_*_health_state.json files into a unified data-quality "
            "scoreboard (HEALTHY/DEGRADED/CRITICAL per-check + staleness)."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Compute and print summary without writing (default).",
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/data_feed_health_scoreboard.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    board = DataFeedHealthScoreboard(data_path=args.data_dir)
    report = board.generate_report()

    print("=== Data Feed Health Scoreboard (MP-623) ===")
    print(f"Generated:      {report.generated_at}")
    print(f"Checks total:   {report.checks_total}")
    print(f"Overall:        {report.overall_status}")
    print(f"Health score:   {report.health_score:.4f}")
    print(
        f"Counts:         H {report.healthy_count} / "
        f"D {report.degraded_count} / C {report.critical_count} "
        f"(stale {report.stale_count})"
    )
    print(f"Worst check:    {report.worst_check or 'n/a'}")
    print(f"Summary:        {report.summary}")
    print()

    if report.checks:
        print("Checks:")
        for c in report.checks:
            age = f"{c.age_hours:.1f}h" if c.age_hours is not None else "n/a"
            stale = "STALE" if c.is_stale else "fresh"
            print(
                f"  {c.check_name:>16s}  {c.status:<8s}  "
                f"consec={c.consecutive_count:<3d}  age={age:<8s}  {stale}"
                + (f"  [{c.note}]" if c.note else "")
            )
        print()

    if args.run:
        path = board.save_report(report)
        print(f"Saved -> {path}")
        print(f"Summary: {report.summary}")

    return 0


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point: always exit(0)."""
    try:
        _main(argv)
    except Exception as exc:  # pragma: no cover - fail-safe CLI
        print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
