"""ADR-020 T3-total cap enforcement in the allocator (regression for the optimized_yield breach).

The WS1.2 optimizer collapsed T3→T2 (the allocator only ever emitted "T1"/"T2" tier strings), so the
15% T3 cap was silently unenforced and optimized_yield could pour 30% into T3 (susde 20% + extra_finance
10%). _enforce_t3_total_cap re-applies the cap against the CANONICAL tier_map. These tests lock it.
"""
from __future__ import annotations

import unittest

from spa_core.allocator.allocator import StrategyAllocator


class TestT3TotalCap(unittest.TestCase):
    def setUp(self) -> None:
        self.sa = StrategyAllocator(strategy_loop_enabled=False)

    def test_over_cap_t3_is_trimmed_to_15pct(self) -> None:
        # susde + extra_finance_base are canonical T3; 20% + 10% = 30% > 15% cap → trimmed
        w = {"morpho_steakhouse": 0.40, "pendle": 0.20, "susde": 0.20,
             "extra_finance_base": 0.10, "spark_susds": 0.05}
        out, enforced = self.sa._enforce_t3_total_cap(w)
        self.assertTrue(enforced)
        t3 = out.get("susde", 0.0) + out.get("extra_finance_base", 0.0)
        self.assertLessEqual(t3, self.sa.T3_TOTAL_CAP + 1e-6)
        # trimmed proportionally (susde was 2x extra_finance → stays 2x)
        self.assertAlmostEqual(out["susde"], 0.10, places=4)
        self.assertAlmostEqual(out["extra_finance_base"], 0.05, places=4)
        # non-T3 untouched
        self.assertAlmostEqual(out["morpho_steakhouse"], 0.40, places=6)
        self.assertAlmostEqual(out["pendle"], 0.20, places=6)

    def test_within_cap_t3_untouched(self) -> None:
        w = {"morpho_steakhouse": 0.40, "susde": 0.10, "spark_susds": 0.10}  # T3 = 10% ≤ 15%
        out, enforced = self.sa._enforce_t3_total_cap(w)
        self.assertFalse(enforced)
        self.assertEqual(out, w)

    def test_freed_weight_stays_cash_not_riskier_tier(self) -> None:
        # trimming T3 must NOT inflate T1/T2 — the freed weight is honest cash
        w = {"morpho_steakhouse": 0.40, "susde": 0.20, "extra_finance_base": 0.10}
        out, _ = self.sa._enforce_t3_total_cap(w)
        self.assertAlmostEqual(out["morpho_steakhouse"], 0.40, places=6)  # unchanged
        self.assertLess(sum(out.values()), sum(w.values()))  # total dropped → cash


if __name__ == "__main__":
    unittest.main()
