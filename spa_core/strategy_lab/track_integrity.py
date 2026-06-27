"""
spa_core/strategy_lab/track_integrity.py — continuity/integrity guard over the FORWARD
live-paper tracks (rates-desk FixedCarry + the Strategy-Lab sleeves).

These forward tracks are only ~3 days deep today, but they WILL BECOME the fundability
evidence next to the main go-live track. They therefore need the same gap-monitor discipline
the main track already has (spa_core/paper_trading/gap_monitor.py) — applied NOW, so a missing
or duplicated forward-track day is detected on the day it happens, not discovered as a 4-day
hole on day 28.

This module MIRRORS the main go-live gap-monitor's discipline, adapted to the forward-track
series shape (an explicit per-day list of points, each {"date": "YYYY-MM-DD", ...}):

  check_track_integrity(series, *, schedule_hours=24) -> dict
      Verify ONE series is append-only & continuous:
        - monotonic, non-DUPLICATE, in-ORDER dates,
        - no GAP wider than `schedule_hours` between the first and last dated point,
        - no FUTURE dates (a fabricated/clock-skewed point).
      Fail-CLOSED: anything malformed → not ok.

  check_all_forward_tracks(data_dir) -> dict
      Run the per-series check over every rates_desk/paper + strategy_lab_paper *_series.json,
      aggregate, and write data/forward_track_integrity.json atomically.

Advisory only: it DETECTS + FLAGS (via the push_policy digest queue, never a Telegram flood); it
never moves capital, never touches execution/*, never blocks a tick. stdlib only, deterministic,
fail-CLOSED, atomic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.strategy_lab.track_integrity")

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
RATES_PAPER_DIR = DATA_DIR / "rates_desk" / "paper"
LAB_PAPER_DIR = DATA_DIR / "strategy_lab_paper"
INTEGRITY_FILE = DATA_DIR / "forward_track_integrity.json"

# A forward track is ticked once per UTC calendar day; one day = 24h. A larger schedule
# (e.g. a weekly track) widens the allowed spacing. Weekends are NOT exempted here (unlike the
# main track) because these forward sleeves tick every calendar day, including weekends.
DEFAULT_SCHEDULE_HOURS = 24


def _utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _coerce_series(series: Any) -> Optional[List[dict]]:
    """Accept either the on-disk doc {"id":.., "series":[...]} or a bare list of points.

    Returns the list of point-dicts, or None if the shape is unusable (fail-CLOSED: an
    unusable shape is a malformed track, not an empty one)."""
    if isinstance(series, dict):
        pts = series.get("series")
        if pts is None:
            return None
        series = pts
    if not isinstance(series, list):
        return None
    return series


def check_track_integrity(series: Any, *, schedule_hours: int = DEFAULT_SCHEDULE_HOURS) -> dict:
    """Verify a single forward-track series is append-only & continuous.

    Checks (mirroring the main go-live gap-monitor discipline):
      - every point is a dict carrying a parseable ``date`` (YYYY-MM-DD),
      - dates are MONOTONIC non-decreasing as stored (append-only / in-order),
      - no DUPLICATE calendar dates (a same-day point must REFRESH in place, never duplicate),
      - no GAP wider than ``schedule_hours`` between consecutive dates (a missing day),
      - no FUTURE date (a fabricated / clock-skewed point).

    Returns a dict:
      ok           — True only if NONE of the above failed.
      n_points     — number of points seen.
      first_date   — first date (ISO) or None.
      last_date    — last date (ISO) or None.
      duplicates   — list of dates that appear more than once.
      gaps         — list of {"from","to","days_missed"} for spacing > schedule.
      out_of_order — list of {"prev","next"} where stored order decreases.
      future       — list of dates strictly after today (UTC).
      reason       — short machine reason ("ok" | "malformed" | "duplicates" | "gaps" |
                     "out_of_order" | "future" | "empty").

    Fail-CLOSED: a malformed series (not a list / non-dict points / unparseable dates) →
    ok=False, reason="malformed". An EMPTY series is ok (a brand-new track, nothing to fault)
    but flagged reason="empty".
    """
    schedule_days = max(1, int(schedule_hours) // 24)  # >24h schedule widens allowed spacing

    base = {
        "ok": False,
        "n_points": 0,
        "first_date": None,
        "last_date": None,
        "duplicates": [],
        "gaps": [],
        "out_of_order": [],
        "future": [],
        "reason": "malformed",
    }

    points = _coerce_series(series)
    if points is None:
        return base

    if not points:
        base.update(ok=True, n_points=0, reason="empty")
        return base

    # Parse each point's date IN STORED ORDER (so we can detect out-of-order appends).
    ordered: List[datetime.date] = []
    for p in points:
        if not isinstance(p, dict):
            return base  # malformed point → fail-CLOSED
        raw = p.get("date")
        if not isinstance(raw, str) or not raw:
            return base  # missing/non-string date → fail-CLOSED
        try:
            ordered.append(datetime.date.fromisoformat(raw[:10]))
        except ValueError:
            return base  # unparseable date → fail-CLOSED

    base["n_points"] = len(ordered)
    base["first_date"] = ordered[0].isoformat()
    base["last_date"] = ordered[-1].isoformat()

    # Out-of-order: stored order must be non-decreasing (append-only discipline).
    out_of_order = []
    for i in range(1, len(ordered)):
        if ordered[i] < ordered[i - 1]:
            out_of_order.append({"prev": ordered[i - 1].isoformat(),
                                 "next": ordered[i].isoformat()})

    # Duplicates: each calendar day appears at most once (same-day point must refresh in place).
    seen: Dict[datetime.date, int] = {}
    for d in ordered:
        seen[d] = seen.get(d, 0) + 1
    duplicates = sorted(d.isoformat() for d, c in seen.items() if c > 1)

    # Gaps: on the SORTED unique date axis, no spacing wider than the schedule.
    uniq = sorted(seen.keys())
    gaps = []
    for i in range(1, len(uniq)):
        delta = (uniq[i] - uniq[i - 1]).days
        if delta > schedule_days:
            gaps.append({"from": uniq[i - 1].isoformat(),
                         "to": uniq[i].isoformat(),
                         "days_missed": delta - 1})

    # Future dates: nothing may be dated after today (UTC) — fabricated / clock-skewed.
    today = _utc_today()
    future = [d.isoformat() for d in uniq if d > today]

    base["duplicates"] = duplicates
    base["out_of_order"] = out_of_order
    base["gaps"] = gaps
    base["future"] = future

    if future:
        base["reason"] = "future"
    elif duplicates:
        base["reason"] = "duplicates"
    elif out_of_order:
        base["reason"] = "out_of_order"
    elif gaps:
        base["reason"] = "gaps"
    else:
        base["reason"] = "ok"

    base["ok"] = not (duplicates or gaps or out_of_order or future)
    return base


def _discover_series_files(data_dir: Path) -> List[Path]:
    """All forward-track *_series.json under rates_desk/paper + strategy_lab_paper."""
    out: List[Path] = []
    for sub in (data_dir / "rates_desk" / "paper", data_dir / "strategy_lab_paper"):
        if sub.is_dir():
            out.extend(sorted(sub.glob("*_series.json")))
    return out


def _track_name(path: Path) -> str:
    """A stable track name: <parent-dir>/<id> (id = filename minus _series.json)."""
    return f"{path.parent.name}/{path.name[:-len('_series.json')]}"


def check_all_forward_tracks(data_dir: Optional[Path] = None, *, write: bool = True) -> dict:
    """Run check_track_integrity over EVERY forward-track series and aggregate.

    Writes data/forward_track_integrity.json atomically (unless write=False).

    Returns:
      {
        "generated_at": iso,
        "all_ok": bool,            # True iff every track is ok
        "n_tracks": int,
        "n_failing": int,
        "tracks": [ {name, ok, n_points, first_date, last_date,
                     duplicates, gaps, out_of_order, future, reason}, ... ],
      }
    Fail-CLOSED: a series file that cannot even be loaded is reported as a not-ok track
    (reason="unreadable"), never silently skipped.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    files = _discover_series_files(root)

    tracks: List[dict] = []
    for f in files:
        name = _track_name(f)
        try:
            doc = atomic_load(str(f), default=None)
        except Exception:  # noqa: BLE001 — a corrupt file is a not-ok track, never a crash
            doc = None
        if doc is None:
            tracks.append({
                "name": name, "ok": False, "n_points": 0,
                "first_date": None, "last_date": None,
                "duplicates": [], "gaps": [], "out_of_order": [], "future": [],
                "reason": "unreadable",
            })
            continue
        res = check_track_integrity(doc)
        res = {"name": name, **res}
        tracks.append(res)

    n_failing = sum(1 for t in tracks if not t["ok"])
    out = {
        "generated_at": _utc_now_iso(),
        "all_ok": n_failing == 0,
        "n_tracks": len(tracks),
        "n_failing": n_failing,
        "tracks": tracks,
    }
    if write:
        # Write the report under the SAME data dir we scanned (so a test/sandbox run lands in its
        # own tmp dir, never the live data/forward_track_integrity.json).
        atomic_save(out, str(root / INTEGRITY_FILE.name))
    return out


