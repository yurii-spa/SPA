"""error_class_census.py — §32 ТЗ «Portfolio CIO»: «Ошибки, которые необходимо измерять».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §32::

    Ошибки, которые необходимо измерять
    Минимум:
    False Rebalance · Missed Opportunity · Late Rebalance · Excessive Turnover ·
    Risk Violation · APY Forecast Error · Break-even Forecast Error

Классов СЕМЬ, и слово владельца «Минимум:» означает, что это ПОЛ, а не потолок: прибор
сверяет семь названных и не утверждает, что других ошибок не бывает.

Предмет — «у КАЖДОГО из семи классов есть ИЗМЕРИТЕЛЬ: носитель, считающий ошибку ПОСЛЕ
того, как она могла случиться, с населением и третьим исходом», а не «есть ли реплей».
Разница существенна, и ради неё у класса ПЯТЬ родов, а не два:

* ``measured`` — носитель считает ошибку post-hoc, население названо, «не измерено»
  отличимо от «ноль ошибок» (ключ третьего исхода есть);
* ``measured_without_third_outcome`` — население и счёт есть, но «не проверено» в носителе
  неотличимо от «ошибок нет» (инв. #17);
* ``signal_at_t0_only`` — класс виден только как ПРИЧИНА ОТКАЗА или ТРИГГЕР в момент
  решения (гейт оборота, календарный триггер RT-04). Гейт предотвращает ошибку, но не
  измеряет, случилась ли она: сколько раз оборот ПРЕВЫСИЛ бюджет по факту, сколько дней
  перекладка ОПОЗДАЛА — не считает никто;
* ``forecast_and_fact_uncompared`` — прогноз лежит в одном носителе (запись: ``payback_days``),
  факт — в другом (реплей: реализованная окупаемость ложных перекладок), и НИ ОДИН не
  вычитает одно из другого. Ошибка прогноза — это разность, а разности нет;
* ``absent`` — ни измерителя, ни сигнала, ни прогноза.

Свежесть измерителя — ОТДЕЛЬНЫЙ вопрос от его наличия: измеритель, не бежавший дольше
своего SLO (``architecture/manifest.json``, второго места для порога нет), есть, но
отвечает о мире, которого уже нет. Возраст считается от ``now`` — входа, не часов.

🪤 ЛОВУШКА, ради которой прибор различает «сигнал в T0» и «замер после»
=====================================================================
Судья тени несёт `move_turnover_over_budget` у 103 строк из 188, а трек — `turnover_usd`
по дням. Замер по наличию слова «turnover» сказал бы «оборот измеряется». Но причина
отказа говорит, что оборот ПРЕДЛОЖЕННОГО хода превысил бы бюджет, а колонка трека — сколько
обернулось; НИКТО не сверяет второе с бюджетом и не называет день, в который оборот был
избыточным. Это сигнал до ошибки, а не измерение ошибки.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): реплей, судью, запись, трек, лимиты и триггер не правит
ни байтом. Карточку владельцу не заводит: измерители — advisory-слой, работа агента.
Контрапункты ВВЕЗЕНЫ, не перемерены: реплей §38 (ADR-220), судья тени, точность прогноза
APY (`apy_forecast_accuracy`), дневные лимиты (`daily_limits`), триггер (ADR-031),
§31 ось C (ADR-977: у break-even есть прогноз, факта на рекомендацию нет).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/error_class_census.json"
CARD_REL = smc.CARD_REL
MANIFEST_REL = "architecture/manifest.json"

# ───────────────────────────── дословное требование ───────────────────────────
SECTION_HEAD = "32. Ошибки, которые необходимо измерять"
NEXT_SECTION_HEAD = "33. Portfolio KPIs"
OWNER_FLOOR_WORD = "Минимум:"
OWNER_CLASSES: Tuple[str, ...] = (
    "False Rebalance",
    "Missed Opportunity",
    "Late Rebalance",
    "Excessive Turnover",
    "Risk Violation",
    "APY Forecast Error",
    "Break-even Forecast Error",
)
#: Число ОБЪЯВЛЕНО и краснеет тестом (урок §22/§23/§30: заказ назвал меньше, чем владелец).
OWNER_CLASSES_DECLARED = 7
#: Заказ G965 п. 1 назвал классы ПОЛНОСТЬЮ (хвост прочитан) — сдвиг 0 печатается.
ORDER_G965_NAMED: Dict[str, Any] = {"classes": 7, "floor_word_named": True, "tail_read": True}

# ───────────────────────────── словарь родов ──────────────────────────────────
CLASS_KINDS: Tuple[str, ...] = (
    "measured",
    "measured_without_third_outcome",
    "signal_at_t0_only",
    "forecast_and_fact_uncompared",
    "forecast_without_fact",
    "absent",
    UNMEASURED,
)
#: Роды, при которых класс считается ИЗМЕРЯЕМЫМ в смысле §32.
MEASURED_KINDS: Tuple[str, ...] = ("measured",)

#: Носители.
REPLAY_REL = "cio_shadow_replay.json"
EVAL_REL = smc.EVAL_REL
RECORD_REL = smc.RECORD_REL
TRACK_REL = smc.TRACK_REL
FORECAST_REL = "apy_forecast_accuracy.json"
LIMITS_REL = "risk_limits_check.json"
BLOCKS_REL = "risk_policy_blocks.json"
TRIGGER_REL = "rebalance_trigger.json"

#: Причины отказа судьи, которыми класс «Excessive Turnover» виден в T0.
TURNOVER_REASON_PREFIXES: Tuple[str, ...] = (
    "move_turnover_over_budget", "week_turnover_over_budget", "day_turnover_over_budget",
)
#: Статусы проверки дневных лимитов; SKIP — третий исход у производителя.
LIMIT_FAIL = "FAIL"
LIMIT_SKIP = "SKIP"
#: Значение судьи, означающее «не проверено» (не вердикт).
JUDGE_UNCHECKED = "UNCHECKED"


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по нему "
                      f"был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _items_after(body: List[str], lead: str) -> Optional[List[str]]:
    """Пункты после строки ``lead`` до «⸻» или конца раздела. HTML-комментарии карточки
    (`<!-- источник … -->`) — не пункты владельца."""
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if s == "⸻":
            break
        if not s or s.startswith("<!--"):
            continue
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = smc._read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {
        "measured": True,
        "classes": _items_after(body, OWNER_FLOOR_WORD),
        "floor_word_present": OWNER_FLOOR_WORD in stripped,
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None,
                           "order_tail_read": ORDER_G965_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    cls = parsed["classes"]
    # Пункты читаются ПОСЛЕ слова «Минимум:», поэтому «слова нет» и «пунктов нет» — одна
    # проверка, не две: раздельная вторая выживала мутацией (SMC-978 M02, первый проход).
    if cls is None:
        mism.append(f"в разделе нет слова владельца {OWNER_FLOOR_WORD!r} — перечень не объявлен "
                    f"полом, пункты не прочитаны")
    elif list(cls) != list(OWNER_CLASSES):
        mism.append(f"классы карточки {cls} ≠ константам {list(OWNER_CLASSES)}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if cls is not None:
        out["order_undercount"] = {"classes": len(cls) - int(ORDER_G965_NAMED["classes"])}
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str) -> Dict[str, Any]:
    """Запись/трек/судья — дверью §30; реплей, прогноз APY, лимиты, блоки, триггер — своими."""
    out = smc.load_carriers(data_dir)
    d = Path(data_dir)
    for key, rel, want in (("replay", REPLAY_REL, dict), ("forecast", FORECAST_REL, dict),
                           ("limits", LIMITS_REL, dict), ("blocks", BLOCKS_REL, list),
                           ("trigger", TRIGGER_REL, dict)):
        doc, why = smc._read_json(d / rel)
        ok = isinstance(doc, want)
        out[key] = doc if ok else None
        out[f"{key}_reason"] = why if doc is None else (None if ok else f"{rel} не {want.__name__}")
    return out


def load_slo(root: str) -> Dict[str, Optional[float]]:
    """SLO свежести по пути артефакта — из манифеста, второго места для порога нет."""
    doc, _ = smc._read_json(Path(root) / MANIFEST_REL)
    out: Dict[str, Optional[float]] = {}
    if not isinstance(doc, dict):
        return out
    for art in doc.get("artifacts") or []:
        if isinstance(art, dict) and art.get("path"):
            slo = art.get("slo_hours")
            out[str(art["path"])] = float(slo) if isinstance(slo, (int, float)) else None
    return out


def _parse_ts(raw: object) -> Optional[dt.datetime]:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def freshness(stamp: object, rel: str, slo: Dict[str, Optional[float]],
              now: dt.datetime) -> Dict[str, Any]:
    """Возраст носителя против его SLO. Три исхода: свеж · устарел · не измерен (нет отметки
    либо нет SLO) — последнее НЕ есть «свеж»."""
    ts = _parse_ts(stamp)
    slo_h = slo.get(f"data/{rel}")
    if ts is None:
        return {"stamp": stamp, "age_hours": None, "slo_hours": slo_h, "fresh": None,
                "reason": "отметка времени носителя не прочитана"}
    age = round((now - ts).total_seconds() / 3600.0, 2)
    if slo_h is None:
        return {"stamp": ts.isoformat(), "age_hours": age, "slo_hours": None, "fresh": None,
                "reason": f"SLO для data/{rel} в манифесте не объявлен"}
    return {"stamp": ts.isoformat(), "age_hours": age, "slo_hours": slo_h,
            "fresh": age <= slo_h, "reason": None}


def _judge_rows(carriers: Dict[str, Any]) -> Tuple[Optional[List[dict]], Optional[str]]:
    ev = carriers.get("eval")
    if ev is None:
        return None, f"судья {EVAL_REL} не прочитан: {carriers.get('eval_reason')}"
    rows = ev.get("per_verdict") if isinstance(ev, dict) else None
    if not isinstance(rows, list):
        return None, f"у судьи {EVAL_REL} нет списка per_verdict"
    return [r for r in rows if isinstance(r, dict)], None


def _carrier(name: str, role: str, **extra: Any) -> Dict[str, Any]:
    c: Dict[str, Any] = {"carrier": name, "role": role}
    c.update(extra)
    return c


def _replay_block(carriers: Dict[str, Any], key: str) -> Tuple[Optional[dict], Optional[str]]:
    replay = carriers.get("replay")
    if replay is None:
        return None, f"реплей {REPLAY_REL} не прочитан: {carriers.get('replay_reason')}"
    block = replay.get(key)
    if not isinstance(block, dict):
        return None, f"у реплея {REPLAY_REL} нет словаря {key!r}"
    return block, None


def _post_hoc_block(block: dict, pop_key: str, hit_key: str, third_key: str) -> Dict[str, Any]:
    """Блок реплея вида {checked, <hit>, unchecked?}: население · счёт · третий исход."""
    pop = block.get(pop_key)
    hits = block.get(hit_key)
    has_third = third_key in block
    if block.get("verdict") == JUDGE_UNCHECKED:
        return {"population": None, "hits": None, "third_outcome_key": third_key,
                "third_outcome_present": True, "unchecked": None,
                "kind": UNMEASURED, "reason": f"носитель сам отказал: {block.get('reason')}"}
    if not isinstance(pop, (int, float)) or not isinstance(hits, (int, float)):
        return {"population": pop, "hits": hits, "third_outcome_key": third_key,
                "third_outcome_present": has_third, "unchecked": block.get(third_key),
                "kind": UNMEASURED, "reason": f"ключи {pop_key!r}/{hit_key!r} не числа"}
    return {"population": int(pop), "hits": int(hits), "third_outcome_key": third_key,
            "third_outcome_present": has_third, "unchecked": block.get(third_key),
            "kind": "measured" if has_third else "measured_without_third_outcome",
            "reason": None}


# ───────────────────────────── классы ────────────────────────────────────────

def measure_false_rebalance(carriers: Dict[str, Any]) -> Dict[str, Any]:
    block, why = _replay_block(carriers, "false_rebalances")
    if block is None:
        return {"kind": UNMEASURED, "reason": why, "carriers": []}
    r = _post_hoc_block(block, "checked", "false", "unchecked")
    c = _carrier(f"{REPLAY_REL}:false_rebalances", "post_hoc", **r)
    return {"kind": r["kind"], "reason": r["reason"], "carriers": [c],
            "population": r["population"], "errors": r["hits"]}


def measure_missed_opportunity(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    block, why = _replay_block(carriers, "missed_opportunities")
    if block is not None:
        r = _post_hoc_block(block, "checked", "missed", "unchecked")
        cs.append(_carrier(f"{REPLAY_REL}:missed_opportunities", "post_hoc", **r))
    rows, why_j = _judge_rows(carriers)
    if rows is not None:
        with_val = [r for r in rows if isinstance(r.get("missed_usd"), (int, float))]
        unchecked = [r for r in rows if r.get("counterfactual") == JUDGE_UNCHECKED]
        cs.append(_carrier(f"{EVAL_REL}:per_verdict.missed_usd", "post_hoc",
                           population=len(with_val), hits=sum(1 for r in with_val if r["missed_usd"] > 0),
                           third_outcome_key="counterfactual=UNCHECKED",
                           third_outcome_present=True, unchecked=len(unchecked),
                           kind="measured" if with_val or unchecked else UNMEASURED,
                           reason=None if (with_val or unchecked) else "у судьи нет строк с missed_usd"))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"{why}; {why_j}", "carriers": []}
    kinds = [c["kind"] for c in cs]
    kind = ("measured" if "measured" in kinds else
            "measured_without_third_outcome" if "measured_without_third_outcome" in kinds
            else UNMEASURED)
    best = next((c for c in cs if c["kind"] == kind), cs[0])
    return {"kind": kind, "reason": None if kind != UNMEASURED else "; ".join(
        str(c.get("reason")) for c in cs), "carriers": cs,
        "population": best.get("population"), "errors": best.get("hits")}


def measure_late_rebalance(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Опоздание перекладки не считает никто; календарный триггер RT-04 — сигнал в T0."""
    trig = carriers.get("trigger")
    if trig is None:
        return {"kind": UNMEASURED, "reason": f"триггер {TRIGGER_REL} не прочитан: "
                                              f"{carriers.get('trigger_reason')}", "carriers": []}
    rt04 = (trig.get("checks") or {}).get("rt04") if isinstance(trig.get("checks"), dict) else None
    if not isinstance(rt04, dict):
        return {"kind": "absent", "reason": "ни измерителя опоздания, ни триггера RT-04 в артефакте",
                "carriers": [], "population": None, "errors": None}
    c = _carrier(f"{TRIGGER_REL}:checks.rt04", "signal_at_t0",
                 days_since=rt04.get("days_since"), threshold_days=rt04.get("threshold_days"),
                 triggered=rt04.get("triggered"), measured=rt04.get("measured"))
    return {"kind": "signal_at_t0_only",
            "reason": ("RT-04 говорит «пора» (дней с последней перекладки против порога), но сколько "
                       "дней перекладка ОПОЗДАЛА и что это стоило — не считает никто"),
            "carriers": [c], "population": None, "errors": None}


