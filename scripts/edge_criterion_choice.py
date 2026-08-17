#!/usr/bin/env python3
"""Edge R&D — registry ideas #58 (OCS) and #59 (OIB): WHICH criterion, and HOW MUCH IS THERE AT ALL.

WHERE THIS COMES FROM
  Entry #56 XCV empanelled the registry's four demotion criteria as a jury and closed the branch
  with a sentence that is an instruction, not a result: *"a rule of this family must be PICKED,
  not averaged."* It then spent its last section undermining the only pick anybody has made — on
  the unseen half the four criteria converge (#41 +11.15, #45 +11.06, jury +11.05, #40 +6.32),
  so the published order #40 > #41 > #45 lives in TRAIN. Both halves of that finding leave the
  same question standing, and neither answers it:

      if the family's rule has to be CHOSEN, can the choice be made CAUSALLY —
      by an agent that sees only the past — or is "choose #40" simply a fit to TRAIN
      wearing the clothes of a decision?

  That is idea #58. It is not the jury: a jury pools four opinions into one verdict every day,
  a selector BACKS ONE of the four and can be wrong about which. #56 measured pooling and
  found it costs return; nobody has measured picking.

  And there is a second question that only becomes askable after twenty entries of the same
  shape (#35–#57), all of them ranking books and demoting the bottom-k:

      how much is there to win on this panel AT ALL, and what fraction of it does
      the registry's own leader already take?

  That is idea #59. Every entry of this family reports its ΔCalmar against raw and against a
  control that destroys information. None reports it against the CEILING — the same rule shape
  run on tomorrow's returns. Without that number "+5.03" is unreadable: it could be most of what
  is available (branch exhausted, stop inventing criteria) or a tenth of it (the criteria are the
  bottleneck, keep going). Twenty entries have been written without knowing which.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #58 — OCS: Online Criterion Selection  ("back the criterion that has been winning")
──────────────────────────────────────────────────────────────────────────────────────────────
      criteria, k, M, L, panel, allocator, costs : #40/#41/#44/#45 and #38, byte-for-byte
      r_c(t)      = daily portfolio return of criterion c's own recycled allocation
      lead_c(t)   = mean r_c over [t−E, t−1]                  ← strictly causal, E is knob one
      leader(t)   = argmax_c lead_c(t), ties by criterion name
      switch      : only after the challenger has topped the ranking H days running (knob two)
      warm-up     : t < E ⇒ NO criterion is backed ⇒ raw equal weight (no demotion, deployed)

  Two knobs, both named, both swept and printed as a full grid rather than as a winner. The
  warm-up default is the conservative one and it is stated because it is the one place the
  selector is optimistic: not choosing means not demoting, and not demoting is what raw does.

  Three outcomes, written down BEFORE the numbers:

    A. some (E, H) beats the best single criterion AND the anti-selector (back the trailing
       LOSER) is symmetrically bad ⇒ criterion leadership persists, the choice is makeable
       causally, and #56's instruction has an implementation.
    B. the selector lands among the singles, close to their average, and the anti-selector lands
       there too ⇒ leadership does NOT persist; "choose #40" cannot be made causally, and what
       the registry published as a ranking of criteria is a ranking of one sample.
    C. the selector is worse than every single ⇒ chasing the leader is a turnover tax on noise,
       which is outcome B plus a bill.

  Section 2 measures persistence DIRECTLY instead of inferring it from the result: how often
  today's leader is tomorrow's, and how often the trailing-E leader is the forward-E leader,
  against the 1/4 a coin would give. Whichever outcome lands, the report says WHY.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #59 — OIB: Oracle Information Bound  ("how much is in this panel, and how much do we take")
──────────────────────────────────────────────────────────────────────────────────────────────
      rule shape  : bottom-k demotion + #39 state machine + #38 recycling — UNCHANGED
      oracle(h)   : score_b(t) = mean of b's returns over [t, t+h)      ← LOOK-AHEAD, never live
      anti-oracle : the same scores, demoting the forward BEST          ← the floor
      chance floor: `ecr.permuted_flags` of the real rule, 20 seeds     ← duty- and turnover-matched
      capture     = (Δ_rule − Δ_chance) / (Δ_oracle − Δ_chance)

  Only the SCORES change; k, M, the state machine, the allocator, the cap and the cost model are
  the same objects the published rows used, so the ceiling is the ceiling OF THIS RULE SHAPE —
  not of all possible rules, and the entry says so wherever it prints a capture ratio.

  The horizon h is swept (1, 5, 20, 60 days) because "perfect foresight" is not one number: a
  rule with M=20 stickiness cannot act on one-day foresight even if it had it, and an oracle that
  sees a quarter ahead is answering a different question than one that sees tomorrow.

  There is a trap in this measurement and it is #54's: a book whose feed died prints exactly 0.0
  forever, so its FORWARD mean is exactly 0.0, which ranks above every book that is genuinely
  losing. The oracle therefore parks in dead books exactly as the causal rules do — the ceiling
  is contaminated by the same accidental cash sleeve as the floor. That is not a flaw to be
  hidden in a caveat: it is measured by re-running the whole bound on the six LIVE books
  (`ets.live_books`, density ≥ 50 %) and printing both.

HONESTY / SCOPE (registry rules — non-negotiable)
  • The oracle is LOOK-AHEAD BY CONSTRUCTION and is never proposed as a rule. Every row that uses
    it is labelled `[LOOK-AHEAD]` in the table, and the test-suite pins that the causal side of
    this file never reads a future return (positive control: mutate tomorrow, assert today).
  • Panel, allocator, cost model (48 bp per one-way leg of turnover = #10's 96 bp round trip),
    L=60, k, M and the train/test split are IMPORTED from #32/#38/#39/#40, never re-derived.
    Books are regenerated nightly, so numbers reproduce only against the panel of the run date.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0 nor the kill-switch thresholds. Evidence L0 (backtest on real feed
    history, NOT live). IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_criterion_choice.py                 # everything
    python3 scripts/edge_criterion_choice.py --idea 58       # OCS only
    python3 scripts/edge_criterion_choice.py --idea 59       # OIB only
    python3 scripts/edge_criterion_choice.py --persistence   # leadership persistence only
    python3 scripts/edge_criterion_choice.py --grid          # the (E × H) selector grid only
    python3 scripts/edge_criterion_choice.py --live-only     # both ideas on the 6 live books
    python3 scripts/edge_criterion_choice.py --controls      # permutation / rotation / TRAIN→TEST
"""
# LLM_FORBIDDEN
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
import edge_event_time_scoring as ets           # noqa: E402  (live/dead book census of #54)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K, REF_M = 2, 20             # #40's reference cell, so every row is like-for-like
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap (RiskPolicy v1.0)
EPS = ecr.EPS

