"""MP-015/MP-016 tests — telegram_client (Keychain) & alert_manager.

subprocess and urllib are mocked everywhere: no real Keychain reads, no real
Telegram API calls. The cycle_runner alert hook is exercised on a tmp data
dir with alert_manager mocked out.
"""
from __future__ import annotations

import json
import urllib.error
from unittest import mock

import pytest

from spa_core.alerts import alert_manager, telegram_client


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _keychain_proc(stdout: str = "", returncode: int = 0) -> mock.Mock:
    return mock.Mock(returncode=returncode, stdout=stdout, stderr="")


class _FakeResp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, status: int = 200, body: dict | None = None):
        self.status = status
        self._body = body

    def read(self):
        return json.dumps(self._body or {}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_creds():
    """Patch both Keychain getters to fixed fake credentials."""
    return mock.patch.multiple(
        telegram_client,
        get_bot_token=mock.Mock(return_value="123:FAKE_TOKEN"),
        get_chat_id=mock.Mock(return_value="42"),
    )


# ─── telegram_client: Keychain (MP-015) ──────────────────────────────────────


def test_get_bot_token_reads_keychain():
    with mock.patch.object(
        telegram_client.subprocess, "run",
        return_value=_keychain_proc("123:FAKE_TOKEN\n"),
    ) as run:
        assert telegram_client.get_bot_token() == "123:FAKE_TOKEN"
    cmd = run.call_args.args[0]
    assert cmd[:2] == ["security", "find-generic-password"]
    assert "TELEGRAM_BOT_TOKEN_SPA" in cmd and "-w" in cmd


def test_get_chat_id_reads_keychain():
    with mock.patch.object(
        telegram_client.subprocess, "run", return_value=_keychain_proc("42\n")
    ) as run:
        assert telegram_client.get_chat_id() == "42"
    assert "TELEGRAM_CHAT_ID_SPA" in run.call_args.args[0]


@pytest.mark.parametrize(
    "proc",
    [_keychain_proc("", returncode=44), _keychain_proc("")],
    ids=["nonzero_exit", "empty_stdout"],
)
def test_missing_keychain_entry_raises(proc):
    with mock.patch.object(telegram_client.subprocess, "run", return_value=proc):
        with pytest.raises(EnvironmentError, match="not found in Keychain"):
            telegram_client.get_bot_token()


def test_keychain_binary_missing_raises():
    with mock.patch.object(
        telegram_client.subprocess, "run", side_effect=FileNotFoundError("security")
    ):
        with pytest.raises(EnvironmentError, match="not found in Keychain"):
            telegram_client.get_chat_id()


# ─── telegram_client: send_message (MP-015) ──────────────────────────────────


def test_send_message_posts_markdown_payload():
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen", return_value=_FakeResp(200)
    ) as urlopen:
        assert telegram_client.send_message("*hi*") is True

    req = urlopen.call_args.args[0]
    assert req.full_url == "https://api.telegram.org/bot123:FAKE_TOKEN/sendMessage"
    assert urlopen.call_args.kwargs["timeout"] == 10
    body = json.loads(req.data.decode("utf-8"))
    assert body == {
        "chat_id": "42",
        "text": "*hi*",
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }


def test_send_message_retries_once_on_network_error():
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen",
        side_effect=[urllib.error.URLError("conn reset"), _FakeResp(200)],
    ) as urlopen:
        assert telegram_client.send_message("hi") is True
    assert urlopen.call_count == 2


def test_send_message_false_after_retry_exhausted(caplog):
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen",
        side_effect=urllib.error.URLError("down"),
    ) as urlopen, caplog.at_level("WARNING", "spa.alerts.telegram_client"):
        assert telegram_client.send_message("hi") is False
    assert urlopen.call_count == 2  # 1 attempt + 1 retry, no more
    assert "failed" in caplog.text


def test_send_message_400_retries_once_as_plain_text():
    # On HTTP 400 (Markdown/HTML parse choke) the client retries ONCE with parse_mode
    # stripped so alerts aren't silently dropped. Mock always 400s → exactly 2 attempts.
    err = urllib.error.HTTPError(
        "https://api.telegram.org", 400, "Bad Request", {}, None
    )
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen", side_effect=err
    ) as urlopen:
        assert telegram_client.send_message("hi") is False
    assert urlopen.call_count == 2  # original + one plain-text fallback


def test_send_message_no_retry_on_non_400_http_error():
    err = urllib.error.HTTPError(
        "https://api.telegram.org", 500, "Server Error", {}, None
    )
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen", side_effect=err
    ) as urlopen:
        assert telegram_client.send_message("hi") is False
    assert urlopen.call_count == 1  # non-400 HTTP error → no retry


def test_send_message_no_raise_without_credentials(caplog):
    with mock.patch.object(
        telegram_client, "get_bot_token",
        side_effect=EnvironmentError("Telegram credentials not found in Keychain"),
    ), caplog.at_level("WARNING", "spa.alerts.telegram_client"):
        assert telegram_client.send_message("hi") is False
    assert "skipped" in caplog.text


