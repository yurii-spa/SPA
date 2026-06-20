"""Kelly Criterion position sizing for the SPA yield portfolio (MP-1231).

Превращает список адаптеров (protocol / apy_pct / tier) в Kelly-оптимальные веса.

Финансовая модель (DeFi stablecoin yield):
    "win"  = протокол НЕ взломан → позиция приносит ``APY edge`` над risk-free.
    "loss" = протокол теряет средства (эксплойт/руг) → теряется 100% позиции.

Классическая формула Kelly::

    f* = (p·b − q) / b           где  b = APY edge над risk-free (доля),
                                       p = вероятность «win» = 1 − hack_prob,
                                       q = вероятность «loss» = hack_prob.

Эквивалентно ``f* = p − q/b``.

Исторические вероятности major loss event (annual) по тирам:
    T1 — 0.5%   (Aave/Compound/Morpho Steakhouse: аудиты, institutional TVL)
    T2 — 2.0%   (Morpho Blue / Yearn / Euler / Maple)
    T3 — 5.0%   (Pendle YT / Private Credit — спекулятивные)

Для live-торговли применяется **half-Kelly** (safety factor 0.5): full-Kelly
слишком агрессивен при ошибке оценки, half-Kelly даёт ~75% роста при куда
меньшей дисперсии (стандартная практика systematic trading).

Модуль строго read-only / advisory: НЕ исполняет сделки, НЕ трогает
``execution/``, без LLM, только stdlib.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# ── Параметры модели ──────────────────────────────────────────────────────────

# Annual probability of a major loss event (exploit / rug / depeg-to-zero) by tier.
TIER_HACK_PROBABILITY: dict[str, float] = {
    "T1": 0.005,
    "T2": 0.020,
    "T3": 0.050,
}

# Консервативный дефолт для неизвестного тира — трактуем как T2.
DEFAULT_HACK_PROBABILITY: float = 0.020

# Risk-free reference (US T-bill, ~4%). Kelly edge ``b`` = APY − risk_free.
DEFAULT_RISK_FREE_PCT: float = 4.0

# Safety factor: 0.5 → half-Kelly для live-торговли (1.0 → full-Kelly).
DEFAULT_KELLY_FRACTION: float = 0.5

_EPS = 1e-12


def hack_probability(tier: str) -> float:
    """Annual probability of a major loss event for *tier* (T1/T2/T3)."""
    return TIER_HACK_PROBABILITY.get(str(tier).strip().upper(), DEFAULT_HACK_PROBABILITY)


def kelly_criterion(p: float, b: float) -> float:
    """Чистая формула Kelly ``f* = (p·b − q) / b`` где ``q = 1 − p``.

    Универсальная (не привязана к DeFi) — используется для верификации против
    учебных значений. Например ``kelly_criterion(0.6, 1.0) == 0.2`` (even-money
    ставка с 60% вероятностью выигрыша → ставить 20% банкролла).

    ``b ≤ 0`` (нет положительного edge) → ``0.0`` (играть нельзя/невыгодно).
    Результат НЕ клампится здесь — отрицательное f* означает «не входить».
    """
    if b <= _EPS:
        return 0.0
    q = 1.0 - p
    return (p * b - q) / b


def kelly_fraction(
    apy_pct: float,
    tier: str,
    *,
    risk_free_pct: float = DEFAULT_RISK_FREE_PCT,
    hack_prob: float | None = None,
    safety_factor: float = DEFAULT_KELLY_FRACTION,
) -> float:
    """Kelly-доля капитала для одной yield-позиции (после safety factor).

    ``b`` = (APY − risk_free) / 100 — фракционный выигрыш при «win».
    ``p`` = 1 − hack_prob, ``q`` = hack_prob.

    Применяется ``safety_factor`` (по умолчанию 0.5 → half-Kelly). Результат
    клампится в ``[0, 1]``: SPA не использует плечо и не шортит, а отрицательный
    full-Kelly (edge не покрывает риск взлома) означает нулевую аллокацию.
    """
    q = hack_probability(tier) if hack_prob is None else float(hack_prob)
    p = 1.0 - q
    b = (float(apy_pct) - float(risk_free_pct)) / 100.0
    f_star = kelly_criterion(p, b)
    f = safety_factor * f_star
    return max(0.0, min(1.0, f))


@dataclass
class KellyResult:
    """Результат расчёта Kelly-весов портфеля."""

    optimal_weights: dict[str, float]            # protocol → нормализованный вес (Σ = 1.0)
    raw_kelly_fractions: dict[str, float]        # protocol → half-Kelly доля (до нормализации)
    safety_factor: float
    risk_free_pct: float
    timestamp: str
    per_protocol: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class KellySizer:
    """Kelly Criterion sizer для yield-портфеля (advisory)."""

    def __init__(
        self,
        risk_free_pct: float = DEFAULT_RISK_FREE_PCT,
        safety_factor: float = DEFAULT_KELLY_FRACTION,
        hack_probabilities: dict[str, float] | None = None,
    ):
        self.risk_free_pct = float(risk_free_pct)
        self.safety_factor = float(safety_factor)
        self.hack_probabilities = dict(TIER_HACK_PROBABILITY)
        if hack_probabilities:
            self.hack_probabilities.update(
                {str(k).strip().upper(): float(v) for k, v in hack_probabilities.items()}
            )

    def _hack_prob(self, tier: str) -> float:
        return self.hack_probabilities.get(
            str(tier).strip().upper(), DEFAULT_HACK_PROBABILITY
        )

    def fraction_for(self, apy_pct: float, tier: str) -> float:
        """Half-Kelly доля для одного протокола (см. :func:`kelly_fraction`)."""
        return kelly_fraction(
            apy_pct,
            tier,
            risk_free_pct=self.risk_free_pct,
            hack_prob=self._hack_prob(tier),
            safety_factor=self.safety_factor,
        )

    def compute_weights(self, adapters: list[dict]) -> KellyResult:
        """Считает Kelly-веса по списку адаптеров.

        Вход — ``list[dict]`` с ключами ``protocol / apy_pct / tier``. Для
        каждого протокола считается half-Kelly доля, затем доли нормализуются
        до суммы 1.0 (Kelly даёт *относительную* привлекательность позиций).

        Если ни у одного протокола нет положительного Kelly-edge (все доли ≈ 0)
        — честный fallback на равные веса, чтобы не уйти молча в 100% кэш.
        Пустой вход → пустой результат.
        """
        ts = datetime.now(timezone.utc).isoformat()
        notes: list[str] = []

        if not adapters:
            notes.append("Нет адаптеров — пустое Kelly-распределение.")
            return KellyResult(
                optimal_weights={},
                raw_kelly_fractions={},
                safety_factor=self.safety_factor,
                risk_free_pct=self.risk_free_pct,
                timestamp=ts,
                per_protocol={},
                notes=notes,
            )

        raw: dict[str, float] = {}
        per_protocol: dict[str, dict] = {}
        for a in adapters:
            p = str(a["protocol"])
            tier = str(a.get("tier", "T2"))
            apy = float(a.get("apy_pct", 0.0) or 0.0)
            q = self._hack_prob(tier)
            edge = apy - self.risk_free_pct
            f = self.fraction_for(apy, tier)
            raw[p] = f
            per_protocol[p] = {
                "tier": tier.upper(),
                "apy_pct": round(apy, 4),
                "edge_pct": round(edge, 4),
                "hack_probability": round(q, 6),
                "win_probability": round(1.0 - q, 6),
                "half_kelly_fraction": round(f, 6),
            }

        total = sum(raw.values())
        if total <= _EPS:
            # Ни одного протокола с положительным edge → равные веса (fallback).
            notes.append(
                "Ни один протокол не имеет положительного Kelly-edge "
                "(APY ≤ risk-free или edge не покрывает риск взлома) — "
                "fallback на равные веса."
            )
            n = len(adapters)
            weights = {str(a["protocol"]): 1.0 / n for a in adapters}
        else:
            weights = {p: f / total for p, f in raw.items()}

        for p in per_protocol:
            per_protocol[p]["optimal_weight"] = round(weights.get(p, 0.0), 6)

        return KellyResult(
            optimal_weights={p: round(w, 6) for p, w in weights.items()},
            raw_kelly_fractions={p: round(f, 6) for p, f in raw.items()},
            safety_factor=self.safety_factor,
            risk_free_pct=self.risk_free_pct,
            timestamp=ts,
            per_protocol=per_protocol,
            notes=notes,
        )


def main() -> None:  # pragma: no cover — CLI thin wrapper
    """CLI: посчитать Kelly-веса по живому снимку адаптеров."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="SPA Kelly Sizer (advisory)")
    parser.add_argument("--risk-free", type=float, default=DEFAULT_RISK_FREE_PCT)
    parser.add_argument("--safety", type=float, default=DEFAULT_KELLY_FRACTION)
    args = parser.parse_args()

    # Переиспользуем загрузчик адаптеров аллокатора (read-only).
    from spa_core.allocator.allocator import StrategyAllocator

    adapters = StrategyAllocator()._load_adapters()
    adapters = [a for a in adapters if a.get("apy_pct")]
    sizer = KellySizer(risk_free_pct=args.risk_free, safety_factor=args.safety)
    result = sizer.compute_weights(adapters)
    print(json.dumps(result.to_dict(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