KINDS: Tuple[str, ...] = tuple(kind for kind, _, _ in erd.CRITERIA)   # drift, downside, vol, redund
TITLES: Dict[str, str] = {kind: title for kind, title, _ in erd.CRITERIA}

EVAL_WINDOWS: Tuple[int, ...] = (20, 60, 120, 250)   # E — how long a criterion is judged over
HOLDS: Tuple[int, ...] = (1, 5, 20)                  # H — how long a challenger must lead to win
HORIZONS: Tuple[int, ...] = (1, 5, 20, 60)           # h — how far the oracle sees
SEEDS = 20                                           # control seeds, same count as #38/#44/#45
REF_E, REF_H = 60, 1                                 # the selector cell every table reports first


# ═══════════════════════════ shared machinery ═══════════════════════════
def criterion_weights(panel: "dgo.Panel", k: int = REF_K, m_days: int = REF_M,
                      kinds: Sequence[str] = KINDS,
                      cap: Optional[float] = None) -> Dict[str, Dict[str, List[float]]]:
    """One recycled allocation per criterion — each row is EXACTLY the published single-criterion rule.

    Nothing new happens here: `panel_scores` → `rank_demotion_flags` → `alloc_recycle` is the
    same three-call chain #40/#41/#44/#45 were measured with, so the selector below is choosing
    among the registry's own rows rather than among lookalikes. The test-suite pins that identity.
    """
    out: Dict[str, Dict[str, List[float]]] = {}
    for kind in kinds:
        flags = xsd.rank_demotion_flags(erd.panel_scores(panel, kind, LOOKBACK), k, m_days)
        out[kind] = ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap)
    return out


def weights_returns(panel: "dgo.Panel", weights: Dict[str, List[float]]) -> List[float]:
    """Daily portfolio return of an allocation — the same sum `ecr.portfolio_metrics` scores.

    Cash earns 0 %/day (the registry's conservative convention, priced separately in #55), so the
    uninvested rest simply does not appear. Kept as its own function because the selector needs
    the PATH, not the summary metrics.
    """
    return [sum(weights[b][i] * panel.rets[b][i] for b in panel.books) for i in range(panel.n)]


def equal_weights(panel: "dgo.Panel") -> Dict[str, List[float]]:
    """Raw equal weight — what the selector holds before it has enough history to back anybody."""
    w = 1.0 / len(panel.books)
    return {b: [w] * panel.n for b in panel.books}


