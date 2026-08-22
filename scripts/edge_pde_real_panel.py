#!/usr/bin/env python3
"""
scripts/edge_pde_real_panel.py — Ideas #71 (PDE-REAL) and #72 (PDE-DB)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads the aggressive-lab panel READ-ONLY.


WHY THIS RUN EXISTS — THE OPEN QUESTION #70 LEFT ON THE TABLE
------------------------------------------------------------
Registry idea #70 (PDE: Proportional Drawdown Exit) replaced the binary guardian snap with a
smooth linear exposure ramp and measured it on the SYNTHETIC fixture
(scripts/edge_proportional_drawdown_exit.py: constant per-book drift + three stress windows).
It reported a mixed verdict, and it named its own главную оговорку precisely:

    "фикстурный дрейф — константа вне стресс-окон; реальная vol непостоянна, и PDE
     на живых данных будет непрерывно корректировать экспозицию → издержки вырастут
     (оценка: 500–1500 бп/год против 40–160 бп/год на фикстуре), что перекроет tail-выигрыш"

and it closed with a concrete next step: add GBM noise to the fixture and re-measure.

That next step is second-best. The repo already carries the thing GBM noise would be an
imitation of: the REAL 10-book panel, data/aggressive_lab/<book>/realized_series.jsonl,
852 shared days 2024-03-06..2026-07-05, with REAL calm-period variance (per-book daily sd
ranges from 0.000% to 3.445%) and REAL crises. #70 could not use it because the session that
ran #70 worked from a worktree, and the panel is NOT git-tracked, so it was simply absent
there. This run does what #70 asked, on real data instead of synthetic noise.

THE MECHANISM IS NOT RE-IMPLEMENTED. It is imported unchanged from #70's own module
(apply_pde / apply_binary_guardian / apply_pde_portfolio / apply_binary_guardian_portfolio /
_pde_exposure / _ROUNDTRIP). Only the data changes. That is the whole point: any difference
between #70's published table and the table below is attributable to the fixture, not to a
second author's reading of the rule.


IDEA #71 — PDE-REAL: does the #70 result survive real calm-period noise?
  Same grid (d_start, d_full) ∈ {(1%,6%), (2%,8%), (3%,10%)}, same 96bp round-trip
  (canonical #10/#49), same binary-guardian baseline (derisk_dd=4%, derisk_frac=0.25,
  reenter_frac=0.5), same two modes (per-book overlay, portfolio-level overlay).

  PREDICTION RECORDED BEFORE THE RUN (registry protocol): PDE's turnover explodes once the
  drawdown series is noisy, the cost line grows by roughly an order of magnitude, and the
  portfolio-level Calmar advantage #70 published (+0.33 vs −0.25 binary, −0.16 raw) does not
  survive net of cost. Gross-vs-net is reported separately so that "it lost" can be attributed
  to the right cause instead of asserted.

  A COST-FREE ARM (roundtrip=0) is run alongside every configuration. Without it, a loss is
  ambiguous: a continuous ramp could be worse because it trades too much (a COST finding) or
  because it de-risks at the wrong moments (a TIMING finding). These are different verdicts
  and they imply different repairs.

IDEA #72 — PDE-DB: does a rebalance deadband rescue PDE?
  If #71 says "PDE is right but too expensive", the textbook repair is a deadband: move
  exposure only when the PDE target has moved at least `band` away from what is currently
  held. band=0 must reproduce #71's PDE exactly (asserted by test, both directions).

  Grid: band ∈ {0, 0.05, 0.10, 0.20, 0.33, 0.50}.

  DECISIVE CONTROL, borrowed from registry #50 (NTB): a band is only a RULE if it beats a
  RANDOM rebalance schedule OF THE SAME TRADE COUNT. #50 killed the no-trade band on exactly
  this control (random days beat the band 15–18 times out of 20 on #45). The same control runs
  here, 20 seeds, on TEST only. If the band wins only because it trades less, that is a
  FREQUENCY finding, not a timing edge, and it must be labelled as such.

HONEST LIMITS DECLARED UP FRONT
  • evidence L0 — backtest on an advisory paper panel, numbers marked [bt], never realized;
  • the panel's own books are themselves backtests (harness.py over real deep-history feeds),
    so this measures a rule on a real return SHAPE, not a realized P&L;
  • the phase="backtest" block only — the forward block re-anchors at ~$100k and diffing
    across that seam fabricates returns of −31%/−84%/+105% (fixed 2026-08-02, reused loader);
  • four TRAIN/TEST splits are reported, not one, because a single split invites the reader to
    take the best cell; the registry-canonical split (2025-06-30) is printed first;
  • no parameter here was tuned on TEST. The grids are #70's grid verbatim plus a band ladder
    that includes its own null (band=0).

stdlib-only, deterministic (seeded RNG), LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_real_panel_ensemble as RPE  # noqa: E402  real-panel loader (phase-clean, fail-CLOSED)
import edge_proportional_drawdown_exit as PDE  # noqa: E402  idea #70 mechanism, imported unchanged

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
#: Panel location. Overridable because the panel is NOT git-tracked: a session working from a
#: worktree has an empty data/ and must point at the prod tree's copy (read-only). #70 hit
#: exactly this and fell back to the fixture instead.
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

INITIAL = 100_000.0
ROUNDTRIP = PDE._ROUNDTRIP  # 0.0096 — canonical #10/#49, taken from #70 rather than restated

#: #70's grid, verbatim — including (2%, 6%), which appears only in #70's PART B but is the
#: configuration its headline positive was published on (Calmar +0.33). Omitting it would mean
#: not testing the claim actually made.
PDE_GRID: Tuple[Tuple[float, float], ...] = ((0.01, 0.06), (0.02, 0.06), (0.02, 0.08), (0.03, 0.10))
#: #72's band ladder. 0.0 is the null: it must reproduce #71 exactly.
BAND_GRID: Tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.33, 0.50)

#: Registry-canonical split first, then the other three used by #68/#69.
SPLITS: Tuple[str, ...] = ("2025-06-30", "2025-03-31", "2025-09-30", "2025-12-31")

#: The three books #70 named as "representative tails" on the fixture. Only two of the three
#: names exist on the real panel (there is no `lrt_carry`); `lrt_neutral` is its nearest
#: analogue and is labelled as a SUBSTITUTION everywhere it appears, never silently.
SEVENTY_TRIO: Tuple[str, ...] = ("susde_dn", "leverage_loop", "lrt_neutral")

PERM_SEEDS = 20


# ─────────────────────────── panel → equity series ───────────────────────────

def load_books(panel_dir: Path = PANEL_DIR) -> Tuple[List[str], Dict[str, List[float]]]:
    """(axis, {book: equity series}) on the common date axis, every book starting at $100k.

    Fail-CLOSED throughout: the loader refuses accounting seams (JUMP_REFUSE) and books with
    fewer than 60 usable points; the axis is the strict intersection across books, so no book
    is ever carried forward over a date it does not have.
    """
    panel = RPE.load_panel(panel_dir)
    axis = RPE.common_axis(panel)
    if len(axis) < 120:
        raise RuntimeError(
            f"common axis is {len(axis)} days — refusing to publish a split on it"
        )
    books: Dict[str, List[float]] = {}
    for name in sorted(panel):
        eq = [INITIAL]
        for d in axis:
            eq.append(eq[-1] * (1.0 + panel[name][d]))
        books[name] = eq
    return axis, books


def slice_books(axis: Sequence[str], books: Dict[str, List[float]],
                start: Optional[str], end: Optional[str]) -> Tuple[List[str], Dict[str, List[float]]]:
    """Restrict every book to [start, end], re-basing each to $100k at the window's first day.

    The equity lists carry one extra leading point (the $100k seed) relative to `axis`, so an
    axis index i maps to equity index i+1. Re-basing matters: a window that inherited the
    parent's peak would report a drawdown the window never lived through.
    """
    idx = [i for i, d in enumerate(axis) if (start is None or d >= start) and (end is None or d <= end)]
    if len(idx) < 2:
        raise ValueError(f"window [{start}, {end}] has {len(idx)} days — refusing")
    lo, hi = idx[0], idx[-1]
    out: Dict[str, List[float]] = {}
    for name, eq in books.items():
        seg = eq[lo: hi + 2]
        base = seg[0]
        out[name] = [v / base * INITIAL for v in seg]
    return [axis[i] for i in idx], out


# ─────────────────────────── metrics ───────────────────────────

def metrics(eq: Sequence[float], cost_paid: float, n_days: int,
            turnover: float) -> Dict[str, float]:
    """Gross and net metrics side by side. Both conventions are printed, never mixed.

    `net_apy_flat` follows #70's own convention (cumulative nominal cost subtracted from final
    equity) so the two registry entries can be compared column-to-column. It understates the
    real bill, because a cost paid on day 3 also forgoes its own compounding; `net_apy_comp`
    (from the cost-deducted path built by the overlay itself) is the honest number. Both are
    reported and the gap is named rather than quietly resolved.
    """
    eq = list(eq)
    apy = PDE._apy(eq)
    mdd = PDE._max_drawdown(eq)
    years = max(n_days / 365.0, 1e-9)
    return {
        "apy": apy,
        "maxdd": -mdd,
        "calmar": PDE._calmar(eq),
        "net_apy_flat": PDE._net_apy(eq, cost_paid),
        "cost_bp_yr": (cost_paid / INITIAL) / years * 10_000.0,
        "turn_yr": turnover / years,
    }


# ─────────────────────────── #72: deadband + controls ───────────────────────────

class OverlayRun(NamedTuple):
    """Everything one overlay pass produced, including the exposure actually HELD each day.

    The exposure path is part of the return value on purpose. Without it the deadband's one
    deliberate exception (below) is unobservable from outside, and a test for it can only look
    at equity — where a full exit from exposure 1.0 is indistinguishable from an ordinary
    band-sized move, because |0 − 1| = 1 clears every band there is. A guard that cannot fail
    is decoration, and this one nearly shipped as decoration.
    """
    equity: List[float]
    cost: float
    turnover: float
    n_trades: int
    exposure: List[float]


def _run_overlay(raw: Sequence[float], *, d_start: float, d_full: float, band: float = 0.0,
                 roundtrip: float = ROUNDTRIP, allowed: Optional[set] = None) -> OverlayRun:
    """The single overlay engine. Every #71/#72 arm is this function with different arguments.

    `band`      — deadband: move only when |target − held| >= band (#72).
    `allowed`   — if given, exposure may only change on these day indices (#50 random control).

    ONE EXCEPTION IS DELIBERATE AND IS NOT COSMETIC — the same one registry #50 had to fix for
    NTB: a target of FULL EXIT (0.0) or FULL RE-ENTRY (1.0) is executed whatever the band.
    Letting a wide band hold 40% exposure while the rule says "out" would replace a risk
    decision with a cost decision. It bites only from a PARTIAL holding (from 1.0 the move is
    delta 1.0 and clears any band on its own), which is exactly what the tests pin.

    Keeping one engine instead of three near-copies is not tidiness: three copies of this loop
    is three chances for the deadband arm, the trade counter and the random control to drift
    apart and start answering slightly different questions under the same column headers.
    """
    raw = list(raw)
    if len(raw) < 2:
        return OverlayRun(raw, 0.0, 0.0, 0, [1.0] * len(raw))
    guarded: List[float] = [raw[0]]
    exposures: List[float] = [1.0]
    peak = raw[0]
    exposure = 1.0
    total_cost = 0.0
    turnover = 0.0
    n_trades = 0
    for i in range(1, len(raw)):
        raw_ret = raw[i] / raw[i - 1] - 1.0 if raw[i - 1] > 0 else 0.0
        new_eq = guarded[-1] * (1.0 + raw_ret * exposure)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = (peak - new_eq) / peak if peak > 0 else 0.0
        if allowed is None or i in allowed:
            target = PDE._pde_exposure(dd, d_start, d_full)
            delta = abs(target - exposure)
            forced = target <= 1e-12 or target >= 1.0 - 1e-12
            if delta > 1e-9 and (delta >= band or forced):
                total_cost += delta * roundtrip * new_eq
                turnover += delta
                n_trades += 1
                exposure = target
        exposures.append(exposure)
    return OverlayRun(guarded, total_cost, turnover, n_trades, exposures)


def apply_pde_deadband(raw: Sequence[float], *, d_start: float, d_full: float,
                       band: float = 0.0, roundtrip: float = ROUNDTRIP,
                       ) -> Tuple[List[float], float, float]:
    """PDE with a rebalance deadband. Returns (gross_equity, cost_paid, turnover).

    band=0.0 reproduces #70's apply_pde exactly (asserted by test on three series shapes and
    the whole grid): a target that has not moved produces delta 0, and 0 >= 0 changes nothing.
    """
    run = _run_overlay(raw, d_start=d_start, d_full=d_full, band=band, roundtrip=roundtrip)
    return run.equity, run.cost, run.turnover


def exposure_path(raw: Sequence[float], *, d_start: float, d_full: float,
                  band: float = 0.0) -> List[float]:
    """The exposure actually held on each day — what the deadband exception is a claim about."""
    return _run_overlay(raw, d_start=d_start, d_full=d_full, band=band).exposure


def apply_pde_random_schedule(raw: Sequence[float], *, d_start: float, d_full: float,
                              n_trades: int, seed: int, roundtrip: float = ROUNDTRIP,
                              ) -> Tuple[List[float], float, float]:
    """CONTROL for #72: the same PDE target, executed on RANDOM days of the same count.

    This is registry #50's decisive control. If a deadband is a timing rule, it must beat a
    random schedule that trades as often. If it does not, the finding is FREQUENCY, not timing.
    The control runs at band=0 — the band is the thing under test, so the control must not
    carry it (and at band=0 the full-exit exception is inert, changing nothing).
    """
    raw = list(raw)
    if len(raw) < 2:
        return raw, 0.0, 0.0
    rng = random.Random(seed)
    days = list(range(1, len(raw)))
    n_trades = max(0, min(n_trades, len(days)))
    allowed = set(rng.sample(days, n_trades)) if n_trades else set()
    run = _run_overlay(raw, d_start=d_start, d_full=d_full, band=0.0, roundtrip=roundtrip,
                       allowed=allowed)
    return run.equity, run.cost, run.turnover


# ─────────────────────────── portfolio plumbing ───────────────────────────

def portfolio_returns(books: Dict[str, List[float]]) -> List[float]:
    """Equal-weight daily returns of the panel (the series every portfolio overlay drives).

    Fail-CLOSED on a ragged panel. The real panel is built on a strict date intersection so the
    lengths always agree, but taking the length from one arbitrary book and indexing the rest
    with it is fail-OPEN by construction: depending on which book sorts first it either raises
    or silently truncates every other book, and a silent truncation is a fabricated portfolio.
    """
    names = sorted(books)
    if not names:
        raise ValueError("empty panel — refusing to build a portfolio out of nothing")
    lengths = {len(books[b]) for b in names}
    if len(lengths) != 1:
        raise ValueError(
            f"ragged panel: book lengths {sorted(lengths)} — refusing to align them by "
            f"truncation; the caller must hand in a common axis"
        )
    n = len(books[names[0]])
    out: List[float] = []
    for i in range(1, n):
        rets = [(books[b][i] / books[b][i - 1] - 1.0) if books[b][i - 1] > 0 else 0.0
                for b in names]
        out.append(sum(rets) / len(names))
    return out


def equity_from_returns(rets: Sequence[float]) -> List[float]:
    eq = [INITIAL]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def per_book_overlay(books: Dict[str, List[float]], fn) -> Tuple[List[float], float, float]:
    """Apply a single-book overlay to every book, then equal-weight the guarded books.

    Returns (portfolio_equity, total_cost, total_turnover). This is #70's "mode A" wiring:
    the overlay decides per book, and the portfolio is the average of what survives.
    """
    names = sorted(books)
    guarded: Dict[str, List[float]] = {}
    total_cost = 0.0
    total_turn = 0.0
    for b in names:
        res = fn(books[b])
        eq, cost = res[0], res[1]
        turn = res[2] if len(res) > 2 else 0.0
        guarded[b] = eq
        total_cost += cost / len(names)
        total_turn += turn / len(names)
    return equity_from_returns(portfolio_returns(guarded)), total_cost, total_turn


# ─────────────────────────── #71 runner ───────────────────────────

def _binary_turnover(raw: Sequence[float], *, derisk_dd: float = 0.04,
                     derisk_frac: float = 0.25, reenter_frac: float = 0.5) -> float:
    """Turnover of #70's binary guardian, recomputed by replaying its own transitions.

    #70's function returns cost but not turnover; deriving turnover from cost would be circular
    when the two arms use different round-trips (the cost-free arm has cost 0 by construction).
    """
    raw = list(raw)
    if len(raw) < 2:
        return 0.0
    guarded = [raw[0]]
    peak, exposure, turn = raw[0], 1.0, 0.0
    for i in range(1, len(raw)):
        raw_ret = raw[i] / raw[i - 1] - 1.0 if raw[i - 1] > 0 else 0.0
        new_eq = guarded[-1] * (1.0 + raw_ret * exposure)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = new_eq / peak - 1.0
        prev = exposure
        if exposure >= 1.0 and dd <= -derisk_dd:
            exposure = derisk_frac
        elif exposure < 1.0 and new_eq >= peak * (1.0 - derisk_dd * (1.0 - reenter_frac)):
            exposure = 1.0
        turn += abs(exposure - prev)
    return turn


def run_idea71(books: Dict[str, List[float]], *, roundtrip: float = ROUNDTRIP
               ) -> Dict[str, Dict[str, float]]:
    """#70's whole table, mechanism imported unchanged, on whatever panel is handed in.

    `roundtrip=0.0` gives the cost-free arm that separates a COST finding from a TIMING one.
    """
    n_days = len(next(iter(books.values()))) - 1
    out: Dict[str, Dict[str, float]] = {}

    raw_eq = equity_from_returns(portfolio_returns(books))
    out["raw equal-weight"] = metrics(raw_eq, 0.0, n_days, 0.0)

    bin_pb, bin_cost, bin_turn = per_book_overlay(
        books,
        lambda eq: (*PDE.apply_binary_guardian(eq, roundtrip=roundtrip), _binary_turnover(eq)),
    )
    out["binary guardian per-book"] = metrics(bin_pb, bin_cost, n_days, bin_turn)

    for d0, d1 in PDE_GRID:
        eq, cost, turn = per_book_overlay(
            books,
            lambda e, a=d0, b=d1: apply_pde_deadband(e, d_start=a, d_full=b, band=0.0,
                                                     roundtrip=roundtrip),
        )
        out[f"PDE per-book {d0:.0%}-{d1:.0%}"] = metrics(eq, cost, n_days, turn)

    port_eq, port_cost = PDE.apply_binary_guardian_portfolio(books, roundtrip=roundtrip)
    port_turn = _binary_turnover(equity_from_returns(portfolio_returns(books)))
    out["binary guardian portfolio"] = metrics(port_eq, port_cost, n_days, port_turn)

    raw_port = equity_from_returns(portfolio_returns(books))
    for d0, d1 in PDE_GRID:
        eq, cost, turn = apply_pde_deadband(raw_port, d_start=d0, d_full=d1, band=0.0,
                                            roundtrip=roundtrip)
        out[f"PDE portfolio {d0:.0%}-{d1:.0%}"] = metrics(eq, cost, n_days, turn)
    return out


def parity_with_seventy(raw: Sequence[float], *, d_start: float, d_full: float) -> bool:
    """True when the deadband at band=0 is byte-identical to #70's own apply_pde.

    Guards the claim this whole entry rests on: 'the mechanism did not change, the data did'.
    """
    a_eq, a_cost = PDE.apply_pde(list(raw), d_start=d_start, d_full=d_full)
    b_eq, b_cost, _ = apply_pde_deadband(raw, d_start=d_start, d_full=d_full, band=0.0)
    if len(a_eq) != len(b_eq) or abs(a_cost - b_cost) > 1e-9:
        return False
    return all(abs(x - y) <= 1e-9 for x, y in zip(a_eq, b_eq))


# ─────────────────────────── #72 runner ───────────────────────────

def run_idea72(books: Dict[str, List[float]], *, d_start: float, d_full: float,
               seeds: int = PERM_SEEDS) -> Dict[str, Dict[str, float]]:
    """Band ladder on the portfolio series + the #50 random-schedule control at matched count."""
    raw_port = equity_from_returns(portfolio_returns(books))
    n_days = len(raw_port) - 1
    out: Dict[str, Dict[str, float]] = {}
    out["raw (no overlay)"] = metrics(raw_port, 0.0, n_days, 0.0)
    for band in BAND_GRID:
        eq, cost, turn = apply_pde_deadband(raw_port, d_start=d_start, d_full=d_full, band=band)
        m = metrics(eq, cost, n_days, turn)
        # Trade COUNT (not turnover) is what the random control has to match.
        m["n_trades"] = float(_count_trades(raw_port, d_start=d_start, d_full=d_full, band=band))
        out[f"band {band:.2f}"] = m

        rand_net: List[float] = []
        for s in range(seeds):
            r_eq, r_cost, _ = apply_pde_random_schedule(
                raw_port, d_start=d_start, d_full=d_full,
                n_trades=int(m["n_trades"]), seed=1000 + s,
            )
            rand_net.append(PDE._net_apy(r_eq, r_cost))
        rand_net.sort()
        beat = sum(1 for v in rand_net if v >= m["net_apy_flat"])
        out[f"band {band:.2f}"]["rand_median"] = rand_net[len(rand_net) // 2]
        out[f"band {band:.2f}"]["rand_beat"] = float(beat)
        out[f"band {band:.2f}"]["p_rand"] = (beat + 1) / (seeds + 1)
    return out


def _count_trades(raw: Sequence[float], *, d_start: float, d_full: float, band: float) -> int:
    """Trade COUNT (not turnover) — what the #50 random control has to match."""
    return _run_overlay(raw, d_start=d_start, d_full=d_full, band=band).n_trades


def loo_per_book(books: Dict[str, List[float]], *, d_start: float, d_full: float
                 ) -> Dict[str, Dict[str, float]]:
    """Leave-one-out: per-book PDE minus per-book binary guardian, dropping each book in turn.

    The registry's own standard control (#40, #69). It exists because this panel has a
    documented law-of-one-book (#68/#69: `eth_directional` in or out of a list flips the
    verdict across 36 cells with zero exceptions). A per-book overlay result that survives only
    while one book is present is a statement about that book, not about the overlay.
    """
    names = sorted(books)
    out: Dict[str, Dict[str, float]] = {}
    for drop in ["<none>"] + names:
        sub = {b: eq for b, eq in books.items() if b != drop}
        if len(sub) < 2:
            continue
        n_days = len(next(iter(sub.values()))) - 1
        pde_eq, pde_cost, pde_turn = per_book_overlay(
            sub, lambda e: apply_pde_deadband(e, d_start=d_start, d_full=d_full, band=0.0))
        bin_eq, bin_cost, bin_turn = per_book_overlay(
            sub, lambda e: (*PDE.apply_binary_guardian(e), _binary_turnover(e)))
        p = metrics(pde_eq, pde_cost, n_days, pde_turn)
        b = metrics(bin_eq, bin_cost, n_days, bin_turn)
        out[drop] = {
            "pde_calmar": p["calmar"], "bin_calmar": b["calmar"],
            "d_calmar": p["calmar"] - b["calmar"],
            "pde_net": p["net_apy_flat"], "bin_net": b["net_apy_flat"],
            "d_net": p["net_apy_flat"] - b["net_apy_flat"],
            "pde_dd": p["maxdd"], "bin_dd": b["maxdd"],
        }
    return out


def worst_dd_books(books: Dict[str, List[float]], k: int = 3) -> List[str]:
    """The k books with the deepest drawdown over the window handed in (used TRAIN-only).

    #70 picked its three 'tail' books by construction of the fixture. On the real panel the
    equivalent choice has to be MADE, and made causally, or the trio is a lookahead.
    """
    scored = [(PDE._max_drawdown(eq), b) for b, eq in books.items()]
    scored.sort(reverse=True)
    return sorted(b for _, b in scored[:k])


# ─────────────────────────── reporting ───────────────────────────

def _row(name: str, m: Dict[str, float]) -> str:
    return (f"| {name:<30} | {m['apy'] * 100:7.2f}% | {m['maxdd'] * 100:7.2f}% | "
            f"{m['calmar']:7.2f} | {m['net_apy_flat'] * 100:7.2f}% | "
            f"{m['cost_bp_yr']:8.1f} | {m['turn_yr']:6.2f} |")


def _table(title: str, rows: Dict[str, Dict[str, float]]) -> None:
    print(f"\n{title}")
    print(f"| {'конфигурация':<30} | {'APY':>8} | {'maxDD':>8} | {'Calmar':>7} | "
          f"{'netAPY':>8} | {'бп/год':>8} | {'turn':>6} |")
    print(f"|{'-' * 32}|{'-' * 10}|{'-' * 10}|{'-' * 9}|{'-' * 10}|{'-' * 10}|{'-' * 8}|")
    for k, v in rows.items():
        print(_row(k, v))


def main() -> None:
    print("=" * 108)
    print("Idea #71 PDE-REAL / #72 PDE-DB — #70's mechanism, imported unchanged, on the REAL panel")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence L0 [bt]  — capital is never moved")
    print("=" * 108)

    axis, books = load_books()
    print(f"\nПанель: {len(books)} книг, {len(axis)} общих дней {axis[0]}..{axis[-1]} "
          f"(phase=backtest блок, шов НЕ пересечён)")

    ok = all(parity_with_seventy(books["leverage_loop"], d_start=a, d_full=b) for a, b in PDE_GRID)
    print(f"Паритет с #70 (band=0 ≡ apply_pde) на всех {len(PDE_GRID)} конфигурациях: "
          f"{'ДА' if ok else 'НЕТ — вердикт ниже НЕДЕЙСТВИТЕЛЕН'}")
    if not ok:
        raise SystemExit(2)

    for split in SPLITS:
        tr_axis, tr_books = slice_books(axis, books, None, split)
        te_axis, te_books = slice_books(axis, books, split, None)
        tag = " (сплит реестра)" if split == SPLITS[0] else ""
        print("\n" + "=" * 108)
        print(f"СПЛИТ {split}{tag} — TRAIN {len(tr_axis)} д. / TEST {len(te_axis)} д.")
        print("=" * 108)

        _table(f"#71 · ПОЛНАЯ ПАНЕЛЬ 10 книг · TEST · с издержками 96бп [bt]",
               run_idea71(te_books))
        _table(f"#71 · ПОЛНАЯ ПАНЕЛЬ 10 книг · TEST · БЕЗ издержек (арм-контроль) [bt]",
               run_idea71(te_books, roundtrip=0.0))

        trio = worst_dd_books(tr_books, 3)
        te_trio = {b: te_books[b] for b in trio}
        print(f"\nПричинное трио (3 худшие по просадке НА TRAIN): {', '.join(trio)}")
        _table(f"#71 · причинное трио · TEST · с издержками [bt]", run_idea71(te_trio))

        named = {b: te_books[b] for b in SEVENTY_TRIO if b in te_books}
        missing = [b for b in SEVENTY_TRIO if b not in te_books]
        note = f"  (ЗАМЕНА: lrt_carry на панели НЕТ; отсутствуют: {missing})" if missing else \
               "  (lrt_neutral ЗАМЕНЯЕТ фикстурный lrt_carry — его на панели нет)"
        _table(f"#71 · трио #70 по именам · TEST · с издержками [bt]{note}", run_idea71(named))

        print(f"\n#71 · LOO-КОНТРОЛЬ: per-book PDE 1%-6% МИНУС per-book binary · TEST · "
              f"выбрасываем по одной книге [bt]")
        print(f"| {'выброшена':<20} | {'PDE Calmar':>10} | {'bin Calmar':>10} | {'ΔCalmar':>8} | "
              f"{'PDE net':>8} | {'bin net':>8} | {'Δnet':>7} |")
        print(f"|{'-' * 22}|{'-' * 12}|{'-' * 12}|{'-' * 10}|{'-' * 10}|{'-' * 10}|{'-' * 9}|")
        for drop, m in loo_per_book(te_books, d_start=0.01, d_full=0.06).items():
            print(f"| {drop:<20} | {m['pde_calmar']:10.2f} | {m['bin_calmar']:10.2f} | "
                  f"{m['d_calmar']:+8.2f} | {m['pde_net'] * 100:7.2f}% | "
                  f"{m['bin_net'] * 100:7.2f}% | {m['d_net'] * 100:+6.2f}pp |")

        if split == SPLITS[0]:
            print("\n" + "-" * 108)
            print(f"#72 · ЛЕСТНИЦА МЁРТВОЙ ЗОНЫ поверх PDE 2%-8% · TEST · "
                  f"контроль #50: случайное расписание той же частоты, {PERM_SEEDS} сидов")
            print("-" * 108)
            rows = run_idea72(te_books, d_start=0.02, d_full=0.08)
            print(f"| {'конфигурация':<16} | {'netAPY':>8} | {'maxDD':>8} | {'Calmar':>7} | "
                  f"{'сделок':>7} | {'медиана случ.':>13} | {'бьют':>5} | {'p':>5} |")
            print(f"|{'-' * 18}|{'-' * 10}|{'-' * 10}|{'-' * 9}|{'-' * 9}|{'-' * 15}|{'-' * 7}|{'-' * 7}|")
            for k, m in rows.items():
                if "rand_median" not in m:
                    print(f"| {k:<16} | {m['net_apy_flat'] * 100:7.2f}% | {m['maxdd'] * 100:7.2f}% | "
                          f"{m['calmar']:7.2f} | {'—':>7} | {'—':>13} | {'—':>5} | {'—':>5} |")
                    continue
                print(f"| {k:<16} | {m['net_apy_flat'] * 100:7.2f}% | {m['maxdd'] * 100:7.2f}% | "
                      f"{m['calmar']:7.2f} | {int(m['n_trades']):7d} | "
                      f"{m['rand_median'] * 100:12.2f}% | {int(m['rand_beat']):3d}/{PERM_SEEDS} | "
                      f"{m['p_rand']:5.3f} |")

    print("\n" + "=" * 108)
    print("Все числа [bt], evidence L0. Капитал не двигался, RiskPolicy v1.0 и трек не тронуты.")
    print("=" * 108)


if __name__ == "__main__":
    main()
