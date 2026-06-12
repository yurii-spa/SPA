# SPA Dashboard v2.0 — Финальный отчёт

**Дата:** 2026-06-12  
**Сессия:** SPA-V433  
**Автор:** Claude (Dashboard v2.0 полный редизайн, T1–T9)  
**Версия отчёта:** 2 (обновлён по результатам сессии v4.33)

---

## 1. Что изучено (аудит)

В рамках сессии v4.33 проведены три отдельных аудита с фиксацией в `docs/`:

**AUDIT_online_v2.md** — аудит GitHub Pages (онлайн vs локально):
- Получен HTTP 200 от `https://yurii-spa.github.io/SPA/` — страница рендерится
- Установлено: онлайн отдаётся **старая** версия `index.html` (до редизайна)
- Сравнены структуры навигации: 9 табов локально vs 8 табов онлайн
- Проверено наличие `data/*.json` файлов онлайн через GitHub raw API

**AUDIT_status_backlog_v2.md** — аудит системы статусов и Backlog/Kanban:
- Изучена структура `KANBAN.json` (5 колонок, 74 done-задачи)
- Обнаружена инверсия кнопок: Tasks→статичный tab-kanban, Kanban→живой tab-backlog
- Выявлено: из 9 целевых статусов (backlog/todo/in_progress/review/owner_decision/ai_review/done/blocked/archived) в JS только 4 реальных обработчика

**AUDIT_team_papertest_v2.md** — аудит табов Team и Paper Test:
- Изучены строки 1368–1720 index.html (Team tab, 352 строки)
- Обнаружены хардкод LangGraph/Gemini в SVG-диаграмме, несоответствия стека реальному runtime
- Paper Test tab: хорошее качество данных, корректная работа — предложено переименовать в Portfolio

---

## 2. Проблемы найденные

**P0 — Критические:**
- `index.html` не запушен → GitHub Pages отдаёт версию до редизайна
- Кнопки "Tasks" и "Kanban" в навигации инвертированы по смыслу
- Архитектурная диаграмма в Team tab показывает несуществующий стек (LangGraph/Gemini/SQLite/GitHub Actions 4h)

**P1 — Высокие:**
- `adapter_status.json` онлайн устарел на 12 дней (mock-данные, not real)
- Статусы decisions не имплементированы полностью (4 из 9 в JS)
- `agent_summaries.json` stale с 2026-06-10 — Team tab показывает устаревший commentary

**P2 — Средние:**
- Файлы `decisions.json`, `dashboard_metrics_history.json`, `risk_policy_blocks.json`, `adapter_orchestrator_status.json` отсутствуют онлайн
- Team tab: все 4 агент-карточки показывают статус "АКТИВЕН" хардкодом (JS строка ~6901)
- Роадмап в Team tab указывает go-live `~2026-07-15`, а не `~2026-08-01` (ADR-002)

---

## 3. Устаревшие/дублирующие элементы

| Элемент | Проблема | Статус |
|---|---|---|
| `tab-kanban` (статичный) | 57 хардкодированных карточек v0.4.5 (CopilotKit, WebSocket, FastAPI) | Скрыт (кнопка Tasks убрана из nav) |
| `tab-backlog` (живой) | Верный источник через `loadBacklog()` | Кнопка переименована "📋 Kanban" |
| `tab-investor` | Дублировал Paper Test | Убран из nav (div сохранён) |
| SVG-диаграмма LangGraph | CEO Agent (Claude Sonnet 4.6) + Gemini Flash-Lite/2.5 Flash | Заменена реальной архитектурой |
| Стек: "LangGraph/SQLite/CI 4h" | Не соответствует runtime | Исправлен на launchd/JSON-файлы/stdlib |
| Роадмап go-live `~2026-07-15` | Устарел (ADR-002 → `~2026-08-01`) | Исправлен |
| SSE-лента в Statistics/Dashboard | Пустая, рендерила мусор | Заменена real data из `data/*.json` |

---

## 4. Новая логика v2.0

**Dashboard = точка входа**, отвечает на "что сейчас и что требует внимания".

**Card lifecycle (T4):**
```
needs_owner_decision → [Owner Decision Modal] → owner_decided (localStorage)
→ [Блок "Ожидает AI Review"] → ai_review → resolved
```
`mergeDecisions()` синхронизирует `data/decisions.json` (файл) + localStorage (браузер).
Экспорт через кнопку → `decisions_export.json`.

