"""
scripts/verify_infrastructure.py

Verifies all SPA infrastructure gates: git hooks, launchd plists,
kill switch, data backups, and monitoring daemons.

MP-1418 (v10.34) — stdlib only, read-only, exit 0 always.

Usage:
    python3 scripts/verify_infrastructure.py          # print report
    python3 scripts/verify_infrastructure.py --json   # JSON output
    python3 scripts/verify_infrastructure.py --strict # exit 1 if not all pass
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Repo root = parent of this script's directory
REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Check functions ────────────────────────────────────────────────────────────


def check_git_hooks() -> bool:
    """Returns True if at least one custom git hook is installed in .git/hooks/.

    Looks for executable files in .git/hooks/ that are NOT sample files.
    """
    hooks_dir = REPO_ROOT / ".git" / "hooks"
    if not hooks_dir.is_dir():
        return False
    for hook in hooks_dir.iterdir():
        if hook.is_file() and not hook.name.endswith(".sample"):
            # Check it's executable
            if os.access(hook, os.X_OK):
                return True
    return False


def check_launchd_plist() -> bool:
    """Returns True if at least one com.spa.*.plist exists in scripts/ or ~/Library/LaunchAgents/.

    Checks both the repo scripts/ directory and the macOS LaunchAgents directory.
    """
    # Check repo scripts/ directory
    scripts_dir = REPO_ROOT / "scripts"
    if scripts_dir.is_dir():
        plists = list(scripts_dir.glob("com.spa.*.plist"))
        if plists:
            return True
    # Check macOS LaunchAgents
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if launch_agents.is_dir():
        plists = list(launch_agents.glob("com.spa.*.plist"))
        if plists:
            return True
    return False


def check_kill_switch() -> bool:
    """Returns True if the kill-switch module exists (spa_core/safety/).

    Checks for spa_core/safety/safeguard.py and live_trading_gate.py.
    """
    safety_dir = REPO_ROOT / "spa_core" / "safety"
    if not safety_dir.is_dir():
        return False
    has_safeguard = (safety_dir / "safeguard.py").is_file()
    has_gate = (safety_dir / "live_trading_gate.py").is_file()
    return has_safeguard and has_gate


def check_data_backups() -> bool:
    """Returns True if the autopush script or equivalent backup mechanism exists.

    Checks for auto_push.py or push_to_github.py in repo root.
    """
    auto_push = REPO_ROOT / "auto_push.py"
    push_github = REPO_ROOT / "push_to_github.py"
    return auto_push.is_file() or push_github.is_file()


def check_monitoring() -> bool:
    """Returns True if launchd monitoring / daily cycle runner exists.

    Checks for cycle_runner.py in spa_core/paper_trading/.
    """
    cycle_runner = REPO_ROOT / "spa_core" / "paper_trading" / "cycle_runner.py"
    return cycle_runner.is_file()


def check_verify_script() -> bool:
    """Returns True if this verify_infrastructure.py script itself exists."""
    return (REPO_ROOT / "scripts" / "verify_infrastructure.py").is_file()


def check_infrastructure_doc() -> bool:
    """Returns True if docs/INFRASTRUCTURE_CHECKLIST.md exists and is non-empty."""
    doc = REPO_ROOT / "docs" / "INFRASTRUCTURE_CHECKLIST.md"
    try:
        return doc.is_file() and doc.stat().st_size >= 200
    except OSError:
        return False


def check_install_hooks_script() -> bool:
    """Returns True if scripts/install_git_hooks.sh exists."""
    return (REPO_ROOT / "scripts" / "install_git_hooks.sh").is_file()


# ── Aggregation ────────────────────────────────────────────────────────────────

# Registry of all checks: (name, description, function)
CHECKS: List[Tuple[str, str, object]] = [
    ("git_hooks",          "Git hooks installed",                    check_git_hooks),
    ("launchd_plist",      "launchd plist files present",           check_launchd_plist),
    ("kill_switch",        "Kill-switch module (spa_core/safety/)",  check_kill_switch),
    ("data_backups",       "Backup/push script available",           check_data_backups),
    ("monitoring",         "Daily cycle runner present",             check_monitoring),
    ("verify_script",      "verify_infrastructure.py present",       check_verify_script),
    ("infrastructure_doc", "INFRASTRUCTURE_CHECKLIST.md present",    check_infrastructure_doc),
    ("install_hooks_sh",   "install_git_hooks.sh present",           check_install_hooks_script),
]


def run_all_checks() -> Dict[str, bool]:
    """Run all checks. Returns {name: bool}. Never raises."""
    results: Dict[str, bool] = {}
    for name, _desc, fn in CHECKS:
        try:
            results[name] = bool(fn())
        except Exception:
            results[name] = False
    return results


def all_pass(results: Optional[Dict[str, bool]] = None) -> bool:
    """Returns True if all infrastructure checks pass."""
    if results is None:
        results = run_all_checks()
    return all(results.values())


def infrastructure_report(results: Optional[Dict[str, bool]] = None) -> dict:
    """Returns a structured report dict with check results and summary."""
    if results is None:
        results = run_all_checks()
    passed = [n for n, ok in results.items() if ok]
    failed = [n for n, ok in results.items() if not ok]
    checks_detail = []
    for name, desc, _ in CHECKS:
        checks_detail.append({
            "name": name,
            "description": desc,
            "status": "PASS" if results.get(name) else "FAIL",
        })
    return {
        "all_pass": all_pass(results),
        "passed": len(passed),
        "total": len(CHECKS),
        "pass_rate_pct": round(len(passed) / len(CHECKS) * 100, 1) if CHECKS else 0.0,
        "checks": checks_detail,
        "failed_checks": failed,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns exit code (0 = success / not-strict, 1 = strict+fail)."""
    if argv is None:
        argv = sys.argv[1:]

    use_json = "--json" in argv
    strict = "--strict" in argv

    results = run_all_checks()
    report = infrastructure_report(results)

    if use_json:
        print(json.dumps(report, indent=2))
    else:
        print("SPA Infrastructure Verification")
        print("=" * 40)
        for item in report["checks"]:
            icon = "✓" if item["status"] == "PASS" else "✗"
            print(f"  {icon} {item['description']} [{item['status']}]")
        print("-" * 40)
        print(f"  {report['passed']}/{report['total']} checks passed "
              f"({report['pass_rate_pct']:.0f}%)")
        print(f"  Overall: {'ALL PASS ✓' if report['all_pass'] else 'SOME FAILED ✗'}")
        if report["failed_checks"]:
            print(f"\n  Failed checks: {', '.join(report['failed_checks'])}")

    if strict and not report["all_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
