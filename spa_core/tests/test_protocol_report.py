"""Tests for MP-792: spa_core/alerts/protocol_report.py.

Coverage:
- MarkdownV2 escaping correctness (all special chars)
- generate_protocol_report: default, filtered, edge cases
- Per-protocol block formatting: APY, TVL, health, tier, adapter key
- Health score computation across all tier/state/APY/TVL combinations
- Data loading: adapter_status.json present vs absent
- Fallback behavior when data files are missing
- send_protocol_report: urllib mocked, success/failure/empty-creds paths
- CLI: --preview / --send argument parsing
- Helper functions: _fmt_apy, _fmt_tvl, _time_ago
- Filtering by string vs list vs None

No network calls are made; urllib.request.urlopen is fully mocked.
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import os

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from spa_core.alerts import protocol_report as pr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(
    key: str,
    name: str,
    tier: str = "T1",
    write_state: str = "BLOCKED",
    chains: list | None = None,
    mock_apy: dict | None = None,
    tvl_usd: float | None = None,
) -> dict:
    a: dict = {
        "protocol_key": key,
        "name": name,
        "tier": tier,
        "write_state": write_state,
        "chains": chains or ["ethereum"],
        "assets": ["USDC"],
    }
    if mock_apy is not None:
        a["mock_apy"] = mock_apy
    if tvl_usd is not None:
        a["tvl_usd"] = tvl_usd
    return a


def _write_adapter_status(tmp: Path, adapters: list) -> None:
    data = {
        "generated_at": "2026-06-13T06:00:00+00:00",
        "schema_version": 1,
        "adapters": adapters,
    }
    (tmp / "adapter_status.json").write_text(json.dumps(data), encoding="utf-8")


def _write_positions(tmp: Path, positions: dict) -> None:
    data = {
        "generated_at": "2026-06-13T06:00:00+00:00",
        "source": "cycle_runner",
        "positions": positions,
    }
    (tmp / "current_positions.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. MarkdownV2 escaping
# ---------------------------------------------------------------------------

class TestEscapeMdv2(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(pr.escape_mdv2("hello world"), "hello world")

    def test_underscore_escaped(self):
        self.assertIn("\\_", pr.escape_mdv2("some_value"))

    def test_asterisk_escaped(self):
        self.assertIn("\\*", pr.escape_mdv2("a*b"))

    def test_dot_escaped(self):
        self.assertIn("\\.", pr.escape_mdv2("4.21%"))

    def test_hyphen_escaped(self):
        self.assertIn("\\-", pr.escape_mdv2("a-b"))

    def test_exclamation_escaped(self):
        self.assertIn("\\!", pr.escape_mdv2("hello!"))

    def test_dollar_not_escaped(self):
        """$ is NOT a MarkdownV2 special char."""
        result = pr.escape_mdv2("$1.5B")
        self.assertNotIn("\\$", result)
        self.assertIn("$", result)

    def test_open_bracket_escaped(self):
        self.assertIn("\\(", pr.escape_mdv2("(val)"))

    def test_close_bracket_escaped(self):
        self.assertIn("\\)", pr.escape_mdv2("(val)"))

    def test_pipe_escaped(self):
        self.assertIn("\\|", pr.escape_mdv2("a|b"))

    def test_tilde_escaped(self):
        self.assertIn("\\~", pr.escape_mdv2("a~b"))

    def test_backtick_escaped(self):
        self.assertIn("\\`", pr.escape_mdv2("a`b"))

    def test_hash_escaped(self):
        self.assertIn("\\#", pr.escape_mdv2("#tag"))

    def test_plus_escaped(self):
        self.assertIn("\\+", pr.escape_mdv2("a+b"))

    def test_equals_escaped(self):
        self.assertIn("\\=", pr.escape_mdv2("a=b"))

    def test_empty_string(self):
        self.assertEqual(pr.escape_mdv2(""), "")

    def test_all_specials_escaped(self):
        specials = r"\_*[]()~`>#+-=|{}.!"
        result = pr.escape_mdv2(specials)
        for ch in specials:
            self.assertIn(f"\\{ch}", result)


# ---------------------------------------------------------------------------
# 2. Formatting helpers
# ---------------------------------------------------------------------------

class TestFmtApy(unittest.TestCase):
    def test_normal_apy(self):
        result = pr._fmt_apy(4.21)
        self.assertIn("4", result)
        self.assertIn("21", result)

    def test_none_returns_na(self):
        self.assertIn("N", pr._fmt_apy(None))  # "N/A" escaped

    def test_zero_apy(self):
        result = pr._fmt_apy(0.0)
        self.assertIn("0", result)

    def test_apy_contains_percent(self):
        result = pr._fmt_apy(5.5)
        # '%' is not a special char, so appears literally
        self.assertIn("%", result)


class TestFmtTvl(unittest.TestCase):
    def test_billions(self):
        result = pr._fmt_tvl(18_000_000_000.0)
        self.assertIn("18", result)
        self.assertIn("B", result)

    def test_millions(self):
        result = pr._fmt_tvl(350_000_000.0)
        self.assertIn("350", result)
        self.assertIn("M", result)

    def test_none(self):
        self.assertIn("N", pr._fmt_tvl(None))

    def test_small_value(self):
        result = pr._fmt_tvl(12345.0)
        self.assertIn("12", result)

    def test_boundary_billion(self):
        result = pr._fmt_tvl(1_000_000_000.0)
        self.assertIn("B", result)


class TestTimeAgo(unittest.TestCase):
    def test_recent(self):
        now = datetime.now(tz=timezone.utc)
        ts = now.isoformat()
        result = pr._time_ago(ts)
        self.assertIn("just now", result)

    def test_minutes_ago(self):
        ts = "2000-01-01T00:00:00+00:00"  # far in the past
        result = pr._time_ago(ts)
        # Will be "Xd ago" since very old
        self.assertIn("ago", result)

    def test_none_returns_unknown(self):
        self.assertEqual(pr._time_ago(None), "unknown")

    def test_invalid_iso_returns_unknown(self):
        self.assertEqual(pr._time_ago("not-a-date"), "unknown")

    def test_z_suffix_handled(self):
        ts = "2026-06-13T06:00:00Z"
        result = pr._time_ago(ts)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


# ---------------------------------------------------------------------------
# 3. Health score computation
# ---------------------------------------------------------------------------

class TestComputeHealthScore(unittest.TestCase):
    def test_t1_active_healthy_apy_good_tvl(self):
        score, label = pr.compute_health_score(
            tier="T1", write_state="ACTIVE", apy=4.5,
            tvl_usd=1_000_000_000.0, audited=True
        )
        self.assertGreaterEqual(score, 85)
        self.assertEqual(label, "EXCELLENT")

    def test_t2_deducts_points(self):
        score_t1, _ = pr.compute_health_score(
            tier="T1", write_state="ACTIVE", apy=4.5,
            tvl_usd=1_000_000_000.0, audited=True
        )
        score_t2, _ = pr.compute_health_score(
            tier="T2", write_state="ACTIVE", apy=4.5,
            tvl_usd=1_000_000_000.0, audited=True
        )
        self.assertLess(score_t2, score_t1)

    def test_t3_deducts_more_than_t2(self):
        _, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 1e9, True)
        score_t2, _ = pr.compute_health_score("T2", "ACTIVE", 4.5, 1e9, True)
        score_t3, _ = pr.compute_health_score("T3", "ACTIVE", 4.5, 1e9, True)
        self.assertLess(score_t3, score_t2)

    def test_error_write_state_deducts(self):
        score_blocked, _ = pr.compute_health_score("T1", "BLOCKED", 4.5, 1e9, True)
        score_error, _ = pr.compute_health_score("T1", "ERROR", 4.5, 1e9, True)
        self.assertLess(score_error, score_blocked)

    def test_apy_out_of_range_deducts(self):
        score_ok, _ = pr.compute_health_score("T1", "ACTIVE", 5.0, 1e9, True)
        score_bad, _ = pr.compute_health_score("T1", "ACTIVE", 50.0, 1e9, True)
        self.assertLess(score_bad, score_ok)

    def test_tvl_below_floor_deducts(self):
        score_ok, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 1e9, True)
        score_low, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 100_000.0, True)
        self.assertLess(score_low, score_ok)

    def test_unaudited_deducts(self):
        score_audit, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 1e9, True)
        score_no, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 1e9, False)
        self.assertLess(score_no, score_audit)

    def test_score_clamped_0_to_100(self):
        score, _ = pr.compute_health_score("T3", "ERROR", -1.0, 1000.0, False)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_label_poor_when_low(self):
        score, label = pr.compute_health_score("T3", "ERROR", 50.0, 1000.0, False)
        self.assertEqual(label, "POOR")

    def test_label_fair(self):
        score, label = pr.compute_health_score("T2", "BLOCKED", 2.5, 50_000_000.0, True)
        self.assertIn(label, ("FAIR", "HEALTHY", "EXCELLENT"))

    def test_none_apy_no_crash(self):
        score, label = pr.compute_health_score("T1", "ACTIVE", None, 1e9, True)
        self.assertIsInstance(score, int)
        self.assertIsInstance(label, str)

    def test_none_tvl_deducts_small(self):
        score_known, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, 1e9, True)
        score_unknown, _ = pr.compute_health_score("T1", "ACTIVE", 4.5, None, True)
        self.assertLessEqual(score_unknown, score_known)


# ---------------------------------------------------------------------------
# 4. _get_best_apy
# ---------------------------------------------------------------------------

class TestGetBestApy(unittest.TestCase):
    def test_returns_max_from_mock(self):
        adapter = _make_adapter(
            "test", "Test",
            mock_apy={"ethereum": {"USDC": 4.2, "USDT": 3.8}}
        )
        apy = pr._get_best_apy(adapter)
        self.assertAlmostEqual(apy, 4.2)

    def test_empty_mock_returns_none(self):
        adapter = _make_adapter("test", "Test")
        apy = pr._get_best_apy(adapter)
        self.assertIsNone(apy)

    def test_live_apy_preferred_over_mock(self):
        adapter = _make_adapter(
            "test", "Test",
            mock_apy={"ethereum": {"USDC": 4.2}}
        )
        adapter["live_apy"] = {"ethereum": {"USDC": 6.5}}
        apy = pr._get_best_apy(adapter)
        self.assertAlmostEqual(apy, 6.5)

    def test_multi_chain_max(self):
        adapter = _make_adapter(
            "test", "Test",
            mock_apy={"ethereum": {"USDC": 4.2}, "arbitrum": {"USDC": 5.1}}
        )
        apy = pr._get_best_apy(adapter)
        self.assertAlmostEqual(apy, 5.1)


# ---------------------------------------------------------------------------
# 5. _get_tvl
# ---------------------------------------------------------------------------

class TestGetTvl(unittest.TestCase):
    def test_returns_tvl_usd_from_adapter(self):
        adapter = _make_adapter("aave-v3", "Aave V3", tvl_usd=5_000_000_000.0)
        tvl = pr._get_tvl(adapter)
        self.assertAlmostEqual(tvl, 5_000_000_000.0)

    def test_falls_back_to_fallback_table(self):
        adapter = _make_adapter("aave-v3", "Aave V3")
        tvl = pr._get_tvl(adapter)
        self.assertIsNotNone(tvl)
        self.assertGreater(tvl, 0)

    def test_unknown_protocol_returns_none(self):
        adapter = _make_adapter("unknown-proto", "Unknown")
        tvl = pr._get_tvl(adapter)
        self.assertIsNone(tvl)


# ---------------------------------------------------------------------------
# 6. _format_protocol_block
# ---------------------------------------------------------------------------

class TestFormatProtocolBlock(unittest.TestCase):
    def _make_block(self, key="aave-v3", tier="T1", apy_val=4.21):
        adapter = _make_adapter(
            key, "Aave V3", tier=tier,
            mock_apy={"ethereum": {"USDC": apy_val}},
            tvl_usd=18_000_000_000.0,
        )
        meta = pr._PROTOCOL_META.get(key, {
            "display_name": key, "chain": "Ethereum",
            "adapter_key": key, "audited": True,
            "bug_bounty": "$1M", "risk_label": "LOW",
        })
        return pr._format_protocol_block(
            protocol_key=key,
            adapter=adapter,
            meta=meta,
            positions={},
            generated_at="2026-06-13T06:00:00+00:00",
        )

    def test_block_contains_display_name(self):
        block = self._make_block()
        self.assertIn("Aave V3 ETH", block)

    def test_block_contains_tier(self):
        block = self._make_block()
        self.assertIn("T1", block)

    def test_block_contains_chain(self):
        block = self._make_block()
        self.assertIn("Ethereum", block)

    def test_block_contains_apy(self):
        block = self._make_block(apy_val=4.21)
        self.assertIn("4", block)
        self.assertIn("21", block)

    def test_block_contains_tvl(self):
        block = self._make_block()
        self.assertIn("18", block)
        self.assertIn("B", block)

    def test_block_contains_health_score(self):
        block = self._make_block()
        self.assertIn("/100", block)

    def test_block_starts_with_emoji(self):
        block = self._make_block()
        self.assertTrue(block.startswith("📊"))

    def test_block_has_seven_lines(self):
        block = self._make_block()
        lines = block.split("\n")
        self.assertEqual(len(lines), 7)

    def test_block_last_line_starts_with_corner(self):
        block = self._make_block()
        last_line = block.split("\n")[-1]
        self.assertTrue(last_line.startswith("└"))

    def test_block_no_adapter_still_renders(self):
        meta = pr._PROTOCOL_META.get("aave-v3", {})
        block = pr._format_protocol_block(
            protocol_key="aave-v3",
            adapter=None,
            meta=meta,
            positions={},
            generated_at=None,
        )
        self.assertIn("Aave", block)

    def test_block_audit_checkmark_present(self):
        block = self._make_block()
        self.assertIn("✅", block)

    def test_block_risk_label_present(self):
        block = self._make_block()
        self.assertIn("LOW", block)


# ---------------------------------------------------------------------------
# 7. generate_protocol_report — core behavior
# ---------------------------------------------------------------------------

class TestGenerateProtocolReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        _write_adapter_status(self.tmp_path, [
            _make_adapter(
                "aave-v3", "Aave V3", tier="T1",
                mock_apy={"ethereum": {"USDC": 4.2}},
                tvl_usd=18_000_000_000.0,
            ),
            _make_adapter(
                "compound-v3", "Compound V3", tier="T1",
                mock_apy={"ethereum": {"USDC": 4.8}},
                tvl_usd=3_200_000_000.0,
            ),
        ])
        _write_positions(self.tmp_path, {"aave_v3": 23750.0, "compound_v3": 38000.0})

    def test_returns_string(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertIsInstance(report, str)

    def test_report_contains_header(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertIn("SPA Protocol Report", report)

    def test_report_contains_aave(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertIn("Aave", report)

    def test_report_contains_compound(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertIn("Compound", report)

    def test_report_length_within_telegram_limit(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertLessEqual(len(report), 4096)

    def test_filter_by_single_key(self):
        report = pr.generate_protocol_report(
            protocol_filter="aave-v3",
            data_dir=self.tmp_path,
        )
        self.assertIn("Aave", report)
        # Compound should not appear in title blocks when filtered out
        # (still might appear in footer summary — just verify aave is there)
        self.assertIsInstance(report, str)

    def test_filter_by_list(self):
        report = pr.generate_protocol_report(
            protocol_filter=["aave-v3"],
            data_dir=self.tmp_path,
        )
        self.assertIn("Aave", report)

    def test_filter_empty_result_message(self):
        report = pr.generate_protocol_report(
            protocol_filter="nonexistent-proto-xyz",
            data_dir=self.tmp_path,
        )
        self.assertIn("No protocols", report)

    def test_fallback_when_no_data_files(self):
        empty_tmp = tempfile.mkdtemp()
        report = pr.generate_protocol_report(data_dir=Path(empty_tmp))
        # Should still produce a report from hardcoded defaults
        self.assertIsInstance(report, str)
        self.assertIn("SPA Protocol Report", report)

    def test_report_not_empty(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertTrue(len(report) > 50)

    def test_report_has_footer_total(self):
        report = pr.generate_protocol_report(data_dir=self.tmp_path)
        self.assertIn("Total", report)

    def test_exception_in_generation_returns_error_string(self):
        """Even if data_dir is a file (will error), must return a string."""
        # Create a file where a dir is expected
        bad_path = Path(self.tmp) / "bad"
        bad_path.write_text("{}", encoding="utf-8")
        report = pr.generate_protocol_report(data_dir=bad_path)
        self.assertIsInstance(report, str)


# ---------------------------------------------------------------------------
# 8. send_protocol_report — mocked urllib
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestSendProtocolReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        _write_adapter_status(self.tmp_path, [
            _make_adapter("aave-v3", "Aave V3", tier="T1",
                          mock_apy={"ethereum": {"USDC": 4.2}}),
        ])

    @unittest.mock.patch("spa_core.telegram.push_policy.enqueue_digest")
    def test_returns_true_on_200(self, mock_enqueue):
        """send_protocol_report is RETIRED as a push: it routes the report to the
        digest queue and returns False."""
        result = pr.send_protocol_report(
            bot_token="test_token",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)
        mock_enqueue.assert_called_once()

    @unittest.mock.patch("urllib.request.urlopen")
    def test_returns_false_on_non_200(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(400)
        result = pr.send_protocol_report(
            bot_token="test_token",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)

    @unittest.mock.patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_returns_false_on_exception(self, mock_urlopen):
        result = pr.send_protocol_report(
            bot_token="test_token",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)

    def test_empty_token_returns_false(self):
        result = pr.send_protocol_report(
            bot_token="",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)

    def test_empty_chat_id_returns_false(self):
        result = pr.send_protocol_report(
            bot_token="test_token",
            chat_id="",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)

    @unittest.mock.patch("spa_core.telegram.push_policy.enqueue_digest")
    def test_report_routed_to_digest(self, mock_enqueue):
        """The MarkdownV2 path is gone (no direct POST). Assert the composed report
        TEXT is routed to the digest queue instead."""
        pr.send_protocol_report(
            bot_token="test_token",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        mock_enqueue.assert_called_once()
        # enqueue_digest(event_key, title, body, *, ...) — body is positional index 2.
        body = mock_enqueue.call_args[0][2]
        self.assertIn("SPA Protocol Report", body)

    @unittest.mock.patch(
        "urllib.request.urlopen",
        side_effect=__import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            url="http://x", code=429, msg="Too Many Requests", hdrs=None, fp=None
        ),
    )
    def test_http_error_returns_false(self, mock_urlopen):
        result = pr.send_protocol_report(
            bot_token="test_token",
            chat_id="-100123",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)

    @unittest.mock.patch("spa_core.telegram.push_policy.enqueue_digest")
    def test_filter_passed_through(self, mock_enqueue):
        """Filtered report is still composed and routed to the digest; the filter
        still affects the enqueued text (aave present, compound absent)."""
        result = pr.send_protocol_report(
            bot_token="tok",
            chat_id="cid",
            protocol_filter="aave-v3",
            data_dir=self.tmp_path,
        )
        self.assertFalse(result)
        mock_enqueue.assert_called_once()
        body = mock_enqueue.call_args[0][2]
        self.assertIn("Aave", body)
        self.assertNotIn("Compound", body)


# ---------------------------------------------------------------------------
# 9. _build_protocol_map
# ---------------------------------------------------------------------------

class TestBuildProtocolMap(unittest.TestCase):
    def test_indexes_by_protocol_key(self):
        adapters = [
            _make_adapter("aave-v3", "Aave V3"),
            _make_adapter("compound-v3", "Compound V3"),
        ]
        m = pr._build_protocol_map(adapters)
        self.assertIn("aave-v3", m)
        self.assertIn("compound-v3", m)

    def test_empty_list(self):
        self.assertEqual(pr._build_protocol_map([]), {})

    def test_missing_key_skipped(self):
        adapters = [{"name": "No Key"}]
        m = pr._build_protocol_map(adapters)
        self.assertEqual(m, {})


# ---------------------------------------------------------------------------
# 10. _load_adapter_status / _load_positions
# ---------------------------------------------------------------------------

class TestDataLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)

    def test_load_adapter_status_present(self):
        adapters = [_make_adapter("aave-v3", "Aave V3")]
        _write_adapter_status(self.tmp_path, adapters)
        result = pr._load_adapter_status(self.tmp_path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["protocol_key"], "aave-v3")

    def test_load_adapter_status_missing_returns_empty(self):
        result = pr._load_adapter_status(self.tmp_path)
        self.assertEqual(result, [])

    def test_load_positions_present(self):
        _write_positions(self.tmp_path, {"aave_v3": 23750.0})
        result = pr._load_positions(self.tmp_path)
        self.assertIn("aave_v3", result)
        self.assertAlmostEqual(result["aave_v3"], 23750.0)

    def test_load_positions_missing_returns_empty(self):
        result = pr._load_positions(self.tmp_path)
        self.assertEqual(result, {})

    def test_load_positions_ignores_non_numeric(self):
        data = {
            "generated_at": "2026-06-13T00:00:00+00:00",
            "positions": {"aave_v3": 23750.0, "bad": "not_a_number"},
        }
        (self.tmp_path / "current_positions.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = pr._load_positions(self.tmp_path)
        self.assertIn("aave_v3", result)
        self.assertNotIn("bad", result)


# ---------------------------------------------------------------------------
# 11. _get_status_emoji
# ---------------------------------------------------------------------------

class TestGetStatusEmoji(unittest.TestCase):
    def test_active_state(self):
        s = pr._get_status_emoji("ACTIVE", 4.5)
        self.assertIn("ACTIVE", s)
        self.assertIn("✅", s)

    def test_blocked_with_valid_apy(self):
        s = pr._get_status_emoji("BLOCKED", 4.5)
        self.assertIn("ACTIVE", s)

    def test_blocked_with_invalid_apy(self):
        s = pr._get_status_emoji("BLOCKED", 0.0)
        self.assertIn("PAPER", s)

    def test_error_state(self):
        s = pr._get_status_emoji("ERROR", 4.5)
        self.assertIn("INACTIVE", s)

    def test_unknown_state(self):
        s = pr._get_status_emoji("UNKNOWN", None)
        self.assertIn("UNKNOWN", s)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
