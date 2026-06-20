#!/usr/bin/env python3
"""Tests for SPA-V421 Agent runtime v1 (MP-301) — мандаты, токен-бюджеты,
forbidden-lists, деградация при недоступности LLM.

Pure stdlib ``unittest`` (без pytest — стиль test_adapter_sdk.py). БЕЗ сети:
LLM никогда не вызывается — probe/клиент инжектируются как фейки; все пути
персистентности уводятся во временные директории.

Run:  python3 -m unittest spa_core.tests.test_agent_runtime -v
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
    LLM_FORBIDDEN_AGENTS,
    LOG_MAX_ENTRIES,
    STATUS_BUDGET_EXHAUSTED,
    STATUS_ERROR,
    STATUS_NO_MANDATE,
    STATUS_OK,
    STATUS_SKIPPED_DEGRADED,
    AgentMandate,
    AgentRuntime,
    TokenBudgetTracker,
    load_all_mandates,
    load_mandate_file,
    save_mandate,
)
from spa_core.agent_runtime.mandate import DEFAULT_MANDATES_DIR

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _mandate(**overrides):
    raw = dict(
        name="ceo",
        role="test role",
        schedule="weekly",
        token_budget_per_run=100,
        token_budget_daily=250,
        forbidden_actions=["modify_policy", "initiate_tx"],
        allowed_outputs=["data/ceo_decisions.json"],
        requires_llm=True,
        degradation_mode="skip",
    )
    raw.update(overrides)
    return AgentMandate(**raw)


def _no_tmp_files(directory: Path):
    return [p.name for p in Path(directory).rglob("*.tmp")]


# ─── AgentMandate: валидация ─────────────────────────────────────────────────


class TestMandateValidation(unittest.TestCase):
    def test_valid_mandate_constructs(self):
        m = _mandate()
        self.assertEqual(m.name, "ceo")
        self.assertTrue(m.requires_llm)

    def test_llm_forbidden_agents_constant(self):
        self.assertEqual(LLM_FORBIDDEN_AGENTS, frozenset({"risk", "execution", "monitoring"}))

    def test_llm_mandate_for_forbidden_agents_raises(self):
        for name in sorted(LLM_FORBIDDEN_AGENTS):
            with self.assertRaises(ValueError, msg=name):
                _mandate(name=name, requires_llm=True)

    def test_forbidden_agent_case_insensitive(self):
        with self.assertRaises(ValueError):
            _mandate(name="Risk", requires_llm=True)

    def test_forbidden_agent_without_llm_is_fine(self):
        m = _mandate(name="risk", requires_llm=False)
        self.assertFalse(m.requires_llm)

    def test_invalid_degradation_mode(self):
        with self.assertRaises(ValueError):
            _mandate(degradation_mode="explode")

    def test_non_positive_budgets(self):
        with self.assertRaises(ValueError):
            _mandate(token_budget_per_run=0)
        with self.assertRaises(ValueError):
            _mandate(token_budget_daily=-5)

    def test_per_run_cannot_exceed_daily(self):
        with self.assertRaises(ValueError):
            _mandate(token_budget_per_run=500, token_budget_daily=100)

    def test_empty_name_role_schedule(self):
        for field in ("name", "role", "schedule"):
            with self.assertRaises(ValueError, msg=field):
                _mandate(**{field: "  "})

    def test_forbidden_actions_must_be_strings(self):
        with self.assertRaises(ValueError):
            _mandate(forbidden_actions=["ok", 42])

    def test_from_dict_missing_fields(self):
        with self.assertRaises(ValueError):
            AgentMandate.from_dict({"name": "x"})

    def test_roundtrip_to_from_dict(self):
        m = _mandate()
        m2 = AgentMandate.from_dict(m.to_dict())
        self.assertEqual(m, m2)


# ─── Мандат-файлы: загрузка/сохранение + 3 стартовых ─────────────────────────


class TestMandateFiles(unittest.TestCase):
    def test_three_starter_mandates_load(self):
        mandates = load_all_mandates(DEFAULT_MANDATES_DIR)
        # Original 3 starters + MP-303 risk_sentinel + MP-308 incident_commander
        # + MP-306 strategy (SPA-V423) + l2_adapters + protocol_research
        # (мандаты добавлены параллельными спринтами без обновления ожиданий;
        # фикс в SPA-V424 — тот же паттерн, что при добавлении strategy в v4.23)
        expected = {"ceo", "alpha", "reporting", "risk_sentinel",
                    "incident_commander", "strategy", "l2_adapters",
                    "protocol_research"}
        self.assertEqual(set(mandates), expected)

    def test_starter_mandate_contents(self):
        mandates = load_all_mandates(DEFAULT_MANDATES_DIR)
        ceo, alpha, rep = mandates["ceo"], mandates["alpha"], mandates["reporting"]
        self.assertEqual(ceo.schedule, "weekly")
        self.assertEqual(alpha.schedule, "weekly")
        self.assertEqual(rep.schedule, "daily")
        self.assertIn("data/ceo_decisions.json", ceo.allowed_outputs)
        self.assertIn("data/alpha_candidates.json", alpha.allowed_outputs)
        self.assertIn("modify_policy", ceo.forbidden_actions)
        self.assertIn("initiate_tx", ceo.forbidden_actions)
        self.assertIn("list_protocol_directly", alpha.forbidden_actions)
        self.assertIn("distort_numbers", rep.forbidden_actions)
        for m in (ceo, alpha, rep):
            self.assertTrue(m.requires_llm)
            self.assertNotIn(m.name, LLM_FORBIDDEN_AGENTS)

    def test_save_and_load_roundtrip_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _mandate(name="custom")
            path = save_mandate(m, tmp)
            self.assertTrue(path.exists())
            self.assertEqual(load_mandate_file(path), m)
            self.assertEqual(_no_tmp_files(Path(tmp)), [])

    def test_broken_mandate_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_mandate(_mandate(name="good"), tmp)
            (Path(tmp) / "broken.json").write_text("{not json", encoding="utf-8")
            mandates = load_all_mandates(tmp)
            self.assertEqual(set(mandates), {"good"})

    def test_duplicate_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _mandate(name="dup")
            save_mandate(m, tmp)
            (Path(tmp) / "zz_copy.json").write_text(
                json.dumps(m.to_dict()), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_all_mandates(tmp)

    def test_missing_dir_returns_empty(self):
        self.assertEqual(load_all_mandates("/nonexistent/nowhere"), {})


# ─── TokenBudgetTracker ──────────────────────────────────────────────────────


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.usage_path = Path(self._tmp.name) / "agent_token_usage.json"
        self.now = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
        self.mandates = {"ceo": _mandate()}  # per_run=100, daily=250
        self.tracker = TokenBudgetTracker(
            self.mandates, usage_path=self.usage_path, now_fn=lambda: self.now
        )

    def test_charge_and_remaining(self):
        self.tracker.start_run("ceo")
        ok, reason = self.tracker.charge("ceo", 40)
        self.assertTrue(ok, reason)
        self.assertEqual(self.tracker.remaining("ceo"), {"run": 60, "daily": 210})

    def test_per_run_exhaustion(self):
        self.tracker.start_run("ceo")
        self.assertTrue(self.tracker.charge("ceo", 90)[0])
        ok, reason = self.tracker.charge("ceo", 20)  # 110 > 100 per-run
        self.assertFalse(ok)
        self.assertIn("per-run", reason)
        # отказ ничего не списал
        self.assertEqual(self.tracker.remaining("ceo"), {"run": 10, "daily": 160})

    def test_daily_exhaustion_across_runs(self):
        for _ in range(2):  # 2 запуска по 100 = 200 daily
            self.tracker.start_run("ceo")
            self.assertTrue(self.tracker.charge("ceo", 100)[0])
        self.tracker.start_run("ceo")
        ok, reason = self.tracker.charge("ceo", 100)  # 300 > 250 daily
        self.assertFalse(ok)
        self.assertIn("daily", reason)

    def test_daily_reset_on_utc_date_change(self):
        self.tracker.start_run("ceo")
        self.tracker.charge("ceo", 100)
        self.now = self.now + timedelta(days=1)  # следующий UTC-день
        self.assertEqual(self.tracker.remaining("ceo"), {"run": 100, "daily": 250})
        self.assertEqual(self.tracker.usage("ceo")["daily_used"], 0)

    def test_unknown_agent_and_bad_amount(self):
        ok, reason = self.tracker.charge("ghost", 10)
        self.assertFalse(ok)
        self.assertIn("no mandate", reason)
        self.assertIsNone(self.tracker.remaining("ghost"))
        self.assertFalse(self.tracker.charge("ceo", -1)[0])

    def test_persistence_survives_reload(self):
        self.tracker.start_run("ceo")
        self.tracker.charge("ceo", 70)
        tracker2 = TokenBudgetTracker(
            self.mandates, usage_path=self.usage_path, now_fn=lambda: self.now
        )
        self.assertEqual(tracker2.remaining("ceo"), {"run": 30, "daily": 180})

    def test_atomic_write_no_tmp_leftovers(self):
        self.tracker.start_run("ceo")
        self.tracker.charge("ceo", 10)
        self.assertTrue(self.usage_path.exists())
        self.assertEqual(_no_tmp_files(self.usage_path.parent), [])
        json.loads(self.usage_path.read_text(encoding="utf-8"))  # валидный JSON


# ─── AgentRuntime ────────────────────────────────────────────────────────────


class TestAgentRuntime(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.mandates_dir = self.dir / "mandates"
        self.log_path = self.dir / "agent_runtime_log.json"
        self.usage_path = self.dir / "agent_token_usage.json"
        save_mandate(_mandate(name="ceo", degradation_mode="skip"), self.mandates_dir)
        save_mandate(
            _mandate(name="alpha", degradation_mode="deterministic-only"),
            self.mandates_dir,
        )
        save_mandate(
            _mandate(name="janitor", requires_llm=False, degradation_mode="skip"),
            self.mandates_dir,
        )

    def _runtime(self, **kwargs):
        kwargs.setdefault("mandates_dir", self.mandates_dir)
        kwargs.setdefault("log_path", self.log_path)
        kwargs.setdefault("usage_path", self.usage_path)
        return AgentRuntime(**kwargs)

    def _log_entries(self):
        return json.loads(self.log_path.read_text(encoding="utf-8"))["entries"]

    def test_load_mandates(self):
        rt = self._runtime()
        self.assertEqual(set(rt.mandates), {"ceo", "alpha", "janitor"})

    def test_default_offline_llm_unavailable(self):
        rt = self._runtime()  # llm=None, probe по умолчанию
        self.assertFalse(rt.llm_available())

    def test_check_permission_forbidden_action(self):
        rt = self._runtime()
        ok, reason = rt.check_permission("ceo", "modify_policy")
        self.assertFalse(ok)
        self.assertIn("forbidden", reason)
        self.assertTrue(rt.check_permission("ceo", "write_decision")[0])

    def test_check_permission_unknown_agent_denied(self):
        rt = self._runtime()
        ok, reason = rt.check_permission("ghost", "anything")
        self.assertFalse(ok)
        self.assertIn("no mandate", reason)

    def test_run_agent_happy_path_with_llm(self):
        fake_llm = lambda prompt: "advice"
        rt = self._runtime(llm=fake_llm, llm_probe=lambda: True)
        seen = {}

        def agent_fn(llm):
            seen["llm"] = llm
            return {"decision": "hold"}

        res = rt.run_agent("ceo", agent_fn, tokens=50)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertEqual(res["result"], {"decision": "hold"})
        self.assertEqual(res["tokens_charged"], 50)
        self.assertFalse(res["degraded"])
        self.assertIs(seen["llm"], fake_llm)
        self.assertEqual(rt.budget.remaining("ceo"), {"run": 50, "daily": 200})

    def test_run_agent_no_mandate(self):
        rt = self._runtime()
        res = rt.run_agent("ghost", lambda llm: 1)
        self.assertEqual(res["status"], STATUS_NO_MANDATE)
        self.assertIsNone(res["result"])

    def test_degradation_skip(self):
        rt = self._runtime()  # LLM недоступен (офлайн-дефолт)
        called = []
        res = rt.run_agent("ceo", lambda llm: called.append(1), tokens=50)
        self.assertEqual(res["status"], STATUS_SKIPPED_DEGRADED)
        self.assertTrue(res["degraded"])
        self.assertIsNone(res["result"])
        self.assertEqual(called, [])              # fn не вызывалась
        self.assertEqual(res["tokens_charged"], 0)  # токены не списаны

    def test_degradation_deterministic_only(self):
        rt = self._runtime()
        seen = {}

        def agent_fn(llm):
            seen["llm"] = llm
            return [1, 2, 3]

        res = rt.run_agent("alpha", agent_fn, tokens=50)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertTrue(res["degraded"])
        self.assertIsNone(seen["llm"])            # fn выполнена с llm=None
        self.assertEqual(res["result"], [1, 2, 3])
        self.assertEqual(res["tokens_charged"], 0)

    def test_non_llm_agent_runs_offline(self):
        rt = self._runtime()
        res = rt.run_agent("janitor", lambda llm: "cleaned", tokens=0)
        self.assertEqual(res["status"], STATUS_OK)
        self.assertFalse(res["degraded"])
        self.assertEqual(res["result"], "cleaned")

    def test_budget_exhausted_blocks_run(self):
        rt = self._runtime(llm=lambda p: "x", llm_probe=lambda: True)
        called = []
        res = rt.run_agent("ceo", lambda llm: called.append(1), tokens=150)  # >100
        self.assertEqual(res["status"], STATUS_BUDGET_EXHAUSTED)
        self.assertEqual(called, [])
        self.assertIn("per-run", res["reason"])

    def test_exception_captured(self):
        rt = self._runtime(llm=lambda p: "x", llm_probe=lambda: True)

        def boom(llm):
            raise RuntimeError("agent exploded")

        res = rt.run_agent("ceo", boom, tokens=10)
        self.assertEqual(res["status"], STATUS_ERROR)
        self.assertIn("RuntimeError", res["reason"])
        self.assertIn("agent exploded", res["reason"])
        self.assertIsNone(res["result"])

    def test_broken_probe_means_unavailable(self):
        def bad_probe():
            raise OSError("probe down")

        rt = self._runtime(llm_probe=bad_probe)
        self.assertFalse(rt.llm_available())
        res = rt.run_agent("ceo", lambda llm: 1)
        self.assertEqual(res["status"], STATUS_SKIPPED_DEGRADED)

    def test_runtime_log_written_and_rotated(self):
        rt = self._runtime()
        for _ in range(3):
            rt.run_agent("janitor", lambda llm: 1)
        entries = self._log_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[-1]["agent"], "janitor")
        # ротация: журнал никогда не превышает LOG_MAX_ENTRIES
        for i in range(LOG_MAX_ENTRIES + 10):
            rt.run_agent("janitor", lambda llm: i)
        self.assertEqual(len(self._log_entries()), LOG_MAX_ENTRIES)

    def test_atomicity_no_tmp_leftovers_anywhere(self):
        rt = self._runtime()
        rt.run_agent("janitor", lambda llm: 1)
        rt.run_agent("ceo", lambda llm: 1)
        self.assertEqual(_no_tmp_files(self.dir), [])
        json.loads(self.log_path.read_text(encoding="utf-8"))
        json.loads(self.usage_path.read_text(encoding="utf-8"))


# ─── Конституция: пакет не тащит LLM SDK ─────────────────────────────────────


class TestNoLLMImports(unittest.TestCase):
    def test_agent_runtime_sources_have_no_llm_sdk_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports

        pkg = _REPO_ROOT / "spa_core" / "agent_runtime"
        for path in sorted(pkg.rglob("*.py")):
            violations = find_forbidden_imports(
                path.read_text(encoding="utf-8"), str(path)
            )
            self.assertEqual(violations, [], f"LLM SDK import in {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
