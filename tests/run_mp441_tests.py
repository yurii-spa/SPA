#!/usr/bin/env python3
"""
Standalone test runner for test_evidence_report.py — no pytest required.
Runs with: python3 tests/run_mp441_tests.py
"""

import json
import os
import sys
import tempfile
import traceback
import types

# ---- repo root on sys.path ------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
for p in (_SCRIPTS_DIR, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import generate_evidence_report as ger


# --------------------------------------------------------------------------- #
# Fixtures (stdlib equivalents)
# --------------------------------------------------------------------------- #

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


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_tmp_data():
    """Returns (tmpdir, evidence_path, tournament_path, golive_path)."""
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    evidence_path = os.path.join(tmpdir, "paper_evidence.json")
    tournament_path = os.path.join(tmpdir, "tournament_ranking.json")
    golive_path = os.path.join(tmpdir, "golive_status.json")
    _write_json(evidence_path, MINIMAL_EVIDENCE)
    _write_json(tournament_path, MINIMAL_TOURNAMENT)
    _write_json(golive_path, MINIMAL_GOLIVE)
    return tmpdir, evidence_path, tournament_path, golive_path


# --------------------------------------------------------------------------- #
# Test runner
# --------------------------------------------------------------------------- #

PASS = 0
FAIL = 0
ERRORS = []


def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  PASS  {name}")
        PASS += 1
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        FAIL += 1
        ERRORS.append((name, traceback.format_exc()))
    except Exception as e:
        print(f"  ERROR {name}: {e}")
        FAIL += 1
        ERRORS.append((name, traceback.format_exc()))


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_module_imports():
    assert isinstance(ger, types.ModuleType)


def test_generate_report_returns_string():
    tmpdir, ep, tp, gp = _make_tmp_data()
    result = ger.generate_report(ep, tp, gp)
    assert isinstance(result, str), "generate_report() must return a str"


def test_report_contains_section_header():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "SPA FAMILY FUND — 30-DAY EVIDENCE REPORT" in report


def test_report_contains_section1():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "SECTION 1: PAPER TRADING SUMMARY" in report


def test_report_contains_section2():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "SECTION 2: STRATEGY TOURNAMENT (Top 5)" in report


def test_report_contains_section3():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "SECTION 3: GO-LIVE CHECKLIST" in report


def test_report_contains_section4():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "SECTION 4: OWNER DECISION" in report


def test_report_contains_confidential():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "CONFIDENTIAL — ДОГОВІР ПРОСТОГО ТОВАРИСТВА" in report


def test_empty_paper_evidence():
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    ep = os.path.join(tmpdir, "paper_evidence.json")
    tp = os.path.join(tmpdir, "tournament_ranking.json")
    gp = os.path.join(tmpdir, "golive_status.json")
    _write_json(ep, {})
    _write_json(tp, MINIMAL_TOURNAMENT)
    _write_json(gp, MINIMAL_GOLIVE)

    report = ger.generate_report(ep, tp, gp)
    assert isinstance(report, str)
    assert len(report) > 100


def test_missing_files_graceful():
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    nonexistent = os.path.join(tmpdir, "nope.json")
    report = ger.generate_report(nonexistent, nonexistent, nonexistent)
    assert isinstance(report, str)
    assert "SECTION 1" in report


def test_blocked_recommendation():
    tmpdir, ep, tp, gp = _make_tmp_data()
    blocked_golive = {
        "ready": False,
        "checks": {"equity_curve_real": False},
        "blockers": ["equity_curve_not_real"],
        "timestamp": "2026-06-12T00:00:00+00:00",
    }
    _write_json(gp, blocked_golive)
    report = ger.generate_report(ep, tp, gp)
    assert "BLOCKED" in report


def test_report_contains_winner_strategy():
    tmpdir, ep, tp, gp = _make_tmp_data()
    report = ger.generate_report(ep, tp, gp)
    assert "S7" in report or "Pendle YT+PT Aggressive" in report


def test_write_report_creates_file():
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    subdir = os.path.join(tmpdir, "subdir")
    output_path = os.path.join(subdir, "evidence_report_30d.txt")
    sample = "Test report content\nLine 2\n"
    result_path = ger.write_report(sample, output_path)
    assert result_path == output_path
    assert os.path.isfile(output_path)
    with open(output_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert content == sample


def test_load_json_missing_file():
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    result = ger.load_json(os.path.join(tmpdir, "does_not_exist.json"))
    assert result == {}


def test_load_json_malformed():
    tmpdir = tempfile.mkdtemp(prefix="spa_test_")
    bad_path = os.path.join(tmpdir, "bad.json")
    with open(bad_path, "w") as fh:
        fh.write("{invalid json{{")
    result = ger.load_json(bad_path)
    assert result == {}


# --------------------------------------------------------------------------- #
# Run all
# --------------------------------------------------------------------------- #

ALL_TESTS = [
    test_module_imports,
    test_generate_report_returns_string,
    test_report_contains_section_header,
    test_report_contains_section1,
    test_report_contains_section2,
    test_report_contains_section3,
    test_report_contains_section4,
    test_report_contains_confidential,
    test_empty_paper_evidence,
    test_missing_files_graceful,
    test_blocked_recommendation,
    test_report_contains_winner_strategy,
    test_write_report_creates_file,
    test_load_json_missing_file,
    test_load_json_malformed,
]

if __name__ == "__main__":
    print(f"\nRunning {len(ALL_TESTS)} tests for MP-441 (generate_evidence_report)\n")
    for t in ALL_TESTS:
        run(t.__name__, t)

    print(f"\n{'='*50}")
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")

    if ERRORS:
        print("\nFailure details:")
        for name, tb in ERRORS:
            print(f"\n--- {name} ---")
            print(tb)

    sys.exit(0 if FAIL == 0 else 1)
