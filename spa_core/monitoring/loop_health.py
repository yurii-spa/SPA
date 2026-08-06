"""loop_health.py — метрики самой петли решений (ADR-066, Фаза 4).

Петля, которая не меряет себя, деградирует так же молча, как офис без
читателей. Метрики — из состояния моста (data/findings_bridge_state.json)
и статусов созданных им карточек:

  latency   находка → карточка (медиана/максимум, часы) и карточка → закрытие;
  taken     судьба карточек моста: new (лежит) / in-progress|done руками /
            closed автозакрытием — «доля взятых» и есть пульс петли;
  recurrence сколько находок ВЕРНУЛИСЬ после закрытия (рецидив = системная
            причина, не случайность).

Выход: data/loop_health.json. Считается при каждом прогоне моста (дёшево).
LLM_FORBIDDEN. Только stdlib. Время — вход (now=).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os
import statistics

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso
from spa_core.monitoring.findings_bridge import STATE_REL, card_status

HEALTH_REL = os.path.join("data", "loop_health.json")


def _hours(a: str | None, b: str | None) -> float | None:
    ta, tb = _parse_iso(a), _parse_iso(b)
    if ta is None or tb is None:
        return None
    return round((tb - ta).total_seconds() / 3600.0, 2)


def compute(state: dict, status_of, now: dt.datetime) -> dict:
    entries = (state.get("findings") or {}).values()
    to_card = [h for e in entries
               if (h := _hours(e.get("first_seen"), e.get("carded_at"))) is not None]
    to_close = [h for e in entries
                if (h := _hours(e.get("carded_at"), e.get("closed_at"))) is not None]
    recurrences = sum(int(e.get("recurrences", 0)) for e in entries)

    taken = {"new": 0, "in_progress": 0, "done_by_human": 0, "auto_closed": 0,
             "unreadable": 0}
    for e in entries:
        card = e.get("card")
        if not card:
            continue
        if e.get("status") == "closed":
            taken["auto_closed"] += 1
            continue
        st = status_of(card)
        if st == "new":
            taken["new"] += 1
        elif st == "in-progress":
            taken["in_progress"] += 1
        elif st == "done":
            taken["done_by_human"] += 1
        else:
            taken["unreadable"] += 1

    def _agg(xs):
        return ({"median_h": round(statistics.median(xs), 2),
                 "max_h": round(max(xs), 2), "n": len(xs)} if xs
                else {"median_h": None, "max_h": None, "n": 0})

    open_cards = sum(1 for e in entries if e.get("status") == "carded")
    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            "open_cards": open_cards,
            "latency_finding_to_card": _agg(to_card),
            "latency_card_to_close": _agg(to_close),
            "recurrences_total": recurrences,
            "cards_fate": taken,
            "note": ("мало истории — медианы по n<5 не интерпретировать"
                     if len(to_card) < 5 else "")}


def run(root: str = REPO_ROOT, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        state = json.load(open(os.path.join(root, STATE_REL)))
    except Exception:
        state = {}
    report = compute(state, card_status, now)
    from spa_core.utils.atomic import atomic_save
    atomic_save(report, os.path.join(root, HEALTH_REL))
    return report