def trailing_mean(path: Sequence[float], window: int) -> List[Optional[float]]:
    """mean over [i−window, i−1] — strictly before day i. None until the window is full.

    The half-open bound is the whole causality argument of idea #58 and it is pinned by a
    positive control in the test-suite: mutating `path[i]` must not move the value at i.
    """
    if window < 1:
        raise ValueError("window must be >= 1 — judging a criterion on no days is not judging")
    out: List[Optional[float]] = [None] * len(path)
    run = 0.0
    for i in range(len(path)):
        if i >= window:
            run -= path[i - window - 1] if i - window - 1 >= 0 else 0.0
        if i >= 1:
            run += path[i - 1]
        if i >= window:
            out[i] = run / window
    return out


# ═══════════════════════════ #58 — the selector ═══════════════════════════
def leader_path(paths: Dict[str, Sequence[float]], kinds: Sequence[str],
                window: int, hold: int = 1, best: bool = True) -> List[Optional[str]]:
    """Which criterion is backed on each day. None during warm-up (nobody is backed yet).

        rank    : mean own-return over [t−window, t−1]           (strictly causal)
        switch  : the challenger must top that ranking `hold` days running before it takes over
        ties    : broken by criterion name, so the report is reproducible rather than dict-ordered

    `hold` is the same shape as the family's M: a state that only changes on repeated evidence.
    With `hold == 1` the selector follows the ranking immediately, and that identity is pinned.

    `best=False` is the sign-flipped CONTROL (back the trailing WORST criterion). It is never a
    proposed rule; it exists so that "leadership carries information" is a measured claim rather
    than an assumption. Fail-CLOSED: a day on which no criterion has a defined trailing score
    backs NOBODY — a selector with no evidence does not guess.
    """
    if hold < 1:
        raise ValueError("hold must be >= 1 — switching on no evidence is not a rule")
    if not kinds:
        raise ValueError("an empty shortlist is not a selector — pass at least one criterion")
    n = len(paths[kinds[0]])
    trail = {c: trailing_mean(paths[c], window) for c in kinds}
    sign = -1.0 if best else 1.0
    out: List[Optional[str]] = []
    backed: Optional[str] = None
    challenger: Optional[str] = None
    run = 0
    for i in range(n):
        ranked = [c for c in kinds if trail[c][i] is not None]
        if not ranked:
            out.append(backed)                    # no evidence ⇒ state frozen (warm-up: nobody)
            continue
        top = sorted(ranked, key=lambda c: (sign * float(trail[c][i]), c))[0]
        if backed is None:
            backed, challenger, run = top, top, 0
        elif top == backed:
            challenger, run = backed, 0
        else:
            run = run + 1 if top == challenger else 1
            challenger = top
            if run >= hold:
                backed, run = top, 0
        out.append(backed)
    return out


def selected_weights(panel: "dgo.Panel", by_kind: Dict[str, Dict[str, List[float]]],
                     leaders: Sequence[Optional[str]]) -> Dict[str, List[float]]:
    """Hold the backed criterion's allocation each day; hold raw equal weight while nobody is backed.

    Because the weights are stitched day by day, the turnover bill of `ecr.portfolio_metrics`
    automatically charges for CHANGING ONE'S MIND — every criterion switch moves capital and the
    cost model sees it. That is deliberate: a selector that flips daily should pay for it, and no
    separate switching penalty is added on top (which would double-charge).
    """
    fallback = equal_weights(panel)
    out: Dict[str, List[float]] = {b: [0.0] * panel.n for b in panel.books}
    for i in range(panel.n):
        src = fallback if leaders[i] is None else by_kind[leaders[i]]
        for b in panel.books:
            out[b][i] = src[b][i]
    return out


def rotated_leaders(leaders: Sequence[Optional[str]], shift: int) -> List[Optional[str]]:
    """Rotate the leadership path in TIME (circular) — the control of #38, applied to the choice.

    Switch count and the share of days each criterion is backed survive exactly; the alignment
    between "who was winning" and "what happened next" does not. Deliberately non-causal: like
    `ecr.shifted_flags` it can never be run live and is never proposed as a rule.
    """
    if not leaders:
        return []
    s = shift % len(leaders)
    return list(leaders[s:]) + list(leaders[:s])


def permuted_leaders(leaders: Sequence[Optional[str]], kinds: Sequence[str],
                     seed: int) -> List[Optional[str]]:
    """Re-label WHICH criterion each leadership spell backs, keeping the spells themselves.

    The sharper of the two controls: switch times, spell lengths and the number of distinct
    criteria are preserved exactly, and only the identity is destroyed. If a re-labelled selector
    does as well as the real one, the selector is not choosing — it is merely holding something.
    """
    rng = random.Random(seed)
    order = list(kinds)
    rng.shuffle(order)
    remap = {kinds[i]: order[i] for i in range(len(kinds))}
    return [None if c is None else remap[c] for c in leaders]


