#!/usr/bin/env python3
"""
scripts/edge_overlay_domain_admissibility.py — registry ideas ODA + PBA

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the dashboard or the fleet. Reads the aggressive-lab panel READ-ONLY. Capital is not
moved. No module is built and no agent is deployed here. The deployed organ's parameters are
IMPORTED, never retyped, and never written back.

Working names ODA / PBA. The registry NUMBERS are claimed at DELIVERY.


THE QUESTION, WHICH CQD FOUND AND DID NOT ASK
=============================================
CQD (#93) measured the deployed L2 guardian on all ten real books and found a class it named
but never tested:

    on `susde_dn` — raw out-of-sample drawdown 0.05 % — the guarded path's drawdown is 0.31 %.
    The overlay on a book whose own drawdown is smaller than its churn BECOMES the drawdown it
    exists to prevent.

CQD stopped there on purpose: changing the deployed organ is owner-gated, and it filed a card.
But the entry left the ENGINEERING question unasked, and it is the one worth a registry number:

    Is "where the overlay is allowed to run at all" a usable ADDITIONAL DIAL — one that can be
    decided CAUSALLY, from data available on the day, rather than by an operator's judgement
    after the fact?

This is not the same dial as any entry in the registry. #1/#9/#32/#33 tune WHEN the overlay
fires. #82/#88/#89 tune WHAT IT COSTS when it does. #35 DGO gates the overlay per-book per-day
on the SIGN OF DRIFT — and died against its own control. Nothing in the registry has gated the
overlay on the SIZE OF WHAT THERE IS TO PROTECT measured against the PRICE OF PROTECTING IT.
That comparison is an economic statement, not a trend statement, and it has a natural zero.


MECHANISM (two forms of one idea; the organ itself is untouched)
----------------------------------------------------------------
Both forms produce a per-book, per-day admission bit. When admission is False the overlay is
not consulted and exposure is 1.0; if the gate closes while the book is de-risked, exposure is
RESTORED to 1.0 and the toll for that move is charged — a gate must not hand out free exits.

  ODA (absolute threshold).  admit(b, t) = trailingMaxDD_W(b, t) >= K · price_of_round
      trailingMaxDD_W(b, t) — the book's own maximum drawdown over the W days ENDING AT t,
      computed on the RAW book path, from equity points strictly at or before the open of the
      day being gated. price_of_round = 2·roundtrip_cost (out and back).
      K = 0 makes the threshold zero and reproduces the deployed organ EXACTLY. That is the
      positive control of the whole file, and it is asserted, not assumed
      (spa_core/tests/test_edge_overlay_domain_admissibility.py).

  PBA (cross-sectional budget).  Each day, rank the books by trailingMaxDD_W and admit the
      overlay to the top M only. M = 10 (all books) is again the deployed organ. This asks the
      companion question #40 asked of #39: is selectivity better expressed as an absolute
      threshold or as a rank under a budget?

Three controls, all mandatory, all in the shape #35 used to kill itself:
  * INVERSE  — admit only when trailing drawdown is SMALL (must be worse; if it is not, the
               gate is not measuring what it claims);
  * ORACLE   — admit on the FULL-SAMPLE drawdown of the book (LOOK-AHEAD; the ceiling of what
               perfect selection could be worth, never a result);
  * DEPLOYED — K=0 / M=10, the organ as it runs today.


THE PREDICTIONS, WRITTEN DOWN BEFORE THE RUN (so the entry cannot be a post-hoc story)
  P1. The gate helps most where CQD found the damage — on the quiet books (`susde_dn`,
      `pendle_yt_susde`), by simply switching the overlay off there — and is close to inert on
      the stressed ones (`pendle_pt_levered`, `susde_spot`).
  P2. The gate's own failure mode is LAG, and it is structural: a book that is quiet for W days
      and then breaks will be gated OFF on the day it breaks. Section 4 measures exactly this
      and it is the honest limit of the idea, not a caveat about it.
  P3. PBA (rank) will be worse than ODA (threshold), because a rank always admits M books even
      on a day when NONE of them has anything to protect — it cannot express "nobody today".


HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; the guardian's own caveats carry over unchanged and are not softened:
    it reduces SLOW-risk drawdown compounding only. GAP risk (exploit, instant depeg, drained
    exit) is not preventable by any overlay, is not addressed by any gate, and stays in the
    tier tail. A gate can only ever remove a cost, never add protection;
  * the toll is proportional, on |Δexposure|, exactly as the deployed organ charges it. Gas in
    dollars per leg is NOT in this file; at pilot sizes it dominates both axes — #91/#92, not
    re-litigated here;
  * every cost quoted is a CONVENTION, not a measurement. #92/#93 established that no
    proportional toll in this tree carries a date or a source, and that the branch's 96 is a
    break-even of a foreign overlay, charged at twice its own definition. Numbers below are
    therefore printed AT NAMED CONVENTIONS and never as "the cost";
  * the comparability rule of #93 is carried over verbatim: a book whose raw Calmar or raw APY
    is not positive is MEASURED, PRINTED, and then excluded from every claim — in that order.
    "Higher Calmar" on a losing book is a shallower path to the same loss;
  * the panel is REGENERATED, not appended (#32 caveat (е)): numbers here reproduce only
    against the panel files of the date printed in the header;
  * no parameter is chosen after reading a number. The grids (K, W, M), the book set (all ten,
    no selection), the conventions (0 / 8 / 13 / 15 / 96 bps, all four already in the tree) and
    the split boundary (2025-06-30, canonical since #79) are fixed in this file above the
    first line of output.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_gross_to_net_toll as gtn  # noqa: E402  (real-panel loader, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 APY/maxDD/Calmar, reused verbatim)

from spa_core.strategy_lab.aggressive_lab.guardian import stdev  # noqa: E402
from spa_core.strategy_lab.swarm import guardian_forward as gf  # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: Admission grids. Fixed before the first number. K=0 and M=len(books) are the deployed organ.
K_GRID: Tuple[float, ...] = (0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
W_GRID: Tuple[int, ...] = (60, 90, 180)
M_GRID: Tuple[int, ...] = (1, 2, 3, 5, 10)

#: Every proportional toll that exists in this tree, in bps of |Δexposure|. Not a measurement —
#: a list of conventions, each one named by its reader. See the module docstring.
CONVENTIONS_BPS: Tuple[int, ...] = (0, 8, 13, 15, 96)

#: The toll the L2 organ actually deploys, READ from the organ so this file cannot drift.
DEPLOYED_BPS = 1e4 * gf.GUARDIAN_PARAMS["roundtrip_cost"]

#: The branch's canonical out-of-sample boundary, unchanged since #79.
SPLIT_DATE = "2025-06-30"

#: Where the money goes when the ceiling FORCES the benchmark to sell part of a winner.
#: Both are conventions, neither is a measurement, and until 2026-09-03 only one of them
#: existed — `"prorata"` was not chosen, it was simply the first thing the code did (#98 TPD).
#:
#:   "cash"     the proceeds leave the risk book into a 0 %-yield sleeve and are NEVER
#:              redeployed. "We do not force-buy anybody because somebody else grew."
#:   "prorata"  the proceeds are pushed back into the under-cap books in proportion to their
#:              current weight — including books that lose money.
TRIM_DESTINATIONS: Tuple[str, ...] = ("cash", "prorata")

#: The convention THIS benchmark is built with. Owner decision 2026-09-03, option 1
#: (card `owner-decision-etalonnaya-planka-issledovanii-nasilno-d`, ADR-218), taken on the
#: measurement in registry entry #98: out of sample `cash` returns the same income at a 20 %
#: shallower drawdown (12.20 % / −1.82 % against 12.20 % / −2.29 %) and wins 16 of 16 cells of
#: the boundary × ceiling grid. It has no parameter to fit, which is the reason it is quotable
#: at all — #98 §3 proved this dial cannot be chosen by fitting history.
BENCHMARK_CONVENTION = "cash"

#: The convention entries #86 and #96 were PUBLISHED under. Their numbers are NOT rewritten
#: (owner decision, same card): this stays as the control column beside the benchmark, forever
#: printed next to it, so no reader has to guess which convention a number came from.
PUBLISHED_CONVENTION = "prorata"


# --------------------------------------------------------------------------------------------
# equity / return plumbing (same conventions as #93, so the two entries are comparable)
# --------------------------------------------------------------------------------------------
class Ruin(Exception):
    """The equity path reached zero. Not a Calmar, not a zero — a different outcome."""


def _equity(rets: Sequence[float]) -> List[float]:
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _rets(equity: Sequence[float]) -> List[float]:
    out: List[float] = []
    for i in range(len(equity) - 1):
        if equity[i] <= 0.0:
            raise Ruin(f"equity path reached zero at index {i}")
        out.append(equity[i + 1] / equity[i] - 1.0)
    return out


def is_dead(rets: Sequence[float]) -> bool:
    """No movement at all = the book is ABSENT from this panel, not neutral in it."""
    return all(abs(r) < 1e-12 for r in rets)


def comparable(raw_calmar: float, raw_apy: float) -> bool:
    """#93's rule, carried over verbatim. Measured, printed, then excluded — in that order."""
    return raw_calmar == raw_calmar and raw_calmar > 0.0 and raw_apy > 0.0


