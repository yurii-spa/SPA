#!/usr/bin/env python3
"""Пересчитывается ли ход НЕПОСРЕДСТВЕННО перед исполнением.

Критерий §49 `Pre-trade safety` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #708.

Дословно критерий звучит так: **«Каждый trade пересчитывается непосредственно
перед execution»**. Тело ТЗ ставит тот же вопрос трижды и подробнее:

* **§27 «Pre-trade check»**: «Между recommendation и execution обязательно
  выполнить повторную проверку» — и перечисляет ДЕВЯТЬ предметов: свежие APY,
  gas, liquidity, slippage, симуляции вывода и вклада, влияние позиции, policy,
  ожидаемая экономика. «Если opportunity исчезла: CANCEL / DEFER, **а не
  исполнять устаревшее решение**».
* **§28 «Decision expiry»**: у каждого решения обязан быть TTL (`valid_until`);
  не исполнено до TTL ⇒ «решение нельзя выполнять без нового расчёта».
* **§-тест 11 «APY disappears before execution»**: рекомендация создана, до
  исполнения ставка падает, ожидается — «pre-trade validation отменяет
  execution».

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь, и меряет её ИСХОДОМ: **было ли у исполненного хода ВТОРОЕ наблюдение
входов**. Повторная проверка по §27 имеет ровно один машинный признак — входы
обязаны быть УВИДЕНЫ ЗАНОВО между предложением и исполнением. Если исполнение
стои́т на том же наблюдении, что и предложение, то проверять было нечем: второго
взгляда на мир не случилось, и «opportunity исчезла» заметить физически нечему.

Материал — цепочка аудита `data/audit_trail.jsonl`, единственная запись, которая
связывает предложение с исполнением: у каждого события есть `prev_event_id`, и
цепочка восстанавливается назад от `trade_executed` до `allocation_proposal`.
У каждого события есть `snapshot_id` — детерминированный ярлык наблюдения
(`<cycle_date>:<sha256…>`, `spa_core/audit/audit_trail.py::_make_snapshot_id`).

По каждому исполнению прибор печатает четыре величины:

* ``second_observation`` — отличается ли `snapshot_id` исполнения от
  `snapshot_id` предложения. Совпал ⇒ входы заново НЕ наблюдались;
* ``recheck_events`` — есть ли в цепочке между вердиктом и исполнением ХОТЬ
  ОДНО событие повторной проверки;
* ``window_s`` — сколько секунд прошло между предложением и исполнением, то
  есть каков размер окна, в котором вход успел бы сдвинуться;
* ``ttl_declared`` — несёт ли решение срок годности (§28).

Почему мерить надо ИСХОД, а не наличие модуля
------------------------------------------------------------------------------
Модуль повторной проверки СУЩЕСТВУЕТ и тесты у него зелёные:
`spa_core/execution/safety_checks.py::PreExecutionSafety` — шесть проверок
(`check_risk_policy`, `check_gas_reasonable`, `check_simulation_passes`,
`check_amount_requires_multisig`, `check_not_in_kill_switch`,
`check_rate_limit`). Именно поэтому критерий и нельзя закрывать по наличию
модуля: у него НЕТ ни одного читателя на пути, которым двигается книга, и быть
не может — инвариант #6 прямо запрещает бумажному коду импортировать
`spa_core/execution/`. Его зовут только инертные инструменты готовности
(`golive_dry_run`, `readiness_audit`, `gate_chain_audit`) и тесты.

Это не дефект инварианта #6 и не предложение его ослабить. Это замер того, что
между «повторная проверка написана» и «ход перепроверяется» стои́т ненаписанная
ступень, и ни один сторож об этом не говорил: ось читателей прибор меряет сам
(`gate_reader_axis`) и НАЗЫВАЕТ каждого зовущего по имени вместо вывода «модуль
есть».

Порога свежести у владельца НЕТ — и подставлять свой запрещено
------------------------------------------------------------------------------
§22 ТЗ требует: «Все значения должны быть config/policy. **Не hardcode**».
Вопрос «вход был СЛИШКОМ стар» требует допуска, а допуск — решение владельца.
Замер 27.09: в колонке владельца (`TriggerParams`, ADR-060 §3, версия v1.1,
14 ручек) НЕТ ни ручки про свежесть входа на момент исполнения, ни срока
годности решения; слов `valid_until` / TTL решения нет ни в ОДНОМ файле
репозитория. Поэтому прибор:

* НЕ выдумывает допуск и НЕ берёт чужой (TTL советательной аналитики, окно
  протухания замка цикла и прочее — ответы на другие вопросы);
* объявляет вопрос о чрезмерной старости **третьим исходом**
  (``freshness_judgeable=False``, причина названа), а не «чисто»;
* печатает ВЕСЬ список ручек владельца рядом с находкой — чтобы отсутствие
  нужной было видно, а не утверждалось.

Допуск можно ПЕРЕДАТЬ (`tolerance_s=`): объявит владелец — прибор начнёт судить
чрезмерную старость, и `CRITICAL` станет достижимым без единой правки.

Что прибор НЕ докладывает
------------------------------------------------------------------------------
* **Верность самих проверок.** Что `PreExecutionSafety` проверяет правильно —
  вопрос не этого прибора;
* **восемь из девяти предметов §27 по отдельности.** Прибор меряет ПРИЗНАК
  повторной проверки (второе наблюдение), а не покрытие каждого предмета:
  свежие liquidity/slippage/влияние позиции у бумажной книги не наблюдаются
  вовсе, и делить ноль по девяти графам значило бы выдать разбор за замер;
* **вред в долларах.** Окно сегодня измерено и мало (см. `window_s`); прибор
  печатает его, а не переводит в деньги, которых не терял.

Побочная ось: ярлык исполнения НЕ уникален (называется, не смешивается)
------------------------------------------------------------------------------
Замер 27.09 по живой цепочке: 46 записанных исполнений несут 32 РАЗНЫХ
`trade_id`, и у 12 ярлыков payload РАЗНЫЙ — один ярлык называет разные денежные
события (`T007` — $58,999.99 от 14.06, $29,620.34 от 15.06 и $28,500.06 от
20.06; `T014` — $30,714.90 в июне и $80,000.00 от 27.08). Для ЭТОГО прибора
следствие ровно одно, и оно методическое: население считается по `event_id`
цепочки, а НЕ по `trade_id`, иначе 14 исполнений молча слились бы в 12.
Родство с классом «дыра в записи» (ADR-350) НАЗВАНО, но не объявлено тем же
дефектом: там расходились суммы книги, здесь — уникальность ярлыка.

ADVISORY: прибор только ЧИТАЕТ. Ни строки RiskPolicy, стоп-крана, аллокатора,
`TriggerParams`, живого трека или `landing/` он не трогает и ничего не чинит.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.observation import observed

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "pre_trade_recheck_census.json"

#: Цепочка аудита — единственная запись, связывающая предложение с исполнением.
CHAIN_FILENAME = "audit_trail.jsonl"

#: Предмет прибора. Один текст на обе ветки, чтобы измеренный и неизмеренный
#: артефакты называли ОДНО И ТО ЖЕ, а не две редакции одной фразы.
CRITERION = ("§49 Pre-trade safety — «Каждый trade пересчитывается "
             "непосредственно перед execution» (+ §27 повторная проверка, "
             "§28 срок годности решения, §-тест 11 отмена при исчезновении)")

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код возврата третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3

#: Событие исполнения и событие предложения в словаре цепочки.
EVENT_EXECUTED = "trade_executed"
EVENT_PROPOSAL = "allocation_proposal"
EVENT_VERDICT = "risk_verdict"

#: События, которые считались бы ПОВТОРНОЙ ПРОВЕРКОЙ, если бы существовали.
#: Перечень намеренно широк: прибор ищет признак второго взгляда на мир любым
#: именем, чтобы «у нас это называется иначе» не читалось как находка.
RECHECK_EVENT_TYPES = (
    "pre_trade_check", "pre_trade_recheck", "pretrade_check",
    "pre_execution_safety", "pre_execution_check", "safety_pipeline",
    "input_refresh", "snapshot_refresh", "decision_revalidated",
)

#: Имена ручек, которые БЫЛИ БЫ допуском свежести или сроком годности решения.
#: Прибор ищет их в колонке владельца ЗАМЕРОМ, а не утверждает отсутствие.
_TOLERANCE_HINTS = ("ttl", "valid", "expir", "fresh", "stale", "input_age",
                    "decision_age", "max_age")

#: Модуль повторной проверки и его инертные читатели. Инертность — свойство
#: ЗОВУЩЕГО, поэтому она объявлена списком и печатается, а не подразумевается.
GATE_MODULE = "spa_core/execution/safety_checks.py"
#: Имя модуля повторной проверки как его видит ИМПОРТ. Разбор идёт по AST, а не
#: подстрокой: подстрока «execution.safety_checks» (а) не ловит господствующую
#: форму `from spa_core.execution import safety_checks` и (б) нашла бы саму эту
#: строку в ЭТОМ файле, объявив прибор читателем гейта на денежном пути. Оба
#: дефекта были у первой редакции и оба нашлись прогоном (запрет «проходить
#: подстрокой» — `.claude/rules/acceptance.md` п. 3, ADR-333).
GATE_MODULE_DOTTED = "spa_core.execution.safety_checks"
GATE_INERT_CALLERS = (
    "spa_core/execution/golive_dry_run.py",
    "spa_core/execution/readiness_audit.py",
    "spa_core/execution/gate_chain_audit.py",
)


# ── чтение ──────────────────────────────────────────────────────────────────

def _parse_ts(raw: object) -> Optional[datetime]:
    """Отметка времени либо ``None``. Непарсимое — отсутствие наблюдения."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_chain(path: Path) -> Dict[str, Any]:
    """Прочитать цепочку аудита. Нечитаемость — названная причина, не пустота."""
    if not path.exists():
        return {"ok": False, "reason": f"цепочки аудита нет на диске: {path}",
                "rows": [], "unparsable_lines": 0}
    rows: List[dict] = []
    unparsable = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    unparsable += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    unparsable += 1
    except OSError as exc:
        return {"ok": False, "reason": f"цепочка аудита не прочитана: {exc}",
                "rows": [], "unparsable_lines": 0}
    return {"ok": True, "reason": None, "rows": rows,
            "unparsable_lines": unparsable}


