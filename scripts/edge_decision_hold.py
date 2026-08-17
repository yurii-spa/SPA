#!/usr/bin/env python3
"""Edge R&D — registry ideas #60 (DHD) and #61 (RPH): the FORM of the rule, and whether the
reserve #59 found is reachable at all.

WHERE THIS COMES FROM
  Entry #59 OIB gave the registry its first denominator and then wrote the next step down in
  words, which no entry of this family had ever done:

      "look not for a fifth criterion but for a different FORM of the rule — partial demotion
       depth with a fast state machine against a slow one, i.e. DECOUPLE 'how often we decide'
       from 'how long we hold'; measure everything against this same ceiling."

  The measurement behind that instruction: with the published stickiness M=20 a perfect oracle
  that sees one day ahead earns 22.47 % APY — LESS than the causal rule's 28.03 %. The machine
  physically cannot act on what it knows. Let the same machine act daily (M=1) and the panel's
  ceiling jumps to netAPY 81.96 % against 21.70 % taken, a capture of 12 %. #59's own summary:
  *"roughly four times more income lies in the panel than any rule of this family takes, and it
  lies at a frequency our own stickiness forbids."*

  Two questions follow, and they are different questions. This file answers both.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #60 — DHD: Decision–Hold Decoupling   ("deciding often and holding long are not one knob")
──────────────────────────────────────────────────────────────────────────────────────────────
  Every entry from #37 to #59 has run the SAME state machine, `xsd.rank_demotion_flags`, and that
  machine has exactly one time knob:

      enter  : in the bottom-k today                       ⇒ demoted, immediately
      leave  : OUT of the bottom-k on M consecutive days   ⇒ re-admitted

  So the single letter M is doing three jobs at once. It sets how long a demotion typically
  lasts; it sets how much evidence a re-admission needs; and — because a book that oscillates in
  and out of the bottom-k never assembles M good days in a row — it decides whether a NOISY book
  can ever come back at all. #59 priced the bundle (≈ two thirds of the achievable income) but
  could not say which of the three jobs costs what, because there is only one dial to turn.

  DHD splits the dial into four, of which three are new:

      decide_every  D : the ranking is consulted only every D-th day; between epochs the state is
                        frozen and the clocks do not tick          ← "how often we decide"
      enter_days    J : consecutive epochs in the bottom-k before a demotion opens (J=1 = today)
      hold_days     R : calendar days a demotion is held before release may even be considered,
                        regardless of what the ranking says        ← "how long we hold", as a TERM
      readmit_days  M : consecutive good epochs required after the term has run out

  The published rule is the corner (D=1, J=1, R=0, M=20), and that is an IDENTITY, not an
  approximation: `decision_hold_flags(s, k, 1, 1, 0, m) == xsd.rank_demotion_flags(s, k, m)`
  cell for cell, pinned by the test-suite with a positive control that reddens when any one of
  the four knobs is mis-wired. Nothing else changes — criterion, k, L, panel, allocator, cap,
  cost model and the train/test split are imported from #40/#38/#32 and are not re-tuned here.

  The interesting corner is the opposite one: (D=1, R=20, M=1) — decide EVERY DAY, hold for a
  fixed TERM, release the moment the term is up and the book is out of the bottom-k. Same average
  stickiness, but the stickiness is now a property of the CALENDAR rather than of the signal's
  noise. If #59's reserve is reachable by re-shaping the machine, this is where it shows up.

  Three outcomes, written down BEFORE the numbers:

    A. some (D, J, R, M) beats the published corner on netAPY AND raises capture against the
       SAME oracle ⇒ the form of the rule was the binding constraint, and #59's instruction has
       an implementation.
    B. the decoupled cells land on the M-sweep's own curve — i.e. only the average spell length
       matters, and how it is produced does not ⇒ the three jobs of M are one job, and the
       registry's single knob was never hiding anything.
    C. the decoupled cells are worse ⇒ the noise-gate that M performs by accident (a flickering
       book cannot come back) is doing real work, and naming it as a term destroys it.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #61 — RPH: Rank Predictability by Horizon   ("is the reserve reachable, or is it a mirage?")
──────────────────────────────────────────────────────────────────────────────────────────────
  #59 measured a ceiling and called the gap beneath it a reserve. But a ceiling is built from
  FORWARD returns, and nothing in #59 asked whether the forward ranking is forecastable at all.
  If it is not, the gap is not a debt to be collected by a cleverer rule — it is the part of the
  panel that is simply noise, and twenty-five entries of this family have been chasing it.

  RPH asks the question directly, with no portfolio, no allocator and no cost model in the way:

      how often is the causal bottom-k (trailing drift over L) the same set as the
      forward bottom-k over the next h days — against the honest null?

  The honest null is NOT k/N. #58 learned this the expensive way: a constant predictor that
  always names the books which end up in the forward bottom-k most often scores far above chance
  on a sample where some books are persistently bad, and beating a coin while losing to a
  constant is the definition of a signal that knows nothing. So three numbers are printed side by
  side for every horizon — overlap of the causal set, `chance` = k/N, and `majority`, the best
  CONSTANT set measured on the same days.

  And there is a trap here that is #54's: a book whose feed died prints exactly 0.0 forever, so
  its forward mean is exactly 0.0, which ranks ABOVE every book that is genuinely losing. On the
  full panel, "predicting the forward bottom-k" is therefore partly predicting which books are
  dead — a fact about our data pipeline dressed as an edge. Both panels are printed, always.

HONESTY / SCOPE (registry rules — non-negotiable)
  • The oracle and the forward ranking are LOOK-AHEAD BY CONSTRUCTION and are never proposed as
    rules. Every row that uses them is labelled `[LOOK-AHEAD]`, and the test-suite pins that the
    causal side of this file never reads a future return (positive control: mutate tomorrow,
    assert today is unchanged).
  • Panel, allocator, cost model (48 bp per one-way leg = #10's 96 bp round trip), L=60, k, the
    concentration cap and the train/test split are IMPORTED from #32/#38/#39/#40, never
    re-derived. Books are regenerated nightly, so numbers reproduce only against the run date.
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0 nor the kill-switch thresholds. Evidence L0 (backtest on real feed
    history, NOT live). IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_decision_hold.py                  # everything
    python3 scripts/edge_decision_hold.py --idea 60        # DHD only
    python3 scripts/edge_decision_hold.py --idea 61        # RPH only
    python3 scripts/edge_decision_hold.py --grid           # (D × R) grid + phase band + term limit
    python3 scripts/edge_decision_hold.py --ceiling        # capture against #59's oracle
    python3 scripts/edge_decision_hold.py --controls       # permutation / rotation / TRAIN→TEST
    python3 scripts/edge_decision_hold.py --live-only      # both ideas on the 6 live books (#54)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, controls #38/#39)
import edge_criterion_choice as ecc             # noqa: E402  (oracle + capture of #59)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_event_time_scoring as ets           # noqa: E402  (live/dead book census of #54)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK          # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END        # "2025-06-30" — the registry's own split
REF_K = 2                        # #40's reference k, so every row is like-for-like
REF_M = 20                       # #40's published stickiness — the corner being decomposed
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap
EPS = ecr.EPS
SEEDS = 20                       # control seeds, same count as #38/#40/#58/#59

DECIDE = (1, 2, 5, 10, 20)       # D — how often the ranking is consulted
HOLDS = (0, 5, 10, 20, 40)       # R — the fixed term a demotion is held for
MS = (1, 5, 10, 20, 40)          # M — the published knob, swept for the reference curve
HORIZONS = (1, 5, 20, 60)        # h — how far the oracle / the forward ranking sees


# ═══════════════════════════ #60 — the four-knob state machine ═══════════════════════════
def decision_hold_flags(scores: "xsd.Scores", k: int,
                        decide_every: int = 1, enter_days: int = 1,
                        hold_days: int = 0, readmit_days: int = 1,
                        worst_first: bool = True, decide_phase: int = 0) -> Dict[str, List[bool]]:
    """True on days the book is DEMOTED — the published machine with its one time knob split in four.

        decide_every D : the ranking is consulted on days where i % D == decide_phase. On every
                         other day the state is FROZEN and neither run-counter moves, exactly as
                         the published machine freezes when a day has no definable rank. The hold
                         clock is the one thing that keeps ticking, because it counts calendar days
                         and not decisions — a term that paused whenever we looked away would not
                         be a term. `decide_phase` is the choice nobody named until #60 measured
                         that it moves the answer more than `decide_every` itself does.
        enter_days   J : consecutive DECISION EPOCHS in the bottom-k before a demotion opens.
        hold_days    R : calendar days a demotion is held before release may be considered at all.
        readmit_days M : consecutive good epochs required once the term R has elapsed.

    (D, J, R, M) = (1, 1, 0, m) is `xsd.rank_demotion_flags(scores, k, m)` cell for cell — an
    identity, not an approximation, and the test-suite pins it with a control that reddens if any
    knob is mis-wired. Everything the published rule does, this machine does by construction.

    Fail-CLOSED in the same three places as the machine it generalises, all of them cases where a
    rank is not defined:
      • fewer than k+1 rankable books on a day ⇒ NOBODY changes state (a field in which everyone
        is the worst has no worst);
      • a book with score None is not rankable and can never enter the bottom-k;
      • ties are broken by book name, so the report is reproducible rather than dict-ordered.

    `worst_first=False` is the sign-flipped CONTROL (demote the BEST-ranked books). It is never a
    proposed rule; it exists so that "the ranking carries information" stays a measured claim.
    """
    if k < 1:
        raise ValueError("k must be >= 1 — a rank rule that demotes nobody is not a rule")
    if decide_every < 1:
        raise ValueError("decide_every must be >= 1 — a rule that never looks is not a rule")
    if enter_days < 1:
        raise ValueError("enter_days must be >= 1 — demoting on no evidence is not a rule")
    if hold_days < 0:
        raise ValueError("hold_days must be >= 0 — a negative term is not a term")
    if readmit_days < 1:
        raise ValueError("readmit_days must be >= 1 — re-admission with no evidence is not a rule")
    if not 0 <= decide_phase < decide_every:
        raise ValueError(f"decide_phase {decide_phase} is outside a {decide_every}-day grid — "
                         "a phase nobody's calendar can land on is not a schedule")
    books = sorted(scores)
    if k >= len(books):
        raise ValueError(f"k={k} with {len(books)} books would demote the whole panel — refused")
    n = len(scores[books[0]]) if books else 0
    sign = 1.0 if worst_first else -1.0

    demoted = {b: False for b in books}
    bad_run = {b: 0 for b in books}
    good_run = {b: 0 for b in books}
    since = {b: 0 for b in books}          # calendar days already spent demoted
    out: Dict[str, List[bool]] = {b: [] for b in books}

    for i in range(n):
        rankable = [b for b in books if scores[b][i] is not None]
        epoch = (i % decide_every == decide_phase) and len(rankable) > k
        if epoch:
            ordered = sorted(rankable, key=lambda b: (sign * float(scores[b][i]), b))
            bottom = set(ordered[:k])
            for b in books:
                in_bottom = b in bottom
                bad_run[b] = bad_run[b] + 1 if in_bottom else 0
                good_run[b] = 0 if in_bottom else good_run[b] + 1
                if demoted[b]:
                    if since[b] >= hold_days and good_run[b] >= readmit_days:
                        demoted[b] = False
                elif bad_run[b] >= enter_days:
                    demoted[b], since[b] = True, 0
        for b in books:
            out[b].append(demoted[b])
            if demoted[b]:
                since[b] += 1
    return out


def spell_stats(flags: Dict[str, Sequence[bool]], n: int) -> Dict[str, float]:
    """How long the machine ACTUALLY holds, measured rather than assumed from the knob names.

    Two configurations can carry the same duty with completely different spell structure — one
    long demotion or ten flickering ones — and the cost model charges for the difference. Printing
    the mean spell next to every row is what makes "decoupling" a claim about the machine's
    behaviour instead of a claim about its parameters.

    An open spell at the end of the sample is counted with the length it has reached; discarding
    it would shorten the mean by exactly the spells that were still running, which are the long ones.
    """
    spells: List[int] = []
    for b in sorted(flags):
        run = 0
        for f in flags[b]:
            if f:
                run += 1
            elif run:
                spells.append(run)
                run = 0
        if run:
            spells.append(run)
    return {
        "duty": xsd.duty(flags),
        "spells_yr": len(spells) * 365.0 / n / max(1, len(flags)),
        "mean_spell": sum(spells) / len(spells) if spells else 0.0,
        "max_spell": float(max(spells)) if spells else 0.0,
    }


def dhd_weights(panel: "dgo.Panel", scores: "xsd.Scores", k: int,
                decide_every: int, enter_days: int, hold_days: int, readmit_days: int,
                cap: Optional[float] = None,
                worst_first: bool = True) -> Tuple[Dict[str, List[float]], Dict[str, List[bool]]]:
    """flags → the #38 recycled allocation. The same two-call chain every published row used."""
    flags = decision_hold_flags(scores, k, decide_every, enter_days, hold_days, readmit_days,
                                worst_first=worst_first)
    return ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap), flags


