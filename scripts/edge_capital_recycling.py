#!/usr/bin/env python3
"""Edge R&D — registry ideas #38 (CBCR) and #39 (CDR). Both attack the SAME unexamined
convention: that de-risked capital becomes CASH AT 0%.

WHERE THIS COMES FROM
  Every de-risk entry in the registry (#1, #9, #15, #23, #28, #32, #35, #36, #37) is scored with
  one and the same portfolio rule: a flagged book's slice of capital goes flat and earns nothing
  until the flag clears. That convention is deliberately conservative, and it is the reason the
  registry's ONLY surviving configuration carries the caveat it does:

      #36: "netAPY after cost (17.62%) is BELOW raw (17.94%) — the win comes out of the drawdown
            (−5.44% → −3.37%), not out of yield; duty rises to 44.8%, i.e. the book sits in cash
            almost half the time."

  Half the portfolio's time in a 0% asset is not a market fact — it is a modelling choice about
  where freed capital goes. In a TEN-book portfolio there is a third option the registry has never
  scored: the freed capital is neither risked in the flagged book nor idle — it goes to the books
  that are NOT flagged right now.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #38 — CBCR: Cross-Book Capital Recycling  ("de-risked is not the same as idle")
──────────────────────────────────────────────────────────────────────────────────────────────
      eligible(t) = books NOT flagged by the overlay on day t
      w_b(t)      = 1/|eligible(t)|  for b in eligible(t),  0 otherwise   (cash only if empty)

  The trigger is untouched — every family is the registry's own. Only the destination of the
  freed slice changes. The hypothesis is "higher yield at equal-or-lower risk": recycling should
  recover the carry that #36 gives up, and should not deepen the drawdown, because capital only
  ever moves INTO books whose own signal is currently quiet.

  Four controls, and the last two are the ones that can kill it:
    • cash-at-r_f      — pay the freed slice the risk-free rate instead of 0%. If recycling only
                         matches this, the finding is "cash should earn something", not an edge.
    • recycle-to-worst — send the freed slice to the WORST-drifting eligible books first. If this
                         does as well, the destination does not matter and the number is noise.
    • concentration cap — recycling silently breaks concentration limits (a 10-book equal weight
                         is 10%; with 6 books flagged the survivors carry 25% each). Re-run under
                         the project's own 20% per-name cap; whatever does not fit stays cash.
    • STATIC WEIGHT-MATCHED — the decisive one. Take the TIME-AVERAGE of the dynamic weights and
                         run them as a fixed portfolio. Same average tilt, zero timing. If the
                         static twin matches the dynamic one, CBCR is a static re-weight wearing
                         a timing costume, and belongs in the allocator, not in an overlay.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #39 — CDR: Causal Demotion & Re-admission  ("#37's own practical conclusion, measured")
──────────────────────────────────────────────────────────────────────────────────────────────
      DEMOTED(b, t) : drift_L(b, t−1) < hurdle          → book leaves the eligible set
      RE-ADMIT      : drift_L(b, ·) ≥ hurdle for M consecutive days
      capital of demoted books is split over the books that remain eligible

  #37 ended with a claim that was never tested: *"the right instrument against a book with a
  persistently negative drift is DEMOTION / withdrawal, not an overlay; an overlay in that role
  is an expensive and indirect surrogate for selection."* That sentence is a hypothesis, and this
  is its test — same trigger, same lookback, same hurdle as #37, changing exactly one thing: the
  freed capital is re-allocated instead of parked. With M=1 the eligibility state is EXACTLY
  `sds_signal` (pinned by the test-suite), so #37 is reproduced as a row inside this table and
  the delta is attributable to the destination of the capital alone.

  Controls: the #37 overlay itself · M ∈ {1, 5, 20} (does hysteresis on re-admission help, per
  the reactivity law of #32?) · oracle demotion (drop the full-sample-negative books from day one
  — LOOK-AHEAD, the ceiling of perfect selection) · drop-eth_directional static (what the project
  policy ADR-055 would have done by hand) · static weight-matched · leave-one-out.

──────────────────────────────────────────────────────────────────────────────────────────────
HONESTY / SCOPE (registry rules — non-negotiable)
──────────────────────────────────────────────────────────────────────────────────────────────
  • Strictly causal: every weight for day i is decided from information through i−1 only, pinned
    in both directions by the test-suite.
  • LEAVE-ONE-OUT IS MANDATORY (rule introduced by #37): a portfolio ΔCalmar carried by a single
    book is not a portfolio edge, and is reported as such.
  • Costs are charged on TURNOVER, not on switch counts, because recycling moves capital on days
    no flag flips. The unit is idea #10's measured 96 bp round-trip per unit of book capital,
    i.e. 48 bp per one-way leg; on a plain cash overlay this formula reproduces the registry's
    switch-based bill exactly (pinned by the test-suite), so the two eras stay comparable.
  • The clean panel loader of #32 is IMPORTED, not re-implemented (it cuts the phase="forward"
    accounting re-anchor and refuses unexplained same-block jumps). The books are REGENERATED
    nightly, so numbers are reproducible only against the panel files of the run date.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence L0 (backtest on real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True.

Usage:
    python3 scripts/edge_capital_recycling.py              # everything
    python3 scripts/edge_capital_recycling.py --idea 38    # CBCR only
    python3 scripts/edge_capital_recycling.py --idea 39    # CDR only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt          # noqa: E402  (audited loader + metrics of idea #32)
import edge_drift_gated_overlay as dgo   # noqa: E402  (signals, dwell latch, SDS of #35/#36/#37)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

TRAIN_END = cfpt.TRAIN_END                 # "2025-06-30"
RF_ANNUAL = cfpt.RF_ANNUAL                 # 0.046
COST_BP_ROUND_TRIP = dgo.COST_BP_PER_SWITCH  # 96 bp per unit of capital, out and back (#10)
BP = cfpt.BP
CONC_CAP = 0.20                            # project's own per-name cap for T2 (RiskPolicy v1.0)
SDS_LOOKBACK = 60                          # #37's train-selected drift window
SDS_HURDLE = 0.0                           # #37's train-selected hurdle
EPS = 1e-12


# ═══════════════════════════════ allocators ═══════════════════════════════
# All of them map per-book DEFEND flags to per-book portfolio weights. Every allocator is a pure
# function of flags (and, where stated, of causal drift), so any difference between two rows of a
# report is attributable to the allocator alone.

def alloc_cash(books: Sequence[str], flags: Dict[str, Sequence[bool]],
               n: int) -> Dict[str, List[float]]:
    """The registry's convention: a flagged book's slice goes to cash and stays there.

    Equal weight 1/N per book; a flagged book contributes 0 and its slice is NOT reallocated.
    This is the row every previous entry of the registry was scored on, reproduced here so the
    recycling rows are read against the same baseline rather than a re-derived one.
    """
    base = 1.0 / len(books)
    return {b: [0.0 if flags[b][i] else base for i in range(n)] for b in books}


def _waterfill(eligible: Sequence[str], cap: Optional[float]) -> Dict[str, float]:
    """Split 1.0 equally over `eligible`, clipping every name at `cap` and redistributing.

    Returns weights that sum to 1.0 unless the cap makes that impossible (len*cap < 1), in which
    case the shortfall is left uninvested — capital that does not fit inside the concentration
    limit becomes cash rather than a silent limit breach. Empty eligible ⇒ everything is cash.
    """
    if not eligible:
        return {}
    if cap is None:
        w = 1.0 / len(eligible)
        return {b: w for b in eligible}
    if cap <= 0.0:
        raise ValueError("cap must be positive — a zero cap is not an allocation rule")
    out: Dict[str, float] = {}
    remaining = list(eligible)
    budget = 1.0
    while remaining and budget > EPS:
        share = budget / len(remaining)
        if share <= cap + EPS:
            for b in remaining:
                out[b] = out.get(b, 0.0) + share
            budget = 0.0
            break
        for b in remaining:
            out[b] = cap
        budget -= cap * len(remaining)
        remaining = []          # every name is at the cap; the rest cannot be placed
    return out


def alloc_recycle(books: Sequence[str], flags: Dict[str, Sequence[bool]], n: int,
                  cap: Optional[float] = None) -> Dict[str, List[float]]:
    """CBCR: the freed slice is split EQUALLY over the books that are not flagged today.

    Capital never enters a flagged book, so the rule can only ever move exposure toward names
    whose own signal is currently quiet. If nothing is eligible, everything is cash — fail-CLOSED,
    the one state where the rule must not invent a destination.
    """
    out: Dict[str, List[float]] = {b: [0.0] * n for b in books}
    for i in range(n):
        eligible = [b for b in books if not flags[b][i]]
        for b, w in _waterfill(eligible, cap).items():
            out[b][i] = w
    return out


def alloc_recycle_ranked(books: Sequence[str], flags: Dict[str, Sequence[bool]], n: int,
                         rets: Dict[str, Sequence[float]], lookback: int = SDS_LOOKBACK,
                         best_first: bool = True,
                         cap: float = CONC_CAP) -> Dict[str, List[float]]:
    """Control: the freed slice is NOT split equally — it is stacked onto the eligible books with
    the best (or, as the refuting control, the WORST) causal trailing drift, each up to `cap`.

    A cap is mandatory here: without one, "stack onto the best" degenerates into a single-name
    portfolio and stops being comparable to anything. Ranking uses `cfpt.trailing_mean`, which
    stops at t−1; books without a measurable drift rank last (they are not preferred on an
    unmeasured state) but remain eligible.

    Purpose: if recycle-to-worst does as well as recycle-to-best, the destination carries no
    information and CBCR's number is an artifact of merely staying deployed.
    """
    mu = {b: cfpt.trailing_mean(rets[b], lookback) for b in books}
    out: Dict[str, List[float]] = {b: [0.0] * n for b in books}
    sign = -1.0 if best_first else 1.0
    for i in range(n):
        eligible = [b for b in books if not flags[b][i]]
        if not eligible:
            continue
        measurable = [b for b in eligible if i >= lookback]
        unmeasured = [b for b in eligible if i < lookback]
        ordered = sorted(measurable, key=lambda b: (sign * mu[b][i], b)) + sorted(unmeasured)
        budget = 1.0
        for b in ordered:
            if budget <= EPS:
                break
            take = min(cap, budget)
            out[b][i] = take
            budget -= take
    return out


def alloc_static_matched(weights: Dict[str, List[float]]) -> Dict[str, List[float]]:
    """THE decisive control: the time-average of a dynamic allocation, held constant.

    Same average exposure per book, same average cash, zero timing. Any advantage the dynamic
    rule has over this twin is timing; anything it does not have over it was a static tilt that
    an allocator could have taken once and for free.
    """
    books = list(weights)
    n = len(weights[books[0]])
    avg = {b: sum(weights[b]) / n for b in books}
    return {b: [avg[b]] * n for b in books}


# ═══════════════════════════════ demotion state (idea #39) ═══════════════════════════════
def demotion_flags(returns: Sequence[float], lookback: int = SDS_LOOKBACK,
                   hurdle_annual: float = SDS_HURDLE,
                   readmit_days: int = 1) -> List[bool]:
    """True on days the book is DEMOTED — out of the eligible set, not merely de-risked.

        demote   : mean(r[t−L : t−1]) < hurdle/365
        re-admit : that mean has been ≥ hurdle/365 on `readmit_days` consecutive days

    With `readmit_days == 1` this is EXACTLY `dgo.sds_signal(returns, lookback, hurdle)` — the
    signal of #37 — which is what makes the comparison in this file clean: the trigger is held
    fixed and only the destination of the capital changes. The test-suite pins that identity.

    Fail-CLOSED before `lookback` points exist: an unmeasured drift is not grounds for demotion
    (the book stays eligible), the same convention `sds_signal` uses.
    """
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    mu = cfpt.trailing_mean(returns, lookback)
    thr = hurdle_annual / 365.0
    out: List[bool] = []
    demoted = False
    good_run = 0
    for i in range(len(returns)):
        if i < lookback:
            out.append(False)
            continue
        above = mu[i] >= thr
        good_run = good_run + 1 if above else 0
        if demoted:
            if good_run >= readmit_days:
                demoted = False
        elif not above:
            demoted = True
        out.append(demoted)
    return out


def oracle_demotion_flags(returns: Sequence[float]) -> List[bool]:
    """LOOK-AHEAD control: demoted for the whole sample iff the book's FULL-SAMPLE mean is < 0.

    Not a strategy and never proposed as one — it is the ceiling of what perfect book selection
    is worth, so causal demotion can be read as a fraction of it.
    """
    n = len(returns)
    if n == 0:
        return []
    return [(sum(returns) / n) < 0.0] * n


# ═══════════════════════════════ evaluation ═══════════════════════════════
def portfolio_metrics(panel: "dgo.Panel", weights: Dict[str, List[float]],
                      cash_annual: float = 0.0,
                      cost_bp_round_trip: float = COST_BP_ROUND_TRIP) -> Dict[str, float]:
    """Daily-rebalanced portfolio over per-book weights, with the uninvested rest earning `cash_annual`.

    Cost model — TURNOVER, not switch counts. Idea #10 measured 96 bp for a round trip of a unit
    of book capital, i.e. 48 bp per one-way leg, so the daily bill is
        48 bp × Σ_b |w_b(t) − w_b(t−1)|
    On a plain cash overlay this reproduces the registry's per-switch bill exactly (one book
    leaving and returning moves 2/N of the portfolio ⇒ 96 bp / N), which is what keeps these
    numbers comparable with #32/#35/#36. Recycling needs the turnover form because it moves
    capital on days when no flag flips at all — a cost a switch counter cannot see.

    The bill is subtracted from the compounded APY rather than re-invested; stated so it is never
    mistaken for a compounded net path.
    """
    n = panel.n
    books = panel.books
    pf: List[float] = []
    for i in range(n):
        deployed = sum(weights[b][i] for b in books)
        r = sum(weights[b][i] * panel.rets[b][i] for b in books)
        pf.append(r + (1.0 - deployed) * cash_annual / 365.0)
    p = cfpt.perf(pf)

    turnover = 0.0
    for b in books:
        for i in range(1, n):
            turnover += abs(weights[b][i] - weights[b][i - 1])
    turnover_yr = turnover * 365.0 / n
    cost_bp_yr = 0.5 * cost_bp_round_trip * turnover_yr

    deployed_avg = sum(sum(weights[b][i] for b in books) for i in range(n)) / n
    max_w = max(max(weights[b]) for b in books)
    return {
        "apy": p["apy"],
        "maxdd": p["maxdd"],
        "calmar": p["calmar"],
        "deployed": deployed_avg,
        "turnover_yr": turnover_yr,
        "cost_bp_yr": cost_bp_yr,
        "net_apy_after_cost": p["apy"] - cost_bp_yr / BP,
        "max_weight": max_w,
    }


def flags_from_weights(w: Sequence[float]) -> List[bool]:
    """Read a 0/1 exposure path (e.g. the dwell latch of #36) back as DEFEND flags."""
    return [x <= EPS for x in w]


# ═══════════════════════════════ signal catalog ═══════════════════════════════
FlagFn = Callable[[Sequence[float]], List[bool]]


def families() -> List[Tuple[str, FlagFn]]:
    """The registry's own de-risk families, plus the only configuration that has ever survived
    train→test AND leave-one-out on this panel (`ecdr#23 + dwell(k=2)`, from #36)."""
    out: List[Tuple[str, FlagFn]] = list(dgo.base_signals())
    out.append(("ecdr+dwell(k=2)#36",
                lambda r: flags_from_weights(dgo.dwell_weights(r, cfpt.sig_ecdr(r, 10, 30), 2))))
    return out


# ═══════════════════════════════ reporting ═══════════════════════════════
_COLS = (f"{'configuration':34s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔCalmar':>8s} "
         f"{'depl':>6s} {'maxW':>6s} {'turn/yr':>8s} {'netAPY':>8s}")


def _header(title: str, panel: "dgo.Panel", base: Dict[str, float]) -> None:
    print()
    print("=" * 110)
    print(f"{title}  ·  {panel.n} days {panel.axis[0]}..{panel.axis[-1]}  ·  {len(panel.books)} books")
    print("=" * 110)
    print(f"raw equal-weight (no overlay): APY {base['apy']*100:.2f}%  maxDD {base['maxdd']*100:.2f}%  "
          f"Calmar {base['calmar']:.2f}")
    print(_COLS)


def _row(name: str, m: Dict[str, float], base: Dict[str, float]) -> None:
    print(f"{name:34s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f}"
          f" {m['calmar']-base['calmar']:8.2f} {m['deployed']*100:5.0f}% {m['max_weight']*100:5.0f}%"
          f" {m['turnover_yr']:8.2f} {m['net_apy_after_cost']*100:7.2f}%")


def _raw_metrics(panel: "dgo.Panel") -> Dict[str, float]:
    return cfpt.perf(panel.raw_portfolio())


# ─────────────────────────────── idea #38 ───────────────────────────────
def idea38_cbcr(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
                start: Optional[str] = None, end: Optional[str] = None,
                segment: str = "FULL", quiet: bool = False) -> Dict[str, Dict[str, float]]:
    """Idea #38 — does recycling the freed slice into the unflagged books beat parking it?"""
    panel = dgo.Panel(subset, start, end)
    base = _raw_metrics(panel)
    if not quiet:
        _header(f"IDEA #38 CBCR — cross-book capital recycling [{segment}] — {label}", panel, base)
    results: Dict[str, Dict[str, float]] = {}

    for name, fn in families():
        flags = {b: fn(panel.rets[b]) for b in panel.books}
        cash = alloc_cash(panel.books, flags, panel.n)
        recyc = alloc_recycle(panel.books, flags, panel.n)
        variants = [
            (f"{name}", cash, 0.0),
            ("  cash@r_f (control)", cash, RF_ANNUAL),
            ("  +CBCR recycle", recyc, 0.0),
            (f"  +CBCR cap {int(CONC_CAP*100)}%",
             alloc_recycle(panel.books, flags, panel.n, cap=CONC_CAP), 0.0),
            ("  CONTROL to-best drift",
             alloc_recycle_ranked(panel.books, flags, panel.n, panel.rets, best_first=True), 0.0),
            ("  CONTROL to-worst drift",
             alloc_recycle_ranked(panel.books, flags, panel.n, panel.rets, best_first=False), 0.0),
            ("  CONTROL static-matched", alloc_static_matched(recyc), 0.0),
        ]
        for vname, w, cash_rate in variants:
            m = portfolio_metrics(panel, w, cash_annual=cash_rate)
            key = name if vname == name else f"{name}{vname.strip()}"
            results[key] = m
            if not quiet:
                _row(vname, m, base)
        if not quiet:
            print("-" * 110)

    if not quiet:
        print("depl = average deployed capital · maxW = largest weight any single book ever carried.")
        print("`static-matched` holds the TIME-AVERAGE of the recycled weights: same tilt, no timing.")
        print("Unless a dynamic row beats its own static twin, CBCR is an allocator decision, not an overlay.")
    return results


# ─────────────────────────────── idea #39 ───────────────────────────────
def idea39_cdr(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False) -> Dict[str, Dict[str, float]]:
    """Idea #39 — demotion-with-redistribution vs the #37 overlay, same trigger, same panel."""
    panel = dgo.Panel(subset, start, end)
    base = _raw_metrics(panel)
    if not quiet:
        _header(f"IDEA #39 CDR — causal demotion & re-admission [{segment}] — {label}", panel, base)
    results: Dict[str, Dict[str, float]] = {}

    sds = {b: dgo.sds_signal(panel.rets[b], SDS_LOOKBACK, SDS_HURDLE) for b in panel.books}
    rows: List[Tuple[str, Dict[str, List[float]], float]] = [
        ("#37 SDS overlay (cash 0%)", alloc_cash(panel.books, sds, panel.n), 0.0),
        ("#37 SDS overlay (cash r_f)", alloc_cash(panel.books, sds, panel.n), RF_ANNUAL),
    ]
    for m_days in (1, 5, 20):
        dem = {b: demotion_flags(panel.rets[b], SDS_LOOKBACK, SDS_HURDLE, m_days)
               for b in panel.books}
        rows.append((f"CDR readmit M={m_days}", alloc_recycle(panel.books, dem, panel.n), 0.0))
        if m_days == 1:
            rows.append((f"  CDR M=1 cap {int(CONC_CAP*100)}%",
                         alloc_recycle(panel.books, dem, panel.n, cap=CONC_CAP), 0.0))
            rows.append(("  CONTROL static-matched",
                         alloc_static_matched(alloc_recycle(panel.books, dem, panel.n)), 0.0))

    oracle = {b: oracle_demotion_flags(panel.rets[b]) for b in panel.books}
    rows.append(("ORACLE demotion* (look-ahead)", alloc_recycle(panel.books, oracle, panel.n), 0.0))

    survivors = [b for b in panel.books if b != "eth_directional"]
    if len(survivors) == len(panel.books):
        survivors = panel.books
    never = {b: [b not in survivors] * panel.n for b in panel.books}
    rows.append(("POLICY drop eth_directional*", alloc_recycle(panel.books, never, panel.n), 0.0))

    for name, w, cash_rate in rows:
        m = portfolio_metrics(panel, w, cash_annual=cash_rate)
        results[name.strip()] = m
        if not quiet:
            _row(name, m, base)

    if not quiet:
        print("-" * 110)
        print("* both starred rows are LOOK-AHEAD (they know which book is broken from day one) —")
        print("  ceilings, not strategies. CDR M=1 uses EXACTLY #37's trigger, so the gap between it")
        print("  and the '#37 SDS overlay' row is the value of the DESTINATION of the capital, alone.")
    return results


def cdr_sweep(readmits: Sequence[int] = (1, 2, 3, 5, 10, 20, 30, 45, 60),
              lookbacks: Sequence[int] = (30, 45, 60, 90, 120)) -> None:
    """Is CDR a plateau or a spike? ΔCalmar over the (re-admission delay × drift window) grid.

    A single winning cell is a lottery ticket; a connected region that changes smoothly is a
    mechanism. #37 established the shape this grid should have if the reactivity law of #32 holds
    — slow is better — and it is checked here on an axis #37 never had (how long to WAIT before
    putting a demoted book back).
    """
    panel = dgo.Panel()
    base = _raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"IDEA #39 CDR — SWEEP of ΔCalmar vs raw ({base['calmar']:.2f}); rows = drift window L, "
          f"cols = re-admission delay M")
    print("=" * 110)
    print(f"{'L \\ M':>8s}" + "".join(f"{m:>8d}" for m in readmits))
    for lkb in lookbacks:
        cells = []
        for m_days in readmits:
            dem = {b: demotion_flags(panel.rets[b], lkb, SDS_HURDLE, m_days) for b in panel.books}
            met = portfolio_metrics(panel, alloc_recycle(panel.books, dem, panel.n))
            cells.append(met["calmar"] - base["calmar"])
        print(f"{lkb:>8d}" + "".join(f"{c:>+8.2f}" for c in cells))
    print("M=1 column reproduces #37's trigger exactly, with the capital re-allocated instead of parked.")


