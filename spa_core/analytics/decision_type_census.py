"""decision_type_census.py — §24 ТЗ «Portfolio CIO»: Decision types.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §24 «Decision types»::

    Portfolio CIO должен выдавать строго типизированный результат:
    KEEP
    REBALANCE
    DEFER
    REDUCE_RISK
    EMERGENCY_EXIT
    REQUIRE_OWNER_APPROVAL
    Не использовать свободный текст как единственный machine-readable результат.

🪤 ЧИСЛО ТИПОВ ПЕРЕСЧИТАНО ПО ТЗ СВОИМ ГЛАЗОМ
=============================================
Заказ G955 п. 1 назвал ШЕСТЬ типов, и на этот раз ПЕРЕСЧЁТ СОШЁЛСЯ: в §24 ТЗ
их ровно шесть. Два предыдущих цикла класса дали расхождение (#1082 — заказ
назвал восемь событий §21 из одиннадцати; #1084 — четыре стартовые величины §23
из шести), поэтому число объявлено константой :data:`OWNER_TYPES_DECLARED`,
число заказа — константой :data:`ORDER_G955_NAMED`, и расхождение (здесь — НОЛЬ)
краснеет тестом, а не живёт в чьей-то памяти. «Сошлось» — это ЗАМЕР, и он обязан
быть напечатан наравне с расхождением: иначе о сошедшемся пересчёте нельзя
отличить «проверяли» от «не проверяли».

Требований в §24 ДВА, и слить их в одно — ответить не на то
===========================================================
* **словарь.** Результат обязан быть СТРОГО ТИПИЗИРОВАН, и типы названы
  владельцем поимённо. Вопрос: существует ли такой тип у двери решения;
* **запрет свободного текста.** Даже у двери, выдающей тип, свободный текст не
  смеет быть ЕДИНСТВЕННЫМ машинно-читаемым результатом. Это ДРУГОЙ предикат —
  он про ФОРМУ результата, а не про его словарь, и дверь может исполнять одно,
  нарушая другое.

Поэтому осей ТРИ, и каждая отвечает на свой вопрос:

ось A — ОБЪЯВЛЕННЫЙ ДОМЕН ДВЕРИ (:data:`PRESENCE_KINDS`)
    Объявлен ли токен владельца домен-константой хоть одной двери решения.
    Домены собираются ИНТРОСПЕКЦИЕЙ модулей дверей, а не перечнем в этом файле:
    перечислить руками значило бы, что отчёт устареет молча при первом же новом
    токене. **«Есть ли строка с таким словом» вопросом НЕ является** — у
    `/pause` имя ``PAUSE CIO`` при эффекте ``ALL_CASH``, и это уже измерено
    (ADR-962 … ADR-966).
ось B — СЦЕНА ОЖИДАНИЯ (:data:`EXPECTATION_KINDS`)
    ДИФФЕРЕНЦИАЛЬНО: строится сцена, в которой ожидается ИМЕННО этот тип, и
    печатается, какой токен выдан на самом деле. Без этой оси «тип есть» верно
    СЛУЧАЙНО, а «типа нет» неотличимо от «сцену построить не сумели».
ось C — ФОРМА РЕЗУЛЬТАТА (:data:`RESULT_FORM_KINDS`)
    Про ДВЕРИ, а не про типы: несёт ли вердикт двери поле с перечислимым
    доменом, и есть ли рядом свободный текст. Это второе требование §24.

🪤 СОПОСТАВЛЯТЬ ТОКЕНЫ ПО ДОГАДКЕ ЗАПРЕЩЕНО
===========================================
``rebalance_economics`` отвечает ``ACT``/``HOLD``, ``churn_damper`` —
``ALLOW``/``BLOCK``, лестница стоп-крана — ``NONE``/``SOFT_DERISK``/``HARD_KILL``,
вторая дверь политики — ``NONE``/``HALT_NEW``/``ALL_CASH``. Ни один из этих
десяти токенов не входит в словарь владельца. Прибор обязан сказать «словарь
владельца в дереве не реализован ни на одной двери», а НЕ переводить
``ACT`` ↔ ``REBALANCE`` и ``ALL_CASH`` ↔ ``EMERGENCY_EXIT`` по сходству смысла:
такой перевод — утверждение О ЭКВИВАЛЕНТНОСТИ, которого §24 не делает и которое
нечем проверить. Ось B печатает ВЫДАННЫЕ токены дословно, и читатель видит
расхождение сам, а не верит нашему переводу.

🪤 ДВА БЛИЗКИХ СОВПАДЕНИЯ, КОТОРЫЕ ДВЕРЬЮ РЕШЕНИЯ НЕ ЯВЛЯЮТСЯ
=============================================================
Слово владельца в дереве всё же встречается — ДВА раза, и ни одно из мест не
производит решения (:data:`NEAR_MISS_NOT_A_DOOR`):

``spa_core/agents/decision_logger.py``
    держит свой словарь ``ALLOCATE``/``PASS``/``REBALANCE``/``ALERT``/``HOLD``/
    ``REPORT`` — но это ЖУРНАЛИСТ уже состоявшегося действия, а не дверь
    решения: он пишет строку в SQLite и ничего не разрешает и не запрещает.
    Признать его исполнением §24 значило бы выдать ПРОТОКОЛ за РЕШЕНИЕ.
журнальная ячейка ``type``
    писатель ходов кладёт в неё ЛИТЕРАЛ ``"rebalance"`` (строчными). Род ячейки
    измерен §20 (``SLOT_KINDS``, ADR-963) и здесь не перемеривается: одна
    шкала — одно измерение. Записывается только СОВЕРШЁННЫЙ ход, то есть пяти
    остальным типам в журнале места нет ПО ПОСТРОЕНИЮ.

Что прибор НЕ утверждает
========================
* **Он не судит, ПРАВИЛЬНЫЙ ли вердикт дверь выдала.** Предмет §24 — РОД
  результата, не его содержание.
* **Он не строит недостающие типы и не правит ни одного порога.** Завести
  словарь решений на пути денег — money-path и предмет №1 владельца (ADR-285);
  ``REQUIRE_OWNER_APPROVAL`` сверх того задевает предмет №2.
* **Он не мерит, ДОХОДИТ ли тип до читателя.** «Дверь выдала токен» и «токен
  прочитан потребителем» — разные вопросы; второй здесь не задаётся, и нулём
  его отсутствие не считается.
* **«Токена нет» ≠ «исход недостижим».** Система умеет остановить покупки и
  уйти в кэш; §24 спрашивает, НАЗЫВАЕТ ли она это типизированным результатом.

ADVISORY. Живой ``data/`` не читается и не пишется: все сцены — из литералов,
часы и журнал ходов инъектируются, дверь гейта работает в одноразовом каталоге.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import contextlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей, шкалы и СЦЕН. Своих копий здесь нет намеренно: ввозится РОВНО
# то, что получает читателя ниже, — ввоз без читателя есть ложное усиление.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .new_capital_census import SLOT_KINDS
except Exception as _exc:  # pragma: no cover
    SLOT_KINDS = ()  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§20 SLOT_KINDS: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .anti_churn_census import (
        SCENE_NOW, SURFACES_22,
        _books, _control, _damper_move, _econ_move, _scene_capital, _trade,
    )
except Exception as _exc:  # pragma: no cover
    SURFACES_22 = ()  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§22 сцены и поверхности: {}: {}".format(
        type(_exc).__name__, _exc))

# §23 (`DECLARATION_KINDS`) здесь НЕ ввозится намеренно: читателя у этой шкалы в
# §24 нет, а ввоз без читателя есть ЛОЖНОЕ УСИЛЕНИЕ — отчёт выглядел бы
# опирающимся на §23, ничего у него не спрашивая.

try:
    from spa_core.monitoring.cio_auto_execution_limits import _gate_verdict
except Exception as _exc:  # pragma: no cover
    _VOCAB_ERRORS.append("§41 дверь гейта: {}: {}".format(
        type(_exc).__name__, _exc))


#: ШЕСТЬ типов решения §24, дословно и в порядке ТЗ.
OWNER_DECISION_TYPES: Tuple[str, ...] = (
    "KEEP",
    "REBALANCE",
    "DEFER",
    "REDUCE_RISK",
    "EMERGENCY_EXIT",
    "REQUIRE_OWNER_APPROVAL",
)

#: Число объявлено ОТДЕЛЬНОЙ константой намеренно — см. ловушку в docstring.
OWNER_TYPES_DECLARED: int = 6

#: Сколько типов назвал заказ G955 п. 1. Хранится рядом, чтобы «сошлось» было
#: ИЗМЕРЕНО отчётом, а не замечено глазами один раз и забыто.
ORDER_G955_NAMED: int = 6

#: Поверхности §24. ``SURFACES_22`` несёт шесть поверхностей решения; §24
#: спрашивает про типы ``REDUCE_RISK``/``EMERGENCY_EXIT``/
#: ``REQUIRE_OWNER_APPROVAL``, и для них нужны две двери, которых ни §20, ни
#: §22, ни §41 среди своих поверхностей не называют:
#:
#: ``kill``
#:     лестница стоп-крана (``governance/kill_switch``) — ЕДИНСТВЕННЫЙ
#:     производитель СТЕПЕНИ опасности в дереве;
#: ``owner``
#:     дверь, которая умела бы сказать «решает владелец» машинно.
#:
#: Расширение названо, вторая копия перечня не заводится.
SURFACES_24: Tuple[str, ...] = tuple(SURFACES_22) + ("kill", "owner")

#: Двери, у которых есть ВЕРДИКТ и которые поэтому пробуются сценой. Имя двери
#: — имя поверхности §24; состав УЖЕ отличается от состава поверхностей, и это
#: не упущение, а ответ (см. :data:`SURFACES_WITHOUT_A_TYPED_DOOR`).
DOORS_24: Tuple[str, ...] = ("economics", "damper", "book", "kill", "gate")

#: Поверхность §24, у которой ТИПИЗИРОВАННОЙ двери нет вовсе, и причина. Это
#: УТВЕРЖДЕНИЕ, поэтому оно печатается, а не умалчивается: поверхность, молча
#: выпавшая из пробы, читалась бы как «её не нашли».
SURFACES_WITHOUT_A_TYPED_DOOR: Dict[str, str] = {
    "allocator": (
        "аллокатор выдаёт ЦЕЛЬ В ДОЛЛАРАХ (раскладку), а не тип решения: его "
        "результат — словарь «протокол → сумма», перечислимого домена у него "
        "нет по построению"),
    "journal": (
        "писатель ходов кладёт в ячейку `type` ЛИТЕРАЛ «rebalance»; род ячейки "
        "измерен §20 (SLOT_KINDS) и здесь не перемеривается. Журнал фиксирует "
        "СОВЕРШЁННЫЙ ход, поэтому пяти неактивным типам в нём места нет"),
    "owner": (
        "двери, которая произносила бы «решает владелец» машинно, на пути "
        "решения НЕТ: очередь владельца (`orchestrator_queue`) принимает "
        "КАРТОЧКУ от сессии, а не вердикт от двери решения, и ни один вердикт "
        "дверей ниже её не зовёт"),
}

#: Два места, где слово владельца в дереве встречается, НЕ будучи дверью
#: решения. Печатается: умолчать о близком совпадении значило бы оставить
#: читателю повод решить, что мы его не заметили.
NEAR_MISS_NOT_A_DOOR: Dict[str, str] = {
    "spa_core/agents/decision_logger.py": (
        "держит словарь ALLOCATE/PASS/REBALANCE/ALERT/HOLD/REPORT — но это "
        "ЖУРНАЛИСТ состоявшегося действия: пишет строку в SQLite, ничего не "
        "разрешает и не запрещает. Совпадение ровно по одному слову "
        "(REBALANCE), и выдать протокол за решение §24 не позволяет"),
    "spa_core/paper_trading/cycle_runner.py «type»: «rebalance»": (
        "литерал строчными в журнальной ячейке; §20 измерил род ячейки, и "
        "записывается только СОВЕРШЁННЫЙ ход"),
}

#: Ось A — объявлен ли токен владельца доменом двери. Шкала ОБЪЯВЛЕНА, а не
#: выведена из сравнений: ветка ``else`` по построению не может сказать, какие
#: роды существуют (урок ADR-357 п. 3).
PRESENCE_KINDS: Tuple[str, ...] = (
    # токен объявлен домен-константой модуля двери решения
    "in_declared_domain",
    # токен константой не объявлен, но ВЫДАН дверью на сцене (литерал в коде)
    "emitted_only",
    # ни объявлен, ни выдан ни одной дверью решения
    "absent_from_every_door",
    UNMEASURED,
)

#: Ось B — что выдано на сцене, где ожидался ИМЕННО этот тип.
EXPECTATION_KINDS: Tuple[str, ...] = (
    # дверь выдала РОВНО токен владельца
    "expected_type_emitted",
    # двери ответили, но токенами ВНЕ словаря владельца (названы дословно)
    "foreign_token_emitted",
    # ни одна дверь не даёт на эту сцену типизированного ответа ВООБЩЕ
    "no_typed_answer",
    # сцену построить нечем, и причина названа
    "unreachable_by_construction",
    UNMEASURED,
)

#: Ось C — форма результата двери (второе требование §24).
RESULT_FORM_KINDS: Tuple[str, ...] = (
    # есть поле с ОБЪЯВЛЕННЫМ доменом И свободный текст рядом
    "typed_plus_text",
    # есть только поле с объявленным доменом; свободного текста нет
    "typed_only",
    # дверь выдаёт токен, но его домен НЕ ОБЪЯВЛЕН НИГДЕ: перечислить исходы
    # нечем, и «строго типизированный результат» §24 держится на том, что
    # читатель сам соберёт домен из литералов в коде
    "typed_but_domain_undeclared",
    # машинно-читаемого поля с перечислимым доменом НЕТ: остаётся текст
    "text_only",
    # результат — ЛОГИЧЕСКОЕ значение, а не тип: домена из двух исходов
    # «да/нет» достаточно для допуска и НЕ достаточно для §24
    "boolean_not_a_type",
    UNMEASURED,
)

#: Просадка сцен §24 в процентах. Литералы — ПРЕДМЕТ (это границы лестницы
#: владельца, ADR-034/048), а не пороги, которые прибор выбирает.
_DD_CALM_PCT: float = 1.0
_DD_SOFT_PCT: float = 7.0
_DD_HARD_PCT: float = 12.0

#: Доля капитала хода, заведомо превышающая потолок одного хода и абсолютный
#: потолок суммы: сцена «решать такое должен владелец».
_OWNER_SCALE_FRACTION: float = 0.85


# ──────────────────────── книга сцены для двери политики ────────────────────

def _scene_book(pnl_usd: float) -> Any:
    """Книга сцены для второй двери политики (``check_portfolio_health``).

    Состав подобран ЗАМЕРОМ, а не на глаз: при двух ногах по 50 % вердикт
    решала бы концентрация, при трёх ногах на одной сети — потолок сети, и
    «здоровая сцена» никогда не была бы здоровой. Это условие ВСЕГО отчёта:
    сцена, отказывающая по соседней причине, произносила бы «тип не выдан» и
    в мире, где он выдаётся.
    """
    from spa_core.risk.policy import PortfolioState, Position
    cap = _capital()
    specs = (("aave_v3", 0.35, "ethereum"),
             ("compound_v3", 0.35, "ethereum"),
             ("morpho_blue_base", 0.25, "base"))
    positions = []
    for i, (key, share, chain) in enumerate(specs):
        p = Position(key, "T1", "USDC", share * cap, 5.0, 5.0,
                     unrealized_pnl_usd=(pnl_usd if i == 0 else 0.0),
                     days_held=30.0)
        p.chain = chain
        positions.append(p)
    return PortfolioState(total_capital_usd=cap, positions=positions)


def _capital() -> float:
    """Капитал сцены. ВВЕЗЕН у §22 — своего числа здесь нет ни одного.

    Тонкая обёртка, а не копия: §22 сам решает, откуда берёт величину (у §41),
    и завести здесь второй источник значило бы развести две сцены молча.
    """
    return float(_scene_capital())


@contextlib.contextmanager
def _quiet():
    """Глушит ЖУРНАЛИРОВАНИЕ дверей на время сцены и возвращает его обратно.

    🪤 Первая редакция глушила ``contextlib.redirect_stdout`` — и это было
    ПУСТЫМ ДЕЙСТВИЕМ, которое выглядело работающим: ``RiskPolicy._log_result``
    пишет через ``logging``, то есть в stderr, а не в stdout. Отчёт выходил
    вперемешку с чужим логом, а код «подавления» при этом был на месте и
    читался как исполненный. Названо в ADR-967 как моя ошибка замера.

    ``logging.disable`` выбран намеренно: он не зависит от того, какой поток
    захватил чей обработчик, и восстанавливается в ``finally``. Ни одно
    СОДЕРЖИМОЕ вердикта при этом не подменяется — глушится только попутный
    лог; свободный текст двери прибор читает ИЗ ВЕРДИКТА (``violations``,
    ``reasons``), а не из лога.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _book_verdict(drawdown_pct: float) -> Any:
    """Вердикт второй двери политики при заданной ПРОСАДКЕ книги."""
    from spa_core.risk.policy import RiskPolicy
    state = _scene_book(-drawdown_pct / 100.0 * _capital())
    return RiskPolicy().check_portfolio_health(state)