# --------------------------------------------------------------------------------------------
# the gated engine
# --------------------------------------------------------------------------------------------
def guarded_path(
    equity: Sequence[float],
    admit: Optional[Sequence[bool]] = None,
    *,
    lookback: int = 10,
    vol_mult: float = 2.0,
    derisk_frac: float = 0.0,
    calm_mult: float = 1.2,
    roundtrip_cost: float = 0.0,
    min_vol: float = 1e-5,
    causal_lag: int = 0,
) -> List[float]:
    """`apply_guardian_vol` with a per-day admission gate and an explicit causality lag.

    Mirrors the deployed organ line for line. Two additions, both off by default:

      * `admit[i]` — whether the overlay is allowed to act on day i at all. False forces
        exposure back to 1.0 AND charges the toll for that move, because a gate that closes
        while the book is de-risked must pay for the re-entry like any other move. `None` = the
        gate is always open.
      * `causal_lag` — 0 means the vol window ENDS at day i, which is what the deployed organ
        does; 1 means it ends at i-1. See section 0: the difference is an instrument check, and
        the whole file's baseline depends on knowing its size.

    With `admit=None` and `causal_lag=0` this function must be bit-identical to
    `apply_guardian_vol`. That equivalence is asserted by test, and the test is mutated in both
    directions so it cannot pass vacuously.
    """
    equity = list(equity)
    if len(equity) < lookback + 2:
        return equity
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    guarded = [equity[0]]
    exposure = 1.0
    for i in range(len(rets)):
        if i >= lookback:
            end = i + 1 - causal_lag
            if end - lookback >= 0:
                recent = stdev(rets[end - lookback: end])
                base = stdev(rets[max(0, end - 1 - 4 * lookback): end - lookback]) or 1e-9
                prev = exposure
                if admit is not None and not admit[i]:
                    exposure = 1.0
                elif exposure >= 1.0 and recent > vol_mult * base and recent > min_vol:
                    exposure = derisk_frac
                elif exposure < 1.0 and (recent < calm_mult * base or recent < min_vol):
                    exposure = 1.0
                if exposure != prev and roundtrip_cost:
                    guarded[-1] *= (1.0 - roundtrip_cost * abs(prev - exposure))
        guarded.append(guarded[-1] * (1.0 + rets[i] * exposure))
    return guarded


