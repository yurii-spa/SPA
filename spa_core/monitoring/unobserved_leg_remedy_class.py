"""КАКОЙ РЫЧАГ поднял бы каждый доллар слепого оборота (заказ #590/G7).

Заказ, оставленный в хвосте ADR-368 по стоячему приказу владельца «Portfolio CIO»:

> Цену слепоты цикл #589 измерил у поверхности решения и назвал адресата, но **не**
> сказал, какой рычаг её снимает. Заказ G7: померить, сколько из $195 000 зависимого
> оборота поднялось бы ОДНОЙ строкой отсечения по universe у писателя журнала
> (ADR-290), а сколько требует живого фида. Сосед считает цену В ДНЯХ и по потолку —
> этот вопрос **в ДОЛЛАРАХ ОБОРОТА** и по двум классам поимённо. Ответ решает, лежит
> ли рычаг в нашей строке кода или в ``POLLED_ADAPTERS`` (money-path, решает
> владелец) — ровно та развилка, на которой приказ стои́т с 13.08.

## Предмет ровно один

**Доллары слепого оборота, разложенные по РЫЧАГУ, который их поднимает.** Не причина,
по которой нога осталась без ставки (предмет ``unevidenced_leg_causes``, заказ #543:
он отвечает в ДНЯХ и КЛАССАХ). Не сама доля слепого оборота (предмет
``unobserved_turnover_dependence``, заказ #587). Не пересчёт ``hit_rate`` и не
суждение о том, был ли HOLD прав.

## Заказ просил ДВА класса — замер нашёл ЧЕТЫРЕ, и это не самоуправство

Заказ назвал развилку «наша строка кода ИЛИ ``POLLED_ADAPTERS``» и в этих двух
классах требовал ответа. Замер 13.09 показал, что между ними лежат ещё два, и каждый
меняет адресата починки:

* нога вне книг форвардного дня, но её **никто не опрашивает** — строка у писателя её
  не поднимет НИ ПРИ КАКОМ состоянии кода: писать в запись нечего. Уложить такой
  доллар в «наша строка» значило бы пообещать починку, которой в нашем коде нет;
* нога в книгах и без живой ставки **под своим ключом**, тогда как ставка того же дня
  лежит в той же записи **под ключом-близнецом**, в который дерево само эту позицию и
  переименовало. Ни фид, ни писатель тут ни при чём — расходятся ДВА ИМЕНИ ОДНИХ
  ДЕНЕГ. Это самый дешёвый рычаг из всех, и он единственный **доказуем записью**.

Поэтому классов четыре, они взаимоисключающи, и сумма их долларов равна ответу
соседа. Свести их обратно к двум значило бы дать верный ответ на не тот вопрос.

## Эпистемический статус у классов РАЗНЫЙ, и он назван у каждого доллара

Складывать «доказано» с «потолком» нельзя, поэтому отчёт их и не складывает:

============================  ==========================  =========================
класс                          рычаг                        статус числа
============================  ==========================  =========================
``key_mismatch``               наш код: свести два имени    **ДОКАЗАНО** (пол=потолок)
``writer_universe``            наш код: строка у писателя   ПОТОЛОК
``needs_polling``              ``POLLED_ADAPTERS`` — владелец  ПОТОЛОК
``feed_outage``                рабочий фид                  ПОТОЛОК
============================  ==========================  =========================

**Почему ``key_mismatch`` доказуем, а остальные — потолок.** Живая ставка
ключа-близнеца лежит в ТОЙ ЖЕ форвардной записи: её существование не предполагается,
а читается. У прочих классов запись молчит о том, существовала ли в тот день живая
ставка у ноги, которой в книгах нет, — и прибор её не выдумывает (конвенция ADR-300:
«класс поднял бы день» есть ПОТОЛОК, а не обещание).

## Ключ-близнец берётся у ДВОЙНОЙ ЗАПИСИ, а не из похожести имён

Соблазн был назвать близнецами ``fluid_usdc`` и ``fluid_fusdc`` по виду строки. Это
было бы третьей копией правила и вдобавок неверной формой: в ``ADAPTER_REGISTRY``
рядом живёт ``fluid_arbitrum``, и по виду имени он такой же близнец, а по деньгам —
нет. Близнецы берутся готовыми у канонического сторожа второй записи
(``scripts/book_second_record.chain_breaks``, род ``renamed_key``): он объявляет
переименованием только тот разрыв цепи ходов, где **суммы равны**, то есть где
деньги доказанно те же. Замер 13.09: T034 2026-09-11, ``['fluid_usdc'] →
['fluid_fusdc']``.

## Опрашиваемость спрашивается у ТОГО, КТО ОПРАШИВАЕТ

``POLLED_ADAPTERS`` (``spa_core.orchestrator.adapter_orchestrator``) — список, который
денежный путь реально обходит. Ни ``ADAPTER_REGISTRY`` (36 кортежей), ни
``ADAPTER_METADATA`` (22 записи) на вопрос «спрашивают ли эту ногу» не отвечают: у
``spark_susds`` и ``fluid_usdc`` класс адаптера ЕСТЬ в реестре, а оркестратор их не
зовёт. Сверить книгу с реестром значило бы получить верный ответ на не тот вопрос
(правило `.claude/rules/adapters.md`, «одно имя — один объект»).

Провенанс ЗНАЧЕНИЯ прибор при этом не спрашивает у дороги: ``adapter_status.json`` он
не читает вовсе — та же граница, что у соседа #543 («пришло не от X» ≠ «не
наблюдалось»).

## День поднимается, только если подняты ВСЕ его отвергающие ноги

Судья метит день ``UNCHECKED``, когда хотя бы одна двигаемая нога осталась без ставки
на КАЖДОМ форвардном дне. Значит рычаг поднимает день тогда и только тогда, когда
после его применения у КАЖДОЙ отвергающей ноги появляется ставка хотя бы на ОДНОМ
форвардном дне. Поэтому доллары дня приписываются НАБОРУ рычагов, а не одному: день
со ногами из разных классов требует их всех, и растворить его в самом дешёвом классе
значило бы удешевить починку на бумаге.

Обратная сторона: ноге довольно ОДНОГО форвардного дня, поэтому у ноги берётся самый
дешёвый из её классов по всем её парам, а не худший.

Доллары берутся днями целиком (``unpriced_gross_usd`` соседа) — величина дневная, и
делить её между ногами внутри дня нельзя по той же причине, по какой сосед публикует
ГРАНИЦЫ: матрицы переводов «откуда куда» журнал не несёт.

ADVISORY. Только stdlib. Прибор ЧИТАЕТ: ни ``POLLED_ADAPTERS``, ни писателя журнала,
ни ``hit_rate``, ни ``MIN_HIT_RATE``, ни пороги RiskPolicy v1.0, ни стоп-кран, ни
живой трек он не трогает. Расширение записи решения и проводка новой ноги —
money-path и решение владельца; этим прибором они не принимаются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное
# имя есть СНИМОК функции на момент импорта, и подмена канонического правила прошла бы
# мимо нас молча. Так же поступают оба соседа по заказу (ADR-366, ADR-368).
from spa_core.monitoring import unevidenced_leg_causes as _causes
from spa_core.monitoring import unobserved_turnover_dependence as _dep
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.unobserved_leg_remedy_class")

OUTPUT_FILENAME = "unobserved_leg_remedy_class.json"
VERSION = "leg-remedy-class-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

# ──────────────────────────────────────────────────────────────────────────
# четыре рычага, взаимоисключающие
# ──────────────────────────────────────────────────────────────────────────
#: Ставка тех же денег лежит в ТОЙ ЖЕ записи под ключом-близнецом. Наш код, и число
#: ДОКАЗАНО записью, а не выдано под потолок.
REMEDY_KEY_MISMATCH = "key_mismatch"
#: Нога вне книг форвардного дня, но её опрашивают ⇒ одна строка отсечения по
#: ``universe`` у писателя (ADR-290) могла бы донести ставку. ПОТОЛОК.
REMEDY_WRITER_UNIVERSE = "writer_universe"
#: Нога вне книг И не опрашивается ⇒ писателю писать нечего. ``POLLED_ADAPTERS``,
#: money-path, решает владелец. ПОТОЛОК.
REMEDY_NEEDS_POLLING = "needs_polling"
#: Нога в книгах, провенанс не ``live``, близнеца нет ⇒ нужен рабочий фид. ПОТОЛОК.
REMEDY_FEED_OUTAGE = "feed_outage"
#: Третий исход: пару разложить не вышло.
REMEDY_UNATTRIBUTABLE = "unattributable"

#: Порядок ДЕШЕВИЗНЫ рычага. Нужен ровно там, где у ноги несколько классов по разным
#: форвардным дням: ноге довольно одного дня со ставкой, поэтому берётся самый дешёвый
#: рычаг, а не худший. Порядок — утверждение о том, ЧЬЁ решение нужно, а не о
#: трудозатратах: два первых наши, третий — владельца.
REMEDY_COST_ORDER = [
    REMEDY_KEY_MISMATCH,
    REMEDY_WRITER_UNIVERSE,
    REMEDY_FEED_OUTAGE,
    REMEDY_NEEDS_POLLING,
    REMEDY_UNATTRIBUTABLE,
]

#: Рычаги, лежащие в НАШЕМ коде. Развилка заказа проходит ровно здесь.
OUR_CODE_REMEDIES = frozenset({REMEDY_KEY_MISMATCH, REMEDY_WRITER_UNIVERSE})
#: Рычаги, требующие решения владельца либо работающего фида (money-path).
OWNER_REMEDIES = frozenset({REMEDY_NEEDS_POLLING, REMEDY_FEED_OUTAGE})

_ADVISORY = ("ADVISORY: `POLLED_ADAPTERS`, писатель журнала, `hit_rate`, "
             "`MIN_HIT_RATE`, пороги RiskPolicy v1.0, стоп-кран и живой трек НЕ "
             "трогаются — прибор только называет рычаг у каждого доллара")

#: Границы утверждения — В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта шапку
#: не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не обещает, что строка у писателя поднимет доллар класса `writer_universe`: "
    "существование живой ставки у ноги ВНЕ книг запись не подтверждает, и это "
    "ПОТОЛОК (конвенция ADR-300), а не план работ",
    "не утверждает, что HOLD на отвергнутых днях был НЕПРАВ, и исход дня не "
    "пересчитывает: рычаг — про наблюдаемость входов, а не про верность решения",
    "не объясняет ПОДКЛАСС перебоя фида (молчал ли фид, вышло ли значение из полосы, "
    "не спросили ли адаптер): запись этого не несёт, а `adapter_status.json` прибор "
    "не читает вовсе",
    "не делит доллары дня между его ногами: величина дневная, матрицы переводов "
    "«откуда куда» журнал не несёт — день целиком приписан НАБОРУ своих рычагов",
    "не принимает ни расширения записи решения, ни проводки новой ноги: и то и "
    "другое money-path и решение владельца",
]

# ──────────────────────────────────────────────────────────────────────────
# исходы, которые НЕ измеряются
# ──────────────────────────────────────────────────────────────────────────
NO_DEPENDENCE = ("сосед `unobserved_turnover_dependence` не дал измеренных дней — "
                 "раскладывать по рычагам нечего, и это НЕ «рычагов нет»")
NO_CAUSES = ("сосед `unevidenced_leg_causes` не дал пар «форвардный день × нога» — "
             "класс ноги неоткуда взять, и самый правдоподобный прибор не выбирает")
NO_POLLED = ("`POLLED_ADAPTERS` не прочитан — опрашиваемость ноги неизвестна, а "
             "«не прочитан» не читается как «не опрашивается»")
DAY_NO_SUBJECT = ("отвергнутый день соседа не несёт списка отвергающих ног либо их "
                  "хода в долларах — раскладывать по рычагам нечего, и пустым "
                  "набором это НЕ читается")
LEG_NO_PAIRS = ("судья назвал ногу отвергающей, а сосед #543 не дал по ней ни одной "
                "пары — два чтения одного дня спорят, и класс ноги не измерен")


def _polled_keys() -> Optional[Set[str]]:
    """Ключи, которые денежный путь РЕАЛЬНО обходит, либо ``None`` = не измерено."""
    try:
        from spa_core.orchestrator import adapter_orchestrator as _orch
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("POLLED_ADAPTERS не прочитан: %s", exc)
        return None
    polled = observed(vars(_orch), "POLLED_ADAPTERS", kind=list)
    if polled is None:
        return None
    keys: Set[str] = set()
    for entry in polled:
        # Кортеж (ключ, тир, класс); пустой список читается как «не измерено» выше,
        # а вот кортеж неожиданной формы — молчаливая потеря ключа, поэтому громко.
        if isinstance(entry, (tuple, list)) and entry:
            keys.add(str(entry[0]))
        else:
            log.warning("POLLED_ADAPTERS несёт запись неожиданной формы: %r", entry)
            return None
    return keys or None


def _twin_keys(data_dir: Path) -> dict:
    """Ключи-близнецы у канонического сторожа ВТОРОЙ ЗАПИСИ, не по виду имени."""
    out: dict = {"measured": False, "pairs": {}, "renames": []}
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_spa_book_second_record",
            Path(__file__).resolve().parents[2] / "scripts" / "book_second_record.py")
        if spec is None or spec.loader is None:
            out["reason"] = "сторож второй записи не загружается — близнецы не измерены"
            return out
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        trades = mod._load(Path(data_dir) / "trades.json")
        if not isinstance(trades, list) or not trades:
            out["reason"] = "журнал ходов пуст — близнецы не измерены"
            return out
        breaks = mod.chain_breaks(trades)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("близнецы не измерены: %s", exc)
        out["reason"] = f"сторож второй записи отказал: {exc}"
        return out

    pairs: Dict[str, Set[str]] = {}
    for brk in breaks:
        if str(brk.get("kind")) != "renamed_key":
            continue
        before = [str(k) for k in (brk.get("keys_only_before") or [])]
        after = [str(k) for k in (brk.get("keys_only_after") or [])]
        # Переименование многие-ко-многим доказательством близнецов НЕ является:
        # какая нога стала какой, двойная запись при равных суммах не различает.
        if len(before) != 1 or len(after) != 1:
            out["renames"].append({"trade_id": brk.get("trade_id"),
                                   "before": before, "after": after,
                                   "used": False,
                                   "why": "не один-к-одному — чей это близнец, "
                                          "двойная запись не различает"})
            continue
        pairs.setdefault(before[0], set()).add(after[0])
        pairs.setdefault(after[0], set()).add(before[0])
        out["renames"].append({"trade_id": brk.get("trade_id"),
                               "before": before, "after": after, "used": True})
    out["measured"] = True
    out["pairs"] = {k: sorted(v) for k, v in sorted(pairs.items())}
    return out


def _live_keys_of(record: Optional[dict]) -> Set[str]:
    """Ключи с живой ставкой в записи форвардного дня."""
    if not isinstance(record, dict):
        return set()
    evidenced = observed(record, "apy_evidenced_pct", kind=dict)
    if evidenced is None:
        return set()
    return {str(k) for k, v in evidenced.items()
            if v is not None and not isinstance(v, bool)}


def _pair_remedy(pair: dict, *, polled: Set[str], twins: Dict[str, List[str]],
                 forward_record: Optional[dict]) -> dict:
    """Рычаг ОДНОЙ пары «форвардный день × нога» — с названной опорой."""
    protocol = str(pair.get("protocol"))
    klass = str(pair.get("class"))

    # Близнец проверяется ПЕРВЫМ и при ЛЮБОМ классе, потому что вопрос у него свой:
    # «лежит ли ставка ТЕХ ЖЕ денег в этой самой записи под другим именем». Замер
    # 13.09 показал, почему порядок решает: `fluid_usdc` 2026-09-10 значится ВНЕ книг
    # (`absent_from_forward_books`) ровно потому, что дерево переименовало позицию в
    # `fluid_fusdc`, и та в той же записи имеет живую ставку. Спрашивать близнеца
    # только у класса «в книгах, но не live» значило бы записать эти доллары в
    # проводку новой ноги — то есть отправить владельцу починку, которая целиком
    # лежит в нашем коде.
    live = _live_keys_of(forward_record)
    for twin in twins.get(protocol, []):
        if twin in live:
            return {"remedy": REMEDY_KEY_MISMATCH, "twin": twin,
                    "why": (f"ставка тех же денег лежит в ТОЙ ЖЕ записи под "
                            f"ключом-близнецом `{twin}` (переименование доказано "
                            f"двойной записью, суммы равны) ⇒ расходятся два имени "
                            f"одних денег, и рычаг не в фиде и не у писателя")}

    if klass == _causes.CLASS_ABSENT:
        if protocol in polled:
            return {"remedy": REMEDY_WRITER_UNIVERSE,
                    "why": ("нога вне книг форвардного дня, но её опрашивают ⇒ "
                            "строка отсечения по universe у писателя могла бы "
                            "донести ставку (ПОТОЛОК)")}
        return {"remedy": REMEDY_NEEDS_POLLING,
                "why": ("нога вне книг форвардного дня И не опрашивается ⇒ писателю "
                        "писать нечего: рычаг в POLLED_ADAPTERS, money-path")}

    if klass in (_causes.CLASS_NOT_LIVE, _causes.CLASS_LIVE_NULL):
        return {"remedy": REMEDY_FEED_OUTAGE,
                "why": ("нога в книгах, провенанс не `live`, близнеца со ставкой в "
                        "записи нет ⇒ нужен рабочий фид")}

    return {"remedy": REMEDY_UNATTRIBUTABLE,
            "why": f"класс пары `{klass}` не раскладывается на рычаг"}


def _cheapest(remedies: List[str]) -> str:
    """Самый дешёвый рычаг ноги: ей довольно ОДНОГО форвардного дня со ставкой."""
    for remedy in REMEDY_COST_ORDER:
        if remedy in remedies:
            return remedy
    return REMEDY_UNATTRIBUTABLE


def measure(data_dir: Path, *, now: Optional[datetime] = None, **_ignored) -> dict:
    """Разложить доллары слепого оборота по рычагам. Только чтение.

    ``_ignored`` — совместимость с зовущей ступенью переписей, которая передаёт общие
    для всех приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни один из
    них не участвует в замере: появись здесь значащий параметр, он обязан быть назван
    явно, а не прийти через эту дверь.
    """
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "subject": ("какой РЫЧАГ поднял бы каждый доллар слепого оборота "
                    "(заказ #590/G7 приказа «Portfolio CIO»)"),
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }

    polled = _polled_keys()
    if polled is None:
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": NO_POLLED,
                    "answer": None, "per_day": [],
                    "findings": [f"[НЕ ИЗМЕРЕНО] {NO_POLLED}"]})
        return doc
    doc["polled_adapters"] = sorted(polled)

    dep = _dep.measure(data_dir, now=now)
    doc["dependence_status"] = dep.get("status")
    dep_days = observed(dep, "per_day", kind=list) or []
    if not dep_days:
        why = f"{NO_DEPENDENCE} (вердикт соседа: {dep.get('status')})"
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None, "per_day": [], "findings": [f"[НЕ ИЗМЕРЕНО] {why}"]})
        return doc

    causes = _causes.measure(data_dir, now=now)
    doc["causes_status"] = causes.get("status")
    pairs = observed(causes, "attribution", kind=list)
    if pairs is None:
        why = f"{NO_CAUSES} (вердикт соседа: {causes.get('status')})"
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None, "per_day": [], "findings": [f"[НЕ ИЗМЕРЕНО] {why}"]})
        return doc

    twins_doc = _twin_keys(data_dir)
    doc["twin_keys"] = twins_doc
    twins: Dict[str, List[str]] = twins_doc.get("pairs") or {}

    history, _bad_lines = _dep._ste.load_history(data_dir)  # строки-мусор — предмет соседа
    by_date = {str(r.get("cycle_date")): r for r in history}

    by_day_leg: Dict[str, Dict[str, List[dict]]] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        day = str(pair.get("decision_date"))
        leg = str(pair.get("protocol"))
        verdict = _pair_remedy(
            pair, polled=polled, twins=twins,
            forward_record=by_date.get(str(pair.get("forward_date"))))
        verdict.update({"forward_date": pair.get("forward_date"),
                        "class": pair.get("class")})
        by_day_leg.setdefault(day, {}).setdefault(leg, []).append(verdict)

    per_day: List[dict] = []
    unmeasured_days: List[dict] = []
    for dep_day in dep_days:
        date = str(dep_day.get("cycle_date"))
        # Список отвергающих ног, которого НЕТ, — это «не измерено», а не «ног нет».
        # Подставив пустой список, прибор объявил бы день поднятым ЦЕЛИКОМ и без
        # единого рычага: слепые доллары молча уехали бы в «наш код» (инв. #17).
        raw_legs = observed(dep_day, "unpriced_protocols", kind=list)
        gross = dep_day.get("unpriced_gross_usd")
        if raw_legs is None or gross is None:
            unmeasured_days.append({"cycle_date": date, "reason": DAY_NO_SUBJECT})
            continue
        legs = [str(p) for p in raw_legs]
        leg_rows: List[dict] = []
        blocked: Optional[str] = None
        for leg in legs:
            verdicts = (by_day_leg.get(date) or {}).get(leg) or []
            if not verdicts:
                blocked = f"{leg}: {LEG_NO_PAIRS}"
                break
            leg_rows.append({
                "protocol": leg,
                "remedy": _cheapest([v["remedy"] for v in verdicts]),
                "pair_remedies": sorted({v["remedy"] for v in verdicts}),
                "pairs": verdicts,
            })
        if blocked is not None:
            unmeasured_days.append({"cycle_date": date, "reason": blocked})
            continue

        needed = sorted({row["remedy"] for row in leg_rows})
        per_day.append({
            "cycle_date": date,
            "unpriced_gross_usd": gross,
            "turnover_usd": dep_day.get("turnover_usd"),
            "legs": leg_rows,
            # День поднимается, только если подняты ВСЕ его ноги ⇒ ему нужен НАБОР.
            "remedies_required": needed,
            "lever_owner": ("наш код" if set(needed) <= OUR_CODE_REMEDIES
                            else "владелец / фид" if set(needed) <= OWNER_REMEDIES
                            else "смешанный — нужны оба"),
            # Доказан день только тогда, когда доказана КАЖДАЯ его нога.
            "proven": needed == [REMEDY_KEY_MISMATCH],
        })

    doc["per_day"] = per_day
    doc["population"] = {
        "dependence_days": len(dep_days),
        "measured_days": len(per_day),
        "unmeasured_days": unmeasured_days,
        "attribution_pairs": len(pairs),
        # Тождество истинно ПО ПОСТРОЕНИЮ и само по себе не доказывает ничего; ценно
        # тем, что уронить день МОЛЧА нельзя — падение обязано быть громким.
        "accounting_identity_holds": len(per_day) + len(unmeasured_days) == len(dep_days),
    }

    if not per_day:
        why = ("ни один день соседа не разложен по рычагам — причины названы "
               "поимённо в population.unmeasured_days")
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None})
        doc["findings"] = _findings(doc)
        return doc

    by_remedy: Dict[str, float] = {}
    for day in per_day:
        # Доллары дня НЕ делятся между рычагами: день требует их все, и разложить
        # его между классами значило бы выдумать деление, которого журнал не несёт.
        for remedy in day["remedies_required"]:
            by_remedy[remedy] = by_remedy.get(remedy, 0.0) + float(day["unpriced_gross_usd"])

    total = sum(float(d["unpriced_gross_usd"]) for d in per_day)
    our_code = sum(float(d["unpriced_gross_usd"]) for d in per_day
                   if set(d["remedies_required"]) <= OUR_CODE_REMEDIES)
    owner = sum(float(d["unpriced_gross_usd"]) for d in per_day
                if not set(d["remedies_required"]) <= OUR_CODE_REMEDIES)
    proven = sum(float(d["unpriced_gross_usd"]) for d in per_day if d["proven"])

    doc["answer"] = {
        "measured": True,
        "blind_turnover_usd": round(total, 2),
        "our_code_usd": round(our_code, 2),
        "our_code_pct": round(our_code / total * 100.0, 2) if total else None,
        "owner_lever_usd": round(owner, 2),
        "owner_lever_pct": round(owner / total * 100.0, 2) if total else None,
        "proven_usd": round(proven, 2),
        "ceiling_usd": round(total - proven, 2),
        # Сумма по рычагам БОЛЬШЕ итога, когда дню нужен не один рычаг. Это не ошибка
        # и не двойной счёт: доллар не делится, он требует обоих.
        "usd_by_remedy": {k: round(v, 2) for k, v in sorted(by_remedy.items())},
        "days_by_remedy_set": sorted(
            {", ".join(d["remedies_required"]) for d in per_day}),
    }
    doc["status"] = _status(doc)
    doc["findings"] = _findings(doc)
    return doc


def _status(doc: dict) -> str:
    if not (doc.get("population") or {}).get("accounting_identity_holds", True):
        return STATUS_UNMEASURED
    answer = doc.get("answer") or {}
    if not answer.get("measured"):
        return STATUS_UNMEASURED
    per_day = doc.get("per_day") or []
    if any(REMEDY_UNATTRIBUTABLE in d["remedies_required"] for d in per_day):
        return STATUS_UNMEASURED
    # Доллар, который наш код поднять не может, — находка: он ЖДЁТ ВЛАДЕЛЬЦА, и
    # молчать о нём значило бы обещать починку, которой у нас нет.
    if answer.get("owner_lever_usd"):
        return STATUS_CRITICAL
    if (doc.get("population") or {}).get("unmeasured_days"):
        return STATUS_WARNING
    if not (doc.get("twin_keys") or {}).get("measured"):
        return STATUS_WARNING
    return STATUS_OK


def _findings(doc: dict) -> List[str]:
    out: List[str] = []
    answer = doc.get("answer") or {}
    pop = doc.get("population") or {}

    if not answer.get("measured"):
        why = doc.get("unmeasured_reason") or "причина не названа"
        return [f"[НЕ ИЗМЕРЕНО] {why}"]

    out.append(
        f"[ОТВЕТ] из ${answer['blind_turnover_usd']:,.2f} слепого оборота наш код "
        f"поднимает ${answer['our_code_usd']:,.2f} ({answer['our_code_pct']:.2f} %), "
        f"а ${answer['owner_lever_usd']:,.2f} ({answer['owner_lever_pct']:.2f} %) "
        f"нашим кодом не поднимаются НИ ПРИ КАКОМ его состоянии — это фид либо "
        f"проводка POLLED_ADAPTERS, money-path и решение владельца")
    out.append(
        f"[СТАТУС ЧИСЛА] доказано записью ${answer['proven_usd']:,.2f}; остальные "
        f"${answer['ceiling_usd']:,.2f} — ПОТОЛОК: существование живой ставки у ноги "
        f"вне книг запись не подтверждает и прибор её не выдумывает (ADR-300)")

    by_remedy = observed(answer, "usd_by_remedy", kind=dict)
    if by_remedy is None:
        out.append("[НЕ ИЗМЕРЕНО] разложение по рычагам отсутствует в ответе — "
                   "печатать пустую разбивку значило бы выдать её за измеренный ноль")
        by_remedy = {}
    for remedy, usd in by_remedy.items():
        out.append(f"[ПО РЫЧАГАМ] {remedy}: ${usd:,.2f}")
    if len(by_remedy) > 1:
        out.append("[ОПОРА] суммы по рычагам БОЛЬШЕ итога там, где дню нужен не один "
                   "рычаг: доллар не делится между рычагами, он требует их обоих — "
                   "это не двойной счёт")

    for day in doc.get("per_day") or []:
        legs = ", ".join(f"{r['protocol']}→{r['remedy']}" for r in day["legs"])
        out.append(
            f"[ПО ДНЯМ] {day['cycle_date']}: ${float(day['unpriced_gross_usd']):,.2f} · "
            f"{legs} · рычаг: {day['lever_owner']}")

    twins = doc.get("twin_keys") or {}
    if twins.get("measured") and twins.get("pairs"):
        named = "; ".join(f"{k} ↔ {', '.join(v)}" for k, v in twins["pairs"].items())
        out.append(f"[ОПОРА] близнецы взяты у двойной записи, не по виду имени: {named}")
    elif not twins.get("measured"):
        out.append(f"[НЕ ИЗМЕРЕНО] близнецы: {twins.get('reason') or 'причина не названа'}")

    owner_days = [d for d in (doc.get("per_day") or [])
                  if not set(d["remedies_required"]) <= OUR_CODE_REMEDIES]
    if owner_days:
        named = ", ".join(f"{d['cycle_date']} (${float(d['unpriced_gross_usd']):,.2f})"
                          for d in owner_days)
        out.append(
            f"[CRITICAL] развилка приказа РАЗРЕШЕНА замером и не в одну сторону: "
            f"{len(owner_days)} дн. слепоты нашей строкой не чинятся — {named}. "
            f"Рычаг там у владельца (POLLED_ADAPTERS / фид), и пока он не сдвинут, "
            f"эти доллары остаются слепыми при ЛЮБОЙ починке писателя")

    bad_days = observed(pop, "unmeasured_days", kind=list)
    if bad_days is None:
        out.append("[НЕ ИЗМЕРЕНО] перечня неизмеренных дней в населении нет — "
                   "молчание здесь неотличимо от «неизмеренных дней не было»")
        bad_days = []
    for bad in bad_days:
        out.append(f"[НЕ ИЗМЕРЕНО] {bad['cycle_date']}: {bad['reason']}")

    out.append("НЕ ДОКЛАДЫВАЕТ: подкласс перебоя фида и верность исхода дня — "
               "границы названы в `what_it_does_not_prove`")
    return out


def format_report(doc: dict) -> List[str]:
    out = [f"   какой рычаг поднял бы слепой оборот (заказ #590/G7): {doc.get('status')}"]
    out.extend(f"   {line}" for line in (doc.get("findings") or []))
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
                    or x.startswith("[ПО ДНЯМ]") or x.startswith("[ПО РЫЧАГАМ]")
                    or x.startswith("[ОПОРА]") or x.startswith("[СТАТУС ЧИСЛА]")),
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
        description=("какой рычаг поднял бы каждый доллар слепого оборота "
                     "(заказ #590/G7 приказа «Portfolio CIO»)"))
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
