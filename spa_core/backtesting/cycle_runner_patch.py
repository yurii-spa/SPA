"""
spa_core/backtesting/cycle_runner_patch.py

Shows how to patch cycle_runner.py to include CPA gate checks.
This is a "patch descriptor" — it reads the current cycle_runner.py
and shows exactly where to add the CPA hook.

MP-1348 (v9.64)

Usage:
  python3 -m spa_core.backtesting.cycle_runner_patch --show-diff
  python3 -m spa_core.backtesting.cycle_runner_patch --apply          # applies patch
  python3 -m spa_core.backtesting.cycle_runner_patch --apply --dry-run
  python3 -m spa_core.backtesting.cycle_runner_patch --verify         # checks if applied

stdlib only; no external dependencies.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
from pathlib import Path

# ── Patch fragments ─────────────────────────────────────────────────────────

CPA_HOOK_IMPORT = """\
# CPA Gate Hook (added by cycle_runner_patch.py)
from spa_core.backtesting.cycle_runner_cpa_hook import CPAGateHook as _CPAGateHook
_cpa_hook = _CPAGateHook()
"""

CPA_HOOK_CALL = """\
    # CPA Gate Check
    _cpa_result = _cpa_hook.check()
    if not _cpa_result["allow_live"]:
        logger.warning(f"[CPA] Live deployment blocked: {_cpa_result['reason']}")
    if _cpa_result["allow_paper"]:
        logger.info("[CPA] Paper trading: ALLOWED")
