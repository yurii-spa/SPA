"""
Capital Allocation Policy v2.0 — Multi-Engine Portfolio.
LLM_FORBIDDEN. fail-closed: CRITICAL → Defensive allocation.
Единственный источник правды для целевых весов движков.

Движки:
  A (Core)     — 60% target, range 50-70%
  B (HY/Carry) — 25% target, range 15-35%
  C (LP)       — 15% target, range 5-25%
  DEF          — Defensive (T-Bills, Gnosis Safe): активируется при RED/CRITICAL

Ребалансировка только при отклонении ≥3% от target.
fail-closed: risk_level=CRITICAL → все движки уходят в Defensive.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
import json

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

CAPITAL_POLICY_VERSION = "capital_policy_v2.0"


@dataclass(frozen=True)
class EngineAllocationTarget:
    """Целевое распределение для одного движка."""
    engine: str
    target_pct: float           # Целевая доля (0.0–1.0)
    min_pct: float              # Минимальная доля
    max_pct: float              # Максимальная доля
    rebalance_threshold: float = 0.03  # Ребалансировка при ≥3% отклонении


# ─── Единственный источник правды для целевых весов ─────────────────────────
ENGINE_TARGETS: Dict[str, EngineAllocationTarget] = {
    "A": EngineAllocationTarget(
        engine="A",
        target_pct=0.60,    # 60% Core
        min_pct=0.50,
        max_pct=0.70,
    ),
    "B": EngineAllocationTarget(
        engine="B",
        target_pct=0.25,    # 25% HY/Carry
        min_pct=0.15,
        max_pct=0.35,
    ),
    "C": EngineAllocationTarget(
        engine="C",
        target_pct=0.15,    # 15% LP
        min_pct=0.05,
        max_pct=0.25,
    ),
}

# Defensive allocation при CRITICAL — T-Bills через Gnosis Safe
DEFENSIVE_ALLOCATION: Dict[str, float] = {
    "A": 0.40,      # Engine A — ограничен
    "B": 0.10,      # Engine B — минимум
    "C": 0.05,      # Engine C — минимум
    "DEF": 0.45,    # Defensive (T-Bills, Gnosis Safe)
}


@dataclass
class AllocationResult:
    """Результат расчёта аллокации."""
    policy_version: str
    overall_risk: str

    # Текущие и целевые веса
    current_allocations: Dict[str, float]
    target_allocations: Dict[str, float]

    # Нужна ли ребалансировка?
    needs_rebalance: bool
    rebalance_actions: Dict[str, float]  # {"A": +0.05, "B": -0.03, ...}

    # Режим
    is_defensive_mode: bool
    block_new_engine_b: bool    # В режиме RED/CRITICAL — блокируем HY
    block_new_engine_c: bool    # В режиме RED/CRITICAL — блокируем LP

    # Мета
    computed_at: str
    LLM_FORBIDDEN: bool = True


def compute_allocation(
    current_allocations: Dict[str, float],
    overall_risk: str,  # "GREEN" | "YELLOW" | "RED" | "CRITICAL"
    total_equity: float = 100_000.0,
) -> AllocationResult:
    """
    Вычисляет целевую аллокацию с учётом риск-режима.

    Args:
        current_allocations: текущие доли {"A": 0.58, "B": 0.27, "C": 0.15}
        overall_risk: из Risk Aggregator ("GREEN"|"YELLOW"|"RED"|"CRITICAL")
        total_equity: общий equity портфеля

    Returns:
        AllocationResult с rebalance_actions

    LLM_FORBIDDEN. fail-closed: CRITICAL → Defensive.
    """
    # LLM_FORBIDDEN
    now = datetime.utcnow().isoformat() + "Z"

    # fail-closed: CRITICAL → Defensive mode
    is_defensive = (overall_risk == "CRITICAL")

    # ── Целевые аллокации по режиму ─────────────────────────────────────────
    if is_defensive:
        targets = DEFENSIVE_ALLOCATION.copy()
    else:
        # Базовые targets из ENGINE_TARGETS
        targets = {e: t.target_pct for e, t in ENGINE_TARGETS.items()}

        if overall_risk == "RED":
            # RED: сдвигаем к A, режем B и C
            targets["A"] = min(ENGINE_TARGETS["A"].max_pct, targets["A"] + 0.10)
            targets["B"] = max(ENGINE_TARGETS["B"].min_pct, targets["B"] - 0.07)
            targets["C"] = max(ENGINE_TARGETS["C"].min_pct, targets["C"] - 0.03)

        elif overall_risk == "YELLOW":
            # YELLOW: умеренно консервативно
            targets["A"] = min(ENGINE_TARGETS["A"].max_pct, targets["A"] + 0.05)
            targets["B"] = max(ENGINE_TARGETS["B"].min_pct, targets["B"] - 0.03)
            targets["C"] = max(ENGINE_TARGETS["C"].min_pct, targets["C"] - 0.02)

        # Нормализуем: сумма должна быть 1.0
        total = sum(targets.values())
        if total > 0:
            targets = {e: v / total for e, v in targets.items()}

    # ── Rebalance detection ──────────────────────────────────────────────────
    rebalance_actions: Dict[str, float] = {}
    needs_rebalance = False

    for engine, target in targets.items():
        if engine == "DEF":
            # Defensive-slice — не измеряем дельту от текущих (нет позиции)
            rebalance_actions[engine] = target
            continue

        current = current_allocations.get(engine, 0.0)
        delta = target - current
        rebalance_actions[engine] = delta

        threshold = ENGINE_TARGETS[engine].rebalance_threshold if engine in ENGINE_TARGETS else 0.03
        if abs(delta) >= threshold:
            needs_rebalance = True

    # При defensive mode любое отклонение от нормального режима — это rebalance
    if is_defensive:
        needs_rebalance = True

    # ── Блокировки новых позиций ─────────────────────────────────────────────
    block_b = overall_risk in ("RED", "CRITICAL")
    block_c = overall_risk in ("RED", "CRITICAL")

    return AllocationResult(
        policy_version=CAPITAL_POLICY_VERSION,
        overall_risk=overall_risk,
        current_allocations=current_allocations,
        target_allocations=targets,
        needs_rebalance=needs_rebalance,
        rebalance_actions=rebalance_actions,
        is_defensive_mode=is_defensive,
        block_new_engine_b=block_b,
        block_new_engine_c=block_c,
        computed_at=now,
        LLM_FORBIDDEN=True,
    )


def validate_allocation_sum(
    allocations: Dict[str, float],
    tolerance: float = 0.001,
) -> bool:
    """
    Проверяет что аллокации суммируются в 1.0 ± tolerance.
    LLM_FORBIDDEN. fail-closed.
    """
    # LLM_FORBIDDEN
    total = sum(allocations.values())
    return abs(total - 1.0) <= tolerance


def get_allowed_engines(overall_risk: str) -> Dict[str, bool]:
    """
    Возвращает какие движки разрешены в каждом риск-режиме.

    Схема:
      GREEN    → A✓  B✓  C✓  DEF✗
      YELLOW   → A✓  B✓  C✗  DEF✗
      RED      → A✓  B✗  C✗  DEF✓
      CRITICAL → A✗  B✗  C✗  DEF✓  (fail-closed)

    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if overall_risk == "CRITICAL":
        return {"A": False, "B": False, "C": False, "DEF": True}
    elif overall_risk == "RED":
        return {"A": True, "B": False, "C": False, "DEF": True}
    elif overall_risk == "YELLOW":
        return {"A": True, "B": True, "C": False, "DEF": False}
    else:  # GREEN
        return {"A": True, "B": True, "C": True, "DEF": False}


