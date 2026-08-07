#!/usr/bin/env python3
"""Edge R&D — registry ideas #40 (XSD) and #41 (MRD). Both attack the SAME unexamined convention
in #39: that a book is demoted on an ABSOLUTE judgement about itself.

WHERE THIS COMES FROM
  #39 (CDR) is the registry's first configuration whose netAPY after cost (21.88%) beats raw
  (17.94%) at a third less drawdown. Its rule demotes a book when its own trailing drift falls
  below a fixed hurdle, and re-admits it after M quiet days. Two things about that rule were
  never examined, and they are entangled inside the single number it reports:

    1. WHICH information pays — "this book is broken in absolute terms" or "this book is the
       worst one available right now"? #39's own leave-one-out says the INCOME half of its win is
       essentially one book (eth_directional, whose drift is negative most of the sample), which
       is exactly what an absolute hurdle is best at catching. If the pay-off is relative rather
       than absolute, the rule should be written differently — and it would then be a statement
       about SELECTION, not about brokenness.

    2. HOW MUCH TIME the rule spends out. Under an absolute hurdle duty is a free variable of the
       market: in a broad calm nobody is demoted (the rule is asleep); in a broad sell-off
       everything is demoted at once and the portfolio goes to cash. Every absolute-threshold
       entry in this registry therefore confounds "which book" with "how long in cash" — the two
       move together and no entry has separated them.

  A cross-sectional rank rule separates them BY CONSTRUCTION: exactly k of N books are out on
  every rankable day, whatever the market is doing. Duty is a constant of the rule, not of the
  regime, so the difference between a rank row and a duty-matched absolute row is attributable to
  the WHICH-book information alone.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #40 — XSD: Cross-Sectional Demotion  ("worst available", not "below zero")
──────────────────────────────────────────────────────────────────────────────────────────────
      score(b, t)  = mean(r_b[t−L : t−1])              ← #39's statistic, byte-for-byte
      DEMOTED(b,t) : score(b,t) is among the k LOWEST scores across the books rankable at t
      RE-ADMIT     : the book has been OUT of the bottom-k on M consecutive days
      capital of demoted books is split over the books that remain eligible (#39's allocator)

  Everything except the demotion CRITERION is #39's and is held fixed: same panel, same L=60,
  same re-admission state machine, same allocator, same turnover cost model. With M=1 the state
  is exactly "in the bottom-k today", pinned by the test-suite, so the M column is read the same
  way it is read in #39.

  THE STRUCTURAL LIMIT, STATED BEFORE THE NUMBERS (it does not go away if the table is good):
  a bottom-k rule ALWAYS keeps 100% of capital deployed. It can rotate capital away from the
  worst book; it can NEVER take the portfolio down as a whole. Against a common shock that hits
  all ten books it is, by construction, defenceless — where #39's absolute rule would empty the
  book. XSD is a SELECTION rule wearing a de-risk rule's clothes, and if it wins on drawdown it
  wins only through dispersion between books, never through exposure. Any deployment of it must
  therefore keep a separate, absolute, portfolio-level kill path — it does not replace one.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #41 — MRD: Marginal Risk Demotion  ("what a book does to the PORTFOLIO, not to itself")
──────────────────────────────────────────────────────────────────────────────────────────────
      D(t)         = days in [t−L, t−1] on which the equal-weight panel return was NEGATIVE
      score(b, t)  = mean(r_b[s] for s in D(t))        ← the book's average return on the
                                                          portfolio's BAD days
      DEMOTED(b,t) : bottom-k by that score; re-admission and allocator exactly as in #40

  Motivation is #39's own honest half: its win is a RISK win (−5.44% → −3.37% drawdown holds in
  every leave-one-out portfolio) while its income win is one book. If the thing being bought is
  drawdown, then ranking books by their contribution to the portfolio's drawdown should buy it
  more directly — and, unlike a rule keyed on a single book's drift, should NOT concentrate in
  one name. That is a falsifiable prediction about the leave-one-out table, and it is checked.

  The reference portfolio in D(t) is the RAW equal-weight panel, never the rule's own current
  weights. That is deliberate: a score that read its own positions would feed back on itself, and
  two rows of the table would stop being comparable. Stated as a convention, not hidden.

──────────────────────────────────────────────────────────────────────────────────────────────
CONTROLS (a rank rule always holds something, so it can post a number with no information at all)
──────────────────────────────────────────────────────────────────────────────────────────────
  • TOP-k sign flip     — demote the BEST-ranked books instead of the worst. If that does as well,
                          the ranking carries no information and the number is an artifact of
                          rotating capital at all.
  • DUTY-MATCHED ABSOLUTE — #39's absolute rule, its three knobs (L, hurdle, M) searched so that
                          its duty equals the rank rule's. This is the decisive control of #40:
                          with time out of the market equalised, the remaining difference is the
                          criterion. The naive version of this control — bisect the hurdle alone —
                          is kept in the table as HURDLE-ONLY because it FAILS, and its failure is
                          itself the cleanest statement of point 2 above: at fixed L and M the
                          absolute rule's duty jumps from 11.7% straight to 46.4% as the hurdle
                          crosses zero. There is no absolute hurdle that spends 26% of book-days
                          demoted on this panel; duty is not a knob of that rule.
  • STATIC WEIGHT-MATCHED — the time-average of the dynamic weights, held constant (#38's control).
                          If the static twin matches, this is an allocator tilt, not a timing rule.
  • BOOK PERMUTATION / TIME ROTATION — #38's information controls, reused unchanged.
  • LEAVE-ONE-OUT       — mandatory since #37; a ΔCalmar carried by one book is not a portfolio edge.
  • TRAIN → TEST        — split at 2025-06-30, the registry's own.
  • WORST-WINDOW        — what each rule did during the panel's deepest drawdown, since that is
                          precisely where the structural limit above should show up.

HONESTY / SCOPE (registry rules — non-negotiable)
  • Strictly causal: every weight for day i is decided from information through i−1 only, pinned
    in both directions by the test-suite.
  • The clean panel loader of #32 is IMPORTED, not re-implemented. Books are REGENERATED nightly,
    so numbers are reproducible only against the panel files of the run date.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence L0 (backtest on real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_cross_sectional_demotion.py            # everything
    python3 scripts/edge_cross_sectional_demotion.py --idea 40  # XSD only
    python3 scripts/edge_cross_sectional_demotion.py --idea 41  # MRD only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt            # noqa: E402  (audited loader + metrics of idea #32)
import edge_capital_recycling as ecr       # noqa: E402  (allocator, cost model, controls of #38/#39)
import edge_drift_gated_overlay as dgo     # noqa: E402  (Panel, signals of #35/#36/#37)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = ecr.SDS_LOOKBACK        # 60 — inherited from #37/#39, NOT re-tuned here
HURDLE = ecr.SDS_HURDLE            # 0.0 — inherited, used only by the absolute reference rows
TRAIN_END = ecr.TRAIN_END
RF_ANNUAL = ecr.RF_ANNUAL
BP = cfpt.BP
EPS = 1e-12

Scores = Dict[str, List[Optional[float]]]


# ═══════════════════════════════ scores (causal, through t−1) ═══════════════════════════════
def drift_scores(rets: Dict[str, Sequence[float]], lookback: int = LOOKBACK) -> Scores:
    """#39's statistic, per book: the trailing mean return through t−1.

    `None` before `lookback` points exist — an unmeasured drift is not a low drift, and must not
    be rankable. (`cfpt.trailing_mean` returns 0.0 there, which would rank a warming-up book in
    the middle of the field; that is exactly the silent fabrication this returns None instead of.)
    """
    out: Scores = {}
    for b, r in rets.items():
        mu = cfpt.trailing_mean(r, lookback)
        out[b] = [None if i < lookback else mu[i] for i in range(len(r))]
    return out


def downside_contribution_scores(rets: Dict[str, Sequence[float]], lookback: int = LOOKBACK,
                                 min_down_days: int = 5) -> Scores:
    """#41's statistic: each book's mean return on the days the RAW panel was down.

    The reference portfolio is the equal-weight panel itself, not the rule's own weights (see the
    module docstring). Fail-CLOSED twice: before `lookback` points exist, and whenever the window
    holds fewer than `min_down_days` down-days — a co-movement estimated on two bad days is not an
    estimate, and the book is left unrankable (hence never demoted) rather than ranked on noise.
    """
    books = sorted(rets)
    if not books:
        return {}
    n = len(rets[books[0]])
    pf = [sum(rets[b][i] for b in books) / len(books) for i in range(n)]
    out: Scores = {b: [None] * n for b in books}
    for i in range(n):
        if i < lookback:
            continue
        down = [s for s in range(max(0, i - lookback), i) if pf[s] < 0.0]
        if len(down) < min_down_days:
            continue
        for b in books:
            out[b][i] = sum(rets[b][s] for s in down) / len(down)
    return out


# ═══════════════════════════════ the rank rule ═══════════════════════════════
def rank_demotion_flags(scores: Scores, k: int, readmit_days: int = 1,
                        worst_first: bool = True) -> Dict[str, List[bool]]:
    """True on days the book is DEMOTED because it sits in the bottom-k of the cross-section.

        demote   : book is among the k lowest scores of the rankable books on day t
        re-admit : the book has been OUT of that set on `readmit_days` consecutive days

    The state machine is #39's (`ecr.demotion_flags`) with one substitution — "below the hurdle"
    becomes "in the bottom-k" — so with `readmit_days == 1` the state is exactly membership of
    the bottom-k, and the M axis means in #40/#41 what it means in #39. Pinned by the test-suite.

    Fail-CLOSED in three places, all of them cases where a rank is not defined:
      • fewer than k+1 rankable books on a day ⇒ NOBODY changes state (a field in which everyone
        is the worst has no worst; demoting k of k would be an exposure decision in disguise);
      • a book with score None is not rankable and can never enter the bottom-k;
      • ties are broken by book name, so the report is reproducible rather than dict-ordered.

    `worst_first=False` is the sign-flipped CONTROL (demote the BEST-ranked books). It is never a
    proposed rule; it exists so that "the ranking carries information" is a measured claim.
    """
    if k < 1:
        raise ValueError("k must be >= 1 — a rank rule that demotes nobody is not a rule")
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    books = sorted(scores)
    if k >= len(books):
        raise ValueError(f"k={k} with {len(books)} books would demote the whole panel — refused")
    n = len(scores[books[0]]) if books else 0
    sign = 1.0 if worst_first else -1.0

    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}
    for i in range(n):
        rankable = [b for b in books if scores[b][i] is not None]
        if len(rankable) <= k:
            for b in books:                       # state frozen: no rank ⇒ no evidence either way
                out[b].append(demoted[b])
            continue
        ordered = sorted(rankable, key=lambda b: (sign * float(scores[b][i]), b))
        bottom = set(ordered[:k])
        for b in books:
            in_bottom = b in bottom
            good_run[b] = 0 if in_bottom else good_run[b] + 1
            if demoted[b]:
                if good_run[b] >= readmit_days:
                    demoted[b] = False
            elif in_bottom:
                demoted[b] = True
            out[b].append(demoted[b])
    return out


def combined_flags(rank: Dict[str, List[bool]],
                   absolute: Dict[str, List[bool]]) -> Dict[str, List[bool]]:
    """Demoted if EITHER rule says so — the practical hybrid a tier curator would actually write.

    Reported because the two rules answer different questions ("worst available" vs "broken"), and
    the portfolio-level exposure cut that #40 structurally cannot make is exactly what the
    absolute leg still provides.
    """
    return {b: [rank[b][i] or absolute[b][i] for i in range(len(rank[b]))] for b in sorted(rank)}


def duty(flags: Dict[str, Sequence[bool]]) -> float:
    """Fraction of (book, day) cells spent demoted — the quantity the duty-matched control equalises."""
    cells = sum(len(v) for v in flags.values())
    return sum(1 for v in flags.values() for f in v if f) / cells if cells else 0.0


def absolute_flags(panel: "dgo.Panel", hurdle: float, lookback: int = LOOKBACK,
                   readmit_days: int = 1) -> Dict[str, List[bool]]:
    """#39's rule verbatim (`ecr.demotion_flags`), applied book by book at a given hurdle."""
    return {b: ecr.demotion_flags(panel.rets[b], lookback, hurdle, readmit_days)
            for b in panel.books}


