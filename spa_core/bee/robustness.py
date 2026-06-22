"""
BEE S9.4 — Robustness Engine.
Параметрическая поверхность: как меняются результаты при вариации ключевых параметров.
LLM_FORBIDDEN: no AI calls. Детерминированный анализ.
PIT-строгость: не использует данные после даты события.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path
import json
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ParameterVariation:
    """Одна точка параметрической поверхности."""
    param_name: str
    param_value: float
    param_relative_change: float  # % от baseline
    metric_name: str
    metric_value: float
    metric_relative_change: float  # % от baseline


@dataclass
class SensitivityReport:
    """Итог анализа чувствительности для одного параметра."""
    param_name: str
    baseline_value: float
    variations: List[ParameterVariation]
    sensitivity_index: float  # d(metric)/d(param) нормированный
    is_critical: bool  # sensitivity_index > 0.5 → критичный параметр
    interpretation: str


ROBUSTNESS_VERSION = "robustness_v1.0"

# Параметры для анализа чувствительности (baseline → проверяемый диапазон)
DEFAULT_SENSITIVITY_PARAMS = {
    "depeg_threshold": {
        "baseline": 0.002,
        "range_pct": [-50, -25, +25, +50, +100],  # % от baseline
        "metric": "gate_trigger_rate",
        "description": "Порог депега для срабатывания гейта",
    },
    "drawdown_kill_pct": {
        "baseline": 0.08,
        "range_pct": [-25, -10, +10, +25, +50],
        "metric": "max_loss_pct",
        "description": "Kill-switch порог drawdown",
    },
    "cash_buffer_min": {
        "baseline": 0.10,
        "range_pct": [-50, -25, +25, +50],
        "metric": "deployment_efficiency",
        "description": "Минимальный cash buffer",
    },
    "min_tvl_usd": {
        "baseline": 100_000_000,
        "range_pct": [-50, +50, +100, +200],
        "metric": "eligible_protocol_count",
        "description": "Минимальный TVL для включения",
    },
}


def _compute_metric_for_param(
    param_name: str,
    param_value: float,
    event_catalog: List[Dict],
    metric_name: str,
) -> float:
    """
    Детерминированно вычисляет метрику при заданном значении параметра.
    LLM_FORBIDDEN. PIT: использует только исторические данные событий.
    """
    # LLM_FORBIDDEN

    if metric_name == "gate_trigger_rate":
        # Сколько событий из каталога триггерит гейт при данном пороге депега
        triggered = 0
        for event in event_catalog:
            peak_depeg = event.get("peak_depeg_pct", 0)
            if peak_depeg >= param_value:
                triggered += 1
        return triggered / len(event_catalog) if event_catalog else 0.0

    elif metric_name == "max_loss_pct":
        # Максимальный убыток до срабатывания kill-switch
        # Линейная аппроксимация: чем больше порог, тем больше убыток
        return param_value  # прямо: kill-switch at X% → max loss X%

    elif metric_name == "deployment_efficiency":
        # Эффективность деплоя: (1 - cash_buffer) = задействованный капитал
        return 1.0 - param_value

    elif metric_name == "eligible_protocol_count":
        # Сколько протоколов проходит TVL фильтр
        # Аппроксимация по известным диапазонам (реальный список не имплементирован)
        if param_value <= 50_000_000:
            return 0.90   # 90% протоколов при min TVL $50M
        elif param_value <= 100_000_000:
            return 0.70   # 70% при $100M
        elif param_value <= 200_000_000:
            return 0.50   # 50% при $200M
        elif param_value <= 500_000_000:
            return 0.30   # 30% при $500M
        else:
            return 0.10   # 10% при >$500M

    return 0.0


def run_sensitivity_analysis(
    param_name: str,
    baseline_value: float,
    range_pct: List[float],
    metric_name: str,
    event_catalog: Optional[List[Dict]] = None,
) -> SensitivityReport:
    """
    Запускает анализ чувствительности для одного параметра.

    Args:
        param_name: имя параметра
        baseline_value: базовое значение
        range_pct: список % отклонений для тестирования
        metric_name: метрика для измерения
        event_catalog: исторические события (PIT)

    Returns:
        SensitivityReport с sensitivity_index и интерпретацией

    LLM_FORBIDDEN. No look-ahead.
    """
    # LLM_FORBIDDEN

    if event_catalog is None:
        catalog_path = _PROJECT_ROOT / "data" / "bee" / "event_catalog.json"
        try:
            event_catalog = json.loads(catalog_path.read_text()).get("events", [])
        except Exception:
            event_catalog = []

    # Baseline метрика
    baseline_metric = _compute_metric_for_param(
        param_name, baseline_value, event_catalog, metric_name
    )

    variations = []
    metric_changes = []

    for pct_change in range_pct:
        varied_value = baseline_value * (1 + pct_change / 100)
        varied_value = max(varied_value, 0.0001)  # не отрицательный

        varied_metric = _compute_metric_for_param(
            param_name, varied_value, event_catalog, metric_name
        )

        metric_change = (
            (varied_metric - baseline_metric) / abs(baseline_metric)
            if baseline_metric != 0 else 0.0
        )

        variations.append(ParameterVariation(
            param_name=param_name,
            param_value=varied_value,
            param_relative_change=pct_change / 100,
            metric_name=metric_name,
            metric_value=varied_metric,
            metric_relative_change=metric_change,
        ))
        metric_changes.append(abs(metric_change))

    # Sensitivity index: avg(|Δmetric/Δparam|) нормированный
    avg_metric_change = sum(metric_changes) / len(metric_changes) if metric_changes else 0.0
    avg_param_change = sum(abs(p) / 100 for p in range_pct) / len(range_pct)

    sensitivity_index = (
        avg_metric_change / avg_param_change
        if avg_param_change > 0 else 0.0
    )
    is_critical = sensitivity_index > 0.5

    # Интерпретация (без обещаний APY)
    if is_critical:
        interpretation = (
            f"CRITICAL: {param_name} is highly sensitive "
            f"(SI={sensitivity_index:.2f}). "
            f"Small changes in {param_name} cause large changes in {metric_name}. "
            f"Requires careful calibration and monitoring."
        )
    else:
        interpretation = (
            f"STABLE: {param_name} sensitivity index={sensitivity_index:.2f}. "
            f"{param_name} changes have moderate impact on {metric_name}."
        )

    return SensitivityReport(
        param_name=param_name,
        baseline_value=baseline_value,
        variations=variations,
        sensitivity_index=sensitivity_index,
        is_critical=is_critical,
        interpretation=interpretation,
    )


def run_full_robustness_analysis(
    output_dir: Optional[Path] = None,
    event_catalog: Optional[List[Dict]] = None,
) -> Dict:
    """
    Полный анализ устойчивости по всем параметрам из DEFAULT_SENSITIVITY_PARAMS.

    Returns dict с:
    - robustness_version
    - run_at
    - params_analyzed
    - critical_params: список критичных
    - stable_params: список стабильных
    - reports: словарь SensitivityReport
    - overall_robustness: "robust" | "moderate" | "fragile"

    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN

    if event_catalog is None:
        catalog_path = _PROJECT_ROOT / "data" / "bee" / "event_catalog.json"
        try:
            event_catalog = json.loads(catalog_path.read_text()).get("events", [])
        except Exception:
            event_catalog = []

    if output_dir is None:
        output_dir = _PROJECT_ROOT / "data" / "bee"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_reports = {}
    critical_params = []
    stable_params = []

    for param_name, cfg in DEFAULT_SENSITIVITY_PARAMS.items():
        report = run_sensitivity_analysis(
            param_name=param_name,
            baseline_value=cfg["baseline"],
            range_pct=cfg["range_pct"],
            metric_name=cfg["metric"],
            event_catalog=event_catalog,
        )
        all_reports[param_name] = report

        if report.is_critical:
            critical_params.append(param_name)
        else:
            stable_params.append(param_name)

        # Per-param JSON (атомарная запись)
        param_json = {
            "param_name": report.param_name,
            "baseline_value": report.baseline_value,
            "sensitivity_index": report.sensitivity_index,
            "is_critical": report.is_critical,
            "interpretation": report.interpretation,
            "variations": [
                {
                    "param_value": v.param_value,
                    "param_relative_change": v.param_relative_change,
                    "metric_name": v.metric_name,
                    "metric_value": v.metric_value,
                    "metric_relative_change": v.metric_relative_change,
                }
                for v in report.variations
            ],
        }
        tmp = output_dir / f"robustness_{param_name}.json.tmp"
        dst = output_dir / f"robustness_{param_name}.json"
        tmp.write_text(json.dumps(param_json, indent=2))
        tmp.replace(dst)

    # Общая оценка устойчивости
    critical_ratio = len(critical_params) / len(DEFAULT_SENSITIVITY_PARAMS)
    if critical_ratio == 0:
        overall = "robust"
    elif critical_ratio <= 0.5:
        overall = "moderate"
    else:
        overall = "fragile"

    summary = {
        "robustness_version": ROBUSTNESS_VERSION,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "params_analyzed": len(all_reports),
        "critical_params": critical_params,
        "stable_params": stable_params,
        "critical_ratio": critical_ratio,
        "overall_robustness": overall,
        "data_source": "event_catalog+deterministic",
        "LLM_FORBIDDEN": True,
        "note": "No APY forecasts. Sensitivity analysis is historical/deterministic only.",
    }
    tmp = output_dir / "robustness_summary.json.tmp"
    dst = output_dir / "robustness_summary.json"
    tmp.write_text(json.dumps(summary, indent=2))
    tmp.replace(dst)

    return {**summary, "reports": all_reports}


if __name__ == "__main__":
    # LLM_FORBIDDEN
    import sys
    result = run_full_robustness_analysis()
    print(f"overall_robustness : {result['overall_robustness']}")
    print(f"critical_params    : {result['critical_params']}")
    print(f"stable_params      : {result['stable_params']}")
    print(f"params_analyzed    : {result['params_analyzed']}")
    sys.exit(0)
