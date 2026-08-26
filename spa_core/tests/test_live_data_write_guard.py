"""Сторож живого `data/` проверяется НАСТОЯЩЕЙ аварией, а не своим исходником.

Каждый тест здесь — положительный контроль к `live_data_write_guard.py`:
воспроизводится ровно то, на что жалуется карточка
`inbox-progon-testov-perepisyvaet-sorok-otslezhivaemyh-failov-data` — прогон
переписывает git-tracked файл в `data/` (не создаёт новый, а МЕНЯЕТ
существующий: `"updated_at": "2026-08-04…" → "2026-08-20…"`, `"count": 26 → 28`),
и требуется, чтобы прогон ПОКРАСНЕЛ и НАЗВАЛ виновника. Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Эффект меряется в ДОЧЕРНЕМ процессе: сторож — autouse-фикстура, и внутри своего
же прогона его срабатывание неотличимо от падения самого теста (урок
`pytest-diversion-blinds-effect-tests`). Обратный контроль — тот же дочерний
прогон БЕЗ плагина: он зелёный, значит краснота приходит от сторожа, а не от
подставного теста.

Улика для дочерних прогонов — СВОЙ файл в `data/` с уникальным по pid именем, а
не настоящий журнал трека: положительный контроль не имеет права быть той самой
аварией, которую он воспроизводит.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from spa_core.tests import _child_pytest

# Тот САМЫЙ объект, который зарегистрировали оба conftest (они грузят модуль по
# пути к файлу под именем `spa_live_data_write_guard`). Вторая копия сторожа
# проверяла бы не то, что работает в прогоне.
guard = sys.modules.get("spa_live_data_write_guard")
if guard is None:                                   # прямой запуск без conftest
    from spa_core.tests import live_data_write_guard as guard

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent

#: Имя улики. Уникально по pid, чтобы параллельные прогоны не мешали друг другу.
DECOY_NAME = f"_live_data_write_guard_control_{os.getpid()}.json"

CHILD_TEST = '''
import json
from pathlib import Path

DECOY = Path(r"{decoy}")


def test_rewrites_a_tracked_state_file():
    # Ровно жалоба карточки: не создание файла, а ПРАВКА существующего.
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["updated_at"] = "2026-08-20T22:55:18"
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''

CHILD_TEST_MARKED = '''
import json
from pathlib import Path

import pytest

DECOY = Path(r"{decoy}")


@pytest.mark.live_data
def test_rewrites_a_tracked_state_file_on_purpose():
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''

CHILD_TEST_CLEAN = '''
def test_touches_nothing():
    assert 1 + 1 == 2
'''


def _run_child(test_file, with_guard, env_extra=None):
    """Дочерний pytest на подставном тесте; плагин подключается по требованию."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), str(TESTS_DIR), env.get("PYTHONPATH", "")]
    )
    env.pop(guard.AUDIT_ENV, None)
    env.pop(guard.AUDIT_OUT_ENV, None)
    env.update(env_extra or {})
    extra = ["-q", "-p", "no:cacheprovider"]
    if with_guard:
        extra += ["-p", "live_data_write_guard"]
    if env_extra is None or "PATH" not in env_extra:
        # Дочерний прогон идёт БЕЗ git НАМЕРЕННО. Сторож тогда работает в своём
        # штатном запасном режиме (`tracked_paths() is None` ⇒ наблюдается весь
        # каталог), и опыт можно ставить на безобидной улике вместо настоящего
        # git-tracked журнала трека. Положительный контроль не имеет права БЫТЬ
        # той аварией, которую он воспроизводит.
        env["PATH"] = ""
    # Потолок узкий НАМЕРЕННО: здоровый прогон занимает доли секунды, и зависший
    # дочерний pytest обязан назваться быстро, а не съесть цикл.
    return _child_pytest.run_child_pytest(
        test_file, *extra, cwd=REPO_ROOT, env=env, timeout=120
    )


