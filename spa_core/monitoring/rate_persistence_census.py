#!/usr/bin/env python3
"""Пережила ли ставка, на которой решали, минимальный срок удержания.

Критерий §49 `Persistence` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #704.

Дословно критерий звучит так: **«Transient APY spikes не вызывают ненужные
trades»**. До этого прибора он был ПРОЗОЙ — и, в отличие от соседей по §49, у
него не называлось даже механизма: ни одной ручки про устойчивость ставки в
колонке владельца нет вовсе (ADR-060 §3 / `TriggerParams`), а ранжирование
берёт ОДНО мгновенное наблюдение (`allocator._load_evidenced_apy` → снимок
`adapters[*].live_apy`), без сглаживания по времени. «Модуль есть, тесты
зелёные» тут не спасает даже формально: модуля нет.

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь: **выживание ставки**. Ставка, на которой принято решение, обязана
дожить до конца срока, который сама же система обещает позиции держать
(`min_hold_days` — «a fresh position is not churned out»). Если ставка за этот
срок осела ниже той существенности, которой система мерит выгоду
(`min_gain_pp`), то деньги стоят в позиции, чьё основание исчезло раньше, чем
позицию разрешено покинуть.

Меряется по ДВУМ осям, и смешивать их нельзя:

* ось **`entry`** — исполненные деньги: нога ВХОДА из журнала ходов
  (`trades.json`). Это про доллары, которые реально поехали;
* ось **`pull`** — поверхность решения: запись
  (`allocation_rationale_history.jsonl`), чья ЦЕЛЬ существенно тянет ключ
  вверх. Это про доллары, которые поехали бы, не откажи другой гейт.

Вторая ось существует ровно потому, что «сегодня ничего не поехало» — не
ответ на вопрос владельца: если цель тянет на спайке, а держит её потолок
оборота, то критерий выполняется СЛУЧАЙНО, и в день, когда потолок не свяжет,
деньги уедут. Поэтому причины отказа на таких днях прибор ВЫПИСЫВАЕТ — пусть
читатель видит, ЧТО именно держало книгу.

Почему сравнение идёт внутри ОДНОГО производителя
------------------------------------------------------------------------------
Ставку наблюдают несколько производителей, и они расходятся: `aave_v3`
2026-09-22 — 12.958 % в `apy_series_daily.json` против 5.392 % в записи
решения того же дня. Этот класс измерен ОТДЕЛЬНО (ADR-312, внутрисуточное
движение входов) и предметом ЭТОГО прибора не является. Поэтому и деление, и
форвардные наблюдения берутся из ОДНОГО носителя — записей решения: там
ставка лежит вместе с моментом наблюдения (`apy_as_of`), то есть у каждой
точки есть своё время, а не только дата. Сравнивать решение одного
производителя с историей другого значило бы мерить их расхождение и называть
это неустойчивостью ставки.

Внутрисуточные наблюдения НЕ сливаются в дневную точку намеренно: слияние
означало бы выбор (среднее? первое? последнее?), которого никто не делал, и
изобретённая точка стала бы третьим местом для ставки.

Своих чисел прибор не имеет ни одного
------------------------------------------------------------------------------
Существенность изменения ставки (`min_gain_pp`), срок выживания
(`min_hold_days`), существенность ноги (`min_leg_frac`) и окно свежести
(`reversal_window_days`) берутся из `TriggerParams.for_mode()` — той колонки,
которой судит живой путь. §22 приказа требует дословно: «Все значения должны
быть config/policy. **Не hardcode**». **Колонка недоступна ⇒ третий исход**, а
не подставленное умолчание.

Почему вердикт судит НАСТОЯЩЕЕ, а история остаётся замером
------------------------------------------------------------------------------
Вход, состоявшийся в августе, состоялся навсегда: сторож, чей вердикт считает
всю историю, красен НАВСЕГДА и учит себя игнорировать
(`.claude/rules/deployment.md`). Поэтому:

* ``CRITICAL`` — исполненный вход на осевшей ставке лежит внутри окна свежести
  владельца от `now`;
* ``WARNING`` — свежих исполненных нет, но они есть в истории ЛИБО цель тянет
  на осевшей ставке (вред жив, деньги держит другой гейт);
* ``OK`` — ни на одной оси такого не было ни разу.

Отсутствие ручки про устойчивость — утверждение о ПОСТРОЕНИИ, и оно живёт
отдельным полем ``no_survival_condition_named``: от того, что неделю тихо, оно
не гаснет.

Чего прибор НЕ утверждает
------------------------------------------------------------------------------
* **Что вход был НЕВЕРЕН.** Ставка умеет падать по-настоящему, и вход на
  честном наблюдении с последующим падением — неудача, а не дефект. Прибор
  говорит только, что основание решения не дожило до конца срока удержания, и
  называет цену.
* **Что производитель ставки врёт.** Расхождение производителей — предмет
  ADR-312, здесь оно только НАЗЫВАЕТСЯ как причина, по которой сравнение
  держится внутри одного носителя.
* **Что ручку устойчивости надо добавить.** Это денежный путь и предмет №1
  границы (`CLAUDE.md`): решает владелец, прибор только меряет.
* **Что «не измерено» = «всё хорошо».** Доллары без форвардного наблюдения
  считаются ОТДЕЛЬНО и печатаются всегда.

Прибор ТОЛЬКО ЧИТАЕТ: журнал решений, журнал ходов, пороги и часы. Ни
`TriggerParams`, ни пороги RiskPolicy v1.0, ни стоп-кран, ни аллокатор, ни
живой трек он не трогает и ничего не чинит. **LLM запрещён** (инвариант #3 —
monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.observation import observed, observed_number

#: Журнал решений: ставка + момент её наблюдения + цель + причины отказа.
DECISIONS_NAME = "allocation_rationale_history.jsonl"

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "rate_persistence_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код возврата третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3

CLASS_FADED = "faded"
CLASS_HELD = "held"
#: Четвёртый исход, и он ИЗМЕРЕН, а не придуман: наблюдения ставки внутри срока
#: удержания расходятся больше существенности и лежат по обе стороны порога.
#: Тогда «осела» и «держалась» неверны ОДИНАКОВО — см. ``survival``.
CLASS_OSCILLATING = "oscillating"
CLASS_UNMEASURED = "unmeasured"

#: Словарь-СКРИН для поиска ручки про выживание ставки среди ИЗМЕРЕННЫХ имён
#: (полей колонки владельца и ключей гейтов из журнала). Это не порог и не
#: политика — это перечень слов, по которым прибор ИЩЕТ кандидата и печатает
#: его читателю. Скрин намеренно ГРУБЫЙ: ошибаться он обязан в сторону
#: находки, иначе «ручки нет» стало бы утверждением о нашем невнимании.
SURVIVAL_VOCABULARY: Tuple[str, ...] = (
    "persist", "stability", "stable", "spike", "transient", "smooth",
    "survive", "survival", "dwell", "sustain", "устойч",
)


# ── часы и разбор отметок ───────────────────────────────────────────────────

def _parse_ts(raw: object) -> Optional[datetime]:
    """Отметка времени. Нечитаемая отметка — ``None``, никогда не «сейчас»."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _num(value: object) -> Optional[float]:
    """Число или ``None``. ``bool`` числом не является, мусор — не ноль."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None


# ── пороги: колонка владельца, а не наши числа ──────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Существенность, срок выживания и окно свежести из ``TriggerParams``.

    Колонка недоступна ⇒ ``measured=False`` с названной причиной. Подставить
    умолчание значило бы завести ещё одну копию чисел ADR-060 §3 и ответить на
    свой вопрос вместо нужного (урок `pyflakes`: отсутствие инструмента —
    третий исход, а не ноль).
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — существенность "
                               f"ставки и срок её выживания НЕ ИЗМЕРЕНЫ, подставлять "
                               f"свои нельзя (§22: «Все значения должны быть "
                               f"config/policy. Не hardcode»)")}
    try:
        min_gain_pp = float(params.min_gain_pp)
        min_hold_days = float(params.min_hold_days)
        min_leg_frac = float(params.min_leg_frac)
        fresh_days = float(params.reversal_window_days)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    if min_hold_days <= 0:
        return {"measured": False,
                "reason": (f"срок удержания в колонке не положителен "
                           f"({min_hold_days}) — окна выживания нет, мерить нечем")}
    # Имена полей колонки нужны СКРИНУ ручки выживания. Их не удалось снять ⇒
    # пустой перечень, и скрин обязан сказать «НЕ ИЗМЕРЕНО»: пустое множество
    # имён дало бы «ручки нет» БЕЗ замера — то есть выдуманное утверждение.
    try:
        names = sorted(str(n) for n in vars(params))
        if not names:
            names = sorted(str(n) for n in
                           type(params).__dataclass_fields__)  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        names = []
    return {"measured": True, "min_gain_pp": min_gain_pp,
            "min_hold_days": min_hold_days, "min_leg_frac": min_leg_frac,
            "fresh_days": fresh_days, "mode": mode, "version": version,
            "column_field_names": names}


# ── журнал решений ──────────────────────────────────────────────────────────

def read_decisions(data_dir: Path) -> Dict[str, Any]:
    """Записи решений с диска. Отсутствие/нечитаемость — третий исход."""
    path = Path(data_dir) / DECISIONS_NAME
    if not path.exists():
        return {"measured": False,
                "reason": (f"журнал решений не найден: {path} — мерить нечего, "
                           f"и это НЕ «ставки держались»")}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"measured": False,
                "reason": f"журнал решений нечитаем ({path}): {type(exc).__name__}: {exc}"}

    records: List[Dict[str, Any]] = []
    unparsed = 0
    undated = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            unparsed += 1
            continue
        if not isinstance(row, dict):
            unparsed += 1
            continue
        stamp = _parse_ts(row.get("generated_at"))
        if stamp is None:
            undated += 1
            continue
        records.append({"ts": stamp, "row": row})
    if not records:
        return {"measured": False,
                "reason": (f"в журнале решений {path} нет ни одной записи с читаемой "
                           f"отметкой времени (неразобранных {unparsed}, без отметки "
                           f"{undated}) — порядок наблюдений НЕ ИЗМЕРЕН")}
    records.sort(key=lambda r: r["ts"])
    return {"measured": True, "records": records, "path": str(path),
            "unparsed": unparsed, "undated": undated}


# ── панель наблюдений: ставка как функция МОМЕНТА, а не даты ────────────────

def build_panel(records: List[Dict[str, Any]],
                aliases: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Наблюдения ставок ``{ключ: [(момент, значение), …]}`` из записей решений.

    Момент берётся из ``apy_as_of[ключ]`` — то есть у каждой точки своё время,
    а не только дата: запись дня не одна, и внутри суток ставка двигается
    (ADR-312). Момента нет ⇒ берётся отметка записи, и такие точки СЧИТАЮТСЯ
    отдельно: «время наблюдения неизвестно» не равно «наблюдения нет», но и
    равным своему моменту не является.
    """
    alias = dict(aliases or {})
    panel: Dict[str, List[Tuple[datetime, float]]] = {}
    fallback_moment = 0
    dropped = 0
    for rec in records:
        row = rec["row"]
        rates = observed(row, "apy_evidenced_pct", kind=dict)
        if rates is None:
            continue
        as_of = observed(row, "apy_as_of", kind=dict) or {}
        for raw_key, raw_value in rates.items():
            value = _num(raw_value)
            if value is None:
                dropped += 1
                continue
            key = alias.get(str(raw_key), str(raw_key))
            moment = _parse_ts(as_of.get(raw_key))
            if moment is None:
                moment = rec["ts"]
                fallback_moment += 1
            panel.setdefault(key, []).append((moment, value))
    for key in panel:
        panel[key].sort(key=lambda p: p[0])
    return {"panel": panel, "fallback_moment": fallback_moment,
            "dropped_values": dropped}