def oracle_leaders(paths: Dict[str, Sequence[float]], kinds: Sequence[str],
                   horizon: int = 1) -> List[str]:
    """LOOK-AHEAD: back the criterion with the best return over [t, t+horizon). Never a rule.

    The ceiling of daily switching — what backing the right criterion would have been worth if
    the choice could be made with perfect foresight. Printed so that outcome B ("leadership is
    not predictable") can be read as a statement about PREDICTABILITY rather than about the size
    of the prize: if even this row is small, there was nothing to predict in the first place.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1 — an oracle that sees nothing is not an oracle")
    n = len(paths[kinds[0]])
    out: List[str] = []
    for i in range(n):
        hi = min(n, i + horizon)
        fwd = {c: sum(paths[c][i:hi]) / (hi - i) for c in kinds}
        out.append(sorted(kinds, key=lambda c: (-fwd[c], c))[0])
    return out


def leadership_persistence(paths: Dict[str, Sequence[float]], kinds: Sequence[str],
                           window: int, hold: int = 1) -> Dict[str, float]:
    """Does today's leader stay the leader — measured directly, not inferred from a Calmar.

    Three numbers, and they answer three different questions:
      • `day_persistence` — P(argmax tomorrow == argmax today) on the RANKING (not the backed
        state, which `hold` would flatter by construction);
      • `forward_hit` — P(trailing-window leader == the criterion that actually wins the NEXT
        `window` days), the quantity a selector is betting on, against `chance` = 1/len(kinds);
      • `spells` — how many times the backed criterion changes per year, i.e. what the bet costs.
    """
    n = len(paths[kinds[0]])
    trail = {c: trailing_mean(paths[c], window) for c in kinds}
    rank: List[Optional[str]] = []
    for i in range(n):
        ranked = [c for c in kinds if trail[c][i] is not None]
        rank.append(sorted(ranked, key=lambda c: (-float(trail[c][i]), c))[0] if ranked else None)

    same = pairs = 0
    for i in range(1, n):
        if rank[i] is None or rank[i - 1] is None:
            continue
        pairs += 1
        same += 1 if rank[i] == rank[i - 1] else 0

    hits = shots = 0
    winners: Dict[str, int] = {c: 0 for c in kinds}
    for i in range(n):
        if rank[i] is None or i + window > n:
            continue
        fwd = {c: sum(paths[c][i:i + window]) / window for c in kinds}
        win = sorted(kinds, key=lambda c: (-fwd[c], c))[0]
        winners[win] += 1
        shots += 1
        hits += 1 if rank[i] == win else 0

    backed = leader_path(paths, kinds, window, hold)
    switches = sum(1 for i in range(1, n)
                   if backed[i] is not None and backed[i - 1] is not None
                   and backed[i] != backed[i - 1])
    return {
        "day_persistence": same / pairs if pairs else float("nan"),
        "forward_hit": hits / shots if shots else float("nan"),
        "chance": 1.0 / len(kinds),
        # The honest null is NOT 1/4. A constant predictor that always names the criterion which
        # wins most often would score `majority` without looking at anything, and on a sample
        # where one criterion dominates that is a high number. Beating 1/4 is arithmetic;
        # beating `majority` is the only version of "the trailing window told us something".
        "majority": (max(winners.values()) / shots) if shots else float("nan"),
        "switches_yr": switches * 365.0 / n,
        "days_judged": float(pairs),
    }


# ═══════════════════════════ #59 — the ceiling ═══════════════════════════
def forward_scores(panel: "dgo.Panel", horizon: int) -> "erd.Scores":
    """LOOK-AHEAD scores: the mean return of book b over [t, t+horizon). Never a rule.

    The window INCLUDES day t because the flag produced for day t governs day t's return: an
    oracle that saw only [t+1, …] would be judged on a day it was not allowed to see, which would
    understate the ceiling for a reason having nothing to do with information.

    The last `horizon−1` days see a shorter window rather than `None`: truncating them would hand
    the oracle a free refusal (no rank ⇒ nobody demoted) exactly at the sample's end, which is
    where a bound is most easily flattered. A day with no forward return at all is `None`.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1 — an oracle that sees nothing is not an oracle")
    n = panel.n
    out: Dict[str, List[Optional[float]]] = {}
    for b in panel.books:
        r = panel.rets[b]
        col: List[Optional[float]] = []
        for i in range(n):
            hi = min(n, i + horizon)
            col.append(sum(r[i:hi]) / (hi - i) if hi > i else None)
        out[b] = col
    return out


