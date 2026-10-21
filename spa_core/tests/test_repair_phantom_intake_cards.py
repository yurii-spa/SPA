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

#: ТЕСТОВАЯ общая блокировка трекера (раунд 3 ARB). В проде такой нет — поэтому `--apply`
#: из CLI отвечает кодом 8; здесь механика транзакции проверяется так, как она будет работать,
#: когда систему снабдят блокировкой, которую берёт КАЖДЫЙ писатель. Файл-замок — вне
#: проверяемых деревьев.
import contextlib
import fcntl
import tempfile

_LOCK_FILE = Path(tempfile.gettempdir()) / "repair_phantom_test_coordination.lock"


@contextlib.contextmanager
def _flock(_tracker=None, lock_file: Path = _LOCK_FILE):
    with open(lock_file, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


COORD = _flock


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

    res = R.repair(tracker, apply=True, coordination=COORD)

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

    R.repair(tracker, apply=True, coordination=COORD)

    body = ph.read_text(encoding="utf-8")
    assert "Закрыто автоматически" not in body
    assert _status(ph) == "needs-owner"


def test_empty_output_signature_also_recognised(tracker):
    src = _inbox(tracker, "Другое задание", status="done")
    _phantom(tracker, "Другое задание",
             asked="Пустой ответ. Переформулируй или пришли как /task <текст>.")

    res = R.repair(tracker, apply=True, coordination=COORD)
    assert res["phantoms_found"] == 1
    assert res["sources_reopened"] == 1
    assert _status(src) == "new"


def test_mass_case_all_of_them(tracker):
    """Миниатюра 11.08: все задания пачки открываются, все фантомы остаются владельцу."""
    srcs = [_inbox(tracker, f"Задание {i}", status="done") for i in range(7)]
    phs = [_phantom(tracker, f"Задание {i}") for i in range(7)]
    before = {p: p.read_bytes() for p in phs}

    res = R.repair(tracker, apply=True, coordination=COORD)

    assert res["phantoms_found"] == 7
    assert res["sources_reopened"] == 7
    assert all(_status(s) == "new" for s in srcs)
    assert all(p.read_bytes() == b for p, b in before.items())


def test_permitted_write_changes_only_the_status_and_keeps_history(tracker):
    """Разрешённая запись: строка `status:` + запись следа; тело и остальной frontmatter — те же."""
    src = _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание")
    before = src.read_text(encoding="utf-8")

    R.repair(tracker, apply=True, coordination=COORD)

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

    res = R.repair(tracker, apply=True, coordination=COORD)

    assert res["phantoms_found"] == 0
    assert ph.read_bytes() == b


def test_handwritten_owner_card_is_never_touched(tracker):
    """Карточка владельца не от интейка (source: nimbalyst) — вне зоны действия."""
    src = _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание", source="nimbalyst")

    assert R.repair(tracker, apply=True, coordination=COORD)["phantoms_found"] == 0
    assert _status(ph) == "needs-owner"
    assert _status(src) == "done", "без доказанного фантома задание не трогается"


def test_card_without_the_title_prefix_is_never_touched(tracker):
    ph = _phantom(tracker, "Задание", title="Живой вопрос про лимит цепочки")

    assert R.repair(tracker, apply=True, coordination=COORD)["phantoms_found"] == 0
    assert _status(ph) == "needs-owner"


def test_already_answered_card_is_never_touched(tracker):
    """Ответил владелец (owner-done) — карточка не наша, даже с подписью аварии."""
    src = _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание", status="owner-done")

    assert R.repair(tracker, apply=True, coordination=COORD)["phantoms_found"] == 0
    assert _status(ph) == "owner-done"
    assert _status(src) == "done"


def test_file_name_alone_does_not_make_a_phantom(tracker):
    """Имя `owner-decision-*` без такого типа во frontmatter — не основание."""
    src = _inbox(tracker, "Задание", status="done")
    _phantom(tracker, "Задание", card_type="inbox", name="owner-decision-fake.md")

    res = R.repair(tracker, apply=True, coordination=COORD)
    assert res["phantoms_found"] == 0
    assert _status(src) == "done"


def test_source_still_open_is_not_disturbed(tracker):
    """Исходник, который НЕ закрывали, менять не за что — он уже в работе."""
    src = _inbox(tracker, "Задание", status="in-progress")
    _phantom(tracker, "Задание")
    b = src.read_bytes()

    res = R.repair(tracker, apply=True, coordination=COORD)

    assert res["exit"] == R.EXIT_OK
    assert res["sources_reopened"] == 0
    assert src.read_bytes() == b


def test_missing_source_is_reported_not_silently_dropped(tracker):
    """Исходника нет ⇒ это НАХОДКА в отчёте, а не тихий пропуск."""
    _phantom(tracker, "Задание без исходника")

    res = R.repair(tracker, apply=True, coordination=COORD)

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

    R.repair(tracker, apply=True, coordination=COORD)
    once = _tree(tmp_path)
    second = R.repair(tracker, apply=True, coordination=COORD)

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

    rc = R.repair(tracker, apply=True, coordination=COORD)["exit"]

    assert rc == R.EXIT_REFUSED
    assert calls == [], "до решения гейта не было ни одной попытки записи"
    assert _tree(tmp_path) == before, "ни новых, ни изменённых, ни удалённых путей"


def test_refusal_names_every_reason_and_the_whole_operation(tracker):
    _refusal_case_ambiguous(tracker)
    res = R.repair(tracker, apply=True, coordination=COORD)
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

    res = R.repair(tracker, apply=True, coordination=COORD)

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
def test_failure_at_each_step_rolls_back_to_the_exact_original(git_tree, rec_root, fail_at, after_replace):
    """Опознанное дерево: и карточки, и журнал переходов обязаны сойтись (код 4)."""
    root, tracker = git_tree
    _three(tracker)
    before = _tree_without_audit(root)
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

    res = R.repair(tracker, apply=True, coordination=COORD, write=flaky, recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    assert res["applied"] is False and res["sources_reopened"] == 0
    assert _tree_without_audit(root) == before, "карточки и дерево — байт в байт как до операции"
    ops = list(rec_root.iterdir())
    assert len(ops) == 1
    m = json.loads((ops[0] / "manifest.json").read_text())
    assert m["state"] == "rolled_back" and m["audit"]["verdict"] == "consistent", m.get("audit")
    changed = fail_at + (1 if after_replace else 0)
    assert len(_audit(root)) == 2 * changed, "по прямому и обратному событию на каждую замену"


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

    res = R.repair(tracker, apply=True, coordination=COORD, write=flaky, restore=broken_restore,
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
    again = R.repair(tracker, apply=True, coordination=COORD, recovery_root=str(rec_root))
    assert again["exit"] == R.EXIT_MANUAL, "пока человек не разобрался — новых записей нет"


def test_success_is_the_full_expected_result(tmp_path, tracker, rec_root):
    srcs = _three(tracker)
    res = R.repair(tracker, apply=True, coordination=COORD, recovery_root=str(rec_root))
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


def _tree_without_audit(root: Path) -> dict:
    """Дерево без журнала переходов: он только дописывается, и сверяется отдельно."""
    t = _tree(root)
    t.pop("data/tracker_status_audit.jsonl", None)
    if t.get("data") == "dir" and not any(k.startswith("data/") for k in t):
        t.pop("data")
    return t


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

    res = R.repair(tracker, apply=True, coordination=COORD, write=fail_after_first)

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
script, tracker, kill_at, when, lock = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
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
import contextlib, fcntl
@contextlib.contextmanager
def coord(_t):
    with open(lock, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
R.repair(tracker, apply=True, write=write, coordination=coord)
print("NOT KILLED")
'''


def _run(args, cwd):
    import subprocess
    return subprocess.run([sys.executable, *args], cwd=str(cwd), capture_output=True, text=True,
                          timeout=120)


_APPLY = r'''
import contextlib, fcntl, importlib.util, json, sys
from pathlib import Path
script, tracker, lock = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location("r", script)
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
@contextlib.contextmanager
def coord(_t):
    with open(lock, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
res = R.repair(tracker, apply=True, coordination=coord)
print(json.dumps(res, ensure_ascii=False, default=str))
sys.exit(res["exit"])
'''


def _apply_coordinated(tracker):
    """`--apply` в ОТДЕЛЬНОМ процессе под тестовой общей блокировкой (CLI её передать не может)."""
    drv = Path(tempfile.gettempdir()) / f"repair_apply_driver_{os.getpid()}.py"
    drv.write_text(_APPLY, encoding="utf-8")
    return _run([str(drv), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
                 str(tracker), str(_LOCK_FILE)], _ROOT)


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
              str(tracker), str(kill_at), when, str(_LOCK_FILE)], _ROOT)
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

    rec = _apply_coordinated(tracker)
    assert all(p.read_bytes() == b for p, b in originals.items()), "откат до исходных байтов"
    assert _status(late) == "done", "новые карточки не обработаны до разбора старой операции"
    reverse = [e for e in _audit(root) if e["source"].endswith("/recover_after_interrupt")]
    assert len(reverse) == len(changed)
    m = json.loads((ops[0] / "manifest.json").read_text())
    if when == "after":
        # Убит ВНУТРИ записи: граница журнала не закрыта ⇒ прямое событие с операцией не связать.
        # Консервативно: код 7 и блокер — даже если похожее событие в журнале есть.
        assert rec.returncode == R.EXIT_AUDIT_UNPROVEN, rec.stdout + rec.stderr
        assert m["state"] == R.AUDIT_UNPROVEN_STATE
        assert any("граница записи не закрыта" in pr for pr in m["audit"]["problems"])
        snap2 = _tree(root)
        again = _apply_coordinated(tracker)
        assert again.returncode == R.EXIT_AUDIT_UNPROVEN, "блокер стоит"
        assert _tree(root) == snap2 and _status(late) == "done"
    else:
        assert rec.returncode == R.EXIT_UNFINISHED, rec.stdout + rec.stderr
        assert m["state"] == "rolled_back"
        again = _apply_coordinated(tracker)
        assert again.returncode == R.EXIT_OK, again.stdout + again.stderr
        assert all(_status(p) == "new" for p in [*srcs, late])


def test_foreign_change_after_interrupt_is_not_overwritten(tmp_path, git_tree):
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    driver = tmp_path.parent / f"driver_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "1", "after", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    # цикл успел взять открытое задание в работу — это ЧУЖАЯ правка поверх нашей
    taken = srcs[0]
    taken.write_text(taken.read_text(encoding="utf-8").replace("status: new", "status: in-progress"),
                     encoding="utf-8")
    foreign = taken.read_bytes()

    res = _apply_coordinated(tracker)

    assert res.returncode == R.EXIT_MANUAL, res.stdout
    assert taken.read_bytes() == foreign, "чужая правка не перезаписана откатом"
    assert _apply_coordinated(tracker).returncode == R.EXIT_MANUAL, "до разбора человеком — ничего"


# ── входы — ВСЕ карточки, включая карточки владельца ─────────────────────────

def test_owner_card_changed_between_plan_and_write_refuses(tracker, rec_root):
    _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")
    plan = R.build_plan(tracker)
    ph.write_text(ph.read_text(encoding="utf-8") + "\nвладелец ответил\n", encoding="utf-8")

    out = R.apply_plan(plan, recovery_root=rec_root)

    assert out["exit"] == R.EXIT_REFUSED
    assert list(rec_root.iterdir()) == []


def test_owner_card_changed_during_operation_rolls_back_ours_only(git_tree, rec_root):
    _root, tracker = git_tree
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

    res = R.repair(tracker, apply=True, coordination=COORD, write=write_then_owner_answers, recovery_root=str(rec_root))
    answered = owner.read_bytes()

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    assert "другим писателем" in res["reason"]
    assert all(p.read_bytes() == b for p, b in originals.items())
    assert answered.endswith("ответ владельца\n".encode()), "правка владельца не тронута откатом"


# ── раунд 3 ARB: без общей блокировки --apply не пишет НИЧЕГО ────────────────

def test_cli_apply_is_blocked_before_any_write(tmp_path, git_tree):
    """Из CLI общую блокировку не передать — код 8, дерево байт в байт, план назван."""
    root, tracker = git_tree
    _three(tracker)
    before = _tree(root)

    r = _cli(tracker, "--apply")

    assert r.returncode == R.EXIT_NO_COORDINATION, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert len(doc["sources_to_reopen"]) == 3, "план прочитан и назван"
    assert doc["applied"] is False and doc["sources_reopened"] == 0
    assert "общей блокировки" in doc["reason"]
    assert _tree(root) == before, "ни карточек, ни data/, ни журнала операции, ни журнала переходов"


def test_library_apply_without_coordination_never_tries_to_write(git_tree, monkeypatch):
    root, tracker = git_tree
    _three(tracker)
    before = _tree(root)
    calls = _forbid_writes(monkeypatch)

    res = R.repair(tracker, apply=True)

    assert res["exit"] == R.EXIT_NO_COORDINATION
    assert calls == [], "до записи даже не дошло"
    assert _tree(root) == before


def test_unfinished_operation_is_not_recovered_without_coordination(tmp_path, git_tree):
    """Восстановление тоже пишет — без общей блокировки оно заблокировано так же."""
    import signal
    root, tracker = git_tree
    _three(tracker)
    driver = tmp_path.parent / f"driver_unf_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "1", "after", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    before = _tree(root)

    cli = _cli(tracker, "--apply")

    assert cli.returncode == R.EXIT_NO_COORDINATION
    assert json.loads(cli.stdout)["unfinished"], "незавершённая операция названа"
    assert _tree(root) == before, "незавершённая операция не тронута — ни откатом, ни записью"


# ── окно ВНУТРИ set_status: между последней сверкой и заменой файла ──────────

def _hook_inside_set_status(monkeypatch, on_first):
    """Подмена `atomic_save_text` в очереди: точка после чтения карточки и до os.replace."""
    import spa_core.owner_queue.queue as q
    real = q.atomic_save_text
    n = {"i": 0}

    def hooked(text, path, *a, **k):
        if n["i"] == 0:
            on_first(Path(path))
        n["i"] += 1
        return real(text, path, *a, **k)

    monkeypatch.setattr(q, "atomic_save_text", hooked)


def test_without_an_honoured_lock_the_window_loses_a_foreign_change(git_tree, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: окно настоящее. Замок, который чужой писатель не берёт, не
    защищает — его правка в окне теряется молча, и сверка хешей этого не видит. Ровно поэтому
    `--apply` без общей блокировки заблокирован."""
    _root, tracker = git_tree
    _three(tracker)
    foreign = "\nправка другого писателя\n"
    _hook_inside_set_status(monkeypatch, lambda p: p.write_text(
        p.read_text(encoding="utf-8") + foreign, encoding="utf-8"))

    res = R.repair(tracker, apply=True, coordination=lambda _t: contextlib.nullcontext())

    assert res["exit"] == R.EXIT_OK
    victim = sorted(tracker.glob("inbox-*.md"))
    assert not any(foreign.strip() in p.read_text(encoding="utf-8") for p in victim), \
        "правка другого писателя потеряна — окно реально"


def test_an_honoured_shared_lock_keeps_the_foreign_change(git_tree, monkeypatch):
    """Общая блокировка, которую берёт и другой писатель: его правка ждёт и ложится ПОВЕРХ."""
    import threading
    import time
    _root, tracker = git_tree
    srcs = _three(tracker)
    owners = {p: p.read_bytes() for p in tracker.glob("owner-decision-*.md")}
    foreign = "правка другого писателя под общей блокировкой"
    state = {}

    def writer(path):
        state["trying"] = True
        with _flock():
            path.write_text(path.read_text(encoding="utf-8") + "\n" + foreign + "\n", encoding="utf-8")

    def on_first(path):
        t = threading.Thread(target=writer, args=(path,))
        t.start()
        state["t"], state["path"] = t, path
        while not state.get("trying"):
            time.sleep(0.01)
        time.sleep(0.2)
        assert foreign not in path.read_text(encoding="utf-8"), "другой писатель ждёт замок"

    _hook_inside_set_status(monkeypatch, on_first)
    res = R.repair(tracker, apply=True, coordination=COORD)
    state["t"].join(10)

    assert res["exit"] == R.EXIT_OK, res
    text = state["path"].read_text(encoding="utf-8")
    assert foreign in text, "правка другого писателя сохранена"
    assert R._fm_str(R._fm(text), "status") == "new", "и наша запись тоже"
    assert all(_status(p) == "new" for p in srcs)
    assert all(p.read_bytes() == b for p, b in owners.items()), "карточки Owner байт в байт"


_DRIVER_IN_WINDOW = r'''
import contextlib, fcntl, importlib.util, os, signal, sys, time
from pathlib import Path
script, tracker, lock, marker, when = sys.argv[1], Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), sys.argv[5]
spec = importlib.util.spec_from_file_location("r", script)
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
import spa_core.owner_queue.queue as q
real = q.atomic_save_text
def hooked(text, path, *a, **k):
    if when == "after":
        real(text, path, *a, **k)
    marker.write_text("in window")
    time.sleep(0.5)                    # другой писатель успевает встать в очередь за замком
    os.kill(os.getpid(), signal.SIGKILL)
q.atomic_save_text = hooked
@contextlib.contextmanager
def coord(_t):
    with open(lock, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
R.repair(tracker, apply=True, coordination=coord)
print("NOT KILLED")
'''


@pytest.mark.parametrize("when", ["before", "after"])
def test_kill_in_the_window_under_the_lock_then_recovery(tmp_path, git_tree, when):
    """Процесс убит ровно в окне, держа общую блокировку. Ядро отпускает замок, другой писатель
    дописывает ту же карточку; следующий запуск НЕ перезаписывает его правку (код 5), карточки
    Owner — исходные байты, журнал операции хранит исходные байты с совпадающим sha256."""
    import signal
    import subprocess as sp
    import threading
    import time
    root, tracker = git_tree
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    owners = {p: p.read_bytes() for p in tracker.glob("owner-decision-*.md")}
    marker = tmp_path.parent / f"marker_{tmp_path.name}"
    driver = tmp_path.parent / f"driver_win_{tmp_path.name}.py"
    driver.write_text(_DRIVER_IN_WINDOW, encoding="utf-8")
    proc = sp.Popen([sys.executable, str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
                     str(tracker), str(_LOCK_FILE), str(marker), when], cwd=str(_ROOT),
                    stdout=sp.PIPE, stderr=sp.PIPE, text=True)
    deadline = time.time() + 60
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert marker.exists(), proc.communicate()
    victim = {}

    def writer():
        with _flock():                                  # ждёт, пока убитый держатель не отпустит замок
            p = sorted(tracker.glob("inbox-*.md"))[0]
            p.write_text(p.read_text(encoding="utf-8") + "\nправка после смерти держателя\n", encoding="utf-8")
            victim["p"], victim["bytes"] = p, p.read_bytes()

    t = threading.Thread(target=writer)
    t.start()
    proc.wait(60)
    t.join(30)
    assert proc.returncode == -signal.SIGKILL
    assert "p" in victim, "замок освобождён смертью держателя"

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_MANUAL, rec.stdout
    assert victim["p"].read_bytes() == victim["bytes"], "правка другого писателя не перезаписана"
    assert all(p.read_bytes() == b for p, b in owners.items()), "карточки Owner байт в байт"
    for p in srcs:
        if p != victim["p"]:
            assert p.read_bytes() == originals[p]
    op = next((root / "data" / "repair_phantom_recovery").iterdir())
    m = json.loads((op / "manifest.json").read_text())
    assert m["state"] == "needs_manual"
    for f in m["files"]:
        data = (op / f"{f['index']:03d}.orig").read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["orig_sha"] == hashlib.sha256(originals[Path(f["path"])]).hexdigest()


def test_recovery_refuses_a_corrupted_snapshot(tmp_path, git_tree):
    """Восстановление сверяет исходные байты слепка с sha256 — порченый слепок не применяется."""
    import signal
    root, tracker = git_tree
    _three(tracker)
    driver = tmp_path.parent / f"driver_cor_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "1", "after", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    op = next((root / "data" / "repair_phantom_recovery").iterdir())
    orig0 = op / "000.orig"
    orig0.write_bytes(orig0.read_bytes() + b"tampered")
    cards_before = {p: p.read_bytes() for p in tracker.glob("*.md")}

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_MANUAL
    assert "слепок повреждён" in json.loads(rec.stdout)["reason"]
    assert all(p.read_bytes() == b for p, b in cards_before.items()), "ни одна карточка не тронута"


# ── перенесено из bda950756: журнал переходов (код 7) и каталоги с fsync родителя ──

def test_rollback_in_an_unrecognised_tree_is_not_a_clean_rollback(tracker, rec_root):
    """Без опознанного дерева журнал переходов не ведётся — доказать его нечем: код 7."""
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    real = R._default_write

    def fail_after_first(path, new_status):
        real(path, new_status)
        raise OSError("сбой после первой замены")

    res = R.repair(tracker, apply=True, coordination=COORD, write=fail_after_first, recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_AUDIT_UNPROVEN, res
    assert all(p.read_bytes() == b for p, b in originals.items()), "карточки всё равно восстановлены"
    m = json.loads((next(rec_root.iterdir()) / "manifest.json").read_text())
    assert m["state"] == R.AUDIT_UNPROVEN_STATE and m["audit"]["verdict"] == "unmeasured"
    # блокер: следующий запуск (и сухой прогон) — снова код 7, без записей
    assert R.repair(tracker, apply=False, recovery_root=str(rec_root))["exit"] == R.EXIT_AUDIT_UNPROVEN

_DRIVER_IN_SET_STATUS = r'''
import importlib.util, os, signal, sys
from pathlib import Path
script, tracker, kill_at, lock = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
spec = importlib.util.spec_from_file_location("r", script)
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
import spa_core.owner_queue.queue as q
real_audit = q.record_status_write
n = {"i": 0}
def audit_then_maybe_die(*a, **k):
    # Окно ВНУТРИ set_status: карточка уже заменена atomic_save_text, событие ещё не дописано.
    if n["i"] == kill_at:
        os.kill(os.getpid(), signal.SIGKILL)
    n["i"] += 1
    return real_audit(*a, **k)
q.record_status_write = audit_then_maybe_die
import contextlib, fcntl
@contextlib.contextmanager
def coord(_t):
    with open(lock, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
R.repair(tracker, apply=True, coordination=coord)
print("NOT KILLED")
'''

@pytest.mark.parametrize("kill_at", [0, 1, 2])
def test_kill_inside_set_status_before_the_audit_line(tmp_path, git_tree, kill_at):
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    owners = sorted(tracker.glob("owner-decision-*.md"))
    originals = {p: p.read_bytes() for p in [*srcs, *owners]}
    prior = {"card": "earlier.md", "old": "new", "new": "done", "source": "someone"}
    (root / "data").mkdir()
    (root / "data" / "tracker_status_audit.jsonl").write_text(json.dumps(prior) + "\n", encoding="utf-8")
    driver = tmp_path.parent / f"driver_in_{tmp_path.name}.py"
    driver.write_text(_DRIVER_IN_SET_STATUS, encoding="utf-8")

    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), str(kill_at), str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL, (r.returncode, r.stdout, r.stderr)

    replaced = [p for p in srcs if p.read_bytes() != originals[p]]
    assert len(replaced) == kill_at + 1, "карточка уже заменена, событие — нет"
    log_before = (root / "data" / "tracker_status_audit.jsonl").read_bytes()
    assert len(_audit(root)) == 1 + kill_at, "прямых событий на одно меньше, чем замен"

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_AUDIT_UNPROVEN, rec.stdout + rec.stderr
    assert all(p.read_bytes() == b for p, b in originals.items()), "карточки и байты Owner — исходные"
    log_after = (root / "data" / "tracker_status_audit.jsonl").read_bytes()
    assert log_after.startswith(log_before), "журнал не переписан и не очищен — только дописан"
    op = next((root / "data" / "repair_phantom_recovery").iterdir())
    m = json.loads((op / "manifest.json").read_text())
    assert m["state"] == R.AUDIT_UNPROVEN_STATE, "недоказанный журнал — не финальное состояние"
    assert m["audit"]["verdict"] == "incomplete"
    assert any("нет прямого события" in pr for pr in m["audit"]["problems"])
    assert "НЕ доказана" in json.loads(rec.stdout)["reason"]

    # Повторный запуск код 7 НЕ обходит: блокер стоит, ничего не пишется.
    snap = _tree(root)
    again = _apply_coordinated(tracker)
    assert again.returncode == R.EXIT_AUDIT_UNPROVEN, again.stdout
    assert _tree(root) == snap, "повторный запуск ничего не записал"
    assert _cli(tracker).returncode == R.EXIT_AUDIT_UNPROVEN, "сухой прогон называет тот же блокер"
    # Свободная запись audit_resolution — ПОЯСНЕНИЕ, а не решение человека: блокер не снимается
    # (воспроизведение ARB 21.10: {"by": "agent-local", "note": "closed automatically"}).
    m["audit_resolution"] = {"by": "agent-local", "note": "closed automatically"}
    (op / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    snap = _tree(root)
    after = _apply_coordinated(tracker)
    assert after.returncode == R.EXIT_AUDIT_UNPROVEN, after.stdout
    assert _cli(tracker).returncode == R.EXIT_AUDIT_UNPROVEN
    assert _tree(root) == snap, "свободная заметка ничего не открыла"
    assert R._is_final(m) is False

def test_first_run_creates_the_recovery_tree_with_parent_fsyncs_before_any_write(git_tree, monkeypatch):
    root, tracker = git_tree
    _three(tracker)
    assert not (root / "data").exists(), "первый запуск: data/ ещё нет"
    events = []
    real_mkdir, real_fsync_dir = R.os.mkdir, R._fsync_dir
    def mkdir(p, *a, **k):
        real_mkdir(p, *a, **k)            # FileExistsError (exist_ok=True у других) — не создание
        events.append(("mkdir", Path(p)))

    monkeypatch.setattr(R.os, "mkdir", mkdir)
    monkeypatch.setattr(R, "_fsync_dir", lambda p: (events.append(("fsync_dir", Path(p))),
                                                    real_fsync_dir(p))[1])
    real_write = R._default_write
    res = R.repair(tracker, apply=True, coordination=COORD,
                   write=lambda p, s: (events.append(("card_write", Path(p))), real_write(p, s))[1])

    assert res["exit"] == R.EXIT_OK, res
    first_card = next(i for i, e in enumerate(events) if e[0] == "card_write")
    made = [(i, e[1]) for i, e in enumerate(events) if e[0] == "mkdir"]
    rec = root / "data" / "repair_phantom_recovery"
    assert [d for _, d in made][:3] == [root / "data", rec, next(rec.iterdir())], made
    for i, d in made:
        nxt = events[i + 1]
        assert nxt == ("fsync_dir", d.parent), f"после mkdir {d} — fsync его родителя"
        assert i < first_card
    manifest_dir_synced = [i for i, e in enumerate(events)
                           if e == ("fsync_dir", next(rec.iterdir())) and i < first_card]
    assert manifest_dir_synced, "каталог операции синхронизирован (журнал на диске) до первой записи"

def test_first_recovery_dir_keeps_an_existing_transition_journal(git_tree, monkeypatch):
    """`data/` и журнал переходов уже есть, каталога восстановления — нет (первый запуск).

    Создание каталога восстановления не трогает журнал: его прежние байты — префикс
    нового содержимого, и каждый вновь созданный каталог синхронизирован у родителя.
    """
    root, tracker = git_tree
    _three(tracker)
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.parent.mkdir()
    prior = (json.dumps({"card": "earlier.md", "old": "new", "new": "done", "source": "someone"})
             + "\n").encode("utf-8")
    journal.write_bytes(prior)
    assert not (root / "data" / "repair_phantom_recovery").exists()
    events = []
    real_mkdir, real_fsync_dir = R.os.mkdir, R._fsync_dir

    def mkdir(p, *a, **k):
        real_mkdir(p, *a, **k)
        events.append(("mkdir", Path(p)))

    monkeypatch.setattr(R.os, "mkdir", mkdir)
    monkeypatch.setattr(R, "_fsync_dir", lambda p: (events.append(("fsync_dir", Path(p))),
                                                    real_fsync_dir(p))[1])

    res = R.repair(tracker, apply=True, coordination=COORD)

    assert res["exit"] == R.EXIT_OK, res
    after = journal.read_bytes()
    assert after.startswith(prior), "журнал не переписан и не очищен — только дописан"
    added = [json.loads(ln) for ln in after[len(prior):].decode("utf-8").splitlines()]
    assert [(e["old"], e["new"]) for e in added] == [("done", "new")] * 3
    made = [(i, e[1]) for i, e in enumerate(events) if e[0] == "mkdir"]
    rec = root / "data" / "repair_phantom_recovery"
    assert [d for _, d in made][:2] == [rec, next(rec.iterdir())], made
    for i, d in made:
        assert events[i + 1] == ("fsync_dir", d.parent), f"после mkdir {d} — fsync его родителя"


# ── чужие байты не в UTF-8 ⇒ код 5 / needs_manual, без необработанного исключения ──

_NON_UTF8 = b"\xff\xfe foreign bytes, not utf-8\n"


def test_non_utf8_foreign_bytes_in_process_are_manual_not_a_crash(git_tree, rec_root):
    root, tracker = git_tree
    _three(tracker)
    owners = {p: p.read_bytes() for p in tracker.glob("owner-decision-*.md")}
    prior = b'{"card": "earlier.md", "old": "new", "new": "done", "source": "someone"}\n'
    (root / "data").mkdir()
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.write_bytes(prior)
    real = R._default_write
    hit = {}

    def write_then_foreign(path, new_status):
        real(path, new_status)
        if not hit:
            path.write_bytes(path.read_bytes() + _NON_UTF8)     # чужой писатель поверх нашей записи
            hit["p"], hit["bytes"] = path, path.read_bytes()
            raise OSError("сбой после первой замены")

    res = R.repair(tracker, apply=True, coordination=COORD, write=write_then_foreign,
                   recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_MANUAL, res
    assert hit["p"].read_bytes() == hit["bytes"], "чужие байты сохранены"
    assert all(p.read_bytes() == b for p, b in owners.items())
    op = next(rec_root.iterdir())
    m = json.loads((op / "manifest.json").read_text())
    assert m["state"] == "needs_manual"
    for f in m["files"]:
        assert hashlib.sha256((op / f"{f['index']:03d}.orig").read_bytes()).hexdigest() == f["orig_sha"]
    assert journal.read_bytes().startswith(prior), "журнал переходов только дописан"
    again = R.repair(tracker, apply=True, coordination=COORD, recovery_root=str(rec_root))
    assert again["exit"] == R.EXIT_MANUAL, "блокер стоит, исключения нет"
    assert hit["p"].read_bytes() == hit["bytes"]


def test_non_utf8_foreign_bytes_after_sigkill_are_manual_not_a_crash(tmp_path, git_tree):
    import signal
    root, tracker = git_tree
    _three(tracker)
    owners = {p: p.read_bytes() for p in tracker.glob("owner-decision-*.md")}
    driver = tmp_path.parent / f"driver_u8_{tmp_path.name}.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "1", "after", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    victim = sorted(p for p in tracker.glob("inbox-*.md") if _status(p) == "new")[0]
    victim.write_bytes(victim.read_bytes() + _NON_UTF8)
    foreign = victim.read_bytes()
    journal = root / "data" / "tracker_status_audit.jsonl"
    log_before = journal.read_bytes()

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_MANUAL, rec.stdout + rec.stderr
    assert "Traceback" not in rec.stderr
    assert victim.read_bytes() == foreign
    assert all(p.read_bytes() == b for p, b in owners.items())
    assert journal.read_bytes().startswith(log_before)


# ── причинность: событие другого процесса — не доказательство этой операции ───

def test_a_matching_foreign_event_does_not_prove_the_missing_forward(tmp_path, git_tree):
    """SIGKILL внутри set_status: прямого события нет. В журнал попадает СОВПАДАЮЩЕЕ по пути,
    переходу, источнику и времени событие ДРУГОГО процесса — прежняя сверка приняла бы его за
    наше и выдала бы «сходится». Теперь — код 7, событие названо чужим."""
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    driver = tmp_path.parent / f"driver_cz_{tmp_path.name}.py"
    driver.write_text(_DRIVER_IN_SET_STATUS, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "0", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    replaced = next(p for p in srcs if p.read_bytes() != originals[p])
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.parent.mkdir(exist_ok=True)
    from datetime import datetime, timezone
    forged = {"ts": datetime.now(timezone.utc).isoformat(), "card": replaced.name,
              "path": str(replaced.resolve()), "old": "done", "new": "new",
              "source": "queue.set_status", "pid": 1, "cwd": "/"}
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_AUDIT_UNPROVEN, rec.stdout
    assert all(p.read_bytes() == b for p, b in originals.items())
    op = next((root / "data" / "repair_phantom_recovery").iterdir())
    m = json.loads((op / "manifest.json").read_text())
    assert m["audit"]["verdict"] == "incomplete"
    assert any("нет прямого события" in pr for pr in m["audit"]["problems"])
    assert any("pid 1" in fe for fe in m["audit"]["foreign_events"])


def test_own_events_still_prove_a_clean_rollback_next_to_a_foreign_one(git_tree, rec_root):
    root, tracker = git_tree
    _three(tracker)
    real = R._default_write
    from datetime import datetime, timezone

    def fail_after_first(path, new_status):
        real(path, new_status)
        with open(root / "data" / "tracker_status_audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "path": str(path),
                                 "old": "done", "new": "new", "source": "queue.set_status",
                                 "pid": 1, "cwd": "/"}) + "\n")
        raise OSError("сбой после первой замены")

    res = R.repair(tracker, apply=True, coordination=COORD, write=fail_after_first,
                   recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    m = json.loads((next(rec_root.iterdir()) / "manifest.json").read_text())
    assert m["state"] == "rolled_back" and m["audit"]["verdict"] == "consistent"
    assert m["audit"]["foreign_events"], "чужое событие названо, но доказательством не служит"


# ── совпавший / переиспользованный pid: событие не доказывает операцию одним номером ──

def _forged(path: Path, pid: int) -> dict:
    from datetime import datetime, timezone
    return {"ts": datetime.now(timezone.utc).isoformat(), "card": path.name,
            "path": str(path.resolve()), "old": "done", "new": "new",
            "source": "queue.set_status", "pid": pid, "cwd": "/"}


def test_same_pid_forged_event_after_sigkill_does_not_close_the_gap(tmp_path, git_tree):
    """Воспроизведение ARB 21.10: SIGKILL внутри set_status, затем в журнале — событие с ТЕМ ЖЕ
    pid писателя, путём и переходом. Раньше: consistent, foreign_events=[]. Теперь — код 7."""
    import signal
    root, tracker = git_tree
    srcs = _three(tracker)
    originals = {p: p.read_bytes() for p in srcs}
    driver = tmp_path.parent / f"driver_sp_{tmp_path.name}.py"
    driver.write_text(_DRIVER_IN_SET_STATUS, encoding="utf-8")
    r = _run([str(driver), str(_ROOT / "scripts" / "repair_phantom_intake_cards.py"),
              str(tracker), "0", str(_LOCK_FILE)], _ROOT)
    assert r.returncode == -signal.SIGKILL
    op = next((root / "data" / "repair_phantom_recovery").iterdir())
    writer_pid = json.loads((op / "manifest.json").read_text())["writer_pid"]
    replaced = next(p for p in srcs if p.read_bytes() != originals[p])
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.parent.mkdir(exist_ok=True)
    with open(journal, "a", encoding="utf-8") as fh:            # номер достался другому процессу
        fh.write(json.dumps(_forged(replaced, writer_pid), ensure_ascii=False) + "\n")

    rec = _apply_coordinated(tracker)

    assert rec.returncode == R.EXIT_AUDIT_UNPROVEN, rec.stdout
    m = json.loads((op / "manifest.json").read_text())
    assert m["audit"]["verdict"] == "incomplete"
    assert any(f"pid {writer_pid}" in fe and "не связано" in fe for fe in m["audit"]["foreign_events"])
    assert all(p.read_bytes() == b for p, b in originals.items())


def test_coinciding_pid_event_outside_the_write_does_not_stand_in_for_a_lost_one(git_tree, rec_root,
                                                                                    monkeypatch):
    """В ТОМ ЖЕ процессе: событие с совпадающим pid лежит в журнале ДО операции, а настоящее
    событие записи не дошло до журнала. Совпадение pid, пути и перехода его не заменяет — код 7."""
    import os as _os
    root, tracker = git_tree
    srcs = _three(tracker)
    first = sorted(srcs)[0]
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.parent.mkdir(exist_ok=True)
    journal.write_text(json.dumps(_forged(first, _os.getpid()), ensure_ascii=False) + "\n", encoding="utf-8")
    import spa_core.owner_queue.queue as q
    monkeypatch.setattr(q, "record_status_write", lambda *a, **k: None)   # прямая строка не дошла
    real = R._default_write

    def fail_after_first(path, new_status):
        real(path, new_status)
        raise OSError("сбой после первой замены")

    res = R.repair(tracker, apply=True, coordination=COORD, write=fail_after_first,
                   recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_AUDIT_UNPROVEN, res
    m = json.loads((next(rec_root.iterdir()) / "manifest.json").read_text())
    assert m["state"] == R.AUDIT_UNPROVEN_STATE
    assert any("нет прямого события операции" in pr for pr in m["audit"]["problems"])
    assert m["audit"]["foreign_events"], "совпавшее событие названо несвязанным"


def test_own_bound_event_proves_the_rollback_next_to_a_coinciding_pid_one(git_tree, rec_root):
    """Обратная сторона: своё событие ВНУТРИ границ записи доказывает откат, совпавшее — нет."""
    import os as _os
    root, tracker = git_tree
    srcs = _three(tracker)
    first = sorted(srcs)[0]
    journal = root / "data" / "tracker_status_audit.jsonl"
    journal.parent.mkdir(exist_ok=True)
    journal.write_text(json.dumps(_forged(first, _os.getpid()), ensure_ascii=False) + "\n", encoding="utf-8")
    real = R._default_write

    def fail_after_first(path, new_status):
        real(path, new_status)
        raise OSError("сбой после первой замены")

    res = R.repair(tracker, apply=True, coordination=COORD, write=fail_after_first,
                   recovery_root=str(rec_root))

    assert res["exit"] == R.EXIT_ROLLED_BACK, res
    m = json.loads((next(rec_root.iterdir()) / "manifest.json").read_text())
    assert m["audit"]["verdict"] == "consistent"
    assert m["audit"]["foreign_events"]


def test_a_free_form_resolution_note_never_makes_the_operation_final():
    """Свободная запись — пояснение, не решение человека (воспроизведение ARB 21.10)."""
    for res in ({"by": "agent-local", "note": "closed automatically"},
                {"by": "Владелец", "note": "разобрал, всё верно"}):
        assert R._is_final({"state": R.AUDIT_UNPROVEN_STATE, "audit_resolution": res}) is False
    assert R._is_final({"state": "rolled_back"}) is True