# ═══════════════════════════ report bodies ═══════════════════════════
def _cfg(d: int, j: int, r: int, m: int) -> str:
    return f"D={d} J={j} R={r} M={m}"


def _dhd_rows(panel: "dgo.Panel", scores: "xsd.Scores", k: int,
              cap: Optional[float]) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """The rows every DHD report prints: the published corner, the M-curve, the decoupled corners."""
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    def add(name: str, d: int, j: int, r: int, m: int, worst_first: bool = True) -> None:
        w, _ = dhd_weights(panel, scores, k, d, j, r, m, cap=cap, worst_first=worst_first)
        rows.append((name, w, 0.0))

    add(f"#40 XSD published  {_cfg(1, 1, 0, REF_M)}", 1, 1, 0, REF_M)
    add(f"daily/no-hold      {_cfg(1, 1, 0, 1)}", 1, 1, 0, 1)
    for r in (5, 10, 20, 40):
        add(f"TERM hold          {_cfg(1, 1, r, 1)}", 1, 1, r, 1)
    for d in (5, 20):
        add(f"SLOW decide        {_cfg(d, 1, 0, 1)}", d, 1, 0, 1)
    add(f"slow decide+term   {_cfg(20, 1, 20, 1)}", 20, 1, 20, 1)
    add(f"patient ENTRY      {_cfg(1, 3, 0, REF_M)}", 1, 3, 0, REF_M)
    add(f"term + evidence    {_cfg(1, 1, 20, 5)}", 1, 1, 20, 5)

    ref_w, _ = dhd_weights(panel, scores, k, 1, 1, 20, 1, cap=cap)
    rows.append(("  CONTROL static twin of R=20", ecr.alloc_static_matched(ref_w), 0.0))
    add("  CONTROL anti-rule (demote BEST) R=20", 1, 1, 20, 1, worst_first=False)
    return rows


