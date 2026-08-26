#!/usr/bin/env python3
"""
scripts/edge_cost_signal_separation.py — Idea #80 CSS: Cost–Signal Separation

Advisory-only backtest on the code-generated fixture.
IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0

THE QUESTION NOBODY ASKED
-------------------------
The "law of reactivity" (#32/#33: corr(turnover, dCalmar) = -0.78, six confirmations
through #79) is the single most-repeated negative result in this registry.  Every one
of those measurements was taken at ONE cost: 96 bps, the break-even that #10 derived
for a completely different overlay (rare-switching DDO #9, 8 switches / 2 years).

So the law has two readings that nobody has separated:

  (A) FISCAL   — reactive rules trade a lot, trading costs 96 bps, the toll eats them.
                 => the family is fixable by execution engineering (cheaper venue,
                    batching, L2, netting).  Six negatives would be a COST finding.

  (B) STRUCTURAL — the reactive SIGNAL destroys information; it would lose at zero cost.
                 => no execution improvement can ever rescue it, and the registry should
                    stop paying for cheaper execution as a way out.

These prescribe opposite engineering.  #80 separates them.

DESIGN
------
1. COST SWEEP.  Equal-weight has zero turnover, so its net series is cost-INVARIANT and
   makes a clean fixed baseline.  Gross returns and turnover are computed ONCE per arm;
   net_r(c) = gross_r - turnover * c/1e4 is then exact at any cost, no re-run.
   Break-even c* = the cost at which dCalmar crosses zero.  If dCalmar(c=0) is already
   negative, c* does not exist and reading (B) is proven for that arm.

2. DECOMPOSITION.  dCalmar(96) = dCalmar(0)          <- pure SIGNAL component
                              + [dCalmar(96)-dCalmar(0)]  <- pure COST component.

3. TWO FREE CONTROLS, BOTH EXACTLY TURNOVER-MATCHED (registry-standard devices).
   A negative dCalmar at zero cost still is not proof the signal is anti-informative:
   it could be an artifact of holding a concentrated subset at all.  Both controls hold
   the trading SCHEDULE fixed and destroy exactly one thing:

   - RELABEL  — one fixed permutation of book identity applied to every daily weight
                vector.  Destroys WHICH book is flagged; preserves WHEN and turnover
                EXACTLY (the per-day weight multiset is untouched).  With n books this
                is enumerated EXHAUSTIVELY (n! <= 5040), so the rank test is exact and
                seed-free.
   - ROTATE   — circular shift of the weight sequence by k days.  Destroys WHEN the
                flags fire; preserves the schedule's own structure and turnover (up to
                the single wrap day).

   If the real arm sits INSIDE the control band, the signal carries no information and
   the loss is the schedule's.  If the real arm sits BELOW the band, the signal is
   actively ANTI-informative -- worse than noise at the same turnover.

DISTINCTNESS FROM PRIOR IDEAS
-----------------------------
- #10 TCB  — swept cost for ONE POSITIVE overlay (DDO #9) to check it survived costs.
             #80 sweeps cost across the NEGATIVE reactive family to ask what the six
             negatives are actually made of.  Opposite direction, opposite purpose.
- #32/#33  — established corr(turnover, dCalmar) = -0.78 at a single fixed cost; neither
             asked whether the correlation survives cost -> 0.
- #50 NTB  — random-day controls at matched TRADE COUNT under one fixed cost; concluded
             "frequency works, the timing rule does not".  #80 holds the schedule fixed
             and varies the COST axis instead, and adds the identity (relabel) control
             that #50 did not run.
- #60 DHD  — varied decision frequency (a strategy knob).  #80 varies the toll (an
             environment knob) with strategies held fixed.

LOOK-AHEAD GUARD
----------------
Signals and weights come from edge_mhfc_backtest (idea #79) UNCHANGED, so its published
look-ahead guarantees carry over verbatim:
  signal at i uses rets[i-h:i]; weight at i applied to rets[i].
Cost is a pure post-hoc drag on the realised series and cannot feed back into any signal
(that failure mode is exactly the one #10 documented as its methodological finding).

HONESTY CONSTRAINTS
-------------------
- Code-generated fixture ONLY.  The real panel (data/aggressive_lab/) is not available
  in this session -- the same limitation #79 declared.  All numbers labeled [bt], L0.
- The fixture's equal-weight baseline has NEGATIVE APY, so every Calmar here is negative
  and the ratio is noisy.  netAPY is therefore printed alongside as a monotone,
  sign-unambiguous second axis; conclusions are only claimed where both axes agree.
- Capital is not moved.  No module is built and no agent is deployed by this script.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import itertools
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_mhfc_backtest as mh  # noqa: E402  (idea #79 harness, reused verbatim)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

# Cost grid in bps of one-way turnover.  96 is the registry's standing convention
# (break-even of #10); 0 is the structural limit; 384 is 4x as a stress upper bound.
COST_GRID = [0, 6, 12, 24, 48, 96, 192, 384]
CONVENTION_COST = 96

ARMS = [
    ("h5", "Single h=5d"),
    ("h20", "Single h=20d"),
    ("h60", "Single h=60d"),
    ("mhfc", "MHFC adaptive"),
]

MAX_EXHAUSTIVE_PERMS = 5040  # 7!; above this we would have to sample instead
ROTATION_STEP = 7            # circular shifts every 7 days across the whole series


# ── weight histories ─────────────────────────────────────────────────────────────
WeightHistory = List[Dict[str, float]]


def _weight_history(
    book_rets: Dict[str, List[float]],
    dates: Sequence[datetime.date],
    mode: str,
) -> WeightHistory:
    """Daily weight vectors for one arm, using idea #79's rule UNCHANGED."""
    return [mh._weights(book_rets, i, mode) for i in range(1, len(dates))]