def measure_excessive_turnover(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Гейты оборота — причины отказа в T0; реализованный оборот лежит в треке; сверки нет."""
    cs: List[Dict[str, Any]] = []
    rows, why_j = _judge_rows(carriers)
    if rows is not None:
        hits = 0
        by_prefix: Dict[str, int] = {p: 0 for p in TURNOVER_REASON_PREFIXES}
        for r in rows:
            reasons = [str(s).split(":")[0] for s in (r.get("reasons") or [])]
            matched = [p for p in TURNOVER_REASON_PREFIXES if p in reasons]
            if matched:
                hits += 1
            for p in matched:
                by_prefix[p] += 1
        cs.append(_carrier(f"{EVAL_REL}:per_verdict.reasons", "signal_at_t0",
                           population=len(rows), rows_with_turnover_refusal=hits,
                           by_prefix=by_prefix))
    daily = carriers.get("daily")
    if daily is not None:
        with_t = [d for d in daily if isinstance(d, dict) and isinstance(d.get("turnover_usd"), (int, float))]
        cs.append(_carrier(f"{TRACK_REL}:daily.turnover_usd", "raw_observation",
                           population=len(daily), rows_with_turnover=len(with_t),
                           rows_without_turnover=len(daily) - len(with_t),
                           compared_to_budget_by=None))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"{why_j}; трек: {carriers.get('daily_reason')}",
                "carriers": []}
    return {"kind": "signal_at_t0_only",
            "reason": ("оборот виден как причина отказа ПРЕДЛОЖЕННОМУ ходу и как колонка трека; "
                       "ни один носитель не сверяет РЕАЛИЗОВАННЫЙ оборот с бюджетом и не называет "
                       "день, в который он был избыточным"),
            "carriers": cs, "population": None, "errors": None}


def measure_risk_violation(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    lim = carriers.get("limits")
    if lim is not None:
        checks = [c for c in (lim.get("checks") or []) if isinstance(c, dict)]
        fails = [c.get("id") for c in checks if c.get("status") == LIMIT_FAIL]
        skips = [c.get("id") for c in checks if c.get("status") == LIMIT_SKIP]
        has_third = "skip_reasons" in lim or bool(skips)
        cs.append(_carrier(f"{LIMITS_REL}:checks", "post_hoc",
                           population=len(checks), hits=len(fails), failing=fails,
                           third_outcome_key="skip_reasons / status=SKIP",
                           third_outcome_present=has_third, unchecked=len(skips),
                           kind=("measured" if checks and has_third else
                                 "measured_without_third_outcome" if checks else UNMEASURED),
                           reason=None if checks else "в проверке лимитов нет ни одной проверки",
                           shape="snapshot"))
    blocks = carriers.get("blocks")
    if blocks is not None:
        rows = [b for b in blocks if isinstance(b, dict)]
        with_v = [b for b in rows if b.get("violations")]
        cs.append(_carrier(f"{BLOCKS_REL}", "post_hoc", population=len(rows), hits=len(with_v),
                           third_outcome_key=None, third_outcome_present=False, unchecked=None,
                           kind="measured_without_third_outcome" if rows else UNMEASURED,
                           reason=None if rows else "журнал блоков пуст", shape="history",
                           last_date=max((str(b.get("date") or b.get("ts") or "") for b in rows),
                                         default=None)))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"лимиты: {carriers.get('limits_reason')}; "
                                              f"блоки: {carriers.get('blocks_reason')}", "carriers": []}
    kinds = [c["kind"] for c in cs]
    kind = ("measured" if "measured" in kinds else
            "measured_without_third_outcome" if "measured_without_third_outcome" in kinds
            else UNMEASURED)
    best = next((c for c in cs if c["kind"] == kind), cs[0])
    return {"kind": kind, "reason": None if kind != UNMEASURED else "; ".join(
        str(c.get("reason")) for c in cs), "carriers": cs,
        "population": best.get("population"), "errors": best.get("hits"),
        "failing_today": next((c.get("failing") for c in cs if "failing" in c), None)}


def measure_apy_forecast_error(carriers: Dict[str, Any]) -> Dict[str, Any]:
    fc = carriers.get("forecast")
    if fc is None:
        return {"kind": UNMEASURED, "reason": f"прогноз {FORECAST_REL} не прочитан: "
                                              f"{carriers.get('forecast_reason')}", "carriers": []}
    pop = fc.get("population") if isinstance(fc.get("population"), dict) else {}
    scoreable = pop.get("scoreable")
    observed = pop.get("days_observed")
    sign = fc.get("sign_disagreements")
    has_third = "unchecked" in fc and isinstance(observed, (int, float))
    observed_n = int(observed) if isinstance(observed, (int, float)) else None
    if not isinstance(scoreable, (int, float)) or not isinstance(sign, list):
        return {"kind": UNMEASURED, "reason": "у прогноза нет population.scoreable или sign_disagreements",
                "carriers": [_carrier(FORECAST_REL, "post_hoc", kind=UNMEASURED)]}
    c = _carrier(f"{FORECAST_REL}:sign_disagreements", "post_hoc",
                 population=int(scoreable), hits=len(sign),
                 third_outcome_key="unchecked / days_observed−scoreable",
                 third_outcome_present=has_third,
                 unchecked=(observed_n - int(scoreable)) if (has_third and observed_n is not None) else None,
                 kind="measured" if has_third else "measured_without_third_outcome", reason=None,
                 magnitude_n=(fc.get("magnitude") or {}).get("n") if isinstance(fc.get("magnitude"), dict) else None)
    return {"kind": c["kind"], "reason": None, "carriers": [c],
            "population": c["population"], "errors": c["hits"]}


def measure_break_even_forecast_error(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Прогноз окупаемости — у записи (`payback_days`); факт — у реплея (реализованная
    окупаемость ложных перекладок). Разности никто не считает."""
    cs: List[Dict[str, Any]] = []
    recs = carriers.get("records")
    if recs is not None:
        with_f = [r for r in recs if isinstance(r.get("payback_days"), (int, float))]
        cs.append(_carrier(f"{RECORD_REL}:payback_days", "forecast",
                           population=len(recs), rows_with_forecast=len(with_f)))
    block, _ = _replay_block(carriers, "false_rebalances")
    if block is not None:
        worst = [w for w in (block.get("worst") or []) if isinstance(w, dict)]
        with_fact = [w for w in worst if isinstance(w.get("payback_days"), (int, float))]
        cs.append(_carrier(f"{REPLAY_REL}:false_rebalances.worst[].payback_days", "fact",
                           population=block.get("checked"), rows_with_fact=len(with_fact),
                           rows_listed=len(worst), compared_to_forecast_by=None))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"запись: {carriers.get('records_reason')}; "
                                              f"реплей: {carriers.get('replay_reason')}", "carriers": []}
    roles = {c["role"] for c in cs}
    forecast_rows = sum(c.get("rows_with_forecast") or 0 for c in cs if c["role"] == "forecast")
    fact_rows = sum(c.get("rows_with_fact") or 0 for c in cs if c["role"] == "fact")
    if forecast_rows and fact_rows:
        kind, reason = "forecast_and_fact_uncompared", (
            f"прогноз окупаемости у {forecast_rows} записей, реализованная окупаемость у "
            f"{fact_rows} перекладок реплея — лежат в разных носителях, разность не считает никто")
    elif forecast_rows:
        kind, reason = "forecast_without_fact", "прогноз окупаемости есть, факта на перекладку нет"
    elif "forecast" in roles or "fact" in roles:
        kind, reason = "absent", "ни прогноза окупаемости, ни факта в носителях"
    else:
        kind, reason = UNMEASURED, "носители прочитаны, но ролей не нашлось"
    return {"kind": kind, "reason": reason, "carriers": cs, "population": None, "errors": None}


