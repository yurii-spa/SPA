"""Drift Calculator (SPA-V389) — расчёт отклонения портфеля от целей.

Сравнивает фактические веса позиций с целевыми и помечает те, что вышли за
порог ребаланса (по умолчанию 5%). Advisory-only: ничего не исполняет.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from spa_core.portfolio.state_tracker import PortfolioPosition

REBALANCE_THRESHOLD = 0.05  # 5% по абсолютному дрейфу веса


@dataclass
class DriftResult:
    """Отклонение одной позиции от цели."""

    protocol: str
    actual_weight: float
    target_weight: float
    drift_pct: float        # actual_weight - target_weight (доля, не проценты)
    drift_usd: float        # actual_usd - target_usd
    needs_rebalance: bool   # abs(drift_pct) > порог

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_drift(
    positions: list[PortfolioPosition], threshold: float = REBALANCE_THRESHOLD
) -> list[DriftResult]:
    """Считает дрейф для каждой позиции.

    ``drift_pct = actual_weight - target_weight`` (>0 — перевес, <0 — недовес).
    ``needs_rebalance`` истинно, когда ``abs(drift_pct) > threshold``.
    """
    results = []
    for p in positions:
        drift_pct = p.actual_weight - p.target_weight
        drift_usd = p.actual_usd - p.target_usd
        results.append(
            DriftResult(
                protocol=p.protocol,
                actual_weight=round(p.actual_weight, 6),
                target_weight=round(p.target_weight, 6),
                drift_pct=round(drift_pct, 6),
                drift_usd=round(drift_usd, 2),
                needs_rebalance=abs(drift_pct) > threshold,
            )
        )
    return results


def portfolio_drift_score(drifts: list[DriftResult]) -> float:
    """Среднее ``abs(drift_pct)`` по позициям.

    0 — идеальный баланс, > 0.1 — плохо. Пустой список → 0.0.
    """
    if not drifts:
        return 0.0
    total = sum(abs(d.drift_pct) for d in drifts)
    return round(total / len(drifts), 6)
