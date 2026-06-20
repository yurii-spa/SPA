"""Tests for the Sky/sUSDS read-only feed (MP-202, Sprint v4.25 / SPA-V425).

Covers robust pool discovery (exact pool_id, fallback by project+symbol among
stablecoin pools, ambiguity → honest None), both read surfaces (decimal vs
percentage + liveness filters), cache TTL, network-error tolerance, the
HARD allocation gate (weight always 0.0 / eligible always False until MP-017),
atomic snapshot persistence with history rotation, and the CLI.

No real network: ``requests.get`` is patched throughout; persistence goes to a
tempdir only. pytest is not installed in this repo — plain ``unittest``.

Run:  python3 -m unittest spa_core.tests.test_sky_susds_feed -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters import sky_susds_feed as mod  # noqa: E402
from spa_core.adapters.sky_susds_feed import (  # noqa: E402
    ALLOCATION_WEIGHT,
    APY_SANITY_MAX,
    ATTESTATION_FILENAME,
    GATE_REASON,
    HISTORY_MAX,
    MIN_TVL_USD,
    STATUS_FILENAME,
    SkySUSDSFeed,
    main,
)


# ─── Fixtures / helpers ──────────────────────────────────────────────────────

def _pool(project="sky-lending", symbol="SUSDS", chain="Ethereum",
          apy=6.5, tvl=2_000_000_000.0, pool_id="uuid-susds",
          stablecoin=True):
    return {"project": project, "symbol": symbol, "chain": chain,
            "apy": apy, "tvlUsd": tvl, "pool": pool_id,
            "stablecoin": stablecoin}


def _mock_get(pools, status="success"):
    """Patch для requests.get, отдающего данный payload пулов."""
    resp = mock.MagicMock()
    resp.json.return_value = {"status": status, "data": pools}
    resp.raise_for_status.return_value = None
    return mock.patch(
        "spa_core.adapters.sky_susds_feed.requests.get", return_value=resp
    )


def _mock_get_raw(payload):
    """Patch для requests.get с произвольным (в т.ч. мусорным) payload."""
    resp = mock.MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return mock.patch(
        "spa_core.adapters.sky_susds_feed.requests.get", return_value=resp
    )


def _feed(**kw):
    kw.setdefault("enabled", True)
    kw.setdefault("cache_ttl", 300)
    kw.setdefault("pool_id", None)
    return SkySUSDSFeed(**kw)


class _TmpDirCase(unittest.TestCase):
    """База: tempdir под data_dir, никаких записей в реальный data/."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write_attestation(self, obj, raw: str | None = None):
        path = self.data_dir / ATTESTATION_FILENAME
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        else:
            path.write_text(json.dumps(obj), encoding="utf-8")


# ─── Pool discovery ──────────────────────────────────────────────────────────

