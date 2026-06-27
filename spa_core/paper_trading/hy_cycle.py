"""
Engine B (HY/Carry) paper trading cycle — EPIC-1 S1.3.
Запускается отдельно от Engine A cycle_runner.

LLM_FORBIDDEN. fail-closed: EXIT режим → skip.
GoLiveChecker-HY: нужно 14+ дней paper trading для прохождения.

Атомарные записи: tmp + os.replace. Только stdlib.
"""
# LLM_FORBIDDEN
from pathlib import Path
import json
import os
from spa_core.utils import clock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HY_DATA_PATH = _PROJECT_ROOT / "data" / "hy_paper_trading.json"
_HY_REGIME_LOG_PATH = _PROJECT_ROOT / "data" / "hy_regime_log.json"

HY_CYCLE_VERSION = "hy_cycle_v1.1"

# Virtual seed capital for the HY sleeve — separate book ON TOP of the $100k safe
# sleeve, so the go-live honest track is untouched (decision 2026-06-23).
HY_SEED_EQUITY = 20_000.0

# Kill switch threshold: drawdown > 8% → EXIT
_KILL_DRAWDOWN_THRESHOLD = -0.08

# GoLive requirement: минимум 14 дней трека
_GOLIVE_MIN_DAYS = 14


def load_hy_state() -> dict:
    """
    Загружает state Engine B из hy_paper_trading.json.
    fail-closed: любая ошибка → минимальный safe default state.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        if not _HY_DATA_PATH.exists():
            return _default_hy_state()
        raw = _HY_DATA_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return _default_hy_state()


def _default_hy_state() -> dict:
    """Минимальный безопасный state при отсутствии/повреждении файла. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    return {
        "sleeve": "B",
        "engine": "HY/Carry",
        "start_date": clock.utcnow().strftime("%Y-%m-%d"),
        "seed_equity": 0.0,
        "equity": 0.0,
        "peak_equity": 0.0,
        "drawdown_pct": 0.0,
        "positions": [],
        "daily_history": [],
        "regime": "EXIT",
        "last_cycle_at": None,
        "cycles_completed": 0,
        "note": "Engine B HY sleeve — awaiting first cycle (auto-seeds on run).",
        "LLM_FORBIDDEN": True,
    }


def save_hy_state(state: dict) -> None:
    """
    Атомарная запись state Engine B: tmp-файл + os.replace.
    Никогда не пишет напрямую в hy_paper_trading.json.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _HY_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _HY_DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _HY_DATA_PATH)


def get_hy_regime() -> str:
    """
    Читает текущий режим Engine B из data/hy_regime_log.json.
    fail-closed: файл отсутствует / повреждён / нет ключа → EXIT.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        if not _HY_REGIME_LOG_PATH.exists():
            return "EXIT"
        log = json.loads(_HY_REGIME_LOG_PATH.read_text(encoding="utf-8"))
        state = log.get("current_state", "EXIT")
        # Допустимые состояния: ENTER, EXIT, WATCH. Любое другое → EXIT (fail-closed)
        if state not in ("ENTER", "EXIT", "WATCH"):
            return "EXIT"
        return state
    except Exception:
        return "EXIT"  # fail-closed


def refresh_hy_regime(current_state: str, drawdown_pct: float = 0.0) -> str:
    """
    Recompute Engine B regime from live data and persist it to hy_regime_log.json.

    Feeds the deterministic RegimeGate with:
      - funding_rate proxy = high-yield band APY (real, from apy_ranking) — true perp
        funding feed not yet wired (v1).
      - depeg_pct = 0.0 conservative (no live depeg feed yet; peg breaks are still
        caught by the per-protocol monitors).
    fail-closed: any error → keep current state (RegimeGate itself defaults to EXIT).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        from spa_core.risk.regime_gate import evaluate_regime, log_regime_change
        from spa_core.paper_trading.sleeve_yield import hy_target_apy_pct
        funding_rate = hy_target_apy_pct() / 100.0   # proxy, decimal
        result = evaluate_regime(
            funding_rate=funding_rate,
            depeg_pct=0.0,
            current_drawdown_pct=drawdown_pct,
            current_state=current_state if current_state in ("ENTER", "EXIT") else None,
        )
        log_regime_change(result, previous_state=current_state)
        new_state = str(result.get("state", "EXIT"))
        return new_state if new_state in ("ENTER", "EXIT", "WATCH") else "EXIT"
    except Exception:
        return current_state if current_state in ("ENTER", "EXIT", "WATCH") else "EXIT"


def compute_drawdown(equity: float, peak_equity: float) -> float:
    """
    Вычисляет drawdown Engine B.
    Возвращает отрицательное число при просадке (напр. -0.05 = -5%).
    peak_equity == 0 → безопасно возвращает 0.0.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if peak_equity <= 0:
        return 0.0
    return (equity - peak_equity) / peak_equity