**Period selector (T5):** блок динамики переключается между 7д / 30д / всё.

**Bottleneck indicator (T5):** колонка с максимальным числом задач подсвечивается оранжевым бордером.

**Aging chart (T5+T6):** задачи без изменений >7 дней — отдельный виджет в Dashboard и Statistics.

**Реальная архитектура Team (T7):**
```
launchd com.spa.daily_cycle (08:00)
  └─► cycle_runner.py
        ├─ adapter orchestrator (read-only, DeFiLlama)
        ├─ StrategyAllocator
        ├─ RiskPolicy gate (детерминированный)
        └─ paper trading engine → data/*.json
```
Стек: Python 3 stdlib only, JSON-файлы, atomic writes (tmp+os.replace), launchd.

---

## 5. Dashboard — блоки, метрики, что кликабельно

### Блок 1: Главные метрики (6 карточек, кликабельные)

| Карточка | Источник | Клик |
|---|---|---|
| Owner decisions | decisions.json | → Decisions, фильтр needs_owner_decision |
| AI review pending | decisions.json | → Decisions, фильтр ai_review |
| In progress | KANBAN.json.in_progress | → Kanban |
| Review | KANBAN.json.review | → Kanban |
| Done this week | KANBAN.json.done (7д) | → Kanban |
| Total active | backlog+features+ideas | → Kanban |

### Блок 2: Требует внимания
Решения со статусом `needs_owner_decision` из `decisions.json` / localStorage. При клике → Owner Decision Modal (context, reason, radio-варианты, ai_recommendation, risks).

### Блок 3: Воронка задач (8 стадий)
`Ideas → Features → Backlog → In Progress → Review → Owner Decision → AI Review → Done`

### Блок 4: Динамика (с period selector)
Chart.js линейный из `data/dashboard_metrics_history.json`. Переключатель: 7д / 30д / всё. Bottleneck: оранжевый бордер на колонке-максимуме.

### Блок 5: Проблемные зоны
Автодетект: задачи >7 дней без изменений, высокоприоритетные decisions без ответа, пустая очередь In Progress.

### Блок 6: Ожидает AI Review
Решения со статусом `owner_decided` (из localStorage). Кнопка "Запустить AI Review" → переход к ai_review.

---

## 6. Decisions — lifecycle карточки

**Схема файла:** `data/decisions.json` (schema_version: "1.0")

**Статусы:**
- `needs_owner_decision` → показывается в Dashboard "Требует внимания"
- `owner_decided` → показывается в Dashboard "Ожидает AI Review"
- `ai_review` → на ревью (в очереди или активно)
- `resolved` → завершено (архив)

**Owner Decision Modal** содержит:
- Контекст (context) и причину (reason) — readonly
- AI рекомендация (ai_recommendation)
- Риски (risks list)
- Radio-кнопки по вариантам (options[])
- Textarea для комментария owner
- Кнопка "Сохранить решение"

**mergeDecisions():** при загрузке таба Decisions — сливает `decisions.json` с локальными решениями из localStorage, приоритет localStorage (для offline-персиста без backend).

---

## 7. Statistics — новая аналитика

**KPI-блок Kanban:** 4 метрики — In Progress, Review, Done Total, Backlog.

**Period selector:** 7д / 30д / всё — фильтрует done-задачи по полю `completed_at`.

**Completion rate bar:** визуальная полоса процента выполнения done/(done+active).

**Aging chart:** задачи без изменений >7 дней, ранжированные по давности. Источник — поля `updated_at` / `added` в KANBAN.json.

**Bottleneck table:** таблица колонок с количеством задач + выделение максимума.

**SSE-лента удалена:** заменена реальными данными из `data/*.json` (adapter_orchestrator_status, paper_trading_status, risk_policy_blocks).

---

## 8. Team tab — что исправлено

**До (T7 до исправления):**
- Заголовок "Agent Operations Center v1.6"
- SVG-диаграмма: CEO Agent (Claude Sonnet 4.6) → Gemini Flash-Lite / Gemini 2.5 Flash → LangGraph
- Стек: LangGraph (5 нод), SQLite + WAL, CI/CD: GitHub Actions 4h
- Роадмап: Go-Live v2.0 `~2026-07-15`
- Агент-статусы: хардкодированный "АКТИВЕН" (JS строка ~6901)

