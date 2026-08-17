"""A fuzzy hint must not hand over the APY of a DIFFERENT asset.

The defect. Pool resolution is two-stage: a pinned UUID first, then a fuzzy hint
on (project, chain, symbol). The TVL side of that contract was already honest —
only a pin may stamp ``tvl_source: "live"``, so a hint can never clear the $5M
floor. **The APY side had no such condition.** The hint matched ``symbol`` by
SUBSTRING and then took the largest TVL, so a pool of another asset on the same
chain and project matched too, and its yield was published as ours.

Why it matters even though the TVL gate holds. ``live_apy`` is read by the
ranking, the office house_view, the reports and the ADR-060 yield-improvement
trigger. A foreign asset may not take fresh capital directly, but it can move the
decision about where capital is taken FROM.

Why it did not look broken. Measured on the live feed 2026-08-09/10, the
near-misses below pay MORE than the real pool in three cases out of four. The
substitution reads as luck, not as a fault. Today the right pool wins only
because it happens to be the largest — a property of this week's numbers, not of
the rule. That is what this file pins.

The fix is asset identity: a hint match must carry ``underlyingTokens`` equal to
the one asset the hint is declared to mean (``_CANONICAL_UNDERLYING``). The data
was already in every feed record; it simply was not read.

Positive controls, not decoration. Every fixture here is a verbatim record from
the live feed, decoys included, and every decoy test FAILS on the unfixed
generator — verified by running this file against a pristine ``origin/main``
checkout before the fix landed. FakeFeed only, no test touches the network
(``.claude/rules/adapters.md``).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import adapter_status_generator as gen

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

# ── Real pools: what each hint SHOULD resolve to (live scan 2026-08-09/10) ───
_AAVE_V3_REAL = {
    "pool": "aa70268e-4b52-42bf-a116-608b370f9501",
    "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 178_734_645.0, "apy": 3.29338,
    "underlyingTokens": ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"],
}
_COMPOUND_REAL = {
    "pool": "7da72d09-56ca-4ec5-a45f-59114353e487",
    "project": "compound-v3", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 38_885_406.0, "apy": 3.29208,
    "underlyingTokens": ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"],
}
_MORPHO_REAL = {
    "pool": "931ea9be-5f4d-428e-beaf-205fc5b4e2b5",
    "project": "morpho-blue", "chain": "Ethereum", "symbol": "STEAKUSDC",
    "tvlUsd": 106_686_102.0, "apy": 3.25555,
    "underlyingTokens": ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"],
}
_SPARK_REAL = {
    "pool": "54e9b138-3146-4c1f-8dce-1cb948f5ef96",
    "project": "sparklend", "chain": "Ethereum", "symbol": "USDS",
    "tvlUsd": 543_078_478.0, "apy": 3.11143,
    "underlyingTokens": ["0xdC035D45d973E3EC169d2276DDab16f1e407384F"],
}
# yearn-finance reports its addresses LOWER-CASE while aave-v3 reports them
# mixed-case. The comparison must therefore be case-insensitive; a case-sensitive
# check would refuse every yearn pool while still looking like a working guard.
_YEARN_REAL = {
    "pool": "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
    "project": "yearn-finance", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 26_391_344.0, "apy": 3.30834,
    "underlyingTokens": ["0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"],
}

# ── Decoys: same project, same chain, symbol matches by SUBSTRING ────────────
_AAVE_V3_FOREIGN = {  # symbol is literally "USDC" — but not Circle's USDC
    "pool": "6f00d46b-8735-49ae-9ced-2a0fccc56ad0",
    "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC",
    "tvlUsd": 64_767_732.0, "apy": 4.79338,   # 4.79% vs the real 3.29%
    "underlyingTokens": ["0xD4fa2D31b7968E448877f69A96DE69f5de8cD23E"],
}
_MORPHO_SYRUP = {  # "SYRUPUSDC" CONTAINS "USDC"; $78.8M against the real $106.7M
    "pool": "44d88566-7795-49d3-a4a9-5d174cd40007",
    "project": "morpho-blue", "chain": "Ethereum", "symbol": "SYRUPUSDC",
    "tvlUsd": 78_764_064.0, "apy": 0.0,
    "underlyingTokens": ["0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b"],
}
_SPARK_WRAPPER = {  # "SUSDS" CONTAINS "USDS" — the wrapper, not the asset
    "pool": "d3694b72-5bc4-44c9-8ab6-1fc7941d216a",
    "project": "sparklend", "chain": "Ethereum", "symbol": "SUSDS",
    "tvlUsd": 3_293_501.0, "apy": 0.0,
    "underlyingTokens": ["0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"],
}
_YEARN_LP = {  # three-asset Curve pool that lists USDC FIRST — not a USDC vault
    "pool": "70684610-4bf2-489c-8329-af063de529a6",
    "project": "yearn-finance", "chain": "Ethereum", "symbol": "CRVUSDCWBTCWETH",
    "tvlUsd": 568_493.0, "apy": 5.04003,
    "underlyingTokens": [
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    ],
}

_REGISTRY = {
    "adapters": {
        "aave_v3":     {"protocol": "aave_v3", "tier": 1, "fallback_apy": 0.04,
                        "chain": "ethereum", "per_protocol_cap": 0.4, "status": "active"},
        "compound_v3": {"protocol": "compound_v3", "tier": 1, "fallback_apy": 0.04,
                        "chain": "ethereum", "per_protocol_cap": 0.4, "status": "active"},
        "morpho_blue": {"protocol": "morpho_blue", "tier": 2, "fallback_apy": 0.04,
                        "chain": "ethereum", "per_protocol_cap": 0.2, "status": "active"},
        "spark_susds": {"protocol": "spark_susds", "tier": 2, "fallback_apy": 0.03,
                        "chain": "ethereum", "per_protocol_cap": 0.2, "status": "active"},
        "yearn_v3":    {"protocol": "yearn_v3", "tier": 2, "fallback_apy": 0.04,
                        "chain": "ethereum", "per_protocol_cap": 0.2, "status": "active"},
    }
}


class _GenBase(unittest.TestCase):
    """generate() against a temp registry/output — no network, no repo data/."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.registry = self.data_dir / "adapter_registry.json"
        self.output = self.data_dir / "adapter_status.json"
        self.registry.write_text(json.dumps(_REGISTRY), encoding="utf-8")

    def _generate(self, pools):
        with patch(_FETCH, return_value=pools):
            return gen.generate(registry_path=self.registry, output_path=self.output)


