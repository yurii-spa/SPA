#!/usr/bin/env python3
"""Go-Live views: Summary, Passed (paged), Open (UX §4.4–4.5)."""
from __future__ import annotations

from typing import Dict, List, Tuple

from spa_core.telegram import menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B

PER_PAGE = 10


def _criteria(gl: Dict) -> List[Dict]:
    crit = gl.get("criteria") if isinstance(gl, dict) else None
    if isinstance(crit, list) and crit:
        return crit
    # fall back to the flat checks map
    out = []
    for name, ok in (gl.get("checks", {}) or {}).items():
        out.append({"name": name, "status": "PASS" if ok else "PENDING",
                    "blocking": not ok})
    return out


def _gl_ts(gl: Dict):
    """Момент замера GoLive: производитель пишет ``timestamp`` (находка T08: экран искал только
    ``generated_at``/``ts`` и печатал «обновлено —»)."""
    return gl.get("generated_at") or gl.get("ts") or gl.get("timestamp")


def golive_verdict(gl: Dict, lang: str) -> str:
    """Вердикт словами, где «критерии пройдены» ≠ «live разрешён» (находка F5/E1).

    ``ready`` у ``golive_checker`` значит «все критерии инвентаря PASS»; разрешение на настоящие деньги
    даёт только владелец, и пока его нет, ``go_live_state`` = ``gate_passed_owner_decision_pending``."""
    state = gl.get("go_live_state")
    if gl.get("ready") and state == "gate_passed_owner_decision_pending":
        return ("✅ критерии пройдены · ⛔ live НЕ разрешён — решения владельца нет (бумага, капитал $0)"
                if lang == "ru" else
                "✅ criteria pass · ⛔ live NOT authorised — no owner decision (paper, capital $0)")
    if gl.get("ready") and state not in (None, "gate_passed_owner_decision_pending"):
        return ("⚠️ критерии пройдены, состояние «{}» не распознано — live не разрешён".format(state)
                if lang == "ru" else "⚠️ criteria pass, state «{}» unknown — live not authorised".format(state))
    if gl.get("ready"):
        return ("✅ критерии пройдены · live разрешает только владелец" if lang == "ru"
                else "✅ criteria pass · only the owner authorises live")
    return "⛔ " + t("lbl.not_ready", lang)


def render_summary(arg: str = "", lang: str = "en", page: int = 0,
                   prefs: Dict = None) -> Tuple[str, Dict]:
    gl = B.read_json("golive_status.json", {})
    if not gl:
        body = [B.unavailable(lang, "golive_status.json")]
        text = B.screen("golive", "gate · honest", body, B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("golive", lang)

    passed = gl.get("passed", "?")
    total = gl.get("total", "?")
    verdict = golive_verdict(gl, lang)
    open_crit = [c for c in _criteria(gl) if c.get("status") != "PASS"]
    body = [
        "🎯  {}".format(t("ttl.golive", lang)),
        "",
        "      {} / {}  PASS        {}".format(passed, total, verdict),
        "",
        "Open ({}):".format(t("lbl.time_gated", lang)),
    ]
    eta_days = None
    for c in open_crit:
        body.append("  ⏳ {:<20} {}".format(c.get("name", "?"),
                                            (c.get("message", "") or "")[:40]))
        if c.get("estimated_days_to_pass"):
            eta_days = c.get("estimated_days_to_pass")
    if eta_days:
        body.append("")
        body.append("{}  ~{} more real track-days".format(t("w.eta", lang), eta_days))
    text = B.screen("golive", "gate v6.0 · honest", body,
                    B.freshness(_gl_ts(gl), lang), lang)
    return text, menus.standard_keyboard("golive", lang)


def render_passed(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    gl = B.read_json("golive_status.json", {})
    passed = [c for c in _criteria(gl) if c.get("status") == "PASS"]
    sl, page, total_pages = B.paginate(passed, page, PER_PAGE)
    body = ["✅  {}  ({})".format(t("ttl.passed", lang), len(passed)), ""]
    for c in sl:
        body.append(" ✅ {}".format(c.get("name", "?")))
    extra = [menus.pager_row("golive.passed", page, total_pages, lang)]
    text = B.screen("golive.passed",
                    "{} {} / {}".format(t("w.page", lang), page + 1, total_pages),
                    body, "", lang)
    # drop the empty footer line cleanly
    text = text.rstrip("\n" + B.RULE).rstrip()
    return text, menus.standard_keyboard("golive.passed", lang, extra_rows=extra)


def render_open(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    gl = B.read_json("golive_status.json", {})
    open_crit = [c for c in _criteria(gl) if c.get("status") != "PASS"]
    body = ["⏳  {}  ({})".format(t("ttl.open", lang), len(open_crit)), ""]
    if not open_crit:
        body.append("✅ none — all criteria pass")
    for c in open_crit:
        body.append(" ⏳ {}".format(c.get("name", "?")))
        msg = (c.get("message", "") or "")[:60]
        if msg:
            body.append("    → {}".format(msg))
    text = B.screen("golive.open", t("lbl.time_gated", lang), body,
                    B.freshness(_gl_ts(gl), lang), lang)
    return text, menus.standard_keyboard("golive.open", lang)
