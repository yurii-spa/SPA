#!/usr/bin/env python3
"""Удержалась ли ставка, на которой ушли деньги — замер по журналу ходов.

Критерий §49 `Persistence` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #702.

Дословно критерий звучит так: **«Transient APY spikes не вызывают ненужные
trades»**, а §41 того же ТЗ называет `minimum persistence` обязательным
ограничением авто-исполнения. До этого прибора критерий был ПРОЗОЙ: цикл #508
измерил, что величину «преимущество держится N часов» **не считает никто —
производителя нет**, и на том остановился. Здесь мерится не наличие
производителя, а ИСХОД: деньги ходили, и по журналу видно, держалась ли ставка,
ради которой они ушли.

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь. Для каждого СОСТОЯВШЕГОСЯ хода: выгода хода в день входа против
выгоды того же хода на ставках следующих дней, внутри горизонта окупаемости
владельца (`max_payback_days`). Обе величины считаются по ОДНИМ И ТЕМ ЖЕ ногам
и по наблюдённым ставкам — это не прогноз, а сверка вчерашнего решения с тем,
что потом наблюдалось.

Форма вреда, названная владельцем, получает здесь точное выражение: ход
**прошёл планку владельца в день входа** (`gain >= min_gain_pp`), а на ставках
горизонта опустился **ниже этой же планки** — то есть будь ставки следующих
дней известны, планка самого владельца ход бы запретила. Деньги ушли на ставке,
которая не продержалась.

Почему производитель ставок — накопитель, а не поверхность решения
------------------------------------------------------------------------------
Вопрос про ДНИ требует производителя, у которого есть дни.
`data/apy_series_daily.json` — ежедневный накопитель живых ставок, и пропуск в
нём не интерполируется (день, когда фид молчал, остаётся пустым). Поверхность
решения (`data/allocation_rationale_history.jsonl`) несёт в каждой записи
**ровно один** день наблюдения — это ИЗМЕРЕНО (см. ``gate_surface``), а не
предположено, и именно поэтому она отвечает на другой вопрос: что гейт МОГ
видеть. Persistence из одного дня не выводится ни при каком пороге.

`min_hold_ok` и `cooldown_ok` этот вопрос НЕ закрывают: они меряют возраст
НАШЕЙ позиции и частоту НАШИХ ходов. История самой ставки в них не входит.

Своих чисел у прибора нет ни одного
------------------------------------------------------------------------------
Планка выгоды (`min_gain_pp`), горизонт (`max_payback_days`) и существенность
ноги (`min_leg_frac`) берутся из `TriggerParams.for_mode()` — колонки ADR-060
§3, которой судит живой путь. §22 приказа требует дословно: «Все значения
должны быть config/policy. **Не hardcode**». Колонка недоступна ⇒ **третий
исход**, а не подставленное умолчание.

Определение дневной выгоды тоже не переписано заново: используется
``shadow_trigger_eval._day_gain_usd`` — тот же, которым живёт теневой
оценщик и сверка прогноза (ADR-нумерация §3 ТЗ: не строить вторую модель того
же). Он fail-CLOSED по дню: если хоть одна двинутая нога в этот день без
ставки, день не оценивается вовсе — частичная оценка молча сдвигала бы ответ в
сторону той ноги, у которой данные оказались.

«Не измерено» здесь — самостоятельный исход, а не ноль
------------------------------------------------------------------------------
Ход НЕ оценивается, когда: он старше первого дня накопителя · в день входа у
какой-то из его ног нет наблюдённой ставки · вперёд не нашлось ни одного
оценённого дня. Каждый такой ход попадает в отчёт С ПРИЧИНОЙ и со своим
оборотом: «мерить нечем» никогда не выдаётся за «ставка держалась»
(инвариант #17).

Отдельный род «не измерено» — **ключ книги, которого у накопителя нет вовсе**.
Он назван поимённо, и про каждый такой ключ прибор ГОВОРИТ, что о нём известно
поверхности решения (сколько дней, последняя ставка, когда) и какой ключ
накопителя ближе всего к нему ПО ЗНАЧЕНИЮ — чтобы «наверное, это он под другим
именем» было измеряемым утверждением, а не догадкой по написанию имени.

Чего прибор НЕ утверждает
------------------------------------------------------------------------------
* **Что ход был НЕВЕРЕН.** Ставка умеет падать по-настоящему, и тогда ход был
  верным решением при неверном исходе. Прибор говорит, что ставка не
  продержалась, и называет цену хода.
* **Что упавшая выгода — вина аллокатора.** Кто именно пропустил ход (цель,
  демпфер, CIO), прибор не разбирает.
* **Что ход с отрицательной выгодой В ДЕНЬ ВХОДА относится к этому критерию.**
  Такой ход не мог быть вызван спайком — преимущества не было вовсе; это
  отдельная порода, и она вынесена отдельным счётчиком (предмет §49
  `Economics`). Породы не смешиваются.

Вердикт судит НАСТОЯЩЕЕ, история остаётся замером
------------------------------------------------------------------------------
Ход, случившийся в августе, случился навсегда: сторож, чей вердикт считает всю
историю, КРАСЕН НАВСЕГДА и учит себя игнорировать
(`.claude/rules/deployment.md`). Поэтому ``CRITICAL`` — только когда горизонт
окупаемости хода с упавшей ставкой ещё НЕ ЗАКРЫТ от `now`, то есть деньги
сейчас стоят на этой ставке; ``WARNING`` — таких ходов сегодня нет, но в
истории они есть; ``OK`` — ни одного за весь журнал.

Прибор ТОЛЬКО ЧИТАЕТ: журнал ходов, накопитель ставок, поверхность решения,
колонку порогов и часы. Ни `TriggerParams`, ни пороги RiskPolicy v1.0, ни
стоп-кран, ни живой трек, ни аллокатор он не трогает и ничего не чинит.
**LLM запрещён** (инвариант #3 — monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Журнал ходов — один адрес, тот же, что у соседней переписи (ADR-480).
JOURNAL_NAME = "trades.json"

#: Накопитель наблюдённых ставок по дням (пропуск НЕ интерполируется).
SERIES_NAME = "apy_series_daily.json"

#: Поверхность решения: что видел гейт в день своего вердикта.
SURFACE_NAME = "allocation_rationale_history.jsonl"

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "apy_persistence_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3

#: Классы исхода одного хода.
KLASS_PERSISTED = "persisted"
KLASS_FADED = "faded_below_owner_band"
KLASS_SIGN_FLIP = "sign_flipped"
KLASS_NEGATIVE_AT_ENTRY = "negative_at_entry"
KLASS_UNMEASURED = "unmeasured"


# ── разбор ───────────────────────────────────────────────────────────────────

def _parse_ts(raw: object) -> Optional[datetime]:
    """Отметка времени записи. Нечитаемая отметка — ``None``, не «сейчас»."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_day(raw: object) -> Optional[date]:
    """Дата ``YYYY-MM-DD`` из строки. Нечитаемая — ``None``."""
    if not isinstance(raw, str) or len(raw.strip()) < 10:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def _num(value: object) -> Optional[float]:
    """Число или ``None``. ``bool`` числом не считается (``True`` — не 1 %)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None


# ── пороги: колонка владельца, а не наши числа ───────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Планка выгоды, горизонт окупаемости и существенность ноги — из ADR-060 §3.

    Колонка недоступна ⇒ ``measured=False``. Подставить сюда умолчание значило
    бы завести ещё одну копию чисел владельца и ответить на свой вопрос вместо
    нужного (§22 ТЗ: «Не hardcode»).
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — планка выгоды, "
                               f"горизонт окупаемости и существенность ноги НЕ ИЗМЕРЕНЫ, "
                               f"подставлять свои нельзя (§22: «Не hardcode»)")}
    try:
        min_gain_pp = float(params.min_gain_pp)
        horizon_days = int(float(params.max_payback_days))
        min_leg_frac = float(params.min_leg_frac)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    if horizon_days <= 0:
        return {"measured": False,
                "reason": (f"горизонт окупаемости владельца не положителен "
                           f"({horizon_days}) — вперёд смотреть некуда, НЕ ИЗМЕРЕНО")}
    return {"measured": True, "min_gain_pp": min_gain_pp,
            "horizon_days": horizon_days, "min_leg_frac": min_leg_frac,
            "mode": mode, "version": version}


def load_gain_model() -> Dict[str, Any]:
    """Модель дневной выгоды — ЧУЖАЯ, не своя (§3 ТЗ: не строить вторую модель).

    Недоступность модели — третий исход, а не повод посчитать выгоду здесь:
    своя формула отвечала бы на свой вопрос, и расхождение с живым путём
    осталось бы невидимым.
    """
    try:
        from spa_core.paper_trading.shadow_trigger_eval import _day_gain_usd
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"модель дневной выгоды `shadow_trigger_eval._day_gain_usd` "
                           f"недоступна ({type(exc).__name__}: {exc}) — считать выгоду "
                           f"своей формулой запрещено, НЕ ИЗМЕРЕНО")}
    return {"measured": True, "day_gain_usd": _day_gain_usd}


# ── журнал ходов ─────────────────────────────────────────────────────────────

def read_journal(data_dir: Path) -> Dict[str, Any]:
    """Журнал ходов с диска. Отсутствие/нечитаемость — третий исход."""
    path = Path(data_dir) / JOURNAL_NAME
    if not path.exists():
        return {"measured": False,
                "reason": f"журнал ходов не найден: {path} — мерить нечего, и это "
                          f"НЕ «ставки держались»"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"журнал ходов нечитаем ({path}): {type(exc).__name__}: {exc}"}
    rows = doc if isinstance(doc, list) else (
        doc.get("trades") if isinstance(doc, dict) else None)
    if not isinstance(rows, list):
        return {"measured": False,
                "reason": f"журнал ходов не список записей: {path} "
                          f"(тип {type(doc).__name__})"}
    moves: List[Dict[str, Any]] = []
    undated = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_ts(row.get("ts") or row.get("timestamp"))
        if ts is None:
            undated += 1
            continue
        moves.append({
            "trade_id": str(row.get("trade_id") or f"#{len(moves) + 1}"),
            "ts": ts,
            "from": row.get("from_allocation") if isinstance(
                row.get("from_allocation"), dict) else {},
            "to": row.get("to_allocation") if isinstance(
                row.get("to_allocation"), dict) else {},
            "capital": _num(row.get("capital")),
            "delta_abs": _num(row.get("delta_abs")),
        })
    moves.sort(key=lambda m: m["ts"])
    if not moves:
        return {"measured": False,
                "reason": (f"в журнале {path} нет ни одной записи с читаемой отметкой "
                           f"времени (записей {len(rows)}, без отметки {undated}) — "
                           f"порядок ходов НЕ ИЗМЕРЕН")}
    return {"measured": True, "moves": moves, "undated": undated,
            "path": str(path), "rows": len(rows)}


# ── накопитель ставок ────────────────────────────────────────────────────────

def read_series(data_dir: Path) -> Dict[str, Any]:
    """Наблюдённые ставки по дням: ``{дата: {ключ: пп}}``.

    Пропуски НЕ достраиваются: день, которого в накопителе нет, остаётся
    отсутствующим и уходит в «не оценено», а не в «ставка та же».
    """
    path = Path(data_dir) / SERIES_NAME
    if not path.exists():
        return {"measured": False,
                "reason": (f"накопитель наблюдённых ставок не найден: {path} — "
                           f"вопрос про ДНИ без производителя дней НЕ ИЗМЕРИМ")}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"накопитель ставок нечитаем ({path}): "
                          f"{type(exc).__name__}: {exc}"}
    series = doc.get("series") if isinstance(doc, dict) else None
    if not isinstance(series, dict) or not series:
        return {"measured": False,
                "reason": (f"у накопителя {path} нет раздела `series` со ставками "
                           f"(тип {type(doc).__name__}) — НЕ ИЗМЕРЕНО")}
    by_day: Dict[date, Dict[str, float]] = {}
    per_key: Dict[str, Dict[date, float]] = {}
    for key, rows in series.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not (isinstance(row, (list, tuple)) and len(row) >= 2):
                continue
            day = _parse_day(row[0])
            value = _num(row[1])
            if day is None or value is None:
                continue
            by_day.setdefault(day, {})[str(key)] = value
            per_key.setdefault(str(key), {})[day] = value
    if not by_day:
        return {"measured": False,
                "reason": (f"в накопителе {path} нет ни одной читаемой пары "
                           f"«дата, ставка» — НЕ ИЗМЕРЕНО")}
    days = sorted(by_day)
    return {"measured": True, "by_day": by_day, "per_key": per_key,
            "keys": sorted(per_key), "first_day": days[0], "last_day": days[-1],
            "days": len(days), "path": str(path)}


# ── поверхность решения: что МОГ видеть гейт ─────────────────────────────────

def read_surface(data_dir: Path) -> Dict[str, Any]:
    """Записи вердиктов: ставки дня, гейты и число РАЗНЫХ дней наблюдения.

    Прибор читает её не для оценки ходов, а для ОДНОГО утверждения: сколько
    дней наблюдения видит одно решение. Отсутствие поверхности гасит только это
    утверждение, а не весь замер, — поэтому здесь ``measured`` отдельный.
    """
    path = Path(data_dir) / SURFACE_NAME
    if not path.exists():
        return {"measured": False,
                "reason": f"поверхность решения не найдена: {path} — сколько дней "
                          f"наблюдения видит гейт, НЕ ИЗМЕРЕНО"}
    records: List[Dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
    except OSError as exc:
        return {"measured": False,
                "reason": f"поверхность решения нечитаема ({path}): "
                          f"{type(exc).__name__}: {exc}"}
    if not records:
        return {"measured": False,
                "reason": f"в поверхности решения {path} нет ни одной читаемой записи"}

    gate_keys: set = set()
    distinct_days: List[int] = []
    without_as_of = 0
    rates_by_day: Dict[date, Dict[str, float]] = {}
    for rec in records:
        gates = rec.get("gates")
        if isinstance(gates, dict):
            gate_keys |= {str(k) for k in gates}
        as_of = rec.get("apy_as_of")
        if isinstance(as_of, dict) and as_of:
            days = {str(v)[:10] for v in as_of.values() if isinstance(v, str)}
            distinct_days.append(len(days))
        else:
            without_as_of += 1
        day = _parse_day(rec.get("cycle_date"))
        rates = rec.get("apy_evidenced_pct")
        if day is not None and isinstance(rates, dict):
            clean = {str(k): _num(v) for k, v in rates.items()}
            rates_by_day[day] = {k: v for k, v in clean.items() if v is not None}
    return {"measured": True, "path": str(path), "records": len(records),
            "gate_keys": sorted(gate_keys),
            "records_with_as_of": len(distinct_days),
            "records_without_as_of": without_as_of,
            "max_distinct_observation_days": max(distinct_days) if distinct_days else None,
            "rates_by_day": rates_by_day}


def gate_surface_claim(surface: Dict[str, Any]) -> Dict[str, Any]:
    """Может ли гейт вообще спросить «а сколько преимущество держится?».

    Утверждение ИЗМЕРЯЕТСЯ, а не объявляется: если ни одна запись вердикта не
    несёт больше одного дня наблюдения, то сравнить день с днём внутри решения
    нечем по построению — при любом значении любого порога.
    """
    if not surface.get("measured"):
        return {"measured": False, "reason": surface.get("reason")}
    peak = surface.get("max_distinct_observation_days")
    return {
        "measured": True,
        "records": surface["records"],
        "records_with_as_of": surface["records_with_as_of"],
        "records_without_as_of": surface["records_without_as_of"],
        "max_distinct_observation_days": peak,
        "gate_keys": surface["gate_keys"],
        # Ни один день истории ставки не входит в решение, если запись несёт
        # максимум один день наблюдения. Ноль дней (поля нет вовсе) — тем более.
        "persistence_representable_in_decision": bool(peak is not None and peak > 1),
    }


# ── ноги хода ────────────────────────────────────────────────────────────────

def move_legs(move: Dict[str, Any], min_usd: float) -> Dict[str, float]:
    """Существенные ноги хода: ``{ключ: Δ$}``. Пыль ниже планки владельца — вон."""
    before = move.get("from") or {}
    after = move.get("to") or {}
    legs: Dict[str, float] = {}
    for key in set(before) | set(after):
        a = _num(after.get(key)) or 0.0
        b = _num(before.get(key)) or 0.0
        delta = a - b
        if abs(delta) >= min_usd:
            legs[str(key)] = delta
    return legs


def _pp_of_capital(gain_usd: float, capital: float) -> float:
    """Дневная выгода в $ → годовая ставка в пп от капитала (форма владельца)."""
    return gain_usd * 365.0 / capital * 100.0


def judge_move(move: Dict[str, Any], legs: Dict[str, float], capital: float,
               by_day: Dict[date, Dict[str, float]], policy: Dict[str, Any],
               day_gain_usd: Any, first_day: Optional[date]) -> Dict[str, Any]:
    """Один ход: держалась ли ставка, ради которой он состоялся."""
    entry_day = move["ts"].date()
    out: Dict[str, Any] = {
        "trade_id": move["trade_id"],
        "ts": move["ts"].isoformat(),
        "entry_day": entry_day.isoformat(),
        "legs": {k: round(v, 2) for k, v in sorted(legs.items())},
        "turnover_usd": round(sum(abs(v) for v in legs.values()) / 2.0, 2),
    }
    if not legs:
        out.update({"klass": KLASS_UNMEASURED,
                    "reason": (f"у хода нет ни одной ноги существеннее "
                               f"${policy['min_leg_frac'] * capital:,.2f} "
                               f"(планка владельца min_leg_frac) — мерить нечего")})
        return out
    if first_day is not None and entry_day < first_day:
        out.update({"klass": KLASS_UNMEASURED,
                    "reason": (f"ход старше накопителя ставок: вход {entry_day}, "
                               f"первый наблюдённый день {first_day} — ставка дня "
                               f"входа НЕ НАБЛЮДАЛАСЬ, и это не «держалась»")})
        return out
    entry_rates = by_day.get(entry_day)
    if entry_rates is None:
        out.update({"klass": KLASS_UNMEASURED,
                    "reason": (f"в накопителе нет дня входа {entry_day} — фид в этот "
                               f"день молчал; пропуск НЕ достраивается")})
        return out
    entry_gain, missing = day_gain_usd(legs, entry_rates)
    if entry_gain is None:
        out.update({"klass": KLASS_UNMEASURED,
                    "missing_protocols": sorted(missing),
                    "reason": (f"в день входа {entry_day} у накопителя нет ставки для "
                               f"{sorted(missing)} — день не оценивается ЦЕЛИКОМ "
                               f"(fail-CLOSED: частичная оценка сдвинула бы ответ в "
                               f"сторону ноги, у которой данные оказались)")})
        return out

    forward: List[Tuple[date, float]] = []
    unchecked: List[Dict[str, Any]] = []
    for step in range(1, policy["horizon_days"] + 1):
        day = entry_day + timedelta(days=step)
        rates = by_day.get(day)
        if rates is None:
            unchecked.append({"day": day.isoformat(), "why": "дня нет в накопителе"})
            continue
        gain, miss = day_gain_usd(legs, rates)
        if gain is None:
            unchecked.append({"day": day.isoformat(),
                              "why": f"нет ставки для {sorted(miss)}"})
            continue
        forward.append((day, gain))
    out.update({"forward_days_checked": len(forward),
                "forward_days_unchecked": len(unchecked),
                "horizon_days": policy["horizon_days"]})
    if not forward:
        out.update({"klass": KLASS_UNMEASURED,
                    "entry_gain_pp": round(_pp_of_capital(entry_gain, capital), 4),
                    "unchecked": unchecked[:5],
                    "reason": (f"внутри горизонта {policy['horizon_days']} дн. ни один "
                               f"день не оценён ({len(unchecked)} не оценено) — исход "
                               f"ставки НЕ ИЗМЕРЕН")})
        return out

    entry_pp = _pp_of_capital(entry_gain, capital)
    realized_pp = _pp_of_capital(sum(g for _, g in forward) / len(forward), capital)
    worst_day, worst_gain = min(forward, key=lambda pair: pair[1])
    band = policy["min_gain_pp"]
    # ЧЬЯ ставка поехала: вклад каждой ноги в падение преимущества, в пп от
    # капитала. Считается тем же произведением «Δ$ × ставка», что и выгода, —
    # поэтому сумма вкладов равна падению целиком, и назвать виновную ногу
    # можно замером, а не предположением («спайк в цели» и «восстановление
    # источника» для владельца один и тот же вред, но лечатся они по-разному).
    attribution: List[Dict[str, Any]] = []
    for key, delta in sorted(legs.items()):
        entry_rate = entry_rates[key]
        rates_seen = [by_day[day][key] for day, _ in forward if key in by_day[day]]
        if not rates_seen:
            continue
        mean_rate = sum(rates_seen) / len(rates_seen)
        attribution.append({
            "protocol": key,
            "delta_usd": round(delta, 2),
            "rate_at_entry_pp": round(entry_rate, 4),
            "mean_rate_over_horizon_pp": round(mean_rate, 4),
            "contribution_to_decay_pp": round(
                _pp_of_capital(delta * (entry_rate - mean_rate) / 100.0 / 365.0,
                               capital), 4),
        })
    attribution.sort(key=lambda a: -abs(a["contribution_to_decay_pp"]))
    out.update({
        "entry_gain_pp": round(entry_pp, 4),
        "realized_gain_pp": round(realized_pp, 4),
        "decay_pp": round(entry_pp - realized_pp, 4),
        "owner_band_pp": band,
        "worst_forward_day": worst_day.isoformat(),
        "worst_forward_gain_pp": round(_pp_of_capital(worst_gain, capital), 4),
        "unchecked": unchecked[:5],
        "decay_attribution": attribution,
    })
    if entry_pp < 0:
        # Спайк тут не при чём: преимущества не было вовсе в день входа.
        out["klass"] = KLASS_NEGATIVE_AT_ENTRY
    elif entry_pp >= band and realized_pp < band:
        out["klass"] = KLASS_FADED
    elif realized_pp < 0:
        out["klass"] = KLASS_SIGN_FLIP
    else:
        out["klass"] = KLASS_PERSISTED
    return out


# ── ключи книги, которых у накопителя нет вовсе ──────────────────────────────

def absent_book_keys(moves: List[Dict[str, Any]], series: Dict[str, Any],
                     surface: Dict[str, Any], min_usd: float) -> List[Dict[str, Any]]:
    """Ключи, которые книга двигала, а накопитель не наблюдал ни одного дня.

    Про каждый говорится, что о нём знает поверхность решения, и какой ключ
    накопителя ближе всего к нему ПО ЗНАЧЕНИЮ на общих днях. Близость по
    значению — измеряемое утверждение; похожесть написания имени им не является
    и поэтому здесь не считается вовсе.
    """
    moved: Dict[str, float] = {}
    for move in moves:
        for key, delta in move_legs(move, min_usd).items():
            moved[key] = moved.get(key, 0.0) + abs(delta)
    # `or`-подстановки здесь нет намеренно: пустая поверхность и НЕПРОЧИТАННАЯ
    # поверхность — разные исходы, и сворачивать их в «ключа не знал никто»
    # значило бы выдать неизмеренное за измеренный ноль (инвариант #17).
    known = set(series["keys"])
    surface_ok = bool(surface.get("measured"))
    rates_by_day: Dict[date, Dict[str, float]] = (
        surface["rates_by_day"] if surface_ok else {})

    out: List[Dict[str, Any]] = []
    for key in sorted(set(moved) - known):
        seen = {day: rates[key] for day, rates in sorted(rates_by_day.items())
                if key in rates}
        nearest: Optional[Dict[str, Any]] = None
        for candidate, values in (series.get("per_key") or {}).items():
            shared = [day for day in seen if day in values]
            if len(shared) < 2:
                continue
            gap = sum(abs(values[day] - seen[day]) for day in shared) / len(shared)
            if nearest is None or gap < nearest["mean_gap_pp"]:
                nearest = {"series_key": candidate, "shared_days": len(shared),
                           "mean_gap_pp": round(gap, 4)}
        item = {
            "book_key": key,
            "moved_usd_total": round(moved[key], 2),
            # Ноль дней говорится только тогда, когда поверхность ПРОЧИТАНА;
            # непрочитанная даёт `None` — «не измерено», а не «не знал никто».
            "days_on_decision_surface": len(seen) if surface_ok else None,
            "decision_surface_read": surface_ok,
            "decision_surface_reason": None if surface_ok else surface.get("reason"),
            "last_seen_day": max(seen).isoformat() if seen else None,
            "last_seen_rate_pp": seen[max(seen)] if seen else None,
            "nearest_series_key_by_value": nearest,
            # Вердикта «это тот же пул под другим именем» здесь НЕТ намеренно:
            # два числа приходят от ДВУХ РАЗНЫХ производителей (поверхность
            # решения и накопитель), снятых в разные минуты, поэтому точного
            # равенства ждать не от чего, а порога «достаточно близко» владелец
            # не назначал — назначить его самому значило бы завести своё число
            # там, где прибор обязан их только читать (§22). Прибор НАЗЫВАЕТ
            # расхождение; тождество имён — предмет реестра пулов (ADR-350,
            # `pool_identity_collision`).
        }
        out.append(item)
    return out


# ── замер целиком ────────────────────────────────────────────────────────────

def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None) -> Dict[str, Any]:
    """Перепись удержания ставок. Три исхода различимы, третий не сворачивается.

    ``now`` инъектируется: вердикт судит о ВОЗРАСТЕ хода, и настенные часы
    сделали бы сцену смертной от календаря (`.claude/rules/deployment.md`).
    """
    now = now or datetime.now(timezone.utc)

    policy = load_policy(params)
    if not policy["measured"]:
        return _unmeasured(policy["reason"], now)
    model = load_gain_model()
    if not model["measured"]:
        return _unmeasured(model["reason"], now)
    journal = read_journal(data_dir)
    if not journal["measured"]:
        return _unmeasured(journal["reason"], now)
    series = read_series(data_dir)
    if not series["measured"]:
        return _unmeasured(series["reason"], now)
    surface = read_surface(data_dir)

    moves = journal["moves"]
    # Капитал берётся из самой записи хода; записи без него мерятся по
    # наибольшему наблюдённому состоянию книги — своего числа здесь нет.
    book_scale = max([sum(abs(_num(v) or 0.0) for v in (m.get("to") or {}).values())
                      for m in moves]
                     + [sum(abs(_num(v) or 0.0) for v in (m.get("from") or {}).values())
                        for m in moves] or [0.0])
    if book_scale <= 0:
        return _unmeasured(
            f"в журнале {journal['path']} нет ни одного состояния книги с суммой "
            f"больше нуля — масштаб книги НЕ ИЗМЕРЕН, существенность ноги "
            f"(доля капитала) не выражается", now)

    judged: List[Dict[str, Any]] = []
    for move in moves:
        capital = move.get("capital") or book_scale
        min_usd = policy["min_leg_frac"] * capital
        legs = move_legs(move, min_usd)
        item = judge_move(move, legs, capital, series["by_day"], policy,
                          model["day_gain_usd"], series["first_day"])
        item["capital_usd"] = round(capital, 2)
        # Возраст хода: горизонт окупаемости ещё не закрыт ⇒ деньги стоят на
        # этой ставке СЕЙЧАС. Окно — то же число владельца, литералов нет.
        item["age_hours"] = round((now - move["ts"]).total_seconds() / 3600.0, 2)
        item["horizon_open_now"] = (
            now - move["ts"] <= timedelta(days=policy["horizon_days"]))
        judged.append(item)

    measured_moves = [m for m in judged if m["klass"] != KLASS_UNMEASURED]
    unmeasured_moves = [m for m in judged if m["klass"] == KLASS_UNMEASURED]
    faded = [m for m in judged if m["klass"] == KLASS_FADED]
    flipped = [m for m in judged if m["klass"] == KLASS_SIGN_FLIP]
    negative = [m for m in judged if m["klass"] == KLASS_NEGATIVE_AT_ENTRY]
    persisted = [m for m in judged if m["klass"] == KLASS_PERSISTED]
    harm = faded + flipped
    current_harm = [m for m in harm if m["horizon_open_now"]]

    # Перечень ненаблюдаемых ключей и утверждение о поверхности считаются ДО
    # проверки «есть ли оценённые ходы» намеренно. Замер приёмки: при сцене, где
    # КАЖДЫЙ ход неоценим из-за ненаблюдаемой ноги, ранний выход уносил с собой
    # именно то объяснение, ради которого замер и делается, — «ключа нет у
    # накопителя» исчезало ровно там, где оно и есть причина третьего исхода.
    absent = absent_book_keys(moves, series, surface,
                             policy["min_leg_frac"] * book_scale)
    gate_claim = gate_surface_claim(surface)

    if not measured_moves:
        return _unmeasured(
            (f"ни один из {len(judged)} ходов журнала не оценён: "
             + "; ".join(f"{m['trade_id']} — {m['reason']}"
                         for m in unmeasured_moves[:4])
             + (" …" if len(unmeasured_moves) > 4 else "")), now,
            extra={"moves": judged, "absent_from_series": absent,
                   "gate_surface": gate_claim,
                   "turnover_unmeasured_usd": round(
                       sum(m["turnover_usd"] for m in unmeasured_moves), 2)})

    if current_harm:
        status = STATUS_CRITICAL
    elif harm:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": ("§49 Persistence — «Transient APY spikes не вызывают "
                      "ненужные trades»"),
        "journal": {"path": journal["path"], "rows": journal["rows"],
                    "moves": len(moves), "undated": journal["undated"],
                    "first_ts": moves[0]["ts"].isoformat(),
                    "last_ts": moves[-1]["ts"].isoformat()},
        "series": {"path": series["path"], "keys": len(series["keys"]),
                   "days": series["days"],
                   "first_day": series["first_day"].isoformat(),
                   "last_day": series["last_day"].isoformat()},
        "policy": {k: policy[k] for k in
                   ("min_gain_pp", "horizon_days", "min_leg_frac", "mode", "version")},
        "book_scale_usd": round(book_scale, 2),
        "gate_surface": gate_claim,
        "absent_from_series": absent,
        "moves": judged,
        "counts": {
            "moves_total": len(judged),
            "moves_measured": len(measured_moves),
            "moves_unmeasured": len(unmeasured_moves),
            "faded_below_owner_band": len(faded),
            "sign_flipped": len(flipped),
            "negative_at_entry": len(negative),
            "persisted": len(persisted),
            "harm_total": len(harm),
            "harm_with_open_horizon": len(current_harm),
            "book_keys_absent_from_series": len(absent),
        },
        # Заголовочные числа ДУБЛИРУЮТСЯ наверх намеренно: мост и офис читают их
        # через `observed_number(doc, key)`, который смотрит верхний уровень.
        "moves_measured": len(measured_moves),
        "moves_unmeasured": len(unmeasured_moves),
        "faded_below_owner_band": len(faded),
        "harm_total": len(harm),
        "harm_with_open_horizon": len(current_harm),
        "turnover_harm_usd": round(sum(m["turnover_usd"] for m in harm), 2),
        "turnover_unmeasured_usd": round(
            sum(m["turnover_usd"] for m in unmeasured_moves), 2),
        "faded": faded,
        "flipped": flipped,
        "negative": negative,
        "unmeasured_moves": unmeasured_moves,
    }


def _unmeasured(reason: str, now: datetime,
                extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "measured": False, "status": STATUS_UNMEASURED, "reason": reason,
        "generated_at": now.isoformat(), "moves": [], "faded": [], "flipped": [],
        "negative": [], "unmeasured_moves": [], "absent_from_series": [],
        "counts": {"moves_total": 0, "moves_measured": 0, "moves_unmeasured": 0,
                   "faded_below_owner_band": 0, "sign_flipped": 0,
                   "negative_at_entry": 0, "persisted": 0, "harm_total": 0,
                   "harm_with_open_horizon": 0,
                   "book_keys_absent_from_series": 0}}
    if extra:
        doc.update(extra)
        doc["unmeasured_moves"] = [m for m in extra.get("moves", [])
                                   if m.get("klass") == KLASS_UNMEASURED]
        doc["counts"]["moves_total"] = len(extra.get("moves", []))
        doc["counts"]["moves_unmeasured"] = len(doc["unmeasured_moves"])
    return doc


# ── отчёт ────────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"удержание ставки (§49 Persistence): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    c = report["counts"]
    return (f"удержание ставки (§49 Persistence): {report['status']} · ходов "
            f"{c['moves_total']} (оценено {c['moves_measured']}, НЕ ИЗМЕРЕНО "
            f"{c['moves_unmeasured']} на ${report['turnover_unmeasured_usd']:,.0f}) · "
            f"преимущество НЕ УДЕРЖАЛОСЬ ниже планки владельца "
            f"{c['faded_below_owner_band']} · "
            f"знак перевернулся {c['sign_flipped']} · держалась {c['persisted']} · "
            f"отрицательна уже на входе {c['negative_at_entry']} (порода §49 Economics, "
            f"не эта) · суммарный ОБОРОТ ходов-находок ${report['turnover_harm_usd']:,.0f} "
            f"(это оборот, а НЕ убыток, и ноги одного круга сложены обе)")


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Строки для офиса — находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        # Перечень ненаблюдаемых ключей печатается и в третьем исходе: он и есть
        # ПРИЧИНА того, что мерить было нечем, и молчать о нём значило бы
        # оставить читателя с «не измерено» без двери.
        lines.extend(_absent_lines(report, limit))
        for item in report.get("unmeasured_moves", [])[:limit]:
            lines.append(f"[НЕ ИЗМЕРЕНО] {item['trade_id']} "
                         f"{item.get('entry_day')}: {item['reason']}")
        return lines
    pol = report["policy"]
    lines.append(
        f"[КОЛОНКА] планка выгоды {pol['min_gain_pp']} пп · горизонт окупаемости "
        f"{pol['horizon_days']} дн. · существенность ноги {pol['min_leg_frac']} — "
        f"ADR-060 §3, колонка `{pol['mode']}` {pol['version']}; своих чисел у прибора нет")
    gate = report.get("gate_surface") or {}
    if gate.get("measured"):
        peak = gate.get("max_distinct_observation_days")
        lines.append(
            f"[ПО ПОСТРОЕНИЮ] одно решение видит максимум "
            f"{'НЕ ИЗМЕРЕНО' if peak is None else peak} день(дня) наблюдения "
            f"(записей {gate['records']}, из них без отметок наблюдения "
            f"{gate['records_without_as_of']}) ⇒ гейт, требующий, чтобы преимущество "
            f"ПРОДЕРЖАЛОСЬ, из такой записи не выводится ни при каком пороге. "
            f"`min_hold_ok`/`cooldown_ok` меряют возраст НАШЕЙ позиции, а не историю "
            f"ставки; гейты в истории: {', '.join(gate['gate_keys'])}")
    else:
        lines.append(f"[ПО ПОСТРОЕНИЮ] НЕ ИЗМЕРЕНО — {gate.get('reason')}")
    if report["status"] == STATUS_WARNING:
        lines.append(
            f"[ВЕРДИКТ] ходов с упавшей ставкой, чей горизонт окупаемости ещё открыт от "
            f"now, НЕТ, но в истории их {report['counts']['harm_total']} — «сегодня "
            f"тихо» НЕ значит «такого не бывало»; последний ход журнала "
            f"{report['journal']['last_ts']}")
    if report["status"] == STATUS_CRITICAL:
        lines.append(
            f"[ВЕРДИКТ] {report['counts']['harm_with_open_horizon']} ход(ов) с "
            f"НЕудержавшимся преимуществом моложе горизонта окупаемости "
            f"{report['policy']['horizon_days']} дн. — по замыслу владельца их "
            f"стоимость ещё не отработана, то есть это решается сегодня, а не в "
            f"истории")
    for item in report.get("faded", [])[:limit]:
        lines.append(
            f"[ПРЕИМУЩЕСТВО НЕ УДЕРЖАЛОСЬ] {item['trade_id']} {item['entry_day']}: на входе "
            f"{item['entry_gain_pp']:+.4f} пп (планка владельца "
            f"{item['owner_band_pp']} пп ПРОЙДЕНА), за {item['forward_days_checked']} "
            f"наблюдённых дн. горизонта {item['realized_gain_pp']:+.4f} пп — падение "
            f"{item['decay_pp']:+.4f} пп; оборот ${item['turnover_usd']:,.0f}. Будь "
            f"ставки этих дней известны, планка САМОГО ВЛАДЕЛЬЦА ход бы запретила"
            + _attribution_tail(item))
    for item in report.get("flipped", [])[:limit]:
        lines.append(
            f"[ЗНАК ПЕРЕВЕРНУЛСЯ] {item['trade_id']} {item['entry_day']}: на входе "
            f"{item['entry_gain_pp']:+.4f} пп, за {item['forward_days_checked']} дн. "
            f"{item['realized_gain_pp']:+.4f} пп — ход стал терять; оборот "
            f"${item['turnover_usd']:,.0f} (планку владельца он на входе не проходил — "
            f"порода отдельная)" + _attribution_tail(item))
    lines.extend(_absent_lines(report, limit))
    for item in report.get("unmeasured_moves", [])[:limit]:
        lines.append(f"[НЕ ИЗМЕРЕНО] {item['trade_id']} {item['entry_day']} "
                     f"(оборот ${item['turnover_usd']:,.0f}): {item['reason']}")
    # Сколько строк СКРЫТО — считается по секциям, а не одним вычитанием:
    # разность «всего минус три предела» врёт, когда какая-то секция короче
    # предела, и читатель получает число, которого не видел ни один перечень.
    hidden = sum(max(0, len(report.get(section, [])) - limit)
                 for section in ("faded", "flipped", "absent_from_series",
                                 "unmeasured_moves"))
    if hidden > 0:
        lines.append(f"… ещё {hidden} строк(и) — полный перечень в артефакте")
    lines.append("ОПОРА: выгода дня считается ЧУЖОЙ моделью "
                 "(`shadow_trigger_eval._day_gain_usd`, fail-CLOSED по дню), ставки — "
                 "накопителем живых наблюдений, пороги — колонкой владельца ADR-060 §3")
    lines.append("ОПОРА: суммарный оборот ходов-находок — это ОБОРОТ, а не убыток: ноги "
                 "одного круга сложены обе, и убытка прибор не считает вовсе (для этого "
                 "нужна книга, а не ставки)")
    lines.append("НЕ ДОКЛАДЫВАЕТ: что ход был НЕВЕРЕН (ставка умеет падать "
                 "по-настоящему) · кто из гейтов его пропустил · ходы с отрицательной "
                 "выгодой на входе к этому критерию не относятся — породы не "
                 "смешиваются; RiskPolicy, стоп-кран, аллокатор и живой трек НЕ "
                 "трогаются, прибор только читает")
    return lines


def _surface_tail(item: Dict[str, Any]) -> str:
    """Что о ключе знает поверхность решения — с различением третьего исхода."""
    if not item.get("decision_surface_read"):
        return (f"Поверхность решения НЕ ПРОЧИТАНА "
                f"({item.get('decision_surface_reason')}), поэтому «его не знал никто» "
                f"здесь НЕ утверждается; ")
    days = item["days_on_decision_surface"]
    if not days:
        return ("Поверхность решения не знала его ни одного дня — то есть его ставки "
                "не знал НИ ОДИН производитель; ")
    return (f"Поверхность решения знала его {days} дн., последняя ставка "
            f"{item['last_seen_rate_pp']} пп ({item['last_seen_day']}); ")


def _absent_lines(report: Dict[str, Any], limit: int) -> List[str]:
    """Ключи книги, которых накопитель не наблюдал — ОДНА копия печати."""
    lines: List[str] = []
    for item in report.get("absent_from_series", [])[:limit]:
        near = item.get("nearest_series_key_by_value")
        near_txt = ("ближайшего по значению ключа нет (общих дней меньше двух)"
                    if not near else
                    f"ближайший ПО ЗНАЧЕНИЮ ключ накопителя `{near['series_key']}` "
                    f"расходится в среднем на {near['mean_gap_pp']} пп на "
                    f"{near['shared_days']} общих дн. — тождество имён прибор НЕ "
                    f"объявляет (числа от двух разных производителей, порога "
                    f"близости владелец не назначал; предмет реестра пулов)")
        lines.append(
            f"[КЛЮЧА НЕТ У НАКОПИТЕЛЯ] `{item['book_key']}`: книга двигала им "
            f"${item['moved_usd_total']:,.0f}, а наблюдённой ставки за все дни — ни "
            f"одной. "
            + _surface_tail(item) + near_txt)
    return lines


def _attribution_tail(item: Dict[str, Any]) -> str:
    """Чья ставка поехала — по замеру вкладов, а не по предположению."""
    rows = item.get("decay_attribution") or []
    if not rows:
        return ""
    top = rows[0]
    side = "цель" if top["delta_usd"] > 0 else "источник"
    return (f". Больше всех в падение внёс `{top['protocol']}` ({side}, "
            f"Δ${top['delta_usd']:,.0f}): {top['rate_at_entry_pp']} пп на входе → "
            f"{top['mean_rate_over_horizon_pp']} пп в среднем по горизонту, вклад "
            f"{top['contribution_to_decay_pp']:+.4f} пп")


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь): обратный порядок `atomic_save` отвергает
    # fail-CLOSED, и артефакт не появился бы ВОВСЕ при бодром `measured=True`
    # (настоящая поломка, найденная приёмкой цикла #701).
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
    # Ненулевой код — только на ход, чей горизонт окупаемости ещё открыт, то
    # есть на то, что решается сегодня. `WARNING` печатается всегда, но кодом не
    # нудит: постоянно ненулевой прибор учит пропускать свой вывод.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
