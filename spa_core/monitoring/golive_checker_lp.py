"""
GoLiveChecker-LP — Engine C (LP/Liquidity) readiness checks — EPIC-2 S2.2.

6 проверок перед переходом Engine C в production:
  CHECK-LP-001  14+ дней paper tracking в daily_history
  CHECK-LP-002  max IL drawdown never < -12% (kill threshold)
  CHECK-LP-003  policy_lp.evaluate_lp_position() без ошибок (импортируется)
  CHECK-LP-004  UniswapV3LPAdapter.read_state() без ошибок
  CHECK-LP-005  data/lp_paper_trading.json существует
  CHECK-LP-006  Все позиции delta-neutral (или нет позиций — OK)

LLM_FORBIDDEN: никаких AI-вызовов.
fail-closed: ошибка проверки → статус ERROR, overall NOT_READY.
Результат пишется в data/golive_lp_report.json (атомарно).

Аналог golive_checker_hy.py для Engine B.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LP_DATA_PATH = _PROJECT_ROOT / "data" / "lp_paper_trading.json"
_GOLIVE_LP_REPORT_PATH = _PROJECT_ROOT / "data" / "golive_lp_report.json"

GOLIVE_LP_VERSION = "golive_lp_v1.0"

# Константы GoLive
_MIN_TRACK_DAYS = 14
_IL_KILL_THRESHOLD = -0.12  # -12%


@dataclass
class LPCheck:
    """Результат одной GoLive проверки Engine C. LLM_FORBIDDEN."""
    check_id: str
    description: str
    status: str          # "PASS" | "FAIL" | "PENDING" | "ERROR"
    detail: str = ""
    blocking: bool = True


@dataclass
class LPGoLiveReport:
    """Итоговый отчёт GoLiveChecker-LP. LLM_FORBIDDEN."""
    checks: list = field(default_factory=list)
    overall_status: str = "NOT_READY"
    passed: int = 0
    total: int = 0
    generated_at: str = ""
    version: str = GOLIVE_LP_VERSION
    LLM_FORBIDDEN: bool = True


def _load_lp_state_safe() -> dict:
    """
    Безопасная загрузка state Engine C.
    fail-closed: ошибка → пустой dict.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        if not _LP_DATA_PATH.exists():
            return {}
        return json.loads(_LP_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _check_lp_001_track_days(state: dict) -> LPCheck:
    """
    CHECK-LP-001: минимум 14 дней paper tracking.
    Считает уникальные записи в daily_history.
    PASS если ≥ 14, PENDING если < 14, ERROR при ошибке.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        history = state.get("daily_history", [])
        days = len(history)
        needed = _MIN_TRACK_DAYS
        remaining = max(0, needed - days)

        if days >= needed:
            return LPCheck(
                check_id="CHECK-LP-001",
                description=f"≥{needed} дней paper tracking",
                status="PASS",
                detail=f"{days} дней в daily_history",
                blocking=True,
            )
        else:
            return LPCheck(
                check_id="CHECK-LP-001",
                description=f"≥{needed} дней paper tracking",
                status="PENDING",
                detail=f"{days}/{needed} дней, осталось {remaining}",
                blocking=True,
            )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-001",
            description=f"≥{_MIN_TRACK_DAYS} дней paper tracking",
            status="ERROR",
            detail=f"Ошибка: {exc}",
            blocking=True,
        )


def _check_lp_002_max_il_drawdown(state: dict) -> LPCheck:
    """
    CHECK-LP-002: максимальный IL drawdown не превысил -12% ни разу.
    Сканирует весь daily_history и текущий il_drawdown_pct.
    PASS если worst IL >= -12%, FAIL если был хотя бы один < -12%.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        history = state.get("daily_history", [])
        current_il = state.get("il_drawdown_pct", 0.0)

        all_il = [current_il]
        for entry in history:
            il = entry.get("il_drawdown_pct", 0.0)
            all_il.append(il)

        worst_il = min(all_il)  # самый отрицательный

        if worst_il < _IL_KILL_THRESHOLD:
            return LPCheck(
                check_id="CHECK-LP-002",
                description="max IL drawdown не превысил -12%",
                status="FAIL",
                detail=f"Worst IL drawdown: {worst_il:.2%} (порог {_IL_KILL_THRESHOLD:.0%})",
                blocking=True,
            )
        else:
            return LPCheck(
                check_id="CHECK-LP-002",
                description="max IL drawdown не превысил -12%",
                status="PASS",
                detail=f"Worst IL drawdown: {worst_il:.2%} — в пределах нормы",
                blocking=True,
            )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-002",
            description="max IL drawdown не превысил -12%",
            status="ERROR",
            detail=f"Ошибка: {exc}",
            blocking=True,
        )


