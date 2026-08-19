#!/usr/bin/env python3
"""Edge R&D #65 SND / #66 SWG — the DISPLACEMENT BUDGET of the published rule #40.

WHY THIS FILE EXISTS
════════════════════
#63 SXD closed the family's open question with an identity

    excess = share · spread + cov(share, spread)

and, on the way, found a term in the PUBLISHED rule #40 that nobody in #35–#64 designed:

    at M = 1 the demoted set is exactly the bottom-k, so share ≡ k/N and cov is a structural zero;
    at M = 20 a demotion OUTLIVES the day that caused it, so on many days MORE than k books are
    out, share wanders — and on the six live books that wandering term is NEGATIVE:
    −3.42 pp of a 5.43 pp excess (TEST: −2.87 of 7.47). The rule displaces MORE capital exactly
    on the days when the spread it is buying is NARROW.

#63's closing line names the follow-up verbatim: "мерить … ЗНАК члена `cov` у самого #40 — он
отрицателен и это единственное известное место, где у опубликованного правила есть бесплатная
поправка: доля растёт ровно тогда, когда спред узкий, и лечится она не новым критерием, а
нормировкой доли на число демоутённых."

This file measures that. It proposes NO new criterion, NO new lookback, NO new k or M. It varies
one knob, and only one, which the whole family has held at +∞ without ever writing it down:

    THE DISPLACEMENT BUDGET B(t) — how much capital the rule is allowed to move off equal weight
    today, as opposed to WHICH books it moves it away from.

    #40  (published)  B(t) = m(t)/N        ← "however many are flagged, take them all to zero"
    #65  SND          B(t) = k/N           ← constant by construction ⇒ cov ≡ 0 by construction
    #66  SWG          B(t) = k/N · g(t)    ← g causal, wide when the ranking is confident

    depth h(t) = min(1, B(t) · N / m(t))   ← applied to every flagged book equally
    weights    w_b = (1−h)/N for flagged; freed B(t) water-filled over eligible, cap 20 %, rest cash

At h ≡ 1 this reproduces `ecr.alloc_recycle` BIT FOR BIT (pinned by the test-suite), so #40 is a
corner of the same machine rather than a different program — the comparison isolates the budget.

TWO IDEAS, TWO DIFFERENT QUESTIONS
══════════════════════════════════
#65 SND (Share-Normalised Demotion) — NEUTRALISE. Is the −3.42 pp free money? Two mechanisms that
    both force share ≡ k/N and disagree about how:
      • SND-depth : every flagged book keeps (1−h)/N, h = k/m(t)     — "everybody a bit less out"
      • SND-count : only the k WORST-ranked of the flagged set stay out, the rest are re-admitted
                    today — "the stalest demotion pays for the newest"
    They have the same share and DIFFERENT selections, so running both separates "the size term
    was the problem" from "the M-stickiness was the problem".

#66 SWG (Spread-Width Gated displacement) — EXPLOIT. cov < 0 says the size term currently works
    against us. Can a CAUSAL signal make it work for us? The gate is the cross-sectional score gap

        gap(t) = mean(score of eligible) − mean(score of flagged)      ← causal, scores stop at t−1
        g(t)   = clip(gap(t) / median(gap over the trailing W days), 0, GMAX)

    Wide gap = the ranking is confident today = the day is worth displacing more capital into.
    The anti-rule (g → GMAX−g, i.e. displace more when the gap is NARROW) is run beside it in
    every table: a gate whose inversion is not worse is not a gate.

WHY THIS IS NOT #47 PDD
═══════════════════════
#47 measured a CONSTANT depth h and proved by identity that PDD(h) = (1−h)·raw + h·#40 — a convex
combination carrying no information. Here h is a FUNCTION OF THE DAY (of m(t), and for #66 of a
causal signal), so the affine identity does not apply — and the test-suite proves it does not, by
measuring the best-fit affine residual and requiring it to be LARGE, not by asserting it in prose.
The two facts live side by side: constant depth is nothing, state-dependent depth is something (or
is measured to be nothing, which is also an answer).

HONESTY / SCOPE
═══════════════
  • Evidence L0 — backtest over the real feed panel, NOT a live track. Every table carries its
    segment in the title ([FULL] / [TRAIN] / [TEST]), so no in-sample row can be read as an
    out-of-sample one.
  • The panel is the family's own and it is holed: 4 of 10 books are dark (#54). EVERY table is
    printed twice — all ten and the six live — and the two are never averaged.
  • The decomposition is GROSS and ARITHMETIC (mean × 365) because only an arithmetic mean is
    additive; it is NOT comparable with the compounded APY columns and is labelled `arith`.
    The turnover bill (96 bp round trip, #10/#49) is printed BESIDE it, never inside it.
  • The cov term is an accounting fact about a realised path, not a forecast. #65 removes it by
    construction; whether removing it PAYS is the measured question, and the answer may be no.
  • Read-only. Writes nothing anywhere, imports no execution code, touches neither the live track
    nor `data/` nor RiskPolicy v1.0 nor the kill-switch. IS_ADVISORY = True,
    OUTSIDE_RISKPOLICY = True. Capital does not move. No agent is deployed by this file.

Usage:
    python3 scripts/edge_displacement_budget.py               # everything
    python3 scripts/edge_displacement_budget.py --idea 65     # SND only
    python3 scripts/edge_displacement_budget.py --idea 66     # SWG only
    python3 scripts/edge_displacement_budget.py --decompose   # the #63 identity on every row
    python3 scripts/edge_displacement_budget.py --train-test  # the 2025-06-30 split
    python3 scripts/edge_displacement_budget.py --controls    # permutation / rotation / static twin
    python3 scripts/edge_displacement_budget.py --sweep       # the multiplier ladder
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, controls #38/#39)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_event_time_scoring as ets           # noqa: E402  (live/dead book census of #54)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)
import edge_score_proportional as spw           # noqa: E402  (the #63 identity itself)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K = 2                        # #40's reference k, so every row is like-for-like
REF_M = 20                       # #40's published stickiness — the source of the wandering share
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap
EPS = ecr.EPS
SEEDS = 20                       # control seeds, same count as #38/#40/#58/#59/#60/#63

GATE_WINDOW = 120                # trailing window for the gate's own median — causal, > LOOKBACK
GMAX = 2.0                       # the gate may at most double the budget; it may never exceed m/N
MULTS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)   # the ladder of constant multipliers for the sweep


# ═══════════════════════ the machine: one budget, one depth ═══════════════════════
def demotion_counts(flags: Dict[str, Sequence[bool]], books: Sequence[str], n: int) -> List[int]:
    """m(t) — how many books the state machine holds demoted on day t. The whole subject."""
    return [sum(1 for b in books if flags[b][i]) for i in range(n)]


def alloc_budgeted(books: Sequence[str], flags: Dict[str, Sequence[bool]], n: int,
                   budget: Sequence[float], cap: Optional[float] = CONC_CAP
                   ) -> Dict[str, List[float]]:
    """Displace exactly `budget[t]` of capital off equal weight, taken equally from the flagged.

    Every flagged book keeps (1−h)/N with the SAME h, so the rule stays magnitude-blind inside the
    flagged set — the selection is still #40's and only the size changes. Freed capital is split
    equally over the eligible books on top of the 1/N they already hold, clipped at `cap`; what
    does not fit inside the cap becomes CASH rather than a silent breach, exactly as `ecr._waterfill`
    decides it. If nothing is eligible, everything is cash — fail-CLOSED, the one state where the
    rule must not invent a destination.

    h is clipped at 1: a budget larger than the flagged set is a request to short a book we do not
    short, and inventing exposure out of a cap on the other side would be a different rule wearing
    this one's name. When that clip binds it is REPORTED (`clip_days`), not silently absorbed.

    At budget[t] ≡ m(t)/N this returns `ecr.alloc_recycle(books, flags, n, cap)` bit for bit; the
    test-suite pins that identity, which is what makes #40 a corner of this machine and not a
    neighbour of it.
    """
    if len(budget) != n:
        raise ValueError("budget must be one number per day — refusing to recycle a short series")
    nb = len(books)
    if nb == 0:
        raise ValueError("no books — a displacement rule over an empty panel is not a rule")
    neutral = 1.0 / nb
    out: Dict[str, List[float]] = {b: [0.0] * n for b in books}
    for i in range(n):
        flagged = [b for b in books if flags[b][i]]
        eligible = [b for b in books if not flags[b][i]]
        if not flagged:
            for b in books:
                out[b][i] = min(neutral, cap) if cap is not None else neutral
            continue
        want = max(0.0, float(budget[i]))
        avail = len(flagged) * neutral
        h = 1.0 if avail <= EPS else min(1.0, want / avail)
        freed = h * avail
        for b in flagged:
            out[b][i] = neutral * (1.0 - h)
        if not eligible:
            continue                          # freed capital is cash; nothing eligible to hold it
        per = freed / len(eligible)
        room = float("inf") if cap is None else max(0.0, cap - neutral)
        take = min(per, room)
        for b in eligible:
            out[b][i] = neutral + take
    return out


def clip_days(flags: Dict[str, Sequence[bool]], books: Sequence[str], n: int,
              budget: Sequence[float]) -> int:
    """How often the requested budget exceeded the flagged set — reported, never hidden."""
    neutral = 1.0 / len(books)
    m = demotion_counts(flags, books, n)
    return sum(1 for i in range(n) if budget[i] > m[i] * neutral + EPS)


# ═══════════════════════════ #65 — the two normalisations ═══════════════════════════
def snd_depth_weights(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                      m_days: int = REF_M, cap: Optional[float] = CONC_CAP,
                      mult: float = 1.0) -> Dict[str, List[float]]:
    """SND-depth — the budget is the CONSTANT k/N (× mult); every flagged book goes partly out."""
    flags = xsd.rank_demotion_flags(scores, k, m_days)
    budget = [mult * k / len(panel.books)] * panel.n
    return alloc_budgeted(panel.books, flags, panel.n, budget, cap)


def worst_k_of_flagged(scores: "xsd.Scores", flags: Dict[str, List[bool]], k: int
                       ) -> Dict[str, List[bool]]:
    """SND-count — keep only the k WORST-ranked of today's flagged set demoted; re-admit the rest.

    Same share as SND-depth (exactly k books out of N, so k/N displaced), a different answer to
    "who". A book whose score is unmeasurable today cannot be ranked and therefore cannot be
    re-admitted on an unmeasured state: it keeps whatever the state machine already said, which is
    the fail-CLOSED direction (staying out is the conservative side of this rule). Ties break by
    book name, so the report is reproducible rather than dict-ordered.
    """
    books = sorted(flags)
    n = len(flags[books[0]]) if books else 0
    out: Dict[str, List[bool]] = {b: [False] * n for b in books}
    for i in range(n):
        flagged = [b for b in books if flags[b][i]]
        if len(flagged) <= k:
            for b in flagged:
                out[b][i] = True
            continue
        rankable = [b for b in flagged if scores[b][i] is not None]
        unrankable = [b for b in flagged if scores[b][i] is None]
        ordered = sorted(rankable, key=lambda b: (float(scores[b][i]), b))
        keep = set(unrankable) | set(ordered[:max(0, k - len(unrankable))])
        for b in keep:
            out[b][i] = True
    return out


def snd_count_weights(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                      m_days: int = REF_M, cap: Optional[float] = CONC_CAP
                      ) -> Dict[str, List[float]]:
    """SND-count — the flagged set itself is trimmed back to k, then #40's own allocator runs."""
    flags = xsd.rank_demotion_flags(scores, k, m_days)
    trimmed = worst_k_of_flagged(scores, flags, k)
    return ecr.alloc_recycle(panel.books, trimmed, panel.n, cap=cap)


