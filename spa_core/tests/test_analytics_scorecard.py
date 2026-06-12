#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.analytics_scorecard (SPA-V444 / MP-122).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir.

Covers:
- extract_source_summary projection: verdict present / absent / unknown-string
  → None (+ note); available from explicit bool / from non-empty dict /
  missing → False; is_demo top-level + in meta + absent + non-bool ignored;
  generated_at from meta + top-level; stale True / False / unparsable → None
- build_scorecard aggregation: all ok → overall ok; one fail → fail; one warn
  (no fail) → warn; stale present → warn; demo present → warn; coverage < 60%
  → warn; nothing read → unknown; counts correctness; fails/warns/stale_sources/
  demo_sources lists; coverage_pct; sources sorted by (category, key)
- tolerance: each source in turn missing / broken-JSON / non-dict / empty /
  garbage (subTest) → never raises; fully empty data_dir → available false,
  overall unknown
- is_demo aggregation (any True → True; all False → False; no info → None)
- content_fingerprint REUSED-BY-IMPORT (is tear_sheet.content_fingerprint),
  ignores generated_at / history, stable, changes with content
- write_status: first → changed True + file; repeat identical → changed False +
  byte-identical md5; different → changed True + history grows; rotation exactly
  HISTORY_MAX (push 600); no stray *.tmp; tolerant of broken existing file
- CLI direct main() (--check no write; default == check; --run writes; repeat
  --run DATA_UNCHANGED; junk → ERROR stderr exit 0 no Traceback; --check/--run
  conflict) AND via subprocess (module run, repo-root cwd)
- import hygiene: real find_forbidden_imports from llm_forbidden_lint +
  py_compile + AST scan for forbidden libs + content_fingerprint reuse-by-import
- end-to-end: tempdir with ok/warn/fail/missing sources → build → write →
  rebuild from written → consistent
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import analytics_scorecard as sc
from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
from spa_core.reporting import tear_sheet as _tear_sheet

_MODULE_PATH = Path(sc.__file__)

_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────

# filename → key mapping derived from the registry.
_FILENAME_BY_KEY = {key: fn for key, fn, _t, _c in sc.SOURCE_REGISTRY}


def _ts(hours_ago: float = 1.0) -> str:
    """ISO timestamp `hours_ago` hours before _NOW."""
    return (_NOW - timedelta(hours=hours_ago)).isoformat()


def _write_source(data_dir: Path, key: str, doc: Any) -> None:
    """Write a mini source artifact for the registry `key` into `data_dir`."""
    filename = _FILENAME_BY_KEY[key]
    (data_dir / filename).write_text(json.dumps(doc), encoding="utf-8")


def _write_raw(data_dir: Path, key: str, text: str) -> None:
    """Write raw (possibly broken) text for the registry `key`."""
    filename = _FILENAME_BY_KEY[key]
    (data_dir / filename).write_text(text, encoding="utf-8")


