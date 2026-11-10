"""portfolio_kpi_census.py — §33 ТЗ «Portfolio CIO»: «Portfolio KPIs».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §33::

    Portfolio KPIs
    Ввести измеримые метрики Portfolio CIO.
    Минимум:
    Gross Portfolio APY · Net Portfolio APY · Realized Portfolio Yield ·
    Optimal Policy-Compliant APY · Yield Gap · Transaction Cost Drag · Portfolio Turnover ·
    False Rebalance Rate · Missed Opportunity Cost · Forecast Accuracy · Average Break-even ·
    Risk Policy Violations
    Особенно важен:
    Yield Gap = Optimal Policy-Compliant Expected APY − Current Expected APY
    Это показывает, сколько доходности теряет текущая аллокация.

KPI **ДВЕНАДЦАТЬ**, слово владельца «Минимум:» означает ПОЛ, а не потолок; один KPI
выделен владельцем словами «Особенно важен:» и задан ФОРМУЛОЙ — прибор сверяет и перечень,
и выделение, и оба члена формулы.

Предмет — «у КАЖДОГО KPI есть ПРОИЗВОДИТЕЛЬ: носитель, который публикует это число под именем
владельца (или однозначным синонимом), с населением, родом числа и третьим исходом», а не «есть
ли дашборд». Разница существенна, и ради неё у KPI ШЕСТЬ родов, а не два:

* ``produced`` — число опубликовано носителем под именем владельца/однозначным синонимом,
  население названо, род числа объявлен (замер · ожидание T0 · контрфакт), «не измерено»
  отличимо от «ноль» (инв. #17);
* ``produced_without_third_outcome`` — число и население есть, но «не измерено» в носителе
  неотличимо от «ноль»;
* ``produced_under_other_name`` — число есть и честно, но ни один носитель не называет его
  именем владельца и не объявляет род (gross/net, ожидание/замер): читатель, ищущий KPI по
  имени владельца, его не найдёт (урок ADR-488: материал лежал в одном поле от читателя);
* ``lower_bound_of_declared`` — число под именем владельца ЕСТЬ, но по построению это НИЖНЯЯ
  ГРАНИЦА объявленного, и носитель этого не говорит. Так устроен «оптимум»: поиск
  ``trim_optimum`` перебирает ПОДМНОЖЕСТВА ног предложения (ADR-859, докстринг модуля:
  «НИЖНЯЯ ГРАНИЦА, а не оптимум»), значит ``target_apy_pp`` ≤ оптимума и
  ``gain_pp = target − book`` ≤ Yield Gap владельца. Число, которое читается как «сколько
  теряет аллокация», на деле говорит «теряет НЕ МЕНЬШЕ»;
* ``components_not_composed`` — слагаемые лежат в носителях (стоимость в долларах по дням,
  оборот по дням, окупаемость по записям), а само число владельца (drag в годовых пп,
  оборот за окно, средняя окупаемость) не складывает никто;
* ``absent`` — ни числа, ни слагаемых.

🪤 ЛОВУШКА, ради которой различаются ``produced`` и ``lower_bound_of_declared``
=============================================================================
Запись советника несёт ``book_apy_pp``, ``target_apy_pp`` и ``gain_pp``; слой владельца
(``cio_brief.OWNER_NUMBER_FIELDS``) печатает их как ``current_apy_pp`` / ``optimal_apy_pp`` /
``yield_gap_pp``. Формула владельца соблюдена АРИФМЕТИЧЕСКИ (прибор сверяет ``gain == target −
book`` на каждой записи), и замер «по наличию поля» сказал бы «Yield Gap измеряется». Но
уменьшаемое — не оптимум, а лучший ДОПУСТИМЫЙ кандидат, найденный ограниченным перебором;
и на книгах Balanced/Aggressive цель равна держимой книге в >98 % записей (ADR-765:
``target_is_the_held_book``), то есть «разрыв 0» там — не измерение разрыва, а его отсутствие
по построению. Оба факта прибор НАЗЫВАЕТ раздельно.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): ни один KPI не ВЫЧИСЛЯЕТ заново — витрина, реплей, судья,
запись, трек, снимок трека и лимиты не правятся ни байтом, и прибор не становится третьим
местом для чисел (`.claude/rules/site-numbers.md`). Карточку владельцу не заводит: производители
KPI — advisory-слой, работа агента. Контрапункты ВВЕЗЕНЫ, не перемерены: роды чисел витрины
(ADR-365/580), реплей §38 (ADR-220, колонки ``gross_apy_pct``/``net_apy_pct`` по рукам),
прибор §32 (ADR-978 — его носители читаются ЕГО дверью, своей копии нет), §31 (ADR-977),
нижняя граница поиска (ADR-859), самосравнение цели (ADR-765), снимок трека (ADR-580 §C2).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import error_class_census as ecc
from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/portfolio_kpi_census.json"
CARD_REL = smc.CARD_REL
MANIFEST_REL = ecc.MANIFEST_REL

# ───────────────────────────── дословное требование ───────────────────────────
SECTION_HEAD = "33. Portfolio KPIs"
NEXT_SECTION_HEAD = "34. Daily Report"
OWNER_FLOOR_WORD = "Минимум:"
OWNER_EMPHASIS_WORD = "Особенно важен:"
OWNER_KPIS: Tuple[str, ...] = (
    "Gross Portfolio APY",
    "Net Portfolio APY",
    "Realized Portfolio Yield",
    "Optimal Policy-Compliant APY",
    "Yield Gap",
    "Transaction Cost Drag",
    "Portfolio Turnover",
    "False Rebalance Rate",
    "Missed Opportunity Cost",
    "Forecast Accuracy",
    "Average Break-even",
    "Risk Policy Violations",
)
#: Число ОБЪЯВЛЕНО и краснеет тестом (урок §22/§23/§30: заказ назвал меньше, чем владелец).
OWNER_KPIS_DECLARED = 12
#: KPI, выделенный владельцем словами «Особенно важен:», и оба члена его формулы.
OWNER_EMPHASIS = "Yield Gap"
OWNER_FORMULA_TERMS: Tuple[str, str] = ("Optimal Policy-Compliant Expected APY", "Current Expected APY")
#: Заказ G966 п. 1 числа KPI НЕ называл («пересчитать входы своим глазом») — сдвиг не применим,
#: хвост прочитан. Печатается, чтобы «не назвал» было отличимо от «назвал верно».
ORDER_G966_NAMED: Dict[str, Any] = {"kpis": None, "emphasis_named": False, "tail_read": True}

# ───────────────────────────── словарь родов ──────────────────────────────────
KPI_KINDS: Tuple[str, ...] = (
    "produced",
    "produced_without_third_outcome",
    "produced_under_other_name",
    "lower_bound_of_declared",
    "components_not_composed",
    "absent",
    UNMEASURED,
)
#: Роды, при которых KPI считается ПРОИЗВОДИМЫМ в смысле §33.
PRODUCED_KINDS: Tuple[str, ...] = ("produced",)
#: Род ЧИСЛА (ADR-580 §C2 — пять родов витрины; здесь три, которыми живут KPI CIO).
NUMBER_REALISED = "замер"
NUMBER_EXPECTED_T0 = "ожидание T0 (из живых ставок, modelled)"
NUMBER_COUNTERFACTUAL = "контрфакт (реплей, modelled)"

#: Носители прибора §32 — ЕГО дверью (своей копии имён нет).
REPLAY_REL = ecc.REPLAY_REL
EVAL_REL = ecc.EVAL_REL
RECORD_REL = ecc.RECORD_REL
TRACK_REL = ecc.TRACK_REL
FORECAST_REL = ecc.FORECAST_REL
LIMITS_REL = ecc.LIMITS_REL
BLOCKS_REL = ecc.BLOCKS_REL
#: Записи советника ДРУГИХ книг (ADR-125): у них свой журнал, одна форма.
BOOK_RECORD_RELS: Dict[str, str] = {
    "conservative": RECORD_REL,
    "balanced": "allocation_rationale_history_balanced.jsonl",
    "aggressive": "allocation_rationale_history_aggressive.jsonl",
}
#: Снимок трека и витрина чисел — от КОРНЯ дерева, не от data/ (ADR-365: один адрес чтения).
SNAPSHOT_REL = "landing/src/data/track_snapshot.json"
SHELF_REL = "landing/src/data/site_numbers.json"
#: Модуль поиска «оптимума» и слова, которыми он САМ объявляет род своего ответа (ADR-859).
OPTIMUM_SEARCH_REL = "spa_core/paper_trading/trim_optimum.py"
OPTIMUM_LOWER_BOUND_WORDS = "НИЖНЯЯ ГРАНИЦА"
#: Рука реплея, отвечающая за ТЕКУЩУЮ аллокацию, и рука CIO-«оптимума».
REPLAY_CURRENT_ARM = "current"
REPLAY_OPT_ARM = "cio_opt"
#: Допуск арифметики формулы владельца на записи (пп годовой ставки).
FORMULA_TOLERANCE_PP = 1e-4
#: Доля записей книги с целью, РАВНОЙ держимой книге, с которой «разрыв 0» становится
#: свойством конструкции, а не измерением (ADR-765: 706 из 725).
SELF_COMPARED_SHARE_WARN = 0.5
#: Значение судьи «не проверено» и состояние снимка «измерено» — чужие словари, одна копия.
JUDGE_UNCHECKED = ecc.JUDGE_UNCHECKED
SNAPSHOT_MEASURED = "MEASURED"


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


def _items_between(body: List[str], lead: str, stops: Tuple[str, ...]) -> Optional[List[str]]:
    """Пункты после строки ``lead`` до любой из ``stops``, «⸻» или конца раздела.
    HTML-комментарии карточки (`<!-- источник … -->`) — не пункты владельца."""
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if s == "⸻" or s in stops:
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
    emphasis = _items_between(body, OWNER_EMPHASIS_WORD, ())
    return {
        "measured": True,
        "kpis": _items_between(body, OWNER_FLOOR_WORD, (OWNER_EMPHASIS_WORD,)),
        "floor_word_present": OWNER_FLOOR_WORD in stripped,
        "emphasis": emphasis[0] if emphasis else None,
        "formula_terms_present": [t for t in OWNER_FORMULA_TERMS if t in stripped],
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None,
                           "order_tail_read": ORDER_G966_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    kpis = parsed["kpis"]
    # Пункты читаются ПОСЛЕ слова «Минимум:», поэтому «слова нет» и «пунктов нет» — одна
    # проверка (урок SMC-978 M02: раздельная вторая выживала мутацией).
    if kpis is None:
        mism.append(f"в разделе нет слова владельца {OWNER_FLOOR_WORD!r} — перечень не объявлен "
                    f"полом, пункты не прочитаны")
    elif list(kpis) != list(OWNER_KPIS):
        mism.append(f"KPI карточки {kpis} ≠ константам {list(OWNER_KPIS)}")
    if parsed.get("emphasis") != OWNER_EMPHASIS:
        mism.append(f"после {OWNER_EMPHASIS_WORD!r} в карточке {parsed.get('emphasis')!r}, "
                    f"константа {OWNER_EMPHASIS!r}")
    if list(parsed.get("formula_terms_present") or []) != list(OWNER_FORMULA_TERMS):
        mism.append(f"члены формулы владельца в карточке {parsed.get('formula_terms_present')} ≠ "
                    f"константам {list(OWNER_FORMULA_TERMS)}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if kpis is not None and ORDER_G966_NAMED["kpis"] is not None:
        out["order_undercount"] = {"kpis": len(kpis) - int(ORDER_G966_NAMED["kpis"])}
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Запись/трек/судья/реплей/прогноз/лимиты/блоки — дверью §32; записи других книг, снимок
    трека, витрина и модуль поиска — своими (у §32 их не было)."""
    out = ecc.load_carriers(data_dir)
    d = Path(data_dir)
    books: Dict[str, Optional[List[dict]]] = {}
    books_reason: Dict[str, Optional[str]] = {}
    for book, rel in BOOK_RECORD_RELS.items():
        if rel == RECORD_REL:
            books[book], books_reason[book] = out.get("records"), out.get("records_reason")
            continue
        rows, why, _corrupt = smc._read_jsonl(d / rel)
        books[book], books_reason[book] = rows, why
    out["books"], out["books_reason"] = books, books_reason
    for key, rel in (("snapshot", SNAPSHOT_REL), ("shelf", SHELF_REL)):
        doc, why = smc._read_json(Path(root) / rel)
        ok = isinstance(doc, dict)
        out[key] = doc if ok else None
        out[f"{key}_reason"] = why if doc is None else (None if ok else f"{rel} не словарь")
    text, why = smc._read_text(os.path.join(root, OPTIMUM_SEARCH_REL))
    out["optimum_search_text"], out["optimum_search_reason"] = text, why
    return out