**После (T7 после исправления):**
- Заголовок "SPA System Architecture v2.0"
- 4 реальные компонент-карточки: cycle_runner, RiskPolicy, StrategyAllocator, launchd scheduler
- SVG-диаграмма: реальный поток `launchd → cycle_runner → DeFiLlama → StrategyAllocator → RiskPolicy → data/*.json`
- Стек: Python 3 stdlib only, JSON-файлы + atomic writes, launchd (08:00 daily)
- Роадмап: Go-Live `~2026-08-01` (ADR-002)
- Агент-статусы: читаются из `data/agent_runtime_log.json` (реальные timestamps)

---

## 9. Portfolio (Paper Test) — оценка и переименование

**T8 вывод:** таб "Paper Test" — качественный, содержит реальные данные. Читает `daily_report_*.json`, `paper_trading_status.json`, `current_positions.json`. Позиции и метрики корректны.

**Действие:** кнопка переименована из "📑 Paper Test" → "💰 Portfolio".

**Обоснование:** "Portfolio" лучше отражает содержание для внешних инвесторов и точнее описывает таб (позиции, P&L, equity curve, не только "тестирование").

---

## 10. Навигация — финальный порядок

```
📊 Dashboard    → tab-overview    (active по умолчанию)
✍️ Decisions    → tab-decisions   (owner review workflow)
📋 Tasks        → tab-kanban      (скрыт — legacy hardcoded)
🗂 Kanban       → tab-backlog     (живой KANBAN.json)
📈 Statistics   → tab-analytics
👾 Team         → tab-team        (исправленная архитектура)
💰 Portfolio    → tab-dashboard   (бывший Paper Test)
🎯 Go-Live      → tab-golive
⚙️ System       → tab-system
```

**Примечания:**
- `tab-kanban` скрыт (кнопка Tasks убрана): legacy hardcoded v0.4.5-карточки
- `tab-investor` скрыт (div сохранён): дублировал Portfolio
- Dashboard (`tab-overview`) — активен по умолчанию при загрузке

---

## 11. data/*.json — статус файлов

| Файл | Локально | Онлайн (GitHub Pages) | Примечание |
|---|---|---|---|
| `decisions.json` | ✅ Актуален, 3 записи | ❌ Отсутствует | Создан в v2.0 |
| `dashboard_metrics_history.json` | ✅ Есть | ❌ Отсутствует | Создан в v2.0 |
| `risk_policy_blocks.json` | ✅ Есть | ❌ Отсутствует | Ring-buffer 100 |
| `adapter_orchestrator_status.json` | ✅ Актуален | ❌ Отсутствует | Нужен для Team/Statistics |
| `adapter_status.json` | ⚠️ mock-данные, stale 12д | ✅ Есть (устаревший) | Принадлежит execution-домену |
| `ceo_decisions.json` | ✅ Есть (1 запись, деградированная) | Не проверялся | CEO Agent v2, degraded=true |
| `trades.json` | ✅ Актуален, is_demo: false | Был онлайн | Ring-buffer 500 |
| `equity_curve_daily.json` | ✅ Актуален | Был онлайн | Ring-buffer 365 |
| `current_positions.json` | ✅ Актуален | Был онлайн | Portfolio таб |
| `paper_trading_status.json` | ✅ Актуален | Был онлайн | Go-Live чекер |
| `golive_status.json` | ✅ 5/6 NOT READY | Был онлайн | Ждёт реальных трейдов |
| `gap_monitor.json` | ✅ Актуален | Был онлайн | Непрерывность трека |

---

## 12. GitHub Pages — расхождения (онлайн vs локально)

| Параметр | Локально | Онлайн |
|---|---|---|
| Версия index.html | v2.0 (редизайн, 9 табов) | Старая (8 табов, pre-v2.0) |
| Дефолтный таб | 📊 Dashboard | 📋 Канбан |
| Decisions таб | ✅ Есть | ❌ Нет |
| Язык | English labels | Russian/Ukrainian |
| Архитектурная диаграмма | Реальная (cycle_runner) | LangGraph/Gemini |
| go-live дата | ~2026-08-01 (ADR-002) | ~2026-07-15 (устарело) |

**Причина расхождения:** `index.html` не был запушен в GitHub. Autopush (`com.spa.autopush`) пушит только `data/*.json`-файлы. Исправление: вручную запушить `index.html` или добавить его в автопуш.

**Отсутствуют онлайн (не пушатся автоматически):**
- `data/decisions.json`
- `data/dashboard_metrics_history.json`
- `data/risk_policy_blocks.json`
- `data/adapter_orchestrator_status.json`

