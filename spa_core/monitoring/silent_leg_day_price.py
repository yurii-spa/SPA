"""Честная цена починки МОЛЧАЩЕЙ ноги — в ДНЯХ знаменателя ``hit_rate`` (заказ #598/G12).

Заказ, оставленный в хвосте [ADR-379] по стоячему приказу владельца «Portfolio CIO»
(`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md`):

> G11 закрыл вопрос «сколько их» и оставил ровно одно имя. Следующий вопрос — о **сроке**:
> сколько дней знаменателя ``hit_rate`` вернёт починка молчащей ноги — и сколько останется
> не возвращённым ничем. ADR-378 назвал цену ноги в **$100 000** и в «**4 из 8 дней**», но
> 4 дня измерены как БЛОКИРУЮЩИЕ, а не как ПОДНИМАЕМЫЕ: день возвращается лишь тогда, когда
> материал есть у ВСЕХ его ног на ОДНОМ форвардном дне ([ADR-371]/[ADR-375]), и вторая нога
> дня может молчать по своей причине. Считать 4 поднятыми — ровно та ошибка переноса ответа
> с ноги на день, которую снял G9.

## Предмет ровно один

**Сколько дней знаменателя ``hit_rate`` поднимает починка ОДНОЙ НАЗВАННОЙ ноги — в
одиночку.** Не доллары слепого оборота (предмет ADR-378), не число молчащих ног (предмет
ADR-379), не значение критерия (оно не считается вовсе и это закреплено тестом).

«Нога блокирует день» и «починка ноги возвращает день» — РАЗНЫЕ утверждения, и второе из
первого не следует. Судья выносит вердикт при ``checked >= 1``: дню довольно ОДНОГО
форвардного дня, где оценены ВСЕ его двигаемые ноги. Значит блокирующая нога есть условие
НЕОБХОДИМОЕ, а достаточным оно становится только тогда, когда на том же форвардном дне
молчать больше некому.

## Ответ — из ТРЁХ чисел, и третье никогда не сливается с первыми двумя

Для каждой молчащей ноги заказ требует разложить её блокирующие дни на:

1. **поднимается в одиночку** — починки этой ноги ДОСТАТОЧНО;
2. **держит вторая нога** — поимённо и с ПРИЧИНОЙ её молчания (род починки у неё свой);
3. **не поднимает ничто из нашего кода** — среди держащих есть нога, рычаг которой лежит
   у владельца (``POLLED_ADAPTERS``, money-path, предмет №1 границы ADR-285).

Слить (2) и (3) значило бы отправить читателя чинить не то место: в (2) работа наша и
измерима, в (3) её у нас нет вовсе.

## Субъект БЕРЁТСЯ У ПЕРЕПИСИ, а не из текста соседа

Имя молчащей ноги приходит от канонического производителя — переписи [ADR-379]
(``polled_never_observed_census``), у которой этот вопрос и есть предмет. Вписать имя
литералом значило бы перепечатать число из соседнего текста: ровно тот дефект, на котором
[ADR-379] поймал сам себя («800 дней» против 39 измеренных). Перепись отказала ⇒ **третий
исход**, а не «молчащих ног нет».

## Причина второй ноги ИЗМЕРЕНА, и порядок проверки не произволен

| род | чем доказан | чей рычаг |
|---|---|---|
| ``renamed_key`` | близнец у сторожа ВТОРОЙ ЗАПИСИ (суммы равны) | наш код |
| ``silent_in_series`` | перепись [ADR-379]: ни одной точки ряда | наш код (проводка фида) |
| ``not_polled`` | ноги нет в ``POLLED_ADAPTERS`` | **владелец** |
| ``polled_and_observed`` | опрашивается и в ряду наблюдалась | наш код (строка писателя) |

``renamed_key`` проверяется **ПЕРВЫМ** намеренно: переименованный ключ выглядит как
«ноги не опрашивают», хотя это те же деньги под другим именем, и отнести его к рычагу
владельца значило бы отдать наружу работу, лежащую у нас. Близнецы берутся у сторожа
двойной записи, а НЕ по виду имени: сходство имён доказательством не является ([ADR-378]).

## Контроль ДОСТАТОЧНОСТИ — тот, без которого «держит вторая нога» есть догадка

Назвав держащие ноги, прибор обязан ПОКАЗАТЬ, что назвал верно: выдача субъекта ВМЕСТЕ с
названными ногами обязана день поднять. Не подняла ⇒ набор назван неправильно ⇒ **не
измерено**, а не «держит кто-то ещё». Это единственный контроль, который отличает
измеренный ответ от правдоподобного списка.

## Что прибор МЕНЯЕТ в уже опубликованном числе

[ADR-371] опубликовал «знаменатель 16 → 22 рычагом ``writer_universe``». Молчащая нога
**опрашивается**, поэтому её дни попали в те +6 по построению — а материала в ряду у неё
нет ни одной точки ([ADR-379]). Значит у рычага писателя есть ПОЛ: тот же рычаг с изъятой
молчащей ногой. Разница пола и потолка есть в точности цена молчащей ноги, и прибор печатает
обе границы, потому что одна без другой читается как план работ.

**ADVISORY.** Прибор ЧИТАЕТ. ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель
журнала, ``POLLED_ADAPTERS``, пины, адаптеры, пороги RiskPolicy v1.0, стоп-кран, живой трек
и ``landing/`` не трогаются; капитал не двигается. Проводка ноги к живому фиду и расширение
записи решения — money-path, и этим прибором они не принимаются.

[ADR-371]: docs/decisions/ADR-371-hit-rate-denominator-recovery.md
[ADR-375]: docs/decisions/ADR-375-remedy-class-single-forward-day.md
[ADR-378]: docs/decisions/ADR-378-writer-universe-lever-floor.md
[ADR-379]: docs/decisions/ADR-379-polled-never-observed-census.md
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное имя
# есть СНИМОК функции на момент импорта, и подмена канонического правила прошла бы мимо
# нас молча. Так же поступают все соседи по этому заказу (ADR-366/368/369/371/378/379).
from spa_core.monitoring import g1_verdict_recoverability as _g1
from spa_core.monitoring import hit_rate_denominator_recovery as _rec
from spa_core.monitoring import polled_never_observed_census as _census
from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.silent_leg_day_price")

OUTPUT_FILENAME = "silent_leg_day_price.json"
VERSION = "silent-leg-day-price-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Роды причины, по которым вторая нога держит день. Порядок кортежа = порядок проверки,
#: и он НЕ произволен (см. шапку): переименование ключа обязано быть распознано до того,
#: как нога будет объявлена неопрашиваемой.
CAUSE_RENAMED = "renamed_key"
CAUSE_SILENT = "silent_in_series"
CAUSE_NOT_POLLED = "not_polled"
CAUSE_POLLED_OBSERVED = "polled_and_observed"
CAUSE_ORDER = (CAUSE_RENAMED, CAUSE_SILENT, CAUSE_NOT_POLLED, CAUSE_POLLED_OBSERVED)

#: Чей рычаг у каждого рода. Единственный род владельца назван ровно один раз — второй
#: копии этого соответствия в файле нет, иначе они разошлись бы молча.
OWNER_CAUSES = frozenset({CAUSE_NOT_POLLED})

#: Исходы дня. Четыре, и они не сливаются (инв. #17).
DAY_LIFTED_ALONE = "lifted_alone"
DAY_HELD_BY_OUR_CODE = "held_by_second_leg_our_code"
DAY_HELD_BY_OWNER = "held_by_second_leg_owner"
DAY_UNMEASURED = "unmeasured"

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `TriggerParams`, писатель журнала, "
             "`POLLED_ADAPTERS`, пины, адаптеры, пороги RiskPolicy v1.0, стоп-кран и живой "
             "трек НЕ трогаются — прибор только делит блокирующие дни ноги на поднимаемые "
             "и держимые")

#: Границы утверждения едут В АРТЕФАКТЕ, а не только в шапке модуля: читатель отчёта шапку
#: не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не печатает `hit_rate` под возмущением и не печатает исход НИ ОДНОГО поднятого дня: "
    "под сентинелом это артефакт сентинела, а не наблюдение (конвенция ADR-300). "
    "Утверждение прибора — о РАЗМЕРЕ знаменателя",
    "не обещает, что у молчащей ноги живая ставка в те дни СУЩЕСТВОВАЛА: ряд этого не "
    "несёт, и «поднимается в одиночку» остаётся ПОТОЛКОМ починки, а не её результатом",
    "не утверждает, что вердикты поднятых дней были бы верны или что HOLD был неправ",
    "не пересчитывает доллары ADR-378 и не поправляет его классы: у него другая ЕДИНИЦА, "
    "и порядок рычагов по цене от единицы зависит (измерено в ADR-371)",
    "не принимает ни строки у писателя, ни пина, ни проводки ноги к фиду: всё это "
    "money-path и решение владельца",
]

# ── исходы, которые НЕ измеряются ────────────────────────────────────────────
NO_JOURNAL = ("журнал решений пуст или не прочитан — населения вопроса нет, и это НЕ "
              "«цена ноги нулевая»")
NO_POLLED = ("`POLLED_ADAPTERS` не прочитан — чей рычаг у второй ноги, сказать нечем; "
             "«не прочитан» не читается как «опрашивать нечего»")
NO_CENSUS = ("перепись молчащих ног (ADR-379) не дала разложения по протоколам — субъект "
             "замера неизвестен, и это НЕ «молчащих ног нет»")
NO_CANON = ("канонический знаменатель (`shadow_trigger_eval.scored_days`) не измерен — "
            "сверять свой отбор не с чем, а второе определение знаменателя заводить "
            "запрещено")
NO_BLOCKING = ("день отвергнут неоценённой ногой, но списка отвергающих ног не несёт — "
               "субъект нельзя признать ни блокирующим, ни непричастным, и подстановка "
               "пустого списка напечатала бы «нога непричастна» как измеренный ответ")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── субъекты: молчащие ноги у канонического производителя ────────────────────
def silent_legs(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Молчащие ноги ПО ПЕРЕПИСИ ADR-379 — по имени, вместе с её вердиктом.

    Возвращает ``{"measured": bool, "legs": [...], "reason": str|None}``. Отказ переписи
    и «перепись прошла, молчащих нет» — РАЗНЫЕ исходы, и слиты они быть не могут: первый
    означает, что вопрос не задан, второй — что он задан и ответ ноль.
    """
    try:
        doc = _census.measure(Path(data_dir), now=now)
    except Exception as exc:  # noqa: BLE001 — любой отказ переписи = «не измерено»
        return {"measured": False, "legs": [], "census_status": None,
                "reason": f"{NO_CENSUS} ({type(exc).__name__}: {exc})"}
    rows = observed(doc, "per_protocol", kind=list)
    if rows is None:
        return {"measured": False, "legs": [], "census_status": doc.get("status"),
                "reason": f"{NO_CENSUS} (вердикт переписи: {doc.get('status')})"}
    legs = [str(r.get("protocol")) for r in rows
            if isinstance(r, dict) and r.get("outcome") in _census.PROVEN_SILENT]
    return {"measured": True, "legs": sorted(legs),
            "census_status": doc.get("status"), "reason": None}


