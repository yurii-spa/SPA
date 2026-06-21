#!/usr/bin/env python3
"""
scripts/backtest_s44.py — S44 Yield Spike Harvester backtest
============================================================

Runs S44 over the REAL 365-day historical APY data in data/historical_apy/
(aave_v3, compound_v3, yearn_v3, sky_susds) and compares it against:

  * STATIC-DIVERSIFIED control — S44's own SPIKE_INACTIVE book (40/30/20/10)
    held every single day with NO spike awareness. This is the cleanest control:
    it isolates exactly what the spike-rotation logic adds, on identical data.

  * S7 (Pendle YT+PT Aggressive) — run via its native simulate_day harness on
    the seeded Pendle-YT universe (the universe S7 was designed for). Reported as
    a cross-reference; S7 trades a different universe than the real lending data,
    so it is not a same-data comparison (and is labelled as such).

The headline question — "does S44 beat a static aggressive book during spikes
and roughly match it during calm?" — is answered by the per-window breakdown:
S44 vs the static-diversified control, segmented into spike windows vs calm days.

Pure stdlib, offline, atomic write, exit 0 on success.

Usage:
    python3 scripts/backtest_s44.py [--out data/backtest_s44_results.json] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategies.s44_spike_harvester import (
    S44SpikeHarvester,
    NORMAL_WEIGHTS,
    REGIME_SPIKE,
)

DATA_DIR = _REPO_ROOT / "data" / "historical_apy"
INITIAL_CAPITAL = 100_000.0

# Real historical files → protocol keys S44 understands.
FILES = {
    "aave_v3":     "aave_v3_usdc.json",
    "compound_v3": "compound_v3_usdc.json",
    "yearn_v3":    "yearn_v3_usdc.json",
    "sky_susds":   "sky_susds.json",
}


def load_series() -> tuple[dict[str, list[float]], list[str]]:
    """Load per-protocol APY series aligned on the common date axis.

    The historical files do not share an identical axis — compound_v3 starts two
    days earlier than the rest — so alignment is by *date*, not by row index.
    Returns ``({protocol: [apy, ...]}, [date, ...])`` over the date intersection.
    """
    by_date: dict[str, dict[str, float]] = {}
    date_sets: list[set[str]] = []
    for proto, fname in FILES.items():
        rows = json.loads((DATA_DIR / fname).read_text())
        by_date[proto] = {r["date"]: float(r["apy"]) for r in rows}
        date_sets.append(set(by_date[proto].keys()))

    common = sorted(set.intersection(*date_sets))
    series = {proto: [by_date[proto][d] for d in common] for proto in FILES}
    return series, common


def static_diversified_backtest(series: dict[str, list[float]]) -> dict:
    """Hold S44's SPIKE_INACTIVE book (40/30/20/10) every day — the control."""
    n = min(len(v) for v in series.values())
    capital = INITIAL_CAPITAL
    curve = [capital]
    for t in range(1, n):
        day_interest = 0.0
        for proto, w in NORMAL_WEIGHTS.items():
            apy_today = series[proto][t]
            day_interest += capital * w * (apy_today / 100.0) / 365.0
        capital += day_interest
        curve.append(capital)
    days = n - 1
    ann = ((curve[-1] / curve[0]) ** (365.0 / days) - 1.0) * 100.0
    return {
        "label": "Static-Diversified control (40/30/20/10, no spike logic)",
        "final_capital_usd": round(curve[-1], 2),
        "total_interest_usd": round(curve[-1] - curve[0], 2),
        "total_return_pct": round((curve[-1] - curve[0]) / curve[0] * 100.0, 4),
        "annualised_return_pct": round(ann, 4),
        "equity_curve": [round(v, 4) for v in curve],
    }


def run_s7_reference() -> dict:
    """Run real S7 via its native harness on the seeded Pendle-YT universe."""
    try:
        from scripts.run_backtest import generate_yt_history, run_s7
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        yt = generate_yt_history(days=365, seed=42)
        base = run_s7(S7PendleYTAggressive(), yt, INITIAL_CAPITAL, scenario="base")
        return {
            "label": "S7 Pendle YT+PT Aggressive (native harness, Pendle-YT universe)",
            "universe": "pendle_yt (NOT the real lending data — cross-reference only)",
            "annualised_return_pct": base.get("annualised_return_pct", 0.0),
            "total_return_pct": base.get("total_return_pct", 0.0),
            "final_capital_usd": base.get("final_capital_usd", 0.0),
            "sharpe_ratio": base.get("sharpe_ratio", 0.0),
            "max_drawdown_pct": base.get("max_drawdown_pct", 0.0),
        }
    except Exception as exc:  # pragma: no cover
        return {"label": "S7 reference", "error": repr(exc)}


