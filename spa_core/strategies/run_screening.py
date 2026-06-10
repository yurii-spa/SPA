"""
spa_core.strategies.run_screening — CLI entry point for strategy pre-screening.

Sprint C / v3.91. Thin wrapper around
:func:`spa_core.strategies.backtester.run_strategy_screening`: backtests every
registered shadow strategy on a fresh synthetic APY history (30 steps by
default), prints a comparison table, and writes ``data/strategy_screening.json``.

CLI::
    python3 -m spa_core.strategies.run_screening [--steps N] [--no-write] [--verbose]

Advisory/read-only — no execution / feed_health / risk-agent imports.
"""
from __future__ import annotations

import sys

from .backtester import main

if __name__ == "__main__":
    sys.exit(main())
