"""
tests/test_s22_s25_strategies.py — S22–S25 high-APY strategy expansion (2026-06-21)

Covers the four new strategies:
  S22 EthenaYieldMaxStrategy   — sUSDe 40% + Sky 30% + Aave 30%, depeg kill switch
  S23 PendlePTFixedStrategy    — PT 50% + Sky 30% + Aave 20%, fixed-rate / mock 7%
  S24 BaseChainMaxStrategy     — Morpho/Aave/Moonwell Base L2, phase-gated
  S25 YieldLadderStrategy      — barbell 60% T1 + 40% dynamic best T2

Tests are offline/stdlib-safe: adapters fall back to deterministic default APYs
when the live feed is unavailable, so assertions never depend on the network.
"""
from __future__ import annotations

import pytest

from spa_core.strategies.s22_ethena_yield_max import (
    EthenaYieldMaxStrategy,
    _norm_apy_pct as s22_norm,
    SLOTS as S22_SLOTS,
)
from spa_core.strategies.s23_pendle_pt_fixed import (
    PendlePTFixedStrategy,
    MOCK_PT_APY,
)
from spa_core.strategies.s24_base_chain_max import (
    BaseChainMaxStrategy,
    _is_phase2_active,
)
from spa_core.strategies.s25_yield_ladder import (
    YieldLadderStrategy,
    T2_CANDIDATES,
    T2_SLEEVE_WEIGHT,
)

CAPITAL = 100_000.0
ALL_CLASSES = [
    EthenaYieldMaxStrategy,
    PendlePTFixedStrategy,
    BaseChainMaxStrategy,
    YieldLadderStrategy,
]
ALL_IDS = ["S22", "S23", "S24", "S25"]


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def s22():
    return EthenaYieldMaxStrategy()


@pytest.fixture
def s23():
    return PendlePTFixedStrategy()


@pytest.fixture
def s24():
    return BaseChainMaxStrategy()


@pytest.fixture
def s25():
    return YieldLadderStrategy()


# ─── Smoke: instantiation + core surface (parametrized across all 4) ──────────

@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_instantiation(cls):
    strat = cls()
    assert strat is not None
    assert strat.STRATEGY_ID in ALL_IDS


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_has_core_methods(cls):
    strat = cls()
    for method in ("get_allocation", "get_expected_apy", "get_risk_summary",
                   "get_health", "simulate", "to_dict"):
        assert callable(getattr(strat, method))


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_allocation_sums_to_capital(cls):
    strat = cls()
    alloc = strat.get_allocation(CAPITAL)
    assert abs(sum(alloc.values()) - CAPITAL) < 1.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_allocation_all_positive(cls):
    strat = cls()
    alloc = strat.get_allocation(CAPITAL)
    assert all(v >= 0 for v in alloc.values())
    assert any(v > 0 for v in alloc.values())


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_zero_capital_zero_allocation(cls):
    strat = cls()
    alloc = strat.get_allocation(0.0)
    assert sum(alloc.values()) == 0.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_negative_capital_zero_allocation(cls):
    strat = cls()
    alloc = strat.get_allocation(-5000.0)
    assert sum(alloc.values()) == 0.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_expected_apy_positive(cls):
    strat = cls()
    assert strat.get_expected_apy() > 0.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_expected_apy_beats_baseline(cls):
    # All four target meaningfully above the current ~3.9% portfolio APY.
    strat = cls()
    assert strat.get_expected_apy() > 3.9


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_expected_apy_within_sane_bounds(cls):
    strat = cls()
    apy = strat.get_expected_apy()
    assert 1.0 <= apy <= 30.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_simulate_ok(cls):
    strat = cls()
    res = strat.simulate(CAPITAL)
    assert res["status"] == "ok"
    assert res["total_capital"] == CAPITAL
    assert res["expected_annual_yield_usd"] > 0.0
    assert "allocation" in res and res["allocation"]


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_simulate_zero_capital(cls):
    strat = cls()
    res = strat.simulate(0.0)
    assert res["status"] == "no_capital"
    assert res["expected_annual_yield_usd"] == 0.0


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_simulate_history_ring_buffer(cls):
    strat = cls()
    for _ in range(5):
        strat.simulate(CAPITAL)
    assert len(strat._simulate_history) == 5


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_health_status_valid(cls):
    strat = cls()
    health = strat.get_health()
    assert health["overall_status"] in ("ok", "degraded", "critical")
    assert health["strategy_id"] in ALL_IDS
    assert health["total_slots"] >= 1


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_risk_summary_has_score(cls):
    strat = cls()
    rs = strat.get_risk_summary()
    assert 0.0 <= rs["risk_score"] <= 1.0
    assert "risk_note" in rs


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_to_dict_serializable(cls):
    import json
    strat = cls()
    d = strat.to_dict()
    assert d["strategy_id"] in ALL_IDS
    # must be JSON-serializable
    json.dumps(d)


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_yield_matches_apy(cls):
    # annual yield USD ≈ capital * expected_apy / 100
    strat = cls()
    res = strat.simulate(CAPITAL)
    expected = CAPITAL * res["expected_apy_pct"] / 100.0
    assert abs(res["expected_annual_yield_usd"] - expected) < CAPITAL * 0.02


