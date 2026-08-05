#!/usr/bin/env python3
"""Edge R&D — ideas #35 (DGO) and #36 (RARE), both derived from the MEASUREMENT of #32.

Idea #32 (`scripts/edge_calm_fp_tax.py`) established two facts on the REAL 10-book panel that
inverted the fixture-era leaderboard:

  1. **Reactivity law** — corr(switches/yr, ΔCalmar) = −0.78 across 15 configurations: the more
     reactive the de-risk signal, the more value it destroys.
  2. **Rebound forfeit** — the mean RAW return of the days an overlay sits de-risked is strongly
     POSITIVE inside a drawdown (+20…+57 bp/day). The overlay cuts exposure after the loss has
     landed and is still in cash while the book climbs back, so maxDD gets DEEPER, not shallower.

#32's practical conclusion was stated as a claim, never as a testable rule: *"a de-risk overlay is
a bet AGAINST your own book; it pays only where the book has negative drift"* — the one book the
overlay helped everywhere was `eth_directional` (−26% APY). Two questions follow, and this script
answers exactly those two, each with the control that could refute it.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #35 — DGO: Drift-Gated Overlay  ("apply the overlay to the books that deserve it")
──────────────────────────────────────────────────────────────────────────────────────────────
    DEFEND(book, t) = base_signal(book, t)  AND  drift_L(book, t−1) < 0
    otherwise: full exposure

The de-risk decision stops being universal and becomes SELECTIVE: a book whose own causal
trailing drift is negative may defend; a positively-drifting book may not (defending it is the
bet-against-yourself #32 measured). This is a composition rule, not a new trigger — it is the
first registry idea that changes WHICH BOOKS an overlay is allowed to touch rather than WHEN.

Controls (all three are required, otherwise a positive number proves nothing):
  • inverse gate — overlay allowed only where drift ≥ 0. Must be clearly WORSE if the reading holds.
  • oracle gate  — full-sample drift sign (LOOK-AHEAD, labelled as such): the upper bound of what
    perfect book-selection is even worth. Causal DGO can only ever capture a fraction of it.
  • drift-only   — de-risk whenever drift_L < 0, with no fast signal at all. This is the control
    that matters most: a slow trend gate IS a trend signal (cf. ecdr#23, the only #32 survivor),
    so unless the composition beats the gate ALONE, DGO is ecdr#23 wearing a new name.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #36 — RARE: Rebound-Asymmetric Re-Entry  ("stop paying for the recovery leg")
──────────────────────────────────────────────────────────────────────────────────────────────
    DEFEND_rare(t) = DEFEND_base(t)  AND NOT (r(t−1) > 0)

#32 measured that the loss channel is the EXIT, not the entry: the days an overlay sits out land
on the recovery leg. RARE deletes exactly those days — it may only ever REMOVE de-risk days from
the base signal, never add them. Controls run the opposite direction: `dwell(k)`, a latch that
stays out until k consecutive up-days confirm a rebound, which can only ADD days out.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #37 — SDS: Slow Drift-Sign De-Risk  (#35's own control, promoted to a hypothesis)
──────────────────────────────────────────────────────────────────────────────────────────────
    DEFEND(t) = mean(r[t−L : t−1]) < hurdle/365

Registered separately because it beat every composite it was built to falsify. With L=10 and
hurdle=r_f it IS kods#15, so the question it asks is sharp: was the μ-family's failure a property
of the family, or only of the fast lookback it was always run with? It is put through a
lookback × hurdle sweep, a TRAIN-selected → TEST run, a per-book decomposition and a
leave-one-out — the last of which is what decides it.

──────────────────────────────────────────────────────────────────────────────────────────────
HONESTY / SCOPE (registry rules)
──────────────────────────────────────────────────────────────────────────────────────────────
  • Every state is strictly causal — decided from information through t−1 only. Pinned in BOTH
    directions by the test-suite (a shock on day i must NOT move exposure on day i, and MUST move
    it from day i+1).
  • The clean panel loader of #32 is IMPORTED, not re-implemented: it cuts the phase="forward"
    row (an accounting re-anchor that a phase-blind diff reads as a −31…−84% day) and refuses any
    unexplained same-block jump. Numbers are reproducible only against the panel files of the run
    date — the books are REGENERATED, not appended (card `agent-aggressive-lab-books-are-regenerated`).
  • Read-only: writes nothing under data/, imports no execution code, touches neither the live
    track nor RiskPolicy v1.0. Evidence level L0 (backtest over real feed history, NOT live).
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY.
  • Turnover cost of #10 (~96 bp per switch) is reported next to every headline, because #32
    showed 12 of 15 configurations die there.

Usage:
    python3 scripts/edge_drift_gated_overlay.py            # everything
    python3 scripts/edge_drift_gated_overlay.py --idea 35  # DGO only
    python3 scripts/edge_drift_gated_overlay.py --idea 36  # RARE + the dwell follow-through
    python3 scripts/edge_drift_gated_overlay.py --idea 37  # SDS only
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt   # noqa: E402  (audited loader + metrics of idea #32)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

TRAIN_END = cfpt.TRAIN_END          # "2025-06-30"
DRIFT_LOOKBACK = 90                 # days of causal trailing mean used as the drift estimate
COST_BP_PER_SWITCH = 96.0           # idea #10's measured round-trip cost
BP = cfpt.BP


# ─────────────────────────────── weights helpers ───────────────────────────────
def binary(flags: Sequence[bool]) -> List[float]:
    """DEFEND → 0 exposure, otherwise 1 (the registry's convention: 1.0 == the raw book)."""
    return [0.0 if f else 1.0 for f in flags]


def switches(weights: Sequence[float]) -> int:
    """Number of transitions INTO a de-risked state (the unit idea #10 prices)."""
    out, prev = 0, False
    for w in weights:
        act = (1.0 - w) >= cfpt.DERISK_EPS
        if act and not prev:
            out += 1
        prev = act
    return out


# ─────────────────────────────── idea #35 — DGO ───────────────────────────────
def drift_gate(returns: Sequence[float], lookback: int = DRIFT_LOOKBACK) -> List[bool]:
    """True on days the book's CAUSAL trailing drift is negative ⇒ the overlay may act.

    Causal by construction: `trailing_mean` averages returns[i-lookback:i], i.e. it stops at
    t−1. Before `lookback` points exist the gate is CLOSED (False) — fail-CLOSED: an unmeasured
    drift is not permission to de-risk. Same predicate as `sds_signal(..., thr_annual=0)`, and
    it is defined through it so the gate of #35 and the signal of #37 can never drift apart.
    """
    return sds_signal(returns, lookback, 0.0)


def drift_gate_inverse(returns: Sequence[float], lookback: int = DRIFT_LOOKBACK) -> List[bool]:
    """Control: permission on POSITIVE trailing drift instead. Disjoint from `drift_gate`
    wherever the drift is measurable; their union is exactly 'drift is measurable'."""
    mu = cfpt.trailing_mean(returns, lookback)
    return [(i >= lookback) and (mu[i] >= 0.0) for i in range(len(returns))]


def drift_gate_oracle(returns: Sequence[float]) -> List[bool]:
    """LOOK-AHEAD control: permission iff the book's FULL-SAMPLE mean return is negative.

    Not a strategy — it cannot be run live and is never proposed as one. It is the ceiling:
    how much book-selection is worth when the drift sign is known for free. Causal DGO must be
    read as a fraction of this number.
    """
    n = len(returns)
    if n == 0:
        return []
    negative = (sum(returns) / n) < 0.0
    return [negative] * n


def gated_weights(base: Sequence[float], gate: Sequence[bool]) -> List[float]:
    """Apply the base overlay only where the gate permits; elsewhere hold full exposure."""
    return [base[i] if gate[i] else 1.0 for i in range(len(base))]


# ─────────────────────────────── idea #36 — RARE ───────────────────────────────
# Two re-entry rules, in opposite directions. Both act ONLY on the exit side; neither touches
# the entry trigger, so any difference from the base row is attributable to re-entry alone.
#
# The registry's baseline overlay is FLAG-ONLY: exposure is cut exactly on the days the signal
# flags and restored the moment it clears. That baseline already carries the rebound forfeit
# #32 measured, so "faster re-entry" has to mean SUBTRACTING flagged days, not shortening a
# dwell that the baseline does not have. Both directions are measured, because the first run of
# this script implemented only the additive one and it moved duty the wrong way — recorded here
# rather than silently replaced.
def veto_after_up(defend: Sequence[bool], returns: Sequence[float]) -> List[bool]:
    """RARE proper (subtractive): never sit out on the day after the book printed an up-day.

        DEFEND_rare(t) = DEFEND_base(t)  AND NOT (r(t−1) > 0)

    #32 measured that the days an overlay sits out inside a drawdown average +20…+57 bp — it is
    holding cash through the recovery leg. This deletes exactly the days that follow a positive
    print, which is the cheapest causal proxy for "the rebound has started". Strictly causal:
    r(t−1) is observed before day t. Duty can only go DOWN relative to the base flag.
    """
    return [defend[i] and not (i >= 1 and returns[i - 1] > 0.0) for i in range(len(defend))]


def dwell_weights(returns: Sequence[float], defend: Sequence[bool],
                  k_positive: int = 1) -> List[float]:
    """The additive direction (control): a latch that stays out until k up-days confirm a rebound.

        IN  →  OUT : defend[i] is True
        OUT →  IN  : the last `k_positive` observed days (…, r[i−1]) were all > 0
                     — evaluated BEFORE the flag, so a trigger that is STILL asserted re-arms
                     the latch on the same day (an up-print does not overrule a live trigger);
                     the rebound rule decides re-entry only once the trigger has cleared

    This is hysteresis, not fast re-entry: it EXTENDS time out of the market versus the flag-only
    baseline. It belongs here as the opposite arm — if #32's rebound-forfeit reading is the whole
    story, holding cash longer through the recovery must be worse. Causal: state on day i uses
    returns[:i] and the (already causal) defend flags only.
    """
    if k_positive < 1:
        raise ValueError("k_positive must be >= 1 — a re-entry rule with no evidence is not a rule")
    n = len(returns)
    out: List[float] = []
    state_out = False
    for i in range(n):
        if state_out:
            window = returns[max(0, i - k_positive):i]
            if len(window) == k_positive and all(r > 0.0 for r in window):
                state_out = False
        if not state_out and defend[i]:
            state_out = True
        out.append(0.0 if state_out else 1.0)
    return out


# ─────────────────────────────── idea #37 — SDS ───────────────────────────────
def sds_signal(returns: Sequence[float], lookback: int,
               thr_annual: float = 0.0) -> List[bool]:
    """Slow Drift-Sign De-Risk — de-risk while the causal trailing drift sits below a hurdle.

        DEFEND(t) = mean(r[t−L : t−1]) < thr_annual / 365

    This is #35's own CONTROL, promoted to a hypothesis of its own because it beat every gated
    composite it was built to falsify. It is deliberately the LEAST reactive member of the
    de-risk family — which is what #32's reactivity law (corr(switches, ΔCalmar) = −0.78)
    predicts should win. It is NOT a new trigger shape: with L=10 and thr=r_f it IS kods#15.
    The question this asks is therefore precise: is the registry's fixture-era failure of the
    μ-family a property of the FAMILY, or only of the fast lookback and the r_f hurdle it was
    always run with? The sweep answers that; the train-selected OOS run decides it.

    Fail-CLOSED before `lookback` points exist: no drift estimate ⇒ no de-risk (stay invested),
    never a de-risk on an unmeasured state.
    """
    mu = cfpt.trailing_mean(returns, lookback)
    thr = thr_annual / 365.0
    return [(i >= lookback) and (mu[i] < thr) for i in range(len(returns))]


# ─────────────────────────────── base signal catalog ───────────────────────────────
SignalFn = Callable[[Sequence[float]], List[bool]]


def base_signals() -> List[Tuple[str, SignalFn]]:
    """The families #32 measured, in their own registry form. Kelly is excluded here because it
    is continuous (no defend/clear state to gate or to re-enter from) — it appears in the
    portfolio table of #32 instead."""
    return [
        ("vol#1(m=1.5)", lambda r: cfpt.sig_vol(r, 1.5)),
        ("vol#1(m=2.0)", lambda r: cfpt.sig_vol(r, 2.0)),
        ("dd#9(θ=2%)", lambda r: cfpt.sig_dd(r, 0.02)),
        ("kods#15(lkb=10)", lambda r: cfpt.sig_kods(r, 10)),
        ("ecdr#23(10/30)", lambda r: cfpt.sig_ecdr(r, 10, 30)),
        ("csd#28(sl=1e-4)", lambda r: cfpt.sig_csd(r, 10, 0.0001)),
    ]


# ─────────────────────────────── portfolio evaluation ───────────────────────────────
class Panel:
    """The clean panel, sliced to a date window and a book subset. Loaded once, reused."""

    def __init__(self, subset: Optional[Sequence[str]] = None,
                 start: Optional[str] = None, end: Optional[str] = None) -> None:
        panel = cfpt.load_clean_panel()
        axis = [d for d in cfpt.common_axis(panel)
                if (start is None or d > start) and (end is None or d <= end)]
        if not axis:
            raise RuntimeError("empty date window — refusing to report on a fabricated axis")
        self.books = sorted(panel) if subset is None else sorted(subset)
        self.axis = axis
        self.rets: Dict[str, List[float]] = {b: [panel[b][d] for d in axis] for b in self.books}

    @property
    def n(self) -> int:
        return len(self.axis)

    def raw_portfolio(self) -> List[float]:
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]