def match_duty_hurdle(panel: "dgo.Panel", target_duty: float, lookback: int = LOOKBACK,
                      readmit_days: int = 1, lo: float = -2.0, hi: float = 2.0,
                      iterations: int = 44) -> Tuple[float, float]:
    """Bisect the absolute HURDLE toward `target_duty`, holding L and M fixed. Returns (hurdle, duty).

    Duty is non-decreasing in the hurdle (a higher bar demotes weakly more book-days), so the
    bisection itself is sound — but on this panel it does NOT converge to an arbitrary target, and
    that failure is a finding rather than a bug (see `HURDLE-ONLY` in the report): at L=60, M=20
    the duty of the absolute rule jumps from 11.7% to 46.4% as the hurdle crosses zero, with
    nothing in between. Under an absolute criterion duty is a property of the MARKET, not a knob
    of the rule. The caller must therefore always report the ACHIEVED duty beside the target and
    never present this row as matched when it is not.
    """
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if duty(absolute_flags(panel, mid, lookback, readmit_days)) < target_duty:
            lo = mid
        else:
            hi = mid
    h = 0.5 * (lo + hi)
    return h, duty(absolute_flags(panel, h, lookback, readmit_days))


def match_duty_absolute(panel: "dgo.Panel", target_duty: float,
                        lookbacks: Sequence[int] = (30, 45, 60, 90, 120),
                        readmits: Sequence[int] = (1, 2, 3, 5, 10, 20, 30, 45, 60),
                        hurdles: Optional[Sequence[float]] = None
                        ) -> Tuple[int, float, int, float]:
    """THE control of #40: the absolute-criterion configuration whose duty is closest to a target.

    Since the hurdle alone cannot reach an arbitrary duty (above), the search runs over all three
    of the absolute rule's own knobs — drift window L, hurdle, re-admission delay M — and returns
    the closest attainable `(lookback, hurdle, readmit, duty)`. Two properties of this control
    matter more than its convenience:

      • it is chosen with FULL-SAMPLE knowledge of its own duty, i.e. a look-ahead advantage is
        deliberately GRANTED to the control. If the rank rule still wins, it wins against a
        handicap in the control's favour, which is the direction an honest comparison should err;
      • the residual |achieved − target| is returned so the report can state it. A control that
        silently missed its target by twenty points would turn a duty comparison into a duty
        confound — which is exactly the trap the hurdle-only bisection walks into.
    """
    if hurdles is None:
        hurdles = [j * 0.005 for j in range(-40, 41)]
    best: Optional[Tuple[float, int, float, int, float]] = None
    cells = len(panel.books) * panel.n
    for lkb in lookbacks:
        # The trailing mean is the expensive part and depends on L alone — computed once per L,
        # then reused for every (hurdle, M). `_demoted_days_from_mu` is pinned by the test-suite
        # to agree with `ecr.demotion_flags` exactly, so this is a speed-up, not a second rule.
        mus = {b: cfpt.trailing_mean(panel.rets[b], lkb) for b in panel.books}
        for m_days in readmits:
            for h in hurdles:
                out = sum(_demoted_days_from_mu(mus[b], lkb, h, m_days) for b in panel.books)
                d = out / cells if cells else 0.0
                err = abs(d - target_duty)
                if best is None or err < best[0]:
                    best = (err, lkb, h, m_days, d)
    assert best is not None
    return best[1], best[2], best[3], best[4]


