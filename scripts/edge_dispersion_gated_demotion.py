#!/usr/bin/env python3
"""Edge R&D — registry ideas #42 (CSDG) and #43 (ZSD). Both attack the SAME unexamined convention
in #40: that the cross-section is ranked EVERY day, whether or not the ranks mean anything.

WHERE THIS COMES FROM
  #40 (XSD) posted the registry's best numbers — netAPY 25.94% against raw 17.94% at −3.37%
  drawdown against −5.44% — and two of its own honest caveats point at the same hole:

    1. Its weakest control is the TIME axis. Book permutation p ≈ 0.048 (the rule knows WHICH
       book), time rotation 4/28, p ≈ 0.172 (the rule barely knows WHEN). A rule that survives
       the first and not the second is a selection rule; #40 said so and addressed it to the
       allocator.

    2. It is the most expensive configuration in the registry: turnover 4.35/yr, a 2.09pp cost
       drag between its gross 28.03% and its net 25.94%.

  Both of those have one candidate cause that no registry entry has ever measured. `bottom-k`
  ranks the field on every single day — including the days when all ten books sit inside each
  other's noise and "the worst two" is a coin flip. On such a day the rule pays turnover to act
  on no information at all. That is simultaneously a cost story (caveat 2) and a WHEN story
  (caveat 1): if the informative days are a minority, a rule that acts on all of them plus all
  the uninformative ones will look weak against a rotation control that dilutes its timing.

  The registry's gates have all been PORTFOLIO-STATE gates — drawdown (#9), volatility (#33),
  regime (#32). The gate below is a different object: it gates on the MEASURABILITY OF THE
  SIGNAL ITSELF. Not "is the market dangerous" but "is the cross-section distinguishable today".

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #42 — CSDG: Cross-Sectional Dispersion Gate  ("rank only when ranks mean something")
──────────────────────────────────────────────────────────────────────────────────────────────
      score(b, t) = mean(r_b[t−L : t−1])                  ← #39/#40's statistic, byte-for-byte
      disp(t)     = population stdev of score(·, t) over the RANKABLE books
      GATE(t)     : disp(t) >= the q-th percentile of disp over the trailing window [t−W, t−1]
      on a gated day   : #40's bottom-k rule runs, unchanged
      on an ungated day: the state is FROZEN — no new demotion, no re-admission credit

  The freeze is the fail-CLOSED reading and it matches a convention the harness already has:
  #40 freezes state when fewer than k+1 books are rankable, on the stated grounds that "no rank
  ⇒ no evidence either way". An ungated day is the same kind of day — the rule declined to look,
  so it learned nothing, and a re-admission counter that ticked anyway would be crediting a book
  for days on which nobody checked it. The alternative (RELEASE everything to equal weight when
  ungated) is reported as a variant, not as the rule: it would ADD turnover, which is the
  opposite of the thing being tested.

  Strictly causal twice over: the percentile window ends at t−1 and never contains disp(t)
  itself, and disp(t) is built from scores that already stop at t−1.

  FALSIFIABLE PREDICTION (this is what makes it a test rather than a knob):
    if the edge lives in high-dispersion days, gating at a high q keeps most of #40's ΔCalmar at
    a fraction of its turnover, so netAPY RISES. If instead ΔCalmar falls in proportion to how
    often the rule is allowed to act, dispersion carries no information beyond "do less of the
    same", and the gate is decoration.

  THE DECISIVE CONTROL — a duty-matched RANDOM gate. #40's decisive control equalised time out
  of the market and asked what was left of the CRITERION. Its transposition to the time axis
  equalises the NUMBER of days on which the rule is allowed to act and asks what is left of the
  TIMING. The random gate draws its days from exactly the region where the real gate is able to
  fire (never from the warm-up, where the real gate is structurally silent — a control that
  could act where the real rule cannot is not matched, it is advantaged). Twenty seeds, so the
  answer is a p-value and not an anecdote.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #43 — ZSD: Z-Score Demotion  ("fix the SIGNIFICANCE, not the hurdle and not the duty")
──────────────────────────────────────────────────────────────────────────────────────────────
  The registry has walked into a 2×2 without ever naming it. A demotion rule has to pin down
  something, and the two entries so far each pinned a different thing:

      #39 CDR   fixes the HURDLE  →  duty is a property of the MARKET
                (measured in #40: at L=60, M=20 the duty jumps 11.7% → 46.4% as the hurdle
                 crosses zero, with nothing in between — duty is not a knob of that rule)
      #40 XSD   fixes the DUTY (k of N)  →  the hurdle is a property of the market

  The third cell fixes NEITHER, and pins the statistical significance of being worst instead:

      mu(t), sd(t) = cross-sectional mean and stdev of the rankable scores at t
      z(b, t)      = (score(b,t) − mu(t)) / sd(t)
      DEMOTED(b,t) : z(b, t) <= −z*
      RE-ADMIT     : z(b, t) > −z* on M consecutive days     ← #40's state machine, unchanged

  Then the COUNT of demoted books is itself dispersion-adaptive: in a tight field nobody is far
  enough below the pack to be demoted, and in a fanned-out field several are. That is the exact
  complement of #42 — #42 gates a fixed-count rule on dispersion, #43 lets dispersion set the
  count — so the two together test one belief from two directions, and a shared failure is a
  much stronger statement than either alone.

  FALSIFIABLE PREDICTION: if normalising by dispersion carries information, ZSD beats BOTH #39
  (fixed hurdle) and #40 (fixed duty) at MATCHED duty. If ZSD merely reproduces a duty-matched
  XSD, the 2×2 collapses — duty is what matters and the criterion is a footnote.

  Fail-CLOSED: fewer than 3 rankable books, or a cross-sectional sd below `MIN_SD`, leaves the
  day unrankable and the state frozen. A z-score built on a degenerate denominator is a number,
  not a measurement, and dividing by it would manufacture demotions out of rounding.

──────────────────────────────────────────────────────────────────────────────────────────────
CONTROLS (all inherited; a rule that always holds something can post a number with no signal)
──────────────────────────────────────────────────────────────────────────────────────────────
  • INVERSE GATE          — rank only on LOW-dispersion days. The sign flip of #42's premise.
  • RANDOM GATE ×20 seeds — the decisive one (above): duty of the GATE matched, timing destroyed.
  • TOP-k FLIP            — demote the best-ranked books; #40's sign flip, kept under the gate.
  • DUTY-MATCHED ABSOLUTE — #40's decisive control, reused verbatim for #43.
  • STATIC WEIGHT-MATCHED — #38's twin: if it matches, this is an allocator tilt, not timing.
  • PERMUTATION / ROTATION — #38's information controls, unchanged, so p-values stay comparable.
  • LEAVE-ONE-OUT         — mandatory since #37.
  • TRAIN → TEST          — split 2025-06-30, the registry's own.

HONESTY / SCOPE (registry rules — non-negotiable)
  • The panel loader, allocator, cost model, metrics and controls are IMPORTED from #32/#38/#40,
    never re-implemented, so every row here is comparable with every row there.
  • L=60 and the bottom-k machinery are INHERITED and not re-tuned. The new axes are the gate
    (q, W) for #42 and z* for #43, and both are swept, not chosen.
  • Books are regenerated nightly ⇒ numbers reproduce only against the panel files of the run
    date. The raw baseline is printed on every run so the reader can check the panel matches.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence L0 (backtest on real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_dispersion_gated_demotion.py            # everything
    python3 scripts/edge_dispersion_gated_demotion.py --idea 42  # CSDG only
    python3 scripts/edge_dispersion_gated_demotion.py --idea 43  # ZSD only
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                # noqa: E402  (audited loader + metrics of #32)
import edge_capital_recycling as ecr           # noqa: E402  (allocator, costs, controls of #38/#39)
import edge_cross_sectional_demotion as xsd    # noqa: E402  (rank rule + duty machinery of #40)
import edge_drift_gated_overlay as dgo         # noqa: E402  (Panel, signals of #35/#36/#37)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK            # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END
BP = cfpt.BP
EPS = 1e-12

GATE_WINDOW = 120                  # trailing days of dispersion history the percentile is read on
GATE_Q = 0.60                      # act on the top 40% of dispersion days — reference, swept below
MIN_GATE_POINTS = 30               # fail-CLOSED: fewer observations ⇒ no percentile ⇒ no gate
MIN_SD = 1e-9                      # fail-CLOSED denominator floor for #43's z-score
REF_K, REF_M = 2, 20               # #40's reference configuration, carried over unchanged
REF_Z = 1.0                        # #43 reference — one cross-sectional sigma below the pack

Scores = xsd.Scores


# ═══════════════════════════════ dispersion of the cross-section ═══════════════════════════════
def dispersion(scores: Scores, min_books: int = 3) -> List[Optional[float]]:
    """Population stdev of the rankable scores on each day — how far apart the field is.

    `None` (not 0.0) when fewer than `min_books` books are rankable: a spread measured on two
    books is not a spread, and a zero there would read as "the field is identical today", which
    is the one thing it is not known to be. Every consumer below treats None as "do not act".
    """
    books = sorted(scores)
    if not books:
        return []
    n = len(scores[books[0]])
    out: List[Optional[float]] = []
    for i in range(n):
        vals = [float(scores[b][i]) for b in books if scores[b][i] is not None]
        if len(vals) < min_books:
            out.append(None)
            continue
        mu = sum(vals) / len(vals)
        out.append((sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5)
    return out


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Nearest-rank percentile of an already-sorted sample (stdlib only, deterministic).

    Nearest-rank rather than interpolated on purpose: the gate is a comparison against a
    threshold drawn from the same small sample, and an interpolated quantile would move with
    floating-point noise between runs on windows of 30-odd points.
    """
    if not sorted_vals:
        raise ValueError("percentile of an empty sample — refused")
    idx = int(q * (len(sorted_vals) - 1) + 0.5)
    return sorted_vals[max(0, min(len(sorted_vals) - 1, idx))]