def portfolio_metrics(panel: Panel, weights: Dict[str, List[float]],
                      cost_bp_per_switch: float = COST_BP_PER_SWITCH) -> Dict[str, float]:
    """Equal-weight, daily-rebalanced combination of the per-book overlaid books.

    The same combination rule is used for every configuration and for the raw baseline, so the
    comparison isolates the overlay. De-risked capital earns 0%/day — the registry's own
    conservative convention (#32 reports the r_f variant beside it; see `--cash-rf`).

    `net_apy_after_cost` is the compounded APY minus the turnover bill of idea #10, charged per
    entry into a de-risked state and spread over the sample. It is an approximation (the bill is
    not re-invested), stated so it can never be mistaken for a compounded net path.
    """
    pf = [sum(weights[b][i] * panel.rets[b][i] for b in panel.books) / len(panel.books)
          for i in range(panel.n)]
    p = cfpt.perf(pf)
    sw = sum(switches(weights[b]) for b in panel.books) / len(panel.books)
    sw_yr = sw * 365.0 / panel.n
    duty = sum(1 for b in panel.books for i in range(panel.n)
               if (1.0 - weights[b][i]) >= cfpt.DERISK_EPS) / (len(panel.books) * panel.n)
    return {
        "apy": p["apy"],
        "maxdd": p["maxdd"],
        "calmar": p["calmar"],
        "duty": duty,
        "switches_yr": sw_yr,
        "cost_bp_yr": sw_yr * cost_bp_per_switch,
        "net_apy_after_cost": p["apy"] - sw_yr * cost_bp_per_switch / BP,
    }


