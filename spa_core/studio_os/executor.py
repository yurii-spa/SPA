"""Сменяемый исполнитель задач графа с сохраняемыми попытками (STUDIO-AUTONOMY-01, поставка S2, эпик E4).

# LLM_FORBIDDEN — этот модуль решений не принимает; модель зовётся только через контракт ролей.

Звенья (всё детерминированное; права роли не расширяются):

* **E4.1 граница модели.** Модель зовётся ТОЛЬКО через :func:`spa_core.studio_os.model_roles.contract.execute`
  ролью ``worker`` (инструментов нет — так объявлена роль). Её ответ — ВХОД :func:`goal_graph.validate_plan`,
  а не действие. Действует только доверенный механизм S1 (:func:`goal_graph.execute_on_stand`) по допуску,
  который исполнитель выдать себе не может.
* **E4.2 изоляция.** Эффекты — только на стенде (каталог с меткой ``.studio_stand``) и только операциями
  словаря S1; у самой модели инструментов нет. Техническая песочница процесса НЕ заявляется: режим исполнителя
  остаётся «патч для разбора», граница — словарь операций, scope плана и стенд.
* **E4.3 провайдер.** Провайдер — явный ``provider_id`` из ``architecture/model_roles.json``; запасного нет.
  Реальный — ``claude_subscription_cli`` (CLI на подписке); ``fixture_test_adapter`` — тестовый, не провайдер.
* **E4.4 бюджет.** Тяжёлый шаг (проверка результата) берёт аренду существующего admission
  (:func:`spa_core.utils.heavy_job.admit`, ADR-551). Отказ — пауза с сохранённой задачей, не обход.
* **E4.5 продолжение.** Всё состояние — в каталоге прогона: попытки и захваты — строки ``kind: "attempt"`` /
  ``kind: "claim"`` в журнале S1 ``goal_journal.jsonl`` (тот же протокол: flock → перечитать → дописать),
  ответ модели и граф — файлы рядом. Новый процесс определяет следующий шаг по файлам (:func:`next_step`);
  сохранённый ответ модели не запрашивается повторно; ``applied``/``checked:*`` не исполняются повторно.
  Конфликтующее исполнение исключает захват S1 с поколением: живой чужой захват — отказ, после срока —
  перехват с поколением +1, прежний исполнитель писать не может.
* **E4.6 учёт и предел.** Каждая попытка записывает провайдера, ``real_provider``, длительность, число попыток
  контракта, usage как его ДОЛОЖИЛ транспорт (иначе ``UNKNOWN``) и хеш контекста. Повторов шага не больше
  :data:`MAX_CALLS`, и предел действует через смену сессий. ``quota`` — пауза до явного продолжения;
  ``ownership_unresolved`` — повтор запрещён ЛЮБЫМ исполнителем до записи разбора.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from spa_core.studio_os import goal_graph as gg
from spa_core.studio_os.model_roles import contract as mr

ROLE = "worker"
#: Сколько вызовов модели на ОДИН шаг предложения допускается всего, через все сессии (E4.6).
MAX_CALLS = 2
ATTEMPT = "attempt"
PROPOSE_TASK = "propose"
#: Исходы шага предложения, после которых новый вызов модели НЕ делается без явной записи.
PAUSING = {"quota": "paused:quota", "ownership_unresolved": "blocked:ownership_unresolved"}
STEP_DONE = "proposed"


class Paused(gg.Refused):
    """Шаг остановлен с сохранённой задачей (квота, admission, неразобранное владение, предел попыток)."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-executor")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _step_graph(goal: Dict[str, Any], context_sha: str) -> Dict[str, Any]:
    """Шаг предложения как «граф» из одной задачи — чтобы его захват и журнал шли ТЕМ ЖЕ протоколом S1.
    Хеш контекста — часть версии: новый контекст — новый шаг, старый ответ к нему не применяется (F5)."""
    return {"version": f"propose:{goal['version']}:{context_sha}", "tasks": {PROPOSE_TASK: {}}}


def _attempts(run_dir: Path, step_version: str) -> List[Dict[str, Any]]:
    return [r for r in gg._journal(run_dir) if r.get("kind") == ATTEMPT and r.get("graph_version") == step_version]


def _append_attempt(run_dir: Path, step: Dict[str, Any], lease: Dict[str, Any], now: str, row: Dict[str, Any],
                    files: Optional[Dict[str, str]] = None) -> None:
    """Дописать строку попытки (и её файлы), если захват ещё текущий. Иначе ``Conflict``: прежнее поколение
    не пишет НИЧЕГО — ни строки, ни файлов ответа и графа (проверка и запись — под одной блокировкой)."""
    with gg._locked(run_dir):
        rows = gg._journal(run_dir)
        gg._check_lease(rows, step["version"], PROPOSE_TASK, lease, now)
        for name, data in (files or {}).items():
            _atomic_write(run_dir / name, data)
        gg._raw_append(run_dir, {"kind": ATTEMPT, "graph_version": step["version"], "task_id": PROPOSE_TASK,
                                 "generation": lease["generation"], "worker": lease["worker"], "at": now, **row})


