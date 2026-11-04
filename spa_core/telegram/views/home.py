#!/usr/bin/env python3
"""HOME (L0) view — the at-a-glance dashboard panel (UX §4.1)."""
from __future__ import annotations

from typing import Dict, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B


def fleet_line(ah: Dict, lang: str) -> str:
    """Здоровье ФЛОТА словами по его собственному вердикту (находка T02/T12): «✅ OK» печаталось ВСЕГДА,
    кроме случая critical > 0, — и при WARNING тоже. Это строка о процессах, не об инвестиционном контуре."""
    if not isinstance(ah, dict) or not ah:
        return "❔ " + ("здоровье агентов не измерено" if lang == "ru" else "agent health not measured")
    ov = str(ah.get("overall_status") or "").upper()
    crit, warn = ah.get("critical_count") or 0, ah.get("warning_count") or 0
    tot = ah.get("total_agents")
    tail = (f" ({tot} агентов)" if lang == "ru" else f" ({tot} agents)") if tot else ""
    if crit or ov == "CRITICAL":
        return f"⛔ агенты: критично {crit}, предупреждений {warn}{tail}" if lang == "ru" else \
            f"⛔ agents: critical {crit}, warnings {warn}{tail}"
    if warn or ov == "WARNING":
        return f"🟠 агенты: предупреждений {warn}{tail}" if lang == "ru" else f"🟠 agents: {warn} warnings{tail}"
    if ov == "OK":
        return "✅ " + t("w.system_ok", lang) + tail
    return "❔ " + (f"здоровье агентов: «{ov or '—'}» не распознано" if lang == "ru" else f"agent health «{ov}» unknown")


def investment_line(lang: str) -> str:
    """Режим инвестиционных движков — отдельной строкой от здоровья процессов (находка F2/T01/T02)."""
    try:
        from spa_core.studio_os.trading_engines import investment_engine_modes
        doc = investment_engine_modes()
    except Exception as exc:  # noqa: BLE001 — экран не падает, а называет пробел
        return ("Движки   ❔ режим не прочитан: " if lang == "ru" else "Engines  ❔ mode unreadable: ") + type(exc).__name__
    parts = []
    for e in doc.get("engines") or []:
        mode, inc = e.get("mode"), e.get("incident") or {}
        if mode is None:
            parts.append(f"❔ {e.get('engine')}: " + ("режим не измерен" if lang == "ru" else "mode not measured"))
        elif mode == "NORMAL":
            parts.append(f"✅ {e.get('engine')}: NORMAL")
        else:
            since = str(inc.get("opened_at") or e.get("mode_since") or "")[:10]
            parts.append(f"⛔ {e.get('engine')}: {mode}" + (f" {inc.get('kc')}" if inc.get("kc") else "")
                         + (f" с {since}" if since and lang == "ru" else f" since {since}" if since else "")
                         + (" — новые позиции запрещены, снимает владелец" if lang == "ru"
                            else " — no new positions, owner clears"))
    return ("{:<8} ".format("Движки" if lang == "ru" else "Engines")) + ("   ·   ".join(parts) or "—")


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

    health_line = fleet_line(ah, lang)
    invest_line = investment_line(lang)

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
            B.fmt_pct(apy, signed=False), ("режим рынка" if lang == "ru" else "market regime"), regime),
        "{:<8} {}".format(t("w.health", lang), health_line),
        invest_line,
    ]
    footer = B.freshness(last_ts, lang)
    text = "{}\n{}\n{}\n{}".format(
        "🏠  {}                       {}".format(t("ttl.home", lang), label),
        B.RULE, "\n".join(lines[2:]), B.RULE + "\n" + footer)
    return text, menus.home_keyboard(lang)
