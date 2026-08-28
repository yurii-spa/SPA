#!/usr/bin/env python3
"""
scripts/edge_periodic_schedule_frontier.py — registry ideas PSF and PLD

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY and writes NOTHING anywhere. Capital is not moved.

Working names are used inside the code (PSF / PLD). Registry NUMBERS are claimed at
DELIVERY, never at writing time (registry rule at the top of DYNAMIC_LEVERAGE_GUARDIAN.md).


THE QUESTION, ORDERED BY THREE VERDICTS IN A ROW
================================================
#50 NTB, #80 CSS and #82 CIT each built a different timing rule, and each was killed by the
same control: a random schedule of the SAME trade count did as well or better. #82 wrote the
practical conclusion in its own last paragraph:

    "инженерию стоит вкладывать не в «умный контроллер, который видит цену», а в ОГРАНИЧЕНИЕ
     ЧАСТОТЫ … первое покупается даром периодическим расписанием"

and it printed one number to back it: a PERIODIC schedule of the same switch count scored
dCalmar +1.31 against the smart arm's +1.12.

That number is a CONTROL, matched to somebody else's switch count, at one price, for one arm.
The registry has never measured the periodic schedule as an ARM ON ITS OWN AXIS. If frequency
is the thing that works, the frequency axis deserves to be measured directly, and the first
honest question about it was already answered once for a different machine, by #60 DHD:

    "ОСЬ «КАК ЧАСТО РЕШАЕМ» ИЗМЕРЕНА И ОКАЗАЛАСЬ НЕ РУЧКОЙ, А МОНЕТКОЙ: ФАЗА сетки решений
     двигает ответ СИЛЬНЕЕ, чем её ШАГ"

#60 said that about the demotion state machine's decision grid (D/J/R/M) on the raw panel.
Whether it also holds for the ranking arms of #79-#82 under the cost convention is open, and
it is the difference between "rebalance every 20 days" being an engineering parameter and
being a coin flip with a number written on it.


IDEA PSF — Periodic Schedule Frontier
--------------------------------------
MECHANISM (a calendar rule; it reads NOTHING):

    the arm may take its candidate weight vector only on days  j  with  (j-1) mod k == phase
    on every other day it holds what it has

  k = 1                    == today's arm, every day, EXACTLY (== #82's lambda=inf arm,
                              == #81's arm; asserted cell-by-cell by test against a
                              published row: h60 netAPY 22.77% / DD -6.54% / Calmar 3.48)
  phase in {0 .. k-1}      exhaustive, never sampled: the k phases PARTITION the day axis

Two numbers are reported for every k, and the whole point of the record is their ratio:

    SPREAD ACROSS k      how much the median phase moves when the period changes  <- the knob
    SPREAD WITHIN k      how much phases of the SAME k differ from each other     <- the coin

If the second swamps the first, "rebalance every k days" is not a parameter and no value of it
may be published as a finding.


IDEA PLD — Phase-Laddered Deployment
-------------------------------------
The constructive consequence, and the reason the two are measured together. If the phase is a
coin, do not flip it: run all k phases at once as k tranches of 1/k of capital, each on its own
offset. This is standard overlapping-portfolio construction, and here it has an unusual
property worth stating plainly:

  PLD ADDS NO DEGREE OF FREEDOM. Its equity path is the arithmetic mean of the k phase equity
  paths — a determined function of runs that already exist. There is nothing in it to fit, so
  it cannot be overfitted; it can only fail to help.

  Its turnover is NOT assumed to be unchanged, it is MEASURED: each tranche trades 1/k of the
  book k times less often, and the ladder's per-day turnover is the equity-weighted mean of
  the tranches'. The equity weights drift apart as tranches diverge, so the identity is only
  approximate and is printed, never asserted.

  What PLD can NEVER do is beat the best phase — that one is unknowable in advance. It removes
  the WORST phase, which is a different and much weaker claim, and this file must not confuse
  the two.

WHY THIS IS NOT #50, #60, #80 OR #82
  #50 NTB   — a band on WEIGHT DRIFT. The trade date is decided by how far the weight moved;
              here nothing is read at all, the calendar decides.
  #60 DHD   — the decision grid of the DEMOTION STATE MACHINE (D/J/R/M) on the raw panel, with
              no cost convention applied. Same word "phase", different machine, different
              dataset, different accounting. Its verdict is the PRIOR here, not the answer.
  #80 CSS   — schedule ROTATION as a control on a fixed arm; the schedule never became an arm.
  #82 CIT   — the toll inside the objective. The periodic schedule appeared there only as one
              matched control point.
  PSF       — the schedule IS the arm, and k IS the axis.

LOOK-AHEAD
  Inherited from #79/#82 unchanged, and structurally stronger: the schedule is a function of
  the day INDEX only. It cannot see returns even in principle. A test perturbs the future and
  requires the past weight vectors to be bit-identical anyway.

HONEST LIMITS DECLARED UP FRONT
  • evidence L0 — the panel's books are themselves backtests over real deep-history feeds, so
    this measures a rule on a real return SHAPE, not realized P&L. All numbers marked [bt];
  • the linear one-way cost model is #10's convention and is OPTIMISTIC: real slippage is
    convex and worst exactly in a crisis, so printed break-evens are reached EARLIER in life;
  • a period k costs k phases of compute and 1/k of the statistical power per phase: at k=90
    a phase makes ~9 trades over 851 days, and a difference between two such paths is mostly
    which week they happened to hold. Large k is printed for the shape of the curve, and no
    single large-k cell may be quoted as a result on its own;
  • no parameter is chosen on TEST: the k ladder, the cost grid, the seeds and the canonical
    split were fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_cost_internalised_timing as cit  # noqa: E402  (#81/#82 harness, reused verbatim)
import edge_cost_signal_separation as css  # noqa: E402  (#80 harness, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 harness, reused verbatim)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

BookRets = Dict[str, List[float]]

#: Inherited from #80/#82 without change — comparability with the published rows is the point.
COST_GRID = css.COST_GRID
CONVENTION_COST = css.CONVENTION_COST
ARMS = css.ARMS
SPLIT_DATE = mh.SPLIT_DATE

#: The axis. k=1 is today's arm; fixed before any number was read.
K_GRID: Tuple[int, ...] = (1, 2, 3, 5, 10, 20, 40, 60, 90)

#: Same 20 seeds as #82's decisive control, so the two bands are read on the same terms.
CONTROL_SEEDS = tuple(range(20))


# ───────────────────────── the schedule ──────────────────────────────────────────
def phase_days(n_slots: int, k: int, phase: int) -> List[int]:
    """Day indices on which a (k, phase) arm is allowed to move.

    Index 0 is excluded on purpose: the first vector is always taken (there is nothing to
    hold yet), which is how `cit.scheduled_history` already behaves. The k phases therefore
    partition {1 .. n_slots-1} exactly — asserted by a test, because an off-by-one here
    would quietly make some days unreachable by ANY phase and bias every band in the file.
    """
    if k < 1:
        raise ValueError(f"period k must be >= 1, got {k}")
    if not 0 <= phase < k:
        raise ValueError(f"phase must be in [0, {k}), got {phase}")
    return [j for j in range(1, n_slots) if (j - 1) % k == phase]


def periodic_scored(
    book_rets: BookRets,
    n_dates: int,
    mode: str,
    k: int,
    phase: int,
) -> cit.Scored:
    """One (arm, k, phase) run, scored by #80's scorer unchanged."""
    n_slots = n_dates - 1
    days = phase_days(n_slots, k, phase)
    hist = cit.scheduled_history(book_rets, n_dates, mode, days)
    return cit.score(hist, book_rets, switches=len(days))


