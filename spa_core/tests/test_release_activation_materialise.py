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
    assert verdict == "OK" and RA.verify_release(path, sha, r) == (True, "")
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
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")  # A5


def test_incomplete_reservation_is_kept_and_refused(repo):
    r, sha, rel = repo
    (rel / sha / "pkg").mkdir(parents=True)                              # резерв без штампа (падение посередине)
    (rel / sha / "pkg" / "mod.py").write_text("VALUE = 'A'\n")
    before = _digest_tree(rel / sha)
    got, verdict = RA.materialise_release(sha, rel, r)
    assert got is None and verdict.startswith("RELEASE_DIR_INCOMPLETE"), verdict
    assert _digest_tree(rel / sha) == before
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")


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
    assert RA.exec_root(sha, rel, r) == (path, "ACTIVATE_OK")
    if tamper == "changed":
        (path / "README").write_text("tampered\n")
    elif tamper == "extra":
        (path / "pkg" / "injected.py").write_text("print('x')\n")
    elif tamper == "missing":
        os.rename(path / "README", r.parent / "README.moved")         # без удаления: файл вынесен
    elif tamper == "manifest":
        (path / ".release_manifest.json").write_text("{}")             # подложенный манифест — лишний файл
    elif tamper == "stamp":
        (path / RA.RELEASE_SHA_FILE).write_text("f" * 40)
    elif tamper == "link":
        os.rename(path / "link_to_mod", r.parent / "link.moved")
        os.symlink("README", path / "link_to_mod")
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")


def test_bytecode_in_the_release_is_an_extra_file_not_ignored(repo):
    """ИЗМЕНЁН НАМЕРЕННО (инв. #16, запись в docs/journal/2026-W44.md, 31.10). Прежняя форма утверждала, что
    ``__pycache__`` «не ломает доказательство», — это и была дыра: интерпретатор читает байткод РАНЬШЕ исходника,
    и подложенный .pyc исполнялся бы под видом одобренного релиза (самопроверка S2). Теперь исполнение идёт с
    ``-B``, а любой байткод в каталоге релиза — лишний файл состава."""
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    (path / "pkg" / "__pycache__").mkdir()
    (path / "pkg" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"\x00")
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")


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
    assert RA.verify_release(rel / sha, sha, r) == (True, "")


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
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")


def test_without_local_objects_a_release_is_not_proven_and_not_touched(repo, tmp_path):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    _git(["init", "-q", "-b", "main"], empty)
    # S2-01 (ARB раунд 5, изменено намеренно): без доверенного дерева коммита доказать каталог НЕЧЕМ —
    # ни «OK», ни подмены; каталог при этом не трогается.
    before = _digest_tree(path)
    assert RA.materialise_release(sha, rel, empty) == (None, "OBJECT_MISSING")
    assert _digest_tree(path) == before


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
        assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")
    else:
        assert verdict == "OK" and RA.verify_release(got, sha, r) == (True, "")


# ── S2-01 (ARB раунд 5): эталон состава — доверенное дерево ОДОБРЕННОГО коммита, а не манифест в каталоге ──
def _forge_manifest(path: Path, sha: str, files: dict):
    """Самосогласованная подделка: манифест перечисляет ровно то, что лежит в каталоге."""
    import json as _json
    (path / ".release_manifest.json").write_text(_json.dumps({"sha": sha, "files": files}))
    (path / RA.RELEASE_SHA_FILE).write_text(sha)


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _plan(sha, rel, r):
    return RA.activation_plan(approved_sha=sha, staged_sha=None, releases_dir=rel, repo=r)


def test_arbitrary_dir_with_a_self_consistent_manifest_is_not_activated(repo):
    """Воспроизведение ARB: каталог одобренного sha содержит произвольный файл, манифест и штамп согласованы."""
    r, sha, rel = repo
    d = rel / sha
    d.mkdir(parents=True)
    data = b"not the approved commit\n"
    (d / "arbitrary.txt").write_bytes(data)
    _forge_manifest(d, sha, {"arbitrary.txt": ["100644", _blob(data)]})
    assert _plan(sha, rel, r)["action"] != "EXEC_FROM_RELEASE"
    assert (d / "arbitrary.txt").read_bytes() == data                   # без удаления


