"""
scripts/spaerror_final_audit.py

MP-1467 (v10.83) — SPAError Final Adoption Audit

Verifies zero bare Exception/RuntimeError in spa_core/ (excluding stdlib
contracts and test files). Exits 0 on PASS, 1 on FAIL.

Usage:
    python3 scripts/spaerror_final_audit.py

stdlib-only — no external dependencies.
"""

from __future__ import annotations

import subprocess
import sys
import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
SCAN_DIR = REPO_ROOT / "spa_core"

# Patterns that constitute bare exception usage
BARE_PATTERNS = [
    "raise Exception",
    "raise RuntimeError",
]

# Lines containing this marker are intentionally stdlib-only (not migrated)
STDLIB_MARKER = "# stdlib-only"

# Exclusions: test files and cached bytecode
EXCLUDE_FRAGMENTS = ["test", "__pycache__"]


def grep_pattern(pattern: str) -> list[str]:
    """Return non-test, non-cache lines matching pattern in spa_core/."""
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, str(SCAN_DIR)],
        capture_output=True,
        text=True,
    )
    lines = []
    for line in result.stdout.splitlines():
        if any(excl in line for excl in EXCLUDE_FRAGMENTS):
            continue
        if STDLIB_MARKER in line:
            continue
        lines.append(line)
    return lines


def collect_spa_imports() -> int:
    """Count files importing from spa_core.utils.errors (SPAError users)."""
    result = subprocess.run(
        [
            "grep",
            "-rln",
            "--include=*.py",
            "from spa_core.utils.errors import",
            str(SCAN_DIR),
        ],
        capture_output=True,
        text=True,
    )
    files = [
        l
        for l in result.stdout.splitlines()
        if l and not any(excl in l for excl in EXCLUDE_FRAGMENTS)
    ]
    return len(files)


def run_audit() -> int:
    """
    Execute the full audit. Returns exit code: 0 = PASS, 1 = FAIL.
    """
    print("=" * 60)
    print("SPA SPAError Final Adoption Audit")
    print(f"Generated : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Scan dir  : {SCAN_DIR}")
    print("=" * 60)

    # Collect violations
    violations: list[str] = []
    for pattern in BARE_PATTERNS:
        violations.extend(grep_pattern(pattern))

    # Remove duplicates (same file:line appearing for both patterns)
    seen: set[str] = set()
    unique_violations: list[str] = []
    for line in violations:
        key = ":".join(line.split(":")[:2])
        if key not in seen:
            seen.add(key)
            unique_violations.append(line)

    spa_import_count = collect_spa_imports()

    print(f"\nFiles using SPAError imports : {spa_import_count}")
    print(f"Bare Exception violations    : {len(unique_violations)}")

    if unique_violations:
        print("\n⛔ FAIL — Remaining bare exceptions (migrate to SPAError):")
        for line in unique_violations[:20]:
            print(f"  {line}")
        if len(unique_violations) > 20:
            print(f"  ... and {len(unique_violations) - 20} more")
        print(
            "\nFix: replace 'raise Exception/RuntimeError' with the appropriate\n"
            "SPAError subclass from spa_core.utils.errors. If this is genuinely\n"
            "a stdlib-only module, append '# stdlib-only' to the raise line.\n"
        )
        return 1

    print("\n✅ PASS — 0 bare exceptions in spa_core/ (non-test, non-stdlib)")
    print(f"   SPAError adoption: {spa_import_count} modules")
    return 0


if __name__ == "__main__":
    sys.exit(run_audit())
