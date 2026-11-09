"""decision_payload_census.py — §25 ТЗ «Portfolio CIO»: Decision payload.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §25 «Decision payload»::

    Для каждого решения сохранять:
    timestamp · current allocation · target allocation ·
    recommended actionable allocation · source · destination · amount ·
    portfolio percentage · source expected APY · destination displayed APY ·
    destination conservative APY · destination marginal APY ·
    expected portfolio APY before · expected portfolio APY after ·
    gross incremental profit · transaction cost · expected net profit ·
    break-even · expected holding period · risk change ·
    concentration change · confidence · decision type · decision reason ·
    rejected alternatives · policy checks · data freshness · decision expiry

🪤 ЧИСЛО ПОЛЕЙ СНЯТО ПРИБОРОМ, А НЕ ГЛАЗАМИ — И ПЕРВЫЙ СЧЁТ БЫЛ НЕВЕРЕН
======================================================================
Наивный счёт по тексту ТЗ даёт **29**, и двадцать девятым в перечень попадает
ЗАГОЛОВОК СЛЕДУЮЩЕГО РАЗДЕЛА («26. Determinism»): фильтр, отбрасывающий строку
``25. ``, строку ``26. `` не отбрасывает. Верное число — **28**, и оно получено
не вычитанием единицы из памяти, а ГРАНИЦЕЙ: перечень кончается строкой ПЕРЕД
заголовком следующего раздела, и обе границы названы константами
(:data:`SECTION_HEAD`, :data:`NEXT_SECTION_HEAD`).

Поэтому число живёт ДВАЖДЫ и обязано совпасть:

* :data:`OWNER_FIELDS_DECLARED` — константа (28);
* :func:`owner_fields_from_card` — РАЗБОР карточки приказа, то есть
  ПРОИЗВОДИТЕЛЬ числа.

Расхождение краснеет тестом. Это ровно урок ADR-913/ADR-919: сторож, сравнивающий
свои константы САМ С СОБОЙ, не мерит ничего — мерка обязана стоять в ПАРИТЕТЕ с
производителем. Карточка нечитаема ⇒ ТРЕТИЙ ИСХОД (``unmeasured`` с названной
причиной), а не молчаливый возврат к константе.

Носителей записи решения ЧЕТЫРЕ, и «главного» среди них нет
===========================================================
Заказ G956 п. 1 назвал ТРИ носителя; замер нашёл ЧЕТВЁРТЫЙ, и расширение
названо, а не подставлено молча (:data:`CARRIERS_25`, :data:`CARRIER_EXTENSION`):

``shadow``
    ``data/allocation_rationale_history.jsonl`` — писатель
    :func:`spa_core.paper_trading.allocation_rationale.build_history_record`;
``journal``
    ``data/trades.json`` — писатель ``spa_core/paper_trading/cycle_runner.py``
    (литеральный словарь у ``trades.append``);
``sqlite``
    таблица ``agent_decisions`` — писатель
    :class:`spa_core.agents.decision_logger.DecisionLogger`;
``trail`` *(четвёртый, найден замером)*
    ``data/audit_trail.jsonl`` — писатель
    :func:`spa_core.audit.audit_trail.record_event`.

Выбрать ОДИН «главный» носитель по удобству значило бы ответить верно про него и
мимо про §25: владелец спрашивает, сохраняется ли поле ДЛЯ КАЖДОГО РЕШЕНИЯ, а не
«есть ли у нас хоть один файл с этим словом». Словари носителей РАЗНЫЕ, и
расхождение названо отчётом.

Осей ДВЕ, и они отвечают на разные вопросы
==========================================
ось A — ОБЪЯВЛЕНИЕ У ПИСАТЕЛЯ (:data:`PRESENCE_KINDS`)
    Существует ли поле у писателя ВООБЩЕ. Меряется интроспекцией писателя —
    построенной записью (``shadow``, ``sqlite``, конверт ``trail``) либо AST
    литерального словаря в месте записи (``journal``, полезная нагрузка
    ``trail``). **Грепом по слову НЕ меряется ни один носитель:** слово в дереве
    встречается у калькуляторов и приборов, которые записи решения не пишут
    (:data:`NEAR_MISS_NOT_THE_FIELD`).
ось B — ЧТО ОКАЗАЛОСЬ В ЗАПИСИ (:data:`RECORD_KINDS`)
    ДИФФЕРЕНЦИАЛЬНО: по НАСТОЯЩИМ записям носителя (``--data-dir``) либо по
    построенной сцене. Без этой оси «поле объявлено» верно и бесполезно.

🪤 ТРЕТИЙ ИСХОД ОСИ B ОБЯЗАТЕЛЕН: «ПОЛЕ ЕСТЬ, НО ВСЕГДА ПУСТО» ≠ «ПОЛЯ НЕТ»
==========================================================================
Требование заказа G956 п. 1 (в) и инварианта #17. Ключ, который писатель
объявил, а значение в нём ``None``/``{}``/``[]`` во ВСЕХ наблюдённых записях, —
это ``present_always_empty``, и он НЕ равен ни присутствию, ни отсутствию.
``admissible_trim`` — живой пример соседнего рода: поле добавлено ВПЕРЁД
(ADR-850), поэтому старые строки его не несут, и доля носящих печатается числом.

🪤 СООТВЕТСТВИЕ «ПОЛЕ ВЛАДЕЛЬЦА → КЛЮЧ НОСИТЕЛЯ» ОБЪЯВЛЕНО, А НЕ УГАДАНО
========================================================================
Это УТВЕРЖДЕНИЕ, и оно лежит в :data:`FIELD_MAP` с причиной у каждого поля
(:data:`MAP_REASONS`). Угадывать по сходству слов запрещено тем же правилом, что
в §24: ``protocol_key`` у ``sqlite`` — ОДИН протокол, и объявить его сразу и
``source``, и ``destination`` значило бы утверждать, что запись различает концы
хода, чего она не делает. Где утверждение не выдерживается, поле честно
``absent_from_writer``, а близкое совпадение НАЗВАНО.

🪤 ДВА ПОЛЯ §25 ДЕЛЕГИРОВАНЫ ПО СЛОВУ ВЛАДЕЛЬЦА И ЗДЕСЬ НЕ МЕРЯТСЯ
==================================================================
:data:`DELEGATED_FIELDS` — ``decision type`` (§24, ADR-967) и ``decision expiry``
(§22, ADR-965). У обоих ответ УЖЕ снят другой шкалой; мерить их второй шкалой
значило бы завести два вердикта об одном предмете, которые разойдутся. Вердикт
делегата ПЕЧАТАЕТСЯ дословно — делегирование без печати было бы умолчанием.

Чего прибор НЕ утверждает
=========================
* **Не судит, ПРАВИЛЬНОЕ ли значение в поле.** Предмет §25 — СОХРАНЕНО ли поле.
* **Не судит, ЧИТАЕТ ли кто-нибудь запись.** «Поле записано» и «поле прочитано
  потребителем» — разные вопросы; второй здесь не задаётся, и нулём его
  отсутствие не считается.
* **Не строит ни одного недостающего поля и не правит ни одного порога.**
  Дописать поле в запись о деньгах — money-path и предмет №1 владельца
  (ADR-285).
* **Не перемеривает §43** (``decision_audit_trail.py``): там ДЕВЯТЬ других полей
  и другой вопрос — ВОССТАНОВИМОСТЬ прошлой перекладки. Одна шкала — одно
  измерение.

ADVISORY. Живой ``data/`` только ЧИТАЕТСЯ и только по НАЗВАННОМУ пути
(``--data-dir``); сцены строятся в одноразовом каталоге.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей и писателей. Своих копий здесь нет намеренно: ввозится РОВНО то,
# что получает читателя ниже, — ввоз без читателя есть ложное усиление.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .decision_type_census import OWNER_DECISION_TYPES, OWNER_TYPES_DECLARED
except Exception as _exc:  # pragma: no cover
    OWNER_DECISION_TYPES = ()  # type: ignore[assignment]
    OWNER_TYPES_DECLARED = 0  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§24 словарь решений: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from spa_core.paper_trading.allocation_rationale import (
        HISTORY_SCHEMA, build_history_record, history_filename,
    )
except Exception as _exc:  # pragma: no cover
    HISTORY_SCHEMA = ""
    build_history_record = None  # type: ignore[assignment]
    history_filename = None  # type: ignore[assignment]
    _VOCAB_ERRORS.append("писатель `shadow`: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from spa_core.audit.audit_trail import AUDIT_FILENAME, VALID_EVENT_TYPES
except Exception as _exc:  # pragma: no cover
    AUDIT_FILENAME = "audit_trail.jsonl"
    VALID_EVENT_TYPES = frozenset()
    _VOCAB_ERRORS.append("писатель `trail`: {}: {}".format(
        type(_exc).__name__, _exc))


#: ДВАДЦАТЬ ВОСЕМЬ полей §25, дословно и в порядке ТЗ. Ключ — машинное имя,
#: значение — формулировка владельца БЕЗ перевода.
OWNER_FIELDS_25: Tuple[Tuple[str, str], ...] = (
    ("timestamp", "timestamp"),
    ("current_allocation", "current allocation"),
    ("target_allocation", "target allocation"),
    ("recommended_actionable_allocation", "recommended actionable allocation"),
    ("source", "source"),
    ("destination", "destination"),
    ("amount", "amount"),
    ("portfolio_percentage", "portfolio percentage"),
    ("source_expected_apy", "source expected APY"),
    ("destination_displayed_apy", "destination displayed APY"),
    ("destination_conservative_apy", "destination conservative APY"),
    ("destination_marginal_apy", "destination marginal APY"),
    ("expected_portfolio_apy_before", "expected portfolio APY before"),
    ("expected_portfolio_apy_after", "expected portfolio APY after"),
    ("gross_incremental_profit", "gross incremental profit"),
    ("transaction_cost", "transaction cost"),
    ("expected_net_profit", "expected net profit"),
    ("break_even", "break-even"),
    ("expected_holding_period", "expected holding period"),
    ("risk_change", "risk change"),
    ("concentration_change", "concentration change"),
    ("confidence", "confidence"),
    ("decision_type", "decision type"),
    ("decision_reason", "decision reason"),
    ("rejected_alternatives", "rejected alternatives"),
    ("policy_checks", "policy checks"),
    ("data_freshness", "data freshness"),
    ("decision_expiry", "decision expiry"),
)

#: Число объявлено ОТДЕЛЬНОЙ константой намеренно — см. ловушку в docstring.
#: Сверяется с РАЗБОРОМ карточки приказа, а не с самим собой.
OWNER_FIELDS_DECLARED: int = 28

#: Сколько полей назвал заказ G956 п. 1 ПОСЛЕ своей же поправки.
ORDER_G956_NAMED: int = 28

#: Сколько даёт НАИВНЫЙ счёт (заголовок следующего раздела попадает в перечень).
#: Хранится рядом, чтобы «я знаю про эту ловушку» было ИЗМЕРЕНО отчётом.
ORDER_G956_NAIVE: int = 29

#: Карточка приказа — ДОМ перечня. Своей копии текста ТЗ здесь нет.
CARD_REL: str = ("nimbalyst-local/tracker/"
                 "inbox-task-portfolio-cio-dynamic-capital-alloc.md")

#: Границы раздела. Обе названы: перечень кончается строкой ПЕРЕД заголовком
#: следующего раздела, и именно это отличает 28 от 29.
SECTION_HEAD: str = "25. Decision payload"
NEXT_SECTION_HEAD: str = "26. Determinism"

#: Строки раздела, перечнем полей НЕ являющиеся.
_SECTION_NOISE: Tuple[str, ...] = ("⸻", "Для каждого решения сохранять:")

#: Носители записи решения. Порядок — порядок разбора, не важности.
CARRIERS_25: Tuple[str, ...] = ("shadow", "journal", "sqlite", "trail")

#: Какой носитель заказ G956 НЕ называл, и почему он здесь. Расширение
#: ОБЪЯВЛЕНО: носитель, молча добавленный в перечень, читался бы как заказанный.
CARRIER_EXTENSION: Dict[str, str] = {
    "trail": (
        "`data/audit_trail.jsonl` (писатель `spa_core/audit/audit_trail.py`) — "
        "заказ G956 п. 1 назвал ТРИ носителя, этот найден замером: он пишет "
        "событие на КАЖДЫЙ цикл (1886 записей на живом треке), включая "
        "`allocation_proposal` и `risk_verdict`, то есть ровно те предметы, о "
        "которых §25 спрашивает. Умолчать о нём значило бы ответить про три "
        "носителя и выдать это за ответ про систему"),
}

#: Как у каждого носителя МЕРЯЕТСЯ ось A. Печатается: способ измерения есть
#: часть утверждения, и носитель, чей способ не назван, читался бы как
#: измеренный тем же способом, что соседний.
CARRIER_PROBE: Dict[str, str] = {
    "shadow": ("ПОСТРОЕННАЯ ЗАПИСЬ: зовётся сам писатель "
               "`allocation_rationale.build_history_record` на литеральной "
               "сцене, словарь — ключи возвращённой записи (включая вложенные)"),
    "journal": ("AST литерального словаря у `trades.append(` в "
                "`spa_core/paper_trading/cycle_runner.py` — запись строится "
                "внутри дневного цикла, и поднимать цикл ради словаря было бы "
                "запуском денежного пути ради вопроса о словаре"),
    "sqlite": ("ПОСТРОЕННАЯ ЗАПИСЬ: `DecisionLogger.log_allocate` пишет строку "
               "в ОДНОРАЗОВУЮ базу, словарь — `PRAGMA table_info` плюс ключи "
               "`data_snapshot`"),
    "trail": ("КОНВЕРТ — ключи реальной записи `record_event`; ПОЛЕЗНАЯ "
              "НАГРУЗКА — AST словарей в местах зова `record_event` внутри "
              "`cycle_runner.py`, по типу события"),
}

#: Где у носителя живёт артефакт для оси B. ``None`` — артефакта нет, ось B
#: меряется построенной сценой, и это НАЗВАНО.
CARRIER_ARTIFACT: Dict[str, Optional[str]] = {
    "shadow": "allocation_rationale_history.jsonl",
    "journal": "trades.json",
    "sqlite": None,
    "trail": "audit_trail.jsonl",
}

#: Ось A — объявлено ли поле у писателя.
PRESENCE_KINDS: Tuple[str, ...] = (
    # ключ объявленного соответствия существует у писателя
    "in_writer_vocabulary",
    # у писателя такого ключа нет вовсе
    "absent_from_writer",
    # ответ снят ДРУГОЙ шкалой (§24/§22) и здесь не перемеривается
    "delegated",
    UNMEASURED,
)

#: Ось B — что оказалось в НАСТОЯЩЕЙ записи.
RECORD_KINDS: Tuple[str, ...] = (
    # ключ есть и хотя бы в одной записи несёт непустое значение
    "present_with_value",
    # ключ объявлен, но во ВСЕХ наблюдённых записях пуст (None/{}/[]/"")
    "present_always_empty",
    # ключа нет ни в одной записи
    "absent_from_record",
    # ответ снят другой шкалой
    "delegated",
    UNMEASURED,
)

#: Ось живого артефакта носителя `sqlite` — отдельный вопрос, см.
#: :func:`sqlite_live_artifact`. Шкала ОБЪЯВЛЕНА, а не выведена из сравнений.
LIVE_ARTIFACT_KINDS: Tuple[str, ...] = (
    "table_present",
    "table_absent_from_every_database",
    "no_database_at_all",
    UNMEASURED,
)

#: Сводный вердикт по полю — ПО ВСЕМ носителям сразу.
FIELD_VERDICT_KINDS: Tuple[str, ...] = (
    # хотя бы один носитель поле СОХРАНЯЕТ со значением
    "carried_with_value",
    # поле объявлено хоть одним носителем, но значения не несёт нигде
    "declared_but_never_filled",
    # ни один носитель поля не имеет
    "absent_from_every_carrier",
    # делегировано другой секции
    "delegated_to_another_section",
    UNMEASURED,
)

#: Делегированные поля: шкала → раздел, решение, вердикт делегата ДОСЛОВНО.
DELEGATED_FIELDS: Dict[str, Dict[str, str]] = {
    "decision_type": {
        "section": "§24 Decision types",
        "adr": "ADR-967",
        "verdict": (
            "словарь владельца (KEEP · REBALANCE · DEFER · REDUCE_RISK · "
            "EMERGENCY_EXIT · REQUIRE_OWNER_APPROVAL) не реализован НИ НА "
            "ОДНОЙ двери решения: 6 из 6 `absent_from_every_door`; двери "
            "отвечают своими токенами (ACT/HOLD, ALLOW/BLOCK, "
            "NONE/HALT_NEW/ALL_CASH), машинного «решает владелец» у пути "
            "решения нет вовсе"),
        "why_not_remeasured": (
            "ячейка рода у носителей ЕСТЬ (`verdict`/`type`/`decision_type`/"
            "`event_type`), и объявить поле «сохранённым» значило бы выдать "
            "ответ, ПРОТИВОПОЛОЖНЫЙ §24, о том же предмете. Предмет §24 — "
            "ДОМЕН рода, и он измерен; второй шкалы об одном предмете не "
            "заводится (слово заказа G956 п. 1, контрапункт 2)"),
    },
    "decision_expiry": {
        "section": "§22 Decision thresholds",
        "adr": "ADR-965",
        "verdict": ("величина `decision expiry` ОТСУТСТВУЕТ: ни одна дверь "
                    "решения срока годности вердикта не объявляет"),
        "why_not_remeasured": (
            "величина уже измерена шкалой §22 (G955 п. 5 / G956 п. 3); "
            "мерить её второй шкалой — завести два расходящихся вердикта об "
            "одном предмете"),
    },
}

#: ОБЪЯВЛЕННОЕ соответствие «поле владельца → ключи носителя». Пустой кортеж
#: означает УТВЕРЖДЕНИЕ «у этого носителя такого поля нет», а не «не смотрели».
#: Путь у `trail` имеет вид ``<тип события>:<точечный путь>``; ``*`` — конверт.
FIELD_MAP: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "timestamp": {
        "shadow": ("generated_at", "cycle_date"),
        "journal": ("ts",),
        "sqlite": ("timestamp",),
        "trail": ("*:timestamp",),
    },
    "current_allocation": {
        "shadow": ("current_positions",),
        "journal": ("from_allocation",),
        "sqlite": (),
        "trail": ("trade_executed:data.from_allocation",),
    },
    "target_allocation": {
        "shadow": ("target_positions",),
        "journal": ("to_allocation",),
        "sqlite": (),
        "trail": ("allocation_proposal:data.target_usd",
                  "trade_executed:data.to_allocation"),
    },
    "recommended_actionable_allocation": {
        "shadow": ("admissible_trim.target_after",),
        "journal": (),
        "sqlite": (),
        "trail": (),
    },
    "source": {
        "shadow": ("legs",),
        "journal": (),
        "sqlite": (),
        "trail": (),
    },
    "destination": {
        "shadow": ("legs",),
        "journal": (),
        "sqlite": (),
        "trail": (),
    },
    "amount": {
        "shadow": ("turnover_usd",),
        "journal": ("delta_abs",),
        "sqlite": ("amount_usd",),
        "trail": ("trade_executed:data.delta_abs",),
    },
    "portfolio_percentage": {
        "shadow": ("turnover_frac",),
        "journal": (),
        "sqlite": (),
        "trail": (),
    },
    "source_expected_apy": {
        "shadow": ("apy_evidenced_pct",),
        "journal": (),
        "sqlite": (),
        "trail": (),
    },
    "destination_displayed_apy": {
        "shadow": ("apy_evidenced_pct",),
        "journal": (),
        "sqlite": ("data_snapshot.apy",),
        "trail": (),
    },
    "destination_conservative_apy": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "destination_marginal_apy": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "expected_portfolio_apy_before": {
        "shadow": ("book_apy_pp",),
        "journal": (), "sqlite": (), "trail": (),
    },
    "expected_portfolio_apy_after": {
        "shadow": ("target_apy_pp",),
        "journal": (), "sqlite": (), "trail": (),
    },
    "gross_incremental_profit": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "transaction_cost": {
        "shadow": ("cost_usd",),
        "journal": (), "sqlite": (), "trail": (),
    },
    "expected_net_profit": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "break_even": {
        "shadow": ("payback_days",),
        "journal": (), "sqlite": (), "trail": (),
    },
    "expected_holding_period": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "risk_change": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "concentration_change": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "confidence": {
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "decision_type": {  # ДЕЛЕГИРОВАНО §24 — соответствие не объявляется
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
    "decision_reason": {
        "shadow": ("reasons",),
        "journal": ("reason",),
        "sqlite": ("reasoning",),
        "trail": ("trade_blocked:data.reason",),
    },
    "rejected_alternatives": {
        "shadow": ("gates",),
        "journal": (), "sqlite": (), "trail": (),
    },
    "policy_checks": {
        "shadow": ("gates", "admissible_trim.policy"),
        "journal": (),
        "sqlite": ("risk_check_result",),
        "trail": ("risk_verdict:data.violations", "risk_verdict:data.approved"),
    },
    "data_freshness": {
        "shadow": ("apy_as_of", "apy_unevidenced"),
        "journal": (),
        "sqlite": (),
        "trail": ("*:snapshot_id",),
    },
    "decision_expiry": {  # ДЕЛЕГИРОВАНО §22 — соответствие не объявляется
        "shadow": (), "journal": (), "sqlite": (), "trail": (),
    },
}

#: ПОЧЕМУ соответствие заявлено именно так. Причина — часть утверждения:
#: «и так понятно» причиной не является (то же правило, что у объявления класса
#: страниц в `.claude/rules/site-numbers.md`).
MAP_REASONS: Dict[str, str] = {
    "timestamp": "момент записи несут все четыре носителя своим полем времени",
    "current_allocation": (
        "раскладка ДО хода: у тени — книга, у журнала и трейла — "
        "`from_allocation`. У `sqlite` раскладки нет вовсе: строка описывает "
        "ОДИН протокол, а не портфель"),
    "target_allocation": (
        "раскладка ПОСЛЕ: у тени — `target_positions`, у журнала — "
        "`to_allocation`, у трейла — предложение `target_usd` и факт "
        "`to_allocation`"),
    "recommended_actionable_allocation": (
        "это НЕ то же, что `target allocation`: владелец различает цель и то, "
        "что допустимо сделать. Единственный носитель различия — "
        "`admissible_trim.target_after` (ADR-850): раскладка ПОСЛЕ урезания до "
        "допустимого размера. У остальных трёх различия нет ни одним полем"),
    "source": (
        "конец хода, ОТКУДА. Тень несёт `legs` — список "
        "`{protocol, direction, delta_usd}`, то есть концы названы ОТДЕЛЬНО и "
        "восстановимы. Журнал и трейл пишут ДВЕ КНИГИ целиком, а не ход: "
        "«откуда» из них выводится вычитанием, то есть записью НЕ ЯВЛЯЕТСЯ. "
        "У `sqlite` один `protocol_key`, и объявить его сразу источником и "
        "приёмником значило бы утверждать, что строка различает концы"),
    "destination": "то же `legs`, направление `increase` (см. `source`)",
    "amount": (
        "размер хода: тень — `turnover_usd`, журнал и трейл — `delta_abs` "
        "(односторонний оборот), `sqlite` — `amount_usd`"),
    "portfolio_percentage": (
        "доля ПОРТФЕЛЯ, которую двигает ход. Тень несёт `turnover_frac`. У "
        "журнала рядом лежит `capital`, но ДОЛЯ в нём не записана, а "
        "вычислимость записью не является"),
    "source_expected_apy": (
        "ставка дня по КАЖДОМУ протоколу — `apy_evidenced_pct`; ноги названы "
        "отдельно, поэтому ставка источника из записи восстановима БЕЗ "
        "обращения к внешнему файлу"),
    "destination_displayed_apy": (
        "та же карта ставок у тени; у `sqlite` — `data_snapshot.apy`, ставка "
        "протокола строки"),
    "destination_conservative_apy": (
        "«консервативная» ставка приёмника (haircut к показанной) не "
        "записывается НИ ОДНИМ носителем и в дереве не производится вовсе"),
    "destination_marginal_apy": (
        "предельная ставка на нашем размере производится ПРИБОРОМ "
        "(`spa_core/monitoring/marginal_apy_at_size`) и публикуется в сводку "
        "аналитики, но в ЗАПИСЬ РЕШЕНИЯ не попадает ни одним полем"),
    "expected_portfolio_apy_before": "`book_apy_pp` — ставка книги до хода",
    "expected_portfolio_apy_after": "`target_apy_pp` — ставка книги после хода",
    "gross_incremental_profit": (
        "ВАЛОВОЙ прирост в деньгах не записан: тень несёт `gain_pp` — прирост "
        "СТАВКИ в п.п. Это другая величина и другая единица; назвать её "
        "исполнением поля значило бы утвердить эквивалентность, которой §25 не "
        "делает"),
    "transaction_cost": "`cost_usd` — цена хода в деньгах",
    "expected_net_profit": (
        "ЧИСТАЯ прибыль (валовая минус издержки) не записана ни одним "
        "носителем; калькулятор `yield_breakeven_calculator.net_profit_usd` "
        "существует, но записи решения не пишет"),
    "break_even": "`payback_days` — срок окупаемости хода",
    "expected_holding_period": (
        "ожидаемый срок удержания не записан: `min_hold_ok` в `gates` — это "
        "ВЕРДИКТ о минимальном удержании, а не ОЖИДАЕМЫЙ срок"),
    "risk_change": (
        "изменение риска не записано ни одним носителем ни одним полем"),
    "concentration_change": (
        "изменение концентрации не записано: `violations` политики называют "
        "НАРУШЕНИЕ потолка, а не ИЗМЕНЕНИЕ концентрации"),
    "confidence": (
        "уверенность решения не записана; `minimum confidence` у двери остаётся "
        "ЛИТЕРАЛОМ (ADR-965), то есть сравнивать записанное не с чем"),
    "decision_type": "ДЕЛЕГИРОВАНО §24 (ADR-967) — см. DELEGATED_FIELDS",
    "decision_reason": "причина решения прозой есть у всех четырёх носителей",
    "rejected_alternatives": (
        "`gates` записывает, КАКОЙ критерий принял или отклонил предложение. "
        "Писатель САМ объявляет это ближайшим честным чтением «отклонённых "
        "альтернатив» и САМ оговаривает границу: триггер судит ОДНО "
        "предложение за цикл, а не набор кандидатов. Граница напечатана в "
        "`not_claimed`, а не умолчана"),
    "policy_checks": (
        "проверки политики: `gates` и `admissible_trim.policy` у тени, "
        "`risk_check_result` у `sqlite`, `approved`/`violations` у трейла"),
    "data_freshness": (
        "свежесть входов: `apy_as_of` (ADR-312 — момент наблюдения КАЖДОЙ "
        "ставки) и `apy_unevidenced` у тени; `snapshot_id` у трейла адресует "
        "снимок дня"),
    "decision_expiry": "ДЕЛЕГИРОВАНО §22 (ADR-965) — см. DELEGATED_FIELDS",
}

#: Места, где слово владельца в дереве ЕСТЬ, но записью решения они не являются.
#: Печатается: умолчать о близком совпадении значило бы оставить читателю повод
#: решить, что мы его не заметили (тот же приём, что `NEAR_MISS_NOT_A_DOOR` §24).
NEAR_MISS_NOT_THE_FIELD: Dict[str, str] = {
    "spa_core/monitoring/marginal_apy_at_size.py": (
        "производит ПРЕДЕЛЬНУЮ ставку на нашем размере и публикует лестницу в "
        "`analytics_summary.json` — но это ПРИБОР, а не запись решения: ни "
        "одно его число не попадает в запись о ходе "
        "(`destination marginal APY`)"),
    "spa_core/analytics/yield_breakeven_calculator.py": (
        "держит `net_profit_usd` и `break-even` — но считает их ПО ЗАПРОСУ и "
        "ничего не сохраняет; поле §25 спрашивает о СОХРАНЁННОМ "
        "(`expected net profit`)"),
    "spa_core/monitoring/decision_audit_trail.py": (
        "мерит ВОССТАНОВИМОСТЬ прошлой перекладки по ДЕВЯТИ полям §43 — "
        "другой перечень и другой вопрос; §25 спрашивает о СОСТАВЕ записи, а "
        "не о её достаточности для воспроизведения"),
    "spa_core/message_bus/topics.py::strategy_signal_payload": (
        "несёт `confidence` с умолчанием 0.8 — но это ПОЛЕЗНАЯ НАГРУЗКА шины "
        "сообщений советательного слоя, а не запись решения о капитале; "
        "умолчание 0.8 к тому же не измерено ничем"),
}

#: Сцена для построенной записи тени. Литералы — СЦЕНА, а не пороги системы.
_SCENE_CAPITAL: float = 100_000.0
_SCENE_DATE: str = "2026-01-01"


# ──────────────────────────── разбор перечня ТЗ ─────────────────────────────

def owner_fields_from_card(root: Path) -> Tuple[Tuple[str, ...], Dict[str, Any]]:
    """Перечень §25 ПО КАРТОЧКЕ ПРИКАЗА — производитель числа 28.

    Возвращает ``(строки перечня, мета)``. ``мета["unmeasured"]`` — причина,
    если перечень снять не удалось; тогда первый элемент ПУСТ, и вердикт обязан
    стать ``unmeasured``, а не молча опереться на :data:`OWNER_FIELDS_DECLARED`.

    Границы — :data:`SECTION_HEAD` и :data:`NEXT_SECTION_HEAD`. Именно вторая
    граница и отличает 28 от наивных 29.
    """
    card = Path(root) / CARD_REL
    meta: Dict[str, Any] = {"card": str(card), "naive_count": None}
    try:
        text = card.read_text(encoding="utf-8")
    except Exception as exc:
        meta["unmeasured"] = "карточка приказа не прочитана: {}: {}".format(
            type(exc).__name__, exc)
        return (), meta

    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip() == SECTION_HEAD)
    except StopIteration:
        meta["unmeasured"] = "заголовок «{}» в карточке не найден".format(
            SECTION_HEAD)
        return (), meta
    try:
        stop = next(i for i in range(start + 1, len(lines))
                    if lines[i].strip() == NEXT_SECTION_HEAD)
    except StopIteration:
        meta["unmeasured"] = (
            "заголовок следующего раздела «{}» не найден — ГРАНИЦЫ перечня "
            "нет, и счёт без неё даёт наивное число".format(NEXT_SECTION_HEAD))
        return (), meta

    def _clean(span: Sequence[str]) -> List[str]:
        out: List[str] = []
        for ln in span:
            s = ln.strip()
            if not s or s in _SECTION_NOISE or s == SECTION_HEAD:
                continue
            out.append(s)
        return out

    fields = _clean(lines[start:stop])
    # НАИВНЫЙ счёт — тот же разбор БЕЗ второй границы: печатается, чтобы
    # ловушка была ИЗМЕРЕНА отчётом, а не описана словами в docstring.
    meta["naive_count"] = len(_clean(lines[start:stop + 1]))
    meta["line_span"] = [start + 1, stop]
    return tuple(fields), meta


# ──────────────────────── интроспекция писателей ───────────────────────────

def _flat_paths(obj: Any, prefix: str = "") -> List[str]:
    """Точечные пути словаря, включая вложенные (листья и сами словари)."""
    out: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = "{}.{}".format(prefix, k) if prefix else str(k)
            out.append(path)
            out.extend(_flat_paths(v, path))
    return out


def _resolve(record: Any, path: str) -> Tuple[bool, Any]:
    """``(ключ существует, значение)`` по точечному пути."""
    cur = record
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _is_empty(value: Any) -> bool:
    """Пусто ли значение. ``0``/``0.0``/``False`` — НЕ пусто (инв. #17).

    Измеренный ноль есть наблюдение, и считать его отсутствием — ровно тот
    дефект, против которого написан инвариант.
    """
    if value is None:
        return True
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return len(value) == 0
    return False


def _dict_literal_keys(path: Path, attr: str, method: str) -> Tuple[
        Tuple[str, ...], Optional[str]]:
    """Ключи литерального словаря у зова ``<attr>.<method>({...})``.

    Возвращает ``(ключи, причина НЕ ИЗМЕРЕНО)``. Отдельная дверь, а не греп:
    греп по слову нашёл бы и комментарий, и соседний словарь.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (), "{} не разобран: {}: {}".format(
            path.name, type(exc).__name__, exc)
    keys: List[str] = []
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == method
                and isinstance(fn.value, ast.Name) and fn.value.id == attr):
            continue
        if not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        found = True
        for k in node.args[0].keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.append(k.value)
    if not found:
        return (), "зов `{}.{}(<словарь>)` в {} не найден".format(
            attr, method, path.name)
    return tuple(sorted(set(keys))), None


