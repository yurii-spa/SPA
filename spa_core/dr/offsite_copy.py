"""
spa_core/dr/offsite_copy.py — DR offsite copy + sha256 verify, with a status surface.

Resilience Plane (R6) — make the offsite-backup mechanism PROVABLY EXERCISED.

WHY THIS EXISTS
---------------
scripts/daily_backup.py / dr_backup.py produce data/backups/spa_state_*.tar.gz on the
SAME host (the Mac mini). A single-host backup is necessary-but-not-sufficient for HA:
if the host dies, the backups die with it. This module copies the NEWEST archive to a
SEPARATE destination and verifies the copy is bit-for-bit identical via sha256 — and then
emits an auditable status JSON so the mechanism is provably exercised (not dormant).

HONEST SCOPE / OWNER-FLAGGED
----------------------------
With no real offsite target configured, the destination is a LOCAL stand-in dir
($HOME/spa_offsite_backups by default). That proves the MECHANISM (newest-archive
selection + atomic transfer + integrity verify + prune + status). A TRUE offsite target
(cloud bucket / remote host / mounted second disk) is INFRASTRUCTURE, owner-flagged.

  ┌─ THE ONE-LINE SWITCH TO A REAL REMOTE (owner decision) ────────────────────────┐
  │  export SPA_OFFSITE_DEST=/Volumes/Backup/spa     # mounted second disk / NAS    │
  │  # or point it at an rsync/sshfs/s3-mount target; mechanism stays identical.    │
  │  When SPA_OFFSITE_DEST is set to anything other than the local stand-in,        │
  │  is_real_remote flips to true in the status JSON.                               │
  └────────────────────────────────────────────────────────────────────────────────┘

DESIGN
------
- stdlib only, deterministic, fail-CLOSED.
- Atomic copy: write to a tmp file in the dest dir, fsync, then os.replace → the dest
  archive never exists in a partial state.
- Verify: sha256(source) == sha256(dest) AFTER copy; on mismatch the bad dest is removed,
  verified:false is written, and exit is non-zero. Never a silent success.
- Status JSON written atomically via spa_core.utils.atomic.atomic_save.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Reuse the canonical atomic JSON writer (tmp + os.replace, fail-closed on junk paths).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spa_core.utils.atomic import atomic_save  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BACKUP_DIR = REPO / "data" / "backups"
DEFAULT_STATUS_PATH = REPO / "data" / "dr_offsite_status.json"
STANDIN_DEST = Path(os.path.expanduser("~/spa_offsite_backups"))

ARCHIVE_GLOB = "spa_state_*.tar.gz"
DEFAULT_KEEP = 14  # keep ~14 newest offsite copies


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming sha256 of a file (constant memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def newest_archive(backup_dir: Path) -> Optional[Path]:
    """Newest spa_state_*.tar.gz (lexical sort: the embedded date/ts is sortable)."""
    if not backup_dir.is_dir():
        return None
    archives = sorted(backup_dir.glob(ARCHIVE_GLOB))
    return archives[-1] if archives else None


def _prune_offsite(dest_dir: Path, keep: int) -> int:
    """Keep only the *keep* newest offsite archives. Returns count kept."""
    archives = sorted(dest_dir.glob(ARCHIVE_GLOB))
    if keep > 0 and len(archives) > keep:
        for old in archives[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
        archives = sorted(dest_dir.glob(ARCHIVE_GLOB))
    return len(archives)


def _atomic_copy(src: Path, dest: Path) -> None:
    """Copy src→dest atomically: tmp in dest dir, fsync, os.replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".offsite.tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            for block in iter(lambda: inp.read(1 << 20), b""):
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_status(
    status_path: Path,
    *,
    verified: bool,
    archive_name: Optional[str],
    sha256: Optional[str],
    dest: str,
    n_offsite_kept: int,
    is_real_remote: bool,
    error: Optional[str] = None,
) -> None:
    atomic_save(
        {
            "last_offsite_ts": _utc_now(),
            "archive_name": archive_name,
            "sha256": sha256,
            "dest": dest,
            "verified": verified,
            "n_offsite_kept": n_offsite_kept,
            "is_real_remote": is_real_remote,
            "error": error,
        },
        str(status_path),
    )


