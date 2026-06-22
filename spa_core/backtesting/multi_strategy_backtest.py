"""
SPA Multi-Strategy Backtest
============================

Запускает несколько стратегий на одних и тех же исторических данных
и сравнивает их метрики.

Поддерживает:
  1. Параллельный прогон всех стратегий на полном периоде.
  2. Walk-forward validation: train 60 дней → test 30 дней → rolling forward.

Каждая стратегия должна реализовывать метод:
    backtest(historical_data: list[dict], initial_capital: float) -> dict

Возвращаемый dict должен содержать:
    {
        "strategy_id": str,
        "equity_curve": list[dict],  # [{date, total_capital, ...}, ...]
        "trades": list[dict],
        "metrics": dict,             # sharpe_ratio, max_drawdown_pct, ...
    }

Usage:
    from backtesting.multi_strategy_backtest import MultiStrategyBacktest

    bt = MultiStrategyBacktest()
    results = bt.run_all(historical_data, initial_capital=100_000)
    print(bt.leaderboard(results))

    # Walk-forward validation
    wf_results = bt.walk_forward(historical_data, train_days=60, test_days=30)
    print(wf_results)
"""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ─── Результат одного прогона стратегии ──────────────────────────────────────

@dataclass
class StrategyResult:
    strategy_id:    str
    strategy_name:  str
    risk_tier:      str
    metrics:        dict
    equity_curve:   list[dict]
    trades:         list[dict]
    period_start:   str
    period_end:     str
    error:          Optional[str] = None

    @property
    def sharpe(self) -> float:
        return self.metrics.get("sharpe_ratio", 0.0)

    @property
    def max_dd(self) -> float:
        return self.metrics.get("max_drawdown_pct", 0.0)

    @property
    def ann_return(self) -> float:
        return self.metrics.get("annualised_return_pct", 0.0)

    @property
    def calmar(self) -> float:
        """Calmar ratio = annualised_return / max_drawdown."""
        if self.max_dd <= 0:
            return 0.0
        return round(self.ann_return / self.max_dd, 4)

    @property
    def risk_adjusted_score(self) -> float:
        """
        Составной риск-скорректированный балл для сравнения стратегий.

        Формула: 0.4 * sharpe + 0.3 * calmar + 0.3 * (ann_return / 10)
        Нормализует все метрики к [0, ∞) диапазону.
        """
        if self.error:
            return 0.0
        sharpe_score = max(0.0, self.sharpe)
        calmar_score = max(0.0, self.calmar)
        return_score = max(0.0, self.ann_return / 10.0)
        return round(0.4 * sharpe_score + 0.3 * calmar_score + 0.3 * return_score, 4)

    def to_summary(self) -> dict:
        return {
            "strategy_id":          self.strategy_id,
            "strategy_name":        self.strategy_name,
            "risk_tier":            self.risk_tier,
            "period":               f"{self.period_start} → {self.period_end}",
            "annualised_return_pct":self.ann_return,
            "sharpe_ratio":         self.sharpe,
            "max_drawdown_pct":     self.max_dd,
            "calmar_ratio":         self.calmar,
            "risk_adjusted_score":  self.risk_adjusted_score,
            "total_trades":         self.metrics.get("total_trades", 0),
            "win_rate":             self.metrics.get("win_rate", 0.0),
            "total_interest_usd":   self.metrics.get("total_interest_usd", 0.0),
            "error":                self.error,
        }


# ─── Walk-forward slice ───────────────────────────────────────────────────────

@dataclass
class WalkForwardSlice:
    """Результат одного walk-forward окна (train + test)."""
    window_index:    int
    train_start:     str
    train_end:       str
    test_start:      str
    test_end:        str
    train_results:   list[StrategyResult]
    test_results:    list[StrategyResult]
    winner_train:    Optional[str] = None   # strategy_id
    winner_test:     Optional[str] = None   # strategy_id (был ли train-winner лучшим на тесте?)
    prediction_hit:  bool = False           # угадал ли train-winner тест?

    def to_dict(self) -> dict:
        return {
            "window_index":  self.window_index,
            "train_period":  f"{self.train_start} → {self.train_end}",
            "test_period":   f"{self.test_start} → {self.test_end}",
            "winner_train":  self.winner_train,
            "winner_test":   self.winner_test,
            "prediction_hit":self.prediction_hit,
            "train_scores":  {r.strategy_id: r.risk_adjusted_score for r in self.train_results},
            "test_scores":   {r.strategy_id: r.risk_adjusted_score for r in self.test_results},
        }


