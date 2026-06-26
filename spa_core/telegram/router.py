#!/usr/bin/env python3
"""Callback / command router for the interactive SPA Telegram bot.

Implements the navigation model from ``docs/TELEGRAM_BOT_UX.md`` §3 and the
service design from ``docs/TELEGRAM_BOT_ARCHITECTURE.md`` §3.2–3.3:

* callback_data grammar (≤64 bytes, stateless / restart-safe):
    ``nav:<path>``          navigate to a view (editMessageText in place)
    ``nav:<path>|<arg>``    navigate to a dynamic leaf (arg passed to builder)
    ``act:<verb>:<arg>``    a settings/mute action (mutates prefs, re-renders)
    ``pg:<path>:<n>``       page n of a paged view
* On a button tap → answerCallbackQuery (clear spinner) → editMessageText IN
  PLACE (one evolving panel). A slash command sends a NEW message.
* Owner-auth: only ``TELEGRAM_CHAT_ID_SPA`` is served; everyone else is rejected
  fail-closed.

The router is transport-agnostic: it takes a ``transport`` object exposing
``edit_message_text(...)``, ``send_message(...)`` and ``answer_callback(...)`` so
it can be unit-tested with a mock (no real Telegram I/O). The live bot supplies
the real transport.

Stdlib only, deterministic, no LLM.
"""
from __future__ import annotations

import html as _html
import re as _re
import time
from typing import Any, Dict, Optional, Tuple

from spa_core.telegram import prefs as prefs_store
from spa_core.telegram.i18n import normalize_lang, t
from spa_core.telegram.views import get_builder

# Telegram parse_mode=HTML allows only this tag whitelist; ANY other raw < > &
# in a view body (e.g. "<$20M", "RESEARCH -> BACKTEST", a "β<0" from live data)
# makes the Bot API reject the message (400 can't-parse-entities) → the
# editMessageText silently fails → the button "does nothing". So we escape every
# body to be HTML-safe and then restore only the intentional whitelist tags.
_ALLOWED_HTML_TAGS = ("b", "i", "u", "s", "code", "pre")


def html_safe(text: str) -> str:
    """Escape raw &<> in a view body, preserving the allowed formatting tags.

    Makes any view body (incl. dynamic data) safe for parse_mode=HTML so a stray
    '<' / '>' / '&' can never break the panel render (the dead-button bug)."""
    esc = _html.escape(str(text or ""), quote=False)  # & < >  (leave quotes)
    for tag in _ALLOWED_HTML_TAGS:
        esc = esc.replace("&lt;%s&gt;" % tag, "<%s>" % tag)
        esc = esc.replace("&lt;/%s&gt;" % tag, "</%s>" % tag)
    # restore <a href="…">…</a> links if a view used them
    esc = _re.sub(r'&lt;a href=&quot;([^&]*)&quot;&gt;', r'<a href="\1">', esc)
    esc = esc.replace("&lt;/a&gt;", "</a>")
    return esc

# slash command → view path (legacy shortcuts open the panel on the matching screen)
COMMAND_TO_PATH = {
    "/start": "home",
    "/menu": "home",
    "/status": "home",
    "/home": "home",
    "/portfolio": "portfolio",
    "/track": "portfolio.track",
    "/positions": "portfolio.positions",
    "/golive": "golive",
    "/strategies": "strategies",
    "/health": "health",
    "/agents": "health.agents",
    "/reports": "reports",
    "/today": "reports.today",
    "/week": "reports.weekly",
    "/warnings": "warnings",
    "/alerts": "warnings",
    "/settings": "settings",
}

CALLBACK_MAX_BYTES = 64


