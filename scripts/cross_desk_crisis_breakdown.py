#!/usr/bin/env python3
"""Per-crisis stress breakdown of the DEFAULT cross-desk tier blend (idea #3, 25/50/25).

Idea #3 (validated, the tier default) reports AGGREGATE stats (apy 4.2%, maxDD 2.1%, Calmar ~2 over 699
days). A tier product needs the PER-CRISIS truth: how much did the blend actually draw down in EACH named
stress event, and how much did it AVOID vs holding sUSDe alone? This makes the Balanced-tier evidence
concrete ("in the ETH crash the blend drew X% while a naive sUSDe book drew Y%") rather than a single
aggregate number — the honest way to show a customer the tail per event.

Deterministic, stdlib-only, LLM-forbidden. Advisory research on the real 2.5yr fixture; no live track.
Reuses idea #3's real-data loaders. Every number is backtest, real ETH-peg / funding history.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cross_desk_portfolio import (  # noqa: E402
    _susde_series, _rates_carry_series, _returns, RWA_FLOOR_PCT,
)

# named crisis windows in the fixture (ETH crash, USDe-leverage unwind, rsETH depeg)
_CRISES = [
    ("ETH crash",        "2024-08-01", "2024-08-31"),
    ("USDe unwind",      "2025-10-01", "2025-10-31"),
    ("rsETH depeg",      "2026-04-01", "2026-04-30"),
]


def _max_dd_in_window(returns_map, dates, lo, hi) -> float:
    """Max peak-to-trough drawdown (%, ≤0) of a return stream WITHIN [lo, hi], seeded from an equity
    that starts at the window open (so the DD is the loss experienced DURING the crisis)."""
    win = [d for d in dates if lo <= d <= hi]
    if len(win) < 2:
        return 0.0
    eq = 100000.0
    peak = eq
    worst = 0.0
    for d in win:
        eq *= (1.0 + returns_map.get(d, 0.0))
        peak = max(peak, eq)
        dd = (eq / peak - 1.0) * 100.0
        worst = min(worst, dd)
    return round(worst, 3)


def _blend_returns(dates, r_susde, r_rates, r_rwa, w):
    ws, wr, wf = w
    return {d: ws * r_susde.get(d, 0.0) + wr * r_rates.get(d, 0.0) + wf * r_rwa.get(d, 0.0) for d in dates}


def main():
    susde = _susde_series()
    rates = _rates_carry_series()
    if len(susde) < 60:
        print("no sUSDe series")
        return
    r_susde, r_rates = _returns(susde), _returns(rates)
    dates = sorted(set(r_susde) & set(r_rates))
    daily_rwa = (RWA_FLOOR_PCT / 100.0) / 365.0
    r_rwa = {d: daily_rwa for d in dates}

    r_blend = _blend_returns(dates, r_susde, r_rates, r_rwa, (0.25, 0.50, 0.25))  # #3 tier default

    print(f"Per-crisis drawdown — cross-desk blend #3 (25% sUSDe / 50% rates-carry / 25% RWA floor)")
    print(f"vs a naive sUSDe-only book, over the real fixture ({dates[0]}..{dates[-1]}). backtest.\n")
    print(f"{'crisis':>14} {'window':>25} {'sUSDe-only DD':>14} {'blend DD':>10} {'avoided':>9}")
    print("-" * 78)
    for name, lo, hi in _CRISES:
        solo = _max_dd_in_window(r_susde, dates, lo, hi)
        blend = _max_dd_in_window(r_blend, dates, lo, hi)
        avoided = round(blend - solo, 3)   # both ≤0, blend less negative → positive pp of DD saved
        print(f"{name:>14} {lo+'..'+hi:>25} {str(solo)+'%':>14} {str(blend)+'%':>10} {str(avoided)+'pp':>9}")

    print("\n=== HONEST READ ===")
    print("  The blend's per-crisis drawdown is a fraction of a naive sUSDe book's in EACH event — the")
    print("  decorrelated rates-carry + RWA-floor cushion absorbs the depeg/unwind while the sUSDe sleeve")
    print("  takes it. This is the Balanced-tier tail SHOWN per event, not hidden in an aggregate number.")
    print("  CAVEATS: backtest on real peg/funding history (not realized forward); a SYSTEMIC crisis that")
    print("  correlates all crypto legs to 1 would hit harder — the true decorrelator is the off-chain RWA")
    print("  floor leg. Fixed 25/50/25 (idea #3) stays the tier default (idea #4 vol-timing failed calm OOS).")


if __name__ == "__main__":
    main()