# ───────────────── объявленные домены дверей (ось A) ────────────────────────

#: Дверь → модуль, в котором её домен мог бы быть объявлен.
_DOMAIN_MODULES: Dict[str, str] = {
    "damper": "spa_core.governance.churn_damper",
    "kill": "spa_core.governance.kill_switch",
    "book": "spa_core.risk.policy",
    "economics": "spa_core.allocator.rebalance_economics",
    "gate": "spa_core.paper_trading.risk_gate",
}


def _declared_domains(emitted: Dict[str, List[str]]
                      ) -> Tuple[Dict[str, List[str]], List[str]]:
    """Домен-константы каждой двери и причины, по которым домен не прочитан.

    🪤 ПРАВИЛО ПРИНАДЛЕЖНОСТИ — ПО ЗНАЧЕНИЮ, А НЕ ПО ИМЕНИ, и это поправка к
    моей же первой редакции. Та брала «все строковые константы модуля» (с
    необязательным префиксом имени) и у двери допуска объявила доменом
    ``current_positions.json`` и ``risk_policy_blocks.json`` — ИМЕНА ФАЙЛОВ.
    Ответ был бы верен про «строковые константы» и неверен про ДОМЕН ВЕРДИКТА,
    то есть прибор отвечал бы на свой вопрос вместо нужного. Названо в ADR-967.

    Константа принадлежит домену, если её ЗНАЧЕНИЕ — либо токен, который дверь
    ВЫДАЛА на сцене, либо токен из словаря ВЛАДЕЛЬЦА. Второе слагаемое не
    делает меру круговой: ось A ровно об этом и спрашивает, и без него
    объявленный, но ни разу не выданный токен владельца остался бы невидимым
    (``in_declared_domain`` был бы недостижим по построению).
    """
    out: Dict[str, List[str]] = {}
    why: List[str] = []
    for door, modname in sorted(_DOMAIN_MODULES.items()):
        try:
            mod = __import__(modname, fromlist=["*"])
        except Exception as exc:  # noqa: BLE001
            why.append("{}: модуль {} не ввезён: {}: {}".format(
                door, modname, type(exc).__name__, exc))
            out[door] = []
            continue
        belongs = set(emitted.get(door) or []) | set(OWNER_DECISION_TYPES)
        out[door] = sorted({
            str(getattr(mod, n)) for n in dir(mod)
            if n.isupper() and isinstance(getattr(mod, n, None), str)
            and str(getattr(mod, n)) in belongs})
    return out, why


