"""CAPITAL-SOURCES-01 §0 — a publisher's `--help` must never publish (incident 2026-10-07).

`scripts/deploy_site_snapshot.py` ignored its arguments, so `deploy_site_snapshot.py --help` ran a real
daily publication. Both publishers now parse arguments BEFORE any write. These tests are in-process with
tripwires on every side-effect door (subprocess, the shelf builder, the site pusher): a regression fails
the test, it can never publish from a test run.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Tripwire(Exception):
    pass


def _boom(*_a, **_k):
    raise _Tripwire("a side-effect door was opened")


# ── deploy_site_snapshot.py ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def dss(monkeypatch):
    m = _load("scripts/deploy_site_snapshot.py", "_dss_cli_test")
    monkeypatch.setattr(m.subprocess, "run", _boom)                 # generator + pusher are subprocesses
    monkeypatch.setattr(m.importlib.util, "spec_from_file_location", _boom)   # constitution build
    return m


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_deploy_help_exits_zero_before_any_side_effect(dss, flag, capsys):
    with pytest.raises(SystemExit) as e:
        dss.main([flag])
    assert e.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_deploy_unknown_argument_fails_before_any_side_effect(dss):
    with pytest.raises(SystemExit) as e:
        dss.main(["--publish-everything"])
    assert e.value.code not in (0, None)


def test_deploy_entrypoint_passes_the_real_argv():
    src = (ROOT / "scripts" / "deploy_site_snapshot.py").read_text(encoding="utf-8")
    assert "sys.exit(main(sys.argv[1:]))" in src     # the CLI's own arguments reach the parser


def test_deploy_dry_run_pushes_nothing(monkeypatch, tmp_path):
    m = _load("scripts/deploy_site_snapshot.py", "_dss_cli_dry")
    calls = []

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if str(m._PUSH) in map(str, cmd):
            raise _Tripwire("push attempted in dry-run")
        return _R()

    snap = tmp_path / "track_snapshot.json"
    snap.write_text('{"as_of": "LOCAL-GENERATION", "x": 1}')
    monkeypatch.setattr(m, "_SNAP", snap)
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m.importlib.util, "spec_from_file_location", _boom)   # constitution: refused, non-fatal
    monkeypatch.setattr(m, "_origin_snapshot", lambda: {"as_of": "ORIGIN-GENERATION", "x": 0})
    assert m.main(["--dry-run"]) == 0
    assert all(str(m._PUSH) not in map(str, c) for c in calls)


# ── publish_site_numbers.py ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def psn(monkeypatch):
    m = _load("scripts/publish_site_numbers.py", "_psn_cli_test")
    monkeypatch.setattr(m, "run", _boom)
    monkeypatch.setattr(m, "_load", _boom)
    return m


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_publish_help_exits_zero_before_any_side_effect(psn, flag, capsys):
    with pytest.raises(SystemExit) as e:
        psn.main([flag])
    assert e.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_publish_unknown_argument_fails_before_any_side_effect(psn):
    with pytest.raises(SystemExit) as e:
        psn.main(["--force-publish"])
    assert e.value.code not in (0, None)


def test_publish_dry_run_never_calls_the_site_pusher(tmp_path):
    m = _load("scripts/publish_site_numbers.py", "_psn_cli_dry")
    shelf = tmp_path / "site_numbers.json"
    shelf.write_text("{}")

    class _BSN:
        NotMeasured = type("NotMeasured", (Exception,), {})
        SequencingViolation = type("SequencingViolation", (Exception,), {})

        @staticmethod
        def run(**_k):
            return {"ready": True, "artifact": shelf}

    class _SSP:
        @staticmethod
        def main(_argv):
            raise _Tripwire("site push attempted in dry-run")

    assert m.run(bsn=_BSN, ssp=_SSP, dry_run=True) == 0
    with pytest.raises(_Tripwire):                    # positive control: without dry-run it WOULD push
        m.run(bsn=_BSN, ssp=_SSP, dry_run=False)