# ── причина молчания второй ноги ─────────────────────────────────────────────
def cause_of(leg: str, *, polled: Set[str], twins: Dict[str, List[str]],
             silent: Set[str]) -> str:
    """Род починки второй ноги. Порядок проверки закреплён ``CAUSE_ORDER`` и значим.

    ``renamed_key`` спрашивается первым: переименованный ключ отсутствует в опрашиваемом
    наборе под СТАРЫМ именем и выглядел бы как рычаг владельца, хотя это те же деньги под
    новым именем и работа лежит у нас.
    """
    if twins.get(leg):
        return CAUSE_RENAMED
    if leg in silent:
        return CAUSE_SILENT
    if leg not in polled:
        return CAUSE_NOT_POLLED
    return CAUSE_POLLED_OBSERVED


# ── кто держит день ──────────────────────────────────────────────────────────
def holders_by_forward_day(records: Dict[str, dict], date: str,
                           horizon: int) -> Optional[List[Tuple[str, List[str]]]]:
    """По каждому форвардному дню — двигаемые ноги, не оценённые на нём.

    ``None`` означает, что дня нет в карте: это отказ разбора, а не «держащих нет».
    """
    order = sorted(records)
    if date not in records:
        return None
    i = order.index(date)
    deltas = _ste._deltas(records[date])
    out: List[Tuple[str, List[str]]] = []
    for fwd_date in order[i + 1:i + 1 + horizon]:
        apy = observed(records[fwd_date], "apy_evidenced_pct", kind=dict) or {}
        out.append((fwd_date, sorted(p for p in deltas if apy.get(p) is None)))
    return out


