#!/usr/bin/env python3
"""
scripts/edge_cost_quote_divergence.py — registry idea CQD (Cost Quote Divergence)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the dashboard or the fleet. Reads the aggressive-lab panel READ-ONLY. Capital is not
moved. No module is built and no agent is deployed here.

Working name CQD. The registry NUMBER is claimed at DELIVERY.


THE QUESTION, WHICH CVD RAISED AND DID NOT ASK
==============================================
CVD traced the R&D branch's 96 bps to its origin and found it was never a cost. In doing so
it read `spa_core/backtesting/tier1/cost_model.py` and found a DIFFERENT number for the same
kind of charge — 8 bps of turnover. And the aggressive lab's live L2 organ, which has been
running hourly for weeks, carries a THIRD: `guardian_forward.GUARDIAN_PARAMS` charges
`roundtrip_cost = 0.0015` — 15 bps — against `abs(prev − exposure)`, which is the SAME
quantity the branch calls τ.

    8 bps  ·  15 bps  ·  96 bps  — same axis, same lab, same books, 12× apart.

None of the three has a measurement date or a source. That much is bookkeeping. The question
worth a registry entry is the next one, and nobody has asked it:

    DOES THE DISAGREEMENT CHANGE ANY VERDICT?

A 12× spread in a number that never moves a decision is an untidiness. A 12× spread in a
number that decides whether an organ helps or hurts is a defect with a size. Which of the two
it is cannot be reasoned out — the answer depends on how much each organ TRADES, and that is
a measurement.

MECHANISM (no new rule; the tree's own organs, re-priced)
---------------------------------------------------------
For each of the ten real books, run the aggressive lab's OWN pre-emptive guardian
(`spa_core/strategy_lab/aggressive_lab/guardian.py::apply_guardian_vol`, imported, at the
parameters `guardian_forward` actually deploys) at each convention on the ladder, and read
off the guardian's own break-even:

    c*_guard(book) = the largest roundtrip cost, in bps of |Δexposure|, at which the guarded
                     path still has a HIGHER Calmar than the unguarded one.

Then set it beside c*_timing = 31…70 bps, which CVD measured for the h60 leverage arm on the
same panel with the same axis. Two organs, one axis, one panel: the comparison is legitimate
and it is the whole content of the entry.

THE PREDICTION, WRITTEN DOWN BEFORE THE RUN (so the entry cannot be a post-hoc story)
    The guardian is rare-switching by construction (it moves only when realized vol spikes
    past 2× its own baseline); the timing arms turn over 14–118× per year. If the discriminant
    is turnover, the guardian's c* should be one to three ORDERS larger than the timing arm's,
    and the 12× convention spread should be inert for the guardian and decisive for the
    branch. If instead the guardian's c* lands anywhere near 8…96, the convention is
    load-bearing in a LIVE advisory organ and that is a finding of a different and more
    urgent kind.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; the guardian's own caveats carry over unchanged and are not softened
    here: it reduces SLOW-risk drawdown compounding only; GAP risk (exploit, instant depeg,
    drained exit) is not preventable by any overlay and stays in the tier tail;
  * `roundtrip_cost` is charged on |Δexposure| exactly as the deployed organ charges it. It
    is a proportional toll only: gas in dollars per leg is NOT in this file. So c*_guard is
    an UPPER bound in the same way c*_timing is, and at pilot sizes gas dominates both —
    that is CVD's finding and it is not re-litigated here;
  * dead books are named. Four of the ten carry stretches of exactly zero return (the panel's
    known missing-2026 books). A book whose Calmar is undefined is printed `n/a`, never as
    "the guardian did not help": an absent measurement and a null result must not read alike;
  * c* is read off an integer bps grid; every value printed is a rung that was SCORED;
  * the guardian's parameters are `guardian_forward`'s deployed ones, imported rather than
    retyped, so this file cannot drift away from the organ it is about;
  * no parameter is chosen after reading: the grid, the book set (all ten, no selection) and
    the comparison target (CVD's published 31…70) were fixed before the first number.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_gross_to_net_toll as gtn  # noqa: E402  (real-panel loader, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 Calmar/APY/maxDD, reused verbatim)

from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol  # noqa: E402
from spa_core.strategy_lab.swarm import guardian_forward as gf  # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: The measurement grid, in bps of |Δexposure|. Fixed before any number was read. It reaches
#: 100× the widest convention in the tree, because the PREDICTION above says the guardian's
#: break-even may be orders away and a grid that stopped at 384 would only be able to say
#: "off the end" — which is not a measurement.
CVAR_GRID: Tuple[int, ...] = tuple(range(0, 10001))

#: Where CVD measured the timing branch's h60 arm on this same panel and this same axis.
CVD_TIMING_CSTAR = (31, 70)
CVD_TIMING_CSTAR_HARD_HALF = (23, 42)

#: The branch's canonical out-of-sample boundary, unchanged from #79…CVD.
SPLIT_DATE = "2025-06-30"

#: The toll the L2 organ actually deploys, read from the organ.
DEPLOYED_BPS = 1e4 * gf.GUARDIAN_PARAMS["roundtrip_cost"]

#: The three conventions, read from their modules at import time — never retyped here.
def census() -> List[Tuple[str, float, str, str]]:
    """(name, bps on |Δw|, reader, provenance) for every proportional toll in the tree.

    Read from the modules, so the census cannot describe a tree that no longer exists. Gas is
    deliberately EXCLUDED: it is dollars per leg, a different dimension, and #91/CVD already
    put it on its own axis. Mixing the two is how a census turns into a muddle.
    """
    from spa_core.backtesting.tier1 import cost_model as cm
    import edge_cost_signal_separation as css

    return [
        ("cost_model.SLIPPAGE_BPS_STABLE", float(cm.SLIPPAGE_BPS_STABLE),
         "allocator ACT/HOLD (rebalance_economics) + tier1 backtest",
         "no date, no source (cost_model_provenance §2)"),
        ("guardian_forward roundtrip_cost", 1e4 * float(gf.GUARDIAN_PARAMS["roundtrip_cost"]),
         "LIVE hourly L2 organ + scripts/guardian_backtest.py",
         "no date, no source"),
        ("edge_cost_signal_separation.CONVENTION_COST", float(css.CONVENTION_COST),
         "registry entries #49…#91",
         "break-even of #10, not a cost; applied at 2× its own definition (CVD)"),
    ]


def convention_spread() -> float:
    """Widest / narrowest of the census, on the one axis they share."""
    vals = [v for _n, v, _r, _p in census() if v > 0]
    return max(vals) / min(vals)


# ── the guardian, re-priced ──────────────────────────────────────────────────────
def _equity(rets: Sequence[float]) -> List[float]:
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _rets(equity: Sequence[float]) -> List[float]:
    """Daily returns of an equity path, refusing on a path that reached zero.

    A wiped-out path has no return on the following day, and letting the division through
    would raise deep inside a scan where the cause is invisible. #91 already paid for the
    sibling of this defect: `mh._apy` clips a wipeout to APY 0, so a bankrupt arm can OUTRANK
    a merely losing one. Ruin is a verdict of its own here, not a number.
    """
    out: List[float] = []
    for i in range(len(equity) - 1):
        if equity[i] <= 0.0:
            raise Ruin(f"equity path reached zero at index {i}")
        out.append(equity[i + 1] / equity[i] - 1.0)
    return out


class Ruin(Exception):
    """The equity path reached zero. Not a Calmar, not a zero — a different outcome."""


def is_dead(rets: Sequence[float]) -> bool:
    """A book with no movement at all is ABSENT from the measurement, not neutral in it.

    The panel carries books with no 2026 data; their returns are exactly 0.0 across the whole
    axis. A guardian cannot be judged on a flat line, and printing 0.00 for such a book would
    put an absence and a null result in the same column.
    """
    return all(abs(r) < 1e-12 for r in rets)


def switches_per_year(equity: Sequence[float], n_days: int, **params) -> float:
    """How often the deployed guardian actually moves. The discriminant of the whole entry.

    Counted by DIFFERENCING two runs of the organ itself rather than by re-implementing its
    trigger: a re-implementation that drifted would quietly change the very number the entry
    turns on. A run at cost 0 and a run at a tiny cost differ ONLY on the days exposure moved.
    """
    free = apply_guardian_vol(equity, roundtrip_cost=0.0, **params)
    tolled = apply_guardian_vol(equity, roundtrip_cost=1e-6, **params)
    moves = sum(1 for a, b in zip(_rets(free), _rets(tolled)) if abs(a - b) > 1e-15)
    yrs = n_days / 365.0 if n_days else 1.0
    return moves / yrs


#: Verdicts that are NOT a number. Each names a distinct reason the break-even does not
#: exist, because collapsing them into one column is how a table starts lying at its edges:
#: "the guardian is not worth its toll" and "the question does not arise here" would other-
#: wise print alike, and only the first is a finding.
NO_CSTAR = {
    "dead": "book has no movement in this panel at all (missing data)",
    "never fires": "guardian never changed exposure — no toll is ever charged",
    "no DD": "raw path has no drawdown, so raw Calmar is undefined; nothing to beat",
    "ruin": "the path reached zero; a wipeout is not a Calmar",
    "never beats": "guarded Calmar is below raw even with a FREE roundtrip",
}

#: A Calmar comparison is only a statement about IMPROVEMENT when the thing being improved is
#: positive. On a book that is losing money, "higher Calmar" can mean a shallower path to the
#: same loss, or an artefact of a shrinking denominator — either way it is not evidence that
#: the overlay helps, and quoting it as such is the aggregate-cut-as-per-item-verdict error.
#: Such rows are MEASURED and PRINTED, and then excluded from every claim, in that order.
def comparable(raw_calmar: float, raw_apy: float) -> bool:
    return raw_calmar == raw_calmar and raw_calmar > 0.0 and raw_apy > 0.0


def guardian_cstar(
    equity: Sequence[float],
    grid: Sequence[int] = CVAR_GRID,
    **params,
) -> Tuple[object, float, float]:
    """(c* or a NO_CSTAR key, raw Calmar, guarded Calmar at cost 0) for one book.

    c* is the largest rung of the grid at which the guarded Calmar still exceeds the raw one.
    A key from NO_CSTAR means the break-even does not exist, and says WHY — see the note on
    that mapping. The first version of this function returned "never beats" for a book with
    no drawdown at all, which is the same defect it exists to avoid: an undefined comparison
    printed as an unfavourable one.
    """
    try:
        raw_rets = _rets(equity)
    except Ruin:
        return "ruin", float("nan"), float("nan")
    raw = mh._calmar(raw_rets)
    if not (raw == raw) or raw in (float("inf"), float("-inf")):
        return "no DD", raw, float("nan")

    best: object = None
    at_zero = float("nan")
    for c in grid:
        g = apply_guardian_vol(equity, roundtrip_cost=c / 1e4, **params)
        try:
            cal = mh._calmar(_rets(g))
        except Ruin:
            break
        if c == 0:
            at_zero = cal
        if cal > raw:
            best = c
        elif best is not None:
            # monotone in the toll by construction (a strictly larger toll can only lower the
            # path), so the first failure after a success ends the scan.
            break
    return (best if best is not None else "never beats"), raw, at_zero


def run(dates, book_rets) -> Dict[str, object]:
    n_days = len(dates) - 1
    params = {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}
    out: Dict[str, object] = {}

    print("\n" + "=" * 100)
    print("Idea CQD — one trade, three prices. Does the 12× disagreement move a verdict?  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_rets)}  ·  {dates[0]} … {dates[-1]} ({len(dates)} days)")
    print(f"  guardian parameters: the ones guardian_forward DEPLOYS: {params}")
    print("=" * 100)

    print("\n" + "─" * 100)
    print("0. THE CENSUS — every proportional toll in the tree, on the ONE axis they share")
    print("   (bps of |Δexposure| / turnover). Gas is excluded on purpose: dollars per leg is")
    print("   a different dimension and #91/CVD already gave it its own axis.")
    print(f"{'constant':>46}{'bps':>7}   reader / provenance")
    print("─" * 100)
    rows = census()
    for name, bps, reader, prov in rows:
        print(f"{name:>46}{bps:>7.0f}   {reader}")
        print(f"{'':>53}   ({prov})")
    spread = convention_spread()
    print(f"\n   widest / narrowest = {spread:.1f}× — on the same axis, in the same lab, over")
    print(f"   the same ten books. Not one of the three carries a measurement date.")
    out["census"] = [[n, b, r, p] for n, b, r, p in rows]
    out["spread"] = spread

    print("\n" + "─" * 100)
    print("1. THE GUARDIAN'S OWN BREAK-EVEN, per book. c* = the largest roundtrip toll at which")
    print("   the guarded path still has a HIGHER Calmar than the unguarded one. Grid 0…"
          f"{CVAR_GRID[-1]} bps,")
    print("   step 1; every value is a rung that was SCORED. 'dead' = the book has no movement")
    print("   in this panel at all (no 2026 data) — an ABSENCE, not a null result.")
    print(f"{'book':>22}{'switches/yr':>13}{'raw APY%':>10}{'raw DD%':>9}"
          f"{'raw Cal':>10}{'guard@0':>10}{'c* (bps)':>13}{'cmp?':>7}")
    print("─" * 100)
    per_book: Dict[str, object] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        eq = _equity(rets)
        if is_dead(rets):
            print(f"{book:>22}{'—':>13}{'—':>10}{'—':>9}{'—':>10}{'—':>10}{'dead':>13}{'—':>7}")
            per_book[book] = {"verdict": "dead", "comparable": False}
            continue
        sw = switches_per_year(eq, n_days, **params)
        c, raw, at0 = guardian_cstar(eq, **params)
        if sw == 0.0 and isinstance(c, str):
            c = "never fires"
        raw_rets = _rets(eq)
        r_apy, r_dd = mh._apy(raw_rets) * 100.0, mh._mdd(raw_rets) * 100.0
        ok = comparable(raw, r_apy)
        shown = c if isinstance(c, str) else (
            f"≥{CVAR_GRID[-1]}" if c >= CVAR_GRID[-1] else str(c))
        fr = "—" if raw != raw or raw in (float("inf"), float("-inf")) else f"{raw:.2f}"
        f0 = "—" if at0 != at0 else f"{at0:.2f}"
        print(f"{book:>22}{sw:>13.2f}{r_apy:>10.1f}{r_dd:>9.1f}{fr:>10}{f0:>10}{shown:>13}"
              f"{('yes' if ok else 'NO'):>7}")
        per_book[book] = {"switches_yr": sw, "raw_calmar": raw, "guarded_calmar_free": at0,
                          "raw_apy_pct": r_apy, "raw_mdd_pct": r_dd, "comparable": ok,
                          "c_star": c if isinstance(c, int) else None,
                          "verdict": c if isinstance(c, str) else "measured"}
    print("\n   verdicts that are not a number, and why they are separate columns of meaning:")
    for k, why in NO_CSTAR.items():
        print(f"     {k:<14} {why}")
    print("   comparable=NO: raw Calmar or raw APY is not positive. A 'higher Calmar' on a")
    print("   losing book is not evidence the overlay helps — those rows are measured and")
    print("   printed, and then excluded from every claim below.")
    out["per_book"] = per_book

    print("\n" + "─" * 100)
    print("2. THE COMPARISON THE ENTRY EXISTS FOR. Same panel, same axis, two organs.")
    print("   Only books whose raw path is comparable (positive APY and Calmar) are counted;")
    print("   the excluded ones are named so the reader can see what was left out and why.")
    excluded = sorted(b for b, v in per_book.items() if not v.get("comparable"))
    print(f"   excluded from every claim below ({len(excluded)}): {', '.join(excluded)}")
    print(f"{'organ':>34}{'turnover/yr':>14}{'c* (bps)':>22}")
    print("─" * 100)
    helped = [b for b, v in per_book.items()
              if v.get("c_star") is not None and v.get("comparable")]
    if helped:
        lo = min(per_book[b]["c_star"] for b in helped)
        hi = max(per_book[b]["c_star"] for b in helped)
        sw_lo = min(per_book[b]["switches_yr"] for b in helped)
        sw_hi = max(per_book[b]["switches_yr"] for b in helped)
        print(f"{'guardian (live L2 organ)':>34}{f'{sw_lo:.2f}…{sw_hi:.2f}':>14}"
              f"{f'{lo}…{hi}':>22}")
    print(f"{'h60 timing arm (CVD, full history)':>34}{'14.38':>14}"
          f"{f'{CVD_TIMING_CSTAR[0]}…{CVD_TIMING_CSTAR[1]}':>22}")
    print(f"{'h60 timing arm (CVD, hard half)':>34}{'14.38':>14}"
          f"{f'{CVD_TIMING_CSTAR_HARD_HALF[0]}…{CVD_TIMING_CSTAR_HARD_HALF[1]}':>22}")
    out["helped_books"] = helped

    print("\n" + "─" * 100)
    print("3. WHERE EACH CONVENTION LANDS. A convention only matters where it crosses a c*.")
    print(f"{'convention':>46}{'bps':>7}{'binds the guardian?':>22}{'binds h60?':>14}")
    print("─" * 100)
    binds: Dict[str, object] = {}
    g_lo = min((per_book[b]["c_star"] for b in helped), default=None)
    for name, bps, _r, _p in rows:
        gb = "n/a" if g_lo is None else ("YES" if bps >= g_lo else "no")
        hb = "YES" if bps >= CVD_TIMING_CSTAR_HARD_HALF[0] else "no"
        print(f"{name:>46}{bps:>7.0f}{gb:>22}{hb:>14}")
        binds[name] = [gb, hb]
    out["binds"] = binds

    # ── 4. the split ─────────────────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("4. SPLIT. c* is a claim about an affordable cost and must hold on both halves of")
    print(f"   the canonical {SPLIT_DATE} boundary. Comparable books only.")
    cut = datetime.date.fromisoformat(SPLIT_DATE)
    k_cut = next((i for i in range(len(dates) - 1) if dates[i + 1] > cut), len(dates) - 1)
    print(f"   TRAIN {dates[1]}…{dates[k_cut]} ({k_cut} d)  ·  "
          f"TEST {dates[k_cut + 1]}…{dates[-1]} ({len(dates) - 1 - k_cut} d)")
    print(f"{'book':>20}{'TRAIN c*':>14}{'TEST c*':>14}{'deployed':>11}{'binds TEST?':>13}")
    print("─" * 100)
    split_out: Dict[str, object] = {}
    for book in sorted(book_rets):
        if not per_book[book].get("comparable"):
            continue
        halves = {}
        for name, sl in (("TRAIN", slice(0, k_cut)), ("TEST", slice(k_cut, None))):
            seg = book_rets[book][sl]
            if is_dead(seg):
                halves[name] = "dead"
                continue
            c, _raw, _a0 = guardian_cstar(_equity(seg), **params)
            halves[name] = c
        t = halves["TEST"]
        binds = "n/a" if isinstance(t, str) else ("YES" if DEPLOYED_BPS > t else "no")
        print(f"{book:>20}{str(halves['TRAIN']):>14}{str(t):>14}"
              f"{DEPLOYED_BPS:>11.0f}{binds:>13}")
        split_out[book] = [halves["TRAIN"], halves["TEST"], binds]
    out["split"] = split_out

    # ── 5. the organ judged on its OWN stated purpose ────────────────────────────
    print("\n" + "─" * 100)
    print("5. FAIRNESS TO THE ORGAN. Its own honest_limits say it 'reduces SLOW-risk drawdown")
    print("   compounding' — that is a claim about maxDD, not about Calmar, and it is judged")
    print(f"   here on ITS axis, out of sample, at the toll it actually deploys ({DEPLOYED_BPS:.0f} bps).")
    print(f"{'book':>20}{'raw APY%':>10}{'raw DD%':>9}{'gd APY%':>10}{'gd DD%':>9}"
          f"{'DD cut?':>9}{'ΔCalmar':>10}")
    print("─" * 100)
    oos: Dict[str, object] = {}
    for book in sorted(book_rets):
        seg = book_rets[book][k_cut:]
        if is_dead(seg):
            print(f"{book:>20}{'no 2026 data — absent, not neutral':>57}")
            oos[book] = "dead"
            continue
        eq = _equity(seg)
        rr = _rets(eq)
        gd = _rets(apply_guardian_vol(eq, roundtrip_cost=DEPLOYED_BPS / 1e4, **params))
        rdd, gdd = mh._mdd(rr) * 100, mh._mdd(gd) * 100
        cal_r, cal_g = mh._calmar(rr), mh._calmar(gd)
        # maxDD is negative; "cut" means the guarded path drew down LESS deeply.
        verdict = "yes" if gdd > rdd + 1e-9 else ("same" if abs(gdd - rdd) < 1e-9 else "NO")
        dc = "—" if (cal_r != cal_r or cal_r in (float("inf"), float("-inf"))) else f"{cal_g - cal_r:+.3f}"
        print(f"{book:>20}{mh._apy(rr) * 100:>10.2f}{rdd:>9.2f}{mh._apy(gd) * 100:>10.2f}"
              f"{gdd:>9.2f}{verdict:>9}{dc:>10}")
        oos[book] = {"raw_dd": rdd, "guarded_dd": gdd, "dd_cut": verdict, "dcalmar": dc}
    print("\n   'NO' in the DD column is the sharpest cell in this file: on a book whose own")
    print("   drawdown is near zero, the overlay's CHURN becomes the drawdown it exists to")
    print("   prevent. That is not a tuning question; it is the overlay firing where there is")
    print("   nothing to protect.")
    out["oos_own_axis"] = oos

    print("\n" + "=" * 100)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 100)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    dates, book_rets = gtn.load_real_panel()
    run(dates, book_rets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
