#!/usr/bin/env python3
"""Edge R&D — registry ideas #51 (SLT) and #52 (SFP): what the demotion family costs when the DATA
is not what the backtest silently assumed.

WHERE THIS COMES FROM
  Entries #32–#50 built one family on the real 10-book panel: rank the books by some causal
  statistic, demote the bottom k, recycle their slice into the survivors. Nineteen entries argued
  about the CRITERION (drift, bad-day return, z-score, dispersion, redundancy, volatility), about
  DUTY, about the CONCENTRATION cap, about the TURNOVER bill (#49) and about the REBALANCE
  FREQUENCY (#50). Not one of them ever asked what happens when the numbers the rule ranks on
  arrive LATE, or do not arrive at all.

  The panel makes that question invisible. Measured on the run date (2026-08-14): ten books, 852
  days, 2024-03-06..2026-07-05 — a fully dense calendar with ZERO missing days in ZERO books, and
  every score computed as if the previous day's mark were on the desk before the decision. That
  completeness is a property of the nightly generator, not evidence about feeds. Production is not
  like that: the project's own STATE reports a stale `agent_health` snapshot, two data paths
  disagreeing on `aave_v3`'s APY (4.80% vs 2.36%), and a held protocol whose TVL is literally
  "not measured". A rule that only works on a dense, same-day panel is not a rule we own.

  These two ideas measure the two failure modes separately, on the panel the family was built on.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #51 — SLT: Signal Latency Tax   ("how much does it cost to be τ days late")
──────────────────────────────────────────────────────────────────────────────────────────────
      score_τ(b, t) = score(b, t − τ)        τ days of staleness, fail-CLOSED before day τ+L
      everything else — state machine, allocator, panel, costs — as in #40/#45, byte-for-byte

  τ folds together the two lags a real deployment has: the feed is τ_data days behind, and the
  decision reaches the book τ_exec days after it is taken. They are ONE number here, and that is
  a measured claim, not an assumption: a pure delay commutes with a causal time-invariant state
  machine, so lagging the input and lagging the output give the same flags. `commutation_check`
  reports the agreement rate and the test-suite pins it.

  τ < 0 is the LOOK-AHEAD control (tomorrow's score, today). It is never a proposal. It exists so
  that "the τ axis is inert" cannot be confused with "our harness ignores τ": if even the
  impossible direction moves nothing, the criterion carries no time-local information at all.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #52 — SFP: Stale-Feed Policy   ("which fail-behaviour should a curator write down")
──────────────────────────────────────────────────────────────────────────────────────────────
  On a day when a book's criterion cannot be computed, four policies are defensible. Today's code
  implements exactly one of them, silently, and it is not the one the project's invariant #2 would
  predict:

      open         unmeasured ⇒ NOT rankable ⇒ cannot be demoted, and an already-demoted book
                   accumulates re-admission credit while blind. THIS IS THE CURRENT BEHAVIOUR of
                   `xsd.rank_demotion_flags`: an outage PROTECTS a book and walks it back to full
                   weight.
      carry        unmeasured ⇒ rank on the last known score (stale rank, decision still taken)
      closed_book  unmeasured ⇒ that book is demoted for the day (fail-CLOSED per name, the
                   literal reading of invariant #2: not measured ⇒ not eligible)
      closed_panel any book unmeasured ⇒ the rule abstains; yesterday's demotion state is held
                   and no counter moves (fail-CLOSED at the cross-section: an incomplete field
                   has no worst)

  The outage process is SYNTHETIC and this is the load-bearing caveat of #52: the panel has no
  real gaps to calibrate against, so a two-state Markov outage (mean run 3 days, steady-state rate
  swept 2%→20%) is INJECTED. The rate axis is the honest deliverable, not any single cell — the
  question is which policy degrades gracefully, not what the number is at 5%.

──────────────────────────────────────────────────────────────────────────────────────────────
THE OUTCOMES, WRITTEN DOWN BEFORE THE NUMBERS (all of them publishable)
──────────────────────────────────────────────────────────────────────────────────────────────
  #51 A. ΔCalmar decays with τ  → freshness has a price; the deliverable is a freshness budget in
         days, and a stale rank feed becomes an operational alarm for the sanctioned #39 module.
      B. ΔCalmar is flat in τ   → the rule is not a timing rule on any axis, which is the same
         thing the static twin of #45 said, now measured where it costs money. Staleness of the
         RANK feed is then not an emergency — and that conclusion must not be exported to the risk
         path, which is a different domain with a different invariant.
      C. ΔCalmar RISES with τ   → our own reaction speed is the defect and lag is free smoothing.
  #52 A. `open` is fine        → the current silent behaviour is defensible and gets written down.
      B. `open` degrades worst → we have been shipping the one policy that protects the book the
         feed cannot see, and #39 CDR needs an explicit stale branch before its forward track can
         be read.
      C. `closed_book` wins    → the literal fail-CLOSED reading is also the profitable one, which
         would be the first time in this registry that safety and yield point the same way.

HONESTY / SCOPE (registry rules — non-negotiable)
  • Strictly causal. Every score for day i is computed from returns through i−1 and then aged by
    τ; days without a real value are None (fail-CLOSED), never a fabricated zero.
  • The panel loader of #32, the rank machine of #40 and the allocator/cost model of #38/#39 are
    IMPORTED, not re-implemented. `policy_flags` is the one generalisation written here, and the
    test-suite pins it to be byte-identical to `xsd.rank_demotion_flags` when nothing is missing.
  • Books are regenerated nightly: numbers reproduce against the panel of the run date
    (2026-08-14: 10 books, 852 days, raw 17.94% / −5.44% / Calmar 3.30).
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence L0 (backtest on real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_signal_latency.py                # everything
    python3 scripts/edge_signal_latency.py --idea 51      # latency only
    python3 scripts/edge_signal_latency.py --idea 52      # stale-feed policy only
    python3 scripts/edge_signal_latency.py --commute      # the delay-commutation check only
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, controls #38/#39)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40/#41)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_redundancy_demotion as rcd          # noqa: E402  (volatility criterion of #45)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK              # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END            # "2025-06-30" — the registry's own split

# The rules carried forward. Both cells were published BEFORE this entry and are not re-tuned:
# #40's reference cell (k=2, M=20) and #45's best cell (k=1, M=1), plus #40 run at #45's cell so
# the two criteria can be read at identical duty machinery.
RULES: Tuple[Tuple[str, str, int, int], ...] = (
    ("drift", "#40 XSD k=2 M=20", 2, 20),
    ("drift", "#40 XSD k=1 M=1", 1, 1),
    ("volatility", "#45 XVD k=1 M=1", 1, 1),
)

TAUS: Tuple[int, ...] = (-5, -1, 0, 1, 2, 3, 5, 10, 20)
POLICIES: Tuple[str, ...] = ("open", "carry", "closed_book", "closed_panel")
OUTAGE_RATES: Tuple[float, ...] = (0.02, 0.05, 0.10, 0.20)
OUTAGE_MEAN_RUN = 3.0                # days; an outage that lasts one day is not what breaks us
SEEDS = 20

Scores = xsd.Scores


# ═══════════════════════════════ #51 — ageing a signal ═══════════════════════════════
def lag_scores(scores: Scores, tau: int) -> Scores:
    """The score a τ-days-stale desk actually holds on day i: the one computed for day i − τ.

    τ > 0 is staleness. Days before the value exists are None — fail-CLOSED, because "we did not
    have the number yet" is exactly the state the rank machine already refuses to rank.
    τ < 0 is the LOOK-AHEAD control (a value from the future); it is a control, never a rule.
    τ = 0 must return the input unchanged, and the test-suite pins that.
    """
    books = sorted(scores)
    if not books:
        return {}
    n = len(scores[books[0]])
    for b in books:
        if len(scores[b]) != n:
            raise ValueError("score series of different length — refusing to align by position")
    out: Scores = {}
    for b in books:
        col: List[Optional[float]] = []
        for i in range(n):
            j = i - tau
            col.append(scores[b][j] if 0 <= j < n else None)
        out[b] = col
    return out


def lag_flags(flags: Dict[str, List[bool]], tau: int) -> Dict[str, List[bool]]:
    """The same delay applied to the OUTPUT of the state machine, for the commutation check.

    Days before the first decision exists are False: "no decision yet" is not-demoted, which is
    the machine's own initial state. Only defined for τ >= 0 (a delayed decision cannot precede
    the machine).
    """
    if tau < 0:
        raise ValueError("lag_flags is a delay — a negative delay is not a decision path")
    books = sorted(flags)
    if not books:
        return {}
    n = len(flags[books[0]])
    return {b: [flags[b][i - tau] if i - tau >= 0 else False for i in range(n)] for b in books}


def commutation_check(panel: "dgo.Panel", kind: str, k: int, m_days: int,
                      taus: Sequence[int] = (1, 2, 3, 5, 10, 20)) -> List[Tuple[int, float, int]]:
    """Is "the feed is τ late" the same thing as "our decision reaches the book τ late"?

    Returns [(τ, agreement, disagreeing cells)] comparing the flags of `lag_scores → machine`
    against `machine → lag_flags`, over the cells where BOTH paths are past their warm-up
    (i >= LOOKBACK + τ). If agreement is 1.0 the two lags are one number and the τ axis of #51
    covers both; where it is not, the entry must say so rather than quietly average them.
    """
    sc = rcd.panel_scores(panel, kind, LOOKBACK)
    base = xsd.rank_demotion_flags(sc, k, m_days)
    out: List[Tuple[int, float, int]] = []
    for tau in taus:
        a = xsd.rank_demotion_flags(lag_scores(sc, tau), k, m_days)
        b = lag_flags(base, tau)
        cells = bad = 0
        for book in sorted(a):
            for i in range(LOOKBACK + tau, panel.n):
                cells += 1
                if a[book][i] != b[book][i]:
                    bad += 1
        out.append((tau, (cells - bad) / cells if cells else 0.0, bad))
    return out


def knife_edge(panel: "dgo.Panel", kind: str, k: int, m_days: int, tau: int = 1
               ) -> Dict[str, object]:
    """WHERE the latency tax is paid: how many book-days a τ-lag moves, and what each date is worth.

    A rule whose whole advantage sits on a handful of days is not a rule with a small latency
    problem — it is a rule with an evidence problem, and the lag axis is just the instrument that
    exposes it. The per-date attribution reverts ONE date of the fresh flags to the lagged
    decision and re-scores; the sum of those deltas need not equal the total (the paths interact),
    so both are printed and neither is presented as a decomposition.
    """
    sc = rcd.panel_scores(panel, kind, LOOKBACK)
    fresh = xsd.rank_demotion_flags(sc, k, m_days)
    late = xsd.rank_demotion_flags(lag_scores(sc, tau), k, m_days)
    cells = [(b, i) for b in sorted(fresh) for i in range(panel.n) if fresh[b][i] != late[b][i]]
    dates = sorted({panel.axis[i] for _, i in cells})

    def score(fl: Dict[str, List[bool]]) -> Dict[str, float]:
        return ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, fl, panel.n))

    m_fresh, m_late = score(fresh), score(late)
    per_date: List[Tuple[str, float]] = []
    for d in dates:
        i = panel.axis.index(d)
        fl = {b: list(fresh[b]) for b in fresh}
        for b in fl:
            fl[b][i] = late[b][i]
        per_date.append((d, score(fl)["calmar"] - m_fresh["calmar"]))
    per_date.sort(key=lambda t: t[1])
    return {
        "cells": len(cells), "dates": len(dates), "total_days": len(fresh) * panel.n,
        "calmar_fresh": m_fresh["calmar"], "calmar_late": m_late["calmar"],
        "delta": m_late["calmar"] - m_fresh["calmar"], "per_date": per_date,
    }


def flag_agreement(a: Dict[str, List[bool]], b: Dict[str, List[bool]], skip: int) -> float:
    """Share of (book, day) cells on which two flag paths agree, ignoring the first `skip` days."""
    cells = bad = 0
    for book in sorted(a):
        for i in range(skip, len(a[book])):
            cells += 1
            if a[book][i] != b[book][i]:
                bad += 1
    return (cells - bad) / cells if cells else 0.0


# ═══════════════════════════════ #52 — outages and fail policies ═══════════════════════════════
def outage_mask(books: Sequence[str], n: int, rate: float, seed: int,
                mean_run: float = OUTAGE_MEAN_RUN, warmup: int = LOOKBACK
                ) -> Dict[str, List[bool]]:
    """True on (book, day) cells where the criterion could not be computed at all.

    Two-state Markov chain per book, independent across books: P(out → back) = 1 / mean_run, and
    P(alive → out) is solved so the steady state equals `rate`. Outages therefore arrive in runs,
    which is how a feed actually fails — an iid coin flip per day would be a much easier problem
    than the one production poses, and would flatter every policy equally.

    Nothing is masked during the warm-up: all four policies must start ranking on the same day, or
    the comparison is between different samples.
    """
    if not 0.0 <= rate < 1.0:
        raise ValueError("outage rate must be in [0, 1) — a permanently dark feed is not a test")
    if mean_run < 1.0:
        raise ValueError("mean_run must be >= 1 day — an outage shorter than a day is not observed")
    back = 1.0 / mean_run
    to_out = rate * back / (1.0 - rate) if rate > 0.0 else 0.0
    rng = random.Random(seed)
    out: Dict[str, List[bool]] = {}
    for b in sorted(books):
        dark = False
        col: List[bool] = []
        for i in range(n):
            dark = (rng.random() >= back) if dark else (rng.random() < to_out)
            col.append(dark and i >= warmup)
        out[b] = col
    return out


def policy_flags(scores: Scores, mask: Dict[str, List[bool]], k: int, readmit_days: int,
                 policy: str) -> Dict[str, List[bool]]:
    """`xsd.rank_demotion_flags` generalised with an explicit behaviour for unmeasured books.

    With an all-False mask every policy reduces to `xsd.rank_demotion_flags(scores, k, M)` exactly
    — pinned in the test-suite, so this cannot quietly drift away from the rule the registry has
    been measuring for nineteen entries.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r} — the four defensible ones are {POLICIES}")
    if k < 1:
        raise ValueError("k must be >= 1 — a rank rule that demotes nobody is not a rule")
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    books = sorted(scores)
    if k >= len(books):
        raise ValueError(f"k={k} with {len(books)} books would demote the whole panel — refused")
    n = len(scores[books[0]])

    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    last_known: Dict[str, Optional[float]] = {b: None for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}

    for i in range(n):
        eff: Dict[str, Optional[float]] = {}
        for b in books:
            if mask[b][i]:
                eff[b] = last_known[b] if policy == "carry" else None
            else:
                if scores[b][i] is not None:
                    last_known[b] = scores[b][i]
                eff[b] = scores[b][i]

        if policy == "closed_panel" and any(mask[b][i] for b in books):
            for b in books:                       # abstain: state held, no counter moves
                out[b].append(demoted[b])
            continue

        rankable = [b for b in books if eff[b] is not None]
        if len(rankable) <= k:
            for b in books:                       # no rank ⇒ no evidence either way (as in #40)
                out[b].append(demoted[b])
            continue

        ordered = sorted(rankable, key=lambda b: (float(eff[b]), b))
        bottom = set(ordered[:k])
        for b in books:
            if policy == "closed_book" and mask[b][i]:
                demoted[b] = True                 # not measured ⇒ not eligible
                good_run[b] = 0
                out[b].append(True)
                continue
            in_bottom = b in bottom
            good_run[b] = 0 if in_bottom else good_run[b] + 1
            if demoted[b]:
                if good_run[b] >= readmit_days:
                    demoted[b] = False
            elif in_bottom:
                demoted[b] = True
            out[b].append(demoted[b])
    return out