class TestForeignAssetIsRefused(_GenBase):
    """The decoy ALONE: an unfixed matcher publishes its yield as ours."""

    def test_foreign_usdc_is_not_published_as_aave_v3(self):
        """4.79% off a token that is not Circle USDC — the largest key in the book.

        This is the positive control. Before the fix this exact record resolved
        by hint and ``live_apy`` came out 4.79338; the pool is $64.8M, so "best
        TVL wins" would take it outright the moment the real pool shrank below it.
        """
        doc = self._generate([_AAVE_V3_FOREIGN])
        row = doc["adapters"]["aave_v3"]
        self.assertIsNone(row["live_apy"], "a foreign asset's APY was published")
        self.assertIsNone(row["pool_match"])
        self.assertIn("foreign asset", row["pool_match_refused"] or "")

    def test_syrupusdc_is_not_published_as_morpho_blue(self):
        doc = self._generate([_MORPHO_SYRUP])
        row = doc["adapters"]["morpho_blue"]
        self.assertIsNone(row["live_apy"])
        self.assertIsNone(row["pool_match"])

    def test_susds_wrapper_is_not_published_as_spark_usds(self):
        """Symbol "SUSDS" contains "USDS" — a wrapper is not its underlying."""
        doc = self._generate([_SPARK_WRAPPER])
        row = doc["adapters"]["spark_susds"]
        self.assertIsNone(row["live_apy"])
        self.assertIsNone(row["pool_match"])

    def test_multi_asset_lp_is_not_published_as_a_usdc_vault(self):
        """CRVUSDCWBTCWETH lists USDC first; taking token[0] would accept it.

        Refusing multi-token exposure is the point: an LP position is a different
        instrument from the single-asset lending pool the hint models, and its
        5.04% would rank capital as if the two were comparable.
        """
        doc = self._generate([_YEARN_LP])
        row = doc["adapters"]["yearn_v3"]
        self.assertIsNone(row["live_apy"])
        self.assertIsNone(row["pool_match"])

    def test_refusal_is_named_not_silent(self):
        """A null alone reports "refused" and "feed was empty" identically."""
        doc = self._generate([_AAVE_V3_FOREIGN])
        reason = doc["adapters"]["aave_v3"]["pool_match_refused"]
        self.assertTrue(reason, "the refusal left no reason behind")
        self.assertIn("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", reason.lower())


