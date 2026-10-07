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
from typing import Callable, List, Optional

# Reuse the canonical atomic JSON writer (tmp + os.replace, fail-closed on junk paths).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spa_core.dr import archive_class, archive_names  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BACKUP_DIR = REPO / "data" / "backups"
DEFAULT_STATUS_PATH = REPO / "data" / "dr_offsite_status.json"
# ADR-611: one status file PER CLASS. The canonical one (read by resilience_status,
# company_truth, mission_control, cartographer) describes the FULL archive — the only class
# that carries the ledgers; a CRITICAL-class run never overwrites it.
# A run that never declared its class must not touch ANY class's status: writing a refusal into
# the canonical FULL status would let a misconfigured caller overwrite a real proof (review P2).
REFUSAL_PATH = REPO / "data" / "dr_offsite_refusal.json"
STATUS_PATH_BY_CLASS = {
    archive_class.CLASS_FULL: DEFAULT_STATUS_PATH,
    archive_class.CLASS_CRITICAL: REPO / "data" / "dr_offsite_status_critical.json",
}
# Remote-upload honesty (ADR-611 §3): a file in the local iCloud Drive folder is NOT proof that
# Apple's servers hold it — macOS exposes no reliable upload receipt to this process (measured
# 2026-10-07: Spotlight kMDItemIsUploaded = null). So a real-remote copy reports NOT_MEASURED,
# never UPLOADED; the stand-in reports SAME_HOST.
UPLOAD_NOT_MEASURED = "NOT_MEASURED"
UPLOAD_SAME_HOST = "SAME_HOST"
STANDIN_DEST = Path(os.path.expanduser("~/spa_offsite_backups"))
# RM-TRUTH-01 / ADR-580 C10: the Owner-controlled destination that ALREADY leaves the Mac.
# iCloud Drive is signed in and syncing on the production host (the track mirror
# `persistence/backup.py` and the ADR-527 memory backup have used it since MP-109 /
# 2026-10-01). Used only when its parent exists; otherwise the stand-in (SAME_HOST).
ICLOUD_PARENT = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
ICLOUD_DEST = ICLOUD_PARENT / "SPA_backups" / "dr_offsite"
DEST_PROBE_TIMEOUT_S = 20.0


def resolve_dest(explicit: Optional[Path] = None) -> Path:
    """--dest → $SPA_OFFSITE_DEST → iCloud Drive (if signed in) → local stand-in."""
    if explicit is not None:
        return Path(os.path.expanduser(str(explicit)))
    env = os.environ.get("SPA_OFFSITE_DEST", "").strip()
    if env:
        return Path(os.path.expanduser(env))
    if ICLOUD_PARENT.is_dir():
        return ICLOUD_DEST
    return STANDIN_DEST

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
    """Newest spa_state_*.tar.gz ACROSS BOTH CLASSES — by the INSTANT the name encodes.

    ⚠️ NOT the offsite selector any more (ADR-611): "newest" across classes shipped the
    29-member CRITICAL archive instead of the FULL one. ``run`` selects through
    ``archive_class.select(backup_dir, cls)``. Kept for the cross-producer ordering tests.

    Two producers write this directory under two naming schemes; a lexical sort put every
    `spa_state_<YYYY-MM-DD>.tar.gz` below every `spa_state_<ts>Z.tar.gz` whatever its date,
    so the broad daily snapshot could never be selected for the offsite copy no matter how
    fresh it was. See `spa_core/dr/archive_names.py`.
    """
    if not backup_dir.is_dir():
        return None
    archives = archive_names.newest_first(backup_dir.glob(ARCHIVE_GLOB))
    return archives[0] if archives else None


def _prune_offsite(dest_dir: Path, keep: int) -> int:
    """Keep the *keep* newest offsite copies OF EACH series. Returns count kept.

    Per-series, so introducing a second producer does not silently halve the depth of the
    first one's history — and so no series can be swept wholesale by the other's volume.
    """
    archives = list(dest_dir.glob(ARCHIVE_GLOB))
    for series in (archive_names.SERIES_DR, archive_names.SERIES_DAILY,
                   archive_names.SERIES_UNKNOWN):
        if series == archive_names.SERIES_UNKNOWN:
            continue  # unparseable names are never auto-deleted (fail-CLOSED)
        _kept, doomed = archive_names.select_for_retention(archives, series=series, keep=keep)
        for old in doomed:
            try:
                old.unlink()
            except OSError:
                pass
    return len(list(dest_dir.glob(ARCHIVE_GLOB)))


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
    archive_class_: Optional[str] = None,
    class_proof: Optional[dict] = None,
    complete: Optional[bool] = None,
    completeness: Optional[dict] = None,
) -> None:
    atomic_save(
        {
            "schema": "spa_dr_offsite_status/v2",
            "last_offsite_ts": _utc_now(),
            "archive_class": archive_class_,
            "class_proof": class_proof,
            "archive_name": archive_name,
            "sha256": sha256,
            "dest": dest,
            "verified": verified,
            # FULL class: did the archive pass full_archive_verify? None = not applicable
            # (CRITICAL class) or not reached — never a default True.
            "complete": complete,
            "completeness": completeness,
            "n_offsite_kept": n_offsite_kept,
            "is_real_remote": is_real_remote,
            "remote_upload": UPLOAD_NOT_MEASURED if is_real_remote else UPLOAD_SAME_HOST,
            "error": error,
        },
        str(status_path),
    )


