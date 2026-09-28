"""Trusted Python 3.13 runtime bundle (ADR-500 runtime closure) — hermetic checks of the invariants the
installer relies on: the content digest is deterministic and is NOT changed by running the interpreter
(__pycache__) or by the bundle's own metadata file. Real relocation/independence/compat are proven by the
manual DYLD trace + build_trusted_runtime.sh self-checks (documented in the runtime report); this file guards
the digest contract that the installer's tamper gate depends on."""
import hashlib
import os
import subprocess


def _tree_digest(root):
    """Mirror the shell exactly: `find . -type f (excl __pycache__, runtime_bundle.json) | LC_ALL=C sort |
    while read f; do shasum -a 256 "$f"; done | shasum -a 256`. shasum prints `<hash>  <path>\\n`."""
    rels = []
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath.split(os.sep):
            continue
        for f in files:
            if f == "runtime_bundle.json":
                continue
            p = os.path.join(dirpath, f)
            if os.path.islink(p):        # `find -type f` excludes symlinks — so does the shell digest
                continue
            rels.append("./" + os.path.relpath(p, root))
    rels.sort()                                                   # LC_ALL=C == byte/ascii sort
    blob = "".join(f"{hashlib.sha256(open(os.path.join(root, r[2:]),'rb').read()).hexdigest()}  {r}\n" for r in rels)
    return hashlib.sha256(blob.encode()).hexdigest()


def _mk_runtime(root):
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "python3.13").mkdir(parents=True)
    (root / "bin" / "python3").write_text("#!/bin/sh\n")
    (root / "lib" / "python3.13" / "os.py").write_text("# stdlib landmark\n")
    return root


def test_digest_deterministic(tmp_path):
    a = _mk_runtime(tmp_path / "a"); b = _mk_runtime(tmp_path / "b")
    assert _tree_digest(a) == _tree_digest(b)                     # same content → same digest


def test_digest_ignores_pycache_and_metadata(tmp_path):
    r = _mk_runtime(tmp_path / "r")
    d0 = _tree_digest(r)
    # simulate an interpreter run writing __pycache__ + the build writing its metadata
    pc = r / "lib" / "python3.13" / "__pycache__"; pc.mkdir()
    (pc / "os.cpython-313.pyc").write_bytes(b"\x00bytecode")
    (r / "runtime_bundle.json").write_text('{"runtime_id":"x"}')
    assert _tree_digest(r) == d0                                  # neither changes the digest → stable tamper gate


def test_digest_changes_on_real_content_tamper(tmp_path):
    r = _mk_runtime(tmp_path / "r")
    d0 = _tree_digest(r)
    (r / "lib" / "python3.13" / "os.py").write_text("# TAMPERED\n")
    assert _tree_digest(r) != d0                                  # a real stdlib change IS caught


def test_build_script_matches_this_digest_formula(tmp_path):
    """The shell digest (build_trusted_runtime.sh / installer) equals this Python formula on the same tree."""
    r = _mk_runtime(tmp_path / "r")
    (r / "runtime_bundle.json").write_text("{}")
    sh = ("cd %s && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' "
          "| LC_ALL=C sort | while read -r f; do shasum -a 256 \"$f\"; done | shasum -a 256 | cut -d' ' -f1" % r)
    got = subprocess.run(["bash", "-c", sh], capture_output=True, text=True).stdout.strip()
    assert got == _tree_digest(r), (got, _tree_digest(r))


# ── §1/§4 SYMLINK HARD GATE: the digest hashes regular files, so a symlink must be independently rejected ──
def test_symlink_not_covered_by_digest_so_must_be_gated(tmp_path):
    r = _mk_runtime(tmp_path / "r")
    d0 = _tree_digest(r)
    os.symlink("/Users/yuriikulieshov/evil", str(r / "lib" / "python3.13" / "evil_link"))
    # the digest is UNCHANGED by adding a symlink (find -type f ignores it) → proves a separate gate is required
    assert _tree_digest(r) == d0
    # and a real `find -type l` catches it
    import subprocess
    out = subprocess.run(["find", str(r), "-type", "l"], capture_output=True, text=True).stdout.strip()
    assert "evil_link" in out


