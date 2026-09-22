#!/usr/bin/env python3
"""
scripts/edge_biss_real_panel.py — Idea #111 (BISS-REAL)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core/execution/. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads the aggressive-lab panel READ-ONLY.


WHY THIS RUN EXISTS — THE ORDER #110 LEFT, VERBATIM
---------------------------------------------------
Registry idea #110 (BISS: Binary Invest-Stress Switch) asked whether it is worth holding risky
exposure AT ALL on a stress day, ran on the SYNTHETIC fixture only, and closed with a literal
order and a literal acceptance criterion:

    "(1) как ORACLE-потолок меняется на реальной панели (другое распределение загрузки потерь,
     ненулевые ложные сигналы)? ...
     Критерий приёмки для следующей идеи: на реальной панели доля от ORACLE-потолка > 50 %
     при <= 10 % ложных срабатываний в штиль."

This run executes part (1) on the full real panel (10 books, 852 common days,
2024-03-06 ... 2026-07-05, phase="backtest" block only). Part (2) — whether an EXOGENOUS
leading feed moves the barrier — is idea #112 (scripts/edge_exogenous_leading_switch.py),
which imports this harness rather than re-deriving it.


THE DEFECT IN #110's ACCEPTANCE CRITERION, FOUND BEFORE THE FIRST NEW NUMBER
----------------------------------------------------------------------------
"Share of the ORACLE ceiling" is not a measurable quantity until the oracle is NAMED, and on a
real panel there is no hand-declared window list to name it with. #110's fixture oracle read
`STRESS_WINDOWS` — three windows written by hand in `aggressive_lab/fixtures.py`. The real panel
has no such list, so the ceiling has to be DERIVED, and every derivation is a different ceiling:

  ORACLE-DAY  perfect DAILY foresight: defend on every day whose EW return is below the RWA
              floor. This is the supremum of the whole mechanism class — no binary daily switch
              can beat it, causal or not.
  ORACLE-WIN  perfect WINDOW foresight: windows derived from the EW equity curve by a declared
              rule (a maximal decline from a running high to the following low, depth >= d),
              defended from the day the window opens. This is the analogue of what #110 measured,
              because a hand-declared window list is also "peak to trough, named in advance".

Both are measured here, at three window depths, and they are NOT close. Quoting a
"share of the ORACLE ceiling" without saying which oracle produced the denominator is the
"one word names two bases" defect the census branch keeps finding in other people's code, so the
share is reported per oracle, never once.

The same holds for the second half of #110's criterion. "<= 10 % ложных срабатываний в штиль"
has two defensible denominators and they differ by an order of magnitude here:

  fp_of_defend  defend-days outside any window / defend-days        (precision-style)
  fp_of_calm    defend-days outside any window / all calm days      (duty-style)

#19 (EWVM) declared its own budget on the SECOND of these ("fp_rate 5 % -> duty 53 %"), and
required < 2 %; #110 declared <= 10 % without naming the denominator at all. Both numbers are
printed for every row so the two budgets can be applied to the number each one meant.


WHAT THIS RUN ADDS THAT #110 DID NOT HAVE
-----------------------------------------
1. Real returns. #110's own caveat (б) said its zero false-positive rate in calm was GUARANTEED
   by the fixture (no negative days outside the windows). On the real panel 38.7 % of EW days are
   negative, so the 1-day trigger is measured where it can actually be wrong.
2. Cost. #110 switched for free. The canonical 96 bp round trip (#10/#49) is charged on the
   fraction of capital whose state changed, and every row is run at 0 bp and 96 bp so a loss is
   attributable to COST or to TIMING instead of asserted.
3. The loss-front-loading census on real windows — #110's headline ("51 % of window losses land
   on day 1") is a property of the fixture's `frac = 0.5**idx` loading, and its own text said so.
   Here it is measured, not inherited.
4. A positive control that the simulator IS #110's mechanism: the same code reproduces #110's
   published fixture cells before any real-panel number is printed. A mismatch is a REFUSAL.
5. TRAIN/TEST split at the registry-canonical 2025-06-30, printed as it falls.

HONEST LIMITS DECLARED UP FRONT
  * evidence L0/[bt] — a backtest of a RULE over an advisory paper panel whose books are
    themselves backtests over real deep-history feeds. Never realised P&L, never fills.
  * phase="backtest" block only (RPE.load_panel); diffing across the forward seam fabricates
    one-day returns of tens of percent.
  * the DEFEND destination is a flat 3.4 %/yr RWA constant, taken from #110 unchanged. It is a
    convention, not a quote, and it flatters every defend rule equally (#110 caveat (г)).
  * the window depth d that defines ORACLE-WIN is chosen from the panel's own drawdown
    distribution. That is look-ahead BY CONSTRUCTION — it defines the ceiling, it is not a
    trading rule — and it is why the whole grid is printed rather than one cell.
  * no capacity, no slippage beyond the flat round trip, no borrow, no tier or chain ceiling.
  * advisory / paper-only: nothing here sizes, funds or gates anything.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_binary_stress_switch as BISS  # noqa: E402  #110 mechanism + constants, UNCHANGED
import edge_real_panel_ensemble as RPE  # noqa: E402  phase-clean real-panel loader (fail-CLOSED)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
#: Panel location. Overridable because the panel is NOT git-tracked: a session working from a
#: worktree has an empty data/ and must point at the prod tree's copy (read-only).
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

RWA_DAILY = BISS.RWA_DAILY      # from #110, not restated
N_RECOVER = BISS.N_RECOVER      # from #110, not restated
DEFEND_FRACS = dict(BISS.DEFEND_FRACS)
ROUNDTRIP = 0.0096              # 96 bp, canonical #10/#49

#: Window depths for ORACLE-WIN. 5 % yields a single 121-day window on this panel and 10 %
#: yields none — both facts are printed rather than hidden by picking one depth.
DEPTH_GRID: Tuple[float, ...] = (0.01, 0.02, 0.05)

SPLIT = "2025-06-30"            # registry-canonical TRAIN/TEST boundary

#: Cells published by #110 that this file must reproduce before printing anything new.
#: (signal, defend_frac) -> (apy_pct, maxdd_pct, calmar). A mismatch is a REFUSAL.
PUBLISHED_110: Dict[Tuple[str, float], Tuple[float, float, float]] = {
    ("ew", 0.5): (-2.59, 14.44, -0.179),
    ("oracle", 0.5): (4.45, 5.26, 0.846),
    ("oracle", 0.0): (11.87, 0.00, float("inf")),
    ("1day", 0.5): (0.90, 9.83, 0.092),
    ("1day", 0.0): (4.49, 5.52, 0.814),
    ("5day", 0.5): (0.89, 9.84, 0.090),
    ("5day", 0.0): (4.45, 5.52, 0.808),
}
CONTROL_TOL = 0.02  # absolute tolerance on APY%/DD% and on Calmar


# ───────────────────────────── window derivation ─────────────────────────────
def decline_windows(dates: Sequence[str], rets: Sequence[float], depth_min: float) -> List[Tuple[str, str]]:
    """Maximal declines of the equity curve, as [open, close] date pairs (inclusive).

    A window opens on the day AFTER a running high and closes on the day of the following low,
    and is kept only if the low is at least `depth_min` below that high. Windows are therefore
    non-overlapping by construction, and a day inside one is a day on which holding risk was, in
    hindsight, a mistake. Look-ahead is intended: this DEFINES the ceiling.

    The still-open episode at the end of the series is included on the same terms as the closed
    ones — dropping it would silently exempt the last decline from the oracle.
    """
    if len(dates) != len(rets):
        raise ValueError("dates/returns length mismatch — refusing to align by position")
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    # eq[i+1] is the equity AFTER the return of dates[i]; index 0 is the pre-series point.
    out: List[Tuple[str, str]] = []
    hwm, hwm_i = eq[0], 0
    trough, trough_i = eq[0], 0

    def close_episode() -> None:
        if trough < hwm and hwm > 0 and (1.0 - trough / hwm) >= depth_min:
            # open = first dated day after the high  -> dates[hwm_i]
            # close = the dated day of the low       -> dates[trough_i - 1]
            if trough_i - 1 >= hwm_i:
                out.append((dates[hwm_i], dates[trough_i - 1]))

    # `>=`, not `>`: on an exactly flat stretch the running high must keep moving, otherwise a
    # book that stands still for a week and then falls is dated as having declined for the whole
    # week. Measured on a flat fixture, `>` opened the window at the first flat day.
    for i, v in enumerate(eq):
        if v >= hwm:
            close_episode()
            hwm, hwm_i = v, i
            trough, trough_i = v, i
        elif v < trough:
            trough, trough_i = v, i
    close_episode()
    return out


def window_days(windows: Sequence[Tuple[str, str]]) -> Set[str]:
    """Every date covered by a window. Built from the dates themselves, not from a range."""
    return {d for lo, hi in windows for d in _dates_between(lo, hi)}


_AXIS_CACHE: List[str] = []


def _dates_between(lo: str, hi: str) -> List[str]:
    return [d for d in _AXIS_CACHE if lo <= d <= hi]


def set_axis(axis: Sequence[str]) -> None:
    """Pin the axis used to expand window bounds into days (no calendar arithmetic)."""
    global _AXIS_CACHE
    _AXIS_CACHE = list(axis)


# ───────────────────────────── simulation ─────────────────────────────
def simulate(
    dates: Sequence[str],
    rets: Dict[str, Sequence[float]],
    books: Sequence[str],
    *,
    mode: str,
    defend_frac: float,
    defend_days: Optional[Set[str]] = None,
    roundtrip: float = 0.0,
    n_recover: int = N_RECOVER,
) -> dict:
    """One binary INVEST/DEFEND run. Returns metrics plus the realised defend-day set.

    mode:
      'ew'       always INVEST (the zero).
      'given'    DEFEND iff the date is in `defend_days`. Used for BOTH oracles (non-causal by
                 construction) and for #112's exogenous signals (causal by construction of the
                 set). Which one it is, is the caller's claim, not this function's.
      '1day'     #110's state machine: DEFEND tomorrow if any book was negative today; back to
                 INVEST after n_recover consecutive all-positive days.
      '5day'     #110's state machine on the portfolio's trailing 5-day sum.

    Causality of '1day'/'5day' is structural: today's allocation is decided from returns up to
    and including yesterday. Day one of any decline is therefore always taken in full.

    `roundtrip` is charged on |change in risky weight| on each day the weight changes, so HALF
    costs half of ZERO for the same switch — the toll follows the capital that moved.
    """
    if mode == "given" and defend_days is None:
        raise ValueError("mode='given' needs defend_days — refusing to default to INVEST")
    n_books = len(books)
    eq = 1.0
    curve = [eq]
    port_rets: List[float] = []
    realised_defend: Set[str] = set()
    prev_risky = 1.0
    switches = 0
    next_invest = True
    recover = 0
    hist: List[float] = []

    for i, d in enumerate(dates):
        book_rets = {b: rets[b][i] for b in books}
        port_today = sum(book_rets[b] for b in books) / n_books

        if mode == "ew":
            invest = True
        elif mode == "given":
            invest = d not in defend_days  # type: ignore[operator]
        else:
            invest = next_invest

        risky = 1.0 if invest else defend_frac
        if not invest:
            realised_defend.add(d)
        toll = roundtrip * abs(risky - prev_risky)
        if risky != prev_risky:
            switches += 1
        w_each = risky / n_books
        r = sum(w_each * book_rets[b] for b in books) + (1.0 - risky) * RWA_DAILY - toll
        eq *= (1.0 + r)
        curve.append(eq)
        port_rets.append(r)
        prev_risky = risky

        if mode == "1day":
            if invest:
                next_invest = not any(book_rets[b] < 0.0 for b in books)
                if not next_invest:
                    recover = 0
            else:
                if all(book_rets[b] >= 0.0 for b in books):
                    recover += 1
                    next_invest = recover >= n_recover
                    if next_invest:
                        recover = 0
                else:
                    recover = 0
                    next_invest = False
        elif mode == "5day":
            hist.append(port_today)
            if len(hist) > 5:
                hist.pop(0)
            trailing = sum(hist)
            if invest:
                next_invest = not (len(hist) >= 5 and trailing < 0.0)
                if not next_invest:
                    recover = 0
            else:
                if len(hist) >= 5 and trailing >= 0.0:
                    recover += 1
                    next_invest = recover >= n_recover
                    if next_invest:
                        recover = 0
                else:
                    recover = 0
                    next_invest = False

    m = RPE.perf(port_rets)
    return {
        "mode": mode,
        "defend_frac": defend_frac,
        "apy_pct": m["apy"] * 100.0,
        "maxdd_pct": abs(m["maxdd"]) * 100.0,
        "calmar": m["calmar"],
        "duty_pct": 100.0 * len(realised_defend) / len(dates) if dates else 0.0,
        "switches": switches,
        "defend_days": realised_defend,
        "n_days": len(dates),
    }


# ───────────────────────────── derived measures ─────────────────────────────
def share_of_ceiling(calmar_row: float, calmar_ew: float, calmar_oracle: float) -> Optional[float]:
    """(row - ew) / (oracle - ew), or None when the question has no answer.

    Three separate reasons for None, each reported by name at the call site rather than
    collapsed into a zero (inv. #17): an infinite ceiling (a zero-drawdown oracle has no finite
    denominator), a non-positive ceiling (the oracle did not beat the zero, so there is no
    ceiling to take a share of), and a non-finite row.
    """
    for v in (calmar_row, calmar_ew, calmar_oracle):
        if v != v or v in (float("inf"), float("-inf")):
            return None
    span = calmar_oracle - calmar_ew
    if span <= 0:
        return None
    return (calmar_row - calmar_ew) / span


def ceiling_refusal(calmar_ew: float, calmar_oracle: float) -> Optional[str]:
    """Why share_of_ceiling refused, in words. None when it did not refuse."""
    if calmar_oracle in (float("inf"), float("-inf")):
        return "ceiling is infinite (oracle drawdown is exactly zero) — share undefined"
    if calmar_ew in (float("inf"), float("-inf")):
        return "zero is infinite (EW drawdown is exactly zero) — share undefined"
    if calmar_oracle - calmar_ew <= 0:
        return f"oracle does not beat EW (span {calmar_oracle - calmar_ew:+.3f}) — no ceiling to share"
    return None


def fp_rates(defend: Set[str], win_days: Set[str], axis: Sequence[str]) -> Dict[str, Optional[float]]:
    """The two denominators of "false positives in calm", both named, never averaged."""
    calm = [d for d in axis if d not in win_days]
    fp = len([d for d in defend if d not in win_days])
    return {
        "fp_of_defend": (fp / len(defend)) if defend else None,   # None = never defended at all
        "fp_of_calm": (fp / len(calm)) if calm else None,          # None = no calm day exists
        "fp_days": float(fp),
        "recall_of_window": (len([d for d in defend if d in win_days]) / len(win_days)) if win_days else None,
    }


def front_loading(dates: Sequence[str], ew: Sequence[float], windows: Sequence[Tuple[str, str]]) -> List[dict]:
    """Per window: what share of its total loss lands on day 1 — #110's headline, re-measured.

    A window of one day is reported as share 1.0 with n_days 1, not hidden: the number is then a
    property of the window length, and the length is printed beside it.
    """
    idx = {d: i for i, d in enumerate(dates)}
    out: List[dict] = []
    for lo, hi in windows:
        days = _dates_between(lo, hi)
        rs = [ew[idx[d]] for d in days]
        loss = sum(r for r in rs if r < 0.0)
        day1 = rs[0] if rs and rs[0] < 0.0 else 0.0
        out.append({
            "open": lo, "close": hi, "n_days": len(days),
            "total_loss_pct": loss * 100.0,
            "day1_share": (abs(day1 / loss) if abs(loss) > 1e-12 else None),
        })
    return out


# ───────────────────────────── positive control ─────────────────────────────
def control_reproduces_110(tol: float = CONTROL_TOL) -> Dict[str, Tuple[float, float, float, float, float, float]]:
    """Run THIS simulator on #110's fixture and compare with #110's published cells.

    Returns {cell: (apy_got, apy_pub, dd_got, dd_pub, cal_got, cal_pub)}; raises on mismatch.
    The control proves that the real-panel numbers below come out of #110's MECHANISM and not
    out of a lookalike — the failure mode that made #109 re-measure its own baseline.
    """
    dates, rets = BISS._load_daily_rets()
    set_axis(dates)
    win = {d for d in dates if BISS._in_crisis_window(d)}
    got: Dict[str, Tuple[float, float, float, float, float, float]] = {}
    bad: List[str] = []
    for (sig, df), (apy_p, dd_p, cal_p) in sorted(PUBLISHED_110.items(), key=lambda kv: str(kv[0])):
        mode = "given" if sig == "oracle" else sig
        r = simulate(dates, rets, BISS.BOOKS, mode=mode, defend_frac=df,
                     defend_days=win if sig == "oracle" else None, roundtrip=0.0)
        key = f"{sig}/{df:g}"
        got[key] = (r["apy_pct"], apy_p, r["maxdd_pct"], dd_p, r["calmar"], cal_p)
        ok = abs(r["apy_pct"] - apy_p) <= tol and abs(r["maxdd_pct"] - dd_p) <= tol
        if cal_p in (float("inf"),):
            ok = ok and r["calmar"] in (float("inf"),)
        else:
            ok = ok and abs(r["calmar"] - cal_p) <= tol
        if not ok:
            bad.append(f"{key}: got {r['apy_pct']:.2f}/{r['maxdd_pct']:.2f}/{r['calmar']:.3f} "
                       f"vs published {apy_p:.2f}/{dd_p:.2f}/{cal_p:.3f}")
    if bad:
        raise AssertionError("REFUSED — this simulator does not reproduce #110:\n  " + "\n  ".join(bad))
    return got


# ───────────────────────────── main ─────────────────────────────
def load_real(panel_dir: Path = PANEL_DIR) -> Tuple[List[str], Dict[str, List[float]], List[str]]:
    panel = RPE.load_panel(panel_dir)
    axis = RPE.common_axis(panel)
    if len(axis) < 200:
        raise RuntimeError(f"common axis is {len(axis)} days — refusing to judge a rule on it")
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    return axis, rets, books


def run(axis: List[str], rets: Dict[str, List[float]], books: List[str],
        *, roundtrips: Sequence[float] = (0.0, ROUNDTRIP), verbose: bool = True) -> dict:
    set_axis(axis)
    ew_series = [sum(rets[b][i] for b in books) / len(books) for i in range(len(axis))]

    oracles: Dict[str, Set[str]] = {
        "ORACLE-DAY": {d for i, d in enumerate(axis) if ew_series[i] < RWA_DAILY},
    }
    wins: Dict[str, List[Tuple[str, str]]] = {}
    for depth in DEPTH_GRID:
        w = decline_windows(axis, ew_series, depth)
        name = f"ORACLE-WIN{depth * 100:.0f}"
        wins[name] = w
        oracles[name] = window_days(w)

    #: The window set the false-positive question is asked against. Declared, not inferred:
    #: 2 % is the middle of the grid and the only depth with both several windows and real depth.
    FP_REF = "ORACLE-WIN2"

    rows: List[dict] = []
    for rt in roundtrips:
        for df_name, df in sorted(DEFEND_FRACS.items()):
            rows.append({"label": "EW", **simulate(axis, rets, books, mode="ew", defend_frac=df,
                                                   roundtrip=rt), "rt": rt, "df_name": df_name})
            for oname, odays in oracles.items():
                rows.append({"label": oname, **simulate(axis, rets, books, mode="given", defend_frac=df,
                                                        defend_days=odays, roundtrip=rt),
                             "rt": rt, "df_name": df_name})
            for sig in ("1day", "5day"):
                rows.append({"label": sig.upper(), **simulate(axis, rets, books, mode=sig, defend_frac=df,
                                                              roundtrip=rt), "rt": rt, "df_name": df_name})

    ref_days = oracles[FP_REF]
    for r in rows:
        r.update(fp_rates(r["defend_days"], ref_days, axis))

    def find(label: str, df: float, rt: float) -> dict:
        return next(x for x in rows if x["label"] == label and x["defend_frac"] == df and x["rt"] == rt)

    if verbose:
        print("=== #111 BISS-REAL: the ORACLE ceiling on the REAL panel ===")
        print(f"axis {axis[0]}...{axis[-1]}  ({len(axis)} days)   books {len(books)}: {', '.join(books)}")
        m = RPE.perf(ew_series)
        neg = 100.0 * len([x for x in ew_series if x < 0]) / len(ew_series)
        print(f"EW zero (no overlay): APY {m['apy'] * 100:.2f}%  maxDD {abs(m['maxdd']) * 100:.2f}%  "
              f"Calmar {m['calmar']:.2f}   negative days {neg:.1f}%")
        print(f"[bt][L0] advisory backtest of a RULE — never realised P&L. RWA floor "
              f"{RWA_DAILY * 365 * 100:.2f}%/yr flat (convention from #110).\n")

        print("--- the fixture's zero false-positive rate was structural; here it is measured ---")
        print(f"  negative EW days on the real panel: {neg:.1f}%   (fixture: ~0% outside its 3 windows)\n")

        print("--- ORACLE-WIN windows derived from the EW curve (look-ahead BY DESIGN) ---")
        for name in sorted(wins):
            w = wins[name]
            days = len(oracles[name])
            print(f"  {name}: {len(w)} windows, {days} days ({100.0 * days / len(axis):.1f}% of axis)")
        print(f"  ORACLE-DAY: {len(oracles['ORACLE-DAY'])} days "
              f"({100.0 * len(oracles['ORACLE-DAY']) / len(axis):.1f}% of axis)\n")

        print(f"--- front-loading of losses inside {FP_REF} windows (#110 measured 51% on day 1) ---")
        for fl in front_loading(axis, ew_series, wins[FP_REF]):
            share = "n/a" if fl["day1_share"] is None else f"{fl['day1_share']:.1%}"
            print(f"  {fl['open']}...{fl['close']} ({fl['n_days']:>3}d)  total loss "
                  f"{fl['total_loss_pct']:>7.2f}%   day-1 share {share}")
        print()

        for rt in roundtrips:
            print(f"--- rows at round-trip {rt * 10000:.0f} bp ---")
            hdr = (f"{'row':<12} {'defend':>6} {'APY%':>8} {'maxDD%':>8} {'Calmar':>9} {'duty%':>7} "
                   f"{'switch':>7} {'fp|defend':>10} {'fp|calm':>9} {'recall':>7}")
            print(hdr)
            print("-" * len(hdr))
            for df_name, df in sorted(DEFEND_FRACS.items()):
                for label in ["EW", "ORACLE-DAY"] + sorted(wins) + ["1DAY", "5DAY"]:
                    r = find(label, df, rt)
                    cal = "inf" if r["calmar"] == float("inf") else f"{r['calmar']:.3f}"
                    fpd = "n/a" if r["fp_of_defend"] is None else f"{r['fp_of_defend']:.1%}"
                    fpc = "n/a" if r["fp_of_calm"] is None else f"{r['fp_of_calm']:.1%}"
                    rec = "n/a" if r["recall_of_window"] is None else f"{r['recall_of_window']:.1%}"
                    print(f"{label:<12} {df_name:>6} {r['apy_pct']:>8.2f} {r['maxdd_pct']:>8.2f} "
                          f"{cal:>9} {r['duty_pct']:>7.1f} {r['switches']:>7} {fpd:>10} {fpc:>9} {rec:>7}")
            print()

        print("--- share of the ceiling: the answer depends on WHICH oracle, so all are printed ---")
        for rt in roundtrips:
            for df_name, df in sorted(DEFEND_FRACS.items()):
                ew_c = find("EW", df, rt)["calmar"]
                for oname in ["ORACLE-DAY"] + sorted(wins):
                    o_c = find(oname, df, rt)["calmar"]
                    why = ceiling_refusal(ew_c, o_c)
                    if why:
                        print(f"  {rt * 10000:>3.0f}bp {df_name:<5} vs {oname:<12} NOT MEASURED — {why}")
                        continue
                    parts = []
                    for sig in ("1DAY", "5DAY"):
                        s = share_of_ceiling(find(sig, df, rt)["calmar"], ew_c, o_c)
                        parts.append(f"{sig} {s:+.1%}" if s is not None else f"{sig} NOT MEASURED")
                    print(f"  {rt * 10000:>3.0f}bp {df_name:<5} vs {oname:<12} ceiling "
                          f"{o_c - ew_c:+.3f} Calmar | " + " | ".join(parts))
        print()

    return {
        "axis": [axis[0], axis[-1]], "n_days": len(axis), "books": books,
        "ew": {k: v for k, v in RPE.perf(ew_series).items()},
        "negative_day_share": len([x for x in ew_series if x < 0]) / len(ew_series),
        "oracle_day_counts": {k: len(v) for k, v in oracles.items()},
        "windows": {k: [list(w) for w in v] for k, v in wins.items()},
        "front_loading": front_loading(axis, ew_series, wins[FP_REF]),
        "fp_reference_window": FP_REF,
        "rows": [{k: v for k, v in r.items() if k != "defend_days"} for r in rows],
    }


def split_report(axis: List[str], rets: Dict[str, List[float]], books: List[str], split: str = SPLIT) -> dict:
    out = {}
    for name, sub in (("TRAIN", [d for d in axis if d <= split]), ("TEST", [d for d in axis if d > split])):
        if len(sub) < 120:
            out[name] = {"status": "NOT MEASURED", "reason": f"{len(sub)} days < 120"}
            continue
        idx = [axis.index(d) for d in sub]
        sub_rets = {b: [rets[b][i] for i in idx] for b in books}
        out[name] = run(sub, sub_rets, books, roundtrips=(ROUNDTRIP,), verbose=False)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else "")
    ap.add_argument("--json", type=Path, default=ROOT / "data" / "edge_biss_real_results.json")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    print("--- positive control: does this simulator reproduce #110's fixture cells? ---")
    got = control_reproduces_110()
    for key, (a, ap_, d, dp, c, cp) in got.items():
        cs = "inf" if c == float("inf") else f"{c:.3f}"
        cps = "inf" if cp == float("inf") else f"{cp:.3f}"
        print(f"  {key:<12} APY {a:>7.2f} (pub {ap_:>7.2f})  DD {d:>6.2f} (pub {dp:>6.2f})  "
              f"Calmar {cs:>7} (pub {cps:>7})")
    print("  OK — mechanism is #110's.\n")

    axis, rets, books = load_real()
    res = run(axis, rets, books)
    res["control_110"] = {k: list(v) for k, v in got.items()}
    res["splits"] = split_report(axis, rets, books)

    print(f"--- TRAIN/TEST at {SPLIT} (96 bp), printed as it falls ---")
    for name in ("TRAIN", "TEST"):
        s = res["splits"][name]
        if s.get("status") == "NOT MEASURED":
            print(f"  {name}: NOT MEASURED — {s['reason']}")
            continue
        for label in ("EW", "1DAY", "5DAY", "ORACLE-WIN2"):
            r = next(x for x in s["rows"] if x["label"] == label and x["defend_frac"] == 0.0)
            cal = "inf" if r["calmar"] == float("inf") else f"{r['calmar']:.3f}"
            print(f"  {name:<6} {label:<12} ZERO  APY {r['apy_pct']:>7.2f}%  maxDD {r['maxdd_pct']:>6.2f}%  "
                  f"Calmar {cal:>8}  duty {r['duty_pct']:>5.1f}%")
    print()

    if not args.no_write:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(res, indent=2, sort_keys=True, default=str))
        print(f"written {args.json} [bt] advisory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
