"""Tests for AdvisoryConfig (read-only optimizer-vs-policy comparison).

15 tests covering: structure of get_comparison(), current-policy sourcing from
RiskConfig, optimal sourcing from optimized_params.json, safe_to_apply logic
(loosening → False, tightening/within-bounds → True), APY-improvement estimation,
and graceful degradation when the optimizer file is missing/corrupt.

The module under test is strictly read-only — these tests also assert it never
writes to disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.allocator.advisory_config import AdvisoryConfig
from spa_core.risk.policy import RiskConfig


# ── fixtures ──────────────────────────────────────────────────────────────────

def _write_params(path: Path, best: dict, expected_apy: float, all_results=None):
    payload = {
        "best_params": best,
        "best_detail": {"params": best, "expected_apy_pct": expected_apy},
    }
    if all_results is not None:
        payload["all_results"] = all_results
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def optimal_params() -> dict:
    return {
        "t1_cap": 0.30,
        "t2_cap": 0.25,
        "cash_buffer": 0.03,
        "rebalance_threshold": 0.05,
    }


@pytest.fixture
def params_file(tmp_path, optimal_params) -> Path:
    # all_results includes a row matching the current live caps (0.40/0.20/0.05)
    # so APY-improvement estimation has a baseline to subtract.
    all_results = [
        {"params": optimal_params, "expected_apy_pct": 8.65},
        {
            "params": {
                "t1_cap": 0.40,
                "t2_cap": 0.20,
                "cash_buffer": 0.05,
                "rebalance_threshold": 0.05,
            },
            "expected_apy_pct": 8.15,
        },
    ]
    return _write_params(tmp_path / "optimized_params.json", optimal_params, 8.65, all_results)


@pytest.fixture
def advisory(params_file) -> AdvisoryConfig:
    return AdvisoryConfig(optimized_params_path=params_file)


# ── 1. structure ──────────────────────────────────────────────────────────────

def test_get_comparison_returns_dict(advisory):
    assert isinstance(advisory.get_comparison(), dict)


def test_comparison_has_required_keys(advisory):
    cmp = advisory.get_comparison()
    for key in (
        "current",
        "optimal",
        "change_required",
        "estimated_apy_improvement",
        "safe_to_apply",
    ):
        assert key in cmp, f"missing key: {key}"


def test_mode_is_advisory(advisory):
    assert advisory.get_comparison()["mode"] == "ADVISORY"


# ── 2. current policy sourced from RiskConfig ─────────────────────────────────

def test_current_reads_riskconfig_caps(advisory):
    cfg = RiskConfig()
    cur = advisory.get_comparison()["current"]
    assert cur["t1_cap"] == cfg.max_concentration_t1
    assert cur["t2_cap"] == cfg.max_concentration_t2
    assert cur["cash_buffer"] == cfg.min_cash_pct


def test_current_includes_policy_version(advisory):
    assert advisory.get_comparison()["current"]["policy_version"] == RiskConfig().version


# ── 3. optimal sourced from optimized_params.json ─────────────────────────────

def test_optimal_matches_file(advisory, optimal_params):
    assert advisory.get_comparison()["optimal"] == optimal_params


def test_optimizer_expected_apy_surfaced(advisory):
    assert advisory.get_comparison()["optimizer_expected_apy_pct"] == 8.65


# ── 4. safe_to_apply logic ────────────────────────────────────────────────────

def test_safe_to_apply_false_when_loosening(advisory):
    # optimal t2_cap=0.25 > 0.20 and cash_buffer=0.03 < 0.05 → loosening → unsafe
    assert advisory.get_comparison()["safe_to_apply"] is False


def test_safe_to_apply_reasons_present_when_unsafe(advisory):
    reasons = advisory.get_comparison()["safe_to_apply_reasons"]
    assert isinstance(reasons, list) and len(reasons) >= 2  # t2_cap + cash_buffer


def test_safe_to_apply_true_when_within_bounds(tmp_path):
    # All recommended values are within / tighter than the live policy.
    safe_params = {
        "t1_cap": 0.30,   # tighter than 0.40
        "t2_cap": 0.20,   # equal to live cap
        "cash_buffer": 0.06,  # MORE conservative than 0.05
        "rebalance_threshold": 0.05,
    }
    pf = _write_params(tmp_path / "p.json", safe_params, 8.0)
    adv = AdvisoryConfig(optimized_params_path=pf)
    cmp = adv.get_comparison()
    assert cmp["safe_to_apply"] is True
    assert cmp["safe_to_apply_reasons"] == []


def test_safe_false_when_only_cash_lowered(tmp_path):
    params = {"t1_cap": 0.30, "t2_cap": 0.20, "cash_buffer": 0.03}
    pf = _write_params(tmp_path / "p.json", params, 8.0)
    cmp = AdvisoryConfig(optimized_params_path=pf).get_comparison()
    assert cmp["safe_to_apply"] is False
    assert any("cash_buffer" in r for r in cmp["safe_to_apply_reasons"])


def test_safe_false_when_only_t2_raised(tmp_path):
    params = {"t1_cap": 0.30, "t2_cap": 0.25, "cash_buffer": 0.05}
    pf = _write_params(tmp_path / "p.json", params, 8.0)
    cmp = AdvisoryConfig(optimized_params_path=pf).get_comparison()
    assert cmp["safe_to_apply"] is False
    assert any("t2_cap" in r for r in cmp["safe_to_apply_reasons"])


# ── 5. APY improvement estimate ───────────────────────────────────────────────

def test_estimated_apy_improvement_string(advisory):
    # 8.65 (optimal) − 8.15 (current caps row) = +0.50%
    s = advisory.get_comparison()["estimated_apy_improvement"]
    assert "+0.50%" in s


# ── 6. graceful degradation ───────────────────────────────────────────────────

def test_missing_file_degrades_gracefully(tmp_path):
    adv = AdvisoryConfig(optimized_params_path=tmp_path / "does_not_exist.json")
    cmp = adv.get_comparison()
    assert cmp["optimizer_loaded"] is False
    assert cmp["optimal"] == {}
    assert cmp["safe_to_apply"] is False  # nothing to apply


def test_corrupt_file_degrades_gracefully(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    cmp = AdvisoryConfig(optimized_params_path=bad).get_comparison()
    assert cmp["optimizer_loaded"] is False
    assert cmp["optimal"] == {}


def test_module_does_not_write_to_disk(tmp_path, params_file):
    before = {p.name for p in tmp_path.iterdir()}
    AdvisoryConfig(optimized_params_path=params_file).get_comparison()
    after = {p.name for p in tmp_path.iterdir()}
    assert before == after  # read-only: no new files created