# ─────────────────────────────── robustness ───────────────────────────────
def train_test(idea: Callable[..., Dict[str, Dict[str, float]]], keys: Sequence[str]) -> None:
    """Report the selected configurations on TRAIN and on the unseen TEST segment."""
    print()
    print("=" * 110)
    print(f"TRAIN → TEST (split {TRAIN_END}; parameters were fixed BEFORE the split, see docstring)")
    print("=" * 110)
    train = idea(end=TRAIN_END, segment="TRAIN", quiet=True)
    test = idea(start=TRAIN_END, segment="TEST", quiet=True)
    raw_tr = _raw_metrics(dgo.Panel(None, None, TRAIN_END))
    raw_te = _raw_metrics(dgo.Panel(None, TRAIN_END, None))
    print(f"raw TRAIN: APY {raw_tr['apy']*100:6.2f}%  DD {raw_tr['maxdd']*100:6.2f}%  "
          f"Calmar {raw_tr['calmar']:5.2f}   |   raw TEST: APY {raw_te['apy']*100:6.2f}%  "
          f"DD {raw_te['maxdd']*100:6.2f}%  Calmar {raw_te['calmar']:5.2f}")
    print(f"{'configuration':34s} {'trAPY':>8s} {'trCalmar':>9s} {'trΔ':>7s} "
          f"{'teAPY':>8s} {'teCalmar':>9s} {'teΔ':>7s}")
    for k in keys:
        if k not in train or k not in test:
            print(f"{k:34s}   [absent — configuration not produced on one of the segments]")
            continue
        a, b = train[k], test[k]
        print(f"{k:34s} {a['apy']*100:7.2f}% {a['calmar']:9.2f} {a['calmar']-raw_tr['calmar']:7.2f} "
              f"{b['apy']*100:7.2f}% {b['calmar']:9.2f} {b['calmar']-raw_te['calmar']:7.2f}")


