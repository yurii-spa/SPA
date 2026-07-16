"""Regression tests for spa_core/monitoring/data_freshness_monitor.py.

`DataFreshnessMonitor` is the site/monitoring stale-data self-detector: it walks
a registry of data files, compares each file's mtime against a per-type
threshold, and classifies FRESH / STALE / MISSING. If its boundary logic is
wrong, a silently-stale feed goes unreported — so these tests lock the exact
contract of the classifier.

Fully hermetic: the constructor injects `clock`, `thresholds`, and `file_map`,
and every file lives under a pytest `tmp_path`. No production data file (and in
particular NOT the live go-live track) is touched. Tests only — the module is
never modified (invariant #16).
"""
from __future__ import annotations

import os

import pytest

from spa_core.monitoring.data_freshness_monitor import (
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_STALE,
    DataFreshnessMonitor,
)

# A fixed "now" so age math is fully deterministic (well clear of epoch).
_NOW = 1_700_000_000.0


def _write_at(path, age_sec, now=_NOW):
    """Create `path` with an mtime `age_sec` seconds before `now`.

    Returns the *actual* mtime the filesystem recorded, so callers that need an
    exact age (boundary tests) can pin `now` to `mtime + threshold` and be
    immune to sub-second mtime-resolution rounding.
    """
    path.write_text("{}", encoding="utf-8")
    target = now - age_sec
    os.utime(path, (target, target))
    return os.path.getmtime(str(path))


def _monitor(tmp_path, thresholds, *, now=_NOW, file_map=None):
    if file_map is None:
        file_map = {dt: f"{dt}.json" for dt in thresholds}
    return DataFreshnessMonitor(
        base_dir=str(tmp_path),
        thresholds=thresholds,
        file_map=file_map,
        clock=lambda: now,
    )


# ---------------------------------------------------------------------------
# FRESH / STALE core classification
# ---------------------------------------------------------------------------

