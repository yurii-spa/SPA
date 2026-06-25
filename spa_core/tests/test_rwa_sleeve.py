"""
spa_core/tests/test_rwa_sleeve.py — the T1 RWA cash-floor SLEEVE (an allocatable strategy).

Hermetic + deterministic: the live tokenized-T-bill floor is monkeypatched on rwa_feed so the
sleeve accrues at a known rate with NO network/disk. We assert:
  - it accrues at the live/config rwa rate over N days (the realized floor);
  - zero drawdown on normal data (T-bill NAV is stable);
  - it never kills on normal data;
  - fail-CLOSED: an out-of-band live rate makes step() raise (harness safe-holds);
  - fail-CLOSED kill_check on internal error;
  - the sleeve drawdown stop trips when equity falls below its config stop;
  - determinism: two identical runs are bit-for-bit identical;
  - identity: id/mandate/is_advisory/tier are the T1 advisory cash floor;
  - it is DISTINCT from the rwa_floor benchmark but lands at the same floor (both read the
    same live rate).

stdlib + pytest only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import MarketSnapshot, KillResult
from spa_core.strategy_lab.data import rwa_feed as RWA
from spa_core.strategy_lab.strategies.rwa_sleeve import RwaSleeve, TBILL_HOLDINGS


# ── helpers ───────────────────────────────────────────────────────────────────────────────────
def _snap(i: int = 0) -> MarketSnapshot:
    # The sleeve ignores market price entirely (NAV-stable); date is all that matters.
    return MarketSnapshot(date=f"2026-06-{10 + (i % 18):02d}")


def _pin_floor(monkeypatch, rate_pct: float) -> None:
    """Pin the live tokenized-T-bill floor to a known rate (config reads rwa_feed lazily)."""
    monkeypatch.setattr(RWA, "current_rwa_floor_pct", lambda *a, **k: rate_pct)


_CFG = {"capital_usd": 100_000.0, "apy_pct": 3.4, "drawdown_stop_pct": 1.0}


# ── identity ────────────────────────────────────────────────────────────────────────────────────
def test_identity_t1_advisory_stable():
    s = RwaSleeve()
    assert s.id == "rwa_sleeve"
    assert s.mandate == "stable"
    assert s.is_advisory is True
    assert s.tier == "T1"
    s.init(100_000.0, _CFG)
    pos = s.positions()
    assert len(pos) == 1
    assert pos[0].kind == "cash"
    assert pos[0].meta["tier"] == "T1"
    assert pos[0].meta["nav_stable"] is True
    assert set(pos[0].meta["holdings"]) == set(TBILL_HOLDINGS)


# ── accrues at the live/config rwa rate ─────────────────────────────────────────────────────────
def test_accrues_at_live_rwa_rate_over_n_days(monkeypatch):
    _pin_floor(monkeypatch, 3.40)
    s = RwaSleeve()
    s.init(100_000.0, _CFG)
    for i in range(365):
        s.step(_snap(i))
    gained = s.equity() - 100_000.0
    # ~3.40% compounded daily on $100k over a year ≈ $3,400 (a touch over from compounding).
    assert 3_350.0 < gained < 3_500.0
    # Realized net APY annualised sits at the floor (it banks the floor; does not beat it).
    assert s.metrics().net_apy_pct == pytest.approx(3.40, abs=0.1)


def test_accrual_matches_sleeve_yield_formula_first_day(monkeypatch):
    from spa_core.paper_trading import sleeve_yield
    _pin_floor(monkeypatch, 3.30)
    s = RwaSleeve()
    s.init(100_000.0, _CFG)
    s.step(_snap(0))
    expected = 100_000.0 + sleeve_yield.daily_yield(100_000.0, 3.30)
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_live_rate_changes_accrual(monkeypatch):
    # A different live floor → proportionally different one-day gain (it reads the LIVE rate).
    _pin_floor(monkeypatch, 3.0)
    a = RwaSleeve(); a.init(100_000.0, _CFG); a.step(_snap(0))
    _pin_floor(monkeypatch, 4.0)
    b = RwaSleeve(); b.init(100_000.0, _CFG); b.step(_snap(0))
    assert (b.equity() - 100_000.0) > (a.equity() - 100_000.0)


# ── zero drawdown / never kills on normal data ──────────────────────────────────────────────────
def test_zero_drawdown_and_never_kills_on_normal_data(monkeypatch):
    _pin_floor(monkeypatch, 3.40)
    s = RwaSleeve()
    s.init(100_000.0, _CFG)
    for i in range(200):
        s.step(_snap(i))
        kr = s.kill_check(_snap(i))
        assert kr.triggered is False, f"unexpected kill on day {i}: {kr.reason}"
    assert s.metrics().max_drawdown_pct == pytest.approx(0.0, abs=1e-9)


# ── fail-CLOSED: out-of-band live rate makes step() raise ───────────────────────────────────────
def test_fail_closed_on_bad_live_rate(monkeypatch):
    _pin_floor(monkeypatch, 99.0)  # absurd rate, outside the sane band
    s = RwaSleeve()
    s.init(100_000.0, _CFG)
    with pytest.raises(ValueError):
        s.step(_snap(0))


def test_fail_closed_kill_check_on_internal_error(monkeypatch):
    s = RwaSleeve()
    s.init(100_000.0, _CFG)
    # Force an internal error inside kill_check's drawdown computation.
    monkeypatch.setattr(s, "_drawdown_pct", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    kr = s.kill_check(_snap(0))
    assert isinstance(kr, KillResult)
    assert kr.triggered is True
    assert "fail-closed" in kr.reason.lower()


# ── the sleeve drawdown stop trips when breached ────────────────────────────────────────────────
def test_drawdown_stop_trips_when_breached(monkeypatch):
    _pin_floor(monkeypatch, 3.40)
    s = RwaSleeve()
    s.init(100_000.0, _CFG)  # stop = 1.0%
    s.step(_snap(0))  # set a peak above 100k
    # Simulate an (unrealistic) NAV impairment below the stop.
    s._equity = s._peak * (1.0 - 0.02)  # 2% drawdown > 1% stop
    kr = s.kill_check(_snap(1))
    assert kr.triggered is True
    assert "drawdown" in kr.reason.lower()
    # Once killed, step() is a no-op (safe-hold).
    eq_after_kill = s.equity()
    s.step(_snap(2))
    assert s.equity() == eq_after_kill


# ── determinism ─────────────────────────────────────────────────────────────────────────────────
def test_determinism_two_runs_identical(monkeypatch):
    _pin_floor(monkeypatch, 3.37)

    def run():
        s = RwaSleeve()
        s.init(100_000.0, _CFG)
        eqs = []
        for i in range(120):
            s.step(_snap(i))
            eqs.append(s.equity())
        return eqs

    assert run() == run()


# ── distinct from, but lands at, the benchmark floor ────────────────────────────────────────────
def test_sleeve_lands_at_same_floor_as_benchmark(monkeypatch):
    from spa_core.strategy_lab.strategies.baselines import RWAFloor
    _pin_floor(monkeypatch, 3.30)

    sleeve = RwaSleeve(); sleeve.init(100_000.0, _CFG)
    bench = RWAFloor(); bench.init(100_000.0, {"apy_pct": 99.0})  # config floor wins over init

    for i in range(365):
        sleeve.step(_snap(i))
        bench.step(_snap(i))

    # Distinct identities…
    assert sleeve.id != bench.id
    assert sleeve.tier == "T1"
    # …but both read the same live floor → equity matches to the cent (sleeve IS the realized floor).
    assert sleeve.equity() == pytest.approx(bench.equity(), abs=0.01)
    assert sleeve.metrics().max_drawdown_pct == pytest.approx(0.0, abs=1e-9)
