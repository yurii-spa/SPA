#!/usr/bin/env python3
"""
Daily simulation wrapper for launchd.
Runs: simulate_day → health_check → weekly_report (Fridays only)

Usage:
    python3 scripts/run_daily_simulation.py           # full run
    python3 scripts/run_daily_simulation.py --dry-run # show what would run
    python3 scripts/run_daily_simulation.py --test    # run but skip Telegram
"""
import sys, subprocess, datetime, argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent

def run_step(name: str, cmd: list, dry_run: bool = False) -> bool:
    """Run a subprocess step. Returns True on success."""
    if dry_run:
        print(f"[DRY-RUN] Would run: {' '.join(cmd)}")
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print(f"✅ {name}: OK")
            return True
        else:
            print(f"❌ {name}: FAILED (exit {result.returncode})")
            print(result.stderr[:500] if result.stderr else "")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏱ {name}: TIMEOUT")
        return False

def is_friday() -> bool:
    return datetime.date.today().weekday() == 4

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test", action="store_true", help="Skip Telegram alerts")
    args = parser.parse_args()

    python = sys.executable
    today = datetime.date.today().isoformat()

    print(f"=== SPA Daily Simulation {today} ===")

    results = {}

    # Step 1: simulate today
    step1_cmd = [python, str(ROOT / "scripts/simulate_day.py"), "--date", today]
    results["simulate"] = run_step("simulate_day", step1_cmd, args.dry_run)

    # Step 2: health check
    health_cmd = [python, str(ROOT / "scripts/run_health_check.py")]
    if args.test:
        health_cmd.append("--test")
    results["health"] = run_step("health_check", health_cmd, args.dry_run)

    # Step 3: weekly report on Fridays
    if is_friday():
        weekly_cmd = [python, str(ROOT / "scripts/weekly_evidence_report.py")]
        results["weekly"] = run_step("weekly_report", weekly_cmd, args.dry_run)
    else:
        print("⏭ weekly_report: skipped (not Friday)")
        results["weekly"] = None

    # Summary
    failed = [k for k, v in results.items() if v is False]
    if failed:
        print(f"\n❌ Failed steps: {', '.join(failed)}")
        return 1
    print("\n✅ All steps completed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
