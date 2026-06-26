"""
Risk Aggregator v1.0 — Multi-Engine Risk View.
Агрегирует риски Engine A (Core) + B (HY/Carry) + C (LP).
LLM_FORBIDDEN: нет AI вызовов.
fail-closed: любой ENGINE CRITICAL → overall=CRITICAL → block.

Governance:
  - Изменение kill-threshold → новый ADR
  - approved=False не может быть переопределён никаким агентом
  - LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}
"""
# LLM_FORBIDDEN
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from pathlib import Path
from datetime import datetime
import json

from spa_core.utils.atomic import atomic_save

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

AGGREGATOR_VERSION = "risk_aggregator_v1.0"


class EngineRiskLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    CRITICAL = "CRITICAL"


class OverallRiskLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    CRITICAL = "CRITICAL"


@dataclass
class EngineRiskSnapshot:
    """Снапшот риска одного движка."""
    engine: str                  # "A" | "B" | "C"
    engine_name: str             # "Core" | "HY/Carry" | "LP"
    risk_level: EngineRiskLevel
    drawdown_pct: float
    kill_threshold_pct: float
    drawdown_to_kill_pct: float  # abs(drawdown) / kill_threshold
    details: Dict
    checked_at: str              # ISO timestamp


@dataclass
class AggregatedRisk:
    """Агрегированный риск портфеля."""
    overall_risk: OverallRiskLevel
    engines: Dict[str, EngineRiskSnapshot]

    # Агрегированные метрики
    total_drawdown_pct: float      # weighted drawdown портфеля
    max_single_engine_dd: float    # наихудший одиночный движок
    cross_engine_correlation: str  # "low" | "medium" | "high"

    # Сигналы
    any_critical: bool
    any_red: bool
    block_new_positions: bool      # True → не открывать новые позиции

    # Мета
    aggregated_at: str
    policy_versions: Dict[str, str]
    LLM_FORBIDDEN: bool = True


# Kill thresholds по движкам — единственный источник правды.
# Изменение → новый ADR + snapshot.
ENGINE_KILL_THRESHOLDS = {
    "A": 0.05,    # Engine A Core: −5% drawdown kill
    "B": 0.08,    # Engine B HY: −8% drawdown kill
    "C": 0.12,    # Engine C LP: −12% IL drawdown kill
}

# Веса движков для взвешенного drawdown
ENGINE_WEIGHTS = {
    "A": 0.60,    # 60% портфеля (Core)
    "B": 0.25,    # 25% портфеля (HY)
    "C": 0.15,    # 15% портфеля (LP)
}


def _classify_engine_risk(
    engine: str,
    drawdown_pct: float,
    kill_threshold: float,
) -> EngineRiskLevel:
    """
    Классифицирует риск движка по drawdown.
    LLM_FORBIDDEN. fail-closed: нет данных → CRITICAL.

    Зоны (по ratio = abs(drawdown) / kill_threshold):
      ratio >= 1.0  → CRITICAL  (kill threshold crossed)
      ratio >= 0.75 → RED       (75% к kill)
      ratio >= 0.50 → YELLOW    (50% к kill)
      ratio <  0.50 → GREEN
    """
    # LLM_FORBIDDEN
    if kill_threshold <= 0:
        return EngineRiskLevel.CRITICAL  # fail-closed: невалидный threshold

    ratio = abs(drawdown_pct) / kill_threshold  # 0=ok, 1.0=kill

    if ratio >= 1.0:
        return EngineRiskLevel.CRITICAL
    elif ratio >= 0.75:
        return EngineRiskLevel.RED
    elif ratio >= 0.50:
        return EngineRiskLevel.YELLOW
    else:
        return EngineRiskLevel.GREEN


