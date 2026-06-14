"""
SPA Capacity Limits (MP-209) — детерминированный код (без LLM).

Правило: позиция SPA в одном протоколе не должна превышать MAX_CAPACITY_PCT
от TVL пула (по умолчанию 1% = 0.01).

Мотивация: если вложить $50K в пул с TVL $200K — займём 25%, что создаёт
огромный market impact при выходе и концентрационный риск.

Режим: warn-only первые 2 недели (ADR-009), затем enforce.
ADR: docs/ADR_009_capacity_limits.md

КОНСТИТУЦИОННЫЙ ИНВАРИАНТ: LLM ЗАПРЕЩЁН в этом модуле.
Только stdlib — без внешних зависимостей.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# 1% от TVL пула — максимально допустимая позиция
MAX_CAPACITY_PCT: float = 0.01

# T1 адаптеры с TVL > $1B могут держать до 3% (ADR-009)
T1_HIGH_TVL_CAPACITY_PCT: float = 0.03
T1_HIGH_TVL_THRESHOLD_USD: float = 1_000_000_000.0


def check_capacity(
    protocol_id: str,
    proposed_amount_usd: float,
    pool_tvl_usd: float,
    max_pct: float = MAX_CAPACITY_PCT,
) -> dict:
    """
    Проверяет не превышает ли proposed_amount capacity limit.

    Args:
        protocol_id:         идентификатор протокола
        proposed_amount_usd: предложенная позиция в USD
        pool_tvl_usd:        TVL пула в USD
        max_pct:             максимально допустимая доля TVL (дефолт 1%)

    Returns:
        {
          "ok":               True/False,
          "protocol_id":      str,
          "proposed_usd":     float,
          "pool_tvl_usd":     float,
          "capacity_pct":     proposed / tvl  (0.0 если нет TVL),
          "max_pct":          float (e.g. 0.01),
          "max_deployable_usd": tvl * max_pct,
          "excess_usd":       max(0, proposed - max_deployable),
          "message":          "ok" | "exceeds_capacity_limit: ..." | "no_tvl_data: skipped"
        }
    """
    if pool_tvl_usd is None or pool_tvl_usd <= 0:
        return {
            "ok": True,  # fail-safe: нет TVL → не блокируем
            "protocol_id": protocol_id,
            "proposed_usd": float(proposed_amount_usd),
            "pool_tvl_usd": float(pool_tvl_usd) if pool_tvl_usd is not None else 0.0,
            "capacity_pct": 0.0,
            "max_pct": max_pct,
            "max_deployable_usd": 0.0,
            "excess_usd": 0.0,
            "message": "no_tvl_data: skipped",
        }

    proposed = float(proposed_amount_usd)
    tvl = float(pool_tvl_usd)
    max_deployable = tvl * max_pct
    capacity_pct = proposed / tvl
    ok = capacity_pct <= max_pct
    excess = max(0.0, proposed - max_deployable)

    if ok:
        message = "ok"
    else:
        message = (
            f"exceeds_capacity_limit: proposed {capacity_pct * 100:.2f}% "
            f"> max {max_pct * 100:.2f}%"
        )

    return {
        "ok": ok,
        "protocol_id": protocol_id,
        "proposed_usd": proposed,
        "pool_tvl_usd": tvl,
        "capacity_pct": capacity_pct,
        "max_pct": max_pct,
        "max_deployable_usd": max_deployable,
        "excess_usd": excess,
        "message": message,
    }


def check_all_capacities(
    allocation: dict,
    tvl_map: dict,
    max_pct: float = MAX_CAPACITY_PCT,
) -> dict:
    """
    Проверяет все протоколы в аллокации на соответствие capacity limit.

    Args:
        allocation: {protocol_id: amount_usd}
        tvl_map:    {protocol_id: tvl_usd}
                    Если протокол отсутствует → skip (warn only, не блокируем).
        max_pct:    максимально допустимая доля TVL (дефолт 1%)

    Returns:
        {
          "ok":        True если все протоколы в лимите,
          "violations": [список нарушений],
          "warnings":  [протоколы без TVL данных],
          "results":   {protocol_id: check_capacity(...) result}
        }
    """
    violations: list[str] = []
    warnings: list[str] = []
    results: dict = {}

    for protocol_id, amount_usd in allocation.items():
        # Нормализуем
        try:
            amount_usd = float(amount_usd) if amount_usd is not None else 0.0
        except (TypeError, ValueError):
            amount_usd = 0.0

        if amount_usd <= 0:
            continue  # нулевые и отрицательные позиции пропускаем

        if protocol_id not in tvl_map:
            # Нет TVL — предупреждение, не блокируем
            warnings.append(
                f"no_tvl_data for {protocol_id}: capacity check skipped"
            )
            results[protocol_id] = {
                "ok": True,
                "protocol_id": protocol_id,
                "proposed_usd": amount_usd,
                "pool_tvl_usd": None,
                "capacity_pct": None,
                "max_pct": max_pct,
                "max_deployable_usd": None,
                "excess_usd": 0.0,
                "message": "no_tvl_data: skipped",
            }
            continue

        tvl = tvl_map[protocol_id]
        result = check_capacity(protocol_id, amount_usd, tvl, max_pct)
        results[protocol_id] = result

        if not result["ok"]:
            violations.append(
                f"{protocol_id}: {result['message']} "
                f"(${amount_usd:,.0f} > max ${result['max_deployable_usd']:,.0f})"
            )

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "results": results,
    }


def apply_capacity_caps(
    allocation: dict,
    tvl_map: dict,
    max_pct: float = MAX_CAPACITY_PCT,
) -> dict:
    """
    Обрезает суммы превышающие capacity limit.

    Args:
        allocation: {protocol_id: amount_usd}
        tvl_map:    {protocol_id: tvl_usd}
        max_pct:    максимально допустимая доля TVL (дефолт 1%)

    Returns:
        Новый allocation dict с capped значениями.
        Если TVL неизвестен — оставляет сумму без изменений (fail-safe).
    """
    result: dict = {}

    for protocol_id, amount_usd in allocation.items():
        if amount_usd is None:
            result[protocol_id] = amount_usd
            continue

        try:
            amount_f = float(amount_usd)
        except (TypeError, ValueError):
            result[protocol_id] = amount_usd
            continue

        if protocol_id not in tvl_map:
            # Fail-safe: TVL неизвестен → пропускаем без изменений
            result[protocol_id] = amount_f
            if amount_f > 0:
                log.warning(
                    "capacity_cap: no TVL data for %s — pass-through (fail-safe)",
                    protocol_id,
                )
            continue

        tvl = tvl_map[protocol_id]
        try:
            tvl_f = float(tvl) if tvl is not None else 0.0
        except (TypeError, ValueError):
            tvl_f = 0.0

        if tvl_f <= 0:
            # Нет валидного TVL → pass-through
            result[protocol_id] = amount_f
            continue

        max_deployable = tvl_f * max_pct
        if amount_f > max_deployable:
            log.warning(
                "capacity_cap: %s capped $%.0f → $%.0f "
                "(%.4f%% TVL → %.4f%% TVL, max_pct=%.2f%%)",
                protocol_id,
                amount_f,
                max_deployable,
                amount_f / tvl_f * 100,
                max_pct * 100,
                max_pct * 100,
            )
            result[protocol_id] = max_deployable
        else:
            result[protocol_id] = amount_f

    return result


def build_tvl_map(adapter_status: dict) -> dict:
    """
    Извлекает {protocol_id: tvl_usd} из структуры adapter_orchestrator_status
    или adapter_status.

    Args:
        adapter_status: dict со списком "adapters", каждый с полями
                        "protocol" и "tvl_usd" (или "tvl").

    Returns:
        {protocol_id: tvl_usd}
        Если tvl_usd отсутствует или 0 → не включает в map
        (caller получит warning от check_all_capacities).
    """
    tvl_map: dict = {}

    if not isinstance(adapter_status, dict):
        log.warning("build_tvl_map: ожидался dict, получен %s", type(adapter_status).__name__)
        return tvl_map

    adapters = adapter_status.get("adapters", [])
    if not isinstance(adapters, list):
        log.warning("build_tvl_map: поле 'adapters' не является списком")
        return tvl_map

    for a in adapters:
        if not isinstance(a, dict):
            continue

        protocol = a.get("protocol")
        if not protocol:
            continue

        # Поддерживаем оба варианта поля TVL
        tvl = a.get("tvl_usd")
        if tvl is None:
            tvl = a.get("tvl")

        try:
            tvl_f = float(tvl) if tvl is not None else 0.0
        except (TypeError, ValueError):
            tvl_f = 0.0

        if tvl_f > 0:
            tvl_map[str(protocol)] = tvl_f
        else:
            log.debug(
                "build_tvl_map: пропуск %s (tvl=%.2f)", protocol, tvl_f
            )

    return tvl_map


def effective_max_pct(
    protocol_id: str,
    tier: str,
    pool_tvl_usd: float,
    base_max_pct: float = MAX_CAPACITY_PCT,
) -> float:
    """
    Возвращает эффективный capacity limit с учётом ADR-009 исключения:
    T1 адаптеры с TVL > $1B могут держать до 3%.

    Args:
        protocol_id:  идентификатор протокола (для логирования)
        tier:         "T1" | "T2"
        pool_tvl_usd: TVL пула в USD
        base_max_pct: базовый лимит (дефолт 1%)

    Returns:
        Эффективный max_pct (float)
    """
    if (
        str(tier).upper() == "T1"
        and pool_tvl_usd is not None
        and pool_tvl_usd >= T1_HIGH_TVL_THRESHOLD_USD
    ):
        log.debug(
            "effective_max_pct: T1 high-TVL exception для %s "
            "(tvl=$%.0f ≥ $%.0f → max_pct=%.1f%%)",
            protocol_id, pool_tvl_usd, T1_HIGH_TVL_THRESHOLD_USD,
            T1_HIGH_TVL_CAPACITY_PCT * 100,
        )
        return T1_HIGH_TVL_CAPACITY_PCT
    return base_max_pct
