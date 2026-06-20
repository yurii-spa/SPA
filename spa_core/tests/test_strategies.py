"""
Tests for the Multi-Strategy Shadow Framework (Sprint A / v3.90).

Stdlib-only ``unittest`` (pytest is not installed in this repo). Self-contained:
all I/O is redirected into a throw-away temp directory, so the tests never read
or write the real ``data/`` tree and require no network.

Run::
    python3 -m unittest spa_core/tests/test_strategies.py -v
    python3 spa_core/tests/test_strategies.py
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.base import (
    active_pools,
    apply_risk_policy,
    normalize,
    pool_apy_history,
    tier_map,
    MAX_CONCENTRATION_T2,
    MAX_CONCENTRATION_T1,
)
from spa_core.strategies.vportfolio import VirtualPortfolio, EQUITY_CURVE_MAX
from spa_core.strategies.baseline import BaselineStrategy
from spa_core.strategies.concentration import ConcentrationStrategy
from spa_core.strategies.momentum import APYMomentumStrategy
from spa_core.strategies.risk_parity import RiskParityPlusStrategy
from spa_core.strategies.kelly import HalfKellyStrategy
from spa_core.strategies.yield_spread import YieldSpreadStrategy
from spa_core.strategies import STRATEGY_REGISTRY, Strategy
from spa_core.strategies import runner as runner_mod
from spa_core.strategies import comparator as comp_mod


def _adapter(protocol, apy, tier="T2", status="ok", health=1.0):
    return {
        "protocol": protocol,
        "tier": tier,
        "apy_pct": apy,
        "status": status,
        "health_score": health,
    }


def _snapshot(adapters, ts="2026-06-09T00:00:00+00:00"):
    return {"run_ts": ts, "adapters": adapters}


# A representative 4×T2 snapshot mirroring the real orchestrator output.
SNAP_4 = _snapshot(
    [
        _adapter("morpho_blue", 8.3),
        _adapter("yearn_v3", 7.2),
        _adapter("euler_v2", 9.1),
        _adapter("maple", 10.5),
    ]
)


class BaseHelpersTest(unittest.TestCase):
    def test_active_pools_filters_non_ok_and_nonpositive(self):
        snap = _snapshot(
            [
                _adapter("a", 5.0),
                _adapter("b", 0.0),            # non-positive APY -> excluded
                _adapter("c", 6.0, status="error"),  # not ok -> excluded
                _adapter("d", None),           # missing APY -> excluded
            ]
        )
        ids = {p["pool_id"] for p in active_pools(snap)}
        self.assertEqual(ids, {"a"})

    def test_tier_map_defaults_unknown_to_t2(self):
        snap = _snapshot([_adapter("a", 5.0, tier="T1"), {"protocol": "b", "apy_pct": 3}])
        tm = tier_map(snap)
        self.assertEqual(tm["a"], "T1")
        self.assertEqual(tm["b"], "T2")

    def test_normalize_sums_to_one(self):
        out = normalize({"a": 2.0, "b": 2.0, "c": 0.0})
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertNotIn("c", out)

    def test_normalize_empty_on_no_mass(self):
        self.assertEqual(normalize({"a": 0.0, "b": -1.0}), {})

    def test_pool_apy_history_extracts_series(self):
        history = [
            {"adapters": [_adapter("a", 5.0), _adapter("b", 9.0)]},
            {"summary": {}},  # summary-only run -> skipped
            {"adapters": [_adapter("a", 6.0)]},
        ]
        series = pool_apy_history(history)
        self.assertEqual(series["a"], [5.0, 6.0])
        self.assertEqual(series["b"], [9.0])


class RiskPolicyTest(unittest.TestCase):
    def test_risk_policy_cap_t2(self):
        """No T2 pool may exceed 0.20 after the guard."""
        weights = {"morpho_blue": 0.5, "yearn_v3": 0.3, "euler_v2": 0.2}
        capped = apply_risk_policy(weights, tier_map(SNAP_4))
        for v in capped.values():
            self.assertLessEqual(v, MAX_CONCENTRATION_T2 + 1e-12)

    def test_risk_policy_cap_t1(self):
        snap = _snapshot([_adapter("aave", 5.0, tier="T1")])
        capped = apply_risk_policy({"aave": 0.9}, tier_map(snap))
        self.assertAlmostEqual(capped["aave"], MAX_CONCENTRATION_T1, places=9)

    def test_risk_policy_idempotent(self):
        caps = tier_map(SNAP_4)
        once = apply_risk_policy({"morpho_blue": 0.5}, caps)
        twice = apply_risk_policy(once, caps)
        self.assertEqual(once, twice)

    def test_risk_policy_drops_nonpositive(self):
        capped = apply_risk_policy({"a": -0.1, "b": 0.0, "c": 0.15}, {"c": "T2"})
        self.assertEqual(set(capped), {"c"})

    def test_risk_policy_only_reduces(self):
        caps = tier_map(SNAP_4)
        capped = apply_risk_policy({"morpho_blue": 0.10}, caps)
        self.assertAlmostEqual(capped["morpho_blue"], 0.10, places=9)


class BaselineTest(unittest.TestCase):
    def test_baseline_equal_weight(self):
        w = BaselineStrategy().target_weights(SNAP_4, {})
        self.assertEqual(len(w), 4)
        vals = list(w.values())
        for v in vals:
            self.assertAlmostEqual(v, vals[0], places=9)  # all equal

    def test_baseline_empty_snapshot(self):
        self.assertEqual(BaselineStrategy().target_weights(_snapshot([]), {}), {})

    def test_baseline_sum_within_one(self):
        w = BaselineStrategy().target_weights(SNAP_4, {})
        self.assertLessEqual(sum(w.values()), 1.0 + 1e-12)


class ConcentrationTest(unittest.TestCase):
    def test_concentration_top1(self):
        w = ConcentrationStrategy().target_weights(SNAP_4, {})
        # maple has the highest APY (10.5) -> top-1 -> 50%.
        self.assertAlmostEqual(w["maple"], 0.50, places=9)
        self.assertAlmostEqual(w["euler_v2"], 0.30, places=9)  # top-2
        self.assertLessEqual(sum(w.values()), 1.0 + 1e-12)

    def test_concentration_remainder_split(self):
        w = ConcentrationStrategy().target_weights(SNAP_4, {})
        # morpho_blue (8.3) and yearn_v3 (7.2) split the remaining 20%.
        self.assertAlmostEqual(w["morpho_blue"], 0.10, places=9)
        self.assertAlmostEqual(w["yearn_v3"], 0.10, places=9)

    def test_concentration_single_pool(self):
        snap = _snapshot([_adapter("solo", 6.0)])
        w = ConcentrationStrategy().target_weights(snap, {})
        self.assertEqual(w, {"solo": 0.60})


class MomentumTest(unittest.TestCase):
    def test_momentum_fallback(self):
        """Fewer than 3 runs -> equal weight."""
        history = [{"adapters": [_adapter("morpho_blue", 5.0)]}]  # 1 run
        w = APYMomentumStrategy().target_weights(SNAP_4, {"history": history})
        vals = list(w.values())
        self.assertEqual(len(vals), 4)
        for v in vals:
            self.assertAlmostEqual(v, vals[0], places=9)

    def test_momentum_positive_only(self):
        # History where morpho rises strongly and others sit at current APY.
        history = []
        for _ in range(4):
            history.append(
                {
                    "adapters": [
                        _adapter("morpho_blue", 2.0),  # baseline low -> positive momentum
                        _adapter("yearn_v3", 7.2),     # flat -> zero momentum
                        _adapter("euler_v2", 9.1),
                        _adapter("maple", 10.5),
                    ]
                }
            )
        w = APYMomentumStrategy().target_weights(SNAP_4, {"history": history})
        # Only morpho_blue has positive delta (8.3 vs 2.0) -> it gets all weight.
        self.assertAlmostEqual(w.get("morpho_blue", 0.0), 1.0, places=6)
        self.assertNotIn("yearn_v3", w)

    def test_momentum_all_flat_fallback(self):
        history = [
            {"adapters": [_adapter("morpho_blue", 8.3), _adapter("maple", 10.5)]}
            for _ in range(5)
        ]
        snap = _snapshot([_adapter("morpho_blue", 8.3), _adapter("maple", 10.5)])
        w = APYMomentumStrategy().target_weights(snap, {"history": history})
        # No positive momentum -> equal weight fallback.
        self.assertAlmostEqual(w["morpho_blue"], 0.5, places=9)
        self.assertAlmostEqual(w["maple"], 0.5, places=9)


class RiskParityTest(unittest.TestCase):
    def _history(self, series_by_pool, n):
        runs = []
        for i in range(n):
            runs.append(
                {"adapters": [_adapter(pid, vals[i]) for pid, vals in series_by_pool.items()]}
            )
        return runs

    def test_risk_parity_inverse_vol(self):
        """Higher sigma -> lower weight."""
        # 'stable' barely moves; 'wild' swings a lot.
        stable = [7.0, 7.1, 6.9, 7.0, 7.05]
        wild = [5.0, 12.0, 4.0, 13.0, 6.0]
        history = self._history({"stable": stable, "wild": wild}, 5)
        snap = _snapshot([_adapter("stable", 7.0), _adapter("wild", 6.0)])
        w = RiskParityPlusStrategy().target_weights(snap, {"history": history})
        self.assertGreater(w["stable"], w["wild"])
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)

    def test_risk_parity_fallback_short_history(self):
        history = [{"adapters": [_adapter("a", 5.0), _adapter("b", 6.0)]}]
        snap = _snapshot([_adapter("a", 5.0), _adapter("b", 6.0)])
        w = RiskParityPlusStrategy().target_weights(snap, {"history": history})
        self.assertAlmostEqual(w["a"], 0.5, places=9)
        self.assertAlmostEqual(w["b"], 0.5, places=9)

    def test_risk_parity_zero_vol_fallback(self):
        # Constant series -> sigma 0 -> equal-weight fallback.
        flat = [7.0, 7.0, 7.0, 7.0]
        history = self._history({"a": flat, "b": flat}, 4)
        snap = _snapshot([_adapter("a", 7.0), _adapter("b", 7.0)])
        w = RiskParityPlusStrategy().target_weights(snap, {"history": history})
        self.assertAlmostEqual(w["a"], 0.5, places=9)


class KellyTest(unittest.TestCase):
    def test_kelly_zero_edge(self):
        """A pool with APY <= rf (4.0%) gets weight 0."""
        snap = _snapshot([_adapter("low", 3.5), _adapter("high", 10.0)])
        w = HalfKellyStrategy().target_weights(snap, {})
        self.assertNotIn("low", w)
        self.assertIn("high", w)

    def test_kelly_half_and_cap(self):
        snap = _snapshot([_adapter("rich", 50.0)])
        w = HalfKellyStrategy().target_weights(snap, {})
        # edge huge -> kelly capped at 0.25 -> half-kelly weight 0.125.
        self.assertAlmostEqual(w["rich"], 0.125, places=9)

    def test_kelly_formula(self):
        snap = _snapshot([_adapter("p", 5.0)])  # edge = 1.0, kelly = 1/2 = 0.5 -> cap 0.25
        w = HalfKellyStrategy().target_weights(snap, {})
        self.assertAlmostEqual(w["p"], 0.125, places=9)

    def test_kelly_at_risk_free_excluded(self):
        snap = _snapshot([_adapter("p", 4.0)])  # edge exactly 0 -> excluded
        self.assertEqual(HalfKellyStrategy().target_weights(snap, {}), {})


class YieldSpreadTest(unittest.TestCase):
    def test_yield_spread_median(self):
        """Pools below the median get weight 0."""
        # APYs 6,7,8,9 -> median 7.5; only 8 and 9 are above.
        snap = _snapshot(
            [_adapter("a", 6.0), _adapter("b", 7.0), _adapter("c", 8.0), _adapter("d", 9.0)]
        )
        w = YieldSpreadStrategy().target_weights(snap, {})
        self.assertNotIn("a", w)
        self.assertNotIn("b", w)
        self.assertIn("c", w)
        self.assertIn("d", w)

    def test_yield_spread_proportional(self):
        snap = _snapshot([_adapter("a", 6.0), _adapter("c", 8.0), _adapter("d", 10.0)])
        # median = 8.0; spreads: a<0 (drop), c=0 (drop), d=+2 -> d gets all.
        w = YieldSpreadStrategy().target_weights(snap, {})
        self.assertEqual(set(w), {"d"})

    def test_yield_spread_respects_cap(self):
        snap = _snapshot(
            [_adapter("a", 1.0), _adapter("b", 2.0), _adapter("c", 20.0), _adapter("d", 21.0)]
        )
        w = YieldSpreadStrategy().target_weights(snap, {})
        for v in w.values():
            self.assertLessEqual(v, MAX_CONCENTRATION_T2 + 1e-12)


class VirtualPortfolioTest(unittest.TestCase):
    def test_vportfolio_yield_accrual(self):
        vp = VirtualPortfolio("t", capital=100_000.0)
        # Step 1: allocate 100% to a 10.0% APY pool (no yield yet, no prior pos).
        snap = _snapshot([_adapter("p", 10.0)])
        vp.step(snap, {"p": 1.0}, "t0")
        self.assertAlmostEqual(vp.equity, 100_000.0, places=4)
        # Step 2: one day of yield on $100k at 10% APY = 100000*0.10/365.
        y = vp.step(snap, {"p": 1.0}, "t1")
        expected = 100_000.0 * 0.10 / 365.0
        self.assertAlmostEqual(y, expected, places=4)
        self.assertAlmostEqual(vp.equity, 100_000.0 + expected, places=4)

    def test_vportfolio_equity_curve_ringbuffer(self):
        vp = VirtualPortfolio("t")
        snap = _snapshot([_adapter("p", 5.0)])
        for i in range(EQUITY_CURVE_MAX + 25):
            vp.step(snap, {"p": 1.0}, f"t{i}")
        self.assertEqual(len(vp.equity_curve), EQUITY_CURVE_MAX)
        # The buffer keeps the most-recent points.
        self.assertEqual(vp.equity_curve[-1]["ts"], f"t{EQUITY_CURVE_MAX + 24}")

    def test_vportfolio_cash_buffer(self):
        vp = VirtualPortfolio("t")
        snap = _snapshot([_adapter("p", 5.0)])
        vp.step(snap, {"p": 0.6}, "t0")  # 60% deployed -> 40% cash
        self.assertAlmostEqual(vp.cash, 40_000.0, places=4)
        self.assertAlmostEqual(sum(vp.positions.values()), 60_000.0, places=4)

    def test_vportfolio_roundtrip_serialization(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            vp = VirtualPortfolio("x")
            vp.step(_snapshot([_adapter("p", 5.0)]), {"p": 0.5}, "t0")
            vp.save(p)
            loaded = VirtualPortfolio.load("x", p)
            self.assertAlmostEqual(loaded.equity, vp.equity, places=6)
            self.assertEqual(len(loaded.equity_curve), 1)

    def test_vportfolio_load_missing_is_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            vp = VirtualPortfolio.load("nope", Path(d) / "nope.json")
            self.assertEqual(vp.equity, 100_000.0)
            self.assertEqual(vp.equity_curve, [])

    def test_vportfolio_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.json"
            VirtualPortfolio("a").save(p)
            leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class RegistryTest(unittest.TestCase):
    def test_registry_has_six_strategies(self):
        names = [s.name for s in STRATEGY_REGISTRY]
        self.assertEqual(
            set(names),
            {
                "s0_baseline",
                "s1_concentration",
                "s2_momentum",
                "s3_risk_parity",
                "s4_kelly",
                "s5_yield_spread",
            },
        )

    def test_registry_protocol_conformance(self):
        for s in STRATEGY_REGISTRY:
            self.assertIsInstance(s, Strategy)
            self.assertIn(s.risk_level, {"low", "medium", "high"})
            self.assertTrue(s.label)


class _IsolatedIO(unittest.TestCase):
    """Base class that redirects runner/comparator I/O into a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.data_dir = d / "strategies"
        self.data_dir.mkdir(parents=True)
        self.snapshot_path = d / "adapter_orchestrator_status.json"
        self.history_path = d / "orchestrator_runs.json"
        self.snapshot_path.write_text(json.dumps(SNAP_4))
        self.history_path.write_text(json.dumps({"runs": [SNAP_4], "max_runs": 30}))

        # Redirect module-level paths.
        self._runner_dir = runner_mod._DATA_DIR
        self._runner_log = runner_mod._RUN_LOG
        runner_mod._DATA_DIR = self.data_dir
        runner_mod._RUN_LOG = self.data_dir / "run_log.json"
        import spa_core.strategies.vportfolio as vp_mod

        self._vp_dir = vp_mod._DATA_DIR
        vp_mod._DATA_DIR = self.data_dir

        self._comp_dir = comp_mod._DATA_DIR
        self._comp_out = comp_mod._OUTPUT
        comp_mod._DATA_DIR = self.data_dir
        comp_mod._OUTPUT = d / "strategy_shadow_comparison.json"
        self.output_path = comp_mod._OUTPUT

    def tearDown(self):
        runner_mod._DATA_DIR = self._runner_dir
        runner_mod._RUN_LOG = self._runner_log
        import spa_core.strategies.vportfolio as vp_mod

        vp_mod._DATA_DIR = self._vp_dir
        comp_mod._DATA_DIR = self._comp_dir
        comp_mod._OUTPUT = self._comp_out
        self._tmp.cleanup()