def _write_child(body, decoy):
    """Файл подставного теста — в собственном временном каталоге.

    Замер #315: дочерний pytest, чей файл лежал внутри `pytest-of-<user>/pytest-N`,
    не доходил даже до `--collect-only` (300 с и таймаут), а тот же файл вне этого
    дерева отрабатывал за 0.00 с — отсюда `tempfile.mkdtemp()` вместо `tmp_path`.

    Цикл #382 измерил ПРИЧИНУ, и она не в каталоге: pytest считает rootdir общим
    предком cwd и аргумента и обходит `scandir`-ом всё, что накрыл. `mkdtemp`
    спасал лишь потому, что возвращает НЕразрешённый `/var/...`; один `.resolve()`
    вернул бы аварию. Настоящая защита теперь — якорь `--rootdir` в
    `_child_pytest.run_child_pytest`, а каталог остаётся своим просто ради
    изоляции улик.
    """
    child_dir = Path(tempfile.mkdtemp(prefix="spa_live_data_guard_control_"))
    test_file = child_dir / "test_writer.py"
    test_file.write_text(body.format(decoy=decoy), encoding="utf-8")
    return child_dir, test_file


@pytest.fixture()
def decoy():
    """Файл-улика в живом `data/`, который дочерний прогон будет переписывать.

    Сам сторож на неё НЕ краснеет, и это следует из порядка фикстур, а не из
    везения: autouse-фикстура conftest ставится ПЕРВОЙ (снимок — до появления
    улики) и снимается ПОСЛЕДНЕЙ (после её удаления), поэтому оба снимка видят
    одно и то же — отсутствие файла. Уносить улику обязана фикстура, а не
    сторож: сторож называет и ничего не прячет.
    """
    path = guard.REPO_ROOT / "data" / DECOY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": "2026-08-04T08:30:45", "count": 26}),
                    encoding="utf-8")
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Чистая часть: что считается «изменилось»
# ---------------------------------------------------------------------------

def test_rewrite_of_an_existing_file_is_a_finding(tmp_path):
    """Главный вид аварии: файл был и остался, но его переписали."""
    f = tmp_path / "alert_log.json"
    f.write_text('{"count": 26}', encoding="utf-8")
    before = guard.snapshot([tmp_path])
    f.write_text('{"count": 28}', encoding="utf-8")   # РОВНО та же длина — ловится
    os.utime(f, ns=(0, 1))                            # только по mtime
    touched = guard.changed(before, guard.snapshot([tmp_path]))
    assert len(touched) == 1 and touched[0].endswith("alert_log.json"), touched


def test_appearance_is_a_finding(tmp_path):
    before = guard.snapshot([tmp_path])
    (tmp_path / "new_log.json").write_text("[]", encoding="utf-8")
    assert len(guard.changed(before, guard.snapshot([tmp_path]))) == 1


def test_disappearance_is_a_finding(tmp_path):
    """Удаление живого состояния — тоже правка прода, не только запись."""
    f = tmp_path / "gone.json"
    f.write_text("[]", encoding="utf-8")
    before = guard.snapshot([tmp_path])
    f.unlink()
    assert len(guard.changed(before, guard.snapshot([tmp_path]))) == 1


def test_untouched_tree_is_not_a_finding(tmp_path):
    """Обратный контроль: сторож не обязан краснеть на тракте без записи."""
    (tmp_path / "a.json").write_text("[]", encoding="utf-8")
    snap = guard.snapshot([tmp_path])
    assert guard.changed(snap, guard.snapshot([tmp_path])) == ()


def test_snapshot_of_missing_directory_is_empty(tmp_path):
    assert guard.snapshot([tmp_path / "нет-такого-каталога"]) == {}


def test_pycache_is_not_state(tmp_path):
    """`.pyc` от импорта — артефакт сборки; краснеть на нём значит кричать волком."""
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    before = guard.snapshot([tmp_path])
    (cache / "apy_database.cpython-313.pyc").write_bytes(b"\x00")
    assert guard.changed(before, guard.snapshot([tmp_path])) == ()