def _demoted_days_from_mu(mu: Sequence[float], lookback: int, hurdle_annual: float,
                          readmit_days: int) -> int:
    """Count of demoted days for #39's absolute rule, given a PRE-COMPUTED trailing mean.

    Exists only so the duty search can sweep thousands of (hurdle, M) pairs without recomputing
    the trailing mean each time. The state machine below is a transcription of
    `ecr.demotion_flags`; the test-suite pins the two to agree on a parameter grid, because a
    transcription that quietly drifted would make the control a different rule than the one it
    claims to duty-match.
    """
    thr = hurdle_annual / 365.0
    demoted = False
    good_run = 0
    total = 0
    for i in range(len(mu)):
        if i < lookback:
            continue
        above = mu[i] >= thr
        good_run = good_run + 1 if above else 0
        if demoted:
            if good_run >= readmit_days:
                demoted = False
        elif not above:
            demoted = True
        total += 1 if demoted else 0
    return total


# ═══════════════════════════════ reporting ═══════════════════════════════
def _panel_scores(panel: "dgo.Panel", kind: str, lookback: int = LOOKBACK) -> Scores:
    if kind == "drift":
        return drift_scores(panel.rets, lookback)
    if kind == "downside":
        return downside_contribution_scores(panel.rets, lookback)
    raise ValueError(f"unknown score kind {kind!r}")


