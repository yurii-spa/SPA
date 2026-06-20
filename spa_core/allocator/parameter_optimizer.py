"""Strategy parameter optimizer (MP-1231) — grid search над RiskConfig-параметрами.

Перебирает сетку ключевых параметров аллокатора/риска и оценивает каждую
комбинацию по **Sharpe ratio на paper-данных + risk-adjusted APY**. Лучший
набор пишется в ``data/optimized_params.json`` (advisory — НЕ применяется
автоматически; смена RiskConfig требует ADR, см. policy.py governance).

Сетка (3×3×3×3 = 81 комбинация)::

    T1_cap              : [0.30, 0.40, 0.50]
    T2_cap              : [0.15, 0.20, 0.25]
    cash_buffer         : [0.03, 0.05, 0.07]
    rebalance_threshold : [0.03, 0.05, 0.08]

Скоринг (детерминированный, без LLM)::

    paper_sharpe        — annualized Sharpe реализованной paper equity curve
                          (общий baseline качества трека).
    expected_apy_pct    — ожидаемый APY портфеля при данных cap'ах/буфере
                          (best-APY water-fill по живым адаптерам).
    risk_adjusted_apy   — expected_apy × (1 − HHI-штраф) − turnover_cost
                          − tracking_error.  HHI растёт с cap'ами (концентрация),
                          turnover_cost растёт при низком rebalance_threshold,
                          tracking_error растёт при высоком — есть внутренний оптимум.

    score = W_SHARPE·paper_sharpe + W_APY·risk_adjusted_apy_pct

Строго read-only / advisory, только stdlib. Все записи атомарны.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_OUT = _DATA_DIR / "optimized_params.json"
_EPS = 1e-12

# ── Сетка параметров ──────────────────────────────────────────────────────────
DEFAULT_GRID: dict[str, list[float]] = {
    "t1_cap": [0.30, 0.40, 0.50],
    "t2_cap": [0.15, 0.20, 0.25],
    "cash_buffer": [0.03, 0.05, 0.07],
    "rebalance_threshold": [0.03, 0.05, 0.08],
}

# ── Веса и константы скоринга ─────────────────────────────────────────────────
W_SHARPE: float = 0.5            # вклад paper-Sharpe в итоговый score
W_APY: float = 0.5               # вклад risk-adjusted APY (в долях, не %)
HHI_PENALTY: float = 0.50        # штраф концентрации: apy × (1 − HHI_PENALTY·HHI)
REBALANCE_COST_PCT: float = 0.05            # % портфеля за один ребаланс
ANNUAL_DRIFT_BUDGET: float = 0.60           # суммарный годовой дрейф весов (доля)
TRACKING_ERROR_WEIGHT: float = 8.0          # штраф за редкие ребалансы (× threshold, %)

TRADING_DAYS: int = 365


def _is_t1(tier: str) -> bool:
    return str(tier).strip().upper() == "T1"


@dataclass
class ScoredCombo:
    """Оценка одной комбинации параметров."""

    params: dict
    paper_sharpe: float
    expected_apy_pct: float
    risk_adjusted_apy_pct: float
    hhi: float
    turnover_cost_pct: float
    tracking_error_pct: float
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizationResult:
    """Результат grid search."""

    best_params: dict
    best_score: float
    best_detail: dict
    num_combinations: int
    paper_sharpe: float
    all_results: list[dict]
    timestamp: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ParameterOptimizer:
    """Grid-search оптимизатор параметров аллокатора (advisory)."""

    def __init__(
        self,
        adapters: list[dict] | None = None,
        equity_data: dict | None = None,
        data_dir: str | Path | None = None,
        grid: dict[str, list[float]] | None = None,
    ):
        self.data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._adapters_override = adapters
        self._equity_override = equity_data
        self.grid = grid or DEFAULT_GRID

    # ── загрузка входов ───────────────────────────────────────────────────────
    def _load_adapters(self) -> list[dict]:
        """Живые адаптеры с положительным APY (orchestrator + registry)."""
        if self._adapters_override is not None:
            return [a for a in self._adapters_override if float(a.get("apy_pct") or 0) > 0]
        try:
            from spa_core.allocator.allocator import StrategyAllocator

            allocator = StrategyAllocator(
                status_path=self.data_dir / "adapter_orchestrator_status.json",
                registry_path=self.data_dir / "adapter_registry.json",
            )
            adapters = allocator._load_adapters()
        except Exception:
            adapters = []
        return [a for a in adapters if float(a.get("apy_pct") or 0) > 0]

    def _load_equity(self) -> dict:
        if self._equity_override is not None:
            return self._equity_override
        path = self.data_dir / "equity_curve_daily.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    # ── метрики ───────────────────────────────────────────────────────────────
    def paper_sharpe(self) -> float:
        """Annualized Sharpe реализованной paper equity curve.

        Из дневных доходностей: ``Sharpe = mean/std × √365``. Нет данных или
        нулевая дисперсия → 0.0 (нейтральный baseline).
        """
        equity = self._load_equity()
        daily = equity.get("daily", []) if isinstance(equity, dict) else []
        rets = [
            float(d.get("daily_return_pct", 0.0)) / 100.0
            for d in daily
            if isinstance(d, dict)
        ]
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        if std <= _EPS:
            return 0.0
        return (mean / std) * math.sqrt(TRADING_DAYS)

    def _simulate_allocation(
        self,
        adapters: list[dict],
        t1_cap: float,
        t2_cap: float,
        cash_buffer: float,
    ) -> dict[str, float]:
        """Best-APY water-fill под per-protocol cap'ами и cash buffer.

        Протоколы сортируются по APY (убыв.) и заполняются до своего cap'а, пока
        не исчерпан ``deployable = 1 − cash_buffer``. Возвращает ``{protocol:
        weight}`` (доли капитала; Σ ≤ deployable).
        """
        deployable = max(0.0, 1.0 - cash_buffer)
        ranked = sorted(
            adapters, key=lambda a: float(a.get("apy_pct", 0.0)), reverse=True
        )
        weights: dict[str, float] = {}
        remaining = deployable
        for a in ranked:
            if remaining <= _EPS:
                break
            cap = t1_cap if _is_t1(a.get("tier", "T2")) else t2_cap
            take = min(cap, remaining)
            weights[str(a["protocol"])] = take
            remaining -= take
        return weights

    def _score(self, adapters: list[dict], sharpe: float, params: dict) -> ScoredCombo:
        t1_cap = params["t1_cap"]
        t2_cap = params["t2_cap"]
        cash_buffer = params["cash_buffer"]
        threshold = params["rebalance_threshold"]

        weights = self._simulate_allocation(adapters, t1_cap, t2_cap, cash_buffer)
        apy_map = {str(a["protocol"]): float(a.get("apy_pct", 0.0)) for a in adapters}

        expected_apy = sum(w * apy_map.get(p, 0.0) for p, w in weights.items())
        deployed = sum(weights.values())
        # HHI концентрации среди размещённого капитала (0..1).
        hhi = (
            sum((w / deployed) ** 2 for w in weights.values())
            if deployed > _EPS
            else 0.0
        )

        # Turnover: ниже threshold → чаще ребалансы → дороже.
        rebalances_per_year = ANNUAL_DRIFT_BUDGET / max(threshold, _EPS)
        turnover_cost_pct = rebalances_per_year * REBALANCE_COST_PCT

        # Tracking error: выше threshold → дольше дрейф → больше расхождение.
        tracking_error_pct = TRACKING_ERROR_WEIGHT * threshold

        risk_adjusted_apy = (
            expected_apy * (1.0 - HHI_PENALTY * hhi)
            - turnover_cost_pct
            - tracking_error_pct
        )

        score = W_SHARPE * sharpe + W_APY * (risk_adjusted_apy / 100.0)

        return ScoredCombo(
            params=dict(params),
            paper_sharpe=round(sharpe, 6),
            expected_apy_pct=round(expected_apy, 6),
            risk_adjusted_apy_pct=round(risk_adjusted_apy, 6),
            hhi=round(hhi, 6),
            turnover_cost_pct=round(turnover_cost_pct, 6),
            tracking_error_pct=round(tracking_error_pct, 6),
            score=round(score, 8),
        )

    # ── grid search ───────────────────────────────────────────────────────────
    def optimize(self) -> OptimizationResult:
        ts = datetime.now(timezone.utc).isoformat()
        adapters = self._load_adapters()
        sharpe = self.paper_sharpe()
        notes: list[str] = []
        if not adapters:
            notes.append(
                "Нет живых адаптеров с положительным APY — risk-adjusted APY = 0, "
                "оптимизация деградирует на чистый turnover/tracking trade-off."
            )

        keys = list(self.grid.keys())
        combos = list(itertools.product(*(self.grid[k] for k in keys)))
        scored: list[ScoredCombo] = []
        for combo in combos:
            params = {k: combo[i] for i, k in enumerate(keys)}
            scored.append(self._score(adapters, sharpe, params))

        # Детерминированный tie-break: по score (убыв.), затем по параметрам.
        scored.sort(
            key=lambda s: (
                -s.score,
                s.params["t1_cap"],
                s.params["t2_cap"],
                s.params["cash_buffer"],
                s.params["rebalance_threshold"],
            )
        )
        best = scored[0]

        return OptimizationResult(
            best_params=best.params,
            best_score=best.score,
            best_detail=best.to_dict(),
            num_combinations=len(scored),
            paper_sharpe=round(sharpe, 6),
            all_results=[s.to_dict() for s in scored],
            timestamp=ts,
            notes=notes,
        )

    def save(self, result: OptimizationResult, path: str | Path = _DEFAULT_OUT) -> Path:
        """Атомарно пишет результат в JSON (tmp + os.replace)."""
        out = Path(path)
        atomic_save(result.to_dict(), str(out))
        return out


def main() -> None:  # pragma: no cover — CLI thin wrapper
    parser = argparse.ArgumentParser(
        description="SPA Strategy Parameter Optimizer (advisory)"
    )
    parser.add_argument(
        "--run", action="store_true", help="записать результат в data/optimized_params.json"
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT))
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    optimizer = ParameterOptimizer(data_dir=args.data_dir)
    result = optimizer.optimize()
    print(f"Комбинаций перебрано: {result.num_combinations}")
    print(f"Paper Sharpe: {result.paper_sharpe}")
    print(f"Лучшие параметры: {json.dumps(result.best_params)}")
    print(f"Score: {result.best_score}")
    print(f"  expected_apy: {result.best_detail['expected_apy_pct']}%")
    print(f"  risk_adjusted_apy: {result.best_detail['risk_adjusted_apy_pct']}%")
    if args.run:
        path = optimizer.save(result, args.out)
        print(f"Сохранено в {path}")
    else:
        print("(--run не указан — запись пропущена)")


if __name__ == "__main__":  # pragma: no cover
    main()
