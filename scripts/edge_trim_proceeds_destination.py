#!/usr/bin/env python3
"""
scripts/edge_trim_proceeds_destination.py — registry ideas TPD + BLO (working names)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the dashboard or the fleet. Reads the aggressive-lab panel READ-ONLY. Capital is not
moved. No module is built and no agent is deployed here.

Working names TPD / BLO. The registry NUMBERS are claimed at DELIVERY, never at writing time
(REGISTRY-NUMBER-RULE, guard spa_core/tests/test_edge_registry_numbers.py).


THE QUESTION, WHICH #96 CREATED AND DID NOT ASK
===============================================
#96 PBA ended the overlay branch with a number that now governs the whole family:

    the mandatory benchmark — capped buy-and-hold at the T2 ceiling of 20 %/book — returns
    26.61 % APY at 3.60 % drawdown, Calmar 7.39, and EVERY overlay policy measured, including
    the deployed organ (3.31), sits more than 3.9 Calmar BELOW it.

That verdict is only as solid as the benchmark. And the benchmark is not a passive object:
every time the cap BINDS it sells part of the winner, and that money has to go SOMEWHERE. The
deployed implementation (`edge_overlay_domain_admissibility.capped_buy_and_hold` →
`trim_to_cap`) puts it back into the under-cap books PRO RATA TO THEIR CURRENT WEIGHT. That
choice is nowhere in #86 or #96. It was never presented as a result, and it was never
presented as a convention either — it is simply the first thing the code does.

This is exactly the class #92 CVD named: a CONVENTION quoted as a MEASUREMENT. #92 found it on
the cost axis. Nobody has looked for it on the ALLOCATION axis, and here it sits inside the one
number the branch is now measured against.

  TPD  Trim-Proceeds Destination.  How much of 7.39 is a property of the PANEL, and how much
       is a property of that unwritten choice? Same books, same cap, same toll, same days —
       only the destination of the trimmed capital changes.

  BLO  Benchmark Leave-One-Out.  On how many books does 7.39 actually stand? If dropping one
       name collapses it, then "the overlay layer loses by 3.9 Calmar" is a statement about
       that one name, not about the layer.

Neither dial is anywhere in the registry. #46 CONC priced the concentration LIMIT; #49/#50/#84
priced WHEN you rebalance; #85/#86/#87 chose the WEIGHTS. Nothing has asked where the money
GOES at the moment the ceiling forces a sale, and nothing has asked how deep the bench is under
the bar itself.


MECHANISM (five destinations, all causal, none of them forecasts anything)
--------------------------------------------------------------------------
On any day the cap binds, `excess` = the sum of over-cap weight. Every over-cap book is set to
`cap`. `excess` then goes to:

  prorata  — split across the strictly-under-cap books in proportion to their current weight.
             THIS IS THE DEPLOYED CONVENTION and therefore the positive control of this file:
             §0 asserts it is BITWISE identical to the benchmark #96 published.
  equal    — split equally across the strictly-under-cap books (tilts harder to the small ones).
  to_min   — all of it into the single smallest under-cap book (maximum anti-momentum).
  to_max   — all of it into the largest under-cap book (momentum inside the ceiling).
  cash     — it leaves the risk book into a 0 %-yield cash sleeve and is NEVER redeployed.
             The honest "we do not force-buy anything" convention.

Redistribution is iterated to a fixed point and the cap invariant is RE-CHECKED afterwards;
a breached benchmark is refused, not printed (the rule `capped_buy_and_hold` already enforces
and this file keeps verbatim). Convergence is not assumed: receivers must be STRICTLY under the
cap, so a book pushed to the cap can never receive again, so the at-cap set only grows.

TOLL. The deployed benchmark charges `2 × cost × traded` — both legs, sell and buy. That is
kept for all four redistributing destinations. `cash` HAS NO BUY LEG and is therefore charged
ONE leg — and because that is itself a choice, the two-leg variant of `cash` is printed beside
it as a sensitivity row rather than argued about.

CASH SLEEVE. Cash is part of NAV, earns exactly 0 %, and the cap is not applied to it (it is
not a book). A cash yield of 0 is conservative and is a CONVENTION, not a measurement — the
tree's stable sleeve is not zero, and quoting one would put an invented number in a benchmark.


THE PREDICTIONS, WRITTEN DOWN BEFORE THE FIRST NUMBER WAS PRODUCED
  P1. The destination matters materially — more than 1.0 Calmar between the best and the worst
      of the five — because this panel contains one book with an extreme ratio
      (pendle_yt_susde, ~105 % APY at ~0.3 % drawdown in the #97 roster) against which the cap
      must bind almost every day. Where its trimmings land is then a first-order decision, not
      a detail.
  P2. Ordering: to_max >= prorata > equal > to_min on Calmar, because the panel contains an
      outright loser (eth_directional, −26 % APY raw) and every destination that tilts toward
      the SMALLEST weight is a rule that systematically buys it.
  P3. cash has the lowest APY of the five and the lowest drawdown; its Calmar is genuinely
      uncertain in advance and is the one cell of §1 that could be a real "risk lower" finding
      rather than an accounting artefact.
  P4. OUT OF SAMPLE the ranking is UNSTABLE. A destination is a bet on which book mean-reverts,
      and this panel is 852 days with one regime. So the expected honest verdict of §2 is
      "the benchmark is convention-dependent", not "here is a new edge".
  P5. BLO: removing pendle_yt_susde costs the benchmark more than 2.0 Calmar, and no other
      single removal costs more than 1.0. Drawdown barely moves under any removal, because the
      panel's drawdown is driven by eth_directional and pendle_pt_levered, not by the book that
      carries the return.

Predictions are recorded so this entry cannot become a post-hoc story. A prediction that is
WRONG is reported as wrong; that is the point of writing it down.


HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. Nothing here moves capital,
    and nothing here is a live claim.
  * every cost quoted is a CONVENTION, not a measurement (#92/#93 stand unchanged): no
    proportional toll in this tree carries a date or a source. Numbers are printed AT NAMED
    CONVENTIONS and never as "the cost". Gas in dollars per leg is not modelled — at pilot
    sizes it dominates both axes (#91), and destinations differ in the NUMBER OF LEGS they
    trade, so a per-leg dollar cost would not be neutral between them. That is a stated hole,
    not a solved problem.
  * the panel is REGENERATED, not appended (#32 caveat (е)): numbers reproduce only against
    the panel files of the date printed in the header.
  * the whole panel is 852 days of ONE broad regime, and the 2025-07…2026-07 test half was
    quiet. No destination is validated against a crisis here.
  * gap risk (exploit, instant depeg, drained exit) is not addressed by any allocation rule and
    stays in the tier tail, exactly as in every entry of this registry.
  * #86 is NOT overturned by this file. Capped buy-and-hold remains the family's benchmark;
    what is measured here is how much of its published number is the panel and how much is the
    convention underneath it.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_gross_to_net_toll as gtn  # noqa: E402  (real-panel loader, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 APY/maxDD/Calmar, reused verbatim)
import edge_overlay_domain_admissibility as oda  # noqa: E402  (#95/#96, the benchmark itself)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: The five destinations. `prorata` is the deployed convention and the positive control.
DESTINATIONS: Tuple[str, ...] = ("prorata", "equal", "to_min", "to_max", "cash")

#: Concentration ceilings. 20 % is the T2 ceiling #86 published; the rest bracket it. A cap
#: that cannot hold the capital is REFUSED and printed as a refusal, never skipped silently.
CAP_GRID: Tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.33)

#: Every proportional toll convention that exists in this tree, in bps. Same list as #95.
CONVENTIONS_BPS: Tuple[int, ...] = (0, 8, 13, 15, 96)

#: The toll the deployed benchmark charges, READ from #95 so this file cannot drift from it.
DEPLOYED_BPS = oda.DEPLOYED_BPS

#: The branch's canonical out-of-sample boundary, unchanged since #79.
SPLIT_DATE = "2025-06-30"

#: Seeds of the RANDOM destination control. Fixed before the first number.
RANDOM_SEEDS: Tuple[int, ...] = (11, 23, 37, 51, 73)

EPS = 1e-15


class Infeasible(ValueError):
    """The ceiling cannot hold this capital under this destination. A refusal, not a number."""


# --------------------------------------------------------------------------------------------
# the mechanism
# --------------------------------------------------------------------------------------------
def redistribute(w: Dict[str, float], cap: float, destination: str) -> Tuple[float, float]:
    """Trim every over-cap weight back to `cap` and send the excess where `destination` says.

    Returns (traded, to_cash). Iterated to a fixed point: one pass can push a receiver over the
    ceiling. Receivers must be STRICTLY under the cap, so a book that reaches the cap can never
    receive again and the at-cap set only grows — that is why this terminates.

    REFUSES (Infeasible) rather than return a portfolio that still breaches the ceiling. A
    silently-breached benchmark is worse than no benchmark, and #86 exists precisely because
    the naive winner was not investable.
    """
    if destination not in DESTINATIONS:
        raise ValueError(f"unknown destination {destination!r}")
    live = list(w)
    traded = 0.0
    to_cash = 0.0
    for _ in range(len(live) + 2):
        over = {b: w[b] - cap for b in live if w[b] > cap + EPS}
        if not over:
            break
        excess = sum(over.values())
        for b in over:
            w[b] = cap
        traded += excess
        if destination == "cash":
            to_cash += excess
            continue
        under = [b for b in live if w[b] < cap - EPS]
        if not under:
            raise Infeasible(
                "every book is at the ceiling and capital is still over-allocated — the cap "
                "cannot hold this portfolio. Refusing rather than printing a breached benchmark.")
        if destination == "prorata":
            base = sum(w[b] for b in under)
            if base <= 0:
                raise Infeasible("no positive weight to receive the trim pro rata")
            for b in under:
                w[b] += excess * w[b] / base
        elif destination == "equal":
            for b in under:
                w[b] += excess / len(under)
        elif destination == "to_min":
            w[min(under, key=lambda b: (w[b], b))] += excess
        elif destination == "to_max":
            w[max(under, key=lambda b: (w[b], b))] += excess
    if max(w.values()) > cap + 1e-9:
        raise Infeasible(
            f"the ceiling was still breached after redistribution (max weight "
            f"{max(w.values()):.4f} > {cap:.2f}) — refusing to print a breached benchmark.")
    return traded, to_cash


def capped_bh(
    book_rets: Dict[str, Sequence[float]],
    live: Sequence[str],
    *,
    cap: float,
    cost: float,
    destination: str = "prorata",
    cash_legs: int = 1,
    trace: Optional[List[float]] = None,
) -> List[float]:
    """Capped buy-and-hold with an EXPLICIT destination for the trim proceeds.

    `destination="prorata"` reproduces `oda.capped_buy_and_hold` BITWISE — asserted in §0 and
    in spa_core/tests/test_edge_trim_proceeds_destination.py, and mutated in the other
    direction so the assertion cannot pass vacuously.

    Toll: two legs (sell + buy) for every redistributing destination, exactly as the deployed
    benchmark charges. `cash` has no buy leg and is charged `cash_legs` (default 1); the
    two-leg variant is printed as a sensitivity row, not argued about.
    """
    live = list(live)
    if destination != "cash" and len(live) * cap < 1.0 - 1e-12:
        raise Infeasible(
            f"a {cap:.0%} cap over {len(live)} books cannot hold 100 % of the capital.")
    n = len(book_rets[live[0]])
    w = {b: 1.0 / len(live) for b in live}
    cash = 0.0
    out = [1.0]
    for i in range(n):
        # cash earns exactly 0 and therefore contributes nothing to the day's return; the
        # weights below are fractions of TOTAL NAV, so the cash fraction simply dilutes.
        r = sum(w[b] * book_rets[b][i] for b in live)
        nav = out[-1] * (1.0 + r)
        if 1.0 + r <= 0:
            out.append(0.0)
            break
        # weights float with the books; the cash sleeve does not move, but its NAV share does
        for b in live:
            w[b] = w[b] * (1.0 + book_rets[b][i]) / (1.0 + r)
        cash = cash / (1.0 + r)
        traded, moved = redistribute(w, cap, destination)
        cash += moved
        if trace is not None:
            trace.append(traded)
        if traded:
            legs = cash_legs if destination == "cash" else 2
            nav *= (1.0 - cost * legs * traded)
        out.append(nav)
    return [out[i + 1] / out[i] - 1.0 for i in range(len(out) - 1) if out[i] > 0]


def capped_bh_random(
    book_rets: Dict[str, Sequence[float]],
    live: Sequence[str],
    *,
    cap: float,
    cost: float,
    seed: int,
) -> List[float]:
    """RANDOM destination control: on each binding pass the excess goes to ONE randomly chosen
    under-cap book. If the winner of §1 is not distinguishable from this cloud, "the destination
    matters" is a statement about noise. Seeded, therefore reproducible."""
    rng = random.Random(seed)
    live = list(live)
    if len(live) * cap < 1.0 - 1e-12:
        raise Infeasible(f"a {cap:.0%} cap over {len(live)} books cannot hold the capital")
    n = len(book_rets[live[0]])
    w = {b: 1.0 / len(live) for b in live}
    out = [1.0]
    for i in range(n):
        r = sum(w[b] * book_rets[b][i] for b in live)
        nav = out[-1] * (1.0 + r)
        if 1.0 + r <= 0:
            out.append(0.0)
            break
        for b in live:
            w[b] = w[b] * (1.0 + book_rets[b][i]) / (1.0 + r)
        traded = 0.0
        for _ in range(len(live) + 2):
            over = {b: w[b] - cap for b in live if w[b] > cap + EPS}
            if not over:
                break
            excess = sum(over.values())
            for b in over:
                w[b] = cap
            traded += excess
            under = [b for b in live if w[b] < cap - EPS]
            if not under:
                raise Infeasible("no receiver under the cap")
            w[under[rng.randrange(len(under))]] += excess
        if max(w.values()) > cap + 1e-9:
            raise Infeasible("ceiling still breached after random redistribution")
        if traded:
            nav *= (1.0 - cost * 2.0 * traded)
        out.append(nav)
    return [out[i + 1] / out[i] - 1.0 for i in range(len(out) - 1) if out[i] > 0]


