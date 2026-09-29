"""Deployment acceptance under the trusted-bootstrap model — regressions for the
four defects the 2026-09-29 benign canary surfaced (ADR-516):

1. acceptance must NOT write mutable state into an immutable content-addressed
   release (it tried to persist its receipt into ``releases/<sha>/data`` → Errno 13);
2. the executability scanner must model interpreter-mediated invocation
   (``/usr/bin/python3 -I <launcher>.py canary``) — the ``.py`` is READ by python,
   so its mode-0444 is correct, not "not executable";
3. import probes must target the FLEET interpreter (miniconda, where uvicorn lives),
   not ``sys.executable`` (the trusted stdlib-only 3.13 that runs acceptance);
4. artifact freshness measured from an immutable release is a frozen copy → NOT
   MEASURED, never false "stale".

Hermetic: fake fleet/release trees in ``tmp_path``; imports/probes injected.
"""
from __future__ import annotations

import os
import plistlib
import time
from pathlib import Path

import pytest

from spa_core.monitoring import deployment_acceptance as acc
from spa_core.monitoring.deployment_acceptance import (
    CRITICAL,
    OK,
    STATE_FILENAME,
    check_entrypoints,
    fleet_python,
    measuring_from_release,
    run_acceptance,
)

_OK_PROBE = lambda w: {"status": "ok", "target": w, "failures": [], "structural": False, "reason": ""}
_NO_IMPORTS = lambda m: (True, "")


def _plist(agents: Path, label: str, program_args: list) -> None:
    (agents / f"{label}.plist").write_bytes(
        plistlib.dumps({"Label": label, "ProgramArguments": program_args}))


# ── Issue 2: interpreter-mediated executability ─────────────────────────────

def test_direct_shell_wrapper_still_needs_execute_bit(tmp_path: Path) -> None:
    """The 2026-08-04 lesson is preserved: a /bin/bash foo.sh whose .sh lost +x
    (0644) is DEAD (exit 126) — fleet convention keeps wrappers 0755."""
    agents, scripts = tmp_path / "a", tmp_path / "s"
    agents.mkdir(); scripts.mkdir()
    s = scripts / "agent_x.sh"; s.write_text("#!/bin/bash\ntrue\n"); os.chmod(s, 0o644)
    _plist(agents, "com.spa.x", ["/bin/bash", str(s)])
    broken = check_entrypoints(agents)
    assert [b["label"] for b in broken] == ["com.spa.x"]
    assert "126" in broken[0]["problem"]


def test_python_interpreter_reads_the_py_so_0444_is_fine(tmp_path: Path) -> None:
    """python READS its script argument — the immutable launcher is 0444 by design,
    and requiring +x on it was the canary false-positive."""
    agents, rel = tmp_path / "a", tmp_path / "r"
    agents.mkdir(); rel.mkdir()
    launcher = rel / "release_launcher-deadbeef.py"
    launcher.write_text("import sys\n"); os.chmod(launcher, 0o444)
    _plist(agents, "com.spa.canary", ["/usr/bin/python3", "-I", str(launcher), "canary"])
    assert check_entrypoints(agents) == []            # NOT broken


def test_trusted_launcher_canary_invocation_is_accepted(tmp_path: Path) -> None:
    """The exact canary shape from 2026-09-29 must not be reported non-executable."""
    agents = tmp_path / "a"; agents.mkdir()
    launcher = tmp_path / "release_launcher-eec1ae58.py"
    launcher.write_text("x=1\n"); os.chmod(launcher, 0o444)
    _plist(agents, "com.spa.canary",
           ["/usr/bin/python3", "-I", str(launcher), "canary"])
    doc = run_acceptance(agent_dir=agents, data_dir=tmp_path / "d", modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=False)
    assert doc["entrypoints_broken"] == []


def test_python_interpreter_with_missing_script_is_broken(tmp_path: Path) -> None:
    agents = tmp_path / "a"; agents.mkdir()
    _plist(agents, "com.spa.g", ["/usr/bin/python3", str(tmp_path / "gone.py")])
    broken = check_entrypoints(agents)
    assert broken and "missing" in broken[0]["problem"]


