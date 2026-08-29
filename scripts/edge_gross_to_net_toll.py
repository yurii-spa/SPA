#!/usr/bin/env python3
"""
scripts/edge_gross_to_net_toll.py — registry idea GTN (Gross-to-Net Toll)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

The working name GTN is used inside the code. The registry NUMBER is claimed at DELIVERY,
never at writing time (registry rule at the top of docs/DYNAMIC_LEVERAGE_GUARDIAN.md).


THE QUESTION NOBODY IN THIS REGISTRY HAS ASKED
==============================================
Every idea from #10 to #82 charges the toll the same way:

    tau_t = sum_b |w_t(b) - w_{t-1}(b)|            net_t = gross_t - tau_t * c / 1e4

That formula prices a BOOK WEIGHT as if it were a tradeable instrument. It is not. A book is
a bundle of LEGS, and two books can hold the SAME leg:

    susde_dn        = sUSDe spot 1.0  +  short ETH perp 1.0
    susde_spot      = sUSDe spot 1.0
    lrt_neutral     = eETH 1.0        +  short ETH perp 1.0
    eth_directional = eETH 1.0
    leverage_loop     = wstETH 2.0  +  ETH debt 1.0
    levered_restaking = wstETH 3.0  +  ETH debt 2.0

Rotating a dollar from susde_spot into susde_dn does NOT sell any sUSDe: the sUSDe leg is
already there, and the only trade is the perp hedge. Today's formula charges that dollar
TWICE — once for leaving susde_spot, once for entering susde_dn — and the registry's whole
#79..#82 family was judged on it. #81 measured the h60 break-even at 108 bps against the
standing 96 bps convention: a 12 % gap. If leg-level netting removes more than 12 % of the
toll, a family the registry has written off as "not worth it at today's price" is in fact
worth it, and that is a decision the project has already made in the wrong direction.

But the correction has TWO signs, and honesty requires both:

  (a) OVERCHARGE — rotations between overlapping books pay for trades nobody makes;
  (b) UNDERCHARGE — a levered book moves MORE notional than its weight. One dollar into
      pendle_pt_levered moves $3 of PT and $2 of borrow: five dollars of execution for one
      dollar of weight. Today's formula charges it one.

Whether the family gets cheaper or dearer is therefore an EMPIRICAL question, not an
arithmetic one, and this harness answers it on the real panel.

MECHANISM (exact, no free parameters in the accounting itself)
--------------------------------------------------------------
Each book b carries a leg vector e_b (gross notional per $1 of book weight), read off the
roster's own code. Portfolio leg exposure and the toll it implies:

    E_t(l)   = sum_b w_t(b) * e_b(l)
    tau_leg  = sum_l |E_t(l) - E_{t-1}(l)|

Two accountings, reported separately because they answer different questions:

  GTN-A  NETTING ONLY (leverage-blind): e_b normalised so sum_l |e_b(l)| = 1. Then
         tau_leg <= tau_book ALWAYS (triangle inequality), and the difference is exactly the
         double-charge of (a) with the size effect (b) held out. This is the isolated
         measurement of "how much of the toll do we pay to ourselves".
  GTN-B  FULL LEG ACCOUNTING (leverage-aware): raw notional. Both signs at once. This is
         what an execution desk would actually be invoiced.

The realisable fraction phi in [0,1] interpolates GTN-A against today's convention:

    tau(phi) = (1 - phi) * tau_book + phi * tau_leg

phi is NOT fitted and is not a free parameter to be optimised: it is the honest statement
that perfect netting needs one venue, one moment and one custodian, and we do not have all
three. Every phi is printed; the reader picks the row their execution deserves. The number
that decides the idea is phi*, the netting fraction at which an arm's break-even reaches the
96 bps convention.

WHY THIS IS NOT #49 RDT, #50 NTB, #47 PDD, #81 CSSR OR #82 CIT
  #49/#50/#47  changed WHEN or HOW MUCH the arm trades. The price of a trade was never
               questioned; tau was always sum_b |dw_b|.
  #81 CSSR     swept the cost c over a grid. Sweeping the PRICE of a unit of turnover does
               not fix a wrong COUNT of units, and the count is what is wrong here.
  #82 CIT      put the toll inside the objective. It internalised the SAME mis-counted toll.
  GTN          leaves every arm, every weight and every trade EXACTLY as published and
               changes only the invoice. No arm's decisions move by a single cell — asserted
               by a test that compares weight histories under both accountings.

THE CONTROLS THAT DECIDE THE VERDICT
  1. DISJOINT (positive control, exact): give every book its own private leg. Then leg
     accounting IS book accounting and every cell must reproduce #80/#81 bit-for-bit. If it
     does not, the instrument is broken and no other number in the file may be read.
  2. RANDOM-COMPOSITION band: leg vectors redrawn at random with the same per-book leg COUNT
     from the same leg pool, seeded. If the real roster's saving sits inside that band, the
     saving is a property of "books have 1-2 legs each", not of OUR books, and must be
     written that way.
  3. RELABEL band: the TRUE leg vectors, permuted across books. Same multiset of
     compositions, wrong ownership. This asks whether the specific pairing (susde_dn WITH
     susde_spot, the two wstETH loops TOGETHER) is what does the work.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]. The panel's books are themselves backtests over real deep-history
    feeds, so this measures an accounting rule on a real return SHAPE, not realised P&L;
  * ECONOMIC overlap is not TRADEABLE overlap. sUSDe spot held by two books is one token and
    nets for real; PT-sUSDe and sUSDe are DIFFERENT tokens and are given different legs here
    precisely so they cannot net. Where the two loops share wstETH on the same lending market
    the netting is real but needs one venue and one instant — that is what phi < 1 is for;
  * the linear one-way cost model is #10's convention and stays OPTIMISTIC: real slippage is
    convex and worst in a crisis. Under GTN-B a levered book's leg flow is larger, so its
    convexity error is larger too, and the printed GTN-B numbers are therefore the FRIENDLY
    end of the range;
  * leg vectors are DERIVED FROM THE ROSTER'S CODE (leverage defaults are read out of
    roster.py at runtime and asserted against this file's table — a drift between them
    FAILS, it does not warn). What is a judgement and not a derivation is which legs count as
    the SAME instrument; that judgement is written out leg by leg below and can be overruled
    by editing one table;
  * no parameter is chosen on TEST: the phi ladder, the cost grid, the seeds and the
    canonical 2025-06-30 split were fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import os
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_cost_signal_separation as css  # noqa: E402  (#80 harness, reused verbatim)
import edge_mhfc_backtest as mh  # noqa: E402  (#79 harness, reused verbatim)
import edge_real_panel_ensemble as RPE  # noqa: E402  (real-panel loader, reused verbatim)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: Panel location. Overridable because the panel is NOT git-tracked: a worktree has an empty
#: data/ and must point at the prod tree's copy (read-only). #70/#79/#80 published fixture
#: numbers under a panel headline exactly because their loader fell back silently.
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

#: Inherited from #80 unchanged.
COST_GRID = css.COST_GRID
CONVENTION_COST = css.CONVENTION_COST
ARMS = css.ARMS
SPLIT_DATE = mh.SPLIT_DATE  # "2025-06-30", registry-canonical

#: Fixed before any number was read.
PHI_GRID: Tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
#: The strongest objection to GTN-B, priced instead of argued: a BORROW leg is not a swap.
#: Opening or repaying a debt on a lending market pays gas and a rate, not book-depth
#: slippage, so charging it the same 96 bps as a spot fill is hostile. delta is the fraction
#: of the spot toll a debt leg pays; the whole ladder is printed and nothing is fitted.
DEBT_RATE_GRID: Tuple[float, ...] = (0.0, 0.25, 1.0)
#: Which legs are borrowings (see RAW_LEGS).
DEBT_LEGS = frozenset({"stable_debt", "eth_debt"})
CONTROL_SAMPLES = 200
RANDOM_COMPOSITION_SEED = 20260828
RELABEL_SEED = 20260828 + 1


# ─────────────────────── the leg table (derived from roster.py) ───────────────────
# Gross notional per $1 of BOOK WEIGHT, leg by leg. Sources are the roster classes named in
# each comment; the leverage numbers are re-read from that source at runtime by
# roster_leverage_defaults() and a mismatch here is a hard failure, not a warning.
#
# THE ONE JUDGEMENT IN THIS FILE: which legs are the SAME instrument. Written out so it can
# be argued with:
#   * "susde"  is the sUSDe token. susde_dn and susde_spot hold the identical token, so a
#     rotation between them does not trade it. REAL netting.
#   * "eth_perp" is the short ETH perpetual. susde_dn and lrt_neutral both carry one; the
#     position is fungible on the venue. REAL netting.
#   * "eeth" is the eETH LRT token, held by lrt_neutral and eth_directional. REAL netting.
#   * "wsteth"/"eth_debt": the 2x and the 3x loop hold the same collateral and the same debt
#     on the same lending market. REAL netting, but it needs both legs moved in one moment —
#     the clearest case for phi < 1.
#   * "pt_susde" (a Pendle principal token), "yt_susde" (a yield token), "lp_eth_stable" (an
#     LP share) and "points" are DISTINCT instruments and are deliberately given private
#     legs: they are economically related to sUSDe/ETH and are STILL not fungible with it.
#     Netting them would be the exact dishonesty this idea exists to measure.
RAW_LEGS: Dict[str, Dict[str, float]] = {
    # SusdeDeltaNeutral: long sUSDe + short ETH perp, unlevered.
    "susde_dn": {"susde": 1.0, "eth_perp": 1.0},
    # SusdeSpot: unhedged sUSDe hold.
    "susde_spot": {"susde": 1.0},
    # PendleYtSusde: one YT position. yt_leverage=8 is the MARK sensitivity of the token,
    # not extra notional to execute — the desk buys one YT, not eight.
    "pendle_yt_susde": {"yt_susde": 1.0},
    # PendlePtLevered: leverage L=3 → L of PT collateral against (L-1) of stable borrow.
    "pendle_pt_levered": {"pt_susde": 3.0, "stable_debt": 2.0},
    # LrtNeutral: LRT spot + short ETH perp, unlevered.
    "lrt_neutral": {"eeth": 1.0, "eth_perp": 1.0},
    # EthDirectional: unhedged LRT.
    "eth_directional": {"eeth": 1.0},
    # LeverageLoop: wstETH at L=2 against (L-1) ETH debt.
    "leverage_loop": {"wsteth": 2.0, "eth_debt": 1.0},
    # PointsFarm: an opaque incentive position.
    "points_farm": {"points": 1.0},
    # EthStableLP: one LP share (50/50 internally, but the share is what trades).
    "lp_eth_stable": {"lp_eth_stable": 1.0},
    # LeveredRestaking: wstETH at L=3 against (L-1) ETH debt.
    "levered_restaking": {"wsteth": 3.0, "eth_debt": 2.0},
}

#: Leverage this file ASSUMES, per book. Checked against roster.py at runtime.
ASSUMED_LEVERAGE: Dict[str, float] = {
    "susde_dn": 1.0,
    "susde_spot": 1.0,
    "pendle_yt_susde": 1.0,   # yt_leverage is a mark sensitivity, not notional (see above)
    "pendle_pt_levered": 3.0,
    "lrt_neutral": 1.0,
    "eth_directional": 1.0,
    "leverage_loop": 2.0,
    "points_farm": 1.0,
    "lp_eth_stable": 1.0,
    "levered_restaking": 3.0,
}

ROSTER_SOURCE = ROOT / "spa_core" / "strategy_lab" / "aggressive_lab" / "roster.py"


def roster_leverage_defaults(source: Optional[Path] = None) -> Dict[str, float]:
    """{book id: the `leverage` default the roster class actually runs with}.

    Read out of roster.py's SOURCE rather than imported, because the default lives inside a
    method body (`self._cfg.get("leverage", 2.0)`) and is not reachable as an attribute. The
    lab's own runner calls run_backtest(feeds, start, end) with NO config, so these literals
    are what produced every point of the panel this harness reads.

    Books with no leverage default are 1.0. `yt_leverage` is deliberately NOT collected: it
    is the YT mark sensitivity, not position notional (see RAW_LEGS).
    """
    src = (source or ROSTER_SOURCE).read_text()
    # Split on class headers so a `leverage` literal can never be attributed to a neighbour
    # class — the same failure mode as mutating a test by text instead of by coordinate.
    chunks = re.split(r"^class\s+\w+\([^)]*\):", src, flags=re.M)[1:]
    out: Dict[str, float] = {}
    for chunk in chunks:
        m_id = re.search(r'^\s{4}id\s*=\s*"([^"]+)"', chunk, flags=re.M)
        if not m_id:
            continue
        levs = re.findall(r'_cfg\.get\(\s*"leverage"\s*,\s*([0-9.]+)\s*\)', chunk)
        if not levs:
            out[m_id.group(1)] = 1.0
            continue
        uniq = {float(x) for x in levs}
        if len(uniq) != 1:
            raise RuntimeError(
                f"{m_id.group(1)}: roster.py carries {sorted(uniq)} as the leverage default "
                f"in one class — refusing to guess which one the panel ran"
            )
        out[m_id.group(1)] = uniq.pop()
    return out


def assert_leg_table_matches_roster(source: Optional[Path] = None) -> Dict[str, float]:
    """fail-CLOSED drift guard: this file's leverage table vs roster.py's live defaults.

    A leg table that has silently drifted from the code it claims to describe is worse than
    no leg table at all: it would publish an invoice for positions nobody holds.
    """
    live = roster_leverage_defaults(source)
    missing = sorted(set(ASSUMED_LEVERAGE) - set(live))
    if missing:
        raise RuntimeError(f"books in this table but not in roster.py: {missing}")
    bad = {b: (ASSUMED_LEVERAGE[b], live[b]) for b in ASSUMED_LEVERAGE if live[b] != ASSUMED_LEVERAGE[b]}
    if bad:
        raise RuntimeError(
            "leg table has drifted from roster.py (book: assumed vs live): "
            + ", ".join(f"{b}: {a} vs {c}" for b, (a, c) in sorted(bad.items()))
        )
    # the table must also SPEND the leverage it claims: a levered book's gross notional is
    # L (collateral) + (L-1) (debt) = 2L-1 per $1 of weight.
    for book, lev in ASSUMED_LEVERAGE.items():
        if lev > 1.0:
            want = 2.0 * lev - 1.0
            got = sum(abs(v) for v in RAW_LEGS[book].values())
            if abs(got - want) > 1e-9:
                raise RuntimeError(
                    f"{book}: leverage {lev} implies gross notional {want}, table says {got}"
                )
    return live


# ─────────────────────────── leg algebra ─────────────────────────────────────────
LegTable = Dict[str, Dict[str, float]]


def normalise_legs(legs: LegTable) -> LegTable:
    """Scale each book's leg vector to gross notional 1.0 (the GTN-A, leverage-blind view)."""
    out: LegTable = {}
    for book, vec in legs.items():
        gross = sum(abs(v) for v in vec.values())
        if gross <= 0.0:
            raise ValueError(f"{book}: empty leg vector — refusing to price a book that holds nothing")
        out[book] = {leg: v / gross for leg, v in vec.items()}
    return out


