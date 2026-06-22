"""
BEE S9.5 — Failure Boundary Analysis.
Находит пограничные условия при которых политика даёт сбой.
LLM_FORBIDDEN: детерминированный поиск, без AI.
No APY promises в выводах.
PIT-строгость: только переданные параметры.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path
import json
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

FAILURE_BOUNDARY_VERSION = "failure_boundary_v1.0"


@dataclass
class StressScenario:
    """Синтетический стрессовый сценарий."""
    scenario_id: str
    label: str
    description: str
    # Параметры сценария
    depeg_pct: float          # пиковый депег
    duration_days: int        # длительность стресса
    tvl_drop_pct: float       # падение TVL (0-1)
    funding_rate_drop: float  # снижение фандинга (абсолютное)
    max_drawdown_pct: float   # ожидаемый drawdown при этом сценарии


@dataclass
class ScenarioResult:
    """Результат одного стрессового сценария."""
    scenario_id: str
    label: str
    outcome: str                   # "survived" | "failed" | "alarm"
    gate_triggered: bool
    drawdown_pct: float
    recovery_possible: bool
    breach_type: Optional[str]     # что именно нарушилось
    policy_response: str           # как отреагировала политика
    no_apy_disclaimer: str         # обязательный дисклеймер


# Синтетические сценарии (от лёгкого к критическому)
SYNTHETIC_SCENARIOS: List[StressScenario] = [
    StressScenario(
        scenario_id="S1_MILD_DEPEG",
        label="Mild Depeg",
        description="Small stablecoin depeg (0.5%), short duration",
        depeg_pct=0.005, duration_days=1, tvl_drop_pct=0.05,
        funding_rate_drop=0.01, max_drawdown_pct=0.005,
    ),
    StressScenario(
        scenario_id="S2_MODERATE_DEPEG",
        label="Moderate Depeg",
        description="1% depeg, 2 days, moderate TVL drop",
        depeg_pct=0.01, duration_days=2, tvl_drop_pct=0.15,
        funding_rate_drop=0.02, max_drawdown_pct=0.015,
    ),
    StressScenario(
        scenario_id="S3_SEVERE_DEPEG",
        label="Severe Depeg",
        description="2% depeg, 3 days (similar to USDC SVB 2023)",
        depeg_pct=0.02, duration_days=3, tvl_drop_pct=0.25,
        funding_rate_drop=0.04, max_drawdown_pct=0.030,
    ),
    StressScenario(
        scenario_id="S4_CRITICAL_DEPEG",
        label="Critical Depeg",
        description="5% depeg, 7 days, high TVL flight",
        depeg_pct=0.05, duration_days=7, tvl_drop_pct=0.50,
        funding_rate_drop=0.06, max_drawdown_pct=0.065,
    ),
    StressScenario(
        scenario_id="S5_CATASTROPHIC",
        label="Catastrophic (UST-like)",
        description="Full depeg event, protocol collapse (UST/Luna 2022 style)",
        depeg_pct=0.30, duration_days=5, tvl_drop_pct=0.90,
        funding_rate_drop=0.10, max_drawdown_pct=0.30,
    ),
    StressScenario(
        scenario_id="S6_FUNDING_COLLAPSE",
        label="Funding Rate Collapse",
        description="Funding rate goes to 0%, no depeg issue",
        depeg_pct=0.001, duration_days=14, tvl_drop_pct=0.10,
        funding_rate_drop=0.12, max_drawdown_pct=0.02,
    ),
    StressScenario(
        scenario_id="S7_LIQUIDITY_CRUNCH",
        label="Liquidity Crunch",
        description="TVL crashes 70%, liquidation cascade",
        depeg_pct=0.008, duration_days=5, tvl_drop_pct=0.70,
        funding_rate_drop=0.03, max_drawdown_pct=0.045,
    ),
    StressScenario(
        scenario_id="S8_SLOW_BLEED",
        label="Slow Bleed",
        description="Gradual 30-day drawdown, no single trigger",
        depeg_pct=0.003, duration_days=30, tvl_drop_pct=0.20,
        funding_rate_drop=0.02, max_drawdown_pct=0.075,
    ),
]


def evaluate_scenario(
    scenario: StressScenario,
    policy_config: Optional[Dict] = None,
) -> ScenarioResult:
    """
    Оценивает один синтетический сценарий против текущей политики.

    Logic (детерминированная, LLM_FORBIDDEN):
    1. Проверяем gate triggers (depeg, funding, TVL)
    2. Если gate triggered → survived (уходим в кэш до нормализации)
    3. Если gate НЕ triggered → drawdown реализуется
    4. Если drawdown >= kill_pct → failed
    5. Если drawdown < kill_pct → survived с alarm

    LLM_FORBIDDEN. No look-ahead. No APY promises.
    """
    # LLM_FORBIDDEN

    if policy_config is None:
        policy_config = {
            "depeg_exit_threshold": 0.006,   # 0.6% — EXIT порог
            "drawdown_kill_pct": 0.08,        # 8% kill switch
            "funding_rate_exit": 0.02,        # 2% exit threshold
            "min_tvl_usd": 100_000_000,
            "tvl_at_entry": 850_000_000,      # baseline TVL
            "cash_buffer": 0.10,              # 10% уже в кэше
        }

    depeg_threshold = policy_config.get("depeg_exit_threshold", 0.006)
    kill_pct = policy_config.get("drawdown_kill_pct", 0.08)
    fr_exit = policy_config.get("funding_rate_exit", 0.02)
    tvl_at_entry = policy_config.get("tvl_at_entry", 850_000_000)
    min_tvl = policy_config.get("min_tvl_usd", 100_000_000)
    cash_buffer = policy_config.get("cash_buffer", 0.10)

    # Проверяем triggers
    gate_depeg = scenario.depeg_pct >= depeg_threshold

    # Funding gate: если stressed funding ниже порога выхода
    baseline_funding = 0.085  # текущий funding rate baseline
    stressed_funding = baseline_funding - scenario.funding_rate_drop
    gate_funding = stressed_funding <= fr_exit

    stressed_tvl = tvl_at_entry * (1.0 - scenario.tvl_drop_pct)
    gate_tvl = stressed_tvl < min_tvl

    gate_triggered = gate_depeg or gate_funding or gate_tvl

    # Какой именно breach?
    breaches = []
    if gate_depeg:
        breaches.append(
            f"depeg {scenario.depeg_pct*100:.2f}% >= threshold {depeg_threshold*100:.2f}%"
        )
    if gate_funding:
        breaches.append(
            f"funding {stressed_funding*100:.2f}% <= exit {fr_exit*100:.2f}%"
        )
    if gate_tvl:
        breaches.append(
            f"TVL ${stressed_tvl/1e6:.0f}M < min ${min_tvl/1e6:.0f}M"
        )
    breach_type = "; ".join(breaches) if breaches else None

    # Если gate triggered: уходим в кэш, максимальный убыток = (1 - cash_buffer) * depeg
    if gate_triggered:
        # Deployed capital takes the hit, but we exit early
        # Cash buffer уже выведен, остальное (1-buffer) теряет depeg_pct
        actual_drawdown = (1.0 - cash_buffer) * scenario.depeg_pct

        if actual_drawdown >= kill_pct:
            # Даже с гейтом — слишком поздно
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                label=scenario.label,
                outcome="failed",
                gate_triggered=True,
                drawdown_pct=actual_drawdown,
                recovery_possible=False,
                breach_type=breach_type,
                policy_response=(
                    f"Gate triggered but exit too slow. "
                    f"Actual drawdown {actual_drawdown*100:.2f}% >= kill {kill_pct*100:.0f}%."
                ),
                no_apy_disclaimer=(
                    "Historical stress test only. Past protection does not imply future protection."
                ),
            )
        else:
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                label=scenario.label,
                outcome="survived",
                gate_triggered=True,
                drawdown_pct=actual_drawdown,
                recovery_possible=True,
                breach_type=breach_type,
                policy_response=(
                    f"Gate triggered on: {breach_type}. "
                    f"Exited to cash. Drawdown limited to {actual_drawdown*100:.2f}%."
                ),
                no_apy_disclaimer=(
                    "Historical stress test only. Past protection does not imply future protection."
                ),
            )
    else:
        # Gate NOT triggered: scenario plays out fully
        actual_drawdown = scenario.max_drawdown_pct

        if actual_drawdown >= kill_pct:
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                label=scenario.label,
                outcome="failed",
                gate_triggered=False,
                drawdown_pct=actual_drawdown,
                recovery_possible=False,
                breach_type=(
                    f"drawdown {actual_drawdown*100:.1f}% >= kill {kill_pct*100:.0f}%"
                ),
                policy_response=(
                    f"Gate NOT triggered "
                    f"(depeg {scenario.depeg_pct*100:.2f}% < threshold {depeg_threshold*100:.2f}%). "
                    f"Kill-switch at {kill_pct*100:.0f}% would activate."
                ),
                no_apy_disclaimer=(
                    "Historical stress test only. Past protection does not imply future protection."
                ),
            )
        else:
            # Alarm если drawdown >= 50% от kill-порога
            alarm = actual_drawdown >= kill_pct * 0.5
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                label=scenario.label,
                outcome="alarm" if alarm else "survived",
                gate_triggered=False,
                drawdown_pct=actual_drawdown,
                recovery_possible=True,
                breach_type=None,
                policy_response=(
                    f"Gate not triggered. Drawdown {actual_drawdown*100:.2f}% within limits. "
                    f"{'ALARM: approaching kill level.' if alarm else 'Within normal range.'}"
                ),
                no_apy_disclaimer=(
                    "Historical stress test only. Past protection does not imply future protection."
                ),
            )


def find_failure_boundary(
    param_name: str = "depeg_pct",
    lo: float = 0.001,
    hi: float = 0.5,
    tolerance: float = 0.0001,
    policy_config: Optional[Dict] = None,
    max_iter: int = 30,
) -> Dict:
    """
    Бинарный поиск по параметру — находит порог отказа (failure boundary).

    Для `param_name="depeg_pct"`:
    - Ищет минимальный depeg при котором система FAILED
    - Возвращает boundary_value

    LLM_FORBIDDEN. Детерминированный бинарный поиск.
    """
    # LLM_FORBIDDEN

    def make_scenario(value: float) -> StressScenario:
        """Создаёт тестовый сценарий с одним варьируемым параметром."""
        base = StressScenario(
            scenario_id="BOUNDARY_TEST",
            label=f"Boundary test {param_name}={value:.4f}",
            description=f"Binary search boundary: {param_name}={value:.4f}",
            depeg_pct=0.001,
            duration_days=3,
            tvl_drop_pct=0.20,
            funding_rate_drop=0.03,
            max_drawdown_pct=0.02,
        )
        setattr(base, param_name, value)
        # Если depeg растёт → drawdown тоже растёт пропорционально
        if param_name == "depeg_pct":
            base.max_drawdown_pct = value * 0.9  # 90% от depeg реализуется как drawdown
        # max_drawdown_pct используется напрямую при param_name == "max_drawdown_pct"
        return base

    iterations = []
    boundary_found = False

    # Проверяем что lo=survived, hi=failed
    lo_result = evaluate_scenario(make_scenario(lo), policy_config)
    hi_result = evaluate_scenario(make_scenario(hi), policy_config)

    if lo_result.outcome == "failed":
        return {
            "param_name": param_name,
            "boundary_value": lo,
            "status": "boundary_below_lo",
            "note": f"Even {param_name}={lo:.4f} causes failure",
            "LLM_FORBIDDEN": True,
        }

    if hi_result.outcome != "failed":
        return {
            "param_name": param_name,
            "boundary_value": hi,
            "status": "no_failure_in_range",
            "note": f"No failure even at {param_name}={hi:.4f}",
            "LLM_FORBIDDEN": True,
        }

    # Бинарный поиск
    for i in range(max_iter):
        mid = (lo + hi) / 2.0
        mid_result = evaluate_scenario(make_scenario(mid), policy_config)
        iterations.append({"iter": i, "mid": round(mid, 6), "outcome": mid_result.outcome})

        if mid_result.outcome == "failed":
            hi = mid
        else:
            lo = mid

        if hi - lo < tolerance:
            boundary_found = True
            break

    boundary_value = (lo + hi) / 2.0

    return {
        "param_name": param_name,
        "boundary_value": boundary_value,
        "status": "found" if boundary_found else "converging",
        "lo": lo,
        "hi": hi,
        "tolerance": tolerance,
        "iterations": len(iterations),
        "note": (
            f"System fails at {param_name} >= {boundary_value:.4f}. "
            f"Historical stress analysis only. No future protection implied."
        ),
        "LLM_FORBIDDEN": True,
    }


def run_full_failure_analysis(
    output_dir: Optional[Path] = None,
    policy_config: Optional[Dict] = None,
) -> Dict:
    """
    Полный анализ отказов:
    1. Все синтетические сценарии (S1-S8)
    2. Поиск failure boundary по depeg_pct

    LLM_FORBIDDEN. No APY promises.
    """
    # LLM_FORBIDDEN

    if output_dir is None:
        output_dir = _PROJECT_ROOT / "data" / "bee"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Прогоняем все сценарии
    scenario_results: List[ScenarioResult] = []
    survived: List[str] = []
    alarmed: List[str] = []
    failed: List[str] = []

    for scenario in SYNTHETIC_SCENARIOS:
        result = evaluate_scenario(scenario, policy_config)
        scenario_results.append(result)

        if result.outcome == "survived":
            survived.append(scenario.scenario_id)
        elif result.outcome == "alarm":
            alarmed.append(scenario.scenario_id)
        else:
            failed.append(scenario.scenario_id)

    # Failure boundary по depeg
    depeg_boundary = find_failure_boundary(
        param_name="depeg_pct",
        lo=0.001,
        hi=0.5,
        policy_config=policy_config,
    )

    # Максимальный survived drawdown
    max_survived_dd = max(
        (r.drawdown_pct for r in scenario_results if r.outcome in ["survived", "alarm"]),
        default=0.0,
    )

    summary = {
        "failure_boundary_version": FAILURE_BOUNDARY_VERSION,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "total_scenarios": len(SYNTHETIC_SCENARIOS),
        "survived": survived,
        "alarmed": alarmed,
        "failed": failed,
        "survival_rate": len(survived) / len(SYNTHETIC_SCENARIOS),
        "depeg_failure_boundary": depeg_boundary,
        "max_survived_drawdown": max_survived_dd,
        "scenarios": [
            {
                "scenario_id": r.scenario_id,
                "label": r.label,
                "outcome": r.outcome,
                "gate_triggered": r.gate_triggered,
                "drawdown_pct": r.drawdown_pct,
                "recovery_possible": r.recovery_possible,
                "breach_type": r.breach_type,
                "policy_response": r.policy_response,
                "no_apy_disclaimer": r.no_apy_disclaimer,
            }
            for r in scenario_results
        ],
        "LLM_FORBIDDEN": True,
        "note": (
            "Synthetic stress scenarios. Historical stress analysis. No APY promises."
        ),
    }

    out_path = output_dir / "failure_boundary.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(summary, indent=2))
    tmp_path.replace(out_path)  # атомарная запись

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--run" in args:
        result = run_full_failure_analysis()
        print(f"failure_boundary v{FAILURE_BOUNDARY_VERSION}")
        print(f"Total scenarios : {result['total_scenarios']}")
        print(f"Survived        : {result['survived']}")
        print(f"Alarmed         : {result['alarmed']}")
        print(f"Failed          : {result['failed']}")
        print(f"Survival rate   : {result['survival_rate']*100:.0f}%")
        b = result.get("depeg_failure_boundary", {})
        print(f"Depeg boundary  : {b.get('boundary_value', '?'):.4f} ({b.get('status')})")
        print(f"LLM_FORBIDDEN   : {result['LLM_FORBIDDEN']}")
        print("Output          : data/bee/failure_boundary.json")
    else:
        # --check (default): вычислить без записи
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = run_full_failure_analysis(output_dir=Path(tmp))
        print(f"failure_boundary v{FAILURE_BOUNDARY_VERSION} [check only, no write]")
        print(f"Total scenarios : {result['total_scenarios']}")
        print(f"Survived        : {result['survived']}")
        print(f"Alarmed         : {result['alarmed']}")
        print(f"Failed          : {result['failed']}")
        print(f"Survival rate   : {result['survival_rate']*100:.0f}%")
        b = result.get("depeg_failure_boundary", {})
        print(f"Depeg boundary  : {b.get('boundary_value', '?'):.4f} ({b.get('status')})")
        print(f"LLM_FORBIDDEN   : {result['LLM_FORBIDDEN']}")