def _gross_and_turnover(
    hist: WeightHistory,
    book_rets: Dict[str, List[float]],
) -> Tuple[List[float], List[float]]:
    """
    Gross portfolio return and turnover per day for a given weight history.

    Cost is deliberately NOT applied here: it is a pure drag applied later, so the
    same gross/turnover pair serves every point of the cost grid exactly.
    """
    book_ids = sorted(book_rets.keys())
    gross: List[float] = []
    turns: List[float] = []
    prev: Dict[str, float] = {}
    for k, w in enumerate(hist):
        i = k + 1  # weight index k corresponds to return index i (see mh._run)
        gross.append(sum(w.get(b, 0.0) * book_rets[b][i] for b in book_ids))
        turns.append(
            sum(abs(w.get(b, 0.0) - prev.get(b, 0.0)) for b in book_ids) if prev else 0.0
        )
        prev = w
    return gross, turns


def _net(gross: Sequence[float], turns: Sequence[float], cost_bps: float) -> List[float]:
    """Exact net series at an arbitrary cost. net = gross - turnover * cost/1e4."""
    return [g - t * cost_bps / 10_000.0 for g, t in zip(gross, turns)]


def _turnover_per_year(turns: Sequence[float], n_days: int) -> float:
    return sum(turns) / (n_days / 365.0) if n_days else 0.0


# ── turnover-matched controls ────────────────────────────────────────────────────
def _relabel(hist: WeightHistory, perm: Sequence[str], book_ids: Sequence[str]) -> WeightHistory:
    """
    Apply ONE fixed identity permutation to every daily weight vector.

    Turnover is preserved EXACTLY: the per-day multiset of weights is untouched and the
    same relabelling is used on every day, so |w_t(b) - w_{t-1}(b)| is merely reindexed.
    """
    mapping = dict(zip(book_ids, perm))
    return [{mapping[b]: w for b, w in day.items()} for day in hist]


def _rotate(hist: WeightHistory, k: int) -> WeightHistory:
    """Circular shift of the weight sequence by k days (turnover preserved up to wrap)."""
    if not hist:
        return hist
    k %= len(hist)
    return hist[k:] + hist[:k]


# ── reporting helpers ────────────────────────────────────────────────────────────
def _dcalmar(net: Sequence[float], base_calmar: float) -> float:
    return mh._calmar(list(net)) - base_calmar


MAX_COST_SEARCH = 2000.0  # bps; above this the linear-cost model is meaningless anyway


def _degenerate(net: Sequence[float]) -> bool:
    """
    True when the cost drag has driven the path through zero equity.

    Guarding this matters: mh._apy() returns 0.0 when the compounded equity is <= 0, and
    0.0 is GREATER than this fixture's negative baseline Calmar.  A naive bisection reads
    that bankruptcy artifact as "still winning" and reports an absurd break-even.  Found
    by the first run of this script printing ">10000 bps" for the worst arm on the board.
    """
    compound = 1.0
    for r in net:
        if 1.0 + r <= 0.0:
            return True
        compound *= 1.0 + r
    return compound <= 0.0