def idea60_dhd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               k: int = REF_K, kind: str = "drift",
               cap: Optional[float] = None) -> Dict[str, Dict[str, float]]:
    """Idea #60 — does splitting M into (decide, enter, hold, re-admit) buy anything?"""
    panel = dgo.Panel(subset, start, end)
    scores = erd.panel_scores(panel, kind, LOOKBACK)
    rows = _dhd_rows(panel, scores, k, cap)
    out = xsd._report(f"IDEA #60 DHD — decision/hold decoupling [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("SPELL STRUCTURE — what the knobs actually produce (duty is matched by the controls,")
        print("spell length is not: the same duty can be one long demotion or ten flickering ones)")
        print(f"{'configuration':38s} {'duty':>7s} {'spells/yr':>10s} {'mean spell':>11s} {'max':>6s}")
        for name, d, j, r, m in (("#40 XSD published", 1, 1, 0, REF_M),
                                 ("daily/no-hold", 1, 1, 0, 1),
                                 ("TERM hold R=20 M=1", 1, 1, 20, 1),
                                 ("TERM hold R=40 M=1", 1, 1, 40, 1),
                                 ("SLOW decide D=20", 20, 1, 0, 1),
                                 ("patient ENTRY J=3", 1, 3, 0, REF_M)):
            st = spell_stats(decision_hold_flags(scores, k, d, j, r, m), panel.n)
            print(f"{name + '  ' + _cfg(d, j, r, m):38s} {st['duty']*100:6.1f}% "
                  f"{st['spells_yr']:10.2f} {st['mean_spell']:11.1f} {st['max_spell']:6.0f}")
    return out


def dhd_grid(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
             decides: Sequence[int] = DECIDE, holds: Sequence[int] = HOLDS,
             cap: Optional[float] = None) -> None:
    """The (D × R) grid at M=1, printed whole — with the M-curve beside it as the reference.

    Printed as a grid rather than as a winner for the reason #47 gave: a single cell chosen after
    looking is a post-hoc cell, and the only defence against reading one is to show all of them.
    The M-curve is what the registry already owns; if the grid never leaves that curve, outcome B
    is the answer and the decomposition bought nothing.
    """
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"GRID (D × R) at M=1, k={k} — netAPY %, and ΔCalmar against raw ({base['calmar']:.2f})")
    print("=" * 110)
    print("netAPY %       " + "".join(f"{'R=' + str(r):>12s}" for r in holds))
    for d in decides:
        cells = []
        for r in holds:
            w, _ = dhd_weights(panel, scores, k, d, 1, r, 1, cap=cap)
            cells.append(ecr.portfolio_metrics(panel, w)["net_apy_after_cost"] * 100)
        print(f"D={d:<12d}" + "".join(f"{c:>12.2f}" for c in cells))
    print()
    print("ΔCalmar        " + "".join(f"{'R=' + str(r):>12s}" for r in holds))
    for d in decides:
        cells = []
        for r in holds:
            w, _ = dhd_weights(panel, scores, k, d, 1, r, 1, cap=cap)
            cells.append(ecr.portfolio_metrics(panel, w)["calmar"] - base["calmar"])
        print(f"D={d:<12d}" + "".join(f"{c:>+12.2f}" for c in cells))
    print()
    print(f"REFERENCE CURVE — the knob the registry already has (D=1, J=1, R=0, M swept), k={k}:")
    print(f"{'M':>6s} {'netAPY':>10s} {'ΔCalmar':>10s} {'turn/yr':>10s} {'mean spell':>11s}")
    for m in MS:
        flags = decision_hold_flags(scores, k, 1, 1, 0, m)
        met = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap))
        st = spell_stats(flags, panel.n)
        print(f"{m:>6d} {met['net_apy_after_cost']*100:9.2f}% "
              f"{met['calmar']-base['calmar']:>+10.2f} {met['turnover_yr']:10.2f} "
              f"{st['mean_spell']:11.1f}")


