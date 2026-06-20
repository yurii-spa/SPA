"""Dynamic allocator (MP-1231) — Kelly × equal-weight blend под RiskConfig.

Расширенный advisory-аллокатор, который:

  1. Считает Kelly-оптимальные веса по протоколам (:class:`KellySizer`).
  2. Смешивает их с равными весами в пропорции 50/50 (стабилизация — чистый
     Kelly слишком чувствителен к ошибке оценки APY/hack-prob).
  3. Применяет cap'ы RiskConfig (T1 ≤ 40%, T2 ≤ 20%, T2-total ≤ 50%) через
     water-filling с перераспределением.
  4. Возвращает целевое распределение (:class:`DynamicAllocationResult`).

Строго read-only / advisory: НЕ исполняет сделки, НЕ трогает ``execution/``,
без LLM, только stdlib. ``approved=False`` от RiskPolicy не переопределяется —
этот модуль лишь формирует *рекомендацию* в рамках cap'ов.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from spa_core.allocator.kelly_sizer import (
    DEFAULT_KELLY_FRACTION,
    DEFAULT_RISK_FREE_PCT,
    KellySizer,
)

try:
    from spa_core.risk.policy import RiskConfig as _RiskConfig
    _POLICY = _RiskConfig()
except Exception:  # pragma: no cover — import guard для изолированных тестов
    _POLICY = None  # type: ignore[assignment]

_EPS = 1e-12

# Cap-значения — единый источник истины RiskConfig (policy.py); fallback при
# неудачном импорте сохраняет совместимость в изолированных юнит-тестах.
T1_CAP: float = _POLICY.max_concentration_t1 if _POLICY is not None else 0.40
T2_CAP: float = _POLICY.max_concentration_t2 if _POLICY is not None else 0.20
T2_TOTAL_CAP: float = (
    _POLICY.max_total_t2_allocation if _POLICY is not None else 0.50
)

# Доля Kelly в блендe (остаток — equal-weight). 0.5 → 50/50.
DEFAULT_KELLY_BLEND: float = 0.5


@dataclass
class DynamicAllocationResult:
    """Результат dynamic-аллокации."""

    target_weights: dict[str, float]      # protocol → вес (Σ ≤ 1.0)
    kelly_weights: dict[str, float]        # Kelly-веса до бленда
    equal_weights: dict[str, float]        # равные веса до бленда
    blended_weights: dict[str, float]      # после бленда, до cap'ов
    kelly_blend: float                     # доля Kelly в блендe
    cash_pct: float                        # нераспределённый остаток
    t1_pct: float
    t2_pct: float
    capped: bool                           # сработал ли per-protocol cap
    t2_cap_enforced: bool                  # сработал ли совокупный T2-cap
    timestamp: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _is_t1(tier: str) -> bool:
    return str(tier).strip().upper() == "T1"


def _cap_for(tier: str) -> float:
    return T1_CAP if _is_t1(tier) else T2_CAP


def _apply_per_protocol_caps(
    weights: dict[str, float], tier_map: dict[str, str]
) -> tuple[dict[str, float], bool]:
    """Water-filling per-protocol cap (T1 ≤ 40%, T2 ≤ 20%) с перераспределением.

    Излишек над cap'ом срезается и раскидывается пропорционально на протоколы с
    запасом ёмкости. Если всё упёрлось в cap'ы — остаток честно остаётся кэшем.
    Возвращает ``(weights, was_capped)``.
    """
    caps = {p: _cap_for(tier_map.get(p, "T2")) for p in weights}
    w = dict(weights)
    was_capped = False

    for _ in range(100):
        over = [p for p in w if w[p] > caps[p] + _EPS]
        if not over:
            break
        was_capped = True
        excess = 0.0
        for p in over:
            excess += w[p] - caps[p]
            w[p] = caps[p]
        uncapped = [p for p in w if w[p] < caps[p] - _EPS]
        if not uncapped:
            break  # некуда раскидывать — остаток уходит в кэш
        base = sum(w[p] for p in uncapped)
        if base <= _EPS:
            share = excess / len(uncapped)
            for p in uncapped:
                w[p] = min(w[p] + share, caps[p])
        else:
            for p in uncapped:
                w[p] = min(w[p] + excess * (w[p] / base), caps[p])
    return w, was_capped


def _enforce_t2_total_cap(
    weights: dict[str, float], tier_map: dict[str, str]
) -> tuple[dict[str, float], bool]:
    """Совокупный T2-cap ≤ :data:`T2_TOTAL_CAP` (ADR-019).

    Если суммарный T2 > cap — T2-веса срезаются пропорционально, освобождённый
    вес water-fill'ится в headroom T1 (не превышая per-protocol T1-cap). Не
    хватило T1-ёмкости → остаток остаётся кэшем. ``(weights, enforced)``.
    """

    def _is_t2(p: str) -> bool:
        return not _is_t1(tier_map.get(p, "T2"))

    t2_total = sum(wt for p, wt in weights.items() if _is_t2(p))
    if t2_total <= T2_TOTAL_CAP + _EPS:
        return dict(weights), False

    scale = T2_TOTAL_CAP / t2_total
    w = dict(weights)
    freed = 0.0
    for p, wt in w.items():
        if _is_t2(p):
            new_wt = wt * scale
            freed += wt - new_wt
            w[p] = new_wt

    t1 = [p for p in w if not _is_t2(p)]
    for _ in range(100):
        if freed <= _EPS:
            break
        room = {p: T1_CAP - w[p] for p in t1 if T1_CAP - w[p] > _EPS}
        if not room:
            break
        base = sum(w[p] for p in room)
        added = 0.0
        if base <= _EPS:
            share = freed / len(room)
            for p in room:
                add = min(share, room[p])
                w[p] += add
                added += add
        else:
            for p, headroom in room.items():
                add = min(freed * (w[p] / base), headroom)
                w[p] += add
                added += add
        freed = max(0.0, freed - added)
    return w, True


class DynamicAllocator:
    """Kelly × equal-weight blend аллокатор под cap'ами RiskConfig."""

    def __init__(
        self,
        kelly_blend: float = DEFAULT_KELLY_BLEND,
        risk_free_pct: float = DEFAULT_RISK_FREE_PCT,
        safety_factor: float = DEFAULT_KELLY_FRACTION,
    ):
        # Доля Kelly клампится в [0, 1].
        self.kelly_blend = max(0.0, min(1.0, float(kelly_blend)))
        self.sizer = KellySizer(
            risk_free_pct=risk_free_pct, safety_factor=safety_factor
        )

    def allocate(self, adapters: list[dict]) -> DynamicAllocationResult:
        """Считает целевое распределение по списку адаптеров.

        Вход — ``list[dict]`` ``{protocol, apy_pct, tier}``. Пустой вход →
        пустой результат (100% кэш). Корректно обрабатывает граничные случаи:
        один протокол, отсутствие T2, нулевые APY.
        """
        ts = datetime.now(timezone.utc).isoformat()
        notes: list[str] = []

        if not adapters:
            notes.append("Нет адаптеров — пустое распределение (100% кэш).")
            return DynamicAllocationResult(
                target_weights={},
                kelly_weights={},
                equal_weights={},
                blended_weights={},
                kelly_blend=self.kelly_blend,
                cash_pct=1.0,
                t1_pct=0.0,
                t2_pct=0.0,
                capped=False,
                t2_cap_enforced=False,
                timestamp=ts,
                notes=notes,
            )

        tier_map = {str(a["protocol"]): str(a.get("tier", "T2")) for a in adapters}

        # 1. Kelly-веса.
        kelly = self.sizer.compute_weights(adapters)
        kelly_w = dict(kelly.optimal_weights)
        notes.extend(kelly.notes)

        # 2. Равные веса.
        n = len(adapters)
        equal_w = {str(a["protocol"]): 1.0 / n for a in adapters}

        # 3. Бленд 50/50 (по умолчанию).
        protocols = list(tier_map.keys())
        blended = {
            p: self.kelly_blend * kelly_w.get(p, 0.0)
            + (1.0 - self.kelly_blend) * equal_w.get(p, 0.0)
            for p in protocols
        }
        # Бленд двух нормализованных распределений уже даёт Σ = 1.0, но
        # подстрахуемся от накопленной ошибки округления.
        s = sum(blended.values())
        if s > _EPS:
            blended = {p: w / s for p, w in blended.items()}

        # 4. Cap'ы RiskConfig: per-protocol, затем совокупный T2.
        capped, was_capped = _apply_per_protocol_caps(blended, tier_map)
        if was_capped:
            notes.append("Веса ограничены per-protocol cap'ами (T1≤40%, T2≤20%).")
        capped, t2_enforced = _enforce_t2_total_cap(capped, tier_map)
        if t2_enforced:
            notes.append(
                f"Совокупный T2 срезан до {T2_TOTAL_CAP * 100:.0f}% (ADR-019)."
            )

        allocated = sum(capped.values())
        cash = max(0.0, 1.0 - allocated)
        if cash > 1e-6:
            notes.append(
                f"Нераспределённый кэш-буфер: {cash * 100:.2f}% "
                "(остаток после cap'ов)."
            )

        t1_pct = sum(w for p, w in capped.items() if _is_t1(tier_map.get(p, "T2")))
        t2_pct = sum(w for p, w in capped.items() if not _is_t1(tier_map.get(p, "T2")))

        return DynamicAllocationResult(
            target_weights={p: round(w, 6) for p, w in capped.items()},
            kelly_weights={p: round(w, 6) for p, w in kelly_w.items()},
            equal_weights={p: round(w, 6) for p, w in equal_w.items()},
            blended_weights={p: round(w, 6) for p, w in blended.items()},
            kelly_blend=self.kelly_blend,
            cash_pct=round(cash, 6),
            t1_pct=round(t1_pct, 6),
            t2_pct=round(t2_pct, 6),
            capped=was_capped,
            t2_cap_enforced=t2_enforced,
            timestamp=ts,
            notes=notes,
        )


def main() -> None:  # pragma: no cover — CLI thin wrapper
    """CLI: dynamic-аллокация по живому снимку адаптеров."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="SPA Dynamic Allocator (advisory)")
    parser.add_argument("--kelly-blend", type=float, default=DEFAULT_KELLY_BLEND)
    args = parser.parse_args()

    from spa_core.allocator.allocator import StrategyAllocator

    adapters = StrategyAllocator()._load_adapters()
    adapters = [a for a in adapters if a.get("apy_pct")]
    result = DynamicAllocator(kelly_blend=args.kelly_blend).allocate(adapters)
    print(json.dumps(result.to_dict(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