def _breakeven_cost(
    gross: Sequence[float],
    turns: Sequence[float],
    base_calmar: float,
) -> Tuple[str, float]:
    """
    Cost at which dCalmar crosses zero, bisected over the non-degenerate cost range.

    Returns (verdict, dCalmar_at_zero).  If dCalmar is already <= 0 at zero cost the arm
    loses even when execution is FREE -- break-even does not exist and reading (B) holds.
    """
    d0 = _dcalmar(_net(gross, turns, 0.0), base_calmar)
    if d0 <= 0.0:
        return ("none (loses at c=0)", d0)

    def still_winning(c: float) -> bool:
        net = _net(gross, turns, c)
        if _degenerate(net):
            return False  # bankrupt is not winning, whatever the ratio says
        return _dcalmar(net, base_calmar) > 0.0

    if still_winning(MAX_COST_SEARCH):
        return (f">{MAX_COST_SEARCH:.0f} bps", d0)
    lo, hi = 0.0, MAX_COST_SEARCH
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if still_winning(mid):
            lo = mid
        else:
            hi = mid
    return (f"{(lo + hi) / 2.0:.0f} bps", d0)


def _band(values: Sequence[float]) -> Tuple[float, float, float]:
    """(min, median, max) of a control distribution."""
    xs = sorted(values)
    n = len(xs)
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
    return xs[0], med, xs[-1]