def leave_one_out(idea: Callable[..., Dict[str, Dict[str, float]]], key: str) -> None:
    """#37's mandatory check: does the portfolio delta survive dropping any single book?"""
    books = dgo.Panel().books
    print()
    print("=" * 110)
    print(f"LEAVE-ONE-OUT — «{key}» (rule of #37: a delta carried by one book is not a portfolio edge)")
    print("=" * 110)
    print(f"{'portfolio':34s} {'rawCalmar':>10s} {'cfgCalmar':>10s} {'ΔCalmar':>8s} {'ΔAPY':>8s}")
    full = idea(quiet=True)[key]
    raw_full = _raw_metrics(dgo.Panel())
    print(f"{'all books':34s} {raw_full['calmar']:10.2f} {full['calmar']:10.2f} "
          f"{full['calmar']-raw_full['calmar']:8.2f} {(full['apy']-raw_full['apy'])*100:7.2f}pp")
    worst = None
    for drop in books:
        sub = [b for b in books if b != drop]
        m = idea(subset=sub, quiet=True)[key]
        raw = _raw_metrics(dgo.Panel(sub))
        d = m["calmar"] - raw["calmar"]
        print(f"{'minus ' + drop:34s} {raw['calmar']:10.2f} {m['calmar']:10.2f} {d:8.2f} "
              f"{(m['apy']-raw['apy'])*100:7.2f}pp")
        worst = d if worst is None else min(worst, d)
    print(f"\nworst-case ΔCalmar across all leave-one-out portfolios: {worst:.2f} "
          f"— {'SURVIVES (positive everywhere)' if worst and worst > 0 else 'FAILS (sign flips)'}")


