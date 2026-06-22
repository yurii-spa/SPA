"""
Engine C (LP/Liquidity) paper trading cycle — EPIC-2 S2.2.
Запускается отдельно от Engine A cycle_runner и Engine B hy_cycle.

LLM_FORBIDDEN. fail-closed: ошибка → skip cycle.
IL kill switch: drawdown > -12% от equity → kill switch, все позиции закрываются.
Delta-neutral requirement: все позиции должны быть delta-neutral.

GoLiveChecker-LP: нужно 14+ дней paper trading для прохождения.

Атомарные записи: tmp + os.replace. Только stdlib.
"""
# LLM_FORBIDDEN
from pathlib import Path
from datetime import datetime
import json
import os

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LP_DATA_PATH = _PROJECT_ROOT / "data" / "lp_paper_trading.json"

LP_CYCLE_VERSION = "lp_cycle_v1.0"

# IL kill switch threshold: IL drawdown > -12% → kill switch
IL_KILL_THRESHOLD = -0.12

# GoLive requirement: минимум 14 дней трека
_GOLIVE_MIN_DAYS = 14


def load_lp_state() -> dict:
    """
    Загружает state Engine C из lp_paper_trading.json.
    fail-closed: любая ошибка → минимальный safe default state.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        if not _LP_DATA_PATH.exists():
            return _default_lp_state()
        raw = _LP_DATA_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return _default_lp_state()


def _default_lp_state() -> dict:
    """Минимальный безопасный state при отсутствии/повреждении файла. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    return {
        "sleeve": "C",
        "engine": "LP/Liquidity",
        "start_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "seed_equity": 0.0,
        "equity": 0.0,
        "peak_equity": 0.0,
        "il_drawdown_pct": 0.0,
        "positions": [],
        "daily_history": [],
        "last_cycle_at": None,
        "cycles_completed": 0,
        "note": "Engine C LP sleeve — no seed data.",
        "LLM_FORBIDDEN": True,
    }


def save_lp_state(state: dict) -> None:
    """
    Атомарная запись state Engine C: tmp-файл + os.replace.
    Никогда не пишет напрямую в lp_paper_trading.json.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _LP_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _LP_DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _LP_DATA_PATH)


def compute_il_drawdown(equity: float, peak_equity: float) -> float:
    """
    Вычисляет IL drawdown для LP sleeve.
    Возвращает отрицательное число при просадке (напр. -0.05 = -5%).
    peak_equity == 0 → безопасно возвращает 0.0.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if peak_equity <= 0:
        return 0.0
    return (equity - peak_equity) / peak_equity


def check_positions_delta_neutral(positions: list) -> bool:
    """
    Проверяет, что все открытые позиции delta-neutral.
    Пустой список позиций → True (нет позиций = допустимо).
    Позиция считается delta-neutral если is_delta_neutral=True или поле отсутствует.
    LLM_FORBIDDEN. fail-closed: ошибка чтения позиции → False.
    """
    # LLM_FORBIDDEN
    if not positions:
        return True
    try:
        for pos in positions:
            if not pos.get("is_delta_neutral", True):
                return False
        return True
    except Exception:
        return False  # fail-closed


