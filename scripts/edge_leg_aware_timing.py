#!/usr/bin/env python3
"""
scripts/edge_leg_aware_timing.py — registry idea LAT (Leg-Aware Timing)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

Working name LAT. The registry NUMBER is claimed at DELIVERY (registry rule at the top of
docs/DYNAMIC_LEVERAGE_GUARDIAN.md).


ORDERED BY GTN, IN ONE SENTENCE
===============================
GTN measured the invoice and found it wrong by a factor: charging the toll on LEGS instead
of on book weights multiplies it by ~1.87 (and by ~1.45 even when borrowings execute free),
because a levered book moves 3-5 dollars of instruments per dollar of weight. One book,
pendle_pt_levered, generates 43-48 % of all leg flow while being one name of ten.

#82 CIT already put a toll inside the switching rule and got +0.19 Calmar out of it — but it
internalised the FLAT, book-level toll, which is the same price for every name. Under the
corrected invoice the toll is no longer flat: it is 5x for a 3x loop and 1x for spot sUSDe.
A controller that sees THAT does not merely trade less; it trades ELSEWHERE.

MECHANISM (one substitution, everything else inherited from #82 verbatim)
------------------------------------------------------------------------
    #82 CIT:   switch iff   lambda * g_daily  >  tau_book * c / 1e4
    LAT:       switch iff   lambda * g_daily  >  tau_leg  * c / 1e4

    tau_book = sum_b |w*_b - w_prev_b|                      (flat: every name costs the same)
    tau_leg  = sum_l |E*(l) - E_prev(l)|,  E(l) = sum_b w_b e_b(l)     (GTN's leg algebra)

g_daily is #82's, unchanged: sum_b (w*_b - w_prev_b) * s_b with the arm's OWN signal, and a
book still in warm-up contributes s_b = 0 (fail-CLOSED — an unmeasured book is never credited
with edge it has not shown). lambda keeps its unit (days) and its two published limits:
lambda = inf is #80's arm cell-for-cell, lambda = 0 freezes the first vector forever.

WHY THIS IS NOT #82 WITH A DIFFERENT CONSTANT
  #82's rule is scale-free in the name: multiply every book's toll by the same factor and the
  rule only trades a bit less — that is the FREQUENCY finding #50 already owns, and #82 duly
  found frequency again (random schedules of the same switch count beat it 5-6 times in 20).
  LAT's toll is HETEROGENEOUS ACROSS NAMES. It can decline a move into a levered book while
  accepting the same-sized move into a spot book on the very same day. That is a different
  object: it changes WHICH books are held, not only HOW OFTEN the arm moves.

THE CONTROL THAT DECIDES THE VERDICT (inherited, non-negotiable)
  LAT trades less, like everything else in this family. So it is judged against a RANDOM
  SWITCH SCHEDULE of the SAME switch count (20 seeds) and against a PERIODIC schedule of the
  same count. Beating neither = frequency, again, and it gets written that way.

  Second control, and the one that separates LAT from CIT: the SAME rule with the toll
  FLATTENED (every book's leg gross replaced by its average). Same switch economics, same
  frequency, no cross-name information. If flat-toll does as well, the heterogeneity — the
  whole idea — bought nothing.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; every caveat of GTN and #82 carries over unchanged, including that
    g_daily is estimated with the SAME signal that picks the books;
  * the leg table is a judgement about which instruments are the same instrument. It is
    written out in edge_gross_to_net_toll.RAW_LEGS and re-checked against roster.py at run
    time; a drift there is a hard failure, not a warning;
  * the linear one-way cost model stays OPTIMISTIC, and more so here: leg flow is larger, so
    the convexity error it ignores is larger;
  * no parameter is chosen on TEST: the lambda ladder, the cost, the seeds and the canonical
    2025-06-30 split were fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_cost_internalised_timing as cit  # noqa: E402  (#82 harness, reused verbatim)
import edge_cost_signal_separation as css  # noqa: E402  (#80 harness, reused verbatim)
import edge_gross_to_net_toll as gtn  # noqa: E402  (GTN leg algebra, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 harness, reused verbatim)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

CONVENTION_COST = css.CONVENTION_COST
ARMS = css.ARMS
#: Fixed before any number was read (same ladder as #82).
LAMBDA_GRID: Tuple[float, ...] = (0.0, 1.0, 5.0, 20.0, 60.0, float("inf"))
CONTROL_SEEDS = tuple(range(20))
#: Which invoice the SCORER uses. GTN showed the flat one is wrong; the honest reading of
#: "what would this cost" is the leg invoice, so that is what pays for every arm here.
DEBT_RATE = 0.0  # the FRIENDLIEST defensible reading: borrowings execute free (GTN §3b)


def scoring_legs() -> gtn.LegTable:
    """The leg table the invoice is written on: real composition, borrowings free."""
    gtn.assert_leg_table_matches_roster()
    return gtn.legs_at_debt_rate(gtn.RAW_LEGS, DEBT_RATE)


def flattened_legs(legs: gtn.LegTable) -> gtn.LegTable:
    """Every book given the SAME gross notional (the average), each on a private leg.

    The control that isolates LAT's actual claim. It keeps the overall SIZE of the toll — so
    the switch economics and the resulting frequency are comparable — while destroying the
    cross-name information that is the whole mechanism. A private leg per book also removes
    netting, which the flat book-level convention never had either.
    """
    avg = sum(sum(abs(v) for v in vec.values()) for vec in legs.values()) / len(legs)
    return {b: {f"__flat__{b}": avg} for b in legs}


def signal_credit(value: Optional[float]) -> float:
    """fail-CLOSED: a book still in warm-up is credited NOTHING, never optimism.

    Split out of the gain sum on purpose. Inline, this rule is nearly untestable: weights sum
    to 1, so when EVERY book is in warm-up together (which is what a single lookback horizon
    produces) any constant credit cancels in `gain` and a mutation of it changes no number.
    It stops cancelling only when the warm-up set is a STRICT SUBSET of the books — which the
    adaptive MHFC signal can produce, because its None is decided per book. As a named
    function the rule can be substituted in a test and the difference measured.
    """
    return 0.0 if value is None else float(value)


def leg_tau(w_new: Dict[str, float], w_prev: Dict[str, float], legs: gtn.LegTable) -> float:
    """Tradeable leg flow of ONE proposed move (GTN's algebra, applied to a single step)."""
    a = gtn.leg_exposure(w_new, legs)
    b = gtn.leg_exposure(w_prev, legs)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def lat_history(
    book_rets: Dict[str, List[float]],
    n_dates: int,
    mode: str,
    lam: float,
    cost_assumed_bps: float,
    legs: gtn.LegTable,
) -> Tuple[css.WeightHistory, int]:
    """#82's cit_history with tau_book replaced by tau_leg. Nothing else differs.

    lam == inf -> take every candidate == #80's arm, cell for cell (asserted by test).
    lam == 0   -> take the first candidate and never move again (zero turnover).
    """
    cand = cit.candidates_for(book_rets, n_dates, mode)
    book_ids = cand.book_ids
    hist: css.WeightHistory = []
    prev: Optional[Dict[str, float]] = None
    switches = 0
    for k in range(len(cand.weights)):
        cw = cand.weights[k]
        if prev is None:
            w = cw
        else:
            tau = leg_tau(cw, prev, legs)
            if tau <= 1e-12:
                w = prev
            else:
                if math.isinf(lam):
                    take = True
                else:
                    sig = cand.signals[k]
                    gain = sum(
                        (cw.get(b, 0.0) - prev.get(b, 0.0)) * signal_credit(sig[b])
                        for b in book_ids
                    )
                    take = lam * gain > tau * cost_assumed_bps / 10_000.0
                if take:
                    w = cw
                    switches += 1
                else:
                    w = prev
        hist.append(w)
        prev = w
    return hist, switches


def _score(hist: css.WeightHistory, book_rets, legs, base_calmar: float, cost: float):
    """(netAPY, maxDD, Calmar, dCalmar, turnover total) under the LEG invoice."""
    gross, _ = css._gross_and_turnover(hist, book_rets)
    tau = gtn.leg_turnover(hist, legs)
    net = css._net(gross, tau, cost)
    return (
        mh._apy(net),
        mh._mdd(net),
        mh._calmar(net),
        css._dcalmar(net, base_calmar),
        sum(tau),
    )


def run(dates, book_rets, *, legs: gtn.LegTable, cost: float = CONVENTION_COST) -> Dict[str, dict]:
    book_ids = sorted(book_rets)
    n_dates = len(dates)
    n_days = n_dates - 1
    print("\n" + "=" * 78)
    print("Idea LAT: Leg-Aware Timing — a toll that is not the same price for every name [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_ids)}  ·  {dates[0]} … {dates[-1]} ({n_dates} days)")
    print(f"  invoice: LEG flow, borrowings at δ={DEBT_RATE:g} of the spot toll  ·  c={cost:g} bps")
    print("=" * 78)

    eq_hist = css._weight_history(book_rets, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq_hist, book_rets)
    eq_tau = gtn.leg_turnover(eq_hist, legs)
    eq_net = css._net(eq_gross, eq_tau, cost)
    eq_calmar, eq_apy = mh._calmar(eq_net), mh._apy(eq_net)
    print(f"\nBaseline equal-weight under the SAME invoice: APY={eq_apy * 100:.2f}%  "
          f"Calmar={eq_calmar:.2f}  leg TO/yr={sum(eq_tau) / (n_days / 365.0):.2f}")

    out: Dict[str, dict] = {}
    print("\n" + "─" * 78)
    print("1. LAMBDA LADDER — λ=inf is today's arm exactly; λ=0 is a frozen vector")
    print(f"{'arm':<16}{'λ':>6}{'switches':>10}{'netAPY':>9}{'maxDD':>9}"
          f"{'Calmar':>8}{'dCalmar':>9}{'legTO/yr':>10}")
    print("─" * 78)
    best: Dict[str, tuple] = {}
    for mode, label in ARMS:
        for lam in LAMBDA_GRID:
            hist, sw = lat_history(book_rets, n_dates, mode, lam, cost, legs)
            apy, mdd, cal, dcal, tot = _score(hist, book_rets, legs, eq_calmar, cost)
            lam_s = "inf" if math.isinf(lam) else f"{lam:g}"
            print(f"  {label:<14}{lam_s:>6}{sw:>10}{apy * 100:>8.2f}%{mdd * 100:>8.2f}%"
                  f"{cal:>8.2f}{dcal:>+9.2f}{tot / (n_days / 365.0):>10.2f}")
            if math.isinf(lam):
                out.setdefault(mode, {})["arm_dcalmar"] = dcal
                out[mode]["arm_switches"] = sw
            else:
                cur = best.get(mode)
                if cur is None or dcal > cur[1]:
                    best[mode] = (lam, dcal, sw)
        print()

    print("─" * 78)
    print("2. THE CONTROL THAT DECIDES IT — same switch COUNT, days chosen at random")
    print("   (20 seeds) and by a PERIODIC schedule. Beating neither = frequency, again.")
    print(f"{'arm':<16}{'λ*':>6}{'sw':>6}{'real dCal':>10}"
          f"{'random band (min/med/max)':>30}{'beat':>8}{'p':>7}{'periodic':>10}")
    print("─" * 78)
    for mode, label in ARMS:
        if mode not in best:
            continue
        lam, real_d, sw = best[mode]
        band: List[float] = []
        for seed in CONTROL_SEEDS:
            days = cit.random_switch_days(len(dates) - 1, sw, seed)
            h = cit.scheduled_history(book_rets, n_dates, mode, days)
            band.append(_score(h, book_rets, legs, eq_calmar, cost)[3])
        lo, med, hi = css._band(band)
        beat = sum(1 for d in band if d > real_d)
        p = (beat + 1) / (len(band) + 1)
        step = max(1, (len(dates) - 1) // max(1, sw))
        per_days = list(range(1, len(dates) - 1, step))[:sw]
        per_d = _score(cit.scheduled_history(book_rets, n_dates, mode, per_days),
                       book_rets, legs, eq_calmar, cost)[3]
        print(f"  {label:<14}{lam:>6g}{sw:>6}{real_d:>+10.2f}"
              f"{lo:>+10.2f}/{med:>+9.2f}/{hi:>+9.2f}{beat:>5}/{len(band):<3}{p:>6.3f}{per_d:>+10.2f}")
        out.setdefault(mode, {}).update(
            {"lambda_star": lam, "dcalmar": real_d, "switches": sw,
             "random_band": (lo, med, hi), "p_random": p, "periodic": per_d}
        )
    print("   NOTE: an arm whose λ* is 0 makes ZERO switches. Its control band is a column of")
    print("   zeros and its p=0.048 is the floor of a 20-seed test, not evidence of anything.")

    print("\n" + "─" * 78)
    print("3. THE CONTROL THAT SEPARATES LAT FROM #82 — the SAME rule with a FLAT toll")
    print("   (every book the average leg gross). Same size of toll, no cross-name signal.")
    print(f"{'arm':<16}{'λ*':>6}{'LAT dCal':>10}{'flat dCal':>11}{'LAT sw':>8}{'flat sw':>9}")
    print("─" * 78)
    flat = flattened_legs(legs)
    for mode, label in ARMS:
        if mode not in best:
            continue
        lam, real_d, sw = best[mode]
        h_flat, sw_flat = lat_history(book_rets, n_dates, mode, lam, cost, flat)
        # both are SCORED on the true leg invoice; only the RULE's toll differs
        d_flat = _score(h_flat, book_rets, legs, eq_calmar, cost)[3]
        print(f"  {label:<14}{lam:>6g}{real_d:>+10.2f}{d_flat:>+11.2f}{sw:>8}{sw_flat:>9}")
        out.setdefault(mode, {})["flat_dcalmar"] = d_flat
        out[mode]["flat_switches"] = sw_flat

    print("\n" + "─" * 78)
    print(f"4. TRAIN / TEST (split {mh.SPLIT_DATE}) — does λ* move between the halves?")
    cut = gtn._split_index(dates, mh.SPLIT_DATE)
    print(f"{'arm':<16}{'λ* train':>10}{'dCal train':>12}{'λ* test':>9}{'dCal test':>11}")
    print("─" * 78)
    for mode, label in ARMS:
        halves = []
        for sl in (slice(0, cut), slice(cut, None)):
            base = mh._calmar(css._net(eq_gross[sl], eq_tau[sl], cost))
            bl, bd = None, None
            for lam in LAMBDA_GRID:
                if math.isinf(lam):
                    continue
                hist, _ = lat_history(book_rets, n_dates, mode, lam, cost, legs)
                gross, _ = css._gross_and_turnover(hist, book_rets)
                tau = gtn.leg_turnover(hist, legs)
                d = css._dcalmar(css._net(gross[sl], tau[sl], cost), base)
                if bd is None or d > bd:
                    bl, bd = lam, d
            halves.append((bl, bd))
        (l_tr, d_tr), (l_te, d_te) = halves
        print(f"  {label:<14}{l_tr:>10g}{d_tr:>+12.2f}{l_te:>9g}{d_te:>+11.2f}")
        out.setdefault(mode, {})["lambda_train_test"] = (l_tr, l_te)

    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    legs = scoring_legs()
    dates, book_rets = gtn.load_real_panel()
    missing = sorted(set(book_rets) - set(legs))
    if missing:
        raise RuntimeError(f"panel carries books with no leg vector: {missing}")
    run(dates, book_rets, legs={b: legs[b] for b in sorted(book_rets)})
    print("\n" + "=" * 78)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