def survival(panel: Dict[str, List[Tuple[datetime, float]]], key: str,
             moment: datetime, value: float, *, horizon_days: float,
             materiality_pp: float) -> Dict[str, Any]:
    """Дожила ли ставка ``value`` ключа ``key`` до конца срока удержания.

    Форвардные наблюдения — те же записи решений, СТРОГО позже момента решения
    и не позже ``horizon_days``. Их нет ⇒ ``unmeasured`` с причиной: ноль
    форвардных точек это отсутствие замера, а не устойчивая ставка.
    """
    points = panel.get(key)
    if not points:
        return {"class": CLASS_UNMEASURED, "forward_n": 0,
                "cause": "key_absent",
                "reason": (f"ключа `{key}` нет в записях решения ни одним наблюдением "
                           f"— ставка, на которой решали, не записана (возможен "
                           f"псевдоним ключа: класс ADR-350)")}
    horizon = moment + timedelta(days=horizon_days)
    forward = [v for (t, v) in points if moment < t <= horizon]
    if not forward:
        return {"class": CLASS_UNMEASURED, "forward_n": 0,
                "cause": "no_forward_observation",
                "reason": (f"форвардных наблюдений `{key}` внутри срока удержания "
                           f"({horizon_days:g} дн от {moment.isoformat()}) нет — "
                           f"выживание ставки НЕ ИЗМЕРЕНО")}
    median = statistics.median(forward)
    floor = value - materiality_pp
    # Три исхода, и средний существует ПОТОМУ ЧТО он измерен, а не для красоты.
    # Носитель наблюдает ставку НЕ РАЗ В СУТКИ, и свои же наблюдения одного
    # ключа внутри срока удержания расходятся (замер: `aave_v3` 09-19 — 5.27 в
    # 06:00 и 3.62 в 16:28, размах 1.65 pp против существенности 0.5 pp; класс
    # ADR-312). Если ставка внутри окна и падала ниже порога, и возвращалась к
    # нему, то «осела» и «держалась» ОДИНАКОВО неверны: это КОЛЕБАНИЕ, и
    # выживание такой ставки по журналу не определено. Назвать колебание
    # падением значило бы выдать расхождение производителя за находку.
    if median <= floor and max(forward) >= floor:
        verdict = CLASS_OSCILLATING
    elif median <= floor:
        verdict = CLASS_FADED
    else:
        verdict = CLASS_HELD
    out = {"class": verdict,
           "forward_n": len(forward),
           "forward_median_pp": round(median, 4),
           "forward_min_pp": round(min(forward), 4),
           "forward_max_pp": round(max(forward), 4),
           "forward_span_pp": round(max(forward) - min(forward), 4),
           "decline_pp": round(value - median, 4),
           "horizon_days": horizon_days}
    if verdict == CLASS_OSCILLATING:
        out["cause"] = "forward_observations_disagree"
        out["reason"] = (
            f"наблюдения `{key}` внутри срока удержания расходятся на "
            f"{max(forward) - min(forward):.4g} pp при существенности "
            f"{materiality_pp:g} pp и по обе стороны порога — ставка КОЛЕБЛЕТСЯ, "
            f"её выживание по журналу НЕ ОПРЕДЕЛЕНО (класс ADR-312)")
    return out


