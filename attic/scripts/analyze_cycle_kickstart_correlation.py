#!/usr/bin/env python3
"""Churn investigation (2026-09-03, owner-decision-knigu-perekladyvayut-22-raza-za-nedelyu):
correlate each `com.spa.daily_cycle` run against deploy-gate kickstarts recorded by
check_agent_before_deploy.sh (marker file /tmp/spa_deploy_gate_kickstarts.log, added 2026-09-03).

A daily_cycle run is "explained by the gate" if a gate-kickstart for that label landed within
TOLERANCE_SECONDS before it — launchctl kickstart is not instantaneous, so a small window is
expected, not evidence of a coincidence. Runs with no matching gate-kickstart are unexplained:
either the genuine 08:00 scheduled fire, or some other mechanism not yet found.

No writes. Read-only diagnostic — prints a report, changes nothing.
"""
import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOLERANCE_SECONDS = 120
MARKER_LOG = Path("/tmp/spa_deploy_gate_kickstarts.log")
LABEL = "com.spa.daily_cycle"

_CYCLE_START_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\] Starting daily paper cycle")
_MARKER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z gate-kickstart label=(\S+)")


def _parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def load_cycle_starts(log_dir: Path):
    starts = []
    for f in sorted(log_dir.glob("daily_cycle_*.log")):
        for line in f.read_text(errors="replace").splitlines():
            m = _CYCLE_START_RE.match(line)
            if m:
                starts.append(_parse_ts(m.group(1)))
    return sorted(starts)


def load_gate_kickstarts(marker_log: Path, label: str):
    if not marker_log.exists():
        return []
    out = []
    for line in marker_log.read_text(errors="replace").splitlines():
        m = _MARKER_RE.match(line)
        if m and m.group(2) == label:
            out.append(_parse_ts(m.group(1)))
    return sorted(out)


def correlate(cycle_starts, gate_kickstarts, tolerance_seconds: int):
    window = timedelta(seconds=tolerance_seconds)
    explained, unexplained = [], []
    for ts in cycle_starts:
        hit = any(0 <= (ts - g).total_seconds() <= tolerance_seconds for g in gate_kickstarts)
        (explained if hit else unexplained).append(ts)
    return explained, unexplained


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs", type=Path)
    ap.add_argument("--marker-log", default=MARKER_LOG, type=Path)
    ap.add_argument("--tolerance-seconds", default=TOLERANCE_SECONDS, type=int)
    args = ap.parse_args()

    cycle_starts = load_cycle_starts(args.logs_dir)
    gate_kickstarts = load_gate_kickstarts(args.marker_log, LABEL)
    explained, unexplained = correlate(cycle_starts, gate_kickstarts, args.tolerance_seconds)

    print(f"daily_cycle runs found:      {len(cycle_starts)}")
    print(f"gate-kickstarts recorded:    {len(gate_kickstarts)} "
          f"(marker log: {args.marker_log}, present={args.marker_log.exists()})")
    print(f"explained by gate kickstart: {len(explained)}")
    print(f"UNEXPLAINED:                 {len(unexplained)}")
    if unexplained:
        print("\nUnexplained run timestamps (candidates: genuine 08:00 fire, or another mechanism):")
        for ts in unexplained:
            print(f"  {ts.isoformat()}")
    if not gate_kickstarts:
        print("\nNOTE: marker log is empty/missing — either no gate has run for daily_cycle since "
              "instrumentation landed (2026-09-03), or CHECK_ONLY=1 was used (no kickstart happens "
              "in that mode, by design). Zero gate-kickstarts does NOT mean zero explanation power; "
              "it means nothing to correlate against yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