# ═══════════════════════════ #66 — the causal width gate ═══════════════════════════
def score_gap(scores: "xsd.Scores", flags: Dict[str, List[bool]]) -> List[Optional[float]]:
    """gap(t) = mean(score | eligible) − mean(score | flagged), on the rankable books only.

    CAUSAL: `scores` is the family's trailing drift, which stops at t−1 by construction (#37/#40),
    and this function reads nothing else. None on a day where either side has no rankable member —
    a gap between a set and an empty set is not a small number, it is undefined, and the caller
    turns None into "hold the neutral budget", not into zero.
    """
    books = sorted(scores)
    n = len(scores[books[0]]) if books else 0
    out: List[Optional[float]] = []
    for i in range(n):
        hi = [float(scores[b][i]) for b in books if not flags[b][i] and scores[b][i] is not None]
        lo = [float(scores[b][i]) for b in books if flags[b][i] and scores[b][i] is not None]
        out.append(None if not hi or not lo else sum(hi) / len(hi) - sum(lo) / len(lo))
    return out


def _trailing_median(xs: Sequence[Optional[float]], i: int, window: int) -> Optional[float]:
    """Median of the last `window` DEFINED values strictly before i. Never reads i or later."""
    hist = [x for x in xs[max(0, i - window):i] if x is not None]
    if len(hist) < max(10, window // 4):
        return None                      # too little history to normalise against — refuse
    s = sorted(hist)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else 0.5 * (s[mid - 1] + s[mid])


def gate_multipliers(gap: Sequence[Optional[float]], window: int = GATE_WINDOW,
                     gmax: float = GMAX, invert: bool = False) -> List[float]:
    """g(t) ∈ [0, gmax] — how many k/N units of capital today's confidence is worth.

    Neutral (g = 1, i.e. exactly the SND budget) whenever the gap or its own trailing median is
    undefined or non-positive: an unmeasured confidence is not a reason to size up OR down, and
    falling back to the constant budget keeps the refusal inside the same family of rules instead
    of teleporting to raw. `invert=True` is the REFUTING control — it spends more on the days the
    ranking is least confident. It is never a proposed rule; it exists so that "the gate carries
    information" is a measured claim and not a hope.
    """
    out: List[float] = []
    for i, g in enumerate(gap):
        med = _trailing_median(gap, i, window)
        if g is None or med is None or med <= EPS or g <= 0.0:
            out.append(1.0)
            continue
        val = max(0.0, min(gmax, g / med))
        out.append(max(0.0, gmax - val) if invert else val)
    return out


def swg_weights(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K, m_days: int = REF_M,
                cap: Optional[float] = CONC_CAP, window: int = GATE_WINDOW,
                gmax: float = GMAX, invert: bool = False) -> Dict[str, List[float]]:
    """SWG — the same selection as #40, sized by a causal read of how confident the ranking is."""
    flags = xsd.rank_demotion_flags(scores, k, m_days)
    g = gate_multipliers(score_gap(scores, flags), window, gmax, invert)
    base = k / len(panel.books)
    return alloc_budgeted(panel.books, flags, panel.n, [base * x for x in g], cap)


# ═══════════════════════════════ report bodies ═══════════════════════════════
def _rows(panel: "dgo.Panel", scores: "xsd.Scores", k: int, cap: Optional[float],
          full_controls: bool) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """Every table in this file prints the SAME rows, so no configuration gets a private baseline."""
    pub = spw.binary_weights(panel, scores, k, REF_M, cap)
    rows: List[Tuple[str, Dict[str, List[float]], float]] = [
        (f"#40 XSD k={k} M={REF_M} [published]", pub, 0.0),
        (f"#40 XSD k={k} M=1  [cov≡0 corner]", spw.binary_weights(panel, scores, k, 1, cap), 0.0),
        ("#65 SND-depth  (B=k/N)", snd_depth_weights(panel, scores, k, REF_M, cap), 0.0),
        ("#65 SND-count  (worst-k out)", snd_count_weights(panel, scores, k, REF_M, cap), 0.0),
        ("#66 SWG gate   (B=k/N·g)", swg_weights(panel, scores, k, REF_M, cap), 0.0),
    ]
    if full_controls:
        rows += [
            ("  CONTROL SWG anti-gate (invert)",
             swg_weights(panel, scores, k, REF_M, cap, invert=True), 0.0),
            ("  CONTROL static twin of #40", ecr.alloc_static_matched(pub), 0.0),
            ("  CONTROL static twin of SND",
             ecr.alloc_static_matched(snd_depth_weights(panel, scores, k, REF_M, cap)), 0.0),
        ]
    return rows


def idea65_snd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False, k: int = REF_K,
               cap: Optional[float] = CONC_CAP) -> Dict[str, Dict[str, float]]:
    """Ideas #65/#66 — does the displacement BUDGET, held constant or gated, beat #40's +∞?"""
    panel = dgo.Panel(subset, start, end)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    rows = _rows(panel, scores, k, cap, full_controls=not quiet)
    out = xsd._report(f"IDEAS #65 SND / #66 SWG — displacement budget [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        flags = xsd.rank_demotion_flags(scores, k, REF_M)
        m = demotion_counts(flags, panel.books, panel.n)
        over = sum(1 for x in m if x > k)
        print("-" * 110)
        print(f"m(t) — books held demoted: mean {sum(m)/len(m):.2f}, max {max(m)}, "
              f"> k on {over}/{panel.n} days ({100.0*over/panel.n:.1f}%). "
              f"That excess IS the unnamed size term of #63.")
        g = gate_multipliers(score_gap(scores, flags))
        neutral = sum(1 for x in g if abs(x - 1.0) <= EPS)
        base = k / len(panel.books)
        print(f"gate g(t): mean {sum(g)/len(g):.2f}, neutral (refused/undefined) on "
              f"{neutral}/{panel.n} days; SWG budget clipped by m(t)/N on "
              f"{clip_days(flags, panel.books, panel.n, [base*x for x in g])} days.")
    return out


# ═══════════════════════════ the #63 identity on every row ═══════════════════════════
def decompose_table(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
                    cap: Optional[float] = CONC_CAP, start: Optional[str] = None,
                    end: Optional[str] = None, segment: str = "FULL") -> Dict[str, Dict[str, float]]:
    """#63's identity applied to the new rows — the number this whole file was built to move.

    All columns are ARITHMETIC %/year (mean × 365) and GROSS, per #63's convention, because only
    an arithmetic mean is additive and the point is that the terms add up. `resid` is printed, not
    asserted away: an identity whose residual is never shown is a claim.
    """
    panel = dgo.Panel(subset, start, end)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    rows = _rows(panel, scores, k, cap, full_controls=False)
    print()
    print("=" * 110)
    print(f"#63 DECOMPOSITION of the new rows [{segment}] — {label}  ·  {panel.n} days  ·  "
          f"{len(panel.books)} books  (arith %/yr, GROSS)")
    print("=" * 110)
    print(f"{'rule':34s} {'exc(all)':>9s} {'exc(act)':>9s} {'share':>7s} {'spread':>8s} "
          f"{'cov':>8s} {'tilt':>8s} {'timing':>8s} {'resid':>10s}")
    out: Dict[str, Dict[str, float]] = {}
    for name, w, _ in rows:
        d = spw.decompose(panel, w)
        out[name.strip()] = d
        print(f"{name:34s} {d['excess_mean']*365*100:8.2f}% {d['excess_live_mean']*365*100:8.2f}% "
              f"{d['share_mean']*100:6.1f}% "
              f"{d['spread_mean']*365*100:7.2f}% {d['cov_share_spread']*365*100:7.2f}% "
              f"{d['tilt_mean']*365*100:7.2f}% {d['timing_mean']*365*100:7.2f}% "
              f"{d['resid_1']*365*100:9.1e}")
    print("-" * 110)
    print("The identity closes on exc(act) — the ACTIVE days, those with share > 0. exc(all) averages")
    print("the flat days in as exact zeros and is the number the APY columns are built from; the two")
    print("are printed side by side so neither can be quoted as the other (#63's convention).")
    print("cov ≡ 0 for #40 M=1, #65 SND-depth and #65 SND-count BY CONSTRUCTION (constant share).")
    print("A non-zero cov on those rows would mean the machine is not doing what it says.")
    return out


# ═══════════════════════════════ controls ═══════════════════════════════
def controls(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
             cap: Optional[float] = CONC_CAP) -> None:
    """Permutation and time-rotation of the SAME weight paths — #38's controls, unchanged.

    Permutation destroys WHICH book a path belongs to; rotation destroys WHEN. Deployment,
    turnover and the character of the allocation survive both. A rule that scores as well against
    its own scrambles is not selecting anything.
    """
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"CONTROLS — {label}  ·  {panel.n} days  ·  {len(panel.books)} books  ·  {SEEDS} seeds")
    print("=" * 110)
    named = [
        (f"#40 XSD k={k} M={REF_M}", spw.binary_weights(panel, scores, k, REF_M, cap)),
        ("#65 SND-depth", snd_depth_weights(panel, scores, k, REF_M, cap)),
        ("#65 SND-count", snd_count_weights(panel, scores, k, REF_M, cap)),
        ("#66 SWG gate", swg_weights(panel, scores, k, REF_M, cap)),
    ]
    print(f"{'rule':24s} {'Calmar':>8s} {'permuted mean':>15s} {'p(perm≥real)':>13s} "
          f"{'rot+91':>8s} {'rot+182':>9s}")
    for name, w in named:
        real = ecr.portfolio_metrics(panel, w)["calmar"]
        perms = [ecr.portfolio_metrics(
            panel, spw.permuted_weights(w, panel.books, s))["calmar"] for s in range(SEEDS)]
        beat = sum(1 for c in perms if c >= real)
        rots = [ecr.portfolio_metrics(
            panel, spw.shifted_weights(w, panel.books, s))["calmar"] for s in (91, 182)]
        print(f"{name:24s} {real:8.2f} {sum(perms)/len(perms):15.2f} "
              f"{(beat + 1) / (SEEDS + 1):13.3f} {rots[0]:8.2f} {rots[1]:9.2f}")
    print("-" * 110)
    print(f"raw equal weight Calmar {base['calmar']:.2f}.  p is the (beat+1)/(seeds+1) convention")
    print("of #38/#40/#58 — with 20 seeds the smallest reportable p is 0.048, and it is a floor,")
    print("not a significance claim.")