def test_python_interpreter_with_unreadable_script_is_broken(tmp_path: Path) -> None:
    agents, scripts = tmp_path / "a", tmp_path / "s"
    agents.mkdir(); scripts.mkdir()
    p = scripts / "t.py"; p.write_text("x=1\n"); os.chmod(p, 0o000)
    _plist(agents, "com.spa.u", ["/usr/bin/python3", str(p)])
    try:
        broken = check_entrypoints(agents)
        assert broken and ("unreadable" in broken[0]["problem"] or "126" in broken[0]["problem"])
    finally:
        os.chmod(p, 0o644)  # so tmp cleanup can remove it


def test_missing_python_interpreter_is_broken(tmp_path: Path) -> None:
    agents = tmp_path / "a"; agents.mkdir()
    good = tmp_path / "ok.py"; good.write_text("x=1\n"); os.chmod(good, 0o444)
    _plist(agents, "com.spa.np", ["/no/such/python3", str(good)])
    broken = check_entrypoints(agents)
    assert broken and "interpreter missing" in broken[0]["problem"]


# ── Issue 1: no write into an immutable release ─────────────────────────────

def _fake_release(tmp_path: Path) -> tuple:
    """A materialised release: has .release_sha, and a data/ subdir like the real one."""
    rel = tmp_path / "releases" / "abc123"
    rel.mkdir(parents=True)
    (rel / ".release_sha").write_text("abc123\n")
    (rel / "data").mkdir()
    agents, scripts = tmp_path / "a", tmp_path / "s"
    agents.mkdir(); scripts.mkdir()
    s = scripts / "agent_x.sh"; s.write_text("#!/bin/bash\ntrue\n"); os.chmod(s, 0o755)
    _plist(agents, "com.spa.x", ["/bin/bash", str(s)])
    return rel, agents


def test_release_is_detected_structurally(tmp_path: Path) -> None:
    rel, _ = _fake_release(tmp_path)
    assert measuring_from_release(rel) is True
    assert measuring_from_release(tmp_path) is False


def test_acceptance_writes_nothing_into_the_release_tree(tmp_path: Path, monkeypatch) -> None:
    """The core rule: running from an immutable release, acceptance persists NOTHING
    under releases/<sha>/ — no matter whether SPA_DATA_DIR is set."""
    rel, agents = _fake_release(tmp_path)
    # make the release genuinely read-only, like the live one, to prove we never even try
    os.chmod(rel / "data", 0o555)
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    try:
        doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                             entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=True)
    finally:
        os.chmod(rel / "data", 0o755)
    assert list((rel / "data").glob("*.json")) == []          # nothing written into the release
    assert doc["state_persisted"] is False
    assert "immutable release" in doc["state_note"]


def test_release_receipt_honors_spa_data_dir_escape(tmp_path: Path, monkeypatch) -> None:
    """SPA_DATA_DIR is the established escape: a live writable state dir outside the release."""
    rel, agents = _fake_release(tmp_path)
    live = tmp_path / "live_state"; live.mkdir()
    monkeypatch.setenv("SPA_DATA_DIR", str(live))
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=True)
    assert (live / STATE_FILENAME).is_file()                  # receipt outside the release
    assert list((rel / "data").glob("*.json")) == []          # still nothing in the release
    assert doc["state_persisted"] is True


def test_persist_failure_does_not_corrupt_the_verdict(tmp_path: Path, monkeypatch) -> None:
    """Optional telemetry: even if the receipt cannot be written, the verdict stands."""
    rel, agents = _fake_release(tmp_path)
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=True)
    assert doc["status"] in (OK, "WARNING")                   # a real verdict, not a crash
    assert doc["monitor"] == "deployment_acceptance"


# ── Issue 4: release artifacts are a frozen copy → NOT MEASURED ─────────────

def test_release_artifacts_without_pointer_are_not_falsely_stale(tmp_path: Path, monkeypatch) -> None:
    """From a release with NO SPA_DATA_DIR, data/ is frozen and live state is not locatable
    ⇒ NOT MEASURED, never false 'stale'."""
    rel, agents = _fake_release(tmp_path)
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    old = time.time() - 999 * 3600
    for n in ("current_positions.json", "adapter_status.json", "agent_health.json"):
        f = rel / "data" / n; f.write_text("{}"); os.utime(f, (old, old))
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=False)
    assert doc["artifacts_overdue"] == []                     # NOT reported stale
    assert doc["artifacts_unchecked"] and "неизменяемого релиза" in doc["artifacts_unchecked"]
    assert doc["status"] != CRITICAL


