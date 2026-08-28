"""
Engine B (HY/Carry) paper trading cycle — пакет **Balanced** (сайт: hy → balanced,
ADR-103 / generate_track_snapshot.py). Запускается отдельно от Engine A cycle_runner.

LLM_FORBIDDEN. Только stdlib. Атомарные записи: tmp + os.replace.

Постура (решение владельца 2026-08 «начинай», разблокировка простоя):
рукав Balanced держит book СПЛОШНОЙ — каждый цикл ребалансирует поимённые позиции
из живого apy_ranking и начисляет по их живому APY. Раньше цикл ГЕЙТИЛСЯ прокси-
режимом ENTER/EXIT над несуществующим perp-funding фидом: фид отсутствовал → режим
fail-closed'ился в EXIT → рукав НЕ открывал позиций НИКОГДА (замер: 918 циклов
вхолостую с 22.06 при живых агентах). Гейтом остаётся то, что и должно им быть:
  • kill-switch по просадке (−8%) — форсирует EXIT и халтит;
  • CIO-директива allow_new (постура RED ⇒ hold+reduce, новых не открываем).
`regime` в state/барах теперь ЧЕСТНАЯ ПОСТУРА книги (ENTER = развёрнута и здорова,
WATCH = в кэше/нечего разворачивать, EXIT = killed), а не мёртвый perp-прокси — так
CHECK-HY-002 (≥7 дней ENTER) снова осмысленна. RiskPolicy v1.0 НЕ трогается: это
paper-рукав (инвариант #9), пороги политики неизменны.

GoLiveChecker-HY: нужно 14+ дней paper trading для прохождения.
"""
# LLM_FORBIDDEN
from pathlib import Path
import json
import os
from spa_core.utils import clock
from spa_core.paper_trading import sleeve_book

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источники: запись, видимая в этом модуле,
#: и авторская карта AGENT_OUTPUT_FILES в spa_core/monitoring/uptime_monitor.py.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/hy_paper_trading.json",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HY_DATA_PATH = _PROJECT_ROOT / "data" / "hy_paper_trading.json"
_HY_REGIME_LOG_PATH = _PROJECT_ROOT / "data" / "hy_regime_log.json"

HY_CYCLE_VERSION = "hy_cycle_v1.2"

# Virtual seed capital — пакет Balanced = $100k (мандат владельца 2026-08: три пакета
# сопоставимы по капиталу). Ровно тот же $100k, что у Conservative и Aggressive.
HY_SEED_EQUITY = sleeve_book.PACKAGE_SEED_USD

