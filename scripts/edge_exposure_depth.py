#!/usr/bin/env python3
"""Edge R&D — registry ideas #47 (PDD) and #48 (PKP): HOW DEEP to cut, not WHICH book to cut.

WHERE THIS COMES FROM
  Entries #37–#46 are one long argument about a single question: *which* book should leave the
  portfolio. Trailing drift (#39/#40), bad-day return (#41), dispersion-gated and z-scored drift
  (#42/#43), redundancy (#44), volatility (#45) — six criteria, one machinery, one verb. In every
  one of them the verb is binary and its depth was never a variable: a demoted book goes to
  **exactly zero** and its slice is recycled to the others, because that is what #38 established
  as the allocator convention and nobody has questioned it since.

  Two things in the registry's own text say the depth axis is the missing one.

    1. #40's structural limit, restated in every entry after it: *"a bottom-k rule always keeps
       100% of capital deployed; it can turn capital away from the worst book and CANNOT take the
       portfolio down; any deployment MUST keep a separate absolute portfolio-level kill path."*
       That sentence has been printed six times and measured zero times.
    2. #45's cheapest-in-registry turnover (0.37/yr against #40's 4.35) bought its netAPY edge
       with **less trading**, not better timing. Cost is the binding constraint on this family, and
       the on/off switch is the most expensive possible way to express a ranking: it moves 1/N of
       the book each time it fires, whatever the strength of the signal.

  So this module adds the axis both observations point at — DEPTH — at the two levels where it
  exists, and it does that without inventing a new criterion, a new panel or a new allocator.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #47 — PDD: Partial Demotion Depth  ("demotion is a dial, not a switch")
──────────────────────────────────────────────────────────────────────────────────────────────
      criterion, k, M, L, panel, costs : #40 XSD, byte-for-byte — nothing here is re-tuned
      w_b(t) = (1 − h) / N              for the k demoted books      ← the ONLY new parameter
      the freed h·k/N is water-filled over the eligible books, capped at `cap` as usual

  The two endpoints are exact, not approximate, and the test-suite pins both:
      h = 0 → every weight is 1/N ⇒ the row IS raw equal weight
      h = 1 → demoted weight is 0  ⇒ the row IS `ecr.alloc_recycle`, i.e. #40 itself
  Everything between them is a continuum the registry has never priced. Three outcomes, all
  publishable, written down before the numbers:

    A. ΔCalmar monotone in h  → the SWITCH is the mechanism; partial cuts are a strictly worse
       version of #40 and the depth axis is closed. (#40 keeps its numbers, and this entry is the
       control that says the convention was right.)
    B. interior maximum in net terms → the switch OVERPAYS: the same selection information is
       worth more when expressed at partial depth, because turnover falls faster than the gross
       edge does. That is a cheaper, less concentrated and more deliverable version of the
       registry leader — and, per #46, one that sits further from the 20% per-name cap.
    C. ΔCalmar flat in h → depth carries nothing, the number belongs entirely to the ranking, and
       the family's whole cost profile is a free parameter that should be set to the cheapest end.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #48 — PKP: Portfolio Kill Path  ("what does OUR OWN kill-switch cost on top of the best rule")
──────────────────────────────────────────────────────────────────────────────────────────────
  #46 asked what our 20% per-name cap costs and answered: nothing, it sits at the optimum. This is
  the same question for the other mandatory constraint — the two-tier kill-switch of ADR-034/048,
  the arm #40 says every deployment of this family MUST carry:

      dd(t)   = peak-to-current drawdown of the REALISED portfolio through t−1 (causal)
      dd ≥ 10% (HARD_KILL)  → gross exposure 0, absorbing (production requires an owner to re-arm)
      5% ≤ dd < 10% (SOFT)  → "halt new / no INCREASE": w_b(t) = min(target_b(t), w_b(t−1))
      otherwise             → the selection rule's weights, untouched

  The SOFT leg is implemented as the ladder actually defines it — a freeze, not a liquidation
  (`mode="freeze"`). A proportional haircut (`mode="haircut"`) is ALSO reported, clearly labelled,
  because a haircut is a STRONGER action than the production tier and reading it as the tier
  would misstate what the project does.

  What can come out of this, again written before the numbers: on this panel raw maxDD is −5.44%
  and #40's is −3.37%, so the 5% tier may never fire at all on the good rules. If so the honest
  reading is *"the kill path costs exactly zero here — and this sample contains nothing for it to
  protect against"*, which is a statement about the SAMPLE, not a licence to drop the arm. The
  threshold is therefore swept below the ladder's own 5% to find where a portfolio arm would start
  to bind, and what it buys when it does.

HONESTY / SCOPE (registry rules — non-negotiable)
  • Strictly causal everywhere: scores for day i use returns through i−1; the kill tier for day i
    uses the equity path through i−1. Both pinned in both directions by the test-suite.
  • Panel, allocator, cost model (48bp per one-way leg of turnover = #10's 96bp round trip),
    L=60, k, M and the train/test split are IMPORTED from #32/#38/#39/#40, never re-derived.
    Books are regenerated nightly, so numbers reproduce only against the panel files of the run
    date (2026-08-10: 10 books, 852 days, raw 17.94% / −5.44% / Calmar 3.30).
  • Read-only. Writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0 nor the kill-switch thresholds. Evidence L0 (backtest on real feed
    history, NOT live). IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_exposure_depth.py                 # everything
    python3 scripts/edge_exposure_depth.py --idea 47       # PDD only
    python3 scripts/edge_exposure_depth.py --idea 48       # PKP only
    python3 scripts/edge_exposure_depth.py --sweep         # the (k × h) grid only
    python3 scripts/edge_exposure_depth.py --controls      # permutation / rotation on the best h
"""
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
REF_K, REF_M = 2, 20             # #40's reference cell, so every depth row is like-for-like
CONC_CAP = ecr.CONC_CAP          # 0.20 — the project's own per-name cap (RiskPolicy v1.0)
EPS = ecr.EPS

