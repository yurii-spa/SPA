"""Цена ЗНАКА критерия №3: какая величина держит его отрицательным (заказ #607/G20).

Заказ, оставленный в хвосте [ADR-387] по стоячему приказу владельца «Portfolio CIO»,
поставлен дословно так:

> Ряд G15→G19 закончен, и итог у него один: ни одно из четырёх звеньев не открывает
> взвод. […] Заказ G20 берёт то, что этот замер назвал попутно и что относится уже
> не к приборам, а к **самому критерию**. […] Измерить по исходу:
> **(а)** существует ли на наблюдённой истории ХОТЬ КАКОЕ-ТО состояние гейтов, при
> котором критерий №3 закрывается положительно — не «сняв гейт X», а перебором всех
> подмножеств снимаемых гейтов, и с названным минимальным ДОСТАТОЧНЫМ набором;
> **(б)** если такого состояния нет — какая ВЕЛИЧИНА делает счёт отрицательным
> поимённо: цена хода (``cost_usd``, и сколько из неё — допущение
> ``ASSUMED_COST_BPS_OF_TURNOVER`` против записанного), горизонт
> (``DEFAULT_HORIZON_DAYS`` = 7 — счёт считается за 7 дней, а стоимость заряжается
> целиком), либо сама выгода. Разложить net на слагаемые на КАЖДОМ оценённом дне;
> **(в)** и в той же валюте — сколько ACT-дней до критерия вернул бы КАЖДЫЙ из
> разобранных входов, будь он другим.

## Чем этот прибор отличается от пяти предыдущих

G15→G19 мерили ЗВЕНЬЯ, доставляющие дни до критерия: писателя, загрузчика, судью,
адаптеры. Все четыре вернули ноль, и ноль был свойством НАСЕЛЕНИЯ — дней с вердиктом
``ACT`` в журнале нет вовсе. Этот прибор снимает население с вопроса целиком:
он спрашивает «а если бы гейты не отказывали — что бы критерий сказал?» и отвечает
перебором ВСЕХ 2^N состояний, а не рассуждением о наиболее вероятном.

## Валюта та же, и берётся она у соседа, а не переписывается

«День дошёл до критерия» определено в ``shadow_trigger_eval.evaluate_window``: день
входит в ``acts_scored`` — единственный набор, которым считается
``net_bps_if_followed`` (мандат владельца [ADR-067]). Здесь этот судья ЗОВЁТСЯ, а не
пересказывается: своей копии правила нет ни одной, иначе две копии спорили бы о том
же дне молча (урок [ADR-376], и ровно тот же порядок, что у [ADR-386] и [ADR-387]).

Единственное, что этот прибор добавляет к судье, — **контрфактический вердикт**.
Гейты не меняются нигде: снятие набора ``S`` означает лишь «день, все отказавшие
гейты которого лежат в ``S``, был бы ``ACT``». Величина ``net_usd`` дня от вердикта
НЕ ЗАВИСИТ — судья считает её до того, как посмотрит на ``verdict`` (см.
``_evaluate_verdict``), — поэтому подстановка вердикта не подменяет ни одного числа.

## Порядок множеств, а не «виновный гейт»

Перепись отказов соседа (``arming_blockade``) отвечает на вопрос «кто отказал чаще»
и честно печатает ``sole_blocker_days = 0``: гейты отказывают пачками. Вопрос заказа
другой — «какой НАБОР достаточен», — и у него есть структура, которой у переписи нет:

* набор ``S`` **допускает** день ``d``, когда ``refused(d) ⊆ S``;
* значит допуск МОНОТОНЕН по включению: расширяя ``S``, дни можно только добавлять;
* и потому день с ПОЛОЖИТЕЛЬНЫМ счётом невозможно взять отдельно, если его набор
  отказов — надмножество набора какого-нибудь убыточного дня. Такой день называется
  здесь **задавленным** (``dominated``), и это не рассуждение, а измеряемый признак:
  прибор называет задавивших поимённо.

Именно поэтому ответ «ни одно состояние гейтов не закрывает критерий» сильнее, чем
«все дни убыточны»: второе — свойство сегодняшних чисел, первое остаётся верным и
тогда, когда прибыльные дни появляются.

## Три входа, и ни один не заменяет другой

Заказ назвал три величины. Прибор трогает КАЖДУЮ отдельно и только через ВХОД
настоящего судьи, на КОПИИ каталога данных:

======================  ==================================  =========================
вход                    как меняется                        чем это НЕ является
======================  ==================================  =========================
цена хода               ``cost_usd`` строки × коэффициент   не правкой судьи
горизонт                ``horizon_days=`` судьи             не правкой данных
выгода                  ``apy_evidenced_pct`` × коэффициент не правкой судьи
======================  ==================================  =========================

Живой каталог данных не открывается на запись ни разу: судья зовётся с
``write=False``, а возмущённые прогоны идут во временном каталоге, который прибор
создаёт и удаляет сам. У обоих свойств есть сторож — заявление без сторожа уже
однажды оказалось ложным ([ADR-387], ``ask_judge``).

**Ноль стоимости через данные ДОСТИЖИМ с 2026-09-15, и это факт о судье, а не о
приборе.** До ADR-393 ``cost_usd = 0`` читался судьёй как «записи нет» и заменялся
допущением ``ASSUMED_COST_BPS_OF_TURNOVER``; ветку снял явный ответ владельца (ADR-392
решение 1), и записанный ноль теперь означает «ход измерен и бесплатен». Допущение
осталось ровно там, где оно и есть пол fail-CLOSED: у строки БЕЗ записанной цены.
Поэтому оба варианта докладываются тем, чем являются: «ход бесплатен» — записанной
ценой, «запись стоимости убрана» — переходом на допущение.

## Что прибор НЕ доказывает

Он не утверждает, что гейт следует снять: пороги оборота — money-path и предмет №1
границы [ADR-285]. Он не утверждает, что ход был бы прибылен: контрфактический счёт
идёт по НАБЛЮДЁННЫМ ставкам следующих дней и наследует все их пробелы (день с
неоценённой ногой у судьи ``UNCHECKED`` и сюда не попадает вовсе). И он ничего не
говорит о ставках вне окна журнала.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed, observed_number

OUTPUT_FILENAME = "criterion_sign_price.json"
VERSION = "criterion-sign-price-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Файлы, которые читает судья. Копируются целиком в возмущённый каталог: брать
#: только журнал значило бы гонять судью на входе, отличающемся ДВУМЯ вещами.
_JUDGE_INPUTS = ("allocation_rationale_history.jsonl", "equity_curve_daily.json")

#: Горизонты для сметания (в). Верхняя граница взята НЕ с потолка: журнал короче,
#: и горизонт больше его длины физически не может добавить ни одного дня — прибор
#: печатает, на каком значении рычаг исчерпан.
HORIZON_SWEEP: Tuple[int, ...] = (7, 10, 14, 17, 21, 25, 30, 35, 40)

#: Коэффициенты цены хода. Ноль ОТСУТСТВУЕТ намеренно: судья читает 0 как «записи
#: нет» и заряжает допущение — см. шапку модуля.
COST_FACTORS: Tuple[float, ...] = (1.0, 0.5, 0.25, 0.1)

#: Коэффициенты выгоды: ставка вперёд × k. Отрицательных нет — они не «меньше
#: выгоды», а другой мир (уход из ноги с плохой ставкой ВЫГОДЕН, [ADR-387]).
APY_FACTORS: Tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)

#: Величины дня, без которых счёт КРИТЕРИЯ не считается. Список существует как
#: список, а не как цепочка `or 0.0` по месту: подстановка нуля в любую из них
#: сдвинула бы итог в сторону нормы и не покраснела бы нигде (инв. #17).
_REQUIRED_NUMBERS = (
    ("net_usd", "net_usd"),
    ("benefit_usd", "benefit_usd_over_checked_days"),
    ("cost_usd", "cost_usd_used"),
    ("turnover_usd", "turnover_usd"),
    ("forward_days_checked", "forward_days_checked"),
    ("forward_days_unchecked", "forward_days_unchecked"),
)

#: Скобка деления пополам для коэффициента перелома. Ответ вне скобки — «перелом
#: не найден в [lo, hi]», а не ближайшее число: подставить край значило бы выдать
#: границу поиска за свойство мира.
_BISECT_STEPS = 24
COST_BISECT_BRACKET = (0.01, 1.0)
APY_BISECT_BRACKET = (1.0, 50.0)


# ────────────────────────── чтение через настоящего судью ──────────────────────
def _judge():
    from spa_core.paper_trading import shadow_trigger_eval as ste
    return ste


def _gate_names() -> List[str]:
    """Снимаемые гейты — имена берутся у судьи, второй копии списка здесь нет.

    ``has_legs`` исключён: «существенных ног нет» не гейт, а отсутствие предмета
    решения, и снять его нельзя ничем (тот же вырез, что в ``arming_blockade``).
    """
    ste = _judge()
    return sorted(g for g in ste._ALL_GATES if g != "has_legs")


def scorable_days(data_dir: Path, *, horizon_days: Optional[int] = None,
                  ) -> Tuple[List[dict], dict]:
    """Дни, которые СЧИТАЕТ критерий, вместе с набором отказавших гейтов.

    Вердикт, счёт и населённость берутся у ``evaluate_window`` (``write=False``),
    состояние гейтов — у ``gate_state``. Ни одна из этих величин здесь не
    пересчитывается: прибор, переписавший правило соседа, отвечает на свой вопрос.
    """
    ste = _judge()
    horizon = int(horizon_days or ste.DEFAULT_HORIZON_DAYS)
    doc = ste.evaluate_window(Path(data_dir), horizon_days=horizon, write=False)
    history, _bad_lines = ste.load_history(Path(data_dir))
    by_date = {str(r.get("cycle_date")): r for r in history}

    days: List[dict] = []
    unmeasured_gate_days: List[str] = []
    unmeasured_field_days: List[dict] = []
    for row in doc.get("per_verdict") or []:
        if row.get("trivial") or row.get("outcome") not in ("hit", "miss"):
            continue
        date = str(row.get("cycle_date") or "")
        state, source = ste.gate_state(by_date.get(date) or {})
        if state is None:
            # Гейты дня не записаны ⇒ «отказавших нет» ОТСЮДА не следует: это
            # ровно та подмена «не измерено» на «в порядке», против которой
            # написан блок `gate_state`. День выносится из населения и НАЗЫВАЕТСЯ.
            unmeasured_gate_days.append(date)
            continue
        refused = frozenset(g for g, ok in state.items()
                            if g != "has_legs" and not ok)
        # Величины дня читаются ЧЕСТНОЙ формой (инв. #17): `row.get(k) or 0.0`
        # склеил бы «поля нет» с «поле равно нулю», и пропавший `net_usd` вошёл
        # бы в сумму критерия нулём — молча и в сторону нормы. День без любой из
        # обязательных величин выносится из населения и НАЗЫВАЕТСЯ.
        numbers = {name: observed_number(row, key) for name, key in _REQUIRED_NUMBERS}
        missing = sorted(key for (name, key) in _REQUIRED_NUMBERS
                         if numbers[name] is None)
        cost_source = observed(row, "cost_source", kind=str)
        if cost_source is None:
            missing.append("cost_source")
        if missing:
            unmeasured_field_days.append({"date": date, "missing": missing})
            continue
        days.append({
            "date": date,
            "refused": refused,
            "gate_source": source,
            "net_usd": numbers["net_usd"],
            "benefit_usd": numbers["benefit_usd"],
            "cost_usd": numbers["cost_usd"],
            "cost_source": cost_source,
            "cost_recorded": observed_number(row, "cost_usd_recorded"),
            "turnover_usd": numbers["turnover_usd"],
            "forward_days_checked": int(numbers["forward_days_checked"]),
            "forward_days_unchecked": int(numbers["forward_days_unchecked"]),
        })
    context = {
        "horizon_days": horizon,
        "journal_days": doc.get("observation_days"),
        "counts": doc.get("counts"),
        "capital_usd": _capital_of(history),
        "unmeasured_gate_days": unmeasured_gate_days,
        "unmeasured_field_days": unmeasured_field_days,
        "criterion_status": _criterion_status(doc),
        "net_bps_as_is": doc.get("net_bps_if_followed"),
    }
    return days, context


def _capital_of(history: Sequence[dict]) -> Optional[float]:
    """Капитал — тот же выбор, что у судьи: последняя строка, где он записан."""
    for rec in reversed(list(history)):
        if rec.get("capital_usd"):
            try:
                return float(rec["capital_usd"])
            except (TypeError, ValueError):
                return None
    return None


def _criterion_status(doc: dict) -> Optional[str]:
    for crit in doc.get("criteria") or []:
        if crit.get("criterion") == "net_bps_if_followed":
            return str(crit.get("status"))
    return None


# ──────────────────────────────── (а) перебор наборов ──────────────────────────
def enumerate_gate_subsets(days: Sequence[dict], gates: Sequence[str],
                           *, capital_usd: Optional[float] = None) -> dict:
    """Перебор ВСЕХ 2^N состояний снятия гейтов.

    Набор ``S`` допускает день ``d``, когда ``refused(d) ⊆ S``; критерий №3
    закрывается положительно, когда допущено ≥1 дня и их суммарный ``net_usd``
    строго больше нуля. Достаточные наборы приводятся к МИНИМАЛЬНЫМ по включению:
    надмножество достаточного набора достаточным быть не перестаёт, и печатать их
    все значило бы выдать 2^k копий одного ответа за k разных.
    """
    gates = list(gates)
    subsets_seen = 0
    sufficient: List[frozenset] = []
    best: Optional[dict] = None
    full = frozenset(gates)

    for size in range(len(gates) + 1):
        for combo in combinations(gates, size):
            subset = frozenset(combo)
            subsets_seen += 1
            admitted = [d for d in days if d["refused"] <= subset]
            if not admitted:
                continue
            net = sum(d["net_usd"] for d in admitted)
            if net > 0.0:
                sufficient.append(subset)
            if best is None or net > best["net_usd"]:
                best = {"gates_lifted": sorted(subset), "act_days": len(admitted),
                        "net_usd": round(net, 2),
                        "dates": [d["date"] for d in admitted]}

    minimal = [s for s in sufficient
               if not any(other < s for other in sufficient)]
    admitted_full = [d for d in days if d["refused"] <= full]
    net_full = sum(d["net_usd"] for d in admitted_full)

    #: ACT-дни до критерия — валюта соседей [ADR-386]/[ADR-387]: сколько дней
    #: критерий №3 получил бы, оставаясь при этом ПОЛОЖИТЕЛЬНЫМ. Набор, дающий
    #: больше дней ценой отрицательного счёта, критерий не закрывает и в валюту
    #: не идёт — иначе число росло бы ровно тогда, когда ответ ухудшается.
    act_days = 0
    best_positive: Optional[dict] = None
    for subset in sufficient:
        admitted = [d for d in days if d["refused"] <= subset]
        if len(admitted) > act_days:
            act_days = len(admitted)
            best_positive = {"gates_lifted": sorted(subset),
                             "act_days": len(admitted),
                             "net_usd": round(sum(d["net_usd"] for d in admitted), 2),
                             "dates": [d["date"] for d in admitted]}

    return {
        "gates": gates,
        "subsets_enumerated": subsets_seen,
        "subsets_possible": 2 ** len(gates),
        "scorable_days": len(days),
        "days_with_positive_net": sum(1 for d in days if d["net_usd"] > 0.0),
        "any_subset_closes_criterion": bool(sufficient),
        "sufficient_subsets": len(sufficient),
        "minimal_sufficient_sets": [sorted(s) for s in
                                    sorted(minimal, key=lambda s: (len(s), sorted(s)))],
        "best_subset_by_net": best,
        "best_positive_subset": best_positive,
        "act_days_to_criterion": act_days,
        "full_lift": {
            "gates_lifted": sorted(full),
            "act_days": len(admitted_full),
            "net_usd": round(net_full, 2),
            "net_bps": (round(10_000.0 * net_full / capital_usd, 2)
                        if capital_usd else None),
        },
        "domination": dominated_positive_days(days),
    }


def dominated_positive_days(days: Sequence[dict]) -> dict:
    """Прибыльные дни, которые нельзя взять отдельно — и КЕМ они задавлены.

    День ``p`` со счётом > 0 задавлен убыточным днём ``q``, если
    ``refused(q) ⊆ refused(p)``: любой набор, допускающий ``p``, допускает и ``q``.
    Это и есть причина, по которой «есть прибыльный день» не означает «есть
    состояние гейтов, закрывающее критерий», — и она структурная, а не про числа.
    """
    positives = [d for d in days if d["net_usd"] > 0.0]
    negatives = [d for d in days if d["net_usd"] <= 0.0]
    rows = []
    for p in positives:
        dominators = sorted(q["date"] for q in negatives
                            if q["refused"] <= p["refused"])
        rows.append({
            "date": p["date"],
            "net_usd": round(p["net_usd"], 2),
            "refused": sorted(p["refused"]),
            "dominated_by": dominators,
            "isolatable": not dominators,
        })
    return {
        "positive_days": len(positives),
        "dominated": sum(1 for r in rows if not r["isolatable"]),
        "isolatable": sum(1 for r in rows if r["isolatable"]),
        "rows": rows,
    }


# ─────────────────────────── (б) разложение счёта на слагаемые ─────────────────
def decompose(days: Sequence[dict], *, horizon_days: int) -> dict:
    """Счёт каждого дня — на НАЗВАННЫЕ слагаемые, плюс три сводки заказа."""
    ste = _judge()
    per_day = []
    for d in days:
        checked = d["forward_days_checked"]
        rate = (d["benefit_usd"] / checked) if checked else None
        breakeven = (d["cost_usd"] / rate) if (rate and rate > 0.0) else None
        # Экстраполяция помечена как ДОПУЩЕНИЕ и в счёт прибора не входит: она
        # отвечает на вопрос «что если бы пробелов вперёд не было», а не на
        # «что наблюдалось». Судья таких дней не оценивает — и правильно делает.
        extrapolated = (rate * horizon_days) if rate is not None else None
        per_day.append({
            "date": d["date"],
            "net_usd": round(d["net_usd"], 2),
            "benefit_usd_observed": round(d["benefit_usd"], 2),
            "cost_usd_charged": round(d["cost_usd"], 2),
            "cost_source": d["cost_source"],
            "cost_implied_bps_of_turnover": (
                round(10_000.0 * d["cost_usd"] / d["turnover_usd"], 2)
                if d["turnover_usd"] else None),
            "turnover_usd": round(d["turnover_usd"], 2),
            "forward_days_checked": checked,
            "forward_days_unchecked": d["forward_days_unchecked"],
            "benefit_usd_per_checked_day": (round(rate, 4)
                                            if rate is not None else None),
            "breakeven_horizon_days": (round(breakeven, 1)
                                       if breakeven is not None else None),
            "ASSUMPTION_benefit_usd_at_full_horizon": (
                round(extrapolated, 2) if extrapolated is not None else None),
            "ASSUMPTION_net_usd_at_full_horizon": (
                round(extrapolated - d["cost_usd"], 2)
                if extrapolated is not None else None),
        })

    recorded = [d for d in days if d["cost_source"] == "recorded"]
    assumed = [d for d in days if d["cost_source"] != "recorded"]
    bps = [10_000.0 * d["cost_usd"] / d["turnover_usd"]
           for d in days if d["turnover_usd"]]
    assumed_const = float(ste.ASSUMED_COST_BPS_OF_TURNOVER)
    cost_total = sum(d["cost_usd"] for d in days)

    # Горизонт судьи против горизонта ГЕЙТА, который этот же ход разрешает. Оба
    # числа берутся ИМПОРТОМ у своих владельцев — литералов здесь нет ни одного,
    # иначе правило жило бы второй копией и молча разошлось бы с оригиналом.
    from spa_core.allocator.rebalance_economics import TriggerParams
    gate_payback = float(TriggerParams().max_payback_days)

    slots_checked = sum(d["forward_days_checked"] for d in days)
    slots_possible = len(days) * horizon_days
    extra_net = [r["ASSUMPTION_net_usd_at_full_horizon"] for r in per_day
                 if r["ASSUMPTION_net_usd_at_full_horizon"] is not None]

    return {
        "per_day": per_day,
        "totals": {
            "net_usd": round(sum(d["net_usd"] for d in days), 2),
            "benefit_usd_observed": round(sum(d["benefit_usd"] for d in days), 2),
            "cost_usd_charged": round(cost_total, 2),
        },
        "cost": {
            "days_with_recorded_cost": len(recorded),
            "days_on_assumption": len(assumed),
            "assumption_share_of_charged_cost": (
                round(sum(d["cost_usd"] for d in assumed) / cost_total, 4)
                if cost_total else None),
            "assumed_bps_constant": assumed_const,
            "recorded_implied_bps": ({
                "min": round(min(bps), 2), "median": round(median(bps), 2),
                "max": round(max(bps), 2)} if bps else None),
            "days_costlier_than_assumption": sum(1 for b in bps if b > assumed_const),
            # Судья называет эту константу «CONSERVATIVE» прямо в своём тексте.
            # Притязание проверяемо: допущение консервативно, если оно не ДЕШЕВЛЕ
            # наблюдённой цены. Медиана выше константы ⇒ притязание не держится.
            "label_conservative_holds": (
                bool(bps) and assumed_const >= median(bps)),
        },
        "horizon": {
            "judge_horizon_days": horizon_days,
            "gate_max_payback_days": gate_payback,
            "gate_over_judge_ratio": (round(gate_payback / horizon_days, 3)
                                      if horizon_days else None),
            "forward_slots_checked": slots_checked,
            "forward_slots_possible": slots_possible,
            "priced_share_of_horizon": (round(slots_checked / slots_possible, 4)
                                        if slots_possible else None),
            "days_breakeven_within_judge_horizon": sum(
                1 for r in per_day
                if r["breakeven_horizon_days"] is not None
                and r["breakeven_horizon_days"] <= horizon_days),
            "days_breakeven_within_gate_payback": sum(
                1 for r in per_day
                if r["breakeven_horizon_days"] is not None
                and r["breakeven_horizon_days"] <= gate_payback),
            "days_never_breakeven": sum(
                1 for r in per_day if r["breakeven_horizon_days"] is None),
            "ASSUMPTION_net_usd_at_full_horizon": (round(sum(extra_net), 2)
                                                   if extra_net else None),
            "ASSUMPTION_positive_days_at_full_horizon": sum(
                1 for v in extra_net if v > 0.0),
        },
    }


# ───────────────────── (в) дифференциал по КАЖДОМУ названному входу ────────────
def _perturbed_dir(src: Path, mutate) -> Path:
    """Временная копия входов судьи с изменённой ОДНОЙ величиной.

    Живой каталог не открывается на запись ни разу: сюда копируются только те
    файлы, которые судья читает, и правится только тот ключ, о котором вопрос.
    """
    tmp = Path(tempfile.mkdtemp(prefix="criterion_sign_"))
    for name in _JUDGE_INPUTS:
        source = Path(src) / name
        if source.exists():
            shutil.copy2(source, tmp / name)
    history = tmp / _JUDGE_INPUTS[0]
    if history.exists():
        out = []
        for line in history.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                out.append(line)       # порченую строку не «чиним»: судья её посчитает
                continue
            mutate(rec)
            out.append(json.dumps(rec, ensure_ascii=False))
        history.write_text("\n".join(out) + "\n", encoding="utf-8")
    return tmp


def _scale_cost(factor: float):
    def mutate(rec: dict) -> None:
        raw = rec.get("cost_usd")
        if raw is None:
            return
        try:
            rec["cost_usd"] = float(raw) * factor
        except (TypeError, ValueError):
            return
    return mutate


def _drop_cost(rec: dict) -> None:
    rec.pop("cost_usd", None)


def _scale_apy(factor: float):
    def mutate(rec: dict) -> None:
        apy = rec.get("apy_evidenced_pct")
        if not isinstance(apy, dict):
            return
        rec["apy_evidenced_pct"] = {
            p: (float(v) * factor if isinstance(v, (int, float)) else v)
            for p, v in apy.items()}
    return mutate


def _answer_for(data_dir: Path, *, horizon_days: int, gates: Sequence[str]) -> dict:
    days, ctx = scorable_days(data_dir, horizon_days=horizon_days)
    enum = enumerate_gate_subsets(days, gates, capital_usd=ctx.get("capital_usd"))
    return {"act_days_to_criterion": enum["act_days_to_criterion"],
            "closes_positively": enum["any_subset_closes_criterion"],
            "best_net_usd": (enum["best_subset_by_net"] or {}).get("net_usd"),
            "scorable_days": enum["scorable_days"],
            "positive_days": enum["days_with_positive_net"],
            # Прибыльные дни ЕСТЬ, а критерий не закрывается — это не
            # противоречие и не шум, а тот самый структурный признак: день
            # задавлен по включению наборов. Без этой колонки вариант с
            # `positive_days > 0` и нулём ACT-дней читался бы как ошибка прибора.
            "dominated_positive_days": (enum["domination"] or {}).get("dominated"),
            "minimal_sufficient_sets": enum["minimal_sufficient_sets"]}


def _variant(data_dir: Path, *, label: str, input_name: str, how: str,
             mutate=None, horizon_days: int, gates: Sequence[str],
             factor: Optional[float] = None) -> dict:
    if mutate is None:
        row = _answer_for(Path(data_dir), horizon_days=horizon_days, gates=gates)
    else:
        tmp = _perturbed_dir(Path(data_dir), mutate)
        try:
            row = _answer_for(tmp, horizon_days=horizon_days, gates=gates)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    row.update({"variant": label, "input": input_name, "how": how,
                "factor": factor})
    return row


def _bisect_flip(data_dir: Path, *, make_mutate, bracket: Tuple[float, float],
                 rising: bool, horizon_days: int, gates: Sequence[str]) -> dict:
    """Коэффициент, на котором ответ переламывается — либо честное «не найден».

    ``rising=True`` — ответ закрывается при БОЛЬШЕМ коэффициенте (выгода);
    ``rising=False`` — при МЕНЬШЕМ (цена хода). Края скобки меряются ОБА: если
    перелома внутри нет, прибор говорит это словом, а не подставляет край.
    """
    lo, hi = bracket

    def closes(factor: float) -> bool:
        tmp = _perturbed_dir(Path(data_dir), make_mutate(factor))
        try:
            return _answer_for(tmp, horizon_days=horizon_days,
                               gates=gates)["closes_positively"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    lo_closes, hi_closes = closes(lo), closes(hi)
    want_lo, want_hi = (False, True) if rising else (True, False)
    if lo_closes != want_lo or hi_closes != want_hi:
        return {"flip_factor": None, "measured": False,
                "bracket": [lo, hi],
                "reason": (f"перелом не найден в скобке [{lo:g}, {hi:g}]: край "
                           f"{lo:g} закрывает={lo_closes}, край {hi:g} "
                           f"закрывает={hi_closes}")}
    left, right = lo, hi
    for _ in range(_BISECT_STEPS):
        mid = (left + right) / 2.0
        if closes(mid) == want_hi:
            right = mid
        else:
            left = mid
    # Печатается ТОЧНОСТЬ, а не две «границы»: после 24 делений они расходятся
    # на ~1e-7 и в любом читаемом округлении совпадают. Две одинаковые цифры,
    # названные разными именами, — вид уверенности, которого замер не даёт.
    return {"flip_factor": round((left + right) / 2.0, 5), "measured": True,
            "bracket": [lo, hi], "bisect_steps": _BISECT_STEPS,
            "resolution": float(f"{abs(right - left):.2g}"),
            "direction": "closes_below" if not rising else "closes_above"}



def _check_flip_against_sweep(flip: dict, rows: Sequence[dict]) -> None:
    """Деление пополам предполагает МОНОТОННОСТЬ — и она здесь проверяется, не берётся.

    Счёт лучшего набора есть максимум конечного числа аффинных функций
    коэффициента, то есть функция ВЫПУКЛАЯ; при отрицательном значении на одном
    краю множество «закрывается» — луч, и деление пополам законно. Это довод, а
    не замер, поэтому рядом стои́т замер: КАЖДАЯ точка сметания сверяется с
    найденным переломом. Хоть одно расхождение ⇒ перелом снимается с публикации
    (``measured = False`` с названной причиной), потому что число, полученное
    делением немонотонной функции, — это утверждение о ходе поиска, а не о мире.
    """
    if not flip.get("measured"):
        return
    pivot = float(flip["flip_factor"])
    below = flip.get("direction") == "closes_below"
    disagreed = []
    for row in rows:
        factor = row.get("factor")
        if factor is None or abs(float(factor) - pivot) <= flip.get("resolution", 0.0):
            continue
        expected = (float(factor) < pivot) if below else (float(factor) > pivot)
        if bool(row["closes_positively"]) != expected:
            disagreed.append(row["variant"])
    flip["monotonicity_control"] = {
        "sweep_points_checked": len([r for r in rows if r.get("factor") is not None]),
        "disagreed": disagreed,
        "holds": not disagreed,
    }
    if disagreed:
        flip["measured"] = False
        flip["flip_factor"] = None
        flip["reason"] = ("перелом снят с публикации: сметание не согласуется с "
                          "делением пополам на " + ", ".join(disagreed) +
                          " — функция немонотонна, и найденная точка описывает "
                          "ход поиска, а не мир")

def differential(data_dir: Path, *, horizon_days: int, gates: Sequence[str]) -> dict:
    """Сколько ACT-дней до критерия вернул бы КАЖДЫЙ вход, будь он другим."""
    rows: List[dict] = []
    for h in HORIZON_SWEEP:
        rows.append(_variant(data_dir, label=f"horizon={h}d", input_name="horizon",
                             how="параметр `horizon_days` настоящего судьи",
                             horizon_days=h, gates=gates, factor=float(h)))
    for f in COST_FACTORS:
        rows.append(_variant(
            data_dir, label=f"cost x{f:g}", input_name="cost",
            how="`cost_usd` строки журнала × коэффициент (копия каталога)",
            mutate=(None if f == 1.0 else _scale_cost(f)),
            horizon_days=horizon_days, gates=gates, factor=f))
    rows.append(_variant(
        data_dir, label="cost: запись убрана", input_name="cost",
        how="`cost_usd` удалён ⇒ судья заряжает допущение в bps оборота",
        mutate=_drop_cost, horizon_days=horizon_days, gates=gates))
    for f in APY_FACTORS:
        rows.append(_variant(
            data_dir, label=f"apy x{f:g}", input_name="benefit",
            how="`apy_evidenced_pct` вперёд × коэффициент (копия каталога)",
            mutate=(None if f == 1.0 else _scale_apy(f)),
            horizon_days=horizon_days, gates=gates, factor=f))

    by_input: Dict[str, dict] = {}
    for name in ("horizon", "cost", "benefit"):
        mine = [r for r in rows if r["input"] == name]
        best = max(mine, key=lambda r: r["act_days_to_criterion"])
        by_input[name] = {
            "variants": len(mine),
            "max_act_days_to_criterion": best["act_days_to_criterion"],
            "closes_at": (best["variant"] if best["closes_positively"] else None),
            "lever_exhausted": not any(r["closes_positively"] for r in mine),
        }

    flips = {
        "cost": _bisect_flip(data_dir, make_mutate=_scale_cost,
                             bracket=COST_BISECT_BRACKET, rising=False,
                             horizon_days=horizon_days, gates=gates),
        "benefit": _bisect_flip(data_dir, make_mutate=_scale_apy,
                                bracket=APY_BISECT_BRACKET, rising=True,
                                horizon_days=horizon_days, gates=gates),
    }
    for name, flip in flips.items():
        _check_flip_against_sweep(flip, [r for r in rows if r["input"] == name])
    # Контроль ЧУВСТВИТЕЛЬНОСТИ: прибор, чей ответ не меняется НИ ОТ ЧЕГО, мерит
    # не мир, а себя. Различие ответов между вариантами — единственное, что
    # отличает измеренный ноль от ноля, вытекающего из неподключённого рычага.
    #
    # СВЯЗЫВАЕТ он только НУЛЬ. Если базовый прогон уже закрывает критерий, то
    # рычаг заведомо доходит до судьи — положительный ответ сам себе свидетель,
    # и требовать от него ещё и изменчивости значило бы отказывать на том
    # единственном исходе, ради которого прибор и написан.
    answers = {(r["act_days_to_criterion"], r["closes_positively"]) for r in rows}
    baseline_closes = any(r["closes_positively"] for r in rows
                          if r["input"] == "cost" and r.get("factor") == 1.0)
    return {
        "rows": rows,
        "by_input": by_input,
        "flip_factors": flips,
        "sensitivity_control": {
            "distinct_answers": len(answers),
            "answer_varies": len(answers) > 1,
            "baseline_closes": baseline_closes,
            "binding": not baseline_closes,
            "holds": baseline_closes or len(answers) > 1,
            "note": ("ответ прибора обязан меняться хотя бы под одним возмущением; "
                     "неизменный НОЛЬ означает, что вход НЕ ДОХОДИТ до судьи, и "
                     "тогда он ничего не измеряет. Контроль связывает только "
                     "нулевой ответ: закрывшийся критерий сам доказывает, что "
                     "рычаг доходит"),
        },
    }


# ──────────────────────────────────── замер ────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            with_differential: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    gates = _gate_names()

    try:
        days, ctx = scorable_days(data_dir)
    except Exception as exc:  # noqa: BLE001 — третий исход, а не ноль
        return _unmeasured(now, f"судья не отвечает на этом каталоге: {exc}", gates)

    if not days:
        return _unmeasured(
            now,
            ("в журнале нет НИ ОДНОГО дня, который критерий №3 считает "
             f"(оценённых дней 0 из {ctx.get('journal_days')} дн. журнала) — "
             "перебирать нечего, и «критерий не закрывается» отсюда НЕ следует"),
            gates, context=ctx)

    horizon = int(ctx["horizon_days"])
    subsets = enumerate_gate_subsets(days, gates, capital_usd=ctx.get("capital_usd"))
    parts = decompose(days, horizon_days=horizon)
    diff = (differential(data_dir, horizon_days=horizon, gates=gates)
            if with_differential else {"measured": False,
                                       "reason": "--no-differential"})

    if with_differential and not diff["sensitivity_control"]["holds"]:
        return _unmeasured(
            now,
            ("ответ прибора НЕ ИЗМЕНИЛСЯ ни под одним из "
             f"{len(diff['rows'])} возмущений — значит возмущаемый вход до судьи "
             "не доходит, и ноль ACT-дней говорит о проводке, а не о мире"),
            gates, context=ctx)

    findings = _findings(subsets, parts, diff)
    status = STATUS_CRITICAL if any(f["severity"] == "critical" for f in findings) \
        else (STATUS_WARNING if findings else STATUS_OK)

    return {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": status,
        "mode": "ADVISORY",
        "order": "#607/G20 (хвост ADR-387, стоячий приказ владельца «Portfolio CIO»)",
        "headline": _headline(subsets, parts, diff),
        "journal": ctx,
        "gate_subsets": subsets,
        "decomposition": parts,
        "differential": diff,
        "findings": findings,
        "what_it_does_not_prove": [
            "не утверждает, что гейт следует снять: пороги оборота — money-path и "
            "предмет №1 границы ADR-285",
            "не утверждает, что ход был бы прибылен: счёт идёт по НАБЛЮДЁННЫМ "
            "ставкам следующих дней и наследует все их пробелы",
            "ничего не говорит о днях вне окна журнала и о ставках, которых в нём нет",
            "не измеряет РЫНОЧНУЮ цену бесплатного хода: с ADR-393 судья читает "
            "записанный `cost_usd = 0` как цену, и прибор берёт её как есть — "
            "верность самой записи проверяет писатель, а не этот счёт",
        ],
    }


def _unmeasured(now: datetime, reason: str, gates: Sequence[str],
                context: Optional[dict] = None) -> dict:
    return {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "mode": "ADVISORY",
        "order": "#607/G20 (хвост ADR-387, стоячий приказ владельца «Portfolio CIO»)",
        "headline": f"НЕ ИЗМЕРЕНО: {reason}",
        "unmeasured_reason": reason,
        "journal": context or {},
        "gate_subsets": {"gates": list(gates)},
        "decomposition": {},
        "differential": {},
        "findings": [],
        "what_it_does_not_prove": [
            "«не измерено» не есть «критерий закрыт» и не есть «критерий не закрыт»",
        ],
    }


def _headline(subsets: dict, parts: dict, diff: dict) -> str:
    if subsets["any_subset_closes_criterion"]:
        sets = subsets["minimal_sufficient_sets"]
        return (f"критерий №3 ЗАКРЫВАЕТСЯ положительно: достаточных наборов "
                f"{subsets['sufficient_subsets']}, минимальных {len(sets)}, "
                f"первый — {', '.join(sets[0]) if sets else '—'}; "
                f"ACT-дней до критерия {subsets['act_days_to_criterion']}")
    exhausted = [n for n, v in (diff.get("by_input") or {}).items()
                 if v["lever_exhausted"]]
    return (f"НИ ОДНО из {subsets['subsets_possible']} состояний гейтов не "
            f"закрывает критерий №3 положительно на {subsets['scorable_days']} "
            f"оценённых дн.; полное снятие даёт {subsets['full_lift']['act_days']} "
            f"ACT-дн. со счётом {subsets['full_lift']['net_usd']:g} $ "
            f"({subsets['full_lift']['net_bps']} bps капитала); "
            f"рычаг исчерпан у входов: {', '.join(exhausted) or 'ни у одного'}")


def _findings(subsets: dict, parts: dict, diff: dict) -> List[dict]:
    out: List[dict] = []
    if not subsets["any_subset_closes_criterion"]:
        out.append({
            "severity": "critical",
            "key": "no_gate_state_closes_criterion",
            "text": (f"перебраны все {subsets['subsets_possible']} состояний снятия "
                     f"гейтов: ни одно не закрывает критерий №3 положительно. "
                     f"Лучший набор — {', '.join((subsets['best_subset_by_net'] or {}).get('gates_lifted') or []) or '—'}: "
                     f"{(subsets['best_subset_by_net'] or {}).get('act_days')} ACT-дн., "
                     f"счёт {(subsets['best_subset_by_net'] or {}).get('net_usd')} $. "
                     "Ожидание, снятие «главного» гейта и любой их порядок исход не "
                     "меняют — это свойство наблюдённой истории, а не незрелости окна"),
        })
    dom = subsets.get("domination") or {}
    if dom.get("dominated"):
        rows = [r for r in dom.get("rows") or [] if not r["isolatable"]]
        out.append({
            "severity": "critical",
            "key": "positive_days_are_dominated",
            "text": (f"{dom['dominated']} прибыльн(ый/ых) дн. невозможно взять "
                     "отдельно НИ ОДНИМ набором: их отказавшие гейты — надмножество "
                     "отказов убыточного дня, и любой допускающий их набор тянет "
                     "убыток за собой. Поимённо: " + "; ".join(
                         f"{r['date']} (+{r['net_usd']} $) задавлен "
                         f"{', '.join(r['dominated_by'])}" for r in rows)),
        })
    cost = parts.get("cost") or {}
    if cost.get("label_conservative_holds") is False:
        rb = cost.get("recorded_implied_bps") or {}
        out.append({
            "severity": "warning",
            "key": "assumption_is_not_conservative",
            "text": (f"допущение `ASSUMED_COST_BPS_OF_TURNOVER` = "
                     f"{cost.get('assumed_bps_constant')} bps названо у судьи "
                     "КОНСЕРВАТИВНЫМ, а наблюдённая записанная цена выше него на "
                     f"{cost.get('days_costlier_than_assumption')} дн. из "
                     f"{len(parts.get('per_day') or [])} (медиана {rb.get('median')} bps, "
                     f"максимум {rb.get('max')} bps). Сегодня допущение не заряжается "
                     f"ни разу (записанная цена у {cost.get('days_with_recorded_cost')} дн. "
                     "из всех), поэтому на числа прибора оно не влияет — но на дне "
                     "БЕЗ записанной цены оно сместит счёт в сторону выгоды"),
        })
    # Вариант, где прибыльный день ПОЯВИЛСЯ, а критерий всё равно не закрылся,
    # — единственное прямое доказательство, что ответ «нет достаточного набора»
    # держится не на «все дни убыточны», а на порядке множеств. Без него читатель
    # вправе считать, что стоит появиться одному плюсу — и критерий закроется.
    blocked = [r for r in (diff.get("rows") or [])
               if r.get("positive_days") and not r.get("closes_positively")
               and r.get("dominated_positive_days")]
    if blocked:
        names = ", ".join(f"{r['variant']} (+{r['positive_days']} прибыльн. дн., "
                          f"задавлено {r['dominated_positive_days']})"
                          for r in blocked)
        out.append({
            "severity": "critical",
            "key": "positive_day_appears_but_criterion_stays_shut",
            "text": (f"под {len(blocked)} возмущени(ем/ями) прибыльный день "
                     "ПОЯВЛЯЕТСЯ, а критерий №3 всё равно не закрывается — "
                     "потому что взять его отдельно нельзя ни одним набором: "
                     + names + ". Значит «нет достаточного набора» держится на "
                     "порядке множеств отказов, а не на сегодняшнем знаке дней, "
                     "и появление прибыльного дня само по себе взвод не открывает"),
        })
    hz = parts.get("horizon") or {}
    if hz.get("days_breakeven_within_judge_horizon") == 0 and \
            hz.get("days_breakeven_within_gate_payback"):
        out.append({
            "severity": "critical",
            "key": "judge_and_gate_stand_on_different_horizons",
            "text": (f"судья считает выгоду за {hz.get('judge_horizon_days')} дн. и "
                     "заряжает стоимость ЦЕЛИКОМ, а гейт, разрешающий тот же ход, "
                     f"стои́т на окупаемости за {hz.get('gate_max_payback_days')} дн. "
                     f"(×{hz.get('gate_over_judge_ratio')}). Наблюдённая окупаемость "
                     f"укладывается в горизонт судьи у 0 дн., в горизонт гейта — у "
                     f"{hz.get('days_breakeven_within_gate_payback')} дн. То есть "
                     "критерий №3 требует от хода строго больше, чем правило, по "
                     "которому этот ход вообще разрешается"),
        })
    return out


# ──────────────────────────────────── отчёт ────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    if str(doc.get("status")) == STATUS_UNMEASURED:
        # Слово «НЕ ИЗМЕРЕНО» стои́т в ПЕРВОЙ строке, а не во второй: читатель,
        # пробегающий шаг 0-офис по заголовкам, обязан увидеть третий исход там
        # же, где увидел бы OK или CRITICAL.
        return [f"   цена ЗНАКА критерия №3 (заказ #607/G20): НЕ ИЗМЕРЕНО",
                f"   ⚠️ {doc.get('unmeasured_reason', 'причина не названа')}"]
    out = [f"   цена ЗНАКА критерия №3 (заказ #607/G20): {doc.get('status')}"]
    out.append(f"   {doc.get('headline')}")

    subsets = observed(doc, "gate_subsets", kind=dict) or {}
    out.append(f"   (а) состояний гейтов перебрано {subsets.get('subsets_enumerated')} "
               f"из {subsets.get('subsets_possible')} · оценённых дней "
               f"{subsets.get('scorable_days')} · из них прибыльных "
               f"{subsets.get('days_with_positive_net')} · достаточных наборов "
               f"{subsets.get('sufficient_subsets')} · ACT-дней до критерия "
               f"{subsets.get('act_days_to_criterion')}")
    dom = subsets.get("domination") or {}
    if dom.get("positive_days"):
        out.append(f"       задавленных прибыльных дней {dom.get('dominated')} из "
                   f"{dom.get('positive_days')} (взять отдельно нельзя ничем)")

    parts = observed(doc, "decomposition", kind=dict) or {}
    tot = parts.get("totals") or {}
    out.append(f"   (б) счёт = выгода {tot.get('benefit_usd_observed')} $ − цена "
               f"{tot.get('cost_usd_charged')} $ = {tot.get('net_usd')} $")
    cost = parts.get("cost") or {}
    rb = cost.get("recorded_implied_bps") or {}
    out.append(f"       цена: записана у {cost.get('days_with_recorded_cost')} дн., "
               f"допущение у {cost.get('days_on_assumption')} дн. "
               f"(доля допущения в заряженной цене "
               f"{cost.get('assumption_share_of_charged_cost')}); наблюдённая цена "
               f"{rb.get('min')}…{rb.get('max')} bps при медиане {rb.get('median')}, "
               f"константа {cost.get('assumed_bps_constant')} bps ⇒ ярлык "
               f"«консервативно» {'держится' if cost.get('label_conservative_holds') else 'НЕ ДЕРЖИТСЯ'}")
    hz = parts.get("horizon") or {}
    out.append(f"       горизонт: судья {hz.get('judge_horizon_days')} дн. против "
               f"гейта {hz.get('gate_max_payback_days')} дн. "
               f"(×{hz.get('gate_over_judge_ratio')}); оплачено вперёд "
               f"{hz.get('forward_slots_checked')} из {hz.get('forward_slots_possible')} "
               f"дней-мест ({hz.get('priced_share_of_horizon')}); окупается в горизонт "
               f"судьи {hz.get('days_breakeven_within_judge_horizon')} дн., в горизонт "
               f"гейта {hz.get('days_breakeven_within_gate_payback')} дн., не окупается "
               f"никогда {hz.get('days_never_breakeven')} дн.")
    out.append(f"       [ДОПУЩЕНИЕ, в счёт НЕ входит] выгода, растянутая на полный "
               f"горизонт по наблюдённой дневной ставке: счёт "
               f"{hz.get('ASSUMPTION_net_usd_at_full_horizon')} $, прибыльных дней "
               f"{hz.get('ASSUMPTION_positive_days_at_full_horizon')}")

    diff = observed(doc, "differential", kind=dict) or {}
    for name in ("cost", "horizon", "benefit"):
        row = (diff.get("by_input") or {}).get(name)
        if not row:
            continue
        flip = (diff.get("flip_factors") or {}).get(name) or {}
        tail = ""
        if flip.get("measured"):
            mono = flip.get("monotonicity_control") or {}
            tail = (f" · перелом на ×{flip.get('flip_factor')} "
                    f"(точность {flip.get('resolution')}; сверено со сметанием в "
                    f"{mono.get('sweep_points_checked')} точк(е/ах), расхождений "
                    f"{len(mono.get('disagreed') or [])})")
        elif flip:
            tail = f" · перелом НЕ НАЙДЕН: {flip.get('reason')}"
        out.append(f"   (в) вход «{name}»: вариантов {row['variants']}, максимум "
                   f"{row['max_act_days_to_criterion']} ACT-дн. до критерия, "
                   f"закрывается на «{row['closes_at'] or 'НИ НА ОДНОМ'}»"
                   f"{' · РЫЧАГ ИСЧЕРПАН' if row['lever_exhausted'] else ''}{tail}")
    ctrl = diff.get("sensitivity_control") or {}
    out.append(f"   [КОНТРОЛЬ] различных ответов под возмущениями "
               f"{ctrl.get('distinct_answers')} ⇒ ответ меняется: "
               f"{'ДА' if ctrl.get('answer_varies') else 'НЕТ'} · связывает "
               f"{'ДА' if ctrl.get('binding') else 'НЕТ (базовый прогон уже закрывает критерий)'}")
    for f in doc.get("findings") or []:
        out.append(f"   [{f['severity'].upper()}] {f['text']}")
    out.append("   НЕ ДОКЛАДЫВАЕТ: " + " · ".join(
        doc.get("what_it_does_not_prove") or ["границы не названы"]))
    out.append("   ADVISORY: гейты, пороги оборота, `RiskPolicy` v1.0, стоп-кран, "
               "писатель журнала и живой трек НЕ трогаются; живой каталог данных "
               "на запись не открывается — судья зовётся с `write=False`, "
               "возмущения идут во временной копии")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, with_differential: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, with_differential=with_differential)
    if write:
        atomic_save(doc, str(base / "data" / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", help="каталог данных (умолчание — data/ репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--no-differential", action="store_true",
                    help="не мерить дифференциал (быстро, но ответ НЕПОЛОН)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    args = ap.parse_args(argv)

    if args.data_dir:
        doc = measure(Path(args.data_dir),
                      with_differential=not args.no_differential)
        if not args.no_write:
            atomic_save(doc, str(Path(args.data_dir) / OUTPUT_FILENAME))
    else:
        doc = run(write=not args.no_write,
                  with_differential=not args.no_differential)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n".join(format_report(doc)))
    return {STATUS_OK: 0, STATUS_WARNING: 0,
            STATUS_CRITICAL: 1}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