def _record_event_payload_keys(path: Path) -> Tuple[
        Dict[str, Tuple[str, ...]], Optional[str]]:
    """Ключи полезной нагрузки трейла ПО ТИПУ СОБЫТИЯ (AST мест зова)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, "{} не разобран: {}: {}".format(
            path.name, type(exc).__name__, exc)
    out: Dict[str, set] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name not in ("record_event", "_audit_record"):
            continue
        if len(node.args) < 3:
            continue
        et, payload = node.args[1], node.args[2]
        if not (isinstance(et, ast.Constant) and isinstance(et.value, str)):
            continue
        if not isinstance(payload, ast.Dict):
            continue
        bucket = out.setdefault(et.value, set())
        for k in payload.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                bucket.add(k.value)
    if not out:
        return {}, "ни одного зова `record_event` со словарём в {}".format(
            path.name)
    return {k: tuple(sorted(v)) for k, v in out.items()}, None


def _scene_shadow_doc() -> Dict[str, Any]:
    """Документ сцены для писателя тени. Все числа — литералы сцены."""
    return {
        "cycle_date": _SCENE_DATE,
        "generated_at": _SCENE_DATE + "T00:00:00+00:00",
        "params": {"policy_version": "v1.0", "mode": "shadow"},
        "decision_shadow": {
            "decision": "HOLD",
            "reasons": ["сцена переписи §25"],
            "legs": [
                {"protocol": "aave_v3", "direction": "decrease",
                 "delta_usd": -1000.0},
                {"protocol": "morpho_blue", "direction": "increase",
                 "delta_usd": 1000.0},
            ],
            "gates": {"gain_above_band": False, "min_hold_ok": True},
            "apy_now_pp": 5.0, "apy_opt_pp": 5.4, "gain_pp": 0.4,
            "required_gain_pp": 0.5, "cost_usd": 12.0, "payback_days": 40.0,
            "turnover_usd": 1000.0, "turnover_frac": 0.01, "warnings": [],
        },
        "admissible_trim": {
            "verdict": "TRIMMED_TO_ADMISSIBLE", "admissible_usd": 500.0,
            "target_before": {"aave_v3": 2000.0},
            "target_after": {"aave_v3": 1500.0, "morpho_blue": 500.0},
            "policy": {"approved": True, "violations": []},
        },
    }


def shadow_scene_record() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Построенная запись тени — зовётся САМ писатель, не копия его словаря."""
    if build_history_record is None:
        return None, "писатель тени не ввезён"
    try:
        rec = build_history_record(
            _scene_shadow_doc(),
            apy_pct={"aave_v3": 5.0, "morpho_blue": 5.4},
            apy_sources={"aave_v3": "live", "morpho_blue": "live"},
            current_positions={"aave_v3": 2000.0},
            target_positions={"aave_v3": 1000.0, "morpho_blue": 1000.0},
            capital_usd=_SCENE_CAPITAL,
            apy_as_of={"aave_v3": _SCENE_DATE + "T00:00:00Z"},
        )
    except Exception as exc:
        return None, "писатель тени отказал: {}: {}".format(
            type(exc).__name__, exc)
    return rec, None


