#!/usr/bin/env python3
"""Tests for the aggressive-lab PINNED-POOL feed — `defi_apy["aave_v3_wsteth"]`.

WHY THIS FILE EXISTS (the measured defect, docs/AGGRESSIVE_PANEL_FEEDS.md §2):
`levered_restaking` / `leverage_loop` fall back to ``defi_apy["aave_v3_wsteth"]`` when the stETH
staking APY is missing (roster.py). That key was NEVER PRODUCED by anything — it existed only in
the feeds.py docstring. So the "fallback" was not a fallback: the book failed closed on the very
day the primary series had a hole.

This wires the key to keyless DeFiLlama yields, and it does so under ADR-064: a pool is resolved
by its PINNED UUID, never by a fuzzy project/chain/symbol "best TVL wins" match, because a gate
(and an accrual) must not rest on an identity that can drift silently between runs.

Egress is blocked in this environment (CONNECT tunnel 403), so no UUID is invented here: the pin
registry ships with ``pool_id: null`` and the feed FAILS CLOSED on an unpinned key. The tests below
pin BOTH sides — the refusal when unpinned, and the resolution when a pin is supplied.

Time is an INPUT everywhere (no wall clock, no network).

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_pinned_pool_feed.py -q
"""
from __future__ import annotations

# FROZEN-DATE-OK: injected-clock — no wall clock is consulted anywhere in this file. Every
# date is BOTH the fixture stamp and the query bound, derived from the same literal set:
# build_live_snapshot(as_of=...) is the injected clock, and history(start, end) is compared
# against chart stamps written from those same literals. The calendar cannot move this test.

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.aggressive_lab import feeds as fd

WSTETH_KEY = "aave_v3_wsteth"

# A made-up UUID used ONLY as a test fixture identity. It is deliberately NOT written into the
# shipped pin registry — inventing a live pool id is exactly what ADR-064 forbids.
FIXTURE_UUID = "00000000-0000-4000-8000-000000000001"


def _pools_payload(*, pool_id=FIXTURE_UUID, apy=3.25, project="aave-v3",
                   chain="Ethereum", symbol="WSTETH", tvl=1_234_567.0):
    return {"status": "success", "data": [
        # a decoy that a FUZZY matcher would happily take (same project/chain/symbol, bigger TVL)
        {"pool": "decoy-decoy-decoy", "project": project, "chain": chain, "symbol": symbol,
         "apy": 99.0, "tvlUsd": 9_999_999_999.0},
        {"pool": pool_id, "project": project, "chain": chain, "symbol": symbol,
         "apy": apy, "tvlUsd": tvl},
    ]}


def _chart_payload(points):
    return {"status": "success", "data": [
        {"timestamp": f"{d}T23:00:00.000Z", "apy": a} for d, a in points
    ]}


def _fetcher(pools=None, charts=None):
    pools = pools if pools is not None else _pools_payload()
    charts = charts or {}

    def _f(url):
        if url.startswith(fd.POOLS_URL):
            return pools
        for pid, payload in charts.items():
            if url.endswith(pid):
                return payload
        raise AssertionError(f"unexpected url {url}")
    return _f


def _pin_file(tmp: Path, record) -> Path:
    p = tmp / "pinned_pools.json"
    p.write_text(json.dumps({"pools": {WSTETH_KEY: record}}), encoding="utf-8")
    return p


class TestPinRegistry(unittest.TestCase):
    def test_shipped_registry_declares_the_key_and_refuses_to_invent_a_uuid(self):
        """The key is DECLARED (so the gap is named, not silent) but its pool_id is null until it
        is read off the live feed on the Mac. A shipped non-null UUID here would be a fabricated
        number (invariant 2) — nothing in this repo has ever seen the live /pools payload."""
        pins = fd.load_pinned_pools()
        self.assertIn(WSTETH_KEY, pins)
        self.assertIsNone(pins[WSTETH_KEY].get("pool_id"),
                          "a UUID must be OBSERVED on the live feed, never written from memory")

    def test_unpinned_key_fails_closed_never_falls_back_to_a_fuzzy_match(self):
        """ADR-064: no pin ⇒ no value. Crucially it must NOT silently resolve by project/chain/
        symbol — the decoy pool in the payload would otherwise supply a 99% APY."""
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(), pins={WSTETH_KEY: {"pool_id": None}})
        with self.assertRaises(InvalidDataError):
            feed.apy()

    def test_pin_from_config_file_is_what_gets_substituted(self):
        """The Mac-side operation is: read the UUID off the live feed, write it into the config.
        No code change. This is that substitution path."""
        tmp = Path(tempfile.mkdtemp(prefix="aggr_pin_"))
        path = _pin_file(tmp, {"pool_id": FIXTURE_UUID, "project": "aave-v3",
                               "chain": "Ethereum", "symbol": "WSTETH"})
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(), pins_path=path)
        self.assertAlmostEqual(feed.apy(), 0.0325, places=6)

    def test_malformed_uuid_in_config_is_refused_not_used(self):
        tmp = Path(tempfile.mkdtemp(prefix="aggr_pin_bad_"))
        path = _pin_file(tmp, {"pool_id": "not-a-uuid", "project": "aave-v3",
                               "chain": "Ethereum", "symbol": "WSTETH"})
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(), pins_path=path)
        with self.assertRaises(InvalidDataError):
            feed.apy()


