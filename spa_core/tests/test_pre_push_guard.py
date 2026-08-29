"""Пуш не имеет права терять коммиты — сторож `scripts/pre_push_check.sh`.

# LLM_FORBIDDEN

Каждый тест — авария 2026-08-29: сессия сделала `git commit` в прод-дереве,
родителем оказалась устаревшая локальная голова, форсированный пуш откатил
`main` на **1249 коммитов**.

Правило «пушить только через push_to_github.py» существовало в CLAUDE.md и не
сработало: у правила не было исполнителя. Здесь проверяется исполнитель.

Тесты офлайн и самодостаточны: «удалённый» репозиторий — bare-каталог во
временной папке, сеть не нужна. Живое дерево проекта не читается и не пишется.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "scripts" / "pre_push_check.sh"
ZERO = "0" * 40


def _git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    r = subprocess.run(["git", *args], cwd=cwd, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _run_hook(repo: Path, local_sha: str, remote_sha: str, *, env_extra=None):
    stdin = f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n"
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run(["bash", str(HOOK), "origin"], cwd=repo, input=stdin,
                          capture_output=True, text=True, env=env)


@pytest.fixture()
def world(tmp_path):
    """Сервер с тремя коммитами и ОТСТАВШАЯ рабочая копия со своим коммитом."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))

    up = tmp_path / "up"
    _git(tmp_path, "clone", "-q", str(remote), str(up))
    c1 = _commit(up, "c1")
    _commit(up, "c2")
    c3 = _commit(up, "c3")
    _git(up, "push", "-q", "origin", "main")

    stale = tmp_path / "stale"
    _git(tmp_path, "clone", "-q", str(remote), str(stale))
    _git(stale, "reset", "-q", "--hard", c1)          # отстал на два коммита
    own = _commit(stale, "own")                        # и сделал свой поверх
    return {"remote": remote, "up": up, "stale": stale, "c1": c1, "c3": c3, "own": own}


def test_the_2026_08_29_shape_is_refused(world):
    """Положительный контроль: ровно та форма, что стоила 1249 коммитов."""
    r = _run_hook(world["stale"], world["own"], world["c1"])
    assert r.returncode == 1, r.stdout
    assert "стёр бы 2 коммит" in r.stdout, r.stdout
    assert "push_to_github.py" in r.stdout, "отказ обязан называть правильный путь"


def test_a_fast_forward_is_allowed(world):
    """Обратный контроль: сторож, который запрещает всё, — не сторож."""
    nxt = _commit(world["up"], "c4")
    r = _run_hook(world["up"], nxt, world["c3"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_pushing_what_is_already_there_is_allowed(world):
    r = _run_hook(world["up"], world["c3"], world["c3"])
    assert r.returncode == 0, r.stdout


def test_other_branches_are_not_guarded(world):
    """Хук сторожит main, а не всякую ветку — иначе его снимут целиком."""
    stdin = f"refs/heads/feature {world['own']} refs/heads/feature {world['c1']}\n"
    r = subprocess.run(["bash", str(HOOK), "origin"], cwd=world["stale"],
                       input=stdin, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_branch_deletion_is_refused(world):
    r = _run_hook(world["stale"], ZERO, world["c3"])
    assert r.returncode == 1 and "удаление ветки" in r.stdout


def test_unreachable_server_fails_closed(world, tmp_path):
    """«Не измерено» никогда не равно «безопасно»."""
    _git(world["stale"], "remote", "set-url", "origin", str(tmp_path / "нет-такого.git"))
    r = _run_hook(world["stale"], world["own"], world["c1"])
    assert r.returncode == 1, r.stdout
    assert "НЕЧЕМ" in r.stdout, "отказ обязан назвать причину, а не молчать"


def test_stale_remote_tracking_ref_does_not_fool_the_guard(world):
    """Ключевое: истину спрашиваем у СЕРВЕРА, а не у remote-tracking ссылки.

    Авария и произошла на устаревшей ссылке. Здесь git «сообщает» хуку, что на
    сервере лежит c1 (как и было в тот раз) — а на сервере c3.
    """
    r = _run_hook(world["stale"], world["own"], world["c1"])
    assert r.returncode == 1 and "стёр бы 2" in r.stdout


def test_escape_hatch_is_explicit_and_loud(world):
    r = _run_hook(world["stale"], world["own"], world["c1"],
                  env_extra={"SPA_ALLOW_HISTORY_REWRITE": "1"})
    assert r.returncode == 0
    assert "ОТКЛЮЧЕНА" in r.stdout, "обход обязан быть слышен, а не тих"


def test_hook_is_executable_and_installed_by_the_installer():
    assert os.access(HOOK, os.X_OK), "хук без бита исполнения — мёртвый хук (урок 04.08)"
    installer = HOOK.parent / "install_git_hooks.sh"
    assert "pre_push_check.sh" in installer.read_text(encoding="utf-8"), (
        "новый сторож не подключён установщиком — он не доедет ни до одного дерева")
