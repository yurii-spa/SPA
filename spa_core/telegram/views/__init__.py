#!/usr/bin/env python3
"""View registry for the interactive SPA Telegram bot (Tier-3 on-demand screens).

Each view is a pure builder ``(arg, lang, page, prefs) -> (text, reply_markup)``.
Adding a screen = add one registry entry; the router needs no edits (mirrors the
strategy-lab pluggable pattern). Builders read ``data/*.json`` read-only and are
fail-CLOSED: a missing/corrupt file renders an explicit "unavailable" line, never
a crash, never a fabricated number.

Stdlib only, deterministic, no LLM.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from spa_core.telegram.views import (
    home,
    portfolio,
    golive,
    strategies,
    health,
    reports,
    warnings,
    settings,
)

# view path -> builder(arg, lang, page, prefs) -> (text, keyboard_dict)
Builder = Callable[..., Tuple[str, Dict]]

VIEW_REGISTRY: Dict[str, Builder] = {
    "home": home.render,

    "portfolio": portfolio.render_menu,
    "portfolio.track": portfolio.render_track,
    "portfolio.positions": portfolio.render_positions,
    "portfolio.equity": portfolio.render_equity,

    "golive": golive.render_summary,
    "golive.passed": golive.render_passed,
    "golive.open": golive.render_open,

    "strategies": strategies.render_overview,
    "strategies.rates": strategies.render_rates,
    "strategies.rwa": strategies.render_rwa,
    "strategies.structural": strategies.render_structural,
    "strategies.refusal": strategies.render_refusal,

    "health": health.render_menu,
    "health.agents": health.render_agents,
    "health.system": health.render_system,
    "health.cycle": health.render_cycle,

    "reports": reports.render_menu,
    "reports.today": reports.render_today,
    "reports.weekly": reports.render_weekly,

    "warnings": warnings.render_active,
    "warnings.recent": warnings.render_recent,

    "settings": settings.render,
}


def get_builder(path: str) -> Builder:
    """Builder for a path, falling back to home. Never raises."""
    return VIEW_REGISTRY.get(path, home.render)
