#!/usr/bin/env python3
"""Tests for spa_core.strategy_lab.aggressive_lab.scorecard — the multi-metric honest tournament.

Covers the SMOKE (the scorecard ranks the roster with return+risk+tail on real data) and the
RED-TEAM (fat-APY/catastrophic-tail surfaced; thin → INSUFFICIENT_DATA; pure ETH-beta flagged).

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_scorecard.py -q
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx
from spa_core.strategy_lab.aggressive_lab import scorecard as sc
from spa_core.strategy_lab.aggressive_lab import loader as ld

INSUFFICIENT = sc.INSUFFICIENT


class TestScorecard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="aggr_lab_test_"))
        fx.materialize(cls.tmp)
        cls.doc = sc.build_scorecard(data_dir=cls.tmp, use_fixture_if_empty=False,
                                     write=False, now_iso="2026-06-30T00:00:00+00:00")
        cls.by_id = {e["strategy_id"]: e for e in cls.doc["strategies"]}

    # ── SMOKE ───────────────────────────────────────────────────────────────────
    def test_smoke_ranks_full_roster(self):
        self.assertEqual(self.doc["n_strategies"], len(fx.roster()))
        for e in self.doc["strategies"]:
            # return + risk + tail + class all present per strategy
            self.assertIn("realized_apy_pct", e)
            self.assertIn("sharpe", e)
            self.assertIn("tail", e)
            self.assertIn("worst_tail_dd_pct", e["tail"])
            self.assertIn("risk_class", e)
            self.assertIn("verdict", e)

    def test_multiple_sort_orders_not_single_leaderboard(self):
        so = self.doc["sort_orders"]
        self.assertIn("by_return_desc", so)
        self.assertIn("by_sharpe_desc", so)
        self.assertIn("by_tail_asc", so)
        # not a single yield-sorted leaderboard: the return order differs from the tail order
        self.assertNotEqual(so["by_return_desc"], so["by_tail_asc"])

    def test_tier_assignment_attached_per_strategy(self):
        """6mo-M1/M2 #1+#2: each scorecard entry carries its enforced tier + eligibility. (Live-roster
        books resolve a tier via tier_policy; fixture-only ids not in the live roster resolve to None
        gracefully — never a crash or a fabricated tier.)"""
        for e in self.doc["strategies"]:
            self.assertIn("tier", e)
            self.assertIn("tier_eligible", e)
            self.assertIn("tier_violations", e)
        # susde_dn (hedged) is Balanced-eligible; leverage_loop (loops) is Aggressive-eligible
        self.assertEqual(self.by_id["susde_dn"]["tier"], "balanced")
        self.assertTrue(self.by_id["susde_dn"]["tier_eligible"])
        self.assertEqual(self.by_id["leverage_loop"]["tier"], "aggressive")
        self.assertTrue(self.by_id["leverage_loop"]["tier_eligible"])
        # a fixture-only strategy not in the live roster → tier None (graceful, not fabricated)
        if "thin_new" in self.by_id:
            self.assertIsNone(self.by_id["thin_new"]["tier"])

    def test_tier_summary_rollup(self):
        ts = self.doc["tier_summary"]
        self.assertIn("eligible_by_tier", ts)
        self.assertIn("susde_dn", ts["eligible_by_tier"].get("balanced", []))
        self.assertIn("leverage_loop", ts["eligible_by_tier"].get("aggressive", []))

    def test_advisory_guardrail_stamps(self):
        self.assertTrue(self.doc["is_advisory"])
        self.assertTrue(self.doc["outside_riskpolicy"])
        self.assertTrue(self.doc["separate_from_golive_track"])
        for e in self.doc["strategies"]:
            self.assertTrue(e["is_advisory"])
            self.assertTrue(e["outside_riskpolicy"])
            self.assertTrue(e["owner_selectable"])

    def test_byte_stable_from_fixed_inputs(self):
        """Determinism: same inputs + injected now_iso → identical doc."""
        again = sc.build_scorecard(data_dir=self.tmp, use_fixture_if_empty=False,
                                   write=False, now_iso="2026-06-30T00:00:00+00:00")
        self.assertEqual(again, self.doc)

    # ── RED-TEAM ─────────────────────────────────────────────────────────────────
    def test_redteam_fat_apy_catastrophic_tail_surfaced(self):
        """lrt_carry has a fat ~13% headline but a catastrophic Apr-2026 depeg → the tail MUST be
        surfaced prominently and the verdict MUST reflect the tail (SEVERE_TAIL), not the yield."""
        e = self.by_id["lrt_carry"]
        self.assertGreaterEqual(e["tail"]["worst_tail_dd_pct"], sc.SEVERE_TAIL_DD_PCT)
        self.assertEqual(e["verdict"], "SEVERE_TAIL")
        # the specific window's in-sample tail is visible
        rseth = next(w for w in e["tail"]["windows"] if w["key"] == "rseth_depeg_2026_04")
        self.assertIsNotNone(rseth["in_sample"])
        # a real, material depeg drawdown is surfaced for the window (honestly less than the nominal
        # window-loss after the multiplicative front-load + drift, but clearly shown) AND the depeg
        # shape-shock pushes the strategy's worst tail past the severe band → the tail is NOT buried.
        self.assertGreater(rseth["in_sample"]["worst_dd_pct"], 5.0)

    def test_redteam_thin_track_insufficient_data(self):
        """thin_new has only 6 forward days, no backtest → INSUFFICIENT_DATA, no degenerate Sharpe."""
        e = self.by_id["thin_new"]
        self.assertFalse(e["trustworthy"])
        self.assertEqual(e["sharpe"], INSUFFICIENT)
        self.assertEqual(e["verdict"], "INSUFFICIENT_DATA")

    def test_redteam_pure_eth_beta_flagged(self):
        """variant_d is secretly pure ETH beta → flagged risk_class B (directional), not alpha."""
        e = self.by_id["variant_d"]
        self.assertEqual(e["risk_class"], "B")
        self.assertIn("beta", e["risk_class_label"].lower())
        self.assertNotEqual(e["risk_class"], "A")
        # and its big directional tail is surfaced (it moves with the market)
        self.assertGreater(e["tail"]["worst_tail_dd_pct"], 15.0)

    def test_incentive_class_flagged(self):
        """points_farm is RiskClass D (incentive) → flagged INCENTIVE_DECAY even if return looks good."""
        e = self.by_id["points_farm"]
        self.assertEqual(e["risk_class"], "D")
        self.assertEqual(e["verdict"], "INCENTIVE_DECAY")

    def test_susde_dn_shows_tail_next_to_yield(self):
        """The canonical case: 11% sUSDe DN shows its Oct-2025 funding-flip tail next to the yield."""
        e = self.by_id["susde_dn"]
        self.assertEqual(e["headline_apy_pct"], 11.0)
        self.assertGreater(e["tail"]["worst_in_sample_dd_pct"], 0.0)
        usde = next(w for w in e["tail"]["windows"] if w["key"] == "usde_unwind_2025_10")
        self.assertIsNotNone(usde["in_sample"])


class TestLoaderFailClosed(unittest.TestCase):
    def test_malformed_jsonl_lines_dropped_and_counted(self):
        tmp = Path(tempfile.mkdtemp(prefix="aggr_lab_loader_"))
        sdir = tmp / "broken"
        sdir.mkdir(parents=True)
        (sdir / "realized_series.jsonl").write_text(
            '{"date":"2026-01-01","equity_usd":100000,"phase":"forward"}\n'
            'NOT JSON AT ALL\n'
            '{"date":"2026-01-02","equity_usd":"oops","phase":"forward"}\n'
            '{"date":"2026-01-03","equity_usd":100200,"phase":"forward"}\n',
            encoding="utf-8")
        s = ld.load_strategy("broken", data_dir=tmp)
        self.assertEqual(s.n_malformed_lines, 2)   # the bad-json + the bad-equity line
        self.assertEqual(s.forward.n_points, 2)

    def test_missing_files_empty_tracks(self):
        tmp = Path(tempfile.mkdtemp(prefix="aggr_lab_missing_"))
        s = ld.load_strategy("nope", data_dir=tmp)
        self.assertEqual(s.forward.n_points, 0)
        self.assertEqual(s.backtest.n_points, 0)


if __name__ == "__main__":
    unittest.main()