def _completeness_summary(rep: dict) -> dict:
    return {k: rep.get(k) for k in ("ok", "findings", "required", "sqlite_checked",
                                     "replay_snapshots_referenced", "manifest_files", "schema")}


def run(
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    dest_dir: Optional[Path] = None,
    status_path: Optional[Path] = None,
    keep: int = DEFAULT_KEEP,
    archive_class_: Optional[str] = None,
    verify_full: Optional[Callable[[Path], dict]] = None,
    refusal_path: Optional[Path] = None,
) -> int:
    """Copy the newest archive OF THE DECLARED CLASS offsite, sha-verify, prune, emit status.

    ``archive_class_`` is REQUIRED (ADR-611): no class ⇒ refusal, never "whatever is newest".
    FULL class: the source is first checked by ``full_archive_verify`` (``verify_full``
    injectable for tests); an incomplete FULL archive is still copied — a partial backup off
    the Mac beats none — but the status says ``complete: false`` and the exit is non-zero.

    Returns process exit code: 0 = verified (and, for FULL, complete) copy; non-zero = any
    failure (fail-CLOSED).
    """
    dest_dir = resolve_dest(dest_dir)
    is_real_remote = dest_dir.resolve() != STANDIN_DEST.resolve()
    if archive_class_ not in archive_class.CLASSES:
        print(f"[FAIL] archive class not declared/unknown: {archive_class_!r} "
              f"(expected one of {archive_class.CLASSES}) — refusing to guess.")
        # recorded, but NEVER into a class status file (no class ⇒ no status it may speak for)
        _write_status(
            refusal_path or REFUSAL_PATH, verified=False, archive_name=None, sha256=None,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            error="archive_class_not_declared", archive_class_=archive_class_,
        )
        return 2
    if status_path is None:
        status_path = STATUS_PATH_BY_CLASS[archive_class_]

    print("==============================================")
    print(" SPA DR offsite copy")
    print("==============================================")
    print(f"  source: {backup_dir}")
    print(f"  dest:   {dest_dir}  (real_remote={is_real_remote})")
    print(f"  class:  {archive_class_}")
    cls = archive_class_

    # 1) Newest archive OF THIS CLASS, class proven by name + manifest (fail-CLOSED).
    src, proof = archive_class.select(backup_dir, cls)
    if src is None or not src.is_file():
        err = "no_source_archive" if str(proof.get("reason", "")).startswith("no_") \
            else f"class_unproven:{proof.get('reason')}"
        print(f"[FAIL] no provable {cls} archive in {backup_dir}: {proof.get('reason')}")
        _write_status(
            status_path, verified=False, archive_name=proof.get("archive"), sha256=None,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            error=err, archive_class_=cls, class_proof=proof,
        )
        return 1
    print(f"[OK] newest {cls} archive: {src.name} (schema {proof.get('schema')})")

    extra = dict(archive_class_=cls, class_proof=proof, complete=None, completeness=None)

    # 2) Source sha256 FIRST — the bytes the completeness verdict and the copy are both about.
    try:
        src_sha = sha256_file(src)
    except OSError as e:
        print(f"[FAIL] cannot read source: {e}")
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=None,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            **extra, error=f"src_read_error:{e}",
        )
        return 1
    print(f"[OK] source sha256: {src_sha}")

    # 2a) FULL: completeness of THOSE bytes. Any verifier crash is a recorded incomplete verdict,
    #     never an exception that leaves the previous (proven) status file standing.
    complete: Optional[bool] = None
    completeness: Optional[dict] = None
    if cls == archive_class.CLASS_FULL:
        from spa_core.dr import full_archive_verify  # noqa: E402
        try:
            rep = (verify_full or full_archive_verify.verify_archive)(src)
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED, recorded
            rep = {"ok": False, "findings": [f"verifier_error:{type(exc).__name__}:{str(exc)[:160]}"]}
        complete = bool(rep.get("ok"))
        completeness = _completeness_summary(rep)
        print(f"[{'OK' if complete else 'FAIL'}] full-archive completeness: "
              f"{'complete' if complete else rep.get('findings')}")
        # 2b') the verdict is about src_sha only if the file did not change underneath it;
        #      the copy below is then compared against src_sha, closing the window to the end.
        try:
            again = sha256_file(src)
        except OSError as e:
            again = f"unreadable:{e}"
        if again != src_sha:
            print("[FAIL] source archive changed while it was being verified — refusing.")
            _write_status(
                status_path, verified=False, archive_name=src.name, sha256=src_sha,
                dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
                archive_class_=cls, class_proof=proof, complete=False,
                completeness=dict(completeness, findings=list(completeness.get("findings") or [])
                                  + ["source_changed_during_verify"], ok=False),
                error="source_changed_during_verify",
            )
            return 1
    extra = dict(archive_class_=cls, class_proof=proof, complete=complete,
                 completeness=completeness)

    # 2b) A stalled sync filesystem (iCloud) does not FAIL — it blocks forever (measured
    #     2026-08-04/05, persistence/backup.py). Probe the destination with a hard deadline
    #     first; no answer ⇒ refuse, recorded (fail-CLOSED, inv. #2), never a hang.
    from spa_core.persistence.backup import _probe_backup_root  # noqa: E402
    stall = _probe_backup_root(dest_dir, DEST_PROBE_TIMEOUT_S)
    if stall is not None:
        print(f"[FAIL] destination not answering: {stall}")
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=src_sha,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            **extra, error=f"dest_unresponsive:{stall}",
        )
        return 1

    # 3) Atomic copy to offsite/secondary destination.
    dest_file = dest_dir / src.name
    try:
        _atomic_copy(src, dest_file)
    except OSError as e:
        print(f"[FAIL] copy failed → {dest_file}: {e}")
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=src_sha,
            dest=str(dest_dir), n_offsite_kept=0, is_real_remote=is_real_remote,
            **extra, error=f"copy_error:{e}",
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
        n_kept = len(list(dest_dir.glob(ARCHIVE_GLOB)))  # a FAILED copy never prunes good ones
        _write_status(
            status_path, verified=False, archive_name=src.name, sha256=src_sha,
            dest=str(dest_dir), n_offsite_kept=n_kept, is_real_remote=is_real_remote,
            **extra, error="sha256_mismatch",
        )
        return 1

    # 5) Prune old offsite copies (keep last N) — but an INCOMPLETE FULL copy never prunes: a run
    #    of incomplete copies must not evict the last complete one (review P2). The next complete
    #    copy prunes, and it is itself the newest, so a complete copy always survives.
    if complete is False:
        n_kept = len(list(dest_dir.glob(ARCHIVE_GLOB)))
    else:
        n_kept = _prune_offsite(dest_dir, keep)

    _write_status(
        status_path, verified=True, archive_name=src.name, sha256=src_sha,
        dest=str(dest_dir), n_offsite_kept=n_kept, is_real_remote=is_real_remote,
        error=None, **extra,
    )
    print("")
    print(f"[VERIFIED] offsite copy sha256 matches source — backup INTACT ({n_kept} kept).")
    if is_real_remote:
        print("NOTE: upload to the remote's servers is NOT MEASURED — local presence in a sync "
              "folder is not proof of upload.")
    if complete is False:
        print("[FAIL] the FULL archive copied is INCOMPLETE — see status 'completeness'.")
        return 1
    if not is_real_remote:
        print(f"NOTE: dest '{dest_dir}' is the LOCAL STAND-IN. TRUE offsite is owner-flagged")
        print("      infra: set SPA_OFFSITE_DEST to a mounted bucket/second-disk/rsync target.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="DR offsite copy + sha256 verify + status surface.")
    ap.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    ap.add_argument("--dest", default=None, help="offsite dest dir (overrides SPA_OFFSITE_DEST)")
    ap.add_argument("--class", dest="archive_class", required=True,
                    choices=archive_class.CLASSES,
                    help="which archive class to copy (ADR-611) — REQUIRED, never inferred")
    ap.add_argument("--status", default=None,
                    help="status JSON (default: per class, see STATUS_PATH_BY_CLASS)")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = ap.parse_args(argv)
    return run(
        backup_dir=Path(args.backup_dir),
        dest_dir=Path(args.dest) if args.dest else None,
        status_path=Path(args.status) if args.status else None,
        keep=args.keep,
        archive_class_=args.archive_class,
    )


if __name__ == "__main__":
    raise SystemExit(main())
