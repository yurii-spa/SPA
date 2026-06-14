#!/usr/bin/env python3
"""Tests for SPA-V417 Adapter SDK v1 (MP-204) — declarative YAML/JSON adapters.

Pure stdlib ``unittest`` (pytest is not installed in this repo — mirrors the
sibling ``test_capacity_analytics.py`` / ``test_llm_forbidden_lint.py`` style).
NO network: the DeFiLlama feed is always injected as an in-memory fake; the
CLI subprocess tests run with ``--no-fetch`` (feed disabled — zero egress).

Run:  python3 -m unittest spa_core.tests.test_adapter_sdk -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapter_sdk import manifest as manifest_mod
from spa_core.adapter_sdk.contract import (
    DEFAULT_TIER_CAPS,
    PoolInfo,
    ProtocolAdapter,
    VALID_TIERS,
)
from spa_core.adapter_sdk.declarative_adapter import DeclarativeAdapter, is_stable_symbol
from spa_core.adapter_sdk.manifest import (
    AdapterManifest,
    ValidationError,
    load_manifest_file,
    validate_manifest,
)
from spa_core.adapter_sdk.registry import (
    DEFAULT_MANIFESTS_DIR,
    build_status_report,
    discover_manifest_paths,
    load_all,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── Test doubles (no network) ────────────────────────────────────────────────


class FakeFeed:
    """In-memory stand-in for DeFiLlamaFeed.fetch_pool (honours min_tvl_usd)."""

    def __init__(self, pools=None):
        # {(project, symbol, chain): {"apy": pct, "tvl": usd, "pool_id": uuid}}
        self.pools = dict(pools or {})
        self.calls = []

    def fetch_pool(self, project, symbol, chain="Ethereum", min_tvl_usd=100_000.0):
        self.calls.append((project, symbol, chain, min_tvl_usd))
        rec = self.pools.get((project, symbol, chain))
        if rec is None:
            return None
        tvl = rec.get("tvl")
        if isinstance(tvl, (int, float)) and tvl < min_tvl_usd:
            return None
        return dict(rec)


class DeadFeed:
    """Feed that returns None for everything (network down / no match)."""

    def fetch_pool(self, *args, **kwargs):
        return None


class RaisingFeed:
    """Feed that blows up — the adapter must degrade, not crash."""

    def fetch_pool(self, *args, **kwargs):
        raise RuntimeError("connection refused")


def _valid_raw(**overrides):
    raw = {
        "name": "spark",
        "defillama_protocol_id": "spark",
        "chains": ["Ethereum"],
        "symbols": ["USDC"],
        "tier": "T2",
        "cap": 0.2,
        "exit_latency": {"hours": 0.0, "profile": "instant"},
        "quality_gates": {"min_tvl_usd": 1_000_000.0, "stable_only": True},
    }
    raw.update(overrides)
    return raw


def _adapter(feed, **overrides):
    return DeclarativeAdapter(validate_manifest(_valid_raw(**overrides)), feed=feed)


# ─── Contract ─────────────────────────────────────────────────────────────────


class TestContract(unittest.TestCase):
    def test_declarative_adapter_implements_protocol(self):
        adapter = _adapter(DeadFeed())
        self.assertIsInstance(adapter, ProtocolAdapter)
        for method in ("fetch_pools", "exit_latency", "health"):
            self.assertTrue(callable(getattr(adapter, method)))
        self.assertEqual(adapter.name, "spark")

    def test_pool_info_apy_decimal_and_to_dict(self):
        p = PoolInfo(
            protocol="x", pool_id="x-usdc-ethereum", chain="Ethereum",
            symbol="USDC", apy_pct=8.5, tvl_usd=1e6, tier="T2",
        )
        self.assertAlmostEqual(p.apy, 0.085)
        d = p.to_dict()
        self.assertEqual(d["apy_pct"], 8.5)
        self.assertAlmostEqual(d["apy"], 0.085)
        self.assertEqual(d["source"], "defillama")

    def test_pool_info_apy_none(self):
        p = PoolInfo(
            protocol="x", pool_id="p", chain="Ethereum", symbol="USDC",
            apy_pct=None, tvl_usd=None, tier="T3",
        )
        self.assertIsNone(p.apy)

    def test_tier_constants(self):
        self.assertEqual(VALID_TIERS, ("T1", "T2", "T3"))
        for tier in VALID_TIERS:
            self.assertIn(tier, DEFAULT_TIER_CAPS)


# ─── Manifest validation ──────────────────────────────────────────────────────


class TestManifestValidation(unittest.TestCase):
    def test_valid_manifest(self):
        m = validate_manifest(_valid_raw())
        self.assertIsInstance(m, AdapterManifest)
        self.assertEqual(m.name, "spark")
        self.assertEqual(m.tier, "T2")
        self.assertEqual(m.chains, ("Ethereum",))
        self.assertEqual(m.exit_latency_hours, 0.0)
        self.assertEqual(m.exit_latency_profile, "instant")
        self.assertTrue(m.quality_gates.stable_only)

    def test_missing_name(self):
        raw = _valid_raw()
        del raw["name"]
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(raw)
        self.assertTrue(any("'name'" in p for p in ctx.exception.problems))

    def test_unknown_tier(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(_valid_raw(tier="T9"))
        joined = " ".join(ctx.exception.problems)
        self.assertIn("T9", joined)
        self.assertIn("T1/T2/T3", joined)

    def test_negative_min_tvl_gate(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(_valid_raw(quality_gates={"min_tvl_usd": -5}))
        self.assertTrue(
            any("min_tvl_usd" in p for p in ctx.exception.problems)
        )

    def test_multiple_problems_collected(self):
        raw = _valid_raw(tier="T9", cap=7.0, quality_gates={"min_tvl_usd": -1})
        del raw["name"]
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(raw)
        self.assertGreaterEqual(len(ctx.exception.problems), 4)

    def test_non_mapping_manifest(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(["not", "a", "dict"])
        self.assertTrue(any("mapping" in p for p in ctx.exception.problems))

    def test_cap_defaults_by_tier(self):
        raw = _valid_raw(tier="T1")
        del raw["cap"]
        self.assertEqual(validate_manifest(raw).cap, DEFAULT_TIER_CAPS["T1"])

    def test_cap_out_of_range(self):
        with self.assertRaises(ValidationError):
            validate_manifest(_valid_raw(cap=1.5))
        with self.assertRaises(ValidationError):
            validate_manifest(_valid_raw(cap=0))

    def test_exit_latency_defaults_unknown(self):
        raw = _valid_raw()
        del raw["exit_latency"]
        m = validate_manifest(raw)
        self.assertIsNone(m.exit_latency_hours)
        self.assertEqual(m.exit_latency_profile, "unknown")

    def test_exit_latency_negative_hours(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_manifest(_valid_raw(exit_latency={"hours": -3}))
        self.assertTrue(any("exit_latency.hours" in p for p in ctx.exception.problems))

    def test_exit_latency_numeric_shorthand(self):
        m = validate_manifest(_valid_raw(exit_latency=336.0))
        self.assertEqual(m.exit_latency_hours, 336.0)
        self.assertEqual(m.exit_latency_profile, "illiquid")

    def test_chains_string_coerced(self):
        m = validate_manifest(_valid_raw(chains="Base"))
        self.assertEqual(m.chains, ("Base",))


# ─── Manifest file loading: YAML / JSON / broken input ────────────────────────


class TestManifestLoading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_yaml_manifest_loads(self):
        p = self._write(
            "a.yaml",
            "name: spark\ndefillama_protocol_id: spark\ntier: T2\n",
        )
        m = load_manifest_file(p)
        self.assertEqual(m.name, "spark")
        self.assertEqual(m.source_path, str(p))

    def test_json_manifest_equivalent_to_yaml(self):
        raw = _valid_raw()
        py = self._write(
            "a.yaml",
            "\n".join(
                [
                    "name: spark",
                    "defillama_protocol_id: spark",
                    "chains: [Ethereum]",
                    "symbols: [USDC]",
                    "tier: T2",
                    "cap: 0.2",
                    "exit_latency: {hours: 0.0, profile: instant}",
                    "quality_gates: {min_tvl_usd: 1000000.0, stable_only: true}",
                ]
            ),
        )
        pj = self._write("b.json", json.dumps(raw))
        my = load_manifest_file(py)
        mj = load_manifest_file(pj)
        dy, dj = my.to_dict(), mj.to_dict()
        dy.pop("source_path"), dj.pop("source_path")
        self.assertEqual(dy, dj)

    def test_broken_yaml_is_validation_error(self):
        p = self._write("bad.yaml", "name: [unclosed\n  tier: : :")
        with self.assertRaises(ValidationError) as ctx:
            load_manifest_file(p)
        self.assertTrue(any("YAML" in prob for prob in ctx.exception.problems))

    def test_broken_json_is_validation_error(self):
        p = self._write("bad.json", "{not json")
        with self.assertRaises(ValidationError) as ctx:
            load_manifest_file(p)
        self.assertTrue(any("JSON" in prob for prob in ctx.exception.problems))

    def test_missing_file_is_validation_error(self):
        with self.assertRaises(ValidationError):
            load_manifest_file(self.dir / "nope.yaml")

    def test_unsupported_extension(self):
        p = self._write("a.toml", "name = 'x'")
        with self.assertRaises(ValidationError):
            load_manifest_file(p)

    def test_yaml_unavailable_falls_back_to_json_compatible_body(self):
        # Simulate a sandbox without PyYAML: a .yaml file whose body is valid
        # JSON must still load (JSON is a YAML subset).
        p = self._write("a.yaml", json.dumps(_valid_raw()))
        orig = manifest_mod.yaml
        manifest_mod.yaml = None
        try:
            m = load_manifest_file(p)
            self.assertEqual(m.name, "spark")
        finally:
            manifest_mod.yaml = orig

    def test_yaml_unavailable_non_json_body_readable_error(self):
        p = self._write("a.yaml", "name: spark\ntier: T2\n")
        orig = manifest_mod.yaml
        manifest_mod.yaml = None
        try:
            with self.assertRaises(ValidationError) as ctx:
                load_manifest_file(p)
            self.assertTrue(any("PyYAML" in prob for prob in ctx.exception.problems))
        finally:
            manifest_mod.yaml = orig


# ─── DeclarativeAdapter.fetch_pools ───────────────────────────────────────────


class TestFetchPools(unittest.TestCase):
    def test_pool_info_fields_from_mocked_feed(self):
        feed = FakeFeed({
            ("spark", "USDC", "Ethereum"): {
                "apy": 4.2, "tvl": 25_000_000.0, "pool_id": "uuid-123",
            },
        })
        adapter = _adapter(feed)
        pools = adapter.fetch_pools()
        self.assertEqual(len(pools), 1)
        p = pools[0]
        self.assertIsInstance(p, PoolInfo)
        self.assertEqual(p.protocol, "spark")
        self.assertEqual(p.pool_id, "spark-usdc-ethereum")
        self.assertEqual(p.chain, "Ethereum")
        self.assertEqual(p.symbol, "USDC")
        self.assertEqual(p.apy_pct, 4.2)
        self.assertAlmostEqual(p.apy, 0.042)
        self.assertEqual(p.tvl_usd, 25_000_000.0)
        self.assertEqual(p.tier, "T2")
        self.assertEqual(p.defillama_pool_id, "uuid-123")
        self.assertEqual(p.exit_latency_hours, 0.0)
        self.assertEqual(p.source, "defillama")
        self.assertIsNotNone(p.fetched_at)

    def test_min_tvl_gate_passed_to_feed(self):
        feed = FakeFeed()
        _adapter(feed).fetch_pools()
        self.assertEqual(feed.calls[0][3], 1_000_000.0)

    def test_quality_gate_tvl_below_min_dropped(self):
        # Feed returns a pool below the gate (e.g. an injected feed ignoring
        # the min_tvl parameter) — the adapter's own gate must drop it.
        class IgnoresMinTvl(FakeFeed):
            def fetch_pool(self, project, symbol, chain="Ethereum", min_tvl_usd=0.0):
                return {"apy": 5.0, "tvl": 50_000.0, "pool_id": "tiny"}

        pools = _adapter(IgnoresMinTvl()).fetch_pools()
        self.assertEqual(pools, [])

    def test_quality_gate_max_apy(self):
        feed = FakeFeed({
            ("spark", "USDC", "Ethereum"): {
                "apy": 95.0, "tvl": 25_000_000.0, "pool_id": "u",
            },
        })
        pools = _adapter(feed, quality_gates={
            "min_tvl_usd": 1_000_000.0, "max_apy_pct": 30.0,
        }).fetch_pools()
        self.assertEqual(pools, [])

    def test_quality_gate_stable_only(self):
        feed = FakeFeed({
            ("spark", "WETH", "Ethereum"): {
                "apy": 2.0, "tvl": 25_000_000.0, "pool_id": "u",
            },
        })
        adapter = _adapter(feed, symbols=["WETH"])
        self.assertEqual(adapter.fetch_pools(), [])

    def test_is_stable_symbol(self):
        self.assertTrue(is_stable_symbol("USDC"))
        self.assertTrue(is_stable_symbol("DAI-USDC-USDT"))
        self.assertFalse(is_stable_symbol("WETH"))
        self.assertFalse(is_stable_symbol("USDC-WETH"))
        self.assertFalse(is_stable_symbol(""))

    def test_multi_chain_multi_symbol_partial(self):
        feed = FakeFeed({
            ("spark", "USDC", "Ethereum"): {
                "apy": 4.0, "tvl": 10_000_000.0, "pool_id": "a",
            },
        })
        adapter = _adapter(feed, symbols=["USDC", "DAI"])
        pools = adapter.fetch_pools()
        self.assertEqual(len(pools), 1)
        self.assertEqual(adapter.health()["status"], "degraded")


# ─── exit_latency / health schemas ────────────────────────────────────────────


class TestExitLatencyAndHealth(unittest.TestCase):
    def test_exit_latency_schema(self):
        rep = _adapter(DeadFeed()).exit_latency()
        for key in ("protocol", "exit_latency_hours", "bucket", "profile",
                    "threshold_hours"):
            self.assertIn(key, rep)
        self.assertEqual(rep["bucket"], "instant")
        self.assertEqual(rep["threshold_hours"], 72.0)

    def test_exit_latency_illiquid_bucket(self):
        rep = _adapter(DeadFeed(), exit_latency={"hours": 336.0}).exit_latency()
        self.assertEqual(rep["bucket"], "illiquid")

    def test_health_ok(self):
        feed = FakeFeed({
            ("spark", "USDC", "Ethereum"): {
                "apy": 4.0, "tvl": 10_000_000.0, "pool_id": "a",
            },
        })
        adapter = _adapter(feed)
        adapter.fetch_pools()
        h = adapter.health()
        for key in ("protocol", "status", "last_fetch_ts", "source",
                    "pools_live", "pools_expected", "tier", "error"):
            self.assertIn(key, h)
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["pools_live"], 1)
        self.assertEqual(h["source"], "defillama")
        self.assertIsNone(h["error"])

    def test_health_error_on_dead_feed(self):
        adapter = _adapter(DeadFeed())
        self.assertEqual(adapter.fetch_pools(), [])
        h = adapter.health()
        self.assertEqual(h["status"], "error")
        self.assertEqual(h["pools_live"], 0)
        self.assertIsNotNone(h["error"])

    def test_raising_feed_degrades_without_crash(self):
        adapter = _adapter(RaisingFeed())
        pools = adapter.fetch_pools()  # must not raise
        self.assertEqual(pools, [])
        h = adapter.health()
        self.assertEqual(h["status"], "error")
        self.assertIn("RuntimeError", str(h["error"]))

    def test_health_lazy_fetch(self):
        feed = FakeFeed({
            ("spark", "USDC", "Ethereum"): {
                "apy": 4.0, "tvl": 10_000_000.0, "pool_id": "a",
            },
        })
        h = _adapter(feed).health()  # no explicit fetch_pools() call
        self.assertEqual(h["status"], "ok")
        self.assertIsNotNone(h["last_fetch_ts"])


# ─── Registry ────────────────────────────────────────────────────────────────


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_valid(self, name="spark", filename=None):
        raw = _valid_raw(name=name)
        p = self.dir / (filename or f"{name}.json")
        p.write_text(json.dumps(raw), encoding="utf-8")
        return p

    def test_invalid_manifest_does_not_break_registry(self):
        self._write_valid("spark")
        (self.dir / "broken.yaml").write_text("tier: T9\n", encoding="utf-8")
        reg = load_all(self.dir, feed=DeadFeed())
        self.assertEqual(sorted(reg["adapters"]), ["spark"])
        self.assertEqual(len(reg["invalid"]), 1)
        problems = reg["invalid"][0]["problems"]
        self.assertTrue(any("'name'" in p for p in problems))
        self.assertTrue(any("T9" in p for p in problems))

    def test_duplicate_name_flagged(self):
        self._write_valid("spark", filename="a.json")
        self._write_valid("spark", filename="b.json")
        reg = load_all(self.dir, feed=DeadFeed())
        self.assertEqual(len(reg["adapters"]), 1)
        self.assertEqual(len(reg["invalid"]), 1)
        self.assertIn("duplicate", reg["invalid"][0]["problems"][0])

    def test_missing_dir_empty(self):
        reg = load_all(self.dir / "nope", feed=DeadFeed())
        self.assertEqual(reg["adapters"], {})
        self.assertEqual(reg["files"], [])

    def test_real_manifests_dir_all_valid(self):
        # The shipped demo manifests must always validate.
        paths = discover_manifest_paths(DEFAULT_MANIFESTS_DIR)
        self.assertGreaterEqual(len(paths), 2)
        reg = load_all(DEFAULT_MANIFESTS_DIR, feed=DeadFeed())
        self.assertEqual(reg["invalid"], [])
        self.assertEqual(len(reg["adapters"]), len(paths))
        for adapter in reg["adapters"].values():
            self.assertIsInstance(adapter, ProtocolAdapter)
            self.assertIn(adapter.tier, ("T2", "T3"))  # conservative demo tiers
            # demo protocols must NOT collide with existing file adapters
            self.assertNotIn(adapter.name, {
                "aave_v3", "compound_v3", "morpho_blue", "yearn_v3",
                "euler_v2", "maple", "pendle_pt",
            })

    def test_status_report_schema_and_counts(self):
        self._write_valid("spark")
        (self.dir / "broken.json").write_text("{", encoding="utf-8")
        reg = load_all(self.dir, feed=DeadFeed())
        report = build_status_report(reg, fetch=True)
        self.assertEqual(report["execution_mode"], "read_only_simulation")
        s = report["summary"]
        self.assertEqual(s["total_manifests"], 2)
        self.assertEqual(s["valid"], 1)
        self.assertEqual(s["invalid"], 1)
        self.assertEqual(s["status"], "invalid_manifests")
        self.assertEqual(s["health_error"], 1)  # DeadFeed -> honest error

    def test_atomic_write_no_tmp_leftovers(self):
        from spa_core.adapter_sdk.registry import _atomic_write_json

        self._write_valid("spark")
        reg = load_all(self.dir, feed=DeadFeed())
        report = build_status_report(reg, fetch=True)
        out = self.dir / "adapter_sdk_status.json"
        for _ in range(3):
            _atomic_write_json(report, out)
        self.assertTrue(out.exists())
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], 1)


# ─── CLI (subprocess; --no-fetch => zero network) ─────────────────────────────


class TestCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        cmd = [
            sys.executable, "-m", "spa_core.adapter_sdk.registry",
            "--manifests-dir", str(self.dir),
            "--no-fetch",
            *extra,
        ]
        return subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120
        )

    def _write_valid(self):
        (self.dir / "spark.json").write_text(
            json.dumps(_valid_raw()), encoding="utf-8"
        )

    def test_exit_0_all_valid(self):
        self._write_valid()
        out = self.dir / "report.json"
        res = self._run("--out", str(out))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("status=ok", res.stdout)
        self.assertTrue(out.exists())
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_exit_1_invalid_manifest(self):
        self._write_valid()
        (self.dir / "broken.yaml").write_text("tier: T9\n", encoding="utf-8")
        res = self._run("--no-write")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("INVALID", res.stdout)

    def test_exit_2_empty_dir(self):
        res = self._run("--no-write")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)

    def test_no_write_creates_no_file(self):
        self._write_valid()
        out = self.dir / "report.json"
        res = self._run("--no-write", "--out", str(out))
        self.assertEqual(res.returncode, 0)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
