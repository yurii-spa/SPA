"""The vol guardian decides inside the bar it trades — pinned DIRECTLY on the shipped organ.

Owner decision 2026-09-02, вариант 1 (card `owner-decision-storozh-prosadki-reshaet-uzhe-znaya-itog`):
the deployed guardian is NOT changed; the numbers it was credited with are recomputed and republished
as honest pairs. That correction is only trustworthy while the thing being corrected stays what it
was measured to be — so the property itself is nailed down here, in both directions.

**Why here and not in the R&D script.** `scripts/edge_overlay_domain_admissibility.py` already pins
this, but on its own MIRROR (`_exposure_trace`), reached through a bit-identity test against the
organ. That chain is sound and stays; what it does not survive is the R&D file being deleted,
renamed or trimmed — an ordinary fate for a research script — after which twenty test files still
touch the guardian and not one of them says what its exposure is a function of. These tests import
`apply_guardian_vol` itself.

Both directions, deliberately:

  * the SHIPPED pre-emptive overlay MUST react on the shock day (the finding, reproduced — if it
    stops, that is a silent behaviour change to a deployed agent and needs an ADR, not a green run);
  * the SHIPPED reactive overlay MUST NOT (the probe can distinguish; it is not a rubber stamp);
  * the CAUSAL reference must not react on the shock day, and MUST react the day after (a control
    that never fires would "prove" causality for free).

Deterministic, network-free.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402
import guardian_causality_recheck as rc  # noqa: E402

from spa_core.strategy_lab.aggressive_lab.guardian import (  # noqa: E402
    apply_guardian_drawdown,
    apply_guardian_vol,
)

PARAMS = {"lookback": 10, "vol_mult": 2.0, "derisk_frac": 0.0, "calm_mult": 1.2, "min_vol": 1e-5}


def _shock_series(calm_days: int = 120, shock: float = 0.60, tail: int = 20):
    """A long calm ramp, ONE violent day, then calm again. Returns (equity, index of the shock day)."""
    eq = [1.0]
    for _ in range(calm_days):
        eq.append(eq[-1] * 1.0002)
    k = len(eq)
    eq.append(eq[-1] * shock)
    for _ in range(tail):
        eq.append(eq[-1] * 1.0002)
    return eq, k


def _exposure_on_day(overlay, equity, k, **kw) -> float:
    """The exposure the overlay ACTUALLY applied to day `k`, recovered from its output.

    `guarded[k]/guarded[k-1] - 1 == (equity[k]/equity[k-1] - 1) * exposure`, so the ratio of the two
    moves IS the exposure — read from what the overlay did, never from its internals, so this cannot
    drift away from the behaviour it is describing.
    """
    raw = equity[k] / equity[k - 1] - 1.0
    assert raw != 0.0, "day k does not move — nothing to divide by"
    guarded = overlay(equity, **kw)
    return (guarded[k] / guarded[k - 1] - 1.0) / raw


class TestShippedOrganDecidesInsideItsOwnBar(unittest.TestCase):

    def test_preemptive_overlay_reacts_on_the_shock_day_itself(self):
        """The finding. The exposure applied to day k is a function of day k's own return."""
        eq, k = _shock_series()
        applied = _exposure_on_day(apply_guardian_vol, eq, k, **PARAMS)
        self.assertLess(
            applied, 1.0,
            "apply_guardian_vol no longer de-risks inside the bar it trades. That is a BEHAVIOUR "
            "CHANGE to a deployed agent, and every published guardian number was measured against "
            "the old behaviour — do not silence this test, write the ADR (see ADR-212).")

    def test_reactive_overlay_does_not_react_on_the_shock_day(self):
        """The other direction: the probe can say 'no leak'. Without this it stamps everything.

        `apply_guardian_drawdown` observes the drawdown AFTER the move lands and cuts from the next
        day — the honest ordering. If this ever went red together with the test above, the probe
        would be measuring itself.
        """
        eq, k = _shock_series()
        applied = _exposure_on_day(
            apply_guardian_drawdown, eq, k, derisk_dd=0.04, derisk_frac=0.0, reenter_frac=0.5)
        self.assertEqual(applied, 1.0,
                         "the reactive overlay took less than the full move on the shock day — "
                         "it, too, now decides inside its own bar")

    def test_reactive_overlay_does_react_the_day_after(self):
        """…and it is not simply inert: it must cut on day k+1."""
        eq, k = _shock_series()
        applied = _exposure_on_day(
            apply_guardian_drawdown, eq, k + 1, derisk_dd=0.04, derisk_frac=0.0, reenter_frac=0.5)
        self.assertLess(applied, 1.0, "the reactive overlay never reacted at all")