# The project's own two-tier ladder (ADR-034 / ADR-048). Read here, never written.
SOFT_DD = 0.05
HARD_DD = 0.10

DEPTHS: Tuple[float, ...] = (0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0)


# ═══════════════════════════ #47 — depth-aware allocator ═══════════════════════════
def alloc_partial(books: Sequence[str], flags: Dict[str, Sequence[bool]], n: int,
                  haircut: float, cap: Optional[float] = None) -> Dict[str, List[float]]:
    """`ecr.alloc_recycle` with the demotion turned from a switch into a dial.

    A demoted book keeps `(1 − haircut)/N` instead of zero; the freed capital is split equally
    over the books that are NOT demoted today, each clipped at `cap` with the remainder left as
    cash — the same treatment `ecr._waterfill` gives an over-capped panel, so a cap can never be
    silently breached.

    Exact at both ends by construction (pinned by the test-suite):
        haircut == 0.0 ⇒ every weight is 1/N            (raw equal weight)
        haircut == 1.0 ⇒ `ecr.alloc_recycle` verbatim   (#40's convention)

    Fail-CLOSED when NOTHING is eligible: the demoted books keep their reduced weight and the
    freed slice stays in cash rather than being pushed back into books the rule just cut.
    """
    if not 0.0 <= haircut <= 1.0:
        raise ValueError("haircut must lie in [0, 1] — outside it this is no longer a demotion")
    if cap is not None and cap <= 0.0:
        raise ValueError("cap must be positive — a zero cap is not an allocation rule")
    books = list(books)
    base = 1.0 / len(books)
    out: Dict[str, List[float]] = {b: [0.0] * n for b in books}
    for i in range(n):
        demoted = [b for b in books if flags[b][i]]
        eligible = [b for b in books if not flags[b][i]]
        kept = (1.0 - haircut) * base
        for b in demoted:
            out[b][i] = kept
        if not eligible:
            continue                       # fail-CLOSED: freed capital waits in cash
        budget = 1.0 - kept * len(demoted)
        share = budget / len(eligible)
        if cap is not None and share > cap + EPS:
            share = cap                    # the rest does not fit inside the limit ⇒ cash
        for b in eligible:
            out[b][i] = share
    return out


