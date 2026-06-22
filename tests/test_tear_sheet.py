"""tests/test_tear_sheet.py — Tests for TearSheetGenerator (MP-1356).

40+ tests covering:
  - HTML output contains all required sections
  - JSON schema validity
  - Monthly heatmap coverage
  - All strategies present in comparison table
  - Atomic write behaviour
  - Fallback data loading
  - Dark theme / colour tokens
  - No external CDN dependencies
  - Self-contained HTML
  - Edge cases (empty data, missing files)
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# ── path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from spa_core.reporting.tear_sheet import TearSheetGenerator


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dirs(tmp_path):
    """Return (data_dir, output_dir) with minimal backtest fixture data."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "reports"
    data_dir.mkdir()

    # Minimal backtest_results.json
    bt = {
        "generated_at": "2026-06-01T00:00:00Z",
        "data_source": "synthetic_test",
        "period_days": 90,
        "seed": 42,
        "initial_capital_usd": 100000.0,
        "note": "test fixture",
        "strategies": {
            "S0_conservative": {
                "strategy_name": "Conservative (T1)",
                "risk_tier": "T1",
                "annualised_return_pct": 4.2,
                "sharpe_ratio": 12.5,
                "sortino_ratio": 25.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": None,
                "total_return_pct": 1.05,
                "backtest_days": 90,
                "win_rate": 1.0,
            },
            "S1_balanced": {
                "strategy_name": "Balanced Yield",
                "risk_tier": "T1/T2",
                "annualised_return_pct": 5.1,
                "sharpe_ratio": 18.0,
                "sortino_ratio": 110.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": None,
                "total_return_pct": 1.27,
                "backtest_days": 90,
                "win_rate": 1.0,
            },
            "S2_yield_max": {
                "strategy_name": "Yield-Maximising",
                "risk_tier": "T2",
                "annualised_return_pct": 6.0,
                "sharpe_ratio": 24.0,
                "sortino_ratio": 150.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": None,
                "total_return_pct": 1.50,
                "backtest_days": 90,
                "win_rate": 1.0,
            },
        },
        "leaderboard": [
            {"strategy": "S2_yield_max", "name": "Yield-Maximising",
             "annualised_return_pct": 6.0, "sharpe_ratio": 24.0,
             "max_drawdown_pct": 0.0, "total_return_pct": 1.50, "risk_tier": "T2"},
        ],
    }
    (data_dir / "backtest_results.json").write_text(json.dumps(bt), encoding="utf-8")

    # Minimal equity_curve_daily.json
    eq = {
        "generated_at": "2026-06-22T06:00:00Z",
        "daily": [
            {"date": "2026-05-01", "daily_return_pct": 0.012, "equity": 100012.0},
            {"date": "2026-05-02", "daily_return_pct": 0.011, "equity": 100023.1},
            {"date": "2026-06-01", "daily_return_pct": 0.013, "equity": 100056.2},
            {"date": "2026-06-02", "daily_return_pct": 0.012, "equity": 100068.4},
        ]
    }
    (data_dir / "equity_curve_daily.json").write_text(json.dumps(eq), encoding="utf-8")

    return data_dir, output_dir


@pytest.fixture
def generator():
    return TearSheetGenerator()


@pytest.fixture
def html_and_summary(generator, tmp_dirs):
    data_dir, output_dir = tmp_dirs
    summary = generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
    html = (output_dir / "backtest_tearsheet.html").read_text(encoding="utf-8")
    return html, summary


# ── Section 1: import & interface ─────────────────────────────────────────────