def _src(verdict: Optional[str] = None, *, generated_at: Optional[str] = None,
         is_demo: Any = "__absent__", available: Any = True,
         in_meta: bool = False) -> Dict[str, Any]:
    """Construct a mini source doc with optional fields."""
    doc: Dict[str, Any] = {}
    if available != "__absent__":
        doc["available"] = available
    if verdict is not None:
        doc["verdict"] = verdict
    if generated_at is None:
        generated_at = _ts(1.0)
    meta: Dict[str, Any] = {"generated_at": generated_at}
    if is_demo != "__absent__":
        if in_meta:
            meta["is_demo"] = is_demo
        else:
            doc["is_demo"] = is_demo
    doc["meta"] = meta
    return doc


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="scorecard_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. extract_source_summary projection
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractSourceSummary(unittest.TestCase):

    def _ex(self, doc: Any) -> Dict[str, Any]:
        return sc.extract_source_summary("k", "Title", "risk", doc, now=_NOW)

    def test_missing_doc_none(self):
        s = self._ex(None)
        self.assertFalse(s["available"])
        self.assertEqual(s["note"], "missing")
        self.assertIsNone(s["verdict"])
        self.assertIsNone(s["stale"])

    def test_verdict_ok(self):
        self.assertEqual(self._ex({"verdict": "ok"})["verdict"], "ok")

    def test_verdict_warn(self):
        self.assertEqual(self._ex({"verdict": "warn"})["verdict"], "warn")

    def test_verdict_fail(self):
        self.assertEqual(self._ex({"verdict": "fail"})["verdict"], "fail")

    def test_verdict_absent_is_none(self):
        self.assertIsNone(self._ex({"available": True, "x": 1})["verdict"])

    def test_verdict_unknown_string_normalised_none(self):
        s = self._ex({"verdict": "weird"})
        self.assertIsNone(s["verdict"])
        self.assertIn("unknown verdict", s.get("note", ""))

    def test_verdict_uppercase_normalised(self):
        self.assertEqual(self._ex({"verdict": "OK"})["verdict"], "ok")

    def test_verdict_non_string_ignored(self):
        s = self._ex({"verdict": 3, "x": 1})
        self.assertIsNone(s["verdict"])
        self.assertNotIn("note", s)

    def test_available_explicit_true(self):
        self.assertTrue(self._ex({"available": True})["available"])

    def test_available_explicit_false(self):
        self.assertFalse(self._ex({"available": False, "x": 1})["available"])

    def test_available_from_nonempty_dict(self):
        # no explicit flag, but real content
        self.assertTrue(self._ex({"foo": "bar"})["available"])

    def test_available_empty_dict_false(self):
        self.assertFalse(self._ex({})["available"])

    def test_available_only_available_key_no_content(self):
        # bare {"available": <non-bool>} has no meaningful content
        self.assertFalse(self._ex({"available": "yes"})["available"])

    def test_is_demo_top_level_true(self):
        self.assertTrue(self._ex({"is_demo": True, "x": 1})["is_demo"])

    def test_is_demo_top_level_false(self):
        self.assertFalse(self._ex({"is_demo": False, "x": 1})["is_demo"])

    def test_is_demo_in_meta(self):
        self.assertTrue(self._ex({"meta": {"is_demo": True}})["is_demo"])

    def test_is_demo_meta_precedence(self):
        # meta wins over top-level
        d = {"is_demo": False, "meta": {"is_demo": True}}
        self.assertTrue(self._ex(d)["is_demo"])

    def test_is_demo_absent_none(self):
        self.assertIsNone(self._ex({"x": 1})["is_demo"])

    def test_is_demo_non_bool_ignored(self):
        self.assertIsNone(self._ex({"is_demo": "yes", "x": 1})["is_demo"])

    def test_generated_at_from_meta(self):
        d = {"meta": {"generated_at": "2026-06-12T00:00:00+00:00"}}
        self.assertEqual(self._ex(d)["generated_at"], "2026-06-12T00:00:00+00:00")

    def test_generated_at_top_level(self):
        d = {"generated_at": "2026-06-12T00:00:00+00:00", "x": 1}
        self.assertEqual(self._ex(d)["generated_at"], "2026-06-12T00:00:00+00:00")

    def test_generated_at_absent_none(self):
        self.assertIsNone(self._ex({"x": 1})["generated_at"])

    def test_stale_false_recent(self):
        d = {"meta": {"generated_at": _ts(1.0)}}
        self.assertFalse(self._ex(d)["stale"])

    def test_stale_true_old(self):
        d = {"meta": {"generated_at": _ts(100.0)}}
        self.assertTrue(self._ex(d)["stale"])

    def test_stale_boundary_just_under_48h(self):
        d = {"meta": {"generated_at": _ts(47.0)}}
        self.assertFalse(self._ex(d)["stale"])

    def test_stale_boundary_just_over_48h(self):
        d = {"meta": {"generated_at": _ts(49.0)}}
        self.assertTrue(self._ex(d)["stale"])

    def test_stale_unparsable_none(self):
        d = {"meta": {"generated_at": "not-a-date"}}
        self.assertIsNone(self._ex(d)["stale"])

    def test_stale_z_suffix_parsed(self):
        d = {"meta": {"generated_at": "2026-06-12T11:00:00Z"}}
        self.assertFalse(self._ex(d)["stale"])

    def test_non_dict_doc_unavailable(self):
        s = self._ex([1, 2, 3])
        self.assertFalse(s["available"])
        self.assertIsNone(s["verdict"])

    def test_summary_carries_identity(self):
        s = self._ex({"verdict": "ok"})
        self.assertEqual(s["key"], "k")
        self.assertEqual(s["title"], "Title")
        self.assertEqual(s["category"], "risk")

    def test_never_raises_on_garbage(self):
        for g in (None, [], {}, 42, "str", {"verdict": None}, {"meta": 5}):
            with self.subTest(g=g):
                s = self._ex(g)
                self.assertIn("available", s)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. build_scorecard aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildAggregation(_TmpBase):

    def _all(self, verdict: str) -> Dict[str, Any]:
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src(verdict, generated_at=_ts(1.0)))
        return sc.build_scorecard(data_dir=self.data_dir, now=_NOW)

    def test_all_ok_overall_ok(self):
        d = self._all("ok")
        self.assertEqual(d["overall_status"], "ok")
        self.assertEqual(d["counts"]["ok"], len(sc.SOURCE_REGISTRY))

    def test_one_fail_overall_fail(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        _write_source(self.data_dir, "concentration", _src("fail"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "fail")
        self.assertIn("concentration", d["fails"])
        self.assertEqual(d["counts"]["fail"], 1)

    def test_one_warn_no_fail_overall_warn(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        _write_source(self.data_dir, "yield_attr", _src("warn"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "warn")
        self.assertIn("yield_attr", d["warns"])

    def test_stale_present_overall_warn(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        _write_source(self.data_dir, "tail_risk", _src("ok", generated_at=_ts(100.0)))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "warn")
        self.assertIn("tail_risk", d["stale_sources"])

    def test_demo_present_overall_warn(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", is_demo=False))
        _write_source(self.data_dir, "drawdown", _src("ok", is_demo=True))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "warn")
        self.assertIn("drawdown", d["demo_sources"])

    def test_low_coverage_overall_warn(self):
        # only 3 of 10 available, all ok → coverage 30% < 60% → warn
        for key in ("drawdown", "tail_risk", "turnover"):
            _write_source(self.data_dir, key, _src("ok"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "warn")
        self.assertLess(d["coverage_pct"], 60.0)

    def test_nothing_read_overall_unknown(self):
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "unknown")
        self.assertFalse(d["available"])

    def test_fail_beats_warn_and_stale(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("warn", generated_at=_ts(100.0)))
        _write_source(self.data_dir, "risk_contrib", _src("fail"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "fail")

    def test_counts_correctness(self):
        verdicts = ["ok", "ok", "warn", "fail", "ok", "warn", "ok", "ok", "fail", "ok"]
        for (key, _fn, _t, _c), v in zip(sc.SOURCE_REGISTRY, verdicts):
            _write_source(self.data_dir, key, _src(v))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        c = d["counts"]
        self.assertEqual(c["ok"], 6)
        self.assertEqual(c["warn"], 2)
        self.assertEqual(c["fail"], 2)
        self.assertEqual(c["total_sources"], 10)
        self.assertEqual(c["unavailable"], 0)

    def test_unknown_verdict_counted(self):
        # available source but no verdict → unknown_verdict
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, {"available": True, "x": 1,
                                               "meta": {"generated_at": _ts(1.0)}})
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["counts"]["unknown_verdict"], 10)
        # all available (coverage 100%) but no real verdict anywhere → unknown
        self.assertEqual(d["overall_status"], "unknown")

    def test_coverage_pct_value(self):
        for key in ("drawdown", "tail_risk", "turnover", "correlation", "concentration"):
            _write_source(self.data_dir, key, _src("ok"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["coverage_pct"], 50.0)

    def test_sources_sorted_by_category_then_key(self):
        d = self._all("ok")
        pairs = [(s["category"], s["key"]) for s in d["sources"]]
        self.assertEqual(pairs, sorted(pairs))

    def test_overall_reason_mentions_fail(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        _write_source(self.data_dir, "concentration", _src("fail"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertIn("FAIL", d["overall_reason"].upper())

    def test_lists_are_keys(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        _write_source(self.data_dir, "concentration", _src("fail"))
        _write_source(self.data_dir, "yield_attr", _src("warn"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["fails"], ["concentration"])
        self.assertEqual(d["warns"], ["yield_attr"])

    def test_schema_keys_stable_when_empty(self):
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        for k in ("meta", "available", "overall_status", "overall_reason",
                  "is_demo", "counts", "fails", "warns", "stale_sources",
                  "demo_sources", "coverage_pct", "sources"):
            self.assertIn(k, d)

    def test_meta_fields(self):
        d = self._all("ok")
        m = d["meta"]
        self.assertEqual(m["source"], "analytics_scorecard")
        self.assertEqual(m["schema_version"], 1)
        self.assertTrue(m["advisory_only"])
        self.assertEqual(m["disclaimer"], "NOT investment advice")
        self.assertEqual(m["stale_hours"], 48)
        self.assertEqual(m["real_track_start"], "2026-06-10")
        self.assertIn("generated_at", m)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. is_demo aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsDemoAggregation(_TmpBase):

    def test_any_true_is_true(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", is_demo=False))
        _write_source(self.data_dir, "drawdown", _src("ok", is_demo=True))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertTrue(d["is_demo"])

    def test_all_false_is_false(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", is_demo=False))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertFalse(d["is_demo"])

    def test_no_info_is_none(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertIsNone(d["is_demo"])

    def test_meta_top_consistency(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", is_demo=True))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["is_demo"], d["meta"]["is_demo"])


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tolerance to broken / garbage inputs
# ═══════════════════════════════════════════════════════════════════════════════

class TestTolerance(_TmpBase):

    def test_each_source_garbage_never_raises(self):
        garbage_variants = [
            ("missing", None),
            ("broken_json", "{nonsense"),
            ("non_dict", "[1, 2, 3]"),
            ("empty_dict", "{}"),
            ("garbage_str", '"just a string"'),
        ]
        for key in _FILENAME_BY_KEY:
            for label, payload in garbage_variants:
                with self.subTest(key=key, variant=label):
                    # fresh dir each time: all other sources ok
                    tmp = Path(tempfile.mkdtemp(prefix="tol_"))
                    try:
                        for k2 in _FILENAME_BY_KEY:
                            _write_source(tmp, k2, _src("ok"))
                        if payload is None:
                            (tmp / _FILENAME_BY_KEY[key]).unlink()
                        else:
                            _write_raw(tmp, key, payload)
                        d = sc.build_scorecard(data_dir=tmp, now=_NOW)
                        self.assertIn("overall_status", d)
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)

    def test_fully_empty_dir(self):
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertFalse(d["available"])
        self.assertEqual(d["overall_status"], "unknown")
        self.assertEqual(d["counts"]["unavailable"], 10)

    def test_all_broken_json_unknown(self):
        for key in _FILENAME_BY_KEY:
            _write_raw(self.data_dir, key, "{not json")
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "unknown")
        self.assertFalse(d["available"])

    def test_nonexistent_data_dir(self):
        d = sc.build_scorecard(data_dir=self.data_dir / "nope", now=_NOW)
        self.assertEqual(d["overall_status"], "unknown")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. content_fingerprint (reused from tear_sheet)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def _doc(self, overall: str = "ok") -> Dict[str, Any]:
        return {"meta": {"generated_at": "x", "source": "analytics_scorecard"},
                "overall_status": overall, "counts": {"ok": 1}}

    def test_reuses_tear_sheet_fingerprint(self):
        self.assertIs(sc.content_fingerprint, _tear_sheet.content_fingerprint)

    def test_ignores_generated_at(self):
        a = self._doc()
        b = self._doc()
        b["meta"] = {"generated_at": "DIFFERENT", "source": "analytics_scorecard"}
        self.assertEqual(sc.content_fingerprint(a), sc.content_fingerprint(b))

    def test_ignores_history(self):
        a = self._doc()
        b = dict(self._doc())
        b["history"] = [{"x": 1}, {"y": 2}]
        self.assertEqual(sc.content_fingerprint(a), sc.content_fingerprint(b))

    def test_changes_with_content(self):
        self.assertNotEqual(
            sc.content_fingerprint(self._doc("ok")),
            sc.content_fingerprint(self._doc("fail")),
        )

    def test_stable(self):
        d = self._doc()
        self.assertEqual(sc.content_fingerprint(d), sc.content_fingerprint(d))

    def test_non_dict_input(self):
        self.assertIsInstance(sc.content_fingerprint(None), str)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. write_status / idempotency / history
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _doc(self, overall: str = "ok") -> Dict[str, Any]:
        return {
            "meta": {"source": "analytics_scorecard",
                     "generated_at": datetime.now(timezone.utc).isoformat()},
            "available": True,
            "overall_status": overall,
            "counts": {"ok": 1, "warn": 0, "fail": 0},
            "coverage_pct": 100.0,
        }

    def test_first_write_changed_true(self):
        out = sc.write_status(self._doc("ok"), self.data_dir)
        self.assertTrue(out["changed"])
        self.assertTrue((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_second_identical_unchanged(self):
        d = self._doc("ok")
        sc.write_status(d, self.data_dir)
        out = sc.write_status(d, self.data_dir)
        self.assertFalse(out["changed"])

    def test_byte_identical_on_repeat(self):
        p = self.data_dir / sc.STATUS_FILENAME
        d = self._doc("ok")
        sc.write_status(d, self.data_dir)
        md5_1 = hashlib.md5(p.read_bytes()).hexdigest()
        sc.write_status(d, self.data_dir)
        md5_2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_idempotent_ignores_generated_at_drift(self):
        d1 = self._doc("ok")
        sc.write_status(d1, self.data_dir)
        d2 = self._doc("ok")
        d2["meta"]["generated_at"] = "2099-01-01T00:00:00+00:00"
        out = sc.write_status(d2, self.data_dir)
        self.assertFalse(out["changed"])

    def test_different_content_rewrites(self):
        sc.write_status(self._doc("ok"), self.data_dir)
        out = sc.write_status(self._doc("fail"), self.data_dir)
        self.assertTrue(out["changed"])

    def test_history_grows(self):
        sc.write_status(self._doc("ok"), self.data_dir)
        sc.write_status(self._doc("warn"), self.data_dir)
        sc.write_status(self._doc("fail"), self.data_dir)
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 3)

    def test_history_entry_shape(self):
        sc.write_status(self._doc("ok"), self.data_dir)
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        h = doc["history"][-1]
        for k in ("generated_at", "overall_status", "ok", "warn", "fail",
                  "coverage_pct"):
            self.assertIn(k, h)

    def test_history_rotation_exactly_max(self):
        for i in range(sc.HISTORY_MAX + 100):
            sc.write_status(self._doc(f"v{i}"), self.data_dir)
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), sc.HISTORY_MAX)

    def test_no_stray_tmp_files(self):
        for i in range(5):
            sc.write_status(self._doc(f"v{i}"), self.data_dir)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.data_dir.glob(".*tmp*")), [])

    def test_tolerant_of_broken_existing(self):
        (self.data_dir / sc.STATUS_FILENAME).write_text("NOT JSON")
        out = sc.write_status(self._doc("ok"), self.data_dir)
        self.assertTrue(out["changed"])
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertIn("overall_status", doc)

    def test_history_max_value(self):
        self.assertEqual(sc.HISTORY_MAX, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. CLI (direct main)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI(_TmpBase):

    def _setup_valid(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", generated_at=_ts(1.0)))

    def test_check_does_not_write(self):
        self._setup_valid()
        rc = sc.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        self._setup_valid()
        rc = sc.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_run_writes(self):
        self._setup_valid()
        rc = sc.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_run_idempotent_md5(self):
        self._setup_valid()
        p = self.data_dir / sc.STATUS_FILENAME
        sc.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(p.read_bytes()).hexdigest()
        sc.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_arg_exit_zero_error_stderr(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = sc.main(["--totally-bogus-arg"])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())
        self.assertNotIn("Traceback", cap.getvalue())

    def test_check_run_conflict_exit_zero(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = sc.main(["--check", "--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())
        self.assertFalse((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_missing_data_exit_zero(self):
        rc = sc.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_run_prints_data_written_then_unchanged(self):
        self._setup_valid()
        cap = io.StringIO()
        old = sys.stdout
        sys.stdout = cap
        try:
            sc.main(["--run", "--data-dir", str(self.data_dir)])
            sc.main(["--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stdout = old
        out = cap.getvalue()
        self.assertIn("DATA_WRITTEN", out)
        self.assertIn("DATA_UNCHANGED", out)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. CLI (subprocess)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLISubprocess(_TmpBase):

    _MOD = "spa_core.paper_trading.analytics_scorecard"

    def _setup_valid(self):
        for key in _FILENAME_BY_KEY:
            _write_source(self.data_dir, key, _src("ok", generated_at=_ts(1.0)))

    def _run(self, args: List[str]):
        return subprocess.run(
            [sys.executable, "-m", self._MOD, *args],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )

    def test_subprocess_check(self):
        self._setup_valid()
        r = self._run(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(r.returncode, 0)
        self.assertIn("overall_status", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_subprocess_run_writes(self):
        self._setup_valid()
        r = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(r.returncode, 0)
        self.assertIn("DATA_WRITTEN", r.stdout)
        self.assertTrue((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_subprocess_run_idempotent(self):
        self._setup_valid()
        self._run(["--run", "--data-dir", str(self.data_dir)])
        r = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertIn("DATA_UNCHANGED", r.stdout)

    def test_subprocess_junk_exit_zero_no_traceback(self):
        r = self._run(["--bogus-arg"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("ERROR", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_subprocess_no_tmp_leak(self):
        self._setup_valid()
        for _ in range(2):
            self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Import / AST hygiene
# ═══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_IMPORTS = {
    "requests", "httpx", "aiohttp", "urllib3", "urllib",
    "web3", "eth_account",
    "numpy", "pandas", "scipy",
    "anthropic", "openai", "langchain", "litellm",
    "socket", "http",
}


class TestImportHygiene(unittest.TestCase):

    def _collect_imports(self, source: str) -> set:
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[0])
        return names

    def test_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_IMPORTS
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_real_llm_forbidden_lint(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        violations = find_forbidden_imports(source, str(_MODULE_PATH))
        self.assertEqual(violations, [], msg=f"LLM SDK imports: {violations}")

    def test_module_compiles(self):
        py_compile.compile(str(_MODULE_PATH), doraise=True)

    def test_test_module_compiles(self):
        py_compile.compile(str(Path(__file__)), doraise=True)

    def test_no_network_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("requests.get", "requests.post", "urllib.request",
                        "http.client", "socket.connect", "web3."):
            self.assertNotIn(pattern, source, msg=f"network pattern: {pattern}")

    def test_no_llm_sdk_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("anthropic.", "openai.", "from anthropic", "from openai"):
            self.assertNotIn(pattern, source, msg=f"LLM SDK pattern: {pattern}")

    def test_atomic_write_pattern_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("os.replace", source)
        self.assertIn("tempfile.mkstemp", source)

    def test_content_fingerprint_imported_from_tear_sheet(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.reporting.tear_sheet import content_fingerprint",
            source)
        self.assertNotIn("def content_fingerprint", source)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. End-to-end smoke
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd(_TmpBase):

    def test_full_pipeline_round_trip(self):
        # one ok, one warn, one fail, one missing (rest unavailable)
        _write_source(self.data_dir, "drawdown", _src("ok"))
        _write_source(self.data_dir, "yield_attr", _src("warn"))
        _write_source(self.data_dir, "concentration", _src("fail"))
        # turnover deliberately not written → missing
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "fail")
        self.assertIn("concentration", d["fails"])
        self.assertIn("yield_attr", d["warns"])

        out1 = sc.write_status(d, self.data_dir)
        self.assertTrue(out1["changed"])
        out2 = sc.write_status(d, self.data_dir)
        self.assertFalse(out2["changed"])

        # rebuild from disk and confirm written scorecard is consistent
        written = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertEqual(written["overall_status"], "fail")
        self.assertEqual(written["counts"]["fail"], 1)
        self.assertIn("history", written)

    def test_mixed_with_stale_and_demo(self):
        _write_source(self.data_dir, "drawdown",
                      _src("ok", generated_at=_ts(200.0)))  # stale
        _write_source(self.data_dir, "tail_risk", _src("ok", is_demo=True))
        _write_source(self.data_dir, "turnover", _src("ok"))
        d = sc.build_scorecard(data_dir=self.data_dir, now=_NOW)
        self.assertEqual(d["overall_status"], "warn")
        self.assertIn("drawdown", d["stale_sources"])
        self.assertIn("tail_risk", d["demo_sources"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