class TestRealAssetStillResolves(_GenBase):
    """The other direction: tightening must not silence the honest pools."""

    def test_the_four_asset_hint_keys_still_resolve(self):
        """Measured: the asset guard nullifies NOTHING on the live feed of 2026-08-10.

        Worth stating plainly — the guard buys no yield today. It buys the
        guarantee that tomorrow's ranking still describes the asset we hold.

        NARROWED 2026-08-17 (agent-spark-susds-identity-split), deliberately and
        not to green a red CI. This test used to assert a FIFTH key,
        ``spark_susds`` → 3.1114 off ``_SPARK_REAL``, and that assertion was the
        defect written down: ``_SPARK_REAL`` is the SparkLend USDS **lending
        market**, while the ``spark_susds`` adapter models the **sUSDS savings
        vault** (``VAULT_ADDRESS`` 0xa393…7fbD) — a different product, already
        pinned by UUID under the ``sky_susds`` key. The asset guard this file
        pins cannot see it: the lending market's underlying really is USDS, so
        every check here passed on a foreign product.

        The key is now refused by the instrument-identity layer, and the
        expectation moved rather than disappeared — see
        ``test_spark_susds_identity_split.py`` (positive control reproduces the
        3.1114 substitution) and the sibling test below, which keeps the refusal
        under this file's own eye. Recorded in docs/journal/2026-W34.md.
        """
        doc = self._generate([
            _AAVE_V3_REAL, _COMPOUND_REAL, _MORPHO_REAL, _SPARK_REAL, _YEARN_REAL,
            _AAVE_V3_FOREIGN, _MORPHO_SYRUP, _SPARK_WRAPPER, _YEARN_LP,
        ])
        expected = {
            "aave_v3": 3.2934, "compound_v3": 3.2921, "morpho_blue": 3.2555,
            "yearn_v3": 3.3083,
        }
        for key, apy in expected.items():
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertEqual(row["pool_match"], "hint")
                self.assertAlmostEqual(row["live_apy"], apy, places=3)
                self.assertIsNone(row["pool_match_refused"])

    def test_spark_susds_takes_no_number_from_the_lending_market(self):
        """The fifth key: its hint matches, its ASSET matches — and it is still wrong.

        Kept here rather than only in the identity file so that anyone widening
        ``_CANONICAL_UNDERLYING`` sees immediately that asset identity is not
        product identity.
        """
        doc = self._generate([_SPARK_REAL, _SPARK_WRAPPER])
        row = doc["adapters"]["spark_susds"]
        self.assertIsNone(row["live_apy"])
        self.assertIsNone(row["pool_match"])
        self.assertIn("identity disputed", row["pool_match_refused"] or "")

    def test_lower_case_feed_addresses_still_match(self):
        """yearn-finance reports lower-case; aave-v3 reports mixed.

        A case-sensitive comparison passes every test above except this one, and
        would silently zero the yearn key in production.
        """
        doc = self._generate([_YEARN_REAL])
        self.assertEqual(doc["adapters"]["yearn_v3"]["pool_match"], "hint")
        self.assertAlmostEqual(doc["adapters"]["yearn_v3"]["live_apy"], 3.3083, places=3)

    def test_real_pool_wins_even_when_the_decoy_is_bigger(self):
        """Sizes INVERTED — the rule is pinned, not today's ordering.

        Today ``aave_v3`` resolves correctly only because the real pool ($178.7M)
        outweighs the foreign one ($64.8M). Feed the decoy at $900M and the old
        "best TVL wins" hands over 9.9%.
        """
        bigger_decoy = dict(_AAVE_V3_FOREIGN, tvlUsd=900_000_000.0, apy=9.9)
        doc = self._generate([_AAVE_V3_REAL, bigger_decoy])
        row = doc["adapters"]["aave_v3"]
        self.assertAlmostEqual(row["live_apy"], 3.2934, places=3)
        self.assertEqual(row["pool_match"], "hint")


