"""Regression coverage for ``scripts/log_session_change.py`` — the shared, append-only
multi-session ANNOUNCE log (PROJECT_CONTROL/16) that the orchestrator protocol itself leans
on: every autonomous cycle records *which files it owns* here so parallel Claude sessions
never silently clobber each other and the owner has one place to see "what moved".

A silent break in this module is corrosive precisely because nothing else guards it: a dropped
line, a clobbered append, or a ``tail`` that chokes on one malformed row would quietly break the
coordination contract without any red test. On origin the module had **0 dedicated tests**; this
file pins the whole surface — ``record`` / ``tail`` / ``_session_id`` / ``main(argv=...)`` — with
special attention to the two properties that matter most: *append-only never clobbers* and
*``tail`` tolerates a corrupt line* (the ``ValueError`` skip branch).

The module is a script (``scripts/`` has no ``__init__.py``), so — exactly like
``test_orchestrator_queue_cli.py`` and ``test_build_agent_registry.py`` do — we load it by file
path via ``importlib.util.spec_from_file_location``.

Hermetic & offline: ``mod._LOG`` (a module-level ``Path`` at the *real* repo
``data/session_changes.jsonl``) is repointed at a ``tmp_path`` file in every test, so the live
announce log is never read or written. Tests only — the module is NOT modified (invariant #16).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "log_session_change.py"


def _load():
    spec = importlib.util.spec_from_file_location("log_session_change", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    """Load the script fresh and repoint its log at a tmp file (never the live log)."""
    m = _load()
    log = tmp_path / "nested" / "session_changes.jsonl"  # nested → exercises parent mkdir
    monkeypatch.setattr(m, "_LOG", log)
    # Deterministic session id unless a test overrides it.
    monkeypatch.setenv("SPA_SESSION_ID", "sess-test")
    return m


def _lines(mod):
    return mod._LOG.read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------- record()

def test_record_writes_one_json_line_and_creates_parent(mod):
    assert not mod._LOG.parent.exists()  # parent dir absent before first write
    entry = mod.record("did a thing", ["a.py", "b.ts"], "pytest 5 green")
    assert mod._LOG.parent.is_dir()  # record() created it
    lines = _lines(mod)
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk == entry
    assert on_disk["summary"] == "did a thing"
    assert on_disk["files"] == ["a.py", "b.ts"]
    assert on_disk["verified"] == "pytest 5 green"
    assert on_disk["session"] == "sess-test"
    # ts is an ISO-8601 Zulu stamp, not empty
    assert on_disk["ts"].endswith("Z") and "T" in on_disk["ts"]


def test_record_strips_summary_and_verified(mod):
    entry = mod.record("  spaced summary \n", [], "  verified text  ")
    assert entry["summary"] == "spaced summary"
    assert entry["verified"] == "verified text"


def test_record_verified_none_becomes_empty_string(mod):
    entry = mod.record("s", [], None)
    assert entry["verified"] == ""
    # round-trips through JSON as ""
    assert json.loads(_lines(mod)[0])["verified"] == ""


def test_record_coerces_path_objects_to_str(mod):
    entry = mod.record("s", [Path("/abs/x.py"), Path("y.py")], "")
    assert entry["files"] == ["/abs/x.py", "y.py"]
    assert all(isinstance(f, str) for f in entry["files"])
    # survives the JSON round-trip
    assert json.loads(_lines(mod)[0])["files"] == ["/abs/x.py", "y.py"]


def test_record_empty_files_list(mod):
    entry = mod.record("s", [], "")
    assert entry["files"] == []


# ------------------------------------------------- append-only never clobbers (the core promise)

def test_record_is_append_only_across_many_calls(mod):
    for i in range(5):
        mod.record(f"change {i}", [f"f{i}.py"], f"v{i}")
    lines = _lines(mod)
    assert len(lines) == 5
    summaries = [json.loads(ln)["summary"] for ln in lines]
    assert summaries == [f"change {i}" for i in range(5)]  # order + all preserved, none clobbered


def test_second_session_does_not_overwrite_first(mod, monkeypatch):
    monkeypatch.setenv("SPA_SESSION_ID", "sess-A")
    mod.record("from A", [], "")
    monkeypatch.setenv("SPA_SESSION_ID", "sess-B")
    mod.record("from B", [], "")
    rows = [json.loads(ln) for ln in _lines(mod)]
    assert [r["session"] for r in rows] == ["sess-A", "sess-B"]
    assert [r["summary"] for r in rows] == ["from A", "from B"]


# --------------------------------------------------------------------------- _session_id()

def test_session_id_prefers_env(mod, monkeypatch):
    monkeypatch.setenv("SPA_SESSION_ID", "custom-id")
    assert mod._session_id() == "custom-id"


def test_session_id_falls_back_to_pid(mod, monkeypatch):
    monkeypatch.delenv("SPA_SESSION_ID", raising=False)
    sid = mod._session_id()
    assert sid.startswith("pid") and sid[3:].isdigit()


def test_session_id_empty_env_falls_back_to_pid(mod, monkeypatch):
    # empty string is falsy → the `or` fallback must kick in, not yield ""
    monkeypatch.setenv("SPA_SESSION_ID", "")
    assert mod._session_id().startswith("pid")


# --------------------------------------------------------------------------- tail()

def test_tail_missing_file_returns_empty(mod):
    assert not mod._LOG.exists()
    assert mod.tail(20) == []


def test_tail_returns_last_n_in_order(mod):
    for i in range(10):
        mod.record(f"c{i}", [], "")
    rows = mod.tail(3)
    assert [r["summary"] for r in rows] == ["c7", "c8", "c9"]


def test_tail_n_larger_than_file_returns_all(mod):
    mod.record("only", [], "")
    assert len(mod.tail(50)) == 1


def test_tail_skips_malformed_lines(mod):
    # one good line, one garbage line, one good line — tail must skip the garbage, not crash
    mod.record("good1", [], "")
    with open(mod._LOG, "a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    mod.record("good2", [], "")
    rows = mod.tail(20)
    assert [r["summary"] for r in rows] == ["good1", "good2"]  # 2 parsed, garbage dropped


def test_tail_all_malformed_returns_empty_not_crash(mod):
    mod._LOG.parent.mkdir(parents=True, exist_ok=True)
    mod._LOG.write_text("{bad\nalso bad\n", encoding="utf-8")
    assert mod.tail(20) == []


# --------------------------------------------------------------------------- main(argv=...)

def test_main_record_path_writes_and_returns_zero(mod, capsys):
    rc = mod.main(["--summary", "cli change", "--files", "x.py", "y.py", "--verified", "ok"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "announced:" in out and "cli change" in out
    row = json.loads(_lines(mod)[0])
    assert row["summary"] == "cli change"
    assert row["files"] == ["x.py", "y.py"]
    assert row["verified"] == "ok"


def test_main_requires_summary_or_tail(mod):
    # argparse .error() exits with code 2
    with pytest.raises(SystemExit) as exc:
        mod.main([])
    assert exc.value.code == 2


def test_main_tail_empty_prints_placeholder(mod, capsys):
    rc = mod.main(["--tail"])
    assert rc == 0
    assert "no session changes recorded yet" in capsys.readouterr().out


def test_main_tail_default_count_is_20(mod, capsys):
    for i in range(25):
        mod.record(f"c{i}", [], "")
    rc = mod.main(["--tail"])  # const=20 default
    assert rc == 0
    out = capsys.readouterr().out
    assert "c24" in out and "c5" in out  # last 20 → c5..c24
    assert "c4" not in out  # c4 is the 21st-from-end, excluded


def test_main_tail_explicit_count(mod, capsys):
    for i in range(10):
        mod.record(f"c{i}", ["/some/dir/file.py"], "")
    rc = mod.main(["--tail", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "c8" in out and "c9" in out and "c7" not in out
    assert "file.py" in out  # basename rendered, not the full path
    assert "/some/dir/" not in out


def test_main_tail_renders_dash_for_no_files_or_verified(mod, capsys):
    mod.record("bare", [], "")
    rc = mod.main(["--tail", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "files: -" in out
    assert "verified: -" in out