# ─── APY normalization helper ─────────────────────────────────────────────────

def test_norm_apy_decimal_scaled():
    assert s22_norm(0.05, 9.0) == 5.0


def test_norm_apy_percent_kept():
    assert s22_norm(7.5, 9.0) == 7.5


def test_norm_apy_none_fallback():
    assert s22_norm(None, 9.0) == 9.0


def test_norm_apy_zero_fallback():
    assert s22_norm(0.0, 9.0) == 9.0


def test_norm_apy_negative_fallback():
    assert s22_norm(-3.0, 9.0) == 9.0


def test_norm_apy_bool_fallback():
    assert s22_norm(True, 9.0) == 9.0


def test_norm_apy_string_fallback():
    assert s22_norm("8", 9.0) == 9.0


def test_norm_apy_boundary_one_is_percent():
    # exactly 1.0 is treated as 1% (percent), not decimal
    assert s22_norm(1.0, 9.0) == 1.0


# ─── S22: Ethena Yield Maximizer specifics ────────────────────────────────────

def test_s22_default_allocation_weights(s22):
    alloc = s22.get_allocation(CAPITAL)
    assert alloc["susde"] == pytest.approx(40_000.0)
    assert alloc["spark_susds"] == pytest.approx(30_000.0)
    assert alloc["aave_v3"] == pytest.approx(30_000.0)


def test_s22_t1_base_is_60pct(s22):
    rs = s22.get_risk_summary()
    # No depeg under normal conditions → T1 = 60%.
    assert rs["t1_weight_pct"] == pytest.approx(60.0)


def test_s22_depeg_returns_bool(s22):
    assert isinstance(s22.ethena_depeg_active(), bool)


def test_s22_kill_switch_reallocates(s22, monkeypatch):
    monkeypatch.setattr(s22, "ethena_depeg_active", lambda: True)
    alloc = s22.get_allocation(CAPITAL)
    # sUSDe bucket emptied, redistributed 50/50 into the T1 safe harbor.
    assert alloc.get("susde", 0.0) == 0.0
    assert alloc["spark_susds"] == pytest.approx(50_000.0)
    assert alloc["aave_v3"] == pytest.approx(50_000.0)
    assert abs(sum(alloc.values()) - CAPITAL) < 1.0


def test_s22_kill_switch_risk_summary_all_t1(s22, monkeypatch):
    monkeypatch.setattr(s22, "ethena_depeg_active", lambda: True)
    rs = s22.get_risk_summary()
    assert rs["t1_weight_pct"] == pytest.approx(100.0)
    assert rs["t3_weight_pct"] == pytest.approx(0.0)
    assert rs["ethena_depeg"] is True


def test_s22_slots_sum_to_one():
    assert sum(s["weight"] for s in S22_SLOTS.values()) == pytest.approx(1.0)


def test_s22_kill_switch_name(s22):
    assert s22.get_risk_summary()["kill_switch"] == "ethena_depeg"


# ─── S23: Pendle PT Fixed Rate specifics ──────────────────────────────────────

def test_s23_default_allocation_weights(s23):
    alloc = s23.get_allocation(CAPITAL)
    assert alloc["pendle_pt"] == pytest.approx(50_000.0)
    assert alloc["spark_susds"] == pytest.approx(30_000.0)
    assert alloc["aave_v3"] == pytest.approx(20_000.0)


def test_s23_pt_apy_positive(s23):
    assert s23.get_pt_apy() > 0.0


def test_s23_pt_live_returns_bool(s23):
    assert isinstance(s23.pt_is_live(), bool)


def test_s23_mock_rate_constant():
    assert MOCK_PT_APY == 7.0


def test_s23_fixed_rate_flag(s23):
    assert s23.get_risk_summary()["fixed_rate"] is True


def test_s23_t1_anchor_is_50pct(s23):
    rs = s23.get_risk_summary()
    assert rs["t1_weight_pct"] == pytest.approx(50.0)
    assert rs["t2_weight_pct"] == pytest.approx(50.0)


