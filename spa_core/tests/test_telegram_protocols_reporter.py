"""
Tests for spa_core/telegram_protocols_reporter.py  (MP-659 / v6.59)

≥ 30 tests covering:
  - format_protocols_message with various adapter counts and structures
  - Empty adapter lists / missing fields
  - Null/None field handling
  - Long message splitting (4096-char Telegram limit)
  - All health/tier combinations
  - TVL formatting
  - APY extraction from mock_apy and flat fields
  - System summary section
  - Deduplication logic
  - send_protocols_report with mocked HTTP

Pure stdlib only — no external dependencies.
"""
from __future__ import annotations

import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from spa_core.telegram_protocols_reporter import (
    _compute_health,
    _format_adapter_line,
    _get_all_adapters,
    _get_best_apy,
    _get_tvl_str,
    format_protocols_message,
    load_adapter_data,
    send_protocols_report,
    split_message,
)


# ──────────────────────────── fixtures ────────────────────────────────────

def _make_adapter(
    *,
    name: str = "Test Protocol",
    protocol_key: str = "test-proto",
    tier: str = "T1",
    apy_pct: float = 5.0,
    tvl_usd: float = 1_000_000_000,
    risk_score: float = 0.25,
    status: str = "active",
    write_state: str = "BLOCKED",
    mock_apy: dict | None = None,
    **kwargs,
) -> dict:
    d: dict = {
        "protocol_key": protocol_key,
        "name": name,
        "tier": tier,
        "write_state": write_state,
        "status": status,
    }
    if apy_pct is not None:
        d["apy_pct"] = apy_pct
    if tvl_usd is not None:
        d["tvl_usd"] = tvl_usd
    if risk_score is not None:
        d["risk_score"] = risk_score
    if mock_apy is not None:
        d["mock_apy"] = mock_apy
    d.update(kwargs)
    return d


def _minimal_data(*adapters) -> dict:
    """Build a minimal adapter_status-like dict."""
    return {"adapters": list(adapters)}


# ══════════════════════════════════════════════════════════════════════════
# 1. _get_best_apy
# ══════════════════════════════════════════════════════════════════════════


class TestGetBestApy(unittest.TestCase):

    def test_flat_apy_pct(self):
        """apy_pct flat field is returned directly."""
        self.assertAlmostEqual(_get_best_apy({"apy_pct": 7.5}), 7.5)

    def test_flat_apy_fallback(self):
        """'apy' is used when 'apy_pct' is absent."""
        self.assertAlmostEqual(_get_best_apy({"apy": 4.2}), 4.2)

    def test_apy_pct_takes_priority_over_mock(self):
        """apy_pct beats mock_apy value."""
        d = {"apy_pct": 3.0, "mock_apy": {"ethereum": {"USDC": 9.9}}}
        self.assertAlmostEqual(_get_best_apy(d), 3.0)

    def test_mock_apy_usdc_preferred(self):
        """USDC on any chain is preferred in mock_apy lookup."""
        d = {"mock_apy": {"ethereum": {"DAI": 2.0, "USDC": 4.8}}}
        self.assertAlmostEqual(_get_best_apy(d), 4.8)

    def test_mock_apy_highest_usdc(self):
        """Returns the highest USDC APY across chains."""
        d = {
            "mock_apy": {
                "ethereum": {"USDC": 4.2},
                "arbitrum": {"USDC": 4.6},
            }
        }
        self.assertAlmostEqual(_get_best_apy(d), 4.6)

    def test_mock_apy_non_usdc_fallback(self):
        """Falls back to first numeric value when USDC absent."""
        d = {"mock_apy": {"ethereum": {"USDT": 3.8}}}
        self.assertAlmostEqual(_get_best_apy(d), 3.8)

    def test_missing_apy_returns_none(self):
        """Returns None when no APY field is present."""
        self.assertIsNone(_get_best_apy({}))

    def test_invalid_adapter_type_returns_none(self):
        """Non-dict input returns None without raising."""
        self.assertIsNone(_get_best_apy(None))  # type: ignore
        self.assertIsNone(_get_best_apy("bad"))  # type: ignore

    def test_empty_mock_apy_dict(self):
        """Empty mock_apy returns None."""
        self.assertIsNone(_get_best_apy({"mock_apy": {}}))


# ══════════════════════════════════════════════════════════════════════════
# 2. _compute_health
# ══════════════════════════════════════════════════════════════════════════