def phase_table(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                cap: Optional[float] = None, m_days: int = REF_M,
                decides: Sequence[int] = (2, 5, 10, 20)) -> None:
    """How much of the D-axis is CADENCE, and how much is merely WHICH DAYS the grid lands on.

    Spacing the decisions D days apart leaves a second, unnamed choice: the phase — Monday's grid
    and Tuesday's grid see different days. The phase carries no information by construction (no
    calendar effect is claimed anywhere in this registry), so the spread of results ACROSS phases
    at fixed D is a direct measurement of this axis's noise floor. If the D-axis moves less than
    its own phase does, then reading "D=7 beats D=10" is reading the noise floor, and the honest
    report of the cadence axis is the min–max band rather than the D=phase-0 row every table
    would otherwise print.

    This is the same instrument as the family's rotation control, aimed at our own knob instead of
    at the signal.
    """
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"PHASE SENSITIVITY OF THE DECISION GRID (M={m_days}, k={k}) — the noise floor of the D axis")
    print("=" * 110)
    print(f"{'D':>4s} {'ΔCalmar min':>12s} {'median':>9s} {'max':>9s} {'band':>8s} "
          f"{'netAPY min':>11s} {'max':>9s} {'band':>8s}")
    for d in decides:
        deltas, nets = [], []
        for ph in range(d):
            w, _ = dhd_weights_phase(panel, scores, k, d, ph, m_days, cap=cap)
            met = ecr.portfolio_metrics(panel, w)
            deltas.append(met["calmar"] - base["calmar"])
            nets.append(met["net_apy_after_cost"] * 100)
        ds, ns = sorted(deltas), sorted(nets)
        print(f"{d:>4d} {ds[0]:>+12.2f} {ds[len(ds)//2]:>+9.2f} {ds[-1]:>+9.2f} "
              f"{ds[-1]-ds[0]:>8.2f} {ns[0]:>10.2f}% {ns[-1]:>8.2f}% {ns[-1]-ns[0]:>7.2f}pp")
    print("-" * 110)
    print("Compare the `band` columns with how much the D axis itself moves between rows: a knob")
    print("whose phase moves the answer as much as its setting does is not a knob, it is a coin.")


