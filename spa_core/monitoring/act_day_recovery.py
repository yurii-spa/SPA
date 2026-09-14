"""spa_core/monitoring/act_day_recovery.py — существует ли рычаг, возвращающий
в ОЦЕНЁННЫЙ набор хоть один ACT-день (заказ #601/G15 стоячего приказа Portfolio CIO).

Ряд G6→G14 закрыл первый критерий взвода (`hit_rate`) целиком: цена починок
измерена, отдача измерена и оказалась НУЛЕВОЙ для решения (ADR-382). Взвод
блокирует не он, а ВТОРОЙ критерий — ``net_bps_if_followed`` (ADR-067), и он
стои́т ``UNCHECKED`` с причиной «ни одного ACT-вердикта не оценено». Заказ G15
спрашивает ровно одно: **назвать поимённо, с ценой и адресатом, рычаг, который
вернул бы в оценённый набор хоть один ACT-день** — и если такого рычага нет ни
одного, это тоже ответ.

Замер 14.09 (40 дней журнала, три книги, 66 строк): **ACT-вердиктов ноль**.
Но ход БЫЛ. Разовое разрешение владельца (ADR-334, 11.09 14:31Z, «советник
получает право ровно на ОДИН ход, чтобы появилось что оценивать») израсходовано
в тот же день: сделка **T034**, 11.09 21:47:52Z, оборот $40,263.16, с меткой
``cio_trial_grant``. Метку ставит ТОЛЬКО ветка ``cio_trial.apply_trial_grant``,
которая тем же присваиванием делает ``decision.decision = "ACT"``, — значит день
11.09 БЫЛ ACT, и это наблюдение в журнале сделок, а не догадка.

**Куда делся вердикт.** В журнале, который читает критерий, 11.09 стои́т ``HOLD``.
За 11.09 прошло ЧЕТЫРЕ прогона цикла (06:00, 20:55, **21:47**, **23:31**);
ход сделал прогон 21:47, а строку журнала последним переписал прогон 23:31 —
``allocation_rationale.append_rationale_history`` заменяет строку той же даты
(«latest run of the day wins», идемпотентность по ``cycle_date``). К 23:31
разрешение уже израсходовано, ``apply_trial_grant`` гейты не снял, вердикт стал
``HOLD`` — и ЗАМЕНИЛ СОБОЙ единственный ACT, который система произвела за 40
дней. Правило замены написано против ДВОЙНОГО СЧЁТА при повторном прогоне дня и
свою задачу решает; цена его — ход и вердикт разных прогонов одного дня
неразличимы, и переживает только последний.

**Ответ этого прибора — рычаг ПАРНЫЙ, и половины у него с РАЗНЫМИ адресатами.**

1. Вернуть сам вердикт: он восстановим из ВТОРОЙ ЗАПИСИ о тех же деньгах
   (``trades.json`` + ``audit_trail.jsonl``) — там и метка, и книга до, и книга
   после, и оборот. Адресат — **наш код**, цена низкая.
2. Оценить возвращённый день: нельзя. Ход выходил из ``pendle``, а у судьи день
   оценивается по форвардным ставкам ВСЕХ двинутых ног (``_day_gain_usd``,
   fail-CLOSED). У ``pendle`` форвардной ставки нет ни в одной строке журнала
   (12–14.09), и в ряду фидов у него **ноль точек** — ключа нет у производителя
   вовсе. Адресат — **фид / POLLED_ADAPTERS, денежный путь, решение владельца**;
   константу под маркой ``live`` запрещает ADR-053.

Поэтому обе границы честно РАСХОДЯТСЯ по смыслу и СХОДЯТСЯ в нуле: починка
журнала нашим кодом возвращает **1** ACT-день в журнал и **0** — в ОЦЕНЁННЫЙ
набор. Критерий ``net_bps_if_followed`` на существующей истории не закрывается
НИ ПРИ КАКОМ состоянии нашего кода, а разовое разрешение владельца
израсходовано и не купило ни одного измеримого числа.

Это и есть та самая форма ошибки, против которой написан инвариант #17: «ACT
не было ни разу» и «ACT был и стёрт» — разные факты, а выглядели одинаково.

Устройство и границы
--------------------
Население берётся у ДЕНЕГ (метка на сделке), а не у журнала: журнал и есть
подозреваемый, и спрашивать его о себе значило бы замкнуть прибор на себя.
Правило метки, правило «что такое точка ряда», пересчёт дня и разбор журнала
взяты у соседей ЦЕЛИКОМ (``cio_trial``, ``criterion_value_interval``,
``shadow_trigger_eval``) — вторых копий здесь нет намеренно.

Прибор ТОЛЬКО ЧИТАЕТ. Он ничего не чинит, журнал не переписывает, вердикт не
восстанавливает — он НАЗЫВАЕТ рычаг, его цену и адресата.

**Чего он НЕ доказывает** — сказано вслух и вынесено в артефакт
(``what_it_does_not_prove``), а не оставлено читателю.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.paper_trading.cio_trial import MARK as TRIAL_MARK, TRIAL_GRANT
from spa_core.monitoring.criterion_value_interval import (
    load_series_points as _load_series_points,
    unit_parity as _unit_parity,
)

log = logging.getLogger("spa.monitoring.act_day_recovery")

VERSION = "act-day-recovery-v1"
ARTIFACT = "act_day_recovery.json"
TRADES_FILENAME = "trades.json"

#: Исходы дня населения. Разведены намеренно: «журнал не знал о ходе никогда» и
#: «журнал знал и строку переписали» — разные дефекты с разными починками, и
#: слить их значило бы записать вторую в первую (инв. #17).
DAY_PRESENT = "present"              # журнал несёт ACT — потери нет
DAY_ERASED = "erased_by_replacement"  # строка ACT заменена ПОЗДНЕЙШИМ прогоном того же дня
DAY_NOT_JOURNALED = "not_journaled"  # строка журнала НЕ позже хода — замена не доказана
DAY_NO_LINE = "no_line"              # строки за этот день нет вовсе
DAY_UNMEASURED = "unmeasured"        # не прочитано — третий исход, не ноль

#: Почему возвращённый день нельзя оценить, и ЧЕЙ рычаг это.
LEVER_OUR_CODE = "our_code"          # материал в ряду есть — поднимает наша строка
LEVER_FEED_OWNER = "feed_owner"      # материала нет ни в один нужный день — фид/POLLED_ADAPTERS
LEVER_NONE = "none_needed"           # день оценивается уже сейчас
#: Горизонт ещё не истёк: форвардных дней нет вовсе. НЕ «рычага не нужно» и НЕ
#: «рычаг у владельца» — ЖДАТЬ, а не чинить. Отдельный класс потому, что без него
#: «слишком рано судить» читалось бы как «всё в порядке» (инв. #17); ровно так же
#: судья помечает UNCHECKED свежий день (замер 14.09).
LEVER_HORIZON_NOT_ELAPSED = "horizon_not_elapsed"
LEVER_UNMEASURED = "unmeasured"

OVERALL_OK = "OK"
OVERALL_WARNING = "WARNING"
OVERALL_CRITICAL = "CRITICAL"
OVERALL_UNMEASURED = "UNMEASURED"

WHAT_IT_DOES_NOT_PROVE = (
    "не доказывает, что восстановленный вердикт был бы ВЫГОДНЫМ: знак "
    "`net_bps_if_followed` считается только по оценённым дням, а этот день "
    "оценить нечем — прибор называет рычаг, а не исход",
    "не доказывает, что правило замены строки той же даты НЕВЕРНО: оно написано "
    "против двойного счёта при повторном прогоне дня и эту задачу решает; "
    "измерена его ЦЕНА на одном дне, а не его отмена",
    "не доказывает, что у `pendle` не было живой ставки 12–14.09: доказано, что "
    "её нет у ПРОИЗВОДИТЕЛЯ (ноль точек ряда) и в журнале — существование ставки "
    "где-то ещё прибор не опровергает и не выдумывает (ADR-300/ADR-302)",
    "не пересчитывает `hit_rate`, не двигает `MIN_HIT_RATE` и не судит о "
    "вердиктах HOLD-дней — предмет здесь ровно один: ACT-день",
)

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `TriggerParams`, писатель журнала, "
             "правило замены строки, `POLLED_ADAPTERS`, пины, адаптеры, накопитель ряда, "
             "пороги RiskPolicy v1.0, стоп-кран, живой трек и `landing/` НЕ трогаются — "
             "прибор только ЧИТАЕТ и называет рычаг, его цену и адресата.")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw) -> Optional[datetime]:
    """ISO-отметка → datetime (UTC). Неразобранное — ``None``, а не «эпоха»."""
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("%s не прочитан: %s", path, exc)
        return None


# ── население: ходы, помеченные разрешением владельца ────────────────────────
def marked_moves(data_dir: Path,
                 trades_filename: str = TRADES_FILENAME) -> Tuple[Optional[List[dict]], str]:
    """Ходы денежного пути с меткой разрешения. ``None`` = НЕ ИЗМЕРЕНО.

    Население берётся у ДЕНЕГ, а не у журнала вердиктов: журнал здесь —
    подозреваемый, и выводить население из него значило бы замкнуть прибор на
    себя (он не нашёл бы ровно тот день, который журнал потерял).

    Метка ``cio_trial_grant`` импортируется у ``cio_trial`` — второй копии
    правила тут нет. Ставит её ТОЛЬКО ветка ``apply_trial_grant``, которая тем
    же присваиванием пишет ``decision = "ACT"``: поэтому метка на сделке есть
    НАБЛЮДЕНИЕ вердикта ACT, а не его реконструкция.
    """
    doc = _read_json(Path(data_dir) / trades_filename)
    if doc is None:
        return None, f"{trades_filename} не прочитан"
    trades = doc.get("trades") if isinstance(doc, dict) else doc
    if not isinstance(trades, list):
        return None, f"{trades_filename} не несёт списка ходов"
    out: List[dict] = []
    for t in trades:
        if isinstance(t, dict) and t.get(TRIAL_MARK):
            out.append(t)
    return out, ""


def _move_deltas(trade: dict) -> Dict[str, float]:
    """Ноги ИСПОЛНЕННОГО хода: книга после минус книга до.

    Своего правила существенности здесь нет — берётся тот же порог
    ``_ste.MATERIAL_TURNOVER_USD``, которым судья отделяет ход от шума.
    """
    frm = trade.get("from_allocation") or {}
    to = trade.get("to_allocation") or {}
    out: Dict[str, float] = {}
    for key in set(frm) | set(to):
        delta = float(to.get(key, 0.0) or 0.0) - float(frm.get(key, 0.0) or 0.0)
        if abs(delta) > 0.005:
            out[str(key)] = round(delta, 2)
    return out


# ── вопрос 1: несёт ли журнал этот ACT ───────────────────────────────────────
def classify_day(trade: dict, record: Optional[dict]) -> Tuple[str, dict]:
    """Что стало с вердиктом этого дня в журнале, который читает критерий.

    ``erased_by_replacement`` объявляется ТОЛЬКО когда строка журнала строго
    ПОЗЖЕ хода: это и есть отпечаток правила «последний прогон дня побеждает».
    Строка РАНЬШЕ хода — другой класс (``not_journaled``), и записать его в
    замену значило бы назвать причиной то, чего в этот раз не было.
    """
    trade_ts = _parse_ts(trade.get("ts"))
    detail = {"trade_ts": trade.get("ts"),
              "trade_id": trade.get("trade_id"),
              "line_generated_at": None,
              "journal_verdict": None}
    if record is None:
        return DAY_NO_LINE, detail
    verdict = str(record.get("verdict") or "").upper()
    line_ts = _parse_ts(record.get("generated_at"))
    detail["journal_verdict"] = verdict or None
    detail["line_generated_at"] = record.get("generated_at")
    if verdict == "ACT":
        return DAY_PRESENT, detail
    if trade_ts is None or line_ts is None:
        detail["reason"] = ("отметка времени хода либо строки не разобрана — "
                            "порядок событий не установлен")
        return DAY_UNMEASURED, detail
    detail["line_later_than_trade_sec"] = round((line_ts - trade_ts).total_seconds(), 3)
    if line_ts > trade_ts:
        return DAY_ERASED, detail
    return DAY_NOT_JOURNALED, detail


# ── вопрос 2: можно ли возвращённый день ОЦЕНИТЬ ─────────────────────────────
def score_recovered_day(deltas: Dict[str, float],
                        forward: List[dict],
                        horizon_days: int) -> dict:
    """Оценим ли исполненный ход по форвардным ставкам журнала.

    Считает ТЕМ ЖЕ ``_ste._day_gain_usd``, которым судья считает всякий другой
    день: свой пересчёт разошёлся бы с судьёй молча, и тогда «день оценим»
    значило бы «оценим ДРУГИМ прибором».
    """
    priced_days = 0
    gain_usd = 0.0
    missing: Set[str] = set()
    for rec in forward[:horizon_days]:
        apy_map = observed(rec, "apy_evidenced_pct", kind=dict) or {}
        day_gain, gaps = _ste._day_gain_usd(deltas, apy_map)
        if day_gain is None:
            missing.update(gaps)
            continue
        priced_days += 1
        gain_usd += day_gain
    return {
        "priced_forward_days": priced_days,
        "forward_days_available": len(forward[:horizon_days]),
        "gain_usd": round(gain_usd, 2) if priced_days else None,
        "unpriced_legs": sorted(missing),
        "scorable": priced_days > 0 and not missing,
    }


def leg_lever(legs: Sequence[str],
              points: Optional[Dict[str, Dict[str, float]]],
              forward_dates: Sequence[str]) -> Tuple[str, dict]:
    """Чей рычаг поднял бы недостающие ставки: наш код или фид/владелец.

    Различие здесь — тот же, что у соседа ``writer_universe_lever_floor``:
    материал в ряду ЕСТЬ ⇒ поднимает наша строка у писателя; материала нет ни в
    один нужный день ⇒ наш код бессилен при любом своём состоянии, и рычаг
    лежит у фида / ``POLLED_ADAPTERS`` (денежный путь, решение владельца).
    Константу под маркой ``live`` запрещает ADR-053, поэтому третьего пути нет.
    """
    if not legs:
        return LEVER_NONE, {"legs": []}
    if points is None:
        return LEVER_UNMEASURED, {"legs": list(legs),
                                  "reason": "ряд фидов не прочитан — рычаг не назван"}
    per_leg: List[dict] = []
    any_material = False
    for leg in legs:
        leg_points = points.get(str(leg)) or {}
        have = sorted(d for d in forward_dates if d in leg_points)
        total = len(leg_points)
        material = bool(have)
        any_material = any_material or material
        per_leg.append({
            "leg": str(leg),
            "series_points_total": total,
            "forward_dates_with_material": have,
            "class": LEVER_OUR_CODE if material else LEVER_FEED_OWNER,
            "why": ("материал того же дня есть в ряду — недостаёт строки у писателя"
                    if material else
                    ("у производителя НОЛЬ точек по этому ключу — ставки не было ни в "
                     "один нужный день, наш код её не поднимет никогда"
                     if total == 0 else
                     "точки ряда есть, но ни одной в нужные форвардные дни")),
        })
    # Достаточно ОДНОЙ ноги без материала, чтобы день не поднялся нашим кодом:
    # судья оценивает ход целиком (fail-CLOSED), а не по доступным ногам.
    blocked = [row for row in per_leg if row["class"] == LEVER_FEED_OWNER]
    lever = LEVER_FEED_OWNER if blocked else LEVER_OUR_CODE
    return lever, {"legs": per_leg,
                   "blocking_legs": [row["leg"] for row in blocked],
                   "any_material": any_material}


# ── замер ────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: int = _ste.DEFAULT_HORIZON_DAYS,
            trades_filename: str = TRADES_FILENAME,
            withhold_forward: Sequence[str] = ()) -> dict:
    """Полный замер G15. Читает; не пишет ничего.

    ``withhold_forward`` — управляющий вход КОНТРОЛЯ расхождения: названные ноги
    вычёркиваются из форвардных ставок, и день обязан перестать быть оценимым.
    Прибор, который не умеет разойтись, нулевой ширины не доказывает.
    """
    now = now or _utcnow()
    data_dir = Path(data_dir)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "question": ("существует ли рычаг, возвращающий в ОЦЕНЁННЫЙ набор хоть один "
                     "ACT-день (заказ #601/G15)"),
        "grant": dict(TRIAL_GRANT),
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
        "advisory": _ADVISORY,
    }

    moves, why = marked_moves(data_dir, trades_filename)
    if moves is None:
        doc.update({"overall": OVERALL_UNMEASURED, "reason": why,
                    "days": [], "bounds": None})
        return doc

    records, bad_lines = _ste.load_history(data_dir)
    by_date: Dict[str, dict] = {str(r.get("cycle_date")): r for r in records
                                if r.get("cycle_date")}
    doc["journal"] = {"lines": len(records), "unparseable": bad_lines,
                      "act_lines": sum(1 for r in records
                                       if str(r.get("verdict") or "").upper() == "ACT")}
    if not records:
        doc.update({"overall": OVERALL_UNMEASURED,
                    "reason": "журнал вердиктов пуст или не прочитан — сравнивать не с чем",
                    "days": [], "bounds": None})
        return doc

    points = _load_series_points(data_dir)
    # КОНТРОЛЬ ШКАЛЫ — до единого вердикта: журнал и ряд суть два производителя
    # одной величины, и проценты против долей подделали бы КАЖДЫЙ вывод о
    # материале. Не сверено ⇒ так и сказано, а не принято за «та же шкала».
    doc["unit_parity"] = (_unit_parity(by_date, points) if points
                          else {"measured": False,
                                "reason": "ряд фидов не прочитан — шкалу сверить не с чем"})

    days: List[dict] = []
    for trade in sorted(moves, key=lambda t: str(t.get("ts") or "")):
        ts = _parse_ts(trade.get("ts"))
        date = ts.date().isoformat() if ts else None
        record = by_date.get(date) if date else None
        state, detail = classify_day(trade, record)

        deltas = _move_deltas(trade)
        turnover = sum(abs(v) for v in deltas.values()) / 2.0
        forward = [by_date[d] for d in sorted(by_date) if date and d > date]
        if withhold_forward:
            trimmed = []
            for rec in forward:
                copy = dict(rec)
                apy = dict(observed(rec, "apy_evidenced_pct", kind=dict) or {})
                for leg in withhold_forward:
                    apy.pop(str(leg), None)
                copy["apy_evidenced_pct"] = apy
                trimmed.append(copy)
            forward = trimmed
        scoring = score_recovered_day(deltas, forward, horizon_days)
        forward_dates = [str(r.get("cycle_date")) for r in forward[:horizon_days]]
        if scoring["scorable"]:
            lever, lever_detail = LEVER_NONE, {"legs": []}
        elif not scoring["forward_days_available"]:
            # Горизонт не истёк — судить не о чем и чинить нечего.
            lever, lever_detail = LEVER_HORIZON_NOT_ELAPSED, {
                "legs": [],
                "why": ("форвардных дней после хода нет вовсе — день не оценим "
                        "ПОКА, и это не рычаг, а срок")}
        else:
            lever, lever_detail = leg_lever(scoring["unpriced_legs"], points,
                                            forward_dates)

        days.append({
            "date": date,
            "state": state,
            "detail": detail,
            "executed_move": {"legs": deltas, "turnover_usd": round(turnover, 2),
                              "material": turnover >= _ste.MATERIAL_TURNOVER_USD},
            "scoring": scoring,
            "lever": lever,
            "lever_detail": lever_detail,
        })

    # ── ОБЕ ГРАНИЦЫ, и середины между ними нет ───────────────────────────────
    # Нижняя: дни, которые вернутся в ОЦЕНЁННЫЙ набор одной лишь починкой
    # журнала — материал у них уже есть.
    # Верхняя: плюс дни, которым недостаёт ставок, чьё поднятие ПО СИЛАМ нашему
    # коду. День, упёршийся в ноль точек у производителя, не входит НИ В ОДНУ
    # границу: он недостижим при любом состоянии нашего кода, и включить его в
    # верхнюю значило бы выдать решение владельца за нашу починку.
    lost = [d for d in days if d["state"] in (DAY_ERASED, DAY_NOT_JOURNALED, DAY_NO_LINE)]
    lower = [d for d in lost if d["scoring"]["scorable"]]
    upper = [d for d in lost if d["scoring"]["scorable"] or d["lever"] == LEVER_OUR_CODE]
    owner_only = [d for d in lost if d["lever"] == LEVER_FEED_OWNER]
    unmeasured = [d for d in days if d["state"] == DAY_UNMEASURED
                  or d["lever"] == LEVER_UNMEASURED]
    too_early = [d for d in lost if d["lever"] == LEVER_HORIZON_NOT_ELAPSED]

    doc["days"] = days
    doc["bounds"] = {
        "act_days_recoverable_to_journal": len(lost),
        "scored_act_days_lower": len(lower),
        "scored_act_days_upper": len(upper),
        "width": len(upper) - len(lower),
        "blocked_on_owner_lever": len(owner_only),
        "too_early_to_judge": len(too_early),
        "unmeasured_days": len(unmeasured),
        "note": ("нижняя — одной починкой журнала; верхняя — плюс то, что по силам "
                 "нашему коду; день без материала у производителя не входит ни в "
                 "одну границу, его рычаг у владельца"),
    }
    doc["criterion"] = {
        "name": "net_bps_if_followed",
        "closes_at_lower_bound": len(lower) > 0,
        "closes_at_upper_bound": len(upper) > 0,
        "note": ("критерий взвода (ADR-067) может быть посчитан только ОЦЕНЁННЫМ "
                 "вердиктом ACT; знак его этим прибором не считается — "
                 "см. what_it_does_not_prove"),
    }

    if unmeasured:
        doc["overall"] = OVERALL_UNMEASURED
        doc["reason"] = (f"{len(unmeasured)} дн. населения не измерены — "
                         "«рычага нет» о них не сказано")
    elif not moves:
        doc["overall"] = OVERALL_OK
        doc["reason"] = ("ходов по разрешению владельца в журнале сделок нет — "
                         "терять было нечего")
    elif too_early and not upper and not owner_only:
        doc["overall"] = OVERALL_WARNING
        doc["reason"] = (f"{len(too_early)} ACT-дн. потеряно журналом, но судить о них "
                         "ещё рано: горизонт не истёк — это срок, а не рычаг")
    elif owner_only and not upper:
        doc["overall"] = OVERALL_CRITICAL
        doc["reason"] = (
            f"ACT-дней потеряно {len(lost)}, вернуть в ОЦЕНЁННЫЙ набор нашим кодом "
            f"нельзя НИ ОДНОГО: {len(owner_only)} дн. упирается(ются) в ноги без "
            f"материала у производителя — рычаг у владельца (фид / POLLED_ADAPTERS). "
            f"Разовое разрешение {TRIAL_GRANT['adr']} израсходовано и не купило ни "
            f"одного измеримого числа")
    elif lost:
        doc["overall"] = OVERALL_CRITICAL
        doc["reason"] = (
            f"ACT-дней потеряно {len(lost)}; в ОЦЕНЁННЫЙ набор возвращаются "
            f"{len(lower)}–{len(upper)} — рычаг НАШ, починка журнала")
    else:
        doc["overall"] = OVERALL_OK
        doc["reason"] = ("каждый ход по разрешению владельца несёт в журнале свой "
                         "вердикт ACT — потери нет")
    return doc


# ── контроль расхождения: прибор обязан УМЕТЬ ответить иначе ────────────────
def widening_control(data_dir: Path, *, now: Optional[datetime] = None,
                     trades_filename: str = TRADES_FILENAME) -> dict:
    """Забрать материал у ОЦЕНИВАЕМОГО дня — оценимость обязана УПАСТЬ.

    Нулевая граница законна только у прибора, способного дать ненулевую. Но
    «способен» доказывается лишь ПАДЕНИЕМ с настоящей высоты: пока в населении
    нет ни одного дня с ``scorable=True``, забирать не у чего, и любое
    «расхождение» здесь было бы истинным ПО ПОСТРОЕНИЮ — перечень непокрытых ног
    удлиняется, а оценимость как была нулевой, так и осталась.

    Замер 14.09 ровно таков: единственный день населения не оценивается вовсе
    (нога ``pendle`` без материала), поэтому на ЖИВЫХ данных контроль честно
    отвечает ``measured: False`` с названной причиной, а способность прибора
    разойтись доказывается на стенде (``test_act_day_recovery``), где день
    оценивается и падает от снятия одной ноги. Выдать здесь ``diverged: True``
    значило бы украсить прибор контролем, который не может не пройти.
    """
    base = measure(data_dir, now=now, trades_filename=trades_filename)
    scorable_days = [d for d in base.get("days", [])
                     if (d.get("scoring") or {}).get("scorable")]
    if not scorable_days:
        return {"measured": False,
                "reason": ("ни одного ОЦЕНИВАЕМОГО дня в населении — падать неоткуда; "
                           "способность прибора разойтись доказывается на стенде, а не "
                           "здесь"),
                "population_days": len(base.get("days", []))}
    day = scorable_days[0]
    victim = sorted(set(day["executed_move"]["legs"])
                    - set(day["scoring"]["unpriced_legs"]))[0]
    perturbed = measure(data_dir, now=now, trades_filename=trades_filename,
                        withhold_forward=[victim])
    after = next((d for d in perturbed.get("days", [])
                  if d.get("date") == day.get("date")), {}).get("scoring", {})
    before = day["scoring"]
    return {
        "measured": True,
        "date": day.get("date"),
        "withheld_leg": victim,
        "scorable_before": before.get("scorable"),
        "scorable_after": after.get("scorable"),
        "priced_days_before": before.get("priced_forward_days"),
        "priced_days_after": after.get("priced_forward_days"),
        "diverged": bool(before.get("scorable")) and not after.get("scorable"),
        "what_it_proves": ("прибор РЕАГИРУЕТ на материал: снятие ставок у одной ноги "
                           "роняет ОЦЕНИВАЕМЫЙ день в неоценимые, значит его нули "
                           "получены замером, а не нечувствительностью"),
    }


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Обе границы — одной строкой, середины нет."""
    out: List[str] = []
    overall = doc.get("overall", OVERALL_UNMEASURED)
    out.append(f"   существует ли рычаг для ACT-дня (заказ #601/G15): {overall}")
    if doc.get("reason"):
        out.append(f"   [ОТВЕТ] {doc['reason']}")
    journal = doc.get("journal") or {}
    if journal:
        out.append(f"   [ЖУРНАЛ] строк {journal.get('lines')}, из них ACT — "
                   f"{journal.get('act_lines')}")
    bounds = doc.get("bounds") or {}
    if bounds:
        out.append(f"   [ГРАНИЦЫ] в журнал возвращается {bounds.get('act_days_recoverable_to_journal')} "
                   f"ACT-дн.; в ОЦЕНЁННЫЙ набор — "
                   f"[{bounds.get('scored_act_days_lower')}, {bounds.get('scored_act_days_upper')}] "
                   f"(ширина {bounds.get('width')}); у владельца "
                   f"{bounds.get('blocked_on_owner_lever')} дн.")
    for day in doc.get("days", []):
        legs = ", ".join(f"{k}{v:+,.0f}" for k, v in
                         sorted((day.get("executed_move", {}).get("legs") or {}).items()))
        out.append(f"   [ПО ДНЯМ] {day.get('date')}: {day.get('state')} · "
                   f"ход {legs} · рычаг: {day.get('lever')}")
        blocking = (day.get("lever_detail") or {}).get("blocking_legs") or []
        if blocking:
            out.append(f"       не оценивается из-за ног без материала: {', '.join(blocking)}")
    parity = doc.get("unit_parity") or {}
    if parity.get("measured") and not parity.get("passed", True):
        out.append("   [ШКАЛА] журнал и ряд говорят в РАЗНЫХ шкалах — вердикты не выносились")
    out.append(f"   {_ADVISORY}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        data_dir: Optional[str] = None, write: bool = True) -> dict:
    """Замер + артефакт. ``write=False`` — посчитать, не трогая диск."""
    base = Path(data_dir) if data_dir else Path(root or ".") / "data"
    doc = measure(base, now=now)
    doc["widening_control"] = widening_control(base, now=now)
    if write:
        atomic_save(doc, str(Path(base) / ARTIFACT))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="G15: существует ли рычаг, возвращающий ACT-день в оценённый набор")
    ap.add_argument("--root", default=".")
    ap.add_argument("--data-dir", default=None,
                    help="каталог data/ (из worktree живого data/ нет по построению)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    args = ap.parse_args(argv)

    doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write)
    for line in format_report(doc):
        print(line)
    # Код возврата — часть ответа: НЕ ИЗМЕРЕНО обязано быть отличимо от «чисто».
    # Незнакомый исход берёт код 2, а не 0: «не узнали, чем кончилось» — это
    # НЕ ИЗМЕРЕНО, и выдавать его за чистый проход запрещено (инв. #17).
    codes = {OVERALL_OK: 0, OVERALL_WARNING: 1,
             OVERALL_CRITICAL: 1, OVERALL_UNMEASURED: 2}
    return codes.get(str(doc.get("overall") or ""), 2)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
