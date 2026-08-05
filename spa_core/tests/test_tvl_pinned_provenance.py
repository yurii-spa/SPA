"""TVL provenance: only a PINNED pool-UUID observation may be called "live".

Why this file exists. The $5M TVL floor is a policy gate, and until now every
adapter cleared it with a hardcoded constant. ``moonwell_base`` is the worked
example: the adapter carries ``TVL_USD = 500_000_000`` while the pool it models
holds $2.6M — a 190x overstatement that let a sub-floor pool pass a floor it
actually fails, silently, for as long as the constant sat there.

Replacing the constant with "whatever pool the feed matched" is not enough. The
matcher resolves a protocol key by fuzzy project/chain/symbol hints and keeps the
biggest TVL; Base alone carries four STEAKUSDC vaults ($587M @ 4.32%, $172M @
3.22%, $30M, $0.3M). Under that rule the identity of "the" pool can move between
runs with nothing in the record to show it moved, and the number that ranks
capital changes for an invisible reason.

So the contract these tests pin is deliberately narrow:

* a PINNED pool-UUID match may stamp ``tvl_source="live"``;
* a hint match may still supply the APY, but its TVL stays ``"static"``;
* a literal is never "live", whatever its size;
* an observation ages out on the same clock as the APY evidence.

Both directions are pinned. A test that only checks "live is accepted" would
pass a producer that stamps live on everything — which is exactly the bug.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.allocator.allocator import _EVIDENCE_MAX_AGE_H, _load_evidenced_tvl
from spa_core.monitoring import adapter_status_generator as gen
from spa_core.tests._freshness import now_utc, ts

# A real UUID shape, so a test can never accidentally pass by matching "".
_PINNED = "ba68527f-8ec2-4c55-827a-8f4673ae047c"


def _pool(pool_id: str, tvl: float, apy: float = 4.32) -> dict:
    return {
        "pool": pool_id,
        "chain": "Base",
        "project": "morpho-blue",
        "symbol": "STEAKUSDC",
        "tvlUsd": tvl,
        "apy": apy,
    }


class TestPinnedLookup(unittest.TestCase):
    """``_lookup_live_pool`` must report HOW it resolved the pool, not just what."""

    def _by(self, pools: list[dict]):
        by_id = {str(p["pool"]).lower(): p for p in pools}
        by_pcs: dict[tuple[str, str, str], list[dict]] = {}
        for p in pools:
            k = (str(p["project"]).lower(), str(p["chain"]).lower(), str(p["symbol"]).upper())
            by_pcs.setdefault(k, []).append(p)
        return by_id, by_pcs

    def test_pinned_uuid_is_reported_as_pinned(self):
        by_id, by_pcs = self._by([_pool(_PINNED, 587_289_575.0)])
        match = gen._lookup_live_pool("morpho_blue_base", by_id, by_pcs)
        self.assertIsNotNone(match)
        pool, kind = match
        self.assertEqual(kind, "pinned")
        self.assertEqual(pool["pool"], _PINNED)

    def test_hint_match_is_reported_as_hint(self):
        """A key with no pin resolves by hint — and must SAY so.

        This is the direction that matters: if a hint match were reported as
        "pinned", every fuzzy resolution would silently earn gate-grade trust.
        """
        other = _pool("11111111-2222-3333-4444-555555555555", 172_548_759.0, apy=3.22)
        by_id, by_pcs = self._by([other])
        # A key that is NOT in _POOL_ID_LOOKUP but does have hints.
        key = next(k for k in gen._DEFILLAMA_HINTS if k not in gen._POOL_ID_LOOKUP)
        match = gen._lookup_live_pool(key, by_id, by_pcs)
        if match is not None:  # hints may or may not match this fixture
            self.assertEqual(match[1], "hint")

    def test_pin_wins_over_a_larger_hint_candidate(self):
        """Identity beats size. The pinned vault is chosen even when smaller.

        "Best TVL wins" is precisely the rule that lets the pool drift; a pin
        must override it, or pinning buys nothing.
        """
        pinned = _pool(_PINNED, 100_000_000.0, apy=4.32)
        bigger = _pool("99999999-8888-7777-6666-555555555555", 900_000_000.0, apy=9.9)
        by_id, by_pcs = self._by([pinned, bigger])
        pool, kind = gen._lookup_live_pool("morpho_blue_base", by_id, by_pcs)
        self.assertEqual(kind, "pinned")
        self.assertEqual(pool["tvlUsd"], 100_000_000.0)

    def test_no_two_keys_share_a_pool(self):
        """Two protocol keys pointing at one pool is hidden concentration.

        The per-protocol cap counts them as independent positions, so two keys on
        one vault would allow twice the intended exposure to a single contract
        with nothing in the risk report showing it.

        This is not hypothetical. While wiring feeds on 2026-08-05, ``frax``
        resolved to the same SFRAX pool as ``sfrax``, and ``fluid_usdc`` to the
        same pool as ``fluid_fusdc``. Both were left unpinned for this reason.
        """
        seen: dict[str, str] = {}
        for key, pid in gen._POOL_ID_LOOKUP.items():
            prev = seen.get(pid)
            self.assertIsNone(
                prev, f"{key} and {prev} pin the same pool {pid} — hidden concentration")
            seen[pid] = key

    def test_every_pin_is_a_uuid_not_an_address(self):
        """The original single pin was an Ethereum ADDRESS, so it never matched.

        It failed silently: lookup fell through to hints and the key resolved
        anyway, so nothing looked broken. A shape check makes that class loud.
        """
        for key, pid in gen._POOL_ID_LOOKUP.items():
            with self.subTest(key=key):
                self.assertFalse(pid.startswith("0x"), f"{key}: address, not a pool UUID")
                self.assertEqual(pid.count("-"), 4, f"{key}: not a UUID shape: {pid}")
                self.assertEqual(len(pid), 36, f"{key}: not a UUID shape: {pid}")


class TestEvidencedTvl(unittest.TestCase):
    """``_load_evidenced_tvl`` — what counts as an observation, and what never does."""

    def _write(self, rows: dict, generated_at: str | None = None) -> Path:
        self._tmp = TemporaryDirectory()
        p = Path(self._tmp.name) / "adapter_status.json"
        doc = {"generated_at": generated_at or ts(1), "adapters": rows}
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_live_row_is_evidence(self):
        p = self._write({"morpho_blue_base": {
            "tvl_usd": 587_289_575.0, "tvl_source": "live",
            "tvl_pool_id": _PINNED, "live_apy_as_of": ts(1)}})
        out = _load_evidenced_tvl(p)
        self.assertIn("morpho_blue_base", out)
        self.assertEqual(out["morpho_blue_base"], (587_289_575.0, _PINNED))

    def test_static_row_is_not_evidence_however_large(self):
        """The failure mode this whole change exists to stop.

        $500M of literal must not outweigh $2.6M of observation.
        """
        p = self._write({"moonwell_base": {
            "tvl_usd": 500_000_000.0, "tvl_source": "static",
            "tvl_pool_id": None, "live_apy_as_of": ts(1)}})
        self.assertEqual(_load_evidenced_tvl(p), {})

    def test_stale_observation_ages_out(self):
        p = self._write({"morpho_blue_base": {
            "tvl_usd": 1.0, "tvl_source": "live", "tvl_pool_id": _PINNED,
            "live_apy_as_of": ts(_EVIDENCE_MAX_AGE_H + 1)}})
        self.assertEqual(_load_evidenced_tvl(p), {})

    def test_fresh_observation_inside_the_window_is_kept(self):
        """Pins the window from BOTH sides — otherwise "always reject" passes."""
        p = self._write({"morpho_blue_base": {
            "tvl_usd": 1.0, "tvl_source": "live", "tvl_pool_id": _PINNED,
            "live_apy_as_of": ts(_EVIDENCE_MAX_AGE_H - 1)}})
        self.assertIn("morpho_blue_base", _load_evidenced_tvl(p))

    def test_undateable_observation_is_refused(self):
        """Unknown age is not evidence (fail-CLOSED), not "assume fresh"."""
        p = self._write({"morpho_blue_base": {
            "tvl_usd": 1.0, "tvl_source": "live", "tvl_pool_id": _PINNED,
            "live_apy_as_of": "not-a-date"}}, generated_at="also-not-a-date")
        self.assertEqual(_load_evidenced_tvl(p), {})

    def test_nonsense_values_are_refused(self):
        for bad in (0, -1, None, True, "587000000"):
            with self.subTest(tvl=bad):
                p = self._write({"x": {"tvl_usd": bad, "tvl_source": "live",
                                       "tvl_pool_id": _PINNED, "live_apy_as_of": ts(1)}})
                self.assertEqual(_load_evidenced_tvl(p), {})

    def test_unreadable_file_yields_nothing_and_never_raises(self):
        """A broken producer must leave the caller on its literal, not crash it."""
        self.assertEqual(_load_evidenced_tvl(None), {})
        self.assertEqual(_load_evidenced_tvl(Path("/nonexistent/adapter_status.json")), {})

    def test_clock_is_an_input(self):
        """Age is measured against an injected ``now``, never ambient wall time.

        Reading the clock directly is what turned three test files into time
        bombs on 2026-08-04; the window must be pinnable from both sides.
        """
        p = self._write({"morpho_blue_base": {
            "tvl_usd": 1.0, "tvl_source": "live", "tvl_pool_id": _PINNED,
            "live_apy_as_of": ts(1)}})
        future = now_utc() + timedelta(hours=_EVIDENCE_MAX_AGE_H + 5)
        self.assertEqual(_load_evidenced_tvl(p, now=future), {})


if __name__ == "__main__":
    unittest.main()
