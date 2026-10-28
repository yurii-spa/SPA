"""Предложение НИКОГДА не урезается до ДОПУСТИМОГО размера — потолок читается как фильтр (ADR-848).

Вопрос, которого не задавал никто
---------------------------------
Теневой советник по перекладке (ADR-060) за 84 дня наблюдения не сказал ``ACT``
ни разу. Два прибора уже спрашивали ПОЧЕМУ, и оба — про СНЯТИЕ стен:

* ``shadow_trigger_eval.arming_blockade`` — какой набор гейтов покрывает каждый
  существенный день (ADR-228/877);
* ``monitoring.arming_wall_order`` — сколько дней освободится, если объявленный
  набор гейтов ПРИНУДИТЕЛЬНО пройдёт (ADR-305), и он же прямо отказывается
  утверждать, что аллокатор предложил бы то же самое при других порогах:
  «цель считается заново, и её пересчёт этому прибору не принадлежит».

Этот прибор спрашивает ОБРАТНОЕ и потому не дублирует ни один из двух: потолок
НЕ снимается, а ход УРЕЗАЕТСЯ до него. Разница не косметическая, а в направлении
оценки:

====================  ===========================  ===========================
                      снять стену                  урезать ход
====================  ===========================  ===========================
что меряется          ПОТОЛОК достижимости         НИЖНЯЯ граница достижимости
прошло ⇒              ничего не доказано           ход был ВОЗМОЖЕН
не прошло ⇒           ветка закрыта                ничего не доказано
====================  ===========================  ===========================

Потолок, прошедший проверку, не доказывает ничего: он получен отменой защиты,
которой владелец не отменял. Урезанный ход — это РЕАЛЬНО допустимое действие
(подмножество той же перекладки), поэтому его прохождение есть доказательство,
а не оценка сверху.

Почему урезанный ход допустим и почему его выигрыш считается ТОЧНО
------------------------------------------------------------------
Урезание — это ``target_k = current + k·(target − current)`` при ``k ∈ (0, 1]``.
Книга остаётся сбалансированной (сумма дельт сохраняет ноль), ни одна позиция не
уходит в минус, состав ног не меняется. Смешанная ставка линейна по позициям,
поэтому ``gain_k = k · gain`` — ТОЧНО, а не приближённо.

Стоимость урезанного хода берётся ПОЛНОЙ, стоимостью целого хода. Это не лень, а
направление ошибки: газ заряжается за ногу (ног столько же), проскальзывание и
мост пропорциональны обороту (он МЕНЬШЕ), значит ``cost_k ≤ cost``, значит

    payback_k = 365·cost_pp_k / gain_k  ≤  365·cost_pp / (k·gain) = payback / k

Прибор печатает ПРАВУЮ часть. Она ЗАВЫШАЕТ окупаемость, то есть ошибается против
находки: «окупается» здесь означает «окупается и на завышенной оценке».

Что прибор НЕ утверждает — граница названа вслух
------------------------------------------------
1. **Он не утверждает, что аллокатор предложил бы именно это.** Оптимизатор под
   ограничением оборота выбрал бы цель заново и, скорее всего, ЛУЧШУЮ: урезание
   пропорционально, а не оптимально. Поэтому измеренное есть нижняя граница
   достижимости, и ровно в этом её ценность.
2. **Он не предсказывает исход хода.** «Разрешение сработало бы» — про гейты, а
   не про прибыль; окупаемость считается по ОБЕЩАННОМУ выигрышу того дня,
   точность обещаний меряет другой прибор (``apy_forecast_accuracy``).
3. **Бюджеты оборота за день и за неделю зависят от входа, которого история не
   несёт.** Поэтому ось «взвод без разрешения» различает «открыто» и «не решено
   бюджетом» и НИКОГДА не выдаёт второе за первое. На оси РАЗРЕШЕНИЯ вопрос
   снимается по построению: разрешение владельца (ADR-334) снимает ровно
   ограничители ЧАСТОТЫ, то есть ровно те гейты, про которые история молчит.

ADVISORY. Ни одного порога не меняет, ``ready_to_arm`` не трогает, капитал не
двигает, RiskPolicy не касается. Правило разрешения не переписывает — зовёт
ОДНУ дверь :func:`spa_core.paper_trading.cio_trial.grant_blockers`, которой тот
же цикл судит живой ход.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.admissible_size")

_EPS = 1e-9

#: Вердикт оси РАЗРЕШЕНИЯ владельца на пробный ход (ADR-334).
ADM_FIRES = "GRANT_FIRES_AT_ADMISSIBLE_SIZE"
ADM_NEVER = "NEVER_AT_ADMISSIBLE_SIZE"
ADM_MOOT = "NOT_BLOCKED"
ADM_UNMEASURED = "UNMEASURED"

#: Классы записи. Имена — часть контракта: по ним считает перепись и читает
#: шаг 0-офис, переименование = смена вопроса.
CLASS_FIRES = "fires_at_admissible_size"
CLASS_ECON_FAILS = "economics_fail_when_cut"
CLASS_NOT_SIZE_REFUSED = "refused_by_something_size_cannot_fix"
CLASS_ALREADY_ADMISSIBLE = "proposal_already_within_caps"
CLASS_NO_PROPOSAL = "nothing_material_to_move"
CLASS_UNMEASURED = "unmeasured"

#: Ось «взвод БЕЗ разрешения»: бюджеты дня и недели зависят от оборота, которого
#: запись не несёт, поэтому исходов три, а не два (инв. #17).
ARM_OPEN = "open_at_admissible_size"
ARM_UNDECIDED = "undecided_by_turnover_budget"
ARM_BLOCKED = "blocked_at_admissible_size"

#: Гейты, чьё состояние НЕ меняется от урезания хода: состав ног тот же, возраст
#: позиций тот же, наблюдённость цели та же, срок с прошлого хода тот же.
_SIZE_INVARIANT_GATES = ("cooldown_ok", "min_hold_ok", "target_fully_evidenced")
#: Гейты-бюджеты: при МЕНЬШЕМ обороте пройденный остаётся пройденным
#: (монотонность), а отказавший становится НЕ РЕШЁННЫМ, а не пройденным.
_BUDGET_GATES = ("week_turnover_ok", "day_turnover_ok")
#: Гейты, которые урезание закрывает ПО ПОСТРОЕНИЮ: оборот равен допустимому.
_SIZE_CAP_GATES = ("move_turnover_ok", "move_amount_ok")


def admissible_turnover_usd(capital_usd: float, params) -> float:
    """Сколько РАЗРЕШЕНО двинуть одним ходом — минимум двух потолков РАЗМЕРА.

    Бюджеты дня и недели сюда НЕ входят намеренно: они зависят от уже
    прокрученного оборота, то есть не являются потолком ЭТОГО хода. Их судьба —
    в монотонном выводе (``_BUDGET_GATES``) и в разрешении владельца, которое
    снимает ровно их.
    """
    return min(float(params.max_turnover_per_move) * float(capital_usd),
               float(params.max_trade_usd))


def cut_to_admissible(rec: dict, params) -> Tuple[Optional[dict], str]:
    """Урезать ЗАПИСАННОЕ предложение до допустимого размера. Третий исход — ``(None, причина)``.

    Возврат ``(замер, "")`` либо ``(None, причина)``. Причина НАЗЫВАЕТСЯ всегда:
    «не измерено» без причины неотличимо от «мерить было нечего».
    """
    capital = rec.get("capital_usd")
    turnover = rec.get("turnover_usd")
    gain = rec.get("gain_pp")
    if not capital or float(capital) <= 0:
        return None, "капитал дня не записан"
    if turnover is None or gain is None:
        return None, "оборот или выигрыш предложения не записан"
    capital = float(capital)
    turnover = float(turnover)
    gain = float(gain)
    if turnover <= 0:
        return None, "оборот предложения ноль — урезать нечего"

    adm = admissible_turnover_usd(capital, params)
    k = adm / turnover
    if k >= 1.0 - _EPS:
        return {"k": 1.0, "admissible_usd": round(adm, 2), "already_admissible": True,
                "gain_pp_cut": round(gain, 6), "payback_days_bound": rec.get("payback_days"),
                "turnover_usd_cut": round(turnover, 2)}, ""

    # Состав ног обязан выжить урезание: нога ниже пыли выпадает из предложения
    # (`_legs`, `min_leg_frac`), то есть предложение становится ДРУГИМ, и
    # линейность выигрыша про него уже ничего не говорит.
    legs = rec.get("legs")
    if isinstance(legs, list) and legs:
        dust = []
        for leg in legs:
            delta = leg.get("delta_usd")
            if delta is None:
                return None, "у ноги предложения нет величины — урезание не измерено"
            if abs(float(delta)) * k < float(params.min_leg_frac) * capital - _EPS:
                dust.append(str(leg.get("protocol")))
        if dust:
            return None, ("урезание обращает в пыль ноги {} — предложение станет "
                          "ДРУГИМ, линейность выигрыша о нём не говорит".format(sorted(dust)))

    payback = rec.get("payback_days")
    bound = (float(payback) / k) if payback is not None else None
    return {"k": round(k, 6), "admissible_usd": round(adm, 2), "already_admissible": False,
            "gain_pp_cut": round(gain * k, 6), "payback_days_bound":
            (round(bound, 2) if bound is not None else None),
            "turnover_usd_cut": round(adm, 2)}, ""


def _arming_axis(gates: Dict[str, bool], cut: dict, params) -> Tuple[str, List[str]]:
    """Ось «взвод БЕЗ разрешения владельца»: три исхода, бюджеты не угаданы."""
    blocked: List[str] = []
    undecided: List[str] = []
    for gate in _SIZE_INVARIANT_GATES:
        if not gates.get(gate, True):
            blocked.append(gate)
    gain_cut = cut.get("gain_pp_cut")
    if gain_cut is None or float(gain_cut) < float(params.min_gain_pp) - _EPS:
        blocked.append("gain_above_band")
    bound = cut.get("payback_days_bound")
    if bound is None or float(bound) > float(params.max_payback_days) + _EPS:
        blocked.append("payback_within_horizon")
    for gate in _BUDGET_GATES:
        if not gates.get(gate, True):
            undecided.append(gate)
    if blocked:
        return ARM_BLOCKED, sorted(blocked)
    if undecided:
        return ARM_UNDECIDED, sorted(undecided)
    return ARM_OPEN, []


def judge_record(rec: dict, *, params, min_gain_pp: float,
                 gate_state_fn: Callable[[dict], Tuple[Optional[Dict[str, bool]], str]],
                 grant_blockers_fn: Callable[..., Tuple[Optional[list], Optional[str]]],
                 ) -> dict:
    """Класс ОДНОЙ записи: сработало бы разрешение, будь ход урезан до допустимого.

    Правило разрешения НЕ переписывается — зовётся ``grant_blockers_fn``, та же
    дверь, которой цикл судит живой ход. Инъекция есть и у неё, и у чтения
    состояния гейтов: контроль обязан проверить, что ответ приходит ИЗ двери, а
    не из копии правила, живущей здесь.
    """
    out = {"date": rec.get("cycle_date"), "schema": rec.get("schema")}
    gates, source = gate_state_fn(rec)
    out["gate_state_source"] = source
    if gates is None:
        out.update({"klass": CLASS_UNMEASURED,
                    "why": "состояние гейтов записи не измерено"})
        return out
    if not gates.get("has_legs", True):
        out.update({"klass": CLASS_NO_PROPOSAL, "why": "двигать нечего"})
        return out

    cut, why = cut_to_admissible(rec, params)
    if cut is None:
        out.update({"klass": CLASS_UNMEASURED, "why": why})
        return out
    out.update({k: cut[k] for k in ("k", "admissible_usd", "turnover_usd_cut",
                                    "gain_pp_cut", "payback_days_bound")})
    out["turnover_usd_full"] = rec.get("turnover_usd")
    out["gain_pp_full"] = rec.get("gain_pp")
    out["payback_days_full"] = rec.get("payback_days")

    if cut["already_admissible"]:
        # Урезать нечего — предложение и так в потолках, значит отказ дня лежит
        # НЕ в размере, и этот прибор о таком дне не говорит ничего.
        out.update({"klass": CLASS_ALREADY_ADMISSIBLE,
                    "why": "оборот предложения уже внутри потолков размера"})
        return out

    arm_verdict, arm_names = _arming_axis(gates, cut, params)
    out["arming_without_grant"] = arm_verdict
    if arm_names:
        out["arming_blocking_gates"] = arm_names

    # ── ось РАЗРЕШЕНИЯ: ограничители частоты поданы ОТКАЗАВШИМИ в худшую
    # сторону. Разрешение снимает ровно их, поэтому худший случай ответа не
    # меняет, а подстановка «прошли» была бы догадкой о входе, которого в
    # истории нет (инв. #17).
    failing = list(_BUDGET_GATES) + ["cooldown_ok", "min_hold_ok", "move_turnover_ok"]
    if not gates.get("target_fully_evidenced", True):
        failing.append("target_fully_evidenced")
    bound = cut.get("payback_days_bound")
    if bound is None or float(bound) > float(params.max_payback_days) + _EPS:
        failing.append("payback_within_horizon")
    blockers, unmeasured = grant_blockers_fn(
        failing, gain_pp=cut.get("gain_pp_cut"), min_gain_pp=min_gain_pp)
    if blockers is None:
        out.update({"klass": CLASS_UNMEASURED,
                    "why": f"препятствия разрешению не измерены: {unmeasured}"})
        return out
    out["grant_blockers"] = [{"class": kind, "gates": names} for kind, names in blockers]
    if not blockers:
        out.update({"klass": CLASS_FIRES,
                    "why": ("выигрыш {:.3f} пп ≥ {:.3f} пп и окупаемость ≤ {} дн. "
                            "при обороте ${:,.0f} вместо ${:,.0f}".format(
                                float(cut["gain_pp_cut"]), float(min_gain_pp),
                                cut.get("payback_days_bound"),
                                float(cut["turnover_usd_cut"]),
                                float(rec.get("turnover_usd") or 0.0)))})
        return out
    kinds = {kind for kind, _ in blockers}
    if kinds <= {"economics_failed", "below_base_gain"}:
        out.update({"klass": CLASS_ECON_FAILS,
                    "why": "урезание ломает экономику хода: " + ", ".join(sorted(kinds))})
    else:
        out.update({"klass": CLASS_NOT_SIZE_REFUSED,
                    "why": "отказал гейт, которого размер не лечит: "
                           + ", ".join(sorted(kinds))})
    return out


def admissible_size_reach(records: List[dict], *, params=None, acts: int = 0,
                          gate_state_fn=None, grant_blockers_fn=None) -> dict:
    """Перепись: сработал бы ход, УРЕЗАННЫЙ до допустимого размера, хоть на одной записи.

    Три исхода различимы (инв. #17):

    * ``GRANT_FIRES_AT_ADMISSIBLE_SIZE`` — есть запись, на которой урезанный ход
      прошёл бы ВСЕ гейты, которые разрешение владельца не снимает. Это
      ДОКАЗАТЕЛЬСТВО достижимости, а не оценка сверху (см. докстринг модуля);
    * ``NEVER_AT_ADMISSIBLE_SIZE`` — измеренные записи есть, и ни на одной
      урезанный ход не прошёл бы; препятствия НАЗВАНЫ переписью классов;
    * ``UNMEASURED`` — мерить было нечего;
    * ``NOT_BLOCKED`` — ``ACT`` уже случался, вопрос не стоит.

    **Единица счёта — ЗАПИСЬ вердикта, а не календарный день**, и это названо в
    отчёте: цикл в иной день прогоняется до пятнадцати раз, поэтому доли от
    записей взвешены частотой прогона. Обе величины печатаются рядом.
    """
    if params is None:
        from spa_core.allocator.rebalance_economics import TriggerParams
        params = TriggerParams.for_mode("paper")
    if gate_state_fn is None:
        from spa_core.paper_trading.shadow_trigger_eval import gate_state as gate_state_fn
    if grant_blockers_fn is None:
        from spa_core.paper_trading.cio_trial import grant_blockers as grant_blockers_fn
    from spa_core.paper_trading.cio_trial import TRIAL_GRANT

    rows = [judge_record(rec, params=params, min_gain_pp=float(params.min_gain_pp),
                         gate_state_fn=gate_state_fn,
                         grant_blockers_fn=grant_blockers_fn)
            for rec in (records or []) if isinstance(rec, dict)]

    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["klass"]] = counts.get(row["klass"], 0) + 1
    fires = [r for r in rows if r["klass"] == CLASS_FIRES]
    judged = [r for r in rows if r["klass"] != CLASS_UNMEASURED]
    granted_at = str(TRIAL_GRANT.get("granted_at") or "")
    fires_after_grant = [r for r in fires
                         if str(r.get("date") or "") >= granted_at[:10]]

    arming: Dict[str, int] = {}
    for row in rows:
        verdict = row.get("arming_without_grant")
        if verdict:
            arming[verdict] = arming.get(verdict, 0) + 1

    if acts:
        verdict = ADM_MOOT
        reason = (f"вердикт ACT уже случался ({acts}) — вопрос «а если урезать ход» "
                  "не стоит")
    elif not judged:
        verdict = ADM_UNMEASURED
        reason = "ни одной измеренной записи — урезать было нечего"
    elif fires:
        verdict = ADM_FIRES
        # Допустимый размер — величина ДНЯ (он зависит от капитала дня), поэтому
        # печатается ПЕРЕЧЕНЬ встреченных значений, а не значение первой записи:
        # одно число на разнокапитальной истории было бы выдумкой про остальные.
        adm_seen = sorted({float(r.get("admissible_usd") or 0.0) for r in fires})
        reason = (
            "на {} записях ({} дат) ход, УРЕЗАННЫЙ до допустимого размера "
            "({}), прошёл бы все гейты, которых разрешение владельца не снимает; "
            "из них после выдачи разрешения — {}. Предложение не урезается НИКЕМ: "
            "потолок размера читается как фильтр предложений, а не как размер "
            "хода".format(
                len(fires), len({r.get("date") for r in fires}),
                " · ".join(f"${v:,.0f}" for v in adm_seen), len(fires_after_grant)))
    else:
        verdict = ADM_NEVER
        reason = ("из {} измеренных записей ни на одной урезанный ход не прошёл бы: "
                  "{}".format(len(judged), ", ".join(
                      f"{k} {v}" for k, v in sorted(counts.items()))))

    return {
        "verdict": verdict,
        "reason": reason,
        "records": len(rows),
        "dates": len({r.get("date") for r in rows if r.get("date")}),
        "measured_records": len(judged),
        "unmeasured_records": counts.get(CLASS_UNMEASURED, 0),
        "class_census": dict(sorted(counts.items())),
        "arming_without_grant_census": dict(sorted(arming.items())),
        "fires": fires,
        "fires_after_grant_records": len(fires_after_grant),
        "grant": {"adr": TRIAL_GRANT.get("adr"), "granted_at": granted_at,
                  "moves": TRIAL_GRANT.get("moves")},
        "params": {
            "max_turnover_per_move": float(params.max_turnover_per_move),
            "max_trade_usd": float(params.max_trade_usd),
            "min_gain_pp": float(params.min_gain_pp),
            "max_payback_days": float(params.max_payback_days),
            "min_leg_frac": float(params.min_leg_frac),
            "policy_version": getattr(params, "version", None),
            "mode": getattr(params, "mode", None),
        },
        "unmeasured_sample": [{"date": r.get("date"), "why": r.get("why")}
                              for r in rows if r["klass"] == CLASS_UNMEASURED][:5],
        "assumptions": [
            "урезание пропорционально (target_k = current + k·(target − current)) — "
            "это ДОПУСТИМЫЙ ход, а не оптимальный; оптимизатор под ограничением "
            "оборота выбрал бы цель заново и, вероятно, лучшую ⇒ замер есть НИЖНЯЯ "
            "граница достижимости",
            "стоимость урезанного хода взята ПОЛНОЙ (газ за ногу тот же, "
            "проскальзывание и мост МЕНЬШЕ) ⇒ окупаемость ЗАВЫШЕНА, ошибка идёт "
            "против находки",
            "ограничители частоты поданы разрешению ОТКАЗАВШИМИ: разрешение "
            "снимает ровно их, поэтому худший случай ответа не меняет",
            "ось «взвод без разрешения» бюджеты дня и недели НЕ угадывает — "
            "отказавший бюджет при меньшем обороте становится НЕ РЕШЁННЫМ",
        ],
    }


def format_admissible_reach(reach: Optional[dict]) -> List[str]:
    """Строки про урезание хода — общие для CLI и шага 0-офис.

    Отсутствие блока — ТРЕТИЙ исход, а не «урезание не помогает»: отчёт старого
    образца молчит ровно так же, как отчёт, в котором ход недостижим, и молчание
    читалось бы согласием.
    """
    if not isinstance(reach, dict):
        return ["Ход, урезанный до допустимого: ⚠️ НЕ ИЗМЕРЕН — в отчёте нет блока "
                "`admissible_size_reach` (отчёт старого образца)"]
    mark = "🔴" if reach.get("verdict") == ADM_FIRES else "•"
    params = reach.get("params") or {}
    out = [f"Ход, урезанный до допустимого ({reach.get('grant', {}).get('adr')}): "
           f"{mark} {reach.get('verdict')} — {reach.get('reason')}",
           "  записей {} ({} дат) · измерено {} · не измерено {} · допустимый ход "
           "min({:.0%} капитала, ${:,.0f})".format(
               reach.get("records"), reach.get("dates"),
               reach.get("measured_records"), reach.get("unmeasured_records"),
               float(params.get("max_turnover_per_move") or 0.0),
               float(params.get("max_trade_usd") or 0.0))]
    for klass, n in (reach.get("class_census") or {}).items():
        out.append(f"  класс {klass}: {n} зап.")
    arming = reach.get("arming_without_grant_census") or {}
    if arming:
        out.append("  то же БЕЗ разрешения владельца: "
                   + " · ".join(f"{k} {v}" for k, v in arming.items())
                   + " — «не решено бюджетом» это третий исход, а не «открыто»")
    for row in (reach.get("fires") or [])[:3]:
        out.append("  ⚠️ {}: ${:,.0f} вместо ${:,.0f} (k={}) ⇒ выигрыш {} пп, "
                   "окупаемость ≤ {} дн. — {}".format(
                       row.get("date"), float(row.get("turnover_usd_cut") or 0.0),
                       float(row.get("turnover_usd_full") or 0.0), row.get("k"),
                       row.get("gain_pp_cut"), row.get("payback_days_bound"),
                       row.get("why")))
    for row in (reach.get("unmeasured_sample") or [])[:2]:
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО {row.get('date')}: {row.get('why')}")
    out.append("  ADVISORY: перепись только ЧИТАЕТ — ни порога, ни разрешения, ни "
               "вердикта она не меняет; урезание хода НЕ ВКЛЮЧЕНО нигде")
    return out
