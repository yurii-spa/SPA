#!/usr/bin/env python3
"""Возвращалась ли книга в состояние, которое сама же покинула — и чего это стоило.

Критерий §49 `Anti-churn` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #701.

Дословно критерий звучит так: **«Система не прыгает между одинаковыми
opportunities»**, а §22 требует защиты от формы `A → B → A → B`. До этого
прибора критерий был ПРОЗОЙ: механизм назывался (гистерезис разворота в
`allocator/rebalance_economics.py`, ограничитель частоты в
`governance/churn_damper.py`), а ИСХОД — прыгала книга или нет — не мерил никто.
«Модуль есть, тесты зелёные» ≠ «работает» (`.claude/rules/acceptance.md`).

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь: **возврат состояния**. Состояние книги ПЕРЕД ходом `i` равно
состоянию ПОСЛЕ хода `j` (`i ≤ j`), при том что между ними книга это состояние
реально покидала. Такой возврат оплачен дважды и кончился там, где начался.

Почему это НЕ то же, что уже проверяется — и разница по ПОСТРОЕНИЮ
------------------------------------------------------------------------------
Существующих защит две, и ни одна не отвечает на вопрос §49:

| защита | что меряет | чего не видит |
|---|---|---|
| `churn_damper.decide` (ADR-168) | ЧАСТОТУ: часы с последнего хода, недельный бюджет оборота | понятия «разворот» у него нет вовсе |
| `rebalance_economics` L2 (ADR-060 §3) | знаки ног против `last_move_legs` | ход, разворачивающий не ПОСЛЕДНИЙ, а более ранний ход |

Вторая строка — главная. Гистерезис сравнивает ноги хода с ногами ХОДА
НЕПОСРЕДСТВЕННО ПРЕДШЕСТВУЮЩЕГО (`last_move_legs`). Поэтому возврат, между
началом и концом которого лежит ДВА и более хода, невидим для него не по
ошибке порога, а по построению: `A→B`, `B→C`, `C→A` — последний ход
разворачивает `A→B`, а сравнивается с `B→C` и разворотом не признаётся.
Книга при этом вернулась в `A`.

Поэтому прибор делит находки на две породы и НЕ смешивает их:

* ``visible_to_check`` — возврат за ДВА хода (`j == i+1`): гистерезис его
  видел, и ход всё равно состоялся. Это вопрос ПОРОГА, и порог — колонка
  владельца (ADR-060 §3);
* ``invisible_by_construction`` — возврат за ТРИ и более хода: гистерезису
  его нечем увидеть. Это вопрос ПРЕДМЕТА сравнения, а не величины порога.

Своих чисел прибор не имеет ни одного
------------------------------------------------------------------------------
Существенность ноги и окно разворота берутся из `TriggerParams.for_mode()` —
той же колонки ADR-060 §3, которой судит живой путь (`min_leg_frac`,
`reversal_window_days`). §22 приказа требует дословно: «Все значения должны быть
config/policy. Не hardcode». Четвёртой копии чисел здесь нет, и **`TriggerParams`
недоступен ⇒ третий исход**, а не подставленное умолчание: колонка,
подставленная прибором, отвечала бы на свой вопрос, а не на нужный.

Псевдонимы ключей ИЗМЕРЯЮТСЯ, а не выдумываются
------------------------------------------------------------------------------
Протокол может быть переименован (`fluid_usdc` → `fluid_fusdc`, ход T034,
класс, который независимо называет `scripts/book_second_record.py`).
Переименование видно на СТЫКЕ соседних записей: `to_allocation[i]` и
`from_allocation[i+1]` расходятся ключами при равных суммах один-к-одному.
Прибор берёт псевдонимы только оттуда — из журнала, — и всегда ГОВОРИТ, какие
взял. Список псевдонимов, вписанный в код руками, был бы третьим местом для
знания о книге; здесь он замер.

Побочно это чинит слепоту самого измерения: без псевдонима возврат T033→T034
не опознаётся вовсе (расхождение $40 000 из $95 000 — 42 %), то есть
переименование ключа МАСКИРУЕТ прыжок книги от любого прибора, который сверяет
состояния по ключам дословно.

Почему вердикт судит НАСТОЯЩЕЕ, а история остаётся замером
------------------------------------------------------------------------------
История не меняется: возврат, состоявшийся в июне, состоялся навсегда. Сторож,
чей вердикт считает всю историю, КРАСЕН НАВСЕГДА и позеленеть не может ни от
какой починки — а такой сторож учит себя игнорировать
(`.claude/rules/deployment.md`: краснеющего на верное состояние чинят, а не
терпят). Поэтому здесь разведены две разные вещи:

* **замер** — все возвраты за всю историю журнала, со ценой и породой каждого.
  Это факт, и он печатается всегда, чтобы «сегодня тихо» никогда не читалось
  как «такого не бывало»;
* **вердикт** — только возвраты, чей последний ход лежит внутри окна разворота
  от `now`. Окно — та же `reversal_window_days` владельца, а не наша граница, и
  дословной даты здесь нет ни одной (иначе сцена умерла бы от календаря).

Отсюда три вердикта, и средний существует именно для того, чтобы тишина не
выдавалась за отсутствие класса: ``CRITICAL`` — возврат внутри окна ЕСТЬ;
``WARNING`` — внутри окна возвратов нет, но в истории они есть; ``OK`` — книга
не возвращалась ни разу за весь журнал.

Слепота гистерезиса — утверждение о ПОСТРОЕНИИ, а не о сегодняшнем дне, и
поэтому живёт отдельным полем ``blind_spot_demonstrated``: она не гаснет от
того, что книга неделю стояла.

Чего прибор НЕ утверждает
------------------------------------------------------------------------------
* **Что возврат был НЕВЕРЕН.** Мир умеет разворачиваться по-настоящему: ставка
  выросла и упала, и тогда вернуться — правильное решение. Прибор говорит
  только, что возврат СОСТОЯЛСЯ, называет его цену и то, видел ли его
  гистерезис. Верность каждого решения он не пересчитывает.
* **Что оборот возвратов складывается.** Интервалы возвратов ВЛОЖЕНЫ друг в
  друга, и сумма по всем возвратам считала бы одни и те же ходы многократно.
  Поэтому итог считается по МАКСИМАЛЬНОМУ НЕПЕРЕСЕКАЮЩЕМУСЯ подмножеству, и
  это сказано в отчёте вслух.
* **Что причина возврата — в аллокаторе.** Цель строит аллокатор, решение
  двигать принимают демпфер и CIO; который из них пропустил ход, прибор не
  разбирает — для этого есть `data/allocation_rationale_history.jsonl`.

Прибор ТОЛЬКО ЧИТАЕТ: журнал ходов, пороги и часы. Ни `TriggerParams`, ни
пороги RiskPolicy v1.0, ни стоп-кран, ни живой трек, ни аллокатор он не трогает
и ничего не чинит. **LLM запрещён** (инвариант #3 — monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Имя журнала ходов. Один адрес, а не поиск по каталогу: журнал денег один.
JOURNAL_NAME = "trades.json"

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "book_oscillation_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код возврата третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3


# ── часы и разбор отметок ────────────────────────────────────────────────────

def _parse_ts(raw: object) -> Optional[datetime]:
    """Отметка времени записи. Нечитаемая отметка — ``None``, не «сейчас»."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(value: object) -> float:
    """Число или 0.0. ``bool`` числом не считается (``True`` — не $1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    f = float(value)
    return f if f == f and abs(f) != float("inf") else 0.0


# ── пороги: колонка владельца, а не наши числа ───────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Существенность ноги и окно разворота из ``TriggerParams.for_mode()``.

    Колонка недоступна ⇒ ``measured=False``. Подставить сюда умолчание значило
    бы завести четвёртую копию чисел ADR-060 §3 и ответить на свой вопрос
    вместо нужного (урок `pyflakes`: отсутствие инструмента — третий исход).
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — существенность и окно "
                               f"разворота НЕ ИЗМЕРЕНЫ, подставлять свои нельзя (§22: "
                               f"«Все значения должны быть config/policy. Не hardcode»)")}
    try:
        min_leg_frac = float(params.min_leg_frac)
        window_days = float(params.reversal_window_days)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    return {"measured": True, "min_leg_frac": min_leg_frac,
            "reversal_window_days": window_days, "mode": mode, "version": version}


# ── журнал ходов ────────────────────────────────────────────────────────────

def read_journal(data_dir: Path) -> Dict[str, Any]:
    """Журнал ходов с диска. Отсутствие/нечитаемость — третий исход."""
    path = Path(data_dir) / JOURNAL_NAME
    if not path.exists():
        return {"measured": False,
                "reason": f"журнал ходов не найден: {path} — мерить нечего, "
                          f"и это НЕ «книга не прыгала»"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"журнал ходов нечитаем ({path}): {type(exc).__name__}: {exc}"}
    rows = doc if isinstance(doc, list) else (
        doc.get("trades") if isinstance(doc, dict) else None)
    if not isinstance(rows, list):
        return {"measured": False,
                "reason": f"журнал ходов не список записей: {path} (тип {type(doc).__name__})"}

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
            "from": row.get("from_allocation") if isinstance(row.get("from_allocation"), dict) else {},
            "to": row.get("to_allocation") if isinstance(row.get("to_allocation"), dict) else {},
            "delta_abs": row.get("delta_abs"),
        })
    moves.sort(key=lambda m: m["ts"])
    if not moves:
        return {"measured": False,
                "reason": (f"в журнале {path} нет ни одной записи с читаемой отметкой "
                           f"времени (записей {len(rows)}, без отметки {undated}) — "
                           f"порядок ходов НЕ ИЗМЕРЕН")}
    return {"measured": True, "moves": moves, "undated": undated,
            "path": str(path), "rows": len(rows)}


# ── псевдонимы ключей: замер на стыках, не список в коде ─────────────────────

def derive_aliases(moves: List[Dict[str, Any]], min_usd: float) -> Dict[str, Any]:
    """Переименования протоколов, ИЗМЕРЕННЫЕ на стыках соседних записей.

    Стык — это `to_allocation[i]` против `from_allocation[i+1]`: между ними
    книга не двигалась, поэтому любое расхождение ключей при равных суммах
    один-к-одному есть переименование, а не ход.
    """
    aliases: Dict[str, str] = {}
    seams: List[Dict[str, Any]] = []
    for prev, nxt in zip(moves, moves[1:]):
        before = _material(prev["to"], min_usd)
        after = _material(nxt["from"], min_usd)
        gone = sorted(set(before) - set(after))
        fresh = sorted(set(after) - set(before))
        if not gone or not fresh or len(gone) != len(fresh):
            continue
        pairs: List[Tuple[str, str]] = []
        taken: set = set()
        for old in gone:
            for new in fresh:
                if new in taken:
                    continue
                if abs(before[old] - after[new]) <= max(min_usd, 0.01):
                    pairs.append((old, new))
                    taken.add(new)
                    break
        if len(pairs) != len(gone):
            continue
        for old, new in pairs:
            aliases[old] = new
        seams.append({"between": [prev["trade_id"], nxt["trade_id"]],
                      "pairs": [list(p) for p in pairs]})
    return {"aliases": aliases, "seams": seams}


def _material(allocation: object, min_usd: float) -> Dict[str, float]:
    """Позиции выше порога существенности. Ниже порога — не позиция."""
    if not isinstance(allocation, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in allocation.items():
        amount = _num(value)
        if amount > min_usd:
            out[str(key)] = round(amount, 2)
    return out


def canonical_state(allocation: object, aliases: Dict[str, str],
                    min_usd: float) -> Dict[str, float]:
    """Состояние книги с приведёнными ключами. Слитые ключи складываются."""
    merged: Dict[str, float] = {}
    for key, amount in _material(allocation, min_usd).items():
        canon = aliases.get(key, key)
        merged[canon] = merged.get(canon, 0.0) + amount
    return {k: round(v, 2) for k, v in merged.items()}


def state_distance(left: Dict[str, float], right: Dict[str, float]) -> float:
    """Расстояние между состояниями в долларах — сумма модулей расхождений."""
    return round(sum(abs(left.get(k, 0.0) - right.get(k, 0.0))
                     for k in set(left) | set(right)), 2)


def move_turnover(move: Dict[str, Any], aliases: Dict[str, str],
                  min_usd: float) -> float:
    """Односторонний оборот хода — ОДНО определение, взятое у демпфера.

    `delta_abs` из записи предпочитается, когда он есть: его пишет живой путь.
    Нет — считаем той же функцией, что и демпфер (`one_sided_turnover`), а не
    `diff_usd/2`: половина занижает одностороннее размещение вдвое, и этот
    класс уже назван в `cycle_runner` (замер 30.08).
    """
    recorded = move.get("delta_abs")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
        return round(float(recorded), 2)
    from spa_core.governance.churn_damper import one_sided_turnover
    return round(one_sided_turnover(
        canonical_state(move["from"], aliases, min_usd),
        canonical_state(move["to"], aliases, min_usd)), 2)


# ── сама перепись ───────────────────────────────────────────────────────────

def find_returns(moves: List[Dict[str, Any]], aliases: Dict[str, str],
                 min_usd: float, tol_usd: float) -> List[Dict[str, Any]]:
    """Все возвраты состояния: книга перед ходом `i` = книга после хода `j`.

    Требование «книга это состояние реально покидала» проверяется, а не
    предполагается: без него пара холостых ходов считалась бы прыжком.
    """
    states_before = [canonical_state(m["from"], aliases, min_usd) for m in moves]
    states_after = [canonical_state(m["to"], aliases, min_usd) for m in moves]
    found: List[Dict[str, Any]] = []
    for i, start in enumerate(states_before):
        if not start:
            continue           # пустая книга — уходить было неоткуда
        # «Насколько книга отходила от `start`» — БЕГУЩИЙ максимум по j, а не
        # пересчёт внутренним циклом: пересчёт делал бы перепись кубической от
        # длины журнала, а журнал растёт на ход в сутки. Значение то же.
        left_by = 0.0
        for j in range(i, len(moves)):
            if j > i:
                left_by = max(left_by, state_distance(start, states_after[j - 1]))
            distance = state_distance(start, states_after[j])
            if distance > tol_usd:
                continue
            # Книга обязана была ПОКИНУТЬ состояние хотя бы один раз внутри.
            if left_by <= tol_usd:
                continue
            spanned = moves[i:j + 1]
            found.append({
                "from_trade": moves[i]["trade_id"],
                "to_trade": moves[j]["trade_id"],
                "first_index": i,
                "last_index": j,
                "moves_spanned": j - i + 1,
                "span_hours": round(
                    (moves[j]["ts"] - moves[i]["ts"]).total_seconds() / 3600.0, 2),
                "residual_usd": distance,
                "left_state_by_usd": round(left_by, 2),
                "turnover_usd": round(sum(
                    move_turnover(m, aliases, min_usd) for m in spanned), 2),
                "book_usd": round(sum(start.values()), 2),
                # ДВЕ породы, и они не смешиваются: за два хода гистерезис
                # сравнивает ноги именно с ходом `i`, за три и более — с чужим.
                "visible_to_reversal_check": (j - i + 1) == 2,
            })
    return found


def _maximal_disjoint(returns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Непересекающееся подмножество возвратов — чтобы оборот не считался дважды.

    Жадно по самому раннему концу: классический выбор интервалов, и он
    даёт максимальное по числу непересекающихся возвратов.
    """
    chosen: List[Dict[str, Any]] = []
    last_end = -1
    for item in sorted(returns, key=lambda r: (r["last_index"], r["first_index"])):
        if item["first_index"] > last_end:
            chosen.append(item)
            last_end = item["last_index"]
    return chosen


