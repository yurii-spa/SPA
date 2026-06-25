#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.drawdown_attribution (MP-127).

Plain unittest only — no pytest, no network, no I/O (all functions are pure).
Covers ≥ 25 cases:

  identify_drawdown_episodes  — no episodes, single, multiple, unfinished,
                                 flat, 1-bar, invalid bars, schema keys
  attribute_drawdown          — sum≈100%, dominant, equal, zero alloc,
                                 empty positions, no returns → equal split,
                                 mixed pos/neg returns, invalid episode
  get_worst_drawdown          — empty curve, single, multiple episodes
  drawdown_summary            — empty, flat, single, multiple, avg/max,
                                 recovery_time present/absent
  protocol_drawdown_contribution_history — empty, single, multiple, count
  AST import hygiene          — no forbidden imports
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

# Ensure spa_core is importable when run directly
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import drawdown_attribution as da
from spa_core.paper_trading.drawdown_attribution import (
    attribute_drawdown,
    build_drawdown_attribution,
    content_fingerprint,
    drawdown_summary,
    get_worst_drawdown,
    identify_drawdown_episodes,
    main,
    protocol_drawdown_contribution_history,
    write_status,
)
from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
from spa_core.reporting import tear_sheet as _tear_sheet


# ─── Synthetic data helpers ───────────────────────────────────────────────────


def _curve(levels, start="2026-01-01"):
    """Build equity curve list from level values; start = ISO date string."""
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "equity": float(v)}
        for i, v in enumerate(levels)
    ]


def _date_at(start, offset):
    """ISO date string = start + offset days."""
    return (date.fromisoformat(start) + timedelta(days=offset)).isoformat()


# Synthetic 90-day equity curve with 3 drawdown episodes:
#   Episode 1: peak $110K → trough $104.5K (−5%) → recovery
#   Episode 2: new peak $111K → trough $102.12K (−8%) → recovery
#   Episode 3: new peak $112K → trough $108.64K (−3%) → recovery
def _make_90day_curve():
    """Return a synthetic 90-day equity curve with 3 drawdowns."""
    # Phase 0: rise from 100K to 110K (days 0-19, 20 bars)
    phase0 = [100_000 + i * 500 for i in range(20)]
    # Phase 1: drawdown 110K → 104.5K (days 20-25, 6 bars)
    phase1 = [110_000 - i * 916.67 for i in range(6)]
    # Phase 2: recovery + new peak 111K (days 26-35, 10 bars)
    phase2 = [104_500 + i * 650 for i in range(10)]
    # Phase 3: drawdown 111K → 102.12K (days 36-44, 9 bars)
    phase3 = [111_000 - i * 986.67 for i in range(9)]
    # Phase 4: recovery + new peak 112K (days 45-60, 16 bars)
    phase4 = [102_120 + i * 618.75 for i in range(16)]
    # Phase 5: drawdown 112K → 108.64K (days 61-65, 5 bars)
    phase5 = [112_000 - i * 672 for i in range(5)]
    # Phase 6: recovery + ending at 115K (days 66-89, 24 bars)
    phase6 = [109_328 + i * 236 for i in range(24)]
    levels = phase0 + phase1 + phase2 + phase3 + phase4 + phase5 + phase6
    return _curve(levels)


# ─── Test helpers ─────────────────────────────────────────────────────────────


def _sum_contributions(attr_dict):
    """Return the sum of all values in an attribution dict."""
    return sum(attr_dict.values())


# ─── identify_drawdown_episodes ───────────────────────────────────────────────


class TestIdentifyDrawdownEpisodes(unittest.TestCase):

    # 1. Empty list → []
    def test_empty_curve_returns_empty(self):
        self.assertEqual(identify_drawdown_episodes([]), [])

    # 2. Single bar → []
    def test_single_bar_returns_empty(self):
        result = identify_drawdown_episodes(_curve([100_000]))
        self.assertEqual(result, [])

    # 3. Two bars, equity rises → no episode
    def test_two_bars_rising_no_episode(self):
        result = identify_drawdown_episodes(_curve([100_000, 101_000]))
        self.assertEqual(result, [])

    # 4. Two bars, equity falls → unfinished episode
    def test_two_bars_falling_unfinished_episode(self):
        result = identify_drawdown_episodes(_curve([100_000, 95_000]))
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["recovery_date"])
        self.assertLess(result[0]["drawdown_pct"], 0)

    # 5. Flat equity line → no episodes
    def test_flat_line_no_episodes(self):
        result = identify_drawdown_episodes(_curve([100_000] * 30))
        self.assertEqual(result, [])

    # 6. Single complete drawdown (peak → trough → recovery)
    def test_single_complete_drawdown(self):
        levels = [100_000, 98_000, 95_000, 92_000, 97_000, 101_000]
        result = identify_drawdown_episodes(_curve(levels))
        self.assertEqual(len(result), 1)
        ep = result[0]
        self.assertIsNotNone(ep["recovery_date"])
        self.assertAlmostEqual(ep["drawdown_pct"], -8.0, places=3)
        self.assertEqual(ep["peak_equity"], 100_000.0)
        self.assertEqual(ep["trough_equity"], 92_000.0)

    # 7. Multiple complete drawdowns
    def test_multiple_complete_drawdowns(self):
        curve = _make_90day_curve()
        result = identify_drawdown_episodes(curve)
        # All 3 synthetic episodes should be recovered
        recovered = [e for e in result if e["recovery_date"] is not None]
        self.assertGreaterEqual(len(recovered), 3)

    # 8. Unfinished (ongoing) drawdown at end of series
    def test_unfinished_drawdown_no_recovery_date(self):
        # Rise then fall, never recover
        levels = [100_000, 105_000, 103_000, 101_000, 99_000, 97_000]
        result = identify_drawdown_episodes(_curve(levels))
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["recovery_date"])

    # 9. Schema keys present in every returned episode
    def test_episode_schema_keys(self):
        levels = [100_000, 90_000, 105_000]
        result = identify_drawdown_episodes(_curve(levels))
        self.assertEqual(len(result), 1)
        required = {
            "start_date", "peak_equity", "trough_date", "trough_equity",
            "recovery_date", "drawdown_pct", "duration_days",
        }
        self.assertEqual(set(result[0].keys()), required)

    # 10. drawdown_pct is always ≤ 0
    def test_drawdown_pct_is_non_positive(self):
        curve = _make_90day_curve()
        episodes = identify_drawdown_episodes(curve)
        for ep in episodes:
            self.assertLessEqual(ep["drawdown_pct"], 0.0)

    # 11. duration_days equals trough - peak date in calendar days
    def test_duration_days_correctness(self):
        levels = [100_000, 99_000, 98_000, 97_000, 100_500]
        result = identify_drawdown_episodes(_curve(levels, start="2026-03-01"))
        self.assertEqual(len(result), 1)
        ep = result[0]
        # peak day 0 (2026-03-01), trough day 3 (2026-03-04)
        self.assertEqual(ep["duration_days"], 3)

    # 12. Invalid bars (non-dict, missing date, non-positive equity) are skipped
    def test_invalid_bars_skipped(self):
        curve = [
            {"date": "2026-01-01", "equity": 100_000},
            "not a dict",                              # skip
            {"date": "bad-date", "equity": 95_000},   # skip
            {"date": "2026-01-02", "equity": -1000},  # skip (non-positive)
            {"date": "2026-01-03", "equity": 98_000},
            {"date": "2026-01-04", "equity": 102_000},
        ]
        # Only bars 0, 2-3 valid: 100K → 98K → 102K → 1 recovered episode
        result = identify_drawdown_episodes(curve)
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0]["recovery_date"])


