#!/usr/bin/env python3
"""Tests for SPA-V419 / MP-206 increment 1 — manifest batch 2 (9 new manifests).

Validates the SECOND batch of declarative Adapter-SDK manifests shipped in
``spa_core/adapter_sdk/manifests/`` (on top of the v4.17 trio spark / fluid /
curve_3pool): ethena_susde, gearbox, across, stargate, velodrome_stable,
convex_3pool, balancer_stable, aerodrome_stable, venus.

Pure stdlib ``unittest`` (pytest is not installed in this repo — mirrors
``test_adapter_sdk.py`` / ``test_discovery.py``). NO network: the registry is
always loaded with an injected dead feed and no test ever calls
``fetch_pools()``/``health()`` against a live feed.

Run:  python3 -m unittest spa_core.tests.test_manifests_batch2 -v
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

# v4.17 demo manifests (batch 1) — must stay untouched by this sprint.
BATCH1_SLUGS = frozenset({"spark", "fluid-lending", "curve-dex"})

# Batch 2 (SPA-V419): file name -> (adapter name, DeFiLlama slug).
BATCH2 = {
    "ethena_susde.yaml": ("ethena_susde", "ethena-usde"),
    "gearbox.yaml": ("gearbox", "gearbox"),
    "across.yaml": ("across", "across"),
    "stargate.yaml": ("stargate", "stargate"),
    "velodrome_stable.yaml": ("velodrome_stable", "velodrome-v2"),
    "convex_3pool.json": ("convex_3pool", "convex-finance"),
    "balancer_stable.json": ("balancer_stable", "balancer-v2"),
    "aerodrome_stable.json": ("aerodrome_stable", "aerodrome-v1"),
    "venus.json": ("venus", "venus-core-pool"),
}


class DeadFeed:
    """Feed double returning None for everything — zero network."""

    def fetch_pool(self, *args, **kwargs):
        return None


def _load_batch2():
    """Load every batch-2 manifest from the REAL manifests dir."""
    out = {}
    for filename in BATCH2:
        path = DEFAULT_MANIFESTS_DIR / filename
        out[filename] = load_manifest_file(path)
    return out


def _load_all_manifests():
    """Every manifest in the real dir (batch 1 + batch 2), validated."""
    return [load_manifest_file(p) for p in discover_manifest_paths(DEFAULT_MANIFESTS_DIR)]


# ─── Batch-2 files: presence + per-file validation ─────────────────────────────


class TestBatch2Files(unittest.TestCase):
    def test_all_batch2_files_present(self):
        for filename in BATCH2:
            self.assertTrue(
                (DEFAULT_MANIFESTS_DIR / filename).is_file(),
                f"missing manifest file: {filename}",
            )

    def test_each_batch2_manifest_validates(self):
        for filename, manifest in _load_batch2().items():
            self.assertIsInstance(manifest, AdapterManifest, filename)

    def test_names_and_slugs_match_expectations(self):
        for filename, manifest in _load_batch2().items():
            expected_name, expected_slug = BATCH2[filename]
            self.assertEqual(manifest.name, expected_name, filename)
            self.assertEqual(
                manifest.defillama_protocol_id, expected_slug, filename
            )

    def test_total_manifest_count_progress(self):
        # MP-206 increment 1: 3 (v4.17) + 9 (this sprint) = 12 manifests.
        paths = discover_manifest_paths(DEFAULT_MANIFESTS_DIR)
        self.assertGreaterEqual(len(paths), 12)

    def test_mixed_yaml_and_json_formats(self):
        # Repo convention: both formats stay exercised by real manifests.
        suffixes = {Path(f).suffix for f in BATCH2}
        self.assertIn(".yaml", suffixes)
        self.assertIn(".json", suffixes)


# ─── Registry: everything loads, no invalid, no duplicates ────────────────────


class TestRegistryWithBatch2(unittest.TestCase):
    def setUp(self):
        self.reg = load_all(DEFAULT_MANIFESTS_DIR, feed=DeadFeed())

    def test_no_invalid_manifests(self):
        self.assertEqual(self.reg["invalid"], [])

    def test_every_file_produced_an_adapter(self):
        self.assertEqual(len(self.reg["adapters"]), len(self.reg["files"]))

    def test_batch2_adapters_registered(self):
        for name, _slug in BATCH2.values():
            self.assertIn(name, self.reg["adapters"])

    def test_adapters_implement_protocol_contract(self):
        for adapter in self.reg["adapters"].values():
            self.assertIsInstance(adapter, ProtocolAdapter)

    def test_unique_adapter_names(self):
        manifests = _load_all_manifests()
        names = [m.name for m in manifests]
        self.assertEqual(len(names), len(set(names)), f"duplicate names in {names}")

    def test_unique_defillama_slugs(self):
        manifests = _load_all_manifests()
        slugs = [m.defillama_protocol_id for m in manifests]
        self.assertEqual(len(slugs), len(set(slugs)), f"duplicate slugs in {slugs}")


# ─── Quality policy: conservative tiers, stable-only, sane gates ───────────────


class TestQualityPolicy(unittest.TestCase):
    def setUp(self):
        self.batch2 = _load_batch2()

    def test_tiers_conservative_t2_or_t3(self):
        for filename, m in self.batch2.items():
            self.assertIn(m.tier, ("T2", "T3"), filename)

    def test_caps_within_tier_defaults(self):
        for filename, m in self.batch2.items():
            self.assertLessEqual(m.cap, DEFAULT_TIER_CAPS[m.tier], filename)
            self.assertGreater(m.cap, 0.0, filename)

    def test_ethena_capped_below_tier_default(self):
        # MP-206 card: "Ethena (capped, ось peg)" — must stay BELOW the T3 cap.
        m = self.batch2["ethena_susde.yaml"]
        self.assertLess(m.cap, DEFAULT_TIER_CAPS["T3"])

    def test_stable_only_gate_enabled_everywhere(self):
        for filename, m in self.batch2.items():
            self.assertTrue(m.quality_gates.stable_only, filename)

    def test_every_symbol_leg_is_stable(self):
        for filename, m in self.batch2.items():
            for symbol in m.symbols:
                self.assertTrue(
                    is_stable_symbol(symbol),
                    f"{filename}: non-stable leg in symbol {symbol!r}",
                )

    def test_max_apy_sanity_band(self):
        # Mirrors the MP-205 discovery gate: APY above 30% is suspicious.
        for filename, m in self.batch2.items():
            self.assertIsNotNone(m.quality_gates.max_apy_pct, filename)
            self.assertLessEqual(m.quality_gates.max_apy_pct, 30.0, filename)

    def test_min_tvl_gate_at_candidate_level(self):
        # MP-206: "каждый через candidate-tier гейты" — TVL floor >= $5M.
        for filename, m in self.batch2.items():
            self.assertGreaterEqual(
                m.quality_gates.min_tvl_usd, 5_000_000.0, filename
            )


# ─── Exit latency: declared and self-consistent ───────────────────────────────


class TestExitLatencyDeclared(unittest.TestCase):
    def setUp(self):
        self.batch2 = _load_batch2()

    def test_exit_latency_hours_declared(self):
        # No "unknown == treated illiquid" surprises: every batch-2 manifest
        # declares hours explicitly.
        for filename, m in self.batch2.items():
            self.assertIsNotNone(m.exit_latency_hours, filename)

    def test_profile_matches_bucket(self):
        for filename, m in self.batch2.items():
            self.assertEqual(
                m.exit_latency_profile,
                _default_profile(m.exit_latency_hours),
                filename,
            )

    def test_ethena_unstake_cooldown_is_illiquid(self):
        m = self.batch2["ethena_susde.yaml"]
        self.assertGreater(m.exit_latency_hours, 72.0)
        self.assertEqual(m.exit_latency_profile, "illiquid")


# ─── No duplicate coverage (file adapters / batch 1 / discovery wiring) ────────


class TestNoDuplicateCoverage(unittest.TestCase):
    def test_no_overlap_with_file_adapter_slugs(self):
        # Substring convention of the feed/discovery: assert NEITHER direction.
        for _name, slug in BATCH2.values():
            self.assertFalse(
                is_covered_protocol(slug, FILE_ADAPTER_PROTOCOL_SLUGS),
                f"slug {slug!r} collides with a file-adapter slug",
            )
            for file_slug in FILE_ADAPTER_PROTOCOL_SLUGS:
                self.assertNotIn(slug, file_slug)

    def test_no_overlap_with_batch1_manifest_slugs(self):
        for _name, slug in BATCH2.values():
            self.assertNotIn(slug, BATCH1_SLUGS)
            self.assertFalse(is_covered_protocol(slug, BATCH1_SLUGS))

    def test_no_overlap_with_file_adapter_names(self):
        file_adapter_names = {
            "aave_v3", "compound_v3", "morpho_blue", "yearn_v3",
            "euler_v2", "maple", "pendle_pt",
        }
        for name, _slug in BATCH2.values():
            self.assertNotIn(name, file_adapter_names)

    def test_discovery_now_covers_batch2_slugs(self):
        # MP-205 wiring: covered_protocol_slugs() reads the manifests dir
        # dynamically, so discovery must stop suggesting batch-2 protocols.
        covered = covered_protocol_slugs()
        for _name, slug in BATCH2.values():
            self.assertIn(slug, covered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