def legs_at_debt_rate(legs: LegTable, delta: float) -> LegTable:
    """Scale every DEBT leg by delta (0 = borrowings execute free, 1 = they cost like a swap).

    A leg scaled to exactly 0 is DROPPED rather than kept at zero, so it can never take part
    in netting: a debt that costs nothing to move must not silently cancel a spot leg.
    """
    out: LegTable = {}
    for book, vec in legs.items():
        row = {}
        for leg, v in vec.items():
            unit = v * delta if leg in DEBT_LEGS else v
            if unit != 0.0:
                row[leg] = unit
        if not row:
            raise ValueError(f"{book}: every leg priced at zero — refusing to invoice nothing")
        out[book] = row
    return out


def per_book_leg_flow(hist: css.WeightHistory, legs: LegTable) -> Dict[str, float]:
    """Total leg notional each book's own weight changes move (attribution, not accounting).

    Sums |dw_b| * gross(e_b) per book: it says WHO generates the invoice. It deliberately
    ignores netting (netting is a property of a PAIR, not of a book), so the shares add up to
    the un-netted total and must not be read as the netted one.
    """
    out: Dict[str, float] = {}
    prev: Optional[Dict[str, float]] = None
    for w in hist:
        if prev is not None:
            for b in set(w) | set(prev):
                d = abs(w.get(b, 0.0) - prev.get(b, 0.0))
                if d:
                    out[b] = out.get(b, 0.0) + d * sum(abs(v) for v in legs.get(b, {}).values())
        prev = w
    return out