class Router:
    """Dispatch updates to view builders and drive the transport."""

    def __init__(self, transport: Any, owner_chat_id: Optional[str]) -> None:
        self.transport = transport
        self.owner_chat_id = str(owner_chat_id) if owner_chat_id is not None else None

    # ── auth ────────────────────────────────────────────────────────────────

    def is_owner(self, chat_id: Any) -> bool:
        """Fail-closed: serve only the configured owner. Unknown owner → nobody."""
        if not self.owner_chat_id:
            return False
        return str(chat_id) == self.owner_chat_id

    # ── render helpers ────────────────────────────────────────────────────────

    def render_view(self, path: str, arg: str, lang: str,
                    page: int, chat_id: str) -> Tuple[str, Dict]:
        """Build (text, keyboard) for a view path. Never raises."""
        prefs = prefs_store.get_prefs(chat_id)
        builder = get_builder(path)
        try:
            body, kb = builder(arg=arg, lang=lang, page=page, prefs=prefs)
            # HTML-safe the body so a stray <>& (static or from live data) can
            # never make the Bot API reject the edit → dead button.
            return html_safe(body), kb
        except Exception as exc:  # noqa: BLE001 — a broken view must not crash the bot
            return ("⚠️ view error: {}".format(type(exc).__name__),
                    {"inline_keyboard": [[{"text": t("btn.home", lang),
                                           "callback_data": "nav:home"}]]})

    # ── command path (new message) ───────────────────────────────────────────

    def handle_command(self, text: str, chat_id: str) -> Optional[Dict]:
        """A slash command → send a NEW message opening the matching panel."""
        if not self.is_owner(chat_id):
            lang = "en"
            self.transport.send_message(chat_id, t("auth.denied", lang), None)
            return None
        cmd = (text or "").strip().split()[0].split("@")[0].lower() if (text or "").strip() else ""
        path = COMMAND_TO_PATH.get(cmd, "home")
        lang = prefs_store.get_lang(chat_id)
        body, kb = self.render_view(path, "", lang, 0, chat_id)
        return self.transport.send_message(chat_id, body, kb)

    # ── callback path (edit in place) ─────────────────────────────────────────

    def handle_callback(self, data: str, chat_id: str, message_id: Any,
                        callback_id: str) -> Optional[Dict]:
        """A button tap → clear spinner, mutate state if needed, edit in place."""
        # Always answer the callback first so the client spinner clears.
        self.transport.answer_callback(callback_id)

        if not self.is_owner(chat_id):
            return None  # fail-closed: silently ignore non-owner taps

        path, arg, page = self.parse_callback(data, chat_id)
        lang = prefs_store.get_lang(chat_id)
        body, kb = self.render_view(path, arg, lang, page, chat_id)
        # editMessageText IN PLACE (single evolving panel — never a new bubble)
        return self.transport.edit_message_text(chat_id, message_id, body, kb)

    def parse_callback(self, data: str, chat_id: str) -> Tuple[str, str, int]:
        """Decode callback_data → (view_path, arg, page). Applies act: verbs.

        Returns the view to render after any state mutation.
        """
        data = str(data or "")
        if data.startswith("nav:"):
            payload = data[4:]
            if "|" in payload:
                path, arg = payload.split("|", 1)
            else:
                path, arg = payload, ""
            return path or "home", arg, 0
        if data.startswith("pg:"):
            rest = data[3:]
            # pg:<path>:<n>  (path may contain dots but no colons)
            try:
                path, n = rest.rsplit(":", 1)
                return path, "", int(n)
            except (ValueError, TypeError):
                return rest, "", 0
        if data.startswith("act:"):
            return self._apply_action(data[4:], chat_id)
        # legacy / unknown → home
        return "home", "", 0

    def _apply_action(self, payload: str, chat_id: str) -> Tuple[str, str, int]:
        """Apply an ``act:<verb>:<arg>`` mutation, return the view to re-render."""
        parts = payload.split(":", 1)
        verb = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        if verb == "togglelang":
            prefs_store.toggle_lang(chat_id)
            return "settings", "", 0
        if verb == "setlang":
            prefs_store.set_pref(chat_id, "lang", normalize_lang(arg))
            return "settings", "", 0
        if verb == "toggle":  # daily / weekly
            if arg in ("daily", "weekly"):
                cur = prefs_store.get_prefs(chat_id).get(arg, True)
                prefs_store.set_pref(chat_id, arg, not cur)
            return "settings", "", 0
        if verb == "warnlevel":
            if arg in ("all", "critical", "off"):
                prefs_store.set_pref(chat_id, "warnings", arg)
            return "settings", "", 0
        if verb == "mute":
            now = time.time()
            secs = {"1h": 3600, "8h": 8 * 3600, "inf": 10 ** 10}.get(arg, 0)
            prefs_store.set_pref(chat_id, "mute_until",
                                 (now + secs) if secs < 10 ** 9 else 10 ** 10)
            return "settings", "", 0
        return "settings", "", 0