def trailing_maxdd(equity: Sequence[float], window: int) -> List[float]:
    """dd[i] = max drawdown of the RAW path over the `window` days ending at equity index i.

    Day i's return spans equity[i] -> equity[i+1], so a gate for day i may look at equity
    points up to and including index i and no further. Returned as a POSITIVE fraction
    (0.03 = a 3 % drawdown), one entry per return index.

    On the raw path, not the guarded one, and that is deliberate: gating on the guarded path
    is self-referential (the overlay suppresses the drawdown, the gate then closes, the
    drawdown returns) and would measure the overlay's own limit cycle rather than the book.
    The book's own NAV is what an operator observes regardless of our exposure.
    """
    out: List[float] = []
    for i in range(len(equity) - 1):
        lo = max(0, i - window + 1)
        peak = equity[lo]
        worst = 0.0
        for j in range(lo, i + 1):
            peak = max(peak, equity[j])
            if peak > 0:
                worst = min(worst, equity[j] / peak - 1.0)
        out.append(-worst)
    return out


def full_sample_maxdd(equity: Sequence[float]) -> float:
    peak = equity[0]
    worst = 0.0
    for x in equity:
        peak = max(peak, x)
        if peak > 0:
            worst = min(worst, x / peak - 1.0)
    return -worst


def oda_admission(
    equity: Sequence[float], window: int, k: float, cost: float, mode: str = "direct"
) -> List[bool]:
    """The ODA gate and its two controls.

    mode='direct'  — admit when trailing drawdown >= K x price_of_round (the hypothesis);
    mode='inverse' — admit when it is BELOW that (the control that must be worse);
    mode='oracle'  — admit on the FULL-SAMPLE drawdown. LOOK-AHEAD. A ceiling, never a result.
    """
    threshold = k * 2.0 * cost
    if mode == "oracle":
        ok = full_sample_maxdd(equity) >= threshold
        return [ok] * (len(equity) - 1)
    dd = trailing_maxdd(equity, window)
    if mode == "inverse":
        return [d < threshold for d in dd]
    return [d >= threshold for d in dd]


def metrics(path: Sequence[float]) -> Tuple[float, float, float]:
    """(APY %, maxDD %, Calmar) of an equity path. Raises Ruin on a wiped-out path."""
    r = _rets(path)
    return mh._apy(r) * 100.0, mh._mdd(r) * 100.0, mh._calmar(r)


def fmt(x: float, nd: int = 2) -> str:
    if x != x:
        return "—"
    if x in (float("inf"), float("-inf")):
        return "∞"
    return f"{x:.{nd}f}"


# --------------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------------
def section0_instrument(book_rets, params) -> Dict[str, object]:
    """Does the organ this file is measured AGAINST see the day it trades on?

    The baseline of every table below is the deployed organ. Before comparing anything to it,
    one property of it has to be known, because it decides what the baseline MEANS: the vol
    window `rets[i-lookback+1 : i+1]` INCLUDES rets[i], and the exposure chosen from it is then
    applied to rets[i]. The day's own close-to-close return is not available before the close,
    so this is not #19's "same-day detection" (an intraday signal an RTMR could genuinely
    produce) — it is the close deciding the trade inside its own bar.

    The registry's own harnesses pin the opposite convention (#32's control: "a −40 % hit on day
    i must not move day i's exposure"). So the size of the difference is not a curiosity; it is
    the error bar on the baseline. Measured, not argued.
    """
    print("\n" + "─" * 100)
    print("0. INSTRUMENT CHECK — the baseline organ's own causality, measured before it is used")
    print("   deployed = vol window ends at day i (the day being traded);")
    print("   causal   = same organ, window ends at i−1. Nothing else differs. Toll = deployed"
          f" {DEPLOYED_BPS:.0f} bps.")
    print("   RAW is printed beside them because the only question that matters is how much of")
    print("   the organ's published drawdown cut survives when it cannot see the day it trades.")
    print(f"{'book':>22}{'raw APY%':>10}{'raw DD%':>9}{'raw Cal':>9}"
          f"{'depl APY%':>11}{'depl DD%':>10}{'depl Cal':>10}"
          f"{'causal APY%':>13}{'causal DD%':>12}{'causal Cal':>12}")
    print("─" * 100)
    cost = DEPLOYED_BPS / 1e4
    out: Dict[str, object] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        if is_dead(rets):
            print(f"{book:>22}{'dead — no movement in this panel':>66}")
            out[book] = {"verdict": "dead"}
            continue
        eq = _equity(rets)
        try:
            d = metrics(guarded_path(eq, None, roundtrip_cost=cost, causal_lag=0, **params))
            c = metrics(guarded_path(eq, None, roundtrip_cost=cost, causal_lag=1, **params))
        except Ruin:
            print(f"{book:>22}{'ruin — the path reached zero':>66}")
            out[book] = {"verdict": "ruin"}
            continue
        w = metrics(eq)
        print(f"{book:>22}{w[0]:>10.2f}{w[1]:>9.2f}{fmt(w[2]):>9}"
              f"{d[0]:>11.2f}{d[1]:>10.2f}{fmt(d[2]):>10}"
              f"{c[0]:>13.2f}{c[1]:>12.2f}{fmt(c[2]):>12}")
        out[book] = {"raw": list(w), "deployed": list(d), "causal": list(c),
                     "apy_premium_pp": d[0] - c[0],
                     "dd_cut_deployed_pp": abs(w[1]) - abs(d[1]),
                     "dd_cut_causal_pp": abs(w[1]) - abs(c[1])}
    print("\n   'dd cut' = how many points of drawdown the overlay removed FROM RAW. Read the")
    print("   two right-hand blocks against the left one; the difference between them is not a")
    print("   tuning choice, it is whether the number was earned inside its own bar.")
    for book in sorted(out):
        v = out[book]
        if "raw" not in v:
            continue
        print(f"     {book:<22} dd cut deployed {v['dd_cut_deployed_pp']:>7.2f} pp"
              f"   ·   dd cut causal {v['dd_cut_causal_pp']:>7.2f} pp")
    return out