class TestPoolDiscovery(unittest.TestCase):
    def test_exact_pool_id_match(self):
        pools = [_pool(pool_id="uuid-a"), _pool(pool_id="uuid-b")]
        with _mock_get(pools):
            out = _feed(pool_id="uuid-b").find_pool()
        self.assertIsNotNone(out)
        self.assertEqual(out["pool"], "uuid-b")

    def test_exact_pool_id_disambiguates_multiple_candidates(self):
        # >1 кандидатов, но точный pool_id снимает неоднозначность.
        pools = [_pool(pool_id="uuid-a"), _pool(pool_id="uuid-b")]
        with _mock_get(pools):
            self.assertIsNone(_feed().fetch_pool())  # без pool_id — None
        with _mock_get(pools):
            out = _feed(pool_id="uuid-a").fetch_pool()
        self.assertEqual(out["pool_id"], "uuid-a")

    def test_pool_id_not_found_falls_back_to_search(self):
        pools = [_pool(pool_id="uuid-real")]
        with _mock_get(pools):
            out = _feed(pool_id="uuid-stale").find_pool()
        self.assertIsNotNone(out)
        self.assertEqual(out["pool"], "uuid-real")

    def test_fallback_single_candidate_sky_lending(self):
        with _mock_get([_pool(project="sky-lending")]):
            self.assertIsNotNone(_feed().find_pool())

    def test_fallback_project_sky_also_matches(self):
        with _mock_get([_pool(project="sky")]):
            self.assertIsNotNone(_feed().find_pool())

    def test_fallback_project_case_insensitive(self):
        with _mock_get([_pool(project="Sky-Lending")]):
            self.assertIsNotNone(_feed().find_pool())

    def test_zero_candidates_returns_none(self):
        with _mock_get([_pool(project="aave-v3", symbol="USDC")]):
            self.assertIsNone(_feed().find_pool())

    def test_multiple_candidates_without_pool_id_returns_none(self):
        pools = [_pool(pool_id="uuid-a"), _pool(pool_id="uuid-b")]
        with _mock_get(pools):
            self.assertIsNone(_feed().find_pool())

    def test_non_stablecoin_pool_excluded(self):
        with _mock_get([_pool(stablecoin=False)]):
            self.assertIsNone(_feed().find_pool())

    def test_stablecoin_must_be_literal_true(self):
        with _mock_get([_pool(stablecoin="true")]):
            self.assertIsNone(_feed().find_pool())

    def test_wrong_symbol_excluded(self):
        with _mock_get([_pool(symbol="SUSDE")]):
            self.assertIsNone(_feed().find_pool())

    def test_wrong_chain_excluded(self):
        with _mock_get([_pool(chain="Base")]):
            self.assertIsNone(_feed().find_pool())

    def test_garbage_status_returns_none(self):
        with _mock_get([_pool()], status="error"):
            self.assertIsNone(_feed().find_pool())

    def test_payload_not_dict_returns_none(self):
        with _mock_get_raw(["not", "a", "dict"]):
            self.assertIsNone(_feed().find_pool())

    def test_data_not_list_returns_none(self):
        with _mock_get_raw({"status": "success", "data": {"oops": 1}}):
            self.assertIsNone(_feed().find_pool())

    def test_non_dict_pool_entries_tolerated(self):
        pools = ["garbage", 42, None, _pool()]
        with _mock_get(pools):
            self.assertIsNotNone(_feed().find_pool())


# ─── Read surfaces: get_* (decimal) vs fetch_* (percentage + liveness) ──────

class TestReadSurfaces(unittest.TestCase):
    def test_get_apy_returns_decimal(self):
        with _mock_get([_pool(apy=6.5)]):
            self.assertAlmostEqual(_feed().get_apy(), 0.065)

    def test_fetch_apy_returns_percentage(self):
        with _mock_get([_pool(apy=6.5)]):
            self.assertAlmostEqual(_feed().fetch_apy(), 6.5)

    def test_get_tvl_returns_usd(self):
        with _mock_get([_pool(tvl=2_000_000_000.0)]):
            self.assertEqual(_feed().get_tvl(), 2_000_000_000.0)

    def test_fetch_tvl_returns_usd(self):
        with _mock_get([_pool(tvl=2_000_000_000.0)]):
            self.assertEqual(_feed().fetch_tvl(), 2_000_000_000.0)

    def test_fetch_pool_shape(self):
        with _mock_get([_pool(pool_id="uuid-x")]):
            out = _feed().fetch_pool()
        self.assertEqual(set(out), {"apy", "tvl", "pool_id"})
        self.assertEqual(out["pool_id"], "uuid-x")

    def test_tvl_floor_99999_rejected(self):
        with _mock_get([_pool(tvl=99_999.0)]):
            self.assertIsNone(_feed().fetch_apy())

    def test_tvl_floor_100000_passes(self):
        with _mock_get([_pool(tvl=100_000.0)]):
            self.assertIsNotNone(_feed().fetch_apy())

    def test_get_apy_has_no_tvl_floor(self):
        # legacy decimal-поверхность без liveness-фильтров (parity defillama_feed)
        with _mock_get([_pool(apy=6.5, tvl=50_000.0)]):
            self.assertAlmostEqual(_feed().get_apy(), 0.065)

    def test_apy_negative_rejected(self):
        with _mock_get([_pool(apy=-0.1)]):
            self.assertIsNone(_feed().fetch_apy())

    def test_apy_above_200_rejected(self):
        with _mock_get([_pool(apy=200.1)]):
            self.assertIsNone(_feed().fetch_apy())

    def test_apy_exactly_zero_passes(self):
        with _mock_get([_pool(apy=0.0)]):
            self.assertEqual(_feed().fetch_apy(), 0.0)

    def test_apy_exactly_200_passes(self):
        with _mock_get([_pool(apy=200.0)]):
            self.assertEqual(_feed().fetch_apy(), 200.0)

    def test_apy_missing_returns_none_both_surfaces(self):
        pool = _pool()
        del pool["apy"]
        with _mock_get([pool]):
            f = _feed()
            self.assertIsNone(f.get_apy())
            self.assertIsNone(f.fetch_apy())

    def test_apy_non_numeric_returns_none(self):
        with _mock_get([_pool(apy="6.5%")]):
            self.assertIsNone(_feed().fetch_apy())

    def test_apy_bool_is_not_a_number(self):
        with _mock_get([_pool(apy=True)]):
            self.assertIsNone(_feed().fetch_apy())

    def test_constants_match_defillama_conventions(self):
        self.assertEqual(MIN_TVL_USD, 100_000.0)
        self.assertEqual(APY_SANITY_MAX, 200.0)


