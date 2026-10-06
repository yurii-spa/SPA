"""
spa_core/tests/test_dr_ledger_coverage.py — ADR-580 C10 (RM-TRUTH-01): every append-only
ledger DECLARED in architecture/provenance.json must ride in the daily DR archive.

WHY: A4/REVIEW_1 (2026-10-05) measured that the daily archive (scripts/daily_backup.py)
carried `data/paper_evidence.json` and `trading_research/evidence.db`, but NONE of the
newer advisory engines' append-only ledgers — `investment_cio/ledger.jsonl`,
`investment_cio_anchors/anchors.jsonl`, `research_factory/ledger.jsonl`,
`capital_shadow/ledger.jsonl` — were in it at all. The ONLY thing that ever covered them
was `com.spa.weekly_backup`, which `RETIRED_LABELS` treats as superseded by
daily_backup + dr_offsite_copy — a replacement that never actually took over this part of
weekly_backup's job (REVIEW_1 item #12).

This test is the RATCHET, not a one-off fixture check: `architecture/provenance.json`'s
`append_only_ledgers.entries` is the declared canon. Any future session that adds an entry
there without also teaching the archive producer to carry it gets a RED test here — it
cannot repeat the same silent gap for a sixth ledger.

Hermetic: scripts/daily_backup.py is loaded as a module and its _DATA/_BACKUPS redirected
to tmp_path; the live data/ tree is never read or written.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_PROVENANCE = _ROOT / "architecture" / "provenance.json"


def _load_daily_backup_module():
    """Import scripts/daily_backup.py as a module (mirrors test_backup_completeness.py)."""
    spec = importlib.util.spec_from_file_location(
        "daily_backup_under_test_dr", str(_SCRIPTS / "daily_backup.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _declared_ledger_paths() -> list:
    """Read architecture/provenance.json → append_only_ledgers.entries[].path.

    These are repo-relative (e.g. "data/investment_cio/ledger.jsonl"); stripped of the
    leading "data/" they are exactly the archive member names daily_backup.py produces.
    """
    doc = json.loads(_PROVENANCE.read_text())
    entries = doc.get("append_only_ledgers", {}).get("entries", [])
    assert entries, (
        "architecture/provenance.json has no append_only_ledgers.entries — the declared "
        "canon this test checks the archive against is itself empty/missing"
    )
    paths = []
    for e in entries:
        p = e.get("path", "")
        assert p.startswith("data/"), f"declared ledger path {p!r} is not under data/"
        paths.append(p[len("data/"):])
    return paths


def _seed_must_have(data: Path) -> None:
    """The archive fail-CLOSES if MUST_HAVE is absent — seed the real critical set (plus
    a real sqlite track.db) so snapshot() can run at all, independent of what THIS test
    is checking."""
    (data / "golive_status.json").write_text(json.dumps({"passed": 27, "total": 29}))
    (data / "equity_curve_daily.json").write_text(json.dumps({"daily": []}))
    (data / "paper_evidence_history.json").write_text(json.dumps({"days": []}))
    (data / "current_positions.json").write_text(json.dumps([]))
    con = sqlite3.connect(str(data / "track.db"))
    try:
        con.execute("CREATE TABLE t(x INTEGER)")
        con.commit()
    finally:
        con.close()


def _seed_declared_ledgers(data: Path, rel_paths: list) -> None:
    """Write a minimal real file at each declared ledger path, mirroring the real shapes
    (jsonl/db/anchors) so the archive is exercised exactly as it will be in production."""
    for rel in rel_paths:
        p = data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".db":
            con = sqlite3.connect(str(p))
            try:
                con.execute("CREATE TABLE evidence(seq INTEGER, hash TEXT)")
                con.execute("INSERT INTO evidence VALUES (1, 'abc')")
                con.commit()
            finally:
                con.close()
        else:
            p.write_text('{"seq": 1, "entry_hash": "abc"}\n')


def test_every_declared_ledger_is_in_the_archive(tmp_path, monkeypatch):
    """The ratchet itself: build a real archive and prove every declared-canon path is a
    member. Fails red the day a declared ledger is not carried."""
    rel_paths = _declared_ledger_paths()

    db = _load_daily_backup_module()
    data = tmp_path / "data"
    backups = data / "backups"
    data.mkdir(parents=True)
    backups.mkdir(parents=True)
    _seed_must_have(data)
    _seed_declared_ledgers(data, rel_paths)

    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(backups))

    rep = db.snapshot(date_str="2026-10-05")
    assert rep["written"] is True

    import tarfile
    with tarfile.open(rep["archive"], "r:gz") as tar:
        members = set(tar.getnames())

    missing = [p for p in rel_paths if p not in members]
    assert not missing, (
        f"declared append-only ledger(s) {missing} are MISSING from the daily DR archive "
        f"(members={sorted(members)}) — architecture/provenance.json declares them but "
        f"scripts/daily_backup.py does not carry them; teach it a new _PROOF_SUBTREES / "
        f"_SQLITE_FILES entry"
    )


def test_declared_ledgers_cover_the_four_rm_truth_01_engines():
    """Pin against the declaration itself silently shrinking back to just evidence.db —
    the four A4-measured gaps must stay named."""
    rel_paths = set(_declared_ledger_paths())
    expected = {
        "investment_cio/ledger.jsonl",
        "investment_cio_anchors/anchors.jsonl",
        "research_factory/ledger.jsonl",
        "capital_shadow/ledger.jsonl",
    }
    missing = expected - rel_paths
    assert not missing, f"architecture/provenance.json dropped declared ledger(s) {missing}"


def test_daily_backup_subtrees_carry_every_declared_jsonl_ledger_without_a_fixture():
    """Direct unit check on _PROOF_SUBTREES, independent of the full snapshot() path:
    every declared *.jsonl ledger's PARENT directory must be a captured subtree (or the
    top-level data/ glob, for a path with no '/'). Catches the gap even if a future
    snapshot() refactor stops using _PROOF_SUBTREES by name."""
    db = _load_daily_backup_module()
    rel_paths = [p for p in _declared_ledger_paths() if p.endswith(".jsonl")]
    for rel in rel_paths:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        assert parent == "" or parent in db._PROOF_SUBTREES, (
            f"{rel!r}'s parent directory {parent!r} is not in _PROOF_SUBTREES "
            f"{db._PROOF_SUBTREES} and is not top-level — the jsonl glob never reaches it"
        )


def test_declared_sqlite_ledger_is_in_sqlite_files_or_a_subtree():
    """The one declared *.db ledger (evidence.db) must be explicitly captured — sqlite
    files are never matched by the *.json/*.jsonl glob."""
    db = _load_daily_backup_module()
    rel_paths = [p for p in _declared_ledger_paths() if p.endswith(".db")]
    assert rel_paths, "expected at least one declared sqlite ledger (evidence.db)"
    for rel in rel_paths:
        assert rel in db._SQLITE_FILES, (
            f"{rel!r} is declared as an append-only ledger but is not in _SQLITE_FILES "
            f"{db._SQLITE_FILES} — a sqlite member is never picked up by the json glob"
        )