# Kill switch threshold: drawdown > 8% → EXIT (в бюджете тира Balanced ≤10%)
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
    Один цикл Engine B (пакет Balanced) paper trading.

    Логика:
      1. Читает state из hy_paper_trading.json.
      2. Чистый старт: рукав, НИКОГДА не державший реальной позиции, (пере)сеется на
         мандатный $100k (счётчик ещё не начинался). Держал позиции → не трогаем.
      3. Считаем drawdown; если < -8% → kill_switch, форсируем EXIT, халтим.
      4. Иначе — СПЛОШНОЙ деплой: ребаланс поимённой book из живого apy_ranking
         (CIO-директива allow_new гейтит только НОВЫЕ позиции), начисление по живому
         APY каждой позиции. Нет живых данных ⇒ держим, доход 0 (fail-closed).
      5. `regime` пишется как честная постура (ENTER развёрнута / WATCH кэш / EXIT kill).
      6. Обновляем daily_history (дедуп по дате). dry_run=False → атомарная запись.

    LLM_FORBIDDEN. fail-closed. dry_run=True по умолчанию.
    """
    # LLM_FORBIDDEN
    now = clock.utcnow()
    today = now.strftime("%Y-%m-%d")

    state = load_hy_state()

    # ── Разовый owner-approved пересев на мандатный $100k (решение владельца 2026-08-24) ──
    # Живые книги пошли на ЛЕГАСИ-сидах ($66k у Balanced), потому что были профинансированы
    # раньше, и штатный self-seed их (правильно) не трогал по _ever_funded. Владелец явно
    # выбрал ЧИСТЫЙ рестарт на $100k, сознательно приняв потерю накопленных дней. Это НЕ
    # ослабление предохранителя: штатный self-seed ниже по-прежнему fail-closed по
    # _ever_funded; здесь — разовая миграция по прямому указанию владельца, защищённая
    # маркером reseed_100k_done, чтобы сработать РОВНО ОДИН РАЗ и никогда не затереть
    # $100k-книгу повторно. Можно удалить после того, как маркер проставлен в проде.
    # Условие узкое: срабатывает ТОЛЬКО на профинансированной книге НИЖЕ мандата
    # (0 < seed < $100k) — то есть на реальном легаси-сиде $66k. Свежие книги (seed=0) и
    # уже $100k-книги под условие не попадают (и синтетические фикстуры тестов тоже).
    if (not state.get("reseed_100k_done")
            and 0 < float(state.get("seed_equity", 0) or 0) < sleeve_book.PACKAGE_SEED_USD):
        state["seed_equity"] = HY_SEED_EQUITY
        state["equity"] = HY_SEED_EQUITY
        state["peak_equity"] = HY_SEED_EQUITY
        state["drawdown_pct"] = 0.0
        state["positions"] = []
        state["daily_history"] = []
        state["regime"] = "EXIT"
        state["reseed_100k_done"] = True
        state["note"] = (f"Balanced (Engine B) — clean ${HY_SEED_EQUITY:,.0f} restart "
                         f"(owner decision 2026-08-24).")

    # Self-seed: засеваем рукав ТОЛЬКО когда он по-настоящему свежий (денег нет ни
    # сейчас, ни в истории). Guards against clobbering an in-flight book.
    # 2026-08 (мандат «начинай», $100k): сид поднят до мандатного $100k (константа
    # HY_SEED_EQUITY = PACKAGE_SEED_USD) — сами условия засева НЕ трогаем, они и так
    # верны: свежая книга (seed<=0, equity<=0, без ever_funded) сеется чистым днём-1
    # на $100k. Книга, у которой капитал БЫЛ (даже фантомный) — НЕ засевается: это
    # потеря / уже начатый трек, её разбирают, а не затирают (fail-closed, инвариант
    # владельца 08.08; сторож spa_core/tests/test_sleeve_seeding_lock.py).
    _hist = state.get("daily_history") or []
    _ever_funded = any(float(h.get("equity", 0) or 0) > 0 for h in _hist)
    if (float(state.get("seed_equity", 0) or 0) <= 0
            and float(state.get("equity", 0) or 0) <= 0
            and not _ever_funded):
        state["seed_equity"] = HY_SEED_EQUITY
        state["equity"] = HY_SEED_EQUITY
        state["peak_equity"] = HY_SEED_EQUITY
        state["note"] = (f"Balanced (Engine B) — clean start seeded "
                         f"${HY_SEED_EQUITY:,.0f} virtual (owner mandate 2026-08).")

    # Обновляем perp-прокси лог для наблюдаемости (НЕ гейтит деплой — см. docstring).
    refresh_hy_regime(state.get("regime", "EXIT"), state.get("drawdown_pct", 0.0))
    state["LLM_FORBIDDEN"] = True

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

    # ── СПЛОШНОЙ деплой: ребаланс поимённой book + начисление (дедуп по дате) ──
    # #208 / ADR-103: раньше начислялась медианная ставка ПОЛОСЫ на весь капитал при
    # пустом списке позиций — «начисление — не трек» (решение владельца 19.08). Теперь
    # рукав держит поимённые позиции из живого apy_ranking и каждая начисляет по СВОЕМУ
    # живому APY. Нет живых данных ⇒ позиции держатся, доход 0 (fail-closed). Деплой
    # больше НЕ гейтится perp-режимом ENTER (мандат «начинай»): гейты — kill-switch
    # выше и CIO-директива allow_new (только НОВЫЕ позиции).
    from spa_core.investment_os.directive import cio_allows_new_positions
    allow_new = cio_allows_new_positions()
    existing_dates = {entry.get("date") for entry in state.get("daily_history", [])}
    if today not in existing_dates:
        rows = sleeve_book.load_ranking_rows()
        cands = sleeve_book.hy_candidates(rows)
        book, opened, closed = sleeve_book.rebalance_book(
            state.get("positions") or [], cands, equity,
            today=today, allow_new=allow_new,
        )
        dy, deployed = sleeve_book.accrue_book(book, cands)
        equity += dy
        if equity > peak:
            peak = equity
        drawdown = compute_drawdown(equity, peak)
        # Честная постура книги: развёрнута в рынок ⇒ ENTER; всё в кэше ⇒ WATCH.
        # (EXIT ставит только kill-switch выше.) Так CHECK-HY-002 «≥7 дней ENTER»
        # снова осмысленна — считает дни реального присутствия в рынке.
        regime = "ENTER" if deployed > 0 else "WATCH"
        state["equity"] = equity
        state["positions"] = book
        state.setdefault("daily_history", []).append({
            "date": today,
            "equity": round(equity, 2),
            "peak_equity": round(peak, 2),
            "drawdown_pct": drawdown,
            "regime": regime,
            "apy_pct": sleeve_book.book_weighted_apy_pct(book),
            "daily_yield_usd": round(dy, 4),
            "positions_count": len(book),
            "deployed_usd": deployed,
            "opened": opened,
            "closed": closed,
            "cio_allowed_new": allow_new,
            "accrual_basis": sleeve_book.ACCRUAL_BASIS,
        })
    else:
        # Тот же день уже записан — постуру берём из текущей развёрнутости книги.
        _dep = sum(float(p.get("notional_usd") or 0.0)
                   for p in (state.get("positions") or []))
        regime = "ENTER" if _dep > 0 else "WATCH"

    # ── обновляем state ──────────────────────────────────────────────────────
    state["regime"] = regime
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
