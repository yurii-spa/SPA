#!/usr/bin/env python3
"""
scripts/edge_downside_parity.py — registry ideas #105 (DSP) and #106 (TDC).

ADVISORY / PAPER-ONLY / OUTSIDE_RISKPOLICY. This module moves no capital, touches no live track,
imports nothing from spa_core/execution, and changes no RiskPolicy threshold. stdlib only.

════════════════════════════════════════════════════════════════════════════════════════════
#105 DSP — Downside-Semideviation Parity
────────────────────────────────────────────────────────────────────────────────────────────
#17 measured cross-sectional risk parity on the real panel with INVERSE TOTAL VOLATILITY.
Total volatility charges a book for its UPSIDE moves, so a book whose variance is mostly
gains is under-weighted for being profitable. DSP replaces the denominator with the downside
semideviation — the same parity idea, but paying only for the half of the distribution that
can actually hurt.

#30 (SKD) already argued this mechanism and found EXACTLY ZERO difference — but on the
SYNTHETIC cross-desk fixture, where semivariance and variance are proportional by
construction, so the fixture could not exhibit the effect it was asked about. On the real
panel it can: the semidev/vol ratio spans 0.044 (`susde_dn`) to 0.868 (`levered_restaking`),
a twentyfold spread, and the causal ROLLING rankings of the two denominators disagree on
68.5 % of days at lookback 20. Whether the disagreement is worth anything is the question
this module answers.

#104 (CCC) de-risks a book whose realized carry compressed below its headline. That is a
switch driven by RETURN. DSP is a continuous weighting driven by the SHAPE of risk. Neither
reads the other's signal.

════════════════════════════════════════════════════════════════════════════════════════════
#106 TDC — Tail-Coincidence Discount
────────────────────────────────────────────────────────────────────────────────────────────
Parity equalises how much risk each book carries; it says nothing about WHEN that risk lands.
Two books with identical semideviation are not interchangeable if one loses on the days the
whole panel loses. TDC multiplies the DSP weight by (1 − coincidence), where coincidence is
the share of the trailing window's worst panel days on which the book was also negative.

#44 (RCD) demoted by redundancy measured as full-sample correlation; #2 by static pairwise
correlation on a two-book fixture. Coincidence is neither: it is a count taken only on the
days that made the tail, and it is estimated causally in a rolling window.

════════════════════════════════════════════════════════════════════════════════════════════
WHAT THIS MODULE REFUSES TO DO
────────────────────────────────────────────────────────────────────────────────────────────
  • §0 is a gate, not a report. Any control that cannot be MEASURED is a refusal, not a pass:
    "could not check" and "checked and fine" are not allowed to share an exit code.
  • A book whose volatility is exactly zero is never floored into a giant inverse weight. It
    is excluded by name with the measured reason. `points_farm` is that book (annVol 0.00 %
    over 852 days, 6.18 % CAGR — deterministic drift, the degeneracy #17's recount named).
  • The roundtrip cost is NOT picked. #92/#93 measured that this tree quotes the same trade at
    three different prices (8 / 15 / 96 bps) and that the 96 bps convention was never a cost at
    all. Every verdict here is therefore reported across the whole grid, and a verdict that
    survives at 0 bps but not at 15 bps is reported as exactly that.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import edge_real_panel_ensemble as ens  # noqa: E402  (the clean, phase-aware panel loader)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

TRAIN_END = ens.TRAIN_END  # "2025-06-30" — the branch's split, not a new one

# Daily-return floor for every inverse-risk denominator. NOT a taste, and its size was chosen by
# MEASUREMENT: the quietest book that survives universe selection (`susde_dn`) has a full-sample
# daily semideviation of 1.9e-05, so the first floor tried here — 1e-04 — bound on the BOOK and
# would have set that book's weight by the knob rather than by its data. 1e-06 sits two orders
# below it: on the full sample it binds on nothing. It still binds on WINDOWS, and how often it
# does is the degeneracy DSP has and inverse-vol does not — measured in §1c, not assumed away.
# Swept in §5.
RISK_FLOOR = 1e-6

# Roundtrip cost grid in basis points. See the module docstring: this tree quotes one trade at
# three prices, so no single number is used.
COST_GRID_BPS = (0.0, 8.0, 15.0, 96.0)

LOOKBACK_GRID = (10, 20, 60)
# Every scheme in a comparison is scored from the SAME first day — the longest lookback on the
# grid — so that "more days in the sample" can never be mistaken for "better scheme".
WARMUP = max(LOOKBACK_GRID)
CAP_GRID = (1.00, 0.60, 0.40)

# #17's published clean-panel table (recount 2026-08-02). The positive control of the data path.
PUBLISHED_17 = {
    "pendle_yt_susde": (121.4, -0.9),
    "pendle_pt_levered": (74.1, -19.1),
    "susde_dn": (17.9, -0.05),
    "susde_spot": (16.1, -6.9),
    "points_farm": (6.2, 0.0),
}


# ══════════════════════════════════════════════════════════════════════════════════════════
# risk estimators — every one takes a window that ENDS THE DAY BEFORE the day it weights
# ══════════════════════════════════════════════════════════════════════════════════════════
def stdev(window: Sequence[float]) -> float:
    n = len(window)
    if n < 2:
        return 0.0
    mean = sum(window) / n
    return math.sqrt(sum((x - mean) ** 2 for x in window) / (n - 1))


def semideviation(window: Sequence[float]) -> float:
    """Root mean square of the NEGATIVE returns, divided by the FULL window length.

    The denominator is n, not the number of negative days: dividing by the count of losses
    would make a window with one small loss look riskier than a window with ten, which is the
    opposite of what the measure is for.
    """
    n = len(window)
    if n == 0:
        return 0.0
    down = [x for x in window if x < 0.0]
    if not down:
        return 0.0
    return math.sqrt(sum(x * x for x in down) / n)


def coincidence(window_by_book: Dict[str, Sequence[float]], book: str, tail_frac: float = 0.10
                ) -> float:
    """Share of the window's WORST panel days on which `book` was also negative.

    The panel day is the equal-weight return of the window's books; the worst `tail_frac` of
    those days is the tail. A book that never loses on a tail day scores 0 (fully idiosyncratic
    loss timing); one that always does scores 1.
    """
    books = sorted(window_by_book)
    n = len(window_by_book[books[0]]) if books else 0
    if n == 0 or book not in window_by_book:
        return 0.0
    panel = [sum(window_by_book[b][i] for b in books) / len(books) for i in range(n)]
    k = max(1, int(round(n * tail_frac)))
    worst = sorted(range(n), key=lambda i: panel[i])[:k]
    return sum(1 for i in worst if window_by_book[book][i] < 0.0) / k


# ══════════════════════════════════════════════════════════════════════════════════════════
# weighting schemes — signature (window_by_book, books) -> {book: weight}, weights sum to 1
# ══════════════════════════════════════════════════════════════════════════════════════════
def _normalise(raw: Dict[str, float], books: Sequence[str]) -> Dict[str, float]:
    total = sum(raw.values())
    if total <= 0:
        return {b: 1.0 / len(books) for b in books}
    return {b: raw[b] / total for b in books}


def w_equal(window_by_book, books, floor=RISK_FLOOR):
    return {b: 1.0 / len(books) for b in books}


def w_inverse_vol(window_by_book, books, floor=RISK_FLOOR):
    return _normalise({b: 1.0 / max(stdev(window_by_book[b]), floor) for b in books}, books)


def w_downside_parity(window_by_book, books, floor=RISK_FLOOR):
    return _normalise({b: 1.0 / max(semideviation(window_by_book[b]), floor) for b in books},
                      books)


def make_tail_coincidence(tail_frac: float = 0.10) -> Callable:
    def w(window_by_book, books, floor=RISK_FLOOR):
        raw = {}
        for b in books:
            base = 1.0 / max(semideviation(window_by_book[b]), floor)
            raw[b] = base * (1.0 - coincidence(window_by_book, b, tail_frac))
        return _normalise(raw, books)
    return w


w_tail_coincidence = make_tail_coincidence(0.10)


SCHEMES: Dict[str, Callable] = {
    "EW": w_equal,
    "IVOL#17": w_inverse_vol,
    "DSP#105": w_downside_parity,
    "TDC#106": w_tail_coincidence,
}


def apply_cap(weights: Dict[str, float], cap: float) -> Dict[str, float]:
    """Cap any single weight at `cap`, spilling the excess onto the UNCAPPED books pro rata.

    Water-filling, and the capped set only ever GROWS. The first version re-derived that set
    from scratch each pass, so a book sitting exactly AT the cap counted as free and received
    spill on the very next pass — with three books and cap 0.40 it came out at 0.53, i.e. the
    cap did not hold on the numbers the cap was there to produce. Found by the test, not by
    reading: one pass looked obviously right and two passes looked obviously convergent.
    """
    if cap >= 1.0:
        return dict(weights)
    if cap * len(weights) < 1.0 - 1e-12:
        raise ValueError(
            f"cap {cap} over {len(weights)} books cannot hold a full portfolio "
            f"(capacity {cap * len(weights):.3f} < 1) — refusing to return weights that miss it")
    w = dict(weights)
    capped: set = set()
    for _ in range(len(w) + 1):
        newly = {b for b, v in w.items() if b not in capped and v > cap + 1e-12}
        if not newly:
            break
        capped |= newly
        excess = sum(w[b] - cap for b in newly)
        for b in newly:
            w[b] = cap
        free = [b for b in w if b not in capped]
        free_total = sum(w[b] for b in free)
        if not free:
            break
        if free_total <= 0:
            for b in free:
                w[b] += excess / len(free)
        else:
            for b in free:
                w[b] += excess * (w[b] / free_total)
    return w


# ══════════════════════════════════════════════════════════════════════════════════════════
# the backtest — one pass, strictly causal, turnover charged
# ══════════════════════════════════════════════════════════════════════════════════════════
def run_scheme(rets: Dict[str, List[float]], books: Sequence[str], scheme: Callable,
               lookback: int, cap: float, cost_bps: float, floor: float = RISK_FLOOR,
               same_bar: bool = False,
               permute: Optional[Dict[str, str]] = None,
               warmup: int = 0) -> Dict[str, object]:
    """Portfolio returns of `scheme` over the whole series.

    `permute` is the PLACEBO: it keeps the day's weight vector exactly and only changes which
    book receives which weight. If the scheme's edge is in the SHAPE of its weights rather than
    in the identification of which book deserves them, a permutation loses nothing.

    `same_bar=True` is the CAUSALITY MUTATION, not an option anyone should use: it lets the
    window end on the day being weighted. It exists so that "this is causal" is a claim a test
    can falsify, rather than a sentence in a docstring.
    """
    n = len(rets[books[0]])
    cost = cost_bps / 10_000.0
    # A scheme with a 20-day lookback would otherwise be SCORED over 40 more days than one with
    # a 60-day lookback, and the extra days are not a property of the scheme. `warmup` pins the
    # first scored day for every scheme in a comparison, so the columns are the same sample.
    start = max(lookback, warmup)
    port: List[float] = []
    turnover: List[float] = []
    weight_hist: List[Dict[str, float]] = []
    prev: Optional[Dict[str, float]] = None
    for t in range(start, n):
        end = t + 1 if same_bar else t
        window = {b: rets[b][end - lookback:end] for b in books}
        w = apply_cap(scheme(window, books, floor), cap)
        if permute is not None:
            # PLACEBO: keep the weight VECTOR, destroy which book each weight belongs to.
            w = {permute[b]: w[b] for b in books}
        gross = sum(w[b] * rets[b][t] for b in books)
        churn = 0.0 if prev is None else sum(abs(w[b] - prev[b]) for b in books) / 2.0
        port.append(gross - churn * cost)
        turnover.append(churn)
        weight_hist.append(w)
        # the weight drifts with the realised returns before the next rebalance
        if gross > -1.0:
            prev = _normalise({b: w[b] * (1.0 + rets[b][t]) for b in books}, books)
        else:
            prev = w
    return {"rets": port, "turnover": turnover, "weights": weight_hist}


def metrics(port: Sequence[float]) -> Dict[str, float]:
    return ens.perf(list(port))


def fmt_pct(x: float) -> str:
    return "—" if x != x else f"{x * 100:.2f}%"


def fmt_cal(x: float) -> str:
    if x != x:
        return "—"
    if x in (float("inf"), float("-inf")):
        return "∞"
    return f"{x:.2f}"


def rankable(m: Dict[str, float]) -> bool:
    """A Calmar of ∞ (no drawdown at all) is not a score — it is the absence of a denominator.

    Selecting on it would make "never fell in the training half" beat every real trade-off, so
    configurations with no drawdown are excluded from SELECTION and named in the output.
    """
    c = m["calmar"]
    return c == c and c not in (float("inf"), float("-inf"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# §0 — the gate. Every control here has to be MEASURED; unmeasured is a refusal.
# ══════════════════════════════════════════════════════════════════════════════════════════
def section0_controls(panel, axis) -> Dict[str, object]:
    print("=" * 100)
    print("0. CONTROLS — the gate. An unmeasured control is a REFUSAL, not a pass.")
    print("=" * 100)
    out: Dict[str, object] = {"failures": []}

    # C1 — the data path is the one the registry published on.
    print("\n C1. Replay #17's published clean-panel table (tolerance 0.1 pp):")
    c1_rows = []
    for book, (apy_pub, dd_pub) in sorted(PUBLISHED_17.items()):
        if book not in panel:
            out["failures"].append(f"C1: book {book} absent from the panel")
            print(f"     {book:20} ABSENT — cannot replay")
            continue
        m = ens.perf([panel[book][d] for d in axis])
        d_apy = abs(m["apy"] * 100 - apy_pub)
        d_dd = abs(m["maxdd"] * 100 - dd_pub)
        ok = d_apy <= 0.1 and d_dd <= 0.1
        c1_rows.append((book, m["apy"] * 100, apy_pub, m["maxdd"] * 100, dd_pub, ok))
        if not ok:
            out["failures"].append(
                f"C1: {book} {m['apy']*100:.2f}%/{m['maxdd']*100:.2f}% vs published "
                f"{apy_pub}%/{dd_pub}%")
        print(f"     {book:20} APY {m['apy']*100:7.2f}% (pub {apy_pub:6.1f}) "
              f"maxDD {m['maxdd']*100:7.2f}% (pub {dd_pub:6.2f})  {'ok' if ok else 'MISMATCH'}")
    out["c1"] = c1_rows

    # C2 — the loader in use is the CLEAN one, not the phase-blind one #16/#17 were computed on.
    print("\n C2. Phase-glue control — the OLD phase-blind loader must still fabricate its seam:")
    art = ens.glue_artifact()
    worst = max(art.items(), key=lambda kv: abs(kv[1]["seam_ret"]), default=None)
    if worst is None or abs(worst[1]["seam_ret"]) < 0.30:
        out["failures"].append("C2: no seam artifact found — cannot show this loader is the clean one")
        print("     NO SEAM FOUND — refusing: the control cannot distinguish the two loaders")
    else:
        print(f"     worst seam: {worst[0]} {worst[1]['seam_ret']*100:+.2f}% one-day move under the")
        print(f"     phase-blind loader; the loader used here does not contain that day at all.")
    out["c2_worst_seam"] = None if worst is None else [worst[0], worst[1]["seam_ret"]]

    # C3 — the degenerate book must be excluded BY MEASUREMENT, and it must be the named one.
    print("\n C3. Degenerate-weight control — a book with NO downside must be excluded, not floored.")
    print("     The rule has to be exercised by this panel, or it is a rule nothing tests:")
    degenerate = []
    for b in sorted(panel):
        r = [panel[b][d] for d in axis]
        if semideviation(r) == 0.0:
            degenerate.append(b)
    if not degenerate:
        out["failures"].append(
            "C3: no zero-downside book on the panel — the exclusion rule is unexercised")
        print("     NO ZERO-DOWNSIDE BOOK — refusing: the rule this run relies on is untested here")
    else:
        quietest = min(
            (semideviation([panel[b][d] for d in axis]) for b in panel
             if semideviation([panel[b][d] for d in axis]) > 0.0))
        print(f"     zero-downside books: {', '.join(degenerate)} "
              f"(semideviation exactly 0.0 over {len(axis)} days).")
        print(f"     Floored instead of excluded, each would carry raw weight {1.0/RISK_FLOOR:,.0f}")
        print(f"     against {1.0/quietest:,.0f} for the quietest book that DOES have a downside —")
        print(f"     i.e. a {1.0/RISK_FLOOR/(1.0/quietest):.1f}× edge handed out by the knob, not the data.")
    out["c3_degenerate"] = degenerate
    return out


def section0b_causality(rets, books) -> Dict[str, object]:
    """C4 — the causality claim has to be falsifiable, so measure what breaking it changes."""
    print("\n C4. Causality control — same-bar mutation must MOVE the result (else the claim")
    print("     'strictly causal' is an ornament: true by construction, tested by nothing):")
    out = {}
    for name in ("DSP#105", "TDC#106", "IVOL#17"):
        causal = run_scheme(rets, books, SCHEMES[name], 20, 1.0, 0.0, warmup=WARMUP)
        peeking = run_scheme(rets, books, SCHEMES[name], 20, 1.0, 0.0, same_bar=True,
                             warmup=WARMUP)
        mc, mp = metrics(causal["rets"]), metrics(peeking["rets"])
        moved = any(abs(a - b) > 1e-12 for a, b in zip(causal["rets"], peeking["rets"]))
        print(f"     {name:9} causal APY {fmt_pct(mc['apy']):>9} maxDD {fmt_pct(mc['maxdd']):>9}"
              f"  |  same-bar APY {fmt_pct(mp['apy']):>9} maxDD {fmt_pct(mp['maxdd']):>9}"
              f"  {'MOVED' if moved else 'IDENTICAL — control is an ornament'}")
        out[name] = {"moved": moved, "causal": mc, "same_bar": mp}
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════
# §1 — universe: which books carry a daily mark at all
# ══════════════════════════════════════════════════════════════════════════════════════════
def section1_universe(panel, axis) -> Tuple[List[str], Dict[str, object]]:
    print("\n" + "=" * 100)
    print("1. UNIVERSE — #17 could not be closed because six of ten 'books' barely move.")
    print("   The sub-panel is SELECTED BY MEASUREMENT here, not assumed.")
    print("=" * 100)
    print("   Clause (a): a book with FLAT days has no daily mark — #17 could not be closed for")
    print("   exactly this reason. Clause (b): a book with NO negative day has no downside")
    print("   denominator at all, so its inverse-semideviation weight would be set by the floor,")
    print("   i.e. by a knob of this script rather than by the book.")
    print(f"{'book':>20}{'flat days':>12}{'neg':>7}{'annVol':>9}{'semidev':>10}{'semi/vol':>10}"
          f"{'APY':>10}{'maxDD':>10}{'verdict':>20}")
    print("-" * 106)
    universe: List[str] = []
    census = {}
    for book in sorted(panel):
        r = [panel[book][d] for d in axis]
        m = ens.perf(r)
        flat = sum(1 for x in r if abs(x) < 1e-12)
        semi = semideviation(r) * math.sqrt(365)
        ratio = semi / m["vol"] if m["vol"] > 0 else float("nan")
        neg = sum(1 for x in r if x < 0.0)
        if flat != 0:
            why = "no daily mark"          # clause (a) — #17's finding, measured here again
        elif neg == 0:
            why = "no downside at all"     # clause (b) — the denominator does not exist
        else:
            why = ""
        keep = why == ""
        if keep:
            universe.append(book)
        census[book] = {"flat": flat, "neg_days": neg, "vol": m["vol"], "semidev": semi,
                        "ratio": ratio, "apy": m["apy"], "maxdd": m["maxdd"],
                        "in_universe": keep, "excluded_because": why}
        print(f"{book:>20}{flat:>12}{neg:>7}{m['vol']*100:>9.2f}%{semi*100:>9.2f}%"
              f"{('—' if ratio != ratio else f'{ratio:.3f}'):>10}"
              f"{m['apy']*100:>9.2f}%{m['maxdd']*100:>9.2f}%"
              f"{('YES' if keep else why):>20}")
    ratios = [c["ratio"] for c in census.values() if c["ratio"] == c["ratio"] and c["ratio"] > 0]
    print(f"\n   semidev/vol spread across the panel: {min(ratios):.3f} … {max(ratios):.3f}"
          f" ({max(ratios)/min(ratios):.1f}×) — this is the room #105 has to be different from")
    print("   #17 at all. On #30's synthetic fixture the same spread was 1.0× by construction,")
    print("   which is why #30 measured a difference of exactly zero and could not have measured")
    print("   anything else.")
    print(f"   Universe: {', '.join(universe)}")
    return universe, census


def section1b_rank_divergence(rets, books) -> Dict[str, object]:
    print("\n   Rolling RANK divergence (does the downside denominator re-order the books, or")
    print("   only re-scale them?) — a scheme that never re-orders is a concentration dial:")
    out = {}
    n = len(rets[books[0]])
    for lkb in LOOKBACK_GRID:
        same = 0
        total = 0
        for t in range(lkb, n):
            win = {b: rets[b][t - lkb:t] for b in books}
            rv = sorted(books, key=lambda b: -1.0 / max(stdev(win[b]), RISK_FLOOR))
            rs = sorted(books, key=lambda b: -1.0 / max(semideviation(win[b]), RISK_FLOOR))
            total += 1
            same += (rv == rs)
        out[lkb] = {"same": same, "total": total}
        print(f"     lookback {lkb:>3}: identical ordering on {same}/{total} days "
              f"({100.0*same/total:.1f} %) — differs on {100.0*(total-same)/total:.1f} %")
    return out


def section1c_floor_binding(rets, books) -> Dict[str, object]:
    """The degeneracy DSP has and inverse-vol does not: a window with no losing day.

    Total volatility is zero only if a window is CONSTANT; downside semideviation is zero
    whenever a window merely never fell. On a panel of carry books that is not rare, and when
    it happens the weight stops being a measurement of the book and becomes the floor — i.e.
    a constant of this script. Counted, because a degeneracy nobody counts is a degeneracy
    nobody bounds.
    """
    print("\n   Floor-binding frequency (share of book-days where the denominator is ZERO and")
    print("   the weight is therefore set by the floor, not by the book):")
    n = len(rets[books[0]])
    out = {}
    print(f"{'lookback':>12}{'IVOL#17 (sd=0)':>20}{'DSP#105 (semi=0)':>20}{'book-days':>14}")
    print("-" * 70)
    for lkb in LOOKBACK_GRID:
        vz = sz = total = 0
        for t in range(lkb, n):
            for b in books:
                win = rets[b][t - lkb:t]
                total += 1
                vz += stdev(win) == 0.0
                sz += semideviation(win) == 0.0
        out[lkb] = {"ivol_zero": vz, "dsp_zero": sz, "book_days": total}
        print(f"{lkb:>12}{f'{vz} ({100.0*vz/total:.1f} %)':>20}"
              f"{f'{sz} ({100.0*sz/total:.1f} %)':>20}{total:>14}")
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════
# §2/§3 — IS sweep on TRAIN, then the chosen configuration on unseen TEST
# ══════════════════════════════════════════════════════════════════════════════════════════
def _split(axis: Sequence[str]) -> Tuple[int, int]:
    train = [i for i, d in enumerate(axis) if d <= TRAIN_END]
    return len(train), len(axis) - len(train)


def sweep(rets, books, idx_lo, idx_hi, cost_bps) -> Dict[Tuple[str, int, float], Dict]:
    sub = {b: rets[b][idx_lo:idx_hi] for b in books}
    out = {}
    for name, fn in SCHEMES.items():
        for lkb in LOOKBACK_GRID:
            for cap in CAP_GRID:
                if name == "EW" and cap < 1.0:
                    continue  # equal weight is already below every cap in a 4-book universe
                res = run_scheme(sub, books, fn, lkb, cap, cost_bps, warmup=WARMUP)
                m = metrics(res["rets"])
                m["turnover"] = sum(res["turnover"]) / max(1, len(res["turnover"]))
                out[(name, lkb, cap)] = m
    return out


def section2_train(rets, books, n_train, cost_bps) -> Dict[str, object]:
    print("\n" + "=" * 100)
    print(f"2. TRAIN (≤ {TRAIN_END}) — in-sample sweep at {cost_bps:.0f} bps roundtrip")
    print("=" * 100)
    res = sweep(rets, books, 0, n_train, cost_bps)
    print(f"{'scheme':>10}{'lkb':>5}{'cap':>6}{'APY':>10}{'maxDD':>10}{'Calmar':>9}"
          f"{'vol':>9}{'turnover/d':>12}")
    print("-" * 100)
    best: Dict[str, Tuple] = {}
    for (name, lkb, cap), m in sorted(res.items()):
        print(f"{name:>10}{lkb:>5}{cap:>6.2f}{fmt_pct(m['apy']):>10}{fmt_pct(m['maxdd']):>10}"
              f"{fmt_cal(m['calmar']):>9}{fmt_pct(m['vol']):>9}{m['turnover']*100:>11.2f}%")
        if rankable(m) and (name not in best or m["calmar"] > best[name][1]["calmar"]):
            best[name] = ((name, lkb, cap), m)
    unrankable = [k for k, m in res.items() if not rankable(m)]
    if unrankable:
        print(f"\n   Excluded from SELECTION (Calmar has no denominator — zero drawdown on TRAIN): "
              f"{len(unrankable)} of {len(res)} configurations.")
        for k in sorted(unrankable):
            print(f"     {k[0]} lkb={k[1]} cap={k[2]:.2f}: APY {fmt_pct(res[k]['apy'])}, maxDD 0.00%")
    print("\n   TRAIN-chosen configuration per scheme (by Calmar, ∞ excluded):")
    for name, (key, m) in sorted(best.items()):
        print(f"     {name:>10} lkb={key[1]:>3} cap={key[2]:.2f}  →  APY {fmt_pct(m['apy'])}, "
              f"maxDD {fmt_pct(m['maxdd'])}, Calmar {fmt_cal(m['calmar'])}")
    return {"sweep": res, "best": best}


def section3_test(rets, books, n_train, best, cost_bps) -> Dict[str, object]:
    n = len(rets[books[0]])
    print("\n" + "=" * 100)
    print(f"3. TEST (> {TRAIN_END}, unseen) — TRAIN-chosen parameters applied, "
          f"{cost_bps:.0f} bps roundtrip")
    print("=" * 100)
    print(f"{'scheme':>10}{'lkb':>5}{'cap':>6}{'APY':>10}{'maxDD':>10}{'Calmar':>9}"
          f"{'turnover/d':>12}")
    print("-" * 100)
    out = {}
    sub = {b: rets[b][n_train:n] for b in books}
    for name, (key, _train_m) in sorted(best.items()):
        res = run_scheme(sub, books, SCHEMES[name], key[1], key[2], cost_bps, warmup=WARMUP)
        m = metrics(res["rets"])
        m["turnover"] = sum(res["turnover"]) / max(1, len(res["turnover"]))
        out[name] = {"key": list(key), "metrics": m}
        print(f"{name:>10}{key[1]:>5}{key[2]:>6.2f}{fmt_pct(m['apy']):>10}"
              f"{fmt_pct(m['maxdd']):>10}{fmt_cal(m['calmar']):>9}{m['turnover']*100:>11.2f}%")
    return out


def section4_cost_grid(rets, books, n_train) -> Dict[float, Dict[str, object]]:
    print("\n" + "=" * 100)
    print("4. COST GRID — the verdict is reported at every price this tree quotes for the same")
    print("   trade (#92/#93: 8 / 15 / 96 bps, and 96 bps was measured never to be a cost).")
    print("=" * 100)
    out = {}
    n = len(rets[books[0]])
    header = f"{'bps':>6}" + "".join(f"{s:>26}" for s in SCHEMES)
    for half, lo, hi in (("TRAIN", 0, n_train), ("TEST", n_train, n)):
        print(f"\n   {half} — APY / maxDD / Calmar at lookback 20, cap 0.60:")
        print("   " + header)
        for bps in COST_GRID_BPS:
            sub = {b: rets[b][lo:hi] for b in books}
            cells = []
            for name, fn in SCHEMES.items():
                cap = 1.0 if name == "EW" else 0.60
                m = metrics(run_scheme(sub, books, fn, 20, cap, bps, warmup=WARMUP)["rets"])
                cells.append(f"{fmt_pct(m['apy'])}/{fmt_pct(m['maxdd'])}/{fmt_cal(m['calmar'])}")
                out.setdefault(bps, {}).setdefault(half, {})[name] = m
            print(f"   {bps:>6.0f}" + "".join(f"{c:>26}" for c in cells))
    return out


def section5_floor_sensitivity(rets, books, n_train) -> Dict[str, object]:
    print("\n" + "=" * 100)
    print("5. FLOOR SENSITIVITY — the inverse-risk floor is a knob, so its weight is measured.")
    print("=" * 100)
    n = len(rets[books[0]])
    out = {}
    print(f"{'floor (daily)':>16}{'DSP TRAIN Calmar':>20}{'DSP TEST Calmar':>19}"
          f"{'DSP TEST APY':>16}{'DSP TEST maxDD':>17}")
    print("-" * 100)
    for floor in (1e-5, 1e-4, 1e-3):
        tr = metrics(run_scheme({b: rets[b][:n_train] for b in books}, books,
                                w_downside_parity, 20, 0.60, 15.0, floor=floor,
                                warmup=WARMUP)["rets"])
        te = metrics(run_scheme({b: rets[b][n_train:n] for b in books}, books,
                                w_downside_parity, 20, 0.60, 15.0, floor=floor,
                                warmup=WARMUP)["rets"])
        out[floor] = {"train": tr, "test": te}
        print(f"{floor:>16.0e}{fmt_cal(tr['calmar']):>20}{fmt_cal(te['calmar']):>19}"
              f"{fmt_pct(te['apy']):>16}{fmt_pct(te['maxdd']):>17}")
    return out


def w_zero_loss_selector(window_by_book, books, floor=RISK_FLOOR):
    """The crude rule DSP may secretly be: hold only the books that did not fall in the window.

    Not an idea of its own — a CONTROL. If this reproduces DSP, then "downside parity" is a
    name for a loss-free-streak selector and the parity arithmetic is decoration.
    """
    clean = [b for b in books if semideviation(window_by_book[b]) == 0.0]
    if not clean:
        return {b: 1.0 / len(books) for b in books}
    return {b: (1.0 / len(clean) if b in clean else 0.0) for b in books}


def section6_mechanism(rets, books, n_train, key, cost_bps=15.0) -> Dict[str, object]:
    """What is DSP actually doing — parity, or selection? Two controls, both decisive."""
    n = len(rets[books[0]])
    lkb, cap = key[1], key[2]
    train = {b: rets[b][:n_train] for b in books}
    test = {b: rets[b][n_train:n] for b in books}
    print("\n" + "=" * 100)
    print("6. MECHANISM — §1c measured that DSP's denominator is exactly zero on a THIRD of")
    print("   book-days, so on those days the weight is the floor, not the book. Two controls")
    print("   decide whether what was measured is parity or selection.")
    print("=" * 100)
    out: Dict[str, object] = {}

    print("\n 6a. ZERO-LOSS SELECTOR — equal weight among books that simply did not fall in the")
    print("     window (EW when none did). No parity arithmetic at all:")
    print(f"{'':>14}{'TRAIN APY':>12}{'TRAIN maxDD':>14}{'TEST APY':>11}{'TEST maxDD':>13}"
          f"{'TEST Calmar':>13}")
    rows = {"DSP#105": w_downside_parity, "ZLS(control)": w_zero_loss_selector,
            "EW": w_equal}
    for name, fn in rows.items():
        c = 1.0 if name == "EW" else cap
        tr = metrics(run_scheme(train, books, fn, lkb, c, cost_bps, warmup=WARMUP)["rets"])
        te = metrics(run_scheme(test, books, fn, lkb, c, cost_bps, warmup=WARMUP)["rets"])
        out[name] = {"train": tr, "test": te}
        print(f"{name:>14}{fmt_pct(tr['apy']):>12}{fmt_pct(tr['maxdd']):>14}"
              f"{fmt_pct(te['apy']):>11}{fmt_pct(te['maxdd']):>13}{fmt_cal(te['calmar']):>13}")

    print("\n 6b. IDENTITY PLACEBO — all 4! = 24 permutations of which book receives which of")
    print("     DSP's own daily weights. The weight VECTOR is untouched; only the address is.")
    print("     Run on BOTH halves on purpose: the only real drawdown on this sub-panel is in")
    print("     TRAIN (EW falls 6.41 % there against 0.58 % in TEST), so a rank taken only on")
    print("     the unseen half would be a ranking inside a calm period — the exact mistake")
    print("     #1's UPD4 named ('OOS on a calm period does not validate crisis protection').")
    perms = list(itertools.permutations(books))
    out["placebo"] = {"n": len(perms)}
    for half_name, half in (("TRAIN (in-sample, holds the drawdown)", train),
                            ("TEST (unseen, calm)", test)):
        print(f"\n     ── {half_name} ──")
        _placebo_half(half, books, perms, lkb, cap, cost_bps, out["placebo"], half_name)
    return out


def _placebo_half(half, books, perms, lkb, cap, cost_bps, store, half_name) -> None:
    scored = []
    for pm in perms:
        mapping = dict(zip(books, pm))
        m = metrics(run_scheme(half, books, w_downside_parity, lkb, cap, cost_bps,
                               permute=mapping, warmup=WARMUP)["rets"])
        scored.append((tuple(pm), m["apy"], m["maxdd"], m["calmar"]))
    ident = next(x for x in scored if x[0] == tuple(books))
    print(f"     identity (the real DSP): APY {fmt_pct(ident[1])}, maxDD {fmt_pct(ident[2])},"
          f" Calmar {fmt_cal(ident[3])}")
    rec = store.setdefault(half_name, {})
    rec.update({"identity_apy": ident[1], "identity_maxdd": ident[2],
                "identity_calmar": ident[3]})
    # The claim under test is "yield higher AND risk lower", so BOTH axes get a rank. Ranking on
    # return alone would let a scheme that only shifts risk pass or fail for the wrong reason.
    for label, idx, higher_is_better, f in (("APY", 1, True, fmt_pct),
                                            ("maxDD (shallower)", 2, True, fmt_pct),
                                            ("Calmar", 3, True, fmt_cal)):
        vals = [x[idx] for x in scored]
        finite = [v for v in vals if v == v and v not in (float("inf"), float("-inf"))]
        if len(finite) < len(vals):
            print(f"     {label}: NOT RANKED — {len(vals)-len(finite)} of {len(vals)} permutations"
                  f" have no finite value (a rank over a set containing ∞ is not a rank)")
            rec[f"rank_{label}"] = None
            continue
        order = sorted(scored, key=lambda x: -x[idx] if higher_is_better else x[idx])
        rank = [x[0] for x in order].index(tuple(books)) + 1
        srt = sorted(finite)
        med = srt[len(srt) // 2]
        print(f"     {label:>18}: real ranks {rank:>2} of {len(scored)}  |  null min {f(srt[0])},"
              f" median {f(med)}, max {f(srt[-1])}")
        rec[f"rank_{label}"] = rank
        rec[f"null_median_{label}"] = med
    # The verdict is per AXIS, not overall: a scheme can address risk well and return badly,
    # and collapsing the two into one sentence is how half a result gets sold as a whole one.
    n = len(scored)
    for label in ("APY", "maxDD (shallower)", "Calmar"):
        r = rec.get(f"rank_{label}")
        if r is None:
            continue
        if r == 1:
            print(f"       → {label}: the real addressing is the BEST of all {n}. On this axis the")
            print("         selection carries something a random address does not.")
        elif r > n // 2:
            print(f"       → {label}: rank {r} of {n} — worse than half the random addresses. The")
            print("         selection carries nothing on this axis; what gain there is, is shape.")
        else:
            print(f"       → {label}: rank {r} of {n} — better than chance but not decisive.")


def section7_tdc_resolution(rets, books, n_train, cost_bps=15.0) -> Dict[str, object]:
    """#106 rejected on its default grid would be #106 rejected on a resolution artifact.

    The coincidence statistic is a count over the worst `tail_frac` of a `lookback`-day window,
    so it has exactly k = round(lookback × tail_frac) observations. At the default (20 × 0.10)
    k = 2 and the "discount" can only take the values 0, 0.5, 1 — a discount that coarse is a
    switch. Whether #106 fails because the IDEA is wrong or because the ESTIMATOR is blind is
    a question with a measurable answer, so it gets measured rather than argued.
    """
    n = len(rets[books[0]])
    train = {b: rets[b][:n_train] for b in books}
    test = {b: rets[b][n_train:n] for b in books}
    print("\n" + "=" * 100)
    print("7. #106 RESOLUTION — the coincidence estimator has k = lookback × tail_frac")
    print("   observations per window. Rejecting the idea at k = 2 would reject the estimator,")
    print("   not the idea, so the whole (lookback × tail_frac) grid is reported.")
    print("=" * 100)
    print(f"{'lkb':>5}{'tail':>7}{'k':>4}{'distinct':>10}{'TRAIN APY':>12}{'TRAIN maxDD':>13}"
          f"{'TEST APY':>11}{'TEST maxDD':>13}{'TEST Calmar':>13}")
    print("-" * 100)
    out = {}
    for lkb in (20, 60):
        for tf in (0.10, 0.25, 0.50):
            k = max(1, int(round(lkb * tf)))
            fn = make_tail_coincidence(tf)
            tr = metrics(run_scheme(train, books, fn, lkb, 0.60, cost_bps,
                                    warmup=WARMUP)["rets"])
            te = metrics(run_scheme(test, books, fn, lkb, 0.60, cost_bps,
                                    warmup=WARMUP)["rets"])
            out[f"{lkb}|{tf}"] = {"k": k, "train": tr, "test": te}
            print(f"{lkb:>5}{tf:>7.2f}{k:>4}{k+1:>10}{fmt_pct(tr['apy']):>12}"
                  f"{fmt_pct(tr['maxdd']):>13}{fmt_pct(te['apy']):>11}"
                  f"{fmt_pct(te['maxdd']):>13}{fmt_cal(te['calmar']):>13}")
    print("\n   'distinct' is how many values the discount can take AT ALL (k+1). A discount that")
    print("   can only be 0, 1/2 or 1 is not a discount; it is a switch with a middle notch.")
    return out


def section6_verdict(res: Dict[str, object]) -> None:
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    test = res["test"]
    ew = test.get("EW", {}).get("metrics")
    for name in ("IVOL#17", "DSP#105", "TDC#106"):
        m = test.get(name, {}).get("metrics")
        if m is None or ew is None:
            print(f"  {name}: NOT MEASURED — no TEST row")
            continue
        d_apy = (m["apy"] - ew["apy"]) * 100
        print(f"  {name:9} vs EW on unseen TEST: ΔAPY {d_apy:+.2f} pp, "
              f"maxDD {fmt_pct(m['maxdd'])} vs {fmt_pct(ew['maxdd'])} "
              f"({'shallower' if m['maxdd'] >= ew['maxdd'] else 'DEEPER'}), "
              f"turnover {m['turnover']*100:.2f}%/d vs {ew['turnover']*100:.2f}%/d")

    # Cost-conditionality, stated rather than buried in §4: a verdict that holds at one price
    # of the same trade and not at another is a verdict about the price, and #92 measured that
    # this tree does not agree with itself about that price.
    grid = res.get("cost_grid", {})
    print("\n  Cost-conditionality (TEST, lkb 20 / cap 0.60) — ΔAPY over EW at each quoted price:")
    for bps in COST_GRID_BPS:
        cell = grid.get(str(bps), {}).get("TEST", {})
        if not cell or "EW" not in cell:
            continue
        base = cell["EW"]["apy"]
        parts = ", ".join(
            f"{k} {100*(v['apy']-base):+.2f} pp" for k, v in cell.items() if k != "EW")
        print(f"    {bps:>5.0f} bps: {parts}")

    # The placebo is the load-bearing control, so its reading is spelled out here too.
    pl = res.get("mechanism", {}).get("placebo", {})
    for half in sorted(pl):
        if not isinstance(pl[half], dict):
            continue
        rec = pl[half]
        print(f"\n  Placebo, {half}: APY rank {rec.get('rank_APY')}/{pl.get('n')}, "
              f"maxDD rank {rec.get('rank_maxDD (shallower)')}/{pl.get('n')}, "
              f"Calmar rank {rec.get('rank_Calmar')}/{pl.get('n')}")

    print("\n  Every number above is [bt] on the aggressive_lab backtest block (L0), advisory,")
    print("  OUTSIDE_RISKPOLICY. No capital moved, no live track touched, no gate changed.")
    print("  Panel snapshot matters: aggressive_lab books are regenerated, so these numbers are")
    print(f"  reproducible against the block {res['axis'][0]} … {res['axis'][1]} "
          f"({res['n_days']} days) and not against a later one.")


# ══════════════════════════════════════════════════════════════════════════════════════════
def run(panel_dir: Optional[Path] = None) -> Dict[str, object]:
    panel = ens.load_panel(panel_dir or ens.PANEL_DIR)
    axis = ens.common_axis(panel)
    print(f"panel: {len(panel)} books, {len(axis)} common days {axis[0]} … {axis[-1]}")

    res: Dict[str, object] = {"axis": [axis[0], axis[-1]], "n_days": len(axis)}
    res["controls"] = section0_controls(panel, axis)

    universe, census = section1_universe(panel, axis)
    res["census"] = census
    res["universe"] = universe
    if len(universe) < 2:
        res["controls"]["failures"].append(
            f"universe has {len(universe)} book(s) — a portfolio study needs at least two")

    if res["controls"]["failures"]:
        print("\n" + "!" * 100)
        print("REFUSED — controls did not pass. Nothing below is computed, because a number")
        print("produced by an uncalibrated instrument is worse than no number:")
        for f in res["controls"]["failures"]:
            print(f"  • {f}")
        print("!" * 100)
        res["refused"] = True
        return res
    res["refused"] = False

    rets = {b: [panel[b][d] for d in axis] for b in universe}
    res["causality"] = section0b_causality(rets, universe)
    res["rank_divergence"] = section1b_rank_divergence(rets, universe)
    res["floor_binding"] = section1c_floor_binding(rets, universe)

    n_train, n_test = _split(axis)
    print(f"\n   split: TRAIN {n_train} days (≤ {TRAIN_END}) / TEST {n_test} days")
    res["n_train"], res["n_test"] = n_train, n_test

    train = section2_train(rets, universe, n_train, 15.0)
    res["train"] = {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in train["sweep"].items()}
    res["test"] = section3_test(rets, universe, n_train, train["best"], 15.0)
    res["cost_grid"] = {str(k): v for k, v in
                        section4_cost_grid(rets, universe, n_train).items()}
    res["floor"] = {str(k): v for k, v in
                    section5_floor_sensitivity(rets, universe, n_train).items()}
    res["mechanism"] = section6_mechanism(rets, universe, n_train,
                                          train["best"]["DSP#105"][0])
    res["tdc_resolution"] = section7_tdc_resolution(rets, universe, n_train)
    section6_verdict(res)
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", type=Path, default=None,
                    help="write the measured result to this path (advisory artifact)")
    args = ap.parse_args(list(argv) if argv is not None else None)
    res = run()
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, default=str))
        print(f"\nwrote {args.json}")
    return 2 if res.get("refused") else 0


if __name__ == "__main__":
    raise SystemExit(main())
