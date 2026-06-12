# Status System & Backlog/Kanban Audit

**Дата:** 2026-06-12  
**Автор:** Claude (T2+T3 audit task)  
**Файлы:** `index.html` (~7200 строк), `KANBAN.json` (1778 строк), `data/decisions.json`

---

## T2: Backlog vs Kanban

### Текущее состояние

#### KANBAN.json — структура колонок

| Колонка | Кол-во items | Описание |
|---|---|---|
| `ideas` | 3 | IDEA-002/003/004 — «post-live drops», низкий приоритет |
| `features` | 10 | MP-402–MP-411, MP-503–MP-507 — эпики Phase 4/5, не взяты в работу |
| `backlog` | 4 | MP-071 (PAT rotation), MP-017, UA-004, UA-006 — приоритизированные задачи |
| `in_progress` | 0 | Пусто |
| `review` | 0 | Пусто |
| `done` | 40+ | Все завершённые задачи с 2026-06-10 |

#### index.html — навигация (строки 872–881)

```
📊 Dashboard   → tab-overview   (новый, v2.0)
📑 Paper Test  → tab-dashboard  (paper trading)
✍️ Decisions   → tab-decisions  (owner review workflow)
📋 Tasks       → tab-kanban     ← СТАТИЧНЫЙ hardcoded HTML
🗂 Kanban      → tab-backlog    ← ЖИВОЙ KANBAN.json через loadBacklog()
📈 Statistics  → ...
👾 Team        → ...
🎯 Go-Live     → ...
⚙️ System      → ...
```

#### Что рендерит tab-kanban (строки 1027–1161)

**Полностью статичный hardcoded HTML** из эпохи v0.4.5 (до teardown 2026-06-10):

- БЭКЛОГ: 9 карточек (CopilotKit, WebSocket, PostgreSQL миграция, Sky/sUSDS 48h GSM и др.) — **устаревшие, не из KANBAN.json**
- В РАБОТЕ: 4 карточки (Paper Trading 8-week clock, Dashboard v0.4, Агент-боты, FastAPI) — **устаревшие**
- НА ПРОВЕРКУ: 2 карточки — **устаревшие**
- ГОТОВО: 24 карточки — **устаревшие, из v0.4.5**

Этот таб **не читает KANBAN.json ни строчкой** — всё захардкожено.

#### Что рендерит tab-backlog (строки 1164–1180 + JS 4790–4856)

Динамическая загрузка KANBAN.json через `loadBacklog()` → `renderBacklog()`:

- 🔴 PHASE 0 — СРОЧНО: items из `backlog` с `phase=phase0` + `priority=P0`
- 🟡 BACKLOG: остальные items из `backlog` + `in_progress` + `review`
- 🔵 FEATURES: items из `features`, сгруппированные по phase
- ✅ DONE: items из `done`, отсортированные по дате

Вкладка называется "🗂 Kanban" и реально является **живым Kanban-бордом**.

---

### Проблемы и дублирование

1. **Перепутаны ярлыки.** Вкладка "📋 Tasks" ведёт на старый статичный `tab-kanban`, а "🗂 Kanban" — на живой `tab-backlog`. Логически должно быть наоборот: живой борд = Kanban.

2. **tab-kanban — мёртвый контент.** Весь контент — snapshot v0.4.5 (до teardown). Отображает задачи, большинство которых либо уже в done в KANBAN.json, либо более не актуальны. Например: «PostgreSQL миграция» = уже `done` в KANBAN.json (MP-210).

3. **Дублирование задач.** Ряд пунктов из статичного `tab-kanban` присутствует в `done` KANBAN.json:
   - «PostgreSQL миграция» → MP-210 done
   - «Security audit + VPN + Kill Switch тест» → MP-108 done  
   - «Backtest Engine (DeFiLlama history 2022+)» → MP-212 done
   - «Dashboard v0.4 — live данные из JSON» → MP-007 done

4. **Счётчик Kanban Tab.** `backlog-tab-count` считает только `backlogAll.length` (4), не включая in_progress/review. Итог: "🗂 Kanban (4)" — вводит в заблуждение.

5. **in_progress и review в KANBAN.json — пустые.** В реальности никакого отдельного "In Progress" не ведётся — текущие задачи просто берутся и сразу завершаются, минуя явный in_progress статус.

---

### Рекомендуемая граница

| Источник | Целевая вкладка | Содержание |
|---|---|---|
| `KANBAN.json` → columns: `backlog` + `in_progress` + `review` | **Kanban** | Активные задачи — что в работе прямо сейчас |
| `KANBAN.json` → columns: `features` + `ideas` | **Backlog** | Будущие задачи — не взяты в работу |
| `KANBAN.json` → columns: `done` | часть Kanban / отдельная секция | Завершённые |

**Действия:**
- `tab-kanban` (статичный) → **удалить или переработать** в что-то полезное (например, interactive milestone tracker)
- Переименовать tab-button "📋 Tasks" → "📋 Milestones" (если оставить статичные вехи)
- "🗂 Kanban" остаётся живым бордом — правильно
- В `renderBacklog` `backlog-tab-count` считать все активные: `backlogAll + inprog + review`

---

## T3: Система статусов

### Текущие статусы (найдены в коде)

#### A. KANBAN.json — implicit (через колонку)

