"""Tests for spa_core/agents/ceo_agent_v2.py (MP-1472 — Atomic Batch 9).

unittest, no network, no external deps. Covers pure/deterministic functions
and the append_decision atomic-write path (migrated from _atomic_write_json
to atomic_save in MP-1472).

Run::
    python3 -m unittest spa_core.tests.test_ceo_agent_v2 -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import spa_core.agents.ceo_agent_v2 as ceo

NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


# ────────────────── compute_drawdown_pct ─────────────────────────────────────

class TestComputeDrawdownPct(unittest.TestCase):
    def test_empty_list_returns_none(self):
        self.assertIsNone(ceo.compute_drawdown_pct([]))

    def test_single_point_no_drawdown(self):
        result = ceo.compute_drawdown_pct([100_000.0])
        self.assertAlmostEqual(result, 0.0)

    def test_at_peak_gives_zero(self):
        result = ceo.compute_drawdown_pct([90_000.0, 95_000.0, 100_000.0])
        self.assertAlmostEqual(result, 0.0)

    def test_drawdown_calculated_correctly(self):
        # peak=100k, last=95k → 5%
        result = ceo.compute_drawdown_pct([100_000.0, 98_000.0, 95_000.0])
        self.assertAlmostEqual(result, 5.0, places=5)

    def test_non_numeric_points_skipped(self):
        # "abc" and None should be skipped silently
        result = ceo.compute_drawdown_pct([100_000.0, None, "abc", 95_000.0])  # type: ignore[list-item]
        self.assertAlmostEqual(result, 5.0, places=5)

    def test_bool_values_skipped(self):
        # bool is a subclass of int — must be excluded
        result = ceo.compute_drawdown_pct([True, 100_000.0, 95_000.0])
        self.assertAlmostEqual(result, 5.0, places=5)

    def test_zero_peak_returns_none(self):
        self.assertIsNone(ceo.compute_drawdown_pct([0.0, 0.0]))

    def test_drawdown_never_negative(self):
        # If last > peak (shouldn't happen) — result clamped to 0
        result = ceo.compute_drawdown_pct([90_000.0, 100_000.0])
        self.assertGreaterEqual(result, 0.0)


# ─────────────────────────── should_run ──────────────────────────────────────

class TestShouldRun(unittest.TestCase):
    def test_no_decisions_triggers_weekly(self):
        run, trigger = ceo.should_run({}, [], NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, ceo.TRIGGER_WEEKLY)

    def test_drawdown_overrides_recent_decision(self):
        # Even with a recent decision, drawdown > threshold triggers run
        recent_ts = (NOW - timedelta(days=1)).isoformat()
        decisions = [{"ts": recent_ts}]
        ctx = {"drawdown_pct": 5.0}  # above DRAWDOWN_TRIGGER_PCT=2
        run, trigger = ceo.should_run(ctx, decisions, NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, ceo.TRIGGER_DRAWDOWN)

    def test_small_drawdown_with_recent_decision_no_run(self):
        recent_ts = (NOW - timedelta(days=2)).isoformat()
        decisions = [{"ts": recent_ts}]
        ctx = {"drawdown_pct": 0.5}  # below threshold
        run, trigger = ceo.should_run(ctx, decisions, NOW)
        self.assertFalse(run)
        self.assertIsNone(trigger)

    def test_stale_decision_triggers_weekly(self):
        old_ts = (NOW - timedelta(days=8)).isoformat()
        decisions = [{"ts": old_ts}]
        run, trigger = ceo.should_run({}, decisions, NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, ceo.TRIGGER_WEEKLY)

    def test_corrupt_ts_triggers_weekly(self):
        decisions = [{"ts": "NOT-A-DATE"}]
        run, trigger = ceo.should_run({}, decisions, NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, ceo.TRIGGER_WEEKLY)


# ────────────────── _deterministic_decision ──────────────────────────────────

class TestDeterministicDecision(unittest.TestCase):
    def test_high_drawdown_escalates(self):
        # DRAWDOWN_TRIGGER_PCT=2; 3% > 2 → escalate
        decision, reasoning = ceo._deterministic_decision({"drawdown_pct": 3.0})
        self.assertEqual(decision, "escalate")
        self.assertIn("[degraded=true]", reasoning)

    def test_low_drawdown_keeps_strategy(self):
        decision, reasoning = ceo._deterministic_decision({"drawdown_pct": 0.5})
        self.assertEqual(decision, "keep_strategy")
        self.assertIn("[degraded=true]", reasoning)

    def test_no_drawdown_data_keeps_strategy(self):
        decision, reasoning = ceo._deterministic_decision({})
        self.assertEqual(decision, "keep_strategy")

    def test_missing_inputs_mentioned_in_reasoning(self):
        ctx = {"drawdown_pct": 0.0, "missing": ["equity", "regime"]}
        _, reasoning = ceo._deterministic_decision(ctx)
        self.assertIn("equity", reasoning)


# ────────────────── _parse_llm_response ──────────────────────────────────────

class TestParseLlmResponse(unittest.TestCase):
    def test_valid_json_string(self):
        resp = json.dumps({"decision": "keep_strategy", "reasoning": "all good"})
        result = ceo._parse_llm_response(resp)
        self.assertIsNotNone(result)
        decision, reasoning = result
        self.assertEqual(decision, "keep_strategy")

    def test_valid_dict_input(self):
        resp = {"decision": "escalate", "reasoning": "drawdown"}
        result = ceo._parse_llm_response(resp)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "escalate")

    def test_invalid_decision_returns_none(self):
        resp = {"decision": "INVALID_DECISION", "reasoning": "x"}
        self.assertIsNone(ceo._parse_llm_response(resp))

    def test_garbage_string_returns_none(self):
        self.assertIsNone(ceo._parse_llm_response("not json at all"))

    def test_missing_decision_key_returns_none(self):
        self.assertIsNone(ceo._parse_llm_response({"reasoning": "ok"}))


# ──────────── append_decision — atomic write (MP-1472) ───────────────────────

class TestAppendDecisionAtomicWrite(unittest.TestCase):
    def _make_decision(self, decision: str = "keep_strategy") -> dict:
        return {
            "ts": NOW.isoformat(),
            "trigger": ceo.TRIGGER_WEEKLY,
            "decision": decision,
            "reasoning": "[degraded=true] test",
            "inputs_digest": "abc123",
            "snapshot_id": "snap001",
            "advisory_only": True,
        }

    def test_creates_file_on_first_write(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ceo_decisions.json"
            dec = self._make_decision()
            ceo.append_decision(dec, path=str(path))
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertIn("decisions", data)
            self.assertEqual(len(data["decisions"]), 1)

    def test_second_write_appends(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ceo_decisions.json"
            ceo.append_decision(self._make_decision("keep_strategy"), path=str(path))
            ceo.append_decision(self._make_decision("escalate"), path=str(path))
            data = json.loads(path.read_text())
            self.assertEqual(len(data["decisions"]), 2)
            self.assertEqual(data["decisions"][1]["decision"], "escalate")

    def test_no_leftover_tmp_files(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ceo_decisions.json"
            ceo.append_decision(self._make_decision(), path=str(path))
            leftovers = [f for f in os.listdir(td) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_schema_version_is_integer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ceo_decisions.json"
            ceo.append_decision(self._make_decision(), path=str(path))
            data = json.loads(path.read_text())
            self.assertIsInstance(data.get("schema_version"), int)

    def test_updated_at_present(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ceo_decisions.json"
            ceo.append_decision(self._make_decision(), path=str(path))
            data = json.loads(path.read_text())
            self.assertIn("updated_at", data)


if __name__ == "__main__":
    unittest.main()