def _depth_rows(panel: "dgo.Panel", kind: str, k: int, m_days: int,
                depths: Sequence[float] = DEPTHS,
                cap: Optional[float] = None) -> List[Tuple[str, Dict[str, List[float]], float]]:
    """One row per depth, plus the controls every row of this family is read against."""
    sc = erd.panel_scores(panel, kind)
    flags = xsd.rank_demotion_flags(sc, k, m_days)
    books, n = panel.books, panel.n
    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    rows.append(("#39 CDR absolute M=20",
                 ecr.alloc_recycle(books, xsd.absolute_flags(panel, xsd.HURDLE, LOOKBACK, 20), n), 0.0))
    for h in depths:
        tag = "raw equal weight" if h == 0.0 else ("#40 XSD (h=1.00)" if h == 1.0 else "")
        label = f"PDD h={h:.2f} k={k} M={m_days}" + (f"  [{tag}]" if tag else "")
        rows.append((label, alloc_partial(books, flags, n, h, cap=cap), 0.0))

    best_ref = alloc_partial(books, flags, n, 0.5, cap=cap)
    rows.append(("  CONTROL static twin of h=0.50", ecr.alloc_static_matched(best_ref), 0.0))
    rows.append(("  CONTROL static twin of h=1.00",
                 ecr.alloc_static_matched(alloc_partial(books, flags, n, 1.0, cap=cap)), 0.0))
    rows.append(("  CONTROL top-k flip h=1.00",
                 alloc_partial(books, xsd.rank_demotion_flags(sc, k, m_days, worst_first=False),
                               n, 1.0, cap=cap), 0.0))
    rows.append((f"  under {int(CONC_CAP*100)}% per-name cap h=1.00",
                 alloc_partial(books, flags, n, 1.0, cap=CONC_CAP), 0.0))
    return rows


def idea47_pdd(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               kind: str = "drift", k: int = REF_K, m_days: int = REF_M,
               depths: Sequence[float] = DEPTHS) -> Dict[str, Dict[str, float]]:
    """Idea #47 — does the cross-sectional edge live in the RANKING or in the ON/OFF switch?"""
    panel = dgo.Panel(subset, start, end)
    rows = _depth_rows(panel, kind, k, m_days, depths)
    out = xsd._report(f"IDEA #47 PDD — partial demotion depth [{segment}] — {label}",
                      panel, rows, quiet)
    if not quiet:
        print("-" * 110)
        print("h=0.00 and h=1.00 are not approximations of raw and of #40 — they ARE those rows,")
        print("which is why this table can be read as a single continuous knob rather than a menu.")
    return out