def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None) -> Dict[str, Any]:
    """Перепись прыжков книги. Три исхода различимы, третий не сворачивается.

    ``now`` инъектируется: прибор судит о ВОЗРАСТЕ находок, и настенные часы
    сделали бы сцену смертной от календаря (`.claude/rules/deployment.md`).
    """
    now = now or datetime.now(timezone.utc)

    policy = load_policy(params)
    if not policy["measured"]:
        return _unmeasured(policy["reason"], now)

    journal = read_journal(data_dir)
    if not journal["measured"]:
        return _unmeasured(journal["reason"], now)

    moves = journal["moves"]
    # Существенность выражена ДОЛЕЙ капитала у владельца, а капитал книги —
    # это сама книга: берём наибольшее наблюдённое состояние как её масштаб.
    book_scale = max(
        [sum(_material(m["from"], 0.0).values()) for m in moves]
        + [sum(_material(m["to"], 0.0).values()) for m in moves] or [0.0])
    min_usd = policy["min_leg_frac"] * book_scale
    tol_usd = min_usd

    alias_report = derive_aliases(moves, min_usd)
    aliases = alias_report["aliases"]

    returns = find_returns(moves, aliases, min_usd, tol_usd)
    window = timedelta(days=policy["reversal_window_days"])
    for item in returns:
        item["within_reversal_window"] = (
            timedelta(hours=item["span_hours"]) <= window)
        item["age_hours"] = round(
            (now - moves[item["last_index"]]["ts"]).total_seconds() / 3600.0, 2)

    # Возврат «в окне разворота» — про РАССТОЯНИЕ между его концами: именно это
    # расстояние видит гистерезис (`days_since_last_move`). Возврат шире окна
    # политика разворотом не считает, и претензии к нему у прибора нет.
    in_window = [r for r in returns if r["within_reversal_window"]]
    invisible = [r for r in in_window if not r["visible_to_reversal_check"]]
    visible = [r for r in in_window if r["visible_to_reversal_check"]]
    disjoint = _maximal_disjoint(in_window)

    # ВЕРДИКТ судит настоящее: возвраты, чей последний ход ещё внутри окна от
    # `now`. История при этом никуда не девается — она в `returns` и в счётчиках.
    window_hours = policy["reversal_window_days"] * 24.0
    recent = [r for r in in_window if r["age_hours"] <= window_hours]

    if recent:
        status = STATUS_CRITICAL
    elif in_window:
        status = STATUS_WARNING
    else:
        status = STATUS_OK
    # Слепота — утверждение о ПОСТРОЕНИИ гистерезиса, и она не гаснет от тишины.
    blind_spot = bool(invisible)

    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": "§49 Anti-churn — «Система не прыгает между одинаковыми opportunities»",
        "journal": {"path": journal["path"], "rows": journal["rows"],
                    "moves": len(moves), "undated": journal["undated"],
                    "first_ts": moves[0]["ts"].isoformat(),
                    "last_ts": moves[-1]["ts"].isoformat()},
        "policy": {k: policy[k] for k in
                   ("min_leg_frac", "reversal_window_days", "mode", "version")},
        "materiality_usd": round(min_usd, 2),
        "book_scale_usd": round(book_scale, 2),
        "aliases": aliases,
        "alias_seams": alias_report["seams"],
        "returns": returns,
        "counts": {
            "returns_total": len(returns),
            "returns_within_window": len(in_window),
            "invisible_by_construction": len(invisible),
            "visible_to_check": len(visible),
            "disjoint_within_window": len(disjoint),
            "recent_within_window_from_now": len(recent),
        },
        "blind_spot_demonstrated": blind_spot,
        "recent": recent,
        # Заголовочные числа ДУБЛИРУЮТСЯ наверх намеренно: мост и офис читают
        # их через `observed_number(doc, key)`, который смотрит верхний уровень.
        # Это не второе место для числа — оба вычислены здесь же, одной строкой.
        "returns_total": len(returns),
        "invisible_by_construction": len(invisible),
        "recent_within_window_from_now": len(recent),
        "turnover_usd_disjoint": round(
            sum(r["turnover_usd"] for r in disjoint), 2),
        "invisible": invisible,
        "visible": visible,
    }