# ─────────────────────────────── information controls ───────────────────────────────
# A recycling rule always ends up holding SOMETHING, so it can post a large number without the
# signal carrying any information at all. These two controls destroy exactly one kind of
# information each, leaving everything else (duty, switch structure, the allocator) untouched.

def permuted_flags(flags: Dict[str, List[bool]], books: Sequence[str],
                   seed: int) -> Dict[str, List[bool]]:
    """Re-attach the flag PATHS to the wrong books (fixed-seed shuffle).

    Duty, switch counts and the day-by-day number of eligible books are preserved exactly; the
    only thing destroyed is WHICH book each flag path belongs to. If a permuted panel does as
    well as the real one, the rule is not selecting books — it is just staying deployed.
    """
    import random
    rng = random.Random(seed)
    order = list(books)
    rng.shuffle(order)
    return {books[i]: flags[order[i]] for i in range(len(books))}


def shifted_flags(flags: Dict[str, List[bool]], books: Sequence[str],
                  shift: int) -> Dict[str, List[bool]]:
    """Rotate every flag path in TIME by `shift` days (circular).

    Book identity, duty and switch structure survive; the temporal alignment between a flag and
    the return it was meant to avoid does not. This is a control, not a strategy — it is
    deliberately non-causal and can never be run live.
    """
    return {b: list(flags[b][shift:]) + list(flags[b][:shift]) for b in books}


