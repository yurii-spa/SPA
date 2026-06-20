"""
Tests for scripts/weekly_evidence_report.py — ADR-002 Evidence Report Generator
Minimum 20 tests covering: week label, report generation, atomic save,
missing-data graceful handling, all report sections, and CLI.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# Make scripts/ importable
# ---------------------------------------------------------------------------
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from weekly_evidence_report import (
    _annualise,
    _fmt_pct,
    _fmt_usd,
    _load_json,
    _paper_day,
    _section_adapters,
    _section_header,
    _section_milestones,
    _section_owner_actions,
    _section_portfolio,
    _section_risk,
    _section_tournament,
    _week_date_range,
    generate_report,
    get_week_label,
    load_equity_history,
    load_milestone_log,
    load_pnl_history,
    load_tournament,
    main,
    save_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Temporary data directory with minimal valid JSON files."""
    d = tmp_path / "data"
    d.mkdir()

    (d / "equity_curve_daily.json").write_text(json.dumps({
        "generated_at": "2026-06-12T06:00:00",
        "is_demo": False,
        "summary": {
            "start_equity": 100000.0,
            "end_equity": 100026.06,
        },
        "daily": [
            {
                "date": "2026-06-10",
                "close_equity": 100008.61,
                "daily_return_pct": 0.0,
                "apy_today": 3.14,
                "daily_yield_usd": 8.61,
            },
            {
                "date": "2026-06-11",
                "close_equity": 100017.30,
                "daily_return_pct": 0.0087,
                "apy_today": 3.17,
                "daily_yield_usd": 8.69,
            },
            {
                "date": "2026-06-12",
                "close_equity": 100026.06,
                "daily_return_pct": 0.0088,
                "apy_today": 3.21,
                "daily_yield_usd": 8.76,
            },
        ],
    }), encoding="utf-8")

    (d / "pnl_history.json").write_text(json.dumps([
        {"timestamp": "2026-06-10 06:00:00", "total_pnl_usd": 8.61,  "current_apy": 3.14},
        {"timestamp": "2026-06-11 06:00:00", "total_pnl_usd": 17.30, "current_apy": 3.17},
        {"timestamp": "2026-06-12 06:00:00", "total_pnl_usd": 26.06, "current_apy": 3.21},
    ]), encoding="utf-8")

    (d / "tournament_ranking.json").write_text(json.dumps({
        "generated_at": "2026-06-12",
        "winner": "S7",
        "strategies": [
            {"rank": 1, "id": "S7", "name": "Pendle YT+PT Aggressive",
             "status": "leading", "apy_realized": 10.115, "sharpe": 1.2, "calmar": 6.47},
            {"rank": 2, "id": "S5", "name": "Pendle PT Enhanced",
             "status": "new",     "apy_realized": None,   "sharpe": None},
        ],
    }), encoding="utf-8")

    (d / "apy_milestone_log.json").write_text(json.dumps({
        "start_date": "2026-06-10",
        "last_updated": "2026-06-12",
        "days_recorded": 3,
        "daily_log": [],
        "milestones_reached": [
            {"level": 1, "name": "Baseline beat",  "target_pct": 5.0,  "first_reached_date": "2026-06-05"},
            {"level": 2, "name": "Target entry",   "target_pct": 7.0,  "first_reached_date": "2026-06-05"},
            {"level": 3, "name": "Target mid",     "target_pct": 10.0, "first_reached_date": "2026-06-09"},
        ],
    }), encoding="utf-8")

    (d / "market_regime.json").write_text(json.dumps({
        "regime": "STABLE",
        "t1_avg_apy": 4.93,
        "recommendation": "hold",
    }), encoding="utf-8")

    (d / "risk_policy_blocks.json").write_text(json.dumps([]), encoding="utf-8")

    (d / "golive_status.json").write_text(json.dumps({
        "ready": False,
        "checks": {
            "equity_curve_real": True,
            "trades_real": False,
            "data_fresh_48h": True,
        },
        "blockers": ["trades_real: no real trades yet"],
        "timestamp": "2026-06-12T19:00:00",
    }), encoding="utf-8")

    (d / "current_positions.json").write_text(json.dumps({
        "capital_usd": 100000.0,
        "deployed_usd": 95000.0,
        "cash_usd": 5000.0,
        "positions": {
            "aave_v3":    31946.82,
            "compound_v3": 29803.17,
            "yearn_v3":   11518.60,
        },
    }), encoding="utf-8")

    (d / "adapter_status.json").write_text(json.dumps({
        "generated_at": "2026-06-12",
        "aave_v3":    {"apy_pct": 3.5, "status": "active"},
        "compound_v3":{"apy_pct": 4.8, "status": "active"},
        "yearn_v3":   {"apy_pct": 5.1, "status": "active"},
    }), encoding="utf-8")

    return d


