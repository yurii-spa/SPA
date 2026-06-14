"""Rebalance Signal Generator (SPA-V389) — advisory-сигналы ребаланса.

Из результатов дрейфа формирует список сигналов BUY/SELL/HOLD с приоритетом.
ВАЖНО: advisory only — НИЧЕГО не исполняет, не обращается к ``execution/`` и не
двигает деньги. Это только рекомендации оператору.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from spa_core.portfolio.drift_calculator import DriftResult

# Пороги приоритета по абсолютному дрейфу веса (доли).
_PRIORITY_HIGH = 0.10   # ≥10% дрейфа → срочно
_PRIORITY_MED = 0.05    # ≥5% → средний приоритет


@dataclass
class RebalanceSignal:
    """Сигнал ребаланса одной позиции."""

    protocol: str
    action: str        # "BUY" / "SELL" / "HOLD"
    usd_delta: float   # >0 — докупить, <0 — продать (модуль = объём сделки)
    priority: str      # "HIGH" / "MEDIUM" / "LOW"
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _priority_for(abs_drift: float) -> str:
    if abs_drift >= _PRIORITY_HIGH:
        return "HIGH"
    if abs_drift >= _PRIORITY_MED:
        return "MEDIUM"
    return "LOW"


def generate_signals(
    drifts: list[DriftResult], min_trade_usd: float = 500
) -> list[RebalanceSignal]:
    """Генерирует сигналы ребаланса (advisory only).

    Логика:
      * ``drift_usd > 0`` (перевес) → нужно ПРОДАТЬ, чтобы вернуться к цели
        (``usd_delta = -drift_usd``).
      * ``drift_usd < 0`` (недовес) → нужно КУПИТЬ (``usd_delta = -drift_usd``).
      * сделки с ``abs(drift_usd) < min_trade_usd`` или без флага
        ``needs_rebalance`` → HOLD (слишком мелко, чтобы дёргаться).
    """
    signals = []
    for d in drifts:
        abs_drift_pct = abs(d.drift_pct)
        # usd_delta — сколько нужно довести позицию к цели: target - actual.
        usd_delta = round(-d.drift_usd, 2)

        if not d.needs_rebalance or abs(d.drift_usd) < min_trade_usd:
            signals.append(
                RebalanceSignal(
                    protocol=d.protocol,
                    action="HOLD",
                    usd_delta=0.0,
                    priority="LOW",
                    reason=(
                        f"Дрейф {d.drift_pct * 100:+.2f}% / ${d.drift_usd:+.2f} "
                        "ниже порога — держим."
                    ),
                )
            )
            continue

        if usd_delta > 0:
            action = "BUY"
            reason = (
                f"Недовес {d.drift_pct * 100:+.2f}% — докупить "
                f"${usd_delta:,.2f} до цели."
            )
        else:
            action = "SELL"
            reason = (
                f"Перевес {d.drift_pct * 100:+.2f}% — продать "
                f"${abs(usd_delta):,.2f} до цели."
            )

        signals.append(
            RebalanceSignal(
                protocol=d.protocol,
                action=action,
                usd_delta=usd_delta,
                priority=_priority_for(abs_drift_pct),
                reason=reason,
            )
        )
    return signals
