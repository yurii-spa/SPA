"""
spa_core/tests/test_advisory_yield_sleeves.py — the generic ADVISORY 8-12% candidate sleeve.

Hermetic + deterministic: the sleeve accrues at a COMMITTED SOURCED literal `apy_pct` from its
config block (no live feed, no network/disk). We assert:
  - identity is set per-instance (id/name/tier/mandate/is_advisory);
  - it accrues at the config rate over N days;
  - first-day accrual matches the shared sleeve_yield formula;
  - fail-CLOSED: an out-of-band configured rate makes step() raise (harness safe-holds);
  - fail-CLOSED: a missing apy_pct makes init() raise;
  - fail-CLOSED kill_check on internal error;
  - the sleeve drawdown stop trips when breached, then step() is a no-op;
  - determinism: two identical runs are bit-for-bit identical;
  - positions/metrics carry the advisory + sourced-rate provenance.

stdlib + pytest only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import MarketSnapshot, KillResult
from spa_core.strategy_lab.strategies.advisory_yield_sleeve import AdvisoryYieldSleeve
from spa_core.paper_trading import sleeve_yield


def _snap(i: int = 0) -> MarketSnapshot:
    # The advisory sleeve ignores market data entirely; only the tick matters.
    return MarketSnapshot(date=f"2026-06-{10 + (i % 18):02d}")


def _cfg(apy: float = 11.2, stop: float = 12.0) -> dict:
    return {
        "name": "PT-sUSDe fixed carry (advisory)",
        "capital_usd": 100_000.0,
        "apy_pct": apy,
        "drawdown_stop_pct": stop,
        "apy_source": "Pendle PT-sUSDe (test)",
        "apy_as_of": "2026-07-02",
        "candidate_ref": "data/strategy_candidates/pt_susde_fixed.candidate.md",
    }


def _sleeve(apy: float = 11.2, stop: float = 12.0) -> AdvisoryYieldSleeve:
    s = AdvisoryYieldSleeve("pt_susde", "PT-sUSDe fixed carry (advisory)", "T2", "stable")
    s.init(100_000.0, _cfg(apy, stop))
    return s


# ── identity (per-instance) ─────────────────────────────────────────────────────────────────────
def test_identity_per_instance_advisory():
    s = _sleeve()
    assert s.id == "pt_susde"
    assert s.mandate == "stable"
    assert s.tier == "T2"
    assert s.is_advisory is True
    pos = s.positions()
    assert len(pos) == 1
    assert pos[0].meta["advisory"] is True
    assert pos[0].meta["apy_as_of"] == "2026-07-02"
    # a second instance with a different id does not collide
    s2 = AdvisoryYieldSleeve("maple_syrup", "Maple (advisory)", "T2")
    s2.init(100_000.0, _cfg(10.0))
    assert s2.id == "maple_syrup" and s.id == "pt_susde"


# ── accrues at the config rate ────────────────────────────────────────────────────────────────────
def test_accrues_at_config_rate_over_year():
    s = _sleeve(apy=11.2)
    for i in range(365):
        s.step(_snap(i))
    gained = s.equity() - 100_000.0
    # ~11.2% compounded daily on $100k over a year ≈ $11,850 (a touch over simple 11.2%).
    assert 11_800.0 < gained < 12_100.0
    # Realized annualized net APY = the full-year daily-compounded return of the 11.2% nominal
    # (compounding lifts it to ~11.85%), so it sits between the nominal and ~12%.
    assert 11.2 <= s.metrics().net_apy_pct <= 12.0


def test_first_day_matches_sleeve_yield_formula():
    s = _sleeve(apy=8.8)
    s.step(_snap(0))
    expected = 100_000.0 + sleeve_yield.daily_yield(100_000.0, 8.8)
    assert s.equity() == pytest.approx(expected, abs=1e-6)


def test_higher_config_rate_accrues_more():
    a = _sleeve(apy=8.0); a.step(_snap(0))
    b = _sleeve(apy=11.2); b.step(_snap(0))
    assert (b.equity() - 100_000.0) > (a.equity() - 100_000.0)


# ── fail-CLOSED ───────────────────────────────────────────────────────────────────────────────────
def test_fail_closed_on_out_of_band_rate():
    s = _sleeve(apy=99.0)  # absurd rate, outside the sane band → step raises
    with pytest.raises(ValueError):
        s.step(_snap(0))


def test_fail_closed_on_missing_apy_in_config():
    s = AdvisoryYieldSleeve("pt_susde", "x", "T2")
    with pytest.raises(ValueError):
        s.init(100_000.0, {"capital_usd": 100_000.0, "drawdown_stop_pct": 12.0})  # no apy_pct


def test_fail_closed_kill_check_on_internal_error(monkeypatch):
    s = _sleeve()
    monkeypatch.setattr(s, "_drawdown_pct", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    kr = s.kill_check(_snap(0))
    assert isinstance(kr, KillResult)
    assert kr.triggered is True
    assert "fail-closed" in kr.reason.lower()


# ── drawdown stop ─────────────────────────────────────────────────────────────────────────────────
def test_drawdown_stop_trips_then_step_is_noop():
    s = _sleeve(stop=12.0)
    s.step(_snap(0))  # set a peak
    s._equity = s._peak * (1.0 - 0.15)  # 15% drawdown > 12% stop
    kr = s.kill_check(_snap(1))
    assert kr.triggered is True
    assert "drawdown" in kr.reason.lower()
    eq_after = s.equity()
    s.step(_snap(2))
    assert s.equity() == eq_after  # killed → no further accrual


def test_no_kill_on_normal_accrual():
    s = _sleeve()
    for i in range(200):
        s.step(_snap(i))
        kr = s.kill_check(_snap(i))
        assert kr.triggered is False, f"unexpected kill on day {i}: {kr.reason}"
    # accrual-only model: equity only grows → zero drawdown
    assert s.metrics().max_drawdown_pct == pytest.approx(0.0, abs=1e-9)


# ── determinism ─────────────────────────────────────────────────────────────────────────────────
def test_determinism_two_runs_identical():
    def run():
        s = _sleeve(apy=9.5)
        eqs = []
        for i in range(120):
            s.step(_snap(i))
            eqs.append(s.equity())
        return eqs
    assert run() == run()


# ── provenance in metrics ─────────────────────────────────────────────────────────────────────────
def test_metrics_carry_sourced_provenance():
    s = _sleeve(apy=11.2)
    s.step(_snap(0))
    ex = s.metrics().extra
    assert ex["advisory"] is True
    assert ex["sourced_apy_pct"] == pytest.approx(11.2, abs=1e-9)
    assert ex["apy_as_of"] == "2026-07-02"
    assert "candidate_ref" in ex and ex["candidate_ref"].endswith(".candidate.md")
    assert "not a realized live yield" in ex["note"].lower()