def load_owner_tolerance(params: Any = None) -> Dict[str, Any]:
    """Колонка владельца: есть ли ручка про свежесть входа / срок годности.

    Отсутствие ручки — НЕ ноль и не «допуск равен нулю». Это третий исход
    вопроса «был ли вход слишком стар», и он обязан быть виден читателю вместе
    со ВСЕМ списком ручек: утверждать отсутствие дешевле, чем его показать.
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — колонка недоступна: третий исход
            return {"measured": False,
                    "reason": f"колонка владельца не прочитана: "
                              f"{type(exc).__name__}: {exc}",
                    "dials": None, "tolerance_dial": None, "tolerance_s": None,
                    "ttl_dial": None, "version": None, "mode": None}
    dials: Dict[str, Any] = {}
    for name in dir(params):
        if name.startswith("_"):
            continue
        value = getattr(params, name, None)
        if isinstance(value, bool) or isinstance(value, (int, float, str)):
            dials[name] = value
    hits = [name for name in sorted(dials)
            if any(hint in name.lower() for hint in _TOLERANCE_HINTS)
            and name not in ("version", "version_date", "mode")]
    return {"measured": True, "reason": None, "dials": dials,
            "tolerance_dial": (hits[0] if hits else None),
            "tolerance_s": None,
            "ttl_dial": (hits[0] if hits else None),
            "version": dials.get("version"), "mode": dials.get("mode")}


# ── разбор одного исполнения ────────────────────────────────────────────────

def score_execution(event: dict, by_id: Dict[str, dict],
                    tolerance_s: Optional[float] = None) -> Dict[str, Any]:
    """Было ли у ЭТОГО исполнения второе наблюдение входов.

    Непрослеживаемая цепочка — третий исход с названной причиной, а не
    «проверки не было»: отсутствие записи и отсутствие проверки различимы.
    """
    out: Dict[str, Any] = {
        "event_id": event.get("event_id"),
        "correlation_id": event.get("correlation_id"),
        "trade_id": (event.get("data") or {}).get("trade_id")
        if isinstance(event.get("data"), dict) else None,
        "ts": event.get("timestamp"),
        "snapshot_id": event.get("snapshot_id"),
    }
    chain: List[dict] = []
    cursor: Optional[dict] = event
    seen: set = set()
    while isinstance(cursor, dict):
        chain.append(cursor)
        prev = cursor.get("prev_event_id")
        if not prev or prev in seen:
            break
        seen.add(prev)
        cursor = by_id.get(prev)
    out["chain"] = [c.get("event_type") for c in reversed(chain)]
    proposal = next((c for c in chain
                     if c.get("event_type") == EVENT_PROPOSAL), None)
    if proposal is None:
        out.update(kind="unmeasured",
                   reason="цепочка не доходит до `allocation_proposal` — "
                          "предложение, которым ход авторизован, не найдено",
                   second_observation=None, window_s=None,
                   recheck_events=None, ttl_declared=None)
        return out
    exec_ts = _parse_ts(event.get("timestamp"))
    prop_ts = _parse_ts(proposal.get("timestamp"))
    out["proposal_snapshot_id"] = proposal.get("snapshot_id")
    out["proposal_ts"] = proposal.get("timestamp")
    if exec_ts is None or prop_ts is None:
        out.update(kind="unmeasured",
                   reason="отметка времени предложения или исполнения не "
                          "разобрана — окно не измерено",
                   second_observation=None, window_s=None,
                   recheck_events=None, ttl_declared=None)
        return out
    window_s = (exec_ts - prop_ts).total_seconds()
    #: Второе наблюдение = ярлык наблюдения ИЗМЕНИЛСЯ. Оба ярлыка обязаны быть
    #: наблюдены: отсутствие ярлыка не есть «совпал».
    exec_snap = event.get("snapshot_id")
    prop_snap = proposal.get("snapshot_id")
    if not isinstance(exec_snap, str) or not isinstance(prop_snap, str) \
            or not exec_snap or not prop_snap:
        second = None
    else:
        second = exec_snap != prop_snap
    #: Повторная проверка в цепочке — любое событие из широкого перечня,
    #: стоящее ПОСЛЕ предложения.
    after_proposal = list(reversed(chain))
    idx = next((i for i, c in enumerate(after_proposal)
                if c.get("event_type") == EVENT_PROPOSAL), None)
    tail = after_proposal[idx + 1:] if idx is not None else []
    rechecks = [c.get("event_type") for c in tail
                if c.get("event_type") in RECHECK_EVENT_TYPES]
    #: §28 — срок годности решения. Ищется у предложения и у исполнения.
    ttl_declared = any(
        isinstance(src, dict) and any(
            key for key in src
            if any(hint in str(key).lower()
                   for hint in ("valid_until", "expires", "ttl")))
        for src in (proposal.get("data"), event.get("data"), proposal, event))
    out.update(second_observation=second, window_s=round(window_s, 3),
               recheck_events=rechecks, ttl_declared=bool(ttl_declared))
    if tolerance_s is not None and window_s > float(tolerance_s) \
            and not rechecks and second is not True:
        out.update(kind="stale_beyond_tolerance",
                   reason=f"окно {window_s:.3f}с превысило объявленный владельцем "
                          f"допуск {float(tolerance_s):.3f}с, а входы заново не "
                          f"наблюдались и повторной проверки в цепочке нет")
        return out
    if rechecks or second is True:
        out.update(kind="recheck_present", reason=None)
        return out
    out.update(kind="no_recheck",
               reason="исполнение стои́т на ТОМ ЖЕ наблюдении, что и "
                      "предложение, и события повторной проверки в цепочке нет "
                      "— второго взгляда на входы не было")
    return out


# ── ось читателей модуля повторной проверки ─────────────────────────────────

def _imports_gate(path: Path) -> Optional[bool]:
    """Импортирует ли файл модуль повторной проверки. Разбор по AST.

    Три формы импорта — одно утверждение::

        import spa_core.execution.safety_checks
        from spa_core.execution.safety_checks import PreExecutionSafety
        from spa_core.execution import safety_checks        # господствующая

    ``None`` — файл не разобран (синтаксис/чтение): третий исход, а не «не
    импортирует». Упоминание имени в строке, комментарии или константе импортом
    НЕ является — именно этим первая редакция объявила сам прибор читателем.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    parent, _, leaf = GATE_MODULE_DOTTED.rpartition(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == GATE_MODULE_DOTTED:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == GATE_MODULE_DOTTED:
                return True
            if node.module == parent and any(
                    alias.name == leaf for alias in node.names):
                return True
    return False


def gate_reader_axis(repo_root: Optional[Path]) -> Dict[str, Any]:
    """Есть ли у модуля повторной проверки читатель на денежном пути.

    Мерится ЗАМЕРОМ по дереву, а не утверждением. Корень недоступен ⇒ третий
    исход: «читателей нет» и «не смотрели» обязаны быть различимы. Файлы, что
    не разобрались, тоже третий исход и НЕ молчат.
    """
    if repo_root is None or not Path(repo_root).exists():
        return {"measured": False,
                "reason": "корень репозитория не передан или не существует — "
                          "читатели модуля повторной проверки НЕ измерены",
                "module": GATE_MODULE, "money_path_callers": None,
                "inert_callers": None, "test_callers": None,
                "unparsed_files": None}
    root = Path(repo_root)
    if not (root / GATE_MODULE).exists():
        return {"measured": False,
                "reason": f"модуля повторной проверки нет в дереве: {GATE_MODULE}",
                "module": GATE_MODULE, "money_path_callers": None,
                "inert_callers": None, "test_callers": None,
                "unparsed_files": None}
    money: List[str] = []
    inert: List[str] = []
    tests: List[str] = []
    unparsed: List[str] = []
    for sub in ("spa_core", "scripts"):
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel == GATE_MODULE:
                continue
            verdict = _imports_gate(path)
            if verdict is None:
                unparsed.append(rel)
                continue
            if not verdict:
                continue
            if "/tests/" in rel or Path(rel).name.startswith("test_"):
                tests.append(rel)
            elif rel in GATE_INERT_CALLERS:
                inert.append(rel)
            else:
                money.append(rel)
    return {"measured": True, "reason": None, "module": GATE_MODULE,
            "money_path_callers": money, "inert_callers": inert,
            "test_callers": tests, "unparsed_files": unparsed}


def identity_axis(executions: List[dict]) -> Dict[str, Any]:
    """Побочная ось: уникален ли ярлык исполнения (`trade_id`) в цепочке."""
    labels: Dict[str, List[dict]] = {}
    unlabelled = 0
    for event in executions:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        tid = data.get("trade_id")
        if not isinstance(tid, str) or not tid:
            unlabelled += 1
            continue
        labels.setdefault(tid, []).append(event)
    collisions = []
    for tid, rows in sorted(labels.items()):
        if len(rows) < 2:
            continue
        payloads = {json.dumps(r.get("data"), sort_keys=True, ensure_ascii=False)
                    for r in rows}
        collisions.append({
            "trade_id": tid, "events": len(rows),
            "payloads_distinct": len(payloads),
            "timestamps": [r.get("timestamp") for r in rows],
        })
    return {"measured": True, "events": len(executions),
            "distinct_labels": len(labels),
            #: СОСТАВ, а не только счёт. Счёт отвечает на вопрос «уникален ли
            #: ярлык», состав — на вопрос «а все ли ходы книги вообще попали в
            #: цепочку»; второй читатель цепочки, собирающий этот состав сам,
            #: был бы вторым местом для правила «что считать исполнением».
            "labels": sorted(labels),
            "unlabelled_events": unlabelled,
            "colliding_labels": collisions}


# ── перепись ────────────────────────────────────────────────────────────────

def run_census(data_dir: Path, now: Optional[datetime] = None,
               repo_root: Optional[Path] = None,
               tolerance_s: Optional[float] = None,
               params: Any = None) -> Dict[str, Any]:
    """Перепись: у каждого записанного исполнения — было ли второе наблюдение."""
    now = now or datetime.now(timezone.utc)
    policy = load_owner_tolerance(params)
    if tolerance_s is None and policy.get("measured"):
        declared = policy.get("tolerance_s")
        tolerance_s = float(declared) if isinstance(declared, (int, float)) \
            and not isinstance(declared, bool) else None
    chain = read_chain(Path(data_dir) / CHAIN_FILENAME)
    if not chain["ok"]:
        return _unmeasured(chain["reason"], now, policy=policy)
    rows = chain["rows"]
    by_id = {r["event_id"]: r for r in rows
             if isinstance(r.get("event_id"), str) and r.get("event_id")}
    executions = [r for r in rows if r.get("event_type") == EVENT_EXECUTED]
    if not executions:
        return _unmeasured(
            "в цепочке аудита нет ни одного события `trade_executed` — предмета "
            "замера сегодня нет, и это НЕ «повторная проверка на месте»",
            now, policy=policy, chain_rows=len(rows))
    scored = [score_execution(event, by_id, tolerance_s) for event in executions]
    kinds = {kind: [s for s in scored if s["kind"] == kind]
             for kind in ("no_recheck", "recheck_present",
                          "stale_beyond_tolerance", "unmeasured")}
    measurable = [s for s in scored if s["kind"] != "unmeasured"]
    windows = sorted(s["window_s"] for s in measurable
                     if isinstance(s.get("window_s"), (int, float)))
    #: Вердикт судит НАСТОЯЩЕЕ: свежайшее исполнение. История остаётся замером —
    #: сторож, красный навсегда, учит себя игнорировать.
    freshest = max(
        (s for s in measurable if _parse_ts(s.get("ts")) is not None),
        key=lambda s: _parse_ts(s["ts"]), default=None)
    if kinds["stale_beyond_tolerance"]:
        status = STATUS_CRITICAL
    elif kinds["no_recheck"]:
        status = STATUS_WARNING
    elif measurable:
        status = STATUS_OK
    else:
        return _unmeasured(
            "ни одно исполнение не прослежено до предложения — окно и второе "
            "наблюдение не измерены ни у одного",
            now, policy=policy, chain_rows=len(rows),
            unmeasured_records=kinds["unmeasured"])
    return {
        "measured": True, "status": status,
        "generated_at": now.isoformat(), "criterion": CRITERION,
        "schema": "pre_trade_recheck_census/v1",
        "policy": policy,
        "tolerance_s": tolerance_s,
        #: Судить чрезмерную старость нечем, пока владелец не объявил допуск.
        #: False здесь — третий исход вопроса, а не «вход свеж».
        "freshness_judgeable": tolerance_s is not None,
        "freshness_unjudgeable_reason": (
            None if tolerance_s is not None else
            "владелец не объявил ни допуска свежести входа, ни срока годности "
            "решения (§28): в колонке TriggerParams такой ручки нет, слова "
            "`valid_until` нет ни в одном файле — вопрос «вход был слишком "
            "стар» НЕ ИЗМЕРЕН и не выдаётся за «чисто»"),
        "chain_rows": len(rows),
        "unparsable_lines": chain["unparsable_lines"],
        "executions": len(executions),
        "executions_measurable": len(measurable),
        "no_recheck": len(kinds["no_recheck"]),
        "recheck_present": len(kinds["recheck_present"]),
        "stale_beyond_tolerance": len(kinds["stale_beyond_tolerance"]),
        "records_unmeasured": len(kinds["unmeasured"]),
        "ttl_declared_count": sum(1 for s in measurable
                                  if s.get("ttl_declared") is True),
        "window_s_min": (windows[0] if windows else None),
        "window_s_median": (windows[len(windows) // 2] if windows else None),
        "window_s_max": (windows[-1] if windows else None),
        "freshest_execution": freshest,
        "findings": [s for s in scored
                     if s["kind"] in ("no_recheck", "stale_beyond_tolerance")],
        "unmeasured_records": kinds["unmeasured"],
        "gate_readers": gate_reader_axis(repo_root),
        "identity": identity_axis(executions),
        "recheck_vocabulary": list(RECHECK_EVENT_TYPES),
        "does_not_report": [
            "верность самих проверок PreExecutionSafety",
            "покрытие каждого из девяти предметов §27 по отдельности",
            "вред в долларах (окно печатается, в деньги не переводится)",
        ],
        "advisory": ("прибор только ЧИТАЕТ: RiskPolicy, стоп-кран, аллокатор, "
                     "TriggerParams, живой трек и landing/ не трогаются"),
    }


def _unmeasured(reason: str, now: datetime,
                policy: Optional[Dict[str, Any]] = None,
                chain_rows: Optional[int] = None,
                unmeasured_records: Optional[List[dict]] = None) -> Dict[str, Any]:
    """Третий исход. Причина названа, предмет назван, разбор не теряется."""
    records = list(unmeasured_records or [])
    return {
        "measured": False, "status": STATUS_UNMEASURED, "reason": reason,
        "generated_at": now.isoformat(), "criterion": CRITERION,
        "schema": "pre_trade_recheck_census/v1",
        "policy": (dict(policy) if policy else None),
        "tolerance_s": None, "freshness_judgeable": False,
        "freshness_unjudgeable_reason": "перепись не измерена",
        "chain_rows": chain_rows, "unparsable_lines": None,
        "executions": 0, "executions_measurable": 0,
        "no_recheck": 0, "recheck_present": 0, "stale_beyond_tolerance": 0,
        "records_unmeasured": len(records), "ttl_declared_count": 0,
        "window_s_min": None, "window_s_median": None, "window_s_max": None,
        "freshest_execution": None, "findings": [],
        "unmeasured_records": records,
        "gate_readers": {"measured": False,
                         "reason": "перепись не измерена",
                         "module": GATE_MODULE, "money_path_callers": None,
                         "inert_callers": None, "test_callers": None,
                         "unparsed_files": None},
        "identity": {"measured": False, "events": 0, "distinct_labels": 0,
                     #: None, а не `[]`: «состава нет» и «состав пуст» — разные
                     #: ответы, и второй здесь был бы неправдой (инв. #17).
                     "labels": None,
                     "unlabelled_events": 0, "colliding_labels": []},
        "recheck_vocabulary": list(RECHECK_EVENT_TYPES),
        "does_not_report": [], "advisory": "прибор только ЧИТАЕТ",
    }


# ── отчёт ───────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"повторная проверка перед исполнением (§49 Pre-trade safety): "
                f"НЕ ИЗМЕРЕНО — {report.get('reason')}")
    return (f"повторная проверка перед исполнением (§49 Pre-trade safety): "
            f"{report['status']} · исполнений {report['executions']} "
            f"(измеримых {report['executions_measurable']}) · БЕЗ второго "
            f"наблюдения {report['no_recheck']} · с повторной проверкой "
            f"{report['recheck_present']} · старше допуска "
            f"{report['stale_beyond_tolerance']} · срок годности объявлен у "
            f"{report['ttl_declared_count']} · окно "
            f"{report['window_s_min']}…{report['window_s_max']}с · НЕ ИЗМЕРЕНО "
            f"{report['records_unmeasured']}")


def _gate_lines(report: Dict[str, Any]) -> List[str]:
    """Читатели модуля повторной проверки. Не измерено ⇒ так и сказать."""
    axis = observed(report, "gate_readers", kind=dict)
    if axis is None:
        return ["[ЧИТАТЕЛИ] НЕ ИЗМЕРЕНО — артефакт не несёт поля `gate_readers`"]
    if not axis.get("measured"):
        return [f"[ЧИТАТЕЛИ] НЕ ИЗМЕРЕНО — {axis.get('reason')}"]
    money = axis.get("money_path_callers") or []
    inert = axis.get("inert_callers") or []
    tests = axis.get("test_callers") or []
    lines = [f"[ЧИТАТЕЛИ] модуль повторной проверки {axis.get('module')}: "
             f"на денежном пути {len(money)} · инертных {len(inert)} · "
             f"тестов {len(tests)}"]
    if not money:
        lines.append("   на денежном пути читателя НЕТ — и по инварианту #6 "
                     "бумажный код не вправе его импортировать; значит между "
                     "«проверка написана» и «ход перепроверяется» стои́т "
                     "ненаписанная ступень, а не забытый вызов")
    for rel in inert:
        lines.append(f"   [инертный] {rel} — готовность/аудит, книгу не двигает")
    return lines


def _identity_lines(report: Dict[str, Any]) -> List[str]:
    """Побочная ось: уникальность ярлыка исполнения."""
    axis = observed(report, "identity", kind=dict)
    if axis is None:
        return ["[ЯРЛЫК] НЕ ИЗМЕРЕНО — артефакт не несёт поля `identity`"]
    coll = axis.get("colliding_labels") or []
    if not coll:
        return [f"[ЯРЛЫК] ярлык исполнения уникален: событий "
                f"{axis.get('events')}, ярлыков {axis.get('distinct_labels')}"]
    lines = [f"[ЯРЛЫК] ПОБОЧНО: событий {axis.get('events')} несут "
             f"{axis.get('distinct_labels')} разных `trade_id`, и у {len(coll)} "
             f"ярлыков payload РАЗНЫЙ — один ярлык называет разные денежные "
             f"события; население считается по `event_id`, не по `trade_id`"]
    for item in coll[:3]:
        lines.append(f"   [{item.get('trade_id')}] событий {item.get('events')}, "
                     f"разных payload {item.get('payloads_distinct')}: "
                     f"{', '.join(str(t)[:19] for t in (item.get('timestamps') or []))}")
    return lines


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Отчёт для шага 0-офис."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        lines.append(f"[ПРЕДМЕТ] {report.get('criterion')}")
        return lines
    if not report.get("freshness_judgeable"):
        lines.append(f"[НЕ ИЗМЕРЕНО] {report.get('freshness_unjudgeable_reason')}")
    policy = observed(report, "policy", kind=dict)
    if policy is not None and policy.get("dials"):
        dials = policy["dials"]
        names = ", ".join(sorted(k for k in dials
                                 if k not in ("version", "version_date", "mode")))
        lines.append(f"[КОЛОНКА ВЛАДЕЛЬЦА] {policy.get('version')} "
                     f"({policy.get('mode')}), ручек {len(dials)}: {names}")
        lines.append("   ни одна из них не про свежесть входа на момент "
                     "исполнения и не про срок годности решения (§28)")
    findings = observed(report, "findings", kind=list)
    if findings is None:
        lines.append("[НАХОДКИ] НЕ ИЗМЕРЕНО — артефакт не несёт поля `findings`")
    else:
        for item in findings[:limit]:
            lines.append(
                f"[{item.get('kind')}] {item.get('trade_id')} "
                f"{str(item.get('ts'))[:19]}: окно {item.get('window_s')}с, "
                f"наблюдение {item.get('snapshot_id')} — {item.get('reason')}")
        if len(findings) > limit:
            lines.append(f"… ещё {len(findings) - limit} находок(и) — "
                         f"полный перечень в артефакте")
    fresh = observed(report, "freshest_execution", kind=dict)
    if fresh is not None:
        lines.append(f"[СВЕЖАЙШЕЕ] {fresh.get('trade_id')} "
                     f"{str(fresh.get('ts'))[:19]}: {fresh.get('kind')} · цепочка "
                     f"{'→'.join(str(c) for c in (fresh.get('chain') or []))}")
    lines.append(f"[ОКНО] предложение→исполнение: min {report.get('window_s_min')}с · "
                 f"медиана {report.get('window_s_median')}с · max "
                 f"{report.get('window_s_max')}с — окно ИЗМЕРЕНО и мало; вред "
                 f"сегодня не в долларах, а в том, что отменять исчезнувшую "
                 f"возможность (§-тест 11) нечем")
    lines.extend(_gate_lines(report))
    lines.extend(_identity_lines(report))
    for item in (observed(report, "unmeasured_records", kind=list) or [])[:3]:
        lines.append(f"[ЗАПИСЬ НЕ ИЗМЕРЕНА] {item.get('trade_id')}: "
                     f"{item.get('reason')}")
    lines.append("НЕ ДОКЛАДЫВАЕТ: " + " · ".join(
        report.get("does_not_report") or ["—"]))
    lines.append(f"ADVISORY: {report.get('advisory')}")
    return lines


# ── ступень моста ───────────────────────────────────────────────────────────

def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь). Обратный порядок `atomic_save` отвергает
    # fail-CLOSED, и артефакт не появляется ВОВСЕ, а ступень докладывает
    # `measured=True` — отказ записи становится неотличим от успеха у всех, кто
    # смотрит на вывод, а не на диск (настоящая поломка цикла #701, ADR-480).
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ступень моста находок (`findings_bridge`): померить и оставить артефакт.

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до читателя, иначе шаг 0-офис увидит отсутствие
    файла и не сможет отличить его от «ступень не запускалась».
    """
    data_dir = Path(root) / "data"
    report = run_census(data_dir, now=now, repo_root=Path(root))
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (по умолчанию — data/ репозитория)")
    ap.add_argument("--repo-root", default=None,
                    help="корень дерева для оси читателей (по умолчанию — свой)")
    ap.add_argument("--tolerance-s", type=float, default=None,
                    help="допуск свежести входа в секундах, ОБЪЯВЛЕННЫЙ "
                         "владельцем; без него вопрос «слишком стар» остаётся "
                         "третьим исходом")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    ap.add_argument("--save", action="store_true",
                    help=f"записать {ARTIFACT_NAME} в каталог данных")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else \
        Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(data_dir, repo_root=repo_root,
                        tolerance_s=args.tolerance_s)
    if args.save and report.get("measured"):
        save_artifact(report, data_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)

    if not report.get("measured"):
        return EXIT_UNMEASURED
    # Ненулевой код — только на CRITICAL, то есть на исполнение, которое реально
    # стояло на входе старше ОБЪЯВЛЕННОГО допуска. `WARNING` печатается всегда,
    # но кодом не нудит: постоянно ненулевой прибор учит пропускать свой вывод,
    # а структурное утверждение держат ADR и карточка владельцу.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
