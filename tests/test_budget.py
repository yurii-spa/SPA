#!/usr/bin/env python3
"""
tests/test_budget.py — MP-1452 (Sprint v10.68)

Test suite for spa_core/agent_runtime/budget.py (TokenBudgetTracker).

Tests:
  A. Atomic migration — _atomic_write_json uses atomic_save (A1–A3)
  B. TokenBudgetTracker instantiation (B1–B3)
  C. start_run & charge (C1–C5)
  D. Daily reset (D1–D3)
  E. Persistence round-trip (E1–E4)

Pure stdlib. No network. Offline.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
import tempfile
from datetime import datetime, timezone

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.agent_runtime.budget import (
    TokenBudgetTracker,
    _atomic_write_json,
    SCHEMA_VERSION,
)
from spa_core.agent_runtime.mandate import AgentMandate


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_mandate(name: str = "test_agent", daily: int = 1000, per_run: int = 200):
    return AgentMandate(
        name=name,
        role="analyst",
        schedule="weekly",
        token_budget_per_run=per_run,
        token_budget_daily=daily,
    )


def _tracker(tmp: pathlib.Path, now_fn=None, extra_mandates=None):
    mandates = {"test_agent": _make_mandate()}
    if extra_mandates:
        mandates.update(extra_mandates)
    usage_path = tmp / "agent_token_usage.json"
    kwargs = {"mandates": mandates, "usage_path": str(usage_path)}
    if now_fn:
        kwargs["now_fn"] = now_fn
    return TokenBudgetTracker(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Atomic migration
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_A1_atomic_save_in_budget_after_migration(self):
        """budget.py imports atomic_save after migration (MP-1452)."""
        src = (_REPO / "spa_core" / "agent_runtime" / "budget.py").read_text(encoding="utf-8")
        self.assertIn("atomic_save", src,
                      "_atomic_write_json should delegate to atomic_save")

    def test_A2_atomic_write_json_writes_valid_file(self):
        """_atomic_write_json writes a valid JSON file atomically."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "out.json"
            _atomic_write_json({"schema_version": 1, "agents": {}}, p)
            self.assertTrue(p.exists())
            data = json.loads(p.read_text())
            self.assertEqual(data["schema_version"], 1)

    def test_A3_no_tmp_files_after_write(self):
        """_atomic_write_json leaves no .tmp files."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "out.json"
            _atomic_write_json({"x": 1}, p)
            tmp_files = list(pathlib.Path(d).glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — Instantiation
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_B1_instantiates_with_mandates(self):
        """TokenBudgetTracker can be instantiated with a mandate dict."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            self.assertIsNotNone(t)

    def test_B2_usage_path_created_after_persist(self):
        """Usage file is created after first start_run."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            t = _tracker(tmp)
            t.start_run("test_agent")
            self.assertTrue((tmp / "agent_token_usage.json").exists())

    def test_B3_schema_version_correct(self):
        """SCHEMA_VERSION constant equals 1."""
        self.assertEqual(SCHEMA_VERSION, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — start_run & charge
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartRunAndCharge(unittest.TestCase):

    def test_C1_charge_within_budget_ok(self):
        """charge() within budget returns (True, 'ok')."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            t.start_run("test_agent")
            ok, reason = t.charge("test_agent", 50)
            self.assertTrue(ok)
            self.assertEqual(reason, "ok")

    def test_C2_charge_unknown_agent_rejected(self):
        """charge() for unknown agent returns (False, ...)."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            ok, reason = t.charge("no_such_agent", 10)
            self.assertFalse(ok)
            self.assertIn("no mandate", reason)

    def test_C3_charge_exceeding_per_run_rejected(self):
        """charge() exceeding per_run_token_budget returns (False, ...)."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            t.start_run("test_agent")
            ok, _ = t.charge("test_agent", 200)   # per_run=200, exactly at limit
            # Either ok=True or False depending on >= vs > logic, but massive over-limit:
            t2 = _tracker(pathlib.Path(d))
            t2.start_run("test_agent")
            ok2, _ = t2.charge("test_agent", 99999)  # way over per_run
            self.assertFalse(ok2)

    def test_C4_invalid_token_amount_rejected(self):
        """charge() with negative token count returns (False, ...)."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            t.start_run("test_agent")
            ok, reason = t.charge("test_agent", -5)
            self.assertFalse(ok)

    def test_C5_start_run_resets_per_run_counter(self):
        """Calling start_run twice resets the run counter."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            t.start_run("test_agent")
            t.charge("test_agent", 100)
            t.start_run("test_agent")  # resets run_used to 0
            ok, _ = t.charge("test_agent", 100)  # should be ok now
            self.assertTrue(ok)


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — Daily reset
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailyReset(unittest.TestCase):

    def test_D1_daily_reset_on_date_change(self):
        """Daily counters reset when UTC date changes."""
        with tempfile.TemporaryDirectory() as d:
            day1 = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
            day2 = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
            t = _tracker(pathlib.Path(d), now_fn=lambda: day1)
            t.start_run("test_agent")
            t.charge("test_agent", 50)

            # Simulate date change
            t._now_fn = lambda: day2
            t._roll_date()
            st = t._agent_state("test_agent")
            self.assertEqual(st["daily_used"], 0)

    def test_D2_state_file_updated_after_reset(self):
        """State file reflects new date after daily reset."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            day1 = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
            day2 = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
            t = _tracker(tmp, now_fn=lambda: day1)
            t.start_run("test_agent")
            t._now_fn = lambda: day2
            t._roll_date()
            state = json.loads((tmp / "agent_token_usage.json").read_text())
            self.assertEqual(state["date"], "2026-06-11")

    def test_D3_no_reset_on_same_day(self):
        """Daily counters are NOT reset when date hasn't changed."""
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
            t = _tracker(pathlib.Path(d), now_fn=lambda: now)
            t.start_run("test_agent")
            t.charge("test_agent", 50)
            t._roll_date()  # same date, no reset
            st = t._agent_state("test_agent")
            self.assertGreater(st["daily_used"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — Persistence round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistence(unittest.TestCase):

    def test_E1_state_persisted_after_charge(self):
        """State is written to disk after charge."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            t = _tracker(tmp)
            t.start_run("test_agent")
            t.charge("test_agent", 30)
            state = json.loads((tmp / "agent_token_usage.json").read_text())
            self.assertIn("agents", state)

    def test_E2_state_loaded_on_new_instance(self):
        """New TokenBudgetTracker loads existing state from file."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            t1 = _tracker(tmp)
            t1.start_run("test_agent")
            t1.charge("test_agent", 75)

            t2 = _tracker(tmp)
            usage = t2.usage("test_agent")
            self.assertEqual(usage["daily_used"], 75)

    def test_E3_usage_file_is_valid_json(self):
        """Usage file is valid JSON after tracker operations."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            t = _tracker(tmp)
            t.start_run("test_agent")
            t.charge("test_agent", 10)
            data = json.loads((tmp / "agent_token_usage.json").read_text())
            self.assertIsInstance(data, dict)
            self.assertIn("schema_version", data)

    def test_E4_usage_returns_dict(self):
        """usage() returns a dict with run_used and daily_used."""
        with tempfile.TemporaryDirectory() as d:
            t = _tracker(pathlib.Path(d))
            t.start_run("test_agent")
            t.charge("test_agent", 20)
            usage = t.usage("test_agent")
            self.assertIsInstance(usage, dict)
            self.assertIn("daily_used", usage)


if __name__ == "__main__":
    unittest.main(verbosity=2)