def test_s23_mock_used_when_no_adapter(monkeypatch):
    strat = PendlePTFixedStrategy()
    # Simulate the Pendle adapter being unavailable.
    strat._adapters.pop("pendle_pt", None)
    assert strat.get_pt_apy() == MOCK_PT_APY
    assert strat.pt_is_live() is False


# ─── S24: Base Chain Maximizer specifics ──────────────────────────────────────

def test_s24_default_allocation_weights(s24):
    alloc = s24.get_allocation(CAPITAL)
    assert alloc["morpho_blue_base"] == pytest.approx(40_000.0)
    assert alloc["aave_v3_base"] == pytest.approx(30_000.0)
    assert alloc["moonwell_base"] == pytest.approx(30_000.0)


def test_s24_all_t2(s24):
    assert s24.get_risk_summary()["t2_weight_pct"] == pytest.approx(100.0)


def test_s24_chain_is_base(s24):
    assert s24.get_risk_summary()["chain"] == "base"


def test_s24_mode_valid(s24):
    assert s24.get_mode() in ("phase2_base", "phase1_advisory")


def test_s24_phase_gate_function_returns_bool():
    assert isinstance(_is_phase2_active(), bool)


def test_s24_to_dict_has_phase_date(s24):
    assert s24.to_dict()["phase2_date"] == "2026-08-01"


# ─── S25: Yield Ladder (barbell) specifics ────────────────────────────────────

def test_s25_t1_base_is_60pct(s25):
    rs = s25.get_risk_summary()
    assert rs["t1_weight_pct"] == pytest.approx(60.0)
    assert rs["sleeve_weight_pct"] == pytest.approx(40.0)


def test_s25_barbell_flag(s25):
    assert s25.get_risk_summary()["barbell"] is True


def test_s25_select_best_t2_in_candidates(s25):
    key, apy = s25.select_best_t2()
    assert key in T2_CANDIDATES
    assert apy > 0.0


def test_s25_sleeve_is_highest_apy(s25):
    key, apy = s25.select_best_t2()
    # Selected sleeve APY must be >= every eligible candidate's APY.
    for cand in T2_CANDIDATES:
        if s25._is_eligible(cand):
            assert apy >= s25._get_adapter_apy(cand) - 1e-9


def test_s25_sleeve_gets_40pct(s25):
    alloc = s25.get_allocation(CAPITAL)
    key, _ = s25.select_best_t2()
    assert alloc.get(key, 0.0) >= 40_000.0 - 1.0


def test_s25_t1_base_in_allocation(s25):
    alloc = s25.get_allocation(CAPITAL)
    assert alloc["spark_susds"] == pytest.approx(30_000.0)
    assert alloc["aave_v3"] >= 30_000.0 - 1.0  # aave could also win sleeve? no — not a candidate


def test_s25_sleeve_weight_constant():
    assert T2_SLEEVE_WEIGHT == pytest.approx(0.40)


def test_s25_dynamic_selection_changes_with_apy(s25, monkeypatch):
    # Force maple to dominate → it must be selected.
    real = s25._get_adapter_apy

    def fake_apy(key):
        return 99.0 if key == "maple" else real(key)

    monkeypatch.setattr(s25, "_get_adapter_apy", fake_apy)
    key, apy = s25.select_best_t2()
    assert key == "maple"
    assert apy == pytest.approx(99.0)


# ─── Registry integration (both registries) ───────────────────────────────────

@pytest.mark.parametrize("sid", ALL_IDS)
def test_registered_in_strategy_registry(sid):
    from spa_core.strategies.strategy_registry import REGISTRY
    meta = REGISTRY.get(sid)
    assert meta is not None
    assert meta.risk_tier in ("T1", "T2", "T3")
    assert meta.target_apy_min < meta.target_apy_max


@pytest.mark.parametrize("sid", ALL_IDS)
def test_registered_in_paper_registry(sid):
    from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
    assert sid in STRATEGY_REGISTRY
    cfg = STRATEGY_REGISTRY[sid]
    assert sum(cfg.allocations.values()) <= 1.0 + 1e-9
    assert cfg.status in ("active", "paused", "killed", "promoted")


@pytest.mark.parametrize("sid,handler", [
    ("S22", "EthenaYieldMaxStrategy"),
    ("S23", "PendlePTFixedStrategy"),
    ("S24", "BaseChainMaxStrategy"),
    ("S25", "YieldLadderStrategy"),
])
def test_handler_class_matches(sid, handler):
    from spa_core.strategies.strategy_registry import REGISTRY
    assert REGISTRY.get(sid).handler_class == handler


def test_paper_registry_strategy_class_set():
    from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
    for sid in ALL_IDS:
        assert STRATEGY_REGISTRY[sid].strategy_class is not None
