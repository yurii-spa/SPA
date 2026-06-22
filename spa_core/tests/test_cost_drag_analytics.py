#!/usr/bin/env python3
"""Tests for the Net-of-Cost Performance & Cost-Drag Analyzer (SPA-V445 / MP-123).

Pure stdlib unittest (no pytest, no network, tempdir-only). Covers: the pure
cost model (:func:`compute_cost_components`), the composed build over
monkeypatched upstream analyzers (verdict thresholds, low-sample capping,
is_demo propagation, honest-unavailable), reuse-by-import of the tear_sheet
``content_fingerprint``, the idempotent atomic persistence (byte-identical
re-run, history rotation, no *.tmp leak, tolerant broken prev), the offline CLI
(direct + subprocess: --check/--run/junk→exit0/conflict), and import hygiene
through the real ``find_forbidden_imports`` from the project's LLM-forbidden lint.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading import cost_drag_analytics as cda
from spa_core.reporting import tear_sheet

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXED_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _yld(available=True, apy=5.0, aum=100000.0, is_demo=False):
    return {
        "available": available,
        "portfolio_apy_pp": apy,
        "aum_usd": aum,
        "is_demo": is_demo,
    }


def _turn(available=True, annualized=2.0, rebal=5, obs=30, is_demo=False):
    return {
        "available": available,
        "headline": {
            "annualized_turnover": annualized,
            "num_rebalance_days": rebal,
            "num_observations": obs,
        },
        "meta": {"is_demo": is_demo},
    }


class _PatchUpstream:
    """Context manager: monkeypatch the two imported upstream builders."""

    def __init__(self, yld, turn):
        self._yld = yld
        self._turn = turn

    def __enter__(self):
        self._orig_y = cda.build_yield_attribution
        self._orig_t = cda.build_turnover_analytics
        cda.build_yield_attribution = lambda *a, **k: self._yld
        cda.build_turnover_analytics = lambda *a, **k: self._turn
        return self

    def __exit__(self, *exc):
        cda.build_yield_attribution = self._orig_y
        cda.build_turnover_analytics = self._orig_t
        return False


def _build(yld, turn, **kw):
    with _PatchUpstream(yld, turn):
        return cda.build_cost_drag(now=_FIXED_NOW, **kw)


# ─── Pure cost model ───────────────────────────────────────────────────────────


class TestComputeCostComponents(unittest.TestCase):
    def test_hand_computed_full(self):
        c = cda.compute_cost_components(2.0, 5, 30, 100000.0)
        # turnover: 2.0 * 10 bps = 20 bps = 0.20 pp
        self.assertAlmostEqual(c["turnover_cost_bps"], 20.0, places=9)
        self.assertAlmostEqual(c["turnover_cost_pp"], 0.20, places=9)
        # rebalances/yr = (5/30)*365 = 60.8333..; gas = *15; drag = /1e5*100
        self.assertAlmostEqual(c["rebalances_per_year"], (5 / 30) * 365, places=9)
        self.assertAlmostEqual(c["gas_cost_annual_usd"], (5 / 30) * 365 * 15, places=9)
        self.assertAlmostEqual(
            c["gas_drag_pp"], (5 / 30) * 365 * 15 / 100000.0 * 100, places=9
        )
        self.assertAlmostEqual(
            c["total_cost_drag_pp"],
            c["turnover_cost_pp"] + c["gas_drag_pp"],
            places=12,
        )

    def test_zero_turnover_zero_rebalance(self):
        c = cda.compute_cost_components(0.0, 0, 30, 100000.0)
        self.assertEqual(c["turnover_cost_pp"], 0.0)
        self.assertEqual(c["gas_drag_pp"], 0.0)
        self.assertEqual(c["total_cost_drag_pp"], 0.0)

    def test_gas_none_when_no_aum(self):
        c = cda.compute_cost_components(2.0, 5, 30, 0.0)
        self.assertIsNone(c["gas_drag_pp"])
        # total still includes the turnover component, gas treated as 0
        self.assertAlmostEqual(c["total_cost_drag_pp"], 0.20, places=9)

    def test_gas_none_when_aum_none(self):
        c = cda.compute_cost_components(2.0, 5, 30, None)
        self.assertIsNone(c["gas_drag_pp"])
        self.assertAlmostEqual(c["total_cost_drag_pp"], 0.20, places=9)

    def test_no_observations_no_gas(self):
        c = cda.compute_cost_components(2.0, 5, 0, 100000.0)
        self.assertIsNone(c["rebalances_per_year"])
        self.assertIsNone(c["gas_cost_annual_usd"])
        self.assertIsNone(c["gas_drag_pp"])

    def test_negative_turnover_clamped(self):
        c = cda.compute_cost_components(-3.0, 0, 30, 100000.0)
        self.assertEqual(c["turnover_cost_bps"], 0.0)
        self.assertEqual(c["turnover_cost_pp"], 0.0)

    def test_overridable_assumptions(self):
        c = cda.compute_cost_components(
            1.0, 1, 30, 100000.0,
            cost_per_turnover_bps=50.0, gas_per_rebalance_usd=100.0,
        )
        self.assertAlmostEqual(c["turnover_cost_pp"], 0.50, places=9)
        self.assertAlmostEqual(
            c["gas_cost_annual_usd"], (1 / 30) * 365 * 100.0, places=6
        )


# ─── Composed build: verdicts & metrics ────────────────────────────────────────


class TestBuildVerdicts(unittest.TestCase):
    def test_ok_low_cost(self):
        doc = _build(_yld(apy=5.0), _turn(annualized=0.5, rebal=1, obs=30))
        self.assertTrue(doc["available"])
        self.assertEqual(doc["verdict"], "ok")
        self.assertFalse(doc["low_sample"])
        self.assertGreater(doc["net_apy_pct"], 0)
        self.assertLessEqual(doc["cost_ratio"], cda.MODERATE_COST_RATIO)

    def test_warn_moderate_cost(self):
        doc = _build(_yld(apy=5.0), _turn(annualized=2.0, rebal=5, obs=30))
        self.assertEqual(doc["verdict"], "warn")
        self.assertGreater(doc["cost_ratio"], cda.MODERATE_COST_RATIO)
        self.assertLessEqual(doc["cost_ratio"], cda.HIGH_COST_RATIO)

    def test_fail_high_cost_ratio(self):
        doc = _build(_yld(apy=5.0), _turn(annualized=10.0, rebal=20, obs=30))
        self.assertEqual(doc["verdict"], "fail")
        self.assertGreater(doc["cost_ratio"], cda.HIGH_COST_RATIO)
        self.assertGreater(doc["net_apy_pct"], 0)  # high ratio but still positive

    def test_fail_negative_net(self):
        doc = _build(_yld(apy=1.0), _turn(annualized=10.0, rebal=20, obs=30))
        self.assertEqual(doc["verdict"], "fail")
        self.assertLessEqual(doc["net_apy_pct"], 0)

    def test_low_sample_caps_fail_to_warn(self):
        # obs=1 < MIN_RELIABLE_OBS; cost would be a fail, but capped to warn.
        doc = _build(_yld(apy=1.0), _turn(annualized=10.0, rebal=1, obs=1))
        self.assertTrue(doc["low_sample"])
        self.assertEqual(doc["verdict"], "warn")
        self.assertIn("low-sample", doc["verdict_reason"])

    def test_low_sample_does_not_promote_ok(self):
        # Even low-sample, a genuinely cheap book stays ok (cap only lowers fail).
        # rebal=0 → zero gas drag; tiny turnover → negligible variable cost.
        doc = _build(_yld(apy=10.0), _turn(annualized=0.1, rebal=0, obs=1))
        self.assertTrue(doc["low_sample"])
        self.assertEqual(doc["gas_drag_pp"], 0.0)
        self.assertEqual(doc["verdict"], "ok")

    def test_metrics_consistency(self):
        doc = _build(_yld(apy=5.0, aum=100000.0), _turn(annualized=2.0, rebal=5, obs=30))
        self.assertAlmostEqual(
            doc["net_apy_pct"],
            doc["gross_apy_pct"] - doc["total_cost_drag_pp"],
            places=6,
        )
        self.assertAlmostEqual(
            doc["cost_ratio"],
            doc["total_cost_drag_pp"] / doc["gross_apy_pct"],
            places=6,
        )
        self.assertAlmostEqual(
            doc["cost_drag_bps"], doc["total_cost_drag_pp"] * 100, places=4
        )

    def test_moderate_boundary_exactly_at_threshold_is_ok(self):
        # Construct cost_ratio == MODERATE exactly via overrides → "> MODERATE"
        # is strict, so exactly-equal stays ok. gross=10, want total=1.0.
        # turnover only (no gas): cost_per_turnover so that annualized*bps/100=1.0
        # annualized=1.0, bps=100 → 1.0 pp; obs high, rebal 0 → no gas.
        doc = _build(
            _yld(apy=10.0),
            _turn(annualized=1.0, rebal=0, obs=30),
            cost_per_turnover_bps=100.0,
        )
        self.assertAlmostEqual(doc["total_cost_drag_pp"], 1.0, places=9)
        self.assertAlmostEqual(doc["cost_ratio"], 0.10, places=9)
        self.assertEqual(doc["verdict"], "ok")


class TestBuildUnavailable(unittest.TestCase):
    def test_yield_unavailable(self):
        doc = _build(_yld(available=False), _turn())
        self.assertFalse(doc["available"])
        self.assertEqual(doc["reason"], "gross_yield_unavailable")
        self.assertIsNone(doc["verdict"])

    def test_turnover_unavailable(self):
        doc = _build(_yld(), _turn(available=False))
        self.assertFalse(doc["available"])
        self.assertEqual(doc["reason"], "turnover_unavailable")

    def test_missing_gross_apy(self):
        y = _yld()
        y["portfolio_apy_pp"] = None
        doc = _build(y, _turn())
        self.assertFalse(doc["available"])
        self.assertEqual(doc["reason"], "gross_yield_unavailable")

    def test_never_raises_on_garbage_upstream(self):
        for y, t in [
            (None, _turn()),
            (_yld(), None),
            ("garbage", _turn()),
            (_yld(), "garbage"),
            ({}, {}),
        ]:
            with self.subTest(y=y, t=t):
                doc = _build(y, t)
                self.assertIn("available", doc)
                self.assertFalse(doc["available"])

    def test_unavailable_schema_stable(self):
        doc = _build(_yld(available=False), _turn())
        for key in (
            "gross_apy_pct", "net_apy_pct", "total_cost_drag_pp",
            "turnover_cost_pp", "gas_drag_pp", "cost_ratio", "verdict",
        ):
            self.assertIn(key, doc)
            self.assertIsNone(doc[key])


class TestIsDemo(unittest.TestCase):
    def test_demo_false_both(self):
        doc = _build(_yld(is_demo=False), _turn(is_demo=False))
        self.assertFalse(doc["meta"]["is_demo"])

    def test_demo_true_from_yield(self):
        doc = _build(_yld(is_demo=True), _turn(is_demo=False))
        self.assertTrue(doc["meta"]["is_demo"])

    def test_demo_true_from_turnover(self):
        doc = _build(_yld(is_demo=False), _turn(is_demo=True))
        self.assertTrue(doc["meta"]["is_demo"])

    def test_demo_absent(self):
        y = _yld()
        y.pop("is_demo")
        t = _turn()
        t["meta"].pop("is_demo")
        doc = _build(y, t)
        self.assertIsNone(doc["meta"]["is_demo"])


# ─── content_fingerprint reuse-by-import ──────────────────────────────────────


class TestFingerprintReuse(unittest.TestCase):
    def test_is_same_object_as_tear_sheet(self):
        self.assertIs(cda.content_fingerprint, tear_sheet.content_fingerprint)

    def test_ignores_generated_at_and_history(self):
        a = _build(_yld(), _turn())
        b = json.loads(json.dumps(a))
        b["meta"]["generated_at"] = "2099-01-01T00:00:00+00:00"
        b["history"] = [{"x": 1}]
        self.assertEqual(cda.content_fingerprint(a), cda.content_fingerprint(b))

    def test_changes_with_content(self):
        a = _build(_yld(apy=5.0), _turn())
        b = _build(_yld(apy=6.0), _turn())
        self.assertNotEqual(cda.content_fingerprint(a), cda.content_fingerprint(b))

    def test_invalid_input(self):
        self.assertEqual(cda.content_fingerprint("nope"), "<invalid>")


# ─── Persistence (atomic, idempotent, rotation) ───────────────────────────────


class TestWriteStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / cda.STATUS_FILENAME

    def tearDown(self):
        for p in Path(self.tmp).glob("*"):
            p.unlink()
        os.rmdir(self.tmp)

    def _doc(self, apy=5.0):
        return _build(_yld(apy=apy), _turn())

    def test_first_write_then_idempotent(self):
        doc = self._doc()
        out1 = cda.write_status(doc, data_dir=self.tmp)
        self.assertTrue(out1["changed"])
        self.assertTrue(self.path.exists())
        md5_1 = hashlib.md5(self.path.read_bytes()).hexdigest()
        out2 = cda.write_status(doc, data_dir=self.tmp)
        self.assertFalse(out2["changed"])
        md5_2 = hashlib.md5(self.path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_changed_content_rewrites_and_grows_history(self):
        cda.write_status(self._doc(apy=5.0), data_dir=self.tmp)
        cda.write_status(self._doc(apy=6.0), data_dir=self.tmp)
        saved = json.loads(self.path.read_text())
        self.assertEqual(len(saved["history"]), 2)

    def test_history_rotation(self):
        doc = self._doc()
        big = dict(doc)
        big["history"] = [{"i": i} for i in range(cda.HISTORY_MAX + 50)]
        cda._atomic_write_json(self.path, big)
        changed = self._doc(apy=7.7)
        cda.write_status(changed, data_dir=self.tmp)
        saved = json.loads(self.path.read_text())
        self.assertEqual(len(saved["history"]), cda.HISTORY_MAX)

    def test_no_tmp_leak(self):
        cda.write_status(self._doc(), data_dir=self.tmp)
        self.assertEqual(list(Path(self.tmp).glob("*.tmp")), [])

    def test_tolerant_broken_prev(self):
        self.path.write_text("{ not json")
        out = cda.write_status(self._doc(), data_dir=self.tmp)
        self.assertTrue(out["changed"])
        self.assertTrue(self.path.exists())

    def test_history_entry_fields(self):
        doc = self._doc()
        entry = cda._history_entry(doc)
        for k in (
            "generated_at", "gross_apy_pct", "net_apy_pct",
            "total_cost_drag_pp", "cost_ratio", "verdict",
        ):
            self.assertIn(k, entry)


# ─── CLI (direct + subprocess) ────────────────────────────────────────────────


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for p in Path(self.tmp).glob("*"):
            p.unlink()
        os.rmdir(self.tmp)

    def test_check_default_no_write(self):
        rc = cda.main(["--data-dir", self.tmp])
        self.assertEqual(rc, 0)
        self.assertFalse((Path(self.tmp) / cda.STATUS_FILENAME).exists())

    def test_run_writes(self):
        # Real upstream over an empty dir → unavailable, but --run still writes.
        rc = cda.main(["--run", "--data-dir", self.tmp])
        self.assertEqual(rc, 0)
        self.assertTrue((Path(self.tmp) / cda.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        cda.main(["--run", "--data-dir", self.tmp])
        path = Path(self.tmp) / cda.STATUS_FILENAME
        md5_1 = hashlib.md5(path.read_bytes()).hexdigest()
        cda.main(["--run", "--data-dir", self.tmp])
        md5_2 = hashlib.md5(path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_arg_exit0(self):
        self.assertEqual(cda.main(["--frobnicate"]), 0)

    def test_check_run_conflict_exit0(self):
        self.assertEqual(cda.main(["--check", "--run"]), 0)

    def _subprocess(self, args):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.cost_drag_analytics", *args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )

    def test_subprocess_check(self):
        r = self._subprocess(["--check", "--data-dir", self.tmp])
        self.assertEqual(r.returncode, 0)

    def test_subprocess_run(self):
        r = self._subprocess(["--run", "--data-dir", self.tmp])
        self.assertEqual(r.returncode, 0)
        self.assertTrue((Path(self.tmp) / cda.STATUS_FILENAME).exists())

    def test_subprocess_junk_no_traceback(self):
        r = self._subprocess(["--frobnicate"])
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


# ─── Import hygiene (read-only boundary / no LLM/network) ──────────────────────


class TestImportHygiene(unittest.TestCase):
    def setUp(self):
        self.src_path = _REPO_ROOT / "spa_core" / "paper_trading" / "cost_drag_analytics.py"
        self.source = self.src_path.read_text(encoding="utf-8")

    def test_no_forbidden_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(self.source, str(self.src_path))
        self.assertEqual(violations, [], f"forbidden imports: {violations}")

    def test_compiles(self):
        import py_compile
        py_compile.compile(str(self.src_path), doraise=True)

    def test_no_network_or_llm_patterns(self):
        for bad in ("requests", "urllib.request", "web3", "socket",
                    "anthropic", "openai", "pandas", "numpy", "http.client"):
            self.assertNotIn(
                f"import {bad}", self.source, f"unexpected import {bad}"
            )

    def test_reuse_by_import_markers(self):
        self.assertIn("from spa_core.reporting.tear_sheet import content_fingerprint", self.source)
        self.assertIn("build_yield_attribution", self.source)
        self.assertIn("build_turnover_analytics", self.source)

    def test_atomic_write_pattern(self):
        # Atomic write contract: centralized atomic_save (tmp + os.replace) OR
        # the legacy inline tempfile.mkstemp + os.replace pattern.
        self.assertTrue(
            "atomic_save" in self.source
            or ("tempfile.mkstemp" in self.source and "os.replace" in self.source),
            "module must write atomically (atomic_save or tempfile.mkstemp+os.replace)",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
