"""
Comprehensive pytest suite for spa_core.paper_trading.position_tracker.PositionTracker.

Coverage targets
================
- record_position: basic creation, append, idempotency, apy_map, field values
- get_history: empty / single / multi
- get_current_weights: empty / single / multi-day returns latest
- compute_drift: no drift, overweight, underweight, asymmetric key sets
- get_concentration_metric: single, equal weights, two adapters, HHI math
- ring-buffer cap (> 365 entries)
- _load_history: missing file, corrupt JSON, wrong type
- _atomic_write: file created, content correct, idempotent re-read
- _build_snapshot: NaN / negative weight filtering, top_adapter selection
- _concentration_from_weights: empty, single, multi, all-zero
- date_str override
- data_dir isolation (tmp dirs)
- equity edge cases (zero, large, float precision)
- adapter_count field
- apy_weighted absent without apy_map, present with apy_map
- timestamp present in ISO 8601 format
- multiple days accumulate correctly
- error handling: non-dict allocation, NaN equity
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spa_core.paper_trading.position_tracker import (
    HISTORY_FILENAME,
    HISTORY_MAX,
    PositionTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tracker() -> PositionTracker:
    return PositionTracker()


def tmp_dir() -> str:
    """Return path to a fresh temporary directory (caller must clean up)."""
    d = tempfile.mkdtemp()
    return d


def history_path(data_dir: str) -> Path:
    return Path(data_dir) / HISTORY_FILENAME


def write_history(data_dir: str, records: list) -> None:
    p = history_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. record_position — file creation
# ---------------------------------------------------------------------------

class TestRecordCreatesFile:
    def test_record_creates_file(self, tmp_path):
        t = make_tracker()
        t.record_position({"aave_v3": 1.0}, 100_000.0, data_dir=str(tmp_path))
        assert history_path(str(tmp_path)).exists()

    def test_record_returns_dict(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"aave_v3": 1.0}, 50_000.0, data_dir=str(tmp_path))
        assert isinstance(snap, dict)

    def test_record_date_field_today(self, tmp_path):
        from datetime import datetime, timezone
        t = make_tracker()
        snap = t.record_position({"aave_v3": 1.0}, 100.0, data_dir=str(tmp_path))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert snap["date"] == today

    def test_record_date_str_override(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"aave_v3": 1.0}, 100.0,
                                  date_str="2026-01-15", data_dir=str(tmp_path))
        assert snap["date"] == "2026-01-15"

    def test_record_equity_stored(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"aave_v3": 1.0}, 123_456.78, data_dir=str(tmp_path))
        assert abs(snap["equity"] - 123_456.78) < 0.01

    def test_record_allocation_stored(self, tmp_path):
        alloc = {"aave_v3": 0.4, "compound_v3": 0.6}
        t = make_tracker()
        snap = t.record_position(alloc, 100_000.0, data_dir=str(tmp_path))
        assert snap["allocation"]["aave_v3"] == pytest.approx(0.4)
        assert snap["allocation"]["compound_v3"] == pytest.approx(0.6)

    def test_record_timestamp_iso(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"aave_v3": 1.0}, 100.0, data_dir=str(tmp_path))
        ts = snap["timestamp"]
        assert "T" in ts, "timestamp should be ISO 8601"

    def test_record_adapter_count(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 0.5, "b": 0.3, "c": 0.2}, 100.0,
                                  data_dir=str(tmp_path))
        assert snap["adapter_count"] == 3

    def test_record_top_adapter(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 0.1, "b": 0.7, "c": 0.2}, 100.0,
                                  data_dir=str(tmp_path))
        assert snap["top_adapter"] == "b"

    def test_record_no_apy_weighted_without_map(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 100.0, data_dir=str(tmp_path))
        assert "apy_weighted" not in snap


# ---------------------------------------------------------------------------
# 2. record_position — append behaviour
# ---------------------------------------------------------------------------

class TestRecordAppendsEntry:
    def test_second_day_appends(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        t.record_position({"a": 1.0}, 101.0, date_str="2026-01-02",
                          data_dir=str(tmp_path))
        history = t.get_history(str(tmp_path))
        assert len(history) == 2

    def test_entries_ordered_by_insertion(self, tmp_path):
        t = make_tracker()
        for i in range(1, 6):
            t.record_position({"a": 1.0}, float(i), date_str=f"2026-01-0{i}",
                              data_dir=str(tmp_path))
        history = t.get_history(str(tmp_path))
        dates = [h["date"] for h in history]
        assert dates == sorted(dates)

    def test_five_days_accumulate(self, tmp_path):
        t = make_tracker()
        for i in range(1, 6):
            t.record_position({"a": 1.0}, float(i * 1000),
                              date_str=f"2026-02-0{i}", data_dir=str(tmp_path))
        assert len(t.get_history(str(tmp_path))) == 5


# ---------------------------------------------------------------------------
# 3. record_position — idempotency
# ---------------------------------------------------------------------------

class TestRecordIdempotentSameDay:
    def test_same_date_not_duplicated(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-06-01",
                          data_dir=str(tmp_path))
        t.record_position({"b": 1.0}, 999.0, date_str="2026-06-01",
                          data_dir=str(tmp_path))
        history = t.get_history(str(tmp_path))
        assert len(history) == 1

    def test_same_date_returns_existing(self, tmp_path):
        t = make_tracker()
        snap1 = t.record_position({"a": 1.0}, 100.0, date_str="2026-06-01",
                                   data_dir=str(tmp_path))
        snap2 = t.record_position({"b": 1.0}, 999.0, date_str="2026-06-01",
                                   data_dir=str(tmp_path))
        assert snap1["equity"] == snap2["equity"]
        assert snap1["allocation"] == snap2["allocation"]

    def test_three_calls_same_date_single_record(self, tmp_path):
        t = make_tracker()
        for _ in range(3):
            t.record_position({"a": 1.0}, 100.0, date_str="2026-03-15",
                              data_dir=str(tmp_path))
        assert len(t.get_history(str(tmp_path))) == 1


# ---------------------------------------------------------------------------
# 4. record_position — apy_map → weighted APY
# ---------------------------------------------------------------------------

class TestRecordWithApyMapComputesWeighted:
    def test_apy_weighted_present(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 100.0, apy_map={"a": 5.0},
                                  data_dir=str(tmp_path))
        assert "apy_weighted" in snap

    def test_apy_weighted_single_adapter(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 100.0, apy_map={"a": 6.5},
                                  data_dir=str(tmp_path))
        assert snap["apy_weighted"] == pytest.approx(6.5)

    def test_apy_weighted_two_equal_weights(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 0.5, "b": 0.5}, 100.0,
                                  apy_map={"a": 4.0, "b": 8.0},
                                  data_dir=str(tmp_path))
        assert snap["apy_weighted"] == pytest.approx(6.0)

    def test_apy_weighted_asymmetric_weights(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 0.25, "b": 0.75}, 100.0,
                                  apy_map={"a": 4.0, "b": 8.0},
                                  data_dir=str(tmp_path))
        # 0.25/(0.25+0.75)*4 + 0.75/(0.25+0.75)*8 = 1 + 6 = 7.0
        assert snap["apy_weighted"] == pytest.approx(7.0)

    def test_apy_missing_adapter_ignored(self, tmp_path):
        """apy_map with fewer keys than allocation — missing treated as 0."""
        t = make_tracker()
        snap = t.record_position({"a": 0.5, "b": 0.5}, 100.0,
                                  apy_map={"a": 10.0},
                                  data_dir=str(tmp_path))
        # only "a" contributes: 0.5/1.0 * 10.0 = 5.0
        assert snap["apy_weighted"] == pytest.approx(5.0)

    def test_apy_zero_total_weight_returns_zero(self, tmp_path):
        """Edge: allocation is empty dict → apy_weighted = 0."""
        t = make_tracker()
        snap = t.record_position({}, 100.0, apy_map={"a": 5.0},
                                  data_dir=str(tmp_path))
        assert snap.get("apy_weighted", 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5. get_history
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_get_history_empty_no_file(self, tmp_path):
        t = make_tracker()
        assert t.get_history(str(tmp_path)) == []

    def test_get_history_returns_list(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        assert isinstance(t.get_history(str(tmp_path)), list)

    def test_get_history_length(self, tmp_path):
        t = make_tracker()
        for i in range(1, 4):
            t.record_position({"a": 1.0}, float(i), date_str=f"2026-05-0{i}",
                              data_dir=str(tmp_path))
        assert len(t.get_history(str(tmp_path))) == 3

    def test_get_history_corrupt_file_returns_empty(self, tmp_path):
        history_path(str(tmp_path)).write_text("NOT_JSON", encoding="utf-8")
        t = make_tracker()
        assert t.get_history(str(tmp_path)) == []

    def test_get_history_wrong_type_returns_empty(self, tmp_path):
        history_path(str(tmp_path)).write_text('{"key": "value"}', encoding="utf-8")
        t = make_tracker()
        assert t.get_history(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# 6. get_current_weights
# ---------------------------------------------------------------------------

class TestGetCurrentWeights:
    def test_empty_history_returns_empty_dict(self, tmp_path):
        t = make_tracker()
        assert t.get_current_weights(str(tmp_path)) == {}

    def test_single_entry_returned(self, tmp_path):
        t = make_tracker()
        alloc = {"aave_v3": 0.6, "morpho_blue": 0.4}
        t.record_position(alloc, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        cw = t.get_current_weights(str(tmp_path))
        assert cw["aave_v3"] == pytest.approx(0.6)

    def test_returns_latest_not_first(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        t.record_position({"b": 1.0}, 200.0, date_str="2026-01-02",
                          data_dir=str(tmp_path))
        cw = t.get_current_weights(str(tmp_path))
        assert "b" in cw
        assert "a" not in cw

    def test_returns_copy_not_reference(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.5, "b": 0.5}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        cw1 = t.get_current_weights(str(tmp_path))
        cw1["a"] = 9999.0  # mutate
        cw2 = t.get_current_weights(str(tmp_path))
        assert cw2["a"] == pytest.approx(0.5)  # original unchanged


# ---------------------------------------------------------------------------
# 7. compute_drift
# ---------------------------------------------------------------------------

class TestComputeDrift:
    def test_no_drift_when_equal(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.5, "b": 0.5}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 0.5, "b": 0.5}, data_dir=str(tmp_path))
        assert drift["a"] == pytest.approx(0.0)
        assert drift["b"] == pytest.approx(0.0)

    def test_overweight_positive_drift(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.7, "b": 0.3}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 0.5, "b": 0.5}, data_dir=str(tmp_path))
        assert drift["a"] == pytest.approx(20.0)  # (0.7 - 0.5) * 100

    def test_underweight_negative_drift(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.3, "b": 0.7}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 0.5, "b": 0.5}, data_dir=str(tmp_path))
        assert drift["a"] == pytest.approx(-20.0)

    def test_drift_adapter_only_in_current(self, tmp_path):
        """Current has adapter "x" not in target → drift = x_weight * 100."""
        t = make_tracker()
        t.record_position({"a": 0.8, "x": 0.2}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 1.0}, data_dir=str(tmp_path))
        assert drift["x"] == pytest.approx(20.0)

    def test_drift_adapter_only_in_target(self, tmp_path):
        """Target has adapter "y" not in current → drift = -y_target * 100."""
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 0.7, "y": 0.3}, data_dir=str(tmp_path))
        assert drift["y"] == pytest.approx(-30.0)

    def test_no_history_returns_empty(self, tmp_path):
        t = make_tracker()
        drift = t.compute_drift({"a": 0.5}, data_dir=str(tmp_path))
        assert drift == {}

    def test_all_keys_present_in_drift(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.6, "c": 0.4}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        drift = t.compute_drift({"a": 0.5, "b": 0.5}, data_dir=str(tmp_path))
        assert set(drift.keys()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# 8. get_concentration_metric
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_single_adapter_max_100(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["max_single_pct"] == pytest.approx(100.0)

    def test_single_adapter_hhi_one(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["hhi"] == pytest.approx(1.0)

    def test_single_adapter_top3_100(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["top3_pct"] == pytest.approx(100.0)

    def test_equal_weights_two(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.5, "b": 0.5}, 100.0, date_str="2026-01-01",
                          data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["max_single_pct"] == pytest.approx(50.0)
        assert m["hhi"] == pytest.approx(0.5)

    def test_equal_weights_four(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}, 100.0,
                          date_str="2026-01-01", data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["hhi"] == pytest.approx(0.25)  # 4 * (0.25)^2

    def test_top3_pct_three_adapters(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.4, "b": 0.35, "c": 0.15, "d": 0.10}, 100.0,
                          date_str="2026-01-01", data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        # top 3: 0.4 + 0.35 + 0.15 = 0.90
        assert m["top3_pct"] == pytest.approx(90.0, abs=0.01)

    def test_adapter_count_field(self, tmp_path):
        t = make_tracker()
        t.record_position({"a": 0.5, "b": 0.3, "c": 0.2}, 100.0,
                          date_str="2026-01-01", data_dir=str(tmp_path))
        m = t.get_concentration_metric(str(tmp_path))
        assert m["adapter_count"] == 3

    def test_no_history_returns_zeros(self, tmp_path):
        t = make_tracker()
        m = t.get_concentration_metric(str(tmp_path))
        assert m["max_single_pct"] == 0.0
        assert m["hhi"] == 0.0
        assert m["adapter_count"] == 0

    def test_hhi_known_value(self):
        """Manual HHI: 60/30/10 split → 0.6²+0.3²+0.1² = 0.36+0.09+0.01 = 0.46"""
        result = PositionTracker._concentration_from_weights(
            {"a": 0.6, "b": 0.3, "c": 0.1}
        )
        assert result["hhi"] == pytest.approx(0.46)


# ---------------------------------------------------------------------------
# 9. _load_history (internal, tested directly)
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_missing_file_returns_empty(self, tmp_path):
        t = make_tracker()
        assert t._load_history(history_path(str(tmp_path))) == []

    def test_valid_file_returns_list(self, tmp_path):
        data = [{"date": "2026-01-01", "equity": 100.0}]
        history_path(str(tmp_path)).write_text(json.dumps(data), encoding="utf-8")
        t = make_tracker()
        loaded = t._load_history(history_path(str(tmp_path)))
        assert loaded == data

    def test_corrupt_json_returns_empty(self, tmp_path):
        history_path(str(tmp_path)).write_text("{broken", encoding="utf-8")
        t = make_tracker()
        assert t._load_history(history_path(str(tmp_path))) == []

    def test_json_object_not_list_returns_empty(self, tmp_path):
        history_path(str(tmp_path)).write_text('{"a": 1}', encoding="utf-8")
        t = make_tracker()
        assert t._load_history(history_path(str(tmp_path))) == []

    def test_empty_list_file_returns_empty_list(self, tmp_path):
        history_path(str(tmp_path)).write_text("[]", encoding="utf-8")
        t = make_tracker()
        assert t._load_history(history_path(str(tmp_path))) == []


# ---------------------------------------------------------------------------
# 10. _atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_file_created(self, tmp_path):
        t = make_tracker()
        p = history_path(str(tmp_path))
        t._atomic_write(p, [{"x": 1}])
        assert p.exists()

    def test_content_correct(self, tmp_path):
        t = make_tracker()
        data = [{"date": "2026-01-01", "equity": 42.0}]
        p = history_path(str(tmp_path))
        t._atomic_write(p, data)
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == data

    def test_overwrites_existing(self, tmp_path):
        t = make_tracker()
        p = history_path(str(tmp_path))
        t._atomic_write(p, [{"a": 1}])
        t._atomic_write(p, [{"b": 2}])
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == [{"b": 2}]

    def test_no_tmp_files_left(self, tmp_path):
        t = make_tracker()
        p = history_path(str(tmp_path))
        t._atomic_write(p, [])
        tmp_files = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
        assert tmp_files == []


# ---------------------------------------------------------------------------
# 11. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_history_capped_at_max(self, tmp_path):
        t = make_tracker()
        # Pre-seed with HISTORY_MAX entries
        existing = [
            {"date": f"2024-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}", "equity": float(i),
             "allocation": {"a": 1.0}, "timestamp": "2024-01-01T00:00:00+00:00",
             "top_adapter": "a", "adapter_count": 1}
            for i in range(HISTORY_MAX)
        ]
        write_history(str(tmp_path), existing)
        # Add one more
        t.record_position({"a": 1.0}, 999.0, date_str="2026-12-31",
                          data_dir=str(tmp_path))
        history = t.get_history(str(tmp_path))
        assert len(history) <= HISTORY_MAX

    def test_oldest_entry_dropped(self, tmp_path):
        t = make_tracker()
        existing = [
            {"date": f"2024-01-{(i+1):02d}", "equity": float(i),
             "allocation": {"a": 1.0}, "timestamp": "2024-01-01T00:00:00+00:00",
             "top_adapter": "a", "adapter_count": 1}
            for i in range(HISTORY_MAX)
        ]
        write_history(str(tmp_path), existing)
        t.record_position({"a": 1.0}, 999.0, date_str="2026-12-31",
                          data_dir=str(tmp_path))
        history = t.get_history(str(tmp_path))
        assert history[-1]["date"] == "2026-12-31"
        assert history[0]["date"] != "2024-01-01"


# ---------------------------------------------------------------------------
# 12. Snapshot filtering — NaN / negative weights
# ---------------------------------------------------------------------------

class TestSnapshotFiltering:
    def test_negative_weight_excluded(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"good": 0.8, "bad": -0.1}, 100.0,
                                  date_str="2026-01-01", data_dir=str(tmp_path))
        assert "bad" not in snap["allocation"]

    def test_nan_weight_excluded(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"good": 0.5, "nan_adapter": float("nan")}, 100.0,
                                  date_str="2026-01-01", data_dir=str(tmp_path))
        assert "nan_adapter" not in snap["allocation"]

    def test_zero_weight_excluded_from_top_adapter_search(self, tmp_path):
        """Adapter with 0 weight is stored but top_adapter picks max > 0."""
        t = make_tracker()
        snap = t.record_position({"z": 0.0, "a": 0.9, "b": 0.1}, 100.0,
                                  date_str="2026-01-01", data_dir=str(tmp_path))
        assert snap["top_adapter"] == "a"

    def test_adapter_count_excludes_negatives(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"good": 1.0, "bad": -0.5}, 100.0,
                                  date_str="2026-01-01", data_dir=str(tmp_path))
        assert snap["adapter_count"] == 1


# ---------------------------------------------------------------------------
# 13. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_non_dict_allocation_raises(self, tmp_path):
        t = make_tracker()
        with pytest.raises(ValueError, match="allocation must be a dict"):
            t.record_position([0.5, 0.5], 100.0, data_dir=str(tmp_path))

    def test_nan_equity_raises(self, tmp_path):
        t = make_tracker()
        with pytest.raises(ValueError, match="equity must be a real number"):
            t.record_position({"a": 1.0}, float("nan"), data_dir=str(tmp_path))

    def test_string_equity_raises(self, tmp_path):
        t = make_tracker()
        with pytest.raises((ValueError, TypeError)):
            t.record_position({"a": 1.0}, "not_a_number", data_dir=str(tmp_path))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 14. Equity edge cases
# ---------------------------------------------------------------------------

class TestEquityEdgeCases:
    def test_zero_equity(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 0.0, date_str="2026-01-01",
                                  data_dir=str(tmp_path))
        assert snap["equity"] == 0.0

    def test_large_equity(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 1_000_000_000.0, date_str="2026-01-01",
                                  data_dir=str(tmp_path))
        assert snap["equity"] == pytest.approx(1_000_000_000.0)

    def test_fractional_equity_preserved(self, tmp_path):
        t = make_tracker()
        snap = t.record_position({"a": 1.0}, 99_999.999, date_str="2026-01-01",
                                  data_dir=str(tmp_path))
        assert abs(snap["equity"] - 99_999.999) < 0.001


# ---------------------------------------------------------------------------
# 15. _concentration_from_weights static method
# ---------------------------------------------------------------------------

class TestConcentrationFromWeights:
    def test_empty_dict(self):
        m = PositionTracker._concentration_from_weights({})
        assert m["hhi"] == 0.0
        assert m["adapter_count"] == 0

    def test_all_zeros(self):
        m = PositionTracker._concentration_from_weights({"a": 0.0, "b": 0.0})
        assert m["hhi"] == 0.0
        assert m["adapter_count"] == 0

    def test_single_adapter_full_weight(self):
        m = PositionTracker._concentration_from_weights({"only": 1.0})
        assert m["hhi"] == pytest.approx(1.0)
        assert m["max_single_pct"] == pytest.approx(100.0)
        assert m["adapter_count"] == 1

    def test_concentration_renormalises(self):
        """Weights that don't sum to 1 should be renormalised."""
        m = PositionTracker._concentration_from_weights({"a": 2.0, "b": 2.0})
        assert m["hhi"] == pytest.approx(0.5)  # each 50 %

    def test_top3_when_fewer_than_3(self):
        m = PositionTracker._concentration_from_weights({"a": 0.6, "b": 0.4})
        assert m["top3_pct"] == pytest.approx(100.0)

    def test_top3_when_exactly_3(self):
        m = PositionTracker._concentration_from_weights(
            {"a": 0.4, "b": 0.35, "c": 0.25}
        )
        assert m["top3_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 16. data_dir isolation / multiple trackers
# ---------------------------------------------------------------------------

class TestDataDirIsolation:
    def test_two_dirs_independent(self, tmp_path):
        dir_a = str(tmp_path / "dir_a")
        dir_b = str(tmp_path / "dir_b")
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01", data_dir=dir_a)
        t.record_position({"b": 1.0}, 200.0, date_str="2026-01-01", data_dir=dir_b)
        hist_a = t.get_history(dir_a)
        hist_b = t.get_history(dir_b)
        assert hist_a[0]["allocation"] == {"a": 1.0}
        assert hist_b[0]["allocation"] == {"b": 1.0}

    def test_missing_dir_created_automatically(self, tmp_path):
        nested = str(tmp_path / "nested" / "deep" / "data")
        t = make_tracker()
        t.record_position({"a": 1.0}, 100.0, date_str="2026-01-01",
                          data_dir=nested)
        assert (Path(nested) / HISTORY_FILENAME).exists()
