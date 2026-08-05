"""Pendle PT: pin the MARKET, choose the issue — and never confuse PT with LP.

Two traps, both measured on the live feed on 2026-08-05.

**The instruments are indistinguishable by every field we normally match on.**
The PT record and the LP record for sUSDe on Ethereum carry the same project,
the same chain, the same symbol (``SUSDE``) and the *same* TVL ($8.24M). Only
``poolMeta`` separates them — ``"For buying PT-sUSDe-13AUG2026"`` against
``"For LP | Maturity 13AUG2026"``. Their APYs are **4.26 % and 12.39 %**. A
"largest TVL wins" rule picks between them by coin flip, and a threefold APY
difference is not noise: it is a different instrument with a different risk.

**PT is dated.** Pinning a pool UUID cannot work here — the issue matures, the
pool disappears, and the feed looks healthy right up to that day. So the pin is
the *market*, and the issue is re-selected every run: the nearest maturity still
far enough out to be worth entering. When none qualifies the answer is None, and
the protocol goes honestly unobserved until the next issue lists.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from spa_core.monitoring.adapter_status_generator import (
    _PT_MIN_DAYS_TO_MATURITY,
    _lookup_pendle_pt,
    _pt_maturity,
)

TODAY = date(2026, 8, 5)


def _pool(meta: str, apy: float, maturity_days: int = 30, tvl: float = 8_237_214.0) -> dict:
    """A feed row; ``meta`` decides whether it is a PT or an LP record."""
    when = (TODAY + timedelta(days=maturity_days)).strftime("%d%b%Y").upper()
    return {
        "pool": f"id-{meta[:12]}-{when}",
        "chain": "Ethereum",
        "project": "pendle",
        "symbol": "SUSDE",
        "tvlUsd": tvl,
        "apy": apy,
        "poolMeta": meta.replace("{DATE}", when),
    }


class TestMaturityParsing(unittest.TestCase):

    def test_pt_meta_yields_a_date(self):
        self.assertEqual(_pt_maturity({"poolMeta": "For buying PT-sUSDe-13AUG2026"}),
                         date(2026, 8, 13))

    def test_lp_meta_is_not_a_pt(self):
        """The LP row also carries a maturity — it must still be refused."""
        self.assertIsNone(_pt_maturity({"poolMeta": "For LP | Maturity 13AUG2026"}))

    def test_unreadable_date_is_refused(self):
        """A dated instrument with an unreadable date has an unknown term.

        Unknown term is not evidence of eligibility, so it does not get to trade.
        """
        for meta in ("For buying PT-sUSDe-NOTADATE", "For buying PT-sUSDe-", "", None):
            with self.subTest(meta=meta):
                self.assertIsNone(_pt_maturity({"poolMeta": meta}))

    def test_month_case_does_not_matter(self):
        """The feed shouts the month; %b expects 'Aug'. A first version uppercased
        the FORMAT instead of the value and silently returned None on valid dates."""
        for text in ("13AUG2026", "13Aug2026", "13aug2026"):
            with self.subTest(text=text):
                self.assertEqual(_pt_maturity({"poolMeta": f"For buying PT-sUSDe-{text}"}),
                                 date(2026, 8, 13))


class TestIssueSelection(unittest.TestCase):

    def test_pt_is_chosen_over_lp_at_identical_tvl(self):
        """The trap itself: same project, chain, symbol and TVL; APY 4.26 vs 12.39.

        The higher number belongs to the LP. Taking it would rank capital on a
        different instrument's return.
        """
        pools = [_pool("For LP | Maturity {DATE}", 12.39),
                 _pool("For buying PT-sUSDe-{DATE}", 4.26)]
        got = _lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got["apy"], 4.26, places=2)

    def test_nearest_valid_maturity_wins(self):
        """The currently traded issue, not the furthest one."""
        pools = [_pool("For buying PT-sUSDe-{DATE}", 4.0, maturity_days=200),
                 _pool("For buying PT-sUSDe-{DATE}", 4.5, maturity_days=30),
                 _pool("For buying PT-sUSDe-{DATE}", 4.9, maturity_days=90)]
        got = _lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY)
        self.assertAlmostEqual(got["apy"], 4.5, places=2)

    def test_a_matured_issue_is_never_selected(self):
        pools = [_pool("For buying PT-sUSDe-{DATE}", 4.26, maturity_days=-1)]
        self.assertIsNone(_lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY))

    def test_an_issue_about_to_mature_is_refused(self):
        """Too close to expiry to enter — the threshold is pinned from both sides."""
        near = _PT_MIN_DAYS_TO_MATURITY - 1
        far = _PT_MIN_DAYS_TO_MATURITY + 1
        self.assertIsNone(_lookup_pendle_pt(
            "pendle_pt_susde", [_pool("For buying PT-sUSDe-{DATE}", 4.26, maturity_days=near)],
            today=TODAY))
        self.assertIsNotNone(_lookup_pendle_pt(
            "pendle_pt_susde", [_pool("For buying PT-sUSDe-{DATE}", 4.26, maturity_days=far)],
            today=TODAY))

    def test_rollover_happens_as_the_calendar_moves(self):
        """The whole point: the same pool list yields a different issue over time.

        A static UUID pin would have kept pointing at the expired one.
        """
        pools = [_pool("For buying PT-sUSDe-{DATE}", 4.2, maturity_days=20),
                 _pool("For buying PT-sUSDe-{DATE}", 4.8, maturity_days=120)]
        now = _lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY)
        later = _lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY + timedelta(days=40))
        self.assertAlmostEqual(now["apy"], 4.2, places=2)
        self.assertAlmostEqual(later["apy"], 4.8, places=2,
                               msg="after the near issue matures the next one must be picked")

    def test_wrong_chain_or_asset_is_not_matched(self):
        pools = [dict(_pool("For buying PT-sUSDe-{DATE}", 4.26), chain="Monad"),
                 dict(_pool("For buying PT-sUSDe-{DATE}", 4.26), symbol="USDC")]
        self.assertIsNone(_lookup_pendle_pt("pendle_pt_susde", pools, today=TODAY))

    def test_unknown_adapter_key_returns_none(self):
        pools = [_pool("For buying PT-sUSDe-{DATE}", 4.26)]
        self.assertIsNone(_lookup_pendle_pt("not_a_pt_market", pools, today=TODAY))

    def test_empty_and_malformed_input_never_raises(self):
        self.assertIsNone(_lookup_pendle_pt("pendle_pt_susde", [], today=TODAY))
        self.assertIsNone(_lookup_pendle_pt("pendle_pt_susde", [None, "junk", {}], today=TODAY))


if __name__ == "__main__":
    unittest.main()
