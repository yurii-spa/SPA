"""Tests for spa_core.strategy_lab.metrics — known-series correctness, beta, drawdown,
beats-RWA-floor logic, compare_table rendering. Hermetic (no I/O)."""
# LLM_FORBIDDEN
import math

from spa_core.strategy_lab import metrics as M
from spa_core.strategy_lab.base import StrategyMetrics, Position


# ── net APY / drawdown ─────────────────────────────────────────────────────────
def test_net_apy_from_equity_positive():
    # 1% over 365 daily steps → ~1% annual.
    eq = [100000.0]
    for _ in range(365):
        eq.append(eq[-1] * (1 + 0.01 / 365))
    napy = M.net_apy_from_equity(eq)
    assert abs(napy - 1.0) < 0.05


def test_max_drawdown():
    # peak 100 → trough 80 → recover: 20% DD.
    eq = [100, 110, 88, 95, 120]  # peak 110 → 88 = 20%
    assert abs(M.max_drawdown_pct(eq) - 20.0) < 0.01


def test_max_drawdown_monotonic_zero():
    assert M.max_drawdown_pct([100, 101, 102, 103]) == 0.0


# ── Sharpe / Sortino on known series ───────────────────────────────────────────
def test_sharpe_known_series():
    # Constant positive daily return → infinite-ish Sharpe; use a series with known stats.
    rets = [0.001, 0.002, 0.0, 0.001, 0.002, 0.0, 0.001, 0.002, 0.0, 0.001]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    expected = (mean / std) * math.sqrt(365)
    assert abs(M.sharpe(rets) - round(expected, 4)) < 1e-3


def test_sharpe_fixed_apy_accrual_is_undefined_not_giant():
    """HONESTY GUARD (artifact class 4 — locked-vol Sharpe).

    A fixed-APY accrual (engine_a/b/c, rwa_floor, rwa_sleeve baselines) has return variance
    that is only floating-point rounding noise. The old code reported a Sharpe of ~451 million
    / ~1.16 billion, which reads to a user as a real, astronomically-good risk-adjusted score.
    A zero-variance series has an UNDEFINED Sharpe → must be None, never a giant finite number.
    """
    apy, eq, rets = 8.33, 100000.0, []
    for _ in range(750):  # mirrors the lab backtest window length
        gain = eq * (apy / 100.0) / 365.0
        rets.append(gain / eq)
        eq += gain
    assert M.sharpe(rets) is None  # was ~1.16e9 before the fix


def test_sharpe_exactly_constant_is_none():
    assert M.sharpe([0.0001, 0.0001, 0.0001, 0.0001]) is None


def test_sharpe_real_jitter_still_finite():
    # A genuinely noisy low-vol book (real daily APY jitter of basis points, std/mean ~ 0.1)
    # keeps an honest finite Sharpe — only float-noise-only series are nulled.
    rets = [0.0001, 0.00012, 0.00009, 0.00011, 0.00008, 0.00013, 0.0001]
    s = M.sharpe(rets)
    assert s is not None and 0.0 < s < 1e6


def test_sortino_penalizes_only_downside():
    # All non-negative returns vs rf=0 → no downside → 0.0 by our convention.
    assert M.sortino([0.001, 0.002, 0.0, 0.001]) == 0.0
    # With a negative return, downside deviation is finite and Sortino is computed.
    s = M.sortino([0.002, -0.001, 0.002, -0.001])
    assert s != 0.0


def test_volatility_zero_for_constant():
    assert M.volatility_pct([0.001, 0.001, 0.001]) == 0.0


# ── beta ~0 (neutral) / ~1 (directional) ───────────────────────────────────────
def test_beta_zero_neutral():
    # Strategy uncorrelated with ETH → beta ~ 0.
    eth = [0.05, -0.03, 0.02, -0.04, 0.01, 0.03, -0.02, 0.04]
    neutral = [0.0001, 0.0001, 0.0001, 0.0001, 0.0001, 0.0001, 0.0001, 0.0001]
    assert abs(M.beta(neutral, eth)) < 0.05


def test_beta_one_directional():
    # Strategy == ETH returns → beta == 1.
    eth = [0.05, -0.03, 0.02, -0.04, 0.01, 0.03, -0.02, 0.04]
    directional = list(eth)
    assert abs(M.beta(directional, eth) - 1.0) < 1e-6


def test_beta_half():
    eth = [0.05, -0.03, 0.02, -0.04, 0.01, 0.03, -0.02, 0.04]
    half = [0.5 * x for x in eth]
    assert abs(M.beta(half, eth) - 0.5) < 1e-6


