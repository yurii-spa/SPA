"""historical_replay_census.py — §38 ТЗ «Portfolio CIO»: «Historical replay».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §38::

    Historical replay
    Если доступна historical data SPA:
    прогнать новый allocator на прошлом периоде без look-ahead bias.
    Минимум сравнить: Current Strategy vs Portfolio CIO Shadow Strategy
    По: Net APY · Realized Return · Gas · Fees · Turnover · Risk Events ·
        Max Concentration · False Rebalances · Missed Opportunities
    Главная цель: не показать максимальный APY на бумаге.
    Главная цель: показать улучшение: risk-adjusted realized net return

Осей сравнения **ДЕВЯТЬ**, стратегий **ДВЕ**, условие ОДНО («без look-ahead bias»), цель
ОДНА (`risk-adjusted realized net return`). Прибор сверяет все четыре перечня и обе границы
раздела с карточкой (`parity`).

Реплей §38 УЖЕ ЕСТЬ — и измеряется он, а не строится заново
===========================================================
`spa_core/monitoring/cio_shadow_replay.py` (ADR-245, 06.09; критерий §49 — ADR-809) гоняет по
журналу ADR-060 (`data/allocation_rationale_history.jsonl`) три руки — `current` (книга, какой
была), `cio_hold` (CIO-тень, как она реально работала: все вердикты `HOLD` ⇒ стоять) и
`cio_opt` (оптимум тюнера без гейтов) — в ДВУХ колонках стоимости (газ заряженный · газ
наблюдённый, ADR-243). Этот прибор НЕ переписывает ни одной формулы реплея: он спрашивает
у реплея, что из ДЕВЯТИ осей владельца тот несёт, где именно у него граница «без
look-ahead», какую долю ПРОШЛОГО ПЕРИОДА его сравнение покрывает — и считает ли главную цель
владельца хоть кто-нибудь.

Пять осей замера
================
* **A — ось владельца → поле реплея.** Для каждой из девяти осей объявлено, каким полем
  реплей на неё отвечает (`AXIS_FIELDS`). Род: `carried` (число у ОБЕИХ стратегий владельца
  в КАЖДОЙ колонке стоимости) · `partial` (поле есть, но отвечает на УЗКИЙ вопрос — сужение
  названо и ИЗМЕРЕНО, не заявлено) · `absent` · `unmeasured`. Главная цель —
  `risk-adjusted realized net return` — отдельная строка: у неё слагаемые
  (`realized_return_usd`, `risk_events`, `max_concentration`) и свой ключ в `comparison`
  ищутся раздельно.
* **B — look-ahead.** Свойство меряется СЦЕНОЙ на живых дверях реплея (`build_arms`,
  `score_days`), а не чтением комментария: (1) состав рук на день *i* не меняется от правки
  записей *i+1…* — решение не видит будущего; (2) день оценивается ставками ЗАВТРА — всплеск
  ставки, живущий один день, не достаётся книге, выбранной в этот день. У каждой сцены есть
  ПОРВАННЫЙ вариант (двери с утечкой), на котором ответ обязан смениться — иначе сцена
  ничего не различает и род `unmeasured`. Отдельно НАЗВАНО, где реплей будущее читает ПО
  ПРАВУ: `false_rebalances` и `missed_opportunities` судят уже сделанный ход по ставкам
  вперёд — это оценка исхода, а не вход решения.
* **C — популяция.** Владелец просит «прошлый период». Реплей сравнивает руки только на
  днях, где сверены ВСЕ три (`common_scored_days`), и у замороженной руки нет цен на
  протоколы, из которых книга ушла. Прибор меряет долю покрытых пар дней, последний общий
  день, и — главное — МОЖЕТ ЛИ популяция вырасти хотя бы на день: если в книге руки
  `cio_hold` есть протокол, которого НЕТ среди ставок ПОСЛЕДНЕЙ записи, завтрашний день
  общим не станет ПО ПОСТРОЕНИЮ (`cannot_grow`, протоколы и дата их последней цены
  названы). Порог «узко» у прибора свой НЕ назначается — спрашивается у реплея
  (`population_too_thin`, ADR-220).
* **D — пара стратегий.** `Current Strategy` ↔ `current`, `Portfolio CIO Shadow Strategy` ↔
  `cio_hold` (как тень РЕАЛЬНО действовала — по вердиктам журнала, которые печатаются);
  третья рука реплея (`cio_opt`) — сверх минимума владельца и названа отдельно.
* **E — свежесть живого артефакта.** `data/cio_shadow_replay.json` против срока годности из
  конституции (единственный читатель — `rebalance_cost_evidence.declared_slo_hours`,
  ADR-243/#730). Свой порог прибор не назначает; дома нет ⇒ `unmeasured`.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``). Реплей запускается с ``write=False`` на КОПИИ трёх
входных файлов в одноразовом каталоге — живой `data/` не читается напрямую реплеем и не
пишется никем. Ни одно число не вычисляется заново (третье место для чисел запрещено —
`.claude/rules/site-numbers.md`): все метрики берутся у реплея как есть. Карточку владельцу
не заводит: реплей и его популяция — advisory-слой, исполнитель — агент. Итог реплея
(`hold_beats_the_live_book`) — предмет §38 и money-path; прибор его ПЕРЕНОСИТ, не судит.
"""
from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import os
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.utils.observation import observed as observed_field
from spa_core.utils.observation import observed_number

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/historical_replay_census.json"
CARD_REL = smc.CARD_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "38. Historical replay"
NEXT_SECTION_HEAD = "39. Observation period"
OWNER_CONDITION_LINE = "Если доступна historical data SPA:"
OWNER_NO_LOOKAHEAD_LINE = "прогнать новый allocator на прошлом периоде без look-ahead bias."
OWNER_COMPARE_LEAD = "Минимум сравнить:"
OWNER_VS = "vs"
OWNER_STRATEGIES: Tuple[str, ...] = ("Current Strategy", "Portfolio CIO Shadow Strategy")
OWNER_STRATEGIES_DECLARED = 2
OWNER_AXES_LEAD = "По:"
OWNER_AXES: Tuple[str, ...] = (
    "Net APY",
    "Realized Return",
    "Gas",
    "Fees",
    "Turnover",
    "Risk Events",
    "Max Concentration",
    "False Rebalances",
    "Missed Opportunities",
)
OWNER_AXES_DECLARED = 9
OWNER_GOAL_LEAD = "Главная цель:"
OWNER_GOAL_NOT = "не показать максимальный APY на бумаге."
OWNER_GOAL_SHOW = "показать улучшение:"
OWNER_GOAL_METRIC = "risk-adjusted realized net return"

