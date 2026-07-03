#!/usr/bin/env python3
"""check_snapshot_freshness.py — build-time STALE_SNAPSHOT gate (P0-2 audit fix).

Fails the landing build (exit 1) when landing/src/data/track_snapshot.json's `as_of` is older than
48h relative to the build date — so the public hero/track numbers can never silently drift stale while
still being presented as current. Run as a prebuild step AFTER generate_track_snapshot.py.

- Fresh (<= 2 calendar days old, ~48h with date-granularity slack) -> exit 0.
- Stale -> exit 1 with a clear STALE_SNAPSHOT message.
- Unreadable/missing snapshot or no as_of -> exit 0 (a different problem; do not block the build here).
- Emergency override: set SPA_ALLOW_STALE_SNAPSHOT=1 to bypass (logged).
"""
import datetime
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_MAX_DAYS = 2  # ~48h, with slack for the date-only `as_of` granularity


def main() -> int:
    if os.environ.get("SPA_ALLOW_STALE_SNAPSHOT") == "1":
        print("check_snapshot_freshness: SPA_ALLOW_STALE_SNAPSHOT=1 — bypassing freshness gate")
        return 0
    try:
        snap = json.loads(_SNAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"check_snapshot_freshness: snapshot unreadable ({_SNAP}) — skipping (not a freshness issue)")
        return 0
    as_of = snap.get("as_of")
    if not as_of:
        print("check_snapshot_freshness: snapshot has no as_of — skipping")
        return 0
    try:
        as_of_date = datetime.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        print(f"check_snapshot_freshness: unparseable as_of {as_of!r} — skipping")
        return 0
    today = datetime.datetime.now(datetime.timezone.utc).date()
    days_old = (today - as_of_date).days
    if days_old > _MAX_DAYS:
        print(
            f"STALE_SNAPSHOT: track_snapshot.json as_of={as_of} is {days_old} days old "
            f"(> {_MAX_DAYS}d / ~48h). The site would publish stale hero/track numbers. "
            f"Refresh the committed data (daily cycle push) or run "
            f"generate_track_snapshot.py, then rebuild. Emergency bypass: SPA_ALLOW_STALE_SNAPSHOT=1.",
            file=sys.stderr,
        )
        return 1
    print(f"check_snapshot_freshness: OK — as_of={as_of} ({days_old}d old, <= {_MAX_DAYS}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
