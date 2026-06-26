#!/usr/bin/env python3
"""Health views: menu, Agents (paged + only-failing filter), System, Last cycle
(UX §4.10–4.11)."""
from __future__ import annotations

from typing import Dict, List, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B

PER_PAGE = 12


def render_menu(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    ah = B.read_json("agent_health.json", {})
    sh = B.read_json("system_health.json", {})
    body = [
        "🩺  {}".format(t("crumb.health", lang)),
        "",
        "Agents  {} ✅  ·  {} ⛔  ·  {} total".format(
            ah.get("healthy_count", "?"), ah.get("critical_count", "?"),
            ah.get("total_agents", "?")),
        "System  {}".format(sh.get("overall_status", "?")),
    ]
    text = B.screen("health", "monitor", body,
                    B.freshness(ah.get("timestamp"), lang), lang)
    return text, menus.standard_keyboard("health", lang)


def render_agents(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    ah = B.read_json("agent_health.json", {})
    agents = ah.get("agents", []) if isinstance(ah, dict) else []
    if not agents:
        body = [B.unavailable(lang, "agent_health.json")]
        text = B.screen("health.agents", "monitor", body, B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("health.agents", lang)

    only_failing = (arg == "fail")
    shown = [a for a in agents if a.get("status") != "OK"] if only_failing else agents
    sl, page, total_pages = B.paginate(shown, page, PER_PAGE)

    healthy = ah.get("healthy_count", 0)
    crit = ah.get("critical_count", 0)
    total = ah.get("total_agents", len(agents))
    overall = ah.get("overall_status", "?")
    body = [
        "🩺  {}        {} ✅   ·   {} ⛔   ·   {} total".format(
            t("ttl.agents", lang), healthy, crit, total),
        "                  {} {}".format(t("w.overall", lang), overall),
        "",
    ]
    for a in sl:
        mark = "✅" if a.get("status") == "OK" else "⛔"
        label = str(a.get("label", "?")).replace("com.spa.", "")
        issue = (" — " + a.get("issue", "")) if a.get("status") != "OK" and a.get("issue") else ""
        body.append(" {} {}{}".format(mark, label, issue))
    pgpath = "health.agents"
    extra: List[List[Dict]] = [menus.pager_row(pgpath, page, total_pages, lang)]
    if not only_failing:
        extra.append([{"text": t("btn.only_failing", lang),
                       "callback_data": "nav:health.agents|fail"}])
    text = B.screen("health.agents",
                    "{} {} / {}".format(t("w.page", lang), page + 1, total_pages),
                    body, B.freshness(ah.get("timestamp"), lang), lang)
    return text, menus.standard_keyboard("health.agents", lang, extra_rows=extra)


def render_system(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    sh = B.read_json("system_health.json", {})
    if not sh:
        body = [B.unavailable(lang, "system_health.json")]
        text = B.screen("health.system", "monitor", body, B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("health.system", lang)
    counts = sh.get("counts", {})
    domains = sh.get("domains", {})
    body = [
        "🩺  {}           {} {}".format(
            t("ttl.system", lang), t("w.overall", lang), sh.get("overall_status", "?")),
        "",
        " CRITICAL {} · WARNING {} · INFO {} · OK {}".format(
            counts.get("CRITICAL", 0), counts.get("WARNING", 0),
            counts.get("INFO", 0), counts.get("OK", 0)),
        "",
    ]
    icon = {"OK": "✅", "INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "⛔", "SKIPPED": "⏭"}
    for dname, dval in domains.items():
        st = dval.get("status", "?") if isinstance(dval, dict) else "?"
        body.append(" {} {}".format(icon.get(st, "•"), dname))
    footer = "run {} · fingerprint {}".format(sh.get("run_id", "—"), sh.get("fingerprint", "—"))
    text = B.screen("health.system", "monitor · 7 domains", body, footer, lang)
    return text, menus.standard_keyboard("health.system", lang)


def render_cycle(arg: str = "", lang: str = "en", page: int = 0,
                 prefs: Dict = None) -> Tuple[str, Dict]:
    st = B.read_json("paper_trading_status.json", {})
    if not st:
        body = [B.unavailable(lang, "paper_trading_status.json")]
        text = B.screen("health.cycle", "monitor", body, B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("health.cycle", lang)
    status = st.get("last_cycle_status", "?")
    mark = "✅" if status == "ok" else "⛔"
    body = [
        "🔄  {}".format(t("ttl.cycle", lang)),
        "",
        "Status     {} {}".format(mark, status),
        "Timestamp  {}".format(st.get("last_cycle_ts", "—")),
        "Last trade {}".format(st.get("last_trade_id", "—")),
        "Adapters   {} live".format(st.get("num_adapters_live", "—")),
        "Risk gate  {}".format("approved ✅" if st.get("risk_policy_approved")
                               else "blocked ⛔"),
    ]
    text = B.screen("health.cycle", "monitor", body,
                    B.freshness(st.get("last_cycle_ts"), lang), lang)
    return text, menus.standard_keyboard("health.cycle", lang)
