#!/usr/bin/env python3
"""Стояло ли решение о перекладке на ставке, которая ПРОДЕРЖАЛАСЬ, — или на разовом скачке.

Критерий §49 `Persistence` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #702.

Дословно критерий звучит так: **«Transient APY spikes не вызывают ненужные
trades»**. До этого прибора он был ПРОЗОЙ — и хуже: прозой без механизма.
Механизм анти-качелей у нас есть (`churn_damper`, гистерезис разворота — их
измерил ADR-480), механизм стоимости есть, а механизма УСТОЙЧИВОСТИ СТАВКИ нет
нигде: ни одной ручки в `TriggerParams`, ни одного гейта в записанном вердикте,
ни одной строки в аллокаторе. Единственный фильтр живого пути — полоса
здравости `0 < apy <= 200 %` (`allocator._LIVE_APY_MIN/MAX_DECIMAL`), и разовый
скачок с 3,5 % до 5,3 % проходит её, не поморщившись.

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь: **атрибуцию порога**. На днях, где полоса выгоды владельца была
ПРОЙДЕНА (`gates.gain_above_band == true`), прибор заменяет сегодняшнюю ставку
каждого протокола, в который цель ДОБАВЛЯЕТ деньги, на его же УСТОЙЧИВЫЙ
уровень — и смотрит, проходит ли полоса после этого. Не проходит ⇒ полосу
прошёл не мир, а скачок: `spike_carried`.

Замена односторонняя намеренно: ставка занижается до уровня, который реально
держался, и никогда не завышается. Прибор не имеет права ВЫДУМАТЬ улучшение —
только снять то, чего не было.

Формула не переписана заново — она СВЕРЕНА
------------------------------------------------------------------------------
Смешанная ставка книги у производителя есть ``Σ pos_p · apy_p / capital``
(денежные средства дают ноль). Прибор не «реализует ту же логику», а на КАЖДОЙ
строке проверяет, что этой формулой воспроизводятся оба записанных числа
производителя — ``book_apy_pp`` и ``target_apy_pp``. Не воспроизводятся ⇒
строка НЕ оценивается и попадает в ``formula_mismatch``: контрфакт, посчитанный
формулой, которая расходится с производителем, отвечал бы на свой вопрос, а не
на нужный (`site-numbers.md`: операнд — тот, который читает потребитель).

Своих ЧИСЕЛ у прибора нет ни одного
------------------------------------------------------------------------------
§22 ТЗ дословно: «Все значения должны быть config/policy. **Не hardcode**».
Поэтому:

* **окно устойчивости** = ``TriggerParams.min_hold_days`` владельца. Выбор не
  произволен, а выведен: min_hold_days — это срок, на который владелец
  запрещает выдёргивать свежую позицию, то есть срок, на который деньги
  СВЯЗЫВАЮТСЯ ходом. Ставка обязана продержаться хотя бы столько, сколько
  будут связаны деньги, — иначе решение опирается на число короче своего
  собственного следствия;
* **существенность ноги** = ``min_leg_frac`` · капитал строки (та же ручка, что
  у соседей);
* **окно свежести вердикта** = ``reversal_window_days``;
* **полоса выгоды** — не наша: у каждой строки истории записан СВОЙ
  ``required_gain_pp``, и сравнивается контрфакт именно с ним.

Колонка ADR-060 §3 недоступна ⇒ **третий исход** (``UNMEASURED``, код 3), а не
подставленное умолчание: четвёртая копия чисел владельца была бы своим числом.

Оценка уровня — ВЫБОР ПРИБОРА, и поэтому он объявлен числом
------------------------------------------------------------------------------
Ручки «чем считать устойчивый уровень» у владельца нет, значит оценку выбирает
прибор, — а свой выбор надо предъявлять, а не прятать. Поэтому находки
считаются ТРЕМЯ оценками сразу (медиана · минимум · среднее прошлых точек), все
три числа попадают в отчёт, а головным берётся то, что даёт МЕДИАНА. Проверка
``headline_is_lower_bound`` говорит вслух, действительно ли головное число —
нижняя граница класса: если какая-то оценка даст находок МЕНЬШЕ, флаг станет
``false``, и головное число перестанет выдаваться за нижнюю границу.

Ряд ставок берётся у САМОГО решения, а не у соседнего производителя
------------------------------------------------------------------------------
Ставку «aave_v3 на 14.09» в этом дереве называют ДВА разных артефакта, и они
расходятся: журнал решений (``apy_evidenced_pct``) — 5.2038 %, накопитель ряда
(``apy_series_daily.json``) — 12.5545 %, при отметках, отличающихся на 34
секунды одного цикла. Прибор берёт ряд ИЗ ЖУРНАЛА РЕШЕНИЙ: измеряется не
«скакал ли фид», а «на чём стояло решение», и операндом обязано быть то число,
которое решение прочло. Расхождение производителей — предмет соседа
(`adapter_feed_divergence`), и подменять им свой операнд значило бы повторить
ровно тот дефект, который ADR-478 нашёл у сторожа сайта.

Чего прибор НЕ утверждает
------------------------------------------------------------------------------
* **Что деньги поехали.** Ни один из найденных дней не совпал с записанным
  ходом: книга стоит с 11.09. Измерено другое и более неприятное — что ПОЛОСА,
  которой решается движение капитала, была пройдена разовым скачком, а
  остановили ход гейты об обороте, сумме и cooldown. Вред не наступил не потому,
  что от него защищались, а потому что ход был велик и свеж.

  **Ставку вообще видят ДВА гейта из десяти, и оба про ВЕЛИЧИНУ, а не про
  длительность:** ``gain_above_band`` (выгода против полосы) и
  ``payback_within_horizon`` (окупаемость = 365 · стоимость / выгода — функция
  той же выгоды). Остальные восемь к уровню ставки нечувствительны по
  построению: их входы это доллары, доли капитала и часы. Поэтому и
  ``payback_within_horizon``, честно отказавший во все три дня, защитой от
  скачка НЕ является: он отказал по ВЕЛИЧИНЕ и под контрфактом отказал бы
  строже — вопроса «продержалась ли ставка» он не задаёт никогда.
* **Что скачок был ошибкой фида.** Ставка умеет расти по-настоящему; прибор
  говорит только, что она НЕ ПРОДЕРЖАЛАСЬ окна владельца. Разница между
  скачком и новым режимом — это и есть длительность, и она здесь измерена, а не
  предположена (сосед: ``scrvusd`` и ``moonwell_base`` держат повышенный
  уровень неделями и находками НЕ становятся).
* **Что payback пересчитан.** Модель стоимости прибору не принадлежит, и он её
  не воспроизводит: пересчитывается ТОЛЬКО ``gain_above_band``, чья формула
  сверена со строкой. Об этом сказано в отчёте, а не умолчано.

Прибор ТОЛЬКО ЧИТАЕТ: журнал решений, пороги владельца и часы. Ни
``TriggerParams``, ни пороги RiskPolicy v1.0, ни стоп-кран, ни аллокатор, ни
живой трек он не трогает и ничего не чинит. **LLM запрещён** (инвариант #3 —
monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

#: Журнал решений. Один адрес: книга денежного пути — консервативная (ADR-324).
HISTORY_NAME = "allocation_rationale_history.jsonl"

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "apy_persistence_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код возврата третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3

#: Допуск сверки формулы со строкой производителя, в процентных пунктах.
#: Числа записаны как float одной и той же формулой, поэтому расхождение выше
#: машинной погрешности означает ДРУГУЮ формулу, а не округление.
_FORMULA_TOL_PP = 1e-6

#: Оценки устойчивого уровня. Головная — медиана (см. docstring); остальные
#: считаются ВСЕГДА, чтобы находка не зависела от выбора прибора молча.
ESTIMATORS: Dict[str, Callable[[List[float]], float]] = {
    "median": statistics.median,
    "min": min,
    "mean": statistics.fmean,
}
HEADLINE_ESTIMATOR = "median"


# ── часы и разбор ────────────────────────────────────────────────────────────

def _parse_ts(raw: object) -> Optional[datetime]:
    """Отметка времени строки. Нечитаемая отметка — ``None``, не «сейчас»."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(value: object) -> Optional[float]:
    """Конечное число или ``None``. ``bool`` числом не считается (``True`` ≠ 1 %)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None


def _positions(raw: object) -> Optional[Dict[str, float]]:
    """Раскладка книги: ``{протокол: доллары}``. Не-объект — ``None`` (нет наблюдения)."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, float] = {}
    for key, value in raw.items():
        num = _num(value)
        if num is not None:
            out[str(key)] = num
    return out


