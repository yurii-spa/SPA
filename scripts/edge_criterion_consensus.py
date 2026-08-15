#!/usr/bin/env python3
"""Edge R&D — registry ideas #56 (XCV) and #57 (SST): WHO decides, and HOW LATE may they decide.

PROVENANCE — WHY THE NUMBERS IN THIS FILE MOVED
  Written 2026-08-13 as ideas #49/#50 and never pushed: the session died before delivery and the
  file sat in a /tmp worktree for two days. In those two days OTHER sessions claimed #49 (RDT,
  rebalance drift tax) and #50 (NTB, no-trade band). Raised and renumbered to the next free slots
  by cycle #249; nothing but the labels changed, and every number below was RE-MEASURED by that
  cycle rather than copied from the dead session's report.

  #57 SST is NOT independent of the registry any more either: entry #51 SLT (2026-08-14) asks the
  same question with different code. Its seven shared lag cells and this file's agree to the last
  digit — that agreement is now the point of #57, together with the d=30/60 tail #51 never swept.

WHERE THIS COMES FROM
  Entries #40–#45 are six criteria answering one question — *which book leaves the portfolio* —
  and every one of them was measured ALONE, against raw and against the same controls. Nobody has
  ever asked the two questions that only exist once you have six of them:

    1. What happens when they VOTE?  A demotion rule is a classifier, and the registry now owns
       four classifiers built on one machinery (`erd.CRITERIA`: drift #40, bad-day return #41,
       volatility #45, redundancy #44). If their errors are independent, a consensus should demote
       fewer books more accurately than any single criterion. If their errors are the SAME errors,
       the consensus is the single criterion with extra words — and that answer retires five
       registry entries into one, which is worth as much as an edge.
    2. How STALE may the vote be?  Every number in #37–#48 assumes the rule acts on today's data
       today. Production does not work that way and we have the measurements to prove it: this
       project's own fleet has carried agents executing week-old code (#177/#178), an `apiserver`
       23 days stale and a `familyfund` 38 days stale (#184), and scheduled artifacts that ran
       overdue for hours. **The registry has never priced a single day of that.** A rule whose
       edge dies at d=2 cannot be deployed on an agent that is routinely three days late, and no
       amount of Calmar in a d=0 backtest changes that.

  Neither question invents a criterion, a panel or an allocator. Both are pure re-use.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #56 — XCV: Cross-Criterion Vote  ("judge a book by a jury, not by one witness")
──────────────────────────────────────────────────────────────────────────────────────────────
      criteria, k, M, L, panel, costs : #40/#41/#44/#45 and #38's allocator, byte-for-byte
      votes_b(t) = #{criteria that rank b in their own bottom-k today}   ← the only new object
      demote      : votes_b(t) >= j                                      ← j is the only new knob
      re-admit    : votes_b(t) < j on M consecutive days  (#39's state machine, unchanged)

  The endpoints are exact, not approximate, and the test-suite pins them:
      one criterion, j=1  → the flags ARE `xsd.rank_demotion_flags` for that criterion (i.e. #40)
      four criteria, j=1  → the UNION of the four bottom-k sets   (superset of every single rule)
      four criteria, j=4  → their INTERSECTION                    (subset of every single rule)
  Everything between is a jury the registry has never empanelled. Three outcomes, all publishable
  and all written down BEFORE the numbers:

    A. an interior j beats every single criterion  → the criteria make INDEPENDENT errors and the
       registry has been throwing away information by picking a winner instead of pooling them.
    B. the vote lands between the singles, monotone in j → the criteria are collinear; the jury
       measures the same witness four times. Then #41/#44/#45 add nothing to #40 and the family's
       real dimension is one, which closes a branch by argument instead of by more sweeps.
    C. the vote is worse than every single → pooling injects the WORST criterion's noise into the
       best one's decisions; a rule of this family must be picked, not averaged.

  Section 1 of the report measures the collinearity DIRECTLY (pairwise Jaccard of the bottom-k
  book-days and pairwise Spearman of the raw scores), so whichever outcome lands, the report says
  WHY rather than only WHAT.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #57 — SST: Signal Staleness Tolerance  ("how many days late may the agent be")
──────────────────────────────────────────────────────────────────────────────────────────────
      rule           : the registry leader, #40 XSD drift, k=2 — untouched
      flags_d(t)     = flags(t − d)          ← act on the decision the rule made d days ago
      d              : 0, 1, 2, 3, 5, 7, 10, 14, 20, 30, 60 days of delivery latency
      M              : 1, 5, 10, 20, 45      ← the rule's own stickiness, swept WITH d

  This is NOT `ecr.shifted_flags`. That control rotates the flag path CIRCULARLY in both
  directions and is deliberately non-causal — it can never be run live. A lag is one-sided and
  strictly backward: every flag it uses was computable at the time it is used, so every cell of
  this grid is an implementable configuration. The first d days carry no decision yet and are
  reported as NOT demoted — the conservative default (no action), named here rather than hidden.

  The hypothesis is specific, not decorative: M is a re-admission delay, so a rule with M=20
  already holds each decision for twenty days. If stickiness buys latency tolerance, the d-axis
  should be nearly flat for d << M and steep at M=1. That would mean the leader's real
  operational requirement is far weaker than "run me daily", and it would be the first number
  this project has for the question its own fleet keeps failing: *how late is too late?*

  The complementary outcome is just as useful: if ΔCalmar collapses at d=1–2 even with M=20, then
  every rule of this family is undeployable on a fleet with the staleness we have MEASURED, and
  that is a delivery finding, not a market one.

HONESTY / SCOPE (registry rules — non-negotiable)
  • Strictly causal everywhere: scores for day i use returns through i−1 (inherited), and the lag
    only ever moves information BACKWARD. Both pinned in both directions by the test-suite.
  • Panel, allocator, cost model (48 bp per one-way leg of turnover = #10's 96 bp round trip),
    L=60, k, M and the train/test split are IMPORTED from #32/#38/#39/#40, never re-derived.
    Books are regenerated nightly, so numbers reproduce only against the panel files of the run
    date (2026-08-13: 10 books, 852 days, raw 17.94% / −5.44% / Calmar 3.30).
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0 nor the kill-switch thresholds. Evidence L0 (backtest on real feed
    history, NOT live). IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_criterion_consensus.py               # everything
    python3 scripts/edge_criterion_consensus.py --idea 56     # XCV only
    python3 scripts/edge_criterion_consensus.py --idea 57     # SST only
    python3 scripts/edge_criterion_consensus.py --agreement   # the criterion-collinearity matrix
    python3 scripts/edge_criterion_consensus.py --grid        # the (M × d) latency grid only
    python3 scripts/edge_criterion_consensus.py --controls    # permutation / rotation / LOO / OOS
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, controls #38/#39)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40/#41)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K, REF_M = 2, 20             # #40's reference cell, so every row is like-for-like
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap (RiskPolicy v1.0)
EPS = ecr.EPS

KINDS: Tuple[str, ...] = tuple(kind for kind, _, _ in erd.CRITERIA)   # drift, downside, vol, redund
LAGS: Tuple[int, ...] = (0, 1, 2, 3, 5, 7, 10, 14, 20, 30, 60)
MS: Tuple[int, ...] = (1, 5, 10, 20, 45)


# ═══════════════════════════ #56 — the jury ═══════════════════════════
def bottom_membership(scores: "erd.Scores", k: int,
                      worst_first: bool = True) -> Tuple[Dict[str, List[bool]], List[bool]]:
    """(bottom-k membership per book-day, "this criterion could rank at all today").

    Fail-CLOSED exactly where `xsd.rank_demotion_flags` is: on a day with k or fewer rankable
    books there is no meaningful "worst k", so the criterion ABSTAINS (its `ok` is False and it
    casts no vote) rather than demoting everybody. A book whose score is None is not rankable and
    can never enter the bottom-k. Ties break by book name so the report is reproducible.

    `worst_first=False` is the sign-flipped CONTROL (vote for the BEST-ranked books). It is never
    a proposed rule; it exists so that "the jury carries information" is a measured claim.
    """
    if k < 1:
        raise ValueError("k must be >= 1 — a criterion that nominates nobody is not a criterion")
    books = sorted(scores)
    if k >= len(books):
        raise ValueError(f"k={k} with {len(books)} books would nominate the whole panel — refused")
    n = len(scores[books[0]]) if books else 0
    sign = 1.0 if worst_first else -1.0
    member: Dict[str, List[bool]] = {b: [False] * n for b in books}
    ok: List[bool] = [False] * n
    for i in range(n):
        rankable = [b for b in books if scores[b][i] is not None]
        if len(rankable) <= k:
            continue                       # abstains: no rank ⇒ no vote, in either direction
        ok[i] = True
        ordered = sorted(rankable, key=lambda b: (sign * float(scores[b][i]), b))
        for b in ordered[:k]:
            member[b][i] = True
    return member, ok


def vote_counts(panel: "dgo.Panel", kinds: Sequence[str], k: int,
                lookback: int = LOOKBACK, worst_first: bool = True
                ) -> Tuple[Dict[str, List[int]], List[int], Dict[str, Dict[str, List[bool]]]]:
    """(votes per book-day, number of criteria that could vote that day, per-criterion membership).

    `voters[i] < len(kinds)` means some criterion abstained; the vote threshold j is then read
    against the criteria that ACTUALLY voted, and `consensus_flags` freezes the state whenever
    fewer than j criteria could vote at all. A jury that cannot reach quorum does not convict.
    """
    if not kinds:
        raise ValueError("an empty jury is not a rule — pass at least one criterion")
    member: Dict[str, Dict[str, List[bool]]] = {}
    ok: Dict[str, List[bool]] = {}
    for kind in kinds:
        m, o = bottom_membership(erd.panel_scores(panel, kind, lookback), k, worst_first)
        member[kind], ok[kind] = m, o
    n = panel.n
    voters = [sum(1 for kind in kinds if ok[kind][i]) for i in range(n)]
    votes = {b: [sum(1 for kind in kinds if ok[kind][i] and member[kind][b][i]) for i in range(n)]
             for b in panel.books}
    return votes, voters, member


def consensus_flags(votes: Dict[str, Sequence[int]], voters: Sequence[int],
                    j: int, m_days: int = 1) -> Dict[str, List[bool]]:
    """True on days the book is DEMOTED because at least `j` criteria nominated it.

        demote   : votes_b(t) >= j
        re-admit : votes_b(t) < j on `m_days` consecutive days

    The state machine is #39's, reached through #40's substitution and one more: "in the bottom-k"
    becomes "nominated by at least j of the jury". With one criterion and j=1 the two are the SAME
    FUNCTION, and the test-suite pins that byte-for-byte — which is what makes every row of this
    entry comparable with #40's numbers rather than merely similar to them.

    Fail-CLOSED: on a day when fewer than j criteria could vote, NOBODY changes state. Convicting
    on an inquorate jury, or acquitting on one, would both be exposure decisions in disguise.
    """
    if j < 1:
        raise ValueError("j must be >= 1 — a jury that convicts on zero votes is not a jury")
    if m_days < 1:
        raise ValueError("m_days must be >= 1 — re-admission with no evidence is not a rule")
    books = sorted(votes)
    n = len(voters)
    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}
    for i in range(n):
        if voters[i] < j:
            for b in books:                # inquorate: state frozen, no evidence either way
                out[b].append(demoted[b])
            continue
        for b in books:
            hit = votes[b][i] >= j
            good_run[b] = 0 if hit else good_run[b] + 1
            if demoted[b]:
                if good_run[b] >= m_days:
                    demoted[b] = False
            elif hit:
                demoted[b] = True
            out[b].append(demoted[b])
    return out


# ═══════════════════════════ #56 — collinearity diagnostics ═══════════════════════════
def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Rank correlation over one cross-section. None when a side is constant (rank is undefined)."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(v: Sequence[float]) -> Optional[List[float]]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                r[order[t]] = avg
            i = j + 1
        return None if len(set(r)) == 1 else r

    rx, ry = ranks(xs), ranks(ys)
    if rx is None or ry is None:
        return None
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx <= EPS or dy <= EPS:
        return None
    return num / (dx * dy)


def criterion_agreement(panel: "dgo.Panel", k: int = REF_K, kinds: Sequence[str] = KINDS,
                        lookback: int = LOOKBACK) -> List[Tuple[str, str, float, Optional[float]]]:
    """Pairwise (Jaccard of bottom-k book-days, mean daily Spearman of the raw scores).

    Jaccard says how often two criteria NOMINATE the same book on the same day — the thing the
    vote actually pools. Spearman says whether they order the whole cross-section alike, which is
    the deeper statement: two criteria can disagree at the bottom edge while ranking identically.
    Both are reported because either one alone can flatter a jury.
    """
    scores = {kind: erd.panel_scores(panel, kind, lookback) for kind in kinds}
    member = {kind: bottom_membership(scores[kind], k)[0] for kind in kinds}
    out: List[Tuple[str, str, float, Optional[float]]] = []
    for a_i in range(len(kinds)):
        for b_i in range(a_i + 1, len(kinds)):
            a, b = kinds[a_i], kinds[b_i]
            inter = union = 0
            for bk in panel.books:
                for i in range(panel.n):
                    x, y = member[a][bk][i], member[b][bk][i]
                    inter += 1 if (x and y) else 0
                    union += 1 if (x or y) else 0
            jac = inter / union if union else 0.0
            rhos: List[float] = []
            for i in range(panel.n):
                # Only the books BOTH criteria could score that day. `redundancy` is undefined for
                # a book whose window is degenerate and is therefore missing on most days for half
                # the panel (a fact of the criterion, measured in section 1's footer); demanding a
                # full cross-section would silently report "n/a" for every pair it belongs to.
                common = [bk for bk in panel.books
                          if scores[a][bk][i] is not None and scores[b][bk][i] is not None]
                if len(common) < 3:
                    continue
                r = _spearman([float(scores[a][bk][i]) for bk in common],
                              [float(scores[b][bk][i]) for bk in common])
                if r is not None:
                    rhos.append(r)
            out.append((a, b, jac, (sum(rhos) / len(rhos)) if rhos else None))
    return out


# ═══════════════════════════ #57 — the delivery lag ═══════════════════════════
def lagged_flags(flags: Dict[str, Sequence[bool]], d: int) -> Dict[str, List[bool]]:
    """Act on the decision the rule made `d` days ago — one-sided, backward, implementable.

    This is the operational twin of `ecr.shifted_flags` and its exact opposite in kind: the
    control ROTATES a path circularly (information from the future re-enters the past and the row
    can never be run live), while a lag only ever DELAYS. The first `d` days precede any decision
    and are reported as NOT demoted, i.e. fully deployed — the no-action default, stated because
    it is the one place the lag row is optimistic relative to the rule it delays.
    """
    if d < 0:
        raise ValueError("d must be >= 0 — a negative lag is look-ahead, not latency")
    if d == 0:
        return {b: list(v) for b, v in flags.items()}
    return {b: [False] * d + list(v)[:-d] for b, v in flags.items()}


def lagged_scores(scores: "erd.Scores", d: int) -> "erd.Scores":
    """The same delay applied to the INPUT instead of to the decision (`None` before day d).

    Reported alongside `lagged_flags` because "our data is stale" and "our agent is late" are
    different sentences about the same portfolio, and the report should not assume they are the
    same number. On this machinery they very nearly are, and the test-suite pins the residual
    difference to the state-machine boundary rather than leaving it as a claim.
    """
    if d < 0:
        raise ValueError("d must be >= 0 — a negative lag is look-ahead, not latency")
    if d == 0:
        return {b: list(v) for b, v in scores.items()}
    return {b: [None] * d + list(v)[:-d] for b, v in scores.items()}


# ═══════════════════════════ report bodies ═══════════════════════════
def _xcv_rows(panel: "dgo.Panel", k: int, m_days: int, kinds: Sequence[str],
              cap: Optional[float] = None) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """One row per single criterion, one per jury size j, plus the controls of this family."""
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    for kind, title, _ in erd.CRITERIA:
        if kind not in kinds:
            continue
        fl = xsd.rank_demotion_flags(erd.panel_scores(panel, kind, LOOKBACK), k, m_days)
        rows.append((f"single {title}", ecr.alloc_recycle(books, fl, n, cap=cap), 0.0))

    votes, voters, _ = vote_counts(panel, kinds, k)
    for j in range(1, len(kinds) + 1):
        tag = "UNION" if j == 1 else ("UNANIMOUS" if j == len(kinds) else "")
        label = f"XCV j={j}/{len(kinds)} k={k} M={m_days}" + (f" [{tag}]" if tag else "")
        rows.append((label, ecr.alloc_recycle(books, consensus_flags(votes, voters, j, m_days),
                                              n, cap=cap), 0.0))

    ref = consensus_flags(votes, voters, 2, m_days)
    up_votes, up_voters, _ = vote_counts(panel, kinds, k, worst_first=False)
    rows.append(("  CONTROL jury flip j=2 (best-k)",
                 ecr.alloc_recycle(books, consensus_flags(up_votes, up_voters, 2, m_days),
                                   n, cap=cap), 0.0))
    rows.append(("  CONTROL static twin of j=2",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, ref, n, cap=cap)), 0.0))
    rows.append((f"  under {int(CONC_CAP*100)}% per-name cap j=2",
                 ecr.alloc_recycle(books, ref, n, cap=CONC_CAP), 0.0))
    return rows


def idea56_xcv(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, m_days: int = REF_M,
               kinds: Sequence[str] = KINDS) -> Dict[str, Dict[str, float]]:
    """Idea #56 — do four demotion criteria make INDEPENDENT errors, or the same error?"""
    panel = dgo.Panel(subset, start, end)
    rows = _xcv_rows(panel, k, m_days, kinds)
    out = xsd._report(f"IDEA #56 XCV — cross-criterion vote [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        votes, voters, _ = vote_counts(panel, kinds, k)
        cells = len(panel.books) * panel.n
        hist = [sum(1 for b in panel.books for i in range(panel.n) if votes[b][i] == v)
                for v in range(len(kinds) + 1)]
        print("-" * 110)
        print("vote histogram over book-days: " + "  ".join(
            f"{v} votes {hist[v]} ({hist[v]/cells*100:.1f}%)" for v in range(len(kinds) + 1)))
        inquorate = sum(1 for x in voters if x < len(kinds))
        print(f"days on which at least one criterion abstained: {inquorate}/{panel.n} "
              f"(state frozen there — fail-CLOSED, never a silent demotion)")
    return out


def _sst_rows(panel: "dgo.Panel", k: int, m_days: int, lags: Sequence[int],
              kind: str = "drift") -> List[Tuple[str, Dict[str, List[float]], float]]:
    sc = erd.panel_scores(panel, kind, LOOKBACK)
    flags = xsd.rank_demotion_flags(sc, k, m_days)
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []
    for d in lags:
        tag = " [#40 XSD verbatim]" if d == 0 else ""
        rows.append((f"SST d={d:<3d} k={k} M={m_days}{tag}",
                     ecr.alloc_recycle(books, lagged_flags(flags, d), n), 0.0))
    return rows


def idea57_sst(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, m_days: int = REF_M,
               lags: Sequence[int] = LAGS) -> Dict[str, Dict[str, float]]:
    """Idea #57 — how many days late may the agent be before the leader's edge is gone?"""
    panel = dgo.Panel(subset, start, end)
    rows = _sst_rows(panel, k, m_days, lags)
    out = xsd._report(f"IDEA #57 SST — signal staleness tolerance [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        base = ecr._raw_metrics(panel)
        d0 = out[f"SST d={0:<3d} k={k} M={m_days} [#40 XSD verbatim]".strip()]["calmar"] \
            - base["calmar"]
        print("-" * 110)
        budget = None
        for d in lags:
            key = f"SST d={d:<3d} k={k} M={m_days}" + (" [#40 XSD verbatim]" if d == 0 else "")
            delta = out[key.strip()]["calmar"] - base["calmar"]
            if d0 > 0 and delta >= 0.5 * d0:
                budget = d
        print(f"latency budget at M={m_days}: ΔCalmar stays above HALF of its d=0 value "
              f"({d0:.2f}) up to d={budget} days"
              if budget is not None else
              f"latency budget at M={m_days}: UNDEFINED — ΔCalmar at d=0 is {d0:.2f}")
        print("the first d days carry no decision and are reported DEPLOYED (no-action default)")
    return out


# ═══════════════════════════ sweeps ═══════════════════════════
def agreement_report(k: int = REF_K, kinds: Sequence[str] = KINDS) -> None:
    panel = dgo.Panel()
    print()
    print("=" * 110)
    print(f"SECTION 1 — do the four criteria of #40/#41/#44/#45 SAY THE SAME THING?  (k={k})")
    print("=" * 110)
    print(f"{'criterion A':14s} {'criterion B':14s} {'Jaccard(bottom-k)':>19s} {'mean Spearman':>15s}")
    for a, b, jac, rho in criterion_agreement(panel, k, kinds):
        print(f"{a:14s} {b:14s} {jac*100:18.1f}% "
              f"{('%15.3f' % rho) if rho is not None else '            n/a'}")
    print()
    print("Jaccard = share of book-days nominated by BOTH out of those nominated by EITHER.")
    print("Spearman is taken over the books BOTH criteria could score that day, not the full ten:")
    for kind in kinds:
        sc = erd.panel_scores(panel, kind, LOOKBACK)
        miss = sum(1 for b in panel.books for i in range(panel.n) if sc[b][i] is None)
        print(f"  {kind:12s} unscored book-days: {miss:5d} / {len(panel.books)*panel.n} "
              f"({miss/(len(panel.books)*panel.n)*100:.1f}%)")
    print("A jury of collinear witnesses cannot outvote its own best member — read section 2 with")
    print("this table in hand, not after it.")


def latency_grid(k: int = REF_K, ms: Sequence[int] = MS, lags: Sequence[int] = LAGS,
                 kind: str = "drift") -> None:
    """ΔCalmar over (rule stickiness M × delivery lag d) — the operational deployability map."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = erd.panel_scores(panel, kind, LOOKBACK)
    print()
    print("=" * 110)
    print(f"SECTION 2 — LATENCY GRID: ΔCalmar vs raw ({base['calmar']:.2f}), k={k}, criterion={kind}")
    print("=" * 110)
    print("M \\ d " + "".join(f"{d:>8d}" for d in lags))
    for m_days in ms:
        flags = xsd.rank_demotion_flags(sc, k, m_days)
        cells = []
        for d in lags:
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                panel.books, lagged_flags(flags, d), panel.n))
            cells.append(m["calmar"] - base["calmar"])
        print(f"{m_days:5d} " + "".join(f"{c:+8.2f}" for c in cells))
    print()
    print("netAPY over the same grid (after the #10 turnover bill):")
    print("M \\ d " + "".join(f"{d:>8d}" for d in lags))
    for m_days in ms:
        flags = xsd.rank_demotion_flags(sc, k, m_days)
        cells = []
        for d in lags:
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                panel.books, lagged_flags(flags, d), panel.n))
            cells.append(m["net_apy_after_cost"] * 100)
        print(f"{m_days:5d} " + "".join(f"{c:8.2f}" for c in cells))
    print()
    print(latency_stability.__doc__.splitlines()[0])
    print(f"{'M':>5s} {'d=0':>8s} {'mean':>8s} {'sd':>7s} {'mean|step|':>11s} {'min':>8s}")
    for m_days, s in latency_stability(panel, k, ms, lags, kind).items():
        print(f"{m_days:5d} {s['d0']:+8.2f} {s['mean']:+8.2f} {s['sd']:7.2f} "
              f"{s['mean_step']:11.2f} {s['min']:+8.2f}")
    print("Two cells with the SAME d=0 number are not the same configuration: one of them survives")
    print("being a week late and the other does not. A jagged d-axis is the cheapest overfit")
    print("detector this registry has — the lag is not a parameter of the rule, so a number that")
    print("moves under it was never a property of the rule.")


def latency_stability(panel: "dgo.Panel", k: int = REF_K, ms: Sequence[int] = MS,
                      lags: Sequence[int] = LAGS, kind: str = "drift"
                      ) -> Dict[int, Dict[str, float]]:
    """STABILITY of ΔCalmar along the lag axis — a configuration that only works on time is luck.

    A delay is not a knob of the rule: no re-tuning, no new information, nothing the rule can
    exploit. So the edge a rule really owns is the one that survives the whole d-axis, and the
    jitter along it (`mean|step|`) measures how much of a d=0 headline was alignment luck.
    """
    base = ecr._raw_metrics(panel)
    sc = erd.panel_scores(panel, kind, LOOKBACK)
    out: Dict[int, Dict[str, float]] = {}
    for m_days in ms:
        flags = xsd.rank_demotion_flags(sc, k, m_days)
        vals = [ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            panel.books, lagged_flags(flags, d), panel.n))["calmar"] - base["calmar"]
            for d in lags]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        steps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
        out[m_days] = {"d0": vals[0], "mean": mean, "sd": sd, "min": min(vals),
                       "mean_step": (sum(steps) / len(steps)) if steps else 0.0}
    return out


def subjury_report(k: int = REF_K, ms: Sequence[int] = (1, 20)) -> None:
    """Leave-one-juror-out: is the jury held back by its worst member, or by pooling itself?

    This is the control that decides #56. If the jury only loses because #44 redundancy (its own
    registry verdict: ❌ return-blind, harmful) is on it, then a curated jury is still a live
    proposal. If the best jury WITHOUT that juror is still behind the best single criterion, then
    the cost is pooling, and the branch closes for every jury anyone could assemble here.
    """
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    best_single = max(
        ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            panel.books,
            xsd.rank_demotion_flags(erd.panel_scores(panel, kind, LOOKBACK), k, REF_M),
            panel.n))["calmar"] - base["calmar"]
        for kind in KINDS)
    print()
    print("=" * 110)
    print(f"SECTION 4 — SUB-JURIES: does dropping a juror rescue the vote?  (k={k}; the best single "
          f"criterion at M={REF_M} scores ΔCalmar {best_single:+.2f})")
    print("=" * 110)
    juries: Tuple[Tuple[str, ...], ...] = (
        KINDS,
        ("drift", "downside", "volatility"),          # minus the return-blind juror (#44)
        ("drift", "downside"),
        ("drift", "volatility"),
        ("downside", "volatility", "redundancy"),     # minus the registry's own winner (#40)
    )
    print(f"{'jury':44s} {'M':>3s} " + "".join(f"{'j=%d' % j:>16s}" for j in range(1, 5)))
    for kinds in juries:
        for m_days in ms:
            votes, voters, _ = vote_counts(panel, kinds, k)
            cells = []
            for j in range(1, 5):
                if j > len(kinds):
                    cells.append(f"{'—':>16s}")
                    continue
                m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                    panel.books, consensus_flags(votes, voters, j, m_days), panel.n))
                cells.append(f"{m['calmar']-base['calmar']:+7.2f}/{m['net_apy_after_cost']*100:6.2f}%")
            print(f"{'+'.join(kinds):44s} {m_days:3d} " + "".join(cells))
    print()
    print("cells are ΔCalmar / netAPY after the #10 turnover bill. A jury beats the branch only if")
    print(f"some cell clears ΔCalmar {best_single:+.2f} AND the single criterion's netAPY.")


def vote_grid(ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20),
              kinds: Sequence[str] = KINDS) -> None:
    """ΔCalmar over (k × j) at two stickinesses — plateau or lottery ticket for the jury."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"SECTION 3 — JURY GRID: ΔCalmar vs raw ({base['calmar']:.2f}) over (k × j)")
    print("=" * 110)
    for m_days in ms:
        print(f"\nM={m_days}")
        print("k \\ j " + "".join(f"{j:>8d}" for j in range(1, len(kinds) + 1)))
        for k in ks:
            votes, voters, _ = vote_counts(panel, kinds, k)
            cells = []
            for j in range(1, len(kinds) + 1):
                m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                    panel.books, consensus_flags(votes, voters, j, m_days), panel.n))
                cells.append(m["calmar"] - base["calmar"])
            print(f"{k:5d} " + "".join(f"{c:+8.2f}" for c in cells))


