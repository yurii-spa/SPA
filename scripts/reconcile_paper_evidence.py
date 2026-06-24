#!/usr/bin/env python3
"""
scripts/reconcile_paper_evidence.py — align paper_evidence.json equity to the curve.

The canonical equity series is data/equity_curve_daily.json (close_equity per real
day, written by cycle_runner). data/paper_evidence.json carries its own equity_value
column which historically drifted (an old backfill wrote wrong values: ±$216 on
2026-06-10..13, −$88 on 06-18..20) while dates/day-counts stayed honest. Going
forward cycle_runner records the correct value (result.current_equity), so this is a
one-time repair — but the script is idempotent and safe to re-run any time.

For each evidence day it sets:
  - equity_value  = equity_curve_daily close_equity for that date
  - day_return_pct = (close - prev_close) / prev_close   (base_capital for day 1)
All other fields (apy_pct, strategy_id, notes, date) are preserved. Atomic write.

LLM_FORBIDDEN. stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EVID = _ROOT / "data" / "paper_evidence.json"
_CURVE = _ROOT / "data" / "equity_curve_daily.json"


def reconcile(dry_run: bool = False) -> dict:
    evid = json.loads(_EVID.read_text(encoding="utf-8"))
    curve_doc = json.loads(_CURVE.read_text(encoding="utf-8"))
    close_by_date = {
        b["date"]: float(b["close_equity"])
        for b in curve_doc.get("daily", [])
        if isinstance(b, dict) and "date" in b and b.get("close_equity") is not None
    }
    base = float(evid.get("base_capital", 100_000.0))

    days = evid.get("days", [])
    fixed = 0
    prev_close = base
    for d in days:
        dt = d.get("date")
        close = close_by_date.get(dt)
        if close is None:
            prev_close = d.get("equity_value", prev_close)
            continue
        new_ret = round((close - prev_close) / prev_close * 100.0, 6) if prev_close else 0.0
        if (round(d.get("equity_value", 0), 2) != round(close, 2)
                or round(d.get("day_return_pct", 0), 6) != new_ret):
            d["equity_value"] = round(close, 2)
            d["day_return_pct"] = new_ret
            fixed += 1
        prev_close = close

    if not dry_run and fixed:
        tmp = _EVID.with_suffix(".tmp")
        tmp.write_text(json.dumps(evid, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_EVID)
    return {"days": len(days), "fixed": fixed, "dry_run": dry_run}


if __name__ == "__main__":
    res = reconcile(dry_run="--dry-run" in sys.argv)
    print(f"reconcile_paper_evidence: {res['fixed']}/{res['days']} day(s) corrected"
          f"{' (dry-run)' if res['dry_run'] else ''}")
