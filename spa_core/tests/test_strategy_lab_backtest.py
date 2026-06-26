"""
spa_core/tests/test_strategy_lab_backtest.py — tests for the SHARED backtest harness.

All hermetic: synthetic MarketSnapshots are INJECTED (no network, no live files). The window
is engineered to contain both an ETH peak-to-trough drawdown AND a funding flip to negative so
the directional/neutral variants are genuinely stress-tested.

Coverage:
  - run_backtest produces metrics for ALL 6 strategies at the SAME initial_capital;
  - Variant D shows beta ≈ 1 and KILLS on a drawdown exceeding its Z threshold;
  - Variant N stays ~neutral (|beta| small);
  - determinism: two runs over identical injected snapshots are bit-for-bit identical;
  - window validation flags a too-calm window (no drawdown / no funding flip);
  - the comparative report renders (table + warnings + kill summary).

stdlib + pytest only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

import pytest

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab import backtest as BT
from spa_core.strategy_lab import report as RPT


# ──────────────────────────────────────────────────────────────────────────────
# config + snapshot fixtures
# ──────────────────────────────────────────────────────────────────────────────
def _config(drawdown_kill_pct: float = 25.0) -> dict:
    """Self-contained lab config dict (mirrors data/strategy_lab_config.json shape) so the
    test never depends on the on-disk SSOT."""
    return {
        "global": {
            "initial_capital": 100000.0,
            "window_start": "2026-06-10",
            "window_end": "2026-07-10",
            "seed": 42,
            "gas_usd_per_rebalance": 8.0,
            "slippage_bps": 5.0,
            "rebalance_bps": 2.0,
            "funding_settles_per_day": 3,
            "rwa_floor_apy_pct": 4.5,
        },
        "strategies": {
            "variant_n": {
                "lrt_symbol": "eeth",
                "hedge_ratio": 1.0,
                "funding_kill_threshold": -0.0003,
                "funding_kill_hours": 24,
                "lrt_depeg_kill_pct": 2.0,
                "points_apy_assumption": 0.03,
            },
            "variant_d": {
                "lrt_symbol": "eeth",
                "drawdown_kill_pct": drawdown_kill_pct,
            },
            "eth_lst_neutral": {
                "lst_symbol": "steth",
                "hedge_ratio": 1.0,
                "funding_kill_threshold": -0.0003,
                "funding_kill_hours": 24,
                "lst_depeg_kill_pct": 1.0,
            },
            "eth_lst_staking": {
                "lst_symbol": "steth",
                "drawdown_kill_pct": drawdown_kill_pct,
            },
            "btc_neutral": {
                "wrapper_symbol": "tbtc",
                "hedge_ratio": 1.0,
                "funding_kill_threshold": -0.0003,
                "funding_kill_hours": 24,
                "wrapper_depeg_kill_pct": 2.0,
            },
            "btc_lending_sleeve": {
                "wrapper_symbol": "tbtc",
                "drawdown_kill_pct": drawdown_kill_pct,
            },
            "engine_a": {"capital_usd": 100000, "apy_pct": 4.5},
            "engine_b": {"capital_usd": 20000},
            "engine_c": {"capital_usd": 10000},
            "rwa_floor": {"capital_usd": 100000, "apy_pct": 4.5},
            "rwa_sleeve": {"capital_usd": 100000, "apy_pct": 3.4, "drawdown_stop_pct": 1.0},
        },
    }


def _date(i: int) -> str:
    return (datetime.date(2026, 6, 10) + datetime.timedelta(days=i)).isoformat()


def _stress_snapshots(n_up: int = 8, n_down: int = 10):
    """A window with a clear ETH run-up then a >25% peak-to-trough drawdown, and funding that
    flips from positive to negative partway through. eeth ratio stays near peg (so Variant N
    survives the depeg kill and only its funding path is exercised)."""
    snaps = []
    price = 3000.0
    ratio = 1.03  # eeth/eth near peg, stable
    restaking = 0.032
    # Up-leg: price rises, funding positive.
    for i in range(n_up):
        price *= 1.01
        snaps.append(_mk(_date(i), price, 0.0001, ratio, restaking))
    peak_idx = n_up - 1
    # Down-leg: price falls ~3.5%/day for n_down days (cumulative > 25%), funding flips negative.
    for j in range(n_down):
        price *= 0.965
        funding = -0.0005  # flipped negative
        snaps.append(_mk(_date(n_up + j), price, funding, ratio, restaking))
    return snaps, peak_idx


def _calm_snapshots(n: int = 20):
    """A too-calm window: ETH drifts up gently (no >10% drawdown), funding always positive."""
    snaps = []
    price = 3000.0
    for i in range(n):
        price *= 1.001
        snaps.append(_mk(_date(i), price, 0.0002, 1.03, 0.032))
    return snaps


def _mk(date, eth_price, funding, ratio, restaking):
    # Carry the ETH legs (eeth LRT + steth LST) AND a parallel BTC leg (tbtc wrapper) so the
    # ETH-staking + BTC strategies are genuinely exercised in the shared harness, not killed on
    # missing data. BTC moves with ETH here (a correlated stress window) at a ~$60k base.
    btc_price = eth_price * 20.0
    return MarketSnapshot(
        date=date,
        eth_price_usd=eth_price,
        funding_rate_8h=funding,
        lrt_price_usd={"eeth": eth_price * ratio, "steth": eth_price * 1.0},
        lrt_eth_ratio={"eeth": ratio, "steth": 1.0},
        restaking_apy={"eeth": restaking, "steth": 0.026},
        defi_apy={"aave_v3": 0.045, "morpho": 0.07},
        btc_price_usd=btc_price,
        btc_funding_rate_8h=funding,
        btc_wrapper_price_usd={"tbtc": btc_price * 1.0},
        btc_wrapper_ratio={"tbtc": 1.0},
        btc_lending_apy={"tbtc": 0.004},
    )


# ──────────────────────────────────────────────────────────────────────────────
# all 6 strategies produce metrics, equal capital
# ──────────────────────────────────────────────────────────────────────────────
def test_run_backtest_all_six_strategies():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)

    strategies = result["strategies"]
    assert set(strategies) == {
        "variant_n", "variant_d", "eth_lst_neutral", "eth_lst_staking",
        "btc_neutral", "btc_lending_sleeve",
        "engine_a", "engine_b", "engine_c", "rwa_floor",
        "rwa_sleeve",
    }
    # Equal capital: every strategy was init'd at the SAME initial_capital. equity_first is
    # the post-first-tick value (day-1 accrual differs per strategy), so we assert it is
    # within a small band of the shared start capital rather than exactly equal.
    cap = cfg["global"]["initial_capital"]
    for sid, s in strategies.items():
        assert s["equity_first"] == pytest.approx(cap, rel=0.02), sid
        m = s["metrics"]
        # full metric set present (not None for the core fields)
        assert m["net_apy_pct"] is not None, sid
        assert m["max_drawdown_pct"] is not None, sid
        assert m["beats_rwa_floor"] is not None, sid
        # HONESTY (artifact class 4): Sharpe is None for a locked-vol fixed-APY baseline
        # (its return variance is float-noise only → a real Sharpe is undefined, NOT a giant
        # finite number). It must be either a sane finite value or None — never astronomical.
        sh = m["sharpe"]
        assert sh is None or abs(sh) < 1e6, (sid, sh)
    assert result["manifest"]["equal_capital"] is True
    assert result["manifest"]["initial_capital"] == cap


# ──────────────────────────────────────────────────────────────────────────────
# Variant D: beta ≈ 1, kills on the drawdown
# ──────────────────────────────────────────────────────────────────────────────
def test_variant_d_beta_one_and_kills_on_drawdown():
    cfg = _config(drawdown_kill_pct=25.0)
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)

    vd = result["strategies"]["variant_d"]
    # Directional sleeve tracks ETH → beta near 1.
    assert vd["metrics"]["beta_to_eth"] == pytest.approx(1.0, abs=0.15)
    # The >25% ETH drawdown must trip the Variant D drawdown kill.
    assert vd["kill"] is not None
    assert "drawdown" in vd["kill"]["reason"].lower()
    assert vd["kill"]["date"] in {s.date for s in snaps}
    assert "variant_d" in result["kills"]


def test_variant_d_no_kill_when_threshold_high():
    # With a very high kill threshold the same drawdown does NOT trip the kill.
    cfg = _config(drawdown_kill_pct=95.0)
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    assert result["strategies"]["variant_d"]["kill"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Variant N: ~neutral
# ──────────────────────────────────────────────────────────────────────────────
def test_variant_n_stays_neutral():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    vn = result["strategies"]["variant_n"]
    # Delta-neutral construction → |beta| small even across the ETH swing.
    assert abs(vn["metrics"]["beta_to_eth"]) < 0.25
    # Funding flipped negative for ≥24h → the neutral funding-kill path should fire.
    assert vn["kill"] is not None
    assert "funding" in vn["kill"]["reason"].lower()


# ──────────────────────────────────────────────────────────────────────────────
# determinism
# ──────────────────────────────────────────────────────────────────────────────
def test_determinism_two_runs_identical():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    r1 = BT.run_backtest(config=cfg, snapshots=snaps)
    r2 = BT.run_backtest(config=cfg, snapshots=snaps)
    # Drop generated_at (timestamp) before comparing — everything else must be identical.
    r1["manifest"].pop("generated_at")
    r2["manifest"].pop("generated_at")
    assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────────
# window validation
# ──────────────────────────────────────────────────────────────────────────────
def test_window_validation_flags_calm_window():
    cfg = _config()
    snaps = _calm_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    warns = result["window_warnings"]
    assert warns, "a calm window must emit window warnings"
    joined = " ".join(warns).lower()
    assert "variant d" in joined  # no drawdown → under-tests D
    assert "variant n" in joined  # no funding flip → under-tests N


def test_window_validation_passes_stress_window():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    assert result["window_warnings"] == []


# ──────────────────────────────────────────────────────────────────────────────
# report renders
# ──────────────────────────────────────────────────────────────────────────────
def test_report_renders():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    md = RPT.comparative_report(result)
    assert "# Strategy Lab — Comparative Backtest Report" in md
    assert "Comparative table" in md
    assert "rwa_floor" in md
    # the kill summary mentions a killed strategy
    assert "killed on" in md.lower()
    # all strategy ids appear in the table
    for sid in ("variant_n", "variant_d", "engine_a", "engine_b", "engine_c",
                "rwa_floor", "rwa_sleeve"):
        assert sid in md


def test_report_calm_window_warning_section():
    cfg = _config()
    snaps = _calm_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    md = RPT.comparative_report(result)
    assert "WINDOW WARNINGS" in md


# ──────────────────────────────────────────────────────────────────────────────
# honesty artifact (b): rwa_floor_source flag in the manifest + report
# ──────────────────────────────────────────────────────────────────────────────
def test_manifest_carries_rwa_floor_source_fallback(monkeypatch):
    import spa_core.strategy_lab.config as LC
    monkeypatch.setattr(LC, "_USE_LIVE_RWA_FLOOR", False)
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    man = result["manifest"]
    assert man["rwa_floor_source"] == "fallback"
    # fallback uses the committed literal from the config block (4.5 in the self-contained test cfg)
    assert man["rwa_floor_pct"] == pytest.approx(cfg["global"]["rwa_floor_apy_pct"])


def test_manifest_carries_rwa_floor_source_live(monkeypatch):
    import spa_core.strategy_lab.config as LC
    import spa_core.strategy_lab.data.rwa_feed as RF
    monkeypatch.setattr(LC, "_USE_LIVE_RWA_FLOOR", True)
    # Inject a live feed value so the source is unambiguously "live".
    monkeypatch.setattr(RF, "current_rwa_floor_pct", lambda *a, **k: 3.375)
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    man = result["manifest"]
    assert man["rwa_floor_source"] == "live"
    assert man["rwa_floor_pct"] == pytest.approx(3.375)


def test_report_labels_fallback_floor_not_as_live(monkeypatch):
    import spa_core.strategy_lab.config as LC
    monkeypatch.setattr(LC, "_USE_LIVE_RWA_FLOOR", False)
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    md = RPT.comparative_report(result)
    assert "fallback" in md.lower()
    assert "NOT a live rate" in md


def test_report_labels_live_floor(monkeypatch):
    import spa_core.strategy_lab.config as LC
    import spa_core.strategy_lab.data.rwa_feed as RF
    monkeypatch.setattr(LC, "_USE_LIVE_RWA_FLOOR", True)
    monkeypatch.setattr(RF, "current_rwa_floor_pct", lambda *a, **k: 3.375)
    cfg = _config()
    snaps, _ = _stress_snapshots()
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    md = RPT.comparative_report(result)
    assert "live tokenized-T-bill feed" in md


# ──────────────────────────────────────────────────────────────────────────────
# honesty artifact (c): realized vs configured window + truncation flag
# ──────────────────────────────────────────────────────────────────────────────
def test_manifest_window_realized_and_not_truncated():
    """Injected snapshots span the full configured window → realized==configured, not truncated."""
    cfg = _config()
    snaps, _ = _stress_snapshots()
    # Configure the window to exactly the injected snapshot span so it is NOT truncated.
    cfg["global"]["window_start"] = snaps[0].date
    cfg["global"]["window_end"] = snaps[-1].date
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    man = result["manifest"]
    assert man["window_realized"]["start"] == snaps[0].date
    assert man["window_realized"]["end"] == snaps[-1].date
    assert man["window_configured"]["start"] == snaps[0].date
    assert man["window_configured"]["end"] == snaps[-1].date
    assert man["window_truncated"] is False


def test_manifest_window_truncated_when_data_short():
    """Configured headline window is ~2yr but the injected data is a short span → truncated flag."""
    cfg = _config()
    snaps, _ = _stress_snapshots()
    cfg["global"]["window_start"] = "2024-06-05"   # headline ~2yr window
    cfg["global"]["window_end"] = "2026-06-24"
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    man = result["manifest"]
    assert man["window_truncated"] is True
    # realized span reflects the actual data, NOT the headline window
    assert man["window_realized"]["start"] == snaps[0].date
    assert man["window_realized"]["end"] == snaps[-1].date
    assert man["window_configured"]["start"] == "2024-06-05"


def test_report_shows_window_truncation_warning():
    cfg = _config()
    snaps, _ = _stress_snapshots()
    cfg["global"]["window_start"] = "2024-06-05"
    cfg["global"]["window_end"] = "2026-06-24"
    result = BT.run_backtest(config=cfg, snapshots=snaps)
    md = RPT.comparative_report(result)
    assert "WINDOW TRUNCATED" in md