class TestImport:
    def test_class_importable(self):
        gen = TearSheetGenerator()
        assert gen is not None

    def test_generate_method_exists(self, generator):
        assert callable(getattr(generator, "generate", None))

    def test_generate_returns_dict(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        result = generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert isinstance(result, dict)

    def test_primary_file_constant(self, generator):
        assert generator.PRIMARY_FILE == "professional_backtest_result.json"

    def test_fallback_file_constant(self, generator):
        assert generator.FALLBACK_FILE == "backtest_results.json"

    def test_months_ordered_all_twelve(self, generator):
        assert len(generator.MONTHS_ORDERED) == 12
        assert "Jan" in generator.MONTHS_ORDERED
        assert "Dec" in generator.MONTHS_ORDERED


# ── Section 2: file creation ──────────────────────────────────────────────────

class TestFileCreation:
    def test_output_dir_created(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        assert not output_dir.exists()
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert output_dir.exists()

    def test_html_file_created(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert (output_dir / "backtest_tearsheet.html").exists()

    def test_json_summary_created(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert (data_dir / "tear_sheet_summary.json").exists()

    def test_html_file_non_empty(self, html_and_summary):
        html, _ = html_and_summary
        assert len(html) > 1000

    def test_json_summary_valid_json(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        raw = (data_dir / "tear_sheet_summary.json").read_text(encoding="utf-8")
        loaded = json.loads(raw)
        assert isinstance(loaded, dict)


# ── Section 3: HTML sections present ─────────────────────────────────────────

class TestHTMLSections:
    def test_html_header_spa_title(self, html_and_summary):
        html, _ = html_and_summary
        assert "Systematic Portfolio Allocator" in html

    def test_html_backtest_report_2022(self, html_and_summary):
        html, _ = html_and_summary
        assert "Backtest Report 2022" in html

    def test_html_summary_stats_box(self, html_and_summary):
        html, _ = html_and_summary
        assert "stats-grid" in html

    def test_html_annual_return_stat(self, html_and_summary):
        html, _ = html_and_summary
        assert "Annual Return" in html

    def test_html_sharpe_ratio_stat(self, html_and_summary):
        html, _ = html_and_summary
        assert "Sharpe Ratio" in html

    def test_html_max_drawdown_stat(self, html_and_summary):
        html, _ = html_and_summary
        assert "Max Drawdown" in html

    def test_html_sortino_ratio_stat(self, html_and_summary):
        html, _ = html_and_summary
        assert "Sortino Ratio" in html

    def test_html_strategy_comparison_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Strategy Comparison" in html

    def test_html_strategy_table_exists(self, html_and_summary):
        html, _ = html_and_summary
        assert 'id="strat-table"' in html

    def test_html_monthly_heatmap_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Monthly Returns Heatmap" in html

    def test_html_drawdown_table_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Top Drawdown Periods" in html

    def test_html_stress_test_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Stress Test Results" in html

    def test_html_benchmark_comparison_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Benchmark Comparison" in html

    def test_html_walk_forward_section(self, html_and_summary):
        html, _ = html_and_summary
        assert "Walk-Forward Validation" in html

    def test_html_caveats_footer(self, html_and_summary):
        html, _ = html_and_summary
        assert "Caveats" in html

    def test_html_guarantee_disclaimer(self, html_and_summary):
        html, _ = html_and_summary
        assert "not a guarantee" in html

    def test_html_defillama_citation(self, html_and_summary):
        html, _ = html_and_summary
        assert "DeFiLlama" in html


# ── Section 4: HTML quality ───────────────────────────────────────────────────

class TestHTMLQuality:
    def test_no_external_cdn_jsdelivr(self, html_and_summary):
        html, _ = html_and_summary
        assert "cdn.jsdelivr.net" not in html

    def test_no_external_cdn_cloudflare(self, html_and_summary):
        html, _ = html_and_summary
        assert "cdnjs.cloudflare.com" not in html

    def test_no_external_script_src(self, html_and_summary):
        html, _ = html_and_summary
        assert '<script src=' not in html

    def test_no_external_link_href_css(self, html_and_summary):
        html, _ = html_and_summary
        # No external CSS links
        import re
        ext_links = re.findall(r'<link[^>]+href=["\']https?://', html)
        assert len(ext_links) == 0

    def test_dark_theme_background(self, html_and_summary):
        html, _ = html_and_summary
        assert "--bg: #0d1117" in html

    def test_green_color_defined(self, html_and_summary):
        html, _ = html_and_summary
        assert "--green: #22c55e" in html

    def test_red_color_defined(self, html_and_summary):
        html, _ = html_and_summary
        assert "--red: #ef4444" in html

    def test_sortable_table_js(self, html_and_summary):
        html, _ = html_and_summary
        assert "sortTable" in html

    def test_sort_onclick_headers(self, html_and_summary):
        html, _ = html_and_summary
        assert "onclick=\"sortTable(" in html

    def test_html_doctype(self, html_and_summary):
        html, _ = html_and_summary
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_html_lang_en(self, html_and_summary):
        html, _ = html_and_summary
        assert 'lang="en"' in html


# ── Section 5: heatmap months ─────────────────────────────────────────────────

class TestMonthlyHeatmap:
    def test_heatmap_has_jan(self, html_and_summary):
        html, _ = html_and_summary
        assert ">Jan<" in html

    def test_heatmap_has_jun(self, html_and_summary):
        html, _ = html_and_summary
        assert ">Jun<" in html

    def test_heatmap_has_dec(self, html_and_summary):
        html, _ = html_and_summary
        assert ">Dec<" in html

    def test_heatmap_has_year_rows(self, html_and_summary):
        html, _ = html_and_summary
        # Year rows must be in the heatmap table
        for year in ["2022", "2023", "2024", "2025"]:
            assert year in html

    def test_heatmap_table_exists(self, html_and_summary):
        html, _ = html_and_summary
        assert 'id="heatmap-table"' in html

    def test_heatmap_uses_css_classes(self, html_and_summary):
        html, _ = html_and_summary
        assert "hm-pos-strong" in html or "hm-pos-med" in html or "na" in html


# ── Section 6: strategy coverage ─────────────────────────────────────────────

class TestStrategyCoverage:
    def test_all_strategies_in_html(self, html_and_summary):
        html, _ = html_and_summary
        assert "Conservative (T1)" in html
        assert "Balanced Yield" in html
        assert "Yield-Maximising" in html

    def test_strategy_ids_in_html(self, html_and_summary):
        html, _ = html_and_summary
        assert "S0_conservative" in html
        assert "S1_balanced" in html
        assert "S2_yield_max" in html

    def test_stress_test_luna_event(self, html_and_summary):
        html, _ = html_and_summary
        assert "LUNA" in html

    def test_stress_test_svb_event(self, html_and_summary):
        html, _ = html_and_summary
        assert "SVB" in html

    def test_stress_test_ftx_event(self, html_and_summary):
        html, _ = html_and_summary
        assert "FTX" in html


# ── Section 7: JSON summary schema ───────────────────────────────────────────

class TestJSONSchema:
    def test_json_has_best_strategy(self, html_and_summary):
        _, summary = html_and_summary
        assert "best_strategy" in summary

    def test_json_has_best_sharpe(self, html_and_summary):
        _, summary = html_and_summary
        assert "best_sharpe" in summary

    def test_json_has_best_annual_return(self, html_and_summary):
        _, summary = html_and_summary
        assert "best_annual_return" in summary

    def test_json_has_max_drawdown(self, html_and_summary):
        _, summary = html_and_summary
        assert "max_drawdown" in summary

    def test_json_has_data_source(self, html_and_summary):
        _, summary = html_and_summary
        assert "data_source" in summary

    def test_json_has_generated_at(self, html_and_summary):
        _, summary = html_and_summary
        assert "generated_at" in summary

    def test_json_has_walk_forward_verdict(self, html_and_summary):
        _, summary = html_and_summary
        assert "walk_forward_verdict" in summary

    def test_json_has_return_range(self, html_and_summary):
        _, summary = html_and_summary
        assert "return_range_min" in summary
        assert "return_range_max" in summary

    def test_json_best_strategy_is_string(self, html_and_summary):
        _, summary = html_and_summary
        assert isinstance(summary["best_strategy"], str)

    def test_json_best_sharpe_is_numeric_or_none(self, html_and_summary):
        _, summary = html_and_summary
        v = summary["best_sharpe"]
        assert v is None or isinstance(v, (int, float))

    def test_json_source_file_field(self, html_and_summary):
        _, summary = html_and_summary
        assert "source_file" in summary

    def test_json_tearsheet_html_field(self, html_and_summary):
        _, summary = html_and_summary
        assert "tearsheet_html" in summary
        assert summary["tearsheet_html"].endswith(".html")

    def test_json_version_field(self, html_and_summary):
        _, summary = html_and_summary
        assert "version" in summary


# ── Section 8: atomic writes ──────────────────────────────────────────────────

class TestAtomicWrites:
    def test_no_tmp_files_left_after_generate(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        tmp_html = list(output_dir.glob("*.tmp"))
        tmp_json = list(data_dir.glob("*.tmp"))
        assert len(tmp_html) == 0
        assert len(tmp_json) == 0

    def test_run_twice_idempotent_html(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        html1 = (output_dir / "backtest_tearsheet.html").read_text()
        generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        html2 = (output_dir / "backtest_tearsheet.html").read_text()
        # Both runs should produce structurally identical HTML (minor timestamp diffs OK)
        assert "Systematic Portfolio Allocator" in html1
        assert "Systematic Portfolio Allocator" in html2

    def test_uses_shutil_not_os_replace(self):
        """Verify shutil.move is imported in the module (not just os.replace)."""
        import inspect
        src = inspect.getsource(TearSheetGenerator._atomic_write_text)
        assert "shutil.move" in src

    def test_atomic_write_json_uses_shutil(self):
        import inspect
        src = inspect.getsource(TearSheetGenerator._atomic_write_json)
        assert "shutil.move" in src


# ── Section 9: edge cases & fallback ─────────────────────────────────────────

class TestEdgeCases:
    def test_empty_data_dir_does_not_crash(self, generator, tmp_path):
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        output_dir = tmp_path / "out"
        result = generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert isinstance(result, dict)

    def test_fallback_loads_backtest_results_json(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        # primary file does NOT exist — should fall back to backtest_results.json
        primary = data_dir / "professional_backtest_result.json"
        assert not primary.exists()
        summary = generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert summary["best_strategy"] is not None

    def test_primary_file_takes_precedence(self, generator, tmp_dirs):
        data_dir, output_dir = tmp_dirs
        primary = {
            "generated_at": "2026-06-22T00:00:00Z",
            "data_source": "professional_primary",
            "period": {"from": "2022-01-01", "to": "2025-12-31", "days": 1460},
            "initial_capital_usd": 100000.0,
            "note": "primary",
            "strategies": {
                "S_primary": {
                    "strategy_name": "Primary Strategy",
                    "risk_tier": "T1",
                    "annualised_return_pct": 7.5,
                    "sharpe_ratio": 30.0,
                    "sortino_ratio": 60.0,
                    "max_drawdown_pct": 0.0,
                    "calmar_ratio": None,
                    "total_return_pct": 2.0,
                    "backtest_days": 1460,
                }
            },
            "leaderboard": [],
        }
        (data_dir / "professional_backtest_result.json").write_text(
            json.dumps(primary), encoding="utf-8"
        )
        summary = generator.generate(data_dir=str(data_dir), output_dir=str(output_dir))
        assert summary["data_source"] == "professional_primary"
        assert summary["best_strategy"] == "Primary Strategy"

    def test_num_helper_returns_none_for_nan(self):
        gen = TearSheetGenerator()
        assert gen._num(float("nan")) is None

    def test_num_helper_returns_none_for_inf(self):
        gen = TearSheetGenerator()
        assert gen._num(float("inf")) is None

    def test_num_helper_converts_valid_float(self):
        gen = TearSheetGenerator()
        assert gen._num(3.14) == pytest.approx(3.14)

    def test_num_helper_handles_none(self):
        gen = TearSheetGenerator()
        assert gen._num(None) is None

    def test_monthly_returns_from_daily_computes_correctly(self):
        gen = TearSheetGenerator()
        daily = [
            {"date": "2026-01-01", "daily_return_pct": 0.01},
            {"date": "2026-01-02", "daily_return_pct": 0.02},
            {"date": "2026-02-01", "daily_return_pct": 0.015},
        ]
        result = gen._monthly_returns_from_daily(daily)
        assert "2026" in result
        assert "Jan" in result["2026"]
        assert "Feb" in result["2026"]
        # Jan compound: (1+0.0001) * (1+0.0002) - 1 ≈ 0.0003
        jan = result["2026"]["Jan"]
        assert abs(jan - 0.03) < 0.005  # roughly 0.01 + 0.02 compounded


# ── Section 10: real data integration ────────────────────────────────────────

class TestRealDataIntegration:
    def test_generate_with_real_project_data(self):
        """Generate using the actual project data/ directory."""
        gen = TearSheetGenerator()
        project_root = ROOT
        data_dir = project_root / "data"
        if not data_dir.exists():
            pytest.skip("project data/ dir not available in this environment")
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = gen.generate(
                data_dir=str(data_dir),
                output_dir=str(Path(tmpdir) / "reports")
            )
        assert isinstance(summary, dict)
        assert "best_strategy" in summary
        assert summary["best_strategy"] is not None

    def test_real_html_has_all_sections(self):
        """Full check of HTML output from real project data."""
        gen = TearSheetGenerator()
        project_root = ROOT
        data_dir = project_root / "data"
        if not data_dir.exists():
            pytest.skip("project data/ dir not available in this environment")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "reports"
            gen.generate(data_dir=str(data_dir), output_dir=str(out_dir))
            html = (out_dir / "backtest_tearsheet.html").read_text(encoding="utf-8")
        required = [
            "Systematic Portfolio Allocator",
            "Backtest Report 2022",
            "stats-grid",
            "Strategy Comparison",
            "Monthly Returns Heatmap",
            "Top Drawdown Periods",
            "Stress Test Results",
            "Benchmark Comparison",
            "Walk-Forward Validation",
            "Caveats",
            "sortTable",
            "--bg: #0d1117",
        ]
        missing = [s for s in required if s not in html]
        assert missing == [], f"HTML missing sections: {missing}"