def depth_sweep(kind: str = "drift", ks: Sequence[int] = (1, 2, 3, 4, 5),
                depths: Sequence[float] = DEPTHS, m_days: int = REF_M) -> None:
    """The (k × depth) grid — ΔCalmar and netAPY side by side, because they can disagree."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = erd.panel_scores(panel, kind)
    print()
    print("=" * 110)
    print(f"DEPTH SWEEP — {kind} criterion, M={m_days}  ·  raw Calmar {base['calmar']:.2f}, "
          f"raw APY {base['apy']*100:.2f}%")
    print("=" * 110)
    for metric in ("ΔCalmar", "netAPY", "turnover/yr", "maxW"):
        print(f"\n{metric}:")
        print("k \\ h    " + "".join(f"{h:>9.2f}" for h in depths))
        for k in ks:
            flags = xsd.rank_demotion_flags(sc, k, m_days)
            cells = []
            for h in depths:
                m = ecr.portfolio_metrics(panel, alloc_partial(panel.books, flags, panel.n, h))
                cells.append({"ΔCalmar": m["calmar"] - base["calmar"],
                              "netAPY": m["net_apy_after_cost"] * 100.0,
                              "turnover/yr": m["turnover_yr"],
                              "maxW": m["max_weight"] * 100.0}[metric])
            print(f"{k:<9d}" + "".join(f"{c:>9.2f}" for c in cells))


def depth_information_controls(kind: str = "drift", k: int = REF_K, m_days: int = REF_M,
                               haircut: float = 0.5, seeds: int = 20) -> None:
    """#38's two controls, run against the DEPTH allocator instead of the on/off one.

    Permutation destroys WHICH-book information, rotation destroys WHEN information. Duty, the
    switch structure and the depth are identical in every twin — only the alignment is broken.
    """
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    flags = xsd.rank_demotion_flags(erd.panel_scores(panel, kind), k, m_days)
    real = ecr.portfolio_metrics(panel, alloc_partial(panel.books, flags, panel.n, haircut))
    print()
    print("=" * 110)
    print(f"INFORMATION CONTROLS — PDD h={haircut:.2f} k={k} M={m_days} "
          f"({seeds} book-permutations, rotations every 30d)")
    print("=" * 110)
    print(ecr._COLS)
    ecr._row("REAL alignment", real, base)

    perm = [ecr.portfolio_metrics(panel, alloc_partial(
        panel.books, ecr.permuted_flags(flags, panel.books, s), panel.n, haircut))
        for s in range(seeds)]
    ps = sorted(perm, key=lambda m: m["calmar"])
    for tag, m in (("perm P10", ps[max(0, int(0.1 * seeds) - 1)]),
                   ("perm P50 (median)", ps[seeds // 2]),
                   ("perm P90", ps[min(seeds - 1, int(0.9 * seeds))])):
        ecr._row(f"  CONTROL {tag}", m, base)
    beaten = sum(1 for m in perm if m["calmar"] >= real["calmar"])
    print(f"  → permutations reaching the real Calmar: {beaten}/{seeds}"
          f"   (empirical p ≈ {(beaten + 1) / (seeds + 1):.3f})")

    shifts = list(range(30, panel.n, 30))
    sm = [ecr.portfolio_metrics(panel, alloc_partial(
        panel.books, ecr.shifted_flags(flags, panel.books, s), panel.n, haircut)) for s in shifts]
    ss = sorted(sm, key=lambda m: m["calmar"])
    kk = len(ss)
    for tag, m in ((f"shift P50 (of {kk})", ss[kk // 2]), ("shift BEST", ss[-1])):
        ecr._row(f"  CONTROL time-{tag}", m, base)
    beaten_s = sum(1 for m in sm if m["calmar"] >= real["calmar"])
    print(f"  → rotations reaching the real Calmar: {beaten_s}/{kk}"
          f"   (empirical p ≈ {(beaten_s + 1) / (kk + 1):.3f})")


# ═══════════════════════════ #48 — portfolio kill path ═══════════════════════════
def apply_kill_path(panel: "dgo.Panel", target: Dict[str, List[float]],
                    soft_dd: float = SOFT_DD, hard_dd: float = HARD_DD,
                    mode: str = "freeze", soft_gross: float = 0.5,
                    hard_rearm_days: Optional[int] = None
                    ) -> Tuple[Dict[str, List[float]], Dict[str, float]]:
    """Overlay the project's own two-tier ladder on ANY set of per-book target weights.

    Causal by construction: the tier for day i is decided from the equity path through i−1, so no
    day's exposure can depend on its own return. Pinned in both directions by the test-suite.

    Tier semantics, kept faithful to ADR-034/048 rather than convenient:
      • HARD_KILL (dd ≥ `hard_dd`) is ABSORBING — production requires an owner to re-arm, and a
        backtest that quietly re-armed itself would be reporting a rule nobody sanctioned.
      • SOFT_DERISK (`soft_dd` ≤ dd < `hard_dd`) with mode="freeze" is *halt new / no INCREASE*:
        a book's weight may fall but never rise, and the released capital goes to cash rather
        than to another book (moving it WOULD be an increase somewhere). This is the tier as
        written. mode="haircut" scales every weight by `soft_gross` — a STRICTLY STRONGER action
        than the production tier, reported only as a labelled sensitivity.

    `hard_rearm_days` is a COUNTERFACTUAL, not the production rule: when set, the kill clears once
    the UN-GATED target portfolio (the "shadow" path the rule would have taken) has been out of
    its own `hard_dd` drawdown for that many consecutive days. It exists to put a number on what
    the owner-in-the-loop re-arm of ADR-034 costs while it waits, and is always labelled as such.
    The shadow path uses only returns through i−1, so it is as causal as the realised one.

    Returns (weights, diagnostics) where diagnostics counts the days each tier was active — a
    rule that never fires must say so out loud instead of posting an unchanged table.
    """
    if mode not in ("freeze", "haircut"):
        raise ValueError(f"unknown SOFT mode {mode!r}")
    if not 0.0 < soft_dd <= hard_dd:
        raise ValueError("thresholds must satisfy 0 < soft_dd <= hard_dd")
    if hard_rearm_days is not None and hard_rearm_days < 1:
        raise ValueError("hard_rearm_days must be >= 1 — re-arming on no evidence is not a rule")
    books, n = panel.books, panel.n

    shadow_dd = [0.0] * n                              # drawdown of the UN-GATED target path
    eq = pk = 1.0
    for i in range(n):
        shadow_dd[i] = eq / pk - 1.0
        eq *= 1.0 + sum(target[b][i] * panel.rets[b][i] for b in books)
        pk = max(pk, eq)

    out: Dict[str, List[float]] = {b: [0.0] * n for b in books}
    prev: Dict[str, float] = {b: 0.0 for b in books}
    equity = peak = 1.0
    killed = False
    clear_run = 0
    soft_days = hard_days = 0
    worst_dd = 0.0

    for i in range(n):
        dd = equity / peak - 1.0                       # equity holds returns through i−1 only
        worst_dd = min(worst_dd, dd)
        # Re-arm is evaluated FIRST and against the SHADOW path, deliberately. While the kill is
        # on, live equity is flat, so the realised drawdown never moves — checking the realised path
        # for recovery would be a state machine that can only ever latch, and the counterfactual
        # would silently report the absorbing rule under a different name.
        if killed and hard_rearm_days is not None:
            clear_run = clear_run + 1 if shadow_dd[i] > -hard_dd else 0
            if clear_run >= hard_rearm_days:
                killed = False
                clear_run = 0
                # Re-baseline the peak to the level trading resumes from. Without this the
                # historical peak would still sit ≥ hard_dd above the live NAV and the switch
                # would fire again on the same day — a re-arm that cannot re-arm. Stated because
                # it means the ladder's guarantee after a re-arm is measured from the NEW peak.
                peak = equity
                dd = 0.0
        if not killed and dd <= -hard_dd:
            killed = True
            clear_run = 0
        if killed:
            w = {b: 0.0 for b in books}
            hard_days += 1
        elif dd <= -soft_dd:
            soft_days += 1
            if mode == "freeze":
                w = {b: min(target[b][i], prev[b]) for b in books}
            else:
                w = {b: soft_gross * target[b][i] for b in books}
        else:
            w = {b: target[b][i] for b in books}
        r = sum(w[b] * panel.rets[b][i] for b in books)
        equity *= 1.0 + r
        peak = max(peak, equity)
        for b in books:
            out[b][i] = w[b]
            prev[b] = w[b]
    return out, {"soft_days": float(soft_days), "hard_days": float(hard_days),
                 "worst_dd_seen": worst_dd}


def _bases(panel: "dgo.Panel") -> List[Tuple[str, Dict[str, List[float]]]]:
    """The selection rules the kill path is priced on top of — the registry's own leaders."""
    books, n = panel.books, panel.n
    drift = erd.panel_scores(panel, "drift")
    vol = erd.panel_scores(panel, "volatility")
    return [
        ("raw equal weight", {b: [1.0 / len(books)] * n for b in books}),
        ("#39 CDR absolute M=20",
         ecr.alloc_recycle(books, xsd.absolute_flags(panel, xsd.HURDLE, LOOKBACK, 20), n)),
        ("#40 XSD k=2 M=20",
         ecr.alloc_recycle(books, xsd.rank_demotion_flags(drift, REF_K, REF_M), n)),
        ("#45 XVD k=1 M=1",
         ecr.alloc_recycle(books, xsd.rank_demotion_flags(vol, 1, 1), n)),
    ]


