#!/usr/bin/env python3
"""Сколько дней жило преимущество, которым ход был оправдан.

Критерий §49 `Persistence` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #702.

Дословно критерий звучит так: **«Transient APY spikes не вызывают ненужные
trades»**, §10 требует мерить устойчивость («duration above threshold», rolling
averages, mean reversion), §41 перечисляет `minimum persistence` среди
обязательных policy-configurable ограничений, а §-тест 2 задаёт форму вреда:
доходность цели `3 % → 12 %` на несколько минут и обратно ⇒ ожидается
`KEEP / DEFER`.

До этого прибора критерий был ПРОЗОЙ. «Модуль есть, тесты зелёные» ≠ «работает»
(`.claude/rules/acceptance.md`), а здесь и модуля нет: ни одной ручки про
устойчивость ставки в колонке владельца (ADR-060 §3) не существует — и это
прибор не утверждает, а ПЕЧАТАЕТ весь список ручек рядом с находкой.

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь: **срок жизни преимущества**. Ход берёт деньги из одних протоколов
(ноги-выходы) и кладёт в другие (ноги-входы). Преимущество хода на день `t` —
это разница наблюдённых ставок:

    преимущество(t) = взвешенная ставка ВХОДОВ(t) − взвешенная ставка ВЫХОДОВ(t)

Вес — доллары самого хода, ставки — наблюдённый ряд `apy_series_daily.json`
(единственный записанный материал о ставках прошлых дней; пропуск дня в нём
никогда не интерполируется). Срок жизни — число подряд идущих форвардных дней,
на которых преимущество осталось положительным. Порог здесь не число, а ЗНАК:
вопрос «существовала ли назавтра причина, по которой деньги переложили».

Операнд выбран, и выбор назван
------------------------------------------------------------------------------
Сравнивать можно двумя способами, и они отвечают на РАЗНЫЕ вопросы:

* ставка цели против ставки ПОКИНУТОГО источника (взято здесь) — «а стоило ли
  вообще перекладывать»: пока разность положительна, ход себя оправдывает, и
  исчезновение разности есть исчезновение причины хода;
* ставка цели против её же ставки в день хода — «а был ли у цели спайк».

Второй ближе к букве («transient APY spikes»), но на вопрос о ВРЕДЕ не
отвечает: цель может осесть, а источник осесть сильнее, и тогда ход всё равно
выгоден. Критерий владельца говорит про «ненужные trades», то есть про вред, —
поэтому взят первый операнд. Второй здесь НЕ измеряется, и это сказано вслух:
прибор, молчащий о том, какой из двух вопросов он решил, читается как ответ на
оба.

Почему мерить надо ИСХОД, а не наличие фильтра
------------------------------------------------------------------------------
Существующие защиты отвечают на другие вопросы, и ни одна — на этот:

| защита | что меряет | чего не видит |
|---|---|---|
| `min_gain_pp` (ADR-060 §3) | ВЕЛИЧИНУ преимущества в момент хода | сколько оно проживёт |
| `max_payback_days` | окупится ли ЦЕНА за 30 дней при ТОМ ЖЕ преимуществе | что преимущества через день уже нет |
| `min_hold_days` | что свежую позицию не выкинут 3 дня | что причина позиции умерла на первый день — тогда порог держит ОШИБКУ |
| `churn_damper` (ADR-168) | частоту ходов | устойчивость ставки |
| гистерезис (ADR-060 §3) | разворот ног | устойчивость ставки |

Ключевое: `max_payback_days` считает окупаемость по преимуществу, **взятому
константой на весь горизонт**. Утверждение «цена вернётся за N дней» верно
ровно настолько, насколько преимущество живёт N дней, и НИКТО этого потом не
перемеривал.

Цена хода в записи ОТСУТСТВУЕТ — и подставлять чужую нельзя
------------------------------------------------------------------------------
Замер 26.09: запись исполненного хода (`trades.json`) не несёт ни цены, ни
ожидаемого выигрыша, ни срока окупаемости. Рядом в
`allocation_rationale_history.jsonl` цена есть — но она принадлежит СОВЕТАТЕЛЬНОЙ
пробе того же дня, и ноги той пробы с ногами исполненного хода **не совпали ни
в один день из 27** (у большинства дней у пробы ног нет вовсе). Взять её ценой
хода значило бы ответить на свой вопрос вместо нужного.

Поэтому прибор цену НЕ подставляет и НЕ вычисляет: он меряет срок жизни
преимущества и сравнивает его с ГОРИЗОНТОМ ВЛАДЕЛЬЦА (`max_payback_days`,
`min_hold_days`). Невозможность воспроизвести §-тест 2 целиком названа вслух
третьим исходом (`test2_not_reproducible`), а не обойдена удобной подстановкой.

Породы находок не смешиваются
------------------------------------------------------------------------------
* ``died_before_min_hold`` — преимущество кончилось раньше, чем истёк
  минимальный срок удержания владельца. Здесь две ручки работают ДРУГ ПРОТИВ
  ДРУГА: `min_hold_days` запрещает выходить, а выходить уже не из чего —
  причина позиции исчезла;
* ``died_within_payback_horizon`` — преимущество кончилось внутри горизонта, за
  который цена обязана окупиться. Утверждение об окупаемости стояло на ставке,
  которой к тому времени не было;
* ``outlived_horizon`` — преимущество пережило горизонт. Претензии нет;
* ``unmeasured`` — ряда у ключа нет вовсе / ход раньше начала ряда /
  форвардных дней с полным материалом нет. **Это не ноль и не «чисто»**
  (инвариант #17), и причина называется у каждого хода отдельно.

Вердикт судит НАСТОЯЩЕЕ, история остаётся замером
------------------------------------------------------------------------------
Ход, чьё преимущество умерло в августе, умер навсегда: сторож, считающий всю
историю, красен НАВСЕГДА и учит себя игнорировать
(`.claude/rules/deployment.md`). Поэтому:

* **замер** — все ходы за всю историю журнала, с породой и сроком каждого.
  Печатается всегда, чтобы «сегодня тихо» не читалось как «такого не бывало»;
* **вердикт** — только ходы не старше горизонта владельца от `now`: их деньги
  могут и сейчас стоять на причине, которой больше нет. ``CRITICAL`` — такой
  ход есть; ``WARNING`` — в истории есть, свежих нет; ``OK`` — каждый измеримый
  ход пережил горизонт; ``UNMEASURED`` — не удалось померить ни один.

Слепота — утверждение о ПОСТРОЕНИИ (ручки про устойчивость нет ни одной, цены
хода в записи нет), и живёт она отдельным полем ``blind_spot_demonstrated``: от
недели тишины она не гаснет.

Прибор ТОЛЬКО ЧИТАЕТ: журнал ходов, ряд ставок, журнал решений, пороги и часы.
Ни `TriggerParams`, ни пороги RiskPolicy v1.0, ни стоп-кран, ни аллокатор, ни
живой трек он не трогает и ничего не чинит. **LLM запрещён** (инвариант #3).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.monitoring.book_oscillation_census import (
    ARTIFACT_NAME as OSCILLATION_ARTIFACT,
    STATUS_CRITICAL,
    STATUS_OK,
    STATUS_UNMEASURED,
    STATUS_WARNING,
    EXIT_UNMEASURED,
    derive_aliases,
    read_journal,
    _material,
)

#: Наблюдённый ряд ставок. Единственный записанный материал о ставках прошлых
#: дней; пропуск дня в нём — «фид молчал», и он НИКОГДА не интерполируется.
SERIES_NAME = "apy_series_daily.json"

#: Журнал решений — из него берётся СЛОВАРЬ гейтов, реально применённых к
#: деньгам. Это поведенческая популяция: чего в нём нет, того money-path не
#: спрашивал ни разу.
DECISIONS_NAME = "allocation_rationale_history.jsonl"

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "gain_persistence_census.json"

#: Чего прибор есть мера. Объявление живёт МОДУЛЬНОЙ константой, а не только внутри
#: доклада, ровно по одной причине: привязку «этот прибор есть мера этого критерия»
#: обязан уметь прочитать читатель, который прибор НЕ ЗАПУСКАЛ (сводка §49, проба
#: реестра `card_acceptance`). Пока строка существовала лишь в возврате
#: :func:`run_census`, спросить об этой привязке можно было только ценой прогона —
#: а на отказном пути (`measured=False`) и того нельзя: доклад отказа поля
#: `criterion` не несёт вовсе. Доклад теперь ССЫЛАЕТСЯ на константу, поэтому мест
#: у строки по-прежнему ОДНО (`.claude/rules/site-numbers.md`).
CRITERION = ("§49 Persistence — «Transient APY spikes не вызывают ненужные "
             "trades» (+ §10 duration above threshold, §41 minimum persistence)")

SPECIES_BEFORE_HOLD = "died_before_min_hold"
SPECIES_WITHIN_PAYBACK = "died_within_payback_horizon"
SPECIES_OUTLIVED = "outlived_horizon"
SPECIES_UNMEASURED = "unmeasured"

#: Поля записи хода, которые несли бы цену/ожидание. Ищутся по СОСТАВУ записи,
#: а не по догадке: список печатается в артефакте вместе с найденным.
COST_FIELDS = ("cost_usd", "cost", "fees_usd", "gas_usd",
               "expected_gain_pp", "gain_pp", "payback_days")


# ── пороги: колонка владельца, а не наши числа ───────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Горизонты владельца из ``TriggerParams.for_mode()`` (ADR-060 §3).

    Своих чисел у прибора нет ни одного (§22 приказа: «Все значения должны быть
    config/policy. **Не hardcode**»). Колонка недоступна ⇒ ``measured=False``,
    то есть ТРЕТИЙ исход: подставленное умолчание отвечало бы на свой вопрос.

    Здесь же измеряется и вторая половина находки — ПОЛНЫЙ список ручек. Он
    печатается целиком именно потому, что утверждение «ручки про устойчивость
    нет» проверяется читателем по списку, а не по нашему поиску подстроки.
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — горизонт окупаемости и "
                               f"минимальный срок удержания НЕ ИЗМЕРЕНЫ, подставлять свои "
                               f"нельзя (§22: «Все значения должны быть config/policy. "
                               f"Не hardcode»)")}
    try:
        min_hold_days = float(params.min_hold_days)
        max_payback_days = float(params.max_payback_days)
        min_leg_frac = float(params.min_leg_frac)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    fields = getattr(params, "__dataclass_fields__", None)
    dials = sorted(fields) if fields else sorted(
        k for k in vars(params) if not k.startswith("_"))
    return {"measured": True, "min_hold_days": min_hold_days,
            "max_payback_days": max_payback_days, "min_leg_frac": min_leg_frac,
            "mode": mode, "version": version, "dials": dials}


# ── наблюдённый ряд ставок ───────────────────────────────────────────────────

def read_series(data_dir: Path) -> Dict[str, Any]:
    """Ряд наблюдённых ставок с диска. Отсутствие/нечитаемость — третий исход."""
    path = Path(data_dir) / SERIES_NAME
    if not path.exists():
        return {"measured": False,
                "reason": (f"ряд наблюдённых ставок не найден: {path} — срок жизни "
                           f"преимущества мерить НЕЧЕМ, и это НЕ «преимущество жило»")}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"ряд ставок нечитаем ({path}): {type(exc).__name__}: {exc}"}
    raw = doc.get("series") if isinstance(doc, dict) else None
    if not isinstance(raw, dict) or not raw:
        return {"measured": False,
                "reason": (f"в {path} нет раздела `series` с точками ряда "
                           f"(тип {type(raw).__name__}) — НЕ ИЗМЕРЕНО")}
    series: Dict[str, Dict[str, float]] = {}
    for key, points in raw.items():
        if not isinstance(points, list):
            continue
        byday: Dict[str, float] = {}
        for point in points:
            if (isinstance(point, (list, tuple)) and len(point) >= 2
                    and isinstance(point[0], str)):
                value = point[1]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue        # нечисло — не наблюдение, а его отсутствие
                byday[point[0]] = float(value)
        if byday:
            series[str(key)] = byday
    if not series:
        return {"measured": False,
                "reason": (f"в {path} ни у одного ключа нет читаемых точек ряда — "
                           f"НЕ ИЗМЕРЕНО")}
    days = sorted({d for byday in series.values() for d in byday})
    return {"measured": True, "series": series, "days": days,
            "path": str(path), "first_day": days[0], "last_day": days[-1],
            "keys": sorted(series)}


# ── словарь гейтов: что money-path СПРАШИВАЛ у настоящих решений ─────────────

def read_decision_gates(data_dir: Path) -> Dict[str, Any]:
    """Словарь гейтов по журналу решений — популяция ПОВЕДЕНЧЕСКАЯ.

    Гейт, отсутствующий во всех записанных решениях, money-path не применял ни
    разу. Оговорка названа вслух в отчёте: гейт, который существует и ни разу не
    связал, этим замером неотличим от отсутствующего — поэтому рядом печатается
    полный список ручек владельца (см. :func:`load_policy`).
    """
    path = Path(data_dir) / DECISIONS_NAME
    if not path.exists():
        return {"measured": False,
                "reason": f"журнал решений не найден: {path} — словарь гейтов НЕ ИЗМЕРЕН"}
    gates: set = set()
    rows = 0
    unreadable = 0
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    unreadable += 1
                    continue
                if not isinstance(row, dict):
                    unreadable += 1
                    continue
                rows += 1
                block = row.get("gates")
                if isinstance(block, dict):
                    gates |= {str(k) for k in block}
    except OSError as exc:
        return {"measured": False,
                "reason": f"журнал решений нечитаем ({path}): {type(exc).__name__}: {exc}"}
    if not rows:
        return {"measured": False,
                "reason": (f"в журнале решений {path} нет ни одной читаемой записи "
                           f"(нечитаемых строк {unreadable}) — словарь гейтов НЕ ИЗМЕРЕН")}
    return {"measured": True, "gates": sorted(gates), "decisions": rows,
            "unreadable": unreadable, "path": str(path)}


# ── ноги хода ────────────────────────────────────────────────────────────────

def move_legs(move: Dict[str, Any], aliases: Dict[str, str],
              min_usd: float) -> Dict[str, Dict[str, float]]:
    """Ноги хода с приведёнными ключами: куда пришло и откуда ушло.

    Псевдонимы применяются ДО вычитания: без них переименование протокола
    выглядит как полный выход и полный вход, то есть как ход, которого не было
    (класс, независимо названный ADR-350 и измеренный #701).
    """
    def canon(allocation: object) -> Dict[str, float]:
        merged: Dict[str, float] = {}
        for key, amount in _material(allocation, 0.0).items():
            name = aliases.get(key, key)
            merged[name] = merged.get(name, 0.0) + amount
        return merged

    before, after = canon(move.get("from")), canon(move.get("to"))
    inflow: Dict[str, float] = {}
    outflow: Dict[str, float] = {}
    for key in set(before) | set(after):
        delta = round(after.get(key, 0.0) - before.get(key, 0.0), 2)
        if delta > min_usd:
            inflow[key] = delta
        elif -delta > min_usd:
            outflow[key] = -delta
    return {"inflow": inflow, "outflow": outflow}


def _weighted_rate(legs: Dict[str, float], series: Dict[str, Dict[str, float]],
                   day: str) -> Optional[float]:
    """Взвешенная долларами ставка набора ног на день ``day``.

    Хотя бы одна нога без наблюдения ⇒ ``None``: ставка набора НЕ ИЗМЕРЕНА.
    Считать её по подмножеству наблюдённых ног значило бы выдать часть за целое.
    """
    total = sum(legs.values())
    if total <= 0:
        return None
    acc = 0.0
    for key, amount in legs.items():
        rate = series.get(key, {}).get(day)
        if rate is None:
            return None
        acc += amount * rate
    return acc / total


def same_day_round_trips(moves: List[Dict[str, Any]], aliases: Dict[str, str],
                         min_usd: float, tol_usd: float = 1.0) -> Dict[str, str]:
    """Ходы, у которых в ТОТ ЖЕ день есть дословно обратный партнёр.

    Такая пара — одно туда-обратно, а не два независимых решения. Не сказать об
    этом значило бы позволить читателю прочесть N находок как N решений: число
    независимых решений МЕНЬШЕ, и разница измеряется, а не оценивается на глаз.

    Возвращает ``{trade_id: partner_id}``. Пустой словарь — партнёров нет
    (замер), а не «не проверяли».
    """
    legs = {m["trade_id"]: move_legs(m, aliases, min_usd) for m in moves}
    day = {m["trade_id"]: (m["ts"].date().isoformat() if m.get("ts") else None)
           for m in moves}

    def same(left: Dict[str, float], right: Dict[str, float]) -> bool:
        return (set(left) == set(right) and bool(left)
                and all(abs(left[k] - right[k]) <= tol_usd for k in left))

    pairs: Dict[str, str] = {}
    ids = list(legs)
    for i, one in enumerate(ids):
        for other in ids[i + 1:]:
            if day[one] is None or day[one] != day[other]:
                continue
            if (same(legs[one]["inflow"], legs[other]["outflow"])
                    and same(legs[one]["outflow"], legs[other]["inflow"])):
                pairs[one] = other
                pairs[other] = one
    return pairs


def advantage_lifetime(move: Dict[str, Any], series: Dict[str, Dict[str, float]],
                       days: List[str], aliases: Dict[str, str],
                       min_usd: float) -> Dict[str, Any]:
    """Сколько форвардных дней подряд преимущество хода оставалось положительным.

    Возвращает либо породу со сроком, либо ``unmeasured`` с НАЗВАННОЙ причиной.
    Оба исхода — ответы; «не измерено» никогда не выдаётся за «преимущество жило».
    """
    legs = move_legs(move, aliases, min_usd)
    inflow, outflow = legs["inflow"], legs["outflow"]
    amount = round(sum(inflow.values()), 2)
    base = {"trade_id": move.get("trade_id"),
            "ts": move["ts"].isoformat() if move.get("ts") else None,
            "day": move["ts"].date().isoformat() if move.get("ts") else None,
            "inflow": inflow, "outflow": outflow, "amount_usd": amount}

    if not inflow or not outflow:
        # Флаг, а не узнавание своей же строки по подстроке: текст причины —
        # это сообщение читателю, и привязывать к нему ЛОГИКУ значило бы
        # завести связь, которую молча рвёт любая правка формулировки.
        return {**base, "species": SPECIES_UNMEASURED, "not_a_transfer": True,
                "reason": ("ход не переносит деньги между протоколами (нет ног в обе "
                           "стороны) — у него нет преимущества, которое могло бы жить")}
    day0 = base["day"]
    if day0 is None:
        return {**base, "species": SPECIES_UNMEASURED,
                "reason": "у хода нет читаемой отметки времени — форвардные дни НЕ ИЗМЕРЕНЫ"}
    if day0 < days[0]:
        return {**base, "species": SPECIES_UNMEASURED,
                "reason": (f"ход раньше начала наблюдённого ряда ({days[0]}) — "
                           f"материала о ставках тех дней не существует")}
    missing = sorted({k for k in list(inflow) + list(outflow) if k not in series})
    if missing:
        return {**base, "species": SPECIES_UNMEASURED,
                "reason": (f"ряда ставок нет вовсе у ключ(ей) {missing} — устойчивость "
                           f"преимущества по этому ходу нельзя проверить даже в принципе")}

    forward = [d for d in days if d > day0]
    sequence: List[List[Any]] = []
    lived = 0
    stopped = None
    for day in forward:
        rate_in = _weighted_rate(inflow, series, day)
        rate_out = _weighted_rate(outflow, series, day)
        if rate_in is None or rate_out is None:
            stopped = f"день {day}: наблюдения есть не у всех ног хода"
            break
        advantage = round(rate_in - rate_out, 4)
        sequence.append([day, advantage])
        if advantage > 0:
            lived += 1
        else:
            stopped = f"день {day}: преимущество стало {advantage:+.4f} пп"
            break
    if not sequence:
        return {**base, "species": SPECIES_UNMEASURED,
                "reason": (f"форвардных дней с полным материалом нет "
                           f"({stopped or 'ряд кончается днём хода'}) — срок жизни "
                           f"преимущества НЕ ИЗМЕРЕН")}
    at_move = None
    rate_in0 = _weighted_rate(inflow, series, day0)
    rate_out0 = _weighted_rate(outflow, series, day0)
    if rate_in0 is not None and rate_out0 is not None:
        at_move = round(rate_in0 - rate_out0, 4)
    return {**base, "species": None, "advantage_days": lived,
            "advantage_at_move_pp": at_move, "sequence": sequence,
            "stopped_because": stopped,
            "forward_days_available": len(forward),
            "exhausted_series": stopped is None}


def classify(item: Dict[str, Any], min_hold_days: float,
             max_payback_days: float) -> Dict[str, Any]:
    """Порода хода по сроку жизни преимущества против горизонтов владельца.

    Границы — ЕГО числа (`min_hold_days`, `max_payback_days`), не наши. Ход,
    чей ряд кончился раньше горизонта, НЕ объявляется пережившим его: это
    третий исход, а не успех (инвариант #17).
    """
    if item.get("species") == SPECIES_UNMEASURED:
        return item
    lived = item["advantage_days"]
    if lived < min_hold_days:
        species = SPECIES_BEFORE_HOLD
    elif lived < max_payback_days:
        species = SPECIES_WITHIN_PAYBACK
    else:
        species = SPECIES_OUTLIVED
    if species == SPECIES_OUTLIVED:
        return {**item, "species": species}
    if item.get("exhausted_series") and lived < max_payback_days:
        # Преимущество не умерло — кончился ряд. Судить о нём как об умершем
        # значило бы назвать «не измерено» находкой.
        return {**item, "species": SPECIES_UNMEASURED,
                "reason": (f"преимущество было положительным все {lived} наблюдённых "
                           f"форвардных дн., и ряд на этом кончился — умерло оно или "
                           f"нет, НЕ ИЗМЕРЕНО (горизонт владельца {max_payback_days:g} дн.)")}
    return {**item, "species": species}


# ── перепись ────────────────────────────────────────────────────────────────

def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None) -> Dict[str, Any]:
    """Перепись сроков жизни преимущества. Три исхода различимы.

    ``now`` инъектируется: прибор судит о ВОЗРАСТЕ ходов, и настенные часы
    сделали бы сцену смертной от календаря (`.claude/rules/deployment.md`).
    """
    now = now or datetime.now(timezone.utc)

    policy = load_policy(params)
    if not policy["measured"]:
        return _unmeasured(policy["reason"], now)

    journal = read_journal(data_dir)
    if not journal["measured"]:
        return _unmeasured(journal["reason"], now)

    series_doc = read_series(data_dir)
    if not series_doc["measured"]:
        return _unmeasured(series_doc["reason"], now)

    gates_doc = read_decision_gates(data_dir)

    moves = journal["moves"]
    book_scale = max(
        [sum(_material(m["from"], 0.0).values()) for m in moves]
        + [sum(_material(m["to"], 0.0).values()) for m in moves] or [0.0])
    min_usd = policy["min_leg_frac"] * book_scale

    alias_report = derive_aliases(moves, min_usd)
    aliases = alias_report["aliases"]

    series = series_doc["series"]
    days = series_doc["days"]
    round_trips = same_day_round_trips(moves, aliases, min_usd)
    items: List[Dict[str, Any]] = []
    for move in moves:
        item = advantage_lifetime(move, series, days, aliases, min_usd)
        item = classify(item, policy["min_hold_days"], policy["max_payback_days"])
        item["age_hours"] = round(
            (now - move["ts"]).total_seconds() / 3600.0, 2)
        item["same_day_inverse_of"] = round_trips.get(item["trade_id"])
        items.append(item)

    def of(species: str) -> List[Dict[str, Any]]:
        return [i for i in items if i.get("species") == species]

    before_hold, within, outlived = (of(SPECIES_BEFORE_HOLD),
                                     of(SPECIES_WITHIN_PAYBACK),
                                     of(SPECIES_OUTLIVED))
    unmeasured = of(SPECIES_UNMEASURED)
    # Ходы без ног в обе стороны — не «не измерено» про устойчивость, а просто
    # не предмет: они ничего не переносят. Держим их отдельно от слепоты.
    not_a_transfer = [i for i in unmeasured if i.get("not_a_transfer")]
    blind_unmeasured = [i for i in unmeasured if not i.get("not_a_transfer")]
    dead = before_hold + within

    horizon_hours = policy["max_payback_days"] * 24.0
    recent_dead = [i for i in dead if i["age_hours"] <= horizon_hours]
    recent_unmeasured = [i for i in blind_unmeasured
                         if i["age_hours"] <= horizon_hours]
    # Отдельная, БОЛЕЕ СИЛЬНАЯ порода того же замера: преимущества не было уже
    # в день хода. Это не «не продержалось», а «не существовало», и смешивать
    # два утверждения нельзя. Оговорка обязательна и стоит в отчёте: ряд — это
    # НАБЛЮДЕНИЕ, а решение могло ранжировать по другому производителю числа;
    # тогда находка говорит о РАСХОЖДЕНИИ двух производителей (класс ADR-126),
    # а какой из них прав, прибор не решает.
    negative_at_move = [i for i in dead
                        if i.get("advantage_at_move_pp") is not None
                        and i["advantage_at_move_pp"] <= 0]

    measurable = len(dead) + len(outlived)
    if measurable == 0:
        return _unmeasured(
            (f"ни один из {len(moves)} ходов журнала не измерим: "
             f"{len(blind_unmeasured)} без материала о ставках, "
             f"{len(not_a_transfer)} ничего не переносят — срок жизни преимущества "
             f"НЕ ИЗМЕРЕН ни разу, и это НЕ «преимущество жило»"), now,
            extra={"items": items, "unmeasured": blind_unmeasured})

    if recent_dead:
        status = STATUS_CRITICAL
    elif dead:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    # Слепота — про ПОСТРОЕНИЕ, и от тишины она не гаснет.
    gate_names = gates_doc.get("gates") if gates_doc.get("measured") else None
    blind = {
        "owner_dials": policy["dials"],
        "recorded_decision_gates": gate_names,
        "decisions_examined": gates_doc.get("decisions") if gates_doc.get("measured") else None,
        "gate_vocabulary_unmeasured": None if gates_doc.get("measured") else gates_doc.get("reason"),
        "move_record_cost_fields": _cost_fields_present(data_dir),
        "test2_not_reproducible": (
            "§-тест 2 приказа сравнивает СРОК ОКУПАЕМОСТИ с ожидаемым сроком жизни "
            "преимущества. Первое слагаемое в записи исполненного хода отсутствует "
            "(ни цены, ни ожидаемого выигрыша, ни payback), поэтому сравнение целиком "
            "не воспроизводимо ни по одному ходу — это третий исход, а не ноль"),
    }
    overlap = oscillation_overlap(items, data_dir)

    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": CRITERION,
        "journal": {"path": journal["path"], "rows": journal["rows"],
                    "moves": len(moves), "undated": journal["undated"],
                    "first_ts": moves[0]["ts"].isoformat(),
                    "last_ts": moves[-1]["ts"].isoformat()},
        "series": {"path": series_doc["path"], "keys": len(series_doc["keys"]),
                   "first_day": series_doc["first_day"],
                   "last_day": series_doc["last_day"]},
        "policy": {k: policy[k] for k in
                   ("min_hold_days", "max_payback_days", "min_leg_frac",
                    "mode", "version")},
        "materiality_usd": round(min_usd, 2),
        "book_scale_usd": round(book_scale, 2),
        "aliases": aliases,
        "alias_seams": alias_report["seams"],
        "items": items,
        "counts": {
            "moves": len(moves),
            "measurable": measurable,
            "died_before_min_hold": len(before_hold),
            "died_within_payback_horizon": len(within),
            "outlived_horizon": len(outlived),
            "unmeasured_no_material": len(blind_unmeasured),
            "not_a_transfer": len(not_a_transfer),
            "recent_dead_within_horizon": len(recent_dead),
            "recent_unmeasured_within_horizon": len(recent_unmeasured),
            "advantage_negative_at_move": len(negative_at_move),
            "dead_in_same_day_round_trips": len(
                [i for i in dead if i.get("same_day_inverse_of")]),
            "independent_dead_decisions": len(dead) - len(
                [i for i in dead if i.get("same_day_inverse_of")]) // 2,
        },
        "negative_at_move": negative_at_move,
        "oscillation_overlap": overlap,
        "blind_spot_demonstrated": True,
        "blind_spot": blind,
        "dead": dead,
        "recent_dead": recent_dead,
        "unmeasured": blind_unmeasured,
        "recent_unmeasured": recent_unmeasured,
        # Заголовочные числа дублируются наверх намеренно: мост и офис читают их
        # через `observed_number(doc, key)`, который смотрит верхний уровень.
        "moves_measurable": measurable,
        "advantage_died_total": len(dead),
        "outlived_horizon_total": len(outlived),
        "recent_dead_within_horizon": len(recent_dead),
        "unmeasured_no_material": len(blind_unmeasured),
        "usd_on_dead_advantage_recent": round(
            sum(i["amount_usd"] for i in recent_dead), 2),
        "usd_unmeasured_recent": round(
            sum(i["amount_usd"] for i in recent_unmeasured), 2),
    }


def oscillation_overlap(items: List[Dict[str, Any]],
                        data_dir: Path) -> Dict[str, Any]:
    """Пересечение населения с переписью прыжков книги (#701, ADR-480).

    Вопросы РАЗНЫЕ: там — вернулась ли книга туда, откуда ушла; здесь — жила ли
    причина, по которой она уходила. Один и тот же ход законно попадает в оба
    населения, и ни одно число не является поправкой к другому. Но молчать об
    этом нельзя: читатель, сложивший «12 возвратов» и «12 умерших преимуществ»,
    получил бы 24 события там, где их меньше.

    Пересечение ИЗМЕРЯЕТСЯ по артефакту соседа. Артефакта нет ⇒ третий исход,
    а не ноль: «не измерено» не выдаётся за «не пересекается».
    """
    path = Path(data_dir) / OSCILLATION_ARTIFACT
    dead_ids = {str(i.get("trade_id")) for i in items
                if i.get("species") in (SPECIES_BEFORE_HOLD, SPECIES_WITHIN_PAYBACK)}
    if not path.exists():
        return {"measured": False,
                "reason": (f"артефакта переписи прыжков нет ({path}) — пересечение "
                           f"населений НЕ ИЗМЕРЕНО, и это НЕ «они не пересекаются»")}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"артефакт переписи прыжков нечитаем ({path}): "
                           f"{type(exc).__name__}: {exc} — пересечение НЕ ИЗМЕРЕНО")}
    returns = doc.get("returns")
    if not isinstance(returns, list):
        return {"measured": False,
                "reason": (f"в {path} нет перечня возвратов (тип "
                           f"{type(returns).__name__}) — пересечение НЕ ИЗМЕРЕНО")}
    oscillating: set = set()
    for item in returns:
        if not isinstance(item, dict):
            continue
        for field in ("from_trade", "to_trade"):
            value = item.get(field)
            if isinstance(value, str):
                oscillating.add(value)
    shared = sorted(dead_ids & oscillating)
    return {"measured": True, "path": str(path),
            "oscillation_endpoints": len(oscillating),
            "dead_advantage_moves": len(dead_ids),
            "shared": shared, "shared_count": len(shared)}


def _cost_fields_present(data_dir: Path) -> Dict[str, Any]:
    """Несёт ли ЗАПИСЬ исполненного хода цену или ожидание — замер по составу.

    Читается сам журнал, а не наша память о его схеме: поле, появившееся
    позже, обязано быть замеченным в тот же день.
    """
    path = Path(data_dir) / "trades.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"состав записи хода НЕ ИЗМЕРЕН: {type(exc).__name__}: {exc}"}
    rows = doc if isinstance(doc, list) else (
        doc.get("trades") if isinstance(doc, dict) else None)
    if not isinstance(rows, list) or not rows:
        return {"measured": False,
                "reason": f"в {path} нет записей ходов — состав НЕ ИЗМЕРЕН"}
    keys: set = set()
    for row in rows:
        if isinstance(row, dict):
            keys |= {str(k) for k in row}
    found = sorted(k for k in COST_FIELDS if k in keys)
    return {"measured": True, "record_keys": sorted(keys),
            "looked_for": list(COST_FIELDS), "found": found,
            "rows": len(rows),
            "carries_cost": bool(found)}


def _unmeasured(reason: str, now: datetime,
                extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    doc = {"measured": False, "status": STATUS_UNMEASURED, "reason": reason,
           "generated_at": now.isoformat(), "items": [], "dead": [],
           "recent_dead": [], "unmeasured": [], "recent_unmeasured": [],
           "blind_spot_demonstrated": False,
           "counts": {"moves": 0, "measurable": 0,
                      "died_before_min_hold": 0,
                      "died_within_payback_horizon": 0,
                      "outlived_horizon": 0,
                      "unmeasured_no_material": 0, "not_a_transfer": 0,
                      "recent_dead_within_horizon": 0,
                      "recent_unmeasured_within_horizon": 0}}
    if extra:
        doc.update(extra)
    return doc


# ── отчёт ───────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"срок жизни преимущества (§49 Persistence): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    c = report["counts"]
    return (f"срок жизни преимущества (§49 Persistence): {report['status']} · ходов "
            f"{c['moves']}, измеримы {c['measurable']} · преимущество УМЕРЛО раньше "
            f"горизонта владельца у {c['died_before_min_hold'] + c['died_within_payback_horizon']} "
            f"(раньше минимального удержания {c['died_before_min_hold']}) · пережили "
            f"горизонт {c['outlived_horizon']} · НЕ ИЗМЕРЕНО {c['unmeasured_no_material']} "
            f"· свежих внутри горизонта {c['recent_dead_within_horizon']}")


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Строки для офиса — каждая находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        return lines
    pol = report["policy"]
    lines.append(
        f"[ГОРИЗОНТЫ ВЛАДЕЛЬЦА] минимальное удержание {pol['min_hold_days']:g} дн. · "
        f"окупаемость цены {pol['max_payback_days']:g} дн. · колонка "
        f"{pol['mode']}/{pol['version']} (ADR-060 §3) — своих чисел у прибора нет")
    if report["status"] == STATUS_WARNING:
        lines.append(
            f"[ВЕРДИКТ] внутри горизонта от now свежих ходов с умершим преимуществом "
            f"НЕТ, но в истории их {report['counts']['died_before_min_hold'] + report['counts']['died_within_payback_horizon']}"
            f" — «сегодня тихо» НЕ значит «такого не бывало»; последний ход журнала "
            f"{report['journal']['last_ts']}")
    for item in report.get("dead", [])[:limit]:
        tail = (f"преимущество на день хода {item['advantage_at_move_pp']:+.3f} пп"
                if item.get("advantage_at_move_pp") is not None
                else "преимущества на день хода НЕ ИЗМЕРЕНО")
        lines.append(
            f"[{'РАНЬШЕ УДЕРЖАНИЯ' if item['species'] == SPECIES_BEFORE_HOLD else 'РАНЬШЕ ОКУПАЕМОСТИ'}]"
            f" {item['trade_id']} {item['day']}: ${item['amount_usd']:,.0f} в "
            f"{', '.join(sorted(item['inflow']))} из {', '.join(sorted(item['outflow']))} — "
            f"преимущество жило {item['advantage_days']} дн., {tail}; {item['stopped_because']}")
    for item in report.get("unmeasured", [])[:limit]:
        lines.append(
            f"[НЕ ИЗМЕРЕНО] {item['trade_id']} {item['day']}: "
            f"${item['amount_usd']:,.0f} — {item['reason']}")
    extra = (len(report.get("dead", [])) + len(report.get("unmeasured", []))
             - 2 * limit)
    if extra > 0:
        lines.append(f"… ещё {extra} ход(ов) — полный перечень в артефакте")
    blind = report.get("blind_spot", {})
    gates = blind.get("recorded_decision_gates")
    if gates is None:
        lines.append(f"[СЛОВАРЬ ГЕЙТОВ НЕ ИЗМЕРЕН] {blind.get('gate_vocabulary_unmeasured')}")
    else:
        lines.append(
            f"[СЛЕПОТА ПО ПОСТРОЕНИЮ] за {blind.get('decisions_examined')} записанных "
            f"решений money-path применял РОВНО эти гейты: {', '.join(gates)} — ни один "
            f"не про устойчивость ставки; ручек владельца {len(blind.get('owner_dials') or [])}: "
            f"{', '.join(blind.get('owner_dials') or [])} — `minimum persistence` из §41 "
            f"среди них нет. Оговорка: гейт, существующий и ни разу не связавший, этим "
            f"замером неотличим от отсутствующего — поэтому список ручек напечатан целиком")
    cost = blind.get("move_record_cost_fields") or {}
    if cost.get("measured"):
        lines.append(
            f"[ЦЕНЫ ХОДА В ЗАПИСИ НЕТ] искали {', '.join(cost['looked_for'])}, нашли "
            f"{cost['found'] or '— ни одного'} в {cost['rows']} записях — цена рядом "
            f"(`{DECISIONS_NAME}`) принадлежит СОВЕТАТЕЛЬНОЙ пробе того же дня, и "
            f"подставлять её ценой исполненного хода нельзя")
    else:
        lines.append(f"[СОСТАВ ЗАПИСИ ХОДА НЕ ИЗМЕРЕН] {cost.get('reason')}")
    lines.append(f"[ТРЕТИЙ ИСХОД] {blind.get('test2_not_reproducible')}")
    if report.get("negative_at_move"):
        ids = ", ".join(str(i["trade_id"]) for i in report["negative_at_move"])
        usd = sum(i["amount_usd"] for i in report["negative_at_move"])
        lines.append(
            f"[ПРЕИМУЩЕСТВА НЕ БЫЛО УЖЕ В ДЕНЬ ХОДА] {len(report['negative_at_move'])} "
            f"ход(ов) на ${usd:,.0f}: {ids} — по НАБЛЮДЁННОМУ ряду ставка входов была "
            f"не выше ставки выходов уже в тот день. Порода СИЛЬНЕЕ «не продержалось» и "
            f"с ней не смешивается. Оговорка: ряд — это наблюдение, а решение могло "
            f"ранжировать по другому производителю числа; тогда это РАСХОЖДЕНИЕ двух "
            f"производителей (класс ADR-126), и какой прав — прибор не решает")
    paired = [i for i in report.get("dead", []) if i.get("same_day_inverse_of")]
    if paired:
        lines.append(
            f"[СЧИТАТЬ РЕШЕНИЯ, А НЕ ЗАПИСИ] из {len(report['dead'])} находок "
            f"{len(paired)} суть {len(paired) // 2} обратные пары ТОГО ЖЕ дня "
            f"({', '.join(sorted({'↔'.join(sorted((str(i['trade_id']), str(i['same_day_inverse_of'])))) for i in paired}))}) "
            f"— туда-обратно есть ОДНО решение, поэтому независимых решений "
            f"{report['counts']['independent_dead_decisions']}, а не {len(report['dead'])}; "
            f"вывод «преимущество не пережило горизонт» от этого не меняется, меняется "
            f"только знаменатель, которым его честно называть")
    overlap = report.get("oscillation_overlap") or {}
    if overlap.get("measured"):
        lines.append(
            f"[НАСЕЛЕНИЯ] с переписью прыжков книги (#701) общих ходов "
            f"{overlap['shared_count']} из {overlap['dead_advantage_moves']}"
            f"{': ' + ', '.join(overlap['shared']) if overlap['shared'] else ''} — "
            f"вопросы РАЗНЫЕ (там «вернулась ли книга», здесь «жила ли причина»), "
            f"складывать находки двух приборов нельзя, и ни одно число не является "
            f"поправкой к другому")
    else:
        lines.append(f"[НАСЕЛЕНИЯ НЕ СВЕРЕНЫ] {overlap.get('reason')}")
    if report.get("recent_unmeasured"):
        lines.append(
            f"[СВЕЖИЕ БЕЗ МАТЕРИАЛА] внутри горизонта лежит "
            f"{len(report['recent_unmeasured'])} ход(ов) на "
            f"${report['usd_unmeasured_recent']:,.0f}, устойчивость которых нельзя "
            f"проверить даже в принципе — «не измерено» не выдаётся за «чисто»")
    if report.get("aliases"):
        pairs = ", ".join(f"{a}→{b}" for a, b in sorted(report["aliases"].items()))
        lines.append(f"[ПСЕВДОНИМЫ] измерены на стыках записей: {pairs} — без них "
                     f"переименование ключа выглядит как ход, которого не было")
    lines.append("ОПОРА: срок считается по ПОДРЯД идущим форвардным дням, и ряд, "
                 "кончившийся раньше горизонта, даёт ТРЕТИЙ исход, а не «пережил»; "
                 "пропуск дня в ряду никогда не интерполируется")
    if report.get("dead"):
        longest = max(i["advantage_days"] for i in report["dead"])
        truncated = [i for i in report["dead"] if i.get("exhausted_series")]
        lines.append(
            f"[НЕ АРТЕФАКТ ОКНА] у всех {len(report['dead'])} находок преимущество умерло "
            f"при ЕЩЁ ИДУЩЕМ ряде (обрезанных окном: {len(truncated)}), и дольше всех оно "
            f"жило {longest} дн. при горизонте {pol['max_payback_days']:g} — вывод «не "
            f"пережило» не зависит от ширины наблюдённого окна, он измерен смертью")
    lines.append("НЕ ДОКЛАДЫВАЕТ: верность каждого хода (ход бывает оправдан риском, "
                 "концентрацией или ликвидностью, а не ставкой) · цену хода (её в "
                 "записи нет) · реализованную доходность книги (это трек) · был ли у "
                 "ЦЕЛИ спайк сам по себе — операнд здесь «цель против покинутого "
                 "источника», то есть вопрос о ВРЕДЕ («стоило ли перекладывать»), а не "
                 "о форме кривой цели · пороги RiskPolicy v1.0, стоп-кран, аллокатор и "
                 "живой трек НЕ трогаются")
    return lines


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь). Обратный порядок `atomic_save`
    # отвергает fail-CLOSED, и тогда артефакта не появляется ВОВСЕ, а ступень
    # докладывает `measured=True`: отказ записи неотличим от успеха у всех, кто
    # смотрит на вывод, а не на диск (настоящая поломка, найденная #701).
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ступень моста находок (`findings_bridge`): померить и оставить артефакт.

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис увидит
    отсутствие файла и не отличит его от «ступень не запускалась».
    """
    data_dir = Path(root) / "data"
    report = run_census(data_dir, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (по умолчанию — data/ репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    ap.add_argument("--save", action="store_true",
                    help=f"записать {ARTIFACT_NAME} в каталог данных")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else (
        Path(__file__).resolve().parents[2] / "data")
    report = run_census(data_dir)
    if args.save and report.get("measured"):
        save_artifact(report, data_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)

    if not report.get("measured"):
        return EXIT_UNMEASURED
    # Ненулевой код — только на СВЕЖИЙ ход с умершим преимуществом, то есть на
    # то, что решается сегодня. `WARNING` и структурная слепота печатаются
    # всегда, но кодом не нудят: вечно красный прибор учит пропускать свой вывод.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
