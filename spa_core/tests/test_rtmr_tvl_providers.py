"""RTMR (ADR-053) TVL provider tests — parsers offline + live smoke."""
from __future__ import annotations

import os
import unittest

from spa_core.monitoring.sensors import tvl_providers as T


class TestParsers(unittest.TestCase):
    def test_tvl_simple(self) -> None:
        self.assertEqual(T.parse_tvl_simple(1.28e10), 1.28e10)

    def test_tvl_simple_bad(self) -> None:
        self.assertIsNone(T.parse_tvl_simple("nope"))

    def test_protocol_current_from_chaintvls(self) -> None:
        self.assertEqual(T.parse_protocol_current({"currentChainTvls": {"Ethereum": 100.0, "Base": 50.0}}), 150.0)

    def test_protocol_current_excludes_borrowed(self) -> None:
        # keys with '-' (e.g. 'Ethereum-borrowed') are excluded
        self.assertEqual(T.parse_protocol_current({"currentChainTvls": {"Ethereum": 100.0, "Ethereum-borrowed": 30.0}}), 100.0)

    def test_history_24h_ago(self) -> None:
        payload = {"tvl": [{"totalLiquidityUSD": 90.0}, {"totalLiquidityUSD": 100.0}]}
        self.assertEqual(T.parse_history_24h_ago(payload), 90.0)  # previous daily point

    def test_current_providers_structure(self) -> None:
        provs = T.tvl_current_providers("aave-v3")
        self.assertIn("defillama_tvl", provs)
        self.assertTrue(all(callable(v) for v in provs.values()))


@unittest.skipIf(os.environ.get("GITHUB_ACTIONS") == "true", "live network — skipped in CI")
class TestLive(unittest.TestCase):
    def test_aave_tvl_live(self) -> None:
        from spa_core.monitoring.sensors import _multisource as M
        r = M.quorum_from(T.tvl_current_providers("aave-v3"), min_quorum=1, max_spread=0.05)
        if r.ok:
            self.assertGreater(r.value, 1e9)  # Aave V3 TVL is billions


if __name__ == "__main__":
    unittest.main()