def duty_matched_clean(panel: "dgo.Panel", kind: str, k: int, target: float,
                       ms: Sequence[int] = tuple(range(1, 61))
                       ) -> Tuple[int, float, Dict[str, float]]:
    """THE control #52 cannot be read without: the SAME rule, no outage, dialled to the same duty.

    #43/#44 established that on this panel duty is the dominant state variable — it walks
    concentration from 14% to 74% — so any policy that changes how many book-days are spent
    demoted will move Calmar for reasons that have nothing to do with handling a dark feed. This
    finds the M at which the clean rule spends the same share of book-days demoted, and returns it
    with the duty actually achieved: where the gap is large (a criterion whose duty barely responds
    to M), the match FAILED and the row must be read as such rather than quietly compared.
    """
    sc = rcd.panel_scores(panel, kind, LOOKBACK)
    best: Optional[Tuple[float, int, float, Dict[str, List[bool]]]] = None
    for m_days in ms:
        fl = xsd.rank_demotion_flags(sc, k, m_days)
        d = xsd.duty(fl)
        gap = abs(d - target)
        if best is None or gap < best[0]:
            best = (gap, m_days, d, fl)
    assert best is not None
    _, m_days, achieved, flags = best
    return m_days, achieved, ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, flags,
                                                                            panel.n))


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2] if s else float("nan")


