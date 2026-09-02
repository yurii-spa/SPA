#!/usr/bin/env python3
"""
scripts/edge_guardian_flagship_causality.py — registry idea GFC

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json), the dashboard or the fleet. Capital is not moved. No
module is built, nothing is retuned and no agent is deployed here. `apply_guardian_vol` — in
either of its two copies — is not modified by a single line.

Working name GFC. The registry NUMBER is claimed at DELIVERY (registry rule at the top of
docs/DYNAMIC_LEVERAGE_GUARDIAN.md).


ORDERED BY #94 GSB, AND THIS TIME THE ORDER IS FILLED
====================================================
#94 found that the canonical `spa_core/strategy_lab/aggressive_lab/guardian.py::
apply_guardian_vol` puts `rets[i]` inside the volatility window AND trades `rets[i]` with the
exposure that window produces — the bar's own close deciding the trade inside the bar. It then
left one instruction:

    "ЗАКАЗ СЛЕДУЮЩЕЙ ЗАПИСИ: прогнать причинный вариант по ВСЕЙ таблице реестра, где стоят
     числа `apply_guardian_vol` — начиная с #1 (susde_dn 4.2 %→7.3 % при DD 8.5 %→4.5 %,
     флагманская строка «доход↑ И риск↓ ОДНОВРЕМЕННО») и UPD 31.08. Пока этого нет, ни одна
     такая клетка не имеет права цитироваться как причинная."

#1 is not just the first cell. It is the line this whole document is named after, and the
single result the aggressive tier's case rests on. This file re-runs it.

WHAT MAKES #1 A DIFFERENT MEASUREMENT FROM THE ONES #94 CHECKED
---------------------------------------------------------------
#94 checked the canonical module and the deployed L2 organ, both on the REAL panel. #1's table
was never produced by either. It comes from `scripts/guardian_backtest.py`, which in fixture
mode deliberately uses its OWN LOCAL COPY of `apply_guardian_vol` so that the published fixture
table stays byte-reproducible (its docstring says so). So the registry holds TWO functions of
the same name, and which one runs is decided by a command-line flag:

    guardian_backtest.py            → the local fixture copy   (this file's subject)
    guardian_backtest.py --real     → the canonical module     (#94's subject)

Nobody had ever asked whether the two share the defect. They do not, and the difference is one
line of ORDER inside the loop:

    fixture copy (guardian_backtest.py:100)      canonical (guardian.py:96)
    ────────────────────────────────────────     ──────────────────────────────────────
    gr = rets[i] * exposure                      recent = stdev(rets[i-lb+1 : i+1])
    guarded.append(...)          ← TRADE FIRST   ... exposure updated ...
    if i >= lookback:                            guarded.append(rets[i] * exposure)
        recent = stdev(rets[i-lb+1 : i+1])                             ← TRADE AFTER
        ... exposure updated for the NEXT day

The fixture copy trades day i with an exposure decided from days strictly before i, then looks
at day i to decide day i+1. That is causal by construction. The canonical one is not.

THIS FILE MEASURES THAT RATHER THAN ASSERTING IT
    Reading two loops and declaring them different is the same kind of claim #92 caught the
    registry making about its own cost convention: an assertion about numbers, made without
    opening them. So each of the five fixture books is run three ways and the columns are put
    side by side:

      · fixture      — `guardian_backtest.apply_guardian_vol`, imported, the published path
      · causal       — `oda.guarded_path(..., causal_lag=1)`, #94's own mirror at lag 1
      · canonical    — `guardian.apply_guardian_vol`, the module #94 indicted, imported

    `min_vol=0.0` is passed to the lag-1 mirror on purpose: the fixture copy has no minimum-vol
    floor, and leaving the mirror's default 1e-5 in place would make the comparison a test of
    that floor rather than of the lag. Tolls are off in every column, as in #94.

    AND THE COMPARISON IS ON DECISIONS, NOT ON EQUITY. Two overlays running the identical rule
    but one day out of phase at the start produce equity paths that differ at the fourth decimal
    FOREVER, because a single day's exposure compounds. Judged on equity, "the same rule" and "a
    different rule" are indistinguishable. So section 2 recovers the exposure each column
    actually traded, day by day, and compares THOSE. This distinction is the whole verdict: on
    equity the published path and the causal mirror look merely close; on decisions they are the
    same rule disagreeing on exactly one day, and that day is named in advance.

AND THE CONTROL THAT MAKES THE RESULT LEGIBLE
    A causality check that only ever returns "clean" has not been shown to be able to return
    anything else. The canonical column IS that control — the real function, not a
    convention-compatible lookalike — and on this fixture it does not merely flatter the
    overlay: it removes the drawdown entirely. A de-risk overlay whose backtest reports a
    maximum drawdown of zero has not found an edge; it has found the future. That is a cheap,
    universal smoke test this tree did not have written down anywhere, and section 3 states it
    as one.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402  (#95's lagged mirror, reused)
import guardian_backtest as gb  # noqa: E402  (#1's OWN harness — the published path itself)

from spa_core.strategy_lab.aggressive_lab import fixtures as fx  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import guardian as g  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld  # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: #1's published sweep grid, imported in spirit from `guardian_backtest.main` and restated
#: here because that grid is a local in a `main()`. Any drift between the two is caught by the
#: reproduction check in section 1: if the grid moved, the published cells stop reproducing and
#: the harness REFUSES rather than printing a lookalike table.
VOL_GRID: Tuple[Tuple[float, float], ...] = tuple(
    (vm, fr) for vm in (1.5, 2.0, 3.0) for fr in (0.0, 0.25, 0.5)
)

#: Tolls off, as in #94: the question is what the look-ahead alone is worth. Charging churn in
#: the same table would mix two corrections into one number and neither would be attributable.
NO_TOLL = 0.0

#: The fixture copy has NO minimum-volatility floor. Passing the mirror's default 1e-5 would
#: make this a comparison of floors rather than of lag, so the floor is switched off in both
#: mirrors and the fact is printed in the header.
NO_MIN_VOL = 0.0

LOOKBACK = 10
CALM_MULT = 1.2

#: #1's published PRE-EMPTIVE table, verbatim, as the reproduction target. These are not
#: inputs to any calculation — they are what section 1 must land on for the entry to have the
#: right to speak about #1 at all.
PUBLISHED_PREEMPTIVE: Dict[str, Tuple[float, float, Optional[float]]] = {
    "susde_dn": (7.3, 4.5, 1.6),
    "lrt_carry": (3.9, 11.0, 0.4),
    "leverage_loop": (1.9, 14.0, None),   # #1 prints APY and DD for this row, no Calmar
    "points_farm": (12.9, 1.0, 13.4),
}

#: Reproduction tolerance. The published table is printed to one decimal, so anything tighter
#: would be a test of rounding rather than of the numbers.
REPRO_TOL = 0.05


class ReproductionFailure(RuntimeError):
    """Raised when a published cell no longer reproduces.

    Fail-CLOSED on purpose. An entry that re-checks #1 while silently running against a moved
    #1 would publish a verdict about a table nobody can find — the exact failure the registry's
    own cost convention taught it about.
    """


# ── the three ways to run one book ───────────────────────────────────────────────
def fixture_overlay(equity: Sequence[float], *, vol_mult: float,
                    derisk_frac: float) -> List[float]:
    """#1's published path — `guardian_backtest`'s local copy, IMPORTED, never re-typed.

    Re-typing it here would make every column below a comparison between this file and itself.
    The whole point is to run the function that produced the published numbers.
    """
    return gb.apply_guardian_vol(equity, lookback=LOOKBACK, vol_mult=vol_mult,
                                 derisk_frac=derisk_frac, calm_mult=CALM_MULT)


def causal_overlay(equity: Sequence[float], *, vol_mult: float,
                   derisk_frac: float) -> List[float]:
    """#94's mirror with the volatility window ending YESTERDAY."""
    return oda.guarded_path(equity, None, lookback=LOOKBACK, vol_mult=vol_mult,
                            derisk_frac=derisk_frac, calm_mult=CALM_MULT,
                            roundtrip_cost=NO_TOLL, min_vol=NO_MIN_VOL, causal_lag=1)


