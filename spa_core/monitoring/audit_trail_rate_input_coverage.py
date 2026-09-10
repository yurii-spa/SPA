"""Сколько дней знаменателя способен рассудить ``audit_trail.jsonl`` (заказ #555).

Заказ цикла #555 (ADR-318) поставлен дословно так:

> **Сколько дней знаменателя способен рассудить ``audit_trail.jsonl`` — тот самый
> носитель прогонов, которым уже пользуется ADR-316?** Этот цикл мерил ОДИН
> названный заказом кандидат и получил ноль. Прежде чем объявлять второй вход
> неизмеримым на прошлом, обязан быть измерен носитель, который у ветки УЖЕ есть
> и который покрывает 19 дней журнала из 36, — то есть в пять раз больше дней.

И назвал ловушку заранее:

> В ``audit_trail`` лежат ``allocation_proposal`` живого аллокатора и
> ``risk_verdict`` — записи ДРУГОГО пути. Значит вопрос стои́т узко: несёт ли
> ``audit_trail`` **ставку, поданную на вход тени**, — а не «есть ли в нём числа,
> похожие на ставки».

Прибор устроен по этому вопросу. Пять слоёв отвечают на пять РАЗНЫХ вопросов, и
смешать их значило бы убедительно ответить не на тот.

## Слой 1 — ОСЬ ПРОГОНОВ. То, что у носителя ЕСТЬ, и это первый результат

У предыдущего кандидата (``apy_composition_log.jsonl``, ADR-318) не хватило
именно её: он касался двух дней знаменателя и на обоих держал по одному снимку.
Здесь ось прогонов настоящая — записи несут ``snapshot_id`` вида ``день:хеш``, и
на одном дне их бывают десятки. Слой считает: сколько дней знаменателя носитель
касается вообще и на скольких из них у него ДВА и более различных прогона.

Слой печатается первым намеренно и НЕ является ответом на заказ. Ось прогонов —
необходимое условие, не достаточное: рассудить движение ставки можно только там,
где носитель эту ставку несёт.

## Слой 2 — ВЕЛИЧИНА. Есть ли в записи объявленное поле ставки

Вопрос слоя: **несёт ли схема записи хоть одно поле со ставкой.** Ответ берётся
ЗАМЕРОМ, а не чтением исходников писателя: прибор обходит каждую запись до
листьев, собирает ПОЛНОЕ население путей (``data.target_usd.aave_v3`` и т.д.) и
классифицирует их. Класс ``rate_bearing`` присваивается по имени листа — и
именно поэтому население путей уезжает в артефакт целиком: читатель обязан иметь
возможность проверить классификацию, а не поверить ей.

**Чего слой НЕ утверждает:** что ни одно число трейла не выводимо из ставки.
Он утверждает ровно одно — запись не ОБЪЯВЛЯЕТ ставку своим полем.

## Слой 3 — ЛОВУШКА ЗАКАЗА. Числа, ПОХОЖИЕ на ставки

Ставка в трейле всё-таки встречается — внутри текста нарушения
``«<нога>: APY N% below minimum M%»``. Заказ требовал отличить это от носителя
ставок, и слой меряет покрытие таких строк ТЕМ ЖЕ правилом, что ADR-318: пара
«день знаменателя × нога» рассужена тогда и только тогда, когда у дня ДВА и
более различных прогона И нога получила значение не менее чем в двух из них.
Одно наблюдение не сравнивается ни с чем.

Причины нерассуженной пары названы поимённо и не растворяются друг в друге:
чинится у них разное.

## Слой 4 — ПОЧЕМУ ЭТО НЕ ЧИНИТСЯ ЧАСТОТОЙ. Цензура и разрешение

Два запрета, независимые от покрытия, и оба меряются НА САМОМ НОСИТЕЛЕ, а не
вычитываются из кода писателя.

**Цензура.** Строка со ставкой рождается только на ветке ОТКАЗА гейта. Прибор
меряет это на населении носителя двумя способами сразу: (а) сколько сообщённых
ставок удовлетворяют предикату, записанному в их же тексте (значение ниже
названного минимума); (б) сколько ног профинансировано в том же прогоне и при
этом БЕЗ сообщённой ставки. Второй способ и есть цензура в чистом виде: о ноге,
чья ставка прошла коридор, носитель молчит именно потому, что она прошла.

Величина, наблюдаемая лишь тогда, когда она провалила порог, не свидетельствует
о движении внутри дня ни при каком покрытии: наблюдение существует как функция
измеряемого значения.

**Разрешение.** Ставка в строке напечатана с фиксированным числом знаков после
запятой. Прибор считает это число по фактическим строкам и сравнивает с самой
узкой маржей, которая сегодня решает деньги (``target_stability.json``, поле
``margin_pp``) — не с константой, вписанной сюда. Сетка грубее маржи ⇒ носитель
не различает то, на чём стои́т решение. Артефакта маржей нет ⇒ третий исход,
а не молчаливое «разрешение достаточно».

## Слой 5 — СШИВКА ОСЕЙ. Можно ли одолжить ось прогонов носителю ставок

Ставка есть у одного носителя, ось прогонов — у другого. Слой меряет, можно ли
их сшить ПО ТОЖДЕСТВУ прогона: пересечение множеств идентификаторов и их форма.
Пересечение пусто и формы разные ⇒ сшивка по тождеству невозможна, и это предмет
следующего заказа, а не вывод этого прибора.

## ADVISORY

Прибор ничего не чинит и не предлагает чинить молча. Писатель трейла, писатель
журнала решений и его правило замены строки дня, ``POLLED_ADAPTERS``, пины,
``MIN_HIT_RATE``, ``TriggerParams``, пороги RiskPolicy v1.0 (в том числе
``min_apy_for_new_position``, чья ветка и рождает единственную ставку трейла),
потолки концентрации, стоп-кран и живой трек не трогаются; капитал не двигается.

## Почему прибор НЕ внесён в перепись потребителей журнала

``decision_journal_coverage.READERS`` — население потребителей КЛЮЧА ставки в
журнале решений, а не читателей журнала вообще (предикат храповика
``ReaderPopulationRatchet`` спрашивает ровно про ключ). Этот прибор ключа не
касается ни разу: из журнала он берёт только ``current_positions`` и
``target_positions``, чтобы построить ноги дня. Внеси его в ``READERS`` — и
``probe_readers`` выдал бы ``insensitive``, ИСТИННЫЙ ПО ПОСТРОЕНИЮ, деля
знаменатель переписи с настоящими потребителями. Это ровно тот класс, который
ADR-317 снял у соседа, и повторять его с другой стороны нельзя.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

VERSION = "audit_trail_rate_input_coverage/v1"

OUTPUT_FILENAME = "audit_trail_rate_input_coverage.json"
HISTORY_FILENAME = "allocation_rationale_history.jsonl"
CARRIER_FILENAME = "audit_trail.jsonl"
RATE_CARRIER_FILENAME = "apy_composition_log.jsonl"
MARGINS_FILENAME = "target_stability.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Разряд сравнения ставок — тот же, что у прибора ADR-318: носитель ставок и
#: журнал пишут проценты с четырьмя знаками.
_PP = 4

#: Единственная форма, которой ставка попадает в трейл: текст нарушения гейта.
#: Именно ЭТУ форму заказ назвал ловушкой — «числа, похожие на ставки».
_RATE_IN_TEXT = re.compile(
    r"^(?:Held APY\s+)?(?P<leg>[a-z0-9_]+):?\s*"
    r"(?:APY\s+)?(?P<value>[-+]?\d+(?:\.\d+)?)%\s+below minimum\s+"
    r"(?P<floor>[-+]?\d+(?:\.\d+)?)%"
)
#: Вторая ветка того же отказа — сверху коридора. Ловится отдельным выражением,
#: потому что предикат цензуры у неё ОБРАТНЫЙ (значение ВЫШЕ порога), и свалить
#: их в одно значило бы считать долю по неверному условию.
_RATE_IN_TEXT_ABOVE = re.compile(
    r"^(?:Held APY\s+)?(?P<leg>[a-z0-9_]+):?\s*"
    r"(?:APY\s+)?(?P<value>[-+]?\d+(?:\.\d+)?)%\s+exceeds maximum(?:\s+allowed)?\s+"
    r"(?P<floor>[-+]?\d+(?:\.\d+)?)%"
)

#: Лексикон имени, по которому лист признаётся КАНДИДАТОМ в носители ставки.
#: Список ОБЪЯВЛЕН, а не выведен: классификация обязана быть проверяемой
#: читателем, поэтому население путей уезжает в артефакт целиком (слой 2).
_RATE_LEXICON = ("apy", "rate", "yield", "apr")

#: Лексикон сверяется с ТОКЕНАМИ snake_case-имени, а не с подстрокой, и это
#: поправка ЗАМЕРА, а не вкусовая. Первая редакция искала подстроку и на живом
#: трейле признала ставкой `data.strategy_loop_active`: в слове «st-RATE-gy»
#: лежит «rate». Список исключений тут не помог бы — он лечил бы поводы, а не
#: класс; токен закрывает класс целиком.
#:
#: Полные имена, у которых токен `rate` есть, а ставкой поле не является.
#: Названы поимённо, чтобы «ставок нет» не держалось на удачном словаре.
_RATE_NAME_EXCEPTIONS = ("hit_rate", "fill_rate", "error_rate")

#: Классы нерассуженной пары — те же четыре, что у ADR-318, плюс пятый, которого
#: у соседа быть не могло: носитель ВООБЩЕ не несёт величины. Растворять их друг
#: в друге нельзя — чинится у них разное.
WHY_NO_QUANTITY = "carrier_declares_no_rate_field"
WHY_DAY_ABSENT = "day_absent_from_carrier"
WHY_ONE_SNAPSHOT = "single_snapshot_on_day"
WHY_LEG_ABSENT = "leg_absent_from_carrier"
WHY_LEG_ONCE = "leg_in_one_snapshot_only"
ADJUDICABLE = "adjudicable"


# ─────────────────────────── чтение носителей ───────────────────────────
def read_journal(data_dir: Path) -> Tuple[List[dict], str]:
    """Строки журнала решений. Битая строка не рушит замер — она называется."""
    rows: List[dict] = []
    broken = 0
    path = Path(data_dir) / HISTORY_FILENAME
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    broken += 1
                    continue
                if isinstance(row, dict) and row.get("cycle_date"):
                    rows.append(row)
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return [], f"{type(exc).__name__}: {exc}"
    if broken and not rows:
        return [], f"строк журнала не разобрано: {broken}"
    return rows, ""


def read_trail(data_dir: Path) -> Tuple[List[dict], str]:
    """Записи ``audit_trail.jsonl`` целиком — они же население слоя 2."""
    rows: List[dict] = []
    broken = 0
    path = Path(data_dir) / CARRIER_FILENAME
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    broken += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    broken += 1
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    if broken and not rows:
        return [], f"строк трейла не разобрано: {broken}"
    return rows, ""


def scored_days(data_dir: Path) -> Optional[Set[str]]:
    """Дни знаменателя ``hit_rate`` — у КАНОНИЧЕСКОГО производителя.

    Список не выписывается сюда руками: знаменатель определяет
    ``shadow_trigger_eval``, и спрашивать надо его. Не ответил ⇒ ``None``, то
    есть «не измерено», а не пустое множество: пустое читалось бы как
    «знаменатель пуст», и прибор объявил бы полное покрытие нуля.
    """
    try:
        from spa_core.paper_trading import shadow_trigger_eval as ste
        report = ste.evaluate_window(Path(data_dir), write=False)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        return None
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return None
    return {str(r.get("cycle_date")) for r in rows
            if not r.get("trivial") and r.get("outcome") in ("hit", "miss")}


def legs_of_day(row: dict) -> List[str]:
    """Ноги дня — ``current_positions ∪ target_positions`` (правило ADR-290)."""
    names: Set[str] = set()
    for key in ("current_positions", "target_positions"):
        book = row.get(key)
        if isinstance(book, dict):
            names.update(str(k) for k in book)
    return sorted(names)


def _day_of(row: dict) -> str:
    """День записи трейла. ``snapshot_id`` вида ``день:хеш`` — первый источник.

    Отметка стены (``timestamp``) берётся ТОЛЬКО как запасной: она про минуту
    записи, а день прогона объявлен самим прогоном.
    """
    sid = row.get("snapshot_id")
    if isinstance(sid, str) and len(sid) >= 10:
        return sid[:10]
    ts = row.get("timestamp")
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else ""


# ───────────────────────── слой 1: ось прогонов ─────────────────────────
def _run_axis(trail: List[dict], denominator: Set[str]) -> dict:
    """Что у носителя ЕСТЬ: дни знаменателя и число различных прогонов на них.

    Необходимое условие, не достаточное. Слой не отвечает на заказ и говорит об
    этом полем ``not_the_answer``: читатель, увидевший «5 дней с двумя и более
    прогонами», прочтёт это как «пять дней рассужены», если его не остановить.
    """
    runs: Dict[str, Set[str]] = {}
    for row in trail:
        day = _day_of(row)
        if not day:
            continue
        sid = row.get("snapshot_id")
        runs.setdefault(day, set()).add(sid if isinstance(sid, str) else "")
    touched = sorted(d for d in denominator if d in runs)
    multi = sorted(d for d in touched if len(runs[d]) >= 2)
    return {
        "measured": True,
        "trail_days_total": len(runs),
        "denominator_days": len(denominator),
        "denominator_days_touched": len(touched),
        "denominator_days_with_two_or_more_runs": len(multi),
        "days_touched": touched,
        "days_with_two_or_more_runs": multi,
        "runs_per_touched_day": {d: len(runs[d]) for d in touched},
        "not_the_answer": (
            "ось прогонов есть — это НЕОБХОДИМОЕ условие, не достаточное. "
            "Рассудить движение ставки можно лишь там, где носитель НЕСЁТ "
            "ставку; о ней отвечают слои 2 и 3, а не этот"),
    }


# ──────────────────── слой 2: объявляет ли запись ставку ────────────────────
def _leaf_paths(obj, prefix: str, out: Dict[str, Dict[str, object]]) -> None:
    """Все листья записи, путём — с ЧИСЛОМ и РОДОМ значений.

    Род нужен слою: ставка есть величина, и булев флаг ею быть не может ни при
    каком имени. Списки схлопываются в ``[]`` — индекс не имя.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            _leaf_paths(value, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(obj, list):
        for value in obj:
            _leaf_paths(value, prefix + "[]", out)
    else:
        entry = out.setdefault(prefix, {"count": 0, "types": set()})
        entry["count"] = int(entry["count"]) + 1  # type: ignore[call-overload]
        types = entry["types"]
        assert isinstance(types, set)
        types.add(type(obj).__name__)


def _names_a_rate(path: str) -> bool:
    """Называет ли ПУТЬ ставку — по токенам ЛЮБОГО своего звена.

    Два уточнения, и оба — поправки замера, а не вкусовые.

    **Токен, а не подстрока.** Подстрочный критерий на живом трейле признал
    ставкой ``strategy_loop_active`` («st-RATE-gy»).

    **Любое звено, а не только последнее.** Ставку писатель положил бы ровно
    так же, как кладёт деньги, — картой по ногам (``target_usd.aave_v3``), и
    тогда лист зовётся именем НОГИ. Критерий по последнему звену не увидел бы
    ``apy_pct.aave_v3`` вовсе, то есть молчал бы после того, как ставку
    наконец добавили, — ложное отрицание в самую опасную сторону.

    Это КАНДИДАТ, не вердикт: род значения проверяется отдельно.
    """
    for segment in path.lower().split("."):
        name = segment.replace("[]", "")
        if not name or name in _RATE_NAME_EXCEPTIONS:
            continue
        if any(token in _RATE_LEXICON for token in name.split("_")):
            return True
    return False


def _quantity(trail: List[dict]) -> dict:
    """Несёт ли схема записи объявленное поле ставки. Замером, не чтением кода.

    Условий ДВА, и оба обязательны: имя называет ставку И значение есть число.
    Одного имени мало — замер это показал; одного рода мало тем более (USD тоже
    число), поэтому ни одно из условий не снимается.
    """
    paths: Dict[str, Dict[str, object]] = {}
    for row in trail:
        _leaf_paths(row, "", paths)
    named = sorted(p for p in paths if _names_a_rate(p))
    numeric = {"int", "float"}
    rate_paths = sorted(
        p for p in named
        if numeric & set(paths[p]["types"])  # type: ignore[arg-type]
    )
    rejected = sorted(set(named) - set(rate_paths))
    return {
        "measured": True,
        "records": len(trail),
        "leaf_paths_total": len(paths),
        "named_like_a_rate": named,
        "rate_bearing_paths": rate_paths,
        "named_but_not_numeric": rejected,
        "declares_a_rate": bool(rate_paths),
        "leaf_paths": {p: {"count": v["count"],
                           "types": sorted(v["types"])}  # type: ignore[arg-type]
                       for p, v in sorted(paths.items())},
        "criterion": (
            "лист несёт ставку, если ИМЯ называет её токеном "
            f"(лексикон {list(_RATE_LEXICON)}, исключения "
            f"{list(_RATE_NAME_EXCEPTIONS)}) И значение есть число. Население "
            "путей приложено целиком, чтобы классификацию можно было "
            "проверить, а не принять"),
        "does_not_prove": (
            "что ни одно число трейла не выводимо из ставки. Утверждается "
            "ровно одно: запись не ОБЪЯВЛЯЕТ ставку своим полем"),
    }


# ───────────────── слой 3: ловушка — числа, похожие на ставки ─────────────────
def _rates_in_text(trail: List[dict]) -> Tuple[Dict[str, Dict[str, Dict[str, float]]],
                                               List[dict]]:
    """Ставки, вынутые из текста нарушений → ``{день: {прогон: {нога: ставка}}}``.

    Второй возврат — плоский список наблюдений со ВСЕМ, что нужно слою 4:
    значение, названный в той же строке порог и сторона отказа.
    """
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    flat: List[dict] = []
    for row in trail:
        day = _day_of(row)
        sid = row.get("snapshot_id")
        if not day or not isinstance(sid, str):
            continue
        data = row.get("data")
        if not isinstance(data, dict):
            continue
        for field in ("violations", "warnings"):
            entries = data.get(field)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                for pattern, side in ((_RATE_IN_TEXT, "below_floor"),
                                      (_RATE_IN_TEXT_ABOVE, "above_ceiling")):
                    match = pattern.match(entry.strip())
                    if not match:
                        continue
                    leg = match.group("leg")
                    value = round(float(match.group("value")), _PP)
                    out.setdefault(day, {}).setdefault(sid, {})[leg] = value
                    flat.append({
                        "cycle_date": day, "snapshot_id": sid, "leg": leg,
                        "value_pp": value,
                        "threshold_pp": round(float(match.group("floor")), _PP),
                        "side": side, "field": field,
                        "decimals": len(match.group("value").split(".")[1])
                                    if "." in match.group("value") else 0,
                    })
                    break
    return out, flat


def _classify_pair(day: str, leg: str, carrier, declares_rate: bool) -> dict:
    """Способен ли носитель рассудить эту пару — и если нет, ПОЧЕМУ именно."""
    if not declares_rate and not carrier:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_NO_QUANTITY,
                "runs_on_day": 0, "observations": 0}
    snaps = carrier.get(day)
    if not snaps:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_DAY_ABSENT,
                "runs_on_day": 0, "observations": 0}
    if len(snaps) < 2:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_ONE_SNAPSHOT,
                "runs_on_day": len(snaps),
                "observations": sum(1 for v in snaps.values() if leg in v)}
    values = [v[leg] for _, v in sorted(snaps.items()) if leg in v]
    if not values:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_LEG_ABSENT,
                "runs_on_day": len(snaps), "observations": 0}
    if len(values) < 2:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_LEG_ONCE,
                "runs_on_day": len(snaps), "observations": 1}
    return {"cycle_date": day, "leg": leg, "verdict": ADJUDICABLE,
            "runs_on_day": len(snaps), "observations": len(values),
            "moved": max(values) != min(values),
            "spread_pp": round(max(values) - min(values), _PP)}