#: Заказ G971 п. 1 назвал числа владельца сам: девять осей (перечислены) и две стратегии;
#: сдвига нет — и это печатается отдельно от «назвал верно».
ORDER_G971_NAMED: Dict[str, Any] = {"axes": 9, "strategies": 2, "tail_read": True}

#: Базовый замер реплея (ADR-245, цикл #505, 06.09): общих сверенных дней 7 из 31 пар.
#: Прибор печатает рост С ТОГО ДНЯ — пар и общих дней раздельно.
ADR245_BASELINE = {"common_scored_days": 7, "day_pairs": 31, "measured_on": "2026-09-06"}

AXIS_KINDS: Tuple[str, ...] = ("carried", "partial", "absent", UNMEASURED)
GOAL_KINDS: Tuple[str, ...] = ("computed", "components_only", "absent", UNMEASURED)
LOOKAHEAD_KINDS: Tuple[str, ...] = ("causal", "leaks", UNMEASURED)
TEAR_KINDS: Tuple[str, ...] = ("discriminates", "indiscriminate", UNMEASURED)
POPULATION_KINDS: Tuple[str, ...] = ("can_grow", "cannot_grow", "empty", UNMEASURED)
FRESHNESS_KINDS: Tuple[str, ...] = ("fresh", "stale", "absent", UNMEASURED)

#: Ось A — объявление: каким полем реплея отвечает ось владельца.
#: ``("arm", <поле>)`` — поле у КАЖДОЙ руки в КАЖДОЙ колонке стоимости;
#: ``("column", <блок>, <поле>)`` — одно число на колонку (без разбивки по рукам).
AXIS_FIELDS: Dict[str, Tuple[str, ...]] = {
    "Net APY": ("arm", "net_apy_pct"),
    "Realized Return": ("arm", "realized_return_usd"),
    "Gas": ("arm", "gas_usd"),
    "Fees": ("arm", "fees_usd"),
    "Turnover": ("arm", "turnover_usd"),
    "Risk Events": ("arm", "risk_events"),
    "Max Concentration": ("arm", "max_concentration"),
    "False Rebalances": ("column", "false_rebalances", "false"),
    "Missed Opportunities": ("column", "missed_opportunities", "missed"),
}

#: Сужения, которые прибор ОЖИДАЕТ у реплея сегодня и ИЗМЕРЯЕТ (не заявляет):
#: * «Risk Events» — единственный вход риска у ``arm_metrics`` это потолок концентрации
#:   (``concentration_cap``); стоп-кран, Tier-A `BLOCK`, отказы RiskPolicy и stale-фид
#:   событиями здесь не считаются. Появится второй вход ⇒ сужение больше не это, род
#:   ``unmeasured`` до перемера, а не молчаливое «carried».
RISK_EVENT_INPUTS_EXPECTED: Tuple[str, ...] = ("concentration_cap",)
#: * «False Rebalances» — ложность судится у ОДНОЙ руки (живой книги): блок колонки не
#:   разбит по рукам. У тени ходов нет ⇒ её ложных перекладок ноль ПО ПОСТРОЕНИЮ, у
#:   оптимума они не судятся вовсе — «сравнить две стратегии по оси» не выполнено.
ONE_SIDED_AXES: Tuple[str, ...] = ("False Rebalances",)

#: Ключи `comparison`, которые читались бы как «с поправкой на риск». Ни одного нет —
#: это и есть замер; появится — род станет `computed`.
RISK_ADJUSTED_KEY_MARKERS: Tuple[str, ...] = ("risk_adjusted", "sharpe", "per_risk", "per_unit_risk",
                                              "drawdown_adjusted", "sortino")
GOAL_COMPONENTS: Tuple[str, ...] = ("realized_return_usd", "risk_events", "max_concentration")

#: Файлы, которые реплей читает (копируются в одноразовый каталог; живой `data/` реплею
#: не отдаётся). Перечень ЗАМКНУТ и сверяется батареей с кодом реплея.
REPLAY_INPUT_FILES: Tuple[str, ...] = ("allocation_rationale_history.jsonl",
                                       "adapter_registry.json", "gas_price_history.json")
LIVE_ARTIFACT_REL = "cio_shadow_replay.json"

#: Где реплей читает будущее ПО ПРАВУ — оценка исхода, не вход решения. Печатается, чтобы
#: читатель не принял это за утечку.
FUTURE_READERS_BY_RIGHT: Tuple[Tuple[str, str], ...] = (
    ("false_rebalances", "окупаемость сделанного хода судится по ставкам ВПЕРЁД (горизонт судьи)"),
    ("missed_opportunities", "несделанный ход тюнера судится по реализованной ставке ЗАВТРА"),
)

# Сцены look-ahead — литералы сцены, не пороги системы.
_A, _B = "proto_a", "proto_b"
SCENE_CAPITAL = 100_000.0
SCENE_SPIKE_PCT = 100.0
SCENE_FLAT_PCT = 1.0


# ───────────────────────────── чтение карточки / паритет ──────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по нему был бы "
                      f"счётом неизвестно чего")
    return lines[start + 1:end], None


