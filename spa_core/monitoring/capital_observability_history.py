"""На скольких днях знаменателя ``hit_rate`` капитал стоял на НАБЛЮДЁННЫХ числах (заказ #586).

Заказ цикла #585 (в хвосте ADR-364) поставил вопрос ровно так:

> ``hit_rate`` считался на 30 днях, но доля наблюдённого капитала за эти 30 дней не
> мерилась ни за один день. Прибор ADR-364 умеет только «сегодня». Померить его на
> ИСТОРИИ и сказать, на скольких из дней вердикт триггера опирался на 100 %, а на
> скольких — нет. Без этого «hit-rate 1.0» остаётся числом без знаменателя.

ADR-364 снял приёмку G1 приказа владельца «Portfolio CIO» — долю капитала на наблюдённых
числах — и получил 100 % по обеим осям. Но снял он её **за один день**: прибор читает
`current_positions.json`, а это снимок ПОСЛЕДНЕГО цикла. Между тем ``hit_rate`` = 1.0 —
не приборная величина, а **критерий взвода** (``MIN_HIT_RATE`` = 0.60, мандат владельца
ADR-067), и посчитан он по ДНЯМ, каждый из которых стоял на своих входах. «Сегодня входы
наблюдены» не говорит о тех днях ничего.

## Почему история вообще измерима

Журнал решений (`allocation_rationale_history.jsonl`) несёт по КАЖДОМУ дню и книгу
(`current_positions` — какие деньги где стояли), и провенанс входов: карту живых ставок
`apy_evidenced_pct` плюс явный список `apy_unevidenced`. То есть доля наблюдённого
капитала за прошлый день не восстанавливается косвенно — она в записи **уже есть**, и
её просто ни разу не посчитали.

## Два сигнала, а не один

Наблюдением считается ключ, который (а) присутствует в `apy_evidenced_pct` с числовым
значением И (б) НЕ перечислен в `apy_unevidenced`. Сигналы независимы, пишутся отдельно,
и их согласие — самая дешёвая улика, какая бывает. **Расхождение читается fail-CLOSED**
(нога НЕ наблюдена) и называется отдельно: два поля одной записи, спорящие о том же
долларе, — находка, а не шум. День, несущий только ОДИН сигнал, даёт сверку
**несостоявшейся**, а не «сошедшейся»: несостоявшаяся сверка за согласие не выдаётся.

## Ось одна, и это сказано вслух

Меряется **только ось APY** — ранжирование. Ось TVL (пол $5M, ADR-053) журнал решений не
несёт ВОВСЕ ни в одной схеме, поэтому по истории она **НЕ ИЗМЕРЕНА**, и это записано
отдельным ключом. Печатать одну ось за обе — ровно тот дефект, который ADR-364 назвал у
`feed_coverage.live_pct`; повторять его здесь тем более нельзя.

## Третий исход — и поимённо, а не только у агрегата

День без карты `current_positions`, с пустой книгой ($0 развёрнуто) или без ОБОИХ полей
провенанса — **НЕ ИЗМЕРЕН**, с названной причиной, и в долю не входит ни как 0 %, ни как
100 %. Учёт замкнут тождеством ``измерено + не измерено == дней на входе``: пока оно
держится, молча уронить день нельзя по построению. Знаменатель ``hit_rate`` спрашивается
у КАНОНИЧЕСКОГО производителя (`shadow_trigger_eval.scored_days`); не ответил ⇒
``UNMEASURED``, а не пустое множество — пустое читалось бы как «оценённых дней нет».

## Что прибор НЕ утверждает

Он не утверждает, что HOLD на деградировавших днях был неправ, и не пересчитывает
``hit_rate``: граница критерия — предмет соседа (`hit_rate_selection_bias`, ось C, заказ
#541). Он не судит о причине, по которой нога осталась без ставки, — это предмет
`unevidenced_leg_causes` (заказ #543). Его собственный предмет ровно один: **на чём
стоял КАПИТАЛ в каждый день, и как эти дни легли относительно знаменателя.**

ADVISORY. Только stdlib. Прибор ЧИТАЕТ: ни `data/`, ни адаптеры, ни пороги, ни
``MIN_HIT_RATE``, ни живой трек он не трогает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

# Производитель зовётся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанным при импорте именем:
# связанное имя — это СНИМОК функции на момент импорта, и подмена канонического
# правила отбора прошла бы мимо нас молча. Константа и читатель журнала —
# значения, у них этой болезни нет.
from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.paper_trading.shadow_trigger_eval import (
    MATERIAL_TURNOVER_USD,
    load_history,
)
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.capital_observability_history")

OUTPUT_FILENAME = "capital_observability_history.json"
VERSION = "cap-obs-hist-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Полная наблюдённость. Сравнение долей ведётся по ДОЛЛАРАМ, а не по округлённому
#: проценту: книга, где ненаблюдённой осталась одна позиция в $1, не есть 100.00 %.
FULL_OBSERVATION_PCT = 100.0

#: Причины, по которым день не измеряется. Разные причины — разные адресаты починки,
#: поэтому они не сливаются в одну.
DAY_NO_BOOK = "в записи дня нет карты `current_positions` — знаменатель не назван"
DAY_EMPTY_BOOK = ("книга дня пуста (развёрнуто $0): доли у нуля не существует — это "
                  "НЕ 0 % и НЕ 100 %")
DAY_NO_PROVENANCE = ("запись дня не несёт НИ `apy_evidenced_pct`, НИ `apy_unevidenced` — "
                     "провенанс входов не объявлен ни для одного доллара")

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `shadow_trigger_eval`, писатель "
             "журнала, `POLLED_ADAPTERS`, пороги RiskPolicy v1.0, стоп-кран и живой трек "
             "НЕ трогаются — прибор только считает долю и называет дни")

#: Границы утверждения. Пишутся В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта
#: шапку не открывает, а именно он и переносит число в решение о взводе.
WHAT_IT_DOES_NOT_PROVE = [
    "не утверждает, что HOLD на деградировавших днях был НЕПРАВ: исход дня прибор не "
    "пересчитывает вовсе",
    "не двигает и не оценивает сам `hit_rate`: его граница — предмет "
    "`hit_rate_selection_bias` (ось C, заказ #541)",
    "не объясняет, ПОЧЕМУ нога осталась без живой ставки: это предмет "
    "`unevidenced_leg_causes` (заказ #543)",
    "ось TVL по истории не измерена ни за один день — журнал решений её не несёт",
    "тождество `измерено + не измерено == дней на входе` истинно ПО ПОСТРОЕНИЮ и само "
    "по себе не доказывает ничего; падать ему есть с чего только на сверке ДВУХ "
    "читателей журнала (`reader_reconciliation`) — там день и исчезает молча",
    "знаменатель доли — РАЗВЁРНУТЫЙ капитал книги того дня; кэш в него не входит "
    "(у кэша нет ставки), а протокол вне книги долю не понижает: вопрос в том, на чём "
    "стояли ДЕНЬГИ, а не какова полнота вселенной",
]


def _numeric(value) -> Optional[float]:
    """Число или ``None``. ``bool`` числом не считается."""
    if value is None or isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _funded(record: dict) -> Optional[Dict[str, float]]:
    """Профинансированные позиции дня, либо ``None`` — карты нет вовсе."""
    positions = observed(record, "current_positions", kind=dict)
    if positions is None:
        return None
    out: Dict[str, float] = {}
    for proto, usd in positions.items():
        amount = _numeric(usd)
        if amount is not None and amount > 0:
            out[str(proto)] = amount
    return out


def _material_legs(record: dict) -> Set[str]:
    """Ноги, которые вердикт дня СУЩЕСТВЕННО двигал (порог — константа судьи).

    Порог берётся у `shadow_trigger_eval`, а не переписывается сюда: «существенность»
    определяет тот, кто по ней судит, и два определения спорили бы о том же дне.
    """
    current = observed(record, "current_positions", kind=dict) or {}
    target = observed(record, "target_positions", kind=dict) or {}
    legs: Set[str] = set()
    for proto in set(current) | set(target):
        cur = _numeric(current.get(proto)) or 0.0
        tgt = _numeric(target.get(proto)) or 0.0
        if abs(tgt - cur) >= MATERIAL_TURNOVER_USD:
            legs.add(str(proto))
    return legs


def _day(record: dict) -> dict:
    """Замер одного дня. Ключ ``unmeasured_reason`` — единственный признак третьего исхода."""
    date = str(record.get("cycle_date"))
    funded = _funded(record)
    if funded is None:
        return {"cycle_date": date, "unmeasured_reason": DAY_NO_BOOK}
    deployed = round(sum(funded.values()), 2)
    if deployed <= 0:
        return {"cycle_date": date, "unmeasured_reason": DAY_EMPTY_BOOK}

    evidenced = observed(record, "apy_evidenced_pct", kind=dict)
    unevidenced_raw = observed(record, "apy_unevidenced", kind=list)
    if evidenced is None and unevidenced_raw is None:
        return {"cycle_date": date, "unmeasured_reason": DAY_NO_PROVENANCE,
                "deployed_usd": deployed}
    both_signals = evidenced is not None and unevidenced_raw is not None
    unevidenced = {str(x) for x in (unevidenced_raw or [])}

    material = _material_legs(record)
    observed_usd = 0.0
    unobserved: List[dict] = []
    disagreements: List[dict] = []
    for proto in sorted(funded):
        usd = funded[proto]
        # Сигнал А — живая ставка объявлена и она ЧИСЛО; сигнал Б — ключ не в списке
        # неэвиденсных. Отсутствие поля целиком делает свой сигнал немым (None), а не
        # отрицательным: «не спрашивали» и «спросили и нет» — разные вещи.
        signal_a = (None if evidenced is None
                    else _numeric(evidenced.get(proto)) is not None)
        signal_b = None if unevidenced_raw is None else proto not in unevidenced
        if both_signals and signal_a != signal_b:
            disagreements.append({
                "cycle_date": date, "protocol": proto, "usd": usd,
                "apy_evidenced_pct": "ставка есть" if signal_a else "ставки нет",
                "apy_unevidenced": "не перечислен" if signal_b else "перечислен"})
        # fail-CLOSED: наблюдением считается только согласие ОБОИХ высказавшихся сигналов.
        votes = [v for v in (signal_a, signal_b) if v is not None]
        if votes and all(votes):
            observed_usd += usd
        else:
            unobserved.append({"protocol": proto, "usd": usd,
                               "material_leg": proto in material})

    observed_usd = round(observed_usd, 2)
    return {
        "cycle_date": date,
        "deployed_usd": deployed,
        "observed_usd": observed_usd,
        "observed_pct": round(100.0 * observed_usd / deployed, 4),
        "fully_observed": observed_usd >= deployed,
        "unobserved": unobserved,
        # Заказ спрашивает не только «сколько», но и «почему день выпал». Ненаблюдённая
        # нога, которую вердикт ДВИГАЛ, — это тот же факт, что делает день неоценимым.
        "unobserved_leg_is_material": (any(x["material_leg"] for x in unobserved)
                                       if unobserved else None),
        "provenance_signals": 2 if both_signals else 1,
        "disagreements": disagreements,
    }


def _denominator(data_dir: Path) -> dict:
    """Дни знаменателя ``hit_rate`` — у канонического производителя, не своей копией."""
    try:
        days = _ste.scored_days(data_dir)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        days = None
    if days is None:
        return {"measured": False,
                "reason": ("знаменатель hit_rate не получен от "
                           "shadow_trigger_eval.scored_days — пустым множеством он НЕ "
                           "подменяется: пустое читалось бы как «оценённых дней нет»"),
                "days": None}
    return {"measured": True, "reason": None, "days": sorted(days)}


def _reader_reconciliation(data_dir: Path, history: List[dict],
                           bad_lines: int) -> dict:
    """Сходится ли КАНОНИЧЕСКИЙ читатель журнала с независимой переписью строк.

    Тождество ``измерено + не измерено == дней на входе`` внутри :func:`measure`
    истинно ПО ПОСТРОЕНИЮ (каждая запись попадает ровно в один список), то есть
    само по себе не меряет ничего. Настоящее место, где день исчезает молча, —
    ШАГ РАНЬШЕ: `load_history` схлопывает повтор даты (побеждает последняя
    строка) и молча пропускает нечитаемую строку. Поэтому сверяются ДВА
    независимых чтения одного файла, и расхождение читателей — «не измерено», а
    не поправка к числу.
    """
    import json as _json

    path = Path(data_dir) / _ste._history_filename(None)
    if not path.exists():
        return {"measured": False, "reason": f"файла журнала нет: {path}"}
    try:
        raw = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return {"measured": False, "reason": f"журнал не прочитан: {exc}"}
    dates, bad = set(), 0
    for line in raw:
        try:
            obj = _json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(obj, dict) or not obj.get("cycle_date"):
            bad += 1
            continue
        dates.add(str(obj["cycle_date"]))
    agrees = len(dates) == len(history) and bad == bad_lines
    return {
        "measured": True,
        "journal_lines": len(raw),
        "distinct_dates": len(dates),
        "corrupt_lines": bad,
        # Схлопнутые повторы — не потеря, а правило («последняя строка дня
        # побеждает»); но НАЗВАНЫ они обязаны быть, иначе разница между строками
        # файла и днями замера читается как пропажа.
        "duplicate_date_lines_collapsed": len(raw) - bad - len(dates),
        "readers_agree": agrees,
        "reason": None if agrees else (
            f"канонический читатель дал {len(history)} дн. и {bad_lines} нечитаемых "
            f"строк, независимая перепись — {len(dates)} и {bad}: два чтения одного "
            f"файла спорят, и число дней НЕ ИЗМЕРЕНО"),
    }


def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    data_dir = Path(data_dir)
    history, bad_lines = load_history(data_dir)
    reconciliation = _reader_reconciliation(data_dir, history, bad_lines)

    per_day: List[dict] = []
    unmeasured: List[dict] = []
    for record in history:
        row = _day(record)
        if row.get("unmeasured_reason"):
            unmeasured.append({"cycle_date": row["cycle_date"],
                               "reason": row["unmeasured_reason"]})
        else:
            per_day.append(row)

    doc: dict = {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "version": VERSION,
        "mode": "ADVISORY",
        "axis": "apy",
        "journal_rows": len(history),
        "corrupt_history_lines": bad_lines,
        # Ось TVL названа НЕИЗМЕРЕННОЙ явно: молчание о ней читалось бы как «обе оси
        # сошлись», ровно та подмена, которую ADR-364 нашёл у feed_coverage.live_pct.
        "tvl_axis": {
            "measured": False,
            "reason": ("журнал решений не несёт TVL ни в одной схеме "
                       "(shadow-hist-v1/v2) — по истории ось допуска (пол $5M, ADR-053) "
                       "не восстановима ни за один день"),
        },
        "population": {
            "input_days": len(history),
            "measured_days": len(per_day),
            "unmeasured_days": unmeasured,
            # Тождество учёта. Первая половина истинна по построению и держит
            # тело цикла; вторая — СВЕРКА ДВУХ ЧИТАТЕЛЕЙ, и вот она может не
            # сойтись: день исчезает не в цикле, а раньше — на схлопывании
            # повтора даты и на молча пропущенной строке.
            "accounting_identity_holds": (
                len(per_day) + len(unmeasured) == len(history)
                and reconciliation.get("readers_agree") is True),
            "reader_reconciliation": reconciliation,
        },
        "per_day": per_day,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
        "advisory": _ADVISORY,
    }

    disagreements = [d for row in per_day for d in row["disagreements"]]
    with_both = [r for r in per_day if r["provenance_signals"] == 2]
    doc["provenance_cross_check"] = {
        "days_with_both_signals": len(with_both),
        "days_with_one_signal": len(per_day) - len(with_both),
        "agreed": len(with_both) - len({d["cycle_date"] for d in disagreements}),
        "disagreements": disagreements,
        "note": ("сверка на дне с ОДНИМ сигналом не состоялась и за согласие не "
                 "выдаётся; расхождение читается fail-CLOSED — нога НЕ наблюдена"),
    }

    denom = _denominator(data_dir)
    doc["denominator"] = denom
    degraded = [r for r in per_day if not r["fully_observed"]]
    doc["degraded_days"] = [
        {"cycle_date": r["cycle_date"], "observed_pct": r["observed_pct"],
         "unobserved_usd": round(r["deployed_usd"] - r["observed_usd"], 2),
         "unobserved": r["unobserved"],
         "unobserved_leg_is_material": r["unobserved_leg_is_material"],
         "in_denominator": (r["cycle_date"] in denom["days"]
                            if denom["measured"] else None)}
        for r in degraded
    ]

    if denom["measured"]:
        scored = set(denom["days"])
        in_denom = [r for r in per_day if r["cycle_date"] in scored]
        # День знаменателя, которого нет среди ИЗМЕРЕННЫХ, — не «полностью наблюдён»:
        # его доля не измерена, и он считается отдельно.
        measured_dates = {r["cycle_date"] for r in per_day}
        doc["answer"] = {
            "scored_days": len(scored),
            "at_full_observation": sum(1 for r in in_denom if r["fully_observed"]),
            "below_full_observation": sum(1 for r in in_denom
                                          if not r["fully_observed"]),
            "not_measured": len(scored - measured_dates),
        }
    else:
        doc["answer"] = None

    doc["status"] = _status(doc, degraded)
    doc["findings"] = _findings(doc, degraded)
    return doc


def _excluded_by_the_same_fact(doc: dict) -> List[dict]:
    """Деградировавшие дни, выпавшие из знаменателя ИЗ-ЗА той же ненаблюдённой ноги."""
    return [d for d in doc["degraded_days"]
            if d["in_denominator"] is False and d["unobserved_leg_is_material"]]


def _status(doc: dict, degraded: List[dict]) -> str:
    if doc["journal_rows"] == 0:
        return STATUS_UNMEASURED
    if not doc["population"]["accounting_identity_holds"]:
        return STATUS_UNMEASURED
    if not doc["denominator"]["measured"]:
        return STATUS_UNMEASURED
    answer = doc["answer"]
    if answer["scored_days"] == 0:
        return STATUS_UNMEASURED
    if answer["below_full_observation"]:
        return STATUS_CRITICAL
    if answer["not_measured"]:
        return STATUS_UNMEASURED
    if not degraded:
        return STATUS_OK
    # Деградация была, и знаменатель её не видел. CRITICAL — если исключение
    # структурно (та же ненаблюдённая нога делает день неоценимым); иначе совпадение,
    # и утверждать про «по построению» нельзя.
    return (STATUS_CRITICAL if len(_excluded_by_the_same_fact(doc)) == len(degraded)
            else STATUS_WARNING)


def _findings(doc: dict, degraded: List[dict]) -> List[str]:
    out: List[str] = []
    if doc["journal_rows"] == 0:
        out.append("[НЕ ИЗМЕРЕНО] журнал решений пуст или не прочитан — "
                   "доли не существует")
        return out
    if not doc["population"]["accounting_identity_holds"]:
        reason = ((observed(doc["population"], "reader_reconciliation", kind=dict)
                    or {}).get("reason")
                   or "измеренные плюс неизмеренные дни не равны дням на входе")
        out.append(f"[НЕ ИЗМЕРЕНО] учёт не замкнулся: {reason}")
    if not doc["denominator"]["measured"]:
        out.append(f"[НЕ ИЗМЕРЕНО] {doc['denominator']['reason']}")

    answer = doc["answer"]
    if answer:
        out.append(
            f"[ОТВЕТ] знаменатель hit_rate — {answer['scored_days']} дн.; на полной "
            f"наблюдённости капитала стояло {answer['at_full_observation']}, ниже "
            f"полной — {answer['below_full_observation']}, доля не измерена у "
            f"{answer['not_measured']}")
    for row in doc["degraded_days"]:
        where = {True: "В ЗНАМЕНАТЕЛЕ", False: "вне знаменателя",
                 None: "положение в знаменателе НЕ ИЗМЕРЕНО"}[row["in_denominator"]]
        out.append(
            f"[ПО ДНЯМ] {row['cycle_date']}: {row['observed_pct']:.2f} % капитала "
            f"наблюдено, ${row['unobserved_usd']:,.2f} стояло на ненаблюдённом "
            f"({', '.join(x['protocol'] for x in row['unobserved'])}) — {where}")

    if answer and answer["below_full_observation"]:
        out.append(
            f"[CRITICAL] {answer['below_full_observation']} дн. знаменателя hit_rate "
            f"стоят на КАПИТАЛЕ, часть которого не наблюдена: критерий взвода "
            f"(MIN_HIT_RATE, мандат владельца ADR-067) оценивал решения по входам, "
            f"чьё происхождение в тот день не было доказано")
    if answer and answer["not_measured"]:
        out.append(
            f"[НЕ ИЗМЕРЕНО] у {answer['not_measured']} дн. знаменателя доля капитала не "
            f"измерена вовсе — эти дни не зачтены ни в полную наблюдённость, ни в "
            f"деградацию")

    same_fact = _excluded_by_the_same_fact(doc)
    if degraded and answer and not answer["below_full_observation"]:
        if len(same_fact) == len(degraded):
            out.append(
                f"[CRITICAL] критерий взвода НИ РАЗУ не оценивался в режиме деградации: "
                f"все {len(degraded)} дн., когда капитал стоял не на полном наблюдении "
                f"(минимум {min(r['observed_pct'] for r in degraded):.2f} %), выпали из "
                f"знаменателя, и выпали ИЗ-ЗА ТОГО ЖЕ факта — ненаблюдённая нога была "
                f"среди двигаемых, а значит день неоценим. «hit_rate стои́т на 100 % "
                f"наблюдённого капитала» верно ПО ПОСТРОЕНИЮ и о поведении триггера при "
                f"деградации входов не говорит ничего")
        else:
            out.append(
                f"[WARNING] деградация наблюдённости была на {len(degraded)} дн., и ни "
                f"один из них не попал в знаменатель; но структурной эта связь доказана "
                f"лишь на {len(same_fact)} — на остальных день выпал по другой причине, "
                f"и совпадение совпадением и остаётся")

    if doc["provenance_cross_check"]["disagreements"]:
        out.append(
            f"[CRITICAL] два поля ОДНОЙ записи спорят о том же долларе на "
            f"{len(doc['provenance_cross_check']['disagreements'])} позици(ях): "
            f"`apy_evidenced_pct` и `apy_unevidenced` расходятся — прочитано "
            f"fail-CLOSED (нога НЕ наблюдена)")
    if not degraded and answer and answer["scored_days"]:
        out.append("[ОПОРА] режима деградации в окне не было вовсе: сказать, как "
                   "критерий ведёт себя при неполных входах, не на чем — и это НЕ то "
                   "же, что «ведёт себя хорошо»")
    return out


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Порядок — порядок вопроса: население, ось, ответ, дни."""
    out: List[str] = []
    pop = observed(doc, "population", kind=dict)
    # Ни одно из трёх чисел не подставляется: пропавший ключ обязан читаться как
    # «не измерено», а не как ноль. `… or []` здесь и был бы тем самым дефектом —
    # отчёт старого образца молчал бы ровно так же, как здоровый.
    unmeasured = None if pop is None else observed(pop, "unmeasured_days", kind=list)
    out.append(f"   доля капитала на наблюдённых числах ПО ИСТОРИИ (заказ #586): "
               f"{doc.get('status')} · дней журнала {doc.get('journal_rows')} · "
               f"измерено "
               f"{'НЕ ИЗМЕРЕНО' if pop is None else pop.get('measured_days')} · "
               f"не измерено "
               f"{'НЕ ИЗМЕРЕНО' if unmeasured is None else len(unmeasured)}")
    tvl = observed(doc, "tvl_axis", kind=dict) or {}
    out.append(f"   ось: APY (ранжирование). ось TVL по истории НЕ ИЗМЕРЕНА — "
               f"{tvl.get('reason')}")
    for line in (observed(doc, "findings", kind=list) or []):
        out.append(f"   {line}")
    if doc.get("advisory"):
        out.append(f"   {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[WARNING]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[ПО ДНЯМ]") or x.startswith("[ОПОРА]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="доля наблюдённого капитала по дням знаменателя hit_rate (заказ #586)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