def _coverage(days_in_denominator: List[dict], carrier,
              declares_rate: bool) -> dict:
    """Слой 3 целиком: пары знаменателя, поимённо и по классам."""
    pairs: List[dict] = []
    for row in days_in_denominator:
        day = str(row["cycle_date"])
        for leg in legs_of_day(row):
            pairs.append(_classify_pair(day, leg, carrier, declares_rate))
    by_verdict: Dict[str, int] = {}
    for pair in pairs:
        by_verdict[pair["verdict"]] = by_verdict.get(pair["verdict"], 0) + 1
    adjudicable = [p for p in pairs if p["verdict"] == ADJUDICABLE]
    return {
        "measured": True,
        # ЧТО именно рассуживалось. Без этой строки `day_absent_from_carrier=75`
        # читается как «в трейле есть поле ставки, просто не на тех днях» — а
        # поля нет вовсе, и мерилась ЗАПАСНАЯ поверхность, текст нарушений.
        "surface": ("поле ставки в записи" if declares_rate
                    else "ТЕКСТ нарушений: объявленного поля ставки у записи "
                         "нет вовсе (слой 2), и покрытие ниже посчитано по "
                         "единственной оставшейся поверхности"),
        "denominator_days": len(days_in_denominator),
        "pairs_total": len(pairs),
        "pairs_adjudicable": len(adjudicable),
        "pairs_moved": sum(1 for p in adjudicable if p["moved"]),
        "by_verdict": dict(sorted(by_verdict.items())),
        "days_touched_by_rate": sorted(
            {str(r["cycle_date"]) for r in days_in_denominator
             if str(r["cycle_date"]) in carrier}),
    }


