"""Задания, закрытые фантомами упавшего классификатора (авария 11.08.2026), — и ничего сверх.

Опасностей у инструмента две, и обе — про полномочия:
  * закрыть или изменить карточку РЕШЕНИЯ ВЛАДЕЛЬЦА (фантом — именно такая карточка; гейт
    ADR-551 запрещает агенту закрывать её без записанного ответа владельца, инв. #14);
  * переоткрыть задание, связь которого с фантомом не доказана.
До 2026-10-21 `--apply` сначала переоткрывал задания и неатомарно дописывал фантом, а потом
получал отказ гейта — половина операции оставалась в трекере. Тесты ниже требуют обратного
порядка: отказ — до первой записи, и целевое дерево после отказа байт-в-байт то же.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "repair_phantom_intake_cards", _ROOT / "scripts" / "repair_phantom_intake_cards.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

_OUTAGE = "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>."


def _phantom(tracker: Path, source_title: str, *, asked: str = _OUTAGE,
             status: str = "needs-owner", source: str = "intake",
             title: str | None = None, quote: str | None = None,
             card_type: str = "owner-decision", name: str | None = None) -> Path:
    p = tracker / (name or f"owner-decision-{abs(hash(source_title)) % 10**8}.md")
    q = quote if quote is not None else f"сделай штуку: {source_title}"
    p.write_text(
        "---\n"
        f"trackerStatus:\n  type: {card_type}\n"
        f'title: "{title if title is not None else "Уточнение по заметке: " + source_title}"\n'
        f"status: {status}\n"
        f"source: {source}\n"
        "created: 2026-08-11\n"
        "---\n\n"
        "## Что случилось и почему это важно\nПришло сообщение, непонятно — вопрос это или задача.\n\n"
        f"Текст: «{q}»\n\n"
        f"## Что от тебя нужно\n{asked}\n\n"
        "## Как понять, что готово\nТы уточнил.\n",
        encoding="utf-8")
    return p


def _inbox(tracker: Path, title: str, status: str = "done", *, text: str | None = None,
           card_type: str = "inbox", name: str | None = None) -> Path:
    p = tracker / (name or f"inbox-{abs(hash(title)) % 10**8}.md")
    p.write_text(
        "---\n"
        f"trackerStatus:\n  type: {card_type}\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        "created: 2026-08-11\n"
        "---\n\n"
        f"## Задание (из Telegram)\n\n{text if text is not None else 'сделай штуку: ' + title}\n",
        encoding="utf-8")
    return p


@pytest.fixture()
def rec_root(tmp_path):
    """Каталог слепков — свой у теста и ВНЕ проверяемого дерева `tmp_path`."""
    d = tmp_path.parent / f"rec_{tmp_path.name}"
    d.mkdir()
    return d


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


def _status(p: Path) -> str:
    return R._fm_str(R._fm(p.read_text(encoding="utf-8")), "status")


def _tree(root: Path) -> dict:
    """Каждый путь под `root` (включая скрытые и каталоги) → sha256 содержимого / «dir»."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            out[os.path.relpath(os.path.join(dirpath, d), root)] = "dir"
        for f in filenames:
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, root)] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
    return out


# ── что скрипт ОБЯЗАН сделать ────────────────────────────────────────────────

def test_source_reopened_and_phantom_left_for_the_owner(tracker):
    src = _inbox(tracker, "ADR-070.2: канон трека коммитится циклом", status="done")
    ph = _phantom(tracker, "ADR-070.2: канон трека коммитится циклом")
    ph_bytes = ph.read_bytes()

    res = R.repair(tracker, apply=True)

    assert res["exit"] == R.EXIT_OK
    assert res["phantoms_found"] == 1
    assert res["phantoms_closed"] == 0, "решение владельца агент не закрывает (инв. #14, ADR-551)"
    assert res["sources_reopened"] == 1
    assert _status(src) == "new", "реальное задание должно вернуться в работу"
    assert ph.read_bytes() == ph_bytes, "фантом — карточка владельца: ни байта не меняется"


