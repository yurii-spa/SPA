#!/usr/bin/env python3
"""
scripts/edge_cost_internalised_timing.py — registry ideas CSSR and CIT

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Reads the aggressive-lab
panel READ-ONLY. Capital is not moved. No module is built and no agent is deployed here.

Working names are used inside the code (CSSR / CIT). Registry NUMBERS are claimed at
DELIVERY, never at writing time (registry rule at the top of DYNAMIC_LEVERAGE_GUARDIAN.md).


TWO QUESTIONS, BOTH ORDERED BY #80 CSS IN ITS OWN CAVEAT LIST
=============================================================
#80 separated the "law of reactivity" (#32/#33, six negatives through #79) into a FISCAL and
a STRUCTURAL reading and found it fiscal: at c=0 no arm loses to equal-weight and the slow
arm (h=60d) wins +4.96 pp netAPY, while every break-even (1/28/82/0 bps) sits BELOW the
registry's 96 bps convention. It then listed two limits of that finding, and both are
answerable with material this repository already carries:

  (а) "фикстура, L0; реальная панель data/aggressive_lab/ в этой сессии недоступна … на
       реальных данных ответ может быть другим, и это ОТКРЫТЫЙ вопрос"
      -> #79 and #80 both ran from a worktree. The panel is NOT git-tracked, so it is simply
         absent there and both silently fell back to the code-generated fixture. This session
         runs in the prod tree, where the panel exists: 10 books x 852 shared days
         2024-03-06..2026-07-05, with REAL calm-period variance and REAL crises.

  (е) "косты применяются как чистый drag к реализованному ряду и НЕ могут попасть обратно в
       сигнал … живой контроллер, читающий NET-equity, этой гарантии не имеет"
      -> Stated as a look-ahead SAFETY property, it hides an engineering question that nobody
         in the registry has asked: every arm ever measured here decides ITS TRADES BLIND TO
         THE TOLL IT WILL PAY. The toll is subtracted afterwards, by the scorer. A real
         allocator does not work that way and does not have to.


IDEA CSSR — Cost-Signal Separation on the REAL panel
----------------------------------------------------
#80's instrument, UNCHANGED (the module is imported, not re-implemented), pointed at the real
panel instead of the fixture. Same cost grid, same decomposition, same two turnover-matched
controls, same canonical split. If the fiscal verdict is a property of the fixture's constant
drift, this is where it breaks.

  ANCHOR: the same code path is first run on the FIXTURE and must reproduce #80's published
  table byte-for-byte (h60: dCalmar(0) +0.56, netAPY(0) +2.34%, break-even 82 bps; MHFC at
  c=96: -14.73% / -31.95% / -0.46 / dCalmar -0.28 / TO 13.84). Two datasets, one instrument.

  DIFFERENCE FROM #80 THAT MUST BE DECLARED: with 10 books RELABEL cannot be exhaustive
  (10! = 3.6M), so on the real panel it is SAMPLED — 200 seeded permutations — and the header
  above every such table says SAMPLED. On the 5-book fixture the same call still enumerates
  all 119, which is what keeps the anchor exact. #80's "best of all 120" claim is a property
  of a 5-book space; it does not transfer to the panel and is not restated there.


IDEA CIT — Cost-Internalised Timing
------------------------------------
MECHANISM (one new knob, everything else inherited from #79/#80 verbatim):

  Every day the arm's rule proposes a candidate weight vector w*. Today's arms take it
  unconditionally. CIT takes it only when it PAYS FOR ITSELF:

      tau      = sum_b |w*_b - w_prev_b|                       turnover the move would cost
      g_daily  = sum_b (w*_b - w_prev_b) * s_b                 expected daily gain of the move,
                                                               s_b = the arm's OWN signal
      switch iff   lambda * g_daily  >  tau * c_assumed / 1e4

  lambda = how many days the arm expects to keep the decision. It is the only new parameter,
  it has a unit (days), and both of its limits are already-published objects:

      lambda = inf  ==  today's arm, exactly (#80's arm, asserted cell-by-cell by test)
      lambda = 0    ==  freeze the first vector forever, zero turnover

  Books whose signal is None (warm-up) contribute s_b = 0: fail-CLOSED, an unmeasured book is
  never credited with edge it has not shown.

WHY THIS IS NOT #50 NTB, #49 RDT, #51 SLT OR #60 DHD
  #50 NTB   — a band on WEIGHT DRIFT: "do not trade until the weight has moved far enough".
              Cost never enters the rule; the band is a distance, and #50 killed it because
              random days of the same trade count did as well.
  #49 RDT   — MEASURED the tax of holding a constant target. It changed no decision.
  #51 SLT   — delayed the signal by tau days. Cost is not in the rule.
  #60 DHD   — decision frequency / holding term as CALENDAR knobs. Cost is not in the rule.
  CIT       — the toll is INSIDE the objective. The arm trades when the edge it believes in
              is worth more than the toll it will pay, and skips the trade otherwise. That is
              a different object from every band above: it is state-dependent in the SIZE of
              the proposed move and in the STRENGTH of the signal, not in elapsed days.

THE CONTROL THAT DECIDES THE VERDICT
  CIT trades less. #50 proved that on this panel "trading less" is by itself worth something,
  and that a rule which only trades less is a FREQUENCY finding, not an edge. So CIT is judged
  against a RANDOM SWITCH SCHEDULE OF THE SAME SWITCH COUNT (20 seeds) and against a PERIODIC
  schedule of the same count. If CIT sits inside the random band, the honest verdict is
  "frequency, again" and it must be written that way.

  Second control, free: MIS-SPECIFIED lambda and MIS-SPECIFIED c_assumed. A rule that only
  works when the controller guesses its own holding horizon right is not deployable, and the
  sweep says how wrong it may be.

LOOK-AHEAD
  Inherited from #79 unchanged: the signal at index i uses rets[i-h:i]; the weight at i is
  applied to rets[i]. CIT adds no new data access - it reads the same signal the arm already
  computed plus its OWN previous weights. Asserted by a test that perturbs the future and
  requires the past to be bit-identical.

HONEST LIMITS DECLARED UP FRONT
  • evidence L0 - the panel's own books are backtests over real deep-history feeds, so this
    measures a rule on a real return SHAPE, not realized P&L. All numbers marked [bt];
  • the linear one-way cost model is #10's convention and is OPTIMISTIC: real slippage is
    convex and worst exactly in a crisis, so printed break-evens are reached EARLIER in life;
  • g_daily is estimated with the SAME signal that picks the books. If the signal is biased
    high, CIT switches too readily; the bias cancels in neither direction and is not corrected
    here. That is a property of the mechanism, not of this measurement;
  • no parameter is chosen on TEST: the lambda ladder, the cost grid, the seeds and the split
    were fixed before any number was read.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
import os
import random
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
#: data/ and must point at the prod tree's copy (read-only). This is exactly the trap #70,
#: #79 and #80 fell into - they found no panel and silently used the fixture instead.
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

#: Inherited from #80 without change.
COST_GRID = css.COST_GRID
CONVENTION_COST = css.CONVENTION_COST
ARMS = css.ARMS

#: The one new knob, in DAYS. inf == today's arm; 0 == freeze. Fixed before any number read.
LAMBDA_GRID: Tuple[float, ...] = (0.0, 1.0, 5.0, 20.0, 60.0, float("inf"))

#: Sampled RELABEL for the 10-book panel (10! is not enumerable). Seeded, so reproducible.
RELABEL_SAMPLES = 200
RELABEL_SEED = 20260827
CONTROL_SEEDS = tuple(range(20))

SPLIT_DATE = mh.SPLIT_DATE  # "2025-06-30", registry-canonical


# ───────────────────────────── data sources ──────────────────────────────────────
BookRets = Dict[str, List[float]]


def _align(by_date: Dict[str, Dict[datetime.date, float]]) -> Tuple[List[datetime.date], BookRets]:
    common = sorted(set.intersection(*[set(d.keys()) for d in by_date.values()]))
    return common, {sid: [by_date[sid][d] for d in common] for sid in sorted(by_date)}


def load_fixture_panel() -> Tuple[List[datetime.date], BookRets]:
    """#80's dataset, loaded through #79's loader unchanged (the ANCHOR dataset)."""
    raw = mh._load_fixture()
    by_date: Dict[str, Dict[datetime.date, float]] = {}
    for sid, series in raw.items():
        dts, rets = mh._daily_returns(series)
        by_date[sid] = dict(zip(dts, rets))
    return _align(by_date)


