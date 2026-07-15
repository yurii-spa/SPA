"""Telegram notification for new ``needs-owner`` cards (ENV_SETUP_BRIEF_v3 §3.3).

Routes through the EXISTING bot (``spa_core.telegram.bot.TelegramBot`` — the
single-authority sender, flood-guarded, Keychain creds ``TELEGRAM_BOT_TOKEN_SPA`` /
``TELEGRAM_CHAT_ID_SPA``). We deliberately do NOT import the raw transport here
(single-authority guard). ``send_message`` is a stateless POST — it takes no
poller lock, so it never conflicts with the running bot. HTML parse-mode is used
so underscores / file paths don't 400 the way Markdown does.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from spa_core.owner_queue.queue import Card, first_instruction_line, load_card

log = logging.getLogger(__name__)


def build_message(card: Card) -> str:
    """Title + first instruction line + repo-relative card path (HTML-safe)."""
    try:
        rel = card.path.resolve().relative_to(Path(__file__).resolve().parents[2])
        rel_str = str(rel)
    except Exception:
        rel_str = card.path.name
    title = html.escape(card.title or card.id)
    instr = html.escape(first_instruction_line(card))
    path = html.escape(rel_str)
    return (
        f"🟥 <b>Owner Decision — нужно решение</b>\n"
        f"<b>{title}</b>\n"
        f"➡️ {instr}\n"
        f"📄 <code>{path}</code>\n"
        f"Ответь: переведи карточку Needs Owner → Owner Done (в Nimbalyst или правкой status:)."
    )


def notify_needs_owner(path: str | Path, *, dry_run: bool = False) -> str:
    """Send a Telegram notice for a needs-owner card. Returns the message text.

    ``dry_run=True`` builds the message but does not send (used by tests / --check).
    """
    card = load_card(path)
    msg = build_message(card)
    if dry_run:
        return msg
    try:
        from spa_core.telegram.bot import TelegramBot

        ok = TelegramBot().send_message(msg, parse_mode="HTML")
        if not ok:
            log.warning("notify_needs_owner: send returned falsy for %s", path)
    except Exception as exc:  # noqa: BLE001 — notification must never crash the orchestrator
        log.warning("notify_needs_owner: send failed for %s: %s", path, exc)
    return msg