def dispersion_gate(disp: Sequence[Optional[float]], window: int = GATE_WINDOW, q: float = GATE_Q,
                    min_points: int = MIN_GATE_POINTS, high: bool = True) -> List[bool]:
    """True on days the cross-section is wide enough to be worth ranking.

        gate(t) = disp(t) >= q-th percentile of the defined disp values in [t−window, t−1]

    Strictly causal: the reference window ENDS at t−1 and never contains disp(t) itself. Using
    the full-sample distribution instead would be the classic quiet look-ahead — the rule would
    know today whether today was going to be a wide day by the standards of a year it has not
    lived through yet.

    Fail-CLOSED: an undefined disp(t), or fewer than `min_points` defined observations behind it,
    yields False. False means "the rule is not allowed to act today", never "act freely" — so a
    cold start cannot demote anything.

    `high=False` is the INVERSE control (act only on the NARROW days). It is never a proposed
    rule; it exists so that "wide days are the informative ones" is a measured claim.
    """
    if window < 1:
        raise ValueError("window must be >= 1 — a percentile over no history is not a threshold")
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    out: List[bool] = []
    for i in range(len(disp)):
        d = disp[i]
        if d is None:
            out.append(False)
            continue
        hist = sorted(v for v in disp[max(0, i - window):i] if v is not None)
        if len(hist) < min_points:
            out.append(False)
            continue
        thr = _percentile(hist, q)
        out.append(d >= thr if high else d <= thr)
    return out