# ═══════════════════════════════ the multiplier ladder ═══════════════════════════════
def sweep(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
          cap: Optional[float] = CONC_CAP, mults: Sequence[float] = MULTS,
          start: Optional[str] = None, end: Optional[str] = None,
          segment: str = "FULL") -> None:
    """Is k/N a plateau or a lottery ticket? The whole constant-budget axis, in one table.

    Both ends are known before the run: mult → 0 must converge on raw equal weight, and a mult
    large enough to exceed m(t)/N every day must converge on #40. A ladder whose ends do not land
    where the machine says they must is a broken machine, not a discovery — the test-suite pins
    both corners.

    Run per SEGMENT as well as on the whole sample, because "the ladder has an interior optimum"
    and "the ladder has an interior optimum IN SAMPLE" are different claims and only the second
    one is cheap to produce.
    """
    panel = dgo.Panel(subset, start, end)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    base = ecr._raw_metrics(panel)
    flags = xsd.rank_demotion_flags(scores, k, REF_M)
    print()
    print("=" * 110)
    print(f"SWEEP of the constant displacement budget [{segment}] — {label}  ·  {panel.n} days  ·  "
          f"{len(panel.books)} books  ·  raw Calmar {base['calmar']:.2f}")
    print("=" * 110)
    print(f"{'B = mult · k/N':22s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔCal':>7s} "
          f"{'turn/yr':>8s} {'netAPY':>8s} {'cov(arith)':>11s} {'clip days':>10s}")
    for mult in mults:
        w = snd_depth_weights(panel, scores, k, REF_M, cap, mult=mult)
        m = ecr.portfolio_metrics(panel, w)
        d = spw.decompose(panel, w)
        cl = clip_days(flags, panel.books, panel.n, [mult * k / len(panel.books)] * panel.n)
        print(f"mult={mult:<17.2f} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f} "
              f"{m['calmar']-base['calmar']:7.2f} {m['turnover_yr']:8.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {d['cov_share_spread']*365*100:10.2f}% "
              f"{cl:10d}")
    pub = ecr.portfolio_metrics(panel, spw.binary_weights(panel, scores, k, REF_M, cap))
    print(f"{'#40 (mult = ∞)':22s} {pub['apy']*100:7.2f}% {pub['maxdd']*100:7.2f}% "
          f"{pub['calmar']:8.2f} {pub['calmar']-base['calmar']:7.2f} {pub['turnover_yr']:8.2f} "
          f"{pub['net_apy_after_cost']*100:7.2f}%")


