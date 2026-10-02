"""spa_core/paper_trading/paper_observations.py — one observation per scheduled run, per book (ADR-533).

The sleeves write ONE accounting row a day, but they run every hour; a loop must be supervised every
hour. This journal is the evidence of the scheduled runs themselves: what the run saw (data quality),
what it valued, what it decided — one line per hour slot.

* **idempotent:** the key is ``(book, hour slot)``; a second run in the same slot appends nothing, so a
  re-run never duplicates an observation (it is reported as ``duplicate_slot``);
* **missed runs are visible:** ``missed_runs`` counts them from the INTERVALS between consecutive runs
  (a 2 h interval on an hourly schedule = one missed run); nothing fills them in. ``gaps`` lists empty
  clock-hour slots, which is NOT the same question: launchd ``StartInterval`` drifts a few seconds a
  run, so a run at 05:59:59 followed by one at 07:00:10 leaves slot 06 empty with no run missed
  (measured 2026-10-02 on both sleeves);
* **append-only, atomic:** the file is rewritten whole through ``atomic_save`` (tmp + ``os.replace``) and
  never shortened except by the retention window (newest ``MAX_LINES`` kept).

Paper evidence only; LLM_FORBIDDEN, stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

MAX_LINES = 24 * 120          # ~120 days of hourly slots


def path(data_dir: "Path | str", book: str) -> Path:
    return Path(data_dir) / "paper_observations" / f"{book}.jsonl"


def slot_of(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H")


def read(data_dir: "Path | str", book: str) -> list[dict]:
    p = path(data_dir, book)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except ValueError:
            continue           # a torn line is skipped, not repaired
    return out


def record(data_dir: "Path | str", book: str, now: datetime, observation: dict) -> str:
    """Append the run's observation for its hour slot. Returns ``appended`` or ``duplicate_slot``."""
    from spa_core.utils.atomic import atomic_save_text

    rows = read(data_dir, book)
    slot = slot_of(now)
    if any(r.get("slot") == slot for r in rows):
        return "duplicate_slot"
    rows.append({"slot": slot, "book": book, "run_ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), **observation})
    rows = rows[-MAX_LINES:]
    p = path(data_dir, book)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_save_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), str(p))
    return "appended"


def gaps(rows: list[dict], *, since_slot: Optional[str] = None) -> list[str]:
    """Hour slots with no observation between the first and last recorded slot (missed runs)."""
    slots = sorted({r["slot"] for r in rows if r.get("slot") and (since_slot is None or r["slot"] >= since_slot)})
    if len(slots) < 2:
        return []
    have, out = set(slots), []
    t = datetime.strptime(slots[0], "%Y-%m-%dT%H")
    end = datetime.strptime(slots[-1], "%Y-%m-%dT%H")
    while t < end:
        t += timedelta(hours=1)
        s = t.strftime("%Y-%m-%dT%H")
        if s not in have:
            out.append(s)
    return out


def missed_runs(rows: list[dict], *, expected_h: float = 1.0, since: Optional[datetime] = None,
                now: Optional[datetime] = None) -> int:
    """Scheduled runs that did not happen, from the intervals between recorded runs.

    A run was due every ``expected_h`` after the previous one; it counts as missed when the next
    recorded run came more than half an interval after it was due (a few seconds of launchd drift
    across an hour boundary is not a miss). With ``now``, the runs due after the LAST recorded run are
    counted too — a stopped process is a growing number, never a measured zero. With ``since``, only
    runs that were due at or after it are counted (a restart after 30 h is not «29 in 24 h»).
    """
    ts = []
    for r in rows:
        try:
            ts.append(datetime.strptime(str(r.get("run_ts")), "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
    ts.sort()
    step = timedelta(hours=expected_h)
    grace = step / 2
    ends = list(zip(ts, ts[1:])) + ([(ts[-1], now)] if (ts and now is not None and now > ts[-1]) else [])
    missed = 0
    for a, b in ends:
        due = a + step
        while due + grace < b:
            if since is None or due >= since:
                missed += 1
            due += step
    return missed