# ── main ─────────────────────────────────────────────────────────────────────────
def run_idea80() -> None:
    print("=" * 78)
    print("Idea #80 CSS: Cost-Signal Separation  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print("Question: is the law of reactivity (#32/#33) about the SIGNAL or about the TOLL?")
    print("=" * 78)

    raw_books = mh._load_fixture()
    by_date: Dict[str, Dict[datetime.date, float]] = {}
    for sid, series in raw_books.items():
        dts, rets = mh._daily_returns(series)
        by_date[sid] = dict(zip(dts, rets))

    common_dates = sorted(set.intersection(*[set(d.keys()) for d in by_date.values()]))
    book_rets = {sid: [by_date[sid][d] for d in common_dates] for sid in sorted(by_date)}
    ret_dates = common_dates[1:]
    book_ids = sorted(book_rets.keys())
    n_days = len(ret_dates)

    print(f"\nBooks: {len(book_ids)}  ({', '.join(book_ids)})")
    print(f"Aligned: {common_dates[0]} … {common_dates[-1]}  ({len(common_dates)} days)")

    # Baseline: equal weight.  Zero turnover after day 1 => cost-invariant.
    eq_hist = _weight_history(book_rets, common_dates, "eq")
    eq_gross, eq_turns = _gross_and_turnover(eq_hist, book_rets)
    eq_calmar = mh._calmar(_net(eq_gross, eq_turns, 0.0))
    eq_apy = mh._apy(_net(eq_gross, eq_turns, 0.0))
    print(
        f"Baseline equal-weight: APY={eq_apy*100:.2f}%  Calmar={eq_calmar:.2f}  "
        f"turnover/yr={_turnover_per_year(eq_turns, n_days):.2f}  (cost-invariant ✓)"
    )

    # ── ANCHOR: reproduce idea #79's published table at the convention cost ────────
    print("\n" + "─" * 78)
    print(f"ANCHOR — this harness must reproduce #79 at c={CONVENTION_COST} bps")
    print(f"{'arm':<22} {'APY':>9} {'maxDD':>9} {'Calmar':>8} {'dCalmar':>9} {'TO/yr':>7}")
    print("─" * 78)
    arms: Dict[str, Tuple[List[float], List[float], WeightHistory]] = {}
    for mode, label in ARMS:
        hist = _weight_history(book_rets, common_dates, mode)
        gross, turns = _gross_and_turnover(hist, book_rets)
        arms[mode] = (gross, turns, hist)
        net = _net(gross, turns, CONVENTION_COST)
        print(
            f"  {label:<20} {mh._apy(net)*100:>8.2f}% {mh._mdd(net)*100:>8.2f}% "
            f"{mh._calmar(net):>8.2f} {_dcalmar(net, eq_calmar):>+9.2f} "
            f"{_turnover_per_year(turns, n_days):>7.2f}"
        )
    print("  (compare against #79's registry table — identical numbers = same instrument)")

    # ── 1. COST SWEEP ─────────────────────────────────────────────────────────────
    print("\n" + "─" * 78)
    print("1. COST SWEEP — dCalmar vs equal-weight at each toll  [bt]")
    header = f"{'arm':<22}" + "".join(f"{c:>8}" for c in COST_GRID)
    print(header)
    print("─" * 78)
    for mode, label in ARMS:
        gross, turns, _ = arms[mode]
        cells = "".join(
            f"{_dcalmar(_net(gross, turns, c), eq_calmar):>+8.2f}" for c in COST_GRID
        )
        print(f"  {label:<20}{cells}")
    print(f"  {'(cost, bps)':<20}" + "".join(f"{c:>8}" for c in COST_GRID))

    print("\n  Same sweep on netAPY (monotone axis, no ratio noise):")
    print(f"  {'arm':<20}" + "".join(f"{c:>8}" for c in COST_GRID))
    for mode, label in ARMS:
        gross, turns, _ = arms[mode]
        cells = "".join(
            f"{mh._apy(_net(gross, turns, c))*100:>7.2f}%" for c in COST_GRID
        )
        print(f"  {label:<20}{cells}")
    print(f"  {'equal-weight':<20}" + "".join(f"{eq_apy*100:>7.2f}%" for _ in COST_GRID))

    # ── 2. DECOMPOSITION + BREAK-EVEN ─────────────────────────────────────────────
    print("\n" + "─" * 78)
    print(f"2. DECOMPOSITION at the convention cost c={CONVENTION_COST} bps")
    print("   The whole verdict turns on the SIGN of the c=0 column, so it is printed")
    print("   at full precision and doubled with netAPY, which carries no ratio noise.")
    print(
        f"{'arm':<22} {'dCal(0)':>10} {'dAPY(0)':>9} {'dCal(96)':>10} "
        f"{'toll part':>10} {'break-even':>16}"
    )
    print("─" * 78)
    for mode, label in ARMS:
        gross, turns, _ = arms[mode]
        d0 = _dcalmar(_net(gross, turns, 0.0), eq_calmar)
        d96 = _dcalmar(_net(gross, turns, CONVENTION_COST), eq_calmar)
        dapy0 = mh._apy(_net(gross, turns, 0.0)) - eq_apy
        verdict, _ = _breakeven_cost(gross, turns, eq_calmar)
        print(
            f"  {label:<20} {d0:>+10.4f} {dapy0*100:>+8.2f}pp {d96:>+10.2f} "
            f"{d96 - d0:>+10.2f} {verdict:>16}"
        )

    # ── 3. TURNOVER-MATCHED CONTROLS AT ZERO COST ─────────────────────────────────
    n_perm = 1
    for k in range(2, len(book_ids) + 1):
        n_perm *= k
    exhaustive = n_perm <= MAX_EXHAUSTIVE_PERMS
    print("\n" + "─" * 78)
    print("3. TURNOVER-MATCHED CONTROLS AT ZERO COST — is the signal informative at all?")
    print(
        f"   RELABEL: {'ALL ' + str(n_perm - 1) + ' non-identity permutations (exact, seed-free)' if exhaustive else 'sampled'}"
        f"   ·   ROTATE: every {ROTATION_STEP}th circular shift"
    )
    print("   p = fraction of controls that BEAT the real arm (small p = signal informative).")
    print(
        f"{'arm':<20} {'real':>8} {'relabel band (min/med/max)':>32} {'beat':>10} {'p':>7}"
    )
    print("─" * 78)

    control_summary: Dict[str, dict] = {}
    for mode, label in ARMS:
        gross, turns, hist = arms[mode]
        real_d0 = _dcalmar(_net(gross, turns, 0.0), eq_calmar)

        relabel_ds: List[float] = []
        perms = itertools.permutations(book_ids) if exhaustive else []
        for perm in perms:
            if list(perm) == book_ids:
                continue  # identity == the real arm
            g2, t2 = _gross_and_turnover(_relabel(hist, perm, book_ids), book_rets)
            # turnover must be preserved exactly by construction
            assert abs(sum(t2) - sum(turns)) < 1e-9, "relabel changed turnover"
            relabel_ds.append(_dcalmar(_net(g2, t2, 0.0), eq_calmar))

        lo, med, hi = _band(relabel_ds)
        beat = sum(1 for d in relabel_ds if d > real_d0)
        p = (beat + 1) / (len(relabel_ds) + 1)
        print(
            f"  {label:<18} {real_d0:>+8.2f}   {lo:>+8.2f} /{med:>+8.2f} /{hi:>+8.2f}   "
            f"{beat:>4}/{len(relabel_ds):<5} {p:>6.3f}"
        )
        control_summary[mode] = {
            "real": real_d0,
            "relabel": (lo, med, hi),
            "relabel_beat": beat,
            "relabel_n": len(relabel_ds),
            "p_relabel": p,
        }

    print(f"\n{'arm':<20} {'real':>8} {'rotate band (min/med/max)':>32} {'beat':>10} {'p':>7}")
    print("─" * 78)
    for mode, label in ARMS:
        gross, turns, hist = arms[mode]
        real_d0 = _dcalmar(_net(gross, turns, 0.0), eq_calmar)
        rot_ds: List[float] = []
        for k in range(ROTATION_STEP, len(hist), ROTATION_STEP):
            g2, t2 = _gross_and_turnover(_rotate(hist, k), book_rets)
            rot_ds.append(_dcalmar(_net(g2, t2, 0.0), eq_calmar))
        lo, med, hi = _band(rot_ds)
        beat = sum(1 for d in rot_ds if d > real_d0)
        p = (beat + 1) / (len(rot_ds) + 1)
        print(
            f"  {label:<18} {real_d0:>+8.2f}   {lo:>+8.2f} /{med:>+8.2f} /{hi:>+8.2f}   "
            f"{beat:>4}/{len(rot_ds):<5} {p:>6.3f}"
        )
        control_summary[mode]["rotate"] = (lo, med, hi)
        control_summary[mode]["rotate_beat"] = beat
        control_summary[mode]["rotate_n"] = len(rot_ds)
        control_summary[mode]["p_rotate"] = p

    # ── 4. OOS: does the answer survive the split? ─────────────────────────────────
    print("\n" + "─" * 78)
    print(f"4. TRAIN / TEST (split {mh.SPLIT_DATE}) — dCalmar at c=0 and c={CONVENTION_COST}")
    print(f"{'arm':<22} {'train c=0':>11} {'train c=96':>12} {'test c=0':>11} {'test c=96':>12}")
    print("─" * 78)
    eq0 = _net(eq_gross, eq_turns, 0.0)
    eq_tr, eq_te = mh._split(eq0, ret_dates, mh.SPLIT_DATE)
    eq_tr_c, eq_te_c = mh._calmar(eq_tr), mh._calmar(eq_te)
    for mode, label in ARMS:
        gross, turns, _ = arms[mode]
        row = []
        for c in (0.0, float(CONVENTION_COST)):
            tr, te = mh._split(_net(gross, turns, c), ret_dates, mh.SPLIT_DATE)
            row.append((mh._calmar(tr) - eq_tr_c, mh._calmar(te) - eq_te_c))
        print(
            f"  {label:<20} {row[0][0]:>+11.2f} {row[1][0]:>+12.2f} "
            f"{row[0][1]:>+11.2f} {row[1][1]:>+12.2f}"
        )

    # ── verdict ───────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VERDICT INPUTS  [bt]  fixture only — real panel unavailable (same as #79)")
    for mode, label in ARMS:
        cs = control_summary[mode]
        inside = cs["relabel"][0] <= cs["real"] <= cs["relabel"][2]
        where = "INSIDE relabel band" if inside else "OUTSIDE (below)" if cs["real"] < cs["relabel"][0] else "OUTSIDE (above)"
        print(
            f"  {label:<20} dCal(0)={cs['real']:+.2f}  {where}  "
            f"p_relabel={cs['p_relabel']:.3f}  p_rotate={cs['p_rotate']:.3f}"
        )
    print()
    print("  Reading (A) FISCAL holds for an arm iff dCalmar(0) > 0 (a break-even exists).")
    print("  Reading (B) STRUCTURAL holds for an arm iff dCalmar(0) <= 0 (loses when free).")
    print()
    print("  IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence L0 [bt]")
    print("  Capital not moved.  No module built, no agent deployed.")
    print("=" * 78)


if __name__ == "__main__":
    run_idea80()