def rebound_forfeit(panel: Panel, weights: Dict[str, List[float]]) -> Dict[str, float]:
    """#32's diagnostic: mean RAW return of the days the overlay sits out, split by regime.

    Positive inside a drawdown ⇒ the overlay is selling the recovery leg. This is the number
    idea #36 is trying to move, so it is reported for every RARE configuration.
    """
    in_dd: List[float] = []
    in_calm: List[float] = []
    for b in panel.books:
        dd = cfpt.trailing_drawdown(panel.rets[b])
        for i in range(panel.n):
            if (1.0 - weights[b][i]) >= cfpt.DERISK_EPS:
                (in_calm if dd[i] > -cfpt.CALM_DD else in_dd).append(panel.rets[b][i])
    mean = lambda v: (sum(v) / len(v) * BP) if v else float("nan")   # noqa: E731 (bp/day)
    return {"dd_bp": mean(in_dd), "calm_bp": mean(in_calm),
            "n_dd": float(len(in_dd)), "n_calm": float(len(in_calm))}


# ─────────────────────────────── reports ───────────────────────────────
def _header(title: str, panel: Panel, base: Dict[str, float]) -> None:
    print()
    print("=" * 104)
    print(f"{title}  ·  {panel.n} days {panel.axis[0]}..{panel.axis[-1]}  ·  {len(panel.books)} books")
    print("=" * 104)
    print(f"raw (no overlay): APY {base['apy']*100:.2f}%  maxDD {base['maxdd']*100:.2f}%  "
          f"Calmar {base['calmar']:.2f}")
    print(f"{'configuration':30s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔAPY':>8s}"
          f" {'ΔDD':>8s} {'ΔCalmar':>8s} {'duty':>6s} {'sw/yr':>6s} {'netAPY':>8s}")


