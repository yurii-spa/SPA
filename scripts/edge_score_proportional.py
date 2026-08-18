#!/usr/bin/env python3
"""Edge R&D — registry ideas #62 (SPW) and #63 (SXD): sizing by MAGNITUDE, and the exact
decomposition «portfolio = spread × share» that #61 named as an open question and refused to fake.

WHERE THIS COMES FROM — two sentences of #61, written down verbatim as the next step
  #61 RPH closed the reserve #59 found ("roughly four times more income lies in the panel") with a
  negative: out of sample, at the horizons a sticky machine can act on (h ≥ 20), the causal rank
  carries no information about the forward spread (0.45 / 0.23 bp/day on 10 books, −0.94 / −1.06 on
  the 6 live ones). But the SAME entry printed a second measurement that pointed the opposite way:

      "on the live panel at h=1 the causal set is guessed exactly as well as by a CONSTANT list
       (47.7 = 47.7), and yet the rule separates FIVE TIMES more money (16.27 against 3.02 bp/day)
       — the information is in the MAGNITUDE, not in the identity of the book."

  and then wrote the two remaining honest levers down:

      "(2) size by MAGNITUDE instead of membership in a set — a weight as a function of the score,
       not a binary flag. Important boundary: #47 PDD already closed SCALAR depth (partial demotion
       is identically a mixture of «panel + #40»), but a weight VECTOR proportional to the score is
       NOT covered by that identity — and it must be measured against the ceiling of #59 and the
       phase band of #60."

  and, in point 6, refused to close a tension with a story:

      "on TEST the forward spread at h=20/60 is ≈ 0, while a portfolio built on THAT SAME ranking
       gives teΔ +6.32 there. … the full DECOMPOSITION «portfolio = spread × share» is NOT done
       here, and I will not pass consistency off as an explanation: it is a stated open question."

  This file answers both, in that order. #62 is the hypothesis; #63 is the identity that says what
  any answer to it can possibly mean.

──────────────────────────────────────────────────────────────────────────────────────────────────
IDEA #62 — SPW: Score-Proportional Weighting   ("the flag is the cheapest possible lossy encoding")
──────────────────────────────────────────────────────────────────────────────────────────────────
  Every entry from #37 to #61 has compressed the criterion into ONE BIT per book per day: in the
  bottom-k, or not. A book that is worst by a hair and a book that is worst by a mile produce the
  identical weight of zero; a book ranked third-worst out of ten and one ranked best produce the
  identical weight of 1/(N−k). #61 measured, on the live panel, that this bit is the wrong summary:
  membership is guessed no better than by a fixed list, while the MONEY separates fivefold.

  SPW replaces the bit with the number. On each day the causal scores of the rankable books are
  standardised across the panel (zero mean, unit dispersion — so λ means the same thing on a calm
  day and a violent one), and the weight is a monotone function of that standardised score:

      linear   φ(z) = max(0, 1 + λ·z)      the tilt with a floor: a book more than 1/λ dispersions
                                           below the field falls out entirely, and that is the only
                                           way SPW can ever set a weight to zero
      softmax  φ(z) = exp(λ·z)             never exactly zero; the cap does all the limiting
      rank     φ(u) = max(0, 1 + λ·u)      u = the book's ORDER, standardised the same way

  `rank` is the load-bearing control of this entry and not a variant: it receives the identical
  tilt budget through the identical machinery, but sees only WHO is above WHOM — every magnitude is
  destroyed by construction. So the comparison linear-vs-rank is exactly #61's claim, made
  falsifiable. If they tie, the magnitude is decoration and the family's one bit was never the
  binding constraint; if linear wins, #61's sentence has an implementation; if rank wins, the
  magnitudes are noise the ordering was already filtering out.

  λ = 0 is an IDENTITY, not an approximation: φ ≡ 1 for every book, so SPW at λ=0 is the raw
  equal-weight panel cell for cell — the same anchoring discipline #60 used with the published
  corner. λ < 0 is the sign-flipped anti-rule (tilt TOWARD the worst books), never a proposal.

  Inherited without re-tuning, exactly as #59/#60/#61 inherited them: the panel and its 852-day
  axis (#32), the criterion (drift, L=60, #37/#39), the reference k=2 (#40), the concentration cap
  0.20 (#38/#46), the 96 bp round-trip cost model (#10), the train/test split 2025-06-30 (#38), and
  the live-book census (#54). The only new axis is λ, and it is shown as a full sweep rather than as
  a chosen cell — #47's rule: a cell picked after looking is a post-hoc cell, and the sole defence
  against reading one is to print all of them.

  Three outcomes, written down BEFORE the numbers:

    A. some λ beats the published binary corner on netAPY AND raises capture against the SAME #59
       ceiling, and `linear` beats `rank` ⇒ the magnitude is real and the one-bit encoding was the
       constraint.
    B. the sweep tracks the binary rows, or `linear` ties `rank` ⇒ the bit was a sufficient
       statistic; #61's "information is in the magnitude" is true of the SPREAD and false of the
       PORTFOLIO, and the difference is the turnover bill.
    C. the sweep is worse everywhere ⇒ continuous weights buy their sensitivity with churn, and the
       flag's brutality was doing risk management nobody had named.

──────────────────────────────────────────────────────────────────────────────────────────────────
IDEA #63 — SXD: Spread × Share Decomposition   ("what a portfolio can possibly be made of")
──────────────────────────────────────────────────────────────────────────────────────────────────
  Take any weight map w and compare it with the equal-weight panel. Then, with no assumptions at
  all about how w was produced:

      excess(t) := R_pf(t) − R_eq(t) = Σ_b (w_b(t) − 1/N)·r_b(t)

  Define share(t) := Σ_b max(0, 1/N − w_b(t)) — the capital actually displaced from equal weight on
  that day — and spread(t) := excess(t)/share(t) where share > 0. Then excess = share × spread
  identically, and over the sample

      mean(excess) = mean(share)·mean(spread) + cov(share, spread)

  which is the decomposition #61 asked for, with its third term named. The three numbers answer
  three different questions and the registry has been conflating them since #37:

    • mean(spread) — is there anything to harvest per unit of capital moved?
    • mean(share)  — how much capital does this FORM allow us to move?
    • cov          — does the rule move MORE capital on the days the spread is large? This is the
      entire economic case for a continuous weight, and no entry of this family has ever measured
      it. A family that has only ever measured mean(spread) has been reporting one third of an
      identity.

  And measuring it corrects a claim I made before running it. For the DAILY binary form (M=1)
  exactly k books are out every day, so share ≡ k/N is a constant and cov ≡ 0 identically — the
  term is structurally absent, as expected. But the family's PUBLISHED form is M=20, and there the
  demoted set may be LARGER than k (a book stays out until it assembles M good days), so share
  varies and cov is not zero at all: it is an unnamed sizing term that nobody chose, and on the
  live panel it is NEGATIVE. The rule that the registry has run since #40 displaces more capital
  on the days the spread is narrow. Both facts are pinned by the test-suite, in both directions.

  Second decomposition, equally exact, and the one that convicts: split the same excess into a
  STANDING TILT and TIMING, w_b(t) = w̄_b + (w_b(t) − w̄_b):

      excess = Σ_b (w̄_b − 1/N)·r_b(t)  +  Σ_b (w_b(t) − w̄_b)·r_b(t)
               └──── tilt ────┘            └──── timing ────┘

  The tilt column is what `alloc_static_matched` holds for free with zero turnover — the control
  that convicted #55's cash sleeve and #58's selector. Printing it INSIDE the identity means the
  verdict is arithmetic rather than a comparison of two report rows.

  And the tie back to #61 is a POSITIVE CONTROL, not a remark: for the uncapped binary rule the
  share is exactly k/N and the spread is exactly the h=1 quantity `rank_agreement` prints. If the
  two agree to floating-point, #61's spread table and every portfolio row of this family are the
  same measurement in different units — which is what makes the h=20 result of #61 read correctly:
  a daily-rebalanced portfolio consumes the ONE-DAY spread every day and never once consumes the
  twenty-day spread that #61 found to be zero. The test-suite pins this agreement.

HONESTY / SCOPE (registry rules — non-negotiable)
  • Forward scores and the oracle are LOOK-AHEAD BY CONSTRUCTION, labelled `[LOOK-AHEAD]` on every
    row, and are measuring rods — never rules. The causal side never reads a future return, and the
    test-suite pins that with a mutation control in both directions.
  • The decomposition is GROSS. Costs are stated beside it and never inside it: a decomposition
    that quietly nets a turnover bill out of one of its three terms would be an argument wearing an
    identity's clothes. netAPY after the 96 bp round-trip model is printed in every portfolio table.
  • Annualisation of the decomposition is ARITHMETIC (mean × 365), because only an arithmetic mean
    is additive and the whole point here is that the terms add up. It is therefore NOT comparable
    with the compounded APY columns, and is labelled `arith` wherever it appears.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0 nor the kill-switch thresholds. Evidence L0 (backtest on real feed
    history, NOT live). IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.
  • The panel is regenerated nightly, so numbers reproduce only against the run date, and the
    4-of-10 dead books of #54 are a property of the data pipeline: every table is printed twice,
    once on all 10 books and once on the 6 live ones, and the two are never averaged.

Usage:
    python3 scripts/edge_score_proportional.py                 # everything
    python3 scripts/edge_score_proportional.py --idea 62       # SPW only
    python3 scripts/edge_score_proportional.py --idea 63       # SXD decomposition only
    python3 scripts/edge_score_proportional.py --sweep         # the λ × form grid
    python3 scripts/edge_score_proportional.py --ceiling       # capture against #59's ceiling
    python3 scripts/edge_score_proportional.py --controls      # permutation / rotation / static twin
    python3 scripts/edge_score_proportional.py --train-test    # the 2025-06-30 split
    python3 scripts/edge_score_proportional.py --live-only     # the 6 live books of #54
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
import edge_criterion_choice as ecc             # noqa: E402  (oracle + capture of #59)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40)
import edge_decision_hold as edh                # noqa: E402  (the four-knob machine of #60/#61)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_event_time_scoring as ets           # noqa: E402  (live/dead book census of #54)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K = 2                        # #40's reference k, so every binary row is like-for-like
REF_M = 20                       # #40's published stickiness
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap
EPS = ecr.EPS
SEEDS = 20                       # control seeds, same count as #38/#40/#58/#59/#60

FORMS = ("linear", "rank", "softmax")
LAMBDAS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)
EXP_CLIP = 50.0                  # softmax exponent clip — an overflow is not a portfolio


# ═══════════════════════════ #62 — the weight map ═══════════════════════════
def _standardise(values: Sequence[float]) -> Optional[List[float]]:
    """Zero mean, unit population dispersion — or None when there is no dispersion to divide by.

    Returning None rather than zeros is the same refusal `drift_scores` makes for an unmeasured
    window: a field in which every book scores identically has no ranking, and a rule that tilted
    anyway would be tilting on floating-point dust. The caller turns None into "hold equal weight
    today", which is the fail-CLOSED destination — not cash, because refusing to rank is not a
    reason to stop being invested in a panel we already hold.
    """
    m = len(values)
    if m < 2:
        return None
    mu = sum(values) / m
    var = sum((v - mu) ** 2 for v in values) / m
    if var <= EPS:
        return None
    sd = math.sqrt(var)
    return [(v - mu) / sd for v in values]


def _shape(z: float, lam: float, form: str) -> float:
    """φ — the non-negative shape function. Never negative, never NaN, never an overflow."""
    if form in ("linear", "rank"):
        return max(0.0, 1.0 + lam * z)
    if form == "softmax":
        return math.exp(max(-EXP_CLIP, min(EXP_CLIP, lam * z)))
    raise ValueError(f"unknown weight form {form!r} — refusing to invent a shape")


def _cap_fill(phi: Dict[str, float], budget: float,
              cap: Optional[float]) -> Dict[str, float]:
    """Split `budget` in proportion to φ, clipping each name at `cap` and re-spreading the excess.

    Capital that cannot be placed inside the cap becomes CASH rather than a silent breach — the
    identical convention as `ecr._waterfill`, which this generalises from equal shares to
    proportional ones (φ ≡ 1 reproduces it exactly). Books with φ = 0 receive nothing and are not
    re-entered: the shape function already said they are out.
    """
    if budget <= EPS:
        return {}
    if cap is not None and cap <= 0.0:
        raise ValueError("cap must be positive — a zero cap is not an allocation rule")
    free = [b for b in sorted(phi) if phi[b] > 0.0]
    out: Dict[str, float] = {}
    while free and budget > EPS:
        total = sum(phi[b] for b in free)
        if total <= EPS:
            break
        prop = {b: budget * phi[b] / total for b in free}
        if cap is None:
            out.update(prop)
            budget = 0.0
            break
        over = [b for b in free if prop[b] > cap + EPS]
        if not over:
            for b in free:
                out[b] = out.get(b, 0.0) + prop[b]
            budget = 0.0
            break
        for b in over:
            out[b] = cap
            budget -= cap
            free.remove(b)
    return out


def spw_weights(panel: "dgo.Panel", scores: "xsd.Scores", lam: float,
                form: str = "linear", cap: Optional[float] = CONC_CAP) -> Dict[str, List[float]]:
    """Weights as a monotone function of the standardised causal score — #62's whole proposal.

    Per day:
      • books whose score is None are UNRANKABLE and keep the neutral share 1/N. They are not
        demoted for being unmeasured (#40's rule, kept: an unmeasured drift is not a low drift) and
        they are not sized on an unmeasured state either — during the L-day warm-up this makes SPW
        identical to the equal-weight panel, which is exactly what the binary rows do there too, so
        the comparison is not contaminated by a different warm-up.
      • the rankable books share the remaining |R|/N of the book, split ∝ φ(standardised score) and
        capped.
      • no dispersion (or fewer than two rankable books) ⇒ equal weight today. Fail-CLOSED.

    The neutral share itself is clipped at `cap`: on a panel so narrow that 1/N already breaches the
    concentration limit, the residue becomes cash rather than a breach. Without this the fail-CLOSED
    path — the one taken exactly when the rule has the least information — would be the only place
    in the file capable of printing a weight the project's own limit forbids.

    λ = 0 returns the equal-weight panel cell for cell, for every form and every cap ≥ 1/N (which is
    every real configuration: 10 or 6 books against a 0.20 cap). That is an identity and the
    test-suite pins it; it is what makes the λ axis readable as a departure from the registry's
    baseline rather than as a different portfolio that happens to be nearby.

    λ < 0 is the anti-rule (weight rises as the score falls). It is a CONTROL and is never proposed.
    """
    if form not in FORMS:
        raise ValueError(f"unknown weight form {form!r} — refusing to invent a shape")
    if not math.isfinite(lam):
        raise ValueError("lambda must be finite — an infinite tilt is not an allocation")
    if cap is not None and cap <= 0.0:
        raise ValueError("cap must be positive — a zero cap is not an allocation rule")
    books = panel.books
    n_books = len(books)
    if n_books < 2:
        raise ValueError("a panel of fewer than two books has no cross-section to size on")
    neutral = 1.0 / n_books if cap is None else min(1.0 / n_books, cap)
    out: Dict[str, List[float]] = {b: [0.0] * panel.n for b in books}

    for i in range(panel.n):
        rankable = [b for b in books if scores[b][i] is not None]
        for b in books:
            if b not in rankable:
                out[b][i] = neutral
        if len(rankable) < 2:
            for b in rankable:
                out[b][i] = neutral
            continue
        raw = [float(scores[b][i]) for b in rankable]
        if form == "rank":
            order = sorted(range(len(rankable)), key=lambda j: (raw[j], rankable[j]))
            pos = [0.0] * len(rankable)
            for place, j in enumerate(order):
                pos[j] = float(place)
            basis = _standardise(pos)
        else:
            basis = _standardise(raw)
        if basis is None:
            for b in rankable:
                out[b][i] = neutral
            continue
        phi = {b: _shape(basis[j], lam, form) for j, b in enumerate(rankable)}
        placed = _cap_fill(phi, neutral * len(rankable), cap)
        for b in rankable:
            out[b][i] = placed.get(b, 0.0)
    return out


def permuted_weights(weights: Dict[str, List[float]], books: Sequence[str],
                     seed: int) -> Dict[str, List[float]]:
    """Re-attach the weight PATHS to the wrong books — #38's control, for a continuous rule.

    Deployment, turnover, concentration and the whole day-by-day shape of the allocation survive
    exactly; only WHICH book each path belongs to is destroyed. A permuted panel that scores as
    well as the real one means the rule is not selecting books, it is merely holding an unusual
    but constant-in-character portfolio.
    """
    import random
    rng = random.Random(seed)
    order = list(books)
    rng.shuffle(order)
    return {books[i]: list(weights[order[i]]) for i in range(len(books))}


def shifted_weights(weights: Dict[str, List[float]], books: Sequence[str],
                    shift: int) -> Dict[str, List[float]]:
    """Rotate every weight path in TIME (circular) — book identity survives, alignment does not."""
    return {b: list(weights[b][shift:]) + list(weights[b][:shift]) for b in books}


# ═══════════════════════════ #63 — the identity ═══════════════════════════
def excess_path(panel: "dgo.Panel", weights: Dict[str, List[float]]) -> List[float]:
    """R_pf(t) − R_eq(t) for a NON-earning cash residue, per day. No assumptions about w."""
    books = panel.books
    neutral = 1.0 / len(books)
    return [sum((weights[b][i] - neutral) * panel.rets[b][i] for b in books)
            for i in range(panel.n)]


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cov(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or not xs:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)


def decompose(panel: "dgo.Panel", weights: Dict[str, List[float]]) -> Dict[str, float]:
    """#63 — the two exact decompositions of the same excess return, plus their residuals.

    Returned (all daily, un-annualised unless the key says otherwise):
      excess_mean     mean_t Σ_b (w_b(t) − 1/N)·r_b(t)
      share_mean      mean_t Σ_b max(0, 1/N − w_b(t))          — capital displaced per day
      spread_mean     mean_t excess(t)/share(t)                — return per unit displaced
      cov_share_spread                                          — the sizing term, zero for any
                                                                  constant-share (binary) rule
      resid_1         excess_mean − (share_mean·spread_mean + cov)  ≡ 0 to floating point
      tilt_mean       mean_t Σ_b (w̄_b − 1/N)·r_b(t)           — the free standing tilt
      timing_mean     mean_t Σ_b (w_b(t) − w̄_b)·r_b(t)        — what the turnover is bought with
      resid_2         excess_mean − (tilt_mean + timing_mean)      ≡ 0 to floating point

    Both residuals are RETURNED and printed rather than asserted away, because an identity whose
    residual is never shown is a claim; this way a reader can see that it holds on the very numbers
    being quoted. Days with share = 0 (the rule is flat against equal weight) contribute an excess
    of exactly 0 and are excluded from the spread mean — a ratio with a zero denominator is not a
    small number, it is an undefined one, and averaging it in as zero would silently drag the
    spread toward the flat days.
    """
    books = panel.books
    neutral = 1.0 / len(books)
    n = panel.n
    exc = excess_path(panel, weights)
    share = [sum(max(0.0, neutral - weights[b][i]) for b in books) for i in range(n)]

    live = [i for i in range(n) if share[i] > EPS]
    spread = [exc[i] / share[i] for i in live]
    sh_live = [share[i] for i in live]
    exc_live = [exc[i] for i in live]

    avg = {b: sum(weights[b]) / n for b in books}
    tilt = [sum((avg[b] - neutral) * panel.rets[b][i] for b in books) for i in range(n)]
    timing = [sum((weights[b][i] - avg[b]) * panel.rets[b][i] for b in books) for i in range(n)]

    share_mean = _mean(sh_live)
    spread_mean = _mean(spread)
    cov = _cov(sh_live, spread)
    excess_live = _mean(exc_live)
    return {
        "excess_mean": _mean(exc),
        "excess_live_mean": excess_live,
        "share_mean": share_mean,
        "spread_mean": spread_mean,
        "cov_share_spread": cov,
        "resid_1": excess_live - (share_mean * spread_mean + cov),
        "tilt_mean": _mean(tilt),
        "timing_mean": _mean(timing),
        "resid_2": _mean(exc) - (_mean(tilt) + _mean(timing)),
        "active_days": float(len(live)),
        "share_sd": math.sqrt(max(0.0, _cov(sh_live, sh_live))),
    }


def binary_weights(panel: "dgo.Panel", scores: "xsd.Scores", k: int, m_days: int,
                   cap: Optional[float] = CONC_CAP) -> Dict[str, List[float]]:
    """The published #40 rule's allocation — the row every table here is measured against."""
    flags = xsd.rank_demotion_flags(scores, k, m_days)
    return ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap)