def gate_eligible(disp: Sequence[Optional[float]], window: int = GATE_WINDOW,
                  min_points: int = MIN_GATE_POINTS) -> List[bool]:
    """Days on which the gate is CAPABLE of firing (warm-up over, dispersion defined).

    The random control below draws only from these days. A random gate that could fire during
    the warm-up — where the real gate is structurally silent — would not be duty-matched, it
    would be handed extra days the real rule never had.
    """
    out: List[bool] = []
    for i in range(len(disp)):
        if disp[i] is None:
            out.append(False)
            continue
        defined = sum(1 for v in disp[max(0, i - window):i] if v is not None)
        out.append(defined >= min_points)
    return out


def causal_rank(disp: Sequence[Optional[float]], window: int = GATE_WINDOW,
                min_points: int = MIN_GATE_POINTS) -> List[Optional[float]]:
    """Where disp(t) sits inside its own trailing window, as a fraction in [0, 1].

    Same causal contract as `dispersion_gate` (the window ends at t−1 and never contains disp(t)),
    expressed as a rank rather than a threshold comparison. Used only by the count-matched
    controls below, which need a day-by-day ORDERING of "how wide was today, by recent standards"
    in order to select an exact number of days.
    """
    out: List[Optional[float]] = []
    for i in range(len(disp)):
        d = disp[i]
        hist = [v for v in disp[max(0, i - window):i] if v is not None] if d is not None else []
        if d is None or len(hist) < min_points:
            out.append(None)
            continue
        out.append(sum(1 for v in hist if v < d) / len(hist))
    return out


def count_matched_gate(rank: Sequence[Optional[float]], eligible: Sequence[bool], n_open: int,
                       high: bool = True) -> List[bool]:
    """Open on exactly `n_open` eligible days — the widest ones (`high`) or the narrowest.

    The per-day rank is causal, but selecting the CUTOFF that admits exactly `n_open` of them
    uses the full sample. That look-ahead is granted deliberately and only to CONTROLS: it can
    make a control look better than it could ever be live, which is the direction an honest
    comparison should err. It is never used by a proposed rule.
    """
    idx = [i for i, e in enumerate(eligible) if e and rank[i] is not None]
    if n_open > len(idx):
        raise ValueError(f"cannot open {n_open} of {len(idx)} eligible days — refused")
    sign = -1.0 if high else 1.0
    chosen = set(sorted(idx, key=lambda i: (sign * float(rank[i]), i))[:n_open])
    return [i in chosen for i in range(len(eligible))]


def random_gate(eligible: Sequence[bool], n_open: int, seed: int) -> List[bool]:
    """A gate that opens on `n_open` days drawn uniformly from `eligible` — timing destroyed.

    Everything the real gate has is preserved: how many days it may act on, and the region of
    the sample it may act in. The only thing removed is WHICH of those days it picks. Fixed seed,
    so the control is reproducible rather than merely random.
    """
    idx = [i for i, e in enumerate(eligible) if e]
    if n_open > len(idx):
        raise ValueError(f"cannot open {n_open} of {len(idx)} eligible days — refused")
    rng = random.Random(seed)
    chosen = set(rng.sample(idx, n_open))
    return [i in chosen for i in range(len(eligible))]


# ═══════════════════════════════ #42 — the gated rank rule ═══════════════════════════════
def gated_rank_flags(scores: Scores, gate: Sequence[bool], k: int, readmit_days: int = 1,
                     worst_first: bool = True, freeze: bool = True) -> Dict[str, List[bool]]:
    """#40's bottom-k demotion, allowed to act only on gated days.

        gated day   : exactly `xsd.rank_demotion_flags` — demote the bottom-k, credit the rest
        ungated day : `freeze=True`  → state carried forward, and the re-admission counter does
                                       NOT advance (no observation was made, so no book earned
                                       credit for the day);
                      `freeze=False` → every demotion is released (the RELEASE variant, reported
                                       because it is the obvious alternative, not because it is
                                       proposed: it strictly ADDS turnover, which is the opposite
                                       of what the gate is for).

    With an all-True gate this function is `xsd.rank_demotion_flags` exactly — pinned in both
    directions by the test-suite, because a gated rule that quietly differed from the ungated one
    would make every row of the table a comparison between two different rules.
    """
    if k < 1:
        raise ValueError("k must be >= 1 — a rank rule that demotes nobody is not a rule")
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    books = sorted(scores)
    if k >= len(books):
        raise ValueError(f"k={k} with {len(books)} books would demote the whole panel — refused")
    n = len(scores[books[0]]) if books else 0
    if len(gate) != n:
        raise ValueError(f"gate has {len(gate)} days, scores have {n} — refused")
    sign = 1.0 if worst_first else -1.0

    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}
    for i in range(n):
        if not gate[i]:
            if not freeze:
                for b in books:
                    demoted[b] = False
                    good_run[b] = 0
            for b in books:
                out[b].append(demoted[b])
            continue
        rankable = [b for b in books if scores[b][i] is not None]
        if len(rankable) <= k:                    # #40's convention: no rank ⇒ no evidence
            for b in books:
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