class TestComputeHealth(unittest.TestCase):

    def test_safe_low_risk(self):
        emoji, label = _compute_health({"risk_score": 0.2, "status": "active"})
        self.assertEqual(emoji, "✅")
        self.assertEqual(label, "SAFE")

    def test_caution_high_risk_score(self):
        emoji, label = _compute_health({"risk_score": 0.65, "status": "active"})
        self.assertEqual(emoji, "⚠️")
        self.assertEqual(label, "CAUTION")

    def test_caution_moderate_risk_score(self):
        emoji, label = _compute_health({"risk_score": 0.42, "status": "active"})
        self.assertEqual(emoji, "⚠️")
        self.assertEqual(label, "CAUTION")

    def test_danger_suspended(self):
        emoji, label = _compute_health({"status": "suspended"})
        self.assertEqual(emoji, "🚨")
        self.assertEqual(label, "DANGER")

    def test_research_status(self):
        emoji, label = _compute_health({"status": "research"})
        self.assertEqual(emoji, "🔬")
        self.assertEqual(label, "RESEARCH")

    def test_monitoring_status(self):
        emoji, label = _compute_health({"status": "monitoring"})
        self.assertEqual(emoji, "⚠️")
        self.assertEqual(label, "MONITOR")

    def test_no_risk_score_active(self):
        """Active adapter with no risk_score → SAFE."""
        emoji, label = _compute_health({"status": "active"})
        self.assertEqual(emoji, "✅")
        self.assertEqual(label, "SAFE")

    def test_suspended_beats_low_risk(self):
        """Suspended status overrides even a low risk_score."""
        emoji, label = _compute_health({"status": "suspended", "risk_score": 0.1})
        self.assertEqual(emoji, "🚨")
        self.assertEqual(label, "DANGER")

    def test_empty_dict(self):
        """Empty dict returns SAFE without raising."""
        emoji, label = _compute_health({})
        self.assertEqual(emoji, "✅")
        self.assertEqual(label, "SAFE")


# ══════════════════════════════════════════════════════════════════════════
# 3. _get_tvl_str
# ══════════════════════════════════════════════════════════════════════════


class TestGetTvlStr(unittest.TestCase):

    def test_billions(self):
        self.assertEqual(_get_tvl_str({"tvl_usd": 2_800_000_000}), "$2.8B")

    def test_millions(self):
        self.assertEqual(_get_tvl_str({"tvl_usd": 500_000_000}), "$500M")

    def test_thousands(self):
        self.assertEqual(_get_tvl_str({"tvl_usd": 30_000}), "$30K")

    def test_small(self):
        result = _get_tvl_str({"tvl_usd": 999})
        self.assertEqual(result, "$999")

    def test_missing_tvl(self):
        self.assertIsNone(_get_tvl_str({}))

    def test_non_numeric_tvl(self):
        self.assertIsNone(_get_tvl_str({"tvl_usd": "big"}))


# ══════════════════════════════════════════════════════════════════════════
# 4. _format_adapter_line
# ══════════════════════════════════════════════════════════════════════════


class TestFormatAdapterLine(unittest.TestCase):

    def test_basic_line_starts_with_bullet(self):
        line = _format_adapter_line(_make_adapter())
        self.assertTrue(line.startswith("• "))

    def test_contains_apy(self):
        line = _format_adapter_line(_make_adapter(apy_pct=6.5))
        self.assertIn("6.5%", line)

    def test_contains_tvl(self):
        line = _format_adapter_line(_make_adapter(tvl_usd=1_500_000_000))
        self.assertIn("$1.5B", line)

    def test_na_when_no_apy(self):
        a = {"name": "X", "tier": "T2"}
        line = _format_adapter_line(a)
        self.assertIn("n/a", line)

    def test_quick_win_bps_shown(self):
        a = _make_adapter(quick_win=True, bps_gain=200)
        line = _format_adapter_line(a)
        self.assertIn("+200bps", line)

    def test_gsm_hours_shown(self):
        a = _make_adapter(gsm_hours=0)
        line = _format_adapter_line(a)
        self.assertIn("GSM: 0h/48h", line)

    def test_write_state_read_only_shown(self):
        """Non-BLOCKED write_state should appear in the line."""
        a = _make_adapter(write_state="READ_ONLY")
        line = _format_adapter_line(a)
        self.assertIn("READ_ONLY", line)

    def test_write_state_blocked_hidden(self):
        """BLOCKED write_state should NOT appear (it's the paper-mode default)."""
        a = _make_adapter(write_state="BLOCKED")
        line = _format_adapter_line(a)
        self.assertNotIn("BLOCKED", line)

    def test_health_emoji_in_line(self):
        a = _make_adapter(status="suspended")
        line = _format_adapter_line(a)
        self.assertIn("🚨", line)

    def test_name_fallback_to_display_name(self):
        a = {"display_name": "My Protocol", "tier": "T1", "apy_pct": 5.0}
        line = _format_adapter_line(a)
        self.assertIn("My Protocol", line)

    def test_name_fallback_to_protocol_key(self):
        a = {"protocol_key": "my-key", "tier": "T1"}
        line = _format_adapter_line(a)
        self.assertIn("my-key", line)


