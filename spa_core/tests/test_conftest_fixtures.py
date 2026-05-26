"""
tests/test_conftest_fixtures.py — validates that conftest.py fixtures produce
correct, well-typed synthetic data. These are smoke tests for the shared fixture
layer itself, not for production logic.

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_conftest_fixtures.py -v
"""

from __future__ import annotations


# ── Pool fixtures ─────────────────────────────────────────────────────────