# ─── Cache TTL ───────────────────────────────────────────────────────────────

class TestCacheTTL(unittest.TestCase):
    def test_second_call_within_ttl_does_not_hit_network(self):
        with _mock_get([_pool()]) as m:
            f = _feed(cache_ttl=300)
            f.fetch_apy()
            f.fetch_apy()
        self.assertEqual(m.call_count, 1)

    def test_expired_ttl_refetches(self):
        with _mock_get([_pool()]) as m:
            f = _feed(cache_ttl=300)
            f.fetch_apy()
            f._cache_ts -= 301  # просрочить кэш
            f.fetch_apy()
        self.assertEqual(m.call_count, 2)

    def test_disabled_feed_returns_none_without_network(self):
        with _mock_get([_pool()]) as m:
            f = _feed(enabled=False)
            self.assertIsNone(f.fetch_apy())
            self.assertIsNone(f.get_apy())
        self.assertEqual(m.call_count, 0)


# ─── Network errors → None, никогда исключений ──────────────────────────────

class TestNetworkErrors(unittest.TestCase):
    def _raising(self, exc):
        return mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get", side_effect=exc
        )

    def test_connection_error_returns_none(self):
        with self._raising(ConnectionError("no route")):
            f = _feed()
            self.assertIsNone(f.fetch_apy())
            self.assertIsNone(f.get_apy())
            self.assertIsNone(f.get_tvl())

    def test_timeout_returns_none(self):
        with self._raising(TimeoutError("slow")):
            self.assertIsNone(_feed().fetch_pool())

    def test_http_error_via_raise_for_status(self):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("503")
        with mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get", return_value=resp
        ):
            self.assertIsNone(_feed().fetch_apy())

    def test_json_decode_error_returns_none(self):
        resp = mock.MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("bad json")
        with mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get", return_value=resp
        ):
            self.assertIsNone(_feed().fetch_apy())


# ─── Allocation gate: HARD 0% until MP-017 ───────────────────────────────────