def sqlite_scene_record() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Построенная строка ``agent_decisions`` в ОДНОРАЗОВОЙ базе.

    Зовётся настоящий :class:`DecisionLogger`: словарь, выписанный руками,
    устарел бы молча при первой же правке писателя.
    """
    try:
        from spa_core.agents.decision_logger import DecisionLogger
        from spa_core.database.init_db import get_connection, init_database
    except Exception as exc:
        return None, "писатель `sqlite` не ввезён: {}: {}".format(
            type(exc).__name__, exc)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "scene.db"
            init_database(db)
            row_id = DecisionLogger(db, "CensusScene").log_allocate(
                "aave_v3", 1000.0, 5.0, "T1", "сцена переписи §25", True)
            if row_id is None or row_id < 0:
                return None, "писатель `sqlite` вернул отказ записи"
            with get_connection(db) as conn:
                cols = [r[1] for r in
                        conn.execute("PRAGMA table_info(agent_decisions)")]
                raw = conn.execute(
                    "SELECT * FROM agent_decisions WHERE id = ?",
                    (row_id,)).fetchone()
            if raw is None:
                return None, "строка сцены в `agent_decisions` не найдена"
            rec = dict(zip(cols, list(raw)))
            snap = rec.get("data_snapshot")
            if isinstance(snap, str):
                try:
                    rec["data_snapshot"] = json.loads(snap)
                except Exception:
                    pass
            return rec, None
    except Exception as exc:
        return None, "сцена `sqlite` не построена: {}: {}".format(
            type(exc).__name__, exc)


def trail_scene_record() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Конверт реальной записи трейла в ОДНОРАЗОВОМ каталоге данных."""
    try:
        from spa_core.audit.audit_trail import begin_cycle, record_event
    except Exception as exc:
        return None, "писатель `trail` не ввезён: {}: {}".format(
            type(exc).__name__, exc)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cid = begin_cycle(_SCENE_DATE, data_dir=tmp)
            cid = cid if isinstance(cid, str) else str(cid)
            rec = record_event(cid, "risk_verdict", {"approved": True},
                               data_dir=tmp)
        if not isinstance(rec, dict) or "error" in rec:
            return None, "писатель `trail` отказал: {}".format(rec)
        return rec, None
    except Exception as exc:
        return None, "сцена `trail` не построена: {}: {}".format(
            type(exc).__name__, exc)


