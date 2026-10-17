"""Запись из пульта получает исполнителя БЕЗ человека; потерянная побудка приёма находится сама.

Положительные контроли заказа ARB 16.10 («агент сам отправил запись и сам же взял её вручную —
автономность НЕ доказана»). На `origin/main` 3584de55f красны все: модуля `cockpit_dispatch` нет,
обёртка цикла записей пульта не выбирает и после сессии ничего не перемеряет.

  * принятая запись пульта выбирается РОВНО один раз; повторный прогон выбора — no-op;
  * запись без объявленной пробы НЕ становится «сделано»: «не принято» с причиной и следующим шагом,
    одно уведомление, повторный прогон её не трогает; объявили пробу — снова кандидат;
  * после сессии «сделано» ставит только проба; иначе `blocked` с причиной — без второго исполнения;
  * запись, побудка которой потерялась, побуждается снова, и повтор приёма/выбора ничего не дублирует;
  * обёртка цикла (`scripts/agent_orchestrator.sh`) доносит взятую запись до промпта ПЕРВОЙ и
    после сессии зовёт перемер с той же карточкой и тем же исполнителем.

Время — вход (`now=` от реальных часов); Telegram — список в памяти; `history_check` — заглушка.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import cockpit_dispatch as cd
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import intake as oi
from spa_core.owner_queue import queue as q
from spa_core.studio_os import mission_intake as mi

NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = (NOW - timedelta(hours=2)).strftime("%a %b %d %H:%M:%S %Y")
SPEC = "contract_manifest_parity_agrees"      # имя из реестра; исход задаёт runner сцены
_REPO = Path(__file__).resolve().parents[2]


def _guard():
    spec = importlib.util.spec_from_file_location(
        "_t_dispatch_card_claim", Path(ca.REPO_ROOT) / "scripts" / "check_card_claim.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


@pytest.fixture(autouse=True)
def _no_real_classifier(monkeypatch, tmp_path):
    """Ни один тест файла не ходит к НАСТОЯЩЕМУ `claude` — ни на Mac, где бинарь есть, ни на CI.

    Контрольный прогон 39003158532: тест приёма зелёный на Mac, потому что приём звал живой
    классификатор (LLM), и красный на CI, где бинаря нет. Подмена делает исход одинаковым везде:
    позвал классификатор ⇒ «недоступен» ⇒ карточка остаётся `new` ⇒ тест красный на ЛЮБОЙ машине.
    """
    from spa_core.telegram import ask_router
    monkeypatch.setattr(ask_router, "_CLAUDE", str(tmp_path / "no-real-claude-in-tests"))


@pytest.fixture
def scene(tmp_path):
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")
    g = _guard()
    sib = g.load_sibling()
    anchors = {"cycle-a": (os.getpid(), START), "cycle-b": (os.getpid(), START)}

    def claim(path, executor):
        g.claim_card(Path(path).stem, log=str(log), session=executor, tracker_dir=str(tracker), now=NOW,
                     sibling=sib, ps=lambda _pid: (0, START), self_anchor=anchors[executor])

    class S:
        pass
    s = S()
    s.tmp, s.tracker, s.claim, s.sent = tmp_path, tracker, claim, []
    s.obox = tmp_path / "data" / "intake_outbox.json"
    s.notify = lambda text: s.sent.append(text) or True
    s.notes = tmp_path / "inbox"
    return s


def _submit(s, text, sid, at=NOW):
    body = {"text": text, "kind": "task", "submission_id": sid}
    # сцена — записи ВЛАДЕЛЬЦА: происхождение задаёт сервер (проверенная подпись Access), не поле задним числом
    prov = mi.provenance_for("public", verified_email="owner@example.org", owner_emails=("owner@example.org",))
    res = mi.submit(json.dumps(body).encode("utf-8"), actor="local", tracker_dir=s.tracker, now=at,
                    provenance=prov)
    card = s.tracker / res["card"]
    assert _fm(card).get("author") == "owner"
    return card


def _intake(s, at=NOW):
    return oi.run_note_intake(at, tracker_dir=s.tracker, repo_root=s.tmp, notify=s.notify,
                              history=lambda _b: {"verdict": "NEW", "response": ""}, ingest=False)


def _dispatch(s, executor="cycle-a"):
    return cd.dispatch(executor=executor, tracker_dir=s.tracker, claim=s.claim, now=NOW,
                       outbox_path=s.obox, notify=s.notify)


def _fm(p):
    return ca.parse_frontmatter(Path(p).read_text(encoding="utf-8"))


def _accepted(s, text=f"Сверить манифест контрактов. проба: {SPEC}", sid="dispatch-0001", at=NOW):
    card = _submit(s, text, sid, at)
    _intake(s)
    assert _fm(card)["status"] == "new" and _fm(card).get("intake_seen")
    s.sent.clear()
    return card


# ── выбор исполнителя ───────────────────────────────────────────────────────────────────────────────
def test_accepted_cockpit_task_is_selected_exactly_once(scene):
    card = _accepted(scene)
    res = _dispatch(scene)
    fm = _fm(card)
    assert res["taken"] == str(card) and res["probe"] == SPEC
    assert fm["status"] == "in-progress" and fm["claimed_by"] == "cycle-a" and fm["acceptance_probe"] == SPEC
    before = card.read_text(encoding="utf-8")
    again = _dispatch(scene)                                     # следующий цикл / повторная доставка
    other = _dispatch(scene, executor="cycle-b")                 # второй оркестратор
    assert again["taken"] is None and other["taken"] is None
    assert card.read_text(encoding="utf-8") == before            # ни строки не переписано
    assert scene.sent == []


def test_card_not_yet_accepted_by_intake_is_not_selected(scene):
    card = _submit(scene, f"проба: {SPEC}", "dispatch-0002")       # приём ещё не прошёл
    assert _dispatch(scene) == {"taken": None, "probe": None, "no_probe": [], "refused": []}
    assert _fm(card)["status"] == "new" and "claimed_by" not in _fm(card)


def test_oldest_first_and_at_most_one_per_pass(scene):
    old = _submit(scene, f"старшая. проба: {SPEC}", "dispatch-0003", at=NOW - timedelta(minutes=30))
    new = _submit(scene, f"младшая. проба: {SPEC}", "dispatch-0004")
    _intake(scene)
    assert _dispatch(scene)["taken"] == str(old)
    assert _fm(new)["status"] == "new"
    assert _dispatch(scene, executor="cycle-b")["taken"] == str(new)


def test_unprobeable_task_is_never_done_and_says_why_once(scene):
    card = _accepted(scene, text="Посмотри, всё ли нормально с сайтом", sid="dispatch-0005")
    res = _dispatch(scene)
    fm = _fm(card)
    assert res["taken"] is None and res["no_probe"] == [card.name]
    assert fm["status"] == "new" and "claimed_by" not in fm and "verified_by_probe" not in fm
    assert fm["acceptance_verdict"] == "no_probe" and fm[cd.DISPATCH_FIELD] == cd.NO_PROBE
    assert fm["acceptance_reason"] == cl.REASON_RU["no_probe"][0]
    assert fm["acceptance_next"] == cd.NEXT_NO_PROBE and "проба: <имя>" in fm["acceptance_next"]
    assert len(scene.sent) == 1 and "ещё не принята" in scene.sent[0] and "Следующий шаг" in scene.sent[0]
    before = card.read_text(encoding="utf-8")
    assert _dispatch(scene)["no_probe"] == []                     # второй прогон — no-op
    assert card.read_text(encoding="utf-8") == before and len(scene.sent) == 1


@pytest.mark.parametrize("text,why", [
    ("Сделай. проба: no_such_probe_name", "не годится"),
    (f"проба: {SPEC} или проба: ci_main_verdict_green", "несколько проб"),
])
def test_invalid_or_ambiguous_probe_is_no_probe_not_a_guess(scene, text, why):
    card = _accepted(scene, text=text, sid="dispatch-0006")
    assert _dispatch(scene)["no_probe"] == [card.name]
    assert why in _fm(card)["acceptance_detail"] and _fm(card)["status"] == "new"


def test_declaring_a_probe_later_rearms_the_card(scene):
    card = _accepted(scene, text="Задача без мерки", sid="dispatch-0007")
    _dispatch(scene)
    q.set_acceptance_probe(card, SPEC)                            # `orchestrator_queue.py probe`
    res = _dispatch(scene)
    assert res["taken"] == str(card) and _fm(card)["status"] == "in-progress"


# ── после сессии: «сделано» ставит только проба ─────────────────────────────────────────────────────
def test_settle_closes_only_on_satisfied_with_one_notice(scene):
    card = _accepted(scene)
    _dispatch(scene)
    r = cd.settle(card, executor="cycle-a", now=NOW, runner=lambda _s: (ca.SATISFIED, "ok"),
                  outbox_path=scene.obox, notify=scene.notify)
    fm = _fm(card)
    assert r["action"] == "closed" and fm["status"] == "done" and fm["verified_by_probe"] == SPEC
    assert len(scene.sent) == 1 and "сделано и проверено" in scene.sent[0]
    cd.settle(card, executor="cycle-a", now=NOW, outbox_path=scene.obox, notify=scene.notify)
    assert len(scene.sent) == 1


@pytest.mark.parametrize("verdict", [ca.NOT_SATISFIED, ca.UNMEASURED])
def test_settle_unsatisfied_blocks_with_reason_never_done(scene, verdict):
    card = _accepted(scene)
    _dispatch(scene)
    r = cd.settle(card, executor="cycle-a", now=NOW, runner=lambda _s: (verdict, "замер"),
                  outbox_path=scene.obox, notify=scene.notify)
    fm = _fm(card)
    assert r["action"] == "blocked" and fm["status"] == "blocked" and "verified_by_probe" not in fm
    assert fm["acceptance_next"] == cd.NEXT_AFTER_CYCLE and verdict in fm["acceptance_detail"]
    assert len(scene.sent) == 1 and "ещё не принята" in scene.sent[0]
    assert _dispatch(scene)["taken"] is None                       # второго исполнения нет


def test_settle_does_not_touch_a_card_of_another_executor(scene):
    card = _accepted(scene)
    _dispatch(scene)
    before = card.read_text(encoding="utf-8")
    r = cd.settle(card, executor="cycle-b", now=NOW, runner=lambda _s: (ca.NOT_SATISFIED, "x"),
                  outbox_path=scene.obox, notify=scene.notify)
    assert r["action"] == "untouched" and card.read_text(encoding="utf-8") == before


# ── потерянная побудка приёма ───────────────────────────────────────────────────────────────────────
def test_lost_wake_is_rewoken_after_threshold_only(scene):
    stale = _submit(scene, f"проба: {SPEC}", "dispatch-0008", at=NOW - timedelta(minutes=20))
    _submit(scene, "свежая запись", "dispatch-0009", at=NOW - timedelta(minutes=2))
    wake = scene.notes / mi.WAKE_FILE
    assert not wake.exists()                                       # побудки не было (сцена без wake_dir)
    res = cd.rewake(scene.tracker, scene.notes, now=NOW)
    assert res == {"stale": [stale.name], "woken": True} and wake.exists()


def test_nothing_to_rewake_when_intake_has_seen_everything(scene):
    _accepted(scene, at=NOW - timedelta(hours=3))
    assert cd.rewake(scene.tracker, scene.notes, now=NOW) == {"stale": [], "woken": None}
    assert not (scene.notes / mi.WAKE_FILE).exists()


def test_unreadable_submission_time_counts_as_stale_not_fresh(scene):
    card = _submit(scene, "запись", "dispatch-0010")
    cl._set_fields(card, {"submitted_at": "когда-то"})
    assert cd.stale_unseen(scene.tracker, now=NOW) == [card.name]


def test_lost_wake_then_double_intake_and_double_dispatch_execute_once(scene):
    """Потеря побудки → страховка будит → приём срабатывает ДВАЖДЫ (коалесценция + запоздалое
    событие) → выбор зовут два цикла: одно «создал задачу», одно взятие, одна карточка."""
    card = _submit(scene, f"проба: {SPEC}", "dispatch-0011", at=NOW - timedelta(minutes=15))
    assert cd.rewake(scene.tracker, scene.notes, now=NOW)["stale"] == [card.name]
    _intake(scene)
    _intake(scene)
    assert sum("Создал задачу" in t for t in scene.sent) == 1
    assert cd.rewake(scene.tracker, scene.notes, now=NOW)["stale"] == []
    assert _dispatch(scene)["taken"] == str(card)
    assert _dispatch(scene, executor="cycle-b")["taken"] is None
    assert len(list(scene.tracker.glob("inbox-*.md"))) == 1


# ── проводка: обёртка цикла ─────────────────────────────────────────────────────────────────────────
_STUB = '''import json, sys
from pathlib import Path
CALLS = Path({calls!r})
with CALLS.open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
cmd = sys.argv[1]
if cmd == "dispatch":
    rc = {rc}
    a = sys.argv
    if rc == 3:
        Path(a[a.index("--card-out") + 1]).write_text("/abs/inbox-stub.md")
        print("ЗАПИСЬ ИЗ ПУЛЬТА ВЗЯТА (заглушка) ", end="")
    if rc == 1:
        raise RuntimeError("заглушка упала")
    sys.exit(rc)
sys.exit(0)
'''


_GNU_MKTEMP = r"""#!/bin/bash
# Поведение GNU coreutils mktemp (ubuntu-latest): шаблон без трёх X подряд — отказ.
last="${@: -1}"
if [ $# -eq 0 ] || [ "${last#-}" != "$last" ]; then exec /usr/bin/mktemp "$@"; fi
case "$last" in *XXX*) exec /usr/bin/mktemp "$@" ;; esac
echo "mktemp: too few X's in template '$last'" >&2
exit 1
"""


def _wrapper_sandbox(tmp_path: Path, dispatch_rc: int, gnu_mktemp: bool = False):
    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(_REPO / "scripts" / "lib" / "starvation_verdict.sh", root / "scripts" / "lib")
    shutil.copy2(_REPO / "scripts" / "claude_run_with_timeout.py", root / "scripts")
    guard = root / "scripts" / "check_owner_order_starvation.py"
    guard.write_text("print('\\u2705 голодающих critical-приказов владельца (>24ч) не найдено')\n")
    pkg = root / "spa_core" / "owner_queue"
    pkg.mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    calls = tmp_path / "calls.jsonl"
    (pkg / "cockpit_dispatch.py").write_text(_STUB.format(calls=str(calls), rc=dispatch_rc))
    prompt_file = tmp_path / "prompt.txt"
    fake = tmp_path / "fake_claude.sh"
    fake.write_text(f"#!/bin/bash\nprintf '%s' \"$2\" > {prompt_file}\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    src = (_REPO / "scripts" / "agent_orchestrator.sh").read_text()
    src = re.sub(r'^REPO_ROOT=.*$', f'REPO_ROOT="{root}"', src, count=1, flags=re.M)
    src = re.sub(r'^PYTHON=.*$', f'PYTHON="{sys.executable}"', src, count=1, flags=re.M)
    src = re.sub(r'^CLAUDE_BIN=.*$', f'CLAUDE_BIN="{fake}"', src, count=1, flags=re.M)
    if gnu_mktemp:
        # обёртка сама ставит системные каталоги В НАЧАЛО PATH — подмена идёт в ту же строку
        shim = tmp_path / "gnu_bin"
        shim.mkdir()
        (shim / "mktemp").write_text(_GNU_MKTEMP)
        (shim / "mktemp").chmod(0o755)
        src, n = re.subn(r'^export PATH="', f'export PATH="{shim}:', src, count=1, flags=re.M)
        assert n == 1, "строка export PATH обёртки не найдена — подмена mktemp не встала"
    w = tmp_path / "wrapper.sh"
    w.write_text(src)
    env = dict(os.environ, SPA_ORCHESTRATOR_ARMED="1", SPA_ORCHESTRATOR_LOG_SUFFIX="_test_" + tmp_path.name)
    env.pop("SPA_SESSION_ID", None)
    proc = subprocess.run(["/bin/bash", str(w)], env=env, capture_output=True, text=True, timeout=120)
    rows = [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
    prompt = prompt_file.read_text() if prompt_file.exists() else None
    return proc, rows, prompt


def test_wrapper_puts_taken_record_first_and_settles_it_after_the_session(tmp_path):
    proc, rows, prompt = _wrapper_sandbox(tmp_path, 3)
    assert prompt is not None, proc.stderr[-1500:]
    assert prompt.startswith("ЗАПИСЬ ИЗ ПУЛЬТА ВЗЯТА"), prompt[:200]
    assert prompt.index("ЗАПИСЬ ИЗ ПУЛЬТА") < prompt.index("Ты — оркестратор SPA")
    cmds = [r[0] for r in rows]
    assert cmds == ["rewake", "dispatch", "settle"], cmds
    disp, settle = rows[1], rows[2]
    executor = disp[disp.index("--executor") + 1]
    assert executor.startswith("cycle-")
    assert settle[settle.index("--card") + 1] == "/abs/inbox-stub.md"
    assert settle[settle.index("--executor") + 1] == executor       # тот же исполнитель


def test_wrapper_takes_the_record_with_gnu_mktemp_too(tmp_path):
    """CI (Linux, GNU mktemp) — та же обёртка, тот же исход, что на Mac (прогон 39003158532, шард 11)."""
    proc, rows, prompt = _wrapper_sandbox(tmp_path, 3, gnu_mktemp=True)
    assert prompt is not None, proc.stderr[-1500:]
    assert prompt.startswith("ЗАПИСЬ ИЗ ПУЛЬТА ВЗЯТА"), prompt[:300]
    assert [r[0] for r in rows] == ["rewake", "dispatch", "settle"]


def test_wrapper_without_a_record_leaves_the_prompt_unchanged_and_settles_nothing(tmp_path):
    proc, rows, prompt = _wrapper_sandbox(tmp_path, 0)
    assert prompt is not None and prompt.startswith("Ты — оркестратор SPA"), (prompt or proc.stderr)[:300]
    assert [r[0] for r in rows] == ["rewake", "dispatch"]


def test_wrapper_names_a_crashed_dispatcher_unmeasured_not_silence(tmp_path):
    proc, rows, prompt = _wrapper_sandbox(tmp_path, 1)
    assert prompt is not None
    head = prompt.split("Ты — оркестратор")[0]
    assert "НЕ ИЗМЕРЕН" in head and "ВЗЯТА" not in head


def test_my_records_shows_a_record_without_probe_as_not_taken_with_reason():
    from spa_core.studio_os import owner_view as ov
    # отметка приёма — только «приём видел»; её значение не предмет теста, поэтому от NOW, а не
    # литерал даты (литерал рядом со словом свежести красил храповик замороженных дат на CI)
    r = {"status": "new", "intake_seen": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "acceptance_verdict": "no_probe",
         "acceptance_reason": "в записи не объявлена проба", "acceptance_next": "добавьте строку «проба: <имя>»"}
    o = ov._record_outcome(r)
    assert o["kind"] == "not_accepted" and o["reason"] and o["next_step"]
    assert "ждёт исполнителя" not in o["text"]
    assert ov._record_outcome({"status": "new", "intake_seen": "x"})["kind"] == "accepted"
