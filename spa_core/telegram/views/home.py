#!/usr/bin/env python3
"""HOME (L0) view — the at-a-glance dashboard panel (UX §4.1)."""
from __future__ import annotations

from typing import Dict, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B


def render(arg: str = "", lang: str = "en", page: int = 0,
           prefs: Dict = None) -> Tuple[str, Dict]:
    st = B.read_json("paper_trading_status.json", {})
    gl = B.read_json("golive_status.json", {})
    ah = B.read_json("agent_health.json", {})

    equity = st.get("current_equity")
    total_ret = st.get("total_return_pct")
    apy = st.get("apy_today_pct")
    daily_yield = st.get("daily_yield_usd")
    regime = st.get("regime") or st.get("market_regime") or "—"
    last_ts = st.get("last_cycle_ts")

    real_days = "?"
    eqc = B.read_json("equity_curve_daily.json", {})
    summ = eqc.get("summary", {}) if isinstance(eqc, dict) else {}
    if isinstance(summ, dict) and summ.get("real_days") is not None:
        real_days = summ.get("real_days")

    passed = gl.get("passed", "?")
    total = gl.get("total", "?")

    crit = ah.get("critical_count", 0) if isinstance(ah, dict) else 0
    sys_line = "✅ {}".format(t("w.system_ok", lang))
    health_line = sys_line
    if crit:
        health_line = "{}   ·   ⛔ {} {}".format(sys_line, crit, t("w.agents", lang))

    label = t("lbl.paper_readonly", lang)
    lines = [
        "🏠  {}".format(t("ttl.home", lang)),
        "",
        "{:<8} {}   {} {}".format(
            t("w.equity", lang), B.fmt_usd(equity),
            B.arrow(total_ret), B.fmt_pct(total_ret)),
        "{:<8} {} {} / 30  ({})    Go-Live {}/{}".format(
            t("w.track", lang), t("w.day", lang), real_days,
            t("w.real", lang), passed, total),
        "{:<8} {}   ·   APY {}   ·   {} {}".format(
            t("w.today", lang), B.fmt_usd(daily_yield, signed=True),
            B.fmt_pct(apy, signed=False), t("w.regime", lang), regime),
        "{:<8} {}".format(t("w.health", lang), health_line),
    ]
    footer = B.freshness(last_ts, lang)
    text = "{}\n{}\n{}\n{}".format(
        "🏠  {}                       {}".format(t("ttl.home", lang), label),
        B.RULE, "\n".join(lines[2:]), B.RULE + "\n" + footer)
    return text, menus.home_keyboard(lang)