def dhd_weights_phase(panel: "dgo.Panel", scores: "xsd.Scores", k: int,
                      decide_every: int, decide_phase: int, m_days: int,
                      cap: Optional[float] = None) -> Tuple[Dict[str, List[float]],
                                                            Dict[str, List[bool]]]:
    """Same chain as `dhd_weights`, with the decision grid's phase exposed as its own argument."""
    flags = decision_hold_flags(scores, k, decide_every, 1, 0, m_days, decide_phase=decide_phase)
    return ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap), flags


def hold_limit_table(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                     cap: Optional[float] = None,
                     terms: Sequence[int] = (20, 40, 60, 100, 200, 400)) -> None:
    """Where the term axis GOES — up to R = the whole sample, i.e. "demoted once, demoted forever".

    This table exists because the grid has an attractive corner at large R, and the corner has a
    trap in it that no amount of staring at netAPY reveals. As R grows the machine stops being a
    rule and becomes a FIXED EXCLUSION SET: the first k books to touch the bottom-k are never
    re-admitted, so what is being scored is "which books were bad early", discovered on the same
    sample it is scored on. The static twin is the instrument that says so out loud — it holds
    each book's TIME-AVERAGE weight with zero turnover, so if it matches or beats the dynamic row
    there is no timing in that row at all, only a standing tilt an allocator could take once and
    for free. It is the control that convicted #55's cash sleeve and #58's selector, and it is
    pointed here at our own most flattering cell before anybody else points it.
    """
    base = ecr._raw_metrics(panel)
    print()
    print("=" * 110)
    print(f"TERM AXIS TO ITS LIMIT (D=1, J=1, M=1; k={k}) — R={panel.n} means NEVER re-admit")
    print("=" * 110)
    print(f"{'R (days held)':>14s} {'netAPY':>9s} {'Calmar':>8s} {'ΔCalmar':>9s} {'maxDD':>8s} "
          f"{'turn/yr':>8s} {'mean spell':>11s} {'STATIC twin':>12s} {'twin turn':>10s}")
    for r in list(terms) + [panel.n]:
        w, flags = dhd_weights(panel, scores, k, 1, 1, r, 1, cap=cap)
        met = ecr.portfolio_metrics(panel, w)
        twin = ecr.portfolio_metrics(panel, ecr.alloc_static_matched(w))
        st = spell_stats(flags, panel.n)
        tag = f"{r}" + (" = ∞" if r >= panel.n else "")
        print(f"{tag:>14s} {met['net_apy_after_cost']*100:8.2f}% {met['calmar']:8.2f} "
              f"{met['calmar']-base['calmar']:>+9.2f} {met['maxdd']*100:7.2f}% "
              f"{met['turnover_yr']:8.2f} {st['mean_spell']:11.1f} "
              f"{twin['net_apy_after_cost']*100:11.2f}% {twin['turnover_yr']:10.2f}")
    print("-" * 110)
    print("Read the last rows against their twins, not against each other: a dynamic row that its")
    print("own zero-turnover twin BEATS has no timing in it, and its height is a fixed in-sample")
    print("exclusion — the same verdict #55 gave the cash sleeve and #58 gave criterion selection.")


