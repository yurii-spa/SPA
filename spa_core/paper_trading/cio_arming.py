"""Взвод CIO: вердикт советника становится решением, по которому книга двигается.

Решение владельца, 2026-09-11, в чате, дословно: «просто сделай так чтобы он начал
работать, запусти его, он не должен простаивать … на все пакеты и стратегии это его
работа». Уточнение того же разговора: «мне не нужно настраивать параметры, мне нужно,
чтобы он начал работать».

Что меняется и что НЕТ
----------------------
До взвода цикл двигал книгу по правилу «ход больше порога И демпфер частоты
пропустил» (ADR-168), а вердикт CIO (ADR-060, `decision_shadow`) записывался рядом и
не влиял ни на что — его собственная подпись: «Verdict is ADVISORY: no position was
changed by it».

После взвода на ЭТОМ месте стоит вердикт CIO. Меняется ровно одно — **РЕШЕНИЕ,
двигать ли книгу**. Не меняется:

- **ЧТО** покупать: цель та же, что и прежде, — итог аллокатора после RiskPolicy
  (Step 2b), analytics-блокировки, RTMR-позы. CIO не строит свою цель, он судит,
  стоит ли переход к этой цели своих денег.
- **RiskPolicy v1.0** — единственный жёсткий гейт — стоит ДО и не тронут.
- **Ни один параметр CIO** не ослаблен (по прямому указанию владельца): окупаемость,
  полоса выигрыша, кулдаун, минимальный срок удержания, бюджеты оборота — как были.
- **Де-риск не ждёт никогда.** Ход, который только сокращает позиции, проходит при
  любом вердикте — то же правило, что у демпфера (`is_pure_reduction`, ADR-168), и
  та же функция, а не её копия. Стоп-кран и реакция на просадку не могут стоять в
  очереди за экономикой.

Отказоустойчивость (инвариант #2, fail-CLOSED)
----------------------------------------------
Вердикта нет, он нечитаем или советник упал ⇒ **держать**. Никогда не торговать на
неизвестном. Держать безопасно: это то, что книга делала последние дни и без взвода.

Почему объявление в КОДЕ, а не в `data/`
----------------------------------------
Синхронизация прода возит `spa_core/`, `scripts/`, `tests/` и НИКОГДА `data/`
(`.claude/rules/deployment.md`, п. 4). Флаг в `data/` уехал бы на origin и никогда не
дошёл бы до цикла, который его читает, — взвод выглядел бы сделанным и не работал бы.
Здесь он доезжает тем же путём, что и сам код, и снимается одной строкой.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict, Optional, Tuple

from spa_core.governance.churn_damper import (
    REASON_DERISK,
    REASON_INITIAL,
    REASON_PLACE_IDLE,
    is_pure_reduction,
)

#: Ходы, которые НЕ являются перекладкой и потому не нуждаются в экономическом
#: суждении CIO. CIO судит одно: окупается ли ПЕРЕТАСОВКА уже вложенных денег.
#: Сокращение позиций (де-риск), первичное размещение пустой книги и вложение
#: простаивающего кэша сверх буфера перетасовкой не являются — это решения демпфера
#: ADR-168, и для последнего — прямое решение владельца 30.08 («размещение
#: простаивающего кэша — не перекладка»). Замер 11.09, пойманный набором
#: `test_cycle_runner`: первая редакция взвода их теряла, и включённый CIO запрещал
#: бы вложить в работу пустую книгу — ровно простой капитала, который ADR-055 прямо
#: запрещает считать нормой.
NOT_A_RESHUFFLE = frozenset({REASON_DERISK, REASON_INITIAL, REASON_PLACE_IDLE})

#: Книги, в которых вердикт CIO управляет перекладкой. Ключ — ``book_id`` тот же,
#: что у `allocation_rationale` (`conservative` / `balanced` / `aggressive`).
#: Снять взвод — удалить строку. Каждая запись несёт, КТО и КОГДА решил.
_OWNER_ORDER = "чат 2026-09-11: «запусти его … на все пакеты и стратегии это его работа»"

ARMED_BOOKS: Dict[str, Dict[str, str]] = {
    "conservative": {
        "armed_by": "владелец", "armed_at": "2026-09-11",
        "source": _OWNER_ORDER, "adr": "ADR-324",
    },
    "balanced": {
        "armed_by": "владелец", "armed_at": "2026-09-11",
        "source": _OWNER_ORDER, "adr": "ADR-328",
    },
    "aggressive": {
        "armed_by": "владелец", "armed_at": "2026-09-11",
        "source": _OWNER_ORDER, "adr": "ADR-328",
    },
}

#: Решения, которые возвращает :func:`trade_allowed`.
ACT = "ACT"
HOLD = "HOLD"
DERISK = "DERISK"
UNARMED = "UNARMED"


def is_armed(book_id: str) -> bool:
    return str(book_id or "").strip().lower() in ARMED_BOOKS


def cio_verdict(cio_doc: Optional[dict]) -> Tuple[Optional[str], list]:
    """``(решение, причины)`` из документа советника; нечитаемо ⇒ ``(None, [...])``."""
    if not isinstance(cio_doc, dict):
        return None, ["вердикт CIO отсутствует"]
    if cio_doc.get("error"):
        return None, [f"советник упал: {cio_doc.get('error')}"]
    shadow = cio_doc.get("decision_shadow")
    if not isinstance(shadow, dict):
        return None, ["в документе CIO нет decision_shadow"]
    dec = shadow.get("decision")
    if dec not in (ACT, HOLD):
        return None, [f"решение CIO не разобрано: {dec!r}"]
    return dec, list(shadow.get("reasons") or [])


def trade_allowed(
    book_id: str,
    cio_doc: Optional[dict],
    current_positions: dict,
    target_positions: dict,
    damper_reason: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Пропустить ли перекладку этой книги. Возврат ``(можно, решение, пояснение)``.

    ``damper_reason`` — как демпфер ADR-168 классифицировал этот ход. Если это НЕ
    перетасовка (де-риск, первичное размещение, вложение простаивающего кэша) — ход
    проходит без экономического суждения CIO: судить там нечего. Если перетасовка —
    решает вердикт CIO.

    Не взведена ⇒ ``(True, UNARMED, …)``: решение остаётся за прежним правилом цикла,
    этот слой не вмешивается вовсе.
    """
    if not is_armed(book_id):
        return True, UNARMED, "CIO не взведён для этой книги — действует прежнее правило"

    if damper_reason in NOT_A_RESHUFFLE:
        return True, DERISK if damper_reason == REASON_DERISK else ACT, (
            f"ход не является перекладкой ({damper_reason}) — экономическое суждение "
            "CIO к нему не относится (правило демпфера ADR-168)")

    if is_pure_reduction(current_positions, target_positions):
        return True, DERISK, ("ход только сокращает позиции — де-риск не ждёт вердикта "
                              "CIO никогда (то же правило, что у демпфера ADR-168)")

    dec, reasons = cio_verdict(cio_doc)
    if dec is None:
        return False, HOLD, ("вердикт CIO недоступен ⇒ держать (fail-CLOSED): "
                             + "; ".join(reasons))
    if dec == ACT:
        return True, ACT, "CIO: перекладка окупается — разрешена"
    return False, HOLD, "CIO: держать — " + ("; ".join(reasons) or "причина не названа")