# ─── attribute_drawdown ───────────────────────────────────────────────────────


class TestAttributeDrawdown(unittest.TestCase):

    def _simple_episode(self, start="2026-01-01", trough_offset=5):
        """Minimal episode dict for testing."""
        s = date.fromisoformat(start)
        return {
            "start_date": start,
            "peak_equity": 100_000.0,
            "trough_date": (s + timedelta(days=trough_offset)).isoformat(),
            "trough_equity": 95_000.0,
            "recovery_date": None,
            "drawdown_pct": -5.0,
            "duration_days": trough_offset,
        }

    def _daily_returns_in_window(self, start, n_days, ret_value, protocol):
        """Build {protocol: {date: ret_value}} for n_days starting at start."""
        d0 = date.fromisoformat(start)
        return {
            protocol: {
                (d0 + timedelta(days=i)).isoformat(): ret_value
                for i in range(n_days + 1)
            }
        }

    # 13. Sum of contributions ≈ 100 % (3 protocols, all negative returns)
    def test_contributions_sum_to_100(self):
        episode = self._simple_episode()
        positions = {"aave_v3": 0.40, "compound_v3": 0.35, "morpho_blue": 0.25}
        returns = {
            "aave_v3":     {"2026-01-01": -0.010, "2026-01-02": -0.008, "2026-01-03": -0.005},
            "compound_v3": {"2026-01-01": -0.007, "2026-01-02": -0.006, "2026-01-03": -0.004},
            "morpho_blue": {"2026-01-01": -0.005, "2026-01-02": -0.004, "2026-01-03": -0.003},
        }
        attr = attribute_drawdown(episode, positions, returns)
        self.assertEqual(set(attr.keys()), set(positions.keys()))
        self.assertAlmostEqual(sum(attr.values()), 100.0, places=3)

    # 14. Dominant protocol identified (high allocation + high loss)
    def test_dominant_protocol_highest_contribution(self):
        episode = self._simple_episode()
        positions = {"aave_v3": 0.60, "compound_v3": 0.10, "morpho_blue": 0.30}
        returns = {
            "aave_v3":     {"2026-01-02": -0.020, "2026-01-03": -0.015},
            "compound_v3": {"2026-01-02": -0.002, "2026-01-03": -0.001},
            "morpho_blue": {"2026-01-02": -0.003, "2026-01-03": -0.002},
        }
        attr = attribute_drawdown(episode, positions, returns)
        # aave_v3 has 60% alloc × biggest loss → highest contribution
        self.assertGreater(attr["aave_v3"], attr["compound_v3"])
        self.assertGreater(attr["aave_v3"], attr["morpho_blue"])

    # 15. Equal allocation + equal returns → equal contributions
    def test_equal_allocation_equal_returns(self):
        episode = self._simple_episode()
        positions = {"proto_a": 0.5, "proto_b": 0.5}
        ret = -0.01
        returns = {
            "proto_a": {"2026-01-02": ret, "2026-01-03": ret},
            "proto_b": {"2026-01-02": ret, "2026-01-03": ret},
        }
        attr = attribute_drawdown(episode, positions, returns)
        self.assertAlmostEqual(attr["proto_a"], 50.0, places=3)
        self.assertAlmostEqual(attr["proto_b"], 50.0, places=3)

    # 16. Zero allocation → 0.0 contribution
    def test_zero_allocation_zero_contribution(self):
        episode = self._simple_episode()
        positions = {"aave_v3": 0.70, "pendle_pt": 0.0, "compound_v3": 0.30}
        returns = {
            "aave_v3":    {"2026-01-02": -0.01},
            "pendle_pt":  {"2026-01-02": -0.05},  # big loss, but 0 allocation
            "compound_v3": {"2026-01-02": -0.01},
        }
        attr = attribute_drawdown(episode, positions, returns)
        self.assertEqual(attr["pendle_pt"], 0.0)

    # 17. Empty positions → {}
    def test_empty_positions_returns_empty(self):
        episode = self._simple_episode()
        attr = attribute_drawdown(episode, {}, {"aave_v3": {"2026-01-02": -0.01}})
        self.assertEqual(attr, {})

    # 18. No return data in episode window → equal split
    def test_no_returns_in_window_equal_split(self):
        episode = self._simple_episode(start="2026-01-01", trough_offset=5)
        positions = {"proto_a": 0.5, "proto_b": 0.5}
        # Returns are all OUTSIDE the episode window
        returns = {
            "proto_a": {"2025-12-01": -0.01},
            "proto_b": {"2025-12-01": -0.01},
        }
        attr = attribute_drawdown(episode, positions, returns)
        self.assertAlmostEqual(attr["proto_a"], 50.0, places=3)
        self.assertAlmostEqual(attr["proto_b"], 50.0, places=3)

    # 19. Mixed positive and negative returns; sum still ≈ 100 %
    def test_mixed_returns_sum_to_100(self):
        episode = self._simple_episode()
        positions = {"bad_proto": 0.5, "good_proto": 0.5}
        returns = {
            "bad_proto":  {"2026-01-02": -0.05},  # caused loss
            "good_proto": {"2026-01-02": +0.01},  # partially offset
        }
        attr = attribute_drawdown(episode, positions, returns)
        self.assertAlmostEqual(sum(attr.values()), 100.0, places=3)
        # bad_proto caused loss → positive contribution %
        self.assertGreater(attr["bad_proto"], 0)
        # good_proto offset loss → negative contribution %
        self.assertLess(attr["good_proto"], 0)

    # 20. Invalid episode (missing dates) → {}
    def test_invalid_episode_missing_dates_returns_empty(self):
        episode = {"peak_equity": 100_000}  # no start_date / trough_date
        result = attribute_drawdown(episode, {"aave_v3": 0.5}, {})
        self.assertEqual(result, {})

    # 21. Returns outside episode window are ignored
    def test_returns_outside_window_ignored(self):
        episode = {
            "start_date": "2026-02-01",
            "trough_date": "2026-02-07",
            "peak_equity": 100_000,
            "trough_equity": 95_000,
        }
        positions = {"p": 1.0}
        returns = {
            "p": {
                "2026-01-15": -0.10,   # before window
                "2026-02-03": -0.02,   # in window
                "2026-03-01": -0.10,   # after window
            }
        }
        # Only the -0.02 on 2026-02-03 should count
        attr_full = attribute_drawdown(episode, positions, returns)
        attr_only = attribute_drawdown(
            episode, positions, {"p": {"2026-02-03": -0.02}}
        )
        self.assertAlmostEqual(attr_full["p"], attr_only["p"], places=4)