def phase_family(book_rets: BookRets, n_dates: int, mode: str, k: int) -> List[cit.Scored]:
    """All k phases of one period — EXHAUSTIVE, never sampled."""
    return [periodic_scored(book_rets, n_dates, mode, k, p) for p in range(k)]


# ───────────────────────── the ladder (PLD) ──────────────────────────────────────
class Ladder:
    __slots__ = ("net", "turn_per_day", "degenerate")

    def __init__(self, net: List[float], turn_per_day: List[float], degenerate: bool) -> None:
        self.net, self.turn_per_day, self.degenerate = net, turn_per_day, degenerate

    def turnover_per_year(self, n_days: int) -> float:
        return css._turnover_per_year(self.turn_per_day, n_days)


def ladder_at_cost(family: Sequence[cit.Scored], cost_bps: float) -> Ladder:
    """k tranches of 1/k capital, each on its own phase, each paying ITS OWN toll.

    The ladder's equity is the arithmetic mean of the tranches' equities, so its daily return
    is the EQUITY-WEIGHTED mean of theirs — not the plain mean. The distinction is not
    pedantic: tranches diverge, and after 851 days the weights are visibly unequal. A test
    mutates this to the plain mean and requires the number to move.

    Turnover is measured the same way (equity-weighted), never assumed.
    """
    if not family:
        raise ValueError("empty phase family")
    nets = [s.net(cost_bps) for s in family]
    turns = [list(s.turns) for s in family]
    horizon = len(nets[0])
    if any(len(n) != horizon for n in nets):
        raise ValueError("phase runs have different horizons — refusing to average them")

    k = len(family)
    equity = [1.0] * k
    prev_total = float(k)
    out: List[float] = []
    tw: List[float] = []
    degenerate = False
    for t in range(horizon):
        total_prev = sum(equity)
        if total_prev <= 0.0:
            degenerate = True
            break
        tw.append(sum(equity[i] / total_prev * turns[i][t] for i in range(k)))
        for i in range(k):
            step = 1.0 + nets[i][t]
            if step <= 0.0:
                degenerate = True
                step = 0.0
            equity[i] *= step
        total = sum(equity)
        if total <= 0.0:
            degenerate = True
            out.append(-1.0)
            break
        out.append(total / prev_total - 1.0)
        prev_total = total
    return Ladder(out, tw, degenerate)


# ───────────────────────── metrics / formatting ──────────────────────────────────
class Row:
    __slots__ = ("apy", "mdd", "calmar", "dcal", "to", "switches")

    def __init__(self, apy, mdd, calmar, dcal, to, switches):
        self.apy, self.mdd, self.calmar = apy, mdd, calmar
        self.dcal, self.to, self.switches = dcal, to, switches


def measure(net: Sequence[float], turn_per_day: Sequence[float], n_days: int,
            base_calmar: float, switches: int) -> Row:
    net = list(net)
    if css._degenerate(net):
        return Row(float("nan"), float("nan"), float("-inf"), float("-inf"),
                   css._turnover_per_year(turn_per_day, n_days), switches)
    return Row(
        mh._apy(net),
        mh._mdd(net),
        mh._calmar(net),
        mh._calmar(net) - base_calmar,
        css._turnover_per_year(turn_per_day, n_days),
        switches,
    )


