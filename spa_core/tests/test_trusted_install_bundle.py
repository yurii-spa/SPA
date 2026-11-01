"""S2 (ARB 01.11 п. 2–3): установочный пакет из зафиксированного коммита и снимок/восстановление конфигурации
доверенного корня. Всё на временных каталогах пользователя; настоящий корень не читается и не пишется."""
import hashlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from spa_core.studio_os import trusted_install_bundle as TB

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "spa_core" / "studio_os" / "trusted_install_bundle.py"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def src(tmp_path):
    """Тестовый репозиторий: файлы пакета (настоящие байты из дерева) + пин с их sha256, одним коммитом."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    expect = {}
    for p in TB.BUNDLE:
        data = (REPO / p).read_bytes()
        (r / p).parent.mkdir(parents=True, exist_ok=True)
        (r / p).write_bytes(data)
        expect[p] = _sha(data)
    pin = {"files": {p: {"sha256": h} for p, h in expect.items()}, "runtime": {"digest": "d" * 64}}
    (r / TB.PIN_PATH).parent.mkdir(parents=True, exist_ok=True)
    (r / TB.PIN_PATH).write_text(json.dumps(pin))
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "reviewed"], r)
    return r, _git(["rev-parse", "HEAD"], r), expect


def test_stage_writes_the_reviewed_bytes_only_when_both_sources_agree(src, tmp_path):
    r, sha, expect = src
    m = TB.stage(str(r), sha, str(tmp_path / "stage"), expect)
    for p in TB.BUNDLE:
        out = tmp_path / "stage" / p
        assert _sha(out.read_bytes()) == expect[p] and oct(out.stat().st_mode & 0o777) == "0o444"
    assert m["sha"] == sha and m["runtime_digest_pinned"] == "d" * 64


def test_report_value_mismatch_refuses_and_writes_nothing(src, tmp_path):
    r, sha, expect = src
    bad = {**expect, "scripts/install_trusted_bootstrap.sh": "0" * 64}
    with pytest.raises(TB.Refused, match="отчёт ARB"):
        TB.stage(str(r), sha, str(tmp_path / "stage"), bad)
    assert not (tmp_path / "stage").exists()


def test_pin_mismatch_refuses_even_when_report_values_match(src, tmp_path):
    r, _, expect = src
    pin = json.loads((r / TB.PIN_PATH).read_text())
    pin["files"]["spa_core/studio_os/release_launcher.py"]["sha256"] = "1" * 64
    (r / TB.PIN_PATH).write_text(json.dumps(pin))
    _git(["commit", "-qam", "pin drift"], r)
    sha2 = _git(["rev-parse", "HEAD"], r)
    with pytest.raises(TB.Refused, match="пин"):
        TB.stage(str(r), sha2, str(tmp_path / "stage"), expect)


def test_stage_takes_the_commit_not_the_working_tree(src, tmp_path):
    r, sha, expect = src
    (r / "scripts/install_trusted_bootstrap.sh").write_text("echo EVIL\n")          # незакоммиченная подмена
    TB.stage(str(r), sha, str(tmp_path / "stage"), expect)
    assert (tmp_path / "stage/scripts/install_trusted_bootstrap.sh").read_bytes() == (REPO / "scripts/install_trusted_bootstrap.sh").read_bytes()


def test_replace_refs_cannot_substitute_a_bundle_file(src, tmp_path):
    r, sha, expect = src
    real = _git(["rev-parse", f"{sha}:spa_core/studio_os/release_launcher.py"], r)
    forged = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(r), input="print('EVIL')\n",
                            capture_output=True, text=True).stdout.strip()
    _git(["replace", real, forged], r)
    TB.stage(str(r), sha, str(tmp_path / "stage"), expect)
    assert b"EVIL" not in (tmp_path / "stage/spa_core/studio_os/release_launcher.py").read_bytes()


def test_tampered_object_store_is_refused(src, tmp_path):
    r, sha, expect = src
    oid = _git(["rev-parse", f"{sha}:scripts/build_trusted_runtime.sh"], r)
    loose = r / ".git" / "objects" / oid[:2] / oid[2:]
    os.chmod(loose, 0o644)
    evil = b"echo EVIL\n"
    loose.write_bytes(zlib.compress(b"blob %d\0" % len(evil) + evil))
    with pytest.raises(TB.Refused, match="sha1"):
        TB.stage(str(r), sha, str(tmp_path / "stage"), expect)
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("bad_sha", ["HEAD", "main", "abc123"])
def test_no_symbolic_or_short_revision_is_accepted(src, tmp_path, bad_sha):
    r, _, expect = src
    with pytest.raises(TB.Refused, match="40 hex"):
        TB.stage(str(r), bad_sha, str(tmp_path / "stage"), expect)


def test_missing_report_values_or_existing_stage_refuse(src, tmp_path):
    r, sha, expect = src
    with pytest.raises(TB.Refused, match="нет ожидаемых"):
        TB.stage(str(r), sha, str(tmp_path / "stage"), {})
    (tmp_path / "stage").mkdir()
    with pytest.raises(TB.Refused, match="уже существует"):
        TB.stage(str(r), sha, str(tmp_path / "stage"), expect)


def test_cli_runs_isolated_from_the_project_and_reports_refusal(src, tmp_path):
    """Запуск владельцем: ``python3 -I`` файла из пакета, без проекта на пути; отказ — код 2."""
    r, sha, expect = src
    args = [sys.executable, "-I", str(MOD), "stage", "--repo", str(r), "--sha", sha, "--stage", str(tmp_path / "st")]
    ok = subprocess.run(args + [f"--expect={p}={h}" for p, h in expect.items()], capture_output=True, text=True,
                        cwd=str(tmp_path))
    assert ok.returncode == 0, ok.stderr
    bad = subprocess.run(args[:-1] + [str(tmp_path / "st2"), "--expect=" + TB.BUNDLE[0] + "=" + "0" * 64],
                         capture_output=True, text=True, cwd=str(tmp_path))
    assert bad.returncode == 2 and "REFUSED" in bad.stderr


# ── снимок и восстановление конфигурации доверенного корня ─────────────────────────────────────────
@pytest.fixture
def root(tmp_path):
    rt = tmp_path / "StudioOS"
    for d in TB.LISTED_DIRS:
        (rt / d).mkdir(parents=True)
    (rt / "releases" / ("a" * 40)).mkdir()
    (rt / "approved_release.json").write_text(json.dumps({"approved_sha": "a" * 40}) + "\n")
    (rt / "runtime.json").write_text(json.dumps({"app_python": "/x/python3", "runtime_digest": "d" * 64}) + "\n")
    os.chmod(rt / "approved_release.json", 0o644)
    os.chmod(rt / "runtime.json", 0o640)
    return rt


def test_snapshot_change_restore_roundtrip(root, tmp_path):
    TB.snapshot(str(root), str(tmp_path / "snap"))
    assert TB.verify(str(root), str(tmp_path / "snap")) == []
    (root / "approved_release.json").write_text(json.dumps({"approved_sha": "b" * 40}) + "\n")
    os.chmod(root / "runtime.json", 0o666)
    (root / "runtime.json").write_text(json.dumps({"app_python": "/y", "trusted_repo": "/r"}) + "\n")
    (root / "releases" / ("b" * 40)).mkdir()
    diffs = TB.verify(str(root), str(tmp_path / "snap"))
    assert len(diffs) == 3                                            # два файла + новый релиз в перечне
    assert TB.restore(str(root), str(tmp_path / "snap")) == []
    after = TB.verify(str(root), str(tmp_path / "snap"))
    assert after == [f"releases/: {['a' * 40]} → {sorted(['a' * 40, 'b' * 40])}"]   # каталоги не удаляются — названо
    assert oct((root / "runtime.json").stat().st_mode & 0o777) == "0o640"
    assert json.loads((root / "approved_release.json").read_text())["approved_sha"] == "a" * 40


def test_tampered_snapshot_is_not_restored(root, tmp_path):
    TB.snapshot(str(root), str(tmp_path / "snap"))
    (root / "approved_release.json").write_text(json.dumps({"approved_sha": "b" * 40}) + "\n")
    (tmp_path / "snap" / "approved_release.json").write_text(json.dumps({"approved_sha": "e" * 40}) + "\n")
    with pytest.raises(TB.Refused, match="копия"):
        TB.restore(str(root), str(tmp_path / "snap"))
    assert json.loads((root / "approved_release.json").read_text())["approved_sha"] == "b" * 40   # не тронут
    (tmp_path / "snap" / "SNAPSHOT.json").write_text("{}")
    with pytest.raises(TB.Refused, match="SNAPSHOT.sha256"):
        TB.verify(str(root), str(tmp_path / "snap"))


def test_snapshot_cli_exit_codes(root, tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-I", str(MOD), *a], capture_output=True, text=True)  # noqa: E731
    assert run("snapshot", "--root", str(root), "--snapshot", str(tmp_path / "s")).returncode == 0
    assert run("verify", "--root", str(root), "--snapshot", str(tmp_path / "s")).returncode == 0
    (root / "approved_release.json").write_text("{}\n")
    assert run("verify", "--root", str(root), "--snapshot", str(tmp_path / "s")).returncode == 1
    assert run("restore", "--root", str(root), "--snapshot", str(tmp_path / "s")).returncode == 0
    assert run("snapshot", "--root", str(root), "--snapshot", str(tmp_path / "s")).returncode == 2   # уже есть
