"""
BEE S9.4 — Benchmark Engine.
Сравнение стратегии vs naive hold (Sharpe/Sortino/Calmar).
LLM_FORBIDDEN. PIT-строгость. No APY promises.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path
import json
import math
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

BENCHMARK_VERSION = "benchmark_v1.0"
RISK_FREE_RATE = 0.045  # 4.5% T-Bills (proxy, 2025-2026)


@dataclass
class ReturnSeries:
    """Временной ряд доходностей."""
    dates: List[str]
    daily_returns: List[float]
    label: str

    @property
    def n(self) -> int:
        return len(self.daily_returns)

    @property
    def mean_daily(self) -> float:
        if not self.daily_returns:
            return 0.0
        return sum(self.daily_returns) / self.n

    @property
    def annualized_return(self) -> float:
        """Геометрическая годовая доходность."""
        if not self.daily_returns:
            return 0.0
        cumulative = 1.0
        for r in self.daily_returns:
            cumulative *= (1 + r)
        return cumulative ** (365 / self.n) - 1

    @property
    def daily_std(self) -> float:
        """Стандартное отклонение дневных доходностей."""
        if self.n < 2:
            return 0.0
        mean = self.mean_daily
        variance = sum((r - mean) ** 2 for r in self.daily_returns) / (self.n - 1)
        return math.sqrt(variance)

    @property
    def annualized_std(self) -> float:
        return self.daily_std * math.sqrt(365)

    @property
    def max_drawdown(self) -> float:
        """Максимальная просадка (отрицательное число)."""
        if not self.daily_returns:
            return 0.0
        peak = 1.0
        equity = 1.0
        max_dd = 0.0
        for r in self.daily_returns:
            equity *= (1 + r)
            if equity > peak:
                peak = equity
            dd = (equity - peak) / peak
            if dd < max_dd:
                max_dd = dd
        return max_dd

    @property
    def downside_daily_returns(self) -> List[float]:
        """Только доходности ниже risk-free (для Sortino)."""
        daily_rfr = (1 + RISK_FREE_RATE) ** (1 / 365) - 1
        return [r for r in self.daily_returns if r < daily_rfr]


def sharpe_ratio(returns: ReturnSeries) -> float:
    """
    Sharpe Ratio = (annualized_return - risk_free) / annualized_std
    LLM_FORBIDDEN. PIT-строгость: только переданные данные.
    """
    # LLM_FORBIDDEN
    if returns.annualized_std < 1e-10:  # float-safe: ~0 std → no meaningful Sharpe
        return 0.0
    return (returns.annualized_return - RISK_FREE_RATE) / returns.annualized_std


def sortino_ratio(returns: ReturnSeries) -> float:
    """
    Sortino Ratio = (annualized_return - risk_free) / downside_std
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    downside = returns.downside_daily_returns
    if not downside:
        return float("inf")  # нет дней ниже RF → максимальный sortino
    downside_var = sum(r ** 2 for r in downside) / len(downside)
    downside_std_daily = math.sqrt(downside_var)
    downside_std_annual = downside_std_daily * math.sqrt(365)
    if downside_std_annual == 0:
        return 0.0
    return (returns.annualized_return - RISK_FREE_RATE) / downside_std_annual