def test_phantom_gets_no_note_and_no_status(tracker):
    """Прежняя версия дописывала фантому «Закрыто автоматически» — запись в карточку владельца."""
    _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")

    R.repair(tracker, apply=True)

    body = ph.read_text(encoding="utf-8")
    assert "Закрыто автоматически" not in body
    assert _status(ph) == "needs-owner"


def test_empty_output_signature_also_recognised(tracker):
    src = _inbox(tracker, "Другое задание", status="done")
    _phantom(tracker, "Другое задание",
             asked="Пустой ответ. Переформулируй или пришли как /task <текст>.")

    res = R.repair(tracker, apply=True)
    assert res["phantoms_found"] == 1
    assert res["sources_reopened"] == 1
    assert _status(src) == "new"


def test_mass_case_all_of_them(tracker):
    """Миниатюра 11.08: все задания пачки открываются, все фантомы остаются владельцу."""
    srcs = [_inbox(tracker, f"Задание {i}", status="done") for i in range(7)]
    phs = [_phantom(tracker, f"Задание {i}") for i in range(7)]
    before = {p: p.read_bytes() for p in phs}

    res = R.repair(tracker, apply=True)

    assert res["phantoms_found"] == 7
    assert res["sources_reopened"] == 7
    assert all(_status(s) == "new" for s in srcs)
    assert all(p.read_bytes() == b for p, b in before.items())


def test_permitted_write_changes_only_the_status_and_keeps_history(tracker):
    """Разрешённая запись: строка `status:` + запись следа; тело и остальной frontmatter — те же."""
    src = _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")
    before = src.read_text(encoding="utf-8")

    R.repair(tracker, apply=True)

    after = src.read_text(encoding="utf-8")
    from spa_core.owner_queue.status_audit import read_trail
    trail = read_trail(after)
    assert trail and trail[-1].get("old") == "done" and trail[-1].get("new") == "new"
    assert R._body(after) == R._body(before), "тело задания не меняется"
    kept = [ln for ln in before.splitlines() if not ln.startswith("status:")]
    assert all(ln in after.splitlines() for ln in kept), "прежние строки frontmatter сохранены"


# ── чего скрипт делать НЕ ДОЛЖЕН ─────────────────────────────────────────────

def test_real_owner_question_is_never_touched(tracker):
    """Настоящий вопрос МОДЕЛИ по существу — не фантом, трогать запрещено."""
    ph = _phantom(tracker, "Что-то важное",
                  asked="Это про сайт или про агентов? Уточни, пожалуйста.")
    b = ph.read_bytes()

    res = R.repair(tracker, apply=True)

    assert res["phantoms_found"] == 0
    assert ph.read_bytes() == b


def test_handwritten_owner_card_is_never_touched(tracker):
    """Карточка владельца не от интейка (source: nimbalyst) — вне зоны действия."""
    src = _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание", source="nimbalyst")

    assert R.repair(tracker, apply=True)["phantoms_found"] == 0
    assert _status(ph) == "needs-owner"
    assert _status(src) == "done", "без доказанного фантома задание не трогается"


def test_card_without_the_title_prefix_is_never_touched(tracker):
    ph = _phantom(tracker, "Задание", title="Живой вопрос про лимит цепочки")

    assert R.repair(tracker, apply=True)["phantoms_found"] == 0
    assert _status(ph) == "needs-owner"


def test_already_answered_card_is_never_touched(tracker):
    """Ответил владелец (owner-done) — карточка не наша, даже с подписью аварии."""
    src = _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание", status="owner-done")

    assert R.repair(tracker, apply=True)["phantoms_found"] == 0
    assert _status(ph) == "owner-done"
    assert _status(src) == "done"


def test_file_name_alone_does_not_make_a_phantom(tracker):
    """Имя `owner-decision-*` без такого типа во frontmatter — не основание."""
    src = _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание", card_type="inbox", name="owner-decision-fake.md")

    res = R.repair(tracker, apply=True)
    assert res["phantoms_found"] == 0
    assert _status(src) == "done"