class RunnerTest(_IsolatedIO):
    def test_runner_all_strategies(self):
        results = runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        self.assertEqual(len(results), 6)
        for name in (s.name for s in STRATEGY_REGISTRY):
            self.assertIn(name, results)
            self.assertIn("equity", results[name])
            self.assertIn("weights", results[name])
            self.assertIn("yield_today", results[name])
            # Every persisted portfolio file exists.
            self.assertTrue((self.data_dir / f"{name}.json").exists())

    def test_runner_applies_guard(self):
        results = runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        # Concentration's raw 0.50 must be clipped to the 0.20 T2 cap.
        for w in results["s1_concentration"]["weights"].values():
            self.assertLessEqual(w, MAX_CONCENTRATION_T2 + 1e-9)

    def test_runner_persists_and_compounds(self):
        runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        r2 = runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        # Second step accrues yield -> baseline equity grows above the start.
        self.assertGreater(r2["s0_baseline"]["equity"], 100_000.0)

    def test_runner_run_log_ringbuffer(self):
        runner_mod.RUN_LOG_MAX  # sanity
        for _ in range(3):
            runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        log = json.loads((self.data_dir / "run_log.json").read_text())
        self.assertEqual(len(log["entries"]), 3)
        self.assertEqual(log["max_entries"], runner_mod.RUN_LOG_MAX)