# ─────────────── слой 4: цензура и разрешение — запреты вне покрытия ───────────
def _censoring(flat: List[dict], trail: List[dict]) -> dict:
    """Наблюдается ли ставка лишь тогда, когда она провалила порог.

    Меряется НА НОСИТЕЛЕ двумя независимыми способами; ноль наблюдений ⇒ третий
    исход, а не «цензуры нет».
    """
    if not flat:
        return {"measured": False,
                "reason": ("ставок в тексте нарушений не найдено — цензура НЕ "
                           "ИЗМЕРЕНА; ноль наблюдений не есть её отсутствие"),
                "observations": 0, "censored": None}
    satisfy = sum(1 for f in flat
                  if (f["side"] == "below_floor" and f["value_pp"] < f["threshold_pp"])
                  or (f["side"] == "above_ceiling" and f["value_pp"] > f["threshold_pp"]))
    # Второй способ: нога профинансирована в том же прогоне, а ставки о ней нет.
    reported: Dict[str, Set[str]] = {}
    for f in flat:
        reported.setdefault(f["snapshot_id"], set()).add(f["leg"])
    funded: Dict[str, Set[str]] = {}
    for row in trail:
        sid = row.get("snapshot_id")
        data = row.get("data")
        if not isinstance(sid, str) or not isinstance(data, dict):
            continue
        book = data.get("target_usd")
        if isinstance(book, dict):
            funded.setdefault(sid, set()).update(
                str(k) for k, v in book.items()
                if isinstance(v, (int, float)) and v > 0)
    silent: List[dict] = []
    for sid in sorted(reported):
        gap = sorted(funded.get(sid, set()) - reported[sid])
        if gap:
            silent.append({"snapshot_id": sid, "funded_without_rate": gap})
    return {
        "measured": True,
        "observations": len(flat),
        "satisfying_own_refusal_predicate": satisfy,
        "censored": satisfy == len(flat),
        "runs_with_a_reported_rate": len(reported),
        "funded_legs_without_a_reported_rate": silent,
        "why_frequency_cannot_fix_it": (
            "величина, наблюдаемая лишь тогда, когда она провалила порог, не "
            "свидетельствует о движении внутри дня ни при каком покрытии: "
            "наблюдение существует как функция измеряемого значения"),
    }