# ═══════════════════════════ report bodies ═══════════════════════════
def _spw_rows(panel: "dgo.Panel", scores: "xsd.Scores", k: int, cap: Optional[float]
              ) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """The rows every SPW report prints: the registry's binary corners, then the λ ladder."""
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []
    rows.append((f"#40 XSD binary k={k} M={REF_M}", binary_weights(panel, scores, k, REF_M, cap), 0.0))
    rows.append((f"#40 binary daily k={k} M=1", binary_weights(panel, scores, k, 1, cap), 0.0))
    for form in FORMS:
        for lam in LAMBDAS:
            if lam == 0.0 and form != FORMS[0]:
                continue                      # λ=0 is the same object for every form (identity)
            name = "raw equal weight ≡ λ=0" if lam == 0.0 else f"SPW {form:7s} λ={lam}"
            rows.append((name, spw_weights(panel, scores, lam, form, cap), 0.0))
    # A static twin for EVERY form, not only the first one. One twin is an anecdote: the twin is
    # the control that decides whether a row is timing or a standing tilt, and a report that runs
    # it on the shape it happens to like is choosing which of its own rows gets audited.
    for form in FORMS:
        twin = ecr.alloc_static_matched(spw_weights(panel, scores, 1.0, form, cap))
        rows.append((f"  CONTROL static twin λ=1 {form}", twin, 0.0))
    rows.append(("  CONTROL anti-rule λ=−1 linear",
                 spw_weights(panel, scores, -1.0, "linear", cap), 0.0))
    return rows