"""

# Sentinel used to check if patch is already applied
_IMPORT_SENTINEL = "from spa_core.backtesting.cycle_runner_cpa_hook import CPAGateHook"
_CALL_SENTINEL = "_cpa_result = _cpa_hook.check()"

# Injection anchors: where to insert the import block (after stdlib imports)
_IMPORT_ANCHOR = "from __future__ import annotations"
# Injection anchor for the call: first line of the main run() body
_CALL_ANCHOR_CANDIDATES = [
    "def run(",
    "def _run(",
    "def main(",
    "def cycle(",
]


class CycleRunnerPatch:
    """
    Patch descriptor for cycle_runner.py.

    Reads the target file, computes what needs to be added,
    and can either preview or apply the patch.
    """

    def __init__(self, cycle_runner_path: str = "cycle_runner.py") -> None:
        self._path = Path(cycle_runner_path)

    # ── Public API ──────────────────────────────────────────────────────────

    def is_already_applied(self) -> bool:
        """Return True if the CPA hook import is already present."""
        if not self._path.exists():
            return False
        text = self._path.read_text(encoding="utf-8")
        return _IMPORT_SENTINEL in text and _CALL_SENTINEL in text

    def show_diff(self) -> str:
        """
        Return a unified diff string of what would be added.

        Returns an empty string if the file does not exist.
        """
        if not self._path.exists():
            return f"# File not found: {self._path}\n"

        original = self._path.read_text(encoding="utf-8")
        patched = self._build_patched(original)

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{self._path}",
                tofile=f"b/{self._path} (patched)",
            )
        )
        if not diff_lines:
            return "# No changes — patch already applied or nothing to add.\n"
        return "".join(diff_lines)

    def apply(self, dry_run: bool = False) -> dict:
        """
        Apply the patch.

        Makes a backup of the original file as ``<filename>.bak`` before writing.

        Args:
            dry_run: If True, compute the result without writing any files.

        Returns:
            {
              "success":         bool,
              "already_applied": bool,
              "lines_added":     int,
              "dry_run":         bool,
              "backup_path":     str | None,
            }
        """
        if not self._path.exists():
            return {
                "success": False,
                "already_applied": False,
                "lines_added": 0,
                "dry_run": dry_run,
                "backup_path": None,
                "error": f"File not found: {self._path}",
            }

        original = self._path.read_text(encoding="utf-8")

        if self.is_already_applied():
            return {
                "success": True,
                "already_applied": True,
                "lines_added": 0,
                "dry_run": dry_run,
                "backup_path": None,
            }

        patched = self._build_patched(original)
        lines_added = patched.count("\n") - original.count("\n")

        if dry_run:
            return {
                "success": True,
                "already_applied": False,
                "lines_added": lines_added,
                "dry_run": True,
                "backup_path": None,
            }

        # Backup original
        backup_path = self._path.with_suffix(self._path.suffix + ".bak")
        shutil.copy2(self._path, backup_path)

        # Atomic write via tmp + os.replace
        tmp_path = self._path.with_suffix(self._path.suffix + ".patch_tmp")
        try:
            tmp_path.write_text(patched, encoding="utf-8")
            os.replace(tmp_path, self._path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        return {
            "success": True,
            "already_applied": False,
            "lines_added": lines_added,
            "dry_run": False,
            "backup_path": str(backup_path),
        }

    def verify(self) -> dict:
        """
        Return verification status of the patch.

        Returns:
            {
              "success":         bool,   # True if patch is applied
              "import_present":  bool,
              "call_present":    bool,
              "file_exists":     bool,
              "path":            str,
            }
        """
        file_exists = self._path.exists()
        import_present = False
        call_present = False

        if file_exists:
            text = self._path.read_text(encoding="utf-8")
            import_present = _IMPORT_SENTINEL in text
            call_present = _CALL_SENTINEL in text

        return {
            "success": import_present and call_present,
            "import_present": import_present,
            "call_present": call_present,
            "file_exists": file_exists,
            "path": str(self._path),
        }

    # ── Private helpers ─────────────────────────────────────────────────────

    def _build_patched(self, original: str) -> str:
        """
        Insert CPA import block and call block into *original* source text.

        Strategy:
          1. Insert import block after the ``from __future__ import annotations``
             line (or after the last stdlib import if anchor not found).
          2. Insert call block at the first line of the first matching
             ``def run(``/``def main(``/etc. function body.
        """
        lines = original.splitlines(keepends=True)
        lines = self._insert_import(lines)
        lines = self._insert_call(lines)
        return "".join(lines)

    @staticmethod
    def _insert_import(lines: list[str]) -> list[str]:
        """Insert CPA_HOOK_IMPORT after the __future__ import line."""
        anchor_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(_IMPORT_ANCHOR):
                anchor_idx = i
                break

        if anchor_idx is None:
            # Fallback: insert before first non-comment, non-empty line
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    anchor_idx = i - 1
                    break
            if anchor_idx is None:
                anchor_idx = 0

        import_lines = ["\n"] + CPA_HOOK_IMPORT.splitlines(keepends=True)
        result = lines[: anchor_idx + 1] + import_lines + lines[anchor_idx + 1 :]
        return result

    @staticmethod
    def _insert_call(lines: list[str]) -> list[str]:
        """Insert CPA_HOOK_CALL at the start of the first matching function body."""
        func_idx = None
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            for candidate in _CALL_ANCHOR_CANDIDATES:
                if candidate in stripped and stripped.lstrip().startswith("def "):
                    func_idx = i
                    break
            if func_idx is not None:
                break

        if func_idx is None:
            # No matching function found — append at end with a note
            return lines + ["\n# NOTE: CPA_HOOK_CALL could not be auto-inserted\n"]

        # Find the first line of the function body (after the def line and its colon)
        body_idx = func_idx + 1
        while body_idx < len(lines):
            stripped = lines[body_idx].strip()
            if stripped and not stripped.startswith('"""') and not stripped.startswith("'''"):
                break
            # Skip docstring
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                # advance until closing triple-quote
                body_idx += 1
                while body_idx < len(lines):
                    if quote in lines[body_idx]:
                        body_idx += 1
                        break
                    body_idx += 1
                break
            body_idx += 1

        call_lines = ["\n"] + CPA_HOOK_CALL.splitlines(keepends=True)
        result = lines[:body_idx] + call_lines + lines[body_idx:]
        return result


# ── CLI ─────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Patch cycle_runner.py to include CPA gate checks."
    )
    parser.add_argument(
        "--cycle-runner",
        default="cycle_runner.py",
        help="Path to cycle_runner.py (default: cycle_runner.py)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--show-diff",
        action="store_true",
        help="Show unified diff of what would be added",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the patch (use --dry-run to preview)",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Check if the patch is already applied",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --apply: compute result without writing files",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    patch = CycleRunnerPatch(cycle_runner_path=args.cycle_runner)

    if args.show_diff:
        print(patch.show_diff())

    elif args.apply:
        result = patch.apply(dry_run=args.dry_run)
        if result.get("error"):
            print(f"ERROR: {result['error']}")
            raise SystemExit(1)
        if result["already_applied"]:
            print("Patch already applied — nothing to do.")
        elif result["dry_run"]:
            print(
                f"[DRY RUN] Would add {result['lines_added']} lines to "
                f"{args.cycle_runner}"
            )
        else:
            print(
                f"Patch applied: {result['lines_added']} lines added. "
                f"Backup: {result['backup_path']}"
            )

    elif args.verify:
        status = patch.verify()
        print(f"File exists:     {status['file_exists']}")
        print(f"Import present:  {status['import_present']}")
        print(f"Call present:    {status['call_present']}")
        print(f"Patch applied:   {status['success']}")
        if not status["success"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
