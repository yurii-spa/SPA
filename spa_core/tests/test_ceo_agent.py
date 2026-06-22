#!/usr/bin/env python3
"""Tests for SPA-V422 CEO Agent v2 (MP-302) — weekly/drawdown триггеры,
детерминированное ядро, валидация LLM-ответа, журнал ceo_decisions.json,
запуск через AgentRuntime с мандатом ceo.

Pure stdlib ``unittest`` (без pytest — стиль test_agent_runtime.py). БЕЗ
сети: LLM никогда не вызывается по-настоящему — только фейковые callable;
вся персистентность уводится в tempdir.

Run:  python3 -m unittest spa_core.tests.test_ceo_agent -v
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.agent_runtime import (
    STATUS_BUDGET_EXHAUSTED,
    STATUS_OK,
    STATUS_SKIPPED_DEGRADED,
    AgentRuntime,
)
from spa_core.agent_runtime.mandate import DEFAULT_MANDATES_DIR
from spa_core.agents.ceo_agent_v2 import (
    AGENT_NAME,
    DECISIONS_MAX_ENTRIES,
    DRAWDOWN_TRIGGER_PCT,
    STATUS_NOT_DUE,
    TRIGGER_DRAWDOWN,
    TRIGGER_FORCED,
    TRIGGER_WEEKLY,
    VALID_DECISIONS,
    append_decision,
    compute_drawdown_pct,
    decide,
    gather_context,
    load_decisions,
    run_ceo,
    should_run,
)
from spa_core.ci.llm_forbidden_lint import find_forbidden_imports

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _now_fn():
    return _NOW


def _write_equity(data_dir: Path, equities, generated_at="2026-06-11T06:00:00+00:00"):
    payload = {
        "generated_at": generated_at,
        "source": "cycle_runner",
        "daily": [
            {"date": f"2026-06-{i + 1:02d}", "equity": eq}
            for i, eq in enumerate(equities)
        ],
    }
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_inputs(data_dir: Path, equities=(100000.0, 100017.3)):
    _write_equity(data_dir, list(equities))
    (data_dir / "strategy_comparison.json").write_text(json.dumps({
        "generated_at": "2026-06-10T08:56:41+00:00",
        "strategies": {
            "v1_passive": {"total_return_pct": 0.0},
            "v2_aggressive": {"total_return_pct": 0.5},
        },
    }), encoding="utf-8")
    (data_dir / "regime_segmentation.json").write_text(json.dumps({
        "generated_at": "2026-06-10T01:14:15+00:00",
        "segmentation": {
            "num_segments": 1,
            "segments": [{
                "direction": "decline", "return_pct": -1.2,
                "start_date": "2026-05-15", "end_date": "2026-05-22",
            }],
        },
    }), encoding="utf-8")


def _decision_entry(ts: str) -> dict:
    return {
        "ts": ts, "snapshot_id": "snap-x", "trigger": TRIGGER_WEEKLY,
        "decision": "keep_strategy", "reasoning": "r", "inputs_digest": "d",
    }


def _tmp_files(directory: Path):
    return [p.name for p in Path(directory).rglob("*.tmp")]


class CeoTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.data_dir = self.tmp / "data"
        self.data_dir.mkdir()
        self.decisions_path = self.tmp / "ceo_decisions.json"
        self.addCleanup(self._tmp.cleanup)

    def runtime(self, llm=None, llm_probe=None):
        """Runtime на РЕАЛЬНОЙ директории мандатов (ceo.json), но вся
        персистентность (журнал, бюджет) — в tempdir."""
        return AgentRuntime(
            mandates_dir=DEFAULT_MANDATES_DIR,
            log_path=self.tmp / "runtime_log.json",
            usage_path=self.tmp / "usage.json",
            llm=llm,
            llm_probe=llm_probe,
        )


# ─── compute_drawdown_pct ────────────────────────────────────────────────────


class TestComputeDrawdown(CeoTestBase):
    def test_empty_series_is_none(self):
        self.assertIsNone(compute_drawdown_pct([]))
        self.assertIsNone(compute_drawdown_pct(None))

    def test_rising_series_zero(self):
        self.assertEqual(compute_drawdown_pct([100.0, 101.0, 102.0]), 0.0)

    def test_five_percent_drop(self):
        dd = compute_drawdown_pct([100000.0, 95000.0])
        self.assertAlmostEqual(dd, 5.0, places=6)

    def test_drawdown_from_global_peak_to_last(self):
        # пик 110, последняя 104.5 → dd = 5%
        dd = compute_drawdown_pct([100.0, 110.0, 99.0, 104.5])
        self.assertAlmostEqual(dd, 5.0, places=6)

    def test_non_numeric_points_skipped(self):
        dd = compute_drawdown_pct([100.0, "broken", None, True, 98.0])
        self.assertAlmostEqual(dd, 2.0, places=6)


# ─── should_run ──────────────────────────────────────────────────────────────


class TestShouldRun(CeoTestBase):
    def test_no_decisions_yet_weekly(self):
        due, trigger = should_run({"drawdown_pct": 0.0}, [], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_old_decision_weekly(self):
        old = (_NOW - timedelta(days=8)).isoformat()
        due, trigger = should_run({"drawdown_pct": 0.0}, [_decision_entry(old)], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_recent_decision_no_drawdown_not_due(self):
        recent = (_NOW - timedelta(days=1)).isoformat()
        due, trigger = should_run({"drawdown_pct": 0.5}, [_decision_entry(recent)], now=_NOW)
        self.assertFalse(due)
        self.assertIsNone(trigger)

    def test_drawdown_overrides_recent_decision(self):
        recent = (_NOW - timedelta(hours=2)).isoformat()
        due, trigger = should_run({"drawdown_pct": 2.5}, [_decision_entry(recent)], now=_NOW)
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_DRAWDOWN)

    def test_drawdown_exactly_threshold_is_not_trigger(self):
        recent = (_NOW - timedelta(days=1)).isoformat()
        due, trigger = should_run(
            {"drawdown_pct": DRAWDOWN_TRIGGER_PCT}, [_decision_entry(recent)], now=_NOW
        )
        self.assertFalse(due)
        self.assertIsNone(trigger)

    def test_malformed_last_ts_treated_as_due(self):
        due, trigger = should_run(
            {"drawdown_pct": 0.0}, [_decision_entry("не-дата")], now=_NOW
        )
        self.assertTrue(due)
        self.assertEqual(trigger, TRIGGER_WEEKLY)

    def test_missing_drawdown_data_weekly_only(self):
        recent = (_NOW - timedelta(days=1)).isoformat()
        due, trigger = should_run({"drawdown_pct": None}, [_decision_entry(recent)], now=_NOW)
        self.assertFalse(due)
        # ...но weekly всё равно срабатывает по сроку
        old = (_NOW - timedelta(days=7)).isoformat()
        due2, trigger2 = should_run({"drawdown_pct": None}, [_decision_entry(old)], now=_NOW)
        self.assertTrue(due2)
        self.assertEqual(trigger2, TRIGGER_WEEKLY)

    def test_injected_now_is_deterministic(self):
        last = (_NOW - timedelta(days=6, hours=23)).isoformat()
        self.assertFalse(should_run({}, [_decision_entry(last)], now=_NOW)[0])
        self.assertTrue(
            should_run({}, [_decision_entry(last)], now=_NOW + timedelta(hours=2))[0]
        )


# ─── gather_context ──────────────────────────────────────────────────────────


class TestGatherContext(CeoTestBase):
    def test_all_inputs_present(self):
        _write_inputs(self.data_dir, equities=(100000.0, 97000.0))
        ctx = gather_context(self.data_dir)
        self.assertEqual(ctx["missing"], [])
        self.assertAlmostEqual(ctx["drawdown_pct"], 3.0, places=6)
        self.assertEqual(ctx["inputs"]["equity"]["num_days"], 2)
        self.assertIn("v2_aggressive", ctx["inputs"]["strategy_comparison"]["strategies"])
        self.assertEqual(ctx["inputs"]["regime"]["last_segment"]["direction"], "decline")

    def test_missing_all_files_honest_notes_no_crash(self):
        ctx = gather_context(self.data_dir)
        self.assertEqual(len(ctx["missing"]), 3)
        self.assertTrue(all(v is None for v in ctx["inputs"].values()))
        self.assertIsNone(ctx["drawdown_pct"])
        self.assertTrue(ctx["snapshot_id"].startswith("snap-"))

    def test_broken_json_honest_note_no_crash(self):
        (self.data_dir / "equity_curve_daily.json").write_text("{broken", encoding="utf-8")
        ctx = gather_context(self.data_dir)
        self.assertIsNone(ctx["inputs"]["equity"])
        self.assertTrue(any("equity" in m and "не читается" in m for m in ctx["missing"]))

    def test_digest_and_snapshot_deterministic_for_same_inputs(self):
        _write_inputs(self.data_dir)
        ctx1 = gather_context(self.data_dir)
        ctx2 = gather_context(self.data_dir)
        self.assertEqual(ctx1["inputs_digest"], ctx2["inputs_digest"])
        self.assertEqual(ctx1["snapshot_id"], ctx2["snapshot_id"])

    def test_digest_changes_when_inputs_change(self):
        _write_inputs(self.data_dir)
        d1 = gather_context(self.data_dir)["inputs_digest"]
        _write_equity(self.data_dir, [100000.0, 90000.0])
        d2 = gather_context(self.data_dir)["inputs_digest"]
        self.assertNotEqual(d1, d2)


# ─── decide ──────────────────────────────────────────────────────────────────


class TestDecide(CeoTestBase):
    def _ctx(self, dd):
        return {"drawdown_pct": dd, "snapshot_id": "snap-abc", "inputs_digest": "deadbeef",
                "missing": []}

    def test_no_llm_drawdown_escalates(self):
        d = decide(self._ctx(3.1), TRIGGER_DRAWDOWN, llm=None, now_fn=_now_fn)
        self.assertEqual(d.decision, "escalate")
        self.assertTrue(d.degraded)
        self.assertIn("[degraded=true]", d.reasoning)

    def test_no_llm_calm_keeps_strategy(self):
        d = decide(self._ctx(0.4), TRIGGER_WEEKLY, llm=None, now_fn=_now_fn)
        self.assertEqual(d.decision, "keep_strategy")
        self.assertIn("[degraded=true]", d.reasoning)

    def test_decision_fields_complete(self):
        d = decide(self._ctx(0.0), TRIGGER_WEEKLY, llm=None, now_fn=_now_fn).to_dict()
        for field in ("ts", "snapshot_id", "trigger", "decision",
                      "reasoning", "inputs_digest"):
            self.assertIn(field, d)
        self.assertEqual(d["ts"], _NOW.isoformat())
        self.assertEqual(d["snapshot_id"], "snap-abc")
        self.assertEqual(d["trigger"], TRIGGER_WEEKLY)
        self.assertEqual(d["inputs_digest"], "deadbeef")
        self.assertIn(d["decision"], VALID_DECISIONS)

    def test_llm_valid_dict_response_used(self):
        llm = lambda prompt: {"decision": "recommend_strategy_change",
                              "reasoning": "v2 стабильно обгоняет v1"}
        d = decide(self._ctx(0.1), TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(d.decision, "recommend_strategy_change")
        self.assertEqual(d.reasoning, "v2 стабильно обгоняет v1")
        self.assertFalse(d.degraded)

    def test_llm_valid_json_string_parsed(self):
        llm = lambda prompt: json.dumps({"decision": "escalate", "reasoning": "режим decline"})
        d = decide(self._ctx(0.1), TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(d.decision, "escalate")
        self.assertFalse(d.degraded)

    def test_llm_invalid_enum_falls_back_deterministic(self):
        llm = lambda prompt: {"decision": "yolo_all_in", "reasoning": "trust me"}
        d = decide(self._ctx(2.7), TRIGGER_DRAWDOWN, llm=llm, now_fn=_now_fn)
        self.assertEqual(d.decision, "escalate")  # детерминистика по dd>2%
        self.assertTrue(d.degraded)
        self.assertIn("валидацию enum", d.reasoning)

    def test_llm_garbage_string_falls_back(self):
        llm = lambda prompt: "ну я думаю надо подержать"
        d = decide(self._ctx(0.2), TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(d.decision, "keep_strategy")
        self.assertTrue(d.degraded)

    def test_llm_raises_falls_back(self):
        def llm(prompt):
            raise RuntimeError("api down")
        d = decide(self._ctx(0.2), TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
        self.assertEqual(d.decision, "keep_strategy")
        self.assertTrue(d.degraded)
        self.assertIn("LLM упал", d.reasoning)

    def test_llm_decision_always_in_enum(self):
        for resp in ({"decision": "escalate"}, {"decision": "modify_policy"},
                     [], None, 42, "{}"):
            llm = lambda prompt, _r=resp: _r
            d = decide(self._ctx(0.0), TRIGGER_WEEKLY, llm=llm, now_fn=_now_fn)
            self.assertIn(d.decision, VALID_DECISIONS)


# ─── журнал ceo_decisions.json ───────────────────────────────────────────────


class TestDecisionsLog(CeoTestBase):
    def _d(self, i=0):
        return _decision_entry((_NOW + timedelta(minutes=i)).isoformat())

    def test_append_creates_file_with_schema(self):
        append_decision(self._d(), self.decisions_path)
        raw = json.loads(self.decisions_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], 1)
        self.assertEqual(len(raw["decisions"]), 1)

    def test_append_appends_in_order(self):
        for i in range(3):
            append_decision(self._d(i), self.decisions_path)
        got = load_decisions(self.decisions_path)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[-1]["ts"], (_NOW + timedelta(minutes=2)).isoformat())

    def test_rotation_keeps_last_max_entries(self):
        many = [self._d(i) for i in range(DECISIONS_MAX_ENTRIES + 7)]
        self.decisions_path.write_text(
            json.dumps({"schema_version": 1, "decisions": many[:-1]}), encoding="utf-8"
        )
        got = append_decision(many[-1], self.decisions_path)
        self.assertEqual(len(got), DECISIONS_MAX_ENTRIES)
        self.assertEqual(got[-1]["ts"], many[-1]["ts"])  # последняя запись жива

    def test_atomic_write_no_tmp_leftovers(self):
        append_decision(self._d(), self.decisions_path)
        self.assertEqual(_tmp_files(self.tmp), [])

    def test_corrupted_existing_file_does_not_crash(self):
        self.decisions_path.write_text("[[[broken", encoding="utf-8")
        got = append_decision(self._d(), self.decisions_path)
        self.assertEqual(len(got), 1)

    def test_load_tolerates_bare_list(self):
        self.decisions_path.write_text(json.dumps([self._d()]), encoding="utf-8")
        self.assertEqual(len(load_decisions(self.decisions_path)), 1)

    def test_load_missing_file_empty(self):
        self.assertEqual(load_decisions(self.tmp / "nope.json"), [])


# ─── запуск через AgentRuntime с мандатом ceo ────────────────────────────────


class TestRunCeoViaRuntime(CeoTestBase):
    def test_deterministic_run_writes_decision(self):
        """Фейковый probe=True, llm=None → guard пропускает, fn получает
        llm=None → детерминированное решение записано."""
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertEqual(res["trigger"], TRIGGER_WEEKLY)  # журнал пуст → weekly
        got = load_decisions(self.decisions_path)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["decision"], "keep_strategy")
        self.assertIn("[degraded=true]", got[0]["reasoning"])

    def test_drawdown_trigger_escalates(self):
        _write_inputs(self.data_dir, equities=(100000.0, 96500.0))  # dd 3.5%
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertEqual(res["trigger"], TRIGGER_DRAWDOWN)
        self.assertEqual(load_decisions(self.decisions_path)[0]["decision"], "escalate")

    def test_offline_default_probe_skips_per_mandate(self):
        """Без probe (llm=None) мандат ceo (requires_llm, skip) → деградация
        skip: fn НЕ вызывается, решение НЕ пишется."""
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_SKIPPED_DEGRADED)
        self.assertTrue(res["degraded"])
        self.assertFalse(self.decisions_path.exists())

    def test_not_due_does_not_invoke_runtime(self):
        _write_inputs(self.data_dir)
        append_decision(_decision_entry((_NOW - timedelta(days=1)).isoformat()),
                        self.decisions_path)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn)
        self.assertEqual(res["status"], STATUS_NOT_DUE)
        self.assertEqual(len(load_decisions(self.decisions_path)), 1)  # без новых

    def test_force_runs_even_when_not_due(self):
        _write_inputs(self.data_dir)
        append_decision(_decision_entry((_NOW - timedelta(days=1)).isoformat()),
                        self.decisions_path)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn, force=True)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertEqual(res["trigger"], TRIGGER_FORCED)
        self.assertEqual(len(load_decisions(self.decisions_path)), 2)

    def test_budget_exhausted_blocks_run_no_decision(self):
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn,
                      tokens=10 ** 9)  # >> бюджета мандата ceo
        self.assertEqual(res["status"], STATUS_BUDGET_EXHAUSTED)
        self.assertFalse(self.decisions_path.exists())

    def test_llm_run_through_runtime_validated(self):
        _write_inputs(self.data_dir)
        llm = lambda prompt: {"decision": "recommend_strategy_change",
                              "reasoning": "v2 обгоняет"}
        rt = self.runtime(llm=llm)
        res = run_ceo(rt, data_dir=self.data_dir,
                      decisions_path=self.decisions_path, now_fn=_now_fn, tokens=100)
        self.assertEqual(res["status"], STATUS_OK)
        got = load_decisions(self.decisions_path)[0]
        self.assertEqual(got["decision"], "recommend_strategy_change")
        self.assertFalse(got["degraded"])

    def test_no_tmp_leftovers_after_run(self):
        _write_inputs(self.data_dir)
        rt = self.runtime(llm=None, llm_probe=lambda: True)
        run_ceo(rt, data_dir=self.data_dir,
                decisions_path=self.decisions_path, now_fn=_now_fn)
        self.assertEqual(_tmp_files(self.tmp), [])


# ─── инварианты мандата и конституции ────────────────────────────────────────


class TestMandateInvariants(CeoTestBase):
    def test_forbidden_initiate_tx_denied(self):
        rt = self.runtime()
        ok, reason = rt.check_permission(AGENT_NAME, "initiate_tx")
        self.assertFalse(ok)
        self.assertIn("forbidden", reason)

    def test_other_forbidden_actions_denied(self):
        rt = self.runtime()
        for action in ("modify_policy", "modify_risk_limits",
                       "modify_whitelist", "move_capital"):
            self.assertFalse(rt.check_permission(AGENT_NAME, action)[0], action)

    def test_writing_own_decisions_is_permitted(self):
        rt = self.runtime()
        ok, _ = rt.check_permission(AGENT_NAME, "write_ceo_decisions")
        self.assertTrue(ok)

    def test_ceo_mandate_allows_only_decisions_output(self):
        rt = self.runtime()
        self.assertEqual(rt.mandates[AGENT_NAME].allowed_outputs,
                         ["data/ceo_decisions.json"])

    def test_no_llm_sdk_imports_in_ceo_agent_v2(self):
        source = (_REPO_ROOT / "spa_core" / "agents" / "ceo_agent_v2.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(find_forbidden_imports(source, "ceo_agent_v2.py"), [])

    def test_no_llm_sdk_imports_in_this_test(self):
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(find_forbidden_imports(source, "test_ceo_agent.py"), [])


if __name__ == "__main__":
    unittest.main()
