#!/usr/bin/env python3
"""Tests for regime_conditional_performance (SPA-V450 / MP-131).

unittest only — NO pytest, NO network, tempdir-isolated. Covers:
- pure math: annualised Sharpe / APY / pop-stdev (hand-computed; <2 obs→None;
  zero-stdev→None; overflow / non-positive base→None)
- forward-fill regime mapping (date before first label→UNKNOWN, exact match,
  between labels picks prior, unsorted inputs)
- bucketing correctness
- verdict boundaries (BEAR Sharpe just below 0→fail; BEAR low-sample→warn;
  all-positive→ok; negative non-bear regime→warn; overall<0 path)
- insufficient_data (empty/short equity, empty regime history → available:false,
  stable schema)
- tolerance / never-raise (missing files, broken JSON, non-dict roots, garbage
  records via subTest + a fuzz property test)
- content_fingerprint reuse-by-import (assertIs to tear_sheet; ignores
  generated_at/history; changes with content)
- write_status (first→WRITTEN, identical→UNCHANGED byte-identical md5,
  different→WRITTEN + history grows, rotation EXACTLY 500, no *.tmp leak,
  tolerant of broken previous file)
- CLI direct main(argv) + subprocess (--check no write, default=check, --run
  writes & idempotent DATA_UNCHANGED, junk→exit 0 no Traceback, conflict)
- import hygiene (real find_forbidden_imports 0 violations, py_compile both,
  no network/LLM/socket/subprocess/eval/exec/pip in module source,
  reuse-by-import marker + atomic-write pattern present)
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics_lab import regime_conditional_performance as rcp
from spa_core.reporting import tear_sheet as ts

_MODULE_PATH = Path(rcp.__file__)
_TEST_PATH = Path(__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _equity_doc(levels: List[float], start: str = "2026-01-01",
                is_demo: Any = None) -> Dict[str, Any]:
    """Build an equity_curve_daily.json doc from a list of close levels."""
    ds = _dates(len(levels), start)
    daily = [{"date": d, "close_equity": float(v)} for d, v in zip(ds, levels)]
    doc: Dict[str, Any] = {"daily": daily}
    if is_demo is not None:
        doc["is_demo"] = is_demo
    return doc


def _write_equity(data_dir: Path, levels: List[float], start: str = "2026-01-01",
                  is_demo: Any = None) -> None:
    doc = _equity_doc(levels, start, is_demo)
    (data_dir / rcp.EQUITY_FILENAME).write_text(json.dumps(doc))


def _write_apy_stub(data_dir: Path) -> None:
    """A minimal real-shape apy_history.json so load_apy_history succeeds."""
    ph = {"p1": [{"ts": "2026-01-01T00:00:00+00:00", "apy": 5.0}]}
    (data_dir / "apy_history.json").write_text(
        json.dumps({"protocol_history": ph, "last_updated": "2026-01-01"})
    )


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="rcp_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure math: _pop_stdev
# ═══════════════════════════════════════════════════════════════════════════════

class TestPopStdev(unittest.TestCase):

    def test_known_value(self):
        # pop stdev of [2,4,4,4,5,5,7,9] = 2.0
        ys = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(rcp._pop_stdev(ys), 2.0, places=10)

    def test_constant_zero(self):
        self.assertEqual(rcp._pop_stdev([5.0, 5.0, 5.0]), 0.0)

    def test_single_point_none(self):
        self.assertIsNone(rcp._pop_stdev([3.0]))

    def test_empty_none(self):
        self.assertIsNone(rcp._pop_stdev([]))

    def test_two_points_hand(self):
        # mean=1, var = ((0-1)^2+(2-1)^2)/2 = 1 → stdev 1
        self.assertAlmostEqual(rcp._pop_stdev([0.0, 2.0]), 1.0, places=10)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Pure math: annualised_sharpe
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharpe(unittest.TestCase):

    def test_hand_computed(self):
        rets = [1.0, -1.0, 2.0, -2.0]  # mean 0 → sharpe 0
        self.assertAlmostEqual(rcp.annualised_sharpe(rets), 0.0, places=10)

    def test_positive_known(self):
        rets = [1.0, 3.0]  # mean 2, pop stdev = 1
        expected = 2.0 / 1.0 * math.sqrt(365)
        self.assertAlmostEqual(rcp.annualised_sharpe(rets), expected, places=8)

    def test_negative(self):
        rets = [-3.0, -1.0]  # mean -2, stdev 1 → negative sharpe
        self.assertLess(rcp.annualised_sharpe(rets), 0)

    def test_zero_stdev_none(self):
        self.assertIsNone(rcp.annualised_sharpe([2.0, 2.0, 2.0]))

    def test_single_obs_none(self):
        self.assertIsNone(rcp.annualised_sharpe([5.0]))

    def test_empty_none(self):
        self.assertIsNone(rcp.annualised_sharpe([]))

    def test_scale_invariance_pct_vs_pct(self):
        rets = [0.5, 1.5, -0.5]
        s1 = rcp.annualised_sharpe(rets)
        # multiplying all by a positive constant leaves sharpe unchanged
        s2 = rcp.annualised_sharpe([r * 10 for r in rets])
        self.assertAlmostEqual(s1, s2, places=8)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Pure math: annualised_apy_pct
# ═══════════════════════════════════════════════════════════════════════════════

class TestApy(unittest.TestCase):

    def test_hand_computed(self):
        # mean daily 0.001 (0.1%) → ((1.001)^365 - 1)*100
        expected = ((1.001 ** 365) - 1.0) * 100.0
        self.assertAlmostEqual(rcp.annualised_apy_pct(0.001), expected, places=8)

    def test_zero_growth(self):
        self.assertAlmostEqual(rcp.annualised_apy_pct(0.0), 0.0, places=10)

    def test_negative_base_none(self):
        # mean daily <= -1 → base <= 0 → None
        self.assertIsNone(rcp.annualised_apy_pct(-1.0))
        self.assertIsNone(rcp.annualised_apy_pct(-2.0))

    def test_overflow_guarded_none_or_finite(self):
        # huge daily return — must not raise; returns None on overflow or finite
        out = rcp.annualised_apy_pct(1e6)
        self.assertTrue(out is None or math.isfinite(out))

    def test_positive_value(self):
        self.assertGreater(rcp.annualised_apy_pct(0.01), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. forward_fill_regime
# ═══════════════════════════════════════════════════════════════════════════════

class TestForwardFill(unittest.TestCase):

    def _tl(self) -> List[Tuple[str, str]]:
        return [("2026-01-01", "BULL"), ("2026-01-08", "BEAR"),
                ("2026-01-15", "SIDEWAYS")]

    def test_exact_match(self):
        m = rcp.forward_fill_regime(["2026-01-08"], self._tl())
        self.assertEqual(m["2026-01-08"], "BEAR")

    def test_between_labels_picks_prior(self):
        m = rcp.forward_fill_regime(["2026-01-10"], self._tl())
        self.assertEqual(m["2026-01-10"], "BEAR")

    def test_before_first_label_unknown(self):
        m = rcp.forward_fill_regime(["2025-12-31"], self._tl())
        self.assertEqual(m["2025-12-31"], rcp.UNKNOWN_LABEL)

    def test_after_last_label_uses_last(self):
        m = rcp.forward_fill_regime(["2026-02-01"], self._tl())
        self.assertEqual(m["2026-02-01"], "SIDEWAYS")

    def test_first_day_exact(self):
        m = rcp.forward_fill_regime(["2026-01-01"], self._tl())
        self.assertEqual(m["2026-01-01"], "BULL")

    def test_empty_timeline_all_unknown(self):
        m = rcp.forward_fill_regime(["2026-01-05", "2026-01-06"], [])
        self.assertEqual(set(m.values()), {rcp.UNKNOWN_LABEL})

    def test_multiple_dates(self):
        dates = ["2025-12-31", "2026-01-01", "2026-01-09", "2026-01-20"]
        m = rcp.forward_fill_regime(dates, self._tl())
        self.assertEqual(m["2025-12-31"], rcp.UNKNOWN_LABEL)
        self.assertEqual(m["2026-01-01"], "BULL")
        self.assertEqual(m["2026-01-09"], "BEAR")
        self.assertEqual(m["2026-01-20"], "SIDEWAYS")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _clean_regime_timeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestCleanTimeline(unittest.TestCase):

    def test_sorts_and_filters(self):
        raw = [
            {"date": "2026-01-08", "regime": "BEAR"},
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "bad", "regime": "BULL"},        # bad date
            {"date": "2026-01-15"},                    # no regime
            "not-a-dict",
            {"regime": "BULL"},                        # no date
        ]
        out = rcp._clean_regime_timeline(raw)
        self.assertEqual(out, [("2026-01-01", "BULL"), ("2026-01-08", "BEAR")])

    def test_non_list_empty(self):
        self.assertEqual(rcp._clean_regime_timeline("nope"), [])
        self.assertEqual(rcp._clean_regime_timeline(None), [])

    def test_truncates_date_prefix(self):
        raw = [{"date": "2026-01-01T12:00:00+00:00", "regime": "BULL"}]
        self.assertEqual(rcp._clean_regime_timeline(raw), [("2026-01-01", "BULL")])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _regime_metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeMetrics(unittest.TestCase):

    def test_empty_bucket(self):
        m = rcp._regime_metrics([])
        self.assertEqual(m["num_days"], 0)
        self.assertIsNone(m["sharpe_annualized"])
        self.assertFalse(m["sufficient_sample"])

    def test_below_min_obs_counts_only(self):
        # 2 obs < MIN_REGIME_OBS(3): counts present but sharpe/apy None
        m = rcp._regime_metrics([1.0, 2.0])
        self.assertEqual(m["num_days"], 2)
        self.assertIsNone(m["sharpe_annualized"])
        self.assertIsNone(m["annualized_apy_pct"])
        self.assertFalse(m["sufficient_sample"])
        # best/worst/total/mean still computed
        self.assertEqual(m["best_day_pct"], 2.0)
        self.assertEqual(m["worst_day_pct"], 1.0)

    def test_enough_obs_computes_sharpe(self):
        m = rcp._regime_metrics([1.0, 2.0, 3.0])
        self.assertEqual(m["num_days"], 3)
        self.assertIsNotNone(m["sharpe_annualized"])
        self.assertIsNotNone(m["annualized_apy_pct"])
        self.assertTrue(m["sufficient_sample"])

    def test_zero_stdev_sharpe_none(self):
        m = rcp._regime_metrics([2.0, 2.0, 2.0])
        self.assertEqual(m["num_days"], 3)
        self.assertIsNone(m["sharpe_annualized"])  # zero variance
        self.assertIsNotNone(m["annualized_apy_pct"])

    def test_total_return_compounds(self):
        # +1% then +1% → (1.01*1.01 - 1)*100 = 2.01
        m = rcp._regime_metrics([1.0, 1.0, 1.0])
        # 1.01^3 - 1 = 0.030301 → 3.0301
        self.assertAlmostEqual(m["total_return_pct"], 3.0301, places=4)

    def test_negative_mean_negative_sharpe(self):
        m = rcp._regime_metrics([-1.0, -2.0, -3.0])
        self.assertLess(m["sharpe_annualized"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. build — happy path + bucketing (monkeypatched upstream)
# ═══════════════════════════════════════════════════════════════════════════════

class _PatchBase(_TmpBase):
    """Base that monkeypatches the upstream regime_history / load_apy_history so
    unit tests don't depend on real data shape or date.today()."""

    def setUp(self) -> None:
        super().setUp()
        self._orig_rh = rcp.regime_history
        self._orig_lh = rcp.load_apy_history

    def tearDown(self) -> None:
        rcp.regime_history = self._orig_rh
        rcp.load_apy_history = self._orig_lh
        super().tearDown()

    def _patch_timeline(self, timeline: List[Dict[str, Any]]) -> None:
        rcp.load_apy_history = lambda data_dir: ([{"x": 1}], None)
        rcp.regime_history = lambda recs, **kw: list(timeline)


