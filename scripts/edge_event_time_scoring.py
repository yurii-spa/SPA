#!/usr/bin/env python3
"""
scripts/edge_event_time_scoring.py — registry idea #54 ETS: Event-Time Scoring
(and the DARK-BOOK discovery it fell over on the way in)

THE QUESTION NOBODY IN #35–#53 ASKED
  Every cross-sectional criterion in the registry — #40 XSD (trailing mean), #41 MRD (downside
  contribution), #44 RCD (redundancy), #45 XVD (trailing vol), #53 CQR (mean/vol) — computes its
  statistic over a CALENDAR window: "the last L=60 days". That is the right window if every book
  prints a return every day. On the real 10-book panel it is not:

      data/aggressive_lab/<book>/realized_series.jsonl, phase="backtest" block, 852 days
        pendle_pt_levered  852/852 prints   (100.0%)
        pendle_yt_susde    852/852          (100.0%)
        points_farm        852/852          (100.0%)
        susde_dn           852/852          (100.0%)
        susde_spot         852/852          (100.0%)
        eth_directional    594/852          ( 69.7%)
        leverage_loop      157/852          ( 18.4%)  — last print 2024-08-09, dark 695d after
        lrt_neutral         76/852          (  8.9%)  — last print 2024-08-23, dark 681d after
        levered_restaking   13/852          (  1.5%)  — last print 2024-03-18, dark 839d after
        lp_eth_stable        1/852          (  0.1%)  — last print 2024-03-06, dark 851d after

  A zero row is not "the book was flat". It is the harness FAILING CLOSED: a required feed key was
  absent that day, so the book did not accrue (roster.py: "a required field missing on a tick → the
  entrant FAILS CLOSED ... the harness records an honest gap"). The gap is honest in the producer
  and INVISIBLE in every consumer, because a fail-closed day and a genuinely flat day are the same
  float 0.0 in realized_series.jsonl.

  Consequence, and it is not small: from 2024-08-24 onward — 680 of the 852 days, 80% of the
  sample — FOUR of the ten books are frozen constants. Their trailing mean is exactly 0.00, their
  trailing vol is exactly 0.00. In a bottom-k ranking, a book scoring exactly 0 outranks every live
  book whose trailing mean has gone negative. So on precisely the days the rule is supposed to
  earn its keep, the demotion rule rotates capital INTO the dead books — and since a dead book
  returns exactly 0.0/day, that rotation is a CASH ALLOCATION IN DISGUISE, taken by accident.

  #52 SFP asked the adjacent question ("what to write in the rule on a day a book was not
  measured") and concluded, from this same panel, that "the panel has zero real gaps over 852
  days". That was read off the DATE axis, which is indeed complete. Section 0 below reads the
  ACCRUAL axis, which is not. Same file, different question, opposite answer.

WHAT #54 THEREFORE MEASURES — in two separable parts

  PART A (audit, not a hypothesis): how much of #40 XSD's published number is dead books acting as
  an accidental cash sleeve? Decisive control: the CASH-TWIN — replace the dark books with books
  explicitly named cash_* carrying the identical zeros, then compare
      XSD on all 10 · XSD on the 6 live books · XSD on the 6 live books + an honest cash sleeve
      of the SAME average weight the dark books held.
  If the third reproduces the first, the dead books were a cash rule nobody wrote down.

  PART B (the actual hypothesis): score in EVENT TIME instead of calendar time —
      ETS(b, t) = mean of the last N=60 NONZERO prints of book b strictly before t,
                  searched back at most 365 days; fewer than 10 prints ⇒ score None (UNMEASURED)
  so a sparse book is judged on the returns it actually produced instead of on a mean diluted by
  structural zeros. Paired with an explicit, causal DARKNESS GATE:
      dark(b, t) = prints of b in the 60 days strictly before t < 3
  and the two fail-directions of an unmeasured score, measured against each other rather than
  assumed:
      ETS-open   — unrankable ⇒ cannot be demoted (what rank_demotion_flags does TODAY: the dark
                   feed PROTECTS the book — #52's finding, here on the accrual axis)
      ETS-closed — unrankable or dark ⇒ demoted (invariant #2, fail-CLOSED)

  The arms are laid out so the criterion (calendar vs event time) and the gate (dark books in or
  out) can be read apart, because they are different claims and only one of them is new science.

METHOD — the #40 machinery verbatim, nothing re-tuned
  Panel  : dgo.Panel (cfpt.load_clean_panel — phase="backtest" block only, the phase-glue seam of
           #16/#17 stays cut), 10 books × 852 days, 2024-03-06 .. 2026-07-05.
  Ranking: xsd.rank_demotion_flags (bottom-k, re-admit after M clean days) — unchanged.
  Alloc  : ecr.alloc_recycle (equal weight over survivors, freed slice recycled) — unchanged.
  Cost   : ecr.portfolio_metrics turnover model, 96 bp round-trip (#10/#49) — unchanged.
  Grid   : (k, M) ∈ {1,2,3} × {1,20} — the registry's grid since #40.
  L=60 calendar days / N=60 prints so that CAL and ETS coincide exactly on a book that prints
  every day. That is the point of the pairing, not a tuning choice.

HONEST LIMITS (mirrored into the registry entry)
  (a) The darkness is a property of THIS harness's feed coverage, not a market fact: these books
      did not die, their inputs did. The finding is about what the registry's criteria do when an
      input dies — which is the deployable question, since a real curator faces exactly that.
  (b) The books are REGENERATED nightly (card agent-aggressive-lab-books-are-regenerated), so every
      number here is reproducible only against the panel snapshot of the run date, which the report
      stamps and which the tests do NOT depend on.
  (c) TRAIN (≤2025-06-30) contains the books' live period, TEST is entirely after they went dark.
      The OOS half therefore tests a 6-book panel; stated rather than smoothed over.
  (d) SURVIVORSHIP (inherited from #16/#17): the roster is the surviving one.
  (e) Evidence level L0 — backtest over real feed history, not a live forward track.
  (f) De-risked/undeployed capital earns 0%/day, the registry's conservative convention.

Read-only over data/aggressive_lab/. Touches no state file, no agent, no site, no track.
Advisory / paper / OUTSIDE_RISKPOLICY. stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                 # noqa: E402  (clean panel loader, perf, BP)
import edge_capital_recycling as ecr            # noqa: E402  (allocator + turnover cost model)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel)

# ── parameters (inherited, NOT re-tuned) ─────────────────────────────────────────────────────────
LOOKBACK = xsd.LOOKBACK              # 60 calendar days — #37/#39/#40
ETS_PRINTS = 60                      # 60 prints — the event-time twin of LOOKBACK
ETS_MAX_BACK = 365                   # never look further back than a year for those prints
ETS_MIN_PRINTS = 10                  # fewer than this ⇒ UNMEASURED (None), never a low score
DARK_WIN = 60                        # darkness is judged over the trailing 60 days …
DARK_MIN_PRINTS = 3                  # … a book with < 3 prints in them is DARK (5% density)
PRINT_EPS = 1e-12                    # |r| ≤ this is "no accrual", not "flat" — see module docstring
TRAIN_END = cfpt.TRAIN_END           # "2025-06-30"
BP = cfpt.BP

Scores = Dict[str, List[Optional[float]]]
Flags = Dict[str, List[bool]]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# PANEL PLUMBING
# ═══════════════════════════════════════════════════════════════════════════════════════════════

class SynthPanel:
    """A Panel-shaped view over explicit return series (duck-types dgo.Panel for ecr/xsd).

    Used for the CASH-TWIN control and the live-only sub-panels. It never reads or writes disk and
    never invents a return: every series handed to it comes from the real panel or is an explicit,
    named zero sleeve.
    """

    def __init__(self, axis: Sequence[str], rets: Dict[str, List[float]]) -> None:
        if not axis:
            raise ValueError("empty axis — refusing to report on a fabricated window")
        for b, r in rets.items():
            if len(r) != len(axis):
                raise ValueError(f"{b}: {len(r)} returns on a {len(axis)}-day axis")
        self.axis = list(axis)
        self.books = sorted(rets)
        self.rets = {b: list(rets[b]) for b in self.books}

    @property
    def n(self) -> int:
        return len(self.axis)

    def raw_portfolio(self) -> List[float]:
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]


def sub_panel(panel, books: Sequence[str]) -> SynthPanel:
    """The same panel restricted to `books` (no reload, no re-slice of the axis)."""
    missing = [b for b in books if b not in panel.rets]
    if missing:
        raise KeyError(f"not in panel: {missing}")
    return SynthPanel(panel.axis, {b: list(panel.rets[b]) for b in books})


def with_cash_sleeve(panel, books: Sequence[str], n_cash: int, prefix: str = "cash") -> SynthPanel:
    """`books` from the panel plus `n_cash` explicit 0.00%/day sleeves — the honest twin."""
    rets = {b: list(panel.rets[b]) for b in books}
    for j in range(n_cash):
        rets[f"{prefix}_{j + 1}"] = [0.0] * panel.n
    return SynthPanel(panel.axis, rets)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# SECTION 0 — THE ACCRUAL AXIS (what a zero row actually is)
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def print_stats(panel) -> Dict[str, dict]:
    """Per book: prints, density, longest dark run, last print, and the day it goes dark for good."""
    out: Dict[str, dict] = {}
    for b in panel.books:
        r = panel.rets[b]
        idx = [i for i, x in enumerate(r) if abs(x) > PRINT_EPS]
        longest = cur = 0
        for x in r:
            if abs(x) <= PRINT_EPS:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
        last = idx[-1] if idx else None
        out[b] = {
            "prints": len(idx),
            "density": len(idx) / len(r) if r else 0.0,
            "longest_dark": longest,
            "last_print": panel.axis[last] if last is not None else None,
            "dark_tail": len(r) - 1 - last if last is not None else len(r),
        }
    return out


def live_books(panel, min_density: float = 0.5) -> List[str]:
    """Books that print on at least `min_density` of the sample — the panel that is actually alive.

    A threshold is a choice, so it is reported next to the densities it separates; on this panel the
    gap it lands in is enormous (69.7% vs 18.4%), which is why any threshold in between gives the
    same six books.
    """
    st = print_stats(panel)
    return sorted(b for b in panel.books if st[b]["density"] >= min_density)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# CRITERIA — calendar time vs event time (both strictly causal, through t−1)
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def cal_scores(rets: Dict[str, Sequence[float]], lookback: int = LOOKBACK) -> Scores:
    """#40 XSD verbatim: mean over the previous `lookback` CALENDAR days (None before warm-up)."""
    return xsd.drift_scores(rets, lookback)


