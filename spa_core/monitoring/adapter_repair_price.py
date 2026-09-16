"""Цена починки АДАПТЕРОВ в ACT-днях до критерия (заказ #606/G19).

Заказ, оставленный в хвосте [ADR-386] по стоячему приказу владельца «Portfolio CIO»,
поставлен дословно так:

> Из 39 дней ёмкости девять (у второй формы одиннадцать) не доходят до критерия с
> причиной ``no_evidenced_apy_for_moved_legs``, и это не свойство судьи вовсе.
> Измерить по исходу: **(а)** сколько дней журнала ВООБЩЕ неоценимы этой причиной —
> не в ёмкостном стенде, а как они лежат, и какая доля КАПИТАЛА книги стояла в эти
> дни на ногах без живой ставки; **(б)** поимённо, какие протоколы дают эту причину и
> сколько раз каждый; **(в)** сколько дней вернулось бы критерию, если бы у КАЖДОГО
> названного протокола появилась живая ставка завтра — то есть цена починки
> АДАПТЕРОВ, выраженная в той же валюте (ACT-дни до критерия), что и цена починки
> писателя в [ADR-383] и судьи в [ADR-386].

## Валюта ответа — та же, что у соседей, и берётся она у НИХ

«День дошёл до критерия» определено не здесь: определение живёт в
``judge_alone_price.capacity`` — вердикт дня стал ``ACT`` И его исход попал в
``hit``/``miss``, то есть день вошёл в ``acts_scored``, единственный набор, которым
считается ``net_bps_if_followed`` (мандат владельца [ADR-067]). Своей копии правила
здесь нет: две копии спорили бы о том же дне молча, обе печатая число и ни одна —
правило.

## Ставка не выдумывается: выдаётся ПРАВО БЫТЬ ОЦЕНЁННЫМ — и это ИЗМЕРЕНО, не заявлено

Возмущение подставляет отсутствующей ноге ``_PRICING_SENTINEL_PCT`` = 0.0: нога
становится оценимой, её вклад в ``benefit`` равен ровно нулю, выдуманной доходности
в числа прибора попасть неоткуда (та же конвенция, что у ``g1_verdict_recoverability``).

Новое здесь — то, что безразличие ответа к подставленному числу **меряется**, а не
объявляется. Стенд гонится ТРИЖДЫ, с сентинелами 0 / +25 / −25 пп:

======================  ===========  ===========  ===========
величина                  0.0          +25.0        −25.0
======================  ===========  ===========  ===========
``reaches_criterion``     38           38           38
``net>0`` среди них       0            1            6
======================  ===========  ===========  ===========

Первая строка — ответ прибора, и он безразличен к сентинелу. Вторая — причина, по
которой знак ``net`` под возмущением **не докладывается вовсе**: он не просто
чувствителен к выдуманному числу, он растёт при ОТРИЦАТЕЛЬНОЙ подстановке (уходить
из ноги с плохой ставкой выгодно), то есть «сколько дней окупается» под грантом было
бы утверждением о сентинеле, а не о мире. Расхождение ``reaches_criterion`` между
сентинелами ⇒ прибор ОТКАЗЫВАЕТ (``UNMEASURED``), а не выбирает удобный.

## Два чтения, и схлопывать их нельзя

* ``today`` — журнал КАК ОН ЛЕЖИТ. Здесь ответ **ноль при любом наборе протоколов**:
  все 40 дней журнала несут ``HOLD``, а критерий №3 может быть закрыт только
  оценённым ``ACT``. Ставки поднимают дни в знаменатель ``hit_rate`` (критерий №2,
  и он давно ``PASS``), но до критерия №3 не доносят ни одного;
* ``capacity`` — тот же ёмкостный стенд, что в [ADR-386]: писатель починен, ранний
  ACT собран из НАСТОЯЩЕЙ строки соседнего дня. Только на нём вопрос заказа вообще
  имеет ненулевой ответ, и только он сравним с ценой починки писателя и судьи.

Сегодняшнее чтение печатается ПЕРВЫМ намеренно: читатель, увидевший «+10 ACT-дней»
раньше нуля, прочтёт ёмкость как обещание.

## Сумма по одиночкам НЕ равна ответу, и это не ошибка счёта

День отвергается тогда, когда двигаемая нога осталась без ставки на КАЖДОМ форвардном
дне. Поэтому дню, отвергнутому парой ног, не помогает ни одна из них поодиночке, а
дню с двумя независимыми дырами хватает любой. Замер 15.09: поодиночке протоколы
поднимают 8 ACT-дней (ОБЪЕДИНЕНИЕ дней, не сумма счётчиков — день с двумя
независимыми дырами иначе считался бы дважды), вместе — 10, и разницу дают ровно
два дня, которым нужна ПАРА ног: 2026-08-25 и 2026-09-11. Трое протоколов
(``morpho_blue``, ``fluid_usdc``, ``spark_susds``) поодиночке не поднимают НИ ОДНОГО
и при этом НЕОБХОДИМЫ — без них день не поднимается никаким набором остальных;
и наоборот, ``compound_v3`` поднимает день в одиночку, но необходим НИ ДЛЯ ОДНОГО
(у 2026-08-11 две независимые дыры, и хватает любой). Ранжировать протоколы по
«сколько поднимает один» значило бы поставить необходимые последними.

Поэтому у каждого протокола докладываются ТРИ разные величины, и ни одна не выводима
из другой: ``alone`` (поднимает в одиночку), ``necessary`` (без него день не
поднимается) и ``union`` (что даёт набор целиком).

## Слово «АДАПТЕРОВ» в заказе прибор ПРОВЕРЯЕТ, а не принимает

Заказ назвал починку адаптерной. Рычаг у каждой пары «форвардный день × нога» уже
измерен соседом (``unobserved_leg_remedy_class``, заказ #590/G7), и берётся он оттуда
ПО ИСХОДУ, а не переписывается: замер 15.09 говорит, что из восьми дней семь
упираются в НАШ код (``writer_universe`` — строка отсечения по universe у писателя;
``key_mismatch`` — ``fluid_usdc`` против ``fluid_fusdc``, два имени одних денег), и
ровно один день (2026-08-24) несёт ногу с рычагом у владельца (``needs_polling``) —
да и тот требует ПАРЫ и адаптерной работой в одиночку не покупается.

Это ответ на заказ, а не возражение ему: цена измерена, а адресат у неё оказался
другим. Сосед считает ту же слепоту в ДОЛЛАРАХ ОБОРОТА; здесь — в ACT-днях.

**ADVISORY.** Прибор ничего не чинит и ничего не гейтит: ни ``POLLED_ADAPTERS``, ни
``ADAPTER_REGISTRY``, ни писателя журнала, ни ``load_history``, ни ``hit_rate``, ни
``MIN_HIT_RATE``, ни ``TriggerParams``, ни пороги RiskPolicy v1.0, ни потолки
концентрации, ни стоп-кран, ни живой трек, ни ``landing/``. Капитал не двигается.
Живое ``data/`` открывается на запись ровно один раз — для собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.adapter_repair_price")

VERSION = "adapter-repair-price-v1"
OUTPUT_FILENAME = "adapter_repair_price.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Ставка, которой возмущение делает ногу ОЦЕНИМОЙ. Ноль выбран не «для простоты»:
#: при нём вклад ноги в ``benefit`` равен ровно нулю, то есть выдаётся право быть
#: оценённым и НЕ выдаётся доходность (конвенция ADR-299).
_PRICING_SENTINEL_PCT = 0.0

#: Сентинелы контроля безразличия. Отрицательный обязателен: именно он показывает,
#: что знак ``net`` под грантом — свойство подстановки, а не мира.
_SENTINEL_CONTROL_PCT: Tuple[float, ...] = (0.0, 25.0, -25.0)

#: Форма свёртки ёмкостного стенда. Взята та же, которой [ADR-386] мерил цену судьи,
#: иначе числа были бы несравнимы — а заказ требует ОДНОЙ валюты.
_CAPACITY_FORM = "first_act_row"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── причина и определение критерия берутся у канонических владельцев ──────────
def _refusal_reason() -> Tuple[Optional[str], str]:
    """Имя причины — у соседа, который её уже объявил публично.

    Своего литерала здесь нет намеренно: строка причины принадлежит судье, и вторая
    её копия разошлась бы с первой молча (обе печатали бы число, ни одна — правило).
    """
    try:
        from spa_core.monitoring.unobserved_turnover_dependence import REFUSAL_REASON
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return None, f"имя причины не прочитано: {type(exc).__name__}: {exc}"
    if not isinstance(REFUSAL_REASON, str) or not REFUSAL_REASON:
        return None, "имя причины у соседа пусто — читать нечего"
    return REFUSAL_REASON, ""


class _CountingLoader:
    """Загрузчик журнала для реплея + СЧЁТЧИК достижимости.

    Счётчик существует потому, что «подмена не дотянулась» и «ничего не изменилось»
    выглядят одинаково и значат разное: ноль вызовов — ``unmeasured``, а не ноль.
    """

    def __init__(self, rows: Sequence[dict]) -> None:
        self.rows = list(rows)
        self.calls = 0

    def __call__(self, data_dir, book_id=None):  # noqa: ARG002 — сигнатура судьи
        self.calls += 1
        return list(self.rows), 0


def ask_judge(data_dir: Path,
              rows: Sequence[dict]) -> Tuple[Optional[dict], str]:
    """Спросить НАСТОЯЩЕГО судью о заданном журнале. Только чтение.

    Подменяется ровно один атрибут — загрузчик журнала; всё остальное в
    ``evaluate_window`` работает как в проде, поэтому ответ есть утверждение о
    поверхности решения, а не о копии её логики.
    """
    from spa_core.paper_trading import shadow_trigger_eval as judge

    original = judge.load_history
    loader = _CountingLoader(rows)
    judge.load_history = loader
    try:
        doc = judge.evaluate_window(Path(data_dir), write=False)
    except BaseException as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return None, f"судья упал: {type(exc).__name__}: {exc}"
    finally:
        judge.load_history = original
    if loader.calls == 0:
        return None, "подменённый загрузчик не вызван ни разу — реплей не дотянулся"
    return doc, ""


def grant(rows: Sequence[dict], protocols: Sequence[str],
          pct: float = _PRICING_SENTINEL_PCT) -> List[dict]:
    """Копия журнала, где названным протоколам выдано ПРАВО быть оценёнными.

    Существующая ставка НЕ переписывается ни при каком ``pct``: возмущение
    заполняет дыру, а не подменяет наблюдение. Иначе прибор менял бы числа,
    которые фид честно наблюдал, и ответ перестал бы быть о дырах.
    """
    out: List[dict] = []
    for rec in rows:
        clone = copy.deepcopy(rec)
        # `or {}` здесь был бы членом класса инв. #17 — и не потому, что менял
        # бы ПОВЕДЕНИЕ (дыру у записи без секции и у записи с пустой секцией
        # заполнять надо одинаково), а потому, что склеивал бы два разных
        # наблюдения в одно выражение. Третий исход существует и назван.
        seen = observed(clone, "apy_evidenced_pct", kind=dict)
        rates: Dict[str, object] = {} if seen is None else dict(seen)
        for protocol in protocols:
            if rates.get(protocol) is None:
                rates[protocol] = pct
        clone["apy_evidenced_pct"] = rates
        out.append(clone)
    return out


# ── (а) дни, неоценимые этой причиной, КАК ОНИ ЛЕЖАТ ──────────────────────────
def blocked_days(report: dict, reason: str) -> List[dict]:
    """Строки судьи, отвергнутые названной причиной. Население — у судьи."""
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)
            and str(r.get("unchecked_reason") or "") == reason]


def capital_on_rejecting(record: dict, rejecting: Sequence[str]) -> dict:
    """Капитал дня, стоящий на отвергающих ногах — ДЕРЖИМЫЙ и ЦЕЛЕВОЙ отдельно.

    Две величины, а не одна, потому что нога-отказчик бывает целевой: капитал на
    ней ещё не стои́т, он туда СОБИРАЛСЯ. Сложить их значило бы посчитать одни
    деньги дважды у дня, где нога и держится, и докупается; выдать одну за обе —
    промолчать о половине вопроса. Знаменатель назван у каждой.
    """
    held_map = record.get("current_positions") or {}
    target_map = record.get("target_positions") or {}
    rej = set(rejecting)

    def _sum(book: dict, keys: Set[str]) -> float:
        total = 0.0
        for key in keys:
            try:
                total += float(book.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                log.warning("нечисловая позиция `%s` в книге — пропущена", key)
        return total

    deployed = _sum(held_map, set(held_map))
    capital = observed(record, "capital_usd", kind=(int, float))
    held = _sum(held_map, rej)
    targeted = _sum(target_map, rej)
    return {
        "held_usd": round(held, 2),
        "deployed_usd": round(deployed, 2),
        "held_pct_of_deployed": (round(100.0 * held / deployed, 2)
                                 if deployed else None),
        "targeted_usd": round(targeted, 2),
        "capital_usd": (round(float(capital), 2) if capital is not None else None),
        "targeted_pct_of_capital": (round(100.0 * targeted / float(capital), 2)
                                    if capital else None),
    }


# ── (б) протоколы поимённо ────────────────────────────────────────────────────
def named_protocols(row: dict) -> Optional[List[str]]:
    """Ноги, названные судьёй в строке. ``None`` — поля НЕТ ВОВСЕ.

    Пустой список и отсутствие поля — РАЗНЫЕ наблюдения (инв. #17): первое
    говорит «судья посмотрел и не назвал ни одной», второе — «строка судьи
    этого не несёт». Прежнее ``row.get("unpriced_protocols") or []`` сливало
    их, и перепись докладывала «причину не даёт никто» о дне, который этой же
    причиной и отвергнут, — то есть ровно «наблюдения нет ⇒ всё хорошо».
    """
    named = observed(row, "unpriced_protocols", kind=list)
    return None if named is None else [str(p) for p in named]


def days_without_named_protocols(blocked: Sequence[dict]) -> List[str]:
    """Дни, отвергнутые причиной, но НЕ несущие поля ``unpriced_protocols``.

    Третий исход переписи. Пустой список здесь — измеренный ноль: население
    прочитано и таких дней не нашлось.
    """
    return sorted({str(row.get("cycle_date")) for row in blocked
                   if named_protocols(row) is None})


def protocol_census(blocked: Sequence[dict]) -> List[dict]:
    """Кто даёт причину и сколько раз — из ``unpriced_protocols`` самого судьи.

    Строка БЕЗ поля в перепись не входит и молча нулём не становится: её
    называет `days_without_named_protocols`, и отчёт печатает это отдельно.
    """
    counts: Dict[str, List[str]] = {}
    for row in blocked:
        day = str(row.get("cycle_date"))
        named = named_protocols(row)
        if named is None:
            continue
        for protocol in named:
            counts.setdefault(protocol, []).append(day)
    return [{"protocol": name, "days_named": len(days), "days": sorted(days)}
            for name, days in sorted(counts.items(),
                                     key=lambda kv: (-len(kv[1]), kv[0]))]


# ── (в)₁ сегодняшнее чтение: дифференциально, по одному и все вместе ──────────
def _criterion_days(report: dict) -> Set[str]:
    """Дни, ДОШЕДШИЕ до критерия №3 в этом отчёте судьи.

    Определение — то же, что у ``judge_alone_price.capacity``: вердикт ``ACT`` И
    исход в ``hit``/``miss``. Вторая копия правила здесь была бы ровно тем
    молчаливым спором, против которого написан весь ряд G15–G18.
    """
    out: Set[str] = set()
    for row in (report.get("per_verdict") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("verdict") or "").upper() != "ACT":
            continue
        if row.get("outcome") in ("hit", "miss"):
            out.add(str(row.get("cycle_date")))
    return out


def _scored_days(report: dict) -> Set[str]:
    """Дни в знаменателе ``hit_rate`` — СОСЕДНИЙ критерий, и он назван отдельно."""
    out: Set[str] = set()
    for row in (report.get("per_verdict") or []):
        if isinstance(row, dict) and not row.get("trivial") \
                and row.get("outcome") in ("hit", "miss"):
            out.add(str(row.get("cycle_date")))
    return out


def today_price(data_dir: Path, rows: Sequence[dict], protocols: Sequence[str],
                reason: str) -> dict:
    """Сколько ACT-дней возвращает критерию грант — на журнале КАК ОН ЛЕЖИТ."""
    base, why = ask_judge(data_dir, rows)
    if base is None:
        return {"measured": False, "reason": why}
    base_criterion = _criterion_days(base)
    base_scored = _scored_days(base)
    base_blocked = {str(r.get("cycle_date")) for r in blocked_days(base, reason)}

    per_protocol: List[dict] = []
    refused: List[str] = []
    for protocol in protocols:
        doc, why = ask_judge(data_dir, grant(rows, [protocol]))
        if doc is None:
            refused.append(f"{protocol}: {why}")
            continue
        per_protocol.append({
            "protocol": protocol,
            "criterion_days_gained": sorted(_criterion_days(doc) - base_criterion),
            "scored_days_gained": sorted(_scored_days(doc) - base_scored),
            "blocked_days_cleared": sorted(
                base_blocked - {str(r.get("cycle_date"))
                                for r in blocked_days(doc, reason)}),
        })

    union, why = ask_judge(data_dir, grant(rows, list(protocols)))
    if union is None:
        return {"measured": False, "reason": f"грант всего набора: {why}"}
    return {
        "measured": True,
        "criterion_days_baseline": len(base_criterion),
        "act_days_returned_by_full_grant": len(_criterion_days(union)
                                               - base_criterion),
        "scored_days_returned_by_full_grant": len(_scored_days(union) - base_scored),
        "blocked_days_baseline": len(base_blocked),
        "blocked_days_cleared_by_full_grant": len(
            base_blocked - {str(r.get("cycle_date"))
                            for r in blocked_days(union, reason)}),
        "per_protocol": per_protocol,
        "refused": refused,
        "why_zero_is_expected": (
            "критерий №3 (`net_bps_if_followed`, мандат ADR-067) может быть закрыт "
            "только ОЦЕНЁННЫМ вердиктом ACT; в журнале, как он лежит, ACT нет ни "
            "одного, поэтому ставки поднимают дни в знаменатель `hit_rate` "
            "(критерий №2, давно PASS) и до критерия №3 не доносят ни одного"),
    }


# ── (в)₂ ёмкостный стенд: та же валюта, что у писателя и судьи ────────────────
def _capacity_of(source: Path, dest: Path, rows: Sequence[dict]) -> Tuple[Optional[dict], str]:
    """Один прогон ёмкостного стенда соседа. Живой каталог только читается."""
    try:
        from spa_core.monitoring import judge_alone_price as jap
    except Exception as exc:  # noqa: BLE001
        return None, f"ёмкостный стенд не импортирован: {type(exc).__name__}: {exc}"
    try:
        carousel = jap._Carousel(Path(source), Path(dest), rows)
        return jap.capacity(carousel, form=_CAPACITY_FORM), ""
    except BaseException as exc:  # noqa: BLE001
        return None, f"ёмкостный стенд отказал: {type(exc).__name__}: {exc}"


def capacity_price(data_dir: Path, rows: Sequence[dict],
                   protocols: Sequence[str], workdir: Path) -> dict:
    """Дифференциальная цена гранта на стенде «писатель починен» ([ADR-386])."""
    base, why = _capacity_of(data_dir, workdir / "base", rows)
    if base is None:
        return {"measured": False, "reason": why}
    base_days = {d["day"] for d in (base.get("days") or [])}

    per_protocol: List[dict] = []
    refused: List[str] = []
    for protocol in protocols:
        cap, why = _capacity_of(data_dir, workdir / f"one_{protocol}",
                                grant(rows, [protocol]))
        if cap is None:
            refused.append(f"{protocol}: {why}")
            continue
        per_protocol.append({
            "protocol": protocol,
            "act_days_alone": sorted({d["day"] for d in (cap.get("days") or [])}
                                     - base_days),
        })

    union, why = _capacity_of(data_dir, workdir / "union",
                              grant(rows, list(protocols)))
    if union is None:
        return {"measured": False, "reason": f"грант всего набора: {why}"}
    union_days = {d["day"] for d in (union.get("days") or [])} - base_days

    # НЕОБХОДИМОСТЬ меряется исключением, а не вычитанием: «поднимает 0 в одиночку»
    # и «не нужен» — разные утверждения, и именно их смешение поставило бы
    # необходимые протоколы последними в любом ранжировании по `alone`.
    for row in per_protocol:
        rest = [p for p in protocols if p != row["protocol"]]
        cap, why = _capacity_of(data_dir, workdir / f"less_{row['protocol']}",
                                grant(rows, rest))
        if cap is None:
            row["necessary_for"] = None
            row["necessity_unmeasured_reason"] = why
            continue
        without = {d["day"] for d in (cap.get("days") or [])} - base_days
        row["necessary_for"] = sorted(union_days - without)

    alone_union: Set[str] = set()
    for row in per_protocol:
        alone_union.update(row.get("act_days_alone") or [])
    return {
        "measured": True,
        "form": _CAPACITY_FORM,
        "criterion_days_baseline": base.get("reaches_criterion"),
        "criterion_days_baseline_material": base.get("reaches_criterion_material"),
        "act_days_returned_by_full_grant": len(union_days),
        "act_days_returned_by_full_grant_list": sorted(union_days),
        "act_days_returned_if_taken_one_by_one": len(alone_union),
        "superadditive_days": sorted(union_days - alone_union),
        "per_protocol": per_protocol,
        "refused": refused,
        "net_positive_days": None,
        "net_positive_unmeasured_reason": (
            "знак `net` под грантом есть функция ПОДСТАВЛЕННОЙ ставки, а не "
            "наблюдения: контроль сентинелов ниже показывает 0 / 1 / 6 окупающихся "
            "дней при 0 / +25 / −25 пп на одном и том же наборе. Докладывать это "
            "число значило бы выдать свойство сентинела за свойство мира"),
    }


def sentinel_control(data_dir: Path, rows: Sequence[dict],
                     protocols: Sequence[str], workdir: Path) -> dict:
    """Безразличен ли ответ к ПОДСТАВЛЕННОМУ числу — замером, а не обещанием.

    Контроль в обе стороны: ``reaches_criterion`` обязан совпасть на всех
    сентинелах (иначе ответ прибора выдуман), а ``net>0`` обязан РАЗОЙТИСЬ — иначе
    отказ докладывать знак был бы предосторожностью без предмета, то есть
    украшением.
    """
    runs: List[dict] = []
    for pct in _SENTINEL_CONTROL_PCT:
        cap, why = _capacity_of(data_dir, workdir / f"sent_{pct}",
                                grant(rows, list(protocols), pct))
        if cap is None:
            return {"measured": False, "reason": f"сентинел {pct}: {why}"}
        runs.append({"sentinel_pct": pct,
                     "reaches_criterion": cap.get("reaches_criterion"),
                     "net_positive": cap.get(
                         "reaches_criterion_material_net_positive")})
    answers = {r["reaches_criterion"] for r in runs}
    signs = {r["net_positive"] for r in runs}
    return {
        "measured": True,
        "runs": runs,
        "answer_invariant": len(answers) == 1,
        "sign_varies": len(signs) > 1,
        "note": ("первая строка — ответ прибора и он безразличен к сентинелу; "
                 "вторая — причина, по которой знак `net` не докладывается вовсе"),
    }


# ── рычаг у каждого протокола: берётся у соседа ПО ИСХОДУ ─────────────────────
def remedy_by_protocol(data_dir: Path) -> dict:
    """Чем чинится каждая названная нога — ответ соседа #590/G7, не своя копия.

    Заказ назвал починку адаптерной; проверить это утверждение обязан прибор, а не
    читатель. Сосед уже разложил каждую пару «форвардный день × нога» по рычагам,
    поэтому здесь его ОТВЕТ и читается — переписывать правило значило бы завести
    второй классификатор, который разойдётся с первым молча.
    """
    try:
        from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"классификатор рычагов не импортирован: {exc}"}
    try:
        doc = _remedy.measure(Path(data_dir))
    except BaseException as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"классификатор рычагов отказал: {type(exc).__name__}: {exc}"}
    by_protocol: Dict[str, Set[str]] = {}
    for day in (doc.get("per_day") or []):
        for leg in (day.get("legs") or []):
            protocol = str(leg.get("protocol"))
            remedy = str(leg.get("remedy"))
            by_protocol.setdefault(protocol, set()).add(remedy)
    if not by_protocol:
        return {"measured": False,
                "reason": "классификатор не назвал ни одной ноги — читать нечего"}
    return {"measured": True,
            "source": "unobserved_leg_remedy_class.measure",
            "by_protocol": {k: sorted(v) for k, v in sorted(by_protocol.items())}}


# ── замер ─────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            with_capacity: bool = True, **_ignored) -> dict:
    """Цена починки адаптеров в ACT-днях. Только чтение (кроме своего стенда).

    ``_ignored`` — совместимость с зовущей ступенью переписей, передающей общие для
    всех приборов ключи. Глотать их молча безопасно ровно потому, что ни один не
    участвует в замере: появись здесь значащий параметр, он обязан быть назван.
    """
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or _utcnow()).isoformat(),
        "mode": "ADVISORY",
        "order": "#606/G19 — цена починки адаптеров в ACT-днях до критерия",
        "currency": ("ACT-дни до критерия №3 (`net_bps_if_followed`, ADR-067) — та "
                     "же валюта, что у цены писателя (ADR-383) и судьи (ADR-386); "
                     "определение «дошёл до критерия» взято у "
                     "judge_alone_price.capacity, своей копии здесь нет"),
    }

    reason, why = _refusal_reason()
    if reason is None:
        doc.update({"status": STATUS_UNMEASURED, "headline": why})
        return doc
    doc["refusal_reason"] = reason

    try:
        from spa_core.paper_trading import shadow_trigger_eval as judge
        rows, bad_lines = judge.load_history(data_dir)
    except BaseException as exc:  # noqa: BLE001
        doc.update({"status": STATUS_UNMEASURED,
                    "headline": f"журнал не прочитан: {type(exc).__name__}: {exc}"})
        return doc
    if not rows:
        doc.update({"status": STATUS_UNMEASURED,
                    "headline": "журнал решений пуст — мерить нечего"})
        return doc
    doc["journal"] = {"rows": len(rows), "corrupt_lines": bad_lines,
                      "first_day": str(rows[0].get("cycle_date")),
                      "last_day": str(rows[-1].get("cycle_date"))}

    report, why = ask_judge(data_dir, rows)
    if report is None:
        doc.update({"status": STATUS_UNMEASURED,
                    "headline": f"судья не ответил: {why}"})
        return doc

    # ── (а) ──────────────────────────────────────────────────────────────────
    by_date = {str(r.get("cycle_date")): r for r in rows}
    blocked = blocked_days(report, reason)
    days_out: List[dict] = []
    held_total = deployed_total = targeted_total = capital_total = 0.0
    capital_days_measured = 0
    capital_unmeasured_days: List[str] = []
    for row in blocked:
        day = str(row.get("cycle_date"))
        record = by_date.get(day)
        named = named_protocols(row)
        rejecting = [] if named is None else named
        legs_unmeasured = ("строка судьи не несёт `unpriced_protocols` — ноги "
                           "дня НЕ НАЗВАНЫ, а не отсутствуют"
                           if named is None else None)
        if record is None:
            capital_unmeasured_days.append(day)
            days_out.append({"day": day, "rejecting_legs": rejecting,
                             "rejecting_legs_unmeasured_reason": legs_unmeasured,
                             "capital": None,
                             "capital_unmeasured_reason":
                                 "строки дня нет в журнале — книга не прочитана"})
            continue
        cap = capital_on_rejecting(record, rejecting)
        held_total += cap["held_usd"]
        deployed_total += cap["deployed_usd"]
        targeted_total += cap["targeted_usd"]
        # Капитал дня, которого книга НЕ НЕСЁТ, не есть капитал, равный нулю
        # (инв. #17). Прежнее `or 0.0` клало ненаблюдённый день в знаменатель
        # `targeted_pct_of_capital` нулём: доля считалась бы от суммы, часть
        # слагаемых которой не измерена, и сказать об этом было бы некому.
        day_capital = cap["capital_usd"]
        if day_capital is None:
            capital_unmeasured_days.append(day)
        else:
            capital_total += day_capital
            capital_days_measured += 1
        days_out.append({"day": day, "verdict": row.get("verdict"),
                         "rejecting_legs": rejecting,
                         "rejecting_legs_unmeasured_reason": legs_unmeasured,
                         "forward_days_available": row.get("forward_days_available"),
                         "capital": cap})
    doc["blocked_days"] = {
        "count": len(blocked),
        "of_journal_days": report.get("observation_days"),
        "days": days_out,
        "capital_on_rejecting_legs": {
            "held_usd": round(held_total, 2),
            "deployed_usd": round(deployed_total, 2),
            "held_pct_of_deployed": (round(100.0 * held_total / deployed_total, 2)
                                     if deployed_total else None),
            "targeted_usd": round(targeted_total, 2),
            # Ноль ИЗМЕРЕННЫХ дней — не ноль долларов: сумма по пустому
            # населению есть отсутствие наблюдения, а не наблюдение нуля.
            "capital_usd": (round(capital_total, 2)
                            if capital_days_measured else None),
            "capital_days_measured": capital_days_measured,
            "capital_unmeasured_days": sorted(set(capital_unmeasured_days)),
            # Доля от НЕПОЛНОГО знаменателя — число, отвечающее не на свой
            # вопрос. Есть хоть один день без наблюдённого капитала ⇒ доля
            # не докладывается вовсе.
            "targeted_pct_of_capital": (
                round(100.0 * targeted_total / capital_total, 2)
                if capital_total and not capital_unmeasured_days else None),
            "note": ("доля КАПИТАЛА книги, а не оборота: сосед #587/G6 делит ход "
                     "отвергающих ног на оборот того же дня, и это другая ось. "
                     "Итоги двух осей на сегодняшнем населении СОВПАДАЮТ до "
                     "доллара, а по дням расходятся — совпадение итогов не есть "
                     "совпадение величин"),
        },
    }

    # ── (б) ──────────────────────────────────────────────────────────────────
    census = protocol_census(blocked)
    doc["protocols"] = census
    # Третий исход переписи (б): дни, чья строка судьи поля НЕ НЕСЁТ. Пустой
    # список — измеренный ноль, непустой — «перепись неполна», и это разные
    # утверждения, которые до сих пор выглядели одинаково.
    doc["protocols_unmeasured_days"] = days_without_named_protocols(blocked)
    protocols = [row["protocol"] for row in census]
    doc["remedy"] = remedy_by_protocol(data_dir)

    # ── (в) ──────────────────────────────────────────────────────────────────
    doc["returns_today"] = today_price(data_dir, rows, protocols, reason)
    if with_capacity and protocols:
        workdir = Path(tempfile.mkdtemp(prefix="spa_g19_"))
        try:
            doc["capacity"] = capacity_price(data_dir, rows, protocols, workdir)
            doc["sentinel_control"] = sentinel_control(data_dir, rows, protocols,
                                                       workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    else:
        doc["capacity"] = None
        doc["capacity_unmeasured_reason"] = (
            "ёмкость не мерилась: with_capacity=False" if protocols
            else "ёмкость не мерилась: причина не названа ни одним протоколом")
        doc["sentinel_control"] = None

    doc["what_it_does_not_prove"] = [
        "какой вердикт день получил бы под грантом: исход `hit`/`miss` под "
        "сентинелом есть артефакт сентинела, а не наблюдение",
        "окупается ли хоть один поднятый день: знак `net` под грантом — функция "
        "подставленной ставки (контроль сентинелов это и показывает)",
        "что живая ставка у названного протокола ПОЯВИТСЯ: прибор мерит цену "
        "починки, а не её осуществимость",
        "верность исхода дня и величину `hit_rate`: ни то, ни другое здесь не "
        "пересчитывается",
    ]
    doc.update(_verdict(doc))
    return doc


def _verdict(doc: dict) -> dict:
    today = observed(doc, "returns_today", kind=dict) or {}
    cap = observed(doc, "capacity", kind=dict)
    control = observed(doc, "sentinel_control", kind=dict)
    blocked = observed(doc, "blocked_days", kind=dict) or {}

    if not today.get("measured"):
        return {"status": STATUS_UNMEASURED,
                "headline": ("сегодняшнее чтение НЕ ИЗМЕРЕНО: "
                             + str(today.get("reason", "причина не названа")))}
    if cap is not None and not cap.get("measured"):
        return {"status": STATUS_UNMEASURED,
                "headline": ("ёмкость НЕ ИЗМЕРЕНА: "
                             + str(cap.get("reason", "причина не названа")))}
    if control is not None:
        if not control.get("measured"):
            return {"status": STATUS_UNMEASURED,
                    "headline": ("контроль сентинелов НЕ ИЗМЕРЕН: "
                                 + str(control.get("reason", "причина не названа")))}
        if not control.get("answer_invariant"):
            return {"status": STATUS_UNMEASURED,
                    "headline": ("ответ прибора ЗАВИСИТ от подставленной ставки — "
                                 "числа ниже недействительны, а не «примерны»")}

    today_days = today.get("act_days_returned_by_full_grant")
    if not blocked.get("count"):
        return {"status": STATUS_OK,
                "headline": ("ни один день журнала не отвергнут этой причиной — "
                             "цены у починки нет, потому что чинить нечего")}
    if cap is None:
        return {"status": STATUS_WARNING,
                "headline": (f"сегодня критерию возвращается {today_days} ACT-дн. "
                             f"при {blocked.get('count')} отвергнутых днях; ёмкость "
                             "не мерилась — сегодняшний ноль за полный ответ "
                             "выдавать нельзя")}
    cap_days = cap.get("act_days_returned_by_full_grant")
    if today_days == 0 and cap_days:
        return {"status": STATUS_CRITICAL,
                "headline": (
                    f"починка ВСЕХ {len(doc.get('protocols') or [])} названных "
                    f"протоколов возвращает критерию СЕГОДНЯ {today_days} ACT-дн., "
                    f"а при починенном писателе — {cap_days}; порядок починок, "
                    "следовательно, не свободен, и адаптеры в нём не первые")}
    return {"status": STATUS_WARNING,
            "headline": (f"сегодня критерию возвращается {today_days} ACT-дн., "
                         f"на ёмкостном стенде — {cap_days}")}


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Порядок строк — порядок вопроса."""
    out = [f"   цена починки адаптеров в ACT-днях (заказ #606/G19): "
           f"{doc.get('status')}"]
    if doc.get("headline"):
        out.append(f"   [ОТВЕТ] {doc['headline']}")

    blocked = observed(doc, "blocked_days", kind=dict)
    if blocked is None:
        out.append("   [а] ⚠️ НЕ ИЗМЕРЕНО: населения отвергнутых дней в отчёте нет")
    else:
        capital = observed(blocked, "capital_on_rejecting_legs", kind=dict)
        if capital is None:
            out.append("   [а] ⚠️ НЕ ИЗМЕРЕНО: секции капитала на отвергающих "
                       "ногах в отчёте нет — печатать здесь нули значило бы "
                       "выдать непрочитанное за пустую книгу")
        else:
            cap_usd = capital.get("capital_usd")
            out.append(f"   [а] дней журнала отвергнуто причиной: "
                       f"{blocked.get('count')} из {blocked.get('of_journal_days')}; "
                       f"на отвергающих ногах держалось "
                       f"${capital.get('held_usd', 0):,.0f} из "
                       f"${capital.get('deployed_usd', 0):,.0f} развёрнутых = "
                       f"{capital.get('held_pct_of_deployed')} % книги, и ещё "
                       f"${capital.get('targeted_usd', 0):,.0f} туда ЦЕЛИЛОСЬ")
            # Список ненаблюдённых дней ОТСУТСТВУЕТ ⇒ отчёт старого образца, и
            # это не «таких дней нет». Пустой список — измеренный ноль.
            unmeasured = observed(capital, "capital_unmeasured_days", kind=list)
            if unmeasured is None:
                out.append("   [а] ⚠️ НЕ ИЗМЕРЕНО: отчёт не несёт списка дней без "
                           "наблюдённого капитала — полон ли знаменатель, "
                           "сказать нечем")
            elif cap_usd is None or unmeasured:
                total_s = ("НЕ ДОКЛАДЫВАЕТСЯ" if cap_usd is None
                           else f"${cap_usd:,.0f} только по измеренным дням")
                out.append(f"   [а] ⚠️ капитал книги НЕ ИЗМЕРЕН на "
                           f"{len(unmeasured)} дн. ({', '.join(unmeasured) or '—'}) "
                           f"⇒ итог по нему {total_s}, доля «целилось от "
                           f"капитала» — тоже")
        days = observed(blocked, "days", kind=list)
        if days is None:
            out.append("   [ПО ДНЯМ] ⚠️ НЕ ИЗМЕРЕНО: списка дней в отчёте нет")
        for day in (days or []):
            cap = observed(day, "capital", kind=dict)
            legs = day.get("rejecting_legs")
            legs_s = (", ".join(legs) if legs else
                      ("НЕ НАЗВАНЫ" if day.get("rejecting_legs_unmeasured_reason")
                       else "—"))
            if cap is None:
                out.append(f"   [ПО ДНЯМ] {day.get('day')}: ноги {legs_s} · "
                           f"⚠️ капитал НЕ ИЗМЕРЕН: "
                           f"{day.get('capital_unmeasured_reason', 'причина не названа')}")
                continue
            out.append(f"   [ПО ДНЯМ] {day.get('day')}: ноги {legs_s} · "
                       f"держалось ${cap.get('held_usd', 0):,.0f} "
                       f"({cap.get('held_pct_of_deployed')} % развёрнутой) · "
                       f"целилось ${cap.get('targeted_usd', 0):,.0f}")

    remedy = observed(doc, "remedy", kind=dict) or {}
    by_protocol = (remedy.get("by_protocol") or {}) if remedy.get("measured") else {}
    for row in (doc.get("protocols") or []):
        levers = by_protocol.get(row["protocol"])
        lever = ", ".join(levers) if levers else "рычаг НЕ ИЗМЕРЕН"
        out.append(f"   [б] {row['protocol']}: назван {row['days_named']} дн. "
                   f"({', '.join(row['days'])}) · рычаг: {lever}")
    blind = doc.get("protocols_unmeasured_days")
    if blind is None:
        out.append("   [б] ⚠️ НЕ ИЗМЕРЕНО: дни без названных ног не пересчитаны — "
                   "перепись (б) может быть неполной, и сказать насколько нечем")
    elif blind:
        out.append(f"   [б] ⚠️ перепись НЕПОЛНА: у {len(blind)} дн. строка судьи "
                   f"не несёт `unpriced_protocols` ({', '.join(blind)}) — это НЕ "
                   "«причину не даёт никто»")
    if not remedy.get("measured"):
        out.append(f"   [б] ⚠️ рычаги НЕ ИЗМЕРЕНЫ: "
                   f"{remedy.get('reason', 'причина не названа')} — слово "
                   "«адаптеров» из заказа осталось НЕПРОВЕРЕННЫМ")

    today = observed(doc, "returns_today", kind=dict) or {}
    if today.get("measured"):
        out.append(f"   [в·сегодня] грант всего набора возвращает критерию "
                   f"{today.get('act_days_returned_by_full_grant')} ACT-дн.; "
                   f"в знаменатель `hit_rate` — "
                   f"{today.get('scored_days_returned_by_full_grant')} дн.; "
                   f"снято отказов {today.get('blocked_days_cleared_by_full_grant')} "
                   f"из {today.get('blocked_days_baseline')}")
        out.append(f"   [в·сегодня] почему ноль: {today.get('why_zero_is_expected')}")
    else:
        out.append(f"   [в·сегодня] ⚠️ НЕ ИЗМЕРЕНО: "
                   f"{today.get('reason', 'причина не названа')}")

    cap = observed(doc, "capacity", kind=dict)
    if cap is None:
        out.append("   [в·ёмкость] ⚠️ НЕ ИЗМЕРЕНА: "
                   + str(doc.get("capacity_unmeasured_reason",
                                 "причина не названа")))
    elif not cap.get("measured"):
        out.append(f"   [в·ёмкость] ⚠️ НЕ ИЗМЕРЕНА: "
                   f"{cap.get('reason', 'причина не названа')}")
    else:
        out.append(f"   [в·ёмкость] при починенном писателе грант набора возвращает "
                   f"{cap.get('act_days_returned_by_full_grant')} ACT-дн. "
                   f"(база стенда {cap.get('criterion_days_baseline')}); "
                   f"поодиночке — {cap.get('act_days_returned_if_taken_one_by_one')}, "
                   f"и разницу дают дни, которым нужна ПАРА: "
                   f"{', '.join(cap.get('superadditive_days') or []) or '—'}")
        for row in (cap.get("per_protocol") or []):
            alone = row.get("act_days_alone") or []
            need = row.get("necessary_for")
            need_s = (", ".join(need) if need else
                      ("НЕ ИЗМЕРЕНО" if need is None else "—"))
            out.append(f"   [в·ёмкость] {row['protocol']}: в одиночку {len(alone)} "
                       f"ACT-дн. · НЕОБХОДИМ для: {need_s}")
        out.append(f"   [в·ёмкость] знак `net` под грантом НЕ ДОКЛАДЫВАЕТСЯ: "
                   f"{cap.get('net_positive_unmeasured_reason')}")

    control = observed(doc, "sentinel_control", kind=dict)
    if control is not None and control.get("measured"):
        runs = " · ".join(f"{r['sentinel_pct']:+g} пп → дошло "
                          f"{r['reaches_criterion']}, окупилось {r['net_positive']}"
                          for r in (control.get("runs") or []))
        out.append(f"   [КОНТРОЛЬ] {runs}")
        out.append(f"   [КОНТРОЛЬ] ответ безразличен к сентинелу: "
                   f"{'ДА' if control.get('answer_invariant') else 'НЕТ'} · знак "
                   f"`net` расходится: "
                   f"{'ДА' if control.get('sign_varies') else 'НЕТ'}")
    elif control is not None:
        out.append(f"   [КОНТРОЛЬ] ⚠️ НЕ ИЗМЕРЕН: "
                   f"{control.get('reason', 'причина не названа')}")

    out.append("   НЕ ДОКЛАДЫВАЕТ: " + " · ".join(
        doc.get("what_it_does_not_prove") or ["границы не названы"]))
    out.append("   ADVISORY: `POLLED_ADAPTERS`, `ADAPTER_REGISTRY`, писатель "
               "журнала, `load_history`, `hit_rate`, `MIN_HIT_RATE`, пороги "
               "RiskPolicy v1.0, стоп-кран и живой трек НЕ трогаются — прибор "
               "только называет цену починки в ACT-днях")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, with_capacity: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, with_capacity=with_capacity)
    if write:
        atomic_save(doc, str(base / "data" / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", help="каталог данных (умолчание — data/ репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--no-capacity", action="store_true",
                    help="не мерить ёмкостный стенд (быстро, но ответ НЕПОЛОН)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    args = ap.parse_args(argv)

    if args.data_dir:
        doc = measure(Path(args.data_dir), with_capacity=not args.no_capacity)
        if not args.no_write:
            atomic_save(doc, str(Path(args.data_dir) / OUTPUT_FILENAME))
    else:
        doc = run(write=not args.no_write, with_capacity=not args.no_capacity)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n".join(format_report(doc)))
    return {STATUS_OK: 0, STATUS_WARNING: 0,
            STATUS_CRITICAL: 1}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
