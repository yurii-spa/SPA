"""КРАЙ ОТРЕЗКА — ОПТИМУМ внутри подмножества или нет (ADR-861).

Что здесь нового по сравнению с соседями
------------------------------------------------------------------------------
Семь блоков уже спрашивают про урезанный ход, и ADR-859 (восьмой) назвал свой
ответ НИЖНЕЙ ГРАНИЦОЙ оптимума, перечислив РОВНО ДВЕ причины, по которым
граница не есть оптимум:

1. внутри подмножества раскладка фиксирована спредом;
2. **берётся НАИБОЛЬШИЙ допустимый размер хода** — «окупаемость по размеру
   убывает, но НЕ строго: дверь оборота отсекает ногу ниже ``min_leg_frac``, и
   меньший размер может уронить ногу, то есть и газ. Монотонность поэтому не
   доказана».

Этот модуль закрывает ПРИЧИНУ 2 — и закрывает замером, а не рассуждением.
Причина 1 остаётся открытой, и это сказано вслух здесь, в переписи и в печати:
её снимает только настоящий оптимум (на каждом подмножестве — задача линейного
программирования), а он money-path и ждёт отдельного решения владельца.

Почему перебор КОНЦОВ УЧАСТКОВ — это ТОЧНО, а не приблизительно
------------------------------------------------------------------------------
Окупаемость книги есть ``DAYS_YEAR · (100·cost/capital) / gain_pp``
(``trim_shape._payback_days``), и на участке, где НАБОР НОГ постоянен:

* ``cost = Σ газ(нога) + оборот · (слippage + bridge)`` — АФФИННА по размеру
  хода (газ за ногу постоянен, остальное пропорционально обороту);
* ``gain_pp`` — АФФИННА по размеру: смешанная ставка линейна по позициям
  (``trim_shape._book_apy_pp``), а позиции на участке линейны по размеру.

Отношение двух аффинных функций МОНОТОННО на интервале, поэтому минимум
окупаемости на участке лежит на его КОНЦЕ. Значит, перебрав концы всех
участков, мы перебрали всех кандидатов на минимум — а не выборку из них.

Концы участков вычисляются ТОЧНО, а не угадываются. Жадная заливка
(``trim_optimum._fill``) даёт ноге ``i`` сумму ``clamp(бюджет − cum_i, 0,
room_i)``, где ``cum_i`` — сумма комнат предыдущих ног. Отсюда ровно два рода
порога у каждой ноги: она ПЕРЕСТАЁТ быть пылью при ``бюджет = cum_i +
min_leg_usd`` (дверь ``_legs``) и НАПОЛНЯЕТСЯ при ``бюджет = cum_i + room_i``.
Бюджет связан с размером хода аффинно (см. ``_size_of_budget``), поэтому пороги
переводятся в размеры без приближения.

**Шаг ``PROBE_DELTA_USD`` — ЦЕНТ, и это не произвол:** книга округляется до
цента (``_fill`` зовёт ``round(…, 2)``), поэтому меньшего различия в ней не
существует. Порог ноги проверяется строгим неравенством (``_legs`` отсекает
``abs(delta) <= min_leg_usd``), поэтому у каждого порога пробуются ОБЕ стороны:
на цент ниже (верх нижнего участка) и на цент выше (низ верхнего).

Положительный контроль самой этой структуры
------------------------------------------------------------------------------
Рассуждение выше — не повод верить коду. Поэтому перепись ВДОБАВОК гоняет
ГУСТУЮ СЕТКУ размеров по названной выборке записей и спрашивает, не побила ли
сетка перебор концов. Побила ⇒ это НАХОДКА (``grid_beats_breakpoints`` > 0), и
она печатается, а не прячется: значит, вывод о монотонности неверен либо
пороги выведены неправильно. Замер своей структуры сеткой — тот же приём, каким
ADR-859 проверял доминирование жадного (``search_worse`` обязан быть нулём).

**Доминирование здесь — инвариант построения.** Край отрезка входит в список
кандидатов, поэтому скан НЕ МОЖЕТ ответить хуже ADR-859: ``scan_worse`` обязан
быть нулём, и это проверяется на всём населении И отдельным тестом.

ЧТО ИЗМЕРЕНО (живая история, замер 2026-10-29)
------------------------------------------------------------------------------
Население — то же, что у ADR-854/855/859 по построению: **87 предложений /
55 дат** из 165 записей.

====================================================  ======================
край отрезка (ответ ADR-859), медиана                 75.13 дн.
скан отрезка, медиана                                 **74.30 дн.**
скан СТРОГО лучше края                                **8** из 87
скан ХУЖЕ края                                        **0** (инвариант)
в горизонт 30 дн.                                     22 → **22**
====================================================  ======================

**И ЦЕНУ ЭТУ НАДО ЧИТАТЬ ПО ОСИ ИСТОЧНИКА, А НЕ ПО МЕДИАНЕ.** Все **8 из 8**
улучшений созданы ПЫЛЬНЫМ ПОРОГОМ двери цены, а не экономикой: в книге скана
лежит дельта **$499.99** при пороге **$500** (см. ``dust_deltas``).
Экономических улучшений — **НОЛЬ**. То есть ПРИЧИНА 2 измерена, и её
экономическая цена на всём записанном населении равна нулю: край отрезка
оптимален везде, где цена считается честно.

Это ответ, а не умолчание, и он УЗКИЙ: он про записанное население и про
ДВЕРЬ КНИГИ, а не про живую дверь дня.

Побочная находка, вынесенная карточкой: расхождение внутри самой двери цены —
``_legs`` берёт с подпороговой дельты и газ, и оборот ПО КОММЕНТАРИЮ («dust:
pays full gas»), а по КОДУ не берёт ничего, тогда как её выигрыш ``_book_apy_pp``
считает полностью. Направление расхождения — ЗАВЫШЕНИЕ привлекательности хода.

Ось ПЛАТО: ловушка СВОЕГО ЖЕ замера
------------------------------------------------------------------------------
Первая редакция оси «та же окупаемость при меньшем размере» считалась по
ЗАПРОШЕННОМУ размеру и дала **36 записей из 87**. Число было про ПОТОЛОК, а не
про плато: размер выше суммы комнат ног даёт ТУ ЖЕ книгу (``_fill`` упирается
в комнаты), поэтому «меньший размер» там ничего не значит. По ФАКТИЧЕСКОМУ
обороту книги ось равна **НУЛЮ**. Ошибка поймана внутри цикла и закреплена
тестом ``ThePlateauAxisIsMeasuredOnTurnoverNotOnRequestedSize``.

Только stdlib. LLM запрещён — это замер, а не суждение. Прибор ЧИТАЕТ и ничего
не чинит: ни один порог не правится, ни одна цель дня не меняется, ни один
доллар не двигается. Допустимость спрашивается ТОЙ ЖЕ дверью КНИГИ
(``trim_admissibility.book_verdict`` → ``RiskPolicy.check_portfolio_health``),
своей копии ни одного порога у прибора нет.
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

_EPS = 1e-9

#: Шаг пробы по обе стороны порога участка. ЦЕНТ — квант самой книги
#: (``_fill`` округляет до двух знаков), меньшего различия в ней нет.
PROBE_DELTA_USD = 0.01

#: Потолок кандидатов НА ПОДМНОЖЕСТВО. Как и у соседа, стои́т ради ТРЕТЬЕГО
#: ИСХОДА, а не ради скорости: подмножество с большим числом порогов обязано
#: уйти в названный исход, а не получить молча урезанный перебор (инв. #17).
MAX_CANDIDATES_PER_SUBSET = 512

#: Сколько ПОСЛЕДНИХ записей населения проверяется густой сеткой. Выборка, а не
#: всё население — и поэтому она НАЗВАНА числом в самой переписи: контроль
#: структуры стои́т дорого (своя сетка на каждое подмножество).
GRID_CONTROL_RECORDS = 12

#: Точек густой сетки на подмножество в контроле структуры.
GRID_CONTROL_POINTS = 64

SZ_MEASURED = "measured"
SZ_UNMEASURED = "unmeasured"
SZ_NO_SUBJECT = "no_subject"
SZ_NO_ALTERNATIVE = "no_alternative"
SZ_TIER_UNKNOWN = "tier_unknown"
SZ_STANDING_INADMISSIBLE = "standing_inadmissible"
SZ_NONE_ADMISSIBLE = "none_admissible"
SZ_SEARCH_TRUNCATED = "search_truncated"

CENSUS_MEASURED = "measured"
CENSUS_MEASURED_ZERO = "measured_zero"
CENSUS_UNMEASURED = "unmeasured"


def _saturation_size(inc_sel: List[List], dec_sel: List[List],
                     net_cash_usd: float) -> float:
    """Размер хода, выше которого книга подмножества УЖЕ НЕ МЕНЯЕТСЯ.

    Выше него ``_fill`` упирается в комнаты ног, поэтому новые кандидаты там
    совпадают с этим и перебирать их незачем (но сам он — кандидат).
    """
    room_inc = sum(a for _, a in inc_sel)
    room_dec = sum(a for _, a in dec_sel)
    if net_cash_usd >= 0:
        return min(room_inc, room_dec + net_cash_usd)
    return min(room_dec, room_inc - net_cash_usd)


def _size_of_budget(budget: float, *, side: str, net_cash_usd: float) -> float:
    """Размер хода, при котором бюджет СТОРОНЫ равен ``budget``.

    Связь аффинна, пока ход не упёрся в комнаты (``_saturation_size``), и
    выводится прямо из ``_fill``: при ``net >= 0`` покупка равна ходу, а продажа
    — ходу минус чистое движение кэша; при ``net < 0`` наоборот.
    """
    if net_cash_usd >= 0:
        return budget if side == "buy" else budget + net_cash_usd
    return budget - net_cash_usd if side == "buy" else budget


def _side_budget_thresholds(side_rows: List[List],
                            min_leg_usd: float) -> List[float]:
    """Пороги бюджета СТОРОНЫ: где нога перестаёт быть пылью и где наполняется.

    Два рода порога и третьего нет — это прямое следствие формы жадной заливки
    ``clamp(бюджет − cum_i, 0, room_i)`` (см. докстринг модуля).
    """
    out: List[float] = []
    cum = 0.0
    for _proto, room in side_rows:
        room = float(room or 0.0)
        out.append(cum + min_leg_usd)   # порог двери `_legs`
        out.append(cum + room)          # нога наполнилась
        cum += room
    return out


def candidate_sizes(inc_sel: List[List], dec_sel: List[List], *,
                    edge: float, net_cash_usd: float,
                    min_leg_usd: float,
                    delta: float = PROBE_DELTA_USD,
                    max_candidates: int = MAX_CANDIDATES_PER_SUBSET
                    ) -> Tuple[Optional[List[float]], str]:
    """Размеры-кандидаты на минимум окупаемости внутри подмножества.

    Возврат ``(список, причина)``; ``None`` — кандидатов больше потолка, и это
    ТРЕТИЙ ИСХОД с названным числом, а не молча урезанный перебор.

    Край отрезка (``edge``) входит в список ВСЕГДА — на нём держится
    доминирование над ответом ADR-859.
    """
    ceiling = min(float(edge), _saturation_size(inc_sel, dec_sel, net_cash_usd))
    raw: List[float] = [float(edge)]
    if ceiling > _EPS:
        raw.append(ceiling)
    for side, rows in (("buy", inc_sel), ("sell", dec_sel)):
        for budget in _side_budget_thresholds(rows, min_leg_usd):
            at = _size_of_budget(budget, side=side, net_cash_usd=net_cash_usd)
            # ОБЕ стороны порога: дверь `_legs` отсекает ногу нестрогим
            # неравенством, поэтому сам порог принадлежит НИЖНЕМУ участку.
            raw.append(at - delta)
            raw.append(at + delta)
    seen: Dict[int, float] = {}
    for size in raw:
        if size <= _EPS or size > float(edge) + _EPS:
            continue
        seen[int(round(size * 100.0))] = min(float(size), float(edge))
    sizes = sorted(seen.values())
    if len(sizes) > max_candidates:
        return None, (f"кандидатов {len(sizes)} при потолке {max_candidates} — "
                      f"перебор концов участков НЕ полон, и урезанный выдавать "
                      f"за полный нельзя")
    return sizes, f"кандидатов {len(sizes)}"


def dust_deltas(current: Dict[str, float], book: Dict[str, float],
                min_leg_usd: float) -> Dict[str, float]:
    """Дельты книги НИЖЕ пыльного порога — те, что дверь цены НЕ ВИДИТ.

    Вопрос не косметический: он решает, ЧЕМ является найденный приз.
    ``rebalance_economics._legs`` выбрасывает дельту ``abs(delta) <=
    min_leg_usd`` ЦЕЛИКОМ — такая нога не попадает ни в газ, ни в оборот (то
    есть ни в проскальзывание, ни в мост). А ``trim_shape._book_apy_pp``
    считает ставку по КНИГЕ, где эта сумма ЛЕЖИТ, значит её выигрыш учтён
    полностью. Для оптимизатора это БЕСПЛАТНЫЙ выигрыш, и он к нему сползает:
    скан размера сам находит ``min_leg_usd − 0.01``.

    Комментарий в самой двери обещает обратное — «dust: pays full gas, moves
    nothing worth moving», то есть газ взять и выигрыша не дать. Код не берёт
    ни газа, ни оборота. Расхождение смотрит в сторону ЗАВЫШЕНИЯ
    привлекательности хода, поэтому молчать о нём нельзя.
    """
    out: Dict[str, float] = {}
    for proto in sorted(set(book or {}) | set(current or {})):
        delta = (float((book or {}).get(proto, 0.0) or 0.0)
                 - float((current or {}).get(proto, 0.0) or 0.0))
        # Полцента — квант книги; меньшего отличия в ней не существует.
        if 0.005 < abs(delta) <= float(min_leg_usd) + 1e-9:
            out[proto] = round(delta, 2)
    return out


def _grid_sizes(edge: float, points: int) -> List[float]:
    """Густая сетка размеров — КОНТРОЛЬ структуры, а не способ искать минимум."""
    if edge <= _EPS or points <= 0:
        return []
    step = float(edge) / float(points)
    return [round(step * (i + 1), 2) for i in range(points)]


def scan_subset(current: Dict[str, float],
                inc_sel: List[List], dec_sel: List[List], *,
                edge: float,
                net_cash_usd: float,
                apy_pct: Dict[str, float],
                capital_usd: float,
                min_leg_frac: float,
                tiers: Dict[str, str],
                chains: Dict[str, str],
                grid_points: int = 0) -> dict:
    """Лучшая книга подмножества по ВСЕМУ отрезку размеров, а не только на краю.

    Каждый кандидат судят ТЕ ЖЕ двери, что у цикла: допустимость —
    ``book_verdict``, цена и выигрыш — ``score_book``.
    """
    from spa_core.paper_trading.trim_optimum import _approved, _fill, score_book

    min_leg_usd = max(0.0, float(min_leg_frac)) * float(capital_usd)
    sizes, why = candidate_sizes(inc_sel, dec_sel, edge=edge,
                                 net_cash_usd=net_cash_usd,
                                 min_leg_usd=min_leg_usd)
    if sizes is None:
        return {"kind": SZ_SEARCH_TRUNCATED, "why": why}

    def _score_at(size: float) -> Optional[dict]:
        book = _fill(current, inc_sel, dec_sel, size, net_cash_usd)
        if book is None:
            return None
        if _approved(book, apy_pct, capital_usd,
                     tiers=tiers, chains=chains) is not True:
            return None
        scored = score_book(current, book, apy_pct, capital_usd=capital_usd,
                            min_leg_frac=min_leg_frac, chains=chains)
        if scored is None:
            return None
        return dict(scored, size_usd=round(float(size), 2))

    best: Optional[dict] = None
    at_edge: Optional[dict] = None
    for size in sizes:
        scored = _score_at(size)
        if scored is None:
            continue
        if abs(size - float(edge)) <= _EPS:
            at_edge = scored
        if best is None or scored["payback_days"] < best["payback_days"] - 1e-9:
            best = scored
    grid_best: Optional[dict] = None
    for size in _grid_sizes(edge, grid_points):
        scored = _score_at(size)
        if scored is None:
            continue
        if (grid_best is None
                or scored["payback_days"] < grid_best["payback_days"] - 1e-9):
            grid_best = scored
    return {"kind": SZ_MEASURED, "best": best, "at_edge": at_edge,
            "grid_best": grid_best, "candidates": len(sizes)}


def search_with_size_scan(current: Dict[str, float],
                          proposal: Dict[str, float],
                          apy_pct: Dict[str, float], *,
                          admissible_usd: float,
                          net_cash_usd: float,
                          capital_usd: float,
                          min_leg_frac: float,
                          tiers: Dict[str, str],
                          chains: Dict[str, str],
                          max_subsets: int = None,
                          grid_points: int = 0) -> dict:
    """ОДНА запись: ответ ADR-859 (только край) и ответ со СКАНОМ отрезка.

    Оба числа берутся из ОДНОГО перебора подмножеств — иначе сравнивались бы
    разные населения, и приз оказался бы артефактом разных прогонов, а не
    разницей вопросов (урок ADR-580 §C2 о сравнении внутри одного рода).
    """
    from spa_core.paper_trading.trim_optimum import (MAX_SUBSETS_PER_RECORD,
                                                     _fill,
                                                     _largest_admissible_turnover,
                                                     score_book)
    from spa_core.paper_trading.trim_shape import _sides

    if max_subsets is None:
        max_subsets = MAX_SUBSETS_PER_RECORD
    inc, dec = _sides(current or {}, proposal or {})
    inc.sort(key=lambda row: -float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    dec.sort(key=lambda row: float((apy_pct or {}).get(row[0], 0.0) or 0.0))
    total = (2 ** len(inc)) * (2 ** len(dec))
    if total > max_subsets:
        return {"kind": SZ_SEARCH_TRUNCATED,
                "why": (f"ног {len(inc)}+{len(dec)} ⇒ подмножеств {total} при "
                        f"потолке перебора {max_subsets} — перебор НЕ полон"),
                "subsets_total": total}
    best_edge: Optional[dict] = None
    best_scan: Optional[dict] = None
    grid_wins = 0
    truncated = 0
    tried = 0
    for n_i in range(len(inc) + 1):
        for pick_i in itertools.combinations(range(len(inc)), n_i):
            inc_sel = [inc[i] for i in pick_i]
            for n_d in range(len(dec) + 1):
                for pick_d in itertools.combinations(range(len(dec)), n_d):
                    dec_sel = [dec[i] for i in pick_d]
                    if not inc_sel and not dec_sel:
                        continue
                    tried += 1
                    edge = _largest_admissible_turnover(
                        current, inc_sel, dec_sel,
                        ceiling=admissible_usd, net=net_cash_usd,
                        apy_pct=apy_pct, capital_usd=capital_usd,
                        tiers=tiers, chains=chains)
                    if edge is None:
                        continue
                    book = _fill(current, inc_sel, dec_sel, edge, net_cash_usd)
                    if book is None:
                        continue
                    # Ответ ADR-859 на этом подмножестве — его и надо
                    # воспроизвести, а не пересказать: та же дверь, тот же край.
                    edge_scored = score_book(current, book, apy_pct,
                                             capital_usd=capital_usd,
                                             min_leg_frac=min_leg_frac,
                                             chains=chains)
                    if edge_scored is not None and (
                            best_edge is None
                            or edge_scored["payback_days"]
                            < best_edge["payback_days"] - 1e-9):
                        best_edge = dict(edge_scored,
                                         size_usd=round(float(edge), 2),
                                         subset_buy=tuple(p for p, _ in inc_sel),
                                         subset_sell=tuple(p for p, _ in dec_sel))
                    scan = scan_subset(current, inc_sel, dec_sel, edge=edge,
                                       net_cash_usd=net_cash_usd,
                                       apy_pct=apy_pct,
                                       capital_usd=capital_usd,
                                       min_leg_frac=min_leg_frac,
                                       tiers=tiers, chains=chains,
                                       grid_points=grid_points)
                    if str(scan.get("kind")) == SZ_SEARCH_TRUNCATED:
                        truncated += 1
                        continue
                    cand = scan.get("best")
                    grid = scan.get("grid_best")
                    if (cand is not None and grid is not None
                            and float(grid["payback_days"])
                            < float(cand["payback_days"]) - 1e-6):
                        grid_wins += 1
                    if cand is not None and (
                            best_scan is None
                            or cand["payback_days"]
                            < best_scan["payback_days"] - 1e-9):
                        best_scan = dict(cand,
                                         subset_buy=tuple(p for p, _ in inc_sel),
                                         subset_sell=tuple(p for p, _ in dec_sel))
    if best_scan is None and best_edge is None:
        return {"kind": SZ_NONE_ADMISSIBLE,
                "why": ("перебраны все подмножества ног — допустимой книги с "
                        "определённой окупаемостью не нашлось"),
                "subsets_tried": tried,
                "subsets_truncated": truncated}
    return {"kind": SZ_MEASURED,
            "edge_only": best_edge,
            "scanned": best_scan,
            "subsets_tried": tried,
            "subsets_truncated": truncated,
            "grid_beats_breakpoints": grid_wins,
            "claim": ("закрыта ПРИЧИНА 2 нижней границы ADR-859 (размер хода). "
                      "ПРИЧИНА 1 — раскладка внутри подмножества фиксирована "
                      "спредом — ОСТАЁТСЯ открытой: её снимает только настоящий "
                      "оптимум (ЛП), и он money-path")}


def compare_trim_size_edge(current: Dict[str, float],
                           proposal: Dict[str, float],
                           apy_pct: Dict[str, float], *,
                           capital_usd: float,
                           params,
                           tiers: Dict[str, str],
                           chains: Dict[str, str],
                           grid_points: int = 0) -> dict:
    """ОДНА запись истории: край против скана, одной дверью книги.

    Исходы повторяют соседа дословно по смыслу (``trim_optimum``), потому что
    это ТО ЖЕ население — условие сравнимости приза: иначе «скан лучше» могло
    бы означать «скан считался на других днях».
    """
    from spa_core.paper_trading.trim_optimum import _approved
    from spa_core.paper_trading.trim_shape import (SHAPE_MEASURED,
                                                   SHAPE_NO_ALTERNATIVE,
                                                   SHAPE_NO_SUBJECT,
                                                   shapes_of_proposal)

    shapes = shapes_of_proposal(current, proposal, apy_pct,
                                capital_usd=capital_usd, params=params)
    kind = str(shapes.get("kind"))
    if kind == SHAPE_NO_SUBJECT:
        return {"kind": SZ_NO_SUBJECT, "why": str(shapes.get("why") or "")}
    if kind == SHAPE_NO_ALTERNATIVE:
        return {"kind": SZ_NO_ALTERNATIVE, "why": str(shapes.get("why") or "")}
    if kind != SHAPE_MEASURED:
        return {"kind": SZ_UNMEASURED, "why": str(shapes.get("why") or "")}

    cur = shapes["current"]
    capital = float(shapes["capital_usd"])
    mlf = float(shapes["min_leg_frac"])
    admissible = float(shapes["admissible_usd"])
    net = float(shapes["net_cash_usd"])

    standing = _approved(cur, apy_pct, capital, tiers=tiers, chains=chains)
    if standing is None:
        return {"kind": SZ_TIER_UNKNOWN,
                "why": ("ярлык тира стоящей книги не прочитан — ни один потолок "
                        "не определён; второй тир НЕ подставляется (ADR-359)")}
    if standing is False:
        return {"kind": SZ_STANDING_INADMISSIBLE,
                "why": ("день уже стоял вне политики — отказ пришёл бы из "
                        "наследства, и приз размера на нём не измерим")}

    found = search_with_size_scan(
        cur, shapes["proposal"], apy_pct,
        admissible_usd=admissible, net_cash_usd=net, capital_usd=capital,
        min_leg_frac=mlf, tiers=tiers, chains=chains, grid_points=grid_points)
    if str(found.get("kind")) != SZ_MEASURED:
        return {"kind": str(found.get("kind")), "why": str(found.get("why") or ""),
                "admissible_usd": admissible, "net_cash_usd": net}
    edge_only = found.get("edge_only") or {}
    scanned = found.get("scanned") or {}
    return {
        "kind": SZ_MEASURED,
        "admissible_usd": admissible,
        "net_cash_usd": net,
        "payback": {
            "edge_only": (None if not edge_only
                          else float(edge_only["payback_days"])),
            "scanned": (None if not scanned
                        else float(scanned["payback_days"])),
        },
        "size_usd": {
            "edge_only": (None if not edge_only else edge_only.get("size_usd")),
            "scanned": (None if not scanned else scanned.get("size_usd")),
        },
        # ЗАПРОШЕННЫЙ размер и ФАКТИЧЕСКИЙ оборот — РАЗНЫЕ числа, и путать их
        # нельзя: размер выше суммы комнат ног даёт ТУ ЖЕ книгу (`_fill`
        # упирается в комнаты), поэтому «меньший размер при той же окупаемости»
        # на запрошенном размере означало бы лишь «потолок был выше комнаты».
        # Первая редакция оси ПЛАТО считала именно так и дала 36 записей из 87 —
        # число про потолок, а не про плато (поймано замером 29.10).
        "turnover_usd": {
            "edge_only": (None if not edge_only
                          else float(edge_only.get("turnover_usd") or 0.0)),
            "scanned": (None if not scanned
                        else float(scanned.get("turnover_usd") or 0.0)),
        },
        "legs": {"edge_only": (None if not edge_only else edge_only.get("legs")),
                 "scanned": (None if not scanned else scanned.get("legs"))},
        # ЧЕМ является приз — вопрос, отдельный от «есть ли приз», и без
        # него число читается как экономика. Подпороговая дельта в книге
        # скана означает, что часть выигрыша дверь цены отдала БЕСПЛАТНО.
        "prize_dust_deltas": (dust_deltas(cur, (scanned or {}).get("book") or {},
                                          mlf * capital)
                              if scanned else {}),
        "min_leg_usd": round(mlf * capital, 2),
        "grid_beats_breakpoints": int(found.get("grid_beats_breakpoints") or 0),
        "grid_points": int(grid_points),
        "subsets_tried": int(found.get("subsets_tried") or 0),
        "subsets_truncated": int(found.get("subsets_truncated") or 0),
        "claim": str(found.get("claim") or ""),
    }


def trim_size_edge_census(records: List[dict], *, params,
                          tiers: Dict[str, str],
                          tiers_measured: bool,
                          chains: Dict[str, str],
                          chains_measured: bool,
                          grid_control_records: int = GRID_CONTROL_RECORDS,
                          grid_points: int = GRID_CONTROL_POINTS) -> dict:
    """Цена ПРИЧИНЫ 2 нижней границы ADR-859 на всей записанной истории.

    Население — то же, что у ADR-854/855/859 по построению (любое записанное
    предложение выше потолка размера). Перепись только ЧИТАЕТ.
    """
    from spa_core.paper_trading.trim_shape import _median, _proposal_of

    if not isinstance(records, list):
        return {"kind": CENSUS_UNMEASURED,
                "why": "история не список — цена размера не измерена"}
    if not tiers_measured:
        return {"kind": CENSUS_UNMEASURED,
                "why": ("реестр адаптеров не прочитан — ярлыков тира нет, и ни "
                        "один потолок на книге не определён; второй тир НЕ "
                        "подставляется (ADR-359)")}
    parsed = [r for r in records if isinstance(r, dict)]
    # Контроль структуры — на ПОСЛЕДНИХ записях, и выборка НАЗВАНА числом.
    grid_from = max(0, len(parsed) - max(0, int(grid_control_records)))
    rows: List[dict] = []
    outcomes: Dict[str, int] = {}
    for idx, rec in enumerate(parsed):
        proposal, source = _proposal_of(rec)
        one = compare_trim_size_edge(
            rec.get("current_positions") or {},
            proposal,
            rec.get("apy_evidenced_pct") or {},
            capital_usd=rec.get("capital_usd") or 0.0,
            params=params, tiers=tiers, chains=chains,
            grid_points=(grid_points if idx >= grid_from else 0))
        kind = str(one.get("kind"))
        outcomes[kind] = outcomes.get(kind, 0) + 1
        if kind == SZ_MEASURED:
            one["date"] = rec.get("cycle_date")
            one["proposal_source"] = source
            rows.append(one)
    if not rows:
        return {"kind": (CENSUS_MEASURED_ZERO if outcomes else CENSUS_UNMEASURED),
                "outcomes": outcomes,
                "records": len(parsed),
                "why": ("сравнимых предложений в истории не нашлось — это ЗАМЕР "
                        "нуля" if outcomes else
                        "ни одной разобранной записи — цена размера не измерена")}

    horizon = float(getattr(params, "max_payback_days", 0.0) or 0.0)
    both = [r for r in rows
            if (r["payback"]["edge_only"] is not None
                and r["payback"]["scanned"] is not None)]

    def _edge(row: dict) -> float:
        return float(row["payback"]["edge_only"])

    def _scan(row: dict) -> float:
        return float(row["payback"]["scanned"])

    strictly_better = sum(1 for r in both if _scan(r) < _edge(r) - 1e-6)
    worse = sum(1 for r in both if _scan(r) > _edge(r) + 1e-6)
    gains = [_edge(r) - _scan(r) for r in both if _scan(r) < _edge(r) - 1e-6]
    # ПЛАТО окупаемости — ось, которой не было ни у одного соседа, и находка
    # замера: окупаемость ТА ЖЕ, а оборот СТРОГО МЕНЬШЕ. Цель дня этого
    # различия не видит вовсе (её мерка — только окупаемость), хотя меньший
    # оборот стоит дешевле по проскальзыванию и несёт меньше риска исполнения.
    # Числом это НЕ приз окупаемости, и смешивать их нельзя.
    def _to(row: dict, name: str) -> Optional[float]:
        v = (row.get("turnover_usd") or {}).get(name)
        return None if v is None else float(v)

    plateau = [r for r in both
               if abs(_scan(r) - _edge(r)) <= 1e-6
               and _to(r, "scanned") is not None
               and _to(r, "edge_only") is not None
               and _to(r, "scanned") < _to(r, "edge_only") - PROBE_DELTA_USD]
    plateau_cuts = [_to(r, "edge_only") - _to(r, "scanned") for r in plateau]
    # Источник приза: экономика или пыльный порог двери цены. Ось отдельная,
    # потому что вопросы разные — «есть ли немонотонность» и «чем создана».
    better = [r for r in both if _scan(r) < _edge(r) - 1e-6]
    from_dust = [r for r in better if (r.get("prize_dust_deltas") or {})]
    grid_wins = sum(int(r.get("grid_beats_breakpoints") or 0) for r in rows)
    grid_checked = sum(1 for r in rows if int(r.get("grid_points") or 0) > 0)
    return {
        "kind": CENSUS_MEASURED,
        "records": len(parsed),
        "outcomes": outcomes,
        "population": len(rows),
        "dates": len({r.get("date") for r in rows}),
        "horizon_days": horizon,
        "comparable": len(both),
        "median_edge_only": _median([_edge(r) for r in both]),
        "median_scanned": _median([_scan(r) for r in both]),
        "scan_strictly_better": strictly_better,
        "scan_worse": worse,
        "best_single_gain_days": (round(max(gains), 2) if gains else None),
        "prize_source": {
            "strictly_better": len(better),
            "from_dust_band": len(from_dust),
            "economic": len(better) - len(from_dust),
            "dust_sample": [{"date": r.get("date"),
                             "gain_days": round(_edge(r) - _scan(r), 2),
                             "min_leg_usd": r.get("min_leg_usd"),
                             "deltas": r.get("prize_dust_deltas")}
                            for r in from_dust[:4]],
            "note": ("`from_dust_band` — приз, созданный ПЫЛЬНЫМ ПОРОГОМ "
                     "двери цены, а не экономикой: `_legs` выбрасывает "
                     "подпороговую дельту и из газа, и из оборота, а "
                     "`_book_apy_pp` её выигрыш считает ⇒ дверь отдаёт её "
                     "БЕСПЛАТНО. `economic` — остаток, и ТОЛЬКО он есть "
                     "цена ПРИЧИНЫ 2"),
        },
        "plateau_same_payback_smaller_size": len(plateau),
        "plateau_median_size_cut_usd": (round(_median(plateau_cuts), 2)
                                        if plateau_cuts else None),
        "plateau_note": ("окупаемость ТА ЖЕ, ФАКТИЧЕСКИЙ оборот книги СТРОГО "
                         "МЕНЬШЕ. Это НЕ приз окупаемости и в её медиану не "
                         "входит: мерка цели дня различия не видит вовсе, хотя "
                         "меньший оборот дешевле по проскальзыванию. Считается "
                         "по обороту книги, НЕ по запрошенному размеру — выше "
                         "суммы комнат ног размер даёт ТУ ЖЕ книгу"),
        "within_horizon_edge_only": sum(1 for r in both
                                        if _edge(r) <= horizon + _EPS),
        "within_horizon_scanned": sum(1 for r in both
                                      if _scan(r) <= horizon + _EPS),
        "grid_control": {
            "records_checked": grid_checked,
            "points_per_subset": int(grid_points),
            "grid_beats_breakpoints": grid_wins,
            "note": ("КОНТРОЛЬ структуры, а не поиск: густая сетка обязана НЕ "
                     "побить перебор концов участков. Ненулевое число — "
                     "НАХОДКА (вывод о монотонности либо пороги неверны), и "
                     "она печатается"),
        },
        "subsets_tried": sum(int(r.get("subsets_tried") or 0) for r in rows),
        "subsets_truncated": sum(int(r.get("subsets_truncated") or 0)
                                 for r in rows),
        "last": rows[-1],
        "tiers_measured": bool(tiers_measured),
        "chains_measured": bool(chains_measured),
        "claim": ("ПРИЧИНА 2 нижней границы ADR-859 (размер хода) ИЗМЕРЕНА, и "
                  "её цену надо читать по оси ИСТОЧНИКА, а не по медиане: "
                  "немонотонность, созданная ПЫЛЬНЫМ ПОРОГОМ двери цены, не "
                  "есть экономический приз. ПРИЧИНА 1 (раскладка фиксирована "
                  "спредом) ОСТАЁТСЯ — её снимает только настоящий оптимум "
                  "(ЛП), money-path. `scan_worse` обязан быть НУЛЁМ: край "
                  "входит в кандидатов"),
        "note": ("вердикт спрошен у двери КНИГИ (`check_portfolio_health`, "
                 "ADR-134), НЕ у живой двери шага: снимка адаптеров дня история "
                 "не несёт. ADVISORY — ни один порог не правится, ни один "
                 "доллар не двигается"),
    }


def trim_size_edge_outcome(census: Optional[dict]) -> Tuple[str, str]:
    """Дверь чтения переписи — ОДНА на всех читателей (урок ADR-851)."""
    if not isinstance(census, dict) or not census:
        return CENSUS_UNMEASURED, ("блока цены размера в артефакте нет — запись "
                                   "СТАРШЕ прибора, а не его ноль (урок ADR-851)")
    kind = str(census.get("kind") or "")
    if kind == CENSUS_MEASURED:
        return CENSUS_MEASURED, (f"цена размера измерена на "
                                 f"{census.get('population')} предложени(и/ях)")
    if kind == CENSUS_MEASURED_ZERO:
        return CENSUS_MEASURED_ZERO, str(census.get("why")
                                         or "сравнимых предложений не нашлось")
    if kind == CENSUS_UNMEASURED:
        return CENSUS_UNMEASURED, str(census.get("why") or "причина не названа")
    return CENSUS_UNMEASURED, f"исход переписи размера не разобран ({kind!r})"


def format_trim_size_edge(census: Optional[dict]) -> List[str]:
    """Печать переписи цены размера — своя, а не строка внутри печати приза."""
    kind, why = trim_size_edge_outcome(census)
    head = ("цена ПРИЧИНЫ 2 нижней границы (ADR-861, ADVISORY — край отрезка "
            "против скана, дверь КНИГИ):")
    if kind != CENSUS_MEASURED:
        return [head, f"  [{kind}] {why}"]
    doc: dict = census if isinstance(census, dict) else {}
    g = doc.get("grid_control") or {}
    last = doc.get("last") or {}
    horizon = doc.get("horizon_days")
    lines = [
        head,
        f"  население {doc.get('population')} предложени(й) / "
        f"{doc.get('dates')} дат (записей просмотрено {doc.get('records')}); "
        f"исходы {doc.get('outcomes')}",
        f"  КРАЙ против СКАНА ({doc.get('comparable')}): медиана "
        f"{doc.get('median_edge_only')} → {doc.get('median_scanned')} дн.; "
        f"скан СТРОГО лучше на {doc.get('scan_strictly_better')}, ХУЖЕ на "
        f"{doc.get('scan_worse')} (ХУЖЕ обязан быть 0 — край входит в "
        f"кандидатов); лучший единичный приз "
        f"{doc.get('best_single_gain_days')} дн.",
        f"  ИСТОЧНИК приза: строго лучше "
        f"{(doc.get('prize_source') or {}).get('strictly_better')} — из них ПЫЛЬНЫЙ "
        f"ПОРОГ двери цены {(doc.get('prize_source') or {}).get('from_dust_band')}, "
        f"ЭКОНОМИКА {(doc.get('prize_source') or {}).get('economic')} (цена ПРИЧИНЫ 2 "
        f"— только второе число)",
        f"  в горизонт {horizon} дн. {doc.get('within_horizon_edge_only')} → "
        f"{doc.get('within_horizon_scanned')}; подмножеств перебрано "
        f"{doc.get('subsets_tried')}, усечено {doc.get('subsets_truncated')}",
        f"  КОНТРОЛЬ структуры: густая сетка на {g.get('records_checked')} "
        f"последних записях по {g.get('points_per_subset')} точек — побила "
        f"перебор концов {g.get('grid_beats_breakpoints')} раз(а) "
        f"(обязан быть 0)",
    ]
    if last:
        pb = last.get("payback") or {}
        sz = last.get("size_usd") or {}
        to = last.get("turnover_usd") or {}
        lines.append(
            f"  последняя запись {last.get('date')}: край "
            f"{pb.get('edge_only')} дн. (размер "
            f"${float(sz.get('edge_only') or 0.0):,.0f}, оборот "
            f"${float(to.get('edge_only') or 0.0):,.0f})"
            f" · скан {pb.get('scanned')} дн. (размер "
            f"${float(sz.get('scanned') or 0.0):,.0f}, оборот "
            f"${float(to.get('scanned') or 0.0):,.0f})")
    lines.insert(4, (
        f"  ПЛАТО окупаемости (та же окупаемость, ФАКТИЧЕСКИЙ оборот книги "
        f"СТРОГО меньше): "
        f"{doc.get('plateau_same_payback_smaller_size')} запис(ей), медиана "
        f"сокращения оборота "
        + (f"${float(doc['plateau_median_size_cut_usd']):,.2f}"
           if doc.get('plateau_median_size_cut_usd') is not None
           else "НЕ ОПРЕДЕЛЕНА (плато нет — ЗАМЕР нуля, не отсутствие числа)")
        + " — отдельная ось, в медиану окупаемости НЕ входит"))
    lines.append(f"  {doc.get('claim')}")
    lines.append(f"  {doc.get('note')}")
    return lines
