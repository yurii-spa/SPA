"""
Offline tests for SPA-V371 — APY gap report persisted into the 4h export
pipeline (data/apy_gap_report.json).

Two layers:
  1. apy_gap_report() output contract (shape / types / arithmetic), exercised
     with synthetic PaperTrader.get_status() dicts — no network, no DB.
  2. export_data.py wiring: the guarded block writes apy_gap_report.json and
     the file is registered in the files_written manifest (static source check
     so the test needs neither a live DB nor a running server).
"""
import re
from pathlib import Path

from spa_core.data_pipeline.apy_gap_report import (
    apy_gap_report,
    TARGET_APY,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _status(positions, total_capital=100_000.0):
    return {
        "portfolio": {"total_capital_usd": total_capital},
        "positions": positions,
    }


_EXPECTED_KEYS = {
    "current_weighted_apy",
    "target_apy",
    "gap",
    "gap_closeable_by_pendle",
    "gap_closeable_by_sky",
    "remaining_gap",
    "on_track",
    "pendle_status",
    "sky_status",
    "summary",
}


# --------------------------------------------------------------------------
# 1. report contract
# --------------------------------------------------------------------------

def test_report_has_all_expected_keys():
    rep = apy_gap_report(_status([]))
    assert _EXPECTED_KEYS.issubset(rep.keys())


def test_empty_portfolio_below_target():
    rep = apy_gap_report(_status([]))
    assert rep["current_weighted_apy"] == 0.0
    assert rep["on_track"] is False
    assert rep["gap"] == round(TARGET_APY - 0.0, 4)
    assert rep["target_apy"] == TARGET_APY


def test_weighted_apy_and_gap_arithmetic():
    # one T1 position covering all capital at 5.0% → weighted APY 5.0
    rep = apy_gap_report(_status(
        [{"amount_usd": 100_000.0, "current_apy": 5.0, "tier": "T1"}],
    ))
    assert rep["current_weighted_apy"] == 5.0
    assert rep["gap"] == round(TARGET_APY - 5.0, 4)
    assert rep["on_track"] is False


def test_on_track_when_at_or_above_target():
    rep = apy_gap_report(_status(
        [{"amount_usd": 100_000.0, "current_apy": TARGET_APY + 1.0, "tier": "T1"}],
    ))
    assert rep["on_track"] is True
    assert rep["gap"] <= 0
    assert "On track" in rep["summary"]


def test_sky_status_always_pending_whitelist():
    rep = apy_gap_report(_status([]))
    assert rep["sky_status"] == "pending_whitelist"


def test_pendle_status_none_when_no_pendle_positions():
    rep = apy_gap_report(_status(
        [{"amount_usd": 100_000.0, "current_apy": 4.0, "tier": "T1"}],
    ))
    assert rep["pendle_status"] == "none"


def test_pendle_status_detected_from_fixed_rate_position():
    rep = apy_gap_report(_status([
        {"amount_usd": 50_000.0, "current_apy": 4.0, "tier": "T1"},
        {"amount_usd": 20_000.0, "current_apy": 7.5, "tier": "T2",
         "special": "fixed_rate", "protocol_key": "pendle-pt-usdc"},
    ]))
    assert rep["pendle_status"] in ("partial", "eligible")


def test_remaining_gap_never_negative():
    rep = apy_gap_report(_status([]))
    assert rep["remaining_gap"] >= 0.0


def test_never_raises_on_missing_keys():
    # totally empty dict must degrade, not throw
    rep = apy_gap_report({})
    assert _EXPECTED_KEYS.issubset(rep.keys())


# --------------------------------------------------------------------------
# 2. export pipeline wiring (static source check)
# --------------------------------------------------------------------------

def _export_src():
    p = Path(__file__).resolve().parents[1] / "export_data.py"
    return p.read_text(encoding="utf-8")


def test_export_writes_apy_gap_report_json():
    src = _export_src()
    assert 'write_json("apy_gap_report.json"' in src
    assert "from data_pipeline.apy_gap_report import apy_gap_report" in src


def test_export_tracks_section_health():
    src = _export_src()
    # P3-8: health helpers are now ExportContext methods (ctx.section_ok/fail).
    assert 'section_ok("apy_gap_report")' in src
    assert 'section_fail("apy_gap_report")' in src


def test_export_registers_file_in_manifest():
    src = _export_src()
    # manifest list entry
    assert re.search(r'files_written\s*=\s*\[', src)
    assert '"apy_gap_report.json"' in src


def test_export_block_is_guarded():
    src = _export_src()
    # the apy gap block must be inside a try/except (graceful, never aborts cycle)
    block = src[src.index("APY gap report (SPA-V371)"):]
    assert "try:" in block[:1000]
    assert "except Exception" in block[:1600]


# --------------------------------------------------------------------------
# SPA-V373 — apy_gap history persistence (append_apy_gap_history)
# --------------------------------------------------------------------------

import json

from spa_core.data_pipeline.apy_gap_report import (
    append_apy_gap_history,
    APY_GAP_HISTORY_FILENAME,
    MAX_HISTORY,
)


def _doc(ts, current=4.2, gap=3.1, on_track=False):
    return {
        "generated_at": ts,
        "current_weighted_apy": current,
        "gap": gap,
        "on_track": on_track,
    }


def _read_history(data_dir):
    return json.loads((Path(data_dir) / APY_GAP_HISTORY_FILENAME).read_text())


class TestAppendApyGapHistory:
    def test_first_append_creates_single_record(self, tmp_path):
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z"), data_dir=str(tmp_path))
        hist = _read_history(tmp_path)
        assert isinstance(hist, list) and len(hist) == 1
        assert set(hist[0].keys()) == {
            "generated_at", "current_weighted_apy", "gap", "on_track",
        }
        assert hist[0]["current_weighted_apy"] == 4.2

    def test_distinct_timestamps_append(self, tmp_path):
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z"), data_dir=str(tmp_path))
        append_apy_gap_history(_doc("2026-06-01T04:00:00Z", current=4.8), data_dir=str(tmp_path))
        hist = _read_history(tmp_path)
        assert len(hist) == 2
        assert hist[-1]["current_weighted_apy"] == 4.8

    def test_same_timestamp_dedups_replaces_last(self, tmp_path):
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z", current=4.2), data_dir=str(tmp_path))
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z", current=5.0), data_dir=str(tmp_path))
        hist = _read_history(tmp_path)
        assert len(hist) == 1
        assert hist[0]["current_weighted_apy"] == 5.0

    def test_trims_to_max_history_keeping_latest(self, tmp_path):
        for i in range(MAX_HISTORY + 25):
            append_apy_gap_history(_doc(f"2026-06-01T{i:04d}", current=float(i)), data_dir=str(tmp_path))
        hist = _read_history(tmp_path)
        assert len(hist) == MAX_HISTORY
        # last record preserved
        assert hist[-1]["current_weighted_apy"] == float(MAX_HISTORY + 24)

    def test_never_raises_on_corrupt_file(self, tmp_path):
        (tmp_path / APY_GAP_HISTORY_FILENAME).write_text("{ not json")
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z"), data_dir=str(tmp_path))
        hist = _read_history(tmp_path)
        assert len(hist) == 1  # corrupt -> treated as empty, then appended

    def test_missing_file_starts_fresh(self, tmp_path):
        # no pre-existing file
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z"), data_dir=str(tmp_path))
        assert (tmp_path / APY_GAP_HISTORY_FILENAME).exists()

    def test_never_raises_when_data_dir_unwritable(self, tmp_path):
        # parent is a file -> mkdir impossible; must swallow, not raise
        bogus = tmp_path / "afile"
        bogus.write_text("x")
        append_apy_gap_history(_doc("2026-06-01T00:00:00Z"), data_dir=str(bogus / "sub"))
        # no exception is the assertion

    def test_export_wires_history_append(self):
        src = _export_src()
        assert "append_apy_gap_history" in src
        assert '"apy_gap_report_history.json"' in src
