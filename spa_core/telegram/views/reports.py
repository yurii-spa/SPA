#!/usr/bin/env python3
"""Reports views: menu, Today (daily digest), Weekly (UX §4.12–4.13).

Renders the canonical digest builders READ-ONLY (no sends). The Tier-2 digest
*senders* are owned elsewhere; this view only displays what those builders
compose. Fail-CLOSED if a builder is unavailable.
"""
from __future__ import annotations

from typing import Dict, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B


def render_menu(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    body = [
        "📅  {}".format(t("crumb.reports", lang)),
        "",
        "📅 {}  — {}".format(t("crumb.today", lang), t("ttl.daily", lang).lower()),
        "📆 {}  — {}".format(t("crumb.weekly", lang), t("ttl.weekly", lang).lower()),
    ]
    text = B.screen("reports", t("lbl.paper_readonly", lang), body,
                    B.freshness(None, lang, "on demand"), lang)
    return text, menus.standard_keyboard("reports", lang)


def render_today(arg: str = "", lang: str = "en", page: int = 0,
                 prefs: Dict = None) -> Tuple[str, Dict]:
    digest = _build_daily()
    if digest is None:
        body = [B.unavailable(lang, "daily digest builder")]
    else:
        body = ["📅  {}".format(t("ttl.daily", lang)), "", digest]
    st = B.read_json("paper_trading_status.json", {})
    text = B.screen("reports.today", t("lbl.paper_readonly", lang), body,
                    B.freshness(st.get("last_cycle_ts"), lang,
                                "read-only · is_demo:false"), lang)
    return text, menus.standard_keyboard("reports.today", lang)


def render_weekly(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    digest = _build_weekly()
    if digest is None:
        body = [B.unavailable(lang, "weekly digest builder")]
    else:
        body = ["📆  {}".format(t("ttl.weekly", lang)), "", digest]
    text = B.screen("reports.weekly", t("lbl.paper_readonly", lang), body,
                    B.freshness(None, lang, "read-only simulation"), lang)
    return text, menus.standard_keyboard("reports.weekly", lang)


def _build_daily():
    """Compose the canonical daily digest text. None on any failure."""
    try:
        from spa_core.reporting import daily_telegram_report as dr
        data = dr.build_report_data()
        return dr.format_daily_message(data)
    except Exception:
        return None


def _build_weekly():
    try:
        from spa_core.reporting import weekly_telegram_report as wr
        data = wr.build_weekly_data()
        return wr.format_weekly_message(data)
    except Exception:
        return None