def test_source_still_open_is_not_disturbed(tracker):
    """Исходник, который НЕ закрывали, менять не за что — он уже в работе."""
    src = _inbox(tracker, "Задание", status="in-progress")
    _phantom(tracker, "Задание")
    b = src.read_bytes()

    res = R.repair(tracker, apply=True)

    assert res["exit"] == R.EXIT_OK
    assert res["sources_reopened"] == 0
    assert src.read_bytes() == b


def test_missing_source_is_reported_not_silently_dropped(tracker):
    """Исходника нет ⇒ это НАХОДКА в отчёте, а не тихий пропуск."""
    _phantom(tracker, "Задание без исходника")

    res = R.repair(tracker, apply=True)

    assert res["sources_not_found"] == 1
    assert "Задание без исходника" in res["orphaned"]


def test_dry_run_writes_nothing(tmp_path, tracker):
    _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")
    before = _tree(tmp_path)

    res = R.repair(tracker, apply=False)

    assert res["phantoms_found"] == 1
    assert res["sources_to_reopen"] and res["sources_reopened"] == 0
    assert _tree(tmp_path) == before


def test_rerun_is_idempotent(tmp_path, tracker):
    _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")

    R.repair(tracker, apply=True)
    once = _tree(tmp_path)
    second = R.repair(tracker, apply=True)

    assert second["exit"] == R.EXIT_OK
    assert second["sources_reopened"] == 0, "открытое задание второй раз не трогается"
    assert _tree(tmp_path) == once


# ── отказ ДО первой записи: дерево байт-в-байт то же ─────────────────────────

def _forbid_writes(monkeypatch):
    """Любая попытка записать во время отказа — падение теста, а не тихая запись."""
    calls = []

    def boom(*args, **_kwargs):
        calls.append(args)
        raise AssertionError(f"запись до решения гейта: {args!r}")

    import spa_core.owner_queue.queue as q
    monkeypatch.setattr(q, "set_status", boom)
    monkeypatch.setattr(R, "_restore", boom)
    monkeypatch.setattr(R, "_write_durable", boom)
    import spa_core.owner_queue.status_audit as sa
    monkeypatch.setattr(sa, "record_status_write", boom)
    return calls


def _refusal_case_ambiguous(tracker):
    a = _inbox(tracker, "Задание", status="done", name="inbox-a.md")
    _inbox(tracker, "Задание", status="done", name="inbox-b.md")
    _phantom(tracker, "Задание")
    # и вторая, вполне разрешённая пара — отказ обязан забрать ВСЮ операцию
    ok = _inbox(tracker, "Чистое", status="done")
    _phantom(tracker, "Чистое")
    return a, ok


@pytest.mark.parametrize("case", ["ambiguous_title", "quote_not_in_source",
                                  "owner_card_under_inbox_name", "inbox_typed_under_owner_name"])
def test_refusal_on_apply_leaves_the_target_tree_byte_identical(tmp_path, tracker, monkeypatch, case):
    (tmp_path / ".git").mkdir()      # дерево опознаётся: журналу переходов и операций есть КУДА писать
    if case == "ambiguous_title":
        _refusal_case_ambiguous(tracker)
    elif case == "quote_not_in_source":
        _inbox(tracker, "Задание", status="done", text="совсем другой текст")
        _phantom(tracker, "Задание")
        _inbox(tracker, "Чистое", status="done")
        _phantom(tracker, "Чистое")
    elif case == "owner_card_under_inbox_name":
        _inbox(tracker, "Задание", status="done", card_type="owner-decision", name="inbox-disguised.md")
        _phantom(tracker, "Задание")
    else:
        _inbox(tracker, "Задание", status="done", name="owner-decision-typed-inbox.md")
        _phantom(tracker, "Задание")
    before = _tree(tmp_path)
    calls = _forbid_writes(monkeypatch)

    rc = R.main(["--tracker-dir", str(tracker), "--apply", "--json"])

    assert rc == R.EXIT_REFUSED
    assert calls == [], "до решения гейта не было ни одной попытки записи"
    assert _tree(tmp_path) == before, "ни новых, ни изменённых, ни удалённых путей"


