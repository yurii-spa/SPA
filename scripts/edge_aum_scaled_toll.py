#!/usr/bin/env python3
"""
scripts/edge_aum_scaled_toll.py — registry idea AST (AUM-Scaled Toll)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

Working name AST. The registry NUMBER is claimed at DELIVERY (registry rule at the top of
docs/DYNAMIC_LEVERAGE_GUARDIAN.md).


ORDERED BY #90 CVX, AND THE ORDER COULD NOT BE FILLED AS WRITTEN
===============================================================
#90 closed the timing branch with one instruction:

    "Следующий шаг ветки — не ещё одно правило переключения, а ЗАМЕР γ по фактическим
     исполнениям (проскальзывание против середины спреда по размеру ордера, по ногам #83),
     после чего все клетки #79–#90 пересчитываются один раз на измеренной пошлине."

We have no fills. The desk is paper; `data/slippage_impact_log.json` carries a daily summary
(`total_trades: 1`) and no size axis; `data/apy_ranking.json` carries `tvl_source: "static"`,
which the risk rule forbids reading as depth. So the literal order cannot be filled today, and
inventing a γ would be exactly the failure #90 named.

What CAN be done, and what nobody in #79–#90 did, is to notice that γ IS NOT A NUMBER. Write
the square-root law out in dollars and the size falls out of it:

    dollar impact of trading Q against depth D  =  Q · η · sqrt(Q/D)
    as a fraction of AUM A, with Q = τ·A:        =  η · τ^1.5 · sqrt(A/D)

so the registry's own parameterisation, cost = γ·τ^1.5/1e4, carries a hidden identity:

    γ  =  1e4 · η · sqrt(A / D)                                         (identity #1)

Every cell from #79 to #90 was computed at an unstated AUM. #90's ladder γ ∈ {0 … 768} is not
a stress axis — it is an AUM axis with the label rubbed off. The same is true, in the OPPOSITE
direction, of a cost nobody in this branch has ever charged at all: gas is a fixed number of
DOLLARS per leg touched, so as a fraction of capital it is

    gas fraction  =  G · L_t / A                                        (identity #2)

which EXPLODES as A shrinks. `docs/cost_model_provenance.md` §3 already showed this mechanism
on two numbers (paper $100k → 0.064 pp, pilot $1 000 → 2.48 pp) and no registry entry ever ran
it through an arm.

AST MECHANISM (no new rule; the same arms, an invoice that knows its own size)
-----------------------------------------------------------------------------
Arms, weights, panel and split are #79's, unchanged, exactly as #80–#90 used them. Only the
invoice changes:

    net_t = gross_t − c_var·τ_t/1e4 − G·L_t/A − Σ_legs q²_{t,leg} / ((R_leg + q_{t,leg})·A)

    q_{t,leg} = |Δ exposure_{t,leg}| · A          dollar flow in one leg on one day
    L_t                                           number of legs actually touched that day
    R_leg                                         tradeable depth of that leg, in dollars

The impact term is the EXACT constant-product fill, cost = q²/(R+q), not a fitted law: for a
constant-product pool the average slippage of selling q into reserve R is exactly q/(q+R). It
therefore carries NO free coefficient — the thing #90 could not measure is replaced by a thing
that is derived, and the only input left is R, which is honestly an AXIS below and not a
number. Concentrated liquidity, stableswap curves and order splitting are all FLATTER than
constant product, so this term is an UPPER bound; γ=0 (#90's first column) is the lower bound,
and the truth is bracketed rather than asserted.

TWO ENDS, AND THAT IS THE FINDING
    · gas ∝ 1/A  ⇒ a FLOOR: below some capital the arm cannot pay for its own transactions;
    · impact ∝ A ⇒ a CEILING: above some capital it cannot pay for its own footprint.
The branch does not have a capacity CEILING, as #90's blanket verdict reads. It has a WINDOW,
and this file measures both of its edges.

THE CONTROL THAT MAKES EVERY CELL READABLE
    equal-weight has leg turnover EXACTLY 0.0 on this panel (asserted, not assumed, by
    `assert_baseline_pays_nothing` and by the suite). It therefore pays no c_var, no gas and
    no impact at ANY A, R or G. The base is the same number in every cell, so each cell is
    the whole bill of the active arm and nothing else. This is #90's construction, kept.

ANCHORS, AND WHERE THEY COME FROM (not invented here)
    G = $12.00/leg   the constant `spa_core/backtesting/tier1/cost_model.py` runs with today;
                     `docs/cost_model_provenance.md` §2 records that it has no measurement date
                     and corresponds to ~20 Gwei × ETH $3 200.
    G = $0.045/leg   the SPOT measurement of 2026-08-30 in the same document §2-бис (0.0725
                     Gwei × 250k gas × ETH $2 490.9), five independent RPC, spread < 1 %.
                     A point, not a distribution — the document says so and so does this file.
    The ×267 between them is not noise in a footnote: it MOVES THE FLOOR by that factor, and
    the floor is what decides whether our own sizes are inside the window.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; every caveat of #90, #88, #83, #82 and #80 carries over unchanged;
  * R is NOT measured. We have no tradeable-depth feed, protocol TVL is not swap depth, and
    the one TVL column in the tree is stamped `static`. R is therefore an axis, and every
    statement below is conditional on a stated R. Refusing to publish a single number here
    is the point of the entry, not a gap in it;
  * gas is charged per leg touched per day. That is an UPPER bound (a desk bundles legs into
    one transaction); the bundled bound, L_t = 1 on any day the portfolio moves at all, is
    computed alongside it, so the floor is BRACKETED and neither end is asserted alone;
  * no dust floor: a leg that moves by one cent is charged a whole gas fee. That also pushes
    the floor UP, in the same direction as the previous line, and both are printed;
  * the impact term uses the δ=0 leg table (borrowings free) — #90's invoice, for
    comparability; the gas COUNT uses the raw table, because a borrow leg is still a
    transaction. The two tables are printed side by side so this choice is visible;
  * one snapshot of depth cannot represent 852 days of it, which is another reason R is an
    axis rather than a column of history;
  * no parameter is chosen on TEST: the AUM ladder, the depth ladder, the two gas anchors,
    c_var ∈ {0, 96} and the canonical 2025-06-30 split were fixed before any number was read.

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

ARMS = css.ARMS
SPLIT_DATE = mh.SPLIT_DATE
CONVENTION_COST = css.CONVENTION_COST  # 96 bps, the registry's standing convention

#: The friendliest defensible reading of the invoice, inherited from #88/#89/#90.
DEBT_RATE = 0.0

#: Fixed before any number was read. Six decades of capital, straddling every size this desk
#: has ever discussed: pilot ($1k/strategy, ADR post-paper path), paper ($100k), and the
#: institutional sizes the earlier capacity note guessed at.
AUM_LADDER: Tuple[float, ...] = (1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9)

#: Tradeable depth PER LEG, in dollars. An AXIS, not a measurement — see the header.
DEPTH_LADDER: Tuple[float, ...] = (1e6, 1e7, 1e8, 1e9, float("inf"))

#: Two anchors from docs/cost_model_provenance.md. Neither is invented here.
GAS_MODEL_CONSTANT = 12.00   # §2: the constant cost_model.py runs with, undated
GAS_SPOT_2026_08_30 = 0.045  # §2-бис: measured spot, five RPC, one point in time

#: Size-invariant proportional share of the toll. 0 isolates the size effect; 96 stacks it on
#: top of the branch's published convention. Both are reported; neither is fitted.
CVAR_LADDER: Tuple[float, ...] = (0.0, CONVENTION_COST)

#: The two sizes this desk actually has. Printed on the axis so the reader does not have to
#: interpolate the ladder by eye.
ANCHOR_SIZES: Tuple[Tuple[str, float], ...] = (
    ("pilot $1k/strategy", 1e3),
    ("paper $100k", 1e5),
)

_EPS = 1e-12


# ── leg tables ───────────────────────────────────────────────────────────────────
def scoring_legs(book_ids: Sequence[str]) -> gtn.LegTable:
    """The table the VARIABLE and IMPACT terms are written on: borrowings free (#90's invoice)."""
    gtn.assert_leg_table_matches_roster()
    tbl = gtn.legs_at_debt_rate(gtn.RAW_LEGS, DEBT_RATE)
    return {b: tbl[b] for b in book_ids}


def touch_legs(book_ids: Sequence[str]) -> gtn.LegTable:
    """The table the GAS COUNT is written on: every leg, because a borrow is a transaction."""
    gtn.assert_leg_table_matches_roster()
    return {b: dict(gtn.RAW_LEGS[b]) for b in book_ids}


# ── the ingredients, measured before any model is applied ────────────────────────
def leg_flow_vectors(hist: css.WeightHistory, legs: gtn.LegTable) -> List[Dict[str, float]]:
    """Per day: {leg: |Δ exposure|} as a FRACTION of AUM. Day 0 trades nothing.

    Split out as its own function on purpose. Both size-dependent terms read it — gas counts
    its keys, impact squares its values — so a defect here would move both at once, and the
    suite pins it independently of either.
    """
    out: List[Dict[str, float]] = []
    prev: Optional[Dict[str, float]] = None
    for w in hist:
        cur = gtn.leg_exposure(w, legs)
        if prev is None:
            out.append({})
            prev = cur
            continue
        day: Dict[str, float] = {}
        for leg in set(cur) | set(prev):
            d = abs(cur.get(leg, 0.0) - prev.get(leg, 0.0))
            if d > _EPS:
                day[leg] = d
        out.append(day)
        prev = cur
    return out


class Ingredients:
    """What the panel says, before any cost model is chosen. All per year."""

    __slots__ = ("legs_touched", "trading_days", "tau", "sum_q2", "n_days")

    def __init__(self, legs_touched, trading_days, tau, sum_q2, n_days):
        self.legs_touched = legs_touched
        self.trading_days = trading_days
        self.tau = tau
        self.sum_q2 = sum_q2
        self.n_days = n_days


def ingredients(
    charge_flows: Sequence[Dict[str, float]],
    touch_flows: Sequence[Dict[str, float]],
    n_days: int,
) -> Ingredients:
    yrs = n_days / 365.0 if n_days else 1.0
    return Ingredients(
        legs_touched=sum(len(d) for d in touch_flows) / yrs,
        trading_days=sum(1 for d in touch_flows if d) / yrs,
        tau=sum(sum(d.values()) for d in charge_flows) / yrs,
        sum_q2=sum(sum(v * v for v in d.values()) for d in charge_flows) / yrs,
        n_days=n_days,
    )


# ── the invoice that knows its own size ──────────────────────────────────────────
def impact_fraction(day: Dict[str, float], aum: float, depth: float) -> float:
    """Exact constant-product fill cost of one day's leg flow, as a fraction of AUM.

    cost_usd(leg) = q² / (R + q)   with q = |Δw_leg| · A.  No free coefficient.
    depth = inf is the frictionless limit and returns exactly 0.0 — that limit is what makes
    this file reduce to #80's invoice, and the suite asserts the reduction cell for cell.
    """
    if math.isinf(depth):
        return 0.0
    if depth <= 0.0:
        raise ValueError("depth must be positive: a zero-depth venue is not a cheaper venue")
    total = 0.0
    for f in day.values():
        q = f * aum
        total += q * q / (depth + q)
    return total / aum


def aum_net(
    gross: Sequence[float],
    charge_flows: Sequence[Dict[str, float]],
    touch_flows: Sequence[Dict[str, float]],
    *,
    aum: float,
    c_var_bps: float,
    gas_per_leg: float,
    depth: float,
    bundled_gas: bool = False,
) -> List[float]:
    """net_t = gross_t − c_var·τ_t/1e4 − gas_t/A − impact_t.

    bundled_gas=True charges ONE fee on any day the portfolio moves at all (the optimistic
    end of the bracket) instead of one per leg (the pessimistic end). Both ends are reported;
    neither is presented alone.
    """
    if aum <= 0.0:
        raise ValueError("AUM must be positive")
    if gas_per_leg < 0.0:
        raise ValueError("gas must not be negative")
    out: List[float] = []
    for g, chg, tch in zip(gross, charge_flows, touch_flows):
        tau = sum(chg.values())
        n_tx = (1 if tch else 0) if bundled_gas else len(tch)
        out.append(
            g
            - tau * c_var_bps / 10_000.0
            - gas_per_leg * n_tx / aum
            - impact_fraction(chg, aum, depth)
        )
    return out


def effective_bps(
    ing: Ingredients,
    *,
    aum: float,
    c_var_bps: float,
    gas_per_leg: float,
    depth: float,
) -> Tuple[float, float, float]:
    """(c_var, gas, impact) expressed in bps PER UNIT OF LEG TURNOVER, so the three land on
    the same axis as the branch's published break-even (#81: h60 break-even 108 bps).

    The impact figure uses the small-q reading q²/R of the exact q²/(R+q) charged above; it is
    a READOUT for the table, never the number scored, and it is the larger of the two, so the
    table never flatters the arm. Both are printed by `main` for the h60 row.
    """
    if ing.tau <= 0.0:
        return c_var_bps, 0.0, 0.0
    gas = 1e4 * gas_per_leg * ing.legs_touched / (aum * ing.tau)
    imp = 0.0 if math.isinf(depth) else 1e4 * aum * ing.sum_q2 / (depth * ing.tau)
    return c_var_bps, gas, imp


class _Row:
    """One scored configuration. Tail is carried NEXT TO the return, never apart from it.

    `ruined` is carried with the numbers, not derived later, because a ruined cell must never
    be silently compared with a solvent one (see `is_ruined`).
    """

    __slots__ = ("apy", "mdd", "calmar", "dcalmar", "ruined")

    def __init__(self, apy, mdd, calmar, dcalmar):
        self.apy, self.mdd, self.calmar, self.dcalmar = apy, mdd, calmar, dcalmar
        self.ruined = False


def is_ruined(net: Sequence[float]) -> bool:
    """True when the equity path reaches zero or below at any point.

    This is not decoration. `mh._apy` returns 0.0 when the compounded path is non-positive
    (`if years <= 0 or compound <= 0: return 0.0`), so a TOTAL WIPEOUT scores APY 0 and can
    outrank an arm that merely lost money. Every table in this file marks such a cell RUIN
    instead of printing a rank for it — a silent floor in the scoring function is exactly the
    kind of thing that turns a ladder into a fiction at its ends.
    """
    eq = 1.0
    for r in net:
        eq *= 1.0 + r
        if eq <= 0.0:
            return True
    return False


def score_at(
    gross: Sequence[float],
    charge_flows: Sequence[Dict[str, float]],
    touch_flows: Sequence[Dict[str, float]],
    base_calmar: float,
    **kw,
) -> _Row:
    net = aum_net(gross, charge_flows, touch_flows, **kw)
    c = mh._calmar(net)
    row = _Row(mh._apy(net), mh._mdd(net), c, c - base_calmar)
    row.ruined = is_ruined(net)
    return row


# ── the free base, verified rather than assumed ──────────────────────────────────
def assert_baseline_pays_nothing(
    eq_charge: Sequence[Dict[str, float]],
    eq_touch: Sequence[Dict[str, float]],
) -> None:
    """Equal-weight must move NO leg on any day. If it ever does, every dCalmar in this file
    stops being 'the active arm's whole bill' and the entry must not be published.
    """
    moved = [i for i, d in enumerate(eq_charge) if d]
    touched = [i for i, d in enumerate(eq_touch) if d]
    if moved or touched:
        raise RuntimeError(
            "equal-weight moved legs on days "
            f"{(moved or touched)[:5]} — the base is no longer free and dCalmar is no longer "
            "the active arm's whole bill; refusing to publish"
        )


# ── the window ───────────────────────────────────────────────────────────────────
def window_edges(
    per_aum: Sequence[Tuple[float, float]],
) -> Tuple[Optional[float], Optional[float]]:
    """(floor, ceiling) of the AUM range where dCalmar > 0, read off the measured ladder.

    Returns the lowest and highest ladder rung that is positive. Never interpolates: an edge
    reported here is a rung that was actually SCORED. An empty window returns (None, None) and
    is printed as empty — not as a point, and not as "about" anything.
    """
    pos = [a for a, d in per_aum if d > 0.0]
    if not pos:
        return None, None
    return min(pos), max(pos)


def _fmt_usd(x: float) -> str:
    if math.isinf(x):
        return "inf"
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if x >= div:
            v = x / div
            return f"${v:.0f}{unit}" if abs(v - round(v)) < 1e-9 else f"${v:.1f}{unit}"
    return f"${x:.0f}"


# ── the run ──────────────────────────────────────────────────────────────────────
def build(dates, book_rets):
    """Everything that does not depend on (A, G, R), computed once."""
    book_ids = sorted(book_rets)
    charge_tbl = scoring_legs(book_ids)
    touch_tbl = touch_legs(book_ids)
    n_days = len(dates) - 1
    built = {}
    for mode, _label in list(ARMS) + [("eq", "equal-weight")]:
        hist = css._weight_history(book_rets, dates, mode)
        gross, _ = css._gross_and_turnover(hist, book_rets)
        chg = leg_flow_vectors(hist, charge_tbl)
        tch = leg_flow_vectors(hist, touch_tbl)
        built[mode] = (gross, chg, tch, ingredients(chg, tch, n_days))
    assert_baseline_pays_nothing(built["eq"][1], built["eq"][2])
    return built, n_days


def run(dates, book_rets) -> Dict[str, dict]:
    built, n_days = build(dates, book_rets)
    out: Dict[str, dict] = {}

    eq_gross, eq_chg, eq_tch, _eq_ing = built["eq"]

    print("\n" + "=" * 100)
    print("Idea AST — AUM-Scaled Toll.  The branch's γ was never a number; it was a size.  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_rets)}  ·  {dates[0]} … {dates[-1]} ({len(dates)} days)")
    print(f"  invoice: c_var·τ/1e4  +  G·L_t/A  +  Σ q²/((R+q)·A)   ·   δ={DEBT_RATE:g}")
    print("=" * 100)

    # ── 0. the base is free, and that is checked, not assumed ────────────────────
    eq_base: Dict[float, float] = {}
    for c_var in CVAR_LADDER:
        net = aum_net(eq_gross, eq_chg, eq_tch, aum=AUM_LADDER[0], c_var_bps=c_var,
                      gas_per_leg=GAS_MODEL_CONSTANT, depth=DEPTH_LADDER[0])
        eq_base[c_var] = mh._calmar(net)
        print(f"\n0. BASELINE equal-weight at c_var={c_var:g}, A={_fmt_usd(AUM_LADDER[0])}, "
              f"G=${GAS_MODEL_CONSTANT:g}, R={_fmt_usd(DEPTH_LADDER[0])}: "
              f"APY={mh._apy(net) * 100:.2f}%  maxDD={mh._mdd(net) * 100:.2f}%  "
              f"Calmar={eq_base[c_var]:.2f}")
    print("   equal-weight moves NO leg on ANY day (asserted above), so this number is the")
    print("   SAME in every cell of every table below at any A, G or R — every dCalmar is")
    print("   therefore the whole bill of the active arm and nothing else.")
    out["baseline"] = {str(k): v for k, v in eq_base.items()}

    # ── 1. the ingredients, before any model ─────────────────────────────────────
    print("\n" + "─" * 100)
    print("1. WHAT THE PANEL SAYS, BEFORE ANY COST MODEL IS CHOSEN (per year).")
    print("   legs/yr drives gas (∝1/A); Σq²/yr drives impact (∝A). τ/yr is the branch's")
    print("   published axis, and it is the ONLY one of the three anyone has charged so far.")
    print(f"{'arm':<16}{'τ/yr (δ=0)':>13}{'legs touched/yr':>18}{'trading days/yr':>18}"
          f"{'Σq²/yr':>12}")
    print("─" * 100)
    for mode, label in ARMS:
        ing = built[mode][3]
        print(f"  {label:<14}{ing.tau:>13.2f}{ing.legs_touched:>18.1f}"
              f"{ing.trading_days:>18.1f}{ing.sum_q2:>12.4f}")
        out.setdefault(mode, {})["ingredients"] = {
            "tau_yr": ing.tau, "legs_yr": ing.legs_touched,
            "trading_days_yr": ing.trading_days, "sum_q2_yr": ing.sum_q2,
        }
    ing_eq = built["eq"][3]
    print(f"  {'equal-weight':<14}{ing_eq.tau:>13.2f}{ing_eq.legs_touched:>18.1f}"
          f"{ing_eq.trading_days:>18.1f}{ing_eq.sum_q2:>12.4f}   ← pays nothing, at any size")

    # ── 2. the toll in bps, on the branch's own axis ─────────────────────────────
    print("\n" + "─" * 100)
    print("2. THE TOLL OF THE BRANCH'S BEST ARM (h60) IN bps PER UNIT OF LEG TURNOVER —")
    print("   the axis on which #81 measured its break-even of 108 bps. c_var is excluded")
    print("   here so the two SIZE-DEPENDENT terms can be read on their own.")
    ing60 = built["h60"][3]
    for gas_label, gas in (("model $12.00/leg", GAS_MODEL_CONSTANT),
                           ("spot $0.045/leg", GAS_SPOT_2026_08_30)):
        print(f"\n   gas anchor: {gas_label}")
        head = f"{'AUM':>8}{'gas bps':>11}" + "".join(
            f"{'imp R=' + _fmt_usd(r):>14}" for r in DEPTH_LADDER)
        print("   " + head)
        print("   " + "─" * (len(head)))
        for a in AUM_LADDER:
            _c, g_bps, _i = effective_bps(ing60, aum=a, c_var_bps=0.0,
                                          gas_per_leg=gas, depth=float("inf"))
            cells = ""
            for r in DEPTH_LADDER:
                _c2, _g2, i_bps = effective_bps(ing60, aum=a, c_var_bps=0.0,
                                                gas_per_leg=gas, depth=r)
                cells += f"{i_bps:>14.1f}"
            print(f"   {_fmt_usd(a):>8}{g_bps:>11.1f}{cells}")
    print("\n   Read the two columns against each other: gas falls with size, impact rises")
    print("   with it. The branch has a WINDOW, not a ceiling.")

    # ── 3. the measured ladder ───────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("3. MEASURED dCalmar vs equal-weight — the arms actually re-run at every size.")
    print("   Positive = the active arm beats doing nothing, net of a toll that knows its own")
    print("   size. This is a measurement, not the inequality of section 2.")
    print("   RUIN = the equity path reached zero. Such a cell is NOT ranked: mh._apy clips a")
    print("   wipeout to APY 0, so a bankrupt arm would otherwise outrank a merely losing one.")
    windows: Dict[str, dict] = {}
    for c_var in CVAR_LADDER:
        base = eq_base[c_var]
        for gas_label, gas in (("model $12.00/leg", GAS_MODEL_CONSTANT),
                               ("spot $0.045/leg", GAS_SPOT_2026_08_30)):
            for depth in DEPTH_LADDER:
                print(f"\n   c_var={c_var:g} bps · gas {gas_label} · depth/leg={_fmt_usd(depth)}")
                head = f"{'AUM':>8}" + "".join(f"{m:>11}" for m, _ in ARMS) + f"{'best':>16}"
                print("   " + head)
                per_arm: Dict[str, List[Tuple[float, float]]] = {m: [] for m, _ in ARMS}
                for a in AUM_LADDER:
                    cells = ""
                    best_mode, best_d = None, None
                    for mode, _label in ARMS:
                        g, chg, tch, _ = built[mode]
                        r = score_at(g, chg, tch, base, aum=a, c_var_bps=c_var,
                                     gas_per_leg=gas, depth=depth)
                        if r.ruined:
                            cells += f"{'RUIN':>11}"
                            continue
                        per_arm[mode].append((a, r.dcalmar))
                        cells += f"{r.dcalmar:>+11.2f}"
                        if best_d is None or r.dcalmar > best_d:
                            best_mode, best_d = mode, r.dcalmar
                    tag = "all RUIN" if best_mode is None else f"{best_mode} {best_d:+.2f}"
                    print(f"   {_fmt_usd(a):>8}{cells}{tag:>16}")
                key = f"c{c_var:g}|{gas:g}|{depth:g}"
                windows[key] = {m: window_edges(v) for m, v in per_arm.items()}
    out["windows"] = {k: {m: [lo, hi] for m, (lo, hi) in v.items()}
                      for k, v in windows.items()}

    # ── 4. the window, stated as a range ─────────────────────────────────────────
    print("\n" + "─" * 100)
    print("4. THE WINDOW — lowest and highest SCORED rung at which the arm beats equal-weight.")
    print("   'empty' means no rung on the ladder is positive. Nothing is interpolated.")
    print(f"{'c_var':>7}{'gas':>10}{'depth/leg':>12}" + "".join(f"{m:>18}" for m, _ in ARMS))
    print("─" * 100)
    for c_var in CVAR_LADDER:
        for gas in (GAS_MODEL_CONSTANT, GAS_SPOT_2026_08_30):
            for depth in DEPTH_LADDER:
                key = f"c{c_var:g}|{gas:g}|{depth:g}"
                cells = ""
                for mode, _ in ARMS:
                    lo, hi = windows[key][mode]
                    cells += f"{('empty' if lo is None else _fmt_usd(lo) + '…' + _fmt_usd(hi)):>18}"
                print(f"{c_var:>7.0f}{gas:>10.3f}{_fmt_usd(depth):>12}{cells}")

    # ── 5. the bracket on gas ────────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("5. THE GAS BRACKET — per-leg (pessimistic, one fee per leg per day) against")
    print("   bundled (optimistic, one fee per day the portfolio moves at all). h60 only.")
    print("   The floor of the window lies between these two columns; neither is the truth.")
    print(f"{'AUM':>8}{'gas':>10}{'per-leg dCal':>15}{'bundled dCal':>15}")
    print("─" * 100)
    g60, chg60, tch60, _ = built["h60"]
    bracket = {}
    for gas in (GAS_MODEL_CONSTANT, GAS_SPOT_2026_08_30):
        for a in AUM_LADDER:
            kw = dict(aum=a, c_var_bps=CONVENTION_COST, gas_per_leg=gas,
                      depth=float("inf"))
            per = score_at(g60, chg60, tch60, eq_base[CONVENTION_COST], **kw).dcalmar
            bun = score_at(g60, chg60, tch60, eq_base[CONVENTION_COST],
                           bundled_gas=True, **kw).dcalmar
            bracket[(gas, a)] = (per, bun)
            print(f"{_fmt_usd(a):>8}{gas:>10.3f}{per:>+15.2f}{bun:>+15.2f}")
    out["gas_bracket"] = {f"{g:g}|{a:g}": v for (g, a), v in bracket.items()}

    # ── 6. our own two sizes ─────────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("6. WHERE THIS DESK ACTUALLY STANDS. Both sizes are ON the ladder, not interpolated.")
    print("   c_var=0 isolates the two size terms; c_var=96 stacks them on the branch's own")
    print("   published convention. The gas anchor is the only thing that moves between the")
    print("   first and second row of every pair — and at $1k it moves the verdict.")
    print(f"{'size':>22}{'c_var':>7}{'gas':>9}{'depth/leg':>12}{'h60 dCalmar':>14}{'verdict':>10}")
    print("─" * 100)
    anchors: Dict[str, float] = {}
    for label, a in ANCHOR_SIZES:
        for c_var in CVAR_LADDER:
            for gas in (GAS_MODEL_CONSTANT, GAS_SPOT_2026_08_30):
                for depth in (1e7, 1e8, float("inf")):
                    r = score_at(g60, chg60, tch60, eq_base[c_var], aum=a,
                                 c_var_bps=c_var, gas_per_leg=gas, depth=depth)
                    verdict = "RUIN" if r.ruined else ("beats" if r.dcalmar > 0 else "loses")
                    shown = "     RUIN" if r.ruined else f"{r.dcalmar:>+14.2f}"
                    anchors[f"{label}|{c_var:g}|{gas:g}|{depth:g}"] = (
                        None if r.ruined else r.dcalmar)
                    print(f"{label:>22}{c_var:>7.0f}{gas:>9.3f}{_fmt_usd(depth):>12}"
                          f"{shown:>14}{verdict:>10}")
    out["anchors"] = anchors

    # ── 7. does the RANKING survive size, as it survived γ in #90? ───────────────
    print("\n" + "─" * 100)
    print("7. RANKING SURVIVAL. #90 found the ORDER of the arms survives every γ. Size is a")
    print("   different axis and it need not behave the same way, so it is checked, not")
    print("   assumed. Ruined rungs are marked '·' and NOT counted as flips: there the ranking")
    print("   is an artefact of the APY clip, not a statement about the arms.")
    print(f"{'gas':>10}{'depth/leg':>12}" + "".join(f"{_fmt_usd(a):>12}" for a in AUM_LADDER))
    print("─" * 100)
    flips = 0
    scored = 0
    for gas in (GAS_MODEL_CONSTANT, GAS_SPOT_2026_08_30):
        for depth in DEPTH_LADDER:
            cells = ""
            for a in AUM_LADDER:
                best_mode, best_d = None, None
                for mode, _ in ARMS:
                    g, chg, tch, _ = built[mode]
                    r = score_at(g, chg, tch, eq_base[CONVENTION_COST], aum=a,
                                 c_var_bps=CONVENTION_COST, gas_per_leg=gas, depth=depth)
                    if r.ruined:
                        continue
                    if best_d is None or r.dcalmar > best_d:
                        best_mode, best_d = mode, r.dcalmar
                if best_mode is None:
                    cells += f"{'·':>12}"
                    continue
                scored += 1
                if best_mode != "h60":
                    flips += 1
                cells += f"{best_mode:>12}"
            print(f"{gas:>10.3f}{_fmt_usd(depth):>12}{cells}")
    print(f"\n   solvent rungs scored: {scored}  ·  rungs where h60 is NOT best: {flips}")
    out["ranking_flips"] = flips
    out["ranking_scored"] = scored

    # ── 8. does the WINDOW survive the canonical split? ──────────────────────────
    print("\n" + "─" * 100)
    print("8. SPLIT. The window is a statement about a COST, not about a fitted rule, so it")
    print("   ought to be the same on both halves of the canonical 2025-06-30 boundary. If it")
    print("   is not, the window is a property of one period and must not be quoted as a law.")
    cut = datetime.date.fromisoformat(SPLIT_DATE)
    #: series index k corresponds to dates[k+1] (see css._weight_history / mh._run)
    k_cut = next((k for k in range(len(dates) - 1) if dates[k + 1] > cut), len(dates) - 1)
    print(f"   TRAIN {dates[1]}…{dates[k_cut]} ({k_cut} d)  ·  "
          f"TEST {dates[k_cut + 1]}…{dates[-1]} ({len(dates) - 1 - k_cut} d)")
    print(f"{'half':>7}{'c_var':>7}{'gas':>9}{'depth/leg':>12}{'h60 window over the AUM ladder':>36}")
    print("─" * 100)
    halves = (("TRAIN", slice(0, k_cut)), ("TEST", slice(k_cut, None)))
    split_windows: Dict[str, list] = {}
    for hname, sl in halves:
        eqn = aum_net(eq_gross[sl], eq_chg[sl], eq_tch[sl], aum=1e5, c_var_bps=0.0,
                      gas_per_leg=GAS_MODEL_CONSTANT, depth=1e8)
        base_h = mh._calmar(eqn)
        for c_var in CVAR_LADDER:
            eqn_c = aum_net(eq_gross[sl], eq_chg[sl], eq_tch[sl], aum=1e5, c_var_bps=c_var,
                            gas_per_leg=GAS_MODEL_CONSTANT, depth=1e8)
            base_h = mh._calmar(eqn_c)
            for gas in (GAS_MODEL_CONSTANT, GAS_SPOT_2026_08_30):
                for depth in (1e8, 1e9):
                    pts = []
                    for a in AUM_LADDER:
                        r = score_at(g60[sl], chg60[sl], tch60[sl], base_h, aum=a,
                                     c_var_bps=c_var, gas_per_leg=gas, depth=depth)
                        if not r.ruined:
                            pts.append((a, r.dcalmar))
                    lo, hi = window_edges(pts)
                    txt = "empty" if lo is None else f"{_fmt_usd(lo)}…{_fmt_usd(hi)}"
                    split_windows[f"{hname}|{c_var:g}|{gas:g}|{depth:g}"] = [lo, hi]
                    print(f"{hname:>7}{c_var:>7.0f}{gas:>9.3f}{_fmt_usd(depth):>12}{txt:>36}")
    out["split_windows"] = split_windows

    print("\n" + "=" * 100)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 100)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    dates, book_rets = gtn.load_real_panel()
    run(dates, book_rets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
