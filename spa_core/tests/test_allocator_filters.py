"""MP-011: тесты TVL-floor фильтра и совокупного T2-кап в StrategyAllocator.

Аллокатор обязан сам соблюдать лимиты RiskPolicy (min_tvl_usd=$5M,
max_total_t2_allocation=35%), иначе детерминированный гейт MP-005 в
cycle_runner блокирует каждый target и реальных сделок не происходит.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.allocator.allocator import StrategyAllocator


@pytest.fixture
def alloc():
    return StrategyAllocator()


# ── TVL-floor ─────────────────────────────────────────────────────────────

def test_tvl_floor_constant_matches_policy(alloc):
    assert alloc.TVL_FLOOR_USD == 5_000_000
    assert alloc.T2_TOTAL_CAP == 0.50  # ADR-019: поднят с 0.35 → 0.50


def test_tvl_floor_filters_low_tvl(alloc):
    pools = [
        {"protocol": "morpho", "tvl_usd": 402_000},
        {"protocol": "aave", "tvl_usd": 10_000_000},
    ]
    ok, rejected = alloc._filter_by_tvl(pools)
    assert len(ok) == 1
    assert ok[0]["protocol"] == "aave"
    assert rejected == ["morpho"]


def test_tvl_floor_keeps_high_tvl(alloc):
    pools = [{"protocol": "aave", "tvl_usd": 10_000_000}]
    ok, rejected = alloc._filter_by_tvl(pools)
    assert ok == pools
    assert rejected == []


def test_tvl_floor_fallback_all_filtered(alloc):
    # Если все плохие — не оставляем пустой список (fallback на исходный).
    pools = [{"protocol": "x", "tvl_usd": 100}]
    ok, _ = alloc._filter_by_tvl(pools)
    assert len(ok) >= 1


def test_real_morpho_scenario(alloc):
    pools = [
        {"protocol": "morpho_blue", "tvl_usd": 402_000},
        {"protocol": "aave_v3", "tvl_usd": 8_000_000_000},
    ]
    ok, _ = alloc._filter_by_tvl(pools)
    ids = [p["protocol"] for p in ok]
    assert "morpho_blue" not in ids
    assert "aave_v3" in ids


# ── T2-total cap ──────────────────────────────────────────────────────────

def test_t2_cap_enforced(alloc):
    weights = {"aave": 0.30, "morpho": 0.40, "euler": 0.30}
    tiers = {"aave": "T1", "morpho": "T2", "euler": "T2"}
    result, enforced = alloc._enforce_t2_total_cap(weights, tiers)
    assert enforced is True
    t2_sum = sum(w for p, w in result.items() if tiers.get(p) == "T2")
    assert abs(t2_sum - alloc.T2_TOTAL_CAP) < 0.001


def test_t2_cap_not_triggered(alloc):
    weights = {"aave": 0.70, "morpho": 0.30}
    tiers = {"aave": "T1", "morpho": "T2"}
    result, enforced = alloc._enforce_t2_total_cap(weights, tiers)
    assert enforced is False
    assert result == weights


def test_t2_freed_goes_to_t1(alloc):
    weights = {"aave": 0.30, "morpho": 0.70}
    tiers = {"aave": "T1", "morpho": "T2"}
    result, _ = alloc._enforce_t2_total_cap(weights, tiers)
    assert result["aave"] > weights["aave"]
    # T1 headroom = 40% − 30% = 10% < freed 35% → T1 упирается в свой cap.
    assert result["aave"] <= alloc.T1_CAP + 1e-9


def test_t2_no_t1_excess_stays_cash(alloc):
    # Нет T1 — излишек остаётся нераспределённым (кэш), не нарушая cap.
    weights = {"morpho": 0.60, "euler": 0.40}
    tiers = {"morpho": "T2", "euler": "T2"}
    result, _ = alloc._enforce_t2_total_cap(weights, tiers)
    t2_sum = sum(w for p, w in result.items() if tiers.get(p) == "T2")
    assert t2_sum <= alloc.T2_TOTAL_CAP + 0.001
    assert sum(result.values()) <= 1.0 + 1e-9


def test_t2_cap_respects_t1_per_protocol_cap(alloc):
    weights = {"aave": 0.38, "compound": 0.38, "morpho": 0.50, "euler": 0.20}
    tiers = {"aave": "T1", "compound": "T1", "morpho": "T2", "euler": "T2"}
    result, _ = alloc._enforce_t2_total_cap(weights, tiers)
    assert result["aave"] <= alloc.T1_CAP + 1e-9
    assert result["compound"] <= alloc.T1_CAP + 1e-9


# ── интеграция: allocate() соблюдает оба лимита ───────────────────────────

def test_allocate_end_to_end_respects_limits(tmp_path):
    snapshot = {
        "adapters": [
            {"protocol": "aave_v3", "status": "ok", "apy_pct": 4.1,
             "tvl_usd": 8_000_000_000, "tier": "T1"},
            {"protocol": "morpho_blue", "status": "ok", "apy_pct": 6.2,
             "tvl_usd": 402_000, "tier": "T1"},
            {"protocol": "pendle", "status": "ok", "apy_pct": 9.0,
             "tvl_usd": 50_000_000, "tier": "T2"},
            {"protocol": "euler", "status": "ok", "apy_pct": 7.0,
             "tvl_usd": 20_000_000, "tier": "T2"},
            {"protocol": "yearn", "status": "ok", "apy_pct": 6.5,
             "tvl_usd": 30_000_000, "tier": "T2"},
        ]
    }
    status = tmp_path / "adapter_orchestrator_status.json"
    status.write_text(json.dumps(snapshot), encoding="utf-8")
    a = StrategyAllocator(
        status_path=status,
        risk_scores_path=tmp_path / "missing_risk_scores.json",
        registry_path=tmp_path / "_no_registry.json",  # isolate from real registry
        allocation_model="equal_weight",
        strategy_loop_enabled=False,
    )
    res = a.allocate()
    # morpho_blue (TVL $402K < $5M) не должен получить вес.
    assert res.target_weights.get("morpho_blue", 0.0) == 0.0
    assert "morpho_blue" in res.tvl_filtered_protocols
    # Совокупный T2 ≤ 35%.
    t2 = sum(w for p, w in res.target_weights.items()
             if p in ("pendle", "euler", "yearn"))
    assert t2 <= a.T2_TOTAL_CAP + 0.001
    # Веса не превышают per-protocol cap'ы и сумма ≤ 1.
    assert all(w <= a.T1_CAP + 1e-9 for w in res.target_weights.values())
    assert sum(res.target_weights.values()) <= 1.0 + 1e-9
