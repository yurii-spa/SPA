"""StrategyAllocator (SPA-V388) — advisory-распределение $100K paper-капитала.

Читает снимок адаптеров (``data/adapter_orchestrator_status.json``), применяет
одну из моделей аллокации (``allocation_models``) и кап'ы по тирам, после чего
возвращает целевое распределение в виде :class:`AllocationResult`.

ВАЖНО: модуль строго read-only / dry-run. Он НЕ исполняет сделки, НЕ обращается
к ``execution/`` и не двигает реальные деньги — только формирует рекомендацию.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from spa_core.allocator import allocation_models as models
from spa_core.strategies.strategy_selector import StrategySelector

log = logging.getLogger("spa.allocator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATUS_PATH = _REPO_ROOT / "data" / "adapter_orchestrator_status.json"
_RISK_SCORES_PATH = _REPO_ROOT / "data" / "risk_scores.json"
_SHADOW_COMPARISON_PATH = _REPO_ROOT / "data" / "strategy_shadow_comparison.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "target_allocation.json"
_EPS = 1e-12

# Модель по умолчанию: risk-aware (SPA-V406). Раньше было "equal_weight".
DEFAULT_MODEL = "risk_adjusted"

_MODEL_DISPATCH = {
    "equal_weight": models.equal_weight,
    "equal": models.equal_weight,
    "best_apy": models.best_apy_weight,
    "best_apy_weight": models.best_apy_weight,
    "risk_parity": models.risk_parity_weight,
    "risk_parity_weight": models.risk_parity_weight,
}

# risk_adjusted обрабатывается отдельно (нужен второй аргумент — risk_scores),
# поэтому не входит в _MODEL_DISPATCH с сигнатурой fn(adapters).
_RISK_MODEL_ALIASES = {"risk_adjusted", "risk", "risk_adjusted_weight"}

# Алиасы идентификаторов: адаптерный protocol → slug в data/risk_scores.json.
# Нормализация в allocation_models снимает регистр/разделители, но не различия
# в самом имени: адаптер "morpho_blue" соответствует slug "morpho".
_PROTOCOL_ALIASES = {
    "morpho_blue": "morpho",
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
    # SPA-V405: explicit deployment breakdown after T1-anchor remainder fill.
    cash_pct: float = 0.0
    t1_pct: float = 0.0
    t2_pct: float = 0.0
    total_deployed_pct: float = 0.0
    # SPA-V406: risk-aware аллокация на основе data/risk_scores.json.
    risk_model_applied: bool = False
    # protocol → {risk_grade, risk_multiplier, pre_risk_weight, post_risk_weight}
    risk_breakdown: dict[str, dict] = field(default_factory=dict)
    # SPA-V408: shadow→allocator feedback loop. Когда лучшая shadow-стратегия
    # (по Sortino, confidence ≥ medium) использована как база весов.
    strategy_loop_active: bool = False
    selected_strategy_id: str | None = None
    strategy_confidence: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class StrategyAllocator:
    """Advisory-аллокатор целевых весов портфеля."""

    CAPITAL = 100_000  # USD paper trading
    T1_CAP = 0.40      # макс 40% на один T1 протокол
    T2_CAP = 0.20      # макс 20% на один T2 протокол (T3 трактуем как T2)

    def __init__(
        self,
        status_path: str | os.PathLike | None = None,
        risk_scores_path: str | os.PathLike | None = None,
        allocation_model: str | None = None,
        strategy_loop_enabled: bool = True,
        comparison_path: str | os.PathLike | None = None,
        strategies_dir: str | os.PathLike | None = None,
    ):
        self.status_path = Path(status_path) if status_path else _STATUS_PATH
        self.risk_scores_path = (
            Path(risk_scores_path) if risk_scores_path else _RISK_SCORES_PATH
        )
        self.allocation_model = allocation_model or DEFAULT_MODEL
        # SPA-V408: shadow→allocator feedback loop.
        self.strategy_loop_enabled = strategy_loop_enabled
        self.comparison_path = (
            Path(comparison_path) if comparison_path else _SHADOW_COMPARISON_PATH
        )
        self.strategies_dir = Path(strategies_dir) if strategies_dir else None

    # ── выбор лучшей shadow-стратегии (SPA-V408) ──────────────────────────
    def _select_shadow_strategy(self) -> dict | None:
        """Пытается выбрать лучшую shadow-стратегию через StrategySelector.

        Строго read-only: читает только ``strategy_shadow_comparison.json`` и
        ``data/strategies/{name}.json``. Любая ошибка → ``None`` (аллокатор тогда
        деградирует на сконфигурированную модель). Возвращает dict выбора
        (см. :meth:`StrategySelector.select_best`) или ``None``.
        """
        try:
            kwargs = {"comparison_path": self.comparison_path}
            if self.strategies_dir is not None:
                kwargs["strategies_dir"] = self.strategies_dir
            selector = StrategySelector(**kwargs)
            return selector.select_best()
        except Exception as e:  # никогда не валим аллокацию из-за селектора
            log.warning("StrategySelector failed (%s) — fallback на модель", e)
            return None

    # ── загрузка risk-оценок (SPA-V406) ───────────────────────────────────
    def _load_risk_scores(self) -> tuple[dict[str, str], bool]:
        """Читает ``data/risk_scores.json`` (вывод risk scoring engine).

        Возвращает ``(mapping, loaded)`` где ``mapping`` — ``slug → grade``
        (плюс адаптерные алиасы из :data:`_PROTOCOL_ALIASES`), а ``loaded``
        — успешно ли загружены оценки. Любая ошибка (файл отсутствует, битый
        JSON, неожиданная схема) → ``({}, False)`` без исключения: аллокатор
        тогда деградирует на equal_weight. Модуль остаётся read-only и НЕ
        импортирует код scoring engine — читается только его JSON-снимок.
        """
        if not self.risk_scores_path.exists():
            log.info("risk_scores.json не найден (%s) — risk-модель не применяется",
                     self.risk_scores_path)
            return {}, False
        try:
            raw = json.loads(self.risk_scores_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.warning("risk_scores.json повреждён (%s) — fallback equal_weight: %s",
                        self.risk_scores_path, e)
            return {}, False

        mapping: dict[str, str] = {}
        if isinstance(raw, dict):
            for s in raw.get("scores", []):
                if not isinstance(s, dict):
                    continue
                slug = s.get("slug") or s.get("protocol")
                grade = s.get("grade")
                if slug and grade:
                    mapping[str(slug)] = str(grade).strip().upper()

        if not mapping:
            log.warning("risk_scores.json без валидных оценок — fallback equal_weight")
            return {}, False

        # Адаптерные алиасы: morpho_blue → grade(morpho) и т.п.
        for adapter_name, slug in _PROTOCOL_ALIASES.items():
            if slug in mapping:
                mapping.setdefault(adapter_name, mapping[slug])

        return mapping, True

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

    # ── заполнение остатка T1-якорем (SPA-V405) ───────────────────────────
    def _fill_remainder(
        self,
        weights: dict[str, float],
        tier_map: dict[str, str],
        apy_map: dict[str, float],
        exclude: set[str] | None = None,
    ) -> tuple[dict[str, float], bool]:
        """Заполняет нераспределённый остаток в headroom доступных адаптеров.

        Структурный 20% cash-drag возникает, когда 4 T2-адаптера (cap 20% каждый)
        могут разместить максимум 80%, а T1-якоря нет. Этот шаг направляет
        остаток капитала в свободную ёмкость (cap − текущий вес) — СНАЧАЛА в
        T1-адаптеры (cap 40%, приоритет якоря), ПОТОМ в T2 — в порядке убывания
        APY. Веса никогда не превышают cap'ы тира.

        ``exclude`` — протоколы, исключённые риск-моделью (grade D): им НЕЛЬЗЯ
        возвращать капитал через headroom-fill, иначе D-исключение нарушится.

        Если ни у одного адаптера нет headroom (всё уперлось в cap'ы) — остаток
        честно остаётся кэшем. Возвращает ``(weights, filled)``.
        """
        excluded = exclude or set()
        w = dict(weights)
        # Полная вселенная адаптеров — включая те, которым модель дала 0
        # (например best_apy выбирает только top-N). Их headroom тоже доступен,
        # КРОМЕ исключённых риском (grade D) — они остаются с весом 0.
        universe = [p for p in tier_map.keys() if p not in excluded]
        caps = {p: self._cap_for(tier_map.get(p, "T2")) for p in universe}

        remainder = max(0.0, 1.0 - sum(w.values()))
        if remainder <= 1e-9:
            return w, False

        filled = False
        # T1 (якорь) первым, затем T2; внутри тира — по убыванию APY.
        for tier_filter in ("T1", "T2"):
            if remainder <= 1e-9:
                break
            candidates = sorted(
                (
                    p
                    for p in universe
                    if str(tier_map.get(p, "T2")).upper() == tier_filter
                ),
                key=lambda p: apy_map.get(p, 0.0),
                reverse=True,
            )
            for p in candidates:
                if remainder <= 1e-9:
                    break
                headroom = caps[p] - w.get(p, 0.0)
                if headroom <= 1e-9:
                    continue
                add = min(headroom, remainder)
                w[p] = w.get(p, 0.0) + add
                remainder -= add
                filled = True
        return w, filled

    # ── основной расчёт ───────────────────────────────────────────────────
    def allocate(self, model: str | None = None) -> AllocationResult:
        model = model or self.allocation_model
        is_risk_model = model in _RISK_MODEL_ALIASES
        if not is_risk_model and model not in _MODEL_DISPATCH:
            raise ValueError(
                f"Неизвестная модель аллокации: {model!r}. "
                f"Доступны: {sorted(set(_MODEL_DISPATCH) | _RISK_MODEL_ALIASES)}"
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
                cash_pct=1.0,
                t1_pct=0.0,
                t2_pct=0.0,
                total_deployed_pct=0.0,
                risk_model_applied=False,
                risk_breakdown={},
                strategy_loop_active=False,
                selected_strategy_id=None,
                strategy_confidence=None,
                notes=notes,
            )

        tier_map = {a["protocol"]: a["tier"] for a in adapters}
        apy_map = {a["protocol"]: a["apy_pct"] for a in adapters}

        risk_model_applied = False
        risk_breakdown: dict[str, dict] = {}
        excluded: set[str] = set()

        strategy_loop_active = False
        selected_strategy_id: str | None = None
        strategy_confidence: str | None = None
        raw_weights: dict[str, float] | None = None

        # ── SPA-V408: shadow→allocator feedback loop ──────────────────────
        # Если включено — пробуем взять веса лучшей shadow-стратегии (по Sortino,
        # confidence ≥ medium) как БАЗУ. Cap'ы по тирам и risk-grade исключения
        # применяются ПОВЕРХ — стратегия не может обойти лимиты или вернуть
        # капитал в grade-D протокол.
        if self.strategy_loop_enabled:
            best = self._select_shadow_strategy()
            if best and best.get("confidence") in ("medium", "high"):
                sw = best.get("allocation_weights") or {}
                # Только веса по живым адаптерам — стратегия могла держать пул,
                # которого нет в текущем снимке оркестратора.
                sw = {
                    p: float(w)
                    for p, w in sw.items()
                    if p in tier_map and (float(w) if w is not None else 0.0) > 0
                }
                if sw:
                    raw_weights = sw
                    strategy_loop_active = True
                    selected_strategy_id = best.get("strategy_id")
                    strategy_confidence = best.get("confidence")
                    notes.append(
                        f"SPA-V408: shadow-стратегия '{selected_strategy_id}' "
                        f"использована как база весов (confidence="
                        f"{strategy_confidence}, Sortino={best.get('sortino')}, "
                        f"N={best.get('days_running')}д)."
                    )
                    log.info(
                        "strategy_loop_active: %s (confidence=%s)",
                        selected_strategy_id, strategy_confidence,
                    )
                    # Risk-grade исключения (grade D) применяем ПОВЕРХ весов
                    # стратегии — это жёсткий safety-гейт, не зависящий от модели.
                    risk_scores, loaded = self._load_risk_scores()
                    if loaded:
                        bd = models.risk_adjusted_breakdown(adapters, risk_scores)
                        excluded = set(bd["excluded"])
                        risk_breakdown = bd["per_protocol"]
                        risk_model_applied = True
                        if excluded:
                            notes.append(
                                "excluded_by_risk (поверх shadow-весов): "
                                + str(sorted(excluded))
                            )
                            log.info("excluded_by_risk: %s", sorted(excluded))

        # ── fallback: сконфигурированная модель (текущее поведение) ───────
        if not strategy_loop_active:
            if is_risk_model:
                risk_scores, loaded = self._load_risk_scores()
                if not loaded:
                    # Защитный fallback: нет/битый risk_scores.json → equal_weight.
                    notes.append(
                        "risk_scores.json отсутствует или повреждён — риск-модель НЕ "
                        "применена, fallback на equal_weight."
                    )
                    raw_weights = models.equal_weight(adapters)
                else:
                    bd = models.risk_adjusted_breakdown(adapters, risk_scores)
                    raw_weights = bd["weights"]
                    risk_breakdown = bd["per_protocol"]
                    excluded = set(bd["excluded"])
                    risk_model_applied = True
                    if bd["excluded"]:
                        notes.append("excluded_by_risk: " + str(sorted(bd["excluded"])))
                        log.info("excluded_by_risk: %s", sorted(bd["excluded"]))
                    if bd["fallback_equal_weight"]:
                        notes.append(
                            "WARNING: все протоколы исключены риск-моделью "
                            "(grade D или нулевой APY) — fallback на equal_weight."
                        )
            else:
                raw_weights = _MODEL_DISPATCH[model](adapters)

        # Исключённые риском (grade D) убираем из расчёта целиком: иначе
        # _apply_caps перераспределит на них excess, а _fill_remainder — остаток.
        weights_for_alloc = {p: w for p, w in raw_weights.items() if p not in excluded}

        capped, was_capped = self._apply_caps(weights_for_alloc, tier_map)
        if was_capped:
            notes.append("Веса ограничены cap'ами по тирам (T1≤40%, T2≤20%).")

        # SPA-V405: устранение структурного cash-drag — остаток после cap'ов
        # направляется в свободную ёмкость T1-якоря (затем T2), а не в кэш.
        # Исключённые риском (grade D) протоколы НЕ получают этот остаток.
        capped, filled = self._fill_remainder(capped, tier_map, apy_map, exclude=excluded)

        # Возвращаем исключённые риском протоколы в вывод с нулевым весом —
        # для прозрачности (видно, что они учтены и сознательно занулены).
        for p in excluded:
            capped.setdefault(p, 0.0)
        if filled:
            notes.append(
                "Остаток после cap'ов размещён в headroom T1-якоря/T2 "
                "(устранение cash-drag, SPA-V405)."
            )

        allocated = sum(capped.values())
        unallocated = max(0.0, 1.0 - allocated)
        if unallocated > 1e-6:
            notes.append(
                f"Нераспределённый кэш-буфер: {unallocated * 100:.2f}% "
                "(остаток после применения cap'ов и заполнения T1-якорем)."
            )

        # Разбивка размещения по тирам (T3 трактуем как T2, как и cap'ы).
        t1_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() == "T1"
        )
        t2_pct = sum(
            w for p, w in capped.items() if str(tier_map.get(p, "T2")).upper() != "T1"
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
            cash_pct=round(unallocated, 6),
            t1_pct=round(t1_pct, 6),
            t2_pct=round(t2_pct, 6),
            total_deployed_pct=round(allocated, 6),
            risk_model_applied=risk_model_applied,
            risk_breakdown=risk_breakdown,
            strategy_loop_active=strategy_loop_active,
            selected_strategy_id=selected_strategy_id,
            strategy_confidence=strategy_confidence,
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
        default=DEFAULT_MODEL,
        choices=sorted(set(_MODEL_DISPATCH) | _RISK_MODEL_ALIASES),
        help="Модель аллокации (по умолчанию risk_adjusted)",
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="Путь вывода")
    args = parser.parse_args()

    allocator = StrategyAllocator()
    result = allocator.allocate(model=args.model)
    allocator.save(result, args.out)
    print(f"Модель: {result.model_used}")
    print(f"Риск-модель применена: {result.risk_model_applied}")
    print(f"Веса: {result.target_weights}")
    print(f"USD: {result.target_usd}")
    print(f"Ожидаемый APY: {result.expected_apy_pct}%")
    print(f"Нераспределено: {result.unallocated_pct * 100:.2f}%")
    print(f"Сохранено в {args.out}")


if __name__ == "__main__":
    main()
