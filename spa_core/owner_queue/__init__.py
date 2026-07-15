"""Owner-queue: files-first очередь карточек (Owner Decisions + Inbox).

Детерминированный, stdlib-only слой над Nimbalyst-native markdown-карточками в
``nimbalyst-local/tracker/``. Источник правды — сами файлы в git; Nimbalyst и этот
модуль — лишь окна/инструменты над ними.

Экспортирует парсинг карточек, листинг по типу/статусу, атомарную смену статуса
(с жёстким запретом ``owner-done`` для агентов) и Telegram-уведомление о новых
``needs-owner`` карточках. Используется протоколом оркестратора (docs/ORCHESTRATOR_PROTOCOL.md).
"""

from spa_core.owner_queue.queue import (
    Card,
    TRACKER_DIR,
    list_cards,
    load_card,
    set_status,
    create_card,
    ingest_notes,
    scan_promotions,
    Promotion,
    first_instruction_line,
    OwnerDoneForbidden,
)

__all__ = [
    "Card",
    "TRACKER_DIR",
    "list_cards",
    "load_card",
    "set_status",
    "create_card",
    "ingest_notes",
    "scan_promotions",
    "Promotion",
    "first_instruction_line",
    "OwnerDoneForbidden",
]
