"""
scripts/edge_risk_shape_adaptive_blend.py

#139 RSAB: Risk-Shape Adaptive Blend — «размещать капитал с учётом уникальности
risk_shape стратегий, и временно сокращать долю shape когда любая из его стратегий
входит в просадку».

Идея: первые 138 записей реестра аллоцировали капитал исключительно по историческим
метрикам доходности/риска (дрейф, просадка, волатильность, Calmar, etc.) и никогда по
МЕТАДАННЫМ risk_shape. Фикстура предоставляет явный risk_shape для каждой стратегии:
    susde_dn    → funding_flip  (1 стратегия)
    lrt_carry   → depeg         (2 стратегии — shared с variant_d)
    leverage_loop → liquidation  (1 стратегия)
    points_farm → incentive_decay (1 стратегия)
    variant_d   → depeg         (shared с lrt_carry)

Гипотеза: (А) СТАТИЧНЫЙ вариант: стратегии с уникальным shape должны получать больший
вес, чем стратегии делящие shape (диверсификация по хвостовым факторам риска). (Б)
АДАПТИВНЫЙ вариант: когда любая стратегия данного shape входит в просадку ≥ threshold,
временно сокращать ВЕСЬ данный shape на γ и перераспределять высвободившееся в другие.

Предсказание: (1) адаптивный RSAB улучшает maxDD в rseth_depeg_2026_04, где ОБЕ
depeg-стратегии (lrt_carry −22%, variant_d −20%) одновременно получают удар — сигнал
активируется ДО пика потерь; (2) статичный RSAB улучшает maxDD во всех окнах за счёт
систематического недовеса depeg-кластера.

Новизна vs реестр: ни одна из 138 записей не использует risk_shape как сигнал аллокации.
#44 RCD использует корреляцию доходностей (blind to shape); #40/#39/#45 используют
дрейф/волатильность. Данный сигнал использует ДЕКЛАРИРОВАННЫЙ риск-класс из meta.json.

stdlib-only, детерминированная фикстура. LLM FORBIDDEN. IS_ADVISORY=True.
OUTSIDE_RISKPOLICY=True. RiskPolicy v1.0 не тронута.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.aggressive_lab.fixtures import strategy_jsonl, strategy_meta, roster, _SPEC
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS

# ── константы ────────────────────────────────────────────────────────────────
STRATEGIES = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
COST_BPS = 96.0          # 96 bp per round-trip of overweight
RATES_DAILY = 3.4 / 100.0 / 365.0  # RWA floor ~3.4%
CAP_PER_NAME = 0.40      # 40% per-name cap (T1 RiskPolicy v1.0)
FLOOR_WEIGHT = 0.02      # 2% minimum weight per strategy (防止нулевых весов)

# Параметры адаптивного RSAB
LOOKBACK_L = 10          # окно для обнаружения просадки shape (дней)
DRAWDOWN_THRESHOLD = 0.005  # 0.5% — порог просадки для активации shape-de-risk
GAMMA_DERISKED = 0.40    # коэффициент сокращения веса активного shape (40% от базы)
N_COOL_DOWN = 5          # дней без просадки перед снятием de-risk (аналог M в CDR)

# ── загрузка фикстурных данных ────────────────────────────────────────────────
def load_fixture_series(strategy_id: str) -> List[dict]:
    """Загрузить backtest-серию (phase="backtest") из фикстуры."""
    jsonl = strategy_jsonl(strategy_id)
    rows = []
    for line in jsonl.strip().split("\n"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("phase") == "backtest":
            rows.append(r)
    return rows


def build_returns_matrix() -> Tuple[List[str], List[datetime.date], Dict[str, List[float]]]:
    """Построить матрицу ежедневных доходностей из фикстуры.
    Возвращает (dates, {strategy_id: [daily_return]}). Инвариант #17: NaN при отсутствии.
    """
    all_series = {}
    for sid in STRATEGIES:
        rows = load_fixture_series(sid)
        all_series[sid] = rows

    # общий диапазон дат
    dates_per_strategy = {sid: [r["date"] for r in rows] for sid, rows in all_series.items()}
    all_dates_strs = sorted(set(d for dates in dates_per_strategy.values() for d in dates))
    all_dates = [datetime.date.fromisoformat(d) for d in all_dates_strs]

    # дневные доходности r(t) = equity(t)/equity(t-1) - 1
    returns: Dict[str, List[Optional[float]]] = {sid: [] for sid in STRATEGIES}
    for sid in STRATEGIES:
        eq_map = {r["date"]: r["equity_usd"] for r in all_series[sid]}
        for i, d in enumerate(all_dates):
            d_str = d.isoformat()
            if i == 0 or d_str not in eq_map:
                returns[sid].append(None)
                continue
            prev_d_str = all_dates[i - 1].isoformat()
            if prev_d_str not in eq_map:
                returns[sid].append(None)
                continue
            returns[sid].append(eq_map[d_str] / eq_map[prev_d_str] - 1.0)

    # убрать первый день (None) — стандарт фикстуры
    valid_start = 1
    dates = all_dates[valid_start:]
    returns_out = {sid: returns[sid][valid_start:] for sid in STRATEGIES}
    return STRATEGIES, dates, returns_out


# ── аллокатор ────────────────────────────────────────────────────────────────
def risk_shape_base_weights() -> Dict[str, float]:
    """Статичные веса: 1/(количество стратегий данного shape), нормированные на 1."""
    shape_counts: Dict[str, int] = {}
    shapes: Dict[str, str] = {}
    for sid in STRATEGIES:
        sh = _SPEC[sid]["risk_shape"]
        shapes[sid] = sh
        shape_counts[sh] = shape_counts.get(sh, 0) + 1

    # вес стратегии = 1/count(shape), нормированный
    raw = {sid: 1.0 / shape_counts[shapes[sid]] for sid in STRATEGIES}
    total = sum(raw.values())
    return {sid: raw[sid] / total for sid in STRATEGIES}


def _compute_portfolio_path(
    dates: List[datetime.date],
    returns_dict: Dict[str, List[Optional[float]]],
    mode: str,
) -> Dict[str, float]:
    """Прогнать portfolio с заданным mode ('ew', 'static_rsab', 'adaptive_rsab').
    Возвращает dict с APY, maxDD, Calmar, per-window stats, cost_pct, наруд.

    Инвариант #3 (детерминизм) и #17 (absent=None): возвращает None для Calmar при maxDD=0.
    """
    N = len(STRATEGIES)
    base_weights = risk_shape_base_weights()
    shapes = {sid: _SPEC[sid]["risk_shape"] for sid in STRATEGIES}

    # отображение shape → стратегии
    shape_to_strats: Dict[str, List[str]] = {}
    for sid in STRATEGIES:
        sh = shapes[sid]
        shape_to_strats.setdefault(sh, []).append(sid)

    # инициальные веса
    if mode == "ew":
        weights = {sid: 1.0 / N for sid in STRATEGIES}
    elif mode == "static_rsab":
        weights = dict(base_weights)
    else:  # adaptive
        weights = dict(base_weights)

    portfolio_equity = 100_000.0
    hwm = portfolio_equity
    max_dd = 0.0
    total_turnover = 0.0
    days_in_drawdown = 0

    # для адаптивного режима: отслеживаем текущее состояние shape
    shape_derisked: Dict[str, int] = {}  # shape → cool_down_counter (0 = active de-risk)
    shape_cool_counter: Dict[str, int] = {}  # shape → дней без просадки (для снятия de-risk)

    # для статистики по окнам
    window_data: Dict[str, Dict] = {}
    for w in STRESS_WINDOWS:
        window_data[w["key"]] = {
            "eq_start": None,
            "eq_min": None,
            "active": False,
        }

    # индивидуальные эквити для отслеживания shape-drawdown
    indiv_equity = {sid: 100_000.0 for sid in STRATEGIES}
    indiv_hwm = {sid: 100_000.0 for sid in STRATEGIES}

    per_day_returns = []

    for i, d in enumerate(dates):
        # 1. считаем доходности стратегий в день d
        day_rets: Dict[str, Optional[float]] = {sid: returns_dict[sid][i] for sid in STRATEGIES}
        if any(r is None for r in day_rets.values()):
            continue

        # 2. обновляем индивидуальные эквити (для сигнала просадки в адаптивном режиме)
        for sid in STRATEGIES:
            indiv_equity[sid] = indiv_equity[sid] * (1.0 + day_rets[sid])
            indiv_hwm[sid] = max(indiv_hwm[sid], indiv_equity[sid])

        # 3. в адаптивном режиме: проверяем просадку по каждому shape
        if mode == "adaptive_rsab":
            new_weights = dict(base_weights)
            derisked_shapes = set()

            for sh, strats in shape_to_strats.items():
                # просадка любой стратегии shape
                max_shape_dd = max(
                    (indiv_hwm[sid] - indiv_equity[sid]) / indiv_hwm[sid]
                    for sid in strats
                )
                if max_shape_dd >= DRAWDOWN_THRESHOLD:
                    # shape в кризисе — де-рискуем
                    derisked_shapes.add(sh)
                    shape_cool_counter[sh] = 0  # сброс счётчика восстановления
                    for sid in strats:
                        new_weights[sid] = base_weights[sid] * (1.0 - GAMMA_DERISKED)
                else:
                    # кризиса нет — проверяем cool-down
                    if sh in shape_derisked:
                        shape_cool_counter[sh] = shape_cool_counter.get(sh, 0) + 1
                        if shape_cool_counter[sh] >= N_COOL_DOWN:
                            del shape_derisked[sh]  # тип dict, нет, это set
                            # скорректировано ниже

            # обновить shape_derisked (set)
            for sh in derisked_shapes:
                shape_derisked[sh] = True  # метка

            # для shape вышедших из кризиса — восстановить после N_COOL_DOWN
            shapes_to_restore = []
            for sh in list(shape_derisked.keys()) if isinstance(shape_derisked, dict) else []:
                pass
            # упрощённая реализация: shape_derisked как dict sh→bool
            # перепишем корректно ниже

            # нормировать новые веса
            total_w = sum(new_weights.values())
            weights = {sid: max(FLOOR_WEIGHT, new_weights[sid] / total_w) for sid in STRATEGIES}
            total_w2 = sum(weights.values())
            weights = {sid: weights[sid] / total_w2 for sid in STRATEGIES}

        # 4. применяем cap на имя
        for sid in STRATEGIES:
            weights[sid] = min(weights[sid], CAP_PER_NAME)
        total_w = sum(weights.values())
        weights = {sid: weights[sid] / total_w for sid in STRATEGIES}

        # 5. портфельная доходность
        port_ret = sum(weights[sid] * day_rets[sid] for sid in STRATEGIES)
        per_day_returns.append(port_ret)

        # 6. оборот (|Δw| × 0.5 для round-trip)
        prev_weights = weights  # (для простоты — считаем оборот как изменение весов от дня к дню)
        # (в данной реализации веса пересчитываются каждый день, turnover = 0 в штиле)
        # TODO: точный оборот = sum(|w_new - w_old|) / 2
        # для этого нужно хранить предыдущие веса

        # 7. эквити портфеля
        portfolio_equity = portfolio_equity * (1.0 + port_ret)
        hwm = max(hwm, portfolio_equity)
        dd = (hwm - portfolio_equity) / hwm if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        if dd > 0:
            days_in_drawdown += 1

        # 8. отслеживаем окна
        for w in STRESS_WINDOWS:
            lo = datetime.date.fromisoformat(str(w["date_from"]))
            hi = datetime.date.fromisoformat(str(w["date_to"]))
            wd = window_data[w["key"]]
            if lo <= d <= hi:
                if not wd["active"]:
                    wd["active"] = True
                    wd["eq_start"] = portfolio_equity
                    wd["eq_min"] = portfolio_equity
                else:
                    wd["eq_min"] = min(wd["eq_min"], portfolio_equity)
            elif d > hi and wd["active"]:
                pass  # окно закрыто

    # ── итоговые метрики ──────────────────────────────────────────────────────
    n_days = len(per_day_returns)
    total_return = portfolio_equity / 100_000.0 - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_days) - 1.0 if n_days > 0 else 0.0

    # приблизительный оборот (для режима adaptive): число дней где >1 shape de-risked / total_days
    narud = days_in_drawdown / n_days if n_days > 0 else 0.0

    calmar = None  # инвариант #17: нет наблюдения = None
    if max_dd > 1e-9:
        calmar = apy / max_dd

    # per-window losses
    window_losses = {}
    for w in STRESS_WINDOWS:
        wd = window_data[w["key"]]
        if wd["eq_start"] is not None and wd["eq_min"] is not None and wd["eq_start"] > 0:
            loss = (wd["eq_start"] - wd["eq_min"]) / wd["eq_start"]
            window_losses[w["key"]] = loss
        else:
            window_losses[w["key"]] = None  # инвариант #17

    return {
        "apy_pct": round(apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3) if calmar is not None else None,
        "narud_pct": round(narud * 100, 1),
        "window_losses": {k: (round(v * 100, 2) if v is not None else None)
                          for k, v in window_losses.items()},
    }


def _compute_single_leg(sid: str, dates: List[datetime.date],
                         returns_dict: Dict[str, List[Optional[float]]]) -> Dict:
    """Одна стратегия без аллокационного правила."""
    equity = 100_000.0
    hwm = equity
    max_dd = 0.0
    rets = returns_dict[sid]
    n = 0

    for r in rets:
        if r is None:
            continue
        equity = equity * (1.0 + r)
        hwm = max(hwm, equity)
        dd = (hwm - equity) / hwm if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        n += 1

    total_return = equity / 100_000.0 - 1.0
    apy = (1.0 + total_return) ** (365.0 / n) - 1.0 if n > 0 else 0.0
    calmar = (apy / max_dd) if max_dd > 1e-9 else None
    return {
        "apy_pct": round(apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3) if calmar is not None else None,
    }


# ── правильная реализация adaptive_rsab ──────────────────────────────────────
def compute_adaptive_rsab(
    dates: List[datetime.date],
    returns_dict: Dict[str, List[Optional[float]]],
) -> Dict:
    """
    Адаптивный RSAB с правильным отслеживанием состояния shape.
    shape_state[sh] = 0  : idle (нет де-риска)
    shape_state[sh] = k  : де-рискован, k дней подряд без просадки (0..N_COOL_DOWN-1)
    shape_state[sh] = ACTIVE : де-рискован, обнаружена просадка сегодня
    """
    base_w = risk_shape_base_weights()
    shapes = {sid: _SPEC[sid]["risk_shape"] for sid in STRATEGIES}
    shape_to_strats: Dict[str, List[str]] = {}
    for sid in STRATEGIES:
        shape_to_strats.setdefault(shapes[sid], []).append(sid)

    # состояние каждого shape: None = idle, int >= 0 = cool_down days counter
    shape_active: Dict[str, bool] = {sh: False for sh in shape_to_strats}
    shape_cool: Dict[str, int] = {sh: 0 for sh in shape_to_strats}

    portfolio_equity = 100_000.0
    hwm = portfolio_equity
    max_dd = 0.0
    days_in_drawdown = 0

    indiv_equity = {sid: 100_000.0 for sid in STRATEGIES}
    indiv_hwm = {sid: 100_000.0 for sid in STRATEGIES}

    prev_weights: Optional[Dict[str, float]] = None
    total_turnover_abs = 0.0
    n_valid = 0

    window_data: Dict[str, Dict] = {}
    for w in STRESS_WINDOWS:
        window_data[w["key"]] = {"eq_start": None, "eq_min": None, "active": False, "eq_after": None}

    for i, d in enumerate(dates):
        day_rets: Dict[str, Optional[float]] = {sid: returns_dict[sid][i] for sid in STRATEGIES}
        if any(r is None for r in day_rets.values()):
            continue

        # обновить индивидуальные эквити
        for sid in STRATEGIES:
            indiv_equity[sid] = indiv_equity[sid] * (1.0 + day_rets[sid])
            indiv_hwm[sid] = max(indiv_hwm[sid], indiv_equity[sid])

        # определить текущее состояние каждого shape и обновить веса
        new_weights = {}
        for sh, strats in shape_to_strats.items():
            # вычислить просадку shape (макс по стратегиям)
            shape_dd = max(
                (indiv_hwm[sid] - indiv_equity[sid]) / indiv_hwm[sid]
                for sid in strats
            )
            if shape_dd >= DRAWDOWN_THRESHOLD:
                # shape в кризисе → включаем де-риск, сбрасываем cool-down
                shape_active[sh] = True
                shape_cool[sh] = 0
            elif shape_active[sh]:
                # shape не в кризисе сегодня, но был → тикаем cool-down
                shape_cool[sh] += 1
                if shape_cool[sh] >= N_COOL_DOWN:
                    shape_active[sh] = False  # снимаем де-риск
                    shape_cool[sh] = 0

            # применить вес
            if shape_active[sh]:
                scale = 1.0 - GAMMA_DERISKED  # =0.6 от базы
            else:
                scale = 1.0
            for sid in strats:
                new_weights[sid] = base_w[sid] * scale

        # нормировать + floor + cap
        total_w = sum(new_weights.values())
        for sid in STRATEGIES:
            new_weights[sid] = max(FLOOR_WEIGHT, new_weights[sid] / total_w)
        total_w2 = sum(new_weights.values())
        for sid in STRATEGIES:
            new_weights[sid] = min(CAP_PER_NAME, new_weights[sid] / total_w2)
        total_w3 = sum(new_weights.values())
        weights = {sid: new_weights[sid] / total_w3 for sid in STRATEGIES}

        # оборот
        if prev_weights is not None:
            turnover = sum(abs(weights[sid] - prev_weights[sid]) for sid in STRATEGIES) / 2.0
            total_turnover_abs += turnover
        prev_weights = dict(weights)
        n_valid += 1

        # доходность портфеля
        port_ret = sum(weights[sid] * day_rets[sid] for sid in STRATEGIES)
        portfolio_equity = portfolio_equity * (1.0 + port_ret)
        hwm = max(hwm, portfolio_equity)
        dd = (hwm - portfolio_equity) / hwm if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        if dd > DRAWDOWN_THRESHOLD / 2:
            days_in_drawdown += 1

        # окна
        for w in STRESS_WINDOWS:
            lo = datetime.date.fromisoformat(str(w["date_from"]))
            hi = datetime.date.fromisoformat(str(w["date_to"]))
            wd = window_data[w["key"]]
            if lo <= d <= hi:
                if not wd["active"]:
                    wd["active"] = True
                    wd["eq_start"] = portfolio_equity / (1.0 + port_ret)  # equity ПЕРЕД окном
                    wd["eq_min"] = portfolio_equity
                else:
                    wd["eq_min"] = min(wd["eq_min"] if wd["eq_min"] else portfolio_equity,
                                       portfolio_equity)

    total_return = portfolio_equity / 100_000.0 - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_valid) - 1.0 if n_valid > 0 else 0.0
    calmar = (apy / max_dd) if max_dd > 1e-9 else None
    turnover_per_year = total_turnover_abs / (n_valid / 365.0) if n_valid > 0 else 0.0
    cost_pct = total_turnover_abs * (COST_BPS / 10_000.0) * 100.0
    net_apy_pct = apy * 100 - cost_pct / (n_valid / 365.0)

    window_losses = {}
    for w in STRESS_WINDOWS:
        wd = window_data[w["key"]]
        if wd.get("eq_start") and wd.get("eq_min") and wd["eq_start"] > 0:
            loss = (wd["eq_start"] - wd["eq_min"]) / wd["eq_start"]
            window_losses[w["key"]] = round(loss * 100, 2)
        else:
            window_losses[w["key"]] = None

    return {
        "apy_pct": round(apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3) if calmar is not None else None,
        "net_apy_pct": round(net_apy_pct, 3),
        "turnover_per_year": round(turnover_per_year, 2),
        "narud_pct": round(days_in_drawdown / n_valid * 100, 1) if n_valid > 0 else None,
        "window_losses": window_losses,
    }


def compute_ew(dates, returns_dict):
    """EW-5 baseline (равновес по 5 стратегиям)."""
    portfolio_equity = 100_000.0
    hwm = portfolio_equity
    max_dd = 0.0
    n_valid = 0
    weights = {sid: 1.0 / len(STRATEGIES) for sid in STRATEGIES}
    window_data = {w["key"]: {"eq_start": None, "eq_min": None, "active": False}
                   for w in STRESS_WINDOWS}

    for i, d in enumerate(dates):
        day_rets = {sid: returns_dict[sid][i] for sid in STRATEGIES}
        if any(r is None for r in day_rets.values()):
            continue
        port_ret = sum(weights[sid] * day_rets[sid] for sid in STRATEGIES)
        portfolio_equity = portfolio_equity * (1.0 + port_ret)
        hwm = max(hwm, portfolio_equity)
        dd = (hwm - portfolio_equity) / hwm if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        n_valid += 1
        for w in STRESS_WINDOWS:
            lo = datetime.date.fromisoformat(str(w["date_from"]))
            hi = datetime.date.fromisoformat(str(w["date_to"]))
            wd = window_data[w["key"]]
            if lo <= d <= hi:
                if not wd["active"]:
                    wd["active"] = True
                    wd["eq_start"] = portfolio_equity / (1.0 + port_ret)
                    wd["eq_min"] = portfolio_equity
                else:
                    wd["eq_min"] = min(wd["eq_min"] or portfolio_equity, portfolio_equity)

    total_return = portfolio_equity / 100_000.0 - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_valid) - 1.0 if n_valid > 0 else 0.0
    calmar = (apy / max_dd) if max_dd > 1e-9 else None
    wl = {}
    for w in STRESS_WINDOWS:
        wd = window_data[w["key"]]
        if wd.get("eq_start") and wd.get("eq_min") and wd["eq_start"] > 0:
            wl[w["key"]] = round((wd["eq_start"] - wd["eq_min"]) / wd["eq_start"] * 100, 2)
        else:
            wl[w["key"]] = None
    return {
        "apy_pct": round(apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3) if calmar is not None else None,
        "window_losses": wl,
    }


def compute_static_rsab(dates, returns_dict):
    """Статичный RSAB: веса фиксированы по диверсификации risk_shape."""
    base_w = risk_shape_base_weights()
    portfolio_equity = 100_000.0
    hwm = portfolio_equity
    max_dd = 0.0
    n_valid = 0
    prev_weights = None
    total_turnover_abs = 0.0
    window_data = {w["key"]: {"eq_start": None, "eq_min": None, "active": False}
                   for w in STRESS_WINDOWS}

    for i, d in enumerate(dates):
        day_rets = {sid: returns_dict[sid][i] for sid in STRATEGIES}
        if any(r is None for r in day_rets.values()):
            continue

        weights = dict(base_w)
        if prev_weights is not None:
            turnover = sum(abs(weights[sid] - prev_weights[sid]) for sid in STRATEGIES) / 2.0
            total_turnover_abs += turnover
        prev_weights = dict(weights)

        port_ret = sum(weights[sid] * day_rets[sid] for sid in STRATEGIES)
        portfolio_equity = portfolio_equity * (1.0 + port_ret)
        hwm = max(hwm, portfolio_equity)
        dd = (hwm - portfolio_equity) / hwm if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        n_valid += 1

        for w in STRESS_WINDOWS:
            lo = datetime.date.fromisoformat(str(w["date_from"]))
            hi = datetime.date.fromisoformat(str(w["date_to"]))
            wd = window_data[w["key"]]
            if lo <= d <= hi:
                if not wd["active"]:
                    wd["active"] = True
                    wd["eq_start"] = portfolio_equity / (1.0 + port_ret)
                    wd["eq_min"] = portfolio_equity
                else:
                    wd["eq_min"] = min(wd["eq_min"] or portfolio_equity, portfolio_equity)

    total_return = portfolio_equity / 100_000.0 - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_valid) - 1.0 if n_valid > 0 else 0.0
    calmar = (apy / max_dd) if max_dd > 1e-9 else None
    cost_pct = total_turnover_abs * (COST_BPS / 10_000.0) * 100.0
    net_apy_pct = apy * 100 - cost_pct / (n_valid / 365.0)
    turnover_per_year = total_turnover_abs / (n_valid / 365.0) if n_valid > 0 else 0.0
    wl = {}
    for w in STRESS_WINDOWS:
        wd = window_data[w["key"]]
        if wd.get("eq_start") and wd.get("eq_min") and wd["eq_start"] > 0:
            wl[w["key"]] = round((wd["eq_start"] - wd["eq_min"]) / wd["eq_start"] * 100, 2)
        else:
            wl[w["key"]] = None
    return {
        "apy_pct": round(apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3) if calmar is not None else None,
        "net_apy_pct": round(net_apy_pct, 3),
        "turnover_per_year": round(turnover_per_year, 2),
        "window_losses": wl,
    }


def main():
    print("=" * 70)
    print("#139 RSAB: Risk-Shape Adaptive Blend — backtest на фикстуре")
    print("=" * 70)
    print(f"Стратегии: {STRATEGIES}")
    print(f"Параметры: L={LOOKBACK_L}d, dd_thr={DRAWDOWN_THRESHOLD*100:.1f}%,")
    print(f"           γ_derisked={GAMMA_DERISKED:.2f}, N_cool={N_COOL_DOWN}d, cost={COST_BPS}bp")
    print()

    # базовые веса
    base_w = risk_shape_base_weights()
    print("Статичные RSAB веса (по risk_shape diversity):")
    shapes = {sid: _SPEC[sid]["risk_shape"] for sid in STRATEGIES}
    for sid in STRATEGIES:
        print(f"  {sid:16s}  shape={shapes[sid]:18s}  w={base_w[sid]*100:.1f}%")
    print()

    # загрузка данных
    strat_ids, dates, returns_dict = build_returns_matrix()
    n_days = sum(1 for r in returns_dict[STRATEGIES[0]] if r is not None)
    print(f"Загружено: {n_days} дней backtest фикстуры "
          f"({dates[0].isoformat()} … {dates[-1].isoformat()})")
    print()

    # 1. EW-5 baseline
    ew = compute_ew(dates, returns_dict)
    print("ОСНОВНАЯ ТАБЛИЦА [bt] [L0] (96 bp на оборот):")
    print()
    hdr = f"{'конфигурация':32s}  {'APY%':>8}  {'maxDD%':>8}  {'Calmar':>8}  {'netAPY%':>9}"
    print(hdr)
    print("-" * 70)

    def fmt_row(label, res, show_net=False):
        cal = f"{res['calmar']:.3f}" if res['calmar'] is not None else "ОТКАЗАН"
        net = f"{res.get('net_apy_pct', res['apy_pct']):.3f}" if show_net else f"{res['apy_pct']:.3f}"
        print(f"{label:32s}  {res['apy_pct']:>8.3f}  {res['max_dd_pct']:>8.3f}  "
              f"{cal:>8}  {net:>9}")

    fmt_row("EW-5 (baseline)", ew)

    # 2. single-leg стратегии
    for sid in STRATEGIES:
        sl = _compute_single_leg(sid, dates, returns_dict)
        sh = _SPEC[sid]["risk_shape"]
        label = f"single-leg {sid} ({sh[:8]})"
        fmt_row(label, sl)

    # 3. статичный RSAB
    static_r = compute_static_rsab(dates, returns_dict)
    fmt_row("static RSAB", static_r, show_net=True)

    # 4. адаптивный RSAB
    adaptive_r = compute_adaptive_rsab(dates, returns_dict)
    fmt_row("adaptive RSAB", adaptive_r, show_net=True)

    print()
    print("PER-WINDOW LOSSES (портфельные просадки в каждом кризисном окне):")
    win_hdr = f"{'окно':30s}  {'EW-5':>8}  {'static':>8}  {'adaptive':>8}  {'delta_s':>8}  {'delta_a':>8}"
    print(win_hdr)
    print("-" * 80)
    for w in STRESS_WINDOWS:
        k = w["key"]
        ew_l = ew["window_losses"].get(k)
        st_l = static_r["window_losses"].get(k)
        ad_l = adaptive_r["window_losses"].get(k)
        fmt_e = f"{ew_l:.2f}%" if ew_l is not None else "N/A"
        fmt_s = f"{st_l:.2f}%" if st_l is not None else "N/A"
        fmt_a = f"{ad_l:.2f}%" if ad_l is not None else "N/A"
        delta_s = f"{(ew_l - st_l):.2f}pp" if (ew_l is not None and st_l is not None) else "N/A"
        delta_a = f"{(ew_l - ad_l):.2f}pp" if (ew_l is not None and ad_l is not None) else "N/A"
        print(f"{k:30s}  {fmt_e:>8}  {fmt_s:>8}  {fmt_a:>8}  {delta_s:>8}  {delta_a:>8}")

    print()
    print("ДЕТАЛИ ADAPTIVE RSAB:")
    print(f"  Gross APY:        {adaptive_r['apy_pct']:.3f}%")
    print(f"  maxDD:            {adaptive_r['max_dd_pct']:.3f}%")
    print(f"  Calmar (gross):   {adaptive_r['calmar']}")
    print(f"  Net APY (96bp):   {adaptive_r['net_apy_pct']:.3f}%")
    print(f"  Turnover/year:    {adaptive_r['turnover_per_year']:.2f}")
    print(f"  Days in DD (%):   {adaptive_r['narud_pct']}")

    print()
    print("ДЕТАЛИ STATIC RSAB:")
    print(f"  Gross APY:        {static_r['apy_pct']:.3f}%")
    print(f"  maxDD:            {static_r['max_dd_pct']:.3f}%")
    print(f"  Calmar (gross):   {static_r['calmar']}")
    print(f"  Net APY (96bp):   {static_r['net_apy_pct']:.3f}%")
    print(f"  Turnover/year:    {static_r['turnover_per_year']:.2f}")

    print()
    print("ВЫВОД (предварительный, см. честные оговорки ниже):")
    ew_cal = ew['calmar'] or 0.0
    ad_cal = adaptive_r['calmar'] or 0.0
    st_cal = static_r['calmar'] or 0.0
    delta_static = st_cal - ew_cal
    delta_adaptive = ad_cal - ew_cal
    print(f"  ΔCalmar (static vs EW):   {delta_static:+.3f}")
    print(f"  ΔCalmar (adaptive vs EW): {delta_adaptive:+.3f}")
    print()
    print("Честные оговорки:")
    print("  (а) [bt] [L0]: синтетическая фикстура, σ²=0 в штиле —")
    print("      shape-signal в спокойные дни = 0 переключений (нет просадки).")
    print("  (б) points_farm (RiskClass D) имеет минимальные hit'ы в фикстуре,")
    print("      что не отражает реальный incentive-decay APY.")
    print("  (в) Статичный RSAB даёт РАЗНЫЕ веса по сравнению с EW только за счёт")
    print("      разного кол-ва стратегий на shape, что на фикстуре эквивалентно")
    print("      фиксированному недовесу depeg-кластера (lrt+variant_d).")
    print("  (г) Адаптивный RSAB в штиле = статичному RSAB (нет dd ≥ 0.5%).")
    print("  (д) IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True; трек не открывался.")
    print()


if __name__ == "__main__":
    main()
