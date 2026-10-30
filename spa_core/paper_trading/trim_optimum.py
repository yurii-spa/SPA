"""ЖАДНЫЙ СПРЕД — НИЖНЯЯ ГРАНИЦА, а не оптимум (ADR-859).

Что здесь нового по сравнению с соседями
------------------------------------------------------------------------------
Шесть блоков уже спрашивают про урезанный ход, и ни один не спрашивает, есть ли
книга ЛУЧШЕ той, которую выбрал жадный спред:

====================================  ========================================
``admissible_size_reach`` (ADR-848)   прошёл бы ход, УРЕЗАННЫЙ до потолка
``admissible_trim`` (ADR-850)         живая проводка: цель урезается до потолка
``…_trim.cost_of_the_trim`` (ADR-853) сколько стоит ОДНО предложение до/после
``trim_shape`` (ADR-854)              дешевле ли урезание ДРУГОЙ формы
``trim_admissibility`` (ADR-855)      пустит ли КНИГУ формы RiskPolicy
**этот модуль**                       **есть ли ДОПУСТИМАЯ книга ЛУЧШЕ жадной**
====================================  ========================================

ADR-855 закрыл вопрос о допустимости и сам назвал, что осталось:

    «жадный спред есть НИЖНЯЯ граница, не оптимум»

Основание у этой оговорки было прямое. Жадный спред (``trim_shape.subset_trim``)
выбирает ноги по наблюдённой ставке — «забирать с худшей, докладывать в лучшую» —
и **про потолки не спрашивает вообще**. Замер ADR-855: из 103 предложений дверь
книги отказывает жадной книге на 45, и вина ФОРМЫ в 37, из них ``t2_group_cap``
в 36. То есть ограничение, которое жадный игнорирует, — не редкость, а главная
причина его отказов: задача с ограничениями, а не сортировка.

Но «жадный не оптимален» было РАССУЖДЕНИЕМ о возможности. Сколько стоит
незаданный вопрос — не знал никто, и приз ADR-854/855 держался на этом.

Что именно здесь измерено — и чего замер НЕ даёт
------------------------------------------------------------------------------
Поиск перечисляет ПОДМНОЖЕСТВА ног предложения (обе стороны), внутри
подмножества раскладывает бюджет тем же правилом спреда, а размер хода берёт
НАИБОЛЬШИЙ ДОПУСТИМЫЙ — его ищет деление отрезка, и допустимость спрашивается
ТОЙ ЖЕ дверью книги (``trim_admissibility.book_verdict``), что у ADR-855.

Деление отрезка здесь ТОЧНО, а не приблизительно, и причина структурная: все
потолки двери книги ЛИНЕЙНЫ по позициям (доля протокола, сумма группы тира,
суммарный L2, концентрация на сеть, буфер кэша), а книги подмножества при росте
размера хода лежат на ОТРЕЗКЕ. Пересечение отрезка с полупространствами есть
ОТРЕЗОК ⇒ множество допустимых размеров связно, и деление находит его край.
Число позиций на открытом конце постоянно (позиция появляется при любом размере
> 0), поэтому счётный потолок связность не рвёт — тем более что дверь книги его
не спрашивает вовсе (находка #973, карточка про ``max_protocols``).

**Поиск ДОМИНИРУЕТ жадный по построению.** Полное подмножество при размере, равном
потолку, И ЕСТЬ книга жадного спреда, поэтому она всегда среди перебранных:
допустим жадный ⇒ ответ поиска не хуже. Это не надежда, а инвариант, и он
проверен на всём населении (замер: 0 нарушений) И отдельным тестом.

**И при этом поиск НЕ есть оптимум — он НИЖНЯЯ граница оптимума.** Две названные
причины, обе измеримы и ни одна не замолчана:

* внутри подмножества раскладка фиксирована спредом. При линейной цели и одном
  бюджете это оптимально, но ГРУППОВОЙ потолок — ещё одно ограничение, и
  неравномерный делёж мог бы оказаться допустимым при БОЛЬШЕМ размере хода;
* берётся наибольший допустимый размер. Окупаемость по размеру убывает (газ за
  ногу постоянен, проскальзывание и выигрыш растут вместе), но НЕ строго: дверь
  оборота (``_legs``) отсекает ногу ниже ``min_leg_frac``, и меньший размер
  может уронить ногу, то есть и газ. Монотонность поэтому не доказана.

Выдать найденное за оптимум значило бы ровно ту подмену, против которой написан
весь этот ряд: нижняя граница, названная оптимумом, закрывает вопрос, оставаясь
открытым. Поэтому исход зовётся ПОИСКОМ, и в печати стои́т слово «граница».

С ЧЕМ сравнивать — и почему не с жадным
------------------------------------------------------------------------------
Сравнивать приз с окупаемостью жадной книги можно ТОЛЬКО там, где дверь эту
книгу пускает. Жадная книга, которой дверь отказала, — не «дорогой вариант», её
НЕТ: её окупаемость не хуже и не лучше, она недоступна. Замер это и показывает:
по всему населению медиана жадного выглядит ЛУЧШЕ медианы поиска ровно потому,
что в неё входят отказанные книги. Поэтому публикуются ДВА числа, и главное —
второе: против лучшей ДОПУСТИМОЙ из прежних двух форм.

Смешать их — тот же дефект, что смешать роды числа на витрине (ADR-580 C2):
сравнение допустимо внутри одного рода, а «книга, которую пустят» и «книга,
которую отказали» — разные роды.

Только stdlib. LLM здесь запрещён — это замер, не суждение. Прибор ЧИТАЕТ и
ничего не чинит: ни один порог не правится, ни один доллар не двигается.
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

_EPS = 1e-9

#: Шагов деления отрезка при поиске наибольшего допустимого размера хода.
#: Сорок шагов на потолке в $15 000 дают разрешение ~1.4e-8 доллара — предел
#: далеко за ценой цента, до которой книга округляется, поэтому край отрезка
#: найден с точностью, которую сама книга уже не различает.
BISECT_STEPS = 40

#: Потолок перебора НА ЗАПИСЬ. Замер 29.10 на живой истории: максимум 512
#: подмножеств у одной записи, 3460 по всем 104 — то есть предел не достигается
#: ни разу и стои́т здесь не ради скорости, а ради ТРЕТЬЕГО ИСХОДА: запись с
#: большим числом ног обязана уйти в `search_truncated` с НАЗВАННЫМ числом, а не
#: получить молча урезанный перебор, выданный за полный (инв. #17).
MAX_SUBSETS_PER_RECORD = 4096

#: Исходы ОДНОЙ записи. Каждый назван, и ни один не притворяется соседом.
OPT_MEASURED = "measured"
OPT_UNMEASURED = "unmeasured"
OPT_NO_SUBJECT = "no_subject"                # оборот внутри потолка ⇒ урезать нечего
OPT_NO_ALTERNATIVE = "no_alternative"        # формы-соседки не существует
OPT_TIER_UNKNOWN = "tier_unknown"            # ярлык тира не прочитан ⇒ потолки не определены
OPT_STANDING_INADMISSIBLE = "standing_inadmissible"  # день уже стоял вне политики
OPT_NONE_ADMISSIBLE = "none_admissible"      # перебрано всё, допустимой книги НЕТ
OPT_SEARCH_TRUNCATED = "search_truncated"    # ног больше, чем потолок перебора

CENSUS_MEASURED = "measured"
CENSUS_MEASURED_ZERO = "measured_zero"
CENSUS_UNMEASURED = "unmeasured"


def _fill(current: Dict[str, float],
          inc_sel: List[List],
          dec_sel: List[List],
          turnover: float,
          net_cash_usd: float) -> Optional[Dict[str, float]]:
    """Книга выбранных ног при целевом размере хода ``turnover``.

    ``None`` — подмножество несовместимо с чистым движением кэша соседки: это
    условие СРАВНЕНИЯ (``subset_trim``), и снять его значило бы разрешить поиску
    разворачивать кэш, которого соседка не разворачивала.
    """
    room_inc = sum(a for _, a in inc_sel)
    room_dec = sum(a for _, a in dec_sel)
    if net_cash_usd >= 0:
        moved = min(turnover, room_inc, room_dec + net_cash_usd)
        buy, sell = moved, moved - net_cash_usd
    else:
        moved = min(turnover, room_dec, room_inc - net_cash_usd)
        buy, sell = moved + net_cash_usd, moved
    if buy < -_EPS or sell < -_EPS:
        return None
    if buy <= _EPS and sell <= _EPS:
        return None
    book = {str(p): float(v or 0.0) for p, v in (current or {}).items()}
    for side, budget, sign in ((inc_sel, buy, 1.0), (dec_sel, sell, -1.0)):
        left = budget
        for proto, room in side:
            if left <= _EPS:
                break
            take = min(room, left)
            left -= take
            book[proto] = round(float(book.get(proto, 0.0) or 0.0) + sign * take, 2)
    return {p: v for p, v in book.items() if v > 0.0}


def _approved(book: Dict[str, float], apy_pct: Dict[str, float],
              capital_usd: float, *, tiers: Dict[str, str],
              chains: Dict[str, str]) -> Optional[bool]:
    """Пустит ли дверь КНИГИ. ``None`` — ярлык тира неизвестен (третий исход)."""
    from spa_core.paper_trading.trim_admissibility import book_verdict

    verdict, _unknown = book_verdict(book, apy_pct, capital_usd,
                                     tiers=tiers, chains=chains)
    if verdict is None:
        return None
    return bool(verdict.get("approved"))


def _unexecuted(current: Dict[str, float], book: Dict[str, float],
                capital_usd: float, min_leg_frac: float,
                legs: List[dict]) -> Dict[str, float]:
    """Проводка к ЕДИНСТВЕННОЙ двери ADR-864 — своего правила пыли здесь нет.

    Имя у проводки отдельное по одной причине: приёмка обязана уметь порвать
    ЭТО звено, не задевая соседнее. Дверь у `evaluate` и у перебора размеров
    одна (``rebalance_economics.unexecuted_legs``), и подмена самой двери
    рвёт оба звена сразу — то есть контроль «перебор перестал отказывать»
    был бы неотличим от «вердикт перестал отказывать».
    """
    from spa_core.allocator.rebalance_economics import unexecuted_legs
    return unexecuted_legs(current, book, capital_usd, min_leg_frac, legs=legs)


def score_book(current: Dict[str, float], book: Dict[str, float],
               apy_pct: Dict[str, float], *, capital_usd: float,
               min_leg_frac: float, chains: Dict[str, str]) -> Optional[dict]:
    """Цена, выигрыш и окупаемость книги — ТЕМИ ЖЕ дверями, что у цикла.

    ``None`` — окупаемость не определена (материального хода нет либо выигрыша
    нет). Это ЗНАЧЕНИЕ, а не ноль: ноль прочитался бы как «окупается мгновенно»
    (``trim_shape._payback_days``).
    """
    from spa_core.allocator.rebalance_economics import _legs, _move_cost_usd
    from spa_core.paper_trading.trim_shape import _book_apy_pp, _payback_days

    legs, turnover = _legs(current, book, capital_usd, min_leg_frac)
    if not legs or turnover <= _EPS:
        return None
    # ADR-864: книга, одну из ног которой дверь цены не исполнит, НЕ СЧИТАЕТСЯ.
    # Это та же дверь и та же причина, что у `evaluate`: цена посчитана по
    # материальным ногам, а выигрыш — по книге, которой мы держать не будем.
    # Без этой строки перебор размеров выигрывал тем, что сползал к
    # `min_leg_usd ± $0.01` (замер #978: 8 «улучшений» из 8 — ровно эта полоса).
    # ``None`` здесь уже означает «окупаемость не определена» — отдельного
    # значения заводить не нужно.
    if _unexecuted(current, book, capital_usd, min_leg_frac, legs):
        return None
    cost = _move_cost_usd(legs, turnover, chains)
    gain = (_book_apy_pp(book, apy_pct, capital_usd)
            - _book_apy_pp(current, apy_pct, capital_usd))
    payback = _payback_days(cost, gain, capital_usd)
    if payback is None:
        return None
    return {"payback_days": payback, "cost_usd": round(cost, 2),
            "gain_pp": gain, "legs": len(legs),
            "turnover_usd": round(turnover, 2), "book": book}


def _largest_admissible_turnover(current, inc_sel, dec_sel, *, ceiling, net,
                                 apy_pct, capital_usd, tiers, chains,
                                 steps: int = BISECT_STEPS) -> Optional[float]:
    """Край отрезка допустимых размеров хода на ЭТОМ подмножестве ног.

    ``None`` — допустимой книги на подмножестве нет ни при каком размере > 0.
    Деление корректно потому, что множество допустимых размеров СВЯЗНО (см.
    докстринг модуля): потолки двери линейны, книги лежат на отрезке.
    """
    def ok(size: float) -> bool:
        book = _fill(current, inc_sel, dec_sel, size, net)
        if book is None:
            return False
        return _approved(book, apy_pct, capital_usd,
                         tiers=tiers, chains=chains) is True

    if ok(ceiling):
        return ceiling
    lo, hi, found = 0.0, ceiling, None
    for _ in range(steps):
        mid = (lo + hi) / 2.0
        if ok(mid):
            lo, found = mid, mid
        else:
            hi = mid
    return found


def search_admissible_optimum(current: Dict[str, float],
                              proposal: Dict[str, float],
                              apy_pct: Dict[str, float],
                              *,
                              admissible_usd: float,
                              net_cash_usd: float,
                              capital_usd: float,
                              min_leg_frac: float,
                              tiers: Dict[str, str],
                              chains: Dict[str, str],
                              max_subsets: int = MAX_SUBSETS_PER_RECORD) -> dict:
    """Лучшая НАЙДЕННАЯ допустимая книга. Возврат — запись с ``kind``.

    НИЖНЯЯ ГРАНИЦА оптимума, а не оптимум: обе причины названы в докстринге
    модуля и повторены в самом возврате полем ``claim``.
    """
    from spa_core.paper_trading.trim_shape import _sides

    inc, dec = _sides(current or {}, proposal or {})
    inc.sort(key=lambda row: -float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    dec.sort(key=lambda row: float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    total = (2 ** len(inc)) * (2 ** len(dec))
    if total > max_subsets:
        return {"kind": OPT_SEARCH_TRUNCATED,
                "why": (f"ног {len(inc)}+{len(dec)} ⇒ подмножеств {total} при "
                        f"потолке перебора {max_subsets} — перебор НЕ полон, и "
                        f"урезанный выдавать за полный нельзя"),
                "subsets_total": total}
    best: Optional[dict] = None
    tried = 0
    admissible_found = 0
    for n_i in range(len(inc) + 1):
        for pick_i in itertools.combinations(range(len(inc)), n_i):
            inc_sel = [inc[i] for i in pick_i]
            for n_d in range(len(dec) + 1):
                for pick_d in itertools.combinations(range(len(dec)), n_d):
                    dec_sel = [dec[i] for i in pick_d]
                    if not inc_sel and not dec_sel:
                        continue
                    tried += 1
                    size = _largest_admissible_turnover(
                        current, inc_sel, dec_sel,
                        ceiling=admissible_usd, net=net_cash_usd,
                        apy_pct=apy_pct, capital_usd=capital_usd,
                        tiers=tiers, chains=chains)
                    if size is None:
                        continue
                    book = _fill(current, inc_sel, dec_sel, size, net_cash_usd)
                    if book is None:
                        continue
                    admissible_found += 1
                    scored = score_book(current, book, apy_pct,
                                        capital_usd=capital_usd,
                                        min_leg_frac=min_leg_frac, chains=chains)
                    if scored is None:
                        continue
                    if (best is None
                            or scored["payback_days"] < best["payback_days"] - 1e-9):
                        best = dict(scored,
                                    subset_buy=tuple(p for p, _ in inc_sel),
                                    subset_sell=tuple(p for p, _ in dec_sel))
    if best is None:
        return {"kind": OPT_NONE_ADMISSIBLE,
                "why": ("перебраны все подмножества ног — допустимой книги с "
                        "определённой окупаемостью не нашлось"),
                "subsets_tried": tried,
                "admissible_books_found": admissible_found}
    return {"kind": OPT_MEASURED,
            "best": best,
            "subsets_tried": tried,
            "admissible_books_found": admissible_found,
            "claim": ("НИЖНЯЯ ГРАНИЦА оптимума: раскладка внутри подмножества "
                      "фиксирована спредом, а размер взят НАИБОЛЬШИЙ допустимый "
                      "(монотонность окупаемости по размеру не доказана — дверь "
                      "оборота отсекает ногу ниже min_leg_frac)")}


def compare_trim_optimum(current: Dict[str, float],
                         proposal: Dict[str, float],
                         apy_pct: Dict[str, float],
                         *,
                         capital_usd: float,
                         params,
                         tiers: Dict[str, str],
                         chains: Dict[str, str]) -> dict:
    """ОДНА запись: жадный · интерполяция · поиск — одной дверью книги.

    Стоящая книга судится не для красоты: день, уже стоявший вне политики, не
    даёт сравнить формы — отказ пришёл из наследства, а не из раскладки
    (урок ADR-855 про ДВА конца отрезка).
    """
    from spa_core.paper_trading.trim_shape import (SHAPE_MEASURED,
                                                   SHAPE_NO_ALTERNATIVE,
                                                   SHAPE_NO_SUBJECT,
                                                   shapes_of_proposal)

    shapes = shapes_of_proposal(current, proposal, apy_pct,
                                capital_usd=capital_usd, params=params)
    kind = str(shapes.get("kind"))
    if kind == SHAPE_NO_SUBJECT:
        return {"kind": OPT_NO_SUBJECT, "why": str(shapes.get("why") or "")}
    if kind == SHAPE_NO_ALTERNATIVE:
        return {"kind": OPT_NO_ALTERNATIVE, "why": str(shapes.get("why") or "")}
    if kind != SHAPE_MEASURED:
        return {"kind": OPT_UNMEASURED, "why": str(shapes.get("why") or "")}

    cur = shapes["current"]
    capital = float(shapes["capital_usd"])
    mlf = float(shapes["min_leg_frac"])
    admissible = float(shapes["admissible_usd"])
    net = float(shapes["net_cash_usd"])
    book_greedy = shapes["book_subset"]
    book_interp = shapes["book_interpolated"]

    standing = _approved(cur, apy_pct, capital, tiers=tiers, chains=chains)
    if standing is None:
        return {"kind": OPT_TIER_UNKNOWN,
                "why": ("ярлык тира стоящей книги не прочитан — ни один потолок "
                        "не определён; второй тир НЕ подставляется (ADR-359)")}
    if standing is False:
        return {"kind": OPT_STANDING_INADMISSIBLE,
                "why": ("день уже стоял вне политики — отказ формы пришёл бы из "
                        "наследства, и приз раскладки на нём не измерим")}

    ok_greedy = _approved(book_greedy, apy_pct, capital, tiers=tiers, chains=chains)
    ok_interp = _approved(book_interp, apy_pct, capital, tiers=tiers, chains=chains)
    if ok_greedy is None or ok_interp is None:
        return {"kind": OPT_TIER_UNKNOWN,
                "why": ("ярлык тира книги формы не прочитан — ни потолок на "
                        "протокол, ни сумма группы не определены; второй тир НЕ "
                        "подставляется (ADR-359)")}

    sc_greedy = score_book(cur, book_greedy, apy_pct, capital_usd=capital,
                           min_leg_frac=mlf, chains=chains)
    sc_interp = score_book(cur, book_interp, apy_pct, capital_usd=capital,
                           min_leg_frac=mlf, chains=chains)
    found = search_admissible_optimum(
        cur, shapes["proposal"], apy_pct,
        admissible_usd=admissible, net_cash_usd=net, capital_usd=capital,
        min_leg_frac=mlf, tiers=tiers, chains=chains)

    # Лучшая ДОПУСТИМАЯ из двух прежних форм — единственная база сравнения,
    # которая не смешивает рода (см. докстринг модуля).
    known: List[float] = []
    if ok_greedy and sc_greedy:
        known.append(float(sc_greedy["payback_days"]))
    if ok_interp and sc_interp:
        known.append(float(sc_interp["payback_days"]))
    best_known = min(known) if known else None

    out = {
        "kind": (OPT_MEASURED if str(found.get("kind")) == OPT_MEASURED
                 else str(found.get("kind"))),
        "admissible_usd": admissible,
        "net_cash_usd": net,
        "approved": {"greedy": bool(ok_greedy), "interpolated": bool(ok_interp)},
        "payback": {
            "greedy": (None if not sc_greedy else sc_greedy["payback_days"]),
            "interpolated": (None if not sc_interp else sc_interp["payback_days"]),
            "best_known_admissible": best_known,
            "search": None,
        },
        "legs": {"greedy": (None if not sc_greedy else sc_greedy["legs"]),
                 "interpolated": (None if not sc_interp else sc_interp["legs"])},
        "search": found,
    }
    if str(found.get("kind")) == OPT_MEASURED:
        out["payback"]["search"] = float(found["best"]["payback_days"])
    else:
        out["why"] = str(found.get("why") or "")
    return out


def trim_optimum_census(records: List[dict], *, params,
                        tiers: Dict[str, str],
                        tiers_measured: bool,
                        chains: Dict[str, str],
                        chains_measured: bool) -> dict:
    """Приз ОГРАНИЧЕННОГО ПОИСКА на всей записанной истории предложений.

    Население то же, что у ADR-854/855 по построению (любое записанное
    предложение выше потолка размера) — это условие сравнимости: три приза
    считаются на ОДНОЙ основе. Перепись только ЧИТАЕТ и ничего не чинит.
    """
    from spa_core.paper_trading.trim_shape import _median, _proposal_of

    if not isinstance(records, list):
        return {"kind": CENSUS_UNMEASURED,
                "why": "история не список — приз поиска не измерен"}
    if not tiers_measured:
        return {"kind": CENSUS_UNMEASURED,
                "why": ("реестр адаптеров не прочитан — ярлыков тира нет, и ни "
                        "один потолок на книге не определён; второй тир НЕ "
                        "подставляется (ADR-359)")}
    rows: List[dict] = []
    outcomes: Dict[str, int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        proposal, source = _proposal_of(rec)
        one = compare_trim_optimum(
            rec.get("current_positions") or {},
            proposal,
            rec.get("apy_evidenced_pct") or {},
            capital_usd=rec.get("capital_usd") or 0.0,
            params=params, tiers=tiers, chains=chains)
        kind = str(one.get("kind"))
        outcomes[kind] = outcomes.get(kind, 0) + 1
        if kind == OPT_MEASURED:
            one["date"] = rec.get("cycle_date")
            one["proposal_source"] = source
            rows.append(one)
    if not rows:
        return {"kind": (CENSUS_MEASURED_ZERO if outcomes else CENSUS_UNMEASURED),
                "outcomes": outcomes,
                "records": len([r for r in records if isinstance(r, dict)]),
                "why": ("сравнимых предложений в истории не нашлось — это ЗАМЕР "
                        "нуля" if outcomes else
                        "ни одной разобранной записи — приз поиска не измерен")}

    horizon = float(getattr(params, "max_payback_days", 0.0) or 0.0)

    def _pb(row: dict, name: str) -> Optional[float]:
        v = (row.get("payback") or {}).get(name)
        return None if v is None else float(v)

    def _pb_of(row: dict, name: str) -> float:
        """Число у записи, УЖЕ отобранной по наличию обоих чисел.

        Отдельная дверь, а не повтор ``_pb``: читатель списка сравнимых не
        должен снимать `Optional` на каждом сравнении — там, где число может
        отсутствовать, оно и отбирается, а здесь его отсутствие было бы
        дефектом отбора, и падать надо громко, а не подставлять ноль.
        """
        v = (row.get("payback") or {}).get(name)
        if v is None:
            raise AssertionError(
                f"отбор сравнимых пропустил запись без числа {name!r} — "
                f"это дефект отбора, а не ноль")
        return float(v)

    # Ось 1 — против ЖАДНОГО, и только там, где дверь жадную книгу ПУСКАЕТ.
    # Это и есть разделение родов: книга, которой отказано, недоступна, и её
    # число сравнению не подлежит.
    vs_greedy = [r for r in rows
                 if (r.get("approved") or {}).get("greedy")
                 and _pb(r, "greedy") is not None and _pb(r, "search") is not None]
    strictly_better = sum(1 for r in vs_greedy
                          if _pb_of(r, "search") < _pb_of(r, "greedy") - 1e-6)
    worse_than_greedy = sum(1 for r in vs_greedy
                            if _pb_of(r, "search") > _pb_of(r, "greedy") + 1e-6)
    # Ось 2 — против лучшей ДОПУСТИМОЙ из прежних двух форм (главное число).
    vs_known = [r for r in rows
                if _pb(r, "best_known_admissible") is not None
                and _pb(r, "search") is not None]
    return {
        "kind": CENSUS_MEASURED,
        "records": len([r for r in records if isinstance(r, dict)]),
        "outcomes": outcomes,
        "population": len(rows),
        "dates": len({r.get("date") for r in rows}),
        "horizon_days": horizon,
        "greedy_admissible": sum(1 for r in rows
                                 if (r.get("approved") or {}).get("greedy")),
        "interpolated_admissible": sum(1 for r in rows
                                       if (r.get("approved") or {}).get("interpolated")),
        "vs_greedy": {
            "comparable": len(vs_greedy),
            "median_greedy": _median([_pb_of(r, "greedy") for r in vs_greedy]),
            "median_search": _median([_pb_of(r, "search") for r in vs_greedy]),
            "search_strictly_better": strictly_better,
            "search_worse": worse_than_greedy,
            "note": ("сравнение ТОЛЬКО там, где дверь пускает жадную книгу: "
                     "отказанная книга недоступна, и её окупаемость не есть "
                     "вариант. `search_worse` обязан быть НУЛЁМ — полное "
                     "подмножество при потолке и есть книга жадного"),
        },
        "vs_best_known_admissible": {
            "comparable": len(vs_known),
            "median_known": _median([_pb_of(r, "best_known_admissible")
                                     for r in vs_known]),
            "median_search": _median([_pb_of(r, "search") for r in vs_known]),
            "search_strictly_better": sum(
                1 for r in vs_known
                if _pb_of(r, "search") < _pb_of(r, "best_known_admissible") - 1e-6),
            "within_horizon_known": sum(
                1 for r in vs_known
                if _pb_of(r, "best_known_admissible") <= horizon + _EPS),
            "within_horizon_search": sum(
                1 for r in vs_known if _pb_of(r, "search") <= horizon + _EPS),
        },
        "subsets_tried": sum(int((r.get("search") or {}).get("subsets_tried") or 0)
                             for r in rows),
        "last": rows[-1],
        "tiers_measured": bool(tiers_measured),
        "chains_measured": bool(chains_measured),
        "claim": ("НИЖНЯЯ ГРАНИЦА оптимума, НЕ оптимум — две названные причины "
                  "в докстринге модуля; доминирование жадного — инвариант "
                  "построения, а не наблюдение"),
        "note": ("вердикт спрошен у двери КНИГИ (`check_portfolio_health`, "
                 "ADR-134), НЕ у живой двери шага: снимка адаптеров дня история "
                 "не несёт. ADVISORY — ни один порог не правится, ни один доллар "
                 "не двигается"),
    }


def trim_optimum_outcome(census: Optional[dict]) -> Tuple[str, str]:
    """Дверь чтения переписи приза — ОДНА на всех читателей (урок ADR-851).

    Возврат ``(исход, причина)``; причина НАЗЫВАЕТСЯ всегда.
    """
    if not isinstance(census, dict) or not census:
        return CENSUS_UNMEASURED, ("блока приза поиска в артефакте нет — запись "
                                   "СТАРШЕ прибора, а не его ноль (урок ADR-851)")
    kind = str(census.get("kind") or "")
    if kind == CENSUS_MEASURED:
        return CENSUS_MEASURED, (f"приз поиска измерен на "
                                 f"{census.get('population')} предложени(и/ях)")
    if kind == CENSUS_MEASURED_ZERO:
        return CENSUS_MEASURED_ZERO, str(census.get("why")
                                         or "сравнимых предложений не нашлось")
    if kind == CENSUS_UNMEASURED:
        return CENSUS_UNMEASURED, str(census.get("why") or "причина не названа")
    return CENSUS_UNMEASURED, f"исход переписи приза не разобран ({kind!r})"


def format_trim_optimum(census: Optional[dict]) -> List[str]:
    """Печать переписи приза — своя, а не строка внутри печати допустимости.

    Вопросы разные, и исходы у них НЕ совпадают: допустимость может быть
    измерена, а приз — нет (ног больше потолка перебора), и наоборот.
    """
    kind, why = trim_optimum_outcome(census)
    head = ("приз ограниченного поиска (ADR-859, ADVISORY — НИЖНЯЯ граница "
            "оптимума, дверь КНИГИ):")
    if kind != CENSUS_MEASURED:
        return [head, f"  [{kind}] {why}"]
    doc: dict = census if isinstance(census, dict) else {}
    g = doc.get("vs_greedy") or {}
    k = doc.get("vs_best_known_admissible") or {}
    last = doc.get("last") or {}
    horizon = doc.get("horizon_days")
    lines = [
        head,
        f"  население {doc.get('population')} предложени(й) / "
        f"{doc.get('dates')} дат (записей просмотрено {doc.get('records')}); "
        f"исходы {doc.get('outcomes')}",
        f"  подмножеств ног перебрано {doc.get('subsets_tried')}; жадная книга "
        f"допустима на {doc.get('greedy_admissible')}, интерполяция — на "
        f"{doc.get('interpolated_admissible')} из {doc.get('population')}",
        f"  ПРОТИВ ЖАДНОГО (только там, где его книгу дверь ПУСКАЕТ, "
        f"{g.get('comparable')}): медиана {g.get('median_greedy')} → "
        f"{g.get('median_search')} дн.; поиск СТРОГО лучше на "
        f"{g.get('search_strictly_better')}, ХУЖЕ на {g.get('search_worse')} "
        f"(ХУЖЕ обязан быть 0 — доминирование по построению)",
        f"  ПРОТИВ лучшей ДОПУСТИМОЙ прежней формы ({k.get('comparable')}) — "
        f"главное число: медиана {k.get('median_known')} → "
        f"{k.get('median_search')} дн.; строго лучше на "
        f"{k.get('search_strictly_better')}; в горизонт {horizon} дн. "
        f"{k.get('within_horizon_known')} → {k.get('within_horizon_search')}",
    ]
    if last:
        pb = last.get("payback") or {}
        best = (last.get("search") or {}).get("best") or {}
        lines.append(
            f"  последняя запись {last.get('date')}: жадный "
            f"{pb.get('greedy')} (допустим "
            f"{(last.get('approved') or {}).get('greedy')}) · интерполяция "
            f"{pb.get('interpolated')} (допустима "
            f"{(last.get('approved') or {}).get('interpolated')}) · ПОИСК "
            f"{pb.get('search')} дн. на {best.get('legs')} ног(ах), оборот "
            f"${float(best.get('turnover_usd') or 0.0):,.0f}")
    lines.append(f"  {doc.get('claim')}")
    lines.append(f"  {doc.get('note')}")
    return lines
