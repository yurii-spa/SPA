"""
spa_core/tests/test_s41_amm_stable_yield.py

Tests for S41AmmStableYield (spa_core/strategies/s41_amm_stable_yield.py).

AUD-18 (задание владельца 2026-08-05) — карточка
`agent-aud18-strategy-unit-tests`.

Замер покрытия ДО этого файла (трассировка исполнения существующим набором
`tests/test_s22_s25_strategies.py` + `tests/test_aerodrome_velodrome.py`,
докстринги исключены) — непокрытыми оставались ровно ветки отказа и защиты:

    _drop_suspended_and_renorm  5/6  ветка «вес обнулился» не исполнялась
    get_allocation              3/4  ветка thin-pool (ADR-050) не исполнялась
    get_expected_apy            8/9  ветка пустой аллокации не исполнялась
    simulate                    5/6  ветка нулевого капитала не исполнялась
    to_dict                     0/1  НЕ ИСПОЛНЯЛСЯ НИ РАЗУ

Read-only, stdlib, без сети, без записи на диск.

Run:
    python3 -m unittest spa_core.tests.test_s41_amm_stable_yield -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s41_amm_stable_yield import (  # noqa: E402
    S41AmmStableYield,
    AERODROME_FULL_WEIGHT,
    AERODROME_KEY,
    AERODROME_LP_TVL_FLOOR_USD,
    AERODROME_THIN_POOL_WEIGHT,
    CASH_KEY,
    DESCRIPTION,
    FALLBACK_APY,
    MAX_DRAWDOWN_PCT,
    PROTOCOL_TIERS,
    RISK_SCORE,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
    TIER,
    WEIGHTS,
    _drop_suspended_and_renorm,
)


class TestS41Renormalisation(unittest.TestCase):
    """Ренормализация: сумма всегда 1.0, cash не выключаем, пустое — пустое."""

    def test_no_suspension_is_identity(self):
        got = _drop_suspended_and_renorm(dict(WEIGHTS), None)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=6)
        for key, weight in WEIGHTS.items():
            self.assertAlmostEqual(got[key], weight, places=6)

    def test_suspended_protocol_is_dropped_and_rest_renormalised(self):
        got = _drop_suspended_and_renorm(dict(WEIGHTS), {"aave_v3"})
        self.assertNotIn("aave_v3", got)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=6)
        # доли уцелевших выросли пропорционально
        self.assertAlmostEqual(got["compound_v3"] / got[AERODROME_KEY],
                               WEIGHTS["compound_v3"] / WEIGHTS[AERODROME_KEY], places=6)

    def test_cash_is_never_suspendable(self):
        got = _drop_suspended_and_renorm(dict(WEIGHTS), {CASH_KEY})
        self.assertIn(CASH_KEY, got)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=6)

    def test_all_protocols_suspended_leaves_cash_only(self):
        suspended = {k for k in WEIGHTS if k != CASH_KEY}
        got = _drop_suspended_and_renorm(dict(WEIGHTS), suspended)
        self.assertEqual(set(got), {CASH_KEY})
        self.assertAlmostEqual(got[CASH_KEY], 1.0, places=6)

    def test_empty_weights_return_empty_not_division_by_zero(self):
        # Ветка `total <= 0` — честный пустой ответ вместо ZeroDivisionError.
        self.assertEqual(_drop_suspended_and_renorm({}, None), {})
        self.assertEqual(_drop_suspended_and_renorm({"aave_v3": 0.0}, None), {})

    def test_unknown_suspended_key_is_harmless(self):
        got = _drop_suspended_and_renorm(dict(WEIGHTS), {"never_heard_of_it"})
        self.assertAlmostEqual(sum(got.values()), 1.0, places=6)
        self.assertEqual(set(got), set(WEIGHTS))


class TestS41Allocation(unittest.TestCase):

    def setUp(self):
        self.s = S41AmmStableYield()

    def test_default_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.get_allocation().values()), 1.0, places=6)

    def test_cash_buffer_at_least_5pct(self):
        self.assertGreaterEqual(self.s.get_allocation()[CASH_KEY], 0.05)

    def test_t2_sleeve_within_50pct_and_per_protocol_20pct(self):
        alloc = self.s.get_allocation()
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        self.assertLessEqual(t2, 0.50)
        for protocol, weight in alloc.items():
            if PROTOCOL_TIERS.get(protocol) == "T2":
                self.assertLessEqual(weight, 0.20)

    def test_no_tvl_supplied_keeps_full_aerodrome_weight(self):
        # Back-compat: без живого TVL берётся спецификационные 15%.
        self.assertAlmostEqual(
            self.s.get_allocation()[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6
        )

    def test_thin_pool_below_floor_cuts_aerodrome_sleeve(self):
        # ADR-050: TVL ниже $20M ⇒ 15% → 5%, остальное ренормализуется.
        alloc = self.s.get_allocation(aerodrome_tvl_usd=2_000_000.0)
        self.assertLess(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)
        # доля до ренормализации — 0.05 из суммы 0.90
        self.assertAlmostEqual(
            alloc[AERODROME_KEY], AERODROME_THIN_POOL_WEIGHT / 0.90, places=6
        )

    def test_exactly_at_floor_is_not_thin(self):
        # Граница: `<` — ровно $20M считается достаточной глубиной.
        alloc = self.s.get_allocation(aerodrome_tvl_usd=AERODROME_LP_TVL_FLOOR_USD)
        self.assertAlmostEqual(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6)

    def test_one_dollar_below_floor_is_thin(self):
        alloc = self.s.get_allocation(aerodrome_tvl_usd=AERODROME_LP_TVL_FLOOR_USD - 1.0)
        self.assertLess(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT)

    def test_thin_pool_and_suspension_compose(self):
        alloc = self.s.get_allocation(
            suspended={"velodrome_optimism"}, aerodrome_tvl_usd=1_000_000.0
        )
        self.assertNotIn("velodrome_optimism", alloc)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)

    def test_allocation_does_not_mutate_module_weights(self):
        alloc = self.s.get_allocation(aerodrome_tvl_usd=1.0)
        alloc[AERODROME_KEY] = 0.99
        self.assertAlmostEqual(WEIGHTS[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6)
        self.assertAlmostEqual(
            self.s.get_allocation()[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6
        )


class TestS41ExpectedApy(unittest.TestCase):

    def setUp(self):
        self.s = S41AmmStableYield()

    def test_fallback_apy_in_declared_band(self):
        apy = self.s.get_expected_apy()
        self.assertGreaterEqual(apy, TARGET_APY_MIN)
        self.assertLessEqual(apy, TARGET_APY_MAX)

    def test_matches_manual_blend(self):
        expected = round(sum(WEIGHTS[p] * FALLBACK_APY[p] for p in WEIGHTS), 4)
        self.assertAlmostEqual(self.s.get_expected_apy(), expected, places=4)

    def test_live_map_overrides_fallback(self):
        got = self.s.get_expected_apy({"aave_v3": 0.0})
        base = sum(WEIGHTS[p] * FALLBACK_APY[p] for p in WEIGHTS)
        self.assertAlmostEqual(got, round(base - WEIGHTS["aave_v3"] * 3.1, 4), places=4)

    def test_empty_allocation_returns_zero_not_crash(self):
        """Ветка «аллокации нет» — честный 0.0, а не деление на пустоту."""
        class _NoAllocation(S41AmmStableYield):
            def get_allocation(self, suspended=None, aerodrome_tvl_usd=None):
                return {}

        self.assertEqual(_NoAllocation().get_expected_apy(), 0.0)

    def test_suspension_changes_the_number(self):
        self.assertNotAlmostEqual(
            self.s.get_expected_apy(suspended={"aave_v3"}),
            self.s.get_expected_apy(), places=4,
        )

    def test_deterministic(self):
        self.assertEqual(self.s.get_expected_apy(), self.s.get_expected_apy())


class TestS41RiskSummary(unittest.TestCase):

    def setUp(self):
        self.s = S41AmmStableYield()

    def test_tier_shares_sum_with_cash_to_100(self):
        rs = self.s.get_risk_summary()
        total = rs["t1_weight_pct"] + rs["t2_weight_pct"] + rs["cash_weight_pct"]
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_t1_anchor_dominates(self):
        rs = self.s.get_risk_summary()
        self.assertGreater(rs["t1_weight_pct"], rs["t2_weight_pct"])

    def test_declared_fields(self):
        rs = self.s.get_risk_summary()
        self.assertEqual(rs["strategy_id"], STRATEGY_ID)
        self.assertEqual(rs["risk_score"], RISK_SCORE)
        self.assertEqual(rs["max_drawdown_pct"], MAX_DRAWDOWN_PCT)


class TestS41Simulate(unittest.TestCase):

    def setUp(self):
        self.s = S41AmmStableYield()

    def test_positions_sum_to_capital(self):
        sim = self.s.simulate(100_000.0)
        self.assertEqual(sim["status"], "ok")
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)

    def test_yield_matches_apy(self):
        sim = self.s.simulate(100_000.0)
        self.assertAlmostEqual(
            sim["expected_annual_yield_usd"],
            round(100_000.0 * sim["expected_apy_pct"] / 100.0, 4), places=4,
        )

    def test_zero_capital_is_no_capital_not_ok(self):
        sim = self.s.simulate(0.0)
        self.assertEqual(sim["status"], "no_capital")
        self.assertEqual(sim["allocation"], {})
        self.assertEqual(sim["expected_annual_yield_usd"], 0.0)
        self.assertEqual(sim["expected_apy_pct"], 0.0)

    def test_negative_capital_is_no_capital(self):
        self.assertEqual(self.s.simulate(-1.0)["status"], "no_capital")

    def test_timestamp_present_in_both_branches(self):
        for capital in (0.0, 10_000.0):
            with self.subTest(capital=capital):
                self.assertTrue(self.s.simulate(capital)["timestamp_utc"].endswith("+00:00"))

    def test_deterministic_except_timestamp(self):
        a = dict(self.s.simulate(50_000.0))
        b = dict(self.s.simulate(50_000.0))
        a.pop("timestamp_utc")
        b.pop("timestamp_utc")
        self.assertEqual(a, b)


class TestS41ToDict(unittest.TestCase):
    """to_dict — до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S41AmmStableYield()
        self.d = self.s.to_dict()

    def test_identity_fields(self):
        self.assertEqual(self.d["strategy_id"], "S41")
        self.assertEqual(self.d["strategy_name"], STRATEGY_NAME)
        self.assertEqual(self.d["tier"], TIER)
        self.assertEqual(self.d["description"], DESCRIPTION)

    def test_declared_band_and_risk(self):
        self.assertEqual(self.d["target_apy_min"], TARGET_APY_MIN)
        self.assertEqual(self.d["target_apy_max"], TARGET_APY_MAX)
        self.assertEqual(self.d["risk_score"], RISK_SCORE)
        self.assertEqual(self.d["max_drawdown_pct"], MAX_DRAWDOWN_PCT)

    def test_weights_match_module_and_sum_to_one(self):
        self.assertEqual(self.d["weights"], WEIGHTS)
        self.assertAlmostEqual(sum(self.d["weights"].values()), 1.0, places=6)

    def test_nested_dicts_are_copies(self):
        self.d["weights"][CASH_KEY] = 0.99
        self.d["protocol_tiers"][CASH_KEY] = "T3"
        self.d["fallback_apy"][CASH_KEY] = 99.0
        self.assertAlmostEqual(WEIGHTS[CASH_KEY], 0.05, places=6)
        self.assertEqual(PROTOCOL_TIERS[CASH_KEY], "CASH")
        self.assertEqual(FALLBACK_APY[CASH_KEY], 0.0)

    def test_json_serialisable(self):
        import json
        self.assertIsInstance(json.dumps(self.d), str)

    def test_deterministic_except_timestamp(self):
        a = dict(self.s.to_dict())
        b = dict(self.s.to_dict())
        a.pop("timestamp")
        b.pop("timestamp")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
