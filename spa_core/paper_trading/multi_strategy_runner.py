"""
spa_core/paper_trading/multi_strategy_runner.py — MP-357 MultiStrategyRunner

Запускает simulate_day для N стратегий параллельно, собирает результаты,
ранжирует стратегии по composite_score из tournament_evaluator,
экспортирует результаты в tournament_ranking.json.

Правила:
  - stdlib only, no external deps
  - Атомарные записи (mkstemp + os.replace) — FORBIDDEN прямой open(..., "w")
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - Принимает список StrategyConfig напрямую (не обращается к STRATEGY_REGISTRY)
  - Комментарии на русском языке
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.paper_trading.strategy_registry import StrategyConfig
from spa_core.paper_trading.vportfolio import VPortfolio, INITIAL_CAPITAL_USD
from spa_core.paper_trading.tournament_evaluator import (
    MIN_OBS,
    StrategyMetrics,
    compute_composite_score,
    compute_sharpe,
    compute_calmar,
    compute_ulcer_index,
    compute_rachev_ratio,
    compute_max_drawdown,
    bootstrap_sharpe_ci,
    _annualize_return,
)

# ─── Константы ────────────────────────────────────────────────────────────────

# Протоколы, которые пропускаем при инициализации позиций:
# внешние / watchlist-протоколы не имеют живых APY в run_day
_SKIP_PROTOCOLS = frozenset({
    "pendle_pt",          # Pendle PT — external, placeholder
    "sky_susds",          # Sky/sUSDS — watchlist, 0% аллокации по FORBIDDEN
    "pendle_yt",          # Pendle YT — internal placeholder
    "susde_spot",         # S8 spot-позиция sUSDe
    "perp_short_hedge",   # S8 perp-хедж позиция
})

RANKING_FILENAME = "tournament_ranking.json"


# ─── MultiStrategyRunner ──────────────────────────────────────────────────────

class MultiStrategyRunner:
    """Параллельный раннер N стратегий с отдельным VPortfolio на каждую.

    Запускает simulate_day для каждой активной стратегии, собирает результаты,
    ранжирует по composite_score из TournamentEvaluator, экспортирует JSON.

    Жизненный цикл:
        1. MultiStrategyRunner(strategies) — создаём с конфигами стратегий
        2. run_day(apy_map)              — ежедневно (можно звать многократно)
        3. get_rankings()               — получаем ранжированный список
        4. export_results(path)         — атомарная запись в JSON

    Usage:
        from spa_core.paper_trading.strategy_registry import S0_CONSERVATIVE_T1, S1_BALANCED
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        runner.run_day({"aave_v3": 4.2, "morpho_blue": 6.5, "compound_v3": 4.8})
        ranking = runner.get_rankings()
        runner.export_results(Path("data/tournament_ranking.json"))
    """

    def __init__(
        self,
        strategies: List[StrategyConfig],
        capital: float = INITIAL_CAPITAL_USD,
    ) -> None:
        """Инициализировать раннер со списком стратегий.

        Args:
            strategies: список StrategyConfig для параллельного запуска
            capital:    начальный виртуальный капитал на каждую стратегию (дефолт: $100K)
        """
        self.capital = float(capital)

        # Индекс стратегий по id для быстрого доступа
        self._strategies: Dict[str, StrategyConfig] = {s.id: s for s in strategies}

        # Создаём VPortfolio для каждой стратегии
        self._portfolios: Dict[str, VPortfolio] = {
            s.id: self._init_portfolio(s) for s in strategies
        }

        # Результаты последнего run_day: {strategy_id: daily_yield_usd}
        self._last_day_yields: Dict[str, float] = {}

    # ── Публичный API ─────────────────────────────────────────────────────────

    def run_day(self, apy_map: Dict[str, float]) -> Dict[str, float]:
        """Запустить simulate_day для каждой активной стратегии.

        Killed/paused стратегии пропускаются без начисления yield.

        Args:
            apy_map: {protocol_key: annual_apy_pct} — живые APY данные,
                     например {"aave_v3": 4.2, "morpho_blue": 6.5}

        Returns:
            dict[strategy_id -> daily_yield_usd] — результаты активных стратегий
        """
        results: Dict[str, float] = {}

        for sid, vp in self._portfolios.items():
            # Пропускаем неактивные стратегии — не начисляем yield
            if vp.status in ("killed", "paused"):
                continue

            # Начисляем дневной yield через VPortfolio.simulate_day
            daily_yield = vp.simulate_day(apy_map)
            results[sid] = daily_yield

        # Сохраняем для get_total_yield()
        self._last_day_yields = results
        return results

    def get_rankings(self) -> List[Dict]:
        """Ранжированный список стратегий по composite_score (убывание).

        Использует compute_composite_score из tournament_evaluator для
        единообразия оценки с основным циклом TournamentEvaluator.

        Returns:
            list of dict с полями:
              - rank:            int, позиция (1 = лучшая)
              - strategy_id:     str
              - composite_score: float [0..1]
              - net_apy:         float, аннуализированный APY как доля (не %)
              - is_active:       bool
              - days_running:    int
        """
        ranked = []
        for sid, vp in self._portfolios.items():
            cfg = self._strategies[sid]
            # Строим StrategyMetrics для compute_composite_score
            metrics = self._build_metrics(vp, cfg)
            score = compute_composite_score(metrics)
            is_active = vp.status in ("active", "promoted")
            # net_apy — аннуализированная доходность в долях (0.042 = 4.2%)
            net_apy = metrics.realized_apy_pct / 100.0 if metrics.realized_apy_pct else 0.0

            ranked.append({
                "strategy_id":     sid,
                "composite_score": score,
                "net_apy":         net_apy,
                "is_active":       is_active,
                "days_running":    vp.days_simulated,
                # Внутренние данные — используются при export, не попадают в JSON напрямую
                "_metrics":        metrics,
            })

        # Сортируем по composite_score убыванию (лучшая стратегия первой)
        ranked.sort(key=lambda r: r["composite_score"], reverse=True)

        # Назначаем ранги: 1 = лучший composite_score
        for i, r in enumerate(ranked):
            r["rank"] = i + 1

        return ranked

    def get_active_strategies(self) -> List[StrategyConfig]:
        """Список StrategyConfig со статусом active или promoted.

        Returns:
            list[StrategyConfig] — только активные/promoted стратегии
        """
        return [
            self._strategies[sid]
            for sid, vp in self._portfolios.items()
            if vp.status in ("active", "promoted")
        ]

    def get_total_yield(self) -> float:
        """Суммарный дневной yield по всем активным стратегиям (USD).

        Использует результаты последнего вызова run_day.
        Возвращает 0.0 если run_day ещё не вызывался.

        Returns:
            total_yield_usd — сумма yield всех активных стратегий за день
        """
        total = 0.0
        for sid, yield_usd in self._last_day_yields.items():
            vp = self._portfolios[sid]
            if vp.status in ("active", "promoted"):
                total += yield_usd
        return total

    def get_allocation_map(self) -> Dict[str, float]:
        """Равномерная аллокация капитала между активными стратегиями.

        Равные веса соответствуют диверсифицированному подходу:
        каждая стратегия получает 1/N долю капитала.

        Returns:
            {strategy_id: allocation_pct} где сумма = 1.0,
            или {} если нет активных стратегий
        """
        active = self.get_active_strategies()
        if not active:
            return {}
        # Равномерное распределение — 1/N на каждую активную стратегию
        share = 1.0 / len(active)
        return {s.id: share for s in active}

    def export_results(self, path) -> None:
        """Атомарная запись tournament_ranking.json (mkstemp + os.replace).

        Формат файла:
          {
            "timestamp": "ISO",
            "strategies": [{rank, strategy_id, composite_score, net_apy, is_active, days_running}],
            "total_active": int,
            "weighted_apy": float
          }

        Args:
            path: Path или str к выходному файлу
        """
        path = Path(path)
        rankings = self.get_rankings()

        # Активные стратегии для подсчёта weighted_apy
        active_rankings = [r for r in rankings if r["is_active"]]
        total_active = len(active_rankings)

        # Взвешенный APY — среднее арифметическое активных (равные веса = get_allocation_map)
        if active_rankings:
            weighted_apy = sum(r["net_apy"] for r in active_rankings) / len(active_rankings)
        else:
            weighted_apy = 0.0

        doc = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategies": [
                {
                    "rank":            r["rank"],
                    "strategy_id":     r["strategy_id"],
                    "composite_score": round(r["composite_score"], 6),
                    "net_apy":         round(r["net_apy"], 6),
                    "is_active":       r["is_active"],
                    "days_running":    r["days_running"],
                }
                for r in rankings
            ],
            "total_active": total_active,
            "weighted_apy": round(weighted_apy, 6),
        }

        # Атомарная запись через centralized atomic_save (MP-1451)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(path))

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _init_portfolio(self, cfg: StrategyConfig) -> VPortfolio:
        """Создать VPortfolio для стратегии с ручной инициализацией позиций.

        Не обращается к глобальному STRATEGY_REGISTRY — использует cfg напрямую.
        Пропускает watchlist/external протоколы из _SKIP_PROTOCOLS.

        Args:
            cfg: StrategyConfig описывает аллокации стратегии

        Returns:
            VPortfolio с инициализированными позициями и peak_equity
        """
        vp = VPortfolio(
            strategy_id=cfg.id,
            capital_usd=self.capital,
            status=cfg.status,
        )

        # Вручную инициализируем позиции из cfg.allocations
        positions: Dict[str, float] = {}
        for protocol, weight in cfg.allocations.items():
            # Пропускаем внешние/watchlist протоколы без живых APY данных
            if protocol in _SKIP_PROTOCOLS:
                continue
            alloc_usd = self.capital * weight
            if alloc_usd > 0:
                positions[protocol] = alloc_usd

        vp.positions = positions
        # Остаток идёт в кэш (гарантирует ≥5% если аллокации ≤ 0.95)
        positions_total = sum(positions.values())
        vp.cash_usd = max(0.0, self.capital - positions_total)
        # Инициализируем peak_equity для корректного расчёта drawdown
        vp.peak_equity = vp.current_equity
        return vp

    def _build_metrics(self, vp: VPortfolio, cfg: StrategyConfig) -> StrategyMetrics:
        """Вычислить StrategyMetrics для одного VPortfolio.

        Использует хелперы из tournament_evaluator для полной совместимости
        с compute_composite_score. Статистические метрики (Sharpe, Calmar, ...)
        вычисляются только при наличии MIN_OBS+ дней.

        Args:
            vp:  VPortfolio с историей доходностей
            cfg: StrategyConfig с целевыми APY

        Returns:
            StrategyMetrics — готово для compute_composite_score()
        """
        returns = vp.daily_returns
        # Серия equity-уровней из истории (нужна для drawdown, Ulcer)
        eq_levels = [h["equity"] for h in vp.equity_history if "equity" in h]
        n = len(returns)

        # Аннуализированная доходность в процентах (0 если < 2 дней)
        realized_apy = _annualize_return(returns) * 100.0 if n >= 2 else 0.0
        # Max drawdown (доля 0..1)
        max_dd = compute_max_drawdown(eq_levels) if len(eq_levels) >= 2 else 0.0

        # Статистические метрики — только при достаточном числе наблюдений
        if n >= MIN_OBS:
            sharpe = compute_sharpe(returns)
            calmar = compute_calmar(returns, max_dd)
            ulcer = compute_ulcer_index(eq_levels)
            rachev = compute_rachev_ratio(returns)
            ci_lo, ci_hi = bootstrap_sharpe_ci(returns)
            is_sig = True
        else:
            # Недостаточно данных — нейтральный балл 0.4 в compute_composite_score
            sharpe = calmar = ulcer = rachev = None
            ci_lo = ci_hi = None
            is_sig = False

        return StrategyMetrics(
            strategy_id=vp.strategy_id,
            name=cfg.name,
            status=vp.status,
            days_observed=n,
            current_equity=vp.current_equity,
            total_return_pct=vp.total_return_pct,
            realized_apy_pct=realized_apy,
            target_apy_min=cfg.target_apy_min,
            target_apy_max=cfg.target_apy_max,
            sharpe_ratio=sharpe,
            calmar_ratio=calmar,
            ulcer_index=ulcer,
            rachev_ratio=rachev,
            max_drawdown_pct=max_dd,
            drawdown_pct=vp.drawdown_pct,
            sharpe_ci_lower=ci_lo,
            sharpe_ci_upper=ci_hi,
            apy_vs_baseline_bps=None,   # не используется без baseline VPortfolio
            is_statistically_significant=is_sig,
        )
