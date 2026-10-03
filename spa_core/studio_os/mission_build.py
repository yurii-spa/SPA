"""spa_core/studio_os/mission_build.py — Mission Control v1 bundle builder (ADR-552).

ONE step: call the canonical read model (``spa_core.studio_os.mission_control.build()``), write a
NEW bundle directory containing that model plus a copy of the UI tree
(``spa_core/studio_os/mission_ui/``), then move the pointer (``current.json``) to it with a single
``os.replace``. ``mission_server.py`` never sees a half-written bundle: it is assembled under a
``.incomplete`` staging name and only renamed into place once every required file is there.

Why a NEW directory per build, not an in-place rewrite
========================================================
The server holds a bundle fully in memory and only re-reads it when the pointer names a different
directory (see ``mission_server.Serving``). Rewriting files inside the directory the server might be
reading from right now would let it observe a half-updated set; a fresh directory name plus one
pointer swap makes that impossible by construction, mirroring the Director server/publisher pair
(``scripts/cartographer/director_publish.py``).

Failure is fail-CLOSED
=======================
If ``mission_control.build()`` raises, or the UI tree is missing ``index.html``/``app.js``, this
module exits 2 and the previous bundle directory + pointer are left completely untouched — the
staging directory is the only thing touched, and it is removed on any failure.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from spa_core.studio_os import mission_server as _mission_server
from spa_core.utils.atomic import atomic_save

DEFAULT_ROOT = Path.home() / "studio-os-serve" / "mission"
DEFAULT_KEEP = 5
POINTER_FILE = "current.json"
BUNDLE_PREFIX = "b-"
#: Finding #10 (second review round): two builds running at once (e.g. a 5-minute cron tick
#: overlapping a slow previous run) could each ``_prune()`` while the OTHER is mid-write — the
#: second build's view of "what's current" is a snapshot taken before the first build's pointer
#: swap, so it could legitimately rmtree the bundle the first build just made current. An
#: exclusive, non-blocking ``flock`` on this file serialises builds against each other entirely;
#: a build that cannot get the lock does not wait and does not fail — it skips (see
#: ``BuildSkipped``), leaving everything exactly as it was.
LOCK_FILE = ".build.lock"
#: A staging directory is a WORK IN PROGRESS, never a bundle. It must NOT start with
#: BUNDLE_PREFIX (finding #13): a concurrent build's ``_prune()`` walks every directory whose name
#: starts with "b-" and may ``rmtree`` it — if the staging name shared that prefix (the former
#: ``b-<stamp>-<rand>.incomplete`` scheme did), a second build running at the same time could prune
#: the FIRST build's in-progress staging directory out from under it.
STAGING_PREFIX = ".staging-"

#: Source tree copied into every bundle. Whatever files exist there are copied; the files the
#: SERVER actually needs (minus mission.json, which this module writes itself) gate the build —
#: derived from ``mission_server.ROUTES`` (finding #13) so a bundle the server would refuse to
#: serve can never be "built" successfully in the first place.
UI_DIR = Path(__file__).resolve().parent / "mission_ui"
#: «another build is running — nothing built this time»; not 0 (success), not 2 (failure)
EXIT_SKIPPED = 75
REQUIRED_UI_FILES = tuple(sorted({name for name, _ctype in _mission_server.ROUTES.values()
                                   if name != "mission.json"}))

# No PRODUCES declaration: the manifest's artifact contract covers repo `data/` artifacts, and the bundle
# lives OUTSIDE the repo on purpose (like com.spa.director_build). Its freshness is watched twice: agent_health
# sees a failing run (exit 2), and the page itself shows «stale» from `generated_at` on the reader's clock.


class BuildError(Exception):
    """Raised on any failure that must leave the previous bundle/pointer untouched."""


class BuildSkipped(Exception):
    """Another build holds the lock (finding #10). NOT a failure: nothing was touched, there is
    simply nothing to do here — the other build will publish its own bundle. Deliberately a
    SEPARATE class from ``BuildError`` so ``main()`` can tell "refused" (exit 2) apart from
    "skipped, by design" (exit 0)."""


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _new_bundle_name(now: datetime) -> str:
    return f"{BUNDLE_PREFIX}{_stamp(now)}-{secrets.token_hex(4)}"


def _new_staging_name(now: datetime) -> str:
    """Deliberately a DIFFERENT prefix from ``BUNDLE_PREFIX`` (see ``STAGING_PREFIX`` docstring) —
    a concurrent build's ``_prune()`` only ever looks at names starting with "b-"."""
    return f"{STAGING_PREFIX}{_stamp(now)}-{secrets.token_hex(4)}"


def _copy_ui_files(src_dir: Path, dest: Path) -> list:
    """Copy every regular file in ``src_dir`` into ``dest``. Raises if a required file is absent."""
    if not src_dir.is_dir():
        raise BuildError(f"mission_ui source tree not found: {src_dir}")
    copied = []
    for f in sorted(src_dir.iterdir()):
        if not f.is_file():
            continue
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)
    missing = [name for name in REQUIRED_UI_FILES if name not in copied]
    if missing:
        raise BuildError(
            f"mission_ui is missing required file(s): {', '.join(missing)} "
            f"(found: {', '.join(copied) or 'nothing'})"
        )
    return copied


