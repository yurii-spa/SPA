"""Цена ОТМЕНЫ двойного счёта в журнале решений (заказ G16, хвост ADR-383).

Заказ цикла #602 поставлен дословно так:

> **Измерить цену ОТМЕНЫ двойного счёта другим способом** — назвать, во что
> обойдётся различать вердикты разных прогонов одного дня (ключ
> ``decision_id``/``run_ts`` вместо ``cycle_date``, миграция уже накопленных
> 40 строк, кто из читателей журнала сломается), и **сколько ACT-дней это
> вернуло бы, если бы правило было таким с самого начала** — обеими границами
> по уже записанной истории сделок.

[ADR-383] измерил ЦЕНУ правила замены строки на одном дне: единственный ACT за
сорок дней был стёрт повторным прогоном того же дня. Рычаг назван и он ПАРНЫЙ.
Этот прибор меряет ЦЕНУ ЕГО ПЕРВОЙ ПОЛОВИНЫ — той, что лежит в нашем коде.

Прибор только ЧИТАЕТ. Он ничего не чинит, не мигрирует и не предлагает
мигрировать молча.

## Четыре вопроса, и у них РАЗНЫЕ ответы

### 1. Ключ. Половина предложенного заказом ключа — переименование даты

Заказ называет два кандидата: ``decision_id`` и ``run_ts``. ``decision_id`` в
записи УЖЕ ЕСТЬ, и это не удача, а ловушка: писатель чеканит его как
``f"adr060-shadow-{cycle_date}"`` — функцию ОДНОЙ ДАТЫ. Ключ ``decision_id``
сталкивается ровно там же, где ``cycle_date``, и замена одного другим не меняет
НИЧЕГО.

Прибор это не пересказывает из докстринга писателя, а **меряет исходом**:
вызывает настоящий ``build_history_record`` ДВАЖДЫ с одной ``cycle_date`` и
РАЗНЫМИ остальными входами. Поле, которое при этом осталось равным, не зависит
ни от чего, кроме даты, — ``date_derived``; поле, которое разошлось, —
``run_distinct``. Проба односторонняя в свою пользу: равенство при
РАЗЛИЧАЮЩИХСЯ входах есть доказательство независимости, а не совпадение.

### 2. Миграция. Цена накопленных строк меряется у САМИХ СТРОК

Под новым ключом строка обязана иметь значение и не сталкиваться с соседкой.
Прибор считает по накопленному журналу: сколько строк несёт каждый кандидат,
сколько получается РАЗНЫХ пар ``(дата, ключ)`` и сколько строк остались бы без
ключа — то есть сколько пришлось бы чеканить задним числом. Строка без ключа —
третий исход, а не ноль.

### 3. Читатели. Вердикт — по ИСХОДУ, и «не сломался» бывает ХУЖЕ поломки

Заказ спрашивает «кто из читателей сломается». Замер даёт ответ строже
вопроса: **главный читатель не ломается — он молча СХЛОПЫВАЕТ**. Правило замены
строки живёт ВТОРОЙ КОПИЕЙ внутри ``shadow_trigger_eval.load_history``
(``by_date[str(obj["cycle_date"])] = obj  # later line wins``), и всякий, кто
читает журнал через неё, наследует правило вместе с нею. Починка одного писателя
вернула бы ACT-день в ФАЙЛ и не вернула бы его КРИТЕРИЮ — а выглядело бы это как
доставленная починка.

Поэтому вердикт читателю выносится не грепом, а тремя стендами:

* ``S1`` — журнал как есть: у дня ``D`` его настоящая строка ``R``;
* ``S2`` — у дня ``D`` ДВЕ строки: ``R'`` (ранний прогон, вердикт ``ACT``) и ``R``;
* ``S3`` — у дня ``D`` ОДНА строка ``R'``.

``R'`` не выдуман: это настоящая строка СОСЕДНЕГО дня, перемеченная на ``D``
(``cycle_date``, ``decision_id``, ``generated_at``, ``verdict``) — реальный
материал вместо правдоподобной подделки.

Исходы, и третий не растворяется в первых двух:

* ``collapses_to_last``  — ответ на ``S2`` равен ответу на ``S1``: читатель несёт
  свою копию правила, починка писателя до него НЕ ДОХОДИТ;
* ``collapses_to_first`` — ответ на ``S2`` равен ответу на ``S3``;
* ``sees_both``          — ответ отличается от обоих: читатель УВИДИТ вторую
  строку, и миграция обязана его учесть;
* ``insensitive_stand``  — ответ на ``S1`` равен ответу на ``S3``: **стенд не
  сдвинул читателя вовсе**, и про схлопывание о нём НЕ ИЗМЕРЕНО ничего. Без
  этого исхода «равен ``S1``» записывалось бы в схлопывание тому, кто журнал не
  читает, — контроль, истинный по построению;
* ``unmeasured``         — с названной причиной (нет приводимой точки входа,
  точка входа упала, ответ не воспроизводится на ОДНОМ И ТОМ ЖЕ стенде).

Повторный прогон ``S1`` — не украшение: ответ, не воспроизводящийся на
неизменном стенде, нельзя сравнивать ни с чем, и объявлять его «увидел обе
строки» значило бы принять за находку собственные часы.

### 4. Население читателей — ДВЕ ДОРОГИ, и каждая слепа к другой

Читатель доходит до журнала двумя разными путями, и население, построенное по
одному, не видит второго ПО ПОСТРОЕНИЮ. Замер 14.09:

* по **имени файла** в исходнике — ``decision_record_run_identity``,
  ``leg_provenance_split``, ``snapshot_minute_sensitivity``, ``target_stability``
  сюда попадают, а ``unobserved_leg_remedy_class`` — нет: он зовёт
  ``_dep._ste.load_history(...)`` через ЧУЖОЙ псевдоним и имени файла не
  произносит;
* по **графу импортов** (транзитивное замыкание до ``shadow_trigger_eval`` /
  ``allocation_rationale``) — наоборот: ``unobserved_leg_remedy_class`` попадает,
  а четверо выше нет, потому что открывают файл своим литералом.

Население — **объединение** обеих дорог, и у каждого модуля названа дорога.
Объединение заведомо ИЗБЫТОЧНО (модуль мог импортировать соседа не ради
журнала), и это безопасно: лишний уходит в ``insensitive_stand``, то есть в
честное «не измерено», а не в находку. Обратная ошибка — пропуск читателя —
безопасной не была бы.

### 5. ACT-дни. Обе границы, и население берётся у ДЕНЕГ

Население — история сделок, а не журнал: журнал здесь подозреваемый ([ADR-383]).

* **Нижняя граница** — дни, где вердикт ``ACT`` НАБЛЮДЁН: ход несёт метку
  ``cio_trial_grant``, которую ставит единственная ветка, тем же присваиванием
  пишущая ``decision = "ACT"``.
* **Верхняя граница** — дни, где замена МОГЛА стереть ``ACT``: ход был,
  выжившая строка дня НЕ ``ACT`` и написана СТРОГО ПОЗЖЕ хода (отпечаток
  правила «последний прогон дня побеждает»), и у дня было не менее двух
  прогонов по независимому носителю ``audit_trail``.
* **Ни в одну границу** не входит день, у которого строки в журнале нет вовсе:
  заменять было нечего. Записать его в верхнюю границу значило бы выдать за
  цену правила то, чего правило не делало.

Граница ответственности названа вслух: ход НЕ ЕСТЬ доказательство теневого
вердикта — тень советует, а двигает деньги живой аллокатор. Поэтому верхняя
граница и есть граница («не более чем»), а не счёт. И обе границы считаются по
дням, ДВИГАВШИМ ДЕНЬГИ: ``ACT``, не сдвинувший ничего, в историю сделок не
попадает вовсе и лежит вне населения, заданного заказом.

## ADVISORY

``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель журнала и его правило
замены строки, ``load_history``, ``POLLED_ADAPTERS``, пины, адаптеры, накопитель
ряда, пороги RiskPolicy v1.0, стоп-кран, живой трек и ``landing/`` НЕ трогаются.
Капитал не двигается. Прибор только ЧИТАЕТ, а стенды строит на КОПИИ.

[ADR-383]: ../../docs/decisions/ADR-383-act-day-erased-from-the-journal.md
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import collections
import copy
import hashlib
import importlib
import inspect
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from spa_core.monitoring._http_reader_probe import UNREAD_RESPONSE
from spa_core.utils.observation import observed

log = logging.getLogger(__name__)

VERSION = "run-identity-key-price-v1"
ARTIFACT = "run_identity_key_price.json"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
TRADES_FILENAME = "trades.json"
AUDIT_FILENAME = "audit_trail.jsonl"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

# ── исходы читателя ──────────────────────────────────────────────────────────
READER_LAST = "collapses_to_last"
READER_FIRST = "collapses_to_first"
READER_BOTH = "sees_both"
READER_INSENSITIVE = "insensitive_stand"
READER_UNMEASURED = "unmeasured"

# ── ПРИЧИНЫ исхода ``unmeasured`` (заказ #614/G26) ───────────────────────────
# До этой правки все они печатались ОДНИМ числом, а в теле несли одну и ту же
# строку «нет приводимой точки входа». Замер 16.09 показал, что это НЕ один
# класс: из 63 не измеренных 59 стояли под этой строкой, 3 — под «ответ не
# воспроизводится», 1 — сам прибор. Инв. #17 требует, чтобы отсутствие
# наблюдения было представлено ОТДЕЛЬНЫМ значением; одна общая строка на шесть
# разных причин — это ноль вместо трёх исходов.
CAUSE_IMPORT_FAILED = "import_failed"
CAUSE_WOULD_ACT = "entry_would_act"
CAUSE_HTTP_ROUTE = "http_route_handler"
CAUSE_RUN_NO_WRITE_SWITCH = "run_without_write_switch"
CAUSE_CLI_ONLY = "cli_entry_only"
CAUSE_NO_ENTRY = "no_entry_point"
CAUSE_ENTRY_RAISED = "entry_raised"
CAUSE_IRREPRODUCIBLE = "answer_not_reproducible"
CAUSE_RESTS_ON_UNSTABLE = "verdict_rests_on_unstable_coords"
#: Ответ-объект без читаемого тела (потоковый) — заказ G29, ADR-404.
CAUSE_RESPONSE_UNREAD = "response_body_unread"
CAUSE_SELF = "the_instrument_itself"
#: Часы прогона до читателя НЕ ДОШЛИ, потому что его точка входа их не берёт.
#: Своя причина, а не общее ведро: «часы провести некуда» и «часы проведены, а
#: вердикта всё равно нет» — разные утверждения, и лечатся они в разных местах
#: (первое — правкой ЧИТАТЕЛЯ, второе — правкой прибора).
CLOCK_NOT_ACCEPTED = "entry_takes_no_clock"
#: Стенд до читателя НЕ ДОШЁЛ — ответ тот же и на ПУСТОМ каталоге. Своя причина,
#: а не `insensitive_stand`: «стенд не сдвинул ответ» и «читатель вообще не
#: открывал каталог стенда» — разные утверждения, и второе НИЧЕГО не говорит о
#: схлопывании. Без этой проверки перепись доложила бы «нечувствителен» о
#: читателе, которого она не коснулась, — fail-OPEN, и он тише красной строки.
CAUSE_STAND_NOT_READ = "stand_not_read"

#: Часовой «пробы пустого каталога не было». ``None`` тут не годится: ``None``
#: есть законный ОТВЕТ читателя, и умолчание в его виде означало бы, что
#: отсутствие пробы неотличимо от пробы, вернувшей пустоту (инв. #17).
_NO_EMPTY_PROBE = object()

#: Точки входа под ДРУГИМ именем, прочитанность которых доказана ПОИМЁННО.
#: Список именной, а не по образцу, и это не лень: образец «первый параметр
#: зовётся data_dir» захватил бы ``allocation_rationale.write_shadow_rationale``
#: (это ПИСАТЕЛЬ журнала, ``write=True`` по умолчанию) и
#: ``cycle_runner.run_cycle`` (дневной цикл, денежный путь). Перепись,
#: расширенная образцом, ЗАПУСТИЛА БЫ цикл — поэтому расширение fail-CLOSED:
#: молчаливо не добавляется никто.
_EXTRA_READ_ONLY_ENTRIES = {
    "spa_core.paper_trading.cio_brief": "build_books_brief",
    "spa_core.paper_trading.cio_trial": "trial_moves_spent",
}

#: Модули, которые прибор НЕ ЗОВЁТ НИКОГДА — с названной причиной у каждого.
#: Это не «не удалось измерить», а ОТКАЗ измерять таким способом: вызов совершил
#: бы действие. Отдельная причина нужна ровно затем, чтобы отказ не выглядел
#: как отсутствие точки входа (памятка: «mutating away a refusal performs the
#: refused action» — здесь тот же класс, но у прибора).
_NEVER_CALL = {
    "spa_core.paper_trading.cycle_runner":
        "run_cycle — дневной цикл: write=True по умолчанию, это денежный путь",
    "spa_core.paper_trading.allocation_rationale":
        "write_shadow_rationale — ПИСАТЕЛЬ журнала, а не его читатель",
    "scripts.kill_switch_drill":
        "run_drill — учение стоп-крана; стоп-кран прибору трогать запрещено",
    "spa_core.monitoring.owner_answer_delivery":
        "run — доставка ответа владельцу: пушер и Телеграм наружу (необратимо)",
    # Заказ G31: этот сосед САМ гоняет перепись двумя процессами по всему её
    # населению. Позвать его отсюда значило бы войти в перепись изнутри
    # переписи — и не разово: каждое плечо подняло бы ещё два. Отказ ЗВАТЬ, а
    # не «нечего позвать»: точка входа у него есть, и именно поэтому её нельзя
    # приводить.
    "spa_core.monitoring.python_reader_clock_doors":
        "measure — гоняет ЭТУ перепись двумя процессами по всему её населению",
}

# ── дороги, которыми читатель доходит до журнала ─────────────────────────────
ROAD_FILENAME = "filename_literal"
ROAD_IMPORTS = "import_closure"

#: Модули, к журналу ведущие. Замыкание строится ОБРАТНО от них.
LOADER_MODULES = (
    "spa_core.paper_trading.shadow_trigger_eval",
    "spa_core.paper_trading.allocation_rationale",
)

#: Литералы, по которым узнаётся вторая дорога — имя файла в исходнике.
FILENAME_NEEDLES = ("allocation_rationale_history", "history_filename")

#: Поля ответа, несущие СТЕННЫЕ ЧАСЫ. Названы ПОИМЁННО: регулярка по «датному
#: виду» глушила бы и входные отметки (``feed_coverage.as_of`` — это ВХОД, а не
#: часы), то есть отвечала бы не на тот вопрос.
CLOCK_FIELDS = ("generated_at", "now", "measured_at", "timestamp", "run_at",
                "as_of_run", "as_of")

#: Каталоги внутри ``data/``, не копируемые в стенды. Исключение ОДИНАКОВО на
#: всех трёх стендах, поэтому дифференциал к нему нечувствителен по построению.
STAND_EXCLUDE = ("backups",)

#: Пауза между двумя пробами ОДНОГО стенда. Нужна затем, чтобы поля,
#: производные от стенных часов, разошлись НАВЕРНЯКА, а не по везению. Замер
#: 16.09 на `house_view_gap`: вызов идёт 1 мс, поля `age_s` округлены до
#: десятых долей секунды — две пробы подряд попадали в одну корзину и
#: «стабильность» подтверждалась ложно, через 0.25 с расходились всегда. Без
#: паузы САМ НАБОР нестабильных координат менялся от прогона к прогону, и
#: вердикт читателю вместе с ним.
#:
#: ГРАНИЦА, названная вслух: поле с шагом ГРУБЕЕ паузы (возраст в целых
#: секундах, «часов назад») этой пробой не вскрывается и по-прежнему способно
#: загрязнить сравнение. Цена названа, чтобы выбор между чувствительностью и
#: стоимостью не выглядел умолчанием: пауза стоит ~27 с на 108 читателей, а
#: ЛИШНЯЯ ПРОБА стоила 879 с против ~300 с — поэтому проб две, а не три.
_STABILITY_PROBE_DELAY_S = 0.25

#: Имена точек входа, которые прибор умеет привести, и имя первого параметра.
_DATA_DIR_ENTRIES = ("measure", "build", "evaluate_window")
_DATA_DIR_PARAMS = ("data_dir", "base", "path")

#: Часовой от рекурсии. Прибор сам ЧИТАЕТ журнал, поэтому обе дороги находят
#: его собственным читателем; погнать его на стенде значило бы запустить всю
#: перепись заново изнутри неё же. Самоисключение НАЗВАНО третьим исходом, а не
#: сделано молча: про себя прибор честно отвечает «не измерено».
_SWEEPING = False

_ADVISORY = (
    "ADVISORY: hit_rate, MIN_HIT_RATE, TriggerParams, писатель журнала и его правило "
    "замены строки, load_history, POLLED_ADAPTERS, пины, накопитель ряда, пороги "
    "RiskPolicy v1.0, стоп-кран, живой трек и landing/ НЕ трогаются — прибор только "
    "читает, а стенды строит на КОПИИ"
)

WHAT_IT_DOES_NOT_PROVE = (
    "не утверждает, каким был вердикт стёртого прогона: единственный его носитель "
    "уничтожен заменой (ADR-314)",
    "не утверждает, что ход доказывает теневой вердикт ACT: тень советует, деньги "
    "двигает живой аллокатор — доказывает только метка разрешения владельца",
    "не утверждает, что правило замены НЕВЕРНО: измерена цена его отмены, а не его "
    "отмена",
    "не утверждает полноты населения читателей: дорога через динамический импорт "
    "обеими мерками не видна",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw) -> Optional[datetime]:
    """ISO-отметка → datetime (UTC). Неразобранное — ``None``, а не «эпоха»."""
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_history(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Строки журнала КАК ОНИ ЛЕЖАТ — без схлопывания по дате.

    Канонический ``load_history`` здесь не годится по существу: он и есть
    вторая копия измеряемого правила, и спрашивать у него про население строк
    значило бы замкнуть прибор на предмет.
    """
    path = Path(data_dir) / HISTORY_FILENAME
    if not path.exists():
        return None, f"{HISTORY_FILENAME} не найден"
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:  # noqa: BLE001
        return None, f"{HISTORY_FILENAME} не прочитан: {exc}"
    rows: List[dict] = []
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, ""