def load_real_panel(panel_dir: Path = PANEL_DIR) -> Tuple[List[datetime.date], BookRets]:
    """The real aggressive-lab panel, through RPE's fail-CLOSED loader unchanged.

    Raises when the panel is absent rather than falling back to the fixture: a silent
    fallback is precisely how #79/#80 ended up publishing fixture numbers under a title
    that did not say so.
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


# ───────────────────────── arm construction (CIT) ────────────────────────────────
def _signals_at(book_rets: BookRets, i: int, mode: str) -> Dict[str, Optional[float]]:
    """The arm's OWN signal, computed by #79's functions unchanged."""
    if mode == "mhfc":
        return {b: mh._mhfc_signal(book_rets[b], i) for b in sorted(book_rets)}
    h = int(mode[1:])
    return {b: mh._signal_at(book_rets[b], i, h) for b in sorted(book_rets)}


class Candidates:
    """Per-day candidate weights and signals for one arm, computed ONCE.

    Purely a speed device with no effect on any number: both series depend only on
    (panel, mode) and NOT on lambda or on the assumed toll, while the lambda ladder and the
    break-even bisection need them hundreds of times. mh._mhfc_signal is O(M*h) per book-day,
    so recomputation would make the 10-book panel unrunnable. A test asserts that a cached
    arm equals a from-scratch arm cell for cell, so the cache cannot drift from the source.
    """

    def __init__(self, book_rets: BookRets, n_dates: int, mode: str) -> None:
        self.book_ids = sorted(book_rets)
        self.mode = mode
        self.weights = [mh._weights(book_rets, i, mode) for i in range(1, n_dates)]
        self.signals = (
            [_signals_at(book_rets, i, mode) for i in range(1, n_dates)]
            if mode != "eq"
            else [{b: 0.0 for b in self.book_ids} for _ in range(1, n_dates)]
        )


#: key -> (the panel object itself, its Candidates). The panel is kept in the value ON PURPOSE:
#: `id()` is only unique among LIVE objects, and CPython reuses the number as soon as one is
#: collected — the same trap as a literal pid. Holding the reference makes reuse impossible for
#: as long as the entry exists. `n_dates` is in the key because a cached series of the wrong
#: length would be silently short, not loudly wrong.
_CAND_CACHE: Dict[Tuple[int, int, str], Tuple[BookRets, Candidates]] = {}


def candidates_for(book_rets: BookRets, n_dates: int, mode: str) -> Candidates:
    key = (id(book_rets), n_dates, mode)
    got = _CAND_CACHE.get(key)
    if got is None or got[0] is not book_rets:
        got = (book_rets, Candidates(book_rets, n_dates, mode))
        _CAND_CACHE[key] = got
    return got[1]


def cit_history(
    book_rets: BookRets,
    n_dates: int,
    mode: str,
    lam: float,
    cost_assumed_bps: float,
    cand: Optional[Candidates] = None,
) -> Tuple[css.WeightHistory, int]:
    """
    Daily weight vectors under cost-internalised switching, plus the switch count.

    lam == inf  -> take every candidate  == #80's arm, cell for cell.
    lam == 0    -> take the first candidate and never move again (zero turnover).
    """
    cand = cand or candidates_for(book_rets, n_dates, mode)
    book_ids = cand.book_ids
    hist: css.WeightHistory = []
    prev: Optional[Dict[str, float]] = None
    switches = 0
    for k in range(len(cand.weights)):
        cw = cand.weights[k]
        if prev is None:
            w = cw
        else:
            tau = sum(abs(cw.get(b, 0.0) - prev.get(b, 0.0)) for b in book_ids)
            if tau <= 1e-12:
                w = prev
            else:
                if math.isinf(lam):
                    take = True
                else:
                    sig = cand.signals[k]
                    gain = sum(
                        (cw.get(b, 0.0) - prev.get(b, 0.0)) * (sig[b] or 0.0)
                        for b in book_ids
                    )
                    take = lam * gain > tau * cost_assumed_bps / 10_000.0
                if take:
                    w = cw
                    switches += 1
                else:
                    w = prev
        hist.append(w)
        prev = w
    return hist, switches


def scheduled_history(
    book_rets: BookRets,
    n_dates: int,
    mode: str,
    switch_days: Sequence[int],
) -> css.WeightHistory:
    """Same candidate stream, but the arm may move ONLY on the given day indices.

    This is the control device #50 used to kill the no-trade band: hold the number of trades
    fixed and randomise WHEN they happen. If the real rule cannot beat that, what it bought
    was frequency, not information.
    """
    allowed = set(switch_days)
    cand = candidates_for(book_rets, n_dates, mode)
    hist: css.WeightHistory = []
    prev: Optional[Dict[str, float]] = None
    for k, cw in enumerate(cand.weights):
        if prev is None or k in allowed:
            w = cw
        else:
            w = prev
        hist.append(w)
        prev = w
    return hist


def random_switch_days(n_slots: int, n_switch: int, seed: int) -> List[int]:
    rng = random.Random(seed)
    pool = list(range(1, n_slots))
    if n_switch >= len(pool):
        return pool
    return sorted(rng.sample(pool, n_switch))


def periodic_switch_days(n_slots: int, n_switch: int) -> List[int]:
    if n_switch <= 0:
        return []
    step = max(1, (n_slots - 1) // n_switch)
    return [k for k in range(1, n_slots, step)][:n_switch]


# ───────────────────────────── scoring ───────────────────────────────────────────
class Scored:
    __slots__ = ("gross", "turns", "hist", "switches")

    def __init__(self, gross, turns, hist, switches):
        self.gross, self.turns, self.hist, self.switches = gross, turns, hist, switches

    def net(self, c: float) -> List[float]:
        return css._net(self.gross, self.turns, c)

    def turnover_per_year(self, n_days: int) -> float:
        return css._turnover_per_year(self.turns, n_days)


def score(hist: css.WeightHistory, book_rets: BookRets, switches: int = -1) -> Scored:
    gross, turns = css._gross_and_turnover(hist, book_rets)
    return Scored(gross, turns, hist, switches)


def split_net(net: Sequence[float], ret_dates: Sequence[datetime.date]) -> Tuple[List[float], List[float]]:
    """Train/test halves of a NET series, using #79's own splitter unchanged.

    Deliberately NOT a re-derivation: an earlier version of this file re-implemented the split
    with its own boundary and zeroed the first day's toll, which moved the anchor cell for h60
    from #80's published +0.11 to +0.12. One cell of disagreement is enough to stop calling it
    the same instrument, so the splitter is imported instead.
    """
    return mh._split(list(net), list(ret_dates), SPLIT_DATE)


def _band(xs: Sequence[float]) -> Tuple[float, float, float]:
    return css._band(list(xs))


def relabel_permutations(book_ids: Sequence[str], want: int) -> List[List[str]]:
    """Non-identity relabellings: EXHAUSTIVE when the space is small enough, else sampled.

    The distinction is not cosmetic. #80 could claim "best of all 120" because 5 books make
    the space enumerable; 10 books make it 3.6M and no such claim transfers. Asking a
    rejection sampler for 200 distinct permutations out of 119 that exist is also a hang, and
    it is exactly what the first version of this function did.
    """
    ids = list(book_ids)
    total = math.factorial(len(ids))
    if total - 1 <= want:
        import itertools

        return [list(p) for p in itertools.permutations(ids) if list(p) != ids]
    return _sample_relabel_permutations(ids, want)


def _sample_relabel_permutations(ids: List[str], want: int) -> List[List[str]]:
    """BOUNDED rejection sampling of distinct non-identity relabellings.

    The bound is not defensive decoration: an unbounded version of this loop is what ate the
    first run of this harness (200 distinct permutations demanded of a 119-element space), and
    a spinning backtest reads to the operator as "slow", never as "broken". Bounded, the same
    defect becomes a failure a test can actually catch.
    """
    total = math.factorial(len(ids))
    rng = random.Random(RELABEL_SEED)
    seen = {tuple(ids)}
    out: List[List[str]] = []
    budget = 20 * want + 1000
    while len(out) < want:
        budget -= 1
        if budget <= 0:
            raise RuntimeError(
                f"rejection sampler could not find {want} distinct non-identity permutations "
                f"of {len(ids)} books ({total - 1} exist) — the caller asked for more than the "
                f"space contains, or the exhaustive branch was bypassed"
            )
        p = ids[:]
        rng.shuffle(p)
        if tuple(p) in seen:
            continue
        seen.add(tuple(p))
        out.append(p)
    return out


def _fmt_lam(lam: float) -> str:
    return "inf" if math.isinf(lam) else f"{lam:g}d"


# ───────────────────────────── idea CSSR ─────────────────────────────────────────
def run_cssr(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    title: str,
    relabel_samples: int = RELABEL_SAMPLES,
) -> Dict[str, dict]:
    """#80's measurement on an arbitrary panel. Returns the per-arm summary."""
    book_ids = sorted(book_rets)
    ret_dates = list(dates[1:])
    n_days = len(ret_dates)

    print("=" * 78)
    print(f"CSSR — cost/signal separation  [{title}]  [bt]")
    print(f"Books: {len(book_ids)} ({', '.join(book_ids)})")
    print(f"Aligned: {dates[0]} … {dates[-1]}  ({len(dates)} days, {n_days} return days)")
    print("=" * 78)

    eq = score(candidates_for(book_rets, len(dates), "eq").weights, book_rets)
    eq_calmar = mh._calmar(eq.net(0.0))
    eq_apy = mh._apy(eq.net(0.0))
    print(
        f"Baseline equal-weight: APY={eq_apy * 100:.2f}%  maxDD={mh._mdd(eq.net(0.0)) * 100:.2f}%  "
        f"Calmar={eq_calmar:.2f}  TO/yr={eq.turnover_per_year(n_days):.2f} (cost-invariant)"
    )

    arms: Dict[str, Scored] = {}
    print(f"\n{'arm':<22} {'APY(96)':>9} {'maxDD':>9} {'Calmar':>8} {'dCal(96)':>9} {'TO/yr':>7}")
    print("-" * 78)
    for mode, label in ARMS:
        s = score(candidates_for(book_rets, len(dates), mode).weights, book_rets)
        arms[mode] = s
        net = s.net(CONVENTION_COST)
        print(
            f"  {label:<20} {mh._apy(net) * 100:>8.2f}% {mh._mdd(net) * 100:>8.2f}% "
            f"{mh._calmar(net):>8.2f} {mh._calmar(net) - eq_calmar:>+9.2f} "
            f"{s.turnover_per_year(n_days):>7.2f}"
        )

    print("\n1. COST SWEEP — dCalmar vs equal-weight")
    print(f"  {'arm':<20}" + "".join(f"{c:>8}" for c in COST_GRID))
    for mode, label in ARMS:
        s = arms[mode]
        print(
            f"  {label:<20}"
            + "".join(f"{mh._calmar(s.net(c)) - eq_calmar:>+8.2f}" for c in COST_GRID)
        )
    print("\n  netAPY (monotone axis, no ratio noise):")
    print(f"  {'arm':<20}" + "".join(f"{c:>8}" for c in COST_GRID))
    for mode, label in ARMS:
        s = arms[mode]
        print(f"  {label:<20}" + "".join(f"{mh._apy(s.net(c)) * 100:>7.2f}%" for c in COST_GRID))
    print(f"  {'equal-weight':<20}" + "".join(f"{eq_apy * 100:>7.2f}%" for _ in COST_GRID))

    print(f"\n2. DECOMPOSITION at c={CONVENTION_COST} bps")
    print(f"{'arm':<22} {'dCal(0)':>10} {'dAPY(0)':>10} {'dCal(96)':>10} {'toll':>9} {'break-even':>16}")
    print("-" * 78)
    summary: Dict[str, dict] = {}
    for mode, label in ARMS:
        s = arms[mode]
        d0 = mh._calmar(s.net(0.0)) - eq_calmar
        d96 = mh._calmar(s.net(CONVENTION_COST)) - eq_calmar
        dapy0 = mh._apy(s.net(0.0)) - eq_apy
        verdict, _ = css._breakeven_cost(s.gross, s.turns, eq_calmar)
        print(
            f"  {label:<20} {d0:>+10.4f} {dapy0 * 100:>+9.2f}pp {d96:>+10.2f} "
            f"{d96 - d0:>+9.2f} {verdict:>16}"
        )
        summary[mode] = {"d0": d0, "d96": d96, "dapy0": dapy0, "breakeven": verdict}

    n_perm_total = math.factorial(len(book_ids))
    exhaustive = n_perm_total - 1 <= relabel_samples
    print(f"\n3. TURNOVER-MATCHED CONTROLS AT c=0  (RELABEL "
          f"{'EXHAUSTIVE: all ' + str(n_perm_total - 1) + ' non-identity permutations' if exhaustive else 'SAMPLED ' + str(relabel_samples) + ' seeded permutations out of ' + str(n_perm_total) + ' — NOT exhaustive'}"
          f"; ROTATE every {css.ROTATION_STEP}th shift)")
    print("   p = fraction of controls that BEAT the real arm (small p = signal informative)")
    print(f"{'arm':<20} {'real':>9} {'relabel min/med/max':>34} {'beat':>10} {'p':>7}")
    print("-" * 78)
    perms = relabel_permutations(book_ids, relabel_samples)
    for mode, label in ARMS:
        s = arms[mode]
        real = mh._calmar(s.net(0.0)) - eq_calmar
        ds = []
        for perm in perms:
            g2, t2 = css._gross_and_turnover(css._relabel(s.hist, perm, book_ids), book_rets)
            assert abs(sum(t2) - sum(s.turns)) < 1e-9, "relabel changed turnover"
            ds.append(mh._calmar(css._net(g2, t2, 0.0)) - eq_calmar)
        lo, med, hi = _band(ds)
        beat = sum(1 for d in ds if d > real)
        p = (beat + 1) / (len(ds) + 1)
        print(
            f"  {label:<18} {real:>+9.2f}   {lo:>+9.2f} /{med:>+9.2f} /{hi:>+9.2f}  "
            f"{beat:>4}/{len(ds):<5} {p:>6.3f}"
        )
        summary[mode].update(relabel=(lo, med, hi), p_relabel=p, relabel_beat=beat, relabel_n=len(ds))

    print(f"\n{'arm':<20} {'real':>9} {'rotate min/med/max':>34} {'beat':>10} {'p':>7}")
    print("-" * 78)
    for mode, label in ARMS:
        s = arms[mode]
        real = mh._calmar(s.net(0.0)) - eq_calmar
        ds = []
        for k in range(css.ROTATION_STEP, len(s.hist), css.ROTATION_STEP):
            g2, t2 = css._gross_and_turnover(css._rotate(s.hist, k), book_rets)
            ds.append(mh._calmar(css._net(g2, t2, 0.0)) - eq_calmar)
        lo, med, hi = _band(ds)
        beat = sum(1 for d in ds if d > real)
        p = (beat + 1) / (len(ds) + 1)
        print(
            f"  {label:<18} {real:>+9.2f}   {lo:>+9.2f} /{med:>+9.2f} /{hi:>+9.2f}  "
            f"{beat:>4}/{len(ds):<5} {p:>6.3f}"
        )
        summary[mode].update(rotate=(lo, med, hi), p_rotate=p, rotate_beat=beat, rotate_n=len(ds))

    print(f"\n4. TRAIN / TEST (split {SPLIT_DATE}) — dCalmar")
    print(f"{'arm':<22} {'train c=0':>11} {'train c=96':>12} {'test c=0':>11} {'test c=96':>12}")
    print("-" * 78)
    base = {}
    for c in (0.0, float(CONVENTION_COST)):
        tr, te = split_net(eq.net(c), ret_dates)
        base[c] = (mh._calmar(tr), mh._calmar(te))
    for mode, label in ARMS:
        s = arms[mode]
        cells = {}
        for c in (0.0, float(CONVENTION_COST)):
            tr, te = split_net(s.net(c), ret_dates)
            cells[c] = (mh._calmar(tr) - base[c][0], mh._calmar(te) - base[c][1])
        print(
            f"  {label:<20} {cells[0.0][0]:>+11.2f} {cells[96.0][0]:>+12.2f} "
            f"{cells[0.0][1]:>+11.2f} {cells[96.0][1]:>+12.2f}"
        )
        summary[mode].update(
            train_d0=cells[0.0][0], train_d96=cells[96.0][0],
            test_d0=cells[0.0][1], test_d96=cells[96.0][1],
        )
    summary["_eq"] = {"calmar": eq_calmar, "apy": eq_apy}
    return summary