def writer_vocabulary(root: Path) -> Tuple[Dict[str, Any], List[str]]:
    """Словари ЧЕТЫРЁХ писателей и причины, если словарь не снят.

    Причина лежит ПРИ НОСИТЕЛЕ (``vocab[carrier]["unreadable"]``), а не только в
    общем списке: искать своё имя в чужой строке — тот же дефект, что мерить
    вердикт подстрокой (ADR-333).
    """
    unreadable: List[str] = []
    vocab: Dict[str, Any] = {c: {"paths": (), "unreadable": []}
                             for c in CARRIERS_25}

    def _fail(carrier: str, why: str) -> None:
        vocab[carrier]["unreadable"].append(why)
        unreadable.append("{}: {}".format(carrier, why))

    rec, why = shadow_scene_record()
    if why:
        _fail("shadow", why)
    else:
        vocab["shadow"]["paths"] = tuple(_flat_paths(rec or {}))
        vocab["shadow"]["record"] = rec

    runner = Path(root) / "spa_core/paper_trading/cycle_runner.py"
    keys, why = _dict_literal_keys(runner, "trades", "append")
    if why:
        _fail("journal", why)
    else:
        vocab["journal"]["paths"] = keys

    rec, why = sqlite_scene_record()
    if why:
        _fail("sqlite", why)
    else:
        vocab["sqlite"]["paths"] = tuple(_flat_paths(rec or {}))
        vocab["sqlite"]["record"] = rec

    envelope, why_env = trail_scene_record()
    if why_env:
        _fail("trail", "конверт — " + why_env)
    payloads, why_pl = _record_event_payload_keys(runner)
    if why_pl:
        _fail("trail", "нагрузка — " + why_pl)
    trail_paths: List[str] = ["*:{}".format(k) for k in sorted(envelope or {})]
    for et, keys_ in sorted(payloads.items()):
        for k in keys_:
            trail_paths.append("{}:data.{}".format(et, k))
    vocab["trail"]["paths"] = tuple(trail_paths)
    vocab["trail"]["envelope"] = envelope
    vocab["trail"]["payloads"] = payloads
    return vocab, unreadable


