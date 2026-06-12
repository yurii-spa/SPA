#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.turnover_analytics (SPA-V441 / MP-121).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir.

Covers:
- one_way_turnover() / turnover_series() math: hand-computed values
  (50/50 → 60/40 = 0.10; full rotation = 1.0; no change = 0.0), clamping
- extract_weight_series: normalisation, cash-not-in-positions, skipping bars
  without a usable positions dict, garbage / non-dict / negative / NaN values
- per_protocol_churn + most_churned_protocol + most_churned_share
- headline: avg / median / max (+ date) / cumulative / annualized turnover,
  implied_avg_holding_days (turnover 0 → None / buy-and-hold), num_rebalance_days
  threshold at REBALANCE_EPS=0.005
- verdict boundaries: annualized exactly 4.0 and 12.0, above / below
- insufficient_data: < 2 usable bars → available:false + reason, never raises
- tolerance of missing / broken-JSON / non-dict / empty / garbage positions
  (subTest each), never raises
- is_demo true / false / absent
- content_fingerprint REUSED from tear_sheet: ignores generated_at / history,
  changes with content, stable
- write_status / idempotency: byte-identical (md5) on repeat, history rotation
  exactly HISTORY_MAX, no stray *.tmp files, tolerant of broken existing file
- CLI: --check no write, --run writes, junk → ERROR on stderr + exit 0,
  --run idempotent, --check/--run conflict, direct + subprocess
- import hygiene: real find_forbidden_imports from llm_forbidden_lint + AST scan
  for forbidden libs + py_compile + no network patterns + content_fingerprint
  reuse-by-import marker
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import turnover_analytics as ta
from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
from spa_core.reporting import tear_sheet as _tear_sheet

_MODULE_PATH = Path(ta.__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _bar(d: str, positions: Optional[Dict[str, float]], **extra: Any) -> Dict[str, Any]:
    bar: Dict[str, Any] = {"date": d, "close_equity": 100000.0, "equity": 100000.0}
    if positions is not None:
        bar["positions"] = positions
    bar.update(extra)
    return bar


def _equity_doc(bars: List[Dict[str, Any]], **top: Any) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"daily": bars}
    doc.update(top)
    return doc


def _write_equity(data_dir: Path, doc: Any) -> None:
    p = data_dir / ta.EQUITY_FILENAME
    p.write_text(json.dumps(doc), encoding="utf-8")


def _make_doc_from_weights(
    weight_dicts: List[Dict[str, float]], scale: float = 100000.0
) -> Dict[str, Any]:
    """Build an equity doc whose bars have positions matching given weights."""
    dts = _dates(len(weight_dicts))
    bars = []
    for d, w in zip(dts, weight_dicts):
        positions = {p: v * scale for p, v in w.items()}
        bars.append(_bar(d, positions))
    return _equity_doc(bars)


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="turnover_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. one_way_turnover / turnover_series math
# ═══════════════════════════════════════════════════════════════════════════════