# ── вопрос 1: КЛЮЧ. Различает ли поле прогоны, или это переименованная дата ──
def _twin_docs(cycle_date: str) -> Tuple[Tuple[dict, dict], Tuple[dict, dict]]:
    """Два входа писателя: ОДНА дата, всё остальное различается.

    Поле, равное на выходе при таких входах, не зависит ни от чего, кроме даты.
    Различаются намеренно ВСЕ остальные входы — иначе равенство поля говорило бы
    о совпадении входов, а не о независимости поля.
    """
    doc_a = {
        "cycle_date": cycle_date,
        "generated_at": f"{cycle_date}T06:00:00+00:00",
        "params": {"policy_version": "v1.0", "mode": "paper"},
        "decision_shadow": {
            "decision": "ACT", "reasons": ["первый прогон"], "legs": ["aave_v3"],
            "gates": {"gate_a": True}, "apy_now_pp": 1.0, "apy_opt_pp": 2.0,
            "gain_pp": 1.0, "required_gain_pp": 0.5, "cost_usd": 10.0,
            "payback_days": 3.0, "turnover_usd": 40000.0, "turnover_frac": 0.4,
            "warnings": ["w"],
        },
    }
    doc_b = {
        "cycle_date": cycle_date,
        "generated_at": f"{cycle_date}T23:31:36+00:00",
        "params": {"policy_version": "v9.9", "mode": "shadow"},
        "decision_shadow": {
            "decision": "HOLD", "reasons": ["второй прогон", "и ещё один"], "legs": [],
            "gates": {"gate_b": False}, "apy_now_pp": 7.0, "apy_opt_pp": 7.5,
            "gain_pp": 0.5, "required_gain_pp": 3.0, "cost_usd": 99.0,
            "payback_days": 88.0, "turnover_usd": 1.0, "turnover_frac": 0.01,
            "warnings": [],
        },
    }
    kw_a = dict(apy_pct={"aave_v3": 3.0}, apy_sources={"aave_v3": "live"},
                current_positions={"aave_v3": 1000.0},
                target_positions={"aave_v3": 2000.0}, capital_usd=95000.0,
                apy_as_of={"aave_v3": f"{cycle_date}T06:00:00Z"})
    kw_b = dict(apy_pct={"morpho_blue": 9.0}, apy_sources={"morpho_blue": "live"},
                current_positions={"morpho_blue": 5000.0},
                target_positions={"morpho_blue": 7000.0}, capital_usd=91000.0,
                apy_as_of={"morpho_blue": f"{cycle_date}T23:00:00Z"})
    return (doc_a, kw_a), (doc_b, kw_b)