# ══════════════════════════════════════════════════════════════════════════
# 5. _get_all_adapters
# ══════════════════════════════════════════════════════════════════════════


class TestGetAllAdapters(unittest.TestCase):

    def test_structured_adapters_list(self):
        data = {"adapters": [_make_adapter(protocol_key="a"), _make_adapter(protocol_key="b")]}
        result = _get_all_adapters(data)
        self.assertEqual(len(result), 2)

    def test_flat_top_level_adapter(self):
        """Flat dict with 'tier' and 'apy_pct' is picked up as an adapter."""
        data = {
            "adapters": [],
            "sfrax": {"adapter_id": "sfrax", "tier": "T2", "apy_pct": 6.0, "tvl_usd": 1e8},
        }
        result = _get_all_adapters(data)
        self.assertEqual(len(result), 1)

    def test_deduplication_by_protocol_key(self):
        """Same protocol_key in adapters list and top-level → counted once."""
        data = {
            "adapters": [{"protocol_key": "aave-v3", "tier": "T1", "apy_pct": 4.2}],
            "aave_v3": {"protocol_key": "aave-v3", "tier": "T1", "apy_pct": 4.2},
        }
        result = _get_all_adapters(data)
        self.assertEqual(len(result), 1)

    def test_metadata_keys_ignored(self):
        """generated_at / mev_protection / etc. are not treated as adapters."""
        data = {
            "generated_at": "2026-06-13",
            "mev_protection": {"enabled": False},
            "adapters": [],
        }
        result = _get_all_adapters(data)
        self.assertEqual(result, [])

    def test_non_dict_top_level_ignored(self):
        data = {"adapters": [], "count": 5, "flag": True}
        result = _get_all_adapters(data)
        self.assertEqual(result, [])

    def test_empty_data_returns_empty(self):
        self.assertEqual(_get_all_adapters({}), [])

    def test_invalid_input_returns_empty(self):
        self.assertEqual(_get_all_adapters(None), [])  # type: ignore


# ══════════════════════════════════════════════════════════════════════════
# 6. format_protocols_message
# ══════════════════════════════════════════════════════════════════════════


