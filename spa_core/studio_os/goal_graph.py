"""Цель → граф задач → допуск → действие на СТЕНДЕ → машинный исход (STUDIO-AUTONOMY-01, поставка S1).

Детерминированные звенья поверх существующего пакета работы (:mod:`spa_core.studio_os.work_packet`).
LLM здесь нет (инв. #3): план модели — ВХОД валидатора, а не разрешение; текст «NONE» правом не
становится. Модуль ничего не пишет в рабочий трекер и рабочие данные: цель и журнал живут в
каталоге прогона, действия исполняются только внутри объявленного стенда. Подключение к
производственным входам (пульт, цикл) — отдельный cutover, этим модулем НЕ выполняется.

Звенья:

* :func:`goal_record` — версионированная цель (E1.1). Повтор ТОГО ЖЕ транспортного сообщения даёт
  ту же идентичность; новая сознательная заметка с тем же текстом — новую. Новая версия цели не
  переписывает старую: :func:`revise_goal` ссылается на прежнюю.
* :func:`validate_plan` — компилятор предложения модели в проверяемый граф (E1.2). Отвергает
  целиком: циклы, несуществующие зависимости, операции вне scope и вне словаря, задачи без
  результата или без объявленной проверки, скрытый предмет владельца. Частично разобранный план
  не исполняется — у отвергнутого графа нет версии.
* :func:`operation_subject` — предмет действия выводится из САМОЙ операции (тип, пути), а не из
  поля ``owner_subject`` модели (E3.1). Неизвестный тип — ``unknown`` ⇒ решать владельцу.
* :func:`approve_task` / :func:`admission` — допуск привязан к цели, версии плана, задаче, набору
  операций, проверке и сроку (E3.3). Любой сдвиг ⇒ нужен новый допуск. Роль ``model`` не одобряет.
* :func:`execute_on_stand` — исполнение ТОЛЬКО на стенде: путь вне стенда — отказ; повтор с тем же
  ключом операции не создаёт второго эффекта (журнал-квитанция); поверх рабочих файлов не пишет.
* :func:`machine_result` — исход по объявленной ДО работы проверке: встроенные виды
  (``file_sha256``, ``file_contains``) или проба реестра ``card_acceptance`` на корне стенда.
  Три исхода различимы: satisfied · not_satisfied · unmeasured.

Журнал переходов — append-only JSONL в каталоге прогона; каждая запись несёт ожидаемое прежнее
состояние, ключ операции и автора. Неподтверждённое состояние не превращается в done.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence

from spa_core.studio_os import work_packet as wp

GOAL_SCHEMA = "studio-goal/1"
GRAPH_SCHEMA = "studio-task-graph/1"
JOURNAL_FILE = "goal_journal.jsonl"
SATISFIED, NOT_SATISFIED, UNMEASURED = "satisfied", "not_satisfied", "unmeasured"

#: Словарь операций, которые S1 умеет исполнять на стенде. Всё прочее — вне словаря ⇒ отказ плана.
STAND_OPS = ("write_file",)
#: Операции, которые план может назвать, но которые сами по себе — предмет владельца.
IRREVERSIBLE_OPS = ("delete", "force_push", "publish", "external_call", "push_main", "restart_service")
KNOWN_OPS = STAND_OPS + IRREVERSIBLE_OPS
#: Пути, изменение которых — предмет владельца по ADR-285 (деньги · публичное).
_MONEY_PATHS = ("spa_core/risk/", "spa_core/governance/", "spa_core/execution/", "spa_core/capital_shadow/",
                "spa_core/paper_trading/", "data/")
_PUBLIC_PATHS = ("landing/",)
CHECK_KINDS = ("file_sha256", "file_contains", "card_probe")


class Refused(Exception):
    """Детерминированный отказ звена с причиной для человека."""


def _sha(obj: Any) -> str:
    raw = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


# ── E1.1 цель ────────────────────────────────────────────────────────────────────────────────────
def goal_record(text: str, *, source: str, transport_id: str, owner: str, outcome: str,
                constraints: Sequence[str] = (), at: str, supersedes: Optional[str] = None) -> Dict[str, Any]:
    """Версионированная цель. Идентичность = источник + ид. транспортного сообщения (+ текст):
    повтор доставки того же сообщения — та же цель; новая заметка с тем же текстом — новая."""
    if not _norm(text):
        raise Refused("цель пуста")
    if not _norm(outcome):
        raise Refused("у цели нет измеряемого результата — исполнять нечего проверять")
    if not transport_id:
        raise Refused("нет идентификатора исходного сообщения — повтор доставки отличить нельзя")
    goal_id = "goal-" + _sha({"source": source, "transport_id": transport_id, "text": _norm(text)})[:16]
    body = {"schema": GOAL_SCHEMA, "goal_id": goal_id, "text": text, "source": source,
            "transport_id": transport_id, "owner": owner, "outcome": outcome,
            "constraints": list(constraints), "at": at, "supersedes": supersedes}
    body["version"] = _sha({k: body[k] for k in ("goal_id", "text", "outcome", "constraints", "supersedes")})
    return body


def revise_goal(old: Dict[str, Any], *, text: str, outcome: str, transport_id: str, at: str,
                constraints: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Новая версия цели (E1.6): старая не переписывается, новая на неё ссылается."""
    return goal_record(text, source=old["source"], transport_id=transport_id, owner=old["owner"],
                       outcome=outcome, constraints=old["constraints"] if constraints is None else constraints,
                       at=at, supersedes=old["version"])


