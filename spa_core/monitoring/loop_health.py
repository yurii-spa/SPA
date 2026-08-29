"""loop_health.py — метрики самой петли решений (ADR-066, Фаза 4).

Петля, которая не меряет себя, деградирует так же молча, как офис без
читателей. Метрики — из состояния моста (data/findings_bridge_state.json)
и статусов созданных им карточек:

  latency   находка → карточка (медиана/максимум, часы) и карточка → закрытие;
  taken     судьба карточек моста: new (лежит) / in-progress|done руками /
            closed автозакрытием — «доля взятых» и есть пульс петли; статус,
            прочитанный, но не из этого перечисления (`ingested`, `needs-owner`,
            …), считается ОТДЕЛЬНО (`other_status`) и называется поимённо —
            складывать его с «не измерено» значило бы объявлять слепым пятном
            измеренное состояние (#421);
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
        # `live` — находка СЕЙЧАС на доске (мост её не закрыл). Замер 29.08 (цикл
        # #421): из четырёх «вернувшихся» две — `aave_v3` (last_seen 25.08) и
        # `fluid_fusdc` (26.08) — закрыты и с тех пор не появлялись ни разу, а
        # обязательный шаг 0-офис четвёртые сутки печатал про них «🔴 РЕЦИДИВ: 4
        # находки ВЕРНУЛИСЬ» в НАСТОЯЩЕМ времени и требовал действия. Счётчик
        # `recurrences` только растёт и не стареет НИКОГДА — ровно то, чего боялась
        # карточка `inbox-puls-petli-adr-066-prochitan-vpervye-3-r`: «счётчик
        # рецидивов навсегда ненулевой и перестаёт быть сигналом».
        recurring.append({"key": key, "recurrences": n,
                          "status": e.get("status"),
                          "last_seen": e.get("last_seen"),
                          "live": e.get("status") != "closed",
                          "carded": bool(e.get("card"))})
    recurring.sort(key=lambda r: (-r["recurrences"], r["key"]))
    by_class: dict[str, int] = {}
    for r in recurring:
        cls = r["key"].rsplit(":", 1)[0] if ":" in r["key"] else r["key"]
        by_class[cls] = by_class.get(cls, 0) + r["recurrences"]
    by_class = dict(sorted(by_class.items(), key=lambda kv: (-kv[1], kv[0])))
    return recurring, by_class


def _recurrence_liveness(recurring: list[dict]) -> dict:
    """Рецидив ЖИВОЙ (находка на доске) отдельно от ИСТОРИЧЕСКОГО (закрыта и молчит).

    **Чего здесь намеренно НЕТ.** Карточка просила отделить рецидив, порождённый
    ТАКТОМ самого сторожа (суточный снимок офиса тасует `top_opportunities`, находка
    выпадает и возвращается, хотя условие не менялось), от рецидива «починили и
    вернулось». Разделить их по этому признаку НЕЧЕМ: `findings_bridge_state.json`
    не записывает, ЧТО изменилось между закрытием и возвратом, а `absent_count`
    (ADR-161) обнуляется при каждом наблюдении и потому маркером эпохи не является.
    Изобрести прокси значило бы предъявить как измерение то, чего никто не мерил —
    ровно класс, против которого написана вся эта петля. Поэтому разделение сделано
    по признаку, который в данных ЕСТЬ, и он же снимает названный картой вред:
    вечно ненулевой счётчик перестаёт звучать в настоящем времени.
    """
    live = sum(r["recurrences"] for r in recurring if r.get("live"))
    return {"live": live,
            "historical": sum(r["recurrences"] for r in recurring) - live,
            "historical_last_seen": max(
                (r.get("last_seen") for r in recurring
                 if not r.get("live") and r.get("last_seen")), default=None)}


def compute(state: dict, status_of, now: dt.datetime) -> dict:
    findings = state.get("findings") or {}
    entries = findings.values()
    to_card = [h for e in entries
               if (h := _hours(e.get("first_seen"), e.get("carded_at"))) is not None]
    to_close = [h for e in entries
                if (h := _hours(e.get("carded_at"), e.get("closed_at"))) is not None]
    recurrences = sum(int(e.get("recurrences", 0)) for e in entries)

    # ЧЕТЫРЕ исхода, а не три. До #421 всё, что не `new`/`in-progress`/`done`,
    # падало в `unreadable` — «статус НЕ ИЗМЕРЕН». Замер 29.08 на живом состоянии:
    # все четыре «неизмеренные» карточки читались прекрасно и несли статус
    # `ingested` (карточки owner-decision, разобранные по протоколу) —
    # `owner-decision-kritichnaya-nahodka-petli-com-spa-{telegr,digest,tier1,weekly}`.
    # То есть «не измерено» стояло на ИЗМЕРЕННОМ состоянии, которого просто не было
    # в перечислении, и шаг 0-офис требовал разбирать четверть выборки как слепое
    # пятно. Направление ошибки обратное обычному, но класс тот же: утверждение о
    # мере, которой не делали. Теперь статус, прочитанный и не попавший в
    # перечисление, называется собой (`other_status`), а `unreadable` означает
    # ровно то, что говорит: статуса не отдали вовсе.
    taken = {"new": 0, "in_progress": 0, "done_by_human": 0, "auto_closed": 0,
             "other_status": 0, "unreadable": 0}
    cards_other_status: list[dict] = []
    cards_unreadable: list[dict] = []
    for key, e in (findings or {}).items():
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
        elif st:
            taken["other_status"] += 1
            cards_other_status.append({"key": key, "card": card, "status": st})
        else:
            # Названо ПОИМЁННО: «четыре карточки не прочитаны» без имён — строка,
            # по которой действовать нечем, и она возвращается каждый цикл целой.
            taken["unreadable"] += 1
            cards_unreadable.append({"key": key, "card": card})

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
            "recurrence_liveness": _recurrence_liveness(_recurring),
            "cards_fate": taken,
            "cards_other_status": cards_other_status,
            "cards_unreadable": cards_unreadable,
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