class TestTurnoverMath(unittest.TestCase):

    def test_5050_to_6040_is_010(self):
        prev = {"a": 0.5, "b": 0.5}
        cur = {"a": 0.6, "b": 0.4}
        self.assertAlmostEqual(ta.one_way_turnover(prev, cur), 0.10, places=10)

    def test_no_change_is_zero(self):
        prev = {"a": 0.5, "b": 0.5}
        self.assertAlmostEqual(ta.one_way_turnover(prev, dict(prev)), 0.0, places=12)

    def test_full_rotation_is_one(self):
        prev = {"a": 1.0}
        cur = {"b": 1.0}
        self.assertAlmostEqual(ta.one_way_turnover(prev, cur), 1.0, places=12)

    def test_partial_rotation_into_new_protocol(self):
        # a: 1.0 → 0.5, b new at 0.5 → gross = 0.5+0.5 = 1.0 → turnover 0.5
        prev = {"a": 1.0}
        cur = {"a": 0.5, "b": 0.5}
        self.assertAlmostEqual(ta.one_way_turnover(prev, cur), 0.5, places=12)

    def test_protocol_dropped(self):
        # a: 0.5→0.5, b: 0.5→0.0, c new 0.0→0.5 → gross=1.0 → turnover 0.5
        prev = {"a": 0.5, "b": 0.5}
        cur = {"a": 0.5, "c": 0.5}
        self.assertAlmostEqual(ta.one_way_turnover(prev, cur), 0.5, places=12)

    def test_result_in_unit_range(self):
        prev = {"a": 0.3, "b": 0.3, "c": 0.4}
        cur = {"a": 0.4, "b": 0.1, "c": 0.5}
        t = ta.one_way_turnover(prev, cur)
        self.assertGreaterEqual(t, 0.0)
        self.assertLessEqual(t, 1.0)

    def test_empty_both_is_zero(self):
        self.assertEqual(ta.one_way_turnover({}, {}), 0.0)

    def test_three_way_hand_computed(self):
        # 1/3,1/3,1/3 → 0.5,0.25,0.25
        prev = {"a": 1/3, "b": 1/3, "c": 1/3}
        cur = {"a": 0.5, "b": 0.25, "c": 0.25}
        gross = abs(0.5 - 1/3) + abs(0.25 - 1/3) + abs(0.25 - 1/3)
        self.assertAlmostEqual(ta.one_way_turnover(prev, cur), 0.5 * gross, places=12)

    def test_turnover_series_length(self):
        weights = [("d1", {"a": 1.0}), ("d2", {"a": 1.0}), ("d3", {"b": 1.0})]
        series = ta.turnover_series(weights)
        self.assertEqual(len(series), 2)

    def test_turnover_series_dates_are_current_bar(self):
        weights = [("d1", {"a": 1.0}), ("d2", {"b": 1.0})]
        series = ta.turnover_series(weights)
        self.assertEqual(series[0][0], "d2")

    def test_turnover_series_values(self):
        weights = [
            ("d1", {"a": 0.5, "b": 0.5}),
            ("d2", {"a": 0.6, "b": 0.4}),
            ("d3", {"a": 0.6, "b": 0.4}),
        ]
        series = ta.turnover_series(weights)
        self.assertAlmostEqual(series[0][1], 0.10, places=10)
        self.assertAlmostEqual(series[1][1], 0.0, places=12)

    def test_single_weight_no_series(self):
        self.assertEqual(ta.turnover_series([("d1", {"a": 1.0})]), [])

    def test_empty_weights_no_series(self):
        self.assertEqual(ta.turnover_series([]), [])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. extract_weight_series
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractWeights(unittest.TestCase):

    def test_normalisation(self):
        doc = _equity_doc([_bar("2026-01-01", {"a": 30.0, "b": 10.0})])
        w = ta.extract_weight_series(doc)
        self.assertEqual(len(w), 1)
        self.assertAlmostEqual(w[0][1]["a"], 0.75, places=12)
        self.assertAlmostEqual(w[0][1]["b"], 0.25, places=12)

    def test_weights_sum_to_one(self):
        doc = _equity_doc([_bar("2026-01-01", {"a": 1.0, "b": 2.0, "c": 3.0})])
        w = ta.extract_weight_series(doc)
        self.assertAlmostEqual(sum(w[0][1].values()), 1.0, places=12)

    def test_cash_not_in_positions_ok(self):
        # positions need not equal equity (cash excluded) — weights normalise
        doc = _equity_doc([_bar("2026-01-01", {"a": 100.0}, equity=1000.0)])
        w = ta.extract_weight_series(doc)
        self.assertAlmostEqual(w[0][1]["a"], 1.0, places=12)

    def test_bare_list_accepted(self):
        bars = [_bar("2026-01-01", {"a": 1.0}), _bar("2026-01-02", {"a": 1.0})]
        w = ta.extract_weight_series(bars)
        self.assertEqual(len(w), 2)

    def test_skip_bar_without_positions(self):
        doc = _equity_doc([
            _bar("2026-01-01", {"a": 1.0}),
            _bar("2026-01-02", None),
            _bar("2026-01-03", {"a": 1.0}),
        ])
        w = ta.extract_weight_series(doc)
        self.assertEqual(len(w), 2)

    def test_skip_empty_positions(self):
        doc = _equity_doc([_bar("2026-01-01", {})])
        self.assertEqual(ta.extract_weight_series(doc), [])

    def test_skip_negative_and_zero(self):
        doc = _equity_doc([_bar("2026-01-01", {"a": 10.0, "b": -5.0, "c": 0.0})])
        w = ta.extract_weight_series(doc)
        self.assertEqual(set(w[0][1].keys()), {"a"})

    def test_skip_nan_inf(self):
        doc = _equity_doc([_bar("2026-01-01", {"a": 10.0, "b": float("nan"),
                                               "c": float("inf")})])
        w = ta.extract_weight_series(doc)
        self.assertEqual(set(w[0][1].keys()), {"a"})

    def test_all_invalid_positions_skipped(self):
        doc = _equity_doc([_bar("2026-01-01", {"a": -1.0, "b": 0.0})])
        self.assertEqual(ta.extract_weight_series(doc), [])

    def test_sorted_by_date(self):
        doc = _equity_doc([
            _bar("2026-01-03", {"a": 1.0}),
            _bar("2026-01-01", {"a": 1.0}),
            _bar("2026-01-02", {"a": 1.0}),
        ])
        w = ta.extract_weight_series(doc)
        self.assertEqual([d for d, _ in w], ["2026-01-01", "2026-01-02", "2026-01-03"])

    def test_invalid_date_skipped(self):
        doc = _equity_doc([_bar("not-a-date", {"a": 1.0}),
                           _bar("2026-01-01", {"a": 1.0})])
        w = ta.extract_weight_series(doc)
        self.assertEqual(len(w), 1)

    def test_non_dict_bar_skipped(self):
        doc = {"daily": ["junk", 42, _bar("2026-01-01", {"a": 1.0})]}
        w = ta.extract_weight_series(doc)
        self.assertEqual(len(w), 1)

    def test_non_list_daily(self):
        self.assertEqual(ta.extract_weight_series({"daily": "x"}), [])

    def test_non_dict_doc(self):
        self.assertEqual(ta.extract_weight_series(None), [])
        self.assertEqual(ta.extract_weight_series(42), [])
        self.assertEqual(ta.extract_weight_series("x"), [])

    def test_positions_not_a_dict(self):
        doc = _equity_doc([_bar("2026-01-01", None)])
        doc["daily"][0]["positions"] = [1, 2, 3]
        self.assertEqual(ta.extract_weight_series(doc), [])


