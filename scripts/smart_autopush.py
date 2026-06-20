#!/usr/bin/env python3
"""
SPA Smart Autopush — pushes pending sprint scripts via GitHub Contents API.

Tracks progress in data/autopush_state.json to avoid re-pushing.
Runs every 60 minutes via launchd com.spa.autopush.

Design:
  - Scans scripts/push_v*.sh for version numbers > last_pushed_version
  - Runs matching scripts in ascending version order
  - Each push_v*.sh calls push_to_github.py internally (API-based, no git)
  - State persisted atomically in data/autopush_state.json after each success
  - Singleton lock in /tmp/spa_smart_autopush.lock

Migration from auto_push.sh:
  - auto_push.sh used scripts/.push_log (filename-based tracking)
  - smart_autopush.py uses data/autopush_state.json (version-number-based)
  - On first run, if last_version == 0, all existing push_v*.sh are candidates;
    set last_version manually to skip already-pushed scripts (see below).

SECRETS POLICY: PAT is NEVER written to any file. Read from Keychain only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("spa_smart_autopush")

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO = Path(__file__).parent.parent          # ~/Documents/SPA_Claude
STATE_FILE = REPO / "data" / "autopush_state.json"
SCRIPTS_DIR = REPO / "scripts"
LOCK_FILE = Path("/tmp/spa_smart_autopush.lock")

# Pause between consecutive script runs (seconds) — avoids GitHub API rate limits
INTER_PUSH_SLEEP = 4


# ── Singleton lock ─────────────────────────────────────────────────────────────

def acquire_lock() -> bool:
    """Return True if lock was acquired, False if another instance is running."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if that PID is still alive
            os.kill(pid, 0)
            logger.warning(f"Another instance running (PID {pid}), exiting")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            logger.info("Removing stale lock")
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# ── PAT ────────────────────────────────────────────────────────────────────────

def get_pat() -> str:
    """Read GitHub PAT from macOS Keychain. Never from files."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
        capture_output=True, text=True, timeout=5,
    )
    pat = result.stdout.strip()
    if pat:
        return pat
    # Fallback: env var (useful in CI / non-macOS)
    for env_var in ("GITHUB_PAT_SPA", "SPA_GITHUB_PAT", "GITHUB_PAT"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    raise RuntimeError(
        "PAT not found: add to Keychain with 'bash setup_pat.sh' or set GITHUB_PAT_SPA env"
    )


# ── State ──────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as exc:
            logger.warning(f"Could not read state file: {exc}")
    return {"last_version": 0, "total_pushed": 0, "updated": ""}


def save_state(state: dict) -> None:
    """Atomic write to data/autopush_state.json."""
    state["updated"] = datetime.now(timezone.utc).isoformat()
    tmp = Path(tempfile.mktemp(dir=STATE_FILE.parent, prefix=".autopush_state."))
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


# ── Script discovery ───────────────────────────────────────────────────────────

def discover_pending(after_version: int) -> list[tuple[int, Path]]:
    """Return list of (version, path) for push_v*.sh scripts with version > after_version."""
    pending: list[tuple[int, Path]] = []
    for p in SCRIPTS_DIR.glob("push_v*.sh"):
        m = re.fullmatch(r"push_v(\d+)\.sh", p.name)
        if m:
            v = int(m.group(1))
            if v > after_version:
                pending.append((v, p))
    return sorted(pending, key=lambda x: x[0])


# ── Script runner ──────────────────────────────────────────────────────────────

def run_script(path: Path, pat: str) -> bool:
    """
    Execute a push_v*.sh script in the repo root.

    PAT is injected via GITHUB_PAT_SPA env var so that push_to_github.py
    can use it as fallback if Keychain is unavailable in the subprocess context.
    The PAT is NEVER written to disk.
    """
    env = {
        # Minimal safe environment
        "HOME": str(Path.home()),
        "PATH": (
            "/Users/yuriikulieshov/miniconda3/bin"
            ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        ),
        # Inject PAT into env so push_to_github.py subprocess can find it
        "GITHUB_PAT_SPA": pat,
    }
    try:
        result = subprocess.run(
            ["bash", str(path)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(REPO),
            env=env,
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                logger.info(f"  {line}")
        if result.returncode != 0:
            if result.stderr:
                for line in result.stderr.strip().splitlines():
                    logger.error(f"  STDERR: {line}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout (180s): {path.name}")
        return False
    except Exception as exc:
        logger.error(f"Exception running {path.name}: {exc}")
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("SPA Smart Autopush starting")

    if not acquire_lock():
        sys.exit(0)

    try:
        _run()
    finally:
        release_lock()


def _run() -> None:
    # 1. Load PAT (fail fast if not available)
    try:
        pat = get_pat()
        logger.info(f"PAT found ({len(pat)} chars)")
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # 2. Load state
    state = load_state()
    last_version: int = state.get("last_version", 0)
    total_pushed: int = state.get("total_pushed", 0)
    logger.info(f"State: last_version=v{last_version}, total_pushed={total_pushed}")

    # 3. Discover pending scripts
    pending = discover_pending(after_version=last_version)
    logger.info(f"Pending scripts: {len(pending)}")
    if not pending:
        logger.info("Nothing to push — all scripts up to date")
        return

    # 4. Run in order, stop on first failure
    pushed_this_run = 0
    for version, path in pending:
        logger.info(f"▶ Running {path.name} (v{version})…")
        ok = run_script(path, pat)
        if ok:
            last_version = version
            total_pushed += 1
            pushed_this_run += 1
            state["last_version"] = last_version
            state["total_pushed"] = total_pushed
            save_state(state)
            logger.info(f"✅ {path.name} done (total_pushed={total_pushed})")
            # Small pause to respect GitHub API rate limits
            import time
            time.sleep(INTER_PUSH_SLEEP)
        else:
            logger.error(f"❌ {path.name} FAILED — stopping, will retry next run")
            break

    logger.info(
        f"Smart Autopush done: pushed_this_run={pushed_this_run}, "
        f"last_version=v{last_version}"
    )


if __name__ == "__main__":
    main()