def cheapest_holders(rows: Sequence[Tuple[str, List[str]]]) -> Tuple[Optional[str], List[str]]:
    """Форвардный день, ближе всех к подъёму, и ноги, которых на нём не хватило.

    Берётся МИНИМУМ по мощности набора: именно он есть «что ещё выдать, чтобы день
    поднялся». Объединение по всем форвардным дням завысило бы работу, пересечение —
    занизило бы, и обе ошибки читались бы как измеренный ответ.
    """
    best_date: Optional[str] = None
    best: Optional[List[str]] = None
    for fwd_date, missing in rows:
        if best is None or len(missing) < len(best):
            best_date, best = fwd_date, list(missing)
    return best_date, (best or [])


# ── замер ────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: Optional[int] = None, book_id: Optional[str] = None,
            **_ignored) -> dict:
    """Ответ заказу #598/G12: цена починки каждой молчащей ноги в ДНЯХ знаменателя.

    ``_ignored`` — совместимость со ступенью переписей, которая передаёт общие для всех
    приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни один не участвует в
    замере: появись здесь значащий параметр, он обязан быть назван явно.
    """
    data_dir = Path(data_dir)
    horizon = int(horizon_days or _ste.DEFAULT_HORIZON_DAYS)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or _utcnow()).isoformat(),
        "subject": ("сколько ДНЕЙ знаменателя `hit_rate` возвращает починка МОЛЧАЩЕЙ ноги "
                    "в одиночку, сколько держит вторая нога и сколько не поднимает ничто "
                    "из нашего кода (заказ #598/G12 приказа «Portfolio CIO»)"),
        "unit": "дни знаменателя hit_rate (не доллары оборота и не число ног)",
        "horizon_days": horizon,
        "status": STATUS_UNMEASURED,
        "findings": [],
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }
    f: List[str] = doc["findings"]

    def refuse(reason: str) -> dict:
        doc["unmeasured_reason"] = reason
        f.append(f"[НЕ ИЗМЕРЕНО] {reason}")
        return doc

    # ── вход 1: журнал решений ───────────────────────────────────────────────
    try:
        history, bad_lines = _ste.load_history(data_dir, book_id)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return refuse(f"{NO_JOURNAL} ({type(exc).__name__}: {exc})")
    if not history:
        return refuse(NO_JOURNAL)
    records = {str(r.get("cycle_date")): r for r in history}
    doc["journal"] = {"rows": len(history), "unparseable": bad_lines,
                      "days": len(records)}

    # ── вход 2: опрашиваемый набор (чей рычаг у второй ноги) ─────────────────
    polled = _remedy._polled_keys()
    if polled is None:
        return refuse(NO_POLLED)
    doc["polled_adapters"] = sorted(polled)

    # ── вход 3: близнецы у сторожа ВТОРОЙ ЗАПИСИ ─────────────────────────────
    twins_doc = _remedy._twin_keys(data_dir)
    twins: Dict[str, List[str]] = twins_doc.get("pairs") or {}
    doc["twin_keys"] = {"measured": twins_doc.get("measured"),
                        "pairs": twins_doc.get("pairs"),
                        "reason": twins_doc.get("reason")}

    # ── вход 4: СУБЪЕКТЫ у переписи ADR-379 ──────────────────────────────────
    subj = silent_legs(data_dir, now=now)
    doc["subjects"] = subj
    if not subj["measured"]:
        return refuse(subj["reason"] or NO_CENSUS)
    silent: Set[str] = set(subj["legs"])

    # ── базовая линия и канонический паритет ─────────────────────────────────
    baseline_rows = _rec._judge_all(records, horizon)
    baseline = _rec._denominator(baseline_rows)
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
        return refuse(NO_CANON)
    if canon != baseline:
        return refuse(f"базовый знаменатель ({len(baseline)}) разошёлся с каноническим "
                      f"({len(canon)}) — числам ниже верить нельзя")

    # ПАРИТЕТ-2: пустой набор обязан воспроизвести судью бит в бит.
    empty_rows = _rec._judge_all(
        _rec.perturb(records, polled=polled, twins=twins, grant_polled=False,
                     respect_writer=True, grant_twin=False), horizon)
    mismatch = [d for d in records if empty_rows.get(d) != baseline_rows.get(d)]
    doc["copy_parity"] = {
        "passed": not mismatch,
        "days_compared": len(records),
        "mismatch_days": sorted(mismatch)[:10],
        "what_it_proves": ("возмущение копирует записи ЧЕСТНО: при пустом наборе реплей "
                           "= настоящий _evaluate_verdict бит в бит"),
    }
    if mismatch:
        return refuse(f"контроль паритета копирования не прошёл на {len(mismatch)} дн.")

    # ── население: дни вне знаменателя, отвергнутые неоценённой ногой ────────
    recoverable: List[str] = []
    blocking_of: Dict[str, Set[str]] = {}
    no_list: List[str] = []
    for date in sorted(set(records) - baseline):
        row = baseline_rows[date]
        if row.get("outcome") != "UNCHECKED":
            continue
        if str(row.get("unchecked_reason") or "") != _g1._REASON_RECOVERABLE:
            continue
        legs = observed(row, "unpriced_protocols", kind=list)
        if legs is None:
            # Пустой список здесь объявил бы субъекта НЕПРИЧАСТНЫМ к дню — то есть
            # напечатал бы «цена ноги меньше» как измеренный ответ (инв. #17).
            no_list.append(date)
            continue
        recoverable.append(date)
        blocking_of[date] = {str(p) for p in legs}
    if no_list:
        return refuse(f"{NO_BLOCKING} ({', '.join(sorted(no_list))})")

    doc["population"] = {
        "journal_days": len(records),
        "denominator_today": len(baseline),
        "recoverable_in_principle": len(recoverable),
        "recoverable_days": recoverable,
    }

    # ── замер по каждому субъекту ────────────────────────────────────────────
    def denom(extra: Set[str], *, polled_set: Optional[Set[str]] = None,
              grant_polled: bool = False, grant_twin: bool = False) -> Set[str]:
        perturbed = _rec.perturb(
            records, polled=polled if polled_set is None else polled_set, twins=twins,
            grant_polled=grant_polled, respect_writer=True, grant_twin=grant_twin,
            extra_keys=set(extra))
        return _rec._denominator(_rec._judge_all(perturbed, horizon))

    per_leg: List[dict] = []
    unmeasured_days: List[str] = []
    sufficiency_failures: List[str] = []
    monotonicity_failures: List[str] = []

    for leg in sorted(silent):
        blocks = [d for d in recoverable if leg in blocking_of[d]]
        lifted = denom({leg})
        if baseline - lifted:
            monotonicity_failures.extend(f"{leg}:{d}" for d in sorted(baseline - lifted))
        alone = sorted(set(blocks) & (lifted - baseline))
        # Дни, которые нога поднимает, НЕ БУДУЧИ их блокирующей, — улика о разборе:
        # день поднялся от выдачи ноги, которой список отвергающих его не числит.
        collateral = sorted((lifted - baseline) - set(blocks))

        # Возмущение для разбора держащих: субъект выдан, больше ничего.
        perturbed = _rec.perturb(records, polled=polled, twins=twins, grant_polled=False,
                                 respect_writer=True, grant_twin=False, extra_keys={leg})
        held: List[dict] = []
        for date in blocks:
            if date in alone:
                continue
            rows = holders_by_forward_day(perturbed, date, horizon)
            if rows is None or not rows:
                unmeasured_days.append(f"{leg}:{date}")
                continue
            fwd_date, missing = cheapest_holders(rows)
            if not missing:
                # День не поднялся, а держащих не нашлось — разбор спорит сам с собой.
                unmeasured_days.append(f"{leg}:{date}")
                continue
            causes = {m: cause_of(m, polled=polled, twins=twins, silent=silent)
                      for m in missing}
            owner_legs = sorted(m for m, c in causes.items() if c in OWNER_CAUSES)
            # КОНТРОЛЬ ДОСТАТОЧНОСТИ: назвал держащих — покажи, что назвал верно.
            check = denom({leg} | set(missing))
            if date not in check:
                sufficiency_failures.append(f"{leg}:{date}")
                continue
            held.append({
                "cycle_date": date,
                "outcome": DAY_HELD_BY_OWNER if owner_legs else DAY_HELD_BY_OUR_CODE,
                "held_by": missing,
                "causes": causes,
                "owner_legs": owner_legs,
                "nearest_forward_day": fwd_date,
                "sufficiency_verified": True,
            })

        held_ours = [h for h in held if h["outcome"] == DAY_HELD_BY_OUR_CODE]
        held_owner = [h for h in held if h["outcome"] == DAY_HELD_BY_OWNER]
        floor = denom(set(), polled_set=polled - {leg}, grant_polled=True)
        with_leg = denom(set(), grant_polled=True)
        per_leg.append({
            "leg": leg,
            "blocking_days": len(blocks),
            "blocking_day_list": blocks,
            "days_lifted_alone": len(alone),
            "days_lifted_alone_list": alone,
            "days_held_by_second_leg": len(held),
            "days_held_our_code": len(held_ours),
            "days_held_owner": len(held_owner),
            "held_detail": held,
            "collateral_days": collateral,
            "denominator_today": len(baseline),
            "denominator_leg_alone": len(lifted),
            "writer_lever_floor_without_leg": len(floor),
            "writer_lever_with_leg": len(with_leg),
            "writer_days_resting_on_leg": len(with_leg) - len(floor),
        })

    doc["per_leg"] = per_leg
    doc["monotonicity_control"] = {
        "passed": not monotonicity_failures,
        "days_lost": monotonicity_failures[:10],
        "what_it_proves": ("выдача ставки субъекту не выбрасывает дни из знаменателя; "
                           "выпавший день означал бы, что возмущение мерит не тот путь"),
    }
    doc["sufficiency_control"] = {
        "passed": not sufficiency_failures,
        "failures": sufficiency_failures[:10],
        "what_it_proves": ("названные держащие ноги ДЕЙСТВИТЕЛЬНО держат: выдача "
                           "субъекта вместе с ними день поднимает. Без этого «держит "
                           "вторая нога» есть правдоподобный список, а не замер"),
    }
    if unmeasured_days:
        doc["unmeasured_days"] = sorted(unmeasured_days)
    if monotonicity_failures:
        return refuse("монотонность нарушена — ответ недействителен")
    if sufficiency_failures:
        return refuse(f"контроль достаточности не прошёл на {len(sufficiency_failures)} "
                      f"дн. — набор держащих ног назван неверно")
    if unmeasured_days:
        return refuse(f"{len(unmeasured_days)} блокирующ(их) дн. не разобрано "
                      f"({', '.join(sorted(unmeasured_days))})")

    # ── ответ ────────────────────────────────────────────────────────────────
    doc["answer"] = {
        "silent_legs": sorted(silent),
        "denominator_today": len(baseline),
        "hit_rate_after": None,
        "hit_rate_after_note": ("НЕ СЧИТАЕТСЯ НАМЕРЕННО: вердикт поднятого дня получен "
                                "под сентинелом и есть артефакт сентинела (ADR-300). "
                                "Ответ заказа — о РАЗМЕРЕ знаменателя"),
        "legs": [{"leg": r["leg"], "blocking_days": r["blocking_days"],
                  "lifted_alone": r["days_lifted_alone"],
                  "held_our_code": r["days_held_our_code"],
                  "held_owner": r["days_held_owner"]} for r in per_leg],
    }

    if not per_leg:
        # Перепись прошла и молчащих не нашла — ИЗМЕРЕННЫЙ ноль, и он обязан звучать
        # иначе, чем отказ переписи выше (инв. #17).
        doc["status"] = STATUS_OK
        f.append("[ОТВЕТ] перепись ADR-379 молчащих ног не нашла — цена в днях пуста по "
                 "ИЗМЕРЕНИЮ, а не по отказу прибора")
        return doc

    for r in per_leg:
        f.append(
            f"[ОТВЕТ] `{r['leg']}`: блокирует {r['blocking_days']} дн., поднимает в "
            f"ОДИНОЧКУ {r['days_lifted_alone']} дн. (знаменатель "
            f"{r['denominator_today']} → {r['denominator_leg_alone']}); держит вторая "
            f"нога {r['days_held_by_second_leg']} дн., из них нашим кодом решаемых "
            f"{r['days_held_our_code']}, рычагом владельца — {r['days_held_owner']}")
        for h in r["held_detail"]:
            names = ", ".join(f"`{m}` ({h['causes'][m]})" for m in h["held_by"])
            f.append(
                f"[ДЕРЖИТ] {h['cycle_date']} — не поднимается починкой `{r['leg']}` в "
                f"одиночку: на ближайшем форвардном дне {h['nearest_forward_day']} "
                f"молчит {names}"
                + (f"; рычаг у ВЛАДЕЛЬЦА ({', '.join(h['owner_legs'])}, "
                   f"`POLLED_ADAPTERS`, money-path, предмет №1 границы ADR-285)"
                   if h["owner_legs"] else "; рычаг в НАШЕМ коде"))
        if r["blocking_days"] and r["days_lifted_alone"] < r["blocking_days"]:
            f.append(
                f"[ПОПРАВКА] цена `{r['leg']}`, названная соседом в БЛОКИРУЮЩИХ днях "
                f"({r['blocking_days']}), выше цены в ПОДНИМАЕМЫХ "
                f"({r['days_lifted_alone']}): день возвращается лишь тогда, когда "
                f"материал есть у ВСЕХ его ног на одном форвардном дне. Читатель, "
                f"взявший число блокирующих дней как план, ПЕРЕОЦЕНИТ отдачу починки")
        if r["writer_days_resting_on_leg"]:
            f.append(
                f"[ПОЛ РЫЧАГА] опубликованные ADR-371 «16 → "
                f"{r['writer_lever_with_leg']} рычагом `writer_universe`» держатся на "
                f"`{r['leg']}` на {r['writer_days_resting_on_leg']} дн.: нога "
                f"ОПРАШИВАЕТСЯ, поэтому её дни вошли в рычаг по построению, а точек в "
                f"ряду у неё нет ни одной (ADR-379). Материалом подтверждённый ПОЛ "
                f"рычага — {r['writer_lever_floor_without_leg']} дн.")
        if r["collateral_days"]:
            f.append(
                f"[СЛЕД] выдача `{r['leg']}` подняла {len(r['collateral_days'])} дн., "
                f"которые списком отвергающих ног её не числят "
                f"({', '.join(r['collateral_days'])}) — расхождение разбора и судьи")

    owner_days = sum(r["days_held_owner"] for r in per_leg)
    ours_days = sum(r["days_held_our_code"] for r in per_leg)
    if owner_days:
        doc["status"] = STATUS_CRITICAL
    elif ours_days or any(r["writer_days_resting_on_leg"] for r in per_leg):
        doc["status"] = STATUS_WARNING
    else:
        doc["status"] = STATUS_OK
    return doc


