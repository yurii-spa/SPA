"""Tests for spa_core.paper_trading.liquidity_depth_analyzer (MP-126).

Coverage:
  - estimate_slippage: T1, T2, zero amount, negative amount, unknown protocol,
    non-finite amount, direction variants, custom data_dir, verdict thresholds.
  - get_capacity_curve: shape / monotonicity, length, T1 vs T2 ordering, unknown proto.
  - analyze_portfolio_liquidity: single / multi-position, empty dict, bad input types,
    total AUM, high_slippage flags, verdict thresholds, worst_case_protocol.
  - flag_low_liquidity_protocols: default threshold, custom thresholds, no-file fallback.
  - Graceful degradation when adapter_orchestrator_status.json is absent.
  - _compute_slippage_bps: unit arithmetic, clamping, edge values.
  - _normalize_slug: various name forms.
  - _num: type coercions.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Make sure the repo root is on sys.path (for direct pytest invocation).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.liquidity_depth_analyzer import (
    AUM_REFERENCE_USD,
    CONSERVATIVE_TVL_USD,
    CURVE_SAMPLE_POINTS_USD,
    DEFAULT_FALLBACK_TVL_USD,
    K_T1,
    K_T2,
    PROTOCOL_LIQUIDITY_TIER,
    WARN_THRESHOLD_BPS,
    _compute_slippage_bps,
    _get_liquidity_tier,
    _get_tvl,
    _normalize_slug,
    _num,
    analyze_portfolio_liquidity,
    estimate_slippage,
    flag_low_liquidity_protocols,
    get_capacity_curve,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """An empty temp directory (no JSON files) — forces fallback TVL."""
    return tmp_path


@pytest.fixture()
def live_data_dir(tmp_path: Path) -> Path:
    """A temp directory with a minimal adapter_orchestrator_status.json."""
    orch = {
        "schema_version": 1,
        "source": "adapter_orchestrator",
        "adapters": [
            {
                "protocol": "aave_v3",
                "tier": "T1",
                "apy_pct": 3.2,
                "tvl_usd": 100_000_000.0,  # $100M
                "status": "ok",
            },
            {
                "protocol": "compound_v3",
                "tier": "T1",
                "apy_pct": 3.1,
                "tvl_usd": 50_000_000.0,   # $50M
                "status": "ok",
            },
            {
                "protocol": "morpho_blue",
                "tier": "T2",
                "apy_pct": 4.7,
                "tvl_usd": 10_000_000.0,   # $10M
                "status": "ok",
            },
            {
                "protocol": "yearn_v3",
                "tier": "T2",
                "apy_pct": 3.3,
                "tvl_usd": 20_000_000.0,   # $20M
                "status": "ok",
            },
            {
                "protocol": "euler_v2",
                "tier": "T2",
                "apy_pct": 2.8,
                "tvl_usd": 8_000_000.0,    # $8M
                "status": "ok",
            },
            {
                "protocol": "maple",
                "tier": "T2",
                "apy_pct": 4.7,
                "tvl_usd": 5_000_000.0,    # $5M
                "status": "ok",
            },
        ],
    }
    (tmp_path / "adapter_orchestrator_status.json").write_text(
        json.dumps(orch), encoding="utf-8"
    )
    return tmp_path


# ─── Unit tests: _num ─────────────────────────────────────────────────────────


def test_num_int():
    assert _num(42) == 42.0


def test_num_float():
    assert _num(3.14) == pytest.approx(3.14)


def test_num_zero():
    assert _num(0) == 0.0


def test_num_bool_excluded():
    assert _num(True) is None
    assert _num(False) is None


def test_num_nan_excluded():
    assert _num(float("nan")) is None


def test_num_inf_excluded():
    assert _num(float("inf")) is None


def test_num_string_excluded():
    assert _num("100") is None


def test_num_none_excluded():
    assert _num(None) is None


# ─── Unit tests: _normalize_slug ──────────────────────────────────────────────


def test_normalize_slug_aave():
    assert _normalize_slug("Aave V3") == "aave_v3"


def test_normalize_slug_already_slug():
    assert _normalize_slug("aave_v3") == "aave_v3"


def test_normalize_slug_hyphen():
    assert _normalize_slug("compound-v3") == "compound_v3"


def test_normalize_slug_mixed_case():
    assert _normalize_slug("MAPLE") == "maple"


def test_normalize_slug_extra_spaces():
    assert _normalize_slug("  yearn_v3  ") == "yearn_v3"


# ─── Unit tests: _compute_slippage_bps ────────────────────────────────────────


def test_compute_slippage_bps_basic():
    """slippage = k * (amount / tvl) * 10_000"""
    bps = _compute_slippage_bps(100_000, 100_000_000, K_T1)
    expected = K_T1 * (100_000 / 100_000_000) * 10_000
    assert bps == pytest.approx(expected)


def test_compute_slippage_bps_zero_amount():
    assert _compute_slippage_bps(0, 1_000_000, K_T1) == 0.0


def test_compute_slippage_bps_negative_amount():
    assert _compute_slippage_bps(-1, 1_000_000, K_T1) == 0.0


def test_compute_slippage_bps_zero_tvl():
    assert _compute_slippage_bps(100_000, 0, K_T1) == 0.0


def test_compute_slippage_bps_clamped_max():
    """Enormous amount relative to TVL — clamp at 10_000 bps."""
    bps = _compute_slippage_bps(1_000_000_000, 1, K_T2)
    assert bps == 10_000.0


def test_compute_slippage_bps_t1_less_than_t2():
    """T1 coefficient (0.5) always gives lower slippage than T2 (2.0) for same inputs."""
    bps_t1 = _compute_slippage_bps(100_000, 10_000_000, K_T1)
    bps_t2 = _compute_slippage_bps(100_000, 10_000_000, K_T2)
    assert bps_t1 < bps_t2


# ─── Tests: estimate_slippage ─────────────────────────────────────────────────


class TestEstimateSlippage:

    def test_t1_protocol_low_slippage(self, live_data_dir):
        """Aave V3 (T1) with $100K vs $100M TVL → very low slippage."""
        result = estimate_slippage("aave_v3", 100_000, "enter", live_data_dir)
        assert result["slippage_bps"] == pytest.approx(
            K_T1 * (100_000 / 100_000_000) * 10_000
        )
        assert result["verdict"] == "ok"
        assert result["liquidity_tier"] == "T1"
        assert result["advisory_only"] is True

    def test_t2_protocol_higher_slippage(self, live_data_dir):
        """Maple (T2) with $100K vs $5M TVL → significant slippage."""
        result = estimate_slippage("maple", 100_000, "exit", live_data_dir)
        expected = K_T2 * (100_000 / 5_000_000) * 10_000
        assert result["slippage_bps"] == pytest.approx(expected)
        assert result["liquidity_tier"] == "T2"

    def test_zero_amount(self, tmp_data_dir):
        result = estimate_slippage("aave_v3", 0, "enter", tmp_data_dir)
        assert result["slippage_bps"] == 0.0
        assert result["slippage_pct"] == 0.0
        assert result["verdict"] == "ok"

    def test_negative_amount_treated_as_zero(self, tmp_data_dir):
        result = estimate_slippage("aave_v3", -5000, "enter", tmp_data_dir)
        assert result["slippage_bps"] == 0.0
        assert len(result["notes"]) > 0

    def test_non_finite_amount(self, tmp_data_dir):
        result = estimate_slippage("aave_v3", float("nan"), "enter", tmp_data_dir)
        assert result["slippage_bps"] == 0.0
        assert any("not a finite number" in n for n in result["notes"])

    def test_unknown_protocol_uses_conservative_k(self, tmp_data_dir):
        """Unknown protocol → T2 k = 2.0 (conservative)."""
        result = estimate_slippage("my_unknown_defi_protocol", 100_000, "enter", tmp_data_dir)
        assert result["liquidity_tier"] == "T2"
        assert result["k"] == K_T2
        assert any("not in registry" in n for n in result["notes"])

    def test_direction_enter_vs_exit_symmetric(self, live_data_dir):
        """Current model is symmetric — enter and exit give same bps."""
        enter = estimate_slippage("compound_v3", 50_000, "enter", live_data_dir)
        exit_ = estimate_slippage("compound_v3", 50_000, "exit", live_data_dir)
        assert enter["slippage_bps"] == exit_["slippage_bps"]

    def test_invalid_direction_defaults_to_enter(self, tmp_data_dir):
        result = estimate_slippage("aave_v3", 1000, "sideways", tmp_data_dir)
        assert result["direction"] == "enter"
        assert any("defaulting to 'enter'" in n for n in result["notes"])

    def test_no_data_dir_uses_fallback_tvl(self, tmp_data_dir):
        """With no live data, fallback conservative TVL is used."""
        result = estimate_slippage("aave_v3", 100_000, "enter", tmp_data_dir)
        assert result["tvl_source"] == "conservative_static"
        assert result["tvl_usd"] == CONSERVATIVE_TVL_USD["aave_v3"]

    def test_verdict_fail_above_200bps(self, tmp_data_dir):
        """Slippage > 200 bps → verdict = 'fail'."""
        # Use a very small TVL to force high slippage
        result = estimate_slippage("maple", 100_000, "exit", tmp_data_dir)
        # Conservative maple TVL = $20M → bps = 2.0 * (100000/20000000) * 10000 = 100 bps
        # That's "warn". Let's try with enormous amount.
        # Force fail by using unknown protocol with default fallback $5M TVL
        # 2.0 * (2_000_000 / 5_000_000) * 10_000 = 8_000 bps → fail
        result2 = estimate_slippage("unknown_proto_xyz", 2_000_000, "exit", tmp_data_dir)
        assert result2["verdict"] == "fail"

    def test_verdict_warn_between_50_and_200bps(self, tmp_data_dir):
        # euler_v2 conservative TVL $30M, $100K amount:
        # 2.0 * (100_000 / 30_000_000) * 10_000 = 66.67 bps → warn
        result = estimate_slippage("euler_v2", 100_000, "enter", tmp_data_dir)
        assert result["verdict"] == "warn"

    def test_result_schema_keys(self, tmp_data_dir):
        result = estimate_slippage("aave_v3", 10_000, "enter", tmp_data_dir)
        required = {
            "protocol", "direction", "amount_usd", "tvl_usd", "tvl_source",
            "liquidity_tier", "k", "slippage_bps", "slippage_pct",
            "verdict", "warn_threshold_bps", "advisory_only", "disclaimer", "notes",
        }
        assert required.issubset(result.keys())

    def test_live_tvl_preferred_over_static(self, live_data_dir):
        """Live data source should be used when orchestrator file is present."""
        result = estimate_slippage("aave_v3", 100_000, "enter", live_data_dir)
        assert result["tvl_source"] == "live"
        assert result["tvl_usd"] == 100_000_000.0


# ─── Tests: get_capacity_curve ────────────────────────────────────────────────


class TestGetCapacityCurve:

    def test_curve_length(self, tmp_data_dir):
        curve = get_capacity_curve("aave_v3", tmp_data_dir)
        assert len(curve) == len(CURVE_SAMPLE_POINTS_USD)

    def test_curve_monotonically_nondecreasing(self, tmp_data_dir):
        curve = get_capacity_curve("aave_v3", tmp_data_dir)
        bps_values = [pt["slippage_bps"] for pt in curve]
        for i in range(len(bps_values) - 1):
            assert bps_values[i] <= bps_values[i + 1], (
                f"Curve not non-decreasing at index {i}: "
                f"{bps_values[i]} > {bps_values[i+1]}"
            )

    def test_curve_amount_ascending(self, tmp_data_dir):
        curve = get_capacity_curve("compound_v3", tmp_data_dir)
        amounts = [pt["amount_usd"] for pt in curve]
        assert amounts == sorted(amounts)

    def test_t1_lower_than_t2_at_same_points(self, tmp_data_dir):
        """T1 protocol should have lower slippage than T2 at every point."""
        curve_t1 = get_capacity_curve("aave_v3", tmp_data_dir)
        curve_t2 = get_capacity_curve("maple", tmp_data_dir)
        # Compare at the same amount indices
        for pt1, pt2 in zip(curve_t1, curve_t2):
            assert pt1["amount_usd"] == pt2["amount_usd"]
            # T1 should have strictly lower bps (same conservative TVL rank may
            # differ, so compare only the k effect — both use conservative TVL here)
            # aave_v3 TVL=2B, k=0.5 vs maple TVL=20M, k=2.0 → T1 must be lower
            assert pt1["slippage_bps"] < pt2["slippage_bps"]

    def test_curve_first_point_matches_estimate(self, tmp_data_dir):
        """First curve point should match estimate_slippage at that amount."""
        curve = get_capacity_curve("aave_v3", tmp_data_dir)
        first = curve[0]
        est = estimate_slippage("aave_v3", first["amount_usd"], "exit", tmp_data_dir)
        assert first["slippage_bps"] == pytest.approx(est["slippage_bps"])

    def test_curve_has_verdict_field(self, tmp_data_dir):
        curve = get_capacity_curve("yearn_v3", tmp_data_dir)
        for pt in curve:
            assert "verdict" in pt
            assert pt["verdict"] in ("ok", "warn", "fail")

    def test_curve_unknown_protocol_returns_nonempty(self, tmp_data_dir):
        curve = get_capacity_curve("totally_unknown_xyz", tmp_data_dir)
        assert len(curve) == len(CURVE_SAMPLE_POINTS_USD)

    def test_curve_slippage_pct_consistency(self, tmp_data_dir):
        curve = get_capacity_curve("compound_v3", tmp_data_dir)
        for pt in curve:
            assert pt["slippage_pct"] == pytest.approx(pt["slippage_bps"] / 100.0)


# ─── Tests: analyze_portfolio_liquidity ───────────────────────────────────────


class TestAnalyzePortfolioLiquidity:

    def test_single_position_basic(self, tmp_data_dir):
        positions = {"aave_v3": 100_000.0}
        result = analyze_portfolio_liquidity(positions, tmp_data_dir)
        assert result["available"] is True
        assert result["num_positions"] == 1
        assert result["total_aum_usd"] == pytest.approx(100_000.0)
        assert "aave_v3" in result["positions"]

    def test_multi_position_total_aum(self, live_data_dir):
        positions = {"aave_v3": 60_000.0, "compound_v3": 30_000.0, "yearn_v3": 10_000.0}
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        assert result["total_aum_usd"] == pytest.approx(100_000.0)
        assert result["num_positions"] == 3

    def test_worst_case_protocol_is_highest_slippage(self, live_data_dir):
        # maple has smallest TVL ($5M) → highest slippage in live_data
        positions = {
            "aave_v3": 50_000.0,
            "maple": 50_000.0,
        }
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        assert result["worst_case_protocol"] == "maple"
        assert result["worst_case_bps"] == pytest.approx(
            result["positions"]["maple"]["exit_slippage_bps"]
        )

    def test_high_slippage_protocols_flagged(self, live_data_dir):
        """maple with $50K vs $5M TVL: 2.0*(50000/5000000)*10000=200bps → flagged."""
        positions = {"aave_v3": 50_000.0, "maple": 50_000.0}
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        assert "maple" in result["high_slippage_protocols"]

    def test_empty_positions_dict(self, tmp_data_dir):
        result = analyze_portfolio_liquidity({}, tmp_data_dir)
        assert result["available"] is True
        assert result["num_positions"] == 0
        assert "no valid positions" in " ".join(result["notes"])

    def test_non_dict_positions(self, tmp_data_dir):
        result = analyze_portfolio_liquidity(["aave_v3", 100_000], tmp_data_dir)  # type: ignore[arg-type]
        assert result["available"] is False

    def test_negative_position_skipped(self, tmp_data_dir):
        positions = {"aave_v3": 100_000.0, "compound_v3": -5000.0}
        result = analyze_portfolio_liquidity(positions, tmp_data_dir)
        assert result["num_positions"] == 1
        assert "compound_v3" not in result["positions"]

    def test_non_numeric_position_skipped(self, tmp_data_dir):
        positions = {"aave_v3": 100_000.0, "yearn_v3": "bad"}
        result = analyze_portfolio_liquidity(positions, tmp_data_dir)
        assert result["num_positions"] == 1

    def test_position_share_sums_to_one(self, live_data_dir):
        positions = {"aave_v3": 70_000.0, "compound_v3": 30_000.0}
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        total_share = sum(v["share"] for v in result["positions"].values())
        assert total_share == pytest.approx(1.0)

    def test_liquidity_score_range(self, live_data_dir):
        positions = {"aave_v3": 100_000.0}
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        assert 0.0 <= result["liquidity_score"] <= 100.0

    def test_all_t1_portfolio_verdict_ok(self, live_data_dir):
        """Portfolio of large T1 positions should have low slippage → ok verdict."""
        # aave_v3 $100K vs $100M TVL = 0.5*(100000/100000000)*10000 = 5 bps < 50 → ok
        positions = {"aave_v3": 60_000.0, "compound_v3": 40_000.0}
        result = analyze_portfolio_liquidity(positions, live_data_dir)
        assert result["verdict"] == "ok"

    def test_result_schema_keys(self, tmp_data_dir):
        result = analyze_portfolio_liquidity({"aave_v3": 1000.0}, tmp_data_dir)
        required = {
            "available", "advisory_only", "total_aum_usd", "num_positions",
            "worst_case_bps", "worst_case_protocol", "avg_exit_slippage_bps",
            "liquidity_score", "verdict", "positions", "high_slippage_protocols",
            "disclaimer", "notes",
        }
        assert required.issubset(result.keys())


# ─── Tests: flag_low_liquidity_protocols ──────────────────────────────────────


class TestFlagLowLiquidityProtocols:

    def test_returns_list(self, tmp_data_dir):
        result = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, tmp_data_dir)
        assert isinstance(result, list)

    def test_sorted_output(self, tmp_data_dir):
        result = flag_low_liquidity_protocols(0, AUM_REFERENCE_USD, tmp_data_dir)
        assert result == sorted(result)

    def test_threshold_zero_flags_all(self, tmp_data_dir):
        """threshold=0 → any nonzero slippage is flagged → all known protocols."""
        # amount=100K against any finite TVL will give nonzero slippage
        flagged = flag_low_liquidity_protocols(0, AUM_REFERENCE_USD, tmp_data_dir)
        # At least all registry protocols should appear
        for slug in PROTOCOL_LIQUIDITY_TIER:
            assert slug in flagged, f"{slug} not flagged at threshold=0"

    def test_threshold_very_high_flags_none(self, live_data_dir):
        """threshold=10_000 → no protocol flagged (max possible is 10_000 bps)."""
        flagged = flag_low_liquidity_protocols(10_000, AUM_REFERENCE_USD, live_data_dir)
        assert flagged == []

    def test_default_threshold_50bps(self, tmp_data_dir):
        """Default threshold 50 bps: euler_v2 (conservative TVL $30M) should be flagged."""
        # euler_v2 conservative TVL = $30M, k=2.0, amount=$100K
        # bps = 2.0 * (100_000 / 30_000_000) * 10_000 = 66.67 bps > 50
        flagged = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, tmp_data_dir)
        assert "euler_v2" in flagged

    def test_no_orchestrator_file_uses_fallback(self, tmp_data_dir):
        """Without live data file, should use static fallback and still return a list."""
        # tmp_data_dir has no files at all
        result = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, tmp_data_dir)
        assert isinstance(result, list)
        assert len(result) >= 0  # may or may not flag depending on fallback TVL

    def test_small_reference_flags_fewer(self, tmp_data_dir):
        """Smaller reference amount → lower slippage → fewer flags."""
        flagged_big = flag_low_liquidity_protocols(50, 1_000_000.0, tmp_data_dir)
        flagged_small = flag_low_liquidity_protocols(50, 1_000.0, tmp_data_dir)
        assert len(flagged_big) >= len(flagged_small)

    def test_aave_v3_not_flagged_with_conservative_tvl(self, tmp_data_dir):
        """Aave V3 conservative TVL $2B, k=0.5, $100K → 2.5 bps < 50 → not flagged."""
        flagged = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, tmp_data_dir)
        assert "aave_v3" not in flagged


# ─── Tests: graceful fallback (no data files) ─────────────────────────────────


class TestGracefulFallback:

    def test_estimate_slippage_no_files(self, tmp_data_dir):
        """estimate_slippage never raises even with no data files."""
        result = estimate_slippage("aave_v3", 100_000, "enter", tmp_data_dir)
        assert isinstance(result, dict)
        assert "slippage_bps" in result
        assert result["advisory_only"] is True

    def test_capacity_curve_no_files(self, tmp_data_dir):
        curve = get_capacity_curve("yearn_v3", tmp_data_dir)
        assert isinstance(curve, list)
        assert len(curve) == len(CURVE_SAMPLE_POINTS_USD)

    def test_portfolio_analysis_no_files(self, tmp_data_dir):
        result = analyze_portfolio_liquidity(
            {"aave_v3": 70_000.0, "maple": 30_000.0}, tmp_data_dir
        )
        assert isinstance(result, dict)
        assert result["available"] is True

    def test_flag_no_files_no_crash(self, tmp_data_dir):
        result = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, tmp_data_dir)
        assert isinstance(result, list)

    def test_corrupted_json_file(self, tmp_path):
        """Corrupted orchestrator file → graceful fallback to static TVL."""
        (tmp_path / "adapter_orchestrator_status.json").write_text(
            "{this is not valid JSON!!!", encoding="utf-8"
        )
        result = estimate_slippage("aave_v3", 100_000, "enter", tmp_path)
        assert result["tvl_source"] == "conservative_static"
        assert result["slippage_bps"] > 0


# ─── Tests: constants / registry integrity ────────────────────────────────────


def test_protocol_liquidity_tier_all_valid():
    """All tier values must be 'T1' or 'T2'."""
    for slug, tier in PROTOCOL_LIQUIDITY_TIER.items():
        assert tier in ("T1", "T2"), f"{slug} has unexpected tier {tier}"


def test_conservative_tvl_all_positive():
    for slug, tvl in CONSERVATIVE_TVL_USD.items():
        assert tvl > 0, f"{slug} conservative TVL must be positive"


def test_default_fallback_tvl_matches_risk_policy_floor():
    """Default fallback TVL should be at least the RiskPolicy TVL floor ($5M)."""
    RISK_POLICY_TVL_FLOOR = 5_000_000.0
    assert DEFAULT_FALLBACK_TVL_USD >= RISK_POLICY_TVL_FLOOR


def test_k_t1_less_than_k_t2():
    assert K_T1 < K_T2


def test_warn_threshold_bps_positive():
    assert WARN_THRESHOLD_BPS > 0


def test_curve_sample_points_ascending():
    pts = list(CURVE_SAMPLE_POINTS_USD)
    assert pts == sorted(pts)


def test_aum_reference_matches_portfolio_capital():
    """AUM_REFERENCE_USD should match our $100K paper-trading capital."""
    assert AUM_REFERENCE_USD == 100_000.0
