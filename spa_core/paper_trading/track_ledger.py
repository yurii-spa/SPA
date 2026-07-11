"""Q2-18 — dated evidenced-track LEDGER (deterministic, advisory).

The single binding go-live blocker is the 30-day EVIDENCED paper track. Today it is stated as a COUNT
("19/30 evidenced days"). This module hardens that count into a reproducible, day-by-day ARTIFACT a
diligence reviewer can independently verify: every evidenced day with its close equity, daily return,
cumulative return, and drawdown-from-running-peak. The 30-day claim becomes a checkable ledger, not an
assertion — a moat artifact for the first allocator.

Reuses the SINGLE evidenced-segregation point (track_evidence.evidenced_bars) so warmup / backfill /
reconstructed bars can NEVER contaminate the ledger. Deterministic, stdlib-only, fail-CLOSED (a missing
/ malformed equity file → an empty ledger with the reason, never a fabricated day). Writes
data/track_ledger.json atomically. Advisory — reads the committed track read-only, moves no capital.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.paper_trading import track_evidence as ev

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_EQUITY = _DATA / "equity_curve_daily.json"
_OUT = _DATA / "track_ledger.json"

DAYS_NEEDED = 30


def _load_daily(path: Path) -> list:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if isinstance(d, dict):
        daily = d.get("daily") or d.get("bars") or []
        return daily if isinstance(daily, list) else []
    return d if isinstance(d, list) else []


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_ledger(*, equity_path: Optional[Path] = None, write: bool = True,
                 now_iso: Optional[str] = None) -> dict:
    daily = _load_daily(equity_path or _EQUITY)
    bars = ev.evidenced_bars(daily)   # the ONE real-series segregation point (warmup/backfill excluded)

    rows: list[dict] = []
    peak = float("-inf")
    start_close: Optional[float] = None
    for bar in bars:
        date = bar.get("date")
        close = _f(bar.get("close_equity"))
        if not date or close <= 0:
            continue
        if start_close is None:
            start_close = close
        peak = max(peak, close)
        dd_from_peak = (close / peak - 1.0) * 100.0 if peak > 0 else 0.0
        cum = (close / start_close - 1.0) * 100.0 if start_close else 0.0
        rows.append({
            "date": date,
            "close_equity_usd": round(close, 2),
            "daily_return_pct": round(_f(bar.get("daily_return_pct")), 4),
            "cumulative_return_pct": round(cum, 4),
            "drawdown_from_peak_pct": round(dd_from_peak, 4),
        })

    n = len(rows)
    max_dd = min((r["drawdown_from_peak_pct"] for r in rows), default=0.0)
    report = {
        "model": "evidenced_track_ledger",
        "generated_at": now_iso,
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "evidence_note": ("EVIDENCED-ONLY: rows filtered through track_evidence.evidenced_bars — "
                          "warmup / backfill / reconstructed / pre-anchor bars are excluded, never counted."),
        "paper_real_start": str(ev.PAPER_REAL_START),
        "n_evidenced_days": n,
        "days_needed": DAYS_NEEDED,
        "days_remaining": max(0, DAYS_NEEDED - n),
        "first_evidenced_date": rows[0]["date"] if rows else None,
        "last_evidenced_date": rows[-1]["date"] if rows else None,
        "cumulative_return_pct": rows[-1]["cumulative_return_pct"] if rows else 0.0,
        "max_drawdown_from_peak_pct": round(max_dd, 4),
        "ledger": rows,
        "note": ("Day-by-day reproducible evidenced-track ledger: each evidenced day's close equity, "
                 "daily + cumulative return, and drawdown from the running peak. Turns the '30-day "
                 "evidenced track' go-live claim from a count into an independently-checkable artifact. "
                 "Advisory / read-only — reproduces the committed track, moves no capital."),
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


def main() -> int:
    rep = build_ledger(write=True)
    print(f"evidenced-track ledger: {rep['n_evidenced_days']}/{rep['days_needed']} days "
          f"({rep['first_evidenced_date']} → {rep['last_evidenced_date']}), "
          f"cum {rep['cumulative_return_pct']}%, maxDD {rep['max_drawdown_from_peak_pct']}%")
    print(f"  {rep['days_remaining']} evidenced days remaining → wrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