| Колонка | Неявный статус |
|---|---|
| `ideas` | Idea / DROP |
| `features` | Future backlog (не взято) |
| `backlog` | Ready / Prioritized |
| `in_progress` | In Progress |
| `review` | Review |
| `done` | Done |

#### B. KANBAN.json — explicit поле `status` в items

Найдено только значение `"done"` на завершённых карточках (не на всех — часть имеет только `completed_at`). Других явных статусов (`blocked`, `rejected`, `archived`) нет.

#### C. Приоритеты в KANBAN.json (поле `priority`)

`P0`, `P1`, `P2`, `P3`, `scheduled`, `LOW`, `HIGH`

В `BK_PRIO_RANK` (JS, строка 4741) обработаны: `P0=0, HIGH=0, P1=1, P2=2, P3=3, LOW=4`.  
**Не обработан:** `scheduled` → падает в default rank 9 (MP-071 отображается в самом низу).

#### D. Статусы Decisions (decisions.json + JS строки 4593–4594)

| Значение поля `status` | JS-label | CSS класс |
|---|---|---|
| `needs_owner_decision` | "Ожидает решения" | `dec-status-needs` (красный) |
| `owner_decided` | "Решено" | `dec-status-decided` (зелёный) |
| `ai_review` | "AI Review" | `dec-status-review` (оранжевый) |
| `resolved` | "Закрыто" | `dec-status-resolved` (серый) |

В реальных данных `data/decisions.json` используются: `needs_owner_decision`, `resolved`.

#### E. CSS классы статусов (не-decision)

**Milestone статусы (tab-kanban, `.ms-dot` / `.ms-status`):**
- `done` — зелёный
- `active` — синий
- `blocked` — оранжевый

**Бейджи health/go-live:**
- `status-ok` / `status-err` — dashboard health
- `golive-ready` / `golive-notready` — go-live bar

**Агенты (`.ops-status`):**
- `active` / `waiting` / `offline`

---

### Целевые статусы (из технического задания v2.0)

```
Backlog | Ready | In Progress | Needs Owner Decision | AI Review | Blocked | Done | Rejected | Archived
```

---

### Mapping: текущий → целевой

#### Kanban items (column-based → explicit status)

```
Column "ideas"       → Backlog  (или Archived если DROP)
Column "features"    → Backlog  (future, не приоритизировано)
Column "backlog"     → Ready    (приоритизировано, готово к взятию)
Column "in_progress" → In Progress
Column "review"      → AI Review (или просто Review как sub-step)
Column "done"        → Done

explicit "status": "done"  → Done
(отсутствует)              → нужно добавить: Blocked, Rejected, Archived
```

#### Decisions статусы

```
needs_owner_decision → Needs Owner Decision  (label уже близко, код ок)
owner_decided        → (нет прямого аналога) → можно: "Decided" или оставить отдельно
ai_review            → AI Review             (совпадает)
resolved             → Done / Archived       (зависит от контекста)
```

#### Priority → не статус, но BK_PRIO_RANK требует фикса

```
"scheduled" priority → добавить в BK_PRIO_RANK как SCHEDULED: 5
```

---

### Что нужно изменить в коде

| # | Файл | Что изменить |
|---|---|---|
| 1 | `index.html` строки 875–877 | Переименовать tab label "📋 Tasks" → "📋 Milestones" или удалить `tab-kanban` |
| 2 | `index.html` `tab-kanban` (1027–1161) | Удалить статичный hardcoded контент или заменить на динамический milestone tracker |
| 3 | `index.html` строка 4741 | `BK_PRIO_RANK`: добавить `SCHEDULED: 5` |
| 4 | `index.html` строка 4840 | `backlog-tab-count` = `backlogAll + inprog + review` вместо только `backlogAll.length` |
| 5 | `index.html` строки 4593–4594 | `statusLabels`: добавить `blocked`, `rejected`, `archived` |
| 6 | `index.html` CSS строки 524–528 | Добавить `.dec-status-blocked`, `.dec-status-rejected`, `.dec-status-archived` |
| 7 | `index.html` строки 1009–1013 | Filter buttons: добавить `Blocked`, `Rejected`, `Archived` |
| 8 | `KANBAN.json` | Добавить `"status": "ready"` к items в колонке `backlog` (для явного статуса) |
| 9 | `KANBAN.json` | Добавить `"status": "blocked"` к items где `depends_on` не закрыты |

---

## Итог

**T2 (Backlog vs Kanban):**
- `tab-kanban` = **мёртвый** hardcoded HTML (v0.4.5 эра, не из KANBAN.json)
- `tab-backlog` = **живой** Kanban-борд (загружает KANBAN.json)
- Ярлыки навигации перепутаны: "Tasks" = статика, "Kanban" = динамика
- Минимум **4 задачи** в статичном борде дублируют `done` в KANBAN.json

**T3 (Статусы):**
- В KANBAN.json статусы **только implicit** (через имя колонки); explicit `status` поле проставлено только для `"done"` на части карточек
- Целевых статусов `Blocked`, `Rejected`, `Archived`, `Ready` — **нет нигде** в текущем коде
- В decisions системе: 4 статуса (needs_owner_decision, owner_decided, ai_review, resolved) — из них 2 совпадают с целевыми, 2 требуют переосмысления
- **Итого переименований/добавлений:** 5 новых статусов + 1 фикс `BK_PRIO_RANK` + удаление/рефакторинг `tab-kanban`