def equal_weight_reference(book_rets: BookRets, n_dates: int, cost_bps: float) -> Row:
    """The registry's standing baseline: equal weight, rebalanced daily."""
    sc = cit.score(cit.scheduled_history(book_rets, n_dates, "eq", range(1, n_dates)),
                   book_rets, switches=n_dates - 2)
    net = sc.net(cost_bps)
    return Row(mh._apy(net), mh._mdd(net), mh._calmar(net), 0.0,
               sc.turnover_per_year(len(net)), sc.switches)


def _f(x: float, w: int = 8, p: int = 2, pct: bool = False) -> str:
    if x != x or math.isinf(x):
        return f"{'n/a':>{w}}"
    return f"{x*100:>{w-1}.{p}f}%" if pct else f"{x:>{w}.{p}f}"


def _sd(xs: Sequence[float]) -> float:
    xs = [x for x in xs if x == x and not math.isinf(x)]
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


# ───────────────────────────── idea PSF ──────────────────────────────────────────
def run_psf(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    title: str,
    k_grid: Sequence[int] = K_GRID,
    cost_bps: float = CONVENTION_COST,
) -> Dict[str, dict]:
    n_dates = len(dates)
    n_slots = n_dates - 1
    ret_dates = list(dates[1:])
    base = equal_weight_reference(book_rets, n_dates, cost_bps)
    out: Dict[str, dict] = {"baseline": base, "arms": {}}

    print("=" * 100)
    print(f"PSF — Periodic Schedule Frontier   [{title}]   c={cost_bps:g} bps   [bt] L0 advisory")
    print("=" * 100)
    print(f"  panel: {len(book_rets)} books x {n_dates} days  {dates[0]}..{dates[-1]}")
    print(f"  equal-weight baseline: netAPY {base.apy*100:.2f}%  maxDD {base.mdd*100:.2f}%  "
          f"Calmar {base.calmar:.2f}  TO/yr {base.to:.2f}")
    print()

    for mode, label in ARMS:
        fam_by_k: Dict[int, List[cit.Scored]] = {}
        print(f"1. {label} — every phase of every period, EXHAUSTIVE (c={cost_bps:g} bps)")
        print(f"   {'k':>4} {'phases':>7} {'trades':>7} {'TO/yr':>7} "
              f"{'dCal min':>9} {'med':>9} {'max':>9} {'spread':>8} "
              f"{'netAPY med':>11} {'maxDD med':>10}")
        rows_by_k: Dict[int, List[Row]] = {}
        for k in k_grid:
            fam = phase_family(book_rets, n_dates, mode, k)
            fam_by_k[k] = fam
            rows = [measure(s.net(cost_bps), s.turns, len(s.gross), base.calmar, s.switches)
                    for s in fam]
            rows_by_k[k] = rows
            dcals = [r.dcal for r in rows]
            finite = [d for d in dcals if not math.isinf(d)]
            lo = min(finite) if finite else float("-inf")
            hi = max(finite) if finite else float("-inf")
            med = statistics.median(finite) if finite else float("-inf")
            print(f"   {k:>4} {len(fam):>7} {statistics.median([r.switches for r in rows]):>7.0f} "
                  f"{statistics.median([r.to for r in rows]):>7.2f} "
                  f"{_f(lo, 9):>9} {_f(med, 9):>9} {_f(hi, 9):>9} "
                  f"{_f(hi - lo, 8) if finite else 'n/a':>8} "
                  f"{_f(statistics.median([r.apy for r in rows if r.apy == r.apy] or [float('nan')]), 11, 2, pct=True)} "
                  f"{_f(statistics.median([r.mdd for r in rows if r.mdd == r.mdd] or [float('nan')]), 10, 2, pct=True)}")

        # THE ratio the record exists for: is k a knob, or is the phase a coin?
        medians = []
        within = []
        for k in k_grid:
            ds = [r.dcal for r in rows_by_k[k] if not math.isinf(r.dcal)]
            if ds:
                medians.append(statistics.median(ds))
            if k > 1 and len(ds) > 1:
                within.append(max(ds) - min(ds))
        across = (max(medians) - min(medians)) if medians else float("nan")
        within_med = statistics.median(within) if within else float("nan")
        print(f"   → SPREAD ACROSS k (max-min of per-k medians): {across:+.2f} dCalmar")
        print(f"   → SPREAD WITHIN k (median over k>1 of max-min across phases): {within_med:+.2f}")
        verdict = ("phase COIN dominates the k knob" if within_med > across
                   else "k knob dominates the phase coin")
        print(f"   → {verdict}")
        print()
        out["arms"][mode] = {
            "rows_by_k": rows_by_k, "fam_by_k": fam_by_k,
            "spread_across_k": across, "spread_within_k": within_med,
        }
    out["ret_dates"] = ret_dates
    out["n_slots"] = n_slots
    return out