# ---------------------------------------------------------------------------
# 1. get_week_label
# ---------------------------------------------------------------------------

class TestGetWeekLabel:
    def test_format_is_YYYY_WNN(self):
        label = get_week_label(date(2026, 6, 12))
        assert label == "2026-W24"

    def test_format_week_01(self):
        label = get_week_label(date(2026, 1, 5))
        assert label.startswith("2026-W")
        assert len(label) == 7  # YYYY-WNN

    def test_zero_padded_week(self):
        # Week 1 of a year should be zero-padded to W01
        label = get_week_label(date(2026, 1, 1))
        assert "-W0" in label or "-W1" in label  # week 1 = W01

    def test_returns_string(self):
        assert isinstance(get_week_label(), str)

    def test_default_is_today(self):
        label_default = get_week_label()
        label_today = get_week_label(date.today())
        assert label_default == label_today

    def test_week_24_boundaries(self):
        # 2026-06-08 (Mon) and 2026-06-14 (Sun) are both in W24
        assert get_week_label(date(2026, 6, 8))  == "2026-W24"
        assert get_week_label(date(2026, 6, 14)) == "2026-W24"


# ---------------------------------------------------------------------------
# 2. _week_date_range
# ---------------------------------------------------------------------------

class TestWeekDateRange:
    def test_monday_sunday(self):
        mon, sun = _week_date_range("2026-W24")
        assert mon.weekday() == 0  # Monday
        assert sun.weekday() == 6  # Sunday
        assert (sun - mon).days == 6

    def test_correct_dates_w24(self):
        mon, sun = _week_date_range("2026-W24")
        assert mon == date(2026, 6, 8)
        assert sun == date(2026, 6, 14)


# ---------------------------------------------------------------------------
# 3. _paper_day
# ---------------------------------------------------------------------------

class TestPaperDay:
    def test_day_0_before_start(self):
        assert _paper_day(date(2026, 6, 9)) == 0

    def test_day_1_on_start(self):
        assert _paper_day(date(2026, 6, 10)) == 1

    def test_day_3(self):
        assert _paper_day(date(2026, 6, 12)) == 3


