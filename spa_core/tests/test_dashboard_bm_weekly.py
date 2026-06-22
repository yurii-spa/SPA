"""
MP-613 — Dashboard: Benchmark + Weekly Summary panels
Tests: 98 unit tests covering HTML structure, CSS classes, JS functions,
       JSON data schemas, night mode, mobile media, and security hygiene.

Run: python3 -m unittest spa_core.tests.test_dashboard_bm_weekly -v
"""

import json
import os
import unittest

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
INDEX_HTML = os.path.join(REPO_ROOT, 'index.html')
BENCHMARK_JSON = os.path.join(REPO_ROOT, 'data', 'benchmark_report.json')
WEEKLY_JSON = os.path.join(REPO_ROOT, 'data', 'weekly_summary.json')


# ── Helpers ────────────────────────────────────────────────────────────────
def _html() -> str:
    with open(INDEX_HTML, encoding='utf-8') as f:
        return f.read()


def _bm_data() -> dict:
    """Return the 'latest' benchmark snapshot (or top-level if flat)."""
    with open(BENCHMARK_JSON, encoding='utf-8') as f:
        raw = json.load(f)
    return raw.get('latest', raw)


def _wk_data() -> dict:
    """Return the latest weekly summary record."""
    with open(WEEKLY_JSON, encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        return raw.get('latest', raw)
    return raw[-1]  # ring-buffer array fallback


# ══════════════════════════════════════════════════════════════════════════
# 1. HTML structure (12 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestIndexHtmlStructure(unittest.TestCase):
    """index.html exists and contains required elements."""

    def test_01_file_exists(self):
        self.assertTrue(os.path.isfile(INDEX_HTML), "index.html must exist")

    def test_02_benchmark_panel_div(self):
        self.assertIn('id="benchmark-panel"', _html())

    def test_03_weekly_panel_div(self):
        self.assertIn('id="weekly-panel"', _html())

    def test_04_bm_row_mp613_class_used(self):
        self.assertIn('bm-row-mp613', _html())

    def test_05_wk_verdict_class_used(self):
        self.assertIn('wk-verdict', _html())

    def test_06_load_benchmark_panel_function(self):
        self.assertIn('async function loadBenchmarkPanel', _html())

    def test_07_load_weekly_panel_function(self):
        self.assertIn('async function loadWeeklyPanel', _html())

    def test_08_benchmark_panel_called_in_analytics(self):
        self.assertIn('loadBenchmarkPanel()', _html())

    def test_09_weekly_panel_called_in_analytics(self):
        self.assertIn('loadWeeklyPanel()', _html())

    def test_10_bm_panel_css_present(self):
        self.assertIn('.bm-panel', _html())

    def test_11_wk_stat_used(self):
        self.assertIn('wk-stat', _html())

    def test_12_benchmark_title_in_html(self):
        self.assertIn('Benchmark Comparison', _html())


# ══════════════════════════════════════════════════════════════════════════
# 2. Benchmark Panel CSS (10 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestBenchmarkPanelCSS(unittest.TestCase):
    """CSS classes for the Benchmark Panel are defined."""

    def test_01_bm_excess_positive(self):
        self.assertIn('.bm-excess.positive', _html())

    def test_02_bm_excess_negative(self):
        self.assertIn('.bm-excess.negative', _html())

    def test_03_bm_panel_class(self):
        self.assertIn('.bm-panel', _html())

    def test_04_bm_verdict_mp613_class(self):
        self.assertIn('.bm-verdict-mp613', _html())

    def test_05_bm_row_mp613_class(self):
        self.assertIn('.bm-row-mp613', _html())

    def test_06_bm_excess_has_border_radius(self):
        html = _html()
        idx = html.index('.bm-excess {')
        snippet = html[idx:idx + 200]
        self.assertIn('border-radius', snippet)

    def test_07_night_bm_row_defined(self):
        self.assertIn('body.night .bm-row-mp613', _html())

    def test_08_bm_name_mp613_class(self):
        self.assertIn('.bm-name-mp613', _html())

    def test_09_bm_apy_mp613_class(self):
        self.assertIn('.bm-apy-mp613', _html())

    def test_10_bm_excess_positive_green_color(self):
        html = _html()
        idx = html.index('.bm-excess.positive')
        snippet = html[idx:idx + 200]
        is_green = (
            '#16a34a' in snippet or
            '#00c864' in snippet or
            'rgba(0,200,100' in snippet or
            '4ade80' in snippet
        )
        self.assertTrue(is_green, "positive excess should use a green color")


# ══════════════════════════════════════════════════════════════════════════
# 3. Weekly Summary Panel CSS (10 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestWeeklyPanelCSS(unittest.TestCase):
    """CSS classes for the Weekly Summary Panel are defined."""

    def test_01_wk_verdict_excellent(self):
        self.assertIn('.wk-verdict.excellent', _html())

    def test_02_wk_verdict_good(self):
        self.assertIn('.wk-verdict.good', _html())

    def test_03_wk_verdict_fair(self):
        self.assertIn('.wk-verdict.fair', _html())

    def test_04_wk_verdict_poor(self):
        self.assertIn('.wk-verdict.poor', _html())

    def test_05_wk_stat_class(self):
        self.assertIn('.wk-stat {', _html())

    def test_06_wk_grid_class(self):
        self.assertIn('.wk-grid', _html())

    def test_07_wk_stat_val_class(self):
        self.assertIn('.wk-stat-val', _html())

    def test_08_wk_stat_label_class(self):
        self.assertIn('.wk-stat-label', _html())

    def test_09_wk_panel_class(self):
        self.assertIn('.wk-panel', _html())

    def test_10_weekly_title_in_html(self):
        self.assertIn('Weekly Summary', _html())


# ══════════════════════════════════════════════════════════════════════════
# 4. benchmark_report.json data structure (20 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestBenchmarkDataStructure(unittest.TestCase):
    """data/benchmark_report.json matches expected schema."""

    def test_01_file_exists(self):
        self.assertTrue(os.path.isfile(BENCHMARK_JSON))

    def test_02_valid_json(self):
        with open(BENCHMARK_JSON, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_03_has_latest_or_benchmarks_key(self):
        with open(BENCHMARK_JSON, encoding='utf-8') as f:
            raw = json.load(f)
        self.assertTrue('latest' in raw or 'benchmarks' in raw)

    def test_04_latest_has_benchmarks(self):
        d = _bm_data()
        self.assertIn('benchmarks', d)

    def test_05_benchmarks_is_list(self):
        d = _bm_data()
        self.assertIsInstance(d['benchmarks'], list)

    def test_06_has_verdict_field(self):
        d = _bm_data()
        self.assertIn('verdict', d)

    def test_07_verdict_is_string(self):
        d = _bm_data()
        self.assertIsInstance(d['verdict'], str)

    def test_08_verdict_is_valid_value(self):
        d = _bm_data()
        self.assertIn(d['verdict'], {'ALPHA+', 'ALPHA', 'BENCHMARK', 'LAGGING'})

    def test_09_has_portfolio_apy_pct(self):
        d = _bm_data()
        self.assertIn('portfolio_apy_pct', d)

    def test_10_portfolio_apy_pct_is_numeric(self):
        d = _bm_data()
        self.assertIsInstance(d['portfolio_apy_pct'], (int, float))

    def test_11_portfolio_apy_pct_positive(self):
        d = _bm_data()
        self.assertGreater(d['portfolio_apy_pct'], 0)

    def test_12_has_annual_alpha_usd(self):
        d = _bm_data()
        self.assertIn('annual_alpha_usd', d)

    def test_13_annual_alpha_usd_is_numeric(self):
        d = _bm_data()
        self.assertIsInstance(d['annual_alpha_usd'], (int, float))

    def test_14_benchmarks_nonempty(self):
        d = _bm_data()
        self.assertGreater(len(d['benchmarks']), 0)

    def test_15_benchmark_item_has_name(self):
        d = _bm_data()
        self.assertIn('name', d['benchmarks'][0])

    def test_16_benchmark_item_has_apy_pct(self):
        d = _bm_data()
        self.assertIn('apy_pct', d['benchmarks'][0])

    def test_17_benchmark_item_has_excess_return_pct(self):
        d = _bm_data()
        self.assertIn('excess_return_pct', d['benchmarks'][0])

    def test_18_benchmark_item_has_portfolio_apy_pct(self):
        d = _bm_data()
        self.assertIn('portfolio_apy_pct', d['benchmarks'][0])

    def test_19_benchmark_item_has_outperforming(self):
        d = _bm_data()
        self.assertIn('outperforming', d['benchmarks'][0])

    def test_20_outperforming_is_bool(self):
        d = _bm_data()
        self.assertIsInstance(d['benchmarks'][0]['outperforming'], bool)


# ══════════════════════════════════════════════════════════════════════════
# 5. weekly_summary.json data structure (20 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestWeeklyDataStructure(unittest.TestCase):
    """data/weekly_summary.json matches expected schema."""

    def test_01_file_exists(self):
        self.assertTrue(os.path.isfile(WEEKLY_JSON))

    def test_02_valid_json(self):
        with open(WEEKLY_JSON, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIsInstance(data, (dict, list))

    def test_03_has_latest_or_is_list(self):
        with open(WEEKLY_JSON, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            self.assertIn('latest', raw)
        else:
            self.assertIsInstance(raw, list)

    def test_04_has_weekly_verdict(self):
        d = _wk_data()
        self.assertIn('weekly_verdict', d)

    def test_05_weekly_verdict_is_string(self):
        d = _wk_data()
        self.assertIsInstance(d['weekly_verdict'], str)

    def test_06_weekly_verdict_valid_value(self):
        d = _wk_data()
        self.assertIn(d['weekly_verdict'], {'EXCELLENT', 'GOOD', 'FAIR', 'POOR'})

    def test_07_has_days_covered(self):
        d = _wk_data()
        self.assertIn('days_covered', d)

    def test_08_days_covered_is_int(self):
        d = _wk_data()
        self.assertIsInstance(d['days_covered'], int)

    def test_09_has_apy_stats(self):
        d = _wk_data()
        self.assertIn('apy_stats', d)

    def test_10_apy_stats_has_avg(self):
        d = _wk_data()
        self.assertIn('avg', d['apy_stats'])

    def test_11_apy_stats_avg_is_numeric(self):
        d = _wk_data()
        self.assertIsInstance(d['apy_stats']['avg'], (int, float))

    def test_12_apy_stats_has_min(self):
        d = _wk_data()
        self.assertIn('min', d['apy_stats'])

    def test_13_apy_stats_has_max(self):
        d = _wk_data()
        self.assertIn('max', d['apy_stats'])

    def test_14_apy_stats_has_trend(self):
        d = _wk_data()
        self.assertIn('trend', d['apy_stats'])

    def test_15_apy_stats_trend_is_valid(self):
        d = _wk_data()
        self.assertIn(d['apy_stats']['trend'], {'RISING', 'FALLING', 'STABLE'})

    def test_16_has_operational_days(self):
        d = _wk_data()
        self.assertIn('operational_days', d)

    def test_17_operational_days_is_int(self):
        d = _wk_data()
        self.assertIsInstance(d['operational_days'], int)

    def test_18_has_top_chain_this_week(self):
        d = _wk_data()
        self.assertIn('top_chain_this_week', d)

    def test_19_top_chain_is_string(self):
        d = _wk_data()
        self.assertIsInstance(d['top_chain_this_week'], str)

    def test_20_has_summary_line(self):
        d = _wk_data()
        self.assertIn('summary_line', d)


# ══════════════════════════════════════════════════════════════════════════
# 6. Night mode CSS (6 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestNightModeCSS(unittest.TestCase):
    """Night mode overrides are defined and do not conflict."""

    def test_01_night_bm_row_mp613(self):
        self.assertIn('body.night .bm-row-mp613', _html())

    def test_02_night_wk_stat(self):
        self.assertIn('body.night .wk-stat', _html())

    def test_03_night_bm_excess_positive(self):
        self.assertIn('body.night .bm-excess.positive', _html())

    def test_04_night_bm_excess_negative(self):
        self.assertIn('body.night .bm-excess.negative', _html())

    def test_05_night_wk_stat_val(self):
        self.assertIn('body.night .wk-stat-val', _html())

    def test_06_night_bm_verdict_mp613(self):
        self.assertIn('body.night .bm-verdict-mp613', _html())


# ══════════════════════════════════════════════════════════════════════════
# 7. Mobile media query (5 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestMobileMedia(unittest.TestCase):
    """@media (max-width:480px) block covers both new panel classes."""

    @staticmethod
    def _media_480_snippet(html: str) -> str:
        idx = html.find('@media (max-width:480px)')
        if idx == -1:
            return ''
        return html[idx:idx + 400]

    def test_01_media_480px_present(self):
        self.assertIn('@media (max-width:480px)', _html())

    def test_02_bm_row_mp613_in_media(self):
        self.assertIn('bm-row-mp613', self._media_480_snippet(_html()))

    def test_03_wk_stat_in_media(self):
        self.assertIn('wk-stat', self._media_480_snippet(_html()))

    def test_04_flex_wrap_in_media(self):
        self.assertIn('flex-wrap', self._media_480_snippet(_html()))

    def test_05_wk_stat_val_in_media(self):
        self.assertIn('wk-stat-val', self._media_480_snippet(_html()))


# ══════════════════════════════════════════════════════════════════════════
# 8. No hardcoded secrets (5 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestNoHardcodedTokens(unittest.TestCase):
    """No API tokens or credentials embedded in index.html."""

    def test_01_no_ghp_prefix(self):
        self.assertNotIn('ghp_', _html())

    def test_02_no_bearer_token_pattern(self):
        # Bearer followed by 20+ alphanumeric chars = hardcoded token
        self.assertNotRegex(_html(), r'Bearer\s+[A-Za-z0-9_\-]{20,}')

    def test_03_no_api_github_in_panel_fns(self):
        html = _html()
        start = html.find('async function loadBenchmarkPanel')
        end = html.find('// ── Advanced Portfolio Stats', start)
        self.assertNotIn('api.github', html[start:end])

    def test_04_no_github_pat_value(self):
        # No embedded PAT value (lowercase check)
        self.assertNotRegex(_html().lower(), r'github[_\-]pat[_\-][a-z0-9]{30,}')

    def test_05_no_api_github_com(self):
        self.assertNotIn('api.github.com', _html())


# ══════════════════════════════════════════════════════════════════════════
# 9. JS function implementation details (10 tests)
# ══════════════════════════════════════════════════════════════════════════
class TestJsFunctions(unittest.TestCase):
    """JS functions fetch correct files, handle .latest, and defer correctly."""

    def test_01_benchmark_fetches_correct_file(self):
        self.assertIn("'data/benchmark_report.json'", _html())

    def test_02_weekly_fetches_correct_file(self):
        self.assertIn("'data/weekly_summary.json'", _html())

    def test_03_benchmark_accesses_raw_latest(self):
        html = _html()
        idx = html.find('async function loadBenchmarkPanel')
        snippet = html[idx:idx + 600]
        self.assertIn('raw.latest', snippet)

    def test_04_weekly_accesses_raw_latest(self):
        html = _html()
        idx = html.find('async function loadWeeklyPanel')
        snippet = html[idx:idx + 600]
        self.assertIn('raw.latest', snippet)

    def test_05_verdict_emoji_map_has_alpha_plus(self):
        self.assertIn("'ALPHA+'", _html())

    def test_06_verdict_emoji_map_has_lagging(self):
        self.assertIn("'LAGGING'", _html())

    def test_07_trend_arrow_map_present(self):
        html = _html()
        self.assertIn("'RISING'", html)
        self.assertIn("'FALLING'", html)
        self.assertIn("'STABLE'", html)

    def test_08_benchmark_uses_no_store_on_force(self):
        html = _html()
        idx = html.find('async function loadBenchmarkPanel')
        snippet = html[idx:idx + 500]
        self.assertIn('no-store', snippet)

    def test_09_benchmark_has_error_handler(self):
        html = _html()
        idx = html.find('async function loadBenchmarkPanel')
        end = html.find('async function loadWeeklyPanel', idx)
        snippet = html[idx:end]
        self.assertIn('catch', snippet)
        self.assertIn('unavailable', snippet.lower())

    def test_10_both_deferred_in_load_analytics(self):
        html = _html()
        start = html.find('async function loadAnalytics()')
        # loadAnalytics closes with the catch block — find the closing brace
        end = html.find('// ── MP-613: Benchmark Panel', start)
        body = html[start:end]
        self.assertIn('loadBenchmarkPanel', body)
        self.assertIn('loadWeeklyPanel', body)
        # Also verify they're inside _defer calls
        self.assertIn('_defer(() => { loadBenchmarkPanel()', body)
        self.assertIn('_defer(() => { loadWeeklyPanel()', body)


if __name__ == '__main__':
    unittest.main()
