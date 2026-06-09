"""StrategyAllocator (SPA-V388) — advisory-распределение $100K paper-капитала.

Читает снимок адаптеров (``data/adapter_orchestrator_status.json``), применяет
одну из моделей аллокации (``allocation_models``) и кап'ы по тирам, после чего
возвращает целевое распределение в виде :class:`AllocationResult`.

ВАЖНО: модуль строго read-only / dry-run. Он НЕ исполняет сделки, НЕ обращается
к ``execution/`` и не двигает реальные деньги — только формирует рекомендацию.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from spa_core.allocator import allocation_models as models

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATUS_PATH = _REPO_ROOT / "data" / "adapter_orchestrator_status.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "target_allocation.json"
_EPS = 1e-12

_MODEL_DISPATCH = {
    "equal_weight": models.equal_weight,
    "equal": models.equal_weight,
    "best_apy": models.best_apy_weight,
    "best_apy_weight": models.best_apy_weight,
    "risk_parity": models.risk_parity_weight,
    "risk_parity_weight": models.risk_parity_weight,
}


@dataclass
class AllocationResult:
    """Результат расчёта целевого распределения."""

    target_weights: dict[str, float]
    target_usd: dict[str, float]
    expected_apy_pct: float
    model_used: str
    timestamp: str
    capital_usd: float = 0.0
    allocated_pct: float = 0.0
    unallocated_pct: float = 0.0
    unallocated_usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class StrategyAllocator:
    """Advisory-аллокатор целевых весов портфеля."""

    CAPITAL = 100_000  # USD paper trading
    T1_CAP = 0.40      # макс 40% на один T1 протокол
    T2_CAP = 0.20      # макс 20% на один T2 протокол (T3 трактуем как T2)

    def __init__(self, status_path: str | os.PathLike | None = None):
        self.status_path = Path(status_path) if status_path else _STATUS_PATH

    # ── загрузка адаптеров ────────────────────────────────────────────────
    def _load_adapters(self) -> list[dict]:
        """Читает снимок оркестратора и возвращает только живые адаптеры.

        Берутся записи со ``status == 'ok'`` (или без поля status). Каждая
        приводится к контракту моделей: protocol / apy_pct / tvl_usd / tier.
        """
        if not self.status_path.exists():
            return []
        with open(self.status_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        adapters = []
        for a in raw.get("adapters", []):
            status = a.get("status", "ok")
            if status not in ("ok", "partial"):
                continue
            adapters.append(
                {
                    "protocol": a["protocol"],
                    "apy_pct": float(a.get("apy_pct", 0.0)),
                    "tvl_usd": float(a.get("tvl_usd", 0.0)),
                    "tier": a.get("tier", "T2"),
                }
            )
        return adapters

    # ── кап'ы по тирам (water-filling) ────────────────────────────────────
    def _cap_for(self, tier: str) -> float:
        return self.T1_CAP if str(tier).upper() == "T1" else self.T2_CAP

    def _apply_caps(
        self, weights: dict[str, float], tier_map: dict[str, str]
    ) -> tuple[dict[str, float], bool]:
        """Итеративно ограничивает веса cap'ами тира с перераспределением.

        Возвращает ``(capped_weights, was_capped)``. Сумма результата ≤ 1.0:
        если все протоколы упёрлись в свои cap'ы, остаток остаётся
        нераспределённым (кэш-буфер), а не нарушает лимиты.
        """
        caps = {p: self._cap_for(tier_map.get(p, "T2")) for p in weights}
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
                # некуда раскидывать — остаток уходит в кэш
                break
            base = sum(w[p] for p in uncapped)
            if base <= _EPS:
                share = excess / len(uncapped)
                for p in uncapped:
                    w[p] = min(w[p] + share, caps[p])
            else:
                for p in uncapped:
                    w[p] = min(w[p] + excess * (w[p] / base), caps[p])
        return w, was_capped

    # ── основной расчёт ───────────────────────────────────────────────────
    def allocate(self, model: str = "equal_weight") -> AllocationResult:
        fn = _MODEL_DISPATCH.get(model)
        if fn is None:
            raise ValueError(
                f"Неизвестная модель аллокации: {model!r}. "
                f"Доступны: {sorted(set(_MODEL_DISPATCH))}"
            )

        adapters = self._load_adapters()
        ts = datetime.now(timezone.utc).isoformat()
        notes: list[str] = []

        if not adapters:
            notes.append("Нет активных адаптеров — пустое распределение.")
            return AllocationResult(
                target_weights={},
                target_usd={},
                expected_apy_pct=0.0,
                model_used=model,
                timestamp=ts,
                capital_usd=float(self.CAPITAL),
                allocated_pct=0.0,
                unallocated_pct=1.0,
                unallocated_usd=float(self.CAPITAL),
                notes=notes,
            )

        tier_map = {a["protocol"]: a["tier"] for a in adapters}
        apy_map = {a["protocol"]: a["apy_pct"] for a in adapters}

        raw_weights = fn(adapters)
        capped, was_capped = self._apply_caps(raw_weights, tier_map)
        if was_capped:
            notes.append("Веса ограничены cap'ами по тирам (T1≤40%, T2≤20%).")

        allocated = sum(capped.values())
        unallocated = max(0.0, 1.0 - allocated)
        if unallocated > 1e-6:
            notes.append(
                f"Нераспределённый кэш-буфер: {unallocated * 100:.2f}% "
                "(остаток после применения cap'ов)."
            )

        target_usd = {p: round(w * self.CAPITAL, 2) for p, w in capped.items()}
        # APY портфеля: веса как доли капитала; нераспределённый кэш = 0% APY.
        expected_apy = sum(capped[p] * apy_map.get(p, 0.0) for p in capped)

        return AllocationResult(
            target_weights={p: round(w, 6) for p, w in capped.items()},
            target_usd=target_usd,
            expected_apy_pct=round(expected_apy, 4),
            model_used=model,
            timestamp=ts,
            capital_usd=float(self.CAPITAL),
            allocated_pct=round(allocated, 6),
            unallocated_pct=round(unallocated, 6),
            unallocated_usd=round(unallocated * self.CAPITAL, 2),
            notes=notes,
        )

    # ── сохранение ────────────────────────────────────────────────────────
    def save(
        self, result: AllocationResult, path: str | os.PathLike = _DEFAULT_OUT
    ) -> Path:
        """Атомарно пишет результат в JSON (tmp + os.replace)."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return out


def main() -> None:
    """CLI: рассчитать и сохранить распределение по выбранной модели."""
    import argparse

    parser = argparse.ArgumentParser(description="SPA Strategy Allocator (advisory)")
    parser.add_argument(
        "--model",
        default="equal_weight",
        choices=sorted(set(_MODEL_DISPATCH)),
        help="Модель аллокации",
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="Путь вывода")
    args = parser.parse_args()

    allocator = StrategyAllocator()
    result = allocator.allocate(model=args.model)
    allocator.save(result, args.out)
    print(f"Модель: {result.model_used}")
    print(f"Веса: {result.target_weights}")
    print(f"USD: {result.target_usd}")
    print(f"Ожидаемый APY: {result.expected_apy_pct}%")
    print(f"Нераспределено: {result.unallocated_pct * 100:.2f}%")
    print(f"Сохранено в {args.out}")


if __name__ == "__main__":
    main()
