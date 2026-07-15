# OWNER DECISIONS — RETIRED (переехало в files-first трекер)

> **⛔ Механизм отключён 2026-07-15** после успешного smoke-теста (ENV_SETUP_BRIEF_v3 Этап 8,
> [ADR-TEST](decisions/ADR-TEST-smoke-2026-07-15.md)). Этот файл больше НЕ источник вопросов владельцу.
> Очередь решений живёт как files-first трекер, видимый в Nimbalyst как kanban. **Не дописывать сюда.**

## Куда смотреть
- **Карточки:** `nimbalyst-local/tracker/own-*.md` (`status: needs-owner | owner-done | ingested`).
- **Тип трекера:** `.nimbalyst/trackers/owner-decision.yaml`. В Nimbalyst — трекер **Owner Decisions**.
- **Как отвечать:** перевести карточку `needs-owner → owner-done` (в Nimbalyst или правкой `status:`).
  **Только владелец** ставит `owner-done`.

## Миграция всех Q-OWN (2026-07-15, полная — включая пункты, добавленные на origin после старта работы)

**Открытые → перенесены в карточки:**
Q-OWN-06→`own-06` (RESOLVED: ключ работает, петля убрана) · Q-OWN-07→`own-07` · Q-OWN-08→`own-08` ·
Q-OWN-11→`own-11` · Q-OWN-13→`own-13` · Q-OWN-14→`own-14` · Q-OWN-15→`own-15` · Q-OWN-16→`own-16` ·
Q-OWN-17→`own-17` · Q-OWN-19→`own-19` · Q-OWN-20→`own-20`.

**Уже были закрыты (история в git + [ADR-OWN-2026-07](decisions/ADR-OWN-2026-07-owner-decisions-batch.md)):**
Q-OWN-01, 02, 03, 04, 05, 12, 21 — RESOLVED; Q-OWN-18 — FALSE ALARM (снят, CF был исправен).

_Полный прежний текст всех вопросов — в истории git этого файла._