def blended_pp(positions: Dict[str, float], apy_pct: Dict[str, float],
               capital_usd: float) -> float:
    """Смешанная ставка книги в процентных пунктах — формула ПРОИЗВОДИТЕЛЯ.

    Протокол без наблюдённой ставки вносит ноль: именно так считает строка, и
    именно это на ней сверяется (``_verify_formula``). Своего правила здесь нет.
    """
    return sum(usd * apy_pct.get(key, 0.0)
               for key, usd in positions.items()) / capital_usd


# ── пороги: колонка владельца, а не наши числа ───────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Окно устойчивости и существенность ноги из ``TriggerParams.for_mode()``.

    Колонка недоступна ⇒ ``measured=False``. Подставить сюда умолчание значило
    бы завести ЧЕТВЁРТУЮ копию чисел ADR-060 §3 и ответить на свой вопрос
    вместо нужного (урок `pyflakes`: отсутствие инструмента — третий исход).
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — окно устойчивости "
                               f"и существенность ноги НЕ ИЗМЕРЕНЫ, подставлять свои "
                               f"нельзя (§22: «Все значения должны быть config/policy. "
                               f"Не hardcode»)")}
    try:
        hold_days = int(params.min_hold_days)
        min_leg_frac = float(params.min_leg_frac)
        window_days = float(params.reversal_window_days)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    if hold_days < 1:
        return {"measured": False,
                "reason": (f"окно устойчивости у владельца {hold_days} дн. — на таком "
                           f"окне «продержалась» не определено вовсе; НЕ ИЗМЕРЕНО, "
                           f"а не «скачков нет»")}
    return {"measured": True, "persistence_window_days": hold_days,
            "min_leg_frac": min_leg_frac, "reversal_window_days": window_days,
            "mode": mode, "version": version}


