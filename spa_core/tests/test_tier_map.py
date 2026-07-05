"""Tests for the canonical protocol→tier resolver (spa_core/adapters/tier_map.py).

Locks in the registry-hygiene contract: tiers come from ADAPTER_REGISTRY + an explicit
alias table, DeFiLlama slugs and variant keys resolve, and genuine unknowns return None
(NEVER a silent "T2" guess).
"""
from __future__ import annotations

import unittest

from spa_core.adapters.tier_map import (
    VALID_TIERS,
    canonical_name,
    tier_of,
    unknown_protocols,
)


class TestTierOf(unittest.TestCase):
    def test_registry_protocol_resolves(self) -> None:
        self.assertEqual(tier_of("aave_v3"), "T1")

    def test_t3_advisory_resolves(self) -> None:
        self.assertEqual(tier_of("susde"), "T3")

    def test_defillama_hyphen_slug_resolves(self) -> None:
        self.assertEqual(tier_of("aave-v3-arbitrum"), "T1")
        self.assertEqual(tier_of("morpho-blue-steakhouse"), "T1")
        self.assertEqual(tier_of("pendle-pt"), "T2")

    def test_variant_keys_resolve(self) -> None:
        self.assertEqual(tier_of("morpho_steakhouse"), "T1")
        self.assertEqual(tier_of("ondo_usdy"), "T2")
        self.assertEqual(tier_of("aerodrome_usdc_lp"), "T2")
        self.assertEqual(tier_of("aave_v3_wsteth"), "T2")

    def test_yt_leg_is_t3(self) -> None:
        self.assertEqual(tier_of("pendle_yt_susde"), "T3")

    def test_case_insensitive(self) -> None:
        self.assertEqual(tier_of("AAVE_V3"), "T1")
        self.assertEqual(tier_of("  Morpho_Steakhouse  "), "T1")

    def test_unknown_returns_none_not_t2(self) -> None:
        # The whole point: an unclassified protocol must NOT silently become T2.
        self.assertIsNone(tier_of("totally_made_up_protocol_xyz"))
        self.assertIsNone(tier_of(""))

    def test_all_results_are_valid_or_none(self) -> None:
        for name in ("aave_v3", "susde", "ondo_usdy", "garbage"):
            t = tier_of(name)
            self.assertTrue(t is None or t in VALID_TIERS)


class TestCanonicalName(unittest.TestCase):
    def test_slug_maps_to_canonical(self) -> None:
        self.assertEqual(canonical_name("aave-v3-arbitrum"), "aave_arbitrum")
        self.assertEqual(canonical_name("morpho-blue-steakhouse"), "morpho_steakhouse")

    def test_unknown_returns_normalised_input(self) -> None:
        self.assertEqual(canonical_name("Foo_Bar"), "foo_bar")


class TestUnknownProtocols(unittest.TestCase):
    def test_previously_unknown_set_now_empty(self) -> None:
        prev = [
            "aave-v3-arbitrum", "aave_v3_wsteth", "aerodrome_usdc_lp",
            "morpho-blue-steakhouse", "morpho_steakhouse", "ondo_usdy",
            "pendle-pt", "pendle_yt_susde",
        ]
        self.assertEqual(unknown_protocols(prev), [])

    def test_reports_genuine_unknowns(self) -> None:
        self.assertEqual(unknown_protocols(["aave_v3", "made_up_xyz"]), ["made_up_xyz"])


if __name__ == "__main__":
    unittest.main()
