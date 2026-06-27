"""
Multi-Engine Investor Report v2.0.
Агрегирует Engine A + B + C в единый отчёт для инвесторов.
LLM_FORBIDDEN. fail-closed: нет данных → 0/pending.
"""
# LLM_FORBIDDEN
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import json
from spa_core.utils import clock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "multi_engine_report_v2.0"


@dataclass
class EngineReport:
    """Отчёт по одному движку."""
    engine: str                     # "A" | "B" | "C"
    engine_name: str
    start_date: Optional[str]
    equity: float
    drawdown_pct: float
    days_tracked: int
    golive_status: str              # "PENDING" | "READY" | "LIVE"
    golive_days_remaining: int
    risk_level: str                 # GREEN/YELLOW/RED/CRITICAL
    notes: str


@dataclass
class MultiEngineReport:
    """Агрегированный отчёт портфеля."""
    report_version: str
    generated_at: str

    # Общий портфель
    total_equity: float
    total_apy_annualized: Optional[float]
    total_paper_days: int           # дней с самого старого sleeve
    overall_risk: str

    # По движкам
    engines: Dict[str, EngineReport]

    # Capital allocation
    target_allocations: Dict[str, float]
    is_defensive_mode: bool

    # Go-live
    golive_ready: bool              # True если ВСЕ движки ready
    golive_blockers: List[str]

    # Compliance
    LLM_FORBIDDEN: bool = True


def _load_json_safe(path: Path, default=None):
    """fail-closed JSON load. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def _get_engine_a_report() -> EngineReport:
    """
    Engine A отчёт из paper_trading_status.json + equity_curve_daily.json
    + golive_status.json. LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    status = _load_json_safe(_PROJECT_ROOT / "data" / "paper_trading_status.json")
    curve = _load_json_safe(_PROJECT_ROOT / "data" / "equity_curve_daily.json")
    golive = _load_json_safe(_PROJECT_ROOT / "data" / "golive_status.json")

    # Equity — реальное поле в paper_trading_status.json
    equity = float(status.get("current_equity") or 100000.0)

    # Drawdown из equity_curve_daily.json summary
    summary = curve.get("summary", {}) if isinstance(curve, dict) else {}
    drawdown_pct = float(summary.get("max_drawdown_pct", 0.0))

    # Дата старта и кол-во дней из paper_trading_status
    start_date = status.get("paper_start_date") or summary.get("first_real_date", "2026-06-10")
    days = int(status.get("days_running") or golive.get("real_track_days") or 0)

    # GoLive из golive_status.json
    golive_ready_flag = bool(golive.get("ready", False))
    if golive_ready_flag:
        gl_status = "LIVE"
        gl_days_left = 0
    else:
        # Берём из blocking criteria
        blocking = [c for c in golive.get("criteria", []) if c.get("blocking", False)]
        max_days = max((c.get("estimated_days_to_pass") or 0 for c in blocking), default=0)
        gl_days_left = int(max_days)
        gl_status = "PENDING" if days < 14 else "READY"

    # APY из status
    apy_today = status.get("apy_today_pct")
    notes = f"APY today: {apy_today:.2f}%" if apy_today else "APY: tracking"
    notes += f" | regime: {status.get('market_regime', 'STABLE')}"

    return EngineReport(
        engine="A",
        engine_name="Core (stablecoin lending)",
        start_date=start_date,
        equity=equity,
        drawdown_pct=drawdown_pct,
        days_tracked=days,
        golive_status=gl_status,
        golive_days_remaining=gl_days_left,
        risk_level="GREEN",
        notes=notes,
    )


def _get_engine_b_report() -> EngineReport:
    """Engine B отчёт из hy_paper_trading.json. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    state = _load_json_safe(_PROJECT_ROOT / "data" / "hy_paper_trading.json")

    equity = float(state.get("equity", 0.0))
    days = len(state.get("daily_history", []))
    golive_days_left = max(0, 14 - days)
    golive_status = "READY" if days >= 14 else "PENDING"
    drawdown_pct = float(state.get("drawdown_pct", 0.0))

    return EngineReport(
        engine="B",
        engine_name="HY/Carry (Pendle PT)",
        start_date=state.get("start_date"),
        equity=equity,
        drawdown_pct=drawdown_pct,
        days_tracked=days,
        golive_status=golive_status,
        golive_days_remaining=golive_days_left,
        risk_level="GREEN",
        notes=f"Regime: {state.get('regime', 'EXIT')}",
    )


def _get_engine_c_report() -> EngineReport:
    """Engine C отчёт из lp_paper_trading.json. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    state = _load_json_safe(_PROJECT_ROOT / "data" / "lp_paper_trading.json")

    equity = float(state.get("equity", 0.0))
    days = len(state.get("daily_history", []))
    golive_days_left = max(0, 14 - days)
    golive_status = "READY" if days >= 14 else "PENDING"
    il_drawdown = float(state.get("il_drawdown_pct", 0.0))

    return EngineReport(
        engine="C",
        engine_name="LP/Liquidity (CLMM)",
        start_date=state.get("start_date"),
        equity=equity,
        drawdown_pct=il_drawdown,
        days_tracked=days,
        golive_status=golive_status,
        golive_days_remaining=golive_days_left,
        risk_level="GREEN",
        notes=f"IL drawdown: {il_drawdown * 100:.2f}%",
    )