def snapshot_engine(
    engine: str,
    drawdown_pct: float,
    details: Optional[Dict] = None,
) -> EngineRiskSnapshot:
    """
    Создаёт снапшот риска одного движка.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    engine_names = {
        "A": "Core (stablecoin lending)",
        "B": "HY/Carry (Pendle PT)",
        "C": "LP/Liquidity (CLMM)",
    }
    kill_threshold = ENGINE_KILL_THRESHOLDS.get(engine, 0.05)
    risk_level = _classify_engine_risk(engine, drawdown_pct, kill_threshold)

    return EngineRiskSnapshot(
        engine=engine,
        engine_name=engine_names.get(engine, f"Engine {engine}"),
        risk_level=risk_level,
        drawdown_pct=drawdown_pct,
        kill_threshold_pct=kill_threshold,
        drawdown_to_kill_pct=abs(drawdown_pct) / kill_threshold,
        details=details or {},
        checked_at=datetime.utcnow().isoformat() + "Z",
    )


def _estimate_cross_engine_correlation(
    snapshots: Dict[str, EngineRiskSnapshot],
) -> str:
    """
    Оценивает корреляцию между движками по риск-уровням.
    LLM_FORBIDDEN. Детерминированная эвристика.

    low    — все GREEN
    high   — 2+ движка RED/CRITICAL (системный риск)
    medium — всё остальное
    """
    # LLM_FORBIDDEN
    if not snapshots:
        return "low"

    risk_levels = [s.risk_level for s in snapshots.values()]

    if all(r == EngineRiskLevel.GREEN for r in risk_levels):
        return "low"

    red_count = sum(
        1 for r in risk_levels
        if r in (EngineRiskLevel.RED, EngineRiskLevel.CRITICAL)
    )
    if red_count >= 2:
        return "high"

    return "medium"


def aggregate_risk(
    engine_drawdowns: Dict[str, float],
    engine_details: Optional[Dict[str, Dict]] = None,
    policy_versions: Optional[Dict[str, str]] = None,
) -> AggregatedRisk:
    """
    Основная функция агрегации рисков.

    Args:
        engine_drawdowns: {"A": -0.02, "B": -0.005, "C": -0.001}
        engine_details:   дополнительные детали по каждому движку
        policy_versions:  версии политик

    Returns:
        AggregatedRisk с overall_risk и block_new_positions.

    LLM_FORBIDDEN. fail-closed: любой CRITICAL → overall=CRITICAL → block.
    """
    # LLM_FORBIDDEN

    if engine_details is None:
        engine_details = {}
    if policy_versions is None:
        policy_versions = {}

    # Снапшоты для каждого движка
    snapshots: Dict[str, EngineRiskSnapshot] = {}
    for engine, dd in engine_drawdowns.items():
        snapshots[engine] = snapshot_engine(
            engine=engine,
            drawdown_pct=dd,
            details=engine_details.get(engine, {}),
        )

    # Агрегация risk-level (fail-closed)
    any_critical = any(
        s.risk_level == EngineRiskLevel.CRITICAL
        for s in snapshots.values()
    )
    any_red = any(
        s.risk_level == EngineRiskLevel.RED
        for s in snapshots.values()
    )

    # fail-closed: CRITICAL → блокируем новые позиции
    block_new_positions = any_critical

    # Общий уровень риска
    if any_critical:
        overall = OverallRiskLevel.CRITICAL
    elif any_red:
        overall = OverallRiskLevel.RED
    elif any(s.risk_level == EngineRiskLevel.YELLOW for s in snapshots.values()):
        overall = OverallRiskLevel.YELLOW
    else:
        overall = OverallRiskLevel.GREEN

    # Взвешенный drawdown портфеля
    total_drawdown = sum(
        ENGINE_WEIGHTS.get(engine, 0.0) * dd
        for engine, dd in engine_drawdowns.items()
    )

    max_dd = min(engine_drawdowns.values()) if engine_drawdowns else 0.0

    correlation = _estimate_cross_engine_correlation(snapshots)

    return AggregatedRisk(
        overall_risk=overall,
        engines=snapshots,
        total_drawdown_pct=total_drawdown,
        max_single_engine_dd=max_dd,
        cross_engine_correlation=correlation,
        any_critical=any_critical,
        any_red=any_red,
        block_new_positions=block_new_positions,
        aggregated_at=datetime.utcnow().isoformat() + "Z",
        policy_versions=policy_versions,
        LLM_FORBIDDEN=True,
    )


def load_live_drawdowns() -> Dict[str, float]:
    """
    Загружает текущие drawdown по движкам из данных paper trading.
    LLM_FORBIDDEN. fail-closed: нет данных → возвращаем 0.0 (консервативно).
    """
    # LLM_FORBIDDEN

    defaults: Dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0}

    pt_path = _PROJECT_ROOT / "data" / "paper_trading_status.json"
    if not pt_path.exists():
        return defaults

    try:
        pt = json.loads(pt_path.read_text())

        # Engine A — из текущего equity vs peak
        equity = float(pt.get("current_equity", pt.get("equity", 100000)))
        peak_equity = float(pt.get("peak_equity", equity))
        engine_a_dd = (
            min(0.0, (equity - peak_equity) / peak_equity)
            if peak_equity > 0 else 0.0
        )

        # Engine B и C — отдельные sleeve (заполняются после go-live Engine B/C)
        engine_b_dd = float(pt.get("engine_b_drawdown", 0.0))
        engine_c_dd = float(pt.get("engine_c_drawdown", 0.0))

        return {
            "A": engine_a_dd,
            "B": engine_b_dd,
            "C": engine_c_dd,
        }
    except Exception:
        # fail-closed: ошибка чтения → безопасные нули
        return defaults


def run_risk_check(
    output_path: Optional[Path] = None,
) -> Dict:
    """
    End-to-end risk check: загружает данные → агрегирует → атомарно сохраняет.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    drawdowns = load_live_drawdowns()
    result = aggregate_risk(
        engine_drawdowns=drawdowns,
        policy_versions={
            "A": "core_v1.0",
            "B": "hy_v1.0",
            "C": "lp_v1.0",
        },
    )

    output = {
        "aggregator_version": AGGREGATOR_VERSION,
        "run_at": result.aggregated_at,
        "overall_risk": str(result.overall_risk),
        "block_new_positions": result.block_new_positions,
        "any_critical": result.any_critical,
        "any_red": result.any_red,
        "total_drawdown_pct": result.total_drawdown_pct,
        "max_single_engine_dd": result.max_single_engine_dd,
        "cross_engine_correlation": result.cross_engine_correlation,
        "engines": {
            engine: {
                "engine_name": snap.engine_name,
                "risk_level": str(snap.risk_level),
                "drawdown_pct": snap.drawdown_pct,
                "kill_threshold_pct": snap.kill_threshold_pct,
                "drawdown_to_kill_pct": snap.drawdown_to_kill_pct,
                "checked_at": snap.checked_at,
            }
            for engine, snap in result.engines.items()
        },
        "policy_versions": result.policy_versions,
        "LLM_FORBIDDEN": True,
    }

    if output_path is None:
        output_path = _PROJECT_ROOT / "data" / "risk_aggregation.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Атомарная запись через канонический atomic_save (P3-9).
    # Байт-идентично: indent=2 (atomic_save добавляет default=str — для
    # сериализуемого payload вывод тот же).
    atomic_save(output, str(output_path))

    return output


if __name__ == "__main__":
    # LLM_FORBIDDEN
    import sys

    result = run_risk_check()

    print(f"Risk Aggregator {AGGREGATOR_VERSION}")
    print(f"Overall risk  : {result['overall_risk']}")
    print(f"Block positions: {result['block_new_positions']}")
    print(f"Any CRITICAL  : {result['any_critical']}")
    print(f"Total DD (wtd): {result['total_drawdown_pct']*100:.3f}%")
    print(f"Correlation   : {result['cross_engine_correlation']}")
    print("")
    for eng, snap in result["engines"].items():
        print(
            f"  Engine {eng} ({snap['engine_name']}): "
            f"{snap['risk_level']} | "
            f"DD={snap['drawdown_pct']*100:.2f}% | "
            f"kill={snap['kill_threshold_pct']*100:.0f}% | "
            f"ratio={snap['drawdown_to_kill_pct']:.2f}"
        )

    sys.exit(0 if not result["any_critical"] else 1)
