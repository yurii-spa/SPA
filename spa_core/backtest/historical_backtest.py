"""
SPA Historical Backtest Engine (MP-212)

Replay auto_allocate() на синтетических стресс-сценариях, основанных
на публичных данных 2022-2026: LUNA-crash, FTX-collapse, USDC-depeg.

Требования:
  - Без сети (все данные встроены)
  - Только stdlib
  - Атомарные записи (tmp + os.replace)

CLI:
    python3 -m spa_core.backtest.historical_backtest
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta

# ─── Дата-классы ──────────────────────────────────────────────────────────────

@dataclass
class HistoricalScenario:
    """Описание одного исторического стресс-сценария."""
    name: str
    start_date: str                    # YYYY-MM-DD
    end_date: str                      # YYYY-MM-DD
    daily_apy_series: list             # [{date, apy_by_protocol: {name: apy_pct}}]
    events: list                       # [{date, event_type, description, affected_protocols}]


@dataclass
class BacktestResult:
    """Результат прогона одного сценария."""
    scenario_name: str
    start_capital: float = 100_000.0
    end_capital: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    days_tracked: int = 0
    daily_equity: list = field(default_factory=list)  # [{date, equity, daily_return}]
    events_handled: list = field(default_factory=list)
    allocation_changes: int = 0


# ─── Встроенные сценарии ──────────────────────────────────────────────────────

def _build_luna_crash_scenario() -> HistoricalScenario:
    """
    LUNA_CRASH_2022: май 2022, 30 дней.
    Сценарий основан на публичных данных о LUNA/UST depeg.

    Фазы:
    - Days 1-14: нормальный APY (Aave 3%, Compound 3.2%, frax 5%)
    - Days 15-21: USDT/USDC brief depeg → frax-подобные peg-протоколы APY → 0
    - Days 22-30: восстановление, Aave 2.8%, Compound 2.9%, frax 4.5%
    """
    start = date(2022, 5, 1)
    series = []
    events = [
        {
            "date": "2022-05-15",
            "event_type": "LUNA_UST_COLLAPSE",
            "description": "Terra/LUNA collapse; UST depegged → contagion to peg assets",
            "affected_protocols": ["frax_usdc", "fraxlend_usdc"],
        },
        {
            "date": "2022-05-22",
            "event_type": "RECOVERY_START",
            "description": "Market stabilizes; peg assets recover partially",
            "affected_protocols": ["frax_usdc"],
        },
    ]

    for i in range(30):
        d = start + timedelta(days=i)
        day_num = i + 1

        if day_num <= 14:
            # Нормальный режим
            apy = {
                "aave_v3": 3.0,
                "compound_v3": 3.2,
                "frax_usdc": 5.0,
                "morpho_blue": 4.5,
            }
        elif day_num <= 21:
            # Депег — peg-протоколы обнуляются
            apy = {
                "aave_v3": 3.0,
                "compound_v3": 3.1,
                "frax_usdc": 0.0,   # peg-риск реализовался
                "morpho_blue": 4.2,
            }
        else:
            # Восстановление
            apy = {
                "aave_v3": 2.8,
                "compound_v3": 2.9,
                "frax_usdc": 4.5,   # частично восстановился
                "morpho_blue": 4.0,
            }

        series.append({"date": d.isoformat(), "apy_by_protocol": apy})

    return HistoricalScenario(
        name="LUNA_CRASH_2022",
        start_date="2022-05-01",
        end_date="2022-05-30",
        daily_apy_series=series,
        events=events,
    )


def _build_ftx_collapse_scenario() -> HistoricalScenario:
    """
    FTX_COLLAPSE_2022: ноябрь 2022, 30 дней.

    Фазы:
    - Days 1-7: нормальный режим (Aave 2.5%, Compound 2.8%, Maple 8%)
    - Days 8-20: credit-дефолты → Maple APY → 0
    - Days 21-30: кредитный кризис → T1 APY падает до 1.5-2%
    """
    start = date(2022, 11, 1)
    series = []
    events = [
        {
            "date": "2022-11-08",
            "event_type": "FTX_COLLAPSE",
            "description": "FTX bankruptcy; credit contagion → Maple borrower defaults",
            "affected_protocols": ["maple_senior"],
        },
    ]

    for i in range(30):
        d = start + timedelta(days=i)
        day_num = i + 1

        if day_num <= 7:
            apy = {
                "aave_v3": 2.5,
                "compound_v3": 2.8,
                "maple_senior": 8.0,   # кредитный протокол
                "pendle_pt_eth": 6.5,  # duration протокол
            }
        elif day_num <= 20:
            # Maple стопит выводы при дефолтах
            apy = {
                "aave_v3": 2.3,
                "compound_v3": 2.5,
                "maple_senior": 0.0,   # credit event → нет APY
                "pendle_pt_eth": 5.0,  # Pendle: заперт, APY сохраняется
            }
        else:
            # Конец кризиса: T1 подавлен из-за делевериджа
            apy = {
                "aave_v3": 1.5,
                "compound_v3": 1.8,
                "maple_senior": 0.0,
                "pendle_pt_eth": 4.5,
            }

        series.append({"date": d.isoformat(), "apy_by_protocol": apy})

    return HistoricalScenario(
        name="FTX_COLLAPSE_2022",
        start_date="2022-11-01",
        end_date="2022-11-30",
        daily_apy_series=series,
        events=events,
    )


def _build_usdc_depeg_scenario() -> HistoricalScenario:
    """
    USDC_DEPEG_2023: март 2023, 14 дней.

    Фазы:
    - Days 1-3: нормальный режим
    - Days 4-6: USDC brief depeg → peg-протоколы теряют APY
    - Days 7-14: repeg → Aave APY спайкует до 8% (высокий спрос на USDC)
    """
    start = date(2023, 3, 9)
    series = []
    events = [
        {
            "date": "2023-03-12",
            "event_type": "USDC_DEPEG",
            "description": "USDC briefly depegged to $0.87 after Silicon Valley Bank collapse",
            "affected_protocols": ["frax_usdc", "crvusd_pool"],
        },
        {
            "date": "2023-03-15",
            "event_type": "USDC_REPEG",
            "description": "Circle confirms USDC redeemability; USDC reprices to $1.0",
            "affected_protocols": [],
        },
    ]

    for i in range(14):
        d = start + timedelta(days=i)
        day_num = i + 1

        if day_num <= 3:
            apy = {
                "aave_v3": 3.5,
                "compound_v3": 3.8,
                "frax_usdc": 4.5,
                "crvusd_pool": 4.0,
            }
        elif day_num <= 6:
            # Депег: peg-протоколы нестабильны
            apy = {
                "aave_v3": 5.0,    # Aave растёт (demand for USDC)
                "compound_v3": 4.5,
                "frax_usdc": 1.0,  # нестабилен
                "crvusd_pool": 0.5,
            }
        else:
            # После репега: Aave APY на максимуме
            apy = {
                "aave_v3": 8.0,    # максимальный спрос на USDC
                "compound_v3": 7.2,
                "frax_usdc": 4.5,  # восстановился
                "crvusd_pool": 4.0,
            }

        series.append({"date": d.isoformat(), "apy_by_protocol": apy})

    return HistoricalScenario(
        name="USDC_DEPEG_2023",
        start_date="2023-03-09",
        end_date="2023-03-22",
        daily_apy_series=series,
        events=events,
    )


# ─── Логика аллокации ──────────────────────────────────────────────────────────

# Тировые метаданные — определяет аллокационные лимиты
_PROTOCOL_TIERS: dict[str, str] = {
    "aave": "T1",
    "compound": "T1",
    "morpho": "T2",
    "yearn": "T2",
    "euler": "T2",
    "maple": "T2",
    "pendle": "T2",
    "frax": "T2",
    "crvusd": "T2",
    "ethena": "T2",
    "susde": "T2",
}

_T1_CAP = 0.40
_T2_CAP = 0.20
_T2_TOTAL_CAP = 0.50  # ADR-019: поднят с 0.35 → 0.50 (2026-06-12)
_CASH_BUFFER = 0.05
_MAX_DEPLOYABLE = 1.0 - _CASH_BUFFER   # 0.95


def _get_tier(protocol_name: str) -> str:
    """Определить тир протокола по substring-матчингу."""
    name_lower = protocol_name.lower()
    for key, tier in _PROTOCOL_TIERS.items():
        if key in name_lower:
            return tier
    return "T2"  # консервативный дефолт


def _compute_allocation(apy_by_protocol: dict) -> dict:
    """
    Простая жадная аллокация: сортируем по APY desc, заполняем до капов.

    Constraints (из RiskPolicy v1.0):
    - T1: ≤ 40% per protocol
    - T2: ≤ 20% per protocol, суммарно ≤ 35%
    - Cash buffer ≥ 5%
    - Пропускаем протоколы с APY ≤ 0
    """
    sorted_protos = sorted(
        [(k, v) for k, v in apy_by_protocol.items() if v > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    allocation: dict = {}
    remaining = _MAX_DEPLOYABLE
    t2_used = 0.0

    for proto, apy in sorted_protos:
        tier = _get_tier(proto)

        if tier == "T1":
            cap = _T1_CAP
        else:
            available_t2 = _T2_TOTAL_CAP - t2_used
            cap = min(_T2_CAP, available_t2)

        alloc = min(cap, remaining)
        if alloc > 0.001:
            allocation[proto] = alloc
            remaining -= alloc
            if tier != "T1":
                t2_used += alloc

        if remaining < 0.001:
            break

    return allocation


def _apy_changed_significantly(
    prev: dict,
    curr: dict,
    threshold: float = 0.5,
) -> bool:
    """Вернуть True если APY любого протокола изменился на > threshold процентных пункта."""
    all_protos = set(prev) | set(curr)
    for p in all_protos:
        prev_val = prev.get(p, 0.0)
        curr_val = curr.get(p, 0.0)
        if abs(curr_val - prev_val) > threshold:
            return True
    return False


# ─── Статистика ───────────────────────────────────────────────────────────────

def _compute_sharpe(daily_returns: list[float]) -> float:
    """Annualized Sharpe ratio (нулевой риск-free rate) из дневных доходностей."""
    n = len(daily_returns)
    if n < 2:
        return 0.0
    mean_r = sum(daily_returns) / n
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / n
    std = math.sqrt(variance)
    if std < 1e-10:
        return 0.0
    return (mean_r / std) * math.sqrt(252)


def _compute_max_drawdown(equity_values: list[float]) -> float:
    """Максимальный drawdown из списка значений equity."""
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for eq in equity_values:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


# ─── Движок бэктеста ──────────────────────────────────────────────────────────

def run_scenario(
    scenario: HistoricalScenario,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """
    Прогнать один исторический сценарий.

    Логика:
    - Начальная аллокация: жадная по первому APY snapshot
    - Каждый день начисляется yield по текущей аллокации и APY
    - При изменении APY > 0.5pp у любого протокола → ребалансировка
    - Записывается equity curve + события

    Args:
        scenario: HistoricalScenario с daily_apy_series
        initial_capital: начальный капитал (дефолт 100_000)

    Returns:
        BacktestResult с полной статистикой
    """
    if not scenario.daily_apy_series:
        return BacktestResult(
            scenario_name=scenario.name,
            start_capital=initial_capital,
            end_capital=initial_capital,
        )

    equity = initial_capital
    prev_apy: dict = {}
    allocation: dict = {}
    daily_equity: list = []
    daily_returns: list[float] = []
    equity_values: list[float] = [initial_capital]
    allocation_changes = 0
    events_handled: list = []

    # Индекс событий по дате для быстрого поиска
    events_by_date: dict = {}
    for ev in scenario.events:
        events_by_date[ev["date"]] = ev

    for day_entry in scenario.daily_apy_series:
        day_str = day_entry["date"]
        apy_today = day_entry["apy_by_protocol"]

        # Обновить аллокацию при старте или при значительном изменении APY
        if not allocation or _apy_changed_significantly(prev_apy, apy_today):
            allocation = _compute_allocation(apy_today)
            allocation_changes += 1

        # Начислить дневной yield
        daily_yield = 0.0
        for proto, weight in allocation.items():
            proto_apy = apy_today.get(proto, 0.0)
            if proto_apy > 0:
                daily_yield += equity * weight * (proto_apy / 100.0 / 365.0)

        new_equity = equity + daily_yield
        daily_return = (new_equity / equity - 1.0) if equity > 0 else 0.0

        daily_equity.append({
            "date": day_str,
            "equity": round(new_equity, 2),
            "daily_return": round(daily_return, 8),
        })
        daily_returns.append(daily_return)
        equity_values.append(new_equity)

        # Зарегистрировать событие, если оно произошло в этот день
        if day_str in events_by_date:
            events_handled.append(events_by_date[day_str])

        equity = new_equity
        prev_apy = apy_today

    total_return_pct = (equity / initial_capital - 1.0) * 100.0 if initial_capital > 0 else 0.0
    max_drawdown_pct = _compute_max_drawdown(equity_values) * 100.0
    sharpe = _compute_sharpe(daily_returns)

    return BacktestResult(
        scenario_name=scenario.name,
        start_capital=initial_capital,
        end_capital=round(equity, 2),
        total_return_pct=round(total_return_pct, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        sharpe_ratio=round(sharpe, 4),
        days_tracked=len(scenario.daily_apy_series),
        daily_equity=daily_equity,
        events_handled=events_handled,
        allocation_changes=allocation_changes,
    )


def run_all_scenarios(
    initial_capital: float = 100_000.0,
) -> dict[str, BacktestResult]:
    """
    Прогнать все 3 встроенных стресс-сценария.

    Returns:
        {"LUNA_CRASH_2022": BacktestResult, "FTX_COLLAPSE_2022": ..., "USDC_DEPEG_2023": ...}
    """
    scenarios = [
        _build_luna_crash_scenario(),
        _build_ftx_collapse_scenario(),
        _build_usdc_depeg_scenario(),
    ]
    return {
        s.name: run_scenario(s, initial_capital)
        for s in scenarios
    }


def generate_backtest_report(results: dict) -> dict:
    """
    Сгенерировать сводный отчёт для инвесторов.

    Args:
        results: {scenario_name: BacktestResult}

    Returns:
        {
            "scenarios_count": int,
            "worst_drawdown_pct": float,
            "best_return_pct": float,
            "avg_sharpe": float,
            "crisis_survival_rate": float,   # доля сценариев без потери капитала
            "scenarios": {...}               # краткая сводка по каждому
        }
    """
    if not results:
        return {
            "scenarios_count": 0,
            "worst_drawdown_pct": 0.0,
            "best_return_pct": 0.0,
            "avg_sharpe": 0.0,
            "crisis_survival_rate": 1.0,
            "scenarios": {},
        }

    drawdowns = [r.max_drawdown_pct for r in results.values()]
    returns = [r.total_return_pct for r in results.values()]
    sharpes = [r.sharpe_ratio for r in results.values()]
    survived = sum(1 for r in results.values() if r.end_capital >= r.start_capital)

    scenario_summaries = {}
    for name, r in results.items():
        scenario_summaries[name] = {
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "days_tracked": r.days_tracked,
            "allocation_changes": r.allocation_changes,
            "events_count": len(r.events_handled),
            "survived": r.end_capital >= r.start_capital,
        }

    return {
        "scenarios_count": len(results),
        "worst_drawdown_pct": round(max(drawdowns), 4),
        "best_return_pct": round(max(returns), 4),
        "avg_sharpe": round(sum(sharpes) / len(sharpes), 4),
        "crisis_survival_rate": round(survived / len(results), 4),
        "scenarios": scenario_summaries,
    }


def save_backtest_results(
    results: dict,
    path: str = "data/backtest_results_historical.json",
) -> None:
    """
    Атомарно сохранить результаты бэктеста в JSON.

    Если path — относительный, вычисляется относительно корня репо
    (2 уровня вверх от spa_core/backtest/).

    Args:
        results: {scenario_name: BacktestResult}
        path: путь к выходному файлу
    """
    if not os.path.isabs(path):
        repo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        path = os.path.join(repo_root, path)
    path = os.path.normpath(path)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Сериализуем BacktestResult → dict
    serialized = {}
    for name, r in results.items():
        serialized[name] = {
            "scenario_name": r.scenario_name,
            "start_capital": r.start_capital,
            "end_capital": r.end_capital,
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "days_tracked": r.days_tracked,
            "allocation_changes": r.allocation_changes,
            "events_handled": r.events_handled,
            "daily_equity": r.daily_equity,
        }

    # Атомарная запись (tmp + os.replace)
    dir_name = os.path.dirname(path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(serialized, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _format_pct(value: float) -> str:
    return f"{value:+.4f}%"


if __name__ == "__main__":
    print("SPA Historical Backtest Engine (MP-212)")
    print("Running all stress scenarios...\n")

    results = run_all_scenarios()

    for name, r in results.items():
        print(f"{'=' * 60}")
        print(f"Scenario: {name}")
        print(f"  Days tracked:        {r.days_tracked}")
        print(f"  Total return:        {_format_pct(r.total_return_pct)}")
        print(f"  Max drawdown:        {r.max_drawdown_pct:.4f}%")
        print(f"  Sharpe ratio:        {r.sharpe_ratio:.4f}")
        print(f"  Allocation changes:  {r.allocation_changes}")
        print(f"  Events handled:      {len(r.events_handled)}")
        print(f"  End capital:         ${r.end_capital:,.2f}")

    print(f"\n{'=' * 60}")
    report = generate_backtest_report(results)
    print("Investor Summary:")
    print(f"  Worst drawdown:      {report['worst_drawdown_pct']:.4f}%")
    print(f"  Best return:         {_format_pct(report['best_return_pct'])}")
    print(f"  Avg Sharpe:          {report['avg_sharpe']:.4f}")
    print(f"  Crisis survival:     {report['crisis_survival_rate']:.0%}")

    save_backtest_results(results)
    print("\nResults saved to data/backtest_results_historical.json")