# ──────────────────────── наблюдение артефактов ────────────────────────────

def _read_jsonl(path: Path) -> Tuple[List[dict], Optional[str]]:
    try:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue  # нечитаемую историю не разрушаем и не судим
            if isinstance(obj, dict):
                rows.append(obj)
        return rows, None
    except Exception as exc:
        return [], "{}: {}: {}".format(path, type(exc).__name__, exc)


def observe_carrier(carrier: str, data_dir: Optional[Path]) -> Tuple[
        List[dict], str, Optional[str]]:
    """Записи носителя для оси B: ``(записи, способ, причина НЕ ИЗМЕРЕНО)``."""
    artifact = CARRIER_ARTIFACT.get(carrier)
    if artifact is None:
        # У носителя нет живого артефакта — ось B меряется ПОСТРОЕННОЙ сценой,
        # и это НАЗВАНО, а не подставлено молча.
        builder = {"sqlite": sqlite_scene_record}.get(carrier)
        if builder is None:
            return [], "none", "ни артефакта, ни сцены у носителя «{}»".format(
                carrier)
        rec, why = builder()
        if why:
            return [], "built_scene", why
        return [rec or {}], "built_scene", None
    if data_dir is None:
        return [], "observed_artifact", (
            "каталог данных не назван (`--data-dir`) — записи носителя «{}» "
            "НЕ НАБЛЮДАЛИСЬ".format(carrier))
    path = Path(data_dir) / artifact
    if not path.exists():
        return [], "observed_artifact", (
            "артефакт носителя «{}» не существует: {}".format(carrier, path))
    if artifact.endswith(".jsonl"):
        rows, why = _read_jsonl(path)
        if why:
            return [], "observed_artifact", why
        return rows, "observed_artifact", None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], "observed_artifact", "{}: {}: {}".format(
            path, type(exc).__name__, exc)
    rows = obj if isinstance(obj, list) else (obj.get("trades") or [])
    rows = [r for r in rows if isinstance(r, dict)]
    return rows, "observed_artifact", None