# ───────────────────────────── idea PLD ──────────────────────────────────────────
def run_pld(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    title: str,
    k_grid: Sequence[int] = K_GRID,
    cost_bps: float = CONVENTION_COST,
) -> Dict[str, dict]:
    n_dates = len(dates)
    base = psf["baseline"]
    print("=" * 100)
    print(f"PLD — Phase-Laddered Deployment   [{title}]   c={cost_bps:g} bps   [bt] L0 advisory")
    print("=" * 100)
    print("  k tranches of 1/k capital, one per phase. Equity = arithmetic mean of the phase")
    print("  equities; it is a DETERMINED function of runs above, with nothing in it to fit.")
    print("  It can never beat the best phase — only remove the worst.")
    print()
    result: Dict[str, dict] = {}
    for mode, label in ARMS:
        rows_by_k = psf["arms"][mode]["rows_by_k"]
        fam_by_k = psf["arms"][mode]["fam_by_k"]
        print(f"2. {label}")
        print(f"   {'k':>4} {'TO/yr lad':>10} {'TO/yr med φ':>12} "
              f"{'lad netAPY':>11} {'lad maxDD':>10} {'lad Cal':>8} {'lad dCal':>9} "
              f"{'φ worst':>9} {'φ med':>9} {'φ best':>9} {'lad vs med':>11}")
        per_k = {}
        for k in k_grid:
            fam = fam_by_k[k]
            lad = ladder_at_cost(fam, cost_bps)
            n_days = len(lad.net)
            lrow = measure(lad.net, lad.turn_per_day, n_days, base.calmar, -1)
            ds = sorted(r.dcal for r in rows_by_k[k] if not math.isinf(r.dcal))
            worst = ds[0] if ds else float("nan")
            best = ds[-1] if ds else float("nan")
            med = statistics.median(ds) if ds else float("nan")
            to_med = statistics.median([r.to for r in rows_by_k[k]])
            print(f"   {k:>4} {lrow.to:>10.2f} {to_med:>12.2f} "
                  f"{_f(lrow.apy, 11, 2, pct=True)} {_f(lrow.mdd, 10, 2, pct=True)} "
                  f"{_f(lrow.calmar, 8)} {_f(lrow.dcal, 9)} "
                  f"{_f(worst, 9)} {_f(med, 9)} {_f(best, 9)} {_f(lrow.dcal - med, 11)}")
            per_k[k] = {"ladder": lrow, "worst": worst, "median": med, "best": best,
                        "ladder_obj": lad}
        result[mode] = per_k
        print()
    return result


# ───────────────────── control: random schedules of the same count ───────────────
def run_random_control(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    modes: Sequence[str],
    k_values: Sequence[int],
    cost_bps: float = CONVENTION_COST,
    seeds: Sequence[int] = CONTROL_SEEDS,
) -> Dict[Tuple[str, int], dict]:
    """The registry's standing decisive control, applied to the periodic arm itself.

    A periodic schedule is a very particular way of spending a trade budget. If random days
    of the SAME COUNT do as well, then even 'trade every k days' carries no information
    beyond 'trade this many times' — which would be the strongest form of #50's verdict yet.
    """
    n_dates = len(dates)
    base = psf["baseline"]
    print("=" * 100)
    print(f"3. CONTROL — random schedules of the SAME trade count (c={cost_bps:g} bps, "
          f"{len(seeds)} seeds; p floor = {1.0/(len(seeds)+1):.3f})")
    print("=" * 100)
    print(f"   {'arm':<14} {'k':>4} {'trades':>7} {'periodic dCal':>14} "
          f"{'random min':>11} {'med':>9} {'max':>9} {'beat':>6} {'p':>7}")
    out: Dict[Tuple[str, int], dict] = {}
    for mode in modes:
        rows_by_k = psf["arms"][mode]["rows_by_k"]
        for k in k_values:
            rows = rows_by_k[k]
            ds = [r.dcal for r in rows if not math.isinf(r.dcal)]
            real = statistics.median(ds) if ds else float("nan")
            n_switch = int(statistics.median([r.switches for r in rows]))
            rnd: List[float] = []
            for seed in seeds:
                days = cit.random_switch_days(n_dates - 1, n_switch, seed)
                sc = cit.score(cit.scheduled_history(book_rets, n_dates, mode, days),
                               book_rets, switches=len(days))
                rnd.append(measure(sc.net(cost_bps), sc.turns, len(sc.gross),
                                   base.calmar, len(days)).dcal)
            finite = [d for d in rnd if not math.isinf(d)]
            beat = sum(1 for d in rnd if d > real)
            p = (beat + 1) / (len(rnd) + 1)
            lo = min(finite) if finite else float("nan")
            hi = max(finite) if finite else float("nan")
            md = statistics.median(finite) if finite else float("nan")
            print(f"   {mode:<14} {k:>4} {n_switch:>7} {_f(real, 14)} "
                  f"{_f(lo, 11)} {_f(md, 9)} {_f(hi, 9)} {beat:>4}/{len(rnd):<2} {p:>7.3f}")
            out[(mode, k)] = {"periodic": real, "random": rnd, "beat": beat, "p": p}
    print()
    return out