def disjoint_legs(book_ids: Sequence[str]) -> LegTable:
    """Every book its own private leg — the accounting the whole registry has used so far."""
    return {b: {f"__own__{b}": 1.0} for b in book_ids}


def leg_exposure(w: Dict[str, float], legs: LegTable) -> Dict[str, float]:
    exp: Dict[str, float] = {}
    for book, weight in w.items():
        if weight == 0.0:
            continue
        for leg, unit in legs.get(book, {}).items():
            exp[leg] = exp.get(leg, 0.0) + weight * unit
    return exp


def leg_turnover(hist: css.WeightHistory, legs: LegTable) -> List[float]:
    """Per-day tradeable leg flow: sum_l |E_t(l) - E_{t-1}(l)|.

    Day 0 is 0.0 to match css._gross_and_turnover, which does not charge the initial build.
    """
    turns: List[float] = []
    prev: Optional[Dict[str, float]] = None
    for w in hist:
        cur = leg_exposure(w, legs)
        if prev is None:
            turns.append(0.0)
        else:
            keys = set(cur) | set(prev)
            turns.append(sum(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in keys))
        prev = cur
    return turns


def blend(tau_book: Sequence[float], tau_leg: Sequence[float], phi: float) -> List[float]:
    """(1-phi)*book + phi*leg. phi=0 is today's convention; phi=1 is perfect netting."""
    return [(1.0 - phi) * a + phi * b for a, b in zip(tau_book, tau_leg)]