def sqlite_live_artifact(data_dir: Optional[Path]) -> Dict[str, Any]:
    """Существует ли таблица ``agent_decisions`` НА ЖИВОМ ТРЕКЕ.

    Отдельный вопрос, и задаётся он отдельно намеренно. Ось B у этого носителя
    меряется ПОСТРОЕННОЙ сценой, то есть отвечает «писатель умеет писать такие
    поля». Умеет — и на живом треке не написал ни одной строки: это ДРУГОЕ
    наблюдение, и выдать первое за второе значило бы объявить носитель
    работающим по его способности.

    Три исхода (инв. #17): таблица есть (с числом строк) · баз нет ни одной
    либо ни в одной базе таблицы нет · каталог не назван ⇒ НЕ ИЗМЕРЕНО.
    """
    if data_dir is None:
        return {"kind": UNMEASURED,
                "why": "каталог данных не назван (`--data-dir`)"}
    dbs = sorted(Path(data_dir).glob("*.db"))
    if not dbs:
        return {"kind": "no_database_at_all",
                "why": "в каталоге данных нет ни одного файла `*.db`",
                "databases": []}
    found: List[str] = []
    unreadable: List[str] = []
    for db in dbs:
        try:
            conn = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "agent_decisions" in names:
                    rows = conn.execute(
                        "SELECT COUNT(*) FROM agent_decisions").fetchone()[0]
                    found.append("{}: {} строк".format(db.name, rows))
            finally:
                conn.close()
        except Exception as exc:
            unreadable.append("{}: {}: {}".format(
                db.name, type(exc).__name__, exc))
    if unreadable and not found:
        return {"kind": UNMEASURED,
                "why": "базы не прочитаны: " + "; ".join(unreadable),
                "databases": [d.name for d in dbs]}
    if not found:
        return {"kind": "table_absent_from_every_database",
                "why": ("ни в одной из {} баз живого каталога нет таблицы "
                        "`agent_decisions` — писатель `sqlite` УМЕЕТ писать "
                        "поля (сцена это показала), но на живом треке не "
                        "написал ни одной строки".format(len(dbs))),
                "databases": [d.name for d in dbs]}
    return {"kind": "table_present", "why": "; ".join(found),
            "databases": [d.name for d in dbs]}


def _trail_split(path: str) -> Tuple[Optional[str], str]:
    """``"<тип события>:<путь>"`` → ``(тип или None для конверта, путь)``."""
    if ":" not in path:
        return None, path
    et, rest = path.split(":", 1)
    return (None if et == "*" else et), rest


def _axis_b(carrier: str, paths: Sequence[str], rows: Sequence[dict]) -> Dict[
        str, Any]:
    """Ось B по одному полю одного носителя."""
    if not paths:
        return {"kind": "absent_from_record",
                "why": "соответствия у носителя не объявлено"}
    if not rows:
        return {"kind": UNMEASURED, "why": "записей носителя нет"}
    seen = 0
    filled = 0
    hits: List[str] = []
    for path in paths:
        et, dotted = (_trail_split(path) if carrier == "trail"
                      else (None, path))
        scoped = [r for r in rows
                  if et is None or r.get("event_type") == et]
        if not scoped:
            continue
        present_here = 0
        filled_here = 0
        for row in scoped:
            ok, value = _resolve(row, dotted)
            if not ok:
                continue
            present_here += 1
            if not _is_empty(value):
                filled_here += 1
        if present_here:
            seen += present_here
            filled += filled_here
            hits.append("{} — ключ в {}/{} записях, непустой в {}".format(
                path, present_here, len(scoped), filled_here))
    if not seen:
        return {"kind": "absent_from_record",
                "why": "ни один объявленный путь не найден ни в одной записи",
                "paths": list(paths)}
    if not filled:
        return {"kind": "present_always_empty",
                "why": "ключ объявлен, но пуст во ВСЕХ наблюдённых записях",
                "hits": hits}
    return {"kind": "present_with_value", "why": "; ".join(hits), "hits": hits}


# ─────────────────────────── положительный контроль ─────────────────────────

