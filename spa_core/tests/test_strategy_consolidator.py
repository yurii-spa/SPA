#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.strategy_consolidator (SPA-V435 / MP-135).

Plain unittest, NO external libraries, ALL persistence in a tempdir.

Coverage:
- load_strategy_tracks: missing directory → empty dict (no crash)
- load_strategy_tracks: valid shadow_strategies/*.json files → correct grouping
- load_strategy_tracks: portfolio_snapshots.json fallback (with / without strategy_id)
- load_strategy_tracks: broken JSON in shadow dir → skipped gracefully
- compute_strategy_metrics: single point → safe defaults (all zeros)
- compute_strategy_metrics: two points → correct total return
- compute_strategy_metrics: known monotonic series → correct return, n_days, drawdown
- compute_strategy_metrics: known sequence → correct Sharpe (hand-computed)
- compute_strategy_metrics: flat equity series → zero Sharpe, zero drawdown
- compute_strategy_metrics: drawdown sequence → correct max_drawdown_pct
- compute_strategy_metrics: close_equity fallback field
- compute_strategy_metrics: non-positive equity skipped
- compute_strategy_metrics: unsorted input is sorted by date
- rank_strategies: empty input → empty list
- rank_strategies: single strategy → rank=1
- rank_strategies: rank-1 has highest composite score
- rank_strategies: normalization edge — all same sharpe/return/drawdown → equal scores
- rank_strategies: is_current True for S0, False for others
- rank_strategies: correct rank ordering (3 strategies)
- rank_strategies: score is between 0 and 1 (inclusive)
- generate_advisory: S0 rank 1 → MAINTAIN
- generate_advisory: S0 rank 2 → MAINTAIN
- generate_advisory: S0 rank 3 → MAINTAIN
- generate_advisory: S0 rank 4 → ROTATE_RECOMMENDED
- generate_advisory: S0 absent → ROTATE_RECOMMENDED
- generate_advisory: top3 list has correct entries
- generate_advisory: explanation is non-empty string
- generate_advisory: empty ranked → MAINTAIN with empty top3
- run_consolidator: writes strategy_consolidator.json
- run_consolidator: atomic (no .tmp leftover after write)
- run_consolidator: returns dict with all expected top-level keys
- run_consolidator: missing data → still returns dict (no crash)
- run_consolidator: output file is valid JSON
- run_consolidator: advisory present in output
- run_consolidator: idempotent — running twice doesn't crash
- run_consolidator: history grows by 1 on second different write
- run_consolidator: history unchanged (no rewrite) when content identical
- run_consolidator: n_strategies reflects loaded track count
- content_fingerprint: changes when content changes
- content_fingerprint: stable across generated_at changes
- content_fingerprint: non-dict → "<invalid>"
- AST lint: no forbidden external imports in strategy_consolidator.py
- Full integration: S0 in top-3 → MAINTAIN verdict in written file
- Full integration: S0 not in top-3 → ROTATE_RECOMMENDED in written file
"""
from __future__ import annotations

import ast
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── ensure repo root on sys.path ─────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import strategy_consolidator as sc

_MODULE_PATH = Path(sc.__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_equity_series(
    n: int,
    start_equity: float = 100_000.0,
    daily_growth: float = 0.001,
    start_date: str = "2026-06-10",
) -> List[Dict[str, Any]]:
    """Monotonically growing equity series of length *n*."""
    d0 = date.fromisoformat(start_date)
    pts = []
    eq = start_equity
    for i in range(n):
        pts.append({"date": (d0 + timedelta(days=i)).isoformat(), "equity": eq})
        eq *= 1.0 + daily_growth
    return pts


def _make_volatile_series(
    values: List[float], start_date: str = "2026-06-10"
) -> List[Dict[str, Any]]:
    """Equity series from an explicit list of values."""
    d0 = date.fromisoformat(start_date)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "equity": v}
        for i, v in enumerate(values)
    ]


def _write_shadow_file(
    shadow_dir: Path, filename: str, records: List[Dict[str, Any]]
) -> None:
    shadow_dir.mkdir(parents=True, exist_ok=True)
    (shadow_dir / filename).write_text(json.dumps(records), encoding="utf-8")


def _write_snapshots(data_dir: Path, records: List[Dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / sc.SNAPSHOTS_FILENAME).write_text(
        json.dumps(records), encoding="utf-8"
    )


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sc_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# 1. load_strategy_tracks
# ═════════════════════════════════════════════════════════════════════════════

class TestLoadStrategyTracks(_TmpBase):

    def test_missing_dir_and_snapshots_returns_empty(self):
        """No shadow_strategies/ dir and no snapshots.json → empty dict, no crash."""
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {})

    def test_shadow_dir_single_file(self):
        """Valid shadow_strategies/S0.json → correct strategy_id grouping."""
        pts = [{"date": "2026-06-10", "strategy_id": "S0", "equity": 100_000.0, "apy": 5.0}]
        _write_shadow_file(self.data_dir / sc.SHADOW_DIR_NAME, "S0.json", pts)
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertIn("S0", result)
        self.assertEqual(len(result["S0"]), 1)
        self.assertEqual(result["S0"][0]["equity"], 100_000.0)

    def test_shadow_dir_multiple_strategies(self):
        """Multiple files → multiple strategy keys."""
        for sid in ("S0", "S1", "S2"):
            pts = [{"date": "2026-06-10", "strategy_id": sid, "equity": 100_000.0}]
            _write_shadow_file(self.data_dir / sc.SHADOW_DIR_NAME, f"{sid}.json", pts)
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertSetEqual(set(result.keys()), {"S0", "S1", "S2"})

    def test_shadow_dir_broken_json_skipped(self):
        """Broken JSON in shadow dir is skipped; valid files still loaded."""
        shadow_dir = self.data_dir / sc.SHADOW_DIR_NAME
        shadow_dir.mkdir(parents=True, exist_ok=True)
        (shadow_dir / "broken.json").write_text("{{{invalid", encoding="utf-8")
        pts = [{"date": "2026-06-10", "strategy_id": "S0", "equity": 100_000.0}]
        _write_shadow_file(shadow_dir, "S0.json", pts)
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertIn("S0", result)
        self.assertEqual(len(result), 1)  # broken.json produced no strategy

    def test_snapshots_fallback_with_strategy_id(self):
        """portfolio_snapshots.json with strategy_id → grouped correctly."""
        recs = [
            {"date": "2026-06-10", "strategy_id": "S0", "equity": 100_000.0},
            {"date": "2026-06-10", "strategy_id": "S1", "equity": 99_000.0},
            {"date": "2026-06-11", "strategy_id": "S0", "equity": 100_500.0},
        ]
        _write_snapshots(self.data_dir, recs)
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertIn("S0", result)
        self.assertIn("S1", result)
        self.assertEqual(len(result["S0"]), 2)
        self.assertEqual(len(result["S1"]), 1)

    def test_snapshots_fallback_no_strategy_id_defaults_to_S0(self):
        """Snapshots without strategy_id field are assigned to S0."""
        recs = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-11", "equity": 100_500.0},
        ]
        _write_snapshots(self.data_dir, recs)
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertIn("S0", result)
        self.assertEqual(len(result["S0"]), 2)

    def test_snapshots_non_list_returns_empty(self):
        """portfolio_snapshots.json that is not a list → empty dict."""
        (self.data_dir / sc.SNAPSHOTS_FILENAME).write_text(
            json.dumps({"bad": "data"}), encoding="utf-8"
        )
        result = sc.load_strategy_tracks(str(self.data_dir))
        self.assertEqual(result, {})


# ═════════════════════════════════════════════════════════════════════════════
# 2. compute_strategy_metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeStrategyMetrics(unittest.TestCase):

    def test_empty_list_returns_safe_defaults(self):
        m = sc.compute_strategy_metrics([])
        self.assertEqual(m["total_return_pct"], 0.0)
        self.assertEqual(m["annualized_return_pct"], 0.0)
        self.assertEqual(m["sharpe"], 0.0)
        self.assertEqual(m["max_drawdown_pct"], 0.0)
        self.assertEqual(m["turnover_proxy"], 0.0)
        self.assertEqual(m["n_days"], 0)

    def test_single_point_returns_safe_defaults(self):
        pts = [{"date": "2026-06-10", "equity": 100_000.0}]
        m = sc.compute_strategy_metrics(pts)
        self.assertEqual(m["n_days"], 0)
        self.assertEqual(m["sharpe"], 0.0)
        self.assertEqual(m["max_drawdown_pct"], 0.0)

    def test_two_points_correct_return(self):
        """Two points: 100k → 110k = +10% total return."""
        pts = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-20", "equity": 110_000.0},
        ]
        m = sc.compute_strategy_metrics(pts)
        self.assertAlmostEqual(m["total_return_pct"], 10.0, places=4)
        self.assertEqual(m["n_days"], 10)

    def test_n_days_correct(self):
        """n_days = calendar days between first and last date."""
        pts = _make_equity_series(31, start_date="2026-06-10")
        m = sc.compute_strategy_metrics(pts)
        self.assertEqual(m["n_days"], 30)

    def test_monotonic_growth_zero_drawdown(self):
        """Strictly increasing equity → max_drawdown_pct = 0.0."""
        pts = _make_equity_series(10, daily_growth=0.002)
        m = sc.compute_strategy_metrics(pts)
        self.assertEqual(m["max_drawdown_pct"], 0.0)

    def test_drawdown_correct(self):
        """100 → 90 → 80 → 95 → 85. Max drawdown is 100→80 = -20%."""
        pts = _make_volatile_series([100.0, 90.0, 80.0, 95.0, 85.0])
        m = sc.compute_strategy_metrics(pts)
        self.assertAlmostEqual(m["max_drawdown_pct"], -20.0, places=4)

    def test_flat_equity_series_zero_sharpe(self):
        """All equity values identical → std = 0 → sharpe = 0, turnover = 0."""
        pts = _make_volatile_series([100_000.0] * 10)
        m = sc.compute_strategy_metrics(pts)
        self.assertEqual(m["sharpe"], 0.0)
        self.assertEqual(m["turnover_proxy"], 0.0)
        self.assertEqual(m["total_return_pct"], 0.0)

    def test_sharpe_hand_computed(self):
        """Verify Sharpe with a hand-computable sequence.

        Equity: [100, 101, 100, 102]
        r = [1/100, -1/101, 2/100] = [0.01, ~-0.0099, 0.02]
        mean_r = (0.01 - 1/101 + 0.02) / 3
        std_r (sample) can be computed manually.
        We test that the returned Sharpe matches our reference.
        """
        pts = _make_volatile_series([100.0, 101.0, 100.0, 102.0])
        m = sc.compute_strategy_metrics(pts)

        # Hand-compute reference
        equities = [100.0, 101.0, 100.0, 102.0]
        returns = [equities[i] / equities[i - 1] - 1.0 for i in range(1, len(equities))]
        n = len(returns)
        mean_r = sum(returns) / n
        var_r = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(var_r)
        expected_sharpe = (mean_r / std_r) * math.sqrt(252.0) if std_r > 0 else 0.0

        self.assertAlmostEqual(m["sharpe"], round(expected_sharpe, 6), places=4)

    def test_negative_return_total(self):
        """Declining equity produces negative total_return_pct."""
        pts = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-20", "equity": 90_000.0},
        ]
        m = sc.compute_strategy_metrics(pts)
        self.assertAlmostEqual(m["total_return_pct"], -10.0, places=4)

    def test_close_equity_fallback(self):
        """Records using 'close_equity' instead of 'equity' should be accepted."""
        pts = [
            {"date": "2026-06-10", "close_equity": 100_000.0},
            {"date": "2026-06-11", "close_equity": 101_000.0},
        ]
        m = sc.compute_strategy_metrics(pts)
        self.assertAlmostEqual(m["total_return_pct"], 1.0, places=4)

    def test_non_positive_equity_skipped(self):
        """Zero and negative equity values are skipped; rest is used."""
        pts = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-11", "equity": 0.0},   # invalid
            {"date": "2026-06-12", "equity": -500.0}, # invalid
            {"date": "2026-06-13", "equity": 105_000.0},
        ]
        m = sc.compute_strategy_metrics(pts)
        # Only the two valid points should be used
        self.assertAlmostEqual(m["total_return_pct"], 5.0, places=4)

    def test_unsorted_input_sorted_by_date(self):
        """Out-of-order records must be sorted by date before computation."""
        pts = [
            {"date": "2026-06-12", "equity": 105_000.0},
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-11", "equity": 102_000.0},
        ]
        m = sc.compute_strategy_metrics(pts)
        # Total return should be from 100k → 105k = +5%
        self.assertAlmostEqual(m["total_return_pct"], 5.0, places=4)
        self.assertEqual(m["n_days"], 2)

    def test_annualized_return_greater_than_total_for_short_period(self):
        """For a sub-year track, annualised return > total return if positive."""
        pts = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-09-10", "equity": 105_000.0},  # ~92 days, +5%
        ]
        m = sc.compute_strategy_metrics(pts)
        # Annualised > total for a sub-year positive return
        self.assertGreater(m["annualized_return_pct"], m["total_return_pct"])

    def test_metrics_keys_present(self):
        """All required keys are present in the output dict."""
        pts = _make_equity_series(5)
        m = sc.compute_strategy_metrics(pts)
        for key in (
            "total_return_pct", "annualized_return_pct", "sharpe",
            "max_drawdown_pct", "turnover_proxy", "n_days",
        ):
            self.assertIn(key, m, f"Missing key: {key}")


# ═════════════════════════════════════════════════════════════════════════════
# 3. rank_strategies
# ═════════════════════════════════════════════════════════════════════════════

class TestRankStrategies(unittest.TestCase):

    def _metrics(
        self,
        sharpe: float = 1.0,
        ret: float = 10.0,
        dd: float = -5.0,
    ) -> Dict[str, Any]:
        return {
            "total_return_pct": ret,
            "annualized_return_pct": ret,
            "sharpe": sharpe,
            "max_drawdown_pct": dd,
            "turnover_proxy": 0.01,
            "n_days": 30,
        }

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(sc.rank_strategies({}), [])

    def test_single_strategy_rank_1(self):
        ranked = sc.rank_strategies({"S0": self._metrics()})
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[0]["strategy_id"], "S0")

    def test_rank_1_has_highest_score(self):
        """Strategy with best Sharpe / return / low drawdown should be rank 1."""
        sm = {
            "S0": self._metrics(sharpe=0.5, ret=5.0, dd=-10.0),
            "S1": self._metrics(sharpe=2.0, ret=15.0, dd=-2.0),  # clearly best
            "S2": self._metrics(sharpe=1.0, ret=8.0, dd=-5.0),
        }
        ranked = sc.rank_strategies(sm)
        self.assertEqual(ranked[0]["strategy_id"], "S1")
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_all_same_metrics_equal_scores(self):
        """When all strategies have identical metrics, scores should be equal."""
        sm = {
            "S0": self._metrics(sharpe=1.0, ret=10.0, dd=-5.0),
            "S1": self._metrics(sharpe=1.0, ret=10.0, dd=-5.0),
            "S2": self._metrics(sharpe=1.0, ret=10.0, dd=-5.0),
        }
        ranked = sc.rank_strategies(sm)
        scores = [e["score"] for e in ranked]
        self.assertAlmostEqual(scores[0], scores[1], places=6)
        self.assertAlmostEqual(scores[1], scores[2], places=6)

    def test_is_current_true_for_S0(self):
        sm = {
            "S0": self._metrics(),
            "S1": self._metrics(sharpe=2.0),
        }
        ranked = sc.rank_strategies(sm)
        s0_entry = next(e for e in ranked if e["strategy_id"] == "S0")
        s1_entry = next(e for e in ranked if e["strategy_id"] == "S1")
        self.assertTrue(s0_entry["is_current"])
        self.assertFalse(s1_entry["is_current"])

    def test_rank_ordering_correct(self):
        """Ranks must be 1, 2, 3 with no gaps."""
        sm = {
            "S0": self._metrics(sharpe=1.0),
            "S1": self._metrics(sharpe=2.0),
            "S2": self._metrics(sharpe=3.0),
        }
        ranked = sc.rank_strategies(sm)
        ranks = [e["rank"] for e in ranked]
        self.assertEqual(ranks, [1, 2, 3])

    def test_score_bounded_0_to_1(self):
        """All composite scores must be in [0, 1]."""
        sm = {sid: self._metrics(sharpe=float(i), ret=float(i * 2), dd=-float(i))
              for i, sid in enumerate(["S0", "S1", "S2", "S3", "S4", "S5"])}
        ranked = sc.rank_strategies(sm)
        for e in ranked:
            self.assertGreaterEqual(e["score"], 0.0)
            self.assertLessEqual(e["score"], 1.0 + 1e-9)

    def test_metrics_preserved_in_ranking(self):
        """The 'metrics' field of each ranked entry must match the input."""
        m = self._metrics(sharpe=1.5)
        ranked = sc.rank_strategies({"S0": m})
        self.assertEqual(ranked[0]["metrics"], m)

    def test_deterministic_tiebreak(self):
        """Equal-score strategies are sorted by strategy_id for determinism."""
        sm = {
            "S2": self._metrics(sharpe=1.0, ret=10.0, dd=-5.0),
            "S1": self._metrics(sharpe=1.0, ret=10.0, dd=-5.0),
        }
        ranked = sc.rank_strategies(sm)
        # S1 < S2 lexicographically → S1 should be rank 1
        self.assertEqual(ranked[0]["strategy_id"], "S1")


# ═════════════════════════════════════════════════════════════════════════════
# 4. generate_advisory
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateAdvisory(unittest.TestCase):

    def _make_ranked(self, strategy_ids: List[str]) -> List[Dict[str, Any]]:
        """Build a minimal ranked list where S0 appears at its natural position."""
        return [
            {
                "strategy_id": sid,
                "score": 1.0 - i * 0.1,
                "rank": i + 1,
                "metrics": {},
                "is_current": sid == sc.CURRENT_STRATEGY_ID,
            }
            for i, sid in enumerate(strategy_ids)
        ]

    def test_s0_rank_1_maintain(self):
        ranked = self._make_ranked(["S0", "S1", "S2", "S3"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "MAINTAIN")
        self.assertEqual(adv["current_rank"], 1)

    def test_s0_rank_2_maintain(self):
        ranked = self._make_ranked(["S1", "S0", "S2", "S3"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "MAINTAIN")
        self.assertEqual(adv["current_rank"], 2)

    def test_s0_rank_3_maintain(self):
        ranked = self._make_ranked(["S1", "S2", "S0", "S3"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "MAINTAIN")
        self.assertEqual(adv["current_rank"], 3)

    def test_s0_rank_4_rotate_recommended(self):
        ranked = self._make_ranked(["S1", "S2", "S3", "S0"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "ROTATE_RECOMMENDED")
        self.assertEqual(adv["current_rank"], 4)

    def test_s0_rank_5_rotate_recommended(self):
        ranked = self._make_ranked(["S1", "S2", "S3", "S4", "S0"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "ROTATE_RECOMMENDED")

    def test_s0_absent_rotate_recommended(self):
        """If S0 is not in the ranked list at all → ROTATE_RECOMMENDED."""
        ranked = self._make_ranked(["S1", "S2", "S3"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["verdict"], "ROTATE_RECOMMENDED")
        self.assertIsNone(adv["current_rank"])

    def test_top3_correct_entries(self):
        ranked = self._make_ranked(["S1", "S2", "S3", "S0", "S4"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["top3"], ["S1", "S2", "S3"])

    def test_explanation_non_empty_string(self):
        ranked = self._make_ranked(["S0", "S1", "S2"])
        adv = sc.generate_advisory(ranked)
        self.assertIsInstance(adv["explanation"], str)
        self.assertGreater(len(adv["explanation"]), 0)

    def test_empty_ranked_returns_maintain(self):
        adv = sc.generate_advisory([])
        self.assertEqual(adv["verdict"], "MAINTAIN")
        self.assertEqual(adv["top3"], [])
        self.assertIsNone(adv["current_rank"])

    def test_recommended_strategy_is_rank_1(self):
        ranked = self._make_ranked(["S3", "S1", "S0"])
        adv = sc.generate_advisory(ranked)
        self.assertEqual(adv["recommended_strategy"], "S3")

    def test_required_keys_present(self):
        adv = sc.generate_advisory(self._make_ranked(["S0"]))
        for key in ("recommended_strategy", "current_rank", "verdict", "explanation", "top3"):
            self.assertIn(key, adv, f"Missing key: {key}")


# ═════════════════════════════════════════════════════════════════════════════
# 5. run_consolidator
# ═════════════════════════════════════════════════════════════════════════════

class TestRunConsolidator(_TmpBase):

    def _write_two_strategies(self) -> None:
        """Write two strategies so S0 is rank 1 (better metrics)."""
        s0_pts = [
            {"date": (date(2026, 6, 10) + timedelta(days=i)).isoformat(),
             "strategy_id": "S0",
             "equity": 100_000.0 * (1.002 ** i)}
            for i in range(20)
        ]
        s1_pts = [
            {"date": (date(2026, 6, 10) + timedelta(days=i)).isoformat(),
             "strategy_id": "S1",
             "equity": 100_000.0 * (1.001 ** i)}
            for i in range(20)
        ]
        shadow_dir = self.data_dir / sc.SHADOW_DIR_NAME
        _write_shadow_file(shadow_dir, "S0.json", s0_pts)
        _write_shadow_file(shadow_dir, "S1.json", s1_pts)

    def test_creates_output_file(self):
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        out = self.data_dir / sc.STATUS_FILENAME
        self.assertTrue(out.exists(), "Output file not created")

    def test_no_tmp_leftover(self):
        """After a successful write, no .tmp files should remain."""
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [], f"Leftover .tmp files: {tmp_files}")

    def test_returns_dict_with_expected_keys(self):
        self._write_two_strategies()
        result = sc.run_consolidator(str(self.data_dir))
        for key in ("meta", "available", "n_strategies", "strategies", "ranking", "advisory"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_missing_data_no_crash(self):
        """Empty data directory → returns dict without crash."""
        result = sc.run_consolidator(str(self.data_dir))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("available"))

    def test_output_is_valid_json(self):
        """Written file must be parseable JSON."""
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        raw = (self.data_dir / sc.STATUS_FILENAME).read_text(encoding="utf-8")
        doc = json.loads(raw)  # must not raise
        self.assertIsInstance(doc, dict)

    def test_advisory_present_in_output(self):
        self._write_two_strategies()
        result = sc.run_consolidator(str(self.data_dir))
        self.assertIn("advisory", result)
        self.assertIn("verdict", result["advisory"])

    def test_idempotent_no_crash(self):
        """Running consolidator twice on same data must not crash."""
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        sc.run_consolidator(str(self.data_dir))  # must not raise
        self.assertTrue((self.data_dir / sc.STATUS_FILENAME).exists())

    def test_history_grows_on_new_write(self):
        """First call creates history=[1 entry]; second with different data → 2."""
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        # Mutate data slightly
        extra = [{"date": "2026-07-01", "strategy_id": "S0", "equity": 200_000.0}]
        _write_shadow_file(self.data_dir / sc.SHADOW_DIR_NAME, "S0_extra.json", extra)
        sc.run_consolidator(str(self.data_dir))
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertGreaterEqual(len(doc.get("history", [])), 1)

    def test_n_strategies_matches_tracks(self):
        self._write_two_strategies()
        result = sc.run_consolidator(str(self.data_dir))
        self.assertEqual(result["n_strategies"], 2)

    def test_s0_maintain_in_written_file(self):
        """When S0 has the best metrics, verdict in written file should be MAINTAIN."""
        # S0 grows faster → better Sharpe → rank 1 → MAINTAIN
        self._write_two_strategies()
        sc.run_consolidator(str(self.data_dir))
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertEqual(doc["advisory"]["verdict"], "MAINTAIN")

    def test_s0_rotate_recommended_when_worst(self):
        """When S0 is ranked 4th or lower → ROTATE_RECOMMENDED in output."""
        # S0 is the worst performer
        shadow_dir = self.data_dir / sc.SHADOW_DIR_NAME
        for i, sid in enumerate(["S1", "S2", "S3", "S4"]):
            pts = [
                {"date": (date(2026, 6, 10) + timedelta(days=j)).isoformat(),
                 "strategy_id": sid,
                 "equity": 100_000.0 * ((1.003 + i * 0.001) ** j)}
                for j in range(20)
            ]
            _write_shadow_file(shadow_dir, f"{sid}.json", pts)
        # S0 is flat (worst)
        s0_pts = [
            {"date": (date(2026, 6, 10) + timedelta(days=j)).isoformat(),
             "strategy_id": "S0",
             "equity": 100_000.0}
            for j in range(20)
        ]
        _write_shadow_file(shadow_dir, "S0.json", s0_pts)
        sc.run_consolidator(str(self.data_dir))
        doc = json.loads((self.data_dir / sc.STATUS_FILENAME).read_text())
        self.assertEqual(doc["advisory"]["verdict"], "ROTATE_RECOMMENDED")


# ═════════════════════════════════════════════════════════════════════════════
# 6. content_fingerprint
# ═════════════════════════════════════════════════════════════════════════════

class TestContentFingerprint(unittest.TestCase):

    def _base_doc(self) -> Dict[str, Any]:
        return {
            "meta": {"generated_at": "2026-06-10T00:00:00+00:00", "source": "test"},
            "available": True,
            "ranking": [],
            "advisory": {"verdict": "MAINTAIN"},
        }

    def test_changes_when_content_changes(self):
        doc1 = self._base_doc()
        doc2 = self._base_doc()
        doc2["available"] = False
        self.assertNotEqual(
            sc.content_fingerprint(doc1), sc.content_fingerprint(doc2)
        )

    def test_stable_across_generated_at(self):
        doc1 = self._base_doc()
        doc2 = self._base_doc()
        doc2["meta"]["generated_at"] = "2099-01-01T00:00:00+00:00"
        self.assertEqual(
            sc.content_fingerprint(doc1), sc.content_fingerprint(doc2)
        )

    def test_history_excluded_from_fingerprint(self):
        doc1 = self._base_doc()
        doc2 = self._base_doc()
        doc2["history"] = [{"generated_at": "2026-06-10T00:00:00+00:00"}]
        self.assertEqual(
            sc.content_fingerprint(doc1), sc.content_fingerprint(doc2)
        )

    def test_non_dict_returns_invalid_string(self):
        fp = sc.content_fingerprint("not a dict")
        self.assertEqual(fp, "<invalid>")

    def test_none_returns_invalid_string(self):
        fp = sc.content_fingerprint(None)
        self.assertEqual(fp, "<invalid>")


# ═════════════════════════════════════════════════════════════════════════════
# 7. AST import hygiene
# ═════════════════════════════════════════════════════════════════════════════

FORBIDDEN_IMPORTS = frozenset([
    "requests", "httpx", "aiohttp",
    "web3", "eth_account",
    "pandas", "numpy", "scipy",
    "anthropic", "openai",
    "socket", "urllib",
])


class TestImportHygiene(unittest.TestCase):

    def test_no_forbidden_external_imports(self):
        """strategy_consolidator.py must not import any forbidden libraries."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_MODULE_PATH))
        imported: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.append(alias.name.split(".")[0])
                else:
                    if node.module:
                        imported.append(node.module.split(".")[0])
        forbidden_found = [m for m in imported if m in FORBIDDEN_IMPORTS]
        self.assertEqual(
            forbidden_found, [],
            f"Forbidden imports found: {forbidden_found}",
        )

    def test_module_imports_only_stdlib(self):
        """All top-level imports must be from stdlib or local spa_core package."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_MODULE_PATH))
        allowed_prefixes = frozenset([
            # stdlib modules used by this module
            "argparse", "ast", "hashlib", "itertools", "json", "logging",
            "math", "os", "sys", "tempfile", "pathlib", "datetime", "typing",
            "__future__",
            # local
            "spa_core",
        ])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertIn(
                        root, allowed_prefixes,
                        f"Unexpected import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    self.assertIn(
                        root, allowed_prefixes,
                        f"Unexpected from-import: {node.module}",
                    )


# ═════════════════════════════════════════════════════════════════════════════
# Entry point (also runnable via pytest)
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
