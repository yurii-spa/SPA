"""
spa_core/tests/test_variant_n.py — Variant N (neutral / market-neutral restaking) tests.

Covers:
  - neutral behavior: a +20% ETH move barely changes equity (beta ≈ 0, hedge works)
  - positive funding accrues income; negative funding drags
  - funding kill fires after N hours sub-X (NOT before)
  - depeg kill fires at Y%
  - fail-closed on an invalid restaking / funding datapoint
  - determinism

All MarketSnapshots are built directly (no network).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab.strategies.variant_n import VariantN

LRT = "eeth"

# Merged config (strategy block + the global cost/cadence params the harness passes through).
BASE_CONFIG = {
    "lrt_symbol": LRT,
    "hedge_ratio": 1.0,
    "funding_kill_threshold": -0.0003,
    "funding_kill_hours": 24,
    "lrt_depeg_kill_pct": 2.0,
    "points_apy_assumption": 0.03,
    # global block (passed through merged):
    "funding_settles_per_day": 3,
    "gas_usd_per_rebalance": 8.0,
    "slippage_bps": 5.0,
    "rebalance_bps": 2.0,
}

CAPITAL = 100_000.0


def cfg(**over):
    c = dict(BASE_CONFIG)
    c.update(over)
    return c


def snap(
    date,
    eth=3000.0,
    funding=0.0001,
    ratio=1.03,
    restaking=0.032,
    drop_funding=False,
    drop_restaking=False,
    drop_eth=False,
    drop_ratio=False,
):
    s = MarketSnapshot(date=date)
    if not drop_eth:
        s.eth_price_usd = eth
    else:
        s.gaps.add("eth_price_usd")
    if not drop_funding:
        s.funding_rate_8h = funding
    else:
        s.gaps.add("funding_rate_8h")
    if not drop_ratio:
        s.lrt_eth_ratio = {LRT: ratio}
    else:
        s.gaps.add(f"lrt_eth_ratio.{LRT}")
    s.lrt_price_usd = {LRT: eth * ratio}
    if not drop_restaking:
        s.restaking_apy = {LRT: restaking}
    else:
        s.gaps.add("restaking_apy")
    return s


def new_strat(config=None):
    s = VariantN()
    s.init(CAPITAL, config or cfg())
    return s


# ── identity ──────────────────────────────────────────────────────────────────────────────
def test_identity():
    s = VariantN()
    assert s.id == "variant_n"
    assert s.mandate == "neutral"
    assert s.is_advisory is True


def test_init_opens_legs_on_first_step():
    s = new_strat()
    # before first step there is no live LRT/perp leg yet (lazy open on first real tick)
    s.step(snap("2026-06-10"))
    pos = s.positions()
    kinds = {p.kind for p in pos}
    assert "lrt" in kinds and "perp_short" in kinds
    lrt = next(p for p in pos if p.kind == "lrt")
    perp = next(p for p in pos if p.kind == "perp_short")
    # LRT notional ≈ capital; perp notional ≈ capital * hedge_ratio
    assert abs(lrt.notional_usd - CAPITAL) < 1.0
    assert abs(perp.notional_usd - CAPITAL * BASE_CONFIG["hedge_ratio"]) < 1.0


# ── neutral behavior: ETH +20% barely moves equity ─────────────────────────────────────────
def test_eth_up_20pct_is_neutral():
    # Zero funding + zero yield to isolate the price hedge; ratio fixed (no depeg).
    s = new_strat(cfg(points_apy_assumption=0.0))
    s.step(snap("2026-06-10", eth=3000.0, funding=0.0, ratio=1.03, restaking=0.0))
    eq0 = s.equity()
    s.step(snap("2026-06-11", eth=3600.0, funding=0.0, ratio=1.03, restaking=0.0))  # +20%
    eq1 = s.equity()
    # beta ≈ 0: a 20% ETH move must not produce anything like a 20% equity move.
    assert abs(eq1 - eq0) < CAPITAL * 0.005  # < 0.5% wobble
    assert s.metrics().beta_to_eth == 0.0


def test_eth_down_20pct_is_neutral():
    s = new_strat(cfg(points_apy_assumption=0.0))
    s.step(snap("2026-06-10", eth=3000.0, funding=0.0, ratio=1.03, restaking=0.0))
    eq0 = s.equity()
    s.step(snap("2026-06-11", eth=2400.0, funding=0.0, ratio=1.03, restaking=0.0))  # -20%
    eq1 = s.equity()
    assert abs(eq1 - eq0) < CAPITAL * 0.005


# ── funding sign convention ─────────────────────────────────────────────────────────────────
def test_positive_funding_accrues_income():
    # positive funding → short RECEIVES → income up; isolate from yield.
    s = new_strat(cfg(points_apy_assumption=0.0))
    s.step(snap("2026-06-10", eth=3000.0, funding=0.0002, ratio=1.03, restaking=0.0))
    m = s.metrics()
    assert m.extra["cum_funding_usd"] > 0
    assert s.equity() > CAPITAL  # only income source is funding → equity grew


def test_negative_funding_drags():
    s = new_strat(cfg(points_apy_assumption=0.0))
    s.step(snap("2026-06-10", eth=3000.0, funding=-0.0002, ratio=1.03, restaking=0.0))
    m = s.metrics()
    assert m.extra["cum_funding_usd"] < 0
    assert s.equity() < CAPITAL  # funding drag with no other income
    assert m.funding_drag_pct < 0


def test_restaking_and_points_accrue_income():
    s = new_strat()  # default points 0.03, restaking 0.032, funding ~0
    s.step(snap("2026-06-10", eth=3000.0, funding=0.0, ratio=1.03, restaking=0.032))
    # one day of (3.2% + 3.0%)/365 on ~100k ≈ $17
    assert s.equity() > CAPITAL
    daily = s.equity() - CAPITAL
    expected = CAPITAL * (0.032 + 0.03) / 365.0
    assert abs(daily - expected) < expected * 0.05


# ── funding kill: fires after N hours sub-X, not before ──────────────────────────────────────
def test_funding_kill_not_before_N_hours():
    # threshold -0.0003, kill_hours 24, settles 3/day → each sub-threshold tick adds 24h.
    s = new_strat()
    # ONE sub-threshold day = 24h which is >= 24 → would fire. Use a config of 48h to test "not before".
    s2 = new_strat(cfg(funding_kill_hours=48))
    s2.step(snap("2026-06-10", funding=-0.0005))
    k1 = s2.kill_check(snap("2026-06-10", funding=-0.0005))  # 24h accumulated
    assert k1.triggered is False  # 24h < 48h, not yet
    s2.step(snap("2026-06-11", funding=-0.0005))
    k2 = s2.kill_check(snap("2026-06-11", funding=-0.0005))  # 48h accumulated
    assert k2.triggered is True
    assert "funding" in k2.reason.lower()


def test_funding_kill_fires_at_N_hours():
    s = new_strat()  # kill_hours = 24
    s.step(snap("2026-06-10", funding=-0.0005))
    k = s.kill_check(snap("2026-06-10", funding=-0.0005))  # 24h >= 24h
    assert k.triggered is True


def test_funding_streak_resets_on_recovery():
    s = new_strat(cfg(funding_kill_hours=48))
    s.kill_check(snap("2026-06-10", funding=-0.0005))  # 24h
    rec = s.kill_check(snap("2026-06-11", funding=0.0002))  # recovers → streak resets
    assert rec.triggered is False
    again = s.kill_check(snap("2026-06-12", funding=-0.0005))  # only 24h again
    assert again.triggered is False  # would have been 72h if no reset; reset proves it


def test_above_threshold_funding_never_kills():
    s = new_strat()
    for d in range(1, 6):
        k = s.kill_check(snap(f"2026-06-1{d}", funding=-0.0001))  # above -0.0003
        assert k.triggered is False


# ── depeg kill at Y% ─────────────────────────────────────────────────────────────────────────
def test_depeg_kill_fires_at_Y_pct():
    # A SUSTAINED depeg beyond Y% fires once it persists past the smoothing/persistence guard
    # (that guard rejects 1-day DeFiLlama timestamp-misalignment artifacts, not real depegs).
    s = new_strat()  # depeg kill 2.0%, entry ratio 1.03
    s.step(snap("2026-06-10", ratio=1.03))  # entry ratio = 1.03
    k = None
    for d in range(11, 16):  # ratio stays -2.5% (sustained, beyond the 2% kill)
        k = s.kill_check(snap(f"2026-06-{d}", ratio=1.03 * 0.975))
        if k.triggered:
            break
    assert k.triggered is True
    assert "depeg" in k.reason.lower()


def test_small_depeg_does_not_kill():
    s = new_strat()
    s.step(snap("2026-06-10", ratio=1.03))
    k = s.kill_check(snap("2026-06-11", ratio=1.03 * 0.99))  # -1% < 2%
    assert k.triggered is False


def test_one_day_depeg_artifact_does_not_kill():
    # FALSE-depeg fix: a lone 1-day ratio spike (a DeFiLlama daily-granularity timestamp-
    # misalignment artifact — eeth showed spurious 0.95/1.14 in Aug-2024 while the peg held)
    # must NOT trip the depeg kill. The peg recovers the next tick → no sustained depeg.
    s = new_strat()  # entry ratio 1.03, kill 2.0%
    s.step(snap("2026-06-10", ratio=1.03))
    triggered = False
    for i, r in enumerate((1.0156, 0.9479, 1.1399, 0.9705, 1.03), start=11):
        if s.kill_check(snap(f"2026-06-{i}", ratio=r)).triggered:
            triggered = True
            break
    assert triggered is False


def test_sustained_depeg_still_kills():
    # A REAL multi-day depeg MUST still trigger the kill (the guard rejects 1-day artifacts only).
    s = new_strat()
    s.step(snap("2026-06-10", ratio=1.03))
    triggered = False
    for i, r in enumerate((1.00, 0.95, 0.92, 0.90), start=11):  # drops AND STAYS down
        if s.kill_check(snap(f"2026-06-{i}", ratio=r)).triggered:
            triggered = True
            break
    assert triggered is True


def test_depeg_shows_as_residual_loss():
    # the residual that survives the hedge is the ratio drift; a small depeg = small loss.
    s = new_strat(cfg(points_apy_assumption=0.0))
    s.step(snap("2026-06-10", eth=3000.0, funding=0.0, ratio=1.03, restaking=0.0))
    eq0 = s.equity()
    s.step(snap("2026-06-11", eth=3000.0, funding=0.0, ratio=1.03 * 0.99, restaking=0.0))
    eq1 = s.equity()
    assert eq1 < eq0  # 1% depeg with flat ETH → ~1% loss on the LRT notional
    assert abs((eq0 - eq1) - CAPITAL * 0.01) < CAPITAL * 0.001


# ── fail-closed on invalid data ──────────────────────────────────────────────────────────────
def test_fail_closed_invalid_restaking():
    s = new_strat()
    s.step(snap("2026-06-10", drop_restaking=True))
    # step fail-closes → killed; kill_check must report triggered.
    k = s.kill_check(snap("2026-06-10", drop_restaking=True))
    assert k.triggered is True


def test_fail_closed_invalid_funding_in_kill():
    s = new_strat()
    s.step(snap("2026-06-10"))
    k = s.kill_check(snap("2026-06-11", drop_funding=True))
    assert k.triggered is True
    assert "fail-closed" in k.reason.lower() or "missing" in k.reason.lower()


def test_fail_closed_invalid_ratio_in_kill():
    s = new_strat()
    s.step(snap("2026-06-10"))
    k = s.kill_check(snap("2026-06-11", drop_ratio=True))
    assert k.triggered is True


def test_killed_strategy_holds():
    s = new_strat()
    s.step(snap("2026-06-10", drop_funding=True))  # fail-closed kill in step
    eq_after_kill = s.equity()
    s.step(snap("2026-06-11"))  # subsequent step is a safe-hold (no accrual)
    assert s.equity() == eq_after_kill


# ── determinism ──────────────────────────────────────────────────────────────────────────────
def _run_sequence(config):
    s = VariantN()
    s.init(CAPITAL, config)
    snaps = [
        snap("2026-06-10", eth=3000.0, funding=0.0001, ratio=1.03, restaking=0.032),
        snap("2026-06-11", eth=3200.0, funding=0.00015, ratio=1.031, restaking=0.031),
        snap("2026-06-12", eth=2900.0, funding=-0.0001, ratio=1.029, restaking=0.033),
        snap("2026-06-13", eth=3100.0, funding=0.0002, ratio=1.030, restaking=0.032),
    ]
    out = []
    for sn in snaps:
        s.step(sn)
        k = s.kill_check(sn)
        out.append((s.equity(), k.triggered))
    return out, s.metrics()


def test_deterministic():
    r1, m1 = _run_sequence(cfg())
    r2, m2 = _run_sequence(cfg())
    assert r1 == r2
    assert m1.net_apy_pct == m2.net_apy_pct
    assert m1.funding_drag_pct == m2.funding_drag_pct


def test_no_mutation_of_input_snapshot():
    s = new_strat()
    sn = snap("2026-06-10")
    before = copy.deepcopy(sn)
    s.step(sn)
    s.kill_check(sn)
    assert sn.eth_price_usd == before.eth_price_usd
    assert sn.lrt_eth_ratio == before.lrt_eth_ratio
    assert sn.restaking_apy == before.restaking_apy
