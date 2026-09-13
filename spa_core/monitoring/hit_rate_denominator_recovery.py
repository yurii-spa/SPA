"""Сколько ДНЕЙ вернул бы знаменателю ``hit_rate`` рычаг `writer_universe` (заказ #591/G8).

Заказ, оставленный в хвосте ADR-369 по стоячему приказу владельца «Portfolio CIO»:

> G7 назвал рычаги и их цену в долларах. Осталась ровно одна неизмеренная величина, без
> которой владельцу нечего предъявить по предмету №1: **сколько дней знаменателя
> ``hit_rate`` вернулось бы, если бы рычаг ``writer_universe`` был применён.** ADR-368 и
> тот замер отвечают в долларах ОБОРОТА; критерий взвода живёт в ДНЯХ, и сосед #543 уже
> печатает потолок «перепись входов поднимает 8 из 8 дней». Заказ G8: свести это в одно
> утверждение — **знаменатель 16 дн. → сколько**, и с каким ``hit_rate``, если вердикты
> под сентинелом НЕ печатать (ADR-300 прямо это запрещает, значит ответ обязан быть о
> РАЗМЕРЕ знаменателя, а не о значении критерия).

## Предмет ровно один

**Мощность знаменателя ``hit_rate`` — в днях — под применённым рычагом.** Не число
``UNCHECKED``-дней (предмет ``g1_verdict_recoverability``, заказ #541: там рычаг другой —
``POLLED_ADAPTERS``, и единица «день получил вердикт»). Не доллары слепого оборота
(предмет ``unobserved_leg_remedy_class``, заказ #590). Не значение ``hit_rate`` — оно не
считается вовсе и это закреплено тестом.

**«День перестал быть UNCHECKED» и «день вошёл в знаменатель» — РАЗНЫЕ утверждения**, и
второе не следует из первого: знаменатель — это ``not trivial and outcome in (hit, miss)``
(``shadow_trigger_eval.evaluate_window``), то есть у дня обязаны быть и существенный ход,
и разобранный вердикт. Прибор меряет ВТОРОЕ, потому что именно второе есть население
критерия взвода.

## Почему ответ о РАЗМЕРЕ, а не о значении

``hit_rate`` — не приборная величина, а критерий взвода (``MIN_HIT_RATE`` = 0.60, мандат
владельца ADR-067). Сегодня он предъявлен как ``PASS`` = 1.0. Конвенция ADR-300 запрещает
печатать вердикт, полученный под сентинелом: исход ``hit``/``miss`` у поднятого дня есть
артефакт сентинела, а не наблюдение. Поэтому утверждение, которое прибор ИМЕЕТ ПРАВО
сделать, ровно одно и оно о мощности: **на скольких днях из достижимых сегодня посчитан
проходящий критерий.** Доля «16 из 24» — утверждение о населении; «1.0 стало бы X» —
выдумка, и её здесь нет.

## Возмущение выдаёт ПРАВО БЫТЬ ОЦЕНЁННЫМ, а не доходность

Сентинел ``_PRICING_SENTINEL_PCT`` = 0.0 берётся у соседа #541 по ссылке на модуль:
вклад ноги в ``benefit`` при нём равен РОВНО НУЛЮ, то есть нога становится оценимой и
никакой выдуманной ставки в числа не попадает. Исключение ровно одно и оно в сторону
БОЛЬШЕЙ правды: рычагу ``key_mismatch`` выдаётся не сентинел, а **живая ставка
ключа-близнеца из той же самой записи** — она наблюдена, а не предположена (G7 поэтому и
называет этот класс единственным доказанным).

## Рычаги ИЗМЕРЕНЫ у канонических производителей, здесь их списков нет

* ``writer_universe`` — «одна строка отсечения по ``universe`` у писателя» (ADR-290)
  означает, что запись дня несёт ставки всего ОПРАШИВАЕМОГО набора, а не только книги.
  Набор берётся у того, кто опрашивает: ``POLLED_ADAPTERS`` через
  ``unobserved_leg_remedy_class._polled_keys`` (не ``ADAPTER_REGISTRY``, не
  ``ADAPTER_METADATA`` — правило `.claude/rules/adapters.md`);
* ``key_mismatch`` — близнецы у сторожа ВТОРОЙ ЗАПИСИ
  (``unobserved_leg_remedy_class._twin_keys``, род ``renamed_key``: суммы равны), а не по
  виду имени;
* ``ceiling`` — ВСЕ ноги, блокирующие хоть один день, измерены из самого журнала.

Второй копии ни одного из этих списков в файле нет намеренно: копия разошлась бы с
оригиналом молча.

## Две ЧИТКИ рычага писателя, и обе измерены

Писатель сам метит часть ног ``apy_unevidenced`` — «я эту ногу видел, живого провенанса
у значения нет». Выдать такой ноге ставку значило бы перебить собственное живое суждение
писателя (ровно то, что ``journal_population_backfill`` отказывается делать по условию
владельца). Поэтому читки две:

* ``respecting`` — опрашиваемый набор МИНУС то, что писатель в тот день сам объявил
  неэвиденсным. Это и есть рычаг писателя в чистом виде;
* ``overriding`` — опрашиваемый набор целиком (перебивая суждение писателя). Верхняя
  чтение, и держится оно ради ЧУВСТВИТЕЛЬНОСТИ: в G7 порядок проверки сдвинул ответ с
  74.36 % на 94.87 %, и вопрос «а не держится ли число на спорном шаге» обязан быть
  ЗАМЕРЕН, а не отвечен словами.

Расхождение читок — не отказ, а **измеренная величина**, и она печатается.

## Дню довольно ОДНОГО форвардного дня — и отсюда граница относительно G7

Судья выносит вердикт при ``checked >= 1``: дню достаточно, чтобы ВСЕ его двигаемые ноги
оказались оценены на ОДНОМ И ТОМ ЖЕ форвардном дне. Сосед G7 берёт у ноги самый дешёвый
рычаг по ВСЕМ её парам и объединяет рычаги ног дня. Это разные вопросы, и потому
``remedies_required`` соседа — НЕОБХОДИМОЕ, но не достаточное условие подъёма дня:
сверка с соседом ведётся ОДНОСТОРОННЕ (день, которому сосед назначил рычаг вне нашего
кода, обязан НЕ подниматься нашим кодом), а обратное не утверждается.

## Контроли (не сработал ⇒ UNMEASURED, а не «ноль»)

* **ПАРИТЕТ-1.** Базовый знаменатель обязан совпасть с каноническим
  ``shadow_trigger_eval.scored_days`` — тем самым правилом отбора, которое читают все
  остальные. Своё второе определение знаменателя было бы молчаливым спором о том же дне.
* **ПАРИТЕТ-2.** При ПУСТОМ наборе возмущённый реплей обязан воспроизвести исход
  настоящего ``_evaluate_verdict`` бит в бит по каждому дню. Не сошлось ⇒ копирование
  записей врёт.
* **МОНОТОННОСТЬ.** Выдача ставок может только ДОБАВЛЯТЬ дни в знаменатель. Если день из
  базового знаменателя под возмущением из него выпал — возмущение мерит не тот путь.
* **СПОСОБНОСТЬ.** Потолок обязан поднять хотя бы один день, иначе ноль по рычагу —
  вакуум: неотличимо «рычаг не тот» от «прибор не поднимает никогда».
* **ДВА ВЫВОДА.** Структурный (ноги ⊆ выданного набора на одном форвардном дне, при
  существенном ходе и разобранном вердикте) и реплей настоящего судьи обязаны совпасть
  по каждому дню каждого сценария.

**ADVISORY.** Прибор ЧИТАЕТ. ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель
журнала, ``POLLED_ADAPTERS``, пороги RiskPolicy v1.0, стоп-кран, живой трек и ``landing/``
не трогаются; капитал не двигается. Расширение записи решения и проводка новой ноги —
money-path и решение владельца, и этим прибором они не принимаются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное имя
# есть СНИМОК функции на момент импорта, и подмена канонического правила прошла бы мимо
# нас молча. Так же поступают все соседи по этому заказу (ADR-366/368/369).
from spa_core.monitoring import g1_verdict_recoverability as _g1
from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.hit_rate_denominator_recovery")

OUTPUT_FILENAME = "hit_rate_denominator_recovery.json"
VERSION = "hit-rate-denominator-recovery-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Сценарии — имена ответа. Порядок = порядок изложения в отчёте.
SC_WRITER = "writer_universe"
SC_WRITER_OVERRIDING = "writer_universe_overriding"
SC_KEY_MISMATCH = "key_mismatch"
SC_OUR_CODE = "our_code"
SC_CEILING = "ceiling_all_blocking"

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `TriggerParams`, писатель журнала, "
             "`POLLED_ADAPTERS`, пороги RiskPolicy v1.0, стоп-кран и живой трек НЕ "
             "трогаются — прибор только считает МОЩНОСТЬ знаменателя под рычагом")

#: Границы утверждения едут В АРТЕФАКТЕ, а не только в шапке модуля: читатель отчёта
#: шапку не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не печатает `hit_rate` под возмущением и не печатает исход НИ ОДНОГО поднятого дня: "
    "под сентинелом это артефакт сентинела, а не наблюдение (конвенция ADR-300). "
    "Утверждение прибора — о РАЗМЕРЕ знаменателя",
    "не обещает, что живая ставка у ноги в тот день СУЩЕСТВОВАЛА: запись этого не несёт, "
    "и `writer_universe` остаётся ПОТОЛКОМ, а не планом работ",
    "не утверждает, что вердикты поднятых дней были бы верны или что HOLD был неправ",
    "не пересчитывает доллары соседа G7 и не поправляет его классы: у него другой "
    "предмет (доллары оборота) и другое правило объединения ног",
    "не принимает ни строки у писателя, ни проводки ноги: и то и другое money-path и "
    "решение владельца",
]

# ── исходы, которые НЕ измеряются ────────────────────────────────────────────
NO_JOURNAL = ("журнал решений пуст или не прочитан — населения вопроса нет, и это НЕ "
              "«знаменатель нулевой»")
NO_POLLED = ("`POLLED_ADAPTERS` не прочитан — набор рычага `writer_universe` неизвестен; "
             "«не прочитан» не читается как «опрашивать нечего»")
NO_CANON = ("канонический знаменатель (`shadow_trigger_eval.scored_days`) не измерен — "
            "сверять свой отбор не с чем, а второе определение знаменателя заводить "
            "запрещено")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── чтение записи ────────────────────────────────────────────────────────────
def writer_unevidenced_keys(record: dict) -> Set[str]:
    """Ноги, которые ПИСАТЕЛЬ в тот день сам объявил без живого провенанса.

    Форма поля в журнале не одна (замер 13.09: список строк; встречается и карта),
    поэтому разбираются обе, а неизвестная форма даёт ПУСТОЕ множество — то есть
    читка ``respecting`` в сомнительном случае ведёт себя как ``overriding`` и
    расхождение читок становится ВИДНЫМ, вместо того чтобы быть замятым.
    """
    raw = record.get("apy_unevidenced")
    out: Set[str] = set()
    if isinstance(raw, dict):
        return {str(k) for k in raw}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict):
                for key in ("protocol", "key", "name"):
                    if item.get(key):
                        out.add(str(item[key]))
                        break
    return out


def _live_rate_map(record: dict) -> Dict[str, float]:
    """Ставки с живым провенансом в записи дня (``{}`` и отсутствия поля — один исход)."""
    evidenced = observed(record, "apy_evidenced_pct", kind=dict) or {}
    return {str(k): v for k, v in evidenced.items()
            if v is not None and not isinstance(v, bool)}


# ── возмущение ───────────────────────────────────────────────────────────────
def perturb(records: Dict[str, dict], *, polled: Set[str], twins: Dict[str, List[str]],
            grant_polled: bool, respect_writer: bool, grant_twin: bool,
            extra_keys: Optional[Set[str]] = None) -> Dict[str, dict]:
    """Копии записей, где выбранным ногам выдано ПРАВО быть оценёнными.

    Копия глубокая: возмущение не смеет тронуть записи, по которым считается базовая
    линия, — иначе паритет сравнивал бы возмущённое с возмущённым и проходил бы всегда.
    """
    out: Dict[str, dict] = {}
    for date, record in records.items():
        clone = copy.deepcopy(record)
        apy = observed(clone, "apy_evidenced_pct", kind=dict)
        apy = dict(apy) if apy is not None else {}

        if grant_twin:
            # Не сентинел: ставка ТЕХ ЖЕ денег, лежащая в ЭТОЙ ЖЕ записи под другим
            # именем. Она наблюдена, и выдавать вместо неё ноль значило бы стереть
            # единственное доказанное наблюдение из всех четырёх рычагов.
            live = _live_rate_map(clone)
            for key, mates in twins.items():
                if apy.get(key) is not None:
                    continue
                for mate in mates:
                    if live.get(mate) is not None:
                        apy[key] = live[mate]
                        break

        granted: Set[str] = set(extra_keys or set())
        if grant_polled:
            granted |= (polled - writer_unevidenced_keys(clone)) if respect_writer else polled
        for key in granted:
            if apy.get(key) is None:
                apy[key] = _g1._PRICING_SENTINEL_PCT

        clone["apy_evidenced_pct"] = apy
        out[date] = clone
    return out


# ── знаменатель ──────────────────────────────────────────────────────────────
def _judge_all(records: Dict[str, dict], horizon: int) -> Dict[str, dict]:
    """Исход настоящего судьи по каждому дню (forward — соседи по той же карте)."""
    order = sorted(records)
    rows: Dict[str, dict] = {}
    for i, date in enumerate(order):
        forward = [records[x] for x in order[i + 1:i + 1 + horizon]]
        rows[date] = _ste._evaluate_verdict(records[date], forward, horizon)
    return rows


def in_denominator(row: dict) -> bool:
    """Правило отбора знаменателя — ОДНО, и оно процитировано у автора знаменателя.

    ``shadow_trigger_eval.evaluate_window``: ``not trivial and outcome in (hit, miss)``.
    Своё второе определение спорило бы с каноническим молча (обе стороны печатают
    число, ни одна — правило), поэтому сверка с ``scored_days`` обязательна и её отказ
    есть третий исход, а не «знаменатель пуст».
    """
    return (not row.get("trivial")) and row.get("outcome") in ("hit", "miss")


def _denominator(rows: Dict[str, dict]) -> Set[str]:
    return {date for date, row in rows.items() if in_denominator(row)}


def _structural_member(record: dict, forward: List[dict], horizon: int) -> bool:
    """Вывод №1 — по ФОРМЕ входа, без вызова судьи.

    День попадает в знаменатель, когда (а) у него есть записанная цель, (б) ход
    существенен и (в) найдётся форвардный день, на котором оценены ВСЕ двигаемые ноги,
    и (г) вердикт разобран. Условия названы здесь порознь именно потому, что реплей
    сворачивает их в один ответ, а разойтись они могут в любом из четырёх мест.
    """
    if (record.get("current_positions") or {}) and not (record.get("target_positions") or {}):
        return False
    deltas = _ste._deltas(record)
    turnover = _ste._turnover_usd(record, deltas)
    if not (bool(deltas) and turnover >= _ste.MATERIAL_TURNOVER_USD):
        # Тривиальный день ВЫНОСИТ исход hit/miss, но в знаменатель не входит.
        return False
    if str(record.get("verdict") or "UNKNOWN").upper() not in ("ACT", "HOLD"):
        return False
    for frec in list(forward)[:horizon]:
        apy = observed(frec, "apy_evidenced_pct", kind=dict) or {}
        if not [p for p in deltas if apy.get(p) is None]:
            return True
    return False


def _structural_denominator(records: Dict[str, dict], horizon: int) -> Set[str]:
    order = sorted(records)
    out: Set[str] = set()
    for i, date in enumerate(order):
        forward = [records[x] for x in order[i + 1:i + 1 + horizon]]
        if _structural_member(records[date], forward, horizon):
            out.add(date)
    return out


# ── замер ────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: Optional[int] = None, book_id: Optional[str] = None,
            **_ignored) -> dict:
    """Ответ заказу #591: мощность знаменателя ``hit_rate`` под каждым рычагом.

    ``_ignored`` — совместимость со ступенью переписей, которая передаёт общие для всех
    приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни один не участвует в
    замере: появись здесь значащий параметр, он обязан быть назван явно.
    """
    data_dir = Path(data_dir)
    horizon = int(horizon_days or _ste.DEFAULT_HORIZON_DAYS)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or _utcnow()).isoformat(),
        "subject": ("сколько ДНЕЙ вернул бы знаменателю `hit_rate` рычаг "
                    "`writer_universe` (заказ #591/G8 приказа «Portfolio CIO»)"),
        "unit": "дни знаменателя hit_rate (не UNCHECKED-дни и не доллары)",
        "horizon_days": horizon,
        "status": STATUS_UNMEASURED,
        "findings": [],
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }
    f: List[str] = doc["findings"]

    # ── вход 1: журнал решений ───────────────────────────────────────────────
    try:
        history, bad_lines = _ste.load_history(data_dir, book_id)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        doc["unmeasured_reason"] = f"{NO_JOURNAL} ({type(exc).__name__}: {exc})"
        f.append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
        return doc
    if not history:
        doc["unmeasured_reason"] = NO_JOURNAL
        f.append(f"[НЕ ИЗМЕРЕНО] {NO_JOURNAL}")
        return doc
    records = {str(r.get("cycle_date")): r for r in history}
    doc["journal"] = {"rows": len(history), "unparseable": bad_lines,
                      "days": len(records)}

    # ── вход 2: опрашиваемый набор ───────────────────────────────────────────
    polled = _remedy._polled_keys()
    if polled is None:
        doc["unmeasured_reason"] = NO_POLLED
        f.append(f"[НЕ ИЗМЕРЕНО] {NO_POLLED}")
        return doc
    doc["polled_adapters"] = sorted(polled)

    # ── вход 3: близнецы у сторожа ВТОРОЙ ЗАПИСИ ─────────────────────────────
    twins_doc = _remedy._twin_keys(data_dir)
    twins: Dict[str, List[str]] = twins_doc.get("pairs") or {}
    doc["twin_keys"] = {"measured": twins_doc.get("measured"),
                        "pairs": twins_doc.get("pairs"),
                        "reason": twins_doc.get("reason")}

    # ── базовая линия ────────────────────────────────────────────────────────
    baseline_rows = _judge_all(records, horizon)
    baseline = _denominator(baseline_rows)

    # ПАРИТЕТ-1: свой отбор против КАНОНИЧЕСКОГО правила знаменателя.
    canon = _ste.scored_days(data_dir, horizon_days=horizon)
    doc["canonical_parity"] = {
        "canonical_measured": canon is not None,
        "canonical_size": None if canon is None else len(canon),
        "own_size": len(baseline),
        "passed": canon is not None and canon == baseline,
        "only_canonical": sorted((canon or set()) - baseline) if canon else [],
        "only_own": sorted(baseline - (canon or set())) if canon else [],
        "what_it_proves": ("знаменатель отбирается ТЕМ ЖЕ правилом, что читают все "
                           "остальные потребители, а не вторым определением"),
    }
    if canon is None:
        doc["unmeasured_reason"] = NO_CANON
        f.append(f"[НЕ ИЗМЕРЕНО] {NO_CANON}")
        return doc
    if canon != baseline:
        doc["unmeasured_reason"] = (
            f"базовый знаменатель ({len(baseline)}) разошёлся с каноническим "
            f"({len(canon)}) — числам ниже верить нельзя")
        f.append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
        return doc

    # ПАРИТЕТ-2: пустой набор обязан воспроизвести судью бит в бит.
    empty_rows = _judge_all(
        perturb(records, polled=polled, twins=twins, grant_polled=False,
                respect_writer=True, grant_twin=False), horizon)
    parity_mismatch = [d for d in records if empty_rows.get(d) != baseline_rows.get(d)]
    doc["copy_parity"] = {
        "passed": not parity_mismatch,
        "days_compared": len(records),
        "mismatch_days": sorted(parity_mismatch)[:10],
        "what_it_proves": ("возмущение копирует записи ЧЕСТНО: при пустом наборе реплей "
                           "= настоящий _evaluate_verdict бит в бит"),
    }
    if parity_mismatch:
        doc["unmeasured_reason"] = (f"контроль паритета копирования не прошёл на "
                                    f"{len(parity_mismatch)} дн.")
        f.append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
        return doc

    # ── население вопроса: дни вне знаменателя и почему ──────────────────────
    outside = sorted(set(records) - baseline)
    blocking_legs: Set[str] = set()
    recoverable_in_principle: List[str] = []
    beyond: List[dict] = []
    no_blocking_list: List[str] = []
    for date in outside:
        row = baseline_rows[date]
        reason = str(row.get("unchecked_reason") or "")
        if row.get("outcome") == "UNCHECKED" and reason == _g1._REASON_RECOVERABLE:
            recoverable_in_principle.append(date)
            # Список отвергающих ног, которого НЕТ, — это «не измерено», а не «ног нет».
            # Подставив пустой, прибор не положил бы ноги дня в ПОТОЛОК: потолок (24)
            # молча занизился бы, а день ушёл бы в «не поднимает никакой рычаг» —
            # то есть ошибка адресата починки, напечатанная как ответ (инв. #17).
            legs = observed(row, "unpriced_protocols", kind=list)
            if legs is None:
                no_blocking_list.append(date)
                continue
            blocking_legs |= {str(p) for p in legs}
        else:
            beyond.append({"cycle_date": date,
                           "why": ("тривиальный ход" if row.get("trivial")
                                   else reason or str(row.get("outcome")))})
    if no_blocking_list:
        doc["unmeasured_reason"] = (
            f"{len(no_blocking_list)} дн. отвергнуты неоценённой ногой, но списка "
            f"отвергающих ног не несут ({', '.join(sorted(no_blocking_list))}) — "
            f"потолок посчитался бы по неполному набору ног и ЗАНИЗИЛСЯ БЫ МОЛЧА")
        f.append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
        return doc
    doc["population"] = {
        "journal_days": len(records),
        "denominator_today": len(baseline),
        "denominator_days_today": sorted(baseline),
        "outside_denominator": len(outside),
        "recoverable_in_principle": len(recoverable_in_principle),
        "recoverable_days": recoverable_in_principle,
        "beyond_any_grant": beyond,
        "beyond_note": ("выдача ставок не лечит НИ ПРИ КАКОМ наборе: тривиальный ход "
                        "исключён из знаменателя по правилу самого критерия, а "
                        "отсутствие форвардных дней / цели / разобранного вердикта — "
                        "не про наблюдаемость ног"),
    }
    doc["blocking_legs"] = sorted(blocking_legs)

    # ── сценарии ─────────────────────────────────────────────────────────────
    plans: List[Tuple[str, dict, str]] = [
        (SC_WRITER,
         {"grant_polled": True, "respect_writer": True, "grant_twin": False},
         "строка отсечения по universe у писателя; суждение писателя об эвиденсе УВАЖЕНО"),
        (SC_WRITER_OVERRIDING,
         {"grant_polled": True, "respect_writer": False, "grant_twin": False},
         "то же, но суждение писателя об эвиденсе ПЕРЕБИТО — контроль чувствительности"),
        (SC_KEY_MISMATCH,
         {"grant_polled": False, "respect_writer": True, "grant_twin": True},
         "свести два имени одних денег; ставка близнеца НАБЛЮДЕНА, не сентинел"),
        (SC_OUR_CODE,
         {"grant_polled": True, "respect_writer": True, "grant_twin": True},
         "оба рычага, лежащих в нашем коде"),
        (SC_CEILING,
         {"grant_polled": True, "respect_writer": False, "grant_twin": True,
          "extra_keys": set(blocking_legs)},
         "ПОТОЛОК: выданы ВСЕ блокирующие ноги, включая не опрашиваемые — верхняя "
         "граница мощности знаменателя при любом рычаге"),
    ]

    scenarios: Dict[str, dict] = {}
    disagreement: List[str] = []
    shrunk: List[str] = []
    for name, kwargs, reading in plans:
        perturbed = perturb(records, polled=polled, twins=twins, **kwargs)
        rows = _judge_all(perturbed, horizon)
        replay = _denominator(rows)
        struct = _structural_denominator(perturbed, horizon)
        if struct != replay:
            disagreement.extend(
                f"{name}:{d}" for d in sorted(struct.symmetric_difference(replay)))
        lost = sorted(baseline - replay)
        if lost:
            shrunk.extend(f"{name}:{d}" for d in lost)
        scenarios[name] = {
            "reading": reading,
            "denominator": len(replay),
            "delta_days": len(replay) - len(baseline),
            "days_added": sorted(replay - baseline),
            "days_still_outside": len(records) - len(replay),
            "recoverable_not_lifted": sorted(set(recoverable_in_principle) - replay),
        }
    doc["scenarios"] = scenarios

    # МОНОТОННОСТЬ: выдача ставок может только ДОБАВЛЯТЬ дни.
    doc["monotonicity_control"] = {
        "passed": not shrunk,
        "days_lost": shrunk[:10],
        "what_it_proves": ("выдача ставок не выбрасывает дни из знаменателя; выпавший "
                           "день означал бы, что возмущение мерит не тот путь"),
    }
    # ДВА ВЫВОДА.
    doc["derivation_cross_check"] = {
        "passed": not disagreement,
        "disagreements": disagreement[:10],
        "what_it_proves": ("структурный отбор и реплей настоящего судьи согласны; один "
                           "вывод был бы утверждением о моём же коде"),
    }
    # СПОСОБНОСТЬ.
    capability_required = bool(recoverable_in_principle)
    ceiling_delta = scenarios[SC_CEILING]["delta_days"]
    doc["capability_control"] = {
        "required": capability_required,
        "passed": (not capability_required) or ceiling_delta > 0,
        "ceiling_delta_days": ceiling_delta,
        "what_it_proves": ("прибор УМЕЕТ возвращать дни; без этого ноль по рычагу был "
                           "бы вакуумом — неотличимо «рычаг не тот» от «прибор не "
                           "возвращает никогда»"),
    }
    for control, why in (("monotonicity_control", "монотонность нарушена"),
                         ("derivation_cross_check", "два вывода разошлись"),
                         ("capability_control", "контроль способности не сработал")):
        block = doc[control]
        if block.get("required") is False:
            continue
        if not block.get("passed"):
            doc["unmeasured_reason"] = f"{why} — ответ недействителен"
            f.append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
            return doc

    # ── односторонняя сверка с соседом G7 ────────────────────────────────────
    doc["neighbour_check"] = _neighbour_check(data_dir, now, scenarios, baseline)

    # ── ответ ────────────────────────────────────────────────────────────────
    today = len(baseline)
    writer = scenarios[SC_WRITER]
    ours = scenarios[SC_OUR_CODE]
    ceiling = scenarios[SC_CEILING]
    doc["answer"] = {
        "denominator_today": today,
        "denominator_after_writer_universe": writer["denominator"],
        "denominator_after_our_code": ours["denominator"],
        "denominator_ceiling": ceiling["denominator"],
        "share_of_ceiling_measured_today_pct": (
            round(100.0 * today / ceiling["denominator"], 2)
            if ceiling["denominator"] else None),
        "hit_rate_after": None,
        "hit_rate_after_note": ("НЕ СЧИТАЕТСЯ НАМЕРЕННО: вердикт поднятого дня получен "
                                "под сентинелом и есть артефакт сентинела (ADR-300). "
                                "Ответ заказа — о РАЗМЕРЕ знаменателя"),
    }

    f.append(
        f"[ОТВЕТ] знаменатель `hit_rate` {today} дн. → {writer['denominator']} дн. "
        f"при рычаге `writer_universe` (+{writer['delta_days']}); обоими рычагами "
        f"нашего кода — {ours['denominator']} (+{ours['delta_days']}); ПОТОЛОК при "
        f"любом рычаге — {ceiling['denominator']} (+{ceiling['delta_days']}). "
        f"Значение критерия под сентинелом не печатается (ADR-300)")

    if ceiling["denominator"]:
        f.append(
            f"[РАЗМЕР] сегодняшний проходящий критерий посчитан на {today} из "
            f"{ceiling['denominator']} достижимых дней = "
            f"{doc['answer']['share_of_ceiling_measured_today_pct']} % населения; "
            f"остальные {ceiling['delta_days']} дн. — «не измерено», а не «HOLD был прав»")

    # Рычаги НЕ СКЛАДЫВАЮТСЯ в днях, и это измеренное свойство, а не оговорка.
    km = scenarios[SC_KEY_MISMATCH]
    doc["levers_are_not_additive"] = {
        "writer_universe_alone": writer["delta_days"],
        "key_mismatch_alone": km["delta_days"],
        "both": ours["delta_days"],
        "additive": writer["delta_days"] + km["delta_days"] == ours["delta_days"],
        "why": ("день возвращается, только когда ВСЕ его двигаемые ноги оценены на ОДНОМ "
                "форвардном дне: рычаг, поднимающий часть ног, в одиночку не возвращает "
                "дня вовсе. Поэтому «цена рычага в днях» осмысленна только в паре с тем, "
                "ЧТО ЕЩЁ применено"),
    }
    if not doc["levers_are_not_additive"]["additive"]:
        f.append(
            f"[СВОЙСТВО] рычаги не складываются в ДНЯХ: `writer_universe` в одиночку "
            f"+{writer['delta_days']} дн., `key_mismatch` в одиночку "
            f"+{km['delta_days']} дн., вместе +{ours['delta_days']} дн. Доказанный "
            f"рычаг G7 сам по себе не возвращает знаменателю ничего — в долларах он "
            f"стоит больше нуля, в днях в одиночку нет. Порядок рычагов по цене зависит "
            f"от ЕДИНИЦЫ, и единицы отвечают на разные вопросы")

    sens = scenarios[SC_WRITER_OVERRIDING]["denominator"] - writer["denominator"]
    doc["writer_verdict_sensitivity"] = {
        "respecting": writer["denominator"],
        "overriding": scenarios[SC_WRITER_OVERRIDING]["denominator"],
        "difference_days": sens,
        "what_it_proves": ("держится ли ответ на спорном шаге — перебитии собственного "
                           "суждения писателя об эвиденсе. Ноль означает, что не держится"),
    }
    # Строка печатается в ОБЕ стороны: молчание при нуле сделало бы «замерено и равно
    # нулю» неотличимым от «не замерено» (инв. #17).
    if sens:
        f.append(
            f"[ЧУВСТВИТЕЛЬНОСТЬ] ответ держится на перебитии суждения писателя: "
            f"уважая `apy_unevidenced` — {writer['denominator']} дн., перебивая — "
            f"{scenarios[SC_WRITER_OVERRIDING]['denominator']} дн. Разница {sens} дн. "
            f"лежит на рычаге ФИДА, а не писателя")
    else:
        f.append(
            f"[ОПОРА] ответ НЕ держится на спорном шаге: уважая собственное суждение "
            f"писателя об эвиденсе и перебивая его, знаменатель одинаков "
            f"({writer['denominator']} дн.). Рычаг писателя возвращает эти дни через "
            f"форвардные дни, где нога отсутствует ЦЕЛИКОМ, а не через дни, где "
            f"писатель объявил её неэвиденсной")

    left = ours["recoverable_not_lifted"]
    if left:
        f.append(
            f"[ЦЕНА] нашим кодом НЕ возвращается {len(left)} дн. "
            f"({', '.join(left)}) — их держат ноги вне опрашиваемого набора; рычаг там "
            f"у владельца (`POLLED_ADAPTERS`, money-path, предмет №1 границы ADR-285)")

    if writer["delta_days"] == 0 and capability_required:
        doc["status"] = STATUS_CRITICAL
        f.append(
            "[CRITICAL] названный заказом рычаг не возвращает знаменателю НИ ОДНОГО "
            "дня: ожидание «перепись входов сделает критерий взвода решаемым» "
            "оказалось ошибкой адресации, и очередь считала иначе")
    elif left or sens:
        doc["status"] = STATUS_WARNING
    else:
        doc["status"] = STATUS_OK
    return doc


def _neighbour_check(data_dir: Path, now: Optional[datetime],
                     scenarios: Dict[str, dict], baseline: Set[str]) -> dict:
    """ОДНОСТОРОННЯЯ сверка с G7: день с рычагом вне нашего кода не смеет подняться.

    Обратное НЕ утверждается, и это не осторожность, а форма самих вопросов: сосед
    берёт у ноги самый дешёвый рычаг по ВСЕМ её парам и объединяет рычаги ног дня,
    а дню довольно ОДНОГО форвардного дня, где оценены все ноги сразу. Поэтому его
    ``remedies_required`` — необходимое условие подъёма, но не достаточное, и
    «сосед назвал рычаг, которого мой сценарий не применял, а день поднялся» есть
    согласие двух разных вопросов, а не спор.
    """
    out: dict = {"compared": False, "direction": "одностороннее: сосед запрещает — "
                                                "мой сценарий обязан не поднимать"}
    try:
        neighbour = _remedy.measure(Path(data_dir), now=now)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не сверено»
        out["reason"] = f"сосед G7 отказал: {type(exc).__name__}: {exc}"
        return out
    per_day = observed(neighbour, "per_day", kind=list)
    if not per_day:
        out["reason"] = (f"сосед G7 не дал разложенных дней (вердикт: "
                         f"{neighbour.get('status')}) — сверять не с чем, и это НЕ "
                         f"«сошлось»")
        return out

    our_lifted = set(scenarios[SC_OUR_CODE]["days_added"])
    violations: List[str] = []
    forbidden: List[str] = []
    for day in per_day:
        if not isinstance(day, dict):
            continue
        date = str(day.get("cycle_date"))
        required = observed(day, "remedies_required", kind=list)
        if required is None:
            continue
        if set(str(x) for x in required) <= set(_remedy.OUR_CODE_REMEDIES):
            continue
        forbidden.append(date)
        if date in our_lifted:
            violations.append(date)
    out.update({
        "compared": True,
        "neighbour_status": neighbour.get("status"),
        "days_neighbour_puts_outside_our_code": sorted(forbidden),
        "violations": sorted(violations),
        "passed": not violations,
        "what_it_proves": ("два прибора об одних днях не спорят в ту сторону, в которую "
                           "спор был бы уликой: день, которому сосед назначил рычаг "
                           "владельца, нашим кодом не поднимается"),
    })
    return out


# ── отрисовка для шага 0-офис ────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → ответ в ДНЯХ → сценарии → контроли."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(f"   знаменатель hit_rate под рычагом (заказ #591/G8): {doc.get('status')} "
               f"· дней журнала {pop.get('journal_days')} · в знаменателе сегодня "
               f"{pop.get('denominator_today')} · восстановимых в принципе "
               f"{pop.get('recoverable_in_principle')}")
    if doc.get("unmeasured_reason"):
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
    for key, label in ((SC_WRITER, "рычаг писателя (universe)"),
                       (SC_KEY_MISMATCH, "рычаг двух имён (близнец)"),
                       (SC_OUR_CODE, "оба рычага нашего кода"),
                       (SC_CEILING, "потолок при любом рычаге")):
        sc = (doc.get("scenarios") or {}).get(key)
        if not sc:
            continue
        out.append(f"   {label}: знаменатель {sc.get('denominator')} дн. "
                   f"({sc.get('delta_days'):+d})")
    par = doc.get("canonical_parity") or {}
    if par:
        out.append("   сверка с каноническим знаменателем: "
                   + ("сошлась" if par.get("passed") else "РАЗОШЛАСЬ"))
    nb = doc.get("neighbour_check") or {}
    if nb.get("compared"):
        out.append("   односторонняя сверка с G7: "
                   + ("сошлась" if nb.get("passed") else "НАРУШЕНА"))
    elif nb.get("reason"):
        out.append(f"   сверка с G7: НЕ СВЕРЕНО — {nb['reason']}")
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    note = (doc.get("answer") or {}).get("hit_rate_after_note")
    if note:
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {note}")
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
        "warn": sum(1 for x in findings if x.startswith("[ЦЕНА")
                    or x.startswith("[ЧУВСТВИТЕЛЬНОСТЬ]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")
                    or x.startswith("[РАЗМЕР]") or x.startswith("[СВОЙСТВО]")
                    or x.startswith("[ОПОРА]")),
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
        description="сколько дней вернул бы знаменателю hit_rate рычаг writer_universe "
                    "(заказ #591/G8)")
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
