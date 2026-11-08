"""Round trip — §14 приказа владельца «Portfolio CIO» (круг, а не вход).

Предмет — дословный текст ТЗ владельца из якорной карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §14 «Учитывать round trip. Ошибка: A → B не должна оцениваться только по
    стоимости входа в B. Нужно оценивать: A exit + B entry + eventual B exit.
    Если высока вероятность скорой новой ребалансировки, это должно снижать
    привлекательность операции.»

Заказ G945 п. 1 требует начинать ЗАМЕРОМ, а не формулой: чем сегодня можно
оценить вероятность СКОРОЙ НОВОЙ перекладки (все нынешние ограничители частоты
смотрят НАЗАД) и есть ли в `data/` наблюдение срока удержания. Этот модуль и
есть тот замер — прямое продолжение §13 (:mod:`transaction_economics`), чей
род `future_exit_cost` вышел `no_input_door`.

ПАРИТЕТ, А НЕ СВОЯ КОПИЯ
========================
Словарь родов (`CHARGE_KINDS`), загрузчик двери (`load_cost_door`) и сцена
(`SCENE_*`) ввезены из :mod:`transaction_economics`, а не перепечатаны. Прибор,
носящий свою копию мерки, отвечает о себе — урок ADR-913 («сторож сравнивал
свои константы САМ С СОБОЙ») и ADR-937 («объявление обязано нести СВОЙ
контракт»). Расширение словаря у соседа автоматически расширяет и этот замер.

ПЯТЬ ОСЕЙ, и каждая несёт СВОЙ бит
==================================
1. **ТРИ СЛАГАЕМЫХ §14.** `A exit`, `B entry`, `eventual B exit` — род каждого
   снят ДИФФЕРЕНЦИАЛЬНО на живой двери цены
   (`rebalance_economics._move_cost_usd`, та же, чьим вердиктом живёт гейт
   `payback_within_horizon`), а не прочитан у докстринга. Два первых есть, и
   они `charged_merged`: нога несёт `direction`, цена его ИГНОРИРУЕТ (замер
   ADR-956, здесь перемеренный своей сценой). Третий — `no_input_door`: у двери
   нет входа, которым можно сказать «из B когда-нибудь придётся выйти».

2. **НЕДОПЛАТА КРУГА — ВИЛКА, а не одно отношение.** Отсутствие третьего
   слагаемого стои́т денег, и это ЧИСЛО; но «сколько именно» зависит от того,
   ЧЕМ окажется будущий выход, и выдумывать его назначение нельзя. Поэтому
   печатается вилка из двух зовов той же двери:

   * **нижняя граница** — дословные ТРИ ноги §14 (`A exit` + `B entry` +
     `eventual B exit` как ОДНА нога из B): владелец назвал три ноги, и это
     ровно то, что он просит зарядить;
   * **верхняя граница** — будущий выход сам окажется перекладкой (две ноги),
     то есть полный обратный ход B→A.

   Первая редакция этой оси печатала ТОЛЬКО верхнюю границу и называла её
   «недоплатой круга» — то есть приписывала §14 требование, которого в нём нет
   (обратный ход возвращает деньги в A, а §14 просит лишь выход из B). Ошибка
   нашлась своим же замером и исправлена вилкой. Литералов здесь нет намеренно:
   обе границы есть ЗАМЕР с датой (`.claude/rules/site-numbers.md`).

3. **ЧЕМ СКАЗАТЬ О ВЕРОЯТНОСТИ СКОРОЙ ПЕРЕКЛАДКИ.** Перечень входов берётся у
   ЖИВОЙ подписи `evaluate()` (`inspect.signature`), а направление каждого
   временного входа меряется у его ПРОИЗВОДИТЕЛЯ двумя сценами, различающимися
   РОВНО знаком времени: журнал в прошлом против журнала в будущем. Вход, чьё
   значение при будущих записях становится отрицательным, есть ВОЗРАСТ, то есть
   обращён НАЗАД. Ответ §14 — число входов рода `forward_looking`.

   **Род `forward_looking` ДОСТИЖИМ, и без этого ноль ничего не значил бы.**
   Первая редакция оси присваивала `observed_past` ЛЮБОМУ заполненному входу —
   то есть отвечала «обращённых вперёд ноль» на любом дереве и не мерила
   ничего (ложное усиление, урок ADR-940). Ошибка нашлась своим же замером.
   Теперь род решает СРАВНЕНИЕ СЦЕН: значение, отличающееся от сцены с ПУСТЫМ
   журналом хоть в одной из записанных сцен, производно от записанного
   прошлого; значение, одинаковое во всех, прошлым не объясняется. Положительный
   контроль — производитель-пустышка, отдающий одно и то же число (тест
   `a_producer_not_derived_from_the_recorded_past_IS_SEEN`).

   **Это ВЕРХНЯЯ граница, и сказано вслух:** литерал («срок удержания 30 дней»)
   попал бы в тот же род, потому что записанным прошлым он тоже не объясняется.
   Утверждение от этого становится СИЛЬНЕЕ, а не слабее: даже считая литералы
   обращёнными вперёд, таких входов сегодня НОЛЬ.

   **Производителей ДВА, и одного не хватало.** Первая редакция спрашивала
   только `allocation_rationale._history_from_trades` и объявляла
   `position_age_days` родом `not_temporal` — то есть УТВЕРЖДАЛА про возраст
   позиции, что он не про время. Это выдуманное свойство: вход заполняет
   ДРУГОЙ производитель того же модуля (`_position_ages`), и он тоже обращён
   назад. Ошибка нашлась своим же замером; теперь спрашиваются оба, а исход
   «этот производитель входа не заполняет» носит имя `other_producer` и НЕ
   выдаёт себя за ответ о времени.

4. **ТРЕТИЙ ИСХОД У ВХОДА РАЗВОРОТА** (инв. #17). Планка разворота
   (`reversal_escalation`) поднимается, только если возраст прошлого хода
   ИЗМЕРЕН и попал в окно. Сцены: внутри окна · вне окна · НЕ ИЗМЕРЕНО. Если
   вердикт «не измерено» совпал с «вне окна» — сомнение разрешено В ПОЛЬЗУ
   СДЕЛКИ, и это `fail_open`. Рядом меряется СОСЕД `turnover_today_usd`, у
   которого тот же `None` ОТКАЗЫВАЕТ (ADR-357) — две двери одной функции, и
   сравнение их есть предмет оси, а не украшение.

5. **НАБЛЮДЕНИЕ СРОКА УДЕРЖАНИЯ В `data/`.** §13 просит
   `Expected Holding Period`, §14 — вероятность скорой перекладки; оба требуют
   наблюдения, которого у двери нет. Ось спрашивает журнал ходов
   (`data/trades.json`): выводи́тся ли срок удержания из него ВООБЩЕ, сколько
   удержаний завершено, и ЧТО ограничивает качество вывода.

   **Ось НЕ публикует «ожидаемый срок удержания» одним числом, и это решение, а
   не недоделка.** Такое число вошло бы в формулу, решающую о движении денег
   (предмет №1 границы ADR-285), а сам журнал несёт ИЗМЕРЕННЫЕ разрывы
   (`scripts/book_second_record.py`: дыра `T008`, переименование `T034`) и
   удержания длиной в секунды — след двух ходов, записанных подряд. Печатается
   перепись с названными оговорками; среднее по ней было бы выдумкой с видом
   наблюдения.

Чего прибор НЕ делает
=====================
`IS_ADVISORY = True`. Только ЧИТАЕТ и только СПРАШИВАЕТ: ни одна константа цены
не правлена, `_move_cost_usd` и `evaluate()` зовутся как ЧИСТЫЕ функции,
RiskPolicy, стоп-кран, потолки концентрации, целевая функция тюнера и живой трек
`data/equity_curve_daily.json` не тронуты ни строкой. Капитал не двигается.

Требование §14 «учитывать round trip» ПРИБОРОМ НЕ ИСПОЛНЯЕТСЯ намеренно:
завести третье слагаемое — значит зарядить в гейт число, которого никто не
наблюдал (ровно дефект ADR-243 на новом месте, и заказ G945 п. 3 это
запрещает). Прибор называет, чего не хватает, и этим кончает свою работу.

Перемер руками::

    python3 -m spa_core.analytics.round_trip_economics --data-dir <путь>/data

Коды возврата: 0 — находок нет · 1 — находки · 2 — НЕ ИЗМЕРЕНО.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .apy_marginal import _load
from .transaction_economics import (
    CHARGE_KINDS,
    COST_EPS,
    SCENE_CAPITAL_USD,
    SCENE_FROM_USD,
    SCENE_MIN_LEG_FRAC,
    SCENE_MOVE_USD,
    UNMEASURED,
    load_cost_door,
)

ENGINE = "round_trip_economics_census"

#: Слой советательный: ни одно число отсюда не гейтит исполнение (инв. #9).
IS_ADVISORY = True

#: Цепь сцены. ОДНА на оба конца хода намеренно: мост — слагаемое §13, и
#: шевельнуть его здесь значило бы приписать кругу цену, которой у круга нет.
SCENE_CHAIN = "ethereum"

#: Направление временного входа. `forward_looking` — то, чего §14 требует и чего
#: может не быть ни у одного входа; `not_temporal` — вход, к которому вопрос о
#: направлении не применим вовсе (книга, ставки, цепи), и смешать его с
#: «назад» значило бы раздуть знаменатель ответа.
INPUT_DIRECTIONS: Tuple[str, ...] = (
    "no_producer",       # производитель его не заполняет НИКОГДА
    "observed_past",     # значение производно от ЗАПИСАННЫХ ходов: обращено НАЗАД
    "forward_looking",   # значение НЕ производно от записанного прошлого
                         # (ВЕРХНЯЯ граница: литерал попал бы в этот же род)
    "other_producer",    # НИ ОДИН спрошенный производитель его не заполняет
    "not_temporal",      # вопрос о направлении к входу не применим (книга, ставки, цепи)
    UNMEASURED,          # сцена не состоялась
)

#: Исход «третьего состояния» у входа: как дверь трактует `None`.
DOUBT_STATES: Tuple[str, ...] = (
    "fail_open",      # «не измерено» совпало с благоприятным для сделки исходом
    "fail_closed",    # «не измерено» ОТКАЗЫВАЕТ
    "no_effect",      # вход вердикт не меняет ни одним значением
    UNMEASURED,
)

#: Удержание короче этого срока — не удержание, а след ДВУХ ходов, записанных
#: подряд одним циклом (замер живого журнала: 19 «удержаний» по 0.001 дн. внутри
#: одной минуты 2026-06-20). Порог ОБЪЯВЛЕН и печатается рядом с ответом: тихо
#: отфильтровать такие записи значило бы спрятать свойство ПИСАТЕЛЯ журнала.
MIN_REAL_HOLD_DAYS = 1.0 / 24.0


def _term(key: str, owner_words: str, why: str) -> Dict[str, Any]:
    return {"term": key, "owner_words": owner_words, "why": why}


#: ТРИ слагаемых §14 — дословный перечень владельца, в его порядке.
TERMS: Tuple[Dict[str, Any], ...] = (
    _term("a_exit", "A exit",
          "нога, уменьшающая позицию A: выход из источника"),
    _term("b_entry", "B entry",
          "нога, увеличивающая позицию B: вход в назначение"),
    _term("eventual_b_exit", "eventual B exit",
          "выход из B, который когда-нибудь придётся заплатить; у двери цены нет "
          "входа, которым о нём можно сказать"),
)

#: Входы живой двери, у которых `None` мерится ОТДЕЛЬНО (ось 4). Контроль
#: (`turnover_today_usd`) объявлен здесь же: сравнивать находку надо с
#: ИЗВЕСТНЫМ членом того же класса, иначе признак построен из формулировки
#: заказа и контроля не проходил ни разу.
DOUBT_INPUTS: Tuple[Dict[str, Any], ...] = (
    {"input": "days_since_last_move", "role": "subject",
     "why": "возраст прошлого хода — единственный вход, через который о скорой "
            "повторной перекладке сегодня можно сказать хоть что-то"},
    {"input": "turnover_today_usd", "role": "control",
     "why": "сосед той же функции, у которого `None` ОТКАЗЫВАЕТ намеренно "
            "(ADR-357) — известный член класса fail_closed"},
)


def validate() -> List[str]:
    """Объявление против своего контракта. Пустой список — контракт держится.

    Сторож мерит сам себя: перечень родов, перечень слагаемых и перечень входов
    — это и есть мерка, которой прибор мерит дверь, и разойдись она с кодом,
    прибор ответил бы о себе (урок ADR-937).
    """
    broken: List[str] = []
    if UNMEASURED in CHARGE_KINDS:
        broken.append("`unmeasured` попал в шкалу родов — он ОТДЕЛЬНЫЙ исход (инв. #17)")
    if len(set(INPUT_DIRECTIONS)) != len(INPUT_DIRECTIONS):
        broken.append("перечень направлений входа содержит повтор")
    for needed in ("forward_looking", "observed_past", "other_producer"):
        if needed not in INPUT_DIRECTIONS:
            broken.append(f"в перечне направлений нет `{needed}` — "
                          "ответ §14 выразить нечем либо исход выдаст себя за другой")
    if len(set(DOUBT_STATES)) != len(DOUBT_STATES):
        broken.append("перечень исходов сомнения содержит повтор")
    for needed in ("fail_open", "fail_closed"):
        if needed not in DOUBT_STATES:
            broken.append(f"в перечне исходов сомнения нет `{needed}`")
    terms = [t["term"] for t in TERMS]
    if len(set(terms)) != len(terms):
        broken.append("слагаемое §14 объявлено дважды")
    if len(terms) != 3:
        broken.append(f"слагаемых §14 объявлено {len(terms)}, владелец назвал три")
    roles = {d["role"] for d in DOUBT_INPUTS}
    if roles != {"subject", "control"}:
        broken.append("у оси сомнения обязаны быть И предмет, И контроль: "
                      f"объявлено {sorted(roles)}")
    if MIN_REAL_HOLD_DAYS <= 0:
        broken.append("порог настоящего удержания не положителен — фильтр обессмыслен")
    return broken


# ---------------------------------------------------------------------------
# Ось 1–2: три слагаемых §14 и недоплата круга
# ---------------------------------------------------------------------------

def _book_a_to_b() -> Tuple[Dict[str, float], Dict[str, float]]:
    """Сцена: ход `SCENE_MOVE_USD` из A в B. Книга объявлена, не взята у трека."""
    cur = {"A": SCENE_FROM_USD, "B": 0.0}
    tgt = {"A": SCENE_FROM_USD - SCENE_MOVE_USD, "B": SCENE_MOVE_USD}
    return cur, tgt


def probe_round_trip(door: Dict[str, Any]) -> Dict[str, Any]:
    """Оси 1 и 2 на живой двери: род трёх слагаемых + ВИЛКА недоплаты круга.

    Третье слагаемое доказывается ДВУМЯ наблюдениями, а не одним: (а) у двери
    цены нет входа, которым можно сказать о будущем выходе — печатается её
    настоящая подпись; (б) выход из B стои́т НЕНУЛЕВЫХ денег, и в цену прямого
    хода они не входят — печатается вилка. Одного (а) не хватило бы: «входа
    нет» совместимо и с «слагаемое равно нулю».
    """
    move_cost, legs_fn = door["move_cost"], door["legs"]
    cur, tgt = _book_a_to_b()
    chains = {"A": SCENE_CHAIN, "B": SCENE_CHAIN}

    legs, turnover = legs_fn(cur, tgt, SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)
    priced = float(move_cost(legs, turnover, chains))

    by_direction: Dict[str, List[dict]] = {}
    for leg in legs:
        by_direction.setdefault(str(leg.get("direction")), []).append(leg)

    # (а) цена ОДНОЙ ноги в каждую сторону. Сцена различается РОВНО знаком
    # дельты, оборот приравнен, чтобы проскальзывание не шевельнулось.
    one_down = [{"protocol": "A", "delta_usd": -SCENE_MOVE_USD, "direction": "decrease"}]
    one_up = [{"protocol": "B", "delta_usd": SCENE_MOVE_USD, "direction": "increase"}]
    cost_down = float(move_cost(one_down, turnover, chains))
    cost_up = float(move_cost(one_up, turnover, chains))
    direction_blind = abs(cost_down - cost_up) <= COST_EPS

    # НИЖНЯЯ граница: дословные ТРИ ноги §14 — выход из A, вход в B и выход из B.
    # Оборот тот же: §14 просит зарядить выход из B за ТЕ ЖЕ деньги, которые в
    # него вошли, а не выдумывать новый размер.
    exit_b = [{"protocol": "B", "delta_usd": -SCENE_MOVE_USD, "direction": "decrease"}]
    owner_three = list(legs) + exit_b
    owner_cost = float(move_cost(owner_three, turnover * 2.0, chains))
    # ВЕРХНЯЯ граница: будущий выход сам окажется перекладкой (две ноги).
    back_legs, back_turnover = legs_fn(tgt, cur, SCENE_CAPITAL_USD, SCENE_MIN_LEG_FRAC)
    backward = float(move_cost(back_legs, back_turnover, chains))

    def _ratio(total: float) -> Optional[float]:
        return round(total / priced, 6) if priced > COST_EPS else None

    terms: List[Dict[str, Any]] = []
    door_params = [name for name in inspect.signature(move_cost).parameters]
    for decl in TERMS:
        row = dict(decl)
        if decl["term"] in ("a_exit", "b_entry"):
            wanted = "decrease" if decl["term"] == "a_exit" else "increase"
            present = bool(by_direction.get(wanted))
            row["kind"] = ("charged_merged" if present and direction_blind
                           else "charged_named" if present else "not_charged")
            row["evidence"] = (
                f"нога {wanted} у хода: {len(by_direction.get(wanted) or [])} · "
                f"цена одной ноги вниз ${cost_down:.6f} против вверх ${cost_up:.6f}"
                + (" — направление ИГНОРИРУЕТСЯ" if direction_blind else " — числа РАЗНЫЕ"))
        else:
            row["kind"] = "no_input_door"
            row["evidence"] = (
                f"параметры живой двери цены: {door_params} — входа о будущем выходе "
                f"нет; выход из B стои́т ${owner_cost - priced:.2f} (нижняя граница) и "
                f"${backward:.2f} (верхняя, если выход сам окажется перекладкой), и в "
                "цену прямого хода не входит ни одна из них")
            row["door_params"] = door_params
        terms.append(row)

    return {
        "terms": terms,
        "scene": {"capital_usd": SCENE_CAPITAL_USD, "move_usd": SCENE_MOVE_USD,
                  "min_leg_frac": SCENE_MIN_LEG_FRAC, "chain": SCENE_CHAIN},
        "legs_priced": len(legs),
        "leg_directions": sorted(by_direction),
        # Что дверь ЗАРЯЖАЕТ сегодня за ход A→B.
        "priced_cost_usd": round(priced, 6),
        # Дословные три ноги §14 (нижняя граница полной цены круга). Число ног
        # печатается РЯДОМ с ценой: без него «нижняя граница» не отличима от
        # «та же пара ног с удвоенным оборотом» — мутант м3 первой редакции
        # выжил ровно на этом, и проверка его не видела.
        "owner_three_legs_count": len(owner_three),
        "owner_three_legs_cost_usd": round(owner_cost, 6),
        "owner_three_legs_over_priced": _ratio(owner_cost),
        # Будущий выход как перекладка (верхняя граница).
        "round_trip_cost_usd": round(priced + backward, 6),
        "round_trip_over_priced": _ratio(priced + backward),
        "direction_blind": direction_blind,
    }


# ---------------------------------------------------------------------------
# Ось 3: чем сегодня сказать о вероятности скорой перекладки
# ---------------------------------------------------------------------------

def load_history_producers() -> Tuple[Dict[str, Any], List[str]]:
    """({имя: производитель}, причины-отказа). Пустой словарь — НЕ ИЗМЕРЕНО.

    Производителей СПРАШИВАЕТСЯ ДВА: историю ходов (`_history_from_trades`) и
    возраст позиций (`_position_ages`). Одного не хватало — см. докстринг
    модуля, ось 3.
    """
    out: Dict[str, Any] = {}
    why: List[str] = []
    try:
        from spa_core.paper_trading import allocation_rationale as ar
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return {}, [f"производители истории не ввезены ({type(exc).__name__}: {exc})"
                    " — направление входов НЕ ИЗМЕРЕНО"]
    for name in ("_history_from_trades", "_position_ages"):
        fn = getattr(ar, name, None)
        if callable(fn):
            out[name] = fn
        else:
            why.append(f"у `allocation_rationale` нет производителя `{name}` — "
                       "форма изменилась, и часть входов НЕ ИЗМЕРЕНА")
    return out, why


def _ledger_at(when: datetime) -> List[dict]:
    """Журнал из одного хода с отметкой ``when``. Книга — сцена, не живой трек."""
    return [{"type": "rebalance", "ts": when.isoformat(), "delta_abs": SCENE_MOVE_USD,
             "from_allocation": {"A": SCENE_FROM_USD},
             "to_allocation": {"A": SCENE_FROM_USD - SCENE_MOVE_USD,
                               "B": SCENE_MOVE_USD}}]


def _ask_producers(producers: Dict[str, Any], when: datetime,
                   now: datetime) -> Dict[str, Any]:
    """Значения ВСЕХ входов, которые спрошенные производители заполняют.

    Имя входа → значение. Производитель, бросивший исключение, не обнуляет
    ответ: его вклад просто отсутствует, и это видно по пропуску имени.
    """
    out: Dict[str, Any] = {}
    ledger = _ledger_at(when) if when is not None else []
    book = {"A": SCENE_FROM_USD - SCENE_MOVE_USD, "B": SCENE_MOVE_USD}
    for name, fn in sorted(producers.items()):
        try:
            if name == "_history_from_trades":
                got = fn(ledger, now)
                if isinstance(got, dict):
                    out.update(got)
            else:  # _position_ages(trades, positions, now) → {протокол: возраст}
                got = fn(ledger, book, now)
                if isinstance(got, dict):
                    out["position_age_days"] = got
        except BaseException:  # noqa: BLE001 — молчание о сцене, не о классе
            continue
    return out


def _age_like(value: Any) -> Optional[float]:
    """Число, которое можно сравнить со нулём: сам float либо минимум словаря.

    `position_age_days` — словарь возрастов; направление у него то же, что у
    любого его члена, и брать минимум честно ровно потому, что знак у всех
    членов один (сцена одна на всех).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and value:
        nums = [float(v) for v in value.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return min(nums) if nums else None
    return None


def probe_input_directions(door: Dict[str, Any], producers: Dict[str, Any],
                           now: datetime, why: Sequence[str] = ()) -> Dict[str, Any]:
    """Ось 3: перечень входов живой двери и направление каждого временного.

    Направление НЕ объявляется, а меряется: две сцены, различающиеся РОВНО
    знаком времени (ход два дня НАЗАД против хода два дня ВПЕРЁД). Значение,
    которое при будущей записи становится отрицательным, есть ВОЗРАСТ — то есть
    обращено назад. Вход, которого НИ ОДИН спрошенный производитель не
    заполняет, получает `other_producer`, а не «назад»: это разные работы.
    """
    door_inputs = [name for name in inspect.signature(door["evaluate"]).parameters]
    empty = _ask_producers(producers, None, now)
    # ЗАПИСАННЫХ сцен две, а не одна: оборот «за сегодня» у хода двухдневной
    # давности равен нулю, то есть совпал бы со сценой пустого журнала, и вход
    # был бы объявлен не производным от прошлого ОШИБОЧНО. Вторая сцена (час
    # назад) закрывает ровно этот случай.
    recorded = {
        "two_days_ago": _ask_producers(producers, now - timedelta(days=2), now),
        "an_hour_ago": _ask_producers(producers, now - timedelta(hours=1), now),
    }
    past = recorded["two_days_ago"]
    future = _ask_producers(producers, now + timedelta(days=2), now)

    rows: List[Dict[str, Any]] = []
    for name in door_inputs:
        if name not in past and name not in future:
            rows.append({"input": name, "direction": "other_producer",
                         "evidence": "ни один спрошенный производитель этого входа "
                                     f"не заполняет (спрошено: {sorted(producers)})"})
            continue
        e_val = empty.get(name)
        present = {label: scene.get(name) for label, scene in recorded.items()}
        if all(v is None for v in present.values()) and future.get(name) is None:
            rows.append({"input": name, "direction": "no_producer",
                         "evidence": "ни в одной сцене значение не появилось"})
            continue
        moved = sorted(label for label, v in present.items() if v != e_val)
        if moved:
            p_num, f_num = _age_like(past.get(name)), _age_like(future.get(name))
            sign = (f" · прошлое {p_num} ≥ 0, будущее {f_num} < 0 ⇒ это ВОЗРАСТ"
                    if p_num is not None and f_num is not None and f_num < 0 <= p_num
                    else "")
            rows.append({"input": name, "direction": "observed_past",
                         "evidence": (f"значение отличается от сцены с ПУСТЫМ журналом "
                                      f"в сцен(ах) {moved} ⇒ производно от записанных "
                                      f"ходов{sign}")})
        else:
            rows.append({"input": name, "direction": "forward_looking",
                         "evidence": ("значение ОДИНАКОВО при пустом и при записанном "
                                      f"журнале ({e_val!r}) ⇒ записанным прошлым не "
                                      "объясняется (верхняя граница: литерал попал бы "
                                      "в этот же род)")})

    counts: Dict[str, int] = {d: 0 for d in INPUT_DIRECTIONS}
    for row in rows:
        counts[row["direction"]] = counts.get(row["direction"], 0) + 1
    future_age = _age_like(future.get("days_since_last_move"))
    return {"inputs": rows, "counts": counts,
            "producers_asked": sorted(producers),
            "producers_unmeasured": list(why),
            "door_inputs_declared": len(door_inputs),
            # Ответ §14 одним числом: сколько входов живой двери НЕ объясняются
            # записанным прошлым. ВЕРХНЯЯ граница — литерал попал бы сюда же.
            "forward_looking": counts.get("forward_looking", 0),
            "forward_looking_is_upper_bound": True,
            "scenes": ["empty"] + sorted(recorded) + ["two_days_ahead"],
            # Побочное наблюдение с НАЗВАННЫМ направлением вреда: запись из
            # будущего производитель принимает, возраст выходит отрицательным, и
            # отрицательный возраст попадает ВНУТРЬ окна разворота — то есть
            # ошибка идёт в СТРОГУЮ сторону и сделку не открывает.
            "producer_accepts_future_records": bool(future_age is not None and future_age < 0),
            }


# ---------------------------------------------------------------------------
# Ось 4: третий исход у входа разворота
# ---------------------------------------------------------------------------

def _doubt_scene(door: Dict[str, Any]) -> Dict[str, Any]:
    """Опорная сцена для `evaluate()`: ход, экономика которого ПРОХОДИТ.

    Выгода выбрана так, чтобы она лежала ВЫШЕ обычной планки и НИЖЕ
    поднятой — иначе разворот не на что было бы повлиять, и ось мерила бы
    собственную сцену. Числа планки берутся у ЖИВЫХ `TriggerParams`, а не
    перепечатываются.
    """
    params = door["module"].TriggerParams.for_mode()
    cur = {"A": 20_000.0, "B": 80_000.0}
    tgt = {"A": 10_000.0, "B": 90_000.0}
    # Ставки подобраны от ЖИВОЙ планки: сдвиг 10 % капитала при разнице ставок
    # `spread` даёт выгоду 0.10 × spread пп.
    needed = params.min_gain_pp
    spread = (needed + params.min_gain_pp * (params.reversal_escalation - 1.0) / 2.0) * 10.0
    apy = {"A": 3.0, "B": 3.0 + spread}
    evidenced = {"A", "B"}
    return {
        "params": params,
        "common": dict(
            current_positions=cur, target_positions=tgt, apy_pct=apy,
            evidenced=evidenced, chains={"A": SCENE_CHAIN, "B": SCENE_CHAIN},
            capital_usd=100_000.0, params=params,
            days_since_last_act=float(params.act_cooldown_days) * 10.0,
            position_age_days={"A": 60.0, "B": 60.0},
            turnover_last_week_usd=0.0, tvl_evidenced=evidenced,
        ),
        "last_move_legs": {"A": +10_000.0, "B": -10_000.0},
    }


def probe_doubt(door: Dict[str, Any]) -> Dict[str, Any]:
    """Ось 4: как дверь трактует «возраст прошлого хода НЕ ИЗМЕРЕН».

    Три сцены на предмет и три на контроль. Находка — совпадение вердикта
    «не измерено» с вердиктом, благоприятным для сделки.
    """
    scene = _doubt_scene(door)
    evaluate, params = door["evaluate"], scene["params"]
    common, last_move = scene["common"], scene["last_move_legs"]

    def run(**over: Any) -> Dict[str, Any]:
        kwargs = dict(common)
        kwargs.setdefault("turnover_today_usd", 0.0)
        kwargs.update(over)
        d = evaluate(**kwargs)
        return {"decision": d.decision, "required_gain_pp": d.required_gain_pp,
                "gain_pp": d.gain_pp, "reasons": list(d.reasons)}

    subject = {
        "inside_window": run(last_move_legs=last_move,
                             days_since_last_move=1.0),
        "outside_window": run(last_move_legs=last_move,
                              days_since_last_move=float(params.reversal_window_days) * 10.0),
        "unmeasured": run(last_move_legs=last_move, days_since_last_move=None),
    }
    control = {
        "measured_zero": run(last_move_legs=None, days_since_last_move=None,
                             turnover_today_usd=0.0),
        "unmeasured": run(last_move_legs=None, days_since_last_move=None,
                          turnover_today_usd=None),
    }

    rows: List[Dict[str, Any]] = []
    for decl in DOUBT_INPUTS:
        row = dict(decl)
        if decl["role"] == "subject":
            same_as_favourable = (
                subject["unmeasured"]["decision"] == subject["outside_window"]["decision"]
                and abs((subject["unmeasured"]["required_gain_pp"] or 0.0)
                        - (subject["outside_window"]["required_gain_pp"] or 0.0)) <= COST_EPS)
            moved = (subject["inside_window"]["required_gain_pp"]
                     != subject["outside_window"]["required_gain_pp"])
            if not moved:
                row["state"] = "no_effect"
                row["evidence"] = ("планка не шевельнулась ни внутри окна, ни вне его — "
                                   "сцена не различает разворот, и ось мерила бы себя")
            else:
                row["state"] = "fail_open" if same_as_favourable else "fail_closed"
                row["evidence"] = (
                    f"внутри окна: {subject['inside_window']['decision']} при планке "
                    f"{subject['inside_window']['required_gain_pp']} · вне окна: "
                    f"{subject['outside_window']['decision']} при "
                    f"{subject['outside_window']['required_gain_pp']} · НЕ ИЗМЕРЕНО: "
                    f"{subject['unmeasured']['decision']} при "
                    f"{subject['unmeasured']['required_gain_pp']}")
            row["scenes"] = subject
        else:
            differs = control["unmeasured"]["decision"] != control["measured_zero"]["decision"]
            row["state"] = "fail_closed" if differs else "fail_open"
            row["evidence"] = (
                f"измеренный ноль: {control['measured_zero']['decision']} · НЕ ИЗМЕРЕНО: "
                f"{control['unmeasured']['decision']} ("
                f"{'; '.join(control['unmeasured']['reasons']) or 'без причин'})")
            row["scenes"] = control
        rows.append(row)

    states = {r["input"]: r["state"] for r in rows}
    return {
        "inputs": rows, "states": states,
        # Контроль обязан подтвердиться, иначе признак построен из формулировки
        # заказа: сравнивать находку надо с ИЗВЕСТНЫМ членом класса.
        "control_holds": states.get("turnover_today_usd") == "fail_closed",
        "reversal_window_days": params.reversal_window_days,
        "reversal_escalation": params.reversal_escalation,
    }


# ---------------------------------------------------------------------------
# Ось 5: наблюдение срока удержания в data/
# ---------------------------------------------------------------------------

def _ts(value: object) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def holding_period_observation(data_dir: Path) -> Dict[str, Any]:
    """Ось 5: выводи́тся ли срок удержания из журнала ходов, и что его портит.

    Три исхода различимы (инв. #17): выведено · выведено и равно нулю (журнал
    прочитан, завершённых удержаний нет) · НЕ ИЗМЕРЕНО с названной причиной.

    Среднего здесь нет НАМЕРЕННО — см. докстринг модуля, ось 5.
    """
    out: Dict[str, Any] = {"data_dir": str(data_dir),
                           "min_real_hold_days": round(MIN_REAL_HOLD_DAYS, 6)}
    trades, why = _load(Path(data_dir) / "trades.json")
    if not isinstance(trades, list):
        out.update(state=UNMEASURED,
                   unmeasured=f"журнал ходов не прочитан как список: {why or 'нет файла'}")
        return out
    reb = [t for t in trades if isinstance(t, dict) and t.get("type") == "rebalance"]
    dated = [t for t in reb if _ts(t.get("ts")) is not None]
    if not dated:
        out.update(state=UNMEASURED,
                   unmeasured=f"ходов с разбираемой отметкой нет (ходов в журнале {len(reb)})",
                   rebalances=len(reb))
        return out
    dated.sort(key=lambda t: _ts(t["ts"]))  # type: ignore[arg-type,return-value]

    open_at: Dict[str, datetime] = {}
    closed: List[Dict[str, Any]] = []
    for t in dated:
        when = _ts(t["ts"])
        frm = t.get("from_allocation") if isinstance(t.get("from_allocation"), dict) else {}
        to = t.get("to_allocation") if isinstance(t.get("to_allocation"), dict) else {}
        for proto in sorted(set(frm or {}) | set(to or {})):
            try:
                before = float((frm or {}).get(proto) or 0.0)
                after = float((to or {}).get(proto) or 0.0)
            except BaseException:  # noqa: BLE001 — нечисло не наблюдение
                continue
            if before <= 0 < after:
                open_at.setdefault(proto, when)
            elif before > 0 >= after:
                started = open_at.pop(proto, None)
                if started is not None:
                    closed.append({"protocol": proto, "opened": started.isoformat(),
                                   "closed": when.isoformat(),
                                   "days": round((when - started).total_seconds() / 86400.0, 6)})

    real = [c for c in closed if c["days"] >= MIN_REAL_HOLD_DAYS]
    sub = len(closed) - len(real)

    # «Открыто» по журналу и «есть в книге» — РАЗНЫЕ утверждения, и расхождение
    # между ними есть ИЗМЕРЕННЫЙ предел качества вывода, а не мелочь: цепь
    # `from→to` журнала сохраняется не везде (дыра `T008`), поэтому позиция
    # может остаться «открытой» навсегда, не существуя в книге. Первая редакция
    # этой оси печатала одно число «открытых» и тем самым выдавала разрыв
    # журнала за живое удержание; ошибка нашлась своим же замером.
    book, why_book = _load(Path(data_dir) / "current_positions.json")
    held: Optional[set] = None
    if isinstance(book, dict):
        inner = book.get("positions") if isinstance(book.get("positions"), dict) else book
        held = {str(k) for k, v in (inner or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    orphan_open = (sorted(set(open_at) - held) if held is not None else None)
    out.update(
        state="derived",
        rebalances=len(reb),
        rebalances_dated=len(dated),
        # Завершённых удержаний ВСЕГО и — отдельно — тех, что длиннее порога.
        # Отфильтровать молча значило бы спрятать свойство ПИСАТЕЛЯ журнала.
        holdings_closed=len(closed),
        holdings_real=len(real),
        holdings_below_threshold=sub,
        holdings_open=len(open_at),
        # Третий исход (инв. #17): книга не прочитана ⇒ `None`, а не ноль.
        holdings_open_not_in_book=(len(orphan_open) if orphan_open is not None else None),
        holdings_open_not_in_book_names=orphan_open,
        book_state=("read" if held is not None
                    else f"НЕ ИЗМЕРЕНО: {why_book or 'current_positions.json не прочитан'}"),
        shortest_real_days=min((c["days"] for c in real), default=None),
        longest_real_days=max((c["days"] for c in real), default=None),
        # Качество вывода ограничено разрывами журнала — их мерит ВТОРАЯ ЗАПИСЬ
        # (`scripts/book_second_record.py`), и сюда её вердикт не копируется:
        # своя копия разошлась бы с ней молча.
        quality_bounded_by="scripts/book_second_record.py (дыры и переименования журнала)",
        # Публикатора у наблюдения нет: единственный срок удержания в коде —
        # ОБЪЯВЛЕННЫЙ (`holding_period_days_declared`, research_factory), а не
        # наблюдённый. Это и есть ответ заказа G945 п. 1 на вторую половину.
        published_by=None,
        declared_elsewhere="spa_core/research_factory (holding_period_days_declared — ОБЪЯВЛЕН, не наблюдён)",
    )
    return out


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def measure(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Секция цикла: пять осей §14."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    rep: Dict[str, Any] = {
        "status": "OK",
        "engine": ENGINE,
        "is_advisory": IS_ADVISORY,
        "question": ("§14: «A → B не должна оцениваться только по стоимости входа "
                     "в B; нужно A exit + B entry + eventual B exit. Высокая "
                     "вероятность скорой новой ребалансировки должна снижать "
                     "привлекательность операции»"),
        "declared": {
            "terms_declared": len(TERMS),
            "charge_kinds": list(CHARGE_KINDS),
            "input_directions": list(INPUT_DIRECTIONS),
            "doubt_states": list(DOUBT_STATES),
            "doubt_inputs_declared": len(DOUBT_INPUTS),
        },
    }

    broken = validate()
    if broken:
        rep.update(status="SKIPPED", verdict=UNMEASURED.upper(),
                   unmeasured=["объявление не выдерживает своего контракта: "
                               + "; ".join(broken)])
        rep["reason"] = rep["unmeasured"][0]
        return rep

    door, why_door = load_cost_door()
    if door is None:
        rep.update(status="SKIPPED", verdict=UNMEASURED.upper(), unmeasured=[why_door])
        rep["reason"] = why_door
        return rep

    rep["round_trip"] = probe_round_trip(door)
    rep["doubt"] = probe_doubt(door)

    producers, why_producers = load_history_producers()
    if not producers:
        rep["input_directions"] = {"state": UNMEASURED,
                                   "unmeasured": "; ".join(why_producers)}
    else:
        rep["input_directions"] = probe_input_directions(door, producers, now,
                                                         why_producers)

    rep["holding_period"] = holding_period_observation(data_dir)

    findings: List[str] = []
    missing = [t["owner_words"] for t in rep["round_trip"]["terms"]
               if t["kind"] == "no_input_door"]
    if missing:
        rt = rep["round_trip"]
        lo, hi = rt["owner_three_legs_over_priced"], rt["round_trip_over_priced"]
        findings.append(
            "слагаемых §14, о которых двери нечем сказать: " + ", ".join(missing)
            + (f"; круг дороже видимого решению в {lo}…{hi} раз(а) (нижняя граница — "
               "дословные три ноги владельца, верхняя — будущий выход сам окажется "
               "перекладкой)" if lo is not None and hi is not None
               else "; вилка круга НЕ ОПРЕДЕЛЕНА (цена прямого хода неотличима от нуля)"))
    merged = [t["owner_words"] for t in rep["round_trip"]["terms"]
              if t["kind"] == "charged_merged"]
    if merged:
        findings.append("слагаемых, заряженных ОДНИМ числом и дверью не различаемых: "
                        + ", ".join(merged))
    idir = rep["input_directions"]
    if idir.get("state") == UNMEASURED:
        findings.append("направление входов НЕ ИЗМЕРЕНО: " + str(idir.get("unmeasured")))
    elif idir.get("forward_looking") == 0:
        findings.append(
            "входов живой двери, НЕ объясняемых записанным прошлым: 0 из "
            f"{idir.get('door_inputs_declared')} (ВЕРХНЯЯ граница — литерал попал бы "
            "в тот же род) — сказать о вероятности СКОРОЙ новой перекладки сегодня "
            "нечем ни одним входом")
    doubt = rep["doubt"]
    if not doubt.get("control_holds"):
        findings.append(
            "КОНТРОЛЬ ОСИ СОМНЕНИЯ НЕ ПОДТВЕРДИЛСЯ: известный член класса "
            "`turnover_today_usd` не дал `fail_closed` — признак построен из "
            "формулировки заказа, и вердикт об оси НЕ ВЫДАЁТСЯ")
    else:
        open_ones = [name for name, state in (doubt.get("states") or {}).items()
                     if state == "fail_open"]
        if open_ones:
            findings.append(
                "входов, у которых «не измерено» разрешается В ПОЛЬЗУ СДЕЛКИ: "
                + ", ".join(open_ones))
    hp = rep["holding_period"]
    if hp.get("state") == UNMEASURED:
        findings.append("срок удержания НЕ ИЗМЕРЕН: " + str(hp.get("unmeasured")))
    elif hp.get("holdings_open_not_in_book"):
        findings.append(
            f"журнал считает открытыми {hp['holdings_open_not_in_book']} позиц(ию/ий), "
            f"которых в книге НЕТ ({', '.join(hp['holdings_open_not_in_book_names'][:6])}"
            f"{' …' if len(hp['holdings_open_not_in_book_names']) > 6 else ''}) — цепь "
            "`from→to` сохраняется не везде, и это ПРЕДЕЛ качества вывода срока "
            "удержания, а не живое удержание")
    if hp.get("state") != UNMEASURED and hp.get("published_by") is None:
        findings.append(
            f"срок удержания ВЫВОДИ́ТСЯ из журнала ({hp.get('holdings_real')} завершённых "
            f"удержаний длиннее порога из {hp.get('holdings_closed')}), но не публикует "
            "его никто — формула §13 `Expected Holding Period` стои́т на ОБЪЯВЛЕННОМ числе")

    rep["findings"] = findings
    rep["verdict"] = "FINDINGS" if findings else "OK"

    # ── СТАТУС ПО КОНТРАКТУ ОТЧЁТА, а не по своему словарю ────────────────
    # У отчёта аналитики статусы объявлены тремя (`OK` · `SKIPPED` · `ERROR`,
    # сторож `test_report_sections.py`), и секция без данных обязана сказать
    # `SKIPPED` С ПРИЧИНОЙ. Первая редакция ставила `WARN`/`CRITICAL` — свой
    # словарь поверх чужого контракта, и два сторожа покраснели ПО ДЕЛУ.
    # Находки живут в `verdict`/`findings` — ровно как у соседей §10 и §12;
    # ИЗМЕРЕННОЕ при этом остаётся в теле целиком, ничего не теряется.
    if not doubt.get("control_holds"):
        # Вердикт об оси сомнения НЕ ВЫДАЁТСЯ: признак не прошёл контроль
        # известным членом класса. Это «не измерено», а не «чисто».
        rep["status"] = "SKIPPED"
        rep["reason"] = ("контроль оси сомнения не подтверждён — вердикт об оси "
                         "НЕ ВЫДАЁТСЯ")
    elif rep["holding_period"].get("state") == UNMEASURED:
        # Единственная ось, которой нужен `data/`. Её «не измерено» и есть
        # причина, по которой секция данных честно зовётся пропущенной.
        rep["status"] = "SKIPPED"
        rep["reason"] = str(rep["holding_period"].get("unmeasured"))
    elif rep["input_directions"].get("state") == UNMEASURED:
        rep["status"] = "SKIPPED"
        rep["reason"] = str(rep["input_directions"].get("unmeasured"))
    else:
        rep["status"] = "OK"
    return rep


def _print(rep: Dict[str, Any]) -> int:
    print(f"§14 Round trip — круг хода, а не вход (двигатель {rep['engine']}, "
          f"слой {'ADVISORY' if rep.get('is_advisory') else '?'})")
    if "round_trip" not in rep:
        # Объявление сломано либо дверь цены не ввезена: мерить было нечем.
        print("   НЕ ИЗМЕРЕНО: " + "; ".join(str(u) for u in (rep.get("unmeasured") or [])))
        return 2
    rt = rep["round_trip"]
    print(f"   ось 1 — слагаемые §14 (ног у хода {rt['legs_priced']}, "
          f"направления {rt['leg_directions']}):")
    for term in rt["terms"]:
        print(f"      [{term['kind']}] {term['owner_words']} — {term['evidence']}")
    print(f"   ось 2 — дверь заряжает ${rt['priced_cost_usd']:.2f}; дословные три ноги "
          f"§14 ${rt['owner_three_legs_cost_usd']:.2f} (×"
          f"{rt['owner_three_legs_over_priced']}), будущий выход как перекладка "
          f"${rt['round_trip_cost_usd']:.2f} (×{rt['round_trip_over_priced']}) ⇒ ВИЛКА")
    idir = rep["input_directions"]
    if idir.get("state") == UNMEASURED:
        print(f"   ось 3 — НЕ ИЗМЕРЕНО: {idir.get('unmeasured')}")
    else:
        print(f"   ось 3 — входов двери {idir['door_inputs_declared']}, спрошено "
              f"производителей {len(idir['producers_asked'])} "
              f"({', '.join(idir['producers_asked'])}), по направлению: "
              + " · ".join(f"{k} {v}" for k, v in sorted(idir["counts"].items()) if v))
        for reason in idir.get("producers_unmeasured") or []:
            print(f"      НЕ ИЗМЕРЕНО: {reason}")
        for row in idir["inputs"]:
            if row["direction"] in ("observed_past", "forward_looking", "no_producer",
                                    "other_producer"):
                print(f"      [{row['direction']}] {row['input']} — {row['evidence']}")
    doubt = rep["doubt"]
    print(f"   ось 4 — третий исход (окно разворота {doubt['reversal_window_days']} дн., "
          f"планка ×{doubt['reversal_escalation']}), контроль "
          f"{'ПОДТВЕРЖДЁН' if doubt['control_holds'] else 'НЕ ПОДТВЕРЖДЁН'}:")
    for row in doubt["inputs"]:
        print(f"      [{row['state']}] {row['input']} ({row['role']}) — {row['evidence']}")
    hp = rep["holding_period"]
    if hp.get("state") == UNMEASURED:
        print(f"   ось 5 — НЕ ИЗМЕРЕНО: {hp.get('unmeasured')}")
    else:
        print(f"   ось 5 — срок удержания ВЫВОДИ́ТСЯ: завершённых {hp['holdings_closed']} "
              f"(длиннее порога {hp['holdings_real']}, короче {hp['holdings_below_threshold']}), "
              f"открытых {hp['holdings_open']} (из них НЕТ в книге "
              f"{hp['holdings_open_not_in_book']}), публикатор {hp['published_by']}")
    if rep.get("status") == "SKIPPED":
        print(f"   статус секции отчёта: SKIPPED — {rep.get('reason')}")
    for finding in rep.get("findings") or []:
        print(f"   ⚠️ {finding}")
    if not rep.get("findings"):
        print("   находок нет (ноль ЧИСЛОМ, а не молчанием)")
    # Код возврата принадлежит ПРИБОРУ, а не контракту отчёта: `SKIPPED` в
    # отчёте означает «ось данных не измерена», и для прибора это код 2.
    if rep.get("status") == "SKIPPED":
        return 2
    return 1 if rep.get("findings") else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ or "",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data",
                    help="каталог данных: из worktree живого data/ нет по построению")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    rep = measure(Path(ns.data_dir))
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 2 if rep.get("status") == "SKIPPED" else (
            1 if rep.get("findings") else 0)
    return _print(rep)


if __name__ == "__main__":  # pragma: no cover — CLI
    sys.exit(main())