# ─── get_worst_drawdown ───────────────────────────────────────────────────────


class TestGetWorstDrawdown(unittest.TestCase):

    # 22. Empty / flat curve → {}
    def test_empty_curve_returns_empty_dict(self):
        self.assertEqual(get_worst_drawdown([]), {})

    def test_flat_curve_returns_empty_dict(self):
        self.assertEqual(get_worst_drawdown(_curve([100_000] * 10)), {})

    # 23. Single drawdown is the worst
    def test_single_drawdown_is_worst(self):
        levels = [100_000, 90_000, 101_000]
        result = get_worst_drawdown(_curve(levels))
        self.assertEqual(result["peak_equity"], 100_000.0)
        self.assertEqual(result["trough_equity"], 90_000.0)
        self.assertAlmostEqual(result["drawdown_pct"], -10.0, places=3)

    # 24. Multiple episodes: correct worst returned
    def test_multiple_episodes_correct_worst(self):
        # DD1: 100K → 95K (5 %) → 105K → DD2: 105K → 96.6K (8 %) → 107K
        levels = [
            100_000, 98_000, 96_000, 95_000, 99_000, 103_000, 105_000,  # DD1
            104_000, 102_000, 100_000, 98_000, 96_600, 100_000, 107_000,  # DD2
        ]
        episodes = identify_drawdown_episodes(_curve(levels))
        worst = get_worst_drawdown(_curve(levels))
        self.assertEqual(
            worst["drawdown_pct"],
            min(e["drawdown_pct"] for e in episodes),
        )


# ─── drawdown_summary ─────────────────────────────────────────────────────────


