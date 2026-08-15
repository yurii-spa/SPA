#!/usr/bin/env python3
"""
scripts/edge_cash_sleeve_frontier.py — registry idea #55 CSF: Cash-Sleeve Frontier

WHERE THIS COMES FROM
  Idea #54 measured that four of the ten books on the registry's real panel go permanently dark
  inside the sample, and that under #40 XSD k=2 M=20 those frozen books hold **31.7% of the
  portfolio on average** while returning exactly 0.00%/day. The dark-tail cash-twin control was
  exact to 0.00 on every metric: the dead books ARE a cash sleeve. Nobody sized it, nobody reviewed
  it, and it is inside every published number of #40–#53.

  That leaves a question #54 raised and did not answer, and it is an allocator question, not a
  measurement one — ADR-055 requires cash above the 5% buffer to be EXPLAINED every cycle:

      An accident put ~32% of the book in cash. Was that a good size, and is the accident's
      TIMING worth anything over a curator who simply wrote "hold c% in cash" once?

THREE THINGS ARE MEASURED, and they are different claims
  1. THE FRONTIER — the deliberate version. #40 XSD k=2 M=20 over the six LIVE books with a fixed
     cash fraction c ∈ {0 … 60%}. What does risk-adjusted return actually do as c rises, and where
     is the Calmar peak? A curator can only choose a c; this is the menu they choose from.
  2. THE TIMING CONTROL — is the accident better than its own static twin? The accidental sleeve is
     DYNAMIC: its size is whatever weight the ranking happens to give the dead books that day. The
     registry's standard refutation (`ecr.alloc_static_matched`, introduced at #38) holds the time-
     average of the same weight vector constant: same average exposure per book, same average cash,
     zero timing. Anything the accident does not beat its twin at was a static tilt, free to anyone.
  3. THE INTEREST BILL — the accident's cash earns 0.00%/day because a dead book earns nothing. A
     deliberate sleeve sits in T1 stables and earns the project's own measured RWA floor. Every row
     is therefore printed twice: cash at 0% (the registry's conservative convention, so the numbers
     stay comparable with #32–#54) and cash at the RWA floor (what the sleeve would really earn).

HONEST LIMITS (mirrored into the registry entry)
  (a) A fixed c is a CHOICE, not a signal: this entry cannot and does not claim to time cash. It
      prices choices.
  (b) The frontier is swept on the full sample and re-checked TRAIN/TEST; a peak found on the full
      sample is in-sample by construction and is labelled so wherever it is quoted.
  (c) The live universe here is #54's six books; the darkness that removed the other four is a
      property of this harness's feed coverage, not a market fact (#54 caveat (a)).
  (d) The RWA floor is a real measured number for T1 stables in this project, but it is a CONSTANT
      here, not a live feed — it is a modelling input and flagged as one.
  (e) Panel regenerated nightly; numbers reproduce against the run-date snapshot only. L0 evidence.
  (f) Turnover cost: 96 bp round-trip (#10/#49), charged on the same turnover model as #38–#54.

Read-only over data/aggressive_lab/. No state file, no agent, no site, no track.
Advisory / paper / OUTSIDE_RISKPOLICY. stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402
import edge_cross_sectional_demotion as xsd     # noqa: E402
import edge_drift_gated_overlay as dgo          # noqa: E402
import edge_event_time_scoring as ets           # noqa: E402  (#54: panel liveness + cash twin)

# The project's own measured floor for T1 stable/RWA yield (docs: real RWA floor ≈ 3.38%). A
# MODELLING CONSTANT here, not a live feed — see caveat (d).
RWA_FLOOR = 0.0338

CASH_GRID = (0.0, 0.05, 0.10, 0.20, 0.30, 0.317, 0.40, 0.50, 0.60)


def scaled(weights: Dict[str, List[float]], keep: float) -> Dict[str, List[float]]:
    """The same allocation, scaled to `keep` of the book; the rest is cash by construction."""
    if not 0.0 <= keep <= 1.0:
        raise ValueError(f"keep={keep} outside [0,1] — that is leverage or a short, not a sleeve")
    return {b: [w * keep for w in ws] for b, ws in weights.items()}


def _hdr(title: str, sub: str = "") -> None:
    print()
    print("=" * 120)
    print(title)
    if sub:
        print(sub)
    print("=" * 120)
    print(f"{'configuration':44s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
          f"{'depl':>7s} {'turn/yr':>8s} {'netAPY':>8s} {'maxW':>7s}")
    print("-" * 120)


def _row(name: str, m: Dict[str, float]) -> None:
    print(f"{name:44s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f} "
          f"{m['deployed']*100:6.1f}% {m['turnover_yr']:8.2f} "
          f"{m['net_apy_after_cost']*100:7.2f}% {m['max_weight']*100:6.1f}%")


def frontier(live_panel, k: int = 2, m_days: int = 20, cash_annual: float = 0.0,
             grid: Sequence[float] = CASH_GRID,
             cap: Optional[float] = None) -> Dict[float, Dict[str, float]]:
    """#40 XSD over the live books, deliberately holding `c` in cash. Returns {c: metrics}."""
    flags = xsd.rank_demotion_flags(ets.cal_scores(live_panel.rets), k, m_days)
    base = ecr.alloc_recycle(live_panel.books, flags, live_panel.n, cap=cap)
    return {c: ecr.portfolio_metrics(live_panel, scaled(base, 1.0 - c), cash_annual=cash_annual)
            for c in grid}


