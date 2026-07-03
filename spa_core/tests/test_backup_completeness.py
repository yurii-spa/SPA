"""
spa_core/tests/test_backup_completeness.py — backup-integrity convergence (R7 follow-up).

WHY: the restore drill (R7) surfaced a REAL backup-integrity gap — the two backup
producers DIVERGED:
  * the DR producer (spa_core/backtesting/tier1/dr_backup.py) made the timestamped
    spa_state_<ts>Z.tar.gz (the NEWEST by mtime) but its hardcoded CRITICAL_FILES list
    OMITTED paper_evidence_history.json, and NEITHER producer carried track.db inside the
    tar (it was snapshotted separately as a bare data/backups/spa_<date>.db).
A restore from the newest backup would therefore MISS critical state = backup theater.

These tests pin the CONVERGED contract: EVERY backup archive (from either producer) must
carry the FULL critical set INCLUDING paper_evidence_history.json AND track.db (inside the
tar, openable as sqlite); and a missing critical file must FAIL-CLOSED (raise / no archive)
rather than silently ship a partial archive.

stdlib-only · hermetic (each producer pointed at a tmp data dir; live data/ untouched).
"""
# LLM_FORBIDDEN
import importlib.util
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

import spa_core.backtesting.tier1.dr_backup as dr

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"

# The full critical set a restore needs (must be carried by EVERY archive).
CRITICAL = (
    "golive_status.json",
    "equity_curve_daily.json",
    "paper_evidence_history.json",
    "current_positions.json",
    "track.db",
)


def _load_daily_backup_module():
    """Import scripts/daily_backup.py as a module (not a package)."""
    spec = importlib.util.spec_from_file_location(
        "daily_backup_under_test", str(_SCRIPTS / "daily_backup.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_data(data: Path) -> None:
    """Seed a tmp data/ with all critical files (json + a real sqlite track.db)."""
    data.mkdir(parents=True, exist_ok=True)
    (data / "golive_status.json").write_text(
        json.dumps({"passed": 27, "total": 29, "real_track_days": 5})
    )
    (data / "equity_curve_daily.json").write_text(
        json.dumps({"daily": [{"date": "2026-06-26", "equity": 100190.22}]})
    )
    (data / "paper_evidence_history.json").write_text(
        json.dumps({"days": [{"date": "2026-06-22"}]})
    )
    (data / "current_positions.json").write_text(
        json.dumps([{"protocol": "aave_v3", "usd": 40000}])
    )
    # a couple of non-critical members so the broad daily glob has more than the critical set
    (data / "trades.json").write_text(json.dumps({"trades": []}))
    con = sqlite3.connect(str(data / "track.db"))
    try:
        con.execute("CREATE TABLE evidence_records(id INTEGER, val TEXT)")
        con.execute("INSERT INTO evidence_records VALUES (1, 'a')")
        con.commit()
    finally:
        con.close()


def _archive_members(archive: str) -> set:
    with tarfile.open(archive, "r:gz") as tar:
        return set(tar.getnames())


def _extract_and_open_db(archive: str, tmp: Path) -> int:
    """Extract track.db from the archive and prove it opens as sqlite. Return row count."""
    with tarfile.open(archive, "r:gz") as tar:
        f = tar.extractfile("track.db")
        assert f is not None, "track.db unreadable in archive"
        dbp = tmp / "extracted_track.db"
        dbp.write_bytes(f.read())
    con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return con.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Producer A — dr_backup.py (the timestamped, newest-by-mtime archive)
# --------------------------------------------------------------------------- #
def test_dr_backup_archive_carries_full_critical_set(tmp_path, monkeypatch):
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)

    monkeypatch.setattr(dr, "_DATA", data)
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    rep = dr.snapshot(ts="20260627T120000Z")
    assert rep["written"] is True
    members = _archive_members(rep["archive"])
    for crit in CRITICAL:
        assert crit in members, f"dr_backup archive MISSING critical file {crit!r}"
    # the previously-omitted file is now present
    assert "paper_evidence_history.json" in members
    # track.db opens from inside the tar
    assert _extract_and_open_db(rep["archive"], tmp_path) == 1
    # embedded manifest verify passes
    assert dr.verify_backup(rep["archive"])["valid"] is True


def test_dr_backup_fails_closed_on_missing_critical(tmp_path, monkeypatch):
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)
    (data / "paper_evidence_history.json").unlink()  # drop a critical file

    monkeypatch.setattr(dr, "_DATA", data)
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    with pytest.raises(dr.BackupIncompleteError):
        dr.snapshot(ts="20260627T120000Z")
    # fail-CLOSED: NO partial archive left behind
    assert list(backups.glob("spa_state_*.tar.gz")) == []