def control(vocab: Dict[str, Any]) -> Tuple[bool, str]:
    """Различает ли ось B НАЛИЧИЕ значения от его отсутствия.

    Контроль дифференциальный и на НАСТОЯЩЕЙ записи: берётся построенная запись
    тени, и у неё РОВНО ОДНО поле (``cost_usd``, то есть `transaction cost`)
    сначала присутствует, потом снимается, потом обнуляется до ``None``. Три
    ответа обязаны быть РАЗНЫМИ. Проверка, никогда не видевшая отсутствия,
    украшение, а не мера (`.claude/rules/deployment.md`, «проверка сторожа
    сторожей»).
    """
    rec = (vocab.get("shadow") or {}).get("record")
    if not isinstance(rec, dict) or "cost_usd" not in rec:
        return False, ("контроль НЕ ПОСТРОЕН: в записи тени нет `cost_usd`, "
                       "то есть снимать нечего")
    paths = ("cost_usd",)
    with_value = _axis_b("shadow", paths, [rec])["kind"]
    без = {k: v for k, v in rec.items() if k != "cost_usd"}
    without_key = _axis_b("shadow", paths, [без])["kind"]
    empty = dict(rec, cost_usd=None)
    with_empty = _axis_b("shadow", paths, [empty])["kind"]
    trio = (with_value, without_key, with_empty)
    if trio != ("present_with_value", "absent_from_record",
                "present_always_empty"):
        return False, ("контроль НЕ ПРОШЁЛ: три сцены дали {} — ось B не "
                       "различает три исхода".format(list(trio)))
    # Вторая половина контроля: измеренный НОЛЬ обязан остаться наблюдением.
    zero = _axis_b("shadow", paths, [dict(rec, cost_usd=0.0)])["kind"]
    if zero != "present_with_value":
        return False, ("контроль НЕ ПРОШЁЛ: измеренный ноль прочитан как «{}» "
                       "— инвариант #17 нарушен самим прибором".format(zero))
    return True, ("ПРОШЁЛ: сцены «значение / ключа нет / пусто» дали три "
                  "РАЗНЫХ исхода, измеренный ноль остался наблюдением")


# ───────────────────────────────── перепись ─────────────────────────────────

