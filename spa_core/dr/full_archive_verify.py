"""
spa_core/dr/full_archive_verify.py — is a FULL archive actually COMPLETE enough to restore from?

WHY (ARB-CONTINUITY-01 Wave B, ADR-611)
---------------------------------------
A sha256-verified offsite copy proves the bytes travelled intact. It does not prove those
bytes are a backup worth having: until RM-TRUTH-01 the daily archive silently lacked every
append-only ledger of the newer engines (ADR-554/556/560), and until 2026-10-07 it lacked the
CIO input snapshots its ledger references by hash — a restored CIO ledger could not be
replayed. Each gap was found by a human reading a member list. This module asks the question
mechanically, on the archive itself, and is reused by the offsite copy (before it claims a
FULL copy) and by the restore drill (after it extracts one).

What "complete" means for the FULL class (each a NAMED finding when it fails):

  manifest      ``backup_manifest.json`` parses, schema ``spa_daily_backup/*``, every listed
                member is present with the sha256 the manifest states, no member is unlisted.
  required      canonical critical state + track/evidence/market sqlite DBs
                (``REQUIRED_MEMBERS``) + every append-only ledger DECLARED in
                ``architecture/provenance.json`` (read at verification time: a new declaration
                is enforced without editing this file; contract unreadable ⇒ fail-CLOSED).
  sqlite        every ``*.db`` member opens read-only and passes ``PRAGMA integrity_check``.
  ledgers       every ``*.jsonl`` ledger member parses line by line.
  replay        every ``snapshot_digest`` referenced by ``investment_cio/ledger.jsonl`` has its
                ``investment_cio/snapshots/<digest>.json.gz`` member AND that member's content
                hashes back to the digest (a present-but-wrong snapshot replays a different input).

stdlib-only · read-only: extraction goes to a private temp dir that is always removed.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PROVENANCE = REPO / "architecture" / "provenance.json"

MANIFEST_NAME = "backup_manifest.json"
FULL_SCHEMA_PREFIX = "spa_daily_backup/"

#: Members a FULL archive must carry regardless of the ledger declaration. Parity with
#: ``scripts/daily_backup.py`` (MUST_HAVE + _SQLITE_FILES) is pinned by a test, so the
#: producer and this checker cannot drift apart silently.
REQUIRED_MEMBERS = (
    "golive_status.json",
    "equity_curve_daily.json",
    "paper_evidence_history.json",
    "current_positions.json",
    "track.db",
    "trading_research/evidence.db",
    "trading_research/market.db",
)

CIO_LEDGER = "investment_cio/ledger.jsonl"
CIO_SNAPSHOT_DIR = "investment_cio/snapshots"


def declared_ledgers(provenance_path: Path = DEFAULT_PROVENANCE) -> List[str]:
    """Archive member names of the declared append-only ledgers. Raises on an unreadable
    or empty declaration — "no contract" must never read as "nothing required"."""
    doc = json.loads(Path(provenance_path).read_text(encoding="utf-8"))
    entries = (doc.get("append_only_ledgers") or {}).get("entries") or []
    out = []
    for e in entries:
        p = str(e.get("path", ""))
        if not p.startswith("data/"):
            raise ValueError(f"declared ledger path not under data/: {p!r}")
        out.append(p[len("data/"):])
    if not out:
        raise ValueError("append_only_ledgers.entries is empty")
    return sorted(set(out))


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _safe_extract(archive: Path, dest: str) -> List[str]:
    names = []
    real_dest = os.path.realpath(dest)
    with tarfile.open(str(archive), "r:gz") as tar:
        for m in tar.getmembers():
            n = m.name
            if n.startswith("/") or ".." in n.split("/") or m.issym() or m.islnk():
                raise ValueError(f"unsafe member rejected: {n!r}")
            target = os.path.realpath(os.path.join(dest, n))
            if not (target == real_dest or target.startswith(real_dest + os.sep)):
                raise ValueError(f"member escapes extraction dir: {n!r}")
            try:
                tar.extract(m, dest, filter="data")
            except TypeError:  # pragma: no cover — Python < 3.12
                tar.extract(m, dest)
            if m.isfile():
                names.append(n)
    return names


def _sqlite_ok(path: str) -> Optional[str]:
    con = None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = con.execute("PRAGMA integrity_check").fetchone()
        return None if row and row[0] == "ok" else f"integrity_check={row}"
    except sqlite3.DatabaseError as exc:
        return f"sqlite_error:{exc}"
    finally:
        if con is not None:
            con.close()


def verify_extracted(root: str, members: List[str], *,
                     provenance_path: Path = DEFAULT_PROVENANCE) -> Dict[str, Any]:
    """Verify an ALREADY-EXTRACTED full archive at *root* (used by the restore drill)."""
    member_set = set(members)
    findings: List[str] = []
    report: Dict[str, Any] = {"members": len(member_set)}

    # 1) manifest
    manifest = None
    if MANIFEST_NAME not in member_set:
        findings.append("manifest:missing")
    else:
        try:
            manifest = json.loads(Path(root, MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            findings.append(f"manifest:unparseable:{type(exc).__name__}")
    if isinstance(manifest, dict):
        schema = manifest.get("schema")
        report["schema"] = schema
        if not (isinstance(schema, str) and schema.startswith(FULL_SCHEMA_PREFIX)):
            findings.append(f"manifest:not_full_class:{schema!r}")
        listed = {}
        for e in manifest.get("files") or []:
            if isinstance(e, dict) and e.get("name"):
                listed[e["name"]] = e.get("sha256")
        bad = []
        for name, want in sorted(listed.items()):
            if name not in member_set:
                bad.append(f"manifest:listed_but_absent:{name}")
            elif want and _sha256_file(os.path.join(root, name)) != want:
                bad.append(f"manifest:sha_mismatch:{name}")
        unlisted = sorted(member_set - set(listed) - {MANIFEST_NAME})
        bad += [f"manifest:unlisted_member:{n}" for n in unlisted]
        findings += bad
        report["manifest_files"] = len(listed)

    # 2) required members (+ declared ledgers)
    try:
        ledgers = declared_ledgers(provenance_path)
    except (OSError, ValueError) as exc:
        ledgers = []
        findings.append(f"contract:provenance_unreadable:{type(exc).__name__}")
    required = sorted(set(REQUIRED_MEMBERS) | set(ledgers))
    missing = [n for n in required if n not in member_set]
    findings += [f"required:missing:{n}" for n in missing]
    report["required"] = len(required)
    report["declared_ledgers"] = ledgers

    # 3) sqlite integrity
    dbs = sorted(n for n in member_set if n.endswith(".db"))
    for n in dbs:
        err = _sqlite_ok(os.path.join(root, n))
        if err:
            findings.append(f"sqlite:{n}:{err}")
    report["sqlite_checked"] = len(dbs)

    # 4) ledger lines parse
    for n in sorted(x for x in ledgers if x.endswith(".jsonl") and x in member_set):
        try:
            with open(os.path.join(root, n), encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if line.strip():
                        json.loads(line)
        except (OSError, ValueError) as exc:
            findings.append(f"ledger:{n}:unparseable_line:{type(exc).__name__}")

    # 5) CIO replay inputs
    digests: List[str] = []
    if CIO_LEDGER in member_set:
        try:
            with open(os.path.join(root, CIO_LEDGER), encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line).get("snapshot_digest")
                        if d:
                            digests.append(str(d))
        except (OSError, ValueError, AttributeError):
            findings.append("replay:cio_ledger_unreadable")
    for d in sorted(set(digests)):
        name = f"{CIO_SNAPSHOT_DIR}/{d}.json.gz"
        if name not in member_set:
            findings.append(f"replay:snapshot_missing:{d[:16]}")
            continue
        try:
            raw = gzip.decompress(Path(root, name).read_bytes())
        except (OSError, EOFError, zlib.error) as exc:  # a flipped byte raises zlib.error
            findings.append(f"replay:snapshot_unreadable:{d[:16]}:{type(exc).__name__}")
            continue
        if hashlib.sha256(raw).hexdigest() != d:
            findings.append(f"replay:snapshot_digest_mismatch:{d[:16]}")
    report["replay_snapshots_referenced"] = len(set(digests))

    report["findings"] = findings
    report["ok"] = not findings
    return report


def verify_archive(archive: Path, *, provenance_path: Path = DEFAULT_PROVENANCE,
                   workdir: Optional[str] = None) -> Dict[str, Any]:
    """Extract *archive* to a private temp dir, :func:`verify_extracted`, always clean up."""
    tmp = tempfile.mkdtemp(prefix="spa_full_verify_", dir=workdir)
    try:
        try:
            members = _safe_extract(Path(archive), tmp)
        except (OSError, tarfile.TarError, EOFError, ValueError) as exc:
            return {"ok": False, "findings": [f"archive:unextractable:{type(exc).__name__}:{exc}"],
                    "archive": Path(archive).name}
        rep = verify_extracted(tmp, members, provenance_path=provenance_path)
        rep["archive"] = Path(archive).name
        return rep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    import sys
    r = verify_archive(Path(sys.argv[1]))
    print(json.dumps(r, indent=1, ensure_ascii=False))
    raise SystemExit(0 if r["ok"] else 1)