def idea48_pkp(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               soft_dds: Sequence[float] = (0.05, 0.04, 0.03, 0.02, 0.015, 0.01),
               ) -> Dict[str, Dict[str, float]]:
    """Idea #48 — price the mandatory portfolio-level kill path on top of the registry's leaders."""
    panel = dgo.Panel(subset, start, end)
    base = ecr._raw_metrics(panel)
    results: Dict[str, Dict[str, float]] = {}
    if not quiet:
        print()
        print("=" * 122)
        print(f"IDEA #48 PKP — portfolio kill path [{segment}] — {label}  ·  {panel.n} days "
              f"{panel.axis[0]}..{panel.axis[-1]}")
        print("=" * 122)
        print(f"raw equal-weight: APY {base['apy']*100:.2f}%  maxDD {base['maxdd']*100:.2f}%  "
              f"Calmar {base['calmar']:.2f}   ·   softD/hardD = days the tier was ACTIVE")
        print(f"{'configuration':46s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔCalmar':>8s} "
              f"{'depl':>6s} {'turn/yr':>8s} {'netAPY':>8s} {'softD':>6s} {'hardD':>6s}")

    for name, target in _bases(panel):
        rows: List[Tuple[str, Dict[str, List[float]], Dict[str, float]]] = [
            (f"{name}  [no kill arm]", target, {"soft_days": 0.0, "hard_days": 0.0})]
        for s in soft_dds:
            w, diag = apply_kill_path(panel, target, soft_dd=s, hard_dd=HARD_DD, mode="freeze")
            rows.append((f"  + ladder freeze {s*100:.1f}%/10%", w, diag))
        w, diag = apply_kill_path(panel, target, soft_dd=SOFT_DD, hard_dd=HARD_DD,
                                  mode="haircut", soft_gross=0.5)
        rows.append(("  + ladder haircut 0.5 (STRONGER than the tier)", w, diag))
        for rname, w, diag in rows:
            m = ecr.portfolio_metrics(panel, w)
            results[rname.strip()] = dict(m, **diag)
            if not quiet:
                print(f"{rname:46s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% "
                      f"{m['calmar']:8.2f} {m['calmar']-base['calmar']:8.2f} "
                      f"{m['deployed']*100:5.0f}% {m['turnover_yr']:8.2f} "
                      f"{m['net_apy_after_cost']*100:7.2f}% {int(diag['soft_days']):6d} "
                      f"{int(diag['hard_days']):6d}")
        if not quiet:
            print("-" * 122)
    return results


