"""Поиск новых протоколов шагом дневного цикла (ADR-089 §6, вариант 1) — контроли шага и
положительные контроли исходной пробы `candidate_discovery_loop_closed`.

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW передаётся в шаг (now_ts=) и в пробу (now=); отметки
# пулов (listedAt) выводятся из того же якоря.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.paper_trading import discovery_step as ds

NOW = dt.datetime(2026, 9, 13, 8, 0, tzinfo=dt.timezone.utc)
NOW_TS = NOW.timestamp()
OLD = int(NOW_TS) - 400 * 86400
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pools():
    return [
        {"pool": "p1", "project": "newlend-x", "symbol": "USDC", "chain": "Ethereum",
         "tvlUsd": 30_000_000.0, "apy": 5.0, "listedAt": OLD},
        {"pool": "p2", "project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
         "tvlUsd": 900_000_000.0, "apy": 4.0, "listedAt": OLD},
        {"pool": "p3", "project": "fluid-lending", "symbol": "USDC", "chain": "Arbitrum",
         "tvlUsd": 50_000_000.0, "apy": 6.0, "listedAt": OLD},
    ]


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class Step(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.td.name, "data")
        os.makedirs(self.data)

    def tearDown(self):
        self.td.cleanup()

    def test_ok_writes_registry_and_status_and_filters_covered(self):
        res = ds.run_discovery_step(self.data, fetch_fn=_pools, now_ts=NOW_TS)
        self.assertEqual(res["status"], ds.OK, res)
        reg = json.load(open(os.path.join(self.data, ds.REGISTRY_FILENAME), encoding="utf-8"))
        protos = sorted(c["protocol"] for c in reg["candidates"])
        # aave-v3 — файловый адаптер; fluid-lending — покрыт реестром ADAPTER_REGISTRY (fluid_*),
        # чего сканер сам по себе не знал (класс «уже наше приезжает как новое»).
        self.assertEqual(protos, ["newlend-x"])
        st = json.load(open(os.path.join(self.data, ds.STATUS_FILENAME), encoding="utf-8"))
        self.assertEqual(st["status"], ds.OK)
        self.assertEqual(st["candidates"], 1)
        self.assertTrue(st["registry_written"])

    def test_degraded_is_a_measured_zero(self):
        res = ds.run_discovery_step(self.data, fetch_fn=lambda: [_pools()[1]], now_ts=NOW_TS)
        self.assertEqual(res["status"], ds.DEGRADED)
        self.assertEqual(res["candidates"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.data, ds.REGISTRY_FILENAME)))

    def test_refused_keeps_previous_registry_byte_for_byte(self):
        ds.run_discovery_step(self.data, fetch_fn=_pools, now_ts=NOW_TS)
        path = os.path.join(self.data, ds.REGISTRY_FILENAME)
        before = _sha(path)

        def boom():
            raise RuntimeError("сеть недоступна")

        res = ds.run_discovery_step(self.data, fetch_fn=boom, now_ts=NOW_TS + 86400)
        self.assertEqual(res["status"], ds.REFUSED)
        self.assertIn("недоступна", res["reason"])
        self.assertEqual(before, _sha(path))
        st = json.load(open(os.path.join(self.data, ds.STATUS_FILENAME), encoding="utf-8"))
        self.assertEqual(st["status"], ds.REFUSED)
        self.assertFalse(st["registry_written"])

    def test_garbage_payload_is_refused_not_zero(self):
        res = ds.run_discovery_step(self.data, fetch_fn=lambda: {"not": "a list"}, now_ts=NOW_TS)
        self.assertEqual(res["status"], ds.REFUSED)
        self.assertFalse(os.path.exists(os.path.join(self.data, ds.REGISTRY_FILENAME)))

    def test_under_pytest_without_injected_feed_is_skipped_not_a_network_call(self):
        with mock.patch.object(ds, "_under_pytest", lambda: True):
            res = ds.run_discovery_step(self.data, now_ts=NOW_TS)
        self.assertEqual(res["status"], ds.SKIPPED)
        self.assertIn("pytest", res["reason"])
        self.assertFalse(os.path.exists(os.path.join(self.data, ds.REGISTRY_FILENAME)))

    def test_scanner_crash_is_refused_never_raised(self):
        from spa_core.adapter_sdk import discovery as d
        with mock.patch.object(d, "run_discovery", side_effect=RuntimeError("сканер упал")):
            res = ds.run_discovery_step(self.data, fetch_fn=_pools, now_ts=NOW_TS)
        self.assertEqual(res["status"], ds.REFUSED)
        self.assertIn("упал", res["reason"])

    def test_coverage_includes_adapter_registry_heads(self):
        cov = ds.coverage_slugs()
        for head in ("aave", "fluid", "silo", "morpho", "pendle"):
            self.assertIn(head, cov)


class Wiring(unittest.TestCase):
    """Шаг подключён при рождении: в цикле, ДО читателей, и объявлен в контракте."""

    def test_daily_monitors_call_the_step_before_the_alpha_scan(self):
        src = open(os.path.join(REPO, "spa_core", "paper_trading", "cycle_reporting.py"), encoding="utf-8").read()
        body = src.split("def _run_daily_monitors(", 1)[1]
        i_step = body.find("run_discovery_step")
        i_alpha = body.find("run_alpha_scan")
        self.assertGreater(i_step, 0, "шаг поиска не вызывается из _run_daily_monitors")
        self.assertGreater(i_alpha, i_step, "читатель (alpha_scan) стоит РАНЬШЕ писателя")

    def test_cycle_runner_declares_both_artifacts(self):
        from spa_core.paper_trading import cycle_runner as cr
        for path in ds.PRODUCES:
            self.assertIn(path, cr.PRODUCES)

    def test_manifest_declares_producer_and_consumer(self):
        m = json.load(open(os.path.join(REPO, "architecture", "manifest.json"), encoding="utf-8"))
        arts = {a["path"]: a for a in m["artifacts"]}
        dc = next(a for a in m["agents"] if a["label"] == "com.spa.daily_cycle")
        produced = {p["artifact"] for p in dc["produces"]}
        for path in ds.PRODUCES:
            self.assertIn(path, arts)
            self.assertIn(path, produced)
            self.assertTrue(arts[path]["consumers"], f"{path}: артефакт без потребителя")

    def test_briefing_builds_the_section(self):
        src = open(os.path.join(REPO, "scripts", "update_system_briefing.py"), encoding="utf-8").read()
        self.assertIn("build_candidate_registry_section() +", src)


class ProbeControls(unittest.TestCase):
    """Проба зелёная на целом контуре и красная с названным звеном на порванном."""

    def test_registered(self):
        self.assertIn("candidate_discovery_loop_closed", ca.PROBES)
        self.assertIsNone(ca.validate_spec("candidate_discovery_loop_closed"))

    def test_satisfied_on_shipped_tree_without_touching_live_data(self):
        live = os.path.join(REPO, "data", ds.REGISTRY_FILENAME)
        before = _sha(live) if os.path.exists(live) else None
        verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertEqual(before, _sha(live) if os.path.exists(live) else None)

    def test_scanner_that_drops_candidates_is_named(self):
        from spa_core.adapter_sdk import discovery as d
        real = d.run_discovery

        def no_candidates(**kw):
            rep = real(**kw)
            rep["candidates"] = []
            rep["status"] = "degraded"
            return rep

        with mock.patch.object(d, "run_discovery", no_candidates):
            verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("ok", detail)

    def test_coverage_that_lets_our_protocol_through_is_named(self):
        with mock.patch.object(ds, "coverage_slugs", lambda: frozenset()):
            verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("покрытие", detail)

    def test_reader_that_says_unmeasured_is_named(self):
        from spa_core.agents import alpha_agent as aa
        with mock.patch.object(aa, "read_candidate_registry",
                               lambda data_dir=None: {"items": [], "measured": False, "reason": "проба"}):
            verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("порвана", detail)

    def test_briefing_section_without_the_row_is_named(self):
        mod = ca._briefing_module()
        with mock.patch.object(mod, "build_candidate_registry_section",
                               lambda **kw: f"## 🧭 Кандидаты\n- про {ca.DISCOVERY_PROBE_PROTO} сказано словами\n"):
            verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("строки таблицы", detail)

    def test_refusal_that_overwrites_the_registry_is_named(self):
        real = ds.run_discovery_step

        def leaky(data_dir=None, **kw):
            res = real(data_dir, **kw)
            if res["status"] == ds.REFUSED:
                # порванное звено: отказ затирает прошлый замер
                path = os.path.join(str(data_dir), ds.REGISTRY_FILENAME)
                open(path, "w", encoding="utf-8").write(json.dumps({"candidates": [], "status": "error"}))
            return res

        with mock.patch.object(ds, "run_discovery_step", leaky):
            verdict, detail = ca._probe_candidate_discovery_loop(None, now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("ПЕРЕПИСАЛ", detail)

    def test_crash_is_unmeasured(self):
        with mock.patch.object(ds, "run_discovery_step", side_effect=RuntimeError("x")):
            verdict, detail = ca.run_probe("candidate_discovery_loop_closed")
        self.assertEqual(verdict, ca.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
