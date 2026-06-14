"""Tests for the MP-106 shadow-strategy framework (spa_core/shadow/).

Fully offline and deterministic: adapters are in-process fixtures, all writes
go to tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.shadow import STRATEGIES, compute_shadow_allocation, run_shadow_cycle
from spa_core.shadow.shadow_tracker import INITIAL_CAPITAL, SHADOW_FILENAME

# Orchestrator-form adapters (protocol/apy_pct), as run_cycle passes them.
ADAPTERS = [
    {"protocol": "aave_v3", "apy_pct": 4.0, "tier": "T1", "tvl_usd": 5e9, "status": "ok"},
    {"protocol": "compound_v3", "apy_pct": 3.5, "tier": "T1", "tvl_usd": 2e9, "status": "ok"},
    {"protocol": "morpho_blue", "apy_pct": 6.0, "tier": "T2", "tvl_usd": 1e9, "status": "ok"},
    {"protocol": "yearn_v3", "apy_pct": 5.0, "tier": "T2", "tvl_usd": 5e8, "status": "partial"},
    # error-status adapter must be ignored by every strategy
    {"protocol": "maple", "apy_pct": 9.0, "tier": "T2", "tvl_usd": 1e8, "status": "error"},
]

REAL_ALLOCATION = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0, "yearn_v3": 14_000.0}
REAL_EQUITY = 100_000.0

NOW = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)


# ─── Registry ────────────────────────────────────────────────────────────────


def test_registry_has_six_strategies():
    assert set(STRATEGIES) == {"S0", "S1", "S2", "S3", "S4", "S5"}
    names = {meta["name"] for meta in STRATEGIES.values()}
    assert names == {
        "MaxYield", "MaxSharpe", "EqualWeight", "T1Only", "Conservative", "CurrentSPA",
    }


def test_unknown_strategy_raises():
    with pytest.raises(KeyError):
        compute_shadow_allocation("S9", ADAPTERS, REAL_ALLOCATION)


# ─── Allocation rules ────────────────────────────────────────────────────────


def test_s0_max_yield_winner_takes_all():
    w = compute_shadow_allocation("S0", ADAPTERS, REAL_ALLOCATION)
    # maple (9%) has status=error → excluded; morpho_blue (6%) wins.
    assert w == {"morpho_blue": 1.0}


def test_s1_max_sharpe_proxy_normalized_and_prefers_t1():
    w = compute_shadow_allocation("S1", ADAPTERS, REAL_ALLOCATION)
    assert pytest.approx(sum(w.values())) == 1.0
    # score = apy / tier_vol: aave 4.0/1, compound 3.5/1, morpho 6.0/2, yearn 5.0/2
    assert w["aave_v3"] > w["morpho_blue"]  # 4.0 > 3.0 despite lower APY
    assert set(w) == {"aave_v3", "compound_v3", "morpho_blue", "yearn_v3"}


def test_s2_equal_weight_across_active_adapters():
    w = compute_shadow_allocation("S2", ADAPTERS, REAL_ALLOCATION)
    assert set(w) == {"aave_v3", "compound_v3", "morpho_blue", "yearn_v3"}
    assert all(v == pytest.approx(0.25) for v in w.values())


def test_s3_t1_only_equal_weights():
    w = compute_shadow_allocation("S3", ADAPTERS, REAL_ALLOCATION)
    assert w == {"aave_v3": pytest.approx(0.5), "compound_v3": pytest.approx(0.5)}


def test_s4_conservative_40_40_20_cash():
    w = compute_shadow_allocation("S4", ADAPTERS, REAL_ALLOCATION)
    assert w == {"aave_v3": pytest.approx(0.40), "compound_v3": pytest.approx(0.40)}
    assert sum(w.values()) == pytest.approx(0.80)  # 20% stays in cash


def test_s4_missing_leg_stays_in_cash():
    no_compound = [a for a in ADAPTERS if a["protocol"] != "compound_v3"]
    w = compute_shadow_allocation("S4", no_compound, REAL_ALLOCATION)
    assert w == {"aave_v3": pytest.approx(0.40)}  # 60% cash, never reallocated


def test_s5_mirrors_real_allocator_preserving_cash():
    w = compute_shadow_allocation(
        "S5", ADAPTERS, REAL_ALLOCATION, real_equity=REAL_EQUITY
    )
    assert w == {
        "aave_v3": pytest.approx(0.40),
        "morpho_blue": pytest.approx(0.20),
        "yearn_v3": pytest.approx(0.14),
    }
    assert sum(w.values()) == pytest.approx(0.74)  # structural cash preserved


def test_s5_empty_allocation_is_all_cash():
    assert compute_shadow_allocation("S5", ADAPTERS, {}) == {}


# ─── Tracker ─────────────────────────────────────────────────────────────────


def test_run_shadow_cycle_writes_doc_and_accrues_yield(tmp_path):
    doc = run_shadow_cycle(
        ADAPTERS, REAL_ALLOCATION, equity=REAL_EQUITY,
        data_dir=tmp_path, date="2026-06-10", now=NOW,
    )
    on_disk = json.loads((tmp_path / SHADOW_FILENAME).read_text())
    assert on_disk["date"] == "2026-06-10"
    assert set(on_disk["strategies"]) == set(STRATEGIES)

    # S0 = 100% morpho_blue @ 6%: pnl = 100000 * 6/100/365
    s0 = on_disk["strategies"]["S0"]
    assert s0["daily_pnl"] == pytest.approx(INITIAL_CAPITAL * 6.0 / 100 / 365, abs=1e-3)
    assert s0["equity"] == pytest.approx(INITIAL_CAPITAL + s0["daily_pnl"], abs=0.01)
    # advisory marker + history row written
    assert on_disk["advisory_only"] is True
    assert on_disk["history"][-1]["date"] == "2026-06-10"
    assert doc["strategies"]["S0"]["equity"] == s0["equity"]


def test_run_shadow_cycle_idempotent_same_day(tmp_path):
    run_shadow_cycle(ADAPTERS, REAL_ALLOCATION, equity=REAL_EQUITY,
                     data_dir=tmp_path, date="2026-06-10", now=NOW)
    doc2 = run_shadow_cycle(ADAPTERS, REAL_ALLOCATION, equity=REAL_EQUITY,
                            data_dir=tmp_path, date="2026-06-10", now=NOW)
    # Re-run on the same date recomputes from prev_equity — no double accrual.
    s0 = doc2["strategies"]["S0"]
    assert s0["prev_equity"] == pytest.approx(INITIAL_CAPITAL)
    assert s0["equity"] == pytest.approx(
        INITIAL_CAPITAL * (1 + 6.0 / 100 / 365), abs=0.01
    )
    assert len(doc2["history"]) == 1  # same-day row replaced, not appended


def test_run_shadow_cycle_compounds_across_days(tmp_path):
    run_shadow_cycle(ADAPTERS, REAL_ALLOCATION, equity=REAL_EQUITY,
                     data_dir=tmp_path, date="2026-06-10", now=NOW)
    doc2 = run_shadow_cycle(ADAPTERS, REAL_ALLOCATION, equity=REAL_EQUITY,
                            data_dir=tmp_path, date="2026-06-11", now=NOW)
    s0 = doc2["strategies"]["S0"]
    assert s0["prev_equity"] > INITIAL_CAPITAL  # day-1 close carried forward
    assert len(doc2["history"]) == 2


# ─── cycle_runner integration (fail-safe, after the real track persists) ─────


def _fake_orch_fn(data_dir):
    return SimpleNamespace(adapters=list(ADAPTERS), status="ok")


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(REAL_ALLOCATION),
            expected_apy_pct=4.5,
            model_used="fake",
            strategy_loop_active=False,
        )


def test_cycle_runner_writes_shadow_portfolio(tmp_path):
    from spa_core.paper_trading import cycle_runner as cr

    res = cr.run_cycle(
        data_dir=tmp_path,
        now=NOW,
        orchestrator_fn=_fake_orch_fn,
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,  # MP-109: no-op in tests
    )
    assert res.status == "ok"
    shadow = json.loads((tmp_path / SHADOW_FILENAME).read_text())
    assert shadow["date"] == "2026-06-10"
    assert set(shadow["strategies"]) == set(STRATEGIES)
    # S5 mirrors the cycle's effective positions against the real equity.
    s5_weights = shadow["strategies"]["S5"]["weights"]
    assert s5_weights["aave_v3"] == pytest.approx(40_000.0 / res.current_equity, rel=1e-4)


def test_cycle_runner_survives_broken_shadow(tmp_path, monkeypatch):
    """A crashing shadow tracker must never fail the real cycle (fail-safe)."""
    import spa_core.shadow.shadow_tracker as st
    from spa_core.paper_trading import cycle_runner as cr

    def _boom(*a, **kw):
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(st, "run_shadow_cycle", _boom)
    res = cr.run_cycle(
        data_dir=tmp_path,
        now=NOW,
        orchestrator_fn=_fake_orch_fn,
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,  # MP-109: no-op in tests
    )
    assert res.status == "ok"
    assert (tmp_path / "trades.json").exists()  # real track persisted anyway
    assert not (tmp_path / SHADOW_FILENAME).exists()
