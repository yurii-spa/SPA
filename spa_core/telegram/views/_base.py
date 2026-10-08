#!/usr/bin/env python3
"""Shared helpers for SPA Telegram bot views: JSON reads, formatters, the
standard screen skeleton (breadcrumb header + body + freshness footer).

Stdlib only, fail-CLOSED, deterministic, no LLM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from spa_core.telegram import menus
from spa_core.telegram.i18n import t

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"

RULE = "─────────────────────────────"


def read_json(name: str, default: Any) -> Any:
    """Read ``data/<name>`` JSON. Returns ``default`` on any error. Never raises.

    ``name`` may include sub-paths (e.g. ``rates_desk/rates_desk_promotion.json``).
    """
    p = DATA_DIR / name
    try:
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def fmt_usd(value: Any, signed: bool = False) -> str:
    try:
        v = float(value or 0.0)
    except (TypeError, ValueError):
        return "$—"
    s = "+" if (signed and v >= 0) else ("-" if (signed and v < 0) else "")
    return "{}${:,.2f}".format(s, abs(v) if signed else v)


def fmt_pct(value: Any, signed: bool = True, dp: int = 2, lang: str = "en") -> str:
    """Owner presentation policy (ADR-660): two decimals, ROUND_HALF_UP, locale-aware.

    ``dp`` is kept for callers' signatures and IGNORED — the owner fixed the precision at two.
    Absent ⇒ «—%», never «+0.00%» (inv. #17: the old ``float(value or 0.0)`` turned a missing
    number into a measured zero)."""
    from spa_core.utils.presentation import fmt_pct as _canon
    return _canon(value, lang, signed=signed, unknown="—%")


def arrow(value: Any) -> str:
    try:
        return "▲" if float(value or 0.0) >= 0 else "▼"
    except (TypeError, ValueError):
        return ""


def short_ts(ts: Any) -> str:
    """``2026-06-26T06:00:02+00:00`` → ``08:00 Мадрид``. Tolerant.

    Owner-facing time is Europe/Madrid (ADR-660, CET/CEST automatic); the machine stamp
    stays UTC in the data. Unparseable ⇒ shown as is, never a guessed time."""
    from spa_core.utils.presentation import fmt_owner_time
    s = str(ts or "")
    if "T" in s and len(s) >= 16:
        local = fmt_owner_time(s, "ru", with_date=False, label=False)
        if local is not None:
            return local + " Мадрид"
        return s[11:16] + " UTC"
    return s[:16] if s else "—"


def date_part(ts: Any) -> str:
    return str(ts or "")[:10] or "—"


def freshness(ts: Any, lang: str = "en", suffix: str = "") -> str:
    """Freshness footer line: ``updated 08:00 Мадрид · <suffix>`` or stale."""
    base = "{} {}".format(t("lbl.updated", lang), short_ts(ts))
    if suffix:
        base += " · " + suffix
    return base


def unavailable(lang: str, fname: str) -> str:
    return "{} ({})".format(t("lbl.unavailable", lang), fname)


def screen(path: str, label: str, body_lines: List[str], footer: str,
           lang: str = "en") -> str:
    """Assemble the standard three-band screen (UX §1).

    header (breadcrumb + honest label) · RULE · body · RULE · footer.
    """
    header = "{}    {}".format(menus.breadcrumb(path, lang), label).rstrip()
    parts = [header, RULE]
    parts.extend(body_lines)
    parts.append(RULE)
    parts.append(footer)
    return "\n".join(parts)


def paginate(items: List[Any], page: int, per_page: int) -> (List[Any], int, int):
    """Return (slice, clamped_page, total_pages) for a 0-based page."""
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total - 1))
    start = page * per_page
    return items[start:start + per_page], page, total
