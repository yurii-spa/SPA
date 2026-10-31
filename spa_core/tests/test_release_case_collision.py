"""S2 задача 03 (E5.3): пара путей, различающихся только регистром, с одинаковыми режимом и blob не блокирует
честный релиз на ФС без различия регистра — и не открывает подмену.

Критерии C3–C5 пакета ``docs/evidence/studio-autonomy-01-2026-10-29/s2/TASK_03_case_collision.md`` (до кода).
Исход зависит от ФС и меряется пробой, а не угадывается: CI (Linux) исполняет ветку «оба файла на диске»,
macOS — ветку правила (тот же inode)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH


def _git(args, cwd, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, **kw)


def _case_insensitive(where: Path) -> bool:
    probe = where / "CaseProbe"
    probe.write_text("")
    return (where / "caseprobe").exists()


def _commit_with(tmp_path, entries):
    """Пути вносятся в индекс напрямую (на нечувствительной ФС рабочее дерево двух таких файлов не держит)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    for mode, name, body in entries:
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(r), input=body,
                              capture_output=True, text=True).stdout.strip()
        _git(["update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}"], r)
    assert _git(["commit", "-q", "-m", "collide"], r).returncode == 0
    return r, _git(["rev-parse", "HEAD"], r).stdout.strip()


def _both(sha, rel, repo):
    return RA.exec_root(sha, rel, repo)[1], LNCH.exec_root(sha, rel, repo)[1]


SAME = [("100644", "docs/API_REFERENCE.md", "same\n"), ("100644", "docs/api_reference.md", "same\n"),
        ("100644", "spa_core/app.py", "print(1)\n")]


def test_identical_case_pair_yields_a_proven_release_on_any_fs(tmp_path):
    """C3: тот же режим и blob — релиз доказан обоими резолверами."""
    repo, sha = _commit_with(tmp_path, SAME)
    rel = tmp_path / "releases"
    got, verdict = RA.materialise_release(sha, rel, repo)
    assert verdict == "OK", verdict
    assert RA.verify_release(got, sha, repo) == (True, "")
    assert _both(sha, rel, repo) == ("ACTIVATE_OK", "ACTIVATE_OK")
    names = sorted(p.name for p in (got / "docs").iterdir())
    assert len(names) == (1 if _case_insensitive(tmp_path) else 2), names


def test_tampering_the_shared_file_of_the_pair_is_refused(tmp_path):
    """C4: правило не открывает подмену — байты единственного файла пары изменены ⇒ CORRUPT у обоих."""
    repo, sha = _commit_with(tmp_path, SAME)
    rel = tmp_path / "releases"
    got, verdict = RA.materialise_release(sha, rel, repo)
    assert verdict == "OK", verdict
    target = next((got / "docs").iterdir())
    os.chmod(target, 0o644)
    target.write_text("EVIL\n")
    assert _both(sha, rel, repo) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")


def test_same_blob_different_mode_is_refused_where_the_fs_folds_case(tmp_path):
    """C5: одинаковый blob, разный режим — один файл на диске не может быть обоими ⇒ отказ (нечувствительная
    ФС); на чувствительной оба файла честно лежат ⇒ OK."""
    repo, sha = _commit_with(tmp_path, [("100644", "run.sh", "echo\n"), ("100755", "RUN.sh", "echo\n")])
    rel = tmp_path / "releases"
    got, verdict = RA.materialise_release(sha, rel, repo)
    if _case_insensitive(tmp_path):
        assert got is None and "коллизия регистра" in verdict, verdict
        assert _both(sha, rel, repo) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")
    else:
        assert verdict == "OK" and _both(sha, rel, repo) == ("ACTIVATE_OK", "ACTIVATE_OK")


def test_genuinely_missing_path_with_a_case_twin_name_is_still_missing(tmp_path):
    """C6: путь, которого на диске нет вовсе (и ФС его ни во что не разрешает), — по-прежнему отказ."""
    repo, sha = _commit_with(tmp_path, SAME)
    rel = tmp_path / "releases"
    got, _ = RA.materialise_release(sha, rel, repo)
    aside = tmp_path / "aside"
    aside.mkdir()
    for p in list((got / "docs").iterdir()):
        os.rename(p, aside / p.name)
    assert _both(sha, rel, repo) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")


def test_launcher_main_executes_a_release_with_an_identical_case_pair(tmp_path):
    """C3 через точку входа лаунчера: план исполнения строится из доказанного релиза."""
    entries = SAME + [("100644", "spa_core/__init__.py", ""),
                      ("100644", "studio_release_agents.json", json.dumps({"prober": "spa_core.app"}))]
    repo, sha = _commit_with(tmp_path, entries)
    root = tmp_path / "trusted_root"
    (root / "releases").mkdir(parents=True)
    (root / "runtime.json").write_text(json.dumps({"app_python": "/usr/bin/false", "trusted_repo": str(repo)}))
    (root / "approved_release.json").write_text(json.dumps({"approved_sha": sha}))
    assert RA.materialise_release(sha, root / "releases", repo)[1] == "OK"
    r = LNCH.main("agent:prober", root=root, python=[], active_path=tmp_path / "active.json")
    assert r[0] == "EXEC_FROM_RELEASE", r


@pytest.mark.parametrize("mod", [RA, LNCH], ids=["release_activation", "release_launcher"])
def test_partner_is_decided_by_the_filesystem_object_not_by_the_name(tmp_path, mod):
    """C7 (дверь правила): совпадение имён без учёта регистра партнёром НЕ делает — нужен тот же объект ФС.
    Сцена не зависит от ФС: путь эталона существует, но это ДРУГОЙ объект (на чувствительной ФС так выглядит,
    например, пустой каталог на месте файла пары — обход его не видит, а ``lstat`` находит)."""
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    (root / "Doc.md").write_text("x\n")
    (other / "doc.md").write_text("x\n")
    assert mod._case_partner(root, "Doc.md", {"doc.md": other / "doc.md"}) is None
    assert mod._case_partner(root, "Doc.md", {"Doc.md": root / "Doc.md"}) == "Doc.md"   # положительный контроль


def test_launcher_refuses_a_stamped_dir_whose_one_file_cannot_carry_both_modes(tmp_path):
    """C5 против лаунчера НАПРЯМУЮ: каталог со штампом (материализация его не дала бы) — один файл 100644 на
    месте пары 100644/100755 с одинаковым blob. Нечувствительная ФС: правило обязано отказать по режиму;
    чувствительная: второго файла нет — отказ «нет файла». ACTIVATE_OK нет ни там, ни там."""
    repo, sha = _commit_with(tmp_path, [("100644", "run.sh", "echo\n"), ("100755", "RUN.sh", "echo\n")])
    d = tmp_path / "releases" / sha
    d.mkdir(parents=True)
    (d / "run.sh").write_text("echo\n")
    (d / LNCH.RELEASE_SHA_FILE).write_text(sha)
    assert _both(sha, tmp_path / "releases", repo) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")