# ── ось «цель тянет»: поверхность решения ──────────────────────────────────

def find_pulls(records: List[Dict[str, Any]], panel: Dict[str, Any],
               policy: Dict[str, Any],
               aliases: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Решения, чья ЦЕЛЬ существенно тянет ключ вверх — и выжила ли ставка.

    Существенность ноги — доля капитала ИЗ САМОЙ ЗАПИСИ (`capital_usd`), а не
    наша константа. Капитала в записи нет ⇒ пулы этой записи не мерятся, и
    причина называется: доля без знаменателя есть догадка.
    """
    alias = dict(aliases or {})
    out: List[Dict[str, Any]] = []
    for rec in records:
        row = rec["row"]
        rates = observed(row, "apy_evidenced_pct", kind=dict)
        current = observed(row, "current_positions", kind=dict)
        target = observed(row, "target_positions", kind=dict)
        capital = observed_number(row, "capital_usd")
        if rates is None or target is None:
            continue
        if capital is None or capital <= 0:
            out.append({"axis": "pull", "class": CLASS_UNMEASURED,
                        "cause": "capital_absent",
                        "cycle_date": row.get("cycle_date"),
                        "decision_id": row.get("decision_id"),
                        "reason": ("в записи нет капитала (`capital_usd`) — "
                                   "существенность ноги НЕ ИЗМЕРЕНА, доля без "
                                   "знаменателя есть догадка"),
                        "usd": 0.0, "protocol": None})
            continue
        min_usd = policy["min_leg_frac"] * capital
        as_of = observed(row, "apy_as_of", kind=dict) or {}
        for raw_key, raw_target in (target or {}).items():
            tgt = _num(raw_target)
            if tgt is None:
                continue
            cur = _num((current or {}).get(raw_key)) or 0.0
            delta = tgt - cur
            if delta < min_usd:
                continue
            key = alias.get(str(raw_key), str(raw_key))
            value = _num((rates or {}).get(raw_key))
            moment = _parse_ts(as_of.get(raw_key)) or rec["ts"]
            item = {"axis": "pull", "protocol": key,
                    "cycle_date": row.get("cycle_date"),
                    "decision_id": row.get("decision_id"),
                    "ts": rec["ts"].isoformat(), "usd": round(delta, 2),
                    "verdict": row.get("verdict"),
                    "reasons": list(observed(row, "reasons", kind=list) or []),
                    # Гейты бывают НЕ ЗАПИСАНЫ вовсе (замер: 45 записей из 69 несут
                    # поле `gates`). «Поля нет» и «ни один гейт не отказал» — разные
                    # исходы, и слить их значило бы напечатать «книгу не держало
                    # ничто» там, где держало неизвестно что (инв. #17).
                    "gates_measured": observed(row, "gates", kind=dict) is not None,
                    "gates_refused": sorted(
                        k for k, v in (observed(row, "gates", kind=dict) or {}).items()
                        if v is False)}
            if value is None:
                item.update({"class": CLASS_UNMEASURED,
                             "cause": "decided_rate_absent",
                             "reason": (f"цель тянет `{key}` на ${delta:,.0f}, а ставки "
                                        f"этого ключа в записи НЕТ — решение принято "
                                        f"на ненаблюдённом числе (класс ADR-366)")})
            else:
                item["decided_pp"] = round(value, 4)
                item.update(survival(panel["panel"], key, moment, value,
                                     horizon_days=policy["min_hold_days"],
                                     materiality_pp=policy["min_gain_pp"]))
            out.append(item)
    return out


# ── ось «деньги поехали»: журнал ходов ─────────────────────────────────────

def find_entries(moves: List[Dict[str, Any]], panel: Dict[str, Any],
                 policy: Dict[str, Any], book_scale: float,
                 aliases: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Ноги ВХОДА исполненных ходов — и выжила ли ставка, на которой решали.

    Ставка решения — ПОСЛЕДНЕЕ наблюдение ключа не позже хода. Если оно старше
    срока удержания, решали не на нём: тогда ``unmeasured`` с причиной, а не
    молчаливая подстановка ближайшего числа.
    """
    alias = dict(aliases or {})
    min_usd = policy["min_leg_frac"] * book_scale
    out: List[Dict[str, Any]] = []
    for move in moves:
        before = move.get("from") if isinstance(move.get("from"), dict) else {}
        after = move.get("to") if isinstance(move.get("to"), dict) else {}
        for raw_key in sorted(set(after) | set(before)):
            delta = (_num(after.get(raw_key)) or 0.0) - (_num(before.get(raw_key)) or 0.0)
            if delta < min_usd:
                continue
            key = alias.get(str(raw_key), str(raw_key))
            item = {"axis": "entry", "trade_id": move.get("trade_id"),
                    "ts": move["ts"].isoformat(), "protocol": key,
                    "usd": round(delta, 2)}
            points = panel["panel"].get(key) or []
            past = [(t, v) for (t, v) in points if t <= move["ts"]]
            if not past:
                item.update({"class": CLASS_UNMEASURED,
                             "cause": "no_observation_before_move",
                             "reason": (f"наблюдений `{key}` до хода нет ни одного — "
                                        f"ставка, на которой решали, не записана")})
                out.append(item)
                continue
            moment, value = past[-1]
            age_days = (move["ts"] - moment).total_seconds() / 86400.0
            if age_days > policy["min_hold_days"]:
                item.update({"class": CLASS_UNMEASURED,
                             "cause": "observation_older_than_hold",
                             "decided_pp": round(value, 4),
                             "observation_age_days": round(age_days, 2),
                             "reason": (f"ближайшее наблюдение `{key}` старше срока "
                                        f"удержания ({age_days:.1f} дн > "
                                        f"{policy['min_hold_days']:g}) — решали не на "
                                        f"нём, выживание НЕ ИЗМЕРЕНО")})
                out.append(item)
                continue
            item["decided_pp"] = round(value, 4)
            item["observation_age_days"] = round(age_days, 2)
            item.update(survival(panel["panel"], key, moment, value,
                                 horizon_days=policy["min_hold_days"],
                                 materiality_pp=policy["min_gain_pp"]))
            out.append(item)
    return out


# ── скрин имён: есть ли в системе ручка про выживание ставки ───────────────

def screen_survival_names(column_names: List[str],
                          gate_names: List[str]) -> Dict[str, Any]:
    """Ищет среди ИЗМЕРЕННЫХ имён кандидата на ручку «ставка дожила».

    Имена не выдуманы: слева поля колонки владельца, справа ключи гейтов,
    встреченные в журнале. Скрин грубый и ошибается в сторону НАХОДКИ —
    кандидат печатается читателю, а не засчитывается как «ручка есть».
    """
    scanned = sorted({str(n) for n in column_names} | {str(n) for n in gate_names})
    if not scanned:
        # Ни одного имени снять не удалось: «ручки нет» здесь было бы выдумано,
        # а не измерено (тот же класс, что «инструмента нет ⇒ ноль», урок
        # `pyflakes`). Третий исход — `None`, и он печатается как таковой.
        return {"names_scanned": [], "candidates": [],
                "vocabulary": list(SURVIVAL_VOCABULARY),
                "no_survival_condition_named": None,
                "reason": ("имён ни колонки, ни гейтов снять не удалось — наличие "
                           "ручки выживания НЕ ИЗМЕРЕНО, и «её нет» утверждать нельзя")}
    hits = sorted(n for n in scanned
                  if any(word in n.lower() for word in SURVIVAL_VOCABULARY))
    return {"names_scanned": scanned, "candidates": hits,
            "vocabulary": list(SURVIVAL_VOCABULARY),
            "no_survival_condition_named": not hits}


# ── суммы долларов: нога без числа НЕ равна нулю (инв. #17) ─────────────────

def _sum_usd(items: List[Dict[str, Any]]) -> Tuple[float, int]:
    """Сумма долларов ног и ЧИСЛО ног без числа.

    ``item["usd"] or 0.0`` было бы ровно тем дефектом, против которого написан
    инвариант #17: нога, у которой суммы нет, прибавила бы к итогу ноль и стала
    бы неотличима от ноги на $0. Здесь она НЕ прибавляет ничего и СЧИТАЕТСЯ
    отдельно, чтобы итог нельзя было прочесть как полный, когда он неполон.
    """
    total = 0.0
    missing = 0
    for item in items:
        value = observed_number(item, "usd")
        if value is None:
            missing += 1
            continue
        total += value
    return round(total, 2), missing


def _max_usd(items: List[Dict[str, Any]]) -> Optional[float]:
    """Наибольшая одиночная сумма — или ``None``, если чисел нет ни у одной ноги."""
    values = [observed_number(i, "usd") for i in items]
    numbers = [v for v in values if v is not None]
    return round(max(numbers), 2) if numbers else None


# ── перепись ────────────────────────────────────────────────────────────────

def _totals(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(i.get("class") for i in items)
    causes = Counter(i.get("cause") for i in items
                     if i.get("class") == CLASS_UNMEASURED)
    usd: Dict[str, float] = {}
    no_number: Counter = Counter()
    for name in {str(i.get("class")) for i in items}:
        same = [i for i in items if str(i.get("class")) == name]
        total, missing = _sum_usd(same)
        usd[name] = total
        if missing:
            no_number[name] = missing
    return {"legs": {str(k): int(v) for k, v in counts.items()},
            "usd": {str(k): v for k, v in usd.items()},
            # Ноги без суммы названы ОТДЕЛЬНО: итог, в который они вошли бы
            # нулём, читался бы как полный, не будучи таким (инв. #17).
            "legs_without_usd": {str(k): int(v) for k, v in no_number.items()},
            # Причины «не измерено» разведены ПОИМЁННО: их четыре, и это разные
            # двери. «Ставки нет в журнале» лечится писателем, «форвардных
            # наблюдений нет» — фидом, и складывать их в одно число нельзя.
            "unmeasured_causes": {str(k): int(v) for k, v in causes.most_common()}}


def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None) -> Dict[str, Any]:
    """Перепись выживания ставок. Три исхода различимы, третий не сворачивается.

    ``now`` инъектируется: прибор судит о СВЕЖЕСТИ находок, и настенные часы
    сделали бы сцену смертной от календаря (`.claude/rules/deployment.md`).
    """
    now = now or datetime.now(timezone.utc)

    policy = load_policy(params)
    if not policy["measured"]:
        return _unmeasured(policy["reason"], now)

    decisions = read_decisions(data_dir)
    if not decisions["measured"]:
        return _unmeasured(decisions["reason"], now)
    records = decisions["records"]

    # Журнал ходов и псевдонимы ключей берутся у СОСЕДА — один адрес журнала
    # денег и один замер переименований, а не вторая копия знания о книге.
    from spa_core.monitoring import book_oscillation_census as boc
    journal = boc.read_journal(Path(data_dir))
    aliases: Dict[str, str] = {}
    entries: List[Dict[str, Any]] = []
    entry_note = None
    book_scale = 0.0
    if journal.get("measured"):
        moves = journal["moves"]
        book_scale = max(
            [sum(v for v in (m["from"] or {}).values() if isinstance(v, (int, float)))
             for m in moves]
            + [sum(v for v in (m["to"] or {}).values() if isinstance(v, (int, float)))
               for m in moves] or [0.0])
        aliases = boc.derive_aliases(moves, policy["min_leg_frac"] * book_scale)["aliases"]
    else:
        entry_note = (f"ось исполненных денег НЕ ИЗМЕРЕНА: {journal.get('reason')} — "
                      f"ось поверхности решения при этом измерена, и сворачивать их "
                      f"в один исход нельзя")

    panel = build_panel(records, aliases)
    pulls = find_pulls(records, panel, policy, aliases)
    if journal.get("measured"):
        entries = find_entries(journal["moves"], panel, policy, book_scale, aliases)

    gate_names: set = set()
    reason_families: Counter = Counter()
    for rec in records:
        gates = observed(rec["row"], "gates", kind=dict) or {}
        gate_names.update(str(k) for k in gates)
    faded_pulls = [p for p in pulls if p.get("class") == CLASS_FADED]
    faded_entries = [e for e in entries if e.get("class") == CLASS_FADED]
    swinging = [i for i in list(entries) + list(pulls)
                if i.get("class") == CLASS_OSCILLATING]
    for pull in faded_pulls:
        for reason in pull.get("reasons") or []:
            reason_families[str(reason).split(":")[0]] += 1

    screen = screen_survival_names(policy.get("column_field_names") or [],
                                   sorted(gate_names))

    # Свежесть САМОЙ ПОЗДНЕЙ тяги называется отдельно: `WARNING` без даты
    # читается как «старая история», а замер #704 нашёл две тяги ВЧЕРАШНИМ днём.
    latest_pull = max([p["ts"] for p in faded_pulls] or [""]) or None
    latest_pull_age_h = None
    if latest_pull:
        stamp = _parse_ts(latest_pull)
        if stamp is not None:
            latest_pull_age_h = round((now - stamp).total_seconds() / 3600.0, 2)

    fresh_window = timedelta(days=policy["fresh_days"])
    fresh_entries = [e for e in faded_entries
                     if (now - _parse_ts(e["ts"])) <= fresh_window]  # type: ignore[operator]
    if fresh_entries:
        status = STATUS_CRITICAL
    elif faded_entries or faded_pulls or swinging:
        # Колебание попадает в WARNING намеренно: «выживание не определено» —
        # это НЕ «ставка держалась», и зелёный вердикт на неопределённости был бы
        # тем самым fail-OPEN, тише красного теста (инв. #17).
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": ("§49 Persistence — «Transient APY spikes не вызывают "
                      "ненужные trades»"),
        "decisions": {"path": decisions["path"], "records": len(records),
                      "unparsed": decisions["unparsed"],
                      "undated": decisions["undated"],
                      "first_ts": records[0]["ts"].isoformat(),
                      "last_ts": records[-1]["ts"].isoformat()},
        "journal": {"measured": bool(journal.get("measured")),
                    "moves": len(journal.get("moves") or []),
                    "note": entry_note},
        "policy": {k: policy[k] for k in
                   ("min_gain_pp", "min_hold_days", "min_leg_frac", "fresh_days",
                    "mode", "version")},
        "panel": {"protocols": len(panel["panel"]),
                  "observations": sum(len(v) for v in panel["panel"].values()),
                  "moment_from_record": panel["fallback_moment"],
                  "dropped_values": panel["dropped_values"]},
        "aliases": aliases,
        "book_scale_usd": round(book_scale, 2),
        "entry_axis": _totals(entries),
        "pull_axis": _totals(pulls),
        "faded_entries": faded_entries,
        "faded_pulls": faded_pulls,
        "fresh_faded_entries": fresh_entries,
        "refusal_families_on_faded_pulls": dict(reason_families.most_common()),
        "oscillating": swinging,
        "latest_faded_pull_ts": latest_pull,
        "latest_faded_pull_age_hours": latest_pull_age_h,
        "survival_screen": screen,
        # Заголовочные числа ДУБЛИРУЮТСЯ наверх намеренно: мост и офис читают их
        # через `observed_number(doc, key)`, который смотрит верхний уровень. Это
        # не второе место для числа — оба вычислены здесь же, одной строкой.
        "faded_entry_legs": len(faded_entries),
        "faded_entry_usd": _sum_usd(faded_entries)[0],
        "faded_entry_legs_without_usd": _sum_usd(faded_entries)[1],
        "faded_pull_legs": len(faded_pulls),
        # Сумма по ДНЯМ, а НЕ различные деньги: одна и та же цель повторяется
        # изо дня в день (замер: $35 000 в `aave_v3` тянуло 09-05, 09-07, 09-14…),
        # поэтому рядом всегда печатается НАИБОЛЬШАЯ одиночная тяга — она и есть
        # честная цена одного дня.
        "faded_pull_usd": _sum_usd(faded_pulls)[0],
        "faded_pull_legs_without_usd": _sum_usd(faded_pulls)[1],
        "faded_pull_usd_max_single": _max_usd(faded_pulls),
        "fresh_faded_entry_legs": len(fresh_entries),
        "oscillating_legs": len(swinging),
        # Тот же порядок, что у тяги цели: сумма по ДНЯМ, а не различные деньги
        # (одна цель повторяется), поэтому рядом — наибольший одиночный случай.
        "oscillating_usd": _sum_usd(swinging)[0],
        "oscillating_usd_max_single": _max_usd(swinging),
        "no_survival_condition_named": screen["no_survival_condition_named"],
    }


