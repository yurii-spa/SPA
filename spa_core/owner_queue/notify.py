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
    """Запасной вид уведомления: заголовок, первая строка задания, путь к карточке.

    Используется, когда варианты ответа из карточки разобрать не удалось (fail-CLOSED —
    выдумывать выбор владельцу нельзя). Основной, человеческий вид строит
    ``spa_core.telegram.owner_decisions``.
    """
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
    """Отправить владельцу карточку решения — с вариантами ответа и рекомендацией.

    Задание владельца 2026-08-08: решение должно приходить простым языком, с вариантами
    и пометкой «рекомендую», чтобы отвечать можно было прямо с телефона.

    Fail-CLOSED в две стороны, и обе намеренные:

    * варианты не разобрались ⇒ уходит СТАРЫЙ вид уведомления (кнопок нет, но владелец
      узнаёт о решении) — выдумывать варианты нельзя;
    * бот не умеет обработать нажатие (маячок ADR-069) ⇒ текст уходит без кнопок.

    ``dry_run=True`` собирает сообщение, но не отправляет (тесты / ``--check``).
    """
    card = load_card(path)
    keyboard = None
    try:
        from spa_core.telegram import owner_decisions

        prep = owner_decisions.register_push(card.path, card.title or card.id, card.body)
        # Берём подготовленный текст ВСЕГДА, а не только когда есть варианты.
        # Раньше при пустом списке уходил старый служебный вид — и многовыборная карточка
        # («можно взять несколько», вариантов намеренно ноль) теряла ЧЕСТНОЕ объяснение
        # «кнопок нет, ответь номерами», получая вместо него «переведи статус в Nimbalyst».
        # Запасной вид остаётся только на случай, когда подготовка вообще не удалась.
        msg = prep.text
        keyboard = prep.keyboard
    except Exception as exc:  # noqa: BLE001 — красивый вид не важнее самого уведомления
        log.warning("notify_needs_owner: rich build failed for %s: %s", path, exc)
        msg = build_message(card)

    if dry_run:
        return msg
    try:
        from spa_core.telegram.bot import TelegramBot

        bot = TelegramBot()
        # `reply_markup` передаём ТОЛЬКО когда кнопки есть: путь без кнопок обязан остаться
        # байт-в-байт прежним. И даже с кнопками — откатываемся на отправку без них, если
        # отправитель этого параметра не знает. Потерять оформление можно; потерять само
        # уведомление о решении владельца — нет.
        try:
            ok = (bot.send_message(msg, parse_mode="HTML", reply_markup=keyboard)
                  if keyboard is not None
                  else bot.send_message(msg, parse_mode="HTML"))
        except TypeError as exc:
            log.warning("notify_needs_owner: sender rejected reply_markup (%s) — "
                        "отправляю без кнопок", exc)
            ok = bot.send_message(msg, parse_mode="HTML")
        if not ok:
            log.warning("notify_needs_owner: send returned falsy for %s", path)
    except Exception as exc:  # noqa: BLE001 — notification must never crash the orchestrator
        log.warning("notify_needs_owner: send failed for %s: %s", path, exc)
    return msg


WITHDRAWN_REASON = ("находка исчезла при следующем прогоне сторожа — "
                    "тревога оказалась ложной")


def build_withdrawn_message(card: Card, reason: str = WITHDRAWN_REASON) -> str:
    try:
        rel = str(card.path.resolve().relative_to(Path(__file__).resolve().parents[2]))
    except Exception:
        rel = card.path.name
    return (
        f"🟩 <b>Вопрос снят — отвечать не нужно</b>\n"
        f"<b>{html.escape(card.title or card.id)}</b>\n"
        f"➡️ {html.escape(reason)}\n"
        f"📄 <code>{html.escape(rel)}</code>\n"
        f"Карточка закрыта автоматически. Считаешь, что вопрос остался — верни ей статус."
    )


def notify_card_withdrawn(path: str | Path, *, reason: str = WITHDRAWN_REASON,
                          dry_run: bool = False) -> str:
    """Сообщить владельцу, что заданный ему вопрос отпал (цикл #172).

    Пара к :func:`notify_needs_owner`. Без неё авто-закрытие карточки означало бы,
    что в чате навсегда висит «нужно решение» по вопросу, которого больше нет:
    владелец видит требование, а карточка за ним уже `done`. Снять вопрос молча —
    отдельный дефект, а не экономия сообщения.

    Заодно гасим кнопки этой карточки: нажатие по старому сообщению не должно
    записывать «ответ владельца» в закрытую карточку (см. ``owner_decisions``).
    """
    card = load_card(path)
    msg = build_withdrawn_message(card, reason)
    if dry_run:
        return msg
    try:
        from spa_core.telegram import owner_decisions

        owner_decisions.mark_withdrawn(card.path)
    except Exception as exc:  # noqa: BLE001 — кнопки важны, но отзыв важнее
        log.warning("notify_card_withdrawn: mark_withdrawn failed for %s: %s", path, exc)
    try:
        from spa_core.telegram.bot import TelegramBot

        if not TelegramBot().send_message(msg, parse_mode="HTML"):
            log.warning("notify_card_withdrawn: send returned falsy for %s", path)
    except Exception as exc:  # noqa: BLE001 — уведомление не роняет оркестратор
        log.warning("notify_card_withdrawn: send failed for %s: %s", path, exc)
    return msg
