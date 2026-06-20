"""
MP-441: Tests for scripts/generate_evidence_report.py
"""

import importlib
import json
import os
import sys
import types

import pytest

# ---- ensure repo root is importable ----------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ---- import the module under test ------------------------------------------
import generate_evidence_report as ger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_EVIDENCE = {
    "schema_version": "1.0",
    "start_date": "2026-06-12",
    "min_days_required": 30,
    "golive_target": "2026-08-01",
    "base_capital": 100000.0,
    "days": [],
    "strategies": {},
}

MINIMAL_TOURNAMENT = {
    "generated_at": "2026-06-12",
    "tournament_days": 3,
    "winner": "S7",
    "strategies": [
        {
            "rank": 1,
            "id": "S7",
            "name": "Pendle YT+PT Aggressive",
            "status": "target_met",
            "tier": "T3",
            "days_running": 3,
            "apy_target": 10.0,
            "apy_realized": 10.1,
            "sharpe": 0.96,
            "calmar": 6.47,
            "ulcer": 1.3,
            "equity_now": 100830.0,
            "equity_series": [100000.0, 100194.0, 100387.0, 100581.0, 100830.0],
        },
    ],
    "strategy_count": 1,
}

MINIMAL_GOLIVE = {
    "ready": True,
    "checks": {
        "equity_curve_real": True,
        "trades_real": True,
        "status_real": True,
    },
    "blockers": [],
    "timestamp": "2026-06-12T18:31:16.195604+00:00",
    "source": "golive_checker",
}


def _write_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


@pytest.fixture()
def tmp_data(tmp_path):
    """Write minimal fixture JSON files and return their paths."""
    evidence_path = str(tmp_path / "paper_evidence.json")
    tournament_path = str(tmp_path / "tournament_ranking.json")
    golive_path = str(tmp_path / "golive_status.json")

    _write_json(evidence_path, MINIMAL_EVIDENCE)
    _write_json(tournament_path, MINIMAL_TOURNAMENT)
    _write_json(golive_path, MINIMAL_GOLIVE)

    return evidence_path, tournament_path, golive_path


# ---------------------------------------------------------------------------
# Test 1: Module imports without errors
# ---------------------------------------------------------------------------

def test_module_imports():
    """The module must be importable without raising any exception."""
    assert isinstance(ger, types.ModuleType)


# ---------------------------------------------------------------------------
# Test 2: generate_report() returns a string
# ---------------------------------------------------------------------------

def test_generate_report_returns_string(tmp_data):
    evidence_path, tournament_path, golive_path = tmp_data
    result = ger.generate_report(evidence_path, tournament_path, golive_path)
    assert isinstance(result, str), "generate_report() must return a str"


# ---------------------------------------------------------------------------
# Test 3: Report contains all mandatory sections
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section_header", [
    "SPA FAMILY FUND — 30-DAY EVIDENCE REPORT",
    "SECTION 1: PAPER TRADING SUMMARY",
    "SECTION 2: STRATEGY TOURNAMENT (Top 5)",
    "SECTION 3: GO-LIVE CHECKLIST",
    "SECTION 4: OWNER DECISION",
    "CONFIDENTIAL — ДОГОВІР ПРОСТОГО ТОВАРИСТВА",
])
def test_report_contains_section(tmp_data, section_header):
    evidence_path, tournament_path, golive_path = tmp_data
    report = ger.generate_report(evidence_path, tournament_path, golive_path)
    assert section_header in report, f"Report must contain: {section_header!r}"


# ---------------------------------------------------------------------------
# Test 4: Empty paper_evidence.json → report still generated without crash
# ---------------------------------------------------------------------------

def test_empty_paper_evidence(tmp_path):
    evidence_path = str(tmp_path / "paper_evidence.json")
    tournament_path = str(tmp_path / "tournament_ranking.json")
    golive_path = str(tmp_path / "golive_status.json")

    _write_json(evidence_path, {})  # Completely empty
    _write_json(tournament_path, MINIMAL_TOURNAMENT)
    _write_json(golive_path, MINIMAL_GOLIVE)

    report = ger.generate_report(evidence_path, tournament_path, golive_path)
    assert isinstance(report, str)
    assert len(report) > 100, "Report must have some content even with empty evidence"


# ---------------------------------------------------------------------------
# Test 5: Missing files → graceful degradation (no FileNotFoundError)
# ---------------------------------------------------------------------------

def test_missing_files_graceful(tmp_path):
    """If data files don't exist, generate_report() must not raise."""
    nonexistent = str(tmp_path / "nope.json")
    # All three paths point to non-existent files
    report = ger.generate_report(nonexistent, nonexistent, nonexistent)
    assert isinstance(report, str)
    assert "SECTION 1" in report


# ---------------------------------------------------------------------------
# Test 6: Blockers → recommendation is BLOCKED
# ---------------------------------------------------------------------------

def test_blocked_recommendation(tmp_data):
    evidence_path, tournament_path, golive_path = tmp_data

    # Overwrite golive with blockers
    blocked_golive = {
        "ready": False,
        "checks": {"equity_curve_real": False},
        "blockers": ["equity_curve_not_real"],
        "timestamp": "2026-06-12T00:00:00+00:00",
    }
    _write_json(golive_path, blocked_golive)

    report = ger.generate_report(evidence_path, tournament_path, golive_path)
    assert "BLOCKED" in report


# ---------------------------------------------------------------------------
# Test 7: Report contains strategy name from tournament top-5
# ---------------------------------------------------------------------------

def test_report_contains_winner_strategy(tmp_data):
    evidence_path, tournament_path, golive_path = tmp_data
    report = ger.generate_report(evidence_path, tournament_path, golive_path)
    # Winner is S7 "Pendle YT+PT Aggressive"
    assert "S7" in report or "Pendle YT+PT Aggressive" in report


# ---------------------------------------------------------------------------
# Test 8: write_report() atomically creates the file
# ---------------------------------------------------------------------------

def test_write_report_creates_file(tmp_path):
    output_path = str(tmp_path / "subdir" / "evidence_report_30d.txt")
    sample_report = "Test report content\nLine 2\n"
    result_path = ger.write_report(sample_report, output_path)

    assert result_path == output_path
    assert os.path.isfile(output_path), "Output file must exist after write_report()"
    with open(output_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert content == sample_report


# ---------------------------------------------------------------------------
# Test 9: load_json returns empty dict for non-existent file
# ---------------------------------------------------------------------------

def test_load_json_missing_file(tmp_path):
    result = ger.load_json(str(tmp_path / "does_not_exist.json"))
    assert result == {}


# ---------------------------------------------------------------------------
# Test 10: load_json returns empty dict for malformed JSON
# ---------------------------------------------------------------------------

def test_load_json_malformed(tmp_path):
    bad_path = str(tmp_path / "bad.json")
    with open(bad_path, "w") as fh:
        fh.write("{invalid json{{")
    result = ger.load_json(bad_path)
    assert result == {}
