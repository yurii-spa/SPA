"""
spa_core/tests/test_dr_backup.py — hermetic tests for the DR snapshot/restore module.

All tests redirect the module's _DATA / _BACKUPS to tmp_path so the REAL data/ and
data/backups/ are never touched. Pure stdlib; deterministic ts injected for reproducibility.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from spa_core.backtesting.tier1 import dr_backup as dr


# The json/jsonl critical fixtures (incl. the bee/ subdir nesting and the .jsonl audit
# chain). This set now covers the FULL MUST_HAVE recovery set (golive_status +
# paper_evidence_history added) so snapshots pass the fail-CLOSED completeness gate.
# track.db is a sqlite file, seeded separately in the fixture (see below) and counted
# via _CRITICAL_DB_COUNT — it is NOT a byte-literal fixture.
_FIXTURE_FILES = {
    "paper_trading_status.json": b'{"status":"ok","capital":100149.54}\n',
    "equity_curve_daily.json": b'[{"d":"2026-06-10","eq":100000.0}]\n',
    "current_positions.json": b'{"positions":[]}\n',
    "golive_status.json": b'{"passed":27,"total":29,"real_track_days":5}\n',
    "paper_evidence_history.json": b'{"days":[{"date":"2026-06-22"}]}\n',
    "audit_chain.jsonl": b'{"i":0,"h":"abc"}\n{"i":1,"h":"def"}\n',
    "bee/defillama_apy_history.json": b'{"source":"defillama_real","pool_results":{}}\n',
}
# track.db is captured as one additional in-tar member (consistent sqlite copy).
_CRITICAL_DB_COUNT = 1
# Total members a complete snapshot of this fixture produces.
_TOTAL_FIXTURE_MEMBERS = len(_FIXTURE_FILES) + _CRITICAL_DB_COUNT


def _seed_track_db(data: Path) -> None:
    con = sqlite3.connect(str(data / "track.db"))
    try:
        con.execute("CREATE TABLE evidence_records(id INTEGER, val TEXT)")
        con.execute("INSERT INTO evidence_records VALUES (1, 'a')")
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Hermetic data/ + backups/ wired into the module."""
    data = tmp_path / "data"
    backups = data / "backups"
    data.mkdir()
    backups.mkdir()
    for rel, content in _FIXTURE_FILES.items():
        p = data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    _seed_track_db(data)
    monkeypatch.setattr(dr, "_DATA", data)
    monkeypatch.setattr(dr, "_BACKUPS", backups)
    return {"data": data, "backups": backups, "tmp": tmp_path}


# ----------------------------------------------------------------------------- snapshot

def test_snapshot_creates_tar_with_manifest(env):
    rep = dr.snapshot(ts="20260624T120000Z")
    arc = Path(rep["archive"])
    assert arc.exists() and arc.name == "spa_state_20260624T120000Z.tar.gz"
    assert rep["written"] is True
    with tarfile.open(arc, "r:gz") as tar:
        names = set(tar.getnames())
    assert dr.MANIFEST_NAME in names
    # All present fixture files are members; the bee/ nesting is preserved.
    for rel in _FIXTURE_FILES:
        assert rel in names
    assert "track.db" in names  # sqlite carried INSIDE the tar (converged contract)
    assert rep["file_count"] == _TOTAL_FIXTURE_MEMBERS


def test_snapshot_records_missing_files_gracefully(env):
    # Remove one NON-critical source; it must be reported as missing, not crash. (A missing
    # MUST_HAVE critical file fail-CLOSES instead — see test_snapshot_fails_closed_*.)
    (env["data"] / "audit_chain.jsonl").unlink()
    rep = dr.snapshot(ts="20260624T130000Z")
    assert "audit_chain.jsonl" in rep["missing"]
    assert rep["file_count"] == _TOTAL_FIXTURE_MEMBERS - 1
    ver = dr.verify_backup(rep["archive"])
    assert ver["valid"] is True  # a backup missing an absent source is still valid