def test_refusal_names_every_reason_and_the_whole_operation(tracker):
    _refusal_case_ambiguous(tracker)
    res = R.repair(tracker, apply=True)
    assert res["exit"] == R.EXIT_REFUSED
    assert res["sources_reopened"] == 0
    assert any("неоднозначна" in r for r in res["refusals"])


def test_gate_refusal_from_the_lifecycle_table_stops_everything(tmp_path, tracker, monkeypatch):
    """Тот же гейт, что у set_status, спрашивается ДО записи: его отказ — отказ всей операции."""
    _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")
    import spa_core.owner_queue.queue as q

    def refuse(*_args, **_kwargs):
        raise q.LifecycleRefused("table says no")

    monkeypatch.setattr(q, "check_lifecycle", refuse)
    before = _tree(tmp_path)
    calls = _forbid_writes(monkeypatch)

    res = R.repair(tracker, apply=True)

    assert res["exit"] == R.EXIT_REFUSED and "table says no" in " ".join(res["refusals"])
    assert calls == [] and _tree(tmp_path) == before


def test_change_between_plan_and_write_refuses_before_writing(tracker, rec_root):
    a = _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")
    plan = R.build_plan(tracker)
    a.write_text(a.read_text(encoding="utf-8") + "\nдописал другой писатель\n", encoding="utf-8")
    changed = a.read_bytes()

    out = R.apply_plan(plan, recovery_root=rec_root)

    assert out["exit"] == R.EXIT_REFUSED
    assert a.read_bytes() == changed, "чужая правка не перезаписана"
    assert list(rec_root.iterdir()) == [], "отказ не заводит журнал операции"


# ── сбой на каждом шаге: до операции либо полный результат, третьего нет ──────

def _three(tracker):
    srcs = [_inbox(tracker, f"Задание {i}", status="done") for i in range(3)]
    [_phantom(tracker, f"Задание {i}") for i in range(3)]
    return srcs


