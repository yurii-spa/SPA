#!/usr/bin/env python3
"""Tests for MP-729 YieldOptimizationSummary.

Run:
    python3 -m unittest spa_core.tests.test_yield_optimization_summary -v
    python3 spa_core/tests/test_yield_optimization_summary.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make spa_core importable from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.yield_optimization_summary import (
    AnalyticsSignal,
    OptimizationSummary,
    build_summary,
    compute_health_score,
    create_signal,
    load_history,
    merge_summaries,
    save_results,
    top_opportunities,
    top_risks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ISO = "2026-06-13T08:00:00+00:00"

_FULL_METRICS = {
    "total_apy": 10.0,
    "total_risk": 20.0,
    "diversification": 60.0,
    "sustainability": 70.0,
}


def _sig(
    module: str = "test_module",
    signal_type: str = "INFO",
    priority: int = 3,
    title: str = "Test signal",
    detail: str = "Detail text",
    action: str = "Do something",
    impact: float = 1.0,
) -> AnalyticsSignal:
    return create_signal(module, signal_type, priority, title, detail, action, impact)


def _make_summary(
    signals=None,
    metrics=None,
    pid: str = "portfolio_001",
) -> OptimizationSummary:
    return build_summary(pid, signals or [], metrics or _FULL_METRICS, _ISO)


# ---------------------------------------------------------------------------
# 1. create_signal
# ---------------------------------------------------------------------------

class TestCreateSignal(unittest.TestCase):

    def test_all_fields_set(self):
        s = create_signal("mod", "RISK", 1, "title", "detail", "action", 2.5)
        self.assertEqual(s.module, "mod")
        self.assertEqual(s.signal_type, "RISK")
        self.assertEqual(s.priority, 1)
        self.assertEqual(s.title, "title")
        self.assertEqual(s.detail, "detail")
        self.assertEqual(s.recommended_action, "action")
        self.assertAlmostEqual(s.estimated_impact_pct, 2.5)

    def test_returns_analytics_signal(self):
        s = create_signal("m", "INFO", 3, "t", "d", "a", 0.0)
        self.assertIsInstance(s, AnalyticsSignal)

    def test_priority_stored_as_int(self):
        s = create_signal("m", "INFO", 2, "t", "d", "a", 1.0)
        self.assertIsInstance(s.priority, int)
        self.assertEqual(s.priority, 2)

    def test_impact_stored_as_float(self):
        s = create_signal("m", "OPPORTUNITY", 1, "t", "d", "a", 3)
        self.assertIsInstance(s.estimated_impact_pct, float)

    def test_signal_type_opportunity(self):
        s = create_signal("m", "OPPORTUNITY", 2, "Yield increase", "d", "a", 5.0)
        self.assertEqual(s.signal_type, "OPPORTUNITY")

    def test_signal_type_risk(self):
        s = create_signal("m", "RISK", 1, "High drawdown", "d", "a", -2.0)
        self.assertEqual(s.signal_type, "RISK")

    def test_signal_type_action(self):
        s = create_signal("m", "ACTION", 2, "Rebalance", "d", "a", 1.0)
        self.assertEqual(s.signal_type, "ACTION")

    def test_signal_type_info(self):
        s = create_signal("m", "INFO", 5, "Status OK", "d", "a", 0.0)
        self.assertEqual(s.signal_type, "INFO")


# ---------------------------------------------------------------------------
# 2. compute_health_score
# ---------------------------------------------------------------------------

class TestComputeHealthScore(unittest.TestCase):

    def test_max_inputs_give_100(self):
        metrics = {
            "total_apy": 20.0,
            "total_risk": 0.0,
            "diversification": 100.0,
            "sustainability": 100.0,
        }
        score = compute_health_score(metrics)
        self.assertAlmostEqual(score, 100.0, places=9)

    def test_min_inputs_give_0(self):
        metrics = {
            "total_apy": 0.0,
            "total_risk": 100.0,
            "diversification": 0.0,
            "sustainability": 0.0,
        }
        score = compute_health_score(metrics)
        self.assertAlmostEqual(score, 0.0, places=9)

    def test_formula_components(self):
        # total_apy=10 → 10/20*25=12.5
        # total_risk=50 → (100-50)/100*30=15
        # diversification=80 → 80/100*25=20
        # sustainability=60 → 60/100*20=12
        # total = 59.5
        metrics = {
            "total_apy": 10.0,
            "total_risk": 50.0,
            "diversification": 80.0,
            "sustainability": 60.0,
        }
        score = compute_health_score(metrics)
        self.assertAlmostEqual(score, 59.5, places=9)

    def test_capped_at_100(self):
        metrics = {
            "total_apy": 100.0,   # 100/20*25=125 alone already>100
            "total_risk": 0.0,
            "diversification": 100.0,
            "sustainability": 100.0,
        }
        score = compute_health_score(metrics)
        self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        score = compute_health_score(_FULL_METRICS)
        self.assertIsInstance(score, float)

    def test_known_calculation(self):
        # total_apy=20 →25; risk=0→30; div=100→25; sust=100→20; total=100
        metrics = {
            "total_apy": 20.0,
            "total_risk": 0.0,
            "diversification": 100.0,
            "sustainability": 100.0,
        }
        self.assertAlmostEqual(compute_health_score(metrics), 100.0)

    def test_partial_metrics_missing_fields_default_to_zero(self):
        metrics = {"total_apy": 20.0}
        # total_apy=20 → 25; total_risk missing → defaults 0 → (100-0)/100*30=30;
        # diversification missing → 0; sustainability missing → 0 → total = 55
        score = compute_health_score(metrics)
        self.assertAlmostEqual(score, 55.0, places=9)

    def test_empty_metrics_gives_30(self):
        # total_risk missing → defaults to 0 → (100-0)/100*30 = 30; rest 0
        score = compute_health_score({})
        self.assertAlmostEqual(score, 30.0, places=9)

    def test_floor_at_zero(self):
        metrics = {
            "total_apy": 0.0,
            "total_risk": 200.0,   # extreme → (100-200)/100*30 = -30
            "diversification": 0.0,
            "sustainability": 0.0,
        }
        score = compute_health_score(metrics)
        self.assertGreaterEqual(score, 0.0)


# ---------------------------------------------------------------------------
# 3. health_label
# ---------------------------------------------------------------------------

class TestHealthLabel(unittest.TestCase):

    def test_excellent_at_80(self):
        metrics = {"total_apy": 20.0, "total_risk": 0.0, "diversification": 80.0, "sustainability": 100.0}
        # 25+30+20+20=95 >= 80
        summary = _make_summary(metrics=metrics)
        self.assertEqual(summary.health_label, "EXCELLENT")

    def test_excellent_at_100(self):
        metrics = {"total_apy": 20.0, "total_risk": 0.0, "diversification": 100.0, "sustainability": 100.0}
        summary = _make_summary(metrics=metrics)
        self.assertEqual(summary.health_label, "EXCELLENT")

    def test_good_at_60(self):
        metrics = {"total_apy": 12.0, "total_risk": 40.0, "diversification": 40.0, "sustainability": 40.0}
        # 12/20*25=15; 60/100*30=18; 40/100*25=10; 40/100*20=8 → 51 (FAIR)
        # adjust: apy=16 → 20; risk=0 → 30; div=40 → 10; sust=20 → 4 → 64 (GOOD)
        metrics2 = {"total_apy": 16.0, "total_risk": 0.0, "diversification": 40.0, "sustainability": 20.0}
        summary = _make_summary(metrics=metrics2)
        score = compute_health_score(metrics2)
        self.assertGreaterEqual(score, 60.0)
        self.assertLess(score, 80.0)
        self.assertEqual(summary.health_label, "GOOD")

    def test_fair_label(self):
        metrics = {"total_apy": 4.0, "total_risk": 60.0, "diversification": 20.0, "sustainability": 20.0}
        # 4/20*25=5; 40/100*30=12; 20/100*25=5; 20/100*20=4 → 26 (POOR)
        # adjust for FAIR (40-79):
        metrics2 = {"total_apy": 10.0, "total_risk": 40.0, "diversification": 40.0, "sustainability": 30.0}
        # 10/20*25=12.5; 60/100*30=18; 40/100*25=10; 30/100*20=6 → 46.5
        summary = _make_summary(metrics=metrics2)
        score = compute_health_score(metrics2)
        self.assertGreaterEqual(score, 40.0)
        self.assertLess(score, 60.0)
        self.assertEqual(summary.health_label, "FAIR")

    def test_poor_label(self):
        metrics = {
            "total_apy": 0.0,
            "total_risk": 100.0,
            "diversification": 0.0,
            "sustainability": 0.0,
        }
        summary = _make_summary(metrics=metrics)
        self.assertEqual(summary.health_label, "POOR")


# ---------------------------------------------------------------------------
# 4. build_summary — signal bucketing
# ---------------------------------------------------------------------------

class TestBuildSummary(unittest.TestCase):

    def test_immediate_actions_priority_1(self):
        signals = [
            _sig(priority=1, title="Alert"),
            _sig(priority=2, title="Task"),
        ]
        summary = _make_summary(signals=signals)
        self.assertEqual(len(summary.immediate_actions), 1)
        self.assertEqual(summary.immediate_actions[0].title, "Alert")

    def test_short_term_priority_2_and_3(self):
        signals = [
            _sig(priority=2, title="P2"),
            _sig(priority=3, title="P3"),
            _sig(priority=4, title="P4"),
        ]
        summary = _make_summary(signals=signals)
        titles = [s.title for s in summary.short_term_actions]
        self.assertIn("P2", titles)
        self.assertIn("P3", titles)
        self.assertNotIn("P4", titles)

    def test_monitor_items_priority_4_and_5(self):
        signals = [
            _sig(priority=3, title="P3"),
            _sig(priority=4, title="P4"),
            _sig(priority=5, title="P5"),
        ]
        summary = _make_summary(signals=signals)
        titles = [s.title for s in summary.monitor_items]
        self.assertIn("P4", titles)
        self.assertIn("P5", titles)
        self.assertNotIn("P3", titles)

    def test_no_signals_gives_empty_buckets(self):
        summary = _make_summary(signals=[])
        self.assertEqual(summary.immediate_actions, [])
        self.assertEqual(summary.short_term_actions, [])
        self.assertEqual(summary.monitor_items, [])

    def test_signals_sorted_by_priority(self):
        signals = [
            _sig(priority=5, title="Low"),
            _sig(priority=1, title="High"),
            _sig(priority=3, title="Mid"),
        ]
        summary = _make_summary(signals=signals)
        priorities = [s.priority for s in summary.signals]
        self.assertEqual(priorities, sorted(priorities))

    def test_portfolio_id_preserved(self):
        summary = build_summary("myportfolio", [], _FULL_METRICS, _ISO)
        self.assertEqual(summary.portfolio_id, "myportfolio")

    def test_generated_at_preserved(self):
        summary = build_summary("p1", [], _FULL_METRICS, _ISO)
        self.assertEqual(summary.generated_at_iso, _ISO)

    def test_overall_health_score_computed(self):
        summary = _make_summary(metrics=_FULL_METRICS)
        expected = compute_health_score(_FULL_METRICS)
        self.assertAlmostEqual(summary.overall_health_score, expected)

    def test_health_label_set(self):
        summary = _make_summary()
        self.assertIn(summary.health_label, ("EXCELLENT", "GOOD", "FAIR", "POOR"))

    def test_summary_metrics_preserved(self):
        summary = _make_summary(metrics=_FULL_METRICS)
        self.assertEqual(summary.summary_metrics, _FULL_METRICS)

    def test_all_signals_in_result(self):
        signals = [_sig(title=f"S{i}", priority=(i % 5) + 1) for i in range(10)]
        summary = _make_summary(signals=signals)
        self.assertEqual(len(summary.signals), 10)

    def test_all_priorities_bucketed(self):
        signals = [_sig(priority=p) for p in [1, 2, 3, 4, 5]]
        summary = _make_summary(signals=signals)
        self.assertEqual(len(summary.immediate_actions), 1)
        self.assertEqual(len(summary.short_term_actions), 2)
        self.assertEqual(len(summary.monitor_items), 2)


# ---------------------------------------------------------------------------
# 5. executive_summary
# ---------------------------------------------------------------------------

class TestExecutiveSummary(unittest.TestCase):

    def test_contains_immediate_count(self):
        signals = [_sig(priority=1, title="A"), _sig(priority=1, title="B")]
        summary = _make_summary(signals=signals)
        self.assertIn("2", summary.executive_summary)

    def test_contains_health_label(self):
        summary = _make_summary()
        self.assertIn(summary.health_label, summary.executive_summary)

    def test_contains_top_priority_title(self):
        signals = [_sig(priority=1, title="UrgentFix")]
        summary = _make_summary(signals=signals)
        self.assertIn("UrgentFix", summary.executive_summary)

    def test_no_immediate_actions_says_so(self):
        summary = _make_summary(signals=[])
        self.assertIn("No immediate actions", summary.executive_summary)

    def test_contains_short_term_count(self):
        signals = [
            _sig(priority=2, title="P2a"),
            _sig(priority=3, title="P3a"),
        ]
        summary = _make_summary(signals=signals)
        self.assertIn("2", summary.executive_summary)

    def test_health_score_in_summary(self):
        summary = _make_summary()
        # Score should appear in format e.g. "42/100"
        score_str = f"{summary.overall_health_score:.0f}/100"
        self.assertIn(score_str, summary.executive_summary)

    def test_executive_summary_is_string(self):
        summary = _make_summary()
        self.assertIsInstance(summary.executive_summary, str)
        self.assertGreater(len(summary.executive_summary), 10)


# ---------------------------------------------------------------------------
# 6. merge_summaries
# ---------------------------------------------------------------------------

class TestMergeSummaries(unittest.TestCase):

    def test_deduplication_by_title(self):
        s1 = _make_summary(signals=[_sig(title="Alpha"), _sig(title="Beta")])
        s2 = _make_summary(signals=[_sig(title="Alpha"), _sig(title="Gamma")])
        merged = merge_summaries([s1, s2])
        titles = [s.title for s in merged]
        self.assertEqual(titles.count("Alpha"), 1)

    def test_keeps_first_occurrence(self):
        sig1 = create_signal("m1", "RISK", 1, "DupTitle", "first", "a", 5.0)
        sig2 = create_signal("m2", "INFO", 5, "DupTitle", "second", "b", 1.0)
        s1 = build_summary("p", [sig1], _FULL_METRICS, _ISO)
        s2 = build_summary("p", [sig2], _FULL_METRICS, _ISO)
        merged = merge_summaries([s1, s2])
        dup = next(s for s in merged if s.title == "DupTitle")
        self.assertEqual(dup.module, "m1")

    def test_combined_count_correct(self):
        s1 = _make_summary(signals=[_sig(title="A"), _sig(title="B")])
        s2 = _make_summary(signals=[_sig(title="C"), _sig(title="D")])
        merged = merge_summaries([s1, s2])
        self.assertEqual(len(merged), 4)

    def test_deduplication_combined_count(self):
        s1 = _make_summary(signals=[_sig(title="A"), _sig(title="B")])
        s2 = _make_summary(signals=[_sig(title="B"), _sig(title="C")])
        merged = merge_summaries([s1, s2])
        self.assertEqual(len(merged), 3)

    def test_preserves_all_unique(self):
        s1 = _make_summary(signals=[_sig(title="X")])
        s2 = _make_summary(signals=[_sig(title="Y")])
        s3 = _make_summary(signals=[_sig(title="Z")])
        merged = merge_summaries([s1, s2, s3])
        titles = {s.title for s in merged}
        self.assertEqual(titles, {"X", "Y", "Z"})

    def test_empty_summaries(self):
        merged = merge_summaries([])
        self.assertEqual(merged, [])

    def test_single_summary(self):
        s = _make_summary(signals=[_sig(title="Solo")])
        merged = merge_summaries([s])
        self.assertEqual(len(merged), 1)

    def test_merge_returns_list(self):
        merged = merge_summaries([_make_summary()])
        self.assertIsInstance(merged, list)

    def test_merge_preserves_priority_order_from_source(self):
        signals = [
            _sig(priority=1, title="P1"),
            _sig(priority=5, title="P5"),
        ]
        s = _make_summary(signals=signals)
        merged = merge_summaries([s])
        # The summary sorts signals by priority, so merged should be in priority order
        priorities = [sig.priority for sig in merged]
        self.assertEqual(priorities, sorted(priorities))


# ---------------------------------------------------------------------------
# 7. top_opportunities
# ---------------------------------------------------------------------------

class TestTopOpportunities(unittest.TestCase):

    def test_sorted_by_impact_desc(self):
        signals = [
            create_signal("m", "OPPORTUNITY", 3, "Low", "d", "a", 2.0),
            create_signal("m", "OPPORTUNITY", 3, "High", "d", "a", 8.0),
            create_signal("m", "OPPORTUNITY", 3, "Mid", "d", "a", 5.0),
        ]
        summary = _make_summary(signals=signals)
        opps = top_opportunities(summary, 3)
        impacts = [o.estimated_impact_pct for o in opps]
        self.assertEqual(impacts, [8.0, 5.0, 2.0])

    def test_limits_to_n(self):
        signals = [
            create_signal("m", "OPPORTUNITY", 3, f"Opp{i}", "d", "a", float(i))
            for i in range(10)
        ]
        summary = _make_summary(signals=signals)
        opps = top_opportunities(summary, 3)
        self.assertEqual(len(opps), 3)

    def test_only_opportunity_type_returned(self):
        signals = [
            create_signal("m", "OPPORTUNITY", 3, "Good", "d", "a", 5.0),
            create_signal("m", "RISK", 1, "Bad", "d", "a", 10.0),  # higher impact but RISK
        ]
        summary = _make_summary(signals=signals)
        opps = top_opportunities(summary, 5)
        for o in opps:
            self.assertEqual(o.signal_type, "OPPORTUNITY")

    def test_empty_when_no_opportunities(self):
        signals = [create_signal("m", "RISK", 1, "R", "d", "a", 5.0)]
        summary = _make_summary(signals=signals)
        self.assertEqual(top_opportunities(summary, 5), [])

    def test_n_larger_than_available(self):
        signals = [create_signal("m", "OPPORTUNITY", 3, "O", "d", "a", 5.0)]
        summary = _make_summary(signals=signals)
        opps = top_opportunities(summary, 100)
        self.assertEqual(len(opps), 1)

    def test_top_n_gives_highest_impact(self):
        signals = [
            create_signal("m", "OPPORTUNITY", 3, f"O{i}", "d", "a", float(i))
            for i in range(10)
        ]
        summary = _make_summary(signals=signals)
        opps = top_opportunities(summary, 3)
        self.assertAlmostEqual(opps[0].estimated_impact_pct, 9.0)
        self.assertAlmostEqual(opps[1].estimated_impact_pct, 8.0)
        self.assertAlmostEqual(opps[2].estimated_impact_pct, 7.0)


# ---------------------------------------------------------------------------
# 8. top_risks
# ---------------------------------------------------------------------------

class TestTopRisks(unittest.TestCase):

    def test_sorted_by_priority_asc(self):
        signals = [
            create_signal("m", "RISK", 3, "P3", "d", "a", 1.0),
            create_signal("m", "RISK", 1, "P1", "d", "a", 1.0),
            create_signal("m", "RISK", 2, "P2", "d", "a", 1.0),
        ]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 3)
        priorities = [r.priority for r in risks]
        self.assertEqual(priorities, [1, 2, 3])

    def test_secondary_sort_by_impact_desc(self):
        signals = [
            create_signal("m", "RISK", 1, "P1Low", "d", "a", 1.0),
            create_signal("m", "RISK", 1, "P1High", "d", "a", 9.0),
        ]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 2)
        self.assertEqual(risks[0].title, "P1High")  # same priority, higher impact first

    def test_only_risk_type_returned(self):
        signals = [
            create_signal("m", "RISK", 1, "Risk1", "d", "a", 5.0),
            create_signal("m", "OPPORTUNITY", 1, "Opp1", "d", "a", 9.0),
        ]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 5)
        for r in risks:
            self.assertEqual(r.signal_type, "RISK")

    def test_limits_to_n(self):
        signals = [
            create_signal("m", "RISK", i % 3 + 1, f"R{i}", "d", "a", float(i))
            for i in range(10)
        ]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 3)
        self.assertEqual(len(risks), 3)

    def test_empty_when_no_risks(self):
        signals = [create_signal("m", "OPPORTUNITY", 1, "O", "d", "a", 5.0)]
        summary = _make_summary(signals=signals)
        self.assertEqual(top_risks(summary, 5), [])

    def test_priority_1_before_priority_2(self):
        signals = [
            create_signal("m", "RISK", 2, "P2", "d", "a", 100.0),
            create_signal("m", "RISK", 1, "P1", "d", "a", 1.0),
        ]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 2)
        self.assertEqual(risks[0].priority, 1)
        self.assertEqual(risks[1].priority, 2)

    def test_n_larger_than_available(self):
        signals = [create_signal("m", "RISK", 1, "R", "d", "a", 5.0)]
        summary = _make_summary(signals=signals)
        risks = top_risks(summary, 100)
        self.assertEqual(len(risks), 1)


# ---------------------------------------------------------------------------
# 9. save / load
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_save_creates_file(self):
        summary = _make_summary()
        path = save_results(summary, self._tmp)
        self.assertTrue(Path(path).exists())

    def test_load_history_empty_before_save(self):
        history = load_history(self._tmp)
        self.assertEqual(history, [])

    def test_save_load_round_trip(self):
        summary = _make_summary(pid="test_portfolio")
        save_results(summary, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["portfolio_id"], "test_portfolio")

    def test_save_load_preserves_health_label(self):
        summary = _make_summary()
        save_results(summary, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(history[0]["health_label"], summary.health_label)

    def test_save_sets_saved_to(self):
        summary = _make_summary()
        path = save_results(summary, self._tmp)
        self.assertEqual(summary.saved_to, path)

    def test_save_multiple(self):
        for i in range(3):
            summary = _make_summary(pid=f"p{i}")
            save_results(summary, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 3)

    def test_load_history_returns_list(self):
        history = load_history(self._tmp)
        self.assertIsInstance(history, list)


# ---------------------------------------------------------------------------
# 10. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_ring_buffer_cap_at_100(self):
        for i in range(105):
            summary = _make_summary(pid=f"p{i}")
            save_results(summary, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            summary = _make_summary(pid=f"p{i}")
            save_results(summary, self._tmp)
        history = load_history(self._tmp)
        last_pid = history[-1]["portfolio_id"]
        self.assertEqual(last_pid, "p104")

    def test_ring_buffer_drops_oldest(self):
        for i in range(105):
            summary = _make_summary(pid=f"p{i}")
            save_results(summary, self._tmp)
        history = load_history(self._tmp)
        pids = [h["portfolio_id"] for h in history]
        self.assertNotIn("p0", pids)
        self.assertNotIn("p4", pids)
        self.assertIn("p104", pids)


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_no_signals_empty_buckets(self):
        summary = _make_summary(signals=[])
        self.assertEqual(summary.immediate_actions, [])
        self.assertEqual(summary.short_term_actions, [])
        self.assertEqual(summary.monitor_items, [])

    def test_no_signals_health_from_metrics(self):
        metrics = {"total_apy": 20.0, "total_risk": 0.0, "diversification": 100.0, "sustainability": 100.0}
        summary = build_summary("p", [], metrics, _ISO)
        self.assertAlmostEqual(summary.overall_health_score, 100.0, places=9)

    def test_all_same_priority_stable_order(self):
        signals = [
            _sig(priority=3, title=f"S{i}", impact=float(i))
            for i in range(5)
        ]
        summary = _make_summary(signals=signals)
        priorities = [s.priority for s in summary.signals]
        self.assertTrue(all(p == 3 for p in priorities))

    def test_mixed_signal_types_all_bucketed(self):
        signals = [
            _sig(priority=1, signal_type="RISK"),
            _sig(priority=2, signal_type="OPPORTUNITY"),
            _sig(priority=3, signal_type="ACTION"),
            _sig(priority=4, signal_type="INFO"),
            _sig(priority=5, signal_type="RISK"),
        ]
        summary = _make_summary(signals=signals)
        total = (
            len(summary.immediate_actions)
            + len(summary.short_term_actions)
            + len(summary.monitor_items)
        )
        self.assertEqual(total, 5)

    def test_build_summary_signals_not_modified(self):
        signals = [_sig(priority=3, title="Orig")]
        original_title = signals[0].title
        _make_summary(signals=signals)
        self.assertEqual(signals[0].title, original_title)

    def test_merge_two_same_titles_deduplicates(self):
        s1 = _make_summary(signals=[_sig(title="Dup")])
        s2 = _make_summary(signals=[_sig(title="Dup")])
        merged = merge_summaries([s1, s2])
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