class TestAllocationGate(_TmpDirCase):
    def _gated_feed(self):
        return _feed(data_dir=self.data_dir)

    def test_allocation_weight_constant_is_zero(self):
        self.assertEqual(ALLOCATION_WEIGHT, 0.0)

    def test_allocation_weight_always_zero(self):
        self.assertEqual(self._gated_feed().allocation_weight(), 0.0)

    def test_eligible_false_without_attestation(self):
        f = self._gated_feed()
        self.assertFalse(f.eligible_for_allocation())
        self.assertFalse(f.gsm_attestation_verified())

    def test_gate_reason_mentions_mp017(self):
        self.assertIn("MP-017", GATE_REASON)
        self.assertEqual(self._gated_feed().gate_status()["reason"], GATE_REASON)

    def test_garbage_attestation_file_is_false(self):
        self._write_attestation(None, raw="{not json!!!")
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_attestation_list_not_dict_is_false(self):
        self._write_attestation(["verified", True])
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_verified_string_true_not_accepted(self):
        self._write_attestation(
            {"verified": "true", "verified_at": "2026-06-11",
             "pause_delay_hours": 48}
        )
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_verified_1_not_accepted(self):
        self._write_attestation(
            {"verified": 1, "verified_at": "2026-06-11",
             "pause_delay_hours": 48}
        )
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_missing_verified_at_is_false(self):
        self._write_attestation({"verified": True, "pause_delay_hours": 48})
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_pause_delay_47_is_false(self):
        self._write_attestation(
            {"verified": True, "verified_at": "2026-06-11",
             "pause_delay_hours": 47}
        )
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_pause_delay_string_not_accepted(self):
        self._write_attestation(
            {"verified": True, "verified_at": "2026-06-11",
             "pause_delay_hours": "48"}
        )
        self.assertFalse(self._gated_feed().gsm_attestation_verified())

    def test_valid_attestation_verifies_but_gate_stays_closed(self):
        # Ключевой инвариант MP-202: даже валидная аттестация НЕ открывает гейт.
        self._write_attestation(
            {"verified": True, "verified_at": "2026-06-11T00:00:00Z",
             "pause_delay_hours": 48}
        )
        f = self._gated_feed()
        self.assertTrue(f.gsm_attestation_verified())
        self.assertEqual(f.allocation_weight(), 0.0)
        self.assertFalse(f.eligible_for_allocation())
        gate = f.gate_status()
        self.assertFalse(gate["eligible_for_allocation"])
        self.assertEqual(gate["allocation_weight"], 0.0)
        self.assertTrue(gate["gsm_attestation_verified"])

    def test_gate_independent_of_live_feed(self):
        # Даже при живом APY гейт закрыт.
        with _mock_get([_pool(apy=6.5)]):
            f = self._gated_feed()
            self.assertAlmostEqual(f.fetch_apy(), 6.5)
            self.assertEqual(f.allocation_weight(), 0.0)
            self.assertFalse(f.eligible_for_allocation())


# ─── Persistence / snapshot ──────────────────────────────────────────────────