def census(root: Optional[Path] = None,
           data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Перепись §25. Только ЧИТАЕТ; ни один порог не изменён."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = Path(data_dir) if data_dir else None

    card_fields, card_meta = owner_fields_from_card(root)
    vocab, unreadable = writer_vocabulary(root)
    control_ok, control_why = control(vocab)

    observed: Dict[str, Any] = {}
    for carrier in CARRIERS_25:
        rows, how, why = observe_carrier(carrier, data_dir)
        observed[carrier] = {"rows": len(rows), "how": how, "unmeasured": why,
                             "_rows": rows}

    rows_out: List[Dict[str, Any]] = []
    for key, verbatim in OWNER_FIELDS_25:
        delegated = DELEGATED_FIELDS.get(key)
        per_carrier: Dict[str, Any] = {}
        if delegated:
            for carrier in CARRIERS_25:
                per_carrier[carrier] = {
                    "presence": {"kind": "delegated",
                                 "why": delegated["section"]},
                    "record": {"kind": "delegated",
                               "why": delegated["section"]},
                }
            rows_out.append({
                "field": key, "owner_words": verbatim,
                "verdict": "delegated_to_another_section",
                "delegated_to": delegated["section"],
                "delegate_adr": delegated["adr"],
                "delegate_verdict": delegated["verdict"],
                "why_not_remeasured": delegated["why_not_remeasured"],
                "mapping_reason": MAP_REASONS.get(key, ""),
                "carriers": per_carrier,
            })
            continue

        for carrier in CARRIERS_25:
            paths = (FIELD_MAP.get(key) or {}).get(carrier) or ()
            declared = set((vocab.get(carrier) or {}).get("paths") or ())
            carrier_unreadable = (vocab.get(carrier) or {}).get(
                "unreadable") or []
            if carrier_unreadable:
                presence = {"kind": UNMEASURED,
                            "why": "словарь писателя «{}» не снят: {}".format(
                                carrier, "; ".join(carrier_unreadable))}
            elif not paths:
                presence = {"kind": "absent_from_writer",
                            "why": "соответствия не объявлено"}
            elif any(p in declared for p in paths):
                presence = {"kind": "in_writer_vocabulary",
                            "why": "объявлено: " + ", ".join(
                                p for p in paths if p in declared)}
            else:
                presence = {
                    "kind": "absent_from_writer",
                    "why": ("объявленный путь у писателя НЕ НАЙДЕН: "
                            + ", ".join(paths))}
            carrier_rows = observed[carrier]["_rows"]
            if observed[carrier]["unmeasured"] and paths:
                record = {"kind": UNMEASURED,
                          "why": observed[carrier]["unmeasured"]}
            else:
                record = _axis_b(carrier, paths, carrier_rows)
            per_carrier[carrier] = {"presence": presence, "record": record}

        pres_kinds = {c["presence"]["kind"] for c in per_carrier.values()}
        rec_kinds = {c["record"]["kind"] for c in per_carrier.values()}
        if "present_with_value" in rec_kinds:
            verdict = "carried_with_value"
        elif "present_always_empty" in rec_kinds:
            verdict = "declared_but_never_filled"
        elif UNMEASURED in rec_kinds or UNMEASURED in pres_kinds:
            verdict = UNMEASURED
        else:
            verdict = "absent_from_every_carrier"
        rows_out.append({
            "field": key, "owner_words": verbatim, "verdict": verdict,
            "mapping_reason": MAP_REASONS.get(key, ""),
            "carriers": per_carrier,
        })

    tally = {k: sum(1 for r in rows_out if r["verdict"] == k)
             for k in FIELD_VERDICT_KINDS}
    per_carrier_tally: Dict[str, Dict[str, int]] = {}
    for carrier in CARRIERS_25:
        per_carrier_tally[carrier] = {
            k: sum(1 for r in rows_out
                   if (r["carriers"][carrier]["record"]["kind"] == k))
            for k in RECORD_KINDS}

    for v in observed.values():
        v.pop("_rows", None)

    parsed = len(card_fields)
    return {
        "section": "§25 Decision payload",
        "owner_criterion": (
            "§25 ТЗ «Portfolio CIO»: для КАЖДОГО решения сохранять 28 "
            "названных полей"),
        "fields_declared": OWNER_FIELDS_DECLARED,
        "fields_parsed_from_card": parsed,
        "card": card_meta,
        "count_parity": (parsed == OWNER_FIELDS_DECLARED
                         if "unmeasured" not in card_meta else None),
        "order_g956_named": ORDER_G956_NAMED,
        "order_g956_naive": ORDER_G956_NAIVE,
        "order_undercount": OWNER_FIELDS_DECLARED - ORDER_G956_NAMED,
        "carriers": list(CARRIERS_25),
        "carrier_extension": dict(CARRIER_EXTENSION),
        "carrier_probe": dict(CARRIER_PROBE),
        "carrier_artifact": dict(CARRIER_ARTIFACT),
        "observed": observed,
        "sqlite_live_artifact": sqlite_live_artifact(data_dir),
        "writer_vocabulary_sizes": {
            c: len((vocab.get(c) or {}).get("paths") or ()) for c in CARRIERS_25},
        "writer_vocabulary_unreadable": unreadable,
        "delegated_fields": {k: dict(v) for k, v in DELEGATED_FIELDS.items()},
        "delegate_24_dictionary": list(OWNER_DECISION_TYPES),
        "delegate_24_types_declared": OWNER_TYPES_DECLARED,
        "shadow_schema": HISTORY_SCHEMA,
        "trail_valid_event_types": sorted(VALID_EVENT_TYPES),
        "trail_filename": AUDIT_FILENAME,
        "shadow_filename": (history_filename() if history_filename else None),
        "near_miss_not_the_field": dict(NEAR_MISS_NOT_THE_FIELD),
        "control": {"passed": control_ok, "reason": control_why},
        "fields": rows_out,
        "tally": tally,
        "tally_per_carrier": per_carrier_tally,
        "vocab_errors": list(_VOCAB_ERRORS),
        "not_claimed": [
            "ПРАВИЛЬНОСТЬ значения не судится: §25 спрашивает, СОХРАНЕНО ли "
            "поле, а не верно ли оно",
            "ЧИТАЕТ ли кто-нибудь запись — другой вопрос, здесь он не "
            "задаётся, и нулём его отсутствие не считается",
            "«отклонённые альтернативы» у тени записаны как `gates` — КАКОЙ "
            "критерий принял или отклонил ОДНО предложение цикла; набора "
            "кандидатов триггер не производит, и писатель объявляет эту "
            "границу сам",
            "§43 (`decision_audit_trail.py`) не перемеривается: там ДЕВЯТЬ "
            "других полей и вопрос о ВОССТАНОВИМОСТИ, а не о составе записи",
            "вычислимость записью НЕ ЯВЛЯЕТСЯ: `portfolio percentage` "
            "выводится из `capital`, но §25 спрашивает о СОХРАНЁННОМ",
        ],
        "advisory": ("прибор только ЧИТАЕТ: ни одно поле не дописано, ни один "
                     "порог не изменён — дописать поле в запись о деньгах это "
                     "money-path и предмет №1 владельца (ADR-285)"),
        "root": str(root),
        "data_dir": (str(data_dir) if data_dir else None),
    }


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §25 исполняется · 1 — находка названа · 2 — НЕ ИЗМЕРЕНО."""
    if report.get("vocab_errors"):
        return 2
    if not (report.get("control") or {}).get("passed"):
        return 2
    if "unmeasured" in (report.get("card") or {}):
        return 2
    if report.get("count_parity") is not True:
        return 2
    if report.get("writer_vocabulary_unreadable"):
        return 2
    tally = report.get("tally") or {}
    if tally.get(UNMEASURED):
        return 2
    live = report.get("sqlite_live_artifact") or {}
    if live.get("kind") == UNMEASURED:
        return 2
    if tally.get("absent_from_every_carrier") or tally.get(
            "declared_but_never_filled"):
        return 1
    if live.get("kind") in ("table_absent_from_every_database",
                            "no_database_at_all"):
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    L: List[str] = ["§25 ТЗ «Portfolio CIO»: Decision payload", "=" * 72]
    ctl = report["control"]
    L.append("контроль: {} {}".format(
        "ПРОШЁЛ" if ctl["passed"] else "НЕ ПРОШЁЛ", ctl["reason"]))
    card = report["card"]
    if "unmeasured" in card:
        L.append("⚠️ ПЕРЕЧЕНЬ НЕ СНЯТ: {}".format(card["unmeasured"]))
    else:
        L.append("перечень снят ПО КАРТОЧКЕ {} строки {}: полей {} · наивный "
                 "счёт (без второй границы) {} · константа {} · паритет {}"
                 .format(card["card"], card.get("line_span"),
                         report["fields_parsed_from_card"],
                         card.get("naive_count"), report["fields_declared"],
                         "ДА" if report["count_parity"] else "НЕТ"))
    L.append("заказ G956 назвал: {} · наивный счёт заказа: {} · ПОТЕРЯНО "
             "заказом: {}".format(report["order_g956_named"],
                                  report["order_g956_naive"],
                                  report["order_undercount"]))
    L.append("")
    L.append("НОСИТЕЛИ ЗАПИСИ РЕШЕНИЯ ({}):".format(len(report["carriers"])))
    for carrier in report["carriers"]:
        obs = report["observed"][carrier]
        L.append("  {:<8} артефакт {} · словарь писателя {} путей · записей "
                 "{} ({})".format(
                     carrier,
                     report["carrier_artifact"].get(carrier) or "—(сцена)",
                     report["writer_vocabulary_sizes"].get(carrier),
                     obs["rows"], obs["how"]))
        L.append("      ось A: {}".format(report["carrier_probe"][carrier]))
        if obs.get("unmeasured"):
            L.append("      ⚠️ НЕ ИЗМЕРЕНО: {}".format(obs["unmeasured"]))
    live = report.get("sqlite_live_artifact") or {}
    L.append("  ⟐ ЖИВОЙ АРТЕФАКТ носителя «sqlite»: {} — {}".format(
        live.get("kind"), live.get("why")))
    for carrier, why in sorted(report["carrier_extension"].items()):
        L.append("  ✚ РАСШИРЕНИЕ перечня заказа — «{}»: {}".format(carrier, why))
    for why in report.get("writer_vocabulary_unreadable") or []:
        L.append("  ⚠️ СЛОВАРЬ ПИСАТЕЛЯ НЕ СНЯТ: {}".format(why))
    L.append("")
    L.append("ДВАДЦАТЬ ВОСЕМЬ ПОЛЕЙ ВЛАДЕЛЬЦА:")
    for r in report["fields"]:
        L.append("  {:<34} {}".format(r["owner_words"], r["verdict"]))
        L.append("      соответствие: {}".format(r["mapping_reason"]))
        if r["verdict"] == "delegated_to_another_section":
            L.append("      ДЕЛЕГИРОВАНО {} ({}): {}".format(
                r["delegated_to"], r["delegate_adr"], r["delegate_verdict"]))
            L.append("      почему не перемеряется: {}".format(
                r["why_not_remeasured"]))
            continue
        for carrier in report["carriers"]:
            c = r["carriers"][carrier]
            L.append("      {:<8} A:{:<22} B:{:<22} {}".format(
                carrier, c["presence"]["kind"], c["record"]["kind"],
                c["record"].get("why") or ""))
    t = report["tally"]
    L.append("")
    L.append("  ИТОГ по полям: СОХРАНЯЕТСЯ со значением {} · объявлено, но "
             "НИКОГДА не заполнено {} · НЕТ НИ У ОДНОГО носителя {} · "
             "делегировано {} · НЕ ИЗМЕРЕНО {}".format(
                 t.get("carried_with_value", 0),
                 t.get("declared_but_never_filled", 0),
                 t.get("absent_from_every_carrier", 0),
                 t.get("delegated_to_another_section", 0),
                 t.get(UNMEASURED, 0)))
    L.append("  ИТОГ по носителям (ось B, из {} полей):".format(
        len(report["fields"])))
    for carrier, tt in report["tally_per_carrier"].items():
        L.append("    {:<8} значение {} · пусто всегда {} · нет в записи {} · "
                 "делегировано {} · НЕ ИЗМЕРЕНО {}".format(
                     carrier, tt.get("present_with_value", 0),
                     tt.get("present_always_empty", 0),
                     tt.get("absent_from_record", 0),
                     tt.get("delegated", 0), tt.get(UNMEASURED, 0)))
    L.append("")
    L.append("ДЕЛЕГИРОВАННЫЕ ПОЛЯ (вердикт делегата печатается дословно):")
    for key, d in sorted(report["delegated_fields"].items()):
        L.append("  • {} → {} ({}): {}".format(
            key, d["section"], d["adr"], d["verdict"]))
    L.append("  словарь §24, ввезённый и прочитанный здесь: {} ({} типов)"
             .format(", ".join(report["delegate_24_dictionary"]),
                     report["delegate_24_types_declared"]))
    L.append("")
    L.append("БЛИЗКИЕ СОВПАДЕНИЯ, НЕ ЯВЛЯЮЩИЕСЯ ЗАПИСЬЮ РЕШЕНИЯ:")
    for place, why in sorted(report["near_miss_not_the_field"].items()):
        L.append("  • {} — {}".format(place, why))
    L.append("")
    for line in report.get("not_claimed") or []:
        L.append("ℹ ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ: {}".format(line))
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for x in report["vocab_errors"]:
            L.append("    {}".format(x))
    code = verdict_code(report)
    L.append({0: "✅ §25 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§25 Decision payload").splitlines()[0])
    ap.add_argument("--root", type=Path, default=None,
                    help="корень дерева (умолчание — дерево этого файла)")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="каталог данных для оси B (НЕ указан ⇒ записи "
                         "носителей НЕ НАБЛЮДАЛИСЬ, и это третий исход)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = census(args.root, args.data_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