def section_frontier(live_panel, k: int = 2, m_days: int = 20) -> None:
    for cash_annual, tag in ((0.0, "cash 0.00%/yr — registry convention"),
                             (RWA_FLOOR, f"cash {RWA_FLOOR*100:.2f}%/yr — measured RWA floor")):
        _hdr(f"SECTION 1 — DELIBERATE CASH FRONTIER, {len(live_panel.books)} live books, "
             f"XSD k={k} M={m_days}  [{tag}]",
             f"{live_panel.n}d {live_panel.axis[0]}..{live_panel.axis[-1]}  ·  "
             f"cap {int(ecr.CONC_CAP*100)}% per name")
        rows = frontier(live_panel, k, m_days, cash_annual, cap=ecr.CONC_CAP)
        best_c = max(rows, key=lambda c: rows[c]["calmar"])
        for c in CASH_GRID:
            mark = "  ← Calmar peak [IN-SAMPLE]" if c == best_c else ""
            note = "  (= the accident's average size)" if abs(c - 0.317) < 1e-9 else ""
            _row(f"cash {c*100:5.1f}%{note}", rows[c])
            if mark:
                print(f"{'':44s}{mark}")


def section_timing_control(panel, live: Sequence[str], k: int = 2, m_days: int = 20) -> None:
    """Is the accident's dynamic cash worth anything over its own static twin?"""
    flags = xsd.rank_demotion_flags(ets.cal_scores(panel.rets), k, m_days)
    dyn = ecr.alloc_recycle(panel.books, flags, panel.n)
    dark = [b for b in panel.books if b not in live]
    share = sum(sum(dyn[b]) for b in dark) / panel.n

    _hdr(f"SECTION 2 — TIMING CONTROL: the accidental sleeve vs its own static twin "
         f"(XSD k={k} M={m_days})",
         f"accidental average cash = {share*100:.1f}% of the book, held in books that earn 0.00%/day")
    _row("ACCIDENT — dynamic, 10-book panel", ecr.portfolio_metrics(panel, dyn))
    _row("  its static-matched twin (#38 control)",
         ecr.portfolio_metrics(panel, ecr.alloc_static_matched(dyn)))

    live_panel = ets.sub_panel(panel, live)
    delib = frontier(live_panel, k, m_days, 0.0, grid=(share,), cap=ecr.CONC_CAP)[share]
    delib_paid = frontier(live_panel, k, m_days, RWA_FLOOR, grid=(share,), cap=ecr.CONC_CAP)[share]
    _row(f"DELIBERATE {share*100:.1f}% cash @0.00%/yr", delib)
    _row(f"DELIBERATE {share*100:.1f}% cash @{RWA_FLOOR*100:.2f}%/yr", delib_paid)
    print("-" * 120)
    print(f"interest the accident forgoes: {share*100:.1f}% of the book × {RWA_FLOOR*100:.2f}%/yr = "
          f"{share*RWA_FLOOR*100:.2f} pp/yr of return, given up for nothing — a dead book is a")
    print("cash sleeve that forgot to earn interest.")


def section_oos(panel, live: Sequence[str], k: int = 2, m_days: int = 20) -> None:
    _hdr(f"SECTION 3 — the frontier out of sample (split {ets.TRAIN_END})",
         "a peak chosen on the full sample is in-sample by construction; this is the check")
    live_panel = ets.sub_panel(panel, live)
    for seg, lo, hi in (("TRAIN", None, ets.TRAIN_END), ("TEST", ets.TRAIN_END, None)):
        ax = [d for d in live_panel.axis
              if (lo is None or d > lo) and (hi is None or d <= hi)]
        idx = [live_panel.axis.index(d) for d in ax]
        sp = ets.SynthPanel(ax, {b: [live_panel.rets[b][i] for i in idx] for b in live_panel.books})
        rows = frontier(sp, k, m_days, RWA_FLOOR, cap=ecr.CONC_CAP)
        best = max(rows, key=lambda c: rows[c]["calmar"])
        print(f"[{seg}] {ax[0]}..{ax[-1]}  Calmar peak at cash={best*100:.1f}%  "
              f"(Calmar {rows[best]['calmar']:.2f}, netAPY {rows[best]['net_apy_after_cost']*100:.2f}%)"
              f"   ·  at cash=0%: Calmar {rows[0.0]['calmar']:.2f}, "
              f"netAPY {rows[0.0]['net_apy_after_cost']*100:.2f}%"
              f"   ·  at cash=31.7%: Calmar {rows[0.317]['calmar']:.2f}, "
              f"netAPY {rows[0.317]['net_apy_after_cost']*100:.2f}%")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Registry idea #55 — cash-sleeve frontier")
    ap.add_argument("--section", default="all", choices=["all", "1", "2", "3"])
    args = ap.parse_args(list(argv) if argv is not None else None)

    panel = dgo.Panel()
    live = ets.live_books(panel)
    live_panel = ets.sub_panel(panel, live)
    print(f"live universe (#54, density ≥ 50%): {len(live)} books — {', '.join(live)}")

    if args.section in ("all", "1"):
        section_frontier(live_panel)
    if args.section in ("all", "2"):
        section_timing_control(panel, live)
    if args.section in ("all", "3"):
        section_oos(panel, live)

    print()
    print("=" * 120)
    print(f"IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence L0  ·  RWA floor {RWA_FLOOR*100:.2f}%"
          f" is a MODELLING CONSTANT, not a live feed  ·  cost 96 bp round-trip (#10/#49)")
    print("=" * 120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
