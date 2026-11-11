"""release_stage_census.py — §40 ТЗ «Portfolio CIO»: «Release stages».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §40::

    Release stages
    Использовать поэтапный запуск.
    Stage 0  Diagnosis only                          Никаких изменений allocation.
    Stage 1  Shadow CIO                              Recommendations only.
    Stage 2  Owner-approved execution                CIO предлагает. Owner подтверждает.
    Stage 3  Limited auto-execution                  Только внутри заранее утвержденных bands.
    Stage 4  Policy-bounded autonomous rebalancing   Только после доказательства безопасности
                                                     предыдущих стадий.

Стадий **ПЯТЬ**, у каждой — имя и одна-две строки смысла. Прибор сверяет перечень, имена,
строки и обе границы раздела с карточкой (`parity`).

Что УЖЕ есть и что измеряется
=============================
Лестница у системы ЕСТЬ — но не как поле, а как ПОВЕДЕНИЕ, разложенное по модулям:
журнал тени ADR-060 (с 06.08 — «recommendations only»), взвод CIO
`spa_core.paper_trading.cio_arming.ARMED_BOOKS` (решение владельца 11.09, ADR-324/328:
вердикт CIO решает перекладку во ВСЕХ трёх бумажных книгах), разовое разрешение
`cio_trial.TRIAL_GRANT` (ADR-334/336 — единственная дверь вида «владелец подтверждает
ход»), пределы §41 `cio_auto_execution_limits.json` (ADR-250 — «bands»), критерий взвода
ADR-067 `shadow_trigger_evaluation.json` («доказательство безопасности»), и дверь реальных
денег `execution_readiness.json` (SPA_EXECUTION_MODE · custody). Прибор НЕ назначает стадию
и НЕ строит вторую лестницу: он спрашивает, на какой ступени система стои́т ПО ПОВЕДЕНИЮ,
объявляет ли хоть один производитель эту ступень ПОЛЕМ, и согласен ли ярлык записи с тем,
что запись делает.

Два РЕФЕРЕНТА у лестницы, и это существенно: «capital execution» у владельца — про РЕАЛЬНЫЕ
деньги, но бумажные книги проходят ту же лестницу своим капиталом ($100k × 3). Прибор
печатает обе: бумажные книги (три) и реальный капитал (один референт).

Пять осей замера
================
* **A — паритет.** Пять стадий, имена, строки смысла и обе границы — с карточки.
* **B — поведение → ступень.** У КАЖДОЙ книги: взведена ли (`cio_arming.is_armed`),
  с какого дня и каким решением; есть ли записи тени (журнал ADR-060). Род поведения:
  `auto_within_bands` (взведена: вердикт CIO решает ход внутри RiskPolicy и пределов §41 —
  форма стадий 3/4; что из них — лестница различает ТОЛЬКО доказательством, см. E) ·
  `recommendations_only` (не взведена, записи есть — стадия 1) · `no_records` (стадия 0) ·
  `unmeasured`. Реальный капитал: `not_entered` (исполнения нет, custody нет,
  `ready_for_live=False`) · `entered` · `unmeasured`.
* **C — объявление.** Сканируются ВСЕ `data/*.json`: несёт ли хоть один производитель
  поле, отвечающее «какая стадия», СЛОВАРЁМ ВЛАДЕЛЬЦА (номер 0…4 либо имя стадии).
  Попутно печатаются ВСЕ словари, которыми артефакты отвечают на вопрос «в каком мы
  режиме» (`SHADOW` · `ADVISORY` · `paper` · `read_only_simulation` · `PAPER_SAFE` …):
  столько словарей — столько мест, где стадию можно прочитать по-разному.
* **D — ярлык против поведения.** У взведённой книги живая запись
  (`allocation_rationale[_<book>].json`) читается на `mode` и `note`: запись, чей вердикт
  РЕШАЕТ ход (ADR-324), подписанная `SHADOW` / «ADVISORY: no position was changed by it», —
  противоречие. И строки журнала: несёт ли хоть одна поле стадии/взвода — иначе решающий
  вердикт в журнале неотличим от советующего.
* **E — двери стадий 2 · 3 · 4.** Стадия 2 («владелец подтверждает»): разовое разрешение в
  коде (`TRIAL_GRANT`: книга, ходов, расход по журналу сделок) и семейства глаголов
  `act:` у бота (статический скан `spa_core/telegram`) — есть ли ОБЩИЙ канал. Стадия 3
  («bands»): перепись §41 (BINDING / LITERAL / ABSENT из 12) и пределы хода в записи
  (`admissible_trim.caps`, ADR-850). Стадия 4 («после доказательства»): критерий взвода
  ADR-067 — `ready_to_arm`, статусы критериев, вердикт блокады ADR-228. Взвод 11.09 при
  `ready_to_arm=False` — РЕШЕНИЕ ВЛАДЕЛЬЦА (ADR-324/328), переносится INFO, не судится.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): карточку, журнал, живые записи, артефакты §41/ADR-067/
готовности и реестры взвода — как есть; ни одно число не считается заново. Стадию НЕ
назначает и «пора ли на следующую» НЕ говорит — это решение владельца по предмету №1.
`spa_core/execution/` не импортирует (инв. #6): дверь реальных денег читается по её
АРТЕФАКТУ. Карточку владельцу не заводит. Пределы §41 (следующий раздел ТЗ) здесь не
перемеряются — читается готовый артефакт ADR-250.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.paper_trading import cio_arming
from spa_core.paper_trading import cio_trial
from spa_core.paper_trading import shadow_trigger_eval as ste
# `_rationale_filename` приватна у писателя намеренно (нет межмодульного читателя); вторая копия правила
# суффикса здесь была бы дрейфующей — поэтому берётся ТА ЖЕ функция, что у писателя.
from spa_core.paper_trading.allocation_rationale import (  # noqa: PLC2701
    RATIONALE_FILENAME, _rationale_filename as rationale_filename, history_filename)
from spa_core.utils.observation import observed as observed_field

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/release_stage_census.json"
CARD_REL = smc.CARD_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "40. Release stages"
NEXT_SECTION_HEAD = "41. Auto-execution limits"
OWNER_LEAD = "Использовать поэтапный запуск."
OWNER_STAGES: Tuple[Dict[str, Any], ...] = (
    {"n": 0, "name": "Diagnosis only", "lines": ("Никаких изменений allocation.",)},
    {"n": 1, "name": "Shadow CIO", "lines": ("Recommendations only.",)},
    {"n": 2, "name": "Owner-approved execution", "lines": ("CIO предлагает.", "Owner подтверждает.")},
    {"n": 3, "name": "Limited auto-execution", "lines": ("Только внутри заранее утвержденных bands.",)},
    {"n": 4, "name": "Policy-bounded autonomous rebalancing",
     "lines": ("Только после доказательства безопасности предыдущих стадий.",)},
)
OWNER_STAGES_DECLARED = 5

#: Заказ G973 п. 1 назвал стадий ПЯТЬ и процитировал имена четырёх («… 3 Limited
#: auto-execution · 4») — имя Stage 4 обрезано. Сдвиг по именам = 1 и печатается
#: отдельно от «назвал верно».
ORDER_G973_NAMED: Dict[str, Any] = {"stages": 5, "names_cited": 4, "tail_read": True}

BEHAVIOUR_KINDS: Tuple[str, ...] = ("auto_within_bands", "recommendations_only", "no_records", UNMEASURED)
REAL_KINDS: Tuple[str, ...] = ("not_entered", "entered", UNMEASURED)
DECLARATION_KINDS: Tuple[str, ...] = ("declared", "not_declared", UNMEASURED)
LABEL_KINDS: Tuple[str, ...] = ("agrees", "contradicts", UNMEASURED)
STAGE2_DOOR_KINDS: Tuple[str, ...] = ("general_channel", "one_off_grant_only", "absent", UNMEASURED)
PROOF_KINDS: Tuple[str, ...] = ("given", "not_given", UNMEASURED)

#: Форма стадии, которую несёт поведение (B): ступень лестницы владельца, а не вердикт.
BEHAVIOUR_STAGE: Dict[str, Optional[str]] = {
    "auto_within_bands": "3/4", "recommendations_only": "1", "no_records": "0", UNMEASURED: None,
}

#: Книги, по которым спрашивается поведение: ключи те же, что у `cio_arming.ARMED_BOOKS`
#: и у `allocation_rationale.rationale_filename`.
BOOKS: Tuple[str, ...] = ("conservative", "balanced", "aggressive")

HISTORY_FILE = ste.HISTORY_FILENAME
EVAL_FILE = ste.EVAL_FILENAME
LIMITS_FILE = "cio_auto_execution_limits.json"
READINESS_FILE = "execution_readiness.json"
INPUT_FILES: Tuple[str, ...] = (HISTORY_FILE, RATIONALE_FILENAME, EVAL_FILE, LIMITS_FILE, READINESS_FILE)

#: Ось D — поля записи, которые читались бы как «стадия / взвод». Ни одного нет — это и
#: есть замер; появится — род станет иным.
STAGE_RECORD_FIELDS: Tuple[str, ...] = ("stage", "release_stage", "cio_stage", "armed", "cio_armed")
#: Подпись тени, с которой запись, решающая ход, спорит сама с собой.
SHADOW_LABELS: Tuple[str, ...] = ("SHADOW",)
ADVISORY_NOTE_MARK = "no position was changed by it"

#: Ось C — ключи артефактов, которые читаются как ответ на «какая стадия / какой режим».
DECLARATION_KEY_RE = re.compile(r"(^|_)(stage|release_stage|cio_stage|posture|execution_mode|mode)$")
#: Словарь владельца: номер ступени либо имя стадии.
OWNER_STAGE_VALUE_RE = re.compile(r"^stage[ _-]?[0-4]$", re.IGNORECASE)
OWNER_STAGE_NAMES_LOWER: Tuple[str, ...] = tuple(s["name"].lower() for s in OWNER_STAGES)
SCAN_MAX_BYTES = 8 * 1024 * 1024
SCAN_DEPTH = 2

#: Ось E, стадия 2 — семейства глаголов бота, которые читались бы как «подтвердить ход».
REBALANCE_VERB_MARKERS: Tuple[str, ...] = ("rebal", "cio", "alloc", "move", "trade", "approve")
TELEGRAM_REL = "spa_core/telegram"
ACT_VERB_RE = re.compile(r"act:([a-z_]+):")

#: Ось E, стадия 3 — перепись §41: сколько пределов из объявленных связывают.
LIMITS_BINDING = "BINDING"
LIMITS_ABSENT = "ABSENT"

#: Файлы `data/`, в имени которых слово «release» значит РЕЛИЗ КОДА (ADR-909), не стадию CIO.
RELEASE_WORD_RE = re.compile(r"release", re.IGNORECASE)


# ───────────────────────────── чтение карточки / паритет ──────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница {NEXT_SECTION_HEAD!r} — "
                      f"перечень не ограничен, и счёт по нему был бы счётом неизвестно чего")
    return lines[start + 1:end], None


_STAGE_HEAD_RE = re.compile(r"^Stage (\d)$")


def _stages_from_body(body: List[str]) -> List[Dict[str, Any]]:
    """`Stage N` → следующая непустая строка — имя, далее строки смысла до `⸻`."""
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for ln in body:
        s = ln.strip()
        m = _STAGE_HEAD_RE.match(s)
        if m:
            cur = {"n": int(m.group(1)), "name": None, "lines": []}
            out.append(cur)
            continue
        if cur is None or not s:
            continue
        if s == "⸻":
            cur = None
            continue
        if cur["name"] is None:
            cur["name"] = s
        else:
            cur["lines"].append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = smc._read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {"measured": True, "lead_present": OWNER_LEAD in stripped, "stages": _stages_from_body(body)}


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    if not parsed.get("measured"):
        return {"agrees": None, "parsed": parsed, "mismatches": []}
    mism: List[str] = []
    if not parsed["lead_present"]:
        mism.append(f"в разделе нет строки {OWNER_LEAD!r}")
    got = parsed["stages"]
    if [s["n"] for s in got] != [s["n"] for s in OWNER_STAGES]:
        mism.append(f"номера стадий в карточке {[s['n'] for s in got]} ≠ объявленным "
                    f"{[s['n'] for s in OWNER_STAGES]}")
    else:
        for g, d in zip(got, OWNER_STAGES):
            if g["name"] != d["name"]:
                mism.append(f"Stage {d['n']}: имя в карточке {g['name']!r} ≠ объявленному {d['name']!r}")
            if tuple(g["lines"]) != tuple(d["lines"]):
                mism.append(f"Stage {d['n']}: строки смысла {g['lines']} ≠ объявленным {list(d['lines'])}")
    return {"agrees": not mism, "parsed": parsed, "mismatches": mism}


# ───────────────────────────── входы ──────────────────────────────────────────

def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path.name} нет"
    except (OSError, ValueError) as exc:
        return None, f"{path.name} не прочитан: {type(exc).__name__}"


def load_journal(data_dir: str, book: str = "conservative") -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]:
    """Строки журнала ADR-060 КНИГИ как есть (все прогоны, не по дням). ``(строки, причина, битых)``.

    Имя файла — у писателя (`history_filename`): консервативная книга пишет в
    ``allocation_rationale_history.jsonl``, остальные — в ``…_history_<book>.jsonl``.
    """
    fname = history_filename(book)
    path = Path(data_dir) / fname
    if not path.exists():
        return None, f"журнала {fname} нет — ступень книги {book!r} по записям не измерить", 0
    rows: List[Dict[str, Any]] = []
    corrupt = 0
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                doc = json.loads(ln)
            except ValueError:
                corrupt += 1
                continue
            if isinstance(doc, dict):
                rows.append(doc)
            else:
                corrupt += 1
    if not rows:
        return None, f"журнал {fname} пуст (битых строк {corrupt})", corrupt
    return rows, None, corrupt


def load_journals(data_dir: str) -> Dict[str, Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]]:
    return {book: load_journal(data_dir, book) for book in BOOKS}


def _dates(rows: List[Dict[str, Any]]) -> List[str]:
    return sorted({str(r["cycle_date"]) for r in rows if isinstance(r.get("cycle_date"), str)})


# ───────────────────────────── ось B — поведение → ступень ────────────────────

def measure_books(journals: Dict[str, Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]],
                  armed_books: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Dict[str, Any]]:
    """Реестр взвода читается в момент вызова (живой `cio_arming.ARMED_BOOKS`), не при импорте."""
    if armed_books is None:
        armed_books = cio_arming.ARMED_BOOKS
    out: Dict[str, Dict[str, Any]] = {}
    for book in BOOKS:
        rows, rows_why, _ = journals.get(book, (None, f"журнал книги {book!r} не читался", 0))
        armed = armed_books.get(book)
        armed_rec: Dict[str, str] = armed if isinstance(armed, dict) else {}
        row: Dict[str, Any] = {
            "book": book, "armed": armed is not None,
            "armed_at": armed_rec.get("armed_at"), "armed_by": armed_rec.get("armed_by"),
            "armed_adr": armed_rec.get("adr"),
            "door": "spa_core.paper_trading.cio_arming.ARMED_BOOKS · trade_allowed / gate_sleeve_book",
            "journal": history_filename(book),
        }
        if rows is None:
            row.update({"records": None, "first_record": None, "last_record": None,
                        "behaviour": UNMEASURED, "reason": rows_why, "stage_shape": None})
            out[book] = row
            continue
        # Журнал книги уже книжный (маршрут писателя); `book_id` у строк до ADR-309 отсутствует,
        # и такие строки принадлежат той книге, в чей файл записаны (ADR-309).
        mine = [r for r in rows if (r.get("book_id") or book) == book]
        ds = _dates(mine)
        row.update({"records": len(mine), "first_record": ds[0] if ds else None,
                    "last_record": ds[-1] if ds else None})
        if armed is not None:
            kind = "auto_within_bands"
        elif mine:
            kind = "recommendations_only"
        else:
            kind = "no_records"
        row["behaviour"] = kind
        row["stage_shape"] = BEHAVIOUR_STAGE[kind]
        if armed is not None and ds:
            try:
                d0 = dt.date.fromisoformat(ds[0])
                da = dt.date.fromisoformat(str(armed.get("armed_at")))
                row["shadow_days_before_arming"] = (da - d0).days
            except ValueError:
                row["shadow_days_before_arming"] = None
        out[book] = row
    return out


def measure_real_capital(data_dir: str) -> Dict[str, Any]:
    """Референт «реальные деньги» — по артефакту готовности (инв. #6: execution/ не импортируется)."""
    doc, why = _read_json(Path(data_dir) / READINESS_FILE)
    base = {"door": f"{READINESS_FILE} (posture · ready_for_live · checks.execution_mode_not_live.live_mode · "
                    "checks.custody_connected.custody_connected); SPA_EXECUTION_MODE=live ∧ custody — "
                    "spa_core/execution/engine_bridge (не импортируется)"}
    if doc is None:
        return {**base, "kind": UNMEASURED, "reason": why}
    # отсутствие раздела — отсутствие наблюдения (None уходит в ответ), не пустой раздел
    checks = observed_field(doc, "checks", kind=dict)
    mode = observed_field(checks, "execution_mode_not_live", kind=dict)
    cust = observed_field(checks, "custody_connected", kind=dict)
    live_mode = observed_field(mode, "live_mode", kind=bool)
    custody = observed_field(cust, "custody_connected", kind=bool)
    ready = observed_field(doc, "ready_for_live", kind=bool)
    posture = observed_field(doc, "posture", kind=str)
    if live_mode is None and custody is None and ready is None:
        return {**base, "kind": UNMEASURED, "reason": f"{READINESS_FILE} не несёт ни live_mode, ни custody, "
                                                       f"ни ready_for_live", "posture": posture}
    entered = bool(live_mode) and bool(custody)
    return {**base, "kind": "entered" if entered else "not_entered", "live_mode": live_mode,
            "custody_connected": custody, "ready_for_live": ready, "posture": posture,
            "audited_at": observed_field(doc, "audited_at", kind=str)}


# ───────────────────────────── ось C — объявление ─────────────────────────────

def _walk(node: Any, prefix: str, depth: int, out: List[Tuple[str, Any]]) -> None:
    if depth > SCAN_DEPTH or not isinstance(node, dict):
        return
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and DECLARATION_KEY_RE.search(str(k)):
            out.append((key, v))
        elif isinstance(v, dict):
            _walk(v, key, depth + 1, out)


def _is_owner_vocabulary(value: Any) -> bool:
    s = str(value).strip()
    return bool(OWNER_STAGE_VALUE_RE.match(s)) or s.lower() in OWNER_STAGE_NAMES_LOWER


def measure_declaration(data_dir: str, skip: Tuple[str, ...] = (os.path.basename(REPORT_REL),)) -> Dict[str, Any]:
    """Несёт ли хоть один артефакт `data/*.json` стадию словарём владельца."""
    d = Path(data_dir)
    if not d.is_dir():
        return {"kind": UNMEASURED, "reason": f"каталога {data_dir} нет", "files": None}
    files = sorted(p for p in d.glob("*.json") if p.name not in skip)
    fields: List[Dict[str, Any]] = []
    unread: List[str] = []
    too_big: List[str] = []
    release_named: List[str] = []
    for p in files:
        if RELEASE_WORD_RE.search(p.name):
            release_named.append(p.name)
        try:
            if p.stat().st_size > SCAN_MAX_BYTES:
                too_big.append(p.name)
                continue
        except OSError:
            unread.append(p.name)
            continue
        doc, why = _read_json(p)
        if doc is None:
            unread.append(p.name)
            continue
        found: List[Tuple[str, Any]] = []
        _walk(doc, "", 0, found)
        for key, val in found:
            fields.append({"file": p.name, "key": key, "value": val, "owner_vocabulary": _is_owner_vocabulary(val)})
    if not files:
        return {"kind": UNMEASURED, "reason": f"в {data_dir} нет ни одного *.json", "files": 0}
    declaring = [f for f in fields if f["owner_vocabulary"]]
    vocab = sorted({str(f["value"]) for f in fields}, key=str.lower)
    return {
        "kind": "declared" if declaring else "not_declared",
        "files": len(files), "files_unread": unread, "files_too_big": too_big,
        "fields": len(fields), "fields_by_vocabulary": {v: sum(1 for f in fields if str(f["value"]) == v) for v in vocab},
        "vocabularies": vocab, "declaring": declaring,
        "release_named_files": release_named,
        "owner_vocabulary": {"numbers": "Stage 0…4", "names": list(OWNER_STAGE_NAMES_LOWER)},
    }


# ───────────────────────────── ось D — ярлык против поведения ─────────────────

def measure_labels(data_dir: str, books: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for book, b in books.items():
        fname = rationale_filename(book)
        doc, why = _read_json(Path(data_dir) / fname)
        row: Dict[str, Any] = {"book": book, "file": fname, "armed": b["armed"]}
        if doc is None:
            row.update({"kind": UNMEASURED, "reason": why, "mode": None, "note_advisory": None})
            out[book] = row
            continue
        mode = observed_field(doc, "mode", kind=str)
        note = observed_field(doc, "note", kind=str)
        advisory = None if note is None else (ADVISORY_NOTE_MARK in note)
        row.update({"mode": mode, "note_advisory": advisory, "generated_at": observed_field(doc, "generated_at", kind=str)})
        if mode is None and note is None:
            row.update({"kind": UNMEASURED, "reason": f"{fname} не несёт ни mode, ни note"})
        elif b["armed"] and (mode in SHADOW_LABELS or advisory is True):
            row["kind"] = "contradicts"
            row["detail"] = (f"книга взведена ({b['armed_adr']}, {b['armed_at']}): её вердикт РЕШАЕТ перекладку, "
                             f"а запись подписана mode={mode!r}" + (" и «ADVISORY: no position was changed by it»" if advisory else ""))
        else:
            row["kind"] = "agrees"
        out[book] = row
    return out


def measure_record_fields(journals: Dict[str, Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]]) -> Dict[str, Any]:
    """Несёт ли хоть одна строка хоть одного журнала поле стадии/взвода."""
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    for book, (r, why, _) in journals.items():
        if r is None:
            missing.append(f"{book}: {why}")
        else:
            rows.extend(r)
    if not rows:
        return {"kind": UNMEASURED, "reason": "; ".join(missing) or "журналов нет", "records": None}
    carrying = {f: sum(1 for r in rows if f in r) for f in STAGE_RECORD_FIELDS}
    total = sum(carrying.values())
    return {"kind": "carried" if total else "absent", "records": len(rows), "journals_missing": missing,
            "by_field": carrying, "fields_declared": list(STAGE_RECORD_FIELDS),
            "detail": (None if total else f"ни одна из {len(rows)} строк ({len(journals) - len(missing)} журнал(ов)) не "
                                            f"несёт ни одного из полей {list(STAGE_RECORD_FIELDS)} — решающий вердикт "
                                            f"(после взвода) в журнале неотличим от советующего (до взвода)")}


# ───────────────────────────── ось E — двери стадий 2 · 3 · 4 ─────────────────

def act_verb_families(root: str) -> Tuple[Optional[List[str]], Optional[str]]:
    base = Path(root) / TELEGRAM_REL
    if not base.is_dir():
        return None, f"каталога {TELEGRAM_REL} нет в {root}"
    found: set = set()
    files = [p for p in base.rglob("*.py") if "tests" not in p.parts]
    if not files:
        return None, f"в {TELEGRAM_REL} нет ни одного *.py вне tests"
    for p in files:
        text, why = smc._read_text(str(p))
        if text is None:
            continue
        found.update(ACT_VERB_RE.findall(text))
    return sorted(found), None


def measure_stage2_door(root: str, data_dir: str) -> Dict[str, Any]:
    verbs, why = act_verb_families(root)
    grant = dict(cio_trial.TRIAL_GRANT)
    spent, spent_why = cio_trial.trial_moves_spent(data_dir)
    row: Dict[str, Any] = {
        "door": "spa_core.paper_trading.cio_trial.TRIAL_GRANT (разовое разрешение владельца, ADR-334/336) · "
                "семейства глаголов act:<verb>: бота (spa_core/telegram, статический скан)",
        "one_off_grant": {"adr": grant.get("adr"), "book": grant.get("book"), "moves": grant.get("moves"),
                          "granted_at": grant.get("granted_at"), "spent": spent, "spent_note": spent_why or None},
        "act_verb_families": verbs, "act_scan_reason": why,
    }
    if verbs is None:
        row.update({"kind": UNMEASURED, "reason": why})
        return row
    rebal = [v for v in verbs if any(m in v for m in REBALANCE_VERB_MARKERS)]
    row["rebalance_verbs"] = rebal
    if rebal:
        row["kind"] = "general_channel"
    elif grant.get("moves"):
        row["kind"] = "one_off_grant_only"
    else:
        row["kind"] = "absent"
    return row


def measure_stage3_bands(data_dir: str, rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    doc, why = _read_json(Path(data_dir) / LIMITS_FILE)
    row: Dict[str, Any] = {"door": f"{LIMITS_FILE} (§41, ADR-250: tally BINDING/LITERAL/DECLARED_INERT/ABSENT) · "
                                   "admissible_trim.caps записи (ADR-850)"}
    if doc is None:
        row.update({"kind": UNMEASURED, "reason": why})
    else:
        tally = observed_field(doc, "tally", kind=dict)
        total = observed_field(doc, "limits_total", kind=int)
        if tally is None or total is None:
            row.update({"kind": UNMEASURED, "reason": f"{LIMITS_FILE} не несёт tally/limits_total"})
        else:
            binding = observed_field(tally, LIMITS_BINDING, kind=int)
            absent = observed_field(tally, LIMITS_ABSENT, kind=int)
            if binding is None:
                row.update({"kind": UNMEASURED, "reason": f"{LIMITS_FILE}: tally без {LIMITS_BINDING}"})
                binding = absent = None
            if binding is not None:
                row.update({"kind": "all_binding" if binding == total else "partly_binding" if binding else "none_binding",
                            "binding": binding, "absent": absent, "total": total, "tally": dict(tally),
                            "generated_at": observed_field(doc, "generated_at", kind=str)})
    caps = None
    caps_adr = None
    if rows:
        last = rows[-1]
        trim = observed_field(last, "admissible_trim", kind=dict)
        caps = observed_field(trim, "caps", kind=dict)
        caps_adr = observed_field(trim, "adr", kind=str)
    row["record_caps"] = caps
    row["record_caps_adr"] = caps_adr
    return row


def measure_stage4_proof(data_dir: str) -> Dict[str, Any]:
    doc, why = _read_json(Path(data_dir) / EVAL_FILE)
    row: Dict[str, Any] = {"door": f"{EVAL_FILE} (критерий взвода ADR-067: ready_to_arm · criteria · "
                                   "arming_blockade ADR-228)"}
    if doc is None:
        row.update({"kind": UNMEASURED, "reason": why})
        return row
    ready = observed_field(doc, "ready_to_arm", kind=bool)
    crit = observed_field(doc, "criteria", kind=list)
    if ready is None:
        row.update({"kind": UNMEASURED, "reason": f"{EVAL_FILE} не несёт ready_to_arm"})
        return row
    row.update({"kind": "given" if ready else "not_given", "ready_to_arm": ready,
                "criteria": (None if crit is None else [{"criterion": c.get("criterion"), "status": c.get("status")}
                                                        for c in crit if isinstance(c, dict)]),
                "observation_days": observed_field(doc, "observation_days", kind=int),
                "status": observed_field(doc, "status", kind=str),
                "generated_at": observed_field(doc, "generated_at", kind=str)})
    blockade = observed_field(doc, "arming_blockade", kind=dict)
    row["blockade_verdict"] = observed_field(blockade, "verdict", kind=str)
    return row


# ───────────────────────────── находки и сборка ───────────────────────────────

def _findings(parity_r: Dict[str, Any], books: Dict[str, Dict[str, Any]], real: Dict[str, Any],
              declaration: Dict[str, Any], labels: Dict[str, Dict[str, Any]], record_fields: Dict[str, Any],
              stage2: Dict[str, Any], stage3: Dict[str, Any], proof: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is False:
        findings.append({"severity": "CRITICAL", "code": "owner_section_drifted",
                         "detail": "; ".join(parity_r["mismatches"])})
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    for book, b in books.items():
        if b["behaviour"] == UNMEASURED:
            unmeasured.append(f"поведение книги {book!r}: {b.get('reason')}")
    if real["kind"] == UNMEASURED:
        unmeasured.append(f"реальный капитал: {real.get('reason')}")

    if declaration["kind"] == "not_declared":
        findings.append({"severity": "CRITICAL", "code": "release_stage_not_declared",
                         "detail": (f"из {declaration['files']} артефактов data/*.json ни один не несёт стадию словарём "
                                    f"владельца (Stage 0…4 / имена); на вопрос «в каком мы режиме» отвечают "
                                    f"{len(declaration['vocabularies'])} разных словарей: {declaration['vocabularies']}")})
    elif declaration["kind"] == UNMEASURED:
        unmeasured.append(f"объявление стадии: {declaration.get('reason')}")

    for book, lb in labels.items():
        if lb["kind"] == "contradicts":
            findings.append({"severity": "CRITICAL", "code": "label_contradicts_behaviour", "book": book,
                             "detail": f"{lb['file']}: {lb['detail']}"})
        elif lb["kind"] == UNMEASURED:
            unmeasured.append(f"ярлык записи {book!r}: {lb.get('reason')}")

    if record_fields["kind"] == "absent":
        findings.append({"severity": "CRITICAL", "code": "record_does_not_carry_the_stage",
                         "detail": record_fields["detail"]})
    elif record_fields["kind"] == UNMEASURED:
        unmeasured.append(f"поля стадии в журнале: {record_fields.get('reason')}")

    if stage2["kind"] == "one_off_grant_only":
        g = stage2["one_off_grant"]
        findings.append({"severity": "WARN", "code": "stage_2_door_is_a_one_off_grant",
                         "detail": (f"единственная дверь «CIO предлагает — владелец подтверждает» — константа в коде "
                                    f"({g['adr']}: книга {g['book']}, ходов {g['moves']}, израсходовано {g['spent']}); "
                                    f"общего канала подтверждения хода у бота нет — семейства act: "
                                    f"{stage2['act_verb_families']}")})
    elif stage2["kind"] == "absent":
        findings.append({"severity": "WARN", "code": "stage_2_door_absent",
                         "detail": "ни разового разрешения, ни канала подтверждения хода"})
    elif stage2["kind"] == UNMEASURED:
        unmeasured.append(f"дверь стадии 2: {stage2.get('reason')}")

    if stage3.get("kind") in ("partly_binding", "none_binding"):
        findings.append({"severity": "WARN", "code": "stage_3_bands_partly_absent",
                         "detail": (f"§41: связывают {stage3['binding']} пределов из {stage3['total']}, отсутствуют "
                                    f"{stage3['absent']} (tally {stage3['tally']}); пределы хода в записи: "
                                    f"{stage3.get('record_caps')} ({stage3.get('record_caps_adr')})"),
                         "carried_from": f"{LIMITS_FILE} (ADR-250, не пересчитано)"})
    elif stage3.get("kind") == UNMEASURED:
        unmeasured.append(f"дверь стадии 3: {stage3.get('reason')}")

    armed = [b for b in books.values() if b["armed"]]
    if proof["kind"] == "not_given" and armed:
        findings.append({"severity": "INFO", "code": "armed_ahead_of_the_proof_gate",
                         "detail": (f"книги {[b['book'] for b in armed]} взведены решением владельца "
                                    f"({sorted({b['armed_adr'] for b in armed})}, {armed[0]['armed_at']}), а дверь "
                                    f"«доказательство безопасности» (ADR-067) отвечает ready_to_arm=False "
                                    f"({None if proof.get('criteria') is None else [c['status'] for c in proof['criteria']]}; "
                                    f"блокада {proof.get('blockade_verdict')}) "
                                    f"— стадия 4 по лестнице не достигнута, поведение стадий 3/4 есть"),
                         "carried_from": "ADR-324/328 (решение владельца 11.09, не судится)"})
    elif proof["kind"] == UNMEASURED:
        unmeasured.append(f"дверь стадии 4: {proof.get('reason')}")

    rel = declaration.get("release_named_files")
    if rel:
        findings.append({"severity": "INFO", "code": "release_word_names_code_releases",
                         "detail": f"файлы {rel} несут слово «release» о РЕЛИЗЕ КОДА (ADR-909), не о стадии CIO"})
    return findings, unmeasured


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None, card_path: Optional[str] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §40. Только ЧИТАЕТ карточку, журнал, записи и артефакты."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    parity_r = parity(card_path)
    journals = load_journals(data_dir)
    rows, _rows_why, corrupt = journals["conservative"]
    books = measure_books(journals)
    real = measure_real_capital(data_dir)
    declaration = measure_declaration(data_dir)
    labels = measure_labels(data_dir, books)
    record_fields = measure_record_fields(journals)
    stage2 = measure_stage2_door(root, data_dir)
    stage3 = measure_stage3_bands(data_dir, rows)
    proof = measure_stage4_proof(data_dir)
    findings, unmeasured = _findings(parity_r, books, real, declaration, labels, record_fields, stage2, stage3, proof)
    counts = {"critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
              "warn": sum(1 for f in findings if f["severity"] == "WARN"),
              "info": sum(1 for f in findings if f["severity"] == "INFO"),
              "unmeasured": len(unmeasured)}
    overall = ("CRITICAL" if counts["critical"] else "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "release_stage_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §40 ТЗ «Portfolio CIO» (Release stages): на какой ступени лестницы "
                     "владельца система стои́т ПО ПОВЕДЕНИЮ у каждого референта (три бумажные книги · реальный "
                     "капитал), объявляет ли хоть один производитель ступень ПОЛЕМ словарём владельца, согласен "
                     "ли ярлык записи с тем, что запись делает, и какие двери есть у стадий 2 (владелец "
                     "подтверждает), 3 (bands) и 4 (доказательство). Ни одно число не считается заново; стадию "
                     "прибор не назначает — это решение владельца. Карточка владельцу не заводится."),
        "overall": overall,
        "counts": counts,
        "declared": {"stages": [dict(s, lines=list(s["lines"])) for s in OWNER_STAGES],
                     "stages_declared": OWNER_STAGES_DECLARED, "lead": OWNER_LEAD,
                     "books": list(BOOKS), "behaviour_kinds": list(BEHAVIOUR_KINDS), "real_kinds": list(REAL_KINDS),
                     "declaration_kinds": list(DECLARATION_KINDS), "label_kinds": list(LABEL_KINDS),
                     "stage2_door_kinds": list(STAGE2_DOOR_KINDS), "proof_kinds": list(PROOF_KINDS),
                     "behaviour_stage": dict(BEHAVIOUR_STAGE), "stage_record_fields": list(STAGE_RECORD_FIELDS),
                     "input_files": list(INPUT_FILES), "order_g973_named": dict(ORDER_G973_NAMED)},
        "parity": parity_r,
        "books": books,
        "real_capital": real,
        "declaration": declaration,
        "labels": labels,
        "record_fields": record_fields,
        "stage2_door": stage2,
        "stage3_bands": stage3,
        "stage4_proof": proof,
        "population": {"journal_rows": {b: (len(j[0]) if j[0] is not None else None) for b, j in journals.items()},
                       "corrupt_lines": {b: j[2] for b, j in journals.items()}},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§40 ТЗ «Portfolio CIO» (Release stages): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (стадий {OWNER_STAGES_DECLARED}; заказ G973 назвал 5, имён процитировал "
              f"{ORDER_G973_NAMED['names_cited']})")
    elif p.get("agrees") is False:
        print("   паритет с карточкой: РАСХОЖДЕНИЕ — " + "; ".join(p["mismatches"]))
    else:
        print(f"   паритет с карточкой: НЕ ИЗМЕРЕН — {p['parsed'].get('reason')}")
    for book, b in doc["books"].items():
        if b["behaviour"] == UNMEASURED:
            print(f"   книга {book:<13} НЕ ИЗМЕРЕНО — {b.get('reason')}")
            continue
        arm = f"взведена {b['armed_at']} ({b['armed_adr']})" if b["armed"] else "не взведена"
        print(f"   книга {book:<13} поведение {b['behaviour']:<21} форма стадии {b['stage_shape']!s:<4} {arm}; "
              f"записей {b['records']} [{b['first_record']}…{b['last_record']}]"
              + (f", тени до взвода {b['shadow_days_before_arming']} дн." if b.get("shadow_days_before_arming") is not None else ""))
    r = doc["real_capital"]
    print(f"   реальный капитал: {r['kind']}" + (f" — {r.get('reason')}" if r["kind"] == UNMEASURED else
          f" (live_mode={r.get('live_mode')}, custody={r.get('custody_connected')}, ready_for_live={r.get('ready_for_live')}, "
          f"posture={r.get('posture')})"))
    d = doc["declaration"]
    if d["kind"] == UNMEASURED:
        print(f"   объявление стадии: НЕ ИЗМЕРЕНО — {d.get('reason')}")
    else:
        print(f"   объявление стадии: {d['kind']} — артефактов {d['files']}, полей режима {d['fields']}, "
              f"словарей {len(d['vocabularies'])}: {d['fields_by_vocabulary']}"
              + (f"; не прочитано {d['files_unread']}" if d["files_unread"] else "")
              + (f"; слишком велики {d['files_too_big']}" if d["files_too_big"] else ""))
    for book, lb in doc["labels"].items():
        print(f"   ярлык {book:<13} {lb['kind']:<12} mode={lb.get('mode')!r} advisory_note={lb.get('note_advisory')}"
              + (f" — {lb.get('reason')}" if lb["kind"] == UNMEASURED else ""))
    rf = doc["record_fields"]
    print(f"   поля стадии в журнале: {rf['kind']} ({rf.get('by_field')})" if rf["kind"] != UNMEASURED
          else f"   поля стадии в журнале: НЕ ИЗМЕРЕНО — {rf.get('reason')}")
    s2 = doc["stage2_door"]
    print(f"   дверь стадии 2: {s2['kind']} — разрешение {s2['one_off_grant']}, глаголы act: {s2.get('act_verb_families')}")
    s3 = doc["stage3_bands"]
    print(f"   дверь стадии 3: {s3.get('kind')} — {s3.get('tally')}, пределы записи {s3.get('record_caps')} ({s3.get('record_caps_adr')})")
    s4 = doc["stage4_proof"]
    print(f"   дверь стадии 4: {s4['kind']} — ready_to_arm={s4.get('ready_to_arm')}, критерии {s4.get('criteria')}, "
          f"блокада {s4.get('blockade_verdict')}")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f.get('detail')}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — момент замера не назван"
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        return None, f"--now не разобран ({exc})"
    return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)), None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§40 ТЗ «Portfolio CIO»: на какой ступени лестницы владельца система стои́т по поведению, "
                    "объявляет ли её полем и согласен ли ярлык записи с поведением")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None, help="каталог данных (журнал ADR-060, записи, артефакты §41/ADR-067/готовности)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card, write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
