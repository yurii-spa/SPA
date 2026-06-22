#!/usr/bin/env python3
"""SPA Milestone Tracker (MP-111).

Tracks progress toward the 30-consecutive-day Go-Live milestone:
30 uninterrupted trading days with no cycle gaps.

Honest metrics philosophy
=========================
- Total return is reported as-is (not extrapolated from short streaks).
- Annualized return uses compound formula: (1 + R)^(365/n) − 1.
  For n < 30 this is clearly labelled "if sustained" — never presented
  as a promise.
- The consecutive-day counter is reset to 0 the moment a gap_monitor
  gap_detected flag is True (>26 h since last cycle).

Safety
======
* Stdlib only. Atomic writes (tmpfile + os.replace).
* Never imports execution/, risk-agents, or feed-health code.
* Called from cycle_runner in a try/except — must never crash the cycle.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

# ─── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
GOLIVE_STATUS_FILE = "golive_status.json"
GAP_MONITOR_FILE = "gap_monitor.json"

# ─── Constants ────────────────────────────────────────────────────────────────

TARGET_DAYS = 30
GAP_THRESHOLD_HOURS = 26  # mirrors gap_monitor.GAP_THRESHOLD_HOURS


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class MilestoneStatus:
    """Snapshot of milestone progress at a point in time."""

    consecutive_days: int
    """Consecutive calendar days with a data point at the tail of equity_curve
    (regardless of gap_monitor state)."""

    consecutive_without_gap: int
    """Same as consecutive_days unless gap_monitor reports gap_detected=True,
    in which case this resets to 0 (the active streak is broken)."""

    target_days: int
    """Goal (30)."""

    progress_pct: float
    """Percentage toward target (0–100), based on consecutive_without_gap."""

    current_streak_start: str
    """ISO date of the first day in the current consecutive streak (YYYY-MM-DD).
    Empty string when there are no data points."""

    estimated_completion: str
    """Projected date when 30/30 will be reached if no gaps occur (YYYY-MM-DD).
    Empty when no data; equals last streak date when milestone already reached."""

    is_milestone_reached: bool
    """True when consecutive_without_gap >= 30."""

    blockers: list[str]
    """Human-readable reasons the milestone is not yet reached."""

    honest_metrics: dict[str, Any]
    """Factual performance metrics over the current streak (no inflation)."""


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


# ─── Pure helpers ─────────────────────────────────────────────────────────────


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s: str) -> date:
    """Parse first 10 chars of an ISO date string → datetime.date."""
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _normalise_bars(equity_curve: list[dict]) -> list[dict]:
    """Convert raw equity_curve entries to a canonical list, sorted by date,
    deduplicated (last entry wins per calendar day).

    Accepts both the cycle_runner schema (daily_return_pct, close_equity /
    equity) and the simplified test schema (pnl_pct, equity).
    """
    normalised: list[dict] = []
    for b in equity_curve or []:
        if not isinstance(b, dict):
            continue
        date_str = str(b.get("date", ""))[:10]
        if not date_str:
            continue
        # Prefer cycle_runner field names; fall back to spec aliases.
        ret = b.get("daily_return_pct")
        if ret is None:
            ret = b.get("pnl_pct")
        eq = b.get("equity")
        if eq is None:
            eq = b.get("close_equity")
        normalised.append({
            "date": date_str,
            "daily_return_pct": _safe_float(ret),
            "equity": _safe_float(eq),
            "_open_equity": _safe_float(b.get("open_equity")),
        })

    normalised.sort(key=lambda x: x["date"])

    deduped: list[dict] = []
    for bar in normalised:
        if deduped and deduped[-1]["date"] == bar["date"]:
            deduped[-1] = bar
        else:
            deduped.append(bar)

    return deduped


def _find_streak(bars: list[dict]) -> list[dict]:
    """Return the longest consecutive tail of *bars* where adjacent dates differ
    by exactly one calendar day.  Empty list → empty streak."""
    if not bars:
        return []
    streak = [bars[-1]]
    for i in range(len(bars) - 2, -1, -1):
        prev = _parse_date(bars[i]["date"])
        curr = _parse_date(bars[i + 1]["date"])
        if (curr - prev).days == 1:
            streak.insert(0, bars[i])
        else:
            break
    return streak


def _compute_honest_metrics(
    streak_bars: list[dict],
    gap_detected: bool,
) -> dict[str, Any]:
    """Compute factual performance metrics over the streak."""
    n = len(streak_bars)
    if n == 0:
        return {
            "streak_days": 0,
            "streak_start": "",
            "streak_end": "",
            "total_return_pct": 0.0,
            "annualized_pct_if_sustained": 0.0,
            "positive_days": 0,
            "total_days": 0,
            "win_rate_pct": 0.0,
            "best_day_pct": 0.0,
            "best_day_date": "",
            "worst_day_pct": 0.0,
            "worst_day_date": "",
            "gaps": 1 if gap_detected else 0,
        }

    # Total return: (last close − first open) / first open
    # Use _open_equity of the first bar if present; otherwise use first close
    # as the open (conservative).
    first_open = streak_bars[0]["_open_equity"] or streak_bars[0]["equity"]
    last_close = streak_bars[-1]["equity"]

    total_return_pct = (
        round((last_close / first_open - 1.0) * 100.0, 4) if first_open else 0.0
    )

    # Annualized: compound formula — (1 + R)^(365/n) - 1
    # Labelled "if_sustained" — NOT a naïve R * 365/n extrapolation.
    if n >= 1 and first_open > 0 and last_close > 0:
        total_factor = last_close / first_open
        annualized_pct = round((total_factor ** (365.0 / n) - 1.0) * 100.0, 2)
    else:
        annualized_pct = 0.0

    daily_rets = [b["daily_return_pct"] for b in streak_bars]
    dates = [b["date"] for b in streak_bars]

    positive_days = sum(1 for r in daily_rets if r > 0)

    best_idx = daily_rets.index(max(daily_rets)) if daily_rets else 0
    worst_idx = daily_rets.index(min(daily_rets)) if daily_rets else 0

    return {
        "streak_days": n,
        "streak_start": streak_bars[0]["date"],
        "streak_end": streak_bars[-1]["date"],
        "total_return_pct": total_return_pct,
        "annualized_pct_if_sustained": annualized_pct,
        "positive_days": positive_days,
        "total_days": n,
        "win_rate_pct": round(positive_days / n * 100.0, 1),
        "best_day_pct": round(daily_rets[best_idx], 4) if daily_rets else 0.0,
        "best_day_date": dates[best_idx] if dates else "",
        "worst_day_pct": round(daily_rets[worst_idx], 4) if daily_rets else 0.0,
        "worst_day_date": dates[worst_idx] if dates else "",
        "gaps": 1 if gap_detected else 0,
    }


# ─── Public API ───────────────────────────────────────────────────────────────


def check_milestone(
    equity_curve: list[dict],
    gap_monitor_data: dict | None = None,
) -> MilestoneStatus:
    """Check progress toward the 30-consecutive-day Go-Live milestone.

    Parameters
    ----------
    equity_curve:
        List of daily bar dicts, each with at minimum ``date`` (YYYY-MM-DD)
        and one of ``daily_return_pct`` / ``pnl_pct`` (float) and one of
        ``equity`` / ``close_equity`` (float).  Both cycle_runner and
        simplified test schemas are accepted.
    gap_monitor_data:
        Dict loaded from ``data/gap_monitor.json``.  When ``gap_detected``
        is ``True`` the active streak is treated as broken: consecutive_without_gap
        is set to 0 and a blocker message is added.

    Returns
    -------
    MilestoneStatus
        Snapshot of the current milestone state with honest metrics.
    """
    blockers: list[str] = []

    bars = _normalise_bars(equity_curve)
    streak_bars = _find_streak(bars)
    consecutive_days = len(streak_bars)

    # Gap monitor: does the gap_monitor say we missed a cycle recently?
    gap_detected = False
    if isinstance(gap_monitor_data, dict):
        gap_detected = bool(gap_monitor_data.get("gap_detected", False))
        if gap_detected:
            hours = _safe_float(gap_monitor_data.get("hours_since_last_entry", 0))
            blockers.append(
                f"gap detected: last cycle {hours:.1f}h ago "
                f"(threshold: {GAP_THRESHOLD_HOURS}h) — streak reset to 0"
            )

    consecutive_without_gap = 0 if gap_detected else consecutive_days

    # Streak start date
    if consecutive_without_gap > 0 and streak_bars:
        streak_start = streak_bars[0]["date"]
    elif bars:
        streak_start = bars[-1]["date"]
    else:
        streak_start = ""

    # Progress
    progress_pct = round(
        min(consecutive_without_gap / TARGET_DAYS * 100.0, 100.0), 1
    )
    is_milestone_reached = consecutive_without_gap >= TARGET_DAYS

    # Estimated completion
    if is_milestone_reached:
        estimated_completion = streak_bars[-1]["date"] if streak_bars else streak_start
    elif streak_start:
        try:
            start_dt = _parse_date(streak_start)
            estimated_completion = (
                start_dt + timedelta(days=TARGET_DAYS - 1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            estimated_completion = ""
    else:
        estimated_completion = ""

    honest_metrics = _compute_honest_metrics(streak_bars, gap_detected)

    return MilestoneStatus(
        consecutive_days=consecutive_days,
        consecutive_without_gap=consecutive_without_gap,
        target_days=TARGET_DAYS,
        progress_pct=progress_pct,
        current_streak_start=streak_start,
        estimated_completion=estimated_completion,
        is_milestone_reached=is_milestone_reached,
        blockers=blockers,
        honest_metrics=honest_metrics,
    )


def generate_milestone_report(status: MilestoneStatus) -> str:
    """Render a human-readable milestone progress report.

    Example output::

        🎯 Milestone Progress: 7/30 consecutive days
        ━━━━━━━━━━━━━━━━━━━━ 23%

        📅 Current streak: 7 days (started 2026-06-04)
        🏁 Est. completion: 2026-07-04

        📊 Honest Metrics (7 days):
        • Total return: +0.29% (real, not annualized)
        • Annualized (if sustained): +15.2%
        • Profitable days: 6/7 (85.7%)
        • Best day:  +0.06% (2026-06-09)
        • Worst day: -0.01% (2026-06-07)
        • Gaps: 0 (required: 0)

        ✅ No blockers
    """
    n = status.consecutive_without_gap
    target = status.target_days
    pct = status.progress_pct

    # Progress bar (20 chars wide)
    bar_width = 20
    filled = round(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    m = status.honest_metrics

    lines: list[str] = [
        f"🎯 Milestone Progress: {n}/{target} consecutive days",
        f"{'━' * bar_width} {pct:.0f}%",
        f"  [{bar}]",
        "",
        f"📅 Current streak: {n} days"
        + (f" (started {status.current_streak_start})" if status.current_streak_start else ""),
        f"🏁 Est. completion: {status.estimated_completion or '—'}",
        "",
        f"📊 Honest Metrics ({m.get('streak_days', 0)} days):",
        f"• Total return: {m.get('total_return_pct', 0.0):+.2f}% (real, not annualized)",
        f"• Annualized (if sustained): {m.get('annualized_pct_if_sustained', 0.0):+.1f}%",
        f"• Profitable days: {m.get('positive_days', 0)}/{m.get('total_days', 0)} "
        f"({m.get('win_rate_pct', 0.0):.1f}%)",
        f"• Best day:  {m.get('best_day_pct', 0.0):+.4f}% ({m.get('best_day_date', '?')})",
        f"• Worst day: {m.get('worst_day_pct', 0.0):+.4f}% ({m.get('worst_day_date', '?')})",
        f"• Gaps: {m.get('gaps', 0)} (required: 0)",
    ]

    if status.is_milestone_reached:
        lines += ["", "🎉 MILESTONE REACHED! 30/30 consecutive days complete."]
    elif status.blockers:
        lines += ["", "❌ Blockers:"]
        for b in status.blockers:
            lines.append(f"  • {b}")
    else:
        lines += ["", "✅ No blockers"]

    return "\n".join(lines)


def update_golive_status_milestone(
    status: MilestoneStatus,
    data_dir: Path | None = None,
) -> None:
    """Patch ``data/golive_status.json`` with the milestone_30d criterion.

    Reads the existing file, updates the ``checks.milestone_30d`` field and
    the ``milestone`` summary block, then rewrites atomically.  The other
    criteria are left intact.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / GOLIVE_STATUS_FILE

    doc = _read_json(path, {})
    if not isinstance(doc, dict):
        doc = {}

    checks = doc.get("checks") or {}
    if not isinstance(checks, dict):
        checks = {}

    checks["milestone_30d"] = status.is_milestone_reached
    doc["checks"] = checks

    # Rebuild blockers: keep existing ones (not milestone-related) + milestone blocker
    blockers = [
        b for b in (doc.get("blockers") or [])
        if "milestone" not in str(b).lower() and "milestone_30d" not in str(b)
    ]
    if not status.is_milestone_reached:
        remaining = status.target_days - status.consecutive_without_gap
        blockers.append(
            f"milestone_30d: {status.consecutive_without_gap}/{status.target_days} days "
            f"({remaining} remaining)"
        )
    doc["blockers"] = blockers

    doc["milestone"] = {
        "consecutive_days": status.consecutive_without_gap,
        "target_days": status.target_days,
        "progress_pct": status.progress_pct,
        "streak_start": status.current_streak_start,
        "estimated_completion": status.estimated_completion,
        "is_reached": status.is_milestone_reached,
    }

    # Recompute ready flag
    doc["ready"] = all(doc["checks"].values()) if doc["checks"] else False
    doc["timestamp"] = datetime.now(timezone.utc).isoformat()
    doc["source"] = "golive_checker+milestone"

    _atomic_write_json(path, doc)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    import sys

    data_dir = _DEFAULT_DATA_DIR
    eq_doc = _read_json(data_dir / "equity_curve_daily.json", {})
    equity_curve = eq_doc.get("daily", []) if isinstance(eq_doc, dict) else []
    gap_data = _read_json(data_dir / GAP_MONITOR_FILE, {})

    status = check_milestone(equity_curve=equity_curve, gap_monitor_data=gap_data)
    print(generate_milestone_report(status))

    # Optionally update golive_status.json
    if "--update" in sys.argv:
        update_golive_status_milestone(status, data_dir=data_dir)
        print("\n✔ golive_status.json updated with milestone_30d.")


if __name__ == "__main__":
    main()
