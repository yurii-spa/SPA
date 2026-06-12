# Online Audit — GitHub Pages vs Local
**Дата:** 2026-06-12  
**Аудитор:** Claude (T1 audit task)

---

## Статус GitHub Pages

**URL:** https://yurii-spa.github.io/SPA/  
**HTTP статус:** 200 OK — страница рендерится.

**Критичная проблема: `index.html` онлайн устарел.**  
GitHub Pages отдаёт старую версию файла. Локальная версия прошла значительный рефакторинг (новые табы, английские лейблы, новый дефолтный таб) и в репозиторий **не запушена**.

---

## Табы онлайн (совпадение с локальной)

### Локальная версия — навигация (9 табов)

| # | ID таба | Кнопка | По умолчанию |
|---|---------|--------|:---:|
| 1 | `tab-overview` | 📊 Dashboard | ✅ active |
| 2 | `tab-dashboard` | 📑 Paper Test | |
| 3 | `tab-decisions` | ✍️ Decisions | |
| 4 | `tab-kanban` | 📋 Tasks | |
| 5 | `tab-backlog` | 🗂 Kanban | |
| 6 | `tab-analytics` | 📈 Statistics | |
| 7 | `tab-team` | 👾 Team | |
| 8 | `tab-golive` | 🎯 Go-Live | |
| 9 | `tab-system` | ⚙️ System | |

Скрытый таб (есть в HTML, но нет кнопки в nav): `tab-investor`.

### Онлайн версия — навигация (8 табов, старый HTML)

| # | Кнопка онлайн |
|---|---------------|
| 1 | 📋 Канбан |
| 2 | 🗂 BACKLOG |
| 3 | 📊 Paper Trading ? |
| 4 | 💼 INVESTOR |
| 5 | 📈 Аналітика |
| 6 | 👾 Команда |
| 7 | 🎯 Go-Live |
| 8 | ⚙️ System |

### Структурные расхождения

| Расхождение | Локально | Онлайн |
|-------------|----------|--------|
| Дефолтный таб | 📊 Dashboard (Overview) | Отсутствует в онлайн |
| Decisions таб | ✅ Есть | ❌ Нет |
| INVESTOR таб в nav | ❌ Скрыт | ✅ Виден |
| Язык лейблов | English | Русский / Украинский |
| Paper Trading | "📑 Paper Test" | "📊 Paper Trading ?" |
| Tasks | "📋 Tasks" | "📋 Канбан" |
| Kanban | "🗂 Kanban" | "🗂 BACKLOG" |
| Statistics | "📈 Statistics" | "📈 Аналітика" |
| Team | "👾 Team" | "👾 Команда" |

**Вывод:** онлайн-версия — это предыдущая итерация дашборда до рефакторинга. Локальный `index.html` не запушен в GitHub.

---

## Доступность data/*.json онлайн

| Файл | Статус онлайн | Дата онлайн | Локальная дата | Актуально? |
|------|:---:|-------------|----------------|:---:|
| `meta.json` | ✅ 200 | 2026-06-11T22:30 | — | ✅ Свежий |
| `trades.json` | ✅ 200 | 2026-06-11T22:30 | 2026-06-11 | ✅ Свежий |
| `paper_trading_status.json` | ✅ 200 | 2026-06-10T06:49 | 2026-06-11T06:00 | ⚠️ На 1 день отстаёт |
| `equity_curve_daily.json` | ✅ 200 | 2026-06-10T06:49 | 2026-06-11T06:00 | ⚠️ На 1 день отстаёт |
| `current_positions.json` | ✅ 200 | 2026-06-10T06:49 | 2026-06-11 | ⚠️ На 1 день отстаёт |
| `golive_status.json` | ✅ 200 | 2026-06-10T09:25 | — | ⚠️ На 2 дня отстаёт |
| `gap_monitor.json` | ✅ 200 | 2026-06-10T17:47 | — | ⚠️ На 2 дня отстаёт |
| `adapter_status.json` | ✅ 200 | 2026-05-31T02:19 | — | ❌ Устарел на 12 дней |
| `decisions.json` | ❌ 404/timeout | — | Есть локально | ❌ Не опубликован |
| `dashboard_metrics_history.json` | ❌ 404 | — | Есть локально | ❌ Не опубликован |
| `kanban_data.json` | ❌ 404 | — | Нет в data/ | ❌ Не существует |
| `risk_policy_blocks.json` | ❌ 404 | — | Есть локально | ❌ Не опубликован |
| `adapter_orchestrator_status.json` | ❌ timeout | — | Есть локально | ❌ Не опубликован |