def section0b_identity(book_rets, params) -> Dict[str, object]:
    """A SECOND, independent route to the same number — with its own stated error rate.

    Section 0 re-derives the organ inside this file. A finding that large must not rest on one
    implementation, so it is checked a different way: the organ's OWN exposure trace
    (`guardian_forward.vol_guardian_trace`, the live module) is read out, and the claim

        causal_exposure[i]  ==  deployed_exposure[i-1]

    is tested pointwise. The vol signal is a pure function of the RAW returns (the organ derives
    `rets` from its input equity, never from the guarded path), so if the deployed organ is
    simply one day early, this identity must hold EXACTLY.

    Its known error rate, named before it is run: it must fail at exactly one index per book —
    i = lookback — where the causal variant makes its first decision and the one-day-later organ
    has not made any yet. A failure anywhere else would mean the two routes disagree about
    something real, and would sink the finding.
    """
    print("\n" + "─" * 100)
    print("0b. THE SAME FINDING BY A SECOND ROUTE — the LIVE module's own exposure trace.")
    print("    Claim under test:  causal_exposure[i] == deployed_exposure[i−1], pointwise.")
    print("    Known error rate, stated before the run: exactly one index per book, i=lookback")
    print("    (the warm-up boundary). Anywhere else = the two routes disagree and the finding")
    print("    does not stand.")
    print(f"{'book':>22}{'points':>9}{'mismatches':>12}{'where':>28}")
    print("─" * 100)
    lb = params["lookback"]
    out: Dict[str, object] = {}
    total_bad = 0
    for book in sorted(book_rets):
        rets = book_rets[book]
        if is_dead(rets):
            continue
        eq = _equity(rets)
        _, deployed_exp, _ = gf.vol_guardian_trace(eq, roundtrip_cost=0.0)
        causal_exp = _exposure_trace(eq, None, causal_lag=1, **params)
        bad = [i for i in range(1, len(causal_exp))
               if abs(causal_exp[i] - deployed_exp[i - 1]) > 1e-15]
        total_bad += len(bad)
        where = "—" if not bad else (f"i={bad[0]} (=lookback)" if bad == [lb]
                                     else f"UNEXPECTED: {bad[:5]}")
        print(f"{book:>22}{len(causal_exp) - 1:>9}{len(bad):>12}{where:>28}")
        out[book] = {"points": len(causal_exp) - 1, "mismatches": bad}
    ok = all(v["mismatches"] in ([], [lb]) for v in out.values())  # type: ignore[index]
    print(f"\n   verdict: {'CONFIRMED' if ok else 'NOT CONFIRMED'} — every mismatch is at the "
          f"named warm-up index (total {total_bad}).")
    out["confirmed"] = ok
    return out


def _exposure_trace(equity, admit: Optional[Sequence[bool]] = None, *,
                    lookback, vol_mult, derisk_frac, calm_mult, min_vol,
                    causal_lag=0) -> List[float]:
    """The exposure sequence `guarded_path` applies. Same branch structure, no equity.

    This function and `guarded_path` are two copies of one decision rule, and a test comparing
    two copies is blind to a change made to both — or to a change made to only one, which is
    worse, because then the identity check of section 0b would be confirming a finding that
    section 0 did not measure. So the two are BOUND by test: at a zero toll, compounding the
    returns against this trace must reproduce `guarded_path`'s equity exactly, for every lag
    and every gate.
    """
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    exps: List[float] = []
    exposure = 1.0
    for i in range(len(rets)):
        if i >= lookback:
            end = i + 1 - causal_lag
            if end - lookback >= 0:
                recent = stdev(rets[end - lookback: end])
                base = stdev(rets[max(0, end - 1 - 4 * lookback): end - lookback]) or 1e-9
                if admit is not None and not admit[i]:
                    exposure = 1.0
                elif exposure >= 1.0 and recent > vol_mult * base and recent > min_vol:
                    exposure = derisk_frac
                elif exposure < 1.0 and (recent < calm_mult * base or recent < min_vol):
                    exposure = 1.0
        exps.append(exposure)
    return exps


def section1_oda(book_rets, params, conventions=CONVENTIONS_BPS) -> Dict[str, object]:
    """ODA per book. K=0 is the deployed organ and it is printed in the same table, not beside
    it, so the reader can see the control and the candidate at one glance."""
    print("\n" + "─" * 100)
    print("1. ODA — the overlay is admitted to a book only while that book's own trailing")
    print(f"   drawdown over W days is at least K × the price of a round (2 × toll).")
    print(f"   K=0 ⇒ threshold 0 ⇒ the DEPLOYED organ, reproduced exactly (asserted by test).")
    print(f"   grids fixed before the run: K {K_GRID}  W {W_GRID}")
    out: Dict[str, object] = {}
    for bps in conventions:
        cost = bps / 1e4
        tag = f"{bps} bps" + (" ← DEPLOYED" if bps == int(DEPLOYED_BPS) else "")
        print(f"\n   ── toll = {tag} " + "─" * (78 - len(tag)))
        print(f"{'book':>22}{'raw Cal':>9}{'K=0 (organ)':>14}"
              + "".join(f"{'K=' + fmt(k, 0):>9}" for k in K_GRID[1:])
              + f"{'best K':>9}{'cmp?':>6}")
        for book in sorted(book_rets):
            rets = book_rets[book]
            if is_dead(rets):
                print(f"{book:>22}{'dead':>9}" + f"{'—':>14}"
                      + "".join(f"{'—':>9}" for _ in K_GRID[1:]) + f"{'—':>9}{'—':>6}")
                continue
            eq = _equity(rets)
            raw_apy, raw_dd, raw_cal = metrics(eq)
            ok = comparable(raw_cal, raw_apy)
            cells: List[Tuple[float, ...]] = []
            for k in K_GRID:
                best_cell = None
                for w in W_GRID:
                    adm = oda_admission(eq, w, k, cost) if k > 0 else None
                    try:
                        m = metrics(guarded_path(eq, adm, roundtrip_cost=cost, **params))
                    except Ruin:
                        continue
                    if best_cell is None or (m[2] == m[2] and m[2] > best_cell[2]):
                        best_cell = m
                cells.append(best_cell or (float("nan"),) * 3)
            organ = cells[0]
            best_i = 0
            for i in range(1, len(cells)):
                if cells[i][2] == cells[i][2] and (
                        cells[best_i][2] != cells[best_i][2] or cells[i][2] > cells[best_i][2]):
                    best_i = i
            print(f"{book:>22}{fmt(raw_cal):>9}{fmt(organ[2]):>14}"
                  + "".join(f"{fmt(c[2]):>9}" for c in cells[1:])
                  + f"{fmt(K_GRID[best_i], 0):>9}{('yes' if ok else 'NO'):>6}")
            out[f"{bps}|{book}"] = {
                "raw": [raw_apy, raw_dd, raw_cal], "comparable": ok,
                "by_k": {str(k): list(c) for k, c in zip(K_GRID, cells)},
                "best_k": K_GRID[best_i],
            }
    print("\n   NOTE. 'best K' is the best cell IN SAMPLE and is not a result — the split in")
    print("   section 3 is. Books marked cmp?=NO are excluded from every claim (#93's rule).")
    return out