def run(
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    dest_dir: Optional[Path] = None,
    status_path: Path = DEFAULT_STATUS_PATH,
    keep: int = DEFAULT_KEEP,
) -> int:
    """Copy newest archive offsite, sha-verify, prune, emit status JSON.

    Returns process exit code: 0 = verified copy, non-zero = any failure (fail-CLOSED).
    """
    if dest_dir is None:
        env = os.environ.get("SPA_OFFSITE_DEST", "").strip()
        dest_dir = Path(env) if env else STANDIN_DEST
    dest_dir = Path(os.path.expanduser(str(dest_dir)))

    # is_real_remote: false iff dest resolves to the local stand-in dir.
    is_real_remote = dest_dir.resolve() != STANDIN_DEST.resolve()

    print("==============================================")
    print(" SPA DR offsite copy")
    print("==============================================")
    print(f"  source: {backup_dir}")
    print(f"  dest:   {dest_dir}  (real_remote={is_real_remote})")

    # 1) Newest archive must exist (fail-CLOSED otherwise).
    src = newest_archive(backup_dir)
    if src is None or not src.is_file():
        print(f"[FAIL] no {ARCHIVE_GLOB} archive in {backup_dir} — nothing to copy.")
        _write_status(
            status_path, verified=False, archive_name=None, sha256=None,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            error="no_source_archive",
        )
        return 1
    print(f"[OK] newest archive: {src.name}")

    # 2) Source sha256.
    try:
        src_sha = sha256_file(src)
    except OSError as e:
        print(f"[FAIL] cannot read source: {e}")
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=None,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            error=f"src_read_error:{e}",
        )
        return 1
    print(f"[OK] source sha256: {src_sha}")

    # 3) Atomic copy to offsite/secondary destination.
    dest_file = dest_dir / src.name
    try:
        _atomic_copy(src, dest_file)
    except OSError as e:
        print(f"[FAIL] copy failed → {dest_file}: {e}")
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=src_sha,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            error=f"copy_error:{e}",
        )
        return 1
    print(f"[OK] copied → {dest_file}")

    # 4) Verify dest sha256 == source (integrity proof). Fail-CLOSED on mismatch.
    dst_sha = sha256_file(dest_file)
    print(f"[OK] dest   sha256: {dst_sha}")
    if dst_sha != src_sha:
        print("[FAIL] sha256 MISMATCH — offsite copy is CORRUPT. Removing.")
        try:
            dest_file.unlink()
        except OSError:
            pass
        n_kept = _prune_offsite(dest_dir, keep)
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=src_sha,
            dest=str(dest_dir), n_offsite_kept=n_kept, is_real_remote=is_real_remote,
            error="sha256_mismatch",
        )
        return 1

    # 5) Prune old offsite copies (keep last N).
    n_kept = _prune_offsite(dest_dir, keep)

    _write_status(
        status_path, verified=True, archive_name=src.name, sha256=src_sha,
        dest=str(dest_dir), n_offsite_kept=n_kept, is_real_remote=is_real_remote,
        error=None,
    )
    print("")
    print(f"[VERIFIED] offsite copy sha256 matches source — backup INTACT ({n_kept} kept).")
    if not is_real_remote:
        print(f"NOTE: dest '{dest_dir}' is the LOCAL STAND-IN. TRUE offsite is owner-flagged")
        print("      infra: set SPA_OFFSITE_DEST to a mounted bucket/second-disk/rsync target.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="DR offsite copy + sha256 verify + status surface.")
    ap.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    ap.add_argument("--dest", default=None, help="offsite dest dir (overrides SPA_OFFSITE_DEST)")
    ap.add_argument("--status", default=str(DEFAULT_STATUS_PATH))
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = ap.parse_args(argv)
    return run(
        backup_dir=Path(args.backup_dir),
        dest_dir=Path(args.dest) if args.dest else None,
        status_path=Path(args.status),
        keep=args.keep,
    )


if __name__ == "__main__":
    raise SystemExit(main())
