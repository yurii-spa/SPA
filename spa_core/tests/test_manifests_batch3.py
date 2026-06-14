#!/usr/bin/env python3
"""Tests for SPA-V420 / MP-206 increment 2 — manifest batch 3 (9 new manifests).

Validates the THIRD (final) batch of declarative Adapter-SDK manifests in
``spa_core/adapter_sdk/manifests/`` that takes the epic over the "20+
adapters" line (12 -> 21): crvusd_llamalend, fraxlend, notional_v3, silo,
moonwell, dolomite, benqi, clearpool, ipor.

Pure stdlib ``unittest`` (pytest is not installed in this repo — mirrors
``test_manifests_batch2.py``). NO network: the registry is always loaded with
an injected dead feed and no test ever calls ``fetch_pools()``/``health()``
against a live feed.

Run:  python3 -m unittest spa_core.tests.test_manifests_batch3 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapter_sdk.contract import DEFAULT_TIER_CAPS, ProtocolAdapter
from spa_core.adapter_sdk.declarative_adapter import is_stable_symbol
from spa_core.adapter_sdk.discovery import (
    FILE_ADAPTER_PROTOCOL_SLUGS,
    covered_protocol_slugs,
    is_covered_protocol,
)
from spa_core.adapter_sdk.manifest import (
    AdapterManifest,
    _default_profile,
    load_manifest_file,
)
from spa_core.adapter_sdk.registry import (
    DEFAULT_MANIFESTS_DIR,
    discover_manifest_paths,
    load_all,
)

# Batches 1+2 (v4.17 / v4.19) — must stay untouched by this sprint.
PRIOR_BATCH_SLUGS = frozenset(
    {
        # batch 1 (v4.17)
        "spark", "fluid-lending", "curve-dex",
        # batch 2 (v4.19)
        "ethena-usde", "gearbox", "across", "stargate", "velodrome-v2",
        "convex-finance", "balancer-v2", "aerodrome-v1", "venus-core-pool",
    }
)

# sky/sUSDS has a dedicated FILE adapter (spa_core/execution/adapters/
# sky_susds_adapter.py, v3.29) — manifests must not collide with it either.
SKY_FILE_ADAPTER_SLUG = "sky-susds"

# Batch 3 (SPA-V420): file name -> (adapter name, DeFiLlama slug).
BATCH3 = {
    "crvusd_llamalend.yaml": ("crvusd_llamalend", "curve-llamalend"),
    "fraxlend.yaml": ("fraxlend", "fraxlend"),
    "notional_v3.yaml": ("notional_v3", "notional-v3"),
    "silo.yaml": ("silo", "silo-v2"),
    "moonwell.yaml": ("moonwell", "moonwell"),
    "dolomite.json": ("dolomite", "dolomite"),
    "benqi.json": ("benqi", "benqi-lending"),
    "clearpool.json": ("clearpool", "clearpool-lending"),
    "ipor.json": ("ipor", "ipor"),
}

# Peg-/credit-risk protocols deliberately capped BELOW the T3 default 0.10
# (same convention as ethena_susde in batch 2).
REDUCED_CAP_FILES = frozenset(
    {"crvusd_llamalend.yaml", "fraxlend.yaml", "clearpool.json", "ipor.json"}
)


class DeadFeed:
    """Feed double returning None for everything — zero network."""

    def fetch_pool(self, *args, **kwargs):
        return None


def _load_batch3():
    """Load every batch-3 manifest from the REAL manifests dir."""
    out = {}
    for filename in BATCH3:
        path = DEFAULT_MANIFESTS_DIR / filename
        out[filename] = load_manifest_file(path)
    return out


def _load_all_manifests():
    """Every manifest in the real dir (batches 1+2+3), validated."""
    return [load_manifest_file(p) for p in discover_manifest_paths(DEFAULT_MANIFESTS_DIR)]


# ─── Batch-3 files: presence + per-file validation ─────────────────────────────


class TestBatch3Files(unittest.TestCase):
    def test_all_batch3_files_present(self):
        for filename in BATCH3:
            self.assertTrue(
                (DEFAULT_MANIFESTS_DIR / filename).is_file(),
                f"missing manifest file: {filename}",
            )

    def test_each_batch3_manifest_validates(self):
        for filename, manifest in _load_batch3().items():
            self.assertIsInstance(manifest, AdapterManifest, filename)

    def test_names_and_slugs_match_expectations(self):
        for filename, manifest in _load_batch3().items():
            expected_name, expected_slug = BATCH3[filename]
            self.assertEqual(manifest.name, expected_name, filename)
            self.assertEqual(
                manifest.defillama_protocol_id, expected_slug, filename
            )

    def test_total_manifest_count_reaches_epic_target(self):
        # MP-206 epic target: 20+ manifests. 3 (v4.17) + 9 (v4.19) + 9 = 21.
        paths = discover_manifest_paths(DEFAULT_MANIFESTS_DIR)
        self.assertGreaterEqual(len(paths), 20)
        self.assertGreaterEqual(len(paths), 21)

    def test_mixed_yaml_and_json_formats(self):
        # Repo convention: both formats stay exercised by real manifests.
        suffixes = {Path(f).suffix for f in BATCH3}
        self.assertIn(".yaml", suffixes)
        self.assertIn(".json", suffixes)


# ─── Registry: everything loads, no invalid, no duplicates ────────────────────


class TestRegistryWithBatch3(unittest.TestCase):
    def setUp(self):
        self.reg = load_all(DEFAULT_MANIFESTS_DIR, feed=DeadFeed())

    def test_no_invalid_manifests(self):
        self.assertEqual(self.reg["invalid"], [])

    def test_every_file_produced_an_adapter(self):
        self.assertEqual(len(self.reg["adapters"]), len(self.reg["files"]))

    def test_batch3_adapters_registered(self):
        for name, _slug in BATCH3.values():
            self.assertIn(name, self.reg["adapters"])

    def test_adapters_implement_protocol_contract(self):
        for adapter in self.reg["adapters"].values():
            self.assertIsInstance(adapter, ProtocolAdapter)

    def test_unique_adapter_names_across_all_manifests(self):
        manifests = _load_all_manifests()
        names = [m.name for m in manifests]
        self.assertEqual(len(names), len(set(names)), f"duplicate names in {names}")

    def test_unique_defillama_slugs_across_all_manifests(self):
        manifests = _load_all_manifests()
        slugs = [m.defillama_protocol_id for m in manifests]
        self.assertEqual(len(slugs), len(set(slugs)), f"duplicate slugs in {slugs}")


# ─── Quality policy: conservative tiers, stable-only, sane gates ───────────────


class TestQualityPolicy(unittest.TestCase):
    def setUp(self):
        self.batch3 = _load_batch3()

    def test_tiers_conservative_t3_only(self):
        # Batch-3 policy: conservative T3 across the board (no T1/T2).
        for filename, m in self.batch3.items():
            self.assertEqual(m.tier, "T3", filename)

    def test_caps_within_tier_defaults(self):
        for filename, m in self.batch3.items():
            self.assertLessEqual(m.cap, DEFAULT_TIER_CAPS[m.tier], filename)
            self.assertGreater(m.cap, 0.0, filename)

    def test_peg_and_credit_risk_capped_below_tier_default(self):
        # crvUSD/FRAX peg axes + Clearpool/IPOR credit-derivative risk:
        # capped at 0.05, below the T3 default (ethena_susde convention).
        for filename in REDUCED_CAP_FILES:
            m = self.batch3[filename]
            self.assertLess(m.cap, DEFAULT_TIER_CAPS["T3"], filename)
            self.assertAlmostEqual(m.cap, 0.05, places=9, msg=filename)

    def test_stable_only_gate_enabled_everywhere(self):
        for filename, m in self.batch3.items():
            self.assertTrue(m.quality_gates.stable_only, filename)

    def test_every_symbol_leg_is_stable(self):
        # CRVUSD and FRAX are already in STABLE_SYMBOLS — no set changes made.
        for filename, m in self.batch3.items():
            for symbol in m.symbols:
                self.assertTrue(
                    is_stable_symbol(symbol),
                    f"{filename}: non-stable leg in symbol {symbol!r}",
                )

    def test_max_apy_sanity_band(self):
        # Mirrors the MP-205 discovery gate: APY above 30% is suspicious.
        for filename, m in self.batch3.items():
            self.assertIsNotNone(m.quality_gates.max_apy_pct, filename)
            self.assertLessEqual(m.quality_gates.max_apy_pct, 30.0, filename)

    def test_min_tvl_gate_at_candidate_level(self):
        # MP-206: "каждый через candidate-tier гейты" — TVL floor >= $5M.
        for filename, m in self.batch3.items():
            self.assertGreaterEqual(
                m.quality_gates.min_tvl_usd, 5_000_000.0, filename
            )


# ─── Exit latency: declared and self-consistent ───────────────────────────────


class TestExitLatencyDeclared(unittest.TestCase):
    def setUp(self):
        self.batch3 = _load_batch3()

    def test_exit_latency_hours_declared(self):
        # No "unknown == treated illiquid" surprises: every batch-3 manifest
        # declares hours explicitly.
        for filename, m in self.batch3.items():
            self.assertIsNotNone(m.exit_latency_hours, filename)

    def test_profile_matches_bucket(self):
        for filename, m in self.batch3.items():
            self.assertEqual(
                m.exit_latency_profile,
                _default_profile(m.exit_latency_hours),
                filename,
            )

    def test_no_illiquid_positions_in_batch3(self):
        # All batch-3 protocols are <= 24h exit — nothing crosses the 72h
        # illiquid threshold (the only illiquid manifest stays ethena_susde).
        for filename, m in self.batch3.items():
            self.assertLessEqual(m.exit_latency_hours, 72.0, filename)
            self.assertIn(m.exit_latency_profile, ("instant", "liquid"), filename)


# ─── No duplicate coverage (file adapters / batches 1-2 / discovery wiring) ────


class TestNoDuplicateCoverage(unittest.TestCase):
    def test_no_overlap_with_file_adapter_slugs(self):
        # Substring convention of the feed/discovery: assert NEITHER direction.
        for _name, slug in BATCH3.values():
            self.assertFalse(
                is_covered_protocol(slug, FILE_ADAPTER_PROTOCOL_SLUGS),
                f"slug {slug!r} collides with a file-adapter slug",
            )
            for file_slug in FILE_ADAPTER_PROTOCOL_SLUGS:
                self.assertNotIn(slug, file_slug)

    def test_no_overlap_with_sky_susds_file_adapter(self):
        for _name, slug in BATCH3.values():
            self.assertNotIn(SKY_FILE_ADAPTER_SLUG, slug)
            self.assertNotIn(slug, SKY_FILE_ADAPTER_SLUG)

    def test_no_overlap_with_prior_batch_manifest_slugs(self):
        # Both directions of the substring convention vs batches 1-2.
        for _name, slug in BATCH3.values():
            self.assertNotIn(slug, PRIOR_BATCH_SLUGS)
            self.assertFalse(
                is_covered_protocol(slug, PRIOR_BATCH_SLUGS),
                f"slug {slug!r} is substring-covered by a prior batch slug",
            )
            for prior_slug in PRIOR_BATCH_SLUGS:
                self.assertNotIn(slug, prior_slug)

    def test_no_substring_collisions_inside_batch3(self):
        slugs = [slug for _name, slug in BATCH3.values()]
        for a in slugs:
            for b in slugs:
                if a == b:
                    continue
                self.assertNotIn(a, b, f"{a!r} is a substring of {b!r}")

    def test_no_overlap_with_file_adapter_names(self):
        file_adapter_names = {
            "aave_v3", "compound_v3", "morpho_blue", "yearn_v3",
            "euler_v2", "maple", "pendle_pt", "sky_susds",
        }
        for name, _slug in BATCH3.values():
            self.assertNotIn(name, file_adapter_names)

    def test_discovery_now_covers_batch3_slugs(self):
        # MP-205 wiring: covered_protocol_slugs() reads the manifests dir
        # dynamically, so discovery must stop suggesting batch-3 protocols.
        covered = covered_protocol_slugs()
        for _name, slug in BATCH3.values():
            self.assertIn(slug, covered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
