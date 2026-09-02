#!/usr/bin/env python3
"""Registry numbers of the vol guardian, recomputed WITHOUT its one-day look-ahead.

**Owner decision 2026-09-02, вариант 1** (card `owner-decision-storozh-prosadki-reshaet-uzhe-znaya-itog`):
do NOT touch the deployed guardian — recompute the numbers it is credited with and publish an
honest pair next to each. This script is that recomputation.

**The defect.** `spa_core.strategy_lab.aggressive_lab.guardian.apply_guardian_vol` sets the exposure
for day *i* from a volatility window that **includes rets[i]**, then multiplies **rets[i]** by that
exposure. A close-to-close return is not known before the close, so in every number the overlay is
credited with, it decided while already knowing the outcome of the day it was deciding about. The
LIVE posture is causal by construction — today it cannot know tomorrow's return, and tomorrow it
applies today's decision — so the defect is in the published numbers, not in the deployed agent.

**No third copy of the rule.** The causal variant is NOT re-implemented here: it is
`edge_overlay_domain_admissibility.guarded_path(..., causal_lag=1)`, the mirror that already
carries the lag switch, is bit-identical to the shipped organ at `causal_lag=0`
(`test_gated_engine_reproduces_the_deployed_organ`) and whose one-day-lag identity is confirmed
against the LIVE module's own exposure trace (`test_causal_variant_equals_the_organs_own_trace_lagged_one_day`).
Reusing it means this table and the instrument check in that script cannot drift apart; adding a
third implementation would have meant two numbers with no way to tell which was the guardian.

Two comparisons are printed, because they answer two different questions:

  * **CAUSAL@same** — the published cell's own winning parameters, applied causally. Answers
    "what is the published number actually worth?". This is the owner's measurement.
  * **CAUSAL@best** — the best causal config over the same grid. Answers "what can a guardian that
    does not peek achieve at all?". Fairer to the overlay, and the ceiling under which any forward
    claim must live — its parameters are still chosen in-sample.

Deterministic, stdlib-only, LLM-forbidden, network-free. Advisory research: reads the aggressive-lab
panel read-only and touches no live track.

    python3 scripts/guardian_causality_recheck.py                    # documented fixture roster
    python3 scripts/guardian_causality_recheck.py --real             # repo's data/aggressive_lab
    python3 scripts/guardian_causality_recheck.py --real /prod/data/aggressive_lab
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402

from spa_core.strategy_lab import metrics  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures as fx  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import guardian as g  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld  # noqa: E402

__all__ = ["causal_overlay", "VOL_GRID", "recheck_book"]

#: The published sweep grid (`scripts/guardian_backtest.py`), reused verbatim so the "было" column
#: here and the published table are the same measurement, not a lookalike.
VOL_GRID = [(vm, fr) for vm in (1.5, 2.0, 3.0) for fr in (0.0, 0.25, 0.5)]

#: Tolls are OFF in this table on purpose. The published cells were computed without a toll, and
#: the question here is what the look-ahead alone is worth — charging churn at the same time would
#: mix two corrections into one number and neither would be attributable.
NO_TOLL = 0.0


def causal_overlay(equity: Sequence[float], *, vol_mult: float = 2.0,
                   derisk_frac: float = 0.0, lookback: int = 10,
                   calm_mult: float = 1.2, min_vol: float = 1e-5) -> List[float]:
    """The shipped overlay with its vol window ending YESTERDAY — the existing mirror, at lag 1."""
    return oda.guarded_path(
        equity, None, lookback=lookback, vol_mult=vol_mult, derisk_frac=derisk_frac,
        calm_mult=calm_mult, roundtrip_cost=NO_TOLL, min_vol=min_vol, causal_lag=1,
    )


def deployed_overlay(equity: Sequence[float], **kw) -> List[float]:
    """The shipped overlay itself — imported, not copied."""
    return g.apply_guardian_vol(equity, roundtrip_cost=NO_TOLL, **kw)


def _equity_of(series) -> List[float]:
    out: List[float] = []
    for p in series:
        v = p.get("equity_usd", p.get("equity"))
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


def _metrics(equity):
    apy = metrics.net_apy_from_equity(equity)
    mdd = metrics.max_drawdown_pct(equity)
    cal = (apy / mdd) if (isinstance(apy, (int, float)) and isinstance(mdd, (int, float)) and mdd > 0) else None
    return apy, mdd, cal


def _best_over(eq, overlay, grid):
    best = None
    for vm, fr in grid:
        a, d, c = _metrics(overlay(eq, vol_mult=vm, derisk_frac=fr))
        key = c if isinstance(c, (int, float)) else -1e9
        if best is None or key > best[0]:
            best = (key, a, d, c, (vm, fr))
    return best[1], best[2], best[3], best[4]


def recheck_book(equity: Sequence[float], grid=VOL_GRID) -> dict:
    """One book's four columns plus the claim arithmetic. Pure; the table and the tests share it."""
    raw = _metrics(equity)
    p_apy, p_dd, p_cal, p_par = _best_over(equity, deployed_overlay, grid)
    same = _metrics(causal_overlay(equity, vol_mult=p_par[0], derisk_frac=p_par[1]))
    b_apy, b_dd, b_cal, b_par = _best_over(equity, causal_overlay, grid)
    claimed = raw[1] - p_dd if isinstance(raw[1], (int, float)) and isinstance(p_dd, (int, float)) else None
    survives = raw[1] - same[1] if isinstance(raw[1], (int, float)) and isinstance(same[1], (int, float)) else None
    return {
        "raw": raw,
        "deployed": (p_apy, p_dd, p_cal), "deployed_params": p_par,
        "causal_same": same,
        "causal_best": (b_apy, b_dd, b_cal), "causal_best_params": b_par,
        # pp of drawdown the published cell claims to have removed FROM RAW, and how much of that
        # claim is left once the overlay cannot see the day it trades.
        "dd_cut_claimed_pp": claimed,
        "dd_cut_causal_pp": survives,
    }


