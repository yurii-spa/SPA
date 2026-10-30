"""S2 задача 01 (STUDIO-AUTONOMY-01, E5.3): материализация релиза без удаления и с проверкой состава.

Критерии A2–A6 пакета ``docs/evidence/studio-autonomy-01-2026-10-29/s2/TASK_01_release_materialise.md``
(зафиксирован ДО кода). Герметично: одноразовый git-репозиторий и каталог релизов под tmp_path.
Прод-дерево, launchd и сеть не трогаются.
"""
import ast
import hashlib
import multiprocessing as mp
import os
import subprocess
from pathlib import Path

import pytest

from spa_core.studio_os import release_activation as RA

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "tree"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    (r / "pkg").mkdir()
    (r / "pkg" / "mod.py").write_text("VALUE = 'A'\n")
    (r / "README").write_text("release A\n")
    os.symlink("pkg/mod.py", r / "link_to_mod")
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "A"], r)
    sha = _git(["rev-parse", "HEAD"], r).stdout.strip()
    return r, sha, tmp_path / "releases"


def _digest_tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            out[str(p.relative_to(root))] = "link:" + os.readlink(p)
        elif p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ── A2: голых подъёмов в модуле нет ─────────────────────────────────────────────────────────────
def test_no_bare_raises_in_release_activation():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_spaerror_guard",
                                                  REPO_ROOT / "tests" / "test_spaerror_complete.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    found = [v for v in guard.bare_raises(REPO_ROOT / "spa_core") if "release_activation.py" in v]
    assert found == [], found


# ── A3: в модуле нет удаления ──────────────────────────────────────────────────────────────────
def test_module_never_deletes():
    tree = ast.parse((REPO_ROOT / "spa_core" / "studio_os" / "release_activation.py").read_text())
    banned_attrs = {"rmtree", "remove", "unlink", "rmdir", "removedirs"}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in banned_attrs:
            hits.append(f"{node.attr}@{node.lineno}")
        if isinstance(node, ast.Constant) and node.value == "rm":
            hits.append(f"'rm'@{node.lineno}")
    assert hits == [], hits


# ── A4: каталоги сохраняются, отказ назван ──────────────────────────────────────────────────────
def test_fresh_materialise_is_proven_and_repeat_changes_nothing(repo):
    r, sha, rel = repo
    path, verdict = RA.materialise_release(sha, rel, r)
    assert verdict == "OK" and RA.verify_release(path, sha) == (True, "")
    before = _digest_tree(path)
    again, verdict2 = RA.materialise_release(sha, rel, r)
    assert (again, verdict2) == (path, "OK")
    assert _digest_tree(path) == before                                 # ни байта не изменено