# ── E3.1 предмет из операции ─────────────────────────────────────────────────────────────────────
def _clean_path(path: Any) -> Optional[str]:
    p = PurePosixPath(str(path or ""))
    if not str(p) or p.is_absolute() or ".." in p.parts:
        return None
    return str(p)


def operation_subject(op: Dict[str, Any]) -> str:
    """'none' · 'money' · 'public' · 'irreversible' · 'unknown' — из типа и путей операции."""
    kind = op.get("op")
    if kind in IRREVERSIBLE_OPS:
        return "irreversible"
    if kind not in KNOWN_OPS:
        return "unknown"
    path = _clean_path(op.get("path"))
    if path is None:
        return "unknown"
    if path.startswith(_MONEY_PATHS):
        return "money"
    if path.startswith(_PUBLIC_PATHS):
        return "public"
    return "none"


def task_subject(task: Dict[str, Any]) -> str:
    """Предмет задачи — самый строгий предмет её операций."""
    order = ("unknown", "irreversible", "money", "public", "none")
    subs = [operation_subject(op) for op in task.get("operations") or []]
    return next((s for s in order if s in subs), "unknown")


# ── E1.2 план → граф ─────────────────────────────────────────────────────────────────────────────
def _check_spec(check: Any) -> Optional[str]:
    if not isinstance(check, dict) or check.get("kind") not in CHECK_KINDS:
        return f"вид проверки не из словаря {CHECK_KINDS}"
    if check["kind"] in ("file_sha256", "file_contains"):
        if _clean_path(check.get("path")) is None:
            return "путь проверки пуст или выходит за корень"
        if check["kind"] == "file_sha256" and not re.fullmatch(r"[0-9a-f]{64}", str(check.get("sha256") or "")):
            return "file_sha256 без полного хеша"
        if check["kind"] == "file_contains" and not str(check.get("text") or ""):
            return "file_contains без текста"
        return None
    try:
        wp.bind_probe(str(check.get("probe") or ""))
    except wp.Refused as exc:
        return str(exc)
    return None


def _in_scope(path: str, scope: Sequence[str]) -> bool:
    return any(path == s.rstrip("/") or path.startswith(s.rstrip("/") + "/") for s in scope)