# ═══════════════════════════════ train / test ═══════════════════════════════
def train_test(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
               cap: Optional[float] = CONC_CAP) -> None:
    """The registry's own split. No parameter in this file was chosen by looking at TEST."""
    tr = idea65_snd(subset, label, end=TRAIN_END, segment="TRAIN", quiet=True, k=k, cap=cap)
    te = idea65_snd(subset, label, start=TRAIN_END, segment="TEST", quiet=True, k=k, cap=cap)
    raw_tr = ecr._raw_metrics(dgo.Panel(subset, None, TRAIN_END))
    raw_te = ecr._raw_metrics(dgo.Panel(subset, TRAIN_END, None))
    print()
    print("=" * 110)
    print(f"TRAIN → TEST (split {TRAIN_END}) — {label}")
    print("=" * 110)
    print(f"raw TRAIN Calmar {raw_tr['calmar']:.2f} (APY {raw_tr['apy']*100:.2f}%)   ·   "
          f"raw TEST Calmar {raw_te['calmar']:.2f} (APY {raw_te['apy']*100:.2f}%)")
    print(f"{'rule':34s} {'trAPY':>8s} {'trCal':>7s} {'teAPY':>8s} {'teCal':>7s} "
          f"{'teΔCal':>7s} {'teNet':>8s}")
    for name in tr:
        if name not in te:
            continue
        a, b = tr[name], te[name]
        print(f"{name:34s} {a['apy']*100:7.2f}% {a['calmar']:7.2f} {b['apy']*100:7.2f}% "
              f"{b['calmar']:7.2f} {b['calmar']-raw_te['calmar']:7.2f} "
              f"{b['net_apy_after_cost']*100:7.2f}%")