# ═══════════════════════════ #60 against #59's ceiling ═══════════════════════════
def ceiling_table(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
                  cap: Optional[float] = None, horizons: Sequence[int] = HORIZONS,
                  seeds: int = SEEDS) -> None:
    """Capture of each FORM against the oracle run through THAT SAME FORM — #59's instruction.

    Two denominators are printed, because they answer two different questions and conflating them
    is how a capture ratio becomes propaganda:
      • capture(own form)  — of what THIS machine could have taken with perfect foresight, how
        much does it take? A high number means the criterion is good and the form is the limit.
      • capture(panel)     — of what the FREEST form (daily decisions, no hold) could have taken,
        how much does it take? This is the number #59 quoted as 12 %, and it is the only one that
        can be compared across forms.

    The floor under both is `ecc.chance_floor`: the same flags re-attached to the wrong books, so
    duty, spell structure and turnover survive exactly and only "which book" is destroyed.
    """
    forms = (("#40 published D=1 J=1 R=0 M=20", 1, 1, 0, REF_M),
             ("daily/no-hold D=1 J=1 R=0 M=1", 1, 1, 0, 1),
             ("TERM hold     D=1 J=1 R=20 M=1", 1, 1, 20, 1),
             ("SLOW decide   D=20 J=1 R=0 M=1", 20, 1, 0, 1))

    # The panel-wide ceiling is the freest form on the shortest horizon: daily decisions, no hold,
    # perfect one-day foresight. That is #59's 81.96 % row and it is the same object here.
    free_oracle, _ = dhd_weights(panel, ecc.forward_scores(panel, 1), k, 1, 1, 0, 1, cap=cap)
    panel_ceiling = ecr.portfolio_metrics(panel, free_oracle)["net_apy_after_cost"]

    print()
    print("=" * 110)
    print("CAPTURE AGAINST THE CEILING (#59's method, applied per FORM rather than per criterion)")
    print(f"panel ceiling = freest form (D=1 R=0 M=1) with h=1 foresight: "
          f"netAPY {panel_ceiling*100:.2f} %   [LOOK-AHEAD]")
    print("=" * 110)
    print(f"{'form':34s} {'netAPY':>9s} {'floor':>9s} " +
          "".join(f"{'orc h=' + str(h):>10s}" for h in horizons) +
          f"{'capt own':>10s}{'capt panel':>11s}")
    for name, d, j, r, m in forms:
        w, flags = dhd_weights(panel, scores, k, d, j, r, m, cap=cap)
        rule = ecr.portfolio_metrics(panel, w)["net_apy_after_cost"]
        floor = ecc.chance_floor(panel, flags, k, m, cap=cap, seeds=seeds)["net_apy_after_cost"]
        orc: List[float] = []
        for h in horizons:
            ow, _ = dhd_weights(panel, ecc.forward_scores(panel, h), k, d, j, r, m, cap=cap)
            orc.append(ecr.portfolio_metrics(panel, ow)["net_apy_after_cost"])
        own = ecc.capture(rule, max(orc), floor)
        pan = ecc.capture(rule, panel_ceiling, floor)
        print(f"{name:34s} {rule*100:8.2f}% {floor*100:8.2f}% " +
              "".join(f"{o*100:9.2f}%" for o in orc) +
              f"{('n/a' if own is None else f'{own*100:.0f} %'):>10s}"
              f"{('n/a' if pan is None else f'{pan*100:.0f} %'):>11s}")
    print("-" * 110)
    print("`capt own` uses the BEST of that form's own oracle horizons as its ceiling; where the")
    print("oracle prints BELOW the causal rule the ratio exceeds 100 %, and it is deliberately NOT")
    print("clipped — that is #59's diagnosis (a machine that holds 20 days cannot use one-day")
    print("foresight), and clipping would hide the very number that shows it.")


