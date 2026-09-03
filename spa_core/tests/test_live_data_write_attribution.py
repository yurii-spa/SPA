"""Карта «файл → тест» обязана уметь сказать «НЕ ИЗМЕРЕНА».

Каждый тест здесь — положительный контроль к третьему исходу атрибуции в
`live_data_write_guard.py`: воспроизводится ровно та авария, на которую жалуется
карточка `inbox-karta-chei-eto-test-vydumyvaetsya-pri-parallelnom-progone`.

Замер #353: одно и то же дерево, один и тот же Мак, разница только в том, шёл ли
рядом второй прогон — **19 записей атрибуции против 0**. Среди 19 «писателей»
были тесты, которые не могут писать ничего (арифметика над списком чисел с
приписанным `reward_harvesting_log.json`). Механизм называния — разница снимков
вокруг теста, и в ней нет ни pid, ни владельца записи: только совпадение во
времени.

Эффект меряется в ДОЧЕРНЕМ процессе (урок `pytest-diversion-blinds-effect-tests`):
внутри своего же прогона поведение autouse-фикстуры неотличимо от поведения
подставного теста. У каждого положительного контроля есть обратный на ОДНОЙ оси:

* сосед ЖИВОЙ ⇒ «не измерено» · сосед МЁРТВЫЙ ⇒ имя названо (ось «живость»);
* писали в окне между тестами ⇒ «не измерено» · не писали ⇒ имя названо;
* сосед есть ⇒ имя не называется, но прогон КРАСНЕЕТ так же (инвариант #16:
  сторож уровня прогона не ослабляется, меняется только право назвать автора).

Дочерний прогон идёт с `PATH`, где есть `ps` и НЕТ `git`. Это не удобство, а
условие опыта: без git сторож наблюдает каталог целиком, и улику можно ставить
безобидную вместо настоящего журнала трека; а `ps` нужен, чтобы живость соседа
была ИЗМЕРЕНА, а не принята на веру, — иначе контроль зеленел бы и на мёртвом pid.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from spa_core.tests import _child_pytest
from spa_core.tests._freshness import ts

guard = sys.modules.get("spa_live_data_write_guard")
if guard is None:                                   # прямой запуск без conftest
    from spa_core.tests import live_data_write_guard as guard

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent

DECOY_NAME = f"_live_data_write_attribution_control_{os.getpid()}.json"

CHILD_WRITER = '''
import json
from pathlib import Path

DECOY = Path(r"{decoy}")


def test_writes_the_decoy():
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''

#: Два теста, ни один из которых не пишет; пишет ХУК между ними — то есть
#: заведомо не тест. Так окно «между тестами» воспроизводится детерминированно,
#: без гонки с фоновым процессом.
CHILD_CLEAN_PAIR = '''
def test_clean_one():
    assert 1 + 1 == 2


def test_clean_two():
    assert 3 * 3 == 9
'''

CHILD_CONFTEST_GAP_WRITER = '''
import json
from pathlib import Path

DECOY = Path(r"{decoy}")
_done = []


def pytest_runtest_logfinish(nodeid, location):
    # Позже фикстур теста и раньше следующего теста: ни один тест в этот момент
    # не идёт. Пишем ровно один раз, чтобы окно было одно.
    if _done:
        return
    _done.append(nodeid)
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''

#: Сосед был жив к НАЧАЛУ теста и снял объявление, пока тест шёл. Сказать, что
#: писал этот тест, нельзя: сосед работал ровно в то же время. Различает ТОЛЬКО
#: проверку ДО теста — после теста в дереве уже никого.
CHILD_WRITER_NEIGHBOUR_LEAVES = '''
import json
import os
from pathlib import Path

DECOY = Path(r"{decoy}")
ANNOUNCEMENT = Path(os.environ["SPA_ATTR_CONTROL_ANNOUNCEMENT"])


def test_writes_the_decoy():
    ANNOUNCEMENT.unlink()          # сосед доработал ПОСРЕДИ теста
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''

#: Зеркальный случай: соседа к началу теста не было, он объявился, пока тест
#: шёл. Различает ТОЛЬКО проверку ПОСЛЕ теста — до теста дерево было пустым.
CHILD_WRITER_NEIGHBOUR_ARRIVES = '''
import json
import os
from pathlib import Path

DECOY = Path(r"{decoy}")
ANNOUNCEMENT = Path(os.environ["SPA_ATTR_CONTROL_ANNOUNCEMENT"])
NEIGHBOUR_PID = int(os.environ["SPA_ATTR_CONTROL_NEIGHBOUR_PID"])


def test_writes_the_decoy():
    ANNOUNCEMENT.parent.mkdir(parents=True, exist_ok=True)
    ANNOUNCEMENT.write_text(          # сосед стартовал ПОСРЕДИ теста
        json.dumps(dict(pid=NEIGHBOUR_PID)), encoding="utf-8")
    payload = json.loads(DECOY.read_text(encoding="utf-8"))
    payload["count"] = payload["count"] + 2
    DECOY.write_text(json.dumps(payload), encoding="utf-8")
'''


def _ps_bin_dir():
    """Каталог с `ps` и БЕЗ `git` — см. докстринг модуля.

    Нет `ps` ⇒ падаем ГРОМКО, а не скипаем (#465). Здесь стоял `pytest.skip`, и
    направление было тем же дефектом, что и в `test_cycle_lock_watch._free_pid`:
    предпосылка этих контролей — ИЗМЕРЕННАЯ живость соседа (докстринг модуля:
    «иначе контроль зеленел бы и на мёртвом pid»), и снятие проверки делает «не
    измерено» неотличимым от «прошло» ровно там, где окружение необычно. Порядок
    `.claude/rules/deployment.md`: тест, не обеспечивший свою предпосылку, обязан
    сказать это вслух. На macOS и `ubuntu-latest` `ps` есть всегда, поэтому в
    штатном прогоне ветка не берётся ни разу и поведение не меняется.
    """
    real = shutil.which("ps")
    if real is None:
        raise AssertionError(
            "предпосылка теста не обеспечена: на этой машине нет `ps`, а живость "
            "соседа обязана быть ИЗМЕРЕНА — контроль не снимается, а падает")
    d = Path(tempfile.mkdtemp(prefix="spa_attr_bin_"))
    (d / "ps").symlink_to(real)
    return d


@pytest.fixture()
def tree(tmp_path):
    """Дерево, в которое кроме дочернего прогона не пишет НИКТО.

    Измерено циклом #415: пока эти контроли смотрели на `data/` настоящего
    репозитория, ЛЮБОЙ второй прогон в том же дереве (штатный способ работы
    сессии — полный прогон фоном плюс точечный) успевал записать живой файл
    внутрь окна одного из подставных тестов, и отчёт называл автором
    `test_clean_one` — ту самую ложную карту, против которой этот файл и написан.
    Запись, попавшая ВНУТРЬ окна теста, от записи самого теста неотличима по
    построению; объявления соседей эту дыру закрывают в проде, но здесь дочерний
    прогон намеренно слеп к объявлениям родителя (`RUNS_DIR_ENV`, цикл #411).

    Поэтому опыт ставится в своём дереве. Сторож определяет корень наблюдения
    как `Path(__file__).parents[2]`, так что достаточно положить его КОПИЮ в
    `<дерево>/spa_core/tests/` — и наблюдать он будет `<дерево>/data/`.
    Проверка при этом не ослабляется (инв. #16): предмет контролей — кого отчёт
    называет автором, а не в каком каталоге лежит улика.
    """
    root = tmp_path / "tree"
    (root / "spa_core" / "tests").mkdir(parents=True)
    for name in ("live_data_write_guard.py", "live_data_write_baseline.json"):
        shutil.copy(TESTS_DIR / name, root / "spa_core" / "tests" / name)
    return root


def _write_child(body, decoy, conftest=None):
    child_dir = Path(tempfile.mkdtemp(prefix="spa_live_data_attr_control_"))
    (child_dir / "test_writer.py").write_text(body.format(decoy=decoy), encoding="utf-8")
    if conftest is not None:
        (child_dir / "conftest.py").write_text(
            conftest.format(decoy=decoy), encoding="utf-8")
    return child_dir, child_dir / "test_writer.py"


def _run_child(test_file, runs_dir, out_path, bin_dir, tree, env_extra=None):
    env = dict(os.environ)
    # ТОЛЬКО копия сторожа из дерева опыта: возьмись он из настоящего
    # `spa_core/tests`, наблюдать он стал бы живой `data/` репозитория.
    env["PYTHONPATH"] = str(tree / "spa_core" / "tests")
    env["PATH"] = str(bin_dir)
    env[guard.AUDIT_ENV] = "1"
    env[guard.AUDIT_OUT_ENV] = str(out_path)
    env[guard.RUNS_DIR_ENV] = str(runs_dir)
    env.update(env_extra or {})
    return _child_pytest.run_child_pytest(
        test_file, "-q", "-p", "no:cacheprovider", "-p", "live_data_write_guard",
        cwd=tree, env=env, timeout=120,
    )


def _rows(out_path):
    text = Path(out_path).read_text(encoding="utf-8") if Path(out_path).exists() else ""
    return [json.loads(l) for l in text.splitlines() if l.strip()]


@pytest.fixture()
def decoy(tree):
    path = tree / "data" / DECOY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    # Отметка ОТНОСИТЕЛЬНАЯ (`.claude/rules/deployment.md`, приём #2). Содержимое
    # улики к предмету не относится вовсе — сторож смотрит, ИЗМЕНИЛСЯ ли файл, а не
    # что в нём, — но литеральная дата рядом со словами о свежести кладёт файл в
    # закрытый класс храповика (`test_frozen_date_ratchet`), и он покраснел на main
    # 28.08. Форму настоящего артефакта (поле-отметка) сохраняем: улика обязана быть
    # похожа на то, что живёт в `data/`.
    path.write_text(json.dumps({"updated_at": ts(hours_ago=1), "count": 26}),
                    encoding="utf-8")
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()


@pytest.fixture()
def bin_dir():
    d = _ps_bin_dir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def live_neighbour():
    """Настоящий живой процесс — сосед, которого дочерний прогон измерит `ps`-ом."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _announce(runs_dir, pid):
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{pid}.json").write_text(
        json.dumps({"pid": pid, "pid_start": guard.pid_start(pid),
                    "repo_root": str(REPO_ROOT), "started_at": time.time()}),
        encoding="utf-8")


# ---------------------------------------------------------------------------
# Положительный контроль №1: рядом ЖИВОЙ объявленный прогон
# ---------------------------------------------------------------------------

def test_live_neighbour_makes_the_report_refuse_to_name_a_nodeid(
        decoy, tree, tmp_path, bin_dir, live_neighbour):
    """Ровно жалоба карточки: сосед есть ⇒ имени в отчёте быть не должно."""
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    _announce(runs, live_neighbour.pid)
    child_dir, test_file = _write_child(CHILD_WRITER, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree)
        rows = _rows(out)
        assert rows, f"замер обязан хоть что-то записать: {run.stdout}{run.stderr}"
        assert all(r.get("nodeid") is None for r in rows), rows
        assert any(r.get("attribution") == guard.UNMEASURED for r in rows), rows
        assert any("прогон(а)" in (r.get("reason") or "") for r in rows), rows
        # Улику всё равно называют: «не измерено» про АВТОРА, а не про файл.
        assert any(DECOY_NAME in p for r in rows for p in r.get("paths", [])), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_run_still_goes_red_with_a_neighbour(decoy, tree, tmp_path, bin_dir, live_neighbour):
    """Инвариант #16: право назвать автора снято, СТОРОЖ не ослаблен."""
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    _announce(runs, live_neighbour.pid)
    child_dir, test_file = _write_child(CHILD_WRITER, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree)
        combined = run.stdout + run.stderr
        assert run.returncode != 0, combined
        assert DECOY_NAME in combined, combined
        assert "1 passed" in combined, combined     # красит ПРОГОН, а не тест
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Обратный контроль на оси «живость»: сосед МЁРТВЫЙ — имя называется
# ---------------------------------------------------------------------------

def test_dead_neighbour_does_not_block_attribution(decoy, tree, tmp_path, bin_dir):
    """Иначе «сосед блокирует» означало бы «любой файл блокирует».

    Одно упавшее объявление сделало бы карту неизмеримой навсегда — это тот же
    класс, что необратимое «не измерено», которым проект уже болел.
    """
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    _announce(runs, proc.pid)
    child_dir, test_file = _write_child(CHILD_WRITER, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree)
        rows = _rows(out)
        assert rows, f"без соседа замер обязан НАЗВАТЬ автора: {run.stdout}{run.stderr}"
        assert any("test_writes_the_decoy" in (r.get("nodeid") or "") for r in rows), rows
        assert not any(r.get("attribution") == guard.UNMEASURED for r in rows), rows
        assert not (runs / f"{proc.pid}.json").exists(), "мёртвое объявление обязано убраться"
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_solo_run_names_the_real_writer(decoy, tree, tmp_path, bin_dir):
    """Обратный контроль ко всему: одинокий прогон карту не потерял."""
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    child_dir, test_file = _write_child(CHILD_WRITER, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree)
        rows = _rows(out)
        assert rows, f"{run.stdout}{run.stderr}"
        assert any("test_writes_the_decoy" in (r.get("nodeid") or "") for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Положительный контроль №2: писали в окне МЕЖДУ тестами
# ---------------------------------------------------------------------------

def test_write_between_tests_makes_attribution_unmeasured(decoy, tree, tmp_path, bin_dir):
    """Писателя, которого никто не объявлял, ловит окно между тестами.

    На прод-хосте это главный случай: в `data/` непрерывно пишет флот из
    полусотни агентов, и ни один из них про объявления прогонов не знает.
    """
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    child_dir, test_file = _write_child(
        CHILD_CLEAN_PAIR, decoy, conftest=CHILD_CONFTEST_GAP_WRITER)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree)
        rows = _rows(out)
        assert rows, f"окно между тестами обязано попасть в отчёт: {run.stdout}{run.stderr}"
        assert all(r.get("nodeid") is None for r in rows), rows
        assert any("МЕЖДУ" in (r.get("reason") or "") for r in rows), rows
        # Ни один из двух тестов не писал — и ни один не назван.
        assert not any("test_clean" in json.dumps(r, ensure_ascii=False) for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_quiet_gap_keeps_attribution(decoy, tree, tmp_path, bin_dir):
    """Обратный контроль на той же оси: тихое окно права назвать автора не снимает."""
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    child_dir, test_file = _write_child(CHILD_WRITER, decoy)
    try:
        _run_child(test_file, runs, out, bin_dir, tree)
        rows = _rows(out)
        assert not any("МЕЖДУ" in (r.get("reason") or "") for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Положительный контроль №3: сосед пришёл/ушёл ПОСРЕДИ теста
#
# Мутационный замер цикла #415 на доставленном коде: снять проверку соседа ДО
# теста — 54 passed; снять проверку ПОСЛЕ — 54 passed. Две точки вызова
# заслоняли друг друга, и ни одна не была закреплена: сосед, стоявший всё время,
# ловится любой из них. Ниже — по контролю на каждую, на ОДНОЙ оси: соседа
# видно только в одном из двух окон.
# ---------------------------------------------------------------------------

def test_neighbour_that_leaves_mid_test_still_blocks_attribution(
        decoy, tree, tmp_path, bin_dir, live_neighbour):
    """Сосед был жив к началу теста и ушёл, пока тест шёл — имя называть нельзя.

    Он работал ровно в то же время, что и тест: кто из двоих писал — из разницы
    снимков не следует. Проверку ПОСЛЕ теста этот случай пройдёт мимо (в дереве
    уже никого), поэтому здесь красится ровно проверка ДО.
    """
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    _announce(runs, live_neighbour.pid)
    child_dir, test_file = _write_child(CHILD_WRITER_NEIGHBOUR_LEAVES, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree, env_extra={
            "SPA_ATTR_CONTROL_ANNOUNCEMENT": str(runs / f"{live_neighbour.pid}.json")})
        rows = _rows(out)
        assert rows, f"замер обязан хоть что-то записать: {run.stdout}{run.stderr}"
        assert all(r.get("nodeid") is None for r in rows), rows
        assert any(r.get("attribution") == guard.UNMEASURED for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


def test_neighbour_that_arrives_mid_test_still_blocks_attribution(
        decoy, tree, tmp_path, bin_dir, live_neighbour):
    """Зеркало: соседа не было к началу теста, он пришёл, пока тест шёл.

    Проверка ДО теста этот случай пройдёт мимо (дерево было пустым), поэтому
    здесь красится ровно повторная проверка ПОСЛЕ — та, ради которой она и
    стоит: «сосед мог стартовать, пока тест шёл».
    """
    runs = tmp_path / "runs"
    out = tmp_path / "audit.jsonl"
    runs.mkdir(parents=True, exist_ok=True)
    child_dir, test_file = _write_child(CHILD_WRITER_NEIGHBOUR_ARRIVES, decoy)
    try:
        run = _run_child(test_file, runs, out, bin_dir, tree, env_extra={
            "SPA_ATTR_CONTROL_ANNOUNCEMENT": str(runs / f"{live_neighbour.pid}.json"),
            "SPA_ATTR_CONTROL_NEIGHBOUR_PID": str(live_neighbour.pid)})
        rows = _rows(out)
        assert rows, f"замер обязан хоть что-то записать: {run.stdout}{run.stderr}"
        assert all(r.get("nodeid") is None for r in rows), rows
        assert any(r.get("attribution") == guard.UNMEASURED for r in rows), rows
        assert any("прогон(а)" in (r.get("reason") or "") for r in rows), rows
    finally:
        shutil.rmtree(child_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Механика объявлений — чистая часть
# ---------------------------------------------------------------------------

def test_announce_and_release_round_trip(tmp_path):
    marker = guard.announce_run(directory=tmp_path)
    assert marker is not None and marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["repo_root"] == str(guard.REPO_ROOT)
    guard.release_run(directory=tmp_path)
    assert not marker.exists()


def test_own_announcement_is_not_a_neighbour(tmp_path):
    """Прогон не смеет счесть соседом самого себя."""
    guard.announce_run(directory=tmp_path)
    assert guard.foreign_runs(directory=tmp_path) == ()


def test_unreadable_announcement_counts_as_a_neighbour(tmp_path):
    """Файл могли читать посреди записи. «Я не понял» ≠ «никого» — строгость."""
    (tmp_path / "424242.json").write_text("{не json", encoding="utf-8")
    assert guard.foreign_runs(directory=tmp_path) == (424242,)


def test_announcement_with_an_unparseable_name_counts_as_a_neighbour(tmp_path):
    """Имя не разбирается в pid ⇒ живость измерить нечем ⇒ строгость.

    Тот же ответ, что на нечитаемое СОДЕРЖИМОЕ, и по той же причине: «я не понял,
    чьё это объявление» — не «объявления нет». Мутационный замер цикла #415:
    без этой строки ветка молчала (54 passed), хотя ветка в коде была.
    """
    (tmp_path / "не-число.json").write_text(
        json.dumps({"pid": 1}), encoding="utf-8")
    assert guard.foreign_runs(directory=tmp_path) == ("не-число.json",)


def test_reused_pid_is_not_a_live_neighbour(tmp_path, monkeypatch):
    """Голый pid — бомба: ОС выдаёт номер заново, и мёртвый сосед оживал бы.

    Отметка старта процесса не сходится ⇒ это ДРУГОЙ процесс, объявление мёртвое.
    """
    monkeypatch.setattr(guard, "_liveness_cache", {})
    pid = os.getpid()
    (tmp_path / f"{pid + 1}.json").write_text(
        json.dumps({"pid": pid + 1, "pid_start": "Mon Jan  1 00:00:00 1990"}),
        encoding="utf-8")
    monkeypatch.setattr(guard, "pid_start", lambda p: "Fri Aug 28 12:00:00 2026")
    assert guard.foreign_runs(directory=tmp_path) == ()


def test_unmeasurable_liveness_counts_as_alive(tmp_path, monkeypatch):
    """`ps` недоступен ⇒ «процесса нет» неотличимо от «нечем спросить» ⇒ строгость."""
    monkeypatch.setattr(guard, "_liveness_cache", {})
    pid = os.getpid()
    (tmp_path / f"{pid + 1}.json").write_text(
        json.dumps({"pid": pid + 1, "pid_start": "неважно"}), encoding="utf-8")
    monkeypatch.setattr(guard, "pid_start", lambda p: None)
    assert guard.foreign_runs(directory=tmp_path) == (pid + 1,)


def test_runs_dir_is_keyed_by_the_tree(monkeypatch):
    """Два worktree — не соседи: у них разные `data/`, и писателя они не делят."""
    monkeypatch.delenv(guard.RUNS_DIR_ENV, raising=False)
    mine = guard.runs_dir()
    monkeypatch.setattr(guard, "REPO_ROOT", Path("/tmp/совсем-другое-дерево"))
    assert guard.runs_dir() != mine


def test_runs_dir_lives_outside_the_repo():
    """Объявление в дереве само пачкало бы то, что измеряется."""
    assert guard.REPO_ROOT not in guard.DEFAULT_RUNS_ROOT.parents


# ---------------------------------------------------------------------------
# Третий исход: форма записи и липкость
# ---------------------------------------------------------------------------

def test_unmeasured_record_names_no_nodeid(tmp_path):
    out = tmp_path / "audit.jsonl"
    guard.record_unmeasured("причина", ("data/alert_log.json",), out_path=out)
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["nodeid"] is None
    assert row["attribution"] == guard.UNMEASURED
    assert row["paths"] == ["data/alert_log.json"]


def test_block_is_sticky(monkeypatch, tmp_path):
    """Ушедший сосед не возвращает права называть автора.

    Писатель, замеченный однажды, может писать в любой момент, а карта, честная
    в половине строк, читается как честная во всех.
    """
    monkeypatch.setattr(guard, "_attribution_blocked", None)
    monkeypatch.setenv(guard.AUDIT_OUT_ENV, str(tmp_path / "a.jsonl"))
    monkeypatch.setattr(guard, "foreign_runs", lambda **k: (1, 2))
    assert guard.check_neighbours() is not None
    monkeypatch.setattr(guard, "foreign_runs", lambda **k: ())
    assert guard.check_neighbours() is not None


def test_first_reason_survives_a_second_block(monkeypatch, tmp_path):
    """Липкость запрета — свойство САМОГО `block_attribution`, не его звонящего.

    Мутация «снять липкость внутри `block_attribution`» оставляла набор ЗЕЛЁНЫМ:
    `test_block_is_sticky` идёт через `check_neighbours`, а тот возвращается
    раньше по собственному `if _attribution_blocked is not None`. Свойство держат
    ДВА условия, и звонящий заслоняет проверяемое — тот самый класс «в цепочке
    отказов условия заслоняют друг друга». Здесь ось ровно одна: функция зовётся
    напрямую, дважды, с разными причинами.

    Цена второго условия не косметическая: причина — это то, что читает человек.
    Перезапись оставила бы в отчёте ПОЗДНЮЮ причину («писали между тестами») там,
    где настоящая была РАНЬШЕ («в дереве идёт чужой прогон»), плюс вторую строку
    «не измерена» об одном и том же прогоне.
    """
    monkeypatch.setattr(guard, "_attribution_blocked", None)
    out = tmp_path / "audit.jsonl"
    monkeypatch.setenv(guard.AUDIT_OUT_ENV, str(out))

    first = guard.block_attribution("первая причина")
    assert guard.block_attribution("вторая причина") == first
    assert guard.attribution_blocked() == first

    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1, "второй запрет дописал ещё одну строку об одном прогоне"
    assert rows[0]["reason"] == "первая причина"
    assert rows[0]["nodeid"] is None


def test_between_tests_change_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "_attribution_blocked", None)
    monkeypatch.setattr(guard, "_last_after", {"data/x.json": (1, 2)})
    monkeypatch.setenv(guard.AUDIT_OUT_ENV, str(tmp_path / "a.jsonl"))
    reason = guard.check_between_tests({"data/x.json": (9, 2)})
    assert reason and "МЕЖДУ" in reason and guard.UNMEASURED in reason


def test_between_tests_quiet_does_not_block(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "_attribution_blocked", None)
    monkeypatch.setattr(guard, "_last_after", {"data/x.json": (1, 2)})
    monkeypatch.setenv(guard.AUDIT_OUT_ENV, str(tmp_path / "a.jsonl"))
    assert guard.check_between_tests({"data/x.json": (1, 2)}) is None


def test_first_test_has_no_gap_to_judge(monkeypatch, tmp_path):
    """До первого теста окна ещё нет — и выдумывать его нельзя."""
    monkeypatch.setattr(guard, "_attribution_blocked", None)
    monkeypatch.setattr(guard, "_last_after", None)
    assert guard.check_between_tests({"data/x.json": (1, 2)}) is None


# ---------------------------------------------------------------------------
# Объявления не копятся вечно
# ---------------------------------------------------------------------------

def test_abandoned_announcement_is_purged(tmp_path):
    """Прогон, снятый `SIGKILL`, своего объявления не снимает — каталог рос бы вечно.

    Разбирает объявления только режим замера, то есть редко; поэтому уборка
    висит на самом дешёвом действии — объявлении себя.
    """
    old = tmp_path / "111.json"
    old.write_text(json.dumps({"pid": 111, "started_at": time.time() - 48 * 3600}),
                   encoding="utf-8")
    assert guard.purge_stale_announcements(directory=tmp_path) == ("111.json",)
    assert not old.exists()


def test_a_running_announcement_is_not_purged(tmp_path):
    """Обратный контроль: свежее объявление уборка не трогает — иначе она чинила бы
    видимость, снимая ровно тех соседей, ради которых написана."""
    fresh = tmp_path / "222.json"
    fresh.write_text(json.dumps({"pid": 222, "started_at": time.time()}), encoding="utf-8")
    assert guard.purge_stale_announcements(directory=tmp_path) == ()
    assert fresh.exists()


def test_unreadable_announcement_is_aged_by_mtime(tmp_path):
    """«Не смогли прочитать» ≠ «удалить», но и копить нечитаемое вечно незачем."""
    broken = tmp_path / "333.json"
    broken.write_text("{не json", encoding="utf-8")
    os.utime(broken, (time.time() - 48 * 3600, time.time() - 48 * 3600))
    assert guard.purge_stale_announcements(directory=tmp_path) == ("333.json",)


def test_announcing_purges_the_abandoned(tmp_path):
    """Уборка обязана СЛУЧАТЬСЯ, а не просто существовать: её зовёт `announce_run`."""
    abandoned = tmp_path / "444.json"
    abandoned.write_text(json.dumps({"pid": 444, "started_at": time.time() - 48 * 3600}),
                         encoding="utf-8")
    guard.announce_run(directory=tmp_path)
    assert not abandoned.exists()
    guard.release_run(directory=tmp_path)