def probe_key_fields(cycle_date: str = "2026-09-11",
                     builder: Optional[Callable[..., dict]] = None) -> dict:
    """Какие поля записи различают ПРОГОНЫ, а какие — только ДАТУ.

    Меряет НАСТОЯЩИМ писателем: своя копия правила чеканки разошлась бы с ним
    молча, и тогда ответ был бы о копии.
    """
    if builder is None:
        try:
            from spa_core.paper_trading.allocation_rationale import (
                build_history_record as builder,
            )
        except Exception as exc:  # noqa: BLE001
            return {"measured": False,
                    "reason": f"писатель записи недоступен: {type(exc).__name__}: {exc}"}
    (doc_a, kw_a), (doc_b, kw_b) = _twin_docs(cycle_date)
    try:
        rec_a = builder(doc_a, **kw_a)
        rec_b = builder(doc_b, **kw_b)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"писатель записи упал: {type(exc).__name__}: {exc}"}
    keys = sorted(set(rec_a) | set(rec_b))
    date_derived = [k for k in keys if rec_a.get(k) == rec_b.get(k)]
    run_distinct = [k for k in keys if rec_a.get(k) != rec_b.get(k)]
    return {
        "measured": True,
        "cycle_date": cycle_date,
        "date_derived": date_derived,
        "run_distinct": run_distinct,
        "decision_id_value": rec_a.get("decision_id"),
        "decision_id_distinguishes_runs": "decision_id" in run_distinct,
        "what_it_proves": (
            "поле, равное при РАЗЛИЧАЮЩИХСЯ входах одного дня, не зависит ни от чего, "
            "кроме даты — ключом прогона оно быть не может"),
    }


# ── вопрос 2: МИГРАЦИЯ накопленных строк ─────────────────────────────────────
def measure_migration(rows: Sequence[dict],
                      candidates: Sequence[str] = ("decision_id", "generated_at"),
                      date_derived: Sequence[str] = ()) -> dict:
    """Что станет с уже накопленными строками под каждым кандидатом в ключ.

    Считает у САМИХ СТРОК: сколько несут кандидата, сколько получается разных
    пар ``(дата, ключ)``, сколько строк остались бы без ключа. Строка без ключа
    — третий исход: её пришлось бы чеканить задним числом, и это часть цены.
    """
    out: Dict[str, dict] = {}
    total = len(rows)
    for field in candidates:
        present = [r for r in rows if r.get(field) is not None]
        pairs = {(str(r.get("cycle_date")), str(r.get(field))) for r in present}
        # Столкновение — две РАЗНЫЕ строки, неотличимые под новым ключом.
        collisions = len(present) - len(pairs)
        usable = field not in set(date_derived)
        out[field] = {
            "rows_total": total,
            "rows_with_key": len(present),
            "rows_needing_minted_key": total - len(present),
            "distinct_pairs": len(pairs),
            "collisions": collisions,
            "distinguishes_runs": usable,
            "verdict": ("годен" if usable and collisions == 0 and len(present) == total
                        else ("НЕ ГОДЕН: ключ выведен из даты — то же столкновение под "
                              "другим именем" if not usable else
                              "годен с чеканкой недостающих" if collisions == 0 else
                              "НЕ ГОДЕН: строки сталкиваются под этим ключом")),
        }
    return {"measured": True, "rows_total": total, "by_candidate": out}


# ── вопрос 3-4: ЧИТАТЕЛИ. Население двумя дорогами ───────────────────────────
def _first_party_modules(tree_root: Path,
                         packages: Sequence[str] = ("spa_core", "scripts")) -> Dict[str, Path]:
    """Карта «имя модуля → файл» по первой стороне, БЕЗ тестов."""
    files: Dict[str, Path] = {}
    for pkg in packages:
        base = tree_root / pkg
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(tree_root).as_posix()
            if "/tests/" in rel:
                continue
            files[rel[:-3].replace("/", ".")] = path
    return files


def _import_edges(files: Dict[str, Path]) -> Dict[str, Set[str]]:
    """Рёбра графа импортов первой стороны (модульный уровень, AST)."""
    edges: Dict[str, Set[str]] = {}
    for name, path in files.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            edges[name] = set()
            continue
        deps: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    deps.add(node.module)
                    for alias in node.names:
                        deps.add(f"{node.module}.{alias.name}")
        edges[name] = {d for d in deps if d in files}
    return edges


def reader_population(tree_root: Path,
                      loaders: Sequence[str] = LOADER_MODULES) -> Tuple[Dict[str, Set[str]], dict]:
    """Население читателей — ОБЪЕДИНЕНИЕ двух дорог, у каждого названа своя.

    Дорога одна — имя файла в исходнике; дорога вторая — транзитивное замыкание
    графа импортов до канонического загрузчика. Каждая слепа к другой ПО
    ПОСТРОЕНИЮ, и населением служит только объединение.
    """
    files = _first_party_modules(Path(tree_root))
    roads: Dict[str, Set[str]] = collections.defaultdict(set)
    for name, path in files.items():
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(needle in src for needle in FILENAME_NEEDLES):
            roads[name].add(ROAD_FILENAME)
    edges = _import_edges(files)
    rev: Dict[str, Set[str]] = collections.defaultdict(set)
    for src_mod, deps in edges.items():
        for dep in deps:
            rev[dep].add(src_mod)
    seen = {m for m in loaders if m in files}
    stack = list(seen)
    while stack:
        node = stack.pop()
        for parent in rev.get(node, ()):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    for name in seen:
        roads[name].add(ROAD_IMPORTS)
    stats = {
        "modules_scanned": len(files),
        "via_filename_only": sorted(m for m, r in roads.items() if r == {ROAD_FILENAME}),
        "via_imports_only": sorted(m for m, r in roads.items() if r == {ROAD_IMPORTS}),
        "via_both": sorted(m for m, r in roads.items() if len(r) == 2),
        "population": len(roads),
    }
    return dict(roads), stats


def build_stands(source_data_dir: Path, dest: Path,
                 day: Optional[str] = None) -> Tuple[Optional[dict], str]:
    """Три стенда на КОПИИ ``data/``: как есть · две строки дня · одна чужая.

    ``R'`` — настоящая строка соседнего дня, перемеченная на ``D``. Настоящий
    материал вместо правдоподобной подделки: выдуманная строка проверяла бы
    читателя на том, чего писатель никогда не писал.
    """
    rows, why = read_history(Path(source_data_dir))
    if rows is None:
        return None, why
    if len(rows) < 2:
        return None, "в журнале меньше двух строк — соседнего дня для стенда нет"
    idx = None
    day_rule = "назван вызовом"
    if day is not None:
        idx = next((i for i, r in enumerate(rows) if r.get("cycle_date") == day), None)
        if idx is None:
            return None, f"дня {day} нет в журнале"
    if idx is None:
        # День стенда выбирается ПРАВИЛОМ, а не литералом, и правило это не
        # вкусовщина: последний день журнала форвардных дней не имеет вовсе,
        # поэтому оконный читатель на нём не шелохнётся и уйдёт в
        # `insensitive_stand` — не потому, что он нечувствителен, а потому, что
        # стенд выбран там, где мерить нечем. Берём ПОЗДНЕЙШИЙ день, за которым
        # в журнале ещё лежит полный горизонт судьи.
        horizon = _judge_horizon()
        idx = max(1, len(rows) - 1 - horizon) if horizon is not None else len(rows) - 1
        day_rule = (f"позднейший день, за которым остаётся горизонт судьи "
                    f"({horizon} дн.)" if horizon is not None
                    else "последний день журнала (горизонт судьи не прочитан)")
    if idx == 0:
        idx = len(rows) - 1
        day_rule += " · сдвинут: у первого дня нет соседа-донора"
    donor = rows[idx - 1]
    target = rows[idx]
    target_day = str(target.get("cycle_date"))
    twin = dict(donor)
    twin["cycle_date"] = target_day
    twin["decision_id"] = f"adr060-shadow-{target_day}"
    twin["generated_at"] = f"{target_day}T06:00:11.000000+00:00"
    twin["verdict"] = "ACT"

    def _write(name: str, day_rows: List[dict]) -> Path:
        stand = Path(dest) / name
        data = stand / "data"
        data.mkdir(parents=True, exist_ok=True)
        for item in sorted(Path(source_data_dir).iterdir()):
            if item.name in STAND_EXCLUDE:
                continue
            dst = data / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        out: List[dict] = []
        for i, row in enumerate(rows):
            if i == idx:
                out.extend(day_rows)
            else:
                out.append(row)
        (data / HISTORY_FILENAME).write_text(
            "\n".join(json.dumps(r, sort_keys=True, default=str) for r in out) + "\n",
            encoding="utf-8")
        return stand

    return {
        "day": target_day,
        "donor_day": str(donor.get("cycle_date")),
        "s1": _write("s1", [target]),
        "s2": _write("s2", [twin, target]),
        "s3": _write("s3", [twin]),
        "rewritten_fields": ["cycle_date", "decision_id", "generated_at", "verdict"],
        "day_rule": day_rule,
    }, ""


def _judge_horizon() -> Optional[int]:
    """Горизонт судьи — у САМОГО судьи, а не своей константой."""
    try:
        from spa_core.paper_trading.shadow_trigger_eval import DEFAULT_HORIZON_DAYS
    except Exception:  # noqa: BLE001
        return None
    try:
        return int(DEFAULT_HORIZON_DAYS)
    except (TypeError, ValueError):
        return None


def _canon(answer) -> str:
    """Сериализация ответа ЦЕЛИКОМ — для дешёвой проверки «совпало ли»."""
    return json.dumps(answer, sort_keys=True, default=str)