# ── журнал решений ───────────────────────────────────────────────────────────

def read_history(data_dir: Path, filename: str = HISTORY_NAME) -> Dict[str, Any]:
    """Строки журнала решений с диска. Отсутствие/нечитаемость — третий исход."""
    path = Path(data_dir) / filename
    if not path.exists():
        return {"measured": False,
                "reason": f"журнал решений не найден: {path} — мерить нечего, "
                          f"и это НЕ «скачки ставок решений не несли»"}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"measured": False,
                "reason": f"журнал решений нечитаем ({path}): {type(exc).__name__}: {exc}"}
    rows: List[Dict[str, Any]] = []
    unparsable = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            unparsable += 1
            continue
        if isinstance(doc, dict) and doc.get("cycle_date"):
            rows.append(doc)
        else:
            unparsable += 1
    if not rows:
        return {"measured": False,
                "reason": (f"в журнале {path} нет ни одной строки с датой цикла "
                           f"(нечитаемых {unparsable}) — ряд ставок решений НЕ ИЗМЕРЕН")}
    rows.sort(key=lambda r: (str(r.get("cycle_date")),
                             str(r.get("generated_at") or "")))
    return {"measured": True, "rows": rows, "unparsable": unparsable,
            "path": str(path)}


# ── ряд ставок: по одной точке на дату, из журнала САМИХ решений ─────────────

def _evidenced(row: Dict[str, Any]) -> Dict[str, float]:
    """``apy_evidenced_pct`` строки, только наблюдённые числа."""
    raw = row.get("apy_evidenced_pct")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw.items():
        num = _num(value)
        if num is not None:
            out[str(key)] = num
    return out