def spike_window_breakdown(
    s44_curve: list[float],
    ctrl_curve: list[float],
    regimes: list[str],
    dates: list[str],
) -> dict:
    """Segment day-by-day P&L into spike days vs calm days for S44 vs control.

    regimes[i] corresponds to the transition into curve index i+1.
    """
    spike_s44 = spike_ctrl = calm_s44 = calm_ctrl = 0.0
    spike_dates: list[str] = []
    for i, regime in enumerate(regimes):
        s44_d = s44_curve[i + 1] - s44_curve[i]
        ctrl_d = ctrl_curve[i + 1] - ctrl_curve[i]
        if regime == REGIME_SPIKE:
            spike_s44 += s44_d
            spike_ctrl += ctrl_d
            if i + 1 < len(dates):
                spike_dates.append(dates[i + 1])
        else:
            calm_s44 += s44_d
            calm_ctrl += ctrl_d
    return {
        "spike_days": len(spike_dates),
        "spike_dates": spike_dates,
        "spike_interest_s44_usd": round(spike_s44, 2),
        "spike_interest_control_usd": round(spike_ctrl, 2),
        "spike_edge_usd": round(spike_s44 - spike_ctrl, 2),
        "calm_interest_s44_usd": round(calm_s44, 2),
        "calm_interest_control_usd": round(calm_ctrl, 2),
        "calm_edge_usd": round(calm_s44 - calm_ctrl, 2),
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description="S44 Yield Spike Harvester backtest")
    ap.add_argument("--out", default=str(_REPO_ROOT / "data" / "backtest_s44_results.json"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    series, dates = load_series()

    s44 = S44SpikeHarvester(capital=INITIAL_CAPITAL)
    s44_res = s44.backtest(series, initial_capital=INITIAL_CAPITAL)
    control = static_diversified_backtest(series)
    s7_ref = run_s7_reference()
    windows = spike_window_breakdown(
        s44_res["equity_curve"], control["equity_curve"], s44_res["regimes"], dates,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "data/historical_apy/ (REAL, 365 days)",
        "initial_capital_usd": INITIAL_CAPITAL,
        "protocols": list(FILES.keys()),
        "note": (
            "S44 vs Static-Diversified control is the same-data, apples-to-apples "
            "comparison. S7 is a cross-reference on the Pendle-YT universe it was "
            "designed for (different data, labelled as such)."
        ),
        "s44": {k: v for k, v in s44_res.items() if k not in ("equity_curve", "regimes")},
        "control_static_diversified": {
            k: v for k, v in control.items() if k != "equity_curve"
        },
        "s7_reference": s7_ref,
        "spike_window_breakdown": windows,
    }
    atomic_write_json(Path(args.out), payload)

    # ── console summary ───────────────────────────────────────────────────────
    print("\nS44 Yield Spike Harvester — backtest on REAL 365-day historical data")
    print("=" * 72)
    s = s44_res
    print(f"S44 (spike-aware):        final ${s['final_capital_usd']:>12,.2f}  "
          f"annRet {s['annualised_return_pct']:>6.2f}%  maxDD {s['max_drawdown_pct']:.2f}%")
    print(f"  spike days: {s['spike_days']:>3}   spike interest ${s['spike_interest_usd']:,.2f}   "
          f"normal interest ${s['normal_interest_usd']:,.2f}")
    c = control
    print(f"Static-Diversified ctrl:  final ${c['final_capital_usd']:>12,.2f}  "
          f"annRet {c['annualised_return_pct']:>6.2f}%")
    edge = s["final_capital_usd"] - c["final_capital_usd"]
    print(f"  → S44 edge over control:  ${edge:,.2f}  "
          f"({s['annualised_return_pct'] - c['annualised_return_pct']:+.2f}pp annualised)")
    print("\nSpike-window breakdown (S44 vs control):")
    w = windows
    print(f"  spike days={w['spike_days']}  "
          f"S44 ${w['spike_interest_s44_usd']:,.2f} vs ctrl ${w['spike_interest_control_usd']:,.2f}  "
          f"edge ${w['spike_edge_usd']:,.2f}")
    print(f"  calm days   "
          f"S44 ${w['calm_interest_s44_usd']:,.2f} vs ctrl ${w['calm_interest_control_usd']:,.2f}  "
          f"edge ${w['calm_edge_usd']:,.2f}")
    if w["spike_dates"]:
        print(f"  spike dates: {w['spike_dates']}")
    print(f"\nS7 reference ({s7_ref.get('universe', 'n/a')}):")
    if "error" in s7_ref:
        print(f"  ERROR: {s7_ref['error']}")
    else:
        print(f"  annRet {s7_ref['annualised_return_pct']:.2f}%  "
              f"final ${s7_ref['final_capital_usd']:,.2f}")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