# ─────────────────────── сцены ожидания (ось B) ─────────────────────────────

def _emit_economics(**over: Any) -> Dict[str, Any]:
    """Токен двери ЦЕНЫ плюс её свободный текст."""
    books = _books(_capital())
    cur = over.pop("current", books["A"])
    tgt = over.pop("target", books["B"])
    d = _econ_move(cur, tgt, over.pop("winner", "pendle"), **over)
    return {"token": str(d.decision), "text": list(d.reasons)[:3]}


def _emit_damper(trades: Sequence[dict], **over: Any) -> Dict[str, Any]:
    books = _books(_capital())
    cur = over.pop("current", books["A"])
    tgt = over.pop("target", books["B"])
    v = _damper_move(cur, tgt, list(trades), **over)
    # У ограничителя ДВА перечислимых поля (`decision` и `reason`) и одно
    # свободное (`detail`); токеном §24 может быть только первое — второе
    # отвечает на вопрос «почему», а не «что это за решение».
    return {"token": str(v.decision), "reason_token": str(v.reason),
            "text": [str(v.detail)]}


def _emit_book(drawdown_pct: float) -> Dict[str, Any]:
    r = _book_verdict(drawdown_pct)
    return {"token": str(r.required_response),
            "reason_token": str(r.drawdown_tier),
            "text": list(r.violations)[:2]}