def validate_plan(goal: Dict[str, Any], proposal: Any, *, scope: Sequence[str],
                  existing: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Предложение модели → граф либо отказ ЦЕЛИКОМ. Возвращает ``{"ok", "refusals", "graph"}``.

    ``existing`` — уже существующие задачи бэклога ``{id: {"done": bool, "evidence": str}}``:
    на них можно ссылаться как на зависимости (E1.3), но только по точному ID.
    """
    existing = existing or {}
    why: List[str] = []
    tasks = proposal.get("tasks") if isinstance(proposal, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return {"ok": False, "refusals": ["план не разобран: нет списка задач"], "graph": None}
    ids = [t.get("id") for t in tasks if isinstance(t, dict)]
    if len(ids) != len(tasks) or any(not isinstance(i, str) or not i for i in ids):
        why.append("у задачи нет идентификатора")
    if len(set(ids)) != len(ids):
        why.append("идентификаторы задач повторяются")
    for t in (t for t in tasks if isinstance(t, dict)):
        tid = t.get("id")
        if not _norm(str(t.get("outcome") or "")):
            why.append(f"{tid}: нет ожидаемого результата")
        bad = _check_spec(t.get("check"))
        if bad:
            why.append(f"{tid}: проверка результата не годится — {bad}")
        ops = t.get("operations")
        if not isinstance(ops, list) or not ops:
            why.append(f"{tid}: нет операций — исполнять нечего")
            ops = []
        for op in ops:
            if not isinstance(op, dict) or op.get("op") not in KNOWN_OPS:
                why.append(f"{tid}: операция {op.get('op') if isinstance(op, dict) else op!r} вне словаря")
                continue
            path = _clean_path(op.get("path"))
            if op["op"] in STAND_OPS and (path is None or not _in_scope(path, scope)):
                why.append(f"{tid}: путь {op.get('path')!r} вне объявленного scope")
        derived = task_subject(t)
        claimed = t.get("owner_subject")
        if claimed is not None and claimed != derived and derived != "none":
            why.append(f"{tid}: модель объявила предмет «{claimed}», а операции дают «{derived}» — "
                       f"скрытый предмет не принимается")
        for dep in t.get("depends_on") or []:
            if dep not in ids and dep not in existing:
                why.append(f"{tid}: зависимость {dep!r} не существует ни в плане, ни в бэклоге")
    order = _topo(tasks, existing) if not why else None
    if not why and order is None:
        why.append("в зависимостях цикл")
    if why:
        return {"ok": False, "refusals": why, "graph": None}
    graph = {"schema": GRAPH_SCHEMA, "goal_id": goal["goal_id"], "goal_version": goal["version"],
             "scope": list(scope), "order": order,
             "tasks": {t["id"]: {**t, "subject": task_subject(t)} for t in tasks},
             "existing": {k: existing[k] for t in tasks for k in (t.get("depends_on") or []) if k in existing}}
    graph["version"] = _sha({k: graph[k] for k in ("goal_id", "goal_version", "scope", "tasks", "existing")})
    return {"ok": True, "refusals": [], "graph": graph}


def _topo(tasks: List[Dict[str, Any]], existing: Dict[str, Any]) -> Optional[List[str]]:
    deps = {t["id"]: [d for d in (t.get("depends_on") or []) if d not in existing] for t in tasks}
    order: List[str] = []
    state: Dict[str, int] = {}

    def visit(n: str) -> bool:
        if state.get(n) == 1:
            return False
        if state.get(n) == 2:
            return True
        state[n] = 1
        for d in deps[n]:
            if not visit(d):
                return False
        state[n] = 2
        order.append(n)
        return True

    for t in sorted(deps):
        if not visit(t):
            return None
    return order


def ready_tasks(graph: Dict[str, Any], done: Iterable[str]) -> List[str]:
    """Задачи, чьи зависимости выполнены (внешние — по evidence бэклога), в порядке графа."""
    done = set(done)
    out = []
    for tid in graph["order"]:
        if tid in done:
            continue
        deps = graph["tasks"][tid].get("depends_on") or []
        if all(d in done or (graph["existing"].get(d) or {}).get("done") for d in deps):
            out.append(tid)
    return out


# ── E3.3 допуск, привязанный к версии ────────────────────────────────────────────────────────────
def _ops_sha(task: Dict[str, Any]) -> str:
    return _sha(task.get("operations") or [])


def approve_task(graph: Dict[str, Any], task_id: str, *, approver: str, role: str, at: str,
                 expires_at: str, source: str = wp.SOURCE_OPERATOR_IMPORT) -> Dict[str, Any]:
    """Допуск ровно этой задачи ровно этой версии графа, её операций и проверки, до срока."""
    if role not in wp.ROLES:
        raise Refused(f"роль «{role}» не может одобрять: ответ модели — не разрешение")
    if source not in wp.SOURCES:
        raise Refused(f"источник одобрения «{source}» не известен")
    task = graph["tasks"].get(task_id)
    if task is None:
        raise Refused(f"задачи {task_id!r} нет в графе")
    if task["subject"] != "none" and role != "owner":
        raise Refused(f"предмет задачи «{task['subject']}» — одобрить может только владелец")
    return {"goal_id": graph["goal_id"], "graph_version": graph["version"], "task_id": task_id,
            "ops_sha256": _ops_sha(task), "check_sha256": _sha(task["check"]), "subject": task["subject"],
            "approver": approver, "role": role, "source": source, "at": at, "expires_at": expires_at}


def _parse(ts: Any) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def admission(graph: Dict[str, Any], task_id: str, approval: Optional[Dict[str, Any]], *, now: str,
              revoked: Iterable[str] = ()) -> List[str]:
    """Почему исполнять НЕЛЬЗЯ (пусто — можно). Каждый разрыв назван отдельно."""
    task = graph["tasks"].get(task_id)
    if task is None:
        return [f"задачи {task_id!r} нет в графе"]
    if not isinstance(approval, dict):
        return ["нет допуска этой задачи"]
    why = []
    if approval.get("goal_id") != graph["goal_id"] or approval.get("graph_version") != graph["version"]:
        why.append("допуск выдан другой версии цели или плана")
    if approval.get("task_id") != task_id:
        why.append(f"допуск другой задачи ({approval.get('task_id')})")
    if approval.get("ops_sha256") != _ops_sha(task):
        why.append("операции изменились после допуска")
    if approval.get("check_sha256") != _sha(task["check"]):
        why.append("проверка результата изменилась после допуска")
    if approval.get("subject") != task["subject"] or (task["subject"] != "none" and approval.get("role") != "owner"):
        why.append("предмет задачи требует допуска владельца")
    if approval.get("role") not in wp.ROLES:
        why.append(f"роль «{approval.get('role')}» не допускает")
    try:
        if _parse(now) >= _parse(approval.get("expires_at")):
            why.append("срок допуска истёк")
    except (TypeError, ValueError):
        why.append("срок допуска не читается — считается истёкшим")
    if _sha(approval) in set(revoked):
        why.append("допуск отозван")
    return why


# ── журнал переходов ─────────────────────────────────────────────────────────────────────────────
def _journal(run_dir: Path) -> List[Dict[str, Any]]:
    path = Path(run_dir) / JOURNAL_FILE
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append(run_dir: Path, row: Dict[str, Any]) -> None:
    path = Path(run_dir) / JOURNAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def task_state(run_dir: Path, graph_version: str, task_id: str) -> str:
    """Последнее записанное состояние задачи для этой версии графа ('new' — записей нет)."""
    st = "new"
    for row in _journal(run_dir):
        if row.get("graph_version") == graph_version and row.get("task_id") == task_id:
            st = row["state"]
    return st


# ── исполнение на стенде ─────────────────────────────────────────────────────────────────────────
def _stand_path(stand: Path, rel: str) -> Path:
    clean = _clean_path(rel)
    if clean is None:
        raise Refused(f"путь {rel!r} выходит за стенд")
    target = (Path(stand) / clean).resolve()
    root = Path(stand).resolve()
    if root != target and root not in target.parents:
        raise Refused(f"путь {rel!r} выходит за стенд")
    return target


def execute_on_stand(graph: Dict[str, Any], task_id: str, approval: Optional[Dict[str, Any]], *,
                     stand: Path, run_dir: Path, now: str, author: str,
                     revoked: Iterable[str] = ()) -> Dict[str, Any]:
    """Исполнить операции задачи на стенде. Повтор с тем же ключом не даёт второго эффекта.

    Журнал: ``started`` (ожидалось new) → ``applied`` → ``checked:<исход>``. Падение между записями
    оставляет ``started`` — зависимые задачи такое состояние НЕ считают выполненным.
    """
    why = admission(graph, task_id, approval, now=now, revoked=revoked)
    if why:
        raise Refused("действие не допущено: " + "; ".join(why))
    stand, run_dir = Path(stand), Path(run_dir)
    if not (stand / ".studio_stand").is_file():
        raise Refused("каталог не помечен как стенд (.studio_stand) — рабочие файлы не трогаются")
    op_key = _sha({"graph": graph["version"], "task": task_id, "approval": _sha(approval)})
    prev = task_state(run_dir, graph["version"], task_id)
    if prev in ("applied",) or prev.startswith("checked:"):
        return {"op_key": op_key, "state": prev, "repeated": True}
    task = graph["tasks"][task_id]
    _append(run_dir, {"graph_version": graph["version"], "task_id": task_id, "op_key": op_key,
                      "expected": prev, "state": "started", "author": author, "at": now})
    effects = []
    for op in task["operations"]:
        if op["op"] not in STAND_OPS:
            raise Refused(f"операция {op['op']} на стенде S1 не исполняется — отдельный допуск/поставка")
        target = _stand_path(stand, op["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        data = str(op.get("content") or "").encode("utf-8")
        tmp = target.with_name(target.name + ".tmp-studio")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        effects.append({"path": op["path"], "sha256": hashlib.sha256(data).hexdigest()})
    _append(run_dir, {"graph_version": graph["version"], "task_id": task_id, "op_key": op_key,
                      "expected": "started", "state": "applied", "effects": effects, "author": author, "at": now})
    return {"op_key": op_key, "state": "applied", "repeated": False, "effects": effects}


def machine_result(graph: Dict[str, Any], task_id: str, *, stand: Path, run_dir: Path, now: str,
                   author: str = "goal_graph") -> Dict[str, Any]:
    """Исход по проверке, объявленной ДО работы. Записывается в журнал; done ставит только он."""
    st = task_state(Path(run_dir), graph["version"], task_id)
    if st != "applied":
        raise Refused(f"проверять нечего: состояние задачи «{st}», а не «applied»")
    check = graph["tasks"][task_id]["check"]
    verdict, detail = UNMEASURED, ""
    try:
        if check["kind"] in ("file_sha256", "file_contains"):
            path = _stand_path(Path(stand), check["path"])
            if not path.exists():
                verdict, detail = NOT_SATISFIED, f"файла {check['path']} нет"
            elif not path.is_file():
                verdict, detail = UNMEASURED, f"{check['path']} — не файл, проверку измерить нельзя"
            elif check["kind"] == "file_sha256":
                got = hashlib.sha256(path.read_bytes()).hexdigest()
                verdict = SATISFIED if got == check["sha256"] else NOT_SATISFIED
                detail = f"sha256 {got[:12]}"
            else:
                ok = str(check["text"]) in path.read_text(encoding="utf-8")
                verdict, detail = (SATISFIED if ok else NOT_SATISFIED), "текст найден" if ok else "текста нет"
        else:
            from spa_core.monitoring import card_acceptance as ca
            verdict, detail = ca.run_probe(check["probe"], repo_root=str(stand))
    except Refused:
        raise
    except Exception as exc:  # noqa: BLE001 — сбой проверки — третий исход, а не «прошло»
        verdict, detail = UNMEASURED, f"{type(exc).__name__}: {exc}"
    _append(Path(run_dir), {"graph_version": graph["version"], "task_id": task_id, "expected": "applied",
                            "state": f"checked:{verdict}", "detail": detail, "author": author, "at": now})
    return {"task_id": task_id, "verdict": verdict, "detail": detail}


def done_tasks(run_dir: Path, graph_version: str) -> List[str]:
    """Выполненные задачи — ТОЛЬКО с машинным исходом satisfied для этой версии графа."""
    last: Dict[str, str] = {}
    for row in _journal(Path(run_dir)):
        if row.get("graph_version") == graph_version:
            last[row["task_id"]] = row["state"]
    return sorted(t for t, s in last.items() if s == f"checked:{SATISFIED}")
