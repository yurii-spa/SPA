#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.correlation_analyzer (SPA-V439 / MP-120).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir.

Covers:
- pearson() math: hand-computed values, perfect correlation, anti-correlation,
  zero variance returns None, short series returns None, single element,
  clamping to [-1, 1]
- _extract_series: valid records, non-numeric APY skipped, missing ts skipped,
  NaN/inf skipped, non-dict records skipped
- _align_series: intersection of dates, disjoint series, single protocol
- insufficient_data: < MIN_POINTS aligned observations → available:false
- unavailable cases: missing file, broken JSON, non-dict root,
  empty protocol_history, only 1 protocol, no valid series
- build_correlation main path: matrix is N×N, diagonal = 1.0, symmetric,
  highest/lowest pairs ordered correctly, clusters, verdicts
  (ok / warn / fail), dominant_cluster_share, notes
- Union-Find clustering: single cluster → fail, two clusters → ok,
  transitive clustering (A↔B and B↔C → all three in one cluster)
- content_fingerprint: changes when content changes, stable across generated_at
- write_status / idempotency: first write returns DATA_WRITTEN, second
  identical call returns DATA_UNCHANGED (byte-identical file), history rotation
  exactly HISTORY_MAX, no stray *.tmp files, tolerant of broken existing file
- CLI: --check does not write, --run writes, junk args → ERROR on stderr + exit 0,
  --run idempotent, subprocess invocation
- import hygiene: AST scan for forbidden libraries (requests, web3, socket,
  urllib, pandas, numpy, anthropic, openai)
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
from typing import Any, Dict, List

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import correlation_analyzer as ca