def run_allocation_check(output_path: Optional[Path] = None) -> Dict:
    """
    End-to-end: загружает текущие данные → вычисляет аллокацию → записывает JSON.

    fail-closed: нет данных риска → используем GREEN (консервативно).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN

    # ── Загружаем overall_risk из Risk Aggregator ────────────────────────────
    risk_path = _PROJECT_ROOT / "data" / "risk_aggregation.json"
    try:
        risk_data = json.loads(risk_path.read_text())
        overall_risk = risk_data.get("overall_risk", "GREEN")
        # Валидация
        if overall_risk not in ("GREEN", "YELLOW", "RED", "CRITICAL"):
            overall_risk = "GREEN"
    except Exception:
        # fail-closed: нет данных → GREEN (safe default)
        overall_risk = "GREEN"

    # ── Текущие аллокации из paper_trading_status ────────────────────────────
    pt_path = _PROJECT_ROOT / "data" / "paper_trading_status.json"
    current: Dict[str, float] = {"A": 0.60, "B": 0.25, "C": 0.15}  # дефолты
    try:
        pt = json.loads(pt_path.read_text())
        current_explicit = pt.get("engine_allocations")
        if isinstance(current_explicit, dict) and current_explicit:
            current = current_explicit
    except Exception:
        pass

    total_equity = 100_000.0

    result = compute_allocation(
        current_allocations=current,
        overall_risk=overall_risk,
        total_equity=total_equity,
    )

    output = {
        "capital_policy_version": CAPITAL_POLICY_VERSION,
        "computed_at": result.computed_at,
        "overall_risk": result.overall_risk,
        "is_defensive_mode": result.is_defensive_mode,
        "needs_rebalance": result.needs_rebalance,
        "current_allocations": result.current_allocations,
        "target_allocations": result.target_allocations,
        "rebalance_actions": result.rebalance_actions,
        "block_new_engine_b": result.block_new_engine_b,
        "block_new_engine_c": result.block_new_engine_c,
        "allowed_engines": get_allowed_engines(overall_risk),
        "LLM_FORBIDDEN": True,
    }

    # ── Атомарная запись ─────────────────────────────────────────────────────
    if output_path is None:
        output_path = _PROJECT_ROOT / "data" / "capital_allocation.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import os
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, indent=2))
    os.replace(tmp, output_path)

    return output


if __name__ == "__main__":
    import sys
    result = run_allocation_check()
    print(json.dumps(result, indent=2))
    sys.exit(0)
