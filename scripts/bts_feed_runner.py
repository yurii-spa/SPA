#!/usr/bin/env python3
"""
BTS Feed Runner — LaunchAgent entry point for perp_funding_feed.

Reads SPA_DATA_DIR env (defaults to data/), calls fetch_and_save, logs result.
"""
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("spa.feeds.bts.runner")


def main() -> int:
    repo_root = os.environ.get(
        "SPA_REPO_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
    sys.path.insert(0, repo_root)
    os.chdir(repo_root)

    data_dir = Path(os.environ.get("SPA_DATA_DIR", "data"))

    try:
        from spa_core.feeds.perp_funding_feed import fetch_and_save
        result = fetch_and_save(data_dir=data_dir)
        if result:
            stale = result.get("stale", True)
            n_assets = len(result.get("assets", {}))
            log.info("BTS feed: stale=%s assets=%d", stale, n_assets)
            return 0
        else:
            log.error("BTS feed: fetch_and_save returned None")
            return 1
    except Exception as exc:
        log.error("BTS feed runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