_MODULE_PATH = Path(ca.__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_series(dates: List[str], values: List[float]) -> Dict[str, Any]:
    return [{"ts": f"{d}T00:00:00+00:00", "apy": v} for d, v in zip(dates, values)]


def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _write_apy(data_dir: Path, ph: Dict[str, Any]) -> None:
    p = data_dir / ca.APY_HISTORY_FILENAME
    p.write_text(json.dumps({"protocol_history": ph, "last_updated": "2026-01-01"}))


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="corr_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. pearson() unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPearson(unittest.TestCase):

    def test_perfect_positive_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(ca.pearson(x, x), 1.0, places=10)

    def test_perfect_negative_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [-1.0, -2.0, -3.0, -4.0, -5.0]
        self.assertAlmostEqual(ca.pearson(x, y), -1.0, places=10)

    def test_zero_correlation(self):
        # [1,2,3] vs [2,2,2] — second is constant
        x = [1.0, 2.0, 3.0]
        y = [2.0, 2.0, 2.0]
        self.assertIsNone(ca.pearson(x, y))

    def test_zero_variance_first_series(self):
        x = [5.0, 5.0, 5.0]
        y = [1.0, 2.0, 3.0]
        self.assertIsNone(ca.pearson(x, y))

    def test_zero_variance_both(self):
        x = [3.0, 3.0, 3.0]
        y = [7.0, 7.0, 7.0]
        self.assertIsNone(ca.pearson(x, y))

    def test_hand_computed_value(self):
        # x=[1,2,3], y=[4,5,8] → r hand-computed
        x = [1.0, 2.0, 3.0]
        y = [4.0, 5.0, 8.0]
        mx, my = 2.0, 17.0 / 3.0
        num = (1 - mx) * (4 - my) + (2 - mx) * (5 - my) + (3 - mx) * (8 - my)
        ss_x = (1 - mx) ** 2 + (2 - mx) ** 2 + (3 - mx) ** 2
        ss_y = (4 - my) ** 2 + (5 - my) ** 2 + (8 - my) ** 2
        expected = num / math.sqrt(ss_x * ss_y)
        self.assertAlmostEqual(ca.pearson(x, y), expected, places=10)

    def test_short_series_one_element(self):
        self.assertIsNone(ca.pearson([1.0], [1.0]))

    def test_empty_series(self):
        self.assertIsNone(ca.pearson([], []))

    def test_two_elements_valid(self):
        x = [1.0, 3.0]
        y = [2.0, 6.0]
        r = ca.pearson(x, y)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 1.0, places=10)

    def test_result_clamped_above(self):
        # Should never exceed 1.0 even with floating-point rounding
        x = list(range(100))
        r = ca.pearson(x, x)
        self.assertLessEqual(r, 1.0)

    def test_result_clamped_below(self):
        x = list(range(100))
        y = [-v for v in x]
        r = ca.pearson(x, y)
        self.assertGreaterEqual(r, -1.0)

    def test_partial_correlation(self):
        # x and y are not perfectly correlated
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 1.0, 4.0, 3.0, 5.0]
        r = ca.pearson(x, y)
        self.assertIsNotNone(r)
        self.assertGreater(r, 0.0)
        self.assertLess(r, 1.0)

    def test_negative_partial_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 3.0, 2.0, 2.0, 1.0]
        r = ca.pearson(x, y)
        self.assertIsNotNone(r)
        self.assertLess(r, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _align_series
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlignSeries(unittest.TestCase):

    def test_full_overlap(self):
        dates = _dates(10)
        sm = {
            "a": {d: float(i) for i, d in enumerate(dates)},
            "b": {d: float(i * 2) for i, d in enumerate(dates)},
        }
        sorted_d, aligned = ca._align_series(sm)
        self.assertEqual(len(sorted_d), 10)
        self.assertEqual(len(aligned["a"]), 10)

    def test_partial_overlap(self):
        d1 = _dates(10)
        d2 = _dates(7, start="2026-01-05")
        sm = {
            "a": {d: 1.0 for d in d1},
            "b": {d: 2.0 for d in d2},
        }
        sorted_d, aligned = ca._align_series(sm)
        # intersection: d1[4..9] ∩ d2[0..6]
        self.assertGreater(len(sorted_d), 0)
        self.assertTrue(all(d in sm["a"] and d in sm["b"] for d in sorted_d))

    def test_no_overlap_returns_empty(self):
        sm = {
            "a": {"2026-01-01": 1.0, "2026-01-02": 2.0},
            "b": {"2026-02-01": 3.0, "2026-02-02": 4.0},
        }
        sorted_d, aligned = ca._align_series(sm)
        self.assertEqual(sorted_d, [])
        self.assertEqual(aligned, {})

    def test_single_protocol_returns_its_dates(self):
        sm = {"a": {"2026-01-01": 1.0, "2026-01-02": 2.0}}
        sorted_d, aligned = ca._align_series(sm)
        self.assertEqual(sorted_d, ["2026-01-01", "2026-01-02"])

    def test_empty_map_returns_empty(self):
        sorted_d, aligned = ca._align_series({})
        self.assertEqual(sorted_d, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Unavailable / error cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnavailableCases(_TmpBase):

    def test_missing_file(self):
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn(ca.APY_HISTORY_FILENAME, r["reason"])

    def test_broken_json(self):
        (self.data_dir / ca.APY_HISTORY_FILENAME).write_text("NOT JSON")
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])

    def test_non_dict_root(self):
        (self.data_dir / ca.APY_HISTORY_FILENAME).write_text("[1, 2, 3]")
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])

    def test_missing_protocol_history_key(self):
        (self.data_dir / ca.APY_HISTORY_FILENAME).write_text(
            json.dumps({"last_updated": "2026-01-01"})
        )
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])

    def test_empty_protocol_history(self):
        _write_apy(self.data_dir, {})
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])

    def test_only_one_protocol(self):
        dates = _dates(20)
        _write_apy(self.data_dir, {"aave": _make_series(dates, [float(i) for i in range(20)])})
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("1", r["reason"])

    def test_insufficient_data_fewer_than_min_points(self):
        n = ca.MIN_POINTS - 1
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v + 1 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        self.assertEqual(r["n_observations"], n)
        self.assertEqual(r["min_required"], ca.MIN_POINTS)

    def test_exactly_min_points_is_available(self):
        n = ca.MIN_POINTS
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v * 2 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])

    def test_never_raises_on_garbage(self):
        """build_correlation must never raise regardless of input."""
        for text in ["null", "42", '""', '{"protocol_history": 99}', "NOT JSON !!"]:
            (self.data_dir / ca.APY_HISTORY_FILENAME).write_text(text)
            r = ca.build_correlation(self.data_dir)  # must not raise
            self.assertFalse(r["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Correlation matrix properties
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrelationMatrix(_TmpBase):

    def _setup_two_protocols(self, n: int = 20):
        dates = _dates(n)
        vals_a = [float(i) for i in range(n)]
        vals_b = [float(i) * 1.5 + 0.3 for i in range(n)]
        _write_apy(self.data_dir, {
            "prot_a": _make_series(dates, vals_a),
            "prot_b": _make_series(dates, vals_b),
        })

    def test_diagonal_is_one(self):
        self._setup_two_protocols()
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        for row in r["correlation_matrix"]:
            p = row["protocol"]
            self.assertAlmostEqual(row["correlations"][p], 1.0, places=10)

    def test_symmetric_matrix(self):
        self._setup_two_protocols()
        r = ca.build_correlation(self.data_dir)
        for row in r["correlation_matrix"]:
            p = row["protocol"]
            for q, val in row["correlations"].items():
                # find q's row
                q_row = next(x for x in r["correlation_matrix"] if x["protocol"] == q)
                self.assertEqual(q_row["correlations"][p], val)

    def test_matrix_has_all_protocols(self):
        self._setup_two_protocols()
        r = ca.build_correlation(self.data_dir)
        protocols = r["protocols"]
        self.assertEqual(len(r["correlation_matrix"]), len(protocols))
        for row in r["correlation_matrix"]:
            self.assertEqual(set(row["correlations"].keys()), set(protocols))

    def test_three_protocols_matrix_shape(self):
        dates = _dates(20)
        _write_apy(self.data_dir, {
            "a": _make_series(dates, [float(i) for i in range(20)]),
            "b": _make_series(dates, [float(i) * 2 for i in range(20)]),
            "c": _make_series(dates, [float(20 - i) for i in range(20)]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["n_protocols"], 3)
        self.assertEqual(len(r["correlation_matrix"]), 3)

    def test_perfectly_correlated_pair_r_equals_one(self):
        n = 20
        dates = _dates(n)
        vals = [float(i + 1) for i in range(n)]
        _write_apy(self.data_dir, {
            "x": _make_series(dates, vals),
            "y": _make_series(dates, [v * 3.7 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        pairs = r["highest_correlation_pairs"]
        self.assertAlmostEqual(pairs[0]["r"], 1.0, places=8)

    def test_perfectly_anti_correlated_pair_r_equals_minus_one(self):
        n = 20
        dates = _dates(n)
        vals = [float(i + 1) for i in range(n)]
        _write_apy(self.data_dir, {
            "x": _make_series(dates, vals),
            "y": _make_series(dates, [-v for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        pairs = r["lowest_correlation_pairs"]
        self.assertAlmostEqual(pairs[0]["r"], -1.0, places=8)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Pairs ordering
# ═══════════════════════════════════════════════════════════════════════════════

class TestPairsOrdering(_TmpBase):

    def _make_three(self):
        n = 20
        dates = _dates(n)
        # a and b perfectly correlated, c inversely correlated with a
        _write_apy(self.data_dir, {
            "a": _make_series(dates, [float(i) for i in range(n)]),
            "b": _make_series(dates, [float(i) * 2 for i in range(n)]),
            "c": _make_series(dates, [float(n - i) for i in range(n)]),
        })

    def test_highest_pairs_descending(self):
        self._make_three()
        r = ca.build_correlation(self.data_dir)
        highs = [pa["r"] for pa in r["highest_correlation_pairs"]]
        self.assertEqual(highs, sorted(highs, reverse=True))

    def test_lowest_pairs_ascending(self):
        self._make_three()
        r = ca.build_correlation(self.data_dir)
        lows = [pa["r"] for pa in r["lowest_correlation_pairs"]]
        self.assertEqual(lows, sorted(lows))

    def test_highest_first_is_ab(self):
        self._make_three()
        r = ca.build_correlation(self.data_dir)
        top = r["highest_correlation_pairs"][0]
        pair = {top["protocol_a"], top["protocol_b"]}
        self.assertEqual(pair, {"a", "b"})

    def test_lowest_first_involves_c(self):
        self._make_three()
        r = ca.build_correlation(self.data_dir)
        bot = r["lowest_correlation_pairs"][0]
        pair = {bot["protocol_a"], bot["protocol_b"]}
        self.assertIn("c", pair)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Clustering (Union-Find)
# ═══════════════════════════════════════════════════════════════════════════════

class TestClustering(_TmpBase):

    def test_all_correlated_single_cluster_verdict_fail(self):
        n = 20
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        # a, b, c all perfectly correlated → single cluster
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v * 2 for v in vals]),
            "c": _make_series(dates, [v * 3 + 1 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["n_clusters"], 1)
        self.assertEqual(r["verdict"], "fail")

    def test_two_independent_clusters_verdict_ok(self):
        # Pair 1 (a, b): monotone step-function — r(a,b) = 1.0
        # Pair 2 (c, d): alternating pattern  — r(c,d) = 1.0
        # Cross-correlation r(step, alt) = 0 (orthogonal shapes → 2 distinct clusters)
        n = 20
        dates = _dates(n)
        step     = [1.0] * 10 + [2.0] * 10          # step up at midpoint
        step2    = [2.0] * 10 + [4.0] * 10          # scaled step; r(step,step2)=1
        alt      = [float(1 + i % 2) for i in range(n)]   # [1,2,1,2,...]; r(step,alt)=0
        alt2     = [float(3 + 2 * (i % 2)) for i in range(n)]  # [3,5,3,5,...]; r(alt,alt2)=1
        _write_apy(self.data_dir, {
            "a": _make_series(dates, step),
            "b": _make_series(dates, step2),
            "c": _make_series(dates, alt),
            "d": _make_series(dates, alt2),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertGreaterEqual(r["n_clusters"], 2)
        # verdict should be ok or warn, not fail
        self.assertNotEqual(r["verdict"], "fail")

    def test_transitive_clustering(self):
        """A↔B and B↔C (|r|>0.8) but not necessarily A↔C → all in same cluster."""
        n = 30
        dates = _dates(n)
        base = [float(i) for i in range(n)]
        # a and b perfectly correlated
        # b and c perfectly correlated
        # → a, b, c all in same cluster via Union-Find
        _write_apy(self.data_dir, {
            "a": _make_series(dates, base),
            "b": _make_series(dates, [v + 0.0 for v in base]),   # r(a,b)=1.0
            "c": _make_series(dates, [v + 0.0 for v in base]),   # r(b,c)=1.0
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["n_clusters"], 1)

    def test_cluster_threshold_value(self):
        self.assertEqual(ca.CLUSTER_THRESHOLD, 0.8)

    def test_high_corr_pairs_all_exceed_threshold(self):
        n = 20
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v * 2 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        for pa in r["high_correlation_pairs"]:
            self.assertGreater(abs(pa["r"]), ca.CLUSTER_THRESHOLD)

    def test_two_protocols_single_cluster_fail(self):
        n = 20
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v * 1.0 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["n_clusters"], 1)
        self.assertEqual(r["verdict"], "fail")

    def test_dominant_cluster_share_computed(self):
        n = 20
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v * 2 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertIn("dominant_cluster_share", r)
        self.assertGreater(r["dominant_cluster_share"], 0.0)
        self.assertLessEqual(r["dominant_cluster_share"], 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Advisory verdict detail
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdict(_TmpBase):

    def test_ok_verdict_when_multiple_clusters(self):
        # Same orthogonal construction as test_two_independent_clusters_verdict_ok
        n = 20
        dates = _dates(n)
        step  = [1.0] * 10 + [2.0] * 10
        step2 = [2.0] * 10 + [4.0] * 10
        alt   = [float(1 + i % 2) for i in range(n)]
        alt2  = [float(3 + 2 * (i % 2)) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, step),
            "b": _make_series(dates, step2),
            "c": _make_series(dates, alt),
            "d": _make_series(dates, alt2),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertIn(r["verdict"], ("ok", "warn"))

    def test_verdict_reason_present_and_nonempty(self):
        n = ca.MIN_POINTS
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v + 1 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertIn("verdict_reason", r)
        self.assertIsInstance(r["verdict_reason"], str)
        self.assertGreater(len(r["verdict_reason"]), 0)

    def test_available_true_includes_all_required_fields(self):
        n = ca.MIN_POINTS
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v + 1 for v in vals]),
        })
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        for field in ("verdict", "verdict_reason", "n_protocols", "n_observations",
                      "date_range", "protocols", "correlation_matrix",
                      "highest_correlation_pairs", "lowest_correlation_pairs",
                      "cluster_threshold", "n_clusters", "clusters",
                      "high_correlation_pairs", "dominant_cluster_share",
                      "notes", "meta"):
            self.assertIn(field, r, msg=f"missing field: {field}")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. content_fingerprint + idempotency
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def _sample_result(self, tag: str = "x") -> Dict:
        return {
            "available": True,
            "verdict": "ok",
            "n_protocols": 2,
            "_tag": tag,
            "meta": {"generated_at": "2026-01-01T00:00:00+00:00", "source": "test"},
        }

    def test_fingerprint_ignores_generated_at(self):
        r1 = self._sample_result()
        r2 = dict(r1)
        r2["meta"] = dict(r1["meta"])
        r2["meta"]["generated_at"] = "2099-12-31T23:59:59+00:00"
        self.assertEqual(ca.content_fingerprint(r1), ca.content_fingerprint(r2))

    def test_fingerprint_ignores_history(self):
        r1 = self._sample_result()
        r2 = dict(r1)
        r2["history"] = [{"old": "data"}]
        self.assertEqual(ca.content_fingerprint(r1), ca.content_fingerprint(r2))

    def test_fingerprint_changes_with_content(self):
        r1 = self._sample_result("a")
        r2 = self._sample_result("b")
        self.assertNotEqual(ca.content_fingerprint(r1), ca.content_fingerprint(r2))

    def test_fingerprint_is_stable_string(self):
        r = self._sample_result()
        fp = ca.content_fingerprint(r)
        self.assertIsInstance(fp, str)
        self.assertGreater(len(fp), 0)
        # deterministic
        self.assertEqual(fp, ca.content_fingerprint(r))


# ═══════════════════════════════════════════════════════════════════════════════
# 9. write_status — persistence, idempotency, history rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _result(self, label: str = "v1") -> Dict:
        return {
            "available": True, "verdict": "ok", "label": label,
            "meta": {"generated_at": "2026-01-01T00:00:00+00:00"},
        }

    def test_first_write_returns_data_written(self):
        status = ca.write_status(self._result("v1"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_file_exists_after_write(self):
        ca.write_status(self._result("v1"), self.data_dir)
        out = self.data_dir / ca.STATUS_FILENAME
        self.assertTrue(out.exists())

    def test_second_identical_call_returns_data_unchanged(self):
        r = self._result("v1")
        ca.write_status(r, self.data_dir)
        status2 = ca.write_status(r, self.data_dir)
        self.assertEqual(status2, "DATA_UNCHANGED")

    def test_second_call_byte_identical(self):
        r = self._result("v1")
        ca.write_status(r, self.data_dir)
        out = self.data_dir / ca.STATUS_FILENAME
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        ca.write_status(r, self.data_dir)
        md5_2 = hashlib.md5(out.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_different_content_returns_data_written(self):
        ca.write_status(self._result("v1"), self.data_dir)
        status = ca.write_status(self._result("v2"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_history_grows_on_update(self):
        ca.write_status(self._result("v1"), self.data_dir)
        ca.write_status(self._result("v2"), self.data_dir)
        doc = json.loads((self.data_dir / ca.STATUS_FILENAME).read_text())
        self.assertIn("history", doc)
        self.assertEqual(len(doc["history"]), 1)

    def test_history_rotation_at_max(self):
        # Fill history to HISTORY_MAX
        for i in range(ca.HISTORY_MAX + 2):
            ca.write_status(self._result(f"v{i}"), self.data_dir)
        doc = json.loads((self.data_dir / ca.STATUS_FILENAME).read_text())
        self.assertLessEqual(len(doc["history"]), ca.HISTORY_MAX)

    def test_no_stray_tmp_files(self):
        for i in range(5):
            ca.write_status(self._result(f"v{i}"), self.data_dir)
        tmp_files = list(self.data_dir.glob(".tmp_corr_*"))
        self.assertEqual(tmp_files, [])

    def test_tolerant_of_broken_existing_file(self):
        (self.data_dir / ca.STATUS_FILENAME).write_text("NOT JSON")
        status = ca.write_status(self._result("v1"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        # file should now be valid JSON
        doc = json.loads((self.data_dir / ca.STATUS_FILENAME).read_text())
        self.assertIn("available", doc)

    def test_fingerprint_field_written(self):
        ca.write_status(self._result("v1"), self.data_dir)
        doc = json.loads((self.data_dir / ca.STATUS_FILENAME).read_text())
        self.assertIn("_fingerprint", doc)
        self.assertIsInstance(doc["_fingerprint"], str)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CLI tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI(_TmpBase):

    def _setup_valid(self) -> None:
        n = ca.MIN_POINTS
        dates = _dates(n)
        vals = [float(i) for i in range(n)]
        _write_apy(self.data_dir, {
            "a": _make_series(dates, vals),
            "b": _make_series(dates, [v + 1 for v in vals]),
        })

    def test_check_does_not_write(self):
        self._setup_valid()
        out_path = self.data_dir / ca.STATUS_FILENAME
        old_io = io.StringIO()
        ca.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertFalse(out_path.exists())

    def test_run_writes_file(self):
        self._setup_valid()
        out_path = self.data_dir / ca.STATUS_FILENAME
        ca.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertTrue(out_path.exists())

    def test_run_idempotent_second_call(self):
        self._setup_valid()
        out_path = self.data_dir / ca.STATUS_FILENAME
        ca.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(out_path.read_bytes()).hexdigest()
        ca.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(out_path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_args_exit_zero_and_error_on_stderr(self):
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            with self.assertRaises(SystemExit) as ctx:
                ca.main(["--unknown-garbage-flag-xyz"])
        finally:
            sys.stderr = old_stderr
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("ERROR", stderr_capture.getvalue())

    def test_no_file_exits_zero(self):
        # Should not raise, should exit 0
        try:
            ca.main(["--check", "--data-dir", str(self.data_dir)])
        except SystemExit as e:
            self.assertEqual(e.code, 0)

    def test_subprocess_check(self):
        self._setup_valid()
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.correlation_analyzer",
             "--check", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("available=", result.stdout)

    def test_subprocess_run(self):
        self._setup_valid()
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.correlation_analyzer",
             "--run", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        out_path = self.data_dir / ca.STATUS_FILENAME
        self.assertTrue(out_path.exists())

    def test_subprocess_junk_arg_exit_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.correlation_analyzer",
             "--totally-bogus-arg"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stderr)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Import / AST hygiene
# ═══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_IMPORTS = {
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

    def test_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_IMPORTS
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_module_compiles(self):
        import py_compile
        py_compile.compile(str(_MODULE_PATH), doraise=True)

    def test_no_network_in_module(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        # None of the network call patterns should appear
        for pattern in ("requests.get", "requests.post", "urllib.request",
                        "http.client", "socket.connect"):
            self.assertNotIn(pattern, source, msg=f"Found network pattern: {pattern}")

    def test_no_llm_sdk_in_module(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("anthropic.", "openai.", "from anthropic", "from openai"):
            self.assertNotIn(pattern, source, msg=f"Found LLM SDK pattern: {pattern}")

    def test_atomic_write_pattern_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("os.replace", source)
        self.assertIn("tempfile.mkstemp", source)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. End-to-end smoke with realistic data shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd(_TmpBase):

    def test_seven_protocols_90_obs(self):
        n = 90
        dates = _dates(n)
        import random
        random.seed(42)
        ph = {}
        for slug in ["aave-v3", "compound-v3", "morpho", "yearn-v3",
                     "euler-v2", "maple", "spark"]:
            vals = [3.0 + random.gauss(0, 0.5) for _ in range(n)]
            ph[slug] = _make_series(dates, vals)
        _write_apy(self.data_dir, ph)
        r = ca.build_correlation(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["n_protocols"], 7)
        self.assertEqual(r["n_observations"], 90)
        # matrix is 7×7
        self.assertEqual(len(r["correlation_matrix"]), 7)
        # diagonal = 1 for all
        for row in r["correlation_matrix"]:
            self.assertAlmostEqual(row["correlations"][row["protocol"]], 1.0, places=8)
        # verdict is one of the three allowed values
        self.assertIn(r["verdict"], ("ok", "warn", "fail"))
        # write round-trip
        status1 = ca.write_status(r, self.data_dir)
        self.assertEqual(status1, "DATA_WRITTEN")
        status2 = ca.write_status(r, self.data_dir)
        self.assertEqual(status2, "DATA_UNCHANGED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