def _unmeasured(reason: str, now: datetime) -> Dict[str, Any]:
    return {"measured": False, "status": STATUS_UNMEASURED, "reason": reason,
            "generated_at": now.isoformat(),
            "entry_axis": {"legs": {}, "usd": {}},
            "pull_axis": {"legs": {}, "usd": {}},
            "faded_entries": [], "faded_pulls": [], "fresh_faded_entries": [],
            "oscillating": [],
            "latest_faded_pull_ts": None, "latest_faded_pull_age_hours": None,
            "faded_entry_legs": 0, "faded_pull_legs": 0,
            "fresh_faded_entry_legs": 0, "oscillating_legs": 0,
            # Третий исход: сумм НЕТ, и ноль здесь был бы «измерено и равно нулю».
            "oscillating_usd": None, "oscillating_usd_max_single": None,
            "no_survival_condition_named": False}


# ── отчёт ───────────────────────────────────────────────────────────────────

def _usd_text(value: Optional[float]) -> str:
    """Сумма словами. ``None`` печатается как «НЕ ИЗМЕРЕНО», а не как «$0»."""
    return "НЕ ИЗМЕРЕНО" if value is None else f"${value:,.0f}"


def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"выживание ставки (§49 Persistence): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    ea, pa = report["entry_axis"], report["pull_axis"]
    return (f"выживание ставки (§49 Persistence): {report['status']} · "
            f"исполненных ног входа {sum(ea['legs'].values())} — ОСЕЛА ставка у "
            f"{report['faded_entry_legs']} на ${report['faded_entry_usd']:,.0f} "
            f"(держалась у {ea['legs'].get(CLASS_HELD, 0)}, КОЛЕБАЛАСЬ у "
            f"{ea['legs'].get(CLASS_OSCILLATING, 0)}, не измерено у "
            f"{ea['legs'].get(CLASS_UNMEASURED, 0)}) · цель тянуло "
            f"{sum(pa['legs'].values())} раз — на осевшей ставке "
            f"{report['faded_pull_legs']} (по дням ${report['faded_pull_usd']:,.0f}, "
            f"наибольшая одиночная {_usd_text(report['faded_pull_usd_max_single'])}) · "
            f"срок выживания {report['policy']['min_hold_days']:g} дн при "
            f"существенности {report['policy']['min_gain_pp']:g} pp "
            f"(колонка {report['policy']['mode']} {report['policy']['version']})")


