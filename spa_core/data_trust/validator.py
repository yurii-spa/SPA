"""
DataTrust Validator — Multi-source price/TVL/APY validation.
LLM_FORBIDDEN: нет вызовов AI.
fail-closed: невалидные данные → EXIT сигнал, не подавлять.
Закрывает AUDIT-011: прямые незащищённые fetches в risk-слое.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DataValidationResult(str, Enum):
    VALID = "valid"
    STALE = "stale"
    OUT_OF_RANGE = "out_of_range"
    DIVERGENT = "divergent"          # источники расходятся > порога
    MISSING = "missing"              # данные отсутствуют
    FAIL_CLOSED = "fail_closed"      # ошибка → fail-closed EXIT


@dataclass
class DataPoint:
    """Единица данных с метаданными валидности."""
    value: float
    source: str
    fetched_at: datetime
    asset: str
    metric: str  # "apy", "tvl_usd", "price", "depeg_pct"
    data_type: str = "real-data"  # "real-data" | "modeled"


@dataclass
class ValidationResult:
    """Результат валидации набора DataPoints."""
    status: DataValidationResult
    validated_value: Optional[float]
    sources_used: List[str]
    divergence_pct: Optional[float]
    staleness_seconds: Optional[float]
    details: str
    signal: str  # "ok" | "alarm" | "exit"

    @property
    def should_exit(self) -> bool:
        """fail-closed: любая ошибка → EXIT"""
        return self.status != DataValidationResult.VALID or self.signal == "exit"


class DataTrustValidator:
    """
    Валидирует данные из нескольких источников.

    Правила:
    1. Минимум 2 источника на критический параметр
    2. Свежесть: max_staleness_seconds
    3. Диапазон: [lo, hi] для каждого типа данных
    4. Расхождение источников: max_divergence_pct
    5. fail-closed: любая ошибка → ValidationResult с signal="exit"

    LLM_FORBIDDEN.
    """

    # Конфигурация по умолчанию (единый источник правды)
    DEFAULT_CONFIG = {
        "apy": {
            "max_staleness_seconds": 14400,   # 4 часа
            "range_lo": 0.0,
            "range_hi": 0.50,                  # 0-50% APY разумный диапазон
            "max_divergence_pct": 0.20,        # 20% расхождение → алерт
            "min_sources": 2,
        },
        "tvl_usd": {
            "max_staleness_seconds": 7200,    # 2 часа
            "range_lo": 0.0,
            "range_hi": 100_000_000_000.0,    # до $100B
            "max_divergence_pct": 0.10,        # 10%
            "min_sources": 2,
        },
        "price": {
            "max_staleness_seconds": 1800,    # 30 минут
            "range_lo": 0.0,
            "range_hi": 1_000_000.0,
            "max_divergence_pct": 0.005,       # 0.5% для стейблов
            "min_sources": 2,
        },
        "depeg_pct": {
            "max_staleness_seconds": 3600,    # 1 час
            "range_lo": 0.0,
            "range_hi": 1.0,
            "max_divergence_pct": 0.001,       # 0.1% абсолютное расхождение
            "min_sources": 1,                  # депег: достаточно 1 источника
        },
        "funding_rate": {
            "max_staleness_seconds": 14400,   # 4 часа
            "range_lo": -0.5,                  # может быть отрицательным
            "range_hi": 0.5,
            "max_divergence_pct": 0.05,        # 5%
            "min_sources": 1,
        },
    }

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self.DEFAULT_CONFIG

    def validate(
        self,
        points: List[DataPoint],
        metric: str,
        as_of: Optional[datetime] = None,
    ) -> ValidationResult:
        """
        Основная функция валидации.

        Args:
            points: список DataPoint от разных источников
            metric: тип метрики (apy, tvl_usd, price, depeg_pct, funding_rate)
            as_of: точка времени PIT (для бэктеста — не берём данные после этого)

        Returns:
            ValidationResult с signal: "ok" | "alarm" | "exit"

        LLM_FORBIDDEN. fail-closed.
        """
        # LLM_FORBIDDEN

        if not points:
            return ValidationResult(
                status=DataValidationResult.MISSING,
                validated_value=None,
                sources_used=[],
                divergence_pct=None,
                staleness_seconds=None,
                details=f"FAIL_CLOSED: no data for {metric}",
                signal="exit",
            )

        cfg = self.config.get(metric, {})
        max_staleness = cfg.get("max_staleness_seconds", 3600)
        range_lo = cfg.get("range_lo", 0.0)
        range_hi = cfg.get("range_hi", float("inf"))
        max_divergence = cfg.get("max_divergence_pct", 0.20)
        min_sources = cfg.get("min_sources", 2)

        now = as_of or datetime.utcnow()

        # PIT фильтрация: только данные до as_of (для бэктеста)
        if as_of is not None:
            points = [p for p in points if p.fetched_at <= as_of]

        if not points:
            return ValidationResult(
                status=DataValidationResult.MISSING,
                validated_value=None,
                sources_used=[],
                divergence_pct=None,
                staleness_seconds=None,
                details=f"FAIL_CLOSED: no PIT data for {metric} at {as_of}",
                signal="exit",
            )

        # 1. Проверка свежести
        stale_points = []
        fresh_points = []
        for p in points:
            age = (now - p.fetched_at).total_seconds()
            if age > max_staleness:
                stale_points.append((p, age))
            else:
                fresh_points.append(p)

        if len(fresh_points) < min_sources:
            worst_age = max(age for _, age in stale_points) if stale_points else 0
            return ValidationResult(
                status=DataValidationResult.STALE,
                validated_value=None,
                sources_used=[p.source for p in fresh_points],
                divergence_pct=None,
                staleness_seconds=worst_age,
                details=(
                    f"FAIL_CLOSED: {len(fresh_points)}/{min_sources} fresh sources for {metric}. "
                    f"Stale: {[p.source for p, _ in stale_points]}"
                ),
                signal="exit",
            )

        values = [p.value for p in fresh_points]
        sources = [p.source for p in fresh_points]

        # 2. Проверка диапазона
        out_of_range = [(v, s) for v, s in zip(values, sources)
                        if not (range_lo <= v <= range_hi)]
        if out_of_range:
            return ValidationResult(
                status=DataValidationResult.OUT_OF_RANGE,
                validated_value=None,
                sources_used=sources,
                divergence_pct=None,
                staleness_seconds=None,
                details=(
                    f"FAIL_CLOSED: values out of range [{range_lo}, {range_hi}] for {metric}: "
                    f"{out_of_range}"
                ),
                signal="exit",
            )

        # 3. Проверка расхождения источников (если ≥2)
        if len(fresh_points) >= 2:
            min_v, max_v = min(values), max(values)
            if min_v > 0:
                divergence = (max_v - min_v) / min_v
            else:
                divergence = abs(max_v - min_v)

            if divergence > max_divergence:
                return ValidationResult(
                    status=DataValidationResult.DIVERGENT,
                    validated_value=None,
                    sources_used=sources,
                    divergence_pct=divergence,
                    staleness_seconds=None,
                    details=(
                        f"ALARM: sources diverge {divergence*100:.2f}% > threshold {max_divergence*100:.1f}% "
                        f"for {metric}. Values: {dict(zip(sources, values))}"
                    ),
                    signal="alarm",
                )
        else:
            divergence = None

        # 4. Агрегация (медиана — устойчивее к выбросам)
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 1:
            validated_value = sorted_values[n // 2]
        else:
            validated_value = (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2

        newest = max(p.fetched_at for p in fresh_points)
        staleness = (now - newest).total_seconds()

        return ValidationResult(
            status=DataValidationResult.VALID,
            validated_value=validated_value,
            sources_used=sources,
            divergence_pct=divergence,
            staleness_seconds=staleness,
            details=f"OK: {metric}={validated_value:.6f} from {sources}",
            signal="ok",
        )

    def validate_batch(
        self,
        data: Dict[str, List[DataPoint]],
        as_of: Optional[datetime] = None,
    ) -> Dict[str, ValidationResult]:
        """
        Валидирует батч метрик. Любая FAIL → сигнал exit для всего батча.
        Используется аллокатором перед принятием решений.
        """
        results = {}
        for metric, points in data.items():
            results[metric] = self.validate(points, metric, as_of=as_of)
        return results

    def any_should_exit(self, results: Dict[str, ValidationResult]) -> bool:
        """fail-closed: если любой результат требует EXIT → True"""
        return any(r.should_exit for r in results.values())
