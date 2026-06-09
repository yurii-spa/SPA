"""
run_alerts.py — SPA-V390 CLI entry point for the email alert system.

  python3 -m spa_core.alerts.run_alerts [--dry-run] [--verbose]

Reads:
  data/golive_readiness.json
  data/adapter_orchestrator_status.json
  data/portfolio_state.json   (optional)

Runs check_alert_conditions → dispatch_alerts and prints a one-line summary:

  ALERTS 3 | CRITICAL 1 | WARNING 2 | INFO 0 | dry_run

stdlib only. Never touches execution/, feed_health/, risk agents.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .alert_config import AlertConfig
from .alert_dispatcher import dispatch_alerts
from .alert_rules import check_alert_conditions

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA = _PROJECT_ROOT / "data"

GOLIVE_PATH = _DATA / "golive_readiness.json"
ORCHESTRATOR_PATH = _DATA / "adapter_orchestrator_status.json"
PORTFOLIO_PATH = _DATA / "portfolio_state.json"


def run(dry_run: bool = False, verbose: bool = False) -> dict:
    config = AlertConfig.from_env()
    if dry_run:
        config.dry_run = True

    alerts = check_alert_conditions(
        GOLIVE_PATH, ORCHESTRATOR_PATH, PORTFOLIO_PATH
    )

    if verbose:
        print(f"config: {config.redacted()}")
        print(f"golive_path:        {GOLIVE_PATH}")
        print(f"orchestrator_path:  {ORCHESTRATOR_PATH}")
        print(f"portfolio_path:     {PORTFOLIO_PATH}")
        if not alerts:
            print("no alerts triggered")
        for a in alerts:
            print(f"  [{a.severity}] {a.title}")
            print(f"      {a.body}")

    result = dispatch_alerts(alerts, config)

    counts = result["counts"]
    mode = "dry_run" if result["dry_run"] else ("sent" if result["sent"] else "no_send")
    summary = (
        f"ALERTS {result['total']} | "
        f"CRITICAL {counts['CRITICAL']} | "
        f"WARNING {counts['WARNING']} | "
        f"INFO {counts['INFO']} | "
        f"{mode}"
    )
    print(summary)

    if verbose:
        print(f"log_path: {result['log_path']}")
        if result.get("error"):
            print(f"send error: {result['error']}")

    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA-V390 Email Alert System — evaluate rules and dispatch."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run (log only, never send email).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed alert and config info.",
    )
    args = parser.parse_args(argv)

    result = run(dry_run=args.dry_run, verbose=args.verbose)
    # Exit non-zero only on a genuine send error (not on dry-run).
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