def _rows(panel: "dgo.Panel", kind: str, ks: Sequence[int], ms: Sequence[int],
          full_controls: bool = True) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """The table body shared by #40 and #41 — only the score function differs between them.

    `full_controls=False` drops the duty-match search (a 3600-configuration sweep) and is used by
    the leave-one-out and train/test passes, which re-run this body once per sub-panel and do not
    read those rows. Nothing that any reported number depends on is skipped.
    """
    sc = _panel_scores(panel, kind)
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    abs20 = absolute_flags(panel, HURDLE, LOOKBACK, 20)
    rows.append(("#39 CDR absolute M=20", ecr.alloc_recycle(books, abs20, n), 0.0))

    ref_k, ref_m = ks[len(ks) // 2], ms[-1]
    for k in ks:
        for m_days in ms:
            fl = rank_demotion_flags(sc, k, m_days)
            rows.append((f"XSD k={k} M={m_days}" if kind == "drift" else f"MRD k={k} M={m_days}",
                         ecr.alloc_recycle(books, fl, n), 0.0))

    ref = rank_demotion_flags(sc, ref_k, ref_m)
    target = duty(ref)
    rows.append((f"  CONTROL top-k flip k={ref_k} M={ref_m}",
                 ecr.alloc_recycle(books, rank_demotion_flags(sc, ref_k, ref_m, worst_first=False),
                                   n), 0.0))
    if full_controls:
        h_only, d_only = match_duty_hurdle(panel, target, LOOKBACK, ref_m)
        rows.append((f"  HURDLE-ONLY duty {d_only*100:.0f}% vs {target*100:.0f}% MISS",
                     ecr.alloc_recycle(books, absolute_flags(panel, h_only, LOOKBACK, ref_m), n),
                     0.0))
        lkb_m, h_m, m_m, d_m = match_duty_absolute(panel, target)
        rows.append((f"  CONTROL duty-matched abs {d_m*100:.0f}% (L{lkb_m}/M{m_m})",
                     ecr.alloc_recycle(books, absolute_flags(panel, h_m, lkb_m, m_m), n), 0.0))
    rows.append(("  CONTROL static-matched",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, ref, n)), 0.0))
    rows.append((f"  HYBRID rank-or-absolute k={ref_k} M={ref_m}",
                 ecr.alloc_recycle(books, combined_flags(ref, abs20), n), 0.0))
    # Deployability, not a control: recycling raises the survivors' weights, and the project's own
    # per-name limit for T2 is 20%. The capped row says what is left of the number once the rule
    # has to live inside the concentration limit it would actually be deployed under.
    rows.append((f"  under {int(ecr.CONC_CAP*100)}% per-name cap k={ref_k} M={ref_m}",
                 ecr.alloc_recycle(books, ref, n, cap=ecr.CONC_CAP), 0.0))
    return rows