def freshness_at(stamp: object, manifest_path: str, slo: Dict[str, Optional[float]],
                 now: dt.datetime) -> Dict[str, Any]:
    """Возраст носителя против SLO манифеста по ПОЛНОМУ пути артефакта (носители §33 живут не
    только в data/). Три исхода: свеж · устарел · не измерен — последнее НЕ есть «свеж»."""
    ts = ecc._parse_ts(stamp)
    slo_h = slo.get(manifest_path)
    if ts is None:
        return {"stamp": stamp, "age_hours": None, "slo_hours": slo_h, "fresh": None,
                "reason": "отметка времени носителя не прочитана"}
    age = round((now - ts).total_seconds() / 3600.0, 2)
    if slo_h is None:
        return {"stamp": ts.isoformat(), "age_hours": age, "slo_hours": None, "fresh": None,
                "reason": f"SLO для {manifest_path} в манифесте не объявлен"}
    return {"stamp": ts.isoformat(), "age_hours": age, "slo_hours": slo_h,
            "fresh": age <= slo_h, "reason": None}


def _carrier(name: str, role: str, **extra: Any) -> Dict[str, Any]:
    c: Dict[str, Any] = {"carrier": name, "role": role}
    c.update(extra)
    return c


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _replay_arm_rates(carriers: Dict[str, Any], rate_key: str, arm: str
                      ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Ставка ``rate_key`` руки ``arm`` в обеих колонках реплея (charged/observed) + население
    и третий исход реплея. Колонки — объявленный РОД стоимости, а не два мнения."""
    replay = carriers.get("replay")
    if replay is None:
        return None, f"реплей {REPLAY_REL} не прочитан: {carriers.get('replay_reason')}"
    comp = replay.get("comparison")
    if not isinstance(comp, dict) or not comp:
        return None, f"у реплея {REPLAY_REL} нет словаря comparison"
    values: Dict[str, Any] = {}
    for col, block in comp.items():
        rates = block.get(rate_key) if isinstance(block, dict) else None
        if isinstance(rates, dict) and _num(rates.get(arm)):
            values[col] = rates[arm]
    if not values:
        return None, f"в comparison реплея нет {rate_key!r} для руки {arm!r}"
    pop = replay.get("population") if isinstance(replay.get("population"), dict) else {}
    third = {k: pop.get(k) for k in ("unpriced_per_arm",) if k in pop}
    if "unchecked" in replay:
        third["unchecked"] = replay.get("unchecked")
    return {"values": values, "columns": sorted(values),
            "population": pop.get("common_scored_days"),
            "days_observed": pop.get("days_observed"),
            "third_outcome_present": bool(third), "third_outcome": third,
            "number_kind": NUMBER_COUNTERFACTUAL}, None


def _record_rows(carriers: Dict[str, Any], key: str) -> Tuple[List[dict], int]:
    recs = carriers.get("records") or []
    rows = [r for r in recs if isinstance(r, dict)]
    return rows, sum(1 for r in rows if _num(r.get(key)))


def _kind_from_carriers(cs: List[Dict[str, Any]]) -> str:
    kinds = [c.get("kind") for c in cs]
    for k in ("produced", "produced_without_third_outcome", "produced_under_other_name"):
        if k in kinds:
            return k
    return UNMEASURED


def _best(cs: List[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    return next((c for c in cs if c.get("kind") == kind), cs[0])


# ───────────────────────────── KPI ───────────────────────────────────────────

def _measure_portfolio_rate(carriers: Dict[str, Any], rate_key: str, owner_name: str
                            ) -> Dict[str, Any]:
    """Gross/Net Portfolio APY: реплей несёт их под однозначным именем по руке «current»
    (контрфакт на общем окне); запись и трек несут ОЖИДАНИЕ T0 без слова gross/net."""
    cs: List[Dict[str, Any]] = []
    arm, why = _replay_arm_rates(carriers, rate_key, REPLAY_CURRENT_ARM)
    if arm is not None:
        cs.append(_carrier(f"{REPLAY_REL}:comparison.*.{rate_key}.{REPLAY_CURRENT_ARM}", "named",
                           kind="produced" if arm["third_outcome_present"]
                           else "produced_without_third_outcome", **arm))
    rows, n_apy = _record_rows(carriers, "book_apy_pp")
    if rows:
        cs.append(_carrier(f"{RECORD_REL}:book_apy_pp", "expected_t0", population=len(rows),
                           rows_with_value=n_apy, number_kind=NUMBER_EXPECTED_T0,
                           third_outcome_present=any("apy_unevidenced" in r for r in rows),
                           gross_net_declared=False, kind="produced_under_other_name"))
    daily = carriers.get("daily")
    if daily is not None:
        with_v = [d for d in daily if isinstance(d, dict) and _num(d.get("apy_expected_pct"))]
        cs.append(_carrier(f"{TRACK_REL}:daily.apy_expected_pct", "expected_t0",
                           population=len(daily), rows_with_value=len(with_v),
                           number_kind=NUMBER_EXPECTED_T0, gross_net_declared=False,
                           kind="produced_under_other_name"))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"{why}; запись: {carriers.get('records_reason')}; "
                                              f"трек: {carriers.get('daily_reason')}", "carriers": []}
    kind = _kind_from_carriers(cs)
    best = _best(cs, kind)
    reason = (None if kind == "produced" else
              f"«{owner_name}» нет ни под своим именем, ни под однозначным синонимом; "
              f"ожидание T0 в записи/треке не говорит, gross оно или net" if kind != UNMEASURED
              else why)
    return {"kind": kind, "reason": reason, "carriers": cs,
            "population": best.get("population"), "value": best.get("values"),
            "number_kind": best.get("number_kind")}


def measure_gross_apy(carriers: Dict[str, Any]) -> Dict[str, Any]:
    return _measure_portfolio_rate(carriers, "gross_apy_pct", "Gross Portfolio APY")


def measure_net_apy(carriers: Dict[str, Any]) -> Dict[str, Any]:
    return _measure_portfolio_rate(carriers, "net_apy_pct", "Net Portfolio APY")


def measure_realized_yield(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Снимок трека: доходность за период, годовой эквивалент, метод, дни, состояние —
    ЕДИНЫЙ производитель (ADR-580 §C2); витрина несёт то же число с родом «замер»."""
    cs: List[Dict[str, Any]] = []
    snap = carriers.get("snapshot")
    if snap is not None:
        tp = snap.get("track_period") if isinstance(snap.get("track_period"), dict) else None
        if tp is not None:
            period = tp.get("period") if isinstance(tp.get("period"), dict) else {}
            state = tp.get("state")
            cs.append(_carrier(f"{SNAPSHOT_REL}:track_period", "named",
                               state=state, period_return_pct=tp.get("period_return_pct"),
                               annualised_equivalent_pct=tp.get("annualised_equivalent_pct"),
                               annualised_formula=tp.get("annualised_formula"),
                               population=period.get("evidenced_bars"),
                               days_act=period.get("days_act"), number_kind=NUMBER_REALISED,
                               third_outcome_present=state is not None,
                               third_outcome_key="track_period.state≠MEASURED",
                               kind=("produced" if state == SNAPSHOT_MEASURED and
                                     _num(tp.get("period_return_pct")) else
                                     UNMEASURED if state is not None and state != SNAPSHOT_MEASURED
                                     else "produced_without_third_outcome"),
                               reason=(None if state == SNAPSHOT_MEASURED else
                                       f"снимок сам говорит state={state!r}")))
        else:
            cs.append(_carrier(f"{SNAPSHOT_REL}:paper_apy_pct", "named",
                               value=snap.get("paper_apy_pct"), number_kind=NUMBER_REALISED,
                               third_outcome_present=False, population=snap.get("real_track_days"),
                               kind="produced_without_third_outcome" if _num(snap.get("paper_apy_pct"))
                               else UNMEASURED, reason=None if _num(snap.get("paper_apy_pct"))
                               else "в снимке нет ни track_period, ни paper_apy_pct"))
    shelf = carriers.get("shelf")
    if shelf is not None:
        head = shelf.get("headline") if isinstance(shelf.get("headline"), dict) else {}
        fig = head.get("apy") if isinstance(head.get("apy"), dict) else None
        if fig is not None:
            cs.append(_carrier(f"{SHELF_REL}:headline.apy", "named", kind_declared=fig.get("kind"),
                               value=fig.get("value"), window_days=fig.get("window_days"),
                               reportable=fig.get("reportable"), number_kind=fig.get("kind"),
                               third_outcome_present="reportable" in fig,
                               kind="produced" if fig.get("kind") and "reportable" in fig
                               else "produced_without_third_outcome"))
    daily = carriers.get("daily")
    if daily is not None:
        cs.append(_carrier(f"{TRACK_REL}:daily", "raw_observation", population=len(daily),
                           number_kind=NUMBER_REALISED, kind="produced_under_other_name",
                           annualised=False))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"снимок: {carriers.get('snapshot_reason')}; "
                                              f"витрина: {carriers.get('shelf_reason')}; "
                                              f"трек: {carriers.get('daily_reason')}", "carriers": []}
    kind = _kind_from_carriers(cs)
    best = _best(cs, kind)
    return {"kind": kind, "reason": None if kind == "produced" else "; ".join(
        str(c.get("reason")) for c in cs if c.get("reason")) or None, "carriers": cs,
        "population": best.get("population"), "number_kind": best.get("number_kind"),
        "value": best.get("annualised_equivalent_pct", best.get("value"))}


