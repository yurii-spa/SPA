"""Transaction economics — §13 приказа владельца «Portfolio CIO» (полная цена хода).

Предмет — дословный текст ТЗ владельца из якорной карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §13 «Transaction economics. Для каждого rebalance: source · destination ·
    amount — рассчитать полную стоимость. Включить: withdraw gas · deposit gas ·
    claim gas · swap fee · protocol fee · slippage · market impact · bridge cost
    · future exit cost. Рассчитать: Gross Incremental Yield · Net Incremental
    Yield · Expected Incremental Profit · Break-even Time.»

Заказ G944 п. 1 требует начинать ЗАМЕРОМ того же вида, что §10 и §12: какие
слагаемые измеримы, какие слепы, и ГДЕ сегодня печатается литерал вместо
наблюдения. Этот модуль и есть тот замер.

ГЛАВНОЕ УСТРОЙСТВО: род слагаемого меряется ДИФФЕРЕНЦИАЛЬНО, на живой двери
=========================================================================
Вопрос «учитывается ли слагаемое» нельзя задать докстрингу: докстринг
`cost_model` перечисляет три трения и выглядит исчерпывающим, а владелец назвал
девять. Поэтому каждое слагаемое спрашивается у НАСТОЯЩЕЙ двери цены
(`spa_core.allocator.rebalance_economics._move_cost_usd` — та же, чьим вердиктом
живёт гейт `payback_within_horizon`): две сцены, различающиеся РОВНО
наступлением этого слагаемого, и ответом служит СДВИГ ЦЕНЫ, а не наличие слова
в коде.

Это тот же выбор, что у ADR-243 («разложение сошлось с `_move_cost_usd` до
девятого знака — это не пересчёт похожей формулой, а раскладка той самой») и у
ADR-913 («сторож сравнивал свои константы САМ С СОБОЙ, лечение — ПАРИТЕТ с
производителем»): прибор, носящий СВОЮ копию цены, отвечает о себе.

ПЯТЬ РОДОВ СЛАГАЕМОГО, и ни один не выдаётся за другой
======================================================
Замер различает пять исходов, потому что чинятся они РАЗНЫМ:

* `charged_named` — цена сдвинулась, и у слагаемого СВОЙ сумманд (slippage,
  bridge cost). Чинить нечего: оно есть;
* `charged_merged` — цена сдвинулась, но тем же числом, которым заряжено
  ДРУГОЕ слагаемое: дверь их не различает. Так устроены `withdraw gas` и
  `deposit gas` — нога несёт `direction`, и цена его ИГНОРИРУЕТ (замер ниже:
  сцена с перевёрнутым направлением стоит ровно столько же). Чинить — расщепить
  литерал по направлению;
* `not_charged` — наступление ВЫРАЗИМО входом двери, и цена на него не
  шевелится. Так устроен `claim gas`: сбор награды трогает позицию, НЕ меняя её
  размера, значит ноги не возникает вовсе и ход стоит ноль. Чинить — завести
  слагаемое;
* `no_input_door` — наступление НЕВЫРАЗИМО: у двери нет входа, которым о нём
  можно сказать (`swap fee`, `protocol fee` — ни актива, ни ставки сбора среди
  параметров нет). Это ОТДЕЛЬНЫЙ исход, а не разновидность предыдущего: там
  слагаемое игнорируется, здесь о нём нечем сообщить, и работы это требует
  разной. Доказательство печатается параметрами настоящей двери;
* `unmeasured` — сцена не состоялась (дверь не ввезена, вход не прочитан).
  Третий исход инв. #17: «не измерено» никогда не выдаётся за «не заряжено».

Слагаемое, заряженное ЛИТЕРАЛОМ, несёт `literal` — имя константы, её значение,
прочитанное из ЖИВОГО модуля, и дом объявления. Перепечатывать значение сюда
было бы ровно тем дефектом, против которого написано `.claude/rules/
site-numbers.md`: литерал в приборе разошёлся бы с литералом в цене молча.

ЧЕТЫРЕ ВЕЛИЧИНЫ §13 — ВТОРАЯ ОСЬ, и она о другом
=================================================
§13 просит не только слагаемые, но и четыре величины. Их род меряется тем же
способом — выходом настоящего `evaluate()`:

* Gross Incremental Yield — `gain_pp`, есть;
* Break-even Time — `payback_days`, есть;
* Net Incremental Yield — поля нет, и это НЕ придирка к имени: сцена
  `cost_does_not_enter_band` поднимает цену хода КРАТНО (дешёвая цепь против
  дорогой, обе берутся замером живого литерала), и `gain_pp` не меняется ни на
  знак, а полоса выгоды `gain_above_band` не сужается. Цена входит РОВНО в срок
  окупаемости — утверждение ADR-243, перемеренное здесь дифференциально.
  Кратность сюда не перепечатана намеренно: она ЗАМЕР с датой, печатает её сам
  прибор, и литерал в докстринге разошёлся бы с ним молча;
* Expected Incremental Profit — не вычисляется, и причина названа: формула
  владельца требует `Expected Holding Period`, а среди входов двери нет ни
  одного, обращённого ВПЕРЁД (`days_since_last_act`, `position_age_days`,
  `days_since_last_move` смотрят НАЗАД). Величину нельзя получить правкой
  формулы — не хватает наблюдения.

Чего прибор НЕ делает
=====================
`IS_ADVISORY = True`. Только ЧИТАЕТ и только СПРАШИВАЕТ: ни одна константа цены
не правлена, `_move_cost_usd` и `evaluate()` зовутся как ЧИСТЫЕ функции (их
чистота объявлена докстрингом `rebalance_economics` и ею же пользуется теневая
фаза ADR-060), RiskPolicy, стоп-кран, потолки концентрации, целевая функция
тюнера и живой трек не тронуты ни строкой. Капитал не двигается.

Требование §13 «рассчитать полную стоимость» ПРИБОРОМ НЕ ИСПОЛНЯЕТСЯ намеренно:
подставить девять слагаемых в гейт, решающий о движении денег, — предмет №1
границы ADR-285. Прибор называет, чего не хватает, и этим кончает свою работу.

stdlib-only · LLM FORBIDDEN.

Перемер руками::

    python3 -m spa_core.analytics.transaction_economics --data-dir <путь>/data

Коды возврата: 0 — перепись снята и хотя бы одно слагаемое заряжено ·
1 — находки (ни одно слагаемое не заряжено) · 2 — НЕ ИЗМЕРЕНО (дверь цены не
ввезена или вход не прочитан).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .apy_marginal import (
    AXIS_STATES,
    SOURCE_MAX_AGE_H,
    _load,
    _norm,
    _source_state,
    opportunity_names,
)

ENGINE = "transaction_economics_census"

#: Слой советательный: ни одно число отсюда не гейтит исполнение (инв. #9).
IS_ADVISORY = True

# ---------------------------------------------------------------------------
# ОБЪЯВЛЕННЫЕ константы. Каждая — выбор, и у каждой названа причина.
# ---------------------------------------------------------------------------

#: Рода слагаемого, от худшего к лучшему. Порядок ЗНАЧИМ: он решает, какой
#: исход печатается в сводке как итог. `unmeasured` стои́т НЕ в начале и не в
#: конце намеренно — «не измерено» не лучше и не хуже «не заряжено», это
#: ОТДЕЛЬНЫЙ исход (инв. #17), и сравнивать его по той же шкале нельзя.
CHARGE_KINDS: Tuple[str, ...] = (
    "no_input_door",    # наступление НЕВЫРАЗИМО: входа у двери нет вовсе
    "not_charged",      # выразимо и ИГНОРИРУЕТСЯ: цена не шевельнулась
    "charged_merged",   # заряжено ТЕМ ЖЕ числом, что и соседнее слагаемое
    "charged_named",    # у слагаемого СВОЙ сумманд
)

#: Исход, который по шкале выше не судится.
UNMEASURED = "unmeasured"

#: Сцена замера. Книга и суммы объявлены здесь, а не взяты из живого трека:
#: предмет замера — ПОВЕДЕНИЕ ЦЕНЫ, и оно обязано быть воспроизводимым на любой
#: машине в любой день. Живой трек сюда не входит ни одним числом (запрет
#: `CLAUDE.md`: `data/equity_curve_daily.json` не трогать).
SCENE_CAPITAL_USD = 100_000.0
SCENE_FROM_USD = 50_000.0
SCENE_MOVE_USD = 10_000.0
SCENE_MIN_LEG_FRAC = 0.01

#: Цепи сцены. `ethereum` и `mainnet` — РАЗНЫЕ строки с ОДИНАКОВЫМ литералом
#: газа (12.0), и это единственный способ спросить о мосте, НЕ шевельнув газ:
#: взять две дешёвые цепи значило бы измерить сумму двух сдвигов и приписать её
#: мосту. Пара выбрана ЗАМЕРОМ литералов, а не на глаз (:func:`_equal_gas_pair`).
SCENE_CHAIN = "ethereum"

#: Допуск сравнения двух цен. Цена округляется до цента у потребителя
#: (`evaluate`), поэтому сравнивать её на равенство float'ов нельзя.
COST_EPS = 1e-6


#: ПРЕДМЕТ наблюдения у слагаемого бывает ДВУХ родов, и спутать их — значит
#: выдумать находку. Сосед §12 (`apy_marginal`) привязывает запись к НАШИМ
#: ВОЗМОЖНОСТЯМ, потому что ставка есть свойство пула; у §13 так устроены не все
#: слагаемые: газ есть свойство ЦЕПИ, и писатель газа честно называет предметом
#: `ethereum`/`base`. Первая редакция этого прибора привязывала всё к
#: протоколам и объявила живое наблюдение газа `fixture_subject` — то есть
#: НАШЛА ДЕФЕКТ, которого нет. Поэтому род предмета ОБЪЯВЛЕН у каждого
#: слагаемого, а не угадывается.
SUBJECT_KINDS: Tuple[str, ...] = ("protocol", "chain")


def _term(key: str, owner_words: str, probe: str, sources: Sequence[str] = (),
          consumer: Optional[str] = None, why: str = "",
          subject_kind: str = "protocol") -> Dict[str, Any]:
    return {"term": key, "owner_words": owner_words, "probe": probe,
            "sources": tuple(sources), "consumer": consumer, "why": why,
            "subject_kind": subject_kind}


#: ДЕВЯТЬ слагаемых §13 — дословный перечень владельца, в его порядке.
#:
#: `probe` — имя сцены, которой слагаемое спрашивается у живой двери (см.
#: :func:`probe_terms`); `sources` — файлы `data/`, которые НЕСЛИ БЫ наблюдение
#: этого слагаемого (пустой кортеж = такого файла нет вовсе); `consumer` — имя
#: места, которое наблюдение читает, `None` = не читает никто (урок
#: `no_consumer` ADR-954: иначе в день наполнения файла перепись потеплела бы
#: БЕЗ новой информации).
TERMS: Tuple[Dict[str, Any], ...] = (
    _term(
        "withdraw_gas", "withdraw gas", "direction_flip",
        ("gas_price_history.json",),
        "rebalance_economics._move_cost_usd (газ за ногу)",
        why="нога несёт `direction`, и цена его ИГНОРИРУЕТ: сцена с "
            "перевёрнутым направлением стоит ровно столько же. Вывод и ввод "
            "заряжены ОДНИМ литералом на ногу",
        subject_kind="chain",
    ),
    _term(
        "deposit_gas", "deposit gas", "direction_flip",
        ("gas_price_history.json",),
        "rebalance_economics._move_cost_usd (газ за ногу)",
        why="тот же литерал, что у вывода — см. `withdraw_gas`",
        subject_kind="chain",
    ),
    _term(
        "claim_gas", "claim gas", "claim_without_size_change",
        ("gas_cost_breakeven_log.json",),
        None,
        why="сбор награды трогает позицию, НЕ меняя её размера ⇒ ноги не "
            "возникает, и ход стоит ноль. Слагаемого нет",
    ),
    _term(
        "swap_fee", "swap fee", "no_asset_input",
        ("aggregator_fee_log.json",),
        None,
        why="сбор пула-обменника зависит от ПАРЫ активов и тарифа, а среди "
            "входов двери нет ни актива, ни тарифа: сказать о наступлении "
            "нечем. Проскальзывание — ДРУГОЕ слагаемое, и владелец назвал оба",
    ),
    _term(
        "protocol_fee", "protocol fee", "no_fee_input",
        ("fee_structure_log.json", "vault_entry_exit_fee_amortization_log.json"),
        None,
        why="сборы входа/выхода и доля с прибыли объявляются ПРОТОКОЛОМ; среди "
            "входов двери ставки сбора нет",
    ),
    _term(
        "slippage", "slippage", "turnover_scale",
        ("slippage_impact_log.json",),
        "rebalance_economics._move_cost_usd (bps оборота)",
        why="заряжено своим суммандом: bps оборота",
    ),
    _term(
        "market_impact", "market impact", "turnover_convexity",
        (),
        None,
        why="влияние размера на цену выхода ВЫПУКЛО по обороту, а зависимость "
            "цены от оборота измерена СТРОГО линейной (двойной оборот даёт "
            "ровно двойную часть): выпуклого члена нет. Сосед §12 мерит "
            "влияние нашего размера на СТАВКУ, а не на цену ХОДА — это разные "
            "предметы, и подставлять один вместо другого нельзя",
    ),
    _term(
        "bridge_cost", "bridge cost", "second_chain",
        ("bridge_risk_log.json",),
        "rebalance_economics._move_cost_usd (bps оборота при >1 цепи)",
        why="заряжено своим суммандом при более чем одной задетой цепи",
    ),
    _term(
        "future_exit_cost", "future exit cost", "round_trip",
        (),
        None,
        why="§14 того же ТЗ («не оценивать A→B только по стоимости входа в B»): "
            "цена считается ЗА ОДИН ход, и будущий выход в неё не входит. "
            "Входа, обращённого вперёд, у двери нет",
    ),
)

#: ЧЕТЫРЕ величины §13 — дословно, в порядке владельца. `field` — поле выхода
#: настоящего `evaluate()`, несущее величину; `None` = не несёт ни одно.
QUANTITIES: Tuple[Dict[str, Any], ...] = (
    {"quantity": "gross_incremental_yield", "owner_words": "Gross Incremental Yield",
     "field": "gain_pp",
     "why": "валовая выгода хода в процентных пунктах книги"},
    {"quantity": "net_incremental_yield", "owner_words": "Net Incremental Yield",
     "field": None,
     "why": "поля нет, и это не придирка к имени: замер `cost_does_not_enter_band` "
            "показывает, что при росте цены выгода не меняется ни на знак и полоса "
            "не сужается — цена входит РОВНО в срок окупаемости"},
    {"quantity": "expected_incremental_profit", "owner_words": "Expected Incremental Profit",
     "field": None,
     "why": "формула владельца требует `Expected Holding Period`, а среди входов "
            "двери нет ни одного, обращённого ВПЕРЁД: правкой формулы величину не "
            "получить, не хватает наблюдения"},
    {"quantity": "break_even_time", "owner_words": "Break-even Time",
     "field": "payback_days",
     "why": "срок окупаемости цены выгодой; ЕДИНСТВЕННОЕ место, которым цена "
            "сегодня влияет на вердикт"},
)


def validate() -> List[str]:
    """Объявление обязано выдерживать СВОЙ контракт (урок ADR-943).

    Сторож, мерящий сам себя своей же меркой, не мерит ничего: перечень родов и
    перечень полей здесь — та же мерка, которой прибор судит дверь.
    """
    broken: List[str] = []
    if len(TERMS) != 9:
        broken.append(f"§13 называет ДЕВЯТЬ слагаемых, объявлено {len(TERMS)}")
    if len(QUANTITIES) != 4:
        broken.append(f"§13 называет ЧЕТЫРЕ величины, объявлено {len(QUANTITIES)}")
    seen = set()
    for t in TERMS:
        if t["term"] in seen:
            broken.append(f"слагаемое объявлено дважды: {t['term']}")
        seen.add(t["term"])
        for need in ("owner_words", "probe", "why"):
            if not str(t.get(need) or "").strip():
                broken.append(f"{t['term']}: поле {need} пусто")
    for q in QUANTITIES:
        if not str(q.get("why") or "").strip():
            broken.append(f"{q['quantity']}: причина не названа")
    if UNMEASURED in CHARGE_KINDS:
        broken.append("`unmeasured` не судится шкалой родов и не может в ней стоять")
    return broken


# ---------------------------------------------------------------------------
# Живая дверь цены. Ввозится ОДИН раз и НАЗЫВАЕТСЯ: прибор, носящий свою копию
# цены, отвечает о себе (ADR-913).
# ---------------------------------------------------------------------------

def load_cost_door() -> Tuple[Optional[Dict[str, Any]], str]:
    """(дверь, причина-отказа). Отсутствие двери — НЕ ИЗМЕРЕНО, а не ноль."""
    try:
        from spa_core.allocator import rebalance_economics as re_mod
        from spa_core.backtesting.tier1 import cost_model as cm
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return None, (f"дверь цены не ввезена ({type(exc).__name__}: {exc}) — "
                      "перепись НЕ ИЗМЕРЕНА")
    for need in ("_move_cost_usd", "_legs", "evaluate"):
        if not hasattr(re_mod, need):
            return None, (f"у двери цены нет `{need}` — форма изменилась, и "
                          "перепись НЕ ИЗМЕРЕНА, а не пуста")
    return {"module": re_mod, "cost_model": cm,
            "move_cost": re_mod._move_cost_usd, "legs": re_mod._legs,
            "evaluate": re_mod.evaluate}, ""


def _equal_gas_pair(cost_model: Any) -> Optional[Tuple[str, str]]:
    """Две РАЗНЫЕ цепи с ОДИНАКОВЫМ литералом газа — для вопроса о мосте.

    Пара ИЩЕТСЯ в живом литерале, а не объявляется здесь: назови её константой,
    и смена литерала газа превратила бы вопрос о мосте в замер суммы двух
    сдвигов МОЛЧА. Пары нет ⇒ третий исход, а не «мост не заряжен».
    """
    table = getattr(cost_model, "GAS_USD_PER_POSITION_CHANGE", None)
    if not isinstance(table, dict):
        return None
    by_value: Dict[float, List[str]] = {}
    for chain, usd in table.items():
        try:
            by_value.setdefault(float(usd), []).append(str(chain))
        except BaseException:  # noqa: BLE001
            continue
    for chains in (c for _usd, c in sorted(by_value.items(), key=lambda kv: -kv[0])):
        if len(chains) >= 2:
            return tuple(sorted(chains)[:2])  # type: ignore[return-value]
    return None


def our_chain_names(adapters: Dict[str, Any], door: Dict[str, Any]) -> set:
    """Имена НАШИХ цепей — предмет наблюдения у газа и у моста.

    Берутся из ДВУХ мест и объединяются: `chain` наших возможностей (о каких
    цепях мы вообще говорим) и ключи заряженного литерала (по каким цепям цена
    умеет заряжать). Взять одно место значило бы объявить `fixture_subject`
    цепь, которая честно называется у соседа: писатель газа пишет `ethereum`,
    литерал знает ещё и `mainnet`, а реестр — `polygon`, по которой живого
    отсчёта нет. Ни одно из трёх расхождений дефектом не является.
    """
    names: set = set()
    for a in (adapters or {}).values():
        if isinstance(a, dict):
            n = _norm(a.get("chain"))
            if n:
                names.add(n)
    table = getattr(door.get("cost_model"), "GAS_USD_PER_POSITION_CHANGE", None)
    if isinstance(table, dict):
        for chain in table:
            n = _norm(chain)
            if n:
                names.add(n)
    return names


def _scene_legs(door: Dict[str, Any]) -> Tuple[List[dict], float]:
    """Опорная сцена: один ход `SCENE_MOVE_USD` из A в B, ноги считает ДВЕРЬ."""
    return door["legs"](
        {"A": SCENE_FROM_USD, "B": 0.0},
        {"A": SCENE_FROM_USD - SCENE_MOVE_USD, "B": SCENE_MOVE_USD},
        SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)


def probe_terms(door: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Род КАЖДОГО слагаемого, снятый на живой двери. Девять ответов.

    Каждая сцена различается РОВНО наступлением своего слагаемого; ответом
    служит сдвиг цены, а не наличие слова в коде.
    """
    move_cost = door["move_cost"]
    legs, turnover = _scene_legs(door)
    one_chain = {"A": SCENE_CHAIN, "B": SCENE_CHAIN}
    base = float(move_cost(legs, turnover, one_chain))
    gas_only = float(move_cost(legs, 0.0, one_chain))

    out: Dict[str, Dict[str, Any]] = {}

    def say(terms: Sequence[str], kind: str, evidence: str) -> None:
        for t in terms:
            out[t] = {"kind": kind, "evidence": evidence}

    # ── withdraw gas / deposit gas: ЧИСТЫЙ ВЫВОД против ЧИСТОГО ВВОДА ───────
    # Нога уже несёт `direction`. Сцены берутся АСИММЕТРИЧНЫЕ: одна нога, и в
    # одной сцене она только выводит, в другой только вводит.
    #
    # Симметричный переворот обеих ног (первая редакция этого замера) предметом
    # НЕ является и был пойман своим же положительным контролем: он сохраняет
    # ЧИСЛО выводящих ног, поэтому дверь, заряжающая вывод дороже ввода, стоила
    # бы на нём РОВНО столько же — замер ответил бы «направление не читается»
    # о двери, которая его читает. Оборот у пары ниже совпадает по построению
    # (`max(increases, decreases)` от одной ноги), цепь и число ног — тоже,
    # значит единственное различие сцен есть НАПРАВЛЕНИЕ.
    out_legs, out_turnover = door["legs"](
        {"A": SCENE_MOVE_USD}, {"A": 0.0}, SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)
    in_legs, in_turnover = door["legs"](
        {"A": 0.0}, {"A": SCENE_MOVE_USD}, SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)
    withdraw_cost = float(move_cost(out_legs, out_turnover, one_chain))
    deposit_cost = float(move_cost(in_legs, in_turnover, one_chain))
    comparable = (len(out_legs) == len(in_legs) == 1
                  and abs(out_turnover - in_turnover) <= COST_EPS)
    if not comparable:
        say(("withdraw_gas", "deposit_gas"), UNMEASURED,
            f"сцены вывода и ввода не сравнимы: ног {len(out_legs)} против "
            f"{len(in_legs)}, оборот ${out_turnover:.2f} против "
            f"${in_turnover:.2f} — различие было бы не только в направлении")
    elif abs(withdraw_cost - deposit_cost) > COST_EPS:
        say(("withdraw_gas", "deposit_gas"), "charged_named",
            f"чистый вывод стои́т ${withdraw_cost:.4f}, чистый ввод "
            f"${deposit_cost:.4f} при одной ноге и равном обороте ⇒ цена читает "
            "направление, и у слагаемых свои числа")
    elif gas_only > COST_EPS:
        say(("withdraw_gas", "deposit_gas"), "charged_merged",
            f"газ заряжен (${gas_only:.4f} за {len(legs)} ног(и) при нулевом "
            f"обороте), а направление ноги цену не меняет: чистый вывод и "
            f"чистый ввод стоят одинаково ${withdraw_cost:.4f} ⇒ вывод и ввод "
            "заряжены ОДНИМ литералом на ногу и дверью не различаются")
    else:
        say(("withdraw_gas", "deposit_gas"), "not_charged",
            f"при нулевом обороте ход стоит ${gas_only:.4f} ⇒ газ не заряжен вовсе")

    # ── claim gas: сбор награды НЕ МЕНЯЕТ размера позиции ───────────────────
    claim_legs, claim_turnover = door["legs"](
        {"A": SCENE_FROM_USD}, {"A": SCENE_FROM_USD},
        SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)
    claim_cost = float(move_cost(claim_legs, claim_turnover, one_chain))
    if abs(claim_cost) > COST_EPS:
        say(("claim_gas",), "charged_named",
            f"сбор без смены размера стоит ${claim_cost:.4f}")
    else:
        say(("claim_gas",), "not_charged",
            f"сбор награды трогает позицию, НЕ меняя её размера ⇒ ног "
            f"{len(claim_legs)}, оборот ${claim_turnover:.2f}, цена "
            f"${claim_cost:.4f}: слагаемого нет")

    # ── slippage: масштаб по ОБОРОТУ ───────────────────────────────────────
    double = float(move_cost(legs, 2.0 * turnover, one_chain))
    if double - base > COST_EPS:
        say(("slippage",), "charged_named",
            f"двойной оборот дорожает ход с ${base:.4f} до ${double:.4f} ⇒ у "
            "слагаемого свой сумманд, пропорциональный обороту")
    else:
        say(("slippage",), "not_charged",
            f"двойной оборот цену не меняет: ${double:.4f} == ${base:.4f}")

    # ── market impact: ВЫПУКЛОСТЬ по обороту ───────────────────────────────
    # Влияние размера на цену выхода выпукло. Часть цены, зависящая от оборота,
    # измеряется вычитанием газа; строго двойная часть при двойном обороте и
    # есть доказательство, что выпуклого члена НЕТ.
    part_1 = base - gas_only
    part_2 = double - gas_only
    if part_1 <= COST_EPS:
        say(("market_impact",), UNMEASURED,
            "часть цены, зависящая от оборота, равна нулю — выпуклость мерить нечем")
    else:
        ratio = part_2 / part_1
        if ratio > 2.0 + 1e-6:
            say(("market_impact",), "charged_named",
                f"двойной оборот даёт {ratio:.6f}× зависящей от оборота части "
                "(больше двух) ⇒ выпуклый член есть")
        else:
            say(("market_impact",), "not_charged",
                f"двойной оборот даёт РОВНО {ratio:.6f}× зависящей от оборота "
                f"части (${part_1:.4f} → ${part_2:.4f}) ⇒ зависимость строго "
                "линейна, выпуклого члена нет")

    # ── bridge cost: ВТОРАЯ ЦЕПЬ при НЕШЕВЕЛЬНУВШЕМСЯ газе ─────────────────
    pair = _equal_gas_pair(door["cost_model"])
    if not pair:
        say(("bridge_cost",), UNMEASURED,
            "в литерале газа нет двух РАЗНЫХ цепей с одинаковой ценой ноги — "
            "спросить о мосте, не шевельнув газ, нечем")
    else:
        same = {"A": pair[0], "B": pair[0]}
        cross = {"A": pair[0], "B": pair[1]}
        c_same = float(move_cost(legs, turnover, same))
        c_cross = float(move_cost(legs, turnover, cross))
        if abs(c_cross - c_same) > COST_EPS:
            say(("bridge_cost",), "charged_named",
                f"вторая цепь ({pair[0]} → {pair[1]}, литерал газа у обеих "
                f"одинаков) дорожает ход с ${c_same:.4f} до ${c_cross:.4f} ⇒ у "
                "слагаемого свой сумманд")
        else:
            say(("bridge_cost",), "not_charged",
                f"вторая цепь цену не меняет: ${c_cross:.4f} == ${c_same:.4f}")

    # ── swap fee / protocol fee / future exit cost: НЕВЫРАЗИМО ─────────────
    # Доказательство — параметры НАСТОЯЩЕЙ двери, а не наше утверждение.
    import inspect
    cost_params = [p for p in inspect.signature(move_cost).parameters]
    eval_params = [p for p in inspect.signature(door["evaluate"]).parameters]
    leg_fields = sorted({k for l in legs for k in l})
    say(("swap_fee",), "no_input_door",
        f"сбор обменника зависит от ПАРЫ активов и тарифа; входы цены "
        f"{cost_params}, поля ноги {leg_fields} — ни актива, ни тарифа среди "
        "них нет, сказать о наступлении нечем")
    say(("protocol_fee",), "no_input_door",
        f"ставку сбора объявляет ПРОТОКОЛ; входы цены {cost_params}, поля ноги "
        f"{leg_fields} — ставки сбора среди них нет")
    forward = [p for p in eval_params if p.startswith("expected") or "horizon" in p
               or "holding" in p]
    say(("future_exit_cost",), "no_input_door",
        f"цена считается ЗА ОДИН ход; входов, обращённых ВПЕРЁД, у решения нет "
        f"(из {len(eval_params)} параметров подходящих {len(forward)}: "
        f"{forward or 'ни одного'}) — будущий выход выразить нечем")

    return out