# ═══════════════════════════ #61 — is the forward rank forecastable at all ═══════════════════════════
def bottom_set(scores: "xsd.Scores", books: Sequence[str], i: int, k: int) -> Optional[frozenset]:
    """The k lowest-scoring rankable books on day i, or None when a rank is not defined.

    Same fail-CLOSED convention as the state machine: fewer than k+1 rankable books is not a
    ranking, and ties break by name so the answer does not depend on dict order.
    """
    rankable = [b for b in books if scores[b][i] is not None]
    if len(rankable) <= k:
        return None
    return frozenset(sorted(rankable, key=lambda b: (float(scores[b][i]), b))[:k])


def rank_agreement(panel: "dgo.Panel", k: int = REF_K, lookback: int = LOOKBACK,
                   horizon: int = 1, kind: str = "drift") -> Dict[str, float]:
    """Does the causal bottom-k coincide with the forward bottom-k — against the HONEST null.

    Returns four numbers and they are four different claims:
      • `overlap`  — mean |causal ∩ forward| / k over days where both sets are defined;
      • `chance`   — k/N, what a uniformly random set of k books would score;
      • `majority` — the best CONSTANT set of k books, scored on the same days. #58 learned that
        this, not the coin, is the null that matters: on a panel where some books are persistently
        bad, naming them every day scores high while knowing nothing about tomorrow;
      • `spread`   — mean forward return of the books OUTSIDE the causal bottom-k minus that of
        the books inside it, in basis points per day. This is the economic quantity; the overlap
        is only its proxy, and they can disagree (missing a mildly-bad book is cheap, missing a
        catastrophic one is not). `spread_const` is the same quantity for the constant set, so
        the null is answered in money and not only in set overlap.

    BOTH nulls on the right-hand side are LOOK-AHEAD: `majority` picks the constant set knowing
    every forward set in the sample, and `spread_const` prices that same hindsight-chosen set.
    That is deliberate and it is what makes the comparison a BOUND rather than a horse-race — if
    the causal rank cannot reach a fixed set chosen with hindsight, no ranking of this shape is
    extracting a moving target. It also means the reverse reading is forbidden: `majority` is not
    a strategy and nobody could have held it.

    Strictly causal on the left-hand side: the trailing score at i uses returns through i−1 only,
    which `erd.panel_scores` guarantees and the test-suite re-checks with a mutation control.
    """
    scores = erd.panel_scores(panel, kind, lookback)
    fwd = ecc.forward_scores(panel, horizon)
    books = panel.books

    hits: List[float] = []
    days: List[frozenset] = []
    spread: List[float] = []
    for i in range(panel.n):
        causal = bottom_set(scores, books, i, k)
        future = bottom_set(fwd, books, i, k)
        if causal is None or future is None:
            continue
        days.append(future)
        hits.append(len(causal & future) / k)
        inside = [float(fwd[b][i]) for b in causal]
        outside = [float(fwd[b][i]) for b in books if b not in causal and fwd[b][i] is not None]
        if inside and outside:
            spread.append(sum(outside) / len(outside) - sum(inside) / len(inside))

    freq: Dict[str, int] = {b: 0 for b in books}
    for s in days:
        for b in s:
            freq[b] += 1
    best_const = frozenset(sorted(books, key=lambda b: (-freq[b], b))[:k])
    majority = sum(freq[b] for b in best_const) / (k * len(days)) if days else float("nan")

    const_spread: List[float] = []
    for i in range(panel.n):
        if bottom_set(scores, books, i, k) is None or bottom_set(fwd, books, i, k) is None:
            continue
        inside = [float(fwd[b][i]) for b in best_const if fwd[b][i] is not None]
        outside = [float(fwd[b][i]) for b in books
                   if b not in best_const and fwd[b][i] is not None]
        if inside and outside:
            const_spread.append(sum(outside) / len(outside) - sum(inside) / len(inside))

    return {
        "overlap": sum(hits) / len(hits) if hits else float("nan"),
        "chance": k / len(books),
        "majority": majority,
        "spread_bp": (sum(spread) / len(spread) * 1e4) if spread else float("nan"),
        "spread_const_bp": (sum(const_spread) / len(const_spread) * 1e4)
                           if const_spread else float("nan"),
        "days": float(len(days)),
    }