def run_random_ladder_control(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    pld: Dict[str, dict],
    modes: Sequence[str],
    k_values: Sequence[int],
    cost_bps: float = CONVENTION_COST,
    seeds: Sequence[int] = CONTROL_SEEDS,
) -> Dict[Tuple[str, int], dict]:
    """THE control that decides what PLD actually is.

    The periodic ladder does two things at once: it spreads capital over k tranches (a
    DIVERSIFICATION in time) and it spaces those tranches evenly and disjointly (a
    PERIODICITY). A ladder of k RANDOM schedules of the same per-tranche count keeps the
    first and destroys the second. If it scores the same, the finding is 'tranching', and
    calling it 'periodic' would be selling the wrong mechanism.
    """
    n_dates = len(dates)
    n_slots = n_dates - 1
    base = psf["baseline"]
    print("=" * 100)
    print(f"3b. CONTROL — RANDOM ladder: k tranches, each on random days of the same count "
          f"({len(seeds)} seeds)")
    print("=" * 100)
    print(f"   {'arm':<14} {'k':>4} {'per-tranche':>12} {'periodic lad':>13} "
          f"{'random min':>11} {'med':>9} {'max':>9} {'beat':>6} {'p':>7}")
    out: Dict[Tuple[str, int], dict] = {}
    for mode in modes:
        for k in k_values:
            if k == 1:
                continue
            real = pld[mode][k]["ladder"].dcal
            n_switch = int(statistics.median(
                [r.switches for r in psf["arms"][mode]["rows_by_k"][k]]))
            band: List[float] = []
            for seed in seeds:
                fam = []
                for i in range(k):
                    days = cit.random_switch_days(n_slots, n_switch, seed * 1000 + i)
                    fam.append(cit.score(
                        cit.scheduled_history(book_rets, n_dates, mode, days),
                        book_rets, switches=len(days)))
                lad = ladder_at_cost(fam, cost_bps)
                band.append(measure(lad.net, lad.turn_per_day, len(lad.net),
                                    base.calmar, -1).dcal)
            finite = [d for d in band if not math.isinf(d)]
            beat = sum(1 for d in band if d > real)
            p = (beat + 1) / (len(band) + 1)
            print(f"   {mode:<14} {k:>4} {n_switch:>12} {_f(real, 13)} "
                  f"{_f(min(finite) if finite else float('nan'), 11)} "
                  f"{_f(statistics.median(finite) if finite else float('nan'), 9)} "
                  f"{_f(max(finite) if finite else float('nan'), 9)} "
                  f"{beat:>4}/{len(band):<2} {p:>7.3f}")
            out[(mode, k)] = {"periodic_ladder": real, "random_ladders": band,
                              "beat": beat, "p": p}
    print()
    return out


def static_tilt_history(cand: "cit.Candidates") -> css.WeightHistory:
    """The IN-SAMPLE twin: the mean of ALL candidate vectors, held from day one.

    In March it knows which books were good in December. #67 STT showed this reads as a
    triumph by construction and reverses out of sample; it is an upper bound, never a rule,
    and every table that prints it says so.
    """
    books = cand.book_ids
    n = len(cand.weights)
    mean_w = {b: sum(w.get(b, 0.0) for w in cand.weights) / n for b in books}
    return [dict(mean_w) for _ in range(n)]


def expanding_tilt_history(cand: "cit.Candidates") -> css.WeightHistory:
    """The CAUSAL twin: the running mean of the candidates seen so far.

    Day t uses candidates 1..t and nothing later, so somebody could have run it. Keeping
    this a NAMED function next to its in-sample sibling is deliberate: the two differ by
    exactly one word in the code and by everything in what they mean, and a test that
    re-implements either one locally cannot tell them apart (it would compare its own copy
    with itself and stay green while the harness used the wrong twin).
    """
    books = cand.book_ids
    run = {b: 0.0 for b in books}
    out: css.WeightHistory = []
    for t, w in enumerate(cand.weights, start=1):
        for b in books:
            run[b] += w.get(b, 0.0)
        out.append({b: run[b] / t for b in books})
    return out