# ═══════════════════════════════ idea #51 ═══════════════════════════════
def idea51_slt(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               taus: Sequence[int] = TAUS) -> Dict[str, Dict[str, float]]:
    """Idea #51 — what a τ-day-old rank feed costs the two rules the registry actually proposes."""
    panel = dgo.Panel(subset, start, end)
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []
    for kind, name, k, m_days in RULES:
        sc = rcd.panel_scores(panel, kind, LOOKBACK)
        for tau in taus:
            fl = xsd.rank_demotion_flags(lag_scores(sc, tau), k, m_days)
            tag = f"{name} τ={tau:+d}" if tau < 0 else f"{name} τ={tau}"
            rows.append((tag + (" LOOK-AHEAD" if tau < 0 else ""),
                         ecr.alloc_recycle(panel.books, fl, panel.n), 0.0))
        fresh = xsd.rank_demotion_flags(sc, k, m_days)
        rows.append((f"  CONTROL static twin of {name}",
                     ecr.alloc_static_matched(ecr.alloc_recycle(panel.books, fresh, panel.n)), 0.0))
    out = xsd._report(f"IDEA #51 SLT — signal latency tax [{segment}] — {label}", panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("The static twin is τ-invariant BY CONSTRUCTION (it holds the time-average of the")
        print("τ=0 rule): it is the floor a latency-sensitive rule falls towards, printed once.")
        _agreement_table(panel, taus)
    return out


def _agreement_table(panel: "dgo.Panel", taus: Sequence[int]) -> None:
    """How much of the demotion set a τ-day lag actually moves — the mechanism behind the tax."""
    print()
    print(f"{'rule':22s} " + " ".join(f"{'τ=' + str(t):>8s}" for t in taus if t >= 0)
          + "     (share of book-days whose demotion state is UNCHANGED vs τ=0)")
    for kind, name, k, m_days in RULES:
        sc = rcd.panel_scores(panel, kind, LOOKBACK)
        base = xsd.rank_demotion_flags(sc, k, m_days)
        cells = []
        for tau in taus:
            if tau < 0:
                continue
            fl = xsd.rank_demotion_flags(lag_scores(sc, tau), k, m_days)
            cells.append(f"{flag_agreement(base, fl, LOOKBACK + max(taus)) * 100:7.1f}%")
        print(f"{name:22s} " + " ".join(cells))


# ═══════════════════════════════ idea #52 ═══════════════════════════════
def idea52_sfp(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               rates: Sequence[float] = OUTAGE_RATES, seeds: int = SEEDS
               ) -> Dict[str, Dict[str, float]]:
    """Idea #52 — which fail-behaviour survives an outage, measured as the median over seeds."""
    panel = dgo.Panel(subset, start, end)
    raw = ecr._raw_metrics(panel)
    results: Dict[str, Dict[str, float]] = {}

    if not quiet:
        print()
        print("=" * 110)
        print(f"IDEA #52 SFP — stale-feed policy [{segment}] — {label}  ·  {panel.n} days  ·  "
              f"{len(panel.books)} books  ·  median of {seeds} seeds")
        print("=" * 110)
        print(f"raw equal-weight: APY {raw['apy']*100:.2f}%  maxDD {raw['maxdd']*100:.2f}%  "
              f"Calmar {raw['calmar']:.2f}   ·   outage: two-state Markov, mean run "
              f"{OUTAGE_MEAN_RUN:.0f}d, SYNTHETIC (the panel has no real gaps)")
        print(f"{'rule / policy':30s} {'rate':>6s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
              f"{'ΔCalmar':>8s} {'duty':>6s} {'turn/yr':>8s} {'netAPY':>8s}")

    for kind, name, k, m_days in RULES:
        sc = rcd.panel_scores(panel, kind, LOOKBACK)
        clean = xsd.rank_demotion_flags(sc, k, m_days)
        m0 = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, clean, panel.n))
        key0 = f"{name} · no outage"
        results[key0] = m0
        if not quiet:
            print(f"{name + ' · no outage':30s} {'—':>6s} {m0['apy']*100:7.2f}% "
                  f"{m0['maxdd']*100:7.2f}% {m0['calmar']:8.2f} {m0['calmar']-raw['calmar']:8.2f} "
                  f"{xsd.duty(clean)*100:5.1f}% {m0['turnover_yr']:8.2f} "
                  f"{m0['net_apy_after_cost']*100:7.2f}%")
        for policy in POLICIES:
            for rate in rates:
                per_seed = []
                for s in range(seeds):
                    mask = outage_mask(panel.books, panel.n, rate, seed=1000 * s + 7)
                    fl = policy_flags(sc, mask, k, m_days, policy)
                    m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, fl, panel.n))
                    per_seed.append((m, xsd.duty(fl)))
                med = {f: _median([m[f] for m, _ in per_seed]) for f in per_seed[0][0]}
                med_duty = _median([d for _, d in per_seed])
                key = f"{name} · {policy} @ {int(rate*100)}%"
                med["duty"] = med_duty
                results[key] = med
                if not quiet:
                    print(f"{'  ' + policy:30s} {int(rate*100):5d}% {med['apy']*100:7.2f}% "
                          f"{med['maxdd']*100:7.2f}% {med['calmar']:8.2f} "
                          f"{med['calmar']-raw['calmar']:8.2f} {med_duty*100:5.1f}% "
                          f"{med['turnover_yr']:8.2f} {med['net_apy_after_cost']*100:7.2f}%")
    if not quiet:
        print("-" * 110)
        print("`open` is what the shipped code does today. Any row that beats it is a change the")
        print("curator has to WRITE DOWN; any row that loses to it is the price of writing it down.")
        _duty_matched_table(panel, raw, results, rates)
    return results


