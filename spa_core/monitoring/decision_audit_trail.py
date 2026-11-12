"""decision_audit_trail.py — можно ли объяснить прошлую перекладку ЧЕРЕЗ ДАННЫЕ.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §43 «Audit trail»::

    Каждое решение должно быть воспроизводимо.
    Сохранять: market snapshot · portfolio snapshot · policy version ·
    configuration version · optimizer version · decision · calculations ·
    execution result · post-trade result.
    Через месяц должно быть возможно ответить:
    «Почему система 13 августа переместила $12,000 из Aave в Morpho?»
    Не через память AI. Через данные.

Девять полей — НЕ наш список. Это дословный перечень владельца, и его дом —
карточка приказа (`inbox-task-portfolio-cio-dynamic-capital-alloc`). Модуль
не назначает ни одного порога: он берёт девять названных полей и по КАЖДОЙ
реальной перекладке живого трека проверяет, отвечает ли на них файл, а не
память сессии.

Что здесь проверяется — ВОССТАНОВИМОСТЬ, а не наличие файла
===========================================================
Поле засчитывается только если названный источник ОТДАЁТ значение именно для
ЭТОГО решения. «Файл с подходящим именем существует» — не ответ: ровно на этом
и держится класс ADR-053/242/243/244 (измеритель построен, потребителя нет) и
находка #505 (имя критерия было занято модулем про другое). Поэтому у каждого
поля есть исход `absent` с НАЗВАННОЙ причиной и отдельный третий исход
`unmeasured` — «источник нечитаем», который не равен «данных нет».

Почему `snapshot_id` меряется ОПЫТОМ, а не чтением кода
=======================================================
В каждой записи трейла стоит поле `snapshot_id` вида
``2026-08-31:9320103a61e4595d`` — по виду адрес содержимого рыночного снимка.
Модуль не верит виду: он дважды зовёт САМ производитель
(`spa_core.audit.audit_trail._make_snapshot_id`) с ОДНИМ И ТЕМ ЖЕ входом. Если
два вызова дают разные значения, идентификатор не может адресовать содержимое
— он именует ПРОГОН. Это измерение, а не рассуждение, и оно краснеет само,
если производителя однажды починят.

«Каждое решение должно быть воспроизводимо» — ось ADR-989 (цикл #1106)
=======================================================================
Девять полей отвечают на вопрос «что сохранено». Первая строка §43 задаёт
другой: воспроизводимо ли решение. Трейл записывает решение ОДИН раз — на
Step 2 (`allocation_proposal.target_usd`) — и ход ОДИН раз — на Step 3
(`trade_executed.to_allocation`); между ними живой цикл переписывает цель
ступенями (RiskPolicy-трим · стоп-кран · SOFT де-риск · RTMR · псевдонимы ·
урезание ADR-850), и ни одна из них своего результата в трейл не пишет. Замер
12.11: из 46 перекладок у 43 исполненная книга НЕ равна записанному решению, и
ни одно событие цепочки не несёт переписанной цели — трейл отвечает на «почему
13 августа переместили $12 000» решением, которого цикл не исполнил. Поэтому с
ADR-989 «полностью объяснима» перекладка только тогда, когда девять полей
отвечают И исполненная книга равна записанному решению (или причина
расхождения записана событием цепочки). Ступени между двумя записями меряются
AST цикла (`rewrite_steps_between_records`), а не памятью о нём: ступень,
добавленная после прибора, невидима прибору по построению (урок #1104/#1105).
Поля стадии/взвода (ADR-986) ищутся в цепочке словарём их единственного
владельца (`release_stage_census.STAGE_RECORD_FIELDS`), не копией.

Чего этот модуль НЕ делает
==========================
Не пишет в трейл, не меняет схему событий, не трогает RiskPolicy, kill-switch,
целевую функцию и живой трек. ADVISORY: он НАЗЫВАЕТ, на какие из девяти
вопросов владельца сегодня отвечают данные, а на какие — только память.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
from typing import Any, Callable

from spa_core.utils.observation import observed, observed_number

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/decision_audit_trail.json"

TRAIL_REL = "data/audit_trail.jsonl"
TRADES_REL = "data/trades.json"
EQUITY_REL = "data/equity_curve_daily.json"
APY_HISTORY_REL = "data/apy_history.json"
SHADOW_HISTORY_REL = "data/allocation_rationale_history.jsonl"

_UNCHECKED = "UNCHECKED"

#: «Через месяц» — литерал ВЛАДЕЛЬЦА из §43, а не подобранное нами число.
#: Вердикт от него не зависит (он ничего не переключает); он лишь называет,
#: сколько перекладок уже перешагнули срок, на который владелец рассчитывал.
OWNER_HORIZON_DAYS = 30
OWNER_HORIZON_PROVENANCE = "§43 ТЗ CIO, дословно: «Через месяц должно быть возможно ответить»"

#: Девять полей владельца в порядке ТЗ. Ключ → дословная формулировка.
OWNER_FIELDS: tuple[tuple[str, str], ...] = (
    ("market_snapshot", "market snapshot"),
    ("portfolio_snapshot", "portfolio snapshot"),
    ("policy_version", "policy version"),
    ("configuration_version", "configuration version"),
    ("optimizer_version", "optimizer version"),
    ("decision", "decision"),
    ("calculations", "calculations"),
    ("execution_result", "execution result"),
    ("post_trade_result", "post-trade result"),
)

PRESENT, PARTIAL, ABSENT, UNMEASURED = "present", "partial", "absent", "unmeasured"

# ── §43, первая строка: «Каждое решение должно быть воспроизводимо» (ADR-989) ──
#: Цикл, который пишет трейл, и имена его двери к трейлу. Писатель ЕДИНСТВЕННЫЙ
#: (`spa_core.audit.audit_trail.record_event`); в цикле он импортируется под
#: именем `_audit_record` — оба имени есть одна дверь, а не две.
CYCLE_RUNNER_REL = "spa_core/paper_trading/cycle_runner.py"
TRAIL_WRITER_NAMES: frozenset = frozenset({"record_event", "_audit_record"})
#: Переменная цели в цикле — её переписывают ступени между Step 2 и Step 3.
DECISION_VARIABLE = "target_usd"
#: Ключи, под которыми событие цепочки могло бы нести ПЕРЕПИСАННУЮ цель.
TARGET_KEYS: tuple[str, ...] = ("target_usd", "target", "rewritten_target", "to_allocation")
#: Ключевое слово, под которым запись трима ADR-850 едет к своему носителю.
TRIM_RECORD_KEYWORD = "admissible_trim"
REPRODUCIBILITY_PROVENANCE = ("§43 ТЗ CIO, дословно: «Каждое решение должно быть воспроизводимо»; "
                              "ось ADR-989; контрапункты — ADR-988 § 9 (трим ADR-850 в трейле?) и "
                              "ADR-986 (стадия/взвод в записи?)")
GAP_EPS_USD = 0.01
GAP_CONSISTENT, GAP_EXPLAINED, GAP_UNEXPLAINED, GAP_UNMEASURED = (
    "consistent", "explained", "unexplained", "unmeasured")


def _num_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _books_equal(a: dict, b: dict) -> bool | None:
    """Две книги равны с точностью до цента; нечисло в любой — НЕ ИЗМЕРЕНО (None)."""
    for p in set(a) | set(b):
        x = _num_or_none(a.get(p, 0.0))
        y = _num_or_none(b.get(p, 0.0))
        if x is None or y is None:
            return None
        if abs(x - y) > GAP_EPS_USD:
            return False
    return True


def decision_execution_gap(move: dict, chain: list[dict]) -> dict:
    """Равна ли ИСПОЛНЕННАЯ книга ЗАПИСАННОМУ решению — и если нет, записано ли почему.

    Четыре исхода: ``consistent`` — равны; ``explained`` — не равны, но другое
    событие ТОЙ ЖЕ цепочки несёт книгу, равную исполненной (переписанная цель
    записана); ``unexplained`` — не равны, и переписанной цели не несёт никто;
    ``unmeasured`` — сравнивать нечем (нет предложения / не словари / не числа).
    «Не измерено» не считается ни совпадением, ни расхождением.
    """
    data = move.get("data") or {}
    executed = data.get("to_allocation")
    proposal_ev = next((e for e in chain if e.get("event_type") == "allocation_proposal"), None)
    if proposal_ev is None:
        return {"status": GAP_UNMEASURED,
                "detail": "в цепочке хода нет allocation_proposal — исполненное сравнивать не с чем"}
    decided = (proposal_ev.get("data") or {}).get("target_usd")
    if not isinstance(decided, dict) or not isinstance(executed, dict):
        return {"status": GAP_UNMEASURED,
                "detail": "цель решения или исполненная книга не словарь — сравнение не поставлено"}
    positions: dict[str, dict] = {}
    for p in sorted(set(decided) | set(executed)):
        x = _num_or_none(decided.get(p, 0.0))
        y = _num_or_none(executed.get(p, 0.0))
        if x is None or y is None:
            return {"status": GAP_UNMEASURED,
                    "detail": f"позиция '{p}': значение не число — сравнение не поставлено"}
        if abs(x - y) > GAP_EPS_USD:
            positions[p] = {"decided": round(x, 2), "executed": round(y, 2)}
    if not positions:
        return {"status": GAP_CONSISTENT, "max_diff_usd": 0.0,
                "detail": "исполненная книга равна записанному решению"}
    max_diff = max(abs(v["decided"] - v["executed"]) for v in positions.values())
    for ev in chain:
        if ev is proposal_ev or ev is move:
            continue
        d = ev.get("data")
        if not isinstance(d, dict):
            continue
        for key in TARGET_KEYS:
            cand = d.get(key)
            if isinstance(cand, dict) and _books_equal(cand, executed) is True:
                return {"status": GAP_EXPLAINED, "max_diff_usd": round(max_diff, 2),
                        "positions": positions,
                        "carrier": f"{ev.get('event_type')}.{key}",
                        "detail": (f"исполнено не то, что записано решением, но переписанную "
                                   f"цель несёт событие '{ev.get('event_type')}'.{key}")}
    return {"status": GAP_UNEXPLAINED, "max_diff_usd": round(max_diff, 2), "positions": positions,
            "detail": (f"{len(positions)} позиц. исполнены не так, как записано решением "
                       f"(максимум ${max_diff:,.2f}), и ни одно событие цепочки не несёт "
                       f"переписанной цели")}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def rewrite_steps_between_records(source: str | None, *, rel: str = CYCLE_RUNNER_REL) -> dict:
    """AST цикла: сколько ступеней переписывают цель МЕЖДУ записью решения и записью хода.

    Меряется ТЕКСТ цикла, а не память о нём: ступень, поставленная после
    прибора, невидима прибору по построению. Три исхода (инв. #17): измерено ·
    источник не прочитан/не разбирается · писатель трейла в цикле не найден.
    Ответ: число ступеней (присваиваний `target_usd`) между строкой записи
    `allocation_proposal` и строкой записи `trade_executed`, события трейла
    между ними и сколько из них несут ПОЛЕ ЦЕЛИ, и кому уезжает запись трима
    ADR-850 (`admissible_trim=`) — дверь трейла или другой носитель.
    """
    out: dict[str, Any] = {"measured": False, "source": rel}
    if source is None:
        out["reason"] = f"{rel} не прочитан — о ступенях между решением и ходом судить нечем"
        return out
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        out["reason"] = f"{rel} не разбирается интерпретатором: {exc.msg} (строка {exc.lineno})"
        return out
    records: dict[str, list[dict]] = {}
    trim_carriers: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if any(kw.arg == TRIM_RECORD_KEYWORD for kw in node.keywords):
            trim_carriers.append({"callee": name, "line": node.lineno,
                                  "is_trail_writer": name in TRAIL_WRITER_NAMES})
        if name not in TRAIL_WRITER_NAMES or len(node.args) < 2:
            continue
        ev = node.args[1]
        if not (isinstance(ev, ast.Constant) and isinstance(ev.value, str)):
            continue
        keys: list[str] = []
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Dict):
            keys = [k.value for k in node.args[2].keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        records.setdefault(ev.value, []).append({"line": node.lineno, "data_keys": keys})
    prop, move = records.get("allocation_proposal"), records.get("trade_executed")
    if not prop or not move:
        missing = [n for n, r in (("allocation_proposal", prop), ("trade_executed", move)) if not r]
        out["reason"] = (f"в {rel} не найдена запись события {', '.join(missing)} дверью трейла "
                         f"({'/'.join(sorted(TRAIL_WRITER_NAMES))}) — границы отрезка не названы")
        return out
    lo, hi = min(r["line"] for r in prop), max(r["line"] for r in move)
    rewrites: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        if not (lo < node.lineno < hi):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(n, ast.Name) and n.id == DECISION_VARIABLE
                   for t in targets for n in ast.walk(t)):
            continue
        callee = _call_name(node.value) if isinstance(node.value, ast.Call) else None
        rewrites.append({"line": node.lineno, "callee": callee})
    rewrites.sort(key=lambda r: r["line"])
    between = sorted(({"event_type": ev, **r} for ev, rows in records.items()
                      for r in rows if lo < r["line"] < hi), key=lambda e: e["line"])
    target_bearing = [e for e in between if any(k in TARGET_KEYS for k in e["data_keys"])]
    reaches: bool | None = (any(c["is_trail_writer"] for c in trim_carriers)
                            if trim_carriers else None)
    out.update({
        "measured": True,
        "proposal_record_line": lo,
        "move_record_line": hi,
        "rewrites": len(rewrites),
        "rewrite_steps": rewrites,
        "events_between": between,
        "target_bearing_events_between": len(target_bearing),
        "trim_record_carriers": trim_carriers,
        # True — доходит; False — едет к другому носителю; None — записи трима в цикле нет.
        "trim_record_reaches_trail": reaches,
    })
    return out


def _stage_fields() -> tuple[str, ...] | None:
    """Поля стадии/взвода — у ЕДИНСТВЕННОГО владельца словаря (ADR-986), не копия."""
    try:
        from spa_core.analytics.release_stage_census import STAGE_RECORD_FIELDS
    except Exception:  # noqa: BLE001 — словарь не ввезён ⇒ третий исход
        return None
    return tuple(str(f) for f in STAGE_RECORD_FIELDS)


def stage_in_chain(chain: list[dict], fields: tuple[str, ...] | None) -> bool | None:
    """Несёт ли хоть одно событие цепочки поле стадии/взвода; None — словаря нет."""
    if fields is None:
        return None
    for ev in chain:
        d = ev.get("data")
        if isinstance(d, dict) and any(f in d for f in fields):
            return True
        if any(f in ev for f in fields):
            return True
    return False


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None

#: Критерий §49 приказа «Portfolio CIO», мерой ПОЛОВИНЫ которого модуль себя
#: объявляет. Якорь читается как НАЧАЛО строки (ADR-333): упоминание критерия
#: в середине заметки есть ссылка на него, а не объявление себя его мерой.
#:
#: Половина — потому что критерий владельца назван ДВУМЯ словами: «Каждое
#: решение имеет snapshot и explanation». Снимок меряет этот модуль (§43),
#: объяснение — сосед `cio_explainability` (§44). Сводить их в один прибор
#: было бы ложью о населении: у снимка население — ПЕРЕКЛАДКИ живого трека, у
#: объяснения — РЕКОМЕНДАЦИИ книг, и это разные множества.
CRITERION = (
    "§49 Auditability (половина «snapshot») приказа владельца «Portfolio CIO» — "
    "дословно: «Каждое решение имеет snapshot и explanation». Снимок здесь это "
    "девять полей §43, и мера их — ВОССТАНОВИМОСТЬ по данным, а не наличие файла"
)

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"


def criterion_verdict(doc: dict) -> dict:
    """Вердикт о ПОЛОВИНЕ критерия §49 `Auditability` — по уже снятому отчёту.

    Правило вычисления живёт ЗДЕСЬ, у производителя чисел, и второй его копии
    нет (ADR-220): читатель (`card_acceptance`) вердикт ПЕРЕНОСИТ, а не считает
    заново.

    Своего порога у вердикта нет ни одного. Квантор «КАЖДОЕ решение» — слово
    владельца из §49, а не выбранная нами доля: поэтому `satisfied` требует
    `fully_answerable == moves`, и «почти все» ответом не является.

    **Переносится НЕ `overall`.** `overall` этого модуля есть лестница ТЯЖЕСТИ,
    где `UNCHECKED` стои́т выше `CRITICAL` намеренно — для здоровья артефакта
    это верно, а для вердикта критерия вывернуло бы инвариант #17 наизнанку:
    находка «поле не восстановимо ни по одной перекладке» есть утверждение
    СУЩЕСТВОВАНИЯ, и непрочитанный рядом источник её не отменяет.

    Три исхода разведены (инв. #17):

    * `SATISFIED` — перекладок хотя бы одна, и у КАЖДОЙ отвечают данными все
      девять полей владельца;
    * `NOT_SATISFIED` — есть перекладка, по которой данные не отвечают, и поля
      НАЗВАНЫ;
    * `UNMEASURED` — раздела `population` нет / числа в нём не читаются /
      **перекладок НОЛЬ**. Последнее не «чисто»: «каждая перекладка
      восстановима» при нуле перекладок верно ПО ПОСТРОЕНИЮ и ответом на вопрос
      владельца не является.
    """
    pop = observed(doc, "population", kind=dict)
    if pop is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("в отчёте нет раздела `population` — судить о "
                           "восстановимости нечем, и это НЕ «ноль перекладок»")}
    moves = observed_number(pop, "moves")
    answerable = observed_number(pop, "fully_answerable")
    missing = [name for name, value in (("moves", moves),
                                        ("fully_answerable", answerable))
               if value is None]
    if missing:
        # Почему не прочитались — говорит сам отчёт: «источника нет» и «источник
        # есть, а число не разобрано» чинятся разным (инв. #17). У самой причины
        # тоже ТРИ исхода, и `or []` схлопнул бы два из них в один: «раздела
        # `unchecked` в отчёте нет» и «отчёт назвал непрочитанного ноль» — разные
        # положения дел, и храповик класса поймал здесь ровно это.
        unread = observed(doc, "unchecked", kind=list)
        if unread is None:
            why = "раздела `unchecked` в отчёте нет — причина НЕ ИЗМЕРЕНА"
        elif not unread:
            why = "отчёт не называет непрочитанного ни одной строкой"
        else:
            why = "; ".join(str(item) for item in unread)
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"в `population` не читаются числа {', '.join(missing)} — "
                           f"знаменатель или числитель НЕ ИЗМЕРЕН ({why})")}
    if moves <= 0:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("перекладок в трейле НЕ НАЙДЕНО ни одной — «каждое "
                           "решение восстановимо» при нуле решений верно ПО "
                           "ПОСТРОЕНИЮ и ответом не является")}
    if answerable < moves:
        # Поля перечисляются ЧЕРЕЗ `observed`, а не через `or {}`: «поля в отчёте
        # нет» и «поле есть, и по нему ноль отказов» — РАЗНЫЕ положения дел, и
        # схлопнуть их в пустой словарь значило бы выдать непрочитанное за
        # благополучие (инв. #17; храповик класса поймал здесь ровно это).
        fields = observed(doc, "owner_fields", kind=dict)
        named: list[str] = []
        unread: list[str] = []
        for key, wording in OWNER_FIELDS:
            entry = observed(fields, key, kind=dict) if fields is not None else None
            counts = observed(entry, "counts", kind=dict) if entry is not None else None
            if counts is None:
                unread.append(f"«{wording}»")
                continue
            bad = 0
            for state in (PARTIAL, ABSENT, UNMEASURED):
                seen = observed_number(counts, state)
                if seen is not None:
                    bad += int(seen)
            if bad:
                named.append(f"«{wording}» ({bad})")
        where = []
        if named:
            where.append("; ".join(named))
        if unread:
            where.append("счёт НЕ ПРОЧИТАН у полей: " + "; ".join(unread))
        # ADR-989: перекладка с девятью полями, но исполненная не так, как
        # записано решением, тоже не объяснима — и причина обязана быть НАЗВАНА.
        repro = observed(doc, "reproducibility", kind=dict)
        gap = observed(repro, "decision_execution_gap", kind=dict) if repro is not None else None
        unexplained = observed_number(gap, GAP_UNEXPLAINED) if gap is not None else None
        if unexplained:
            where.append(f"у {unexplained:.0f} исполненная книга отличается от записанного "
                         f"решения без записи причины (ось ADR-989)")
        if not where:
            where.append("перечень полей в отчёте не разобран")
        return {"status": CRITERION_NOT_SATISFIED,
                "reason": (f"по данным восстановимы {answerable:.0f} перекладок из "
                           f"{moves:.0f}: снимка решения у остальных НЕТ. Поля "
                           f"владельца, по которым данные не отвечают: "
                           + " · ".join(where)),
                "answerable": answerable, "moves": moves}
    repro = observed(doc, "reproducibility", kind=dict)
    gap = observed(repro, "decision_execution_gap", kind=dict) if repro is not None else None
    tail = (" и исполненная книга равна записанному решению" if gap is not None
            else "; ось «решение ↔ исполнено» (ADR-989) в этом отчёте не снята")
    return {"status": CRITERION_SATISFIED,
            "reason": (f"у каждой из {moves:.0f} перекладок данные отвечают на все "
                       f"девять полей §43{tail} — снимок решения восстановим"),
            "answerable": answerable, "moves": moves}


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_jsonl(path: str) -> tuple[list[dict], int] | None:
    """Строки JSONL и число НЕразобранных. ``None`` — файла нет / он нечитаем."""
    try:
        raw = open(path, "r", encoding="utf-8").read()
    except OSError:
        return None
    rows: list[dict] = []
    bad = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


def _day(ts: object) -> str | None:
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


# ── Опыт над производителем snapshot_id ───────────────────────────────────────

def probe_snapshot_id(make_id: Callable[[str], str] | None, cycle_date: str) -> dict:
    """Адресует ли ``snapshot_id`` СОДЕРЖИМОЕ снимка — проверяется опытом.

    Два вызова с одним входом. Разные ответы ⇒ идентификатор именует прогон,
    а не рыночный снимок, и восстановить по нему нечего.
    """
    if make_id is None:
        return {"measured": False,
                "reason": "производитель snapshot_id не импортируется — опыт не поставлен"}
    try:
        first, second = make_id(cycle_date), make_id(cycle_date)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"производитель snapshot_id упал: {exc}"}
    return {
        "measured": True,
        "same_input_same_output": first == second,
        "content_addressed": first == second,
        "samples": [first, second],
    }


# ── Разрешение девяти полей по ОДНОЙ перекладке ───────────────────────────────

def _f(status: str, source: str, detail: str = "") -> dict:
    return {"status": status, "source": source, "detail": detail}


def resolve_move(move: dict, chain: list[dict], ctx: dict) -> dict:
    """Девять полей владельца по одной записи ``trade_executed``.

    ``chain`` — все события того же ``correlation_id`` (цикл, породивший ход).
    ``ctx`` — уже прочитанные посторонние источники со своим статусом чтения.
    """
    data = move.get("data") or {}
    date = _day(move.get("timestamp"))
    by_type: dict[str, dict] = {}
    for ev in chain:
        by_type.setdefault(str(ev.get("event_type")), ev)
    proposal = (by_type.get("allocation_proposal") or {}).get("data") or {}
    verdict = (by_type.get("risk_verdict") or {}).get("data") or {}

    out: dict[str, dict] = {}

    # 1. market snapshot — ставки/TVL, которые аллокатор ранжировал в тот день.
    out["market_snapshot"] = _market_snapshot(date, ctx)

    # 2. portfolio snapshot — книга ДО хода.
    before = data.get("from_allocation")
    if isinstance(before, dict) and before:
        extra = ""
        pos = (observed(ctx, "equity_positions", kind=dict) or {}).get(date)
        if isinstance(pos, dict) and pos:
            extra = " (сходится со вторым источником equity_curve_daily.daily[].positions)"
        out["portfolio_snapshot"] = _f(PRESENT, f"{TRAIL_REL}::trade_executed.from_allocation",
                                       f"{len(before)} позиц.{extra}")
    else:
        out["portfolio_snapshot"] = _f(ABSENT, TRAIL_REL,
                                       "у записи хода нет непустой from_allocation")

    # 3. policy version — версия RiskPolicy, которой судили ЭТОТ ход.
    out["policy_version"] = _version_field(
        chain, ("policy_version", "risk_policy_version", "policy"),
        live=ctx.get("live_policy_version"),
        what="версия RiskPolicy",
        carrier="risk_verdict")

    # 4. configuration version — пороги, которыми судили ЭТОТ ход.
    out["configuration_version"] = _version_field(
        chain, ("configuration_version", "config_version", "risk_config_version", "config"),
        live=ctx.get("live_config_version"),
        what="версия конфигурации порогов",
        carrier="risk_verdict")

    # 5. optimizer version — чем считали цель.
    model = proposal.get("model_used")
    if isinstance(model, str) and model:
        out["optimizer_version"] = _f(
            PARTIAL, f"{TRAIL_REL}::allocation_proposal.model_used",
            f"записано ИМЯ модели '{model}', а не её версия: правка оптимизатора "
            f"оставит это поле прежним")
    else:
        out["optimizer_version"] = _f(ABSENT, TRAIL_REL, "model_used не записан")

    # 6. decision — сама цель.
    target = proposal.get("target_usd")
    if isinstance(target, dict) and target:
        out["decision"] = _f(PRESENT, f"{TRAIL_REL}::allocation_proposal.target_usd",
                             f"{len(target)} ключ(ей) цели")
    else:
        out["decision"] = _f(ABSENT, TRAIL_REL,
                             "в цепочке хода нет allocation_proposal с непустой целью")

    # 7. calculations — числа, ИЗ КОТОРЫХ получилась цель.
    out["calculations"] = _calculations(date, verdict, ctx)

    # 8. execution result — что получилось.
    after = data.get("to_allocation")
    if isinstance(after, dict) and after and data.get("diff_usd") is not None:
        out["execution_result"] = _f(PRESENT,
                                     f"{TRAIL_REL}::trade_executed.to_allocation+diff_usd",
                                     f"diff_usd={data.get('diff_usd')}")
    else:
        out["execution_result"] = _f(ABSENT, TRAIL_REL,
                                     "у записи хода нет to_allocation и/или diff_usd")

    # 9. post-trade result — что ход ПРИНЁС.
    out["post_trade_result"] = _post_trade(date, ctx)

    return out


def _market_snapshot(date: str | None, ctx: dict) -> dict:
    """Ставки, по которым ранжировали в ЭТОТ день, — из хранилища, а не из памяти."""
    if date is None:
        return _f(UNMEASURED, TRAIL_REL, "у записи хода нет разбираемой отметки времени")
    hist = ctx.get("apy_history")
    if hist is None:
        return _f(UNMEASURED, APY_HISTORY_REL, "файл истории ставок нечитаем")
    if not isinstance(hist, dict) or not hist:
        snap = ctx.get("snapshot_probe") or {}
        why = "истории ставок по протоколам не ведёт никто (protocol_history пуст)"
        if snap.get("measured") and not snap.get("content_addressed"):
            why += ("; snapshot_id в трейле адресует ПРОГОН, а не содержимое — "
                    "два вызова производителя на одном входе дали разные значения")
        return _f(ABSENT, APY_HISTORY_REL, why)
    rates = {p: v for p, v in hist.items() if _rate_on(v, date) is not None}
    if not rates:
        return _f(ABSENT, APY_HISTORY_REL, f"в истории ставок нет ни одного протокола на {date}")
    return _f(PRESENT, f"{APY_HISTORY_REL}::protocol_history", f"{len(rates)} протокол(ов) на {date}")


def _rate_on(series: object, date: str) -> float | None:
    if isinstance(series, dict):
        v = series.get(date)
        return v if isinstance(v, (int, float)) else None
    if isinstance(series, list):
        for point in series:
            if isinstance(point, dict) and _day(point.get("date") or point.get("ts")) == date:
                v = point.get("apy")
                return v if isinstance(v, (int, float)) else None
    return None


def _version_field(chain: list[dict], keys: tuple[str, ...], *, live: str | None,
                   what: str, carrier: str) -> dict:
    for ev in chain:
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        for k in keys:
            if data.get(k) not in (None, ""):
                return _f(PRESENT, f"{TRAIL_REL}::{ev.get('event_type')}.{k}", str(data[k]))
    detail = f"ни одно событие цикла не несёт {what}; носителем было бы событие '{carrier}'"
    if live:
        detail += (f". Сегодня она существует и равна '{live}' — то есть теряется не "
                   f"значение, а его ЗАПИСЬ рядом с решением")
    return _f(ABSENT, TRAIL_REL, detail)


def _calculations(date: str | None, verdict: dict, ctx: dict) -> dict:
    """Числа решения: не «что решили», а «из чего это следует».

    Строки вердикта гейта — причины ОТКАЗА по ограничениям. Они объясняют, чего
    система НЕ сделала, и не объясняют, почему цель именно такая; поэтому это
    `partial`, а не ответ.
    """
    reasons = list(verdict.get("violations") or []) + list(verdict.get("warnings") or [])
    note = ""
    shadow_day = (ctx.get("shadow_days") or {}).get(date)
    if isinstance(shadow_day, dict) and shadow_day:
        # Накопитель ADR-060 хранит числа ТЕНЕВОГО слоя за тот же день. Это
        # ДРУГОЕ решение (advisory, оно капитал не двигало), поэтому объяснить
        # им ход живого аллокатора нельзя — подставить его вместо ответа значило
        # бы выдать чужой расчёт за расчёт этого хода.
        note = (f"; числа за {date} есть у ТЕНЕВОГО слоя ({SHADOW_HISTORY_REL}), "
                f"но он этот ход не принимал — это расчёт ДРУГОГО решения")
    if reasons:
        return _f(PARTIAL, f"{TRAIL_REL}::risk_verdict",
                  f"записаны {len(reasons)} строк(и) вердикта гейта — это причины ОТКАЗА "
                  f"по ограничениям, а не расчёт, из которого получилась цель{note}")
    return _f(ABSENT, TRAIL_REL,
              f"в цепочке хода нет ни одной величины, из которой следует цель{note}")


def _post_trade(date: str | None, ctx: dict) -> dict:
    """Что ход ПРИНЁС: книга на следующий день есть, вклад самого хода — нет."""
    if date is None:
        return _f(UNMEASURED, TRAIL_REL, "у записи хода нет разбираемой отметки времени")
    days = ctx.get("equity_days")
    if days is None:
        return _f(UNMEASURED, EQUITY_REL, "дневная кривая нечитаема")
    after = sorted(d for d in days if d > date)
    if not after:
        return _f(ABSENT, EQUITY_REL, f"после {date} в дневной кривой нет ни одного дня")
    return _f(PARTIAL, f"{EQUITY_REL}::daily",
              f"есть КНИГА за {after[0]} (equity/apy_today) — уровень портфеля; "
              f"вклада ИМЕННО этого хода не считает никто, и связи хода с исходом нет")


# ── Тождество хода ────────────────────────────────────────────────────────────

def id_collisions(moves: list[dict]) -> dict:
    """Именует ли ``trade_id`` ровно один ход — вопрос, на котором стои́т §43.

    Вопрос владельца поставлен через ход («перекладку $12 000 13 августа»), и
    ответить на него данными можно, только если у хода есть однозначное имя.
    """
    seen: dict[str, list[dict]] = {}
    unnamed = 0
    for m in moves:
        tid = (m.get("data") or {}).get("trade_id")
        if not isinstance(tid, str) or not tid:
            unnamed += 1
            continue
        seen.setdefault(tid, []).append(m)
    reused = {tid: rows for tid, rows in seen.items() if len(rows) > 1}
    worst = None
    if reused:
        tid = sorted(reused, key=lambda t: -len(reused[t]))[0]
        worst = {
            "trade_id": tid,
            "occurrences": [
                {"date": _day(r.get("timestamp")), "diff_usd": (r.get("data") or {}).get("diff_usd")}
                for r in reused[tid]
            ],
        }
    return {
        "moves": len(moves),
        "distinct_ids": len(seen),
        "reused_ids": len(reused),
        "unnamed_moves": unnamed,
        "worst": worst,
    }


# ── Прогон ────────────────────────────────────────────────────────────────────

def run(root: str | None = None, *, now: dt.datetime | None = None,
        read: Callable[[str], Any] = _read_json,
        read_lines: Callable[[str], "tuple[list[dict], int] | None"] = _read_jsonl,
        read_text: Callable[[str], "str | None"] = _read_text,
        stage_fields: "tuple[str, ...] | None | Callable[[], tuple[str, ...] | None]" = _stage_fields,
        write: bool = True) -> dict:
    """Собрать отчёт. ``now`` инъектируется — иных обращений к часам здесь нет.

    ``read_text`` — дверь к тексту цикла (ось ADR-989 меряет его AST);
    ``stage_fields`` — словарь полей стадии (по умолчанию у владельца словаря).
    """
    root = root or REPO_ROOT
    now = now or dt.datetime.now(dt.timezone.utc)
    fields_of_stage = stage_fields() if callable(stage_fields) else stage_fields

    trail = read_lines(os.path.join(root, TRAIL_REL))
    if trail is None:
        return _report(root, now, overall=_UNCHECKED, fields={}, findings=[],
                       unchecked=[f"{TRAIL_REL} нечитаем — судить о восстановимости нечем"],
                       population={}, identity={}, snapshot={}, moves=[], write=write)
    rows, bad_lines = trail
    moves = [r for r in rows if r.get("event_type") == "trade_executed"]
    if not moves:
        return _report(root, now, overall=_UNCHECKED, fields={}, findings=[],
                       unchecked=["в трейле нет ни одной перекладки — восстанавливать нечего"],
                       population={"trail_events": len(rows), "unparseable_lines": bad_lines},
                       identity={}, snapshot={}, moves=[], write=write,
                       reproducibility={"provenance": REPRODUCIBILITY_PROVENANCE,
                                        "decision_execution_gap": None,
                                        "rewrite_steps": rewrite_steps_between_records(
                                            read_text(os.path.join(root, CYCLE_RUNNER_REL))),
                                        "stage_in_trail": None})

    chains: dict[str, list[dict]] = {}
    for r in rows:
        chains.setdefault(str(r.get("correlation_id")), []).append(r)

    ctx = _context(root, read, read_lines, sample_date=_day(moves[-1].get("timestamp")) or "1970-01-01")

    resolved = []
    stage_carried = 0
    for m in moves:
        chain = chains.get(str(m.get("correlation_id")), [m])
        fields = resolve_move(m, chain, ctx)
        age = _age_days(_day(m.get("timestamp")), now)
        gap = decision_execution_gap(m, chain)
        stage = stage_in_chain(chain, fields_of_stage)
        if stage:
            stage_carried += 1
        resolved.append({
            "trade_id": (m.get("data") or {}).get("trade_id"),
            "date": _day(m.get("timestamp")),
            "diff_usd": (m.get("data") or {}).get("diff_usd"),
            "age_days": age,
            "fields": fields,
            "gap": gap,
            "stage_carried": stage,
            # ADR-989: девять полей отвечают И исполнено то, что записано (или
            # причина расхождения записана). «Не измерено» у зазора полной
            # объяснимости не даёт — fail-CLOSED.
            "fully_answerable": (all(f["status"] == PRESENT for f in fields.values())
                                 and gap["status"] in (GAP_CONSISTENT, GAP_EXPLAINED)),
        })

    per_field = {}
    for key, wording in OWNER_FIELDS:
        counts = {PRESENT: 0, PARTIAL: 0, ABSENT: 0, UNMEASURED: 0}
        detail = ""
        source = ""
        for r in resolved:
            f = r["fields"][key]
            counts[f["status"]] += 1
            if not detail or f["status"] in (ABSENT, UNMEASURED):
                detail, source = f["detail"], f["source"]
        per_field[key] = {"owner_wording": wording, "counts": counts,
                          "source": source, "detail": detail}

    gap_counts = {s: 0 for s in (GAP_CONSISTENT, GAP_EXPLAINED, GAP_UNEXPLAINED, GAP_UNMEASURED)}
    worst_gap: dict | None = None
    for r in resolved:
        g = r["gap"]
        gap_counts[g["status"]] += 1
        # Худшее расхождение — только среди ИЗМЕРЕННЫХ величин: зазор без числа
        # (`None`) не «нулевой», он не участвует в выборе (инв. #17).
        cur = observed_number(g, "max_diff_usd")
        best = observed_number(worst_gap, "max_diff_usd") if worst_gap is not None else None
        if g["status"] == GAP_UNEXPLAINED and cur is not None and (best is None or cur > best):
            worst_gap = {"trade_id": r["trade_id"], "date": r["date"],
                         "max_diff_usd": cur, "positions": g.get("positions")}
    reproducibility = {
        "provenance": REPRODUCIBILITY_PROVENANCE,
        "decision_execution_gap": {"moves": len(resolved), **gap_counts, "worst": worst_gap},
        "rewrite_steps": rewrite_steps_between_records(
            read_text(os.path.join(root, CYCLE_RUNNER_REL))),
        "stage_in_trail": {"measured": fields_of_stage is not None,
                           "fields": list(fields_of_stage) if fields_of_stage is not None else None,
                           "moves": len(resolved),
                           "carrying": stage_carried if fields_of_stage is not None else None},
    }

    identity = id_collisions(moves)
    # Запись без возраста в «старые» не попадает — но это НЕ «ей ноль дней»:
    # ноль здесь только сравнение, а отсутствие названо соседним счётчиком.
    older = [r for r in resolved
             if (observed_number(r, "age_days") or 0) >= OWNER_HORIZON_DAYS]
    population = {
        "trail_events": len(rows),
        "unparseable_lines": bad_lines,
        "moves": len(resolved),
        "moves_older_than_owner_horizon": len(older),
        "owner_horizon_days": OWNER_HORIZON_DAYS,
        "owner_horizon_provenance": OWNER_HORIZON_PROVENANCE,
        "fully_answerable": sum(1 for r in resolved if r["fully_answerable"]),
        "gap_unexplained": gap_counts[GAP_UNEXPLAINED],
        "oldest_move_date": min((r["date"] for r in resolved if r["date"]), default=None),
        "newest_move_date": max((r["date"] for r in resolved if r["date"]), default=None),
    }

    findings, unchecked = _judge(per_field, identity, population, ctx, reproducibility)

    if all(c[UNMEASURED] == len(resolved) for c in (v["counts"] for v in per_field.values())):
        overall = _UNCHECKED
    elif any(f["severity"] == "CRITICAL" for f in findings):
        overall = "CRITICAL"
    elif any(f["severity"] == "WARN" for f in findings):
        overall = "WARN"
    else:
        overall = "OK"

    return _report(root, now, overall=overall, fields=per_field, findings=findings,
                   unchecked=unchecked, population=population, identity=identity,
                   snapshot=ctx.get("snapshot_probe") or {}, moves=resolved, write=write,
                   reproducibility=reproducibility)


def _age_days(date: str | None, now: dt.datetime) -> float | None:
    if date is None:
        return None
    try:
        d = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return round((now - d).total_seconds() / 86400.0, 2)


def _context(root: str, read: Callable[[str], Any],
             read_lines: Callable[[str], "tuple[list[dict], int] | None"],
             *, sample_date: str) -> dict:
    ctx: dict = {}

    hist = read(os.path.join(root, APY_HISTORY_REL))
    ctx["apy_history"] = (hist or {}).get("protocol_history") if isinstance(hist, dict) else None

    eq = read(os.path.join(root, EQUITY_REL))
    daily = (eq or {}).get("daily") if isinstance(eq, dict) else None
    if isinstance(daily, list):
        ctx["equity_days"] = {d.get("date") for d in daily if isinstance(d, dict)}
        ctx["equity_positions"] = {d.get("date"): d.get("positions")
                                   for d in daily if isinstance(d, dict)}
    else:
        ctx["equity_days"] = None
        ctx["equity_positions"] = {}

    sh = read_lines(os.path.join(root, SHADOW_HISTORY_REL))
    ctx["shadow_days"] = ({r.get("cycle_date"): r for r in sh[0]} if sh else {})

    # Версии, которые СУЩЕСТВУЮТ сегодня, — чтобы отличить «версии нет» от
    # «версия есть, но её не записывают рядом с решением».
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        ctx["live_policy_version"] = str(getattr(cfg, "version", "") or "")
        ctx["live_config_version"] = str(getattr(cfg, "version_date", "") or "")
    except Exception:  # noqa: BLE001
        ctx["live_policy_version"] = None
        ctx["live_config_version"] = None

    make_id = None
    try:
        from spa_core.audit import audit_trail as _at
        make_id = _at._make_snapshot_id
    except Exception:  # noqa: BLE001
        make_id = None
    ctx["snapshot_probe"] = probe_snapshot_id(make_id, sample_date)
    return ctx


def _judge(per_field: dict, identity: dict, population: dict, ctx: dict,
           reproducibility: dict | None = None) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []
    n = population.get("moves") or 0

    for key, v in per_field.items():
        c = v["counts"]
        if not n or c[PRESENT]:
            continue
        if c[ABSENT]:
            # Ни одна перекладка не отдаёт поле целиком, и хотя бы одна не
            # отдаёт вовсе. Для §43 это и есть «не воспроизводимо данными».
            where = (f"НИ ПО ОДНОЙ из {n}" if c[ABSENT] == n
                     else f"ни по одной из {n} (нет вовсе — {c[ABSENT]}, "
                          f"частично — {c[PARTIAL]})")
            findings.append({
                "severity": "CRITICAL",
                "code": f"field_never_recoverable:{key}",
                "message": (f"поле владельца «{v['owner_wording']}» не восстановимо "
                            f"{where} перекладок живого трека: {v['detail']}"),
            })
        else:
            findings.append({
                "severity": "WARN",
                "code": f"field_partial:{key}",
                "message": (f"поле владельца «{v['owner_wording']}» восстановимо ЧАСТИЧНО "
                            f"на всех {n} перекладках: {v['detail']}"),
            })
    recoverable = [v["owner_wording"] for v in per_field.values()
                   if n and v["counts"][PRESENT] == n]
    if recoverable:
        findings.append({
            "severity": "INFO",
            "code": "fields_recoverable",
            "message": (f"отвечают данными на всех {n} перекладках {len(recoverable)} из "
                        f"{len(per_field)} полей: " + ", ".join(f"«{w}»" for w in recoverable)),
        })
    for key, v in per_field.items():
        if v["counts"][UNMEASURED]:
            unchecked.append(f"«{v['owner_wording']}»: {v['counts'][UNMEASURED]} из {n} — "
                             f"{v['detail']}")

    if identity.get("reused_ids"):
        w = identity.get("worst") or {}
        occ = "; ".join(f"{o['date']} на ${o['diff_usd']:,.2f}" for o in w.get("occurrences", [])
                        if o.get("diff_usd") is not None)
        findings.append({
            "severity": "CRITICAL",
            "code": "trade_id_not_unique",
            "message": (f"имя хода НЕ однозначно: {identity['reused_ids']} из "
                        f"{identity['distinct_ids']} значений trade_id названы больше одного "
                        f"раза — {w.get('trade_id')} это {occ}. Вопрос владельца поставлен "
                        f"ЧЕРЕЗ ход («перекладка 13 августа»), и такой join отвечает двумя "
                        f"разными ходами сразу"),
        })
    if identity.get("unnamed_moves"):
        findings.append({
            "severity": "WARN",
            "code": "unnamed_moves",
            "message": f"{identity['unnamed_moves']} перекладок записаны без trade_id",
        })

    snap = ctx.get("snapshot_probe") or {}
    if snap.get("measured") and not snap.get("content_addressed"):
        findings.append({
            "severity": "INFO",
            "code": "snapshot_id_is_a_run_id",
            "message": ("опыт над производителем: два вызова _make_snapshot_id на ОДНОМ "
                        "входе дали разные значения — поле snapshot_id именует ПРОГОН, "
                        "а не содержимое рыночного снимка, и восстановить по нему нечего"),
        })
    elif not snap.get("measured"):
        unchecked.append(f"snapshot_id: {snap.get('reason', 'опыт не поставлен')}")

    _judge_reproducibility(findings, unchecked, n, reproducibility or {})

    if n and not population.get("fully_answerable"):
        findings.append({
            "severity": "CRITICAL",
            "code": "no_move_is_fully_answerable",
            "message": (f"ни одна из {n} перекладок не объяснима данными полностью: "
                        f"{population.get('moves_older_than_owner_horizon')} из них уже "
                        f"старше месяца, на который рассчитывал §43"),
        })
    if population.get("unparseable_lines"):
        unchecked.append(f"{population['unparseable_lines']} строк(и) трейла не разобраны")
    return findings, unchecked


def _judge_reproducibility(findings: list[dict], unchecked: list[str], n: int,
                           repro: dict) -> None:
    """Находки оси ADR-989 — «решение ↔ исполнено», ступени между записями, стадия."""
    gap = observed(repro, "decision_execution_gap", kind=dict)
    if n and gap is not None:
        u = observed_number(gap, GAP_UNEXPLAINED)
        u = int(u) if u is not None else None
        if u:
            w = observed(gap, "worst", kind=dict)
            where = ""
            if w is not None and (w.get("date") or w.get("trade_id")):
                diff = observed_number(w, "max_diff_usd")
                diff_txt = f"${diff:,.2f}" if diff is not None else "НЕ ИЗМЕРЕНО"
                where = (f" — худшая: {w.get('date')} {w.get('trade_id')}, расхождение "
                         f"{diff_txt}")
            findings.append({
                "severity": "CRITICAL",
                "code": "decision_differs_from_execution_unexplained",
                "message": (f"у {u} из {n} перекладок исполненная книга отличается от "
                            f"записанного решения (allocation_proposal.target_usd), и ни одно "
                            f"событие цепочки не несёт переписанную цель{where}. На вопрос "
                            f"«почему переместили» такой трейл отвечает решением, которого "
                            f"цикл не исполнил"),
            })
        if observed_number(gap, GAP_CONSISTENT) == n and n:
            findings.append({
                "severity": "INFO",
                "code": "decision_matches_execution",
                "message": f"у всех {n} перекладок исполненная книга равна записанному решению",
            })
        unmeasured = observed_number(gap, GAP_UNMEASURED)
        if unmeasured:
            unchecked.append(f"решение ↔ исполнено: у {unmeasured:.0f} из {n} перекладок "
                             f"сравнение не поставлено (нет предложения или не числа)")

    steps = observed(repro, "rewrite_steps", kind=dict)
    if steps is not None and not steps.get("measured"):
        unchecked.append(f"ступени между записью решения и записью хода: {steps.get('reason')}")
    elif steps is not None:
        rewrites = observed_number(steps, "rewrites")
        bearing = observed_number(steps, "target_bearing_events_between")
        if rewrites is None or bearing is None:
            unchecked.append("ступени между записью решения и записью хода: счёт в разделе "
                             "`rewrite_steps` не прочитан")
            rewrites, bearing = 0, 0
        rewrites, bearing = int(rewrites), int(bearing)
        callees = ", ".join(str(r.get("callee") or f"строка {r.get('line')}")
                            for r in (steps.get("rewrite_steps") or []))
        between = steps.get("events_between") or []
        types = ", ".join(sorted({e["event_type"] for e in between})) or "ни одного"
        reaches = steps.get("trim_record_reaches_trail")
        if reaches is False:
            carriers = ", ".join(sorted({str(c.get("callee")) for c in
                                         (steps.get("trim_record_carriers") or [])}))
            trim_note = (f"; запись трима ADR-850 (`{TRIM_RECORD_KEYWORD}=`) едет к "
                         f"{carriers}, а не в трейл")
        elif reaches is None:
            trim_note = f"; записи трима ADR-850 (`{TRIM_RECORD_KEYWORD}=`) в цикле не найдено"
        else:
            trim_note = "; запись трима ADR-850 доходит до двери трейла"
        if rewrites and not bearing:
            findings.append({
                "severity": "CRITICAL",
                "code": "rewrite_steps_invisible_to_trail",
                "message": (f"между записью решения (строка {steps.get('proposal_record_line')}) "
                            f"и записью хода (строка {steps.get('move_record_line')}) цель "
                            f"переписывают {rewrites} ступеней ({callees}); событий трейла между "
                            f"ними {len(between)} ({types}), с полем цели — 0: ни одна ступень "
                            f"не записывает, ЧТО она сделала с целью{trim_note}"),
            })
        elif rewrites:
            findings.append({
                "severity": "INFO",
                "code": "rewrite_steps_carried_by_trail",
                "message": (f"между записью решения и записью хода {rewrites} ступеней "
                            f"переписывают цель, и {bearing} событий трейла несут поле цели"
                            f"{trim_note}"),
            })

    stage = observed(repro, "stage_in_trail", kind=dict)
    if stage is not None and not stage.get("measured"):
        unchecked.append("стадия/взвод в записи решения: словарь полей "
                         "(release_stage_census.STAGE_RECORD_FIELDS) не ввезён")
    elif stage is not None and n:
        carrying = observed_number(stage, "carrying")
        carrying = int(carrying) if carrying is not None else None
        fields = ", ".join(stage.get("fields") or [])
        if carrying is None:
            unchecked.append("стадия/взвод в записи решения: счёт несущих цепочек не прочитан")
        elif carrying == 0:
            findings.append({
                "severity": "WARN",
                "code": "stage_not_in_trail",
                "message": (f"ни одна из {n} цепочек не несёт поля стадии/взвода ({fields}) — "
                            f"решающий вердикт взведённой книги в трейле неотличим от "
                            f"советующего (ADR-986)"),
            })
        elif carrying < n:
            findings.append({
                "severity": "WARN",
                "code": "stage_partly_in_trail",
                "message": f"поле стадии/взвода несут {carrying} из {n} цепочек ({fields})",
            })
        else:
            findings.append({
                "severity": "INFO",
                "code": "stage_in_trail",
                "message": f"все {n} цепочек несут поле стадии/взвода ({fields})",
            })


def _report(root: str, now: dt.datetime, *, overall: str, fields: dict,
            findings: list[dict], unchecked: list[str], population: dict,
            identity: dict, snapshot: dict, moves: list[dict], write: bool,
            reproducibility: dict | None = None) -> dict:
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": {
            "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
            "warn": sum(1 for f in findings if f["severity"] == "WARN"),
            "info": sum(1 for f in findings if f["severity"] == "INFO"),
            "unchecked": len(unchecked),
        },
        "population": population,
        "owner_fields": fields,
        "identity": identity,
        "snapshot_id_probe": snapshot,
        "reproducibility": reproducibility or {"provenance": REPRODUCIBILITY_PROVENANCE},
        "moves": moves[-10:],
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: схема трейла, RiskPolicy, kill-switch и живой трек НЕ "
                     "трогаются — дописать поле в запись решения значит изменить путь, "
                     "по которому двигается капитал, это решение владельца"),
    }
    # Вердикт о критерии владельца кладётся в САМ отчёт: иначе читателю пришлось
    # бы вывести его из чисел, то есть завести ВТОРУЮ копию правила (ADR-220).
    doc["criterion"] = criterion_verdict(doc)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    c = doc["counts"]
    print(f"decision_audit_trail: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    gap = (doc.get("reproducibility") or {}).get("decision_execution_gap") or {}
    if gap:
        print(f"  решение ↔ исполнено: совпали {gap.get(GAP_CONSISTENT)} · объяснены "
              f"{gap.get(GAP_EXPLAINED)} · расходятся без причины {gap.get(GAP_UNEXPLAINED)} · "
              f"не измерено {gap.get(GAP_UNMEASURED)} из {gap.get('moves')}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
