#!/usr/bin/env python3
"""Portfolio views: menu, Track, Positions, Equity history (UX §4.2–4.3)."""
from __future__ import annotations

from typing import Dict, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B


def render_menu(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    st = B.read_json("paper_trading_status.json", {})
    body = [
        "📊  {}".format(t("crumb.portfolio", lang)),
        "",
        "{}   {}".format(t("w.equity", lang), B.fmt_usd(st.get("current_equity"))),
        "{} {}".format(t("w.today", lang), B.fmt_usd(st.get("daily_yield_usd"), signed=True)),
    ]
    text = B.screen("portfolio", t("lbl.paper_readonly", lang), body,
                    B.freshness(st.get("last_cycle_ts"), lang), lang)
    return text, menus.standard_keyboard("portfolio", lang)


def render_track(arg: str = "", lang: str = "en", page: int = 0,
                 prefs: Dict = None) -> Tuple[str, Dict]:
    st = B.read_json("paper_trading_status.json", {})
    eqc = B.read_json("equity_curve_daily.json", {})
    summ = eqc.get("summary", {}) if isinstance(eqc, dict) else {}
    if not st and not summ:
        body = [B.unavailable(lang, "paper_trading_status.json")]
        text = B.screen("portfolio.track", t("lbl.paper_sim", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("portfolio.track", lang)

    equity = st.get("current_equity")
    total_ret = st.get("total_return_pct")
    real_days = summ.get("real_days", "?")
    anchor = summ.get("first_real_date") or summ.get("evidenced_anchor") or "—"
    first_date = summ.get("first_date") or st.get("paper_start_date") or "—"
    best = summ.get("best_day", {}) or {}
    body = [
        "📊  {}".format(t("ttl.track", lang)),
        "{:<14}{}".format(t("w.equity", lang), B.fmt_usd(equity)),
        "{:<14}{} {}        {} {}".format(
            t("w.total_return", lang), B.arrow(total_ret), B.fmt_pct(total_ret),
            t("w.since", lang), first_date),
        "{:<14}{} {} / 30      {} {}".format(
            t("w.track", lang), t("w.day", lang), real_days, t("w.anchor", lang), anchor),
        "{:<14}{}".format(t("w.days_running", lang), st.get("days_running", "?")),
        "",
        t("w.today", lang),
        "  {:<13}{}".format(t("w.daily_yield", lang),
                            B.fmt_usd(st.get("daily_yield_usd"), signed=True)),
        "  {:<13}{}".format(t("w.daily_return", lang),
                            B.fmt_pct(st.get("daily_return_pct"), dp=4)),
        "  APY (today)  {}".format(B.fmt_pct(st.get("apy_today_pct"), signed=False)),
        "  {:<13}{}".format(t("w.regime", lang),
                            st.get("regime") or st.get("market_regime") or "—"),
        "",
        "{:<14}{}    {} -5%".format(
            t("w.drawdown", lang),
            B.fmt_pct(summ.get("real_max_drawdown_pct"), signed=False),
            t("w.kill_at", lang)),
    ]
    if best:
        body.append("Best day      {}  {}".format(
            B.fmt_pct(best.get("daily_return_pct"), dp=3), best.get("date", "—")))
    footer = B.freshness(st.get("last_cycle_ts"), lang, "is_demo:false")
    text = B.screen("portfolio.track", t("lbl.paper_sim", lang), body, footer, lang)
    return text, menus.standard_keyboard("portfolio.track", lang)


def render_positions(arg: str = "", lang: str = "en", page: int = 0,
                     prefs: Dict = None) -> Tuple[str, Dict]:
    cp = B.read_json("current_positions.json", {})
    positions = cp.get("positions", {}) if isinstance(cp, dict) else {}
    if not positions:
        body = [B.unavailable(lang, "current_positions.json")]
        text = B.screen("portfolio.positions", t("lbl.paper_sim", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("portfolio.positions", lang)

    capital = float(cp.get("capital_usd", 100000.0) or 100000.0)
    deployed = float(cp.get("deployed_usd", 0.0) or 0.0)
    cash = float(cp.get("cash_usd", 0.0) or 0.0)
    n = len(positions)
    body = [
        "📦  {}   ({} {} {})".format(
            t("ttl.positions", lang), B.fmt_usd(deployed),
            t("w.deployed_across", lang), n),
        "",
        " {:<16}{:>10}{:>7}".format("Protocol", "USD", "%"),
        " {:<16}{:>10}{:>7}".format("──────────────", "────────", "─────"),
    ]
    for proto, usd in sorted(positions.items(), key=lambda kv: -float(kv[1] or 0.0)):
        u = float(usd or 0.0)
        pct = (u / capital * 100.0) if capital else 0.0
        body.append(" {:<16}{:>10,.0f}{:>7.1f}".format(proto[:16], u, pct))
    body.append(" {:<16}{:>10}{:>7}".format("──────────────", "────────", "─────"))
    body.append(" {:<16}{:>10,.0f}{:>7.1f}".format(
        t("w.cash_buffer", lang)[:16], cash, (cash / capital * 100.0) if capital else 0.0))
    body.append("")
    body.append("{}  {}".format(t("w.model", lang), cp.get("model_used", "—")))
    footer = B.freshness(cp.get("generated_at"), lang, "live feed")
    text = B.screen("portfolio.positions", t("lbl.paper_sim", lang), body, footer, lang)
    # monospace via <pre>
    return _mono(text), menus.standard_keyboard("portfolio.positions", lang)


def render_equity(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    eqc = B.read_json("equity_curve_daily.json", {})
    daily = eqc.get("daily", []) if isinstance(eqc, dict) else []
    if not daily:
        body = [B.unavailable(lang, "equity_curve_daily.json")]
        text = B.screen("portfolio.equity", t("lbl.paper_sim", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("portfolio.equity", lang)
    window = daily[-7:]
    body = ["📈  {}  (7d)".format(t("crumb.equity", lang)), ""]
    for bar in window:
        eq = bar.get("close_equity") or bar.get("equity") or 0.0
        ret = bar.get("daily_return_pct", 0.0)
        body.append(" {:<12}{:>13}  {}".format(
            bar.get("date", "—"), B.fmt_usd(eq), B.fmt_pct(ret, dp=4)))
    footer = B.freshness(eqc.get("generated_at"), lang, "is_demo:false")
    text = B.screen("portfolio.equity", t("lbl.paper_sim", lang), body, footer, lang)
    return _mono(text), menus.standard_keyboard("portfolio.equity", lang)


def _mono(text: str) -> str:
    return "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