class _ScaledPanel:
    """A panel whose every daily return is multiplied by `mult`. A CONTROL, never a market claim.

    The 852 real days never take any of these rules past −5.44%, so the ladder's own thresholds
    are outside the sample and "it cost nothing" is untestable in the direction that matters. This
    amplification is the positive control the deployment rule demands: it manufactures drawdowns
    deep enough for the tiers to fire, so the question becomes "when the ladder DOES fire, does it
    help or hurt?" — a property of the RULE, which amplification preserves, rather than of the
    market, which it destroys. Evidence for any number produced here is L0-synthetic and must be
    labelled as such wherever it is quoted.
    """

    def __init__(self, panel: "dgo.Panel", mult: float) -> None:
        if mult <= 0.0:
            raise ValueError("mult must be positive — a non-positive scale is not an amplification")
        self.books = list(panel.books)
        self.axis = list(panel.axis)
        self.rets = {b: [r * mult for r in panel.rets[b]] for b in self.books}

    @property
    def n(self) -> int:
        return len(self.axis)

    def raw_portfolio(self) -> List[float]:
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]


def amplified_stress(mults: Sequence[float] = (2.0, 3.0, 4.0)) -> None:
    """Does the ladder help WHEN IT FIRES? Answered on an amplified panel, honestly labelled."""
    real = dgo.Panel()
    drift = erd.panel_scores(real, "drift")
    xsd_flags = xsd.rank_demotion_flags(drift, REF_K, REF_M)
    print()
    print("=" * 110)
    print("POSITIVE CONTROL — returns amplified until the ladder actually fires (SYNTHETIC, L0)")
    print("=" * 110)
    print(f"{'panel × mult · configuration':44s} {'APY':>9s} {'maxDD':>9s} {'Calmar':>8s} "
          f"{'depl':>6s} {'softD':>6s} {'hardD':>6s}")
    for mult in mults:
        p = _ScaledPanel(real, mult)
        bases = [("raw equal weight", {b: [1.0 / len(p.books)] * p.n for b in p.books}),
                 ("#40 XSD k=2 M=20", ecr.alloc_recycle(p.books, xsd_flags, p.n))]
        for name, target in bases:
            variants = [("no kill arm", target, {"soft_days": 0.0, "hard_days": 0.0})]
            for tag, kw in (("ladder freeze 5%/10%", dict(mode="freeze")),
                            ("ladder haircut 0.5", dict(mode="haircut", soft_gross=0.5)),
                            ("freeze + auto re-arm 5d [counterfactual]",
                             dict(mode="freeze", hard_rearm_days=5)),
                            ("freeze + auto re-arm 20d [counterfactual]",
                             dict(mode="freeze", hard_rearm_days=20))):
                w, diag = apply_kill_path(p, target, soft_dd=SOFT_DD, hard_dd=HARD_DD, **kw)
                variants.append((tag, w, diag))
            for tag, w, diag in variants:
                m = ecr.portfolio_metrics(p, w)
                print(f"{f'×{mult:.0f} {name} · {tag}':44s} {m['apy']*100:8.2f}% "
                      f"{m['maxdd']*100:8.2f}% {m['calmar']:8.2f} {m['deployed']*100:5.0f}% "
                      f"{int(diag['soft_days']):6d} {int(diag['hard_days']):6d}")
        print("-" * 110)
    print("Amplification scales returns, NOT the calendar: it preserves the sign, ordering and")
    print("timing of every book-day and only makes the drawdowns deep enough to cross the tiers.")