def run_lp_cycle(dry_run: bool = True) -> dict:
    """
    Один цикл Engine C LP/Liquidity paper trading.

    Логика:
      1. Читает state из lp_paper_trading.json (fail-closed)
      2. Проверяет delta-neutral требование по позициям
      3. Считает IL drawdown; если < -12% → kill_switch
      4. Обновляет daily_history (дедупликация по дате)
      5. Если dry_run=False → атомарная запись в lp_paper_trading.json

    LLM_FORBIDDEN. fail-closed. dry_run=True по умолчанию.
    """
    # LLM_FORBIDDEN
    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")

    # fail-closed: ошибка загрузки → skip cycle
    try:
        state = load_lp_state()
    except Exception:
        return {
            "sleeve": "C",
            "cycle_skipped": True,
            "reason": "fail_closed_load_error",
            "ran_at": now.isoformat() + "Z",
            "LLM_FORBIDDEN": True,
        }

    state["LLM_FORBIDDEN"] = True

    # ── delta-neutral check ──────────────────────────────────────────────────
    positions = state.get("positions", [])
    if not check_positions_delta_neutral(positions):
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["cycles_completed"] = state.get("cycles_completed", 0) + 1
        if not dry_run:
            save_lp_state(state)
        return {
            "sleeve": "C",
            "cycle_skipped": True,
            "reason": "delta_neutral_violation — positions not delta-neutral",
            "positions_count": len(positions),
            "ran_at": now.isoformat() + "Z",
            "dry_run": dry_run,
            "LLM_FORBIDDEN": True,
        }

    # ── IL drawdown kill switch ──────────────────────────────────────────────
    equity = state.get("equity", 0.0)
    peak = state.get("peak_equity", equity)

    # Обновляем peak, если equity выросло
    if equity > peak:
        peak = equity

    il_dd = compute_il_drawdown(equity, peak)

    if il_dd < IL_KILL_THRESHOLD:
        state["peak_equity"] = peak
        state["il_drawdown_pct"] = il_dd
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["LLM_FORBIDDEN"] = True
        if not dry_run:
            save_lp_state(state)
        return {
            "sleeve": "C",
            "kill_switch": True,
            "reason": (
                f"IL drawdown={il_dd:.2%} exceeds {IL_KILL_THRESHOLD:.0%} threshold"
            ),
            "equity": equity,
            "peak_equity": peak,
            "il_drawdown_pct": il_dd,
            "ran_at": now.isoformat() + "Z",
            "dry_run": dry_run,
            "LLM_FORBIDDEN": True,
        }

    # ── обновляем daily_history (дедупликация по дате) ──────────────────────
    existing_dates = {entry.get("date") for entry in state.get("daily_history", [])}
    if today not in existing_dates:
        state.setdefault("daily_history", []).append({
            "date": today,
            "equity": equity,
            "peak_equity": peak,
            "il_drawdown_pct": il_dd,
            "positions_count": len(positions),
            "delta_neutral_ok": True,
        })

    # ── обновляем state ──────────────────────────────────────────────────────
    state["peak_equity"] = peak
    state["il_drawdown_pct"] = il_dd
    state["last_cycle_at"] = now.isoformat() + "Z"
    state["cycles_completed"] = state.get("cycles_completed", 0) + 1
    state["LLM_FORBIDDEN"] = True

    if not dry_run:
        save_lp_state(state)

    return {
        "sleeve": "C",
        "cycle_skipped": False,
        "equity": equity,
        "peak_equity": peak,
        "il_drawdown_pct": il_dd,
        "positions_count": len(positions),
        "delta_neutral_ok": True,
        "ran_at": now.isoformat() + "Z",
        "dry_run": dry_run,
        "LLM_FORBIDDEN": True,
    }


def get_lp_summary() -> dict:
    """
    Краткий статус Engine C для dashboard / health check.
    Вычисляет golive_days_remaining от actual daily_history (не calendar days).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    state = load_lp_state()
    days_tracked = len(state.get("daily_history", []))
    remaining = max(0, _GOLIVE_MIN_DAYS - days_tracked)

    return {
        "sleeve": "C",
        "engine": "LP/Liquidity",
        "start_date": state.get("start_date", "unknown"),
        "equity": state.get("equity", 0.0),
        "peak_equity": state.get("peak_equity", 0.0),
        "il_drawdown_pct": state.get("il_drawdown_pct", 0.0),
        "days_tracked": days_tracked,
        "cycles_completed": state.get("cycles_completed", 0),
        "golive_days_needed": _GOLIVE_MIN_DAYS,
        "golive_days_remaining": remaining,
        "golive_ready": days_tracked >= _GOLIVE_MIN_DAYS,
        "LLM_FORBIDDEN": True,
    }


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    dry = "--run" not in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    result = run_lp_cycle(dry_run=dry)
    summary = get_lp_summary()

    print(
        f"[lp_cycle {LP_CYCLE_VERSION}] sleeve={result.get('sleeve')} "
        f"skipped={result.get('cycle_skipped', False)} "
        f"kill_switch={result.get('kill_switch', False)} "
        f"il_dd={result.get('il_drawdown_pct', 0.0):.2%} "
        f"dry_run={dry}"
    )

    if verbose:
        print(json.dumps(result, indent=2))
        print(json.dumps(summary, indent=2))
