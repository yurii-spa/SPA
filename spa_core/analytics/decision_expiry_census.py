"""decision_expiry_census.py — §28 ТЗ «Portfolio CIO»: Decision expiry.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §28 «Decision expiry»::

    Каждое investment decision должно иметь TTL.
    Например:
    valid_until
    Если execution не произошел до TTL:
    решение нельзя выполнять без нового расчета.

🪤 ВОПРОС §28 ВЛАДЕЛЬЦУ УЖЕ ЗАДАН И УЖЕ ОТВЕЧЕН — 27.10, ВАРИАНТ А
==================================================================
Заказ G959 пп. 2–3 велел завести карточку владельцу («нужна ли предпусковая проверка на
бумаге»). Предпосылка заказа ОПРОВЕРГНУТА разбором очереди: карточка
``owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch`` (27.09) спрашивала ровно это
про §27 **и §28 сразу**, и владелец ответил **27.10, вариант А**: допуск свежести входа
**60 с на бумаге / 15 с вживую**, срок годности решения **10 мин** (реестр ответов
ADR-839 — ``docs/decisions/owner-answers-2026-10-27-session.json``, запись ADR-836).
Спросить второй раз — дефект очереди (ADR-285), поэтому карточки нет, а числа владельца
ВВОЗЯТСЯ из реестра (:func:`import_owner_answer`) и сверяются с константами прибора
(:data:`OWNER_TTL_S`, :data:`OWNER_FRESHNESS_S`) — число живёт дважды, расхождение
краснеет.

Предмет §28 после этого — не «есть ли TTL», а **исполнен ли ответ владельца**: попал ли
срок годности в колонку владельца (``TriggerParams``), и способен ли читатель этой колонки
(ADR-487) взять из неё ЗНАЧЕНИЕ, а не только имя ручки.

Второго прибора на один предмет НЕ заводится — ввозятся четверо
================================================================
* **ADR-487** (``pre_trade_recheck_census``): ``ttl_declared = 0 из 46`` и колонка
  владельца (``load_owner_tolerance``) — ввоз, не перемер (G959 п. 1 (а)).
* **§25 / ADR-968** (``decision_payload_census``): поле владельца №28 «decision expiry»
  делегировано (``DELEGATED_FIELDS``) — то есть владелец назвал срок годности ДВАЖДЫ, в
  §25 как поле записи и в §28 как раздел; вердикт делегата ввозится дословно.
* **§22 / ADR-965** (``anti_churn_census``): величина «decision expiry» среди девяти
  величин §22 — её исход ввозится строкой переписи.
* **§26 / ADR-969 и §27 / ADR-970**: «истёк ли TTL» есть сравнение с ``now``, а ``now`` у
  субъектов не вход (G959 п. 1 (в)) — ось часов ввозится из §27 (``measure_clock_at_both_events``),
  словари ``PIN_KINDS``/``RUN_IDENTITY_FIELDS`` — из §26.

Оси (то, чего у соседей нет)
============================
* **A — ответ владельца**: запись реестра ADR-839 найдена · выбор · паритет чисел с
  константами · возраст ответа · статус карточки.
* **B — колонка владельца и её читатель**: ручки ``TriggerParams`` (ввоз ADR-487) + контроль
  СПОСОБНОСТИ читателя: загрузчику подаётся сцена с ручкой ``decision_ttl_s`` — берёт ли он
  ЗНАЧЕНИЕ (``tolerance_s``) или только ИМЯ (``ttl_dial``). Замер #1089: имя брал, значение —
  никогда (``tolerance_s`` у него был литерал ``None``). Исполнено ADR-972 (цикл #1090):
  колонка v1.2 несёт ``input_freshness_tolerance_s`` (60/15 с) и ``decision_ttl_s`` (600 с),
  читатель берёт оба значения. Ось B теперь сверяет ЧИСЛА колонки с ответом владельца
  (``column_matches_answer``): ручка с чужим числом — не исполнение, а подмена
  (``owner_answer_misexecuted``, CRITICAL).
* **C — роли полей времени у записи решения**: у живой записи (носитель ``shadow`` §25,
  ``allocation_rationale_history.jsonl``) каждое поле, похожее на время, получает РОЛЬ:
  ``birth_stamp`` (штамп прогона, §26 ``RUN_IDENTITY_FIELDS``) · ``identity_date`` (дата в
  имени — ``decision_id = adr060-shadow-<дата>``, G959 п. 1 (г): это ярлык, не срок) ·
  ``input_stamp`` (``apy_as_of`` — возраст ВХОДА, не решения) · ``expiry``. Полей роли
  ``expiry`` — ноль, и это измерено, а не предположено.
* **D — «похожие на TTL» окна дерева**: в дереве много сроков годности, и ни один из них
  не про решение: окно свежести свидетельства (36 ч — ВХОД), кэш фида (ВХОД), возраст
  маячка бота (АРТЕФАКТ), живость сторожа (ПРОЦЕСС), ``slo_hours`` паспортов агентов
  (АРТЕФАКТ, сотни объявлений). Каждое объявление проверено по коду/JSON. Спутать любое из
  них с TTL решения — класс «TTL советательной аналитики, окно протухания замка», против
  которого ADR-487 написал свой отказ.
* **E — дверь принуждения**: «нельзя выполнять без нового расчёта» требует двери между
  решением и исполнением, которая читает срок и ``now``. На бумаге второе событие пишет
  ТОТ ЖЕ процесс через ≤ 2 с (ввоз ADR-487/§27): срок владельца 600 с против окна
  ≤ 2 с — TTL на бумаге **недостижим по построению** (отношение печатается). Модуль
  повторной проверки (``GATE_MODULE`` ADR-487) слов срока годности не знает и зовущих на
  денежном пути не имеет (ввоз ``gate_reader_axis``).
* **F — часы у двери**: ввоз §27: вход цикла ``now`` принимает, субъекты — нет; у «истёк ли
  TTL» нет НИ ОДНОГО операнда: ни ``valid_until`` (ось C), ни ``now`` у субъекта (ADR-969).

Что модуль НЕ делает
====================
Не двигает капитал, не правит ``TriggerParams``, политику, гейт, прибор ADR-487 и ни одну
проверку. Не заводит карточку владельцу — вопрос отвечен. **Только называет.**
ADVISORY (``applied=False``).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── ВВЕЗЁННЫЕ СЛОВАРИ И ДВЕРИ. Своя копия мерки = «прибор отвечает о себе» ────
# §13 (ADR-956) — третий исход.
from spa_core.analytics.transaction_economics import UNMEASURED
# §26 (ADR-969): штампы прогона, словарь пришпиливаемости, дверь к идентификаторам кода.
from spa_core.analytics.determinism_census import (
    FIFTH_INPUT,
    PIN_KINDS,
    RUN_IDENTITY_FIELDS,
    _code_identifiers,
)
# §27 (ADR-970): двери к коду (использование ∪ определение), ось часов, ввоз ADR-487.
from spa_core.analytics.pre_trade_check_census import (
    CALLER_SURFACE,
    _callers_mention,
    _check_evidence,
    import_recheck_verdict,
    measure_clock_at_both_events,
)
# §25 (ADR-968): поле владельца «decision expiry» и вердикт делегата.
from spa_core.analytics import decision_payload_census as _s25
# §22 (ADR-965): величина «decision expiry» среди девяти величин.
from spa_core.analytics import anti_churn_census as _s22
# §24 (ADR-967): словарь типов решения — читатель для слова «новый расчёт».
from spa_core.analytics.decision_type_census import OWNER_DECISION_TYPES
# §49 / ADR-487: колонка владельца, подсказки имён ручек, модуль гейта и его читатели.
from spa_core.monitoring import pre_trade_recheck_census as _s49
# Честная форма чтения наблюдения (инв. #17).
from spa_core.utils.observation import observed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/decision_expiry_census.json"

#: Границы раздела §28 в карточке приказа. ОБЕ названы (ловушка §25/§27: без второй
#: границы в перечень попадает заголовок следующего раздела).
SECTION_HEAD = "28. Decision expiry"
NEXT_SECTION_HEAD = "29. Emergency mode"

#: Карточка приказа владельца — производитель чисел паритета.
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

#: Якоря §28 — УТВЕРЖДЕНИЕ о форме, проверяемое разбором.
_REQUIREMENT_LINE = "Каждое investment decision должно иметь TTL."
_EXAMPLE_LEAD = "Например:"
_CONDITION_LINE = "Если execution не произошел до TTL:"
_CONSEQUENCE_LINE = "решение нельзя выполнять без нового расчета."

#: Что владелец назвал в §28: ОДНО требование, ОДИН пример, ОДНО следствие.
OWNER_REQUIREMENTS_DECLARED = 1
OWNER_EXAMPLES_DECLARED = 1
OWNER_CONSEQUENCES_DECLARED = 1
#: Пример владельца дословно — слово, которого на записи решения нет.
OWNER_EXAMPLE_FIELD = "valid_until"
#: Сколько требований/следствий назвал заказ G959 п. 1 («мой счёт по первым строкам»).
#: Хранится, чтобы совпадение или недосчёт заказа был ИЗМЕРЕН отчётом (форма §27
#: ``ORDER_G958_NAMED``).
ORDER_G959_NAMED = {"requirements": 1, "consequences": 1}

# ── ось A: ответ владельца (ввоз реестра ADR-839) ────────────────────────────

#: Карточка, в которой владелец ответил на §27+§28 сразу, и реестр её ответа.
OWNER_ANSWER_CARD = "owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch"
OWNER_ANSWER_CARD_REL = f"nimbalyst-local/tracker/{OWNER_ANSWER_CARD}.md"
OWNER_ANSWER_REGISTER_REL = "docs/decisions/owner-answers-2026-10-27-session.json"
OWNER_ANSWER_ADR = "ADR-836"
#: Выбор владельца и его числа — КОНСТАНТЫ прибора, сверяемые с реестром (число живёт
#: дважды). Кириллическая «А» — так записано в реестре.
OWNER_CHOICE = "А"
OWNER_TTL_S = 600.0
OWNER_FRESHNESS_S: Dict[str, float] = {"paper": 60.0, "pilot": 15.0}
#: Где лежит исполнение ответа (карточка, которая его учитывает как НЕ исполненный).
EXECUTION_ADDRESS_CARD = "inbox-vosemnadtsat-otvetov-vladeltsa-27-10-isp"

ANSWER_KINDS: Tuple[str, ...] = (
    "answered_and_executed",      # ручки в колонке, читатель берёт значение
    "answered_not_executed",      # ответ есть, в колонке ничего
    "not_answered",               # записи в реестре нет
    UNMEASURED,
)

# ── ось B: колонка владельца и способность её читателя ───────────────────────

LOADER_KINDS: Tuple[str, ...] = (
    "reads_value",        # загрузчик берёт ЗНАЧЕНИЕ ручки (tolerance_s число)
    "names_dial_only",    # загрузчик находит ИМЯ ручки, значение не берёт
    UNMEASURED,
)

#: Имена ручек СЦЕНЫ для контроля читателя. Это НЕ предложение имён владельцу — любое
#: имя с подсказкой ADR-487 ``_TOLERANCE_HINTS`` даёт тот же ответ, и это проверяется.
_SCENE_TTL_DIAL = "decision_ttl_s"
_SCENE_FRESHNESS_DIAL = "input_freshness_tolerance_s"

# ── ось C: роли полей времени у записи решения ───────────────────────────────

TIME_FIELD_ROLES: Tuple[str, ...] = (
    "birth_stamp",     # штамп прогона (§26 RUN_IDENTITY_FIELDS) — когда родилось
    "identity_date",   # дата внутри ярлыка — КТО это, а не ДО КОГДА
    "input_stamp",     # возраст ВХОДА (as_of) — не возраст решения
    "expiry",          # срок годности РЕШЕНИЯ — то, что просит §28
    UNMEASURED,
)
#: Поля, у которых дата — часть ЛИЧНОСТИ решения (ADR-968: ``adr060-shadow-<дата>``).
IDENTITY_DATE_FIELDS: Tuple[str, ...] = ("cycle_date", "decision_id")
#: По каким признакам имя поля читается как «про время».
_TIME_LIKE_MARKS: Tuple[str, ...] = ("_at", "date", "time", "_ts", "as_of", "expir",
                                     "ttl", "valid", "deadline", "until")
#: Носитель записи решения — §25 зовёт его ``shadow``; имя файла берётся у §25.
RECORD_CARRIER = "shadow"
#: Писатель записи и имя, которым он чеканит ярлык (проверяется по коду).
RECORD_WRITER_REL = "spa_core/paper_trading/allocation_rationale.py"

# ── ось D: «похожие на TTL» окна дерева ──────────────────────────────────────

AGED_KINDS: Tuple[str, ...] = (
    "input",      # стареет ВХОД (свидетельство, кэш фида)
    "artifact",   # стареет файл/маячок
    "process",    # стареет живость процесса
    "decision",   # стареет РЕШЕНИЕ — то, что просит §28
    UNMEASURED,
)

#: ОБЪЯВЛЕНИЕ, проверяемое кодом: каждое окно годности дерева — что оно состаривает.
#: ``evidence`` — имена, обязанные быть в КОДЕ модуля (не в комментарии); ``json`` —
#: ключ, обязанный встречаться в документе хотя бы раз (число вхождений печатается).
LOOKALIKE_MAP: Dict[str, Dict[str, Any]] = {
    "окно свежести свидетельства (гейт годности)": {
        "kind": "input",
        "evidence": {"spa_core/allocator/allocator.py": ("_EVIDENCE_MAX_AGE_H",)},
        "ages": "возраст живой ставки/TVL у `_fundable` (36 ч) — вход, не решение",
    },
    "кэш ответа фида DeFiLlama": {
        "kind": "input",
        "evidence": {"spa_core/adapters/defillama_feed.py": ("cache_ttl",)},
        "ages": "ответ внешнего фида — вход",
    },
    "возраст маячка бота (кнопки владельцу)": {
        "kind": "artifact",
        "evidence": {"spa_core/telegram/alert_actions.py": ("BEACON_MAX_AGE_S",)},
        "ages": "файл-маячок умений бота (6 ч, ADR-400)",
    },
    "живость сторожа Telegram": {
        "kind": "process",
        "evidence": {"spa_core/monitoring/telegram_health.py": ("BEACON_MAX_AGE_S",)},
        "ages": "живость процесса (300 с) — другой вопрос, чем кнопки (ADR-400)",
    },
    "сроки годности артефактов в паспортах агентов": {
        "kind": "artifact",
        "json": ("architecture/manifest.json", "slo_hours"),
        "ages": "файл, который агент обязан обновлять (SLO в часах)",
    },
}

# ── ось E: дверь принуждения ─────────────────────────────────────────────────

ENFORCEMENT_KINDS: Tuple[str, ...] = (
    "gate_reads_ttl_on_path",   # дверь читает срок И стоит на денежном пути
    "gate_without_ttl",         # дверь есть, слов срока годности в её коде нет
    "no_gate_on_path",          # дверь не имеет ни одного зовущего на пути
    UNMEASURED,
)
#: Точные токены срока годности решения — спрашиваются у кода ТОКЕНОМ целиком
#: (по основе «valid» нашёлся бы `validate`, «fresh» — `refresh`: урок M8 §27).
EXPIRY_TOKENS: Tuple[str, ...] = ("valid_until", "expires_at", "decision_ttl",
                                  "decision_expiry", "ttl_s")


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _read_lines(path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines(), None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except UnicodeDecodeError as exc:  # pragma: no cover
        return None, f"UnicodeDecodeError: {exc}"


def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    """Строки РОВНО раздела §28: от его заголовка до заголовка §29."""
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == SECTION_HEAD:
            start = i
            break
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == NEXT_SECTION_HEAD:
            return lines[start + 1:j], None
    return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                  f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по "
                  f"нему был бы счётом неизвестно чего")


def _items_between(body: List[str], lead: str, stops: Tuple[str, ...]) -> List[str]:
    out: List[str] = []
    seen = False
    for ln in body:
        s = ln.strip()
        if not seen:
            if s == lead:
                seen = True
            continue
        if not s or s == "⸻":
            continue
        if s in stops:
            break
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    """РАЗБОР карточки — производитель чисел §28. Третий исход при любом сбое."""
    lines, why = _read_lines(card_path)
    if lines is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(lines)
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    for anchor in (_REQUIREMENT_LINE, _EXAMPLE_LEAD, _CONDITION_LINE, _CONSEQUENCE_LINE):
        if anchor not in stripped:
            return {"measured": False,
                    "reason": f"в §28 не найден якорь {anchor!r} — форма раздела "
                              f"не та, на которую написан разбор"}
    lead_at = stripped.index(_EXAMPLE_LEAD)
    requirements = [s for s in stripped[:lead_at] if s and s != "⸻"]
    examples = _items_between(body, _EXAMPLE_LEAD, (_CONDITION_LINE,))
    consequences = _items_between(body, _CONDITION_LINE, ())
    return {"measured": True, "reason": None, "requirements": requirements,
            "examples": examples, "condition": _CONDITION_LINE,
            "consequences": consequences}


def parity(card_path: str) -> Dict[str, Any]:
    """Константы прибора ↔ разбор карточки. Расхождение НАЗЫВАЕТСЯ, не прячется."""
    parsed = owner_section_from_card(card_path)
    if not parsed["measured"]:
        return {"agrees": None, "parsed": parsed, "mismatches": [],
                "order_g959_named": dict(ORDER_G959_NAMED),
                "order_undercount": None}
    mism: List[str] = []
    if parsed["requirements"] != [_REQUIREMENT_LINE]:
        mism.append(f"требования: карточка {parsed['requirements']} ≠ "
                    f"прибор {[_REQUIREMENT_LINE]}")
    if len(parsed["requirements"]) != OWNER_REQUIREMENTS_DECLARED:
        mism.append(f"число требований: карточка {len(parsed['requirements'])} ≠ "
                    f"объявлено {OWNER_REQUIREMENTS_DECLARED}")
    if parsed["examples"] != [OWNER_EXAMPLE_FIELD]:
        mism.append(f"пример: карточка {parsed['examples']} ≠ прибор {[OWNER_EXAMPLE_FIELD]}")
    if len(parsed["examples"]) != OWNER_EXAMPLES_DECLARED:
        mism.append(f"число примеров: карточка {len(parsed['examples'])} ≠ "
                    f"объявлено {OWNER_EXAMPLES_DECLARED}")
    if parsed["consequences"] != [_CONSEQUENCE_LINE]:
        mism.append(f"следствие: карточка {parsed['consequences']} ≠ "
                    f"прибор {[_CONSEQUENCE_LINE]}")
    if len(parsed["consequences"]) != OWNER_CONSEQUENCES_DECLARED:
        mism.append(f"число следствий: карточка {len(parsed['consequences'])} ≠ "
                    f"объявлено {OWNER_CONSEQUENCES_DECLARED}")
    undercount = ((len(parsed["requirements"]) - ORDER_G959_NAMED["requirements"])
                  + (len(parsed["consequences"]) - ORDER_G959_NAMED["consequences"]))
    return {"agrees": not mism, "parsed": parsed, "mismatches": mism,
            "order_g959_named": dict(ORDER_G959_NAMED),
            "order_undercount": undercount}


# ───────────────────────────── ось A: ответ владельца ────────────────────────

def _frontmatter(lines: List[str]) -> Dict[str, str]:
    """Плоские пары ``key: value`` из шапки карточки. Вложенность не нужна."""
    out: Dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return out
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def _parse_ts(raw: Any) -> Optional[dt.datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def _numbers_from_label(label: str) -> Dict[str, List[float]]:
    """Числа ответа владельца из текста реестра: секунды (``N с``) и минуты (``N мин``)."""
    secs = [float(x) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*с\b", label)]
    mins = [float(x) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*мин", label)]
    return {"seconds": secs, "minutes": mins}


def import_owner_answer(root: str = REPO_ROOT,
                        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Ось A: запись реестра ADR-839 для карточки §27+§28 — ввоз, не перемер.

    Паритет: числа из текста записи против констант прибора. Расхождение —
    отказ паритета, не подстановка. Возраст ответа — от ``owner_answered_at``
    карточки до ``now`` (вход, не окружение).
    """
    out: Dict[str, Any] = {"measured": True, "card": OWNER_ANSWER_CARD,
                           "register": OWNER_ANSWER_REGISTER_REL, "adr": OWNER_ANSWER_ADR,
                           "execution_address": EXECUTION_ADDRESS_CARD}
    reg_path = os.path.join(root, OWNER_ANSWER_REGISTER_REL)
    try:
        with open(reg_path, encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError) as exc:
        return {**out, "measured": False,
                "reason": f"реестр ответов не прочитан: {type(exc).__name__}: {exc}"}
    records: List[dict] = []
    if isinstance(reg, dict):
        for v in reg.values():
            if isinstance(v, list) and any(isinstance(r, dict) and "card" in r for r in v):
                records = [r for r in v if isinstance(r, dict)]
                break
    elif isinstance(reg, list):
        records = [r for r in reg if isinstance(r, dict)]
    # Сравнение имени ЦЕЛИКОМ (ADR-839 R1: подстрока пускала чужую карточку).
    hits = [r for r in records if r.get("card") == OWNER_ANSWER_CARD]
    if len(hits) != 1:
        out["record"] = None
        out["kind"] = "not_answered" if not hits else UNMEASURED
        out["reason"] = (f"в реестре {len(hits)} записей для {OWNER_ANSWER_CARD!r} — "
                         f"ожидалась ровно одна")
        return out
    rec = hits[0]
    out["record"] = {k: rec.get(k) for k in ("choice", "label", "owner_text", "adr", "kind")}
    label = str(rec.get("label") or "")
    nums = _numbers_from_label(label)
    mism: List[str] = []
    if rec.get("choice") != OWNER_CHOICE:
        mism.append(f"выбор: реестр {rec.get('choice')!r} ≠ прибор {OWNER_CHOICE!r}")
    declared_s = [OWNER_FRESHNESS_S["paper"], OWNER_FRESHNESS_S["pilot"]]
    if nums["seconds"] != declared_s:
        mism.append(f"допуски свежести: реестр {nums['seconds']} ≠ прибор {declared_s}")
    if [m * 60.0 for m in nums["minutes"]] != [OWNER_TTL_S]:
        mism.append(f"срок годности: реестр {nums['minutes']} мин ≠ прибор {OWNER_TTL_S} с")
    out["parity"] = {"agrees": not mism, "mismatches": mism,
                     "register_numbers": nums,
                     "declared": {"ttl_s": OWNER_TTL_S, "freshness_s": dict(OWNER_FRESHNESS_S)}}
    # Статус и момент ответа — у карточки (реестр момента не несёт).
    lines, why = _read_lines(os.path.join(root, OWNER_ANSWER_CARD_REL))
    if lines is None:
        out["card_status"] = UNMEASURED
        out["card_reason"] = f"карточка не прочитана: {why}"
        out["answered_at"] = None
        out["age_days"] = None
    else:
        fm = _frontmatter(lines)
        out["card_status"] = fm.get("status") or UNMEASURED
        answered = _parse_ts(fm.get("owner_answered_at"))
        out["answered_at"] = answered.isoformat() if answered else None
        if answered is None:
            out["age_days"] = None
        else:
            ref = now or dt.datetime.now(dt.timezone.utc)
            out["age_days"] = round((ref - answered).total_seconds() / 86400.0, 2)
    return out