def chance_floor(panel: "dgo.Panel", flags: Dict[str, List[bool]], k: int, m_days: int,
                 cap: Optional[float] = None, seeds: int = SEEDS) -> Dict[str, float]:
    """The duty- and turnover-matched "no information" level of THIS rule (#38's own control).

    `ecr.permuted_flags` re-attaches the real flag paths to the wrong books: the number of demoted
    book-days, the switch structure and the day-by-day count of eligible books are preserved
    EXACTLY, and only "which book" is destroyed. That is the honest zero for a capture ratio —
    scoring against raw instead would credit the rule for merely holding a different portfolio.
    """
    acc: Dict[str, float] = {}
    for s in range(seeds):
        m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            panel.books, ecr.permuted_flags(flags, panel.books, s), panel.n, cap=cap))
        for key, v in m.items():
            acc[key] = acc.get(key, 0.0) + v
    return {key: v / seeds for key, v in acc.items()}


def capture(rule: float, oracle: float, floor: float) -> Optional[float]:
    """(rule − floor) / (oracle − floor); None when the ceiling is not above the floor.

    Refusing to print a ratio when the denominator is non-positive is not pedantry: a ceiling at
    or below chance means the measurement found NO information to capture, and a percentage of
    nothing is the kind of number that gets quoted later without its denominator.
    """
    span = oracle - floor
    if span <= EPS:
        return None
    return (rule - floor) / span


# ═══════════════════════════ report bodies ═══════════════════════════
def _ocs_rows(panel: "dgo.Panel", k: int, m_days: int, kinds: Sequence[str],
              windows: Sequence[int], hold: int,
              cap: Optional[float] = None) -> List[Tuple[str, Dict[str, List[float]], float]]:
    by_kind = criterion_weights(panel, k, m_days, kinds, cap=cap)
    paths = {c: weights_returns(panel, by_kind[c]) for c in kinds}
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    for c in kinds:
        rows.append((f"single {TITLES[c]}", by_kind[c], 0.0))
    for e in windows:
        rows.append((f"OCS E={e} H={hold} [causal]",
                     selected_weights(panel, by_kind, leader_path(paths, kinds, e, hold)), 0.0))

    short = [c for c in kinds if c != "redundancy"]
    if short and len(short) != len(kinds):
        # #56 measured that the return-blind juror (#44 RCD, −2.37 alone) drags a POOL down. A
        # selector is not a pool and need never back it, so "does the known-bad criterion explain
        # the selector's loss?" is a different question and gets its own row rather than a guess.
        rows.append((f"OCS E={REF_E} H={hold} shortlist −#44",
                     selected_weights(panel, by_kind,
                                      leader_path({c: paths[c] for c in short}, short,
                                                  REF_E, hold)), 0.0))

    ref = leader_path(paths, kinds, REF_E, hold)
    rows.append((f"  CONTROL anti-selector E={REF_E}",
                 selected_weights(panel, by_kind,
                                  leader_path(paths, kinds, REF_E, hold, best=False)), 0.0))
    rows.append((f"  CONTROL static twin of E={REF_E}",
                 ecr.alloc_static_matched(selected_weights(panel, by_kind, ref)), 0.0))
    rows.append(("  [LOOK-AHEAD] oracle choice h=1",
                 selected_weights(panel, by_kind, oracle_leaders(paths, kinds, 1)), 0.0))
    rows.append((f"  [LOOK-AHEAD] oracle choice h={REF_E}",
                 selected_weights(panel, by_kind, oracle_leaders(paths, kinds, REF_E)), 0.0))
    return rows


