"""
tests/test_retry_logic.py — retry mechanism and pipeline health tests.

Run with:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_retry_logic.py -v
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

SPA_CORE = Path(__file__).parent.parent
ROOT = SPA_CORE.parent
sys.path.insert(0, str(SPA_CORE))
