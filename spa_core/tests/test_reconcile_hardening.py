"""spa_core/tests/test_reconcile_hardening.py — WS-3.2 NAV-RECONCILE HARDENING.

# LLM_FORBIDDEN

Cutover-Bulletproof WS-3.2: ``reconciliation.reconcile`` must reconcile correctly
OR fail-CLOSED (block — never a silent proceed) under EVERY failure mode:

  * PARTIAL-FILL      — matches_target=False → block.
  * REORG/STATE-CHANGE— expected != actual → block.
  * STALE-PRICE       — price as_of too old → block.
  * DUST-TOLERANCE    — sub-threshold passes, at/above blocks (exact boundary).
  * NON-FINITE        — NaN/Inf valuation → fail-closed (never coerced to pass).
  * NAV-TO-THE-CENT   — conservation checked with Decimal to one cent.

HARD GUARANTEES: pure arithmetic, deterministic, INERT (no chain, no live data,
is_live never flipped). Every mismatch must produce ``blocked=True`` / ``ok=False``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math

import pytest

from spa_core.execution import reconciliation as rec


def _target() -> dict:
    return {"aave_v3": 40_000.0, "morpho_blue": 20_000.0, "compound_v3": 15_000.0}


_CAPITAL = 75_000.0  # _target() deploys $75k → a clean full fill conserves NAV.


# =========================================================================== #
# PARTIAL-FILL → matches_target False → blocked.
# =========================================================================== #
class TestPartialFillBlocks:
    def test_partial_fill_blocks(self):
        target = _target()
        partial = {**target, "aave_v3": 25_000.0}  # $15k short
        r = rec.reconcile(target, partial, nav_before=_CAPITAL, costs_usd=0.0)
        assert r["matches_target"] is False
        assert r["ok"] is False and r["blocked"] is True

    def test_full_fill_ok(self):
        target = _target()
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0)
        assert r["matches_target"] is True
        assert r["nav_conserved_to_cent"] is True
        assert r["ok"] is True and r["blocked"] is False


# =========================================================================== #
# REORG / STATE-CHANGE → expected != actual → blocked.
# =========================================================================== #
class TestReorgBlocks:
    def test_reorg_dropped_position_blocks(self):
        target = _target()
        reorged = {**target, "aave_v3": 0.0}
        r = rec.reconcile(target, reorged, nav_before=_CAPITAL, costs_usd=0.0)
        assert r["blocked"] is True

    def test_reorg_phantom_position_blocks(self):
        target = _target()
        phantom = {**target, "euler_v2": 12_000.0}
        r = rec.reconcile(target, phantom, nav_before=_CAPITAL, costs_usd=0.0)
        assert r["blocked"] is True


# =========================================================================== #
# DUST-TOLERANCE — exact boundary: < DUST passes, >= DUST blocks.
# =========================================================================== #
class TestDustToleranceBoundary:
    def test_just_below_dust_passes(self):
        target = {"aave_v3": 40_000.0}
        # 0.99 < $1 dust → still matches.
        drifted = {"aave_v3": 40_000.0 + 0.99}
        r = rec.reconcile(target, drifted, nav_before=40_000.99, costs_usd=0.0)
        assert r["matches_target"] is True

    def test_at_dust_threshold_blocks(self):
        target = {"aave_v3": 40_000.0}
        # exactly $1.00 == DUST_TOLERANCE_USD → NOT dust → block (strict <).
        at = {"aave_v3": 40_000.0 + rec.DUST_TOLERANCE_USD}
        r = rec.reconcile(target, at, nav_before=40_001.0, costs_usd=0.0)
        assert r["matches_target"] is False
        assert r["blocked"] is True

    def test_above_dust_blocks(self):
        target = {"aave_v3": 40_000.0}
        above = {"aave_v3": 40_005.0}  # $5 > $1
        r = rec.reconcile(target, above, nav_before=40_005.0, costs_usd=0.0)
        assert r["matches_target"] is False
        assert r["blocked"] is True


# =========================================================================== #
# NON-FINITE — NaN/Inf valuation must fail-CLOSED (never coerced to pass).
# =========================================================================== #
class TestNonFiniteFailsClosed:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_position_blocks(self, bad):
        target = {"aave_v3": 40_000.0}
        r = rec.reconcile(target, {"aave_v3": bad}, nav_before=40_000.0, costs_usd=0.0)
        assert r["finite"] is False
        # The latent fail-OPEN: a NaN must NOT report matches_target True.
        assert r["matches_target"] is False
        assert r["nav_conserved"] is False
        assert r["nav_conserved_to_cent"] is False
        assert r["ok"] is False and r["blocked"] is True

    def test_bool_position_rejected(self):
        # bool would coerce to 1.0 and masquerade as $1 — must be rejected.
        target = {"aave_v3": 1.0}
        r = rec.reconcile(target, {"aave_v3": True}, nav_before=1.0, costs_usd=0.0)
        assert r["finite"] is False and r["blocked"] is True


# =========================================================================== #
# STALE-PRICE — a price snapshot older than MAX_PRICE_AGE_SECONDS → block.
# =========================================================================== #
class TestStalePriceBlocks:
    def test_fresh_price_ok(self):
        target = _target()
        now = 1_000_000.0
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0,
                          price_as_of=now - 5.0, now=now)
        assert r["price_stale"] is False
        assert r["ok"] is True

    def test_stale_price_blocks(self):
        target = _target()
        now = 1_000_000.0
        # 1 hour old quote >> 120s budget → stale → block even on a clean book.
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0,
                          price_as_of=now - 3600.0, now=now)
        assert r["price_stale"] is True
        assert r["ok"] is False and r["blocked"] is True
        assert any("stale price" in reason for reason in r["block_reasons"])

    def test_future_dated_price_blocks(self):
        target = _target()
        now = 1_000_000.0
        # A future-dated quote is untrustworthy → stale/block (negative age).
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0,
                          price_as_of=now + 50.0, now=now)
        assert r["price_stale"] is True and r["blocked"] is True

    def test_boundary_age_ok(self):
        target = _target()
        now = 1_000_000.0
        # exactly at the budget is still acceptable (<=).
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0,
                          price_as_of=now - rec.MAX_PRICE_AGE_SECONDS, now=now)
        assert r["price_stale"] is False

    def test_no_price_supplied_keeps_legacy(self):
        # Backward-compat: callers that pass no price age are not stale-gated.
        target = _target()
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0)
        assert r["price_stale"] is False and r["price_age_seconds"] is None
        assert r["ok"] is True


# =========================================================================== #
# NAV-TO-THE-CENT — Decimal conservation: a one-cent surplus/deficit blocks.
# =========================================================================== #
class TestNavToTheCent:
    def test_exact_to_the_cent_conserved(self):
        target = {"aave_v3": 40_000.00}
        # costs 0.50 → expected 39_999.50; outcome 39_999.50 → conserved to cent.
        outcome = {"aave_v3": 39_999.50}
        r = rec.reconcile(target, outcome, nav_before=40_000.00, costs_usd=0.50)
        # position delta is 0.50 < dust → matches; cents axis exact.
        assert r["nav_conserved_to_cent"] is True
        assert r["nav_residual_cents"] == "0.00"

    def test_one_cent_deficit_breaks_cent_axis(self):
        target = {"aave_v3": 40_000.00}
        # nav_after 40_000.00 but expected 40_000.02 (costs -0.02 → surplus 0.02).
        # Use costs to force a 2-cent expected gap > 1 cent.
        outcome = {"aave_v3": 40_000.00}
        r = rec.reconcile(target, outcome, nav_before=40_000.00, costs_usd=0.02)
        assert r["nav_conserved_to_cent"] is False
        assert r["blocked"] is True

    def test_capital_vanished_blocks(self):
        target = {"aave_v3": 40_000.0}
        outcome = {"aave_v3": 30_000.0}  # $10k vanished, no costs
        r = rec.reconcile(target, outcome, nav_before=40_000.0, costs_usd=0.0)
        assert r["nav_conserved"] is False
        assert r["nav_conserved_to_cent"] is False
        assert r["blocked"] is True

    def test_capital_appeared_blocks(self):
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        outcome = {"aave_v3": 40_000.0, "morpho_blue": 50_000.0}  # +$30k phantom
        r = rec.reconcile(target, outcome, nav_before=60_000.0, costs_usd=0.0)
        assert r["blocked"] is True


# =========================================================================== #
# RED-TEAM SWEEP — NO failure mode silently proceeds; ONLY the clean book is ok.
# =========================================================================== #
class TestRedTeamNoSilentProceed:
    def test_no_corrupt_outcome_is_ok(self):
        target = _target()
        corrupt = {
            "partial":          {**target, "aave_v3": 25_000.0},
            "zero_fill":        {**target, "morpho_blue": 0.0},
            "overfill":         {**target, "aave_v3": 60_000.0},
            "reorg_drop":       {**target, "aave_v3": 0.0},
            "phantom":          {**target, "euler_v2": 10_000.0},
            "vanished":         {"aave_v3": 10_000.0},
            "appeared":         {**target, "morpho_blue": 80_000.0},
            "nan":              {**target, "aave_v3": float("nan")},
            "inf":              {**target, "aave_v3": float("inf")},
        }
        for name, outcome in corrupt.items():
            r = rec.reconcile(target, outcome, nav_before=_CAPITAL, costs_usd=0.0)
            assert r["ok"] is False, f"{name} was OK — fail-OPEN!"
            assert r["blocked"] is True

    def test_only_clean_book_is_ok(self):
        target = _target()
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0)
        assert r["ok"] is True

    def test_stale_price_on_otherwise_clean_book_still_blocks(self):
        """A clean fill with a STALE price still blocks — the stale axis is
        orthogonal and cannot be masked by a matching book."""
        target = _target()
        now = 2_000_000.0
        r = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0,
                          price_as_of=now - 10_000.0, now=now)
        assert r["matches_target"] is True   # book is clean...
        assert r["ok"] is False              # ...but stale price still blocks.


# =========================================================================== #
# INERT — the hardened reconcile never flips is_live / touches live data.
# =========================================================================== #
class TestInert:
    def test_round_trip_still_dry_run(self):
        report = rec.round_trip(current={"aave_v3": 1_000.0},
                                target={"aave_v3": 1_000.0}, write=False,
                                ts="2026-06-28T00:00:00+00:00")
        assert report["live_execution"] is False
        assert report["mode"] == "dry_run_analytical"

    def test_reconcile_is_pure(self):
        # No exception, no side effect, deterministic.
        a = rec.reconcile({"x": 1.0}, {"x": 1.0}, nav_before=1.0)
        b = rec.reconcile({"x": 1.0}, {"x": 1.0}, nav_before=1.0)
        assert a["ok"] == b["ok"] and a["nav_residual_cents"] == b["nav_residual_cents"]