# ═══════════════════════════════ affine check (vs #47) ═══════════════════════════════
def affine_residual(panel: "dgo.Panel", scores: "xsd.Scores", weights: Dict[str, List[float]],
                    k: int = REF_K, cap: Optional[float] = CONC_CAP) -> Dict[str, float]:
    """Best-fit (1−a)·raw + a·#40 against `weights`, and the residual it cannot explain.

    #47 proved a CONSTANT depth is exactly such a combination (residual ~1e−17). If a
    state-dependent budget were also one, this file would be re-deriving #47 under a new name.
    The residual is returned so the reader can see which of the two it is.
    """
    books = panel.books
    n = panel.n
    neutral = 1.0 / len(books)
    pub = spw.binary_weights(panel, scores, k, REF_M, cap)
    num = den = 0.0
    for b in books:
        for i in range(n):
            d = pub[b][i] - neutral
            num += d * (weights[b][i] - neutral)
            den += d * d
    a = num / den if den > EPS else 0.0
    worst = 0.0
    sq = 0.0
    for b in books:
        for i in range(n):
            fit = neutral + a * (pub[b][i] - neutral)
            e = abs(weights[b][i] - fit)
            worst = max(worst, e)
            sq += e * e
    return {"alpha": a, "max_abs": worst, "rms": math.sqrt(sq / (len(books) * n))}


