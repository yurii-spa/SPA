"""S2 задача 02 (E5.3): встроенный resolver лаунчера проверяет состав релиза по ДОВЕРЕННОМУ дереву коммита.

Критерии B1–B8 пакета ``docs/evidence/studio-autonomy-01-2026-10-29/s2/TASK_02_launcher_trusted_tree.md`` (до кода).
Герметично: одноразовый git-репозиторий, «root plane» и каталог релизов — под tmp_path. Ничего не исполняется:
``main`` в тестовом режиме только возвращает план (``python`` — список-приёмник).
"""
import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH


def _git(args, cwd, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, **kw)


def _commit(repo: Path, files: dict, msg: str) -> str:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", msg], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


@pytest.fixture
def scene(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    os.makedirs(repo / "spa_core", exist_ok=True)
    sha_a = _commit(repo, {"spa_core/__init__.py": "", "spa_core/app.py": "print('A')\n",
                           "studio_release_agents.json": json.dumps({"prober": "spa_core.app"})}, "A")
    os.symlink("app.py", repo / "spa_core" / "link_to_app")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "A+link"], repo)
    sha_a = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    root = tmp_path / "trusted_root"
    (root / "releases").mkdir(parents=True)
    (root / "runtime.json").write_text(json.dumps({"app_python": "/usr/bin/false",
                                                   "trusted_repo": str(repo)}))
    return {"repo": repo, "sha": sha_a, "root": root, "releases": root / "releases",
            "active": tmp_path / "active.json"}


def _approve(scene, sha):
    (scene["root"] / "approved_release.json").write_text(json.dumps({"approved_sha": sha}))


def _run(scene, service="agent:prober"):
    return LNCH.main(service, root=scene["root"], python=[], active_path=scene["active"])


# ── B1: воспроизведение ARB S2-01 против лаунчера ────────────────────────────────────────────────
def test_arbitrary_dir_with_a_stamp_and_a_self_consistent_manifest_is_not_executed(scene):
    sha = scene["sha"]
    d = scene["releases"] / sha
    d.mkdir()
    data = b"print('not the approved commit')\n"
    (d / "spa_core").mkdir()
    (d / "spa_core" / "app.py").write_bytes(data)
    roles = json.dumps({"prober": "spa_core.app"}).encode()
    (d / "studio_release_agents.json").write_bytes(roles)
    blob = lambda b: hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()  # noqa: E731
    (d / ".release_manifest.json").write_text(json.dumps(
        {"sha": sha, "files": {"spa_core/app.py": ["100644", blob(data)],
                               "studio_release_agents.json": ["100644", blob(roles)]}}))
    (d / LNCH.RELEASE_SHA_FILE).write_text(sha)
    _approve(scene, sha)
    r = _run(scene)
    assert r == ("FAIL_CLOSED", "APPROVED_RELEASE_CORRUPT"), r
    assert not scene["active"].exists()                                  # до исполнения ничего не записано
    assert (d / "spa_core" / "app.py").read_bytes() == data              # без удаления


# ── B2: верный релиз исполняется ─────────────────────────────────────────────────────────────────
def test_genuine_release_of_the_approved_commit_executes(scene):
    path, verdict = RA.materialise_release(scene["sha"], scene["releases"], scene["repo"])
    assert verdict == "OK"
    _approve(scene, scene["sha"])
    r = _run(scene)
    assert r[0] == "EXEC_FROM_RELEASE" and r[2] == str(path), r
    assert _run(scene)[0] == "EXEC_FROM_RELEASE"                          # повтор — без изменений


# ── B3: подмены состава ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tamper", ["changed", "extra", "missing", "mode", "link_to_file",
                                    "file_to_link", "other_commit"])
def test_tampered_release_is_refused(scene, tamper):
    sha = scene["sha"]
    path, _ = RA.materialise_release(sha, scene["releases"], scene["repo"])
    _approve(scene, sha)
    assert _run(scene)[0] == "EXEC_FROM_RELEASE"                          # положительный контроль
    aside = scene["root"].parent / "aside"
    aside.mkdir(exist_ok=True)
    if tamper == "changed":
        (path / "spa_core" / "app.py").write_text("print('EVIL')\n")
    elif tamper == "extra":
        (path / "spa_core" / "injected.py").write_text("print('x')\n")
    elif tamper == "missing":
        os.rename(path / "spa_core" / "app.py", aside / "app.py")
    elif tamper == "mode":
        os.chmod(path / "spa_core" / "app.py", 0o755)
    elif tamper == "link_to_file":
        os.rename(path / "spa_core" / "link_to_app", aside / "link")
        (path / "spa_core" / "link_to_app").write_text("app.py")
    elif tamper == "file_to_link":
        outside = aside / "app_copy.py"
        outside.write_bytes((path / "spa_core" / "app.py").read_bytes())
        os.rename(path / "spa_core" / "app.py", aside / "app.moved")
        os.symlink(outside, path / "spa_core" / "app.py")
    elif tamper == "other_commit":
        sha_b = _commit(scene["repo"], {"spa_core/app.py": "print('B')\n"}, "B")
        path_b, _ = RA.materialise_release(sha_b, scene["releases"], scene["repo"])
        os.rename(path, aside / "a_release")
        os.rename(path_b, path)
        (path / LNCH.RELEASE_SHA_FILE).write_text(sha)                    # штамп переписан на одобренный
    r = _run(scene)
    assert r == ("FAIL_CLOSED", "APPROVED_RELEASE_CORRUPT"), r


