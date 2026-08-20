"""Сторож `spa_core/data/` проверяется НАСТОЯЩЕЙ аварией, а не своим исходником.

Каждый тест здесь — положительный контроль к `_package_data_guard.py`:
воспроизводится ровно то, что делали 14 писателей до цикла #315 (вызов
`analyze()` без подмены пути лога под `cd spa_core`), и требуется, чтобы прогон
ПОКРАСНЕЛ и НАЗВАЛ виновника. Проверка, никогда не видевшая настоящей поломки, —
украшение (правило `.claude/rules/deployment.md`).

Эффект меряется в ДОЧЕРНЕМ процессе: сторож — autouse-фикстура, и внутри своего
же прогона его срабатывание неотличимо от падения самого теста
(урок `pytest-diversion-blinds-effect-tests`). Обратный контроль — тот же
дочерний прогон БЕЗ плагина: он зелёный, значит краснота приходит от сторожа,
а не от подставного теста.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Тот САМЫЙ объект, который зарегистрировал conftest (он грузит модуль по пути
# к файлу под именем `spa_package_data_guard`). Вторая копия сторожа проверяла бы
# не то, что работает в прогоне.
guard = sys.modules.get("spa_package_data_guard")
if guard is None:                                   # прямой запуск без conftest
    from spa_core.tests import _package_data_guard as guard

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent

#: Имя улики. Уникально по pid, чтобы параллельные прогоны не мешали друг другу.
JUNK_NAME = f"_package_data_guard_positive_control_{os.getpid()}.json"

CHILD_TEST = '''
from pathlib import Path

PKG_DATA = Path(r"{pkg_data}")


def test_writes_into_package_data():
    PKG_DATA.mkdir(parents=True, exist_ok=True)
    (PKG_DATA / "{junk}").write_text("[]", encoding="utf-8")
    assert (PKG_DATA / "{junk}").exists()
'''


def _run_child(test_file: Path, with_guard: bool):
    """Дочерний pytest на подставном тесте; плагин подключается по требованию."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), str(TESTS_DIR), env.get("PYTHONPATH", "")]
    )
    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"]
    if with_guard:
        cmd += ["-p", "_package_data_guard"]
    # Потолок узкий НАМЕРЕННО: здоровый прогон занимает доли секунды (замер #315),
    # и зависший дочерний pytest обязан назваться быстро, а не съесть цикл.
    return subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120
    )


# ---------------------------------------------------------------------------
# Чистая часть: что считается «появилось»
# ---------------------------------------------------------------------------

def test_new_files_names_only_what_appeared():
    before = {"apy_history.json", "covariance_summary.json"}
    after = before | {"vault_strategy_log.json", "whale_impact_log.json"}
    assert guard.new_files(before, after) == (
        "vault_strategy_log.json",
        "whale_impact_log.json",
    )


def test_unchanged_directory_is_not_a_finding():
    """Обратный контроль: сторож не обязан краснеть на тракте без записи."""
    names = {"apy_history.json"}
    assert guard.new_files(names, names) == ()


def test_disappeared_file_is_not_a_finding():
    """Сторож отвечает на «появилось», а не на «изменилось» — удаление не его вопрос."""
    assert guard.new_files({"a.json", "b.json"}, {"a.json"}) == ()


def test_snapshot_of_missing_directory_is_empty(tmp_path):
    assert guard.snapshot(tmp_path / "нет-такого-каталога") == frozenset()


def test_snapshot_sees_what_lies_in_the_directory(tmp_path):
    (tmp_path / "x.json").write_text("[]", encoding="utf-8")
    assert guard.snapshot(tmp_path) == frozenset({"x.json"})


# ---------------------------------------------------------------------------
# Каталог берётся от файла, а не от cwd
# ---------------------------------------------------------------------------

def test_guarded_directory_is_the_package_dir(monkeypatch, tmp_path):
    """Авария случалась ИМЕННО из-за cwd — сторож не имеет права от него зависеть.

    Шаг CI «Run spa_core/tests» стартует из `cd spa_core`, а разработчик гоняет
    тот же набор из корня репо. Сторож обязан смотреть в один и тот же каталог
    в обоих случаях.
    """
    expected = REPO_ROOT / "spa_core" / "data"
    assert guard.PACKAGE_DATA_DIR == expected
    monkeypatch.chdir(tmp_path)
    assert guard.PACKAGE_DATA_DIR == expected


def test_failure_message_names_the_test_and_the_file():
    msg = guard.failure_message("tests/test_x.py::test_y", ("vault_strategy_log.json",))
    assert "tests/test_x.py::test_y" in msg
    assert "vault_strategy_log.json" in msg
    assert "reap_stale_worktrees" in msg


# ---------------------------------------------------------------------------
# Положительный контроль: настоящая авария в дочернем процессе
# ---------------------------------------------------------------------------

def test_child_run_goes_red_and_names_the_writer():
    """Подставной тест пишет в spa_core/data — прогон со сторожем обязан упасть.

    Каталог для подставного теста берётся `tempfile.mkdtemp()`, а НЕ фикстурой
    `tmp_path`. Замер #315: дочерний pytest, чей файл лежит внутри basetemp
    родителя (`.../pytest-of-<user>/pytest-N/...`), не доходит даже до
    `--collect-only` — 300 с и таймаут; тот же файл вне этого дерева отрабатывает
    за 0.00 с. Родство каталогов здесь не деталь оформления, а условие, при
    котором положительный контроль вообще выполним.
    """
    junk = guard.PACKAGE_DATA_DIR / JUNK_NAME
    child_dir = Path(tempfile.mkdtemp(prefix="spa_package_data_guard_control_"))
    test_file = child_dir / "test_writer.py"
    test_file.write_text(
        CHILD_TEST.format(pkg_data=guard.PACKAGE_DATA_DIR, junk=JUNK_NAME),
        encoding="utf-8",
    )
    try:
        with_guard = _run_child(test_file, with_guard=True)
        without_guard = _run_child(test_file, with_guard=False)

        combined = with_guard.stdout + with_guard.stderr
        assert with_guard.returncode != 0, combined
        assert JUNK_NAME in combined, combined
        assert "test_writes_into_package_data" in combined, combined

        # Обратный контроль: без сторожа тот же тест ЗЕЛЁНЫЙ — значит краснота
        # приходит от сторожа, а не от подставного теста.
        assert without_guard.returncode == 0, without_guard.stdout + without_guard.stderr
    finally:
        if junk.exists():
            junk.unlink()
        shutil.rmtree(child_dir, ignore_errors=True)

    # Улику убрал сам тест, а не сторож: сторож НАЗЫВАЕТ и ничего не прячет.
    assert not junk.exists()