def _emit_kill(drawdown_pct: Optional[float]) -> Dict[str, Any]:
    from spa_core.governance.kill_switch import classify_drawdown_pct
    tier, why = classify_drawdown_pct(drawdown_pct)
    return {"token": str(tier), "text": [str(why)]}


def _emit_gate(target: Dict[str, float]) -> Dict[str, Any]:
    """Отпечаток двери ДОПУСКА. Ввезён у §41 — своей копии здесь нет."""
    spec = [{"protocol": k, "tier": "T1", "chain": "ethereum", "asset": "USDC"}
            for k in sorted(target)]
    return {"token": _gate_verdict(dict(target), spec, capital_usd=_capital()),
            "text": []}


def _scene_keep() -> Dict[str, Any]:
    """Книга уже оптимальна: цель равна текущей, просадки нет."""
    books = _books(_capital())
    return {
        "economics": _emit_economics(current=books["A"], target=books["A"]),
        "damper": _emit_damper([_trade(10.0, 1_000.0, SCENE_NOW)],
                               current=books["A"], target=books["A"]),
        "book": _emit_book(_DD_CALM_PCT),
        "kill": _emit_kill(_DD_CALM_PCT),
    }


def _scene_rebalance() -> Dict[str, Any]:
    books = _books(_capital())
    return {
        "economics": _emit_economics(current=books["A"], target=books["B"]),
        "damper": _emit_damper([_trade(10.0, 1_000.0, SCENE_NOW)]),
        "gate": _emit_gate(books["B"]),
    }


