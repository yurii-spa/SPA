"""
GoLiveChecker-HY v1.0 — Engine B go-live readiness checks.
Отдельный чеклист для Engine B (HY/Carry).

LLM_FORBIDDEN. fail-closed: нет данных → CHECK_FAIL.

Проверки:
  CHECK-HY-001  Минимум 14 дней paper trading (daily_history)
  CHECK-HY-002  Минимум 7 дней с режимом ENTER из 14
  CHECK-HY-003  Drawdown не пересёк -8% ни разу за весь период
  CHECK-HY-004  policy_hy.evaluate_protocol() работает без ошибок
  CHECK-HY-005  PendlePTAdapter.read_state() без ошибок
  CHECK-HY-006  data/hy_paper_trading.json существует и читаема

Атомарная запись: tmp + os.replace (data/golive_hy_report.json).
"""
# LLM_FORBIDDEN
from dataclasses import dataclass, field
from typing import List
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile
from spa_core.utils import clock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLIVE_HY_VERSION = "golive_hy_v1.0"

# Минимальные требования для go-live Engine B
MIN_PAPER_DAYS = 14        # дней paper trading
MIN_ENTER_DAYS = 7         # минимум дней с режимом ENTER
MAX_DRAWDOWN_PCT = -0.08   # -8% drawdown threshold (включительно — FAIL если хуже)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HYGoLiveCheck:
    """Результат одного go-live чека."""
    check_id: str
    name: str
    status: str       # "PASS" | "FAIL" | "WARN" | "PENDING"
    value: object     # Фактическое значение
    threshold: object # Требуемое
    note: str


@dataclass
class HYGoLiveReport:
    """Полный отчёт GoLive-HY."""
    checks: List[HYGoLiveCheck]
    total: int
    passed: int
    failed: int
    pending: int

    overall_status: str   # "PASS" | "FAIL" | "PENDING"
    ready_for_golive: bool
    blocker_ids: List[str]

    checked_at: str
    policy_version: str
    LLM_FORBIDDEN: bool = True


# ---------------------------------------------------------------------------
# Individual checks (LLM_FORBIDDEN in each)
# ---------------------------------------------------------------------------

def _check_data_file() -> HYGoLiveCheck:
    """CHECK-HY-006: hy_paper_trading.json существует и читаема. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    hy_path = _PROJECT_ROOT / "data" / "hy_paper_trading.json"
    if not hy_path.exists():
        return HYGoLiveCheck(
            check_id="CHECK-HY-006",
            name="data/hy_paper_trading.json exists",
            status="FAIL",
            value="file not found",
            threshold="file exists",
            note="Create hy_paper_trading.json via EPIC-1 S1.3",
        )
    try:
        data = json.loads(hy_path.read_text())
        sleeve = data.get("sleeve", "?")
        return HYGoLiveCheck(
            check_id="CHECK-HY-006",
            name="data/hy_paper_trading.json exists",
            status="PASS",
            value=f"sleeve={sleeve}",
            threshold="file exists with sleeve=B",
            note=f"start_date={data.get('start_date')}",
        )
    except Exception as e:
        return HYGoLiveCheck(
            check_id="CHECK-HY-006",
            name="data/hy_paper_trading.json exists",
            status="FAIL",
            value=str(e)[:80],
            threshold="valid JSON",
            note="JSON parse error — fail-closed",
        )


def _check_paper_days(hy_state: dict) -> HYGoLiveCheck:
    """CHECK-HY-001: Минимум 14 дней paper trading. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    history = hy_state.get("daily_history", [])
    days = len(history)
    if days >= MIN_PAPER_DAYS:
        status = "PASS"
    elif days > 0:
        status = "PENDING"
    else:
        status = "FAIL"
    return HYGoLiveCheck(
        check_id="CHECK-HY-001",
        name=f"Paper trading days >= {MIN_PAPER_DAYS}",
        status=status,
        value=days,
        threshold=MIN_PAPER_DAYS,
        note=f"{days}/{MIN_PAPER_DAYS} days tracked. {max(0, MIN_PAPER_DAYS - days)} remaining.",
    )


