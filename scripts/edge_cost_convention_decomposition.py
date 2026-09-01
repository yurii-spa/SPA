#!/usr/bin/env python3
"""
scripts/edge_cost_convention_decomposition.py — registry idea CVD
(Cost Convention Decomposition)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

Working name CVD. The registry NUMBER is claimed at DELIVERY.


THE ORDER, AND WHY IT CANNOT BE FILLED AS WRITTEN
=================================================
#91 AST closed with one instruction, and it is the only thing standing between the
#79–#91 branch and a verdict:

    "судьба всей ветки упирается ... в разложение конвенции 96 bps на размеро-НЕзависимую
     часть (комиссия, спред) и размеро-зависимую (газ, удар) ... разложить 96 bps на
     составляющие с датой и источником у каждой"

The order presumes the convention is a COST that can be split into parts. It is not, and
this file's first job is to show that with code rather than with an opinion.

    · WHERE 96 COMES FROM.  `scripts/edge_cost_signal_separation.py:107` defines
      `CONVENTION_COST = 96` and its own comment names the source: "the registry's standing
      convention (break-even of #10)". Registry #10 (`edge_turnover_cost_breakeven.py`,
      2026-07-15) SWEPT a cost axis over the #9 causal overlay and reported the cost at
      which that overlay's Calmar fell to static #3's. 96 bps is therefore an OUTPUT of a
      different arm's sensitivity analysis — the price at which somebody ELSE's edge died.
      Nobody ever measured it as a price anybody pays. It has no parts to decompose,
      because it was never assembled from parts.

    · AND IT IS APPLIED AT TWICE ITS OWN DEFINITION.  #10 charges
          turnover_t = 0.5 · Σ_i |w_t[i] − w_{t−1}[i]|        (the ½ is in its source)
      while every harness from #80 to #91 charges
          τ_t        =       Σ_b |w_t[b] − w_{t−1}[b]|        (no ½)
      and then multiplies by the same 96. `measure_turnover_definition_ratio()` below runs
      ONE weight path through BOTH modules and prints the ratio rather than asserting it;
      the suite pins it. In this branch's units #10's number is 48, not 96 — and #91 itself
      measured that the first ladder step of exactly that size costs h60 **1.04 Calmar**,
      more than any effect the whole branch has ever claimed. The convention is not merely
      unsourced; it is off by a factor that dominates the branch's own findings.

    · WHAT THE TREE'S OWN COST MODEL SAYS.  `spa_core/backtesting/tier1/cost_model.py` — the
      single source named by `docs/cost_model_provenance.md` §1 — contains no 96 and no fee
      line at all. Its only size-INDEPENDENT charge on turnover is SLIPPAGE_BPS_STABLE = 8.0
      (plus BRIDGE_BPS = 5.0 per rebalance, and only multi-chain). Gas is dollars per leg,
      i.e. size-DEPENDENT, and #91 already moved it to the size-dependent side of the
      invoice. So the requested split, run against the tree instead of against the
      convention, yields 8 (undated) on the size-independent side — and after #91's invoice
      models slippage EXPLICITLY as q²/(R+q), even that 8 is double counting, since it is
      itself a slippage constant.

    · AND THE THREE INSTRUMENTS NAMED FOR THESE COSTS DO NOT CONTAIN OBSERVATIONS.  This
      was nearly written here as "they are empty", which is FALSE and would have been the
      same class of error as the convention itself — a claim about numbers, made without
      reading them. `read_instrument_content()` reads all three and reports what is in the
      non-null rows, so the claim ages with the tree rather than with this docstring:
        `data/fee_structure_log`      — rows with a rate carry `avg_effective_rate: 0.3`
          (percent) beside `total_revenue_30d: 0.0` and `cheapest == most_expensive ==
          "Uniswap"`: one protocol, no revenue behind the average. 0.3 % is the standard
          Uniswap volatile-pair tier; a stablecoin pair trades on the 0.01–0.05 % tiers.
          It is a default that survived, not a fee our books paid;
        `data/slippage_impact_log`    — `total_trades` ∈ {1,2,3,5}, and ZERO rows carry any
          size or notional field. Slippage without a size axis cannot price a rebalance;
        `data/gas_cost_breakeven_log` — the rows that are not `INSUFFICIENT_DATA` are named
          "USDC-LP (small, expensive)" and "stETH (large, cheap)". Those strings are the
          producer's own `__main__` demo block; `demo_rows_trace_to_producer()` re-derives
          that by reading the analyser's source, so it is checked, not recognised by eye.

    Net: the size-independent part of the toll — pool fee plus spread — has NO number in
    this repository, dated or otherwise. Publishing one would be the exact failure #90
    named when it refused to invent γ.

WHAT IS DELIVERED INSTEAD, AND WHY IT IS STRONGER
-------------------------------------------------
If the cost cannot be measured, measure what the branch can AFFORD, and hand the owner an
inequality instead of a guess:

    c*(A, G, R)  =  the largest size-independent toll, in bps of leg turnover, at which the
                    arm still beats equal-weight — read off a 1-bps integer grid, never
                    interpolated, with the full crossing profile printed so that a cell with
                    more than one crossing is visible rather than summarised away.

That turns the branch's open question from "what does it cost?" (unanswerable today) into
"is a stablecoin swap fee plus spread bigger or smaller than c*?" (answerable by anyone with
a pool page, and falsifiable). Everything else — panel, arms, weights, split, invoice,
leg tables, the free equal-weight base — is #91's, imported and reused verbatim.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; every caveat of #91, #90, #88, #83, #82 and #80 carries over unchanged,
    including that the leverage signal is judged on the same series it was formed on;
  * c* is NOT a claim that the branch is fundable. It is an upper bound on an unmeasured
    number. A cell with c* = 0 says the branch loses even for FREE fees; a cell with a large
    c* says only that the fee is not what kills it — the arm still has to survive every
    other caveat in the branch;
  * R (tradeable depth per leg) is still NOT measured — no depth feed exists, protocol TVL
    is not swap depth, the one TVL column in the tree is stamped `static`. R stays an AXIS,
    exactly as in #91, and every number below is conditional on a stated R;
  * gas keeps #91's two anchors ($12.00 undated model constant, $0.045 spot of 2026-08-30)
    and is charged per leg touched per day — the pessimistic end. #91's bundled bracket is
    not re-derived here; its conclusion (the floor lies between the two) is unchanged;
  * the 1-bps grid is a MEASUREMENT grid, not a fitted parameter: its range and step were
    fixed before any number was read, and c* is always a rung that was actually scored;
  * Calmar need not be monotone in the toll (the drawdown denominator can move either way),
    so monotonicity is CHECKED per cell and reported, not assumed. A cell whose profile
    crosses zero more than once is printed as such and its c* is labelled a lower bound;
  * no parameter is chosen on TEST: the AUM ladder, depth ladder, gas anchors, the c_var
    grid and the canonical 2025-06-30 split were all fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_aum_scaled_toll as ast  # noqa: E402  (#91 invoice, reused verbatim)
import edge_cost_signal_separation as css  # noqa: E402  (#80 harness, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 harness, reused verbatim)
import edge_turnover_cost_breakeven as tcb  # noqa: E402  (#10 — the ORIGIN of the 96)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

ARMS = ast.ARMS
AUM_LADDER = ast.AUM_LADDER
DEPTH_LADDER = ast.DEPTH_LADDER
GAS_ANCHORS: Tuple[Tuple[str, float], ...] = (
    ("model $12.00/leg", ast.GAS_MODEL_CONSTANT),
    ("spot $0.045/leg", ast.GAS_SPOT_2026_08_30),
)
SPLIT_DATE = ast.SPLIT_DATE

#: The measurement grid for the affordable toll, in bps of leg turnover. Fixed before any
#: number was read. Step 1 bps: c* is always a rung that was SCORED, never interpolated.
#: The top rung is 4x the branch's published convention, so a cell that never crosses inside
#: the grid is reported as ">=400", not silently clipped to the convention.
CVAR_GRID_MAX = 400
CVAR_GRID_STEP = 1

#: The coarse profile printed next to every headline cell, so the shape of the crossing is
#: visible and not just its location. On the grid, hence scored.
PROFILE_RUNGS: Tuple[int, ...] = (0, 8, 13, 24, 48, 96, 192, 384)

#: Candidate size-independent tolls placed against c*. NONE of them is a measurement of the
#: fee+spread this branch would actually pay; each is labelled with what it really is.
CANDIDATES: Tuple[Tuple[str, float, str], ...] = (
    ("0 — free fees (structural floor)", 0.0, "limit, not a price"),
    ("8 — tree's slippage constant", 8.0,
     "cost_model.py SLIPPAGE_BPS_STABLE; undated; a SLIPPAGE number, already modelled by q²/(R+q)"),
    ("13 — that constant + bridge", 13.0,
     "cost_model.py 8 + BRIDGE_BPS 5; undated; bridge applies only multi-chain"),
    ("48 — #10's break-even in THIS harness's units", 48.0,
     "the convention corrected for the ½ in #10's turnover; still a break-even, not a price"),
    ("96 — the convention as actually charged", 96.0,
     "edge_cost_signal_separation.py:107; a break-even of ANOTHER overlay, applied at 2x its own definition"),
)

#: #91's published section-4 table, verbatim from docs/DYNAMIC_LEVERAGE_GUARDIAN.md.
#: (aum, c_var, gas, depth) -> dCalmar of h60. This file re-derives them; if any cell moves,
#: the invoice is no longer #91's and nothing below may be compared with #91's verdict.
AST_PUBLISHED_ANCHORS: Tuple[Tuple[Tuple[float, float, float, float], float], ...] = (
    ((1e3, 0.0, ast.GAS_MODEL_CONSTANT, 1e8), -4.12),
    ((1e3, 0.0, ast.GAS_SPOT_2026_08_30, 1e8), +2.13),
    ((1e5, 0.0, ast.GAS_MODEL_CONSTANT, 1e8), +1.71),
    ((1e5, 0.0, ast.GAS_SPOT_2026_08_30, 1e8), +2.28),
    ((1e3, 96.0, ast.GAS_SPOT_2026_08_30, 1e8), -1.43),
    ((1e5, 96.0, ast.GAS_SPOT_2026_08_30, 1e8), -1.32),
)

_EPS = 1e-12


# ── section 0 · the provenance, measured rather than asserted ────────────────────
def measure_turnover_definition_ratio() -> float:
    """Run ONE weight path through #10's charger and #80's charger; return their ratio.

    Behavioural, not textual: both quantities come out of the SOURCE modules, so this stays
    true if either definition is edited, and stops being true the moment they agree. (A test
    that compared two copies of a literal would be blind to exactly the drift it exists to
    catch.)
    """
    # A 3-asset path, because #10's replay is written for its 3 regime sleeves. Two moves,
    # so the ratio cannot be an artefact of a single edge case.
    path = [
        list(tcb.WEIGHTS_CRUISE),
        [0.05, 0.25, 0.70],
        [0.40, 0.45, 0.15],
    ]
    dates = [f"2025-01-0{i + 1}" for i in range(len(path))]
    flat: Dict[str, float] = {d: 0.0 for d in dates}
    _eq, _n, tcb_turnover = tcb._replay_with_cost(dates, path, flat, flat, flat, 0.0)

    # The same path through #80's turnover, which is what #79–#91 charge the convention on.
    books = ("a", "b", "c")
    hist = [{b: w[i] for i, b in enumerate(books)} for w in path]
    css_turnover = 0.0
    prev: Optional[Dict[str, float]] = None
    for w in hist:
        if prev is not None:
            css_turnover += sum(abs(w[b] - prev[b]) for b in books)
        prev = w

    if tcb_turnover <= _EPS:
        raise RuntimeError("the probe path moved nothing — the ratio would be meaningless")
    return css_turnover / tcb_turnover


def read_tree_cost_model() -> Dict[str, float]:
    """The tree's own cost constants, read from the module the provenance doc names as the
    single source. Imported, not copied, so this section cannot drift away from the code."""
    from spa_core.backtesting.tier1 import cost_model as cm

    return {
        "slippage_bps_stable": float(cm.SLIPPAGE_BPS_STABLE),
        "bridge_bps": float(cm.BRIDGE_BPS),
        "gas_usd_ethereum": float(cm.GAS_USD_PER_POSITION_CHANGE["ethereum"]),
        "gas_usd_blended": float(cm.GAS_USD_PER_POSITION_CHANGE["blended"]),
    }


def read_instrument_content(data_dir: Optional[Path] = None) -> Dict[str, str]:
    """What the three instruments named for these costs actually contain, today.

    Returns a verdict string per instrument. `absent` is reported as `absent`, never as
    `empty`: a worktree may have no `data/` at all, and the two must not read alike. Nor is
    "has rows" reported as "has measurements" — the rows are described, and the description
    is what the reader judges.
    """
    base = data_dir if data_dir is not None else (ROOT / "data")
    out: Dict[str, str] = {}

    def _rows(name: str) -> Optional[list]:
        p = base / name
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text())
        except (ValueError, OSError):
            return None
        return d if isinstance(d, list) else [d]

    rows = _rows("fee_structure_log.json")
    if rows is None:
        out["fee_structure_log"] = "absent (no data/ in this tree)"
    else:
        rated = [r for r in rows if r.get("avg_effective_rate") is not None]
        vals = sorted({float(r["avg_effective_rate"]) for r in rated})
        rev = sorted({float(r.get("total_revenue_30d") or 0.0) for r in rated})
        one_name = {(r.get("cheapest"), r.get("most_expensive")) for r in rated}
        out["fee_structure_log"] = (
            f"{len(rows)} rows, {len(rated)} with a rate; rate∈{vals} %, "
            f"revenue_30d∈{rev}, (cheapest,dearest)∈{sorted(map(str, one_name))}")

    rows = _rows("slippage_impact_log.json")
    if rows is None:
        out["slippage_impact_log"] = "absent (no data/ in this tree)"
    else:
        sized = sum(1 for r in rows
                    if any(("size" in k or "notional" in k) for k in r))
        trades = sorted({r["total_trades"] for r in rows if r.get("total_trades") is not None})
        out["slippage_impact_log"] = (
            f"{len(rows)} rows, total_trades∈{trades}, {sized} with a size axis")

    rows = _rows("gas_cost_breakeven_log.json")
    if rows is None:
        out["gas_cost_breakeven_log"] = "absent (no data/ in this tree)"
    else:
        usable = [r for r in rows if "INSUFFICIENT_DATA" not in (r.get("flags") or [])]
        names = sorted({str(r.get("name")) for r in usable})
        out["gas_cost_breakeven_log"] = (
            f"{len(rows)} rows, {len(usable)} without INSUFFICIENT_DATA; "
            f"their names: {names}")
    return out


#: The analyser whose `__main__` demo block is the suspected author of every usable row in
#: `data/gas_cost_breakeven_log.json`. Named here so the check below reads the SOURCE.
GAS_ANALYSER = ROOT / "spa_core" / "analytics" / "defi_protocol_gas_cost_breakeven_analyzer.py"


def demo_rows_trace_to_producer(data_dir: Optional[Path] = None) -> Tuple[int, int]:
    """(usable rows, of them found verbatim in the producer's `__main__` demo block).

    Reads the analyser's SOURCE rather than trusting a remembered string, because the whole
    point of the check is that a log full of a module's own examples is indistinguishable
    from a log full of observations unless somebody goes and looks.
    """
    base = data_dir if data_dir is not None else (ROOT / "data")
    p = base / "gas_cost_breakeven_log.json"
    if not p.exists() or not GAS_ANALYSER.exists():
        return 0, 0
    try:
        rows = json.loads(p.read_text())
    except (ValueError, OSError):
        return 0, 0
    src = GAS_ANALYSER.read_text()
    demo = src[src.index('if __name__ == "__main__":'):] if 'if __name__ == "__main__":' in src else ""
    usable = [r for r in rows if "INSUFFICIENT_DATA" not in (r.get("flags") or [])]
    hits = sum(1 for r in usable if str(r.get("name")) and f'"{r.get("name")}"' in demo)
    return len(usable), hits


# ── section 2 · the affordable toll ──────────────────────────────────────────────
class Crossing:
    """The profile of one cell's dCalmar against the toll, and where it crosses zero.

    `c_star` is a SCORED rung, never an interpolation. `single` says whether the profile
    crosses zero exactly once over the grid; when it does not, `c_star` is only a lower
    bound and every table in this file labels it so.
    """

    __slots__ = ("c_star", "single", "at_zero", "ruined_any", "profile")

    def __init__(self, c_star, single, at_zero, ruined_any, profile):
        self.c_star = c_star            # int rung, or None when even c=0 loses
        self.single = single
        self.at_zero = at_zero          # dCalmar at c_var=0, for scale
        self.ruined_any = ruined_any
        self.profile = profile          # {rung: dCalmar or None if RUIN}


def single_crossing(signs: Sequence[bool]) -> bool:
    """True when the profile changes sign at most once along the grid.

    Pure and separate on purpose. A single c* is only an honest summary of a profile that
    crosses ONCE; a profile that dips negative and comes back has a c* that is a lower bound
    and must say so. Summarising a two-crossing profile as one number is exactly how a
    ladder turns into a fiction at its ends, so the rule is a function the suite can hit
    directly with hand-made profiles rather than a line buried inside a scan.
    """
    return sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1]) <= 1


def check_ast_anchors(
    built: Dict[str, tuple],
    base_calmar: float,
    anchors: Sequence[Tuple[Tuple[float, float, float, float], float]] = AST_PUBLISHED_ANCHORS,
    tol: float = 0.005,
) -> List[List[float]]:
    """Re-derive #91's published section-4 cells through the imported invoice, or REFUSE.

    Nothing in this file may be set beside #91's verdict unless it was scored on #91's
    invoice. Importing the module is not evidence of that — an edit anywhere in the chain
    (#79 weights, #80 turnover, #83 leg table, #91 impact) would move these numbers while
    every import still resolved. So the comparison is against the numbers as PUBLISHED in
    the registry, and a mismatch raises rather than warns.
    """
    g, chg, tch, _ = built["h60"]
    rows: List[List[float]] = []
    for (a, c, gas, depth), published in anchors:
        got = ast.score_at(g, chg, tch, base_calmar, aum=a, c_var_bps=c,
                           gas_per_leg=gas, depth=depth).dcalmar
        if abs(got - published) > tol:
            raise RuntimeError(
                f"anchor moved: #91 published {published:+.2f} for "
                f"(A={a:g}, c={c:g}, G={gas:g}, R={depth:g}) and this run scores {got:+.2f} — "
                "the invoice is no longer #91's; refusing to publish")
        rows.append([a, c, gas, depth, published, got])
    return rows


def affordable_cvar(
    gross: Sequence[float],
    charge_flows: Sequence[Dict[str, float]],
    touch_flows: Sequence[Dict[str, float]],
    base_calmar: float,
    *,
    aum: float,
    gas_per_leg: float,
    depth: float,
    grid_max: int = CVAR_GRID_MAX,
    step: int = CVAR_GRID_STEP,
) -> Crossing:
    """Scan the toll on an integer grid and report where the arm stops beating the base.

    The base is equal-weight, which moves no leg on any day and therefore pays NOTHING at
    any toll (asserted by #91's `assert_baseline_pays_nothing`, re-run by `build`). So
    dCalmar here is the whole bill of the active arm and c* is the whole toll it can carry.
    """
    signs: List[bool] = []
    profile: Dict[int, Optional[float]] = {}
    ruined_any = False
    c_star: Optional[int] = None
    at_zero = 0.0
    for c in range(0, grid_max + 1, step):
        row = ast.score_at(gross, charge_flows, touch_flows, base_calmar,
                           aum=aum, c_var_bps=float(c), gas_per_leg=gas_per_leg, depth=depth)
        if c == 0:
            at_zero = None if row.ruined else row.dcalmar
        if row.ruined:
            ruined_any = True
            positive = False
        else:
            positive = row.dcalmar > 0.0
        if c in PROFILE_RUNGS:
            profile[c] = None if row.ruined else row.dcalmar
        signs.append(positive)
        if positive:
            c_star = c
    return Crossing(c_star, single_crossing(signs), at_zero, ruined_any, profile)


def _fmt_c(x: Crossing) -> str:
    if x.c_star is None:
        return "loses at 0"
    tag = "" if x.single else "≥"
    if x.c_star >= CVAR_GRID_MAX:
        return f"≥{CVAR_GRID_MAX}"
    return f"{tag}{x.c_star}"


# ── the run ──────────────────────────────────────────────────────────────────────
def run(dates, book_rets) -> Dict[str, object]:
    built, n_days = ast.build(dates, book_rets)
    out: Dict[str, object] = {}
    eq_gross, eq_chg, eq_tch, _ = built["eq"]
    base = mh._calmar(ast.aum_net(eq_gross, eq_chg, eq_tch, aum=AUM_LADDER[0],
                                  c_var_bps=0.0, gas_per_leg=ast.GAS_MODEL_CONSTANT,
                                  depth=DEPTH_LADDER[0]))

    print("\n" + "=" * 100)
    print("Idea CVD — the convention was never a cost. What the branch can AFFORD.  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  books {len(book_rets)}  ·  {dates[0]} … {dates[-1]} ({len(dates)} days)")
    print(f"  invoice (#91, verbatim): c_var·τ/1e4 + G·L_t/A + Σ q²/((R+q)·A)  ·  δ={ast.DEBT_RATE:g}")
    print("=" * 100)

    # ── anchor · the invoice is #91's, and that is shown before anything is claimed ──
    print("\n" + "─" * 100)
    print("ANCHOR. Every cell below is scored through #91's invoice, imported not re-typed.")
    print("   These six cells are #91's own published section-4 table; if any of them moved,")
    print("   nothing in this file may be compared with #91's verdict. Refuses on mismatch.")
    anchor_out = check_ast_anchors(built, base)
    print(f"{'AUM':>8}{'c_var':>7}{'gas':>9}{'depth':>9}{'#91 published':>16}{'re-derived':>13}")
    print("─" * 100)
    for a, c, gas, depth, published, got in anchor_out:
        print(f"{ast._fmt_usd(a):>8}{c:>7.0f}{gas:>9.3f}{ast._fmt_usd(depth):>9}"
              f"{published:>+16.2f}{got:>+13.2f}")
    out["ast_anchors"] = anchor_out

    # ── 0. provenance ────────────────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("0. WHERE THE 96 COMES FROM — traced, not recalled.")
    ratio = measure_turnover_definition_ratio()
    print(f"   · the literal lives at edge_cost_signal_separation.py:107 as CONVENTION_COST")
    print(f"     = {css.CONVENTION_COST}, and its own comment names it 'break-even of #10'.")
    print(f"   · #10 (edge_turnover_cost_breakeven.py) SWEPT that axis over the #9 overlay and")
    print(f"     reported the cost at which SOMEONE ELSE'S edge died. It is an output of a")
    print(f"     sensitivity analysis, not a price anybody was ever quoted.")
    print(f"   · TURNOVER DEFINITION RATIO (one path through both source modules, measured")
    print(f"     here rather than asserted): #80/#91 charge {ratio:.3f}× what #10 charged.")
    print(f"     In this branch's units #10's number is {css.CONVENTION_COST / ratio:.0f}, "
          f"not {css.CONVENTION_COST}.")
    out["turnover_ratio"] = ratio
    out["convention_in_branch_units"] = css.CONVENTION_COST / ratio

    cm = read_tree_cost_model()
    print(f"\n   THE TREE'S OWN COST MODEL (spa_core/backtesting/tier1/cost_model.py — the one")
    print(f"   source docs/cost_model_provenance.md §1 names) contains no 96 and no fee line:")
    print(f"     slippage on turnover : {cm['slippage_bps_stable']:g} bps   (size-INdependent as written; undated)")
    print(f"     bridge per rebalance : {cm['bridge_bps']:g} bps   (multi-chain only; undated)")
    print(f"     gas ethereum / blended: ${cm['gas_usd_ethereum']:g} / ${cm['gas_usd_blended']:g} per leg "
          f"(size-DEPENDENT; #91 moved it)")
    print(f"     pool / protocol fee  : ABSENT — the model has no such line at all")
    out["cost_model"] = cm

    inst = read_instrument_content()
    print(f"\n   AND THE THREE INSTRUMENTS NAMED FOR THESE COSTS, read just now. They are NOT")
    print(f"   empty — that is what this section nearly claimed without looking — but nothing")
    print(f"   in them is an observation of what a rebalance of ours costs:")
    for k, v in inst.items():
        print(f"     {k}")
        print(f"       {v}")
    usable, hits = demo_rows_trace_to_producer()
    print(f"     · of the {usable} usable gas rows, {hits} are found VERBATIM in the producer's")
    print(f"       own __main__ demo block ({GAS_ANALYSER.name}) — a module's examples written")
    print(f"       into a live log read exactly like readings until somebody opens the source.")
    print(f"   ⇒ the size-independent part of the toll — pool fee plus spread — has NO measured")
    print(f"     number in this repository. The one rate present (0.3 %) is the Uniswap")
    print(f"     volatile-pair tier standing beside zero revenue and a single protocol; a")
    print(f"     stablecoin pair trades on 0.01–0.05 %. #91's order cannot be filled as")
    print(f"     written, and inventing the number would be the failure #90 refused to commit.")
    out["instruments"] = inst
    out["gas_demo_rows"] = [usable, hits]

    # ── 1. what we are allowed to say instead ────────────────────────────────────
    print("\n" + "─" * 100)
    print("1. THE MEASUREMENT THAT REPLACES IT — c*, the largest size-independent toll in bps")
    print("   of leg turnover at which the arm still beats equal-weight. Read off a 1-bps")
    print(f"   integer grid 0…{CVAR_GRID_MAX}; every c* below is a rung that was SCORED.")
    print("   'loses at 0' = the arm is behind even with FREE fees, so no fee can save it.")
    print(f"   '≥{CVAR_GRID_MAX}' = the profile never crossed inside the grid.")
    print("   A leading ≥ marks a cell whose profile crosses zero more than once; there c* is")
    print("   only a lower bound and is labelled, not smoothed.")

    cells: Dict[str, Crossing] = {}
    for gas_label, gas in GAS_ANCHORS:
        print(f"\n   gas anchor: {gas_label}")
        head = f"{'AUM':>8}" + "".join(f"{'R=' + ast._fmt_usd(r):>14}" for r in DEPTH_LADDER)
        print("   " + head)
        print("   " + "─" * len(head))
        for a in AUM_LADDER:
            row = ""
            for depth in DEPTH_LADDER:
                g, chg, tch, _ = built["h60"]
                x = affordable_cvar(g, chg, tch, base, aum=a, gas_per_leg=gas, depth=depth)
                cells[f"h60|{gas:g}|{a:g}|{depth:g}"] = x
                row += f"{_fmt_c(x):>14}"
            print(f"   {ast._fmt_usd(a):>8}{row}")
    out["c_star_h60"] = {k: [v.c_star, v.single] for k, v in cells.items()}
    wobbly = [k for k, v in cells.items() if not v.single]
    print(f"\n   crossing profiles scored: {len(cells)}  ·  crossing zero more than once: "
          f"{len(wobbly)}{'' if not wobbly else ' → ' + ', '.join(wobbly)}")
    print("   (a clean single crossing is what makes a single c* per cell a legitimate")
    print("    summary; the count is printed so the reader does not have to take it on trust.)")
    out["non_single_cells"] = wobbly

    # ── 2. the candidates placed against it ──────────────────────────────────────
    print("\n" + "─" * 100)
    print("2. THE CANDIDATES, AND WHAT EACH ONE REALLY IS. None is a measurement of the fee")
    print("   plus spread this branch would pay; the third column says what it is instead.")
    for label, val, what in CANDIDATES:
        print(f"   {val:>5.0f} bps · {label}")
        print(f"           {what}")
    out["candidates"] = [[l, v, w] for l, v, w in CANDIDATES]

    print("\n   VERDICT PER CANDIDATE at the sizes this desk actually has (h60, per-leg gas,")
    print("   both gas anchors, three depths). 'beats' means dCalmar > 0 at that toll.")
    print(f"{'size':>22}{'gas':>9}{'depth':>10}{'c*':>10}" +
          "".join(f"{int(v):>7}" for _l, v, _w in CANDIDATES))
    print("─" * 100)
    verdicts: Dict[str, object] = {}
    for label, a in ast.ANCHOR_SIZES:
        for _gl, gas in GAS_ANCHORS:
            for depth in (1e7, 1e8, 1e9):
                x = cells.get(f"h60|{gas:g}|{a:g}|{depth:g}")
                if x is None:
                    g, chg, tch, _ = built["h60"]
                    x = affordable_cvar(g, chg, tch, base, aum=a, gas_per_leg=gas, depth=depth)
                marks = ""
                for _l, v, _w in CANDIDATES:
                    ok = x.c_star is not None and x.c_star >= v
                    marks += f"{('beats' if ok else '—'):>7}"
                print(f"{label:>22}{gas:>9.3f}{ast._fmt_usd(depth):>10}{_fmt_c(x):>10}{marks}")
                verdicts[f"{label}|{gas:g}|{depth:g}"] = _fmt_c(x)
    out["anchor_verdicts"] = verdicts

    # ── 3. the profile, so the crossing is visible ───────────────────────────────
    print("\n" + "─" * 100)
    print("3. THE PROFILE behind one headline cell (h60, A=$100k, per-leg gas). The table")
    print("   above is a single number per cell; this is the shape it was read from, so a")
    print("   reader can see that the crossing is a crossing and not a cliff or a wobble.")
    print(f"{'gas':>9}{'depth':>10}" + "".join(f"{'c=' + str(r):>10}" for r in PROFILE_RUNGS))
    print("─" * 100)
    prof_out: Dict[str, object] = {}
    for _gl, gas in GAS_ANCHORS:
        for depth in DEPTH_LADDER:
            x = cells[f"h60|{gas:g}|{1e5:g}|{depth:g}"]
            row = "".join(
                ("      RUIN" if x.profile.get(r) is None else f"{x.profile[r]:>+10.2f}")
                for r in PROFILE_RUNGS)
            print(f"{gas:>9.3f}{ast._fmt_usd(depth):>10}{row}")
            prof_out[f"{gas:g}|{depth:g}"] = {str(r): x.profile.get(r) for r in PROFILE_RUNGS}
    out["profile_100k"] = prof_out

    # ── 4. every arm, so the finding is not about one arm ────────────────────────
    print("\n" + "─" * 100)
    print("4. EVERY ARM at the two sizes this desk has (per-leg gas, R=$1B). #90/#91 found the")
    print("   ORDER of the arms survives every toll and every size; c* is a different readout")
    print("   and it is checked here rather than inherited.")
    print(f"{'size':>22}{'gas':>9}" + "".join(f"{m:>12}" for m, _ in ARMS))
    print("─" * 100)
    per_arm: Dict[str, object] = {}
    for label, a in ast.ANCHOR_SIZES:
        for _gl, gas in GAS_ANCHORS:
            row = ""
            for mode, _ in ARMS:
                g, chg, tch, _ = built[mode]
                x = affordable_cvar(g, chg, tch, base, aum=a, gas_per_leg=gas, depth=1e9)
                row += f"{_fmt_c(x):>12}"
                per_arm[f"{label}|{gas:g}|{mode}"] = x.c_star
            print(f"{label:>22}{gas:>9.3f}{row}")
    out["per_arm"] = per_arm

    # ── 5. the split ─────────────────────────────────────────────────────────────
    print("\n" + "─" * 100)
    print("5. SPLIT. c* is a statement about an AFFORDABLE COST, not about a fitted rule, so")
    print(f"   it ought to land in the same place on both halves of the canonical {SPLIT_DATE}")
    print("   boundary. If it does not, it is a property of one period and must not be quoted.")
    cut = datetime.date.fromisoformat(SPLIT_DATE)
    k_cut = next((k for k in range(len(dates) - 1) if dates[k + 1] > cut), len(dates) - 1)
    print(f"   TRAIN {dates[1]}…{dates[k_cut]} ({k_cut} d)  ·  "
          f"TEST {dates[k_cut + 1]}…{dates[-1]} ({len(dates) - 1 - k_cut} d)")
    print(f"{'half':>7}{'size':>22}{'gas':>9}{'depth':>10}{'c* (h60)':>12}")
    print("─" * 100)
    g60, chg60, tch60, _ = built["h60"]
    split_out: Dict[str, object] = {}
    for hname, sl in (("TRAIN", slice(0, k_cut)), ("TEST", slice(k_cut, None))):
        base_h = mh._calmar(ast.aum_net(eq_gross[sl], eq_chg[sl], eq_tch[sl], aum=1e5,
                                        c_var_bps=0.0, gas_per_leg=ast.GAS_MODEL_CONSTANT,
                                        depth=1e8))
        for label, a in ast.ANCHOR_SIZES:
            for _gl, gas in GAS_ANCHORS:
                for depth in (1e8, 1e9):
                    x = affordable_cvar(g60[sl], chg60[sl], tch60[sl], base_h,
                                        aum=a, gas_per_leg=gas, depth=depth)
                    print(f"{hname:>7}{label:>22}{gas:>9.3f}{ast._fmt_usd(depth):>10}"
                          f"{_fmt_c(x):>12}")
                    split_out[f"{hname}|{label}|{gas:g}|{depth:g}"] = x.c_star
    out["split"] = split_out

    print("\n" + "=" * 100)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 100)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    import edge_gross_to_net_toll as gtn

    dates, book_rets = gtn.load_real_panel()
    run(dates, book_rets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