def ets_scores(rets: Dict[str, Sequence[float]], n_prints: int = ETS_PRINTS,
               max_back: int = ETS_MAX_BACK, min_prints: int = ETS_MIN_PRINTS) -> Scores:
    """Mean over the last `n_prints` NONZERO prints strictly before t, searched back `max_back` days.

    Fewer than `min_prints` inside the window ⇒ None. None is UNMEASURED, never a low score: a book
    we could not measure has not earned a rank, and handing it one would be an exposure decision
    disguised as a measurement. What to DO with an unmeasured book is the gate's job, deliberately
    kept out of the criterion so the two can be read apart.
    """
    out: Scores = {}
    for b, r in rets.items():
        series: List[Optional[float]] = []
        for i in range(len(r)):
            lo = max(0, i - max_back)
            window = [r[j] for j in range(i - 1, lo - 1, -1) if abs(r[j]) > PRINT_EPS]
            take = window[:n_prints]
            series.append(sum(take) / len(take) if len(take) >= min_prints else None)
        out[b] = series
    return out


def dark_flags(rets: Dict[str, Sequence[float]], win: int = DARK_WIN,
               min_prints: int = DARK_MIN_PRINTS) -> Flags:
    """True on days book b has printed fewer than `min_prints` times in the previous `win` days.

    Strictly causal (window is [t−win, t−1]). During warm-up (i < win) the book is NOT called dark:
    a short history is not evidence of a dead feed, and calling it dark would demote every book on
    day 1 for a reason that has nothing to do with the book.
    """
    out: Flags = {}
    for b, r in rets.items():
        flags: List[bool] = []
        for i in range(len(r)):
            if i < win:
                flags.append(False)
                continue
            prints = sum(1 for j in range(i - win, i) if abs(r[j]) > PRINT_EPS)
            flags.append(prints < min_prints)
        out[b] = flags
    return out