# ---------------------------------------------------------------------------
# Что именно под наблюдением
# ---------------------------------------------------------------------------

def test_watched_dirs_are_taken_from_file_not_cwd(monkeypatch, tmp_path):
    """Авария у соседа случилась ИМЕННО из-за cwd — этот сторож не смеет от него зависеть.

    Шаг CI «Run spa_core/tests» стартует из `cd spa_core`, а разработчик гоняет
    тот же набор из корня репо.
    """
    expected = (REPO_ROOT / "data", REPO_ROOT / "spa_core" / "data",
                REPO_ROOT / "spa_core" / "database")
    assert guard.WATCHED == expected
    monkeypatch.chdir(tmp_path)
    assert guard.WATCHED == expected


@pytest.mark.parametrize("rel", [
    "data/live_execution_log.json",   # домен ИСПОЛНЕНИЯ — инвариант #6
    "data/alert_log.json",            # журнал тревог владельца
    "data/risk_alerts.json",
    "spa_core/database/spa.db",
])
def test_files_named_by_the_card_are_inside_the_watched_area(rel):
    """Карточка требует закрыть эти пути первыми — они обязаны быть под сторожем."""
    target = REPO_ROOT / rel
    assert any(target == w or w in target.parents for w in guard.WATCHED), rel


def test_failure_message_names_the_subject_the_file_and_the_price():
    msg = guard.failure_message("tests/test_x.py::test_y", ("data/alert_log.json",))
    assert "tests/test_x.py::test_y" in msg
    assert "data/alert_log.json" in msg
    assert "live_data" in msg          # почему эта пометка НЕ выход
    assert "чистое дерево" in msg      # почему это не косметика
    assert guard.AUDIT_ENV in msg      # как узнать ИМЯ теста, если он не назван


def test_failure_message_does_not_invent_a_culprit():
    """Вне режима замера сторож знает ФАЙЛ, но не ТЕСТ — и обязан так и сказать."""
    msg = guard.failure_message("прогон", ("data/alert_log.json",))
    assert msg.startswith("прогон изменил живое состояние")


# ---------------------------------------------------------------------------
# Уровень прогона: где стоит сама проверка
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, exitstatus=0):
        self.exitstatus = exitstatus


def test_session_finish_reddens_a_green_run(monkeypatch, tmp_path):
    """Прогон, оставивший правку, обязан вернуть НЕнулевой код."""
    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "_tracked", None)   # снимок подменён — фильтр не нужен
    monkeypatch.setattr(guard, "_session_before", {"data/x.json": (1, 2)})
    monkeypatch.setattr(guard, "snapshot", lambda roots=None: {"data/x.json": (9, 2)})
    session = _FakeSession()
    assert guard.session_finish(session) == ("data/x.json",)
    assert session.exitstatus == 1


def test_session_finish_keeps_an_existing_failure_code(monkeypatch):
    """Свой код возврата сторож не затирает — падение тестов важнее его находки."""
    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "_tracked", None)   # снимок подменён — фильтр не нужен
    monkeypatch.setattr(guard, "_session_before", {"data/x.json": (1, 2)})
    monkeypatch.setattr(guard, "snapshot", lambda roots=None: {"data/x.json": (9, 2)})
    session = _FakeSession(exitstatus=2)
    guard.session_finish(session)
    assert session.exitstatus == 2


def test_session_finish_is_idempotent(monkeypatch):
    """Хук стоит в ОБОИХ корнях conftest — второй вызов не смеет отчитаться дважды."""
    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "_tracked", None)   # снимок подменён — фильтр не нужен
    monkeypatch.setattr(guard, "_session_before", {"data/x.json": (1, 2)})
    monkeypatch.setattr(guard, "snapshot", lambda roots=None: {"data/x.json": (9, 2)})
    assert guard.session_finish(_FakeSession()) == ("data/x.json",)
    second = _FakeSession()
    assert guard.session_finish(second) == ()
    assert second.exitstatus == 0