@pytest.mark.parametrize("fail_at", [0, 1, 2])
@pytest.mark.parametrize("after_replace", [False, True])
def test_failure_at_each_step_rolls_back_to_the_exact_original(tmp_path, tracker, rec_root, fail_at, after_replace):
    _three(tracker)
    before = _tree(tmp_path)
    real = R._default_write
    n = {"i": 0}

    def flaky(path, new_status):
        i = n["i"]
        n["i"] += 1
        if i == fail_at and not after_replace:
            raise OSError(f"сбой ДО замены файла {i}")
        real(path, new_status)
        if i == fail_at and after_replace:
            raise OSError(f"сбой ПОСЛЕ замены файла {i}")

    res = R.repair(tracker, apply=True, write=flaky, recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    assert res["applied"] is False and res["sources_reopened"] == 0
    assert _tree(tmp_path) == before, "состояние до операции — байт в байт"
    ops = list(rec_root.iterdir())
    assert len(ops) == 1
    assert json.loads((ops[0] / "manifest.json").read_text())["state"] == "rolled_back"


def test_unconfirmed_rollback_keeps_recovery_material_and_asks_for_a_human(tmp_path, tracker, rec_root):
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    real = R._default_write
    n = {"i": 0}

    def flaky(path, new_status):
        n["i"] += 1
        real(path, new_status)
        if n["i"] == 2:
            raise OSError("сбой после второй замены")

    def broken_restore(_path, _data):
        raise OSError("диск отказал при откате")

    res = R.repair(tracker, apply=True, write=flaky, restore=broken_restore,
                   recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_MANUAL
    assert "ручное вмешательство" in res["reason"]
    rec = Path(res["op"])
    manifest = json.loads((rec / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "needs_manual"
    assert len(manifest["files"]) == 3
    for m in manifest["files"]:
        data = (rec / f"{m['index']:03d}.orig").read_bytes()
        assert hashlib.sha256(data).hexdigest() == m["orig_sha"]
        assert data == originals[Path(m["path"])]
    again = R.repair(tracker, apply=True, recovery_root=str(rec_root))
    assert again["exit"] == R.EXIT_MANUAL, "пока человек не разобрался — новых записей нет"


def test_success_is_the_full_expected_result(tmp_path, tracker, rec_root):
    srcs = _three(tracker)
    res = R.repair(tracker, apply=True, recovery_root=str(rec_root))
    assert res["exit"] == R.EXIT_OK and res["sources_reopened"] == 3
    assert all(_status(s) == "new" for s in srcs)
    ops = list(rec_root.iterdir())
    assert len(ops) == 1, "журнал операции остаётся как запись о сделанном"
    assert json.loads((ops[0] / "manifest.json").read_text())["state"] == "committed"


# ── журнал переходов в опознанном дереве (append-only) ───────────────────────

@pytest.fixture()
def git_tree(tmp_path):
    """Изолированное дерево, которое `status_audit.repo_root_for` опознаёт как git-дерево."""
    (tmp_path / ".git").mkdir()
    t = tmp_path / "nimbalyst-local" / "tracker"
    t.mkdir(parents=True)
    return tmp_path, t


def _audit(root: Path) -> list[dict]:
    p = root / "data" / "tracker_status_audit.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_rollback_restores_the_card_and_appends_the_reverse_to_the_audit(git_tree):
    root, tracker = git_tree
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    prior = {"card": "earlier.md", "old": "new", "new": "done", "source": "someone"}
    (root / "data").mkdir()
    (root / "data" / "tracker_status_audit.jsonl").write_text(json.dumps(prior) + "\n", encoding="utf-8")
    real = R._default_write
    n = {"i": 0}

    def fail_after_first(path, new_status):
        real(path, new_status)
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("сбой после успешного set_status")

    res = R.repair(tracker, apply=True, write=fail_after_first)

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    assert all(p.read_bytes() == b for p, b in originals.items()), "карточки — исходные байты"
    assert all(_status(p) == "done" for p in srcs)
    log = _audit(root)
    assert log[0] == prior, "журнал не очищен и не переписан: прежняя строка на месте"
    moved = [e for e in log[1:]]
    assert [(e["old"], e["new"]) for e in moved] == [("done", "new"), ("new", "done")]
    assert moved[0]["source"] == "queue.set_status"
    assert moved[1]["source"] == "repair_phantom_intake_cards/rollback"
    assert moved[0]["card"] == moved[1]["card"], "прямой и обратный — про одну и ту же карточку"
    touched = {e["card"] for e in moved}
    assert len(touched) == 1, "в журнале ровно то, что было сделано: одна запись и один откат"


# ── остановка ПРОЦЕССА между заменами и следующий запуск ─────────────────────

_DRIVER = r'''
import importlib.util, os, signal, sys
from pathlib import Path
script, tracker, kill_at, when = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
spec = importlib.util.spec_from_file_location("r", script)
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
real = R._default_write
n = {"i": 0}
def write(path, new_status):
    i = n["i"]; n["i"] += 1
    if i == kill_at and when == "before":
        os.kill(os.getpid(), signal.SIGKILL)
    real(path, new_status)
    if i == kill_at and when == "after":       # файл заменён, журнал операции ещё не знает
        os.kill(os.getpid(), signal.SIGKILL)
R.repair(tracker, apply=True, write=write)
print("NOT KILLED")
'''


def _run(args, cwd):
    import subprocess
    return subprocess.run([sys.executable, *args], cwd=str(cwd), capture_output=True, text=True,
                          timeout=120)


def _cli(tracker, *extra):
    return _run([str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
                 "--tracker-dir", str(tracker), "--json", *extra], _ROOT)


@pytest.mark.parametrize("kill_at", [0, 1, 2])
@pytest.mark.parametrize("when", ["before", "after"])
def test_killed_process_is_detected_and_undone_before_new_cards(tmp_path, git_tree, kill_at, when):
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    driver = tmp_path.parent / f"driver_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")

    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), str(kill_at), when], _ROOT)
    assert r.returncode == -signal.SIGKILL, (r.returncode, r.stdout, r.stderr)

    changed = [p for p in srcs if p.read_bytes() != originals[p]]
    assert len(changed) == kill_at + (1 if when == "after" else 0), "что видит читатель после прерывания"
    ops = list((root / "data" / "repair_phantom_recovery").iterdir())
    assert len(ops) == 1
    assert json.loads((ops[0] / "manifest.json").read_text())["state"] == "prepared"

    # ещё одна «новая» пара — она НЕ должна обработаться, пока не разобрана старая операция
    late = _inbox(tracker, "Позднее", status="done")
    _phantom(tracker, "Позднее")

    snap = _tree(root)
    dry = _cli(tracker)
    assert dry.returncode == R.EXIT_UNFINISHED
    assert _tree(root) == snap, "сухой прогон ничего не меняет даже при незавершённой операции"

    rec = _cli(tracker, "--apply")
    assert rec.returncode == R.EXIT_UNFINISHED, rec.stdout + rec.stderr
    assert all(p.read_bytes() == b for p, b in originals.items()), "откат до исходных байтов"
    assert _status(late) == "done", "новые карточки не обработаны до разбора старой операции"
    assert json.loads((ops[0] / "manifest.json").read_text())["state"] == "rolled_back"
    reverse = [e for e in _audit(root) if e["source"].endswith("/recover_after_interrupt")]
    assert len(reverse) == len(changed)

    again = _cli(tracker, "--apply")
    assert again.returncode == R.EXIT_OK, again.stdout + again.stderr
    assert all(_status(p) == "new" for p in [*srcs, late])


