#!/usr/bin/env python3
"""
scripts/day1_readiness_check.py

MP-1428 (v10.44): Day 1 readiness entry-point script.

Exit codes:
  0 — all CRITICAL checks pass (ready for Day 1)
  1 — one or more CRITICAL checks fail (blocked)

Usage:
    python3 scripts/day1_readiness_check.py
    python3 scripts/day1_readiness_check.py --markdown
"""
from __future__ import annotations

import sys
import os

# Ensure repo root is on path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.paper_day1_checklist import PaperDay1Checklist

checklist = PaperDay1Checklist(base_dir=_REPO_ROOT)

if "--markdown" in sys.argv:
    print(checklist.to_markdown())
else:
    result = checklist.run_all()
    checklist.print_report()
    sys.exit(0 if result["all_critical_pass"] else 1)