# ─────────────────────────── control leg tables ──────────────────────────────────
def random_composition_legs(true_legs: LegTable, seed: int) -> LegTable:
    """Same per-book leg COUNT, legs redrawn from the same pool. Composition destroyed.

    Answers: is the saving a property of OUR roster, or merely of "books hold 1-2 legs"?
    """
    rng = random.Random(seed)
    pool = sorted({leg for vec in true_legs.values() for leg in vec})
    out: LegTable = {}
    for book in sorted(true_legs):
        vec = true_legs[book]
        k = min(len(vec), len(pool))
        picked = rng.sample(pool, k)
        sizes = sorted(abs(v) for v in vec.values())
        out[book] = {leg: size for leg, size in zip(picked, sizes)}
    return out


def relabel_legs(true_legs: LegTable, seed: int) -> LegTable:
    """The TRUE leg vectors, permuted across books. Same compositions, wrong owners."""
    rng = random.Random(seed)
    books = sorted(true_legs)
    perm = books[:]
    rng.shuffle(perm)
    return {b: dict(true_legs[src]) for b, src in zip(books, perm)}


def is_identity_relabel(true_legs: LegTable, permuted: LegTable) -> bool:
    return all(permuted[b] == true_legs[b] for b in true_legs)


# ─────────────────────────── datasets ────────────────────────────────────────────
BookRets = Dict[str, List[float]]