def idea62_spw(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, kind: str = "drift",
               cap: Optional[float] = CONC_CAP) -> Dict[str, Dict[str, float]]:
    """Idea #62 — does sizing by the magnitude of the score beat sizing by membership in a set?"""
    panel = dgo.Panel(subset, start, end)
    scores = erd.panel_scores(panel, kind, LOOKBACK)
    rows = _spw_rows(panel, scores, k, cap)
    return xsd._report(f"IDEA #62 SPW — score-proportional weighting [{segment}] — {label}",
                       panel, rows, quiet)


def form_grid(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
              cap: Optional[float] = CONC_CAP,
              lams: Sequence[float] = LAMBDAS) -> None:
    """The λ × form grid, printed whole — netAPY, ΔCalmar, turnover, and max weight.

    `rank` beside `linear` on every row is the entry's own falsification test: identical machinery,
    identical tilt budget, and the only difference is whether the magnitudes are visible. Reading a
    winner out of one column while the other column is not printed is precisely how #58 talked
    itself into a selector that a constant list beat.
    """
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"GRID λ × form, k={k}, cap={cap} — netAPY % (ΔCalmar), raw Calmar {base['calmar']:.2f}")
    print("=" * 110)
    print(f"{'λ':>6s}" + "".join(f"{f:>22s}" for f in FORMS))
    for lam in lams:
        cells = []
        for form in FORMS:
            met = ecr.portfolio_metrics(panel, spw_weights(panel, scores, lam, form, cap))
            cells.append(f"{met['net_apy_after_cost']*100:8.2f}% "
                         f"({met['calmar']-base['calmar']:+6.2f})")
        print(f"{lam:>6.2f}" + "".join(f"{c:>22s}" for c in cells))
    print()
    print(f"{'λ':>6s}" + "".join(f"{f + ' turn/yr':>22s}" for f in FORMS))
    for lam in lams:
        cells = []
        for form in FORMS:
            met = ecr.portfolio_metrics(panel, spw_weights(panel, scores, lam, form, cap))
            cells.append(f"{met['turnover_yr']:9.2f}  maxW {met['max_weight']*100:3.0f}%")
        print(f"{lam:>6.2f}" + "".join(f"{c:>22s}" for c in cells))
    print("-" * 110)
    print("`rank` is the magnitude-BLIND twin of `linear`: same tilt budget, order only. The gap")
    print("between those two columns IS #61's claim that the information lies in the magnitude —")
    print("there is no other number in this registry that tests it.")


