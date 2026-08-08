#!/usr/bin/env python3
"""Edge R&D — registry ideas #44 (RCD) and #45 (XVD): demotion criteria that CANNOT SEE RETURNS.

WHERE THIS COMES FROM
  Entry #43 closed the #37–#43 family with a claim that is much larger than the rule it was
  testing: measured over 172 configurations of three criterion families, the spread of ΔCalmar
  BETWEEN families inside one duty bucket was 1.29, while the spread BETWEEN duty buckets was
  4.72. Its words: *"the demotion criterion is a footnote, and the state variable is duty"* —
  and, on this allocator, duty IS concentration (maxW walks 14% → 74% as duty rises).

  That claim was inferred from three criteria that are all functions of a book's RETURNS:
  trailing drift (#39/#40), return on the portfolio's bad days (#41), dispersion-gated and
  z-scored versions of the same drift (#42/#43). Reading it strictly, it says the return
  information those criteria carry is worth ~1.29 of ΔCalmar against ~4.72 for the duty knob.
  But every one of them still HAD return information. Nobody ever ran the experiment that makes
  the claim falsifiable: **a criterion carrying no return information at all.**

  These two ideas are that experiment, and they are also two honest edge candidates in their own
  right — "hold the least redundant books" and "hold the calmest books" are real, well-known
  selection rules that this registry has never measured on the real panel.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #44 — RCD: Redundancy-Concentration Demotion  ("drop what the portfolio already owns")
──────────────────────────────────────────────────────────────────────────────────────────────
      score(b, t) = − mean over peers a≠b of  corr(r_b, r_a) on [t−L, t−1]
      DEMOTED(b,t): score among the k LOWEST  ⇒  the k MOST REDUNDANT books are dropped
      RE-ADMIT    : out of that bottom-k on M consecutive days      (state machine of #39/#40)
      allocator, panel, L=60, cost model: #39/#40's, byte-for-byte

  WHY IT IS THE DECISIVE CONTROL. Pearson correlation is invariant under any positive affine
  transform of either series: multiply a book's whole return path by 3, add 10bp/day to it, and
  its every correlation is unchanged. So this score literally cannot distinguish the panel's best
  book from its worst. It is return-BLIND by construction, not by intention — and the test-suite
  pins that as a property, so it cannot quietly stop being true.

  WHY IT IS ALSO A REAL CANDIDATE. Dropping the most redundant book is the textbook
  diversification move; on a panel of ten books that share two or three factors it should raise
  effective breadth. If it works, the win is a RISK win by construction, never an income win.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #45 — XVD: Cross-Sectional Volatility Demotion  ("drop the noisiest, keep the calmest")
──────────────────────────────────────────────────────────────────────────────────────────────
      score(b, t) = − stdev(r_b on [t−L, t−1])
      everything else exactly as #44

  Half-blind rather than blind: σ is invariant under a sign flip of the whole return path, so
  XVD cannot tell a book that earns 20%/yr from its exact mirror image that loses it. It CAN see
  scale. It therefore sits deliberately between #40 (fully return-aware) and #44 (fully blind),
  and the three of them read as a ladder of how much return information a criterion carries.

──────────────────────────────────────────────────────────────────────────────────────────────
THE THREE OUTCOMES, WRITTEN DOWN BEFORE THE NUMBERS (all three are publishable)
──────────────────────────────────────────────────────────────────────────────────────────────
  A. RCD ≈ XSD at matched duty  → #43 confirmed in its strongest form: the return information in
     the whole #37–#43 family is worth nothing, the number belongs to duty/concentration, and the
     two paper modules the owner sanctioned (#39 CDR, #36 dwell) MUST log realised duty and
     concentration or their forward track will not be interpretable.
  B. RCD ≪ XSD at matched duty  → #43 OVERREACHES: return information does pay, its
     duty-collapse merely lacked the contrast that would have shown it. The criterion is not a
     footnote and the family's numbers survive as criterion findings.
  C. RCD ≫ XSD                  → a new edge of a kind this registry has never held: selection
     on covariance structure, orthogonal to every return-based entry (#1–#43).

  A CONTROL THE REGISTRY DOES NOT YET HAVE. #38's controls (permute books, rotate time) destroy
  one kind of information inside a REAL criterion's flag paths. They cannot answer "what would
  ANY bottom-k rule of this duty have scored?" — so this module adds the pure null: a criterion
  that is nothing but a fixed-seed random number, its M swept until its duty matches the real
  rule's. That null is what turns "our number is big" into "our number is bigger than nothing".

HONESTY / SCOPE (registry rules — non-negotiable)
  • Strictly causal: every score for day i is computed from returns through i−1 only, pinned in
    both directions by the test-suite. Unrankable ⇒ never demoted (fail-CLOSED), never ranked at
    a fabricated zero.
  • The clean panel loader of #32 and the rank machinery of #40 are IMPORTED, not re-implemented.
    Books are regenerated nightly, so numbers reproduce only against the panel files of the run
    date (2026-08-08: 10 books, 852 days, raw 17.94% / −5.44% / Calmar 3.30).
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence L0 (backtest on real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_redundancy_demotion.py              # everything
    python3 scripts/edge_redundancy_demotion.py --idea 44    # RCD only
    python3 scripts/edge_redundancy_demotion.py --idea 45    # XVD only
    python3 scripts/edge_redundancy_demotion.py --contrast   # the criterion-ladder table only
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                 # noqa: E402  (audited loader + metrics of #32)
import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, controls #38/#39)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40/#41)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K, REF_M = 2, 20             # #40's reference cell, so the contrast is like-for-like
MIN_PEERS = 2                    # fewer usable peers than this ⇒ redundancy is not estimated
VAR_FLOOR = 1e-16                # a book with no variance in the window has no correlation

Scores = xsd.Scores


# ═══════════════════════ return-blind scores (causal, window [t−L, t−1]) ═══════════════════════
def rolling_corr(x: Sequence[float], y: Sequence[float], lookback: int) -> List[Optional[float]]:
    """corr(x, y) over the window [i−L, i−1] at each i, `None` where it is not defined.

    Causal by construction: index i is never inside its own window. `None` in two cases, both of
    them fail-CLOSED — before `lookback` points exist, and when either leg has no variance in the
    window (a flat book correlates with nothing; scoring it 0.0 would drop it into the middle of
    the cross-section, which is exactly the silent fabrication this refuses).
    """
    if lookback < 2:
        raise ValueError("lookback must be >= 2 — correlation over one point is not a number")
    n = len(x)
    if len(y) != n:
        raise ValueError("series of different length — refusing to align by position")
    out: List[Optional[float]] = [None] * n
    sx = sy = sxx = syy = sxy = 0.0
    for i in range(n):
        if i >= 1:                                    # window gains day i−1 …
            a, b = x[i - 1], y[i - 1]
            sx += a; sy += b; sxx += a * a; syy += b * b; sxy += a * b
        j = i - 1 - lookback                          # … and loses the day that fell out of it
        if j >= 0:
            a, b = x[j], y[j]
            sx -= a; sy -= b; sxx -= a * a; syy -= b * b; sxy -= a * b
        if i < lookback:
            continue
        m = float(lookback)
        vx = max(0.0, sxx / m - (sx / m) ** 2)
        vy = max(0.0, syy / m - (sy / m) ** 2)
        if vx <= VAR_FLOOR or vy <= VAR_FLOOR:
            continue
        out[i] = (sxy / m - (sx / m) * (sy / m)) / math.sqrt(vx * vy)
    return out


def redundancy_scores(rets: Dict[str, Sequence[float]], lookback: int = LOOKBACK,
                      min_peers: int = MIN_PEERS) -> Scores:
    """#44's statistic: MINUS the book's mean correlation with its peers, so bottom-k = most redundant.

    Return-blind: correlation is invariant under r → a·r + b for any a > 0, so no monotone
    transform of a book's profitability can move this score. Pinned by the test-suite.
    """
    books = sorted(rets)
    if len(books) < min_peers + 1:
        raise ValueError(f"{len(books)} books cannot support a peer estimate with min_peers={min_peers}")
    n = len(rets[books[0]])
    pair: Dict[Tuple[str, str], List[Optional[float]]] = {}
    for a, b in combinations(books, 2):
        pair[(a, b)] = rolling_corr(rets[a], rets[b], lookback)

    out: Scores = {b: [None] * n for b in books}
    for b in books:
        peers = [pair[(min(b, o), max(b, o))] for o in books if o != b]
        for i in range(n):
            vals = [p[i] for p in peers if p[i] is not None]
            if len(vals) < min_peers:
                continue
            out[b][i] = -sum(vals) / len(vals)
    return out


def volatility_scores(rets: Dict[str, Sequence[float]], lookback: int = LOOKBACK) -> Scores:
    """#45's statistic: MINUS the book's trailing stdev, so bottom-k = most volatile.

    `cfpt.trailing_vol` reports 0.0 during warm-up, which would rank a warming-up book as the
    CALMEST on the panel and permanently protect it. Masked to None for the same reason
    `xsd.drift_scores` masks its own warm-up.
    """
    out: Scores = {}
    for b, r in rets.items():
        sd = cfpt.trailing_vol(r, lookback)
        out[b] = [None if i < lookback else -sd[i] for i in range(len(r))]
    return out


def random_scores(books: Sequence[str], n: int, seed: int, warmup: int = LOOKBACK) -> Scores:
    """The pure null: a criterion made of nothing but a fixed-seed random number.

    Same warm-up as the real criteria, so the rules start ranking on the same day and the panel
    they are scored over is identical. This is not a strategy and is never proposed as one.
    """
    rng = random.Random(seed)
    return {b: [None if i < warmup else rng.random() for i in range(n)] for b in sorted(books)}


def panel_scores(panel: "dgo.Panel", kind: str, lookback: int = LOOKBACK) -> Scores:
    """One dispatcher for the whole criterion ladder, so every row shares the rank machinery."""
    if kind in ("drift", "downside"):
        return xsd._panel_scores(panel, kind, lookback)
    if kind == "redundancy":
        return redundancy_scores(panel.rets, lookback)
    if kind == "volatility":
        return volatility_scores(panel.rets, lookback)
    raise ValueError(f"unknown score kind {kind!r}")


CRITERIA: Tuple[Tuple[str, str, str], ...] = (
    ("drift", "#40 XSD drift (return-aware)", "sees level and scale"),
    ("downside", "#41 MRD bad-day return", "sees level and scale"),
    ("volatility", "#45 XVD volatility", "sees scale only (sign-blind)"),
    ("redundancy", "#44 RCD redundancy", "sees NEITHER (return-blind)"),
)


# ═══════════════════════════════ duty bookkeeping ═══════════════════════════════
def rule_duty(scores: Scores, k: int, m_days: int) -> float:
    return xsd.duty(xsd.rank_demotion_flags(scores, k, m_days))


def match_duty_random(panel: "dgo.Panel", target: float, k: int = REF_K,
                      ms: Sequence[int] = tuple(range(1, 41)),
                      seeds: int = 20) -> Tuple[int, float]:
    """The M at which the random null spends the same share of book-days demoted as the real rule.

    Swept rather than assumed, because a random criterion's duty is NOT k/N once M > 1: it enters
    the bottom-k by luck and then has to stay out of it M days running, which for iid noise is
    rare. That the sweep is necessary at all is a result in its own right (see `criterion_ladder`).
    """
    best: Optional[Tuple[float, int, float]] = None
    for m_days in ms:
        duties = [rule_duty(random_scores(panel.books, panel.n, s), k, m_days)
                  for s in range(seeds)]
        med = sorted(duties)[len(duties) // 2]
        gap = abs(med - target)
        if best is None or gap < best[0]:
            best = (gap, m_days, med)
    assert best is not None
    return best[1], best[2]


# ═══════════════════════════════ tables ═══════════════════════════════
def _rows_for(panel: "dgo.Panel", kind: str, ks: Sequence[int], ms: Sequence[int]
              ) -> List[Tuple[str, Dict[str, List[float]], float]]:
    sc = panel_scores(panel, kind)
    books, n = panel.books, panel.n
    tag = {"redundancy": "RCD", "volatility": "XVD", "drift": "XSD", "downside": "MRD"}[kind]
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    rows.append(("#39 CDR absolute M=20",
                 ecr.alloc_recycle(books, xsd.absolute_flags(panel, xsd.HURDLE, LOOKBACK, 20), n), 0.0))
    drift_ref = xsd.rank_demotion_flags(panel_scores(panel, "drift"), REF_K, REF_M)
    rows.append((f"#40 XSD drift k={REF_K} M={REF_M}", ecr.alloc_recycle(books, drift_ref, n), 0.0))

    for k in ks:
        for m_days in ms:
            fl = xsd.rank_demotion_flags(sc, k, m_days)
            rows.append((f"{tag} k={k} M={m_days}", ecr.alloc_recycle(books, fl, n), 0.0))

    ref = xsd.rank_demotion_flags(sc, REF_K, REF_M)
    rows.append((f"  CONTROL top-k flip k={REF_K} M={REF_M}",
                 ecr.alloc_recycle(books, xsd.rank_demotion_flags(sc, REF_K, REF_M,
                                                                  worst_first=False), n), 0.0))
    rows.append(("  CONTROL static-matched",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, ref, n)), 0.0))
    rows.append((f"  under {int(ecr.CONC_CAP*100)}% per-name cap k={REF_K} M={REF_M}",
                 ecr.alloc_recycle(books, ref, n, cap=ecr.CONC_CAP), 0.0))

    # Two rows that only make sense once a rule turns out to spend most of its duty on ONE book.
    # The static twin asks whether the dynamics matter at all; the look-ahead policy row is #39's
    # own comparator ("just delete the broken book forever") and is the ceiling a selection rule
    # would have to beat to be worth its turnover. Both are controls, neither is a proposal.
    lean = xsd.rank_demotion_flags(sc, 1, 1)
    rows.append(("  CONTROL static twin of k=1 M=1",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, lean, n)), 0.0))
    if "eth_directional" in books:
        forever = {b: [b == "eth_directional"] * n for b in books}
        rows.append(("  POLICY drop eth_directional (LOOK-AHEAD)",
                     ecr.alloc_recycle(books, forever, n), 0.0))
    return rows


def idea44_rcd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20)
               ) -> Dict[str, Dict[str, float]]:
    """Idea #44 — does a criterion that cannot see returns buy the same thing a return criterion does?"""
    panel = dgo.Panel(subset, start, end)
    rows = _rows_for(panel, "redundancy", ks, ms)
    out = xsd._report(f"IDEA #44 RCD — redundancy demotion [{segment}] — {label}", panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("depl stays ~100% for every RCD row BY CONSTRUCTION — the structural limit of #40")
        print("applies unchanged: a bottom-k rule rotates capital, it can never take the book down,")
        print("and any deployment must keep a separate absolute portfolio-level kill path.")
    return out


def idea45_xvd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20)
               ) -> Dict[str, Dict[str, float]]:
    """Idea #45 — the half-blind rung of the ladder: rank on scale, blind to sign."""
    panel = dgo.Panel(subset, start, end)
    rows = _rows_for(panel, "volatility", ks, ms)
    return xsd._report(f"IDEA #45 XVD — volatility demotion [{segment}] — {label}", panel, rows, quiet)