def flag_if_broken(report: Optional[dict] = None, *, data_dir: Optional[Path] = None) -> dict:
    """Advisory hook for the hourly paper agents: run the aggregate check and, if ANY forward
    track is broken (gap / duplicate / out-of-order / future / unreadable), enqueue ONE digest
    line per broken track to the push_policy digest queue (NEVER a Telegram flood, NEVER raises).

    Returns the aggregate report so callers can also log/inspect it. Safe to call every tick:
    the digest queue is folded into the single daily digest, so repeated calls do not flood.
    """
    rep = report if report is not None else check_all_forward_tracks(data_dir)
    broken = [t for t in rep.get("tracks", []) if not t.get("ok")]
    if not broken:
        return rep
    try:
        from spa_core.telegram import push_policy
        for t in broken:
            detail = []
            if t.get("gaps"):
                detail.append(f"gaps={t['gaps']}")
            if t.get("duplicates"):
                detail.append(f"dups={t['duplicates']}")
            if t.get("out_of_order"):
                detail.append(f"out_of_order={t['out_of_order']}")
            if t.get("future"):
                detail.append(f"future={t['future']}")
            body = (f"reason={t.get('reason')} "
                    f"({t.get('first_date')}..{t.get('last_date')}, n={t.get('n_points')}); "
                    + "; ".join(detail)) if detail else f"reason={t.get('reason')}"
            push_policy.enqueue_digest(
                f"forward_track_integrity:{t.get('name')}",
                f"Forward-track integrity: {t.get('name')}",
                body,
                severity="WARNING",
                reason="forward_track_integrity_broken",
                data_dir=str(data_dir) if data_dir is not None else None,
            )
    except Exception as exc:  # noqa: BLE001 — the advisory flag must NEVER crash a paper tick
        log.warning("forward-track integrity digest route failed: %s", exc)
    return rep


def main() -> int:
    import json
    rep = check_all_forward_tracks()
    print(json.dumps(rep, indent=2, default=str))
    return 0 if rep["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
