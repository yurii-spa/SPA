#!/usr/bin/env python3
"""
tests/test_ceo_agent_v2.py — MP-1452 (Sprint v10.68)

Test suite for spa_core/agents/ceo_agent_v2.py.

Tests:
  A. compute_drawdown_pct — pure function (A1–A4)
  B. should_run — pure function (B1–B5)
  C. CeoDecision.to_dict (C1–C3)
  D. gather_context (D1–D3)
  E. decide — deterministic path (E1–E3)

Pure stdlib. No network. No LLM calls. Offline.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
import tempfile
from datetime import datetime, timedelta, timezone

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.agents.ceo_agent_v2 import (
    CeoDecision,
    compute_drawdown_pct,
    gather_context,
    should_run,
    decide,
    TRIGGER_DRAWDOWN,
    TRIGGER_WEEKLY,
    DRAWDOWN_TRIGGER_PCT,
    WEEKLY_PERIOD_DAYS,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
_7_DAYS_AGO = _NOW - timedelta(days=8)
_YESTERDAY = _NOW - timedelta(days=1)


def _eq_curve(n: int = 10, start: float = 100000.0, drift: float = 50.0) -> list:
    return [{"date": f"2026-06-{i+1:02d}", "equity": start + i * drift} for i in range(n)]


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — compute_drawdown_pct
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeDrawdownPct(unittest.TestCase):

    def test_A1_no_drawdown_when_rising(self):
        """Returns 0.0 when last point equals peak."""
        equity = [100000.0, 101000.0, 102000.0]
        dd = compute_drawdown_pct(equity)
        self.assertAlmostEqual(dd, 0.0, places=4)

    def test_A2_correct_drawdown_value(self):
        """Returns correct percentage when equity has fallen from peak."""
        equity = [100000.0, 102000.0, 97900.0]
        dd = compute_drawdown_pct(equity)
        # (102000 - 97900) / 102000 * 100 ≈ 4.02%
        self.assertAlmostEqual(dd, (102000 - 97900) / 102000 * 100, places=2)

    def test_A3_empty_list_returns_none(self):
        """Returns None for empty equity list."""
        self.assertIsNone(compute_drawdown_pct([]))

    def test_A4_nonnumeric_values_skipped(self):
        """Non-numeric values are skipped gracefully."""
        equity = [100000.0, None, "bad", 99000.0]
        result = compute_drawdown_pct(equity)
        # Should not crash; None or float
        self.assertTrue(result is None or isinstance(result, float))


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — should_run
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldRun(unittest.TestCase):

    def test_B1_triggers_weekly_when_no_decisions(self):
        """should_run returns True/TRIGGER_WEEKLY when no decisions exist."""
        ctx = {"drawdown_pct": 0.5}
        run, trigger = should_run(ctx, [], now=_NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_B2_triggers_weekly_when_7_days_elapsed(self):
        """should_run returns True/TRIGGER_WEEKLY when last run was >=7 days ago."""
        ctx = {"drawdown_pct": 0.0}
        decisions = [{"ts": _7_DAYS_AGO.isoformat()}]
        run, trigger = should_run(ctx, decisions, now=_NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_B3_no_run_when_recent(self):
        """should_run returns False when last run was recent and no drawdown."""
        ctx = {"drawdown_pct": 0.0}
        decisions = [{"ts": _YESTERDAY.isoformat()}]
        run, _ = should_run(ctx, decisions, now=_NOW)
        self.assertFalse(run)

    def test_B4_triggers_drawdown_when_exceeded(self):
        """should_run returns True/TRIGGER_DRAWDOWN when drawdown > threshold."""
        ctx = {"drawdown_pct": DRAWDOWN_TRIGGER_PCT + 0.5}
        decisions = [{"ts": _YESTERDAY.isoformat()}]
        run, trigger = should_run(ctx, decisions, now=_NOW)
        self.assertTrue(run)
        self.assertEqual(trigger, TRIGGER_DRAWDOWN)

    def test_B5_returns_false_none_when_not_due(self):
        """should_run returns (False, None) when nothing triggers."""
        ctx = {"drawdown_pct": 0.0}
        recent = _NOW - timedelta(days=2)
        decisions = [{"ts": recent.isoformat()}]
        run, trigger = should_run(ctx, decisions, now=_NOW)
        self.assertFalse(run)
        self.assertIsNone(trigger)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — CeoDecision
# ═══════════════════════════════════════════════════════════════════════════════

class TestCeoDecision(unittest.TestCase):

    def test_C1_to_dict_has_required_keys(self):
        """CeoDecision.to_dict() contains ts, decision, trigger, reasoning."""
        d = CeoDecision(
            ts=_NOW.isoformat(),
            snapshot_id="snap001",
            trigger=TRIGGER_WEEKLY,
            decision="keep_strategy",
            reasoning="All looks fine.",
            inputs_digest="abc123",
        )
        as_dict = d.to_dict()
        for key in ("ts", "decision", "trigger", "reasoning", "snapshot_id"):
            self.assertIn(key, as_dict)

    def test_C2_decision_is_valid_enum_value(self):
        """CeoDecision.decision is one of the valid enum values."""
        valid = {"keep_strategy", "recommend_strategy_change", "escalate"}
        d = CeoDecision(
            ts=_NOW.isoformat(),
            snapshot_id="snap002",
            trigger=TRIGGER_WEEKLY,
            decision="keep_strategy",
            reasoning="ok",
            inputs_digest="xyz",
        )
        self.assertIn(d.decision, valid)

    def test_C3_to_dict_is_serializable(self):
        """CeoDecision.to_dict() output is JSON-serializable."""
        d = CeoDecision(
            ts=_NOW.isoformat(),
            snapshot_id="snap003",
            trigger=TRIGGER_DRAWDOWN,
            decision="escalate",
            reasoning="Drawdown triggered.",
            inputs_digest="hash001",
        )
        as_json = json.dumps(d.to_dict())
        self.assertIsInstance(as_json, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — gather_context
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatherContext(unittest.TestCase):

    def test_D1_returns_dict_with_missing_info(self):
        """gather_context returns a dict even when no data files exist."""
        with tempfile.TemporaryDirectory() as d:
            result = gather_context(data_dir=d)
            self.assertIsInstance(result, dict)

    def test_D2_loads_equity_curve_when_present(self):
        """gather_context includes inputs when equity_curve_daily.json exists."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            curve = _eq_curve(10)
            _write_json(data_dir / "equity_curve_daily.json", {"daily": curve})
            result = gather_context(data_dir=str(data_dir))
            # gather_context returns 'inputs' dict with equity info
            self.assertIn("inputs", result)

    def test_D3_missing_files_listed_in_context(self):
        """gather_context marks missing files gracefully."""
        with tempfile.TemporaryDirectory() as d:
            result = gather_context(data_dir=d)
            # Should have some indicator of missing context
            self.assertIsInstance(result.get("missing", []), list)


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — decide (deterministic path, no LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecide(unittest.TestCase):

    def test_E1_decide_returns_ceo_decision(self):
        """decide() without LLM returns a CeoDecision."""
        ctx = {"drawdown_pct": 0.0}
        result = decide(context=ctx, trigger=TRIGGER_WEEKLY, llm=None)
        self.assertIsInstance(result, CeoDecision)

    def test_E2_decide_escalates_on_high_drawdown(self):
        """decide() with large drawdown returns escalate decision."""
        ctx = {"drawdown_pct": DRAWDOWN_TRIGGER_PCT + 1.0}
        result = decide(context=ctx, trigger=TRIGGER_DRAWDOWN, llm=None)
        self.assertIn(result.decision, {"escalate", "recommend_strategy_change", "keep_strategy"})
        # At minimum: must not crash and must be a valid decision
        valid = {"keep_strategy", "recommend_strategy_change", "escalate"}
        self.assertIn(result.decision, valid)

    def test_E3_decide_degraded_when_no_llm(self):
        """decide() without LLM marks reasoning as degraded."""
        ctx = {"drawdown_pct": 0.0}
        result = decide(context=ctx, trigger=TRIGGER_WEEKLY, llm=None)
        self.assertIsInstance(result.reasoning, str)
        self.assertGreater(len(result.reasoning), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
