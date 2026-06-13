"""
test_dashboard_ce_forecast.py — MP-618
Dashboard v3.4: Capital Efficiency + Yield Forecast panels.

Coverage:
  TestIndexHtmlStructure      (12) — div ids, JS functions, CSS classes, grade variants
  TestCapitalEfficiencyDataStructure (20) — data/capital_efficiency.json schema & values
  TestForecastDataStructure   (20) — data/yield_forecast.json schema & values
  TestNightModeCSS             (5) — body.night overrides
  TestMobileMedia              (5) — @media (max-width:480px)
  TestLoadAnalyticsCalls       (8) — functions called via _defer in loadAnalytics()
  TestNoHardcodedTokens        (5) — no leaked credentials
  TestReloadButtons            (5) — onclick attributes present in HTML

Total: 80 tests
Run: python3 -m unittest spa_core.tests.test_dashboard_ce_forecast -v
"""

import json
import os
import re
import unittest

# Resolve paths relative to repo root
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
_INDEX = os.path.join(_REPO, 'index.html')
_CE_JSON = os.path.join(_REPO, 'data', 'capital_efficiency.json')
_FC_JSON = os.path.join(_REPO, 'data', 'yield_forecast.json')


def _html() -> str:
    """Read index.html once; cached on first call."""
    if not hasattr(_html, '_cache'):
        with open(_INDEX, encoding='utf-8') as fh:
            _html._cache = fh.read()
    return _html._cache


def _ce() -> dict:
    """Return the `latest` record from capital_efficiency.json."""
    if not hasattr(_ce, '_cache'):
        with open(_CE_JSON, encoding='utf-8') as fh:
            raw = json.load(fh)
        _ce._cache = raw.get('latest', raw) if isinstance(raw, dict) else raw[-1]
    return _ce._cache


def _fc() -> dict:
    """Return the `latest` record from yield_forecast.json."""
    if not hasattr(_fc, '_cache'):
        with open(_FC_JSON, encoding='utf-8') as fh:
            raw = json.load(fh)
        _fc._cache = raw.get('latest', raw) if isinstance(raw, dict) else raw[-1]
    return _fc._cache


def _analytics_body() -> str:
    """Extract the body of the loadAnalytics function from index.html."""
    html = _html()
    m = re.search(r'async function loadAnalytics\(\)(.*?)^}', html,
                  re.DOTALL | re.MULTILINE)
    return m.group(0) if m else ''


# ─── TestIndexHtmlStructure (12) ─────────────────────────────────────────────

class TestIndexHtmlStructure(unittest.TestCase):
    """Verify the structural additions to index.html are present."""

    def test_index_html_exists(self):
        self.assertTrue(os.path.isfile(_INDEX), 'index.html not found')

    def test_capital_efficiency_panel_div(self):
        self.assertIn('id="capital-efficiency-panel"', _html())

    def test_forecast_panel_div(self):
        self.assertIn('id="forecast-panel"', _html())

    def test_load_capital_efficiency_panel_function_defined(self):
        self.assertIn('async function loadCapitalEfficiencyPanel', _html())

    def test_load_forecast_panel_function_defined(self):
        self.assertIn('async function loadForecastPanel', _html())

    def test_ce_grade_css_class(self):
        self.assertIn('.ce-grade', _html())

    def test_ce_bar_css_class(self):
        self.assertIn('.ce-bar', _html())

    def test_fc_disclaimer_css_class(self):
        self.assertIn('.fc-disclaimer', _html())

    def test_fc_row_css_class(self):
        self.assertIn('.fc-row', _html())

    def test_grade_a_class_present(self):
        self.assertIn('grade-a', _html())

    def test_grade_b_class_present(self):
        self.assertIn('grade-b', _html())

    def test_grade_c_class_present(self):
        self.assertIn('grade-c', _html())

    def test_grade_d_class_present(self):
        self.assertIn('grade-d', _html())


# ─── TestCapitalEfficiencyDataStructure (20) ─────────────────────────────────