def _unmeasured(reason: str, now: datetime) -> Dict[str, Any]:
    return {"measured": False, "status": STATUS_UNMEASURED, "reason": reason,
            "generated_at": now.isoformat(), "returns": [],
            "blind_spot_demonstrated": False, "recent": [],
            "counts": {"returns_total": 0, "returns_within_window": 0,
                       "invisible_by_construction": 0, "visible_to_check": 0,
                       "disjoint_within_window": 0,
                       "recent_within_window_from_now": 0}}


# ── отчёт ───────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"прыжки книги (§49 Anti-churn): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    c = report["counts"]
    return (f"прыжки книги (§49 Anti-churn): {report['status']} · ходов "
            f"{report['journal']['moves']} · возвратов состояния "
            f"{c['returns_total']} (в окне разворота {c['returns_within_window']}, "
            f"СВЕЖИХ от now {c['recent_within_window_from_now']}) · НЕВИДИМЫ "
            f"гистерезису по построению {c['invisible_by_construction']} · видимы ему "
            f"{c['visible_to_check']} · оборот непересекающихся "
            f"${report['turnover_usd_disjoint']:,.0f}")


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Строки для офиса — находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        return lines
    if report["status"] == STATUS_WARNING:
        lines.append(
            f"[ВЕРДИКТ] внутри окна разворота от now свежих возвратов НЕТ, но в истории "
            f"их {report['counts']['returns_within_window']} — «сегодня тихо» НЕ значит "
            f"«такого не бывало»; последний ход журнала "
            f"{report['journal']['last_ts']}")
    if report.get("blind_spot_demonstrated"):
        lines.append(
            f"[СЛЕПОТА ПО ПОСТРОЕНИЮ] {report['counts']['invisible_by_construction']} "
            f"возврат(ов) журнала гистерезису нечем увидеть: он сверяет ноги с "
            f"`last_move_legs` — ходом НЕПОСРЕДСТВЕННО предыдущим, — а эти возвраты "
            f"разворачивают ход, лежащий дальше. Это утверждение о ПРЕДМЕТЕ сравнения, "
            f"и оно не гаснет от того, что книга неделю стояла")
    if report.get("aliases"):
        pairs = ", ".join(f"{a}→{b}" for a, b in sorted(report["aliases"].items()))
        lines.append(f"[ПСЕВДОНИМЫ] измерены на стыках записей: {pairs} — без них "
                     f"переименование ключа МАСКИРУЕТ возврат от любой дословной сверки")
    for item in report.get("invisible", [])[:limit]:
        lines.append(
            f"[НЕВИДИМ ГИСТЕРЕЗИСУ] {item['from_trade']}..{item['to_trade']}: книга "
            f"вернулась в прежнее состояние за {item['moves_spanned']} ход(ов) за "
            f"{item['span_hours']:.1f} ч, остаток ${item['residual_usd']:,.2f}, "
            f"оборот ${item['turnover_usd']:,.0f} при книге ${item['book_usd']:,.0f} — "
            f"сравнение идёт с ходом {item['last_index'] - item['first_index']} "
            f"назад, а не с тем, который разворачивается")
    for item in report.get("visible", [])[:limit]:
        lines.append(
            f"[ВИДЕН ГИСТЕРЕЗИСУ] {item['from_trade']}..{item['to_trade']}: возврат за "
            f"два хода за {item['span_hours']:.1f} ч, оборот ${item['turnover_usd']:,.0f}, "
            f"остаток ${item['residual_usd']:,.2f} — порог разворота ход не остановил "
            f"(вопрос ВЕЛИЧИНЫ порога, колонка ADR-060 §3, а не предмета сравнения)")
    extra = len(report.get("invisible", [])) + len(report.get("visible", [])) - 2 * limit
    if extra > 0:
        lines.append(f"… ещё {extra} возврат(ов) — полный перечень в артефакте")
    lines.append("ОПОРА: интервалы возвратов ВЛОЖЕНЫ, поэтому итог оборота считан по "
                 "максимальному непересекающемуся подмножеству "
                 f"({report['counts']['disjoint_within_window']} возвратов) — сумма по "
                 "всем считала бы одни ходы многократно")
    lines.append("НЕ ДОКЛАДЫВАЕТ: верность каждого возврата (мир умеет разворачиваться "
                 "по-настоящему) · кто из гейтов пропустил ход · пороги RiskPolicy v1.0, "
                 "стоп-кран, аллокатор и живой трек НЕ трогаются — прибор только читает")
    return lines


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь). Замер #701: обратный порядок
    # `atomic_save` отвергает fail-CLOSED, и артефакт не появлялся ВОВСЕ, а
    # ступень при этом докладывала `measured=True` — то есть отказ записи был
    # неотличим от успеха у всех, кто смотрит на её вывод, а не на диск.
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ступень моста находок (`findings_bridge`): померить и оставить артефакт.

    Форма ответа — та же, что у соседних переписей: ``{"measured", "doc"}``.
    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис увидит
    отсутствие файла и не сможет отличить его от «ступень не запускалась».
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
    # Ненулевой код — только на СВЕЖИЙ возврат, то есть на то, что решается
    # сегодня. `WARNING` (история есть, настоящее тихо) и слепота гистерезиса
    # печатаются всегда, но кодом не нудят: постоянно ненулевой прибор учит
    # пропускать его вывод, а структурное утверждение держат ADR и карточка
    # владельцу, а не вечно красный светофор.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
