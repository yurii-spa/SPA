"""
spa_core/backtesting/tier1/dr_backup.py — Disaster-recovery state snapshot + restore-verify.

PARALLEL MODEL — this module READS the canonical state files and writes ONLY into its own
backup directory (data/backups/). It never modifies a live state file, never imports the
tournament/RiskPolicy/execution code, and performs no network I/O. It is a pure-stdlib,
deterministic DR primitive: prove the critical state can be backed up and restored INTACT.

WHY: SPA runs on a single Mac mini (production host). A single host is a single point of
failure (SPOF). Institutional DR readiness requires demonstrating that the critical state
(paper-trading status, equity curve, positions, go-live gate, trade ring-buffer, audit
chain, Tier-1 verdict/packages, and the real DeFiLlama APY cache) can be:

  1. snapshot()       — captured into ONE integrity-checked, gzipped tar with a manifest;
  2. verify_backup()  — re-hashed and proven bit-for-bit against its embedded manifest;
  3. restore()        — extracted to a SEPARATE directory, byte-identical to the source.

HONEST SCOPE: a single-host backup is NECESSARY BUT NOT SUFFICIENT for high availability.
True HA needs a SECOND host (failover) and an OFFSITE copy of these archives — that is
infrastructure, not code. This module proves the *backup is restorable*; it does not, by
itself, eliminate the SPOF. The offsite copy + a standby host are the manual follow-ups.

Deterministic: with a fixed `ts` the archive path and contents are reproducible; sha256 of
identical bytes is identical run-to-run. Atomic: the tar is built in a temp file and moved
into place only after it is fully written (os.replace within the same dir = atomic rename).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_write_via_tmp

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_BACKUPS = _DATA / "backups"

# Manifest member name stored INSIDE the tar — the integrity record verify_backup() trusts.
MANIFEST_NAME = "backup_manifest.json"
ARCHIVE_PREFIX = "spa_state_"
ARCHIVE_SUFFIX = ".tar.gz"

# CRITICAL state files, as POSIX-relative paths under data/. Only those that exist are
# included; a missing source is recorded (not fatal) so DR degrades gracefully.
CRITICAL_FILES = [
    "paper_trading_status.json",
    "equity_curve_daily.json",
    "current_positions.json",
    "golive_status.json",
    "trades.json",
    "gap_monitor.json",
    "audit_chain.jsonl",
    "tier1_verdict.json",
    "tier1_packages.json",
    "bee/defillama_apy_history.json",
]

_CHUNK = 1 << 20  # 1 MiB hashing chunk


def _data_dir() -> Path:
    """Resolved each call so tests can monkeypatch _DATA hermetically."""
    return _DATA


def _backup_dir() -> Path:
    return _BACKUPS


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_ts() -> str:
    """Compact UTC timestamp, filesystem-safe and lexically sortable."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_path(ts: str) -> Path:
    return _backup_dir() / f"{ARCHIVE_PREFIX}{ts}{ARCHIVE_SUFFIX}"


