# DISPATCH REPORT — SPA-V351 — Architect Review + KANBAN Housekeeping

**Дата:** 2026-05-30
**Спринт:** v3.51 (SPA-V330-style)
**Триггер:** v3.50 закончился на «0» → периодический architect review (каждые 5 спринтов)
**Исполнитель:** оркестратор (Claude архитекторского уровня) — напрямую

---

## 0. Почему review выполнен напрямую, а не через architect.py

`spa_core/dev_agents/architect.py` — это **LLM-обёртка над Claude API** (`import anthropic`, `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`, модель `claude-sonnet-4-6`). В автономной песочнице нет ни пакета `anthropic`, ни `ANTHROPIC_API_KEY`, поэтому `python -m spa_core.dev_agents.architect --command review-backlog` падает с `ModuleNotFoundError: No module named 'anthropic'`.

Поскольку сам оркестратор является Claude-инстансом архитекторского уровня, review выполнен напрямую в том же формате, что ожидает `review_backlog()` (next sprint / defer / risks). Это разумный автономный выбор — внешний LLM-вызов не добавил бы ценности к тому, что оркестратор делает нативно.

---

## 1. Next sprint recommendation

| # | Задача | Оценка | Статус блокировки |
|---|--------|--------|-------------------|
| 1 | **SPA-V326 / SPA-BL-010 — MEV Protection (Flashbots Protect RPC)** в `eth_signer.py` | 6h | **разблокирована** ← рекомендуется |
| 2 | Закрытие user-action блокеров (RPC keys / Telegram / Gnosis Safe) | — | blocked on user |
| 3 | FEAT-001 Phase 3 live execution | 80h | blocked (go-live ADR 2026-07-15 + secrets) |

**Главная рекомендация:** следующий dev-спринт — **MEV Protection (SPA-BL-010)**. Это единственная разблокированная HIGH-приоритетная **код**-работа, имеющая прямую ценность для go-live (защита live-транзакций от sandwich/frontrun). Она замещает «feed-health монитор #10».

## 2. Items to defer

- **Feed-health монитор #10 / кросс-сигнальная корреляция** — ЗАМОРОЖЕН (см. SPA-BL-011). 9 мониторов за v3.40→v3.50 уже покрывают свежесть, счётчики, дельты TVL, per-protocol аномалии/dropout/staleness, schema-drift, диапазоны значений и монотонность дат. Кросс-сигнальная корреляция — это агрегация уже покрытых сигналов, дублирует v3.47 `feed_health_summary.py`, а не новый класс отказа.
- **FEAT-001/002 Phase 3/4 live capital** — после go-live ADR 2026-07-15 и закрытия user-action секретов.
- **IDEA-002/003/004** (Mobile app, Discord bot, Multi-user) — post-go-live, LOW.
- **BL-001 Mac Mini** — post-go-live, MEDIUM (IDEA-001 объединён сюда как дубль).
- **BL-007 Sky/sUSDS T1** — условный, ждёт on-chain GSM ≥48h.

## 3. Risks / blockers

**КРИТИЧЕСКИЙ ПУТЬ к go-live (2026-07-15, ~7 недель) — это user actions, не код.** Весь HIGH-приоритетный backlog заблокирован на пользователе:

- `BL-004` — включить GitHub Pages (Settings → Pages)
- `BL-005` / `SPA-BL-008` — Telegram bot token + chat ID в Secrets
- `BL-006` — PAT с `workflow` scope
- `SPA-BL-007` — Alchemy/Infura RPC keys в Secrets (нужны для live MorphoAdapter/AaveV3/CompoundV3)
- `SPA-BL-009` — Gnosis Safe + `SPA_WALLET_ADDRESS` (Go-Live критерий #9)

**Диагноз monitor-treadmill:** dev-агент построил 9 feed-health мониторов подряд именно потому, что это была единственная разблокированная код-работа. Дальнейшие мониторы дают убывающую ценность. До разблокировки секретов реальная go-live-работа (live execution, реальные алерты) невозможна.

---

## 4. Выполненный housekeeping (KANBAN.json)

1. **IDEA-001** (Mac Mini Local Server) → `status: superseded`, `superseded_by: BL-001` — дубликат backlog-карточки BL-001.
2. **+SPA-BL-010** MEV Protection / Flashbots (HIGH) — следующий разблокированный код-спринт.
3. **+SPA-BL-011** GOVERNANCE: feed-health домен заморожен (HIGH, 0h) — монитор #10 только под НОВЫЙ класс отказа.
4. **+SPA-BL-012** CRITICAL PATH: go-live user-action трекер (HIGH, blocked_by user_action) — эскалация видимости блокеров.
5. Подтверждено `done` (во избежание повторного взятия): V327 live-APY-feed (`defillama_apy_feed.py` + v3.35 enrichment), V328 Pendle-PT, V331 pg-migration-prep (v3.41), V332 go-live-dashboard (v3.33–3.35).

**Status pass НЕ применялся** — housekeeping является реальной работой спринта (изменены 3 файла, добавлены 3 backlog-карточки, 1 dedup).

---

## 5. Артефакты

- `KANBAN.json` — обновлён (валиден, round-trip OK); бэкап `.bak.v351`.
- `SPA_sprint_log.md` — запись v3.51; бэкап `.bak.v351`.
- `DISPATCH_REPORT_2026-05-30_v351_architect.md` — этот отчёт.
- `push_v351.html` — для пуша через localhost:8765.
