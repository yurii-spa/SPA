"""MP-136: Tests for spa_core/alerts/telegram_format_ru.py

Covers:
  - format_timestamp_ru:       various months, edge cases
  - PROTOCOL_NAMES:            key mappings
  - SEVERITY_EMOJI:            CRITICAL → 🔴, WARN → 🟡, INFO → 🔵
  - format_alert_ru:           token_unlock, governance_proposal, tvl_drop,
                               apy_spike, unknown category, missing fields,
                               explanation included
  - format_alert_detail_ru:    detail sections, source URL, never raises
  - build_detail_keyboard:     buttons generated for CRITICAL/WARN, skips INFO
  - parse_detail_callback:     round-trip encode/decode, unknown commands
  - format_message_ru:         empty list, single alert, multiple alerts,
                               legacy string input, never raises on garbage
"""
from __future__ import annotations

import pytest

from spa_core.alerts.telegram_format_ru import (
    MONTH_NAMES_RU,
    PROTOCOL_NAMES,
    SEVERITY_EMOJI,
    build_detail_keyboard,
    format_alert_detail_ru,
    format_alert_ru,
    format_message_ru,
    format_timestamp_ru,
    parse_detail_callback,
)


# ─── format_timestamp_ru ─────────────────────────────────────────────────────


class TestFormatTimestampRu:
    def test_june(self):
        assert format_timestamp_ru("2026-06-03T00:00:00Z") == "3 июня 2026 г."

    def test_january(self):
        assert format_timestamp_ru("2026-01-15T12:00:00Z") == "15 января 2026 г."

    def test_december(self):
        assert format_timestamp_ru("2025-12-31T00:00:00Z") == "31 декабря 2025 г."

    def test_bare_date(self):
        assert format_timestamp_ru("2026-06-01") == "1 июня 2026 г."

    def test_empty_string_returns_empty(self):
        assert format_timestamp_ru("") == ""

    def test_bad_input_returns_as_is(self):
        assert format_timestamp_ru("not-a-date") == "not-a-date"

    def test_all_months_present(self):
        """MONTH_NAMES_RU must have all 12 months."""
        assert set(MONTH_NAMES_RU.keys()) == set(range(1, 13))

    def test_may_uses_genitive(self):
        assert format_timestamp_ru("2026-05-20T00:00:00Z") == "20 мая 2026 г."

    def test_different_year(self):
        assert format_timestamp_ru("2030-03-07T00:00:00Z") == "7 марта 2030 г."

    def test_all_12_months_round_trip(self):
        """Spot-check each month is represented correctly."""
        expected = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        ]
        for month_num, expected_name in enumerate(expected, start=1):
            iso = f"2026-{month_num:02d}-01"
            result = format_timestamp_ru(iso)
            assert expected_name in result, f"Month {month_num}: expected '{expected_name}' in '{result}'"


# ─── PROTOCOL_NAMES mapping ───────────────────────────────────────────────────


