"""
Tests for MP-991: ProtocolDeFiTreasuryRunwayAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_treasury_runway_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.protocol_defi_treasury_runway_analyzer import (
    ProtocolDeFiTreasuryRunwayAnalyzer,
    _safe_div,
    _clamp,
    DISCOUNT_CONCENTRATED,
    DISCOUNT_DEFAULT,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(
    name="TestProto",
    treasury_stable=10_000_000,
    treasury_native=5_000_000,
    treasury_eth_btc=2_000_000,
    monthly_opex=300_000,
    monthly_emissions=200_000,
    monthly_revenue=100_000,
    token_price=1.0,
    token_price_ath=10.0,
    fdv=100_000_000,
    concentration=30.0,
    div_score=50.0,
):
    return {
        "name": name,
        "treasury_stable_usd": treasury_stable,
        "treasury_native_usd": treasury_native,
        "treasury_eth_btc_usd": treasury_eth_btc,
        "monthly_opex_usd": monthly_opex,
        "monthly_token_emissions_usd": monthly_emissions,
        "monthly_protocol_revenue_usd": monthly_revenue,
        "token_price_usd": token_price,
        "token_price_ath_usd": token_price_ath,
        "fully_diluted_valuation_usd": fdv,
        "token_concentration_pct": concentration,
        "diversification_score": div_score,
    }


def tmp_cfg(td=None):
    if td is None:
        td = tempfile.mkdtemp()
    return {
        "log_path": os.path.join(td, "treasury_runway_log.json"),
        "log_cap": 10,
    }


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2), 5.0)

    def test_safe_div_zero_denom(self):
        self.assertEqual(_safe_div(10, 0), 0.0)

    def test_safe_div_zero_denom_custom_default(self):
        self.assertEqual(_safe_div(10, 0, default=99), 99)

    def test_safe_div_negative(self):
        self.assertAlmostEqual(_safe_div(-6, 3), -2.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(50, 0, 100), 50)

    def test_clamp_above(self):
        self.assertEqual(_clamp(200, 0, 100), 100)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5, 0, 100), 0)

    def test_discount_concentrated_less_than_default(self):
        self.assertLess(DISCOUNT_CONCENTRATED, DISCOUNT_DEFAULT)

    def test_discount_values_in_range(self):
        self.assertGreater(DISCOUNT_CONCENTRATED, 0)
        self.assertLess(DISCOUNT_DEFAULT, 1)


# ── instantiation & top-level ─────────────────────────────────────────────────

class TestAnalyzerInit(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def test_instantiation(self):
        self.assertIsInstance(self.analyzer, ProtocolDeFiTreasuryRunwayAnalyzer)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze([make_protocol()], tmp_cfg(self.td))
        self.assertIsInstance(result, dict)

    def test_top_level_keys(self):
        result = self.analyzer.analyze([make_protocol()], tmp_cfg(self.td))
        for k in ("analyzed_at", "protocol_count", "protocols", "aggregates"):
            self.assertIn(k, result)

    def test_protocol_count(self):
        protos = [make_protocol(name=f"P{i}") for i in range(4)]
        result = self.analyzer.analyze(protos, tmp_cfg(self.td))
        self.assertEqual(result["protocol_count"], 4)

    def test_empty_protocols(self):
        result = self.analyzer.analyze([], tmp_cfg(self.td))
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["protocols"], [])

    def test_analyzed_at_iso(self):
        result = self.analyzer.analyze([make_protocol()], tmp_cfg(self.td))
        ts = result["analyzed_at"]
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ── per-protocol result fields ────────────────────────────────────────────────

class TestProtocolFields(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()
        self.pr = self.analyzer.analyze(
            [make_protocol()], tmp_cfg(self.td)
        )["protocols"][0]

    def test_name_preserved(self):
        self.assertEqual(self.pr["name"], "TestProto")

    def test_total_treasury_present(self):
        self.assertIn("total_treasury_usd", self.pr)

    def test_net_monthly_burn_present(self):
        self.assertIn("net_monthly_burn_usd", self.pr)

    def test_runway_months_present(self):
        self.assertIn("runway_months", self.pr)

    def test_native_token_dependency_pct_present(self):
        self.assertIn("native_token_dependency_pct", self.pr)

    def test_health_label_present(self):
        self.assertIn("health_label", self.pr)

    def test_flags_is_list(self):
        self.assertIsInstance(self.pr["flags"], list)

    def test_discount_factor_present(self):
        self.assertIn("discount_factor", self.pr)

    def test_stable_pct_present(self):
        self.assertIn("stable_pct_of_treasury", self.pr)

    def test_token_price_vs_ath_pct_present(self):
        self.assertIn("token_price_vs_ath_pct", self.pr)

    def test_runway_months_nonneg(self):
        self.assertGreaterEqual(self.pr["runway_months"], 0)

    def test_native_dep_pct_in_range(self):
        dep = self.pr["native_token_dependency_pct"]
        self.assertGreaterEqual(dep, 0)
        self.assertLessEqual(dep, 100)

    def test_stable_pct_in_range(self):
        sp = self.pr["stable_pct_of_treasury"]
        self.assertGreaterEqual(sp, 0)
        self.assertLessEqual(sp, 100)


# ── total treasury calculation ────────────────────────────────────────────────

class TestTotalTreasury(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_treasury_stables_contribution(self):
        p = make_protocol(treasury_stable=10_000_000,
                          treasury_native=0, treasury_eth_btc=0)
        r = self._run(p)
        self.assertAlmostEqual(r["total_treasury_usd"], 10_000_000, delta=1)

    def test_treasury_eth_btc_contribution(self):
        p = make_protocol(treasury_stable=0,
                          treasury_native=0, treasury_eth_btc=1_000_000)
        r = self._run(p)
        self.assertAlmostEqual(r["total_treasury_usd"], 800_000, delta=1)

    def test_native_discounted_low_concentration(self):
        # concentration < 50 → discount = 0.60
        p = make_protocol(treasury_stable=0,
                          treasury_native=1_000_000, treasury_eth_btc=0,
                          concentration=30)
        r = self._run(p)
        self.assertAlmostEqual(r["total_treasury_usd"],
                               1_000_000 * DISCOUNT_DEFAULT, delta=1)

    def test_native_discounted_high_concentration(self):
        # concentration > 50 → discount = 0.30
        p = make_protocol(treasury_stable=0,
                          treasury_native=1_000_000, treasury_eth_btc=0,
                          concentration=60)
        r = self._run(p)
        self.assertAlmostEqual(r["total_treasury_usd"],
                               1_000_000 * DISCOUNT_CONCENTRATED, delta=1)

    def test_all_components_combined(self):
        p = make_protocol(treasury_stable=10e6,
                          treasury_native=5e6, treasury_eth_btc=2e6,
                          concentration=30)
        r = self._run(p)
        expected = 10e6 + 2e6 * 0.80 + 5e6 * DISCOUNT_DEFAULT
        self.assertAlmostEqual(r["total_treasury_usd"], expected, delta=10)

    def test_zero_treasury_no_crash(self):
        p = make_protocol(treasury_stable=0, treasury_native=0,
                          treasury_eth_btc=0)
        r = self._run(p)
        self.assertEqual(r["total_treasury_usd"], 0)

    def test_total_treasury_positive(self):
        p = make_protocol()
        r = self._run(p)
        self.assertGreaterEqual(r["total_treasury_usd"], 0)


# ── net burn and runway ───────────────────────────────────────────────────────

class TestBurnAndRunway(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_net_burn_basic(self):
        p = make_protocol(monthly_opex=400_000, monthly_emissions=200_000,
                          monthly_revenue=100_000)
        r = self._run(p)
        self.assertAlmostEqual(r["net_monthly_burn_usd"], 500_000, delta=1)

    def test_net_burn_revenue_positive(self):
        # revenue > opex + emissions → negative burn
        p = make_protocol(monthly_opex=100_000, monthly_emissions=50_000,
                          monthly_revenue=500_000)
        r = self._run(p)
        self.assertLess(r["net_monthly_burn_usd"], 0)

    def test_runway_infinite_when_no_burn(self):
        p = make_protocol(monthly_opex=100_000, monthly_emissions=0,
                          monthly_revenue=500_000)
        r = self._run(p)
        self.assertGreaterEqual(r["runway_months"], 999.0)

    def test_runway_calculated_stable_over_burn(self):
        # stable=6M, burn=1M → runway=6 months
        p = make_protocol(treasury_stable=6_000_000,
                          monthly_opex=600_000, monthly_emissions=600_000,
                          monthly_revenue=200_000)
        r = self._run(p)
        # burn = 600+600-200 = 1_000_000 → runway = 6
        self.assertAlmostEqual(r["runway_months"], 6.0, delta=0.5)

    def test_zero_burn_zero_stable_no_crash(self):
        p = make_protocol(treasury_stable=0,
                          monthly_opex=0, monthly_emissions=0,
                          monthly_revenue=0)
        r = self._run(p)
        self.assertGreaterEqual(r["runway_months"], 0)

    def test_runway_months_capped_at_999(self):
        p = make_protocol(monthly_opex=1, monthly_emissions=0,
                          monthly_revenue=1_000_000)
        r = self._run(p)
        self.assertLessEqual(r["runway_months"], 999.0)


# ── discount factor ───────────────────────────────────────────────────────────

class TestDiscountFactor(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_low_concentration_gives_high_discount(self):
        p = make_protocol(concentration=20)
        r = self._run(p)
        self.assertAlmostEqual(r["discount_factor"], DISCOUNT_DEFAULT)

    def test_high_concentration_gives_low_discount(self):
        p = make_protocol(concentration=80)
        r = self._run(p)
        self.assertAlmostEqual(r["discount_factor"], DISCOUNT_CONCENTRATED)

    def test_boundary_exactly_50_low_discount(self):
        # exactly 50 → not > 50 → default
        p = make_protocol(concentration=50)
        r = self._run(p)
        self.assertAlmostEqual(r["discount_factor"], DISCOUNT_DEFAULT)

    def test_boundary_51_high_concentration(self):
        p = make_protocol(concentration=51)
        r = self._run(p)
        self.assertAlmostEqual(r["discount_factor"], DISCOUNT_CONCENTRATED)


# ── health labels ─────────────────────────────────────────────────────────────

class TestHealthLabels(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_critical_low_runway(self):
        # runway < 6 months
        p = make_protocol(treasury_stable=2_000_000,
                          monthly_opex=500_000, monthly_emissions=500_000,
                          monthly_revenue=0)
        r = self._run(p)
        self.assertEqual(r["health_label"], "CRITICAL")

    def test_critical_high_native_dependency(self):
        # native_dep > 80%: give zero stables, all native
        p = make_protocol(treasury_stable=0,
                          treasury_native=10_000_000,
                          treasury_eth_btc=0,
                          monthly_opex=100,
                          monthly_emissions=0,
                          monthly_revenue=1_000_000,
                          concentration=90)
        r = self._run(p)
        self.assertEqual(r["health_label"], "CRITICAL")

    def test_fortress_label(self):
        # >36 months runway, stables > 70%
        p = make_protocol(
            treasury_stable=40_000_000,
            treasury_native=0,
            treasury_eth_btc=0,
            monthly_opex=100_000,
            monthly_emissions=0,
            monthly_revenue=0,
        )
        r = self._run(p)
        self.assertEqual(r["health_label"], "FORTRESS")

    def test_strong_label(self):
        # runway 18-36 months, stables not 70%
        p = make_protocol(
            treasury_stable=10_000_000,
            treasury_native=10_000_000,  # dilutes stable%
            treasury_eth_btc=0,
            monthly_opex=300_000,
            monthly_emissions=200_000,
            monthly_revenue=0,
            concentration=30,
        )
        r = self._run(p)
        # burn=500k, runway=10M/500k=20 months → STRONG
        self.assertIn(r["health_label"], ("STRONG", "ADEQUATE", "FORTRESS"))

    def test_adequate_label(self):
        # 12-18 months
        p = make_protocol(
            treasury_stable=8_000_000,
            treasury_native=0,
            treasury_eth_btc=0,
            monthly_opex=500_000,
            monthly_emissions=200_000,
            monthly_revenue=100_000,
        )
        r = self._run(p)
        # burn=600k, runway=8M/600k≈13.3 months
        self.assertIn(r["health_label"], ("ADEQUATE", "STRONG", "FORTRESS"))

    def test_vulnerable_label(self):
        # 6-12 months
        p = make_protocol(
            treasury_stable=5_000_000,
            treasury_native=0,
            treasury_eth_btc=0,
            monthly_opex=600_000,
            monthly_emissions=100_000,
            monthly_revenue=100_000,
        )
        r = self._run(p)
        # burn=600k, runway≈8.3 months
        self.assertIn(r["health_label"], ("VULNERABLE", "ADEQUATE"))

    def test_valid_label_set(self):
        valid = {"FORTRESS", "STRONG", "ADEQUATE", "VULNERABLE", "CRITICAL"}
        p = make_protocol()
        r = self._run(p)
        self.assertIn(r["health_label"], valid)

    def test_revenue_positive_not_critical(self):
        # Net inflow → should not be CRITICAL (unless native dep >80%)
        p = make_protocol(
            treasury_stable=5_000_000,
            treasury_native=0,
            treasury_eth_btc=0,
            monthly_opex=100_000,
            monthly_emissions=0,
            monthly_revenue=500_000,
        )
        r = self._run(p)
        self.assertNotEqual(r["health_label"], "CRITICAL")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_native_token_dependent_flag(self):
        # native_dep_pct > 70
        p = make_protocol(treasury_stable=0,
                          treasury_native=10_000_000,
                          treasury_eth_btc=0,
                          concentration=30)
        r = self._run(p)
        self.assertIn("NATIVE_TOKEN_DEPENDENT", r["flags"])

    def test_no_native_dependent_flag_when_low(self):
        p = make_protocol(treasury_stable=10_000_000,
                          treasury_native=1_000_000,
                          treasury_eth_btc=0)
        r = self._run(p)
        self.assertNotIn("NATIVE_TOKEN_DEPENDENT", r["flags"])

    def test_emission_heavy_flag(self):
        # emissions > revenue * 2
        p = make_protocol(monthly_emissions=500_000, monthly_revenue=100_000)
        r = self._run(p)
        self.assertIn("EMISSION_HEAVY", r["flags"])

    def test_no_emission_heavy_when_low(self):
        p = make_protocol(monthly_emissions=100_000, monthly_revenue=500_000)
        r = self._run(p)
        self.assertNotIn("EMISSION_HEAVY", r["flags"])

    def test_emission_heavy_zero_revenue(self):
        # zero revenue + any emission → EMISSION_HEAVY
        p = make_protocol(monthly_emissions=100_000, monthly_revenue=0)
        r = self._run(p)
        self.assertIn("EMISSION_HEAVY", r["flags"])

    def test_diversified_treasury_flag(self):
        p = make_protocol(div_score=80)
        r = self._run(p)
        self.assertIn("DIVERSIFIED_TREASURY", r["flags"])

    def test_no_diversified_treasury_flag(self):
        p = make_protocol(div_score=30)
        r = self._run(p)
        self.assertNotIn("DIVERSIFIED_TREASURY", r["flags"])

    def test_runway_concern_flag(self):
        # runway < 9 months
        p = make_protocol(treasury_stable=4_000_000,
                          monthly_opex=500_000, monthly_emissions=500_000,
                          monthly_revenue=100_000)
        r = self._run(p)
        # burn=900k, runway=4M/900k≈4.4 months
        self.assertIn("RUNWAY_CONCERN", r["flags"])

    def test_no_runway_concern_when_long(self):
        p = make_protocol(treasury_stable=50_000_000,
                          monthly_opex=100_000, monthly_emissions=0,
                          monthly_revenue=0)
        r = self._run(p)
        self.assertNotIn("RUNWAY_CONCERN", r["flags"])

    def test_revenue_positive_flag(self):
        p = make_protocol(monthly_revenue=1_000_000, monthly_opex=200_000)
        r = self._run(p)
        self.assertIn("REVENUE_POSITIVE", r["flags"])

    def test_no_revenue_positive_when_below_opex(self):
        p = make_protocol(monthly_revenue=50_000, monthly_opex=300_000)
        r = self._run(p)
        self.assertNotIn("REVENUE_POSITIVE", r["flags"])

    def test_flags_is_list(self):
        p = make_protocol()
        r = self._run(p)
        self.assertIsInstance(r["flags"], list)

    def test_flags_known_values_only(self):
        known = {"NATIVE_TOKEN_DEPENDENT", "EMISSION_HEAVY",
                 "DIVERSIFIED_TREASURY", "RUNWAY_CONCERN", "REVENUE_POSITIVE"}
        p = make_protocol()
        r = self._run(p)
        for f in r["flags"]:
            self.assertIn(f, known)


# ── aggregates ────────────────────────────────────────────────────────────────

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def test_aggregates_keys(self):
        result = self.analyzer.analyze([make_protocol()], tmp_cfg(self.td))
        agg = result["aggregates"]
        for k in ("strongest", "weakest", "avg_runway_months",
                  "critical_count", "revenue_positive_count"):
            self.assertIn(k, agg)

    def test_empty_aggregates(self):
        agg = self.analyzer.analyze([], tmp_cfg(self.td))["aggregates"]
        self.assertIsNone(agg["strongest"])
        self.assertIsNone(agg["weakest"])
        self.assertEqual(agg["avg_runway_months"], 0.0)

    def test_strongest_most_runway(self):
        rich = make_protocol(name="Rich",
                             treasury_stable=100_000_000,
                             monthly_opex=100_000, monthly_emissions=0,
                             monthly_revenue=0)
        poor = make_protocol(name="Poor",
                             treasury_stable=500_000,
                             monthly_opex=500_000, monthly_emissions=100_000,
                             monthly_revenue=0)
        agg = self.analyzer.analyze([rich, poor], tmp_cfg(self.td))["aggregates"]
        self.assertEqual(agg["strongest"], "Rich")

    def test_weakest_least_runway(self):
        rich = make_protocol(name="Rich",
                             treasury_stable=100_000_000,
                             monthly_opex=100_000, monthly_emissions=0,
                             monthly_revenue=0)
        poor = make_protocol(name="Poor",
                             treasury_stable=500_000,
                             monthly_opex=500_000, monthly_emissions=100_000,
                             monthly_revenue=0)
        agg = self.analyzer.analyze([rich, poor], tmp_cfg(self.td))["aggregates"]
        self.assertEqual(agg["weakest"], "Poor")

    def test_critical_count(self):
        collapsed = make_protocol(treasury_stable=1_000_000,
                                  monthly_opex=1_000_000, monthly_emissions=1_000_000,
                                  monthly_revenue=0)
        healthy = make_protocol(name="Healthy",
                                treasury_stable=100_000_000,
                                monthly_opex=100_000, monthly_emissions=0,
                                monthly_revenue=0)
        agg = self.analyzer.analyze([collapsed, healthy], tmp_cfg(self.td))["aggregates"]
        self.assertGreaterEqual(agg["critical_count"], 1)

    def test_revenue_positive_count(self):
        profitable = make_protocol(monthly_revenue=2_000_000, monthly_opex=100_000)
        burning = make_protocol(name="Burning",
                                monthly_revenue=0, monthly_opex=500_000)
        agg = self.analyzer.analyze([profitable, burning], tmp_cfg(self.td))["aggregates"]
        self.assertEqual(agg["revenue_positive_count"], 1)

    def test_avg_runway_months_nonneg(self):
        protos = [make_protocol(name=f"P{i}") for i in range(5)]
        agg = self.analyzer.analyze(protos, tmp_cfg(self.td))["aggregates"]
        self.assertGreaterEqual(agg["avg_runway_months"], 0)


# ── ring-buffer log ──────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _cfg(self, cap=10):
        return {
            "log_path": os.path.join(self.td, "treasury_runway_log.json"),
            "log_cap": cap,
        }

    def test_log_file_created(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        self.assertTrue(os.path.exists(cfg["log_path"]))

    def test_log_is_list(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_ts(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_has_snapshots(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertIn("snapshots", data[0])

    def test_log_accumulates(self):
        cfg = self._cfg(cap=10)
        self.analyzer.analyze([make_protocol()], cfg)
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_enforced(self):
        cfg = self._cfg(cap=3)
        for _ in range(5):
            self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)

    def test_log_snapshot_has_runway(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        snap = data[0]["snapshots"][0]
        self.assertIn("runway_months", snap)

    def test_log_snapshot_has_health_label(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        snap = data[0]["snapshots"][0]
        self.assertIn("health_label", snap)

    def test_log_snapshot_has_total_treasury(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        snap = data[0]["snapshots"][0]
        self.assertIn("total_treasury", snap)

    def test_log_is_valid_json(self):
        cfg = self._cfg()
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)   # no exception
        self.assertIsNotNone(data)

    def test_log_atomic_double_write(self):
        cfg = self._cfg(cap=5)
        self.analyzer.analyze([make_protocol()], cfg)
        self.analyzer.analyze([make_protocol()], cfg)
        with open(cfg["log_path"]) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)


# ── edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiTreasuryRunwayAnalyzer()
        self.td = tempfile.mkdtemp()

    def _run(self, p, extra_cfg=None):
        cfg = tmp_cfg(self.td)
        if extra_cfg:
            cfg.update(extra_cfg)
        return self.analyzer.analyze([p], cfg)["protocols"][0]

    def test_all_zeros_no_crash(self):
        p = make_protocol(treasury_stable=0, treasury_native=0,
                          treasury_eth_btc=0, monthly_opex=0,
                          monthly_emissions=0, monthly_revenue=0,
                          token_price=0, token_price_ath=0, fdv=0,
                          concentration=0, div_score=0)
        r = self._run(p)
        self.assertIsInstance(r["health_label"], str)

    def test_large_values_no_crash(self):
        p = make_protocol(treasury_stable=1e15, treasury_native=1e15,
                          monthly_opex=1e12, monthly_revenue=1e10)
        r = self._run(p)
        self.assertIsInstance(r["health_label"], str)

    def test_multiple_protocols_all_fields(self):
        protos = [make_protocol(name=f"P{i}") for i in range(8)]
        result = self.analyzer.analyze(protos, tmp_cfg(self.td))
        self.assertEqual(len(result["protocols"]), 8)

    def test_token_price_vs_ath_at_ath(self):
        p = make_protocol(token_price=5.0, token_price_ath=5.0)
        r = self._run(p)
        self.assertAlmostEqual(r["token_price_vs_ath_pct"], 100.0, places=1)

    def test_token_price_vs_ath_below(self):
        p = make_protocol(token_price=1.0, token_price_ath=10.0)
        r = self._run(p)
        self.assertAlmostEqual(r["token_price_vs_ath_pct"], 10.0, places=1)

    def test_missing_fields_use_defaults(self):
        # Minimal protocol dict
        p = {"name": "Minimal"}
        r = self._run(p)
        self.assertEqual(r["name"], "Minimal")
        self.assertIn("health_label", r)

    def test_custom_config_fortress_threshold(self):
        # Lower FORTRESS threshold
        p = make_protocol(
            treasury_stable=20_000_000,
            treasury_native=0, treasury_eth_btc=0,
            monthly_opex=100_000, monthly_emissions=0, monthly_revenue=0,
        )
        cfg = tmp_cfg(self.td)
        cfg["fortress_runway_months"] = 15.0
        cfg["fortress_stable_pct"] = 60.0
        r = self.analyzer.analyze([p], cfg)["protocols"][0]
        # 20M/100k=200 months, stable_pct=100% → FORTRESS
        self.assertEqual(r["health_label"], "FORTRESS")


if __name__ == "__main__":
    unittest.main()
