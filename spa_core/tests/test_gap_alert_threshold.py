# LLM_FORBIDDEN
"""
Pins the cycle-gap alert threshold to the author's intent so the local/UTC drift
that made it fire ~2h late (fixed 2026-07-23, owner Variant B) cannot recur silently.

The daily cycle runs at 08:00 LOCAL = 06:00 UTC (summer). The gap alert opens at
"real UTC start + buffer" = 06:00 + 2h = 08:00 UTC. If someone reverts the threshold to
the old (wrong) 10, or breaks the buffer relationship, THIS test goes red.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import unittest

from spa_core.paper_trading import cycle_gap_monitor as gm

# The REAL UTC hour the cycle starts in summer (08:00 local Europe/Madrid = 06:00 UTC).
# Kept in the test (not the alert path) on purpose: Variant C (auto-DST derivation in the
# alert path) was rejected as a fail-open surface. This is the pinned documented premise.
_REAL_CYCLE_UTC_START_SUMMER = 6


class TestGapAlertThreshold(unittest.TestCase):
    def test_threshold_equals_real_start_plus_buffer(self):
        # the whole point of the 2026-07-23 fix: threshold = real UTC start + buffer.
        self.assertEqual(
            gm.GAP_ALERT_AFTER_UTC_HOUR,
            _REAL_CYCLE_UTC_START_SUMMER + gm.GAP_ALERT_BUFFER_H,
            "gap alert threshold must equal real UTC cycle start (06:00) + buffer",
        )

    def test_threshold_is_8_not_the_old_wrong_10(self):
        self.assertEqual(gm.GAP_ALERT_AFTER_UTC_HOUR, 8)
        self.assertNotEqual(gm.GAP_ALERT_AFTER_UTC_HOUR, 10)

    def test_buffer_is_two_hours(self):
        self.assertEqual(gm.GAP_ALERT_BUFFER_H, 2)

    def test_expected_local_hour_maps_to_real_utc_start_in_summer(self):
        # Europe/Madrid summer = UTC+2, so 08:00 local == 06:00 UTC.
        self.assertEqual(gm.EXPECTED_CYCLE_LOCAL_HOUR - 2, _REAL_CYCLE_UTC_START_SUMMER)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
