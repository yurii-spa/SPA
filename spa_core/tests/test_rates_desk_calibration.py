"""
spa_core/tests/test_rates_desk_calibration.py — PART 1 (calibration sweep) + PART 2 (LeveredCarry
stress scrutiny) tests for the rates desk.

Proves:
  CALIBRATION (calibrate.py):
    - the calibrated max_total_haircut VETOES the toxic rsETH/ezETH-2024/2026 books but PASSES the
      healthy sUSDe carry (the §9 separation the desk's edge depends on),
    - the sweep is deterministic + the chosen point is admissible (100% toxic coverage, all stress
      events refused) and the config CALIBRATED_* values flow into RatePolicyParams defaults,
    - the robust objective picks the CENTER of the safe band (margin to both cliffs), not its edge.

  LEVERED STRESS (levered_stress.py):
    - LeveredCarry UNWINDS under the Oct-2025 replay (the kill fires, DD bounded within the band),
    - the gate REFUSES ENTRY into the toxic LRT loop (Apr-2026 KelpDAO) — no loop to blow up,
    - the harness is HONEST (not rigged): defeat the kills → the verdict DOWNGRADES (DD blows the band),
    - gated DD « naive (ungated) DD — the gate's value is real.

PURE / Decimal / stdlib / deterministic. LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import dataclasses
from decimal import Decimal as D

import pytest

from spa_core.strategy_lab.rates_desk import calibrate as CAL
from spa_core.strategy_lab.rates_desk import levered_stress as LS
from spa_core.strategy_lab.rates_desk import config
from spa_core.strategy_lab.rates_desk.contracts import (
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry


# ── shared fixtures: a toxic rsETH book vs a healthy sUSDe book ─────────────────────────────────────
def _toxic_rseth_risk(as_of: str = "2026-04-01") -> UnderlyingRisk:
    return UnderlyingRisk(
        underlying="rseth", as_of=as_of, nav_redemption_value=D("1"), market_price=D("0.975"),
        peg_distance=D("0.025"), peg_vol_30d=D("0.03"), redemption_sla_seconds=86400 * 7,
        reserve_fund_ratio=D("0"), funding_neg_frac_90d=D("0.50"), oracle_kind="redstone",
        oracle_staleness_seconds=900, nested_protocol_count=5, top_borrower_share=D("0.55"))


def _healthy_susde_risk(as_of: str = "2025-01-01") -> UnderlyingRisk:
    return UnderlyingRisk(
        underlying="susde", as_of=as_of, nav_redemption_value=D("1"), market_price=D("1"),
        peg_distance=D("0"), peg_vol_30d=D("0"), redemption_sla_seconds=86400,
        reserve_fund_ratio=D("0.05"), funding_neg_frac_90d=D("0.10"), oracle_kind="chainlink",
        oracle_staleness_seconds=300, nested_protocol_count=1, top_borrower_share=D("0.1"))


def _gate(risk, kind, quoted, as_of, hedge, params):
    eng = FairValueEngine(params)
    q = RateQuote(underlying=risk.underlying, kind=kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
                  market_id=f"PT-{risk.underlying}", tenor_seconds=86400 * 60, as_of=as_of,
                  quoted_rate=D(quoted), tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"),
                  hedge_available=hedge)
    opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=D("100000"))
    ty = D("0.10") if hedge else None
    res, _ = evaluate_entry(opp, risk, D("1"), q.exit_liquidity_usd, params, KillState(),
                            engine=eng, trailing_yield=ty, boros_forward=ty)
    return res


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# PART 1 — calibration
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_calibrated_threshold_vetoes_toxic_rseth_but_passes_healthy_susde():
    """The headline §9 guarantee: at the CALIBRATED threshold the toxic rsETH-2026 book is REFUSED
    (its tail haircut breaches the veto) while the healthy sUSDe carry FIRES."""
    p = RatePolicyParams()  # reads the calibrated config defaults
    tox = _gate(_toxic_rseth_risk(), UnderlyingKind.LRT, "0.45", "2026-04-01", False, p)
    healthy = _gate(_healthy_susde_risk(), UnderlyingKind.STABLE_SYNTH, "0.12", "2025-01-01", True, p)
    assert tox.approved is False, "toxic rsETH must be vetoed"
    assert healthy.approved is True, "healthy sUSDe carry must still fire (not over-vetoed)"


def test_calibrated_values_flow_from_config_into_params():
    """The calibrated values are PINNED in config.py (not hardcoded in the engine) and flow into the
    RatePolicyParams defaults."""
    p = RatePolicyParams()
    assert p.max_total_haircut == D(str(config.CALIBRATED_MAX_TOTAL_HAIRCUT))
    assert p.k_peg == D(str(config.CALIBRATED_K_PEG))
    assert p.k_protocol == D(str(config.CALIBRATED_K_PROTOCOL))


def test_toxic_haircut_strictly_above_threshold_above_healthy():
    """The separation band must be real: toxic total_haircut > max_total_haircut > healthy haircut."""
    p = RatePolicyParams()
    eng = FairValueEngine(p)
    tox = eng.fair(risk=_toxic_rseth_risk(), kind=UnderlyingKind.LRT, tenor_seconds=86400 * 60,
                   hedge_available=False, position_size_usd=D("500000"),
                   exit_liquidity_usd=D("2e6"), as_of="2026-04-01")
    healthy = eng.fair(risk=_healthy_susde_risk(), kind=UnderlyingKind.STABLE_SYNTH,
                       tenor_seconds=86400 * 60, hedge_available=True, position_size_usd=D("500000"),
                       exit_liquidity_usd=D("2e6"), as_of="2025-01-01",
                       trailing_yield=D("0.10"), boros_forward=D("0.12"))
    assert healthy.total_haircut < p.max_total_haircut < tox.total_haircut


def test_sweep_is_deterministic_and_chosen_is_admissible():
    """The sweep is a pure deterministic grid (same data → same chosen point), and the chosen point is
    admissible: 100% toxic coverage + every stress event refused."""
    deep = CAL.pph.load()
    funding = CAL.retro.load_funding()
    r1 = CAL.sweep(deep=deep, funding=funding)
    r2 = CAL.sweep(deep=deep, funding=funding)
    assert r1["chosen"] == r2["chosen"]
    ch = r1["chosen"]
    assert ch is not None
    assert ch["toxic_coverage"] == 1.0
    assert ch["toxic_stress_all_refused"] is True
    assert ch["healthy_fire_rate"] == 1.0
    assert ch["survivor_beats_floor"] is True


def test_sweep_chosen_is_robust_center_not_loose_edge():
    """The robust objective picks a point with POSITIVE margin to BOTH cliffs (it sits inside the band,
    not one grid-step below the toxic leak)."""
    deep = CAL.pph.load()
    funding = CAL.retro.load_funding()
    r = CAL.sweep(deep=deep, funding=funding)
    ch = r["chosen"]
    assert ch["robust_margin"] > 0.0
    assert ch["toxic_leak_margin"] > 0.0
    assert ch["healthy_strangle_margin"] > 0.0


def test_sweep_confirms_defaults_are_optimal():
    """Honest 'defaults confirmed' outcome: the chosen point equals the current config defaults (the
    sweep does not churn a risk cutoff for a cosmetic APY tick)."""
    r = CAL.sweep()
    ch = r["chosen"]
    assert ch["params"]["max_total_haircut"] == str(float(config.CALIBRATED_MAX_TOTAL_HAIRCUT))
    assert ch["params"]["k_peg"] == str(float(config.CALIBRATED_K_PEG))
    assert ch["params"]["k_protocol"] == str(float(config.CALIBRATED_K_PROTOCOL))


def test_overtight_threshold_strangles_healthy_carry():
    """Demonstrate the trade-off: an over-TIGHT max_total_haircut (below the healthy haircut) would
    VETO the healthy sUSDe carry too — the over-veto failure the calibration avoids."""
    # an over-tight threshold BELOW even the benign healthy book's structural haircut (~0.018:
    # oracle+liquidity+protocol) strangles the carry. (In the deep survivor series the healthy haircut
    # rises toward ~0.09 in hostile-funding regimes — the calibration's lower cliff is at ~0.09 there;
    # this fixture isolates the structural floor.)
    p = dataclasses.replace(RatePolicyParams(), max_total_haircut=D("0.015"))
    healthy = _gate(_healthy_susde_risk(), UnderlyingKind.STABLE_SYNTH, "0.12", "2025-01-01", True, p)
    assert healthy.approved is False  # strangled — proves the lower cliff is real


def test_overloose_threshold_leaks_toxic():
    """An over-LOOSE max_total_haircut (above the toxic haircut) lets a toxic book clear the veto on
    economics — the upper cliff. (The deep rsETH surface haircut ≈ 0.18-0.20; 0.30 leaks it.)"""
    p = dataclasses.replace(RatePolicyParams(), max_total_haircut=D("0.30"))
    tox = _gate(_toxic_rseth_risk(), UnderlyingKind.LRT, "0.45", "2026-04-01", False, p)
    # at a 30% threshold the tail veto no longer fires; SOME other structural veto (depeg) may still
    # catch rsETH (peg_distance 0.025 > max_peg_distance). The point: it is NOT a TAIL_VETO anymore.
    from spa_core.strategy_lab.rates_desk.contracts import KillReason
    assert tox.reason != KillReason.TAIL_VETO


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# PART 2 — LeveredCarry stress scrutiny
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_levered_unwinds_under_oct2025_replay():
    """THE test: the Oct-2025 USDe leverage unwind. The gated levered loop must UNWIND (a kill fires)
    and its realized DD must stay within the drawdown band."""
    r = LS.run(write=False)
    oct_ev = next(e for e in r["events"] if "USDe leverage unwind" in e["label"])
    assert oct_ev["entry_vetoed"] is False, "the stable-synth loop forms"
    assert oct_ev["kill_fired"] is True, "the kill MUST fire on the unwind"
    assert D(oct_ev["gated_max_dd_pct"]) <= D(r["max_dd_band_pct"]), "DD must stay within the band"
    assert oct_ev["survives"] is True


def test_levered_gated_dd_better_than_naive():
    """The gate's value is real: the gated levered DD is strictly LESS than the naive (ungated) DD on
    every loop event (the gate cut the levered loss)."""
    r = LS.run(write=False)
    for e in r["events"]:
        if e["entry_vetoed"] or e["naive_max_dd_pct"] is None:
            continue
        assert D(e["gated_max_dd_pct"]) < D(e["naive_max_dd_pct"]), e["label"]


def test_levered_refuses_entry_into_toxic_lrt_loop():
    """Apr-2026 KelpDAO rsETH: the gate must REFUSE ENTRY — the desk never levers into a toxic LRT, so
    there is no loop to blow up (DD 0%, entry vetoed)."""
    r = LS.run(write=False)
    lrt_ev = next(e for e in r["events"] if e["kind"] == "lrt")
    assert lrt_ev["entry_vetoed"] is True
    assert D(lrt_ev["gated_max_dd_pct"]) == D("0")


def test_levered_default_verdict_survives_paper_candidate():
    """At the default 3× gated leverage the desk SURVIVES the stress events → keeps PAPER_CANDIDATE."""
    r = LS.run(write=False)
    assert r["survives_stress"] is True
    assert r["recommended_stage"] == "PAPER_CANDIDATE"


def test_levered_harness_is_honest_downgrades_when_kills_defeated():
    """The harness is NOT rigged to always survive: defeat the kill rules (carry-compression off,
    funding hysteresis effectively infinite) and the verdict must DOWNGRADE (DD blows the band)."""
    base = RatePolicyParams()
    p = dataclasses.replace(base, carry_compression_frac=D("0.0"), funding_flip_streak_kill=999)
    r = LS.run(params=p, max_leverage=D("5"), write=False)
    assert r["survives_stress"] is False
    assert r["recommended_stage"] == "BACKTEST_PASS"
    # at least one loop blew past the band
    loop_dds = [D(e["gated_max_dd_pct"]) for e in r["events"] if not e["entry_vetoed"]]
    assert any(dd > D(r["max_dd_band_pct"]) for dd in loop_dds)


def test_levered_dd_monotonic_in_leverage():
    """Sanity that the honest model is not the leverage-blind one: realized DD on the Oct-2025 loop
    RISES with leverage (a blind model would show it flat/0)."""
    dd_3x = D(next(e for e in LS.run(max_leverage=D("3"), write=False)["events"]
                   if "USDe leverage unwind" in e["label"])["gated_max_dd_pct"])
    dd_5x = D(next(e for e in LS.run(max_leverage=D("5"), write=False)["events"]
                   if "USDe leverage unwind" in e["label"])["gated_max_dd_pct"])
    assert dd_5x > dd_3x > D("0")


def test_levered_run_is_deterministic():
    r1 = LS.run(write=False)
    r2 = LS.run(write=False)
    # strip the timestamp before comparing
    r1 = {k: v for k, v in r1.items() if k != "generated_at"}
    r2 = {k: v for k, v in r2.items() if k != "generated_at"}
    assert r1 == r2