def metrics(rets: Sequence[float]) -> Tuple[float, float, float]:
    """APY %, maxDD % (negative), Calmar — through #79's functions, reused verbatim."""
    return mh._apy(list(rets)) * 100.0, mh._mdd(list(rets)) * 100.0, mh._calmar(list(rets))


def _key(dest: str, cap: float) -> str:
    """Result-dict key. Explicit, so §5 cannot miss a cell because float repr moved."""
    return f"{dest}@cap{int(round(cap * 1000)):04d}"


def fmt(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def _split_index(dates: Sequence[datetime.date], boundary: str) -> int:
    b = datetime.date.fromisoformat(boundary)
    for i, d in enumerate(dates):
        if d > b:
            return i
    return len(dates)


# --------------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------------
def section0_identity(book_rets, live) -> Dict[str, object]:
    """POSITIVE CONTROL of the whole file: this file's mechanism IS the deployed benchmark.

    Bitwise, on the real panel, at every toll convention, for BOTH conventions the benchmark
    now offers. If either ever stops holding, every number below is about a different portfolio
    than the one `oda` builds, and the file has to stop rather than print a contrast against a
    benchmark it did not reproduce.

    UPDATED 2026-09-03 (owner decision, ADR-218). Before that date `oda.capped_buy_and_hold`
    had ONE convention and this check named it by omission — it compared against the default.
    A default is not a name: once the default moved to `cash`, the same code would silently
    have compared `prorata` against `cash` and reported a difference as a defect of this file.
    Both sides are now SAID OUT LOUD, and both conventions are pinned, which is strictly more
    than was checked before.
    """
    print("\n" + "─" * 100)
    print("0. IDENTITY — each destination must BE the same-named oda convention, bitwise.")
    out: Dict[str, object] = {}
    for dest in (oda.PUBLISHED_CONVENTION, oda.BENCHMARK_CONVENTION):
        for bps in CONVENTIONS_BPS:
            theirs = oda.capped_buy_and_hold(book_rets, live, cap=0.20, cost=bps / 1e4,
                                             destination=dest)
            mine = capped_bh(book_rets, live, cap=0.20, cost=bps / 1e4, destination=dest)
            same = len(theirs) == len(mine) and all(a == b for a, b in zip(theirs, mine))
            out[f"{dest}_bps{bps}"] = same
            print(f"   {dest:>8} · {bps:>3} bps · identical to oda.capped_buy_and_hold: {same}")
            if not same:
                raise SystemExit(
                    "REFUSING: the reimplementation is not the deployed benchmark under "
                    f"{dest!r}. Every contrast below would be against a portfolio oda never "
                    "builds.")
    a, d, c = metrics(capped_bh(book_rets, live, cap=0.20, cost=DEPLOYED_BPS / 1e4))
    out["published"] = {"apy": a, "mdd": d, "calmar": c}
    print(f"   reproduced #96 headline: APY {a:.2f} · maxDD {d:.2f} · Calmar {c:.2f}"
          f"   (published: 26.61 / −3.60 / 7.39, {oda.PUBLISHED_CONVENTION!r} convention)")
    return out


def section1_destinations(book_rets, live) -> Dict[str, object]:
    """TPD §1 — the same panel, the same days, the same toll. Only the destination moves."""
    print("\n" + "─" * 100)
    print("1. TPD — where the trimmed capital goes. Full sample, ALL numbers IN-SAMPLE.")
    print(f"   toll = deployed {DEPLOYED_BPS:.0f} bps; two legs charged, `cash` one leg.")
    print(f"{'cap':>7}" + "".join(f"{d:>21}" for d in DESTINATIONS))
    print(f"{'':>7}" + "".join(f"{'APY / DD / Cal':>21}" for _ in DESTINATIONS))
    print("─" * 100)
    out: Dict[str, object] = {}
    cost = DEPLOYED_BPS / 1e4
    for cap in CAP_GRID:
        row = f"{cap:>6.0%} "
        for dest in DESTINATIONS:
            try:
                a, d, c = metrics(capped_bh(book_rets, live, cap=cap, cost=cost, destination=dest))
                out[_key(dest, cap)] = {"apy": a, "mdd": d, "calmar": c}
                row += f"{a:>6.2f}/{d:>6.2f}/{fmt(c):>6}"
            except Infeasible:
                out[_key(dest, cap)] = "REFUSED"
                row += f"{'REFUSED (infeasible)':>21}"
        print(row)
    print("\n   REFUSED is a result, not a gap: a 10 % ceiling over ten books pins every book at")
    print("   the ceiling, leaving nothing strictly under it to receive a trim. Only `cash` can")
    print("   express that portfolio, and it does so by holding cash — which is the honest answer.")

    print(f"\n   Toll sensitivity at the T2 ceiling (20 %), every convention in the tree:")
    print(f"{'bps':>7}" + "".join(f"{d:>21}" for d in DESTINATIONS))
    for bps in CONVENTIONS_BPS:
        row = f"{bps:>7}"
        for dest in DESTINATIONS:
            a, d, c = metrics(capped_bh(book_rets, live, cap=0.20, cost=bps / 1e4, destination=dest))
            out[f"{dest}@20@{bps}bps"] = {"apy": a, "mdd": d, "calmar": c}
            row += f"{a:>6.2f}/{d:>6.2f}/{fmt(c):>6}"
        print(row)

    a2, d2, c2 = metrics(capped_bh(book_rets, live, cap=0.20, cost=DEPLOYED_BPS / 1e4,
                                   destination="cash", cash_legs=2))
    out["cash@20@2legs"] = {"apy": a2, "mdd": d2, "calmar": c2}
    print(f"\n   SENSITIVITY · `cash` charged TWO legs instead of one: "
          f"APY {a2:.2f} · maxDD {d2:.2f} · Calmar {fmt(c2)}")
    return out


def section1b_binding(dates, book_rets, live) -> Dict[str, object]:
    """POST-HOC DIAGNOSTIC (not a prediction): how often does the ceiling actually BIND?

    Added AFTER §3 came back with all five destinations scoring identically out of sample.
    A destination can only matter on days the cap binds; if it never binds, every destination
    is the same portfolio and the tie is arithmetic, not a finding about allocation. Labelled
    post-hoc on purpose — it explains a measured result, it does not join the predictions.
    """
    print("\n" + "─" * 100)
    print("1b. POST-HOC DIAGNOSTIC — how often the ceiling binds (deployed convention).")
    print("    Added after §3 returned an exact tie; a destination is inert on days nothing")
    print("    is trimmed. This is an explanation of a measured result, NOT a prediction.")
    cost = DEPLOYED_BPS / 1e4
    k = _split_index(dates, SPLIT_DATE)
    out: Dict[str, object] = {}
    print(f"{'cap':>7}{'days bound':>13}{'of days':>10}{'TRAIN bound':>14}"
          f"{'TEST bound':>13}{'traded (NAV)':>15}")
    print("─" * 100)
    for cap in CAP_GRID:
        tr: List[float] = []
        try:
            capped_bh(book_rets, live, cap=cap, cost=cost, destination="prorata", trace=tr)
        except Infeasible:
            print(f"{cap:>6.0%} {'REFUSED (infeasible for prorata)':>60}")
            out[_key("prorata", cap)] = "REFUSED"
            continue
        bound = [i for i, t in enumerate(tr) if t > 0]
        n_tr = len([i for i in bound if i < k])
        n_te = len([i for i in bound if i >= k])
        out[_key("prorata", cap)] = {"bound": len(bound), "train": n_tr, "test": n_te,
                                     "traded": sum(tr)}
        print(f"{cap:>6.0%} {len(bound):>12}{len(tr):>10}{n_tr:>14}{n_te:>13}{sum(tr):>15.4f}")
    print("\n    A cap that binds on ZERO days in a half makes every destination that half's")
    print("    same portfolio. Read §3 through this table before reading it as stability.")
    return out


def section2_controls(book_rets, live) -> Dict[str, object]:
    """The random-destination cloud. If the spread of §1 sits inside it, §1 measured noise."""
    print("\n" + "─" * 100)
    print("2. CONTROL — RANDOM destination (one random under-cap receiver per binding pass).")
    print("   Five fixed seeds. A finding must sit OUTSIDE this cloud to be a finding.")
    cost = DEPLOYED_BPS / 1e4
    out: Dict[str, object] = {}
    cals, apys = [], []
    for s in RANDOM_SEEDS:
        a, d, c = metrics(capped_bh_random(book_rets, live, cap=0.20, cost=cost, seed=s))
        out[f"seed{s}"] = {"apy": a, "mdd": d, "calmar": c}
        cals.append(c)
        apys.append(a)
        print(f"   seed {s:>3}: APY {a:>6.2f} · maxDD {d:>6.2f} · Calmar {fmt(c):>6}")
    out["band"] = {"calmar_lo": min(cals), "calmar_hi": max(cals),
                   "apy_lo": min(apys), "apy_hi": max(apys)}
    print(f"   random band: Calmar [{min(cals):.2f}, {max(cals):.2f}] · "
          f"APY [{min(apys):.2f}, {max(apys):.2f}]")
    return out


def section3_oos(dates, book_rets, live) -> Dict[str, object]:
    """TPD §3 — out of sample, under BOTH split protocols, because they are not the same thing.

    RESTART (the naive split every earlier entry of this branch used): rebuild the portfolio
    from equal weights on the first day of the test half. For a MEAN-REVERTING signal that is
    neutral. For a BUY-AND-HOLD portfolio it is NOT: the thing being tested is the drift of the
    weights, and restarting deletes it. §1b measured the consequence — under RESTART the 20 %
    ceiling binds on ZERO of 370 test days, so all five destinations are literally the same
    portfolio and score identically. That tie is arithmetic, not evidence, and reading it as
    "the dial does not matter" would be the mistake this section exists to prevent.

    CARRY (the protocol this file uses for its claim): run one continuous path over all 852
    days and measure only the test segment. The weights cross the boundary as they actually
    would. The ceiling then binds on 190 of the 370 test days and the destinations separate.

    Both are printed. The ORACLE row is the best destination chosen ON TEST ITSELF — a ceiling,
    never a result.
    """
    print("\n" + "─" * 100)
    k = _split_index(dates, SPLIT_DATE)
    print(f"3. OUT OF SAMPLE — boundary {SPLIT_DATE}: TRAIN {k} d / TEST {len(dates) - k} d.")
    print("   TWO protocols, because for a buy-and-hold portfolio they are NOT the same test.")
    cost = DEPLOYED_BPS / 1e4
    tr = {b: list(book_rets[b])[:k] for b in live}
    te = {b: list(book_rets[b])[k:] for b in live}
    out: Dict[str, object] = {}
    print(f"\n{'destination':>14}{'TRAIN Cal':>11}{'  |':>3}{'RESTART TEST Cal':>18}"
          f"{'  |':>3}{'CARRY TEST APY':>16}{'CARRY TEST DD':>15}{'CARRY TEST Cal':>16}")
    print("─" * 100)
    best_tr, best_dest = None, None
    for dest in DESTINATIONS:
        full = capped_bh(book_rets, live, cap=0.20, cost=cost, destination=dest)
        ta, td, tc = metrics(full[:k])
        ca, cd, cc = metrics(full[k:])
        ra, rd, rc = metrics(capped_bh(te, live, cap=0.20, cost=cost, destination=dest))
        out[dest] = {"train": {"apy": ta, "mdd": td, "calmar": tc},
                     "restart_test": {"apy": ra, "mdd": rd, "calmar": rc},
                     "carry_test": {"apy": ca, "mdd": cd, "calmar": cc}}
        if best_tr is None or tc > best_tr:
            best_tr, best_dest = tc, dest
        print(f"{dest:>14}{tc:>11.4f}{'  |':>3}{rc:>18.4f}{'  |':>3}"
              f"{ca:>16.2f}{cd:>15.2f}{cc:>16.2f}")
    oracle = max(DESTINATIONS, key=lambda d: out[d]["carry_test"]["calmar"])
    out["chosen_on_train"] = best_dest
    out["oracle_on_test"] = oracle
    print(f"\n   Chosen on TRAIN by Calmar: `{best_dest}` → CARRY-TEST Calmar "
          f"{fmt(out[best_dest]['carry_test']['calmar'])}")
    print(f"   Deployed convention `prorata`  → CARRY-TEST Calmar "
          f"{fmt(out['prorata']['carry_test']['calmar'])}")
    print(f"   ORACLE (chosen ON TEST, look-ahead — a ceiling, never a result): `{oracle}` "
          f"→ {fmt(out[oracle]['carry_test']['calmar'])}")

    gap_tr = abs(out["to_min"]["train"]["calmar"] - out["to_max"]["train"]["calmar"])
    gap_te = abs(out["to_min"]["carry_test"]["calmar"] - out["to_max"]["carry_test"]["calmar"])
    out["twin_gap"] = {"train": gap_tr, "test": gap_te}
    print(f"\n   THE NUMBER THAT DECIDES WHAT THIS IDEA IS: `to_min` and `to_max` are OPPOSITE")
    print(f"   rules. On TRAIN they differ by {gap_tr:.5f} Calmar. On CARRY-TEST they differ by")
    print(f"   {gap_te:.2f}. A dial whose two extremes are indistinguishable in-sample and five")
    print("   Calmar apart out of sample CANNOT BE CHOSEN BY FITTING. Any future session that")
    print("   'optimises the destination' on history is fitting noise, and this line is why.")

    print("\n   ROBUSTNESS — every boundary × ceiling printed, none selected. CARRY protocol.")
    print(f"{'boundary':>13}{'test d':>8}" + "".join(f"{'cap ' + f'{c:.0%}':>26}" for c in
                                                     (0.15, 0.20, 0.25, 0.33)))
    print(f"{'':>21}" + "".join(f"{'pro / cash / to_max':>26}" for _ in range(4)))
    grid: Dict[str, object] = {}
    for bd in ("2025-01-31", "2025-06-30", "2025-12-31", "2026-03-31"):
        kk = _split_index(dates, bd)
        row = f"{bd:>13}{len(dates) - kk:>8}"
        for cap in (0.15, 0.20, 0.25, 0.33):
            cells = []
            for dest in ("prorata", "cash", "to_max"):
                try:
                    c = metrics(capped_bh(book_rets, live, cap=cap, cost=cost,
                                          destination=dest)[kk:])[2]
                    cells.append(f"{c:.2f}")
                except Infeasible:
                    cells.append("REF")
            grid[f"{bd}@cap{int(cap * 100)}"] = cells
            row += f"{' / '.join(cells):>26}"
        print(row)
    out["grid"] = grid
    wins = sum(1 for v in grid.values()
               if v[1] not in ("REF",) and v[0] not in ("REF",) and float(v[1]) > float(v[0]))
    out["cash_beats_prorata"] = f"{wins}/{len(grid)}"
    print(f"\n   `cash` beats the deployed `prorata` in {wins} of {len(grid)} boundary×ceiling")
    print("   cells. NOTHING IS FITTED HERE: `cash` has no parameter — it is the rule 'do not")
    print("   force-buy anything with the winner's proceeds'. That is why it is quotable and")
    print("   `to_max` (which wins more cells) is NOT: to_max is a momentum BET, and the twin")
    print("   gap above proves this panel cannot tell you whether to take it.")
    return out


def section4_blo(book_rets, live) -> Dict[str, object]:
    """BLO — how deep is the bench under the bar? Drop one book, then drop them greedily."""
    print("\n" + "─" * 100)
    print("4. BLO — leave-one-out on the benchmark itself (20 % cap, deployed convention).")
    cost = DEPLOYED_BPS / 1e4
    base = metrics(capped_bh(book_rets, live, cap=0.20, cost=cost))
    print(f"   full panel ({len(live)} books): APY {base[0]:.2f} · maxDD {base[1]:.2f} · "
          f"Calmar {fmt(base[2])}")
    out: Dict[str, object] = {"full": {"apy": base[0], "mdd": base[1], "calmar": base[2]}}
    print(f"\n{'book removed':>22}{'raw APY':>10}{'raw Cal':>10}{'bench APY':>12}"
          f"{'bench DD':>11}{'bench Cal':>11}{'ΔCalmar':>10}")
    print("─" * 100)
    rows = []
    for b in live:
        rest = [x for x in live if x != b]
        if len(rest) * 0.20 < 1.0 - 1e-12:
            print(f"{b:>22}{'':>10}{'':>10}{'REFUSED — 20 % over ' + str(len(rest)) + ' books':>44}")
            continue
        a, d, c = metrics(capped_bh({x: book_rets[x] for x in rest}, rest, cap=0.20, cost=cost))
        ra, _rd, rc = metrics(book_rets[b])
        rows.append((c - base[2], b, ra, rc, a, d, c))
    for dc, b, ra, rc, a, d, c in sorted(rows):
        out[b] = {"apy": a, "mdd": d, "calmar": c, "d_calmar": dc,
                  "raw_apy": ra, "raw_calmar": rc}
        print(f"{b:>22}{ra:>10.2f}{fmt(rc):>10}{a:>12.2f}{d:>11.2f}{fmt(c):>11}{dc:>10.2f}")
    print("\n   Sorted by damage: the top row is the book the benchmark stands on.")

    print("\n   Greedy removal — drop the most load-bearing book, then re-measure and repeat:")
    remaining = list(live)
    ladder = []
    while len(remaining) * 0.20 >= 1.0 - 1e-12 and len(remaining) > 2:
        cur = metrics(capped_bh({x: book_rets[x] for x in remaining}, remaining,
                                cap=0.20, cost=cost))
        worst, worst_c = None, None
        for b in remaining:
            rest = [x for x in remaining if x != b]
            if len(rest) * 0.20 < 1.0 - 1e-12:
                continue
            try:
                c = metrics(capped_bh({x: book_rets[x] for x in rest}, rest,
                                      cap=0.20, cost=cost))[2]
            except Infeasible:
                # A 20 % ceiling over few enough books can PIN every one of them: the
                # portfolio is then unrepresentable, not merely worse. That is the floor of
                # this ladder and it is printed as a refusal, not skipped and not smoothed.
                ladder.append({"n": len(remaining), "calmar": cur[2], "apy": cur[0],
                               "mdd": cur[1], "drop_next": b, "next_is": "REFUSED"})
                print(f"   {len(remaining):>2} books: APY {cur[0]:>6.2f} · "
                      f"maxDD {cur[1]:>6.2f} · Calmar {fmt(cur[2]):>7}   → dropping `{b}` "
                      f"REFUSES: a 20 % ceiling cannot hold {len(rest)} books")
                out["ladder"] = ladder
                return out
            if worst_c is None or c < worst_c:
                worst, worst_c = b, c
        if worst is None:
            break
        ladder.append({"n": len(remaining), "calmar": cur[2], "apy": cur[0], "mdd": cur[1],
                       "drop_next": worst})
        print(f"   {len(remaining):>2} books: APY {cur[0]:>6.2f} · maxDD {cur[1]:>6.2f} · "
              f"Calmar {fmt(cur[2]):>7}   → dropping `{worst}` next")
        remaining = [x for x in remaining if x != worst]
    if len(remaining) >= 2:
        cur = metrics(capped_bh({x: book_rets[x] for x in remaining}, remaining,
                                cap=0.20, cost=cost))
        ladder.append({"n": len(remaining), "calmar": cur[2], "apy": cur[0], "mdd": cur[1],
                       "drop_next": None})
        print(f"   {len(remaining):>2} books: APY {cur[0]:>6.2f} · maxDD {cur[1]:>6.2f} · "
              f"Calmar {fmt(cur[2]):>7}   (floor of the 20 % ceiling)")
    out["ladder"] = ladder
    return out


def section5_verdict(res) -> None:
    print("\n" + "─" * 100)
    print("5. VERDICT")
    s1 = res["s1"]
    at20 = {d: s1[_key(d, 0.20)] for d in DESTINATIONS
            if isinstance(s1.get(_key(d, 0.20)), dict)}
    cals = {d: v["calmar"] for d, v in at20.items()}
    lo, hi = min(cals.values()), max(cals.values())
    band = res["s2"]["band"]
    print(f"   TPD spread at the T2 ceiling: Calmar {lo:.2f} … {hi:.2f} "
          f"(width {hi - lo:.2f}) across {len(cals)} destinations.")
    print(f"   RANDOM control band:          Calmar {band['calmar_lo']:.2f} … "
          f"{band['calmar_hi']:.2f}.")
    inside = band["calmar_lo"] <= hi <= band["calmar_hi"]
    print(f"   Best destination inside the random band? {inside}"
          f"   ({'noise' if inside else 'distinguishable from random'})")
    s3 = res["s3"]
    print(f"   OUT OF SAMPLE (CARRY): TRAIN picked `{s3['chosen_on_train']}` and it scores "
          f"{fmt(s3[s3['chosen_on_train']]['carry_test']['calmar'])} on TEST against the "
          f"deployed {fmt(s3['prorata']['carry_test']['calmar'])}; look-ahead ceiling "
          f"`{s3['oracle_on_test']}` {fmt(s3[s3['oracle_on_test']]['carry_test']['calmar'])}.")
    print(f"   The two OPPOSITE destinations differ by {s3['twin_gap']['train']:.5f} Calmar "
          f"in-sample and {s3['twin_gap']['test']:.2f} out of sample — this dial is NOT "
          f"selectable from history.")
    print(f"   `cash` (no parameter, no fitting: 'do not force-buy') beats the deployed "
          f"convention in {s3['cash_beats_prorata']} boundary×ceiling cells.")
    blo = res["s4"]
    worst = min((k for k in blo if isinstance(blo[k], dict) and "d_calmar" in blo[k]),
                key=lambda k: blo[k]["d_calmar"])
    print(f"   BLO: the benchmark's most load-bearing book is `{worst}` "
          f"(ΔCalmar {blo[worst]['d_calmar']:.2f} when removed; "
          f"{fmt(blo['full']['calmar'])} → {fmt(blo[worst]['calmar'])}).")
    print("\n   All numbers L0 [bt], IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True. No module is")
    print("   built and no agent is deployed by this file.")


def run(dates, book_rets) -> Dict[str, object]:
    live = [b for b in sorted(book_rets) if not oda.is_dead(book_rets[b])]
    print("=" * 100)
    print("TPD / BLO — the unwritten convention inside the family's mandatory benchmark")
    print(f"panel: {len(live)} books × {len(dates)} days  ({dates[0]} … {dates[-1]})")
    print("=" * 100)
    res: Dict[str, object] = {}
    res["s0"] = section0_identity(book_rets, live)
    res["s1"] = section1_destinations(book_rets, live)
    res["s1b"] = section1b_binding(dates, book_rets, live)
    res["s2"] = section2_controls(book_rets, live)
    res["s3"] = section3_oos(dates, book_rets, live)
    res["s4"] = section4_blo(book_rets, live)
    section5_verdict(res)
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--fixture", action="store_true",
                    help="run on the synthetic fixture panel instead of the real one")
    args = ap.parse_args(argv)
    dates, book_rets = (gtn.load_fixture_panel() if args.fixture else gtn.load_real_panel())
    run(dates, book_rets)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