def affine_table(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
                 cap: Optional[float] = CONC_CAP) -> None:
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    print()
    print("=" * 110)
    print(f"IS THIS #47 IN DISGUISE? best-fit (1−a)·raw + a·#40 — {label}")
    print("=" * 110)
    print(f"{'rule':34s} {'alpha':>8s} {'max|resid|':>12s} {'rms resid':>12s}")
    named = [
        ("#47 PDD constant depth h=0.5",
         {b: [0.5 * (1.0 / len(panel.books)) + 0.5 * v
              for v in spw.binary_weights(panel, scores, k, REF_M, cap)[b]]
          for b in panel.books}),
        ("#65 SND-depth", snd_depth_weights(panel, scores, k, REF_M, cap)),
        ("#65 SND-count", snd_count_weights(panel, scores, k, REF_M, cap)),
        ("#66 SWG gate", swg_weights(panel, scores, k, REF_M, cap)),
    ]
    for name, w in named:
        r = affine_residual(panel, scores, w, k, cap)
        print(f"{name:34s} {r['alpha']:8.3f} {r['max_abs']:12.2e} {r['rms']:12.2e}")
    print("-" * 110)
    print("#47's row is the positive control: a CONSTANT depth is an exact convex combination and")
    print("its residual must be machine zero. A state-dependent budget that is NOT #47 must not be.")