def _strip_clock(answer) -> str:
    """Ответ без СТЕННЫХ полей верхнего уровня — названных поимённо."""
    obj = copy.deepcopy(answer)
    if isinstance(obj, dict):
        for key in CLOCK_FIELDS:
            obj.pop(key, None)
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def unstable_coords(one, two, path: str = "") -> Set[str]:
    """Координаты, РАЗОШЕДШИЕСЯ на двух вызовах ОДНОГО И ТОГО ЖЕ стенда.

    Замер, а не список имён. Координата, которая расходится при тождественном
    входе, по построению не может быть свидетельством о входе — поэтому её
    можно снять, ничего не ослабив. Обратное (дописать имя в ``CLOCK_FIELDS``)
    было бы догадкой и уносило бы ВХОДНЫЕ отметки: ``feed_coverage.as_of`` —
    это вход, а не часы, и глушить его значило бы отвечать не на тот вопрос.
    """
    out: Set[str] = set()
    if type(one) is not type(two):
        return {path}
    if isinstance(one, dict):
        for key in set(one) | set(two):
            if key not in one or key not in two:
                out.add(f"{path}.{key}")
            else:
                out |= unstable_coords(one[key], two[key], f"{path}.{key}")
    elif isinstance(one, list):
        if len(one) != len(two):
            return {path}
        for idx, (a, b) in enumerate(zip(one, two)):
            out |= unstable_coords(a, b, f"{path}[{idx}]")
    elif one != two:
        out.add(path)
    return out


def _stable_leaves(obj, drop: Set[str], path: str = "") -> int:
    """Сколько ЛИСТЬЕВ ответа уцелело после снятия нестабильных координат."""
    if path in drop:
        return 0
    if isinstance(obj, dict):
        return sum(_stable_leaves(v, drop, f"{path}.{k}") for k, v in obj.items())
    if isinstance(obj, list):
        return sum(_stable_leaves(v, drop, f"{path}[{i}]") for i, v in enumerate(obj))
    return 1


def mask_coords(obj, drop: Set[str], path: str = "",
                label: str = "<нестабильно на одном стенде>"):
    """Ответ без измеренных нестабильных координат."""
    if path in drop:
        return label
    if isinstance(obj, dict):
        return {k: mask_coords(v, drop, f"{path}.{k}", label) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_coords(v, drop, f"{path}[{i}]", label) for i, v in enumerate(obj)]
    return obj


#: Чем заменяется координата, измеренная как момент выдачи ответа (заказ G30).
CALL_MOMENT_MARK = "<момент зова>"


