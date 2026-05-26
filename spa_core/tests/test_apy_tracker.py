"""
Tests for APYTracker — 6 tests covering snapshot recording,
trend calculation, pruning, and weighted portfolio APY.
"""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import sys
import or

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.apy_tracker import APYTracker