def absolute_is_subset_of_rank(panel: "dgo.Panel", kind: str, k: int, m_days: int,
                               hurdle: float = HURDLE, readmit_abs: int = 20) -> Tuple[int, int]:
    """(book-days demoted by the absolute rule but NOT by the rank rule, absolute's total).

    Reported because the HYBRID row is only interesting if the two rules disagree somewhere. If
    the absolute rule's demotions are a strict subset of the rank rule's, the hybrid is the rank
    rule with extra words, and that has to be said rather than shown as a separate winning line.
    """
    sc = _panel_scores(panel, kind)
    rank = rank_demotion_flags(sc, k, m_days)
    absolute = absolute_flags(panel, hurdle, LOOKBACK, readmit_abs)
    extra = sum(1 for b in panel.books for i in range(panel.n)
                if absolute[b][i] and not rank[b][i])
    total = sum(1 for b in panel.books for i in range(panel.n) if absolute[b][i])
    return extra, total


def _report(title: str, panel: "dgo.Panel", rows, quiet: bool) -> Dict[str, Dict[str, float]]:
    base = ecr._raw_metrics(panel)
    if not quiet:
        ecr._header(title, panel, base)
    results: Dict[str, Dict[str, float]] = {}
    for name, w, cash_rate in rows:
        m = ecr.portfolio_metrics(panel, w, cash_annual=cash_rate)
        results[name.strip()] = m
        if not quiet:
            ecr._row(name, m, base)
    return results


