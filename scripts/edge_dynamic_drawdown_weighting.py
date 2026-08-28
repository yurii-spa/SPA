"""
IDEA #85 — DDW: Dynamic Drawdown Weighting
«веса пропорциональны ОБРАТНО глубине текущей просадки — мягкая непороговая альтернатива XSD/MRD»

ГИПОТЕЗА. #40 XSD, #41 MRD, #45 XVD — все бинарные: книга ИЛИ включена ИЛИ нет.
Бинарность = резкое изменение весов при пересечении порога → высокий оборот → пошлина (#80).
DDW заменяет порог на НЕПРЕРЫВНУЮ функцию: вес книги = 1/(1 + DD_b × kappa),
где DD_b — текущая просадка книги от её пика (standalone, без заглядывания вперёд).
При DD_b = 0 (книга на пике): вес = 1/(1+0) = 1, равновесие.
При DD_b = 20%: вес = 1/(1 + 0.20×kappa). При kappa=5: 1/2 = 50% от равного.
Веса нормируются на 1. При kappa=0: тождественно равновес.

ОЖИДАНИЯ. На фикстуре потери ПЕРЕДНЕЗАГРУЖЕНЫ: большая часть убытка — первый день окна.
Механизм РЕАГИРУЕТ на реализованный убыток, а не предсказывает — значит помогает
на ХВОСТЕ окна, но не защищает от первого удара. Ожидается ЧАСТИЧНАЯ защита, но не полная.
Разложение по цене (c=0 vs c=96) покажет: сигнальная часть или только пошлина?

ДАННЫЕ: фикстура 5 книг × 699 дней [bt] 2024-07-01 … 2026-05-31.
L0, IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True. Реальная панель не доступна (облачный checkout),
честно объявлено в оговорках. #80 CSS-фреймворк: развёртка по цене (c=0…384).

stdlib-only. LLM_FORBIDDEN. Детерминировано.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from spa_core.strategy_lab.aggressive_lab.fixtures import strategy_jsonl
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS

BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
INITIAL = 100_000.0
KAPPAS = [0.0, 1.0, 2.0, 5.0, 10.0, 20.0]
COST_GRID = [0, 6, 12, 24, 48, 96, 192, 384]
SPLIT_DATE = datetime.date(2025, 6, 30)


# ── data loading ─────────────────────────────────────────────────────────────

def _load_panel() -> Dict[str, List[Tuple[datetime.date, float]]]:
    """Daily returns per book from fixture backtest phase only."""
    panel: Dict[str, List[Tuple[datetime.date, float]]] = {}
    for book in BOOKS:
        rows: List[Tuple[datetime.date, float]] = []
        for line in strategy_jsonl(book).strip().split("\n"):
            rec = json.loads(line)
            if rec["phase"] != "backtest":
                continue
            rows.append((datetime.date.fromisoformat(rec["date"]), float(rec["equity_usd"])))
        rets: List[Tuple[datetime.date, float]] = []
        for i in range(1, len(rows)):
            d, eq = rows[i]
            prev_eq = rows[i - 1][1]
            rets.append((d, eq / prev_eq - 1.0))
        panel[book] = rets
    return panel


def _align(panel: Dict[str, List[Tuple[datetime.date, float]]]) -> Tuple[List[datetime.date], Dict[str, Dict[datetime.date, float]]]:
    date_sets = [set(d for d, _ in panel[b]) for b in BOOKS]
    common = sorted(set.intersection(*date_sets))
    rets_map = {b: {d: r for d, r in panel[b]} for b in BOOKS}
    return common, rets_map


# ── backtest engines ──────────────────────────────────────────────────────────

def _run_ew(dates: List[datetime.date], rets_map: Dict[str, Dict[datetime.date, float]], cost_bps: int) -> List[Tuple[datetime.date, float]]:
    """Equal-weight buy-and-hold (no rebalancing ⇒ weights drift; zero rebalance cost)."""
    n = len(BOOKS)
    # Track each book's equity from initial equal allocation
    book_eq: Dict[str, float] = {b: INITIAL / n for b in BOOKS}
    curve: List[Tuple[datetime.date, float]] = []
    for d in dates:
        for b in BOOKS:
            book_eq[b] *= (1.0 + rets_map[b][d])
        curve.append((d, sum(book_eq.values())))
    return curve


def _run_ddw(dates: List[datetime.date], rets_map: Dict[str, Dict[datetime.date, float]],
             kappa: float, cost_bps: int) -> List[Tuple[datetime.date, float]]:
    """Dynamic Drawdown Weighting: w_b ∝ 1/(1 + DD_b × kappa). Standalone peaks for signal."""
    cost_frac = cost_bps / 10_000.0
    n = len(BOOKS)

    # Standalone book equity (tracks each book independently for the drawdown signal)
    standalone: Dict[str, float] = {b: INITIAL for b in BOOKS}
    peaks: Dict[str, float] = {b: INITIAL for b in BOOKS}

    # Portfolio
    weights: Dict[str, float] = {b: 1.0 / n for b in BOOKS}
    portfolio_eq = INITIAL

    curve: List[Tuple[datetime.date, float]] = []

    for d in dates:
        # 1. Update standalone equities (signal source, no cost)
        for b in BOOKS:
            standalone[b] *= (1.0 + rets_map[b][d])
            if standalone[b] > peaks[b]:
                peaks[b] = standalone[b]

        # 2. Portfolio return with current weights
        port_ret = sum(weights[b] * rets_map[b][d] for b in BOOKS)
        portfolio_eq *= (1.0 + port_ret)

        # 3. Post-return current weights (after drift)
        book_val = {b: weights[b] * portfolio_eq * (1.0 + rets_map[b][d]) / (1.0 + port_ret) for b in BOOKS}
        total_val = sum(book_val.values())
        curr_w = {b: book_val[b] / total_val for b in BOOKS}

        # 4. Desired weights from drawdown signal
        if kappa == 0.0:
            target_w = {b: 1.0 / n for b in BOOKS}
        else:
            dd = {b: max(0.0, 1.0 - standalone[b] / peaks[b]) for b in BOOKS}
            raw = {b: 1.0 / (1.0 + dd[b] * kappa) for b in BOOKS}
            tot_raw = sum(raw.values())
            target_w = {b: raw[b] / tot_raw for b in BOOKS}

        # 5. Turnover and cost (half-turn: one-sided)
        turnover = 0.5 * sum(abs(target_w[b] - curr_w[b]) for b in BOOKS)
        portfolio_eq -= portfolio_eq * turnover * cost_frac

        weights = target_w
        curve.append((d, portfolio_eq))

    return curve


# ── metrics ───────────────────────────────────────────────────────────────────

def _metrics(curve: List[Tuple[datetime.date, float]]) -> Dict[str, float]:
    equities = [eq for _, eq in curve]
    n_days = len(equities)
    total_ret = equities[-1] / INITIAL
    n_years = n_days / 365.0
    apy = (total_ret ** (1.0 / n_years) - 1.0) * 100.0

    peak = INITIAL
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = max_dd * 100.0

    calmar = (apy / abs(max_dd_pct)) if max_dd_pct != 0 else 0.0

    # Turnover estimate: daily weight drift (approximated by abs return dispersion)
    # We don't track turnover separately here; we add it to run_ddw externally
    return {"apy_pct": round(apy, 2), "max_dd_pct": round(max_dd_pct, 2), "calmar": round(calmar, 4)}


def _turnover_per_year(dates: List[datetime.date], rets_map: Dict[str, Dict[datetime.date, float]],
                       kappa: float) -> float:
    """Compute annualised turnover for DDW (kappa, c=0) without cost drag."""
    n = len(BOOKS)
    standalone = {b: INITIAL for b in BOOKS}
    peaks = {b: INITIAL for b in BOOKS}
    weights = {b: 1.0 / n for b in BOOKS}
    total_turnover = 0.0

    for d in dates:
        for b in BOOKS:
            standalone[b] *= (1.0 + rets_map[b][d])
            if standalone[b] > peaks[b]:
                peaks[b] = standalone[b]

        port_ret = sum(weights[b] * rets_map[b][d] for b in BOOKS)
        book_val = {b: weights[b] * (1.0 + rets_map[b][d]) / (1.0 + port_ret) for b in BOOKS}
        total_val = sum(book_val.values())
        curr_w = {b: book_val[b] / total_val for b in BOOKS}

        if kappa == 0.0:
            target_w = {b: 1.0 / n for b in BOOKS}
        else:
            dd = {b: max(0.0, 1.0 - standalone[b] / peaks[b]) for b in BOOKS}
            raw = {b: 1.0 / (1.0 + dd[b] * kappa) for b in BOOKS}
            tot_raw = sum(raw.values())
            target_w = {b: raw[b] / tot_raw for b in BOOKS}

        total_turnover += 0.5 * sum(abs(target_w[b] - curr_w[b]) for b in BOOKS)
        weights = target_w

    n_days = len(dates)
    return round(total_turnover * 365.0 / n_days, 4)


def _window_hit(curve: List[Tuple[datetime.date, float]], window_key: str) -> float:
    """Return the portfolio fractional return during a named stress window."""
    w = next((w for w in STRESS_WINDOWS if w["key"] == window_key), None)
    if w is None:
        return 0.0
    lo = datetime.date.fromisoformat(str(w["date_from"]))
    hi = datetime.date.fromisoformat(str(w["date_to"]))
    date_eq = {d: eq for d, eq in curve}
    dates_in_window = sorted(d for d in date_eq if lo <= d <= hi)
    if not dates_in_window:
        return 0.0
    before_dates = sorted(d for d in date_eq if d < lo)
    eq_before = date_eq[before_dates[-1]] if before_dates else INITIAL
    eq_after = date_eq[dates_in_window[-1]]
    return round((eq_after / eq_before - 1.0) * 100.0, 2)


def _split(curve: List[Tuple[datetime.date, float]]) -> Tuple[List, List]:
    train = [(d, eq) for d, eq in curve if d <= SPLIT_DATE]
    test = [(d, eq) for d, eq in curve if d > SPLIT_DATE]
    return train, test


def _split_metrics(curve: List[Tuple[datetime.date, float]], base_calmar: float) -> Dict[str, float]:
    train, test = _split(curve)
    if not train or not test:
        return {"train_dcal": 0.0, "test_dcal": 0.0}
    train_m = _metrics([(d, eq) for d, eq in train])
    test_m = _metrics([(d, eq) for d, eq in test])
    # Calmar needs base; use ratio to initial for each split
    # For train: equities start at INITIAL
    # For test: equities start at last train equity
    train_init = INITIAL
    test_init = train[-1][1] if train else INITIAL

    def _m_adjusted(part: List, init: float) -> Dict:
        if not part:
            return {"apy_pct": 0.0, "max_dd_pct": 0.0, "calmar": 0.0}
        equities = [eq for _, eq in part]
        n_days = len(equities)
        total_ret = equities[-1] / init
        n_years = n_days / 365.0
        apy = (total_ret ** (1.0 / n_years) - 1.0) * 100.0 if n_years > 0 else 0.0
        peak = init
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak
            if dd < max_dd:
                max_dd = dd
        max_dd_pct = max_dd * 100.0
        calmar = (apy / abs(max_dd_pct)) if max_dd_pct != 0 else 0.0
        return {"apy_pct": round(apy, 2), "max_dd_pct": round(max_dd_pct, 2), "calmar": round(calmar, 4)}

    train_m = _m_adjusted(train, train_init)
    test_m = _m_adjusted(test, test_init)
    return {
        "train_dcal": round(train_m["calmar"] - base_calmar, 4),
        "test_dcal": round(test_m["calmar"] - base_calmar, 4),
        "train_apy": train_m["apy_pct"],
        "test_apy": test_m["apy_pct"],
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run_backtest(cost_bps: int = 96) -> Dict:
    """Run full DDW analysis at given cost_bps. Returns structured results."""
    panel = _load_panel()
    dates, rets_map = _align(panel)

    # Baseline: equal-weight
    ew_curve = _run_ew(dates, rets_map, cost_bps)
    ew_m = _metrics(ew_curve)

    results = {"ew": ew_m, "ddw": {}}

    for kappa in KAPPAS:
        curve = _run_ddw(dates, rets_map, kappa, cost_bps)
        m = _metrics(curve)
        to = _turnover_per_year(dates, rets_map, kappa)
        dcal = round(m["calmar"] - ew_m["calmar"], 4)
        w_eth = _window_hit(curve, "eth_crash_2024_08")
        w_usde = _window_hit(curve, "usde_unwind_2025_10")
        w_rs = _window_hit(curve, "rseth_depeg_2026_04")
        sm = _split_metrics(curve, ew_m["calmar"])
        results["ddw"][kappa] = {
            **m, "dcalmar": dcal, "turnover": to,
            "eth_crash": w_eth, "usde_unwind": w_usde, "rseth_depeg": w_rs,
            **sm,
        }

    return results


def run_price_sweep() -> Dict:
    """CSS-style: ΔCalmar(kappa=10) across cost_bps=0..384."""
    panel = _load_panel()
    dates, rets_map = _align(panel)
    sweep = {}
    for c in COST_GRID:
        ew_curve = _run_ew(dates, rets_map, c)
        ew_m = _metrics(ew_curve)
        row = {}
        for kappa in KAPPAS:
            curve = _run_ddw(dates, rets_map, kappa, c)
            m = _metrics(curve)
            row[kappa] = round(m["calmar"] - ew_m["calmar"], 4)
        sweep[c] = row
    return sweep


def main() -> None:
    print("=" * 72)
    print("IDEA #85 — DDW: Dynamic Drawdown Weighting [bt, фикстура, L0]")
    print(f"  Книг: {len(BOOKS)}, дней: 699 (2024-07-01…2026-05-31)")
    print(f"  Кost_bps=96. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True")
    print("=" * 72)

    res = run_backtest(96)
    ew = res["ew"]
    print(f"\nБАЗА Equal-Weight: APY {ew['apy_pct']:.2f}% / "
          f"maxDD {ew['max_dd_pct']:.2f}% / Calmar {ew['calmar']:.4f}")

    print(f"\n{'kappa':>8} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8} {'ΔCal':>8} "
          f"{'TO/год':>8} {'eth':>8} {'usde':>8} {'rseth':>8} {'trΔCal':>8} {'tsΔCal':>8}")
    print("-" * 100)
    for kappa in KAPPAS:
        d = res["ddw"][kappa]
        print(f"{kappa:>8.1f} {d['apy_pct']:>8.2f} {d['max_dd_pct']:>8.2f} "
              f"{d['calmar']:>8.4f} {d['dcalmar']:>8.4f} {d['turnover']:>8.2f} "
              f"{d['eth_crash']:>8.2f} {d['usde_unwind']:>8.2f} {d['rseth_depeg']:>8.2f} "
              f"{d['train_dcal']:>8.4f} {d['test_dcal']:>8.4f}")

    print("\n\nРАЗВЁРТКА ПО ЦЕНЕ (ΔCalmar, строки=cost_bps, столбцы=kappa):")
    sweep = run_price_sweep()
    col_hdr = "c\\k"
    header = f"{col_hdr:>6}" + "".join(f"{k:>10.1f}" for k in KAPPAS)
    print(header)
    print("-" * (6 + 10 * len(KAPPAS)))
    for c in COST_GRID:
        row = f"{c:>6}"
        for kappa in KAPPAS:
            row += f"{sweep[c][kappa]:>10.4f}"
        print(row)

    print("\n\nВЫВОД:")
    best_dcal_c0 = max(res_c0["dcalmar"] for kappa, res_c0 in {
        k: {**d, "dcalmar": d["dcalmar"]} for k, d in res["ddw"].items()
    }.items() if kappa > 0)
    print(f"  Лучший ΔCalmar при c=96: {max(d['dcalmar'] for k, d in res['ddw'].items() if k > 0):.4f}")

    # c=0 sweep
    sweep_c0 = sweep[0]
    best_kappa_c0 = max((k for k in KAPPAS if k > 0), key=lambda k: sweep_c0[k])
    print(f"  Лучший ΔCalmar при c=0: {sweep_c0[best_kappa_c0]:.4f} (kappa={best_kappa_c0})")
    structural = sweep_c0[best_kappa_c0] > 0
    print(f"  Структурное прочтение (ΔCal>0 при c=0): {'✅ ДА' if structural else '❌ НЕТ'}")


if __name__ == "__main__":
    main()