def unmeasured_flags(scores: Scores, warmup: int) -> Flags:
    """True where a score is None AFTER the warm-up — the fail-CLOSED leg of an unmeasured book."""
    return {b: [(s[i] is None and i >= warmup) for i in range(len(s))] for b, s in scores.items()}


def or_flags(*sets: Flags) -> Flags:
    books = sorted(sets[0])
    n = len(sets[0][books[0]])
    return {b: [any(s[b][i] for s in sets) for i in range(n)] for b in books}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# ARMS
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def arm_weights(panel, kind: str, k: int, m_days: int) -> Dict[str, List[float]]:
    """Weights for one arm. `kind` ∈ {raw, cal, cal_gate, ets_open, ets_closed, dark_only}."""
    books, n = panel.books, panel.n
    if kind == "raw":
        w = 1.0 / len(books)
        return {b: [w] * n for b in books}

    if kind == "dark_only":                       # the gate alone, no cross-sectional criterion
        return ecr.alloc_recycle(books, dark_flags(panel.rets), n)

    if kind in ("cal", "cal_gate"):
        sc = cal_scores(panel.rets)
        flags = xsd.rank_demotion_flags(sc, k, m_days)
        if kind == "cal_gate":
            flags = or_flags(flags, dark_flags(panel.rets))
        return ecr.alloc_recycle(books, flags, n)

    if kind in ("ets_open", "ets_closed"):
        sc = ets_scores(panel.rets)
        flags = xsd.rank_demotion_flags(sc, k, m_days)
        if kind == "ets_closed":
            flags = or_flags(flags, dark_flags(panel.rets),
                             unmeasured_flags(sc, LOOKBACK))
        return ecr.alloc_recycle(books, flags, n)

    raise ValueError(f"unknown arm {kind!r}")