def test_session_finish_is_silent_on_a_clean_run(monkeypatch):
    """Обратный контроль: без правки прогон остаётся зелёным."""
    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "_tracked", None)   # снимок подменён — фильтр не нужен
    monkeypatch.setattr(guard, "_session_before", {"data/x.json": (1, 2)})
    monkeypatch.setattr(guard, "snapshot", lambda roots=None: {"data/x.json": (1, 2)})
    session = _FakeSession()
    assert guard.session_finish(session) == ()
    assert session.exitstatus == 0


# ---------------------------------------------------------------------------
# Сужение до git-tracked
# ---------------------------------------------------------------------------

def test_tracked_paths_are_known_to_git():
    """Набор наблюдения берётся у git, а не у содержимого каталога."""
    tracked = guard.tracked_paths()
    assert tracked, "git должен знать хоть что-то под наблюдением"
    assert "data/golive_status.json" in tracked
    # Runtime-осадок git не знает — и в наблюдение он не попадает.
    assert "data/consumption_receipts.jsonl" not in tracked


def test_tracked_paths_returns_none_when_git_is_unusable(monkeypatch):
    """Git недоступен ⇒ None ⇒ наблюдается ВСЁ: ошибаться в сторону строгости."""
    def _boom(*a, **k):
        raise OSError("нет git")
    monkeypatch.setattr(guard.subprocess, "run", _boom)
    assert guard.tracked_paths() is None


def test_watched_snapshot_keeps_only_tracked(monkeypatch):
    monkeypatch.setattr(guard, "_tracked", frozenset({"data/a.json"}))
    monkeypatch.setattr(guard, "snapshot",
                        lambda roots=None: {"data/a.json": (1, 1), "data/junk.tmp": (1, 1)})
    assert guard.watched_snapshot() == {"data/a.json": (1, 1)}


def test_watched_snapshot_keeps_everything_without_git(monkeypatch):
    monkeypatch.setattr(guard, "_tracked", None)
    monkeypatch.setattr(guard, "snapshot",
                        lambda roots=None: {"data/a.json": (1, 1), "data/junk.tmp": (1, 1)})
    assert len(guard.watched_snapshot()) == 2


def test_same_content_rewrite_is_still_a_finding(tmp_path):
    """Главный довод за mtime: `git status` такую правку не покажет НИКОГДА.

    Замер цикла #352 — прогон переписывает `data/golive_status.json` (артефакт
    гейта go-live) тем же содержимым. Сравнение по содержимому объявило бы это
    чистым прогоном.
    """
    f = tmp_path / "golive_status.json"
    f.write_text('{"ready": false}', encoding="utf-8")
    before = guard.snapshot([tmp_path])
    f.write_text('{"ready": false}', encoding="utf-8")   # БАЙТ В БАЙТ то же самое
    os.utime(f, ns=(0, 1))
    assert len(guard.changed(before, guard.snapshot([tmp_path]))) == 1


# ---------------------------------------------------------------------------
# Режим замера
# ---------------------------------------------------------------------------

def test_record_writes_nodeid_and_paths(tmp_path):
    out = tmp_path / "audit.jsonl"
    guard.record("spa_core/tests/test_x.py::test_y", ("data/alert_log.json",), out_path=out)
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row == {"nodeid": "spa_core/tests/test_x.py::test_y",
                   "paths": ["data/alert_log.json"]}


def test_audit_report_lives_outside_the_repo_by_default():
    """Отчёт, записанный в дерево, сам пачкает то, что измеряет."""
    default = guard.DEFAULT_AUDIT_OUT
    assert REPO_ROOT not in default.parents and default != REPO_ROOT


def test_audit_mode_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv(guard.AUDIT_ENV, raising=False)
    assert guard.audit_enabled() is False
    monkeypatch.setenv(guard.AUDIT_ENV, "1")
    assert guard.audit_enabled() is True