def idea58_ocs(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, m_days: int = REF_M, kinds: Sequence[str] = KINDS,
               windows: Sequence[int] = EVAL_WINDOWS,
               hold: int = REF_H) -> Dict[str, Dict[str, float]]:
    """Idea #58 — can the family's rule be CHOSEN causally, or only in hindsight?"""
    panel = dgo.Panel(subset, start, end)
    rows = _ocs_rows(panel, k, m_days, kinds, windows, hold)
    out = xsd._report(f"IDEA #58 OCS — online criterion selection [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        by_kind = criterion_weights(panel, k, m_days, kinds)
        paths = {c: weights_returns(panel, by_kind[c]) for c in kinds}
        led = leader_path(paths, kinds, REF_E, hold)
        print("-" * 110)
        warm = sum(1 for c in led if c is None)
        share = {c: sum(1 for x in led if x == c) for c in kinds}
        print(f"E={REF_E} H={hold}: warm-up {warm}/{panel.n} days backing NOBODY (raw equal weight, "
              f"no demotion — the conservative default, stated because it flatters the row)")
        print("days backed: " + "  ".join(
            f"{TITLES[c].split()[0]} {share[c]} ({share[c]/panel.n*100:.1f}%)" for c in kinds))
    return out


def _oib_rows(panel: "dgo.Panel", k: int, ms: Sequence[int], horizons: Sequence[int],
              cap: Optional[float] = None) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """The ceiling swept over M as well as h — because the two limits are DIFFERENT limits.

    A rule with M=20 holds each demotion for twenty days. Handing such a rule one-day foresight
    does not buy one-day accuracy: the machine cannot act on it. Sweeping M alongside h is what
    separates "the panel contains no more information" from "this rule shape cannot spend it",
    and those two sentences have opposite consequences for what the registry should do next.
    """
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []
    drift = erd.panel_scores(panel, "drift", LOOKBACK)
    for m_days in ms:
        rows.append((f"#40 XSD drift k={k} M={m_days}",
                     ecr.alloc_recycle(panel.books,
                                       xsd.rank_demotion_flags(drift, k, m_days), panel.n,
                                       cap=cap), 0.0))
    for m_days in ms:
        for h in horizons:
            fs = forward_scores(panel, h)
            rows.append((f"  [LOOK-AHEAD] oracle h={h} M={m_days}",
                         ecr.alloc_recycle(panel.books,
                                           xsd.rank_demotion_flags(fs, k, m_days), panel.n,
                                           cap=cap), 0.0))
    fs = forward_scores(panel, horizons[-1])
    rows.append((f"  [LOOK-AHEAD] ANTI-oracle h={horizons[-1]} M={ms[-1]}",
                 ecr.alloc_recycle(panel.books,
                                   xsd.rank_demotion_flags(fs, k, ms[-1], worst_first=False),
                                   panel.n, cap=cap), 0.0))
    return rows


def idea59_oib(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, ms: Sequence[int] = (1, REF_M),
               horizons: Sequence[int] = HORIZONS) -> Dict[str, Dict[str, float]]:
    """Idea #59 — what is the ceiling of this rule shape, and what fraction does #40 take?"""
    panel = dgo.Panel(subset, start, end)
    rows = _oib_rows(panel, k, ms, horizons)
    out = xsd._report(f"IDEA #59 OIB — oracle information bound [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        base = ecr._raw_metrics(panel)
        drift = erd.panel_scores(panel, "drift", LOOKBACK)
        print("-" * 110)
        print("CAPTURE — how much of the ceiling the published rule takes. maxDD is printed beside "
              "every Calmar")
        print("because Calmar is UNBOUNDED as drawdown goes to zero: an oracle that removes the "
              "drawdown entirely posts")
        print("a Calmar in the thousands, and a percentage of that is arithmetic, not a finding. "
              "Read the APY columns first.")
        print(f"{'ceiling':26s} {'ceilDD':>8s} {'ΔCalmar':>9s} {'capC':>7s} "
              f"{'ΔnetAPY':>10s} {'capA':>7s}")
        for m_days in ms:
            rule_m = out[f"#40 XSD drift k={k} M={m_days}"]
            floor = chance_floor(panel, xsd.rank_demotion_flags(drift, k, m_days), k, m_days)
            print(f"— M={m_days}: rule Calmar {rule_m['calmar']:.2f} (Δ vs raw "
                  f"{rule_m['calmar']-base['calmar']:+.2f}) · chance floor {floor['calmar']:.2f} "
                  f"/ netAPY {floor['net_apy_after_cost']*100:.2f}%")
            for h in horizons:
                o = out[f"[LOOK-AHEAD] oracle h={h} M={m_days}"]
                cc = capture(rule_m["calmar"], o["calmar"], floor["calmar"])
                cn = capture(rule_m["net_apy_after_cost"], o["net_apy_after_cost"],
                             floor["net_apy_after_cost"])
                print(f"  oracle h={h:<16d} {o['maxdd']*100:7.2f}% "
                      f"{o['calmar']-floor['calmar']:+9.2f} "
                      f"{('%.0f%%' % (cc*100)) if cc is not None else '  n/a':>7s} "
                      f"{(o['net_apy_after_cost']-floor['net_apy_after_cost'])*100:+9.2f}pp "
                      f"{('%.0f%%' % (cn*100)) if cn is not None else '  n/a':>7s}")
        print("capture is a fraction of THIS RULE SHAPE's ceiling (bottom-k + M + recycling), "
              "not of every rule a curator could write.")
    return out


# ═══════════════════════════ diagnostics ═══════════════════════════
def persistence_report(subset: Optional[Sequence[str]] = None,
                       kinds: Sequence[str] = KINDS, windows: Sequence[int] = EVAL_WINDOWS,
                       k: int = REF_K, m_days: int = REF_M, hold: int = REF_H) -> None:
    """Section 2 of #58 — leadership persistence, measured before any Calmar is quoted."""
    panel = dgo.Panel(subset)
    by_kind = criterion_weights(panel, k, m_days, kinds)
    paths = {c: weights_returns(panel, by_kind[c]) for c in kinds}
    print()
    print("=" * 110)
    print(f"LEADERSHIP PERSISTENCE — is there anything to follow?  ({panel.n} days, "
          f"{len(kinds)} criteria, chance = {100.0/len(kinds):.0f}%)")
    print("=" * 110)
    print(f"{'window E':>9s} {'P(leader holds a day)':>22s} {'P(trailing == forward)':>23s}"
          f" {'coin':>7s} {'majority':>9s} {'switches/yr':>12s}")
    for e in windows:
        p = leadership_persistence(paths, kinds, e, hold)
        print(f"{e:9d} {p['day_persistence']*100:21.1f}% {p['forward_hit']*100:22.1f}%"
              f" {p['chance']*100:6.1f}% {p['majority']*100:8.1f}% {p['switches_yr']:12.2f}")
    print("A selector bets on the third column, and its honest null is `majority` (always name the")
    print("criterion that wins most often — a predictor that reads nothing), NOT the coin. Beating")
    print("the coin and losing to majority means the window is describing the sample, not the future.")


def selector_grid(subset: Optional[Sequence[str]] = None,
                  kinds: Sequence[str] = KINDS, windows: Sequence[int] = EVAL_WINDOWS,
                  holds: Sequence[int] = HOLDS, k: int = REF_K, m_days: int = REF_M) -> None:
    """The (E × H) grid printed WHOLE — the registry does not publish winners of unprinted sweeps."""
    panel = dgo.Panel(subset)
    base = ecr._raw_metrics(panel)
    by_kind = criterion_weights(panel, k, m_days, kinds)
    paths = {c: weights_returns(panel, by_kind[c]) for c in kinds}
    singles = {c: ecr.portfolio_metrics(panel, by_kind[c]) for c in kinds}
    best_single = max(singles.values(), key=lambda m: m["calmar"])
    print()
    print("=" * 110)
    print(f"SELECTOR GRID (E × H) — ΔCalmar vs raw   [best single criterion: "
          f"{best_single['calmar']-base['calmar']:+.2f}]")
    print("=" * 110)
    print("  H \\ E  " + "".join(f"{e:>9d}" for e in windows))
    for h in holds:
        cells = []
        for e in windows:
            m = ecr.portfolio_metrics(panel, selected_weights(
                panel, by_kind, leader_path(paths, kinds, e, h)))
            cells.append(f"{m['calmar']-base['calmar']:+9.2f}")
        print(f"{h:6d}   " + "".join(cells))
    print()
    print("netAPY over the same grid (after the #10 turnover bill):")
    print("  H \\ E  " + "".join(f"{e:>9d}" for e in windows))
    for h in holds:
        cells = []
        for e in windows:
            m = ecr.portfolio_metrics(panel, selected_weights(
                panel, by_kind, leader_path(paths, kinds, e, h)))
            cells.append(f"{m['net_apy_after_cost']*100:8.2f}%")
        print(f"{h:6d}   " + "".join(cells))


def selector_controls(subset: Optional[Sequence[str]] = None,
                      kinds: Sequence[str] = KINDS, k: int = REF_K, m_days: int = REF_M,
                      e: int = REF_E, hold: int = REF_H, seeds: int = SEEDS) -> None:
    """Destroy exactly one kind of information each, leave the spells and the turnover intact."""
    panel = dgo.Panel(subset)
    base = ecr._raw_metrics(panel)
    by_kind = criterion_weights(panel, k, m_days, kinds)
    paths = {c: weights_returns(panel, by_kind[c]) for c in kinds}
    led = leader_path(paths, kinds, e, hold)
    real = ecr.portfolio_metrics(panel, selected_weights(panel, by_kind, led))
    print()
    print("=" * 110)
    print(f"INFORMATION CONTROLS — OCS E={e} H={hold}  "
          f"({seeds} criterion-relabellings, 3 time-rotations)")
    print("=" * 110)
    print(f"{'configuration':34s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔCalmar':>8s}"
          f" {'depl':>5s} {'maxW':>5s} {'turn/yr':>8s} {'netAPY':>8s}")
    ecr._row("REAL choice", real, base)

    beat = 0
    for s in range(seeds):
        m = ecr.portfolio_metrics(panel, selected_weights(
            panel, by_kind, permuted_leaders(led, kinds, s)))
        beat += 1 if m["calmar"] >= real["calmar"] else 0
    print(f"{'  relabelled criteria (' + str(seeds) + ' seeds)':34s}   "
          f"reached the real Calmar in {beat}/{seeds} draws  (p ≈ {(beat+1)/(seeds+1):.3f})")

    for shift in (91, 182, 273):
        m = ecr.portfolio_metrics(panel, selected_weights(
            panel, by_kind, rotated_leaders(led, shift)))
        ecr._row(f"  rotated {shift}d [non-causal]", m, base)


def dead_book_contrast(k: int = REF_K, ms: Sequence[int] = (1, REF_M),
                       horizons: Sequence[int] = HORIZONS) -> None:
    """#54's trap, applied to the ceiling: a dead feed prints 0.0, and 0.0 outranks every loser."""
    full = dgo.Panel()
    live = ets.live_books(full)
    print()
    print("=" * 110)
    print(f"DEAD-BOOK CONTAMINATION OF THE CEILING (#54) — {len(live)} live of {len(full.books)}")
    print("=" * 110)
    print("live books: " + ", ".join(live))
    print("A book whose feed died prints exactly 0.0 forever, so its FORWARD mean is exactly 0.0 —")
    print("which outranks every book that is genuinely losing. The oracle parks in dead books for")
    print("the same reason the causal rules do, so the ceiling carries the same unsigned cash leg.")
    for name, subset in (("all 10 books", None), (f"{len(live)} live books", live)):
        panel = dgo.Panel(subset)
        base = ecr._raw_metrics(panel)
        drift = erd.panel_scores(panel, "drift", LOOKBACK)
        for m_days in ms:
            rule = xsd.rank_demotion_flags(drift, k, m_days)
            rule_m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, rule, panel.n))
            floor = chance_floor(panel, rule, k, m_days)
            print(f"\n{name}, M={m_days}: raw Calmar {base['calmar']:.2f} · #40 Calmar "
                  f"{rule_m['calmar']:.2f} (netAPY {rule_m['net_apy_after_cost']*100:.2f}%) "
                  f"· chance floor {floor['calmar']:.2f}")
            print(f"{'ceiling':22s} {'ceilDD':>8s} {'ΔCalmar':>9s} {'capC':>7s} "
                  f"{'netAPY':>9s} {'capA':>7s}")
            for h in horizons:
                o = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                    panel.books, xsd.rank_demotion_flags(forward_scores(panel, h), k, m_days),
                    panel.n))
                cc = capture(rule_m["calmar"], o["calmar"], floor["calmar"])
                cn = capture(rule_m["net_apy_after_cost"], o["net_apy_after_cost"],
                             floor["net_apy_after_cost"])
                print(f"oracle h={h:<13d} {o['maxdd']*100:7.2f}% "
                      f"{o['calmar']-floor['calmar']:+9.2f} "
                      f"{('%.0f%%' % (cc*100)) if cc is not None else '  n/a':>7s} "
                      f"{o['net_apy_after_cost']*100:8.2f}% "
                      f"{('%.0f%%' % (cn*100)) if cn is not None else '  n/a':>7s}")