def ceiling_table(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                  cap: Optional[float] = CONC_CAP, seeds: int = SEEDS,
                  lams: Sequence[float] = (0.5, 1.0, 2.0)) -> None:
    """Capture against #59's panel ceiling — the same denominator #60 was measured with.

    The ceiling is the freest binary form (daily decisions, no hold) fed one-day foresight, which
    is #59's 81.96 % row and #60's `panel_ceiling`; keeping the identical object is the only way
    the capture percentages of #59, #60 and #62 can be read on one line. Each SPW row ALSO gets its
    own oracle — the same λ and form fed forward scores — because a form that cannot use foresight
    is limited by its shape and not by its criterion, which is exactly the diagnosis #59 made of
    M=20 stickiness.

    The floor is the permutation twin of the SAME weights (`permuted_weights`): identical
    deployment, turnover and concentration, book identity destroyed.
    """
    free_oracle, _ = edh.dhd_weights(panel, ecc.forward_scores(panel, 1), k, 1, 1, 0, 1, cap=cap)
    panel_ceiling = ecr.portfolio_metrics(panel, free_oracle)["net_apy_after_cost"]

    print()
    print("=" * 110)
    print("CAPTURE AGAINST #59's CEILING — the identical denominator #59 and #60 were scored on")
    print(f"panel ceiling = binary daily form with h=1 foresight: netAPY {panel_ceiling*100:.2f} % "
          "[LOOK-AHEAD]")
    print("=" * 110)
    print(f"{'form':34s} {'netAPY':>9s} {'floor':>9s} {'own oracle':>11s} "
          f"{'capt own':>9s} {'capt panel':>11s}")

    def _floor_from(w: Dict[str, List[float]]) -> float:
        acc = 0.0
        for s in range(seeds):
            acc += ecr.portfolio_metrics(
                panel, permuted_weights(w, panel.books, s))["net_apy_after_cost"]
        return acc / seeds

    bw = binary_weights(panel, scores, k, REF_M, cap)
    bflags = xsd.rank_demotion_flags(scores, k, REF_M)
    b_rule = ecr.portfolio_metrics(panel, bw)["net_apy_after_cost"]
    b_floor = ecc.chance_floor(panel, bflags, k, REF_M, cap=cap, seeds=seeds)["net_apy_after_cost"]
    b_orc = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books, xsd.rank_demotion_flags(ecc.forward_scores(panel, 1), k, REF_M),
        panel.n, cap=cap))["net_apy_after_cost"]
    own = ecc.capture(b_rule, b_orc, b_floor)
    pan = ecc.capture(b_rule, panel_ceiling, b_floor)
    print(f"{'#40 XSD binary k=' + str(k) + ' M=' + str(REF_M):34s} {b_rule*100:8.2f}% "
          f"{b_floor*100:8.2f}% {b_orc*100:10.2f}% "
          f"{('n/a' if own is None else f'{own*100:.0f} %'):>9s}"
          f"{('n/a' if pan is None else f'{pan*100:.0f} %'):>11s}")

    fwd = ecc.forward_scores(panel, 1)
    for form in FORMS:
        for lam in lams:
            w = spw_weights(panel, scores, lam, form, cap)
            rule = ecr.portfolio_metrics(panel, w)["net_apy_after_cost"]
            floor = _floor_from(w)
            orc = ecr.portfolio_metrics(
                panel, spw_weights(panel, fwd, lam, form, cap))["net_apy_after_cost"]
            own = ecc.capture(rule, orc, floor)
            pan = ecc.capture(rule, panel_ceiling, floor)
            print(f"{'SPW ' + form + ' λ=' + str(lam):34s} {rule*100:8.2f}% {floor*100:8.2f}% "
                  f"{orc*100:10.2f}% "
                  f"{('n/a' if own is None else f'{own*100:.0f} %'):>9s}"
                  f"{('n/a' if pan is None else f'{pan*100:.0f} %'):>11s}")
    print("-" * 110)
    print("A capture above 100 % is NOT clipped: it means that form cannot use one-day foresight,")
    print("which is #59's diagnosis of stickiness and is the number that shows it.")