def idea40_xsd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20)
               ) -> Dict[str, Dict[str, float]]:
    """Idea #40 — is the demotion win about "below zero" or about "worst available"?"""
    panel = dgo.Panel(subset, start, end)
    rows = _rows(panel, "drift", ks, ms, full_controls=not quiet)
    out = _report(f"IDEA #40 XSD — cross-sectional demotion [{segment}] — {label}",
                  panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("depl stays ~100% for every XSD row BY CONSTRUCTION — that is the structural limit,")
        print("not a result: a bottom-k rule can rotate capital, it can never take the book down.")
        print("HURDLE-ONLY is a FAILED match kept in the table on purpose: with L and M fixed, the")
        print("absolute rule's duty jumps 11.7% → 46.4% as the hurdle crosses zero and cannot be")
        print("dialled in between. The matched control below had to move L and M as well.")
        extra, total = absolute_is_subset_of_rank(panel, "drift", ks[len(ks) // 2], ms[-1])
        print(f"HYBRID: of {total} book-days the absolute rule demotes, {extra} are NOT already "
              f"demoted by the rank rule — the hybrid is the rank rule with extra words."
              if extra == 0 else
              f"HYBRID: the absolute rule demotes {extra} of {total} book-days the rank rule does "
              f"not — the two rules genuinely disagree, and the hybrid row is worth reading.")
    return out


def idea41_mrd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20)
               ) -> Dict[str, Dict[str, float]]:
    """Idea #41 — rank by contribution to the portfolio's bad days instead of by own drift."""
    panel = dgo.Panel(subset, start, end)
    rows = _rows(panel, "downside", ks, ms, full_controls=not quiet)
    return _report(f"IDEA #41 MRD — marginal risk demotion [{segment}] — {label}",
                   panel, rows, quiet)


def sweep(kind: str, ks: Sequence[int] = (1, 2, 3, 4, 5),
          ms: Sequence[int] = (1, 2, 3, 5, 10, 20, 45)) -> None:
    """Plateau or lottery ticket? ΔCalmar over the (books demoted × re-admission delay) grid."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = _panel_scores(panel, kind)
    tag = "#40 XSD" if kind == "drift" else "#41 MRD"
    print()
    print("=" * 110)
    print(f"{tag} — SWEEP of ΔCalmar vs raw ({base['calmar']:.2f}); rows = k books demoted, "
          f"cols = re-admission delay M")
    print("=" * 110)
    # The corner label is bound to a name rather than written inline: a backslash inside an
    # f-string replacement field is a SyntaxError before Python 3.12, and the CI matrix runs
    # 3.11 — where it is not a bad row, it is a COLLECTION error that reddens the whole suite.
    corner = "k \\ M"
    print(f"{corner:>8s}" + "".join(f"{m:>8d}" for m in ms))
    for k in ks:
        cells = []
        for m_days in ms:
            w = ecr.alloc_recycle(panel.books, rank_demotion_flags(sc, k, m_days), panel.n)
            cells.append(ecr.portfolio_metrics(panel, w)["calmar"] - base["calmar"])
        print(f"{k:>8d}" + "".join(f"{c:>+8.2f}" for c in cells))


def worst_window(kind: str, k: int = 2, m_days: int = 20) -> None:
    """The structural limit, measured: what each rule held through the panel's deepest drawdown.

    The rank rule is always fully deployed, so if the raw panel's worst stretch is a COMMON move
    it cannot help there, and any drawdown improvement it shows must come from dispersion between
    books instead. Printing the raw peak-to-trough window beside each rule's own return over the
    same days is the cheapest way to keep that distinction from being blurred in a Calmar column.
    """
    panel = dgo.Panel()
    raw = panel.raw_portfolio()
    eq, peak, worst, lo_i, pk_i, cur_pk = 1.0, 1.0, 0.0, 0, 0, 0
    for i, r in enumerate(raw):
        eq *= 1.0 + r
        if eq > peak:
            peak, cur_pk = eq, i
        dd = eq / peak - 1.0
        if dd < worst:
            worst, lo_i, pk_i = dd, i, cur_pk

    sc = _panel_scores(panel, kind)
    rank = rank_demotion_flags(sc, k, m_days)
    abs20 = absolute_flags(panel, HURDLE, LOOKBACK, m_days)
    print()
    print("=" * 110)
    print(f"WORST WINDOW — raw peak-to-trough {panel.axis[pk_i]}..{panel.axis[lo_i]} "
          f"({lo_i - pk_i} days, raw {worst*100:.2f}%)")
    print("=" * 110)
    tag = "XSD" if kind == "drift" else "MRD"
    for name, flags in ((f"{tag} k={k} M={m_days}", rank), ("#39 absolute M=%d" % m_days, abs20)):
        w = ecr.alloc_recycle(panel.books, flags, panel.n)
        seg = 1.0
        depl = 0.0
        for i in range(pk_i + 1, lo_i + 1):
            deployed = sum(w[b][i] for b in panel.books)
            depl += deployed
            seg *= 1.0 + sum(w[b][i] * panel.rets[b][i] for b in panel.books)
        days = max(1, lo_i - pk_i)
        print(f"  {name:28s} return over the window {(seg-1)*100:+7.2f}%   "
              f"average deployed {depl/days*100:5.1f}%")
    print("  A rule that improves Calmar while staying 100% deployed did it by CHOOSING books,")
    print("  not by reducing exposure — it is not a substitute for a portfolio-level kill path.")


def leave_one_out(idea: Callable[..., Dict[str, Dict[str, float]]], key: str) -> None:
    """#37's mandatory check, reused verbatim from #38/#39 so the tables stay comparable."""
    ecr.leave_one_out(idea, key)


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idea", type=int, choices=(40, 41), default=None)
    args = ap.parse_args(argv)

    print("Ideas #40 XSD / #41 MRD — ADVISORY, OUTSIDE_RISKPOLICY, evidence L0 (backtest).")
    print("Capital does not move. The live track and RiskPolicy v1.0 are not touched.")

    if args.idea in (None, 40):
        idea40_xsd()
        sweep("drift")
        ecr.train_test(idea40_xsd, ["#39 CDR absolute M=20", "XSD k=1 M=20", "XSD k=2 M=20",
                                    "XSD k=3 M=20", "CONTROL static-matched",
                                    "CONTROL top-k flip k=2 M=20"])
        leave_one_out(idea40_xsd, "XSD k=2 M=20")
        panel = dgo.Panel()
        fl = rank_demotion_flags(_panel_scores(panel, "drift"), 2, 20)
        ecr.information_controls(panel, fl, "XSD k=2 M=20")
        ecr.weight_decomposition(panel, fl, "XSD k=2 M=20 recycled")
        worst_window("drift")

    if args.idea in (None, 41):
        idea41_mrd()
        sweep("downside")
        ecr.train_test(idea41_mrd, ["#39 CDR absolute M=20", "MRD k=1 M=20", "MRD k=2 M=20",
                                    "MRD k=3 M=20", "CONTROL static-matched",
                                    "CONTROL top-k flip k=2 M=20"])
        leave_one_out(idea41_mrd, "MRD k=2 M=20")
        panel = dgo.Panel()
        fl = rank_demotion_flags(_panel_scores(panel, "downside"), 2, 20)
        ecr.information_controls(panel, fl, "MRD k=2 M=20")
        ecr.weight_decomposition(panel, fl, "MRD k=2 M=20 recycled")
        worst_window("downside")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