def _verify_formula(row: Dict[str, Any], apy: Dict[str, float],
                    current: Dict[str, float], target: Dict[str, float],
                    capital: float) -> Optional[str]:
    """Воспроизводится ли ЗАПИСАННОЕ число строки нашей формулой.

    Возвращает причину расхождения либо ``None``. Расхождение — не повод
    «поправить» число: строка просто не оценивается, потому что контрфакт
    посчитался бы формулой, которой производитель не пользуется.
    """
    for field, positions in (("book_apy_pp", current), ("target_apy_pp", target)):
        recorded = _num(row.get(field))
        if recorded is None:
            return f"{field} не записан числом — сверить формулу не на чем"
        ours = blended_pp(positions, apy, capital)
        if abs(ours - recorded) > _FORMULA_TOL_PP:
            return (f"{field}: строка {recorded!r}, наша формула {ours!r} "
                    f"(расхождение {abs(ours - recorded):.9f} пп > {_FORMULA_TOL_PP})")
    return None


def _prior_levels(series: Dict[str, List[Tuple[str, float]]], protocol: str,
                  before_date: str, window: int) -> List[float]:
    """Последние ``window`` наблюдённых точек протокола СТРОГО до ``before_date``."""
    points = [value for date, value in series.get(protocol, ()) if date < before_date]
    return points[-window:]


# ── ядро ────────────────────────────────────────────────────────────────────

def _grade_row(row: Dict[str, Any], series: Dict[str, List[Tuple[str, float]]],
               policy: Dict[str, Any], estimator: Callable[[List[float]], float],
               ) -> Dict[str, Any]:
    """Оценка ОДНОЙ строки: пройдена ли полоса без разового скачка.

    Ответ несёт либо находку, либо названную причину, почему строка не судится.
    Ни одна ветка не возвращает «скачка нет» молча.
    """
    capital = _num(row.get("capital_usd"))
    current = _positions(row.get("current_positions"))
    target = _positions(row.get("target_positions"))
    required = _num(row.get("required_gain_pp"))
    recorded_gain = _num(row.get("gain_pp"))
    gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
    apy = _evidenced(row)
    date = str(row.get("cycle_date"))

    if not capital or capital <= 0 or current is None or target is None:
        return {"date": date, "verdict": "unusable",
                "reason": "строка не несёт капитала или раскладок книги числами"}
    if required is None or recorded_gain is None:
        return {"date": date, "verdict": "unusable",
                "reason": "строка не несёт полосы выгоды или выгоды числами"}
    if gates.get("gain_above_band") is not True:
        return {"date": date, "verdict": "band_not_cleared",
                "reason": "полоса выгоды владельца в этот день НЕ пройдена — "
                          "атрибутировать нечего"}
    # Флаг гейта и ЧИСЛА строки обязаны говорить одно и то же. Расходятся ⇒
    # строка не судится: атрибутировать скачку прохождение полосы, которого по
    # собственным числам строки не было, значило бы выдумать находку. Замер
    # приёмки #702: без этой сверки сцена с лживым флагом давала `spike_carried`
    # при выгоде НИЖЕ полосы — то есть находку из ничего.
    if recorded_gain < required:
        return {"date": date, "verdict": "row_self_inconsistent",
                "reason": (f"строка объявляет `gain_above_band` пройденной, а её "
                           f"собственные числа говорят обратное: выгода "
                           f"{recorded_gain!r} пп ниже полосы {required!r} пп — "
                           f"атрибуция НЕ ИЗМЕРЕНА, а не «скачок»")}

    mismatch = _verify_formula(row, apy, current, target, capital)
    if mismatch:
        return {"date": date, "verdict": "formula_mismatch", "reason": mismatch}

    materiality = policy["min_leg_frac"] * capital
    increases = {p: target.get(p, 0.0) - current.get(p, 0.0) for p in target}
    increases = {p: d for p, d in increases.items() if d > materiality}
    if not increases:
        return {"date": date, "verdict": "no_material_increase",
                "reason": (f"цель не добавляет существенно ни одному протоколу "
                           f"(существенность ${materiality:,.2f} = min_leg_frac "
                           f"владельца × капитал)")}

    window = policy["persistence_window_days"]
    counterfactual = dict(apy)
    elevated: List[Dict[str, Any]] = []
    unchecked: List[Dict[str, Any]] = []
    for protocol in sorted(increases):
        today = apy.get(protocol)
        if today is None:
            unchecked.append({"protocol": protocol, "observed_days": 0,
                              "reason": "ставка протокола в этот день НЕ наблюдена"})
            continue
        prior = _prior_levels(series, protocol, date, window)
        if len(prior) < window:
            unchecked.append({"protocol": protocol, "observed_days": len(prior),
                              "reason": (f"наблюдённых дней до {date} всего {len(prior)} "
                                         f"при окне устойчивости {window} — "
                                         f"«продержалась» НЕ ИЗМЕРЕНО")})
            continue
        level = float(estimator(prior))
        if today > level:
            counterfactual[protocol] = level
            elevated.append({"protocol": protocol, "today_pct": today,
                             "persistent_pct": round(level, 6),
                             "elevation_pp": round(today - level, 6),
                             "added_usd": round(increases[protocol], 2),
                             "prior_pct": prior})

    gain_cf = (blended_pp(target, counterfactual, capital)
               - blended_pp(current, counterfactual, capital))
    carried = gain_cf < required
    return {
        "date": date,
        "generated_at": row.get("generated_at"),
        "verdict": "spike_carried" if carried else "persists",
        "recorded_gain_pp": round(recorded_gain, 6),
        "required_gain_pp": required,
        "counterfactual_gain_pp": round(gain_cf, 6),
        "gain_attributable_to_transient_pp": round(recorded_gain - gain_cf, 6),
        "elevated": elevated,
        "unchecked_protocols": unchecked,
        "partially_unchecked": bool(unchecked),
        "turnover_usd": round(sum(increases.values()), 2),
        "refusing_gates": sorted(k for k, v in gates.items() if v is False),
        "refusal_reasons": [r for r in (row.get("reasons") or [])
                            if isinstance(r, str)],
    }


