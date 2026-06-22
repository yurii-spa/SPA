"""tests/test_telegram_manager.py — Unit tests for TelegramManager.

Tests are network-free: Telegram send is monkey-patched to record calls.
Tests are filesystem-safe: each test uses a tmp dir for cooldown state.

Run:
    python3 -m pytest tests/test_telegram_manager.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
import sys
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts.telegram_manager import (
    TelegramManager,
    _dedup_key,
    _save_cooldown_state,
    CATEGORY_COOLDOWNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path, *, production: bool = True) -> TelegramManager:
    """Create a TelegramManager that writes dedup state to a temp directory."""
    return TelegramManager(data_dir=tmp_path, production=production)


def _patch_send(mgr: TelegramManager, return_value: bool = True):
    """Patch the raw Telegram HTTP call on the given manager instance."""
    return patch.object(
        type(mgr), "_send_raw", staticmethod(lambda *a, **kw: return_value)
    )


def _patch_keychain(token: str = "TOK", chat_id: str = "123"):
    """Patch Keychain reads to return a fake token and chat_id."""
    def fake_keychain(key: str) -> str | None:
        if "TOKEN" in key:
            return token
        if "CHAT" in key:
            return chat_id
        return None
    return patch("spa_core.alerts.telegram_manager._keychain_get", side_effect=fake_keychain)


# ---------------------------------------------------------------------------
# Tests: cooldown suppression
# ---------------------------------------------------------------------------

class TestCooldownSuppression:
    """The manager must suppress repeated sends within the cooldown window."""

    def test_first_send_is_allowed(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            result = mgr.send("hello", title="t1", category="alert")
        assert result is True

    def test_second_send_within_cooldown_is_suppressed(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("first", title="t1", category="alert")
            # Immediately try again — should be suppressed
            result = mgr.send("second", title="t1", category="alert")
        assert result is False

    def test_different_titles_not_suppressed_by_each_other(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            r1 = mgr.send("msg A", title="title_a", category="alert")
            r2 = mgr.send("msg B", title="title_b", category="alert")
        assert r1 is True
        assert r2 is True

    def test_cooldown_state_persists_across_manager_instances(self, tmp_path):
        """New manager in same data_dir must still see the cooldown."""
        mgr1 = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr1, return_value=True):
            mgr1.send("first", title="persistent", category="alert")

        # New manager instance, same data dir
        mgr2 = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr2, return_value=True):
            result = mgr2.send("second", title="persistent", category="alert")
        assert result is False, (
            "Second manager should see the cooldown written by the first"
        )

    def test_cooldown_expires(self, tmp_path):
        """After cooldown expires the message is allowed again."""
        mgr = _make_manager(tmp_path)
        # Write a stale cooldown entry (2 hours ago)
        key = _dedup_key("alert", "stale_title")
        stale_ts = time.time() - 7200  # 2 hours ago
        state = {key: stale_ts}
        _save_cooldown_state(tmp_path / "telegram_cooldowns.json", state)

        with _patch_keychain(), _patch_send(mgr, return_value=True):
            result = mgr.send("post-expiry", title="stale_title", category="alert")
        assert result is True

    def test_is_in_cooldown_true_after_send(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("msg", title="t_check", category="alert")
        assert mgr.is_in_cooldown(title="t_check", category="alert") is True

    def test_cooldown_remaining_minutes_positive(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("msg", title="t_rem", category="alert")
        remaining = mgr.cooldown_remaining_minutes(title="t_rem", category="alert")
        # alert cooldown is 1h = 60 min; remaining should be ~60
        assert 58 <= remaining <= 60


# ---------------------------------------------------------------------------
# Tests: P0 bypasses cooldown
# ---------------------------------------------------------------------------

class TestP0BypassesCooldown:
    """P0 messages must ALWAYS send — they never check cooldown."""

    def test_p0_sends_immediately(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            r1 = mgr.send("kill-switch!", title="kill_switch", category="p0")
            r2 = mgr.send("kill-switch again!", title="kill_switch", category="p0")
        assert r1 is True
        assert r2 is True, "P0 must not be suppressed even on immediate repeat"

    def test_p0_is_never_in_cooldown(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("p0 msg", title="infra_down", category="p0")
        assert mgr.is_in_cooldown(title="infra_down", category="p0") is False

    def test_p0_remaining_minutes_always_zero(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.cooldown_remaining_minutes(title="any", category="p0") == 0


# ---------------------------------------------------------------------------
# Tests: debug category suppressed in production
# ---------------------------------------------------------------------------

class TestDebugCategory:
    """Debug messages must be suppressed in production mode."""

    def test_debug_suppressed_in_production(self, tmp_path):
        mgr = _make_manager(tmp_path, production=True)
        sends: List[str] = []
        with _patch_keychain(), patch.object(
            TelegramManager, "_send_raw", staticmethod(lambda *a, **kw: sends.append("sent") or True)
        ):
            result = mgr.send("debug info", title="debug_thing", category="debug")
        assert result is False
        assert not sends, "No HTTP call should be made for debug in production"

    def test_debug_allowed_in_non_production(self, tmp_path):
        mgr = _make_manager(tmp_path, production=False)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            result = mgr.send("debug info", title="debug_thing", category="debug")
        assert result is True


# ---------------------------------------------------------------------------
# Tests: category cooldown values
# ---------------------------------------------------------------------------

class TestCategoryDefaults:
    """Verify built-in cooldown defaults are sane."""

    def test_daily_cooldown_is_at_least_22h(self):
        assert CATEGORY_COOLDOWNS["daily"] >= 22 * 3600

    def test_alert_cooldown_is_at_least_30min(self):
        assert CATEGORY_COOLDOWNS["alert"] >= 1800

    def test_p0_cooldown_is_zero(self):
        assert CATEGORY_COOLDOWNS["p0"] == 0

    def test_debug_cooldown_is_negative(self):
        assert CATEGORY_COOLDOWNS["debug"] < 0

    def test_milestone_cooldown_between_1h_and_12h(self):
        c = CATEGORY_COOLDOWNS["milestone"]
        assert 3600 <= c <= 12 * 3600


# ---------------------------------------------------------------------------
# Tests: cooldown override
# ---------------------------------------------------------------------------

class TestCooldownOverride:
    def test_override_zero_allows_immediate_resend(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("first", title="ov", category="alert")
            result = mgr.send(
                "second",
                title="ov",
                category="alert",
                cooldown_override_hours=0,
            )
        # cooldown_override_hours=0 → 0 seconds → no suppression
        assert result is True

    def test_override_large_extends_cooldown(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("first", title="big_cd", category="daily", cooldown_override_hours=48)
        # Check that a 48h cooldown is active
        remaining = mgr.cooldown_remaining_minutes(title="big_cd", category="daily")
        # 48 h = 2880 min; should be close to 2880
        assert 2870 <= remaining <= 2880


# ---------------------------------------------------------------------------
# Tests: missing Keychain credentials
# ---------------------------------------------------------------------------

class TestMissingCredentials:
    def test_no_credentials_returns_false(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("spa_core.alerts.telegram_manager._keychain_get", return_value=None):
            result = mgr.send("msg", title="t", category="alert")
        assert result is False

    def test_partial_credentials_returns_false(self, tmp_path):
        """Only token present, no chat_id."""
        mgr = _make_manager(tmp_path)
        def partial(key: str) -> str | None:
            return "TOKEN_VALUE" if "TOKEN" in key else None
        with patch("spa_core.alerts.telegram_manager._keychain_get", side_effect=partial):
            result = mgr.send("msg", title="t", category="alert")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: atomic state persistence
# ---------------------------------------------------------------------------

class TestAtomicStatePersistence:
    def test_state_file_written_after_send(self, tmp_path):
        mgr = _make_manager(tmp_path)
        state_file = tmp_path / "telegram_cooldowns.json"
        assert not state_file.exists(), "State file should not exist before first send"
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("msg", title="atomic_t", category="alert")
        assert state_file.exists(), "State file must be written after a successful send"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert isinstance(state, dict)
        assert len(state) == 1

    def test_state_file_not_written_on_failed_send(self, tmp_path):
        mgr = _make_manager(tmp_path)
        state_file = tmp_path / "telegram_cooldowns.json"
        with _patch_keychain(), _patch_send(mgr, return_value=False):
            mgr.send("msg", title="fail_t", category="alert")
        assert not state_file.exists(), (
            "State file must NOT be written when the Telegram send failed"
        )

    def test_state_file_not_written_when_suppressed(self, tmp_path):
        mgr = _make_manager(tmp_path)
        state_file = tmp_path / "telegram_cooldowns.json"
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("first", title="t_supp", category="alert")
        mtime_after_first = state_file.stat().st_mtime

        # Small sleep to detect mtime change
        time.sleep(0.05)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("second", title="t_supp", category="alert")

        mtime_after_second = state_file.stat().st_mtime
        assert mtime_after_second == mtime_after_first, (
            "State file must NOT be updated when the send was suppressed by cooldown"
        )

    def test_status_returns_dict(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with _patch_keychain(), _patch_send(mgr, return_value=True):
            mgr.send("msg", title="st_t", category="milestone")
        result = mgr.status()
        assert isinstance(result, dict)
        assert len(result) == 1
        entry = next(iter(result.values()))
        assert "last_sent_at" in entry
        assert "elapsed_minutes" in entry