# ── B4: подмена объекта через refs/replace не меняет эталон ──────────────────────────────────────
def test_replace_ref_in_the_repository_cannot_substitute_the_reference(scene):
    """Злоумышленник с правом записи в репозиторий подменяет дерево одобренного коммита через `git replace`
    так, чтобы «эталон» совпал с поддельным каталогом. Эталон обязан остаться деревом настоящего коммита."""
    sha = scene["sha"]
    repo = scene["repo"]
    # поддельное содержимое и коммит с тем же сообщением, которым подменим настоящий
    forged_tree_repo = repo
    real_tree = _git(["rev-parse", f"{sha}^{{tree}}"], repo).stdout.strip()
    (repo / "spa_core" / "app.py").write_text("print('EVIL')\n")
    _git(["add", "-A"], repo)
    forged_tree = _git(["write-tree"], repo).stdout.strip()
    assert forged_tree != real_tree
    r = _git(["replace", real_tree, forged_tree], repo)
    assert r.returncode == 0, r.stderr
    assert _git(["ls-tree", "-r", sha, "spa_core/app.py"], forged_tree_repo).stdout.split()[2] != \
        _git(["--no-replace-objects", "ls-tree", "-r", sha, "spa_core/app.py"], repo).stdout.split()[2]
    # каталог релиза собран по ПОДМЕНЁННОМУ дереву (как его увидел бы наивный ls-tree)
    d = scene["releases"] / sha
    (d / "spa_core").mkdir(parents=True)
    (d / "spa_core" / "__init__.py").write_text("")
    (d / "spa_core" / "app.py").write_text("print('EVIL')\n")
    os.symlink("app.py", d / "spa_core" / "link_to_app")
    (d / "studio_release_agents.json").write_text(json.dumps({"prober": "spa_core.app"}))
    (d / LNCH.RELEASE_SHA_FILE).write_text(sha)
    _approve(scene, sha)
    assert _run(scene) == ("FAIL_CLOSED", "APPROVED_RELEASE_CORRUPT")


# ── B5: нет доверенного эталона ─────────────────────────────────────────────────────────────────
def test_no_trusted_repo_is_unverifiable_and_fails_closed(scene):
    RA.materialise_release(scene["sha"], scene["releases"], scene["repo"])
    _approve(scene, scene["sha"])
    (scene["root"] / "runtime.json").write_text(json.dumps({"app_python": "/usr/bin/false"}))
    assert _run(scene) == ("FAIL_CLOSED", "APPROVED_RELEASE_UNVERIFIABLE")
    assert not scene["active"].exists()


def test_repo_without_the_object_is_unverifiable(scene, tmp_path):
    RA.materialise_release(scene["sha"], scene["releases"], scene["repo"])
    _approve(scene, scene["sha"])
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    _git(["init", "-q", "-b", "main"], empty)
    (scene["root"] / "runtime.json").write_text(json.dumps({"app_python": "/usr/bin/false",
                                                           "trusted_repo": str(empty)}))
    assert _run(scene) == ("FAIL_CLOSED", "APPROVED_RELEASE_UNVERIFIABLE")


# ── B6: TRUST CLOSURE — лаунчер не импортирует изменяемый код ────────────────────────────────────
def test_launcher_imports_nothing_from_spa_core():
    tree = ast.parse(Path(LNCH.__file__).read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert not any(m.startswith("spa_core") for m in mods), mods


def test_tampered_object_store_is_unverifiable_not_trusted(scene):
    """Подмена САМОГО хранилища объектов: файл объекта дерева одобренного коммита переписан сжатым чужим
    деревом. git отдаёт подменённые байты под прежним именем; доверие держится на перепроверке sha1 объекта."""
    import zlib
    sha, repo = scene["sha"], scene["repo"]
    real_tree = _git(["rev-parse", f"{sha}^{{tree}}"], repo).stdout.strip()
    (repo / "spa_core" / "app.py").write_text("print('EVIL')\n")
    _git(["add", "-A"], repo)
    forged_tree = _git(["write-tree"], repo).stdout.strip()
    forged = subprocess.run(["git", "cat-file", "tree", forged_tree], cwd=str(repo),
                            capture_output=True).stdout
    loose = repo / ".git" / "objects" / real_tree[:2] / real_tree[2:]
    assert loose.is_file(), "сцена: объект дерева должен быть свободным (не в паке)"
    os.chmod(loose, 0o644)
    loose.write_bytes(zlib.compress(b"tree %d\0" % len(forged) + forged))
    d = scene["releases"] / sha                                           # каталог = подменённое дерево
    (d / "spa_core").mkdir(parents=True)
    (d / "spa_core" / "__init__.py").write_text("")
    (d / "spa_core" / "app.py").write_text("print('EVIL')\n")
    os.symlink("app.py", d / "spa_core" / "link_to_app")
    (d / "studio_release_agents.json").write_text(json.dumps({"prober": "spa_core.app"}))
    (d / LNCH.RELEASE_SHA_FILE).write_text(sha)
    _approve(scene, sha)
    assert _run(scene) == ("FAIL_CLOSED", "APPROVED_RELEASE_UNVERIFIABLE")