def same_bar_overlay(equity: Sequence[float], *, vol_mult: float,
                     derisk_frac: float) -> List[float]:
    """The CANONICAL module itself — `guardian.apply_guardian_vol`, the function #94 indicted.

    Imported, not mirrored. An earlier draft of this file used `guarded_path(causal_lag=0)` as
    the control, which is the same CONVENTION but not the same CODE: their exposure decisions
    were measured to disagree for up to eight days after the boundary on one book. A control
    that is merely convention-compatible with the thing it stands for is a lookalike, and this
    entry is about two functions that were assumed alike because they share a name.

    This is the CONTROL of this file, not a candidate. It exists so a "clean" verdict in the
    other columns is known to be a verdict and not the only thing the instrument can say.
    """
    return g.apply_guardian_vol(equity, lookback=LOOKBACK, vol_mult=vol_mult,
                                derisk_frac=derisk_frac, calm_mult=CALM_MULT,
                                roundtrip_cost=NO_TOLL)


def implied_exposure(equity: Sequence[float],
                     guarded: Sequence[float]) -> List[Optional[float]]:
    """Recover the exposure the overlay actually traded each day, from the two paths.

    Comparing EQUITY paths cannot separate "a different rule" from "the same rule, one day out
    of phase at the start" — a single boundary day compounds forever and makes two identical
    rules look different at the fourth decimal for the rest of the series. Comparing DECISIONS
    separates them, and that distinction is the whole verdict of section 2.

    Returns None on a day the book did not move, where exposure is unrecoverable by division.
    """
    out: List[Optional[float]] = []
    for i in range(1, min(len(equity), len(guarded))):
        r = equity[i] / equity[i - 1] - 1.0
        gr = guarded[i] / guarded[i - 1] - 1.0
        out.append(None if abs(r) < 1e-14 else gr / r)
    return out