def _f(x):
    return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--real", nargs="?", const="", metavar="DIR", default=None,
        help="recompute on the REAL aggressive-lab books (DIR, default: repo's data/aggressive_lab) "
             "instead of the documented fixture roster")
    args = ap.parse_args(argv)

    if args.real is not None:
        from spa_core.strategy_lab.aggressive_lab import AGGRESSIVE_LAB_DIR
        root = Path(args.real) if args.real else AGGRESSIVE_LAB_DIR
        loaded = ld.load_all(data_dir=root)
        if not loaded:
            # A worktree's data/aggressive_lab is empty BY CONSTRUCTION (untracked panel) — refuse
            # loudly instead of printing an empty table that reads as "the books are clean".
            print(f"REAL mode: no books found under {root} — pass the prod tree's "
                  f"data/aggressive_lab explicitly (the panel is untracked, absent in worktrees).",
                  file=sys.stderr)
            return 2
        print(f"REAL books from {root}")
    else:
        tmp = Path(__import__("tempfile").mkdtemp(prefix="guardian_causal_"))
        fx.materialize(tmp)
        loaded = ld.load_all(data_dir=tmp)
        print("documented fixture roster")

    print()
    print("DEPLOYED    = shipped overlay (decides knowing the return of the day it trades).")
    print("CAUSAL@same = same winning params, window ends yesterday — what the published cell is worth.")
    print("CAUSAL@best = best causal config over the same grid — what a non-peeking guardian can do.")
    print()
    header = (f"{'book':22} {'RAW apy/dd':>13}  {'DEPLOYED apy/dd/cal':>21}  "
              f"{'CAUSAL@same apy/dd/cal':>24}  {'CAUSAL@best apy/dd/cal':>24}")
    print(header)
    print("-" * len(header))

    claims = []
    for sid in sorted(loaded):
        s = loaded[sid]
        eq = _equity_of(s.backtest.series if s.backtest.n_points >= 2 else [])
        if len(eq) < 30:
            continue
        r = recheck_book(eq)
        print(f"{sid:22} {_f(r['raw'][0])+'/'+_f(r['raw'][1]):>13}  "
              f"{_f(r['deployed'][0])+'/'+_f(r['deployed'][1])+'/'+_f(r['deployed'][2]):>21}  "
              f"{_f(r['causal_same'][0])+'/'+_f(r['causal_same'][1])+'/'+_f(r['causal_same'][2]):>24}  "
              f"{_f(r['causal_best'][0])+'/'+_f(r['causal_best'][1])+'/'+_f(r['causal_best'][2]):>24}"
              f"   [depl{r['deployed_params']} best{r['causal_best_params']}]")
        if isinstance(r["dd_cut_claimed_pp"], float) and r["dd_cut_claimed_pp"] > 0.5:
            claims.append((sid, r["dd_cut_claimed_pp"], r["dd_cut_causal_pp"]))

    if claims:
        print()
        print("Drawdown cut CLAIMED by the published cell vs what survives causally (pp):")
        for sid, claimed, survives in sorted(claims, key=lambda t: t[2] / t[1]):
            share = survives / claimed * 100.0
            print(f"  {sid:22} claimed {claimed:6.1f} pp  ->  causal {survives:6.1f} pp  "
                  f"({share:.0f}% of the claim survives)")
        print()
        print("Read: a cell whose surviving share is ~0 was a one-day look-ahead, not a guardian.")
        print("The overlay's OWN claim — 'reduces the COMPOUNDING of SLOW drawdowns' — is where the")
        print("share stays high; the resale of that claim as a headline halving is where it does not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