def kill_path_binding(panel: Optional["dgo.Panel"] = None) -> None:
    """How deep does each rule's WORST realised drawdown go — i.e. can the ladder fire at all?"""
    panel = panel or dgo.Panel()
    print()
    print("=" * 110)
    print("WHERE THE LADDER BINDS — worst realised drawdown of each rule, against the two tiers")
    print("=" * 110)
    print(f"{'rule':34s} {'maxDD':>9s} {'SOFT 5%':>9s} {'HARD 10%':>10s} {'binds at':>10s}")
    for name, target in _bases(panel):
        m = ecr.portfolio_metrics(panel, target)
        dd = m["maxdd"]
        # the shallowest threshold that would have fired at all, to 1bp
        fires = "never" if dd > -0.0001 else f"{-dd*100:.2f}%"
        print(f"{name:34s} {dd*100:8.2f}% {'FIRES' if dd <= -SOFT_DD else 'silent':>9s} "
              f"{'FIRES' if dd <= -HARD_DD else 'silent':>10s} {fires:>10s}")
    print("\nA tier that never fires costs exactly zero AND protects against exactly nothing that")
    print("is inside this sample. That is a statement about the sample, not a licence to drop the")
    print("arm: the events the ladder exists for are the ones 852 days of this panel do not hold.")


# ═══════════════════════════════ CLI ═══════════════════════════════
def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D — ideas #47 (PDD) and #48 (PKP)")
    ap.add_argument("--idea", type=int, choices=(47, 48), default=None)
    ap.add_argument("--sweep", action="store_true", help="the (k × depth) grid only")
    ap.add_argument("--controls", action="store_true", help="permutation / rotation only")
    ap.add_argument("--traintest", action="store_true")
    ap.add_argument("--loo", action="store_true")
    ap.add_argument("--haircut", type=float, default=0.5)
    args = ap.parse_args(argv)

    if args.sweep:
        depth_sweep()
        return 0
    if args.controls:
        depth_information_controls(haircut=args.haircut)
        return 0
    if args.traintest:
        ecr.train_test(idea47_pdd, [f"PDD h={h:.2f} k={REF_K} M={REF_M}" for h in (0.4, 0.5, 0.6)]
                       + ["CONTROL static twin of h=0.50"])
        return 0
    if args.loo:
        ecr.leave_one_out(idea47_pdd, f"PDD h={args.haircut:.2f} k={REF_K} M={REF_M}")
        return 0

    if args.idea in (None, 47):
        idea47_pdd()
        depth_sweep()
    if args.idea in (None, 48):
        kill_path_binding()
        idea48_pkp()
        amplified_stress()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