class TestCapitalEfficiencyDataStructure(unittest.TestCase):
    """Verify data/capital_efficiency.json schema and value constraints."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_CE_JSON))

    def test_is_valid_json(self):
        with open(_CE_JSON) as f:
            data = json.load(f)
        self.assertIsNotNone(data)

    def test_has_overall_grade(self):
        self.assertIn('overall_grade', _ce())

    def test_overall_grade_is_string(self):
        self.assertIsInstance(_ce()['overall_grade'], str)

    def test_overall_grade_valid_value(self):
        self.assertIn(_ce()['overall_grade'].upper(), ('A', 'B', 'C', 'D'))

    def test_has_deployment_rate_pct(self):
        self.assertIn('deployment_rate_pct', _ce())

    def test_deployment_rate_pct_is_numeric(self):
        self.assertIsInstance(_ce()['deployment_rate_pct'], (int, float))

    def test_deployment_rate_pct_in_range(self):
        v = _ce()['deployment_rate_pct']
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_has_portfolio_raroc(self):
        self.assertIn('portfolio_raroc', _ce())

    def test_portfolio_raroc_is_numeric(self):
        self.assertIsInstance(_ce()['portfolio_raroc'], (int, float))

    def test_has_idle_opportunity_cost_daily(self):
        self.assertIn('idle_opportunity_cost_daily', _ce())

    def test_idle_opportunity_cost_daily_is_numeric(self):
        self.assertIsInstance(_ce()['idle_opportunity_cost_daily'], (int, float))

    def test_has_deployed_capital_usd(self):
        self.assertIn('deployed_capital_usd', _ce())

    def test_deployed_capital_usd_is_numeric(self):
        self.assertIsInstance(_ce()['deployed_capital_usd'], (int, float))

    def test_has_total_capital_usd(self):
        self.assertIn('total_capital_usd', _ce())

    def test_total_capital_usd_is_numeric(self):
        self.assertIsInstance(_ce()['total_capital_usd'], (int, float))

    def test_has_summary(self):
        self.assertIn('summary', _ce())

    def test_summary_is_string(self):
        self.assertIsInstance(_ce()['summary'], str)

    def test_has_adapters(self):
        self.assertIn('adapters', _ce())

    def test_adapters_is_list(self):
        self.assertIsInstance(_ce()['adapters'], list)

    def test_total_capital_positive(self):
        self.assertGreater(_ce()['total_capital_usd'], 0)


# ─── TestForecastDataStructure (20) ──────────────────────────────────────────

class TestForecastDataStructure(unittest.TestCase):
    """Verify data/yield_forecast.json schema and value constraints."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_FC_JSON))

    def test_is_valid_json(self):
        with open(_FC_JSON) as f:
            data = json.load(f)
        self.assertIsNotNone(data)

    def test_has_portfolio_current_apy(self):
        self.assertIn('portfolio_current_apy', _fc())

    def test_portfolio_current_apy_is_numeric(self):
        self.assertIsInstance(_fc()['portfolio_current_apy'], (int, float))

    def test_has_portfolio_forecast_1d(self):
        self.assertIn('portfolio_forecast_1d', _fc())

    def test_portfolio_forecast_1d_is_numeric(self):
        self.assertIsInstance(_fc()['portfolio_forecast_1d'], (int, float))

    def test_has_portfolio_forecast_7d(self):
        self.assertIn('portfolio_forecast_7d', _fc())

    def test_portfolio_forecast_7d_is_numeric(self):
        self.assertIsInstance(_fc()['portfolio_forecast_7d'], (int, float))

    def test_has_portfolio_forecast_30d(self):
        self.assertIn('portfolio_forecast_30d', _fc())

    def test_portfolio_forecast_30d_is_numeric(self):
        self.assertIsInstance(_fc()['portfolio_forecast_30d'], (int, float))

    def test_has_portfolio_trend(self):
        self.assertIn('portfolio_trend', _fc())

    def test_portfolio_trend_valid_value(self):
        self.assertIn(_fc()['portfolio_trend'], ('RISING', 'FALLING', 'STABLE'))

    def test_has_high_confidence_count(self):
        self.assertIn('high_confidence_count', _fc())

    def test_high_confidence_count_is_int(self):
        self.assertIsInstance(_fc()['high_confidence_count'], int)

    def test_high_confidence_count_non_negative(self):
        self.assertGreaterEqual(_fc()['high_confidence_count'], 0)

    def test_has_disclaimer(self):
        self.assertIn('disclaimer', _fc())

    def test_disclaimer_is_string(self):
        self.assertIsInstance(_fc()['disclaimer'], str)

    def test_disclaimer_non_empty(self):
        self.assertTrue(len(_fc()['disclaimer']) > 0)

    def test_top_level_schema_version(self):
        with open(_FC_JSON) as f:
            raw = json.load(f)
        self.assertIn('schema_version', raw)

    def test_top_level_source_field(self):
        with open(_FC_JSON) as f:
            raw = json.load(f)
        self.assertIn('source', raw)

    def test_source_value(self):
        with open(_FC_JSON) as f:
            raw = json.load(f)
        self.assertEqual(raw['source'], 'yield_forecast_engine')


# ─── TestNightModeCSS (5) ────────────────────────────────────────────────────

class TestNightModeCSS(unittest.TestCase):
    """Verify body.night overrides exist for new CE and FC panels."""

    def test_night_ce_metric_override(self):
        self.assertIn('body.night .ce-metric', _html())

    def test_night_ce_bar_override(self):
        self.assertIn('body.night .ce-bar', _html())

    def test_night_ce_metric_val_override(self):
        self.assertIn('body.night .ce-metric-val', _html())

    def test_night_fc_val_override(self):
        self.assertIn('body.night .fc-val', _html())

    def test_night_fc_disclaimer_override(self):
        self.assertIn('body.night .fc-disclaimer', _html())


# ─── TestMobileMedia (5) ─────────────────────────────────────────────────────