class TestProtocolNames:
    def test_aave_v3(self):
        assert PROTOCOL_NAMES["aave-v3"] == "Aave V3"

    def test_ethena_susde(self):
        assert PROTOCOL_NAMES["ethena-susde"] == "Ethena sUSDe"

    def test_pendle_pt(self):
        assert PROTOCOL_NAMES["pendle-pt"] == "Pendle PT"

    def test_compound_v3(self):
        assert PROTOCOL_NAMES["compound-v3"] == "Compound V3"

    def test_morpho_blue(self):
        assert PROTOCOL_NAMES["morpho"] == "Morpho Blue"

    def test_maple_finance(self):
        assert PROTOCOL_NAMES["maple"] == "Maple Finance"

    def test_sky_susds(self):
        assert PROTOCOL_NAMES["sky"] == "Sky / sUSDS"

    def test_euler_v2(self):
        assert PROTOCOL_NAMES["euler-v2"] == "Euler V2"

    def test_unknown_slug_passthrough(self):
        """Unmapped slugs should pass through as-is in format_alert_ru."""
        alert = {
            "severity": "WARN",
            "protocol": "unknown-protocol-xyz",
            "category": "tvl_drop",
            "message": "TVL dropped 20.0% over 24h",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert "unknown-protocol-xyz" in text


# ─── SEVERITY_EMOJI mapping ───────────────────────────────────────────────────


class TestSeverityEmoji:
    def test_critical_is_red(self):
        assert SEVERITY_EMOJI["CRITICAL"] == "🔴"

    def test_warn_is_yellow(self):
        assert SEVERITY_EMOJI["WARN"] == "🟡"

    def test_info_is_blue(self):
        assert SEVERITY_EMOJI["INFO"] == "🔵"

    def test_ok_is_checkmark(self):
        assert SEVERITY_EMOJI["OK"] == "✅"

    def test_critical_emoji_in_alert(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "aave-v3",
            "category": "tvl_drop",
            "message": "TVL dropped 55.0% over 7d",
            "evidence": {},
        }
        assert format_alert_ru(alert).startswith("🔴")

    def test_warn_emoji_in_alert(self):
        alert = {
            "severity": "WARN",
            "protocol": "maple",
            "category": "tvl_drop",
            "message": "TVL dropped 20.0% over 24h",
            "evidence": {},
        }
        assert format_alert_ru(alert).startswith("🟡")


# ─── format_alert_ru — token_unlock ──────────────────────────────────────────


class TestFormatAlertTokenUnlock:
    def _alert(self, pct="6.40", symbol="ENA", ts="2026-06-03T00:00:00Z"):
        return {
            "severity": "CRITICAL",
            "protocol": "ethena-susde",
            "category": "token_unlock",
            "message": f"Token unlock {pct}% of supply ({symbol}) at {ts}",
            "evidence": {
                "pct_supply": float(pct),
                "symbol": symbol,
                "unlock_at": ts,
            },
        }

    def test_contains_protocol_name(self):
        assert "Ethena sUSDe" in format_alert_ru(self._alert())

    def test_contains_symbol(self):
        assert "ENA" in format_alert_ru(self._alert())

    def test_contains_percentage(self):
        assert "6.40%" in format_alert_ru(self._alert())

    def test_contains_russian_date(self):
        text = format_alert_ru(self._alert())
        assert "3 июня 2026 г." in text
        # No double period
        assert "г.." not in text

    def test_contains_headline(self):
        assert "Разблокировка токенов" in format_alert_ru(self._alert())

    def test_contains_explanation(self):
        """Alert block must include an explanation of why this is notable."""
        text = format_alert_ru(self._alert())
        # Explanation contains Russian text about market pressure
        assert "давление" in text.lower() or "рынок" in text.lower() or "цен" in text.lower()

    def test_pendle_warn(self):
        alert = {
            "severity": "WARN",
            "protocol": "pendle-pt",
            "category": "token_unlock",
            "message": "Token unlock 1.80% of supply (PENDLE) at 2026-06-01T00:00:00Z",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert "🟡" in text
        assert "Pendle PT" in text
        assert "PENDLE" in text
        assert "1.80%" in text
        assert "1 июня 2026 г." in text


# ─── format_alert_ru — governance_proposal ───────────────────────────────────


class TestFormatAlertGovernance:
    def _governance(self, tag, title="Some governance action"):
        return {
            "severity": "CRITICAL",
            "protocol": "aave-v3",
            "category": "governance_proposal",
            "message": f"Risk-sensitive proposal [{tag}]: {title}",
            "evidence": {"tag": tag},
        }

    def test_emergency_headline(self):
        text = format_alert_ru(self._governance("emergency", "Emergency freeze"))
        assert "Экстренное голосование в DAO" in text

    def test_upgrade_headline(self):
        text = format_alert_ru(self._governance("upgrade", "Upgrade Comet"))
        assert "Предложение по обновлению протокола" in text

    def test_risk_param_headline(self):
        text = format_alert_ru(self._governance("risk-param", "Risk param change"))
        assert "Изменение риск-параметров DAO" in text

    def test_treasury_headline(self):
        text = format_alert_ru(self._governance("treasury", "Treasury proposal"))
        assert "Предложение по казне DAO" in text

    def test_aave_protocol_name(self):
        text = format_alert_ru(self._governance("emergency"))
        assert "Aave V3" in text

    def test_critical_emoji(self):
        text = format_alert_ru(self._governance("emergency"))
        assert text.startswith("🔴")

    def test_contains_explanation(self):
        """Alert block must include an explanation for governance events."""
        text = format_alert_ru(self._governance("risk-param"))
        # Explanation mentions following/monitoring the vote
        assert any(word in text.lower() for word in ["голосов", "предложен", "параметр"])


# ─── format_alert_ru — other categories & edge cases ─────────────────────────


class TestFormatAlertOther:
    def test_missing_fields_no_raise(self):
        result = format_alert_ru({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_category_uses_message(self):
        alert = {
            "severity": "INFO",
            "protocol": "compound-v3",
            "category": "some_new_category",
            "message": "APY below benchmark",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert "APY below benchmark" in text
        assert "Compound V3" in text

    def test_tvl_drop_format(self):
        alert = {
            "severity": "WARN",
            "protocol": "euler-v2",
            "category": "tvl_drop",
            "message": "TVL dropped 33.4% over 7d",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert "Euler V2" in text
        assert "Падение ликвидности" in text
        assert "33.4%" in text
        assert "7 дней" in text

    def test_tvl_drop_explanation(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "maple",
            "category": "tvl_drop",
            "message": "TVL dropped 55.0% over 7d",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        # Should explain about TVL/liquidity issues
        assert any(word in text.lower() for word in ["ликвидн", "отток", "apy"])

    def test_apy_spike_format(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "ethena-susde",
            "category": "apy_spike",
            "message": "APY 18.40% is 2.56x baseline 7.20%",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert "Аномальный рост APY" in text
        assert "18.40%" in text
        assert "2.56x" in text

    def test_apy_spike_explanation(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "pendle-pt",
            "category": "apy_spike",
            "message": "APY 24.60% is 4.03x baseline 6.10%",
            "evidence": {},
        }
        text = format_alert_ru(alert)
        assert any(word in text.lower() for word in ["риск", "apy", "аномал", "субсид"])


# ─── format_alert_detail_ru ───────────────────────────────────────────────────


class TestFormatAlertDetailRu:
    def test_token_unlock_detail_sections(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "ethena-susde",
            "category": "token_unlock",
            "message": "Token unlock 6.40% of supply (ENA) at 2026-06-03T00:00:00Z",
            "evidence": {
                "pct_supply": 6.4,
                "symbol": "ENA",
                "unlock_at": "2026-06-03T00:00:00Z",
                "tokens": 420_000_000,
            },
            "detected_at": "2026-06-01T00:00:00Z",
        }
        text = format_alert_detail_ru(alert)
        assert "Что произошло" in text
        assert "Влияние" in text
        assert "Рекомендованные действия" in text
        # Source URL for token unlock
        assert "tokenunlocks" in text

    def test_governance_detail_has_source_snapshot(self):
        alert = {
            "severity": "CRITICAL",
            "protocol": "aave-v3",
            "category": "governance_proposal",
            "message": "Risk-sensitive proposal [emergency]: Emergency shutdown",
            "evidence": {"tag": "emergency", "space": "aave.eth"},
            "detected_at": "2026-06-01T00:00:00Z",
        }
        text = format_alert_detail_ru(alert)
        assert "snapshot.org" in text
        assert "aave.eth" in text

    def test_tvl_drop_detail_has_tvl_figures(self):
        alert = {
            "severity": "WARN",
            "protocol": "euler-v2",
            "category": "tvl_drop",
            "message": "TVL dropped 33.4% over 7d",
            "evidence": {
                "delta_7d": -33.4,
                "tvl_now": 780_000_000.0,
            },
            "detected_at": "2026-06-01T00:00:00Z",
        }
        text = format_alert_detail_ru(alert)
        assert "Euler V2" in text
        assert "Что произошло" in text
        assert "defillama.com" in text

    def test_never_raises_on_empty_dict(self):
        result = format_alert_detail_ru({})
        assert isinstance(result, str)

    def test_never_raises_on_garbage(self):
        try:
            result = format_alert_detail_ru({"severity": None, "protocol": 123})  # type: ignore
        except Exception as exc:
            pytest.fail(f"format_alert_detail_ru raised: {exc}")
        assert isinstance(result, str)


# ─── build_detail_keyboard ────────────────────────────────────────────────────


class TestBuildDetailKeyboard:
    def test_critical_alert_gets_button(self):
        alerts = [
            {
                "severity": "CRITICAL",
                "protocol": "aave-v3",
                "category": "governance_proposal",
            }
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        rows = kb["inline_keyboard"]
        assert len(rows) == 1
        assert rows[0][0]["callback_data"] == "detail_aave-v3__governance_proposal"

    def test_warn_alert_gets_button(self):
        alerts = [
            {"severity": "WARN", "protocol": "maple", "category": "token_unlock"}
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        assert kb["inline_keyboard"][0][0]["callback_data"] == "detail_maple__token_unlock"

    def test_info_alert_no_button(self):
        alerts = [
            {"severity": "INFO", "protocol": "compound-v3", "category": "tvl_drop"}
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is None

    def test_empty_list_returns_none(self):
        assert build_detail_keyboard([]) is None

    def test_multiple_alerts_multiple_buttons(self):
        alerts = [
            {"severity": "CRITICAL", "protocol": "aave-v3", "category": "governance_proposal"},
            {"severity": "WARN", "protocol": "ethena-susde", "category": "token_unlock"},
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        assert len(kb["inline_keyboard"]) == 2

    def test_deduplicate_same_protocol_category(self):
        """Duplicate (protocol, category) pairs should only produce one button."""
        alerts = [
            {"severity": "CRITICAL", "protocol": "aave-v3", "category": "tvl_drop"},
            {"severity": "WARN", "protocol": "aave-v3", "category": "tvl_drop"},
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        assert len(kb["inline_keyboard"]) == 1

    def test_button_text_contains_protocol_name(self):
        alerts = [
            {"severity": "CRITICAL", "protocol": "pendle-pt", "category": "token_unlock"}
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        text = kb["inline_keyboard"][0][0]["text"]
        assert "Pendle PT" in text
        assert "📋" in text

    def test_callback_data_within_64_bytes(self):
        alerts = [
            {"severity": "CRITICAL", "protocol": "curve-usdc-usdt", "category": "governance_proposal"}
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        cb = kb["inline_keyboard"][0][0]["callback_data"]
        assert len(cb.encode("utf-8")) <= 64


# ─── parse_detail_callback ────────────────────────────────────────────────────


class TestParseDetailCallback:
    def test_valid_governance_proposal(self):
        result = parse_detail_callback("detail_aave-v3__governance_proposal")
        assert result == ("aave-v3", "governance_proposal")

    def test_valid_token_unlock(self):
        result = parse_detail_callback("detail_ethena-susde__token_unlock")
        assert result == ("ethena-susde", "token_unlock")

    def test_valid_tvl_drop(self):
        result = parse_detail_callback("detail_euler-v2__tvl_drop")
        assert result == ("euler-v2", "tvl_drop")

    def test_valid_apy_spike(self):
        result = parse_detail_callback("detail_pendle-pt__apy_spike")
        assert result == ("pendle-pt", "apy_spike")

    def test_unknown_command_returns_none(self):
        assert parse_detail_callback("cmd_now") is None
        assert parse_detail_callback("cmd_status") is None

    def test_empty_string_returns_none(self):
        assert parse_detail_callback("") is None

    def test_detail_without_separator_returns_none(self):
        assert parse_detail_callback("detail_aave-v3") is None

    def test_round_trip_consistency(self):
        """build_detail_keyboard → parse_detail_callback should be idempotent."""
        alerts = [
            {"severity": "CRITICAL", "protocol": "compound-v3", "category": "tvl_drop"},
        ]
        kb = build_detail_keyboard(alerts)
        assert kb is not None
        cb = kb["inline_keyboard"][0][0]["callback_data"]
        result = parse_detail_callback(cb)
        assert result == ("compound-v3", "tvl_drop")


# ─── format_message_ru ────────────────────────────────────────────────────────


class TestFormatMessageRu:
    def test_empty_list_returns_no_events(self):
        text = format_message_ru([])
        assert "Новых событий нет" in text
        assert "✅" in text

    def test_single_alert_has_header(self):
        alerts = [
            {
                "severity": "WARN",
                "protocol": "maple",
                "category": "token_unlock",
                "message": "Token unlock 1.80% of supply (MPL) at 2026-06-01T00:00:00Z",
                "evidence": {},
            }
        ]
        text = format_message_ru(alerts)
        assert text.startswith("🚨 *SPA — Важные события*")

    def test_multiple_alerts_all_present(self):
        alerts = [
            {
                "severity": "CRITICAL",
                "protocol": "aave-v3",
                "category": "governance_proposal",
                "message": "Risk-sensitive proposal [emergency]: Emergency shutdown",
                "evidence": {"tag": "emergency"},
            },
            {
                "severity": "WARN",
                "protocol": "pendle-pt",
                "category": "token_unlock",
                "message": "Token unlock 1.80% of supply (PENDLE) at 2026-06-01T00:00:00Z",
                "evidence": {},
            },
            {
                "severity": "CRITICAL",
                "protocol": "ethena-susde",
                "category": "token_unlock",
                "message": "Token unlock 6.40% of supply (ENA) at 2026-06-03T00:00:00Z",
                "evidence": {},
            },
        ]
        text = format_message_ru(alerts)
        assert "🔴 Aave V3" in text
        assert "🟡 Pendle PT" in text
        assert "🔴 Ethena sUSDe" in text
        assert text.count("Разблокировка токенов") == 2

    def test_no_trailing_blank_line(self):
        alerts = [
            {
                "severity": "INFO",
                "protocol": "compound-v3",
                "category": "tvl_drop",
                "message": "TVL dropped 18.0% over 24h",
                "evidence": {},
            }
        ]
        text = format_message_ru(alerts)
        assert not text.endswith("\n")

    def test_legacy_string_input_fallback(self):
        """Legacy list[str] input must not crash — produces bullet lines."""
        text = format_message_ru(["CRITICAL aave-v3: something", "WARN maple: unlock"])
        assert "🚨 *SPA — Важные события*" in text
        assert "• CRITICAL aave-v3: something" in text
        assert "• WARN maple: unlock" in text

    def test_never_raises_on_garbage(self):
        try:
            result = format_message_ru(None)  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"format_message_ru raised on None: {exc}")
        assert isinstance(result, str)
