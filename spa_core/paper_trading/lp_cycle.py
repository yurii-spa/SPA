"""
Engine C paper trading cycle — пакет **Aggressive** (сайт: lp → aggressive,
ADR-103 / generate_track_snapshot.py). Запускается отдельно от Engine A/B.

LLM_FORBIDDEN. Только stdlib. Атомарные записи: tmp + os.replace.

Постура (решение владельца 2026-08 «Гоу B» — собрать НАСТОЯЩУЮ высокодоходную книгу
в опубликованной полосе Aggressive, до 20% APY, стоп под 25% просадки):
рукав держит book СПЛОШНОЙ и КОНЦЕНТРИРОВАННУЮ — top-2 самых доходных имени полосы
из живого apy_ranking, потолок 60% на протокол, бюджет просадки −25%. Раньше рукав
опрашивал lp_candidates (фильтр по LP-именам): в живом whitelist LP-имён НЕТ, список
возвращался ПУСТЫМ, и рукав простаивал (замер: 929 циклов вхолостую с 22.06). Теперь
опрашивает band_candidates — те же стейбл-протоколы, но взятые концентрированно.

Честная рамка (инвариант #8): whitelist сейчас — только стейбл-протоколы (susde,
pendle PT, …), directional/leveraged плечо в нём отсутствует, поэтому «агрессия»
здесь = КОНЦЕНТРАЦИЯ + широкий бюджет просадки, а НЕ directional-риск. Позиции по
сути peg/duration-риск ⇒ честно помечены delta-neutral. Настоящая directional-
агрессия требует расширения whitelist (owner/legal) — вынесено отдельной задачей.

IL kill switch: drawdown < -25% → kill switch. RiskPolicy v1.0 НЕ трогается (инв. #9).
GoLiveChecker-LP: нужно 14+ дней paper trading для прохождения.
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
    "data/lp_paper_trading.json",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LP_DATA_PATH = _PROJECT_ROOT / "data" / "lp_paper_trading.json"

LP_CYCLE_VERSION = "lp_cycle_v1.2"

# Virtual seed capital — пакет Aggressive = $100k (мандат владельца 2026-08: три
# пакета сопоставимы по капиталу). Ровно тот же $100k, что у Conservative и Balanced.
LP_SEED_EQUITY = sleeve_book.PACKAGE_SEED_USD

# IL kill switch threshold: IL drawdown < -25% → kill switch (бюджет тира Aggressive
# ≤25%; owner «Гоу B»: «стоп под 25% просадки»). Широкий бюджет — и есть тот рычаг,
# которым Aggressive отличается от Balanced (−8%): терпит больше до халта.
IL_KILL_THRESHOLD = -0.25

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
        "start_date": clock.utcnow().strftime("%Y-%m-%d"),
        "seed_equity": 0.0,
        "equity": 0.0,
        "peak_equity": 0.0,
        "il_drawdown_pct": 0.0,
        "positions": [],
        "daily_history": [],
        "last_cycle_at": None,
        "cycles_completed": 0,
        "note": "Engine C LP sleeve — awaiting first cycle (auto-seeds on run).",
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
    now = clock.utcnow()
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

    # ── Разовый owner-approved пересев на мандатный $100k (решение владельца 2026-08-24) ──
    # Живая книга пошла на ЛЕГАСИ-сиде ($33k у Aggressive) — была профинансирована раньше,
    # и штатный self-seed её (правильно) не трогал по _ever_funded. Владелец явно выбрал
    # ЧИСТЫЙ рестарт на $100k, сознательно приняв потерю накопленных дней. Штатный self-seed
    # ниже по-прежнему fail-closed по _ever_funded; здесь — разовая миграция по прямому
    # указанию владельца, защищённая маркером reseed_100k_done (срабатывает РОВНО ОДИН РАЗ,
    # $100k-книгу повторно не затирает). Можно удалить после проставления маркера в проде.
    # Условие узкое: только профинансированная книга НИЖЕ мандата (0 < seed < $100k) — то
    # есть реальный легаси-сид $33k. Свежие и $100k-книги (и фикстуры тестов) не трогает.
    if (not state.get("reseed_100k_done")
            and 0 < float(state.get("seed_equity", 0) or 0) < sleeve_book.PACKAGE_SEED_USD):
        state["seed_equity"] = LP_SEED_EQUITY
        state["equity"] = LP_SEED_EQUITY
        state["peak_equity"] = LP_SEED_EQUITY
        state["il_drawdown_pct"] = 0.0
        state["positions"] = []
        state["daily_history"] = []
        state["reseed_100k_done"] = True
        state["note"] = (f"Aggressive (Engine C) — clean ${LP_SEED_EQUITY:,.0f} restart "
                         f"(owner decision 2026-08-24).")

    # Self-seed: засеваем рукав ТОЛЬКО когда он по-настоящему свежий (денег нет ни
    # сейчас, ни в истории). Guards against clobbering an in-flight book.
    # 2026-08 («Гоу B», $100k): сид поднят до мандатного $100k (LP_SEED_EQUITY =
    # PACKAGE_SEED_USD) — условия засева НЕ трогаем. Свежая книга (seed<=0, equity<=0,
    # без ever_funded) сеется чистым днём-1 на $100k. Книга, у которой капитал БЫЛ
    # (даже фантомный) — НЕ засевается (fail-closed, инвариант владельца 08.08;
    # сторож spa_core/tests/test_sleeve_seeding_lock.py).
    _hist = state.get("daily_history") or []
    _ever_funded = any(float(h.get("equity", 0) or 0) > 0 for h in _hist)
    if (float(state.get("seed_equity", 0) or 0) <= 0
            and float(state.get("equity", 0) or 0) <= 0
            and not _ever_funded):
        state["seed_equity"] = LP_SEED_EQUITY
        state["equity"] = LP_SEED_EQUITY
        state["peak_equity"] = LP_SEED_EQUITY
        state["note"] = (f"Aggressive (Engine C) — clean start seeded "
                         f"${LP_SEED_EQUITY:,.0f} virtual (owner mandate 2026-08 «Гоу B»).")

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

    # ── rebalance the REAL Aggressive book + accrue per-position (dedup by date) ──
    # «Гоу B»: концентрированная высокодоходная книга — top-2 самых доходных имени
    # полосы (band_candidates), потолок 60% на протокол. Раньше опрашивался
    # lp_candidates (фильтр по LP-именам) → в живом whitelist LP-имён НЕТ → список
    # пуст → рукав простаивал. Теперь берём те же стейбл-протоколы, но концентрированно.
    # Каждая позиция начисляет по СВОЕМУ живому APY; нет живых данных ⇒ держим, доход 0
    # (fail-closed). IL по-прежнему не моделируется (нужен прайс-фид) — il_drawdown 0.
    existing_dates = {entry.get("date") for entry in state.get("daily_history", [])}
    # Захватываем книгу ДО сегодняшнего ребаланса — ниже (CIO Brief SHADOW) это
    # «текущая» позиция хода, а ветка ниже перезапишет и `state["positions"]`, и
    # локальную `positions`.
    _legs_before = list(positions)
    if today not in existing_dates:
        from spa_core.investment_os.directive import cio_allows_new_positions
        rows = sleeve_book.load_ranking_rows()
        cands = sleeve_book.band_candidates(rows, sleeve_book.AGG_BAND_MIN)
        # CIO-директива (ADR-103): постура RED ⇒ новых позиций не открываем.
        allow_new = cio_allows_new_positions()
        book, opened, closed = sleeve_book.rebalance_book(
            positions, cands, equity, today=today, allow_new=allow_new,
            max_positions=sleeve_book.AGG_MAX_POSITIONS,
            cap_pct=sleeve_book.AGG_PER_PROTOCOL_CAP_PCT,
        )
        dy, deployed = sleeve_book.accrue_book(book, cands)
        equity += dy
        if equity > peak:
            peak = equity
        il_dd = compute_il_drawdown(equity, peak)
        state["equity"] = equity
        state["positions"] = book
        positions = book
        state.setdefault("daily_history", []).append({
            "date": today,
            "equity": round(equity, 2),
            "peak_equity": round(peak, 2),
            "il_drawdown_pct": il_dd,
            "apy_pct": sleeve_book.book_weighted_apy_pct(book),
            "daily_yield_usd": round(dy, 4),
            "positions_count": len(book),
            "deployed_usd": deployed,
            "opened": opened,
            "closed": closed,
            "cio_allowed_new": allow_new,
            "accrual_basis": sleeve_book.ACCRUAL_BASIS,
            "delta_neutral_ok": True,
        })

    # ── CIO Brief SHADOW (ADR-060 phase 0 инструментация Aggressive) ─────────
    # Тот же fail-open паттерн, что Step 2f у cycle_runner.py (Conservative) и
    # ADR-201 sleeve-тень ниже: отчётный слой не имеет права ломать цикл,
    # который несёт трек. Ничего не решает и не двигает — записывает
    # сегодняшнее решение (уже принятое веткой выше) в СВОЮ книгу истории
    # (`book_id="aggressive"`), чтобы cio_brief.build_books_brief() мог его
    # прочитать. current/target — список ног этой книги, схлопнутый в
    # плоский словарь (`sleeve_book.collapse_legs_to_flat`) — писатель ждёт
    # ту же форму, что у Conservative-аллокатора. apy_pct/apy_sources/
    # tvl_sources/tvl_usd — из сырых строк ранжирования
    # (`sleeve_book.apy_provenance_from_rows`): у Aggressive нет объекта-
    # аллокатора с провенансом, единственный источник — сама живая строка
    # ранжирования (ADR-053/061/063, «live» = наблюдение).
    # blocked_protocols/policy_refusals НЕ передаются: у Aggressive нет
    # RiskPolicy-гейта над аллокатором, который бы их производил — честнее
    # промолчать (None), чем выдумать пустой список, будто гейт отработал.
    try:
        from spa_core.paper_trading.allocation_rationale import write_shadow_rationale
        _rows = sleeve_book.load_ranking_rows()
        _apy_pct, _apy_sources, _tvl_sources, _tvl_usd = (
            sleeve_book.apy_provenance_from_rows(_rows))
        write_shadow_rationale(
            # _LP_DATA_PATH.parent, НЕ _PROJECT_ROOT / "data": первое
            # monkeypatch-нутое тестами (fixture `lp` в
            # test_sleeve_book_and_cio_directive.py) переводит его в tmp_path;
            # второе — жёсткий путь на боевой data/, который тест бы обошёл
            # молча и записал в живое состояние (запрещено, .claude/rules/deployment.md).
            data_dir=_LP_DATA_PATH.parent,
            current_positions=sleeve_book.collapse_legs_to_flat(_legs_before),
            target_positions=sleeve_book.collapse_legs_to_flat(positions),
            apy_pct=_apy_pct,
            apy_sources=_apy_sources,
            tvl_sources=_tvl_sources,
            tvl_usd=_tvl_usd,
            capital_usd=equity,
            cycle_date=today,
            run_ts=now.isoformat() + "Z",
            trades=[],
            book_id="aggressive",
            write=not dry_run,
        )
    except Exception as _shadow_exc:  # noqa: BLE001 — advisory only, never breaks the cycle
        import logging as _logging
        _logging.getLogger("spa.lp_cycle").warning(
            "CIO Brief SHADOW skipped (%s) — cycle continues", _shadow_exc)

    # ── обновляем state ──────────────────────────────────────────────────────
    state["peak_equity"] = peak
    state["il_drawdown_pct"] = il_dd
    state["last_cycle_at"] = now.isoformat() + "Z"
    state["cycles_completed"] = state.get("cycles_completed", 0) + 1
    state["LLM_FORBIDDEN"] = True

    if not dry_run:
        save_lp_state(state)

    # ── ADR-201: тень слива 50/30/20 (advisory, fail-open) ──────────────────
    # Прецедент — shadow-блок ADR-060 в cycle_runner: отчётная тень не имеет
    # права валить цикл. Капитал не двигает, ничего не гейтит (IS_ADVISORY).
    if not dry_run:
        try:
            from spa_core.strategy_lab.sleeve.composer import run_sleeve_shadow
            _root = Path(__file__).resolve().parents[2]
            run_sleeve_shadow(
                data_dir=_root / "data",
                panel_dir=_root / "data" / "aggressive_lab",
                date_str=today,
            )
        except Exception as _sleeve_exc:  # noqa: BLE001
            import logging as _logging
            _logging.getLogger("spa.lp_cycle").warning(
                "ADR-201 sleeve shadow failed (%s) — cycle unaffected", _sleeve_exc)

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