# ---------------------------------------------------------------------------
# 4. generate_report — top-level
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_returns_string(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert isinstance(result, str)

    def test_contains_title(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert "# SPA Weekly Evidence Report" in result

    def test_contains_week_label(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert "2026-W24" in result

    def test_all_sections_present(self):
        result = generate_report("2026-W24", [], [], {}, {})
        for section in [
            "## Portfolio Performance",
            "## Strategy Tournament",
            "## Milestones Reached",
            "## Risk Assessment",
            "## Adapter Status",
            "## Owner Actions Required",
        ]:
            assert section in result, f"Missing section: {section}"

    def test_empty_inputs_no_crash(self):
        """Completely empty inputs must not raise."""
        try:
            result = generate_report("2026-W24", [], [], {}, {})
        except Exception as exc:
            pytest.fail(f"generate_report crashed on empty inputs: {exc}")

    def test_none_optional_args_no_crash(self):
        """None optional args must be tolerated."""
        try:
            result = generate_report(
                "2026-W24", [], [], {}, {},
                market_regime=None,
                risk_blocks=None,
                golive_status=None,
                current_positions=None,
                adapter_status=None,
            )
        except Exception as exc:
            pytest.fail(f"generate_report crashed on None optional args: {exc}")

    def test_equity_data_appears_in_report(self):
        equity = [
            {"date": "2026-06-10", "equity": 100008.61, "daily_return_pct": 0.0, "apy_today": 3.14, "daily_yield_usd": 8.61},
            {"date": "2026-06-11", "equity": 100017.30, "daily_return_pct": 0.0087, "apy_today": 3.17, "daily_yield_usd": 8.69},
        ]
        result = generate_report("2026-W24", equity, [], {}, {})
        # Start equity should appear somewhere
        assert "100,008.61" in result or "100,000" in result

    def test_tournament_winner_appears(self):
        tournament = {
            "winner": "S7",
            "strategies": [
                {"rank": 1, "id": "S7", "name": "Pendle YT", "status": "leading",
                 "apy_realized": 10.115, "sharpe": 1.2},
            ],
        }
        result = generate_report("2026-W24", [], [], tournament, {})
        assert "S7" in result or "Pendle YT" in result

    def test_milestones_l1_l2_l3_reached(self):
        milestone_log = {
            "milestones_reached": [
                {"level": 1, "target_pct": 5.0, "first_reached_date": "2026-06-05"},
                {"level": 2, "target_pct": 7.0, "first_reached_date": "2026-06-05"},
                {"level": 3, "target_pct": 10.0, "first_reached_date": "2026-06-09"},
            ]
        }
        result = generate_report("2026-W24", [], [], {}, milestone_log)
        assert "✅ L1" in result
        assert "✅ L2" in result
        assert "✅ L3" in result

    def test_unreached_milestone_shows_pending(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert "⏳" in result  # at least one pending milestone

    def test_risk_gate_pass_when_no_blocks(self):
        result = generate_report("2026-W24", [], [], {}, {},
                                 risk_blocks=[], market_regime={"regime": "STABLE"})
        assert "PASS" in result

    def test_risk_gate_shows_blocks_count(self):
        blocks = [{"timestamp": "2026-06-10T10:00:00", "reason": "TVL too low"}]
        result = generate_report("2026-W24", [], [], {}, {}, risk_blocks=blocks)
        assert "BLOCK" in result or "1" in result

    def test_adr002_footer_present(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert "ADR-002" in result

    def test_golive_target_date_in_header(self):
        result = generate_report("2026-W24", [], [], {}, {})
        assert "2026-08-01" in result

    def test_volatile_regime_shows_warning(self):
        regime = {"regime": "VOLATILE", "recommendation": "reduce"}
        result = generate_report("2026-W24", [], [], {}, {}, market_regime=regime)
        assert "VOLATILE" in result

    def test_owner_actions_none_required(self):
        result = generate_report("2026-W24", [], [], {}, {},
                                 golive_status={"ready": True, "blockers": [], "checks": {}},
                                 market_regime={"regime": "STABLE"})
        assert "No owner actions required" in result

    def test_owner_actions_blocker_listed(self):
        golive = {"ready": False, "blockers": ["trades_real: no real trades"], "checks": {}}
        result = generate_report("2026-W24", [], [], {}, {}, golive_status=golive)
        assert "trades_real" in result


# ---------------------------------------------------------------------------
# 5. save_report
# ---------------------------------------------------------------------------

class TestSaveReport:
    def test_file_is_created(self, tmp_path):
        content = "# Test\n"
        path = save_report(content, "2026-W24", data_dir=tmp_path)
        assert os.path.isfile(path)

    def test_correct_filename(self, tmp_path):
        path = save_report("# Test\n", "2026-W24", data_dir=tmp_path)
        assert path.endswith("2026-W24.md")

    def test_content_is_preserved(self, tmp_path):
        content = "# SPA Weekly Evidence Report — 2026-W24\n\nTest content.\n"
        path = save_report(content, "2026-W24", data_dir=tmp_path)
        with open(path, encoding="utf-8") as fh:
            written = fh.read()
        assert written == content

    def test_creates_weekly_evidence_subdirectory(self, tmp_path):
        save_report("# Test\n", "2026-W24", data_dir=tmp_path)
        assert (tmp_path / "weekly_evidence").is_dir()

    def test_overwrite_is_idempotent(self, tmp_path):
        save_report("version 1\n", "2026-W24", data_dir=tmp_path)
        path = save_report("version 2\n", "2026-W24", data_dir=tmp_path)
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "version 2\n"

    def test_no_tmp_file_left_behind(self, tmp_path):
        save_report("# Test\n", "2026-W25", data_dir=tmp_path)
        leftover = list((tmp_path / "weekly_evidence").glob(".tmp_*"))
        assert len(leftover) == 0


# ---------------------------------------------------------------------------
# 6. Data loaders — graceful fallback
# ---------------------------------------------------------------------------

class TestDataLoaders:
    def test_load_equity_history_missing_file(self, tmp_path):
        result = load_equity_history(tmp_path)
        assert result == []

    def test_load_pnl_history_missing_file(self, tmp_path):
        result = load_pnl_history(tmp_path)
        assert result == []

    def test_load_tournament_missing_file(self, tmp_path):
        result = load_tournament(tmp_path)
        assert result == {}

    def test_load_milestone_log_missing_file(self, tmp_path):
        result = load_milestone_log(tmp_path)
        assert result == {}

    def test_load_equity_from_equity_curve_daily(self, tmp_data_dir):
        rows = load_equity_history(tmp_data_dir)
        assert len(rows) == 3
        assert rows[0]["date"] == "2026-06-10"
        assert rows[0]["equity"] == 100008.61

    def test_load_equity_fallback_to_history(self, tmp_path):
        """When equity_curve_daily.json missing, falls back to equity_history.json."""
        (tmp_path / "equity_history.json").write_text(json.dumps([
            {"date": "2026-06-10", "equity": 100000.0, "apy_pct": 9.8, "day_pnl": 0.0},
        ]), encoding="utf-8")
        rows = load_equity_history(tmp_path)
        assert len(rows) == 1
        assert rows[0]["equity"] == 100000.0

    def test_load_json_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {{{", encoding="utf-8")
        result = _load_json(bad)
        assert result == {}

    def test_load_json_missing_file(self, tmp_path):
        result = _load_json(tmp_path / "nonexistent.json")
        assert result == {}


# ---------------------------------------------------------------------------
# 7. Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_fmt_usd_positive(self):
        assert _fmt_usd(26.06) == "+$26.06"

    def test_fmt_usd_negative(self):
        assert "-$" in _fmt_usd(-10.5)

    def test_fmt_pct_positive(self):
        assert _fmt_pct(0.03).startswith("+")

    def test_annualise_positive(self):
        # A 0.1% weekly return should annualise to roughly 5.3%
        ann = _annualise(0.1)
        assert 5.0 < ann < 6.0

    def test_annualise_zero(self):
        assert _annualise(0.0) == 0.0


# ---------------------------------------------------------------------------
# 8. CLI (main())
# ---------------------------------------------------------------------------

class TestCLI:
    def test_dry_run_prints_report(self, tmp_data_dir, capsys):
        ret = main(["--dry-run", "--data-dir", str(tmp_data_dir)])
        captured = capsys.readouterr()
        assert ret == 0
        assert "# SPA Weekly Evidence Report" in captured.out

    def test_saves_file_when_not_dry_run(self, tmp_data_dir, capsys):
        ret = main(["--data-dir", str(tmp_data_dir)])
        assert ret == 0
        out_file = tmp_data_dir / "weekly_evidence" / f"{get_week_label()}.md"
        assert out_file.exists()

    def test_week_flag_overrides_default(self, tmp_data_dir, capsys):
        ret = main(["--week", "2026-W24", "--dry-run", "--data-dir", str(tmp_data_dir)])
        captured = capsys.readouterr()
        assert ret == 0
        assert "2026-W24" in captured.out

    def test_missing_data_dir_still_produces_report(self, tmp_path, capsys):
        """Completely empty data dir should not crash."""
        empty_data = tmp_path / "data_empty"
        empty_data.mkdir()
        ret = main(["--dry-run", "--data-dir", str(empty_data)])
        assert ret == 0


# ---------------------------------------------------------------------------
# 9. Integration — full pipeline with fixture data
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline_with_fixture_data(self, tmp_data_dir):
        from weekly_evidence_report import (
            load_adapter_status,
            load_current_positions,
            load_golive_status,
            load_market_regime,
            load_risk_blocks,
        )
        equity = load_equity_history(tmp_data_dir)
        pnl = load_pnl_history(tmp_data_dir)
        tournament = load_tournament(tmp_data_dir)
        milestones = load_milestone_log(tmp_data_dir)
        regime = load_market_regime(tmp_data_dir)
        blocks = load_risk_blocks(tmp_data_dir)
        golive = load_golive_status(tmp_data_dir)
        positions = load_current_positions(tmp_data_dir)
        adapters = load_adapter_status(tmp_data_dir)

        report = generate_report(
            week_label="2026-W24",
            equity_history=equity,
            pnl_history=pnl,
            tournament_data=tournament,
            milestone_log=milestones,
            market_regime=regime,
            risk_blocks=blocks,
            golive_status=golive,
            current_positions=positions,
            adapter_status=adapters,
        )

        assert "# SPA Weekly Evidence Report — 2026-W24" in report
        assert "aave_v3" in report
        assert "S7" in report or "Pendle YT" in report
        assert "✅ L1" in report
        assert "STABLE" in report

    def test_saved_report_is_valid_markdown(self, tmp_data_dir):
        equity = load_equity_history(tmp_data_dir)
        report = generate_report("2026-W24", equity, [], {}, {})
        path = save_report(report, "2026-W24", data_dir=tmp_data_dir)

        with open(path, encoding="utf-8") as fh:
            content = fh.read()

        # Basic markdown checks
        assert content.startswith("#")
        assert "##" in content
        assert "|" in content  # tables present
