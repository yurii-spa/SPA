#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.replay_equity — re-derive the equity bars from the archived cycle inputs and
compare with what the cycle wrote (inbox «Целостность трека SPA», task 3).

NO FORK: the yield is recomputed by the very function the cycle uses
(``spa_core.paper_trading.equity._accrue_daily_yield``), so the replay answers "did the stored
inputs produce the stored bar?", not "does a second formula agree with the first?".

Three outcomes (never a raise):
  PASS      — every archived date re-derives to the bar within ``tolerance_usd`` (default 1 cent)
  FAIL      — at least one date differs (names them, worst delta)
  UNCHECKED — no archive / broken chain / no overlap with the curve — «не измерено», not «сходится»
Dates before the archive started are ``pre-archive`` by construction and are NOT judged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from spa_core.audit import cycle_inputs_archive as archive
from spa_core.paper_trading.equity import _accrue_daily_yield

TOLERANCE_USD = 0.01


def _curve_bars(data_dir: Path) -> dict[str, dict]:
    p = data_dir / "equity_curve_daily.json"
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {b["date"]: b for b in (doc.get("daily") or []) if isinstance(b, dict) and "date" in b}


def replay(data_dir: str | os.PathLike, tolerance_usd: float = TOLERANCE_USD) -> dict[str, Any]:
    ddir = Path(data_dir)
    chain = archive.verify(ddir)
    if chain["entries"] == 0:
        return {"status": "UNCHECKED", "reason": "no cycle_inputs.jsonl yet (archive starts with the first cycle after delivery)",
                "days": 0, "diffs": [], "max_abs_diff_usd": None, "chain": chain}
    if not chain["ok"]:
        return {"status": "UNCHECKED", "reason": f"archive chain broken at {chain['broken_at']}: {chain['reason']}",
                "days": 0, "diffs": [], "max_abs_diff_usd": None, "chain": chain}
    entries = [e for e in archive.read_all(ddir) if "payload" in e]
    last_per_date: dict[str, dict] = {}
    runs: dict[str, int] = {}
    for e in entries:
        d = e["payload"].get("cycle_date")
        if not d:
            continue
        last_per_date[d] = e["payload"]
        runs[d] = runs.get(d, 0) + 1
    bars = _curve_bars(ddir)
    diffs: list[dict] = []
    checked = 0
    for d in sorted(last_per_date):
        p = last_per_date[d]
        y = _accrue_daily_yield(p.get("positions") or {}, p.get("apy_map") or {})
        close = float(p["open_equity"]) + y
        row: dict[str, Any] = {"date": d, "runs": runs[d], "rederived_close": round(close, 4), "archived_close": p.get("close_equity")}
        problems = []
        if abs(close - float(p.get("close_equity", 0.0))) > tolerance_usd:
            problems.append("archive self-inconsistent")
        bar = bars.get(d)
        if bar is None:
            row["curve_close"] = None
            problems.append("no bar in equity_curve_daily.json")
        else:
            row["curve_close"] = bar.get("close_equity")
            if abs(close - float(bar.get("close_equity", 0.0))) > tolerance_usd:
                problems.append("curve differs")
        checked += 1
        if problems:
            row["problems"] = problems
            row["abs_diff_usd"] = round(max(abs(close - float(p.get("close_equity", 0.0))),
                                           abs(close - float(bar.get("close_equity", 0.0))) if bar else 0.0), 4)
            diffs.append(row)
    if checked == 0:
        return {"status": "UNCHECKED", "reason": "archive has no dated records", "days": 0, "diffs": [], "max_abs_diff_usd": None, "chain": chain}
    worst = max((r["abs_diff_usd"] for r in diffs), default=0.0)
    return {"status": "FAIL" if diffs else "PASS", "days": checked, "first": min(last_per_date), "last": max(last_per_date),
            "diffs": diffs, "max_abs_diff_usd": worst, "tolerance_usd": tolerance_usd, "chain": chain,
            "reruns": {d: n for d, n in runs.items() if n > 1}}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="re-derive equity bars from data/cycle_inputs.jsonl")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[2] / "data"))
    a = ap.parse_args(argv)
    rep = replay(a.data_dir)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return {"PASS": 0, "UNCHECKED": 1, "FAIL": 2}[rep["status"]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