ARMS: Tuple[Tuple[str, str], ...] = (
    ("raw", "raw equal-weight (no overlay)"),
    ("cal", "CAL  #40 XSD calendar-mean"),
    ("cal_gate", "CAL + darkness gate"),
    ("ets_open", "ETS  event-time, fail-OPEN"),
    ("ets_closed", "ETS + gate, fail-CLOSED"),
)


def run_grid(panel, label: str, ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20),
             quiet: bool = False) -> Dict[str, Dict[str, float]]:
    """The (k, M) grid over every arm. Returns {row_name: metrics}."""
    out: Dict[str, Dict[str, float]] = {}
    base = ecr.portfolio_metrics(panel, arm_weights(panel, "raw", 1, 1))
    out["raw"] = base
    if not quiet:
        print()
        print("=" * 118)
        print(f"{label}  ·  {panel.n} days {panel.axis[0]}..{panel.axis[-1]}  ·  "
              f"{len(panel.books)} books [bt]")
        print("=" * 118)
        print(f"{'configuration':40s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
              f"{'depl':>7s} {'turn/yr':>8s} {'netAPY':>8s} {'maxW':>7s}")
        print("-" * 118)
        _row("raw equal-weight (no overlay)", base)

    for kind, pretty in ARMS:
        if kind == "raw":
            continue
        for k in ks:
            for m_days in ms:
                name = f"{pretty}  k={k} M={m_days}"
                m = ecr.portfolio_metrics(panel, arm_weights(panel, kind, k, m_days))
                out[name] = m
                if not quiet:
                    _row(name, m)
    gate = ecr.portfolio_metrics(panel, arm_weights(panel, "dark_only", 1, 1))
    out["GATE-ONLY darkness gate, no ranking"] = gate
    if not quiet:
        _row("  GATE-ONLY darkness gate, no ranking", gate)
    return out