class TestPersistence(_TmpDirCase):
    def _run(self, write=True, pools=None):
        f = _feed(data_dir=self.data_dir)
        ctx = _mock_get(pools if pools is not None else [_pool(apy=6.5)])
        with ctx:
            return f.run(write=write)

    def test_run_writes_status_file(self):
        self._run(write=True)
        self.assertTrue((self.data_dir / STATUS_FILENAME).exists())

    def test_snapshot_schema(self):
        self._run(write=True)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        for key in ("source", "is_demo", "advisory_only", "updated_at",
                    "status", "live_data", "pool_id", "apy_pct", "apy_decimal",
                    "tvl_usd", "gate", "allocation_weight",
                    "eligible_for_allocation", "history"):
            self.assertIn(key, doc, key)
        self.assertEqual(doc["source"], "sky_susds_feed")
        self.assertFalse(doc["is_demo"])
        self.assertTrue(doc["advisory_only"])
        self.assertEqual(doc["status"], "ok")
        self.assertAlmostEqual(doc["apy_pct"], 6.5)
        self.assertAlmostEqual(doc["apy_decimal"], 0.065)
        self.assertEqual(doc["allocation_weight"], 0.0)
        self.assertFalse(doc["eligible_for_allocation"])

    def test_atomic_write_no_tmp_leftover(self):
        self._run(write=True)
        leftovers = [p for p in os.listdir(self.data_dir) if p.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_check_mode_does_not_write(self):
        self._run(write=False)
        self.assertFalse((self.data_dir / STATUS_FILENAME).exists())

    def test_offline_snapshot_is_honest_unavailable(self):
        with mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get",
            side_effect=ConnectionError("offline"),
        ):
            snap = _feed(data_dir=self.data_dir).run(write=True)
        self.assertEqual(snap["status"], "unavailable")
        self.assertIsNone(snap["apy_pct"])
        self.assertFalse(snap["live_data"])
        self.assertEqual(snap["allocation_weight"], 0.0)

    def test_broken_existing_status_file_tolerated(self):
        (self.data_dir / STATUS_FILENAME).write_text("{broken!!!", "utf-8")
        self._run(write=True)  # не должно упасть
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["history"]), 1)

    def test_history_appends_across_runs(self):
        self._run(write=True)
        self._run(write=True)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["history"]), 2)

    def test_history_rotation_exactly_500(self):
        seed = {
            "history": [
                {"ts": f"t{i}", "status": "ok", "apy_pct": 6.5, "tvl_usd": 1.0}
                for i in range(HISTORY_MAX)
            ]
        }
        (self.data_dir / STATUS_FILENAME).write_text(json.dumps(seed), "utf-8")
        snap = self._run(write=True)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["history"]), HISTORY_MAX)
        self.assertEqual(HISTORY_MAX, 500)
        # новая запись в хвосте, самая старая вытеснена
        self.assertEqual(doc["history"][-1]["ts"], snap["updated_at"])
        self.assertEqual(doc["history"][0]["ts"], "t1")

    def test_history_non_dict_entries_dropped(self):
        seed = {"history": ["junk", 42, {"ts": "t0", "status": "ok"}]}
        (self.data_dir / STATUS_FILENAME).write_text(json.dumps(seed), "utf-8")
        self._run(write=True)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["history"]), 2)  # t0 + новая

    def test_double_run_idempotent_exit_and_schema(self):
        snap1 = self._run(write=True)
        snap2 = self._run(write=True)
        self.assertEqual(snap1["status"], snap2["status"])
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(doc["status"], "ok")

    def test_summary_renders_both_states(self):
        f = _feed(data_dir=self.data_dir)
        with _mock_get([_pool(apy=6.5)]):
            ok = f.summary(f.run(write=False))
        self.assertIn("allocation_weight: 0.0", ok)
        self.assertIn("6.5000%", ok)
        with mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get",
            side_effect=ConnectionError("offline"),
        ):
            f2 = _feed(data_dir=self.data_dir)
            off = f2.summary(f2.run(write=False))
        self.assertIn("unavailable", off)
        self.assertIn("MP-017", off)


# ─── CLI ─────────────────────────────────────────────────────────────────────

class TestCLI(_TmpDirCase):
    def _offline(self):
        return mock.patch(
            "spa_core.adapters.sky_susds_feed.requests.get",
            side_effect=ConnectionError("offline"),
        )

    def test_check_exit_0_offline_and_no_write(self):
        with self._offline():
            rc = main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / STATUS_FILENAME).exists())

    def test_run_exit_0_offline_and_writes(self):
        with self._offline():
            rc = main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(doc["status"], "unavailable")

    def test_run_twice_idempotent_exit_0(self):
        with self._offline():
            self.assertEqual(main(["--run", "--data-dir", str(self.data_dir)]), 0)
            self.assertEqual(main(["--run", "--data-dir", str(self.data_dir)]), 0)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["history"]), 2)

    def test_check_exit_0_with_live_mock(self):
        with _mock_get([_pool(apy=6.5)]):
            self.assertEqual(main(["--check", "--data-dir", str(self.data_dir)]), 0)

    def test_cli_subprocess_empty_env_exit_0_no_traceback(self):
        # Пустая среда: фид выключен через env — ноль сетевых вызовов.
        env = dict(os.environ)
        env["DEFILLAMA_ENABLED"] = "false"
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.adapters.sky_susds_feed",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("unavailable", proc.stdout)


# ─── Constitution: no LLM SDK imports ────────────────────────────────────────

class TestNoLLMImports(unittest.TestCase):
    def test_module_source_has_no_llm_sdk_imports(self):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for forbidden in ("anthropic", "openai", "langchain", "litellm",
                          "google.generativeai"):
            self.assertNotIn(f"import {forbidden}", src)
            self.assertNotIn(f"from {forbidden}", src)


if __name__ == "__main__":
    unittest.main()