def test_snapshot_fails_closed_on_missing_critical(env):
    """A MUST_HAVE critical file absent → fail-CLOSED (raise) + NO partial archive."""
    (env["data"] / "golive_status.json").unlink()
    with pytest.raises(dr.BackupIncompleteError):
        dr.snapshot(ts="20260624T131500Z")
    assert list(env["backups"].glob("spa_state_*.tar.gz")) == []


def test_snapshot_fails_closed_on_missing_trackdb(env):
    (env["data"] / "track.db").unlink()
    with pytest.raises(dr.BackupIncompleteError):
        dr.snapshot(ts="20260624T132500Z")
    assert list(env["backups"].glob("spa_state_*.tar.gz")) == []


def test_snapshot_dry_run_writes_nothing(env):
    rep = dr.snapshot(write=False, ts="20260624T140000Z")
    assert rep["written"] is False
    assert not Path(rep["archive"]).exists()
    assert rep["file_count"] == _TOTAL_FIXTURE_MEMBERS


def test_manifest_embedded_matches_report(env):
    rep = dr.snapshot(ts="20260624T150000Z")
    with tarfile.open(rep["archive"], "r:gz") as tar:
        m = json.loads(tar.extractfile(dr.MANIFEST_NAME).read())
    assert m["file_count"] == rep["file_count"]
    assert {e["name"] for e in m["files"]} == {e["name"] for e in rep["files"]}


# ------------------------------------------------------------------------- verify_backup

def test_verify_true_on_fresh_backup(env):
    rep = dr.snapshot(ts="20260624T160000Z")
    ver = dr.verify_backup(rep["archive"])
    assert ver["valid"] is True
    assert ver["mismatches"] == []
    assert ver["missing_members"] == []
    assert ver["file_count"] == _TOTAL_FIXTURE_MEMBERS


def test_verify_false_on_tampered_member(env):
    """Rewrite the tar with one data member's bytes altered → sha mismatch → invalid."""
    rep = dr.snapshot(ts="20260624T170000Z")
    src = Path(rep["archive"])
    tampered = src.with_name("tampered.tar.gz")
    with tarfile.open(src, "r:gz") as tin, tarfile.open(tampered, "w:gz") as tout:
        for member in tin.getmembers():
            f = tin.extractfile(member)
            data = f.read() if f is not None else b""
            if member.name == "current_positions.json":
                data = data + b"TAMPERED"  # corrupt the content
                member.size = len(data)
            ti = tarfile.TarInfo(name=member.name)
            ti.size = len(data)
            ti.mtime = 0
            tout.addfile(ti, fileobj=dr._BytesReader(data))
    ver = dr.verify_backup(tampered)
    assert ver["valid"] is False
    assert "current_positions.json" in ver["mismatches"]


def test_verify_false_when_member_dropped(env):
    """A member listed in the manifest but absent from the tar → invalid."""
    rep = dr.snapshot(ts="20260624T175000Z")
    src = Path(rep["archive"])
    rebuilt = src.with_name("dropped.tar.gz")
    with tarfile.open(src, "r:gz") as tin, tarfile.open(rebuilt, "w:gz") as tout:
        for member in tin.getmembers():
            if member.name == "audit_chain.jsonl":
                continue  # drop a manifested file but keep the manifest
            f = tin.extractfile(member)
            data = f.read() if f is not None else b""
            ti = tarfile.TarInfo(name=member.name)
            ti.size = len(data)
            ti.mtime = 0
            tout.addfile(ti, fileobj=dr._BytesReader(data))
    ver = dr.verify_backup(rebuilt)
    assert ver["valid"] is False
    assert "audit_chain.jsonl" in ver["missing_members"]


def test_verify_missing_archive(env):
    ver = dr.verify_backup(env["backups"] / "nope.tar.gz")
    assert ver["valid"] is False
    assert ver["error"] == "archive_not_found"


# -------------------------------------------------------------------------------- restore

def test_restore_round_trips_byte_identical(env):
    rep = dr.snapshot(ts="20260624T180000Z")
    dest = env["tmp"] / "restore_here"
    res = dr.restore(rep["archive"], dest)
    assert res["ok"] is True
    assert dr.MANIFEST_NAME not in res["restored"]  # manifest is not restored as state
    for rel, content in _FIXTURE_FILES.items():
        out = dest / rel
        assert out.exists(), rel
        assert out.read_bytes() == content  # byte-identical to source