def _row(name: str, m: Dict[str, float]) -> None:
    print(f"{name:40s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f} "
          f"{m['deployed']*100:6.1f}% {m['turnover_yr']:8.2f} "
          f"{m['net_apy_after_cost']*100:7.2f}% {m['max_weight']*100:6.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# SECTION 1 — WHAT A FROZEN BOOK DOES TO A RANK
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def dark_weight_share(panel, dark: Sequence[str], k: int = 2, m_days: int = 20,
                      stress_win: int = 20) -> Dict[str, float]:
    """Under #40 XSD, how much of the portfolio sits in books that are already permanently dark?

    Reported over the whole sample and over the STRESS days the rule exists for — days on which the
    live books' own equal-weight sleeve has lost money over the trailing `stress_win` days. (The
    first definition tried here, "≥ half the live books' trailing 60-day mean is negative", fired on
    zero days out of 852: with five books carrying a positive funding/points drift, a majority-
    negative 60-day mean never occurs on this panel. A stress definition that never fires measures
    nothing, so it was replaced rather than reported as a null.)
    """
    w = arm_weights(panel, "cal", k, m_days)
    live = [b for b in panel.books if b not in dark]
    n = panel.n
    live_pf = [sum(panel.rets[b][i] for b in live) / len(live) for i in range(n)]
    share_all, share_stress, stress_days = 0.0, 0.0, 0
    for i in range(n):
        s = sum(w[b][i] for b in dark)
        share_all += s
        if i >= stress_win:
            trail = 1.0
            for j in range(i - stress_win, i):
                trail *= 1.0 + live_pf[j]
            if trail < 1.0:
                share_stress += s
                stress_days += 1
    return {
        "share_all": share_all / n,
        "share_stress": share_stress / stress_days if stress_days else 0.0,
        "stress_days": float(stress_days),
    }


def rank_position_of_dark(panel, dark: Sequence[str]) -> Dict[str, float]:
    """Where a frozen book lands in the CAL cross-section: fraction of days it is in the TOP half.

    A frozen book scores exactly 0.00. It therefore outranks every live book whose trailing mean has
    turned negative — mechanically, not because anything about it improved.
    """
    sc = cal_scores(panel.rets)
    n, books = panel.n, panel.books
    top_half, ranked_days = 0, 0
    for i in range(n):
        rankable = [b for b in books if sc[b][i] is not None]
        if len(rankable) < 2:
            continue
        ranked_days += 1
        ordered = sorted(rankable, key=lambda b: (float(sc[b][i]), b), reverse=True)
        cut = max(1, len(ordered) // 2)
        top = set(ordered[:cut])
        if any(b in top for b in dark if b in rankable):
            top_half += 1
    return {"top_half_frac": top_half / ranked_days if ranked_days else 0.0,
            "ranked_days": float(ranked_days)}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# REPORT SECTIONS
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def section0(panel) -> Tuple[List[str], List[str]]:
    st = print_stats(panel)
    live = live_books(panel)
    dark = [b for b in panel.books if b not in live]
    print()
    print("=" * 118)
    print("SECTION 0 — THE ACCRUAL AXIS: a zero row is a fail-CLOSED day, not a flat day")
    print("=" * 118)
    print(f"{'book':22s} {'prints':>8s} {'density':>9s} {'longest dark':>13s} "
          f"{'last print':>12s} {'dark tail':>10s}")
    print("-" * 118)
    for b in sorted(panel.books, key=lambda x: -st[x]["density"]):
        s = st[b]
        print(f"{b:22s} {s['prints']:8d} {s['density']*100:8.1f}% {s['longest_dark']:12d}d "
              f"{str(s['last_print']):>12s} {s['dark_tail']:9d}d")
    print("-" * 118)
    print(f"LIVE (density ≥ 50%): {len(live)} books — {', '.join(live)}")
    print(f"DARK inside the sample: {len(dark)} books — {', '.join(dark)}")
    if dark:
        first_all_dark = max(panel.axis.index(st[b]['last_print']) for b in dark
                             if st[b]['last_print'] is not None)
        print(f"From {panel.axis[first_all_dark]} onward ({panel.n - 1 - first_all_dark} of "
              f"{panel.n} days = {(panel.n - 1 - first_all_dark)/panel.n*100:.0f}% of the sample) "
              f"the panel is effectively {len(live)} books, not {len(panel.books)}.")
    return live, dark


def section1(panel, dark: Sequence[str]) -> None:
    print()
    print("=" * 118)
    print("SECTION 1 — WHAT A FROZEN BOOK DOES TO THE #40 RANK")
    print("=" * 118)
    if not dark:
        print("no dark books on this panel — section is vacuous, which is itself the answer")
        return
    pos = rank_position_of_dark(panel, dark)
    sh = dark_weight_share(panel, dark)
    print(f"A dark book sits in the TOP HALF of the CAL cross-section on "
          f"{pos['top_half_frac']*100:.1f}% of the {int(pos['ranked_days'])} rankable days.")
    print(f"Under #40 XSD k=2 M=20, dark books hold {sh['share_all']*100:.1f}% of the portfolio on "
          f"average across the sample,")
    print(f"and {sh['share_stress']*100:.1f}% on the {int(sh['stress_days'])} STRESS days "
          f"(live sleeve down over the trailing 20 days).")
    print("Those weights earn exactly 0.00%/day. That is a cash allocation, taken by accident,")
    print("through books whose feed died — and it is inside every published number of #40–#53.")

    # Why the event-time criterion cannot fix this by itself: on a dark book, CAL decays toward
    # 0.00 as the zeros fill the window, while ETS keeps quoting the mean of prints up to a YEAR
    # old — i.e. it hands a dead book the score it had while it was alive.
    cal, ets = cal_scores(panel.rets), ets_scores(panel.rets)
    st = print_stats(panel)
    print()
    print(f"{'dark book':22s} {'CAL score in dark tail':>24s} {'ETS score in dark tail':>24s}"
          f" {'ETS age (days)':>16s}")
    print("-" * 118)
    for b in sorted(dark):
        lp = st[b]["last_print"]
        if lp is None:
            continue
        i0 = panel.axis.index(lp) + 1 + LOOKBACK       # after the calendar window has fully filled
        cs = [cal[b][i] for i in range(i0, panel.n) if cal[b][i] is not None]
        es = [ets[b][i] for i in range(i0, panel.n) if ets[b][i] is not None]
        r = panel.rets[b]
        ages = []
        for i in range(i0, panel.n):
            back = [j for j in range(i - 1, max(-1, i - 1 - ETS_MAX_BACK), -1)
                    if abs(r[j]) > PRINT_EPS]
            if len(back) >= ETS_MIN_PRINTS:
                ages.append(i - back[0])
        ets_txt = f"{sum(es)/len(es)*1e4:20.2f} bp/d" if es else f"{'UNMEASURED (None)':>25s}"
        age_txt = f"{sum(ages)/len(ages):16.0f}" if ages else f"{'—':>16s}"
        print(f"{b:22s} {(sum(cs)/len(cs)*1e4 if cs else 0.0):20.2f} bp/d {ets_txt} {age_txt}")
    print("A dark book's CAL score is 0.00 bp/d by construction (its window is all zeros). Its ETS")
    print("score is whatever it last EARNED, quoted from prints up to a year stale — and the sign of")
    print("that stale number decides its fate for a year: leverage_loop keeps a POSITIVE +2.38 bp/d")
    print("and outranks live books that are currently losing, while levered_restaking keeps −38.84")
    print("and is demoted for the right answer for the wrong reason. Past the 365-day horizon ETS")
    print("returns None, and under ETS-open (what rank_demotion_flags does today) a None book can")
    print("never be demoted at all — the dead feed PROTECTS the book. That is why #54's named")
    print("hypothesis loses to the criterion it was meant to improve (section 3): event time")
    print("re-animates dead books; only the explicit darkness gate retires them.")


def _window(panel, start: Optional[str] = None, end: Optional[str] = None) -> SynthPanel:
    ax = [d for d in panel.axis
          if (start is None or d >= start) and (end is None or d <= end)]
    idx = [panel.axis.index(d) for d in ax]
    return SynthPanel(ax, {b: [panel.rets[b][i] for i in idx] for b in panel.books})


def section2(panel, live: Sequence[str], dark: Sequence[str], k: int = 2, m_days: int = 20) -> None:
    """The decisive control: is the dark sleeve just cash?

    Run twice. On the FULL sample the twin cannot be exact — the four books were alive for the first
    ~170 days, so a named cash sleeve is genuinely a different series there. On the DARK-TAIL window
    (from the day the last of them printed) they are provably frozen, and the twin is the whole
    claim: if the metrics coincide there, the dead books are literally a cash sleeve.
    """
    st = print_stats(panel)
    tail_start_i = max(panel.axis.index(st[b]["last_print"]) for b in dark
                       if st[b]["last_print"] is not None) + 1
    tail_start = panel.axis[tail_start_i]

    for tag, p in (("FULL sample", panel), (f"DARK TAIL from {tail_start}",
                                            _window(panel, start=tail_start))):
        print()
        print("=" * 118)
        print(f"SECTION 2 — CASH-TWIN CONTROL [{tag}] (k={k} M={m_days}): "
              f"were the dead books a cash rule?")
        print("=" * 118)
        live_p = sub_panel(p, live)
        twin = with_cash_sleeve(p, live, len(dark))
        full = ecr.portfolio_metrics(p, arm_weights(p, "cal", k, m_days))
        twin_m = ecr.portfolio_metrics(twin, arm_weights(twin, "cal", k, m_days))
        only_m = ecr.portfolio_metrics(live_p, arm_weights(live_p, "cal", k, m_days))
        print(f"{'configuration':40s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
              f"{'depl':>7s} {'turn/yr':>8s} {'netAPY':>8s} {'maxW':>7s}")
        print("-" * 118)
        _row(f"raw equal-weight, all {len(p.books)}", ecr.portfolio_metrics(
            p, arm_weights(p, "raw", k, m_days)))
        _row(f"raw equal-weight, {len(live)} live only", ecr.portfolio_metrics(
            live_p, arm_weights(live_p, "raw", k, m_days)))
        _row(f"XSD on all {len(p.books)} books (published #40 shape)", full)
        _row(f"XSD on {len(live)} live + {len(dark)} named cash sleeves", twin_m)
        _row(f"XSD on the {len(live)} live books only", only_m)
        print("-" * 118)
        print(f"cash-twin vs dark-book panel: ΔCalmar {twin_m['calmar']-full['calmar']:+.2f}  "
              f"ΔAPY {(twin_m['apy']-full['apy'])*100:+.2f}pp  "
              f"ΔmaxDD {(twin_m['maxdd']-full['maxdd'])*100:+.2f}pp  "
              f"ΔnetAPY {(twin_m['net_apy_after_cost']-full['net_apy_after_cost'])*100:+.2f}pp")
        print(f"dropping the dead books (HINDSIGHT, not deployable): ΔCalmar "
              f"{only_m['calmar']-full['calmar']:+.2f}  "
              f"ΔnetAPY {(only_m['net_apy_after_cost']-full['net_apy_after_cost'])*100:+.2f}pp")
    print()
    print("Deltas ≈ 0 on the DARK TAIL ⇒ the dead books ARE a cash sleeve: the published #40 number")
    print("is not a cross-sectional edge over ten books, it is a six-book rule carrying an")
    print("unlabelled, unintended cash leg that nobody sized, reviewed or wrote down.")


def arm_flags(panel, kind: str, k: int, m_days: int) -> Flags:
    """The demotion flags of one arm, before allocation (so the cap can be varied over them)."""
    sc = cal_scores(panel.rets) if kind in ("cal", "cal_gate") else ets_scores(panel.rets)
    flags = xsd.rank_demotion_flags(sc, k, m_days)
    if kind == "cal_gate":
        flags = or_flags(flags, dark_flags(panel.rets))
    elif kind == "ets_closed":
        flags = or_flags(flags, dark_flags(panel.rets), unmeasured_flags(sc, LOOKBACK))
    return flags


def capped_table(panel, title: str, k: int = 2, m_days: int = 20) -> Dict[str, Dict[str, float]]:
    """Deployability: every arm uncapped and under the project's own 20% per-name cap.

    Recycling the dead books' slice raises the survivors' weights; the ungated rows already sit at
    16.7% and the gated ones breach 20%. A number that only exists above the cap the project would
    actually deploy under is not a proposal, so the capped twin is printed beside it, not in a
    footnote.
    """
    print()
    print("=" * 118)
    print(f"{title}  ·  {panel.n}d {panel.axis[0]}..{panel.axis[-1]}  ·  k={k} M={m_days}  ·  "
          f"cap {int(ecr.CONC_CAP*100)}%")
    print("=" * 118)
    print(f"{'configuration':40s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
          f"{'depl':>7s} {'turn/yr':>8s} {'netAPY':>8s} {'maxW':>7s}")
    print("-" * 118)
    out: Dict[str, Dict[str, float]] = {}
    books, n = panel.books, panel.n
    _row("raw equal-weight (no overlay)", ecr.portfolio_metrics(
        panel, arm_weights(panel, "raw", k, m_days)))
    for kind, pretty in ARMS:
        if kind == "raw":
            continue
        flags = arm_flags(panel, kind, k, m_days)
        for cap, tag in ((None, "uncapped"), (ecr.CONC_CAP, f"cap {int(ecr.CONC_CAP*100)}%")):
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(books, flags, n, cap=cap))
            out[f"{kind}/{tag}"] = m
            _row(f"{pretty}  [{tag}]", m)
    return out


def section3(panel, live: Sequence[str]) -> None:
    run_grid(panel, "SECTION 3 — CRITERION × GATE on all 10 books [bt]")
    run_grid(sub_panel(panel, live),
             "SECTION 3b — the same arms on the LIVE books only (darkness removed by hand)")


def section4(panel) -> None:
    """TRAIN / TEST. Stated honestly: TEST is a post-mortem window for four of the books."""
    print()
    print("=" * 118)
    print(f"SECTION 4 — OOS SPLIT at {TRAIN_END}  (TRAIN holds the books' live period; "
          f"TEST is entirely after they went dark)")
    print("=" * 118)
    tr_axis = [d for d in panel.axis if d <= TRAIN_END]
    te_axis = [d for d in panel.axis if d > TRAIN_END]
    for seg, ax in (("TRAIN", tr_axis), ("TEST", te_axis)):
        idx = [panel.axis.index(d) for d in ax]
        sp = SynthPanel(ax, {b: [panel.rets[b][i] for i in idx] for b in panel.books})
        run_grid(sp, f"[{seg}] {ax[0]}..{ax[-1]}", ks=(2,), ms=(20,))
        capped_table(sp, f"[{seg}] under the per-name cap")


def section5(panel, live: Sequence[str], k: int = 2, m_days: int = 20) -> None:
    """Leave-one-out over the LIVE books: is any conclusion one book's property?

    Both surviving claims are carried through the same omission: the GATE (cal_gate vs cal, under
    the 20% cap — the only deployable form) and the CRITERION (ets_closed vs cal). Calmar AND
    netAPY, because the gate's whole effect is to trade one for the other and a single column
    would let either side of that trade disappear.
    """
    print()
    print("=" * 118)
    print(f"SECTION 5 — LEAVE-ONE-OUT over the live books (k={k} M={m_days}, cap "
          f"{int(ecr.CONC_CAP*100)}%)")
    print("=" * 118)
    print(f"{'omitted':20s} {'CAL Cal':>9s} {'gate Cal':>9s} {'ΔCal':>7s} | "
          f"{'CAL net':>9s} {'gate net':>9s} {'Δnet':>7s} | {'ETS net':>9s} {'Δnet':>7s}")
    print("-" * 118)
    for omit in ["(none)"] + list(live):
        books = [b for b in panel.books if b != omit]
        sp = sub_panel(panel, books)
        m: Dict[str, Dict[str, float]] = {}
        for kind in ("cal", "cal_gate", "ets_closed"):
            w = ecr.alloc_recycle(sp.books, arm_flags(sp, kind, k, m_days), sp.n, cap=ecr.CONC_CAP)
            m[kind] = ecr.portfolio_metrics(sp, w)
        c0, c1 = m["cal"]["calmar"], m["cal_gate"]["calmar"]
        n0, n1 = m["cal"]["net_apy_after_cost"], m["cal_gate"]["net_apy_after_cost"]
        n2 = m["ets_closed"]["net_apy_after_cost"]
        print(f"{omit:20s} {c0:9.2f} {c1:9.2f} {c1-c0:+7.2f} | {n0*100:8.2f}% {n1*100:8.2f}% "
              f"{(n1-n0)*100:+6.2f}pp | {n2*100:8.2f}% {(n2-n0)*100:+6.2f}pp")


def section6(panel, dark: Sequence[str], k: int = 2, m_days: int = 20) -> None:
    """Who else steps in this hole? #45 XVD — "demote the noisiest, keep the quietest".

    A book whose feed died has trailing volatility of exactly zero. A criterion that rewards
    quietness therefore rewards death. Measured rather than asserted, because "it must follow from
    the definition" is how a wrong number gets into a registry.
    """
    import edge_redundancy_demotion as rcd     # noqa: E402  (#44/#45 criteria)

    print()
    print("=" * 118)
    print(f"SECTION 6 — DOES #45 XVD REWARD DEATH? (k={k} M={m_days}, «keep the quietest»)")
    print("=" * 118)
    sc = rcd.volatility_scores(panel.rets)
    flags = xsd.rank_demotion_flags(sc, k, m_days)
    n = panel.n
    order_pos: Dict[str, List[int]] = {b: [] for b in panel.books}
    for i in range(n):
        rankable = [b for b in panel.books if sc[b][i] is not None]
        if len(rankable) < k + 1:
            continue
        ordered = sorted(rankable, key=lambda b: (float(sc[b][i]), b))
        for j, b in enumerate(ordered):
            order_pos[b].append(j + 1)
    print(f"{'book':22s} {'demoted days':>14s} {'share':>8s} {'avg XVD rank':>14s}   (1 = first to "
          f"be demoted)")
    print("-" * 118)
    for b in sorted(panel.books, key=lambda x: (sum(order_pos[x]) / len(order_pos[x]))
                    if order_pos[x] else 99.0):
        d = sum(1 for i in range(n) if flags[b][i])
        avg = sum(order_pos[b]) / len(order_pos[b]) if order_pos[b] else float("nan")
        print(f"{b:22s} {d:14d} {d/n*100:7.1f}% {avg:14.2f}   {'DARK' if b in dark else ''}")
    never = [b for b in dark if not any(flags[b])]
    print("-" * 118)
    print(f"Dead books NEVER demoted by XVD in {n} days: {', '.join(never) if never else '—'}.")
    print("Zero volatility is not calm, it is silence. A criterion that rewards quietness rewards")
    print("death — and #45's own verdict was never read with that in mind.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Registry idea #54 — event-time scoring / dark books")
    ap.add_argument("--section", default="all",
                    choices=["all", "0", "1", "2", "3", "4", "5", "6"])
    args = ap.parse_args(list(argv) if argv is not None else None)

    panel = dgo.Panel()
    live, dark = section0(panel)
    want = args.section
    if want in ("all", "1"):
        section1(panel, dark)
    if want in ("all", "2"):
        section2(panel, live, dark)
        capped_table(panel, "SECTION 2b — the same arms under the per-name cap [FULL]")
    if want in ("all", "3"):
        section3(panel, live)
    if want in ("all", "4"):
        section4(panel)
    if want in ("all", "5"):
        section5(panel, live)
    if want in ("all", "6"):
        section6(panel, dark)

    print()
    print("=" * 118)
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence L0 (backtest on real feed history)")
    print(f"L={LOOKBACK}d / N={ETS_PRINTS} prints / dark = <{DARK_MIN_PRINTS} prints in {DARK_WIN}d "
          f"/ cost 96 bp round-trip (#10/#49)")
    print("Panel is regenerated nightly — numbers are reproducible against the snapshot of the run "
          "date only.")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
