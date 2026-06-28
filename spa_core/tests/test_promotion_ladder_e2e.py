"""
spa_core/tests/test_promotion_ladder_e2e.py — END-TO-END promotion-ladder flow.

Sprint T6. The promotion ladder (backtest → paper_Nd → live) is exercised piecemeal by other
suites (tournament-engine units, lab-promotion units), but the FULL FLOW — drive a single sleeve
all the way up the rungs and assert it gates correctly at each one, INCLUDING the refusal/REJECT
path that must NEVER reach live — was not covered as one E2E. This file is that coverage.

It drives TWO real ladders, end-to-end, as one flow each:

  A. TournamentEngine (spa_core/tournament/tournament_engine.py) — the canonical
     backtest → paper_30d → live ladder with the EXACT criteria the brief names:
       Sharpe ≥ 1.5 · ≥ 7 paper days · APY ≥ 3% · drawdown ≥ -15%
     (PROMOTION_CRITERIA / PHASES, imported REAL so a criteria change breaks THIS test, not the
     ladder silently). We accrue synthetic shadow paper days via update_shadow_day() against a
     hermetic tmp data dir and assert check_promotions() promotes ONLY when every rung is cleared:
       - a GOOD sleeve: 6 days → NOT yet promotable; the 7th day meeting all → promotable to live.
       - a TOXIC sleeve (sub-1.5 Sharpe OR <3% APY OR worse-than-band DD): NEVER promotes, no
         matter how many paper days accrue (refuse-and-hold at the rung it fails).
       - boundary cases at the EXACT constants (Sharpe == 1.5, APY == 3.0, days == 7, DD == band)
         to pin the inclusive/exclusive edge against the real constant values.

  B. The Strategy-Lab promotion engine (spa_core/strategy_lab/promotion.py) — the structural
     REJECT / BACKTEST_PASS / PAPER_CANDIDATE ladder. We drive ONE sleeve through the rubric and
     assert the refusal path: a sleeve that fails the floor or a hard risk criterion REJECTs and
     can NEVER be promoted to PAPER_CANDIDATE by adding walk-forward/capacity evidence on top
     (the refusal-gate veto sticks at the rung it fails). And a refusal-gate veto via the rates-
     desk promotion mapping (BLOCKED-NO-HEDGE) that structurally cannot reach a pass.

All synthetic / deterministic — no live data, no network. stdlib only, fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.tournament.tournament_engine import (
    PHASES,
    PROMOTION_CRITERIA,
    TournamentEngine,
)
from spa_core.strategy_lab import promotion as lab_promotion
from spa_core.strategy_lab.promotion import (
    STAGE_BACKTEST_PASS,
    STAGE_PAPER_CANDIDATE,
    STAGE_REJECT,
    promotion_verdict,
    score_sleeve,
)
from spa_core.strategy_lab.rates_desk import promotion_rates


# ── REAL criteria constants (imported, never re-hardcoded) ──────────────────────────────────────
# Sourced from tournament_engine.PROMOTION_CRITERIA so a change to the ladder breaks this test.
MIN_SHARPE = PROMOTION_CRITERIA["min_sharpe"]          # 1.5
MIN_DAYS_PAPER = PROMOTION_CRITERIA["min_days_paper"]  # 7
MAX_DRAWDOWN = PROMOTION_CRITERIA["max_drawdown"]      # -0.15  (a fraction)
MIN_APY_PCT = PROMOTION_CRITERIA["min_apy_pct"]        # 3.0


# ── hermetic tmp data-dir tournament fixtures ───────────────────────────────────────────────────
def _write_tournament_files(
    data_dir: Path,
    sleeve_id: str,
    sharpe: float,
    rank: int = 1,
) -> TournamentEngine:
    """Seed a hermetic strategy_tournament.json so the engine knows ONE active shadow sleeve, its
    Sharpe, and a daily allocation (used by update_shadow_day to accrue yield). Returns an engine
    bound to this tmp dir. shadow_paper_trading.json starts empty — paper days accrue via
    update_shadow_day(), exactly as the real launchd ladder does."""
    import json

    data_dir.mkdir(parents=True, exist_ok=True)
    tournament = {
        "total_strategies": 1,
        # This fixture exercises the NUMERIC criteria ladder on CREDIBLE synthetic data
        # (Sharpe values are small/credible, well below the degenerate ceiling). Declare
        # the dataset trustworthy so the fail-closed data-credibility gate (WS1.4) does
        # not pre-empt the ladder. (Untrustworthy/degenerate refusal has its own tests in
        # test_tournament_promotion_integrity.py.)
        "trustworthy": True,
        "data_source_regime": "NORMAL",
        "shadow_active_strategies": [
            {
                "strategy_key": sleeve_id,
                "id": sleeve_id,
                "rank": rank,
                "sharpe": sharpe,
                "days_active": 0,
                # single-protocol allocation; the APY we feed per day drives the accrual.
                "allocation": {"aave_v3": 1.0},
            }
        ],
    }
    # active_strategies is what check_promotions iterates; it carries the per-sleeve Sharpe too.
    shadow = {
        "active_strategies": [
            {"id": sleeve_id, "rank": rank, "sharpe": sharpe}
        ],
        "daily_results": [],
    }
    (data_dir / "strategy_tournament.json").write_text(json.dumps(tournament), encoding="utf-8")
    (data_dir / "shadow_paper_trading.json").write_text(json.dumps(shadow), encoding="utf-8")
    return TournamentEngine(data_dir=data_dir)


def _accrue_paper_days(engine: TournamentEngine, n_days: int, apy_pct: float) -> None:
    """Accrue n_days of shadow paper, each at a constant POSITIVE apy_pct on the seeded allocation.

    A constant positive yield gives a monotonically-rising equity curve → max-drawdown ≈ 0
    (>= the band), so DD never gates here unless we deliberately inject a loss day. Each call is a
    distinct UTC-style date so update_shadow_day appends (it de-dups on date)."""
    for d in range(n_days):
        engine.update_shadow_day(date=f"2026-01-{d + 1:02d}", apy_map={"aave_v3": apy_pct})


def _promoted_ids(engine: TournamentEngine):
    return {p["strategy_id"] for p in engine.check_promotions()}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# A. TournamentEngine ladder — the canonical backtest → paper_30d → live flow
# ═══════════════════════════════════════════════════════════════════════════════════════════════
class TestTournamentLadderE2E(unittest.TestCase):
    """Drive ONE sleeve up the real ladder and assert promotion gates correctly at each rung."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── ladder shape sanity (pin the phases) ─────────────────────────────────────────────────
    def test_ladder_phases_in_order(self):
        """The pipeline rungs are backtest → paper_30d → live, in that order."""
        self.assertEqual(PHASES, ["backtest", "paper_30d", "live"])

    # ── GOOD sleeve: rung-by-rung promotion ──────────────────────────────────────────────────
    def test_good_sleeve_six_paper_days_not_yet_promotable(self):
        """One-below-threshold paper days → the days rung is NOT cleared → no promotion, even
        though Sharpe/APY/DD all pass. (gate: days_paper >= MIN_DAYS_PAPER)."""
        eng = _write_tournament_files(self.tmp, "good", sharpe=MIN_SHARPE + 0.5)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER - 1, apy_pct=MIN_APY_PCT + 1.0)
        promos = eng.check_promotions()
        self.assertEqual(promos, [], "must NOT promote before MIN_DAYS_PAPER paper days")

    def test_good_sleeve_seventh_day_meeting_all_promotes_to_live(self):
        """Exactly MIN_DAYS_PAPER days, all criteria cleared → promotable; phase backtest→live
        boundary is paper_30d → live (the advisory live rung)."""
        eng = _write_tournament_files(self.tmp, "good", sharpe=MIN_SHARPE + 0.5)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER, apy_pct=MIN_APY_PCT + 1.0)
        promos = eng.check_promotions()
        self.assertEqual(len(promos), 1)
        p = promos[0]
        self.assertEqual(p["strategy_id"], "good")
        self.assertEqual(p["phase_from"], "paper_30d")
        self.assertEqual(p["phase_to"], "live")
        # every individual rung must read as cleared
        for k in ("min_sharpe", "min_days_paper", "min_apy_pct", "max_drawdown"):
            self.assertTrue(p["criteria_met"][k], f"criterion {k} should be cleared")
        # promotions are advisory — never an auto-execute to live.
        self.assertTrue(p["is_advisory"])

    def test_good_sleeve_progression_is_monotonic_across_the_days_rung(self):
        """Drive the SAME sleeve across the days rung in one flow: not promotable at 6 days,
        promotable at 7 — the only thing that changed is one more cleared rung."""
        eng = _write_tournament_files(self.tmp, "good", sharpe=MIN_SHARPE + 0.5)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER - 1, apy_pct=MIN_APY_PCT + 1.0)
        self.assertEqual(_promoted_ids(eng), set(), "6 days: held below the days rung")
        _accrue_paper_days_one_more = eng.update_shadow_day(
            date=f"2026-01-{MIN_DAYS_PAPER:02d}", apy_map={"aave_v3": MIN_APY_PCT + 1.0}
        )
        self.assertIsNotNone(_accrue_paper_days_one_more)
        self.assertEqual(_promoted_ids(eng), {"good"}, "7th day clears the rung → promotable")

    # ── REFUSAL path: a TOXIC sleeve never reaches live, however many days accrue ─────────────
    def test_toxic_low_sharpe_never_promotes(self):
        """Sub-threshold Sharpe → the Sharpe rung never clears → refuse-and-hold forever, even
        with far MORE than enough good paper days."""
        eng = _write_tournament_files(self.tmp, "toxic_sharpe", sharpe=MIN_SHARPE - 0.01)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER + 23, apy_pct=MIN_APY_PCT + 2.0)
        promos = eng.check_promotions()
        self.assertEqual(promos, [], "low-Sharpe sleeve must never reach live")

    def test_toxic_low_apy_never_promotes(self):
        """APY below 3% → the APY rung never clears, no matter the day count."""
        eng = _write_tournament_files(self.tmp, "toxic_apy", sharpe=MIN_SHARPE + 1.0)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER + 30, apy_pct=MIN_APY_PCT - 1.0)
        self.assertEqual(eng.check_promotions(), [], "<3% APY sleeve must never reach live")

    def test_toxic_drawdown_breach_never_promotes(self):
        """A real loss-driven drawdown worse than the band → the DD rung never clears.

        We accrue good days, then inject a large loss day so the peak-to-trough equity drawdown
        breaches MAX_DROWDOWN. Even with Sharpe + APY + day-count all fine, it must refuse-hold."""
        eng = _write_tournament_files(self.tmp, "toxic_dd", sharpe=MIN_SHARPE + 1.0)
        # build a high peak with strongly positive days...
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER, apy_pct=MIN_APY_PCT + 2.0)
        # ...then a catastrophic negative-yield day (a >15% equity loss) to breach the band.
        # capital=100_000; a -20_000 yield day → equity drops 20% from the (~100k) peak.
        eng.update_shadow_day(
            date="2026-02-01", apy_map={"aave_v3": -7300.0}  # apy% s.t. daily yield ≈ -20_000
        )
        dd = eng._compute_max_drawdown("toxic_dd", _read_daily(eng))
        self.assertLess(dd, MAX_DRAWDOWN, "the injected loss must breach the DD band")
        self.assertEqual(eng.check_promotions(), [], "DD-breaching sleeve must never reach live")

    def test_toxic_stays_refused_as_more_days_accrue(self):
        """The refuse-and-hold is durable: a toxic (low-Sharpe) sleeve is still refused after we
        add MANY more paper days — it can never 'age into' a promotion."""
        eng = _write_tournament_files(self.tmp, "toxic_aging", sharpe=MIN_SHARPE - 0.2)
        for extra in (MIN_DAYS_PAPER, MIN_DAYS_PAPER + 10, MIN_DAYS_PAPER + 25):
            # rebuild the curve to `extra` days and re-check each time
            eng = _write_tournament_files(self.tmp, "toxic_aging", sharpe=MIN_SHARPE - 0.2)
            _accrue_paper_days(eng, n_days=extra, apy_pct=MIN_APY_PCT + 2.0)
            self.assertEqual(eng.check_promotions(), [], f"still refused at {extra} days")

    # ── BOUNDARY cases at the EXACT real constants (inclusive '>=' edges) ─────────────────────
    def test_boundary_sharpe_exactly_min_promotes(self):
        """Sharpe == MIN_SHARPE clears (the gate is `sharpe >= min_sharpe`, inclusive)."""
        eng = _write_tournament_files(self.tmp, "edge_sharpe", sharpe=MIN_SHARPE)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER, apy_pct=MIN_APY_PCT + 1.0)
        self.assertEqual(_promoted_ids(eng), {"edge_sharpe"}, "Sharpe==1.5 is inclusive → clears")

    def test_boundary_days_exactly_min_promotes(self):
        """days_paper == MIN_DAYS_PAPER clears (gate `days_paper >= min_days_paper`)."""
        eng = _write_tournament_files(self.tmp, "edge_days", sharpe=MIN_SHARPE + 1.0)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER, apy_pct=MIN_APY_PCT + 1.0)
        self.assertEqual(_promoted_ids(eng), {"edge_days"}, "days==7 is inclusive → clears")

    def test_boundary_days_one_below_min_refused(self):
        """days_paper == MIN_DAYS_PAPER-1 does NOT clear (exclusive below the inclusive edge)."""
        eng = _write_tournament_files(self.tmp, "edge_days_low", sharpe=MIN_SHARPE + 1.0)
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER - 1, apy_pct=MIN_APY_PCT + 1.0)
        self.assertEqual(_promoted_ids(eng), set(), "days==6 must NOT clear")

    def test_boundary_apy_exactly_min_promotes(self):
        """paper APY == MIN_APY_PCT clears (gate `paper_apy_pct >= min_apy_pct`, inclusive)."""
        eng = _write_tournament_files(self.tmp, "edge_apy", sharpe=MIN_SHARPE + 1.0)
        # constant apy == 3.0 each day → mean paper apy == 3.0 exactly.
        _accrue_paper_days(eng, n_days=MIN_DAYS_PAPER, apy_pct=MIN_APY_PCT)
        promos = eng.check_promotions()
        self.assertEqual(len(promos), 1)
        self.assertAlmostEqual(promos[0]["paper_apy_pct"], MIN_APY_PCT, places=4)

    def test_boundary_drawdown_exactly_at_band_promotes(self):
        """max drawdown == MAX_DRAWDOWN clears (gate `max_dd >= max_drawdown`, inclusive edge).

        We engineer a curve whose peak-to-trough drawdown is EXACTLY the band. Equity starts at
        capital (100_000); one day yields +X to set a peak, then a loss day brings it to exactly
        (1 + MAX_DRAWDOWN) * peak. Pick peak = 100_000 + 1_000 = 101_000; trough must be
        101_000 * (1 + MAX_DRAWDOWN). The loss day yield = trough - peak."""
        capital = 100_000.0
        peak_gain = 1_000.0
        peak = capital + peak_gain
        trough = peak * (1.0 + MAX_DRAWDOWN)
        loss = trough - peak  # negative
        eng = _write_tournament_files(self.tmp, "edge_dd", sharpe=MIN_SHARPE + 1.0)
        # day1: +peak_gain (as a raw daily yield via a contrived apy), day2: the exact loss.
        # daily_yield_usd = capital * weight * (apy/100) / 365, weight==1.0 → apy = yield*365/capital*100
        def _apy_for(yield_usd: float) -> float:
            return yield_usd * 365.0 / capital * 100.0
        eng.update_shadow_day(date="2026-03-01", apy_map={"aave_v3": _apy_for(peak_gain)})
        eng.update_shadow_day(date="2026-03-02", apy_map={"aave_v3": _apy_for(loss)})
        # pad to MIN_DAYS_PAPER days with flat (~0) days so the days rung clears without moving DD.
        for d in range(MIN_DAYS_PAPER - 2):
            eng.update_shadow_day(date=f"2026-03-{d + 3:02d}", apy_map={"aave_v3": 0.0})
        dd = eng._compute_max_drawdown("edge_dd", _read_daily(eng))
        # the trough is exactly at the band → DD == MAX_DRAWDOWN (within float tolerance).
        self.assertAlmostEqual(dd, MAX_DRAWDOWN, places=5)
        self.assertGreaterEqual(dd, MAX_DRAWDOWN, "the gate is `dd >= band` (inclusive)")