class TestFormatProtocolsMessage(unittest.TestCase):

    def test_returns_string(self):
        self.assertIsInstance(format_protocols_message({}), str)

    def test_contains_header(self):
        msg = format_protocols_message({})
        self.assertIn("SPA Protocol Status", msg)

    def test_contains_date(self):
        msg = format_protocols_message({})
        self.assertIn("UTC", msg)

    def test_empty_adapters_no_crash(self):
        """Empty adapters list produces a valid (header-only) message."""
        msg = format_protocols_message({"adapters": []})
        self.assertIn("SPA Protocol Status", msg)

    def test_none_input_no_crash(self):
        msg = format_protocols_message(None)  # type: ignore
        self.assertIsInstance(msg, str)

    def test_single_t1_adapter_appears(self):
        data = _minimal_data(_make_adapter(name="Aave V3", tier="T1", apy_pct=4.2))
        msg = format_protocols_message(data)
        self.assertIn("Aave V3", msg)
        self.assertIn("4.2%", msg)

    def test_t1_section_header(self):
        data = _minimal_data(_make_adapter(tier="T1"))
        msg = format_protocols_message(data)
        self.assertIn("T1", msg)

    def test_t2_section_header(self):
        data = _minimal_data(_make_adapter(tier="T2"))
        msg = format_protocols_message(data)
        self.assertIn("T2", msg)

    def test_t1_before_t2_in_output(self):
        data = _minimal_data(
            _make_adapter(name="B", tier="T2", protocol_key="b"),
            _make_adapter(name="A", tier="T1", protocol_key="a"),
        )
        msg = format_protocols_message(data)
        self.assertLess(msg.index("T1"), msg.index("T2"))

    def test_system_section_present(self):
        msg = format_protocols_message({})
        self.assertIn("System", msg)

    def test_system_shows_capital(self):
        data = {"positions_data": {"capital_usd": 100_000}}
        msg = format_protocols_message(data)
        self.assertIn("$100,000", msg)

    def test_system_shows_deployed_and_cash(self):
        data = {
            "positions_data": {
                "capital_usd": 100_000,
                "deployed_usd": 95_000,
                "cash_usd": 5_000,
                "positions": {},
            }
        }
        msg = format_protocols_message(data)
        self.assertIn("$95,000", msg)
        self.assertIn("$5,000", msg)

    def test_system_shows_total_adapters(self):
        data = _minimal_data(
            _make_adapter(protocol_key="a"),
            _make_adapter(protocol_key="b"),
            _make_adapter(protocol_key="c"),
        )
        msg = format_protocols_message(data)
        self.assertIn("Total adapters: 3", msg)

    def test_system_shows_active_positions(self):
        data = {
            "adapters": [],
            "positions_data": {
                "positions": {"aave_v3": 30_000, "compound": 20_000, "empty": 0}
            },
        }
        msg = format_protocols_message(data)
        self.assertIn("Active positions: 2", msg)

    def test_mev_coverage_shown(self):
        data = {
            "adapters": [],
            "mev_protection": {"coverage": {"coverage_pct": 66.7}},
        }
        msg = format_protocols_message(data)
        self.assertIn("MEV coverage: 67%", msg)

    def test_health_emojis_present(self):
        data = _minimal_data(
            _make_adapter(status="active", risk_score=0.2, protocol_key="safe"),
            _make_adapter(status="suspended", protocol_key="bad"),
        )
        msg = format_protocols_message(data)
        self.assertIn("✅", msg)
        self.assertIn("🚨", msg)

    def test_research_status_shown(self):
        data = _minimal_data(_make_adapter(status="research", gsm_hours=0))
        msg = format_protocols_message(data)
        self.assertIn("🔬", msg)

    def test_unknown_tier_rendered(self):
        """Adapters with a tier not in canonical list are still shown."""
        data = _minimal_data(_make_adapter(tier="T4-CUSTOM", protocol_key="x"))
        msg = format_protocols_message(data)
        self.assertIn("T4-CUSTOM", msg)

    def test_multiple_adapters_all_present(self):
        names = ["Proto Alpha", "Proto Beta", "Proto Gamma"]
        adapters = [_make_adapter(name=n, protocol_key=n.lower().replace(" ", "-")) for n in names]
        data = _minimal_data(*adapters)
        msg = format_protocols_message(data)
        for name in names:
            self.assertIn(name, msg)

    def test_tvl_shown_in_message(self):
        data = _minimal_data(_make_adapter(tvl_usd=2_800_000_000))
        msg = format_protocols_message(data)
        self.assertIn("$2.8B", msg)

    def test_missing_tvl_no_crash(self):
        a = {"name": "X", "tier": "T2", "apy_pct": 5.0}
        msg = format_protocols_message({"adapters": [a]})
        self.assertIn("X", msg)

    def test_null_fields_graceful(self):
        """Adapter with all fields None/missing still formats."""
        msg = format_protocols_message({"adapters": [{}]})
        self.assertIsInstance(msg, str)
        self.assertIn("n/a", msg)  # APY shows "n/a"


# ══════════════════════════════════════════════════════════════════════════
# 7. split_message
# ══════════════════════════════════════════════════════════════════════════