def information_controls(panel: "dgo.Panel", flags: Dict[str, List[bool]], label: str,
                         cap: Optional[float] = None, seeds: int = 20) -> None:
    """Score the real alignment against permuted-book and time-shifted twins of the same flags."""
    base = _raw_metrics(panel)
    real = portfolio_metrics(panel, alloc_recycle(panel.books, flags, panel.n, cap=cap))
    print()
    print("=" * 110)
    print(f"INFORMATION CONTROLS — «{label}» recycled  ({seeds} book-permutations, 3 time-shifts)")
    print("=" * 110)
    print(_COLS)
    _row("REAL alignment", real, base)

    perm = []
    for s in range(seeds):
        m = portfolio_metrics(panel, alloc_recycle(
            panel.books, permuted_flags(flags, panel.books, s), panel.n, cap=cap))
        perm.append(m)
    perm_sorted = sorted(perm, key=lambda m: m["calmar"])
    for tag, m in (("perm P10", perm_sorted[max(0, int(0.1 * seeds) - 1)]),
                   ("perm P50 (median)", perm_sorted[seeds // 2]),
                   ("perm P90", perm_sorted[min(seeds - 1, int(0.9 * seeds))])):
        _row(f"  CONTROL {tag}", m, base)
    beaten = sum(1 for m in perm if m["calmar"] >= real["calmar"])
    print(f"  → permutations reaching the real Calmar: {beaten}/{seeds}"
          f"   (empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")

    # Time-shift is swept, not sampled: three hand-picked rotations are three anecdotes, and the
    # first run of this script produced exactly the trap — one rotation (270d) nearly matched the
    # real alignment while two others were far below it. The whole rotation orbit is measured.
    shifts = list(range(30, panel.n, 30))
    shift_m = [portfolio_metrics(panel, alloc_recycle(
        panel.books, shifted_flags(flags, panel.books, s), panel.n, cap=cap)) for s in shifts]
    shift_sorted = sorted(shift_m, key=lambda m: m["calmar"])
    k = len(shift_sorted)
    for tag, m in ((f"shift P10 (of {k})", shift_sorted[max(0, int(0.1 * k) - 1)]),
                   ("shift P50 (median)", shift_sorted[k // 2]),
                   ("shift P90", shift_sorted[min(k - 1, int(0.9 * k))]),
                   ("shift BEST", shift_sorted[-1])):
        _row(f"  CONTROL time-{tag}", m, base)
    beaten_s = sum(1 for m in shift_m if m["calmar"] >= real["calmar"])
    print(f"  → rotations reaching the real Calmar: {beaten_s}/{k}"
          f"   (empirical p ≈ {(beaten_s + 1) / (k + 1):.3f})")
    print("  Read the two controls together: permutation destroys WHICH-book information, rotation")
    print("  destroys WHEN information. A rule that survives the first and not the second is a")
    print("  cross-sectional SELECTION rule, and belongs in the allocator rather than in an overlay.")


def weight_decomposition(panel: "dgo.Panel", flags: Dict[str, List[bool]], label: str,
                         cap: Optional[float] = None) -> None:
    """Where does the recycled capital actually end up? Concentration stated, not implied."""
    w = alloc_recycle(panel.books, flags, panel.n, cap=cap)
    print()
    print("=" * 110)
    print(f"WEIGHT DECOMPOSITION — «{label}» (equal weight would be {100.0/len(panel.books):.1f}% each)")
    print("=" * 110)
    print(f"{'book':24s} {'avg w':>8s} {'max w':>8s} {'duty(flagged)':>14s} {'book APY':>10s}")
    for b in sorted(panel.books, key=lambda x: -sum(w[x]) / panel.n):
        duty = sum(1 for f in flags[b] if f) / panel.n
        print(f"{b:24s} {sum(w[b])/panel.n*100:7.1f}% {max(w[b])*100:7.1f}% {duty*100:13.1f}% "
              f"{cfpt.perf(panel.rets[b])['apy']*100:9.2f}%")


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idea", type=int, choices=(38, 39), default=None)
    ap.add_argument("--loo-key", default=None, help="configuration key for the leave-one-out pass")
    args = ap.parse_args(argv)

    print("Ideas #38 CBCR / #39 CDR — ADVISORY, OUTSIDE_RISKPOLICY, evidence L0 (backtest).")
    print("Capital does not move. The live track and RiskPolicy v1.0 are not touched.")

    if args.idea in (None, 38):
        idea38_cbcr()
        train_test(idea38_cbcr, [
            "ecdr#23(10/30)", "ecdr#23(10/30)+CBCR recycle",
            "ecdr+dwell(k=2)#36", "ecdr+dwell(k=2)#36+CBCR recycle",
            "ecdr+dwell(k=2)#36CONTROL static-matched",
        ])
        leave_one_out(idea38_cbcr, args.loo_key or "ecdr+dwell(k=2)#36+CBCR recycle")
        panel = dgo.Panel()
        dwell = {b: flags_from_weights(dgo.dwell_weights(
            panel.rets[b], cfpt.sig_ecdr(panel.rets[b], 10, 30), 2)) for b in panel.books}
        information_controls(panel, dwell, "ecdr+dwell(k=2)#36")
        information_controls(panel, dwell, f"ecdr+dwell(k=2)#36 cap {int(CONC_CAP*100)}%",
                             cap=CONC_CAP)
        weight_decomposition(panel, dwell, "ecdr+dwell(k=2)#36 recycled")

    if args.idea in (None, 39):
        idea39_cdr()
        cdr_sweep()
        train_test(idea39_cdr, ["#37 SDS overlay (cash 0%)", "CDR readmit M=1",
                                "CDR readmit M=5", "CDR readmit M=20",
                                "CONTROL static-matched"])
        leave_one_out(idea39_cdr, "CDR readmit M=1")
        leave_one_out(idea39_cdr, "CDR readmit M=20")
        panel = dgo.Panel()
        dem20 = {b: demotion_flags(panel.rets[b], SDS_LOOKBACK, SDS_HURDLE, 20)
                 for b in panel.books}
        information_controls(panel, dem20, "CDR M=20")
        weight_decomposition(panel, dem20, "CDR M=20 recycled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