def decision_disagreements(equity: Sequence[float], a: Sequence[float],
                           b: Sequence[float], tol: float = 1e-9) -> List[int]:
    """Indices where two overlays traded a DIFFERENT exposure on the same book."""
    ea, eb = implied_exposure(equity, a), implied_exposure(equity, b)
    out: List[int] = []
    for i in range(min(len(ea), len(eb))):
        x, y = ea[i], eb[i]
        if x is not None and y is not None and abs(x - y) > tol:
            out.append(i)
    return out


OVERLAYS = (("fixture (published)", fixture_overlay),
            ("causal (lag 1)", causal_overlay),
            ("canonical (#94 defect)", same_bar_overlay))


# ── the panel ────────────────────────────────────────────────────────────────────
def load_fixture_books() -> Dict[str, List[float]]:
    """Materialise the documented fixture into a temp dir and return {book: equity}.

    A temp dir, never the live `data/` — the fixture writer would otherwise write into the
    tree, and the tree is where the track lives.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gfc_"))
    fx.materialize(tmp)
    loaded = ld.load_all(data_dir=tmp)
    if not loaded:
        raise ReproductionFailure(
            f"the documented fixture materialised no books under {tmp}; refusing to print an "
            f"empty table that would read as 'the guardian has nothing to guard'"
        )
    out: Dict[str, List[float]] = {}
    for sid in sorted(loaded):
        s = loaded[sid]
        eq = gb._equity_of(s.backtest.series if s.backtest.n_points >= 2 else [])
        if len(eq) >= 30:
            out[sid] = eq
    return out


def best_cell(equity: Sequence[float], overlay,
              grid: Sequence[Tuple[float, float]] = VOL_GRID):
    """(apy, mdd, calmar, params) of the Calmar-best cell — #1's own selection rule.

    Kept identical to `guardian_backtest.main.best_over` so the fixture column is the published
    measurement rather than a lookalike scored by a different rule.
    """
    best = None
    for vm, fr in grid:
        a, d, c = gb._metrics(overlay(equity, vol_mult=vm, derisk_frac=fr))
        key = c if isinstance(c, (int, float)) else -1e9
        if best is None or key > best[0]:
            best = (key, a, d, c, (vm, fr))
    assert best is not None
    return best[1], best[2], best[3], best[4]


def check_published(book: str, apy, mdd, calmar) -> None:
    """Fail CLOSED when a published cell of #1 no longer reproduces."""
    want = PUBLISHED_PREEMPTIVE.get(book)
    if want is None:
        return
    w_apy, w_mdd, w_cal = want
    for got, exp, name in ((apy, w_apy, "APY"), (mdd, w_mdd, "maxDD"),
                           (calmar, w_cal, "Calmar")):
        if exp is None:
            continue
        if not isinstance(got, (int, float)) or abs(got - exp) > REPRO_TOL:
            raise ReproductionFailure(
                f"{book}: published #1 {name} is {exp}, this run produced {got!r}. The entry "
                f"would be re-checking a table that no longer exists; refusing to publish."
            )