def _scene_defer() -> Dict[str, Any]:
    """«Решить позже»: данные о цели не предъявлены (fail-CLOSED, инв. #2).

    Это ровно тот случай, для которого тип ``DEFER`` и назван: решение не
    «держим», а «пока не на чем решать». Сцена построена ЧЕРЕЗ отсутствие
    доказанной ставки, а не через слово в коде.
    """
    books = _books(_capital())
    return {
        "economics": _emit_economics(current=books["A"], target=books["B"],
                                     evidenced=set()),
        "damper": _emit_damper([]),
        "kill": _emit_kill(None),
    }


def _scene_reduce_risk() -> Dict[str, Any]:
    return {"book": _emit_book(_DD_SOFT_PCT), "kill": _emit_kill(_DD_SOFT_PCT)}


def _scene_emergency_exit() -> Dict[str, Any]:
    return {"book": _emit_book(_DD_HARD_PCT), "kill": _emit_kill(_DD_HARD_PCT)}


def _scene_require_owner_approval() -> Dict[str, Any]:
    """Ход такого размера, что решать его обязан владелец (предмет №1).

    ``_OWNER_SCALE_FRACTION`` капитала заведомо выше потолка одного хода и
    абсолютного потолка суммы (§41 измерил оба BINDING), то есть сцена
    достижима: дверь ОТКАЖЕТ. Предмет §24 — каким ТОКЕНОМ она об этом скажет.
    """
    books = _books(_capital())
    target = {"pendle": _OWNER_SCALE_FRACTION * _capital()}
    return {
        "economics": _emit_economics(current=books["A"], target=target),
        "damper": _emit_damper([_trade(10.0, 1_000.0, SCENE_NOW)],
                               target=target),
        "gate": _emit_gate(target),
    }


#: Тип владельца → сцена, в которой ожидается ИМЕННО он. Карта объявлена: тип
#: без сцены есть «не измерено», а не ноль.
EXPECTATION_SCENES: Dict[str, Callable[[], Dict[str, Any]]] = {
    "KEEP": _scene_keep,
    "REBALANCE": _scene_rebalance,
    "DEFER": _scene_defer,
    "REDUCE_RISK": _scene_reduce_risk,
    "EMERGENCY_EXIT": _scene_emergency_exit,
    "REQUIRE_OWNER_APPROVAL": _scene_require_owner_approval,
}

#: Почему сцена именно такая. Печатается рядом с вердиктом: сцена без
#: объявленного основания позволяет подогнать ожидание под результат.
SCENE_GROUNDS: Dict[str, str] = {
    "KEEP": "цель равна текущей книге, просадка 1 % — менять нечего",
    "REBALANCE": "здоровый ход в вдвое лучший пул, срок удержания выдержан",
    "DEFER": ("ставка цели НЕ ПРЕДЪЯВЛЕНА (фид молчит) и просадка НЕ "
              "ИЗМЕРЕНА — решать не на чем, а не «держим»"),
    "REDUCE_RISK": "просадка 7 % — полоса SOFT лестницы владельца [5 %, 10 %)",
    "EMERGENCY_EXIT": "просадка 12 % — полоса HARD лестницы владельца (≥ 10 %)",
    "REQUIRE_OWNER_APPROVAL": (
        "ход на 85 % капитала — выше потолка одного хода и абсолютного потолка "
        "суммы; это предмет №1 границы владельца"),
}


# ───────────────────────────── контроль ─────────────────────────────────────

def _control_24() -> Tuple[bool, str, Dict[str, Any]]:
    """Два условия, без которых счёт читать нельзя.

    (1) ЗДОРОВАЯ сцена даёт типизированный ответ у обеих ввезённых дверей —
    это условие §22, и оно ввозится, а не переписывается;
    (2) хоть один токен МЕНЯЕТСЯ между двумя сценами. Без второго условия
    «собранный домен» мог бы оказаться артефактом сломанной сцены: дверь,
    отвечающая одно и то же на любой вход, выглядит точно так же.
    """
    if _VOCAB_ERRORS:
        return False, "словари/сцены НЕ ВВЕЗЕНЫ: {}".format(
            "; ".join(_VOCAB_ERRORS)), {}
    ok, why, baseline = _control()
    if not ok:
        return False, "контроль §22 не прошёл: {}".format(why), baseline
    try:
        with _quiet():
            calm = _emit_kill(_DD_CALM_PCT)["token"]
            hard = _emit_kill(_DD_HARD_PCT)["token"]
            keep = _scene_keep()["economics"]["token"]
            move = _scene_rebalance()["economics"]["token"]
    except Exception as exc:  # noqa: BLE001
        return False, "сцены §24 не построены: {}: {}".format(
            type(exc).__name__, exc), baseline
    moved = {"kill": (calm, hard), "economics": (keep, move)}
    if calm == hard and keep == move:
        return False, ("ни один токен не меняется между сценами ({}) — "
                       "собранный домен был бы артефактом сломанной сцены"
                       .format(moved)), baseline
    base = dict(baseline)
    base["kill"] = "{} → {}".format(calm, hard)
    base["economics"] = "{} → {}".format(keep, move)
    return True, "", base


