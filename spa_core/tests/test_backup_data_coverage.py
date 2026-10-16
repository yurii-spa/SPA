"""
spa_core/tests/test_backup_data_coverage.py — data-coverage audit 2026-10-16
(docs/backup/DATA_COVERAGE_2026-10-16.md): every data/ subtree classified NECESSARY must ride in
the daily FULL archive, and the classes that must NOT ride (the archives themselves, the disposable
memory index, lock/tmp scratch, torn raw sqlite copies) stay out.

WHY: the measurement of 2026-10-16 found 46 data/ subdirectories outside FULL, among them two
SIBLING anchor witnesses (capital_shadow_anchors, research_factory_anchors) of ledgers FULL already
required — a restored ledger without its anchor cannot prove it was not rewritten, which is exactly
why investment_cio_anchors was added for ADR-554. Also outside: forward proof-chained paper series
(aggressive_lab, swarm, strategy_lab_paper), the ADR-066 verdict archive (investment_os), owner
records (cmo_drafts approvals, telegram prefs) and incident forensics.

Positive controls: on the code before the audit (origin 8f913113) test 1 is RED (aggressive_lab/…
and the anchors are not members), test 2 is RED (the anchors are not required, so an archive
lacking them verifies clean), test 3 is RED (no _EVIDENCE_SUBTREES).

Hermetic: scripts/daily_backup.py is loaded as a module with _DATA/_BACKUPS redirected to tmp_path.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import sqlite3
import tarfile
from pathlib import Path

from spa_core.dr import full_archive_verify

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "backup" / "DATA_COVERAGE_2026-10-16.md"

#: Pinned literally (not read from the module): the test must fail if the producer's list shrinks.
NECESSARY_MEMBERS = (
    "capital_shadow_anchors/anchors.jsonl",
    "research_factory_anchors/ledger.anchors.jsonl",
    "aggressive_lab/susde_dn/realized_series.jsonl",
    "aggressive_lab/susde_dn/meta.json",
    "swarm/blend_forward_proof.jsonl",
    "strategy_lab_paper/fluid_series.json",
    "sleeve_aggressive/ledger.jsonl",
    "investment_os/quant_verdicts.jsonl",
    "dfb/history/pool_x.jsonl",
    "monitoring/risk_posture.json",
    "monitoring/reaction_log.json",
    "telegram/user_prefs.json",
    "cmo_drafts/cmo_20260718_000.json",
    "daily_summaries/2026-10-15.json",
    "statements/2026-06.json",
    "dd_snapshot/SNAPSHOT_MANIFEST.json",
    "bee/pinned/safety_report.json",
    "publication_inputs/" + "ab" * 32 + ".json",
    "reports/golive_readiness_2026-07-29.md",   # non-json evidence rides too
    "dataroom/spa_dataroom_20260711-001502.zip",
    "_corrupt_snapshot_20260625/golive_status.json",
    "sandbox_sweep/capital_sweep.json",
    "golive_status.json.pre_heal_bak",
    "rates_desk/anchors.jsonl.orphaned-20260710",
)
MUST_NOT_RIDE = (
    "backups/spa_state_2026-10-15.tar.gz",
    "backups/spa_2026-10-15.db",
    "memory/index.db",
    "capital_shadow/.ledger.lock",
    "trading_research/tick.lock",
    "monitoring/scratch.tmp",
    "aggressive_lab/raw_copy.db",     # a raw live-db copy would be torn; sqlite rides via _SQLITE_FILES only
    "investment_os/.hidden",
)


def _load():
    spec = importlib.util.spec_from_file_location("daily_backup_cov", str(_ROOT / "scripts" / "daily_backup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE t(x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
    finally:
        con.close()


def _seed(data: Path) -> None:
    (data / "golive_status.json").write_text(json.dumps({"passed": 1, "total": 1}))
    (data / "equity_curve_daily.json").write_text(json.dumps({"daily": []}))
    (data / "paper_evidence_history.json").write_text(json.dumps({"days": []}))
    (data / "current_positions.json").write_text("[]")
    _sqlite(data / "track.db")
    for rel in NECESSARY_MEMBERS + MUST_NOT_RIDE:
        p = data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".db"):
            _sqlite(p)
        else:
            p.write_bytes(('{"seq": 1, "rel": "%s"}\n' % rel).encode())


def _snapshot(tmp_path, monkeypatch):
    db = _load()
    data = tmp_path / "data"
    data.mkdir()
    _seed(data)
    monkeypatch.setattr(db, "_DATA", str(data))
    monkeypatch.setattr(db, "_BACKUPS", str(data / "backups"))
    rep = db.snapshot(date_str="2026-10-16")
    assert rep["written"] is True
    with tarfile.open(rep["archive"], "r:gz") as tar:
        return data, {m.name: (tar.extractfile(m).read() if m.isfile() else None) for m in tar.getmembers()}


def test_every_necessary_subtree_rides_and_scratch_does_not(tmp_path, monkeypatch):
    data, members = _snapshot(tmp_path, monkeypatch)
    missing = [n for n in NECESSARY_MEMBERS if n not in members]
    assert not missing, f"NECESSARY data/ members missing from the FULL archive: {missing}"
    for n in NECESSARY_MEMBERS:  # byte-for-byte, not just by name
        assert members[n] == (data / n).read_bytes(), n
    leaked = [n for n in MUST_NOT_RIDE if n in members]
    assert not leaked, f"TEMPORARY / never-archive members leaked into the archive: {leaked}"


def _write_archive(path: Path, members: dict) -> Path:
    files = [{"name": n, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in sorted(members.items())]
    with tarfile.open(path, "w:gz") as tar:
        raw = json.dumps({"schema": "spa_daily_backup/v2", "files": files}).encode()
        ti = tarfile.TarInfo("backup_manifest.json"); ti.size = len(raw)
        tar.addfile(ti, io.BytesIO(raw))
        for n, b in sorted(members.items()):
            ti = tarfile.TarInfo(n); ti.size = len(b)
            tar.addfile(ti, io.BytesIO(b))
    return path


def _complete_members(tmp: Path) -> dict:
    snap = b'{"sleeves":{}}'
    digest = hashlib.sha256(snap).hexdigest()
    m = {
        "golive_status.json": b"{}", "equity_curve_daily.json": b"{}",
        "paper_evidence_history.json": b"{}", "current_positions.json": b"[]",
        f"investment_cio/snapshots/{digest}.json.gz": gzip.compress(snap),
    }
    for name in ("track.db", "spa.db", "trading_research/evidence.db", "trading_research/market.db"):
        p = tmp / ("_" + name.replace("/", "_"))
        _sqlite(p)
        m[name] = p.read_bytes()
    for led in full_archive_verify.declared_ledgers():
        if led.endswith(".jsonl"):
            m[led] = b'{"seq": 1}\n'
    m["investment_cio/ledger.jsonl"] = (json.dumps({"seq": 1, "snapshot_digest": digest}) + "\n").encode()
    return m


def test_full_verification_requires_both_sibling_anchor_witnesses(tmp_path):
    complete = _complete_members(tmp_path)
    ok = full_archive_verify.verify_archive(_write_archive(tmp_path / "ok.tar.gz", complete))
    assert ok["ok"], ok["findings"]   # control: the complete scene verifies clean
    for anchor in ("capital_shadow_anchors/anchors.jsonl", "research_factory_anchors/ledger.anchors.jsonl"):
        m = dict(complete)
        assert anchor in m, f"{anchor} is not a declared ledger in architecture/provenance.json"
        m.pop(anchor)
        rep = full_archive_verify.verify_archive(_write_archive(tmp_path / "no_anchor.tar.gz", m))
        assert not rep["ok"] and f"required:missing:{anchor}" in rep["findings"], rep["findings"]


def test_evidence_list_never_names_the_archives_and_matches_the_classification_doc():
    db = _load()
    subtrees = set(db._EVIDENCE_SUBTREES) | set(db._PROOF_SUBTREES)
    assert not subtrees & {"backups", "memory"}, "the archives / disposable index must never be archived"
    assert {"backups", "memory"} <= set(db._NEVER_SUBTREES)
    doc = _DOC.read_text(encoding="utf-8")
    undocumented = [s for s in db._EVIDENCE_SUBTREES if f"`{s}`" not in doc]
    assert not undocumented, f"captured subtrees without a row in {_DOC.name}: {undocumented}"