def test_dr_backup_fails_closed_on_missing_trackdb(tmp_path, monkeypatch):
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)
    (data / "track.db").unlink()  # drop the sqlite critical file

    monkeypatch.setattr(dr, "_DATA", data)
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    with pytest.raises(dr.BackupIncompleteError):
        dr.snapshot(ts="20260627T120000Z")
    assert list(backups.glob("spa_state_*.tar.gz")) == []


# --------------------------------------------------------------------------- #
# Producer B — scripts/daily_backup.py (the date-stamped daily archive)
# --------------------------------------------------------------------------- #
def test_daily_backup_archive_carries_full_critical_set(tmp_path, monkeypatch):
    db = _load_daily_backup_module()
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)

    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(backups))

    rep = db.snapshot(date_str="2026-06-27")
    assert rep["written"] is True
    members = _archive_members(rep["archive"])
    for crit in CRITICAL:
        assert crit in members, f"daily_backup archive MISSING critical file {crit!r}"
    assert "track.db" in members, "track.db must be INSIDE the tar, not a separate bare .db"
    assert _extract_and_open_db(rep["archive"], tmp_path) == 1
    assert db.verify(rep["archive"])["valid"] is True


def test_daily_backup_fails_closed_on_missing_critical(tmp_path, monkeypatch):
    db = _load_daily_backup_module()
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)
    (data / "current_positions.json").unlink()  # drop a critical file

    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(backups))

    with pytest.raises(db.BackupIncompleteError):
        db.snapshot(date_str="2026-06-27")
    assert list(backups.glob("spa_state_*.tar.gz")) == []


# --------------------------------------------------------------------------- #
# End-to-end: drill restores cleanly from a freshly-produced converged archive
# --------------------------------------------------------------------------- #
def test_drill_restores_clean_from_converged_archive(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "drill_restore_under_test", str(_SCRIPTS / "drill_restore.py")
    )
    drill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drill)

    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)

    monkeypatch.setattr(dr, "_DATA", data)
    monkeypatch.setattr(dr, "_BACKUPS", backups)
    arc = dr.snapshot(ts="20260627T130000Z")["archive"]

    monkeypatch.setattr(drill, "_DATA", os.path.realpath(str(data)))
    monkeypatch.setattr(drill, "_BACKUPS", str(backups))
    monkeypatch.setattr(drill, "_STATUS_PATH", str(data / "restore_drill_status.json"))
    monkeypatch.setattr(drill, "ARCHIVE_GLOB", str(backups / "spa_state_*.tar.gz"))
    monkeypatch.setattr(drill, "DB_GLOB", str(backups / "spa_*.db"))

    report = drill.run_drill(archive=arc, quiet=True)
    assert report["all_ok"] is True, report
    # track.db came from INSIDE the archive (no separate bare .db snapshot needed)
    assert str(report["db_snapshot"]).startswith("in-archive:")
    # every critical file validated PASS
    validated = {e["file"]: e["ok"] for e in report["files_validated"]}
    for crit in CRITICAL:
        assert validated.get(crit) is True, f"{crit} did not restore clean: {validated}"


