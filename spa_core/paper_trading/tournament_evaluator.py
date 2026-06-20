"""
spa_core/paper_trading/tournament_evaluator.py — Multi-Strategy Tournament Evaluator

TournamentEvaluator: оценивает все стратегии из VPortfolioManager по финансовым
метрикам и принимает решения kill/promote.

Метрики (все вычисляются из equity_history каждого vPortfolio):
  - Sharpe ratio (annualized, rf=3%)
  - Calmar ratio (CAGR / max_drawdown)
  - Ulcer Index (sqrt(mean(drawdown²)))
  - Rachev Ratio (ETG / ETL, хвосты 5%)
  - APY realized vs target
  - Bootstrap confidence interval (95%, N=1000 resample)

Правила:
  - Минимум MIN_OBS=14 дней для статистической значимости
  - Kill: drawdown > kill_threshold ИЛИ Sharpe < -0.5 за 14+ дней
  - Promote: 30+ дней, Sharpe > 1.0, APY > baseline+200bps, Calmar > 0.5
  - stdlib only, no external deps, read-only/advisory
  - Запись в data/tournament_ranking.json (атомарная)
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics
from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY, StrategyConfig
from spa_core.paper_trading.vportfolio import VPortfolio, VPortfolioManager
from spa_core.utils.atomic import atomic_save

# ─── Константы ────────────────────────────────────────────────────────────────

MIN_OBS = 14                  # минимум дней для статоценки
PROMOTE_MIN_OBS = 30          # минимум дней для promote
RISK_FREE_RATE = 0.03         # 3% годовых (rf)
RACHEV_ALPHA = 0.05           # 5% хвосты для Rachev Ratio
BOOTSTRAP_N = 1000            # итераций bootstrap
BOOTSTRAP_SEED = 42
SHARPE_KILL_THRESHOLD = -0.5  # Sharpe < -0.5 → кандидат на kill
PROMOTE_SHARPE = 1.0          # минимальный Sharpe для promote
PROMOTE_CALMAR = 0.5          # минимальный Calmar для promote
PROMOTE_APY_PREMIUM = 2.0     # bps/% APY-превышение над baseline для promote
BASELINE_STRATEGY_ID = "S0"   # Conservative T1 как baseline
TOURNAMENT_FILENAME = "tournament_ranking.json"

# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class StrategyMetrics:
    """Финансовые метрики одной стратегии."""
    strategy_id: str
    name: str
    status: str
    days_observed: int
    current_equity: float
    total_return_pct: float
    realized_apy_pct: float       # аннуализированная реализованная доходность
    target_apy_min: float
    target_apy_max: float
    sharpe_ratio: Optional[float]
    calmar_ratio: Optional[float]
    ulcer_index: Optional[float]
    rachev_ratio: Optional[float]
    max_drawdown_pct: float       # 0..1
    drawdown_pct: float           # текущая просадка 0..1
    sharpe_ci_lower: Optional[float]  # 95% bootstrap CI lower
    sharpe_ci_upper: Optional[float]  # 95% bootstrap CI upper
    apy_vs_baseline_bps: Optional[float]  # APY разница vs S0 baseline (bps)
    is_statistically_significant: bool   # ≥ MIN_OBS дней
    notes: List[str] = field(default_factory=list)

    @property
    def has_real_data(self) -> bool:
        """True если накоплено ≥ MIN_OBS дней для статистически значимой оценки."""
        return self.is_statistically_significant

    def to_dict(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "status": self.status,
            "days_observed": self.days_observed,
            "has_real_data": self.has_real_data,
            "current_equity": round(self.current_equity, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "realized_apy_pct": round(self.realized_apy_pct, 4),
            "target_apy_min": self.target_apy_min,
            "target_apy_max": self.target_apy_max,
            "sharpe_ratio": _fmt(self.sharpe_ratio),
            "calmar_ratio": _fmt(self.calmar_ratio),
            "ulcer_index": _fmt(self.ulcer_index),
            "rachev_ratio": _fmt(self.rachev_ratio),
            "max_drawdown_pct": round(self.max_drawdown_pct, 6),
            "drawdown_pct": round(self.drawdown_pct, 6),
            "sharpe_ci_lower": _fmt(self.sharpe_ci_lower),
            "sharpe_ci_upper": _fmt(self.sharpe_ci_upper),
            "apy_vs_baseline_bps": _fmt(self.apy_vs_baseline_bps),
            "is_statistically_significant": self.is_statistically_significant,
            "notes": self.notes,
        }


@dataclass
class StrategyResult:
    """Результат оценки стратегии в турнире."""
    strategy_id: str
    rank: int
    composite_score: float    # 0..1; выше = лучше
    metrics: StrategyMetrics
    should_kill: bool
    should_promote: bool
    kill_reasons: List[str] = field(default_factory=list)
    promote_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "rank": self.rank,
            "composite_score": round(self.composite_score, 6),
            "metrics": self.metrics.to_dict(),
            "should_kill": self.should_kill,
            "should_promote": self.should_promote,
            "kill_reasons": self.kill_reasons,
            "promote_reasons": self.promote_reasons,
        }


# ─── Math helpers ─────────────────────────────────────────────────────────────

def _fmt(v: Optional[float]) -> Optional[float]:
    """Round or return None."""
    if v is None:
        return None
    if not math.isfinite(v):
        return None
    return round(v, 6)


def _mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    variance = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(variance, 0.0))


def _annualize_return(daily_returns: List[float]) -> float:
    """CAGR из дневных доходностей (fraction, not %)."""
    if not daily_returns:
        return 0.0
    cumulative = 1.0
    for r in daily_returns:
        cumulative *= (1.0 + r)
    n = len(daily_returns)
    if cumulative <= 0:
        return -1.0
    return (cumulative ** (365.0 / n)) - 1.0


def compute_sharpe(
    daily_returns: List[float],
    rf_annual: float = RISK_FREE_RATE,
) -> Optional[float]:
    """Annualized Sharpe ratio.

    Sharpe = (mean_daily_return - rf_daily) / std_daily * sqrt(365)

    Returns None если < 2 наблюдений или std=0.
    """
    if len(daily_returns) < 2:
        return None
    rf_daily = (1.0 + rf_annual) ** (1.0 / 365.0) - 1.0
    excess = [r - rf_daily for r in daily_returns]
    m = _mean(excess)
    s = _std(excess)
    if s <= 0:
        return None
    return m / s * math.sqrt(365.0)


def compute_calmar(
    daily_returns: List[float],
    max_dd_pct: float,
) -> Optional[float]:
    """Calmar ratio = CAGR / max_drawdown.

    Returns None если max_dd=0 или недостаточно данных.
    """
    if len(daily_returns) < 2:
        return None
    if max_dd_pct <= 0:
        return None
    cagr = _annualize_return(daily_returns)
    return cagr / max_dd_pct


def compute_ulcer_index(equity_series: List[float]) -> Optional[float]:
    """Ulcer Index = sqrt(mean(drawdown_from_peak²)).

    Принимает список значений equity (уровни, не доходности).
    Returns None если < 2 точек.
    """
    if len(equity_series) < 2:
        return None
    peak = equity_series[0]
    sum_sq = 0.0
    for eq in equity_series:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        sum_sq += dd * dd
    return math.sqrt(sum_sq / len(equity_series))


def compute_max_drawdown(equity_series: List[float]) -> float:
    """Max drawdown (0..1) из серии equity levels."""
    if len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for eq in equity_series:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_rachev_ratio(
    daily_returns: List[float],
    alpha: float = RACHEV_ALPHA,
) -> Optional[float]:
    """Rachev Ratio = E[tail gain] / E[tail loss].

    ETG = mean of top alpha-fraction returns (right tail)
    ETL = -mean of bottom alpha-fraction returns (left tail)

    Returns None если ETL <= 0 или недостаточно данных.
    """
    n = len(daily_returns)
    if n < int(math.ceil(1.0 / alpha)) * 2:
        return None
    cutoff = max(1, math.ceil(n * alpha))
    sorted_r = sorted(daily_returns)

    # Left tail (losses)
    tail_loss = sorted_r[:cutoff]
    etl = -_mean(tail_loss)
    if etl <= 0:
        return None

    # Right tail (gains)
    tail_gain = sorted_r[-cutoff:]
    etg = _mean(tail_gain)

    return etg / etl


def bootstrap_sharpe_ci(
    daily_returns: List[float],
    n_iter: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
    rf_annual: float = RISK_FREE_RATE,
) -> Tuple[Optional[float], Optional[float]]:
    """Bootstrap confidence interval для Sharpe ratio.

    Returns (lower, upper) или (None, None) если < 2 наблюдений.
    """
    if len(daily_returns) < 2:
        return None, None

    rng = random.Random(seed)
    n = len(daily_returns)
    sharpes = []
    for _ in range(n_iter):
        sample = [rng.choice(daily_returns) for _ in range(n)]
        s = compute_sharpe(sample, rf_annual)
        if s is not None and math.isfinite(s):
            sharpes.append(s)

    if not sharpes:
        return None, None

    sharpes.sort()
    lo_idx = int((1.0 - confidence) / 2.0 * len(sharpes))
    hi_idx = int((1.0 + confidence) / 2.0 * len(sharpes)) - 1
    lo_idx = max(0, min(lo_idx, len(sharpes) - 1))
    hi_idx = max(0, min(hi_idx, len(sharpes) - 1))
    return sharpes[lo_idx], sharpes[hi_idx]


def compute_composite_score(m: StrategyMetrics) -> float:
    """Взвешенный composite score [0..1].

    Веса:
      - Sharpe (35%)
      - Calmar (20%)
      - APY vs target (20%)
      - Ulcer Index inverse (15%)  — меньше Ulcer → выше балл
      - Rachev Ratio (10%)

    Нормализация: каждый компонент → sigmoid-like [0, 1].

    Если стратегия не накопила ≥ MIN_OBS дней (has_real_data=False) —
    возвращает 0.0, а НЕ нейтральный fallback.  Это гарантирует, что все
    стратегии без достаточной истории получают одинаково честный нулевой балл
    вместо артефактного 0.3386, скрывающего отсутствие реальных данных.
    """
    # Честный нулевой балл при нехватке статистически значимых данных
    if not m.is_statistically_significant:
        return 0.0

    score = 0.0
    weight_total = 0.0

    # Sharpe (35%)
    if m.sharpe_ratio is not None and math.isfinite(m.sharpe_ratio):
        # sigmoid-like: [-3, 3] → [0, 1] via tanh
        s_norm = (math.tanh(m.sharpe_ratio / 1.5) + 1.0) / 2.0
        score += 0.35 * s_norm
    else:
        score += 0.35 * 0.4
    weight_total += 0.35

    # Calmar (20%)
    if m.calmar_ratio is not None and math.isfinite(m.calmar_ratio):
        c_norm = (math.tanh(m.calmar_ratio / 0.8) + 1.0) / 2.0
        score += 0.20 * c_norm
    else:
        score += 0.20 * 0.4
    weight_total += 0.20

    # APY vs target midpoint (20%)
    target_mid = (m.target_apy_min + m.target_apy_max) / 2.0
    if target_mid > 0:
        apy_ratio = m.realized_apy_pct / target_mid if target_mid else 0.0
        a_norm = min(1.0, max(0.0, apy_ratio))
        a_norm = (math.tanh((apy_ratio - 0.8) * 2.5) + 1.0) / 2.0
        score += 0.20 * a_norm
    else:
        score += 0.20 * 0.4
    weight_total += 0.20

    # Ulcer Index inverse (15%) — меньше Ulcer → выше балл
    if m.ulcer_index is not None and math.isfinite(m.ulcer_index):
        # ulcer 0..0.05 → high score; > 0.10 → low score
        u_inv = 1.0 - min(1.0, m.ulcer_index * 20.0)
        score += 0.15 * u_inv
    else:
        score += 0.15 * 0.5
    weight_total += 0.15

    # Rachev Ratio (10%)
    if m.rachev_ratio is not None and math.isfinite(m.rachev_ratio):
        r_norm = (math.tanh((m.rachev_ratio - 1.0) / 0.5) + 1.0) / 2.0
        score += 0.10 * r_norm
    else:
        score += 0.10 * 0.4
    weight_total += 0.10

    return min(1.0, max(0.0, score / weight_total if weight_total > 0 else 0.0))


# ─── TournamentEvaluator ──────────────────────────────────────────────────────

class TournamentEvaluator(BaseAnalytics):
    """Оценивает все стратегии VPortfolioManager и ранжирует их.

    Usage:
        manager = VPortfolioManager.load()
        evaluator = TournamentEvaluator(manager)
        ranking = evaluator.evaluate_all()
    """

    OUTPUT_PATH = "data/tournament_ranking.json"

    def __init__(
        self,
        manager: VPortfolioManager,
        data_dir: Optional[Path] = None,
        base_dir: str = ".",
    ) -> None:
        super().__init__(base_dir)
        self.manager = manager
        self._data_dir: Path = data_dir or manager._data_dir

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """BaseAnalytics contract: run the tournament and return a result dict.

        Delegates to :meth:`evaluate_all` (the canonical entry point) and
        returns a JSON-serialisable summary. Without this method the class is
        abstract and cannot be instantiated (BaseAnalytics.analyze is
        ``@abstractmethod``).
        """
        ranking = self.evaluate_all()
        return {
            "count": len(ranking),
            "leader": ranking[0].strategy_id if ranking else None,
            "ranking": [
                getattr(r, "strategy_id", str(r)) for r in ranking
            ],
        }

    def evaluate_all(self) -> List[StrategyResult]:
        """Вычислить метрики для всех стратегий и вернуть ранжированный список.

        Returns:
            list[StrategyResult] отсортированный по composite_score DESC.
        """
        # 1. Baseline APY для сравнения
        baseline_apy = self._baseline_apy()

        # 2. Вычисляем метрики каждой стратегии
        results: List[StrategyResult] = []
        for sid, vp in self.manager.portfolios.items():
            metrics = self._compute_metrics(vp, baseline_apy)
            kill = self.should_kill(sid)
            promote = self.should_promote(sid)
            kill_reasons = self._kill_reasons(vp, metrics) if kill else []
            promote_reasons = self._promote_reasons(vp, metrics, baseline_apy) if promote else []

            composite = compute_composite_score(metrics)

            results.append(StrategyResult(
                strategy_id=sid,
                rank=0,  # назначим позже
                composite_score=composite,
                metrics=metrics,
                should_kill=kill,
                should_promote=promote,
                kill_reasons=kill_reasons,
                promote_reasons=promote_reasons,
            ))

        # 3. Сортируем по composite_score DESC
        results.sort(key=lambda r: r.composite_score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    def should_kill(self, strategy_id: str) -> bool:
        """True если стратегию нужно остановить.

        Критерии (ИЛИ):
          - max_drawdown > kill_threshold (из StrategyConfig или 5% дефолт)
          - Sharpe < SHARPE_KILL_THRESHOLD за MIN_OBS+ дней
          - Стратегия уже killed
        """
        vp = self.manager.get(strategy_id)
        if vp is None:
            return False
        if vp.status == "killed":
            return True

        cfg = STRATEGY_REGISTRY.get(strategy_id)
        kill_dd = cfg.kill_drawdown_pct if cfg and cfg.kill_drawdown_pct is not None else 0.05

        # Drawdown kill
        dd = compute_max_drawdown(self._equity_levels(vp))
        if dd >= kill_dd:
            return True

        # Sharpe kill (только при MIN_OBS+ дней)
        returns = vp.daily_returns
        if len(returns) >= MIN_OBS:
            sharpe = compute_sharpe(returns)
            if sharpe is not None and sharpe < SHARPE_KILL_THRESHOLD:
                return True

        return False

    def should_promote(self, strategy_id: str) -> bool:
        """True если стратегия готова к promotion.

        Критерии (ВСЕ):
          - PROMOTE_MIN_OBS+ дней наблюдений
          - Sharpe > PROMOTE_SHARPE
          - APY > baseline + PROMOTE_APY_PREMIUM
          - Calmar > PROMOTE_CALMAR
          - Статус не killed
        """
        vp = self.manager.get(strategy_id)
        if vp is None:
            return False
        if vp.status in ("killed", "promoted"):
            return vp.status == "promoted"  # уже promoted = true

        returns = vp.daily_returns
        if len(returns) < PROMOTE_MIN_OBS:
            return False

        # Sharpe
        sharpe = compute_sharpe(returns)
        if sharpe is None or sharpe < PROMOTE_SHARPE:
            return False

        # Calmar
        eq_levels = self._equity_levels(vp)
        max_dd = compute_max_drawdown(eq_levels)
        calmar = compute_calmar(returns, max_dd)
        if calmar is None or calmar < PROMOTE_CALMAR:
            return False

        # APY vs baseline
        realized_apy = _annualize_return(returns) * 100.0
        baseline_apy = self._baseline_apy()
        if realized_apy < baseline_apy + PROMOTE_APY_PREMIUM:
            return False

        return True

    def to_dict(self) -> dict:
        """Returns current tournament ranking as JSON-serializable dict (BaseAnalytics)."""
        results = self.evaluate_all()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "tournament_evaluator",
            "is_demo": False,
            "num_strategies": len(results),
            "ranking": [r.to_dict() for r in results],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_ranking(self, results: List[StrategyResult]) -> Path:
        """Атомарная запись data/tournament_ranking.json."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._data_dir / TOURNAMENT_FILENAME

        doc = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "tournament_evaluator",
            "is_demo": False,
            "num_strategies": len(results),
            "min_obs_required": MIN_OBS,
            "promote_min_obs": PROMOTE_MIN_OBS,
            "baseline_strategy_id": BASELINE_STRATEGY_ID,
            "ranking": [r.to_dict() for r in results],
        }

        atomic_save(doc, str(out_path))
        return out_path

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _equity_levels(self, vp: VPortfolio) -> List[float]:
        """Серия уровней equity из equity_history."""
        return [h["equity"] for h in vp.equity_history if "equity" in h]

    def _compute_metrics(
        self,
        vp: VPortfolio,
        baseline_apy: float,
    ) -> StrategyMetrics:
        """Вычислить все метрики для одного VPortfolio."""
        cfg = STRATEGY_REGISTRY.get(vp.strategy_id)
        returns = vp.daily_returns
        eq_levels = self._equity_levels(vp)
        n = len(returns)

        realized_apy = _annualize_return(returns) * 100.0 if n >= 2 else 0.0

        # Max drawdown
        max_dd = compute_max_drawdown(eq_levels) if len(eq_levels) >= 2 else 0.0

        # Метрики (только при MIN_OBS+)
        if n >= MIN_OBS:
            sharpe = compute_sharpe(returns)
            calmar = compute_calmar(returns, max_dd)
            ulcer = compute_ulcer_index(eq_levels)
            rachev = compute_rachev_ratio(returns)
            ci_lo, ci_hi = bootstrap_sharpe_ci(returns)
            is_sig = True
        else:
            sharpe = calmar = ulcer = rachev = None
            ci_lo = ci_hi = None
            is_sig = False

        # APY vs baseline
        apy_vs_baseline = (realized_apy - baseline_apy) * 100.0 if baseline_apy != 0 else None

        notes = []
        if n < MIN_OBS:
            notes.append(f"Only {n} days observed (< {MIN_OBS} required for statistics)")
        if vp.status == "killed":
            notes.append("Strategy killed by TournamentEvaluator")
        if vp.status == "promoted":
            notes.append("Strategy promoted as best performer")

        return StrategyMetrics(
            strategy_id=vp.strategy_id,
            name=cfg.name if cfg else vp.strategy_id,
            status=vp.status,
            days_observed=n,
            current_equity=vp.current_equity,
            total_return_pct=vp.total_return_pct,
            realized_apy_pct=realized_apy,
            target_apy_min=cfg.target_apy_min if cfg else 0.0,
            target_apy_max=cfg.target_apy_max if cfg else 0.0,
            sharpe_ratio=sharpe,
            calmar_ratio=calmar,
            ulcer_index=ulcer,
            rachev_ratio=rachev,
            max_drawdown_pct=max_dd,
            drawdown_pct=vp.drawdown_pct,
            sharpe_ci_lower=ci_lo,
            sharpe_ci_upper=ci_hi,
            apy_vs_baseline_bps=apy_vs_baseline,
            is_statistically_significant=is_sig,
            notes=notes,
        )

    def _baseline_apy(self) -> float:
        """Реализованный APY базовой стратегии S0."""
        baseline_vp = self.manager.get(BASELINE_STRATEGY_ID)
        if baseline_vp is None or len(baseline_vp.daily_returns) < 2:
            return 0.0
        return _annualize_return(baseline_vp.daily_returns) * 100.0

    def _kill_reasons(
        self,
        vp: VPortfolio,
        metrics: StrategyMetrics,
    ) -> List[str]:
        reasons = []
        cfg = STRATEGY_REGISTRY.get(vp.strategy_id)
        kill_dd = cfg.kill_drawdown_pct if cfg and cfg.kill_drawdown_pct else 0.05
        if metrics.max_drawdown_pct >= kill_dd:
            reasons.append(
                f"max_drawdown {metrics.max_drawdown_pct:.2%} >= threshold {kill_dd:.2%}"
            )
        if (
            metrics.sharpe_ratio is not None
            and metrics.sharpe_ratio < SHARPE_KILL_THRESHOLD
            and metrics.days_observed >= MIN_OBS
        ):
            reasons.append(
                f"Sharpe {metrics.sharpe_ratio:.3f} < {SHARPE_KILL_THRESHOLD} "
                f"over {metrics.days_observed} days"
            )
        return reasons

    def _promote_reasons(
        self,
        vp: VPortfolio,
        metrics: StrategyMetrics,
        baseline_apy: float,
    ) -> List[str]:
        reasons = []
        if metrics.days_observed >= PROMOTE_MIN_OBS:
            reasons.append(f"{metrics.days_observed} days ≥ {PROMOTE_MIN_OBS} required")
        if metrics.sharpe_ratio is not None and metrics.sharpe_ratio >= PROMOTE_SHARPE:
            reasons.append(f"Sharpe {metrics.sharpe_ratio:.3f} ≥ {PROMOTE_SHARPE}")
        if metrics.calmar_ratio is not None and metrics.calmar_ratio >= PROMOTE_CALMAR:
            reasons.append(f"Calmar {metrics.calmar_ratio:.3f} ≥ {PROMOTE_CALMAR}")
        if metrics.realized_apy_pct >= baseline_apy + PROMOTE_APY_PREMIUM:
            reasons.append(
                f"APY {metrics.realized_apy_pct:.2f}% ≥ baseline {baseline_apy:.2f}% "
                f"+ {PROMOTE_APY_PREMIUM}%"
            )
        return reasons
