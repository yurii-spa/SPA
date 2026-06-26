#!/usr/bin/env python3
"""Warnings views: Active (open warnings, urgent first) + Recent (UX §4.14).

Derives warnings READ-ONLY from monitor state files (agent_health critical,
kill-switch, cycle status, refusal). Honest financial-vs-monitoring framing.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B


def _active_warnings() -> List[Dict]:
    out: List[Dict] = []
    ah = B.read_json("agent_health.json", {})
    if isinstance(ah, dict) and ah.get("overall_status") == "CRITICAL":
        n = ah.get("critical_count", 0)
        out.append({
            "sev": "CRITICAL", "key": "agent_health",
            "title": "agent_health",
            "detail": "{} agents down · overall CRITICAL".format(n),
            "since": B.short_ts(ah.get("timestamp")),
            "financial": False,
        })
    ks = B.read_json("kill_switch_active.json", {})
    if isinstance(ks, dict) and ks.get("active"):
        out.append({
            "sev": "CRITICAL", "key": "kill_switch", "title": "kill-switch",
            "detail": "all positions flat (paper) · {}".format(ks.get("reason", "")),
            "since": B.short_ts(ks.get("set_at")), "financial": True,
        })
    st = B.read_json("paper_trading_status.json", {})
    if isinstance(st, dict) and st.get("last_cycle_status") not in ("ok", None, ""):
        out.append({
            "sev": "CRITICAL", "key": "cycle", "title": "cycle failure",
            "detail": "last cycle status={}".format(st.get("last_cycle_status")),
            "since": B.short_ts(st.get("last_cycle_ts")), "financial": False,
        })
    ref = B.read_json("refusal_status.json", {})
    if isinstance(ref, dict):
        refused = [u for u in ref.get("underlyings", [])
                   if u.get("verdict") not in ("SAFE", None)]
        if refused:
            out.append({
                "sev": "WARNING", "key": "refusal", "title": "refusal fired",
                "detail": "{} book(s) refused".format(len(refused)),
                "since": B.short_ts(ref.get("generated_at")), "financial": False,
            })
    # urgent first
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    out.sort(key=lambda w: order.get(w["sev"], 9))
    return out


def render_active(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    warns = _active_warnings()
    body = ["⚠️  {}".format(t("ttl.warnings", lang)), ""]
    if not warns:
        body.append(t("w.no_active", lang))
    for w in warns:
        emoji = "⛔" if w["sev"] == "CRITICAL" else "⚠️"
        frame = (t("lbl.monitoring_not_financial", lang)
                 if not w["financial"] else "financial")
        body.append(" {} {}  {}".format(emoji, w["sev"], w["title"]))
        body.append("    {}".format(w["detail"]))
        body.append("    since {} · {}".format(w["since"], frame))
        body.append("")
    ah = B.read_json("agent_health.json", {})
    footer = B.freshness(ah.get("timestamp"), lang,
                         "{} {}".format(len(warns), t("w.active", lang)))
    text = B.screen("warnings", "{} {}".format(len(warns), t("w.active", lang)),
                    body, footer, lang)
    return text, menus.standard_keyboard("warnings", lang)


def render_recent(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    hist = B.read_json("alert_history.json", [])
    rows = hist if isinstance(hist, list) else hist.get("alerts", []) if isinstance(hist, dict) else []
    body = ["🗂️  {}".format(t("crumb.recent", lang)), ""]
    if not rows:
        body.append(B.unavailable(lang, "alert_history.json"))
    for r in (rows[-10:] if isinstance(rows, list) else []):
        if not isinstance(r, dict):
            continue
        preview = str(r.get("preview", r.get("text", "")))[:50]
        ts = B.short_ts(r.get("ts") or r.get("timestamp"))
        body.append(" • {}  {}".format(ts, preview))
    text = B.screen("warnings.recent", "last 7d", body, B.freshness(None, lang), lang)
    return text, menus.standard_keyboard("warnings.recent", lang)