def calmar_ratio(returns: ReturnSeries) -> float:
    """
    Calmar Ratio = annualized_return / |max_drawdown|
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    max_dd = abs(returns.max_drawdown)
    if max_dd == 0:
        return float("inf")  # нет просадки
    return returns.annualized_return / max_dd


@dataclass
class BenchmarkResult:
    """Сравнение стратегии vs baseline."""
    strategy_label: str
    baseline_label: str
    period_days: int

    # Метрики стратегии
    strategy_annualized_return: float
    strategy_sharpe: float
    strategy_sortino: float
    strategy_calmar: float
    strategy_max_drawdown: float

    # Метрики baseline
    baseline_annualized_return: float
    baseline_sharpe: float
    baseline_sortino: float
    baseline_calmar: float
    baseline_max_drawdown: float

    # Победитель по метрикам
    better_return: bool
    better_sharpe: bool
    better_sortino: bool
    better_calmar: bool
    better_drawdown: bool

    # Общий вывод
    wins: int  # из 5 метрик
    verdict: str  # "outperforms" | "underperforms" | "mixed"
    note: str  # без обещаний APY


def compare_vs_naive(
    strategy_returns: ReturnSeries,
    naive_daily_return: Optional[float] = None,
) -> BenchmarkResult:
    """
    Сравнивает стратегию vs naive hold (статичная доходность).

    Naive hold baseline = risk-free (T-Bills 4.5%) если не передан явно.

    LLM_FORBIDDEN. No APY promises.
    """
    # LLM_FORBIDDEN

    if naive_daily_return is None:
        # Naive = risk-free rate (T-Bills)
        naive_daily_return = (1 + RISK_FREE_RATE) ** (1 / 365) - 1

    # Строим naive series с теми же датами
    naive = ReturnSeries(
        dates=strategy_returns.dates,
        daily_returns=[naive_daily_return] * strategy_returns.n,
        label="naive_hold_risk_free",
    )

    s = strategy_returns
    n = naive

    s_sharpe = sharpe_ratio(s)
    s_sortino = sortino_ratio(s)
    s_calmar = calmar_ratio(s)

    n_sharpe = sharpe_ratio(n)
    n_sortino = sortino_ratio(n)
    n_calmar = calmar_ratio(n)

    better_return = s.annualized_return > n.annualized_return
    better_sharpe = s_sharpe > n_sharpe
    better_sortino = s_sortino > n_sortino
    better_calmar = s_calmar > n_calmar
    better_drawdown = abs(s.max_drawdown) < abs(n.max_drawdown)

    wins = sum([better_return, better_sharpe, better_sortino, better_calmar, better_drawdown])

    if wins >= 4:
        verdict = "outperforms"
    elif wins <= 1:
        verdict = "underperforms"
    else:
        verdict = "mixed"

    note = (
        f"Strategy vs naive ({RISK_FREE_RATE*100:.1f}% T-Bills benchmark). "
        f"Past performance is historical only. No future APY implied."
    )

    return BenchmarkResult(
        strategy_label=s.label,
        baseline_label=n.label,
        period_days=s.n,
        strategy_annualized_return=s.annualized_return,
        strategy_sharpe=s_sharpe,
        strategy_sortino=s_sortino,
        strategy_calmar=s_calmar,
        strategy_max_drawdown=s.max_drawdown,
        baseline_annualized_return=n.annualized_return,
        baseline_sharpe=n_sharpe,
        baseline_sortino=n_sortino,
        baseline_calmar=n_calmar,
        baseline_max_drawdown=n.max_drawdown,
        better_return=better_return,
        better_sharpe=better_sharpe,
        better_sortino=better_sortino,
        better_calmar=better_calmar,
        better_drawdown=better_drawdown,
        wins=wins,
        verdict=verdict,
        note=note,
    )


def run_benchmark(output_path: Optional[Path] = None) -> Dict:
    """
    End-to-end: загружает equity_curve_daily.json, строит ReturnSeries,
    сравнивает vs naive. Записывает data/bee/benchmark_result.json атомарно.

    LLM_FORBIDDEN. PIT: только данные >= honest_start_date.
    """
    # LLM_FORBIDDEN

    honest_start = "2026-06-10"

    # Пробуем загрузить equity curve
    equity_path = _PROJECT_ROOT / "data" / "equity_curve_daily.json"
    pt_path = _PROJECT_ROOT / "data" / "paper_trading_status.json"

    history = []

    # Сначала equity_curve_daily.json (кольцевой буфер 365 дней)
    try:
        raw = json.loads(equity_path.read_text())
        entries = raw if isinstance(raw, list) else raw.get("entries", [])
        history = [
            {"date": e.get("date", ""), "equity": e.get("equity", e.get("portfolio_value", 0))}
            for e in entries
            if e.get("date", "") >= honest_start
            and not e.get("is_warmup", False)
            and not e.get("is_seed", False)
        ]
    except Exception:
        pass

    # Fallback: paper_trading_status.json → daily_history
    if not history:
        try:
            pt = json.loads(pt_path.read_text())
            raw_history = pt.get("daily_history", [])
            history = [
                {"date": e.get("date", ""), "equity": e.get("equity", e.get("portfolio_value", 100000))}
                for e in raw_history
                if not e.get("is_warmup", False)
                and not e.get("is_seed", False)
                and e.get("date", "") >= honest_start
            ]
        except Exception:
            pass

    if len(history) < 2:
        result = {
            "benchmark_version": BENCHMARK_VERSION,
            "run_at": datetime.utcnow().isoformat() + "Z",
            "status": "insufficient_data",
            "data_points": len(history),
            "min_required": 2,
            "LLM_FORBIDDEN": True,
            "note": "Past performance is historical only. No future APY implied.",
        }
    else:
        # Сортируем по дате (PIT)
        history.sort(key=lambda e: e["date"])
        equities = [e["equity"] for e in history]
        dates = [e["date"] for e in history]

        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])
            else:
                daily_returns.append(0.0)

        strategy = ReturnSeries(
            dates=dates[1:],  # даты соответствуют returns
            daily_returns=daily_returns,
            label="SPA_Core_Engine_A",
        )

        benchmark = compare_vs_naive(strategy)

        result = {
            "benchmark_version": BENCHMARK_VERSION,
            "run_at": datetime.utcnow().isoformat() + "Z",
            "honest_start": honest_start,
            "status": "ok",
            "data_points": len(daily_returns),
            "strategy": {
                "label": benchmark.strategy_label,
                "annualized_return": benchmark.strategy_annualized_return,
                "sharpe": benchmark.strategy_sharpe,
                "sortino": (
                    None if math.isinf(benchmark.strategy_sortino)
                    else benchmark.strategy_sortino
                ),
                "calmar": (
                    None if math.isinf(benchmark.strategy_calmar)
                    else benchmark.strategy_calmar
                ),
                "max_drawdown": benchmark.strategy_max_drawdown,
            },
            "baseline": {
                "label": benchmark.baseline_label,
                "annualized_return": benchmark.baseline_annualized_return,
                "sharpe": benchmark.baseline_sharpe,
                "sortino": (
                    None if math.isinf(benchmark.baseline_sortino)
                    else benchmark.baseline_sortino
                ),
                "calmar": (
                    None if math.isinf(benchmark.baseline_calmar)
                    else benchmark.baseline_calmar
                ),
                "max_drawdown": benchmark.baseline_max_drawdown,
            },
            "wins_out_of_5": benchmark.wins,
            "verdict": benchmark.verdict,
            "note": benchmark.note,
            "LLM_FORBIDDEN": True,
        }

    if output_path is None:
        output_path = _PROJECT_ROOT / "data" / "bee" / "benchmark_result.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Атомарная запись
    tmp = output_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.replace(output_path)

    return result


if __name__ == "__main__":
    # LLM_FORBIDDEN
    import sys
    result = run_benchmark()
    status = result.get("status", "ok")
    print(f"status  : {status}")
    if status == "ok":
        print(f"verdict : {result['verdict']}")
        print(f"wins    : {result['wins_out_of_5']}/5")
        s = result["strategy"]
        b = result["baseline"]
        print(f"strategy sharpe={s['sharpe']:.3f}  sortino={s['sortino']}  calmar={s['calmar']}")
        print(f"baseline sharpe={b['sharpe']:.3f}  sortino={b['sortino']}  calmar={b['calmar']}")
    print(f"LLM_FORBIDDEN: {result['LLM_FORBIDDEN']}")
    sys.exit(0)
