"""Concentration the per-protocol cap cannot see, and Sky's promotion out of watch-list.

Two owner decisions of 2026-08-05, pinned so neither drifts back silently.

**Curator concentration.** ``morpho_steakhouse`` (Ethereum) and ``morpho_blue_base``
(Base) are different pools on different chains — different contracts, separately
capped, counted as independent positions. They are also the same *curator*: one
team decides which collateral each vault accepts, at what LLTV, against which
oracle. Today that is 50 % of capital under one team's judgement, and nothing in
the risk report says so. The metric is ADVISORY by decision: it measures, it does
not gate. Changing a RiskPolicy threshold needs its own ADR.

**Sky/sUSDS → T1.** Invariant 10 held Sky at 0 % pending an on-chain GSM pause
delay ≥ 48h. The condition was checkable but never checked — the producer wrote
``gsm_hours: null`` every run for as long as its RPC endpoints had been dead.
Once fixed, the delay was observed at exactly 48.00h by independent quorum, so
the condition is *met* and leaving the registry at "WL" would be a false record.
No fixed share was assigned: the allocator ranks it like anything else.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.paper_trading.concentration_analytics import curator_concentration

_REPO = Path(__file__).resolve().parents[2]
BOOK = {"pendle": 20_000.0, "maple": 20_000.0, "morpho_blue_base": 10_000.0,
        "morpho_steakhouse": 40_000.0, "aave_v3": 5_000.0}
CAP = 100_000.0


class TestCuratorConcentration(unittest.TestCase):

    def test_the_measured_reality_two_pools_one_curator(self):
        """The finding itself: 50 % under Steakhouse across two 'independent' caps."""
        res = curator_concentration(BOOK, CAP)
        self.assertEqual(res["max_curator"], "steakhouse")
        self.assertAlmostEqual(res["max_pct"], 50.0, places=3)
        self.assertEqual(res["by_curator"]["steakhouse"]["protocols"],
                         ["morpho_blue_base", "morpho_steakhouse"])

    def test_unknown_curators_are_named_not_silently_dropped(self):
        """Counting an unmapped protocol as 'no curator' would understate the number.

        A report that cannot say what it does not know is worse than no report:
        it reads as coverage.
        """
        res = curator_concentration(BOOK, CAP)
        self.assertEqual(res["unmapped"], ["aave_v3", "maple", "pendle"])

    def test_splitting_across_curators_lowers_the_number(self):
        """The other direction — otherwise 'always 50 %' would pass."""
        book = dict(BOOK)
        book["morpho_steakhouse"] = 10_000.0
        book["aave_v3"] = 35_000.0
        res = curator_concentration(book, CAP)
        self.assertAlmostEqual(res["max_pct"], 20.0, places=3)

    def test_zero_and_negative_positions_are_ignored(self):
        res = curator_concentration({"morpho_steakhouse": 0.0, "morpho_blue_base": -5.0}, CAP)
        self.assertEqual(res["by_curator"], {})
        self.assertEqual(res["max_pct"], 0.0)

    def test_empty_book_and_bad_capital_never_raise(self):
        self.assertEqual(curator_concentration({}, CAP)["max_curator"], None)
        self.assertEqual(curator_concentration(BOOK, 0.0)["max_pct"], 0.0)

    def test_mapping_is_injectable(self):
        """Callers can supply their own map — the constant is a default, not a law."""
        res = curator_concentration({"a": 30_000.0, "b": 10_000.0}, CAP,
                                    curator_of={"a": "x", "b": "x"})
        self.assertAlmostEqual(res["max_pct"], 40.0, places=3)

    def test_metric_is_advisory_only(self):
        """It must not have become a gate. Nothing here may reject or cap.

        The owner chose "measure first". A metric that quietly starts gating is a
        RiskPolicy change made without an ADR.
        """
        res = curator_concentration(BOOK, CAP)
        for forbidden in ("approved", "blocked", "rejected", "cap_breached", "violation"):
            self.assertNotIn(forbidden, res)


class TestSkyPromotedOutOfWatchList(unittest.TestCase):

    def test_pool_whitelist_says_t1_not_wl(self):
        from spa_core.data_pipeline.defillama_fetcher import POOL_WHITELIST

        entry = POOL_WHITELIST["sky-susds-ethereum"]
        self.assertEqual(entry["tier"], "T1")
        self.assertNotIn("watch_condition", entry,
                         "the watch condition is MET — leaving it reads as still pending")

    def test_adapter_registry_agrees_with_the_whitelist(self):
        """Two records of the same tier must not disagree — that is how drift starts."""
        doc = json.loads((_REPO / "data" / "adapter_registry.json").read_text(encoding="utf-8"))
        adapters = doc.get("adapters", doc)
        self.assertEqual(str(adapters["sky_susds"]["tier"]).upper(), "T1")

    def test_no_fixed_share_was_hardcoded(self):
        """The monitor asked for max_concentration=0.30; the owner said 'allocator decides'.

        A hardcoded share would be manual control layered over the mechanism built
        to make that decision.
        """
        from spa_core.data_pipeline.defillama_fetcher import POOL_WHITELIST

        entry = POOL_WHITELIST["sky-susds-ethereum"]
        self.assertNotIn("max_concentration", entry)
        self.assertNotIn("allocation_pct", entry)


if __name__ == "__main__":
    unittest.main()
