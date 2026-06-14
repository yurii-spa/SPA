"""Tests for spa_core.adapter_sdk.discovery (SPA-V418 / MP-205).

unittest only (no pytest in this repo), ZERO network: the fetch function is
always injected as a fake. Covers every quality gate in isolation and
combined, the explicit age_unknown behaviour (flagged, NOT silently dropped),
covered-protocol exclusion, dedup, ranking/capping, honest error degradation,
atomic writes and the CLI exit codes via subprocess (offline --pools-file).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.adapter_sdk import discovery
from spa_core.adapter_sdk.discovery import (
    DiscoveryError,
    GateConfig,
    covered_protocol_slugs,
    evaluate_pool,
    extract_pools,
    is_covered_protocol,
    pool_age_days,
    run_discovery,
    write_report_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Deterministic "now" for age math: 2027-01-15ish, irrelevant which.
NOW = 1_800_000_000.0
DAY = 86_400

# A covered set injected everywhere (keeps unit tests independent from the
# real manifests directory).
COVERED = frozenset({"aave-v3", "compound-v3", "spark"})


def make_pool(**overrides):
    """A raw DeFiLlama pool dict that passes every default gate."""
    pool = {
        "pool": "uuid-default",
        "project": "newlend-proto",
        "chain": "Ethereum",
        "symbol": "USDC",
        "tvlUsd": 10_000_000.0,
        "apy": 5.0,
        "listedAt": NOW - 365 * DAY,  # ~1 year old
    }
    pool.update(overrides)
    return pool


def fake_fetch(pools):
    return lambda: pools


def raising_fetch():
    raise ConnectionError("ProxyError 403: egress to yields.llama.fi blocked")


def discover(pools, gates=None, covered=COVERED):
    return run_discovery(
        fetch_fn=fake_fetch(pools), gates=gates, covered_protocols=covered, now_ts=NOW
    )


# ─── Happy path & report schema ───────────────────────────────────────────────


class TestHappyPath(unittest.TestCase):
    def test_candidate_passes_all_gates(self):
        report = discover([make_pool()])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["candidates"]), 1)
        c = report["candidates"][0]
        self.assertEqual(c["pool_id"], "uuid-default")
        self.assertEqual(c["protocol"], "newlend-proto")
        self.assertEqual(c["chain"], "Ethereum")
        self.assertEqual(c["symbol"], "USDC")
        self.assertEqual(c["apy_pct"], 5.0)
        self.assertEqual(c["tvl_usd"], 10_000_000.0)
        self.assertEqual(c["age_days"], 365)
        self.assertEqual(
            c["gates_passed"], ["tvl", "age", "stable", "apy", "not_covered"]
        )
        self.assertEqual(c["gates_unknown"], [])

    def test_suggested_tier_is_candidate_never_a_real_tier(self):
        c = discover([make_pool()])["candidates"][0]
        self.assertEqual(c["suggested_tier"], "candidate")
        self.assertNotIn(c["suggested_tier"], ("T1", "T2", "T3"))

    def test_report_schema_keys(self):
        report = discover([make_pool()])
        for key in (
            "generated_at", "source", "gates", "scanned_pools", "candidates",
            "rejected_count", "status", "error", "advisory",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["source"], "adapter_sdk.discovery")
        for gate_key in (
            "min_tvl_usd", "min_age_days", "stable_only", "max_apy_pct",
            "max_candidates",
        ):
            self.assertIn(gate_key, report["gates"])

    def test_rejected_count(self):
        pools = [make_pool(), make_pool(pool="u2", tvlUsd=1.0), "not-a-dict"]
        report = discover(pools)
        self.assertEqual(report["scanned_pools"], 3)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["rejected_count"], 2)


# ─── TVL gate ─────────────────────────────────────────────────────────────────


class TestTvlGate(unittest.TestCase):
    def test_below_min_rejected(self):
        report = discover([make_pool(tvlUsd=4_999_999.0)])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["status"], "degraded")

    def test_exactly_min_passes(self):
        report = discover([make_pool(tvlUsd=5_000_000.0)])
        self.assertEqual(len(report["candidates"]), 1)

    def test_missing_tvl_rejected(self):
        pool = make_pool()
        del pool["tvlUsd"]
        self.assertEqual(discover([pool])["candidates"], [])

    def test_custom_min_tvl(self):
        gates = GateConfig(min_tvl_usd=20_000_000.0)
        report = discover([make_pool(tvlUsd=10_000_000.0)], gates=gates)
        self.assertEqual(report["candidates"], [])
        report = discover([make_pool(tvlUsd=25_000_000.0)], gates=gates)
        self.assertEqual(len(report["candidates"]), 1)


# ─── Age gate (incl. honest age_unknown) ─────────────────────────────────────


class TestAgeGate(unittest.TestCase):
    def test_old_pool_passes_with_age_days(self):
        c = discover([make_pool(listedAt=NOW - 200 * DAY)])["candidates"][0]
        self.assertEqual(c["age_days"], 200)
        self.assertIn("age", c["gates_passed"])

    def test_young_pool_rejected(self):
        report = discover([make_pool(listedAt=NOW - 30 * DAY)])
        self.assertEqual(report["candidates"], [])

    def test_age_unknown_flagged_but_kept(self):
        # No listedAt/inception in the data: the candidate is NOT silently
        # dropped — it is kept with age_days=None and an explicit
        # gates_unknown=["age"] flag for the human reviewer.
        pool = make_pool()
        del pool["listedAt"]
        report = discover([pool])
        self.assertEqual(len(report["candidates"]), 1)
        c = report["candidates"][0]
        self.assertIsNone(c["age_days"])
        self.assertEqual(c["gates_unknown"], ["age"])
        self.assertNotIn("age", c["gates_passed"])

    def test_inception_field_used_when_listed_at_missing(self):
        pool = make_pool(inception=NOW - 300 * DAY)
        del pool["listedAt"]
        c = discover([pool])["candidates"][0]
        self.assertEqual(c["age_days"], 300)
        self.assertIn("age", c["gates_passed"])

    def test_pool_age_days_garbage_is_none(self):
        self.assertIsNone(pool_age_days({"listedAt": "yesterday"}, NOW))
        self.assertIsNone(pool_age_days({"listedAt": True}, NOW))
        self.assertIsNone(pool_age_days({}, NOW))
        # Future timestamp (negative age) is unusable, not negative age.
        self.assertIsNone(pool_age_days({"listedAt": NOW + DAY}, NOW))


# ─── Stablecoin gate ──────────────────────────────────────────────────────────


class TestStableGate(unittest.TestCase):
    def test_non_stable_symbol_rejected(self):
        report = discover([make_pool(symbol="WETH")])
        self.assertEqual(report["candidates"], [])

    def test_multi_leg_stable_symbol_passes(self):
        c = discover([make_pool(symbol="DAI-USDC-USDT")])["candidates"][0]
        self.assertIn("stable", c["gates_passed"])

    def test_mixed_leg_symbol_rejected(self):
        report = discover([make_pool(symbol="USDC-WETH")])
        self.assertEqual(report["candidates"], [])

    def test_stable_only_disabled_allows_non_stable(self):
        gates = GateConfig(stable_only=False)
        report = discover([make_pool(symbol="WETH")], gates=gates)
        self.assertEqual(len(report["candidates"]), 1)
        c = report["candidates"][0]
        self.assertNotIn("stable", c["gates_passed"])


# ─── APY sanity gate ──────────────────────────────────────────────────────────


class TestApyGate(unittest.TestCase):
    def test_zero_apy_rejected(self):
        self.assertEqual(discover([make_pool(apy=0.0)])["candidates"], [])

    def test_negative_apy_rejected(self):
        self.assertEqual(discover([make_pool(apy=-1.0)])["candidates"], [])

    def test_above_max_rejected(self):
        self.assertEqual(discover([make_pool(apy=30.01)])["candidates"], [])

    def test_exactly_max_passes(self):
        report = discover([make_pool(apy=30.0)])
        self.assertEqual(len(report["candidates"]), 1)

    def test_missing_apy_rejected(self):
        pool = make_pool()
        del pool["apy"]
        self.assertEqual(discover([pool])["candidates"], [])


# ─── Covered-protocol exclusion ───────────────────────────────────────────────


class TestCoveredExclusion(unittest.TestCase):
    def test_covered_protocol_excluded(self):
        report = discover([make_pool(project="aave-v3")])
        self.assertEqual(report["candidates"], [])

    def test_covered_substring_match(self):
        # Feed convention: slug "spark" covers project "sparklend".
        report = discover([make_pool(project="sparklend")])
        self.assertEqual(report["candidates"], [])
        self.assertTrue(is_covered_protocol("sparklend", COVERED))
        self.assertFalse(is_covered_protocol("newlend-proto", COVERED))

    def test_default_covered_includes_file_adapters_and_manifests(self):
        covered = covered_protocol_slugs()
        for slug in (
            "aave-v3", "compound-v3", "morpho-blue", "euler-v2",
            "maple", "yearn-finance",
        ):
            self.assertIn(slug, covered)
        # Real SDK manifests: spark.yaml, fluid.yaml, curve_3pool.json.
        for slug in ("spark", "fluid-lending", "curve-dex"):
            self.assertIn(slug, covered)


# ─── Dedup / ranking / cap ────────────────────────────────────────────────────


class TestDedupRankingCap(unittest.TestCase):
    def test_dedup_by_pool_id(self):
        pools = [make_pool(pool="same-id"), make_pool(pool="same-id", apy=6.0)]
        report = discover(pools)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["apy_pct"], 5.0)  # first wins

    def test_ranked_by_tvl_desc(self):
        pools = [
            make_pool(pool="small", tvlUsd=6_000_000.0),
            make_pool(pool="big", tvlUsd=60_000_000.0),
            make_pool(pool="mid", tvlUsd=20_000_000.0),
        ]
        ids = [c["pool_id"] for c in discover(pools)["candidates"]]
        self.assertEqual(ids, ["big", "mid", "small"])

    def test_max_candidates_cap(self):
        pools = [
            make_pool(pool=f"p{i}", tvlUsd=5_000_000.0 + i) for i in range(10)
        ]
        gates = GateConfig(max_candidates=3)
        report = discover(pools, gates=gates)
        self.assertEqual(len(report["candidates"]), 3)
        # The 3 biggest TVLs survive.
        self.assertEqual(
            [c["pool_id"] for c in report["candidates"]], ["p9", "p8", "p7"]
        )
        self.assertEqual(report["rejected_count"], 7)

    def test_synthetic_pool_id_when_uuid_missing(self):
        pool = make_pool()
        del pool["pool"]
        c = discover([pool])["candidates"][0]
        self.assertEqual(c["pool_id"], "newlend-proto-usdc-ethereum")


# ─── Honest degradation ───────────────────────────────────────────────────────


class TestDegradation(unittest.TestCase):
    def test_raising_fetch_is_status_error_not_exception(self):
        report = run_discovery(
            fetch_fn=raising_fetch, covered_protocols=COVERED, now_ts=NOW
        )
        self.assertEqual(report["status"], "error")
        self.assertIn("ProxyError 403", report["error"])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["scanned_pools"], 0)

    def test_fetch_returning_non_list_is_error(self):
        report = run_discovery(
            fetch_fn=lambda: {"oops": True}, covered_protocols=COVERED, now_ts=NOW
        )
        self.assertEqual(report["status"], "error")
        self.assertIn("expected list", report["error"])

    def test_empty_pool_list_is_degraded(self):
        report = discover([])
        self.assertEqual(report["status"], "degraded")
        self.assertIsNone(report["error"])

    def test_no_candidates_is_degraded(self):
        report = discover([make_pool(tvlUsd=1.0)])
        self.assertEqual(report["status"], "degraded")

    def test_extract_pools_envelope(self):
        self.assertEqual(
            extract_pools({"status": "success", "data": [{"a": 1}]}), [{"a": 1}]
        )
        with self.assertRaises(DiscoveryError):
            extract_pools({"status": "error"})
        with self.assertRaises(DiscoveryError):
            extract_pools({"status": "success", "data": "nope"})
        with self.assertRaises(DiscoveryError):
            extract_pools(["bare list is not the envelope"])

    def test_evaluate_pool_garbage_input(self):
        gates = GateConfig()
        self.assertIsNone(evaluate_pool(None, gates, COVERED, NOW))
        self.assertIsNone(evaluate_pool("x", gates, COVERED, NOW))
        self.assertIsNone(evaluate_pool({}, gates, COVERED, NOW))


# ─── Atomic write ─────────────────────────────────────────────────────────────


class TestAtomicWrite(unittest.TestCase):
    def test_write_and_no_tmp_leftover(self):
        report = discover([make_pool()])
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "sub" / "candidate_registry.json"
            write_report_atomic(report, out)
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["status"], "ok")
            leftovers = [
                p for p in Path(tmpdir).rglob("*") if p.name.endswith(".tmp")
            ]
            self.assertEqual(leftovers, [])


# ─── CLI (subprocess, offline via --pools-file) ───────────────────────────────


def run_cli(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "spa_core.adapter_sdk.discovery", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def _pools_file(self, pools):
        path = self.tmp / "pools.json"
        path.write_text(
            json.dumps({"status": "success", "data": pools}), encoding="utf-8"
        )
        return str(path)

    def _fresh_pool(self):
        # Real wall-clock listedAt: the CLI uses time.time() for age.
        import time as _time

        return make_pool(listedAt=_time.time() - 400 * DAY)

    def test_exit_0_ok_with_candidates(self):
        proc = run_cli("--pools-file", self._pools_file([self._fresh_pool()]), "--no-write")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("status=ok", proc.stdout)
        self.assertIn("ADVISORY", proc.stdout)

    def test_exit_1_degraded_when_no_candidates(self):
        proc = run_cli("--pools-file", self._pools_file([]), "--no-write")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("status=degraded", proc.stdout)

    def test_exit_2_error_on_unreadable_source(self):
        proc = run_cli(
            "--pools-file", str(self.tmp / "does_not_exist.json"), "--no-write"
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("status=error", proc.stdout)

    def test_no_write_creates_no_file(self):
        out = self.tmp / "report.json"
        proc = run_cli(
            "--pools-file", self._pools_file([self._fresh_pool()]),
            "--no-write", "--out", str(out),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(out.exists())

    def test_writes_valid_report(self):
        out = self.tmp / "report.json"
        proc = run_cli(
            "--pools-file", self._pools_file([self._fresh_pool()]),
            "--out", str(out),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["suggested_tier"], "candidate")
        leftovers = [p for p in self.tmp.rglob("*") if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_min_tvl_option_filters(self):
        pool = self._fresh_pool()
        pool["tvlUsd"] = 6_000_000.0
        proc = run_cli(
            "--pools-file", self._pools_file([pool]),
            "--min-tvl", "50000000", "--no-write",
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("status=degraded", proc.stdout)

    def test_max_candidates_option_caps(self):
        pools = []
        for i in range(5):
            p = self._fresh_pool()
            p["pool"] = f"cli-p{i}"
            pools.append(p)
        out = self.tmp / "capped.json"
        proc = run_cli(
            "--pools-file", self._pools_file(pools),
            "--max-candidates", "2", "--out", str(out),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(report["candidates"]), 2)


# ─── Constitution: no LLM SDK imports in the new module ───────────────────────


class TestNoLlmImports(unittest.TestCase):
    def test_discovery_module_is_llm_free(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports

        source = (REPO_ROOT / "spa_core" / "adapter_sdk" / "discovery.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(find_forbidden_imports(source, "discovery.py"), [])


if __name__ == "__main__":
    unittest.main()
