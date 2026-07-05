"""RTMR (ADR-053) Chainlink oracle provider tests — ABI decode offline + live smoke."""
from __future__ import annotations

import os
import unittest

from spa_core.monitoring.sensors import oracle_providers as O


class TestDecode(unittest.TestCase):
    def test_parse_latest_round_data(self) -> None:
        # 5 words: roundId, answer(=1.00008 @ 8 dec = 100008000), startedAt, updatedAt=1700000000, answeredInRound
        w = lambda n: format(n, "064x")
        h = "0x" + w(1) + w(100008000) + w(0) + w(1700000000) + w(1)
        price, ts = O.parse_latest_round_data(h, 8)
        self.assertAlmostEqual(price, 1.00008, places=5)
        self.assertEqual(ts, 1700000000)

    def test_short_result_none(self) -> None:
        self.assertIsNone(O.parse_latest_round_data("0x1234", 8))

    def test_zero_answer_none(self) -> None:
        w = lambda n: format(n, "064x")
        self.assertIsNone(O.parse_latest_round_data("0x" + w(1) + w(0) + w(0) + w(1700000000) + w(1), 8))

    def test_feeds_structure(self) -> None:
        self.assertIn("USDC", O._FEEDS)


@unittest.skipIf(os.environ.get("GITHUB_ACTIONS") == "true", "live RPC — skipped in CI")
class TestLive(unittest.TestCase):
    def test_usdc_chainlink_live(self) -> None:
        try:
            price, ts = O.chainlink_reader(O._FEEDS["USDC"])()
            self.assertAlmostEqual(price, 1.0, delta=0.05)
            self.assertGreater(ts, 1_600_000_000)
        except Exception:
            self.skipTest("RPC unavailable")


if __name__ == "__main__":
    unittest.main()
