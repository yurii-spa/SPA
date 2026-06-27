#!/usr/bin/env python3
"""scripts/pre_cutover_gate.py — CLI entry-point for the PRE-CUTOVER READINESS GATE.

Thin wrapper over ``spa_core.paper_trading.pre_cutover_gate``. Drives every
money-path defense against an ephemeral SANDBOX and asserts each one fires.

INERT / sandbox-only / never moves capital / never imports execution/.

Exit codes:
    0 — EVERY defense demonstrably fired (all assertions pass).
    1 — one or more defenses did NOT fire (the report names the failing gate(s)).

Usage:
    python3 scripts/pre_cutover_gate.py
    python3 scripts/pre_cutover_gate.py --data-dir /tmp/spa_sandbox
    python3 scripts/pre_cutover_gate.py --json-only
"""
from __future__ import annotations

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.paper_trading.pre_cutover_gate import main

if __name__ == "__main__":
    sys.exit(main())
