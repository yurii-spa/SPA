"""Урезать ПРЕДЛОЖЕНИЕ до допустимого РАЗМЕРА хода — перед вердиктом (ADR-850).

Предмет. Потолок размера хода владельца ($15 000, ADR-357; 15 % капитала за ход,
ADR-060 §3) до этого шага читался как **ФИЛЬТР предложений, а не как РАЗМЕР хода**:
аллокатор предлагал перекладку целиком, потолок отказывал ей ЦЕЛИКОМ, и урезать
предложение до разрешённого размера не умел НИКТО. Замер цикла #968 (ADR-848, живая
история книги `conservative`, 163 записи / 84 даты): на **7 записях (6 дат)** ход,
урезанный до допустимых $15 000, прошёл бы ВСЕ гейты, которых разовое разрешение
владельца (ADR-334) не снимает; **3 из них — после выдачи разрешения**. Острая запись
`2026-10-02`: предложение $40 000 (выигрыш 3.236 пп, окупаемость 9.94 дн.) отказано
ТОЛЬКО потолками размера, а урезанное до $15 000 даёт выигрыш 1.214 пп при пороге 0.50
и окупаемость ≤ 26.5 дн. при потолке 30.

Что этот шаг делает и чем он НЕ является
----------------------------------------
Шаг стои́т РЯДОМ с двумя соседями того же рода (`apply_rtmr_posture_gate`,
`apply_pool_alias_gate`) и ДО Step 2f, чтобы вердикт CIO судил уже итоговую цель —
то есть ровно тот ход, который цикл и сделает. Одна цель, один вердикт, один ход.

* **НИ ОДИН порог не ослабляется.** Потолки размера, полоса выигрыша, окупаемость,
  кулдаун, срок удержания, бюджеты дня и недели остаются как есть. Ход становится
  МЕНЬШЕ — это строго консервативнее, чем предложение, которое его породило.
* **RiskPolicy v1.0 не тронута ни строкой.** Урезанная цель ПЕРЕСПРАШИВАЕТСЯ у той
  же двери, которой цикл судил полную (`risk_gate._apply_risk_policy_gate`), и не
  прошла ⇒ урезание ОТМЕНЯЕТСЯ, цель остаётся прежней (fail-CLOSED, поведение дня
  не меняется вовсе).
* **Урезается только ПЕРЕТАСОВКА.** Де-риск, первичное размещение пустой книги и
  вложение простаивающего кэша — не перекладка (`churn_damper`, ADR-168;
  `cio_arming.NOT_A_RESHUFFLE`), и урезать их значило бы ЗАДЕРЖАТЬ де-риск или
  оставить капитал простаивать, что прямо запрещено (ADR-055 и правило «де-риск не
  ждёт никогда»).
* **Это НЕ новая цель.** Урезанная книга лежит НА ОТРЕЗКЕ между стоящей книгой и
  целью аллокатора: ни одного протокола, которого цель не финансирует, в ней не
  появляется, и ни одна позиция не выходит за пределы пары (стоящая, цель).

Почему отрезок, а не «оптимальная урезка»
-----------------------------------------
Карточка просила пересчитать цель под ограничением оборота, потому что оптимизатор
выбрал бы лучшую цель, чем пропорциональное урезание. Верно про ВЫИГРЫШ и неверно
про ДОПУСТИМОСТЬ: все потолки этого слоя (концентрация на протокол, сумма тира,
буфер кэша) — ЛИНЕЙНЫЕ, поэтому точка отрезка между двумя допустимыми книгами
допустима ПО ПОСТРОЕНИЮ, а «жадная» перестановка ног — нет. Контрпример на двух
ключах T2 при потолке тира 50 %: стоящая (30, 10), цель (10, 30) — обе 40 %;
жадная пара «купить B раньше, чем продан A» даёт (30, 30) = 60 % и выходит за
потолок тира. Лучшее число ВНЕ допустимого множества — ровно тот класс дефекта,
против которого написан весь этот слой, поэтому шаг берёт отрезок и говорит об
этом вслух. Отрезок даёт НИЖНЮЮ границу достижимости (ADR-848 §«почему замер —
нижняя граница»); верхняя остаётся предметом отдельного решения с пересчётом цели
под ограничением, и для него потребуется переспросить RiskPolicy так же.

Три исхода различимы (инв. #17)
-------------------------------
``TRIMMED`` (урезано, названы k и обе суммы) · ``NOT_NEEDED`` (оборот уже внутри
потолков — k = 1, цель возвращается той же) · ``NOT_A_RESHUFFLE`` / ``NOTHING_TO_MOVE``
(предмета нет) · ``REFUSED_BY_POLICY`` (урезанную цель не одобрила та же RiskPolicy ⇒
прежнее поведение) · ``UNMEASURED`` (входа нет; причина НАЗВАНА, догадки нет).

LLM запрещён. Только stdlib. Детерминированно: одни входы — один ответ.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.admissible_trim")

_EPS = 1e-9

#: Вердикты шага. Имена — часть контракта: по ним читает шаг 0-офис и перепись,
#: переименование = смена вопроса.
TRIM_APPLIED = "TRIMMED_TO_ADMISSIBLE"
TRIM_NOT_NEEDED = "ALREADY_WITHIN_SIZE_CAPS"
TRIM_NOT_A_RESHUFFLE = "NOT_A_RESHUFFLE"
TRIM_NOTHING_TO_MOVE = "NOTHING_MATERIAL_TO_MOVE"
TRIM_REFUSED_BY_POLICY = "REFUSED_BY_RISK_POLICY"
TRIM_UNMEASURED = "UNMEASURED"


def _interpolate(current: Dict[str, float], target: Dict[str, float],
                 k: float) -> Dict[str, float]:
    """Точка отрезка «стоящая книга → цель» на доле ``k`` пути.

    Ключи — объединение обеих книг: позиция, которую цель обнуляет, обязана
    сокращаться ЧАСТИЧНО, иначе урезание продавало бы её целиком, то есть
    делало бы ход БОЛЬШЕ допустимого.
    """
    out: Dict[str, float] = {}
    for proto in sorted(set(current or {}) | set(target or {})):
        cur = float((current or {}).get(proto, 0.0) or 0.0)
        tgt = float((target or {}).get(proto, 0.0) or 0.0)
        val = round(cur + k * (tgt - cur), 2)
        if val > 0.0:
            out[proto] = val
    return out


def _turnover(current: Dict[str, float], target: Dict[str, float],
              capital_usd: float, min_leg_frac: float) -> float:
    """Оборот хода — ТОЙ ЖЕ дверью, которой его считает отказавший гейт.

    Своя копия определения оборота спорила бы с `move_amount_ok` молча: у двери
    (`rebalance_economics._legs`) из оборота выпадает пыль, и «урезал до
    потолка» по другому определению означало бы «не урезал».
    """
    from spa_core.allocator.rebalance_economics import _legs

    _, turnover = _legs(dict(current or {}), dict(target or {}),
                        float(capital_usd), float(min_leg_frac))
    return float(turnover)


def apply_admissible_trim(
    target_usd: Dict[str, float],
    *,
    current_positions: Dict[str, float],
    capital_usd: float,
    notes: List[str],
    adapters=None,
    ddir=None,
    params=None,
    trades=None,
    now=None,
    policy_gate: Optional[Callable[..., dict]] = None,
    damper_decide: Optional[Callable[..., object]] = None,
) -> Tuple[Dict[str, float], dict]:
    """Урезать цель до допустимого РАЗМЕРА хода. Возврат ``(цель, запись)``.

    Цель заменяется ТОЛЬКО когда урезание и состоялось, и переспрошенная
    RiskPolicy одобрила урезанную книгу. В любом другом исходе возвращается
    цель, пришедшая на вход, а запись НАЗЫВАЕТ причину.

    ``policy_gate`` и ``damper_decide`` — двери, а не копии правил: первая судит
    допустимость книги (та же, что у Step 2b), вторая классифицирует ход
    (та же, что у демпфера ADR-168 и у разрешения ADR-336). Инъекция есть
    затем, чтобы контроль мог доказать, что ответ приходит ИЗ двери: подменённая
    дверь обязана менять ответ.
    """
    record: dict = {"verdict": TRIM_UNMEASURED, "adr": "ADR-850"}
    target_in = dict(target_usd or {})

    if policy_gate is None:
        from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate as policy_gate
    if damper_decide is None:
        from spa_core.governance.churn_damper import decide as damper_decide

    try:
        capital = float(capital_usd or 0.0)
    except (TypeError, ValueError):
        capital = 0.0
    if capital <= 0:
        record["why"] = "капитал дня не измерен — урезать нечего и не от чего"
        return target_in, record

    if params is None:
        from spa_core.allocator.rebalance_economics import TriggerParams
        params = TriggerParams.for_mode()

    # ── предмет: урезается только ПЕРЕТАСОВКА ────────────────────────────────
    # Классификация берётся у демпфера — той же двери, которой её берёт
    # разрешение владельца (ADR-336). Не классифицировано ⇒ НЕ ИЗМЕРЕНО, и
    # урезание не делается: держать прежнее поведение безопасно, угадывать нет.
    try:
        from spa_core.paper_trading.cio_arming import NOT_A_RESHUFFLE
        damper_reason = getattr(
            damper_decide(dict(current_positions or {}), target_in,
                          list(trades or []), capital, now=now),
            "reason", None)
    except Exception as exc:  # noqa: BLE001 — не классифицировано ⇒ третий исход
        record["why"] = f"род хода не классифицирован ({type(exc).__name__}) ⇒ цель не тронута"
        return target_in, record
    record["damper_reason"] = damper_reason
    if damper_reason in NOT_A_RESHUFFLE:
        record.update({
            "verdict": TRIM_NOT_A_RESHUFFLE,
            "why": (f"ход не перетасовка ({damper_reason}) — де-риск не ждёт никогда, "
                    "а размещение кэша и первичное размещение урезать значило бы "
                    "оставить капитал простаивать (ADR-055)"),
        })
        return target_in, record

    # ── сколько РАЗРЕШЕНО двинуть одним ходом — одна дверь (ADR-848) ─────────
    from spa_core.paper_trading.admissible_size import admissible_turnover_usd

    admissible = float(admissible_turnover_usd(capital, params))
    turnover_full = _turnover(current_positions or {}, target_in, capital,
                              float(params.min_leg_frac))
    record.update({
        "admissible_usd": round(admissible, 2),
        "turnover_full_usd": round(turnover_full, 2),
        "caps": {"max_trade_usd": float(params.max_trade_usd),
                 "max_turnover_per_move": float(params.max_turnover_per_move)},
    })

    if turnover_full <= _EPS:
        record.update({"verdict": TRIM_NOTHING_TO_MOVE,
                       "why": "материального хода нет — урезать нечего"})
        return target_in, record
    if admissible <= _EPS:
        record.update({"why": "допустимый размер хода не положителен — потолок не прочитан"})
        return target_in, record
    if turnover_full <= admissible + 0.01:
        record.update({"verdict": TRIM_NOT_NEEDED, "k": 1.0,
                       "why": "оборот предложения уже внутри потолков размера"})
        return target_in, record

    k = admissible / turnover_full
    trimmed = _interpolate(current_positions or {}, target_in, k)
    turnover_cut = _turnover(current_positions or {}, trimmed, capital,
                             float(params.min_leg_frac))
    record.update({"k": round(k, 6), "turnover_cut_usd": round(turnover_cut, 2)})

    # Округление до цента может оставить оборот на копейки выше потолка — это
    # НЕ повод отменить урезание, но и не повод объявить потолок соблюдённым:
    # допуск назван явно и равен цене округления одной ноги.
    if turnover_cut > admissible + 0.01:
        record.update({
            "why": (f"урезанный оборот ${turnover_cut:,.2f} выше допустимого "
                    f"${admissible:,.2f} — цель не тронута"),
        })
        return target_in, record

    # ── урезанную книгу судит ТА ЖЕ RiskPolicy, что судила полную ────────────
    # Отрезок между двумя допустимыми книгами допустим по построению (все
    # потолки слоя линейны), но «по построению» не есть «спрошено»: стоящая
    # книга могла уйти за потолок дрейфом, и тогда точка отрезка унаследовала
    # бы нарушение. Поэтому вопрос задаётся, и отказ означает прежнее поведение.
    try:
        verdict = policy_gate(dict(trimmed), capital, list(adapters or []), ddir=ddir,
                              current_positions=dict(current_positions or {}))
    except Exception as exc:  # noqa: BLE001 — гейт не ответил ⇒ не измерено
        record["why"] = (f"RiskPolicy не переспрошена ({type(exc).__name__}) ⇒ "
                         "урезание отменено, цель прежняя")
        return target_in, record
    if not isinstance(verdict, dict):
        record["why"] = "ответ RiskPolicy не разобран ⇒ урезание отменено"
        return target_in, record
    record["policy"] = {
        "approved": bool(verdict.get("approved")),
        "error": verdict.get("error"),
        "violations": list(verdict.get("violations") or [])[:5],
        "trimmed_by_gate": bool(verdict.get("trimmed")),
    }
    if verdict.get("error") is not None or not verdict.get("approved"):
        record.update({
            "verdict": TRIM_REFUSED_BY_POLICY,
            "why": ("урезанную книгу не одобрила та же RiskPolicy "
                    f"({record['policy']['violations'] or record['policy']['error']}) "
                    "⇒ цель прежняя, поведение дня не изменено"),
        })
        notes.append(f"admissible_trim: урезание отменено RiskPolicy — {record['why']} (ADR-850)")
        return target_in, record

    # Гейт вправе сам подрезать книгу под буфер кэша / пол TVL. Берём ЕГО вывод
    # (он и есть допустимая книга), но тогда обязаны перемерить оборот: подрезка
    # гейта могла увести его выше потолка размера, и молча принять такую книгу
    # значило бы вернуть ровно тот дефект, против которого шаг написан.
    final = {str(p): round(float(v), 2)
             for p, v in (verdict.get("target_usd") or trimmed).items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    turnover_final = _turnover(current_positions or {}, final, capital,
                               float(params.min_leg_frac))
    record["turnover_final_usd"] = round(turnover_final, 2)
    if turnover_final > admissible + 0.01:
        record.update({
            "verdict": TRIM_REFUSED_BY_POLICY,
            "why": (f"книга после подрезки гейтом даёт оборот ${turnover_final:,.2f} "
                    f"выше допустимого ${admissible:,.2f} ⇒ цель прежняя"),
        })
        notes.append(f"admissible_trim: урезание отменено — {record['why']} (ADR-850)")
        return target_in, record

    record.update({
        "verdict": TRIM_APPLIED,
        "target_before": {p: round(float(v), 2) for p, v in target_in.items()},
        "target_after": dict(final),
        "why": (f"предложение ${turnover_full:,.0f} урезано до допустимого "
                f"${turnover_final:,.0f} (k={k:.4f}); ни один порог не ослаблен, "
                "RiskPolicy переспрошена и одобрила"),
    })
    notes.append(
        f"admissible_trim: ход ${turnover_full:,.0f} → ${turnover_final:,.0f} "
        f"(потолок ${admissible:,.0f}, k={k:.4f}) — предложение урезано до "
        f"допустимого РАЗМЕРА, пороги не тронуты (ADR-850)")
    log.info("ADR-850 admissible trim: $%.2f → $%.2f (cap $%.2f, k=%.4f)",
             turnover_full, turnover_final, admissible, k)
    return final, record


def format_live_trim(census: Optional[dict]) -> List[str]:
    """Строки шага 0-офис про ЖИВОЙ трим — что он сделал на записанных днях.

    Прибор без читателя — сирота (урок ADR-843), поэтому у записи трима есть
    перепись (`shadow_trigger_eval.live_trim_census`) и эта печать, которую
    зовут оба читателя артефакта: его собственная сводка и шаг 0-офис.
    """
    if not isinstance(census, dict) or not census:
        return ["Живое урезание хода (ADR-850): ⚠️ НЕ ИЗМЕРЕНО — переписи в артефакте нет"]
    if census.get("unmeasured_reason"):
        return [f"Живое урезание хода (ADR-850): ⚠️ НЕ ИЗМЕРЕНО — {census['unmeasured_reason']}"]
    counts = census.get("counts") or {}
    out = [
        "Живое урезание хода (ADR-850): записей {} · урезано {} · уже внутри потолков {} · "
        "не перетасовка {} · отказано RiskPolicy {} · не измерено {} · записей БЕЗ поля {}".format(
            census.get("records"), counts.get(TRIM_APPLIED, 0),
            counts.get(TRIM_NOT_NEEDED, 0), counts.get(TRIM_NOT_A_RESHUFFLE, 0),
            counts.get(TRIM_REFUSED_BY_POLICY, 0), counts.get(TRIM_UNMEASURED, 0),
            census.get("records_without_field")),
    ]
    last = census.get("last_applied")
    if isinstance(last, dict) and last:
        out.append("  последнее урезание: {} — ${:,.0f} → ${:,.0f} (k={})".format(
            last.get("date"), float(last.get("turnover_full_usd") or 0.0),
            float(last.get("turnover_final_usd") or 0.0), last.get("k")))
    elif census.get("records"):
        out.append("  урезаний не было ни на одной записи — это ЗАМЕР, а не отсутствие "
                   "проводки: проводку меряет контроль в обе стороны")
    return out