# ───────────────────────────── idea CIT ──────────────────────────────────────────
def run_cit(
    dates: Sequence[datetime.date],
    book_rets: BookRets,
    title: str,
    cost: float = CONVENTION_COST,
) -> Dict[Tuple[str, float], dict]:
    """Cost-internalised switching: the lambda ladder, its break-evens, and its controls."""
    ret_dates = list(dates[1:])
    n_days = len(ret_dates)
    n_dates = len(dates)

    print("\n" + "=" * 78)
    print(f"CIT — cost-internalised timing  [{title}]  [bt]   assumed toll = actual toll = {cost:g} bps")
    print("=" * 78)

    eq = score(candidates_for(book_rets, len(dates), "eq").weights, book_rets)
    eq_calmar_c = mh._calmar(eq.net(cost))

    out: Dict[Tuple[str, float], dict] = {}
    print(f"\n1. LAMBDA LADDER at c={cost:g} bps  (lambda=inf is TODAY'S ARM — the anchor)")
    print(f"{'arm':<14} {'lam':>6} {'switch':>7} {'TO/yr':>7} {'netAPY':>9} {'maxDD':>9} "
          f"{'Calmar':>8} {'dCal':>8}")
    print("-" * 78)
    for mode, label in ARMS:
        for lam in LAMBDA_GRID:
            hist, sw = cit_history(book_rets, n_dates, mode, lam, cost)
            s = score(hist, book_rets, sw)
            net = s.net(cost)
            out[(mode, lam)] = {
                "switches": sw,
                "to": s.turnover_per_year(n_days),
                "apy": mh._apy(net),
                "mdd": mh._mdd(net),
                "calmar": mh._calmar(net),
                "dcal": mh._calmar(net) - eq_calmar_c,
                "scored": s,
            }
            r = out[(mode, lam)]
            print(
                f"  {label:<12} {_fmt_lam(lam):>6} {sw:>7} {r['to']:>7.2f} "
                f"{r['apy'] * 100:>8.2f}% {r['mdd'] * 100:>8.2f}% {r['calmar']:>8.2f} "
                f"{r['dcal']:>+8.2f}"
            )
        print("-" * 78)
    print(f"  equal-weight baseline at c={cost:g}: netAPY {mh._apy(eq.net(cost)) * 100:.2f}%  "
          f"Calmar {eq_calmar_c:.2f}")

    print("\n2. BREAK-EVEN of each lambda (dCalmar vs equal-weight crosses zero)")
    print("   The whole point: does internalising the toll lift the break-even ABOVE the")
    print(f"   registry convention of {CONVENTION_COST} bps? Anything below it changes nothing in practice.")
    print(f"{'arm':<14}" + "".join(f"{_fmt_lam(l):>12}" for l in LAMBDA_GRID))
    print("-" * 78)
    for mode, label in ARMS:
        cells = []
        cand = candidates_for(book_rets, n_dates, mode)
        for lam in LAMBDA_GRID:
            # The arm must be REBUILT at every candidate cost, because unlike every previous
            # registry arm this rule READS the cost. #80 could reuse one gross/turnover pair
            # across the whole grid; here that shortcut would measure a different object.
            def be(c: float, mode=mode, lam=lam) -> Optional[float]:
                h, _ = cit_history(book_rets, n_dates, mode, lam, c, cand=cand)
                sc = score(h, book_rets)
                net = css._net(sc.gross, sc.turns, c)
                if css._degenerate(net):
                    return None
                return mh._calmar(net) - mh._calmar(eq.net(c))

            d0 = be(0.0)
            if d0 is None or d0 <= 0.0:
                cells.append("loses@0")
                continue
            lo, hi = 0.0, css.MAX_COST_SEARCH
            if (be(hi) or -1.0) > 0.0:
                cells.append(f">{css.MAX_COST_SEARCH:.0f}")
                continue
            for _ in range(24):  # 2000/2^24 bps of resolution — far below the printed 1 bps
                mid = (lo + hi) / 2.0
                v = be(mid)
                if v is not None and v > 0.0:
                    lo = mid
                else:
                    hi = mid
            cells.append(f"{(lo + hi) / 2.0:.0f}bps")
        print(f"  {label:<12}" + "".join(f"{c:>12}" for c in cells))

    print(f"\n3. DECISIVE CONTROL — random switch schedule of the SAME switch count "
          f"({len(CONTROL_SEEDS)} seeds), plus periodic.")
    print("   #50 killed the no-trade band on exactly this control. If CIT is inside the band,")
    print("   what it bought is FREQUENCY, not cost-awareness, and it must be written that way.")
    print(f"{'arm':<14} {'lam':>6} {'CIT dCal':>9} {'random min/med/max':>32} {'beat':>8} {'p':>7} {'periodic':>9}")
    print("-" * 78)
    for mode, label in ARMS:
        for lam in LAMBDA_GRID:
            if math.isinf(lam) or lam == 0.0:
                continue  # the two limits have no free schedule to randomise
            r = out[(mode, lam)]
            sw = r["switches"]
            ds = []
            for seed in CONTROL_SEEDS:
                days = random_switch_days(n_dates - 1, sw, seed)
                sc = score(scheduled_history(book_rets, n_dates, mode, days), book_rets)
                ds.append(mh._calmar(sc.net(cost)) - eq_calmar_c)
            lo, med, hi = _band(ds)
            beat = sum(1 for d in ds if d > r["dcal"])
            p = (beat + 1) / (len(ds) + 1)
            per = score(
                scheduled_history(book_rets, n_dates, mode, periodic_switch_days(n_dates - 1, sw)),
                book_rets,
            )
            per_d = mh._calmar(per.net(cost)) - eq_calmar_c
            print(
                f"  {label:<12} {_fmt_lam(lam):>6} {r['dcal']:>+9.2f}   "
                f"{lo:>+9.2f} /{med:>+9.2f} /{hi:>+9.2f} {beat:>4}/{len(ds):<3} {p:>6.3f} "
                f"{per_d:>+9.2f}"
            )
            out[(mode, lam)].update(rand_band=(lo, med, hi), p_rand=p, periodic=per_d)
        print("-" * 78)

    print("\n4. MIS-SPECIFICATION — the controller's assumed toll is WRONG "
          f"(actual stays {cost:g} bps)")
    print(f"{'arm':<14} {'lam':>6}" + "".join(f"{f'c^={c}':>10}" for c in (0, 24, 96, 384)))
    print("-" * 78)
    for mode, label in ARMS:
        for lam in LAMBDA_GRID:
            if math.isinf(lam) or lam == 0.0:
                continue
            cells = []
            for c_assumed in (0, 24, 96, 384):
                h, _ = cit_history(book_rets, n_dates, mode, lam, c_assumed)
                sc = score(h, book_rets)
                cells.append(mh._calmar(sc.net(cost)) - eq_calmar_c)
            print(f"  {label:<12} {_fmt_lam(lam):>6}" + "".join(f"{v:>+10.2f}" for v in cells))
        print("-" * 78)

    print(f"\n5. TRAIN / TEST (split {SPLIT_DATE}) — dCalmar at c={cost:g}, "
          "and netAPY on both halves")
    print(f"{'arm':<14} {'lam':>6} {'trn dCal':>9} {'tst dCal':>9} {'trn netAPY':>11} {'tst netAPY':>11}")
    print("-" * 78)
    eq_tr, eq_te = split_net(eq.net(cost), ret_dates)
    ctr, cte = mh._calmar(eq_tr), mh._calmar(eq_te)
    atr, ate = mh._apy(eq_tr), mh._apy(eq_te)
    for mode, label in ARMS:
        for lam in LAMBDA_GRID:
            s = out[(mode, lam)]["scored"]
            tr, te = split_net(s.net(cost), ret_dates)
            print(
                f"  {label:<12} {_fmt_lam(lam):>6} {mh._calmar(tr) - ctr:>+9.2f} "
                f"{mh._calmar(te) - cte:>+9.2f} "
                f"{mh._apy(tr) * 100:>10.2f}% {mh._apy(te) * 100:>10.2f}%"
            )
            out[(mode, lam)].update(
                train_dcal=mh._calmar(tr) - ctr,
                test_dcal=mh._calmar(te) - cte,
                train_apy=mh._apy(tr), test_apy=mh._apy(te),
            )
        print("-" * 78)
    print(f"  equal-weight: train netAPY {atr * 100:.2f}%  test netAPY {ate * 100:.2f}%")

    print("\n6. SIGN-GATE DECOMPOSITION — which HALF of the rule is doing the work?")
    print("   Setting the ASSUMED toll to zero leaves 'lambda * gain > 0', i.e. 'never move to")
    print("   a vector you expect to be worse'. That is a SIGNAL gate with no cost in it, and")
    print("   it is lambda-free (any lambda > 0 gives the same arm). Whatever it earns is NOT")
    print("   attributable to internalising the toll; only the remainder is.")
    print(f"{'arm':<14} {'switch':>7} {'TO/yr':>7} {'netAPY':>9} {'maxDD':>9} {'Calmar':>8} "
          f"{'dCal':>8} {'random min/med/max':>30} {'p':>7}")
    print("-" * 78)
    for mode, label in ARMS:
        hist, sw = cit_history(book_rets, n_dates, mode, 1.0, 0.0)
        s = score(hist, book_rets, sw)
        net = s.net(cost)
        d = mh._calmar(net) - eq_calmar_c
        ds = []
        for seed in CONTROL_SEEDS:
            days = random_switch_days(n_dates - 1, sw, seed)
            sc = score(scheduled_history(book_rets, n_dates, mode, days), book_rets)
            ds.append(mh._calmar(sc.net(cost)) - eq_calmar_c)
        lo, med, hi = _band(ds)
        beat = sum(1 for x in ds if x > d)
        p = (beat + 1) / (len(ds) + 1)
        print(
            f"  {label:<12} {sw:>7} {s.turnover_per_year(n_days):>7.2f} "
            f"{mh._apy(net) * 100:>8.2f}% {mh._mdd(net) * 100:>8.2f}% {mh._calmar(net):>8.2f} "
            f"{d:>+8.2f}   {lo:>+8.2f} /{med:>+8.2f} /{hi:>+8.2f} {p:>6.3f}"
        )
        out[(mode, "signgate")] = {"switches": sw, "dcal": d, "p_rand": p,
                                   "apy": mh._apy(net), "mdd": mh._mdd(net)}
    print("\n  Increment attributable to the TOLL comparison = dCal(best lambda) - dCal(sign gate):")
    for mode, label in ARMS:
        finite = [l for l in LAMBDA_GRID if not math.isinf(l) and l > 0]
        best = max(finite, key=lambda l: out[(mode, l)]["dcal"])
        inc = out[(mode, best)]["dcal"] - out[(mode, "signgate")]["dcal"]
        print(
            f"    {label:<20} best lambda={_fmt_lam(best):<5} dCal={out[(mode, best)]['dcal']:+.2f}  "
            f"sign gate={out[(mode, 'signgate')]['dcal']:+.2f}  toll adds {inc:+.2f}"
        )
    return out


