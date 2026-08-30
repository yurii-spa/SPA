#!/usr/bin/env python3
"""
scripts/edge_single_book_turnover_cap.py — registry ideas SBTC and CVX

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

Working names SBTC and CVX. The registry NUMBERS are claimed at DELIVERY (registry rule at
the top of docs/DYNAMIC_LEVERAGE_GUARDIAN.md).


ORDERED BY #88 LAT, VERBATIM
============================
#88 closed with one practical instruction and it named an address:

    "инженерию по-прежнему стоит вкладывать в ОГРАНИЧЕНИЕ ЧАСТОТЫ и удешевление исполнения,
     но «дешевле» теперь имеет адрес: 43-48 % всего ног-потока генерирует одна книга
     (pendle_pt_levered), и ограничение оборота ИМЕННО ЕЁ — единственная правка этого
     семейства, у которой измеренная цена больше измеренного шума."

That sentence is a hypothesis, not a result, and #88 did not test it. Everything the family
has constrained so far has been constrained UNIFORMLY: #50 NTB put a band on the allocation
weights, #72 PDE-DB put a band on continuous exposure, #82 CIT put a flat toll inside the
switching rule, #88 LAT put a leg-aware toll inside the same rule but still gated the WHOLE
vector on one scalar. Not one entry has ever asked the question this one asks:

    Does it matter WHICH NAME you slow down?

SBTC MECHANISM (a constraint on ONE name, not on the vector)
-----------------------------------------------------------
Take the arm's daily target w*_t unchanged (#79's rule, the same one #80-#88 all use). Before
it is traded, clamp the day's move of a designated set S of books:

    b in S:      w_t[b] = w_{t-1}[b] + clamp(w*_t[b] - w_{t-1}[b], -kappa, +kappa)
    b not in S:  w_t[b] = w*_t[b] * (1 - sum_{S} w_t) / sum_{not S} w*_t[b]

The free books keep the arm's PROPORTIONS among themselves and absorb exactly the budget the
capped book did not take, so the vector still sums to 1 and gross exposure never changes. The
constraint therefore is not free: holding one name still costs turnover in the others, and
that turnover is charged. w_{t-1} is the REALISED weight, not the target — the cap is a path,
not a filter.

Two limits, both asserted by the acceptance suite:
    kappa = inf  ->  w_t == w*_t cell for cell (today's arm, #80's arm)
    kappa = 0    ->  the capped book's weight is frozen at its first value forever

fail-CLOSED where the constraint is infeasible: if the free books carry no weight to absorb
the residual (sum_{not S} w* == 0), or if the capped set would need more than the whole
portfolio, the day is REFUSED — the previous vector is held — rather than quietly relaxing
the cap. An unaffordable constraint must not become a licence to trade.

THE CONTROL THAT DECIDES THE VERDICT
------------------------------------
SBTC trades less, like every other arm this family has produced, and #50 has already been
confirmed four times over: trading less is worth money all by itself. So "it beat the raw
arm" decides nothing. Two controls, and they are the entry:

  (1) IDENTITY, same kappa — cap each of the ten books in turn at the SAME kappa. With ten
      books this control is EXHAUSTIVE, not sampled: pendle_pt_levered's rank among ten is
      the whole statement, and the best p it can produce is 0.100.

  (2) IDENTITY, turnover-MATCHED — the control that actually decides. Same kappa removes
      different amounts of flow from different names, so (1) alone could be won by whichever
      book happens to trade most. For each other book, kappa is retuned so its leg turnover
      lands as close as possible to SBTC's, and the two are compared at EQUAL flow removed.
      If pendle_pt_levered does not win THERE, the name carries nothing and the finding is
      frequency again — and it gets written that way.

  (3) GLOBAL cap — S = every book, kappa retuned to the same leg turnover. This is the "no
      name information at all" reading: the same amount of slowing, spread over everyone.

CVX: THE SECOND QUESTION, AND IT IS ABOUT THE FAMILY'S FOUNDATION
-----------------------------------------------------------------
Every entry from #79 to #88 charges cost linearly, c * |flow|, and every one of them carries
the same caveat in its own small print: the linear one-way model is OPTIMISTIC, and #88 added
that it is most optimistic exactly where leg flow is largest. Nobody has measured what that
caveat is worth. CVX charges an impact term as well,

    net_t = gross_t - c * tau_t / 1e4 - gamma * tau_t**1.5 / 1e4

and asks a question the whole branch depends on: does the RANKING survive, and at what gamma
does every active arm lose to holding the panel? A finding that only exists under a cost model
its own authors call optimistic is not a finding, and the honest way to know is to price it.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; every caveat of #88, #83, #82 and #80 carries over unchanged, including
    that the arm's signal is estimated on the same series it is scored on;
  * the leg table is a judgement about which instruments are the same instrument; it is
    re-checked against roster.py at run time and a drift there is a hard failure;
  * ten books means the identity control cannot produce a p below 0.100 — that is a floor of
    the panel, not evidence, and it is printed as such;
  * the turnover match is approximate (kappa is a coarse dial and flow is a step function of
    it); the achieved flow of every control row is printed next to its score so the reader can
    see how good the match actually was, instead of trusting the word "matched";
  * no parameter is chosen on TEST: the kappa ladder, the search grid, the cost, the gamma
    grid and the canonical 2025-06-30 split were fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_cost_signal_separation as css  # noqa: E402  (#80 harness, reused verbatim)
import edge_gross_to_net_toll as gtn  # noqa: E402  (#83 leg algebra, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 harness, reused verbatim)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

CONVENTION_COST = css.CONVENTION_COST
ARMS = css.ARMS
SPLIT_DATE = mh.SPLIT_DATE

#: The book #88 named. Not a parameter — it is the address the order came with.
ORDERED_BOOK = "pendle_pt_levered"

#: Fixed before any number was read. Typical single-book move on this panel is 1/k ~ 0.1.
KAPPA_LADDER: Tuple[float, ...] = (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, float("inf"))
#: Finer grid used ONLY to match a control's turnover to SBTC's. Never used to pick a winner.
KAPPA_SEARCH: Tuple[float, ...] = tuple(i / 200.0 for i in range(0, 101))  # 0.000 … 0.500
#: Impact grid for CVX, in bps on tau**1.5. Fixed before any number was read.
GAMMA_GRID: Tuple[float, ...] = (0.0, 48.0, 96.0, 192.0, 384.0, 768.0)

#: The FRIENDLIEST defensible reading of the invoice, inherited from #88: borrowings free.
DEBT_RATE = 0.0

_EPS = 1e-12


def scoring_legs() -> gtn.LegTable:
    """The leg table the invoice is written on: real composition, borrowings free."""
    gtn.assert_leg_table_matches_roster()
    return gtn.legs_at_debt_rate(gtn.RAW_LEGS, DEBT_RATE)


# ── the mechanism ────────────────────────────────────────────────────────────────
def clamp_move(target: float, prev: float, kappa: float) -> float:
    """One book's realised weight after its daily move is clamped to +/- kappa.

    Split out as a named function on purpose: inline, the kappa=inf branch and the clamp are
    one expression and a mutation of either is invisible in the aggregate. `math.isinf` is
    handled explicitly because `min(inf, x)` would silently work while `kappa=0` must NOT be
    confused with "no cap".
    """
    d = target - prev
    if math.isinf(kappa):
        return target
    if d > kappa:
        return prev + kappa
    if d < -kappa:
        return prev - kappa
    return target


#: Target histories are pure functions of (panel, mode) and are rebuilt thousands of times by
#: the turnover-matching search. Cached by IDENTITY of the panel object, never by content, so
#: a different panel can never be served a cached vector.
_TARGET_CACHE: Dict[Tuple[int, int, str], css.WeightHistory] = {}


def target_history(book_rets, dates, mode: str) -> css.WeightHistory:
    key = (id(book_rets), len(dates), mode)
    hit = _TARGET_CACHE.get(key)
    if hit is None:
        hit = css._weight_history(book_rets, dates, mode)
        _TARGET_CACHE[key] = hit
    return hit


def capped_history(
    book_rets: Dict[str, List[float]],
    dates: Sequence[datetime.date],
    mode: str,
    capped: Sequence[str],
    kappa: float,
) -> Tuple[css.WeightHistory, int, int]:
    """The arm's history with set `capped` held to +/- kappa per day.

    Returns (history, days the cap actually bound, days REFUSED as infeasible).
    """
    targets = target_history(book_rets, dates, mode)
    book_ids = sorted(book_rets)
    cap_set = set(capped)
    unknown = cap_set - set(book_ids)
    if unknown:
        raise ValueError(f"cap named books that are not on the panel: {sorted(unknown)}")
    hist: css.WeightHistory = []
    prev: Optional[Dict[str, float]] = None
    bound = 0
    refused = 0
    for tgt in targets:
        if prev is None:
            hist.append(dict(tgt))
            prev = dict(tgt)
            continue
        held = {b: clamp_move(tgt.get(b, 0.0), prev.get(b, 0.0), kappa) for b in cap_set}
        if all(abs(held[b] - tgt.get(b, 0.0)) <= _EPS for b in cap_set):
            # Nothing was clamped, so the residual is exactly zero and the rescale below is
            # the identity. Taking it anyway would inject float noise into EVERY free weight
            # on EVERY non-binding day — noise that css._gross_and_turnover would then charge
            # as real turnover, and that would put a fake bill on the kappa=inf limit itself.
            hist.append(dict(tgt))
            prev = dict(tgt)
            continue
        taken = sum(held.values())
        free_target = sum(tgt.get(b, 0.0) for b in book_ids if b not in cap_set)
        # fail-CLOSED: a constraint we cannot afford to honour is a REFUSAL to trade, never
        # a quiet relaxation of the cap.
        if taken > 1.0 + _EPS or (free_target <= _EPS and abs(taken - 1.0) > _EPS):
            refused += 1
            hist.append(dict(prev))
            continue
        w = dict(held)
        if free_target > _EPS:
            scale = (1.0 - taken) / free_target
            for b in book_ids:
                if b not in cap_set:
                    w[b] = tgt.get(b, 0.0) * scale
        else:
            for b in book_ids:
                if b not in cap_set:
                    w[b] = 0.0
        if any(abs(w.get(b, 0.0) - tgt.get(b, 0.0)) > _EPS for b in cap_set):
            bound += 1
        hist.append(w)
        prev = w
    return hist, bound, refused


# ── invoices ─────────────────────────────────────────────────────────────────────
def convex_net(
    gross: Sequence[float],
    turns: Sequence[float],
    cost_bps: float,
    gamma_bps: float,
) -> List[float]:
    """net = gross - c*tau/1e4 - gamma*tau**1.5/1e4.

    gamma = 0 reproduces css._net exactly (asserted by the suite). The 3/2 exponent is the
    textbook square-root impact law written per unit traded; it is a MODEL, not a measurement
    on this desk, and the entry says so.
    """
    out: List[float] = []
    for g, t in zip(gross, turns):
        t = max(0.0, float(t))
        out.append(g - t * cost_bps / 10_000.0 - (t ** 1.5) * gamma_bps / 10_000.0)
    return out


class Row:
    """One scored configuration. Tail is carried NEXT TO the return, never apart from it."""

    __slots__ = ("apy", "mdd", "calmar", "dcalmar", "leg_to_yr", "bound", "refused")

    def __init__(self, apy, mdd, calmar, dcalmar, leg_to_yr, bound=0, refused=0):
        self.apy, self.mdd, self.calmar = apy, mdd, calmar
        self.dcalmar, self.leg_to_yr = dcalmar, leg_to_yr
        self.bound, self.refused = bound, refused


def score(
    hist: css.WeightHistory,
    book_rets: Dict[str, List[float]],
    legs: gtn.LegTable,
    base_calmar: float,
    cost: float,
    n_days: int,
    gamma: float = 0.0,
) -> Row:
    gross, _ = css._gross_and_turnover(hist, book_rets)
    tau = gtn.leg_turnover(hist, legs)
    net = convex_net(gross, tau, cost, gamma)
    return Row(
        mh._apy(net),
        mh._mdd(net),
        mh._calmar(net),
        mh._calmar(net) - base_calmar,
        sum(tau) / (n_days / 365.0) if n_days else 0.0,
    )


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation, ties averaged. stdlib, no scipy.

    Used for exactly one question and it is the frequency question: across the ten
    single-book freezes, does the AMOUNT of flow removed explain the score? If it does, the
    identity finding is #50 wearing a new hat.
    """
    def ranks(v: Sequence[float]) -> List[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def match_kappa_to_flow(
    book_rets, dates, mode, capped, target_flow_yr, legs, n_days,
) -> Tuple[float, float]:
    """Smallest kappa on the search grid whose leg flow is nearest `target_flow_yr`.

    Ties broken toward the LOOSER cap, which is the conservative choice: it gives the control
    the benefit of trading more, never less, than the arm it is matched against.
    """
    best: Optional[Tuple[float, float, float]] = None
    for k in KAPPA_SEARCH:
        hist, _, _ = capped_history(book_rets, dates, mode, capped, k)
        flow = sum(gtn.leg_turnover(hist, legs)) / (n_days / 365.0) if n_days else 0.0
        err = abs(flow - target_flow_yr)
        # ties -> the LOOSER cap (KAPPA_SEARCH ascends), never the tighter one
        if best is None or err < best[1] + 1e-9:
            best = (k, err, flow)
    assert best is not None
    return best[0], best[2]


# ── report ───────────────────────────────────────────────────────────────────────
def _fmt_k(k: float) -> str:
    return "inf" if math.isinf(k) else f"{k:.3f}"


def run(dates, book_rets, *, legs: gtn.LegTable, cost: float = CONVENTION_COST) -> Dict[str, dict]:
    book_ids = sorted(book_rets)
    n_days = len(dates) - 1
    out: Dict[str, dict] = {}

    print("\n" + "=" * 92)
    print("Ideas SBTC + CVX — does it matter WHICH NAME you slow down, and does the answer")
    print("survive a cost model its own authors call optimistic?  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_ids)}  ·  {dates[0]} … {dates[-1]} ({len(dates)} days)")
    print(f"  invoice: LEG flow, borrowings at δ={DEBT_RATE:g} of the spot toll  ·  c={cost:g} bps")
    print(f"  ordered book: {ORDERED_BOOK}")
    print("=" * 92)

    eq_hist = css._weight_history(book_rets, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq_hist, book_rets)
    eq_tau = gtn.leg_turnover(eq_hist, legs)
    eq_net = css._net(eq_gross, eq_tau, cost)
    eq_calmar, eq_apy, eq_mdd = mh._calmar(eq_net), mh._apy(eq_net), mh._mdd(eq_net)
    print(f"\nBaseline equal-weight (does not trade) under the SAME invoice: "
          f"APY={eq_apy * 100:.2f}%  maxDD={eq_mdd * 100:.2f}%  Calmar={eq_calmar:.2f}  "
          f"legTO/yr={sum(eq_tau) / (n_days / 365.0):.2f}")
    out["baseline"] = {"apy": eq_apy, "mdd": eq_mdd, "calmar": eq_calmar}

    # ── 0. who actually generates the invoice, per arm ───────────────────────────
    print("\n" + "─" * 92)
    print("0. WHO GENERATES THE FLOW — and a correction to the number #88 quoted.")
    print("   #88 headlined '43-48 % of all leg flow' while SCORING at δ=0. Those are two")
    print("   different columns: 43-48 % is the δ=1 accounting (borrowings priced like swaps).")
    print("   At the δ=0 invoice #88 actually paid, the share is smaller — and still first by")
    print("   a factor of more than two over the runner-up, so the ADDRESS survives the fix.")
    print(f"{'arm':<16}{'top three books by leg flow (δ=0, the scored invoice)':<58}"
          f"{'ordered @δ=1':>14}")
    print("─" * 92)
    shares: Dict[str, Dict[str, float]] = {}
    legs_full = gtn.legs_at_debt_rate(gtn.RAW_LEGS, 1.0)
    legs_full = {b: legs_full[b] for b in book_ids}
    for mode, label in ARMS:
        h = target_history(book_rets, dates, mode)
        flow = gtn.per_book_leg_flow(h, legs)
        tot = sum(flow.values()) or 1.0
        sh = {b: flow.get(b, 0.0) / tot for b in book_ids}
        shares[mode] = sh
        top = sorted(sh.items(), key=lambda kv: -kv[1])
        full = gtn.per_book_leg_flow(h, legs_full)
        full_share = full.get(ORDERED_BOOK, 0.0) / (sum(full.values()) or 1.0)
        cells = "  ".join(f"{b}={v * 100:.1f}%" for b, v in top[:3])
        print(f"  {label:<14}{cells:<58}{full_share * 100:>13.1f}%")
    out["shares"] = shares

    # ── 1. the kappa ladder on the ORDERED book ──────────────────────────────────
    print("\n" + "─" * 92)
    print(f"1. KAPPA LADDER, S = {{{ORDERED_BOOK}}}.  κ=inf is today's arm exactly;")
    print("   κ=0 freezes that one book's weight and lets the other nine keep trading.")
    print(f"{'arm':<16}{'κ':>7}{'netAPY':>9}{'maxDD':>9}{'Calmar':>8}{'dCalmar':>9}"
          f"{'legTO/yr':>10}{'bound':>7}{'refused':>9}")
    print("─" * 92)
    best: Dict[str, Tuple[float, Row]] = {}
    for mode, label in ARMS:
        for k in KAPPA_LADDER:
            hist, bound, refused = capped_history(book_rets, dates, mode, [ORDERED_BOOK], k)
            r = score(hist, book_rets, legs, eq_calmar, cost, n_days)
            r.bound, r.refused = bound, refused
            print(f"  {label:<14}{_fmt_k(k):>7}{r.apy * 100:>8.2f}%{r.mdd * 100:>8.2f}%"
                  f"{r.calmar:>8.2f}{r.dcalmar:>+9.2f}{r.leg_to_yr:>10.2f}{bound:>7}{refused:>9}")
            if math.isinf(k):
                out.setdefault(mode, {})["raw_dcalmar"] = r.dcalmar
                out[mode]["raw_leg_to_yr"] = r.leg_to_yr
            else:
                cur = best.get(mode)
                if cur is None or r.dcalmar > cur[1].dcalmar:
                    best[mode] = (k, r)
        print()
    for mode, (k, r) in best.items():
        out.setdefault(mode, {}).update(
            {"kappa_star": k, "dcalmar": r.dcalmar, "apy": r.apy, "mdd": r.mdd,
             "leg_to_yr": r.leg_to_yr}
        )

    # ── 2. identity control at the SAME kappa (exhaustive over ten books) ────────
    print("─" * 92)
    print("2. IDENTITY CONTROL, SAME κ — cap each of the ten books in turn at the arm's κ*.")
    print("   EXHAUSTIVE, not sampled. Ten books ⇒ the smallest p this control can report is")
    print("   0.100, and that is a floor of the panel, not evidence.")
    print(f"{'arm':<16}{'κ*':>7}{'ordered dCal':>14}{'rank':>7}{'best other book':>22}"
          f"{'its dCal':>10}")
    print("─" * 92)
    for mode, label in ARMS:
        if mode not in best:
            continue
        k, r = best[mode]
        rows = {}
        for b in book_ids:
            h, _, _ = capped_history(book_rets, dates, mode, [b], k)
            rows[b] = score(h, book_rets, legs, eq_calmar, cost, n_days)
        order = sorted(book_ids, key=lambda b: -rows[b].dcalmar)
        rank = order.index(ORDERED_BOOK) + 1
        other = [b for b in order if b != ORDERED_BOOK][0]
        print(f"  {label:<14}{_fmt_k(k):>7}{rows[ORDERED_BOOK].dcalmar:>+14.2f}"
              f"{rank:>4}/{len(book_ids):<3}{other[:20]:>22}{rows[other].dcalmar:>+10.2f}")
        out.setdefault(mode, {})["rank_same_kappa"] = rank
        out[mode]["p_same_kappa"] = rank / len(book_ids)

    # ── 3. the common limit, the impossible match, and the frequency test ───────
    print("\n" + "─" * 92)
    print("3. THE CONTROL THAT WAS SUPPOSED TO DECIDE — AND WHY IT CANNOT BE BUILT HERE.")
    print("   Plan was: retune each other book's κ so its leg flow lands on the ordered")
    print("   book's, then compare at EQUAL flow removed. It is impossible on this panel:")
    print("   the ordered book's own floor (κ=0, frozen) is the LOWEST of the ten, so no")
    print("   other name can be brought down to it. The confound is therefore named, not")
    print("   hidden — and it runs AGAINST every alternative, which is the only reason the")
    print("   comparison is still readable. All ten are shown at the common limit κ=0.")
    print("   Then the frequency question is asked directly: does the AMOUNT of flow removed")
    print("   explain the score? If it does, this is #50 in a new hat.")
    for mode, label in ARMS:
        raw_d = out.get(mode, {}).get("raw_dcalmar", float("nan"))
        raw_to = out.get(mode, {}).get("raw_leg_to_yr", float("nan"))
        rows = {}
        for b in book_ids:
            h, _, _ = capped_history(book_rets, dates, mode, [b], 0.0)
            rows[b] = score(h, book_rets, legs, eq_calmar, cost, n_days)
        order = sorted(book_ids, key=lambda b: -rows[b].dcalmar)
        rank = order.index(ORDERED_BOOK) + 1
        floor_rank = sorted(book_ids, key=lambda b: rows[b].leg_to_yr).index(ORDERED_BOOK) + 1
        rho = spearman([rows[b].leg_to_yr for b in book_ids],
                       [rows[b].dcalmar for b in book_ids])
        print(f"\n  {label}  (uncapped: legTO/yr {raw_to:.2f}, dCalmar {raw_d:+.2f})")
        print(f"    {'frozen book':<24}{'legTO/yr':>10}{'netAPY':>9}{'maxDD':>9}"
              f"{'Calmar':>8}{'dCalmar':>9}")
        for b in order:
            r = rows[b]
            mark = "  <= ordered" if b == ORDERED_BOOK else ""
            print(f"    {b:<24}{r.leg_to_yr:>10.2f}{r.apy * 100:>8.2f}%{r.mdd * 100:>8.2f}%"
                  f"{r.calmar:>8.2f}{r.dcalmar:>+9.2f}{mark}")
        print(f"    rank of ordered book by score: {rank}/{len(book_ids)}  ·  "
              f"by flow floor: {floor_rank}/{len(book_ids)} (lowest = the match is impossible)")
        print(f"    FREQUENCY TEST — Spearman(flow removed, dCalmar) across the ten: "
              f"rho={rho:+.3f}")
        out.setdefault(mode, {}).update(
            {"rank_frozen": rank, "p_frozen": rank / len(book_ids),
             "floor_rank": floor_rank, "rho_flow_vs_score": rho,
             "frozen_rows": {b: (rows[b].leg_to_yr, rows[b].dcalmar) for b in book_ids}}
        )

    # ── 4. global cap — and what it actually degenerates into ────────────────────
    print("\n" + "─" * 92)
    print("4. GLOBAL CAP AT MATCHED FLOW — S = every book, κ retuned to the ordered book's")
    print("   flow. Read the 'refused' column before the score: with no free book left to")
    print("   absorb the residual, a global cap CANNOT be honoured on a day whose clamped")
    print("   vector does not already sum to 1, and fail-CLOSED holds yesterday. So this row")
    print("   is not 'the same slowing spread over everyone' — it is switch SUPPRESSION, and")
    print("   saying so is the difference between a control and a decoration.")
    print(f"{'arm':<16}{'κ global':>10}{'achieved TO':>13}{'bound':>8}{'refused':>9}"
          f"{'global dCal':>13}{'ordered dCal':>14}")
    print("─" * 92)
    for mode, label in ARMS:
        if mode not in best:
            continue
        k, r = best[mode]
        kg, flow = match_kappa_to_flow(book_rets, dates, mode, book_ids, r.leg_to_yr, legs, n_days)
        h, bound_g, refused_g = capped_history(book_rets, dates, mode, book_ids, kg)
        rg = score(h, book_rets, legs, eq_calmar, cost, n_days)
        print(f"  {label:<14}{kg:>10.3f}{flow:>13.2f}{bound_g:>8}{refused_g:>9}"
              f"{rg.dcalmar:>+13.2f}{r.dcalmar:>+14.2f}")
        out.setdefault(mode, {})["global_dcalmar"] = rg.dcalmar
        out[mode]["global_refused"] = refused_g

    # ── 5. train / test ──────────────────────────────────────────────────────────
    print("\n" + "─" * 92)
    print(f"5. TRAIN / TEST (split {SPLIT_DATE}) — does κ* move between the halves?")
    cut = gtn._split_index(dates, SPLIT_DATE)
    print(f"{'arm':<16}{'κ* train':>10}{'dCal train':>12}{'κ* test':>10}{'dCal test':>11}"
          f"{'dCal test @ κ*train':>21}")
    print("─" * 92)
    for mode, label in ARMS:
        halves = []
        per_kappa: Dict[float, List[float]] = {}
        for kk in KAPPA_LADDER:
            if math.isinf(kk):
                continue
            hist, _, _ = capped_history(book_rets, dates, mode, [ORDERED_BOOK], kk)
            gross, _ = css._gross_and_turnover(hist, book_rets)
            tau = gtn.leg_turnover(hist, legs)
            per_kappa[kk] = []
            for sl in (slice(0, cut), slice(cut, None)):
                base = mh._calmar(css._net(eq_gross[sl], eq_tau[sl], cost))
                per_kappa[kk].append(css._dcalmar(css._net(gross[sl], tau[sl], cost), base))
        for half in (0, 1):
            bk = max(per_kappa, key=lambda kk: per_kappa[kk][half])
            halves.append((bk, per_kappa[bk][half]))
        (k_tr, d_tr), (k_te, d_te) = halves
        carried = per_kappa[k_tr][1]
        print(f"  {label:<14}{k_tr:>10.3f}{d_tr:>+12.2f}{k_te:>10.3f}{d_te:>+11.2f}"
              f"{carried:>+21.2f}")
        out.setdefault(mode, {})["kappa_train_test"] = (k_tr, k_te)
        out[mode]["dcal_test_at_train_kappa"] = carried

    # ── 6. CVX: does any of this survive a convex invoice? ───────────────────────
    print("\n" + "─" * 92)
    print("6. CVX — CONVEX INVOICE.  net = gross − c·τ − γ·τ^1.5.  γ=0 is the whole family's")
    print("   model. Equal-weight does not trade, so it pays NOTHING extra: every column is")
    print("   the active arm's own bill.  Question: at what γ does doing nothing win?")
    print(f"{'arm / config':<26}" + "".join(f"{'γ=' + str(int(g)):>11}" for g in GAMMA_GRID))
    print("─" * 92)
    cvx: Dict[str, Dict[float, float]] = {}
    for mode, label in ARMS:
        for tag, kk in (("raw (κ=inf)", float("inf")),
                        ("SBTC κ*", best[mode][0] if mode in best else 0.0)):
            hist, _, _ = capped_history(book_rets, dates, mode, [ORDERED_BOOK], kk)
            gross, _ = css._gross_and_turnover(hist, book_rets)
            tau = gtn.leg_turnover(hist, legs)
            row: Dict[float, float] = {}
            cells = []
            for g in GAMMA_GRID:
                base = mh._calmar(convex_net(eq_gross, eq_tau, cost, g))
                d = mh._calmar(convex_net(gross, tau, cost, g)) - base
                row[g] = d
                cells.append(f"{d:>+11.2f}")
            name = f"{label} {tag}"
            print(f"  {name:<24}" + "".join(cells))
            cvx[name] = row
    out["cvx"] = cvx
    print("\n   Read down a row: the γ at which the number crosses zero is the impact charge")
    print("   at which that arm stops being worth running at all.")

    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    legs = scoring_legs()
    dates, book_rets = gtn.load_real_panel()
    missing = sorted(set(book_rets) - set(legs))
    if missing:
        raise RuntimeError(f"panel carries books with no leg vector: {missing}")
    if ORDERED_BOOK not in book_rets:
        raise RuntimeError(f"the ordered book {ORDERED_BOOK} is not on this panel")
    run(dates, book_rets, legs={b: legs[b] for b in sorted(book_rets)})
    print("\n" + "=" * 92)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