def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None, history_name: str = HISTORY_NAME,
               ) -> Dict[str, Any]:
    """Перепись атрибуции полосы. Три исхода различимы, третий не сворачивается.

    ``now`` инъектируется: вердикт судит о ВОЗРАСТЕ находок, и настенные часы
    сделали бы сцену смертной от календаря (`.claude/rules/deployment.md`).
    """
    now = now or datetime.now(timezone.utc)

    policy = load_policy(params)
    if not policy["measured"]:
        return _unmeasured(policy["reason"], now)

    history = read_history(data_dir, history_name)
    if not history["measured"]:
        return _unmeasured(history["reason"], now)

    rows = history["rows"]

    # Находки считаются ВСЕМИ оценками уровня: выбор оценки — наш, и он
    # предъявляется числом, а не прячется в коде.
    by_estimator: Dict[str, List[Dict[str, Any]]] = {}
    for name, estimator in ESTIMATORS.items():
        series: Dict[str, List[Tuple[str, float]]] = {}
        graded: List[Dict[str, Any]] = []
        for row in rows:
            graded.append(_grade_row(row, series, policy, estimator))
            # Ряд наращивается ПОСЛЕ оценки строки: решение дня не могло
            # видеть собственную точку как историю.
            for protocol, value in _evidenced(row).items():
                points = series.setdefault(protocol, [])
                date = str(row.get("cycle_date"))
                if points and points[-1][0] == date:
                    points[-1] = (date, value)   # последний прогон дня
                else:
                    points.append((date, value))
        by_estimator[name] = graded

    graded = by_estimator[HEADLINE_ESTIMATOR]
    carried = [g for g in graded if g["verdict"] == "spike_carried"]
    counts_by_estimator = {name: sum(1 for g in rows_ if g["verdict"] == "spike_carried")
                           for name, rows_ in by_estimator.items()}
    headline_is_lower_bound = all(
        counts_by_estimator[HEADLINE_ESTIMATOR] <= n
        for n in counts_by_estimator.values())

    band_days = [g for g in graded
                 if g["verdict"] in ("spike_carried", "persists")]
    window_hours = policy["reversal_window_days"] * 24.0
    recent: List[Dict[str, Any]] = []
    for item in carried:
        stamp = _parse_ts(item.get("generated_at")) or _parse_ts(
            f"{item['date']}T00:00:00+00:00")
        item["age_hours"] = (round((now - stamp).total_seconds() / 3600.0, 2)
                             if stamp else None)
        if item["age_hours"] is not None and item["age_hours"] <= window_hours:
            recent.append(item)

    if recent:
        status = STATUS_CRITICAL
    elif carried:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": ("§49 Persistence — «Transient APY spikes не вызывают "
                      "ненужные trades»"),
        "history": {"path": history["path"], "rows": len(rows),
                    "unparsable": history["unparsable"],
                    "first_date": str(rows[0].get("cycle_date")),
                    "last_date": str(rows[-1].get("cycle_date"))},
        "policy": {k: policy[k] for k in
                   ("persistence_window_days", "min_leg_frac",
                    "reversal_window_days", "mode", "version")},
        "estimator": HEADLINE_ESTIMATOR,
        "counts_by_estimator": counts_by_estimator,
        "headline_is_lower_bound": headline_is_lower_bound,
        "counts": {
            "rows_total": len(rows),
            "band_cleared_days": len(band_days),
            "spike_carried": len(carried),
            "persists": len(band_days) - len(carried),
            "partially_unchecked": sum(1 for g in band_days
                                       if g.get("partially_unchecked")),
            "formula_mismatch": sum(1 for g in graded
                                    if g["verdict"] == "formula_mismatch"),
            "unusable": sum(1 for g in graded if g["verdict"] == "unusable"),
            "row_self_inconsistent": sum(1 for g in graded
                                         if g["verdict"] == "row_self_inconsistent"),
            "recent_from_now": len(recent),
        },
        # Заголовочные числа ДУБЛИРУЮТСЯ наверх намеренно: мост и офис читают их
        # через ``observed_number(doc, key)``, который смотрит верхний уровень.
        # Это не второе место для числа — оба вычислены здесь же, одной строкой.
        "spike_carried": len(carried),
        "band_cleared_days": len(band_days),
        "recent_from_now": len(recent),
        # Утверждение о ПОСТРОЕНИИ: механизма устойчивости нет, и оно не гаснет
        # от того, что книга неделю стояла. Проверяется контрфактом — под ним
        # меняет вердикт РОВНО полоса выгоды, а остальные гейты к уровню ставки
        # нечувствительны (их входы — доллары и часы).
        "no_persistence_gate": bool(carried),
        "findings": carried,
        "recent": recent,
        "graded": graded,
    }