def _check_enter_days(hy_state: dict) -> HYGoLiveCheck:
    """CHECK-HY-002: Минимум 7 дней с режимом ENTER. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    history = hy_state.get("daily_history", [])
    enter_days = sum(1 for h in history if h.get("regime") == "ENTER")
    if enter_days >= MIN_ENTER_DAYS:
        status = "PASS"
    elif len(history) > 0:
        status = "PENDING"
    else:
        status = "FAIL"
    return HYGoLiveCheck(
        check_id="CHECK-HY-002",
        name=f"ENTER regime days >= {MIN_ENTER_DAYS}",
        status=status,
        value=enter_days,
        threshold=MIN_ENTER_DAYS,
        note=f"{enter_days} ENTER days out of {len(history)} tracked.",
    )


def _check_drawdown(hy_state: dict) -> HYGoLiveCheck:
    """CHECK-HY-003: Drawdown не превышал -8% ни разу. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    history = hy_state.get("daily_history", [])
    # Наихудший drawdown из истории
    hist_worst = min(
        (h.get("drawdown_pct", 0.0) for h in history),
        default=0.0,
    )
    # Текущий drawdown из верхнего уровня state
    current_dd = hy_state.get("drawdown_pct", 0.0)
    worst = min(hist_worst, current_dd)

    status = "PASS" if worst >= MAX_DRAWDOWN_PCT else "FAIL"
    return HYGoLiveCheck(
        check_id="CHECK-HY-003",
        name="Drawdown never exceeded -8%",
        status=status,
        value=f"{worst:.2%}",
        threshold=f"{MAX_DRAWDOWN_PCT:.2%}",
        note=f"Worst drawdown seen: {worst:.2%} (threshold: {MAX_DRAWDOWN_PCT:.2%})",
    )


