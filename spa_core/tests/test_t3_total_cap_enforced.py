"""ADR-337: общий потолок тира T3 (15 %, ADR-020) впервые исполняется гейтом RiskPolicy.

Порог `max_total_t3_allocation` был объявлен в RiskConfig и не читался НИГДЕ — проверялся
только T2. Замер 11.09 вызовом настоящего гейта: T3-позиция на 20 % одобрена, общий
потолок тира молчал. Порог не изменён — он впервые исполняется. Проверки — в обе стороны.
"""
from __future__ import annotations

import unittest

from spa_core.risk.policy import PortfolioState, Position, RiskConfig, RiskPolicy

CAP = 100_000.0


def _pos(key, tier, amount):
    return Position(protocol_key=key, tier=tier, asset="USDC", amount_usd=amount,
                    apy_at_open=5.0, current_apy=5.0, unrealized_pnl_usd=0.0,
                    days_held=10, chain="ethereum")


def _t3_violations(res):
    return [v for v in res.violations if "Total T3" in v]


class TheCapIsDeclaredAndNowEnforced(unittest.TestCase):
    def test_the_threshold_is_the_declared_one_unchanged(self):
        self.assertEqual(RiskConfig().max_total_t3_allocation, 0.15)

    def test_a_new_t3_position_over_the_tier_cap_is_refused(self):
        """СЦЕНА ЗАМЕРА 11.09: T3 на 20 % — раньше одобрялась."""
        state = PortfolioState(total_capital_usd=CAP, positions=[])
        res = RiskPolicy().check_new_position(state, "pendle", "T3", amount_usd=20_000.0,
                                              current_apy=14.0, tvl_usd=21_000_000.0,
                                              chain="ethereum")
        self.assertTrue(_t3_violations(res), res.violations)

    def test_two_t3_positions_summing_over_the_cap_are_refused(self):
        state = PortfolioState(total_capital_usd=CAP, positions=[_pos("a_t3", "T3", 10_000.0)])
        res = RiskPolicy().check_new_position(state, "b_t3", "T3", amount_usd=6_000.0,
                                              current_apy=8.0, tvl_usd=50_000_000.0,
                                              chain="ethereum")
        self.assertTrue(_t3_violations(res))


class WhatIsNotAViolation(unittest.TestCase):
    """Обратная сторона: гейт, отказывающий на всё, — не гейт."""

    def test_t3_exactly_at_the_cap_passes(self):
        state = PortfolioState(total_capital_usd=CAP, positions=[])
        res = RiskPolicy().check_new_position(state, "pendle", "T3", amount_usd=15_000.0,
                                              current_apy=8.0, tvl_usd=50_000_000.0,
                                              chain="ethereum")
        self.assertEqual(_t3_violations(res), [])

    def test_t2_positions_do_not_count_toward_the_t3_cap(self):
        state = PortfolioState(total_capital_usd=CAP,
                               positions=[_pos("t2a", "T2", 20_000.0), _pos("t2b", "T2", 20_000.0)])
        res = RiskPolicy().check_new_position(state, "t3", "T3", amount_usd=10_000.0,
                                              current_apy=8.0, tvl_usd=50_000_000.0,
                                              chain="ethereum")
        self.assertEqual(_t3_violations(res), [])


class TheBookAndTheCapacity(unittest.TestCase):
    def test_a_book_already_over_the_t3_cap_is_named(self):
        """Тир динамический — книга нарушает порог и без сделки (Pendle меряет тир по TVL)."""
        state = PortfolioState(total_capital_usd=CAP, positions=[_pos("pendle", "T3", 20_000.0)])
        res = RiskPolicy().check_portfolio_health(state)
        self.assertTrue(any("Total T3" in v for v in res.violations), res.violations)

    def test_capacity_for_a_new_t3_position_stops_at_the_cap(self):
        state = PortfolioState(total_capital_usd=CAP, positions=[_pos("a_t3", "T3", 10_000.0)])
        room = RiskPolicy().max_safe_position_size(state, "b_t3", "T3")
        self.assertLessEqual(room, 5_000.0 + 0.01)


if __name__ == "__main__":
    unittest.main()
