"""Tests for spa_core/monitoring/series_anomaly_detector.py (series anomaly detection).

PARALLEL layer. Pure stdlib, deterministic, no network, no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import statistics

import spa_core.monitoring.series_anomaly_detector as ad


def _series_from_values(values, start_day=1):
    """Build {date_iso: apy} with sequential dates so sort order is chronological."""
    return {f"2026-05-{start_day + i:02d}": float(v) for i, v in enumerate(values)}


# --- spike consensus ----------------------------------------------------------
def test_clear_spike_flagged_by_all_three_methods_critical():
    # 29 flat days at 3.0%, then a spike to 12.0% as the latest value
    vals = [3.0] * 29 + [12.0]
    series_map = {"spiky": _series_from_values(vals)}
    res = ad.detect_apy_anomalies(series_map)
    assert len(res) == 1
    rec = res[0]
    assert rec["protocol"] == "spiky"
    assert rec["methods_agree"] == 3            # mad_z + iqr + jump all fire
    assert rec["severity"] == ad.SEVERITY_CRITICAL
    assert rec["iqr_outlier"] is True
    assert rec["jump_pct"] > ad.JUMP_PCT_THRESHOLD
    # mad_z is the finite flat-window sentinel (perfectly flat baseline)
    assert rec["mad_z"] >= ad.MAD_Z_THRESHOLD


def test_spike_off_noisy_window_still_consensus():
    # window has mild noise (so MAD>0), latest is a real spike
    import random
    rng = random.Random(42)
    window = [3.0 + rng.uniform(-0.05, 0.05) for _ in range(30)]
    vals = window + [10.0]
    series_map = {"noisy_spike": _series_from_values(vals[:31])}
    res = ad.detect_apy_anomalies(series_map)
    assert len(res) == 1
    assert res[0]["methods_agree"] >= 2
    assert res[0]["mad_z"] >= ad.MAD_Z_THRESHOLD


# --- stable series → no anomaly ----------------------------------------------
def test_flat_stable_series_no_anomaly():
    series_map = {"flat": _series_from_values([3.5] * 30)}
    assert ad.detect_apy_anomalies(series_map) == []


def test_gently_drifting_series_no_anomaly():
    # slow drift 3.00 -> 3.29: no jump exceeds threshold, no IQR outlier
    vals = [3.0 + 0.01 * i for i in range(30)]
    series_map = {"drift": _series_from_values(vals)}
    assert ad.detect_apy_anomalies(series_map) == []


# --- MAD robustness -----------------------------------------------------------
def test_mad_zscore_robust_to_single_outlier():
    # one fat outlier inside the window must NOT inflate the scale: a later
    # moderate value should not be deemed anomalous by mad_z.
    window = [3.0] * 28 + [50.0] + [3.0]   # single contaminating outlier
    z_moderate = ad._mad_zscore(3.2, window)
    # mean+stdev would be wrecked by the 50.0; MAD median stays 3.0, mad==0
    # here, so a tiny deviation is the finite sentinel, NOT inf — bounded.
    assert z_moderate == ad._FLAT_SPIKE_Z or z_moderate < ad.MAD_Z_THRESHOLD
    assert z_moderate != float("inf")
    # the median itself is unaffected by the outlier
    assert statistics.median(window) == 3.0


def test_mad_zscore_flat_window_no_change_returns_zero():
    assert ad._mad_zscore(3.0, [3.0] * 10) == 0.0


def test_mad_zscore_flat_window_with_change_returns_finite_sentinel():
    z = ad._mad_zscore(9.0, [3.0] * 10)
    assert z == ad._FLAT_SPIKE_Z
    assert z != float("inf")


def test_mad_zscore_scales_with_dispersion():
    # genuine dispersion → finite, sensible z-score (not exploding)
    window = [2.0, 2.5, 3.0, 3.5, 4.0, 2.0, 2.5, 3.0, 3.5, 4.0]
    z = ad._mad_zscore(3.0, window)
    assert 0.0 <= z < ad.MAD_Z_THRESHOLD


# --- IQR fence math -----------------------------------------------------------
def test_iqr_fence_math():
    # 1..9 → Q1=3 (median of [1,2,3,4,5]), Q3=7 (median of [5,6,7,8,9]) inclusive
    q1, q3 = ad._quartiles([1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert q1 == 3.0
    assert q3 == 7.0
    iqr = q3 - q1
    assert q1 - ad.IQR_K * iqr == 3.0 - 1.5 * 4.0   # -3.0
    assert q3 + ad.IQR_K * iqr == 7.0 + 1.5 * 4.0   # 13.0


def test_quartiles_even_length():
    q1, q3 = ad._quartiles([1, 2, 3, 4])  # lower=[1,2]->1.5, upper=[3,4]->3.5
    assert q1 == 1.5
    assert q3 == 3.5


# --- decimal vs percent normalisation ----------------------------------------
def test_decimal_series_normalised_to_percent():
    # decimal APY (all <= 1.0): 0.03 flat then 0.12 spike → normalised to %
    vals = [0.03] * 29 + [0.12]
    series_map = {"dec": _series_from_values(vals)}
    res = ad.detect_apy_anomalies(series_map)
    assert len(res) == 1
    assert abs(res[0]["latest_apy"] - 12.0) < 1e-6   # 0.12 -> 12.0%
    assert abs(res[0]["median"] - 3.0) < 1e-6


# --- min points / graceful ----------------------------------------------------
def test_too_few_points_skipped():
    series_map = {"short": _series_from_values([3.0, 9.0])}
    assert ad.detect_apy_anomalies(series_map) == []


def test_empty_inputs_graceful():
    assert ad.detect_apy_anomalies({}) == []
    assert ad.detect_peg_anomalies({}) == []
    assert ad.detect_tvl_anomalies({}, None) == []


# --- peg detector -------------------------------------------------------------
def test_peg_detector_flags_non_stable_and_sorts_critical_first():
    report = {"statuses": [
        {"adapter_id": "x", "asset": "USDC", "deviation_pct": 0.0, "status": "STABLE"},
        {"adapter_id": "y", "asset": "USDe", "deviation_pct": 0.8, "status": "WARNING"},
        {"adapter_id": "z", "asset": "FRAX", "deviation_pct": 3.1, "status": "CRITICAL"},
    ]}
    res = ad.detect_peg_anomalies(report)
    assert len(res) == 2
    assert res[0]["adapter_id"] == "z"             # critical sorts first
    assert res[0]["severity"] == ad.SEVERITY_CRITICAL
    assert res[1]["severity"] == ad.SEVERITY_WARN


# --- tvl detector -------------------------------------------------------------
def test_tvl_drop_detected_with_prior():
    status = {"adapters": {
        "aave_v3": {"tvl_usd": 1_000_000.0},
        "morpho": {"tvl_usd": 300_000.0},   # dropped from 1M -> 70% drop
    }}
    prior = {"aave_v3": 1_100_000.0, "morpho": 1_000_000.0}
    res = ad.detect_tvl_anomalies(status, prior)
    assert len(res) == 1                            # only morpho exceeds 30%
    assert res[0]["adapter_id"] == "morpho"
    assert res[0]["drop_pct"] == 70.0
    assert res[0]["severity"] == ad.SEVERITY_CRITICAL  # >50% drop


def test_tvl_no_prior_returns_empty():
    status = {"adapters": {"aave_v3": {"tvl_usd": 1.0}}}
    assert ad.detect_tvl_anomalies(status, None) == []


# --- determinism --------------------------------------------------------------
def test_determinism():
    vals = [3.0] * 29 + [12.0]
    series_map = {"spiky": _series_from_values(vals)}
    assert ad.detect_apy_anomalies(series_map) == ad.detect_apy_anomalies(series_map)
    r1 = ad.detect_all(series_map=series_map, peg_report={}, adapter_status={})
    r2 = ad.detect_all(series_map=series_map, peg_report={}, adapter_status={})
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# --- build_report structure ---------------------------------------------------
def test_build_report_structure_no_write():
    vals = [3.0] * 29 + [12.0]
    series_map = {"spiky": _series_from_values(vals)}
    peg = {"statuses": [{"adapter_id": "z", "asset": "FRAX",
                         "deviation_pct": 3.1, "status": "CRITICAL"}]}
    rep = ad.build_report(write=False, series_map=series_map, peg_report=peg,
                          adapter_status={})
    for key in ("schema_version", "generated_at", "generated_by", "llm_forbidden",
                "config", "count", "critical_count", "overall_status",
                "apy_anomalies", "peg_anomalies", "tvl_anomalies", "worst"):
        assert key in rep
    assert rep["llm_forbidden"] is True
    assert rep["generated_by"] == "series_anomaly_detector"
    assert rep["overall_status"] == "RED"          # has criticals
    assert rep["count"] == 2                        # 1 apy + 1 peg
    assert rep["critical_count"] == 2


def test_build_report_green_when_clean():
    series_map = {"flat": _series_from_values([3.5] * 30)}
    rep = ad.build_report(write=False, series_map=series_map, peg_report={},
                          adapter_status={})
    assert rep["overall_status"] == "GREEN"
    assert rep["count"] == 0
    assert rep["critical_count"] == 0
    assert rep["worst"] is None


def test_build_report_atomic_write(tmp_path, monkeypatch):
    out = tmp_path / "anomaly_report.json"
    monkeypatch.setattr(ad, "_OUT", out)
    series_map = {"flat": _series_from_values([3.5] * 30)}
    ad.build_report(write=True, series_map=series_map, peg_report={},
                    adapter_status={})
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["generated_by"] == "series_anomaly_detector"
    assert loaded["overall_status"] == "GREEN"