### Детали онлайн-данных

**`paper_trading_status.json` онлайн (устарел на 1 цикл):**
- equity: $100,010.09 (локально уже $100,017.30)
- last_cycle_ts: 2026-06-10 (локально 2026-06-11)
- days_running: 22 (локально 23)

**`equity_curve_daily.json` онлайн (неполный):**
- Только 1 день данных: 2026-06-10 (локально уже 2 дня: 2026-06-10, 2026-06-11)
- Кривая капитала на дашборде будет неполной

**`adapter_status.json` онлайн (критически устарел):**
- generated_at: 2026-05-31 — 12 дней назад
- Все APY в режиме `mock`, write_state: `BLOCKED`
- Принадлежит execution-домену, не должен перезаписываться из read-only кода

**`golive_status.json` онлайн:**
- ready: false
- Блокер: `"trades.json: no real (is_demo:false) trades recorded yet"`
- Онлайн-версия не знает о новых трейдах от 2026-06-11

**`trades.json` онлайн (актуальный):**
- 2 трейда от 2026-06-11T22:30 — свежие
- PT-20260611223001: euler-v2-usdc-ethereum $20,000 @ 2.769%
- PT-20260611223001: morpho-usdc-ethereum $40,000 @ 3.589%
- Это реальные трейды (is_demo не указан, но структура правильная)

---

## Расхождения

### 1. КРИТИЧНО — `index.html` не запушен
Локальный дашборд значительно новее онлайн-версии:
- Добавлен таб Dashboard (Overview) как дефолтный — онлайн его нет
- Добавлен таб Decisions — онлайн его нет
- Переименованы все табы на английский — онлайн по-прежнему русский/украинский
- INVESTOR таб убран из навигации локально — онлайн виден

### 2. ВЫСОКИЙ — Данные на 1 цикл отстают
`auto_push.py` (90 мин) не запушил результаты цикла от 2026-06-11:
- `paper_trading_status.json` — онлайн 2026-06-10, локально 2026-06-11
- `equity_curve_daily.json` — онлайн 1 день, локально 2 дня
- `current_positions.json` — онлайн 2026-06-10, локально 2026-06-11
- `golive_status.json` — онлайн не знает о новых трейдах

При этом `trades.json` и `meta.json` **запушены** (показывают 2026-06-11T22:30), значит auto_push работает, но не включает все нужные файлы.

### 3. СРЕДНИЙ — Критические data-файлы отсутствуют онлайн
Файлы, которые дашборд запрашивает (`fetch(BASE + '/...')`), но онлайн не существуют:
- `decisions.json` — нужен для таба Decisions
- `dashboard_metrics_history.json` — нужен для Overview
- `risk_policy_blocks.json` — нужен для мониторинга
- `adapter_orchestrator_status.json` — основной источник данных для Paper Trading таба

### 4. НИЗКИЙ — `adapter_status.json` онлайн устарел на 12 дней
Данные от 2026-05-31, mock APY. Принадлежит execution-домену — должен обновляться им же.

---

## Что нужно сделать

1. **Запушить `index.html` в GitHub** — приоритет 1. Без этого онлайн-дашборд отображает старую версию без Dashboard/Decisions табов. Команда:
   ```bash
   python3 push_to_github.py --file /abs/path/index.html --message "feat: dashboard v2 — Overview tab, Decisions tab, English labels"
   ```

2. **Добавить в `auto_push.py` пропущенные файлы** — проверить, почему эти файлы не попадают в автопуш:
   - `paper_trading_status.json`
   - `equity_curve_daily.json`
   - `current_positions.json`
   - `golive_status.json`
   - `gap_monitor.json`
   - `decisions.json`
   - `dashboard_metrics_history.json`
   - `risk_policy_blocks.json`
   - `adapter_orchestrator_status.json`

3. **Ручной пуш накопленных данных** — после запуска цикла от 2026-06-12 запушить все data/*.json вручную, чтобы онлайн-версия была полностью актуальна.

4. **Разобраться с `adapter_status.json`** — файл устарел на 12 дней (2026-05-31). Обновление зависит от execution-домена, нужно убедиться что pipeline не сломан.

5. **`kanban_data.json` не существует** — дашборд нигде его не формирует, KANBAN.json берётся напрямую с GitHub raw. Это ожидаемое поведение, не баг.

---

*Сгенерировано: 2026-06-12. Источники: локальный index.html + fetch GitHub Pages + fetch data/*.json online.*
