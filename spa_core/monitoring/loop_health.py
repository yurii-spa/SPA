"""loop_health.py — метрики самой петли решений (ADR-066, Фаза 4).

Петля, которая не меряет себя, деградирует так же молча, как офис без
читателей. Метрики — из состояния моста (data/findings_bridge_state.json)
и статусов созданных им карточек:

  latency   находка → карточка (медиана/максимум, часы) и карточка → закрытие;
  taken     судьба карточек моста: new (лежит) / in-progress|done руками /
            closed автозакрытием — «доля взятых» и есть пульс петли;
  recurrence сколько находок ВЕРНУЛИСЬ после закрытия (рецидив = системная
            причина, не случайность) — и ПОИМЁННО какие: `recurring_findings`
            (ключ, число возвратов, есть ли живая карточка) и свёртка по классу
            находки `recurrences_by_class`. Голая сумма объявляла причину
            системной, не называя ни одной находки, — действовать по ней было
            нечем.

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


def _recurrence_detail(findings: dict) -> tuple[list[dict], dict[str, int]]:
    """Назвать ПОИМЁННО, какие находки вернулись после закрытия (и чьи они).

    `recurrences_total` — голая сумма: она объявляет рецидив системной причиной
    и не называет ни одной. Читатель (шаг 0-офис) печатал «🔴 РЕЦИДИВ: 5 находок
    ВЕРНУЛИСЬ» и требовал действия, по которому действовать было нечем: ни ключа,
    ни производителя, ни ответа на главный вопрос — есть ли у рецидива живая
    карточка. Замер 28.08: все 5 рецидивов пришли из ОДНОГО класса
    (`gap:opportunity_unnamed:*`), а из отчёта это было неизвлекаемо.

    Класс находки — ключ без последнего сегмента (`gap:opportunity_unnamed:aave_v3`
    → `gap:opportunity_unnamed`): именно он и есть «производитель», о котором
    говорит формулировка о системной причине.

    `carded=False` при возврате — самый острый случай: находка вернулась, и
    карточки под неё сейчас нет.
    """
    recurring: list[dict] = []
    for key, e in (findings or {}).items():
        n = int(e.get("recurrences", 0) or 0)
        if n <= 0:
            continue
        recurring.append({"key": key, "recurrences": n,
                          "status": e.get("status"),
                          "carded": bool(e.get("card"))})
    recurring.sort(key=lambda r: (-r["recurrences"], r["key"]))
    by_class: dict[str, int] = {}
    for r in recurring:
        cls = r["key"].rsplit(":", 1)[0] if ":" in r["key"] else r["key"]
        by_class[cls] = by_class.get(cls, 0) + r["recurrences"]
    by_class = dict(sorted(by_class.items(), key=lambda kv: (-kv[1], kv[0])))
    return recurring, by_class


def compute(state: dict, status_of, now: dt.datetime) -> dict:
    findings = state.get("findings") or {}
    entries = findings.values()
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
    _recurring, _by_class = _recurrence_detail(findings)
    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            "open_cards": open_cards,
            "latency_finding_to_card": _agg(to_card),
            "latency_card_to_close": _agg(to_close),
            "recurrences_total": recurrences,
            # ADR-066: рецидив, названный поимённо (см. _recurrence_detail).
            "recurring_findings": _recurring,
            "recurrences_by_class": _by_class,
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