def proposal_status(run_dir: Path, goal: Dict[str, Any], context_sha: str) -> Dict[str, Any]:
    """Где шаг предложения сейчас — ТОЛЬКО по файлам прогона. ``state``: new · proposed · paused:quota ·
    blocked:ownership_unresolved · in_flight · failed:limit; плюс сохранённые числа."""
    step = _step_graph(goal, context_sha)
    rows = _attempts(Path(run_dir), step["version"])
    results = [r for r in rows if r.get("phase") == "result"]
    started = [r for r in rows if r.get("phase") == "call_started"]
    state = "new"                                          # последняя пауза без последующего «продолжить» держит шаг
    for r in rows:
        ph, st = r.get("phase"), r.get("status")
        if ph == "result" and st == "ok" and r.get("plan_ok"):
            state = STEP_DONE
        elif ph == "result" and st in PAUSING:
            state = PAUSING[st]
        elif ph == "resume" and state == PAUSING.get("quota"):
            state = "new"
        elif ph == "ownership_resolved" and state == PAUSING.get("ownership_unresolved"):
            state = "new"
    if state == "new" and len(started) > len(results):
        state = "in_flight"
    if state in ("new", "in_flight") and len(started) >= MAX_CALLS and len(started) == len(results):
        state = "failed:limit"
    last_ok = next((r for r in reversed(results) if r.get("status") == "ok" and r.get("plan_ok")), None)
    return {"state": state, "step_version": step["version"], "calls": len(started), "results": len(results),
            "graph_version": (last_ok or {}).get("graph_version_out"), "answer_file": (last_ok or {}).get("answer_file")}