def test_restore_does_not_touch_live_data(env):
    """restore writes only to dest_dir, never the source data/ dir."""
    rep = dr.snapshot(ts="20260624T185000Z")
    before = {p: p.read_bytes() for p in env["data"].rglob("*") if p.is_file()}
    dest = env["tmp"] / "elsewhere"
    dr.restore(rep["archive"], dest)
    after = {p: p.read_bytes() for p in env["data"].rglob("*") if p.is_file()}
    assert before == after  # source untouched


def test_restore_missing_archive(env):
    res = dr.restore(env["backups"] / "absent.tar.gz", env["tmp"] / "d")
    assert res["ok"] is False
    assert res["error"] == "archive_not_found"


# ---------------------------------------------------------------------------------- prune

def test_prune_keeps_newest_n(env):
    made = []
    for i in range(6):
        ts = f"20260624T1{i}0000Z"
        dr.snapshot(ts=ts)
        made.append(f"spa_state_{ts}.tar.gz")
    result = dr.prune(keep=3)
    assert len(result["kept"]) == 3
    assert len(result["deleted"]) == 3
    remaining = {p.name for p in dr.list_backups()}
    # Newest three (lexically largest ts) survive.
    assert remaining == set(sorted(made, reverse=True)[:3])


def test_prune_noop_when_under_limit(env):
    dr.snapshot(ts="20260624T120000Z")
    dr.snapshot(ts="20260624T130000Z")
    result = dr.prune(keep=14)
    assert result["deleted"] == []
    assert len(dr.list_backups()) == 2


# ----------------------------------------------------------------------- sha256 / determinism

def test_sha256_deterministic_for_same_bytes(env):
    rep1 = dr.snapshot(write=False, ts="X")
    rep2 = dr.snapshot(write=False, ts="X")
    # Same source bytes → identical per-file integrity hashes (the load-bearing proof).
    # The manifest hash legitimately differs (it embeds created_at_utc wall-clock).
    assert {e["name"]: e["sha256"] for e in rep1["files"]} == \
           {e["name"]: e["sha256"] for e in rep2["files"]}


def test_file_hash_changes_when_source_changes(env):
    rep1 = dr.snapshot(write=False, ts="X")
    h1 = {e["name"]: e["sha256"] for e in rep1["files"]}["paper_trading_status.json"]
    (env["data"] / "paper_trading_status.json").write_bytes(b'{"status":"changed"}\n')
    rep2 = dr.snapshot(write=False, ts="X")
    h2 = {e["name"]: e["sha256"] for e in rep2["files"]}["paper_trading_status.json"]
    assert h1 != h2


# ---------------------------------------------------------------------------- latest_status

def test_latest_status_no_backup(env):
    st = dr.latest_status()
    assert st["has_backup"] is False
    assert st["backup_count"] == 0
    assert "NO DR BACKUP" in st["note"]


def test_latest_status_reports_age_and_validity(env):
    dr.snapshot(ts="20260624T000000Z")
    now = datetime.datetime(2026, 6, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)
    st = dr.latest_status(now=now)
    assert st["has_backup"] is True
    assert st["valid"] is True
    assert st["age_hours"] == pytest.approx(12.0, abs=0.01)
    assert st["stale"] is False
    assert st["file_count"] == _TOTAL_FIXTURE_MEMBERS


def test_latest_status_flags_stale(env):
    dr.snapshot(ts="20260620T000000Z")
    now = datetime.datetime(2026, 6, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)
    st = dr.latest_status(now=now)
    assert st["stale"] is True  # >26h old


def test_latest_status_picks_newest(env):
    dr.snapshot(ts="20260624T010000Z")
    dr.snapshot(ts="20260624T090000Z")
    dr.snapshot(ts="20260624T050000Z")
    st = dr.latest_status()
    assert st["ts"] == "20260624T090000Z"
