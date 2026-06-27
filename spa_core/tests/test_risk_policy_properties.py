"""
spa_core/tests/test_risk_policy_properties.py — PROPERTY-BASED tests for the
RiskPolicy GATE (the un-overridable, fail-CLOSED, LLM-FORBIDDEN safety surface).

Sprint T2: assert the NON-NEGOTIABLES hold over a randomized input space —
`approved=False` is NEVER silently flipped to True by ANY field combination,
the kill-switch fires deterministically + monotonically at the config threshold,
and the eval path NEVER raises on non-finite / degenerate inputs (fail closed).

Convention (repo standard, NO `hypothesis`): a single seeded random.Random per
property loops ~200 cases, asserting an invariant that must hold for EVERY case.
A seeded PRNG keeps the suite bit-for-bit reproducible while exercising a broad,
property-style input space. Pure stdlib + pytest. Deterministic (seed 1337).

Invariants proven here (count × cases):
  G1  approved-NEVER-silently-flips: any field combo that SHOULD reject does    (≈8×200)
      (sub-floor TVL / out-of-band APY / over-cap concentration / over-T2 /
       insufficient cash / drawdown) → approved is ALWAYS False, never True.
  G2  sub-floor TVL (<$5M) can NEVER return approved=True.                       (200)
  G3  out-of-band APY (<1% or >30%) can NEVER return approved=True.             (200)
  G4  over-cap concentration can NEVER return approved=True.                    (200)
  G5  kill-switch fires DETERMINISTICALLY at the threshold READ FROM RiskConfig (200)
      AND is MONOTONE (worse drawdown ⇒ still kill, never un-kills).
  G6  the WHOLE gate NEVER RAISES on non-finite inputs (NaN/inf across amount/
      apy/tvl/drawdown/price) → fail-closed approved=False / kill.             (≈4×200)
  G7  check_stablecoin_depeg / check_axis_compliance: a depeg beyond threshold /
      an axis breach → NEVER approved=True.                                    (2×200)
  G8  determinism: same seeded input → same verdict (verdict is a pure fn).     (200)

REAL GATE HOLES found by this fuzzing + fixed (fail-closed, NO threshold change):
  • check_stablecoin_depeg(): a NaN price returned approved=True — |nan-1|<thr
    is False so it never `continue`d, then `nan>=2*thr` is False → fell through
    to WARN → silent bypass. Now fail-closed (non-finite price → violation).
  • check_new_position(): total_capital_usd==0 raised ZeroDivisionError out of
    the gate (concentration math divides by it) — an exception is itself a
    bypass. Now fail-closed (non-positive capital → approved=False reject).

LLM-forbidden surface.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import random

import pytest

from risk.policy import (
    RiskPolicy,
    RiskConfig,
    Position,
    PortfolioState,
)

N_CASES = 200
SEED = 1337

# Threshold constants are READ FROM RiskConfig (single source of truth). The
# pins below assert the policy still reads these exact values — config drift
# breaks the test rather than silently the policy.
_CFG = RiskConfig()
NON_FINITE = [float("nan"), float("inf"), float("-inf")]
_PROTOCOLS = [
    "aave-v3-usdc-ethereum", "compound-v3-usdc-ethereum", "morpho-blue-usdc-ethereum",
    "yearn-v3-usdc-ethereum", "euler-v2-usdc-ethereum", "maple-usdc-ethereum",
    "some-unregistered-protocol",
]
_TIERS = ["T1", "T2"]
_CHAINS = ["ethereum", "arbitrum", "base"]


def _rng(salt: int = 0) -> random.Random:
    return random.Random(SEED + salt)


@pytest.fixture
def policy() -> RiskPolicy:
    return RiskPolicy()


# ---------------------------------------------------------------------------
# Pin: the thresholds the properties below depend on are read FROM RiskConfig.
# If an owner changes a threshold, these break loudly (intentional tripwire) —
# the policy never drifts silently behind a passing test.
# ---------------------------------------------------------------------------
def test_threshold_pins_from_config():
    assert _CFG.min_tvl_usd == 5_000_000
    assert _CFG.min_apy_for_new_position == 1.0
    assert _CFG.max_apy_for_new_position == 30.0
    assert _CFG.max_concentration_t1 == 0.40
    assert _CFG.max_concentration_t2 == 0.20
    assert _CFG.max_total_t2_allocation == 0.50
    assert _CFG.min_cash_pct == 0.05
    assert _CFG.max_drawdown_stop == 0.05
    assert _CFG.version == "v1.0"


# ---------------------------------------------------------------------------
# G1. CORE INVARIANT: approved=False is NEVER silently flipped to True.
#     Fuzz amount/apy/tvl/protocol/tier over a wide space; whenever the input
#     deterministically VIOLATES at least one non-negotiable (computed here from
#     the SAME config constants), the gate MUST return approved=False. The gate
#     can never be MORE permissive than its own thresholds.
# ---------------------------------------------------------------------------
def test_approved_never_silently_flips(policy):
    rng = _rng(1)
    cfg = _CFG
    for _ in range(N_CASES):
        capital = rng.uniform(1_000.0, 1_000_000.0)
        # build a (possibly already-occupied) portfolio
        positions = []
        n = rng.randint(0, 3)
        for i in range(n):
            positions.append(Position(
                protocol_key=rng.choice(_PROTOCOLS),
                tier=rng.choice(_TIERS),
                asset="USDC",
                amount_usd=rng.uniform(0.0, capital * 0.3),
                apy_at_open=5.0, current_apy=5.0,
                unrealized_pnl_usd=rng.uniform(-capital * 0.1, capital * 0.1),
                chain=rng.choice(_CHAINS),
            ))
        state = PortfolioState(total_capital_usd=capital, positions=positions)

        protocol = rng.choice(_PROTOCOLS)
        tier = rng.choice(_TIERS)
        amount = rng.uniform(0.0, capital * 1.2)
        apy = rng.uniform(-5.0, 50.0)
        tvl = rng.uniform(0.0, 50_000_000.0)
        chain = rng.choice(_CHAINS)

        result = policy.check_new_position(
            state, protocol, tier, amount, apy, tvl, chain=chain,
            check_capacity=False,
        )

        # Independently recompute whether ANY non-negotiable is violated, using
        # the policy's own config constants. If so, approved MUST be False.
        max_conc = cfg.max_concentration_t1 if tier == "T1" else cfg.max_concentration_t2
        new_conc = (state.concentration_pct(protocol) * capital + amount) / capital
        remaining_cash_pct = (state.cash_usd - amount) / capital
        must_reject = (
            tvl < cfg.min_tvl_usd
            or apy > cfg.max_apy_for_new_position
            or apy < cfg.min_apy_for_new_position
            or amount > state.cash_usd
            or remaining_cash_pct < cfg.min_cash_pct
            or new_conc > max_conc
            or state.total_drawdown_pct >= cfg.max_drawdown_stop
        )
        if must_reject:
            assert result.approved is False, (
                f"GATE HOLE: approved silently flipped True despite a violation. "
                f"tier={tier} amount={amount} apy={apy} tvl={tvl} "
                f"new_conc={new_conc} cash%={remaining_cash_pct} "
                f"dd={state.total_drawdown_pct} -> {result.violations}"
            )
        # And approved is ALWAYS a strict bool (never truthy-non-bool leak).
        assert result.approved in (True, False)


# ---------------------------------------------------------------------------
# G2. A sub-floor TVL (<$5M) can NEVER return approved=True.
# ---------------------------------------------------------------------------
def test_subfloor_tvl_never_approved(policy):
    rng = _rng(2)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        state = PortfolioState(total_capital_usd=capital, positions=[])
        tvl = rng.uniform(0.0, _CFG.min_tvl_usd - 1.0)  # strictly sub-floor
        result = policy.check_new_position(
            state, rng.choice(_PROTOCOLS), rng.choice(_TIERS),
            amount_usd=rng.uniform(1.0, capital * 0.2),
            current_apy=rng.uniform(1.0, 30.0),  # otherwise-valid APY
            tvl_usd=tvl, check_capacity=False,
        )
        assert result.approved is False, f"sub-floor TVL ${tvl:,.0f} approved!"
        assert any("TVL" in v for v in result.violations)


# ---------------------------------------------------------------------------
# G3. An out-of-band APY (<1% or >30%) can NEVER return approved=True.
# ---------------------------------------------------------------------------
def test_out_of_band_apy_never_approved(policy):
    rng = _rng(3)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        state = PortfolioState(total_capital_usd=capital, positions=[])
        if rng.random() < 0.5:
            apy = rng.uniform(-10.0, _CFG.min_apy_for_new_position - 1e-6)  # too low
        else:
            apy = rng.uniform(_CFG.max_apy_for_new_position + 1e-6, 500.0)  # too high
        result = policy.check_new_position(
            state, rng.choice(_PROTOCOLS), rng.choice(_TIERS),
            amount_usd=rng.uniform(1.0, capital * 0.2),
            current_apy=apy,
            tvl_usd=rng.uniform(_CFG.min_tvl_usd, 50_000_000.0),  # valid TVL
            check_capacity=False,
        )
        assert result.approved is False, f"out-of-band APY {apy}% approved!"
        assert any("APY" in v for v in result.violations)


# ---------------------------------------------------------------------------
# G4. An over-cap concentration can NEVER return approved=True.
#     Seed an existing position in the SAME protocol at/above the tier cap, then
#     add more → post-trade concentration strictly exceeds the cap.
# ---------------------------------------------------------------------------
def test_over_cap_concentration_never_approved(policy):
    rng = _rng(4)
    for _ in range(N_CASES):
        capital = rng.uniform(50_000.0, 1_000_000.0)
        tier = rng.choice(_TIERS)
        protocol = rng.choice(_PROTOCOLS)
        cap = _CFG.max_concentration_t1 if tier == "T1" else _CFG.max_concentration_t2
        # existing concentration already AT the cap
        existing = cap * capital
        state = PortfolioState(
            total_capital_usd=capital,
            positions=[Position(
                protocol_key=protocol, tier=tier, asset="USDC",
                amount_usd=existing, apy_at_open=5.0, current_apy=5.0,
                chain="ethereum",
            )],
        )
        # add a strictly-positive amount that we can afford → conc > cap
        add = rng.uniform(capital * 0.02, capital * 0.05)
        result = policy.check_new_position(
            state, protocol, tier,
            amount_usd=add, current_apy=rng.uniform(1.0, 30.0),
            tvl_usd=rng.uniform(_CFG.min_tvl_usd, 50_000_000.0),
            check_capacity=False,
        )
        assert result.approved is False, (
            f"over-cap concentration approved! tier={tier} cap={cap} "
            f"existing={existing} add={add} -> {result.violations}")
        assert any("Concentration" in v or "T2 allocation" in v
                   for v in result.violations)


# ---------------------------------------------------------------------------
# G5. Kill-switch: DETERMINISTIC at the threshold READ FROM RiskConfig, MONOTONE
#     (worse drawdown ⇒ still kill, never un-kills). Drives drawdown via a
#     single negative-PnL position so total_drawdown_pct is controllable.
# ---------------------------------------------------------------------------
def _state_with_drawdown(capital: float, dd: float) -> PortfolioState:
    """A portfolio whose total_drawdown_pct == max(0, dd)."""
    pnl = -dd * capital  # negative pnl ⇒ drawdown
    return PortfolioState(
        total_capital_usd=capital,
        positions=[Position(
            protocol_key="aave-v3-usdc-ethereum", tier="T1", asset="USDC",
            amount_usd=capital * 0.2, apy_at_open=5.0, current_apy=5.0,
            unrealized_pnl_usd=pnl, chain="ethereum",
        )],
    )


def test_kill_switch_deterministic_at_config_threshold(policy):
    rng = _rng(5)
    thr = _CFG.max_drawdown_stop  # READ FROM CONFIG — single source of truth
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        # at/above threshold → kill; below → no kill (deterministic boundary)
        dd_kill = thr + rng.uniform(0.0, 0.20)
        dd_ok = rng.uniform(0.0, thr - 1e-6)

        r_kill = policy.check_portfolio_health(_state_with_drawdown(capital, dd_kill))
        assert r_kill.approved is False, f"dd={dd_kill} ≥ thr={thr} did NOT kill"
        assert any("KILL SWITCH" in v for v in r_kill.violations)

        r_ok = policy.check_portfolio_health(_state_with_drawdown(capital, dd_ok))
        # below threshold there is no KILL SWITCH violation (other warn-only checks
        # may add warnings, but never a kill-switch violation here)
        assert not any("KILL SWITCH" in v for v in r_ok.violations), (
            f"dd={dd_ok} < thr={thr} spuriously killed: {r_ok.violations}")


def test_kill_switch_monotone(policy):
    """Worse drawdown ⇒ still kill (never un-kills as it gets worse)."""
    rng = _rng(6)
    thr = _CFG.max_drawdown_stop
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        dd = thr + rng.uniform(0.0, 0.10)
        worse = dd + rng.uniform(1e-4, 0.50)
        killed = policy.check_portfolio_health(_state_with_drawdown(capital, dd)).approved
        killed_worse = policy.check_portfolio_health(
            _state_with_drawdown(capital, worse)).approved
        # both must be killed (approved=False); a worse drawdown never re-approves
        assert killed is False and killed_worse is False, (
            f"monotonicity broken: dd={dd}->{worse} approved {killed}->{killed_worse}")


# ---------------------------------------------------------------------------
# G6. The WHOLE gate NEVER RAISES on non-finite inputs → fail-closed.
#     Fuzz NaN/inf/-inf across amount/apy/tvl (check_new_position), drawdown
#     (check_portfolio_health via a corrupted-pnl proxy), and price
#     (check_portfolio_health depeg + check_stablecoin_depeg).
# ---------------------------------------------------------------------------
def test_non_finite_new_position_fail_closed_never_raises(policy):
    rng = _rng(7)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        state = PortfolioState(total_capital_usd=capital, positions=[])
        # randomly poison one (or more) of the numeric inputs with a non-finite
        amount = rng.uniform(1.0, capital * 0.2)
        apy = rng.uniform(1.0, 30.0)
        tvl = rng.uniform(_CFG.min_tvl_usd, 50_000_000.0)
        poisoned = rng.choice(["amount", "apy", "tvl"])
        bad = rng.choice(NON_FINITE)
        if poisoned == "amount":
            amount = bad
        elif poisoned == "apy":
            apy = bad
        else:
            tvl = bad
        # must NOT raise, and must fail closed
        result = policy.check_new_position(
            state, rng.choice(_PROTOCOLS), rng.choice(_TIERS),
            amount, apy, tvl, check_capacity=False,
        )
        assert result.approved is False, f"non-finite {poisoned}={bad} approved!"
        assert any("non-finite" in v for v in result.violations)


def test_non_finite_drawdown_fail_closed_kills(policy):
    rng = _rng(8)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        bad = rng.choice(NON_FINITE)

        class _BadState(PortfolioState):
            @property
            def total_drawdown_pct(self):
                return bad

        result = policy.check_portfolio_health(
            _BadState(total_capital_usd=capital, positions=[]))
        assert result.approved is False, f"non-finite drawdown {bad} not killed"
        assert any("non-finite portfolio drawdown" in v for v in result.violations)


def test_non_finite_price_fail_closed_both_depeg_paths(policy):
    rng = _rng(9)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        state = PortfolioState(total_capital_usd=capital, positions=[])
        bad = rng.choice(NON_FINITE)
        sym = rng.choice(["USDC", "USDT", "DAI", "sUSDe"])

        # path A: check_portfolio_health depeg branch
        r1 = policy.check_portfolio_health(state, stablecoin_prices={sym: bad})
        assert r1.approved is False, f"PH depeg non-finite {sym}={bad} approved"
        assert any("non-finite" in v for v in r1.violations)

        # path B: standalone check_stablecoin_depeg (the FOUND-AND-FIXED hole)
        r2 = policy.check_stablecoin_depeg({sym: bad})
        assert r2.approved is False, f"standalone depeg non-finite {sym}={bad} approved"
        assert any("non-finite" in v for v in r2.violations)


def test_zero_capital_new_position_fail_closed_never_raises(policy):
    """FOUND-AND-FIXED hole: total_capital_usd==0 used to raise ZeroDivisionError."""
    rng = _rng(10)
    for _ in range(N_CASES):
        bad_cap = rng.choice([0.0, -rng.uniform(1.0, 1e6)])
        state = PortfolioState(total_capital_usd=bad_cap, positions=[])
        # must NOT raise, must reject
        result = policy.check_new_position(
            state, rng.choice(_PROTOCOLS), rng.choice(_TIERS),
            amount_usd=rng.uniform(1.0, 1000.0),
            current_apy=rng.uniform(1.0, 30.0),
            tvl_usd=rng.uniform(_CFG.min_tvl_usd, 50_000_000.0),
            check_capacity=False,
        )
        assert result.approved is False, f"non-positive capital {bad_cap} approved!"


# ---------------------------------------------------------------------------
# G7. depeg-beyond-threshold / axis-breach → NEVER approved.
# ---------------------------------------------------------------------------
def test_critical_depeg_never_approved(policy):
    rng = _rng(11)
    thr = 0.02  # PriceFeedFetcher.DEFAULT_DEPEG_THRESHOLD; CRITICAL ⇔ |dev| ≥ 2*thr
    for _ in range(N_CASES):
        sym = rng.choice(["USDC", "USDT", "DAI"])
        # deviation strictly ≥ 2*thr (CRITICAL band), either side of peg
        dev = rng.uniform(2 * thr, 0.30)
        price = 1.0 + (dev if rng.random() < 0.5 else -dev)
        r = policy.check_stablecoin_depeg({sym: price})
        assert r.approved is False, f"CRITICAL depeg price {price} approved!"
        assert any("DEPEG KILL SWITCH" in v for v in r.violations)


def test_axis_breach_never_approved(policy):
    rng = _rng(12)
    # credit-axis limit is 0.15; allocate a credit protocol strictly above it.
    for _ in range(N_CASES):
        credit_w = rng.uniform(0.16, 1.0)
        alloc = {"maple-usdc-ethereum": round(credit_w, 4)}
        # optionally add a benign non-matching protocol
        if rng.random() < 0.5:
            alloc["aave-v3-usdc-ethereum"] = round(rng.uniform(0.0, 0.2), 4)
        r = policy.check_axis_compliance(alloc)
        assert r.approved is False, f"credit-axis breach {credit_w} approved! {alloc}"
        assert any("CREDIT" in v for v in r.violations)


# ---------------------------------------------------------------------------
# G8. Determinism: same seeded input → same verdict (verdict is a pure fn of
#     state + args; calling twice yields byte-identical approved + violations).
# ---------------------------------------------------------------------------
def test_verdict_deterministic(policy):
    rng = _rng(13)
    for _ in range(N_CASES):
        capital = rng.uniform(10_000.0, 1_000_000.0)
        state = PortfolioState(total_capital_usd=capital, positions=[])
        args = dict(
            protocol_key=rng.choice(_PROTOCOLS), tier=rng.choice(_TIERS),
            amount_usd=rng.uniform(0.0, capital * 1.2),
            current_apy=rng.uniform(-5.0, 50.0),
            tvl_usd=rng.uniform(0.0, 50_000_000.0),
            chain=rng.choice(_CHAINS), check_capacity=False,
        )
        r1 = policy.check_new_position(state, **args)
        r2 = policy.check_new_position(state, **args)
        assert r1.approved == r2.approved
        assert r1.violations == r2.violations


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
