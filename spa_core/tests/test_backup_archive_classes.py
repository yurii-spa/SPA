"""
ADR-611 (ARB-CONTINUITY-01 Wave B) — FULL vs CRITICAL backup archives can no longer be confused.

Replays the defect measured 2026-10-07: `offsite_copy` took the NEWEST `spa_state_*` archive across
both producers and shipped the 29-member DR-critical archive (no ledgers) to iCloud while the FULL
daily archive stayed on the Mac. Each test below is a failure injection with a positive control:
the scene is first shown to reproduce the old wrong answer (or the defect), then the new code is
shown to refuse / pick correctly.

Archive names are LABELS derived from one fixed anchor; the only clock-judging call
(`full_offsite_proven`) receives the same anchor as `now=` — no wall clock is read at import.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed as now= into archive_class.full_offsite_proven; archive names built from it are labels the code never compares with the wall clock
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import sqlite3
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.dr import archive_class, full_archive_verify, offsite_copy

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def _daily_name(days_ago: int = 0) -> str:
    return f"spa_state_{(NOW - timedelta(days=days_ago)).strftime('%Y-%m-%d')}.tar.gz"


def _dr_name(hours_ago: int = 0) -> str:
    return f"spa_state_{(NOW - timedelta(hours=hours_ago)).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"


def _sqlite_bytes(tmp: Path, name: str) -> bytes:
    p = tmp / f"_{name.replace('/', '_')}"
    if p.exists():
        return p.read_bytes()
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE t(x INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    return p.read_bytes()


def _full_members(tmp: Path) -> dict:
    """A COMPLETE full-class member set: required state, sqlite DBs, every DECLARED ledger,
    and a CIO ledger whose snapshot_digest resolves to a real content-addressed snapshot."""
    snap_doc = b'{"sleeves":{}}'
    digest = hashlib.sha256(snap_doc).hexdigest()
    m = {
        "golive_status.json": b'{"passed": 1, "total": 1, "real_track_days": 1}',
        "equity_curve_daily.json": b'{"daily": []}',
        "paper_evidence_history.json": b'{"days": []}',
        "current_positions.json": b"[]",
        f"investment_cio/snapshots/{digest}.json.gz": gzip.compress(snap_doc),
    }
    for db in ("track.db", "trading_research/evidence.db", "trading_research/market.db"):
        m[db] = _sqlite_bytes(tmp, db)
    for led in full_archive_verify.declared_ledgers():
        if led.endswith(".jsonl"):
            m[led] = b'{"seq": 1}\n'
    m["investment_cio/ledger.jsonl"] = (json.dumps({"seq": 1, "snapshot_digest": digest}) + "\n").encode()
    return m


def _write_archive(path: Path, members: dict, schema: str = "spa_daily_backup/v2",
                   manifest: bool = True, manifest_override: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    files = [{"name": n, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in sorted(members.items())]
    with tarfile.open(path, "w:gz") as tar:
        if manifest:
            doc = {"schema": schema, "files": files}
            doc.update(manifest_override or {})
            raw = json.dumps(doc).encode()
            ti = tarfile.TarInfo("backup_manifest.json"); ti.size = len(raw)
            tar.addfile(ti, io.BytesIO(raw))
        for n, b in sorted(members.items()):
            ti = tarfile.TarInfo(n); ti.size = len(b)
            tar.addfile(ti, io.BytesIO(b))
    return path


def _critical(path: Path) -> Path:
    return _write_archive(path, {"golive_status.json": b"{}"}, schema="spa_dr_backup/v2")


def _run(tmp_path, backup_dir, cls, **kw):
    status = tmp_path / "status.json"
    kw.setdefault("dest_dir", tmp_path / "offsite")
    code = offsite_copy.run(backup_dir=backup_dir, status_path=status, archive_class_=cls, **kw)
    return code, json.loads(status.read_text())


@pytest.fixture(autouse=True)
def _responsive_dest(monkeypatch):
    import spa_core.persistence.backup as pb
    monkeypatch.setattr(pb, "_probe_backup_root", lambda root, t: None)


# ── 1. full/critical confusion ───────────────────────────────────────────────────────────────
def test_full_class_never_ships_the_newer_critical_archive(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    _critical(b / _dr_name(0))  # written later the same day ⇒ newest by instant
    # positive control: the OLD selector is fooled by exactly this scene
    assert offsite_copy.newest_archive(b).name == _dr_name(0)
    code, st = _run(tmp_path, b, "full")
    assert code == 0, st
    assert st["archive_name"] == _daily_name(0)
    assert st["archive_class"] == "full" and st["complete"] is True
    assert not (tmp_path / "offsite" / _dr_name(0)).exists()


def test_critical_class_picks_the_critical_series_and_does_not_claim_completeness(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    _critical(b / _dr_name(30))  # OLDER than the daily one — still the only critical candidate
    code, st = _run(tmp_path, b, "critical")
    assert code == 0 and st["archive_name"] == _dr_name(30)
    assert st["archive_class"] == "critical" and st["complete"] is None


def test_undeclared_class_is_refused_and_never_touches_a_class_status(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    status = tmp_path / "status.json"
    proven = {"verified": True, "archive_class": "full", "complete": True, "last_offsite_ts": NOW.isoformat()}
    status.write_text(json.dumps(proven))
    refusal = tmp_path / "refusal.json"
    code = offsite_copy.run(backup_dir=b, dest_dir=tmp_path / "offsite", status_path=status,
                            archive_class_=None, refusal_path=refusal)
    assert code == 2
    assert json.loads(status.read_text()) == proven  # untouched
    assert json.loads(refusal.read_text())["error"] == "archive_class_not_declared"
    assert not (tmp_path / "offsite").exists()


def test_cli_requires_class():
    with pytest.raises(SystemExit) as e:
        offsite_copy.main(["--dest", "/nonexistent"])
    assert e.value.code == 2


def test_callers_declare_full_class():
    assert "--class full" in (ROOT / "scripts" / "daily_backup.sh").read_text()
    assert '"--class", "full"' in (ROOT / "scripts" / "resilience_cycle.py").read_text()


# ── 2. unprovable / disagreeing class ────────────────────────────────────────────────────────
def test_daily_name_without_manifest_is_refused_without_falling_back(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(1), _full_members(tmp_path))  # older, provable
    _write_archive(b / _daily_name(0), _full_members(tmp_path), manifest=False)  # newest, unprovable
    code, st = _run(tmp_path, b, "full")
    assert code != 0 and st["error"] == "class_unproven:manifest_missing"
    assert st["archive_name"] == _daily_name(0)
    assert not (tmp_path / "offsite").exists() or not list((tmp_path / "offsite").iterdir())


def test_witnesses_disagree_is_refused(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path), schema="spa_dr_backup/v2")
    proof = archive_class.prove_class(b / _daily_name(0))
    assert proof["class"] is None and proof["reason"].startswith("witnesses_disagree")
    code, st = _run(tmp_path, b, "full")
    assert code != 0 and st["error"].startswith("class_unproven:witnesses_disagree")


def test_legacy_names_classify_by_both_witnesses(tmp_path):
    full = _write_archive(tmp_path / _daily_name(0), {"a.json": b"{}"})
    crit = _critical(tmp_path / _dr_name(0))
    stray = _write_archive(tmp_path / "spa_state_handcopy.tar.gz", {"a.json": b"{}"})
    assert archive_class.prove_class(full)["class"] == "full"
    assert archive_class.prove_class(crit)["class"] == "critical"
    assert archive_class.prove_class(stray)["reason"] == "name_format_unrecognised"


# ── 3. destination / copy failures ───────────────────────────────────────────────────────────
def test_broken_destination_is_a_recorded_refusal(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    blocker = tmp_path / "offsite_is_a_file"
    blocker.write_text("not a directory")
    code, st = _run(tmp_path, b, "full", dest_dir=blocker)
    assert code != 0 and st["verified"] is False and st["error"].startswith("copy_error")
    assert st["archive_class"] == "full"


def test_remote_upload_is_never_claimed(tmp_path, monkeypatch):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    code, st = _run(tmp_path, b, "full", dest_dir=tmp_path / "icloud_like")
    assert code == 0 and st["is_real_remote"] is True and st["remote_upload"] == "NOT_MEASURED"
    monkeypatch.setattr(offsite_copy, "STANDIN_DEST", tmp_path / "standin")
    code, st = _run(tmp_path, b, "full", dest_dir=tmp_path / "standin")
    assert st["remote_upload"] == "SAME_HOST"


# ── 4. completeness of the FULL archive ──────────────────────────────────────────────────────
def test_complete_full_archive_verifies(tmp_path):
    rep = full_archive_verify.verify_archive(_write_archive(tmp_path / "a.tar.gz", _full_members(tmp_path)))
    assert rep["ok"] is True, rep["findings"]
    assert rep["replay_snapshots_referenced"] == 1 and rep["sqlite_checked"] == 3


@pytest.mark.parametrize("mutate,finding", [
    (lambda m: m.pop("research_factory/ledger.jsonl"), "required:missing:research_factory/ledger.jsonl"),
    (lambda m: m.pop("investment_cio_anchors/anchors.jsonl"), "required:missing:investment_cio_anchors/anchors.jsonl"),
    (lambda m: m.pop("trading_research/market.db"), "required:missing:trading_research/market.db"),
    (lambda m: [m.pop(k) for k in list(m) if k.startswith("investment_cio/snapshots/")], "replay:snapshot_missing"),
    (lambda m: m.update({k: gzip.compress(b'{"other":1}') for k in list(m) if "snapshots/" in k}), "replay:snapshot_digest_mismatch"),
    (lambda m: m.update({"track.db": b"SQLite format 3\x00" + b"\x00" * 200}), "sqlite:track.db"),
    (lambda m: m.update({"capital_shadow/ledger.jsonl": b"{not json\n"}), "ledger:capital_shadow/ledger.jsonl"),
])
def test_each_missing_or_broken_part_is_a_named_finding(tmp_path, mutate, finding):
    m = _full_members(tmp_path)
    mutate(m)
    rep = full_archive_verify.verify_archive(_write_archive(tmp_path / "a.tar.gz", m))
    assert rep["ok"] is False
    assert any(f.startswith(finding) for f in rep["findings"]), rep["findings"]


def test_manifest_sha_mismatch_and_unlisted_member_are_findings(tmp_path):
    m = _full_members(tmp_path)
    p = _write_archive(tmp_path / "a.tar.gz", m,
                       manifest_override={"files": [{"name": "golive_status.json", "sha256": "0" * 64}]})
    rep = full_archive_verify.verify_archive(p)
    assert "manifest:sha_mismatch:golive_status.json" in rep["findings"]
    assert any(f.startswith("manifest:unlisted_member:") for f in rep["findings"])


def test_unreadable_contract_fails_closed(tmp_path):
    rep = full_archive_verify.verify_archive(_write_archive(tmp_path / "a.tar.gz", _full_members(tmp_path)),
                                             provenance_path=tmp_path / "absent.json")
    assert rep["ok"] is False and any(f.startswith("contract:provenance_unreadable") for f in rep["findings"])


def test_incomplete_full_archive_is_copied_but_reported_incomplete(tmp_path):
    b = tmp_path / "backups"
    m = _full_members(tmp_path)
    m.pop("capital_shadow/ledger.jsonl")
    _write_archive(b / _daily_name(0), m)
    code, st = _run(tmp_path, b, "full")
    assert code != 0 and st["verified"] is True and st["complete"] is False
    assert "required:missing:capital_shadow/ledger.jsonl" in st["completeness"]["findings"]
    assert (tmp_path / "offsite" / _daily_name(0)).exists()  # preserved, not hidden
    assert archive_class.full_offsite_proven(st) == (False, "FULL archive incomplete")


# ── 5. one shared reading of the status for every consumer ──────────────────────────────────
@pytest.mark.parametrize("doc,expect", [
    (None, None),
    ({"verified": True, "is_real_remote": True}, False),                         # pre-ADR-611 status
    ({"verified": True, "archive_class": "critical", "complete": None}, False),
    ({"verified": True, "archive_class": "full", "complete": None}, False),       # not measured
    ({"verified": False, "archive_class": "full", "complete": True}, False),
    ({"verified": True, "archive_class": "full", "complete": True, "last_offsite_ts": NOW.isoformat()}, True),
])
def test_full_offsite_proven(doc, expect):
    assert archive_class.full_offsite_proven(doc, now=NOW)[0] is expect


# (The Company Truth consumer of the same reading is pinned in test_backups_three_facts.py —
#  company_truth may only be imported by its allow-listed tests, ADR-592 import ratchet.)


# ── 6. producer ↔ verifier parity, and the real producer end to end ──────────────────────────
def _load_daily_backup():
    spec = importlib.util.spec_from_file_location("daily_backup_adr611", str(ROOT / "scripts" / "daily_backup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_required_members_match_the_producer():
    db = _load_daily_backup()
    producer = set(db.MUST_HAVE) | set(db._SQLITE_FILES)
    optional = {"academy.db"}  # captured "when present" by the producer
    assert set(full_archive_verify.REQUIRED_MEMBERS) == producer - optional


def test_real_daily_producer_output_verifies_complete(tmp_path, monkeypatch):
    db = _load_daily_backup()
    data = tmp_path / "data"
    for name, raw in _full_members(tmp_path).items():
        p = data / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    (data / "backups").mkdir()
    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(data / "backups"))
    rep = db.snapshot(date_str=NOW.strftime("%Y-%m-%d"))
    assert rep["written"] is True
    arch = Path(rep["archive"])
    assert archive_class.prove_class(arch)["class"] == "full"
    v = full_archive_verify.verify_archive(arch)
    assert v["ok"] is True, v["findings"]


# ── 7. restore drill applies the same completeness to a proven FULL archive ──────────────────
def _load_drill(monkeypatch, backups: Path):
    spec = importlib.util.spec_from_file_location("drill_adr611", str(ROOT / "scripts" / "drill_restore.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_STATUS_PATH", str(backups.parent / "restore_drill_status.json"))
    return mod


def test_drill_fails_an_incomplete_full_archive_and_passes_a_complete_one(tmp_path, monkeypatch):
    b = tmp_path / "x" / "backups"
    drill = _load_drill(monkeypatch, b)
    good = _write_archive(b / _daily_name(1), _full_members(tmp_path))
    r = drill._drill_one(str(good))
    entry = next(e for e in r["files_validated"] if e["file"] == "full_archive_completeness")
    assert entry["ok"] is True and r["archive_class"]["class"] == "full"
    m = _full_members(tmp_path)
    m.pop("investment_cio/ledger.jsonl")
    bad = _write_archive(b / _daily_name(0), m)
    r = drill._drill_one(str(bad))
    entry = next(e for e in r["files_validated"] if e["file"] == "full_archive_completeness")
    assert entry["ok"] is False and r["all_ok"] is False


def test_drill_names_an_unprovable_class_instead_of_assuming_full(tmp_path, monkeypatch):
    b = tmp_path / "x" / "backups"
    drill = _load_drill(monkeypatch, b)
    legacy = _write_archive(b / _daily_name(0), _full_members(tmp_path), manifest=False)
    r = drill._drill_one(str(legacy))
    assert r["archive_class"] == {"class": None, "reason": "manifest_missing"}
    assert not any(e["file"] == "full_archive_completeness" for e in r["files_validated"])



# ── 8. independent-review findings (P0 / P1 / P2) ────────────────────────────────────────────
def _flip_snapshot_byte(m: dict) -> None:
    k = next(k for k in m if k.startswith("investment_cio/snapshots/"))
    b = bytearray(m[k])
    # gzip.compress writes a 10-byte header; byte 10 opens the first deflate block. Setting
    # BTYPE=11 (reserved) makes zlib raise zlib.error — NOT an OSError — which is exactly the
    # exception class that escaped the verifier (review P0). Deterministic, one byte.
    b[10] |= 0x06
    m[k] = bytes(b)


def test_p0_corrupted_snapshot_is_a_finding_not_a_crash(tmp_path):
    m = _full_members(tmp_path)
    _flip_snapshot_byte(m)
    rep = full_archive_verify.verify_archive(_write_archive(tmp_path / "a.tar.gz", m))
    assert rep["ok"] is False
    assert any(f.startswith("replay:snapshot_unreadable:") and f.endswith(":error")
               for f in rep["findings"]), rep["findings"]


def test_p0_any_verifier_crash_replaces_a_prior_proven_status(tmp_path):
    b = tmp_path / "backups"
    _write_archive(b / _daily_name(0), _full_members(tmp_path))
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"verified": True, "archive_class": "full", "complete": True,
                                  "last_offsite_ts": NOW.isoformat()}))

    def boom(_p):
        import zlib
        raise zlib.error("invalid stored block lengths")
    code = offsite_copy.run(backup_dir=b, dest_dir=tmp_path / "offsite", status_path=status,
                            archive_class_="full", verify_full=boom)
    st = json.loads(status.read_text())
    assert code != 0 and st["complete"] is False
    assert st["completeness"]["findings"][0].startswith("verifier_error:error")
    assert archive_class.full_offsite_proven(st, now=NOW)[0] is False


def test_p0_real_flipped_byte_end_to_end(tmp_path):
    b = tmp_path / "backups"
    m = _full_members(tmp_path)
    _flip_snapshot_byte(m)
    _write_archive(b / _daily_name(0), m)
    code, st = _run(tmp_path, b, "full")
    assert code != 0 and st["complete"] is False


def test_p1a_proven_status_goes_stale(tmp_path):
    ok = {"verified": True, "archive_class": "full", "complete": True}
    fresh = dict(ok, last_offsite_ts=(NOW - timedelta(hours=20)).isoformat())
    old = dict(ok, last_offsite_ts=(NOW - timedelta(days=archive_class.OFFSITE_STALE_DAYS + 0.5)).isoformat())
    assert archive_class.full_offsite_proven(fresh, now=NOW) == (True, None)
    proven, why = archive_class.full_offsite_proven(old, now=NOW)
    assert proven is False and why.startswith("stale")
    assert archive_class.full_offsite_proven(dict(ok), now=NOW)[0] is False  # no timestamp


def test_future_dated_proof_is_not_trusted():
    """Re-review P2 (07.10): a future ``last_offsite_ts`` gave a negative age and read as proven."""
    ok = {"verified": True, "archive_class": "full", "complete": True}
    ahead = dict(ok, last_offsite_ts=(NOW + timedelta(hours=3)).isoformat())
    proven, why = archive_class.full_offsite_proven(ahead, now=NOW)
    assert proven is False and "future" in why
    skew = dict(ok, last_offsite_ts=(NOW + timedelta(minutes=5)).isoformat())
    assert archive_class.full_offsite_proven(skew, now=NOW) == (True, None)


def test_p1a_one_threshold_source():
    from spa_core.monitoring import resilience_status
    assert resilience_status.OFFSITE_STALE_DAYS is archive_class.OFFSITE_STALE_DAYS


def test_p1b_source_changing_during_verify_is_refused(tmp_path):
    b = tmp_path / "backups"
    src = _write_archive(b / _daily_name(0), _full_members(tmp_path))

    def mutate_then_pass(p):
        with open(p, "ab") as f:
            f.write(b"appended-after-hash")
        return {"ok": True, "findings": []}
    code, st = _run(tmp_path, b, "full", verify_full=mutate_then_pass)
    assert code != 0 and st["error"] == "source_changed_during_verify" and st["complete"] is False
    assert not (tmp_path / "offsite" / src.name).exists()


def test_p2_incomplete_copies_never_evict_the_last_complete_one(tmp_path):
    b = tmp_path / "backups"
    dest = tmp_path / "offsite"
    _write_archive(b / _daily_name(5), _full_members(tmp_path))
    assert _run(tmp_path, b, "full", dest_dir=dest, keep=2)[0] == 0
    m = _full_members(tmp_path)
    m.pop("capital_shadow/ledger.jsonl")
    for d in (4, 3, 2, 1):
        _write_archive(b / _daily_name(d), m)
        assert _run(tmp_path, b, "full", dest_dir=dest, keep=2)[0] != 0
    assert (dest / _daily_name(5)).exists()  # the last complete copy survived four incomplete runs


def test_p2_symlinked_archive_is_not_a_candidate(tmp_path):
    b = tmp_path / "backups"
    real = _write_archive(b / _daily_name(1), _full_members(tmp_path))
    (b / _daily_name(0)).symlink_to(real)
    assert [p.name for p in archive_class.candidates(b, "full")] == [_daily_name(1)]


def test_p2_tar_path_traversal_is_rejected(tmp_path):
    p = tmp_path / "evil.tar.gz"
    with tarfile.open(p, "w:gz") as tar:
        raw = b"x"
        ti = tarfile.TarInfo("../escaped.json"); ti.size = 1
        tar.addfile(ti, io.BytesIO(raw))
    rep = full_archive_verify.verify_archive(p, workdir=str(tmp_path))
    assert rep["ok"] is False and rep["findings"][0].startswith("archive:unextractable:ValueError")
    assert not (tmp_path.parent / "escaped.json").exists()


def test_p2_mission_control_label_means_proven(tmp_path):
    from spa_core.studio_os import mission_control as mc
    src = (ROOT / "spa_core" / "studio_os" / "mission_control.py").read_text()
    assert '"offsite_verified": off_ok' in src and '"offsite_sha_verified_raw"' in src
    gov = (ROOT / "scripts" / "cartographer" / "governance.py").read_text()
    assert "сырое поле, НЕ доказательство полноты" in gov