class TestDrawdownSummary(unittest.TestCase):

    # 25. Empty curve → zeros / None
    def test_empty_curve_zero_episodes(self):
        result = drawdown_summary([])
        self.assertEqual(result["total_episodes"], 0)
        self.assertIsNone(result["max_drawdown"])
        self.assertIsNone(result["avg_drawdown"])
        self.assertIsNone(result["avg_duration"])
        self.assertIsNone(result["avg_recovery_time"])

    # 26. Flat curve → zero episodes
    def test_flat_curve_zero_episodes(self):
        result = drawdown_summary(_curve([100_000] * 20))
        self.assertEqual(result["total_episodes"], 0)

    # 27. Single episode: avg_drawdown == max_drawdown
    def test_single_episode_avg_equals_max(self):
        levels = [100_000, 90_000, 105_000]
        result = drawdown_summary(_curve(levels))
        self.assertEqual(result["total_episodes"], 1)
        self.assertAlmostEqual(result["avg_drawdown"], result["max_drawdown"], places=4)

    # 28. Multiple episodes: max_drawdown is the most negative
    def test_multiple_episodes_max_drawdown_is_worst(self):
        curve = _make_90day_curve()
        result = drawdown_summary(curve)
        self.assertGreaterEqual(result["total_episodes"], 3)
        self.assertLessEqual(result["max_drawdown"], result["avg_drawdown"])

    # 29. avg_recovery_time None when no episode recovered
    def test_no_recovered_episodes_avg_recovery_none(self):
        # Monotonically falling: 1 unfinished episode, never recovers
        levels = [100_000 - i * 1000 for i in range(20)]
        result = drawdown_summary(_curve(levels))
        self.assertIsNone(result["avg_recovery_time"])

    # 30. avg_duration is correct for a known episode
    def test_avg_duration_single_episode(self):
        # peak day0=100K, trough day3=90K, recovery day5=105K
        levels = [100_000, 96_000, 93_000, 90_000, 97_000, 105_000]
        result = drawdown_summary(_curve(levels))
        self.assertEqual(result["total_episodes"], 1)
        self.assertAlmostEqual(result["avg_duration"], 3.0, places=1)

    # 31. avg_recovery_time correct for a single known episode
    def test_avg_recovery_time_single_episode(self):
        # trough day3, recovery day5 → recovery_time = 2
        levels = [100_000, 96_000, 93_000, 90_000, 97_000, 105_000]
        result = drawdown_summary(_curve(levels))
        self.assertAlmostEqual(result["avg_recovery_time"], 2.0, places=1)


# ─── protocol_drawdown_contribution_history ────────────────────────────────────


class TestProtocolDrawdownContributionHistory(unittest.TestCase):

    # 32. Empty episodes → {}
    def test_empty_episodes_returns_empty(self):
        result = protocol_drawdown_contribution_history([], [{"a": 50.0}])
        self.assertEqual(result, {})

    # 33. Empty attribution_history → {}
    def test_empty_attribution_history_returns_empty(self):
        ep = [{"drawdown_pct": -5.0}]
        result = protocol_drawdown_contribution_history(ep, [])
        self.assertEqual(result, {})

    # 34. Single episode attribution → correct count / avg / max
    def test_single_episode_profile(self):
        ep = [{"drawdown_pct": -5.0}]
        attrs = [{"aave_v3": 70.0, "compound_v3": 30.0}]
        result = protocol_drawdown_contribution_history(ep, attrs)
        self.assertIn("aave_v3", result)
        self.assertIn("compound_v3", result)
        self.assertEqual(result["aave_v3"]["count"], 1)
        self.assertEqual(result["aave_v3"]["max_contribution_pct"], 70.0)
        self.assertAlmostEqual(result["aave_v3"]["avg_contribution_pct"], 70.0)

    # 35. Count reflects only positive contributions
    def test_count_only_positive_contributions(self):
        eps = [{"drawdown_pct": -5.0}, {"drawdown_pct": -3.0}]
        attrs = [
            {"proto_a": 80.0, "proto_b": 20.0},  # both positive
            {"proto_a": -10.0, "proto_b": 110.0}, # proto_a negative
        ]
        result = protocol_drawdown_contribution_history(eps, attrs)
        # proto_a: positive in episode 0, negative in episode 1 → count=1
        self.assertEqual(result["proto_a"]["count"], 1)
        # proto_b: positive in both → count=2
        self.assertEqual(result["proto_b"]["count"], 2)

    # 36. avg_contribution_pct averages across all appearances
    def test_avg_contribution_pct_across_episodes(self):
        eps = [{"drawdown_pct": -5.0}, {"drawdown_pct": -3.0}]
        attrs = [
            {"aave_v3": 60.0},
            {"aave_v3": 40.0},
        ]
        result = protocol_drawdown_contribution_history(eps, attrs)
        self.assertAlmostEqual(result["aave_v3"]["avg_contribution_pct"], 50.0, places=3)

    # 37. max_contribution_pct is the highest single-episode value
    def test_max_contribution_pct_is_max(self):
        eps = [{"drawdown_pct": -5.0}] * 3
        attrs = [{"p": 30.0}, {"p": 75.0}, {"p": 50.0}]
        result = protocol_drawdown_contribution_history(eps, attrs)
        self.assertAlmostEqual(result["p"]["max_contribution_pct"], 75.0, places=3)


# ─── End-to-end integration: 90-day synthetic track ─────────────────────────