def section2_controls(book_rets, params) -> Dict[str, object]:
    """INVERSE and ORACLE. #35 died against exactly this pair; the honest thing is to run them
    before believing anything in section 1."""
    print("\n" + "─" * 100)
    print("2. THE CONTROLS. INVERSE admits the overlay only where there is LITTLE to protect")
    print("   (it must be WORSE — if it is not, the gate is not measuring what it claims).")
    print("   ORACLE admits on the FULL-SAMPLE drawdown: LOOK-AHEAD, the ceiling of perfect")
    print(f"   selection, never a result. Toll = deployed {DEPLOYED_BPS:.0f} bps, W = {W_GRID[1]}.")
    print(f"{'book':>22}{'organ Cal':>12}{'ODA Cal':>12}{'INVERSE Cal':>14}{'ORACLE Cal':>13}"
          f"{'cmp?':>6}")
    print("─" * 100)
    cost = DEPLOYED_BPS / 1e4
    w = W_GRID[1]
    out: Dict[str, object] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        if is_dead(rets):
            continue
        eq = _equity(rets)
        raw_apy, _, raw_cal = metrics(eq)
        ok = comparable(raw_cal, raw_apy)
        row: Dict[str, float] = {}
        organ = metrics(guarded_path(eq, None, roundtrip_cost=cost, **params))
        row["organ"] = organ[2]
        for mode in ("direct", "inverse", "oracle"):
            best = float("nan")
            for k in K_GRID[1:]:
                adm = oda_admission(eq, w, k, cost, mode=mode)
                try:
                    m = metrics(guarded_path(eq, adm, roundtrip_cost=cost, **params))
                except Ruin:
                    continue
                if m[2] == m[2] and (best != best or m[2] > best):
                    best = m[2]
            row[mode] = best
        print(f"{book:>22}{fmt(row['organ']):>12}{fmt(row['direct']):>12}"
              f"{fmt(row['inverse']):>14}{fmt(row['oracle']):>13}{('yes' if ok else 'NO'):>6}")
        row["comparable"] = ok  # type: ignore[assignment]
        out[book] = row
    return out


def section3_split(dates, book_rets, params) -> Dict[str, object]:
    """TRAIN/TEST at the canonical boundary. The gate's K is chosen on TRAIN and JUDGED on TEST;
    picking it on the full sample would make section 1 the answer, and section 1 is not."""
    print("\n" + "─" * 100)
    print(f"3. THE SPLIT — boundary {SPLIT_DATE}, canonical since #79. K chosen on TRAIN by")
    print("   Calmar, then APPLIED UNSEEN to TEST. The TEST column is the only result here.")
    idx = 0
    boundary = datetime.date.fromisoformat(SPLIT_DATE)
    for i, d in enumerate(dates):
        if d <= boundary:
            idx = i
    cost = DEPLOYED_BPS / 1e4
    w = W_GRID[1]
    print(f"   toll = deployed {DEPLOYED_BPS:.0f} bps, W = {w}; TRAIN {idx + 1} d / "
          f"TEST {len(dates) - idx - 1} d")
    print(f"{'book':>22}{'K*(train)':>11}{'TEST organ APY%':>17}{'TEST organ DD%':>16}"
          f"{'TEST ODA APY%':>15}{'TEST ODA DD%':>14}{'ΔCal':>9}{'cmp?':>6}")
    print("─" * 100)
    out: Dict[str, object] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        if is_dead(rets):
            continue
        tr, te = rets[:idx + 1], rets[idx + 1:]
        if is_dead(te):
            print(f"{book:>22}{'—':>11}{'no TEST data (book absent in 2026)':>67}")
            out[book] = {"verdict": "dead in TEST"}
            continue
        eq_tr, eq_te = _equity(tr), _equity(te)
        best_k, best_cal = 0.0, float("-inf")
        for k in K_GRID:
            adm = oda_admission(eq_tr, w, k, cost) if k > 0 else None
            try:
                m = metrics(guarded_path(eq_tr, adm, roundtrip_cost=cost, **params))
            except Ruin:
                continue
            if m[2] == m[2] and m[2] != float("inf") and m[2] > best_cal:
                best_k, best_cal = k, m[2]
        raw_apy_te, _, raw_cal_te = metrics(eq_te)
        ok = comparable(raw_cal_te, raw_apy_te)
        organ = metrics(guarded_path(eq_te, None, roundtrip_cost=cost, **params))
        adm = oda_admission(eq_te, w, best_k, cost) if best_k > 0 else None
        oda = metrics(guarded_path(eq_te, adm, roundtrip_cost=cost, **params))
        dcal = oda[2] - organ[2] if (oda[2] == oda[2] and organ[2] == organ[2]) else float("nan")
        print(f"{book:>22}{fmt(best_k, 0):>11}{organ[0]:>17.2f}{organ[1]:>16.2f}"
              f"{oda[0]:>15.2f}{oda[1]:>14.2f}{fmt(dcal):>9}{('yes' if ok else 'NO'):>6}")
        out[book] = {"k_train": best_k, "test_organ": list(organ), "test_oda": list(oda),
                     "test_raw": [raw_apy_te, _, raw_cal_te], "comparable": ok,
                     "d_calmar": dcal}
    return out