def _align(by_date: Dict[str, Dict[datetime.date, float]]) -> Tuple[List[datetime.date], BookRets]:
    common = sorted(set.intersection(*[set(d.keys()) for d in by_date.values()]))
    return common, {sid: [by_date[sid][d] for d in common] for sid in sorted(by_date)}


def load_fixture_panel() -> Tuple[List[datetime.date], BookRets]:
    """#80's dataset through #79's loader unchanged (the ANCHOR dataset)."""
    raw = mh._load_fixture()
    by_date: Dict[str, Dict[datetime.date, float]] = {}
    for sid, series in raw.items():
        dts, rets = mh._daily_returns(series)
        by_date[sid] = dict(zip(dts, rets))
    return _align(by_date)


def load_real_panel(panel_dir: Path = PANEL_DIR) -> Tuple[List[datetime.date], BookRets]:
    """The real aggressive-lab panel through RPE's fail-CLOSED loader unchanged.

    REFUSES when the panel is absent instead of falling back to the fixture — the silent
    fallback is how #70/#79/#80 published fixture numbers under a panel headline.
    """
    if not panel_dir.exists():
        raise FileNotFoundError(
            f"panel not found at {panel_dir} — refusing to substitute the fixture silently; "
            f"set SPA_PANEL_DIR to the prod tree's data/aggressive_lab"
        )
    panel = RPE.load_panel(panel_dir)
    axis = RPE.common_axis(panel)
    if len(axis) < 120:
        raise RuntimeError(f"common axis is {len(axis)} days — refusing to publish on it")
    by_date = {
        book: {datetime.date.fromisoformat(d): panel[book][d] for d in axis}
        for book in sorted(panel)
    }
    return _align(by_date)


# ─────────────────────────── per-arm assembly ────────────────────────────────────
class Arm:
    """One arm's weight history plus every toll it can be charged. Weights NEVER vary."""

    def __init__(self, book_rets: BookRets, dates: Sequence[datetime.date], mode: str) -> None:
        self.mode = mode
        self.hist = css._weight_history(book_rets, dates, mode)
        self.gross, self.tau_book = css._gross_and_turnover(self.hist, book_rets)

    def tau(self, legs: LegTable, phi: float) -> List[float]:
        return blend(self.tau_book, leg_turnover(self.hist, legs), phi)


def kappa(tau_book: Sequence[float], tau_other: Sequence[float]) -> float:
    """Toll multiplier: total charged units under the other accounting / under today's."""
    base = sum(tau_book)
    return (sum(tau_other) / base) if base else 1.0