class TestMobileMedia(unittest.TestCase):
    """Verify @media (max-width:480px) responsive rules for new panels."""

    def _media_blocks(self):
        """Extract bodies of all @media (max-width:480px) blocks, handling nested {}."""
        html = _html()
        results = []
        for m in re.finditer(r'@media\s*\(max-width\s*:\s*480px\)\s*\{', html):
            start, depth, pos = m.end(), 1, m.end()
            while pos < len(html) and depth > 0:
                if html[pos] == '{':
                    depth += 1
                elif html[pos] == '}':
                    depth -= 1
                pos += 1
            results.append(html[start:pos - 1])
        return results

    def test_media_480px_block_exists(self):
        self.assertTrue(len(self._media_blocks()) >= 1,
                        '@media (max-width:480px) block not found')

    def test_ce_metric_in_media_block(self):
        combined = ' '.join(self._media_blocks())
        self.assertIn('ce-metric', combined)

    def test_fc_val_in_media_block(self):
        combined = ' '.join(self._media_blocks())
        self.assertIn('fc-val', combined)

    def test_media_block_has_min_width_rule(self):
        combined = ' '.join(self._media_blocks())
        self.assertIn('min-width', combined)

    def test_media_block_has_font_size_rule(self):
        combined = ' '.join(self._media_blocks())
        self.assertIn('font-size', combined)


# ─── TestLoadAnalyticsCalls (8) ──────────────────────────────────────────────

class TestLoadAnalyticsCalls(unittest.TestCase):
    """Verify both functions are called (via _defer) inside loadAnalytics()."""

    def test_load_capital_efficiency_panel_called(self):
        body = _analytics_body()
        self.assertIn('loadCapitalEfficiencyPanel', body)

    def test_load_forecast_panel_called(self):
        body = _analytics_body()
        self.assertIn('loadForecastPanel', body)

    def test_both_present_in_analytics_body(self):
        body = _analytics_body()
        self.assertIn('loadCapitalEfficiencyPanel', body)
        self.assertIn('loadForecastPanel', body)

    def test_capital_efficiency_called_via_defer(self):
        body = _analytics_body()
        self.assertIn('_defer(() => { loadCapitalEfficiencyPanel', body)

    def test_forecast_panel_called_via_defer(self):
        body = _analytics_body()
        self.assertIn('_defer(() => { loadForecastPanel', body)

    def test_mp618_comment_in_analytics(self):
        body = _analytics_body()
        self.assertIn('MP-618', body)

    def test_capital_efficiency_after_weekly_panel(self):
        body = _analytics_body()
        pos_weekly = body.find('loadWeeklyPanel')
        pos_ce = body.find('loadCapitalEfficiencyPanel')
        self.assertGreater(pos_ce, pos_weekly,
                           'loadCapitalEfficiencyPanel should appear after loadWeeklyPanel')

    def test_forecast_after_capital_efficiency(self):
        body = _analytics_body()
        pos_ce = body.find('loadCapitalEfficiencyPanel')
        pos_fc = body.find('loadForecastPanel')
        self.assertGreater(pos_fc, pos_ce,
                           'loadForecastPanel should appear after loadCapitalEfficiencyPanel')


# ─── TestNoHardcodedTokens (5) ───────────────────────────────────────────────

class TestNoHardcodedTokens(unittest.TestCase):
    """Verify no credentials are embedded in index.html."""

    def test_no_ghp_token(self):
        self.assertNotIn('ghp_', _html())

    def test_no_bearer_token(self):
        # Reject 'Bearer ' followed immediately by a non-space token-looking string
        self.assertIsNone(re.search(r'Bearer [A-Za-z0-9+/=]{8,}', _html()))

    def test_no_api_github_com(self):
        self.assertNotIn('api.github.com', _html())

    def test_no_raw_pat_assignment(self):
        # Match patterns like PAT="..." or pat='...'
        self.assertIsNone(re.search(r'PAT\s*=\s*["\'][A-Za-z0-9_]+["\']', _html()))

    def test_no_hardcoded_password(self):
        self.assertIsNone(re.search(r'password\s*=\s*["\'][^"\']+["\']',
                                    _html(), re.IGNORECASE))


# ─── TestReloadButtons (5) ───────────────────────────────────────────────────

class TestReloadButtons(unittest.TestCase):
    """Verify the reload/refresh buttons use the correct onclick handlers."""

    def test_capital_efficiency_reload_onclick(self):
        self.assertIn('onclick="loadCapitalEfficiencyPanel(true)"', _html())

    def test_forecast_reload_onclick(self):
        self.assertIn('onclick="loadForecastPanel(true)"', _html())

    def test_capital_efficiency_button_is_refresh_btn(self):
        # The button with CE onclick should also carry the refresh-btn class
        pattern = r'<button[^>]*class="refresh-btn"[^>]*onclick="loadCapitalEfficiencyPanel\(true\)"'
        self.assertIsNotNone(re.search(pattern, _html()))

    def test_forecast_button_is_refresh_btn(self):
        pattern = r'<button[^>]*class="refresh-btn"[^>]*onclick="loadForecastPanel\(true\)"'
        self.assertIsNotNone(re.search(pattern, _html()))

    def test_both_reload_buttons_present(self):
        self.assertIn('onclick="loadCapitalEfficiencyPanel(true)"', _html())
        self.assertIn('onclick="loadForecastPanel(true)"', _html())


if __name__ == '__main__':
    unittest.main()