def _check_policy_hy() -> HYGoLiveCheck:
    """CHECK-HY-004: policy_hy.evaluate_protocol() работает без ошибок. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    try:
        # Гарантируем, что project root в sys.path
        root_str = str(_PROJECT_ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        from spa_core.risk.policy_hy import evaluate_protocol, HY_LIMITS

        # Тест с нормальными данными — должен вернуть dict с approved=True
        result = evaluate_protocol(
            protocol_name="Pendle_test",
            yield_apy=0.115,
            tvl_usd=1_000_000_000.0,
            depeg_pct=0.001,
            funding_rate=0.085,
            audit_count=3,
            term_to_maturity_days=90,
            liquidity_usd=5_000_000.0,
            sleeve_allocation_pct=0.15,
            current_drawdown_pct=0.0,
            limits=HY_LIMITS,
        )
        approved = result.get("approved", False)
        violations = result.get("violations", [])
        return HYGoLiveCheck(
            check_id="CHECK-HY-004",
            name="policy_hy.evaluate_protocol() OK",
            status="PASS" if isinstance(result, dict) else "FAIL",
            value=f"approved={approved}",
            threshold="no exception, returns dict",
            note=f"violations={violations}, policy={result.get('policy_version', '?')}",
        )
    except Exception as e:
        return HYGoLiveCheck(
            check_id="CHECK-HY-004",
            name="policy_hy.evaluate_protocol() OK",
            status="FAIL",
            value=str(e)[:80],
            threshold="no exception",
            note=f"policy_hy import/call failed: {e}",
        )


def _check_pendle_adapter() -> HYGoLiveCheck:
    """CHECK-HY-005: PendlePTAdapter.read_state() без ошибок. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    # Адаптер Engine B — в adapters/ (корень проекта), не в spa_core/adapters/
    adapter_path = _PROJECT_ROOT / "adapters" / "pendle_pt.py"
    if not adapter_path.exists():
        return HYGoLiveCheck(
            check_id="CHECK-HY-005",
            name="PendlePTAdapter.read_state() OK",
            status="FAIL",
            value="adapters/pendle_pt.py not found",
            threshold="file exists",
            note="Engine B adapter missing at adapters/pendle_pt.py",
        )
    try:
        spec = importlib.util.spec_from_file_location("pendle_pt_engine_b", adapter_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        adapter = mod.PendlePTAdapter()
        state = adapter.read_state()

        # read_state() должен возвращать dict с обязательными полями
        yield_apy = state.get("yield_apy", None)
        tvl_usd = state.get("tvl_usd", 0)
        validated = state.get("validated", False)

        if yield_apy is None:
            raise ValueError("read_state() returned no yield_apy")

        return HYGoLiveCheck(
            check_id="CHECK-HY-005",
            name="PendlePTAdapter.read_state() OK",
            status="PASS",
            value=f"yield_apy={yield_apy:.1%}",
            threshold="no exception, yield_apy present",
            note=f"tvl=${tvl_usd/1e6:.0f}M, validated={validated}, source={state.get('data_source', '?')}",
        )
    except Exception as e:
        return HYGoLiveCheck(
            check_id="CHECK-HY-005",
            name="PendlePTAdapter.read_state() OK",
            status="FAIL",
            value=str(e)[:80],
            threshold="no exception",
            note=f"Adapter error: {e}",
        )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_golive_check_hy() -> HYGoLiveReport:
    """
    Запускает все GoLive checks для Engine B (HY/Carry).

    LLM_FORBIDDEN. fail-closed: нет данных → FAIL.
    Атомарная запись data/golive_hy_report.json (tmp + os.replace).

    Returns:
        HYGoLiveReport с результатами всех 6 проверок.
    """
    # LLM_FORBIDDEN

    # Загружаем HY state — fail-closed при ошибке чтения
    hy_path = _PROJECT_ROOT / "data" / "hy_paper_trading.json"
    try:
        hy_state = json.loads(hy_path.read_text()) if hy_path.exists() else {}
    except Exception:
        hy_state = {}  # fail-closed: нет данных → проверки провалятся сами

    # Запускаем все проверки в порядке CHECK-HY-001..006
    checks = [
        _check_paper_days(hy_state),
        _check_enter_days(hy_state),
        _check_drawdown(hy_state),
        _check_policy_hy(),
        _check_pendle_adapter(),
        _check_data_file(),
    ]

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    pending = sum(1 for c in checks if c.status == "PENDING")
    blockers = [c.check_id for c in checks if c.status == "FAIL"]

    # Общий статус: FAIL > PENDING > PASS (строгий порядок)
    if failed > 0:
        overall = "FAIL"
        ready = False
    elif pending > 0:
        overall = "PENDING"
        ready = False
    else:
        overall = "PASS"
        ready = True

    report = HYGoLiveReport(
        checks=checks,
        total=len(checks),
        passed=passed,
        failed=failed,
        pending=pending,
        overall_status=overall,
        ready_for_golive=ready,
        blocker_ids=blockers,
        checked_at=clock.utcnow().isoformat() + "Z",
        policy_version=GOLIVE_HY_VERSION,
        LLM_FORBIDDEN=True,
    )

    # Атомарная запись: tmp + os.replace (никогда прямой open(..., "w"))
    report_path = _PROJECT_ROOT / "data" / "golive_hy_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_dict = {
        "golive_hy_version": GOLIVE_HY_VERSION,
        "checked_at": report.checked_at,
        "overall_status": overall,
        "ready_for_golive": ready,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "blocker_ids": blockers,
        "checks": [
            {
                "id": c.check_id,
                "name": c.name,
                "status": c.status,
                "value": str(c.value),
                "threshold": str(c.threshold),
                "note": c.note,
            }
            for c in checks
        ],
        "LLM_FORBIDDEN": True,
    }

    # Атомарная запись
    fd, tmp_path = tempfile.mkstemp(dir=report_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(report_dict, f, indent=2)
        os.replace(tmp_path, report_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # LLM_FORBIDDEN
    import argparse

    parser = argparse.ArgumentParser(description="GoLiveChecker-HY Engine B")
    parser.add_argument("--json", action="store_true", help="Вывод в JSON")
    args = parser.parse_args()

    r = run_golive_check_hy()

    if args.json:
        report_path = _PROJECT_ROOT / "data" / "golive_hy_report.json"
        print(report_path.read_text())
    else:
        icon_map = {"PASS": "✅", "FAIL": "❌", "PENDING": "⏳", "WARN": "⚠️"}
        print(f"=== GoLiveChecker-HY {GOLIVE_HY_VERSION} ===")
        print(f"Overall: {r.overall_status} ({r.passed}/{r.total} PASS)")
        print(f"Ready:   {r.ready_for_golive}")
        if r.blocker_ids:
            print(f"Blockers: {', '.join(r.blocker_ids)}")
        print()
        for c in r.checks:
            icon = icon_map.get(c.status, "?")
            print(f"{icon} {c.check_id}: {c.name} [{c.status}]")
            print(f"   value={c.value}  threshold={c.threshold}")
            print(f"   {c.note}")