def literal_sites(door: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ГДЕ сегодня печатается литерал вместо наблюдения.

    Значения читаются из ЖИВОГО модуля. Перепечатать их сюда значило бы завести
    второе место для числа, и расхождение с заряженным литералом стало бы
    невидимым (`.claude/rules/site-numbers.md`).
    """
    cm = door["cost_model"]
    out: List[Dict[str, Any]] = []
    for name, terms in (("GAS_USD_PER_POSITION_CHANGE", ("withdraw_gas", "deposit_gas")),
                        ("SLIPPAGE_BPS_STABLE", ("slippage",)),
                        ("BRIDGE_BPS", ("bridge_cost",))):
        if not hasattr(cm, name):
            out.append({"constant": name, "terms": list(terms),
                        "state": UNMEASURED,
                        "detail": "константы в живом модуле нет — литерал не прочитан"})
            continue
        value = getattr(cm, name)
        out.append({"constant": name, "terms": list(terms),
                    "home": f"{cm.__name__}.{name}",
                    "value": value if not isinstance(value, dict) else dict(value),
                    "state": "literal"})
    return out


def _declared_number(node: Any, key: str) -> Tuple[Optional[float], str]:
    """Число, объявленное ЛИБО значением, ЛИБО записью `{key: …, source: …}`.

    Писатель газа несёт цену ETH записью `{"source": "live", "usd": 2225.76}`, а
    не числом, и первая редакция этого читателя потребовала числа — то есть
    ответила `unmeasured` о наблюдении, которое ЕСТЬ. Это ровно тот дефект, про
    который инв. #17: «не измерено» обязано быть ПРАВДОЙ, а не следствием того,
    что читатель не знает объявленной формы. Поэтому разбираются обе формы, и
    род наблюдения (`source`) спрашивается ОТДЕЛЬНЫМ вопросом: число, снятое не
    живьём, наблюдением не является.
    """
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return float(node), "declared_bare"
    if isinstance(node, dict):
        val = node.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            src = str(node.get("source") or "").lower()
            if src and src != "live":
                return None, f"source={src!r} — снято не живьём"
            return float(val), "live" if src == "live" else "declared_record"
        return None, f"в записи нет числового `{key}` ({node.get(key)!r})"
    return None, f"ни число, ни запись ({type(node).__name__})"


def observed_gas_usd_per_leg(data_dir: Path) -> Dict[str, Any]:
    """Наблюдённый газ за ногу — в ТОЙ ЖЕ единице, которой заряжает цена.

    Метод ADR-243, перемеренный здесь: `gas_limit_per_leg` × gwei × цена ETH.
    Три исхода различимы (инв. #17): наблюдено · наблюдения нет · не прочитано.

    Текущее показание берётся из `chains` (там писатель держит ЖИВОЙ отсчёт с
    кворумом), а не из хвоста `history`: в ряду рядом с живыми отсчётами лежат
    `unchecked`, и взять последний не глядя значило бы выдать непроверенный
    отсчёт за наблюдение.
    """
    rec: Dict[str, Any] = {"source": "gas_price_history.json"}
    doc, why = _load(data_dir / "gas_price_history.json")
    if why or not isinstance(doc, dict):
        rec.update(state=UNMEASURED, detail=why or "запись не является отображением")
        return rec
    limit, why_limit = _declared_number(doc.get("gas_limit_per_leg"), "gas_limit")
    eth_usd, why_eth = _declared_number(doc.get("eth_usd"), "usd")
    chains = doc.get("chains")
    if not isinstance(chains, dict) or not chains:
        rec.update(state="empty",
                   detail="перечня цепей в записи нет — прочитанная пустота "
                          "наблюдением не является")
        return rec
    if limit is None or eth_usd is None:
        rec.update(state=UNMEASURED,
                   detail=f"для перевода в доллары нужны и `gas_limit_per_leg` "
                          f"({why_limit}), и `eth_usd` ({why_eth})")
        return rec
    per_chain: Dict[str, Any] = {}
    for chain, node in chains.items():
        if not isinstance(node, dict):
            continue
        gwei = node.get("gwei")
        src = str(node.get("source") or "").lower()
        if not isinstance(gwei, (int, float)) or isinstance(gwei, bool):
            per_chain[str(chain)] = {"state": "no_live_sample",
                                     "detail": f"отсчёта газа нет ({gwei!r})"}
            continue
        if src != "live":
            per_chain[str(chain)] = {"state": "no_live_sample",
                                     "detail": f"отсчёт есть, но source={src!r}"}
            continue
        usd = float(gwei) * 1e-9 * float(limit) * float(eth_usd)
        per_chain[str(chain)] = {"state": "observed", "gwei": gwei,
                                 "usd_per_leg": round(usd, 6),
                                 "sources_ok": node.get("sources_ok")}
    rec.update(state="observed" if any(v.get("state") == "observed"
                                       for v in per_chain.values()) else "no_live_sample",
               gas_limit_per_leg=limit, eth_usd=eth_usd,
               generated_at=doc.get("generated_at"), per_chain=per_chain)
    return rec


def charged_vs_observed(door: Dict[str, Any], observed: Dict[str, Any]) -> Dict[str, Any]:
    """Заряженный газ против наблюдённого — по цепям, у которых есть ОБА числа.

    Это перемер ADR-243 (расхождение ×311 на 06.09) тем же методом, но у
    СЛАГАЕМЫХ §13: сверять нечего, если одна из сторон не наблюдена, и такой
    случай называется, а не считается нулём.
    """
    out: Dict[str, Any] = {"pairs": [], "state": UNMEASURED}
    table = getattr(door["cost_model"], "GAS_USD_PER_POSITION_CHANGE", None)
    if not isinstance(table, dict):
        out["detail"] = "литерала газа в живом модуле нет"
        return out
    per_chain = observed.get("per_chain")
    if observed.get("state") != "observed" or not isinstance(per_chain, dict):
        out["detail"] = (f"наблюдения газа нет ({observed.get('state')}): "
                         "сверять заряженное не с чем")
        return out
    worst: Optional[float] = None
    for chain, obs in sorted(per_chain.items()):
        if obs.get("state") != "observed":
            continue
        key = str(chain).lower()
        if key not in table:
            out["pairs"].append({"chain": chain, "state": "not_in_literal",
                                 "observed_usd_per_leg": obs["usd_per_leg"]})
            continue
        charged = float(table[key])
        obs_usd = float(obs["usd_per_leg"])
        ratio = (charged / obs_usd) if obs_usd > 0 else None
        out["pairs"].append({"chain": chain, "state": "compared",
                             "charged_usd_per_leg": charged,
                             "observed_usd_per_leg": round(obs_usd, 6),
                             "ratio_charged_over_observed":
                                 None if ratio is None else round(ratio, 2)})
        if ratio is not None:
            worst = ratio if worst is None else max(worst, ratio)
    compared = [p for p in out["pairs"] if p["state"] == "compared"]
    if compared:
        out["state"] = "compared"
        out["chains_compared"] = len(compared)
        out["worst_ratio_charged_over_observed"] = None if worst is None else round(worst, 2)
    else:
        out["detail"] = "ни по одной цепи нет ОБОИХ чисел"
    return out


def probe_quantities(door: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Род КАЖДОЙ из четырёх величин §13, снятый на выходе живого `evaluate()`.

    Вторая сцена отличается РОВНО ценой хода (дорогая цепь против дешёвой), и
    она отвечает на вопрос, который нельзя задать перечню полей: ВЛИЯЕТ ли цена
    на выгоду или только на срок окупаемости.
    """
    ev = door["evaluate"]
    table = getattr(door["cost_model"], "GAS_USD_PER_POSITION_CHANGE", None) or {}

    def scene(chain: str) -> Any:
        return ev(current_positions={"A": SCENE_FROM_USD, "B": 0.0},
                  target_positions={"A": SCENE_FROM_USD - SCENE_MOVE_USD,
                                    "B": SCENE_MOVE_USD},
                  apy_pct={"A": 3.0, "B": 9.0}, evidenced={"A", "B"},
                  chains={"A": chain, "B": chain},
                  capital_usd=SCENE_CAPITAL_USD)

    # Дешёвая и дорогая цепь берутся ЗАМЕРОМ литерала, не по памяти.
    priced = sorted(((float(v), str(k)) for k, v in table.items()
                     if isinstance(v, (int, float))))
    cheap = priced[0][1] if priced else SCENE_CHAIN
    dear = priced[-1][1] if priced else SCENE_CHAIN

    d_cheap, d_dear = scene(cheap), scene(dear)
    fields = {f for f in vars(d_dear)} if hasattr(d_dear, "__dict__") else set()

    cost_ratio = (float(d_dear.cost_usd) / float(d_cheap.cost_usd)
                  if float(d_cheap.cost_usd) > 0 else None)
    gain_moved = abs(float(d_dear.gain_pp) - float(d_cheap.gain_pp)) > COST_EPS
    band_moved = (d_dear.gates.get("gain_above_band")
                  != d_cheap.gates.get("gain_above_band"))

    out: List[Dict[str, Any]] = []
    for q in QUANTITIES:
        rec = {"quantity": q["quantity"], "owner_words": q["owner_words"],
               "declared_field": q["field"], "why": q["why"]}
        field = q["field"]
        if field is None:
            rec["state"] = "not_computed"
        elif field in fields:
            rec["state"] = "computed"
            rec["value_in_scene"] = getattr(d_cheap, field, None)
        else:
            rec["state"] = UNMEASURED
            rec["detail"] = (f"объявленного поля `{field}` в выходе решения нет — "
                             "форма изменилась")
        out.append(rec)

    scene_rec = {
        "cheap_chain": cheap, "dear_chain": dear,
        "cost_usd_cheap": d_cheap.cost_usd, "cost_usd_dear": d_dear.cost_usd,
        "cost_ratio": None if cost_ratio is None else round(cost_ratio, 2),
        "gain_pp_cheap": d_cheap.gain_pp, "gain_pp_dear": d_dear.gain_pp,
        "gain_moved_with_cost": gain_moved,
        "band_moved_with_cost": band_moved,
        "payback_days_cheap": d_cheap.payback_days,
        "payback_days_dear": d_dear.payback_days,
    }
    scene_rec["reading"] = (
        "цена выросла ×{:.2f}, а выгода {} и полоса {} ⇒ цена входит РОВНО в "
        "срок окупаемости".format(
            cost_ratio or 0.0,
            "сдвинулась" if gain_moved else "не сдвинулась ни на знак",
            "сузилась" if band_moved else "не сузилась")
        if not gain_moved and not band_moved else
        "цена влияет и на выгоду — утверждение ADR-243 перемерить")
    return [{"quantities": out, "cost_does_not_enter_band": scene_rec}]


def terms_state(data_dir: Path, adapters: Dict[str, Any],
                door: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Состояние каждого из девяти слагаемых: род заряда + род наблюдения.

    `now` — ВХОД, а не стенные часы (`.claude/rules/deployment.md` § «Время в
    тестах»): иначе проверка свежести наблюдения стала бы будильником.
    """
    now = now or datetime.now(timezone.utc)
    names = {"protocol": opportunity_names(adapters),
             "chain": our_chain_names(adapters, door)}
    probes = probe_terms(door)
    out: List[Dict[str, Any]] = []
    for t in TERMS:
        probe = probes.get(t["term"]) or {"kind": UNMEASURED,
                                          "evidence": "сцена не состоялась"}
        rec: Dict[str, Any] = {
            "term": t["term"], "owner_words": t["owner_words"],
            "charge_kind": probe["kind"], "charge_evidence": probe["evidence"],
            "why": t["why"], "probe": t["probe"],
        }
        rec["subject_kind"] = t["subject_kind"]
        ours = names.get(t["subject_kind"]) or set()
        if not t["sources"]:
            rec["observation"] = {"state": "no_source",
                                  "detail": "файла, который нёс БЫ наблюдение "
                                            "этого слагаемого, в data/ нет вовсе"}
        elif not ours:
            rec["observation"] = {
                "state": UNMEASURED,
                "detail": f"имён рода `{t['subject_kind']}` не прочитано ни "
                          "одного — привязать запись не к чему, и это НЕ "
                          "«предмет выдуман»"}
        else:
            states = [_source_state(data_dir, s, ours, t["consumer"], now)
                      for s in t["sources"]]
            best = max(states, key=lambda s: AXIS_STATES.index(s["state"])
                       if s["state"] in AXIS_STATES else -1)
            rec["observation"] = best
            if len(states) > 1:
                rec["observation_all"] = states
        out.append(rec)
    return out


def measure(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Секция цикла: перепись девяти слагаемых и четырёх величин §13."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    rep: Dict[str, Any] = {
        "status": "OK",
        "engine": ENGINE,
        "is_advisory": IS_ADVISORY,
        "question": ("§13: «для каждого rebalance рассчитать ПОЛНУЮ стоимость» — "
                     "какие из девяти слагаемых заряжены сегодня и где вместо "
                     "наблюдения печатается литерал"),
        "declared": {
            "terms_declared": len(TERMS),
            "quantities_declared": len(QUANTITIES),
            "charge_kinds": list(CHARGE_KINDS),
            "source_max_age_h": SOURCE_MAX_AGE_H,
            "scene": {"capital_usd": SCENE_CAPITAL_USD,
                      "move_usd": SCENE_MOVE_USD,
                      "min_leg_frac": SCENE_MIN_LEG_FRAC},
        },
    }

    broken = validate()
    if broken:
        rep.update(status="SKIPPED", verdict="UNMEASURED",
                   unmeasured=["объявление не выдерживает своего контракта: "
                               + "; ".join(broken)])
        rep["reason"] = rep["unmeasured"][0]
        return rep

    door, why_door = load_cost_door()
    if door is None:
        rep.update(status="SKIPPED", verdict="UNMEASURED", unmeasured=[why_door])
        rep["reason"] = why_door
        return rep
    rep["declared"]["cost_door"] = (
        f"{door['module'].__name__}._move_cost_usd (та же, чьим вердиктом живёт "
        "гейт payback_within_horizon)")

    status_doc, why_status = _load(data_dir / "adapter_status.json")
    adapters = (status_doc or {}).get("adapters") if isinstance(status_doc, dict) else None
    if not isinstance(adapters, dict) or not adapters:
        # Род ЗАРЯДА измерим и без входа — он свойство двери, не данных. Поэтому
        # перепись продолжается, а слепота наблюдений НАЗЫВАЕТСЯ, а не молчит.
        rep["unmeasured"] = [
            why_status or "в adapter_status.json нет перечня `adapters` — "
                          "привязать наблюдение к нашим возможностям нечем"]
        adapters = {}

    terms = terms_state(data_dir, adapters, door, now=now)
    rep["terms"] = terms
    rep["literals"] = literal_sites(door)
    observed = observed_gas_usd_per_leg(data_dir)
    rep["observed_gas"] = observed
    rep["charged_vs_observed"] = charged_vs_observed(door, observed)
    quantities = probe_quantities(door)[0]
    rep["quantities"] = quantities["quantities"]
    rep["cost_does_not_enter_band"] = quantities["cost_does_not_enter_band"]

    by_kind: Dict[str, List[str]] = {}
    for t in terms:
        by_kind.setdefault(t["charge_kind"], []).append(t["term"])
    charged = [t for t in terms if t["charge_kind"] in ("charged_named", "charged_merged")]
    credited_obs = [t for t in terms
                    if (t.get("observation") or {}).get("state") == "credited"]
    rep["counts"] = {
        "terms_declared": len(TERMS),
        "charged_named": len(by_kind.get("charged_named", [])),
        "charged_merged": len(by_kind.get("charged_merged", [])),
        "not_charged": len(by_kind.get("not_charged", [])),
        "no_input_door": len(by_kind.get("no_input_door", [])),
        "charge_unmeasured": len(by_kind.get(UNMEASURED, [])),
        "terms_charged_total": len(charged),
        "observation_credited": len(credited_obs),
        "quantities_computed": len([q for q in rep["quantities"]
                                    if q["state"] == "computed"]),
        "quantities_not_computed": len([q for q in rep["quantities"]
                                        if q["state"] == "not_computed"]),
    }
    rep["by_kind"] = by_kind

    findings: List[str] = []
    if by_kind.get("charged_merged"):
        findings.append(
            "слагаемых, заряженных ОДНИМ числом и дверью не различаемых: "
            + ", ".join(by_kind["charged_merged"]))
    if by_kind.get("not_charged"):
        findings.append("слагаемых ВЫРАЗИМЫХ и не заряженных: "
                        + ", ".join(by_kind["not_charged"]))
    if by_kind.get("no_input_door"):
        findings.append("слагаемых, о которых двери нечем сказать: "
                        + ", ".join(by_kind["no_input_door"]))
    nc = [q["quantity"] for q in rep["quantities"] if q["state"] == "not_computed"]
    if nc:
        findings.append("величин §13 не вычисляется: " + ", ".join(nc))
    cvo = rep["charged_vs_observed"]
    if cvo.get("state") == "compared" and (cvo.get("worst_ratio_charged_over_observed") or 0) > 1.0:
        findings.append(
            "газ заряжен литералом выше наблюдённого в "
            f"{cvo['worst_ratio_charged_over_observed']} раз(а) по "
            f"{cvo['chains_compared']} цеп(и/ям)")
    rep["findings"] = findings
    rep["verdict"] = "FINDINGS" if findings else "OK"
    if not charged:
        rep["status"] = "CRITICAL"
    elif findings:
        rep["status"] = "WARN"
    return rep


def _print(rep: Dict[str, Any]) -> int:
    c = rep.get("counts") or {}
    print(f"§13 Transaction economics — перепись слагаемых цены хода "
          f"(двигатель {rep['engine']}, слой {'ADVISORY' if rep['is_advisory'] else '?'})")
    if rep.get("status") == "SKIPPED":
        print(f"  НЕ ИЗМЕРЕНО: {rep.get('reason')}")
        return 2
    for u in rep.get("unmeasured") or []:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    print(f"  слагаемых объявлено {c.get('terms_declared')} · "
          f"свой сумманд {c.get('charged_named')} · "
          f"заряжено ЧУЖИМ числом {c.get('charged_merged')} · "
          f"выразимо и НЕ заряжено {c.get('not_charged')} · "
          f"сказать нечем {c.get('no_input_door')} · "
          f"не измерено {c.get('charge_unmeasured')}")
    for t in rep.get("terms") or []:
        obs = (t.get("observation") or {}).get("state")
        print(f"    · {t['owner_words']:<18} {t['charge_kind']:<15} "
              f"наблюдение: {obs}")
        print(f"        {t['charge_evidence']}")
    print(f"  величин объявлено {len(rep.get('quantities') or [])} · "
          f"вычисляется {c.get('quantities_computed')} · "
          f"НЕ вычисляется {c.get('quantities_not_computed')}")
    for q in rep.get("quantities") or []:
        print(f"    · {q['owner_words']:<28} {q['state']:<14} "
              f"{q.get('declared_field') or '—'}")
    band = rep.get("cost_does_not_enter_band") or {}
    if band:
        print(f"  сцена цены: {band.get('cheap_chain')} ${band.get('cost_usd_cheap')} → "
              f"{band.get('dear_chain')} ${band.get('cost_usd_dear')} "
              f"(×{band.get('cost_ratio')})")
        print(f"        {band.get('reading')}")
    cvo = rep.get("charged_vs_observed") or {}
    if cvo.get("state") == "compared":
        print(f"  заряжено против наблюдённого: цепей {cvo.get('chains_compared')}, "
              f"худшее отношение ×{cvo.get('worst_ratio_charged_over_observed')}")
        for p in cvo.get("pairs") or []:
            if p.get("state") == "compared":
                print(f"    · {p['chain']}: заряжено ${p['charged_usd_per_leg']} "
                      f"против наблюдённых ${p['observed_usd_per_leg']} "
                      f"(×{p['ratio_charged_over_observed']})")
    else:
        print(f"  заряжено против наблюдённого: НЕ ИЗМЕРЕНО — {cvo.get('detail')}")
    for f in rep.get("findings") or []:
        print(f"  [НАХОДКА] {f}")
    return 0 if c.get("terms_charged_total") else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or ENGINE).splitlines()[0])
    ap.add_argument("--data-dir", default="data",
                    help="каталог состояния (живой трек — у ПРОД-дерева)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    rep = measure(Path(ns.data_dir))
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        if rep.get("status") == "SKIPPED":
            return 2
        return 0 if (rep.get("counts") or {}).get("terms_charged_total") else 1
    return _print(rep)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