class TestEndToEndSyntheticTrack(unittest.TestCase):

    def setUp(self):
        self.curve = _make_90day_curve()
        self.episodes = identify_drawdown_episodes(self.curve)
        self.positions = {
            "aave_v3":    0.40,
            "compound_v3": 0.35,
            "morpho_blue": 0.15,
            "pendle_pt":   0.10,
        }

    def _make_returns(self, episode, values):
        """Make returns_by_protocol for an episode with given per-protocol daily losses."""
        start = date.fromisoformat(episode["start_date"])
        trough = date.fromisoformat(episode["trough_date"])
        n = (trough - start).days + 1
        result = {}
        for proto, daily_ret in values.items():
            result[proto] = {
                (start + timedelta(days=i)).isoformat(): daily_ret
                for i in range(n)
            }
        return result

    # 38. At least 3 episodes found in the synthetic track
    def test_at_least_3_episodes_found(self):
        self.assertGreaterEqual(len(self.episodes), 3)

    # 39. All episodes have negative drawdown_pct
    def test_all_episodes_negative_drawdown(self):
        for ep in self.episodes:
            self.assertLess(ep["drawdown_pct"], 0.0)

    # 40. Full attribution pipeline: attribute all episodes, build history
    def test_full_attribution_pipeline(self):
        returns_config = {
            "aave_v3":    -0.003,
            "compound_v3": -0.002,
            "morpho_blue": -0.005,
            "pendle_pt":   -0.001,
        }
        attribution_history = []
        for ep in self.episodes:
            rets = self._make_returns(ep, returns_config)
            attr = attribute_drawdown(ep, self.positions, rets)
            self.assertAlmostEqual(sum(attr.values()), 100.0, places=2)
            attribution_history.append(attr)

        history = protocol_drawdown_contribution_history(
            self.episodes, attribution_history
        )
        # All protocols should appear
        for proto in self.positions:
            self.assertIn(proto, history)
            self.assertGreaterEqual(history[proto]["count"], 0)

    # 41. get_worst_drawdown matches the min episode in the full list
    def test_worst_drawdown_matches_min_episode(self):
        worst = get_worst_drawdown(self.curve)
        self.assertEqual(
            worst["drawdown_pct"],
            min(e["drawdown_pct"] for e in self.episodes),
        )

    # 42. drawdown_summary total_episodes consistent with identify_
    def test_summary_total_episodes_consistent(self):
        summary = drawdown_summary(self.curve)
        self.assertEqual(summary["total_episodes"], len(self.episodes))


# ─── AST import hygiene ───────────────────────────────────────────────────────