# ─── alert_manager: formatting & fail-safety (MP-016) ────────────────────────


def _sent_text(fn, *args):
    """Run an alert function with send_message(_with_keyboard) mocked; return text."""
    # _send() uses send_message_with_keyboard when keyboard=True (default),
    # and send_message when keyboard=False. Patch both so the helper works for all.
    # Also bypass _already_sent_today dedup so tests are hermetic.
    with mock.patch.object(
        alert_manager.telegram_client, "send_message", return_value=True
    ) as send_plain, mock.patch.object(
        alert_manager.telegram_client, "send_message_with_keyboard", return_value=True
    ) as send_kb, mock.patch(
        "spa_core.alerts.alert_manager._already_sent_today", return_value=False
    ), mock.patch(
        "spa_core.alerts.alert_manager._mark_sent_today",
    ):
        assert fn(*args) is True
    # Whichever was called, extract the first positional arg (the text).
    if send_kb.called:
        return send_kb.call_args.args[0]
    return send_plain.call_args.args[0]


def test_send_daily_summary_format():
    report = {
        "date": "2026-06-10",
        "equity_usd": 100008.61,
        "daily_pnl_pct": 0.0123,
        "golive_status": "PRE-LIVE",
    }
    text = _sent_text(alert_manager.send_daily_summary, report)
    # MP-016b updated the format; check key substrings rather than exact match.
    assert "2026-06-10" in text
    assert "100,009" in text or "100008" in text  # equity value present


def test_send_daily_summary_negative_pnl_sign():
    text = _sent_text(
        alert_manager.send_daily_summary,
        {"date": "2026-06-10", "equity_usd": 99500, "daily_pnl_pct": -0.5,
         "golive_status": "PRE-LIVE"},
    )
    # Must contain the equity, must not have a "+-" artifact.
    assert "99,500" in text or "99500" in text
    assert "+-" not in text


def test_send_red_flag_russian_format():
    """send_red_flag uses Russian formatting (MP-136): header + alert blocks."""
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
            "protocol": "maple",
            "category": "token_unlock",
            "message": "Token unlock 1.80% of supply (MPL) at 2026-06-01T00:00:00Z",
            "evidence": {},
        },
    ]
    text = _sent_text(alert_manager.send_red_flag, alerts)
    assert text.startswith("🚨 *SPA — Важные события*")
    assert "🔴 Aave V3" in text
    assert "Экстренное голосование в DAO" in text
    assert "🟡 Maple Finance" in text
    assert "Разблокировка токенов MPL" in text


def test_send_red_flag_empty_list():
    """Empty flag list → 'Новых событий нет.' message, still returns True."""
    text = _sent_text(alert_manager.send_red_flag, [])
    assert "Новых событий нет" in text


def test_send_gap_alert_format():
    text = _sent_text(alert_manager.send_gap_alert, 49.26)
    assert text == "⏰ *SPA Gap Detected*\nПоследний цикл: 49.3ч назад"


def test_send_golive_change_format():
    text = _sent_text(alert_manager.send_golive_change, "NOT READY", "READY")
    assert text == "🟢 *SPA Go-Live*\nСтатус изменился: NOT READY → READY"


def test_send_startup_test_format():
    text = _sent_text(alert_manager.send_startup_test)
    # Text may have an extended suffix (MP-016b); check core content.
    assert "✅" in text
    assert "SPA Telegram подключён" in text
    assert "Алерты работают" in text


def test_alert_manager_fail_safe_on_send_crash(caplog):
    # send_startup_test uses keyboard=True → send_message_with_keyboard; crash both.
    with mock.patch.object(
        alert_manager.telegram_client, "send_message",
        side_effect=RuntimeError("boom"),
    ), mock.patch.object(
        alert_manager.telegram_client, "send_message_with_keyboard",
        side_effect=RuntimeError("boom"),
    ), caplog.at_level("WARNING", "spa.alerts.alert_manager"):
        assert alert_manager.send_startup_test() is False
    assert "alert skipped" in caplog.text


def test_alert_manager_fail_safe_on_bad_report():
    with mock.patch.object(
        alert_manager.telegram_client, "send_message", return_value=True
    ) as send:
        assert alert_manager.send_daily_summary({"equity_usd": "garbage"}) is False
    send.assert_not_called()


# ─── cycle_runner hook (MP-016) ──────────────────────────────────────────────


