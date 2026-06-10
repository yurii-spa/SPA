"""Tests for the SPA-V412 exit-latency profiles + liquidity policy.

Covers:
  * every adapter declares an ``EXIT_LATENCY_HOURS`` class constant and
    surfaces it on ``get_yield_info().exit_latency_hours`` (no live network —
    only the static metadata path is exercised),
  * ``spa_core/adapters/exit_latency_policy.py`` — the read-only liquidity
    policy check and the kill-switch exit ordering.

Run:  python3 -m unittest spa_core.tests.test_exit_latency -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.adapters.compound_v3 import CompoundV3Adapter
from spa_core.adapters.maple import MapleAdapter
from spa_core.adapters.morpho_blue import MorphoBlueAdapter
from spa_core.adapters.euler_v2 import EulerV2Adapter
from spa_core.adapters.yearn_v3 import YearnV3Adapter
from spa_core.adapters.exit_latency_policy import (
    ILLIQUID_THRESHOLD_HOURS,
    MAX_ILLIQUID_SHARE,
    classify_exit_latency,
    check_exit_latency_policy,
    kill_switch_exit_order,
)

ALL_ADAPTERS = [
    AaveV3Adapter,
    CompoundV3Adapter,
    MapleAdapter,
    MorphoBlueAdapter,
    EulerV2Adapter,
    YearnV3Adapter,
]


class TestYieldInfoField(unittest.TestCase):
    def test_field_defaults_to_none(self):
        # Strictly additive: omitting exit_latency_hours must still work.
        yi = YieldInfo(
            protocol="x", asset="USDC", apy=0.05, tvl_usd=1.0,
            tier="T1", risk_score=0.2,
        )
        self.assertIsNone(yi.exit_latency_hours)

    def test_field_accepts_value(self):
        yi = YieldInfo(
            protocol="x", asset="USDC", apy=0.05, tvl_usd=1.0,
            tier="T1", risk_score=0.2, exit_latency_hours=0.0,
        )
        self.assertEqual(yi.exit_latency_hours, 0.0)


class TestAdapterDeclareExitProfile(unittest.TestCase):
    def test_every_adapter_declares_a_numeric_profile(self):
        for cls in ALL_ADAPTERS:
            with self.subTest(adapter=cls.__name__):
                self.assertTrue(hasattr(cls, "EXIT_LATENCY_HOURS"))
                val = cls.EXIT_LATENCY_HOURS
                self.assertIsInstance(val, (int, float))
                self.assertGreaterEqual(val, 0.0)

    def test_get_yield_info_surfaces_exit_latency(self):
        # Exercise the static metadata path with the live feed mocked out:
        # get_yield_info() builds YieldInfo from fetch(); exit_latency_hours is
        # pure class metadata so it is always present regardless of feed state.
        for cls in ALL_ADAPTERS:
            with self.subTest(adapter=cls.__name__):
                adapter = cls()
                with mock.patch.object(
                    adapter, "fetch", return_value={"apy": None, "tvl": None}
                ):
                    yi = adapter.get_yield_info()
                self.assertEqual(yi.exit_latency_hours, cls.EXIT_LATENCY_HOURS)

    def test_liquid_anchors_are_instant(self):
        for cls in (AaveV3Adapter, CompoundV3Adapter, MorphoBlueAdapter, EulerV2Adapter):
            with self.subTest(adapter=cls.__name__):
                self.assertEqual(cls.EXIT_LATENCY_HOURS, 0.0)

    def test_yearn_under_threshold(self):
        self.assertLess(YearnV3Adapter.EXIT_LATENCY_HOURS, ILLIQUID_THRESHOLD_HOURS)

    def test_maple_is_illiquid(self):
        self.assertGreater(MapleAdapter.EXIT_LATENCY_HOURS, ILLIQUID_THRESHOLD_HOURS)


class TestClassify(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(classify_exit_latency(0.0), "instant")
        self.assertEqual(classify_exit_latency(1.0), "liquid")
        self.assertEqual(classify_exit_latency(72.0), "liquid")
        self.assertEqual(classify_exit_latency(72.1), "illiquid")
        self.assertEqual(classify_exit_latency(None), "unknown")


class TestPolicyCheck(unittest.TestCase):
    def test_all_liquid_passes(self):
        positions = {
            "aave_v3": {"weight": 0.5, "exit_latency_hours": 0.0},
            "yearn_v3": {"weight": 0.5, "exit_latency_hours": 1.0},
        }
        rep = check_exit_latency_policy(positions)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["illiquid_share"], 0.0)
        self.assertEqual(rep["illiquid_positions"], [])

    def test_illiquid_over_cap_fails(self):
        positions = {
            "aave_v3": {"weight": 0.7, "exit_latency_hours": 0.0},
            "maple": {"weight": 0.3, "exit_latency_hours": 336.0},
        }
        rep = check_exit_latency_policy(positions)
        self.assertFalse(rep["ok"])
        self.assertAlmostEqual(rep["illiquid_share"], 0.3)
        self.assertIn("maple", rep["illiquid_positions"])

    def test_illiquid_exactly_at_cap_passes(self):
        positions = {
            "aave_v3": {"weight": 0.75, "exit_latency_hours": 0.0},
            "maple": {"weight": 0.25, "exit_latency_hours": 336.0},
        }
        rep = check_exit_latency_policy(positions)
        self.assertTrue(rep["ok"])
        self.assertAlmostEqual(rep["illiquid_share"], MAX_ILLIQUID_SHARE)

    def test_unknown_latency_counts_as_illiquid(self):
        positions = {
            "mystery": {"weight": 0.4, "exit_latency_hours": None},
            "aave_v3": {"weight": 0.6, "exit_latency_hours": 0.0},
        }
        rep = check_exit_latency_policy(positions)
        self.assertFalse(rep["ok"])
        self.assertIn("mystery", rep["illiquid_positions"])
        self.assertEqual(rep["breakdown"]["mystery"]["bucket"], "unknown")

    def test_sequence_input_shape(self):
        positions = [
            ("aave_v3", 0.8, 0.0),
            ("maple", 0.2, 336.0),
        ]
        rep = check_exit_latency_policy(positions)
        self.assertTrue(rep["ok"])
        self.assertAlmostEqual(rep["illiquid_share"], 0.2)

    def test_does_not_mutate_input(self):
        positions = {"aave_v3": {"weight": 0.5, "exit_latency_hours": 0.0}}
        snapshot = {"aave_v3": {"weight": 0.5, "exit_latency_hours": 0.0}}
        check_exit_latency_policy(positions)
        self.assertEqual(positions, snapshot)


class TestKillSwitchOrder(unittest.TestCase):
    def test_liquid_first(self):
        positions = {
            "maple": {"weight": 0.2, "exit_latency_hours": 336.0},
            "aave_v3": {"weight": 0.3, "exit_latency_hours": 0.0},
            "yearn_v3": {"weight": 0.5, "exit_latency_hours": 1.0},
        }
        order = kill_switch_exit_order(positions)
        self.assertEqual(order[0], "aave_v3")  # 0h, biggest? no — instant first
        self.assertEqual(order[-1], "maple")   # slowest exits last

    def test_tie_broken_by_weight(self):
        positions = [
            ("a", 0.2, 0.0),
            ("b", 0.5, 0.0),
        ]
        # equal latency -> larger weight drains first
        self.assertEqual(kill_switch_exit_order(positions), ["b", "a"])

    def test_unknown_sorts_last(self):
        positions = [
            ("mystery", 0.9, None),
            ("aave_v3", 0.1, 0.0),
        ]
        self.assertEqual(kill_switch_exit_order(positions), ["aave_v3", "mystery"])


if __name__ == "__main__":
    unittest.main()