# ═══════════════════════════════════════════════════════════════════════════════
# 3. per_protocol_churn / most_churned
# ═══════════════════════════════════════════════════════════════════════════════

class TestChurn(unittest.TestCase):

    def test_per_protocol_churn_basic(self):
        weights = [
            ("d1", {"a": 0.5, "b": 0.5}),
            ("d2", {"a": 0.6, "b": 0.4}),
        ]
        churn = ta.per_protocol_churn(weights)
        self.assertAlmostEqual(churn["a"], 0.1, places=12)
        self.assertAlmostEqual(churn["b"], 0.1, places=12)

    def test_churn_union_equals_twice_turnover(self):
        weights = [
            ("d1", {"a": 0.5, "b": 0.5}),
            ("d2", {"a": 0.6, "b": 0.4}),
            ("d3", {"a": 0.2, "b": 0.8}),
        ]
        churn = ta.per_protocol_churn(weights)
        series = ta.turnover_series(weights)
        self.assertAlmostEqual(sum(churn.values()), 2 * sum(t for _, t in series), places=12)

    def test_churn_empty(self):
        self.assertEqual(ta.per_protocol_churn([]), {})
        self.assertEqual(ta.per_protocol_churn([("d1", {"a": 1.0})]), {})

    def test_most_churned_in_headline(self):
        # a moves most
        # 'a' moves; build via the real path and confirm it is the top churner.
        d = self._build([{"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.1}])
        self.assertIn(d["headline"]["most_churned_protocol"], ("a", "b"))

    def _build(self, weight_dicts):
        tmp = tempfile.mkdtemp(prefix="ch_")
        try:
            _write_equity(Path(tmp), _make_doc_from_weights(weight_dicts))
            return ta.build_turnover_analytics(data_dir=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_most_churned_share_fraction(self):
        d = self._build([{"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.1}])
        share = d["headline"]["most_churned_share"]
        self.assertGreater(share, 0.0)
        self.assertLessEqual(share, 1.0)
        # a and b move equally → share ~0.5
        self.assertAlmostEqual(share, 0.5, places=6)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Headline metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeadline(_TmpBase):

    def _build(self, weight_dicts, **top):
        doc = _make_doc_from_weights(weight_dicts)
        doc.update(top)
        _write_equity(self.data_dir, doc)
        return ta.build_turnover_analytics(data_dir=self.data_dir)

    def test_avg_median_max_cumulative(self):
        # turnovers: 0.10, 0.0, 0.20
        weights = [
            {"a": 0.5, "b": 0.5},
            {"a": 0.6, "b": 0.4},
            {"a": 0.6, "b": 0.4},
            {"a": 0.8, "b": 0.2},
        ]
        d = self._build(weights)
        h = d["headline"]
        self.assertEqual(h["num_observations"], 3)
        self.assertAlmostEqual(h["cumulative_turnover"], 0.30, places=6)
        self.assertAlmostEqual(h["avg_daily_turnover"], 0.10, places=6)
        self.assertAlmostEqual(h["median_daily_turnover"], 0.10, places=6)
        self.assertAlmostEqual(h["max_daily_turnover"], 0.20, places=6)

    def test_max_turnover_date(self):
        weights = [
            {"a": 0.5, "b": 0.5},
            {"a": 0.6, "b": 0.4},   # 2026-01-02, t=0.10
            {"a": 0.9, "b": 0.1},   # 2026-01-03, t=0.30
        ]
        d = self._build(weights)
        self.assertEqual(d["headline"]["max_turnover_date"], "2026-01-03")

    def test_annualized_is_avg_times_365(self):
        weights = [{"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}]
        d = self._build(weights)
        h = d["headline"]
        self.assertAlmostEqual(
            h["annualized_turnover"], h["avg_daily_turnover"] * 365, places=4
        )

    def test_implied_holding_days(self):
        # avg = 0.10 → implied = 10 days
        weights = [{"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}]
        d = self._build(weights)
        self.assertAlmostEqual(d["headline"]["implied_avg_holding_days"], 10.0, places=4)

    def test_implied_holding_none_when_zero_turnover(self):
        # identical books → avg turnover 0 → implied holding None (buy-and-hold)
        weights = [{"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}]
        d = self._build(weights)
        self.assertEqual(d["headline"]["avg_daily_turnover"], 0.0)
        self.assertIsNone(d["headline"]["implied_avg_holding_days"])

    def test_median_even_count(self):
        # turnovers: 0.10, 0.20 → median 0.15
        weights = [
            {"a": 0.5, "b": 0.5},
            {"a": 0.6, "b": 0.4},
            {"a": 0.8, "b": 0.2},
        ]
        d = self._build(weights)
        self.assertAlmostEqual(d["headline"]["median_daily_turnover"], 0.15, places=6)

    def test_num_rebalance_days_threshold(self):
        # turnovers: 0.10 (>eps), 0.001 (<eps), 0.006 (>eps)
        weights = [
            {"a": 0.5, "b": 0.5},
            {"a": 0.6, "b": 0.4},     # 0.10
            {"a": 0.601, "b": 0.399}, # 0.001
            {"a": 0.607, "b": 0.393}, # 0.006
        ]
        d = self._build(weights)
        self.assertEqual(d["headline"]["num_rebalance_days"], 2)

    def test_rebalance_eps_value(self):
        self.assertEqual(ta.REBALANCE_EPS, 0.005)

    def test_zero_turnover_no_rebalance_days(self):
        weights = [{"a": 1.0}, {"a": 1.0}, {"a": 1.0}]
        d = self._build(weights)
        self.assertEqual(d["headline"]["num_rebalance_days"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Verdict boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdict(_TmpBase):

    def _build_with_avg(self, avg_turnover: float):
        """Construct two bars whose single turnover equals avg_turnover."""
        # turnover for {a:0.5,b:0.5} → {a:0.5+x, b:0.5-x} is x (one-way).
        x = avg_turnover
        weights = [{"a": 0.5, "b": 0.5}, {"a": 0.5 + x, "b": 0.5 - x}]
        _write_equity(self.data_dir, _make_doc_from_weights(weights))
        return ta.build_turnover_analytics(data_dir=self.data_dir)

    def test_below_moderate_is_ok(self):
        # annualized = 2.0 → avg = 2/365
        d = self._build_with_avg(2.0 / 365)
        self.assertEqual(d["verdict"], "ok")

    def test_exactly_moderate_is_ok(self):
        # annualized exactly 4.0 → NOT > MODERATE → ok
        d = self._build_with_avg(4.0 / 365)
        self.assertAlmostEqual(d["headline"]["annualized_turnover"], 4.0, places=4)
        self.assertEqual(d["verdict"], "ok")

    def test_just_above_moderate_is_warn(self):
        d = self._build_with_avg(5.0 / 365)
        self.assertEqual(d["verdict"], "warn")

    def test_exactly_high_is_warn(self):
        # annualized exactly 12.0 → NOT > HIGH → warn
        d = self._build_with_avg(12.0 / 365)
        self.assertAlmostEqual(d["headline"]["annualized_turnover"], 12.0, places=4)
        self.assertEqual(d["verdict"], "warn")

    def test_just_above_high_is_fail(self):
        d = self._build_with_avg(13.0 / 365)
        self.assertEqual(d["verdict"], "fail")

    def test_full_rotation_is_fail(self):
        # turnover 1.0 → annualized 365 → fail
        weights = [{"a": 1.0}, {"b": 1.0}]
        _write_equity(self.data_dir, _make_doc_from_weights(weights))
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertEqual(d["verdict"], "fail")

    def test_verdict_reason_present(self):
        d = self._build_with_avg(2.0 / 365)
        self.assertIsInstance(d["verdict_reason"], str)
        self.assertGreater(len(d["verdict_reason"]), 0)

    def test_thresholds_values(self):
        self.assertEqual(ta.MODERATE_TURNOVER, 4.0)
        self.assertEqual(ta.HIGH_TURNOVER, 12.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. insufficient_data / tolerance
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnavailable(_TmpBase):

    def test_missing_file(self):
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertFalse(d["available"])
        self.assertEqual(d["reason"], "insufficient_data")

    def test_single_bar_with_positions(self):
        _write_equity(self.data_dir, _equity_doc([_bar("2026-01-01", {"a": 1.0})]))
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertFalse(d["available"])
        self.assertEqual(d["reason"], "insufficient_data")

    def test_no_bars_with_positions(self):
        _write_equity(self.data_dir, _equity_doc([
            _bar("2026-01-01", None), _bar("2026-01-02", None),
        ]))
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertFalse(d["available"])

    def test_unavailable_schema_stable(self):
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        for key in ("meta", "available", "reason", "track", "headline",
                    "verdict", "verdict_reason", "per_protocol_churn",
                    "recent_turnover"):
            self.assertIn(key, d)
        self.assertIn("num_observations", d["headline"])

    def test_never_raises_on_garbage(self):
        garbage = [
            "NOT JSON !!", "null", "42", '""', "[1,2,3]",
            '{"daily": 99}', '{"daily": [1,2,3]}',
            '{"daily": [{"date": "x", "positions": {}}]}',
            '{"daily": [{"positions": {"a": 1}}]}',
            '{"daily": [{"date": "2026-01-01", "positions": "notdict"}]}',
            '{"daily": [{"date": "2026-01-01", "positions": {"a": "x"}}]}',
            '{"daily": []}',
            '{}',
        ]
        for text in garbage:
            with self.subTest(text=text):
                (self.data_dir / ta.EQUITY_FILENAME).write_text(text)
                d = ta.build_turnover_analytics(data_dir=self.data_dir)  # must not raise
                self.assertIn("available", d)
                self.assertFalse(d["available"])

    def test_broken_json_tolerated(self):
        (self.data_dir / ta.EQUITY_FILENAME).write_text("{not valid")
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertFalse(d["available"])

    def test_min_obs_value(self):
        self.assertEqual(ta.MIN_OBS, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. is_demo
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsDemo(_TmpBase):

    def _build(self, **top):
        doc = _make_doc_from_weights([{"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}])
        doc.update(top)
        _write_equity(self.data_dir, doc)
        return ta.build_turnover_analytics(data_dir=self.data_dir)

    def test_is_demo_true(self):
        self.assertIs(self._build(is_demo=True)["meta"]["is_demo"], True)

    def test_is_demo_false(self):
        self.assertIs(self._build(is_demo=False)["meta"]["is_demo"], False)

    def test_is_demo_absent(self):
        self.assertIsNone(self._build()["meta"]["is_demo"])

    def test_is_demo_non_bool_ignored(self):
        self.assertIsNone(self._build(is_demo="yes")["meta"]["is_demo"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. content_fingerprint (reused from tear_sheet)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def _doc(self, tag: str = "x") -> Dict[str, Any]:
        return {
            "available": True,
            "verdict": "ok",
            "tag": tag,
            "meta": {"generated_at": "2026-01-01T00:00:00+00:00", "source": "t"},
        }

    def test_reuses_tear_sheet_fingerprint(self):
        # the module-level symbol IS tear_sheet.content_fingerprint
        self.assertIs(ta.content_fingerprint, _tear_sheet.content_fingerprint)

    def test_ignores_generated_at(self):
        a = self._doc()
        b = dict(a)
        b["meta"] = dict(a["meta"]); b["meta"]["generated_at"] = "2099-12-31T00:00:00+00:00"
        self.assertEqual(ta.content_fingerprint(a), ta.content_fingerprint(b))

    def test_ignores_history(self):
        a = self._doc()
        b = dict(a); b["history"] = [{"old": 1}]
        self.assertEqual(ta.content_fingerprint(a), ta.content_fingerprint(b))

    def test_changes_with_content(self):
        self.assertNotEqual(
            ta.content_fingerprint(self._doc("a")),
            ta.content_fingerprint(self._doc("b")),
        )

    def test_stable(self):
        d = self._doc()
        self.assertEqual(ta.content_fingerprint(d), ta.content_fingerprint(d))

    def test_non_dict_input(self):
        self.assertIsInstance(ta.content_fingerprint(None), str)
        self.assertEqual(ta.content_fingerprint(42), ta.content_fingerprint("x"))


# ═══════════════════════════════════════════════════════════════════════════════
# 9. write_status — persistence, idempotency, history rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _doc(self, tag: str = "v1", gen: str = "2026-01-01T00:00:00+00:00"):
        return {
            "meta": {"source": ta.SOURCE_NAME, "generated_at": gen,
                     "is_demo": False},
            "available": True,
            "verdict": "ok",
            "headline": {"avg_daily_turnover": 0.1, "annualized_turnover": 1.0,
                         "num_rebalance_days": 1, "tag": tag},
        }

    def test_first_write_changed_true(self):
        out = ta.write_status(self._doc("v1"), self.data_dir)
        self.assertTrue(out["changed"])
        self.assertTrue((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_second_identical_unchanged(self):
        d = self._doc("v1")
        ta.write_status(d, self.data_dir)
        out2 = ta.write_status(d, self.data_dir)
        self.assertFalse(out2["changed"])

    def test_byte_identical_on_repeat(self):
        d = self._doc("v1")
        ta.write_status(d, self.data_dir)
        p = self.data_dir / ta.STATUS_FILENAME
        md5_1 = hashlib.md5(p.read_bytes()).hexdigest()
        ta.write_status(d, self.data_dir)
        md5_2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_idempotent_ignores_generated_at_drift(self):
        ta.write_status(self._doc("v1", gen="2026-01-01T00:00:00+00:00"), self.data_dir)
        out2 = ta.write_status(self._doc("v1", gen="2099-12-31T00:00:00+00:00"), self.data_dir)
        self.assertFalse(out2["changed"])

    def test_different_content_rewrites(self):
        ta.write_status(self._doc("v1"), self.data_dir)
        out2 = ta.write_status(self._doc("v2"), self.data_dir)
        self.assertTrue(out2["changed"])

    def test_history_grows(self):
        ta.write_status(self._doc("v1"), self.data_dir)
        ta.write_status(self._doc("v2"), self.data_dir)
        doc = json.loads((self.data_dir / ta.STATUS_FILENAME).read_text())
        self.assertIn("history", doc)
        self.assertEqual(len(doc["history"]), 2)

    def test_history_rotation_exactly_max(self):
        for i in range(ta.HISTORY_MAX + 10):
            ta.write_status(self._doc(f"v{i}"), self.data_dir)
        doc = json.loads((self.data_dir / ta.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), ta.HISTORY_MAX)

    def test_no_stray_tmp_files(self):
        for i in range(5):
            ta.write_status(self._doc(f"v{i}"), self.data_dir)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.data_dir.glob(".*tmp*")), [])

    def test_tolerant_of_broken_existing(self):
        (self.data_dir / ta.STATUS_FILENAME).write_text("NOT JSON")
        out = ta.write_status(self._doc("v1"), self.data_dir)
        self.assertTrue(out["changed"])
        doc = json.loads((self.data_dir / ta.STATUS_FILENAME).read_text())
        self.assertIn("available", doc)

    def test_history_max_value(self):
        self.assertEqual(ta.HISTORY_MAX, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CLI tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI(_TmpBase):

    def _setup_valid(self):
        _write_equity(self.data_dir, _make_doc_from_weights(
            [{"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}]))

    def test_check_does_not_write(self):
        self._setup_valid()
        rc = ta.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        self._setup_valid()
        rc = ta.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_run_writes(self):
        self._setup_valid()
        rc = ta.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_run_idempotent_md5(self):
        self._setup_valid()
        p = self.data_dir / ta.STATUS_FILENAME
        ta.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(p.read_bytes()).hexdigest()
        ta.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_arg_exit_zero_error_stderr(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = ta.main(["--totally-bogus-arg"])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())

    def test_check_run_conflict_exit_zero(self):
        cap = io.StringIO()
        old = sys.stderr
        sys.stderr = cap
        try:
            rc = ta.main(["--check", "--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stderr = old
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", cap.getvalue())
        # conflict must not have written
        self.assertFalse((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_missing_data_exit_zero(self):
        rc = ta.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_subprocess_check(self):
        self._setup_valid()
        r = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
             "--check", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("available", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_subprocess_run_writes(self):
        self._setup_valid()
        r = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
             "--run", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("DATA_WRITTEN", r.stdout)
        self.assertTrue((self.data_dir / ta.STATUS_FILENAME).exists())

    def test_subprocess_run_idempotent(self):
        self._setup_valid()
        subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
             "--run", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        r = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
             "--run", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertIn("DATA_UNCHANGED", r.stdout)

    def test_subprocess_junk_exit_zero_no_traceback(self):
        r = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
             "--bogus-arg"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("ERROR", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_subprocess_no_tmp_leak(self):
        self._setup_valid()
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.turnover_analytics",
                 "--run", "--data-dir", str(self.data_dir)],
                capture_output=True, text=True, cwd=str(_REPO_ROOT),
            )
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Import / AST hygiene
# ═══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_IMPORTS = {
    "requests", "httpx", "aiohttp", "urllib3", "urllib",
    "web3", "eth_account",
    "numpy", "pandas", "scipy",
    "anthropic", "openai", "langchain", "litellm",
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

    def test_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_IMPORTS
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_real_llm_forbidden_lint_no_llm_sdk(self):
        # Reuse the project's own AST linter on this module's source.
        source = _MODULE_PATH.read_text(encoding="utf-8")
        violations = find_forbidden_imports(source, str(_MODULE_PATH))
        self.assertEqual(violations, [], msg=f"LLM SDK imports: {violations}")

    def test_module_compiles(self):
        py_compile.compile(str(_MODULE_PATH), doraise=True)

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
        # reuse-by-import marker: the source must import content_fingerprint
        # from tear_sheet rather than redefine it.
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("from spa_core.reporting.tear_sheet import content_fingerprint",
                      source)
        self.assertNotIn("def content_fingerprint", source)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. End-to-end smoke with realistic shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd(_TmpBase):

    def test_full_pipeline_round_trip(self):
        import random
        random.seed(7)
        protocols = ["aave_v3", "compound_v3", "yearn_v3", "euler_v2", "maple"]
        bars = []
        dts = _dates(30)
        for d in dts:
            positions = {p: max(1.0, 20000 + random.gauss(0, 3000)) for p in protocols}
            bars.append(_bar(d, positions))
        _write_equity(self.data_dir, _equity_doc(bars, is_demo=False))
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertTrue(d["available"])
        self.assertEqual(d["headline"]["num_observations"], 29)
        self.assertIn(d["verdict"], ("ok", "warn", "fail"))
        # recent_turnover bounded
        self.assertLessEqual(len(d["recent_turnover"]), ta.RECENT_TURNOVER_MAX)
        # round-trip persist
        out1 = ta.write_status(d, self.data_dir)
        self.assertTrue(out1["changed"])
        out2 = ta.write_status(d, self.data_dir)
        self.assertFalse(out2["changed"])

    def test_recent_turnover_bounded_to_90(self):
        dts = _dates(120)
        bars = [_bar(d, {"a": 0.5 + 0.001 * (i % 3), "b": 0.5 - 0.001 * (i % 3)})
                for i, d in enumerate(dts)]
        _write_equity(self.data_dir, _equity_doc(bars))
        d = ta.build_turnover_analytics(data_dir=self.data_dir)
        self.assertEqual(len(d["recent_turnover"]), ta.RECENT_TURNOVER_MAX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