def test_fresh_file_classified_fresh(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    result = mon.check_all()

    assert result["checks"]["apy_data"]["status"] == STATUS_FRESH
    assert result["fresh_files"] == ["apy_data"]
    assert result["stale_files"] == []
    assert result["missing_files"] == []
    assert mon.is_fresh("apy_data") is True


def test_stale_file_classified_stale(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10_000)  # > 3600s
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    result = mon.check_all()

    check = result["checks"]["apy_data"]
    assert check["status"] == STATUS_STALE
    assert check["age_sec"] == pytest.approx(10_000, abs=1.0)
    assert result["stale_files"] == ["apy_data"]
    assert mon.is_fresh("apy_data") is False
    assert mon.stale_count() == 1


# ---------------------------------------------------------------------------
# The STALE/FRESH boundary — the code uses a STRICT `age_sec > max_age_sec`,
# so age exactly at the threshold must still be FRESH; one second over is STALE.
# This off-by-one is the single most likely place staleness gets mis-reported.
# ---------------------------------------------------------------------------

def test_boundary_exactly_at_threshold_is_fresh(tmp_path):
    threshold = 3_600
    mtime = _write_at(tmp_path / "apy_data.json", age_sec=threshold)
    # Pin now so age is EXACTLY the threshold, regardless of fs mtime rounding.
    mon = _monitor(tmp_path, {"apy_data": threshold}, now=mtime + threshold)
    result = mon.check_all()

    assert result["checks"]["apy_data"]["age_sec"] == pytest.approx(threshold, abs=1e-6)
    assert result["checks"]["apy_data"]["status"] == STATUS_FRESH
    assert mon.is_fresh("apy_data") is True


def test_boundary_one_second_over_threshold_is_stale(tmp_path):
    threshold = 3_600
    mtime = _write_at(tmp_path / "apy_data.json", age_sec=threshold)
    # now = mtime + threshold + 1  →  age = threshold + 1  →  strictly greater.
    mon = _monitor(tmp_path, {"apy_data": threshold}, now=mtime + threshold + 1)
    result = mon.check_all()

    assert result["checks"]["apy_data"]["status"] == STATUS_STALE


# ---------------------------------------------------------------------------
# MISSING has two distinct paths, both must yield MISSING:
#   (a) a mapped file that simply doesn't exist on disk, and
#   (b) an unknown data_type whose _resolve_path returns None.
# ---------------------------------------------------------------------------

def test_mapped_file_absent_is_missing(tmp_path):
    # No file written for apy_data.
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    result = mon.check_all()

    check = result["checks"]["apy_data"]
    assert check["status"] == STATUS_MISSING
    assert check["age_sec"] is None
    assert result["missing_files"] == ["apy_data"]
    assert mon.is_fresh("apy_data") is False
    assert mon.missing_count() == 1


def test_unknown_data_type_resolves_to_missing(tmp_path):
    # threshold registers a type that is NOT in file_map → _resolve_path → None.
    mon = DataFreshnessMonitor(
        base_dir=str(tmp_path),
        thresholds={"ghost": 3_600},
        file_map={},  # deliberately empty
        clock=lambda: _NOW,
    )
    result = mon.check_all()

    check = result["checks"]["ghost"]
    assert check["status"] == STATUS_MISSING
    assert check["path"] is None
    assert result["missing_files"] == ["ghost"]


# ---------------------------------------------------------------------------
# is_fresh() tri-state contract: None (unknown) vs False (stale/missing) vs True.
# ---------------------------------------------------------------------------

def test_is_fresh_unknown_type_returns_none(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    mon.check_all()

    assert mon.is_fresh("apy_data") is True
    # A type never checked is genuinely unknown → None, NOT False.
    assert mon.is_fresh("never_registered") is None


def test_is_fresh_before_check_all_is_none(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    # No check_all() yet → checks dict empty → tri-state None, not a false True.
    assert mon.is_fresh("apy_data") is None


# ---------------------------------------------------------------------------
# Multi-file run: the three lists partition the registry, summary counts stay
# consistent with the lists, and every registered type lands in exactly one.
# ---------------------------------------------------------------------------

def test_summary_and_lists_consistent_across_mixed_states(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)          # FRESH
    _write_at(tmp_path / "portfolio_nav.json", age_sec=500_000)  # STALE (>1d)
    # gate_status file absent → MISSING
    thresholds = {
        "apy_data": 3_600,
        "portfolio_nav": 86_400,
        "gate_status": 604_800,
    }
    mon = _monitor(tmp_path, thresholds)
    result = mon.check_all()

    assert result["fresh_files"] == ["apy_data"]
    assert result["stale_files"] == ["portfolio_nav"]
    assert result["missing_files"] == ["gate_status"]

    summary = result["summary"]
    assert summary["total"] == 3
    assert summary["fresh"] == 1
    assert summary["stale"] == 1
    assert summary["missing"] == 1
    # Counts must equal the list lengths (no double-count / drop).
    assert summary["fresh"] == len(result["fresh_files"])
    assert summary["stale"] == len(result["stale_files"])
    assert summary["missing"] == len(result["missing_files"])
    # Partition: every registered type in exactly one bucket.
    buckets = result["fresh_files"] + result["stale_files"] + result["missing_files"]
    assert sorted(buckets) == sorted(thresholds)

    assert mon.stale_count() == 1
    assert mon.missing_count() == 1


def test_check_result_carries_threshold_metadata(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    check = mon.check_all()["checks"]["apy_data"]

    assert check["threshold_sec"] == 3_600
    # apy_data has a canonical human label in the module's _THRESHOLD_LABELS.
    assert check["threshold_label"] == "1 hour"
    assert check["path"] == os.path.join(str(tmp_path), "apy_data.json")


def test_threshold_label_falls_back_for_unmapped_type(tmp_path):
    # A type NOT present in the module's _THRESHOLD_LABELS map must fall back
    # to the "<n>s" form rather than raising a KeyError.
    _write_at(tmp_path / "custom_feed.json", age_sec=10)
    mon = _monitor(tmp_path, {"custom_feed": 900})
    check = mon.check_all()["checks"]["custom_feed"]

    assert check["threshold_label"] == "900s"


def test_last_run_and_to_dict_populated(tmp_path):
    _write_at(tmp_path / "apy_data.json", age_sec=10)
    mon = _monitor(tmp_path, {"apy_data": 3_600})
    result = mon.check_all()

    assert result["last_run"] is not None
    # to_dict() reflects the last run verbatim.
    assert mon.to_dict() is result or mon.to_dict() == result