# ─────────────────────────── ось C: форма результата ────────────────────────

def _result_form(door: str, samples: Sequence[Dict[str, Any]],
                 domains: Dict[str, List[str]]) -> Tuple[str, str]:
    """Форма результата двери — второе требование §24.

    🪤 СУДИТСЯ ВЕСЬ НАБОР СЦЕН, А НЕ ПЕРВАЯ ИЗ НИХ. Первая редакция брала
    первую сцену, в которой дверь участвовала, — и вторая дверь политики
    получала ``typed_only`` только потому, что в сцене ``KEEP`` список
    нарушений пуст: вердикт о ФОРМЕ зависел от ПОРЯДКА сцен в карте. Названо в
    ADR-967 как моя ошибка замера. Свободный текст есть у двери, если он есть
    ХОТЬ В ОДНОЙ сцене: «иногда только текст» формой «только тип» не является.
    """
    tokens = [s.get("token") for s in samples if s.get("token") is not None]
    if not tokens:
        return UNMEASURED, "дверь не вернула вердикта — форму мерить нечем"
    text = [str(t) for s in samples for t in (s.get("text") or [])
            if str(t).strip()]
    if door == "gate":
        return "boolean_not_a_type", (
            "машинно-читаемый результат двери допуска — ЛОГИЧЕСКОЕ `approved` "
            "плюс урезанная книга в долларах; домена из двух исходов «да/нет» "
            "достаточно для допуска и НЕ достаточно для §24, где типов шесть")
    declared = domains.get(door) or []
    tail = ("; свободный текст рядом ЕСТЬ ({} строк(и) на {} сценах)".format(
        len(text), len(samples)) if text else "; свободного текста нет")
    if not declared:
        return "typed_but_domain_undeclared", (
            "токены {} выдаются ЛИТЕРАЛАМИ: домен-константы у двери не "
            "объявлено ни одной, то есть перечислимость её результата нигде не "
            "записана{}".format(sorted(set(map(str, tokens))), tail))
    return ("typed_plus_text" if text else "typed_only"), (
        "домен объявлен константами ({}), выданы {}{}".format(
            ", ".join(declared), sorted(set(map(str, tokens))), tail))


# ───────────────────────────── сборка отчёта ────────────────────────────────

def _presence(owner_type: str, domains: Dict[str, List[str]],
              emitted_everywhere: Dict[str, List[str]]) -> Dict[str, Any]:
    """Ось A по одному типу владельца."""
    declared_in = sorted(d for d, toks in domains.items() if owner_type in toks)
    if declared_in:
        return {"kind": "in_declared_domain", "doors": declared_in,
                "why": "токен объявлен домен-константой двери: {}".format(
                    ", ".join(declared_in))}
    emitted_in = sorted(d for d, toks in emitted_everywhere.items()
                        if owner_type in toks)
    if emitted_in:
        return {"kind": "emitted_only", "doors": emitted_in,
                "why": ("токен константой не объявлен, но ВЫДАН дверью {} — "
                        "литерал в коде".format(", ".join(emitted_in)))}
    return {"kind": "absent_from_every_door", "doors": [],
            "why": ("ни одна дверь решения не объявляет и не выдаёт этот "
                    "токен; домены дверей: {}".format(
                        json.dumps(domains, ensure_ascii=False)))}