def test_file_and_manifest_swapped_together_are_refused(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    data = b"VALUE = 'EVIL'\n"
    (path / "pkg" / "mod.py").write_bytes(data)
    import json as _json
    man = path / ".release_manifest.json"
    if man.exists():
        doc = _json.loads(man.read_text())
        doc["files"]["pkg/mod.py"] = ["100644", _blob(data)]
        man.write_text(_json.dumps(doc))
    assert _plan(sha, rel, r)["action"] != "EXEC_FROM_RELEASE"


def test_shortened_manifest_with_missing_file_is_refused(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    os.rename(path / "README", r.parent / "README.aside")
    import json as _json
    man = path / ".release_manifest.json"
    if man.exists():
        doc = _json.loads(man.read_text())
        doc["files"].pop("README", None)
        man.write_text(_json.dumps(doc))
    assert _plan(sha, rel, r)["action"] != "EXEC_FROM_RELEASE"


def test_correct_release_of_another_commit_renamed_to_the_approved_sha_is_refused(repo):
    r, sha_a, rel = repo
    (r / "pkg" / "mod.py").write_text("VALUE = 'B'\n")
    _git(["commit", "-qam", "B"], r)
    sha_b = _git(["rev-parse", "HEAD"], r).stdout.strip()
    path_b, verdict = RA.materialise_release(sha_b, rel, r)
    assert verdict == "OK"
    os.rename(path_b, rel / sha_a)                                       # честный релиз B под именем A
    for f in (rel / sha_a / RA.RELEASE_SHA_FILE,):
        f.write_text(sha_a)
    import json as _json
    man = rel / sha_a / ".release_manifest.json"
    if man.exists():
        doc = _json.loads(man.read_text())
        doc["sha"] = sha_a
        man.write_text(_json.dumps(doc))
    assert _plan(sha_a, rel, r)["action"] != "EXEC_FROM_RELEASE"


def test_mode_and_link_kind_are_part_of_the_composition(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    assert _plan(sha, rel, r)["action"] == "EXEC_FROM_RELEASE"          # положительный контроль
    os.chmod(path / "pkg" / "mod.py", 0o755)                             # режим 100644 → исполняемый
    assert _plan(sha, rel, r)["action"] != "EXEC_FROM_RELEASE"
    os.chmod(path / "pkg" / "mod.py", 0o644)
    target = os.readlink(path / "link_to_mod")
    os.rename(path / "link_to_mod", r.parent / "link.aside")
    (path / "link_to_mod").write_text(target)                            # ссылка → обычный файл с тем же текстом
    assert _plan(sha, rel, r)["action"] != "EXEC_FROM_RELEASE"


def test_no_local_objects_means_unverifiable_not_trusted(repo, tmp_path):
    r, sha, rel = repo
    RA.materialise_release(sha, rel, r)
    empty = tmp_path / "no_objects"
    empty.mkdir()
    _git(["init", "-q", "-b", "main"], empty)
    plan = _plan(sha, rel, empty)
    assert plan["action"] != "EXEC_FROM_RELEASE"
    assert RA.exec_root(sha, rel) == (None, "APPROVED_RELEASE_UNVERIFIABLE")   # «не проверено» ≠ «не совпало»
    assert RA.exec_root(sha, rel, empty) == (None, "APPROVED_RELEASE_UNVERIFIABLE")


def test_regular_file_replaced_by_a_link_to_identical_bytes_outside_is_refused(repo, tmp_path):
    """Содержимое по ссылке совпадает, но исполнение ушло бы ЗА пределы релиза: род пути — часть состава."""
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    outside = tmp_path / "outside_mod.py"
    outside.write_bytes((path / "pkg" / "mod.py").read_bytes())
    os.rename(path / "pkg" / "mod.py", tmp_path / "mod.aside")
    os.symlink(outside, path / "pkg" / "mod.py")
    assert RA.exec_root(sha, rel, r) == (None, "APPROVED_RELEASE_CORRUPT")
