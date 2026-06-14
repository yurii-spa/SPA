"""
Tests for spa_core/reporting/auto_promoter.py — ADR-029 Strategy Promotion
Automation Policy.

Coverage targets:
  - evaluate_strategy: Tier A / B / C routing + every exclusion gate
  - _check_tier_a / _check_tier_b: each criterion independently
  - evaluate_all: file loading, metrics derivation, summary counts
  - save_report: atomic write, valid JSON, directory creation
  - _compute_max_drawdown: edge cases
  - Boundary / exact-threshold values
  - Output shape contracts
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from spa_core.reporting.auto_promoter import (
    AutoPromoter,
    T3_SPEC_STRATEGIES,
    CAPITAL_AT_RISK_THRESHOLD_USD,
    _compute_max_drawdown,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_promoter() -> AutoPromoter:
    return AutoPromoter()


def _tier_a_metrics(**overrides) -> dict:
    """Default metrics that satisfy ALL Tier A criteria."""
    base = {
        "paper_days":      30,
        "sharpe":          1.2,
        "realized_apy":    11.0,
        "target_apy":      10.0,     # apy_ratio = 1.10 ✓
        "max_drawdown_pct": 4.9,     # < 5.0 ✓
        "halt_count":      0,
        "capital_at_risk": 1_000.0,
        "tier_label":      "T1",
    }
    base.update(overrides)
    return base


def _tier_b_metrics(**overrides) -> dict:
    """Default metrics satisfying Tier B but NOT Tier A."""
    base = {
        "paper_days":      30,
        "sharpe":          0.85,     # >= 0.8 but < 1.0
        "realized_apy":    9.0,
        "target_apy":      10.0,    # apy_ratio = 0.90 ✓ (Tier B), < 1.10 (not Tier A)
        "max_drawdown_pct": 6.0,    # < 8.0 ✓ but >= 5.0 (not Tier A)
        "halt_count":      0,
        "capital_at_risk": 500.0,
        "tier_label":      "T2",
    }
    base.update(overrides)
    return base


def _tier_c_metrics(**overrides) -> dict:
    """Default metrics that force Tier C (low sharpe)."""
    base = {
        "paper_days":      10,
        "sharpe":          0.5,
        "realized_apy":    5.0,
        "target_apy":      10.0,
        "max_drawdown_pct": 10.0,
        "halt_count":      2,
        "capital_at_risk": 0.0,
        "tier_label":      "T2",
    }
    base.update(overrides)
    return base


def _make_tournament_file(tmp_path: Path, strategies: list) -> Path:
    data = {
        "generated_at":   "2026-06-12",
        "strategies":     strategies,
        "strategy_count": len(strategies),
    }
    p = tmp_path / "tournament_ranking.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_policy_file(tmp_path: Path, auto_promote_enabled: bool = False) -> Path:
    data = {"auto_promote_enabled": auto_promote_enabled, "version": "1.0"}
    p = tmp_path / "promotion_policy.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _good_strategy_entry(**overrides) -> dict:
    """A tournament entry with all fields filled."""
    base = {
        "rank": 1,
        "id": "S1",
        "strategy_id": "s1_test",
        "name": "Test Strategy",
        "tier": "T1",
        "days_running": 30,
        "sharpe": 1.2,
        "apy_target": 10.0,
        "apy_realized": 11.0,
        "equity_series": [100000.0, 100500.0, 101000.0],
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Tier A — evaluate_strategy
# ===========================================================================

class TestTierA:
    def test_tier_a_all_criteria_pass(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics())
        assert r["tier"] == "A"
        assert r["eligible"] is True
        assert r["action"] == "AUTO_PROMOTE"

    def test_tier_a_fails_insufficient_days(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(paper_days=29))
        # paper_days < 30 → Tier C (before reaching Tier A check)
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"
        assert "paper_days" in r["reason"]

    def test_tier_a_fails_low_sharpe_below_tier_b_floor(self):
        """sharpe < 0.8 → Tier C gate fires before any Tier A check."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(sharpe=0.79))
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"
        assert "Sharpe" in r["reason"] or "sharpe" in r["reason"].lower()

    def test_tier_a_fails_low_sharpe_between_tiers(self):
        """sharpe = 0.95 passes Tier C gate but fails Tier A → Tier B."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(sharpe=0.95))
        assert r["tier"] == "B"
        assert r["action"] == "PENDING_48H"

    def test_tier_a_fails_low_apy_ratio(self):
        """apy_ratio = 1.05 → passes Tier B floor (0.90) but < 1.10 → Tier B, not A."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(realized_apy=10.5, target_apy=10.0))
        # ratio = 1.05 < 1.10 → not Tier A
        assert r["tier"] == "B"

    def test_tier_a_fails_apy_below_tier_b_floor(self):
        """apy_ratio < 0.90 → Tier C gate."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(realized_apy=8.9, target_apy=10.0))
        assert r["tier"] == "C"

    def test_tier_a_fails_high_drawdown_between_tiers(self):
        """drawdown = 5.5 — passes Tier C gate (< 8.0) but fails Tier A (< 5.0) → Tier B."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(max_drawdown_pct=5.5))
        assert r["tier"] == "B"

    def test_tier_a_fails_high_drawdown_tier_c(self):
        """drawdown >= 8.0 → Tier C gate."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(max_drawdown_pct=8.0))
        assert r["tier"] == "C"

    def test_tier_a_fails_halt_count(self):
        """Any halt → Tier C gate."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(halt_count=1))
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"
        assert "HALT" in r["reason"] or "halt" in r["reason"].lower()

    def test_tier_a_t3_spec_excluded_by_tier_label(self):
        """tier_label == 'T3-SPEC' forces Tier C regardless of metrics."""
        p = _make_promoter()
        r = p.evaluate_strategy("s_any", _tier_a_metrics(tier_label="T3-SPEC"))
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"
        assert "T3-SPEC" in r["reason"]

    def test_tier_a_t3_spec_excluded_by_strategy_id_s4(self):
        """strategy_id 's4_pendle_lp' in T3_SPEC_STRATEGIES → Tier C."""
        p = _make_promoter()
        r = p.evaluate_strategy("s4_pendle_lp", _tier_a_metrics(tier_label="T2"))
        assert r["tier"] == "C"
        assert "T3-SPEC" in r["reason"]

    def test_tier_a_t3_spec_excluded_by_strategy_id_s11(self):
        """strategy_id 's11_hybrid' in T3_SPEC_STRATEGIES → Tier C."""
        p = _make_promoter()
        r = p.evaluate_strategy("s11_hybrid", _tier_a_metrics(tier_label="T2"))
        assert r["tier"] == "C"

    def test_tier_a_capital_at_risk_gate(self):
        """capital_at_risk > 50_000 → Tier C size gate."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(capital_at_risk=50_001.0))
        assert r["tier"] == "C"
        assert "capital_at_risk" in r["reason"] or "size gate" in r["reason"]

    def test_tier_a_t2_strategy_promoted(self):
        """T2 strategies are eligible for Tier A."""
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_a_metrics(tier_label="T2"))
        assert r["tier"] == "A"
        assert r["eligible"] is True

    def test_tier_a_result_contains_criteria_results(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics())
        assert isinstance(r["criteria_results"], dict)
        assert "sharpe" in r["criteria_results"]
        assert "paper_days" in r["criteria_results"]

    def test_tier_a_reason_string_nonempty(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics())
        assert isinstance(r["reason"], str) and len(r["reason"]) > 0


# ===========================================================================
# 2. Tier B — evaluate_strategy
# ===========================================================================

class TestTierB:
    def test_tier_b_passes(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics())
        assert r["tier"] == "B"
        assert r["eligible"] is True
        assert r["action"] == "PENDING_48H"

    def test_tier_b_fails_low_sharpe_below_floor(self):
        """sharpe < 0.8 → Tier C gate before Tier B check."""
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(sharpe=0.79))
        assert r["tier"] == "C"

    def test_tier_b_fails_insufficient_days(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(paper_days=0))
        assert r["tier"] == "C"
        assert "paper_days" in r["reason"]

    def test_tier_b_fails_high_drawdown(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(max_drawdown_pct=8.0))
        assert r["tier"] == "C"

    def test_tier_b_fails_halt_count(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(halt_count=3))
        assert r["tier"] == "C"

    def test_tier_b_fails_low_apy_ratio(self):
        """apy_ratio < 0.90 → Tier C gate."""
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(realized_apy=8.9, target_apy=10.0))
        assert r["tier"] == "C"

    def test_tier_b_t3_spec_excluded(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics(tier_label="T3-SPEC"))
        assert r["tier"] == "C"

    def test_tier_b_contains_criteria_results(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s2_test", _tier_b_metrics())
        assert isinstance(r["criteria_results"], dict)
        assert "sharpe" in r["criteria_results"]

    def test_tier_b_t3_tier_not_excluded(self):
        """T3 (not T3-SPEC) is NOT in the excluded set — can reach Tier B."""
        p = _make_promoter()
        # T3 tier but all Tier B criteria met
        r = p.evaluate_strategy("s8_test", _tier_b_metrics(tier_label="T3"))
        assert r["tier"] == "B"


# ===========================================================================
# 3. Tier C — evaluate_strategy
# ===========================================================================

class TestTierC:
    def test_tier_c_catches_remainder(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s9_test", _tier_c_metrics())
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"
        assert r["eligible"] is False

    def test_tier_c_t3_spec_by_tier_label(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s_new", {"tier_label": "T3-SPEC"})
        assert r["tier"] == "C"
        assert "T3-SPEC" in r["reason"]

    def test_tier_c_t3_spec_by_strategy_id_set(self):
        p = _make_promoter()
        for sid in T3_SPEC_STRATEGIES:
            r = p.evaluate_strategy(sid, _tier_a_metrics())
            assert r["tier"] == "C", f"Expected Tier C for {sid}"

    def test_tier_c_halt_one(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(halt_count=1))
        assert r["tier"] == "C"

    def test_tier_c_halt_many(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(halt_count=99))
        assert r["tier"] == "C"

    def test_tier_c_low_sharpe_exactly_zero(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(sharpe=0.0))
        assert r["tier"] == "C"

    def test_tier_c_low_apy_ratio_zero_target(self):
        """target_apy = 0 → apy_ratio = 0.0 → Tier C."""
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(target_apy=0.0))
        assert r["tier"] == "C"

    def test_tier_c_capital_at_risk_exceeds_threshold(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(capital_at_risk=100_000.0))
        assert r["tier"] == "C"

    def test_tier_c_paper_days_zero(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_a_metrics(paper_days=0))
        assert r["tier"] == "C"

    def test_tier_c_reason_nonempty(self):
        p = _make_promoter()
        r = p.evaluate_strategy("s1_test", _tier_c_metrics())
        assert len(r["reason"]) > 0


# ===========================================================================
# 4. Output shape contracts — evaluate_strategy
# ===========================================================================

class TestEvaluateStrategyShape:
    REQUIRED_KEYS = {
        "strategy_id", "tier", "eligible", "reason",
        "criteria_results", "action", "evaluated_at",
    }

    @pytest.mark.parametrize("metrics_fn,sid", [
        (_tier_a_metrics, "s1_test"),
        (_tier_b_metrics, "s2_test"),
        (_tier_c_metrics, "s9_test"),
    ])
    def test_result_has_all_required_keys(self, metrics_fn, sid):
        p = _make_promoter()
        r = p.evaluate_strategy(sid, metrics_fn())
        assert self.REQUIRED_KEYS == self.REQUIRED_KEYS & set(r.keys())

    def test_strategy_id_preserved(self):
        p = _make_promoter()
        r = p.evaluate_strategy("my_strategy", _tier_a_metrics())
        assert r["strategy_id"] == "my_strategy"

    def test_tier_is_a_b_or_c(self):
        for m in [_tier_a_metrics(), _tier_b_metrics(), _tier_c_metrics()]:
            r = _make_promoter().evaluate_strategy("s_x", m)
            assert r["tier"] in {"A", "B", "C"}

    def test_action_auto_promote_for_tier_a(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics())
        assert r["action"] == "AUTO_PROMOTE"

    def test_action_pending_48h_for_tier_b(self):
        r = _make_promoter().evaluate_strategy("s2_test", _tier_b_metrics())
        assert r["action"] == "PENDING_48H"

    def test_action_manual_review_for_tier_c(self):
        r = _make_promoter().evaluate_strategy("s9_test", _tier_c_metrics())
        assert r["action"] == "MANUAL_REVIEW"

    def test_eligible_true_for_tier_a(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics())
        assert r["eligible"] is True

    def test_eligible_true_for_tier_b(self):
        r = _make_promoter().evaluate_strategy("s2_test", _tier_b_metrics())
        assert r["eligible"] is True

    def test_eligible_false_for_tier_c(self):
        r = _make_promoter().evaluate_strategy("s9_test", _tier_c_metrics())
        assert r["eligible"] is False

    def test_evaluated_at_is_iso_string(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics())
        ts = r["evaluated_at"]
        assert isinstance(ts, str) and "T" in ts and ts.endswith("Z")

    def test_criteria_results_is_dict(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics())
        assert isinstance(r["criteria_results"], dict)


# ===========================================================================
# 5. _check_tier_a
# ===========================================================================

class TestCheckTierA:
    def test_check_tier_a_all_pass(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics())
        assert result["pass"] is True

    def test_check_tier_a_fails_paper_days(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics(paper_days=29))
        assert result["pass"] is False
        assert result["criteria"]["paper_days"]["pass"] is False

    def test_check_tier_a_fails_sharpe(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics(sharpe=0.99))
        assert result["pass"] is False
        assert result["criteria"]["sharpe"]["pass"] is False

    def test_check_tier_a_fails_apy_ratio(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics(realized_apy=10.9, target_apy=10.0))
        assert result["pass"] is False
        assert result["criteria"]["apy_ratio"]["pass"] is False

    def test_check_tier_a_fails_drawdown(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics(max_drawdown_pct=5.0))
        assert result["pass"] is False
        assert result["criteria"]["max_drawdown_pct"]["pass"] is False

    def test_check_tier_a_fails_halt_count(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics(halt_count=1))
        assert result["pass"] is False
        assert result["criteria"]["halt_count"]["pass"] is False

    def test_check_tier_a_returns_criteria_dict(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics())
        assert "criteria" in result
        for key in ("paper_days", "sharpe", "apy_ratio", "max_drawdown_pct", "halt_count"):
            assert key in result["criteria"]

    def test_check_tier_a_criteria_have_required_sub_keys(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics())
        for crit in result["criteria"].values():
            assert "pass" in crit
            assert "value" in crit
            assert "threshold" in crit

    def test_check_tier_a_returns_pass_bool(self):
        p = _make_promoter()
        result = p._check_tier_a(_tier_a_metrics())
        assert isinstance(result["pass"], bool)


# ===========================================================================
# 6. _check_tier_b
# ===========================================================================

class TestCheckTierB:
    def test_check_tier_b_all_pass(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics())
        assert result["pass"] is True

    def test_check_tier_b_fails_paper_days(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics(paper_days=0))
        assert result["pass"] is False
        assert result["criteria"]["paper_days"]["pass"] is False

    def test_check_tier_b_fails_sharpe(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics(sharpe=0.79))
        assert result["pass"] is False
        assert result["criteria"]["sharpe"]["pass"] is False

    def test_check_tier_b_fails_apy_ratio(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics(realized_apy=8.9, target_apy=10.0))
        assert result["pass"] is False
        assert result["criteria"]["apy_ratio"]["pass"] is False

    def test_check_tier_b_fails_drawdown(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics(max_drawdown_pct=8.0))
        assert result["pass"] is False
        assert result["criteria"]["max_drawdown_pct"]["pass"] is False

    def test_check_tier_b_fails_halt_count(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics(halt_count=1))
        assert result["pass"] is False
        assert result["criteria"]["halt_count"]["pass"] is False

    def test_check_tier_b_returns_criteria_dict(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics())
        for key in ("paper_days", "sharpe", "apy_ratio", "max_drawdown_pct", "halt_count"):
            assert key in result["criteria"]

    def test_check_tier_b_criteria_have_required_sub_keys(self):
        p = _make_promoter()
        result = p._check_tier_b(_tier_b_metrics())
        for crit in result["criteria"].values():
            assert "pass" in crit and "value" in crit and "threshold" in crit


# ===========================================================================
# 7. evaluate_all — integration with mock files
# ===========================================================================

class TestEvaluateAll:
    def test_evaluate_all_reads_tournament_file(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path)
        p = _make_promoter()
        report = p.evaluate_all(str(t), str(pol))
        assert "strategies" in report
        assert len(report["strategies"]) == 1

    def test_evaluate_all_returns_summary(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        s = report["summary"]
        assert "total" in s and "tier_a" in s and "tier_b" in s and "tier_c" in s

    def test_evaluate_all_summary_counts_match(self, tmp_path):
        entries = [
            _good_strategy_entry(strategy_id="s1_t1", rank=1),
            _good_strategy_entry(
                strategy_id="s2_t2", rank=2, sharpe=0.85, apy_realized=9.0,
                apy_target=10.0, equity_series=[100_000.0, 100_500.0]
            ),
        ]
        t = _make_tournament_file(tmp_path, entries)
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        s = report["summary"]
        assert s["tier_a"] + s["tier_b"] + s["tier_c"] == s["total"]
        assert s["total"] == 2

    def test_evaluate_all_auto_promote_enabled_flag(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path, auto_promote_enabled=True)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report["summary"]["auto_promote_enabled"] is True

    def test_evaluate_all_auto_promote_disabled(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path, auto_promote_enabled=False)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report["summary"]["auto_promote_enabled"] is False

    def test_evaluate_all_has_generated_at(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert "generated_at" in report
        assert report["generated_at"].endswith("Z")

    def test_evaluate_all_has_adr_reference(self, tmp_path):
        t = _make_tournament_file(tmp_path, [_good_strategy_entry()])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report.get("adr_reference") == "ADR-029"

    def test_evaluate_all_t3_spec_in_tournament_goes_tier_c(self, tmp_path):
        entry = _good_strategy_entry(strategy_id="s11_hybrid", tier="T3-SPEC", rank=1)
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report["strategies"][0]["tier"] == "C"

    def test_evaluate_all_handles_null_sharpe(self, tmp_path):
        entry = _good_strategy_entry(sharpe=None)
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        # null sharpe → 0.0 → Tier C (sharpe < 0.8)
        assert report["strategies"][0]["tier"] == "C"

    def test_evaluate_all_handles_null_apy_realized(self, tmp_path):
        entry = _good_strategy_entry(apy_realized=None)
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        # null apy_realized → 0.0 → apy_ratio = 0 < 0.90 → Tier C
        assert report["strategies"][0]["tier"] == "C"

    def test_evaluate_all_handles_empty_equity_series(self, tmp_path):
        entry = _good_strategy_entry(equity_series=[])
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        # Should not raise
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert len(report["strategies"]) == 1

    def test_evaluate_all_strategy_count_matches(self, tmp_path):
        entries = [_good_strategy_entry(strategy_id=f"s{i}_test", rank=i) for i in range(5)]
        t = _make_tournament_file(tmp_path, entries)
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report["summary"]["total"] == 5

    def test_evaluate_all_result_includes_name_and_rank(self, tmp_path):
        entry = _good_strategy_entry(name="My Strategy", rank=3)
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        s = report["strategies"][0]
        assert s["name"] == "My Strategy"
        assert s["rank"] == 3

    def test_evaluate_all_no_strategy_id_field_falls_back_to_id(self, tmp_path):
        """Entries without 'strategy_id' key use lowercase 'id' field."""
        entry = {
            "rank": 1,
            "id": "S99",
            "name": "Fallback Strategy",
            "tier": "T1",
            "days_running": 30,
            "sharpe": 1.2,
            "apy_target": 10.0,
            "apy_realized": 11.0,
            "equity_series": [100_000.0, 101_100.0],
        }
        t = _make_tournament_file(tmp_path, [entry])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        sid = report["strategies"][0]["strategy_id"]
        assert sid == "s99"  # lowercase fallback

    def test_evaluate_all_raises_on_missing_tournament_file(self, tmp_path):
        pol = _make_policy_file(tmp_path)
        with pytest.raises(FileNotFoundError):
            _make_promoter().evaluate_all(
                str(tmp_path / "nonexistent.json"), str(pol)
            )

    def test_evaluate_all_empty_strategies_list(self, tmp_path):
        t = _make_tournament_file(tmp_path, [])
        pol = _make_policy_file(tmp_path)
        report = _make_promoter().evaluate_all(str(t), str(pol))
        assert report["summary"]["total"] == 0
        assert report["strategies"] == []


# ===========================================================================
# 8. save_report — atomic write
# ===========================================================================

class TestSaveReport:
    def _sample_report(self) -> dict:
        return {
            "adr_reference": "ADR-029",
            "strategies": [],
            "summary": {"total": 0, "tier_a": 0, "tier_b": 0, "tier_c": 0,
                        "auto_promote_enabled": False},
            "generated_at": "2026-06-12T00:00:00Z",
        }

    def test_save_report_creates_file(self, tmp_path):
        p = _make_promoter()
        p.save_report(self._sample_report(), data_dir=str(tmp_path))
        assert (tmp_path / "promotion_report.json").exists()

    def test_save_report_file_content_valid_json(self, tmp_path):
        p = _make_promoter()
        report = self._sample_report()
        p.save_report(report, data_dir=str(tmp_path))
        with open(tmp_path / "promotion_report.json", "r") as fh:
            loaded = json.load(fh)
        assert loaded["adr_reference"] == "ADR-029"

    def test_save_report_content_matches_input(self, tmp_path):
        p = _make_promoter()
        report = self._sample_report()
        report["summary"]["total"] = 42
        p.save_report(report, data_dir=str(tmp_path))
        loaded = json.loads((tmp_path / "promotion_report.json").read_text())
        assert loaded["summary"]["total"] == 42

    def test_save_report_creates_dir_if_missing(self, tmp_path):
        nested = tmp_path / "nested" / "subdir"
        p = _make_promoter()
        p.save_report(self._sample_report(), data_dir=str(nested))
        assert (nested / "promotion_report.json").exists()

    def test_save_report_overwrites_existing(self, tmp_path):
        p = _make_promoter()
        # Write first version
        r1 = self._sample_report()
        r1["summary"]["total"] = 1
        p.save_report(r1, data_dir=str(tmp_path))
        # Overwrite
        r2 = self._sample_report()
        r2["summary"]["total"] = 99
        p.save_report(r2, data_dir=str(tmp_path))
        loaded = json.loads((tmp_path / "promotion_report.json").read_text())
        assert loaded["summary"]["total"] == 99

    def test_save_report_no_tmp_files_left(self, tmp_path):
        p = _make_promoter()
        p.save_report(self._sample_report(), data_dir=str(tmp_path))
        tmp_files = [f for f in tmp_path.iterdir() if ".tmp" in f.name]
        assert tmp_files == []

    def test_save_report_unicode_preserved(self, tmp_path):
        p = _make_promoter()
        report = self._sample_report()
        report["note"] = "Стратегія ✓"
        p.save_report(report, data_dir=str(tmp_path))
        loaded = json.loads((tmp_path / "promotion_report.json").read_text(encoding="utf-8"))
        assert loaded["note"] == "Стратегія ✓"


# ===========================================================================
# 9. _compute_max_drawdown
# ===========================================================================

class TestComputeMaxDrawdown:
    def test_empty_series_returns_zero(self):
        assert _compute_max_drawdown([]) == 0.0

    def test_single_element_returns_zero(self):
        assert _compute_max_drawdown([100_000.0]) == 0.0

    def test_monotone_increasing_no_drawdown(self):
        series = [100_000.0, 101_000.0, 102_000.0, 103_000.0]
        assert _compute_max_drawdown(series) == 0.0

    def test_known_drawdown(self):
        # Peak 100, drops to 90 → 10% drawdown
        series = [100.0, 100.0, 90.0]
        dd = _compute_max_drawdown(series)
        assert abs(dd - 10.0) < 1e-9

    def test_drawdown_then_recovery(self):
        series = [100.0, 95.0, 105.0]
        dd = _compute_max_drawdown(series)
        # Peak 100, trough 95 → 5%
        assert abs(dd - 5.0) < 1e-9

    def test_multiple_drawdowns_returns_max(self):
        # Peak 110, trough 99 = 10%, later peak 110, trough 88 = 20%
        series = [100.0, 110.0, 99.0, 110.0, 88.0]
        dd = _compute_max_drawdown(series)
        # max drawdown ≈ (110 - 88) / 110 * 100 ≈ 20.0
        assert dd == pytest.approx((110 - 88) / 110 * 100, rel=1e-6)

    def test_two_elements_increasing(self):
        assert _compute_max_drawdown([100.0, 101.0]) == 0.0

    def test_two_elements_decreasing(self):
        dd = _compute_max_drawdown([100.0, 90.0])
        assert abs(dd - 10.0) < 1e-9


# ===========================================================================
# 10. Boundary / exact-threshold values
# ===========================================================================

class TestBoundaryValues:
    def test_paper_days_exactly_30_passes(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(paper_days=30))
        assert r["tier"] == "A"

    def test_paper_days_29_is_tier_c(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(paper_days=29))
        assert r["tier"] == "C"

    def test_sharpe_exactly_1_0_is_tier_a(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(sharpe=1.0))
        assert r["tier"] == "A"

    def test_sharpe_exactly_0_8_is_tier_b(self):
        r = _make_promoter().evaluate_strategy(
            "s2_test", _tier_b_metrics(sharpe=0.8, max_drawdown_pct=6.0)
        )
        assert r["tier"] == "B"

    def test_apy_ratio_exactly_1_10_is_tier_a(self):
        r = _make_promoter().evaluate_strategy(
            "s1_test", _tier_a_metrics(realized_apy=11.0, target_apy=10.0)
        )
        assert r["tier"] == "A"

    def test_apy_ratio_exactly_0_90_is_tier_b(self):
        r = _make_promoter().evaluate_strategy(
            "s2_test", _tier_b_metrics(realized_apy=9.0, target_apy=10.0, max_drawdown_pct=6.0)
        )
        assert r["tier"] == "B"

    def test_drawdown_exactly_5_0_fails_tier_a(self):
        """drawdown == 5.0 is NOT < 5.0 → Tier A criterion fails."""
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(max_drawdown_pct=5.0))
        # Still passes Tier B (< 8.0) and all Tier C gates
        assert r["tier"] == "B"

    def test_drawdown_just_below_5_0_passes_tier_a(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(max_drawdown_pct=4.999))
        assert r["tier"] == "A"

    def test_drawdown_exactly_8_0_is_tier_c(self):
        r = _make_promoter().evaluate_strategy("s1_test", _tier_a_metrics(max_drawdown_pct=8.0))
        assert r["tier"] == "C"

    def test_capital_at_risk_exactly_threshold_passes(self):
        """capital_at_risk == 50_000 is NOT > 50_000 → not a Tier C gate."""
        r = _make_promoter().evaluate_strategy(
            "s1_test",
            _tier_a_metrics(capital_at_risk=CAPITAL_AT_RISK_THRESHOLD_USD)
        )
        # Should still be Tier A (all other criteria pass)
        assert r["tier"] == "A"

    def test_capital_at_risk_one_above_threshold_is_tier_c(self):
        r = _make_promoter().evaluate_strategy(
            "s1_test",
            _tier_a_metrics(capital_at_risk=CAPITAL_AT_RISK_THRESHOLD_USD + 0.01)
        )
        assert r["tier"] == "C"

    def test_t3_spec_strategies_set_is_nonempty(self):
        assert len(T3_SPEC_STRATEGIES) > 0

    def test_t3_spec_strategies_contains_known_ids(self):
        assert "s11_hybrid" in T3_SPEC_STRATEGIES
        assert "s4_pendle_lp" in T3_SPEC_STRATEGIES


# ===========================================================================
# 11. None / missing metrics graceful handling
# ===========================================================================

class TestNoneMetrics:
    def test_none_sharpe_treated_as_zero(self):
        r = _make_promoter().evaluate_strategy("s1_test", {"sharpe": None, "tier_label": "T1"})
        assert r["tier"] == "C"

    def test_none_paper_days_treated_as_zero(self):
        r = _make_promoter().evaluate_strategy(
            "s1_test", _tier_a_metrics(paper_days=None)
        )
        assert r["tier"] == "C"

    def test_missing_metrics_keys_default_to_safe_values(self):
        """Completely empty metrics should not raise — defaults apply."""
        r = _make_promoter().evaluate_strategy("s1_test", {})
        # No crash; result should be Tier C (all defaults are 0/empty)
        assert r["tier"] == "C"
        assert r["action"] == "MANUAL_REVIEW"

    def test_none_halt_count_treated_as_zero(self):
        """halt_count=None → 0, should not block if other criteria pass."""
        metrics = _tier_a_metrics(halt_count=None)
        r = _make_promoter().evaluate_strategy("s1_test", metrics)
        # halt defaults to 0, so should be Tier A
        assert r["tier"] == "A"