def format_report(report: Dict[str, Any], limit: int = 5) -> List[str]:
    """Строки для офиса — находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        return lines
    if report["status"] == STATUS_WARNING and not report["faded_entries"]:
        age = report.get("latest_faded_pull_age_hours")
        when = (f"; самая поздняя тяга — {report.get('latest_faded_pull_ts', '')[:10]} "
                f"({age:.0f} ч назад)" if age is not None else
                "; дата самой поздней тяги НЕ ИЗМЕРЕНА")
        lines.append("[ВЕРДИКТ] исполненных входов на осевшей ставке в журнале нет, но "
                     "ЦЕЛЬ на них тянуло — деньги держал другой гейт, а не устойчивость "
                     "ставки; «сегодня тихо» тут не значит «защита есть»" + when)
    elif report["status"] == STATUS_WARNING:
        lines.append(f"[ВЕРДИКТ] свежих (внутри {report['policy']['fresh_days']:g} дн от "
                     f"now) входов на осевшей ставке нет, но в истории их "
                     f"{report['faded_entry_legs']} — «сегодня тихо» НЕ значит «такого "
                     f"не бывало»")
    if report.get("survival_screen", {}).get("no_survival_condition_named") is None:
        lines.append(f"[РУЧКА НЕ ИЗМЕРЕНА] "
                     f"{report['survival_screen'].get('reason', 'причина не названа')} — "
                     f"это третий исход, а не «ручки нет»")
    elif report.get("no_survival_condition_named"):
        lines.append(
            f"[НЕТ РУЧКИ ПО ПОСТРОЕНИЮ] среди "
            f"{len(report['survival_screen']['names_scanned'])} ИЗМЕРЕННЫХ имён (поля "
            f"колонки владельца + ключи гейтов из журнала) нет ни одного про выживание "
            f"ставки: ранжирование берёт ОДНО мгновенное наблюдение, и условия «ставка "
            f"дожила» в колонке не существует. Утверждение о ПОСТРОЕНИИ — от тишины оно "
            f"не гаснет")
    else:
        lines.append(f"[КАНДИДАТ В РУЧКУ] скрин имён нашёл "
                     f"{', '.join(report['survival_screen']['candidates'])} — проверить "
                     f"вручную, прибор кандидата не засчитывает")
    for item in report.get("fresh_faded_entries", [])[:limit]:
        lines.append(
            f"[СВЕЖИЙ ВХОД НА ОСЕВШЕЙ СТАВКЕ] {item.get('trade_id')} "
            f"{item['ts'][:10]}: ${item['usd']:,.0f} в `{item['protocol']}` на "
            f"{item.get('decided_pp')} %, за {item.get('horizon_days'):g} дн медиана "
            f"{item.get('forward_median_pp')} % (−{item.get('decline_pp')} pp, "
            f"форвардных наблюдений {item.get('forward_n')})")
    for item in report.get("faded_entries", [])[:limit]:
        if item in report.get("fresh_faded_entries", []):
            continue
        lines.append(
            f"[ВХОД НА ОСЕВШЕЙ СТАВКЕ] {item.get('trade_id')} {item['ts'][:10]}: "
            f"${item['usd']:,.0f} в `{item['protocol']}` на {item.get('decided_pp')} %, "
            f"за {item.get('horizon_days'):g} дн медиана "
            f"{item.get('forward_median_pp')} % (−{item.get('decline_pp')} pp)")
    for item in report.get("faded_pulls", [])[:limit]:
        if not item.get("gates_measured"):
            refused = ("гейты в записи НЕ ЗАПИСАНЫ — что держало книгу, НЕ ИЗМЕРЕНО "
                       "(это не «не держало ничто»)")
        else:
            refused = ", ".join(item.get("gates_refused") or []) or "ни один гейт не отказал"
        lines.append(
            f"[ЦЕЛЬ ТЯНУЛА НА ОСЕВШЕЙ СТАВКЕ] {item.get('cycle_date')}: "
            f"${item['usd']:,.0f} в `{item['protocol']}` на {item.get('decided_pp')} % → "
            f"за {item.get('horizon_days'):g} дн медиана {item.get('forward_median_pp')} % "
            f"(−{item.get('decline_pp')} pp); вердикт {item.get('verdict')}, отказали: "
            f"{refused}")
    extra = len(report.get("faded_pulls", [])) - limit
    if extra > 0:
        lines.append(f"… ещё {extra} случай(ев) тяги цели — полный перечень в артефакте")
    if report.get("oscillating_legs"):
        lines.append(
            f"[ВЫЖИВАНИЕ НЕ ОПРЕДЕЛЕНО] у {report['oscillating_legs']} случая(ев) "
            f"(по дням ${report['oscillating_usd']:,.0f}, наибольший одиночный "
            f"{_usd_text(report['oscillating_usd_max_single'])}) наблюдения ОДНОГО ключа внутри срока "
            f"удержания расходятся больше существенности и лежат по обе стороны порога: "
            f"«осела» и «держалась» неверны одинаково. Это не смягчение вердикта, а "
            f"отдельный исход — носитель наблюдает ставку не раз в сутки (класс ADR-312)")
        for item in report.get("oscillating", [])[:limit]:
            lines.append(
                f"   · {item.get('trade_id') or item.get('cycle_date')} "
                f"`{item['protocol']}` ${item['usd']:,.0f}: решали на "
                f"{item.get('decided_pp')} %, вперёд "
                f"{item.get('forward_min_pp')}…{item.get('forward_max_pp')} % "
                f"(размах {item.get('forward_span_pp')} pp)")
    if report.get("refusal_families_on_faded_pulls"):
        fams = " · ".join(f"{k} {v}" for k, v in
                          report["refusal_families_on_faded_pulls"].items())
        lines.append(f"[ЧТО ДЕРЖАЛО КНИГУ] причины отказа на днях осевшей ставки: {fams} "
                     f"— ни одна из них не про устойчивость ставки, и это и есть ответ "
                     f"на §49: критерий выполняется ПОБОЧНО")
    if report.get("aliases"):
        pairs = ", ".join(f"{a}→{b}" for a, b in sorted(report["aliases"].items()))
        lines.append(f"[ПСЕВДОНИМЫ] взяты замером у соседа (ADR-480): {pairs} — без них "
                     f"ряд ставки рвётся на переименовании ключа")
    unmeasured_usd = report["entry_axis"]["usd"].get(CLASS_UNMEASURED, 0.0)
    if unmeasured_usd:
        causes = observed(report["entry_axis"], "unmeasured_causes", kind=dict)
        if causes is None:
            named = "причины в артефакте НЕТ — это дефект прибора, а не «нет причин»"
        elif not causes:
            named = "причина не названа ни у одной ноги"
        else:
            named = " · ".join(f"{k} {v}" for k, v in causes.items())
        lines.append(f"[НЕ ИЗМЕРЕНО] ${unmeasured_usd:,.0f} исполненных денег, чью "
                     f"ставку проверить НЕЧЕМ — это отдельный исход, а не «ставка "
                     f"держалась». Двери: {named}")
    if report["journal"].get("note"):
        lines.append(f"[ОСЬ ДЕНЕГ] {report['journal']['note']}")
    lines.append("ОПОРА: доллары тяги цели НЕ складываются в «различные деньги» — одна "
                 "и та же цель повторяется изо дня в день, поэтому рядом с суммой по дням "
                 f"печатается наибольшая одиночная тяга "
                 f"({_usd_text(report['faded_pull_usd_max_single'])})")
    lines.append("ОПОРА: сравнение идёт ВНУТРИ одного носителя (записи решения, ставка + "
                 "момент наблюдения); расхождение производителей ставки — предмет "
                 "ADR-312, а не этого прибора")
    lines.append("НЕ ДОКЛАДЫВАЕТ: верность каждого входа (ставка умеет падать "
                 "по-настоящему) · надо ли добавлять ручку устойчивости (денежный путь, "
                 "предмет №1 — решает владелец) · пороги RiskPolicy v1.0, стоп-кран, "
                 "аллокатор и живой трек НЕ трогаются — прибор только читает")
    return lines


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь). Обратный порядок `atomic_save`
    # отвергает fail-CLOSED, и артефакт не появляется ВОВСЕ, а ступень при этом
    # докладывает `measured=True`: замер #701 на соседе, контроль читает ДИСК.
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    # Ненулевой код — только на СВЕЖИЙ исполненный вход на осевшей ставке, то
    # есть на то, что решается сегодня. `WARNING` печатается всегда, но кодом не
    # нудит: постоянно ненулевой прибор учит пропускать свой вывод, а
    # структурное утверждение держат ADR и карточка владельцу.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
