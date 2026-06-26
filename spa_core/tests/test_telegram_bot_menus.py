#!/usr/bin/env python3
"""Tests for the interactive SPA Telegram bot (menus · router · views).

Covers (per docs/TELEGRAM_BOT_UX.md + TELEGRAM_BOT_ARCHITECTURE.md):
* router dispatches nav / act / pg callbacks
* editMessageText used for drill-down (callbacks), sendMessage for commands
* Back resolves to the parent path
* owner-auth rejects non-owner (fail-closed)
* a view renders from fixture JSON; fail-closed "unavailable" on missing data
* EN|RU per-chat toggle
* every callback_data ≤ 64 bytes

The Telegram transport is mocked — no real sends.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.telegram import menus, prefs as prefs_store
from spa_core.telegram.i18n import t
from spa_core.telegram.router import CALLBACK_MAX_BYTES, Router
from spa_core.telegram.views import VIEW_REGISTRY, get_builder

OWNER = "424242"
OUTSIDER = "999999"


# ── Mock transport (records calls; performs no real I/O) ──────────────────────


class MockTransport:
    def __init__(self):
        self.edits = []     # (chat_id, message_id, text, keyboard)
        self.sends = []     # (chat_id, text, keyboard)
        self.answers = []   # callback_id

    def edit_message_text(self, chat_id, message_id, text, reply_markup):
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True}

    def send_message(self, chat_id, text, reply_markup):
        self.sends.append((chat_id, text, reply_markup))
        return {"ok": True}

    def answer_callback(self, callback_id):
        self.answers.append(callback_id)


@pytest.fixture()
def isolated_prefs(tmp_path, monkeypatch):
    """Point the prefs store at a temp file so tests don't touch real data/."""
    pf = tmp_path / "user_prefs.json"
    monkeypatch.setattr(prefs_store, "PREFS_FILE", pf, raising=True)
    return pf


@pytest.fixture()
def router(isolated_prefs):
    return Router(MockTransport(), OWNER)


# ── Owner-auth (fail-closed) ──────────────────────────────────────────────────


def test_owner_auth_accepts_owner(router):
    assert router.is_owner(OWNER) is True
    assert router.is_owner(int(OWNER)) is True


def test_owner_auth_rejects_outsider(router):
    assert router.is_owner(OUTSIDER) is False


def test_owner_auth_fail_closed_when_no_owner(isolated_prefs):
    r = Router(MockTransport(), None)
    assert r.is_owner(OWNER) is False  # missing creds → serve nobody


def test_outsider_callback_ignored(router):
    router.handle_callback("nav:strategies", OUTSIDER, 1, "cb")
    # spinner cleared but no panel edit for an outsider
    assert router.transport.answers == ["cb"]
    assert router.transport.edits == []


def test_outsider_command_denied(router):
    router.handle_command("/start", OUTSIDER)
    assert len(router.transport.sends) == 1
    assert "denied" in router.transport.sends[0][1].lower()


# ── Command path sends a NEW message; callbacks edit in place ─────────────────


def test_command_sends_new_message(router):
    router.handle_command("/start", OWNER)
    assert len(router.transport.sends) == 1
    assert len(router.transport.edits) == 0
    assert "SPA Monitor" in router.transport.sends[0][1]


def test_callback_edits_in_place(router):
    router.handle_callback("nav:portfolio", OWNER, 77, "cb1")
    assert len(router.transport.edits) == 1
    assert len(router.transport.sends) == 0  # drill-down never spawns a bubble
    chat, mid, text, kb = router.transport.edits[0]
    assert chat == OWNER and mid == 77
    assert "inline_keyboard" in kb


def test_callback_clears_spinner_first(router):
    router.handle_callback("nav:health", OWNER, 5, "spin")
    assert router.transport.answers == ["spin"]


# ── nav / act / pg dispatch ───────────────────────────────────────────────────


def test_parse_nav(router):
    assert router.parse_callback("nav:strategies.rates", OWNER) == ("strategies.rates", "", 0)


def test_parse_nav_with_arg(router):
    path, arg, page = router.parse_callback("nav:strategies.rates|rates_desk_fixed_carry", OWNER)
    assert path == "strategies.rates"
    assert arg == "rates_desk_fixed_carry"


def test_parse_pg(router):
    assert router.parse_callback("pg:health.agents:3", OWNER) == ("health.agents", "", 3)


def test_pg_callback_renders_requested_page(router):
    router.handle_callback("pg:health.agents:1", OWNER, 1, "cb")
    # at least one edit happened; page index propagated without error
    assert len(router.transport.edits) == 1


def test_act_togglelang_returns_settings(router):
    path, arg, page = router.parse_callback("act:togglelang:1", OWNER)
    assert path == "settings"


# ── Back resolves to parent ───────────────────────────────────────────────────


def test_parent_resolution():
    assert menus.parent_of("strategies.rates") == "strategies"
    assert menus.parent_of("strategies") == "home"
    assert menus.parent_of("home") == "home"


def test_back_button_points_to_parent():
    kb = menus.standard_keyboard("strategies.rates", "en")
    nav = kb["inline_keyboard"][-1]
    back = nav[0]
    assert back["callback_data"] == "nav:strategies"
    home_btn = nav[1]
    assert home_btn["callback_data"] == "nav:home"