def _extract_plan(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        doc = json.loads(m.group(0))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def render_request(goal: Dict[str, Any], *, scope: Sequence[str], context: str) -> mr.Request:
    """Запрос роли worker: вернуть план в формате, который понимает ``goal_graph.validate_plan``."""
    instruction = (
        "Return ONLY one JSON object, no prose. Schema: {\"tasks\": [{\"id\": str, \"outcome\": str, "
        "\"operations\": [{\"op\": \"write_file\", \"path\": <relative path>, \"content\": <full file text>}], "
        "\"check\": {\"kind\": \"file_contains\", \"path\": <same path>, \"text\": <text that proves the outcome>}, "
        "\"depends_on\": []}]}. Allowed paths: only under " + ", ".join(scope) + ". "
        "Goal: " + goal["text"] + " Expected outcome: " + goal["outcome"])
    return mr.Request(role=ROLE, task_id=goal["goal_id"], instruction=instruction, context=context)


def propose(goal: Dict[str, Any], *, run_dir: Path, scope: Sequence[str], context: str, provider_id: str,
            adapters: Mapping[str, Callable[..., mr.AdapterOutput]], worker: str, now: str, ttl_s: int,
            config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Получить и проверить план модели, сохранив попытку ДО использования ответа.

    Сохранённый годный план — возвращается без вызова модели (E4.5). Пауза/блок/предел — ``Paused``.
    Захват шага — протоколом S1; при перехвате ответ прежнего поколения в журнал не попадает."""
    run_dir = Path(run_dir)
    req = render_request(goal, scope=scope, context=context)
    st = proposal_status(run_dir, goal, req.context_sha256)
    if st["state"] == STEP_DONE:
        return {**st, "graph": load_graph(run_dir, st["graph_version"]), "called_model": False}
    if st["state"].startswith(("paused:", "blocked:", "failed:")):
        raise Paused(f"шаг предложения: {st['state']} — новый вызов модели не делается без явного продолжения")
    step = _step_graph(goal, req.context_sha256)
    lease = gg.claim(run_dir, step, PROPOSE_TASK, worker=worker, process=f"pid:{os.getpid()}", now=now, ttl_s=ttl_s)
    st = proposal_status(run_dir, goal, req.context_sha256)          # перечитать после захвата
    if st["calls"] >= MAX_CALLS:
        raise Paused(f"предел вызовов модели на шаг ({MAX_CALLS}) исчерпан — нужен разбор, не повтор")
    _append_attempt(run_dir, step, lease, now, {"phase": "call_started", "pid": os.getpid(), "provider_id": provider_id,
                                                "context_sha256": req.context_sha256})
    res = mr.execute(req, config=config or mr.load_config(), provider_id=provider_id, adapters=adapters)
    row: Dict[str, Any] = {"phase": "result", "status": res.status, "provider_id": res.provider_id,
                           "provider_kind": res.provider_kind, "real_provider": res.real_provider,
                           "model": res.model, "contract_attempts": res.attempts, "elapsed_s": res.elapsed_s,
                           "usage": res.usage, "context_sha256": res.context_sha256, "error": (res.reason or "")[:300],
                           "attempt_log": res.attempt_log,
                           "permissions": res.permissions, "tools": res.tools, "plan_ok": False}
    files: Dict[str, str] = {}
    if res.status == "ok":
        answer_file = f"answer-{_sha(res.text)[:16]}.txt"
        files[answer_file] = res.text
        row.update(answer_file=answer_file, answer_sha256=_sha(res.text))
        plan = _extract_plan(res.text)
        if plan is None:
            row.update(status="malformed", error="в ответе нет JSON-плана")
        else:
            v = gg.validate_plan(goal, plan, scope=scope)
            row["plan_refusals"] = v["refusals"]
            if v["ok"]:
                files[f"graph-{v['graph']['version'][:16]}.json"] = json.dumps(v["graph"], ensure_ascii=False,
                                                                              sort_keys=True)
                row.update(plan_ok=True, graph_version_out=v["graph"]["version"])
    _append_attempt(run_dir, step, lease, now, row, files)
    st = proposal_status(run_dir, goal, req.context_sha256)
    if st["state"] == STEP_DONE:
        return {**st, "graph": load_graph(run_dir, st["graph_version"]), "called_model": True}
    raise Paused(f"шаг предложения: исход {row['status']} ({row.get('error') or row.get('plan_refusals')}) → {st['state']}")


def resume_after_quota(run_dir: Path, goal: Dict[str, Any], context_sha: str, *, by: str, now: str) -> None:
    """Явное продолжение после квоты — отдельная запись, а не молчаливый повтор."""
    _note(run_dir, goal, context_sha, {"phase": "resume", "by": by, "at": now})


def resolve_ownership(run_dir: Path, goal: Dict[str, Any], context_sha: str, *, by: str, now: str, evidence: str) -> None:
    """Запись разбора неразобранного владения (кто убедился, что процессов прежнего прогона нет, и чем)."""
    if not evidence.strip():
        raise gg.Refused("разбор владения без доказательства не принимается")
    _note(run_dir, goal, context_sha, {"phase": "ownership_resolved", "by": by, "evidence": evidence, "at": now})


def _note(run_dir: Path, goal, context_sha, row) -> None:
    step = _step_graph(goal, context_sha)
    with gg._locked(Path(run_dir)):
        gg._raw_append(Path(run_dir), {"kind": ATTEMPT, "graph_version": step["version"], "task_id": PROPOSE_TASK, **row})


def load_graph(run_dir: Path, version: Optional[str]) -> Optional[Dict[str, Any]]:
    if not version:
        return None
    p = Path(run_dir) / f"graph-{version[:16]}.json"
    if not p.is_file():
        return None
    g = json.loads(p.read_text(encoding="utf-8"))
    return g if g.get("version") == version else None


def load_approval(run_dir: Path, task_id: str) -> Optional[Dict[str, Any]]:
    p = Path(run_dir) / f"approval-{task_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def next_step(run_dir: Path, graph: Dict[str, Any]) -> Dict[str, Any]:
    """Следующий шаг задач графа — по журналу и файлам прогона (никакой памяти сессии)."""
    done = set(gg.done_tasks(Path(run_dir), graph["version"]))
    for tid in graph["order"]:
        st = gg.task_state(Path(run_dir), graph["version"], tid)
        if st == f"checked:{gg.SATISFIED}":
            continue
        if st.startswith("checked:") or st.startswith("aborted:revoked"):
            return {"step": "stopped", "task_id": tid, "state": st}
        if tid not in gg.ready_tasks(graph, done):
            return {"step": "waiting_dependency", "task_id": tid, "state": st}
        if st == "started":
            return {"step": "recover", "task_id": tid, "state": st}
        if st == "applied":
            return {"step": "check", "task_id": tid, "state": st}
        if load_approval(run_dir, tid) is None:
            return {"step": "await_approval", "task_id": tid, "state": st}
        return {"step": "execute", "task_id": tid, "state": st}
    return {"step": "done", "task_id": None, "state": "all satisfied"}


def advance(graph: Dict[str, Any], *, run_dir: Path, stand: Path, worker: str, now: str, ttl_s: int,
            admit: Optional[Callable[[], Any]] = None, barrier: Optional[Callable[[str], None]] = None,
            revoked: Sequence[str] = ()) -> Dict[str, Any]:
    """Сделать СЛЕДУЮЩИЙ шаг одной задачи графа под захватом. Повтор безопасен: сделанное не повторяется.

    ``admit`` — аренда admission для проверки результата (по умолчанию — существующий ``heavy_job.admit``).
    ``barrier`` — вызывается на известной границе ('started', 'applied'); нужен только для доказательства
    прерывания (тест убивает процесс на этой границе)."""
    run_dir, stand = Path(run_dir), Path(stand)
    nxt = next_step(run_dir, graph)
    tid = nxt["task_id"]
    if nxt["step"] in ("done", "stopped", "waiting_dependency", "await_approval"):
        return nxt
    lease = gg.claim(run_dir, graph, tid, worker=worker, process=f"pid:{os.getpid()}", now=now, ttl_s=ttl_s)
    if nxt["step"] == "recover":
        out = gg.recover(graph, tid, stand=stand, run_dir=run_dir, now=now, author=worker, lease=lease)
        return {"step": "recovered", "task_id": tid, "state": out["state"], "lease": lease["generation"]}
    if nxt["step"] == "execute":
        hook = (lambda: (barrier("started"), False)[1]) if barrier else None
        out = gg.execute_on_stand(graph, tid, load_approval(run_dir, tid), stand=stand, run_dir=run_dir, now=now,
                                  author=worker, lease=lease, revoked=revoked, revoked_now=hook, entry="stand_api")
        if barrier:
            barrier("applied")
        return {"step": "executed", "task_id": tid, "state": out["state"], "lease": lease["generation"]}
    # check — тяжёлый шаг под admission (E4.4)
    if admit is None:
        from spa_core.utils import heavy_job
        admit = lambda: heavy_job.admit("executor_check", str(stand), note=f"{graph['version'][:12]}:{tid}")  # noqa: E731
    try:
        hold = admit()
    except Exception as exc:  # noqa: BLE001 — отказ admission — пауза с сохранённой задачей
        return {"step": "paused:admission", "task_id": tid, "state": nxt["state"], "why": str(exc)[:300]}
    try:
        out = gg.machine_result(graph, tid, stand=stand, run_dir=run_dir, now=now, lease=lease, author=worker)
    finally:
        rel = getattr(hold, "release", None)
        if callable(rel):
            rel()
    return {"step": "checked", "task_id": tid, "state": f"checked:{out['verdict']}", "detail": out["detail"],
            "lease": lease["generation"]}


def run_until_blocked(graph: Dict[str, Any], *, run_dir: Path, stand: Path, worker: str, now: Callable[[], str],
                      ttl_s: int, admit=None, barrier=None, max_steps: int = 20) -> List[Dict[str, Any]]:
    """Шагать, пока граф не выполнен или не остановлен (ожидание допуска, пауза, отказ)."""
    log = []
    for _ in range(max_steps):
        r = advance(graph, run_dir=run_dir, stand=stand, worker=worker, now=now(), ttl_s=ttl_s, admit=admit,
                    barrier=barrier)
        log.append({k: v for k, v in r.items() if k != "lease"} | {"lease": r.get("lease")})
        if r["step"] in ("done", "stopped", "waiting_dependency", "await_approval") or r["step"].startswith("paused:"):
            break
    return log


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m spa_core.studio_os.executor run --run-dir R --stand S --graph-version V --worker W``.

    Продолжает задачи графа по файлам прогона. ``--stop-at started|applied`` — дождаться внешней остановки
    на этой границе (только для доказательства прерывания: процесс пишет ``at_<граница>`` и ждёт сигнала)."""
    import argparse
    ap = argparse.ArgumentParser(prog="executor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-dir", required=True)
    r.add_argument("--stand", required=True)
    r.add_argument("--graph-version", required=True)
    r.add_argument("--worker", required=True)
    r.add_argument("--ttl-s", type=int, default=600)
    r.add_argument("--stop-at", choices=("started", "applied"))
    r.add_argument("--admission-registry", help="каталог аренд admission (политика чисел — прежняя, ADR-551)")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir)
    graph = load_graph(run_dir, a.graph_version)
    if graph is None:
        print(json.dumps({"step": "refused", "why": "граф этой версии в каталоге прогона не найден"}))
        return 2

    def barrier(at: str) -> None:
        if a.stop_at == at:
            _atomic_write(run_dir / f"at_{at}-{os.getpid()}", str(os.getpid()))
            while True:                                      # ждать SIGKILL владельца теста
                time.sleep(0.2)

    try:
        admit = None
        if a.admission_registry:
            from spa_core.utils import heavy_job
            pol = {**heavy_job._policy(), "registry_dir": a.admission_registry}
            admit = lambda: heavy_job.admit("executor_check", a.stand, policy=pol, renice=False)  # noqa: E731
        log = run_until_blocked(graph, run_dir=run_dir, stand=Path(a.stand), worker=a.worker, now=_now_iso,
                                ttl_s=a.ttl_s, admit=admit, barrier=barrier if a.stop_at else None)
    except gg.Refused as exc:
        print(json.dumps({"step": "refused", "why": str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps(log, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
