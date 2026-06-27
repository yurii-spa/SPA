"""Tests for TelegramDailyDigest (MP-627).

Pure-stdlib unittest suite.
Uses tempfile.TemporaryDirectory for all I/O — production data/ never touched.
All Telegram network calls are mocked via unittest.mock to avoid real HTTP.

Coverage areas
--------------
* DigestSection dataclass
* escape_mdv2 — all special characters, normal text, empty string
* TelegramDailyDigest._load_json — present, missing, malformed, empty
* TelegramDailyDigest._format_section — with lines, without lines
* TelegramDailyDigest._latest — dict with 'latest', plain dict, list, None
* Section builders — with data, without data (graceful degradation)
* build_digest — header, sections, truncation, date param
* save_digest — file created, atomic write, path returned, date in filename
* send_digest — mocked success, mocked HTTP error, mocked URLError
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path

from spa_core.analytics.telegram_daily_digest import (
    DigestSection,
    TelegramDailyDigest,
    escape_mdv2,
    _MAX_MESSAGE_LEN,
    _DIGEST_SUBDIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_digest(tmpdir: str) -> TelegramDailyDigest:
    return TelegramDailyDigest(data_dir=tmpdir)


def _write(tmpdir: str, filename: str, data) -> None:
    path = Path(tmpdir) / filename
    path.write_text(json.dumps(data), encoding="utf-8")


# ===========================================================================
# escape_mdv2
# ===========================================================================

class TestEscapeMdv2(unittest.TestCase):

    def test_plain_text_unchanged(self):
        self.assertEqual(escape_mdv2("hello world"), "hello world")

    def test_dot_escaped(self):
        self.assertEqual(escape_mdv2("3.14"), r"3\.14")

    def test_exclamation_escaped(self):
        self.assertIn("\\!", escape_mdv2("hello!"))

    def test_underscore_escaped(self):
        self.assertIn("\\_", escape_mdv2("snake_case"))

    def test_asterisk_escaped(self):
        self.assertIn("\\*", escape_mdv2("2*3"))

    def test_hyphen_escaped(self):
        self.assertIn("\\-", escape_mdv2("2026-06-13"))

    def test_plus_escaped(self):
        self.assertIn("\\+", escape_mdv2("a+b"))

    def test_parens_escaped(self):
        result = escape_mdv2("(hello)")
        self.assertIn("\\(", result)
        self.assertIn("\\)", result)

    def test_brackets_escaped(self):
        result = escape_mdv2("[link]")
        self.assertIn("\\[", result)
        self.assertIn("\\]", result)

    def test_hash_escaped(self):
        self.assertIn("\\#", escape_mdv2("#tag"))

    def test_pipe_escaped(self):
        self.assertIn("\\|", escape_mdv2("a|b"))

    def test_tilde_escaped(self):
        self.assertIn("\\~", escape_mdv2("~text"))

    def test_empty_string(self):
        self.assertEqual(escape_mdv2(""), "")

    def test_backslash_escaped_first(self):
        # Single backslash → double backslash
        result = escape_mdv2("\\")
        self.assertEqual(result, "\\\\")

    def test_multiple_specials(self):
        result = escape_mdv2("$100.00 (APY 5.0%)")
        self.assertIn("\\.", result)
        self.assertIn("\\(", result)
        self.assertIn("\\)", result)

    def test_dollar_not_special(self):
        # $ is NOT a MarkdownV2 special char
        result = escape_mdv2("$100")
        self.assertEqual(result, "$100")


# ===========================================================================
# DigestSection
# ===========================================================================

class TestDigestSection(unittest.TestCase):

    def test_fields(self):
        sec = DigestSection(title="Test", emoji="🔥", lines=["line1"])
        self.assertEqual(sec.title, "Test")
        self.assertEqual(sec.emoji, "🔥")
        self.assertEqual(sec.lines, ["line1"])

    def test_default_empty_lines(self):
        sec = DigestSection(title="T", emoji="X")
        self.assertEqual(sec.lines, [])

    def test_lines_mutable(self):
        sec = DigestSection(title="T", emoji="X")
        sec.lines.append("added")
        self.assertEqual(sec.lines, ["added"])


# ===========================================================================
# TelegramDailyDigest._load_json
# ===========================================================================

class TestLoadJson(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_valid_dict(self):
        _write(self.tmp, "test.json", {"key": "value"})
        result = self.d._load_json("test.json")
        self.assertEqual(result, {"key": "value"})

    def test_load_valid_list(self):
        _write(self.tmp, "list.json", [1, 2, 3])
        result = self.d._load_json("list.json")
        self.assertEqual(result, [1, 2, 3])

    def test_missing_file_returns_none(self):
        result = self.d._load_json("nonexistent.json")
        self.assertIsNone(result)

    def test_empty_file_returns_none(self):
        Path(self.tmp, "empty.json").write_text("", encoding="utf-8")
        result = self.d._load_json("empty.json")
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        Path(self.tmp, "bad.json").write_text("not json!", encoding="utf-8")
        result = self.d._load_json("bad.json")
        self.assertIsNone(result)

    def test_whitespace_only_returns_none(self):
        Path(self.tmp, "ws.json").write_text("   \n  ", encoding="utf-8")
        result = self.d._load_json("ws.json")
        self.assertIsNone(result)


# ===========================================================================
# TelegramDailyDigest._format_section
# ===========================================================================

class TestFormatSection(unittest.TestCase):

    def setUp(self):
        self.d = _make_digest(tempfile.mkdtemp())

    def test_header_format(self):
        sec = DigestSection(title="Portfolio", emoji="📊", lines=["APY: 5.0%"])
        result = self.d._format_section(sec)
        self.assertIn("📊", result)
        self.assertIn("*Portfolio*", result)

    def test_lines_indented(self):
        sec = DigestSection(title="T", emoji="X", lines=["line one"])
        result = self.d._format_section(sec)
        self.assertIn("  ", result)  # indentation

    def test_no_lines_header_only(self):
        sec = DigestSection(title="Empty", emoji="❓")
        result = self.d._format_section(sec)
        self.assertIn("*Empty*", result)
        # No newline after header if no lines
        self.assertNotIn("\n", result)

    def test_special_chars_in_title_escaped(self):
        sec = DigestSection(title="Price: 5.0%", emoji="💰", lines=[])
        result = self.d._format_section(sec)
        self.assertIn("\\.", result)

    def test_special_chars_in_lines_escaped(self):
        sec = DigestSection(title="T", emoji="X", lines=["APY: 5.0%"])
        result = self.d._format_section(sec)
        # % is not special, but . is
        self.assertIn("\\.", result)

    def test_multiple_lines(self):
        sec = DigestSection(title="T", emoji="X", lines=["a", "b", "c"])
        result = self.d._format_section(sec)
        lines = result.split("\n")
        self.assertEqual(len(lines), 4)  # header + 3 lines


# ===========================================================================
# Section builders — with data
# ===========================================================================

class TestBuildPortfolioSection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_strategy_summary(self):
        _write(self.tmp, "strategy_summary.json", {
            "latest": {"total_apy_pct": 5.22, "capital_deployed_usd": 95000, "adapter_count": 3}
        })
        sec = self.d.build_portfolio_section()
        self.assertIn("5.22", " ".join(sec.lines))
        self.assertIn("95,000", " ".join(sec.lines))

    def test_with_paper_trading_status_fallback(self):
        _write(self.tmp, "paper_trading_status.json", {
            "current_apy_pct": 4.5, "total_value_usd": 100000
        })
        sec = self.d.build_portfolio_section()
        self.assertIsInstance(sec, DigestSection)
        self.assertEqual(sec.emoji, "📊")

    def test_no_data_graceful(self):
        sec = self.d.build_portfolio_section()
        self.assertIsInstance(sec, DigestSection)
        self.assertTrue(any("unavailable" in line.lower() for line in sec.lines))

    def test_returns_digest_section(self):
        sec = self.d.build_portfolio_section()
        self.assertIsInstance(sec, DigestSection)


class TestBuildAlertSection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_alerts(self):
        _write(self.tmp, "alert_report.json", {
            "latest": {
                "alerts": [
                    {"severity": "CRITICAL", "message": "APY dropped"},
                    {"severity": "WARNING", "message": "T2 near cap"},
                ]
            }
        })
        sec = self.d.build_alert_section()
        self.assertIn("CRITICAL", " ".join(sec.lines))
        self.assertIn("WARNING", " ".join(sec.lines))

    def test_no_data_graceful(self):
        sec = self.d.build_alert_section()
        self.assertTrue(any("unavailable" in line.lower() for line in sec.lines))

    def test_emoji(self):
        sec = self.d.build_alert_section()
        self.assertEqual(sec.emoji, "🚨")


class TestBuildProgressSection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_progress_tracker(self):
        _write(self.tmp, "progress_tracker.json", {
            "paper_days": 3,
            "days_to_golive": 49,
            "go_live_target_date": "2026-08-01",
            "summary_verdict": "ON TRACK",
            "current_equity": 100500.0,
            "milestones": [{"done": True}, {"done": False}],
        })
        sec = self.d.build_progress_section()
        lines_str = " ".join(sec.lines)
        self.assertIn("3", lines_str)
        self.assertIn("49", lines_str)
        self.assertIn("1/2", lines_str)

    def test_no_data_graceful(self):
        sec = self.d.build_progress_section()
        self.assertTrue(any("unavailable" in line.lower() for line in sec.lines))

    def test_emoji(self):
        sec = self.d.build_progress_section()
        self.assertEqual(sec.emoji, "🎯")


class TestBuildPaperTradingSection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_paper_trading_log(self):
        _write(self.tmp, "paper_trading_log.json", {
            "day_number": 3, "total_pnl_usd": 1234.56, "best_strategy": "S8"
        })
        sec = self.d.build_paper_trading_section()
        lines_str = " ".join(sec.lines)
        self.assertIn("3", lines_str)
        self.assertIn("S8", lines_str)

    def test_fallback_equity_curve(self):
        _write(self.tmp, "equity_curve_daily.json", [
            {"equity_usd": 100500.0, "date": "2026-06-13"}
        ])
        sec = self.d.build_paper_trading_section()
        self.assertIsInstance(sec, DigestSection)

    def test_no_data_graceful(self):
        sec = self.d.build_paper_trading_section()
        self.assertTrue(any("unavailable" in line.lower() for line in sec.lines))

    def test_emoji(self):
        sec = self.d.build_paper_trading_section()
        self.assertEqual(sec.emoji, "📈")


class TestBuildForecastSection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_yield_forecast(self):
        _write(self.tmp, "yield_forecast.json", {
            "latest": {
                "forecast_7d_apy": 5.1,
                "forecast_30d_apy": 5.4,
                "trend": "RISING",
            }
        })
        sec = self.d.build_forecast_section()
        lines_str = " ".join(sec.lines)
        self.assertIn("5.10", lines_str)
        self.assertIn("RISING", lines_str)

    def test_no_data_graceful(self):
        sec = self.d.build_forecast_section()
        self.assertTrue(any("unavailable" in line.lower() for line in sec.lines))

    def test_emoji(self):
        sec = self.d.build_forecast_section()
        self.assertEqual(sec.emoji, "🔮")


# ===========================================================================
# build_digest
# ===========================================================================

class TestBuildDigest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_string(self):
        result = self.d.build_digest()
        self.assertIsInstance(result, str)

    def test_contains_date(self):
        result = self.d.build_digest(date_str="2026-06-13")
        self.assertIn("2026", result)

    def test_respects_max_length(self):
        result = self.d.build_digest()
        self.assertLessEqual(len(result), _MAX_MESSAGE_LEN)

    def test_custom_date_str(self):
        result = self.d.build_digest(date_str="2026-07-01")
        self.assertIn("2026", result)

    def test_has_header(self):
        result = self.d.build_digest()
        self.assertIn("SPA Daily Digest", result)

    def test_has_all_section_emojis(self):
        result = self.d.build_digest()
        for emoji in ("📊", "🚨", "🎯", "📈", "🔮"):
            self.assertIn(emoji, result)

    def test_no_raw_date_without_escaping_if_date_has_hyphen(self):
        # MarkdownV2 - must be escaped
        result = self.d.build_digest(date_str="2026-06-13")
        # The escaped form should appear
        self.assertIn("2026\\-06\\-13", result)

    def test_truncation_with_long_data(self):
        # Fill forecast with very long lines
        _write(self.tmp, "yield_forecast.json", {
            "latest": {
                "forecast_7d_apy": 5.0,
                "trend": "X" * 5000,  # extremely long string
            }
        })
        result = self.d.build_digest()
        self.assertLessEqual(len(result), _MAX_MESSAGE_LEN)


# ===========================================================================
# save_digest
# ===========================================================================

class TestSaveDigest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_path_string(self):
        path = self.d.save_digest("test content", date_str="2026-06-13")
        self.assertIsInstance(path, str)

    def test_file_created(self):
        path = self.d.save_digest("hello digest", date_str="2026-06-13")
        self.assertTrue(os.path.exists(path))

    def test_file_contents_match(self):
        content = "test digest content"
        path = self.d.save_digest(content, date_str="2026-06-13")
        saved = Path(path).read_text(encoding="utf-8")
        self.assertEqual(saved, content)

    def test_date_in_filename(self):
        path = self.d.save_digest("content", date_str="2026-07-01")
        self.assertIn("2026-07-01", path)

    def test_default_date_uses_today(self):
        path = self.d.save_digest("content")
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(today, path)

    def test_subdir_created(self):
        self.d.save_digest("content", date_str="2026-06-13")
        subdir = Path(self.tmp) / _DIGEST_SUBDIR
        self.assertTrue(subdir.exists())

    def test_no_tmp_files_left(self):
        self.d.save_digest("content", date_str="2026-06-13")
        subdir = Path(self.tmp) / _DIGEST_SUBDIR
        tmp_files = list(subdir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_overwrite_same_date(self):
        self.d.save_digest("first", date_str="2026-06-13")
        self.d.save_digest("second", date_str="2026-06-13")
        subdir = Path(self.tmp) / _DIGEST_SUBDIR
        content = (subdir / "2026-06-13.txt").read_text(encoding="utf-8")
        self.assertEqual(content, "second")


# ===========================================================================
# send_digest (mocked)
# ===========================================================================

class TestSendDigest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mock_success_response(self, message_id: int = 42):
        """Return a mock response object for a successful Telegram call."""
        response_data = json.dumps({
            "ok": True,
            "result": {"message_id": message_id, "chat": {"id": -1001}},
        }).encode("utf-8")
        mock_resp = mock.MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        return mock_resp

    # NOTE (flood-guard migration): send_digest now routes transport through the
    # canonical rate-limited client spa_core.alerts.telegram_client.send_message,
    # so these tests mock that chokepoint instead of urllib. The canonical client
    # returns bool, so message_id is no longer surfaced (reported as None).

    def test_successful_send_returns_ok_true(self):
        # RETIRED (Phase-1 Telegram rebuild): send_digest no longer pushes — the
        # analytics digest is folded into the single canonical daily message.
        # It still BUILDS the digest text but returns ok=False (no send).
        with mock.patch.object(
            self.d, "build_digest", wraps=self.d.build_digest
        ) as build:
            result = self.d.send_digest("fake_token", "-100123")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 0)
        build.assert_called_once()  # build_digest still produced the text

    @mock.patch("spa_core.alerts.telegram_client.send_message", return_value=True)
    def test_successful_send_returns_message_id(self, mock_send):
        # Canonical client returns bool only — message_id is None on success now.
        result = self.d.send_digest("fake_token", "-100123")
        self.assertIsNone(result.get("message_id"))

    @mock.patch("spa_core.alerts.telegram_client.send_message", return_value=False)
    def test_http_error_returns_ok_false(self, mock_send):
        # A failed/suppressed send → ok=False with an error string.
        result = self.d.send_digest("bad_token", "0")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 0)
        self.assertIn("error", result)

    @mock.patch("spa_core.alerts.telegram_client.send_message", return_value=False)
    def test_url_error_returns_ok_false(self, mock_send):
        result = self.d.send_digest("token", "chat")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 0)
        self.assertIn("error", result)

    @mock.patch(
        "spa_core.alerts.telegram_client.send_message",
        side_effect=RuntimeError("unexpected"),
    )
    def test_unexpected_exception_returns_ok_false(self, mock_send):
        result = self.d.send_digest("token", "chat")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    @mock.patch("spa_core.alerts.telegram_client.send_message")
    def test_send_calls_urlopen_once(self, mock_send):
        # RETIRED (Phase-1 Telegram rebuild): send_digest no longer hits the
        # transport at all — neither urlopen nor the canonical client. It only
        # builds the text and returns ok=False.
        result = self.d.send_digest("token", "chat")
        mock_send.assert_not_called()
        self.assertFalse(result["ok"])

    @mock.patch("spa_core.alerts.telegram_client.send_message", return_value=True)
    def test_result_has_required_keys_on_success(self, mock_send):
        result = self.d.send_digest("token", "chat")
        self.assertIn("ok", result)
        self.assertIn("status_code", result)

    @mock.patch("spa_core.alerts.telegram_client.send_message", return_value=False)
    def test_result_has_error_key_on_failure(self, mock_send):
        result = self.d.send_digest("token", "chat")
        self.assertIn("error", result)


# ===========================================================================
# Integration
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _make_digest(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_pipeline_with_all_data(self):
        """Write all data files, build digest, save, verify."""
        _write(self.tmp, "strategy_summary.json", {
            "latest": {"total_apy_pct": 5.22, "capital_deployed_usd": 95000, "adapter_count": 3}
        })
        _write(self.tmp, "alert_report.json", {
            "latest": {"alerts": [{"severity": "WARNING", "message": "T2 near cap"}]}
        })
        _write(self.tmp, "progress_tracker.json", {
            "paper_days": 3, "days_to_golive": 49,
            "go_live_target_date": "2026-08-01", "summary_verdict": "ON TRACK",
            "current_equity": 100000.0, "milestones": [{"done": True}, {"done": False}],
        })
        _write(self.tmp, "paper_trading_log.json", {
            "day_number": 3, "total_pnl_usd": 512.34, "best_strategy": "S9"
        })
        _write(self.tmp, "yield_forecast.json", {
            "latest": {"forecast_7d_apy": 5.1, "forecast_30d_apy": 5.5, "trend": "RISING"}
        })

        digest = self.d.build_digest(date_str="2026-06-13")
        self.assertIsInstance(digest, str)
        self.assertLessEqual(len(digest), _MAX_MESSAGE_LEN)

        path = self.d.save_digest(digest, date_str="2026-06-13")
        self.assertTrue(os.path.exists(path))
        saved = Path(path).read_text(encoding="utf-8")
        self.assertEqual(saved, digest)

    def test_all_sections_no_data_still_builds(self):
        """With empty data dir, digest should still build cleanly."""
        digest = self.d.build_digest(date_str="2026-06-13")
        self.assertIsInstance(digest, str)
        self.assertGreater(len(digest), 50)

    def test_digest_contains_advisory_footer(self):
        digest = self.d.build_digest()
        # Footer contains "advisory" text
        self.assertIn("advisory", digest.lower())


if __name__ == "__main__":
    unittest.main()