def test_foreign_change_after_interrupt_is_not_overwritten(tmp_path, git_tree):
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    driver = tmp_path.parent / f"driver_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "1", "after"], _ROOT)
    assert r.returncode == -signal.SIGKILL
    # цикл успел взять открытое задание в работу — это ЧУЖАЯ правка поверх нашей
    taken = srcs[0]
    taken.write_text(taken.read_text(encoding="utf-8").replace("status: new", "status: in-progress"),
                     encoding="utf-8")
    foreign = taken.read_bytes()

    res = _cli(tracker, "--apply")

    assert res.returncode == R.EXIT_MANUAL, res.stdout
    assert taken.read_bytes() == foreign, "чужая правка не перезаписана откатом"
    assert _cli(tracker, "--apply").returncode == R.EXIT_MANUAL, "до разбора человеком — ничего"


# ── входы — ВСЕ карточки, включая карточки владельца ─────────────────────────

def test_owner_card_changed_between_plan_and_write_refuses(tracker, rec_root):
    _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")
    plan = R.build_plan(tracker)
    ph.write_text(ph.read_text(encoding="utf-8") + "\nвладелец ответил\n", encoding="utf-8")

    out = R.apply_plan(plan, recovery_root=rec_root)

    assert out["exit"] == R.EXIT_REFUSED
    assert list(rec_root.iterdir()) == []


def test_owner_card_changed_during_operation_rolls_back_ours_only(tracker, rec_root):
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    owner = _phantom(tracker, "Посторонний вопрос", asked="Настоящий вопрос владельцу?")
    real = R._default_write
    n = {"i": 0}

    def write_then_owner_answers(path, new_status):
        real(path, new_status)
        n["i"] += 1
        if n["i"] == 1:
            owner.write_text(owner.read_text(encoding="utf-8") + "\nответ владельца\n", encoding="utf-8")

    res = R.repair(tracker, apply=True, write=write_then_owner_answers, recovery_root=str(rec_root))
    answered = owner.read_bytes()

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    assert "другим писателем" in res["reason"]
    assert all(p.read_bytes() == b for p, b in originals.items())
    assert answered.endswith("ответ владельца\n".encode()), "правка владельца не тронута откатом"
