"""RTMR (ADR-053) liquidity provider tests — position sizing + wiring."""
from __future__ import annotations

import unittest

from spa_core.monitoring.sensors import liquidity_providers as L


class TestLiquidityProviders(unittest.TestCase):
    def test_depth_providers_structure(self) -> None:
        provs = L.depth_providers({"aave_v3": "aave-v3"})
        self.assertIn("aave_v3", provs)
        self.assertTrue(all(callable(f) for f in provs["aave_v3"].values()))

    def test_position_sizes_returns_dict(self) -> None:
        self.assertIsInstance(L.position_sizes(), dict)

    def test_liquidity_inputs_aligned(self) -> None:
        depth, sizes = L.liquidity_inputs()
        # every depth-scope must have a position size (sensor requires both)
        self.assertEqual(set(depth.keys()), set(sizes.keys()))


if __name__ == "__main__":
    unittest.main()