class ComparatorTest(_IsolatedIO):
    def _build_curve(self, name, equities):
        curve = [{"ts": f"t{i}", "equity": e, "positions": {}} for i, e in enumerate(equities)]
        doc = {
            "name": name,
            "initial_capital": 100_000.0,
            "cash": 0.0,
            "positions": {},
            "equity": equities[-1],
            "last_ts": f"t{len(equities)-1}",
            "equity_curve": curve,
        }
        (self.data_dir / f"{name}.json").write_text(json.dumps(doc))

    def test_comparator_ranking(self):
        # Steady winner vs a volatile, lower-Sortino loser.
        self._build_curve("s3_risk_parity", [100_000, 100_100, 100_200, 100_300, 100_400, 100_500])
        self._build_curve("s1_concentration", [100_000, 99_000, 101_000, 99_500, 101_500, 100_400])
        doc = comp_mod.build_comparison("2026-06-09T00:00:00+00:00")
        self.assertEqual(doc["strategies"][0]["rank"], 1)
        # Steady riser (no downside) should outrank the volatile one.
        self.assertEqual(doc["best_strategy"], "s3_risk_parity")
        ranks = {r["name"]: r["rank"] for r in doc["strategies"]}
        self.assertLess(ranks["s3_risk_parity"], ranks["s1_concentration"])

    def test_comparator_null_sharpe(self):
        """Fewer than 5 points -> sharpe is null, not an error."""
        self._build_curve("s0_baseline", [100_000, 100_100, 100_050])  # 3 points
        doc = comp_mod.build_comparison("t")
        row = next(r for r in doc["strategies"] if r["name"] == "s0_baseline")
        self.assertIsNone(row["sharpe"])

    def test_comparator_sortino_present_with_enough_points(self):
        self._build_curve("s0_baseline", [100_000, 100_100, 99_900, 100_200, 100_050, 100_300])
        doc = comp_mod.build_comparison("t")
        row = next(r for r in doc["strategies"] if r["name"] == "s0_baseline")
        self.assertIsNotNone(row["sortino"])

    def test_comparator_pnl_and_drawdown(self):
        self._build_curve("s0_baseline", [100_000, 102_000, 101_000])
        doc = comp_mod.build_comparison("t")
        row = next(r for r in doc["strategies"] if r["name"] == "s0_baseline")
        self.assertAlmostEqual(row["pnl_pct"], 1.0, places=6)
        # peak 102000 -> trough 101000 = ~0.98% drawdown.
        self.assertAlmostEqual(row["max_drawdown"], (102_000 - 101_000) / 102_000, places=6)

    def test_comparator_ignores_run_log(self):
        (self.data_dir / "run_log.json").write_text(json.dumps({"entries": []}))
        self._build_curve("s0_baseline", [100_000, 100_100])
        doc = comp_mod.build_comparison("t")
        names = {r["name"] for r in doc["strategies"]}
        self.assertNotIn("run_log", names)

    def test_comparator_writes_atomically(self):
        self._build_curve("s0_baseline", [100_000, 100_100])
        comp_mod.write_comparison("t", self.output_path)
        self.assertTrue(self.output_path.exists())
        leftovers = [f for f in os.listdir(self.output_path.parent) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_comparator_empty_is_graceful(self):
        doc = comp_mod.build_comparison("t")
        self.assertEqual(doc["strategies"], [])
        self.assertIsNone(doc["best_strategy"])


class EndToEndTest(_IsolatedIO):
    def test_run_then_compare(self):
        # Two runner steps, then compare — full pipeline on isolated I/O.
        runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        runner_mod.run_all_strategies(self.snapshot_path, self.history_path)
        doc = comp_mod.build_comparison("2026-06-09T00:00:00+00:00")
        self.assertEqual(len(doc["strategies"]), 6)
        self.assertIsNotNone(doc["best_strategy"])
        self.assertEqual(doc["days_running"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