# ═══════════════════════════════ #43 — the z-score rule ═══════════════════════════════
def zscore_scores(scores: Scores, min_books: int = 3, min_sd: float = MIN_SD) -> Scores:
    """Cross-sectionally standardised scores: how many field-sigmas a book sits below the pack.

    `None` wherever the standardisation is not defined — fewer than `min_books` rankable, or a
    cross-sectional sd at or below `min_sd`. A z built on a degenerate denominator is arithmetic,
    not measurement, and would turn rounding noise into demotions.
    """
    books = sorted(scores)
    if not books:
        return {}
    n = len(scores[books[0]])
    out: Scores = {b: [None] * n for b in books}
    for i in range(n):
        rankable = [b for b in books if scores[b][i] is not None]
        if len(rankable) < min_books:
            continue
        vals = [float(scores[b][i]) for b in rankable]
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
        if sd <= min_sd:
            continue
        for b in rankable:
            out[b][i] = (float(scores[b][i]) - mu) / sd
    return out


def zscore_demotion_flags(zs: Scores, z_star: float, readmit_days: int = 1,
                          worst_first: bool = True) -> Dict[str, List[bool]]:
    """True on days the book sits `z_star` cross-sectional sigmas or more BELOW the field mean.

        demote   : z(b,t) <= −z_star           (variable count, variable implied hurdle)
        re-admit : z(b,t) > −z_star on `readmit_days` consecutive days

    The state machine is #40's, one substitution ("in the bottom-k" → "below −z*"), so the M axis
    means here exactly what it means in #39 and #40 and the three tables stay comparable.

    Fail-CLOSED: a book with z None is unrankable — its state is frozen and its re-admission
    counter does not advance. Note this differs from "not demoted": an unmeasured book that was
    demoted yesterday STAYS demoted, because nothing has been observed that would clear it.

    `worst_first=False` demotes the field's TOP instead — the sign-flip control, never a rule.
    """
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    if z_star <= 0.0:
        raise ValueError("z_star must be > 0 — a non-positive threshold demotes the median book")
    books = sorted(zs)
    n = len(zs[books[0]]) if books else 0
    sign = 1.0 if worst_first else -1.0

    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}
    for i in range(n):
        for b in books:
            z = zs[b][i]
            if z is None:
                out[b].append(demoted[b])
                continue
            below = (sign * float(z)) <= -z_star
            good_run[b] = 0 if below else good_run[b] + 1
            if demoted[b]:
                if good_run[b] >= readmit_days:
                    demoted[b] = False
            elif below:
                demoted[b] = True
            out[b].append(demoted[b])
    return out


# ═══════════════════════════════ shared plumbing ═══════════════════════════════
def _scores(panel: "dgo.Panel") -> Scores:
    return xsd.drift_scores(panel.rets, LOOKBACK)


def _gate_for(panel: "dgo.Panel", window: int = GATE_WINDOW, q: float = GATE_Q,
              high: bool = True) -> Tuple[List[bool], List[Optional[float]]]:
    disp = dispersion(_scores(panel))
    return dispersion_gate(disp, window, q, high=high), disp


def gate_duty(gate: Sequence[bool]) -> float:
    """Fraction of DAYS the rule was allowed to act — the quantity the random control matches."""
    return sum(1 for g in gate if g) / len(gate) if gate else 0.0


