#!/usr/bin/env python3
"""Settings view: language EN|RU, daily/weekly digest toggles, warning level,
mute (UX §4.15). State lives in data/telegram/user_prefs.json."""
from __future__ import annotations

import time
from typing import Dict, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B

_WARN_LABEL = {
    "all": {"en": "All", "ru": "Все"},
    "critical": {"en": "Critical only", "ru": "Только критич."},
    "off": {"en": "Off", "ru": "Выкл"},
}


def render(arg: str = "", lang: str = "en", page: int = 0,
           prefs: Dict = None) -> Tuple[str, Dict]:
    prefs = prefs or {}
    lang_flag = "🇬🇧 EN" if lang == "en" else "🇷🇺 RU"
    daily = "🔔 ON" if prefs.get("daily", True) else "🔕 OFF"
    weekly = "🔔 ON" if prefs.get("weekly", True) else "🔕 OFF"
    warn_level = prefs.get("warnings", "critical")
    warn_lbl = _WARN_LABEL.get(warn_level, {}).get(lang, warn_level)

    mute_until = prefs.get("mute_until", 0) or 0
    now = time.time()
    if mute_until and float(mute_until) > now:
        left_h = max(1, int((float(mute_until) - now) / 3600))
        mute_line = "💤 muted (~{}h left)".format(left_h) if float(mute_until) < 4e9 \
            else "💤 muted (until unmute)"
    else:
        mute_line = "— {}".format(t("w.not_muted", lang))

    body = [
        "⚙️  {}".format(t("ttl.settings", lang)),
        "",
        "{:<11} {}  ({})".format(t("set.language", lang), lang_flag, t("w.active", lang)),
        "{:<11} {}".format(t("set.daily", lang), daily),
        "{:<11} {}".format(t("set.weekly", lang), weekly),
        "{:<11} 🚨 {}".format(t("set.warnings", lang), warn_lbl),
        "{:<11} {}".format(t("set.mute", lang), mute_line),
    ]
    text = B.screen("settings", "⚙️", body, B.freshness(None, lang), lang)
    return text, menus.settings_keyboard(prefs, lang)