def _existing_bundles(root: Path) -> list:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(BUNDLE_PREFIX))


def _current_bundle_name(root: Path) -> Optional[str]:
    """Best-effort read of ``current.json`` straight off disk — ``None`` on anything wrong with
    it, never an exception (this is a defensive extra read, not the pointer's canonical reader,
    which is ``mission_server.read_pointer``)."""
    try:
        doc = json.loads((root / POINTER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    name = doc.get("bundle")
    return str(name) if name else None


def _prune(root: Path, keep: int, current_name: str) -> list:
    """Remove bundle dirs beyond ``keep``, oldest first, NEVER the one ``current.json`` names.

    Bundle names sort chronologically (UTC stamp prefix), so a plain name sort is a time sort.

    Finding #10 (second review round): re-reads ``current.json`` fresh rather than trusting ONLY
    the caller's ``current_name`` — belt-and-suspenders now that ``build_bundle`` also serialises
    builds with ``LOCK_FILE``, but cheap enough to keep even though the lock should make the two
    ever disagree.
    """
    live_current = _current_bundle_name(root) or current_name
    bundles = _existing_bundles(root)
    protect = {current_name, live_current}
    excess = len(bundles) - keep
    if excess <= 0:
        return []
    removed = []
    for p in bundles:
        if len(removed) >= excess:
            break
        if p.name in protect:
            continue  # the bundle current.json names (by either reading) is never pruned
        shutil.rmtree(p, ignore_errors=True)
        removed.append(p.name)
    return removed


def build_bundle(root, *, keep: int = DEFAULT_KEEP, now: Optional[datetime] = None,
                  build_fn: Optional[Callable[[], dict]] = None,
                  ui_dir: Optional[Path] = None) -> dict:
    """Build one new bundle and move the pointer to it, serialised against any OTHER concurrent
    call to this function on the same ``root`` (finding #10): a non-blocking exclusive lock on
    ``root/.build.lock``. Raises ``BuildSkipped`` (NOT a failure) if another build already holds
    it — this call touches nothing at all in that case, not even a staging directory.

    Raises ``BuildError`` on ANY failure (finding #13: including one this function did not
    anticipate), having touched nothing but its own (removed) staging directory — the previous
    bundle dir and pointer are left exactly as they were.
    """
    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_FILE
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BuildSkipped(
                f"another build holds {lock_path} — pointer and bundles untouched") from exc
        return _build_bundle_locked(root, keep=keep, now=now, build_fn=build_fn, ui_dir=ui_dir)
    finally:
        os.close(lock_fd)  # also releases the flock


def _build_bundle_locked(root: Path, *, keep: int, now: Optional[datetime],
                          build_fn: Optional[Callable[[], dict]],
                          ui_dir: Optional[Path]) -> dict:
    """The actual build, assuming the caller already holds the exclusive lock."""
    try:
        now = now or datetime.now(timezone.utc)
        ui_dir = Path(ui_dir) if ui_dir is not None else UI_DIR

        from spa_core.studio_os import mission_control as mc
        build_fn = build_fn or mc.build
        try:
            model = build_fn()
        except Exception as exc:  # noqa: BLE001 — any producer failure is fail-CLOSED, never a half bundle
            raise BuildError(f"mission_control.build() raised {type(exc).__name__}: {exc}") from exc
        if not isinstance(model, dict):
            raise BuildError(
                f"mission_control.build() returned {type(model).__name__}, expected dict")

        name = _new_bundle_name(now)
        bundle_dir = root / name
        staging = root / _new_staging_name(now)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(mode=0o700)
        try:
            atomic_save(model, str(staging / "mission.json"))
            copied = _copy_ui_files(ui_dir, staging)
        except BuildError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 — same fail-CLOSED guarantee, unanticipated cause
            shutil.rmtree(staging, ignore_errors=True)
            raise BuildError(f"writing staged bundle failed: {type(exc).__name__}: {exc}") from exc

        try:
            os.replace(staging, bundle_dir)  # same filesystem (both under root) → atomic rename
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise BuildError(f"could not activate new bundle directory: {exc}") from exc

        pointer = {
            "bundle": name,
            "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schema": model.get("schema"),
            "system_state": ((model.get("system") or {}).get("_meta") or {}).get("state"),
        }
        pointer_path = root / POINTER_FILE
        try:
            # data FIRST (finding #13) — this used to be a hand-rolled tmp+os.replace, the exact
            # pattern atomic_save exists to replace.
            atomic_save(pointer, str(pointer_path))
        except Exception as exc:  # noqa: BLE001 — the new bundle dir exists but is not yet
            # pointed at; the OLD pointer (if any) still names the OLD bundle, so nothing is served
            # half-built — but the failure must still surface as BuildError, not a bare traceback.
            raise BuildError(f"could not write pointer: {type(exc).__name__}: {exc}") from exc

        removed = _prune(root, keep, current_name=name)
        return {"bundle": name, "ui_files": copied, "pruned": removed, "pointer": pointer}
    except BuildError:
        raise
    except Exception as exc:  # noqa: BLE001 — finding #13: ANY unexpected exception is fail-CLOSED
        raise BuildError(f"unexpected {type(exc).__name__}: {exc}") from exc


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Mission Control v1 bundle builder (ADR-552)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="bundle root (default: %(default)s)")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="bundles to keep (default: %(default)s)")
    a = ap.parse_args(argv)
    try:
        result = build_bundle(Path(a.root), keep=a.keep)
    except BuildSkipped as exc:
        # Finding #10: another build holds the lock — pointer and bundles untouched. Nothing was built,
        # so this is NOT a success (inv. #17): exit 75 (EX_TEMPFAIL, the same «refused, try later» code
        # the heavy-job admission uses), distinct from failure (2) and success (0).
        print(f"MISSION_BUILD_SKIPPED: {exc}")
        return EXIT_SKIPPED
    except BuildError as exc:
        print(f"MISSION_BUILD_FAILED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders: build_bundle() already wraps
        # every failure as BuildError, but main() must not let an uncaught traceback mean exit 1
        # ("a crash" is a different signal from "refused" — both are fail-CLOSED, but only the
        # latter is the documented contract: pointer untouched, exit 2).
        print(f"MISSION_BUILD_FAILED: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"mission bundle {result['bundle']}: ui_files={len(result['ui_files'])} "
          f"pruned={len(result['pruned'])} system={result['pointer'].get('system_state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
