#!/usr/bin/env python3
"""Adaptive cycle-frequency scheduler (MP-1576 / Improvement 1).

The daily paper-trading cycle has historically run on a fixed launchd
schedule (08:00 UTC). That cadence is fine when the portfolio is calm, but
too slow when a position is sitting near a concentration cap or when the
portfolio is drawing down. This module derives an *advisory* cadence from
the current portfolio state so the cycle can tighten monitoring exactly when
it matters and relax it when nothing is happening.

Rules (in strict priority order — the first match wins)
=======================================================
1. **EMERGENCY (30 min)**  — drawdown > 2 %.
   The portfolio is bleeding; watch it every half hour.
2. **TIGHT (1 h)**          — any single position weight > 35 % cap.
   A position is near / over the per-protocol concentration cap and must be
   monitored hourly until it is rebalanced back under the cap.
3. **RELAXED (4 h)**        — low volatility AND no position near a limit.
   Calm market, nothing close to a cap → run only every 4 hours.
4. **NORMAL (24 h)**        — the default daily cadence (none of the above).

Design / safety
===============
* STRICTLY ADVISORY. This module changes **no** allocation, risk or
  execution state. It reads JSON snapshots and returns a recommendation. The
  caller decides whether (and how) to reschedule launchd. It NEVER touches
  capital.
* Stdlib only. All writes are atomic (``atomic_save``).
* Fail-safe: a missing / corrupt input file degrades to the NORMAL daily
  cadence rather than raising. ``decide()`` never raises on bad data.
* No LLM. Pure deterministic thresholds — safe for the monitoring domain
  (``LLM_FORBIDDEN_AGENTS`` includes ``monitoring``).

CLI
===
    python3 -m spa_core.paper_trading.adaptive_scheduler --check   # print, no write
    python3 -m spa_core.paper_trading.adaptive_scheduler --run     # + write JSON
    python3 -m spa_core.paper_trading.adaptive_scheduler --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger(__name__)

# ─── Tunable thresholds (deterministic) ─────────────────────────────────────

EMERGENCY_DRAWDOWN_PCT = 2.0   # drawdown beyond this (in %, positive magnitude)
TIGHT_POSITION_PCT = 35.0      # a single position weight beyond this → tight
LOW_VOLATILITY_PCT = 0.5       # daily volatility below this counts as "low"
NEAR_LIMIT_PCT = 30.0          # a position above this is "near a limit" (no relax)

# ─── Cadence modes (minutes) ────────────────────────────────────────────────

MODE_EMERGENCY = "emergency"
MODE_TIGHT = "tight"
MODE_RELAXED = "relaxed"
MODE_NORMAL = "normal"

INTERVAL_MINUTES: Dict[str, int] = {
    MODE_EMERGENCY: 30,
    MODE_TIGHT: 60,
    MODE_RELAXED: 240,
    MODE_NORMAL: 1440,
}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


# ─── Decision result ────────────────────────────────────────────────────────


@dataclass
class CadenceDecision:
    """Advisory cadence recommendation. ``interval_minutes`` is authoritative."""

    mode: str
    interval_minutes: int
    reason: str
    drawdown_pct: float = 0.0
    max_position_pct: float = 0.0
    volatility_pct: float = 0.0
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON, returning ``default`` on any error. Never raises."""
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("adaptive_scheduler: unreadable %s (%s)", path, exc)
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def max_position_weight_pct(positions: Dict[str, Any]) -> float:
    """Largest single position as a percentage of the portfolio.

    ``positions`` maps protocol → USD. Returns 0.0 for an empty / invalid map.
    """
    if not isinstance(positions, dict) or not positions:
        return 0.0
    vals = [_coerce_float(v) for v in positions.values()]
    vals = [v for v in vals if v > 0]
    total = sum(vals)
    if total <= 0:
        return 0.0
    return max(vals) / total * 100.0


def _abs_drawdown_pct(summary: Dict[str, Any], status: Dict[str, Any]) -> float:
    """Current drawdown magnitude in % (always >= 0).

    Prefers the live ``drawdown_pct`` on the latest equity bar; falls back to
    the equity summary ``max_drawdown_pct``. Stored as a negative number, so
    we return its magnitude.
    """
    # Latest daily bar drawdown (live, single-cycle) wins if present.
    daily = summary.get("daily") if isinstance(summary, dict) else None
    if isinstance(daily, list) and daily:
        last = daily[-1]
        if isinstance(last, dict) and "drawdown_pct" in last:
            return abs(_coerce_float(last.get("drawdown_pct")))
    roll = summary.get("summary") if isinstance(summary, dict) else None
    if isinstance(roll, dict) and "max_drawdown_pct" in roll:
        return abs(_coerce_float(roll.get("max_drawdown_pct")))
    # status fallback (some snapshots carry it flat)
    if isinstance(status, dict) and "drawdown_pct" in status:
        return abs(_coerce_float(status.get("drawdown_pct")))
    return 0.0