# ── отрисовка для шага 0-офис ────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → субъекты → цена по ногам → контроли."""
    out: List[str] = []
    pop = doc.get("population") or {}
    subj = doc.get("subjects") or {}
    out.append(f"   цена починки молчащей ноги в ДНЯХ (заказ #598/G12): {doc.get('status')} "
               f"· дней журнала {pop.get('journal_days')} · знаменатель сегодня "
               f"{pop.get('denominator_today')} · молчащих ног "
               f"{len(subj.get('legs') or []) if subj.get('measured') else 'НЕ ИЗМЕРЕНО'}")
    if doc.get("unmeasured_reason"):
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
    for r in doc.get("per_leg") or []:
        out.append(f"   `{r['leg']}`: блокирует {r['blocking_days']} дн. · поднимает в "
                   f"одиночку {r['days_lifted_alone']} · держит вторая нога "
                   f"{r['days_held_by_second_leg']} (наших {r['days_held_our_code']}, "
                   f"владельца {r['days_held_owner']})")
    par = doc.get("canonical_parity") or {}
    if par:
        out.append("   сверка с каноническим знаменателем: "
                   + ("сошлась" if par.get("passed") else "РАЗОШЛАСЬ"))
    suf = doc.get("sufficiency_control") or {}
    if suf:
        out.append("   контроль достаточности держащих ног: "
                   + ("сошёлся" if suf.get("passed") else "НЕ СОШЁЛСЯ"))
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
        "warn": sum(1 for x in findings if x.startswith("[ДЕРЖИТ]")
                    or x.startswith("[ПОПРАВКА]") or x.startswith("[ПОЛ РЫЧАГА]")
                    or x.startswith("[СЛЕД]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")),
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
        description="цена починки молчащей ноги в ДНЯХ знаменателя hit_rate "
                    "(заказ #598/G12)")
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
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING, STATUS_CRITICAL) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