# ═══════════════════════════════ #42 report ═══════════════════════════════
def idea42_csdg(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
                start: Optional[str] = None, end: Optional[str] = None,
                segment: str = "FULL", quiet: bool = False,
                qs: Sequence[float] = (0.0, 0.4, 0.6, 0.8), window: int = GATE_WINDOW,
                seeds: int = 20) -> Dict[str, Dict[str, float]]:
    """Idea #42 — does gating #40's rank rule on cross-sectional dispersion buy anything?"""
    panel = dgo.Panel(subset, start, end)
    sc = _scores(panel)
    disp = dispersion(sc)
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    ungated = xsd.rank_demotion_flags(sc, REF_K, REF_M)
    rows.append((f"#40 XSD k={REF_K} M={REF_M} (ungated)", ecr.alloc_recycle(books, ungated, n), 0.0))

    ref_gate: Optional[List[bool]] = None
    for q in qs:
        g = dispersion_gate(disp, window, q)
        fl = gated_rank_flags(sc, g, REF_K, REF_M)
        rows.append((f"CSDG q={q:.1f} (gate {gate_duty(g)*100:.0f}% of days)",
                     ecr.alloc_recycle(books, fl, n), 0.0))
        if abs(q - GATE_Q) < 1e-9:
            ref_gate = g

    assert ref_gate is not None, "reference q must be inside the swept set"
    n_open = sum(1 for g in ref_gate if g)
    elig = gate_eligible(disp, window)
    if n_open > sum(1 for e in elig if e):      # cannot happen; a gate is a subset of eligibility
        raise AssertionError("gate fires outside its eligible region — refused")

    rank = causal_rank(disp, window)
    inv = count_matched_gate(rank, elig, n_open, high=False)
    rows.append((f"  CONTROL inverse gate, SAME {n_open} days (narrowest)",
                 ecr.alloc_recycle(books, gated_rank_flags(sc, inv, REF_K, REF_M), n), 0.0))
    rows.append((f"  CONTROL top-k flip under gate q={GATE_Q:.1f}",
                 ecr.alloc_recycle(books, gated_rank_flags(
                     sc, ref_gate, REF_K, REF_M, worst_first=False), n), 0.0))
    rows.append((f"  VARIANT release-when-ungated q={GATE_Q:.1f}",
                 ecr.alloc_recycle(books, gated_rank_flags(
                     sc, ref_gate, REF_K, REF_M, freeze=False), n), 0.0))
    rows.append((f"  CONTROL static-matched (gated q={GATE_Q:.1f})",
                 ecr.alloc_static_matched(ecr.alloc_recycle(
                     books, gated_rank_flags(sc, ref_gate, REF_K, REF_M), n)), 0.0))

    out = _report(f"IDEA #42 CSDG — dispersion-gated demotion [{segment}] — {label}",
                  panel, rows, quiet)

    if not quiet:
        base = ecr._raw_metrics(panel)
        real = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            books, gated_rank_flags(sc, ref_gate, REF_K, REF_M), n))
        print("-" * 110)
        print(f"THE DECISIVE CONTROL — random gates opening on the SAME {n_open} days drawn from "
              f"the same eligible region")
        print(f"{'configuration':34s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔCalmar':>8s} "
              f"{'depl':>6s} {'maxW':>6s} {'turn/yr':>8s} {'netAPY':>8s}")
        rand = []
        for s in range(seeds):
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                books, gated_rank_flags(sc, random_gate(elig, n_open, s), REF_K, REF_M), n))
            rand.append(m)
        rs = sorted(rand, key=lambda m: m["calmar"])
        for tag, m in (("rand P10", rs[max(0, int(0.1 * seeds) - 1)]),
                       ("rand P50 (median)", rs[seeds // 2]),
                       ("rand P90", rs[min(seeds - 1, int(0.9 * seeds))]),
                       ("rand BEST", rs[-1])):
            ecr._row(f"  CONTROL {tag}", m, base)
        beaten = sum(1 for m in rand if m["calmar"] >= real["calmar"])
        print(f"  → random gates reaching the real gate's Calmar: {beaten}/{seeds}"
              f"   (empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")
        print("  If the random gates match, the gate's VALUE is 'act less often', not 'act on the")
        print("  right days' — a cost argument, never a timing one, and it must be sold as such.")
    return out


def gate_sweep(qs: Sequence[float] = (0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
               windows: Sequence[int] = (60, 120, 252)) -> None:
    """Plateau or lottery ticket? ΔCalmar and netAPY over the (percentile × window) grid."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = _scores(panel)
    disp = dispersion(sc)
    print()
    print("=" * 110)
    print(f"#42 CSDG — SWEEP vs raw Calmar {base['calmar']:.2f}; rows = gate percentile q, "
          f"cols = trailing window W")
    print("=" * 110)
    header = "q \\ W"
    print(f"{header:>8s}" + "".join(f"{w:>22d}" for w in windows))
    print(f"{'':>8s}" + "".join(f"{'ΔCalmar  net  gate%':>22s}" for _ in windows))
    for q in qs:
        cells = []
        for w in windows:
            g = dispersion_gate(disp, w, q)
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
                panel.books, gated_rank_flags(sc, g, REF_K, REF_M), panel.n))
            cells.append(f"{m['calmar']-base['calmar']:+8.2f}{m['net_apy_after_cost']*100:7.2f}%"
                         f"{gate_duty(g)*100:6.0f}%")
        print(f"{q:>8.1f}" + "".join(f"{c:>22s}" for c in cells))
    print("q=0.0 is the ungated #40 rule restricted to the warm-up-complete region — the row that")
    print("says how much of any difference is the gate and how much is merely the shorter sample.")


# ═══════════════════════════════ #43 report ═══════════════════════════════
def idea43_zsd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               zstars: Sequence[float] = (0.6, 1.0, 1.4), ms: Sequence[int] = (1, 20)
               ) -> Dict[str, Dict[str, float]]:
    """Idea #43 — fix the significance of 'worst' instead of the hurdle (#39) or the duty (#40)."""
    panel = dgo.Panel(subset, start, end)
    sc = _scores(panel)
    zs = zscore_scores(sc)
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    abs20 = xsd.absolute_flags(panel, xsd.HURDLE, LOOKBACK, REF_M)
    rows.append(("#39 CDR absolute M=20", ecr.alloc_recycle(books, abs20, n), 0.0))
    xsd_ref = xsd.rank_demotion_flags(sc, REF_K, REF_M)
    rows.append((f"#40 XSD k={REF_K} M={REF_M}", ecr.alloc_recycle(books, xsd_ref, n), 0.0))

    ref_flags: Optional[Dict[str, List[bool]]] = None
    for z in zstars:
        for m_days in ms:
            fl = zscore_demotion_flags(zs, z, m_days)
            rows.append((f"ZSD z={z:.1f} M={m_days} (duty {xsd.duty(fl)*100:.0f}%)",
                         ecr.alloc_recycle(books, fl, n), 0.0))
            if abs(z - REF_Z) < 1e-9 and m_days == REF_M:
                ref_flags = fl

    assert ref_flags is not None, "reference (z*, M) must be inside the swept set"
    target = xsd.duty(ref_flags)

    rows.append((f"  CONTROL top-flip z={REF_Z:.1f} M={REF_M}",
                 ecr.alloc_recycle(books, zscore_demotion_flags(
                     zs, REF_Z, REF_M, worst_first=False), n), 0.0))
    if not quiet:
        lkb_m, h_m, m_m, d_m = xsd.match_duty_absolute(panel, target)
        rows.append((f"  CONTROL duty-matched abs {d_m*100:.0f}% (L{lkb_m}/M{m_m})",
                     ecr.alloc_recycle(books, xsd.absolute_flags(panel, h_m, lkb_m, m_m), n), 0.0))
        k_m, dk_m = _match_duty_rank(sc, target, ms=(REF_M,))
        rows.append((f"  CONTROL duty-matched XSD k={k_m} ({dk_m*100:.0f}%)",
                     ecr.alloc_recycle(books, xsd.rank_demotion_flags(sc, k_m, REF_M), n), 0.0))
    rows.append((f"  CONTROL static-matched z={REF_Z:.1f} M={REF_M}",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, ref_flags, n)), 0.0))
    rows.append((f"  under {int(ecr.CONC_CAP*100)}% per-name cap z={REF_Z:.1f} M={REF_M}",
                 ecr.alloc_recycle(books, ref_flags, n, cap=ecr.CONC_CAP), 0.0))

    out = _report(f"IDEA #43 ZSD — z-score demotion [{segment}] — {label}", panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("The whole point of the row pair above: ZSD fixes NEITHER hurdle nor duty. If the")
        print("duty-matched XSD row reproduces it, the 2×2 collapses and duty is what mattered.")
    return out


def _match_duty_rank(scores: Scores, target: float, ks: Sequence[int] = (1, 2, 3, 4, 5),
                     ms: Sequence[int] = (REF_M,)) -> Tuple[int, float]:
    """The bottom-k configuration whose book-day duty is closest to `target`.

    k is coarse (each step is 1/N of the panel ≈ 10 points of duty), so this control is honest
    only if the ACHIEVED duty is printed beside the target — which the caller does. A control
    that missed the target by ten points and did not say so would turn the criterion comparison
    back into the duty confound #40 spent its whole table escaping.
    """
    best: Optional[Tuple[float, int, float]] = None
    for k in ks:
        for m_days in ms:
            d = xsd.duty(xsd.rank_demotion_flags(scores, k, m_days))
            err = abs(d - target)
            if best is None or err < best[0]:
                best = (err, k, d)
    assert best is not None
    return best[1], best[2]


def z_sweep(zstars: Sequence[float] = (0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.8),
            ms: Sequence[int] = (1, 2, 5, 10, 20, 45)) -> None:
    """ΔCalmar over the (significance threshold × re-admission delay) grid, with duty printed."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    zs = zscore_scores(_scores(panel))
    print()
    print("=" * 110)
    print(f"#43 ZSD — SWEEP of ΔCalmar vs raw ({base['calmar']:.2f}); rows = z*, "
          f"cols = re-admission delay M   [duty in brackets]")
    print("=" * 110)
    header = "z* \\ M"
    print(f"{header:>8s}" + "".join(f"{m:>16d}" for m in ms))
    for z in zstars:
        cells = []
        for m_days in ms:
            fl = zscore_demotion_flags(zs, z, m_days)
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, fl, panel.n))
            cells.append(f"{m['calmar']-base['calmar']:+8.2f}[{xsd.duty(fl)*100:3.0f}%]")
        print(f"{z:>8.1f}" + "".join(f"{c:>16s}" for c in cells))


# ═══════════════════════════════ shared report shim ═══════════════════════════════
def _report(title: str, panel: "dgo.Panel", rows, quiet: bool) -> Dict[str, Dict[str, float]]:
    """#40's reporter, reused so every row of #42/#43 is printed in the same columns as #39/#40."""
    return xsd._report(title, panel, rows, quiet)


# ═══════════════════════════════ the control that won ═══════════════════════════════
def idea42_inverse(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
                   start: Optional[str] = None, end: Optional[str] = None,
                   segment: str = "FULL", quiet: bool = False,
                   window: int = GATE_WINDOW, seeds: int = 20) -> Dict[str, Dict[str, float]]:
    """The REFUTING CONTROL of #42, run through #42's own discipline — because it beat the rule.

    This is not a promotion and must never be read as one. The inverse gate was not a hypothesis;
    it was the sign flip put in the table so that "wide days are the informative ones" would be a
    measured claim rather than an assumption. It won. A control that wins is a hypothesis-
    GENERATING event on the sample that produced it, not a result — it was selected by looking at
    the answer, which is the single most reliable way to manufacture an edge that is not there.

    So it gets the same treatment every proposed rule gets — count-matched random gates,
    train→test, leave-one-out — and whatever those say is recorded as-is. If it survives all
    three it is a candidate for a FUTURE entry with a pre-registered threshold, not a conclusion
    of this one.
    """
    panel = dgo.Panel(subset, start, end)
    sc = _scores(panel)
    disp = dispersion(sc)
    elig = gate_eligible(disp, window)
    rank = causal_rank(disp, window)
    books, n = panel.books, panel.n

    ref_gate = dispersion_gate(disp, window, GATE_Q)
    n_open = sum(1 for g in ref_gate if g)
    inv = count_matched_gate(rank, elig, n_open, high=False)

    rows: List[Tuple[str, Dict[str, List[float]], float]] = [
        (f"#40 XSD k={REF_K} M={REF_M} (ungated)",
         ecr.alloc_recycle(books, xsd.rank_demotion_flags(sc, REF_K, REF_M), n), 0.0),
        (f"CSDG q={GATE_Q:.1f} (wide days — the RULE)",
         ecr.alloc_recycle(books, gated_rank_flags(sc, ref_gate, REF_K, REF_M), n), 0.0),
        (f"INVERSE same {n_open} days (narrow — the CONTROL)",
         ecr.alloc_recycle(books, gated_rank_flags(sc, inv, REF_K, REF_M), n), 0.0),
        ("  CONTROL top-k flip under inverse",
         ecr.alloc_recycle(books, gated_rank_flags(sc, inv, REF_K, REF_M, worst_first=False), n),
         0.0),
        ("  CONTROL static-matched (inverse)",
         ecr.alloc_static_matched(ecr.alloc_recycle(
             books, gated_rank_flags(sc, inv, REF_K, REF_M), n)), 0.0),
    ]
    out = _report(f"#42 CONTROL-THAT-WON — inverse dispersion gate [{segment}] — {label}",
                  panel, rows, quiet)

    if not quiet:
        base = ecr._raw_metrics(panel)
        real = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            books, gated_rank_flags(sc, inv, REF_K, REF_M), n))
        print("-" * 110)
        print(f"Random gates on the SAME {n_open} days, drawn from the same eligible region:")
        rand = [ecr.portfolio_metrics(panel, ecr.alloc_recycle(
            books, gated_rank_flags(sc, random_gate(elig, n_open, s), REF_K, REF_M), n))
            for s in range(seeds)]
        rs = sorted(rand, key=lambda m: m["calmar"])
        for tag, m in (("rand P50 (median)", rs[seeds // 2]), ("rand BEST", rs[-1])):
            ecr._row(f"  CONTROL {tag}", m, base)
        beaten = sum(1 for m in rand if m["calmar"] >= real["calmar"])
        print(f"  → random gates reaching the inverse gate's Calmar: {beaten}/{seeds}"
              f"   (empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")
    return out


# ═══════════════════════════════ the instrument #43 needs ═══════════════════════════════
def duty_collapse(buckets: Sequence[Tuple[float, float]] = ((0.0, 0.10), (0.10, 0.20),
                                                            (0.20, 0.30), (0.30, 0.45),
                                                            (0.45, 1.00))) -> None:
    """Does ΔCalmar depend on the CRITERION at all, once duty is held fixed?

    Every demotion entry in the registry (#39 hurdle-fixed, #40 duty-fixed, #43 significance-
    fixed) reports a single configuration and compares it with a single duty-matched twin. That
    is one point of contact between two families. This puts ALL the configurations of ALL THREE
    families on one axis — book-day duty — and asks whether knowing the family adds anything once
    the duty bucket is known.

    Read it like an analysis of variance done by hand: if the spread of ΔCalmar ACROSS families
    inside a duty bucket is small next to the spread ACROSS buckets, then duty is the state
    variable of this whole family of rules and the criterion is a footnote. That is a statement
    about eight registry entries at once, and no entry so far has had the instrument to make it.
    """
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = _scores(panel)
    zs = zscore_scores(sc)

    # (duty, ΔCalmar, max weight) per configuration. maxW is carried because these rules are
    # ALWAYS 100% deployed: demoting d of N books leaves the survivors at 1/(N−d) each, so on this
    # allocator "more duty" is literally "more concentration", and the duty axis cannot be read
    # without it. Inferring that from the allocator's source would be an argument; here it is a
    # measurement, printed beside the number it explains.
    pts: Dict[str, List[Tuple[float, float, float]]] = {"#39 absolute": [], "#40 XSD rank": [],
                                                        "#43 ZSD z-score": []}

    def _add(fam: str, fl: Dict[str, List[bool]]) -> None:
        m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, fl, panel.n))
        pts[fam].append((xsd.duty(fl), m["calmar"] - base["calmar"], m["max_weight"]))

    for h in [j * 0.01 for j in range(-12, 13)]:
        for m_days in (1, 5, 20, 45):
            _add("#39 absolute", xsd.absolute_flags(panel, h, LOOKBACK, m_days))
    for k in (1, 2, 3, 4, 5):
        for m_days in (1, 2, 5, 10, 20, 45):
            _add("#40 XSD rank", xsd.rank_demotion_flags(sc, k, m_days))
    for z in (0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.8):
        for m_days in (1, 2, 5, 10, 20, 45):
            _add("#43 ZSD z-score", zscore_demotion_flags(zs, z, m_days))

    print()
    print("=" * 110)
    print("DUTY COLLAPSE — mean ΔCalmar by book-day duty bucket, per criterion family "
          f"(raw Calmar {base['calmar']:.2f})")
    print("=" * 110)
    print(f"{'duty bucket':>16s}" + "".join(f"{fam:>20s}" for fam in pts) + f"{'mean maxW':>12s}")
    bucket_means: List[List[float]] = []
    for lo, hi in buckets:
        row_means: List[float] = []
        cells = []
        ws: List[float] = []
        for fam in pts:
            sel = [(d, w) for u, d, w in pts[fam] if lo <= u < hi]
            ws.extend(w for _, w in sel)
            if sel:
                mean = sum(d for d, _ in sel) / len(sel)
                row_means.append(mean)
                cells.append(f"{mean:+8.2f} (n={len(sel):>2d})")
            else:
                cells.append(f"{'—':>15s}")
        bucket_means.append(row_means)
        wcell = f"{sum(ws)/len(ws)*100:10.1f}%" if ws else f"{'—':>11s}"
        print(f"{f'{lo*100:.0f}–{hi*100:.0f}%':>16s}" + "".join(f"{c:>20s}" for c in cells) + wcell)

    within = [max(r) - min(r) for r in bucket_means if len(r) > 1]
    across = [sum(r) / len(r) for r in bucket_means if r]
    print()
    print(f"  spread ACROSS families inside a duty bucket: max {max(within):.2f}, "
          f"mean {sum(within)/len(within):.2f}")
    print(f"  spread ACROSS duty buckets (family-averaged): {max(across) - min(across):.2f}")
    print("  If the second dominates the first, duty is the state variable and the criterion is a")
    print("  footnote — which is the strongest single reading these three entries admit.")
    print("  And the maxW column says what the duty axis IS on this allocator: these rules never")
    print("  de-risk (100% deployed always), so climbing the duty axis is climbing the")
    print(f"  CONCENTRATION axis. The project's own per-name cap for T2 is "
          f"{ecr.CONC_CAP*100:.0f}% — read the column against it before reading the ΔCalmar.")


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--idea", type=int, choices=(42, 43), default=None)
    args = ap.parse_args(argv)

    print("Ideas #42 CSDG / #43 ZSD — ADVISORY, OUTSIDE_RISKPOLICY, evidence L0 (backtest).")
    print("Capital does not move. The live track and RiskPolicy v1.0 are not touched.")

    if args.idea in (None, 42):
        idea42_csdg()
        gate_sweep()
        _train_test_prefix(idea42_csdg, [f"#40 XSD k={REF_K} M={REF_M} (ungated)",
                                         f"CSDG q={GATE_Q:.1f}",
                                         f"CONTROL static-matched (gated q={GATE_Q:.1f})"])
        ecr.leave_one_out(_csdg_loo, "CSDG-ref")
        panel = dgo.Panel()
        sc = _scores(panel)
        g, _ = _gate_for(panel)
        ecr.information_controls(panel, gated_rank_flags(sc, g, REF_K, REF_M),
                                 f"CSDG q={GATE_Q:.1f}")
        idea42_inverse()
        _train_test_prefix(idea42_inverse, ["INVERSE same"])
        ecr.leave_one_out(_inv_loo, "INVERSE-ref")

    if args.idea in (None, 43):
        idea43_zsd()
        z_sweep()
        duty_collapse()
        _train_test_prefix(idea43_zsd, [f"ZSD z={REF_Z:.1f} M={REF_M}", "#40 XSD", "#39 CDR"])
        ecr.leave_one_out(_zsd_loo, "ZSD-ref")
        panel = dgo.Panel()
        zs = zscore_scores(_scores(panel))
        ecr.information_controls(panel, zscore_demotion_flags(zs, REF_Z, REF_M),
                                 f"ZSD z={REF_Z:.1f} M={REF_M}")
    return 0


# The row LABELS of #42/#43 carry a measured quantity (the achieved gate/duty), which is the
# honest way to print them but makes them unstable keys across sub-panels — a leave-one-out
# panel has a different duty and therefore a different label. These two shims re-key the
# reference row to a stable name so `ecr.leave_one_out` / `train_test` can find it, WITHOUT
# changing any number: the row is looked up by prefix and re-labelled, never recomputed.
def _rekey(res: Dict[str, Dict[str, float]], prefix: str, name: str) -> Dict[str, Dict[str, float]]:
    for k, v in res.items():
        if k.startswith(prefix):
            out = dict(res)
            out[name] = v
            return out
    raise KeyError(f"no row starting with {prefix!r} in {sorted(res)}")


def _csdg_loo(**kw) -> Dict[str, Dict[str, float]]:
    return _rekey(idea42_csdg(**kw), f"CSDG q={GATE_Q:.1f}", "CSDG-ref")


def _inv_loo(**kw) -> Dict[str, Dict[str, float]]:
    return _rekey(idea42_inverse(**kw), "INVERSE same", "INVERSE-ref")


def _zsd_loo(**kw) -> Dict[str, Dict[str, float]]:
    return _rekey(idea43_zsd(**kw), f"ZSD z={REF_Z:.1f} M={REF_M}", "ZSD-ref")


def _train_test_prefix(idea, prefixes: Sequence[str]) -> None:
    """`ecr.train_test` for rows whose labels carry a measured duty (see `_rekey`)."""
    print()
    print("=" * 110)
    print(f"TRAIN → TEST (split {TRAIN_END}; the gate/threshold axes were SWEPT, not train-selected)")
    print("=" * 110)
    train = idea(end=TRAIN_END, segment="TRAIN", quiet=True)
    test = idea(start=TRAIN_END, segment="TEST", quiet=True)
    raw_tr = ecr._raw_metrics(dgo.Panel(None, None, TRAIN_END))
    raw_te = ecr._raw_metrics(dgo.Panel(None, TRAIN_END, None))
    print(f"raw TRAIN: APY {raw_tr['apy']*100:6.2f}%  DD {raw_tr['maxdd']*100:6.2f}%  "
          f"Calmar {raw_tr['calmar']:5.2f}   |   raw TEST: APY {raw_te['apy']*100:6.2f}%  "
          f"DD {raw_te['maxdd']*100:6.2f}%  Calmar {raw_te['calmar']:5.2f}")
    print(f"{'configuration':34s} {'trAPY':>8s} {'trCalmar':>9s} {'trΔ':>7s} "
          f"{'teAPY':>8s} {'teCalmar':>9s} {'teΔ':>7s}")
    for p in prefixes:
        a = next((v for k, v in train.items() if k.startswith(p)), None)
        b = next((v for k, v in test.items() if k.startswith(p)), None)
        if a is None or b is None:
            print(f"{p:34s}   [absent — configuration not produced on one of the segments]")
            continue
        print(f"{p:34s} {a['apy']*100:7.2f}% {a['calmar']:9.2f} {a['calmar']-raw_tr['calmar']:7.2f} "
              f"{b['apy']*100:7.2f}% {b['calmar']:9.2f} {b['calmar']-raw_te['calmar']:7.2f}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