def run_static_tilt_control(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    pld: Dict[str, dict],
    modes: Sequence[str],
    k_values: Sequence[int],
    cost_bps: float = CONVENTION_COST,
) -> Dict[str, dict]:
    """The degenerate explanation that has to be ruled out before PLD may be called anything.

    A ladder of k tranches holds, in aggregate, the average of k weight vectors that were
    each chosen up to k days apart. As k grows this converges on the TIME-AVERAGE of the
    arm's candidate weights — a STANDING TILT with almost no turnover. #67 STT showed on a
    different machine that such a tilt reads as a triumph in-sample and reverses out of it,
    and that the registry's habit of charging it ZERO turnover is itself wrong.

    Two twins are therefore scored next to every ladder:
      STATIC (in-sample)  mean of ALL candidate vectors, held from day one. It knows in March
                          which books were good in December — an upper bound, not a rule, and
                          it is labelled that way wherever it is printed.
      EXPANDING (causal)  running mean of candidates seen SO FAR, rebalanced daily. A rule
                          somebody could actually run, and it pays its own toll.
    """
    n_dates = len(dates)
    base = psf["baseline"]
    print("=" * 100)
    print(f"3c. CONTROL — is the ladder just a STANDING TILT? (c={cost_bps:g} bps)")
    print("=" * 100)
    print(f"   {'arm':<14} {'k':>4} {'ladder dCal':>12} {'ladder TO':>10} "
          f"{'STATIC* dCal':>13} {'STATIC* TO':>11} {'EXPAND dCal':>12} {'EXPAND TO':>10}")
    print("   * STATIC is IN-SAMPLE by construction (#67): an upper bound, never a rule.")
    out: Dict[str, dict] = {}
    for mode in modes:
        cand = cit.candidates_for(book_rets, n_dates, mode)
        n = len(cand.weights)
        s_static = cit.score(static_tilt_history(cand), book_rets, switches=0)
        s_exp = cit.score(expanding_tilt_history(cand), book_rets, switches=n - 1)
        r_static = measure(s_static.net(cost_bps), s_static.turns, len(s_static.gross),
                           base.calmar, 0)
        r_exp = measure(s_exp.net(cost_bps), s_exp.turns, len(s_exp.gross), base.calmar, n - 1)
        best_k = max(k_values, key=lambda k: pld[mode][k]["ladder"].dcal)
        lrow = pld[mode][best_k]["ladder"]
        print(f"   {mode:<14} {best_k:>4} {_f(lrow.dcal, 12)} {lrow.to:>10.2f} "
              f"{_f(r_static.dcal, 13)} {r_static.to:>11.2f} "
              f"{_f(r_exp.dcal, 12)} {r_exp.to:>10.2f}   (best ladder k of the grid)")
        out[mode] = {"static": r_static, "expanding": r_exp,
                     "best_k": best_k, "static_scored": s_static, "exp_scored": s_exp}
    print()

    # Both axes, side by side with the tail — the registry's honesty rule.
    print(f"   {'arm':<14} {'twin':<20} {'netAPY':>9} {'maxDD':>9} {'Calmar':>8} "
          f"{'dCal':>8} {'TO/yr':>8} {'train dCal':>11} {'test dCal':>10}")
    ret_dates = psf["ret_dates"]
    eq = cit.score(cit.scheduled_history(book_rets, n_dates, "eq", range(1, n_dates)),
                   book_rets, switches=n_dates - 2)
    eq_tr, eq_te = cit.split_net(eq.net(cost_bps), ret_dates)
    base_tr, base_te = mh._calmar(eq_tr), mh._calmar(eq_te)
    for mode in modes:
        for name, sc, row in (("STATIC (in-sample*)", out[mode]["static_scored"], out[mode]["static"]),
                              ("EXPANDING (causal)", out[mode]["exp_scored"], out[mode]["expanding"])):
            a, b = cit.split_net(sc.net(cost_bps), ret_dates)
            print(f"   {mode:<14} {name:<20} {_f(row.apy, 9, 2, pct=True)} "
                  f"{_f(row.mdd, 9, 2, pct=True)} {_f(row.calmar, 8)} {_f(row.dcal, 8)} "
                  f"{row.to:>8.2f} {mh._calmar(a) - base_tr:>+11.2f} "
                  f"{mh._calmar(b) - base_te:>+10.2f}")
    print()
    return out


def run_tilt_identity_control(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    tilt: Dict[str, dict],
    modes: Sequence[str],
    cost_bps: float = CONVENTION_COST,
    relabel_samples: int = 200,
) -> Dict[str, dict]:
    """Does the causal tilt know WHICH books, or only HOW FLAT to be?

    RELABEL is the right control for a near-constant weight history and the only one that
    is: it applies ONE fixed permutation of book identities to every day, so the per-day
    multiset of weights — and therefore the turnover, exactly — is untouched. If a
    relabelled tilt scores the same, the vector carries no information about the books and
    the whole effect is 'be flatter than the rule', which is a statement about CONCENTRATION
    and belongs to #46, not here.

    ROTATE (#80's other control) is deliberately reported and deliberately discounted: a
    circular shift of an almost-constant history is almost the identity, so it cannot fail.
    It is printed so that nobody reads its silence as evidence.
    """
    n_dates = len(dates)
    base = psf["baseline"]
    ret_dates = psf["ret_dates"]
    print("=" * 100)
    print(f"3d. CONTROL — RELABEL the causal tilt ({relabel_samples} sampled permutations, "
          f"turnover preserved EXACTLY)")
    print("=" * 100)
    print(f"   {'arm':<14} {'real dCal':>10} {'relabel min':>12} {'med':>9} {'max':>9} "
          f"{'beat':>8} {'p':>7} {'rotate dCal':>12}")
    out: Dict[str, dict] = {}
    for mode in modes:
        sc = tilt[mode]["exp_scored"]
        real = tilt[mode]["expanding"].dcal
        books = sorted(book_rets)
        band: List[float] = []
        for perm in cit.relabel_permutations(books, relabel_samples):
            h2 = css._relabel(sc.hist, perm, books)
            s2 = cit.score(h2, book_rets, switches=-1)
            band.append(measure(s2.net(cost_bps), s2.turns, len(s2.gross), base.calmar, -1).dcal)
        rot = css._rotate(sc.hist, css.ROTATION_STEP)
        s_rot = cit.score(rot, book_rets, switches=-1)
        rot_d = measure(s_rot.net(cost_bps), s_rot.turns, len(s_rot.gross), base.calmar, -1).dcal
        finite = [d for d in band if not math.isinf(d)]
        beat = sum(1 for d in band if d > real)
        p = (beat + 1) / (len(band) + 1)
        print(f"   {mode:<14} {_f(real, 10)} {_f(min(finite), 12)} "
              f"{_f(statistics.median(finite), 9)} {_f(max(finite), 9)} "
              f"{beat:>5}/{len(band):<3} {p:>7.3f} {_f(rot_d, 12)}")
        out[mode] = {"real": real, "band": band, "beat": beat, "p": p, "rotate": rot_d}
    print()

    print("   TILT STABILITY — is the vector learned on TRAIN the vector TEST wants?")
    print(f"   {'arm':<14} {'L1(train,test)':>15} {'top-3 books by TRAIN weight'}")
    for mode in modes:
        cand = cit.candidates_for(book_rets, n_dates, mode)
        books = cand.book_ids
        cut = datetime.date.fromisoformat(SPLIT_DATE)
        tr = [w for w, d in zip(cand.weights, ret_dates) if d <= cut]
        te = [w for w, d in zip(cand.weights, ret_dates) if d > cut]
        wtr = {b: sum(w.get(b, 0.0) for w in tr) / len(tr) for b in books}
        wte = {b: sum(w.get(b, 0.0) for w in te) / len(te) for b in books}
        l1 = sum(abs(wtr[b] - wte[b]) for b in books)
        top = sorted(books, key=lambda b: -wtr[b])[:3]
        print(f"   {mode:<14} {l1:>15.3f}   " +
              ", ".join(f"{b} {wtr[b]*100:.1f}%→{wte[b]*100:.1f}%" for b in top))
    print()
    return out