# --------------------------------------------------------------------------- #
# WS-8 ("Cutover-Bulletproof") — the published PROOF CHAINS / CAPTURED BOOK /
# DAY-30 artifact must be (a) captured by the daily backup (they live in subdirs the
# old top-level glob never reached) and (b) byte-verifiably recovered by the drill —
# a TORN proof chain in a backup must be DETECTED + REFUSED, never silently restored.
# --------------------------------------------------------------------------- #
def _seed_proof_chain(data: Path) -> str:
    """Seed a minimal but REAL hash-chained rates-desk decision log under data/rates_desk/.
    Returns the head hash. Uses the published canonical-JSON + SHA-256 recipe verify_spa.py uses."""
    import hashlib

    rd = data / "rates_desk"
    rd.mkdir(parents=True, exist_ok=True)

    def _canonical(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _entry_hash(row):
        payload = {k: v for k, v in row.items()
                   if k not in ("seq", "ts", "entry_hash", "prev_hash")}
        canon = _canonical({"seq": row["seq"], "ts": row["ts"],
                            "event_type": "rates_desk_decision",
                            "payload": payload, "prev_hash": row["prev_hash"]})
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    prev = "0" * 64
    lines = []
    for i in range(3):
        row = {"seq": i, "ts": f"2026-06-2{i}T00:00:00Z", "prev_hash": prev,
               "underlying": f"PT-{i}", "approved": True}
        row["entry_hash"] = _entry_hash(row)
        prev = row["entry_hash"]
        lines.append(json.dumps(row))
    (rd / "decision_log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return prev


def test_daily_backup_captures_proof_chain_subtree(tmp_path, monkeypatch):
    """The proof-chain subtrees (data/rates_desk/ etc.) — invisible to the old top-level glob —
    are now captured by the daily backup. A backup that cannot restore the proof chain is theater."""
    db = _load_daily_backup_module()
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    _seed_data(data)
    _seed_proof_chain(data)

    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(data / "backups"))

    rep = db.snapshot(date_str="2026-06-28")
    members = _archive_members(rep["archive"])
    assert "rates_desk/decision_log.jsonl" in members, \
        f"proof chain NOT captured by daily backup (members={sorted(members)})"
    assert db.verify(rep["archive"])["valid"] is True


def test_drill_detects_and_refuses_corrupt_proof_chain(tmp_path, monkeypatch):
    """RED-TEAM: a backup whose restored proof chain no longer reproduces its hash must FAIL the
    drill (detected + refused), never silently pass as a clean restore."""
    spec = importlib.util.spec_from_file_location(
        "drill_restore_corrupt", str(_SCRIPTS / "drill_restore.py"))
    drill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drill)

    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)
    _seed_data(data)
    _seed_proof_chain(data)
    # hermetic: keep the drill's status write inside the tmp data/ — never clobber the live
    # data/restore_drill_status.json (it feeds the R8 resilience rollup; a test-artifact there
    # flips resilience OK->WARNING on fake evidence).
    monkeypatch.setattr(drill, "_STATUS_PATH", str(data / "restore_drill_status.json"))

    db = _load_daily_backup_module()
    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(backups))
    arc = db.snapshot(date_str="2026-06-28")["archive"]

    # Build a CORRUPTED copy: mutate a decision-chain payload field WITHOUT fixing entry_hash.
    corrupt = str(backups / "spa_state_9999-99-99.tar.gz")
    import io
    with tarfile.open(arc, "r:gz") as src, tarfile.open(corrupt, "w:gz") as out:
        for m in src.getmembers():
            f = src.extractfile(m)
            blob = f.read() if f else b""
            if m.name == "rates_desk/decision_log.jsonl" and blob:
                rows = blob.decode().splitlines()
                row0 = json.loads(rows[0])
                row0["approved"] = (not row0["approved"])  # tamper, leave stale entry_hash
                rows[0] = json.dumps(row0)
                blob = ("\n".join(rows) + "\n").encode()
            ti = tarfile.TarInfo(m.name)
            ti.size = len(blob); ti.mtime = m.mtime; ti.mode = m.mode
            out.addfile(ti, io.BytesIO(blob))

    report = drill.run_drill(archive=corrupt, quiet=True)
    assert report["all_ok"] is False, "drill SILENTLY restored a corrupt proof chain"
    proof = {e["file"]: e for e in report["files_validated"]}.get("proof_chains")
    assert proof is not None and proof["ok"] is False
    assert "chain broken" in proof["detail"].lower() or "fail" in proof["detail"].lower()
