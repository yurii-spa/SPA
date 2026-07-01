#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/day30_review.py — CLI entry for the RISKWIRE day-30 REVIEW pipeline (WS1.3).

Thin wrapper over ``spa_core.riskwire.day30_review`` so the review can be produced / verified from
a plain script path (launchd bash-wrapper, cron, a reviewer's shell) without a ``-m`` invocation.

    python3 scripts/day30_review.py            # print the review (read-only, no write)
    python3 scripts/day30_review.py --write    # write data/riskwire/day30_review.json + docs/DAY30_REVIEW.md
    python3 scripts/day30_review.py --verify    # re-derive review_hash, report match

Read-only / advisory / INERT re: cutover — it NEVER mutates the go-live track and moves no capital.
"""
import sys
from pathlib import Path

# make the repo root importable when run as a bare script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.riskwire.day30_review import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
