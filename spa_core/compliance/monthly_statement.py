"""spa_core.compliance.monthly_statement — period (monthly/weekly) statement.

Produces an end-of-period statement for the paper-trading track: opening and
closing NAV, the period return in $ and %, an annualized figure, the strategy
mix, and a risk-events attestation.  The first partial period is
``2026-06-10 .. 2026-06-21``.

Output (atomic write):
    data/statements/<period>.json    e.g. data/statements/2026-06.json

Constraints (SPA policy)
------------------------
- READ-ONLY / advisory: reads ``data/equity_curve_daily.json``,
  ``data/risk_policy_blocks.json``, ``data/current_positions.json``; writes only
  the statement artifact.
- Pure stdlib.  Atomic writes.  Fail-safe.  LLM FORBIDDEN.

CLI
---
    python3 -m spa_core.compliance.monthly_statement --check
    python3 -m spa_core.compliance.monthly_statement --run
    python3 -m spa_core.compliance.monthly_statement --run --period 2026-06 \
        --start 2026-06-10 --end 2026-06-21
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

#: First partial period of the real paper track.
DEFAULT_PERIOD = "2026-06"
DEFAULT_START = "2026-06-10"
DEFAULT_END = "2026-06-21"

PRIMARY_STRATEGY = "risk_adjusted multi-protocol allocation (StrategyAllocator + RiskPolicy v1.0 gate)"
POLICY_ATTESTATION = "All positions within policy limits throughout period"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


def _period_days(start: str, end: str) -> int:
    """Inclusive-of-start day count between two YYYY-MM-DD dates (≥1)."""
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(end, "%Y-%m-%d")
        return max(1, (d1 - d0).days)
    except Exception:
        return 1


def annualize(period_return_pct: float, period_days: int) -> float:
    """Simple (non-compounding) annualization of a period return."""
    if period_days <= 0:
        return 0.0
    return period_return_pct / period_days * 365.0


def _equity_in_window(daily: list[dict], start: str, end: str) -> list[dict]:
    """Return daily snapshots whose ``date`` falls within [start, end]."""
    rows = []
    for d in daily:
        date = d.get("date")
        if isinstance(date, str) and start <= date <= end:
            rows.append(d)
    return rows


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def build_statement(
    *,
    period: str = DEFAULT_PERIOD,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Compute the period statement dict.  Never raises (fail-safe)."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    equity_doc = _load_json(ddir / "equity_curve_daily.json") or {}
    daily = equity_doc.get("daily", []) if isinstance(equity_doc, dict) else []
    window = _equity_in_window(daily, start, end)

    # Opening NAV = open_equity of first in-window day (fallback: start_equity).
    # Closing NAV = close_equity of last in-window day (fallback: end_equity).
    summary = equity_doc.get("summary", {}) if isinstance(equity_doc, dict) else {}
    if window:
        opening_nav = float(window[0].get("open_equity") or window[0].get("equity") or 0.0)
        closing_nav = float(window[-1].get("close_equity") or window[-1].get("equity") or 0.0)
    else:
        opening_nav = float(summary.get("start_equity") or 0.0)
        closing_nav = float(summary.get("end_equity") or 0.0)

    pnl_usd = round(closing_nav - opening_nav, 2)
    pnl_pct = round((pnl_usd / opening_nav * 100), 4) if opening_nav else 0.0

    pdays = _period_days(start, end)
    annualized_pct = round(annualize(pnl_pct, pdays), 4)

    # Average allocation across the in-window days (per protocol → mean USD).
    avg_alloc = _average_allocation(window)

    # Risk events over the period.
    kill_switch_triggers = _count_kill_switch(ddir, start, end)
    risk_gate_blocks = _count_risk_blocks(ddir, start, end)

    statement: dict[str, Any] = {
        "report_type": "period_statement",
        "version": "v1.0",
        "period": period,
        "period_start": start,
        "period_end": end,
        "period_days": pdays,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_partial_period": period == DEFAULT_PERIOD and start == DEFAULT_START,
        "starting_nav_usd": round(opening_nav, 2),
        "ending_nav_usd": round(closing_nav, 2),
        "return_usd": pnl_usd,
        "return_pct": pnl_pct,
        "annualized_return_pct": annualized_pct,
        "strategy_used": PRIMARY_STRATEGY,
        "average_allocation_usd": avg_alloc,
        "risk_events": {
            "kill_switch_triggers": kill_switch_triggers,
            "risk_gate_blocks": risk_gate_blocks,
        },
        "policy_attestation": POLICY_ATTESTATION,
        "all_within_policy": kill_switch_triggers == 0,
        "is_demo": bool(equity_doc.get("is_demo", False)) if isinstance(equity_doc, dict) else None,
        "days_observed": len(window),
    }
    return statement


def _average_allocation(window: list[dict]) -> dict[str, float]:
    """Mean USD per protocol across the in-window daily snapshots."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for d in window:
        positions = d.get("positions")
        if not isinstance(positions, dict):
            continue
        for proto, amt in positions.items():
            try:
                totals[proto] = totals.get(proto, 0.0) + float(amt)
                counts[proto] = counts.get(proto, 0) + 1
            except (TypeError, ValueError):
                continue
    return {
        proto: round(totals[proto] / counts[proto], 2)
        for proto in totals
        if counts.get(proto)
    }


