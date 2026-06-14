"""
SPA Risk Policy — Оси риска v2 (MP-208)
Чистые функции для расчёта осей кредитного, peg-, дюрационного и бридж-рисков.

Governance: LLM FORBIDDEN — только детерминированный код.
ADR: docs/ADR_008_risk_axes_v2.md
Версия: v2.0 (2026-06-11)

Все функции принимают:
    allocation: dict  — {protocol_name: weight_fraction} (веса 0…1, сумма ≤ 1)

Substring-матчинг имён протоколов выполняется case-insensitive:
    "AAVE_V3_USDC" совпадает с "aave".
"""
from __future__ import annotations

# ─── Константы протоколов по осям риска ──────────────────────────────────────

CREDIT_PROTOCOLS: list[str] = ["maple", "clearpool", "ipor"]
"""Протоколы с uncollateralized / credit риском."""

PEG_PROTOCOLS: list[str] = ["ethena", "susde", "crvusd", "fraxlend", "frax"]
"""Протоколы с peg-риском не-USDC/USDT активов."""

BRIDGE_PROTOCOLS: list[str] = ["across", "stargate", "layerzero"]
"""Cross-chain протоколы с bridge-риском."""

DURATION_DEFAULT_PROTOCOLS: list[str] = ["pendle", "maple", "morpho_lock"]
"""Протоколы с exit_latency > 24h (дефолтный список при отсутствии exit_latency_map)."""

_DURATION_DEFAULT_HOURS: float = 168.0  # 7 дней — дефолт для duration-списка

_MATURITY_DAYS_KEY: str = "_maturity_days"
"""Служебный ключ в exit_latency_map для передачи maturity_days: {proto: days}."""


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _matches(protocol_key: str, names: list[str]) -> bool:
    """Substring-матчинг (case-insensitive): protocol_key содержит любое из names."""
    key = protocol_key.lower()
    return any(n.lower() in key for n in names)


def _collect_matched(allocation: dict, names: list[str]) -> tuple[float, list[str]]:
    """Сумма весов протоколов, чьи ключи substring-совпадают с именами из names."""
    total: float = 0.0
    matched: list[str] = []
    for proto, w in allocation.items():
        if _matches(proto, names):
            total += float(w)
            matched.append(proto)
    return total, matched


def _resolve_latency(proto: str, exit_latency_map: dict) -> float | None:
    """
    Получить exit_latency_hours для протокола.

    Порядок поиска:
    1. Точное совпадение ключа в exit_latency_map
    2. Substring-матчинг с ключами exit_latency_map (пропускаем "_" служебные)
    3. Дефолт из DURATION_DEFAULT_PROTOCOLS → _DURATION_DEFAULT_HOURS
    4. None — протокол не считается duration-протоколом
    """
    proto_lower = proto.lower()

    # Шаг 1: точное совпадение
    if proto in exit_latency_map:
        val = exit_latency_map[proto]
        if isinstance(val, (int, float)):
            return float(val)

    # Шаг 2: substring-матчинг
    for k, v in exit_latency_map.items():
        if k.startswith("_"):  # пропускаем служебные ключи
            continue
        if not isinstance(v, (int, float)):
            continue
        k_lower = k.lower()
        if k_lower in proto_lower or proto_lower in k_lower:
            return float(v)

    # Шаг 3: дефолт для известных duration-протоколов
    if _matches(proto, DURATION_DEFAULT_PROTOCOLS):
        return _DURATION_DEFAULT_HOURS

    return None


def _resolve_maturity(proto: str, maturity_days_map: dict) -> float | None:
    """Получить maturity_days для протокола (substring-матчинг)."""
    proto_lower = proto.lower()
    for k, v in maturity_days_map.items():
        k_lower = k.lower()
        if k_lower in proto_lower or proto_lower in k_lower:
            if isinstance(v, (int, float)):
                return float(v)
    return None


# ─── Оси риска ───────────────────────────────────────────────────────────────

def check_credit_axis(allocation: dict, limit: float = 0.15) -> dict:
    """
    CREDIT_AXIS: суммарная доля credit-протоколов ≤ limit (дефолт 15%).

    credit_protocols = ["maple", "clearpool", "ipor"]

    Args:
        allocation: {protocol_name: weight_fraction} (веса 0…1, сумма ≤ 1)
        limit: максимально допустимая доля (дефолт 0.15)

    Returns:
        {"ok": bool, "credit_weight": float, "limit": float, "protocols": list[str]}
    """
    credit_weight, protocols = _collect_matched(allocation, CREDIT_PROTOCOLS)
    return {
        "ok": credit_weight <= limit,
        "credit_weight": round(credit_weight, 8),
        "limit": limit,
        "protocols": protocols,
    }


def check_peg_axis(allocation: dict, limit: float = 0.10) -> dict:
    """
    PEG_AXIS: суммарная доля peg-риск-протоколов ≤ limit (дефолт 10%).

    peg_protocols = ["ethena", "susde", "crvusd", "fraxlend", "frax"]

    Args:
        allocation: {protocol_name: weight_fraction}
        limit: максимально допустимая доля (дефолт 0.10)

    Returns:
        {"ok": bool, "peg_weight": float, "limit": float, "protocols": list[str]}
    """
    peg_weight, protocols = _collect_matched(allocation, PEG_PROTOCOLS)
    return {
        "ok": peg_weight <= limit,
        "peg_weight": round(peg_weight, 8),
        "limit": limit,
        "protocols": protocols,
    }