# ═══════════════════════════ CLI ═══════════════════════════
def _banner() -> None:
    print()
    print("ADVISORY / OUTSIDE_RISKPOLICY — evidence L0 (backtest, not live). No capital moves, "
          "no state is written,")
    print("RiskPolicy v1.0 and the kill-switch thresholds are untouched. Rows marked "
          "[LOOK-AHEAD] are CEILINGS, never rules.")


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--idea", type=int, choices=(58, 59), default=None)
    ap.add_argument("--persistence", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--controls", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    args = ap.parse_args(list(argv))

    only = args.persistence or args.grid or args.controls
    subset = ets.live_books(dgo.Panel()) if args.live_only else None
    label = f"{len(subset)} live books (#54)" if subset else "all 10 real books"

    if args.persistence:
        persistence_report(subset)
    if args.grid:
        selector_grid(subset)
    if args.controls:
        selector_controls(subset)
        ecr.train_test(idea58_ocs, [f"OCS E={e} H={REF_H} [causal]" for e in EVAL_WINDOWS]
                       + [f"single {TITLES[c]}" for c in KINDS])
        ecr.train_test(idea59_oib,
                       [f"#40 XSD drift k={REF_K} M={m}" for m in (1, REF_M)]
                       + [f"[LOOK-AHEAD] oracle h={h} M={m}"
                          for m in (1, REF_M) for h in HORIZONS])
    if only:
        _banner()
        return 0

    if args.idea in (None, 58):
        idea58_ocs(subset=subset, label=label)
        persistence_report(subset)
        selector_grid(subset)
        selector_controls(subset)
        ecr.train_test(idea58_ocs, [f"OCS E={e} H={REF_H} [causal]" for e in EVAL_WINDOWS]
                       + [f"single {TITLES[c]}" for c in KINDS])
    if args.idea in (None, 59):
        idea59_oib(subset=subset, label=label)
        dead_book_contrast()
        ecr.train_test(idea59_oib,
                       [f"#40 XSD drift k={REF_K} M={m}" for m in (1, REF_M)]
                       + [f"[LOOK-AHEAD] oracle h={h} M={m}"
                          for m in (1, REF_M) for h in HORIZONS])
    _banner()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