MEASURERS = {
    "False Rebalance": measure_false_rebalance,
    "Missed Opportunity": measure_missed_opportunity,
    "Late Rebalance": measure_late_rebalance,
    "Excessive Turnover": measure_excessive_turnover,
    "Risk Violation": measure_risk_violation,
    "APY Forecast Error": measure_apy_forecast_error,
    "Break-even Forecast Error": measure_break_even_forecast_error,
}

#: Какой носитель задаёт свежесть измерителя класса (по его отметке `generated_at`/`checked_at`).
FRESHNESS_CARRIER: Dict[str, Tuple[str, str, str]] = {
    "False Rebalance": ("replay", REPLAY_REL, "generated_at"),
    "Missed Opportunity": ("replay", REPLAY_REL, "generated_at"),
    "Risk Violation": ("limits", LIMITS_REL, "checked_at"),
    "APY Forecast Error": ("forecast", FORECAST_REL, "generated_at"),
}


def measure_classes(carriers: Dict[str, Any], slo: Dict[str, Optional[float]],
                    now: dt.datetime) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in OWNER_CLASSES:
        r = MEASURERS[name](carriers)
        fk = FRESHNESS_CARRIER.get(name)
        if fk and r["kind"] in ("measured", "measured_without_third_outcome"):
            key, rel, stamp_key = fk
            doc = carriers.get(key)
            r["freshness"] = freshness((doc or {}).get(stamp_key) if isinstance(doc, dict) else None,
                                       rel, slo, now)
        else:
            r["freshness"] = None
        out[name] = r
    tally = {k: sum(1 for r in out.values() if r["kind"] == k) for k in CLASS_KINDS}
    return {"classes": out, "tally": tally, "declared": OWNER_CLASSES_DECLARED,
            "measured": sum(1 for r in out.values() if r["kind"] in MEASURED_KINDS)}


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], classes: Dict[str, Any]
              ) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    rows = classes.get("classes") or {}
    for name, r in rows.items():
        k = r["kind"]
        if k == UNMEASURED:
            unmeasured.append(f"класс «{name}»: {r.get('reason')}")
            continue
        if k == "measured":
            add("INFO", f"error_class_measured:{name}",
                f"«{name}»: население {r.get('population')}, ошибок {r.get('errors')}, третий исход есть")
        elif k == "measured_without_third_outcome":
            add("WARN", f"error_class_without_third_outcome:{name}",
                f"«{name}»: население {r.get('population')}, ошибок {r.get('errors')}, но «не проверено» "
                f"в носителе неотличимо от «ошибок нет» (инв. #17)")
        elif k == "signal_at_t0_only":
            add("WARN", f"error_class_signal_at_t0_only:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "forecast_and_fact_uncompared":
            add("CRITICAL", f"error_class_forecast_and_fact_uncompared:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "forecast_without_fact":
            add("CRITICAL", f"error_class_forecast_without_fact:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "absent":
            add("CRITICAL", f"error_class_absent:{name}", f"«{name}»: {r.get('reason')}")
        fr = r.get("freshness")
        if fr:
            if fr.get("fresh") is False:
                add("WARN", f"measurer_stale:{name}",
                    f"«{name}»: измеритель не бежал {fr['age_hours']} ч при SLO {fr['slo_hours']} ч "
                    f"(отметка {fr['stamp']}) — измеритель есть, ответ о мире, которого уже нет")
            elif fr.get("fresh") is None:
                unmeasured.append(f"свежесть измерителя «{name}»: {fr.get('reason')}")
        if name == "Risk Violation" and r.get("failing_today"):
            add("INFO", "risk_limit_failing_today",
                f"проверка дневных лимитов сегодня красна: {r['failing_today']}")
    measured = classes.get("measured")
    # Сводка — только по классам, чей род ИЗМЕРЕН: класс с нечитаемым носителем лежит в
    # `unmeasured`, и делать из него находку значило бы изготовить её из неизмеренного.
    missing = [n for n, r in rows.items() if r["kind"] not in MEASURED_KINDS and r["kind"] != UNMEASURED]
    if rows and measured is not None and missing:
        add("CRITICAL", "error_classes_declared_vs_measured",
            f"объявлено {classes['declared']} классов (слово владельца «Минимум» — это пол), "
            f"измеряется {measured}; без измерителя: "
            + ", ".join(f"«{n}»→{rows[n]['kind']}" for n in missing))
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §32. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir)
    slo = load_slo(root)
    classes = measure_classes(carriers, slo, stamped)
    findings, unmeasured = _findings(parity_r, classes)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "error_class_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §32 ТЗ «Portfolio CIO» (ошибки, которые необходимо "
                     "измерять). Реплей, судью, запись, трек, лимиты и триггер НЕ трогает; карточку "
                     "владельцу не заводит — измерители есть advisory-слой, работа агента"),
        "overall": overall,
        "counts": counts,
        "declared": {"classes": list(OWNER_CLASSES), "classes_declared": OWNER_CLASSES_DECLARED,
                     "floor_word": OWNER_FLOOR_WORD, "declared_is_floor": True,
                     "order_g965_named": dict(ORDER_G965_NAMED),
                     "class_kinds": list(CLASS_KINDS), "measured_kinds": list(MEASURED_KINDS),
                     "slo_source": MANIFEST_REL},
        "parity": parity_r,
        "classes": classes,
        "carriers_read": {k: (carriers.get(k) is not None)
                          for k in ("records", "daily", "eval", "replay", "forecast",
                                    "limits", "blocks", "trigger")},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path): перестановка у §26 оставляла прибор без артефакта.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§32 ТЗ «Portfolio CIO» (ошибки, которые необходимо измерять): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (классов {OWNER_CLASSES_DECLARED}, слово «Минимум» на месте; "
              f"заказ G965 назвал {ORDER_G965_NAMED['classes']}, сдвиг {p.get('order_undercount')})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    cl = doc["classes"]
    print(f"   классов объявлено {cl.get('declared')}, измеряется {cl.get('measured')}; роды {cl.get('tally')}")
    for name, r in (cl.get("classes") or {}).items():
        fr = r.get("freshness") or {}
        fresh = ("" if not fr else
                 f" · свежесть {'OK' if fr.get('fresh') else 'УСТАРЕЛ' if fr.get('fresh') is False else 'не измерена'}"
                 f" ({fr.get('age_hours')} ч / SLO {fr.get('slo_hours')} ч)")
        print(f"      «{name}»: {r['kind']} — носителей {len(r.get('carriers') or [])}, "
              f"население {r.get('population')}, ошибок {r.get('errors')}{fresh}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§32 ТЗ «Portfolio CIO»: у КАЖДОГО из семи классов ошибок есть ли измеритель "
                    "с населением и третьим исходом")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(ns.data_dir if ns.data_dir else ns.root, who="error_class_census")
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
