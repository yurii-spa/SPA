# Audit v2 Dashboard — SPA Dashboard Restructuring

**Дата аудита:** 2026-06-12  
**Аудитор:** Claude (SPA-V2.0-DASHBOARD)

---

## 1. Текущая структура (до v2.0)

### Вкладки (слева направо)

| # | Кнопка | ID div | Статус по умолчанию | Содержимое |
|---|--------|--------|---------------------|------------|
| 1 | 📋 Канбан | `tab-kanban` | **ACTIVE (default)** | Hardcoded milestone roadmap + hardcoded kanban cards (фаза 0/1) |
| 2 | 🗂 BACKLOG | `tab-backlog` | hidden | Динамическая загрузка KANBAN.json из raw.githubusercontent.com — все колонки (ideas, features, backlog, in_progress, review, done) |
| 3 | 📊 Paper Trading | `tab-dashboard` | hidden | Paper trading метрики, equity curve, позиции, APY, алерты, стратегия race |
| 4 | 💼 INVESTOR | `tab-investor` | hidden | Investor Summary из data/daily_report_{date}.json |
| 5 | 📈 Аналітика | `tab-analytics` | hidden | Protocol analytics, APY/TVL scatter, rolling Sharpe, APY history |
| 6 | 👾 Команда | `tab-team` | hidden | Agent Operations Center, Pixel Office анимация, агент-карточки |
| 7 | 🎯 Go-Live | `tab-golive` | hidden | Readiness Checklist, donut chart, timeline, PDFReport |
| 8 | ⚙️ System | `tab-system` | hidden | System Health Monitor, pipeline статусы, freshness |

### JavaScript загрузка данных

- `BASE`: `./data` (при localhost:8765) → `/SPA/data` (GitHub Pages) → `http://localhost:8000` (dev)
- KANBAN.json: `https://raw.githubusercontent.com/yurii-spa/SPA/main/KANBAN.json` (через GitHub raw, не через httpserver)
- HTTP сервер: `python -m http.server 8765` — чистый статик, **POST недоступен**

### Состояние KANBAN.json (на 2026-06-12)

| Колонка | Элементов |
|---------|-----------|
| ideas | 3 |
| features | 10 |
| backlog | 4 |
| in_progress | 0 |
| review | 0 |
| done | 71 |

---

## 2. Найденные проблемы

### P0 — Критические

1. **Нет Dashboard-обзора** — дефолтная вкладка (Канбан) показывает hardcoded статику без живых данных и не отвечает на вопрос "что сейчас происходит и что требует внимания".

2. **Нет Owner Decision workflow** — существует `data/ceo_decisions.json` с решениями (статус `keep_strategy`, `degraded=true`), но нет UI для просмотра и принятия решений владельцем.

3. **Стартовый таб неверный** — при открытии index.html активен статичный Канбан, а не обзор системы. Пользователь не видит актуального состояния без дополнительных кликов.

### P1 — Высокий приоритет

4. **Дублирование Канбан/BACKLOG** — вкладка Канбан содержит hardcoded (устаревшие?) карточки фазы 0/1, а вкладка BACKLOG динамически загружает те же задачи из KANBAN.json. Это два несинхронизированных источника истины для одного контента.

5. **INVESTOR таб = Paper Trading lite** — вкладка INVESTOR показывает `data/daily_report_{date}.json`, что является упрощённой версией Paper Trading. Дублирует основной Paper Trading таб.

6. **Именование путает** — вкладка с кодом `tab-dashboard` называется "Paper Trading", а "Dashboard" в проекте не существует как концепция навигации. Создаёт когнитивную путаницу.

### P2 — Средний приоритет

7. **Нет воронки задач** — невозможно увидеть где скапливаются задачи (bottleneck) без ручного подсчёта по вкладкам.

8. **Нет индикатора срочности** — нет способа быстро понять сколько задач требуют решения прямо сейчас.

9. **Static Канбан устаревает** — hardcoded карточки в `tab-kanban` требуют ручного обновления при каждом спринте, расходятся с KANBAN.json.

10. **Go-Live дата устарела** — в `tab-golive` захардкожена дата `2026-07-15`, тогда как по ADR-002 перенос на `~2026-08-01`. Должна читаться из KANBAN.json.

### P3 — Низкий приоритет

11. **tabIds массив неполный** — `const tabIds = ['kanban','backlog','dashboard','analytics','team','golive','system']` — не включает investor. Keyboard shortcut (?) не доберётся до него.

12. **Нет исторических метрик dashboard** — нет `data/dashboard_metrics_history.json` для трендов.

---

## 3. Устаревший/дублирующий контент

| Элемент | Проблема | Решение |
|---------|----------|---------|
| Вкладка INVESTOR | Дублирует Paper Test (данные из daily_report_*.json) | Убрать из навигации. Содержимое div сохранить в HTML, но не показывать в nav |
| Hardcoded канбан-карточки в `tab-kanban` | Дублирует KANBAN.json; устаревает автоматически | Сохранить как "Tasks/Roadmap" — это статическая дорожная карта, не живой канбан |
| Дата `2026-07-15` в `tab-golive` | Не совпадает с ADR-002 (~2026-08-01) | Читать из KANBAN.json.golive_decision_date |

---

## 4. Что работает хорошо (сохранить)

- Визуальный стиль (#f5f4f0 фон, синяя #185FA5 акцентная, шрифты)
- Paper Trading метрики — полные, актуальные данные из paper_trading_status.json
- Analytics вкладка — качественные чарты APY/TVL, rolling Sharpe
- Team вкладка — pixel office + agent cards оригинальны и информативны
- Go-Live checklist — чёткий, данные из golive_status.json
- System Health — исчерпывающий мониторинг

---

## 5. Решение по дублям

| Вкладка | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| 📋 Канбан | hardcoded roadmap | 📋 Tasks — сохранить content | Это дорожная карта фаз — valuable, но переименовать |
| 🗂 BACKLOG | dynamic KANBAN.json | 🗂 Kanban — сохранить content | Переименовать: это и есть живой Kanban |
| 💼 INVESTOR | investor view | Скрыть из навигации | Содержимое = subset Paper Test |
| (отсутствует) | — | 📊 Dashboard | НОВЫЙ первый таб |
| (отсутствует) | — | ✍️ Decisions | НОВЫЙ второй таб |

---

## 6. Итоговая новая структура

| # | Новое имя | ID | Источник данных |
|---|-----------|-----|-----------------|
| 1 | 📊 Dashboard | `tab-overview` (NEW) | KANBAN.json + decisions.json |
| 2 | ✍️ Decisions | `tab-decisions` (NEW) | data/decisions.json + localStorage |
| 3 | 📋 Tasks | `tab-kanban` (renamed) | hardcoded roadmap — сохранить |
| 4 | 🗂 Kanban | `tab-backlog` (renamed) | KANBAN.json via GitHub raw |
| 5 | 📈 Statistics | `tab-analytics` (renamed) | protocol analytics JSON |
| 6 | 👾 Team | `tab-team` (same) | agent_summaries.json |
| 7 | 📑 Paper Test | `tab-dashboard` (renamed) | paper_trading_status.json |
| 8 | 🎯 Go-Live | `tab-golive` (same) | golive_status.json |
| 9 | ⚙️ System | `tab-system` (same) | system health JSONs |

*Investor tab (`tab-investor`) div остаётся в HTML но исключается из навигации.*

---

*Сохранено: 2026-06-12 · ФАЗА 1 АУДИТ ЗАВЕРШЁН*
