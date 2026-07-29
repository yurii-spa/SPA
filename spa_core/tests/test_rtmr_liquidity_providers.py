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

    def test_empty_holdings_yield_empty_depth(self) -> None:
        """Incident 2026-07: all-cash portfolio → held={} → `{} or _SLUGS` resurrected all 7
        default scopes with no sizes → 7 permanent critical 'unknown position size' signals →
        portfolio could never leave DEFENSIVE. Holding nothing must mean NO liquidity scopes."""
        self.assertEqual(L.depth_providers({}), {})

    def test_none_still_defaults_to_slugs(self) -> None:
        provs = L.depth_providers(None)
        self.assertGreaterEqual(len(provs), 5)  # explicit None keeps the default watchlist


if __name__ == "__main__":
    unittest.main()