def _aware_utc(now, run_ts: str):
    """Часы цикла как aware-UTC. Рукава живут на наивном `clock.utcnow()`, а CIO и
    демпфер сравнивают с aware-метками сделок: смешение упало бы TypeError, CIO вернул
    бы документ-ошибку, и книга тихо замёрзла бы на fail-CLOSED (ADR-339)."""
    from datetime import datetime, timezone
    if now is None:
        try:
            now = datetime.fromisoformat(str(run_ts).replace("Z", "+00:00"))
        except ValueError:
            return None
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


def gate_sleeve_book(book_id: str, legs_before: list, proposed: list, opened: list,
                     closed: list, rows: list, equity: float, data_dir, *,
                     today: str, run_ts: str, now=None) -> Tuple[list, list, list, str]:
    """Взвод CIO для книг Balanced / Aggressive (ADR-328).

    В этих книгах ход ПРЕДЛАГАЕТ `sleeve_book.rebalance_book`, и до взвода он же его
    и совершал — вердикт CIO записывался уже ПОСЛЕ, о свершившемся. Здесь вердикт
    спрашивается ДО: предложенная книга принимается только если CIO разрешил
    перетасовку (или ход вовсе не перетасовка — де-риск, первичное размещение,
    вложение кэша). Иначе книга остаётся ровно той, что была, — ноги копируются
    целиком, со всеми полями, и за удержание не платится ничего.

    Возврат ``(книга, opened, closed, пояснение)``.

    Честно названное ограничение: у этих книг нет журнала сделок в форме
    `trades.json`, поэтому гейты CIO, читающие историю ходов (кулдаун, недельный
    оборот, разворот), здесь не видят прошлого и не связывают. До взвода книги
    двигались КАЖДЫЙ цикл без единого экономического гейта — со взводом каждую
    перетасовку судят полоса выигрыша и окупаемость. Направление — строже, не мягче.
    """
    import copy as _copy

    if not is_armed(book_id):
        return proposed, opened, closed, "CIO не взведён для этой книги"
    try:
        from spa_core.paper_trading import sleeve_book as _sb
        from spa_core.paper_trading.allocation_rationale import write_shadow_rationale
        from spa_core.governance.churn_damper import decide as _damper

        flat_before = _sb.collapse_legs_to_flat(legs_before)
        flat_prop = _sb.collapse_legs_to_flat(proposed)
        apy_pct, apy_sources, tvl_sources, tvl_usd = _sb.apy_provenance_from_rows(rows)
        doc = write_shadow_rationale(
            data_dir=data_dir, current_positions=flat_before, target_positions=flat_prop,
            apy_pct=apy_pct, apy_sources=apy_sources, tvl_sources=tvl_sources,
            tvl_usd=tvl_usd, capital_usd=equity, cycle_date=today, run_ts=run_ts,
            trades=[], book_id=book_id, write=False, now=_aware_utc(now, run_ts))
        damper_reason = _damper(flat_before, flat_prop, [], equity,
                                now=_aware_utc(now, run_ts)).reason
    except Exception as exc:  # noqa: BLE001 — вердикт не получен ⇒ держать (fail-CLOSED)
        return (_copy.deepcopy(list(legs_before)), [], [],
                f"вердикт CIO не получен ({type(exc).__name__}) ⇒ держать (fail-CLOSED)")

    ok, dec, why = trade_allowed(book_id, doc, flat_before, flat_prop,
                                 damper_reason=damper_reason)
    if ok:
        return proposed, opened, closed, f"{dec} — {why}"
    return _copy.deepcopy(list(legs_before)), [], [], f"{dec} — {why}"