def test_corrupt_existing_release_is_kept_and_refused(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    (path / "pkg" / "mod.py").write_text("VALUE = 'B'\n")                # подмена файла артефакта
    before = _digest_tree(path)
    got, verdict = RA.materialise_release(sha, rel, r)
    assert got is None and verdict.startswith("RELEASE_DIR_CORRUPT"), verdict
    assert _digest_tree(path) == before                                 # повреждённая копия сохранена
    assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_CORRUPT")  # A5


def test_incomplete_reservation_is_kept_and_refused(repo):
    r, sha, rel = repo
    (rel / sha / "pkg").mkdir(parents=True)                              # резерв без штампа (падение посередине)
    (rel / sha / "pkg" / "mod.py").write_text("VALUE = 'A'\n")
    before = _digest_tree(rel / sha)
    got, verdict = RA.materialise_release(sha, rel, r)
    assert got is None and verdict.startswith("RELEASE_DIR_INCOMPLETE"), verdict
    assert _digest_tree(rel / sha) == before
    assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_CORRUPT")


def test_missing_object_creates_nothing(repo):
    r, _sha, rel = repo
    got, verdict = RA.materialise_release("0" * 40, rel, r)
    assert (got, verdict) == (None, "OBJECT_MISSING")
    assert not rel.exists() or not any(rel.iterdir())


# ── A5: состав по хешам, а не по штампу ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("tamper", ["changed", "extra", "missing", "manifest", "stamp", "link"])
def test_exec_root_proves_composition_not_just_the_stamp(repo, tamper):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    assert RA.exec_root(sha, rel) == (path, "ACTIVATE_OK")
    if tamper == "changed":
        (path / "README").write_text("tampered\n")
    elif tamper == "extra":
        (path / "pkg" / "injected.py").write_text("print('x')\n")
    elif tamper == "missing":
        os.rename(path / "README", r.parent / "README.moved")         # без удаления: файл вынесен
    elif tamper == "manifest":
        (path / RA.MANIFEST_FILE).write_text("{}")
    elif tamper == "stamp":
        (path / RA.RELEASE_SHA_FILE).write_text("f" * 40)
    elif tamper == "link":
        os.rename(path / "link_to_mod", r.parent / "link.moved")
        os.symlink("README", path / "link_to_mod")
    assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_CORRUPT")


def test_bytecode_written_by_execution_does_not_break_the_proof(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    (path / "pkg" / "__pycache__").mkdir()
    (path / "pkg" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"\x00")
    assert RA.exec_root(sha, rel) == (path, "ACTIVATE_OK")


# ── A6: два процесса — один создаёт, другой не подменяет ────────────────────────────────────────
def _racer(sha, rel, r, out):
    out.put(RA.materialise_release(sha, rel, r)[1])


def test_two_processes_materialise_the_same_sha_without_substitution(repo):
    r, sha, rel = repo
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    ps = [ctx.Process(target=_racer, args=(sha, rel, r, out)) for _ in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    verdicts = [out.get(timeout=5) for _ in ps]
    assert "OK" in verdicts
    assert all(v == "OK" or v.startswith("RELEASE_DIR_INCOMPLETE") for v in verdicts), verdicts
    assert sorted(p.name for p in rel.iterdir()) == [sha]               # один каталог, без временных
    assert RA.verify_release(rel / sha, sha) == (True, "")


def test_archive_that_differs_from_the_commit_tree_is_refused_and_kept(tmp_path):
    """``export-ignore`` выкидывает файл из ``git archive``: каталог НЕ равен коммиту — отказ, копия сохранена."""
    r = tmp_path / "tree"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    (r / "keep.py").write_text("X = 1\n")
    (r / "secret.txt").write_text("not exported\n")
    (r / ".gitattributes").write_text("secret.txt export-ignore\n")
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "A"], r)
    sha = _git(["rev-parse", "HEAD"], r).stdout.strip()
    rel = tmp_path / "releases"
    got, verdict = RA.materialise_release(sha, rel, r)
    assert got is None and verdict.startswith("MATERIALISE_FAILED:состав не совпал"), verdict
    assert (rel / sha / "keep.py").exists()                             # незавершённая копия сохранена
    assert not (rel / sha / RA.RELEASE_SHA_FILE).exists()               # и исполнению не подлежит
    assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_CORRUPT")


def test_proven_release_is_returned_even_when_the_object_is_no_longer_local(repo, tmp_path):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    _git(["init", "-q", "-b", "main"], empty)
    assert RA.materialise_release(sha, rel, empty) == (path, "OK")      # готовый доказанный — без git


def test_case_colliding_paths_never_yield_a_silently_wrong_release(tmp_path):
    """Находка 30.10 на настоящем коммите SPA: ``docs/API_REFERENCE.md`` и ``docs/api_reference.md``. На ФС без
    различия регистра (macOS по умолчанию) извлечение склеивает их — релиз НЕ равен коммиту. Исход зависит от ФС
    и назван: чувствительная — ``OK`` с доказанным составом; нечувствительная — отказ, копия сохранена. Ложного
    ``OK`` нет ни там, ни там."""
    r = tmp_path / "tree"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    for name, body in (("Doc.md", "upper\n"), ("doc.md", "lower\n")):   # пути вносятся в индекс напрямую
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(r), input=body,
                              capture_output=True, text=True).stdout.strip()
        _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"], r)
    _git(["commit", "-q", "-m", "collide"], r)
    sha = _git(["rev-parse", "HEAD"], r).stdout.strip()
    rel = tmp_path / "releases"
    probe = tmp_path / "CaseProbe"
    probe.write_text("")
    case_insensitive = (tmp_path / "caseprobe").exists()
    got, verdict = RA.materialise_release(sha, rel, r)
    if case_insensitive:
        assert got is None and "состав не совпал" in verdict, verdict
        assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_CORRUPT")
    else:
        assert verdict == "OK" and RA.verify_release(got, sha) == (True, "")
