#!/usr/bin/env python3
# LLM_FORBIDDEN
"""
Deterministic correction of fabricated 10.115% entries in the track evidence.

OWNER DECISION 2026-07-23 (Variant A, ADR-058, card owner-decision-v-zhurnalah-dohodnosti):
the daily cycle used to inject the S7 BACKTEST value 10.115% as a fallback when it could not
read a real daily APY. Those rows are non-measurements. Variant A = **flag, do not delete**:
mark each with ``fabricated: true`` + reason (keeps full auditability — we sell "verify us"),
and recompute the APY milestones from REAL days only.

Honesty: nothing is invented or deleted; rows stay, flagged. The milestone recompute reuses the
SAME rule the producer now uses (skip fabricated) so the fix is durable, not overwritten next cycle.

Usage:
    python3 scripts/fix_fabricated_evidence.py --data-dir data --dry-run   # show before→after, no write
    python3 scripts/fix_fabricated_evidence.py --data-dir data             # apply (atomic)
"""
# LLM_FORBIDDEN

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FABRICATED_VALUE = 10.115           # the S7 backtest fallback the cycle injected
FABRICATED_REASON = "S7 backtest fallback injected by cycle_runner when live APY was unavailable (ADR-058)"


def _is_fabricated(row: dict) -> bool:
    return isinstance(row, dict) and round(float(row.get("apy_pct", 0) or 0), 3) == FABRICATED_VALUE


def _flag_rows(rows: list) -> list:
    """Return dates of rows newly flagged fabricated (idempotent)."""
    flagged = []
    for r in rows:
        if _is_fabricated(r) and not r.get("fabricated"):
            r["fabricated"] = True
            r["fabricated_reason"] = FABRICATED_REASON
            flagged.append(r.get("date"))
    return flagged


def _recompute_milestones(daily_log: list, milestones: list) -> list:
    """First date each target is reached, REAL (non-fabricated) days only.

    Mirrors the producer's ``_refresh_milestones_reached`` EXACTLY: only REACHED levels appear in
    the list (an unreached level is absent, not present-with-null) — so the fix is byte-stable
    across the next cycle instead of being reshaped by the producer.
    """
    reached: dict = {}
    for e in sorted(daily_log, key=lambda x: x["date"]):
        if e.get("fabricated"):
            continue
        for m in milestones:
            if m["level"] not in reached and e.get("apy_pct", 0) >= m["target_pct"]:
                reached[m["level"]] = e["date"]
    by_level = {m["level"]: m for m in milestones}
    return [
        {**by_level[lvl], "first_reached_date": date}
        for lvl, date in sorted(reached.items())
    ]


def fix(data_dir: Path, dry_run: bool) -> dict:
    report = {"paper_evidence": {}, "apy_milestone": {}, "applied": not dry_run}

    # ── paper_evidence.json ──────────────────────────────────────────────────
    pe_path = data_dir / "paper_evidence.json"
    pe = json.loads(pe_path.read_text(encoding="utf-8"))
    pe_rows = pe.get("days") or pe.get("entries") or []
    report["paper_evidence"]["flagged"] = _flag_rows(pe_rows)

    # ── apy_milestone_log.json ───────────────────────────────────────────────
    am_path = data_dir / "apy_milestone_log.json"
    am = json.loads(am_path.read_text(encoding="utf-8"))
    daily = am.get("daily_log", [])
    report["apy_milestone"]["flagged"] = _flag_rows(daily)
    before = {m["target_pct"]: m.get("first_reached_date") for m in am.get("milestones_reached", [])}
    # keep the level/name/target_pct schema of the existing milestones
    templ = [{"level": m["level"], "name": m["name"], "target_pct": m["target_pct"]}
             for m in am.get("milestones_reached", [])]
    am["milestones_reached"] = _recompute_milestones(daily, templ)
    after = {m["target_pct"]: m.get("first_reached_date") for m in am["milestones_reached"]}
    report["apy_milestone"]["milestones_before"] = before
    report["apy_milestone"]["milestones_after"] = after

    if not dry_run:
        from spa_core.utils.atomic import atomic_save
        atomic_save(pe, str(pe_path))
        atomic_save(am, str(am_path))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rep = fix(Path(args.data_dir), args.dry_run)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