# ───────────────────────── ось B: колонка и её читатель ──────────────────────

def measure_owner_column(params: Any = None) -> Dict[str, Any]:
    """Ось B: ручки владельца (ввоз ADR-487) + контроль читателя колонки.

    Контроль — сцена с ручкой срока годности, поданная ТОМУ ЖЕ загрузчику: если и
    на сцене ``tolerance_s`` остаётся ``None``, то читатель берёт из колонки ИМЯ, а
    не ЗНАЧЕНИЕ, и исполнение ответа владельца одной ручкой невозможно —
    второй шаг обязан быть у читателя.
    """
    out: Dict[str, Any] = {"measured": True, "source": "ADR-487 load_owner_tolerance (ввоз)"}
    try:
        live = _s49.load_owner_tolerance(params)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"дверь ADR-487 к колонке упала: {type(exc).__name__}: {exc}"}
    if not live.get("measured"):
        return {"measured": False, "reason": f"колонка не прочитана: {live.get('reason')}"}
    dials = observed(live, "dials", kind=dict) or {}
    out["dials"] = sorted(dials)
    out["dials_n"] = len(dials)
    out["version"] = live.get("version")
    out["mode"] = live.get("mode")
    out["ttl_dial"] = live.get("ttl_dial")
    out["tolerance_dial"] = live.get("tolerance_dial")
    out["tolerance_s"] = live.get("tolerance_s")
    out["ttl_s"] = live.get("ttl_s")
    out["hints"] = list(_s49._TOLERANCE_HINTS)
    # Паритет ЧИСЕЛ колонки с ответом владельца (ADR-836, вариант А). Ручка есть, а число
    # чужое — это не исполнение, и сторож обязан это различать от «ручки нет».
    out["column_matches_answer"] = _column_matches_answer(out)
    # Контроль читателя: сцена с ручкой — берёт ли он значение?
    scene = types.SimpleNamespace(**{_SCENE_TTL_DIAL: OWNER_TTL_S,
                                     _SCENE_FRESHNESS_DIAL: OWNER_FRESHNESS_S["paper"],
                                     "version": "scene", "mode": "paper"})
    try:
        probe = _s49.load_owner_tolerance(scene)
    except Exception as exc:  # noqa: BLE001
        out["loader"] = {"kind": UNMEASURED,
                         "reason": f"загрузчик упал на сцене: {type(exc).__name__}: {exc}"}
        return out
    named = probe.get("ttl_dial") in (_SCENE_TTL_DIAL, _SCENE_FRESHNESS_DIAL)
    value = probe.get("tolerance_s")
    reads = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not named:
        kind = UNMEASURED
        why = ("сцена с ручкой срока годности НЕ опознана загрузчиком по его же "
               f"подсказкам {list(_s49._TOLERANCE_HINTS)} — контроль не состоялся")
    elif reads:
        kind = "reads_value"
        why = f"на сцене загрузчик вернул tolerance_s={value!r} — значение берётся"
    else:
        kind = "names_dial_only"
        why = (f"на сцене загрузчик назвал ручку {probe.get('ttl_dial')!r}, а "
               f"tolerance_s={value!r}: имя берётся, значение — нет. Ручка в колонке "
               f"сама по себе судить старость не начнёт")
    assert kind in LOADER_KINDS
    out["loader"] = {"kind": kind, "reason": why, "scene_dials": [_SCENE_TTL_DIAL,
                                                                  _SCENE_FRESHNESS_DIAL]}
    return out