def check_duration_axis(
    allocation: dict,
    exit_latency_map: dict,
    limit: float = 0.30,
    maturity_limit: float = 0.15,
) -> dict:
    """
    DURATION_AXIS: доля протоколов с exit_latency > 24h ≤ limit (дефолт 30%).
    Maturity ladder: среди duration-протоколов доля с maturity < 30 дней ≤ maturity_limit.

    Args:
        allocation: {protocol_name: weight_fraction}
        exit_latency_map: {protocol_name: hours_float}
            Опционально: ключ "_maturity_days": {protocol_name: days_float}
            для проверки maturity ladder.
        limit: максимальная доля duration-протоколов (дефолт 0.30)
        maturity_limit: максимальная доля short-maturity среди всего портфеля (дефолт 0.15)

    Returns:
        {
            "ok": bool,
            "duration_weight": float,
            "short_maturity_weight": float,
            "duration_limit": float,
            "maturity_limit": float,
            "duration_protocols": list[str],
            "short_maturity_protocols": list[str],
            "violations": list[str],
        }
    """
    maturity_days_map: dict = exit_latency_map.get(_MATURITY_DAYS_KEY, {})

    duration_protocols: list[str] = []
    duration_weight: float = 0.0

    for proto, w in allocation.items():
        latency = _resolve_latency(proto, exit_latency_map)
        if latency is not None and latency > 24.0:
            duration_protocols.append(proto)
            duration_weight += float(w)

    # Maturity ladder: duration-протоколы с maturity < 30 дней
    short_maturity_protocols: list[str] = []
    short_maturity_weight: float = 0.0
    for proto in duration_protocols:
        days = _resolve_maturity(proto, maturity_days_map)
        if days is not None and days < 30:
            short_maturity_protocols.append(proto)
            short_maturity_weight += float(allocation.get(proto, 0.0))

    violations: list[str] = []
    if duration_weight > limit:
        violations.append(
            f"duration_weight {duration_weight:.1%} exceeds duration_limit {limit:.1%}"
        )
    if short_maturity_weight > maturity_limit:
        violations.append(
            f"short_maturity_weight {short_maturity_weight:.1%} exceeds maturity_limit {maturity_limit:.1%}"
        )

    return {
        "ok": len(violations) == 0,
        "duration_weight": round(duration_weight, 8),
        "short_maturity_weight": round(short_maturity_weight, 8),
        "duration_limit": limit,
        "maturity_limit": maturity_limit,
        "duration_protocols": duration_protocols,
        "short_maturity_protocols": short_maturity_protocols,
        "violations": violations,
    }


def check_bridge_axis(
    allocation: dict,
    per_cap: float = 0.05,
    total_limit: float = 0.10,
) -> dict:
    """
    BRIDGE_AXIS: per-protocol ≤ per_cap (5%) AND суммарно ≤ total_limit (10%).

    bridge_protocols = ["across", "stargate", "layerzero"]

    Args:
        allocation: {protocol_name: weight_fraction}
        per_cap: максимальная доля на один bridge-протокол (дефолт 0.05)
        total_limit: максимальная суммарная доля bridge-протоколов (дефолт 0.10)

    Returns:
        {
            "ok": bool,
            "bridge_weight": float,
            "violations": list[str],
            "protocols": list[str],
            "per_cap": float,
            "total_limit": float,
        }
    """
    violations: list[str] = []
    matched_protocols: list[str] = []
    bridge_weight: float = 0.0

    for proto, w in allocation.items():
        w = float(w)
        if _matches(proto, BRIDGE_PROTOCOLS):
            matched_protocols.append(proto)
            bridge_weight += w
            if w > per_cap:
                violations.append(
                    f"{proto}: weight {w:.1%} exceeds per-cap {per_cap:.1%}"
                )

    if bridge_weight > total_limit:
        violations.append(
            f"total bridge weight {bridge_weight:.1%} exceeds total_limit {total_limit:.1%}"
        )

    return {
        "ok": len(violations) == 0,
        "bridge_weight": round(bridge_weight, 8),
        "violations": violations,
        "protocols": matched_protocols,
        "per_cap": per_cap,
        "total_limit": total_limit,
    }


def check_all_axes(
    allocation: dict,
    exit_latency_map: dict | None = None,
) -> dict:
    """
    Проверить все 4 оси риска: credit, peg, duration, bridge.

    Args:
        allocation: {protocol_name: weight_fraction}
        exit_latency_map: {protocol_name: hours_float} (опционально)

    Returns:
        {
            "credit": dict,
            "peg": dict,
            "duration": dict,
            "bridge": dict,
            "ok": bool,             # True если все 4 оси ok
            "summary": "ok"|"fail",
            "violations": list[str],  # все нарушения по всем осям
        }
    """
    if exit_latency_map is None:
        exit_latency_map = {}

    credit = check_credit_axis(allocation)
    peg = check_peg_axis(allocation)
    duration = check_duration_axis(allocation, exit_latency_map)
    bridge = check_bridge_axis(allocation)

    all_ok = credit["ok"] and peg["ok"] and duration["ok"] and bridge["ok"]

    violations: list[str] = []
    if not credit["ok"]:
        violations.append(
            f"CREDIT axis: credit_weight={credit['credit_weight']:.1%} > limit {credit['limit']:.1%}"
        )
    if not peg["ok"]:
        violations.append(
            f"PEG axis: peg_weight={peg['peg_weight']:.1%} > limit {peg['limit']:.1%}"
        )
    for v in duration.get("violations", []):
        violations.append(f"DURATION axis: {v}")
    for v in bridge.get("violations", []):
        violations.append(f"BRIDGE axis: {v}")

    return {
        "credit": credit,
        "peg": peg,
        "duration": duration,
        "bridge": bridge,
        "ok": all_ok,
        "summary": "ok" if all_ok else "fail",
        "violations": violations,
    }