# ─── Multi-Strategy Backtest ──────────────────────────────────────────────────

class MultiStrategyBacktest:
    """
    Запускает несколько стратегий на одних данных и сравнивает результаты.

    Стратегии загружаются из реестра (strategy_registry.REGISTRY) или
    передаются напрямую через параметр `strategy_instances`.
    """

    def __init__(
        self,
        strategy_instances: Optional[list] = None,
        initial_capital: float = 100_000.0,
    ) -> None:
        """
        Args:
            strategy_instances: Список объектов стратегий с методом backtest().
                                 Если None — загружаем все активные из реестра.
            initial_capital: Начальный капитал для всех стратегий.
        """
        self.initial_capital = initial_capital
        self._strategies = strategy_instances or self._load_from_registry()

    # ── Загрузка стратегий ────────────────────────────────────────────────────

    def _load_from_registry(self) -> list:
        """Импортирует и инстанцирует все активные стратегии из реестра."""
        try:
            import importlib
            from strategies.strategy_registry import REGISTRY
            instances = []
            for meta in REGISTRY.as_list(enabled_only=True):
                try:
                    mod = importlib.import_module(meta.module)
                    cls = getattr(mod, meta.handler_class)
                    instances.append(cls())
                    log.info("Loaded strategy: %s (%s)", meta.id, meta.handler_class)
                except Exception as exc:
                    log.warning("Could not load strategy %s: %s", meta.id, exc)
            return instances
        except Exception as exc:
            log.error("Could not load strategy registry: %s", exc)
            return []

    # ── Полный прогон всех стратегий ─────────────────────────────────────────

    def run_all(
        self,
        historical_data: list[dict],
        initial_capital: Optional[float] = None,
    ) -> list[StrategyResult]:
        """
        Запускает backtest для каждой стратегии на полных исторических данных.

        Args:
            historical_data: список записей [{timestamp, protocol_key, apy, tvl_usd, tier}, ...]
            initial_capital: переопределить начальный капитал (или использует self.initial_capital)

        Returns:
            Список StrategyResult, отсортированный по risk_adjusted_score убыванию.
        """
        capital = initial_capital or self.initial_capital
        if not historical_data:
            return []

        all_dates = sorted({r["timestamp"][:10] for r in historical_data})
        period_start = all_dates[0]  if all_dates else ""
        period_end   = all_dates[-1] if all_dates else ""

        results: list[StrategyResult] = []

        for strategy in self._strategies:
            strategy_id = getattr(strategy, "strategy_id", strategy.__class__.__name__)
            strategy_name, risk_tier = self._get_meta(strategy_id)
            log.info("Running backtest: %s", strategy_id)

            try:
                raw = strategy.backtest(historical_data, initial_capital=capital)
                results.append(StrategyResult(
                    strategy_id=strategy_id,
                    strategy_name=strategy_name,
                    risk_tier=risk_tier,
                    metrics=raw.get("metrics", {}),
                    equity_curve=raw.get("equity_curve", []),
                    trades=raw.get("trades", []),
                    period_start=period_start,
                    period_end=period_end,
                ))
            except Exception as exc:
                log.error("Backtest failed for %s: %s", strategy_id, exc)
                results.append(StrategyResult(
                    strategy_id=strategy_id,
                    strategy_name=strategy_name,
                    risk_tier=risk_tier,
                    metrics={},
                    equity_curve=[],
                    trades=[],
                    period_start=period_start,
                    period_end=period_end,
                    error=str(exc),
                ))

        # Сортируем по risk_adjusted_score убыванию
        results.sort(key=lambda r: r.risk_adjusted_score, reverse=True)
        return results

    # ── Walk-Forward Validation ───────────────────────────────────────────────

    def walk_forward(
        self,
        historical_data: list[dict],
        train_days: int = 60,
        test_days: int = 30,
        step_days: Optional[int] = None,
        initial_capital: Optional[float] = None,
    ) -> list[WalkForwardSlice]:
        """
        Walk-Forward Validation.

        Разбивает данные на скользящие окна:
          [train_days][test_days] → сдвигаемся на step_days → повтор

        Args:
            historical_data: полная история
            train_days:      размер обучающего окна (default 60 дней)
            test_days:       размер тестового окна (default 30 дней)
            step_days:       шаг скользящего окна (default = test_days)
            initial_capital: начальный капитал

        Returns:
            Список WalkForwardSlice для каждого окна.
        """
        if step_days is None:
            step_days = test_days

        capital = initial_capital or self.initial_capital

        # Группируем данные по дням
        days_data: dict[str, list[dict]] = {}
        for row in historical_data:
            ts = row["timestamp"][:10]
            days_data.setdefault(ts, []).append(row)

        all_dates = sorted(days_data.keys())
        total_days = len(all_dates)

        if total_days < train_days + test_days:
            log.warning(
                "Walk-forward: only %d days available, need %d (train=%d, test=%d)",
                total_days, train_days + test_days, train_days, test_days
            )
            return []

        slices: list[WalkForwardSlice] = []
        window_start = 0
        window_index = 0

        while window_start + train_days + test_days <= total_days:
            train_dates = all_dates[window_start : window_start + train_days]
            test_dates  = all_dates[window_start + train_days : window_start + train_days + test_days]

            # Собираем данные для каждого периода
            train_data = [r for d in train_dates for r in days_data[d]]
            test_data  = [r for d in test_dates  for r in days_data[d]]

            log.info(
                "Walk-forward window %d: train %s→%s, test %s→%s",
                window_index,
                train_dates[0], train_dates[-1],
                test_dates[0],  test_dates[-1],
            )

            # Прогон на train
            train_results = self.run_all(train_data, initial_capital=capital)
            # Прогон на test (независимо)
            test_results  = self.run_all(test_data,  initial_capital=capital)

            # Определяем winners
            winner_train = train_results[0].strategy_id if train_results else None
            winner_test  = test_results[0].strategy_id  if test_results  else None
            prediction_hit = (winner_train == winner_test) if (winner_train and winner_test) else False

            slices.append(WalkForwardSlice(
                window_index=window_index,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                train_results=train_results,
                test_results=test_results,
                winner_train=winner_train,
                winner_test=winner_test,
                prediction_hit=prediction_hit,
            ))

            window_start += step_days
            window_index += 1

        return slices

    # ── Leaderboard ───────────────────────────────────────────────────────────

    def leaderboard(self, results: list[StrategyResult]) -> list[dict]:
        """
        Возвращает таблицу сравнения стратегий, отсортированную по risk_adjusted_score.

        Args:
            results: список StrategyResult из run_all()

        Returns:
            Список dict'ов с ключевыми метриками.
        """
        return [r.to_summary() for r in sorted(
            results, key=lambda r: r.risk_adjusted_score, reverse=True
        )]

    def winner(self, results: list[StrategyResult]) -> Optional[StrategyResult]:
        """Возвращает стратегию с наивысшим risk_adjusted_score."""
        if not results:
            return None
        valid = [r for r in results if not r.error]
        return max(valid, key=lambda r: r.risk_adjusted_score) if valid else None

    # ── Walk-forward summary ──────────────────────────────────────────────────

    def walk_forward_summary(self, slices: list[WalkForwardSlice]) -> dict:
        """
        Агрегирует результаты walk-forward в сводную таблицу.

        Returns:
            dict с: hit_rate, win_counts, avg_test_score_by_strategy, windows
        """
        if not slices:
            return {"windows": 0, "hit_rate": 0.0, "win_counts": {}, "windows_detail": []}

        hit_count = sum(1 for s in slices if s.prediction_hit)
        win_counts: dict[str, int] = {}
        for s in slices:
            if s.winner_test:
                win_counts[s.winner_test] = win_counts.get(s.winner_test, 0) + 1

        # Средний test score по каждой стратегии
        test_scores: dict[str, list[float]] = {}
        for s in slices:
            for r in s.test_results:
                test_scores.setdefault(r.strategy_id, []).append(r.risk_adjusted_score)
        avg_test_scores = {
            sid: round(sum(scores) / len(scores), 4)
            for sid, scores in test_scores.items()
        }

        return {
            "windows":          len(slices),
            "hit_rate":         round(hit_count / len(slices), 4),
            "win_counts":       win_counts,
            "avg_test_scores":  avg_test_scores,
            "windows_detail":   [s.to_dict() for s in slices],
        }

    # ── JSON export ───────────────────────────────────────────────────────────

    def save_results(
        self,
        results: list[StrategyResult],
        output_path: str | Path,
    ) -> None:
        """Сохраняет leaderboard + полные метрики в JSON файл."""
        out = {
            "leaderboard":     self.leaderboard(results),
            "full_results":    [r.to_summary() for r in results],
            "equity_curves":   {
                r.strategy_id: r.equity_curve[-10:]  # последние 10 точек кривой
                for r in results
            },
        }
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2))
        log.info("Multi-strategy backtest results saved to %s", path)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_meta(self, strategy_id: str) -> tuple[str, str]:
        """Возвращает (name, risk_tier) из реестра или дефолты."""
        try:
            from strategies.strategy_registry import REGISTRY
            meta = REGISTRY.get(strategy_id)
            if meta:
                return meta.name, meta.risk_tier
        except Exception:
            pass
        return strategy_id, "T?"

    def __repr__(self) -> str:
        return (
            f"MultiStrategyBacktest("
            f"{len(self._strategies)} strategies, "
            f"capital=${self.initial_capital:,.0f})"
        )