class TestImportHygiene(unittest.TestCase):

    _MODULE_PATH = (
        Path(__file__).resolve().parents[2]
        / "spa_core"
        / "paper_trading"
        / "drawdown_attribution.py"
    )

    _FORBIDDEN = frozenset({
        "requests", "httpx", "aiohttp", "urllib3",
        "web3", "eth_account",
        "numpy", "pandas", "scipy",
        "openai", "anthropic",
        "boto3", "google",
    })

    # 43. Module uses only stdlib — no forbidden imports
    def test_no_forbidden_imports(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in self._FORBIDDEN:
                        found.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in self._FORBIDDEN:
                        found.add(root)
        self.assertEqual(found, set(), f"Forbidden imports found: {found}")

    # 44. Module file exists and is importable
    def test_module_file_exists(self):
        self.assertTrue(self._MODULE_PATH.exists())

    # 45. All five pure functions remain exported in __all__ (additive growth)
    def test_all_exports_present(self):
        from spa_core.paper_trading import drawdown_attribution as mod
        pure = {
            "identify_drawdown_episodes",
            "attribute_drawdown",
            "get_worst_drawdown",
            "drawdown_summary",
            "protocol_drawdown_contribution_history",
        }
        self.assertTrue(pure.issubset(set(mod.__all__)))
        # build layer additively exported too
        for name in ("build_drawdown_attribution", "content_fingerprint",
                     "write_status", "main"):
            self.assertIn(name, mod.__all__)


# ──────────────────────────────────────────────────────────────────────────────
# Build-layer fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _equity_doc(bars, is_demo=False):
    """``equity_curve_daily.json``-shaped doc from list of (date, equity, positions)."""
    daily = []
    for d, eq, pos in bars:
        bar = {"date": d, "close_equity": float(eq), "equity": float(eq)}
        if pos is not None:
            bar["positions"] = pos
        daily.append(bar)
    return {"is_demo": is_demo, "source": "test", "daily": daily}


def _drawdown_data_dir(dominance="fail"):
    """Create a temp data dir with a real single-protocol drawdown.

    ``dominance`` ∈ {"fail","warn","ok"} tunes how concentrated the loss is.
    Returns the dir path (caller owns cleanup via TemporaryDirectory).
    """
    if dominance == "fail":
        # aave collapses, comp flat → ~100% attribution
        bars = [
            ("2026-01-01", 100000, {"aave": 50000, "comp": 50000}),
            ("2026-01-02", 90000, {"aave": 40000, "comp": 50000}),
            ("2026-01-03", 95000, {"aave": 45000, "comp": 50000}),
            ("2026-01-04", 101000, {"aave": 51000, "comp": 50000}),
        ]
        positions = {"aave": 51000, "comp": 50000}
    elif dominance == "warn":
        # aave drops a lot, comp drops a little → ~60-70%
        bars = [
            ("2026-01-01", 100000, {"aave": 50000, "comp": 50000}),
            ("2026-01-02", 88000, {"aave": 41000, "comp": 47000}),
            ("2026-01-03", 95000, {"aave": 46000, "comp": 49000}),
            ("2026-01-04", 102000, {"aave": 52000, "comp": 50000}),
        ]
        positions = {"aave": 52000, "comp": 50000}
    else:  # ok — perfectly balanced loss (equal weights, equal drop)
        bars = [
            ("2026-01-01", 100000, {"aave": 50000, "comp": 50000}),
            ("2026-01-02", 90000, {"aave": 45000, "comp": 45000}),
            ("2026-01-03", 95000, {"aave": 47500, "comp": 47500}),
            ("2026-01-04", 101000, {"aave": 50500, "comp": 50500}),
        ]
        positions = {"aave": 50000, "comp": 50000}
    d = tempfile.mkdtemp(prefix="dd_attr_test_")
    _write_json(os.path.join(d, "equity_curve_daily.json"), _equity_doc(bars))
    _write_json(
        os.path.join(d, "current_positions.json"),
        {"capital_usd": 100000, "positions": positions},
    )
    return d


# ──────────────────────────────────────────────────────────────────────────────
# build_drawdown_attribution
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildDrawdownAttribution(unittest.TestCase):

    # 46. Missing data dir → available:false insufficient_data, never raises
    def test_missing_files_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            r = build_drawdown_attribution(d)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        self.assertIn("verdict", r)
        self.assertIn("verdict_reason", r)
        self.assertIn("meta", r)

    # 47. Rising-only track → no_episodes, schema stable
    def test_no_episodes_rising_track(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [
                ("2026-01-01", 100000, {"aave": 100000}),
                ("2026-01-02", 101000, {"aave": 101000}),
                ("2026-01-03", 102000, {"aave": 102000}),
            ]
            _write_json(os.path.join(d, "equity_curve_daily.json"),
                        _equity_doc(bars))
            r = build_drawdown_attribution(d)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "no_episodes")
        self.assertEqual(r["headline"]["num_episodes"], 0)
        self.assertEqual(r["per_protocol_contribution_history"], {})

    # 48. Single-protocol collapse → fail verdict
    def test_fail_single_protocol_dominance(self):
        d = _drawdown_data_dir("fail")
        try:
            r = build_drawdown_attribution(d)
        finally:
            _rmtree(d)
        self.assertTrue(r["available"])
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["headline"]["worst_contributor"], "aave")
        self.assertGreaterEqual(r["headline"]["worst_contributor_pct"],
                                da.FAIL_DOMINANCE_PCT)

    # 49. Warn-band dominance → warn verdict (50 < x < 75)
    def test_warn_dominance(self):
        d = _drawdown_data_dir("warn")
        try:
            r = build_drawdown_attribution(d)
        finally:
            _rmtree(d)
        self.assertTrue(r["available"])
        pct = r["headline"]["worst_contributor_pct"]
        self.assertGreater(pct, da.WARN_DOMINANCE_PCT)
        # depending on exact numbers may cross into fail; assert verdict matches band
        if pct >= da.FAIL_DOMINANCE_PCT:
            self.assertEqual(r["verdict"], "fail")
        else:
            self.assertEqual(r["verdict"], "warn")

    # 50. Balanced loss → ok verdict
    def test_ok_balanced(self):
        d = _drawdown_data_dir("ok")
        try:
            r = build_drawdown_attribution(d)
        finally:
            _rmtree(d)
        self.assertTrue(r["available"])
        self.assertLessEqual(r["headline"]["worst_contributor_pct"],
                             da.WARN_DOMINANCE_PCT)
        self.assertEqual(r["verdict"], "ok")

    # 51. is_demo honestly propagated from source
    def test_is_demo_propagated(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [
                ("2026-01-01", 100000, {"aave": 100000}),
                ("2026-01-02", 90000, {"aave": 90000}),
                ("2026-01-03", 101000, {"aave": 101000}),
            ]
            doc = _equity_doc(bars, is_demo=True)
            _write_json(os.path.join(d, "equity_curve_daily.json"), doc)
            _write_json(os.path.join(d, "current_positions.json"),
                        {"capital_usd": 100000, "positions": {"aave": 101000}})
            r = build_drawdown_attribution(d)
        self.assertEqual(r["meta"]["is_demo"], True)

    # 52. Verdict + verdict_reason ALWAYS present (available or not)
    def test_verdict_always_present(self):
        with tempfile.TemporaryDirectory() as d:
            r = build_drawdown_attribution(d)
        self.assertIn(r["verdict"], {"ok", "warn", "fail"})
        self.assertIsInstance(r["verdict_reason"], str)
        self.assertTrue(r["verdict_reason"])

    # 53. Broken equity JSON → never raises → unavailable
    def test_broken_equity_json(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "equity_curve_daily.json"), "w") as fh:
                fh.write("{ not json ::::")
            r = build_drawdown_attribution(d)
        self.assertFalse(r["available"])

    # 54. Non-dict equity root → never raises
    def test_garbage_equity_root(self):
        with tempfile.TemporaryDirectory() as d:
            _write_json(os.path.join(d, "equity_curve_daily.json"), [1, 2, 3])
            r = build_drawdown_attribution(d)
        self.assertFalse(r["available"])

    # 55. Drawdown present but no positions block → insufficient_data
    def test_drawdown_no_positions(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [
                ("2026-01-01", 100000, None),
                ("2026-01-02", 90000, None),
                ("2026-01-03", 101000, None),
            ]
            _write_json(os.path.join(d, "equity_curve_daily.json"),
                        _equity_doc(bars))
            r = build_drawdown_attribution(d)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")

    # 56. Tolerance subTest: assorted garbage never raises
    def test_never_raises_garbage_inputs(self):
        cases = [
            None, "string", 12345, [], {}, [1, 2], {"daily": "x"},
            {"daily": [1, 2, 3]}, {"daily": [{"no_date": True}]},
        ]
        for c in cases:
            with self.subTest(case=repr(c)[:40]):
                with tempfile.TemporaryDirectory() as d:
                    _write_json(os.path.join(d, "equity_curve_daily.json"), c)
                    try:
                        r = build_drawdown_attribution(d)
                    except Exception as exc:
                        self.fail(f"build raised on {c!r}: {exc}")
                    self.assertIn("available", r)
                    self.assertIn("verdict", r)


# ──────────────────────────────────────────────────────────────────────────────
# content_fingerprint — reuse-by-import from tear_sheet
# ──────────────────────────────────────────────────────────────────────────────


class TestContentFingerprint(unittest.TestCase):

    # 57. SAME object as tear_sheet.content_fingerprint
    def test_fingerprint_is_tear_sheet_object(self):
        self.assertIs(content_fingerprint, _tear_sheet.content_fingerprint)
        self.assertIs(da.content_fingerprint, _tear_sheet.content_fingerprint)

    # 58. generated_at ignored
    def test_fingerprint_ignores_generated_at(self):
        a = {"x": 1, "meta": {"generated_at": "T1", "source": "s"}}
        b = {"x": 1, "meta": {"generated_at": "T2", "source": "s"}}
        self.assertEqual(content_fingerprint(a), content_fingerprint(b))

    # 59. history ignored
    def test_fingerprint_ignores_history(self):
        a = {"x": 1, "history": [1, 2, 3]}
        b = {"x": 1, "history": []}
        self.assertEqual(content_fingerprint(a), content_fingerprint(b))

    # 60. content change → fingerprint changes
    def test_fingerprint_content_sensitive(self):
        a = {"x": 1, "meta": {"source": "s"}}
        b = {"x": 2, "meta": {"source": "s"}}
        self.assertNotEqual(content_fingerprint(a), content_fingerprint(b))

    # 61. non-dict input → sentinel, never raises
    def test_fingerprint_non_dict(self):
        self.assertIsInstance(content_fingerprint(None), str)
        self.assertIsInstance(content_fingerprint([1, 2]), str)


# ──────────────────────────────────────────────────────────────────────────────
# write_status — atomic persistence + idempotency + rotation
# ──────────────────────────────────────────────────────────────────────────────


class TestWriteStatus(unittest.TestCase):

    def _build(self, d):
        return build_drawdown_attribution(d)

    # 62. First write → DATA_WRITTEN, file exists, no *.tmp left
    def test_first_write(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(d)
            status = write_status(r, d)
            self.assertEqual(status, "DATA_WRITTEN")
            self.assertTrue(os.path.exists(
                os.path.join(d, "drawdown_attribution.json")))
            self.assertEqual(
                [f for f in os.listdir(d) if ".tmp" in f], [])

    # 63. Second write same content → DATA_UNCHANGED, byte-identical
    def test_idempotent_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(d)
            write_status(r, d)
            out = os.path.join(d, "drawdown_attribution.json")
            md5_1 = hashlib.md5(open(out, "rb").read()).hexdigest()
            status2 = write_status(r, d)
            md5_2 = hashlib.md5(open(out, "rb").read()).hexdigest()
            self.assertEqual(status2, "DATA_UNCHANGED")
            self.assertEqual(md5_1, md5_2)

    # 64. Changed content → history grows by exactly 1
    def test_history_grows(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = self._build(d)
            write_status(r1, d)
            r2 = dict(r1)
            r2["notes"] = ["changed marker"]
            write_status(r2, d)
            doc = json.loads(open(
                os.path.join(d, "drawdown_attribution.json")).read())
            self.assertEqual(len(doc["history"]), 1)

    # 65. History rotation caps at exactly HISTORY_MAX
    def test_history_rotation_cap(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._build(d)
            for i in range(da.HISTORY_MAX + 25):
                r = dict(base)
                r["notes"] = [f"marker-{i}"]
                write_status(r, d)
            doc = json.loads(open(
                os.path.join(d, "drawdown_attribution.json")).read())
            self.assertEqual(len(doc["history"]), da.HISTORY_MAX)

    # 66. Tolerant of a broken previous artifact (treats as fresh)
    def test_tolerant_broken_previous(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "drawdown_attribution.json")
            with open(out, "w") as fh:
                fh.write("{ broken")
            r = self._build(d)
            try:
                status = write_status(r, d)
            except Exception as exc:
                self.fail(f"write_status raised on broken prev: {exc}")
            self.assertEqual(status, "DATA_WRITTEN")

    # 67. No leftover .tmp files after many writes
    def test_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._build(d)
            for i in range(5):
                r = dict(base)
                r["notes"] = [f"m{i}"]
                write_status(r, d)
            leftovers = [f for f in os.listdir(d) if ".tmp" in f]
            self.assertEqual(leftovers, [])

    # 68. _fingerprint field embedded in written doc
    def test_fingerprint_field_written(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(d)
            write_status(r, d)
            doc = json.loads(open(
                os.path.join(d, "drawdown_attribution.json")).read())
            self.assertIsInstance(doc["_fingerprint"], str)
            self.assertEqual(doc["_fingerprint"], content_fingerprint(r))


# ──────────────────────────────────────────────────────────────────────────────
# CLI — main(argv) direct + subprocess
# ──────────────────────────────────────────────────────────────────────────────


class TestCLIDirect(unittest.TestCase):

    # 69. --check default: returns 0, no write
    def test_check_no_write(self):
        d = _drawdown_data_dir("fail")
        try:
            rc = main(["--check", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(
                os.path.join(d, "drawdown_attribution.json")))
        finally:
            _rmtree(d)

    # 70. default (no flag) = check, no write
    def test_default_is_check(self):
        d = _drawdown_data_dir("fail")
        try:
            rc = main(["--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(
                os.path.join(d, "drawdown_attribution.json")))
        finally:
            _rmtree(d)

    # 71. --run writes the artifact
    def test_run_writes(self):
        d = _drawdown_data_dir("fail")
        try:
            rc = main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(
                os.path.join(d, "drawdown_attribution.json")))
        finally:
            _rmtree(d)

    # 72. --run twice idempotent (no *.tmp, file stable)
    def test_run_idempotent(self):
        d = _drawdown_data_dir("fail")
        try:
            main(["--run", "--data-dir", d])
            out = os.path.join(d, "drawdown_attribution.json")
            md5_1 = hashlib.md5(open(out, "rb").read()).hexdigest()
            main(["--run", "--data-dir", d])
            md5_2 = hashlib.md5(open(out, "rb").read()).hexdigest()
            self.assertEqual(md5_1, md5_2)
            self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [])
        finally:
            _rmtree(d)

    # 73. junk arg → rc 0 (no raise)
    def test_junk_arg_exit_zero(self):
        self.assertEqual(main(["--nonsense-flag"]), 0)

    # 74. --check + --run conflict → rc 0 (no raise)
    def test_conflict_exit_zero(self):
        self.assertEqual(main(["--check", "--run"]), 0)


class TestCLISubprocess(unittest.TestCase):

    _MOD = "spa_core.paper_trading.drawdown_attribution"

    def _run(self, args, data_dir):
        full = [sys.executable, "-m", self._MOD] + args + ["--data-dir", data_dir]
        return subprocess.run(
            full, cwd=str(_REPO_ROOT), capture_output=True, text=True
        )

    # 75. --check via subprocess: exit 0, no write
    def test_subprocess_check(self):
        d = _drawdown_data_dir("fail")
        try:
            res = self._run(["--check"], d)
            self.assertEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(
                os.path.join(d, "drawdown_attribution.json")))
            self.assertNotIn("Traceback", res.stderr)
        finally:
            _rmtree(d)

    # 76. --run via subprocess writes, then DATA_UNCHANGED on rerun
    def test_subprocess_run_idempotent(self):
        d = _drawdown_data_dir("fail")
        try:
            r1 = self._run(["--run"], d)
            self.assertEqual(r1.returncode, 0)
            self.assertIn("DATA_WRITTEN", r1.stdout)
            r2 = self._run(["--run"], d)
            self.assertEqual(r2.returncode, 0)
            self.assertIn("DATA_UNCHANGED", r2.stdout)
        finally:
            _rmtree(d)

    # 77. junk arg via subprocess → exit 0, ERROR, no Traceback
    def test_subprocess_junk(self):
        d = _drawdown_data_dir("fail")
        try:
            res = self._run(["--garbage-xyz"], d)
            self.assertEqual(res.returncode, 0)
            self.assertNotIn("Traceback", res.stderr)
            self.assertIn("ERROR", res.stderr)
        finally:
            _rmtree(d)

    # 78. conflict via subprocess → exit 0, no Traceback
    def test_subprocess_conflict(self):
        d = _drawdown_data_dir("fail")
        try:
            res = self._run(["--check", "--run"], d)
            self.assertEqual(res.returncode, 0)
            self.assertNotIn("Traceback", res.stderr)
        finally:
            _rmtree(d)


# ──────────────────────────────────────────────────────────────────────────────
# Import hygiene via REAL linter + module-source checks
# ──────────────────────────────────────────────────────────────────────────────


class TestRealLinterHygiene(unittest.TestCase):

    _MODULE_PATH = (
        Path(__file__).resolve().parents[2]
        / "spa_core" / "paper_trading" / "drawdown_attribution.py"
    )
    _TEST_PATH = Path(__file__).resolve()

    # 79. REAL find_forbidden_imports → 0 violations in module
    def test_real_linter_zero_violations(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        violations = find_forbidden_imports(src, str(self._MODULE_PATH))
        self.assertEqual(list(violations), [])

    # 80. py_compile both files cleanly
    def test_py_compile_both(self):
        import py_compile
        for p in (self._MODULE_PATH, self._TEST_PATH):
            try:
                py_compile.compile(str(p), doraise=True)
            except py_compile.PyCompileError as exc:
                self.fail(f"py_compile failed for {p}: {exc}")

    # 81. No network/LLM/socket/subprocess/eval/exec/pip patterns in MODULE CODE
    def test_no_dangerous_patterns(self):
        # Strip the module docstring (which legitimately MENTIONS web3/requests
        # in its safety prose) so we test actual code, not documentation.
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        doc = ast.get_docstring(tree) or ""
        code = src.replace(doc, "")
        for pat in ("import socket", "import requests", "urllib.request",
                    "import anthropic", "import openai", "import subprocess",
                    "eval(", "exec(", "pip install", "import web3",
                    "from web3"):
            with self.subTest(pattern=pat):
                self.assertNotIn(pat, code)

    # 82. reuse-by-import marker: imports drawdown_analytics + tear_sheet
    def test_reuse_by_import_marker(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("from spa_core.paper_trading.drawdown_analytics import", src)
        self.assertIn("from spa_core.reporting.tear_sheet import", src)
        self.assertIn("content_fingerprint", src)

    # 83. atomic-write pattern present (tempfile.mkstemp + os.replace or atomic_save)
    def test_atomic_write_pattern(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        uses_atomic_save = "atomic_save" in src
        uses_raw_atomic = "tempfile.mkstemp" in src and "os.replace" in src
        self.assertTrue(
            uses_atomic_save or uses_raw_atomic,
            "Module must use atomic_save() or the raw tempfile.mkstemp+os.replace pattern",
        )

    # 84. e2e round-trip: build → write → reload → matches fingerprint
    def test_e2e_round_trip(self):
        d = _drawdown_data_dir("fail")
        try:
            r = build_drawdown_attribution(d)
            write_status(r, d)
            doc = json.loads(open(
                os.path.join(d, "drawdown_attribution.json")).read())
            self.assertEqual(doc["_fingerprint"], content_fingerprint(r))
            self.assertEqual(doc["verdict"], r["verdict"])
            self.assertTrue(doc["available"])
        finally:
            _rmtree(d)


def _rmtree(path):
    """Best-effort recursive delete (test teardown helper)."""
    import shutil
    try:
        shutil.rmtree(path)
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
