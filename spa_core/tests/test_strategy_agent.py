#!/usr/bin/env python3
"""Tests for SPA-V423 Strategy Agent v2 (MP-306) — weekly-триггер,
ранжирование shadow S0-S5, Kelly-sizing (интеграция optimization/ + stdlib
fallback), валидация LLM-ответа, журнал strategy_recommendations.json,
запуск через AgentRuntime с мандатом strategy.

Pure stdlib ``unittest`` (без pytest — стиль test_ceo_agent.py). БЕЗ сети:
LLM никогда не вызывается по-настоящему — только фейковые callable; вся
персистентность уводится в tempdir.

Run:  python3 -m unittest spa_core.tests.test_strategy_agent -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.agent_runtime import (
    STATUS_BUDGET_EXHAUSTED,
    STATUS_OK,
    AgentRuntime,
)
from spa_core.agent_runtime.mandate import (
    DEFAULT_MANDATES_DIR,
    LLM_FORBIDDEN_AGENTS,
)
from spa_core.agents.strategy_agent_v2 import (
    AGENT_NAME,
    MIN_DAYS_FOR_CANDIDATE,
    RECOMMENDATIONS_MAX_ENTRIES,
    RISK_FREE_RATE_PCT,
    STATUS_NOT_DUE,
    TRIGGER_FORCED,
    TRIGGER_WEEKLY,
    VALID_RECOMMENDATIONS,
    StrategyRecommendation,
    _stdlib_kelly_fraction,
    annualized_volatility_pp,
    append_recommendation,
    decide,
    gather_context,
    kelly_sizing,
    load_recommendations,
    rank_shadow_strategies,
    run_strategy_agent,
    should_run,
)
from spa_core.ci.llm_forbidden_lint import find_forbidden_imports

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _now_fn():
    return _NOW


def _shadow_strategy(name, sortino=None, sharpe=None, pnl=0.0, dd=0.0, days=1,
                     label=None):
    return {
        "name": name, "label": label or name, "equity": 100000.0,
        "pnl_pct": pnl, "days_running": days, "sharpe": sharpe,
        "sortino": sortino, "max_drawdown": dd,
    }


def _write_shadow(data_dir: Path, strategies, best="s0_baseline"):
    (data_dir / "strategy_shadow_comparison.json").write_text(json.dumps({
        "updated_at": "2026-06-09T19:18:10+00:00",
        "strategies": strategies,
        "best_strategy": best,
        "days_running": max((s.get("days_running", 0) for s in strategies), default=0),
    }), encoding="utf-8")


def _write_equity(data_dir: Path, daily_returns=(0.0, 0.02, 0.015), apy=6.5):
    daily = [
        {"date": f"2026-06-{i + 1:02d}", "equity": 100000.0 + i,
         "daily_return_pct": r, "apy_today": apy}
        for i, r in enumerate(daily_returns)
    ]
    (data_dir / "equity_curve_daily.json").write_text(json.dumps({
        "generated_at": "2026-06-11T06:00:00+00:00", "daily": daily,
    }), encoding="utf-8")


def _write_strategy_comparison(data_dir: Path):
    (data_dir / "strategy_comparison.json").write_text(json.dumps({
        "generated_at": "2026-06-10T08:56:41+00:00",
        "strategies": {
            "v1_passive": {"total_return_pct": 0.0},
            "v2_aggressive": {"total_return_pct": 0.5},
        },
    }), encoding="utf-8")


def _write_inputs(data_dir: Path, strategies=None, best="s0_baseline",
                  daily_returns=(0.0, 0.02, 0.015), apy=6.5):
    if strategies is None:
        strategies = [
            _shadow_strategy("s0_baseline", sortino=1.0, sharpe=1.0, days=20),
            _shadow_strategy("s1_concentration", sortino=2.0, sharpe=1.5, days=20),
            _shadow_strategy("s2_momentum", sortino=0.5, sharpe=0.4, days=20),
        ]
    _write_shadow(data_dir, strategies, best=best)
    _write_equity(data_dir, daily_returns=daily_returns, apy=apy)
    _write_strategy_comparison(data_dir)


def _rec_entry(ts: str) -> dict:
    return {
        "ts": ts, "snapshot_id": "snap-x", "trigger": TRIGGER_WEEKLY,
        "recommendation": "keep_current", "strategy": "s0_baseline",
        "reasoning": "r", "inputs_digest": "d",
    }


def _tmp_files(directory: Path):
    return [p.name for p in Path(directory).rglob("*.tmp")]


class StrategyTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.data_dir = self.tmp / "data"
        self.data_dir.mkdir()
        self.rec_path = self.tmp / "strategy_recommendations.json"
        self.addCleanup(self._tmp.cleanup)

    def runtime(self, llm=None, llm_probe=None):
        """Runtime на РЕАЛЬНОЙ директории мандатов (strategy.json), но вся
        персистентность (журнал, бюджет) — в tempdir."""
        return AgentRuntime(
            mandates_dir=DEFAULT_MANDATES_DIR,
            log_path=self.tmp / "runtime_log.json",
            usage_path=self.tmp / "usage.json",
            llm=llm,
            llm_probe=llm_probe,
        )


# ─── rank_shadow_strategies ──────────────────────────────────────────────────


class TestRankShadowStrategies(StrategyTestBase):
    def test_empty_and_garbage_input(self):
        self.assertEqual(rank_shadow_strategies([]), [])
        self.assertEqual(rank_shadow_strategies(None), [])
        self.assertEqual(rank_shadow_strategies("мусор"), [])
        self.assertEqual(rank_shadow_strategies([42, "x", {"no_name": 1}]), [])

    def test_sortino_primary_descending(self):
        ranked = rank_shadow_strategies([
            _shadow_strategy("a", sortino=0.5, days=10),
            _shadow_strategy("b", sortino=2.0, days=10),
            _shadow_strategy("c", sortino=1.0, days=10),
        ])
        self.assertEqual([r["name"] for r in ranked], ["b", "c", "a"])
        self.assertEqual([r["rank"] for r in ranked], [1, 2, 3])

    def test_sharpe_tiebreak(self):
        ranked = rank_shadow_strategies([
            _shadow_strategy("a", sortino=1.0, sharpe=0.5, days=10),
            _shadow_strategy("b", sortino=1.0, sharpe=1.5, days=10),
        ])
        self.assertEqual(ranked[0]["name"], "b")

    def test_pnl_then_drawdown_tiebreak(self):
        ranked = rank_shadow_strategies([
            _shadow_strategy("a", sortino=1.0, sharpe=1.0, pnl=0.1, days=10),
            _shadow_strategy("b", sortino=1.0, sharpe=1.0, pnl=0.4, days=10),
        ])
        self.assertEqual(ranked[0]["name"], "b")
        ranked2 = rank_shadow_strategies([
            _shadow_strategy("a", sortino=1.0, sharpe=1.0, pnl=0.1, dd=5.0, days=10),
            _shadow_strategy("b", sortino=1.0, sharpe=1.0, pnl=0.1, dd=1.0, days=10),
        ])
        self.assertEqual(ranked2[0]["name"], "b")

    def test_none_metrics_rank_last(self):
        ranked = rank_shadow_strategies([
            _shadow_strategy("nulls", sortino=None, sharpe=None, pnl=None, days=10),
            _shadow_strategy("real", sortino=0.01, days=10),
        ])
        self.assertEqual(ranked[0]["name"], "real")
        self.assertIsNone(ranked[1]["sortino"])

    def test_eligibility_gate_min_days(self):
        ranked = rank_shadow_strategies([
            _shadow_strategy("young", sortino=9.9, days=MIN_DAYS_FOR_CANDIDATE - 1),
            _shadow_strategy("old", sortino=1.0, days=MIN_DAYS_FOR_CANDIDATE),
        ])
        by_name = {r["name"]: r for r in ranked}
        self.assertFalse(by_name["young"]["eligible"])
        self.assertTrue(by_name["old"]["eligible"])
        # молодая всё равно ранжируется (rank 1), но не eligible
        self.assertEqual(ranked[0]["name"], "young")

    def test_real_repo_shape_day1_all_ineligible(self):
        """Форма реального data/strategy_shadow_comparison.json: день 1,
        sortino/sharpe = null — все 6 ранжируются, ни одна не eligible."""
        strategies = [
            _shadow_strategy(n, sortino=None, sharpe=None, days=1)
            for n in ("s0_baseline", "s1_concentration", "s2_momentum",
                      "s3_risk_parity", "s4_kelly", "s5_yield_spread")
        ]
        ranked = rank_shadow_strategies(strategies)
        self.assertEqual(len(ranked), 6)
        self.assertFalse(any(r["eligible"] for r in ranked))

    def test_deterministic_stable_order(self):
        strategies = [
            _shadow_strategy("b", sortino=1.0, days=10),
            _shadow_strategy("a", sortino=1.0, days=10),
        ]
        r1 = rank_shadow_strategies(strategies)
        r2 = rank_shadow_strategies(list(reversed(strategies)))
        self.assertEqual([x["name"] for x in r1], [x["name"] for x in r2])
        self.assertEqual(r1[0]["name"], "a")  # name — финальный tiebreak


# ─── Kelly-sizing ────────────────────────────────────────────────────────────


class TestKellySizing(StrategyTestBase):
    def test_annualized_volatility_needs_two_points(self):
        self.assertIsNone(annualized_volatility_pp([]))
        self.assertIsNone(annualized_volatility_pp([0.01]))
        self.assertIsNone(annualized_volatility_pp(None))
        self.assertIsNotNone(annualized_volatility_pp([0.0, 0.02]))

    def test_annualized_volatility_skips_garbage(self):
        vol = annualized_volatility_pp([0.0, "broken", None, True, 0.02])
        self.assertIsNotNone(vol)
        self.assertGreater(vol, 0.0)

    def test_stdlib_formula_matches_variance_kelly(self):
        # f* = ((apy - rf)/100) / (vol/100)^2; apy=10, rf=5, vol=50pp → 0.2
        f = _stdlib_kelly_fraction(10.0, 50.0, risk_free_rate_pct=5.0)
        self.assertAlmostEqual(f, 0.2, places=9)

    def test_stdlib_formula_zero_when_no_excess(self):
        self.assertEqual(_stdlib_kelly_fraction(RISK_FREE_RATE_PCT, 10.0), 0.0)
        self.assertEqual(_stdlib_kelly_fraction(3.0, 10.0), 0.0)
        self.assertEqual(_stdlib_kelly_fraction(10.0, 0.0), 0.0)
        self.assertEqual(_stdlib_kelly_fraction(-1.0, 10.0), 0.0)

    def test_stdlib_formula_clamped_to_one(self):
        self.assertEqual(_stdlib_kelly_fraction(50.0, 1.0), 1.0)

    def test_sizing_uses_optimization_module_when_available(self):
        res = kelly_sizing(10.0, 50.0)
        # spa_core/optimization/ существует в репо → интеграция активна
        self.assertEqual(res["source"], "spa_core.optimization.dynamic_kelly")
        self.assertAlmostEqual(res["kelly_fraction"], 0.2, places=6)
        self.assertAlmostEqual(res["half_kelly"], 0.1, places=6)
        self.assertAlmostEqual(res["recommended_deployment_pct"], 10.0, places=4)

    def test_sizing_fallback_when_kelly_fn_raises(self):
        def broken(*a, **k):
            raise RuntimeError("boom")
        res = kelly_sizing(10.0, 50.0, kelly_fn=broken)
        self.assertEqual(res["source"], "stdlib_fallback")
        self.assertAlmostEqual(res["kelly_fraction"], 0.2, places=6)
        self.assertIn("stdlib", res["note"])

    def test_sizing_insufficient_data_honest_zero(self):
        for apy, vol in ((None, 10.0), (5.0, None), (5.0, 0.0)):
            res = kelly_sizing(apy, vol)
            self.assertEqual(res["kelly_fraction"], 0.0)
            self.assertEqual(res["recommended_deployment_pct"], 0.0)
            self.assertEqual(res["source"], "insufficient_data")
            self.assertTrue(res["note"])

    def test_sizing_half_kelly_is_half(self):
        res = kelly_sizing(10.0, 50.0)
        self.assertAlmostEqual(res["half_kelly"], res["kelly_fraction"] / 2, places=9)

    def test_sizing_low_apy_below_riskfree_zero_with_note(self):
        # реальный кейс репо: APY ~3.17% < risk-free 5% → Kelly=0, честная note
        res = kelly_sizing(3.17, 0.12)
        self.assertEqual(res["kelly_fraction"], 0.0)
        self.assertTrue(res["note"])


# ─── should_run ──────────────────────────────────────────────────────────────


class TestShouldRun(StrategyTestBase):
    def test_no_recommendations_yet_weekly(self):
        due, trigger = should_run({}, [], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_old_recommendation_weekly(self):
        old = (_NOW - timedelta(days=8)).isoformat()
        due, trigger = should_run({}, [_rec_entry(old)], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_recent_recommendation_not_due(self):
        recent = (_NOW - timedelta(days=1)).isoformat()
        due, trigger = should_run({}, [_rec_entry(recent)], now=_NOW)
        self.assertFalse(due)
        self.assertIsNone(trigger)

    def test_exactly_seven_days_is_due(self):
        edge = (_NOW - timedelta(days=7)).isoformat()
        due, trigger = should_run({}, [_rec_entry(edge)], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_malformed_last_ts_treated_as_due(self):
        due, trigger = should_run({}, [_rec_entry("не-дата")], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_injected_now_is_deterministic(self):
        last = (_NOW - timedelta(days=6, hours=23)).isoformat()
        self.assertFalse(should_run({}, [_rec_entry(last)], now=_NOW)[0])
        self.assertTrue(
            should_run({}, [_rec_entry(last)], now=_NOW + timedelta(hours=2))[0]
        )


# ─── gather_context ──────────────────────────────────────────────────────────


class TestGatherContext(StrategyTestBase):
    def test_all_inputs_present(self):
        _write_inputs(self.data_dir)
        ctx = gather_context(self.data_dir)
        self.assertEqual(ctx["missing"], [])
        self.assertEqual(ctx["inputs"]["shadow"]["num_strategies"], 3)
        self.assertEqual(ctx["current_strategy"], "s0_baseline")
        self.assertEqual(ctx["inputs"]["equity"]["num_days"], 3)
        self.assertIn("v2_aggressive",
                      ctx["inputs"]["strategy_comparison"]["strategies"])
        self.assertEqual(len(ctx["ranking"]), 3)
        self.assertEqual(ctx["ranking"][0]["name"], "s1_concentration")
        self.assertIn("kelly_fraction", ctx["kelly"])

    def test_missing_all_files_honest_notes_no_crash(self):
        ctx = gather_context(self.data_dir)
        self.assertEqual(len(ctx["missing"]), 3)
        self.assertTrue(all(v is None for v in ctx["inputs"].values()))
        self.assertEqual(ctx["ranking"], [])
        self.assertIsNone(ctx["current_strategy"])
        self.assertEqual(ctx["kelly"]["source"], "insufficient_data")
        self.assertTrue(ctx["snapshot_id"].startswith("snap-"))

    def test_broken_json_honest_note_no_crash(self):
        (self.data_dir / "strategy_shadow_comparison.json").write_text(
            "{broken", encoding="utf-8")
        ctx = gather_context(self.data_dir)
        self.assertIsNone(ctx["inputs"]["shadow"])
        self.assertTrue(any("shadow" in m and "не читается" in m
                            for m in ctx["missing"]))

    def test_digest_and_snapshot_deterministic_for_same_inputs(self):
        _write_inputs(self.data_dir)
        ctx1 = gather_context(self.data_dir)
        ctx2 = gather_context(self.data_dir)
        self.assertEqual(ctx1["inputs_digest"], ctx2["inputs_digest"])
        self.assertEqual(ctx1["snapshot_id"], ctx2["snapshot_id"])

    def test_digest_changes_when_inputs_change(self):
        _write_inputs(self.data_dir)
        d1 = gather_context(self.data_dir)["inputs_digest"]
        _write_equity(self.data_dir, daily_returns=(0.0, -0.5, 0.1), apy=2.0)
        d2 = gather_context(self.data_dir)["inputs_digest"]
        self.assertNotEqual(d1, d2)

    def test_kelly_in_context_is_deterministic_from_equity(self):
        _write_inputs(self.data_dir, daily_returns=(0.0, 0.02, 0.015), apy=6.5)
        ctx = gather_context(self.data_dir)
        self.assertEqual(ctx["kelly"]["apy_pct"], 6.5)
        self.assertGreater(ctx["kelly"]["volatility_pp"], 0.0)


# ─── decide ──────────────────────────────────────────────────────────────────


class TestDecide(StrategyTestBase):
    def _ctx(self, ranking=None, current="s0_baseline", kelly=None, missing=None):
        return {
            "ranking": ranking if ranking is not None else [],
            "current_strategy": current,
            "kelly": kelly or {"recommended_deployment_pct": 0.0, "source": "x"},
            "snapshot_id": "snap-abc",
            "inputs_digest": "deadbeef",
            "missing": missing or [],
        }

    def _ranked(self, *names_eligible):
        return [
            {"name": n, "rank": i + 1, "sortino": 2.0 - i, "sharpe": 1.0,
             "pnl_pct": 0.1, "max_drawdown": 0.0, "days_running": 20 if e else 1,
             "eligible": e}
            for i, (n, e) in enumerate(names_eligible)
        ]

    def test_no_eligible_keeps_current(self):
        ctx = self._ctx(ranking=self._ranked(("s1", False), ("s0_baseline", False)))
        rec = decide(ctx, TRIGGER_WEEKLY, llm=None, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "keep_current")
        self.assertEqual(rec.strategy, "s0_baseline")
        self.assertTrue(rec.degraded)
        self.assertIn("[degraded=true]", rec.reasoning)

    def test_top_equals_current_keeps_current(self):
        ctx = self._ctx(ranking=self._ranked(("s0_baseline", True), ("s1", True)))
        rec = decide(ctx, TRIGGER_WEEKLY, llm=None, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "keep_current")
        self.assertEqual(rec.strategy, "s0_baseline")

    def test_top_differs_recommends_strategy(self):
        ctx = self._ctx(ranking=self._ranked(("s4_kelly", True), ("s0_baseline", True)))
        rec = decide(ctx, TRIGGER_WEEKLY, llm=None, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "recommend_strategy")
        self.assertEqual(rec.strategy, "s4_kelly")
        self.assertIn("селектор", rec.reasoning)

    def test_recommendation_fields_complete_and_advisory(self):
        ctx = self._ctx(ranking=self._ranked(("s1", True)))
        d = decide(ctx, TRIGGER_WEEKLY, llm=None, now_fn=_now_fn).to_dict()
        for f in ("ts", "snapshot_id", "trigger", "recommendation", "strategy",
                  "kelly", "ranking_top3", "reasoning", "inputs_digest",
                  "degraded", "advisory_only", "schema_version"):
            self.assertIn(f, d)
        self.assertEqual(d["ts"], _NOW.isoformat())
        self.assertEqual(d["snapshot_id"], "snap-abc")
        self.assertEqual(d["inputs_digest"], "deadbeef")
        self.assertTrue(d["advisory_only"])
        self.assertIn(d["recommendation"], VALID_RECOMMENDATIONS)

    def test_llm_valid_dict_response_used(self):
        ctx = self._ctx(ranking=self._ranked(("s4_kelly", True), ("s0_baseline", True)))
        llm = lambda prompt: {"recommendation": "recommend_strategy",
                              "strategy": "s4_kelly",
                              "reasoning": "s4 стабильно обгоняет baseline"}
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "recommend_strategy")
        self.assertEqual(rec.strategy, "s4_kelly")
        self.assertEqual(rec.reasoning, "s4 стабильно обгоняет baseline")
        self.assertFalse(rec.degraded)

    def test_llm_valid_json_string_parsed(self):
        ctx = self._ctx(ranking=self._ranked(("s1", True)))
        llm = lambda prompt: json.dumps(
            {"recommendation": "keep_current", "reasoning": "истории мало"})
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "keep_current")
        self.assertEqual(rec.strategy, "s0_baseline")  # подставлена текущая
        self.assertFalse(rec.degraded)

    def test_llm_invalid_enum_falls_back(self):
        ctx = self._ctx(ranking=self._ranked(("s4_kelly", True), ("s0_baseline", True)))
        llm = lambda prompt: {"recommendation": "yolo_all_in", "reasoning": "."}
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "recommend_strategy")  # детерминистика
        self.assertTrue(rec.degraded)
        self.assertIn("валидацию", rec.reasoning)

    def test_llm_hallucinated_strategy_name_falls_back(self):
        """LLM рекомендует несуществующую/не-eligible стратегию → fallback."""
        ctx = self._ctx(ranking=self._ranked(("s4_kelly", True), ("s0_baseline", True)))
        llm = lambda prompt: {"recommendation": "recommend_strategy",
                              "strategy": "s99_moon", "reasoning": "верь мне"}
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertTrue(rec.degraded)
        self.assertEqual(rec.strategy, "s4_kelly")  # детерминированный лидер

    def test_llm_garbage_string_falls_back(self):
        ctx = self._ctx(ranking=self._ranked(("s0_baseline", True)))
        llm = lambda prompt: "ну я думаю надо подержать"
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "keep_current")
        self.assertTrue(rec.degraded)

    def test_llm_raises_falls_back(self):
        def llm(prompt):
            raise RuntimeError("api down")
        ctx = self._ctx(ranking=self._ranked(("s0_baseline", True)))
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.recommendation, "keep_current")
        self.assertTrue(rec.degraded)
        self.assertIn("LLM упал", rec.reasoning)

    def test_llm_recommendation_always_in_enum(self):
        ctx = self._ctx(ranking=self._ranked(("s1", True)))
        for resp in ({"recommendation": "change_active_strategy"},
                     {"recommendation": "keep_current", "strategy": 42},
                     [], None, 7, "{}", "[broken"):
            llm = lambda prompt, _r=resp: _r
            rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
            self.assertIn(rec.recommendation, VALID_RECOMMENDATIONS)

    def test_kelly_stays_deterministic_even_with_llm(self):
        """LLM никогда не сайзит капитал: kelly в рекомендации — из контекста."""
        kelly = {"kelly_fraction": 0.2, "half_kelly": 0.1,
                 "recommended_deployment_pct": 10.0, "source": "x"}
        ctx = self._ctx(ranking=self._ranked(("s1", True)), kelly=kelly)
        llm = lambda prompt: {"recommendation": "keep_current",
                              "reasoning": "и кстати деплой 100% котлетой",
                              "kelly": {"kelly_fraction": 1.0}}
        rec = decide(ctx, TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(rec.kelly["kelly_fraction"], 0.2)
        self.assertEqual(rec.kelly["recommended_deployment_pct"], 10.0)


# ─── журнал strategy_recommendations.json ────────────────────────────────────


class TestRecommendationsLog(StrategyTestBase):
    def _r(self, i=0):
        return _rec_entry((_NOW + timedelta(minutes=i)).isoformat())

    def test_append_creates_file_with_schema(self):
        append_recommendation(self._r(), self.rec_path)
        raw = json.loads(self.rec_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], 1)
        self.assertTrue(raw["advisory_only"])
        self.assertEqual(len(raw["recommendations"]), 1)

    def test_append_appends_in_order(self):
        for i in range(3):
            append_recommendation(self._r(i), self.rec_path)
        got = load_recommendations(self.rec_path)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[-1]["ts"], (_NOW + timedelta(minutes=2)).isoformat())

    def test_rotation_keeps_last_max_entries(self):
        many = [self._r(i) for i in range(RECOMMENDATIONS_MAX_ENTRIES + 7)]
        self.rec_path.write_text(
            json.dumps({"schema_version": 1, "recommendations": many[:-1]}),
            encoding="utf-8",
        )
        got = append_recommendation(many[-1], self.rec_path)
        self.assertEqual(len(got), RECOMMENDATIONS_MAX_ENTRIES)
        self.assertEqual(got[-1]["ts"], many[-1]["ts"])

    def test_atomic_write_no_tmp_leftovers(self):
        append_recommendation(self._r(), self.rec_path)
        self.assertEqual(_tmp_files(self.tmp), [])

    def test_corrupted_existing_file_does_not_crash(self):
        self.rec_path.write_text("[[[broken", encoding="utf-8")
        got = append_recommendation(self._r(), self.rec_path)
        self.assertEqual(len(got), 1)

    def test_load_tolerates_bare_list(self):
        self.rec_path.write_text(json.dumps([self._r()]), encoding="utf-8")
        self.assertEqual(len(load_recommendations(self.rec_path)), 1)

    def test_load_missing_file_empty(self):
        self.assertEqual(load_recommendations(self.tmp / "nope.json"), [])


# ─── запуск через AgentRuntime с мандатом strategy ───────────────────────────


class TestRunViaRuntime(StrategyTestBase):
    def test_offline_default_runs_deterministic_only(self):
        """Мандат strategy: requires_llm=true, degradation_mode=
        deterministic-only → офлайн (llm=None, дефолтный probe) guard
        выполняет fn(llm=None): рекомендация записана, degraded=True."""
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertTrue(res["degraded"])
        self.assertEqual(res["trigger"], TRIGGER_WEEKLY)  # журнал пуст → weekly
        got = load_recommendations(self.rec_path)
        self.assertEqual(len(got), 1)
        self.assertIn("[degraded=true]", got[0]["reasoning"])

    def test_recommends_leader_when_differs_from_current(self):
        _write_inputs(self.data_dir)  # лидер s1_concentration, current s0_baseline
        rt = self.runtime(llm=None)
        run_strategy_agent(rt, data_dir=self.data_dir,
                           recommendations_path=self.rec_path, now_fn=_now_fn)
        got = load_recommendations(self.rec_path)[0]
        self.assertEqual(got["recommendation"], "recommend_strategy")
        self.assertEqual(got["strategy"], "s1_concentration")
        self.assertTrue(got["advisory_only"])

    def test_day_one_data_keeps_current(self):
        strategies = [
            _shadow_strategy(n, sortino=None, days=1)
            for n in ("s0_baseline", "s1_concentration", "s2_momentum")
        ]
        _write_inputs(self.data_dir, strategies=strategies)
        rt = self.runtime(llm=None)
        run_strategy_agent(rt, data_dir=self.data_dir,
                           recommendations_path=self.rec_path, now_fn=_now_fn)
        got = load_recommendations(self.rec_path)[0]
        self.assertEqual(got["recommendation"], "keep_current")

    def test_not_due_does_not_invoke_runtime(self):
        _write_inputs(self.data_dir)
        append_recommendation(_rec_entry((_NOW - timedelta(days=1)).isoformat()),
                              self.rec_path)
        rt = self.runtime(llm=None)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_NOT_DUE)
        self.assertEqual(len(load_recommendations(self.rec_path)), 1)  # без новых

    def test_force_runs_even_when_not_due(self):
        _write_inputs(self.data_dir)
        append_recommendation(_rec_entry((_NOW - timedelta(days=1)).isoformat()),
                              self.rec_path)
        rt = self.runtime(llm=None)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path,
                                 now_fn=_now_fn, force=True)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertEqual(res["trigger"], TRIGGER_FORCED)
        self.assertEqual(len(load_recommendations(self.rec_path)), 2)

    def test_budget_exhausted_blocks_run_no_recommendation(self):
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path,
                                 now_fn=_now_fn, tokens=10 ** 9)
        self.assertEqual(res["status"], STATUS_BUDGET_EXHAUSTED)
        self.assertFalse(self.rec_path.exists())

    def test_llm_run_through_runtime_validated(self):
        _write_inputs(self.data_dir)
        llm = lambda prompt: {"recommendation": "recommend_strategy",
                              "strategy": "s1_concentration",
                              "reasoning": "s1 лидирует по sortino"}
        rt = self.runtime(llm=llm)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path,
                                 now_fn=_now_fn, tokens=100)
        self.assertEqual(res["status"], STATUS_OK)
        got = load_recommendations(self.rec_path)[0]
        self.assertEqual(got["recommendation"], "recommend_strategy")
        self.assertEqual(got["strategy"], "s1_concentration")
        self.assertFalse(got["degraded"])

    def test_missing_all_inputs_still_runs_honestly(self):
        rt = self.runtime(llm=None)
        res = run_strategy_agent(rt, data_dir=self.data_dir,
                                 recommendations_path=self.rec_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_OK)
        got = load_recommendations(self.rec_path)[0]
        self.assertEqual(got["recommendation"], "keep_current")
        self.assertIn("Отсутствуют входы", got["reasoning"])

    def test_no_tmp_leftovers_after_run(self):
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None)
        run_strategy_agent(rt, data_dir=self.data_dir,
                           recommendations_path=self.rec_path, now_fn=_now_fn)
        self.assertEqual(_tmp_files(self.tmp), [])


# ─── инварианты мандата и конституции ────────────────────────────────────────


class TestMandateInvariants(StrategyTestBase):
    def test_change_active_strategy_denied(self):
        """Ключевой запрет MP-306: активную стратегию меняет ТОЛЬКО селектор."""
        rt = self.runtime()
        ok, reason = rt.check_permission(AGENT_NAME, "change_active_strategy")
        self.assertFalse(ok)
        self.assertIn("forbidden", reason)

    def test_other_forbidden_actions_denied(self):
        rt = self.runtime()
        for action in ("modify_policy", "initiate_tx", "modify_risk_limits",
                       "modify_whitelist", "move_capital"):
            self.assertFalse(rt.check_permission(AGENT_NAME, action)[0], action)

    def test_writing_own_recommendations_is_permitted(self):
        rt = self.runtime()
        ok, _ = rt.check_permission(AGENT_NAME, "write_strategy_recommendations")
        self.assertTrue(ok)

    def test_mandate_allows_only_recommendations_output(self):
        rt = self.runtime()
        self.assertEqual(rt.mandates[AGENT_NAME].allowed_outputs,
                         ["data/strategy_recommendations.json"])

    def test_mandate_weekly_deterministic_only(self):
        rt = self.runtime()
        m = rt.mandates[AGENT_NAME]
        self.assertEqual(m.schedule, "weekly")
        self.assertTrue(m.requires_llm)
        self.assertEqual(m.degradation_mode, "deterministic-only")
        self.assertLessEqual(m.token_budget_per_run, m.token_budget_daily)

    def test_agent_name_not_in_llm_forbidden_set(self):
        self.assertNotIn(AGENT_NAME, LLM_FORBIDDEN_AGENTS)

    def test_no_llm_sdk_imports_in_strategy_agent_v2(self):
        source = (_REPO_ROOT / "spa_core" / "agents" / "strategy_agent_v2.py"
                  ).read_text(encoding="utf-8")
        self.assertEqual(find_forbidden_imports(source, "strategy_agent_v2.py"), [])

    def test_no_llm_sdk_imports_in_this_test(self):
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(find_forbidden_imports(source, "test_strategy_agent.py"), [])


if __name__ == "__main__":
    unittest.main()
