#!/usr/bin/env python3
"""Menu tree + keyboard builders for the interactive SPA Telegram bot.

Implements the tree from ``docs/TELEGRAM_BOT_UX.md`` §2. The tree is data:
each node has a dotted ``path`` (the ``nav:<path>`` callback target), a
breadcrumb-segment i18n key, and a list of child paths. Back is computed as
the parent of the current path (drop the last dotted segment) — no separate
state needed, restart-safe.

callback_data grammar (≤ 64 bytes, stateless):
    nav:<path>            navigate to a view, e.g. ``nav:strategies.rates``
    act:<verb>:<arg>      an action, e.g. ``act:setlang:ru``, ``act:mute:8h``
    pg:<path>:<n>         page n of a paged view, e.g. ``pg:health.agents:2``

Stdlib only, deterministic, no LLM.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from spa_core.telegram.i18n import t

HOME = "home"

# path -> (breadcrumb i18n key, [child paths])
# Children are rendered as the screen's inline buttons (2 per row).
TREE: Dict[str, Dict] = {
    "home": {"crumb": "crumb.home", "children": [
        "portfolio", "golive", "strategies", "health",
        "reports", "warnings", "settings",
    ]},

    "portfolio": {"crumb": "crumb.portfolio", "children": [
        "portfolio.track", "portfolio.positions", "portfolio.equity",
    ]},
    "portfolio.track": {"crumb": "crumb.track", "children": [
        "portfolio.positions", "portfolio.equity",
    ]},
    "portfolio.positions": {"crumb": "crumb.positions", "children": []},
    "portfolio.equity": {"crumb": "crumb.equity", "children": []},

    "golive": {"crumb": "crumb.golive", "children": [
        "golive.passed", "golive.open",
    ]},
    "golive.passed": {"crumb": "crumb.passed", "children": [], "paged": True},
    "golive.open": {"crumb": "crumb.open", "children": []},

    "strategies": {"crumb": "crumb.strategies", "children": [
        "strategies.rates", "strategies.rwa",
        "strategies.structural", "strategies.refusal",
    ]},
    "strategies.rates": {"crumb": "crumb.rates", "children": [], "dynamic": True},
    "strategies.rwa": {"crumb": "crumb.rwa", "children": []},
    "strategies.structural": {"crumb": "crumb.structural", "children": []},
    "strategies.refusal": {"crumb": "crumb.refusal", "children": [], "dynamic": True},

    "health": {"crumb": "crumb.health", "children": [
        "health.agents", "health.system", "health.cycle",
    ]},
    "health.agents": {"crumb": "crumb.agents", "children": [], "paged": True},
    "health.system": {"crumb": "crumb.system", "children": []},
    "health.cycle": {"crumb": "crumb.cycle", "children": []},

    "reports": {"crumb": "crumb.reports", "children": [
        "reports.today", "reports.weekly",
    ]},
    "reports.today": {"crumb": "crumb.today", "children": []},
    "reports.weekly": {"crumb": "crumb.weekly", "children": []},

    "warnings": {"crumb": "crumb.warnings", "children": [
        "warnings.recent",
    ]},
    "warnings.recent": {"crumb": "crumb.recent", "children": []},

    "settings": {"crumb": "crumb.settings", "children": []},  # custom keyboard
}

# button label i18n key per child path (the leftmost glyph + word)
_CHILD_LABEL: Dict[str, str] = {
    "portfolio": "btn.portfolio",
    "golive": "btn.golive",
    "strategies": "btn.strategies",
    "health": "btn.health",
    "reports": "btn.reports",
    "warnings": "btn.warnings",
    "settings": "btn.settings",
    "portfolio.track": "btn.track",
    "portfolio.positions": "btn.positions",
    "portfolio.equity": "btn.equity_history",
    "golive.passed": "btn.passed",
    "golive.open": "btn.open",
    "strategies.rates": "btn.rates_desk",
    "strategies.rwa": "btn.rwa_board",
    "strategies.structural": "btn.structural_desk",
    "strategies.refusal": "btn.refusal_log",
    "health.agents": "btn.agents",
    "health.system": "btn.system",
    "health.cycle": "btn.last_cycle",
    "reports.today": "btn.today",
    "reports.weekly": "btn.weekly",
    "warnings.recent": "btn.recent",
}


def parent_of(path: str) -> str:
    """Parent path (one level up). Home is its own parent."""
    if "." not in path:
        return HOME
    return path.rsplit(".", 1)[0]


def breadcrumb(path: str, lang: str = "en") -> str:
    """``Home › Strategies › Rates Desk`` (localized segments)."""
    segs: List[str] = []
    node = TREE.get(path)
    # walk up the parent chain collecting crumbs
    chain = [path]
    cur = path
    while cur != HOME:
        cur = parent_of(cur)
        chain.append(cur)
    chain.reverse()
    for p in chain:
        n = TREE.get(p)
        if n:
            segs.append(t(n["crumb"], lang))
    return " › ".join(segs)


def is_paged(path: str) -> bool:
    return bool(TREE.get(path, {}).get("paged"))


# ── Keyboard builders ──────────────────────────────────────────────────────


def _rows(buttons: List[Dict], per_row: int = 2) -> List[List[Dict]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def nav_row(path: str, lang: str = "en") -> List[Dict]:
    """The reserved last row: [◀ Back] [🏠 Home] for non-home, else [🔄 Refresh]."""
    if path == HOME:
        return [{"text": t("btn.refresh", lang), "callback_data": "nav:home"}]
    return [
        {"text": t("btn.back", lang), "callback_data": "nav:" + parent_of(path)},
        {"text": t("btn.home", lang), "callback_data": "nav:home"},
    ]


def child_buttons(path: str, lang: str = "en") -> List[Dict]:
    """Inline buttons for the static children of a node."""
    out: List[Dict] = []
    for child in TREE.get(path, {}).get("children", []):
        lbl_key = _CHILD_LABEL.get(child, child)
        out.append({"text": t(lbl_key, lang), "callback_data": "nav:" + child})
    return out


def standard_keyboard(path: str, lang: str = "en",
                      extra_rows: Optional[List[List[Dict]]] = None) -> Dict:
    """Child buttons (2/row) + any extra rows + the nav row last."""
    rows = _rows(child_buttons(path, lang), per_row=2)
    if extra_rows:
        rows.extend(extra_rows)
    rows.append(nav_row(path, lang))
    return {"inline_keyboard": rows}


def pager_row(path: str, page: int, total_pages: int, lang: str = "en") -> List[Dict]:
    """[◀] n/N [▶] chips using pg:<path>:<n> callbacks."""
    prev_p = max(0, page - 1)
    next_p = min(total_pages - 1, page + 1)
    return [
        {"text": "◀", "callback_data": "pg:{}:{}".format(path, prev_p)},
        {"text": "{}/{}".format(page + 1, total_pages), "callback_data": "nav:" + path},
        {"text": "▶", "callback_data": "pg:{}:{}".format(path, next_p)},
    ]


def home_keyboard(lang: str = "en") -> Dict:
    """The L0 home grid: 6 sections + Settings + Refresh (per UX §4.1)."""
    children = TREE["home"]["children"]  # 7 sections
    btns = [{"text": t(_CHILD_LABEL[c], lang), "callback_data": "nav:" + c}
            for c in children]
    rows = _rows(btns, per_row=2)
    # append Refresh next to the (odd) last button row or on its own
    refresh = {"text": t("btn.refresh", lang), "callback_data": "nav:home"}
    if rows and len(rows[-1]) == 1:
        rows[-1].append(refresh)
    else:
        rows.append([refresh])
    return {"inline_keyboard": rows}


def settings_keyboard(prefs: Dict, lang: str = "en") -> Dict:
    """Settings toggles (UX §4.15): language flip, daily/weekly on-off,
    warnings 3-way, mute chips."""
    next_lang = "RU" if lang == "en" else "EN"
    daily_state = t("btn.off", lang) if prefs.get("daily", True) else t("btn.on", lang)
    weekly_state = t("btn.off", lang) if prefs.get("weekly", True) else t("btn.on", lang)
    rows = [
        [
            {"text": "{}: {}".format(t("btn.language", lang), next_lang),
             "callback_data": "act:togglelang:1"},
            {"text": "{}: {}".format(t("btn.daily", lang), daily_state),
             "callback_data": "act:toggle:daily"},
        ],
        [
            {"text": "{}: {}".format(t("btn.weekly_toggle", lang), weekly_state),
             "callback_data": "act:toggle:weekly"},
        ],
        [
            {"text": "{} {}".format(t("btn.warnings_pref", lang), t("btn.all", lang)),
             "callback_data": "act:warnlevel:all"},
            {"text": t("btn.critical_only", lang), "callback_data": "act:warnlevel:critical"},
            {"text": t("btn.off", lang), "callback_data": "act:warnlevel:off"},
        ],
        [
            {"text": "{} 1h".format(t("btn.mute", lang)), "callback_data": "act:mute:1h"},
            {"text": "8h", "callback_data": "act:mute:8h"},
            {"text": t("btn.until_unmute", lang), "callback_data": "act:mute:inf"},
        ],
        nav_row("settings", lang),
    ]
    return {"inline_keyboard": rows}