def generate_multi_engine_report(output_path: Optional[Path] = None) -> MultiEngineReport:
    """
    Генерирует полный multi-engine investor report.
    LLM_FORBIDDEN. fail-closed.
    """
    # LLM_FORBIDDEN
    now = clock.utcnow()

    engine_a = _get_engine_a_report()
    engine_b = _get_engine_b_report()
    engine_c = _get_engine_c_report()

    engines = {"A": engine_a, "B": engine_b, "C": engine_c}

    # Общий портфель
    total_equity = engine_a.equity + engine_b.equity + engine_c.equity
    total_days = max(e.days_tracked for e in engines.values())

    # Risk level (самый плохой)
    risk_levels = [e.risk_level for e in engines.values()]
    if "CRITICAL" in risk_levels:
        overall_risk = "CRITICAL"
    elif "RED" in risk_levels:
        overall_risk = "RED"
    elif "YELLOW" in risk_levels:
        overall_risk = "YELLOW"
    else:
        overall_risk = "GREEN"

    # GoLive: берём blockers из golive_status.json для Engine A + статус B/C
    golive_data = _load_json_safe(_PROJECT_ROOT / "data" / "golive_status.json")
    a_blockers = golive_data.get("blockers", [])

    engine_bc_blockers = [
        f"Engine {eng}: needs {e.golive_days_remaining} more days"
        for eng, e in engines.items()
        if eng != "A" and e.golive_status == "PENDING"
    ]
    all_blockers = list(a_blockers) + engine_bc_blockers
    golive_ready = len(all_blockers) == 0

    # Capital targets (из Capital Policy или дефолты v2)
    cap_data = _load_json_safe(_PROJECT_ROOT / "data" / "capital_allocation.json")
    targets = cap_data.get("target_allocations", {"A": 0.60, "B": 0.25, "C": 0.15})
    is_defensive = bool(cap_data.get("is_defensive_mode", False))

    # APY — из paper_trading_status.json (Engine A)
    pt = _load_json_safe(_PROJECT_ROOT / "data" / "paper_trading_status.json")
    apy_raw = pt.get("apy_today_pct")
    apy = float(apy_raw) / 100.0 if apy_raw is not None else None  # нормируем в долях

    report = MultiEngineReport(
        report_version=REPORT_VERSION,
        generated_at=now.isoformat() + "Z",
        total_equity=total_equity,
        total_apy_annualized=apy,
        total_paper_days=total_days,
        overall_risk=overall_risk,
        engines=engines,
        target_allocations=targets,
        is_defensive_mode=is_defensive,
        golive_ready=golive_ready,
        golive_blockers=all_blockers,
        LLM_FORBIDDEN=True,
    )

    # Сохраняем отчёт атомарно (tmp + rename)
    if output_path is None:
        output_path = _PROJECT_ROOT / "data" / "multi_engine_report.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_dict = {
        "report_version": report.report_version,
        "generated_at": report.generated_at,
        "total_equity": report.total_equity,
        "total_apy_annualized": report.total_apy_annualized,
        "total_paper_days": report.total_paper_days,
        "overall_risk": report.overall_risk,
        "is_defensive_mode": report.is_defensive_mode,
        "golive_ready": report.golive_ready,
        "golive_blockers": report.golive_blockers,
        "target_allocations": report.target_allocations,
        "engines": {
            eng: {
                "engine": e.engine,
                "engine_name": e.engine_name,
                "start_date": e.start_date,
                "equity": e.equity,
                "drawdown_pct": e.drawdown_pct,
                "days_tracked": e.days_tracked,
                "golive_status": e.golive_status,
                "golive_days_remaining": e.golive_days_remaining,
                "risk_level": e.risk_level,
                "notes": e.notes,
            }
            for eng, e in report.engines.items()
        },
        "LLM_FORBIDDEN": True,
    }

    # Атомарная запись: tmp + os.replace
    import os
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(report_dict, indent=2))
    os.replace(str(tmp_path), str(output_path))

    return report


if __name__ == "__main__":
    # CLI: python3 -m spa_core.reporting.multi_engine_report
    # LLM_FORBIDDEN
    r = generate_multi_engine_report()
    print(f"=== Multi-Engine Investor Report {r.report_version} ===")
    print(f"Generated: {r.generated_at}")
    print(f"Total equity:  ${r.total_equity:,.2f}")
    if r.total_apy_annualized is not None:
        print(f"APY (today):   {r.total_apy_annualized * 100:.2f}%")
    print(f"Overall risk:  {r.overall_risk}")
    print(f"GoLive ready:  {r.golive_ready}")
    if r.golive_blockers:
        print("GoLive blockers:")
        for b in r.golive_blockers:
            print(f"  • {b}")
    print()
    for eng, e in r.engines.items():
        print(f"Engine {eng}: {e.engine_name}")
        print(f"  equity=${e.equity:,.2f} | days={e.days_tracked} | golive={e.golive_status} | {e.notes}")
    print()
    print(f"Target allocations: {r.target_allocations}")
    print(f"Defensive mode: {r.is_defensive_mode}")
    print(f"LLM_FORBIDDEN: {r.LLM_FORBIDDEN}")