def _column_matches_answer(column: Dict[str, Any]) -> Dict[str, Any]:
    """Сходятся ли числа ручек колонки с числами ответа владельца — три исхода.

    ``kind``: ``matches`` · ``differs`` (расхождения названы) · ``unmeasured`` (ручки нет
    или режим колонки не из словаря ответа — сравнивать нечего, и это не «сошлось»).
    """
    mode = column.get("mode")
    expected_fresh = OWNER_FRESHNESS_S.get(str(mode)) if mode is not None else None
    ttl_s, fresh_s = column.get("ttl_s"), column.get("tolerance_s")
    if column.get("ttl_dial") is None or column.get("tolerance_dial") is None:
        return {"kind": UNMEASURED,
                "reason": "в колонке нет обеих ручек ответа — сравнивать с ответом нечего"}
    if expected_fresh is None:
        return {"kind": UNMEASURED,
                "reason": f"режим колонки {mode!r} не назван в ответе владельца "
                          f"({sorted(OWNER_FRESHNESS_S)}) — ожидаемого допуска нет"}
    mismatches: List[str] = []
    if not isinstance(ttl_s, (int, float)) or abs(float(ttl_s) - OWNER_TTL_S) > 1e-9:
        mismatches.append(f"срок годности решения: колонка {ttl_s!r}, владелец {OWNER_TTL_S:.0f} с")
    if not isinstance(fresh_s, (int, float)) or abs(float(fresh_s) - expected_fresh) > 1e-9:
        mismatches.append(f"допуск свежести ({mode}): колонка {fresh_s!r}, "
                          f"владелец {expected_fresh:.0f} с")
    if mismatches:
        return {"kind": "differs", "reason": "; ".join(mismatches), "mismatches": mismatches}
    return {"kind": "matches", "reason": f"ttl {OWNER_TTL_S:.0f} с · допуск {expected_fresh:.0f} с ({mode})"}