def shrinkage_history(cand: "cit.Candidates", alpha: float) -> css.WeightHistory:
    """w = (1-alpha)*equal_weight + alpha*today's candidate, rebalanced DAILY.

    A pure CONCENTRATION knob: alpha=0 is equal weight, alpha=1 is today's arm, and nothing
    in between averages anything over TIME. It exists to answer the only question that can
    still demote the causal tilt to a re-labelled old finding.
    """
    books = cand.book_ids
    flat = 1.0 / len(books)
    return [
        {b: (1.0 - alpha) * flat + alpha * w.get(b, 0.0) for b in books}
        for w in cand.weights
    ]


def run_shrinkage_control(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    tilt: Dict[str, dict],
    modes: Sequence[str],
    cost_bps: float = CONVENTION_COST,
    alphas: Sequence[float] = (0.0, 0.25, 0.5, 0.75, 1.0),
) -> Dict[str, dict]:
    """Is the causal tilt a TIME-AVERAGE, or just a CONCENTRATION setting wearing a clock?

    The tilt is flatter than the rule and closer to equal weight; #46 CONC already owns the
    axis 'how concentrated should we be'. If some point on the straight line between equal
    weight and today's arm reproduces the tilt's numbers, then averaging over time explains
    nothing and this record must say so instead of naming a new object.

    The line is NOT a free parameter here: every alpha is printed, and the tilt has to beat
    the WHOLE line, not the average of it.
    """
    n_dates = len(dates)
    base = psf["baseline"]
    ret_dates = psf["ret_dates"]
    eq = cit.score(cit.scheduled_history(book_rets, n_dates, "eq", range(1, n_dates)),
                   book_rets, switches=n_dates - 2)
    eq_tr, eq_te = cit.split_net(eq.net(cost_bps), ret_dates)
    base_tr, base_te = mh._calmar(eq_tr), mh._calmar(eq_te)

    print("=" * 100)
    print(f"3e. CONTROL — the SHRINKAGE line: (1-α)·equal-weight + α·today's arm, daily "
          f"(c={cost_bps:g} bps)")
    print("=" * 100)
    print(f"   {'arm':<8} {'α':>6} {'netAPY':>9} {'maxDD':>9} {'Calmar':>8} {'dCal':>8} "
          f"{'TO/yr':>8} {'train':>8} {'test':>8}")
    out: Dict[str, dict] = {}
    for mode in modes:
        cand = cit.candidates_for(book_rets, n_dates, mode)
        best = float("-inf")
        for a in alphas:
            sc = cit.score(shrinkage_history(cand, a), book_rets, switches=-1)
            row = measure(sc.net(cost_bps), sc.turns, len(sc.gross), base.calmar, -1)
            tr, te = cit.split_net(sc.net(cost_bps), ret_dates)
            print(f"   {mode:<8} {a:>6.2f} {_f(row.apy, 9, 2, pct=True)} "
                  f"{_f(row.mdd, 9, 2, pct=True)} {_f(row.calmar, 8)} {_f(row.dcal, 8)} "
                  f"{row.to:>8.2f} {mh._calmar(tr) - base_tr:>+8.2f} "
                  f"{mh._calmar(te) - base_te:>+8.2f}")
            best = max(best, row.dcal)
        t = tilt[mode]["expanding"]
        verdict = ("tilt BEATS the whole line" if t.dcal > best
                   else "the line REACHES the tilt — time-averaging explains nothing")
        print(f"   {mode:<8} {'TILT':>6} {_f(t.apy, 9, 2, pct=True)} {_f(t.mdd, 9, 2, pct=True)} "
              f"{_f(t.calmar, 8)} {_f(t.dcal, 8)} {t.to:>8.2f}   → {verdict}")
        out[mode] = {"best_alpha_dcal": best, "tilt_dcal": t.dcal}
        print()
    return out


def run_ladder_cost_grid(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    modes: Sequence[str],
    k_values: Sequence[int],
) -> None:
    """Is the ladder's advantage FISCAL (it trades less) or STRUCTURAL (it holds better)?

    #80's separation, applied to PLD. At c=0 turnover is free, so anything left at zero cost
    is a property of WHAT is held, not of what it cost to get there. A ladder that only wins
    at c=96 is #50's frequency verdict in a new coat.
    """
    n_dates = len(dates)
    print("=" * 100)
    print("6. FISCAL vs STRUCTURAL — ladder dCalmar across the cost grid (#80's separation)")
    print("=" * 100)
    for mode in modes:
        print(f"   {mode:<14}" + "".join(f"{('c=' + str(c)):>9}" for c in COST_GRID))
        for k in k_values:
            fam = psf["arms"][mode]["fam_by_k"][k]
            cells = []
            for c in COST_GRID:
                base_c = equal_weight_reference(book_rets, n_dates, c)
                lad = ladder_at_cost(fam, c)
                cells.append(measure(lad.net, lad.turn_per_day, len(lad.net),
                                     base_c.calmar, -1).dcal)
            print(f"     k={k:<11}" + "".join(_f(x, 9) for x in cells))
    print()