def section4_lockout(book_rets) -> Dict[str, object]:
    """THE HONEST LIMIT, measured rather than disclaimed.

    The gate is a trailing statistic, so it is structurally LATE: a book quiet for W days and
    then breaking is gated OFF on the day it breaks. This section counts how much of each
    book's actual tail fell on days when the gate was CLOSED. A gate that saves churn by
    standing down through the crisis has not improved anything; it has moved the cost.
    """
    print("\n" + "─" * 100)
    print("4. GATE LOCKOUT ON THE TAIL — the structural failure mode of the idea, counted.")
    print("   'tail days' = the book's worst 5 % of daily returns. 'locked out' = the gate was")
    print(f"   CLOSED on such a day. W = {W_GRID[1]}, toll = deployed {DEPLOYED_BPS:.0f} bps.")
    print(f"{'book':>22}{'K':>5}{'gate open %':>13}{'tail days':>11}{'locked out':>12}"
          f"{'lockout % of tail':>19}{'worst day locked?':>19}")
    print("─" * 100)
    cost = DEPLOYED_BPS / 1e4
    w = W_GRID[1]
    out: Dict[str, object] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        if is_dead(rets):
            continue
        eq = _equity(rets)
        order = sorted(range(len(rets)), key=lambda i: rets[i])
        n_tail = max(1, len(rets) // 20)
        tail = set(order[:n_tail])
        worst = order[0]
        for k in (2.0, 10.0, 50.0):
            adm = oda_admission(eq, w, k, cost)
            locked = sum(1 for i in tail if not adm[i])
            openpct = 100.0 * sum(1 for a in adm if a) / len(adm)
            print(f"{book:>22}{k:>5.0f}{openpct:>13.1f}{n_tail:>11}{locked:>12}"
                  f"{100.0 * locked / n_tail:>19.1f}"
                  f"{('LOCKED OUT' if not adm[worst] else 'open'):>19}")
            out[f"{book}|K{k:.0f}"] = {"gate_open_pct": openpct, "tail_days": n_tail,
                                       "locked_out": locked,
                                       "worst_day_locked": not adm[worst]}
    return out


def section5_pba(book_rets, params) -> Dict[str, object]:
    """PBA — the cross-sectional form. Equal-weight portfolio of the per-book guarded paths.

    The portfolio convention is #32/#35's (equal weight, overlay applied per book), kept so the
    number is comparable to those entries. #86's finding stands and is NOT overturned here:
    equal-weight DAILY REBALANCING is itself worse than capped buy-and-hold on this panel, so
    the EW portfolio below is a CONTRAST BETWEEN OVERLAY POLICIES, not a claim that this is the
    portfolio one should hold. M = 10 admits every book and is the deployed organ.
    """
    print("\n" + "─" * 100)
    print("5. PBA — rank the books by trailing drawdown each day, admit the overlay to the top M.")
    print("   M=10 admits everyone = the deployed organ. Equal-weight portfolio of the guarded")
    print("   book paths (#32/#35 convention). #86 stands: EW daily rebalancing is NOT the")
    print("   portfolio to hold — this table contrasts OVERLAY POLICIES on a fixed portfolio.")
    cost = DEPLOYED_BPS / 1e4
    w = W_GRID[1]
    live = [b for b in sorted(book_rets) if not is_dead(book_rets[b])]
    eqs = {b: _equity(book_rets[b]) for b in live}
    dds = {b: trailing_maxdd(eqs[b], w) for b in live}
    n = len(book_rets[live[0]])
    out: Dict[str, object] = {}
    print(f"{'policy':>28}{'APY%':>10}{'maxDD%':>10}{'Calmar':>10}{'vs organ ΔCal':>15}")
    print("─" * 100)
    organ_cal = None
    for m in M_GRID:
        adm: Dict[str, List[bool]] = {b: [False] * n for b in live}
        for i in range(n):
            rank = sorted(live, key=lambda b: -dds[b][i])
            for b in rank[:m]:
                adm[b][i] = True
        paths = {}
        for b in live:
            try:
                paths[b] = guarded_path(eqs[b], adm[b], roundtrip_cost=cost, **params)
            except Ruin:
                paths[b] = None
        prets: List[float] = []
        for i in range(n):
            vals = []
            for b in live:
                p = paths[b]
                if p is None or i + 1 >= len(p) or p[i] <= 0:
                    continue
                vals.append(p[i + 1] / p[i] - 1.0)
            prets.append(sum(vals) / len(vals) if vals else 0.0)
        apy, dd, cal = mh._apy(prets) * 100.0, mh._mdd(prets) * 100.0, mh._calmar(prets)
        if m == M_GRID[-1]:
            organ_cal = cal
        label = f"PBA M={m}" + (" ← organ" if m == len(live) else "")
        out[f"M{m}"] = {"apy": apy, "mdd": dd, "calmar": cal}
        print(f"{label:>28}{apy:>10.2f}{dd:>10.2f}{fmt(cal):>10}"
              f"{fmt(cal - organ_cal) if organ_cal is not None else '—':>15}")
    praw: List[float] = []
    for i in range(n):
        praw.append(sum(book_rets[b][i] for b in live) / len(live))
    apy, dd, cal = mh._apy(praw) * 100.0, mh._mdd(praw) * 100.0, mh._calmar(praw)
    out["raw"] = {"apy": apy, "mdd": dd, "calmar": cal}
    print(f"{'NO OVERLAY AT ALL (raw EW)':>28}{apy:>10.2f}{dd:>10.2f}{fmt(cal):>10}"
          f"{fmt(cal - organ_cal) if organ_cal is not None else '—':>15}")
    # BOTH conventions, always, side by side. The key is NEVER the bare `capped_bh_20` any
    # more: an unlabelled benchmark number is precisely how a convention came to be quoted as
    # a measurement for two entries running (#98). Whoever reads these numbers reads which
    # convention produced them in the same breath.
    for dest, label in ((BENCHMARK_CONVENTION, f"#86 BENCHMARK BH 20% {BENCHMARK_CONVENTION}"),
                        (PUBLISHED_CONVENTION, f"#86 control BH 20% {PUBLISHED_CONVENTION}")):
        bh = capped_buy_and_hold(book_rets, live, cap=0.20, cost=cost, destination=dest)
        apy, dd, cal = mh._apy(bh) * 100.0, mh._mdd(bh) * 100.0, mh._calmar(bh)
        out[f"capped_bh_20_{dest}"] = {"apy": apy, "mdd": dd, "calmar": cal}
        print(f"{label:>28}{apy:>10.2f}{dd:>10.2f}{fmt(cal):>10}"
              f"{fmt(cal - organ_cal) if organ_cal is not None else '—':>15}")
    print("\n   The last two rows are MANDATORY for this family since #86: equal-weight daily")
    print("   rebalancing destroys the panel's natural anti-momentum, so beating it is not an")
    print("   achievement. Capped buy-and-hold at the T2 ceiling of 20 %/book is investable and")
    print("   is the bar. Any policy above that does not clear it has not found anything.")
    print(f"   The bar is built with the {BENCHMARK_CONVENTION!r} convention since 2026-09-03")
    print(f"   (owner decision, ADR-218): a forced sale does not force-buy anybody. The")
    print(f"   {PUBLISHED_CONVENTION!r} row is the convention #86/#96 were PUBLISHED under and is")
    print("   kept beside it — those numbers are not rewritten, they are labelled.")
    return out


def capped_buy_and_hold(book_rets, live, *, cap: float, cost: float,
                        destination: str = BENCHMARK_CONVENTION) -> List[float]:
    """#86's base 2, the family's mandatory benchmark: buy and hold, trimmed back whenever a
    book drifts past the T2 concentration ceiling. Turnover of the trim is charged at `cost`.

    #86 measured that the naive winner (uncapped EW buy-and-hold) is NOT INVESTABLE — it ends
    with 34.76 % in one name against a 20 % ceiling. Quoting it as a benchmark would be
    comparing against a portfolio the risk policy forbids.

    `destination` says where the FORCED sale proceeds go, and it is the reason this signature
    grew a parameter on 2026-09-03: until #98 TPD asked, the answer was `"prorata"` and it was
    never a decision — it was the first thing the code did, quoted ever since as a measurement.
    The default is now `BENCHMARK_CONVENTION`; `PUBLISHED_CONVENTION` reproduces #86/#96
    bitwise and is kept forever as the control column.

    TOLL. A redistributing destination pays BOTH legs (sell + buy). `"cash"` has no buy leg and
    pays one. That is itself a choice; #98 printed the two-leg variant of `cash` beside it and
    the verdict does not depend on it (Calmar 6.69 against 6.70).
    """
    if destination not in TRIM_DESTINATIONS:
        raise ValueError(
            f"unknown trim destination {destination!r} — the benchmark refuses to guess where "
            f"forced sale proceeds go. Known: {', '.join(TRIM_DESTINATIONS)}.")
    # Feasibility is a property OF THE DESTINATION, not of the ceiling alone: under `cash` the
    # capital a tight ceiling cannot hold simply leaves the risk book, so a cap that `prorata`
    # cannot satisfy is perfectly well defined here. Refusing both would be a refusal copied
    # rather than reasoned.
    if destination == "prorata" and len(live) * cap < 1.0 - 1e-12:
        raise ValueError(
            f"a {cap:.0%} cap over {len(live)} books cannot hold 100 % of the capital. "
            "Returning a silently-breached path would put an infeasible portfolio in the "
            "benchmark column, which is worse than refusing.")
    n = len(book_rets[live[0]])
    w = {b: 1.0 / len(live) for b in live}
    cash = 0.0
    out = [1.0]
    for i in range(n):
        # `w` are fractions of TOTAL NAV and the cash sleeve earns exactly 0, so it contributes
        # nothing to the day's return and simply dilutes. A cash yield of 0 is a CONVENTION and
        # not a measurement (#98): the tree's stable sleeve is not zero, and quoting any number
        # for it would put an invented figure inside the benchmark.
        r = sum(w[b] * book_rets[b][i] for b in live)
        nav = out[-1] * (1.0 + r)
        if 1.0 + r <= 0:
            out.append(0.0)
            break
        for b in live:
            w[b] = w[b] * (1.0 + book_rets[b][i]) / (1.0 + r)
        cash = cash / (1.0 + r)
        traded, moved = _trim(w, cap, destination)
        cash += moved
        # The cash sleeve is CHECKED, not merely tracked. Written down because the first
        # version of this function tracked it and never read it: dropping the dilution line
        # above then changed nothing any test could see, which is a benchmark quietly holding
        # more than 100 % of its own capital. Weights are NAV fractions, so books plus sleeve
        # must be exactly one, every day, under both conventions.
        if abs(sum(w.values()) + cash - 1.0) > 1e-9:
            raise ValueError(
                f"capital is not conserved on day {i}: books {sum(w.values()):.12f} + cash "
                f"{cash:.12f} != 1. Refusing rather than printing a benchmark that invented "
                "or lost capital.")
        if max(w.values()) > cap + 1e-9:
            raise ValueError(
                f"the cap was still breached after trimming on day {i} "
                f"(max weight {max(w.values()):.4f} > {cap:.2f}). A benchmark that breaches the "
                "T2 ceiling is not the investable benchmark #86 requires — refusing to print it.")
        if traded:
            nav *= (1.0 - cost * (1.0 if destination == "cash" else 2.0) * traded)
        out.append(nav)
    return [out[i + 1] / out[i] - 1.0 for i in range(len(out) - 1) if out[i] > 0]


def trim_to_cap(w: Dict[str, float], cap: float) -> float:
    """Trim every over-cap weight back to `cap`, pro-rata into the rest. Returns the amount moved.

    The PUBLISHED convention of #86/#96, kept under its own honest name. New code should call
    `_trim(w, cap, destination)` and say which convention it means.
    """
    traded, to_cash = _trim(w, cap, "prorata")
    assert to_cash == 0.0, "pro-rata redistribution must not leak capital into cash"
    return traded


def _trim(w: Dict[str, float], cap: float, destination: str) -> Tuple[float, float]:
    """Trim every over-cap weight back to `cap` and send the excess where `destination` says.

    Returns (traded, to_cash). Iterated to a fixed point ON PURPOSE: one pass can push a
    previously under-cap book OVER the cap, and a single pass would then leave the portfolio
    silently in breach. `capped_buy_and_hold` re-checks the invariant after calling this and
    REFUSES rather than print a breached benchmark.
    """
    if destination not in TRIM_DESTINATIONS:
        raise ValueError(f"unknown trim destination {destination!r}")
    live = list(w)
    traded = 0.0
    to_cash = 0.0
    for _ in range(len(live) + 1):
        over = {b: w[b] - cap for b in live if w[b] > cap + 1e-15}
        if not over:
            break
        excess = sum(over.values())
        traded += excess
        for b in over:
            w[b] = cap
        if destination == "cash":
            # The proceeds leave the risk book. Nothing can be pushed over the ceiling by a
            # payment that never happens, so this branch converges on the first pass.
            to_cash += excess
            continue
        # Receivers must be STRICTLY below the cap. Paying into a book that already sits AT
        # the cap pushes it over again on the next pass, and the loop then oscillates instead
        # of converging — caught by the two-pass fixture in the acceptance tests.
        under = [b for b in live if w[b] < cap - 1e-15]
        base = sum(w[b] for b in under)
        if base <= 0:
            raise ValueError(
                "every book is at the cap and capital is still over-allocated — the cap cannot "
                "hold this portfolio. Refusing rather than printing a breached benchmark.")
        for b in under:
            w[b] += excess * w[b] / base
    return traded, to_cash


def section6_verdict(res) -> None:
    """The out-of-sample line, on comparable books only, said in one place."""
    print("\n" + "─" * 100)
    print("6. THE OUT-OF-SAMPLE LINE — comparable books only (#93's rule), K chosen on TRAIN.")
    print("   Both columns are printed because a Calmar that rises while the DRAWDOWN also")
    print("   rises is an income result, not a risk result, and selling it as the second would")
    print("   be exactly the thing this registry exists not to do.")
    print(f"{'book':>22}{'ΔAPY pp':>10}{'ΔDD pp (− = deeper)':>22}{'ΔCalmar':>12}{'reads as':>28}")
    print("─" * 100)
    for book, v in sorted(res["split"].items()):
        if not isinstance(v, dict) or not v.get("comparable") or "test_oda" not in v:
            continue
        o, g = v["test_organ"], v["test_oda"]
        dapy, ddd = g[0] - o[0], abs(o[1]) - abs(g[1])
        dcal = v["d_calmar"]
        if abs(dapy) < 1e-9 and abs(ddd) < 1e-9:
            reads = "gate never bound"
        elif dapy > 0 and ddd > 0:
            reads = "income UP and risk DOWN"
        elif dapy > 0 and ddd <= 0:
            reads = "income up, DRAWDOWN DEEPER"
        elif dapy <= 0 and ddd > 0:
            reads = "risk down, income given up"
        else:
            reads = "worse on both"
        print(f"{book:>22}{dapy:>10.2f}{ddd:>22.2f}{fmt(dcal):>12}{reads:>28}")


def run(dates, book_rets) -> Dict[str, object]:
    params = {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}
    print("\n" + "=" * 100)
    print("Ideas ODA + PBA — WHERE the overlay is allowed to run, decided causally.  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_rets)}  ·  {dates[0]} … {dates[-1]} ({len(dates)} days)")
    print(f"  guardian parameters, IMPORTED from the deployed organ: {params}")
    print(f"  deployed toll: {DEPLOYED_BPS:.0f} bps — a CONVENTION with no date and no source"
          " (#92/#93)")
    print("=" * 100)
    res = {
        "instrument": section0_instrument(book_rets, params),
        "identity": section0b_identity(book_rets, params),
        "oda": section1_oda(book_rets, params),
        "controls": section2_controls(book_rets, params),
        "split": section3_split(dates, book_rets, params),
        "lockout": section4_lockout(book_rets),
        "pba": section5_pba(book_rets, params),
    }
    section6_verdict(res)
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None,
                    help="write the measured numbers to this path (never under data/)")
    args = ap.parse_args(argv)
    # Argument checks BEFORE the panel is loaded. Two reasons, and the second is the sharper:
    # refusing a bad destination after doing all the work is wasteful, and — because the panel
    # is absent from a worktree BY CONSTRUCTION — a refusal placed after the load would have its
    # verdict decided by which tree it runs in rather than by the argument it is judging.
    if args.json and "data/" in str(args.json).replace("\\", "/"):
        print("REFUSAL: this harness does not write under data/.", file=sys.stderr)
        return 2
    dates, book_rets = gtn.load_real_panel()
    if not book_rets:
        print("REFUSAL: the panel is empty. An empty table would read as 'no books', which is a "
              "different statement from 'the panel is not here'.", file=sys.stderr)
        return 2
    res = run(dates, book_rets)
    res["panel"] = {"days": len(dates), "from": str(dates[0]), "to": str(dates[-1]),
                    "books": sorted(book_rets)}
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