def optimum_search_kind(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Какого рода ответ поиска «оптимума» — спрашивается у САМОГО модуля (ADR-859), а не
    предполагается: модуль перестал звать себя нижней границей ⇒ род НЕ ИЗМЕРЕН, а не «оптимум»."""
    text = carriers.get("optimum_search_text")
    if text is None:
        return {"kind": UNMEASURED,
                "reason": f"модуль поиска {OPTIMUM_SEARCH_REL} не прочитан: "
                          f"{carriers.get('optimum_search_reason')}"}
    head = text.split('"""', 2)
    doc = head[1] if len(head) >= 2 else ""
    if OPTIMUM_LOWER_BOUND_WORDS in doc:
        return {"kind": "lower_bound_of_declared",
                "reason": (f"модуль поиска {OPTIMUM_SEARCH_REL} сам объявляет свой ответ "
                           f"«{OPTIMUM_LOWER_BOUND_WORDS}, а не оптимум» (ADR-859): перебираются "
                           f"подмножества ног предложения, раскладка внутри фиксирована спредом")}
    return {"kind": UNMEASURED,
            "reason": (f"докстринг {OPTIMUM_SEARCH_REL} больше не объявляет род своего ответа "
                       f"словами «{OPTIMUM_LOWER_BOUND_WORDS}» — оптимум это или нижняя граница, "
                       f"не измерено; перемерить, а не считать оптимумом")}


def measure_optimal_apy(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    rows, n = _record_rows(carriers, "target_apy_pp")
    search = optimum_search_kind(carriers)
    if rows:
        cs.append(_carrier(f"{RECORD_REL}:target_apy_pp", "named_via_cio_brief",
                           population=len(rows), rows_with_value=n, number_kind=NUMBER_EXPECTED_T0,
                           owner_facing_key="optimal_apy_pp", search_kind=search["kind"],
                           lower_bound_declared_in_carrier=False))
    arm, _ = _replay_arm_rates(carriers, "gross_apy_pct", REPLAY_OPT_ARM)
    if arm is not None:
        cs.append(_carrier(f"{REPLAY_REL}:comparison.*.gross_apy_pct.{REPLAY_OPT_ARM}", "named",
                           search_kind=search["kind"], **arm))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"запись: {carriers.get('records_reason')}; "
                                              f"реплей: {carriers.get('replay_reason')}",
                "carriers": [], "search": search}
    if search["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": search["reason"], "carriers": cs, "search": search,
                "population": cs[0].get("population")}
    return {"kind": "lower_bound_of_declared",
            "reason": ("«Optimal Policy-Compliant APY» печатается из target_apy_pp (owner-facing "
                       "optimal_apy_pp), а цель — лучший ДОПУСТИМЫЙ кандидат ограниченного перебора: "
                       + search["reason"] + "; носитель об этом не говорит"),
            "carriers": cs, "search": search, "population": cs[0].get("population"),
            "number_kind": NUMBER_EXPECTED_T0}


def _self_compared(rows: List[dict]) -> Dict[str, Any]:
    """Сколько записей книги сравнивают книгу С САМОЙ СОБОЙ (цель == держимое, ADR-765)."""
    judged = [r for r in rows if isinstance(r.get("current_positions"), dict)
              and isinstance(r.get("target_positions"), dict)]
    same = sum(1 for r in judged if r["current_positions"] == r["target_positions"])
    zero = sum(1 for r in rows if r.get("gain_pp") == 0)
    return {"rows": len(rows), "judged": len(judged), "self_compared": same, "gain_zero": zero,
            "share": round(same / len(judged), 4) if judged else None}


def formula_parity(rows: List[dict]) -> Dict[str, Any]:
    """Формула владельца на записи: gain == target − book (в допуске). Три исхода у строки:
    сходится · расходится · не судима (поля не числа)."""
    agree = disagree = unjudged = 0
    for r in rows:
        g, t, b = r.get("gain_pp"), r.get("target_apy_pp"), r.get("book_apy_pp")
        if not (_num(g) and _num(t) and _num(b)):
            unjudged += 1
        elif abs(float(g) - (float(t) - float(b))) <= FORMULA_TOLERANCE_PP:
            agree += 1
        else:
            disagree += 1
    return {"agree": agree, "disagree": disagree, "unjudged": unjudged,
            "tolerance_pp": FORMULA_TOLERANCE_PP}


def measure_yield_gap(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    books = carriers.get("books") or {}
    per_book: Dict[str, Any] = {}
    for book, rows in books.items():
        if rows is None:
            per_book[book] = {"kind": UNMEASURED,
                              "reason": (carriers.get("books_reason") or {}).get(book)}
            continue
        rows = [r for r in rows if isinstance(r, dict)]
        n = sum(1 for r in rows if _num(r.get("gain_pp")))
        per_book[book] = {"population": len(rows), "rows_with_value": n,
                          "formula": formula_parity(rows), "self_compared": _self_compared(rows)}
        cs.append(_carrier(f"{BOOK_RECORD_RELS[book]}:gain_pp", "named_via_cio_brief", book=book,
                           population=len(rows), rows_with_value=n, number_kind=NUMBER_EXPECTED_T0,
                           owner_facing_key="yield_gap_pp",
                           third_outcome_key="cio_brief.numbers_missing / apy_unevidenced",
                           third_outcome_present=any("apy_unevidenced" in r for r in rows)))
    arm, _ = _replay_arm_rates(carriers, "gross_apy_pct", REPLAY_OPT_ARM)
    replay = carriers.get("replay")
    if arm is not None and isinstance(replay, dict):
        comp = replay.get("comparison") or {}
        spread = {col: blk.get("opt_minus_current_pp") for col, blk in comp.items()
                  if isinstance(blk, dict) and _num(blk.get("opt_minus_current_pp"))}
        if spread:
            cs.append(_carrier(f"{REPLAY_REL}:comparison.*.opt_minus_current_pp", "named",
                               values=spread, population=arm.get("population"),
                               number_kind=NUMBER_COUNTERFACTUAL,
                               third_outcome_present=arm["third_outcome_present"]))
    search = optimum_search_kind(carriers)
    if not cs:
        return {"kind": UNMEASURED, "reason": f"записи книг: {carriers.get('books_reason')}; "
                                              f"реплей: {carriers.get('replay_reason')}",
                "carriers": [], "per_book": per_book, "search": search}
    if search["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": search["reason"], "carriers": cs,
                "per_book": per_book, "search": search}
    cons = per_book.get("conservative") or {}
    return {"kind": "lower_bound_of_declared",
            "reason": ("Yield Gap = target_apy_pp − book_apy_pp сходится с формулой владельца "
                       "арифметически, но уменьшаемое — нижняя граница оптимума (" + search["reason"]
                       + "); число читается как «сколько теряет аллокация», а говорит «теряет НЕ "
                       "МЕНЬШЕ»; носитель об этом не говорит"),
            "carriers": cs, "per_book": per_book, "search": search,
            "population": cons.get("population"), "number_kind": NUMBER_EXPECTED_T0}


def measure_cost_drag(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Стоимость — в долларах по записям (оценка T0), по дням трека и за период в снимке;
    drag как ГОДОВЫЕ пп капитала не считает никто. В реплее gross − net есть drag по рукам,
    но разность не печатается ни одним ключом."""
    cs: List[Dict[str, Any]] = []
    rows, n = _record_rows(carriers, "cost_usd")
    if rows:
        cs.append(_carrier(f"{RECORD_REL}:cost_usd", "component_usd_t0", population=len(rows),
                           rows_with_value=n, number_kind=NUMBER_EXPECTED_T0))
    daily = carriers.get("daily")
    if daily is not None:
        with_c = [d for d in daily if isinstance(d, dict) and _num(d.get("cost_usd"))]
        cs.append(_carrier(f"{TRACK_REL}:daily.cost_usd", "component_usd_realised",
                           population=len(daily), rows_with_value=len(with_c),
                           rows_without_column=len(daily) - len(with_c),
                           sum_usd=round(sum(float(d["cost_usd"]) for d in with_c), 2),
                           number_kind=NUMBER_REALISED, annualised_by=None))
    snap = carriers.get("snapshot")
    tp = (snap or {}).get("track_period") if isinstance(snap, dict) else None
    if isinstance(tp, dict) and _num(tp.get("costs_paid_usd")):
        cs.append(_carrier(f"{SNAPSHOT_REL}:track_period.costs_paid_usd", "component_usd_realised",
                           value=tp.get("costs_paid_usd"), number_kind=NUMBER_REALISED,
                           annualised_by=None))
    g, _ = _replay_arm_rates(carriers, "gross_apy_pct", REPLAY_CURRENT_ARM)
    nt, _ = _replay_arm_rates(carriers, "net_apy_pct", REPLAY_CURRENT_ARM)
    if g is not None and nt is not None:
        cs.append(_carrier(f"{REPLAY_REL}:comparison.*.(gross−net).{REPLAY_CURRENT_ARM}",
                           "components_in_one_carrier", columns=g["columns"],
                           population=g.get("population"), number_kind=NUMBER_COUNTERFACTUAL,
                           difference_printed_by=None))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"запись: {carriers.get('records_reason')}; "
                                              f"трек: {carriers.get('daily_reason')}; "
                                              f"реплей: {carriers.get('replay_reason')}", "carriers": []}
    return {"kind": "components_not_composed",
            "reason": ("стоимость лежит долларами (оценка T0 в записи, факт по дням трека и за период "
                       "в снимке) и парой gross/net по рукам реплея; «drag» как годовые пп капитала "
                       "не складывает и не печатает никто"),
            "carriers": cs, "population": None, "number_kind": None}


def measure_turnover(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    daily = carriers.get("daily")
    if daily is not None:
        with_t = [d for d in daily if isinstance(d, dict) and _num(d.get("turnover_usd"))]
        cs.append(_carrier(f"{TRACK_REL}:daily.turnover_usd", "component_usd_realised",
                           population=len(daily), rows_with_value=len(with_t),
                           rows_without_column=len(daily) - len(with_t),
                           sum_usd=round(sum(float(d["turnover_usd"]) for d in with_t), 2),
                           number_kind=NUMBER_REALISED, rate_over_window_by=None))
    rows, n = _record_rows(carriers, "turnover_usd")
    if rows:
        cs.append(_carrier(f"{RECORD_REL}:turnover_usd/turnover_frac", "component_usd_t0",
                           population=len(rows), rows_with_value=n, number_kind=NUMBER_EXPECTED_T0,
                           proposed_not_realised=True))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"трек: {carriers.get('daily_reason')}; "
                                              f"запись: {carriers.get('records_reason')}", "carriers": []}
    return {"kind": "components_not_composed",
            "reason": ("оборот лежит долларами по дням трека (у части дней колонки нет вовсе — "
                       "отсутствие неотличимо от нуля) и ПРЕДЛОЖЕННЫМ оборотом в записи; оборот "
                       "портфеля за окно (доля капитала за период) не складывает никто"),
            "carriers": cs, "population": None, "number_kind": None}


def measure_false_rebalance_rate(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Числитель и знаменатель — в ОДНОМ блоке реплея с третьим исходом (§32 «измеряется»)."""
    r = ecc.measure_false_rebalance(carriers)
    if r["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": r.get("reason"), "carriers": r.get("carriers") or []}
    kind = {"measured": "produced",
            "measured_without_third_outcome": "produced_without_third_outcome"}.get(r["kind"], r["kind"])
    pop, hits = r.get("population"), r.get("errors")
    return {"kind": kind, "reason": None if kind == "produced" else r.get("reason"),
            "carriers": r.get("carriers") or [],
            "population": pop, "numerator": hits,
            "value": (round(hits / pop, 4) if _num(pop) and _num(hits) and pop else None),
            "number_kind": NUMBER_COUNTERFACTUAL}


def measure_missed_opportunity_cost(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Стоимость упущенного — долларами на строку судьи (``missed_usd``) с третьим исходом
    ``counterfactual=UNCHECKED``; агрегат — у реплея (§32 «измеряется»)."""
    r = ecc.measure_missed_opportunity(carriers)
    if r["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": r.get("reason"), "carriers": r.get("carriers") or []}
    kind = {"measured": "produced",
            "measured_without_third_outcome": "produced_without_third_outcome"}.get(r["kind"], r["kind"])
    return {"kind": kind, "reason": None if kind == "produced" else r.get("reason"),
            "carriers": r.get("carriers") or [], "population": r.get("population"),
            "numerator": r.get("errors"), "number_kind": NUMBER_COUNTERFACTUAL}


def measure_forecast_accuracy(carriers: Dict[str, Any]) -> Dict[str, Any]:
    r = ecc.measure_apy_forecast_error(carriers)
    if r["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": r.get("reason"), "carriers": r.get("carriers") or []}
    fc = carriers.get("forecast") or {}
    mag = fc.get("magnitude") if isinstance(fc.get("magnitude"), dict) else {}
    kind = {"measured": "produced",
            "measured_without_third_outcome": "produced_without_third_outcome"}.get(r["kind"], r["kind"])
    return {"kind": kind, "reason": None if kind == "produced" else r.get("reason"),
            "carriers": r.get("carriers") or [], "population": r.get("population"),
            "sign_disagreements": r.get("errors"), "magnitude_median": mag.get("median"),
            "magnitude_n": mag.get("n"), "number_kind": NUMBER_COUNTERFACTUAL}


def measure_average_break_even(carriers: Dict[str, Any]) -> Dict[str, Any]:
    cs: List[Dict[str, Any]] = []
    rows, n = _record_rows(carriers, "payback_days")
    if rows:
        cs.append(_carrier(f"{RECORD_REL}:payback_days", "component_forecast_t0", population=len(rows),
                           rows_with_value=n, rows_without=len(rows) - n,
                           number_kind=NUMBER_EXPECTED_T0, averaged_by=None))
    block, _ = ecc._replay_block(carriers, "false_rebalances")
    if block is not None:
        worst = [w for w in (block.get("worst") or []) if isinstance(w, dict)]
        cs.append(_carrier(f"{REPLAY_REL}:false_rebalances.max_payback_days/worst[].payback_days",
                           "component_fact", threshold_days=block.get("max_payback_days"),
                           rows_listed=len(worst),
                           rows_with_fact=sum(1 for w in worst if _num(w.get("payback_days"))),
                           number_kind=NUMBER_COUNTERFACTUAL, averaged_by=None,
                           note="max_payback_days — ПОРОГ реплея, не среднее"))
    if not cs:
        return {"kind": UNMEASURED, "reason": f"запись: {carriers.get('records_reason')}; "
                                              f"реплей: {carriers.get('replay_reason')}", "carriers": []}
    return {"kind": "components_not_composed",
            "reason": ("окупаемость лежит прогнозом на запись (payback_days) и фактом у ≤5 худших "
                       "перекладок реплея; СРЕДНЮЮ окупаемость — ни прогнозную, ни фактическую — "
                       "не считает никто (max_payback_days реплея — порог, не среднее)"),
            "carriers": cs, "population": None, "number_kind": None}


def measure_risk_policy_violations(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Снимок лимитов (с SKIP) — производитель СЕГОДНЯШНЕГО счёта; журнал блоков —
    история без третьего исхода: запись появляется ТОЛЬКО при блоке, и «51 день без записи»
    неотличимо от «писатель молчит»."""
    r = ecc.measure_risk_violation(carriers)
    if r["kind"] == UNMEASURED:
        return {"kind": UNMEASURED, "reason": r.get("reason"), "carriers": r.get("carriers") or []}
    kind = {"measured": "produced",
            "measured_without_third_outcome": "produced_without_third_outcome"}.get(r["kind"], r["kind"])
    hist = next((c for c in r.get("carriers") or [] if c.get("shape") == "history"), None)
    return {"kind": kind, "reason": None if kind == "produced" else r.get("reason"),
            "carriers": r.get("carriers") or [], "population": r.get("population"),
            "numerator": r.get("errors"), "failing_today": r.get("failing_today"),
            "history": ({"rows": hist.get("population"), "with_violations": hist.get("hits"),
                         "last_date": hist.get("last_date"),
                         "third_outcome_present": hist.get("third_outcome_present")}
                        if hist else None),
            "number_kind": NUMBER_REALISED}


MEASURERS = {
    "Gross Portfolio APY": measure_gross_apy,
    "Net Portfolio APY": measure_net_apy,
    "Realized Portfolio Yield": measure_realized_yield,
    "Optimal Policy-Compliant APY": measure_optimal_apy,
    "Yield Gap": measure_yield_gap,
    "Transaction Cost Drag": measure_cost_drag,
    "Portfolio Turnover": measure_turnover,
    "False Rebalance Rate": measure_false_rebalance_rate,
    "Missed Opportunity Cost": measure_missed_opportunity_cost,
    "Forecast Accuracy": measure_forecast_accuracy,
    "Average Break-even": measure_average_break_even,
    "Risk Policy Violations": measure_risk_policy_violations,
}

#: Какой носитель задаёт свежесть производителя KPI: (ключ носителя, путь в манифесте, отметка).
FRESHNESS_CARRIER: Dict[str, Tuple[str, str, str]] = {
    "Gross Portfolio APY": ("replay", f"data/{REPLAY_REL}", "generated_at"),
    "Net Portfolio APY": ("replay", f"data/{REPLAY_REL}", "generated_at"),
    "Realized Portfolio Yield": ("snapshot", SNAPSHOT_REL, "generated_at"),
    "False Rebalance Rate": ("replay", f"data/{REPLAY_REL}", "generated_at"),
    "Missed Opportunity Cost": ("replay", f"data/{REPLAY_REL}", "generated_at"),
    "Forecast Accuracy": ("forecast", f"data/{FORECAST_REL}", "generated_at"),
    "Risk Policy Violations": ("limits", f"data/{LIMITS_REL}", "checked_at"),
}


def measure_kpis(carriers: Dict[str, Any], slo: Dict[str, Optional[float]],
                 now: dt.datetime) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in OWNER_KPIS:
        r = MEASURERS[name](carriers)
        fk = FRESHNESS_CARRIER.get(name)
        if fk and r["kind"] in ("produced", "produced_without_third_outcome"):
            key, path, stamp_key = fk
            doc = carriers.get(key)
            r["freshness"] = freshness_at((doc or {}).get(stamp_key) if isinstance(doc, dict)
                                          else None, path, slo, now)
        else:
            r["freshness"] = None
        out[name] = r
    tally = {k: sum(1 for r in out.values() if r["kind"] == k) for k in KPI_KINDS}
    return {"kpis": out, "tally": tally, "declared": OWNER_KPIS_DECLARED,
            "produced": sum(1 for r in out.values() if r["kind"] in PRODUCED_KINDS),
            "emphasis": OWNER_EMPHASIS, "emphasis_kind": out[OWNER_EMPHASIS]["kind"]}


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], kpis: Dict[str, Any]
              ) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    rows = kpis.get("kpis") or {}
    for name, r in rows.items():
        k = r["kind"]
        if k == UNMEASURED:
            unmeasured.append(f"KPI «{name}»: {r.get('reason')}")
            continue
        if k == "produced":
            add("INFO", f"kpi_produced:{name}",
                f"«{name}»: производитель {r['carriers'][0].get('carrier')}, население "
                f"{r.get('population')}, род числа «{r.get('number_kind')}», третий исход есть")
        elif k == "produced_without_third_outcome":
            add("WARN", f"kpi_without_third_outcome:{name}",
                f"«{name}»: число и население есть, но «не измерено» в носителе неотличимо от "
                f"«ноль» (инв. #17)")
        elif k == "produced_under_other_name":
            add("WARN", f"kpi_under_other_name:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "lower_bound_of_declared":
            add("CRITICAL", f"kpi_lower_bound_of_declared:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "components_not_composed":
            add("CRITICAL", f"kpi_components_not_composed:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "absent":
            add("CRITICAL", f"kpi_absent:{name}", f"«{name}»: {r.get('reason')}")
        fr = r.get("freshness")
        if fr:
            if fr.get("fresh") is False:
                add("WARN", f"producer_stale:{name}",
                    f"«{name}»: производитель не бежал {fr['age_hours']} ч при SLO {fr['slo_hours']} ч "
                    f"(отметка {fr['stamp']}) — число есть, оно о мире, которого уже нет")
            elif fr.get("fresh") is None:
                unmeasured.append(f"свежесть производителя «{name}»: {fr.get('reason')}")
        if name == OWNER_EMPHASIS:
            for book, pb in (r.get("per_book") or {}).items():
                sc = pb.get("self_compared") or {}
                share = sc.get("share")
                if share is not None and share >= SELF_COMPARED_SHARE_WARN:
                    add("WARN", f"yield_gap_zero_by_self_comparison:{book}",
                        f"книга {book}: в {sc['self_compared']} из {sc['judged']} записей цель РАВНА "
                        f"держимой книге (ADR-765) — Yield Gap 0 там не измерение разрыва, а его "
                        f"отсутствие по построению (gain_pp == 0 у {sc['gain_zero']} из {sc['rows']})")
                f = pb.get("formula") or {}
                if f.get("disagree"):
                    add("WARN", f"yield_gap_formula_disagrees:{book}",
                        f"книга {book}: gain_pp ≠ target − book у {f['disagree']} записей "
                        f"(допуск {f['tolerance_pp']} пп)")
        if name == "Risk Policy Violations":
            if r.get("failing_today"):
                add("INFO", "risk_limit_failing_today",
                    f"проверка дневных лимитов сегодня красна: {r['failing_today']}")
            h = r.get("history")
            if h and h.get("third_outcome_present") is False:
                add("WARN", "violations_history_without_third_outcome",
                    f"журнал блоков {BLOCKS_REL}: {h.get('rows')} записей, последняя {h.get('last_date')}; "
                    f"запись появляется ТОЛЬКО при блоке — «нет записей» неотличимо от «писатель "
                    f"молчит», счёт нарушений за период по нему не судится")
    produced = kpis.get("produced")
    missing = [n for n, r in rows.items() if r["kind"] not in PRODUCED_KINDS and r["kind"] != UNMEASURED]
    if rows and produced is not None and missing:
        add("CRITICAL", "kpis_declared_vs_produced",
            f"объявлено {kpis['declared']} KPI (слово владельца «Минимум» — это пол), "
            f"производится {produced}; без производителя: "
            + ", ".join(f"«{n}»→{rows[n]['kind']}" for n in missing)
            + f"; выделенный владельцем «{OWNER_EMPHASIS}» → {kpis.get('emphasis_kind')}")
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §33. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir, root)
    slo = ecc.load_slo(root)
    kpis = measure_kpis(carriers, slo, stamped)
    findings, unmeasured = _findings(parity_r, kpis)
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
        "schema": "portfolio_kpi_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §33 ТЗ «Portfolio CIO» (Portfolio KPIs). Ни один KPI не "
                     "вычисляет заново — витрину, реплей, судью, запись, трек, снимок и лимиты НЕ "
                     "трогает; карточку владельцу не заводит — производители KPI есть advisory-слой, "
                     "работа агента"),
        "overall": overall,
        "counts": counts,
        "declared": {"kpis": list(OWNER_KPIS), "kpis_declared": OWNER_KPIS_DECLARED,
                     "floor_word": OWNER_FLOOR_WORD, "declared_is_floor": True,
                     "emphasis": OWNER_EMPHASIS, "formula_terms": list(OWNER_FORMULA_TERMS),
                     "order_g966_named": dict(ORDER_G966_NAMED),
                     "kpi_kinds": list(KPI_KINDS), "produced_kinds": list(PRODUCED_KINDS),
                     "slo_source": MANIFEST_REL, "optimum_search": OPTIMUM_SEARCH_REL},
        "parity": parity_r,
        "kpis": kpis,
        "carriers_read": {k: (carriers.get(k) is not None)
                          for k in ("records", "daily", "eval", "replay", "forecast", "limits",
                                    "blocks", "snapshot", "shelf", "optimum_search_text")},
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
    print(f"§33 ТЗ «Portfolio CIO» (Portfolio KPIs): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (KPI {OWNER_KPIS_DECLARED}, слово «Минимум» на месте, "
              f"выделен «{OWNER_EMPHASIS}», оба члена формулы; заказ G966 числа не называл — "
              f"сдвиг не применим)")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    k = doc["kpis"]
    print(f"   KPI объявлено {k.get('declared')}, производится {k.get('produced')}; роды {k.get('tally')}; "
          f"выделенный «{k.get('emphasis')}» → {k.get('emphasis_kind')}")
    for name, r in (k.get("kpis") or {}).items():
        fr = r.get("freshness") or {}
        fresh = ("" if not fr else
                 f" · свежесть {'OK' if fr.get('fresh') else 'УСТАРЕЛ' if fr.get('fresh') is False else 'не измерена'}"
                 f" ({fr.get('age_hours')} ч / SLO {fr.get('slo_hours')} ч)")
        print(f"      «{name}»: {r['kind']} — носителей {len(r.get('carriers') or [])}, "
              f"население {r.get('population')}, род числа {r.get('number_kind')}{fresh}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§33 ТЗ «Portfolio CIO»: у КАЖДОГО из двенадцати KPI есть ли производитель "
                    "с населением, родом числа и третьим исходом")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
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