def snapshot(write: bool = True, ts: Optional[str] = None) -> dict:
    """Create a timestamped, integrity-checked gzip-tar backup of the critical state files.

    Args:
        write: if False, build the manifest but do NOT write the archive (dry-run).
        ts:    timestamp string injected for deterministic tests; UTC now in production.

    Returns a report: {ts, archive, files:[{name,sha256,size}], missing:[...], total_bytes,
    file_count, manifest_sha256}. The MANIFEST (same {files,missing,...}) is also stored
    inside the tar as `backup_manifest.json` so verify_backup() is self-contained.
    """
    data = _data_dir()
    ts = ts or _utc_ts()

    entries: List[Dict] = []
    missing: List[str] = []
    total = 0
    for rel in CRITICAL_FILES:
        src = data / rel
        if src.exists() and src.is_file():
            size = src.stat().st_size
            entries.append({"name": rel, "sha256": _sha256_file(src), "size": size})
            total += size
        else:
            missing.append(rel)

    manifest = {
        "schema": "spa_dr_backup/v1",
        "llm_forbidden": True,
        "ts": ts,
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "file_count": len(entries),
        "total_bytes": total,
        "files": entries,
        "missing": missing,
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    report = {
        "ts": ts,
        "archive": str(_archive_path(ts)),
        "files": entries,
        "missing": missing,
        "total_bytes": total,
        "file_count": len(entries),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "written": False,
    }
    if not write:
        return report

    backups = _backup_dir()
    backups.mkdir(parents=True, exist_ok=True)
    # Atomic: build into a temp tar in the SAME dir, then rename into the final name.
    with atomic_write_via_tmp(str(_archive_path(ts))) as tmp:
        with tarfile.open(str(tmp), "w:gz") as tar:
            # Manifest first so it is cheap to read back.
            info = tarfile.TarInfo(name=MANIFEST_NAME)
            info.size = len(manifest_bytes)
            info.mtime = 0  # deterministic
            tar.addfile(info, fileobj=_BytesReader(manifest_bytes))
            for e in entries:
                src = data / e["name"]
                # Store under the same relative path; arcname keeps the bee/ subdir.
                tar.add(str(src), arcname=e["name"], recursive=False)
    report["written"] = True
    return report


class _BytesReader:
    """Minimal file-like reader so tarfile.addfile can stream in-memory bytes (stdlib has
    io.BytesIO; this avoids the extra import and is fully deterministic)."""

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


def _read_manifest_from_tar(tar: tarfile.TarFile) -> Optional[dict]:
    try:
        member = tar.getmember(MANIFEST_NAME)
    except KeyError:
        return None
    f = tar.extractfile(member)
    if f is None:
        return None
    return json.loads(f.read().decode("utf-8"))


def verify_backup(path) -> dict:
    """Open the tar, re-hash every data member, and compare to the embedded manifest.

    This is the "the backup is restorable AND intact" proof. Returns:
      {valid, archive, file_count, files:[{name,ok,expected,actual,size,size_ok}],
       mismatches:[name...], missing_members:[...], extra_members:[...], error?}.
    valid is True only if a manifest exists, every manifested file is present, and every
    sha256 + size matches.
    """
    path = Path(path)
    out = {
        "archive": str(path),
        "valid": False,
        "file_count": 0,
        "files": [],
        "mismatches": [],
        "missing_members": [],
        "extra_members": [],
    }
    if not path.exists():
        out["error"] = "archive_not_found"
        return out
    try:
        with tarfile.open(str(path), "r:gz") as tar:
            manifest = _read_manifest_from_tar(tar)
            if manifest is None:
                out["error"] = "manifest_missing"
                return out
            expected = {e["name"]: e for e in manifest.get("files", [])}
            members = {m.name for m in tar.getmembers()}
            # Members present in tar that aren't the manifest and aren't expected.
            out["extra_members"] = sorted(
                m for m in members if m != MANIFEST_NAME and m not in expected
            )
            files_report = []
            all_ok = True
            for name, e in expected.items():
                if name not in members:
                    out["missing_members"].append(name)
                    files_report.append({"name": name, "ok": False, "reason": "absent_from_tar"})
                    all_ok = False
                    continue
                member = tar.getmember(name)
                f = tar.extractfile(member)
                actual = _sha256_bytes(f.read()) if f is not None else None
                size_ok = member.size == e.get("size")
                ok = (actual == e.get("sha256")) and size_ok
                if not ok:
                    out["mismatches"].append(name)
                    all_ok = False
                files_report.append({
                    "name": name,
                    "ok": ok,
                    "expected": e.get("sha256"),
                    "actual": actual,
                    "size": member.size,
                    "size_ok": size_ok,
                })
            out["files"] = files_report
            out["file_count"] = len(expected)
            out["valid"] = all_ok and not out["missing_members"]
    except (tarfile.TarError, OSError, ValueError) as exc:
        out["error"] = f"open_failed: {exc.__class__.__name__}: {exc}"
        out["valid"] = False
    return out


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def restore(path, dest_dir) -> dict:
    """Extract a backup to `dest_dir` (NEVER the live data/ by default — restore to a
    separate dir for verification). Skips the manifest member. Path-traversal hardened.

    Returns {restored:[rel...], ok, dest, skipped:[...], error?}. ok is True if every
    manifested data file was extracted.
    """
    path = Path(path)
    dest = Path(dest_dir)
    out = {"archive": str(path), "dest": str(dest), "restored": [], "skipped": [], "ok": False}
    if not path.exists():
        out["error"] = "archive_not_found"
        return out
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(str(path), "r:gz") as tar:
            manifest = _read_manifest_from_tar(tar)
            expected = {e["name"] for e in (manifest.get("files", []) if manifest else [])}
            for member in tar.getmembers():
                if member.name == MANIFEST_NAME:
                    continue
                target = dest / member.name
                if not _is_within(dest, target):
                    out["skipped"].append(member.name)  # path-traversal guard
                    continue
                f = tar.extractfile(member)
                if f is None:
                    out["skipped"].append(member.name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                # Atomic per-file write into dest.
                with atomic_write_via_tmp(str(target)) as tmp:
                    with open(str(tmp), "wb") as w:
                        shutil.copyfileobj(f, w)
                out["restored"].append(member.name)
            out["ok"] = expected.issubset(set(out["restored"])) if expected else bool(out["restored"])
    except (tarfile.TarError, OSError, ValueError) as exc:
        out["error"] = f"restore_failed: {exc.__class__.__name__}: {exc}"
        out["ok"] = False
    return out


def list_backups() -> List[Path]:
    """All spa_state_*.tar.gz archives, newest first (lexical sort works: ts is sortable)."""
    backups = _backup_dir()
    if not backups.exists():
        return []
    archives = [p for p in backups.iterdir()
                if p.is_file() and p.name.startswith(ARCHIVE_PREFIX) and p.name.endswith(ARCHIVE_SUFFIX)]
    return sorted(archives, key=lambda p: p.name, reverse=True)


def prune(keep: int = 14) -> dict:
    """Ring-buffer: keep the newest `keep` archives, delete older ones.

    Returns {kept:[name...], deleted:[name...], keep}."""
    if keep < 0:
        keep = 0
    archives = list_backups()  # newest first
    kept = archives[:keep]
    doomed = archives[keep:]
    deleted = []
    for p in doomed:
        try:
            p.unlink()
            deleted.append(p.name)
        except OSError:
            pass
    return {"keep": keep, "kept": [p.name for p in kept], "deleted": deleted}


def _age_seconds(ts: str, now: Optional[datetime.datetime] = None) -> Optional[float]:
    try:
        dt = datetime.datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - dt).total_seconds()


def latest_status(now: Optional[datetime.datetime] = None) -> dict:
    """Newest backup age + validity — the DR-readiness summary for reporting.

    Returns {has_backup, archive?, ts?, age_seconds?, age_hours?, valid?, file_count?,
    backup_count, stale?, note}. `stale` flags a newest backup older than 26h (daily
    cadence + grace), i.e. the daily DR job likely missed a run.
    """
    archives = list_backups()
    out = {"has_backup": bool(archives), "backup_count": len(archives)}
    if not archives:
        out["note"] = (
            "NO DR BACKUP present. Run snapshot() / schedule com.spa.dr_backup daily. "
            "Single-host backup is necessary-but-not-sufficient for HA."
        )
        return out
    newest = archives[0]
    out["archive"] = str(newest)
    # Recover ts from filename: spa_state_<ts>.tar.gz
    ts = newest.name[len(ARCHIVE_PREFIX):-len(ARCHIVE_SUFFIX)]
    out["ts"] = ts
    age = _age_seconds(ts, now=now)
    if age is not None:
        out["age_seconds"] = round(age, 1)
        out["age_hours"] = round(age / 3600.0, 2)
        out["stale"] = age > 26 * 3600
    ver = verify_backup(newest)
    out["valid"] = ver["valid"]
    out["file_count"] = ver.get("file_count", 0)
    out["note"] = (
        "DR backup present and VERIFIED intact." if ver["valid"]
        else "DR backup present but FAILED verification — investigate."
    ) + " Offsite copy + standby host are manual HA follow-ups (single host = SPOF)."
    return out


if __name__ == "__main__":
    snap = snapshot()
    ver = verify_backup(snap["archive"])
    print(json.dumps({
        "snapshot": {
            "archive": snap["archive"],
            "file_count": snap["file_count"],
            "total_bytes": snap["total_bytes"],
            "missing": snap["missing"],
            "written": snap["written"],
        },
        "verify": {
            "valid": ver["valid"],
            "file_count": ver["file_count"],
            "mismatches": ver["mismatches"],
            "missing_members": ver["missing_members"],
        },
        "dr_readiness": latest_status(),
    }, indent=2))