def _resolution(flat: List[dict], data_dir: Path) -> dict:
    """Различает ли сетка печати ту маржу, на которой сегодня стоя́т деньги."""
    if not flat:
        return {"measured": False,
                "reason": "ставок в тексте нет — разрешение НЕ ИЗМЕРЕНО",
                "grid_pp": None, "finest_margin_pp": None,
                "resolves_the_deciding_margin": None}
    decimals = max(f["decimals"] for f in flat)
    grid = round(10.0 ** (-decimals), 10)
    margins: List[dict] = []
    reason = ""
    try:
        doc = json.loads((Path(data_dir) / MARGINS_FILENAME).read_text(encoding="utf-8"))
        for entry in (doc.get("protocols") or []):
            if not isinstance(entry, dict):
                continue
            margin = entry.get("margin_pp")
            if isinstance(margin, (int, float)) and margin > 0:
                margins.append({"protocol": entry.get("protocol")
                                            or entry.get("adapter"),
                                "margin_pp": round(float(margin), _PP),
                                "usd": entry.get("usd") or entry.get("target_usd")})
    except Exception as exc:  # noqa: BLE001
        reason = f"маржи не прочитаны ({type(exc).__name__}: {exc})"
    if not margins:
        return {"measured": False,
                "reason": reason or ("в артефакте маржей нет ни одной "
                                     "положительной — сравнивать сетку не с чем"),
                "grid_pp": grid, "decimals": decimals,
                "finest_margin_pp": None,
                "resolves_the_deciding_margin": None}
    finest = min(margins, key=lambda m: m["margin_pp"])
    return {
        "measured": True,
        "decimals": decimals,
        "grid_pp": grid,
        "finest_margin_pp": finest["margin_pp"],
        "finest_margin_at": finest["protocol"],
        "finest_margin_usd": finest["usd"],
        "coarser_by_times": (round(grid / finest["margin_pp"], 1)
                             if finest["margin_pp"] else None),
        "resolves_the_deciding_margin": grid <= finest["margin_pp"],
        "margins_considered": len(margins),
    }