def sxd_table(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
              cap: Optional[float] = CONC_CAP,
              lams: Sequence[float] = (0.5, 1.0, 2.0, 4.0)) -> Dict[str, Dict[str, float]]:
    """Idea #63 — the same excess, decomposed two ways, for the binary rule and for SPW.

    Everything here is GROSS and ARITHMETIC (mean × 365): the terms are printed because they ADD,
    and only arithmetic means do. The cost column beside them is the same 96 bp round-trip model as
    every other table, stated so the reader can see which decompositions survive their own bill.
    """
    rows: List[Tuple[str, Dict[str, List[float]]]] = [
        (f"#40 binary k={k} M={REF_M}", binary_weights(panel, scores, k, REF_M, cap)),
        (f"#40 binary k={k} M=1", binary_weights(panel, scores, k, 1, cap)),
    ]
    for form in ("linear", "rank"):
        for lam in lams:
            rows.append((f"SPW {form} λ={lam}", spw_weights(panel, scores, lam, form, cap)))

    print()
    print("=" * 110)
    print("IDEA #63 SXD — excess over equal weight, decomposed exactly. All columns ARITHMETIC %/yr,")
    print("GROSS of cost.  excess = share×spread + cov  and  excess = tilt + timing (both exact)")
    print("=" * 110)
    print(f"{'allocation':26s} {'excess':>8s} {'share':>7s} {'spread':>9s} {'share×sp':>9s} "
          f"{'cov':>8s} {'tilt':>8s} {'timing':>8s} {'resid':>8s} {'cost':>7s}")
    out: Dict[str, Dict[str, float]] = {}
    for name, w in rows:
        d = decompose(panel, w)
        out[name] = d
        cost = ecr.portfolio_metrics(panel, w)["cost_bp_yr"] / ecr.BP
        print(f"{name:26s} {d['excess_mean']*365*100:7.2f}% {d['share_mean']*100:6.1f}% "
              f"{d['spread_mean']*365*100:8.2f}% {d['share_mean']*d['spread_mean']*365*100:8.2f}% "
              f"{d['cov_share_spread']*365*100:7.2f}% {d['tilt_mean']*365*100:7.2f}% "
              f"{d['timing_mean']*365*100:7.2f}% "
              f"{max(abs(d['resid_1']), abs(d['resid_2']))*365*100:7.1e} {cost*100:6.2f}%")
    print("-" * 110)
    print("`share` is the capital a form actually displaces. For the DAILY binary form it is the")
    print("constant k/N and `cov` is identically zero; for the PUBLISHED M=20 form the demoted set")
    print("can exceed k, so cov is an unnamed sizing term nobody chose — read its sign.")
    print("`tilt` is what a static allocator holds for free with zero turnover (#38/#55/#58's")
    print("control, here INSIDE the identity): an excess that is all tilt is not timing at all.")
    return out


