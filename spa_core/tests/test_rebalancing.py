"""
tests/test_rebalancing.py — portfolio drift-based rebalancing tests.

Covers:
  - test_no_drift_when_at_target
  - test_trim_when_overweight
  - test_add_when_underweight
  - test_should_rebalance_true_on_large_drift
  - test_should_rebalance_false_when_balanced
  - test_rebalance_actions_produced
  - test_cash_outside_bounds_triggers_rebalance

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_rebalancing.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make spa_core importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))