# ───────────────────── слой 5: сшиваются ли оси прогонов ─────────────────────
def _join(trail: List[dict], data_dir: Path) -> dict:
    """Одолжима ли ось прогонов трейла носителю ставок — ПО ТОЖДЕСТВУ прогона."""
    theirs: Set[str] = set()
    path = Path(data_dir) / RATE_CARRIER_FILENAME
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                snap = row.get("snapshot") if isinstance(row, dict) else None
                if isinstance(snap, str):
                    theirs.add(snap)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"носитель ставок не прочитан "
                          f"({type(exc).__name__}: {exc})",
                "joinable_by_identity": None}
    ours: Set[str] = set()
    for row in trail:
        sid = row.get("snapshot_id")
        if isinstance(sid, str):
            ours.add(sid)
    if not ours or not theirs:
        return {"measured": False,
                "reason": ("у одного из носителей нет ни одного идентификатора "
                           "прогона — сшивку сравнивать не с чем"),
                "joinable_by_identity": None}
    shared = ours & theirs
    return {
        "measured": True,
        "trail_run_ids": len(ours),
        "rate_carrier_run_ids": len(theirs),
        "shared_run_ids": len(shared),
        "joinable_by_identity": bool(shared),
        "trail_id_sample": sorted(ours)[-1],
        "rate_carrier_id_sample": sorted(theirs)[-1],
        "note": ("сшивка ПО ВРЕМЕНИ здесь не измеряется намеренно: у правила "
                 "близости обязана быть СВОЯ цена ошибки, и одна убедительная "
                 "пара её не даёт — это предмет следующего заказа"),
    }


