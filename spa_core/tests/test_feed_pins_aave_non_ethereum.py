"""ADR-076.1 — the four Aave pools outside Ethereum become MEASURED, not assumed.

Why this file exists. The book sits at the 90% single-chain limit for Ethereum,
so the redistribution path (ADR-072 → 072.1 → 073) is healthy and has nowhere to
put the idle cash: every candidate with a live TVL is on Ethereum. The four Aave
adapters on Base / Arbitrum / OP Mainnet / Polygon already reported a live APY —
the single missing measurement was the pool SIZE, and a constant can never
supply it: the $5M floor is a policy gate, and ``literal >= 5_000_000`` is
tautologically True (ADR-053, ADR-064).

So each of the four is pinned to a DeFiLlama pool UUID, verified by
``underlyingTokens`` == the native Circle USDC of that chain. The measurement is
what it is, in both directions, and both directions are pinned here:

* three pools clear the floor — the cash gains somewhere to stand;
* ``aave_v3_optimism`` observes $1.74M and honestly FAILS it. That is the
  correct outcome and it is asserted, not smoothed. Its static estimate claimed
  $400M — a 230x overstatement, the largest in the table, and exactly the class
  the moonwell 190x pin exposed.

Every fixture below is a verbatim record from the 2026-08-09 live scan,
including the near-miss pools (bridged USDC.e, SYRUPUSDC) that carry HIGHER
headline yields than the pins. Those are the temptation a fuzzy "best TVL wins"
match would eventually take; the tests that use them are positive controls, not
decoration. FakeFeed only — no test touches the network
(rule ``.claude/rules/adapters.md``).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.adapters.status_reader import tvl_floor_verdict
from spa_core.monitoring import adapter_status_generator as gen

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

# The RiskPolicy TVL floor is READ, never restated, so this file cannot drift
# from policy by carrying its own copy of the number.
_FLOOR_USD = 5_000_000.0

# ── The four pins, as the live feed reported them on 2026-08-09 ──────────────
# Shape verbatim; ``underlying`` is kept in the fixture because it is the fact
# that makes the identity checkable — each is the native Circle USDC.
_BASE_POOL = {
    "pool": "7e0661bf-8cf3-45e6-9424-31916d4c7b84",
    "project": "aave-v3", "chain": "Base", "symbol": "USDC",
    "tvlUsd": 21_897_189.0, "apy": 3.44813,
    "underlyingTokens": ["0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"],
}
_ARBITRUM_POOL = {
    "pool": "d9fa8e14-0447-4207-9ae8-7810199dfa1f",
    "project": "aave-v3", "chain": "Arbitrum", "symbol": "USDC",
    "tvlUsd": 39_513_923.0, "apy": 2.36165,
    "underlyingTokens": ["0xaf88d065e77c8cC2239327C5EDb3A432268e5831"],
}
_OPTIMISM_POOL = {
    "pool": "0758c3b8-4ffb-4176-b0a9-f446e367db46",
    # DeFiLlama calls this chain "OP Mainnet", never "Optimism"
    # (.claude/rules/adapters.md) — the label the hint spent months missing.
    "project": "aave-v3", "chain": "OP Mainnet", "symbol": "USDC",
    "tvlUsd": 1_736_770.0, "apy": 2.88407,
    "underlyingTokens": ["0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"],
}
_POLYGON_POOL = {
    "pool": "1b8b4cdb-0728-42a8-bf13-2c8fea7427ee",
    "project": "aave-v3", "chain": "Polygon", "symbol": "USDC",
    "tvlUsd": 12_013_655.0, "apy": 2.92236,
    "underlyingTokens": ["0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"],
}

# ── Near-miss pools from the SAME scan: every one is a real record ───────────
# Note the yields: two of the three pay MORE than the pool we pinned. A matcher
# that ranked by headline APY, or that let "USDC" match by substring, would rank
# capital by a different asset on a thinner pool.
_ARBITRUM_BRIDGED = {  # USDC.e — a different token, 4.17% vs the pin's 2.36%
    "pool": "7aab7b0f-01c1-4467-bc0d-77826d870f19",
    "project": "aave-v3", "chain": "Arbitrum", "symbol": "USDC",
    "tvlUsd": 145_956.0, "apy": 4.1698,
    "underlyingTokens": ["0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"],
}
_POLYGON_LEGACY = {  # USDC.e on Polygon — 3.18% vs the pin's 2.92%
    "pool": "37b04faa-95bb-4ccb-9c4e-c70fa167342b",
    "project": "aave-v3", "chain": "Polygon", "symbol": "USDC",
    "tvlUsd": 531_745.0, "apy": 3.18079,
    "underlyingTokens": ["0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"],
}
_BASE_SYRUP = {  # symbol SYRUPUSDC CONTAINS "USDC" — a substring hint match
    "pool": "974b8732-2dce-4a46-8204-7f9e6b7efb71",
    "project": "aave-v3", "chain": "Base", "symbol": "SYRUPUSDC",
    "tvlUsd": 12_449_038.0, "apy": 0.0,
    "underlyingTokens": ["0x660975730059246A68521a3e2FBD4740173100f5"],
}

_PINNED_POOLS = {
    "aave_v3_base":     _BASE_POOL,
    "aave_arbitrum":    _ARBITRUM_POOL,
    "aave_v3_optimism": _OPTIMISM_POOL,
    "aave_v3_polygon":  _POLYGON_POOL,
}

_ALL_POOLS = list(_PINNED_POOLS.values()) + [
    _ARBITRUM_BRIDGED, _POLYGON_LEGACY, _BASE_SYRUP,
]

_REGISTRY = {
    "adapters": {
        "aave_v3_base":     {"protocol": "aave_v3_base", "tier": 2,
                             "fallback_apy": 0.045, "chain": "base",
                             "per_protocol_cap": 0.2, "status": "active"},
        "aave_arbitrum":    {"protocol": "aave_arbitrum", "tier": 1,
                             "fallback_apy": 0.04, "chain": "arbitrum",
                             "per_protocol_cap": 0.2, "status": "active"},
        "aave_v3_optimism": {"protocol": "aave_v3_optimism", "tier": 1,
                             "fallback_apy": 0.04, "chain": "optimism",
                             "per_protocol_cap": 0.2, "status": "active"},
        "aave_v3_polygon":  {"protocol": "aave_v3_polygon", "tier": 1,
                             "fallback_apy": 0.04, "chain": "polygon",
                             "per_protocol_cap": 0.2, "status": "active"},
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
        """Generate AND write, because the floor verdict reads the file.

        ``generate()`` only builds the document; the consumer side of this
        contract (``status_reader``) goes through ``adapter_status.json`` on
        disk. Asserting on the in-memory doc alone would leave the path that
        actually decides capital untested.
        """
        with patch(_FETCH, return_value=pools):
            doc = gen.generate(registry_path=self.registry, output_path=self.output)
        gen.write(doc, self.output)
        return doc


class TestPinsRegistered(unittest.TestCase):
    """The pins themselves — a pure table check, no feed involved."""

    def test_four_keys_pinned_to_the_scanned_uuids(self):
        for key, pool in _PINNED_POOLS.items():
            with self.subTest(key=key):
                self.assertEqual(gen._POOL_ID_LOOKUP.get(key), pool["pool"])

    def test_four_distinct_non_ethereum_chains(self):
        """The whole point of ADR-076: somewhere OTHER than Ethereum.

        Four keys all landing on one chain would leave the 90% single-chain
        limit exactly as binding as before, while looking like progress.
        """
        chains = {p["chain"] for p in _PINNED_POOLS.values()}
        self.assertEqual(len(chains), 4, f"pins collapsed onto {chains}")
        self.assertNotIn("Ethereum", chains)

    def test_each_pin_is_native_circle_usdc(self):
        """Identity is the underlying token, not the symbol string.

        Both near-miss pools below carry symbol "USDC" too, and one of them pays
        more. Without this check the pins would rest on a label.
        """
        expected = {
            "aave_v3_base":     "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "aave_arbitrum":    "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
            "aave_v3_optimism": "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
            "aave_v3_polygon":  "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        }
        for key, want in expected.items():
            with self.subTest(key=key):
                got = [t.lower() for t in _PINNED_POOLS[key]["underlyingTokens"]]
                self.assertEqual(got, [want])


class TestPinnedObservation(_GenBase):
    """Each key yields a live, pinned, auditable TVL — with the UUID recorded."""

    def test_live_apy_and_pinned_tvl(self):
        doc = self._generate(_ALL_POOLS)
        for key, pool in _PINNED_POOLS.items():
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertAlmostEqual(row["live_apy"], round(pool["apy"], 4))
                self.assertTrue(row["live_apy_fresh"])
                self.assertEqual(row["pool_match"], "pinned")
                self.assertEqual(row["tvl_source"], "live")
                self.assertEqual(row["tvl_usd"], pool["tvlUsd"])
                # An auditor can re-fetch this UUID and reproduce the number.
                self.assertEqual(row["tvl_pool_id"], pool["pool"])

    def test_a_near_miss_can_never_supply_gate_grade_tvl(self):
        """Feed the decoys ALONE: the pins are gone, so the TVL must not be live.

        This is where the pin earns its keep. The decoys are the SAME project on
        the SAME chain with a symbol that contains "USDC", so the fuzzy hint
        still resolves them and still hands over an APY — 4.17% off a $146k
        bridged USDC.e pool, 3.18% off a $532k legacy pool. That APY is labelled
        ``pool_match: "hint"`` and only ranks (ADR-061 evidence gate guards it);
        the number that faces the $5M floor stays ``static``, with no UUID to
        pretend it was seen. If a hint match ever earned ``tvl_source: "live"``,
        a $146k pool of a different asset would clear a policy gate.
        """
        doc = self._generate([_ARBITRUM_BRIDGED, _POLYGON_LEGACY, _BASE_SYRUP])
        for key in ("aave_arbitrum", "aave_v3_polygon", "aave_v3_base"):
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertNotEqual(row["pool_match"], "pinned")
                self.assertEqual(row["tvl_source"], "static")
                self.assertIsNone(row["tvl_pool_id"])

    def test_pin_wins_even_when_a_decoy_is_bigger(self):
        """"Best TVL wins" must not survive next to a pin.

        Base carries SYRUPUSDC at $12.4M against the pinned $21.9M today, so the
        sizes are fed INVERTED here — the decoy made larger than the pin — to
        pin the rule rather than today's numbers.
        """
        bigger_decoy = dict(_BASE_SYRUP, tvlUsd=900_000_000.0, apy=9.9)
        doc = self._generate([_BASE_POOL, bigger_decoy])
        row = doc["adapters"]["aave_v3_base"]
        self.assertEqual(row["tvl_usd"], _BASE_POOL["tvlUsd"])
        self.assertEqual(row["tvl_pool_id"], _BASE_POOL["pool"])
        self.assertAlmostEqual(row["live_apy"], round(_BASE_POOL["apy"], 4))

    def test_static_estimate_is_never_stamped_live(self):
        """Feed answers, our pools are absent → static, and honestly labelled.

        The estimates being replaced are overstated 11x–230x; if the fallback
        path ever stamped them ``live`` they would clear the $5M floor on the
        strength of a literal — the precise failure ADR-053 forbids.
        """
        doc = self._generate([_ARBITRUM_BRIDGED])
        for key in _PINNED_POOLS:
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertEqual(row["tvl_source"], "static")
                self.assertIsNone(row["tvl_pool_id"])
                self.assertEqual(row["tvl_usd"], gen._TVL_ESTIMATES[key])
                # …and the literal is large enough that a "live" stamp would
                # have cleared the floor. That is what makes this a control.
                self.assertGreater(row["tvl_usd"], _FLOOR_USD)


class TestFloorVerdictOnTheObservation(_GenBase):
    """What the measurement actually decides — in BOTH directions."""

    def test_three_clear_the_floor_and_optimism_does_not(self):
        """The honest split. Asserting only the passes would hide the point.

        ``aave_v3_optimism`` observes $1.74M against a $400M estimate. The
        answer "no candidate here" IS the measurement (ADR-076: a negative
        outcome is allowed and must be named), not a number to go looking for.
        """
        self._generate(_ALL_POOLS)
        verdicts = {
            key: tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD)
            for key in _PINNED_POOLS
        }
        self.assertEqual(verdicts["aave_v3_base"], True)
        self.assertEqual(verdicts["aave_arbitrum"], True)
        self.assertEqual(verdicts["aave_v3_polygon"], True)
        self.assertEqual(verdicts["aave_v3_optimism"], False)

    def test_unobserved_is_unmeasured_not_a_pass(self):
        """No observation ⇒ ``None``. Not True, and not False either.

        Before the pins these four sat on constants and the floor could not
        return anything but True for any of them. The replacement must not swap
        one silent verdict for another.
        """
        self._generate([_ARBITRUM_BRIDGED])
        for key in _PINNED_POOLS:
            with self.subTest(key=key):
                self.assertIsNone(
                    tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD))

    def test_feed_down_leaves_every_verdict_unmeasured(self):
        """DeFiLlama unreachable is an incident, never evidence of anything."""
        doc = self._generate(None)
        self.assertFalse(doc["feed_reachable"])
        for key in _PINNED_POOLS:
            with self.subTest(key=key):
                self.assertIsNone(
                    tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD))


if __name__ == "__main__":
    unittest.main()