def _leaves(obj, path: str = ""):
    """Пары ``(координата, лист)`` в той же записи пути, что ``unstable_coords``."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            yield from _leaves(val, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            yield from _leaves(val, f"{path}[{idx}]")
    else:
        yield path, obj


def _inside(value, window) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and window[0] <= value <= window[1])


def call_moment_coords(answers: Sequence, windows: Sequence) -> Set[str]:
    """Координаты, чьё значение — МОМЕНТ ЗОВА, установленный замером (заказ G30).

    Замер 17.09: у 18 маршрутов вердикт гасила одна координата тела
    (``_fetched_at`` ×12, ``ts`` ×6), и у неё 16 дверей ``time.time()`` в трёх
    модулях — общей двери, которую можно закрепить, нет. Но координату, равную
    моменту зова, можно УЗНАТЬ: её значение лежит внутри окна ``[начало, конец]``
    того самого зова, снятого зондом по тем же часам. Значение из стенда туда
    попасть не может — стенд собран до первой пробы, а зов маршрута каталога не
    меняет (замер ADR-399: sha 1325 файлов до и после).

    Правило fail-CLOSED, по ВСЕМ пробам, а не по одной:

    * кандидат — координата, лежащая в окне на ``s1`` И на повторной ``s1``;
      окна нет хотя бы у одной из них — кандидатов нет;
    * координата, присутствующая на какой-либо пробе ВНЕ окна (или на пробе
      без окна), кандидатом быть перестаёт: где-то она несёт не момент зова, а
      значит может нести стенд (``setdefault`` у ``btc_engine`` — ровно такой
      случай, когда отметка берётся из файла);
    * производная от часов (возраст, округлённая отметка) в окно не попадает и
      остаётся нестабильной — ошибка возможна только в сторону МЕНЬШЕЙ
      определённости.
    """
    answers = list(answers)
    windows = list(windows)
    if len(answers) < 2 or not windows[0] or not windows[1]:
        return set()

    def inside(ans, win) -> Set[str]:
        return {c for c, v in _leaves(ans) if _inside(v, win)}

    cand = inside(answers[0], windows[0]) & inside(answers[1], windows[1])
    for ans, win in zip(answers, windows):
        if ans is None or not cand:
            continue
        present = {c for c, _v in _leaves(ans)}
        cand -= present if not win else (present - inside(ans, win))
    return cand


def clock_kwarg(fn, now: Optional[datetime]) -> Dict[str, object]:
    """``{"now": now}``, если точка входа берёт часы, иначе ``{}``.

    Заказ G28, часть 1. Определение ОДНО и живёт здесь, потому что ответ нужен
    в двух местах — при СВЯЗЫВАНИИ зова (``module_driver``) и при записи строки
    отчёта (``classify_reader``). Будь их два, у переписи завелась бы вторая
    копия правила «часы проведены» — ровно тот класс, который она ловит у
    читателей журнала.

    Спрашивается у ПОДПИСИ, но проверяется ИСХОДОМ: положительный контроль
    ``test_injected_clock_reaches_the_reader`` сверяет не наличие параметра, а
    то, что ответ читателя несёт ИМЕННО переданное время.
    """
    if now is None:
        return {}
    try:
        params = inspect.signature(fn).parameters
    except (ValueError, TypeError):
        return {}
    return {"now": now} if "now" in params else {}


def module_driver(mod, *, now: Optional[datetime] = None
                  ) -> Tuple[Optional[str], Optional[Callable[[Path], object]]]:
    """Как позвать модуль так, как его зовёт цикл. Не нашли — ``None``.

    ``write=False`` передаётся везде, где параметр есть: стенд — копия, но
    прибор не имеет права опираться на это и писать туда, куда его не звали.

    ``now`` — ЧАСЫ ПРОГОНА, и проводятся они здесь, в единственном месте, где
    зов связывается (заказ G28). До этой правки прибор звал читателя без часов,
    тот брал их у машины, и его ``generated_at`` расходился между двумя пробами
    ОДНОГО стенда просто оттого, что между зовами прошло время. Дальше работал
    защитный ход: координата объявлялась нестабильной и СНИМАЛАСЬ, а если вся
    разница между стендами лежала в снятом — вердикт не выносился вовсе
    (``verdict_rests_on_unstable_coords``). Замер 16.09: так стояли **26**
    читателей из 108, и **26 из 26 УЖЕ принимали** ``now=`` — то есть цена,
    которую заказ собирался платить у читателя, была уплачена давно, а не
    проводила часы ПРОВОДКА. Половина инъекции есть та же бомба, что её
    отсутствие (``.claude/rules/deployment.md``); недостающая половина была эта.
    """
    for name in _DATA_DIR_ENTRIES:
        fn = getattr(mod, name, None)
        if callable(fn) and inspect.isfunction(fn):
            sig = inspect.signature(fn)
            params = list(sig.parameters)
            if params and params[0] in _DATA_DIR_PARAMS:
                kwargs = {"write": False} if "write" in sig.parameters else {}
                kwargs.update(clock_kwarg(fn, now))
                return name, (lambda stand, fn=fn, kw=kwargs: fn(stand / "data", **kw))
    fn = getattr(mod, "run", None)
    if callable(fn) and inspect.isfunction(fn):
        sig = inspect.signature(fn)
        if "write" in sig.parameters and "root" in sig.parameters:
            kwargs = clock_kwarg(fn, now)
            return "run", (lambda stand, fn=fn, kw=kwargs:
                           fn(root=str(stand), write=False, **kw))
    extra = _EXTRA_READ_ONLY_ENTRIES.get(getattr(mod, "__name__", ""))
    if extra:
        fn = getattr(mod, extra, None)
        if callable(fn) and inspect.isfunction(fn):
            sig = inspect.signature(fn)
            params = list(sig.parameters)
            if params and params[0] in _DATA_DIR_PARAMS:
                kwargs = clock_kwarg(fn, now)
                return extra, (lambda stand, fn=fn, kw=kwargs: fn(stand / "data", **kw))
    return None, None


def _http_surface(mod) -> Optional[str]:
    """Модуль — HTTP-поверхность? Спрашиваем у ОБЪЕКТА, не у имени модуля.

    Имя (``spa_core.api.routers.*``) было бы догадкой и ошибалось бы в обе
    стороны: роутер живёт и вне каталога (``spa_core.api.server``), а каталог
    может однажды получить модуль без роутера. Тип объекта — замер.
    """
    for attr, obj in vars(mod).items():
        cls = type(obj).__name__
        if cls in ("APIRouter", "FastAPI"):
            return f"{cls} в атрибуте {attr}"
    return None


def _module_functions(mod) -> Dict[str, List[str]]:
    """Функции УРОВНЯ МОДУЛЯ, объявленные в нём самом → их параметры."""
    out: Dict[str, List[str]] = {}
    name = getattr(mod, "__name__", "")
    for fn_name, fn in vars(mod).items():
        if fn_name.startswith("_") or not inspect.isfunction(fn):
            continue
        if getattr(fn, "__module__", None) != name:
            continue
        try:
            out[fn_name] = list(inspect.signature(fn).parameters)
        except (ValueError, TypeError):
            out[fn_name] = []
    return out


def no_entry_cause(mod) -> Tuple[str, str]:
    """ПОЧЕМУ точку входа привести не удалось — поимённо, а не одной строкой.

    Порядок ветвей — от самой узкой претензии к самой широкой, чтобы модуль не
    попал в общее ведро, имея названную причину.
    """
    http = _http_surface(mod)
    if http:
        return (CAUSE_HTTP_ROUTE,
                f"обработчик HTTP-маршрута ({http}), и партия зова маршрутов до "
                "него не дошла — сам по себе он ИЗМЕРИМ (заказ G27: каталог "
                "доходит переменной SPA_DATA_DIR до импорта, см. "
                "`_http_reader_probe`); прежняя строка «каталог стенда ему не "
                "передать» была догадкой и замером опровергнута")
    fns = _module_functions(mod)
    run_params = fns.get("run")
    if run_params is not None and "write" not in run_params:
        return (CAUSE_RUN_NO_WRITE_SWITCH,
                f"run({', '.join(run_params) or ''}) есть, но параметра write НЕТ — "
                f"вызов писал бы туда, куда прибор не звали")
    if "main" in fns and not any(
            p and p[0] in _DATA_DIR_PARAMS for n, p in fns.items() if n != "main"):
        return (CAUSE_CLI_ONLY,
                "только main(argv) — вход командной строки, по умолчанию он "
                "работает против ЖИВОГО каталога")
    if not fns:
        return (CAUSE_NO_ENTRY,
                "приводимой точки входа нет: функций уровня модуля нет вовсе")
    return (CAUSE_NO_ENTRY,
            "приводимой точки входа нет: ни одна функция уровня модуля не берёт "
            f"каталог data/ первым параметром (есть: {', '.join(sorted(fns)[:6])})")


def classify_reader(module_name: str, stands: dict, *,
                    now: Optional[datetime] = None) -> dict:
    """Вердикт одному читателю — по ИСХОДУ на трёх стендах.

    ``now`` проводится в САМ читатель (заказ G28). Одно и то же время во всех
    четырёх пробах означает, что расхождение между ответами может быть только о
    СТЕНДЕ, а не о том, сколько заняли зовы. Часы, которые читатель не берёт,
    записываются причиной ``entry_takes_no_clock`` — не измерено, а не «ноль».
    """
    row: Dict[str, object] = {"module": module_name}
    never = _NEVER_CALL.get(module_name)
    if never:
        # Отказ ЗВАТЬ — не то же, что «нечего позвать»: точка входа есть, и
        # именно поэтому её нельзя приводить. Своя причина, а не общее ведро.
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_WOULD_ACT, reason=never)
        return row
    try:
        mod = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_IMPORT_FAILED,
                   reason=f"импорт не удался: {type(exc).__name__}")
        return row
    entry, call = module_driver(mod, now=now)
    if call is None:
        cause, reason = no_entry_cause(mod)
        row.update(outcome=READER_UNMEASURED, cause=cause, reason=reason)
        return row
    row["entry"] = entry
    # Записывается ФАКТ, а не намерение: строка отчёта обязана различать
    # «вердикт получен при проведённых часах» и «вердикт получен при стенных».
    # Без этого поля улучшение счётчика было бы неотличимо от везения.
    injected = bool(clock_kwarg(getattr(mod, entry), now))
    row["clock_injected"] = injected
    if not injected:
        row["clock_reason"] = (CLOCK_NOT_ACCEPTED if now is not None
                               else "часы прогона прибору не переданы")
    try:
        raw1 = call(stands["s1"])
        # Пауза НУЖНА, а третья проба — нет. Поле, бегущее на каждом зове,
        # расходится при любом зазоре, поэтому пара «без паузы» есть
        # ПОДМНОЖЕСТВО пары «с паузой», и объединять их было незачем. Замер
        # 16.09: третья проба стоила лишний зов КАЖДОГО из 108 читателей и
        # увела перепись на 879 с; пауза стоит 27 с и ловит то же.
        time.sleep(_STABILITY_PROBE_DELAY_S)
        raw1_again = call(stands["s1"])
        raw2 = call(stands["s2"])
        raw3 = call(stands["s3"])
    except BaseException as exc:  # noqa: BLE001
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_ENTRY_RAISED,
                   reason=f"{entry}() упал: {type(exc).__name__}")
        return row
    return verdict_from_probes(row, raw1, raw1_again, raw2, raw3)


def verdict_from_probes(row: dict, raw1, raw1_again, raw2, raw3,
                        on_empty=_NO_EMPTY_PROBE) -> dict:
    """Вердикт по ЧЕТЫРЁМ ответам: ``s1``, ``s1`` повторно, ``s2``, ``s3``.

    Выделено из ``classify_reader`` заказом G27 и выделено НАМЕРЕННО, а не для
    красоты: обработчик HTTP-маршрута зовётся отдельным процессом и пачкой (см.
    ``_http_reader_probe``), поэтому его четыре ответа приходят готовыми. Будь
    правило скопировано во вторую ветку, у переписи завелись бы ДВА определения
    слова «схлопывает» — ровно тот класс, который она сама и ловит у читателей
    журнала («правило живёт второй копией у читателя»). Копия одна, и она здесь.

    ``on_empty`` — ответ того же читателя на ПУСТОМ каталоге, и он проверяет не
    журнал, а ПРОВОДКУ: дошёл ли стенд до читателя вообще. Сравнение идёт ПОСЛЕ
    того же маскирования, что и вердикт, — иначе одна нестабильная координата
    выдала бы «дошёл» там, где не доходило ничего. Спрашивается только у
    нечувствительных: у схлопывающего ответ уже сдвинулся между стендами, то
    есть каталог он читал по построению.
    """
    # Нестабильные координаты МЕРЯЮТСЯ двумя вызовами одного стенда и снимаются
    # у всех четырёх ответов. Раньше здесь стоял немедленный `unmeasured`, и на
    # нём терялся ЕДИНСТВЕННЫЙ схлопывающий читатель: `house_view_gap` несёт 33
    # поля `age_s` в десятых долях секунды, `_strip_clock` снимает только
    # ВЕРХНИЙ уровень, поэтому вердикт был подбрасыванием монеты — вызов идёт
    # 1 мс и подряд совпадал, а под нагрузкой переписи расходился. Замер 16.09:
    # прогон 1 — `collapses_to_last`, прогон 2 — `unmeasured`, дерево одно.
    # Ноль схлопывающих читался как «ADR-395 закрыл вопрос», что неправда.
    # Быстрый путь, ТОЧНЫЙ, а не приблизительный: равная сериализация двух
    # проб означает, что расходящихся координат нет ни одной, и обходить дерево
    # незачем. Большинство читателей устойчивы, а обход строит путь-строку на
    # КАЖДЫЙ узел — на крупных ответах это и съело прогон (замер: перепись
    # ушла с ~5 мин за 20+, пока сравнение шло обходом всегда).
    if _canon(raw1) == _canon(raw1_again):
        drop: Set[str] = set()
    else:
        drop = unstable_coords(raw1, raw1_again)
    row["unstable_coords"] = len(drop)
    # Ответ, в котором НЕ ОСТАЛОСЬ ни одного устойчивого листа, снятием не
    # спасается: сравнивать после маскирования было бы нечего, и любые два
    # стенда сошлись бы тождественно. Это ровно «не воспроизводится», и
    # называть это надо так, а не «вердикт стоит на снятом».
    if drop and not _stable_leaves(raw1, drop):
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_IRREPRODUCIBLE,
                   reason="ответ не воспроизводится на ОДНОМ И ТОМ ЖЕ стенде: "
                          f"устойчивых полей не осталось ни одного (снято {len(drop)})")
        return row
    _mask = (lambda obj: obj) if not drop else (lambda obj: mask_coords(obj, drop))
    a1 = _strip_clock(_mask(raw1))
    a1_again = _strip_clock(_mask(raw1_again))
    a2 = _strip_clock(_mask(raw2))
    a3 = _strip_clock(_mask(raw3))
    if a1 != a1_again:
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_IRREPRODUCIBLE,
                   reason="ответ не воспроизводится на одном стенде даже после "
                          f"снятия {len(drop)} измеренно нестабильных координат")
        return row
    if a1 == a3:
        # Снятие нестабильных координат не имеет права ГАСИТЬ улику. Если
        # стенды разошлись ТОЛЬКО в снятом, «нечувствителен» — неправда, а
        # выносить вердикт по снятому нельзя: он был бы подбрасыванием монеты
        # (замер 16.09 на `house_view_gap` — ровно этот случай: вся разница
        # между стендами легла в 33 поля `age_s`, производные от часов, и
        # прежний код отвечал `collapses_to_last` или `unmeasured` через
        # прогон). Третий исход, названный и ДЕТЕРМИНИРОВАННЫЙ.
        raw_cross = unstable_coords(raw1, raw3)
        if raw_cross and not (raw_cross - drop):
            row.update(outcome=READER_UNMEASURED, cause=CAUSE_RESTS_ON_UNSTABLE,
                       reason=(f"стенды разошлись ТОЛЬКО в {len(raw_cross)} координат(ах), "
                               f"нестабильных на одном стенде (всего снято {len(drop)}) — "
                               "судить о схлопывании нечем, а «нечувствителен» неправда"))
            return row
        if on_empty is not _NO_EMPTY_PROBE:
            if _strip_clock(_mask(on_empty)) == a1:
                row.update(outcome=READER_UNMEASURED, cause=CAUSE_STAND_NOT_READ,
                           reason=("ответ тот же и на ПУСТОМ каталоге — каталог "
                                   "стенда читатель не открывал; «нечувствителен "
                                   "к стенду» было бы про него неправдой"))
                return row
            row["reaches_stand"] = True
        row.update(outcome=READER_INSENSITIVE,
                   reason="стенд не сдвинул ответ — про схлопывание НЕ ИЗМЕРЕНО ничего")
        return row
    if a2 == a1:
        row.update(outcome=READER_LAST,
                   reason="ответ на двух строках равен ответу на ОДНОЙ ПОСЛЕДНЕЙ — "
                          "читатель несёт свою копию правила замены")
    elif a2 == a3:
        row.update(outcome=READER_FIRST,
                   reason="ответ на двух строках равен ответу на ОДНОЙ ПЕРВОЙ")
    else:
        row.update(outcome=READER_BOTH,
                   reason="ответ отличается от обоих — читатель УВИДИТ вторую строку")
    return row


# ── читатели-обработчики HTTP-маршрутов (заказ G27, часть 2) ────────────────
#: Сколько ждать ответа от одного стенда HTTP-переписи. Превышение — НЕ ноль и
#: не «нечувствителен», а названный третий исход у каждого модуля партии.
_HTTP_PROBE_TIMEOUT_S = 900

#: ПОРЯДОК ЗОВА. Повторная проба ``s1`` последняя — так окно, на котором
#: меряется нестабильность, накрывает весь прогон партии (обоснование и замер —
#: в докстринге ``http_probe_batch``). Порядок ВЫЧИСЛЕНИЯ вердикта другой и
#: задан отдельно: смешать их значило бы вернуть ту же монету через список.
_HTTP_PROBE_ORDER = ("s1", "s2", "s3", "empty", "s1_again")
_HTTP_VERDICT_ORDER = ("s1", "s1_again", "s2", "s3", "empty")


def http_modules(names: Sequence[str]) -> List[str]:
    """Те из населения, у кого есть HTTP-поверхность. Вопрос — ОБЪЕКТУ, не имени."""
    out: List[str] = []
    for name in names:
        if name in _NEVER_CALL:
            continue
        try:
            mod = importlib.import_module(name)
        except BaseException:                                  # noqa: BLE001
            continue
        if _http_surface(mod):
            out.append(name)
    return out


def http_probe_batch(stands: dict, names: Sequence[str], tree_root: Path,
                     runner=None, *, now: Optional[datetime] = None
                     ) -> Tuple[Dict[str, tuple], dict]:
    """Четыре пробы ВСЕЙ партии маршрутов: ``s1``, ``s1`` повторно, ``s2``, ``s3``.

    Партией, а не по модулю, и это не оптимизация ради скорости. Вердикт
    требует ЧЕТЫРЁХ ответов одного читателя, а каждый ответ здесь — отдельный
    процесс (иначе ``SPA_DATA_DIR`` не успевает лечь до импорта). По модулю это
    было бы 20 × 4 = 80 процессов с FastAPI внутри каждого; партией — четыре.

    **Порядок проб не произволен, и в этом вся точность.** Повторная проба ``s1``
    идёт ПОСЛЕДНЕЙ, а не второй, чтобы окно измерения нестабильности НАКРЫВАЛО
    весь прогон партии. Иначе пара «подряд» меряет зазор в 18 с, а стенды ``s2``
    и ``s3`` разделены 70 с, и координата, тикнувшая между ними, объявляется
    стабильной — вердикт становится монетой ровно так, как в ADR-396.

    Замер 16.09, ради которого порядок и переставлен: ``/api/riskwire/proof``
    несёт ``age_hours``, округлённый до **0.1 часа (6 минут)**. Две пробы подряд
    попадают в одну корзину практически всегда (``unstable_coords: 0``), а
    граница корзины, пришедшаяся между ``s2`` и ``s3``, дала ``collapses_to_first``
    в одном прогоне и ``insensitive_stand`` в соседнем — на одном дереве, одних
    стендах и неизменном коде. Паузой это не лечится: пауза меньше 6 минут.

    Накрывающее окно лечит ТОЧНО, а не вероятностно: монотонная производная от
    часов, изменившаяся между ЛЮБЫМИ двумя пробами, изменилась и между первой и
    последней, потому что ``[s1 … s1_again] ⊇ [s2 … s3]``. Граница названа
    вслух: поле НЕмонотонное (случайное) способно вернуться к прежнему значению
    и этой пробой не вскрывается.

    **Часы (заказ G29, ADR-404).** ``now`` доносится до процесса-зонда тем же
    путём, что и каталог стенда, — окружением до импорта, и ОДНИМ И ТЕМ ЖЕ
    моментом на все пять проб: иначе отметка верхнего уровня расходилась бы
    между пробами одного стенда просто оттого, что между ними прошло время.
    Проводка спрашивает подпись зовущего тем же ``clock_kwarg``, что и у
    питоньих читателей. Дошли ли часы — судит ДВЕРЬ (``__clock__`` в ответе),
    а не факт передачи: ``meta["clock_pinned"]`` истинно, только если на
    ВСЕХ пробах ``_shared.now()`` вернул закреплённый момент.
    """
    runner = _run_http_probe if runner is None else runner
    meta: Dict[str, object] = {"modules_asked": len(names),
                               "probe_order": list(_HTTP_PROBE_ORDER)}
    if not names:
        meta["reason"] = "модулей с HTTP-поверхностью в населении нет"
        return {}, meta
    by_label: Dict[str, Dict[str, dict]] = {}
    # ПЯТАЯ проба — ПУСТОЙ каталог, и она не про журнал вовсе. Она отвечает на
    # вопрос, которого без неё не задавал никто: ДОШЁЛ ли стенд до читателя.
    # Маршрут, чей ответ на пустом каталоге тот же, что на настоящем, каталога
    # не открывал — и «нечувствителен к стенду» было бы про него неправдой, а
    # не осторожностью. Без этой пробы правка G27 обменяла бы одну слепоту на
    # другую, потише.
    empty_holder = tempfile.TemporaryDirectory(prefix="spa_g27_empty_")
    empty_data = Path(empty_holder.name) / "data"
    empty_data.mkdir(parents=True, exist_ok=True)
    stand_paths = {"s1": Path(stands["s1"]) / "data",
                   "s1_again": Path(stands["s1"]) / "data",
                   "s2": Path(stands["s2"]) / "data",
                   "s3": Path(stands["s3"]) / "data",
                   "empty": empty_data}
    clock = clock_kwarg(runner, now)
    doors: List[object] = []
    for label in _HTTP_PROBE_ORDER:
        answer, why = runner(stand_paths[label], names, tree_root, **clock)
        if answer is None:
            # Один упавший процесс обесценивает ВСЮ партию: трёх ответов на
            # вердикт не хватает, а достроить четвёртый нечем. Молчание здесь
            # прочиталось бы как «маршруты ни при чём».
            meta["failed_probe"] = label
            meta["reason"] = why
            empty_holder.cleanup()
            return {}, meta
        by_label[label] = answer
        doors.append(((answer.get("__clock__") or {}) if isinstance(answer, dict)
                      else {}).get("shared_now"))
    empty_holder.cleanup()
    meta["probes_done"] = len(by_label)
    meta["clock_pinned"] = bool(clock) and all(
        door == now.isoformat() for door in doors)
    if clock and not meta["clock_pinned"]:
        # Часы передали, а дверь ответила другим — это НЕ «закреплено». Строки
        # не получат `clock_injected`, и это сказано вслух (инв. #17).
        meta["clock_reason"] = ("часы переданы, но `_shared.now()` вернул иное: " +
                                ", ".join(sorted({str(d) for d in doors}))[:200])
    out: Dict[str, tuple] = {}
    for name in names:
        out[name] = tuple((by_label[label].get(name) or {})
                          for label in _HTTP_VERDICT_ORDER)
    return out, meta


#: Файл процесса-зонда. Зовётся ПО ПУТИ, а не ``-m``: ``-m`` импортирует пакет
#: ``spa_core.monitoring`` (и десятки модулей) раньше, чем зонд закрепит часы.
_HTTP_PROBE_SCRIPT = Path(__file__).resolve().with_name("_http_reader_probe.py")


def _run_http_probe(stand_data: Path, names: Sequence[str], tree_root: Path,
                    now: Optional[datetime] = None):
    """Один процесс: ``SPA_DATA_DIR`` и часы пинятся ДО импорта, ответ — файлом."""
    import subprocess
    with tempfile.TemporaryDirectory(prefix="spa_g27_http_") as tmp:
        mods = Path(tmp) / "modules.json"
        out = Path(tmp) / "answer.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env["SPA_DATA_DIR"] = str(stand_data)
        env.pop("SPA_CENSUS_PINNED_NOW", None)
        if now is not None:
            env["SPA_CENSUS_PINNED_NOW"] = now.isoformat()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run(
                [sys.executable,
                 str(Path(tree_root) / "spa_core" / "monitoring" / _HTTP_PROBE_SCRIPT.name),
                 str(mods), str(out)],
                cwd=str(tree_root), env=env, capture_output=True,
                timeout=_HTTP_PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"зов маршрутов не уложился в {_HTTP_PROBE_TIMEOUT_S} с"
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            return None, f"процесс-зовущий вышел кодом {proc.returncode}: {tail}"
        try:
            return json.loads(out.read_text(encoding="utf-8")), ""
        except (OSError, ValueError) as exc:
            return None, f"ответ процесса не прочитан: {type(exc).__name__}"


def classify_http_reader(module_name: str, probes: tuple,
                         clock_pinned: bool = False) -> dict:
    """Вердикт обработчику — ПО МАРШРУТАМ, и итог модуля собирается из них.

    Гранулярность здесь не вкусовая. Вердикт на ЦЕЛОМ модуле меряет объединение
    всех его ответов, и один шумный маршрут гасит соседей: замер 16.09 —
    ``rates_desk`` целиком уходил в «не воспроизводится» из-за ОДНОГО маршрута,
    пряча десять нечувствительных, а ``cockpit`` прятал два. Маршрут — это и
    есть то, что владелец видит на дашборде, поэтому он и единица.

    Итог модуля берётся по СИЛЬНЕЙШЕМУ сигналу: схлопывание хотя бы на одном
    маршруте есть свойство модуля, а «не измерено» ставится, только если не
    измерен НИ ОДИН маршрут — и тогда с причиной, преобладающей среди них, а не
    с общей строкой про HTTP.
    """
    row: Dict[str, object] = {"module": module_name, "entry": "http_routes",
                              "clock_injected": bool(clock_pinned)}
    s1, s1_again, s2, s3, empty = probes
    if s1.get("import_failed"):
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_IMPORT_FAILED,
                   reason=f"импорт не удался: {s1['import_failed']}")
        return row
    routes = s1.get("routes") or {}
    refused = s1.get("refused") or {}
    if not routes:
        row.update(outcome=READER_UNMEASURED, cause=CAUSE_HTTP_ROUTE,
                   reason=("читающего маршрута без обязательных аргументов у модуля "
                           f"нет: отказов {len(refused)} — " +
                           "; ".join(f"{p}: {why}" for p, why in
                                     sorted(refused.items())[:3])))
        row["routes_refused"] = refused
        return row
    per_route: Dict[str, dict] = {}
    for path in sorted(routes):
        unread = [a for a in (routes[path], (s1_again.get("routes") or {}).get(path))
                  if isinstance(a, dict) and UNREAD_RESPONSE in a]
        if unread:
            # Одинаковый ТИП ответа на всех стендах — не одинаковый ответ.
            per_route[path] = {"route": path, "outcome": READER_UNMEASURED,
                               "cause": CAUSE_RESPONSE_UNREAD,
                               "reason": (f"тело ответа {unread[0][UNREAD_RESPONSE]} "
                                          "прочитать нельзя (потоковый) — сравнивать "
                                          "нечего")}
            continue
        probes_in_order = (s1, s1_again, s2, s3, empty)
        answers = [(p.get("routes") or {}).get(path) for p in probes_in_order]
        # Момент выдачи узнаётся ЗАМЕРОМ по окну зова (заказ G30) и снимается у
        # всех пяти ответов одной меткой — иначе единственная плывущая
        # координата «когда отдано» гасила бы вердикт о стенде целиком.
        moment = call_moment_coords(
            answers, [(p.get("window") or {}).get(path) for p in probes_in_order])
        head: Dict[str, object] = {"route": path}
        if moment:
            answers = [a if a is None else mask_coords(a, moment, label=CALL_MOMENT_MARK)
                       for a in answers]
            head["call_moment_coords"] = sorted(moment)
        sub = verdict_from_probes(head, *answers[:4], on_empty=answers[4])
        per_route[path] = sub
    row["routes"] = per_route
    row["routes_refused"] = refused
    row["routes_by_outcome"] = dict(collections.Counter(
        str(v["outcome"]) for v in per_route.values()))
    for outcome in (READER_LAST, READER_FIRST, READER_BOTH, READER_INSENSITIVE):
        named = [p for p, v in per_route.items() if v["outcome"] == outcome]
        if named:
            row["outcome"] = outcome
            row["reason"] = (f"{len(named)} маршрут(ов) из {len(per_route)}: " +
                             ", ".join(sorted(named)[:4]) + " — " +
                             str(per_route[named[0]].get("reason")))
            return row
    causes = collections.Counter(str(v.get("cause")) for v in per_route.values())
    cause, count = causes.most_common(1)[0]
    row.update(outcome=READER_UNMEASURED, cause=cause,
               reason=(f"ни один из {len(per_route)} маршрутов не измерен; "
                       f"преобладающая причина — {cause} ({count})"))
    return row


# ── вопрос 5: ACT-дни, обеими границами, население — у ДЕНЕГ ─────────────────
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("%s не прочитан: %s", path, exc)
        return None


def runs_per_day(data_dir: Path) -> Tuple[Optional[Dict[str, int]], str]:
    """Сколько прогонов было в каждом дне — по НЕЗАВИСИМОМУ носителю.

    ``audit_trail`` пишет ``cycle_start`` на КАЖДЫЙ прогон; журнал вердиктов —
    подозреваемый, и считать прогоны по нему значило бы замкнуть прибор на
    предмет. День, которого в носителе нет вовсе, — ``None``, а не единица:
    молчание носителя не есть «прогон был один».
    """
    path = Path(data_dir) / AUDIT_FILENAME
    if not path.exists():
        return None, f"{AUDIT_FILENAME} не найден"
    counts: Dict[str, int] = collections.Counter()
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                event = obj.get("event") or obj.get("event_type") or obj.get("type")
                if event != "cycle_start":
                    continue
                stamp = str(obj.get("timestamp") or obj.get("ts") or "")
                if len(stamp) >= 10:
                    counts[stamp[:10]] += 1
    except OSError as exc:
        return None, f"{AUDIT_FILENAME} не прочитан: {exc}"
    return dict(counts), ""


def act_day_bounds(data_dir: Path, *, trial_mark: Optional[str] = None) -> dict:
    """Сколько ACT-дней вернул бы ключ прогона — обеими границами.

    Население — история сделок. Журнал здесь подозреваемый, и выводить из него
    население значило бы не найти ровно тот день, который журнал потерял.
    """
    if trial_mark is None:
        try:
            from spa_core.paper_trading.cio_trial import MARK as trial_mark
        except Exception:  # noqa: BLE001 — второй копии правила тут нет
            return {"measured": False,
                    "reason": "метка разрешения владельца недоступна — нижняя граница "
                              "не измерена, и подставлять её нулём запрещено"}
    rows, why = read_history(Path(data_dir))
    if rows is None:
        return {"measured": False, "reason": why}
    trades_doc = _read_json(Path(data_dir) / TRADES_FILENAME)
    if trades_doc is None:
        return {"measured": False, "reason": f"{TRADES_FILENAME} не прочитан"}
    trades = trades_doc.get("trades") if isinstance(trades_doc, dict) else trades_doc
    if not isinstance(trades, list):
        return {"measured": False, "reason": f"{TRADES_FILENAME} не несёт списка ходов"}
    runs, runs_why = runs_per_day(Path(data_dir))

    # Строка дня — ПОСЛЕДНЯЯ в файле для этой даты: именно её видит читатель.
    line_of_day: Dict[str, dict] = {}
    for row in rows:
        date = row.get("cycle_date")
        if date:
            line_of_day[str(date)] = row

    by_day: Dict[str, List[dict]] = collections.defaultdict(list)
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        stamp = str(trade.get("ts") or "")
        if len(stamp) >= 10:
            by_day[stamp[:10]].append(trade)

    lower: List[dict] = []
    upper: List[dict] = []
    outside: List[dict] = []
    not_journaled: List[dict] = []
    for date in sorted(by_day):
        day_trades = by_day[date]
        marked = [t for t in day_trades if t.get(trial_mark)]
        record = line_of_day.get(date)
        detail = {
            "date": date,
            "trades": len(day_trades),
            "marked_trades": len(marked),
            "runs_in_day": runs.get(date) if runs is not None else None,
            "journal_verdict": (str(record.get("verdict")).upper() if record else None),
            "line_generated_at": record.get("generated_at") if record else None,
        }
        if record is None:
            detail["why"] = ("строки дня в журнале нет вовсе — заменять было нечего; "
                             "в границы не входит ни в одну")
            outside.append(detail)
            continue
        verdict = str(record.get("verdict") or "").upper()
        if verdict == "ACT":
            detail["why"] = "день уже несёт ACT — терять было нечего"
            continue
        line_ts = _parse_ts(record.get("generated_at"))
        first_move = min((_parse_ts(t.get("ts")) for t in day_trades
                          if _parse_ts(t.get("ts")) is not None), default=None)
        if line_ts is None or first_move is None:
            detail["why"] = "отметка строки или хода не разобрана — день НЕ ИЗМЕРЕН"
            detail["unmeasured"] = True
            outside.append(detail)
            continue
        if line_ts <= first_move:
            detail["why"] = ("выжившая строка НАПИСАНА РАНЬШЕ хода — прогон хода "
                             "строки не оставил вовсе; это не замена")
            not_journaled.append(detail)
            continue
        runs_in_day = detail["runs_in_day"]
        if runs_in_day is not None and runs_in_day < 2:
            detail["why"] = ("в дне один прогон по независимому носителю — заменять "
                             "было некому")
            not_journaled.append(detail)
            continue
        if marked:
            detail["why"] = ("ход несёт метку разрешения владельца — вердикт ACT "
                             "НАБЛЮДЁН, а не реконструирован")
            lower.append(detail)
        else:
            detail["why"] = ("ход был, строка написана ПОЗЖЕ него, прогонов в дне "
                             "не менее двух — замена МОГЛА стереть ACT")
        upper.append(detail)

    unmeasured_days = [d for d in outside if d.get("unmeasured")]
    return {
        "measured": not unmeasured_days,
        "trial_mark": trial_mark,
        "trade_days": len(by_day),
        "lower": len(lower),
        "upper": len(upper),
        "lower_days": [d["date"] for d in lower],
        "upper_days": [d["date"] for d in upper],
        "outside_journal_window": [d["date"] for d in outside],
        "not_replacement": [d["date"] for d in not_journaled],
        "runs_carrier": ("audit_trail" if runs is not None else None),
        "runs_carrier_reason": runs_why,
        "days": lower + [d for d in upper if d not in lower] + outside + not_journaled,
        "reason": ("" if not unmeasured_days else
                   f"{len(unmeasured_days)} дн. населения не разобраны по отметкам"),
    }


# ── замер ────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            tree_root: Optional[Path] = None,
            day: Optional[str] = None,
            sweep_readers: bool = True,
            stand_dest: Optional[Path] = None) -> dict:
    """Полный замер G16. Читает; своего артефакта здесь не пишет.

    ``sweep_readers=False`` отключает самую дорогую часть — прогон читателей на
    стендах; остальные три ответа от неё не зависят и меряются всегда.
    """
    now = now or _utcnow()
    data_dir = Path(data_dir)
    tree_root = Path(tree_root) if tree_root else Path(__file__).resolve().parents[2]
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "question": ("во что обойдётся отмена двойного счёта — ключ прогона вместо "
                     "даты — и сколько ACT-дней это вернуло бы (заказ #602/G16)"),
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
        "advisory": _ADVISORY,
    }

    rows, why = read_history(data_dir)
    doc["journal"] = ({"lines": len(rows),
                       "dates": len({r.get("cycle_date") for r in rows}),
                       "act_lines": sum(1 for r in rows
                                        if str(r.get("verdict") or "").upper() == "ACT")}
                      if rows is not None else {"lines": None, "reason": why})

    key = probe_key_fields()
    doc["key_probe"] = key
    date_derived = key.get("date_derived", []) if key.get("measured") else []

    doc["migration"] = (measure_migration(rows, date_derived=date_derived)
                        if rows is not None
                        else {"measured": False, "reason": why})

    doc["act_bounds"] = act_day_bounds(data_dir)

    if not sweep_readers:
        doc["readers"] = {"measured": False,
                          "reason": "прогон читателей отключён вызовом (sweep_readers=False)"}
        return _verdict(doc)

    global _SWEEPING
    if _SWEEPING:
        doc["readers"] = {"measured": False,
                          "reason": ("повторный вход в перепись читателей — прибор "
                                     "позван изнутри собственного прогона")}
        return _verdict(doc)

    roads, stats = reader_population(tree_root)
    readers: Dict[str, object] = {"population_stats": stats}
    tmp_parent = Path(stand_dest) if stand_dest else None
    holder = None
    if tmp_parent is None:
        holder = tempfile.TemporaryDirectory(prefix="spa_g16_stands_")
        tmp_parent = Path(holder.name)
    _SWEEPING = True
    try:
        stands, stand_why = build_stands(data_dir, tmp_parent, day=day)
        if stands is None:
            readers.update(measured=False, reason=f"стенды не построены: {stand_why}")
            doc["readers"] = readers
            return _verdict(doc)
        readers["stand"] = {"day": stands["day"], "donor_day": stands["donor_day"],
                            "rewritten_fields": stands["rewritten_fields"],
                            "day_rule": stands.get("day_rule"),
                            "excluded_from_copy": list(STAND_EXCLUDE)}
        readers["what_the_counts_are"] = (
            "число схлопывающих есть НИЖНЯЯ ГРАНИЦА, а не перепись: вердикт читателю "
            "выносится на ОДНОМ дне стенда, и оконный читатель, которого этот день не "
            "задел, честно уходит в insensitive_stand, а не в «не схлопывает». "
            "Вторая причина той же односторонности: нестабильные координаты СНИМАЮТСЯ, "
            "и если разница между стендами легла ТОЛЬКО в снятую координату, читатель "
            "прочтётся как insensitive_stand. Граница смещена в сторону НЕДОоценки — "
            "прибор скорее промолчит о схлопывании, чем выдумает его")
        # Обработчики HTTP-маршрутов зовутся ПАРТИЕЙ и отдельными процессами
        # (см. `http_probe_batch`): каталог стенда доходит до них переменной
        # `SPA_DATA_DIR`, выставленной ДО импорта. До заказа G27 они все стояли
        # под причиной `http_route_handler` — самой многочисленной группой не
        # измеренных, и ровно той, чей ответ владелец видит на дашборде.
        http_names = http_modules(sorted(roads))
        http_probes, http_meta = http_probe_batch(stands, http_names, Path(tree_root),
                                                  now=now)
        readers["http_batch"] = http_meta
        rowsout: List[dict] = []
        for name in sorted(roads):
            if name == __name__ or name.endswith(".run_identity_key_price"):
                row = {"module": name, "outcome": READER_UNMEASURED,
                       "cause": CAUSE_SELF,
                       "reason": ("это сам прибор: он ГОНИТ перепись, и гнать его "
                                  "внутри неё значило бы войти в неё заново")}
            elif name in http_probes:
                row = classify_http_reader(
                    name, http_probes[name],
                    clock_pinned=bool(http_meta.get("clock_pinned")))
            else:
                row = classify_reader(name, stands, now=now)
            row["roads"] = sorted(roads[name])
            rowsout.append(row)
        readers["measured"] = True
        readers["modules"] = rowsout
        readers["outcomes"] = dict(collections.Counter(str(r["outcome"]) for r in rowsout))
        # Инв. #17: «не измерено» обязано быть представлено РАЗЛИЧИМЫМИ
        # значениями. Пока причина была одна на всех, число 64 отвечало на
        # вопрос «сколько прибор не умеет спросить», а читалось как «сколько
        # читателей ни при чём».
        readers["unmeasured_causes"] = dict(collections.Counter(
            str(r.get("cause") or "cause_not_recorded")
            for r in rowsout if r.get("outcome") == READER_UNMEASURED))
    finally:
        _SWEEPING = False
        if holder is not None:
            holder.cleanup()
    doc["readers"] = readers
    return _verdict(doc)


def _verdict(doc: dict) -> dict:
    """Общий вердикт. НЕ ИЗМЕРЕНО обязано быть отличимо от «чисто»."""
    key = doc.get("key_probe") or {}
    readers = doc.get("readers") or {}
    bounds = doc.get("act_bounds") or {}
    # Отсутствие поля пробы — НЕ «ключ различает прогоны». Умолчание в эту
    # сторону было бы fail-OPEN: молчание пробы прочиталось бы как хорошая
    # новость, а «не измерено» обязано быть отличимо от «чисто» (инв. #17).
    key_answered = key.get("measured") and "decision_id_distinguishes_runs" in key
    if not key_answered or not bounds.get("measured"):
        doc["overall"] = STATUS_UNMEASURED
        doc["reason"] = (key.get("reason") or bounds.get("reason")
                         or "часть ответа не измерена: проба ключа не назвала вердикт")
        return doc
    outcomes = readers.get("outcomes") or {}
    collapsing = int(outcomes.get(READER_LAST, 0)) + int(outcomes.get(READER_FIRST, 0))
    renamed = not key.get("decision_id_distinguishes_runs", True)
    if readers.get("measured") and collapsing:
        doc["overall"] = STATUS_CRITICAL
        doc["reason"] = (
            f"починка ОДНОГО писателя до критерия НЕ ДОХОДИТ: не менее {collapsing} "
            f"читател(я/ей) из {len(readers.get('modules') or [])} схлопывают день САМИ, "
            f"и среди них сам критерий взвода. ACT-дней вернулось бы "
            f"{bounds.get('lower')}–{bounds.get('upper')}")
    elif renamed:
        doc["overall"] = STATUS_WARNING
        doc["reason"] = ("ключ decision_id выведен из даты — предложенная замена ключа "
                         "не меняет ничего")
    else:
        doc["overall"] = STATUS_OK
        doc["reason"] = "ключ прогона различает прогоны, схлопывающих читателей нет"
    return doc


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Обе границы — одной строкой, середины нет."""
    out: List[str] = []
    out.append(f"   цена отмены двойного счёта в журнале (заказ #602/G16): "
               f"{doc.get('overall', STATUS_UNMEASURED)}")
    if doc.get("reason"):
        out.append(f"   [ОТВЕТ] {doc['reason']}")
    key = doc.get("key_probe") or {}
    if key.get("measured"):
        verdict = ("НЕ различает прогоны — переименованная дата"
                   if not key.get("decision_id_distinguishes_runs") else "различает прогоны")
        out.append(f"   [КЛЮЧ] decision_id = {key.get('decision_id_value')!r}: {verdict}; "
                   f"полей, зависящих только от даты — {len(key.get('date_derived') or [])}, "
                   f"различающих прогон — {len(key.get('run_distinct') or [])}")
    else:
        out.append(f"   [КЛЮЧ] НЕ ИЗМЕРЕНО: {key.get('reason')}")
    # Инв. #17: непрочитанная миграция обязана быть НАЗВАНА, а не исчезнуть из
    # отчёта. Пустой раздел молча неотличим от «мерили и нечего печатать».
    mig = observed(doc, "migration", kind=dict)
    if mig is None or not mig.get("measured", True):
        out.append(f"   [МИГРАЦИЯ] НЕ ИЗМЕРЕНО: "
                   f"{(mig or {}).get('reason') or 'раздел миграции не прочитан'}")
        mig = {}
    for field, row in sorted((mig.get("by_candidate") or {}).items()):
        out.append(f"   [МИГРАЦИЯ] {field}: строк с ключом {row['rows_with_key']}/"
                   f"{row['rows_total']}, чеканить задним числом {row['rows_needing_minted_key']}, "
                   f"столкновений {row['collisions']} — {row['verdict']}")
    readers = doc.get("readers") or {}
    if readers.get("measured"):
        counts = readers.get("outcomes") or {}
        stand = readers.get("stand") or {}
        out.append(f"   [ЧИТАТЕЛИ] население {len(readers.get('modules') or [])} "
                   f"(имя файла {len((readers.get('population_stats') or {}).get('via_filename_only') or [])} · "
                   f"граф импортов {len((readers.get('population_stats') or {}).get('via_imports_only') or [])} · "
                   f"обе дороги {len((readers.get('population_stats') or {}).get('via_both') or [])}); "
                   f"стенд на дне {stand.get('day')} ({stand.get('day_rule')})")
        out.append("   [ЧИТАТЕЛИ] " + " · ".join(
            f"{name} {counts.get(name, 0)}" for name in
            (READER_LAST, READER_FIRST, READER_BOTH, READER_INSENSITIVE, READER_UNMEASURED)))
        for row in readers.get("modules") or []:
            if row.get("outcome") in (READER_LAST, READER_FIRST):
                out.append(f"       [СХЛОПЫВАЕТ] {row['module']} ({row.get('entry')})")
        # Инв. #17: причина «не измерено» печатается ЧИСЛОМ по каждому классу.
        # Одно суммарное число молча читается как «эти читатели ни при чём»,
        # тогда как отвечает оно на другой вопрос — «о скольких прибор не умеет
        # спросить». Пустая сводка при непустом `unmeasured` — тоже отчёт.
        causes = readers.get("unmeasured_causes")
        n_un = (readers.get("outcomes") or {}).get(READER_UNMEASURED, 0)
        if n_un and not causes:
            out.append("       [ПРИЧИНЫ] НЕ ИЗМЕРЕНО: причины не записаны, "
                       f"а не измеренных {n_un} — число без причины непригодно")
        for cause, n in sorted((causes or {}).items(), key=lambda kv: (-kv[1], kv[0])):
            out.append(f"       [ПРИЧИНА] {cause}: {n}")
        for row in readers.get("modules") or []:
            if row.get("cause") == CAUSE_WOULD_ACT:
                out.append(f"       [ОТКАЗ ЗВАТЬ] {row['module']} — {row.get('reason')}")
        # Эти читатели и были прежним ПОДБРАСЫВАНИЕМ МОНЕТЫ: до ADR-396 они
        # всплывали в `collapses_to_last` и пропадали из него через прогон.
        # Число без имён вернуло бы их в безымянность — назвать обязан отчёт.
        for row in readers.get("modules") or []:
            if row.get("cause") == CAUSE_RESTS_ON_UNSTABLE:
                out.append(f"       [СУДИТЬ НЕЧЕМ] {row['module']} "
                           f"({row.get('entry')}) — {row.get('reason')}")
    else:
        out.append(f"   [ЧИТАТЕЛИ] НЕ ИЗМЕРЕНО: {readers.get('reason')}")
    bounds = doc.get("act_bounds") or {}
    if bounds.get("measured"):
        out.append(f"   [ГРАНИЦЫ] ACT-дней вернулось бы [{bounds.get('lower')}, "
                   f"{bounds.get('upper')}] из {bounds.get('trade_days')} дн. с ходами; "
                   f"вне окна журнала {len(bounds.get('outside_journal_window') or [])}, "
                   f"не замена {len(bounds.get('not_replacement') or [])}")
        out.append(f"   [ГРАНИЦЫ] нижняя: {', '.join(bounds.get('lower_days') or []) or '—'}")
    else:
        out.append(f"   [ГРАНИЦЫ] НЕ ИЗМЕРЕНО: {bounds.get('reason')}")
    out.append(f"   {_ADVISORY}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        data_dir: Optional[str] = None, write: bool = True,
        sweep_readers: bool = True) -> dict:
    """Замер + артефакт. ``write=False`` — посчитать, не трогая диск."""
    base = Path(data_dir) if data_dir else Path(root or ".") / "data"
    doc = measure(base, now=now, sweep_readers=sweep_readers)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(base) / ARTIFACT))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="G16: цена отмены двойного счёта в журнале решений")
    ap.add_argument("--root", default=".")
    ap.add_argument("--data-dir", default=None,
                    help="каталог data/ (из worktree живого data/ нет по построению)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    ap.add_argument("--no-readers", action="store_true",
                    help="не гонять читателей на стендах (самая дорогая часть)")
    args = ap.parse_args(argv)

    doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write,
              sweep_readers=not args.no_readers)
    for line in format_report(doc):
        print(line)
    codes = {STATUS_OK: 0, STATUS_WARNING: 1, STATUS_CRITICAL: 1, STATUS_UNMEASURED: 2}
    return codes.get(str(doc.get("overall") or ""), 2)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
