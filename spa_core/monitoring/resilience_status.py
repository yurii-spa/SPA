"""
spa_core/monitoring/resilience_status.py — resilience posture rollup (R8).

WHY THIS EXISTS
---------------
The resilience sprint produced several PROOFS that each write their own status JSON:

  * data/dr_offsite_status.json   (R6, spa_core/dr/offsite_copy.py)   — offsite copy + verify
  * data/restore_drill_status.json(R7, spa_core/dr/drill_restore.py)  — restore-from-backup drill
  * data/fleet_drill_status.json  (R4, spa_core/monitoring/drill_fleet_down.py) — fleet-down drill

Each proof is legible on its own, but nobody wants to open three files (and remember
their shapes + freshness windows) to answer "are we resilient right now?". This module
reads the three statuses, derives a single posture, and writes data/resilience_status.json
so ONE file (and one SYSTEM_BRIEFING section) answers that question honestly.

DESIGN (mirrors the briefing's T1 snapshot-age guard)
-----------------------------------------------------
- stdlib only, deterministic, fail-CLOSED.
- Each proof has an age threshold matching its cadence:
    * offsite copy runs daily        → stale if last run > OFFSITE_STALE_DAYS (2d)
    * restore drill runs ~weekly      → stale if last run > DRILL_STALE_DAYS (8d)
    * fleet drill runs ~weekly        → stale if last run > DRILL_STALE_DAYS (8d)
- A MISSING status file is treated as "never run" → contributes WARNING (we refuse to
  vouch for a proof that has never been exercised).
- overall == OK  iff  every proof is fresh AND passed (offsite verified, drills all_ok).
  overall == WARNING otherwise (with the reasons collected in `notes`).
- We READ ONLY the producers' output. This module never runs a backup, drill, or offsite
  copy itself (those are owned by other agents) — it is a pure read-derive-write rollup.
- Status written atomically via spa_core.utils.atomic.atomic_save.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from spa_core.utils.atomic import atomic_save  # noqa: E402

DATA_DIR = REPO / "data"
OFFSITE_STATUS = DATA_DIR / "dr_offsite_status.json"
RESTORE_STATUS = DATA_DIR / "restore_drill_status.json"
FLEET_STATUS = DATA_DIR / "fleet_drill_status.json"
OUTPUT = DATA_DIR / "resilience_status.json"

# Freshness windows, derived from each proof's expected cadence (fail-honest).
OFFSITE_STALE_DAYS = 2.0   # offsite copy is a daily job → >2d means it skipped a day
DRILL_STALE_DAYS = 8.0     # drills run ~weekly → >8d means a weekly slot was missed


# ── helpers ─────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    """Return parsed JSON dict, or None if the file is absent/empty/unreadable.

    None is the honest "never run / unusable" signal (distinct from {} which a
    producer could legitimately write); callers map None → never_run + WARNING.
    """
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _age_days(ts: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Age in days since ISO timestamp ``ts`` (UTC), or None if unparseable.

    Tolerates the two timestamp shapes the producers emit:
      * "2026-06-27T10:04:58.838009+00:00" (isoformat with offset)
      * "2026-06-27T10:04:58Z"             (Z suffix)
    """
    if not ts or not isinstance(ts, str):
        return None
    now = now or datetime.now(timezone.utc)
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # fall back to the leading 19 chars (date+time, no fractional/offset)
        try:
            dt = datetime.fromisoformat(ts[:19].replace(" ", "T"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def _is_stale(age_days: Optional[float], threshold_days: float) -> bool:
    """Stale iff we can't date the proof, or it's older than its window (fail-CLOSED)."""
    if age_days is None:
        return True
    return age_days > threshold_days


# ── per-proof derivation ─────────────────────────────────────────────────────────
def _derive_offsite(now: Optional[datetime] = None) -> Dict[str, Any]:
    d = _read_json(OFFSITE_STATUS)
    if d is None:
        return {
            "last_ts": None, "verified": False, "is_real_remote": False,
            "stale": True, "never_run": True,
        }
    last_ts = d.get("last_offsite_ts")
    age = _age_days(last_ts, now)
    return {
        "last_ts": last_ts,
        "verified": bool(d.get("verified", False)),
        "is_real_remote": bool(d.get("is_real_remote", False)),
        "stale": _is_stale(age, OFFSITE_STALE_DAYS),
        "never_run": False,
        "age_days": round(age, 2) if age is not None else None,
    }


def _derive_drill(path: Path, ts_keys, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Generic restore/fleet drill derivation.

    ts_keys: ordered candidate keys for the drill timestamp (producers differ:
    restore uses 'last_drill_ts', fleet uses 'generated_at').
    all_ok: restore uses 'all_ok', fleet uses 'passed'.
    """
    d = _read_json(path)
    if d is None:
        return {
            "last_ts": None, "all_ok": False, "stale": True, "never_run": True,
        }
    last_ts = None
    for k in ts_keys:
        if d.get(k):
            last_ts = d[k]
            break
    age = _age_days(last_ts, now)
    all_ok = bool(d.get("all_ok", d.get("passed", False)))
    return {
        "last_ts": last_ts,
        "all_ok": all_ok,
        "stale": _is_stale(age, DRILL_STALE_DAYS),
        "never_run": False,
        "age_days": round(age, 2) if age is not None else None,
    }


# ── rollup ────────────────────────────────────────────────────────────────────────
def build_posture(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Read the 3 proof statuses → derive {offsite, restore_drill, fleet_drill, overall, notes}.

    Pure (no I/O side effects beyond reading the status files). `now` is injectable
    so the staleness logic is deterministically testable.
    """
    now = now or datetime.now(timezone.utc)
    offsite = _derive_offsite(now)
    restore = _derive_drill(RESTORE_STATUS, ("last_drill_ts",), now)
    fleet = _derive_drill(FLEET_STATUS, ("generated_at", "last_drill_ts", "ts"), now)

    notes = []
    # offsite reasons
    if offsite["never_run"]:
        notes.append("offsite: never run (dr_offsite_status.json missing)")
    else:
        if offsite["stale"]:
            notes.append(f"offsite: STALE (> {OFFSITE_STALE_DAYS:g}d since last copy)")
        if not offsite["verified"]:
            notes.append("offsite: last copy NOT verified")
        if not offsite["is_real_remote"]:
            notes.append("offsite: dest is the LOCAL stand-in (no real remote configured) [owner-flagged]")
    # restore-drill reasons
    if restore["never_run"]:
        notes.append("restore_drill: never run (restore_drill_status.json missing)")
    else:
        if restore["stale"]:
            notes.append(f"restore_drill: STALE (> {DRILL_STALE_DAYS:g}d since last drill)")
        if not restore["all_ok"]:
            notes.append("restore_drill: last drill did NOT pass (all_ok=false)")
    # fleet-drill reasons
    if fleet["never_run"]:
        notes.append("fleet_drill: never run (fleet_drill_status.json missing)")
    else:
        if fleet["stale"]:
            notes.append(f"fleet_drill: STALE (> {DRILL_STALE_DAYS:g}d since last drill)")
        if not fleet["all_ok"]:
            notes.append("fleet_drill: last drill did NOT pass")

    # overall: OK iff every proof fresh AND passing. The local-stand-in offsite dest
    # is owner-flagged but does NOT by itself force WARNING (the mechanism is proven);
    # an UNVERIFIED offsite copy DOES (the copy itself is untrustworthy).
    ok = (
        not offsite["never_run"] and not offsite["stale"] and offsite["verified"]
        and not restore["never_run"] and not restore["stale"] and restore["all_ok"]
        and not fleet["never_run"] and not fleet["stale"] and fleet["all_ok"]
    )
    overall = "OK" if ok else "WARNING"

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema": "spa_resilience_status/v1",
        "llm_forbidden": True,
        "thresholds": {
            "offsite_stale_days": OFFSITE_STALE_DAYS,
            "drill_stale_days": DRILL_STALE_DAYS,
        },
        "offsite": offsite,
        "restore_drill": restore,
        "fleet_drill": fleet,
        "overall": overall,
        "notes": notes,
    }


def write_status(posture: Optional[Dict[str, Any]] = None,
                 path: Optional[Path] = None) -> Dict[str, Any]:
    """Derive (if not supplied) and atomically write the resilience rollup. Returns it.

    `path` defaults to the module-level OUTPUT resolved at CALL time (not bound as a
    default arg) so tests that monkeypatch rs.OUTPUT redirect the write.
    """
    posture = posture or build_posture()
    atomic_save(posture, str(path or OUTPUT))
    return posture


def main() -> int:
    posture = write_status()
    print(f"[resilience_status] overall={posture['overall']}  → {OUTPUT}")
    for n in posture["notes"]:
        print(f"  · {n}")
    # exit 0 even on WARNING — this is a reporter, not a gate (the briefing surfaces it).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