def _items_between(body: List[str], lead: str, stop: str) -> Optional[List[str]]:
    """Непустые строки после ``lead`` до строки ``stop`` (или «⸻»/конца)."""
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if s == stop or s == "⸻":
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
    compare = _items_between(body, OWNER_COMPARE_LEAD, OWNER_AXES_LEAD)
    return {
        "measured": True,
        "condition_line_present": OWNER_CONDITION_LINE in stripped,
        "no_lookahead_line_present": OWNER_NO_LOOKAHEAD_LINE in stripped,
        "strategies": ([s for s in compare if s != OWNER_VS] if compare is not None else None),
        "vs_present": (OWNER_VS in compare) if compare is not None else None,
        "axes": _items_between(body, OWNER_AXES_LEAD, OWNER_GOAL_LEAD),
        "goal_leads": sum(1 for s in stripped if s == OWNER_GOAL_LEAD),
        "goal_not_present": OWNER_GOAL_NOT in stripped,
        "goal_show_present": OWNER_GOAL_SHOW in stripped,
        "goal_metric_present": OWNER_GOAL_METRIC in stripped,
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_g971_named": dict(ORDER_G971_NAMED)}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    if not parsed["condition_line_present"]:
        mism.append(f"нет условия владельца {OWNER_CONDITION_LINE!r}")
    if not parsed["no_lookahead_line_present"]:
        mism.append(f"нет требования {OWNER_NO_LOOKAHEAD_LINE!r}")
    if parsed["strategies"] is None:
        mism.append(f"нет строки {OWNER_COMPARE_LEAD!r} — пара стратегий не объявлена")
    else:
        if list(parsed["strategies"]) != list(OWNER_STRATEGIES):
            mism.append(f"стратегии карточки {parsed['strategies']} ≠ константам {list(OWNER_STRATEGIES)}")
        if not parsed["vs_present"]:
            mism.append(f"между стратегиями нет {OWNER_VS!r} — это не сравнение")
    if parsed["axes"] is None:
        mism.append(f"нет строки {OWNER_AXES_LEAD!r} — оси сравнения не объявлены")
    elif list(parsed["axes"]) != list(OWNER_AXES):
        mism.append(f"оси карточки {parsed['axes']} ≠ константам {list(OWNER_AXES)}")
    if parsed["goal_leads"] < 2 or not parsed["goal_not_present"] or not parsed["goal_show_present"]:
        mism.append("цель владельца объявлена не в его форме (две строки «Главная цель:», "
                    "отрицание и утверждение)")
    if not parsed["goal_metric_present"]:
        mism.append(f"нет метрики цели {OWNER_GOAL_METRIC!r}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    return out


# ───────────────────────────── реплей: запуск на копии входов ─────────────────

def _replay_module():
    from spa_core.monitoring import cio_shadow_replay as R
    return R


def run_replay_on_copy(data_dir: str, *, now: dt.datetime) -> Dict[str, Any]:
    """Прогнать реплей на КОПИИ его входов. Живой каталог реплею не отдаётся; ``write=False``.

    Три исхода: ``{"measured": True, "doc": …, "copied": [...], "missing": [...]}`` ·
    ``measured=False`` с причиной (входов нет вовсе / реплей не импортирован / упал).
    """
    try:
        R = _replay_module()
    except Exception as exc:  # noqa: BLE001 — «нечем прогнать» ≠ «разницы нет»
        return {"measured": False, "reason": f"реплей не импортирован: {type(exc).__name__}: {exc}"}
    copied: List[str] = []
    missing: List[str] = []
    tmp = tempfile.mkdtemp(prefix="hrc_replay_")
    try:
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        for name in REPLAY_INPUT_FILES:
            src = os.path.join(data_dir, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(tmp, "data", name))
                copied.append(name)
            else:
                missing.append(name)
        if REPLAY_INPUT_FILES[0] in missing:
            return {"measured": False, "copied": copied, "missing": missing,
                    "reason": f"журнала ADR-060 нет в {data_dir!r} — прогонять нечего"}
        try:
            doc = R.run(root=tmp, now=now, write=False)
        except Exception as exc:  # noqa: BLE001
            return {"measured": False, "copied": copied, "missing": missing,
                    "reason": f"реплей упал: {type(exc).__name__}: {exc}"}
        return {"measured": True, "doc": doc, "copied": copied, "missing": missing,
                "sandbox_root_removed": True}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_records(data_dir: str) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Записи журнала ADR-060 — ТЕМ ЖЕ читателем, что у реплея (`load_history`)."""
    try:
        from pathlib import Path
        from spa_core.paper_trading import shadow_trigger_eval as ste
        records, _unparseable = ste.load_history(Path(data_dir))
        return records, None
    except Exception as exc:  # noqa: BLE001
        return None, f"журнал не прочитан: {type(exc).__name__}: {exc}"


# ───────────────────────────── ось A: оси владельца → поля реплея ─────────────

def _arm_field_everywhere(doc: Dict[str, Any], field: str, arms: Sequence[str]) -> Tuple[bool, List[str]]:
    """Есть ли ЧИСЛО ``field`` у каждой руки ``arms`` в каждой колонке стоимости."""
    columns = observed_field(doc, "columns", kind=dict)
    if columns is None or not columns:
        return False, ["в отчёте реплея нет колонок стоимости"]
    gaps: List[str] = []
    for col, block in columns.items():
        arms_out = observed_field(block, "arms", kind=dict) or {}
        for arm in arms:
            row = observed_field(arms_out, arm, kind=dict)
            if row is None:
                gaps.append(f"{col}/{arm}: руки нет")
                continue
            if observed_number(row, field) is None:
                gaps.append(f"{col}/{arm}: поля {field!r} нет или оно не число")
    return not gaps, gaps


def risk_event_inputs() -> Tuple[Optional[Tuple[str, ...]], Optional[str]]:
    """Входы риска у ``arm_metrics`` реплея — по СИГНАТУРЕ, а не по памяти."""
    try:
        R = _replay_module()
        params = inspect.signature(R.arm_metrics).parameters
    except Exception as exc:  # noqa: BLE001
        return None, f"сигнатура arm_metrics не прочитана: {type(exc).__name__}: {exc}"
    return tuple(p for p in params if p.endswith("_cap") or "risk" in p or "kill" in p
                 or "block" in p or "event" in p), None


def measure_axes(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Род каждой из девяти осей владельца на отчёте реплея."""
    try:
        R = _replay_module()
        owner_arms = (R.ARM_CURRENT, R.ARM_CIO_HOLD)
    except Exception as exc:  # noqa: BLE001
        return {axis: {"kind": UNMEASURED, "field": AXIS_FIELDS[axis],
                       "reason": f"реплей не импортирован: {exc}"} for axis in OWNER_AXES}
    out: Dict[str, Dict[str, Any]] = {}
    columns = observed_field(doc, "columns", kind=dict) or {}
    for axis in OWNER_AXES:
        spec = AXIS_FIELDS[axis]
        row: Dict[str, Any] = {"field": list(spec), "kind": UNMEASURED, "reason": None, "narrowing": None}
        if spec[0] == "arm":
            ok, gaps = _arm_field_everywhere(doc, spec[1], owner_arms)
            if not ok:
                row["kind"] = "absent"
                row["reason"] = "; ".join(gaps)
            else:
                row["kind"] = "carried"
                row["columns"] = sorted(columns)
        else:
            block_name, field = spec[1], spec[2]
            gaps = []
            for col, block in columns.items():
                blk = observed_field(block, block_name, kind=dict)
                if blk is None:
                    gaps.append(f"{col}: блока {block_name!r} нет")
                elif observed_number(blk, field) is None:
                    gaps.append(f"{col}: {block_name}.{field} нет или не число "
                                f"({blk.get('verdict')}: {blk.get('reason')})")
            if not columns:
                gaps.append("в отчёте реплея нет колонок стоимости")
            if gaps:
                row["kind"] = "absent"
                row["reason"] = "; ".join(gaps)
            else:
                row["kind"] = "carried"
                row["columns"] = sorted(columns)
        # Сужения — ИЗМЕРЯЮТСЯ, и только поверх «число есть».
        if row["kind"] == "carried" and axis == "Risk Events":
            inputs, why = risk_event_inputs()
            if inputs is None:
                row["kind"] = UNMEASURED
                row["reason"] = why
            elif tuple(inputs) == RISK_EVENT_INPUTS_EXPECTED:
                row["kind"] = "partial"
                row["narrowing"] = ("событием считается ТОЛЬКО день, где доля протокола превысила "
                                    "потолок концентрации T1; стоп-кран (SOFT/HARD), Tier-A BLOCK, отказы "
                                    "RiskPolicy и stale-фид событиями не считаются — у двери один вход "
                                    f"риска: {list(inputs)}")
            else:
                row["kind"] = UNMEASURED
                row["reason"] = (f"входы риска у arm_metrics изменились: {list(inputs)} ≠ "
                                 f"{list(RISK_EVENT_INPUTS_EXPECTED)} — сужение перемерить")
        if row["kind"] == "carried" and axis in ONE_SIDED_AXES:
            # Блок колонки без разбивки по рукам ⇒ ось судится у ОДНОЙ стороны.
            per_arm = any(isinstance(observed_field(observed_field(b, spec[1], kind=dict) or {}, "arms", kind=dict), dict)
                          for b in columns.values())
            if not per_arm:
                row["kind"] = "partial"
                row["narrowing"] = ("ложность судится только у живой книги (`current`): у тени ходов нет ⇒ "
                                    "ноль ПО ПОСТРОЕНИЮ, у оптимума не судится вовсе; «сравнить две "
                                    "стратегии по этой оси» реплей не делает")
        out[axis] = row
    return out


def measure_goal(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Главная цель владельца — считает ли её кто-нибудь."""
    comparison = observed_field(doc, "comparison", kind=dict)
    if comparison is None:
        return {"kind": UNMEASURED, "reason": "в отчёте реплея нет `comparison`"}
    if not comparison:
        return {"kind": UNMEASURED, "reason": "сравнение пусто — реплей до него не дошёл"}
    keys: List[str] = []
    for col, block in comparison.items():
        if isinstance(block, dict):
            keys.extend(f"{col}.{k}" for k in block)
    adjusted = [k for k in keys if any(m in k.lower() for m in RISK_ADJUSTED_KEY_MARKERS)]
    if adjusted:
        return {"kind": "computed", "keys": adjusted, "comparison_keys": keys}
    try:
        R = _replay_module()
        arms = (R.ARM_CURRENT, R.ARM_CIO_HOLD)
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "reason": f"реплей не импортирован: {exc}"}
    present = [c for c in GOAL_COMPONENTS if _arm_field_everywhere(doc, c, arms)[0]]
    if len(present) == len(GOAL_COMPONENTS):
        return {"kind": "components_only", "components_present": present, "comparison_keys": keys,
                "reason": ("сравнение несёт чистую доходность (net_apy_pct) и её разность между руками, "
                           "события риска и максимальную концентрацию печатаются РЯДОМ, но ни один ключ "
                           "сравнения не ставит доходность в отношение к риску — слагаемые есть, число "
                           "не складывает никто")}
    return {"kind": "absent", "components_present": present, "comparison_keys": keys,
            "reason": f"слагаемых цели нет: {sorted(set(GOAL_COMPONENTS) - set(present))}"}


# ───────────────────────────── ось B: look-ahead — сценами на живых дверях ────

def _rec(day: str, book: Dict[str, float], target: Dict[str, float], apy: Dict[str, float],
         verdict: str = "HOLD") -> dict:
    return {"cycle_date": day, "generated_at": f"{day}T06:00:00+00:00", "capital_usd": SCENE_CAPITAL,
            "current_positions": dict(book), "target_positions": dict(target),
            "apy_evidenced_pct": dict(apy), "verdict": verdict, "required_gain_pp": 0.5}


def _scene_days(n: int) -> List[str]:
    """Имена дней сцены — порядковые строки; реплей сортирует по ``(cycle_date, generated_at)``."""
    return [f"day-{i:02d}" for i in range(n)]


def _day_gain():
    from spa_core.paper_trading import shadow_trigger_eval as ste
    return ste._day_gain_usd


def scene_composition_is_causal() -> Dict[str, Any]:
    """Состав рук на дни 0…1 не зависит от записей 2…: решение не читает будущее.

    Порванный вариант — сборщик, берущий цель ЗАВТРАШНЕЙ записи: на нём ответ меняется.
    """
    R = _replay_module()
    days = _scene_days(4)
    flat = {_A: SCENE_FLAT_PCT, _B: SCENE_FLAT_PCT}
    all_a = {_A: SCENE_CAPITAL}
    all_b = {_B: SCENE_CAPITAL}
    base = [_rec(days[0], all_a, all_a, flat), _rec(days[1], all_a, all_a, flat),
            _rec(days[2], all_a, all_a, flat), _rec(days[3], all_a, all_a, flat)]
    future_changed = [dict(base[0]), dict(base[1]),
                      _rec(days[2], all_b, all_b, flat, verdict="ACT"),
                      _rec(days[3], all_b, all_b, flat, verdict="ACT")]
    arms_base = R.build_arms(base)
    arms_changed = R.build_arms(future_changed)
    same_prefix = all(arms_base[arm][:2] == arms_changed[arm][:2] for arm in R.ARMS)

    def leaky_build(records: List[dict]) -> Dict[str, List[Dict[str, float]]]:
        # Утечка: рука оптимума берёт цель СЛЕДУЮЩЕЙ записи.
        out = R.build_arms(records)
        out[R.ARM_CIO_OPT] = [R._positions(records[min(i + 1, len(records) - 1)], "target_positions")
                              for i in range(len(records))]
        return out
    torn_same = all(leaky_build(base)[arm][:2] == leaky_build(future_changed)[arm][:2] for arm in R.ARMS)
    return {"name": "composition_is_causal", "door": "cio_shadow_replay.build_arms",
            "holds": same_prefix, "torn_holds": torn_same,
            "kind": ("causal" if same_prefix else "leaks"),
            # Контроль — о ЧУВСТВИТЕЛЬНОСТИ предиката: дверь с утечкой обязана не пройти.
            "tear_kind": ("discriminates" if not torn_same else "indiscriminate"),
            "detail": "состав рук на дни 0…1 одинаков при любой правке записей 2…3; у утечки — различается"}


def scene_scored_by_tomorrow() -> Dict[str, Any]:
    """День оценивается ставками ЗАВТРА: всплеск, живущий один день, книге того дня не достаётся.

    Порванный вариант — оценка ставками ТОГО ЖЕ дня: книга, стоящая во всплеске, получает его.
    """
    R = _replay_module()
    day_gain = _day_gain()
    days = _scene_days(3)
    flat = {_A: SCENE_FLAT_PCT, _B: SCENE_FLAT_PCT}
    spike = {_A: SCENE_SPIKE_PCT, _B: SCENE_FLAT_PCT}
    all_a = {_A: SCENE_CAPITAL}
    all_b = {_B: SCENE_CAPITAL}
    records = [_rec(days[0], all_a, all_a, flat), _rec(days[1], all_a, all_a, spike),
               _rec(days[2], all_a, all_a, flat)]
    in_a, _ = R.score_days([all_a, all_a, all_a], records, day_gain=day_gain)
    in_b, _ = R.score_days([all_b, all_b, all_b], records, day_gain=day_gain)
    # День 1 (книга стоит ВО ВСПЛЕСКЕ) оценивается ставками дня 2, где ставки равны.
    equal_on_spike_day = (in_a[1] is not None and in_b[1] is not None and abs(in_a[1] - in_b[1]) < 1e-9)
    last_not_invented = len(in_a) == len(records) - 1

    def same_day_score(books: List[Dict[str, float]]) -> List[Optional[float]]:
        return [day_gain(books[i], records[i]["apy_evidenced_pct"])[0] for i in range(len(records) - 1)]
    t_a, t_b = same_day_score([all_a, all_a, all_a]), same_day_score([all_b, all_b, all_b])
    torn_equal = (t_a[1] is not None and t_b[1] is not None and abs(t_a[1] - t_b[1]) < 1e-9)
    holds = equal_on_spike_day and last_not_invented
    return {"name": "scored_by_tomorrow", "door": "cio_shadow_replay.score_days",
            "holds": holds, "torn_holds": torn_equal,
            "kind": ("causal" if holds else "leaks"),
            "tear_kind": ("discriminates" if not torn_equal else "indiscriminate"),
            "spike_day_gain_usd": {"book_in_spike": in_a[1], "book_outside": in_b[1]},
            "torn_spike_day_gain_usd": {"book_in_spike": t_a[1], "book_outside": t_b[1]},
            "last_day_not_invented": last_not_invented,
            "detail": ("на дне всплеска обе книги получают одно и то же (ставки ЗАВТРА равны); "
                       "у оценки тем же днём книга во всплеске получает в "
                       f"{SCENE_SPIKE_PCT / SCENE_FLAT_PCT:.0f}× больше; последний день без завтра не выдумывается")}


LOOKAHEAD_SCENES: Dict[str, Callable[[], Dict[str, Any]]] = {
    "composition_is_causal": scene_composition_is_causal,
    "scored_by_tomorrow": scene_scored_by_tomorrow,
}


def measure_lookahead() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name, fn in LOOKAHEAD_SCENES.items():
        try:
            row = fn()
        except Exception as exc:  # noqa: BLE001
            row = {"name": name, "kind": UNMEASURED, "tear_kind": UNMEASURED,
                   "reason": f"сцена упала: {type(exc).__name__}: {exc}"}
        if row.get("tear_kind") == "indiscriminate":
            # Сцена, не различающая утечку, о причинности ничего не сказала.
            row["kind"] = UNMEASURED
            row["reason"] = "порванная сцена даёт тот же ответ — сцена ничего не различает"
        out[name] = row
    return out


# ───────────────────────────── ось C: популяция ───────────────────────────────

def measure_population(doc: Dict[str, Any], records: Optional[List[dict]]) -> Dict[str, Any]:
    pop = observed_field(doc, "population", kind=dict)
    if pop is None:
        return {"kind": UNMEASURED, "reason": "в отчёте реплея нет `population`"}
    pairs = observed_number(pop, "day_pairs")
    common = observed_number(pop, "common_scored_days")
    if pairs is None or common is None:
        return {"kind": UNMEASURED, "reason": "реплей не назвал пар дней или общих дней"}
    common_dates = observed_field(pop, "common_dates", kind=list)
    out: Dict[str, Any] = {
        "day_pairs": int(pairs), "common_scored_days": int(common),
        "coverage_share": (round(common / pairs, 4) if pairs else None),
        "last_common_date": (common_dates[-1] if common_dates else None),
        "scored_per_arm": observed_field(pop, "scored_per_arm", kind=dict),
        "unpriced_per_arm": observed_field(pop, "unpriced_per_arm", kind=dict),
        "verdicts": observed_field(pop, "verdicts", kind=dict),
        "growth_since_adr245": {"day_pairs": int(pairs) - ADR245_BASELINE["day_pairs"],
                                "common_scored_days": int(common) - ADR245_BASELINE["common_scored_days"],
                                "baseline": dict(ADR245_BASELINE)},
    }
    try:
        R = _replay_module()
        out["replay_refuses_claim"] = bool(R.population_too_thin(common))
        out["replay_min_common_days"] = R.MIN_COMMON_DAYS_FOR_CLAIM
    except Exception as exc:  # noqa: BLE001
        out["replay_refuses_claim"] = None
        out["reason_refusal_unmeasured"] = f"порог реплея не прочитан: {exc}"
    if int(common) == 0:
        out["kind"] = "empty"
        return out
    if records is None or not records:
        out["kind"] = UNMEASURED
        out["reason"] = "записи журнала не прочитаны — рост популяции не судится"
        return out
    # Может ли вырасти: у замороженной руки каждый протокол должен иметь цену в ПОСЛЕДНЕЙ записи.
    try:
        R = _replay_module()
        hold_book = R.build_arms(records)[R.ARM_CIO_HOLD][0]
    except Exception as exc:  # noqa: BLE001
        out["kind"] = UNMEASURED
        out["reason"] = f"рука тени не собрана: {exc}"
        return out
    last = records[-1]
    last_apy = observed_field(last, "apy_evidenced_pct", kind=dict) or {}
    last_priced: Dict[str, Optional[str]] = {p: None for p in hold_book}
    for rec in records:
        for p in (observed_field(rec, "apy_evidenced_pct", kind=dict) or {}):
            if p in last_priced:
                last_priced[p] = str(rec.get("cycle_date"))
    unpriced_today = sorted(p for p in hold_book if last_apy.get(p) is None)
    out.update({
        "hold_book_day0": hold_book,
        "last_record_date": str(last.get("cycle_date")),
        "hold_book_last_priced": last_priced,
        "hold_book_unpriced_in_last_record": unpriced_today,
        "kind": ("cannot_grow" if unpriced_today else "can_grow"),
    })
    return out


# ───────────────────────────── ось D: пара стратегий ──────────────────────────

def measure_strategy_pair(doc: Dict[str, Any]) -> Dict[str, Any]:
    try:
        R = _replay_module()
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "reason": f"реплей не импортирован: {exc}"}
    mapping = {OWNER_STRATEGIES[0]: R.ARM_CURRENT, OWNER_STRATEGIES[1]: R.ARM_CIO_HOLD}
    extra = [a for a in R.ARMS if a not in mapping.values()]
    pop = observed_field(doc, "population", kind=dict) or {}
    verdicts = observed_field(pop, "verdicts", kind=dict)
    columns = observed_field(doc, "columns", kind=dict) or {}
    present = all(observed_field(observed_field(b, "arms", kind=dict) or {}, arm, kind=dict) is not None
                  for b in columns.values() for arm in mapping.values()) and bool(columns)
    return {"kind": ("both_present" if present else "absent"), "mapping": mapping, "extra_arms": extra,
            "shadow_arm_acted_as": verdicts,
            "note": ("рука тени стоит, пока журнал выносит HOLD; на дне ACT она берёт цель того дня "
                     "(выведено из вердикта, не вписано литералом — ADR-245)")}


# ───────────────────────────── ось E: свежесть живого артефакта ───────────────

def measure_freshness(root: str, data_dir: str, *, now: dt.datetime) -> Dict[str, Any]:
    path = os.path.join(data_dir, LIVE_ARTIFACT_REL)
    try:
        with open(path, encoding="utf-8") as fh:
            live = json.load(fh)
    except FileNotFoundError:
        return {"kind": "absent", "path": path, "reason": "живого артефакта реплея нет"}
    except (OSError, ValueError) as exc:
        return {"kind": UNMEASURED, "path": path, "reason": f"артефакт не прочитан: {type(exc).__name__}: {exc}"}
    stamp_raw = live.get("generated_at")
    try:
        stamp = dt.datetime.fromisoformat(str(stamp_raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return {"kind": UNMEASURED, "path": path, "reason": f"generated_at не разобран: {stamp_raw!r}"}
    age_h = (now - stamp).total_seconds() / 3600.0
    try:
        from spa_core.monitoring import rebalance_cost_evidence as rce

        def _read(where: str):
            with open(where, encoding="utf-8") as fh:
                return json.load(fh)
        slo, why = rce.declared_slo_hours(root, _read, "data/" + LIVE_ARTIFACT_REL)
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "path": path, "age_hours": round(age_h, 2),
                "reason": f"читатель срока годности не загружен: {type(exc).__name__}: {exc}"}
    if slo is None:
        return {"kind": UNMEASURED, "path": path, "age_hours": round(age_h, 2),
                "reason": f"срок годности не объявлен: {why}"}
    return {"kind": ("stale" if age_h > slo else "fresh"), "path": path, "age_hours": round(age_h, 2),
            "slo_hours": slo, "generated_at": stamp.isoformat(),
            "live_overall": live.get("overall"),
            "live_common_scored_days": observed_number(observed_field(live, "population", kind=dict) or {},
                                                       "common_scored_days")}


# ───────────────────────────── находки и сборка ───────────────────────────────

def _findings(parity_r: Dict[str, Any], replay_r: Dict[str, Any], axes: Dict[str, Dict[str, Any]],
              goal: Dict[str, Any], lookahead: Dict[str, Dict[str, Any]], population: Dict[str, Any],
              pair: Dict[str, Any], freshness: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is False:
        findings.append({"severity": "CRITICAL", "code": "owner_section_drifted",
                         "detail": "; ".join(parity_r["mismatches"])})
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    if not replay_r.get("measured"):
        unmeasured.append(f"реплей не прогнан: {replay_r.get('reason')}")
        return findings, unmeasured

    for axis, row in axes.items():
        if row["kind"] == "absent":
            findings.append({"severity": "CRITICAL", "code": "axis_absent", "axis": axis, "detail": row["reason"]})
        elif row["kind"] == "partial":
            findings.append({"severity": "WARN", "code": "axis_partial", "axis": axis, "detail": row["narrowing"]})
        elif row["kind"] == UNMEASURED:
            unmeasured.append(f"ось {axis!r}: {row.get('reason')}")

    if goal["kind"] in ("components_only", "absent"):
        findings.append({"severity": "CRITICAL", "code": "risk_adjusted_return_not_computed",
                         "detail": goal.get("reason")})
    elif goal["kind"] == UNMEASURED:
        unmeasured.append(f"цель владельца: {goal.get('reason')}")

    for name, row in lookahead.items():
        if row["kind"] == "leaks":
            findings.append({"severity": "CRITICAL", "code": "look_ahead_leak", "scene": name,
                             "detail": row.get("detail")})
        elif row["kind"] == UNMEASURED:
            unmeasured.append(f"сцена look-ahead {name!r}: {row.get('reason')}")

    pk = population.get("kind")
    if pk == "cannot_grow":
        findings.append({"severity": "CRITICAL", "code": "comparison_window_cannot_grow",
                         "detail": (f"общих сверенных дней {population['common_scored_days']} из "
                                    f"{population['day_pairs']} пар ({population['coverage_share']:.1%} периода), "
                                    f"последний общий день {population['last_common_date']}, последняя запись "
                                    f"{population['last_record_date']}; книга руки тени держит протоколы без "
                                    f"цены в последней записи: {population['hold_book_unpriced_in_last_record']} "
                                    f"(последняя цена: "
                                    f"{ {p: population['hold_book_last_priced'][p] for p in population['hold_book_unpriced_in_last_record']} }) "
                                    f"— завтрашний день общим не станет по построению; с ADR-245 пар "
                                    f"+{population['growth_since_adr245']['day_pairs']}, общих дней "
                                    f"+{population['growth_since_adr245']['common_scored_days']}")})
    elif pk == "empty":
        findings.append({"severity": "CRITICAL", "code": "comparison_window_empty",
                         "detail": "ни одного дня, сверенного во всех руках"})
    elif pk == UNMEASURED:
        unmeasured.append(f"популяция: {population.get('reason')}")
    if population.get("replay_refuses_claim") is True:
        findings.append({"severity": "WARN", "code": "replay_refuses_its_own_claim",
                         "detail": (f"сам реплей объявляет популяцию узкой ({population['common_scored_days']} < "
                                    f"{population['replay_min_common_days']}) и улучшение risk-adjusted return "
                                    f"НЕ утверждает — перенесено, не пересчитано")})

    if pair.get("kind") == "absent":
        findings.append({"severity": "CRITICAL", "code": "strategy_pair_absent",
                         "detail": f"не обе стратегии владельца присутствуют в колонках: {pair.get('mapping')}"})
    elif pair.get("kind") == UNMEASURED:
        unmeasured.append(f"пара стратегий: {pair.get('reason')}")

    if freshness.get("kind") == "stale":
        findings.append({"severity": "WARN", "code": "live_artifact_stale",
                         "detail": (f"живой артефакт реплея возрастом {freshness['age_hours']} ч при сроке "
                                    f"{freshness['slo_hours']} ч — его бегун есть ступень моста "
                                    f"(`findings_bridge`), служба `com.spa.decision_loop` не загружена "
                                    f"(известный класс); числа ниже сняты на СВЕЖЕЙ копии входов")})
    elif freshness.get("kind") == "absent":
        findings.append({"severity": "WARN", "code": "live_artifact_absent", "detail": freshness.get("reason")})
    elif freshness.get("kind") == UNMEASURED:
        unmeasured.append(f"свежесть артефакта: {freshness.get('reason')}")

    # Итог реплея ПЕРЕНОСИТСЯ (money-path — не судится здесь). «Раздела находок нет» и «находок
    # ноль» — разные положения дел (инв. #17): первое означает отчёт не этого прибора.
    doc = replay_r["doc"]
    carried = observed_field(doc, "findings", kind=list)
    if carried is None:
        unmeasured.append("в отчёте реплея нет раздела `findings` — итог реплея не перенесён")
    else:
        for f in carried:
            if f.get("code") in ("hold_beats_the_live_book", "false_rebalances_dominate"):
                findings.append({"severity": "INFO", "code": f"replay.{f['code']}", "detail": f.get("message"),
                                 "carried_from": "cio_shadow_replay (не пересчитано)"})
    return findings, unmeasured


def _tally(axes: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    return {k: sum(1 for r in axes.values() if r["kind"] == k) for k in AXIS_KINDS}


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None, card_path: Optional[str] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §38. Только ЧИТАЕТ; реплей гоняется на копии входов с ``write=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    parity_r = parity(card_path)
    replay_r = run_replay_on_copy(data_dir, now=stamped)
    records, rec_why = load_records(data_dir)
    if replay_r.get("measured"):
        rdoc = replay_r["doc"]
        axes = measure_axes(rdoc)
        goal = measure_goal(rdoc)
        population = measure_population(rdoc, records)
        if records is None and population.get("kind") == UNMEASURED:
            population["reason"] = rec_why or population.get("reason")
        pair = measure_strategy_pair(rdoc)
    else:
        axes = {a: {"kind": UNMEASURED, "field": list(AXIS_FIELDS[a]), "reason": replay_r.get("reason")}
                for a in OWNER_AXES}
        goal = {"kind": UNMEASURED, "reason": replay_r.get("reason")}
        population = {"kind": UNMEASURED, "reason": replay_r.get("reason")}
        pair = {"kind": UNMEASURED, "reason": replay_r.get("reason")}
    lookahead = measure_lookahead()
    freshness = measure_freshness(root, data_dir, now=stamped)
    findings, unmeasured = _findings(parity_r, replay_r, axes, goal, lookahead, population, pair, freshness)
    counts = {"critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
              "warn": sum(1 for f in findings if f["severity"] == "WARN"),
              "info": sum(1 for f in findings if f["severity"] == "INFO"),
              "unmeasured": len(unmeasured)}
    overall = ("CRITICAL" if counts["critical"] else "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    replay_summary: Dict[str, Any] = {"measured": replay_r.get("measured"), "reason": replay_r.get("reason"),
                                      "inputs_copied": replay_r.get("copied"), "inputs_missing": replay_r.get("missing")}
    if replay_r.get("measured"):
        rdoc = replay_r["doc"]
        replay_summary.update({"overall": rdoc.get("overall"), "comparison": rdoc.get("comparison"),
                               "criterion": rdoc.get("criterion"), "unchecked": rdoc.get("unchecked"),
                               "provenance": rdoc.get("provenance")})
    doc = {
        "schema": "historical_replay_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §38 ТЗ «Portfolio CIO» (Historical replay): какие из девяти осей "
                     "владельца несёт существующий реплей (A), держится ли «без look-ahead» сценой на живых "
                     "дверях (B), какую долю прошлого периода покрывает сравнение и может ли она вырасти (C), "
                     "обе ли стратегии владельца в сравнении (D), свеж ли живой артефакт (E), и считает ли "
                     "кто-нибудь главную цель владельца. Реплей гоняется на КОПИИ входов с write=False; ни одно "
                     "число не считается заново, итог реплея переносится. Карточка владельцу не заводится."),
        "overall": overall,
        "counts": counts,
        "declared": {"axes": list(OWNER_AXES), "axes_declared": OWNER_AXES_DECLARED,
                     "strategies": list(OWNER_STRATEGIES), "strategies_declared": OWNER_STRATEGIES_DECLARED,
                     "goal_metric": OWNER_GOAL_METRIC, "no_lookahead_line": OWNER_NO_LOOKAHEAD_LINE,
                     "axis_fields": {k: list(v) for k, v in AXIS_FIELDS.items()},
                     "axis_kinds": list(AXIS_KINDS), "goal_kinds": list(GOAL_KINDS),
                     "lookahead_kinds": list(LOOKAHEAD_KINDS), "population_kinds": list(POPULATION_KINDS),
                     "freshness_kinds": list(FRESHNESS_KINDS),
                     "future_readers_by_right": [{"block": b, "why": w} for b, w in FUTURE_READERS_BY_RIGHT],
                     "replay_input_files": list(REPLAY_INPUT_FILES),
                     "order_g971_named": dict(ORDER_G971_NAMED)},
        "parity": parity_r,
        "replay": replay_summary,
        "axes": axes,
        "axes_tally": _tally(axes),
        "goal": goal,
        "lookahead": lookahead,
        "population": population,
        "strategy_pair": pair,
        "freshness": freshness,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§38 ТЗ «Portfolio CIO» (Historical replay): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (осей {OWNER_AXES_DECLARED}, стратегий {OWNER_STRATEGIES_DECLARED}; "
              f"заказ G971 назвал {ORDER_G971_NAMED['axes']} осей — сдвига нет)")
    elif p.get("agrees") is False:
        print("   паритет с карточкой: РАСХОЖДЕНИЕ — " + "; ".join(p["mismatches"]))
    else:
        print(f"   паритет с карточкой: НЕ ИЗМЕРЕН — {p['parsed'].get('reason')}")
    r = doc["replay"]
    if r.get("measured"):
        cmp_ = r.get("comparison") or {}
        print(f"   реплей на копии входов: {r.get('overall')} · критерий §49 {((r.get('criterion') or {}).get('status'))} · "
              f"колонки {sorted(cmp_)}")
    else:
        print(f"   реплей: НЕ ПРОГНАН — {r.get('reason')}")
    print(f"   оси владельца: {doc['axes_tally']}")
    for axis, row in doc["axes"].items():
        tail = row.get("narrowing") or row.get("reason") or ""
        print(f"      {axis:<22} {row['kind']:<10} {'.'.join(str(x) for x in row['field'][1:])}"
              f"{' — ' + tail if tail else ''}")
    g = doc["goal"]
    print(f"   цель владельца ({OWNER_GOAL_METRIC}): {g['kind']}"
          f"{' — ' + str(g.get('reason')) if g.get('reason') else ''}")
    for name, row in doc["lookahead"].items():
        print(f"   look-ahead {name:<24} {row['kind']:<10} порванная={row.get('tear_kind')}")
    pop = doc["population"]
    if pop.get("day_pairs") is not None:
        share = pop["coverage_share"]
        share_txt = f"{share:.1%}" if share is not None else "доля НЕ ИЗМЕРЕНА (пар нет)"
        print(f"   популяция: общих {pop['common_scored_days']} из {pop['day_pairs']} пар "
              f"({share_txt}), последний общий день {pop.get('last_common_date')}, "
              f"последняя запись {pop.get('last_record_date')} → {pop['kind']}; "
              f"реплей отказывает утверждать: {pop.get('replay_refuses_claim')}")
    else:
        print(f"   популяция: {pop['kind']} — {pop.get('reason')}")
    fr = doc["freshness"]
    print(f"   живой артефакт: {fr['kind']} (возраст {fr.get('age_hours')} ч, срок {fr.get('slo_hours')} ч)")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f.get('detail')}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — момент замера не назван"
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        return None, f"--now не разобран ({exc})"
    return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)), None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§38 ТЗ «Portfolio CIO»: что из девяти осей владельца несёт реплей, где его look-ahead, "
                    "какую долю периода покрывает сравнение")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None, help="каталог данных (журнал ADR-060 и живой артефакт)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card, write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
