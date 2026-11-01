"""S2 T08: установщик доверенной плоскости — ``trusted_repo`` в ``runtime.json`` и материализация релиза без
``rm -rf`` через проверку состава УСТАНОВЛЕННОГО лаунчера. Критерии H1–H4 (``S2_STATUS.md``).

Изолированно: режим ``--self-test-root`` гоняет ТЕ ЖЕ функции установщика (``materialise_release_dir``,
``write_runtime_json``) на временном каталоге пользователя; под root и на штатном корне он отказывает. Root,
права root:wheel и рабочий bootstrap этим НЕ проверяются (NOT MEASURED)."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from spa_core.studio_os import release_launcher as LNCH

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "scripts" / "install_trusted_bootstrap.sh"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path, files):
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    for rel, body in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(body)
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "release"], r)
    return r, _git(["rev-parse", "HEAD"], r)


FILES = {"spa_core/__init__.py": "", "spa_core/probe.py": "print('RELEASE')\n",
         LNCH.AGENT_ROLE_MANIFEST: json.dumps({"probe": "spa_core.probe"})}


def _install(root, repo, sha, launcher=None):
    launcher = launcher or Path(LNCH.__file__)
    lsha = hashlib.sha256(Path(launcher).read_bytes()).hexdigest()
    return subprocess.run(["bash", str(INSTALLER), "--self-test-root", str(root), "--launcher", str(launcher),
                           "--launcher-sha256", lsha, "--repo", str(repo), "--approved", sha,
                           "--self-test-app-python", sys.executable], capture_output=True, text=True)


def _digest(d: Path):
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode() + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def test_installer_writes_trusted_repo_and_a_release_the_launcher_proves(tmp_path):
    """H1/H2: runtime.json несёт trusted_repo; релиз доказан, и его же принимает лаунчер."""
    repo, sha = _repo(tmp_path, FILES)
    root = tmp_path / "root"
    root.mkdir()
    r = _install(root, repo, sha)
    assert r.returncode == 0, r.stderr + r.stdout
    rt = json.loads((root / "runtime.json").read_text())
    assert rt["trusted_repo"] == str(repo) and rt["app_python"] == sys.executable
    assert (root / "releases" / sha / ".release_sha").read_text() == sha
    assert LNCH.exec_root(sha, root / "releases", rt["trusted_repo"])[1] == "ACTIVATE_OK"
    plan = LNCH.main("agent:probe", root=root, python=[], active_path=tmp_path / "active.json")
    assert plan[0] == "EXEC_FROM_RELEASE" and plan[2] == str(root / "releases" / sha)


def test_existing_proven_release_is_reused_untouched(tmp_path):
    """H3: повторная установка — каталог доказан и не меняется ни байтом."""
    repo, sha = _repo(tmp_path, FILES)
    root = tmp_path / "root"
    root.mkdir()
    assert _install(root, repo, sha).returncode == 0
    before = _digest(root / "releases" / sha)
    r = _install(root, repo, sha)
    assert r.returncode == 0 and "reused untouched" in r.stdout and _digest(root / "releases" / sha) == before


def test_unproven_existing_release_is_kept_and_install_fails_closed(tmp_path):
    """H3: подменённый файл в существующем каталоге — установка отказывает, каталог сохранён как есть."""
    repo, sha = _repo(tmp_path, FILES)
    root = tmp_path / "root"
    root.mkdir()
    assert _install(root, repo, sha).returncode == 0
    victim = root / "releases" / sha / "spa_core" / "probe.py"
    victim.write_text("print('EVIL')\n")
    r = _install(root, repo, sha)
    assert r.returncode != 0 and "KEPT untouched" in r.stderr, r.stderr
    assert victim.read_text() == "print('EVIL')\n"


def test_reserved_but_empty_release_dir_is_kept_and_refused(tmp_path):
    """Незавершённая копия (каталог без содержимого и штампа) — отказ, каталог не удалён и не перезаписан."""
    repo, sha = _repo(tmp_path, FILES)
    root = tmp_path / "root"
    (root / "releases" / sha).mkdir(parents=True)
    r = _install(root, repo, sha)
    assert r.returncode != 0 and (root / "releases" / sha).is_dir() and not list((root / "releases" / sha).iterdir())


def test_fresh_materialisation_never_stamps_an_unproven_copy(tmp_path):
    """Случай, где извлечение НЕ равно коммиту: пара путей одного регистра с разным содержимым на ФС без
    различия регистра. Там — отказ, копия сохранена БЕЗ штампа; на чувствительной ФС — честный OK."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    for name, body in (("Doc.md", "upper\n"), ("doc.md", "lower\n")):
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(r), input=body, capture_output=True,
                              text=True).stdout.strip()
        _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"], r)
    _git(["commit", "-q", "-m", "collide"], r)
    sha = _git(["rev-parse", "HEAD"], r)
    root = tmp_path / "root"
    root.mkdir()
    probe = tmp_path / "CaseProbe"
    probe.write_text("")
    folds = (tmp_path / "caseprobe").exists()
    res = _install(root, r, sha)
    dest = root / "releases" / sha
    if folds:
        assert res.returncode != 0 and "copy KEPT, no stamp" in res.stderr, res.stderr
        assert dest.is_dir() and not (dest / ".release_sha").exists()
    else:
        assert res.returncode == 0 and (dest / ".release_sha").read_text() == sha


def test_self_test_mode_refuses_the_real_root(tmp_path):
    """H4: изолированный режим не работает на штатном корне (есть он на машине или нет)."""
    repo, sha = _repo(tmp_path, FILES)
    res = _install(Path(LNCH.TRUSTED_ROOT), repo, sha)
    assert res.returncode != 0 and "outside" in res.stderr


def test_release_step_of_the_installer_has_no_rm():
    """H2 статически: в функции материализации и шаге 4 нет удаления; одобрение — только sha."""
    src = INSTALLER.read_text()
    fn = src[src.index("materialise_release_dir(){"):src.index("write_runtime_json(){")]
    step4 = src[src.index("# 4) materialise the approved release"):src.index("# 5) approval file")]
    for part in (fn, step4):
        assert not re.search(r"\brm\s+-", part), part          # команда удаления, а не слово в тексте
    assert "launcher_composition" in fn and 'printf \'%s\' "$SHA" > "$DEST/.release_sha"' in fn