class TestSplitMessage(unittest.TestCase):

    def test_short_message_single_chunk(self):
        text = "Hello World"
        chunks = split_message(text)
        self.assertEqual(chunks, [text])

    def test_empty_string(self):
        chunks = split_message("")
        self.assertEqual(chunks, [""])

    def test_exact_limit_single_chunk(self):
        text = "x" * 4096
        chunks = split_message(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_exceeds_limit_splits(self):
        text = "\n".join(["Line " + str(i) for i in range(500)])
        chunks = split_message(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4096)

    def test_all_content_preserved(self):
        """No content is lost during splitting."""
        lines = [f"Protocol {i}: APY {i}%" for i in range(200)]
        text = "\n".join(lines)
        chunks = split_message(text)
        reassembled = "\n".join(chunks)
        # Every line must appear somewhere in the reassembled text
        for line in lines:
            self.assertIn(line, reassembled)

    def test_custom_max_len(self):
        text = "abcde\nfghij\nklmno"
        chunks = split_message(text, max_len=8)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 8)

    def test_very_long_single_line_hard_split(self):
        """A single line longer than max_len is hard-split."""
        text = "A" * 5000
        chunks = split_message(text, max_len=100)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)

    def test_real_message_within_limit(self):
        """A typical /protocols message fits in one chunk."""
        data = _minimal_data(
            *[_make_adapter(name=f"Proto {i}", protocol_key=f"proto-{i}") for i in range(5)]
        )
        msg = format_protocols_message(data)
        chunks = split_message(msg)
        # 5 adapters → message should be well under 4096
        self.assertEqual(len(chunks), 1)

    def test_split_returns_list(self):
        chunks = split_message("test")
        self.assertIsInstance(chunks, list)

    def test_large_message_no_chunk_exceeds_limit(self):
        """100 adapters → may split but never exceeds 4096."""
        data = _minimal_data(
            *[
                _make_adapter(
                    name=f"Protocol Number {i} With A Very Long Name",
                    protocol_key=f"proto-{i}",
                    tvl_usd=float(i) * 1e9,
                )
                for i in range(100)
            ]
        )
        msg = format_protocols_message(data)
        chunks = split_message(msg)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4096)


# ══════════════════════════════════════════════════════════════════════════
# 8. send_protocols_report (mocked)
# ══════════════════════════════════════════════════════════════════════════


class TestSendProtocolsReport(unittest.TestCase):

    def _fake_urlopen(self, req, timeout=30):
        """Return a fake successful Telegram API response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {}}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_successful_send(self):
        data = _minimal_data(_make_adapter())
        with patch("urllib.request.urlopen", side_effect=self._fake_urlopen):
            result = send_protocols_report(
                chat_id="123",
                bot_token="fake-token",
                data=data,
            )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["sent"], 1)
        self.assertEqual(result["errors"], [])

    def test_network_error_captured(self):
        data = _minimal_data(_make_adapter())
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = send_protocols_report(
                chat_id="123",
                bot_token="fake-token",
                data=data,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["sent"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_returns_dict_structure(self):
        data = {"adapters": []}
        with patch("urllib.request.urlopen", side_effect=self._fake_urlopen):
            result = send_protocols_report(
                chat_id="999",
                bot_token="tok",
                data=data,
            )
        self.assertIn("ok", result)
        self.assertIn("sent", result)
        self.assertIn("responses", result)
        self.assertIn("errors", result)

    def test_data_overrides_file_loading(self):
        """When data= is provided, load_adapter_data is NOT called."""
        data = {"adapters": []}
        with patch(
            "spa_core.telegram_protocols_reporter.load_adapter_data"
        ) as mock_load, patch("urllib.request.urlopen", side_effect=self._fake_urlopen):
            send_protocols_report(chat_id="1", bot_token="t", data=data)
        mock_load.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# 9. load_adapter_data (filesystem)
# ══════════════════════════════════════════════════════════════════════════


class TestLoadAdapterData(unittest.TestCase):

    def test_missing_directory_returns_defaults(self):
        result = load_adapter_data(Path("/nonexistent/path/xyz"))
        self.assertIsInstance(result, dict)
        self.assertIn("positions_data", result)
        self.assertIsInstance(result["positions_data"], dict)

    def test_loads_real_data(self):
        """Smoke-test: load from the actual repo data directory."""
        import pathlib

        repo_data = pathlib.Path(__file__).resolve().parents[2] / "data"
        if not repo_data.exists():
            self.skipTest("data/ dir not found")
        result = load_adapter_data(repo_data)
        self.assertIsInstance(result, dict)
        # Real adapter_status.json has 'adapters' list
        if "adapters" in result:
            self.assertIsInstance(result["adapters"], list)

    def test_positions_data_merged(self):
        """positions_data key always present in result."""
        result = load_adapter_data(Path("/does/not/exist"))
        self.assertIn("positions_data", result)


if __name__ == "__main__":
    unittest.main()