def _run_installer(tmp_path, runtime, extra=()):
    """Run install_trusted_bootstrap.sh --dry-run against a crafted bundle (dummy launcher/approved args)."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    launcher = tmp_path / "l.py"; launcher.write_text("x")
    lsha = subprocess.run(["shasum", "-a", "256", str(launcher)], capture_output=True, text=True).stdout.split()[0]
    return subprocess.run(["bash", os.path.join(repo, "scripts/install_trusted_bootstrap.sh"), "--dry-run",
        "--launcher", str(launcher), "--launcher-sha256", lsha, "--repo", repo,
        "--approved", "5b65257784441f61568e6c3bd22e9d0a1e928c83",
        "--runtime", str(runtime), "--runtime-digest", "deadbeef", *extra],
        capture_output=True, text=True)


def test_installer_rejects_symlinked_bundle(tmp_path):
    """A bundle with ANY symlink is rejected by the installer BEFORE it runs the interpreter (fail-closed)."""
    r = tmp_path / "rt"; (r / "bin").mkdir(parents=True); (r / "lib" / "python3.13").mkdir(parents=True)
    (r / "bin" / "python3").write_text("#!/bin/sh\necho 3.13.0\n"); os.chmod(r / "bin" / "python3", 0o755)
    os.symlink("/Users/yuriikulieshov/evil", str(r / "lib" / "python3.13" / "evil"))
    res = _run_installer(tmp_path, r)
    assert res.returncode != 0 and "symlink" in (res.stdout + res.stderr).lower()


def test_installer_rejects_symlink_to_user_path(tmp_path):
    r = tmp_path / "rt"; (r / "bin").mkdir(parents=True); (r / "lib" / "python3.13").mkdir(parents=True)
    (r / "bin" / "python3").write_text("#!/bin/sh\n"); os.chmod(r / "bin" / "python3", 0o755)
    os.symlink(str(tmp_path / "attacker_writable"), str(r / "bin" / "python3-evil"))
    res = _run_installer(tmp_path, r)
    assert res.returncode != 0 and "symlink" in (res.stdout + res.stderr).lower()


# ── §4 WHOLE-TREE permission closure of the REUSE/verify path (installer --verify-runtime, read-only) ──
import shutil
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALLER = os.path.join(REPO, "scripts/install_trusted_bootstrap.sh")
BUILDER = os.path.join(REPO, "scripts/build_trusted_runtime.sh")


def _digest_of(d):
    sh = ("cd %s && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' "
          "| LC_ALL=C sort | while read -r f; do shasum -a 256 \"$f\"; done | shasum -a 256 | cut -d' ' -f1" % d)
    return subprocess.run(["bash", "-c", sh], capture_output=True, text=True).stdout.strip()


def _verify(d, digest):
    return subprocess.run(["bash", INSTALLER, "--verify-runtime", d, "--runtime-digest", digest,
        "--launcher", "x", "--launcher-sha256", "x", "--repo", "x", "--approved", "x", "--runtime", "x"],
        capture_output=True, text=True)


@pytest.fixture(scope="module")
def ro_runtime(tmp_path_factory):
    """A real relocatable 3.13 bundle, installed READ-ONLY (files+dirs a-w) like the trusted plane."""
    import sys
    if sys.version_info[:2] != (3, 13):
        pytest.skip("needs a 3.13 to build the runtime bundle")
    stage = str(tmp_path_factory.mktemp("rt") / "bundle")
    r = subprocess.run(["bash", BUILDER, "--src", sys.executable, "--stage", stage, "--print-digest"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isdir(stage):
        pytest.skip("build_trusted_runtime.sh unavailable: " + r.stderr[-200:])
    digest = _digest_of(stage)
    subprocess.run(["chmod", "-R", "a-w", stage])                # fully read-only (files + dirs)
    yield stage, digest
    subprocess.run(["chmod", "-R", "u+w", stage])                # allow cleanup


def test_correct_runtime_verifies(ro_runtime):
    stage, digest = ro_runtime
    assert _verify(stage, digest).returncode == 0                # read-only, root-would-be-owner, digest, smoke


def test_writable_stdlib_file_fails_closed_and_untouched(ro_runtime):
    stage, digest = ro_runtime
    f = os.path.join(stage, "lib/python3.13/os.py")
    subprocess.run(["chmod", "u+w", f])
    try:
        r = _verify(stage, digest)
        assert r.returncode != 0 and "writable" in (r.stdout + r.stderr).lower()
        assert _digest_of(stage) == digest                       # tree left byte-for-byte (only a mode bit changed by the test)
    finally:
        subprocess.run(["chmod", "a-w", f])


def test_writable_subdir_fails_closed(ro_runtime):
    stage, digest = ro_runtime
    d = os.path.join(stage, "lib/python3.13")
    subprocess.run(["chmod", "u+w", d])
    try:
        r = _verify(stage, digest)
        assert r.returncode != 0 and "writable" in (r.stdout + r.stderr).lower()
    finally:
        subprocess.run(["chmod", "a-w", d])


def test_group_other_writable_fails_closed(ro_runtime):
    stage, digest = ro_runtime
    f = os.path.join(stage, "bin/python3")
    subprocess.run(["chmod", "o+w", f])
    try:
        r = _verify(stage, digest)
        assert r.returncode != 0 and "writable" in (r.stdout + r.stderr).lower()
    finally:
        subprocess.run(["chmod", "o-w", f])


def test_tampered_file_fails_closed(ro_runtime):
    stage, digest = ro_runtime
    f = os.path.join(stage, "lib/python3.13/os.py")
    subprocess.run(["chmod", "u+w", f]); open(f, "a").write("# t\n")
    try:
        r = _verify(stage, digest)
        assert r.returncode != 0 and "digest" in (r.stdout + r.stderr).lower()
    finally:
        open(f, "r+").truncate(os.path.getsize(f) - 4); subprocess.run(["chmod", "a-w", f])
