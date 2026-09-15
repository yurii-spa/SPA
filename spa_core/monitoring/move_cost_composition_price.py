"""Цена СОСТАВА хода: от чего она зависит поимённо (заказ #608/G21).

Заказ, оставленный в хвосте [ADR-388] по стоячему приказу владельца «Portfolio
CIO», поставлен дословно так:

> Замер закрыл вопрос «почему критерий стоит» и открыл ровно один новый, который
> из него следует и ни разу не мерился: **перекладки не окупаются — а КАКИЕ
> именно и ПОЧЕМУ.** […]
> **(а)** от чего зависит цена хода поимённо — оборот, число ног, сеть, протокол?
> Замер: та же ``rebalance_economics``, что цену и писала, и **сверка её оценки с
> НАБЛЮДЁННОЙ** там, где обе есть. Цена, которую никто не сверял с фактом, —
> допущение с записью, а не наблюдение;
> **(б)** два дня из 17 имеют выгоду ОТРИЦАТЕЛЬНУЮ (2026-08-06: −0.86 $,
> 2026-09-07: −2.39 $) — то есть предложенная перекладка уходила в ХУДШУЮ ставку.
> Это либо дефект аллокатора, либо верный ход по другому основанию (риск,
> концентрация, тир), и различить их можно только по записи самого дня. Назвать
> основание каждого из двух;
> **(в)** и в той же валюте: если бы цена хода равнялась своей наблюдённой
> МЕДИАНЕ вместо записанной на каждом дне — сколько ACT-дней вернулось бы
> критерию?

## Первое, что меряет прибор, — существует ли «наблюдённая цена» вообще

Заказ просит сверить ОЦЕНКУ с НАБЛЮДЁННОЙ ценой. Прибор эту сверку и делает — и
сверка отвечает не тем, чего ждал заказ: ``cost_usd`` в журнале **и есть выход
оценщика**. Он пересчитывается из собственных записанных входов дня
(``legs`` + ``turnover_usd`` + карта сетей) функцией
:func:`spa_core.allocator.rebalance_economics._move_cost_usd` — той самой, что
число и записала, — и совпадает С ТОЧНОСТЬЮ ДО ЦЕНТА. Второго, независимого
наблюдения цены в системе нет ни одного: бумажная стадия исполнения не делает,
поэтому факта, с которым можно было бы сверить, не существует.

Отсюда всё остальное: «цена должна упасть в 6.16 раза» ([ADR-388]) — утверждение
о ТРЁХ КОНСТАНТАХ модели (``GAS_USD_PER_POSITION_CHANGE``,
``SLIPPAGE_BPS_STABLE``, ``BRIDGE_BPS``), а не о мире. Прибор поэтому не
«сверяет цену с фактом» (нечего сверять), а делает три вещи, которые сделать
можно: **воспроизводит** записанное число из записанных входов, **разлагает** его
на названные слагаемые и **измеряет**, какое из слагаемых держит знак критерия.

## Три слагаемых, и они зависят от РАЗНОГО

======================  =========================================  ==================
слагаемое               от чего зависит                            как меняется в bps
======================  =========================================  ==================
проскальзывание         ТОЛЬКО от оборота (константа в bps)        не меняется вовсе
газ                     число ног × сеть каждой ноги               ~ 1/оборот
мост                    5 bps, если сетей больше одной             ступенька 0 или 5
======================  =========================================  ==================

Поэтому «цена в bps оборота» гуляет: проскальзывание в ней неподвижно, а газ —
фиксированные доллары на ногу, и в bps он тем больше, чем МЕНЬШЕ ход. Это не
наблюдение о рынке, а форма формулы, и прибор называет её формой, а не находкой.

## Чего прибор НЕ делает: не восстанавливает ноги, которых не записали

До 2026-09-01 писатель журнала ``legs`` не писал вовсе. Слагаемое
«газ + мост» на таких днях вычитается из записанной цены целиком
(``cost − проскальзывание``), а РАЗДЕЛИТЬ его на газ и мост нельзя: одну и ту же
сумму объясняют разные пары (число ног, набор сетей). Такой день получает третий
исход — ``legs_not_recorded``, — а не подобранную пару и не ноль (инв. #17).
Тот же третий исход получает день, чья нога отсутствует в карте сетей: оценщик
молча подставил бы ``blended`` = 1.5 $, и «сверка» сравнивала бы записанное
число с догадкой, объявляя согласие.

## Карта сетей — СЕГОДНЯШНЯЯ, и это сказано вслух

``chains`` берётся из ``data/adapter_registry.json`` (тот же источник, что у
писателя, :mod:`spa_core.paper_trading.allocation_rationale`) — то есть карта
НЫНЕШНЯЯ, а не та, что действовала в день решения. Дня-своей-карты в журнале
нет. Совпадение до цента на всех воспроизводимых днях и есть довод, что карта не
двигалась в нужных ключах; довод, а не запись, и прибор печатает его как довод.

## (б) различение делает ЗАПИСЬ ДНЯ, а не рассуждение

«Дефект аллокатора» и «верный ход, который не сбылся» различаются одним
измеримым признаком: **знаком выгоды, посчитанной по ставкам САМОГО дня решения**
(ex ante). Если аллокатор предлагал книгу, которая была хуже уже по его
собственным данным, — это дефект. Если она была лучше, а вперёд ставка ушла —
это снос ставки, и виновная нога называется поимённо.

Обе величины считаются ОДНОЙ арифметикой судьи (``_day_gain_usd``), а не своей
копией правила, и восстановление форвардного окна сверяется с числом судьи на
каждом дне: расхождение хоть на цент ⇒ прибор докладывает НЕ ИЗМЕРЕНО.

## Что прибор НЕ доказывает

Он не утверждает, что цену следует понизить: константы стоимости — вход
денежного пути. Он не утверждает, что ход был бы прибылен. Он ничего не говорит
о днях вне окна журнала и о ногах, которых в нём нет. И он не измеряет
РЫНОЧНУЮ цену перекладки — её в системе не наблюдал никто.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed, observed_number

OUTPUT_FILENAME = "move_cost_composition_price.json"
VERSION = "move-cost-composition-price-v1"
ORDER = "#608/G21 (хвост ADR-388, стоячий приказ владельца «Portfolio CIO»)"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Совпадение цены считается точным в пределах цента: оценщик округляет свой
#: результат до двух знаков (`round(..., 2)` в `evaluate`), поэтому требовать
#: побайтового равенства значило бы объявить расхождением собственное округление.
CENT = 0.005

#: Уровни цены для сметания (в), в bps оборота. Медиана и константа
#: проскальзывания добавляются к ним ЗАМЕРОМ, а не литералом: обе берутся у своих
#: владельцев в рантайме.
BPS_SWEEP: Tuple[float, ...] = (30.0, 20.0, 15.0, 10.0, 5.0, 4.0, 3.0, 2.0, 1.0)

#: Предел перебора ног при разборе НЕРАЗДЕЛИМОЙ суммы «газ + мост» (см.
#: :func:`lump_explanations`). Число — параметр ПОИСКА, а не свойство мира, и
#: печатается рядом с ответом: «решение единственно» при пределе 8 означает
#: «единственно среди наборов не длиннее восьми», и ничего больше.
LUMP_SEARCH_MAX_LEGS = 8

#: Скобка деления пополам для уровня цены (bps оборота). Ответ вне скобки —
#: «перелом не найден», а не край: подставить границу поиска значило бы выдать
#: параметр прибора за свойство мира.
BPS_BISECT_BRACKET = (0.1, 30.0)
_BISECT_STEPS = 24


# ───────────────────────── соседи зовутся, а не переписываются ─────────────────
def _neighbour():
    """Прибор G20: у него уже живёт доступ к судье и возмущение каталога.

    Своей копии этих правил здесь нет ни одной — две копии спорили бы об одном
    и том же дне молча (урок [ADR-376]).
    """
    from spa_core.monitoring import criterion_sign_price as csp
    return csp


def _judge():
    from spa_core.paper_trading import shadow_trigger_eval as ste
    return ste


def _cost_model():
    """Константы стоимости — ИМПОРТОМ у владельца, литералов здесь нет.

    Оценщик ``_move_cost_usd`` тоже берётся отсюда: воспроизводить цену своей
    формулой значило бы сверять запись с ДРУГОЙ моделью и называть совпадение
    подтверждением.
    """
    from spa_core.allocator.rebalance_economics import _move_cost_usd
    from spa_core.backtesting.tier1.cost_model import (
        GAS_USD_PER_POSITION_CHANGE, SLIPPAGE_BPS_STABLE, BRIDGE_BPS)
    return (_move_cost_usd, GAS_USD_PER_POSITION_CHANGE,
            float(SLIPPAGE_BPS_STABLE), float(BRIDGE_BPS))


def chain_map(data_dir: Path) -> Tuple[Dict[str, str], str]:
    """Карта «протокол → сеть» из ТОГО ЖЕ файла, что читает писатель журнала.

    Второй исход назван: файла нет / он не читается ⇒ пустая карта И причина.
    Пустая карта не означает «сетей нет» — она означает, что состав цены
    воспроизвести нечем, и все дни уйдут в третий исход.
    """
    path = Path(data_dir) / "adapter_registry.json"
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — причина, а не пустота
        return {}, f"карта сетей НЕ ПРОЧИТАНА ({path.name}: {exc})"
    out: Dict[str, str] = {}
    for name, entry in (reg.get("adapters") or {}).items():
        if isinstance(entry, dict) and entry.get("chain"):
            out[str(name)] = str(entry["chain"]).strip().lower()
    return out, f"{path.name}: {len(out)} ключ(ей) (карта СЕГОДНЯШНЯЯ, не дня решения)"


def journal_by_date(data_dir: Path) -> Tuple[Dict[str, dict], List[str]]:
    """Строки журнала по дате + порядок дат — обе величины у судьи."""
    ste = _judge()
    history, _bad = ste.load_history(Path(data_dir))
    rows = {str(r.get("cycle_date")): r for r in history}
    order = [str(r.get("cycle_date")) for r in history]
    return rows, order


# ───────────────────────── (а) состав цены и её воспроизведение ────────────────
def compose(days: Sequence[dict], rows: Dict[str, dict],
            chains: Dict[str, str]) -> dict:
    """Разложить записанную цену на НАЗВАННЫЕ слагаемые и воспроизвести её.

    Три исхода у каждого дня, и они различимы: ``reproduced`` (оценщик выдал то
    же число из записанных входов), ``divergent`` (выдал ДРУГОЕ — запись и модель
    разошлись), ``unmeasured`` с причиной (ног не записали / сеть ноги неизвестна).
    «Не измерено» никогда не складывается с «совпало».
    """
    move_cost, gas_table, slip_bps, bridge_bps = _cost_model()
    per_day: List[dict] = []
    for d in days:
        rec = rows.get(d["date"]) or {}
        turnover = float(d["turnover_usd"])
        recorded = float(d["cost_usd"])
        legs = rec.get("legs")
        slippage = turnover * slip_bps / 10_000.0
        row = {
            "date": d["date"],
            "cost_usd_recorded": round(recorded, 2),
            "turnover_usd": round(turnover, 2),
            "cost_bps_of_turnover": (round(10_000.0 * recorded / turnover, 2)
                                     if turnover else None),
            "slippage_usd": round(slippage, 2),
            "legs_recorded": (len(legs) if isinstance(legs, list) else None),
        }
        if not isinstance(legs, list) or not legs:
            # Ног не записали ⇒ газ и мост НЕ РАЗДЕЛИМЫ: одну и ту же сумму
            # объясняют разные пары (число ног, набор сетей). Подобранная пара
            # была бы догадкой, выданной за запись.
            row.update({
                "status": "unmeasured",
                "reason": "legs_not_recorded",
                "gas_usd": None, "bridge_usd": None,
                "gas_plus_bridge_usd": round(recorded - slippage, 2),
                "cost_usd_recomputed": None, "abs_diff_usd": None,
                "lump": lump_explanations(recorded - slippage, turnover,
                                          gas_table=gas_table,
                                          bridge_bps=bridge_bps),
            })
            per_day.append(row)
            continue
        unknown = sorted({str(l.get("protocol")) for l in legs
                          if str(l.get("protocol")) not in chains})
        if unknown:
            # Оценщик на неизвестной сети молча подставляет `blended` = 1.5 $.
            # Сверка с подстановкой сравнивала бы запись с догадкой и объявляла
            # согласие — ровно та подмена «не измерено» на «в порядке».
            row.update({
                "status": "unmeasured",
                "reason": "chain_unknown:" + ",".join(unknown),
                "gas_usd": None, "bridge_usd": None,
                "gas_plus_bridge_usd": round(recorded - slippage, 2),
                "cost_usd_recomputed": None, "abs_diff_usd": None,
            })
            per_day.append(row)
            continue
        touched = {chains[str(l.get("protocol"))] for l in legs}
        gas = sum(float(gas_table.get(chains[str(l.get("protocol"))],
                                      gas_table.get("blended", 1.5)))
                  for l in legs)
        bridge = (turnover * bridge_bps / 10_000.0) if len(touched) > 1 else 0.0
        recomputed = round(move_cost(list(legs), turnover, chains), 2)
        diff = abs(recomputed - recorded)
        row.update({
            "status": "reproduced" if diff <= CENT else "divergent",
            "reason": None,
            "gas_usd": round(gas, 2),
            "bridge_usd": round(bridge, 2),
            "gas_plus_bridge_usd": round(gas + bridge, 2),
            "chains_touched": sorted(touched),
            "cost_usd_recomputed": recomputed,
            "abs_diff_usd": round(diff, 4),
        })
        per_day.append(row)

    good = [r for r in per_day if r["status"] == "reproduced"]
    divergent = [r for r in per_day if r["status"] == "divergent"]
    unmeasured = [r for r in per_day if r["status"] == "unmeasured"]
    totals = {
        "gas_usd": round(sum(r["gas_usd"] for r in good), 2),
        "slippage_usd": round(sum(r["slippage_usd"] for r in good), 2),
        "bridge_usd": round(sum(r["bridge_usd"] for r in good), 2),
    }
    grand = sum(totals.values())
    shares = ({k: round(v / grand, 4) for k, v in totals.items()}
              if grand else None)

    def _bps(name: str) -> Optional[dict]:
        vals = [10_000.0 * r[name] / r["turnover_usd"] for r in good
                if r["turnover_usd"]]
        if not vals:
            return None
        return {"min": round(min(vals), 3), "median": round(median(vals), 3),
                "max": round(max(vals), 3),
                "spread": round(max(vals) - min(vals), 3)}

    by_component = {"gas_usd": _bps("gas_usd"),
                    "slippage_usd": _bps("slippage_usd"),
                    "bridge_usd": _bps("bridge_usd")}
    widest = None
    spreads = {k: (v or {}).get("spread") for k, v in by_component.items()}
    if any(s is not None for s in spreads.values()):
        widest = max((k for k, s in spreads.items() if s is not None),
                     key=lambda k: spreads[k])

    lumps = [r["lump"] for r in unmeasured if r.get("lump")]
    return {
        "per_day": per_day,
        "days_total": len(per_day),
        "cost_usd_recorded_total": round(
            sum(r["cost_usd_recorded"] for r in per_day), 2),
        # Утверждение «газ и мост неразделимы» ИЗМЕРЕНО, а не заявлено: на
        # скольких днях сумму объясняет больше одной пары «ноги × сети», и на
        # скольких ровно одна — с НАЗВАННЫМ пределом поиска, потому что
        # «единственно» без предела было бы утверждением о мире, которого
        # перебор не делал.
        "lump_ambiguous_days": sum(1 for l in lumps if l["explanations"] > 1),
        "lump_single_solution_days": sum(1 for l in lumps
                                         if l["explanations"] == 1),
        "lump_unexplained_days": sum(1 for l in lumps
                                     if l["explanations"] == 0),
        "lump_max_explanations": (max(l["explanations"] for l in lumps)
                                  if lumps else None),
        "lump_search_max_legs": LUMP_SEARCH_MAX_LEGS,
        "days_reproduced": len(good),
        "days_divergent": len(divergent),
        "days_unmeasured": len(unmeasured),
        "unmeasured_reasons": sorted({str(r["reason"]).split(":")[0]
                                      for r in unmeasured}),
        "max_abs_diff_usd": (round(max(r["abs_diff_usd"] for r in good), 4)
                             if good else None),
        # Заявление заказа «цена никем не сверялась с фактом» проверяемо ровно
        # так: если КАЖДЫЙ воспроизводимый день воспроизводится до цента, то
        # записанное число и есть выход оценщика, а не независимое наблюдение.
        "recorded_cost_is_the_estimator": bool(good) and not divergent,
        "component_totals_usd": totals,
        "component_shares": shares,
        "component_bps_of_turnover": by_component,
        "widest_bps_component": widest,
        "slippage_bps_constant": slip_bps,
        "bridge_bps_constant": bridge_bps,
        "gas_usd_per_leg_by_chain": {k: float(v) for k, v in gas_table.items()},
        # Проскальзывание в bps ПО ПОСТРОЕНИЮ не двигается — и это проверено
        # замером, а не объявлено: нулевой размах и есть доказательство, что
        # разброс «цены в bps» держат газ и мост, а не оборот.
        "slippage_bps_varies": bool((by_component["slippage_usd"] or {})
                                    .get("spread")),
    }


def lump_explanations(lump_usd: float, turnover_usd: float, *,
                      gas_table: Dict[str, float], bridge_bps: float,
                      max_legs: int = LUMP_SEARCH_MAX_LEGS) -> dict:
    """Сколько пар «число ног × набор сетей» объясняют НЕРАЗДЕЛИМУЮ сумму.

    Утверждение «газ и мост там не разделимы» прибор ПЕЧАТАЕТ — значит обязан его
    и мерить. Перебор идёт по мультимножествам цен газа (синонимы сетей с равной
    ценой неразличимы по построению: `ethereum` и `mainnet` стоят одинаково, и
    выдавать их за два ответа значило бы считать одно решение дважды) и по обоим
    состояниям моста, при том что мост заряжается ТОЛЬКО на наборе из ≥2 сетей.

    Два решения и больше ⇒ сумма не разложима **измеренно**. Ровно одно решение
    ⇒ сказано ровно это: единственно СРЕДИ НАБОРОВ НЕ ДЛИННЕЕ ``max_legs`` —
    предел поиска называется в ответе, потому что «единственно» без него было бы
    утверждением о мире, которого перебор не делал.
    """
    units = sorted({float(v) for v in gas_table.values()})
    bridge = turnover_usd * bridge_bps / 10_000.0
    found: List[dict] = []
    for n in range(1, max_legs + 1):
        for combo in itertools.combinations_with_replacement(units, n):
            distinct = len(set(combo))
            for multichain in (False, True):
                # Мост НЕ заряжается на одной сети и обязателен на нескольких:
                # разрешить обе ветки для любого набора значило бы считать
                # решения, которых оценщик выдать не может.
                if multichain != (distinct > 1):
                    continue
                total = sum(combo) + (bridge if multichain else 0.0)
                if abs(total - lump_usd) <= CENT:
                    found.append({"legs": n, "gas_units": list(combo),
                                  "multichain": multichain})
    return {
        "explanations": len(found),
        "search_max_legs": max_legs,
        "separable": len(found) == 1,
        "examples": found[:3],
    }


# ─────────────────── (б) снос ставки против дефекта аллокатора ─────────────────
def benefit_drift(days: Sequence[dict], rows: Dict[str, dict],
                  order: Sequence[str], *, horizon_days: int) -> dict:
    """Выгода дня = во что верил аллокатор + снос ставки вперёд.

    Обе половины считаются арифметикой СУДЬИ (``_deltas``/``_day_gain_usd``), а
    восстановленное форвардное окно сверяется с числом судьи на каждом дне:
    расхождение хоть на цент ⇒ вся секция объявляется НЕ ИЗМЕРЕННОЙ. Прибор,
    который восстановил окно неверно, обязан сказать это, а не печатать свои
    слагаемые как разложение чужого числа.
    """
    ste = _judge()
    idx = {d: i for i, d in enumerate(order)}
    per_day: List[dict] = []
    worst_diff = 0.0
    unreconciled: List[str] = []
    for d in days:
        rec = rows.get(d["date"]) or {}
        deltas = ste._deltas(rec)
        ex_ante_map = observed(rec, "apy_evidenced_pct", kind=dict) or {}
        i = idx.get(d["date"])
        forward = [rows[x] for x in order[i + 1:i + 1 + horizon_days]] \
            if i is not None else []
        checked = 0
        observed_benefit = 0.0
        leg_drift: Dict[str, float] = {p: 0.0 for p in deltas}
        for frec in forward:
            gain, _missing = ste._day_gain_usd(
                deltas, observed(frec, "apy_evidenced_pct", kind=dict) or {})
            if gain is None:
                continue
            checked += 1
            observed_benefit += gain
            fmap = observed(frec, "apy_evidenced_pct", kind=dict) or {}
            for p, dv in deltas.items():
                ex = ex_ante_map.get(p)
                if ex is None:
                    continue
                leg_drift[p] += dv * (float(fmap[p]) - float(ex)) / 100.0 / 365.0
        day_rate_ex_ante, missing_ex_ante = ste._day_gain_usd(deltas, ex_ante_map)
        ex_ante_total = (day_rate_ex_ante * checked
                         if day_rate_ex_ante is not None else None)
        diff = abs(observed_benefit - float(d["benefit_usd"]))
        worst_diff = max(worst_diff, diff)
        if diff > 0.02:
            unreconciled.append(d["date"])
        worst_leg = (min(leg_drift.items(), key=lambda kv: kv[1])
                     if leg_drift else None)
        # Различитель заказа: знак выгоды по ставкам САМОГО дня решения.
        # ex ante ≤ 0 ⇒ книга была хуже уже по данным аллокатора (дефект);
        # ex ante > 0 ⇒ ход был верен по его данным, а вперёд ставка ушла.
        if float(d["benefit_usd"]) >= 0.0:
            basis = None
        elif ex_ante_total is None:
            basis = "unmeasured:ex_ante_unpriced:" + ",".join(missing_ex_ante)
        elif ex_ante_total > 0.0:
            basis = "forward_rate_drift"
        else:
            basis = "allocator_proposed_a_worse_book"
        per_day.append({
            "date": d["date"],
            "benefit_usd_observed": round(float(d["benefit_usd"]), 2),
            "benefit_usd_reconstructed": round(observed_benefit, 2),
            "reconciles_with_judge": diff <= 0.02,
            "benefit_usd_ex_ante": (round(ex_ante_total, 2)
                                    if ex_ante_total is not None else None),
            "drift_usd": (round(observed_benefit - ex_ante_total, 2)
                          if ex_ante_total is not None else None),
            "forward_days_checked": checked,
            "gain_pp_claimed": observed_number(rec, "gain_pp"),
            "legs_moved": sorted(deltas),
            "worst_drift_leg": (worst_leg[0] if worst_leg else None),
            "worst_drift_usd": (round(worst_leg[1], 2) if worst_leg else None),
            "negative_benefit": float(d["benefit_usd"]) < 0.0,
            "basis": basis,
        })

    if unreconciled:
        return {
            "measured": False,
            "reason": ("восстановленное форвардное окно расходится с числом судьи "
                       f"на дн.: {', '.join(unreconciled)} (максимум "
                       f"{worst_diff:.4f} $) — слагаемые описывали бы ДРУГОЕ число"),
            "per_day": per_day,
            "max_abs_diff_usd": round(worst_diff, 4),
        }

    drifts = [r["drift_usd"] for r in per_day if r["drift_usd"] is not None]
    negatives = [r for r in per_day if r["negative_benefit"]]
    ex_ante_sum = sum(r["benefit_usd_ex_ante"] for r in per_day
                      if r["benefit_usd_ex_ante"] is not None)
    return {
        "measured": True,
        "per_day": per_day,
        "max_abs_diff_usd": round(worst_diff, 4),
        "benefit_usd_observed_total": round(
            sum(r["benefit_usd_observed"] for r in per_day), 2),
        "benefit_usd_ex_ante_total": round(ex_ante_sum, 2),
        "drift_usd_total": round(sum(drifts), 2) if drifts else None,
        "days_drift_negative": sum(1 for v in drifts if v < 0.0),
        "days_drift_positive": sum(1 for v in drifts if v > 0.0),
        "negative_benefit_days": [
            {"date": r["date"], "benefit_usd": r["benefit_usd_observed"],
             "benefit_usd_ex_ante": r["benefit_usd_ex_ante"],
             "gain_pp_claimed": r["gain_pp_claimed"],
             "legs_moved": r["legs_moved"],
             "worst_drift_leg": r["worst_drift_leg"],
             "worst_drift_usd": r["worst_drift_usd"],
             "basis": r["basis"]}
            for r in negatives],
        "negative_days_by_basis": {
            basis: sorted(r["date"] for r in negatives if r["basis"] == basis)
            for basis in sorted({str(r["basis"]) for r in negatives})},
    }


# ─────────────────────── (в) контрфакт: цена = уровень в bps ───────────────────
def _set_bps(level_bps: float):
    """Заменить цену КАЖДОЙ строки на ``level_bps`` от её же оборота.

    Пропорция оборота выбрана не для красоты: это единственная форма, в которой
    «медиана наблюдённой цены» вообще определена — сама наблюдённая цена и
    выражена в bps оборота. Строка без оборота не трогается: подставить ей число
    значило бы придумать ход, которого не было.
    """
    def mutate(rec: dict) -> None:
        turnover = rec.get("turnover_usd")
        if turnover is None:
            return
        try:
            rec["cost_usd"] = float(turnover) * level_bps / 10_000.0
        except (TypeError, ValueError):
            return
    return mutate


def cost_level_sweep(data_dir: Path, *, horizon_days: int,
                     gates: Sequence[str], median_bps: Optional[float],
                     slippage_bps: float) -> dict:
    """Сколько ACT-дней вернул бы критерию КАЖДЫЙ уровень цены.

    Уровни — в bps оборота, и три из них названы: записанная цена как есть,
    наблюдённая МЕДИАНА (прямой вопрос заказа) и ОДНО проскальзывание (цена мира,
    где газ бесплатен и сеть одна). Последний уровень и есть проверяемый пол:
    ниже него цена в этой модели опуститься не может ничем, кроме смены самой
    константы.
    """
    csp = _neighbour()
    rows: List[dict] = []

    def _at(level: Optional[float], label: str, note: str) -> dict:
        mutate = _set_bps(level) if level is not None else None
        row = csp._variant(Path(data_dir), label=label, input_name="cost_level",
                           how=note, mutate=mutate, horizon_days=horizon_days,
                           gates=gates, factor=level)
        rows.append(row)
        return row

    as_is = _at(None, "цена как записана", "журнал не трогается")
    named: Dict[str, Optional[dict]] = {"as_is": as_is}
    if median_bps is not None:
        named["median"] = _at(
            median_bps, f"цена = медиана {median_bps:g} bps",
            "`cost_usd` = медиана наблюдённых bps × оборот строки (копия каталога)")
    named["slippage_only"] = _at(
        slippage_bps, f"цена = одно проскальзывание {slippage_bps:g} bps",
        "`cost_usd` = SLIPPAGE_BPS_STABLE × оборот (газ и мост обнулены)")
    for level in BPS_SWEEP:
        _at(level, f"цена = {level:g} bps", "`cost_usd` = уровень × оборот строки")

    flip = _bisect_bps(data_dir, horizon_days=horizon_days, gates=gates)
    # Сторож монотонности соседа читает `flip_factor` и снимает публикацию,
    # обнуляя ИМЕННО его. Оставить рядом живой `flip_bps` значило бы напечатать
    # снятое с публикации число как измеренное — две копии одной величины,
    # спорящие между собой молча.
    csp._check_flip_against_sweep(flip, [r for r in rows if r.get("factor")])
    if not flip.get("measured"):
        flip["flip_bps"] = None

    answers = {(r["act_days_to_criterion"], r["closes_positively"]) for r in rows}
    baseline_closes = bool(as_is["closes_positively"])
    return {
        "rows": rows,
        "named": {k: (v or {}).get("act_days_to_criterion") for k, v in named.items()},
        "named_closes": {k: (v or {}).get("closes_positively")
                         for k, v in named.items()},
        "median_bps": median_bps,
        "slippage_bps": slippage_bps,
        "flip_level_bps": flip,
        "max_act_days": max(r["act_days_to_criterion"] for r in rows),
        "sensitivity_control": {
            "distinct_answers": len(answers),
            "answer_varies": len(answers) > 1,
            "baseline_closes": baseline_closes,
            "binding": not baseline_closes,
            "holds": baseline_closes or len(answers) > 1,
            "note": ("ответ обязан меняться хотя бы под одним уровнем цены; "
                     "неизменный НОЛЬ означал бы, что уровень до судьи не "
                     "доходит. Контроль связывает только нулевой ответ"),
        },
    }


def _bisect_bps(data_dir: Path, *, horizon_days: int,
                gates: Sequence[str]) -> dict:
    """Уровень цены в bps, НИЖЕ которого критерий закрывается, либо «не найден».

    Валюта здесь прямая — bps оборота, — а не коэффициент к записанному числу
    ([ADR-388] мерил коэффициент). Коэффициент отвечает «во сколько раз дешевле
    сегодняшней записи», уровень — «дешевле КАКОГО ЧИСЛА», и только второй можно
    поставить рядом с константой модели.
    """
    csp = _neighbour()
    lo, hi = BPS_BISECT_BRACKET

    def closes(level: float) -> bool:
        tmp = csp._perturbed_dir(Path(data_dir), _set_bps(level))
        try:
            return csp._answer_for(tmp, horizon_days=horizon_days,
                                   gates=gates)["closes_positively"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    lo_closes, hi_closes = closes(lo), closes(hi)
    if not lo_closes or hi_closes:
        return {"flip_bps": None, "measured": False, "bracket": [lo, hi],
                "reason": (f"перелом не найден в скобке [{lo:g}, {hi:g}] bps: край "
                           f"{lo:g} закрывает={lo_closes}, край {hi:g} "
                           f"закрывает={hi_closes}")}
    left, right = lo, hi
    for _ in range(_BISECT_STEPS):
        mid = (left + right) / 2.0
        if closes(mid):
            left = mid
        else:
            right = mid
    return {"flip_bps": round((left + right) / 2.0, 5), "measured": True,
            "bracket": [lo, hi], "bisect_steps": _BISECT_STEPS,
            "resolution": float(f"{abs(right - left):.2g}"),
            "direction": "closes_below",
            # Ключ `flip_factor` существует ради сторожа монотонности соседа:
            # он сверяет точки сметания с ПЕРЕЛОМОМ и читает именно это имя.
            "flip_factor": round((left + right) / 2.0, 5)}


# ──────────────────────────────────── замер ────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            with_sweep: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    csp = _neighbour()
    gates = csp._gate_names()

    try:
        days, ctx = csp.scorable_days(data_dir)
        rows, order = journal_by_date(data_dir)
    except Exception as exc:  # noqa: BLE001 — третий исход, а не ноль
        return _unmeasured(now, f"судья не отвечает на этом каталоге: {exc}")

    if not days:
        return _unmeasured(
            now,
            ("в журнале нет НИ ОДНОГО дня, который критерий №3 считает "
             f"(оценённых дней 0 из {ctx.get('journal_days')} дн. журнала) — "
             "раскладывать нечего, и «цена не при чём» отсюда НЕ следует"),
            context=ctx)

    horizon = int(ctx["horizon_days"])
    chains, chains_source = chain_map(data_dir)
    parts = compose(days, rows, chains)
    drift = benefit_drift(days, rows, order, horizon_days=horizon)

    bps = [10_000.0 * d["cost_usd"] / d["turnover_usd"]
           for d in days if d["turnover_usd"]]
    median_bps = round(median(bps), 4) if bps else None
    _mc, _gas, slip_bps, _bridge = _cost_model()

    sweep = (cost_level_sweep(data_dir, horizon_days=horizon, gates=gates,
                              median_bps=median_bps, slippage_bps=slip_bps)
             if with_sweep else {"measured": False, "reason": "--no-sweep"})

    if with_sweep and not sweep["sensitivity_control"]["holds"]:
        return _unmeasured(
            now,
            ("ответ НЕ ИЗМЕНИЛСЯ ни под одним из "
             f"{len(sweep['rows'])} уровней цены — значит уровень до судьи не "
             "доходит, и ноль ACT-дней говорит о проводке, а не о мире"),
            context=ctx)

    findings = _findings(parts, drift, sweep, slip_bps)
    status = STATUS_CRITICAL if any(f["severity"] == "critical" for f in findings) \
        else (STATUS_WARNING if findings else STATUS_OK)

    return {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": status,
        "mode": "ADVISORY",
        "order": ORDER,
        "headline": _headline(parts, drift, sweep, slip_bps),
        "journal": ctx,
        "chains_source": chains_source,
        "observed_cost_bps": ({"min": round(min(bps), 2), "median": median_bps,
                               "max": round(max(bps), 2)} if bps else None),
        "composition": parts,
        "benefit_drift": drift,
        "cost_level_sweep": sweep,
        "findings": findings,
        "what_it_does_not_prove": [
            "не измеряет РЫНОЧНУЮ цену перекладки: на бумажной стадии исполнения "
            "нет, и независимого наблюдения цены не существует ни одного",
            "не утверждает, что константы стоимости следует понизить — это вход "
            "денежного пути и предмет №1 границы ADR-285",
            "не разделяет газ и мост там, где ноги не записаны: одну сумму "
            "объясняют разные пары (число ног, набор сетей)",
            "карта сетей СЕГОДНЯШНЯЯ, не дня решения: совпадение до цента — довод "
            "в пользу её неподвижности, а не запись о ней",
            "ничего не говорит о днях вне окна журнала",
        ],
    }


def _unmeasured(now: datetime, reason: str,
                context: Optional[dict] = None) -> dict:
    return {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "mode": "ADVISORY",
        "order": ORDER,
        "headline": f"НЕ ИЗМЕРЕНО: {reason}",
        "unmeasured_reason": reason,
        "journal": context or {},
        "composition": {},
        "benefit_drift": {},
        "cost_level_sweep": {},
        "findings": [],
        "what_it_does_not_prove": [
            "«не измерено» не есть «состав цены в порядке» и не есть «не в порядке»",
        ],
    }


def _headline(parts: dict, drift: dict, sweep: dict, slip_bps: float) -> str:
    flip = (sweep.get("flip_level_bps") or {}) if isinstance(sweep, dict) else {}
    named = (sweep.get("named") or {}) if isinstance(sweep, dict) else {}
    shares = parts.get("component_shares") or {}
    head = (f"записанная цена ВОСПРОИЗВЕДЕНА оценщиком до цента на "
            f"{parts['days_reproduced']} дн. из {parts['days_total']} "
            f"(расхождений {parts['days_divergent']}, не измерено "
            f"{parts['days_unmeasured']}) ⇒ `cost_usd` есть ВЫХОД МОДЕЛИ, а не "
            f"наблюдение")
    if shares:
        head += (f"; состав: газ {shares.get('gas_usd')}, проскальзывание "
                 f"{shares.get('slippage_usd')}, мост {shares.get('bridge_usd')}")
    if flip.get("measured"):
        head += (f"; критерий закрывается лишь ниже {flip['flip_bps']:g} bps "
                 f"оборота, а одно проскальзывание стои́т {slip_bps:g} bps "
                 f"(×{slip_bps / flip['flip_bps']:.2f})")
    if named.get("median") is not None:
        head += f"; при медианной цене ACT-дней {named['median']}"
    return head


def _findings(parts: dict, drift: dict, sweep: dict,
              slip_bps: float) -> List[dict]:
    out: List[dict] = []
    if parts.get("recorded_cost_is_the_estimator"):
        out.append({
            "severity": "critical",
            "key": "recorded_cost_is_not_an_observation",
            "text": (f"на всех {parts['days_reproduced']} дн., где записаны входы, "
                     "оценщик `_move_cost_usd` выдаёт из них РОВНО записанное "
                     f"число (максимум расхождения {parts['max_abs_diff_usd']} $). "
                     "Значит «наблюдённая цена хода» наблюдением не является: это "
                     "выход той же модели, и утверждение «цена должна упасть "
                     "в N раз» — утверждение о трёх её константах, а не о мире. "
                     "Независимого наблюдения цены в системе нет ни одного"),
        })
    if parts.get("days_divergent"):
        bad = [r["date"] for r in parts.get("per_day") or []
               if r["status"] == "divergent"]
        out.append({
            "severity": "critical",
            "key": "recorded_cost_diverges_from_the_estimator",
            "text": (f"на {len(bad)} дн. записанная цена НЕ воспроизводится из "
                     "собственных записанных входов: " + ", ".join(bad) +
                     ". Либо запись, либо модель изменились после решения — и "
                     "число, которое заряжает критерий, не принадлежит ни одной "
                     "из них целиком"),
        })
    flip = (sweep.get("flip_level_bps") or {}) if isinstance(sweep, dict) else {}
    if flip.get("measured") and flip["flip_bps"] < slip_bps:
        out.append({
            "severity": "critical",
            "key": "slippage_constant_alone_exceeds_the_budget",
            "text": (f"критерий №3 закрывается положительно только ниже "
                     f"{flip['flip_bps']:g} bps оборота, а ОДНО проскальзывание — "
                     f"константа `SLIPPAGE_BPS_STABLE` = {slip_bps:g} bps — уже "
                     f"в {slip_bps / flip['flip_bps']:.2f} раза дороже. То есть "
                     "мир, где газ бесплатен и сеть одна, критерий тоже НЕ "
                     "закрывает: связывает не число ног и не сеть, а плоская "
                     "константа проскальзывания, которую никто не наблюдал"),
        })
    named = (sweep.get("named") or {}) if isinstance(sweep, dict) else {}
    if named.get("median") == 0 and sweep.get("median_bps") is not None:
        out.append({
            "severity": "warning",
            "key": "median_cost_returns_no_act_day",
            "text": (f"прямой вопрос заказа: при цене, равной наблюдённой медиане "
                     f"{sweep['median_bps']:g} bps на КАЖДОМ дне, критерию "
                     "возвращается 0 ACT-дн. Значит «дорого на нескольких днях» "
                     "исключено замером: дорого РОВНО ВЕЗДЕ, и разброс цены "
                     "по дням знак критерия не держит"),
        })
    if parts.get("days_unmeasured"):
        out.append({
            "severity": "warning",
            "key": "composition_unmeasurable_where_legs_were_not_recorded",
            "text": (f"состав цены НЕ ИЗМЕРЕН на {parts['days_unmeasured']} дн. из "
                     f"{parts['days_total']}: причины — "
                     f"{', '.join(parts.get('unmeasured_reasons') or ['—'])}. "
                     "Неразделимость ИЗМЕРЕНА, а не заявлена: сумму «газ + мост» "
                     f"объясняет больше одной пары «ноги × сети» на "
                     f"{parts.get('lump_ambiguous_days')} дн. (до "
                     f"{parts.get('lump_max_explanations')} решений), ровно одна "
                     f"пара — на {parts.get('lump_single_solution_days')} дн., и "
                     "это «единственно» верно лишь СРЕДИ НАБОРОВ не длиннее "
                     f"{parts.get('lump_search_max_legs')} ног. Подобранная пара "
                     "была бы догадкой, выданной за запись"),
        })
    if drift.get("measured") is False:
        out.append({
            "severity": "critical",
            "key": "benefit_reconstruction_does_not_reconcile",
            "text": "разложение выгоды снято: " + str(drift.get("reason")),
        })
    elif drift.get("measured"):
        worse = (drift.get("negative_days_by_basis") or {}).get(
            "allocator_proposed_a_worse_book") or []
        if worse:
            out.append({
                "severity": "critical",
                "key": "allocator_proposed_a_worse_book",
                "text": (f"{len(worse)} дн. предлагали книгу, которая была хуже "
                         "уже по ставкам САМОГО дня решения: " + ", ".join(worse) +
                         ". Это не снос ставки вперёд, а дефект предложения — "
                         "различает их знак выгоды ex ante"),
            })
        drift_total = drift.get("drift_usd_total")
        ex_ante = drift.get("benefit_usd_ex_ante_total")
        if drift_total is not None and ex_ante is not None:
            out.append({
                "severity": "warning",
                "key": "forward_drift_is_small_beside_the_cost",
                "text": (f"снос ставки вперёд за всё окно = {drift_total} $ при "
                         f"вере аллокатора {ex_ante} $ и заряженной цене "
                         f"{parts.get('cost_usd_recorded_total')} $. Даже "
                         "безошибочный прогноз (снос = 0) знак критерия НЕ "
                         "меняет: дело не в качестве предсказания ставок"),
            })
    return out


# ──────────────────────────────────── отчёт ────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    if str(doc.get("status")) == STATUS_UNMEASURED:
        return [f"   цена СОСТАВА хода (заказ {ORDER}): НЕ ИЗМЕРЕНО",
                f"   ⚠️ {doc.get('unmeasured_reason', 'причина не названа')}"]
    out = [f"   цена СОСТАВА хода (заказ {ORDER}): {doc.get('status')}"]
    out.append(f"   {doc.get('headline')}")

    parts = observed(doc, "composition", kind=dict) or {}
    obs = observed(doc, "observed_cost_bps", kind=dict) or {}
    if parts.get("days_unmeasured"):
        _lump_note = (f"       неразделимость ИЗМЕРЕНА: сумму «газ + мост» объясняют "
                      f"несколько пар на {parts.get('lump_ambiguous_days')} дн. "
                      f"(максимум {parts.get('lump_max_explanations')} решений), "
                      f"ровно одна пара — на {parts.get('lump_single_solution_days')} дн. "
                      f"(предел перебора {parts.get('lump_search_max_legs')} ног), "
                      f"ни одной — на {parts.get('lump_unexplained_days')} дн.")
    else:
        _lump_note = None
    out.append(f"   (а) воспроизведено {parts.get('days_reproduced')} дн. · "
               f"расхождений {parts.get('days_divergent')} · НЕ ИЗМЕРЕНО "
               f"{parts.get('days_unmeasured')} "
               f"({', '.join(parts.get('unmeasured_reasons') or ['—'])}); "
               f"наблюдённая цена {obs.get('min')}…{obs.get('max')} bps при "
               f"медиане {obs.get('median')}")
    tot = parts.get("component_totals_usd") or {}
    sh = parts.get("component_shares") or {}
    out.append(f"       слагаемые (по воспроизводимым дн.): газ {tot.get('gas_usd')} $ "
               f"({sh.get('gas_usd')}) · проскальзывание {tot.get('slippage_usd')} $ "
               f"({sh.get('slippage_usd')}) · мост {tot.get('bridge_usd')} $ "
               f"({sh.get('bridge_usd')})")
    comp = parts.get("component_bps_of_turnover") or {}
    out.append(f"       в bps оборота: проскальзывание "
               f"{(comp.get('slippage_usd') or {}).get('median')} (размах "
               f"{(comp.get('slippage_usd') or {}).get('spread')} ⇒ меняется: "
               f"{'ДА' if parts.get('slippage_bps_varies') else 'НЕТ'}) · газ "
               f"{(comp.get('gas_usd') or {}).get('min')}…"
               f"{(comp.get('gas_usd') or {}).get('max')} · мост "
               f"{(comp.get('bridge_usd') or {}).get('min')}…"
               f"{(comp.get('bridge_usd') or {}).get('max')}; шире всего гуляет "
               f"«{parts.get('widest_bps_component')}»")
    if _lump_note:
        out.append(_lump_note)

    drift = observed(doc, "benefit_drift", kind=dict) or {}
    if drift.get("measured"):
        out.append(f"   (б) выгода {drift.get('benefit_usd_observed_total')} $ = вера "
                   f"аллокатора {drift.get('benefit_usd_ex_ante_total')} $ + снос "
                   f"ставки {drift.get('drift_usd_total')} $ (сноса вниз "
                   f"{drift.get('days_drift_negative')} дн., вверх "
                   f"{drift.get('days_drift_positive')} дн.; сверка с судьёй — "
                   f"максимум {drift.get('max_abs_diff_usd')} $)")
        for row in drift.get("negative_benefit_days") or []:
            out.append(f"       {row['date']}: выгода {row['benefit_usd']} $, ex ante "
                       f"{row['benefit_usd_ex_ante']} $ (заявлен gain "
                       f"{row['gain_pp_claimed']} пп) ⇒ ОСНОВАНИЕ «{row['basis']}»; "
                       f"хуже всех снесло `{row['worst_drift_leg']}` на "
                       f"{row['worst_drift_usd']} $")
    else:
        out.append(f"   (б) НЕ ИЗМЕРЕНО: {drift.get('reason')}")

    sweep = observed(doc, "cost_level_sweep", kind=dict) or {}
    named = sweep.get("named") or {}
    flip = sweep.get("flip_level_bps") or {}
    out.append(f"   (в) ACT-дней до критерия: цена как записана "
               f"{named.get('as_is')} · медиана {sweep.get('median_bps')} bps → "
               f"{named.get('median')} · одно проскальзывание "
               f"{sweep.get('slippage_bps')} bps → {named.get('slippage_only')} · "
               f"максимум по всем уровням {sweep.get('max_act_days')}")
    if flip.get("measured"):
        mono = flip.get("monotonicity_control") or {}
        out.append(f"       перелом на {flip.get('flip_bps')} bps оборота "
                   f"(точность {flip.get('resolution')}; сверено со сметанием в "
                   f"{mono.get('sweep_points_checked')} точк(е/ах), расхождений "
                   f"{len(mono.get('disagreed') or [])})")
    elif flip:
        out.append(f"       перелом НЕ НАЙДЕН: {flip.get('reason')}")
    ctrl = sweep.get("sensitivity_control") or {}
    out.append(f"   [КОНТРОЛЬ] различных ответов под уровнями "
               f"{ctrl.get('distinct_answers')} ⇒ ответ меняется: "
               f"{'ДА' if ctrl.get('answer_varies') else 'НЕТ'} · связывает "
               f"{'ДА' if ctrl.get('binding') else 'НЕТ (базовый прогон уже закрывает критерий)'}")
    out.append(f"   [ОПОРА] карта сетей — {doc.get('chains_source')}")
    for f in doc.get("findings") or []:
        out.append(f"   [{f['severity'].upper()}] {f['text']}")
    out.append("   НЕ ДОКЛАДЫВАЕТ: " + " · ".join(
        doc.get("what_it_does_not_prove") or ["границы не названы"]))
    out.append("   ADVISORY: константы стоимости, гейты, пороги оборота, "
               "`RiskPolicy` v1.0, стоп-кран, писатель журнала и живой трек НЕ "
               "трогаются; живой каталог на запись не открывается — судья зовётся "
               "с `write=False`, уровни цены идут во временной копии")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, with_sweep: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, with_sweep=with_sweep)
    if write:
        atomic_save(doc, str(base / "data" / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", help="каталог данных (умолчание — data/ репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--no-sweep", action="store_true",
                    help="не мерить сметание уровней (быстро, но ответ НЕПОЛОН)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    args = ap.parse_args(argv)

    if args.data_dir:
        doc = measure(Path(args.data_dir), with_sweep=not args.no_sweep)
        if not args.no_write:
            atomic_save(doc, str(Path(args.data_dir) / OUTPUT_FILENAME))
    else:
        doc = run(write=not args.no_write, with_sweep=not args.no_sweep)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n".join(format_report(doc)))
    return {STATUS_OK: 0, STATUS_WARNING: 0,
            STATUS_CRITICAL: 1}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