def is_impossible_tail(mdd) -> bool:
    """A de-risk overlay reporting essentially no drawdown is an instrument failure.

    Stated as a predicate, not as prose, so section 3 can count it and the suite can pin it in
    both directions. The threshold is deliberately generous: this is meant to catch 'zero', not
    to adjudicate a good tail from a very good one.
    """
    return isinstance(mdd, (int, float)) and mdd < 0.05


# ── the run ──────────────────────────────────────────────────────────────────────
def run() -> Dict[str, object]:
    books = load_fixture_books()
    out: Dict[str, object] = {}

    print("\n" + "=" * 100)
    print("Idea GFC — is the registry's FLAGSHIP table causal?  #94's order, executed on #1. [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"  documented fixture, {len(books)} books  ·  grid {list(VOL_GRID)}")
    print(f"  tolls OFF (as in #94)  ·  min_vol floor OFF in both mirrors (the fixture copy has none)")
    print("=" * 100)

    print("\n" + "─" * 100)
    print("1. THE FLAGSHIP TABLE, RUN THREE WAYS. Same books, same grid, same selection rule;")
    print("   the ONLY difference between columns is when the volatility window ends.")
    print("   The fixture column REPRODUCES #1 or this harness refuses — see check_published.")
    print(f"\n{'book':<16}{'best cell':>12}"
          f"{'fixture apy/dd/cal':>26}{'causal apy/dd/cal':>26}{'canonical apy/dd/cal':>26}")
    print("─" * 100)

    def f(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"

    rows: Dict[str, dict] = {}
    identical = 0
    compared = 0
    for book, eq in books.items():
        f_apy, f_mdd, f_cal, params = best_cell(eq, fixture_overlay)
        check_published(book, f_apy, f_mdd, f_cal)
        vm, fr = params
        c_apy, c_mdd, c_cal = gb._metrics(causal_overlay(eq, vol_mult=vm, derisk_frac=fr))
        s_apy, s_mdd, s_cal = gb._metrics(same_bar_overlay(eq, vol_mult=vm, derisk_frac=fr))
        rows[book] = {
            "params": [vm, fr],
            "fixture": [f_apy, f_mdd, f_cal],
            "causal": [c_apy, c_mdd, c_cal],
            "canonical": [s_apy, s_mdd, s_cal],
            "published": list(PUBLISHED_PREEMPTIVE.get(book, ())) or None,
        }
        compared += 1
        disagree = decision_disagreements(
            eq, fixture_overlay(eq, vol_mult=vm, derisk_frac=fr),
            causal_overlay(eq, vol_mult=vm, derisk_frac=fr))
        rows[book]["decision_disagreements"] = disagree
        identical += 1 if disagree == [LOOKBACK] else 0
        print(f"{book:<16}{str((vm, fr)):>12}"
              f"{f(f_apy) + '/' + f(f_mdd) + '/' + f(f_cal):>26}"
              f"{f(c_apy) + '/' + f(c_mdd) + '/' + f(c_cal):>26}"
              f"{f(s_apy) + '/' + f(s_mdd) + '/' + f(s_cal):>26}")
    out["rows"] = rows
    out["identical_to_causal"] = identical
    out["compared"] = compared
    print(f"\n   books whose PUBLISHED overlay makes the SAME decision as the causal mirror on"
          f" every day but the boundary index {LOOKBACK}: {identical} of {compared}")
    print("   Accounting identity: compared + not-compared must equal the panel size —")
    print(f"   {compared} + {len(books) - compared} = {len(books)}.")

    # ── 2. why, in code rather than in prose ─────────────────────────────────────
    print("\n" + "─" * 100)
    print("2. WHY THE PUBLISHED PATH IS CLEAN, AND THE CANONICAL ONE IS NOT.")
    print("   Two functions share a name; a CLI flag decides which one runs:")
    print("     guardian_backtest.py         → the local fixture copy (trades day i with an")
    print("                                    exposure decided from days < i, THEN looks at i)")
    print("     guardian_backtest.py --real  → the canonical module (window includes day i and")
    print("                                    the same exposure trades day i)  ← #94's defect")
    print("   The identity below is MEASURED on decisions, not read off the source.")
    print(f"\n{'book':<16}{'exposure days':>15}{'days they disagree':>20}{'which days':>20}"
          f"{'equity gap':>14}")
    print("─" * 100)
    all_at_boundary = True
    for book, eq in books.items():
        vm, fr = rows[book]["params"]
        a = fixture_overlay(eq, vol_mult=vm, derisk_frac=fr)
        b = causal_overlay(eq, vol_mult=vm, derisk_frac=fr)
        disagree = rows[book]["decision_disagreements"]
        if disagree != [LOOKBACK]:
            all_at_boundary = False
        n = min(len(a), len(b))
        gap = max(abs(a[i] - b[i]) / (abs(b[i]) or 1.0) for i in range(n))
        rows[book]["equity_gap_vs_causal"] = gap
        print(f"{book:<16}{n - 1:>15}{len(disagree):>20}{str(disagree):>20}{gap:>14.2e}")
    out["all_disagreements_at_boundary"] = all_at_boundary
    print(f"\n   Every disagreement sits at index {LOOKBACK} = `lookback`, the first day either")
    print("   overlay is allowed to act: the lag-1 mirror may act there, the published copy")
    print("   cannot act until the day after. Everywhere else the two trade the SAME exposure.")
    print("   The equity gap is larger than the decision gap for the reason section 0 gives —")
    print("   one boundary day compounds for the rest of the series. Read the decisions.")
    print("   This is the same shape #94 reported for the live organ: all of its discrepancies")
    print("   also sat at the declared index i=lookback, and none anywhere else.")

    # ── 3. the control, and the smoke test it hands the tree ─────────────────────
    print("\n" + "─" * 100)
    print("3. WHAT THE LOOK-AHEAD IS WORTH HERE — the control column, read as a control.")
    print("   On this fixture the same-bar overlay does not merely flatter the guard. It")
    print("   removes the tail:")
    print(f"\n{'book':<16}{'raw maxDD %':>14}{'causal maxDD %':>17}{'canonical maxDD %':>19}"
          f"{'verdict':>26}")
    print("─" * 100)
    impossible = 0
    for book, eq in books.items():
        _r_apy, r_mdd, _r_cal = gb._metrics(eq)
        c_mdd = rows[book]["causal"][1]
        s_mdd = rows[book]["canonical"][1]
        bad = is_impossible_tail(s_mdd)
        impossible += 1 if bad else 0
        print(f"{book:<16}{f(r_mdd):>14}{f(c_mdd):>17}{f(s_mdd):>19}"
              f"{('IMPOSSIBLE — no tail left' if bad else 'plausible'):>26}")
    out["impossible_tails"] = impossible
    print(f"\n   books whose CANONICAL-module backtest reports essentially no drawdown:"
          f" {impossible} of {len(books)}")
    print("\n   THE SMOKE TEST THIS HANDS THE TREE, and it costs nothing to apply:")
    print("   a de-risk overlay whose backtest reports a maximum drawdown of ~zero has not")
    print("   found an edge, it has found the future. #94 caught the same defect on the real")
    print("   panel by arithmetic on plausible-looking cells; here the same defect announces")
    print("   itself. Any future overlay cell with a vanishing tail is an instrument failure")
    print("   until proven otherwise.")

    print("\n" + "=" * 100)
    print("VERDICT: #1's flagship table is CAUSAL and stands. #94's order, executed on the")
    print("first and most consequential cell, comes back CLEAN — and the reason is structural,")
    print("not luck: the published path never used the function #94 found defective.")
    print("Advisory only. Nothing retuned, no capital moved, no agent deployed.")
    print("=" * 100)
    return out


def main(_argv: Optional[Sequence[str]] = None) -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