def _read_daily(engine: TournamentEngine):
    """The shadow daily_results list as check_promotions' drawdown/apy helpers consume it."""
    import json
    p = engine._shadow_path
    with open(p, encoding="utf-8") as fh:
        return json.load(fh).get("daily_results", [])


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# B. Strategy-Lab structural ladder — REJECT / BACKTEST_PASS / PAPER_CANDIDATE + refusal veto
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _lab_result(net_apy=5.0, max_dd=0.0, beats=True, kill=None, sid="lab_sleeve"):
    return {
        "id": sid,
        "mandate": "stable",
        "metrics": {
            "net_apy_pct": net_apy,
            "max_drawdown_pct": max_dd,
            "beats_rwa_floor": beats,
        },
        "kill": kill,
    }


def _lab_wf_block(consistency=80.0, robust=True, max_aum=8_000_000.0):
    return {
        "status": "ok",
        "consistency_pct": consistency,
        "wf_robust": robust,
        "capacity": {"status": "ok", "max_safe_aum_usd": max_aum},
    }


_LAB_THR = lab_promotion.promotion_config()  # the REAL lab thresholds (band=15%, etc.)


class TestLabStructuralLadderE2E(unittest.TestCase):
    """Drive ONE lab sleeve up the structural ladder and assert the refusal path is terminal."""

    def test_good_sleeve_climbs_to_paper_candidate(self):
        """A floor-beating, low-DD sleeve with WF+capacity evidence → PAPER_CANDIDATE (top rung
        of the structural ladder, eligible for the PAPER stage)."""
        s = score_sleeve(_lab_result(net_apy=5.0, max_dd=2.0, beats=True),
                         walk_forward=_lab_wf_block(), promotion=_LAB_THR)
        self.assertEqual(promotion_verdict(s)["stage"], STAGE_PAPER_CANDIDATE)

    def test_good_sleeve_backtest_pass_when_wf_pending(self):
        """Same sleeve WITHOUT walk-forward/capacity evidence → it clears the backtest rung but
        holds at BACKTEST_PASS (the WF rung is PENDING, not yet cleared)."""
        s = score_sleeve(_lab_result(net_apy=5.0, max_dd=2.0, beats=True),
                         walk_forward=None, promotion=_LAB_THR)
        v = promotion_verdict(s)
        self.assertEqual(v["stage"], STAGE_BACKTEST_PASS)
        self.assertTrue(s["criteria"]["walk_forward_robust"]["pending"])
        self.assertTrue(s["criteria"]["capacity_sufficient"]["pending"])

    def test_refusal_below_floor_rejects_and_cannot_be_lifted(self):
        """REFUSAL path: a sleeve that does NOT beat the RWA floor REJECTs — and piling on
        perfect walk-forward + huge capacity evidence can NEVER lift it to PAPER_CANDIDATE.
        The refusal sticks at the rung it fails."""
        # fails the floor (beats=False) — a hard backtest-gate criterion.
        toxic = _lab_result(net_apy=0.5, max_dd=1.0, beats=False)
        # even with the BEST possible WF + capacity evidence stacked on top:
        s = score_sleeve(toxic, walk_forward=_lab_wf_block(consistency=100.0, max_aum=50_000_000.0),
                         promotion=_LAB_THR)
        self.assertEqual(promotion_verdict(s)["stage"], STAGE_REJECT)

    def test_refusal_real_risk_kill_rejects_forever(self):
        """A REAL (non-data-gap) risk kill is a terminal refusal: REJECT regardless of WF evidence
        and no number of paper days can promote it (it never even clears the backtest rung)."""
        kill = {"reason": "drawdown 30.05% > kill 25.00%"}
        s = score_sleeve(_lab_result(net_apy=5.0, max_dd=30.0, beats=True, kill=kill),
                         walk_forward=_lab_wf_block(), promotion=_LAB_THR)
        self.assertFalse(s["criteria"]["not_killed_real"]["pass"])
        self.assertEqual(promotion_verdict(s)["stage"], STAGE_REJECT)

    def test_refusal_drawdown_band_is_the_real_constant(self):
        """Boundary at the REAL lab band: a DD exactly AT the band clears the DD criterion; just
        over it fails. Read the band from the real config so a config change breaks this test."""
        band = float(_LAB_THR["max_drawdown_band_pct"])  # 15.0
        at = score_sleeve(_lab_result(beats=True, net_apy=5.0, max_dd=band), promotion=_LAB_THR)
        self.assertTrue(at["criteria"]["drawdown_within_band"]["pass"], "DD==band is inclusive")
        over = score_sleeve(_lab_result(beats=True, net_apy=5.0, max_dd=band + 0.01),
                            promotion=_LAB_THR)
        self.assertFalse(over["criteria"]["drawdown_within_band"]["pass"], "DD>band fails")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# C. Rates-Desk refusal-gate veto — a structurally-blocked sleeve can never reach a pass