class TestCanonicalTableIsFailClosed(unittest.TestCase):
    """The declaration itself — an undeclared asset must refuse, not guess."""

    def test_every_hint_has_a_declared_asset(self):
        """Otherwise the hint resolves on a substring, which is the defect.

        Fail-CLOSED means the code refuses such a key at runtime; this test says
        the shipped table has no such key, so nobody has to discover it as a null.
        """
        undeclared = [
            key for key, (_p, sym, chain) in gen._DEFILLAMA_HINTS.items()
            if (chain.lower(), sym.upper()) not in gen._CANONICAL_UNDERLYING
        ]
        self.assertEqual(undeclared, [], f"hints with no declared asset: {undeclared}")

    def test_undeclared_pair_refuses_the_whole_hint(self):
        """Remove the declaration and the key must go dark, not fuzzy."""
        table = dict(gen._CANONICAL_UNDERLYING)
        table.pop(("ethereum", "USDC"))
        by_id, by_pcs = gen._build_pool_indexes([_AAVE_V3_REAL, _AAVE_V3_FOREIGN])
        with patch.object(gen, "_CANONICAL_UNDERLYING", table):
            pool, reason = gen._hint_pool("aave_v3", by_pcs)
        self.assertIsNone(pool)
        self.assertIn("no canonical underlying", reason)

    def test_addresses_are_stored_lower_case(self):
        """The comparison lower-cases the feed side; the table must match it."""
        for pair, addr in gen._CANONICAL_UNDERLYING.items():
            with self.subTest(pair=pair):
                self.assertEqual(addr, addr.lower())
                self.assertTrue(addr.startswith("0x") and len(addr) == 42)

    def test_pins_are_unaffected_by_the_hint_guard(self):
        """A pinned UUID is already auditable — the guard must not re-litigate it.

        ``morpho_steakhouse`` is pinned to the STEAKUSDC pool, whose SYMBOL does
        not contain the hint's "USDC" as a whole word. If the identity check ever
        moved in front of the pin, every pinned key would go dark at once.
        """
        by_id, by_pcs = gen._build_pool_indexes([_MORPHO_REAL])
        match = gen._lookup_live_pool("morpho_steakhouse", by_id, by_pcs)
        self.assertIsNotNone(match)
        self.assertEqual(match[1], "pinned")


class TestUnderlyingExtraction(unittest.TestCase):
    """``_pool_underlying`` — the one place the identity is read."""

    def test_single_token_is_lower_cased(self):
        self.assertEqual(
            gen._pool_underlying(_AAVE_V3_REAL),
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        )

    def test_missing_field_is_none_not_a_guess(self):
        self.assertIsNone(gen._pool_underlying({"pool": "x"}))

    def test_multi_token_is_none(self):
        self.assertIsNone(gen._pool_underlying(_YEARN_LP))

    def test_empty_and_malformed_are_none(self):
        for tokens in ([], [""], ["   "], [None], "0xabc", [123]):
            with self.subTest(tokens=tokens):
                self.assertIsNone(gen._pool_underlying({"underlyingTokens": tokens}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