def _unmeasured(reason: str, now: datetime) -> Dict[str, Any]:
    return {"measured": False, "status": STATUS_UNMEASURED, "reason": reason,
            "generated_at": now.isoformat(), "findings": [], "recent": [],
            "graded": [], "no_persistence_gate": False,
            "counts": {"rows_total": 0, "band_cleared_days": 0,
                       "spike_carried": 0, "persists": 0,
                       "partially_unchecked": 0, "formula_mismatch": 0,
                       "unusable": 0, "row_self_inconsistent": 0,
                       "recent_from_now": 0}}


# ── отчёт ───────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"устойчивость ставки решения (§49 Persistence): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    c = report["counts"]
    return (f"устойчивость ставки решения (§49 Persistence): {report['status']} · "
            f"строк {c['rows_total']} · полоса выгоды пройдена в {c['band_cleared_days']} "
            f"дн. · ПРОЙДЕНА РАЗОВЫМ СКАЧКОМ {c['spike_carried']} "
            f"(свежих от now {c['recent_from_now']}) · окно устойчивости "
            f"{report['policy']['persistence_window_days']} дн. (min_hold_days "
            f"владельца, колонка {report['policy']['mode']})")


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Строки для офиса — находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        return lines
    if report["status"] == STATUS_WARNING:
        lines.append(
            f"[ВЕРДИКТ] свежих находок от now нет, но в истории их "
            f"{report['counts']['spike_carried']} — «сегодня тихо» НЕ значит "
            f"«такого не бывало»; последняя строка журнала "
            f"{report['history']['last_date']}")
    for item in report.get("findings", [])[:limit]:
        who = ", ".join(
            f"{e['protocol']} {e['today_pct']:.4f} % против устойчивых "
            f"{e['persistent_pct']:.4f} % (+{e['elevation_pp']:.4f} пп, "
            f"добавлено ${e['added_usd']:,.0f})" for e in item["elevated"])
        lines.append(
            f"[ПОЛОСУ ПРОШЁЛ СКАЧОК] {item['date']}: записано "
            f"{item['recorded_gain_pp']:.3f} пп при полосе "
            f"{item['required_gain_pp']:.3f} пп, а на устойчивых ставках "
            f"{item['counterfactual_gain_pp']:.3f} пп — скачку принадлежит "
            f"{item['gain_attributable_to_transient_pp']:.3f} пп из выгоды; "
            f"{who or 'ни один протокол не был поднят'}")
        lines.append(
            f"   ход остановили гейты {', '.join(item['refusing_gates']) or '—'} "
            f"— ни один из них НЕ про ДЛИТЕЛЬНОСТЬ ставки (`payback_within_horizon` "
            f"тоже про величину выгоды): оборот ${item['turnover_usd']:,.0f}")
        if item.get("partially_unchecked"):
            lines.append(
                f"   ⚠️ часть протоколов НЕ ИЗМЕРЕНА (истории короче окна): "
                + "; ".join(f"{u['protocol']} — {u['reason']}"
                            for u in item["unchecked_protocols"]))
    extra = len(report.get("findings", [])) - limit
    if extra > 0:
        lines.append(f"… ещё {extra} находок(и) — полный перечень в артефакте")
    if report.get("no_persistence_gate"):
        lines.append(
            "[СЛЕПОТА ПО ПОСТРОЕНИЮ] механизма устойчивости ставки нет НИГДЕ на "
            "денежном пути: ни ручки в TriggerParams, ни гейта в записанном "
            "вердикте. Ставку видят ДВА гейта из десяти — `gain_above_band` и "
            "`payback_within_horizon` (окупаемость есть функция той же выгоды), — "
            "и оба про ВЕЛИЧИНУ выгоды, а не про длительность ставки; остальные "
            "восемь к уровню ставки нечувствительны, их входы это доллары и часы. "
            "Это утверждение о ПОСТРОЕНИИ, и оно не гаснет от того, что книга "
            "неделю стояла")
    lines.append(
        f"[ОПОРА] оценка устойчивого уровня — ВЫБОР прибора, поэтому предъявлена "
        f"числом: {', '.join(f'{k}={v}' for k, v in sorted(report['counts_by_estimator'].items()))}; "
        f"головная {report['estimator']}"
        + (" — нижняя граница класса" if report.get("headline_is_lower_bound")
           else " — НЕ нижняя граница: другая оценка даёт находок меньше"))
    lines.append(
        "НЕ ДОКЛАДЫВАЕТ: что деньги поехали (ни одна находка не совпала с "
        "записанным ходом) · что скачок был ошибкой фида (новый режим держится "
        "и находкой не становится) · payback НЕ пересчитан — модель стоимости "
        "прибору не принадлежит · пороги RiskPolicy v1.0, стоп-кран, аллокатор "
        "и живой трек НЕ трогаются, прибор только читает")
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
    # Ненулевой код — только на СВЕЖУЮ находку, то есть на то, что решается
    # сегодня. `WARNING` (история есть, настоящее тихо) печатается всегда, но
    # кодом не нудит: постоянно ненулевой прибор учит пропускать его вывод, а
    # структурное утверждение держат ADR и карточка владельцу.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
