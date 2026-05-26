"""
Tests for concurrent pool fetching and file-based caching in DeFiLlamaFetcher.

Covers:
  - test_concurrent_fetch_returns_same_as_sequential
  - test_concurrent_fetch_uses_multiple_threads
  - test_cache_hit_skips_network
  - test_cache_miss_on_expired
  - test_perf_timing_logged

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_concurrent_fetch.py -v
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Make spa_core importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))