def test_run_cycle_alerts_dispatch(tmp_path):
    from spa_core.paper_trading import cycle_runner

    date = "2026-06-10"
    (tmp_path / f"daily_report_{date}.json").write_text(json.dumps(
        {"date": date, "equity_usd": 100008.61, "daily_pnl_pct": 0.0,
         "golive_status": "PRE-LIVE"}
    ))
    (tmp_path / "red_flags.json").write_text(json.dumps(
        {"red_flags": [{"severity": "CRITICAL", "protocol": "aave-v3",
                        "message": "gov proposal"}]}
    ))
    (tmp_path / "gap_monitor.json").write_text(json.dumps(
        {"gap_detected": True, "hours_since_last_entry": 49.26}
    ))

    with mock.patch.multiple(
        alert_manager,
        send_daily_summary=mock.Mock(return_value=True),
        send_red_flag=mock.Mock(return_value=True),
        send_gap_alert=mock.Mock(return_value=True),
    ), mock.patch(
        # N12: _run_cycle_alerts (+ _should_send_alert) moved to cycle_reporting;
        # patch the live call-site module. cycle_runner re-exports both names.
        "spa_core.paper_trading.cycle_reporting._should_send_alert",
        return_value=True,
    ):
        sent = cycle_runner._run_cycle_alerts(tmp_path, date=date)
        assert sent == {"daily_summary": True, "red_flags": True, "gap": True}
        # MP-136: cycle_runner passes raw dicts, not pre-formatted strings
        alert_manager.send_red_flag.assert_called_once_with(
            [{"severity": "CRITICAL", "protocol": "aave-v3", "message": "gov proposal"}]
        )
        alert_manager.send_gap_alert.assert_called_once_with(49.26)


def test_run_cycle_alerts_quiet_when_nothing_to_send(tmp_path):
    """No report, empty flags, no gap → nothing sent, nothing raised."""
    from spa_core.paper_trading import cycle_runner

    (tmp_path / "red_flags.json").write_text(json.dumps({"red_flags": []}))
    (tmp_path / "gap_monitor.json").write_text(json.dumps({"gap_detected": False}))

    with mock.patch.object(
        alert_manager.telegram_client, "send_message", return_value=True
    ) as send:
        sent = cycle_runner._run_cycle_alerts(tmp_path, date="2026-06-10")
    assert sent == {}
    send.assert_not_called()


# ─── alert_history.json audit trail (observability) ──────────────────────────


@pytest.fixture
def _history_to_tmp(tmp_path, monkeypatch):
    """Redirect alert_history.json to a tmp file and enable recording under pytest."""
    hist = tmp_path / "alert_history.json"
    monkeypatch.setattr(telegram_client, "_HISTORY_STATE", hist)
    monkeypatch.setenv("SPA_ALERT_HISTORY_TEST", "1")
    return hist


def _read_hist(path):
    return json.loads(path.read_text())


def test_alert_history_records_success_with_message_id(_history_to_tmp):
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen",
        return_value=_FakeResp(200, {"ok": True, "result": {"message_id": 777}}),
    ):
        assert telegram_client.send_message("🟢 *SPA Go-Live*\nx") is True

    doc = _read_hist(_history_to_tmp)
    assert doc["schema_version"] == 1
    assert doc["source"] == "telegram_client"
    assert doc["count"] == 1
    e = doc["entries"][0]
    assert e["ok"] is True
    assert e["message_id"] == 777
    assert e["type"] == "golive"
    assert "ts" in e and "preview" in e
    assert "error" not in e


def test_alert_history_records_failure_with_error(_history_to_tmp):
    err = urllib.error.HTTPError(
        "https://api.telegram.org", 500, "Server Error", {}, None
    )
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen", side_effect=err
    ):
        assert telegram_client.send_message("hi") is False

    e = _read_hist(_history_to_tmp)["entries"][0]
    assert e["ok"] is False
    assert "500" in e["error"]
    assert "message_id" not in e


def test_alert_history_records_missing_credentials(_history_to_tmp):
    with mock.patch.object(
        telegram_client, "get_bot_token",
        side_effect=EnvironmentError("Telegram credentials not found in Keychain"),
    ):
        assert telegram_client.send_message("hi") is False

    e = _read_hist(_history_to_tmp)["entries"][0]
    assert e["ok"] is False
    assert "Keychain" in e["error"]


def test_alert_history_is_ring_buffered(_history_to_tmp, monkeypatch):
    monkeypatch.setattr(telegram_client, "HISTORY_MAX", 3)
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen",
        return_value=_FakeResp(200, {"result": {"message_id": 1}}),
    ):
        for i in range(5):
            telegram_client.send_message(f"msg {i}")

    doc = _read_hist(_history_to_tmp)
    assert doc["count"] == 3  # capped
    assert len(doc["entries"]) == 3
    assert doc["entries"][-1]["preview"] == "msg 4"  # newest retained


def test_alert_history_disabled_under_pytest_by_default(tmp_path, monkeypatch):
    """Without SPA_ALERT_HISTORY_TEST the recorder is a no-op under pytest."""
    hist = tmp_path / "alert_history.json"
    monkeypatch.setattr(telegram_client, "_HISTORY_STATE", hist)
    monkeypatch.delenv("SPA_ALERT_HISTORY_TEST", raising=False)
    with _patch_creds(), mock.patch.object(
        telegram_client.urllib.request, "urlopen",
        return_value=_FakeResp(200, {"result": {"message_id": 1}}),
    ):
        assert telegram_client.send_message("hi") is True
    assert not hist.exists()