def _row(name: str, m: Dict[str, float], base: Dict[str, float]) -> None:
    print(f"{name:30s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f}"
          f" {(m['apy']-base['apy'])*100:7.2f} {(m['maxdd']-base['maxdd'])*100:7.2f}"
          f" {m['calmar']-base['calmar']:8.2f} {m['duty']*100:5.1f}% {m['switches_yr']:6.1f}"
          f" {m['net_apy_after_cost']*100:7.2f}%")


def idea35_dgo(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL") -> Dict[str, Dict[str, float]]:
    """Idea #35 — is a de-risk overlay worth more when only negatively-drifting books may use it?"""
    panel = Panel(subset, start, end)
    base = cfpt.perf(panel.raw_portfolio())
    _header(f"IDEA #35 DGO — drift-gated overlay [{segment}] — {label}", panel, base)
    results: Dict[str, Dict[str, float]] = {}

    # control that has to be beaten: the gate on its own, as a de-risk signal
    for lkb in (60, 90):
        w = {b: binary(drift_gate(panel.rets[b], lkb)) for b in panel.books}
        m = portfolio_metrics(panel, w)
        results[f"drift-only(L={lkb})"] = m
        _row(f"CONTROL drift-only(L={lkb})", m, base)
    print("-" * 104)

    for name, fn in base_signals():
        flags = {b: fn(panel.rets[b]) for b in panel.books}
        plain = {b: binary(flags[b]) for b in panel.books}
        m_plain = portfolio_metrics(panel, plain)
        results[name] = m_plain
        _row(name, m_plain, base)

        for gate_name, gate_fn in (
            ("DGO", lambda r: drift_gate(r, DRIFT_LOOKBACK)),
            ("inv", lambda r: drift_gate_inverse(r, DRIFT_LOOKBACK)),
            ("oracle*", drift_gate_oracle),
        ):
            w = {b: gated_weights(plain[b], gate_fn(panel.rets[b])) for b in panel.books}
            m = portfolio_metrics(panel, w)
            results[f"{name} +{gate_name}"] = m
            _row(f"  +{gate_name}", m, base)
        print("-" * 104)

    print("* oracle uses the FULL-SAMPLE drift sign — LOOK-AHEAD, an upper bound, not a strategy.")
    print("CONTROL drift-only is the decisive comparison: unless a gated row beats it, the gate")
    print("is doing the work and DGO is a slow trend signal (ecdr#23) under a different name.")
    return results


def idea36_rare(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books",
                start: Optional[str] = None, end: Optional[str] = None,
                segment: str = "FULL") -> Dict[str, Dict[str, float]]:
    """Idea #36 — does fast, asymmetric re-entry remove the rebound forfeit measured by #32?"""
    panel = Panel(subset, start, end)
    base = cfpt.perf(panel.raw_portfolio())
    _header(f"IDEA #36 RARE — asymmetric re-entry [{segment}] — {label}", panel, base)
    results: Dict[str, Dict[str, float]] = {}
    forfeits: Dict[str, Dict[str, float]] = {}

    for name, fn in base_signals():
        flags = {b: fn(panel.rets[b]) for b in panel.books}
        variants = [
            (name, {b: binary(flags[b]) for b in panel.books}),
            ("  +RARE veto-after-up",
             {b: binary(veto_after_up(flags[b], panel.rets[b])) for b in panel.books}),
            ("  CONTROL dwell(k=1)",
             {b: dwell_weights(panel.rets[b], flags[b], 1) for b in panel.books}),
            ("  CONTROL dwell(k=2)",
             {b: dwell_weights(panel.rets[b], flags[b], 2) for b in panel.books}),
            ("  CONTROL dwell(k=3)",
             {b: dwell_weights(panel.rets[b], flags[b], 3) for b in panel.books}),
        ]
        for vname, w in variants:
            m = portfolio_metrics(panel, w)
            key = vname.strip() if vname.strip() != name else name
            results[f"{name}{'' if vname == name else ' ' + vname.strip()}"] = m
            forfeits[f"{name}{'' if vname == name else ' ' + vname.strip()}"] = \
                rebound_forfeit(panel, w)
            _row(vname, m, base)
        print("-" * 104)

    print()
    print("REBOUND FORFEIT (#32's diagnostic) — mean RAW return of the days the overlay sits out")
    print("positive inside a drawdown ⇒ the recovery leg is being sold; this is what RARE targets")
    print(f"{'configuration':34s} {'in drawdown':>14s} {'in calm':>12s} {'days out (dd/calm)':>22s}")
    for key, f in forfeits.items():
        print(f"{key:34s} {f['dd_bp']:13.1f}bp {f['calm_bp']:11.1f}bp"
              f" {int(f['n_dd']):11d} /{int(f['n_calm']):8d}")
    return results


def idea37_sds(subset: Optional[Sequence[str]] = None, label: str = "all 10 real books") -> None:
    """Idea #37 — the control of #35, tested properly: sweep, train-selected OOS, decomposition.

    Four questions, in the order that can kill the idea fastest:
      1. SWEEP — is the good lookback a plateau or a single spike? A spike is a fitted number.
      2. TRAIN→TEST — pick the configuration on TRAIN ONLY, then report what it did on the
         unseen TEST segment. This is the rule #33 failed and is the only honest verdict line.
      3. DECOMPOSITION — is the whole effect one negative-drift book (which would make this
         book-selection, exactly as #32 said) or does it also help positive-drift books?
      4. COST — at #10's 96 bp per switch, what is left?
    """
    full = Panel(subset)
    train = Panel(subset, None, TRAIN_END)
    test = Panel(subset, TRAIN_END, None)

    print()
    print("=" * 104)
    print(f"IDEA #37 SDS — slow drift-sign de-risk — {label}")
    print("=" * 104)
    print("1. SWEEP over lookback × hurdle (plateau ⇒ mechanism, spike ⇒ fitted number)")
    print(f"{'hurdle':>8s} | " + " ".join(f"L={l:<3d}" for l in (10, 20, 30, 45, 60, 75, 90, 120, 180)))
    base_full = cfpt.perf(full.raw_portfolio())
    for thr in (0.0, cfpt.RF_ANNUAL):
        cells = []
        for lkb in (10, 20, 30, 45, 60, 75, 90, 120, 180):
            w = {b: binary(sds_signal(full.rets[b], lkb, thr)) for b in full.books}
            cells.append(f"{portfolio_metrics(full, w)['calmar'] - base_full['calmar']:+5.2f}")
        print(f"{thr*100:7.1f}% | " + " ".join(f"{c:>5s}" for c in cells))
    print(f"(cells are ΔCalmar vs raw Calmar {base_full['calmar']:.2f}; hurdle 4.6% + L=10 is "
          f"kods#15 itself)")

    print()
    print("2. TRAIN-SELECTED → TEST (the only line that decides the verdict)")
    base_train = cfpt.perf(train.raw_portfolio())
    base_test = cfpt.perf(test.raw_portfolio())
    best_key: Optional[Tuple[int, float]] = None
    best_dc = float("-inf")
    for thr in (0.0, cfpt.RF_ANNUAL):
        for lkb in (10, 20, 30, 45, 60, 75, 90, 120, 180):
            w = {b: binary(sds_signal(train.rets[b], lkb, thr)) for b in train.books}
            dc = portfolio_metrics(train, w)["calmar"] - base_train["calmar"]
            if dc > best_dc:
                best_dc, best_key = dc, (lkb, thr)
    assert best_key is not None
    lkb, thr = best_key
    print(f"   selected on TRAIN ({train.n}d, {train.axis[0]}..{train.axis[-1]}): "
          f"L={lkb}, hurdle={thr*100:.1f}%  (ΔCalmar on train {best_dc:+.2f})")
    for seg, pnl, bse in (("TRAIN", train, base_train), ("TEST", test, base_test)):
        w = {b: binary(sds_signal(pnl.rets[b], lkb, thr)) for b in pnl.books}
        m = portfolio_metrics(pnl, w)
        print(f"   {seg:5s} ({pnl.n:3d}d): raw {bse['apy']*100:6.2f}%/{bse['maxdd']*100:6.2f}%"
              f"/{bse['calmar']:5.2f}  →  SDS {m['apy']*100:6.2f}%/{m['maxdd']*100:6.2f}%"
              f"/{m['calmar']:5.2f}   ΔAPY {(m['apy']-bse['apy'])*100:+6.2f}pp"
              f"  ΔDD {(m['maxdd']-bse['maxdd'])*100:+6.2f}pp  ΔCalmar {m['calmar']-bse['calmar']:+5.2f}"
              f"  sw/yr {m['switches_yr']:4.1f}  net {m['net_apy_after_cost']*100:6.2f}%")

    print()
    print("3. PER-BOOK DECOMPOSITION at the train-selected setting "
          "(is it one negative-drift book?)")
    print(f"{'book':22s} {'full-sample drift':>18s} {'raw APY':>9s} {'SDS APY':>9s} {'ΔAPY':>8s}"
          f" {'raw DD':>8s} {'SDS DD':>8s} {'duty':>6s}")
    helped_pos = helped_neg = 0
    for b in full.books:
        br = full.rets[b]
        bw = binary(sds_signal(br, lkb, thr))
        raw = cfpt.perf(br)
        ov = cfpt.perf([bw[i] * br[i] for i in range(full.n)])
        drift = sum(br) / len(br) * 365 * 100
        duty = sum(1 for x in bw if x < 1.0) / len(bw)
        if ov["apy"] > raw["apy"]:
            if drift < 0:
                helped_neg += 1
            else:
                helped_pos += 1
        print(f"{b:22s} {drift:17.2f}% {raw['apy']*100:8.2f}% {ov['apy']*100:8.2f}%"
              f" {(ov['apy']-raw['apy'])*100:7.2f} {raw['maxdd']*100:7.2f}%"
              f" {ov['maxdd']*100:7.2f}% {duty*100:5.1f}%")
    print(f"   books whose APY improved: {helped_neg} of the negative-drift ones, "
          f"{helped_pos} of the positive-drift ones")
    print("   (if only negative-drift books improve, this is book SELECTION — #32's reading — "
          "not timing)")

    print()
    print("5. LEAVE-ONE-OUT — how much of the portfolio effect survives dropping ONE book?")
    print("   (a portfolio-level ΔCalmar carried by a single book is not a portfolio edge)")
    print(f"{'portfolio':30s} {'raw Calmar':>11s} {'SDS Calmar':>11s} {'ΔCalmar':>9s} {'ΔAPY(pp)':>9s}")
    w_all = {b: binary(sds_signal(full.rets[b], lkb, thr)) for b in full.books}
    m_all = portfolio_metrics(full, w_all)
    print(f"{'all books':30s} {base_full['calmar']:11.2f} {m_all['calmar']:11.2f}"
          f" {m_all['calmar']-base_full['calmar']:9.2f}"
          f" {(m_all['apy']-base_full['apy'])*100:9.2f}")
    for drop in full.books:
        keep = [b for b in full.books if b != drop]
        sub = Panel(keep)
        b_sub = cfpt.perf(sub.raw_portfolio())
        w_sub = {b: binary(sds_signal(sub.rets[b], lkb, thr)) for b in keep}
        m_sub = portfolio_metrics(sub, w_sub)
        print(f"{'  minus ' + drop:30s} {b_sub['calmar']:11.2f} {m_sub['calmar']:11.2f}"
              f" {m_sub['calmar']-b_sub['calmar']:9.2f}"
              f" {(m_sub['apy']-b_sub['apy'])*100:9.2f}")

    print()
    print("4. COST SENSITIVITY at the train-selected setting (idea #10 charges ~96 bp/switch)")
    for cost in (0.0, 48.0, 96.0, 192.0):
        w = {b: binary(sds_signal(full.rets[b], lkb, thr)) for b in full.books}
        m = portfolio_metrics(full, w, cost)
        print(f"   {cost:5.0f} bp/switch → net APY {m['net_apy_after_cost']*100:6.2f}%"
              f"  (raw {base_full['apy']*100:.2f}%, gross {m['apy']*100:.2f}%,"
              f" bill {m['cost_bp_yr']:5.0f} bp/yr)")


def dwell_followthrough(subset: Optional[Sequence[str]] = None,
                        label: str = "all 10 real books") -> None:
    """#36's SURVIVING ARM, put through the same two executions that killed #35 and #37.

    RARE proper (veto-after-up) is refuted; its opposite — the dwell latch — is the arm that
    improved several families. A control that wins is a hypothesis, not a result, so it gets the
    same treatment: pick k on TRAIN only, report the unseen TEST, then leave-one-out to check
    the portfolio number is not one book in a trench coat (which is exactly how #37 died).
    """
    full = Panel(subset)
    train = Panel(subset, None, TRAIN_END)
    test = Panel(subset, TRAIN_END, None)
    print()
    print("=" * 104)
    print(f"IDEA #36 follow-through — the DWELL arm under train-selection and leave-one-out"
          f" — {label}")
    print("=" * 104)
    for name, fn in base_signals():
        b_tr = cfpt.perf(train.raw_portfolio())
        best_k, best_dc = 1, float("-inf")
        for k in (1, 2, 3):
            w = {b: dwell_weights(train.rets[b], fn(train.rets[b]), k) for b in train.books}
            dc = portfolio_metrics(train, w)["calmar"] - b_tr["calmar"]
            if dc > best_dc:
                best_dc, best_k = dc, k
        b_te = cfpt.perf(test.raw_portfolio())
        w_te = {b: dwell_weights(test.rets[b], fn(test.rets[b]), best_k) for b in test.books}
        m_te = portfolio_metrics(test, w_te)
        w_pl = {b: binary(fn(test.rets[b])) for b in test.books}
        m_pl = portfolio_metrics(test, w_pl)
        print(f"{name:20s} train-picked k={best_k} (ΔCalmar train {best_dc:+.2f})"
              f" → TEST ΔCalmar {m_te['calmar']-b_te['calmar']:+.2f}"
              f" (plain signal on TEST {m_pl['calmar']-b_te['calmar']:+.2f},"
              f" so dwell adds {m_te['calmar']-m_pl['calmar']:+.2f})")

    print()
    print("LEAVE-ONE-OUT on the full sample, dwell(k=2) — the configuration that looked best")
    print(f"{'portfolio':30s} " + " ".join(f"{n.split('(')[0]:>16s}" for n, _ in base_signals()))
    rows: List[Tuple[str, List[float]]] = []
    for drop in [None] + list(full.books):
        keep = full.books if drop is None else [b for b in full.books if b != drop]
        sub = Panel(keep)
        b_sub = cfpt.perf(sub.raw_portfolio())
        deltas = []
        for _, fn in base_signals():
            w = {b: dwell_weights(sub.rets[b], fn(sub.rets[b]), 2) for b in keep}
            deltas.append(portfolio_metrics(sub, w)["calmar"] - b_sub["calmar"])
        rows.append(("all books" if drop is None else "  minus " + drop, deltas))
    for nm, deltas in rows:
        print(f"{nm:30s} " + " ".join(f"{d:+16.2f}" for d in deltas))
    print("cells are ΔCalmar vs the raw portfolio of that same book set (dwell k=2, H-free).")


def noisy_subset() -> List[str]:
    """The books with real mark-to-market noise — #32 showed accrual paths understate the tax."""
    panel = cfpt.load_clean_panel()
    axis = cfpt.common_axis(panel)
    out: List[str] = []
    for b in sorted(panel):
        r = [panel[b][d] for d in axis]
        if cfpt._ann_vol(r) >= cfpt.NOISY_VOL_FLOOR:
            out.append(b)
    return out


def main(argv: Sequence[str]) -> int:
    ideas = {"35", "36", "37"}
    if "--idea" in argv:
        ideas = {argv[list(argv).index("--idea") + 1]}
    noisy = noisy_subset()
    print("Panel: clean loader of idea #32 (phase='forward' row cut, same-block jumps refused).")
    print(f"NOISY subset ({len(noisy)}/10): {', '.join(noisy)}")
    print("Evidence L0 (backtest over real feed history). IS_ADVISORY, OUTSIDE_RISKPOLICY.")

    for idea, fn in (("35", idea35_dgo), ("36", idea36_rare)):
        if idea not in ideas:
            continue
        fn(None, "all 10 real books", None, None, "FULL")
        fn(noisy, f"NOISY subset ({len(noisy)} books)", None, None, "FULL")
        fn(noisy, f"NOISY subset ({len(noisy)} books)", None, TRAIN_END, "TRAIN")
        fn(noisy, f"NOISY subset ({len(noisy)} books)", TRAIN_END, None, "TEST")
        if idea == "36":
            dwell_followthrough(None, "all 10 real books")
            dwell_followthrough(noisy, f"NOISY subset ({len(noisy)} books)")

    if "37" in ideas:
        idea37_sds(None, "all 10 real books")
        idea37_sds(noisy, f"NOISY subset ({len(noisy)} books)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
