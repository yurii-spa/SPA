"""RTMR (ADR-053) keyless price provider tests — parsers (offline) + structure + live smoke."""
from __future__ import annotations

import os
import unittest

from spa_core.monitoring.sensors import providers as PR


class TestParsers(unittest.TestCase):
    def test_coingecko(self) -> None:
        self.assertEqual(PR.parse_coingecko({"usd-coin": {"usd": 1.001}}, "usd-coin"), 1.001)

    def test_coingecko_missing_none(self) -> None:
        self.assertIsNone(PR.parse_coingecko({}, "usd-coin"))

    def test_coinbase(self) -> None:
        self.assertEqual(PR.parse_coinbase({"data": {"amount": "0.999"}}), 0.999)

    def test_binance(self) -> None:
        self.assertEqual(PR.parse_binance({"price": "1.0002"}), 1.0002)

    def test_kraken(self) -> None:
        self.assertEqual(PR.parse_kraken({"result": {"USDCUSD": {"c": ["1.0001", "100"]}}}), 1.0001)

    def test_llama(self) -> None:
        self.assertEqual(PR.parse_llama({"coins": {"coingecko:dai": {"price": 0.998}}}, "dai"), 0.998)

    def test_bad_payloads_return_none(self) -> None:
        self.assertIsNone(PR.parse_coinbase({"nope": 1}))
        self.assertIsNone(PR.parse_kraken({"result": {}}))


class TestStructure(unittest.TestCase):
    def test_usdc_has_five_sources(self) -> None:
        provs = PR.price_providers_for("USDC")
        self.assertGreaterEqual(len(provs), 5)  # coingecko+defillama+coinbase+binance+kraken
        for fn in provs.values():
            self.assertTrue(callable(fn))

    def test_unknown_asset_empty(self) -> None:
        self.assertEqual(PR.price_providers_for("NOTACOIN"), {})

    def test_supported_assets(self) -> None:
        self.assertIn("USDC", PR.supported_assets())


@unittest.skipIf(os.environ.get("GITHUB_ACTIONS") == "true", "live network — skipped in CI")
class TestLiveSmoke(unittest.TestCase):
    def test_usdc_quorum_live(self) -> None:
        from spa_core.monitoring.sensors import _multisource as M
        r = M.quorum_from(PR.price_providers_for("USDC"), min_quorum=3, max_spread=0.02)
        # USDC should be ~$1 across sources; if network flakes, at worst quorum fails (fail-closed) — that's OK
        if r.ok:
            self.assertAlmostEqual(r.value, 1.0, delta=0.03)


if __name__ == "__main__":
    unittest.main()