def test_release_with_spa_data_dir_measures_live_state(tmp_path: Path, monkeypatch) -> None:
    """The deterministic release wiring: SPA_DATA_DIR (plist EnvironmentVariables) names the
    LIVE state root, so a release-mode canary MEASURES it — no manual --data-dir."""
    rel, agents = _fake_release(tmp_path)
    live = tmp_path / "live"; live.mkdir()
    for n in ("current_positions.json", "adapter_status.json", "agent_health.json"):
        (live / n).write_text("{}")                           # all fresh
    monkeypatch.setenv("SPA_DATA_DIR", str(live))
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=True)
    assert doc["artifacts_unchecked"] is None                 # live state IS measured
    assert doc["artifacts_overdue"] == []                     # and it is fresh
    assert doc["status"] == OK                                # legitimate OK, no manual --data-dir
    assert (live / STATE_FILENAME).is_file()                  # receipt in live state, not the release
    assert list((rel / "data").glob("*.json")) == []          # release untouched


def test_release_with_spa_data_dir_catches_genuinely_stale_live_state(tmp_path: Path, monkeypatch) -> None:
    """Not weakened: with the live pointer, a truly stale live artifact IS reported."""
    rel, agents = _fake_release(tmp_path)
    live = tmp_path / "live"; live.mkdir()
    old = time.time() - 999 * 3600
    f = live / "current_positions.json"; f.write_text("{}"); os.utime(f, (old, old))
    (live / "adapter_status.json").write_text("{}")
    (live / "agent_health.json").write_text("{}")
    monkeypatch.setenv("SPA_DATA_DIR", str(live))
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=None, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=False)
    assert any(a["artifact"] == "current_positions.json" for a in doc["artifacts_overdue"])


def test_explicit_data_dir_still_measured_even_from_release(tmp_path: Path) -> None:
    """An explicit --data-dir points at LIVE state — then we DO measure it."""
    rel, agents = _fake_release(tmp_path)
    live = tmp_path / "live"; live.mkdir()
    old = time.time() - 999 * 3600
    f = live / "current_positions.json"; f.write_text("{}"); os.utime(f, (old, old))
    (live / "adapter_status.json").write_text("{}")
    (live / "agent_health.json").write_text("{}")
    doc = run_acceptance(agent_dir=agents, repo_root=rel, data_dir=live, modules=(),
                         entrypoint_prober=_OK_PROBE, import_runner=_NO_IMPORTS, write=False)
    assert any(a["artifact"] == "current_positions.json" for a in doc["artifacts_overdue"])


# ── Issue 3: probes target the fleet interpreter ────────────────────────────

def test_fleet_python_prefers_spa_agent_python(monkeypatch) -> None:
    monkeypatch.setenv("SPA_AGENT_PYTHON", "/sentinel/python3")
    assert fleet_python() == "/sentinel/python3"


def test_fleet_python_falls_back_to_sys_executable_when_miniconda_absent(monkeypatch) -> None:
    """In CI (ubuntu, no miniconda) the 'fleet' is the interpreter running the tests."""
    import sys
    from spa_core.utils import fleet_python as fp_mod
    monkeypatch.delenv("SPA_AGENT_PYTHON", raising=False)
    monkeypatch.setattr(fp_mod, "MINICONDA_DEFAULT", "/no/such/miniconda/python3")
    assert fleet_python() == sys.executable


def test_fleet_python_single_source_no_duplicate_hardcode() -> None:
    """The miniconda path must live in exactly ONE place in Python code (the shared
    resolver) — not duplicated inside deployment_acceptance/self_heal."""
    import spa_core.monitoring.deployment_acceptance as da
    import spa_core.monitoring.self_heal as sh
    for mod in (da, sh):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "miniconda3/bin/python3" not in src, (
            f"{mod.__name__} hardcodes the fleet python path — use fleet_python()")


def test_check_imports_uses_the_fleet_interpreter(monkeypatch, tmp_path) -> None:
    """The real defect: acceptance under the trusted 3.13 must probe imports with the
    interpreter the AGENTS use, not sys.executable."""
    monkeypatch.setenv("SPA_AGENT_PYTHON", "/sentinel/python3")
    seen = {}

    def fake_run(argv, **kw):
        seen["exe"] = argv[0]
        class R:  # noqa: D401
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(acc.subprocess, "run", fake_run)
    acc.check_imports(("spa_core.adapters",), repo_root=tmp_path)
    assert seen["exe"] == "/sentinel/python3"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