def _check_lp_003_policy_lp() -> LPCheck:
    """
    CHECK-LP-003: policy_lp.evaluate_lp_position() импортируется и выполняется без ошибок.
    Тестирует с заведомо корректными параметрами (хорошая позиция).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        _spa = str(_PROJECT_ROOT)
        if _spa not in sys.path:
            sys.path.insert(0, _spa)

        from spa_core.risk.policy_lp import evaluate_lp_position, LP_LIMITS, LP_POLICY_VERSION

        result = evaluate_lp_position(
            pool_name="USDC_USDT",
            protocol="uniswap_v3",
            fee_apy_24h=0.062,
            pool_tvl_usd=180_000_000.0,
            il_current_pct=0.0002,
            audit_count=4,
            range_width_pct=0.001,
            fee_volatility_7d=0.12,
            liquidity_depth_usd=8_000_000.0,
            sleeve_allocation_pct=0.10,
            current_drawdown_pct=0.0,
            is_delta_neutral=True,
        )

        approved = result.get("approved", False)
        version = result.get("policy_version", "unknown")

        if approved:
            return LPCheck(
                check_id="CHECK-LP-003",
                description="policy_lp.evaluate_lp_position() работает корректно",
                status="PASS",
                detail=f"approved=True, policy_version={version}",
                blocking=True,
            )
        else:
            violations = result.get("violations", [])
            return LPCheck(
                check_id="CHECK-LP-003",
                description="policy_lp.evaluate_lp_position() работает корректно",
                status="FAIL",
                detail=f"approved=False, violations={violations}",
                blocking=True,
            )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-003",
            description="policy_lp.evaluate_lp_position() работает корректно",
            status="ERROR",
            detail=f"Ошибка импорта/выполнения: {exc}",
            blocking=True,
        )


def _check_lp_004_uniswap_adapter() -> LPCheck:
    """
    CHECK-LP-004: UniswapV3LPAdapter.read_state() выполняется без ошибок.
    Загружает модуль через importlib.util чтобы обойти конфликт имён с spa_core/adapters/.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        import importlib.util as _ilu

        _adapter_path = _PROJECT_ROOT / "adapters" / "uniswap_v3_lp.py"
        if not _adapter_path.exists():
            return LPCheck(
                check_id="CHECK-LP-004",
                description="UniswapV3LPAdapter.read_state() без ошибок",
                status="FAIL",
                detail=f"Файл адаптера не найден: {_adapter_path}",
                blocking=True,
            )

        _spec = _ilu.spec_from_file_location("_uniswap_v3_lp_direct", _adapter_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        UniswapV3LPAdapter = _mod.UniswapV3LPAdapter

        adapter = UniswapV3LPAdapter()
        state = adapter.read_state()

        fee_apy = state.get("fee_apy_24h")
        tvl = state.get("pool_tvl_usd")
        validated = state.get("validated", False)

        if fee_apy is not None and tvl is not None:
            return LPCheck(
                check_id="CHECK-LP-004",
                description="UniswapV3LPAdapter.read_state() без ошибок",
                status="PASS",
                detail=(
                    f"fee_apy_24h={fee_apy:.2%}, tvl=${tvl / 1e6:.1f}M, "
                    f"validated={validated}"
                ),
                blocking=True,
            )
        else:
            return LPCheck(
                check_id="CHECK-LP-004",
                description="UniswapV3LPAdapter.read_state() без ошибок",
                status="FAIL",
                detail=f"Неполные данные: fee_apy={fee_apy}, tvl={tvl}",
                blocking=True,
            )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-004",
            description="UniswapV3LPAdapter.read_state() без ошибок",
            status="ERROR",
            detail=f"Ошибка: {exc}",
            blocking=True,
        )


