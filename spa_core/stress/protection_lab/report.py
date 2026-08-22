"""Protection Lab — текстовые отчёты (для владельца и карточек).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from typing import List

from .replay import ProtectionReport


def format_report(report: ProtectionReport) -> str:
    """Развёрнутый отчёт одного сценария."""
    b, p = report.benchmark, report.protected
    lines: List[str] = []
    lines.append(f"═══ {report.scenario_name} ({report.scenario_id}) ═══")
    lines.append(f"Капитал на входе: ${report.capital_usd:,.0f}")
    lines.append("")
    lines.append(f"{'':24}{'ПАССИВНЫЙ':>14}{'ЗАЩИЩЁННЫЙ':>14}")
    lines.append(f"{'Итоговый NAV':24}{b.final_equity:>14,.0f}{p.final_equity:>14,.0f}")
    lines.append(f"{'Минимальный NAV':24}{b.min_equity:>14,.0f}{p.min_equity:>14,.0f}")
    lines.append(f"{'Max drawdown %':24}{b.max_drawdown_pct:>14.2f}{p.max_drawdown_pct:>14.2f}")
    lines.append(f"{'Доход (yield) $':24}{b.yield_earned_usd:>14,.0f}{p.yield_earned_usd:>14,.0f}")
    lines.append(f"{'Обесценения $':24}{b.impairment_usd:>14,.0f}{p.impairment_usd:>14,.0f}")
    lines.append(f"{'Haircut+gas $':24}{b.haircut_usd + b.gas_usd:>14,.0f}"
                 f"{p.haircut_usd + p.gas_usd:>14,.0f}")
    lines.append("")
    sign = "+" if report.capital_saved_usd >= 0 else "−"
    lines.append(f"Capital saved: {sign}${abs(report.capital_saved_usd):,.0f}")
    if report.protection_efficiency_pct is not None:
        lines.append(f"Protection efficiency: {report.protection_efficiency_pct:.1f}%")
    if report.detection_day is not None:
        lines.append(f"Опасность увидена: день {report.detection_day}")
    else:
        lines.append("Опасность увидена: НИКОГДА")
    if report.first_action_day is not None:
        lines.append(f"Первое действие: день {report.first_action_day}")
    if p.actions:
        lines.append("")
        lines.append("Действия защиты:")
        for a in p.actions:
            lines.append(f"  день {a['day']:>2} · {a['kind']:<20} {a['detail']}")
    if p.execution_failures:
        lines.append("")
        lines.append(f"Отказы исполнения ({len(p.execution_failures)}):")
        for f in p.execution_failures[:10]:
            lines.append(f"  день {f['day']:>2} · {f['protocol']}: {f['reason']}")
        if len(p.execution_failures) > 10:
            lines.append(f"  … ещё {len(p.execution_failures) - 10}")
    if report.findings:
        lines.append("")
        lines.append("НАХОДКИ ПО АРХИТЕКТУРЕ:")
        for f in report.findings:
            lines.append(f"  ⚠ {f}")
    if report.assumptions:
        lines.append("")
        lines.append("Допущения маппинга (названы, не спрятаны):")
        for a in report.assumptions:
            lines.append(f"  · {a}")
    return "\n".join(lines) + "\n"


def format_summary_table(reports: List[ProtectionReport]) -> str:
    """Сводная таблица по всем сценариям."""
    lines: List[str] = []
    lines.append("═══ Protection Lab — сводка ═══")
    lines.append(f"{'Сценарий':<38}{'bench DD%':>10}{'prot DD%':>10}"
                 f"{'saved $':>12}{'eff %':>8}{'увидена':>9}")
    survived = 0
    for r in reports:
        det = f"д.{r.detection_day}" if r.detection_day is not None else "нет"
        eff = (f"{r.protection_efficiency_pct:.0f}"
               if r.protection_efficiency_pct is not None else "—")
        lines.append(
            f"{r.scenario_id:<38}{r.benchmark.max_drawdown_pct:>10.2f}"
            f"{r.protected.max_drawdown_pct:>10.2f}{r.capital_saved_usd:>12,.0f}"
            f"{eff:>8}{det:>9}")
        if r.protected.max_drawdown_pct < 10.0:
            survived += 1
    lines.append("")
    lines.append(f"Пережито без HARD-уровня просадки: {survived}/{len(reports)}")
    worst = max(reports, key=lambda r: r.protected.max_drawdown_pct, default=None)
    if worst is not None:
        lines.append(f"Худший для защищённой книги: {worst.scenario_id} "
                     f"(DD {worst.protected.max_drawdown_pct:.2f}%)")
    return "\n".join(lines) + "\n"