# ─── Standalone runner ────────────────────────────────────────────────────────

def run_multi_backtest(
    historical_data: list[dict],
    initial_capital: float = 100_000.0,
    walk_forward: bool = True,
    train_days: int = 60,
    test_days:  int = 30,
    output_path: Optional[str | Path] = None,
) -> dict:
    """
    Удобный точечный запуск multi-strategy backtest.

    Args:
        historical_data: исторические данные
        initial_capital: начальный капитал
        walk_forward:    включить walk-forward validation
        train_days:      размер train окна
        test_days:       размер test окна
        output_path:     путь для сохранения JSON (опционально)

    Returns:
        dict с: leaderboard, winner, walk_forward_summary (если включён)
    """
    bt = MultiStrategyBacktest(initial_capital=initial_capital)
    full_results = bt.run_all(historical_data)
    top = bt.winner(full_results)

    out = {
        "leaderboard": bt.leaderboard(full_results),
        "winner": top.to_summary() if top else None,
    }

    if walk_forward and len(full_results) > 0:
        wf_slices = bt.walk_forward(
            historical_data,
            train_days=train_days,
            test_days=test_days,
        )
        out["walk_forward"] = bt.walk_forward_summary(wf_slices)

    if output_path:
        bt.save_results(full_results, output_path)

    return out