# ───────────────────────────── entrypoint ────────────────────────────────────────
def main(argv: Sequence[str] = ()) -> int:
    which = argv[0] if argv else "all"
    print("#" * 78)
    print("# edge_cost_internalised_timing — CSSR + CIT")
    print("# IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0  [bt]")
    print("# capital is NOT moved; RiskPolicy v1.0 / kill-switch / live track untouched")
    print("#" * 78)

    fx_dates, fx_books = load_fixture_panel()
    if which in ("all", "anchor", "cssr"):
        print("\n\n>>> ANCHOR RUN — the FIXTURE; must reproduce #80's published table <<<\n")
        run_cssr(fx_dates, fx_books, "FIXTURE (#80 anchor)", relabel_samples=RELABEL_SAMPLES)

    real_dates: Optional[List[datetime.date]] = None
    real_books: Optional[BookRets] = None
    try:
        real_dates, real_books = load_real_panel()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"\n\n!!! REAL PANEL UNAVAILABLE: {exc}")
        print("!!! NOT falling back to the fixture — that is how #79/#80 published fixture")
        print("!!! numbers under a title that did not say so.")

    if real_books is not None and which in ("all", "cssr"):
        print("\n\n>>> CSSR — the REAL panel (answers #80's caveat (a)) <<<\n")
        run_cssr(real_dates, real_books, "REAL PANEL data/aggressive_lab")

    if which in ("all", "cit"):
        print("\n\n>>> CIT — fixture (comparable with #80) <<<\n")
        run_cit(fx_dates, fx_books, "FIXTURE")
        if real_books is not None:
            print("\n\n>>> CIT — REAL panel <<<\n")
            run_cit(real_dates, real_books, "REAL PANEL")

    print("\n" + "#" * 78)
    print("# END. Advisory only. No module built, no agent deployed, no capital moved.")
    print("#" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