def controls() -> None:
    panel = dgo.Panel()
    votes, voters, _ = vote_counts(panel, KINDS, REF_K)
    ecr.information_controls(panel, consensus_flags(votes, voters, 2, REF_M),
                             f"XCV j=2/{len(KINDS)} k={REF_K} M={REF_M}")
    sc = erd.panel_scores(panel, "drift", LOOKBACK)
    ecr.information_controls(panel, lagged_flags(xsd.rank_demotion_flags(sc, REF_K, REF_M), 5),
                             f"SST d=5 k={REF_K} M={REF_M}")
    ecr.leave_one_out(idea56_xcv, f"XCV j=2/{len(KINDS)} k={REF_K} M={REF_M}")
    ecr.train_test(idea56_xcv, [f"single {t}" for _, t, _ in erd.CRITERIA]
                   + [f"XCV j={j}/{len(KINDS)} k={REF_K} M={REF_M}"
                      + (" [UNION]" if j == 1 else (" [UNANIMOUS]" if j == len(KINDS) else ""))
                      for j in range(1, len(KINDS) + 1)])
    ecr.train_test(idea57_sst, [(f"SST d={d:<3d} k={REF_K} M={REF_M}"
                                 + (" [#40 XSD verbatim]" if d == 0 else "")).strip()
                                for d in (0, 1, 3, 7, 10, 14, 20, 30)])


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--idea", type=int, choices=(56, 57), default=None)
    ap.add_argument("--agreement", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--controls", action="store_true")
    a = ap.parse_args(list(argv))

    only = a.agreement or a.grid or a.controls
    if a.agreement:
        agreement_report()
    if a.grid:
        latency_grid()
        vote_grid()
        subjury_report()
    if a.controls:
        controls()
    if only:
        return 0

    if a.idea in (None, 56):
        agreement_report()
        idea56_xcv()
        vote_grid()
        subjury_report()
    if a.idea in (None, 57):
        idea57_sst()
        latency_grid()
    if a.idea is None:
        controls()
    print()
    print("ADVISORY / OUTSIDE_RISKPOLICY — evidence L0 (backtest, not live). No capital moves, "
          "no state is written, RiskPolicy v1.0 and the kill-switch thresholds are untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
