"""The data-dir guard must reach BOTH test roots — measured, not asserted by comment.

Positive control (deployment rule: a check that has never seen the real failure
is an ornament).  Every test here replays the state cycle #386 measured on
2026-08-26: with the isolation fixture declared only in ``tests/conftest.py``,
a test running out of ``spa_core/tests/`` saw ``SPA_DATA_DIR is None`` and every
module resolving its data dir through the canonical hook resolved it to the
host's live ``data/``.  Remove the wiring from ``spa_core/tests/conftest.py``
and ``test_env_is_isolated_in_this_root`` and the child-process measurement both
go red for exactly that reason.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_LIVE_DATA_DIR = _REPO_ROOT / "data"

# Subject of the child-process measurement: a small, fast, hermetic file from
# THIS root. The point is to read the env out of an ORDINARY test's run, not out
# of a test written to be observed — a guard measured only through its own
# probe proves the probe.
_CHILD_SUBJECT = _HERE / "test_utils_atomic.py"


def test_env_is_isolated_in_this_root():
    """The env hook is set, and it does NOT point at the live track.

    This is the whole finding in one line: on 2026-08-26 this assertion could
    not pass from ``spa_core/tests/`` at all, because nothing in this root set
    the variable.
    """
    raw = os.environ.get("SPA_DATA_DIR")
    assert raw, (
        "SPA_DATA_DIR is unset inside spa_core/tests/ — the isolation fixture "
        "does not reach this root, so every module using the canonical hook "
        "reads and writes the live repo-root data/ (measured #386)"
    )
    assert Path(raw).resolve() != _LIVE_DATA_DIR.resolve()


def test_sandbox_lives_next_to_tmp_path_not_inside_it(tmp_path):
    """The sandbox must not be an entry in the directory the test works in.

    Measured 2026-08-27: ``test_package_data_guard.py`` writes ONE file into its
    ``tmp_path`` and asserts the directory holds exactly that file. A sandbox
    created inside ``tmp_path`` is a second entry there — an isolation that
    rewrites what the test sees is not an isolation.
    """
    sandbox = Path(os.environ["SPA_DATA_DIR"]).resolve()
    assert sandbox.parent != tmp_path.resolve(), (
        f"sandbox {sandbox} sits inside the test's own tmp_path — every test that "
        f"inspects its tmp dir wholesale now sees an extra entry")
    assert not list(tmp_path.iterdir()), (
        f"tmp_path is not empty at test start: {sorted(p.name for p in tmp_path.iterdir())}")


def test_sandbox_is_per_test_not_shared():
    """Two tests must not see each other's data dir.

    A single process-wide dir would be isolation from the live track but not
    from the next test — leftovers there turn an ordering accident into a
    verdict.
    """
    sandbox = Path(os.environ["SPA_DATA_DIR"])
    assert not list(sandbox.iterdir()), (
        f"data-dir sandbox not empty at test start: {sorted(p.name for p in sandbox.iterdir())} "
        "— it is being shared between tests instead of created per test"
    )
    (sandbox / "left_behind.json").write_text("{}")


def test_sandbox_is_per_test_not_shared_second_leg():
    """Second leg of the pair above: the previous test's leftover is invisible.

    Named as its own test on purpose — a leftover check inside one test can
    only ever see its own writes.
    """
    sandbox = Path(os.environ["SPA_DATA_DIR"])
    assert not (sandbox / "left_behind.json").exists()


@pytest.mark.live_data
def test_live_data_marker_still_opts_out():
    """Control in the other direction: the documented opt-out must still work.

    Tests that read the live track ON PURPOSE (SSOT cross-checks, evidence
    chain) declare it with this marker. If the guard ignored the marker it
    would not be an isolation any more — it would be a blanket that silently
    breaks the tests whose job is to look at the real thing.
    """
    raw = os.environ.get("SPA_DATA_DIR")
    # Stated as "the guard built nothing for me" rather than "the value is X":
    # the ambient value is whatever the run was started with, and pinning it
    # would make this test judge the environment instead of the guard.
    assert raw is None or not raw.endswith("_spa_isolated_data"), (
        f"a live_data-marked test was sandboxed anyway (SPA_DATA_DIR={raw!r})"
    )


def test_both_conftests_delegate_to_one_module():
    """Neither root may carry its own copy of the policy.

    Checks the CALL, not a comment: each conftest must load
    ``data_dir_guard.py`` by path and delegate the fixture body to it. Two
    inline copies is how the roots drifted for as long as they did — one of
    them simply never got the fixture.
    """
    for rel in ("tests/conftest.py", "spa_core/tests/conftest.py"):
        src = (_REPO_ROOT / rel).read_text()
        assert "data_dir_guard.py" in src, f"{rel} does not load the shared guard module"
        assert "data_dir_guard.isolate(request, tmp_path_factory, monkeypatch)" in src, (
            f"{rel} declares _isolate_data_dir but does not delegate to the shared "
            f"module — a second copy of the policy is exactly what drifted"
        )
        assert 'monkeypatch.setenv("SPA_DATA_DIR"' not in src, (
            f"{rel} still sets SPA_DATA_DIR inline; the policy belongs in "
            f"spa_core/tests/data_dir_guard.py only"
        )


def test_child_run_of_an_ordinary_file_in_this_root_is_isolated(tmp_path):
    """Measure the env in a CHILD pytest run, through an ordinary test file.

    In-process assertions inherit whatever this run's environment happens to
    be; the failure being replayed here is precisely an ambient-environment
    one. So: spawn pytest, pin --rootdir, collect a plugin that records
    SPA_DATA_DIR for every test it runs, and read the record back.
    """
    assert _CHILD_SUBJECT.exists(), f"child-run subject missing: {_CHILD_SUBJECT}"
    record = tmp_path / "seen.json"
    plugin_dir = tmp_path / "plug"
    plugin_dir.mkdir()
    (plugin_dir / "ddprobe.py").write_text(
        "import json, os\n"
        f"_OUT = {str(record)!r}\n"
        "_seen = {}\n"
        "def pytest_runtest_call(item):\n"
        "    _seen[item.nodeid] = os.environ.get('SPA_DATA_DIR')\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    with open(_OUT, 'w') as fh:\n"
        "        json.dump(_seen, fh)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(plugin_dir) + os.pathsep + env.get("PYTHONPATH", "")
    # The child must not inherit this run's sandbox, or it would "pass" on the
    # parent's env instead of on its own conftest wiring.
    env.pop("SPA_DATA_DIR", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(_CHILD_SUBJECT), "-q",
         "--rootdir", str(_REPO_ROOT), "-p", "no:cacheprovider", "-p", "ddprobe"],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=600,
    )
    assert record.exists(), (
        "child pytest recorded nothing — the run did not reach any test.\n"
        f"exit={proc.returncode}\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )
    seen = json.loads(record.read_text())
    assert seen, "child pytest ran no tests"
    unguarded = {nid: val for nid, val in seen.items()
                 if not val or Path(val).resolve() == _LIVE_DATA_DIR.resolve()}
    assert not unguarded, (
        f"{len(unguarded)} of {len(seen)} test(s) in a child run of "
        f"{_CHILD_SUBJECT.name} saw the LIVE data dir: "
        f"{sorted(unguarded)[:5]}"
    )