def breakeven_in_phi(
    arm: Arm,
    legs: LegTable,
    base_calmar: float,
    target_cost: float = CONVENTION_COST,
) -> Optional[float]:
    """Smallest phi at which the arm still beats equal-weight AT target_cost, or None.

    Bisection is legitimate here and the reason is worth writing down: tau(phi) is linear and
    decreasing in phi under GTN-A, so net return at a fixed cost is monotone increasing in
    phi and the crossing is unique. Under an accounting where tau_leg > tau_book the
    direction reverses; the caller must not read a phi* from GTN-B, and main() does not.
    """
    def wins(phi: float) -> bool:
        net = css._net(arm.gross, arm.tau(legs, phi), target_cost)
        if css._degenerate(net):
            return False
        return css._dcalmar(net, base_calmar) > 0.0

    if wins(0.0):
        return 0.0
    if not wins(1.0):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if wins(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def _split_index(dates: Sequence[datetime.date], boundary: str) -> int:
    """Index into the RETURN axis (dates[1:]) of the first day after the split boundary."""
    b = datetime.date.fromisoformat(boundary)
    ret_dates = list(dates)[1:]
    for i, d in enumerate(ret_dates):
        if d > b:
            return i
    return len(ret_dates)


# ─────────────────────────── one dataset, whole report ───────────────────────────
def run_dataset(
    title: str,
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    *,
    legs_raw: Optional[LegTable] = None,
    controls: bool = True,
) -> Dict[str, dict]:
    """Full GTN report for one dataset. Returns the machine-readable summary."""
    book_ids = sorted(book_rets)
    n_days = len(dates) - 1
    print("\n" + "=" * 78)
    print(f"DATASET: {title}")
    print(f"  books {len(book_ids)}: {', '.join(book_ids)}")
    print(f"  aligned {dates[0]} … {dates[-1]}  ({len(dates)} days)")
    print("=" * 78)

    # every book must have a leg vector, or the invoice is a guess
    if legs_raw is None:
        legs_raw = disjoint_legs(book_ids)
    unknown = sorted(set(book_ids) - set(legs_raw))
    if unknown:
        raise RuntimeError(
            f"no leg vector for {unknown} — refusing to price a book whose composition is unknown"
        )
    legs_raw = {b: legs_raw[b] for b in book_ids}
    legs_a = normalise_legs(legs_raw)
    legs_disjoint = disjoint_legs(book_ids)

    eq = Arm(book_rets, dates, "eq")
    eq_calmar = mh._calmar(css._net(eq.gross, eq.tau_book, 0.0))
    eq_apy = mh._apy(css._net(eq.gross, eq.tau_book, 0.0))
    print(
        f"\nBaseline equal-weight: APY={eq_apy * 100:.2f}%  Calmar={eq_calmar:.2f}  "
        f"turnover/yr={css._turnover_per_year(eq.tau_book, n_days):.2f}  (cost-invariant ✓)"
    )

    arms = {mode: Arm(book_rets, dates, mode) for mode, _ in ARMS}

    # ── 0. POSITIVE CONTROL: disjoint legs must reproduce book accounting exactly ──
    print("\n" + "─" * 78)
    print("0. POSITIVE CONTROL — private leg per book ⇒ leg accounting IS book accounting")
    for mode, label in ARMS:
        arm = arms[mode]
        tau_d = leg_turnover(arm.hist, legs_disjoint)
        worst = max((abs(a - b) for a, b in zip(arm.tau_book, tau_d)), default=0.0)
        if worst > 1e-12:
            raise RuntimeError(f"{mode}: disjoint legs disagree with book turnover by {worst}")
        print(f"  {label:<20} max cell difference {worst:.1e}  ✓")
    print("  (anchor holds — every number below is the same instrument as #80/#81)")

    # ── 1. HOW MUCH OF THE TOLL DO WE PAY TO OURSELVES ────────────────────────────
    print("\n" + "─" * 78)
    print("1. TOLL MULTIPLIER κ — charged units relative to today's convention  [bt]")
    print(f"{'arm':<22} {'TO/yr book':>11} {'TO/yr GTN-A':>12} {'κ_A':>7} "
          f"{'TO/yr GTN-B':>12} {'κ_B':>7}")
    print("─" * 78)
    summary: Dict[str, dict] = {}
    for mode, label in ARMS:
        arm = arms[mode]
        tau_a = leg_turnover(arm.hist, legs_a)
        tau_b = leg_turnover(arm.hist, legs_raw)
        k_a, k_b = kappa(arm.tau_book, tau_a), kappa(arm.tau_book, tau_b)
        print(
            f"  {label:<20} {css._turnover_per_year(arm.tau_book, n_days):>11.2f} "
            f"{css._turnover_per_year(tau_a, n_days):>12.2f} {k_a:>7.3f} "
            f"{css._turnover_per_year(tau_b, n_days):>12.2f} {k_b:>7.3f}"
        )
        summary[mode] = {"kappa_a": k_a, "kappa_b": k_b}
    print("  κ<1 = we have been overcharging ourselves; κ>1 = undercharging (leverage).")

    # ── 2. THE LADDER: does the family cross the 96 bps convention ────────────────
    print("\n" + "─" * 78)
    print(f"2. GTN-A LADDER — netAPY and dCalmar at c={CONVENTION_COST} bps, by netting fraction φ")
    print(f"{'arm':<22}" + "".join(f"{'φ=' + f'{p:.2f}':>14}" for p in PHI_GRID))
    print("─" * 78)
    for mode, label in ARMS:
        arm = arms[mode]
        cells = []
        for phi in PHI_GRID:
            net = css._net(arm.gross, arm.tau(legs_a, phi), CONVENTION_COST)
            cells.append(f"{mh._apy(net) * 100:>7.2f}%{css._dcalmar(net, eq_calmar):>+6.2f}")
        print(f"  {label:<20}" + "".join(f"{c:>14}" for c in cells))
    print(f"  {'equal-weight':<20}" + "".join(f"{eq_apy * 100:>7.2f}%{0.0:>+6.2f}" for _ in PHI_GRID))
    print("  (each cell: netAPY then dCalmar vs equal-weight, same day, same weights)")

    print("\n  BREAK-EVEN COST by φ (bps at which dCalmar crosses zero):")
    print(f"  {'arm':<20}" + "".join(f"{'φ=' + f'{p:.2f}':>14}" for p in PHI_GRID))
    for mode, label in ARMS:
        arm = arms[mode]
        cells = []
        for phi in PHI_GRID:
            verdict, _ = css._breakeven_cost(arm.gross, arm.tau(legs_a, phi), eq_calmar)
            cells.append(verdict)
        print(f"  {label:<20}" + "".join(f"{c:>14}" for c in cells))
        summary[mode]["breakeven_by_phi"] = [
            css._breakeven_cost(arm.gross, arm.tau(legs_a, p), eq_calmar)[0] for p in PHI_GRID
        ]

    print(f"\n  φ* — netting fraction needed to clear c={CONVENTION_COST} bps "
          f"(None = never clears, even at perfect netting):")
    for mode, label in ARMS:
        phi_star = breakeven_in_phi(arms[mode], legs_a, eq_calmar)
        summary[mode]["phi_star"] = phi_star
        shown = "never" if phi_star is None else (
            "already (φ=0)" if phi_star <= 0.0 else f"{phi_star:.3f}"
        )
        print(f"    {label:<20} {shown}")

    # ── 3. GTN-B: the invoice an execution desk would actually send ───────────────
    print("\n" + "─" * 78)
    print(f"3. GTN-B FULL LEG ACCOUNTING (leverage-aware) at c={CONVENTION_COST} bps")
    print(f"{'arm':<22} {'netAPY book':>12} {'netAPY GTN-B':>13} {'dCal book':>10} "
          f"{'dCal GTN-B':>11} {'break-even B':>14}")
    print("─" * 78)
    for mode, label in ARMS:
        arm = arms[mode]
        tau_b = leg_turnover(arm.hist, legs_raw)
        n0 = css._net(arm.gross, arm.tau_book, CONVENTION_COST)
        nb = css._net(arm.gross, tau_b, CONVENTION_COST)
        verdict, _ = css._breakeven_cost(arm.gross, tau_b, eq_calmar)
        print(
            f"  {label:<20} {mh._apy(n0) * 100:>11.2f}% {mh._apy(nb) * 100:>12.2f}% "
            f"{css._dcalmar(n0, eq_calmar):>+10.2f} {css._dcalmar(nb, eq_calmar):>+11.2f} "
            f"{verdict:>14}"
        )
        summary[mode]["breakeven_b"] = verdict

    print("\n  3b. DEBT-LEG SENSITIVITY — δ = fraction of the spot toll a BORROW leg pays.")
    print("      δ=0 is the friendliest defensible reading (a borrow is gas + a rate, not a")
    print("      fill); δ=1 is GTN-B above. The verdict must survive δ=0 to be worth writing.")
    print(f"  {'arm':<20}" + "".join(f"{'δ=' + f'{d:.2f}':>26}" for d in DEBT_RATE_GRID))
    for mode, label in ARMS:
        arm = arms[mode]
        cells = []
        for delta in DEBT_RATE_GRID:
            tab = legs_at_debt_rate(legs_raw, delta)
            tau_d = leg_turnover(arm.hist, tab)
            net = css._net(arm.gross, tau_d, CONVENTION_COST)
            be, _ = css._breakeven_cost(arm.gross, tau_d, eq_calmar)
            be_short = "none" if be.startswith("none") else be.replace(" bps", "")
            cells.append(
                f"κ={kappa(arm.tau_book, tau_d):.2f} {mh._apy(net) * 100:>7.2f}% be={be_short:>4}"
            )
        print(f"  {label:<20}" + "".join(f"{c:>26}" for c in cells))
        summary[mode]["debt_rate_kappa"] = [
            kappa(arm.tau_book, leg_turnover(arm.hist, legs_at_debt_rate(legs_raw, d)))
            for d in DEBT_RATE_GRID
        ]

    print("\n  3c. WHO GENERATES THE INVOICE — share of un-netted leg flow, by book (GTN-B):")
    for mode, label in ARMS:
        flow = per_book_leg_flow(arms[mode].hist, legs_raw)
        total = sum(flow.values()) or 1.0
        top = sorted(flow.items(), key=lambda kv: -kv[1])[:4]
        print(f"  {label:<20}" + "  ".join(f"{b}={v / total * 100:.0f}%" for b, v in top))

    # ── 4. CONTROLS ───────────────────────────────────────────────────────────────
    if controls:
        print("\n" + "─" * 78)
        print(f"4. CONTROLS — is the saving OUR roster's, or any roster's?  ({CONTROL_SAMPLES} samples)")
        print("   RANDOM-COMPOSITION: same leg counts, legs redrawn from the same pool.")
        print("   RELABEL: the true leg vectors, permuted across books.")
        print(f"{'arm':<20} {'real κ_A':>9} {'random band (min/med/max)':>32} "
              f"{'≤real':>8} {'p':>7}")
        print("─" * 78)
        for mode, label in ARMS:
            arm = arms[mode]
            real_k = summary[mode]["kappa_a"]
            band: List[float] = []
            for s in range(CONTROL_SAMPLES):
                ctrl = normalise_legs(random_composition_legs(legs_raw, RANDOM_COMPOSITION_SEED + s))
                band.append(kappa(arm.tau_book, leg_turnover(arm.hist, ctrl)))
            lo, med, hi = css._band(band)
            beat = sum(1 for k in band if k <= real_k)  # "at least as much saving as ours"
            p = (beat + 1) / (len(band) + 1)
            print(f"  {label:<18} {real_k:>9.3f}   {lo:>8.3f} /{med:>8.3f} /{hi:>8.3f}   "
                  f"{beat:>4}/{len(band):<4} {p:>6.3f}")
            summary[mode]["random_band"] = (lo, med, hi)
            summary[mode]["p_random"] = p

        print(f"\n{'arm':<20} {'real κ_A':>9} {'relabel band (min/med/max)':>32} "
              f"{'≤real':>8} {'p':>7}")
        print("─" * 78)
        for mode, label in ARMS:
            arm = arms[mode]
            real_k = summary[mode]["kappa_a"]
            band = []
            skipped = 0
            for s in range(CONTROL_SAMPLES):
                perm = relabel_legs(legs_raw, RELABEL_SEED + s)
                if is_identity_relabel(legs_raw, perm):
                    skipped += 1
                    continue  # the identity IS the real arm; counting it would flatter us
                band.append(kappa(arm.tau_book, leg_turnover(arm.hist, normalise_legs(perm))))
            lo, med, hi = css._band(band)
            beat = sum(1 for k in band if k <= real_k)
            p = (beat + 1) / (len(band) + 1)
            print(f"  {label:<18} {real_k:>9.3f}   {lo:>8.3f} /{med:>8.3f} /{hi:>8.3f}   "
                  f"{beat:>4}/{len(band):<4} {p:>6.3f}"
                  + (f"   (identity dropped ×{skipped})" if skipped else ""))
            summary[mode]["relabel_band"] = (lo, med, hi)
            summary[mode]["p_relabel"] = p
        print("   p = fraction of control tables that save AT LEAST as much as the true one.")
        print("   Small p ⇒ the saving is a property of OUR composition, not of any composition.")

    # ── 5. TRAIN / TEST ───────────────────────────────────────────────────────────
    cut = _split_index(dates, SPLIT_DATE)
    if 30 < cut < (len(dates) - 31):
        print("\n" + "─" * 78)
        print(f"5. TRAIN / TEST (split {SPLIT_DATE}) — κ_A and dCalmar(φ=1) at c={CONVENTION_COST}")
        print(f"{'arm':<22} {'κ_A train':>10} {'κ_A test':>10} {'dCal train':>11} {'dCal test':>10}")
        print("─" * 78)
        for mode, label in ARMS:
            arm = arms[mode]
            tau_a = leg_turnover(arm.hist, legs_a)
            halves = []
            for sl in (slice(0, cut), slice(cut, None)):
                g, tb, ta = arm.gross[sl], arm.tau_book[sl], tau_a[sl]
                base = mh._calmar(css._net(eq.gross[sl], eq.tau_book[sl], 0.0))
                halves.append((
                    kappa(tb, ta),
                    css._dcalmar(css._net(g, ta, CONVENTION_COST), base),
                ))
            (k_tr, d_tr), (k_te, d_te) = halves
            print(f"  {label:<20} {k_tr:>10.3f} {k_te:>10.3f} {d_tr:>+11.2f} {d_te:>+10.2f}")
            summary[mode]["kappa_train_test"] = (k_tr, k_te)
    else:
        print(f"\n5. TRAIN / TEST skipped — split {SPLIT_DATE} does not cut this axis usefully.")

    return summary


# ─────────────────────────── main ────────────────────────────────────────────────
def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    want_fixture = "--fixture" in argv or "--both" in argv
    want_real = "--real" in argv or "--both" in argv or not (want_fixture)

    print("=" * 78)
    print("Idea GTN: Gross-to-Net Toll — the invoice, not the trade  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print("Question: the registry prices BOOK WEIGHTS. Books share LEGS. What does the")
    print("          toll look like when it is charged on what actually trades?")
    print("=" * 78)

    live = assert_leg_table_matches_roster()
    print("\nLeverage defaults re-read from roster.py (drift ⇒ hard failure):")
    for book in sorted(ASSUMED_LEVERAGE):
        legs = RAW_LEGS[book]
        print(f"  {book:<20} L={live.get(book, 1.0):<4} gross={sum(abs(v) for v in legs.values()):<5} "
              f"legs={', '.join(f'{k}×{v:g}' for k, v in sorted(legs.items()))}")

    if want_fixture:
        dates, book_rets = load_fixture_panel()
        # The 5-book fixture has no roster identity; every book gets a private leg, so this
        # run exists ONLY to prove the harness reproduces #80 on #80's own dataset.
        run_dataset("FIXTURE (#80's dataset) — disjoint legs, anchor only", dates, book_rets,
                    legs_raw=None, controls=False)

    if want_real:
        dates, book_rets = load_real_panel()
        missing = sorted(set(book_rets) - set(RAW_LEGS))
        if missing:
            raise RuntimeError(f"panel carries books with no leg vector: {missing}")
        run_dataset("REAL aggressive-lab panel", dates, book_rets, legs_raw=RAW_LEGS)

    print("\n" + "=" * 78)
    print("Advisory only. No capital moved, no module built, no agent deployed.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