# ═══════════════════════════════ entry point ═══════════════════════════════
def _panels() -> List[Tuple[Optional[Sequence[str]], str]]:
    """Both panels, always, never averaged — the 4 dark books of #54 are a property of the data."""
    live = ets.live_books(dgo.Panel())
    return [(None, "all 10 real books"), (live, f"{len(live)} live books (#54)")]


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Edge R&D #65 SND / #66 SWG — displacement budget. Advisory, read-only.")
    ap.add_argument("--idea", type=int, choices=(65, 66), default=None)
    ap.add_argument("--decompose", action="store_true")
    ap.add_argument("--train-test", action="store_true")
    ap.add_argument("--controls", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--affine", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument("-k", type=int, default=REF_K)
    args = ap.parse_args(argv)

    panels = _panels()
    if args.live_only:
        panels = panels[1:]
    picked = any((args.decompose, args.train_test, args.controls, args.sweep, args.affine))

    for subset, label in panels:
        if not picked or args.idea is not None:
            idea65_snd(subset, label, k=args.k)
        if args.decompose or not picked:
            decompose_table(subset, label, k=args.k)
            decompose_table(subset, label, k=args.k, end=TRAIN_END, segment="TRAIN")
            decompose_table(subset, label, k=args.k, start=TRAIN_END, segment="TEST")
        if args.affine or not picked:
            affine_table(subset, label, k=args.k)
        if args.sweep or not picked:
            sweep(subset, label, k=args.k)
            sweep(subset, label, k=args.k, end=TRAIN_END, segment="TRAIN")
            sweep(subset, label, k=args.k, start=TRAIN_END, segment="TEST")
        if args.train_test or not picked:
            train_test(subset, label, k=args.k)
        if args.controls or not picked:
            controls(subset, label, k=args.k)

    print()
    print("Evidence L0 (backtest over the real feed panel, NOT live). IS_ADVISORY=True, "
          "OUTSIDE_RISKPOLICY=True.")
    print("Nothing was written: no file under data/, no execution import, no capital moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