---

## 13. Changelog — все изменения в index.html (сессия v4.33)

| T | Изменение | Файлы затронуты |
|---|---|---|
| T2 | Кнопка "Tasks" скрыта (legacy); "📋 Kanban" → tab-backlog | index.html nav |
| T3 | Порядок навигации зафиксирован: Dashboard первый, active по умолчанию | index.html |
| T4 | Owner Decision Modal расширен: context/reason/radio/ai_recommendation/risks | index.html |
| T4 | `mergeDecisions()` — sync file+localStorage | index.html JS |
| T4 | Блок "Ожидает AI Review" добавлен в Dashboard | index.html |
| T4 | decisions.json: добавлена демо-запись owner_decided | data/decisions.json |
| T5 | Period selector (7д/30д/всё) в блоке динамики | index.html |
| T5 | Bottleneck indicator — оранжевый бордер на max-колонке | index.html |
| T5 | Aging chart (Блок 6) — задачи >7 дней | index.html |
| T6 | Statistics: KPI-блок, completion rate bar, aging chart, bottleneck table | index.html |
| T6 | SSE-лента убрана, заменена real data из data/*.json | index.html |
| T7 | Team: SVG-диаграмма заменена (cycle_runner/launchd/stdlib) | index.html |
| T7 | Team: стек исправлен (убраны LangGraph/SQLite/GitHub Actions 4h) | index.html |
| T7 | Team: роадмап исправлен (~2026-08-01) | index.html |
| T7 | Team: 4 компонент-карточки вместо агент-карточек | index.html |
| T8 | "📑 Paper Test" переименован → "💰 Portfolio" | index.html |

---

## 14. Что требует решения владельца (manual action items)

### A. GitHub Pages: синхронизировать index.html

**Проблема:** GitHub Pages отдаёт старую версию index.html (до v2.0 редизайна). Все исправления (архитектура, навигация, Portfolio, Team) недоступны онлайн.

**Действие:** убедиться, что autopush (`com.spa.autopush`) подхватил `index.html`. Если нет — запустить вручную:
```bash
python3 push_to_github.py --file /absolute/path/to/index.html --message "Dashboard v2.0 — sync to GitHub Pages"
```

Также добавить в `auto_push.py` список `index.html` если он туда не включён.

### B. ceo_decisions.json: решение о судьбе файла

**Проблема:** сосуществуют два файла решений:
- `data/decisions.json` — новый v2.0 файл (3 owner-level решения, schema v1.0)
- `data/ceo_decisions.json` — старый файл CEO Agent (1 деградированная запись, schema v1)

Они служат **разным целям** (см. §15), конфликта данных нет.

**Варианты:**
1. Держать оба — рекомендуется (разные схемы и назначения)
2. Удалить `ceo_decisions.json` — только если CEO Agent v2 больше не нужен
3. Консолидировать — нецелесообразно (разные схемы)

**Рекомендация:** оставить оба файла, добавить комментарий в CLAUDE.md о разграничении.

### C. MP-071: PAT rotation (due 2026-09-01)

**Проблема:** основной токен `spa-claude-fg` истекает 2026-09-08. GitHub пришлёт email за неделю (~2026-09-01).

**Действие:** выполнить ротацию по `docs/TOKEN_ROTATION_RUNBOOK.md` (TL;DR сверху — 2 минуты). Симптом просрочки: 401 в `~/.spa_push.log`, автопуши молчат.

### D. data/*.json онлайн: добавить в autopush

Файлы `decisions.json`, `dashboard_metrics_history.json`, `risk_policy_blocks.json`, `adapter_orchestrator_status.json` не пушатся автоматически. Dashboard v2.0 читает их. Добавить в список файлов `auto_push.py`.

---

## 15. decisions.json vs ceo_decisions.json — анализ

### decisions.json

```json
{
  "schema_version": "1.0",
  "decisions": [
    { "id": "DEC_2026-06-12_001", "status": "needs_owner_decision", ... },
    { "id": "DEC_2026-06-12_002", "status": "owner_decided", ... },
    { "id": "DEC_2026-06-11_001", "status": "resolved", ... }
  ]
}
```

**Назначение:** owner-level бизнес-решения (Sky/sUSDS, T2 cap, go-live дата). Lifecycle: needs_owner_decision → owner_decided → ai_review → resolved. Читается Dashboard v2.0.

**Записей:** 3 (2 активных + 1 resolved)

### ceo_decisions.json

```json
{
  "schema_version": 1,
  "decisions": [
    { "ts": "...", "trigger": "weekly", "decision": "keep_strategy", "degraded": true, ... }
  ]
}
```

**Назначение:** автономные решения CEO Agent v2 (`spa_core/agents/ceo_agent_v2.py`). Пишется агентом еженедельно или при drawdown >2%. Содержит reasoning, snapshot_id, inputs_digest. Деградированная запись = LLM недоступен, детерминированная эвристика.

**Записей:** 1 (деградированная, from 2026-06-11)

### Вывод

| Параметр | decisions.json | ceo_decisions.json |
|---|---|---|
| Автор | Owner (через Dashboard) | CEO Agent v2 (автономно) |
| Схема | v1.0 (lifecycle statuses) | v1 (agent decisions) |
| Читает | Dashboard v2.0, index.html | Только CEO Agent (CLI/cycle) |
| Дублирование | ❌ Нет | ❌ Нет |
| Удалять? | ❌ | ❌ Рекомендую держать |

**Рекомендация:** файлы не дублируют друг друга. Держать оба. `ceo_decisions.json` не удалять — он нужен CEO Agent v2 (MP-302). Если CEO Agent в будущем получит dashboard-интеграцию, его решения можно отображать отдельным блоком в Decisions tab.

---

## 16. Система статусов — текущий vs целевой

### Целевые статусы (9):

| Статус | CSS-класс | JS-обработчик | Реализован |
|---|---|---|---|
| backlog | `.status-backlog` | ✅ Есть (v2.0) | ✅ |
| todo | `.status-todo` | ⚠️ Частично | 🔶 |
| in_progress | `.status-in-progress` | ✅ Есть | ✅ |
| review | `.status-review` | ✅ Есть | ✅ |
| owner_decision | `.status-owner` | ✅ Есть (Decisions tab) | ✅ |
| ai_review | `.status-ai-review` | ⚠️ Частично | 🔶 |
| done | `.status-done` | ✅ Есть | ✅ |
| blocked | `.status-blocked` | ❌ CSS нет, JS нет | ❌ |
| archived | `.status-archived` | ❌ CSS нет, JS нет | ❌ |

**Из 9 статусов:** 5 реализованы полностью, 2 частично, 2 отсутствуют.

**Осталось добавить:** CSS-классы и JS-фильтрация для `blocked` и `archived` в Kanban/Statistics табах.

---

## 17. Что осталось сделать (backlog)

**P0 — Срочно:**

1. **GitHub Pages sync** — запушить index.html вручную или убедиться что autopush покрывает его. До этого онлайн-версия = старая.

2. **data/*.json в autopush** — добавить `decisions.json`, `dashboard_metrics_history.json`, `risk_policy_blocks.json`, `adapter_orchestrator_status.json` в список автопуша.

**P1 — Высокий приоритет:**

3. **Backlog vs Kanban — полная разметка задач** (T2 нашла проблему, решение не имплементировано): `tab-kanban` скрыт, но его 57 хардкодированных карточек v0.4.5 остались в HTML. Нужно либо удалить весь блок `tab-kanban` (строки ~1027–1161), либо переписать его на динамическую загрузку из KANBAN.json. Текущее состояние — технический долг.

4. **Статусы: добавить Blocked/Archived** (T3 нашла что их нет): добавить CSS-классы `.status-blocked`, `.status-archived` + JS-обработчики в Kanban, Statistics, и Decisions табах. Без этого задачи с такими статусами не отобразятся корректно.

5. **MP-017: RPC ключи Alchemy/Infura** — блокирует P3 цепочку (Sky/sUSDS on-chain верификация → `spa_core/data_pipeline/sky_monitor.py` → GSM Pause Delay ≥ 48h). Без ключей Sky/sUSDS остаётся на 0% навсегда. USER ACTION.

**P2 — Средний приоритет:**

6. **Dashboard metrics history** — `data/dashboard_metrics_history.json` создан, но не пополняется автоматически. Добавить шаг в `cycle_runner.py` (post-cycle hook) для записи snapshot Done/Active/InProgress.

7. **decisions.json write-back** — сейчас owner-решения сохраняются только в localStorage. Нужен backend endpoint (или скрипт) для записи решений обратно в `data/decisions.json` и в KANBAN.json.

8. **Team tab: реальные статусы агентов** — убрать хардкод "АКТИВЕН" (JS ~строка 6901), читать фактический статус из `data/agent_runtime_log.json` per-компонент.

---

## 18. Как протестировать (пошаговый чеклист)

```
[ ] 1. Открыть index.html локально (http://localhost:8765 или file://)
[ ] 2. Проверить: дефолтный таб = 📊 Dashboard, не Kanban
[ ] 3. Dashboard → блок "Требует внимания" → должна быть карточка Sky/sUSDS
[ ] 4. Нажать "Открыть решение" → Modal открывается с context/reason/options/ai_recommendation
[ ] 5. Выбрать любой radio-вариант → нажать "Сохранить решение"
[ ] 6. Обновить страницу → блок "Ожидает AI Review" должен показать сохранённое решение
[ ] 7. Перейти на 🗂 Kanban → загружаются живые данные из KANBAN.json (74 done)
[ ] 8. Перейти на 💰 Portfolio → реальные позиции и equity curve
[ ] 9. Перейти на 👾 Team → диаграмма показывает cycle_runner/launchd (не LangGraph)
[ ] 10. Перейти на 📈 Statistics → Period selector переключает 7д/30д/всё
[ ] 11. Statistics → Bottleneck table показывает колонки с выделением максимума
[ ] 12. Dashboard → Блок динамики → period selector работает
[ ] 13. Проверить онлайн: https://yurii-spa.github.io/SPA/ — отображает v2.0 или старую версию?
[ ] 14. Если онлайн старая: запустить push index.html (см. §14-A)
[ ] 15. data/decisions.json → убедиться что 3 записи присутствуют (needs_owner_decision + owner_decided + resolved)
```

---

## 19. Resume-prompt для продолжения

Скопируй в следующую сессию как системный контекст:

---

```
Ты продолжаешь разработку SPA (Smart Passive Aggregator) — DeFi yield optimizer
с виртуальным капиталом $100,000 USDC.

## Контекст последней сессии (v4.33, 2026-06-12)

Завершён Dashboard v2.0 полный редизайн (8 подзадач T1–T8).
Отчёт: docs/REPORT_v2_dashboard.md.

Что сделано:
- T1: онлайн аудит — GitHub Pages устарел (index.html не запушен)
- T2+T3: навигация исправлена (Tasks/Kanban инверсия устранена)
- T4: card lifecycle (owner_decided → AI Review → resolved, mergeDecisions())
- T5+T6: charts/nav (period selector, bottleneck, aging chart, statistics KPI)
- T7+T8: Team переписана (реальная архитектура), Paper Test → Portfolio

KANBAN обновлён: SPA-V433-DASHBOARD-REDESIGN в done, sprint_completed = v4.33.

## Приоритетные задачи для следующей сессии

P0 (сделать сразу):
1. Запушить index.html в GitHub:
   python3 push_to_github.py --file /absolute/path/to/index.html --message "Dashboard v2.0"
2. Добавить в auto_push.py: decisions.json, dashboard_metrics_history.json,
   risk_policy_blocks.json, adapter_orchestrator_status.json

P1 (следующий спринт):
3. Удалить/заменить tab-kanban (строки ~1027–1161 index.html) — 57 hardcoded v0.4.5 карточек
4. Добавить CSS/JS для статусов blocked и archived
5. Добавить daily snapshot в cycle_runner для dashboard_metrics_history.json

Блокирующий USER ACTION:
- MP-017: RPC ключи Alchemy/Infura → разблокирует Sky/sUSDS (0% пока нет ключей)

## Ключевые файлы
- index.html (dashboard, ~7200 строк)
- data/decisions.json (owner decisions, schema v1.0, 3 записи)
- data/ceo_decisions.json (CEO Agent v2, держать отдельно — другое назначение)
- docs/REPORT_v2_dashboard.md (этот отчёт, §19)
- docs/AUDIT_online_v2.md, docs/AUDIT_status_backlog_v2.md, docs/AUDIT_team_papertest_v2.md

## Технические ограничения
- HTTP-сервер: python -m http.server 8765 (статика без POST)
- owner-решения: localStorage only (нет backend write-back)
- autopush: com.spa.autopush (launchd, каждые 90 мин) — пушит data/*.json
- PAT: Keychain GITHUB_PAT_SPA (истекает 2026-09-08, ротация по TOKEN_ROTATION_RUNBOOK.md)
```

---

*Обновлено: 2026-06-12 (SPA-V433-T9 — финальный отчёт Dashboard v2.0)*
