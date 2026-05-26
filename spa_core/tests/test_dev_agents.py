"""
Tests for spa_core.dev_agents — Architect and Tester agents.

These tests are fully offline (no LLM calls, no subprocess, no Telegram).
They cover:
  - SpaTester._parse_output with passing pytest output
  - SpaTester._parse_output with failing pytest output (failed_tests captured)
  - SpaArchitect._load_kanban with KANBAN.json on disk (if present)
  - SpaArchitect.promote_idea — idea moves from 'ideas' to 'backlog'
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