def _volatility_pct(summary: Dict[str, Any]) -> float:
    roll = summary.get("summary") if isinstance(summary, dict) else None
    if isinstance(roll, dict):
        return abs(_coerce_float(roll.get("daily_volatility_pct")))
    return 0.0


# ─── Core decision (pure) ───────────────────────────────────────────────────


def decide_cadence(
    *,
    drawdown_pct: float,
    max_position_pct: float,
    volatility_pct: float,
) -> CadenceDecision:
    """Pure rule engine — given three scalars return the cadence.

    Priority order is strict: emergency → tight → relaxed → normal.
    All inputs are coerced to safe floats; this function never raises.
    """
    dd = abs(_coerce_float(drawdown_pct))
    pos = _coerce_float(max_position_pct)
    vol = abs(_coerce_float(volatility_pct))

    if dd > EMERGENCY_DRAWDOWN_PCT:
        mode = MODE_EMERGENCY
        reason = (
            f"drawdown {dd:.2f}% > {EMERGENCY_DRAWDOWN_PCT:.1f}% "
            "→ emergency 30-min monitoring"
        )
    elif pos > TIGHT_POSITION_PCT:
        mode = MODE_TIGHT
        reason = (
            f"max position {pos:.2f}% > {TIGHT_POSITION_PCT:.1f}% cap "
            "→ tight hourly monitoring"
        )
    elif vol < LOW_VOLATILITY_PCT and pos < NEAR_LIMIT_PCT:
        mode = MODE_RELAXED
        reason = (
            f"low volatility {vol:.2f}% and max position {pos:.2f}% < "
            f"{NEAR_LIMIT_PCT:.1f}% → relaxed 4-hour cadence"
        )
    else:
        mode = MODE_NORMAL
        reason = "no trigger active → normal daily cadence"

    return CadenceDecision(
        mode=mode,
        interval_minutes=INTERVAL_MINUTES[mode],
        reason=reason,
        drawdown_pct=round(dd, 4),
        max_position_pct=round(pos, 4),
        volatility_pct=round(vol, 4),
        generated_at=_utc_now_iso(),
    )


# ─── State-driven decision (reads data/) ────────────────────────────────────


def decide_from_state(data_dir: Optional[Path] = None) -> CadenceDecision:
    """Read the live JSON snapshots and derive a cadence.

    Inputs (all optional / fail-safe):
      * ``equity_curve_daily.json`` → drawdown + volatility
      * ``paper_trading_status.json`` → current positions (for max weight)
    A completely missing data directory degrades to NORMAL.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    equity = _read_json(ddir / "equity_curve_daily.json", {})
    status = _read_json(ddir / "paper_trading_status.json", {})

    # No live data at all → don't infer a "calm" relaxed cadence from zeros;
    # degrade safely to the NORMAL daily cadence.
    if not equity and not status:
        return CadenceDecision(
            mode=MODE_NORMAL,
            interval_minutes=INTERVAL_MINUTES[MODE_NORMAL],
            reason="no live data snapshots → normal daily cadence",
            generated_at=_utc_now_iso(),
        )

    positions = {}
    if isinstance(status, dict):
        positions = status.get("current_positions") or {}
    # fall back to the positions embedded in the latest equity bar
    if not positions and isinstance(equity, dict):
        daily = equity.get("daily")
        if isinstance(daily, list) and daily and isinstance(daily[-1], dict):
            positions = daily[-1].get("positions") or {}

    return decide_cadence(
        drawdown_pct=_abs_drawdown_pct(equity, status if isinstance(status, dict) else {}),
        max_position_pct=max_position_weight_pct(positions),
        volatility_pct=_volatility_pct(equity),
    )


def run(data_dir: Optional[Path] = None, write: bool = True) -> CadenceDecision:
    """Decide and (optionally) persist to ``data/adaptive_schedule.json``."""
    decision = decide_from_state(data_dir)
    if write:
        ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        try:
            atomic_save(decision.to_dict(), str(ddir / "adaptive_schedule.json"))
        except OSError as exc:  # never crash the cycle on a write failure
            log.warning("adaptive_scheduler: write failed (%s)", exc)
    return decision


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adaptive_scheduler",
        description="Advisory adaptive cycle-frequency recommendation (read-only).",
    )
    parser.add_argument("--run", action="store_true", help="write adaptive_schedule.json")
    parser.add_argument("--check", action="store_true", help="compute + print only (default)")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    data_dir = Path(args.data_dir) if args.data_dir else None
    decision = run(data_dir=data_dir, write=bool(args.run))

    print(f"mode            : {decision.mode}")
    print(f"interval        : {decision.interval_minutes} min")
    print(f"drawdown        : {decision.drawdown_pct:.2f}%")
    print(f"max position    : {decision.max_position_pct:.2f}%")
    print(f"volatility      : {decision.volatility_pct:.2f}%")
    print(f"reason          : {decision.reason}")
    if args.run:
        print("(wrote adaptive_schedule.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