def test_home_has_refresh_not_back():
    kb = menus.home_keyboard("en")
    flat = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    # Home shows a Refresh (nav:home) and no Back-to-parent
    assert "nav:home" in flat


def test_full_flow_home_strategies_rates_sleeve_back(router):
    # Home (command) → Strategies → Rates Desk → sleeve → Back → Strategies
    router.handle_command("/start", OWNER)
    for cb in ("nav:strategies", "nav:strategies.rates",
               "nav:strategies.rates|rates_desk_fixed_carry"):
        router.handle_callback(cb, OWNER, 10, "c")
    # Back from sleeve detail = parent of strategies.rates = strategies
    router.handle_callback("nav:strategies", OWNER, 10, "c")
    assert len(router.transport.edits) == 4
    # breadcrumbs correct at the Rates Desk step
    rates_text = router.transport.edits[1][2]
    assert "Home › Strategies › Rates Desk" in rates_text


def test_breadcrumb_localized():
    assert menus.breadcrumb("strategies.rates", "en") == "Home › Strategies › Rates Desk"
    assert menus.breadcrumb("strategies.rates", "ru").startswith("Дом › Стратегии")


# ── Views render from fixture JSON + fail-closed on missing ───────────────────


def _write(tmp_data, name, obj):
    p = tmp_data / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_all_views_render():
    for path, builder in VIEW_REGISTRY.items():
        text, kb = builder(arg="", lang="en", page=0, prefs={"daily": True})
        assert isinstance(text, str) and text, path
        assert "inline_keyboard" in kb, path


def test_view_renders_from_fixture(tmp_path, monkeypatch):
    from spa_core.telegram.views import _base
    monkeypatch.setattr(_base, "DATA_DIR", tmp_path, raising=True)
    _write(tmp_path, "golive_status.json", {
        "ready": False, "passed": 27, "total": 29,
        "criteria": [
            {"name": "equity_curve_real", "status": "PASS"},
            {"name": "min_track_days_30", "status": "PENDING",
             "blocking": True, "estimated_days_to_pass": 25,
             "message": "5/30 honest track days"},
        ],
    })
    from spa_core.telegram.views import golive
    text, _ = golive.render_summary(arg="", lang="en", page=0, prefs={})
    assert "27 / 29" in text
    assert "min_track_days_30" in text


def test_view_fail_closed_on_missing_data(tmp_path, monkeypatch):
    from spa_core.telegram.views import _base
    monkeypatch.setattr(_base, "DATA_DIR", tmp_path, raising=True)  # empty dir
    from spa_core.telegram.views import portfolio
    text, kb = portfolio.render_positions(arg="", lang="en", page=0, prefs={})
    assert t("lbl.unavailable", "en").split()[0] in text  # the ⚠️ glyph
    assert "inline_keyboard" in kb  # still navigable, never a crash


def test_view_never_raises_returns_keyboard(router, monkeypatch):
    # a broken builder must not crash the router
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(VIEW_REGISTRY, "home", boom)
    text, kb = router.render_view("home", "", "en", 0, OWNER)
    assert "view error" in text
    assert "inline_keyboard" in kb


# ── EN|RU per-chat toggle ─────────────────────────────────────────────────────


def test_lang_toggle_persists(router, isolated_prefs):
    assert prefs_store.get_lang(OWNER) == "en"
    router.handle_callback("act:togglelang:1", OWNER, 1, "c")
    assert prefs_store.get_lang(OWNER) == "ru"
    # next render is in RU
    text = router.transport.edits[-1][2]
    assert "НАСТРОЙКИ" in text


def test_lang_is_per_chat(isolated_prefs):
    prefs_store.set_pref(OWNER, "lang", "ru")
    prefs_store.set_pref(OUTSIDER, "lang", "en")
    assert prefs_store.get_lang(OWNER) == "ru"
    assert prefs_store.get_lang(OUTSIDER) == "en"


def test_home_buttons_localized():
    en = menus.home_keyboard("en")
    ru = menus.home_keyboard("ru")
    en_labels = {b["text"] for row in en["inline_keyboard"] for b in row}
    ru_labels = {b["text"] for row in ru["inline_keyboard"] for b in row}
    assert "📊 Portfolio" in en_labels
    assert "📊 Портфель" in ru_labels


# ── callback_data ≤ 64 bytes everywhere ──────────────────────────────────────


def test_all_callback_data_within_64_bytes():
    for path, builder in VIEW_REGISTRY.items():
        for lang in ("en", "ru"):
            _, kb = builder(arg="", lang=lang, page=0, prefs={})
            for row in kb["inline_keyboard"]:
                for btn in row:
                    cd = btn["callback_data"]
                    assert len(cd.encode("utf-8")) <= CALLBACK_MAX_BYTES, (path, cd)


def test_settings_keyboard_callback_bytes():
    kb = menus.settings_keyboard({"daily": True, "weekly": False}, "ru")
    for row in kb["inline_keyboard"]:
        for btn in row:
            assert len(btn["callback_data"].encode("utf-8")) <= CALLBACK_MAX_BYTES


# ── Mute action ───────────────────────────────────────────────────────────────


def test_mute_action_sets_mute(router, isolated_prefs):
    assert prefs_store.is_muted(OWNER) is False
    router.handle_callback("act:mute:8h", OWNER, 1, "c")
    assert prefs_store.is_muted(OWNER) is True