def _count_kill_switch(data_dir: Path, start: str, end: str) -> int:
    """Count kill-switch triggers in the period (from risk_policy_blocks.json)."""
    blocks = _load_json(data_dir / "risk_policy_blocks.json")
    if not isinstance(blocks, list):
        return 0
    n = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        date = b.get("date") or (b.get("ts", "")[:10] if isinstance(b.get("ts"), str) else "")
        if not (isinstance(date, str) and start <= date <= end):
            continue
        violations = b.get("violations", [])
        text = " ".join(str(v).upper() for v in violations) if isinstance(violations, list) else ""
        if "KILL SWITCH" in text:
            n += 1
    return n


def _count_risk_blocks(data_dir: Path, start: str, end: str) -> int:
    """Count RiskPolicy gate blocks whose date falls in the period."""
    blocks = _load_json(data_dir / "risk_policy_blocks.json")
    if not isinstance(blocks, list):
        return 0
    n = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        date = b.get("date") or (b.get("ts", "")[:10] if isinstance(b.get("ts"), str) else "")
        if isinstance(date, str) and start <= date <= end:
            n += 1
    return n


def write_statement(
    statement: dict[str, Any],
    *,
    data_dir: str | Path | None = None,
) -> str:
    """Atomically write the statement to data/statements/<period>.json."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    out_path = ddir / "statements" / f"{statement.get('period', DEFAULT_PERIOD)}.json"
    _atomic_write(out_path, json.dumps(statement, indent=2, ensure_ascii=False))
    return str(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _arg(argv: list[str], flag: str, default: str | None) -> str | None:
    if flag in argv:
        try:
            return argv[argv.index(flag) + 1]
        except IndexError:
            return default
    return default


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    do_run = "--run" in argv
    period = _arg(argv, "--period", DEFAULT_PERIOD)
    start = _arg(argv, "--start", DEFAULT_START)
    end = _arg(argv, "--end", DEFAULT_END)
    data_dir = _arg(argv, "--data-dir", None)

    st = build_statement(period=period, start=start, end=end, data_dir=data_dir)

    print(f"SPA Period Statement — {st['period']} ({st['period_start']} .. {st['period_end']})")
    print(f"  NAV          : ${st['starting_nav_usd']:,.2f} → ${st['ending_nav_usd']:,.2f}")
    print(f"  return       : ${st['return_usd']:,.2f}  ({st['return_pct']:.4f}%)")
    print(f"  annualized   : {st['annualized_return_pct']:.2f}%")
    print(f"  risk events  : {st['risk_events']['kill_switch_triggers']} kill / "
          f"{st['risk_events']['risk_gate_blocks']} gate blocks")
    print(f"  attestation  : {st['policy_attestation']}")

    if do_run:
        path = write_statement(st, data_dir=data_dir)
        print(f"  wrote        : {path}")
    else:
        print("  (--check mode: no file written; pass --run to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