# ── correlation to stable blend ────────────────────────────────────────────────
def test_correlation_perfect():
    a = [0.001, 0.002, 0.003, 0.004]
    b = [0.002, 0.004, 0.006, 0.008]
    assert abs(M.correlation(a, b) - 1.0) < 1e-6


def test_correlation_undefined_on_constant():
    assert M.correlation([0.001, 0.001, 0.001], [0.002, 0.003, 0.004]) is None


# ── funding drag ───────────────────────────────────────────────────────────────
def test_funding_drag():
    events = [
        {"type": "funding", "usd": -100.0},
        {"type": "funding", "usd": -50.0},
        {"type": "rebalance", "usd": -8.0},  # ignored
        {"type": "funding", "usd": 20.0},    # positive = received, not a drag
    ]
    # cost = 150 / 100000 * 100 = 0.15%
    assert abs(M.funding_drag_pct(events, 100000.0) - 0.15) < 1e-6


# ── tail scenario ──────────────────────────────────────────────────────────────
def test_tail_directional_takes_eth_shock():
    # beta=1 → -20% price leg, no short notional → ~-20%.
    pnl = M.tail_eth_down20_funding_flip_pct([], 100000.0, beta_to_eth=1.0)
    assert abs(pnl - (-20.0)) < 1e-6


def test_tail_neutral_funding_cost_dominates():
    # beta~0 hedged book; perp short pays funding when it flips.
    short = Position(asset="ETH-PERP", kind="perp_short", notional_usd=100000.0)
    pnl = M.tail_eth_down20_funding_flip_pct(
        [short], 100000.0, beta_to_eth=0.0, funding_flip_8h=0.0005, settles_per_day=3
    )
    # price leg ~0; funding cost = 100000 * 0.0005 * 3 = 150 → -0.15%
    assert abs(pnl - (-0.15)) < 1e-6


# ── beats RWA floor ────────────────────────────────────────────────────────────
def test_beats_floor_true():
    # 8% APY, 1% DD, floor 4.5% → excess 3.5 > DD 1 → True.
    assert M.beats_rwa_floor(8.0, 1.0, floor_apy_pct=4.5) is True


def test_beats_floor_false_below_floor():
    assert M.beats_rwa_floor(3.0, 0.5, floor_apy_pct=4.5) is False


def test_beats_floor_false_drawdown_erases_excess():
    # 6% APY (excess 1.5) but 5% DD → excess does not cover DD → False.
    assert M.beats_rwa_floor(6.0, 5.0, floor_apy_pct=4.5) is False


# ── compute_metrics aggregate ──────────────────────────────────────────────────
def test_compute_metrics_full():
    eq = [100000.0]
    rets = []
    for _ in range(30):
        r = 0.0001
        eq.append(eq[-1] * (1 + r))
        rets.append(r)
    eth = [0.01, -0.01] * 15
    stable = [0.0001] * 30
    m = M.compute_metrics(
        equity_series=eq,
        daily_returns=rets,
        eth_returns=eth,
        stable_returns=stable,
        events=[{"type": "funding", "usd": -10.0}],
        config={"capital_usd": 100000, "funding_settles_per_day": 3, "rwa_floor_apy_pct": 4.5},
        positions=[],
    )
    assert isinstance(m, StrategyMetrics)
    assert m.net_apy_pct is not None
    assert m.max_drawdown_pct == 0.0
    assert abs(m.beta_to_eth) < 0.05  # constant returns vs ETH → ~0 beta
    assert m.funding_drag_pct == round(10.0 / 100000 * 100, 4)
    assert isinstance(m.beats_rwa_floor, bool)


# ── compare table ──────────────────────────────────────────────────────────────
def test_compare_table_renders_and_flags():
    passer = StrategyMetrics(net_apy_pct=8.0, max_drawdown_pct=1.0, sharpe=2.0,
                             sortino=2.5, volatility_pct=1.0, beta_to_eth=0.0,
                             funding_drag_pct=0.1, corr_to_stable_blend=0.2,
                             tail_eth_down20_funding_flip_pct=-0.15, beats_rwa_floor=True)
    loser = StrategyMetrics(net_apy_pct=2.0, max_drawdown_pct=3.0, sharpe=0.1,
                            sortino=0.1, volatility_pct=5.0, beta_to_eth=1.0,
                            funding_drag_pct=0.0, corr_to_stable_blend=0.9,
                            tail_eth_down20_funding_flip_pct=-20.0, beats_rwa_floor=False)
    table = M.compare_table({"variant_n": passer, "variant_d": loser}, floor_apy_pct=4.5)
    assert "variant_n" in table
    assert "variant_d" in table
    assert "below floor" in table  # loser flagged
    assert "| Strategy |" in table
    assert "4.50% APY" in table