def idea61_rph(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", k: int = REF_K,
               horizons: Sequence[int] = HORIZONS) -> Dict[int, Dict[str, float]]:
    """Idea #61 — how much of the forward ranking is knowable in advance, at each horizon?"""
    panel = dgo.Panel(subset, start, end)
    print()
    print("=" * 110)
    print(f"IDEA #61 RPH — rank predictability by horizon [{segment}] — {label} "
          f"({panel.n} days, {len(panel.books)} books, k={k}, L={LOOKBACK})")
    print("=" * 110)
    print(f"{'horizon h':>10s} {'overlap':>9s} {'chance':>9s} {'majority':>10s} "
          f"{'edge vs maj':>12s} {'spread bp/d':>12s} {'const bp/d':>11s} {'days':>7s}")
    out: Dict[int, Dict[str, float]] = {}
    for h in horizons:
        m = rank_agreement(panel, k, LOOKBACK, h)
        out[h] = m
        print(f"{h:>10d} {m['overlap']*100:8.1f}% {m['chance']*100:8.1f}% {m['majority']*100:9.1f}% "
              f"{(m['overlap']-m['majority'])*100:>+11.1f}pp {m['spread_bp']:12.2f} "
              f"{m['spread_const_bp']:11.2f} {m['days']:7.0f}")
    print("-" * 110)
    print("`overlap` above `chance` and below `majority` means the trailing window is reproducing a")
    print("standing fact about the panel (some books are persistently worst) and adding nothing")
    print("about tomorrow. That is the reading #58 arrived at for criteria; here it is asked of")
    print("BOOKS, which is what every rule in the family actually ranks.")
    print("[LOOK-AHEAD] the forward set is built from future returns; it is a measuring rod, never a rule.")
    return out


# ═══════════════════════════ controls ═══════════════════════════
def controls(panel: "dgo.Panel", scores: "xsd.Scores", k: int = REF_K,
             cap: Optional[float] = None, seeds: int = SEEDS) -> None:
    """The registry's two information controls, applied to the decoupled corner (R=20, M=1)."""
    flags = decision_hold_flags(scores, k, 1, 1, 20, 1)
    ecr.information_controls(panel, flags, "DHD term-hold D=1 J=1 R=20 M=1", cap=cap, seeds=seeds)


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D #60 DHD / #61 RPH — advisory, read-only")
    ap.add_argument("--idea", type=int, choices=(60, 61), default=None)
    ap.add_argument("--grid", action="store_true")
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

    everything = not (args.grid or args.ceiling or args.controls or args.train_test
                      or args.idea is not None)

    for subset, label in subsets:
        panel = dgo.Panel(subset)
        scores = erd.panel_scores(panel, "drift", LOOKBACK)
        if everything or args.idea == 60:
            idea60_dhd(subset, label, k=args.k)
        if everything or args.grid:
            dhd_grid(panel, scores, args.k)
            phase_table(panel, scores, args.k)
            hold_limit_table(panel, scores, args.k)
        if everything or args.ceiling:
            ceiling_table(panel, scores, args.k)
        if everything or args.controls:
            controls(panel, scores, args.k)
        if everything or args.idea == 61:
            idea61_rph(subset, label, k=args.k)

    if everything or args.train_test:
        print()
        print("=" * 110)
        print(f"TRAIN → TEST (split {TRAIN_END}) — every knob was fixed BEFORE the split, see docstring")
        print("=" * 110)
        ecr.train_test(idea60_dhd, [f"#40 XSD published  {_cfg(1, 1, 0, REF_M)}",
                                    f"daily/no-hold      {_cfg(1, 1, 0, 1)}",
                                    f"TERM hold          {_cfg(1, 1, 20, 1)}",
                                    f"TERM hold          {_cfg(1, 1, 40, 1)}",
                                    f"SLOW decide        {_cfg(20, 1, 0, 1)}"])
        for seg, s, e in (("TRAIN", None, TRAIN_END), ("TEST", TRAIN_END, None)):
            idea61_rph(None, "all real books", start=s, end=e, segment=seg, k=args.k)
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