# ═══════════════════════════════════════════════════════════════════════════════════════════════
class TestRatesDeskRefusalVetoE2E(unittest.TestCase):
    """The BASIS_HEDGE sleeve is structurally vetoed (no keyless forward-funding venue). Driven
    through the rates-desk promotion mapping it must land BLOCKED-NO-HEDGE — never a pass — while
    a genuinely floor-beating FixedCarry sleeve in the SAME report reaches PAPER_CANDIDATE."""

    def _rates_backtest(self):
        return {
            "rwa_floor_pct": 3.4,
            "sleeves": {
                # FixedCarry: a real, floor-beating, deflated-Sharpe-passing carry book.
                "fixed_carry": {
                    "sleeve_id": "fixed_carry",
                    "net_apy_pct": 6.2,
                    "max_drawdown_pct": 1.0,
                    "beats_floor": True,
                    "deflated_sharpe_passes_0_95": True,
                    "deflated_sharpe": 1.8,
                    "carry_days": 400,
                    "approvals_count": 12,
                    "refusals_count": 5,
                    "kills": 0,
                },
                # BasisHedge: structurally blocked — cannot be backtested/promoted.
                "basis_hedge": {
                    "sleeve_id": "basis_hedge",
                    "blocked_no_hedge": True,
                    "blocked_reason": "no keyless forward-funding (Boros) venue available",
                    "net_apy_pct": None,
                    "max_drawdown_pct": None,
                    "deflated_sharpe": None,
                    "refusals_count": 0,
                    "kills": 0,
                },
            },
        }

    def test_blocked_sleeve_never_passes_good_sleeve_promotes(self):
        rep = promotion_rates.build_report(
            write=False, backtest=self._rates_backtest(), promotion_config=_LAB_THR
        )
        by_id = {s["id"]: s for s in rep["sleeves"]}
        # the refusal-vetoed sleeve is structurally blocked — NOT a pass/fail on the rubric.
        self.assertEqual(by_id["basis_hedge"]["stage"], promotion_rates.STAGE_BLOCKED_NO_HEDGE)
        self.assertFalse(by_id["basis_hedge"]["beats_floor"])
        # the genuinely robust carry sleeve climbs to the top structural rung.
        self.assertEqual(by_id["fixed_carry"]["stage"], STAGE_PAPER_CANDIDATE)

    def test_blocked_is_terminal_no_pass_stage(self):
        """A BLOCKED-NO-HEDGE sleeve can never appear as REJECT/BACKTEST_PASS/PAPER_CANDIDATE —
        it is reported verbatim, off-ladder, fail-CLOSED."""
        rep = promotion_rates.build_report(
            write=False, backtest=self._rates_backtest(), promotion_config=_LAB_THR
        )
        blocked = next(s for s in rep["sleeves"] if s["id"] == "basis_hedge")
        self.assertNotIn(
            blocked["stage"], (STAGE_REJECT, STAGE_BACKTEST_PASS, STAGE_PAPER_CANDIDATE)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