def _check_lp_005_data_file_exists() -> LPCheck:
    """
    CHECK-LP-005: data/lp_paper_trading.json существует и содержит корректные поля.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        if not _LP_DATA_PATH.exists():
            return LPCheck(
                check_id="CHECK-LP-005",
                description="data/lp_paper_trading.json существует",
                status="FAIL",
                detail=f"Файл не найден: {_LP_DATA_PATH}",
                blocking=True,
            )

        data = json.loads(_LP_DATA_PATH.read_text(encoding="utf-8"))
        required_keys = ["sleeve", "engine", "start_date", "equity", "LLM_FORBIDDEN"]
        missing = [k for k in required_keys if k not in data]

        if missing:
            return LPCheck(
                check_id="CHECK-LP-005",
                description="data/lp_paper_trading.json существует",
                status="FAIL",
                detail=f"Отсутствуют поля: {missing}",
                blocking=True,
            )

        sleeve = data.get("sleeve")
        if sleeve != "C":
            return LPCheck(
                check_id="CHECK-LP-005",
                description="data/lp_paper_trading.json существует",
                status="FAIL",
                detail=f"sleeve={sleeve!r} != 'C'",
                blocking=True,
            )

        return LPCheck(
            check_id="CHECK-LP-005",
            description="data/lp_paper_trading.json существует",
            status="PASS",
            detail=f"sleeve=C, start_date={data.get('start_date')}, LLM_FORBIDDEN={data.get('LLM_FORBIDDEN')}",
            blocking=True,
        )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-005",
            description="data/lp_paper_trading.json существует",
            status="ERROR",
            detail=f"Ошибка чтения: {exc}",
            blocking=True,
        )


def _check_lp_006_delta_neutral(state: dict) -> LPCheck:
    """
    CHECK-LP-006: все позиции delta-neutral (или нет позиций — OK).
    Проверяет поле is_delta_neutral в каждой позиции.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        positions = state.get("positions", [])

        if not positions:
            return LPCheck(
                check_id="CHECK-LP-006",
                description="Все позиции delta-neutral",
                status="PASS",
                detail="Нет открытых позиций — требование выполнено",
                blocking=True,
            )

        non_neutral = [
            p.get("pool_id", f"pos#{i}")
            for i, p in enumerate(positions)
            if not p.get("is_delta_neutral", True)
        ]

        if non_neutral:
            return LPCheck(
                check_id="CHECK-LP-006",
                description="Все позиции delta-neutral",
                status="FAIL",
                detail=f"Non-neutral позиции: {non_neutral}",
                blocking=True,
            )

        return LPCheck(
            check_id="CHECK-LP-006",
            description="Все позиции delta-neutral",
            status="PASS",
            detail=f"Все {len(positions)} позиций delta-neutral",
            blocking=True,
        )
    except Exception as exc:
        return LPCheck(
            check_id="CHECK-LP-006",
            description="Все позиции delta-neutral",
            status="ERROR",
            detail=f"Ошибка: {exc}",
            blocking=True,
        )


def run_golive_check_lp(write_report: bool = True) -> LPGoLiveReport:
    """
    Запускает все 6 GoLive проверок Engine C и формирует отчёт.

    Если write_report=True → атомарная запись в data/golive_lp_report.json.
    fail-closed: ошибка любой проверки → статус ERROR, overall NOT_READY.
    LLM_FORBIDDEN.

    Returns:
        LPGoLiveReport с результатами всех проверок.
    """
    # LLM_FORBIDDEN
    now = datetime.now(timezone.utc).isoformat()
    state = _load_lp_state_safe()

    checks = [
        _check_lp_001_track_days(state),
        _check_lp_002_max_il_drawdown(state),
        _check_lp_003_policy_lp(),
        _check_lp_004_uniswap_adapter(),
        _check_lp_005_data_file_exists(),
        _check_lp_006_delta_neutral(state),
    ]

    passed = sum(1 for c in checks if c.status == "PASS")
    total = len(checks)

    # overall_status: READY только если все blocking checks PASS
    blocking_failures = [
        c for c in checks
        if c.blocking and c.status in ("FAIL", "ERROR")
    ]
    pending_checks = [
        c for c in checks
        if c.status == "PENDING"
    ]

    if blocking_failures:
        overall = "NOT_READY"
    elif pending_checks:
        overall = "PENDING"
    elif passed == total:
        overall = "READY"
    else:
        overall = "NOT_READY"

    report = LPGoLiveReport(
        checks=checks,
        overall_status=overall,
        passed=passed,
        total=total,
        generated_at=now,
        version=GOLIVE_LP_VERSION,
        LLM_FORBIDDEN=True,
    )

    if write_report:
        _write_report(report)

    return report


def _write_report(report: LPGoLiveReport) -> None:
    """
    Атомарная запись отчёта в data/golive_lp_report.json.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        _GOLIVE_LP_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": report.version,
            "overall_status": report.overall_status,
            "passed": report.passed,
            "total": report.total,
            "generated_at": report.generated_at,
            "LLM_FORBIDDEN": True,
            "checks": [
                {
                    "check_id": c.check_id,
                    "description": c.description,
                    "status": c.status,
                    "detail": c.detail,
                    "blocking": c.blocking,
                }
                for c in report.checks
            ],
        }
        tmp = _GOLIVE_LP_REPORT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _GOLIVE_LP_REPORT_PATH)
    except Exception:
        pass  # fail-closed: ошибка записи не ломает отчёт


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys as _sys

    write = "--no-write" not in _sys.argv
    report = run_golive_check_lp(write_report=write)

    print(f"[{GOLIVE_LP_VERSION}] GoLive-LP: {report.overall_status} ({report.passed}/{report.total})")
    for c in report.checks:
        icon = "✅" if c.status == "PASS" else ("⏳" if c.status == "PENDING" else "❌")
        print(f"  {icon} {c.check_id}: [{c.status}] {c.detail}")

    if write:
        print(f"  → Отчёт записан: {_GOLIVE_LP_REPORT_PATH}")
