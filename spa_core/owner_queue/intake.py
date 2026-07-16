"""Событийный ЛЁГКИЙ интейк Inbox (owner-approved 2026-07-15).

Триггерится по событию (WatchPaths на inbox/ → agent_inbox_intake.sh). Делает ТОЛЬКО:
  1. `ingest_notes()` — свободные заметки Obsidian из inbox/ → inbox-карточки;
  2. для каждой НОВОЙ inbox-карточки — классификация через `ask_router` (Claude): задача/идея/непонятно;
     - **задача** → вписать критерий + статус `in-progress` (детальную работу делает ПОЛНЫЙ цикл);
     - **идея** → сохранить в `docs/ideas/<дата>-<slug>.md`, карточку → `done` (идея ≠ инструкция);
     - **непонятно** → карточка `own-*` `needs-owner` с уточняющим вопросом, исходную → `done`;
  3. короткий ответ владельцу в Telegram.

ЖЁСТКО ОГРАНИЧЕН: детерминированный Python — умеет ТОЛЬКО карточки + уведомления. НИКАКОГО кода,
git/push, деплоя, исполнения задач, правок тестов (это физически недоступно — модуль их не вызывает).
Claude запускается лишь для классификации (ask_router). Fail-safe: любая ошибка по карточке —
карточка остаётся `new` и её подхватит обычный цикл, ничего не теряется.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]


def _notify(text: str) -> None:
    """Ответ владельцу через существующий бот (единая Telegram-власть, flood-guarded)."""
    try:
        from spa_core.telegram.bot import TelegramBot

        TelegramBot().send_message(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ронять интейк
        log.warning("intake notify failed: %s", exc)


def _journal_history(dt: datetime, card, verdict: str, response: str) -> None:
    """Дописать результат проверки истории (Шаг 1a) в журнал недели (owner-directive)."""
    try:
        from spa_core.utils.atomic import atomic_save_text

        jdir = _REPO / "docs" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        iso = dt.isocalendar()
        jf = jdir / f"{iso[0]}-W{iso[1]:02d}.md"
        prev = jf.read_text(encoding="utf-8") if jf.exists() else f"# Journal · {iso[0]}-W{iso[1]:02d}\n"
        entry = (f"\n- **История-чек [{verdict}]** для «{card.title}» "
                 f"(source: {card.fields.get('source','')}): {response[:300]}")
        atomic_save_text(prev.rstrip() + entry + "\n", str(jf))
    except Exception as exc:  # noqa: BLE001
        log.warning("_journal_history failed: %s", exc)


def run_note_intake(now: datetime | None = None) -> dict:
    """Разобрать новые inbox-заметки/карточки. Returns {'processed': [...], 'urgent': bool}."""
    import html

    from spa_core.owner_queue.queue import (
        _slug,  # каноническая версия с Cyrillic→Latin транслитом (DRY — не дублировать)
        create_card,
        ingest_notes,
        list_cards,
        set_status,
    )
    from spa_core.telegram.ask_router import classify_and_answer
    from spa_core.utils.atomic import atomic_save_text

    dt = now or datetime.now(timezone.utc)
    processed: list[str] = []
    urgent = False

    try:
        ingest_notes()  # свободные заметки Obsidian → inbox-карточки
    except Exception as exc:  # noqa: BLE001
        log.warning("intake ingest_notes failed: %s", exc)

    for card in list_cards(tracker_type="inbox", status="new"):
        body = (card.body or card.title).strip()
        if "срочно" in body.lower():
            urgent = True

        # ── Шаг 1a — ПРОВЕРКА ИСТОРИИ (owner-directive 2026-07-16) ──────────────
        # Не дубль ли это? Уже сделано / в работе / осознанно отклонено → НЕ плодить
        # карточку, ответить человечески + журнал. PARTIAL → создать, но пометить.
        partial_note = ""
        try:
            from spa_core.owner_queue.history_check import history_check, is_duplicate

            hc = history_check(body)
            verdict = hc.get("verdict", "NEW")
            resp_h = hc.get("response", "")
            if is_duplicate(verdict):
                icon = {"DONE": "✅", "IN_PROGRESS": "🔧", "REJECTED": "🚫"}.get(verdict, "ℹ️")
                _notify(f"{icon} {html.escape(resp_h or 'нашёл совпадение в памяти — дубль не создаю')}")
                _journal_history(dt, card, verdict, resp_h)
                set_status(card.path, "done")
                processed.append(card.id)
                continue
            if verdict == "PARTIAL" and resp_h:
                partial_note = resp_h
                _journal_history(dt, card, "PARTIAL", resp_h)
        except Exception as exc:  # noqa: BLE001 — history-check не должен ронять приём
            log.warning("intake history_check failed for %s: %s — продолжаю как NEW", card.id, exc)

        try:
            kind, resp = classify_and_answer(body)
        except Exception as exc:  # noqa: BLE001 — карточка ждёт обычного цикла
            log.warning("intake classify failed for %s: %s — leaving as new", card.id, exc)
            continue

        try:
            if kind == "idea":
                ideas = _REPO / "docs" / "ideas"
                ideas.mkdir(parents=True, exist_ok=True)
                fpath = ideas / f"{dt.strftime('%Y-%m-%d')}-{_slug(card.title)}.md"
                atomic_save_text(f"# {card.title}\n\n_Из Inbox {dt.strftime('%Y-%m-%d')} (source: {card.fields.get('source','')})._\n\n{body}\n", str(fpath))
                set_status(card.path, "done")
                _notify(f"💡 Записал как идею: <b>{html.escape(card.title)}</b>")
            elif kind == "unclear":
                q = resp or "Уточни: это вопрос или задача?"
                create_card(
                    "owner-decision",
                    f"Уточнение по заметке: {card.title}",
                    body=(f"## Что случилось и почему это важно\nПришло сообщение, непонятно — вопрос это или задача.\n\n"
                          f"Текст: «{body}»\n\n## Что от тебя нужно\n{q}\n\n"
                          f"## Как понять, что готово\nТы уточнил.\n\n## Что будет после\nОбработаю по твоему ответу."),
                    status="needs-owner", source="intake",
                )
                set_status(card.path, "done")
                _notify(f"❓ Есть вопрос — смотри карточку: {html.escape(q)}")
            else:  # task
                # вписать критерий (полную декомпозицию делает обычный цикл), статус in-progress
                if "Как понять, что готово" not in body:
                    txt = card.path.read_text(encoding="utf-8").rstrip() + \
                        "\n\n## Как понять, что готово\nЗадача выполнена и проверена (детали — обычный цикл).\n"
                    atomic_save_text(txt, str(card.path))
                set_status(card.path, "in-progress")
                _notify(f"📥 Создал задачу: <b>{html.escape(card.title)}</b>")
            processed.append(card.id)
        except Exception as exc:  # noqa: BLE001 — карточка остаётся new → обычный цикл
            log.warning("intake route failed for %s: %s — leaving as new", card.id, exc)

    return {"processed": processed, "urgent": urgent}