def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Замер §24. Живой ``data/`` не читается и не пишется."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    control_ok, control_why, baseline = _control_24()

    # Сцены строятся ДО чтения доменов намеренно: правило принадлежности
    # константы домену опирается на ВЫДАННЫЕ токены (см. `_declared_domains`).
    scenes: Dict[str, Any] = {}
    emitted_everywhere: Dict[str, List[str]] = {d: [] for d in DOORS_24}
    if control_ok:
        for owner_type, build in EXPECTATION_SCENES.items():
            try:
                with _quiet():
                    scenes[owner_type] = build()
            except Exception as exc:  # noqa: BLE001 — упавшая сцена = НЕ ИЗМЕРЕНО
                scenes[owner_type] = {"_error": "{}: {}".format(
                    type(exc).__name__, exc)}
                continue
            for door, got in scenes[owner_type].items():
                tok = (got or {}).get("token")
                if tok is not None and tok not in emitted_everywhere.get(door, []):
                    emitted_everywhere.setdefault(door, []).append(str(tok))
    domains, domain_why = _declared_domains(emitted_everywhere)

    rows: List[Dict[str, Any]] = []
    for owner_type in OWNER_DECISION_TYPES:
        entry: Dict[str, Any] = {"type": owner_type,
                                 "scene_ground": SCENE_GROUNDS[owner_type]}
        if not control_ok:
            entry["presence"] = {"kind": UNMEASURED, "doors": [],
                                 "why": control_why}
            entry["expectation"] = {"kind": UNMEASURED, "why": control_why}
            rows.append(entry)
            continue

        entry["presence"] = _presence(owner_type, domains, emitted_everywhere)

        scene = scenes.get(owner_type) or {}
        if "_error" in scene:
            entry["expectation"] = {
                "kind": UNMEASURED,
                "why": "сцена не построена: {}".format(scene["_error"])}
            rows.append(entry)
            continue
        if not scene:
            entry["expectation"] = {
                "kind": "unreachable_by_construction",
                "why": "сцены для этого типа не объявлено"}
            rows.append(entry)
            continue

        got = {door: (v or {}).get("token") for door, v in scene.items()}
        hit = sorted(d for d, tok in got.items() if tok == owner_type)
        if hit:
            entry["expectation"] = {
                "kind": "expected_type_emitted", "doors": hit,
                "emitted": got,
                "why": "дверь {} выдала РОВНО токен владельца".format(
                    ", ".join(hit))}
        elif any(tok is not None for tok in got.values()):
            entry["expectation"] = {
                "kind": "foreign_token_emitted", "emitted": got,
                "why": ("двери ответили, но токенами ВНЕ словаря владельца: "
                        "{} — и перевести их в «{}» по сходству смысла прибор "
                        "не вправе: §24 такого утверждения не делает, а "
                        "проверить его нечем".format(
                            json.dumps(got, ensure_ascii=False), owner_type))}
        else:
            entry["expectation"] = {
                "kind": "no_typed_answer", "emitted": got,
                "why": "ни одна дверь не дала типизированного ответа"}
        entry["free_text"] = {door: (v or {}).get("text")
                              for door, v in scene.items()}
        rows.append(entry)

    forms: Dict[str, Any] = {}
    for door in DOORS_24:
        samples = [scene[door] for owner_type in OWNER_DECISION_TYPES
                   for scene in [scenes.get(owner_type) or {}]
                   if isinstance(scene.get(door), dict)]
        if not samples:
            forms[door] = {"kind": UNMEASURED,
                           "why": ("ни одна сцена не вызвала эту дверь — "
                                   "форму результата мерить нечем"
                                   if control_ok else control_why)}
            continue
        kind, why = _result_form(door, samples, domains)
        forms[door] = {"kind": kind, "why": why,
                       "declared_domain": domains.get(door) or [],
                       "emitted_on_scenes": sorted(
                           emitted_everywhere.get(door) or [])}

    presence_tally = {k: sum(1 for r in rows
                             if (r.get("presence") or {}).get("kind") == k)
                      for k in PRESENCE_KINDS}
    expectation_tally = {k: sum(1 for r in rows
                                if (r.get("expectation") or {}).get("kind") == k)
                         for k in EXPECTATION_KINDS}
    form_tally = {k: sum(1 for v in forms.values() if v.get("kind") == k)
                  for k in RESULT_FORM_KINDS}

    return {
        "section": "§24 Decision types",
        "owner_criterion": (
            "§24 ТЗ «Portfolio CIO»: результат обязан быть строго типизирован "
            "— KEEP · REBALANCE · DEFER · REDUCE_RISK · EMERGENCY_EXIT · "
            "REQUIRE_OWNER_APPROVAL; свободный текст не смеет быть "
            "ЕДИНСТВЕННЫМ machine-readable результатом"),
        "types_declared": OWNER_TYPES_DECLARED,
        "order_g955_named": ORDER_G955_NAMED,
        "order_undercount": OWNER_TYPES_DECLARED - ORDER_G955_NAMED,
        "surfaces": list(SURFACES_24),
        "doors_probed": list(DOORS_24),
        "surfaces_without_a_typed_door": dict(SURFACES_WITHOUT_A_TYPED_DOOR),
        # Род журнальной ячейки `type` ДЕЛЕГИРОВАН §20 и здесь не перемеривается:
        # ввезённая шкала ПЕЧАТАЕТСЯ, то есть у ввоза есть читатель, а у читателя
        # — повод не заводить второй шкалы об одном предмете.
        "journal_slot_scale_delegated_to_20": list(SLOT_KINDS),
        "near_miss_not_a_door": dict(NEAR_MISS_NOT_A_DOOR),
        "scenes_imported_from": (
            "spa_core/analytics/anti_churn_census.py (§22) → "
            "spa_core/monitoring/cio_auto_execution_limits.py (§41); "
            "SLOT_KINDS §20, UNMEASURED §13"),
        "control": {"passed": control_ok, "reason": control_why,
                    "healthy_baseline": baseline},
        "declared_domains": domains,
        "declared_domains_unreadable": domain_why,
        "emitted_on_scenes": {d: sorted(v) for d, v in emitted_everywhere.items()},
        "types": rows,
        "result_forms": forms,
        "tally": {"presence": presence_tally, "expectation": expectation_tally,
                  "result_form": form_tally},
        "vocab_errors": list(_VOCAB_ERRORS),
        "not_claimed": [
            "ПРАВИЛЬНОСТЬ вердикта не судится: предмет §24 — РОД результата, "
            "а не его содержание",
            "ДОХОДИТ ли токен до потребителя — другой вопрос, здесь он не "
            "задаётся, и нулём его отсутствие не считается",
            "«токена нет» ≠ «исход недостижим»: остановить покупки и уйти в "
            "кэш система умеет, §24 спрашивает, НАЗЫВАЕТ ли она это типом",
            "перевод чужого токена в слово владельца НЕ делается: ось B "
            "печатает выданное дословно",
        ],
        "advisory": ("прибор только ЧИТАЕТ: ни один порог не изменён, ни один "
                     "недостающий тип не построен — завести словарь решений на "
                     "пути денег это money-path и предмет №1 владельца "
                     "(ADR-285), а REQUIRE_OWNER_APPROVAL сверх того задевает "
                     "предмет №2"),
        "root": str(root),
    }


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §24 исполняется · 1 — находка названа · 2 — НЕ ИЗМЕРЕНО."""
    if report.get("vocab_errors") or not report.get("control", {}).get("passed"):
        return 2
    tally = report.get("tally") or {}
    if (tally.get("presence") or {}).get(UNMEASURED):
        return 2
    if (tally.get("expectation") or {}).get(UNMEASURED):
        return 2
    if (tally.get("result_form") or {}).get(UNMEASURED):
        return 2
    if report.get("declared_domains_unreadable"):
        return 2
    pres = tally.get("presence") or {}
    exp = tally.get("expectation") or {}
    form = tally.get("result_form") or {}
    if pres.get("absent_from_every_door"):
        return 1
    if exp.get("foreign_token_emitted") or exp.get("no_typed_answer"):
        return 1
    if (form.get("text_only") or form.get("boolean_not_a_type")
            or form.get("typed_but_domain_undeclared")):
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    L: List[str] = ["§24 ТЗ «Portfolio CIO»: Decision types", "=" * 72]
    ctl = report["control"]
    L.append("контроль: {} {}".format(
        "ПРОШЁЛ" if ctl["passed"] else "НЕ ПРОШЁЛ", ctl["reason"]))
    L.append("  здоровая сцена: {}".format(json.dumps(
        ctl["healthy_baseline"], ensure_ascii=False)))
    L.append("сцены и словари ввезены из: {}".format(
        report["scenes_imported_from"]))
    L.append("типов в ТЗ: {} · заказ G955 назвал: {} · ПОТЕРЯНО заказом: {}"
             .format(report["types_declared"], report["order_g955_named"],
                     report["order_undercount"]))
    L.append("поверхностей §24: {} · дверей с вердиктом: {}".format(
        len(report["surfaces"]), len(report["doors_probed"])))
    for surface, why in sorted(report["surfaces_without_a_typed_door"].items()):
        L.append("  ⊘ поверхность «{}» типизированной двери НЕ ИМЕЕТ: {}"
                 .format(surface, why))
    L.append("")
    L.append("ОБЪЯВЛЕННЫЕ ДОМЕНЫ ДВЕРЕЙ (интроспекция модулей, не перечень):")
    for door in report["doors_probed"]:
        L.append("  {:<10} объявлено {} · выдано на сценах {}".format(
            door,
            json.dumps(report["declared_domains"].get(door) or [],
                       ensure_ascii=False) or "—",
            json.dumps(report["emitted_on_scenes"].get(door) or [],
                       ensure_ascii=False)))
    for why in report.get("declared_domains_unreadable") or []:
        L.append("  ⚠️ НЕ ИЗМЕРЕНО: {}".format(why))
    L.append("")
    L.append("ШЕСТЬ ТИПОВ ВЛАДЕЛЬЦА — объявлен ли токен, и что выдано на сцене:")
    for r in report["types"]:
        pres = r.get("presence") or {}
        exp = r.get("expectation") or {}
        L.append("  {:<24} A:{:<24} B:{}".format(
            r["type"], pres.get("kind"), exp.get("kind")))
        L.append("      сцена: {}".format(r.get("scene_ground")))
        L.append("      A — {}".format(pres.get("why") or ""))
        L.append("      B — {}".format(exp.get("why") or ""))
    t = report["tally"]
    L.append("")
    L.append("  ИТОГ ось A (объявлен ли токен): объявлен доменом {} · выдан "
             "литералом {} · НЕТ НИ У ОДНОЙ ДВЕРИ {} · НЕ ИЗМЕРЕНО {}".format(
                 t["presence"].get("in_declared_domain", 0),
                 t["presence"].get("emitted_only", 0),
                 t["presence"].get("absent_from_every_door", 0),
                 t["presence"].get(UNMEASURED, 0)))
    L.append("  ИТОГ ось B (что выдано на сцене ожидания): выдан ОЖИДАЕМЫЙ {} · "
             "выдан ЧУЖОЙ {} · типизированного ответа НЕТ {} · сцена "
             "недостижима {} · НЕ ИЗМЕРЕНО {}".format(
                 t["expectation"].get("expected_type_emitted", 0),
                 t["expectation"].get("foreign_token_emitted", 0),
                 t["expectation"].get("no_typed_answer", 0),
                 t["expectation"].get("unreachable_by_construction", 0),
                 t["expectation"].get(UNMEASURED, 0)))
    L.append("")
    L.append("ОСЬ C — ФОРМА РЕЗУЛЬТАТА (второе требование §24, про ДВЕРИ):")
    for door in report["doors_probed"]:
        f = report["result_forms"].get(door) or {}
        L.append("  {:<10} {}".format(door, f.get("kind")))
        L.append("      {}".format(f.get("why") or ""))
    L.append("  ИТОГ ось C: тип+текст {} · только тип {} · ТОКЕН БЕЗ "
             "ОБЪЯВЛЕННОГО ДОМЕНА {} · ТОЛЬКО ТЕКСТ {} · ЛОГИЧЕСКОЕ вместо "
             "типа {} · НЕ ИЗМЕРЕНО {}".format(
                 t["result_form"].get("typed_plus_text", 0),
                 t["result_form"].get("typed_only", 0),
                 t["result_form"].get("typed_but_domain_undeclared", 0),
                 t["result_form"].get("text_only", 0),
                 t["result_form"].get("boolean_not_a_type", 0),
                 t["result_form"].get(UNMEASURED, 0)))
    L.append("")
    L.append("БЛИЗКИЕ СОВПАДЕНИЯ, НЕ ЯВЛЯЮЩИЕСЯ ДВЕРЬЮ РЕШЕНИЯ:")
    for place, why in sorted(report["near_miss_not_a_door"].items()):
        L.append("  • {} — {}".format(place, why))
    L.append("")
    for line in report.get("not_claimed") or []:
        L.append("ℹ ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ: {}".format(line))
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for x in report["vocab_errors"]:
            L.append("    {}".format(x))
    code = verdict_code(report)
    L.append({0: "✅ §24 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§24 Decision types").splitlines()[0])
    ap.add_argument("--root", type=Path, default=None,
                    help="корень дерева (умолчание — дерево этого файла)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = census(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