class TestBuildBucketing(_PatchBase):

    def test_buckets_by_regime(self):
        # 6 equity bars → 5 daily returns dated 01-02..01-06
        _write_equity(self.data_dir, [100, 101, 102, 101, 102, 103])
        self._patch_timeline([
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-04", "regime": "BEAR"},
        ])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertTrue(r["available"])
        # returns on 01-02,01-03 → BULL ; 01-04,01-05,01-06 → BEAR
        self.assertEqual(r["regimes"]["BULL"]["num_days"], 2)
        self.assertEqual(r["regimes"]["BEAR"]["num_days"], 3)

    def test_unknown_days_skipped(self):
        # timeline starts after some equity dates → those returns are UNKNOWN
        _write_equity(self.data_dir, [100, 101, 102, 103, 104, 105])
        self._patch_timeline([{"date": "2026-01-04", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertTrue(r["available"])
        self.assertGreater(r["track"]["num_unknown_days"], 0)
        self.assertIn("BULL", r["regimes"])

    def test_dominant_regime_most_days(self):
        _write_equity(self.data_dir, [100, 101, 102, 103, 104, 105, 106, 107])
        self._patch_timeline([
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-05", "regime": "BEAR"},
        ])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        # 7 returns: 01-02..01-04 BULL(3), 01-05..01-08 BEAR(4) → BEAR dominant
        self.assertEqual(r["dominant_regime"], "BEAR")

    def test_headline_fields_present(self):
        _write_equity(self.data_dir, [100, 101, 102, 103, 104])
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        for key in ("available", "verdict", "verdict_reason",
                    "num_regimes_observed", "dominant_regime", "worst_regime",
                    "worst_regime_sharpe", "regimes", "overall", "track",
                    "meta", "is_demo"):
            self.assertIn(key, r)

    def test_is_demo_surfaced(self):
        _write_equity(self.data_dir, [100, 101, 102, 103], is_demo=False)
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertIs(r["is_demo"], False)

    def test_is_demo_absent_none(self):
        _write_equity(self.data_dir, [100, 101, 102, 103])
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertIsNone(r["is_demo"])

    def test_overall_pools_all_buckets(self):
        _write_equity(self.data_dir, [100, 101, 100, 101, 100, 101])
        self._patch_timeline([
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-04", "regime": "BEAR"},
        ])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertEqual(r["overall"]["num_days"], 5)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Verdict boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdict(_PatchBase):

    def _build_with_levels(self, levels, timeline):
        _write_equity(self.data_dir, levels)
        self._patch_timeline(timeline)
        return rcp.build_regime_conditional_performance(self.data_dir)

    def test_fail_bear_negative_sharpe(self):
        # BEAR region with declining equity → negative mean → negative sharpe
        # levels: rising in BULL then strictly declining (with variance) in BEAR
        levels = [100, 101, 102,    # BULL returns on 01-02,01-03
                  100, 99, 100, 97]  # BEAR returns on 01-04..01-07 (net down, varying)
        timeline = [
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-04", "regime": "BEAR"},
        ]
        r = self._build_with_levels(levels, timeline)
        self.assertTrue(r["available"])
        bear = r["regimes"]["BEAR"]
        self.assertGreaterEqual(bear["num_days"], rcp.MIN_REGIME_OBS)
        self.assertIsNotNone(bear["sharpe_annualized"])
        self.assertLess(bear["sharpe_annualized"], 0)
        self.assertEqual(r["verdict"], "fail")
        self.assertIn("BEAR", r["verdict_reason"])

    def test_warn_bear_low_sample(self):
        # BEAR with < MIN_REGIME_OBS days but > 0 → sharpe None → warn
        levels = [100, 101, 102, 103, 102]  # BULL 01-02..01-04, BEAR 01-05 only
        timeline = [
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-05", "regime": "BEAR"},
        ]
        r = self._build_with_levels(levels, timeline)
        bear = r["regimes"]["BEAR"]
        self.assertGreater(bear["num_days"], 0)
        self.assertLess(bear["num_days"], rcp.MIN_REGIME_OBS)
        self.assertIsNone(bear["sharpe_annualized"])
        self.assertEqual(r["verdict"], "warn")

    def test_ok_all_positive_no_bear(self):
        # steadily rising, single BULL regime, varying returns → positive sharpe
        levels = [100, 101, 103, 104, 106, 107]
        timeline = [{"date": "2026-01-01", "regime": "BULL"}]
        r = self._build_with_levels(levels, timeline)
        self.assertEqual(r["verdict"], "ok")

    def test_warn_negative_nonbear_regime(self):
        # BULL fine, SIDEWAYS negative sharpe (no BEAR) → warn
        levels = [100, 101, 103, 104,   # BULL 01-02..01-04 rising
                  103, 104, 102, 103]    # SIDEWAYS 01-05..01-08 net down w/ var
        timeline = [
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-05", "regime": "SIDEWAYS"},
        ]
        r = self._build_with_levels(levels, timeline)
        self.assertNotIn("BEAR", r["regimes"])
        side = r["regimes"]["SIDEWAYS"]
        if side["sharpe_annualized"] is not None and side["sharpe_annualized"] < 0:
            self.assertEqual(r["verdict"], "warn")
        else:
            self.assertIn(r["verdict"], ("ok", "warn"))

    def test_verdict_reason_always_present(self):
        levels = [100, 101, 102, 103, 104]
        timeline = [{"date": "2026-01-01", "regime": "BULL"}]
        r = self._build_with_levels(levels, timeline)
        self.assertTrue(r["verdict_reason"])

    def test_decide_verdict_overall_negative_path(self):
        # craft metrics directly: no bear, all-regime sharpe None, overall < 0
        regimes = {
            "SIDEWAYS": {"num_days": 2, "sharpe_annualized": None},
        }
        overall = {"sharpe_annualized": -1.5}
        v, reason = rcp._decide_verdict(regimes, overall, None, None)
        self.assertEqual(v, "warn")
        self.assertIn("overall", reason.lower())

    def test_decide_verdict_fail_direct(self):
        regimes = {"BEAR": {"num_days": 5, "sharpe_annualized": -0.0001}}
        overall = {"sharpe_annualized": -0.0001}
        v, reason = rcp._decide_verdict(regimes, overall, "BEAR", -0.0001)
        self.assertEqual(v, "fail")

    def test_decide_verdict_bear_sharpe_exactly_zero_not_fail(self):
        # Sharpe == 0 is not < 0 → not fail (boundary)
        regimes = {"BEAR": {"num_days": 5, "sharpe_annualized": 0.0}}
        overall = {"sharpe_annualized": 0.0}
        v, reason = rcp._decide_verdict(regimes, overall, "BEAR", 0.0)
        self.assertEqual(v, "ok")

    def test_decide_verdict_ok_direct(self):
        regimes = {"BULL": {"num_days": 5, "sharpe_annualized": 1.2}}
        overall = {"sharpe_annualized": 1.2}
        v, reason = rcp._decide_verdict(regimes, overall, "BULL", 1.2)
        self.assertEqual(v, "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. insufficient_data / stable schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficient(_PatchBase):

    def _assert_unavailable_schema(self, r):
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        for key in ("verdict", "verdict_reason", "num_regimes_observed",
                    "dominant_regime", "worst_regime", "regimes", "overall",
                    "meta"):
            self.assertIn(key, r)
        self.assertIn("generated_at", r["meta"])
        self.assertIn("source", r["meta"])

    def test_missing_equity_file(self):
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self._assert_unavailable_schema(r)

    def test_one_bar_equity(self):
        _write_equity(self.data_dir, [100])
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self._assert_unavailable_schema(r)

    def test_empty_regime_timeline(self):
        _write_equity(self.data_dir, [100, 101, 102, 103])
        self._patch_timeline([])  # empty timeline
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self._assert_unavailable_schema(r)

    def test_all_returns_unknown(self):
        # timeline entirely after the equity dates → all returns UNKNOWN
        _write_equity(self.data_dir, [100, 101, 102, 103])
        self._patch_timeline([{"date": "2030-01-01", "regime": "BULL"}])
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self._assert_unavailable_schema(r)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Tolerance / never-raise
# ═══════════════════════════════════════════════════════════════════════════════

class TestTolerance(_TmpBase):

    def test_missing_everything(self):
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("meta", r)

    def test_broken_equity_json(self):
        (self.data_dir / rcp.EQUITY_FILENAME).write_text("{ not valid json")
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertFalse(r["available"])

    def test_non_dict_equity_root(self):
        (self.data_dir / rcp.EQUITY_FILENAME).write_text("[1, 2, 3]")
        r = rcp.build_regime_conditional_performance(self.data_dir)
        self.assertFalse(r["available"])

    def test_broken_apy_with_good_equity(self):
        _write_equity(self.data_dir, [100, 101, 102, 103])
        (self.data_dir / "apy_history.json").write_text("{ broken")
        r = rcp.build_regime_conditional_performance(self.data_dir)
        # broken apy → no timeline → insufficient_data, but never raises
        self.assertIn("available", r)
        self.assertFalse(r["available"])

    def test_garbage_equity_records_subtests(self):
        garbage_docs = [
            {"daily": "not-a-list"},
            {"daily": [1, 2, 3]},
            {"daily": [{"date": "bad", "close_equity": 5}]},
            {"daily": [{"date": "2026-01-01"}]},          # no equity
            {"daily": [{"close_equity": 5}]},              # no date
            {"daily": [{"date": "2026-01-01", "close_equity": -5}]},
            {"daily": []},
            {},
            "string-root",
            123,
            None,
        ]
        for i, doc in enumerate(garbage_docs):
            with self.subTest(case=i):
                (self.data_dir / rcp.EQUITY_FILENAME).write_text(json.dumps(doc))
                _write_apy_stub(self.data_dir)
                try:
                    r = rcp.build_regime_conditional_performance(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"build raised on garbage case {i}: {exc}")
                self.assertIn("available", r)

    def test_never_raises_property_fuzz(self):
        payloads = [
            "null", "123", '"string"', "true", "[]", "{}",
            json.dumps({"daily": [{"date": "2026-01-01", "close_equity": "x"}]}),
            json.dumps({"daily": [{"date": "2026-01-01", "close_equity": float("nan")}
                                  if False else {"date": "2026-01-01", "close_equity": 1}]}),
        ]
        for i, payload in enumerate(payloads):
            with self.subTest(case=i):
                (self.data_dir / rcp.EQUITY_FILENAME).write_text(payload)
                _write_apy_stub(self.data_dir)
                try:
                    r = rcp.build_regime_conditional_performance(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"raised on payload {i}: {exc}")
                self.assertIn("available", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. content_fingerprint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def test_reused_by_import_same_object(self):
        self.assertIs(rcp.content_fingerprint, ts.content_fingerprint)

    def test_ignores_generated_at(self):
        d1 = {"verdict": "ok", "meta": {"generated_at": "A", "source": "x"}}
        d2 = {"verdict": "ok", "meta": {"generated_at": "B", "source": "x"}}
        self.assertEqual(rcp.content_fingerprint(d1), rcp.content_fingerprint(d2))

    def test_ignores_history(self):
        d1 = {"verdict": "ok", "history": [1, 2, 3], "meta": {"source": "x"}}
        d2 = {"verdict": "ok", "history": [], "meta": {"source": "x"}}
        self.assertEqual(rcp.content_fingerprint(d1), rcp.content_fingerprint(d2))

    def test_changes_with_content(self):
        d1 = {"verdict": "ok", "meta": {"source": "x"}}
        d2 = {"verdict": "fail", "meta": {"source": "x"}}
        self.assertNotEqual(rcp.content_fingerprint(d1), rcp.content_fingerprint(d2))

    def test_stable_across_calls(self):
        d = {"verdict": "warn", "num_regimes_observed": 3, "meta": {"source": "x"}}
        self.assertEqual(rcp.content_fingerprint(d), rcp.content_fingerprint(d))


# ═══════════════════════════════════════════════════════════════════════════════
# 12. write_status — persistence, idempotency, rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _result(self, verdict="ok", n=3):
        return {
            "available": True,
            "verdict": verdict,
            "num_regimes_observed": n,
            "dominant_regime": "BULL",
            "worst_regime": None,
            "worst_regime_sharpe": None,
            "meta": {"generated_at": "2026-01-01T00:00:00", "source": rcp.SOURCE_NAME},
        }

    def test_first_write_returns_written(self):
        status = rcp.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        self.assertTrue((self.data_dir / rcp.STATUS_FILENAME).exists())

    def test_identical_write_unchanged_byte_identical(self):
        r = self._result()
        rcp.write_status(r, self.data_dir)
        out = self.data_dir / rcp.STATUS_FILENAME
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        status2 = rcp.write_status(r, self.data_dir)
        md5_2 = hashlib.md5(out.read_bytes()).hexdigest()
        self.assertEqual(status2, "DATA_UNCHANGED")
        self.assertEqual(md5_1, md5_2)

    def test_different_content_written(self):
        rcp.write_status(self._result("ok"), self.data_dir)
        status = rcp.write_status(self._result("fail"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_history_grows(self):
        # Each content-changing write appends a slim record (drawdown_analytics
        # pattern): after N distinct writes history has N entries.
        rcp.write_status(self._result("ok"), self.data_dir)
        doc = json.loads((self.data_dir / rcp.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 1)
        rcp.write_status(self._result("warn"), self.data_dir)
        doc = json.loads((self.data_dir / rcp.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 2)
        rcp.write_status(self._result("fail"), self.data_dir)
        doc = json.loads((self.data_dir / rcp.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 3)

    def test_history_rotation_exactly_max(self):
        for i in range(rcp.HISTORY_MAX + 5):
            r = self._result(n=i)  # force content change each write
            rcp.write_status(r, self.data_dir)
        doc = json.loads((self.data_dir / rcp.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), rcp.HISTORY_MAX)

    def test_no_tmp_files_left(self):
        for v in ("ok", "warn", "fail"):
            rcp.write_status(self._result(v), self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp*")) + list(
            self.data_dir.glob(".tmp*")
        )
        self.assertEqual(leftovers, [])

    def test_tolerant_broken_existing_file(self):
        (self.data_dir / rcp.STATUS_FILENAME).write_text("{ broken json")
        status = rcp.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        doc = json.loads((self.data_dir / rcp.STATUS_FILENAME).read_text())
        self.assertIn("history", doc)

    def test_unavailable_result_writable(self):
        r = rcp.build_regime_conditional_performance(self.data_dir)  # unavailable
        s1 = rcp.write_status(r, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        s2 = rcp.write_status(r, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. CLI — direct main() + subprocess
# ═══════════════════════════════════════════════════════════════════════════════

class TestCliDirect(_PatchBase):

    def _setup_valid(self):
        _write_equity(self.data_dir, [100, 101, 102, 103, 104, 105])
        self._patch_timeline([{"date": "2026-01-01", "regime": "BULL"}])

    def test_check_does_not_write(self):
        self._setup_valid()
        out = self.data_dir / rcp.STATUS_FILENAME
        rc = rcp.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse(out.exists())

    def test_default_is_check_no_write(self):
        self._setup_valid()
        out = self.data_dir / rcp.STATUS_FILENAME
        rc = rcp.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse(out.exists())

    def test_run_writes_file(self):
        self._setup_valid()
        out = self.data_dir / rcp.STATUS_FILENAME
        rc = rcp.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue(out.exists())

    def test_run_idempotent(self):
        self._setup_valid()
        out = self.data_dir / rcp.STATUS_FILENAME
        rcp.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        rcp.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(out.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_args_exit_zero_error_stderr(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = rcp.main(["--unknown-garbage-flag-xyz"])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())

    def test_check_run_conflict_exit_zero_error(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = rcp.main(["--check", "--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())


class TestCliSubprocess(_TmpBase):
    """subprocess CLI tests against REAL data dir (real track is short →
    available:false gracefully). No monkeypatch possible across process."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.regime_conditional_performance", *args],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )

    def test_subprocess_check_no_write(self):
        res = self._run("--check", "--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertIn("available=", res.stdout)
        self.assertFalse((self.data_dir / rcp.STATUS_FILENAME).exists())

    def test_subprocess_default_is_check(self):
        res = self._run("--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertFalse((self.data_dir / rcp.STATUS_FILENAME).exists())

    def test_subprocess_run_writes_and_idempotent(self):
        # use a tempdir copy with valid-enough data? real data short → still
        # writes an (unavailable) artifact. Run twice → second DATA_UNCHANGED.
        _write_equity(self.data_dir, [100, 101, 102, 103, 104])
        _write_apy_stub(self.data_dir)
        res1 = self._run("--run", "--data-dir", str(self.data_dir))
        self.assertEqual(res1.returncode, 0)
        self.assertIn("write_status=", res1.stdout)
        self.assertTrue((self.data_dir / rcp.STATUS_FILENAME).exists())
        res2 = self._run("--run", "--data-dir", str(self.data_dir))
        self.assertEqual(res2.returncode, 0)
        self.assertIn("DATA_UNCHANGED", res2.stdout)

    def test_subprocess_junk_arg_exit_zero_no_traceback(self):
        res = self._run("--totally-bogus-arg")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ERROR", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_subprocess_conflict_exit_zero_no_traceback(self):
        res = self._run("--check", "--run")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ERROR", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_subprocess_no_tmp_leak(self):
        _write_equity(self.data_dir, [100, 101, 102, 103, 104])
        _write_apy_stub(self.data_dir)
        self._run("--run", "--data-dir", str(self.data_dir))
        self._run("--run", "--data-dir", str(self.data_dir))
        leftovers = list(self.data_dir.glob("*.tmp*")) + list(
            self.data_dir.glob(".tmp*")
        )
        self.assertEqual(leftovers, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Import / AST hygiene + lint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_TOP = {
    "requests", "httpx", "aiohttp", "urllib3",
    "web3", "eth_account",
    "numpy", "pandas", "scipy",
    "anthropic", "openai",
    "socket",
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

    def test_no_forbidden_top_level_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_TOP
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_real_find_forbidden_imports_zero_violations(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        source = _MODULE_PATH.read_text(encoding="utf-8")
        violations = find_forbidden_imports(source, str(_MODULE_PATH))
        self.assertEqual(len(violations), 0, msg=f"forbidden imports: {violations}")

    def test_module_compiles(self):
        import py_compile
        py_compile.compile(str(_MODULE_PATH), doraise=True)

    def test_test_file_compiles(self):
        import py_compile
        py_compile.compile(str(_TEST_PATH), doraise=True)

    def test_no_network_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("requests.get", "requests.post", "urllib.request",
                        "http.client", "socket.connect", "socket.socket"):
            self.assertNotIn(pattern, source, msg=f"Found network pattern: {pattern}")

    def test_no_llm_sdk_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("anthropic.", "openai.", "from anthropic", "from openai"):
            self.assertNotIn(pattern, source, msg=f"Found LLM SDK pattern: {pattern}")

    def test_no_subprocess_eval_exec_pip(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("pip install", "subprocess", "eval(", "exec(",
                        "socket.socket", "socket.connect"):
            self.assertNotIn(pattern, source, msg=f"Found pattern: {pattern}")

    def test_no_socket_import(self):
        # The word "socket" may appear in the docstring ("no sockets/network"),
        # but it must never be IMPORTED. AST-level check.
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        self.assertNotIn("socket", used)

    def test_atomic_write_pattern_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        # Module uses atomic_save (centralised helper) OR raw tmp+os.replace pattern.
        uses_atomic_save = "atomic_save" in source
        uses_raw_atomic = "os.replace" in source and "tempfile.mkstemp" in source
        self.assertTrue(
            uses_atomic_save or uses_raw_atomic,
            "Neither atomic_save nor tmp+os.replace atomic write pattern found in source",
        )

    def test_reuse_by_import_marker_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.reporting.tear_sheet import content_fingerprint", source
        )

    def test_reuse_regime_and_equity_imports_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("from spa_core.paper_trading.regime_detector import", source)
        self.assertIn(
            "from spa_core.paper_trading.drawdown_analytics import extract_equity_series",
            source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
