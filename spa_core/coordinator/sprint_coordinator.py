#!/usr/bin/env python3
"""
SPA Sprint Coordinator — prevents parallel agent coordination failures.

Guards every sprint wave with deterministic pre/post gates:
  - Import smoke-test (all spa_core modules importable)
  - KANBAN.json integrity (valid JSON, no conflict markers)
  - Git index lock check
  - Unresolved merge conflict detection
  - Push-script file existence audit
  - pytest smoke (post-gate only)

Usage:
  python3 -m spa_core.coordinator.sprint_coordinator pre-gate
  python3 -m spa_core.coordinator.sprint_coordinator post-gate
  python3 -m spa_core.coordinator.sprint_coordinator kanban-update --done +1 --sprint v11.71
  python3 -m spa_core.coordinator.sprint_coordinator wave-report --wave 12
"""
from __future__ import annotations

import fcntl
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent.parent
DATA = REPO / "data"
KANBAN_PATH = REPO / "KANBAN.json"

# Modules to skip during import smoke-test (heavy / side-effect / test helpers)
_SKIP_PATTERNS = frozenset(
    [
        "__pycache__",
        "test_",
        "/tests/",
        "_test.py",
        # execution-domain isolation — never import from read-only code
        "spa_core/execution/",
        "spa_core/feed_health/",
        # non-runtime modules with external deps (fastapi / alembic / anthropic / pydantic)
        # these are dev/infra-only and explicitly NOT stdlib-compliant
        "spa_core/api/",
        "spa_core/database/alembic/",
        "spa_core/dev_agents/",
        "spa_core/family_fund/api/",
        "family_fund/manage_users",
    ]
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------
class GateResult(NamedTuple):
    """Outcome of a pre/post gate run."""

    passed: bool
    checks: dict  # str -> bool | int
    errors: list  # list[str]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_imports(
    skip_patterns: frozenset = _SKIP_PATTERNS,
) -> tuple[int, int, list]:
    """
    Import every spa_core module that isn't a test or in a skip-pattern.

    Returns
    -------
    ok_count    : int  — modules imported successfully
    fail_count  : int  — modules that raised on import
    errors      : list[str] — "<module>: <exc>" (capped at 20)
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    ok, fail, errors = 0, 0, []

    for pyfile in sorted(REPO.glob("spa_core/**/*.py")):
        rel = str(pyfile.relative_to(REPO))

        # Skip-pattern check
        skip = False
        for pat in skip_patterns:
            if pat in rel:
                skip = True
                break
        if skip:
            continue

        mod = rel.replace(os.sep, ".").removesuffix(".py")
        try:
            importlib.import_module(mod)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            if len(errors) < 20:
                errors.append(f"{mod}: {exc}")

    return ok, fail, errors


def check_kanban() -> tuple[bool, str]:
    """
    Verify KANBAN.json is present, conflict-free, and valid JSON.

    Returns
    -------
    is_valid : bool
    error    : str  — empty string when valid
    """
    if not KANBAN_PATH.exists():
        return False, "KANBAN.json missing"

    text = KANBAN_PATH.read_text(encoding="utf-8")

    if "<<<<<<" in text or ">>>>>>>" in text:
        return False, "KANBAN.json has git merge-conflict markers"

    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return False, f"KANBAN.json invalid JSON: {exc}"

    return True, ""


def check_git_clean() -> tuple[bool, str]:
    """
    Check for unresolved merge conflicts and stale .git/index.lock.

    Returns
    -------
    is_clean : bool
    error    : str  — empty when clean
    """
    # Unresolved merge conflict files
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    conflicts = [l for l in result.stdout.strip().splitlines() if l]
    if conflicts:
        return False, f"Unresolved conflict files: {conflicts[:5]}"

    # Stale index lock
    lock_path = REPO / ".git" / "index.lock"
    if lock_path.exists():
        return False, ".git/index.lock exists — another git process running or stale lock"

    return True, ""


def check_push_scripts(scripts_dir: Path | None = None) -> tuple[int, list]:
    """
    Walk scripts/push_v*.sh and verify every referenced relative file path
    actually exists on disk.

    Returns
    -------
    missing_count : int
    details       : list[str]  — "<script>: <path>" (capped at 10)
    """
    scripts_dir = scripts_dir or (REPO / "scripts")
    missing: list[str] = []

    for script in sorted(scripts_dir.glob("push_v*.sh")):
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for raw_line in text.splitlines():
            line = raw_line.strip().rstrip("\\").strip()
            # Skip comments, flags, python invocations, blank lines
            if not line or line.startswith("#") or line.startswith("-") or line.startswith("python"):
                continue
            # Looks like a file path: contains "/" and "."
            if "/" not in line or "." not in line:
                continue
            # Skip lines that look like shell commands
            if any(c in line for c in ("=", "$", "(", ")", "|", ";")):
                continue
            candidate = REPO / line
            if not candidate.exists():
                missing.append(f"{script.name}: {line}")
                if len(missing) >= 10:
                    return len(missing), missing  # cap early

    return len(missing), missing


# ---------------------------------------------------------------------------
# Gate runners
# ---------------------------------------------------------------------------


def pre_gate() -> GateResult:
    """
    Run all PRE-sprint checks.

    Checks
    ------
    1. KANBAN.json valid and conflict-free
    2. Git working tree has no unresolved conflicts / index.lock
    3. All spa_core modules import without error
    """
    checks: dict = {}
    errors: list = []

    # 1. KANBAN
    kanban_ok, kanban_err = check_kanban()
    checks["kanban_valid"] = kanban_ok
    if not kanban_ok:
        errors.append(f"[KANBAN] {kanban_err}")

    # 2. Git clean
    git_ok, git_err = check_git_clean()
    checks["git_clean"] = git_ok
    if not git_ok:
        errors.append(f"[GIT] {git_err}")

    # 3. Import smoke-test
    ok, fail, import_errors = check_imports()
    checks["imports_ok"] = fail == 0
    checks["import_ok_count"] = ok
    checks["import_fail_count"] = fail
    if fail > 0:
        errors.extend(f"[IMPORT] {e}" for e in import_errors[:5])

    passed = all(v for k, v in checks.items() if isinstance(v, bool))
    return GateResult(passed=passed, checks=checks, errors=errors)


def post_gate() -> GateResult:
    """
    Run all POST-sprint checks: same as pre_gate plus pytest smoke-test.

    Pytest is run with -x (fail-fast) and --timeout=30 to keep things quick.
    """
    pre = pre_gate()
    checks = dict(pre.checks)
    errors = list(pre.errors)

    # pytest
    test_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "spa_core/tests/",
            "-x",
            "-q",
            "--tb=short",
            "--timeout=30",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    tests_passed = test_result.returncode == 0
    checks["tests_passed"] = tests_passed
    if not tests_passed:
        tail = (test_result.stdout + test_result.stderr)[-600:]
        errors.append(f"[PYTEST] {tail}")

    passed = pre.passed and tests_passed
    return GateResult(passed=passed, checks=checks, errors=errors)


# ---------------------------------------------------------------------------
# KANBAN atomic updater (single-writer via fcntl)
# ---------------------------------------------------------------------------


def kanban_update(done_delta: int = 1, sprint: str | None = None) -> dict:
    """
    Atomically update KANBAN.json.

    Uses an exclusive fcntl lock so multiple parallel agents cannot corrupt
    the file.  Increments ``done_count`` by *done_delta* and optionally sets
    ``sprint_current``.

    Returns
    -------
    dict with ``done_count`` and ``sprint`` after the write.
    """
    with open(KANBAN_PATH, "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            data["done_count"] = data.get("done_count", 0) + done_delta
            if sprint is not None:
                data["sprint_current"] = sprint
            data["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            data["updated_by"] = f"sprint_coordinator ({datetime.now(tz=timezone.utc).isoformat()})"

            fh.seek(0)
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.truncate()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)

    return {
        "done_count": data["done_count"],
        "sprint": data.get("sprint_current"),
    }


# ---------------------------------------------------------------------------
# Wave report
# ---------------------------------------------------------------------------


def wave_report(wave: int | None = None) -> dict:
    """
    Produce a summary snapshot of coordinator health for the given wave.

    Does NOT write anything to disk — purely advisory.
    """
    ok, fail, import_errors = check_imports()
    kanban_ok, kanban_err = check_kanban()
    git_ok, git_err = check_git_clean()
    missing_count, missing_paths = check_push_scripts()

    kanban_data: dict = {}
    if kanban_ok:
        try:
            kanban_data = json.loads(KANBAN_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    # Count new files since last git commit
    new_files_result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    new_files = [l for l in new_files_result.stdout.strip().splitlines() if l]

    return {
        "wave": wave,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "imports": {
            "ok": ok,
            "fail": fail,
            "top_errors": import_errors[:5],
        },
        "kanban": {
            "valid": kanban_ok,
            "done_count": kanban_data.get("done_count"),
            "sprint_current": kanban_data.get("sprint_current"),
            "sprint_completed": kanban_data.get("sprint_completed"),
            "error": kanban_err or None,
        },
        "git": {
            "clean": git_ok,
            "error": git_err or None,
            "new_files_in_head": new_files[:20],
        },
        "push_scripts": {
            "missing_refs": missing_count,
            "samples": missing_paths[:5],
        },
    }


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(
        description="SPA Sprint Coordinator — parallel agent safety gates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")

    sub.add_parser("pre-gate", help="Run pre-sprint checks (imports, KANBAN, git)")
    sub.add_parser("post-gate", help="Run post-sprint checks (pre-gate + pytest)")

    ku = sub.add_parser("kanban-update", help="Atomically update KANBAN.json")
    ku.add_argument("--done", type=int, default=1, metavar="N", help="Increment done_count by N")
    ku.add_argument("--sprint", type=str, default=None, help="Set sprint_current")

    wr = sub.add_parser("wave-report", help="Print JSON health summary for a wave")
    wr.add_argument("--wave", type=int, default=None, help="Wave number (informational)")

    return parser, parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser, args = _parse_args(argv)

    if args.cmd == "pre-gate":
        r = pre_gate()
        print(json.dumps({"passed": r.passed, "checks": r.checks, "errors": r.errors}, indent=2))
        return 0 if r.passed else 1

    elif args.cmd == "post-gate":
        r = post_gate()
        print(json.dumps({"passed": r.passed, "checks": r.checks, "errors": r.errors}, indent=2))
        return 0 if r.passed else 1

    elif args.cmd == "kanban-update":
        result = kanban_update(done_delta=args.done, sprint=args.sprint)
        print(json.dumps(result, indent=2))
        return 0

    elif args.cmd == "wave-report":
        report = wave_report(args.wave)
        print(json.dumps(report, indent=2))
        return 0

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
