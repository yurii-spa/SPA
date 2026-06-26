"""
spa_core/tests/test_rwa_floor_live_wiring.py — DISCONNECTS (b) + (c) coverage.

(b) The forward-track FLOOR must be REAL: the RWAFloor baseline (and therefore the paper
    benchmark) accrues at the LIVE tokenized-T-bill rate (~3.375%), NOT the 4.5% committed
    literal. The literal is used ONLY as the fail-closed fallback when the live feed is down.

(c) The real allocatable T1 cash sleeve (rwa_sleeve) is built into the paper service's strategy
    set so it accrues a forward record like the other sleeves — reading the SAME live feed.

Internal consistency: the RWAFloor benchmark and the rwa_sleeve both read
config.rwa_floor_apy_pct(), which returns rwa_feed's live blended rate (the same value the
rwa_floor_curve persists).

Hermetic: the live feed is injected/monkeypatched (no network). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab import config as lab_config
from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab.data import rwa_feed
from spa_core.paper_trading import sleeve_yield
from spa_core.strategy_lab.strategies.baselines import RWAFloor
from spa_core.strategy_lab.strategies.rwa_sleeve import RwaSleeve

LIVE_RATE = 3.375  # the real TVL-weighted tokenized-T-bill floor (~3.375%, NOT the 4.5 literal)


def _snap(date="2026-06-10"):
    return MarketSnapshot(date=date, defi_apy={})


def _accrue_expected(capital, apy_pct, days):
    eq = capital
    for _ in range(days):
        eq += sleeve_yield.daily_yield(eq, apy_pct)
    return eq


# ── (b) RWAFloor benchmark accrues at the LIVE rate, not 4.5 ──────────────────────────────────────
def test_rwa_floor_apy_pct_returns_live_rate(monkeypatch):
    """config.rwa_floor_apy_pct(live=True) returns the live feed rate (~3.375), not the literal."""
    monkeypatch.setattr(rwa_feed, "current_rwa_floor_pct", lambda max_age_hours=24.0: LIVE_RATE)
    rate = lab_config.rwa_floor_apy_pct(live=True)
    assert rate == pytest.approx(LIVE_RATE)
    assert rate != pytest.approx(4.5), "must NOT be the 4.5 literal when the live feed is up"


def test_rwa_floor_baseline_accrues_at_live_rate_not_literal(monkeypatch):
    """The RWAFloor benchmark accrues at the LIVE ~3.375% — proving the forward floor is REAL."""
    monkeypatch.setattr(rwa_feed, "current_rwa_floor_pct", lambda max_age_hours=24.0: LIVE_RATE)
    s = RWAFloor()
    s.init(100_000.0, {"apy_pct": 4.5})  # config literal present but must be IGNORED while feed up
    days = 30
    for d in range(days):
        s.step(_snap(date=f"2026-06-{10 + d:02d}"))
    expected_live = _accrue_expected(100_000.0, LIVE_RATE, days)
    expected_literal = _accrue_expected(100_000.0, 4.5, days)
    assert s.equity() == pytest.approx(expected_live, abs=1e-6)
    assert s.equity() != pytest.approx(expected_literal, abs=1.0)  # demonstrably NOT the 4.5 track


def test_rwa_floor_falls_back_to_literal_when_feed_down(monkeypatch):
    """Feed down → config.rwa_floor_apy_pct returns the committed literal (fail-closed fallback)."""
    def _boom(max_age_hours=24.0):
        raise RuntimeError("feed down")
    monkeypatch.setattr(rwa_feed, "current_rwa_floor_pct", _boom)
    literal = float(lab_config.global_config()["rwa_floor_apy_pct"])
    rate = lab_config.rwa_floor_apy_pct(live=True)
    assert rate == pytest.approx(literal)  # 4.5 only as the fail-closed fallback


# ── (b) internal consistency — benchmark + sleeve read the SAME live rate ─────────────────────────
def test_floor_benchmark_and_sleeve_read_same_live_rate(monkeypatch):
    monkeypatch.setattr(rwa_feed, "current_rwa_floor_pct", lambda max_age_hours=24.0: LIVE_RATE)
    bench = RWAFloor(); bench.init(100_000.0, {"apy_pct": 4.5})
    sleeve = RwaSleeve(); sleeve.init(100_000.0, {"apy_pct": 3.4, "drawdown_stop_pct": 1.0})
    for d in range(20):
        bench.step(_snap(date=f"2026-06-{10 + d:02d}"))
        sleeve.step(_snap(date=f"2026-06-{10 + d:02d}"))
    # Both accrue at the SAME live rate → identical equity track.
    assert sleeve.equity() == pytest.approx(bench.equity(), abs=1e-6)
    assert sleeve.equity() == pytest.approx(_accrue_expected(100_000.0, LIVE_RATE, 20), abs=1e-6)


# ── (c) rwa_sleeve is built into the paper service + accrues a forward record ─────────────────────
class _FakeMarketData:
    def __init__(self, snapshot):
        self._snap = snapshot

    def latest(self):
        return self._snap


def test_rwa_sleeve_in_paper_service_strategy_set(tmp_path):
    from spa_core.strategy_lab.paper import PaperService
    md = _FakeMarketData(MarketSnapshot(date="2026-06-10", defi_apy={"x": 0.045}))
    svc = PaperService(market_data=md, state_dir=tmp_path, alert_on_kill=False, alert_on_gap=False)
    assert "rwa_sleeve" in svc._strategies
    assert svc._strategies["rwa_sleeve"].id == "rwa_sleeve"
    assert svc._strategies["rwa_sleeve"].is_advisory is True


def test_rwa_sleeve_accrues_a_forward_record_in_paper_service(tmp_path, monkeypatch):
    """rwa_sleeve must tick, accrue, and persist a dated series point like the other sleeves."""
    monkeypatch.setattr(rwa_feed, "current_rwa_floor_pct", lambda max_age_hours=24.0: LIVE_RATE)
    from spa_core.strategy_lab.paper import PaperService
    md = _FakeMarketData(MarketSnapshot(date="2026-06-10", defi_apy={"x": 0.045}))
    svc = PaperService(market_data=md, state_dir=tmp_path, alert_on_kill=False, alert_on_gap=False)

    start_equity = svc._strategies["rwa_sleeve"].equity()
    svc.tick()
    # a dated series point was persisted for the sleeve
    import json
    series = json.loads((tmp_path / "rwa_sleeve_series.json").read_text())["series"]
    assert len(series) == 1
    assert series[0]["date"] == "2026-06-10"
    # it actually accrued at the live floor (grew above its starting capital)
    assert svc._strategies["rwa_sleeve"].equity() > start_equity