def criterion_ladder(k: int = REF_K, m_days: int = REF_M, seeds: int = 20) -> None:
    """THE experiment: identical machinery, identical (k, M), only the criterion changes.

    The rank family hands this comparison something #43 had to search three knobs for — with k
    and M fixed, duty is very nearly a constant of the machinery rather than of the criterion, so
    the rows below are close to duty-matched by construction. The duty column is printed for every
    row so that "close to" is a number the reader checks, not a claim they take.
    """
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"CRITERION LADDER at k={k}, M={m_days} — same rank machinery, same allocator, "
          f"only the score differs")
    print("=" * 110)
    print(f"raw panel: APY {base['apy']*100:.2f}%  maxDD {base['maxdd']*100:.2f}%  "
          f"Calmar {base['calmar']:.2f}   ({len(panel.books)} books, {panel.n} days, "
          f"{panel.axis[0]}..{panel.axis[-1]})")
    print(f"{'criterion':34s} {'duty':>7s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} "
          f"{'ΔCalmar':>8s} {'turn/yr':>8s} {'netAPY':>8s} {'maxW':>6s}")

    def emit(name: str, flags: Dict[str, List[bool]]) -> Dict[str, float]:
        w = ecr.alloc_recycle(panel.books, flags, panel.n)
        m = ecr.portfolio_metrics(panel, w)
        max_w = max(sum(w[b]) / panel.n for b in panel.books)
        print(f"{name:34s} {xsd.duty(flags)*100:6.1f}% {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% "
              f"{m['calmar']:8.2f} {m['calmar']-base['calmar']:8.2f} {m['turnover_yr']:8.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {max_w*100:5.1f}%")
        return m

    ladder: Dict[str, Dict[str, float]] = {}
    duties: Dict[str, float] = {}
    for kind, name, blindness in CRITERIA:
        sc = panel_scores(panel, kind)
        fl = xsd.rank_demotion_flags(sc, k, m_days)
        duties[kind] = xsd.duty(fl)
        ladder[kind] = emit(f"{name}", fl)
        print(f"{'':34s} └ {blindness}")

    # the pure null, at the SAME (k, M) and then at duty-matched M
    print(f"{'':-<110s}")
    target = duties["drift"]
    raw_null = [ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books, xsd.rank_demotion_flags(random_scores(panel.books, panel.n, s), k, m_days),
        panel.n)) for s in range(seeds)]
    d_raw = sorted(rule_duty(random_scores(panel.books, panel.n, s), k, m_days)
                   for s in range(seeds))[seeds // 2]
    srt = sorted(raw_null, key=lambda m: m["calmar"])
    for tag, m in (("P10", srt[max(0, int(0.1 * seeds) - 1)]), ("P50", srt[seeds // 2]),
                   ("P90", srt[min(seeds - 1, int(0.9 * seeds))])):
        print(f"{'RANDOM null M=' + str(m_days) + ' ' + tag:34s} {d_raw*100:6.1f}% "
              f"{m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f} "
              f"{m['calmar']-base['calmar']:8.2f} {m['turnover_yr']:8.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {'':>5s}")
    m_match, d_match = match_duty_random(panel, target, k, seeds=seeds)
    matched = [ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books, xsd.rank_demotion_flags(random_scores(panel.books, panel.n, s), k, m_match),
        panel.n)) for s in range(seeds)]
    srt2 = sorted(matched, key=lambda m: m["calmar"])
    for tag, m in (("P10", srt2[max(0, int(0.1 * seeds) - 1)]), ("P50", srt2[seeds // 2]),
                   ("P90", srt2[min(seeds - 1, int(0.9 * seeds))])):
        print(f"{'RANDOM duty-matched M=' + str(m_match) + ' ' + tag:34s} {d_match*100:6.1f}% "
              f"{m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f} "
              f"{m['calmar']-base['calmar']:8.2f} {m['turnover_yr']:8.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {'':>5s}")
    beaten = sum(1 for m in matched if m["calmar"] >= ladder["redundancy"]["calmar"])
    print(f"  → duty-matched random draws reaching RCD's Calmar: {beaten}/{seeds} "
          f"(empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")
    beaten_d = sum(1 for m in matched if m["calmar"] >= ladder["drift"]["calmar"])
    print(f"  → duty-matched random draws reaching XSD's Calmar: {beaten_d}/{seeds} "
          f"(empirical p ≈ {(beaten_d + 1) / (seeds + 1):.3f})")

    print()
    lo, hi = min(duties.values()), max(duties.values())
    print(f"DUTY SPREAD across the four real criteria at (k={k}, M={m_days}): "
          f"{lo*100:.1f}% … {hi*100:.1f}%"
          + ("  — an EXACT match: at M=1 the demoted set is today's bottom-k, so duty is k/N of the"
             if hi - lo < 1e-9 else "  — near enough to read the rows against each other,"))
    print("  rankable days for every criterion alike, and nothing had to be searched for."
          if hi - lo < 1e-9 else "  and the duty column is printed so the reader checks that rather than taking it.")
    print(f"The random null had to move M from {m_days} to {m_match} to reach {d_match*100:.1f}% duty: "
          "an iid criterion has no")
    print("persistence, so it re-enters the bottom-k almost daily and the hysteresis traps it. Read the")
    print("null on GROSS Calmar only — its turnover is two orders of magnitude above any real rule, so")
    print("its netAPY is meaningless as a comparator and is printed only to show that.")


def persistence_table(k: int = REF_K, seeds: int = 1) -> None:
    """The link #43's duty-collapse could not see: criterion PERSISTENCE is what sets duty.

    At M=1 the demoted set is "today's bottom-k", so duty is k/N over the rankable days for EVERY
    criterion — an exact duty match with nothing to search for. Raise M and the criteria separate,
    and they separate strictly in the order of how often their bottom-k set changes. That is the
    whole mechanism by which a criterion reaches a duty, stated as a measurement.
    """
    panel = dgo.Panel()
    print()
    print("=" * 110)
    print(f"CRITERION PERSISTENCE at k={k} — how often the demoted SET changes, and the duty it reaches")
    print("=" * 110)
    print(f"{'criterion':16s} {'set changes on':>15s} {'duty M=1':>10s} {'duty M=20':>10s}")

    def row(name: str, sc: Scores) -> None:
        sets: List[Optional[frozenset]] = []
        for i in range(panel.n):
            rankable = [b for b in panel.books if sc[b][i] is not None]
            if len(rankable) <= k:
                sets.append(None)
                continue
            sets.append(frozenset(sorted(rankable, key=lambda b: (float(sc[b][i]), b))[:k]))
        pairs = [(sets[i - 1], sets[i]) for i in range(1, panel.n)
                 if sets[i] is not None and sets[i - 1] is not None]
        changed = sum(1 for a, b in pairs if a != b)
        print(f"{name:16s} {changed/len(pairs)*100:14.1f}% "
              f"{rule_duty(sc, k, 1)*100:9.1f}% {rule_duty(sc, k, 20)*100:9.1f}%")

    for kind, _, _ in CRITERIA:
        row(kind, panel_scores(panel, kind))
    row("random null", random_scores(panel.books, panel.n, 0))
    print("  duty at M=1 is identical across every row BY CONSTRUCTION (k/N of the rankable days):")
    print("  the M=1 rung of the ladder is therefore an EXACT duty match, obtained with no search.")


def criterion_agreement(k: int = REF_K, m_days: int = REF_M) -> None:
    """How much do these criteria actually DISAGREE? A blind criterion that demotes the same
    book-days as a return criterion is not an independent test of anything, and the overlap has
    to be printed before any conclusion is drawn from the ladder."""
    panel = dgo.Panel()
    flags = {kind: xsd.rank_demotion_flags(panel_scores(panel, kind), k, m_days)
             for kind, _, _ in CRITERIA}
    print()
    print("=" * 110)
    print(f"CRITERION AGREEMENT at k={k}, M={m_days} — Jaccard overlap of the demoted book-day sets")
    print("=" * 110)
    keys = [c[0] for c in CRITERIA]
    print(f"{'':14s}" + "".join(f"{x:>14s}" for x in keys))
    for a in keys:
        line = f"{a:14s}"
        for b in keys:
            sa = {(bk, i) for bk in panel.books for i in range(panel.n) if flags[a][bk][i]}
            sb = {(bk, i) for bk in panel.books for i in range(panel.n) if flags[b][bk][i]}
            j = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
            line += f"{j*100:13.1f}%"
        print(line)


def sweep(kind: str, ks: Sequence[int] = (1, 2, 3, 4, 5),
          ms: Sequence[int] = (1, 2, 3, 5, 10, 20, 45)) -> None:
    """Plateau or lottery ticket? ΔCalmar over the (books demoted × re-admission delay) grid."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = panel_scores(panel, kind)
    tag = {"redundancy": "#44 RCD", "volatility": "#45 XVD"}[kind]
    print()
    print("=" * 110)
    print(f"SWEEP {tag} — ΔCalmar over k (books demoted) × M (re-admission delay)")
    print("=" * 110)
    corner = "k \\ M"          # bound first: a backslash inside an f-string field is a
    print(f"{corner:>6s}" + "".join(f"{m:>8d}" for m in ms))  # SyntaxError before Python 3.12
    for k in ks:
        line = f"{k:>6d}"
        for m_days in ms:
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                panel.books, xsd.rank_demotion_flags(sc, k, m_days), panel.n))
            line += f"{m['calmar'] - base['calmar']:+8.2f}"
        print(line)


def worst_window(kind: str, k: int = REF_K, m_days: int = REF_M) -> None:
    """What the rule did inside the panel's deepest raw drawdown — where the structural limit bites."""
    panel = dgo.Panel()
    raw = panel.raw_portfolio()
    eq = cfpt.equity_path(raw)
    peak_i = trough_i = 0
    peak, worst = eq[0], 0.0
    for i, v in enumerate(eq):
        if v > peak:
            peak, peak_i = v, i
        if peak > 0 and v / peak - 1.0 < worst:
            worst, trough_i = v / peak - 1.0, i
    a, b = max(0, peak_i), min(panel.n, trough_i)
    sc = panel_scores(panel, kind)
    w = ecr.alloc_recycle(panel.books, xsd.rank_demotion_flags(sc, k, m_days), panel.n)
    # `ecr.alloc_recycle` weights are PORTFOLIO shares summing to 1.0 each day (unlike the 0..1
    # per-book overlays of `dgo`), so neither line divides by the book count.
    seg = [sum(w[bk][i] * panel.rets[bk][i] for bk in panel.books) for i in range(a, b)]
    depl = sum(w[bk][i] for bk in panel.books for i in range(a, b)) / max(1, b - a)
    print()
    print("=" * 110)
    print(f"WORST WINDOW {panel.axis[a]}..{panel.axis[min(b, panel.n-1)]} ({b-a} days, "
          f"raw {(cfpt.equity_path(raw[a:b])[-1]-1)*100:+.2f}%)")
    print("=" * 110)
    print(f"  {kind} k={k} M={m_days}: {(cfpt.equity_path(seg)[-1]-1)*100:+.2f}% "
          f"at {depl*100:.0f}% deployed — an improvement here is bought by CHOOSING books, "
          f"never by lowering exposure.")


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idea", type=int, choices=(44, 45), default=None)
    ap.add_argument("--contrast", action="store_true", help="criterion ladder + agreement only")
    ap.add_argument("--loo-key", default=None, help="configuration key for the leave-one-out pass")
    args = ap.parse_args(argv)

    print("Ideas #44 RCD / #45 XVD — ADVISORY, OUTSIDE_RISKPOLICY, evidence L0 (backtest).")
    print("Capital does not move. The live track and RiskPolicy v1.0 are not touched.")

    if args.contrast:
        criterion_ladder(REF_K, 1)        # the EXACT duty match — see persistence_table
        criterion_ladder(REF_K, REF_M)
        persistence_table()
        criterion_agreement()
        return 0

    if args.idea in (None, 44):
        idea44_rcd()
        sweep("redundancy")
        worst_window("redundancy")
    if args.idea in (None, 45):
        idea45_xvd()
        sweep("volatility")
        worst_window("volatility")
    if args.idea is None:
        criterion_ladder(REF_K, 1)
        criterion_ladder(REF_K, REF_M)
        persistence_table()
        criterion_agreement()
        ecr.train_test(idea44_rcd, [f"RCD k={REF_K} M={REF_M}", f"#40 XSD drift k={REF_K} M={REF_M}",
                                    "CONTROL top-k flip k=2 M=20", "CONTROL static-matched"])
        ecr.train_test(lambda **kw: idea45_xvd(ks=(1, 2), ms=(1, 20), **kw),
                       ["XVD k=1 M=1", f"XVD k={REF_K} M={REF_M}", "CONTROL static twin of k=1 M=1"])
        # The flipped redundancy rule posts a big number and FAILS leave-one-out; #42's rule is
        # that such a row is reported as a failed candidate, never quietly dropped.
        ecr.leave_one_out(idea44_rcd, args.loo_key or "CONTROL top-k flip k=2 M=20")
        ecr.leave_one_out(lambda **kw: idea45_xvd(ks=(1, 2), ms=(1, 20), **kw), "XVD k=1 M=1")
        panel = dgo.Panel()
        for kind, k, m_days in (("redundancy", REF_K, REF_M), ("volatility", 1, 1)):
            fl = xsd.rank_demotion_flags(panel_scores(panel, kind), k, m_days)
            tag = f"{'#44 RCD' if kind == 'redundancy' else '#45 XVD'} k={k} M={m_days}"
            ecr.information_controls(panel, fl, tag)
            ecr.weight_decomposition(panel, fl, tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
