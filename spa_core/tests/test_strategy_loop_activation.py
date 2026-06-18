#!/usr/bin/env python3
"""Tests for ADR-033 strategy-loop activation config.

Covers ``spa_core.strategies.strategy_config`` (the fail-safe reader) and the
cycle-runner wiring (``_default_allocator`` honouring the mode). No network; all
file I/O is in a temp dir. pytest is not installed in this repo, so the tests use
``unittest`` (stdlib)::

    python3 -m unittest spa_core.tests.test_strategy_loop_activation -v
    python3 spa_core/tests/test_strategy_loop_activation.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.strategy_config import (
    DEFAULT_MODE,
    VALID_MODES,
    get_strategy_loop_mode,
    load_strategy_config,
    loop_enabled_for_allocator,
)
from spa_core.paper_trading import cycle_runner


def _write_config(data_dir: Path, payload) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "strategy_config.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestLoadStrategyConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_defaults_to_shadow(self):
        cfg = load_strategy_config(data_dir=self.dir)
        self.assertEqual(cfg["strategy_loop_mode"], DEFAULT_MODE)
        self.assertEqual(cfg["strategy_loop_mode"], "shadow")
        self.assertEqual(cfg["source"], "default_missing")

    def test_valid_shadow_mode(self):
        _write_config(self.dir, {"strategy_loop_mode": "shadow",
                                 "activated_at": "2026-06-14", "reason": "ADR-033"})
        cfg = load_strategy_config(data_dir=self.dir)
        self.assertEqual(cfg["strategy_loop_mode"], "shadow")
        self.assertEqual(cfg["activated_at"], "2026-06-14")
        self.assertEqual(cfg["reason"], "ADR-033")
        self.assertEqual(cfg["source"], "file")

    def test_valid_active_mode(self):
        _write_config(self.dir, {"strategy_loop_mode": "active"})
        self.assertEqual(get_strategy_loop_mode(data_dir=self.dir), "active")

    def test_valid_off_mode(self):
        _write_config(self.dir, {"strategy_loop_mode": "off"})
        self.assertEqual(get_strategy_loop_mode(data_dir=self.dir), "off")

    def test_mode_is_case_insensitive_and_trimmed(self):
        _write_config(self.dir, {"strategy_loop_mode": "  ACTIVE  "})
        self.assertEqual(get_strategy_loop_mode(data_dir=self.dir), "active")

    def test_unknown_mode_falls_back_to_default(self):
        _write_config(self.dir, {"strategy_loop_mode": "turbo"})
        cfg = load_strategy_config(data_dir=self.dir)
        self.assertEqual(cfg["strategy_loop_mode"], DEFAULT_MODE)
        self.assertEqual(cfg["source"], "default_invalid")

    def test_corrupt_json_falls_back_to_default(self):
        _write_config(self.dir, "{ this is not json ]")
        cfg = load_strategy_config(data_dir=self.dir)
        self.assertEqual(cfg["strategy_loop_mode"], DEFAULT_MODE)
        self.assertEqual(cfg["source"], "default_invalid")

    def test_non_dict_json_falls_back_to_default(self):
        _write_config(self.dir, ["shadow"])
        cfg = load_strategy_config(data_dir=self.dir)
        self.assertEqual(cfg["strategy_loop_mode"], DEFAULT_MODE)
        self.assertEqual(cfg["source"], "default_invalid")

    def test_missing_mode_key_falls_back_to_default(self):
        _write_config(self.dir, {"reason": "no mode here"})
        self.assertEqual(get_strategy_loop_mode(data_dir=self.dir), DEFAULT_MODE)

    def test_valid_modes_constant(self):
        self.assertEqual(VALID_MODES, ("off", "shadow", "active"))


class TestLoopEnabledForAllocator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shadow_does_not_enable_allocator_loop(self):
        _write_config(self.dir, {"strategy_loop_mode": "shadow"})
        self.assertFalse(loop_enabled_for_allocator(data_dir=self.dir))

    def test_off_does_not_enable_allocator_loop(self):
        _write_config(self.dir, {"strategy_loop_mode": "off"})
        self.assertFalse(loop_enabled_for_allocator(data_dir=self.dir))

    def test_active_enables_allocator_loop(self):
        _write_config(self.dir, {"strategy_loop_mode": "active"})
        self.assertTrue(loop_enabled_for_allocator(data_dir=self.dir))

    def test_missing_config_does_not_enable_loop(self):
        # Default is shadow → allocator loop must stay disabled (safe default).
        self.assertFalse(loop_enabled_for_allocator(data_dir=self.dir))


class TestDefaultAllocatorHonoursMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shadow_builds_allocator_with_loop_disabled(self):
        _write_config(self.dir, {"strategy_loop_mode": "shadow"})
        alloc = cycle_runner._default_allocator(self.dir)
        self.assertFalse(alloc.strategy_loop_enabled)

    def test_active_builds_allocator_with_loop_enabled(self):
        _write_config(self.dir, {"strategy_loop_mode": "active"})
        alloc = cycle_runner._default_allocator(self.dir)
        self.assertTrue(alloc.strategy_loop_enabled)

    def test_missing_config_builds_allocator_with_loop_disabled(self):
        # No config file → shadow default → loop disabled in the allocator.
        alloc = cycle_runner._default_allocator(self.dir)
        self.assertFalse(alloc.strategy_loop_enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