# ───────────────────────────── сборка ─────────────────────────────
_DOES_NOT_REPORT = (
    "каким был бы вердикт тени при другой ставке того же дня, и выводимо ли "
    "хоть одно число трейла из ставки. Прибор меряет, НЕСЁТ ли носитель ставку "
    "и на скольких парах способен рассудить её движение; отсутствие поля не "
    "есть утверждение о самих вердиктах тех дней")

_ADVISORY = (
    "ADVISORY: писатель audit_trail, писатель журнала решений и его правило "
    "замены строки дня, POLLED_ADAPTERS, пины, MIN_HIT_RATE, TriggerParams, "
    "пороги RiskPolicy v1.0 (включая min_apy_for_new_position), потолки "
    "концентрации, стоп-кран и живой трек не тронуты; капитал не двигается")


def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Полный замер. Детерминирован при тех же файлах на диске.

    ``now`` — только отметка отчёта: прибор не судит о свежести и не берёт
    времени у стены ни в одном вердикте.
    """
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "order": ("заказ #555 (ADR-318): сколько дней знаменателя способен "
                  "рассудить audit_trail.jsonl"),
        "carrier_file": CARRIER_FILENAME,
        "findings": [],
        "third_outcomes": [],
    }

    journal, jerr = read_journal(data_dir)
    trail, terr = read_trail(data_dir)
    doc["journal_rows"] = len(journal)
    doc["carrier"] = {"measured": not terr, "reason": terr or "",
                      "records": len(trail)}

    if terr or not trail:
        doc["status"] = STATUS_UNMEASURED
        doc["third_outcomes"].append(
            f"носитель {CARRIER_FILENAME} не прочитан "
            f"({terr or 'ни одной записи'}) — ни ось прогонов, ни величину "
            "строить не из чего")
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] носитель не прочитан: {terr or 'пуст'}")
        doc["run_axis"] = {"measured": False, "reason": terr or "носитель пуст"}
        doc["quantity"] = {"measured": False, "reason": terr or "носитель пуст"}
        doc["coverage"] = {"measured": False, "reason": terr or "носитель пуст"}
        doc["censoring"] = {"measured": False, "reason": "носитель не прочитан"}
        doc["resolution"] = {"measured": False, "reason": "носитель не прочитан"}
        doc["run_axis_join"] = {"measured": False, "reason": "носитель не прочитан"}
        doc["population"] = {"scoreable": 0}
        doc["does_not_report"] = _DOES_NOT_REPORT
        doc["advisory"] = _ADVISORY
        return doc

    quantity = _quantity(trail)
    rates, flat = _rates_in_text(trail)
    doc["quantity"] = quantity
    doc["censoring"] = _censoring(flat, trail)
    doc["resolution"] = _resolution(flat, data_dir)
    doc["run_axis_join"] = _join(trail, data_dir)

    denominator = scored_days(data_dir)
    if denominator is None or not journal:
        doc["status"] = STATUS_UNMEASURED
        why = ("журнал решений не прочитан "
               f"({jerr or 'пуст'})" if not journal else
               "знаменатель hit_rate не получен от "
               "shadow_trigger_eval.evaluate_window — пустое множество здесь "
               "читалось бы как «знаменатель пуст»")
        doc["run_axis"] = {"measured": False, "reason": why}
        doc["coverage"] = {"measured": False, "reason": why}
        doc["population"] = {"scoreable": 0}
        doc["third_outcomes"].append(why)
        doc["findings"].append(f"[НЕ ИЗМЕРЕНО] {why}")
        doc["does_not_report"] = _DOES_NOT_REPORT
        doc["advisory"] = _ADVISORY
        return doc

    doc["run_axis"] = _run_axis(trail, denominator)
    in_denominator = [r for r in journal
                      if str(r.get("cycle_date")) in denominator]
    coverage = _coverage(in_denominator, rates, quantity["declares_a_rate"])
    doc["coverage"] = coverage
    doc["population"] = {"scoreable": coverage["pairs_total"]}
    doc["status"] = _status(coverage)
    doc["third_outcomes"].extend(_third_outcomes(doc, coverage))
    doc["findings"].extend(_findings(doc, coverage))
    doc["does_not_report"] = _DOES_NOT_REPORT
    doc["advisory"] = _ADVISORY
    return doc


def _status(coverage: dict) -> str:
    """Вердикт прибора. «Нечем измерить» и «измерено, всё тихо» — РАЗНОЕ."""
    if not coverage.get("pairs_total"):
        return STATUS_UNMEASURED
    if not coverage.get("pairs_adjudicable"):
        return STATUS_CRITICAL
    if coverage["pairs_adjudicable"] < coverage["pairs_total"]:
        return STATUS_WARNING
    return STATUS_OK


def _third_outcomes(doc: dict, coverage: dict) -> List[str]:
    out: List[str] = []
    unresolved = coverage["pairs_total"] - coverage["pairs_adjudicable"]
    if unresolved:
        out.append(
            f"движение ставки НЕ ИЗМЕРЕНО на {unresolved} пар(ах) из "
            f"{coverage['pairs_total']}: носитель этих пар рассудить не может. "
            "Это не «ставка не двигалась» — это отсутствие наблюдения")
    for key in ("censoring", "resolution", "run_axis_join"):
        block = doc.get(key) or {}
        if not block.get("measured") and block.get("reason"):
            out.append(block["reason"])
    return [x for x in out if x]


def _findings(doc: dict, coverage: dict) -> List[str]:
    out: List[str] = []
    axis = doc.get("run_axis") or {}
    quantity = doc.get("quantity") or {}
    out.append(
        f"[ОТВЕТ] знаменатель hit_rate — {coverage['denominator_days']} дн., "
        f"пар «день × нога» {coverage['pairs_total']}; носитель "
        f"{CARRIER_FILENAME} способен рассудить "
        f"{coverage['pairs_adjudicable']} из них "
        f"(движение наблюдено на {coverage['pairs_moved']})")
    if axis.get("measured"):
        out.append(
            f"[ОСЬ ЕСТЬ] трейл касается "
            f"{axis['denominator_days_touched']} дн. знаменателя из "
            f"{axis['denominator_days']}, и на "
            f"{axis['denominator_days_with_two_or_more_runs']} из них держит "
            f"ДВА и более различных прогона "
            f"(прогонов на день: {axis['runs_per_touched_day']}). "
            "Это необходимое условие, НЕ ответ на заказ")
    if quantity.get("measured") and not quantity.get("declares_a_rate"):
        out.append(
            f"[CRITICAL] запись трейла не ОБЪЯВЛЯЕТ ставку ни одним полем: "
            f"{quantity['leaf_paths_total']} различных путей-листьев на "
            f"{quantity['records']} записях, несущих ставку — 0. Ось прогонов у "
            "носителя лучшая в ветке, а величины, ради которой заказ его назвал, "
            "в нём нет вовсе")
    cens = doc.get("censoring") or {}
    if cens.get("measured"):
        out.append(
            f"[ЛОВУШКА] ставка встречается только в ТЕКСТЕ нарушения: "
            f"{cens['observations']} наблюдени(е/я/й) на "
            f"{cens['runs_with_a_reported_rate']} прогон(е/ах), и "
            f"{cens['satisfying_own_refusal_predicate']} из них удовлетворяют "
            "предикату отказа, записанному в их же тексте"
            + (" — носитель ЦЕНЗУРИРОВАН" if cens.get("censored") else ""))
        for entry in (cens.get("funded_legs_without_a_reported_rate") or []):
            out.append(
                f"[ЛОВУШКА] прогон {entry['snapshot_id']}: профинансированы, но "
                f"ставки о них носитель молчит — {', '.join(entry['funded_without_rate'])}. "
                "О ноге, чья ставка прошла коридор, он молчит именно потому, что "
                "она прошла")
    res = doc.get("resolution") or {}
    if res.get("measured") and not res.get("resolves_the_deciding_margin"):
        out.append(
            f"[CRITICAL] сетка печати {res['grid_pp']} пп ({res['decimals']} "
            f"знак(а/ов) после запятой) грубее самой узкой маржи, на которой "
            f"сегодня стоя́т деньги — {res['finest_margin_pp']} пп у "
            f"{res['finest_margin_at']} — в {res['coarser_by_times']} раз(а). "
            "Даже при полном покрытии носитель не различал бы то, на чём "
            "стои́т решение")
    join = doc.get("run_axis_join") or {}
    if join.get("measured") and not join.get("joinable_by_identity"):
        out.append(
            f"[ОПОРА] оси прогонов двух носителей НЕ сшиваются по тождеству: "
            f"{join['trail_run_ids']} идентификаторов трейла против "
            f"{join['rate_carrier_run_ids']} у носителя ставок, общих "
            f"{join['shared_run_ids']}; формы разные "
            f"(«{join['trail_id_sample']}» против "
            f"«{join['rate_carrier_id_sample']}»)")
    if not coverage["pairs_adjudicable"] and coverage["pairs_total"]:
        out.append(
            f"[CRITICAL] о ВТОРОМ входе тени трейл не свидетельствует НИ НА "
            f"ОДНОЙ паре знаменателя ({coverage['pairs_total']} пар): "
            + ", ".join(f"{k}={v}" for k, v in coverage["by_verdict"].items())
            + ". Это ВТОРОЙ названный заказами кандидат, давший ноль, и отказы "
            "у них РАЗНОЙ природы: у соседа была величина без дней "
            "(восполнимо вперёд), здесь — дни без величины")
    for line in doc.get("third_outcomes") or []:
        out.append(f"[НЕ ИЗМЕРЕНО] {line}")
    return out


# ────────────────────────────── проводка ──────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: сперва ОСЬ, потом ВЕЛИЧИНА, потом доля.

    Ось идёт первой, потому что она у носителя ЕСТЬ и именно её не хватило
    предыдущему кандидату; но сразу за ней обязана идти строка о величине —
    читатель, увидевший «трейл покрывает 7 дней знаменателя» и не увидевший
    следующей строки, прочтёт это как «семь дней рассужены».
    """
    out: List[str] = []
    coverage = doc.get("coverage") or {}
    out.append(
        f"   рассуживает ли audit_trail знаменатель (заказ #555): "
        f"{doc.get('status')} · дней журнала {doc.get('journal_rows')} · "
        f"знаменатель {coverage.get('denominator_days')} дн. · пар «день × нога» "
        f"{coverage.get('pairs_total')} · трейл рассуживает "
        f"{coverage.get('pairs_adjudicable')}")
    axis = doc.get("run_axis") or {}
    if axis.get("measured"):
        out.append(
            f"   ось прогонов ЕСТЬ: дней знаменателя касается "
            f"{axis['denominator_days_touched']} из {axis['denominator_days']}, "
            f"с двумя и более прогонами — "
            f"{axis['denominator_days_with_two_or_more_runs']} "
            f"(необходимое условие, не ответ)")
    else:
        out.append(f"   ось прогонов НЕ ИЗМЕРЕНА: {axis.get('reason')}")
    quantity = doc.get("quantity") or {}
    if quantity.get("measured"):
        out.append(
            f"   величина: путей-листьев {quantity['leaf_paths_total']} на "
            f"{quantity['records']} записях, несущих ставку "
            f"{len(quantity['rate_bearing_paths'])} — запись ставку "
            f"{'ОБЪЯВЛЯЕТ' if quantity['declares_a_rate'] else 'НЕ ОБЪЯВЛЯЕТ'}")
    else:
        out.append(f"   величина НЕ ИЗМЕРЕНА: {quantity.get('reason')}")
    cens = doc.get("censoring") or {}
    if cens.get("measured"):
        out.append(
            f"   цензура: {cens['satisfying_own_refusal_predicate']} из "
            f"{cens['observations']} наблюдений удовлетворяют предикату отказа "
            f"— носитель {'ЦЕНЗУРИРОВАН' if cens['censored'] else 'не цензурирован'}")
    else:
        out.append(f"   цензура НЕ ИЗМЕРЕНА: {cens.get('reason')}")
    res = doc.get("resolution") or {}
    if res.get("measured"):
        out.append(
            f"   разрешение: сетка {res['grid_pp']} пп против самой узкой маржи "
            f"{res['finest_margin_pp']} пп ({res['finest_margin_at']}) — "
            f"{'различает' if res['resolves_the_deciding_margin'] else 'НЕ РАЗЛИЧАЕТ'}")
    else:
        out.append(f"   разрешение НЕ ИЗМЕРЕНО: {res.get('reason')}")
    join = doc.get("run_axis_join") or {}
    if join.get("measured"):
        out.append(
            f"   сшивка осей по тождеству прогона: общих идентификаторов "
            f"{join['shared_run_ids']} — "
            f"{'возможна' if join['joinable_by_identity'] else 'НЕВОЗМОЖНА'}")
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("does_not_report"):
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {doc['does_not_report']}")
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
        "warn": sum(1 for x in findings
                    if x.startswith("[ЛОВУШКА]") or x.startswith("[ОПОРА]")
                    or x.startswith("[ОСЬ ЕСТЬ]")),
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
        description="сколько дней знаменателя способен рассудить audit_trail "
                    "(заказ #555)")
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