def spread_bridge(panel: "dgo.Panel", k: int = REF_K, kind: str = "drift") -> None:
    """The bridge to #61: the same number in two currencies, printed side by side.

    #61 measured the forward spread in bp/day between the causal bottom-k and the rest. #63 measures
    the portfolio excess of the rule built on that same set. For the UNCAPPED binary rule the two
    are related by an exact factor k/N — so this table is what makes #61's h=20 result readable
    rather than paradoxical: a daily-rebalanced book consumes the ONE-DAY spread every day and never
    consumes the twenty-day spread that #61 found to be zero.

    The capped rows are printed too and they do NOT match by construction: the cap turns part of the
    displaced capital into cash, and the difference between the two rows is the price of the cap,
    not an error. Saying which rows are identities and which are not is the whole point.

    One bookkeeping detail decides whether the identity closes or misses by 7 %: #61 averages its
    spread over the days on which BOTH the causal and the forward set are defined, while a portfolio
    is averaged over every day it exists, including the L-day warm-up on which it is flat. So the
    comparison is made on the ACTIVE days (`excess_live_mean`) and the day counts are printed beside
    it. Quietly averaging over different denominators and then calling the 7 % gap "approximately
    equal" is exactly the kind of near-miss that would have buried the identity.
    """
    scores = erd.panel_scores(panel, kind, LOOKBACK)
    print()
    print("=" * 110)
    print("BRIDGE TO #61 — the forward spread and the portfolio excess are ONE measurement")
    print("=" * 110)
    n_books = len(panel.books)
    w_unc = ecr.alloc_recycle(panel.books, xsd.rank_demotion_flags(scores, k, 1), panel.n, cap=None)
    w_cap = ecr.alloc_recycle(panel.books, xsd.rank_demotion_flags(scores, k, 1),
                              panel.n, cap=CONC_CAP)
    d_unc, d_cap = decompose(panel, w_unc), decompose(panel, w_cap)
    print(f"{'h':>4s} {'#61 spread bp/d':>16s} {'× k/N':>10s} "
          f"{'#63 excess bp/d, active days':>30s} {'gap':>8s} {'capped':>9s}")
    for h in (1, 5, 20, 60):
        ra = edh.rank_agreement(panel, k, LOOKBACK, h, kind)
        pred = ra["spread_bp"] * k / n_books
        got = d_unc["excess_live_mean"] * 1e4
        print(f"{h:>4d} {ra['spread_bp']:>16.2f} {pred:>10.2f} {got:>30.2f} "
              f"{got - pred:>+8.2f} {d_cap['excess_live_mean']*1e4:>9.2f}")
    print(f"     active days {d_unc['active_days']:.0f} of {panel.n}; "
          f"#61 scores its spread on the days a forward set is also defined")
    print("-" * 110)
    print("Only the h=1 row is the identity, and it closes to the second decimal: the portfolio is")
    print("rebalanced daily, so ONE day is the only horizon it ever consumes. The h>1 rows are the")
    print("same portfolio against spreads it never touches — that is why #61's h=20 zero and this")
    print("family's positive portfolio rows were never in contradiction.")
    print("[LOOK-AHEAD] every spread column is built from forward returns; the capped column is not")
    print("an identity by construction (the cap turns displaced capital into cash).")