# ───────────────────────── ось C: роли полей времени ─────────────────────────

def _time_like(name: str) -> bool:
    """Поле «про время»: ярлык с датой внутри (ADR-968) или имя с меткой времени."""
    if name in IDENTITY_DATE_FIELDS:
        return True
    low = name.lower()
    return any(mark in low for mark in _TIME_LIKE_MARKS)


def _role_of(name: str) -> str:
    low = name.lower()
    if any(h in low for h in _s49._TOLERANCE_HINTS) or "until" in low or "deadline" in low:
        return "expiry"
    if name in RUN_IDENTITY_FIELDS:
        return "birth_stamp"
    if name in IDENTITY_DATE_FIELDS:
        return "identity_date"
    if "as_of" in low:
        return "input_stamp"
    return UNMEASURED


def _last_record(path: str) -> Tuple[Optional[dict], Optional[str], int]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}", 0
    if not raw:
        return None, "носитель пуст — записи решения нет", 0
    try:
        rec = json.loads(raw[-1])
    except ValueError as exc:
        return None, f"последняя строка не JSON: {exc}", len(raw)
    if not isinstance(rec, dict):
        return None, "последняя запись не словарь", len(raw)
    return rec, None, len(raw)


def measure_record_time_fields(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось C: у каждого поля времени живой записи решения — РОЛЬ.

    Имя носителя берётся у §25 (``CARRIER_ARTIFACT[RECORD_CARRIER]``): своё имя файла
    было бы второй копией одного адреса. Претензия «``decision_id`` — ярлык с датой»
    проверяется по коду писателя. Ввоз §25 (делегированный вердикт) и §22 (строка
    величины) — рядом, не вместо.
    """
    out: Dict[str, Any] = {"measured": True, "carrier": RECORD_CARRIER}
    fname = _s25.CARRIER_ARTIFACT.get(RECORD_CARRIER)
    if not fname:
        return {"measured": False,
                "reason": f"§25 не называет файла носителя {RECORD_CARRIER!r}"}
    out["artifact"] = fname
    rec, why, n = _last_record(os.path.join(data_dir, fname))
    out["records_n"] = n
    if rec is None:
        out["fields"] = None
        out["reason"] = f"запись решения не прочитана: {why}"
        out["expiry_fields"] = None
    else:
        fields: Dict[str, str] = {}
        for key in sorted(rec):
            if _time_like(key):
                fields[key] = _role_of(key)
        out["fields"] = fields
        out["expiry_fields"] = sorted(k for k, r in fields.items() if r == "expiry")
        out["roles_tally"] = {r: sum(1 for v in fields.values() if v == r)
                              for r in TIME_FIELD_ROLES}
        out["owner_example_present"] = OWNER_EXAMPLE_FIELD in rec
    # Претензия (г) G959: дата в ярлыке — личность, не срок. Проверяется у писателя.
    cache: Dict[str, Any] = {}
    ok, problems = _check_evidence(root, {RECORD_WRITER_REL: ("decision_id", "cycle_date")},
                                   cache)
    out["writer_claim"] = {"module": RECORD_WRITER_REL,
                           "kind": ("confirmed" if ok is True else
                                    UNMEASURED if ok is None else "refuted"),
                           "problems": problems}
    # Ввоз §25: делегированный вердикт поля «decision expiry».
    deleg = _s25.DELEGATED_FIELDS.get("decision_expiry")
    out["s25_delegated"] = ({"section": deleg.get("section"), "adr": deleg.get("adr"),
                             "verdict": deleg.get("verdict")} if deleg else None)
    out["s25_field_28_named"] = any(k == "decision_expiry" for k, _ in _s25.OWNER_FIELDS_25)
    # Ввоз §22: строка величины «decision expiry».
    try:
        rep22 = _s22.census(Path(root))
        row = next((p for p in rep22.get("params", [])
                    if p.get("param") == "decision expiry"), None)
        out["s22_row"] = ({"outcome": row.get("outcome"), "detail": row.get("detail")}
                          if row else {"outcome": UNMEASURED,
                                       "detail": "§22 не отдал строку «decision expiry»"})
    except Exception as exc:  # noqa: BLE001
        out["s22_row"] = {"outcome": UNMEASURED,
                          "detail": f"перепись §22 упала: {type(exc).__name__}: {exc}"}
    return out


# ───────────────────────── ось D: похожие на TTL ─────────────────────────────

def _count_json_key(path: str, key: str) -> Tuple[Optional[int], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    n = 0
    stack = [doc]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            n += sum(1 for k in cur if k == key)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return n, None


def measure_lookalikes(root: str = REPO_ROOT) -> Dict[str, Any]:
    """Ось D: каждое окно годности дерева — ЧТО оно состаривает. Объявление проверено."""
    out: Dict[str, Any] = {"measured": True, "windows": {}}
    cache: Dict[str, Any] = {}
    for name, decl in LOOKALIKE_MAP.items():
        row: Dict[str, Any] = {"kind": decl["kind"], "ages": decl["ages"]}
        if "evidence" in decl:
            ok, problems = _check_evidence(root, decl["evidence"], cache)
            row["evidence"] = {k: list(v) for k, v in decl["evidence"].items()}
            if ok is None:
                row["kind"] = UNMEASURED
                row["reason"] = "; ".join(problems)
            elif not ok:
                row["kind"] = UNMEASURED
                row["reason"] = "объявление разошлось с кодом: " + "; ".join(problems)
        else:
            rel, key = decl["json"]
            n, why = _count_json_key(os.path.join(root, rel), key)
            row["evidence"] = {rel: [key]}
            if n is None:
                row["kind"] = UNMEASURED
                row["reason"] = f"{rel}: {why}"
            elif n == 0:
                row["kind"] = UNMEASURED
                row["reason"] = f"{rel}: ключа {key!r} нет ни разу — объявление не подтверждено"
            else:
                row["declarations"] = n
        assert row["kind"] in AGED_KINDS
        out["windows"][name] = row
    out["tally"] = {k: sum(1 for r in out["windows"].values() if r["kind"] == k)
                    for k in AGED_KINDS}
    return out


# ───────────────────────── ось E: дверь принуждения ──────────────────────────

def measure_enforcement_door(data_dir: str, root: str = REPO_ROOT,
                             now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Ось E: есть ли между решением и исполнением дверь, читающая срок и `now`.

    Три двери спрашиваются: модуль повторной проверки ADR-487 (его слова и его
    зовущие — ввоз ``gate_reader_axis``), поверхность зовущих §27 (точные токены
    срока годности) и окно между событиями (ввоз ADR-487) против срока владельца.
    """
    out: Dict[str, Any] = {"measured": True, "gate_module": _s49.GATE_MODULE}
    gate_path = os.path.join(root, _s49.GATE_MODULE)
    ids, why = _code_identifiers(gate_path)
    if ids is None:
        out["gate_words"] = {"kind": UNMEASURED, "reason": f"модуль гейта не разобран: {why}"}
    else:
        hits = sorted(w for w in EXPIRY_TOKENS if w in ids)
        out["gate_words"] = {"kind": "present" if hits else "absent", "hits": hits}
    readers = _s49.gate_reader_axis(Path(root))
    out["gate_readers"] = {k: readers.get(k) for k in
                           ("measured", "reason", "money_path_callers", "inert_callers")}
    hits_surface, unm = _callers_mention(root, EXPIRY_TOKENS, {}, exact=True)
    if hits_surface is None:
        out["surface_tokens"] = {"kind": UNMEASURED, "reason": "; ".join(unm)}
    else:
        out["surface_tokens"] = {"kind": "present" if hits_surface else "absent",
                                 "hits": hits_surface, "surface": list(CALLER_SURFACE)}
    # Род двери принуждения.
    gw = out["gate_words"]
    gr = out["gate_readers"]
    if gw["kind"] == UNMEASURED or not gr.get("measured"):
        kind = UNMEASURED
        why_k = gw.get("reason") or gr.get("reason")
    elif gw["kind"] == "present" and gr.get("money_path_callers"):
        kind = "gate_reads_ttl_on_path"
        why_k = f"гейт знает {gw['hits']} и его зовут {gr['money_path_callers']}"
    elif not gr.get("money_path_callers"):
        kind = "no_gate_on_path"
        why_k = (f"у модуля повторной проверки нет ни одного зовущего на денежном пути "
                 f"(инертные: {gr.get('inert_callers')}); слов срока годности в его коде "
                 f"{'есть' if gw['kind'] == 'present' else 'нет'}")
    else:
        kind = "gate_without_ttl"
        why_k = "гейт зовётся с пути, но слов срока годности в его коде нет"
    assert kind in ENFORCEMENT_KINDS
    out["door"] = {"kind": kind, "reason": why_k}
    # Окно между событиями против срока владельца — ввоз ADR-487.
    recheck = import_recheck_verdict(data_dir, root, now=now)
    out["recheck"] = recheck
    if recheck.get("measured") and isinstance(recheck.get("window_s_max"), (int, float)):
        w = float(recheck["window_s_max"])
        out["ttl_vs_window"] = {"owner_ttl_s": OWNER_TTL_S, "window_s_max": w,
                                "ttl_over_window": (round(OWNER_TTL_S / w, 1) if w > 0 else None),
                                "reachable_on_paper": w >= OWNER_TTL_S}
    else:
        out["ttl_vs_window"] = {"owner_ttl_s": OWNER_TTL_S, "window_s_max": None,
                                "ttl_over_window": None, "reachable_on_paper": None,
                                "reason": recheck.get("reason")}
    return out


# ───────────────────────── ось F: часы у двери (ввоз §27) ────────────────────

def measure_clock(root: str = REPO_ROOT) -> Dict[str, Any]:
    clock = measure_clock_at_both_events(root)
    clock["fifth_input"] = FIFTH_INPUT
    entry = clock.get("cycle_entry") or {}
    if entry.get("kind") not in (None,):
        assert entry["kind"] in PIN_KINDS
    # «новый расчёт» — какой тип решения §24 это слово? Читатель словаря.
    clock["s24_type_for_stale"] = ("DEFER" if "DEFER" in OWNER_DECISION_TYPES else None)
    return clock


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], answer: Dict[str, Any], column: Dict[str, Any],
              record: Dict[str, Any], lookalikes: Dict[str, Any],
              enforcement: Dict[str, Any], clock: Dict[str, Any]
              ) -> Tuple[List[Dict[str, str]], List[str]]:
    findings: List[Dict[str, str]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is None:
        unmeasured.append("паритет с карточкой: " + str(parity_r["parsed"].get("reason")))
    elif not parity_r["agrees"]:
        findings.append({"severity": "CRITICAL", "code": "owner_text_drifted",
                         "message": "разбор карточки разошёлся с константами: "
                                    + "; ".join(parity_r["mismatches"])})
    elif parity_r.get("order_undercount") is None:
        unmeasured.append("недосчёт заказа G959: НЕ ИЗМЕРЕН")
    elif parity_r["order_undercount"] != 0:
        findings.append({"severity": "INFO", "code": "order_miscounted",
                         "message": f"заказ G959 п. 1 назвал {ORDER_G959_NAMED}, карточка "
                                    f"даёт сдвиг {parity_r['order_undercount']}"})

    # Ось A + B вместе дают род ответа.
    kind_a = UNMEASURED
    if not answer.get("measured"):
        unmeasured.append("ось A (ответ владельца): " + str(answer.get("reason")))
    elif answer.get("record") is None:
        kind_a = answer.get("kind", UNMEASURED)
        if kind_a == "not_answered":
            findings.append({"severity": "WARN", "code": "owner_not_asked_or_not_answered",
                             "message": f"в реестре нет записи для {OWNER_ANSWER_CARD}"})
        else:
            unmeasured.append("ось A: " + str(answer.get("reason")))
    else:
        par = answer.get("parity") or {}
        if not par.get("agrees"):
            findings.append({"severity": "CRITICAL", "code": "owner_answer_drifted",
                             "message": "числа реестра разошлись с константами прибора: "
                                        + "; ".join(par.get("mismatches") or [])})
        if not column.get("measured"):
            unmeasured.append("ось B (колонка владельца): " + str(column.get("reason")))
        else:
            executed = column.get("ttl_dial") is not None
            kind_a = "answered_and_executed" if executed else "answered_not_executed"
            parity_col = column.get("column_matches_answer") or {}
            if executed and parity_col.get("kind") == "differs":
                findings.append({
                    "severity": "CRITICAL", "code": "owner_answer_misexecuted",
                    "message": (f"ручки срока в колонке владельца ({column.get('version')}) "
                                f"есть, но их числа расходятся с ответом {OWNER_ANSWER_ADR} "
                                f"(вариант {OWNER_CHOICE}): {parity_col.get('reason')}")})
            elif executed and parity_col.get("kind") == UNMEASURED:
                unmeasured.append("ось B (паритет чисел колонки с ответом): "
                                  + str(parity_col.get("reason")))
            if not executed:
                age = answer.get("age_days")
                findings.append({
                    "severity": "CRITICAL", "code": "owner_answer_unexecuted",
                    "message": (f"владелец ответил {OWNER_ANSWER_ADR} ({answer.get('answered_at')}, "
                                f"{age if age is not None else 'возраст НЕ ИЗМЕРЕН'} дн. назад, "
                                f"вариант {OWNER_CHOICE}: срок годности решения {OWNER_TTL_S:.0f} с, "
                                f"допуск свежести {OWNER_FRESHNESS_S['paper']:.0f}/"
                                f"{OWNER_FRESHNESS_S['pilot']:.0f} с), а в колонке владельца "
                                f"({column.get('dials_n')} ручек, {column.get('version')}) ручки "
                                f"срока годности НЕТ; карточка ответа в статусе "
                                f"{answer.get('card_status')!r}; адрес исполнения — "
                                f"{EXECUTION_ADDRESS_CARD}")})
    assert kind_a in ANSWER_KINDS

    if column.get("measured"):
        loader = column.get("loader") or {}
        if loader.get("kind") == UNMEASURED:
            unmeasured.append("ось B (читатель колонки): " + str(loader.get("reason")))
        elif loader.get("kind") == "names_dial_only":
            findings.append({
                "severity": "WARN", "code": "column_reader_names_dial_but_never_reads_value",
                "message": (f"читатель колонки (ADR-487 load_owner_tolerance) {loader.get('reason')} "
                            f"— исполнение ответа владельца требует ДВУХ шагов: ручка в "
                            f"колонке И чтение её значения; первый без второго не судит")})

    if not record.get("measured"):
        unmeasured.append("ось C: " + str(record.get("reason")))
    else:
        if record.get("fields") is None:
            unmeasured.append("ось C (запись решения): " + str(record.get("reason")))
        else:
            tally = record.get("roles_tally") or {}
            if record.get("expiry_fields") == []:
                findings.append({
                    "severity": "WARN", "code": "decision_record_has_no_expiry_field",
                    "message": (f"у живой записи решения ({record.get('artifact')}, "
                                f"{record.get('records_n')} записей) поля времени: "
                                f"{record.get('fields')} — роли {tally}; роли «expiry» нет ни у "
                                f"одного; `{OWNER_EXAMPLE_FIELD}` отсутствует; дата в "
                                f"`decision_id` — личность решения, не срок (ADR-968)")})
            for k, r in (record.get("fields") or {}).items():
                if r == UNMEASURED:
                    unmeasured.append(f"ось C: поле {k!r} похоже на время, роль НЕ ОБЪЯВЛЕНА")
        wc = record.get("writer_claim") or {}
        if wc.get("kind") == UNMEASURED:
            unmeasured.append("ось C (писатель): " + "; ".join(wc.get("problems") or []))
        elif wc.get("kind") == "refuted":
            findings.append({"severity": "CRITICAL", "code": "writer_claim_refuted",
                             "message": "претензия о ярлыке писателя опровергнута кодом: "
                                        + "; ".join(wc.get("problems") or [])})
        if record.get("s25_field_28_named"):
            findings.append({
                "severity": "INFO", "code": "owner_named_expiry_twice_s25_and_s28",
                "message": (f"владелец назвал срок годности ДВАЖДЫ — полем №28 §25 «decision "
                            f"expiry» и разделом §28; §25 делегировал поле "
                            f"{(record.get('s25_delegated') or {}).get('section')} с вердиктом: "
                            f"{(record.get('s25_delegated') or {}).get('verdict')}")})
        row22 = record.get("s22_row") or {}
        if row22.get("outcome") == UNMEASURED:
            unmeasured.append("ось C (ввоз §22): " + str(row22.get("detail")))

    if not lookalikes.get("measured"):
        unmeasured.append("ось D: " + str(lookalikes.get("reason")))
    else:
        for name, row in lookalikes["windows"].items():
            if row["kind"] == UNMEASURED:
                unmeasured.append(f"ось D «{name}»: {row.get('reason')}")
        tally = lookalikes.get("tally") or {}
        measured_n = sum(v for k, v in tally.items() if k != UNMEASURED)
        if measured_n and tally.get("decision", 0) == 0:
            findings.append({
                "severity": "INFO", "code": "every_ttl_in_tree_ages_something_else",
                "message": (f"окон годности в дереве проверено {measured_n}: {tally} — ни одно "
                            f"не состаривает РЕШЕНИЕ; взять любое из них за TTL решения "
                            f"значило бы ответить на другой вопрос (отказ ADR-487)")})

    if not enforcement.get("measured"):
        unmeasured.append("ось E: " + str(enforcement.get("reason")))
    else:
        door = enforcement.get("door") or {}
        if door.get("kind") == UNMEASURED:
            unmeasured.append("ось E (дверь): " + str(door.get("reason")))
        elif door.get("kind") in ("no_gate_on_path", "gate_without_ttl"):
            findings.append({
                "severity": "WARN", "code": "no_enforcement_door_for_expiry",
                "message": (f"«нельзя выполнять без нового расчёта» некому исполнить: "
                            f"{door.get('reason')}; точных токенов срока годности на "
                            f"поверхности зовущих "
                            f"{(enforcement.get('surface_tokens') or {}).get('kind')}")})
        st = enforcement.get("surface_tokens") or {}
        if st.get("kind") == UNMEASURED:
            unmeasured.append("ось E (поверхность): " + str(st.get("reason")))
        tv = enforcement.get("ttl_vs_window") or {}
        if tv.get("reachable_on_paper") is None:
            unmeasured.append("ось E (срок против окна): " + str(tv.get("reason")))
        elif tv.get("reachable_on_paper") is False:
            findings.append({
                "severity": "INFO", "code": "owner_ttl_unreachable_on_paper",
                "message": (f"срок владельца {tv['owner_ttl_s']:.0f} с против окна между "
                            f"решением и бумажным исполнением ≤ {tv['window_s_max']} с "
                            f"(×{tv['ttl_over_window']}): на бумаге TTL не истекает ПО "
                            f"ПОСТРОЕНИЮ — оба события пишет один процесс; число владельца "
                            f"начнёт что-то решать вместе с реальным исполнением (инв. #6)")})

    if not clock.get("measured"):
        unmeasured.append("ось F: " + str(clock.get("reason")))
    else:
        subj = clock.get("subjects") or {}
        if isinstance(subj, dict) and subj.get("kind") == UNMEASURED:
            unmeasured.append("ось F (субъекты ADR-969): " + str(subj.get("reason")))
        else:
            ambient = sorted(s for s, k in subj.items() if k == "unpinnable_ambient")
            entry = clock.get("cycle_entry") or {}
            if entry.get("kind") == UNMEASURED:
                unmeasured.append("ось F (вход цикла): " + str(entry.get("reason")))
            elif ambient:
                findings.append({
                    "severity": "WARN", "code": "expiry_needs_now_and_it_is_not_an_input",
                    "message": (f"«истёк ли TTL» = f(valid_until, now): первого операнда "
                                f"нет у записи (ось C), второго нет входом у субъектов "
                                f"{', '.join(ambient)} (ADR-969); у входа цикла момент "
                                f"{'ЕСТЬ (' + ', '.join(entry.get('params') or []) + ')' if entry.get('kind') == 'pinnable_named' else 'НЕТ'}; "
                                f"слово §24 для просроченного решения — "
                                f"{clock.get('s24_type_for_stale') or 'в словаре нет'}")})
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None, params: Any = None) -> Dict[str, Any]:
    """Полный замер §28. Только ЧИТАЕТ; ``applied=False``.

    ``params`` — колонка владельца как ВХОД (умолчание — живая `TriggerParams`):
    сцена «ответ не исполнен» после ADR-972 на живой колонке недостижима, а
    находка обязана оставаться достижимой для контроля в обе стороны.
    """
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    answer = import_owner_answer(root, now=stamped)
    column = measure_owner_column(params)
    record = measure_record_time_fields(data_dir, root)
    lookalikes = measure_lookalikes(root)
    enforcement = measure_enforcement_door(data_dir, root, now=now)
    clock = measure_clock(root)

    findings, unmeasured = _findings(parity_r, answer, column, record, lookalikes,
                                     enforcement, clock)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "decision_expiry_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §28 ТЗ «Portfolio CIO» (Decision expiry). "
                     "TriggerParams, политику, гейт, прибор ADR-487 и живой трек НЕ "
                     "трогает; карточку владельцу не заводит — вопрос отвечен 27.10"),
        "overall": overall,
        "counts": counts,
        "declared": {"requirement": _REQUIREMENT_LINE, "example": OWNER_EXAMPLE_FIELD,
                     "condition": _CONDITION_LINE, "consequence": _CONSEQUENCE_LINE,
                     "order_g959_named": dict(ORDER_G959_NAMED),
                     "owner_choice": OWNER_CHOICE, "owner_ttl_s": OWNER_TTL_S,
                     "owner_freshness_s": dict(OWNER_FRESHNESS_S),
                     "answer_kinds": list(ANSWER_KINDS),
                     "loader_kinds": list(LOADER_KINDS),
                     "time_field_roles": list(TIME_FIELD_ROLES),
                     "aged_kinds": list(AGED_KINDS),
                     "enforcement_kinds": list(ENFORCEMENT_KINDS)},
        "parity": parity_r,
        "axis_a_owner_answer": answer,
        "axis_b_owner_column": column,
        "axis_c_record_time_fields": record,
        "axis_d_lookalikes": lookalikes,
        "axis_e_enforcement": enforcement,
        "axis_f_clock": clock,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path): перестановка у §26 оставляла прибор без
        # артефакта (#1088, M13).
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§28 ТЗ «Portfolio CIO» (Decision expiry): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (требование 1, пример "
              f"`{OWNER_EXAMPLE_FIELD}`, следствие 1; заказ G959 назвал "
              f"{ORDER_G959_NAMED}, сдвиг {p.get('order_undercount')})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    a = doc["axis_a_owner_answer"]
    if a.get("measured") and a.get("record"):
        print(f"   [ось A] ответ владельца {a['adr']}: вариант {a['record'].get('choice')} — "
              f"«{a['record'].get('label')}» · карточка {a.get('card_status')} · "
              f"{a.get('age_days')} дн. · паритет чисел = {(a.get('parity') or {}).get('agrees')}")
    else:
        print(f"   [ось A] {a.get('kind') or UNMEASURED}: {a.get('reason')}")
    b = doc["axis_b_owner_column"]
    if b.get("measured"):
        print(f"   [ось B] колонка {b.get('version')}/{b.get('mode')}: ручек {b.get('dials_n')}, "
              f"ручка срока = {b.get('ttl_dial')} · читатель: {(b.get('loader') or {}).get('kind')}")
    else:
        print(f"   [ось B] НЕ ИЗМЕРЕНО: {b.get('reason')}")
    r = doc["axis_c_record_time_fields"]
    if r.get("fields") is not None:
        print(f"   [ось C] поля времени записи: {r['fields']} · expiry = {r.get('expiry_fields')} "
              f"· §22: {(r.get('s22_row') or {}).get('outcome')}")
    else:
        print(f"   [ось C] {r.get('reason')}")
    d = doc["axis_d_lookalikes"]
    if d.get("measured"):
        print(f"   [ось D] окна годности: {d.get('tally')}")
    e = doc["axis_e_enforcement"]
    if e.get("measured"):
        print(f"   [ось E] дверь: {(e.get('door') or {}).get('kind')} · срок/окно: "
              f"{(e.get('ttl_vs_window') or {}).get('ttl_over_window')} · достижим на бумаге = "
              f"{(e.get('ttl_vs_window') or {}).get('reachable_on_paper')}")
    f = doc["axis_f_clock"]
    print(f"   [ось F] субъекты: {f.get('subjects')} · вход цикла: "
          f"{(f.get('cycle_entry') or {}).get('kind')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    """``--now`` — вход, не окружение. Пустое/неразбираемое — ОТКАЗ, не часы."""
    if raw is None:
        return None, None
    ts = _parse_ts(raw.strip()) if raw.strip() else None
    if ts is None:
        return None, f"--now {raw!r} не разбирается как ISO-8601 — отказ, а не стенные часы"
    return ts, None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§28 ТЗ «Portfolio CIO»: Decision expiry — исполнен ли ответ "
                    "владельца о сроке годности решения")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по "
                         "построению — передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(argv)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
