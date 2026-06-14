"""
Go-Live Report Card — plain-text formatted output for terminal / email / GitHub Actions log.

Usage:
    from golive.report_card import generate_report_card
    from golive.checklist import run_full_check

    result = run_full_check("data")
    print(generate_report_card(result))
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

# Status → icon
_ICONS = {
    "PASS":    "✅",
    "FAIL":    "❌",
    "WARN":    "⚠ ",
    "PENDING": "⏳",
}

# Verdict → label
_VERDICT_LABELS = {
    "READY":        "READY",
    "ALMOST_READY": "ALMOST READY",
    "NOT_READY":    "NOT READY",
    "BLOCKED":      "BLOCKED",
}

# ── Box geometry ──────────────────────────────────────────────────────────────
# Total box width (chars between outer borders):
#   ╔══════════════════════════════════════════════════════╗  ← 56 ═ chars
#
# Each data row:
#   ║  <content padded to 54 chars>  ║
#   = 1 + 2 + 54 + 1 = 58 chars wide (matches ╔ + 56═ + ╗ = 58)

_INNER   = 56   # ═-count in top/bottom/divider  (== _WIDTH + 2 in old code)
_CONTENT = 54   # visible content chars per row   (== _INNER - 2 leading spaces)


def _char_width(ch: str) -> int:
    """Return terminal display width of a single Unicode character (0, 1, or 2).

    Uses unicodedata.east_asian_width — 'W' (wide) and 'F' (fullwidth) are 2
    columns; variation selectors and zero-width characters are 0; everything
    else is 1.
    """
    cp = ord(ch)
    # Variation selectors (U+FE00–U+FE0F, U+E0100–U+E01EF) are zero-width
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return 0
    # Zero-width joiner / non-joiner
    if cp in (0x200B, 0x200C, 0x200D, 0xFEFF):
        return 0
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


def _vis(text: str) -> int:
    """Return visible (terminal) column width of a string."""
    return sum(_char_width(ch) for ch in text)


def _rpad(text: str, width: int) -> str:
    """Right-pad `text` so its visible width equals `width`."""
    v = _vis(text)
    pad = max(0, width - v)
    return text + " " * pad


def _row(text: str) -> str:
    """Render one content row: ║  <text padded to _CONTENT>  ║"""
    return f"║  {_rpad(text, _CONTENT)}║"


def _divider() -> str:
    return "╠" + "═" * _INNER + "╣"


def _top() -> str:
    return "╔" + "═" * _INNER + "╗"


def _bottom() -> str:
    return "╚" + "═" * _INNER + "╝"


def _title_row(text: str) -> str:
    """Centre text inside the box."""
    # _INNER chars between the two ║
    padded = text.center(_INNER)
    return f"║{padded}║"


# ── Criterion rows ────────────────────────────────────────────────────────────
# Layout:  ICON Name_____________STATUS___note (truncated)
#          2    22               9        remainder

_NAME_W   = 22
_STATUS_W =  9

def _truncate(text: str, max_w: int) -> str:
    """Truncate text so its visible width ≤ max_w, appending '…' if cut."""
    if _vis(text) <= max_w:
        return text
    result = ""
    used = 0
    for ch in text:
        w = _char_width(ch)
        if used + w + 1 > max_w:   # +1 for the ellipsis
            result += "…"
            break
        result += ch
        used += w
    return result


def _criterion_row(c: dict) -> str:
    icon   = _ICONS.get(c["status"], "? ")
    name   = _rpad(c["name"], _NAME_W)
    status = _rpad(c["status"], _STATUS_W)

    # Remaining space for note
    used_so_far = _vis(icon) + _vis(name) + _vis(status)
    note_budget = _CONTENT - used_so_far - 2   # 2 = leading spaces in _row
    note = _truncate(c.get("note", ""), max(0, note_budget))

    return _row(f"{icon}{name}{status}{note}")


# ── Report card ───────────────────────────────────────────────────────────────

def generate_report_card(check_result: dict) -> str:
    """
    Generate a plain-text report card from a run_full_check() result dict.
    Returns a multi-line string suitable for terminal, email, or log output.
    """
    generated_at   = check_result.get("generated_at", "")
    verdict        = check_result.get("verdict", "NOT_READY")
    verdict_emoji  = check_result.get("verdict_emoji", "🔴")
    days_remaining = check_result.get("days_remaining", 0)
    go_live_date   = check_result.get("go_live_date", "2026-07-15")
    criteria       = check_result.get("criteria", [])
    recommendation = check_result.get("recommendation", "")

    # Date for header
    try:
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        date_str = generated_at[:10] if generated_at else "????-??-??"

    verdict_label = _VERDICT_LABELS.get(verdict, verdict)

    fail_count    = sum(1 for c in criteria if c["status"] == "FAIL")
    pending_count = sum(1 for c in criteria if c["status"] == "PENDING")
    warn_count    = sum(1 for c in criteria if c["status"] == "WARN")

    if fail_count:
        verdict_detail = f"{fail_count} failing"
    elif pending_count:
        verdict_detail = f"{pending_count} pending"
    elif warn_count:
        verdict_detail = f"{warn_count} warning{'s' if warn_count > 1 else ''}"
    else:
        verdict_detail = "all criteria met"

    # Next review date extracted from recommendation text
    next_review = ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", recommendation)
    if m:
        next_review = m.group(1)

    # Word-wrap recommendation to fit content width
    max_chars = _CONTENT - 4   # 2 leading + 2 indent
    rec_lines: list[str] = []
    current = ""
    for word in recommendation.split():
        test = (current + " " + word).strip()
        if len(test) > max_chars:
            if current:
                rec_lines.append(current)
            current = word
        else:
            current = test
    if current:
        rec_lines.append(current)

    lines = []
    lines.append(_top())
    lines.append(_title_row(f" SPA GO-LIVE READINESS REPORT · {date_str} "))
    lines.append(_divider())
    lines.append(_row(f"Overall Verdict: {verdict_emoji} {verdict_label} ({verdict_detail})"))
    lines.append(_row(f"Days Until Target: {days_remaining} days ({go_live_date})"))
    lines.append(_divider())

    for c in criteria:
        lines.append(_criterion_row(c))

    lines.append(_divider())

    if rec_lines:
        lines.append(_row("Recommendation:"))
        for rl in rec_lines:
            lines.append(_row(f"  {rl}"))
    else:
        lines.append(_row("Recommendation: —"))

    if next_review:
        lines.append(_row(f"Next review: {next_review}"))

    lines.append(_bottom())

    return "\n".join(lines)