# ─── CLI точка входа ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import logging
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from backtesting.data_loader import generate_synthetic_history
    except ImportError:
        print("Could not import data_loader — run from spa_core/ directory")
        sys.exit(1)

    print("Generating 90-day synthetic history...")
    hist = generate_synthetic_history(days=90)

    print("Running multi-strategy backtest (full + walk-forward)...")
    result = run_multi_backtest(
        hist,
        initial_capital=100_000,
        walk_forward=True,
        train_days=60,
        test_days=30,
    )

    print("\n=== LEADERBOARD ===")
    for i, row in enumerate(result["leaderboard"], 1):
        print(
            f"  #{i} {row['strategy_id']:30s} "
            f"APY={row['annualised_return_pct']:6.2f}% "
            f"Sharpe={row['sharpe_ratio']:5.2f} "
            f"DD={row['max_drawdown_pct']:5.2f}% "
            f"Score={row['risk_adjusted_score']:5.3f}"
        )

    if result.get("winner"):
        w = result["winner"]
        print(f"\n🏆 Winner: {w['strategy_id']} (score={w['risk_adjusted_score']:.3f})")

    if result.get("walk_forward"):
        wf = result["walk_forward"]
        print(f"\nWalk-forward: {wf['windows']} windows, hit_rate={wf['hit_rate']:.1%}")
