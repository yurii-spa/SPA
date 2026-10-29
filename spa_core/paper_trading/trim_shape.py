"""ФОРМА урезания имеет свою цену, и она измеряется, а не выводится (ADR-854).

Что здесь нового по сравнению с соседями
----------------------------------------
Четыре блока уже спрашивают про урезанный ход, и ни один не спрашивает про его
ФОРМУ:

====================================  ======================================
``admissible_size_reach`` (ADR-848)   прошёл бы ход, УРЕЗАННЫЙ до потолка
``admissible_trim`` (ADR-850)         живая проводка: цель урезается до потолка
``…_trim.cost_of_the_trim`` (ADR-853) сколько стоит ОДНО предложение до/после
**этот модуль**                       **дешевле ли урезание ДРУГОЙ формы**
====================================  ======================================

ADR-853 измерил цену трима на живой записи (+17.53 бп за доллар хода) и назвал
механизм: ``cur + k·(tgt − cur)`` трогает ВСЕ ноги частично, поэтому ЧИСЛО ног
с ``k`` не падает, а газ платится ЗА НОГУ. Из механизма он вывел утверждение —
«урезание, выбирающее МЕНЬШЕ ног, дешевле при том же размере хода» — и честно
оставил его РАССУЖДЕНИЕМ: прибора, который сравнил бы две формы, не было, а
население живых урезаний равнялось ОДНОЙ записи.

Этот модуль и есть такой прибор. Он сравнивает две формы одного и того же
урезания:

* **пропорциональная интерполяция** — ровно то, что делает живой шаг 2e''
  (дверь ``admissible_trim._interpolate``, не копия);
* **подмножество, упорядоченное по спреду** — продавать с худшей наблюдённой
  ставки, покупать в лучшую, пока не выбран допустимый размер хода.

Почему сравнение честное, а не подыгрывает второй форме
-------------------------------------------------------
Три величины у обеих форм ОДНИ И ТЕ ЖЕ, и это условие сравнения, а не деталь:

1. **потолок размера** — ``admissible_turnover_usd`` (одна дверь, ADR-848);
2. **чистое движение кэша** — у подмножества оно РАВНО движению кэша
   интерполяции (``net_k = k·(Σtgt − Σcur)``). Без этого условия подмножество
   могло бы «выиграть», просто развернув кэш, которого интерполяция не
   разворачивала, — то есть ответить на другой вопрос;
3. **модель издержек и карта сетей** — ``rebalance_economics._legs`` /
   ``_move_cost_usd`` (те же двери, которыми цену считает цикл).

Меняется РОВНО форма. Поэтому дельта отвечает на вопрос «стоит ли формы
различать», а не «чем отличались два дня».

Что прибор НЕ утверждает — граница названа вслух
------------------------------------------------
**Книга подмножества НЕ объявляется допустимой.** RiskPolicy её не спрашивали:
на исторических днях у неё нет ни живого TVL того дня, ни тиров. Что про
допустимость известно ТОЧНО, и что — нет:

======================================  =========================================
потолок на ПРОТОКОЛ (40 % T1 / 20 % T2) та же позиция, что у интерполяции: каждая
                                        координата лежит МЕЖДУ ``cur`` и ``tgt``,
                                        а потолок — верхняя граница, то есть
                                        отрезок по координате его сохраняет
буфер кэша ≥ 5 %                        РАВЕН интерполяции по построению (п. 2)
пол TVL и эвиденс                       не хуже: множество финансируемых
                                        протоколов у подмножества ⊆ множества
                                        интерполяции
потолок на ГРУППУ (T2 всего ≤ 50 %)     **НЕ ИЗВЕСТНО.** Сумма по группе у угла
                                        бокса может превышать обе границы ⇒
                                        спрашивать обязана RiskPolicy
======================================  =========================================

Поэтому измеренное — РАЗМЕР ПРИЗА формы, а не разрешение его взять. Проводка
оптимума под ограничением есть money-path и отдельное решение владельца.

ADVISORY. Ни одного порога не меняет, цель дня не трогает, капитал не двигает,
RiskPolicy не касается, живой трек не пишет. Только ЧИТАЕТ записанную историю
предложений.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.trim_shape")

_EPS = 1e-9
_DAYS_YEAR = 365.0

#: Исходы вопроса «дешевле ли урезание другой формы» на ОДНОЙ записи. Четыре, и
#: каждый — ЗНАЧЕНИЕ (инв. #17 CLAUDE.md), а не пустое поле.
SHAPE_MEASURED = "measured"
SHAPE_UNMEASURED = "unmeasured"
SHAPE_NO_SUBJECT = "no_subject"          # оборот уже внутри потолка ⇒ урезать нечего
SHAPE_NO_ALTERNATIVE = "no_alternative"  # форма-соседка пуста (одна сторона хода пуста)


def _sides(current: Dict[str, float],
           target: Dict[str, float]) -> Tuple[List[List], List[List]]:
    """Две стороны предложения: куда ДОКЛАДЫВАЕМ и откуда ЗАБИРАЕМ.

    Пыль здесь НЕ отсекается намеренно: отсев — предмет двери ``_legs``, и своя
    копия порога спорила бы с ней молча (тот же класс, из-за которого оборот
    считается дверью, а не формулой).
    """
    inc: List[List] = []
    dec: List[List] = []
    for proto in sorted(set(current or {}) | set(target or {})):
        delta = (float((target or {}).get(proto, 0.0) or 0.0)
                 - float((current or {}).get(proto, 0.0) or 0.0))
        if delta > 0:
            inc.append([proto, delta])
        elif delta < 0:
            dec.append([proto, -delta])
    return inc, dec


def subset_trim(current: Dict[str, float],
                target: Dict[str, float],
                apy_pct: Dict[str, float],
                *,
                admissible_usd: float,
                net_cash_usd: float) -> Tuple[Optional[Dict[str, float]], str]:
    """Урезание ФОРМОЙ ПОДМНОЖЕСТВА. Возврат ``(книга, "")`` либо ``(None, причина)``.

    Правило выбора: **забирать с худшей наблюдённой ставки, докладывать в
    лучшую**, пока не выбран допустимый размер хода. Это и есть «считать ноги»:
    доллар хода идёт в ногу с максимальным спредом, а нога, до которой денег не
    хватило, не трогается ВОВСЕ — газ за неё не платится.

    ``net_cash_usd`` — чистое движение кэша, которое обязано совпасть с чистым
    движением кэша формы-соседки. Это условие СРАВНЕНИЯ: без него подмножество
    могло бы развернуть кэш, которого соседка не разворачивала.

    Каждая координата возвращённой книги лежит между ``current`` и ``target``:
    ни одна позиция не уходит дальше предложения и ни одна не идёт против него.
    Допустимость книги здесь НЕ утверждается (см. докстринг модуля).
    """
    try:
        cap = float(admissible_usd)
        net = float(net_cash_usd)
    except (TypeError, ValueError):
        return None, "допустимый размер хода или движение кэша не число"
    if cap <= _EPS:
        return None, "допустимый размер хода не положителен — выбирать нечего"
    inc, dec = _sides(current or {}, target or {})
    cap_inc = sum(a for _, a in inc)
    cap_dec = sum(a for _, a in dec)
    # Сколько ВСЕГО можно купить (b) и продать (s) при b − s = net и
    # max(b, s) ≤ cap. Решается в одну строку на каждую сторону, потому что
    # максимум ровно один из двух.
    if net >= 0:
        moved = min(cap, cap_inc, cap_dec + net)
        buy, sell = moved, moved - net
    else:
        moved = min(cap, cap_dec, cap_inc - net)
        buy, sell = moved + net, moved
    if buy < -_EPS or sell < -_EPS:
        return None, (f"сторон хода не хватает на чистое движение кэша "
                      f"${net:,.2f} при потолке ${cap:,.2f}")
    if buy <= _EPS and sell <= _EPS:
        return None, ("одна из сторон хода пуста — подмножества, сохраняющего "
                      "движение кэша соседки, не существует")
    inc.sort(key=lambda row: -float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    dec.sort(key=lambda row: float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    book: Dict[str, float] = {str(p): float(v or 0.0)
                              for p, v in (current or {}).items()}
    for side, budget, sign in ((inc, buy, 1.0), (dec, sell, -1.0)):
        left = budget
        for proto, room in side:
            if left <= _EPS:
                break
            take = min(room, left)
            left -= take
            book[proto] = round(float(book.get(proto, 0.0) or 0.0) + sign * take, 2)
    return {p: v for p, v in book.items() if v > 0.0}, ""


#: Откуда взято ПРЕДЛОЖЕНИЕ записи. Ось нужна потому, что у записи, которую
#: живой шаг УЖЕ урезал (ADR-850), поле ``target_positions`` несёт книгу ПОСЛЕ
#: урезания: читать её как предложение значило бы объявить «урезать нечего»
#: ровно на той единственной записи, где урезание и состоялось.
PROPOSAL_FROM_TRIM_BEFORE = "trim.target_before"
PROPOSAL_FROM_TARGET = "target_positions"
PROPOSAL_ABSENT = "absent"


def _proposal_of(rec: dict) -> Tuple[Dict[str, float], str]:
    """Предложение записи ДО урезания и откуда оно взято.

    Возврат ``(книга, источник)``. ``PROPOSAL_ABSENT`` — самостоятельное
    значение: запись без цели это НЕ пустая цель (инв. #17), и перепись обязана
    различать «предложения не записано» от «предложение пусто».
    """
    trim = rec.get("admissible_trim")
    if isinstance(trim, dict):
        before = trim.get("target_before")
        if isinstance(before, dict) and before:
            return ({str(p): float(v or 0.0) for p, v in before.items()},
                    PROPOSAL_FROM_TRIM_BEFORE)
    target = rec.get("target_positions")
    if isinstance(target, dict) and target:
        return ({str(p): float(v or 0.0) for p, v in target.items()},
                PROPOSAL_FROM_TARGET)
    return {}, PROPOSAL_ABSENT


def _payback_days(cost_usd: float, gain_pp: float, capital_usd: float) -> Optional[float]:
    """Окупаемость ТОЙ ЖЕ формулой, что у гейта (``rebalance_economics.evaluate``).

    ``None`` — «не определена» (выигрыша нет), и это ЗНАЧЕНИЕ, а не ноль:
    ноль прочитался бы как «окупается мгновенно».
    """
    if gain_pp is None or gain_pp <= _EPS or capital_usd <= _EPS:
        return None
    cost_pp = 100.0 * float(cost_usd) / float(capital_usd)
    return round(_DAYS_YEAR * cost_pp / float(gain_pp), 2)


def _book_apy_pp(book: Dict[str, float], apy_pct: Dict[str, float],
                 capital_usd: float) -> float:
    """Смешанная ставка книги — линейна по позициям, поэтому считается точно."""
    return sum((float(v or 0.0) / capital_usd)
               * float((apy_pct or {}).get(p, 0.0) or 0.0)
               for p, v in (book or {}).items())


def compare_trim_shapes(current: Dict[str, float],
                        target: Dict[str, float],
                        apy_pct: Dict[str, float],
                        *,
                        capital_usd: float,
                        params,
                        chains: Dict[str, str],
                        chains_measured: bool) -> dict:
    """Две формы ОДНОГО урезания, одной моделью и одним потолком.

    Возврат — запись с полем ``kind`` из четырёх значений выше. Прибор ничего
    не судит и ни одного порога не применяет: он называет цену, выигрыш, число
    ног и окупаемость у каждой формы.
    """
    from spa_core.allocator.rebalance_economics import _legs, _move_cost_usd
    from spa_core.paper_trading.admissible_size import admissible_turnover_usd
    from spa_core.paper_trading.admissible_trim import _interpolate

    out: dict = {"chains_measured": bool(chains_measured)}
    try:
        capital = float(capital_usd or 0.0)
    except (TypeError, ValueError):
        capital = 0.0
    if capital <= _EPS:
        out.update({"kind": SHAPE_UNMEASURED,
                    "why": "капитал дня не записан — ни цену, ни выигрыш считать не от чего"})
        return out
    cur = {str(p): float(v or 0.0) for p, v in (current or {}).items()}
    tgt = {str(p): float(v or 0.0) for p, v in (target or {}).items()}
    mlf = float(params.min_leg_frac)
    try:
        admissible = float(admissible_turnover_usd(capital, params))
        legs_full, turnover_full = _legs(cur, tgt, capital, mlf)
    except Exception as exc:  # noqa: BLE001 — дверь не ответила ⇒ третий исход
        out.update({"kind": SHAPE_UNMEASURED,
                    "why": f"дверь оборота не ответила ({type(exc).__name__})"})
        return out
    out["admissible_usd"] = round(admissible, 2)
    out["turnover_full_usd"] = round(turnover_full, 2)
    if turnover_full <= _EPS:
        out.update({"kind": SHAPE_NO_SUBJECT,
                    "why": "материального хода нет — формы сравнивать не на чем"})
        return out
    if turnover_full <= admissible + 0.01:
        out.update({"kind": SHAPE_NO_SUBJECT,
                    "why": ("предложение уже внутри потолка размера — урезания нет, "
                            "и формы у него нет тоже")})
        return out

    k = admissible / turnover_full
    net_k = k * (sum(tgt.values()) - sum(cur.values()))
    out["k"] = round(k, 6)
    try:
        book_interp = _interpolate(cur, tgt, k)
        legs_i, turnover_i = _legs(cur, book_interp, capital, mlf)
        cost_i = _move_cost_usd(legs_i, turnover_i, chains) if legs_i else 0.0
    except Exception as exc:  # noqa: BLE001
        out.update({"kind": SHAPE_UNMEASURED,
                    "why": f"форма интерполяции не посчитана ({type(exc).__name__})"})
        return out

    book_subset, why = subset_trim(cur, tgt, apy_pct or {},
                                   admissible_usd=admissible, net_cash_usd=net_k)
    if book_subset is None:
        out.update({"kind": SHAPE_NO_ALTERNATIVE, "why": why,
                    "interpolated": {"legs": len(legs_i),
                                     "turnover_usd": round(turnover_i, 2),
                                     "cost_usd": round(cost_i, 2)}})
        return out
    try:
        legs_s, turnover_s = _legs(cur, book_subset, capital, mlf)
        cost_s = _move_cost_usd(legs_s, turnover_s, chains) if legs_s else 0.0
    except Exception as exc:  # noqa: BLE001
        out.update({"kind": SHAPE_UNMEASURED,
                    "why": f"форма подмножества не посчитана ({type(exc).__name__})"})
        return out

    base_pp = _book_apy_pp(cur, apy_pct or {}, capital)
    gain_i = round(_book_apy_pp(book_interp, apy_pct or {}, capital) - base_pp, 6)
    gain_s = round(_book_apy_pp(book_subset, apy_pct or {}, capital) - base_pp, 6)
    pb_i = _payback_days(cost_i, gain_i, capital)
    pb_s = _payback_days(cost_s, gain_s, capital)
    bps_i = (cost_i / turnover_i * 10_000.0) if turnover_i > _EPS else None
    bps_s = (cost_s / turnover_s * 10_000.0) if turnover_s > _EPS else None

    out.update({
        "kind": SHAPE_MEASURED,
        "interpolated": {"legs": len(legs_i), "turnover_usd": round(turnover_i, 2),
                         "cost_usd": round(cost_i, 2), "gain_pp": gain_i,
                         "payback_days": pb_i,
                         "cost_bps": None if bps_i is None else round(bps_i, 2)},
        "subset": {"legs": len(legs_s), "turnover_usd": round(turnover_s, 2),
                   "cost_usd": round(cost_s, 2), "gain_pp": gain_s,
                   "payback_days": pb_s,
                   "cost_bps": None if bps_s is None else round(bps_s, 2)},
        "legs_delta": len(legs_s) - len(legs_i),
        "cost_delta_usd": round(cost_s - cost_i, 2),
        "gain_delta_pp": round(gain_s - gain_i, 6),
        "payback_delta_days": (None if (pb_i is None or pb_s is None)
                               else round(pb_s - pb_i, 2)),
        "why": (f"одно предложение ${turnover_full:,.0f} под потолком "
                f"${admissible:,.0f}: интерполяция — {len(legs_i)} ног, "
                f"${cost_i:,.2f}, выигрыш {gain_i:.4f} пп"
                + ("" if pb_i is None else f", окупаемость {pb_i:,.1f} дн.")
                + f" · подмножество — {len(legs_s)} ног, ${cost_s:,.2f}, выигрыш "
                  f"{gain_s:.4f} пп"
                + ("" if pb_s is None else f", окупаемость {pb_s:,.1f} дн.")
                + ("" if chains_measured else
                   "; карта сетей НЕ прочитана — абсолютные бп занижены на мост, "
                   "дельта осмысленна (карта у форм одна)")),
    })
    return out


#: Исходы вопроса «что перепись форм знает». Третий — самостоятельное значение.
CENSUS_MEASURED = "measured"
CENSUS_MEASURED_ZERO = "measured_zero"   # урезаемых предложений не нашлось — ЗАМЕР нуля
CENSUS_UNMEASURED = "unmeasured"         # мерить было нечем


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 4)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 4)


def trim_shape_census(records: List[dict], *, params,
                      chains: Dict[str, str],
                      chains_measured: bool) -> dict:
    """Форма урезания на ВСЕЙ записанной истории предложений, а не на одной записи.

    ADR-853 честно назвал цену трима замером с населением **ОДНА запись** —
    живых урезаний больше и не было. Эта перепись спрашивает соседний вопрос,
    у которого население другое по построению: урезаемым является любое
    записанное предложение, чей оборот ВЫШЕ потолка размера, независимо от
    того, дошла ли до него живая проводка ADR-850.

    Перепись только ЧИТАЕТ и ничего не чинит.
    """
    if not isinstance(records, list):
        return {"kind": CENSUS_UNMEASURED,
                "why": "история не список — перепись форм не измерена"}
    rows: List[dict] = []
    outcomes: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        proposal, source = _proposal_of(rec)
        sources[source] = sources.get(source, 0) + 1
        cmp_ = compare_trim_shapes(
            rec.get("current_positions") or {},
            proposal,
            rec.get("apy_evidenced_pct") or {},
            capital_usd=rec.get("capital_usd") or 0.0,
            params=params, chains=chains, chains_measured=chains_measured)
        kind = str(cmp_.get("kind"))
        outcomes[kind] = outcomes.get(kind, 0) + 1
        if kind == SHAPE_MEASURED:
            cmp_["date"] = rec.get("cycle_date")
            cmp_["proposal_source"] = source
            rows.append(cmp_)
    if not rows:
        return {"kind": (CENSUS_MEASURED_ZERO if outcomes else CENSUS_UNMEASURED),
                "outcomes": outcomes,
                "proposal_sources": sources,
                "records": len([r for r in records if isinstance(r, dict)]),
                "why": ("урезаемых предложений в истории не нашлось — это ЗАМЕР нуля"
                        if outcomes else
                        "ни одной разобранной записи — перепись форм не измерена")}

    horizon = float(getattr(params, "max_payback_days", 0.0) or 0.0)
    legs_fewer = sum(1 for r in rows if r["legs_delta"] < 0)
    legs_same = sum(1 for r in rows if r["legs_delta"] == 0)
    legs_more = sum(1 for r in rows if r["legs_delta"] > 0)
    cheaper = sum(1 for r in rows if r["cost_delta_usd"] < -_EPS)
    same_cost = sum(1 for r in rows if abs(r["cost_delta_usd"]) <= _EPS)
    dearer = sum(1 for r in rows if r["cost_delta_usd"] > _EPS)
    gain_up = sum(1 for r in rows if r["gain_delta_pp"] > _EPS)
    gain_same = sum(1 for r in rows if abs(r["gain_delta_pp"]) <= _EPS)
    gain_down = sum(1 for r in rows if r["gain_delta_pp"] < -_EPS)
    both_pb = [r for r in rows if r["payback_delta_days"] is not None]
    pb_better = sum(1 for r in both_pb if r["payback_delta_days"] < -_EPS)
    pb_same = sum(1 for r in both_pb if abs(r["payback_delta_days"]) <= _EPS)
    pb_worse = sum(1 for r in both_pb if r["payback_delta_days"] > _EPS)
    # Окупаемость, не определённая у ОДНОЙ из форм, — отдельное число: выдать её
    # за «не изменилась» значило бы потерять ровно тот случай, где форма делает
    # выигрыш положительным там, где соседка его не делает.
    pb_one_side = len(rows) - len(both_pb)
    # Оборот форм обязан совпадать; где он МЕНЬШЕ, подмножество упёрлось в
    # ёмкость сторон, и тогда его цена сравнивается с ходом ДРУГОГО размера.
    turnover_equal = sum(1 for r in rows
                         if abs(r["subset"]["turnover_usd"]
                                - r["interpolated"]["turnover_usd"]) <= 1.0)
    turnover_smaller = sum(1 for r in rows
                           if r["subset"]["turnover_usd"]
                           < r["interpolated"]["turnover_usd"] - 1.0)
    turnover_larger = sum(1 for r in rows
                          if r["subset"]["turnover_usd"]
                          > r["interpolated"]["turnover_usd"] + 1.0)
    # Подмножество обязано УКЛАДЫВАТЬСЯ в тот же потолок размера. Число
    # превышений печатается ДАЖЕ когда оно ноль: «измерено и равно нулю» и
    # «не измерено» обязаны быть различимы (инв. #17), а форма, тихо
    # вышедшая за потолок, сравнивалась бы с соседкой не по тому вопросу.
    turnover_over_cap = sum(1 for r in rows
                            if r["subset"]["turnover_usd"]
                            > float(r.get("admissible_usd") or 0.0) + 0.01)
    within_i = sum(1 for r in both_pb
                   if r["interpolated"]["payback_days"] <= horizon + _EPS)
    within_s = sum(1 for r in both_pb
                   if r["subset"]["payback_days"] <= horizon + _EPS)
    return {
        "kind": CENSUS_MEASURED,
        "records": len([r for r in records if isinstance(r, dict)]),
        "outcomes": outcomes,
        "proposal_sources": sources,
        "population": len(rows),
        "dates": len({r.get("date") for r in rows}),
        "legs": {"fewer": legs_fewer, "same": legs_same, "more": legs_more,
                 "delta_median": _median([float(r["legs_delta"]) for r in rows])},
        "cost": {"cheaper": cheaper, "same": same_cost, "dearer": dearer,
                 "delta_usd_median": _median([r["cost_delta_usd"] for r in rows])},
        "gain": {"higher": gain_up, "same": gain_same, "lower": gain_down,
                 "delta_pp_median": _median([r["gain_delta_pp"] for r in rows])},
        "payback": {
            "comparable": len(both_pb),
            "undefined_on_one_side": pb_one_side,
            "better": pb_better, "same": pb_same, "worse": pb_worse,
            "median_interpolated": _median(
                [r["interpolated"]["payback_days"] for r in both_pb]),
            "median_subset": _median([r["subset"]["payback_days"] for r in both_pb]),
            "horizon_days": horizon,
            "within_horizon_interpolated": within_i,
            "within_horizon_subset": within_s,
        },
        "turnover": {"equal": turnover_equal, "smaller": turnover_smaller,
                     "larger": turnover_larger, "over_cap": turnover_over_cap},
        "last": rows[-1],
        "chains_measured": bool(chains_measured),
        "note": ("формы сравниваются при ОДНОМ потолке размера, ОДНОМ чистом "
                 "движении кэша и ОДНОЙ модели издержек — меняется только форма; "
                 "книга подмножества допустимой НЕ объявляется (RiskPolicy не "
                 "спрашивали), поэтому измерен РАЗМЕР ПРИЗА формы, а не "
                 "разрешение его взять"),
    }


def trim_shape_outcome(census: Optional[dict]) -> Tuple[str, str]:
    """Дверь чтения переписи форм — ОДНА на всех читателей.

    Почему дверь, а не ``census["kind"]`` у каждого: у ADR-851 ровно на этом
    развилось «шага не звали» и «шаг сработал ноль раз» — два читателя одного
    артефакта разошлись в том, чем считать отсутствие блока. Возврат
    ``(исход, причина)``; причина НАЗЫВАЕТСЯ всегда.
    """
    if not isinstance(census, dict) or not census:
        return CENSUS_UNMEASURED, ("блока переписи форм в артефакте нет — запись "
                                   "СТАРШЕ прибора, а не его ноль (урок ADR-851)")
    kind = str(census.get("kind") or "")
    if kind == CENSUS_MEASURED:
        pop = census.get("population")
        return CENSUS_MEASURED, f"форма сравнена на {pop} предложени(и/ях)"
    if kind == CENSUS_MEASURED_ZERO:
        return CENSUS_MEASURED_ZERO, str(census.get("why")
                                         or "урезаемых предложений не нашлось")
    if kind == CENSUS_UNMEASURED:
        return CENSUS_UNMEASURED, str(census.get("why") or "причина не названа")
    return CENSUS_UNMEASURED, f"исход переписи форм не разобран ({kind!r})"


def format_trim_shape(census: Optional[dict]) -> List[str]:
    """Печать переписи форм — своя, а не строка внутри печати ЦЕНЫ (ADR-853).

    Вопросы разные и исходы у них НЕ совпадают: цена трима может быть измерена,
    а форма — нет (и наоборот, как сегодня: цена живого трима не записана, а
    формы сравнены на всей истории). Слить их в одну печать значило бы, что
    ответ на один вопрос меняет чтение ответа на другой.
    """
    kind, why = trim_shape_outcome(census)
    head = "форма урезания (ADR-854, ADVISORY — допустимость не утверждается):"
    if kind != CENSUS_MEASURED:
        return [head, f"  [{kind}] {why}"]
    legs = census.get("legs") or {}
    cost = census.get("cost") or {}
    gain = census.get("gain") or {}
    pb = census.get("payback") or {}
    turn = census.get("turnover") or {}
    last = census.get("last") or {}
    lines = [
        head,
        f"  население {census.get('population')} предложени(й) / "
        f"{census.get('dates')} дат (урезаемых; записей просмотрено "
        f"{census.get('records')}); источник предложения "
        f"{census.get('proposal_sources')}",
        f"  ног: меньше {legs.get('fewer')} · столько же {legs.get('same')} · "
        f"больше {legs.get('more')} (медиана дельты {legs.get('delta_median')})",
        f"  цена: дешевле {cost.get('cheaper')} · та же {cost.get('same')} · "
        f"дороже {cost.get('dearer')} (медиана дельты "
        f"${cost.get('delta_usd_median')})",
        f"  выигрыш: выше {gain.get('higher')} · тот же {gain.get('same')} · "
        f"ниже {gain.get('lower')} (медиана дельты "
        f"{gain.get('delta_pp_median')} пп)",
        f"  окупаемость: сравнимы {pb.get('comparable')} · лучше "
        f"{pb.get('better')} · та же {pb.get('same')} · хуже {pb.get('worse')} · "
        f"не определена у одной формы {pb.get('undefined_on_one_side')}",
        f"  медиана окупаемости: интерполяция {pb.get('median_interpolated')} дн. "
        f"→ подмножество {pb.get('median_subset')} дн. (горизонт гейта "
        f"{pb.get('horizon_days')} дн.: укладываются "
        f"{pb.get('within_horizon_interpolated')} → "
        f"{pb.get('within_horizon_subset')})",
        f"  оборот форм: равен {turn.get('equal')} · у подмножества меньше "
        f"{turn.get('smaller')} · больше {turn.get('larger')} · ВЫШЕ ПОТОЛКА "
        f"{turn.get('over_cap')} — где МЕНЬШЕ, подмножество упёрлось в ёмкость "
        f"сторон; где БОЛЬШЕ, интерполяция потеряла ход на пыли (её мелкие ноги "
        f"отсекает дверь `_legs`), а не подмножество вышло за потолок",
    ]
    if last:
        lines.append(
            f"  последнее: {last.get('date')} — ног "
            f"{(last.get('interpolated') or {}).get('legs')} → "
            f"{(last.get('subset') or {}).get('legs')}, окупаемость "
            f"{(last.get('interpolated') or {}).get('payback_days')} → "
            f"{(last.get('subset') or {}).get('payback_days')} дн.")
    if not census.get("chains_measured"):
        lines.append("  карта сетей НЕ прочитана — абсолютные бп занижены на мост; "
                     "дельта осмысленна (карта у форм одна)")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: допустима ли книга подмножества (RiskPolicy не "
                 "спрашивали; потолок на ГРУППУ угол бокса не сохраняет) · "
                 "предложил ли бы аллокатор именно её · исход хода")
    return lines
