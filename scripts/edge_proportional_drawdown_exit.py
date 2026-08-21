"""
Idea #70 — PDE: Proportional Drawdown Exit
===========================================
Advisory-only backtest (IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True).
Do NOT import spa_core.execution. Do NOT touch RiskPolicy v1.0, kill-switch, live data.

HYPOTHESIS
----------
The existing guardian.apply_guardian_drawdown is BINARY: exposure snaps to `derisk_frac`
the moment drawdown from peak crosses `-derisk_dd`, and snaps back on recovery. This cliff
creates two problems:
  1. Whipsaw: equity hovering near the threshold oscillates between full and derisked.
  2. Overshoot cost: on a fast-moving tail (depeg, liquidation cascade) the gap is large
     before the trigger fires AND again when re-entry is clumsy.

PDE replaces the binary snap with a SMOOTH LINEAR RAMP:
  exposure(dd) = clamp(0, 1, 1 - (dd - d_start) / (d_full - d_start))

  dd ≤ d_start → fully invested (1.0)
  d_start < dd < d_full → exposure linearly falls from 1 to 0
  dd ≥ d_full → fully out (0.0)

Re-entry is symmetric: as equity recovers, exposure ramps back up through the same formula.

Transaction cost: proportional to |Δexposure| each day (96bp round-trip, #10/#49 canonical).

TESTS
-----
Two modes:
  (A) PDE per-book — each book's drawdown tracked independently; overlay applied before
      equal-weighting into the portfolio (same as guardian per-book).
  (B) PDE at portfolio level — track aggregate portfolio drawdown; all books scale together.

GRID: (d_start, d_full) ∈ {(0.01,0.06), (0.02,0.08), (0.03,0.10)}
Books: susde_dn, lrt_carry, leverage_loop (three representative tails).
Baseline: raw equal-weight, binary guardian (derisk_dd=0.04, derisk_frac=0.25).
Roundtrip cost: 0.0096 (96bp, canonical #10/#49).

FIXTURE DATA (deterministic, no external files, from fixtures.py spec):
  susde_dn: 11%/yr drift, USDe-unwind 2025-10 −9%, eth_crash −3%, rseth −1%
  lrt_carry: 13%/yr drift, eth_crash −5%, usde −4%, rseth_depeg −22% (catastrophic)
  leverage_loop: 15%/yr drift, eth −6%, usde −28% (worst cascade), rseth −11%
Backtest span: 2024-07-01 .. 2026-05-31 (700 days).

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
from typing import Dict, List, Tuple

# ── Constants (from fixtures.py) ──────────────────────────────────────────────────────────────────

_BACKTEST_START = datetime.date(2024, 7, 1)
_BACKTEST_END = datetime.date(2026, 5, 31)
_INITIAL = 100_000.0
_ROUNDTRIP = 0.0096  # 96 bp, canonical #10/#49

_STRESS_WINDOWS = [
    {"key": "eth_crash_2024_08",    "date_from": "2024-08-01", "date_to": "2024-08-31"},
    {"key": "usde_unwind_2025_10",  "date_from": "2025-10-01", "date_to": "2025-10-31"},
    {"key": "rseth_depeg_2026_04",  "date_from": "2026-04-01", "date_to": "2026-04-30"},
]

_BOOK_SPECS: Dict[str, dict] = {
    "susde_dn": {
        "daily_drift": 11.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09, "rseth_depeg_2026_04": 0.01},
    },
    "lrt_carry": {
        "daily_drift": 13.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04, "rseth_depeg_2026_04": 0.22},
    },
    "leverage_loop": {
        "daily_drift": 15.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28, "rseth_depeg_2026_04": 0.11},
    },
}

# ── Fixture generation (mirrors fixtures.py determinism) ─────────────────────────────────────────

def _window_for(d: datetime.date) -> str:
    for w in _STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(w["date_from"])
        hi = datetime.date.fromisoformat(w["date_to"])
        if lo <= d <= hi:
            return w["key"]
    return ""


def _build_series(spec: dict) -> List[float]:
    """Return a list of daily equity values (float). Geometric front-loading inside stress windows."""
    drift = spec["daily_drift"]
    hits: Dict[str, float] = spec["window_hits"]
    window_lengths: Dict[str, int] = {}
    for w in _STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(w["date_from"])
        hi = datetime.date.fromisoformat(w["date_to"])
        window_lengths[w["key"]] = (hi - lo).days + 1
    window_day_counters: Dict[str, int] = {}
    equity = _INITIAL
    result: List[float] = []
    d = _BACKTEST_START
    while d <= _BACKTEST_END:
        key = _window_for(d)
        daily_loss = 0.0
        if key:
            total = float(hits.get(key, 0.0))
            if total > 0.0:
                n = window_lengths[key]
                idx = window_day_counters.get(key, 0)
                window_day_counters[key] = idx + 1
                norm = sum(0.5 ** j for j in range(n))
                frac = (0.5 ** idx) / norm if norm > 0 else 0.0
                daily_loss = total * frac
        equity = equity * (1.0 + drift - daily_loss)
        result.append(equity)
        d += datetime.timedelta(days=1)
    return result


# ── Metrics ───────────────────────────────────────────────────────────────────────────────────────

def _max_drawdown(eq: List[float]) -> float:
    """Peak-to-trough drawdown as a positive fraction (0 = no drawdown)."""
    if not eq:
        return 0.0
    peak = eq[0]
    worst = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > worst:
            worst = dd
    return worst


def _apy(eq: List[float]) -> float:
    """Annualised return from first to last equity value."""
    if len(eq) < 2 or eq[0] <= 0:
        return 0.0
    n_days = len(eq)
    return (eq[-1] / eq[0]) ** (365.0 / n_days) - 1.0


def _calmar(eq: List[float]) -> float:
    dd = _max_drawdown(eq)
    apy = _apy(eq)
    return apy / dd if dd > 1e-9 else (float("inf") if apy > 0 else 0.0)


def _net_apy(eq: List[float], cost_paid: float) -> float:
    """APY after subtracting cumulative transaction cost from final equity."""
    if len(eq) < 2 or eq[0] <= 0:
        return 0.0
    n_days = len(eq)
    net_eq = eq[-1] - cost_paid
    return (net_eq / eq[0]) ** (365.0 / n_days) - 1.0


# ── PDE overlay ───────────────────────────────────────────────────────────────────────────────────

def _pde_exposure(dd: float, d_start: float, d_full: float) -> float:
    """
    dd: current drawdown from rolling peak (positive number, e.g. 0.05 = 5% drawdown).
    Returns exposure in [0.0, 1.0].
    """
    if d_full <= d_start:
        return 0.0 if dd >= d_start else 1.0
    frac = (dd - d_start) / (d_full - d_start)
    return max(0.0, min(1.0, 1.0 - frac))


def apply_pde(raw: List[float], *, d_start: float, d_full: float,
              roundtrip: float = _ROUNDTRIP) -> Tuple[List[float], float]:
    """
    Apply PDE overlay to a single book's equity series.
    Returns (guarded_equity, cumulative_cost).
    Cost charged proportional to |Δexposure| each day (fractional round-trip).
    """
    if len(raw) < 2:
        return list(raw), 0.0
    guarded: List[float] = [raw[0]]
    peak = raw[0]
    exposure = 1.0
    total_cost = 0.0
    for i in range(1, len(raw)):
        raw_ret = raw[i] / raw[i - 1] - 1.0 if raw[i - 1] > 0 else 0.0
        prev_eq = guarded[-1]
        new_eq = prev_eq * (1.0 + raw_ret * exposure)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = (peak - new_eq) / peak if peak > 0 else 0.0
        new_exp = _pde_exposure(dd, d_start, d_full)
        delta_exp = abs(new_exp - exposure)
        if delta_exp > 1e-9:
            cost = delta_exp * roundtrip * new_eq
            total_cost += cost
        exposure = new_exp
    return guarded, total_cost


def apply_binary_guardian(raw: List[float], *, derisk_dd: float = 0.04, derisk_frac: float = 0.25,
                           reenter_frac: float = 0.5, roundtrip: float = _ROUNDTRIP
                           ) -> Tuple[List[float], float]:
    """Baseline binary guardian (mirrors guardian.apply_guardian_drawdown, with cost)."""
    if len(raw) < 2:
        return list(raw), 0.0
    guarded: List[float] = [raw[0]]
    peak = raw[0]
    exposure = 1.0
    total_cost = 0.0
    for i in range(1, len(raw)):
        raw_ret = raw[i] / raw[i - 1] - 1.0 if raw[i - 1] > 0 else 0.0
        prev_eq = guarded[-1]
        new_eq = prev_eq * (1.0 + raw_ret * exposure)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = new_eq / peak - 1.0  # negative number
        prev_exp = exposure
        if exposure >= 1.0 and dd <= -derisk_dd:
            exposure = derisk_frac
        elif exposure < 1.0 and new_eq >= peak * (1.0 - derisk_dd * (1.0 - reenter_frac)):
            exposure = 1.0
        if abs(exposure - prev_exp) > 1e-9:
            cost = abs(exposure - prev_exp) * roundtrip * new_eq
            total_cost += cost
    return guarded, total_cost


# ── Portfolio-level PDE ───────────────────────────────────────────────────────────────────────────

def apply_pde_portfolio(books: Dict[str, List[float]], *, d_start: float, d_full: float,
                         roundtrip: float = _ROUNDTRIP) -> Tuple[List[float], float]:
    """
    PDE applied at the PORTFOLIO LEVEL: aggregate portfolio drawdown drives exposure for ALL books.
    Books are equal-weighted. Exposure multiplier applied to daily return contribution.
    Returns (portfolio_equity, cumulative_cost).
    """
    n = len(next(iter(books.values())))
    names = sorted(books.keys())
    n_books = len(names)
    port: List[float] = [_INITIAL]
    peak = _INITIAL
    exposure = 1.0
    total_cost = 0.0
    for i in range(1, n):
        raw_rets = [(books[b][i] / books[b][i - 1] - 1.0) if books[b][i - 1] > 0 else 0.0
                    for b in names]
        avg_ret = sum(raw_rets) / n_books
        prev_eq = port[-1]
        new_eq = prev_eq * (1.0 + avg_ret * exposure)
        port.append(new_eq)
        peak = max(peak, new_eq)
        dd = (peak - new_eq) / peak if peak > 0 else 0.0
        new_exp = _pde_exposure(dd, d_start, d_full)
        delta_exp = abs(new_exp - exposure)
        if delta_exp > 1e-9:
            cost = delta_exp * roundtrip * new_eq
            total_cost += cost
        exposure = new_exp
    return port, total_cost


def apply_binary_guardian_portfolio(books: Dict[str, List[float]], *,
                                     derisk_dd: float = 0.04, derisk_frac: float = 0.25,
                                     reenter_frac: float = 0.5,
                                     roundtrip: float = _ROUNDTRIP) -> Tuple[List[float], float]:
    """Binary guardian at portfolio level (aggregate drawdown trigger)."""
    n = len(next(iter(books.values())))
    names = sorted(books.keys())
    n_books = len(names)
    port: List[float] = [_INITIAL]
    peak = _INITIAL
    exposure = 1.0
    total_cost = 0.0
    for i in range(1, n):
        raw_rets = [(books[b][i] / books[b][i - 1] - 1.0) if books[b][i - 1] > 0 else 0.0
                    for b in names]
        avg_ret = sum(raw_rets) / n_books
        prev_eq = port[-1]
        new_eq = prev_eq * (1.0 + avg_ret * exposure)
        port.append(new_eq)
        peak = max(peak, new_eq)
        dd = new_eq / peak - 1.0
        prev_exp = exposure
        if exposure >= 1.0 and dd <= -derisk_dd:
            exposure = derisk_frac
        elif exposure < 1.0 and new_eq >= peak * (1.0 - derisk_dd * (1.0 - reenter_frac)):
            exposure = 1.0
        if abs(exposure - prev_exp) > 1e-9:
            cost = abs(exposure - prev_exp) * roundtrip * new_eq
            total_cost += cost
    return port, total_cost


def raw_equal_weight(books: Dict[str, List[float]]) -> List[float]:
    """No overlay, equal-weight portfolio."""
    n = len(next(iter(books.values())))
    names = sorted(books.keys())
    n_books = len(names)
    port: List[float] = [_INITIAL]
    for i in range(1, n):
        raw_rets = [(books[b][i] / books[b][i - 1] - 1.0) if books[b][i - 1] > 0 else 0.0
                    for b in names]
        avg_ret = sum(raw_rets) / n_books
        port.append(port[-1] * (1.0 + avg_ret))
    return port


# ── Main ─────────────────────────────────────────────────────────────────────────────────────────

def _fmt(val: float, pct: bool = True, decimals: int = 2) -> str:
    if math.isinf(val):
        return "inf"
    if pct:
        return f"{val * 100:.{decimals}f}%"
    return f"{val:.{decimals}f}"


def main() -> None:
    print("=" * 70)
    print("Idea #70 — PDE: Proportional Drawdown Exit  [bt]")
    print("Advisory-only. IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True.")
    print("=" * 70)
    print()

    # Build fixture series
    raw_series: Dict[str, List[float]] = {
        name: _build_series(spec) for name, spec in _BOOK_SPECS.items()
    }
    n_days = len(next(iter(raw_series.values())))
    print(f"Fixture: {n_days} days  ({_BACKTEST_START} .. {_BACKTEST_END})")
    print()

    # ── PART A: PDE per-book individually ────────────────────────────────────────────────────────

    print("-" * 70)
    print("PART A — PDE per-book (susde_dn, lrt_carry, leverage_loop)")
    print("-" * 70)
    _grid_a: List[Tuple[float, float]] = [(0.01, 0.06), (0.02, 0.08), (0.03, 0.10)]

    per_book_header = f"{'book':<14} {'config':<22} {'APY':>8} {'maxDD':>8} {'Calmar':>8} {'netAPY':>8}"
    print(per_book_header)
    print("-" * len(per_book_header))

    for book_name in ["susde_dn", "lrt_carry", "leverage_loop"]:
        raw = raw_series[book_name]
        apy_raw = _apy(raw)
        dd_raw = _max_drawdown(raw)
        calmar_raw = _calmar(raw)
        print(f"{book_name:<14} {'raw (no overlay)':<22} "
              f"{_fmt(apy_raw):>8} {_fmt(dd_raw):>8} {_fmt(calmar_raw,False):>8} {_fmt(apy_raw):>8}")
        # Binary guardian
        bg, bg_cost = apply_binary_guardian(raw)
        apy_bg = _apy(bg)
        dd_bg = _max_drawdown(bg)
        net_bg = _net_apy(bg, bg_cost)
        print(f"{book_name:<14} {'binary -4%/25%':<22} "
              f"{_fmt(apy_bg):>8} {_fmt(dd_bg):>8} {_fmt(_calmar(bg),False):>8} {_fmt(net_bg):>8}")
        # PDE configurations
        for d_start, d_full in _grid_a:
            guarded, cost = apply_pde(raw, d_start=d_start, d_full=d_full)
            apy_g = _apy(guarded)
            dd_g = _max_drawdown(guarded)
            net_g = _net_apy(guarded, cost)
            label = f"PDE {d_start*100:.0f}%-{d_full*100:.0f}%"
            print(f"{book_name:<14} {label:<22} "
                  f"{_fmt(apy_g):>8} {_fmt(dd_g):>8} {_fmt(_calmar(guarded),False):>8} {_fmt(net_g):>8}")
        print()

    # ── PART B: PDE at portfolio level ───────────────────────────────────────────────────────────

    print("-" * 70)
    print("PART B — PDE at PORTFOLIO LEVEL (aggregate drawdown drives all books)")
    print("-" * 70)

    port_header = f"{'config':<28} {'APY':>8} {'maxDD':>8} {'Calmar':>8} {'netAPY':>8}"
    print(port_header)
    print("-" * len(port_header))

    # Raw equal-weight
    raw_port = raw_equal_weight(raw_series)
    raw_port_apy = _apy(raw_port)
    raw_port_dd = _max_drawdown(raw_port)
    print(f"{'raw equal-weight':<28} {_fmt(raw_port_apy):>8} {_fmt(raw_port_dd):>8} "
          f"{_fmt(_calmar(raw_port),False):>8} {_fmt(raw_port_apy):>8}")

    # Binary guardian at portfolio level
    bg_port, bg_port_cost = apply_binary_guardian_portfolio(raw_series)
    bg_port_net = _net_apy(bg_port, bg_port_cost)
    print(f"{'binary portfolio -4%/25%':<28} {_fmt(_apy(bg_port)):>8} {_fmt(_max_drawdown(bg_port)):>8} "
          f"{_fmt(_calmar(bg_port),False):>8} {_fmt(bg_port_net):>8}")

    # PDE at portfolio level
    for d_start, d_full in [(0.01, 0.06), (0.02, 0.08), (0.02, 0.06), (0.03, 0.10)]:
        port, cost = apply_pde_portfolio(raw_series, d_start=d_start, d_full=d_full)
        net = _net_apy(port, cost)
        label = f"PDE-port {d_start*100:.0f}%-{d_full*100:.0f}%"
        print(f"{label:<28} {_fmt(_apy(port)):>8} {_fmt(_max_drawdown(port)):>8} "
              f"{_fmt(_calmar(port),False):>8} {_fmt(net):>8}")

    print()

    # ── PART C: Continuous vs Binary cost comparison ──────────────────────────────────────────────

    print("-" * 70)
    print("PART C — Transaction cost breakdown (PDE charges daily; binary charges at switch)")
    print("-" * 70)
    cost_header = f"{'book/config':<28} {'gross APY':>10} {'cost (bp/yr)':>14} {'net APY':>10}"
    print(cost_header)
    print("-" * len(cost_header))

    for book_name in ["susde_dn", "lrt_carry", "leverage_loop"]:
        raw = raw_series[book_name]
        for d_start, d_full in [(0.01, 0.06), (0.02, 0.08)]:
            guarded, cost = apply_pde(raw, d_start=d_start, d_full=d_full)
            gross = _apy(guarded)
            years = n_days / 365.0
            cost_bpyr = (cost / guarded[0]) / years * 10000
            net = _net_apy(guarded, cost)
            label = f"{book_name} PDE {d_start*100:.0f}%-{d_full*100:.0f}%"
            print(f"{label:<28} {_fmt(gross):>10} {cost_bpyr:>14.1f} {_fmt(net):>10}")
        bg, bg_cost = apply_binary_guardian(raw)
        bg_gross = _apy(bg)
        bg_cost_bpyr = (bg_cost / bg[0]) / (n_days / 365.0) * 10000
        bg_net = _net_apy(bg, bg_cost)
        print(f"{book_name + ' binary':28} {_fmt(bg_gross):>10} {bg_cost_bpyr:>14.1f} {_fmt(bg_net):>10}")
    print()

    # ── PART D: Summary verdict ──────────────────────────────────────────────────────────────────

    print("-" * 70)
    print("PART D — Summary: best PDE config vs binary guardian per book [bt]")
    print("-" * 70)
    print()
    results: Dict[str, Dict[str, dict]] = {}
    for book_name in ["susde_dn", "lrt_carry", "leverage_loop"]:
        raw = raw_series[book_name]
        best_calmar = -1.0
        best_config = ""
        best_net = 0.0
        best_dd = 0.0
        raw_c = _calmar(raw)
        for d_start, d_full in [(0.01, 0.06), (0.02, 0.08), (0.03, 0.10)]:
            guarded, cost = apply_pde(raw, d_start=d_start, d_full=d_full)
            c = _calmar(guarded)
            if c > best_calmar:
                best_calmar = c
                best_config = f"PDE {d_start*100:.0f}%-{d_full*100:.0f}%"
                best_net = _net_apy(guarded, cost)
                best_dd = _max_drawdown(guarded)
        bg, bg_cost = apply_binary_guardian(raw)
        bg_c = _calmar(bg)
        bg_net = _net_apy(bg, bg_cost)
        bg_dd = _max_drawdown(bg)
        results[book_name] = {
            "raw_calmar": raw_c, "raw_dd": _max_drawdown(raw),
            "binary_calmar": bg_c, "binary_net": bg_net, "binary_dd": bg_dd,
            "pde_best_config": best_config, "pde_calmar": best_calmar,
            "pde_net": best_net, "pde_dd": best_dd,
        }
        pde_wins = best_calmar > bg_c
        verdict_str = "PDE WINS" if pde_wins else "BINARY WINS"
        print(f"{book_name}:")
        print(f"  raw:           Calmar={_fmt(raw_c,False)}  maxDD={_fmt(_max_drawdown(raw))}")
        print(f"  binary -4%/25%: Calmar={_fmt(bg_c,False)}  maxDD={_fmt(bg_dd)}  netAPY={_fmt(bg_net)}")
        print(f"  {best_config}: Calmar={_fmt(best_calmar,False)}  maxDD={_fmt(best_dd)}  netAPY={_fmt(best_net)}")
        delta = best_calmar - bg_c
        sign = "+" if delta >= 0 else ""
        print(f"  → {verdict_str}  (ΔCalmar PDE−binary = {sign}{_fmt(delta, False)})")
        print()

    print("-" * 70)
    print("HONEST CAVEATS:")
    print("  (a) evidence L0 — backtest on deterministic FIXTURE, not realised data")
    print("  (b) fixture drift is constant → PDE mostly reactive to stress-window shocks")
    print("  (c) real continuous trading faces wider bid/ask; 96bp RT is a lower bound")
    print("  (d) fixture has NO path noise between stress windows → PDE rarely fires outside windows")
    print("      (on real data with daily vol, PDE fires much more often → higher cost)")
    print("  (e) d_start/d_full not optimised — grid 3×3; luckier choices likely exist")
    print("  (f) IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True")
    print("  (g) RiskPolicy v1.0, kill-switch, live track, data/ and fleet NOT touched")
    print("-" * 70)


if __name__ == "__main__":
    main()