# ---------------------------------------------------------------------------
# Положительный контроль: настоящая авария в дочернем процессе
# ---------------------------------------------------------------------------

def test_child_run_goes_red_and_names_the_file(decoy):
    """Подставной тест переписывает файл в живом `data/` — прогон обязан упасть.

    Сам тест при этом ЗЕЛЁНЫЙ (он делает ровно то, что написано), а красным
    становится прогон: проверка стоит на высоте своей приёмки — «после прогона
    `git status -- data/` пуст».
    """
    child_dir, test_file = _write_child(CHILD_TEST, decoy)
    try:
        with_guard = _run_child(test_file, with_guard=True)
        combined = with_guard.stdout + with_guard.stderr
        assert with_guard.returncode != 0, combined
        assert DECOY_NAME in combined, combined
        assert "1 passed" in combined, combined      # красит ПРОГОН, а не тест
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_same_writer_is_green_without_the_guard(decoy):
    """Обратный контроль: краснота приходит от сторожа, а не от подставного теста."""
    child_dir, test_file = _write_child(CHILD_TEST, decoy)
    try:
        without_guard = _run_child(test_file, with_guard=False)
        assert without_guard.returncode == 0, without_guard.stdout + without_guard.stderr
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_clean_test_stays_green_with_the_guard():
    """Сторож не красит прогон, в котором живого состояния никто не трогал."""
    child_dir, test_file = _write_child(CHILD_TEST_CLEAN, "не используется")
    try:
        run = _run_child(test_file, with_guard=True)
        assert run.returncode == 0, run.stdout + run.stderr
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_live_data_marker_does_not_license_writing(decoy):
    """Пометка `live_data` — про ЧТЕНИЕ живого состояния, и записи не разрешает.

    Соблазн был обратный: сделать её выходом из проверки. Тогда любой писатель
    гасился бы одной строкой, а сторож превратился бы в вежливую просьбу. В
    `tests/conftest.py` пометка описана прямо — «тесты, которые ЧИТАЮТ
    закоммиченный live data/» — и права писать не даёт.
    """
    child_dir, test_file = _write_child(CHILD_TEST_MARKED, decoy)
    try:
        run = _run_child(test_file, with_guard=True)
        combined = run.stdout + run.stderr
        assert run.returncode != 0, combined
        assert DECOY_NAME in combined, combined
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_untracked_file_does_not_redden_a_run_when_git_is_available(decoy):
    """Обратный контроль к сужению: осадок, которого git не знает, прогон не красит.

    Та же улика, тот же дочерний прогон — разница ровно одна: git доступен, значит
    `tracked_paths()` вернул набор, и улики в нём нет. Без этого контроля «сторож
    сузился» было бы утверждением, а не измерением.
    """
    child_dir, test_file = _write_child(CHILD_TEST, decoy)
    try:
        run = _run_child(test_file, with_guard=True,
                         env_extra={"PATH": os.environ.get("PATH", "")})
        assert run.returncode == 0, run.stdout + run.stderr
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_audit_mode_adds_the_name_and_still_fails(decoy, tmp_path):
    """Режим замера НИЧЕГО не гасит — он ДОБАВЛЯЕТ имя виновника к тому же отказу."""
    out = tmp_path / "audit.jsonl"
    child_dir, test_file = _write_child(CHILD_TEST, decoy)
    try:
        run = _run_child(test_file, with_guard=True,
                         env_extra={guard.AUDIT_ENV: "1", guard.AUDIT_OUT_ENV: str(out)})
        assert run.returncode != 0, run.stdout + run.stderr
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert rows, "режим замера обязан ЗАПИСАТЬ то, за что иначе роняет"
        assert any(DECOY_NAME in p for r in rows for p in r["paths"]), rows
        assert any("test_rewrites_a_tracked_state_file" in r["nodeid"] for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)