def _duty_matched_table(panel: "dgo.Panel", raw: Dict[str, float],
                        results: Dict[str, Dict[str, float]], rates: Sequence[float]) -> None:
    """Every policy row re-read against the clean rule dialled to the SAME duty."""
    print()
    print(f"{'DUTY-MATCHED READING':30s} {'rate':>6s} {'duty':>6s} {'Calmar':>8s} "
          f"{'clean@duty':>11s} {'gapDuty':>8s} {'policy−clean':>13s}")
    for kind, name, k, _m in RULES:
        for policy in POLICIES:
            for rate in rates:
                key = f"{name} · {policy} @ {int(rate*100)}%"
                if key not in results:
                    continue
                row = results[key]
                _, achieved, clean = duty_matched_clean(panel, kind, k, row["duty"])
                print(f"{name + ' · ' + policy:30s} {int(rate*100):5d}% {row['duty']*100:5.1f}% "
                      f"{row['calmar']:8.2f} {clean['calmar']:11.2f} "
                      f"{(achieved-row['duty'])*100:7.1f}pp {row['calmar']-clean['calmar']:13.2f}")


# ═══════════════════════════════ cli ═══════════════════════════════
def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D #51 SLT / #52 SFP — latency and outages")
    ap.add_argument("--idea", choices=("51", "52"), default=None)
    ap.add_argument("--commute", action="store_true", help="the delay-commutation check only")
    ap.add_argument("--knife", action="store_true", help="the per-date attribution of the τ=1 tax")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    args = ap.parse_args(argv)

    panel = dgo.Panel()

    if args.commute:
        _print_commutation(panel)
        return 0

    if args.knife:
        _print_knife(panel)
        return 0

    if args.idea in (None, "51"):
        idea51_slt()
        _print_commutation(panel)
        _print_knife(panel)
        ecr.train_test(idea51_slt, [f"{n} τ={t}" for _, n, _, _ in RULES for t in (0, 1, 3, 5)])
    if args.idea in (None, "52"):
        idea52_sfp(seeds=args.seeds)
    return 0


def _print_commutation(panel: "dgo.Panel") -> None:
    print()
    print("=" * 110)
    print("COMMUTATION — is «the feed is τ late» the same as «our order is τ late»?")
    print("=" * 110)
    for kind, name, k, m_days in RULES:
        cells = commutation_check(panel, kind, k, m_days)
        print(f"{name:22s} " + "  ".join(f"τ={t}: {a*100:.1f}% ({bad} cells differ)"
                                         for t, a, bad in cells))


def _print_knife(panel: "dgo.Panel") -> None:
    print()
    print("=" * 110)
    print("WHERE THE TAX IS PAID — book-days moved by ONE day of staleness, and what each is worth")
    print("=" * 110)
    for kind, name, k, m_days in RULES:
        r = knife_edge(panel, kind, k, m_days)
        top = "  ".join(f"{d} {dc:+.2f}" for d, dc in r["per_date"][:3])
        print(f"{name:22s} {r['cells']:4d} of {r['total_days']} book-days move on "
              f"{r['dates']:3d} dates  ·  Calmar {r['calmar_fresh']:.2f} → {r['calmar_late']:.2f} "
              f"({r['delta']:+.2f})")
        print(f"{'':22s} worst dates: {top}")


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