def run_hy_cycle(dry_run: bool = True) -> dict:
    """
    Один цикл Engine B HY/Carry paper trading.

    Логика:
      1. Читает state из hy_paper_trading.json
      2. Получает текущий режим из hy_regime_log.json
      3. Если режим != ENTER → пропускаем (fail-closed, cycle_skipped=True)
      4. Считаем drawdown; если < -8% → kill_switch, форсируем EXIT
      5. Обновляем daily_history (дедупликация по дате)
      6. Если dry_run=False → атомарная запись в hy_paper_trading.json

    LLM_FORBIDDEN. fail-closed. dry_run=True по умолчанию.
    """
    # LLM_FORBIDDEN
    now = clock.utcnow()
    today = now.strftime("%Y-%m-%d")

    state = load_hy_state()

    # Self-seed: fund the sleeve ONLY when the state is genuinely fresh (never run,
    # no equity, no history). Guards against clobbering an in-flight book.
    if (float(state.get("seed_equity", 0) or 0) <= 0
            and float(state.get("equity", 0) or 0) <= 0
            and not state.get("daily_history")
            and int(state.get("cycles_completed", 0) or 0) == 0):
        state["seed_equity"] = HY_SEED_EQUITY
        state["equity"] = HY_SEED_EQUITY
        state["peak_equity"] = HY_SEED_EQUITY
        state["note"] = f"Engine B HY sleeve — seeded ${HY_SEED_EQUITY:,.0f} virtual."

    # Refresh regime from live data (writes hy_regime_log.json), then read it back.
    refresh_hy_regime(state.get("regime", "EXIT"), state.get("drawdown_pct", 0.0))
    regime = get_hy_regime()

    # Всегда обновляем regime в state
    state["regime"] = regime
    state["LLM_FORBIDDEN"] = True

    # ── fail-closed: режим не ENTER → пропускаем цикл ──────────────────────
    if regime != "ENTER":
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["cycles_completed"] = state.get("cycles_completed", 0) + 1
        if not dry_run:
            save_hy_state(state)
        return {
            "sleeve": "B",
            "cycle_skipped": True,
            "reason": f"regime={regime} — no new HY positions",
            "equity": state.get("equity", 0.0),
            "drawdown_pct": state.get("drawdown_pct", 0.0),
            "regime": regime,
            "ran_at": now.isoformat() + "Z",
            "dry_run": dry_run,
            "LLM_FORBIDDEN": True,
        }

    # ── drawdown kill switch ─────────────────────────────────────────────────
    equity = state.get("equity", 0.0)
    peak = state.get("peak_equity", equity)

    # Обновляем peak, если equity выросло
    if equity > peak:
        peak = equity

    drawdown = compute_drawdown(equity, peak)

    if drawdown < _KILL_DRAWDOWN_THRESHOLD:
        state["regime"] = "EXIT"  # форсируем EXIT в state
        state["peak_equity"] = peak
        state["drawdown_pct"] = drawdown
        state["last_cycle_at"] = now.isoformat() + "Z"
        state["LLM_FORBIDDEN"] = True
        if not dry_run:
            save_hy_state(state)
        return {
            "sleeve": "B",
            "kill_switch": True,
            "reason": f"drawdown={drawdown:.2%} exceeds {_KILL_DRAWDOWN_THRESHOLD:.0%} threshold",
            "equity": equity,
            "peak_equity": peak,
            "drawdown_pct": drawdown,
            "regime": "EXIT",
            "ran_at": now.isoformat() + "Z",
            "dry_run": dry_run,
            "LLM_FORBIDDEN": True,
        }

    # ── accrue ONE day of carry yield + record daily bar (dedup by date) ────
    # Real APY of the high-yield band (from apy_ranking), accrued once per new day
    # while regime==ENTER. Compounds into equity. No yield invented.
    existing_dates = {entry.get("date") for entry in state.get("daily_history", [])}
    if today not in existing_dates:
        from spa_core.paper_trading.sleeve_yield import hy_target_apy_pct, daily_yield
        apy_pct = hy_target_apy_pct()
        dy = daily_yield(equity, apy_pct)
        equity += dy
        if equity > peak:
            peak = equity
        drawdown = compute_drawdown(equity, peak)
        state["equity"] = equity
        state.setdefault("daily_history", []).append({
            "date": today,
            "equity": round(equity, 2),
            "peak_equity": round(peak, 2),
            "drawdown_pct": drawdown,
            "regime": regime,
            "apy_pct": round(apy_pct, 4),
            "daily_yield_usd": round(dy, 4),
            "positions_count": len(state.get("positions", [])),
        })

    # ── обновляем state ──────────────────────────────────────────────────────
    state["peak_equity"] = peak
    state["drawdown_pct"] = drawdown
    state["last_cycle_at"] = now.isoformat() + "Z"
    state["cycles_completed"] = state.get("cycles_completed", 0) + 1
    state["LLM_FORBIDDEN"] = True

    if not dry_run:
        save_hy_state(state)

    return {
        "sleeve": "B",
        "cycle_skipped": False,
        "equity": equity,
        "peak_equity": peak,
        "drawdown_pct": drawdown,
        "regime": regime,
        "ran_at": now.isoformat() + "Z",
        "dry_run": dry_run,
        "LLM_FORBIDDEN": True,
    }


def get_hy_summary() -> dict:
    """
    Краткий статус Engine B для dashboard / health check.
    Вычисляет golive_days_remaining от actual daily_history (не calendar days).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    state = load_hy_state()
    days_tracked = len(state.get("daily_history", []))
    remaining = max(0, _GOLIVE_MIN_DAYS - days_tracked)

    return {
        "sleeve": "B",
        "engine": "HY/Carry",
        "start_date": state.get("start_date", "unknown"),
        "equity": state.get("equity", 0.0),
        "peak_equity": state.get("peak_equity", 0.0),
        "drawdown_pct": state.get("drawdown_pct", 0.0),
        "regime": state.get("regime", "EXIT"),
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

    result = run_hy_cycle(dry_run=dry)
    summary = get_hy_summary()

    print(f"[hy_cycle {HY_CYCLE_VERSION}] sleeve={result.get('sleeve')} "
          f"regime={result.get('regime')} "
          f"skipped={result.get('cycle_skipped', False)} "
          f"kill_switch={result.get('kill_switch', False)} "
          f"dry_run={dry}")

    if verbose:
        print(json.dumps(result, indent=2))
        print(json.dumps(summary, indent=2))