class TestCausalReferenceIsAWorkingControl(unittest.TestCase):

    def test_causal_reference_takes_the_full_shock_day(self):
        eq, k = _shock_series()
        applied = _exposure_on_day(rc.causal_overlay, eq, k, **PARAMS)
        self.assertEqual(applied, 1.0, "the causal reference peeked at the day it was trading")

    def test_causal_reference_reacts_the_day_after(self):
        eq, k = _shock_series()
        applied = _exposure_on_day(rc.causal_overlay, eq, k + 1, **PARAMS)
        self.assertLess(applied, 1.0,
                        "the causal reference never reacted at all — it is not a control, it is a "
                        "no-op, and every 'causal' number computed from it would be RAW")


class TestRecheckReusesTheExistingMirror(unittest.TestCase):
    """No third copy of the decision rule: the recheck's two columns ARE the two known engines."""

    def test_deployed_column_is_the_shipped_organ_itself(self):
        eq, _ = _shock_series()
        self.assertEqual(rc.deployed_overlay(eq, **{k: v for k, v in PARAMS.items()}),
                         apply_guardian_vol(eq, roundtrip_cost=0.0, **PARAMS))

    def test_causal_column_is_the_existing_lag_one_mirror(self):
        eq, _ = _shock_series()
        self.assertEqual(
            rc.causal_overlay(eq, **PARAMS),
            oda.guarded_path(eq, None, roundtrip_cost=0.0, causal_lag=1, **PARAMS))

    def test_that_binding_is_not_vacuous(self):
        """If the recheck silently reverted to lag 0, the binding above must go red."""
        eq, _ = _shock_series()
        self.assertNotEqual(
            rc.causal_overlay(eq, **PARAMS),
            oda.guarded_path(eq, None, roundtrip_cost=0.0, causal_lag=0, **PARAMS),
            "lag 0 and lag 1 produced the same path — the binding test cannot see the difference "
            "it exists to see")


class TestRecheckMeasuresTheLookAheadPremium(unittest.TestCase):
    """`recheck_book`'s headline arithmetic, pinned in both directions on constructed books."""

    def test_a_book_whose_whole_cut_is_the_look_ahead(self):
        """One violent day and nothing else: the deployed cell 'cuts' it, the causal one cannot."""
        eq, _ = _shock_series(calm_days=200, shock=0.60, tail=60)
        r = rc.recheck_book(eq)
        self.assertGreater(r["dd_cut_claimed_pp"], 10.0,
                           "the deployed overlay did not claim a cut — no premium to measure")
        self.assertGreater(
            r["dd_cut_claimed_pp"] - r["dd_cut_causal_pp"], 5.0,
            "the recheck reports the same cut with and without the look-ahead on a book that is "
            "NOTHING BUT a one-day gap — it is not measuring the premium")

    def test_a_book_with_no_premium_to_find(self):
        """The other direction. A monotone-up book has no drawdown; both columns must say ~0."""
        eq = [1.0]
        for _ in range(200):
            eq.append(eq[-1] * 1.0003)
        r = rc.recheck_book(eq)
        self.assertAlmostEqual(r["dd_cut_claimed_pp"], 0.0, places=6)
        self.assertAlmostEqual(r["dd_cut_causal_pp"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
