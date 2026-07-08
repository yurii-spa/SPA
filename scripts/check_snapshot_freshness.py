#!/usr/bin/env python3
"""check_snapshot_freshness.py — snapshot-freshness monitor (WARN-ONLY by default).

Checks whether landing/src/data/track_snapshot.json's `as_of` is older than ~48h. This is an
OPERATOR MONITORING signal, not a deploy blocker: a stale snapshot must NOT stop the public site
from deploying (CF Pages) — the site handles staleness gracefully (the hero shows an honest
"as of <date>" label / degraded plaque, and /admin surfaces a freshness tile). Run as a prebuild
step AFTER generate_track_snapshot.py.

Exit policy (2026-07-09 — owner: stale data must not block production deploys):
- Fresh (<= 2 calendar days old) -> exit 0 ("OK").
- Stale -> print a clear STALE_SNAPSHOT WARNING but **exit 0 by default** (warn-only).
- STRICT mode (opt-in): set STRICT_SNAPSHOT_FRESHNESS=1/true to make staleness exit 1 (e.g. a local
  pre-commit hook that wants a hard gate). Cloudflare builds do NOT set it → never blocked.
- Unreadable/missing/undated snapshot -> exit 0 (a different problem; not a freshness gate).
- SPA_ALLOW_STALE_SNAPSHOT=1 still forces a clean pass (legacy emergency bypass).

Also writes data/snapshot_freshness.json (best-effort) so operator monitoring can read the state.
"""
import datetime
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_STATUS = _ROOT / "data" / "snapshot_freshness.json"
_MAX_DAYS = 2  # ~48h, with slack for the date-only `as_of` granularity


def _strict() -> bool:
    return os.environ.get("STRICT_SNAPSHOT_FRESHNESS", "").strip().lower() in ("1", "true", "yes")


def _write_status(payload: dict) -> None:
    try:
        _STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATUS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _STATUS)
    except Exception:  # noqa: BLE001 — status is best-effort, never fatal
        pass


def main() -> int:
    if os.environ.get("SPA_ALLOW_STALE_SNAPSHOT") == "1":
        print("check_snapshot_freshness: SPA_ALLOW_STALE_SNAPSHOT=1 — clean pass")
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
    fresh = days_old <= _MAX_DAYS
    _write_status({
        "fresh": fresh, "as_of": str(as_of), "days_old": days_old, "max_days": _MAX_DAYS,
        "checked_at": today.isoformat(),
        "message": "OK" if fresh else f"Track snapshot is stale ({days_old}d old, > {_MAX_DAYS}d)",
    })
    if not fresh:
        print(
            f"STALE_SNAPSHOT (warning): track_snapshot.json as_of={as_of} is {days_old} days old "
            f"(> {_MAX_DAYS}d / ~48h). The public site shows an honest 'as of' label and /admin flags it; "
            f"refresh via generate_track_snapshot.py (daily-cycle push). "
            f"WARN-ONLY — the build is NOT blocked. Set STRICT_SNAPSHOT_FRESHNESS=1 for a hard gate.",
            file=sys.stderr,
        )
        return 1 if _strict() else 0
    print(f"check_snapshot_freshness: OK — as_of={as_of} ({days_old}d old, <= {_MAX_DAYS}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