# ───────────────────────── train / test and break-even ───────────────────────────
def run_split(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    pld: Dict[str, dict],
    modes: Sequence[str],
    k_grid: Sequence[int] = K_GRID,
    cost_bps: float = CONVENTION_COST,
) -> None:
    ret_dates = psf["ret_dates"]
    n_dates = len(dates)
    print("=" * 100)
    print(f"4. TRAIN / TEST (split {SPLIT_DATE}) — does any k survive the half it never saw?")
    print("=" * 100)
    eq = cit.score(cit.scheduled_history(book_rets, n_dates, "eq", range(1, n_dates)),
                   book_rets, switches=n_dates - 2)
    eq_tr, eq_te = cit.split_net(eq.net(cost_bps), ret_dates)
    base_tr, base_te = mh._calmar(eq_tr), mh._calmar(eq_te)
    print(f"   equal-weight: train Calmar {base_tr:.2f} (netAPY {mh._apy(eq_tr)*100:.2f}%)  ·  "
          f"test Calmar {base_te:.2f} (netAPY {mh._apy(eq_te)*100:.2f}%)")
    for mode in modes:
        print(f"   {mode}:")
        print(f"     {'k':>4} {'φ-med train':>12} {'φ-med test':>11} "
              f"{'ladder train':>13} {'ladder test':>12} {'lad test APY':>13}")
        for k in k_grid:
            fam = psf["arms"][mode]["fam_by_k"][k]
            trs, tes = [], []
            for s in fam:
                a, b = cit.split_net(s.net(cost_bps), ret_dates)
                trs.append(mh._calmar(a) - base_tr)
                tes.append(mh._calmar(b) - base_te)
            lad = pld[mode][k]["ladder_obj"]
            la, lb = cit.split_net(lad.net, ret_dates)
            print(f"     {k:>4} {statistics.median(trs):>+12.2f} {statistics.median(tes):>+11.2f} "
                  f"{mh._calmar(la) - base_tr:>+13.2f} {mh._calmar(lb) - base_te:>+12.2f} "
                  f"{mh._apy(lb)*100:>12.2f}%")
    print()


def run_breakeven(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    psf: Dict[str, dict],
    modes: Sequence[str],
    k_grid: Sequence[int] = K_GRID,
) -> None:
    """Break-even of the MEDIAN phase — the honest cell, because the ladder's toll is
    non-linear in cost while a single phase's is exactly linear."""
    n_dates = len(dates)
    print("=" * 100)
    print("5. BREAK-EVEN of the median phase (bps of one-way turnover; convention = 96)")
    print("=" * 100)
    print(f"   {'arm':<14}" + "".join(f"{('k=' + str(k)):>12}" for k in k_grid))
    for mode in modes:
        cells = []
        for k in k_grid:
            fam = psf["arms"][mode]["fam_by_k"][k]
            # median phase by dCalmar at the convention cost, then its own break-even
            base = equal_weight_reference(book_rets, n_dates, 0.0)
            scored = sorted(
                fam,
                key=lambda s: measure(s.net(CONVENTION_COST), s.turns, len(s.gross),
                                      psf["baseline"].calmar, s.switches).dcal,
            )
            med_phase = scored[len(scored) // 2]
            verdict, _d0 = css._breakeven_cost(med_phase.gross, med_phase.turns, base.calmar)
            cells.append(verdict)
        print(f"   {mode:<14}" + "".join(f"{c:>12}" for c in cells))
    print()


# ───────────────────────────── entry point ───────────────────────────────────────
def main(argv: Sequence[str] = ()) -> int:
    ap = argparse.ArgumentParser(description="PSF / PLD — advisory backtest, writes nothing")
    ap.add_argument("--fixture", action="store_true",
                    help="run on the code fixture instead of the real panel (anchor mode)")
    ap.add_argument("--quick", action="store_true", help="short k grid, for smoke runs")
    args = ap.parse_args(list(argv))

    if args.fixture:
        dates, book_rets = cit.load_fixture_panel()
        title = "FIXTURE (anchor)"
    else:
        dates, book_rets = cit.load_real_panel()
        title = "REAL aggressive-lab panel"

    k_grid = (1, 5, 20) if args.quick else K_GRID
    psf = run_psf(dates, book_rets, title, k_grid)
    pld = run_pld(dates, book_rets, psf, title, k_grid)
    modes = [m for m, _ in ARMS]
    run_random_control(dates, book_rets, psf, modes, k_grid)
    run_random_ladder_control(dates, book_rets, psf, pld, modes, k_grid)
    tilt = run_static_tilt_control(dates, book_rets, psf, pld, modes, k_grid)
    run_tilt_identity_control(dates, book_rets, psf, tilt, modes)
    run_shrinkage_control(dates, book_rets, psf, tilt, modes)
    run_split(dates, book_rets, psf, pld, modes, k_grid)
    run_breakeven(dates, book_rets, psf, modes, k_grid)
    run_ladder_cost_grid(dates, book_rets, psf, modes, k_grid)
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence=L0 [bt]  "
          "capital not moved · nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
