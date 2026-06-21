#!/usr/bin/env python3
"""
bts_monitor_runner.py — LaunchAgent runner for BTS Monitor.

Sets up logging, runs BTSMonitor.run(), then BTSExitMonitor.run().
Exit 0 always (fail-safe).
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("spa.bts_monitor_runner")


def main() -> None:
    try:
        from spa_core.monitoring.bts_monitor import BTSMonitor
        monitor = BTSMonitor(use_alert_dispatcher=True)
        result = monitor.run()
        log.info("BTS monitor: %s", result)
    except Exception as exc:
        log.error("BTS monitor runner failed: %s", exc)

    try:
        from spa_core.analytics.bts_exit_monitor import BTSExitMonitor
        exit_monitor = BTSExitMonitor()
        exit_result = exit_monitor.run()
        log.info("BTS exit monitor: %s", exit_result)
    except Exception as exc:
        log.error("BTS exit monitor runner failed: %s", exc)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("Fatal: %s", exc)
    sys.exit(0)