class TestPinnedResolution(unittest.TestCase):
    def test_resolves_the_pinned_pool_not_the_biggest_one(self):
        """The positive control for the ADR-064 failure mode: the decoy has 8000x the TVL and a
        99% APY. A 'best TVL wins' matcher returns the decoy; a pinned matcher returns 3.25%."""
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(),
                                 pins={WSTETH_KEY: {"pool_id": FIXTURE_UUID}})
        self.assertAlmostEqual(feed.apy(), 0.0325, places=6)

    def test_identity_drift_is_refused(self):
        """The pin records chain/project/symbol alongside the UUID. If the UUID comes back
        describing a DIFFERENT pool, that is drift — refuse, do not accrue on it."""
        payload = _pools_payload(project="aave-v2", symbol="STETH")
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(pools=payload),
                                 pins={WSTETH_KEY: {"pool_id": FIXTURE_UUID, "project": "aave-v3",
                                                    "chain": "Ethereum", "symbol": "WSTETH"}})
        with self.assertRaises(InvalidDataError):
            feed.apy()

    def test_pinned_uuid_absent_from_feed_fails_closed(self):
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(),
                                 pins={WSTETH_KEY: {"pool_id": "11111111-0000-4000-8000-000000000009"}})
        with self.assertRaises(InvalidDataError):
            feed.apy()

    def test_history_is_windowed_and_dated(self):
        charts = {FIXTURE_UUID: _chart_payload([("2026-01-01", 3.0), ("2026-01-02", 3.5),
                                                ("2026-02-01", 4.0)])}
        feed = fd.PinnedPoolFeed(WSTETH_KEY, fetcher=_fetcher(charts=charts),
                                 pins={WSTETH_KEY: {"pool_id": FIXTURE_UUID}})
        hist = feed.history("2026-01-01", "2026-01-31")
        self.assertEqual(sorted(hist), ["2026-01-01", "2026-01-02"])
        self.assertAlmostEqual(hist["2026-01-02"], 0.035, places=6)


class TestSnapshotWiring(unittest.TestCase):
    """The key must actually LAND on the snapshot — that is the whole defect."""

    def test_history_snapshot_carries_the_key(self):
        f = fd.AggressiveFeeds(eth_price_series={"2026-01-01": 3000.0, "2026-01-02": 3100.0},
                               wsteth_apy_series={"2026-01-01": 0.031, "2026-01-02": 0.032},
                               enable_points=False)
        snaps = f.historical_snapshots("2026-01-01", "2026-01-02")
        self.assertEqual([s.defi_apy.get(WSTETH_KEY) for s in snaps], [0.031, 0.032])

    def test_missing_day_is_a_gap_not_a_substituted_number(self):
        f = fd.AggressiveFeeds(eth_price_series={"2026-01-01": 3000.0, "2026-01-02": 3100.0},
                               wsteth_apy_series={"2026-01-01": 0.031},
                               enable_points=False)
        snaps = f.historical_snapshots("2026-01-01", "2026-01-02")
        self.assertEqual(snaps[0].defi_apy.get(WSTETH_KEY), 0.031)
        self.assertNotIn(WSTETH_KEY, snaps[1].defi_apy)

    def test_live_snapshot_carries_the_key_from_the_live_loader(self):
        f = fd.AggressiveFeeds(enable_points=False,
                               live_loaders={"aave_v3_wsteth": lambda: 0.0299})
        snap = f.build_live_snapshot(as_of="2026-03-04")
        self.assertAlmostEqual(snap.defi_apy[WSTETH_KEY], 0.0299, places=6)

    def test_live_loader_failure_is_an_honest_gap(self):
        def _boom():
            raise InvalidDataError("no pin")
        f = fd.AggressiveFeeds(enable_points=False, live_loaders={"aave_v3_wsteth": _boom})
        snap = f.build_live_snapshot(as_of="2026-03-04")
        self.assertNotIn(WSTETH_KEY, snap.defi_apy)
        self.assertIn("defi_apy.aave_v3_wsteth", snap.gaps)


if __name__ == "__main__":
    unittest.main()
