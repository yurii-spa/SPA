"""shadow_mode_census.py — §30 ТЗ «Portfolio CIO»: Shadow Mode — обязательный этап.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §30 «Shadow Mode — обязательный этап»::

    Не подключать реальный capital execution сразу.
    После реализации Portfolio CIO сначала работает:
    SHADOW MODE
    Он видит реальные данные и портфель, но не выполняет транзакции.
    Каждый cycle сохраняет:
    what current system did
    what Portfolio CIO recommended
    why
    estimated outcome
    what happened afterwards

Требований здесь ЧЕТЫРЕ, и слить их в одно — ответить не на то:

* **(A) не исполняет** — вердикт тени не двигает книгу. Мерится ДВЕРЬЮ, а не словом
  «shadow» в имени файла: ``cio_arming.trade_allowed`` на настоящей двери, книга
  взведена / не взведена (ADR-324/328), плюс ПОРЯДОК: взведён ли CIO ДО того, как
  критерии взвода (ADR-067, ``shadow_trigger_evaluation.ready_to_arm``) сказали «готов»;
* **(B) видит реальные данные и портфель** — последняя живая запись несёт книгу ТОГО ЖЕ
  дня, что и трек, и ставки с моментом наблюдения (``apy_as_of``), а не литералы;
* **(C) пять полей** — у КАЖДОГО есть носитель. Различаются ТРИ рода: поле лежит в САМОЙ
  записи решения · поле лежит у ВТОРОГО носителя и склеивается с записью по дате ·
  поля нет ни у кого. Второй род законен, но он и есть предмет §30: «каждый цикл
  сохраняет» пять полей ВМЕСТЕ, а склейка по дате — работа читателя, не записи;
* **(D) оба ответа, различимы** — на каждый день трека в окне записи есть ответ СИСТЕМЫ
  (двинула / держала) и ответ CIO (ACT / HOLD), и они не совпадают по построению.

🪤 ЛОВУШКА, ради которой прибор мерит ПОРЯДОК шагов цикла и ДАТУ взвода
======================================================================
Запись решения пишется на Step 2f, а сделка идёт на Step 3 — поэтому «что сделала
система» в записи отсутствует ПО ПОСТРОЕНИЮ порядка шагов, а не по забывчивости:
в момент записи этого ещё никто не знает. Второй порядок: 11.09 владелец ВЗВЁЛ CIO на
всех трёх книгах (ADR-324/328), и с того дня перетасовку решает его вердикт. После
взвода ответ системы и ответ CIO о перетасовке совпадают ПО ПОСТРОЕНИЮ — контрольная
рука сравнения §30/§31 исчезла: ни одного дня расхождения после взвода быть не может,
и «hit_rate = 1.0» на одних HOLD это измеряет НИЧЕГО. Замер по полям сказал бы
«всё сохраняется»; замер по порядку говорит, что сравнивать стало нечего.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): взвод, демпфер, запись решения, судью тени и живой
трек не правит ни байтом. Карточку владельцу не заводит — взвод 11.09 есть решение
владельца (ADR-285: записывать, не переспрашивать). Контрапункты ВВЕЗЕНЫ, не перемерены:
§25 носители (ADR-968), §23 стартовая политика (ADR-966), взвод (ADR-324), «ACT 0 за 30
дней» (ADR-228), судья тени (`shadow_trigger_eval`, Step 2g), §38 `cio_shadow_replay`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/shadow_mode_census.json"

# ───────────────────────────── дословное требование ───────────────────────────
SECTION_HEAD = "30. Shadow Mode — обязательный этап"
NEXT_SECTION_HEAD = "31. Counterfactual tracking"
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

OWNER_FIRST_LINE = "Не подключать реальный capital execution сразу."
OWNER_NO_EXEC_LINE = "Он видит реальные данные и портфель, но не выполняет транзакции."
OWNER_SAVED_LEAD = "Каждый cycle сохраняет:"
OWNER_SAVED_FIELDS: Tuple[str, ...] = (
    "what current system did",
    "what Portfolio CIO recommended",
    "why",
    "estimated outcome",
    "what happened afterwards",
)
#: Число ОБЪЯВЛЕНО и краснеет тестом (урок §22/§23: заказ назвал меньше, чем владелец).
OWNER_SAVED_FIELDS_DECLARED = 5
#: Заказ G962 п. 1 процитировал первые два поля и поставил «…» — хвост не читан.
ORDER_G962_NAMED: Dict[str, Any] = {"saved_fields": 2, "tail_read": False}

# ───────────────────────────── словари родов ───────────────────────────────────
#: (A) кто решает перетасовку в книге.
EXEC_KINDS: Tuple[str, ...] = ("shadow_only", "verdict_decides", UNMEASURED)
#: (B) род входа записи.
INPUT_KINDS: Tuple[str, ...] = ("real_same_day", "stale", "absent", UNMEASURED)
#: (C) где живёт поле владельца.
FIELD_KINDS: Tuple[str, ...] = ("in_the_record", "in_a_second_carrier", "absent_everywhere",
                                UNMEASURED)
#: (D) ответ системы за день.
ACTION_KINDS: Tuple[str, ...] = ("moved", "held", UNMEASURED)

#: Носители: запись решения (§25 «shadow», ADR-968) и вторые носители, склеиваемые по дате.
RECORD_REL = "allocation_rationale_history.jsonl"
TRACK_REL = "equity_curve_daily.json"
TRADES_REL = "trades.json"
EVAL_REL = "shadow_trigger_evaluation.json"
COMMIT_REL = "book_commit_packages.jsonl"

#: Поле владельца → (ключи САМОЙ записи, вторые носители: имя → ключи).
FIELD_CARRIERS: Dict[str, Dict[str, Any]] = {
    "what current system did": {
        "record_keys": (),
        "second": {TRACK_REL: ("daily[].turnover_usd", "daily[].positions"),
                   TRADES_REL: ("[].ts", "[].to_allocation"),
                   COMMIT_REL: ("package.action",)},
        "why_not_in_record": ("запись пишется на Step 2f, сделка идёт на Step 3 — в момент "
                              "записи ответ системы ещё не существует"),
    },
    "what Portfolio CIO recommended": {
        "record_keys": ("verdict", "legs", "target_positions"), "second": {},
    },
    "why": {"record_keys": ("reasons", "gates"), "second": {}},
    "estimated outcome": {
        "record_keys": ("gain_pp", "cost_usd", "payback_days", "target_apy_pp", "book_apy_pp"),
        "second": {},
    },
    "what happened afterwards": {
        "record_keys": (),
        "second": {EVAL_REL: ("per_verdict[].outcome", "per_verdict[].counterfactual")},
        "why_not_in_record": ("исход известен только через горизонт (7 дн.); судья тени "
                              "пересчитывает его КАЖДЫЙ цикл по всему окну и перезаписывает "
                              "артефакт — запись при этом не дописывается"),
    },
}

#: Маркеры ПОРЯДКА в `cycle_runner.py`: писатель записи (Step 2f) · дверь взвода (Step 3) ·
#: сама сделка. Каждый обязан встретиться РОВНО один раз.
CYCLE_RUNNER_REL = "spa_core/paper_trading/cycle_runner.py"
ORDER_MARKERS: Dict[str, str] = {
    "record_writer": "_cio_doc = write_shadow_rationale(",
    "arming_door": "_cio_arming.trade_allowed(",
    "trade_decision": "and _cio_gate_ok)",
}

SCENE_BOOK_ARMED = "conservative"
SCENE_BOOK_UNARMED = "scene_unarmed_book"


# ───────────────────────────── общие помощники ───────────────────────────────

def _read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _read_jsonl(path: Path) -> Tuple[Optional[List[dict]], Optional[str], int]:
    """(строки, причина, битых строк). Битая строка — счёт, а не молчание."""
    text, why = _read_text(str(path))
    if text is None:
        return None, why, 0
    rows: List[dict] = []
    corrupt = 0
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except ValueError:
            corrupt += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            corrupt += 1
    return rows, None, corrupt


def _date_of(ts: object) -> Optional[str]:
    s = str(ts or "")
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else None


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по нему "
                      f"был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _items_after(body: List[str], lead: str) -> Optional[List[str]]:
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if not s or s == "⸻":
            if out and s == "⸻":
                break
            continue
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = _read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {
        "measured": True,
        "saved_fields": _items_after(body, OWNER_SAVED_LEAD),
        "first_line_present": OWNER_FIRST_LINE in stripped,
        "no_exec_line_present": OWNER_NO_EXEC_LINE in stripped,
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None, "order_tail_read": ORDER_G962_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    fields = parsed["saved_fields"]
    if fields is None:
        mism.append(f"в разделе нет строки {OWNER_SAVED_LEAD!r}")
    elif list(fields) != list(OWNER_SAVED_FIELDS):
        mism.append(f"поля карточки {fields} ≠ константам {list(OWNER_SAVED_FIELDS)}")
    if not parsed["first_line_present"]:
        mism.append("строка «не подключать реальный capital execution сразу» не найдена")
    if not parsed["no_exec_line_present"]:
        mism.append("строка «видит реальные данные … не выполняет транзакции» не найдена")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if fields is not None:
        out["order_undercount"] = len(fields) - int(ORDER_G962_NAMED["saved_fields"])
    return out


# ───────────────────────────── порядок шагов цикла ───────────────────────────

def measure_cycle_order(root: str = REPO_ROOT, text: Optional[str] = None) -> Dict[str, Any]:
    """Писатель записи (Step 2f) стои́т ДО двери взвода и ДО сделки (Step 3)?

    Каждый маркер РОВНО один раз: ноль — порядок не измерен, два — тоже.
    """
    if text is None:
        text, why = _read_text(os.path.join(root, CYCLE_RUNNER_REL))
        if text is None:
            return {"kind": UNMEASURED, "reason": f"{CYCLE_RUNNER_REL} не прочитан: {why}",
                    "lines": {}}
    lines: Dict[str, int] = {}
    for name, marker in ORDER_MARKERS.items():
        hits = [i + 1 for i, ln in enumerate(text.splitlines()) if marker in ln]
        if len(hits) != 1:
            return {"kind": UNMEASURED,
                    "reason": f"маркер {name!r} ({marker!r}) встретился {len(hits)} раз(а), "
                              f"ожидался ровно один — порядок не измерен",
                    "lines": {}}
        lines[name] = hits[0]
    w, d, t = lines["record_writer"], lines["arming_door"], lines["trade_decision"]
    if w < d < t:
        return {"kind": "record_precedes_the_trade", "lines": lines,
                "reason": (f"запись решения пишется (строка {w}) ДО двери взвода (строка {d}) "
                           f"и ДО сделки (строка {t}): ответ системы в момент записи ещё не "
                           f"существует")}
    return {"kind": "trade_precedes_the_record", "lines": lines,
            "reason": f"сделка (строка {t}) или дверь взвода (строка {d}) стоя́т до записи (строка {w})"}


# ───────────────────────────── ось A: не исполняет ───────────────────────────

def _door_arming(book_id: str, verdict: str, current: Dict[str, float],
                 target: Dict[str, float]) -> Dict[str, Any]:
    """Настоящая дверь `cio_arming.trade_allowed` на перетасовке с вердиктом тени."""
    try:
        from spa_core.paper_trading import cio_arming
    except Exception as exc:  # noqa: BLE001 — нечем измерить ≠ «не исполняет»
        return {"kind": UNMEASURED, "reason": f"cio_arming не импортирован: {type(exc).__name__}: {exc}"}
    doc = {"decision_shadow": {"decision": verdict, "reasons": ["scene"]}}
    try:
        allowed, decision, why = cio_arming.trade_allowed(
            book_id, doc, current, target, damper_reason="reshuffle")
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "reason": f"дверь упала: {type(exc).__name__}: {exc}"}
    armed = cio_arming.is_armed(book_id)
    return {"kind": "verdict_decides" if armed else "shadow_only",
            "armed": armed, "allowed": allowed, "decision": decision, "why": why,
            "armed_meta": dict((cio_arming.ARMED_BOOKS or {}).get(book_id) or {})}


def measure_execution(data_dir: str, order: Dict[str, Any]) -> Dict[str, Any]:
    """(A): решает ли вердикт тени перетасовку, и взведён ли CIO ДО готовности."""
    try:
        from spa_core.analytics import anti_churn_census as s22
        capital = float(s22._scene_capital())
        books = s22._books(capital)
        current, target = dict(books["A"]), dict(books["B"])
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"сцена §22 не ввезена: {type(exc).__name__}: {exc}"}

    armed_hold = _door_arming(SCENE_BOOK_ARMED, "HOLD", current, target)
    armed_act = _door_arming(SCENE_BOOK_ARMED, "ACT", current, target)
    unarmed_hold = _door_arming(SCENE_BOOK_UNARMED, "HOLD", current, target)
    doors = {"armed_book_hold": armed_hold, "armed_book_act": armed_act,
             "unarmed_book_hold": unarmed_hold}
    if any(d.get("kind") == UNMEASURED for d in doors.values()):
        kind, why = UNMEASURED, "; ".join(
            f"{k}: {d.get('reason')}" for k, d in doors.items() if d.get("kind") == UNMEASURED)
    elif (armed_hold["allowed"] is False and armed_act["allowed"] is True
          and unarmed_hold["allowed"] is True
          and armed_hold["kind"] == armed_act["kind"] == "verdict_decides"
          and unarmed_hold["kind"] == "shadow_only"):
        # Род ДВЕРИ и её ОТВЕТ обязаны сходиться: дверь, назвавшая себя советником и при этом
        # запретившая ход, — противоречие, а не вердикт (мутация M05 первого прохода выжила
        # ровно потому, что род двери никто не сверял с её ответом).
        kind, why = "verdict_decides", (
            f"в книге «{SCENE_BOOK_ARMED}» вердикт тени РЕШАЕТ перетасовку (HOLD ⇒ "
            f"{armed_hold['decision']}, ACT ⇒ {armed_act['decision']}); в невзведённой книге "
            f"дверь отвечает {unarmed_hold['decision']} и не вмешивается")
    elif armed_hold["allowed"] is True and armed_hold["kind"] == "shadow_only":
        kind, why = "shadow_only", "вердикт тени перетасовку не задерживает — тень советует"
    else:
        kind, why = UNMEASURED, f"дверь ответила непредвиденно: {doors}"

    armed_books: Dict[str, Any] = {}
    try:
        from spa_core.paper_trading import cio_arming
        armed_books = {k: dict(v) for k, v in (cio_arming.ARMED_BOOKS or {}).items()}
    except Exception as exc:  # noqa: BLE001
        armed_books = {UNMEASURED: f"{type(exc).__name__}: {exc}"}

    ev, why_ev = _read_json(Path(data_dir) / EVAL_REL)
    readiness: Dict[str, Any]
    if ev is None:
        readiness = {"measured": False, "reason": f"{EVAL_REL} не прочитан: {why_ev}"}
    else:
        readiness = {"measured": True, "ready_to_arm": ev.get("ready_to_arm"),
                     "status": ev.get("status"),
                     "criteria": {c.get("criterion"): c.get("status")
                                  for c in (ev.get("criteria") or []) if isinstance(c, dict)},
                     "observation_days": ev.get("observation_days"),
                     # Нет словаря счётов ⇒ None, а не пустой словарь (инв. #17).
                     "counts": ev.get("counts") if isinstance(ev.get("counts"), dict) else None,
                     "arming_blockade": (ev.get("arming_blockade") or {}).get("verdict")}
    armed_before_ready: Optional[bool] = None
    if readiness.get("measured") and kind == "verdict_decides":
        armed_before_ready = readiness.get("ready_to_arm") is False
    return {"measured": True, "kind": kind, "why": why, "doors": doors,
            "armed_books": armed_books, "arming_readiness": readiness,
            "armed_before_ready": armed_before_ready, "cycle_order": order.get("kind")}


# ───────────────────────────── живые носители ────────────────────────────────

def load_carriers(data_dir: str) -> Dict[str, Any]:
    d = Path(data_dir)
    recs, why_r, corrupt = _read_jsonl(d / RECORD_REL)
    track, why_t = _read_json(d / TRACK_REL)
    trades, why_x = _read_json(d / TRADES_REL)
    ev, why_e = _read_json(d / EVAL_REL)
    commits, why_c, corrupt_c = _read_jsonl(d / COMMIT_REL)
    daily = (track or {}).get("daily") if isinstance(track, dict) else None
    return {
        "records": recs, "records_reason": why_r, "records_corrupt": corrupt,
        "daily": daily if isinstance(daily, list) else None,
        "daily_reason": why_t if track is None else (None if isinstance(daily, list)
                                                     else "в треке нет списка daily"),
        "trades": trades if isinstance(trades, list) else None,
        "trades_reason": why_x if trades is None else (None if isinstance(trades, list)
                                                       else "trades.json не список"),
        "eval": ev if isinstance(ev, dict) else None, "eval_reason": why_e,
        "commits": commits, "commits_reason": why_c, "commits_corrupt": corrupt_c,
    }


# ───────────────────────────── ось B: реальные входы ─────────────────────────

def measure_inputs(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """(B): последняя запись видит портфель и ставки ТОГО ЖЕ дня, что и трек."""
    recs, daily = carriers.get("records"), carriers.get("daily")
    if not recs:
        return {"measured": False, "reason": f"запись решения не прочитана/пуста: "
                                              f"{carriers.get('records_reason') or 'нет строк'}"}
    last = recs[-1]
    inputs: Dict[str, Dict[str, Any]] = {}

    # портфель: книга записи == книга трека того же дня
    if daily is None:
        inputs["portfolio"] = {"kind": UNMEASURED,
                               "reason": f"трек не прочитан: {carriers.get('daily_reason')}"}
    else:
        day = next((x for x in reversed(daily) if x.get("date") == last.get("cycle_date")), None)
        if day is None:
            inputs["portfolio"] = {"kind": "stale", "reason": (
                f"дня {last.get('cycle_date')} в треке нет — запись видит не сегодняшний портфель")}
        else:
            rec_pos = {k: round(float(v), 2) for k, v in (last.get("current_positions") or {}).items()}
            trk_pos = {k: round(float(v), 2) for k, v in (day.get("positions") or {}).items()}
            if not rec_pos:
                inputs["portfolio"] = {"kind": "absent", "reason": "в записи нет current_positions"}
            elif rec_pos == trk_pos:
                inputs["portfolio"] = {"kind": "real_same_day", "date": last.get("cycle_date"),
                                       "positions": len(rec_pos)}
            else:
                inputs["portfolio"] = {"kind": "stale", "reason": (
                    f"книга записи {rec_pos} ≠ книге трека {trk_pos} на {last.get('cycle_date')}")}

    # ставки: evidenced и с моментом наблюдения того же дня
    # Три состояния у каждого поля различимы: нет ключа · не словарь · словарь (пустой или нет);
    # подстановка `or {}` склеила бы первые два с пустым словарём (инв. #17).
    apy_raw = last.get("apy_evidenced_pct")
    apy = apy_raw if isinstance(apy_raw, dict) else None
    as_of_raw = last.get("apy_as_of")
    as_of = as_of_raw if isinstance(as_of_raw, dict) else None
    if "apy_evidenced_pct" not in last:
        inputs["rates"] = {"kind": "absent", "reason": "в записи нет apy_evidenced_pct"}
    elif apy is None:
        inputs["rates"] = {"kind": UNMEASURED,
                           "reason": f"apy_evidenced_pct не словарь ({type(apy_raw).__name__})"}
    elif not apy:
        inputs["rates"] = {"kind": "absent", "reason": "apy_evidenced_pct пуст — ни одной живой ставки"}
    else:
        same_day = [p for p in apy
                    if as_of is not None and _date_of(as_of.get(p)) == last.get("cycle_date")]
        if not as_of:
            inputs["rates"] = {"kind": UNMEASURED, "rates": len(apy),
                               "reason": "apy_as_of отсутствует — день наблюдения ставок не записан"}
        elif len(same_day) == len(apy):
            inputs["rates"] = {"kind": "real_same_day", "rates": len(apy), "date": last.get("cycle_date")}
        else:
            inputs["rates"] = {"kind": "stale", "rates": len(apy), "same_day": len(same_day),
                               "reason": f"{len(apy) - len(same_day)} ставок наблюдены не в день записи"}
    tally = {k: sum(1 for v in inputs.values() if v.get("kind") == k) for k in INPUT_KINDS}
    return {"measured": True, "record_date": last.get("cycle_date"), "inputs": inputs, "tally": tally}


# ───────────────────────────── ось C: пять полей ─────────────────────────────

def _writer_keys(root: str) -> Tuple[Optional[set], Optional[str]]:
    """Ключи, которые объявляет писатель записи (текст `build_history_record`)."""
    path = os.path.join(root, "spa_core/paper_trading/allocation_rationale.py")
    text, why = _read_text(path)
    if text is None:
        return None, f"писатель не прочитан: {why}"
    start = text.find("def build_history_record(")
    if start < 0:
        return None, "в писателе нет build_history_record"
    body = text[start:]
    nxt = body.find("\ndef ", 10)
    body = body[:nxt] if nxt > 0 else body
    keys = set()
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith('"') and '":' in s:
            keys.add(s[1:s.index('":')])
    return keys, None


def measure_fields(root: str, carriers: Dict[str, Any]) -> Dict[str, Any]:
    """(C): у каждого поля владельца — род носителя и покрытие на живых записях."""
    recs = carriers.get("records")
    writer, why_w = _writer_keys(root)
    fields: Dict[str, Dict[str, Any]] = {}
    for name, spec in FIELD_CARRIERS.items():
        row: Dict[str, Any] = {"record_keys": list(spec["record_keys"]),
                               "second_carriers": {k: list(v) for k, v in spec["second"].items()}}
        rk = spec["record_keys"]
        if rk:
            if writer is None:
                row.update(kind=UNMEASURED, reason=why_w)
            elif not set(rk) <= writer:
                row.update(kind=UNMEASURED,
                           reason=f"писатель не объявляет {sorted(set(rk) - writer)} — "
                                  f"константа прибора расходится с кодом")
            elif not recs:
                row.update(kind=UNMEASURED, reason="живых записей нет — покрытие не измерено")
            else:
                cov = {k: sum(1 for r in recs if r.get(k) is not None) for k in rk}
                row.update(kind="in_the_record", coverage=cov, records=len(recs))
        else:
            present = {c: c for c in spec["second"]}
            readable = {}
            for c in present:
                if c == TRACK_REL:
                    readable[c] = carriers.get("daily") is not None
                elif c == TRADES_REL:
                    readable[c] = carriers.get("trades") is not None
                elif c == EVAL_REL:
                    readable[c] = carriers.get("eval") is not None
                elif c == COMMIT_REL:
                    readable[c] = carriers.get("commits") is not None
                else:
                    readable[c] = False
            if not any(readable.values()):
                row.update(kind=UNMEASURED,
                           reason=f"ни один второй носитель не прочитан: {readable}")
            else:
                row.update(kind="in_a_second_carrier", readable=readable,
                           why_not_in_record=spec.get("why_not_in_record"))
                if name == "what happened afterwards" and carriers.get("eval"):
                    pv = carriers["eval"].get("per_verdict") or []
                    outcomes: Dict[str, int] = {}
                    for p in pv:
                        o = str(p.get("outcome"))
                        outcomes[o] = outcomes.get(o, 0) + 1
                    row["per_verdict"] = {"rows": len(pv), "outcomes": outcomes}
                if name == "what current system did" and carriers.get("commits") is not None:
                    acts: Dict[str, int] = {}
                    for c in carriers["commits"]:
                        pkg = c.get("package")
                        a = str(pkg.get("action")) if isinstance(pkg, dict) else UNMEASURED
                        acts[a] = acts.get(a, 0) + 1
                    row["commit_actions"] = acts
        fields[name] = row
    tally = {k: sum(1 for v in fields.values() if v.get("kind") == k) for k in FIELD_KINDS}
    return {"measured": True, "fields": fields, "tally": tally,
            "writer_keys": sorted(writer) if writer else None}


# ───────────────────────────── ось D: оба ответа по дням ─────────────────────

def system_action_for_day(date: str, daily_by_date: Dict[str, dict],
                          trade_dates: Optional[set]) -> Dict[str, Any]:
    """Ответ СИСТЕМЫ за день: двинула · держала · не измерено.

    `turnover_usd` > 0 ИЛИ сделка этой даты ⇒ moved; `turnover_usd == 0` и сделок нет ⇒
    held; ключа оборота нет и сделок нет ⇒ UNMEASURED (отсутствие сделки — не наблюдение
    удержания, инв. #17).
    """
    day = daily_by_date.get(date)
    turnover = day.get("turnover_usd") if isinstance(day, dict) else None
    traded = (date in trade_dates) if trade_dates is not None else None
    if (turnover or 0) > 0 or traded:
        return {"kind": "moved", "turnover_usd": turnover, "trade_on_date": traded}
    if turnover == 0 and traded is False:
        return {"kind": "held", "turnover_usd": 0.0, "trade_on_date": False}
    if turnover == 0 and traded is None:
        return {"kind": "held", "turnover_usd": 0.0, "trade_on_date": None,
                "note": "сделки не прочитаны; удержание — по обороту трека"}
    return {"kind": UNMEASURED, "turnover_usd": turnover, "trade_on_date": traded,
            "reason": "в треке нет turnover_usd за день, а сделок на дату нет — удержание не наблюдено"}


def measure_pairs(carriers: Dict[str, Any], armed_at: Optional[str]) -> Dict[str, Any]:
    """(D): на каждый день трека в окне записи — ответ системы и ответ CIO."""
    recs, daily = carriers.get("records"), carriers.get("daily")
    if not recs:
        return {"measured": False, "reason": "записей решения нет"}
    if daily is None:
        return {"measured": False, "reason": f"трек не прочитан: {carriers.get('daily_reason')}"}
    by_date: Dict[str, List[dict]] = {}
    for r in recs:
        d = r.get("cycle_date")
        if d:
            by_date.setdefault(d, []).append(r)
    if not by_date:
        return {"measured": False, "reason": "ни одна запись не несёт cycle_date"}
    w0, w1 = min(by_date), max(by_date)
    daily_by_date: Dict[str, dict] = {str(x.get("date")): x for x in daily
                                      if isinstance(x, dict) and isinstance(x.get("date"), str)}
    track_days = sorted(d for d in daily_by_date if w0 <= d <= w1)
    trades = carriers.get("trades")
    trade_dates = ({_date_of(t.get("ts")) for t in trades if isinstance(t, dict)}
                   if trades is not None else None)
    matrix: Dict[str, int] = {}
    divergent: List[Dict[str, Any]] = []
    after_arming = {"days": 0, "divergent": 0, "moved": 0}
    multi_run_days = 0
    for d in track_days:
        rs = by_date.get(d)
        if not rs:
            matrix["no_record"] = matrix.get("no_record", 0) + 1
            continue
        if len(rs) > 1:
            multi_run_days += 1
        cio = "ACT" if any(r.get("verdict") == "ACT" for r in rs) else (
            "HOLD" if all(r.get("verdict") == "HOLD" for r in rs) else UNMEASURED)
        sysa = system_action_for_day(d, daily_by_date, trade_dates)
        key = f"{sysa['kind']}&{cio}"
        matrix[key] = matrix.get(key, 0) + 1
        diverges = (sysa["kind"] == "moved" and cio == "HOLD") or (sysa["kind"] == "held" and cio == "ACT")
        if diverges:
            divergent.append({"date": d, "system": sysa["kind"], "cio": cio,
                              "turnover_usd": sysa.get("turnover_usd")})
        if armed_at and d > armed_at:
            after_arming["days"] += 1
            after_arming["divergent"] += int(diverges)
            after_arming["moved"] += int(sysa["kind"] == "moved")
    missing = [d for d in track_days if d not in by_date]
    return {"measured": True, "window": [w0, w1], "track_days": len(track_days),
            "days_with_record": len(track_days) - len(missing), "days_without_record": missing,
            "records": len(recs), "multi_run_days": multi_run_days, "matrix": matrix,
            "divergent_days": divergent, "armed_at": armed_at, "after_arming": after_arming,
            "answers_distinguishable": bool(divergent)}


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], order: Dict[str, Any], execution: Dict[str, Any],
              inputs: Dict[str, Any], fields: Dict[str, Any],
              pairs: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    if order.get("kind") == UNMEASURED:
        unmeasured.append(f"порядок шагов цикла: {order.get('reason')}")

    # (A)
    if not execution.get("measured"):
        unmeasured.append(f"ось A: {execution.get('reason')}")
    elif execution.get("kind") == UNMEASURED:
        unmeasured.append(f"ось A: {execution.get('why')}")
    elif execution.get("kind") == "verdict_decides":
        rd = execution.get("arming_readiness") or {}
        meta = (execution.get("armed_books") or {}).get(SCENE_BOOK_ARMED) or {}
        if execution.get("armed_before_ready") is True:
            add("WARN", "armed_before_the_shadow_criteria_passed",
                f"CIO взведён на книгах {sorted(execution.get('armed_books') or {})} "
                f"решением владельца {meta.get('armed_at')} ({meta.get('adr')}), а критерии взвода "
                f"ADR-067 и сегодня говорят ready_to_arm={rd.get('ready_to_arm')} "
                f"({rd.get('criteria')}): этап §30 «обязательный, ПОТОМ подключать» пройден "
                f"приказом, не замером — решение владельца, записано, не переспрашивается (ADR-285)")
        elif execution.get("armed_before_ready") is None:
            unmeasured.append("ось A: готовность взвода (shadow_trigger_evaluation) не прочитана")
        add("INFO", "shadow_verdict_decides_the_reshuffle",
            f"{execution.get('why')} — на бумаге; реальный capital execution не подключён "
            f"(REAL CAPITAL = $0), первая строка §30 цела")

    # (B)
    if not inputs.get("measured"):
        unmeasured.append(f"ось B: {inputs.get('reason')}")
    else:
        for name, r in inputs["inputs"].items():
            if r.get("kind") == "stale":
                add("WARN", f"input_not_same_day:{name}", f"«{name}»: {r.get('reason')}")
            elif r.get("kind") == "absent":
                add("CRITICAL", f"input_absent:{name}", f"«{name}»: {r.get('reason')}")
            elif r.get("kind") == UNMEASURED:
                unmeasured.append(f"ось B «{name}»: {r.get('reason')}")

    # (C)
    if not fields.get("measured"):
        unmeasured.append("ось C не измерена")
    else:
        for name, r in fields["fields"].items():
            if r.get("kind") == "absent_everywhere":
                add("CRITICAL", f"field_absent_everywhere:{name}", f"«{name}»: носителя нет")
            elif r.get("kind") == UNMEASURED:
                unmeasured.append(f"ось C «{name}»: {r.get('reason')}")
        sys_row = fields["fields"].get("what current system did") or {}
        if sys_row.get("kind") == "in_a_second_carrier" and order.get("kind") == "record_precedes_the_trade":
            ln = order.get("lines") or {}
            add("WARN", "system_action_absent_from_the_record_by_step_order",
                f"«what current system did» в записи решения отсутствует ПО ПОСТРОЕНИЮ: запись "
                f"пишется на Step 2f (строка {ln.get('record_writer')}), сделка решается на Step 3 "
                f"(строка {ln.get('trade_decision')}); ответ системы живёт у вторых носителей "
                f"{sorted(sys_row.get('readable') or {})} и склеивается по дате читателем — "
                f"«каждый цикл сохраняет» пять полей ВМЕСТЕ не исполнено для первого из пяти")
        aft = fields["fields"].get("what happened afterwards") or {}
        if aft.get("kind") == "in_a_second_carrier":
            pv = aft.get("per_verdict") or {}
            add("INFO", "afterwards_is_recomputed_not_appended",
                f"«what happened afterwards» живёт у судьи тени ({EVAL_REL}, строк per_verdict "
                f"{pv.get('rows')}, исходы {pv.get('outcomes')}): пересчитывается каждый цикл по "
                f"всему окну, запись решения не дописывается — воспроизводимо, но не «сохранено "
                f"каждым циклом»")

    # (D)
    if not pairs.get("measured"):
        unmeasured.append(f"ось D: {pairs.get('reason')}")
    else:
        if pairs.get("days_without_record"):
            add("WARN", "track_days_without_a_record",
                f"{len(pairs['days_without_record'])} дн. трека в окне записи без записи решения: "
                f"{pairs['days_without_record'][:10]}")
        um = sum(v for k, v in (pairs.get("matrix") or {}).items() if k.startswith(UNMEASURED))
        if um:
            add("WARN", "system_action_unmeasured_on_days",
                f"на {um} дн. ответ системы НЕ ИЗМЕРЕН: в треке нет turnover_usd и сделок на дату "
                f"нет — удержание не наблюдено, а подразумевается")
        aa = pairs.get("after_arming") or {}
        if pairs.get("armed_at") and execution.get("kind") == "verdict_decides":
            if aa.get("days", 0) > 0 and aa.get("divergent", 0) == 0:
                add("CRITICAL", "control_arm_collapsed_after_arming",
                    f"после взвода {pairs['armed_at']} — {aa['days']} дн. трека, расхождений "
                    f"«система ↔ CIO» 0, ходов {aa['moved']}: во взведённой книге ответ системы о "
                    f"перетасовке ЕСТЬ ответ CIO, сравнивать §30/§31 стало нечего; до взвода "
                    f"расхождений {len(pairs.get('divergent_days') or [])} "
                    f"({[d['date'] for d in pairs.get('divergent_days') or []]}); hit_rate на одних "
                    f"HOLD меряет не советника, а тишину")
        if not pairs.get("answers_distinguishable"):
            add("WARN", "answers_never_diverged",
                "за всё окно записи система ни разу не разошлась с CIO — различимость двух ответов "
                "не наблюдена ни на одном дне")
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §30. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    order = measure_cycle_order(root)
    carriers = load_carriers(data_dir)
    execution = measure_execution(data_dir, order)
    inputs = measure_inputs(carriers)
    fields = measure_fields(root, carriers)
    armed_at = ((execution.get("armed_books") or {}).get(SCENE_BOOK_ARMED) or {}).get("armed_at") \
        if execution.get("measured") else None
    pairs = measure_pairs(carriers, armed_at)

    findings, unmeasured = _findings(parity_r, order, execution, inputs, fields, pairs)
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
        "schema": "shadow_mode_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §30 ТЗ «Portfolio CIO» (Shadow Mode). Взвод, демпфер, "
                     "запись решения, судью тени и живой трек НЕ трогает; карточку владельцу не "
                     "заводит — взвод 11.09 есть решение владельца"),
        "overall": overall,
        "counts": counts,
        "declared": {"saved_fields": list(OWNER_SAVED_FIELDS),
                     "saved_fields_declared": OWNER_SAVED_FIELDS_DECLARED,
                     "first_line": OWNER_FIRST_LINE, "no_exec_line": OWNER_NO_EXEC_LINE,
                     "order_g962_named": dict(ORDER_G962_NAMED),
                     "exec_kinds": list(EXEC_KINDS), "input_kinds": list(INPUT_KINDS),
                     "field_kinds": list(FIELD_KINDS), "action_kinds": list(ACTION_KINDS),
                     "order_markers": dict(ORDER_MARKERS)},
        "parity": parity_r,
        "cycle_order": order,
        "axis_a_execution": execution,
        "axis_b_inputs": inputs,
        "axis_c_fields": fields,
        "axis_d_pairs": pairs,
        "carriers_read": {k: (v is not None) for k, v in carriers.items()
                          if k in ("records", "daily", "trades", "eval", "commits")},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path): перестановка у §26 оставляла прибор без артефакта.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§30 ТЗ «Portfolio CIO» (Shadow Mode): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (полей {OWNER_SAVED_FIELDS_DECLARED}; заказ G962 "
              f"назвал {ORDER_G962_NAMED['saved_fields']}, хвост не читал, сдвиг {p.get('order_undercount')})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    o = doc["cycle_order"]
    print(f"   порядок шагов цикла: {o.get('kind')} — {o.get('reason')}")
    a = doc["axis_a_execution"]
    if a.get("measured"):
        rd = a.get("arming_readiness") or {}
        print(f"   [ось A] исполнение: {a.get('kind')} · взведены {sorted(a.get('armed_books') or {})} · "
              f"ready_to_arm={rd.get('ready_to_arm')} · взведён до готовности: {a.get('armed_before_ready')}")
    else:
        print(f"   [ось A] НЕ ИЗМЕРЕНО: {a.get('reason')}")
    b = doc["axis_b_inputs"]
    if b.get("measured"):
        print(f"   [ось B] входы записи {b.get('record_date')}: " + ", ".join(
            f"{k}→{v.get('kind')}" for k, v in b["inputs"].items()))
    else:
        print(f"   [ось B] НЕ ИЗМЕРЕНО: {b.get('reason')}")
    f = doc["axis_c_fields"]
    if f.get("measured"):
        print(f"   [ось C] пять полей: {f.get('tally')}")
        for name, r in f["fields"].items():
            extra = r.get("coverage") or r.get("readable") or ""
            print(f"      «{name}»: {r.get('kind')} {extra}")
    d = doc["axis_d_pairs"]
    if d.get("measured"):
        print(f"   [ось D] окно {d.get('window')} · дней трека {d.get('track_days')} · с записью "
              f"{d.get('days_with_record')} · записей {d.get('records')} · дней с >1 прогоном "
              f"{d.get('multi_run_days')} · матрица {d.get('matrix')} · расхождений "
              f"{len(d.get('divergent_days') or [])} · после взвода {d.get('after_arming')}")
    else:
        print(f"   [ось D] НЕ ИЗМЕРЕНО: {d.get('reason')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    """``--now`` — вход, не окружение. Пустое/неразбираемое — ОТКАЗ, не часы."""
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — отказ, а не стенные часы"
    try:
        ts = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None, f"--now {raw!r} не разбирается как ISO-8601 — отказ, а не стенные часы"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts, None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§30 ТЗ «Portfolio CIO»: Shadow Mode — сохраняет ли каждый цикл пять полей "
                    "владельца, различимы ли ответ системы и ответ CIO, исполняет ли тень")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(ns.data_dir if ns.data_dir else ns.root, who="shadow_mode_census")
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