def controls(panel: "dgo.Panel", scores: "xsd.Scores", lam: float = 1.0,
             form: str = "linear", cap: Optional[float] = CONC_CAP, seeds: int = SEEDS) -> None:
    """Permutation and rotation controls for a CONTINUOUS rule, plus the static twin.

    The binary family runs these on flags; SPW has no flags, so the identical instrument is applied
    to the weight paths themselves. Permutation destroys WHICH book; rotation destroys WHEN; the
    static twin destroys timing while keeping the standing tilt. A rule that only survives the
    permutation is a cross-sectional tilt and belongs to the allocator (ADR-055), not to an overlay.
    """
    base = ecr._raw_metrics(panel)
    w = spw_weights(panel, scores, lam, form, cap)
    real = ecr.portfolio_metrics(panel, w)
    print()
    print("=" * 110)
    print(f"INFORMATION CONTROLS — SPW {form} λ={lam}  ({seeds} book-permutations, rotation sweep)")
    print("=" * 110)
    print(ecr._COLS)
    ecr._row("REAL alignment", real, base)

    perm = [ecr.portfolio_metrics(panel, permuted_weights(w, panel.books, s)) for s in range(seeds)]
    ps = sorted(perm, key=lambda m: m["calmar"])
    for tag, m in (("perm P10", ps[max(0, int(0.1 * seeds) - 1)]),
                   ("perm P50 (median)", ps[seeds // 2]),
                   ("perm P90", ps[min(seeds - 1, int(0.9 * seeds))])):
        ecr._row(f"  CONTROL {tag}", m, base)
    beaten = sum(1 for m in perm if m["calmar"] >= real["calmar"])
    print(f"  → permutations reaching the real Calmar: {beaten}/{seeds}"
          f"   (empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")

    shifts = list(range(30, panel.n, 30))
    sh = [ecr.portfolio_metrics(panel, shifted_weights(w, panel.books, s)) for s in shifts]
    ss = sorted(sh, key=lambda m: m["calmar"])
    kk = len(ss)
    for tag, m in ((f"shift P10 (of {kk})", ss[max(0, int(0.1 * kk) - 1)]),
                   ("shift P50 (median)", ss[kk // 2]),
                   ("shift BEST", ss[-1])):
        ecr._row(f"  CONTROL time-{tag}", m, base)
    beaten_s = sum(1 for m in sh if m["calmar"] >= real["calmar"])
    print(f"  → rotations reaching the real Calmar: {beaten_s}/{kk}"
          f"   (empirical p ≈ {(beaten_s + 1) / (kk + 1):.3f})")
    ecr._row("  CONTROL static twin (no timing)",
             ecr.portfolio_metrics(panel, ecr.alloc_static_matched(w)), base)


TT_KEYS = (f"#40 XSD binary k={REF_K} M={REF_M}",
           f"#40 binary daily k={REF_K} M=1",
           "raw equal weight ≡ λ=0",
           "SPW linear  λ=0.5",
           "SPW linear  λ=1.0",
           "SPW rank    λ=1.0",
           "SPW linear  λ=2.0",
           "SPW rank    λ=2.0",
           "SPW softmax λ=1.0",
           "  CONTROL static twin λ=1 linear")


def train_test_subset(subset: Optional[Sequence[str]], label: str,
                      keys: Sequence[str] = TT_KEYS, k: int = REF_K) -> None:
    """TRAIN → TEST on an arbitrary book subset — `ecr.train_test` is wired to the full panel only.

    This exists because the whole verdict of #62 turns on a subset: the 4 dead books of #54 print
    exactly 0.0 forever, which is a return that ranks above every genuinely losing book, so a rule
    that tilts away from losers is partly tilting toward corpses. Running the out-of-sample split
    ONLY on the panel that contains them would answer a question about our data pipeline.

    The raw baseline is recomputed per segment and per subset, so ΔCalmar is always against the
    equal-weight panel a reader could actually have held on that segment.
    """
    print()
    print("=" * 110)
    print(f"TRAIN → TEST (split {TRAIN_END}) — {label}; λ and the forms fixed BEFORE the split")
    print("=" * 110)
    sub = list(subset) if subset is not None else None
    train = idea62_spw(sub, label, end=TRAIN_END, segment="TRAIN", quiet=True, k=k)
    test = idea62_spw(sub, label, start=TRAIN_END, segment="TEST", quiet=True, k=k)
    raw_tr = ecr._raw_metrics(dgo.Panel(sub, None, TRAIN_END))
    raw_te = ecr._raw_metrics(dgo.Panel(sub, TRAIN_END, None))
    print(f"raw TRAIN: APY {raw_tr['apy']*100:6.2f}%  DD {raw_tr['maxdd']*100:6.2f}%  "
          f"Calmar {raw_tr['calmar']:5.2f}   |   raw TEST: APY {raw_te['apy']*100:6.2f}%  "
          f"DD {raw_te['maxdd']*100:6.2f}%  Calmar {raw_te['calmar']:5.2f}")
    print(f"{'configuration':34s} {'trAPY':>8s} {'trDD':>7s} {'trCalmar':>9s} {'trΔ':>7s} "
          f"{'teAPY':>8s} {'teDD':>7s} {'teCalmar':>9s} {'teΔ':>7s}")
    for key in keys:
        kk = key.strip()
        if kk not in train or kk not in test:
            print(f"{key:34s}   [absent — configuration not produced on one of the segments]")
            continue
        a, b = train[kk], test[kk]
        print(f"{key:34s} {a['apy']*100:7.2f}% {a['maxdd']*100:6.2f}% {a['calmar']:9.2f} "
              f"{a['calmar']-raw_tr['calmar']:7.2f} "
              f"{b['apy']*100:7.2f}% {b['maxdd']*100:6.2f}% {b['calmar']:9.2f} "
              f"{b['calmar']-raw_te['calmar']:7.2f}")
    print("-" * 110)
    print("maxDD is printed on BOTH segments beside every return: this registry's rule is that the")
    print("tail is never one table away from the yield it paid for.")


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D #62 SPW / #63 SXD — advisory, read-only")
    ap.add_argument("--idea", type=int, choices=(62, 63), default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--ceiling", action="store_true")
    ap.add_argument("--controls", action="store_true")
    ap.add_argument("--train-test", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument("-k", type=int, default=REF_K)
    args = ap.parse_args(argv)

    full = dgo.Panel()
    live = ets.live_books(full)
    subsets: List[Tuple[Optional[List[str]], str]] = []
    if args.live_only:
        subsets.append((live, f"{len(live)} LIVE books (#54)"))
    else:
        subsets.append((None, f"all {len(full.books)} real books"))
        subsets.append((live, f"{len(live)} LIVE books (#54)"))

    everything = not (args.sweep or args.ceiling or args.controls or args.train_test
                      or args.idea is not None)

    for subset, label in subsets:
        panel = dgo.Panel(subset)
        scores = erd.panel_scores(panel, "drift", LOOKBACK)
        if everything or args.idea == 62:
            idea62_spw(subset, label, k=args.k)
        if everything or args.sweep:
            form_grid(panel, scores, args.k)
        if everything or args.ceiling:
            ceiling_table(panel, scores, args.k)
        if everything or args.controls:
            controls(panel, scores, cap=CONC_CAP)
        if everything or args.idea == 63:
            print()
            print(f"### {label}")
            sxd_table(panel, scores, args.k)
            spread_bridge(panel, args.k)

    if everything or args.train_test:
        for subset, label in ((None, f"all {len(full.books)} real books"),
                              (live, f"{len(live)} LIVE books (#54)")):
            train_test_subset(subset, label, k=args.k)
        for seg, s, e in (("TRAIN", None, TRAIN_END), ("TEST", TRAIN_END, None)):
            for subset, label in ((None, "all real books"), (live, f"{len(live)} LIVE books")):
                p = dgo.Panel(subset, s, e)
                sc = erd.panel_scores(p, "drift", LOOKBACK)
                print()
                print(f"### {seg} — {label}")
                sxd_table(p, sc, args.k)
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
