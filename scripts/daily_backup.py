#!/usr/bin/env python3
"""
scripts/daily_backup.py — DAILY full snapshot of ALL data/*.json (+ *.jsonl) state.

WHY: SPA runs on a single Mac mini (SPOF). The DR primitive
spa_core/backtesting/tier1/dr_backup.py snapshots only ~10 hand-picked CRITICAL_FILES
and was NEVER wired to a schedule, so data/backups/ had no reliable recent snapshots —
a prior corruption lost real data because the last usable backup was stale. This module
is the broad, scheduled safety net: it captures EVERY data/*.json and data/*.jsonl into a
single integrity-checked gzip tar each day, atomically, with 30-day retention.

Scope (deliberately broad): all of data/*.json and data/*.jsonl at the top level of data/.
This includes the critical state (equity_curve_daily, golive_status, paper_trading_status,
trades, current_positions, gap_monitor, paper_evidence_history, strategy_*, tier1_*, etc.)
plus the audit chain/trail jsonl files. The archive name is DATE-stamped
(spa_state_YYYY-MM-DD.tar.gz) so at most one snapshot per day is kept and re-runs overwrite
that day's archive deterministically.

stdlib-only · atomic (build temp tar in same dir, shutil.move into place) · deterministic
(manifest member mtime pinned to 0; identical inputs → identical member set).

Usage:
  python3 scripts/daily_backup.py                # create today's snapshot + prune
  python3 scripts/daily_backup.py --dry-run      # show what would be captured
  python3 scripts/daily_backup.py --verify PATH  # re-hash an archive against its manifest
  python3 scripts/daily_backup.py --retention 30 # keep last N daily archives (default 30)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_REPO_ROOT, "data")
_BACKUPS = os.path.join(_DATA, "backups")

ARCHIVE_PREFIX = "spa_state_"
ARCHIVE_SUFFIX = ".tar.gz"
MANIFEST_NAME = "backup_manifest.json"
DEFAULT_RETENTION = 30
_CHUNK = 1 << 20  # 1 MiB

# The MUST-HAVE recovery set (same as the DR producer). The daily glob already captures the
# *.json members, but track.db is a *.db and is NOT matched by the glob — it is added
# explicitly via a consistent sqlite copy so EVERY archive carries the full critical set.
# A backup missing any of these fail-CLOSES (no partial archive = no backup theater).
MUST_HAVE = [
    "golive_status.json",
    "equity_curve_daily.json",
    "paper_evidence_history.json",
    "current_positions.json",
    "track.db",
]
# Files captured via the sqlite online-backup API (consistent even if mid-write).
_SQLITE_FILES = ("track.db",)


class BackupIncompleteError(RuntimeError):
    """Raised fail-CLOSED when a produced archive is missing a MUST_HAVE critical file."""


def _consistent_sqlite_copy(src: str, dst: str) -> None:
    """Transactionally-consistent copy of a (possibly mid-write) sqlite DB via the online
    backup API, so the archived .db always opens clean."""
    src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_con = sqlite3.connect(dst)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _archive_path(date_str: str) -> str:
    return os.path.join(_BACKUPS, f"{ARCHIVE_PREFIX}{date_str}{ARCHIVE_SUFFIX}")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_sources() -> list:
    """All top-level data/*.json and data/*.jsonl, sorted for determinism."""
    files = []
    for pattern in ("*.json", "*.jsonl"):
        files.extend(glob.glob(os.path.join(_DATA, pattern)))
    files = [f for f in files if os.path.isfile(f)]
    return sorted(files)


def snapshot(date_str: str = "", dry_run: bool = False) -> dict:
    """Create a DATE-stamped gzip-tar of all data/*.json + *.jsonl, with embedded manifest.

    Returns a report dict. Atomic: tar built in a temp file in the backups dir, then
    shutil.move into the final name (matches the project's cross-device-safe convention).
    """
    date_str = date_str or _today()
    sources = _collect_sources()

    # Stage consistent copies of sqlite members (track.db) in a scratch dir so the bytes we
    # hash are exactly the bytes we tar (and they open clean). Removed in finally.
    scratch = tempfile.mkdtemp(prefix="spa_daily_stage_")
    try:
        entries = []   # each: {name, sha256, size, _src}
        total = 0
        for src in sources:
            rel = os.path.relpath(src, _DATA)  # e.g. "trades.json"
            size = os.path.getsize(src)
            entries.append({"name": rel, "sha256": _sha256_file(src), "size": size, "_src": src})
            total += size

        # Explicitly add sqlite members (NOT matched by the *.json/*.jsonl glob) via a
        # consistent copy, so track.db lands INSIDE the tar — not as a separate bare .db.
        have = {e["name"] for e in entries}
        for rel in _SQLITE_FILES:
            if rel in have:
                continue
            src = os.path.join(_DATA, rel)
            if not os.path.isfile(src):
                continue
            staged = os.path.join(scratch, os.path.basename(rel))
            _consistent_sqlite_copy(src, staged)
            entries.append({
                "name": rel,
                "sha256": _sha256_file(staged),
                "size": os.path.getsize(staged),
                "_src": staged,
            })
            total += os.path.getsize(staged)

        entries.sort(key=lambda e: e["name"])  # deterministic member order

        # Fail-CLOSED completeness pre-check: every MUST_HAVE critical file must be present.
        present = {e["name"] for e in entries}
        missing_critical = [c for c in MUST_HAVE if c not in present]
        if missing_critical:
            raise BackupIncompleteError(
                "REFUSING to write daily backup: missing critical file(s) "
                f"{missing_critical} (have={sorted(present)})"
            )

        manifest_files = [{k: v for k, v in e.items() if not k.startswith("_")}
                          for e in entries]
        manifest = {
            "schema": "spa_daily_backup/v2",
            "llm_forbidden": True,
            "date": date_str,
            "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "file_count": len(manifest_files),
            "total_bytes": total,
            "files": manifest_files,
            "must_have": list(MUST_HAVE),
        }
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

        report = {
            "date": date_str,
            "archive": _archive_path(date_str),
            "file_count": len(manifest_files),
            "total_bytes": total,
            "manifest_sha256": _sha256_bytes(manifest_bytes),
            "written": False,
        }

        if dry_run:
            return report

        os.makedirs(_BACKUPS, exist_ok=True)
        final = _archive_path(date_str)
        fd, tmp = tempfile.mkstemp(dir=_BACKUPS, suffix=".tar.gz.tmp")
        os.close(fd)
        try:
            with tarfile.open(tmp, "w:gz") as tar:
                info = tarfile.TarInfo(name=MANIFEST_NAME)
                info.size = len(manifest_bytes)
                info.mtime = 0  # deterministic
                tar.addfile(info, fileobj=_BytesReader(manifest_bytes))
                for e in entries:
                    tar.add(e["_src"], arcname=e["name"], recursive=False)
            # Fail-CLOSED POST assertion BEFORE the atomic move: prove every MUST_HAVE member
            # is in the tar and track.db opens. On failure we unlink tmp → no partial archive.
            _assert_archive_complete(tmp)
            shutil.move(tmp, final)  # cross-device-safe atomic replace
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        report["written"] = True
        return report
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _assert_archive_complete(archive_path: str) -> None:
    """Fail-CLOSED: open the just-built tar and prove every MUST_HAVE critical member is
    present, and that track.db extracts + opens via sqlite (integrity_check ok)."""
    with tarfile.open(archive_path, "r:gz") as tar:
        members = {m.name for m in tar.getmembers()}
        missing = [c for c in MUST_HAVE if c not in members]
        if missing:
            raise BackupIncompleteError(
                f"completeness assertion FAILED: archive missing {missing} "
                f"(members={sorted(members)})"
            )
        if "track.db" in MUST_HAVE:
            f = tar.extractfile("track.db")
            if f is None:
                raise BackupIncompleteError("completeness assertion FAILED: track.db unreadable in tar")
            tmpdir = tempfile.mkdtemp(prefix="spa_daily_verify_")
            try:
                dbp = os.path.join(tmpdir, "track.db")
                with open(dbp, "wb") as w:
                    shutil.copyfileobj(f, w)
                con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
                try:
                    row = con.execute("PRAGMA integrity_check").fetchone()
                    if not row or row[0] != "ok":
                        raise BackupIncompleteError(
                            f"completeness assertion FAILED: track.db integrity_check={row}"
                        )
                finally:
                    con.close()
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


class _BytesReader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


def verify(path: str) -> dict:
    """Re-hash every data member in the archive and compare to the embedded manifest."""
    with tarfile.open(path, "r:gz") as tar:
        try:
            mf = tar.getmember(MANIFEST_NAME)
        except KeyError:
            return {"valid": False, "error": "manifest missing"}
        f = tar.extractfile(mf)
        manifest = json.loads(f.read().decode("utf-8"))
        expected = {e["name"]: e for e in manifest["files"]}
        mismatches = []
        for name, meta in expected.items():
            try:
                m = tar.getmember(name)
            except KeyError:
                mismatches.append({"name": name, "reason": "missing in tar"})
                continue
            data = tar.extractfile(m).read()
            if _sha256_bytes(data) != meta["sha256"]:
                mismatches.append({"name": name, "reason": "sha256 mismatch"})
    return {
        "valid": len(mismatches) == 0,
        "archive": path,
        "file_count": len(expected),
        "mismatches": mismatches,
    }


def prune(retention: int = DEFAULT_RETENTION) -> list:
    """Keep only the newest *retention* DATE-stamped daily archives. Returns removed paths."""
    pattern = os.path.join(_BACKUPS, f"{ARCHIVE_PREFIX}????-??-??{ARCHIVE_SUFFIX}")
    archives = sorted(glob.glob(pattern))  # YYYY-MM-DD sorts chronologically
    removed = []
    if len(archives) > retention:
        for old in archives[:-retention]:
            try:
                os.remove(old)
                removed.append(old)
            except OSError:
                pass
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="SPA daily data/*.json snapshot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", metavar="PATH", help="verify an archive and exit")
    ap.add_argument("--retention", type=int, default=DEFAULT_RETENTION)
    args = ap.parse_args()

    if args.verify:
        rep = verify(args.verify)
        print(json.dumps(rep, indent=2))
        return 0 if rep.get("valid") else 1

    rep = snapshot(dry_run=args.dry_run)
    if args.dry_run:
        print(f"[DRY-RUN] would snapshot {rep['file_count']} files "
              f"({rep['total_bytes']} bytes) → {rep['archive']}")
        return 0

    vrep = verify(rep["archive"])
    removed = prune(args.retention)
    size = os.path.getsize(rep["archive"])
    print(f"[OK] daily backup {rep['date']}: {rep['file_count']} files, "
          f"archive {size} bytes → {rep['archive']}")
    print(f"[{'VERIFIED' if vrep['valid'] else 'FAIL'}] integrity: "
          f"{vrep['file_count']} members re-hashed, "
          f"{len(vrep.get('mismatches', []))} mismatches")
    if removed:
        print(f"[PRUNE] removed {len(removed)} archive(s) beyond retention={args.retention}")
    return 0 if vrep["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
