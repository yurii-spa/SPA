#!/usr/bin/env python3
"""Daily off-site backup of the paper-trading track (MP-109, SPA-V415).

Copies the SQLite mirror (``track.db``) plus the key JSON/markdown files of the
track record into a dated folder ``<backup_dir>/YYYY-MM-DD/`` — by default on
iCloud Drive, i.e. *off the machine* — so losing the laptop/disk no longer
means losing the track (DR minimum).

Behaviour
=========
* Sources are looked up in ``data_dir`` first, then in its parent (the repo
  root — where ``KANBAN.json`` / ``SPA_sprint_log.md`` live). Missing files are
  skipped, never fatal.
* Every copy is atomic: bytes go to a tempfile inside the destination folder,
  then ``os.replace`` (same-filesystem rename).
* A ``manifest.json`` (file list + sha256 + size + timestamp) is written into
  the dated folder, also atomically.
* Rotation keeps the most recent 14 dated (``YYYY-MM-DD``) folders. Deletion
  candidates must (a) match the date pattern, (b) be directories, (c) resolve
  to a path strictly inside ``backup_dir`` — nothing outside the backup root
  can ever be removed.
* ``backup_dir`` resolution: explicit argument → ``$SPA_BACKUP_DIR`` →
  ``~/Library/Mobile Documents/com~apple~CloudDocs/SPA_backups`` (iCloud Drive,
  if the iCloud parent exists) → ``~/SPA_backups`` fallback.
* Fail-safe: ``run_backup()`` never raises — errors are logged as WARNING and
  returned as ``{"status": "error", ...}``.

CLI: ``python3 -m spa_core.persistence.backup [--data-dir D] [--backup-dir B] [--verbose]``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.track_backup")

# Files that constitute the track record (copied when present).
TRACK_FILES = (
    "track.db",
    "trades.json",
    "equity_curve_daily.json",
    "paper_trading_status.json",
    "KANBAN.json",
    "SPA_sprint_log.md",
)

MANIFEST_FILENAME = "manifest.json"
KEEP_LAST = 14  # dated folders retained by rotation
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_ICLOUD_PARENT = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def default_backup_dir() -> Path:
    """Resolve the backup root: $SPA_BACKUP_DIR → iCloud Drive → ~/SPA_backups."""
    env = os.environ.get("SPA_BACKUP_DIR")
    if env:
        return Path(env).expanduser()
    if _ICLOUD_PARENT.exists():
        return _ICLOUD_PARENT / "SPA_backups"
    return Path.home() / "SPA_backups"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_copy(src: Path, dest: Path) -> None:
    """Copy ``src`` → ``dest`` atomically (tempfile in dest dir + os.replace)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(dest.parent), prefix=f".{dest.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_name, dest)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _atomic_write_json(path: Path, obj) -> None:
    """Write JSON atomically via centralized atomic_save (MP-1451)."""
    atomic_save(obj, str(path))


def _rotate(backup_dir: Path, keep_last: int = KEEP_LAST) -> list[str]:
    """Delete dated folders beyond the newest ``keep_last``.

    Strictly scoped: only direct children of ``backup_dir`` whose name matches
    ``YYYY-MM-DD``, that are real directories, and that resolve to a path
    inside ``backup_dir``, are ever removed. Returns the deleted folder names.
    """
    deleted: list[str] = []
    root = backup_dir.resolve()
    dated = sorted(
        p for p in backup_dir.iterdir()
        if p.is_dir() and not p.is_symlink() and _DATE_DIR_RE.match(p.name)
    )
    for victim in dated[:-keep_last] if len(dated) > keep_last else []:
        resolved = victim.resolve()
        if resolved.parent != root:  # paranoia: never reach outside backup_dir
            log.warning("rotation skipped suspicious path %s", victim)
            continue
        shutil.rmtree(resolved)
        deleted.append(victim.name)
    return deleted


def run_backup(
    data_dir: str | os.PathLike,
    backup_dir: str | os.PathLike | None = None,
    *,
    now: datetime | None = None,
    keep_last: int = KEEP_LAST,
) -> dict:
    """Back up the track into ``<backup_dir>/YYYY-MM-DD/`` + rotate. Never raises."""
    result: dict = {
        "status": "ok",
        "backup_dir": None,
        "dest": None,
        "date": None,
        "files": [],
        "skipped": [],
        "rotated_out": [],
        "errors": [],
    }
    try:
        ddir = Path(os.fspath(data_dir))
        broot = Path(os.fspath(backup_dir)) if backup_dir is not None else default_backup_dir()
        now_dt = now or datetime.now(timezone.utc)
        date = now_dt.strftime("%Y-%m-%d")
        dest = broot / date
        dest.mkdir(parents=True, exist_ok=True)
        result.update(backup_dir=str(broot), dest=str(dest), date=date)

        manifest_files: list[dict] = []
        for name in TRACK_FILES:
            # data_dir first, then repo root (KANBAN.json / SPA_sprint_log.md).
            src = ddir / name
            if not src.exists():
                src = ddir.parent / name
            if not src.exists() or not src.is_file():
                result["skipped"].append(name)
                continue
            try:
                _atomic_copy(src, dest / name)
                entry = {
                    "name": name,
                    "source": str(src),
                    "sha256": _sha256(dest / name),
                    "size_bytes": (dest / name).stat().st_size,
                }
                manifest_files.append(entry)
                result["files"].append(name)
            except Exception as exc:  # one bad file must not kill the backup
                log.warning("backup of %s failed (%s) — continuing", name, exc)
                result["errors"].append(f"{name}: {type(exc).__name__}: {exc}")

        manifest = {
            "ts": now_dt.isoformat(),
            "source_data_dir": str(ddir),
            "files": manifest_files,
        }
        _atomic_write_json(dest / MANIFEST_FILENAME, manifest)

        result["rotated_out"] = _rotate(broot, keep_last=keep_last)
        if result["errors"]:
            result["status"] = "error"
    except Exception as exc:  # noqa: BLE001 — backup must never raise
        log.warning("track backup failed (%s)", exc)
        result["status"] = "error"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spa_core.persistence.backup",
        description="Daily off-site backup of the SPA paper-trading track.",
    )
    parser.add_argument("--data-dir", default=None, help="data directory (default <repo>/data)")
    parser.add_argument(
        "--backup-dir", default=None,
        help="backup root (default $SPA_BACKUP_DIR or iCloud Drive SPA_backups)",
    )
    parser.add_argument("--verbose", action="store_true", help="verbose output")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    repo_root = Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else repo_root / "data"

    # Refresh the SQLite mirror first so the backup carries a current track.db.
    from spa_core.persistence.track_store import TrackStore

    sync = TrackStore(db_path=data_dir / "track.db").sync_from_json(data_dir)
    print(
        f"sync   : {sync['status']}  trades={sync['trades_total']}  "
        f"equity_points={sync['equity_points_total']}"
        + (f"  errors={sync['errors']}" if sync["errors"] else "")
    )

    res = run_backup(data_dir, args.backup_dir)
    print(
        f"backup : {res['status']}  dest={res['dest']}  files={res['files']}  "
        f"skipped={res['skipped']}  rotated_out={res['rotated_out']}"
        + (f"  errors={res['errors']}" if res["errors"] else "")
    )
    return 0 if (sync["status"] == "ok" and res["status"] == "ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
