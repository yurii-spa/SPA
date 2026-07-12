"""Q1-13 capital-efficiency guard — the missing check for silent under-earning.

Asserts: the observed LAZY scenario (idle cash + qualifying headroom) → WARNING; a STRUCTURAL book
(caps genuinely exhausted) → OK; and fail-CLOSED (idle book + unreadable feed → not a false OK).
Deterministic, no network (positions/apy passed as in-memory dicts via monkeypatched loaders).
"""
from __future__ import annotations

import spa_core.monitoring.capital_efficiency as ce


def _pos(cap, cash, positions):
    return {"capital_usd": cap, "cash_usd": cash, "deployed_usd": cap - cash, "positions": positions}


def _apy(rows):
    return {"by_apy": rows}


def _patch(monkeypatch, pos, apy):
    monkeypatch.setattr(ce, "_load", lambda p: pos if str(p).endswith("current_positions.json") else apy)


def test_lazy_idle_cash_warns(monkeypatch):
    # 20% cash (min 5%), one T1 anchor at cap; qualifying T1/T2 headroom exists → LAZY WARNING.
    pos = _pos(100000, 20000, [
        {"protocol": "aave_v3", "usd": 40000},
        {"protocol": "pendle", "usd": 20000},
        {"protocol": "susde", "usd": 10000},
        {"protocol": "morpho_steakhouse", "usd": 5000},
        {"protocol": "extra_finance_base", "usd": 5000},
    ])
    apy = _apy([
        {"protocol": "compound_v3", "tier": "T1", "apy_pct": 6.5},
        {"protocol": "spark_susds", "tier": "T1", "apy_pct": 6.0},
        {"protocol": "frax", "tier": "T2", "apy_pct": 7.5},
    ])
    _patch(monkeypatch, pos, apy)
    r = ce.assess()
    assert r["verdict"] == "WARNING", r
    assert r["idle_excess_pct"] == 0.15
    assert r["deployable_now_pct"] > 0.03
    assert r["forgone_yield_bps_est"] > 0


def test_structural_cash_is_ok(monkeypatch):
    # Idle cash but NO qualifying headroom (only T3 available, which is not counted as safe headroom)
    # → caps genuinely exhausted → OK, not flagged.
    pos = _pos(100000, 20000, [{"protocol": "aave_v3", "usd": 40000}, {"protocol": "pendle", "usd": 40000}])
    apy = _apy([{"protocol": "susde", "tier": "T3", "apy_pct": 12.0}])  # T3 only → no safe headroom
    _patch(monkeypatch, pos, apy)
    r = ce.assess()
    assert r["verdict"] == "OK", r
    assert r["deployable_headroom_pct"] == 0.0


def test_within_tolerance_is_ok(monkeypatch):
    # cash just above the 5% floor but within the 3pp tolerance → OK (do not cry wolf).
    pos = _pos(100000, 7000, [{"protocol": "aave_v3", "usd": 40000}, {"protocol": "pendle", "usd": 53000}])
    apy = _apy([{"protocol": "compound_v3", "tier": "T1", "apy_pct": 6.5}])
    _patch(monkeypatch, pos, apy)
    r = ce.assess()
    assert r["verdict"] == "OK", r


def test_fail_closed_unknown_when_feed_empty(monkeypatch):
    # Idle book over tolerance but the APY feed is empty/unreadable → cannot PROVE structural → UNKNOWN,
    # never a false OK (fail-CLOSED).
    pos = _pos(100000, 20000, [{"protocol": "aave_v3", "usd": 40000}, {"protocol": "pendle", "usd": 40000}])
    _patch(monkeypatch, pos, {})  # empty feed
    r = ce.assess()
    assert r["verdict"] == "UNKNOWN", r


def test_unreadable_positions_unknown(monkeypatch):
    monkeypatch.setattr(ce, "_load", lambda p: None)
    r = ce.assess()
    assert r["verdict"] == "UNKNOWN", r
