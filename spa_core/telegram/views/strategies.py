#!/usr/bin/env python3
"""Strategies views: overview (Structural Desk verdicts), Rates Desk + sleeve
detail, RWA Safety Board, Structural Desk thesis map, Refusal Log + per-asset
(UX §4.6–4.9).

Dynamic leaves (sleeve detail, refusal underlying detail) are addressed with the
``nav:<path>|<arg>`` form (router passes ``<arg>`` to the builder). Stays ≤64B.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B

RATES_FILE = "rates_desk/rates_desk_promotion.json"
REFUSAL_FILE = "refusal_status.json"
RWA_FILE = "rwa_safety_board.json"

# static structural-desk verdict map (UX §4.6 — from docs/STRUCTURAL_DESK.md)
_STRUCTURAL = [
    ("✅", "Rates Desk", "GO", "carry is fundable"),
    ("◐", "RWA Safety Board", "meas-GO", "book NO-GO (off-code)"),
    ("⛔", "Liquidator", "NO-GO", "too small (<$20M bar)"),
]


def render_overview(arg: str = "", lang: str = "en", page: int = 0,
                    prefs: Dict = None) -> Tuple[str, Dict]:
    rates = B.read_json(RATES_FILE, {})
    floor = rates.get("rwa_floor_pct", 3.4) if isinstance(rates, dict) else 3.4
    body = ["🏦  {}".format(t("ttl.strategies", lang)), "", t("s.three_theses", lang)]
    for emoji, name, verdict, why in _STRUCTURAL:
        body.append("  {}  {:<18} {:<8} {}".format(emoji, name, verdict, why))
    body.append("")
    body.append(t("s.all_advisory", lang))
    body.append("")
    body.append("{}  {}".format(t("s.rwa_floor_bench", lang),
                                B.fmt_pct(floor, signed=False)))
    text = B.screen("strategies", t("lbl.advisory_nocap", lang), body,
                    B.freshness(rates.get("generated_at"), lang), lang)
    return text, menus.standard_keyboard("strategies", lang)


def _sleeve_name(s: Dict) -> str:
    sid = str(s.get("id", ""))
    return sid.replace("rates_desk_", "").replace("_", " ").title().replace(" ", "")


def render_rates(arg: str = "", lang: str = "en", page: int = 0,
                 prefs: Dict = None) -> Tuple[str, Dict]:
    rates = B.read_json(RATES_FILE, {})
    if not rates:
        body = [B.unavailable(lang, RATES_FILE)]
        text = B.screen("strategies.rates", t("lbl.advisory_paper", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("strategies.rates", lang)

    sleeves = rates.get("sleeves", []) if isinstance(rates, dict) else []
    # sleeve detail leaf?
    if arg:
        return _render_sleeve_detail(arg, sleeves, rates, lang)

    body = [
        "🏦  {}            {} ✅ GO".format(t("ttl.rates", lang), t("w.verdict", lang)),
        "",
        "Pipeline: {}".format(rates.get("pipeline", "")),
        "",
        "{} ({})              {}".format(
            t("s.sleeves", lang), len(sleeves), t("s.beats_floor_q", lang)),
    ]
    sleeve_btns: List[Dict] = []
    for s in sleeves:
        name = _sleeve_name(s)
        beats = "✅ yes" if s.get("beats_floor") else "⛔ no"
        body.append("  {:<20} {}   ({})".format(name, beats, s.get("stage", "")))
        sleeve_btns.append({"text": "{} ▸".format(name),
                            "callback_data": "nav:strategies.rates|{}".format(s.get("id", ""))})
    rows = [sleeve_btns[i:i + 2] for i in range(0, len(sleeve_btns), 2)]
    footer = B.freshness(rates.get("generated_at"), lang, "LLM-forbidden · fail-closed")
    text = B.screen("strategies.rates", t("lbl.advisory_paper", lang), body, footer, lang)
    return text, menus.standard_keyboard("strategies.rates", lang, extra_rows=rows)


def _render_sleeve_detail(sid: str, sleeves: List[Dict], rates: Dict,
                          lang: str) -> Tuple[str, Dict]:
    s = next((x for x in sleeves if str(x.get("id")) == sid), None)
    if not s:
        body = [B.unavailable(lang, "sleeve {}".format(sid))]
        text = B.screen("strategies.rates", t("lbl.advisory_paper", lang), body,
                        B.freshness(rates.get("generated_at"), lang), lang)
        return text, menus.standard_keyboard("strategies.rates", lang)
    name = _sleeve_name(s)
    verdict = "✅ GO" if s.get("beats_floor") else "⛔ NO-GO"
    body = [
        "🏦  {}               {}".format(name.upper(), verdict),
        "",
        "Stage     {}".format(s.get("stage", "—")),
        "Net APY   {}".format(B.fmt_pct(s.get("net_apy_pct"), signed=False)),
        "Max DD    {}".format(B.fmt_pct(s.get("max_drawdown_pct"), signed=False)),
        "Deflated Sharpe  {}".format(s.get("deflated_sharpe", "—")),
        "Refusals  {}".format(s.get("refusals_count", "—")),
        "",
        "Promotion criteria",
    ]
    for ck, cv in (s.get("criteria", {}) or {}).items():
        mark = "✅" if cv.get("pass") else "⛔"
        body.append("  {} {}".format(mark, ck))
    footer = "{} · floor {}".format(t("lbl.moves_no_capital", lang),
                                    B.fmt_pct(rates.get("rwa_floor_pct", 3.4), signed=False))
    text = B.screen("strategies.rates", t("lbl.advisory_paper", lang), body, footer, lang)
    return text, menus.standard_keyboard("strategies.rates", lang)


def render_rwa(arg: str = "", lang: str = "en", page: int = 0,
               prefs: Dict = None) -> Tuple[str, Dict]:
    rwa = B.read_json(RWA_FILE, {})
    if not rwa:
        body = [B.unavailable(lang, RWA_FILE)]
        text = B.screen("strategies.rwa", t("lbl.advisory_nocap", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("strategies.rwa", lang)
    assets = rwa.get("assets", []) if isinstance(rwa, dict) else []
    counts = rwa.get("verdict_counts", {})
    body = [
        "🛡️  {}        ◐ meas-GO".format(t("ttl.rwa", lang)),
        "",
        "verdicts: " + " · ".join("{} {}".format(k, v) for k, v in counts.items()),
        "",
        " {:<8}{:<16}{}".format("Asset", "Verdict", "exit72h$"),
        " {:<8}{:<16}{}".format("──────", "──────────────", "────────"),
    ]
    for a in assets[:12]:
        body.append(" {:<8}{:<16}{:>9,.0f}".format(
            str(a.get("symbol", "?"))[:8], str(a.get("verdict", "?"))[:16],
            float(a.get("exit_capacity_72h_usd", 0.0) or 0.0)))
    footer = B.freshness(rwa.get("generated_at"), lang, "advisory · book NO-GO")
    text = B.screen("strategies.rwa", t("lbl.advisory_nocap", lang), body, footer, lang)
    return text, menus.standard_keyboard("strategies.rwa", lang)


def render_structural(arg: str = "", lang: str = "en", page: int = 0,
                      prefs: Dict = None) -> Tuple[str, Dict]:
    body = ["🔬  {}".format(t("crumb.structural", lang)), "", t("s.three_theses", lang)]
    for emoji, name, verdict, why in _STRUCTURAL:
        body.append("  {}  {:<18} {:<8} {}".format(emoji, name, verdict, why))
    text = B.screen("strategies.structural", t("lbl.advisory_nocap", lang), body,
                    B.freshness(None, lang, "static verdict map"), lang)
    return text, menus.standard_keyboard("strategies.structural", lang)


def render_refusal(arg: str = "", lang: str = "en", page: int = 0,
                   prefs: Dict = None) -> Tuple[str, Dict]:
    ref = B.read_json(REFUSAL_FILE, {})
    if not ref:
        body = [B.unavailable(lang, REFUSAL_FILE)]
        text = B.screen("strategies.refusal", t("lbl.advisory_nocap", lang), body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("strategies.refusal", lang)
    underlyings = ref.get("underlyings", []) if isinstance(ref, dict) else []
    thr = ref.get("thresholds", {})

    if arg:  # per-underlying detail
        u = next((x for x in underlyings if str(x.get("symbol")) == arg), None)
        if u:
            body = [
                "🛡️  {}   {}".format(str(u.get("symbol", "?")).upper(),
                                     u.get("verdict", "?")),
                "",
                "tail score  {}".format(round(float(u.get("tail_score", 0.0)), 3)),
                "group       {}".format(u.get("group", "—")),
                "",
                (u.get("reason", "") or "")[:300],
            ]
            text = B.screen("strategies.refusal", t("lbl.advisory_nocap", lang), body,
                            B.freshness(ref.get("generated_at"), lang), lang)
            return text, menus.standard_keyboard("strategies.refusal", lang)

    refuse = thr.get("refuse_threshold", 0.45)
    safe = thr.get("safe_band", 0.30)
    body = [
        "🛡️  {}          {}".format(t("ttl.refusal", lang), t("s.refusal_band", lang)),
        "",
        "refuse ≥ {} · safe band ≤ {} · fail-closed".format(refuse, safe),
        "",
        " {:<12}{:>6}  {}".format("Underlying", "tail", "verdict"),
        " {:<12}{:>6}  {}".format("──────────", "─────", "────────"),
    ]
    chips: List[Dict] = []
    for u in underlyings:
        sym = str(u.get("symbol", "?"))
        mark = "✅ SAFE" if u.get("verdict") == "SAFE" else "⛔ REFUSE"
        body.append(" {:<12}{:>6}  {}".format(
            sym[:12], round(float(u.get("tail_score", 0.0)), 3), mark))
        chips.append({"text": "{} ▸".format(sym),
                      "callback_data": "nav:strategies.refusal|{}".format(sym)})
    body.append("")
    body.append(t("s.no_book_refused", lang))
    rows = [chips[i:i + 3] for i in range(0, len(chips), 3)]
    footer = B.freshness(ref.get("generated_at"), lang,
                         "{} · LLM-forbidden".format(ref.get("model", "")))
    text = B.screen("strategies.refusal", t("lbl.advisory_nocap", lang), body, footer, lang)
    return text, menus.standard_keyboard("strategies.refusal", lang, extra_rows=rows)
