# SPA — Правила совместной работы с AI агентами

> Этот файл — живой документ. Каждое важное решение, изменение рабочего процесса или правило фиксируется здесь. Читается агентами в каждой сессии.

---

## 🚀 ОБЯЗАТЕЛЬНЫЙ STARTUP PROTOCOL

Выполнять в НАЧАЛЕ каждой сессии, перед выбором задачи:

1. **CURRENT_STATE.md** → прочитать: статус launchd, push_method, sprint_last, blockers
2. **RULES.md** → напомнить себе правила (если давно не читал)
3. **Push fix если нужен** → если CURRENT_STATE говорит autopush_status=not_installed:
   ```bash
   bash ~/Documents/SPA_Claude/mp009_fix_launchd.command
   ```
4. **KANBAN.json** → sprint_current, что в backlog с P0-P1, что blocked
5. **docs/DECISIONS.md** → последние 3-5 записей: что было сделано, какие блокеры

Только после этих 5 шагов → брать задачу из backlog.

---

## ✅ ОБЯЗАТЕЛЬНЫЙ ЧЕКЛИСТ ЗАКРЫТИЯ СПРИНТА (DoD)

Спринт считается done ТОЛЬКО если выполнены ВСЕ 3 пункта:

1. **KANBAN.json** → карточка: status=done, sprint_completed=vX.YZ, completed=YYYY-MM-DD (атомарно)
2. **SPA_sprint_log.md** → новая запись: что сделано, тесты, почему эта задача, что дальше
3. **CURRENT_STATE.md** → обновить: sprint_last=vX.YZ, infrastructure_status если изменился

Пропустить пункт 2 или 3 = sprint "shipped_local" но не done.
Без этого история теряется — DD-аудиторы увидят дыры в sprint log.

---

## ⚡ ПРИОРИТИЗАЦИЯ: INFRASTRUCTURE FIRST

Порядок выбора задач:

1. **P0 infrastructure** — ВСЕГДА первые (autopush fix, алерты, пуш)
2. **P0 process** — CURRENT_STATE.md, RULES.md sync, sprint DoD
3. **P1 infrastructure / monitoring** — алерты, daily report, kill-switch
4. **P1 analytics** — только если нет P0/P1 infra в backlog
5. **P2+ analytics** — только если нет P1 infra в backlog

**Исключение:** если P0/P1 infra заблокированы USER ACTION — тогда переходи к следующему приоритету и явно пиши в sprint log почему.

**Запрещено:** брать analytics P2+ при наличии infra P1 не-blocked задач.

---

## 🚨 ANTI-HALT ПРОТОКОЛ

Если блокер повторяется 3-й раз без прогресса:

1. **НЕ писать тот же текст 4-й раз** — это шум, не коммуникация
2. Создать задачу **[ESCAPE-XXX]** в KANBAN с конкретным планом выхода:
   - Альтернативный метод
   - Что нужно от пользователя (конкретное действие, не описание)
   - Крайний срок (если применимо)
3. Продолжить работу с незаблокированными задачами
4. Добавить в DECISIONS.md: "Блокер X повторился 3 раза, создан ESCAPE-XXX"

**Запрещено:** 26 циклов с одинаковым текстом (инцидент 2026-05-31 — 2026-06-09).

---

## 📦 DELIVERY STATUS В KANBAN

Каждая done-карточка должна иметь поле delivery_status:

- **shipped_local** — написан и протестирован, не запушен в GitHub
- **shipped_remote** — в GitHub repo, не в production
- **in_prod** — работает в daily_cycle или автономно на машине

**Настоящий done = in_prod** (или shipped_remote для аналитических модулей read-only).
shipped_local = промежуточный статус, не финальный.

В sprint log всегда указывать delivery_status в конце записи.

---

## 🔴 АБСОЛЮТНЫЕ ЗАПРЕТЫ (нарушение = стоп)

1. **Никогда не просить пользователя пушить вручную.** Autopush (com.spa.autopush) работает каждые 90 минут. Агент сам диагностирует проблемы с пушем.
2. **Никогда не встраивать PAT/токены в файлы.** Инцидент 2026-06-10 — PAT утёк в 90+ файлов.
3. **Никогда не создавать push_*.html с кредами.**
4. **LLM запрещён в risk/execution/monitoring коде** — только stdlib Python.
5. **Только атомарные записи** — tmp + os.replace, никогда прямой open(..., "w").
6. **Не импортировать** execution/risk код из paper_trading/analytics модулей.

---

## 🟡 РАБОЧИЙ ПРОЦЕСС

### Пуш в GitHub
- Autopush: `com.spa.autopush` каждые 90 минут забирает всё из `~/Documents/SPA_Claude`
- **Статус (2026-06-23):** autopush УСТАНОВЛЕН и работает (`autopush_installed` PASS в golive_checker; heartbeat — `logs/auto_push.log`)
- **Если на новом хосте не установлен:** `bash ~/Documents/SPA_Claude/mp009_fix_launchd.command`
- Агенты никогда не упоминают пуш в отчётах — он происходит автоматически

### Спринты
- Каждый спринт = один MP-xxx тикет из KANBAN.json
- Отчёт по завершении: что сделано, сколько тестов, KANBAN обновлён
- Агент сам выбирает следующую задачу без одобрения пользователя (режим "я сплю")
- Стоп только при USER ACTION блокере или реальном техническом препятствии

### Язык
- **Всегда русский** в сообщениях пользователю
- Код, комментарии, коммит-сообщения — английский

### Модели
- Архитектура/дизайн/ADR: `fable` (Claude 5.0)
- Код/тесты/инфра: `opus` (Claude 4.8)
- Быстрые задачи: `sonnet`

---

## 🟢 ИНФРАСТРУКТУРА (что и где)

> Актуальный полный список агентов: `CURRENT_STATE.md § Мониторинг — LaunchAgents & Health`
> Источник истины в рантайме: `data/agent_health.json` (60 мин), `data/cycle_health.json` (5 мин)

| Сервис | Расписание | Лог |
|--------|-----------|-----|
| com.spa.daily_cycle | 08:00 ежедн. | logs/launchd_stdout.log |
| com.spa.autopush | каждые 90 мин | /tmp/spa_autopush.log |
| com.spa.httpserver | always-on | — |
| com.spa.cloudflared | always-on | — |
| com.spa.agent_health | каждые 60 мин | /tmp/spa_agent_health.log |
| com.spa.cycle_health | каждые 5 мин | /tmp/spa_cycle_health.log |
| **Итого агентов** | **~42** (источник истины: `launchctl list \| grep spa` / `data/agent_health.json`) | data/agent_health.json |

**PAT в Keychain:** `security find-generic-password -s GITHUB_PAT_SPA -w`
**Ротация PAT:** `bash setup_pat.sh`

---

## 📋 ИСТОРИЯ КЛЮЧЕВЫХ РЕШЕНИЙ

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-10 | Перезапуск трека с нуля | Все данные до этой даты — демо/недействительны |
| 2026-06-10 | PAT инцидент — токен утёк в файлы | Запрет встраивания токенов |
| 2026-06-11 | Два проекта: SPA_Claude (prod) + SPA_Dev (dev) | Разделение production и AI-команды |
| 2026-06-11 | ADR-020 — автономная команда агентов | Агенты общаются через team_chat.json каждые 4ч |
| 2026-06-12 | Go-live перенесён на ~2026-08-01 | ADR-002 — нужно 30 честных дней трека |
| 2026-06-12 | Backlog пополнен MP-126..135 | 10 новых аналитических модулей |

---

## 🤖 КОМАНДА АГЕНТОВ (SPA_Dev)

**Файлы:** `~/Documents/SPA_Dev/agents/*.md`
**KANBAN Dev:** `~/Documents/SPA_Dev/sprints/KANBAN_DEV.json`
**Переписка:** `~/Documents/SPA_Dev/spa_agents/state/team_chat.json`
**Запуск:** launchd `com.spa.agent-team` каждые 4 часа

| Агент | Модель | Роль |
|-------|--------|------|
| orchestrator | sonnet | Координация, стендапы |
| architect | fable | Архитектурные решения, ADR |
| product_manager | fable | Роадмап, спринты, приоритеты |
| business_analyst | fable | Unit economics, investor narrative |
| backend_developer | opus | Python, тесты, адаптеры |
| frontend_developer | opus | index.html, dashboard |
| qa_engineer | opus | Тесты, регрессия |
| devops | opus | launchd, CI, инфра |
| security_reviewer | fable | Аудит, ADR безопасности |
| data_engineer | opus | Data pipeline, JSON схемы |
| technical_writer | sonnet | Документация |
| ui_ux_designer | fable | UX, дизайн-решения |

**Activation Matrix:**
- `drawdown_alert` → architect + product_manager
- `apy_below_benchmark` → product_manager
- `morning_standup` → orchestrator
- `weekly_retro` → orchestrator + product_manager
- `adapter_offline` → backend_developer

---

## 📊 СОСТОЯНИЕ ПРОЕКТА

> ⚠️ Живые цифры — `docs/SYSTEM_BRIEFING.md` + `KANBAN.json` (sprint/done) + `data/golive_status.json`.
> Значения ниже — снимок, может устаревать; не доверяй им для оперативных решений.

- **Спринт:** см. `KANBAN.json` (на 2026-06-24 — v12.82, Done **1358**)
- **Track start:** 2026-06-10 (~15/30 честных дней)
- **GoLive:** 27/29 — NOT READY (2 time-gated блокера)
- **Go-live target:** ~2026-07-09 (30 честных дней трека)

---

## 🔵 ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА

RULE-7: Ни один plist не считается установленным, пока:
  a) launchctl list <label> показывает загрузку, И
  b) err-лог агента пуст после первого прогона.
  Проверка: bash scripts/agent_status.sh

RULE-8: Kill-switch на основе Sharpe требует минимум MIN_DAYS_FOR_SHARPE (30) дней данных.
  При меньшем количестве — Sharpe игнорируется (insufficient data = no signal).
  Причина: Sharpe на малой выборке (~5 дней) даёт ложные срабатывания (Sharpe -61).

---

## 🔍 ПРАВИЛА МОНИТОРИНГА

### ПРАВИЛО MON-001: Обязательные агенты

Следующие LaunchAgents ДОЛЖНЫ быть загружены всегда (verified 2026-06-22):

**Always-on (должны иметь активный PID):**
- `com.spa.httpserver` — port 8765, family fund portal
- `com.spa.cloudflared` — туннель earn-defi.com
- `com.spa.dashboard` — dashboard backend
- `com.spa.familyfund` — family fund HTTP API
- `com.spa.bot_commands` — Telegram bot
- `com.spa.apiserver` — REST API (exit=-15 при рестарте — ожидаемо)

**Критические периодические (должны быть loaded, exit=0):**
- `com.spa.daily_cycle` — 08:00 ежедн. (CORE: equity, rebalance, GoLive)
- `com.spa.autopush` — каждые 90 мин (push в GitHub)
- `com.spa.agent_health` — каждые 60 мин (мониторинг всех ~42 агентов)
- `com.spa.cycle_health` — каждые 5 мин (gap, equity anomaly, freshness)
- `com.spa.cycle_gap_monitor` — каждые 5 мин (gap_monitor.json heartbeat)

Если любой из этих агентов NOT LOADED → инцидент P1.
Проверка: `launchctl list | grep com.spa | sort`
Восстановление: перечитай `CURRENT_STATE.md § Мониторинг` → скопируй нужный plist из `scripts/` в `~/Library/LaunchAgents/` → `launchctl load`.

### ПРАВИЛО MON-002: Пороги здоровья системы

Система считается здоровой если ВСЕ условия выполнены:

| Метрика | Порог OK | Источник |
|---------|----------|----------|
| `last_cycle_ts` | не старше **26 часов** | data/paper_trading_status.json |
| `last_cycle_status` | `"ok"` | data/paper_trading_status.json |
| `kill_switch` | `CLEAR` (drawdown < **SOFT 5%**; **HARD all-cash kill при ≥10%**, ADR-048) | data/golive_status.json: drawdown_below_kill |
| `equity` | не падает >5% за сутки | data/cycle_health.json: equity_anomaly |
| `golive.passed` | не регрессирует (≥ предыдущего) | data/golive_status.json |
| `agent_health.warning_count` | ≤ 2 | data/agent_health.json |
| `agent_health.critical_count` | 0 | data/agent_health.json |
| `autopush` | exit=0, /tmp/spa_autopush.log существует | launchctl + лог |

**Ложные CRITICAL:** `agent_health.overall_status=CRITICAL` может быть ложным если `portfolio_health.score=null` (структурный баг). Смотри `critical_count`, не `overall_status`.

### ПРАВИЛО MON-003: Реакция на сбои

| Инцидент | Приоритет | Действие |
|---------|-----------|---------|
| `last_cycle_ts` > 26ч | **P0** | Немедленно запустить вручную: `python3 -m spa_core.paper_trading.cycle_runner --verbose` |
| `kill_switch` TRIGGERED | **P0** | НЕ трогать — это автоматическая защита. Прочитать DECISIONS.md, понять причину |
| drawdown ≥ **5%** (SOFT de-risk) | **P1** | **НЕ ликвидирует** (ADR-048): cycle halt'ит новые/увеличивающие аллокации (hold+reduce only), edge-triggered WARNING. Проверить `derisk_status.json` / risk_policy_blocks.json |
| drawdown ≥ **10%** (HARD kill) | **P0** | kill_switch активируется сам → **all-cash** ({"cash":1.0}). НЕ трогать — автоматическая защита. Прочитать DECISIONS.md (ADR-048) |
| Любой always-on агент NOT LOADED | **P1** | `launchctl load ~/Library/LaunchAgents/<label>.plist` |
| `agent_health.critical_count` > 0 | **P1** | Прочитать data/agent_health.json, исправить конкретный агент |
| `golive.passed` регрессировал | **P1** | Немедленно выяснить какой критерий упал, НЕ продолжать разработку |
| `autopush` не работает >3ч | **P1** | Проверить `~/Library/LaunchAgents/com.spa.autopush.plist`, перезагрузить |
| `cycle_health.overall=WARNING` | **P2** | Проверить data/cycle_health.json, исправить stale файлы |
| Одиночный WARNING агент | **P2** | Логировать, исправить при следующей сессии |

**Запрещено:** продолжать разработку аналитики при наличии P0/P1 инцидентов.

**Известные non-issues (по состоянию 2026-06-22):**
- `com.spa.apiserver` exit=-15 — SIGTERM при рестарте launchd, штатное поведение
- `portfolio_health.json` null-поля → ложный CRITICAL в agent_health: смотри `critical_count=0`
- `market_regime.json` stale (порог 4ч) — обновляется только в 08:00, WARNING ожидаем до 08:00+
- `equity_curve_daily.json` содержит 20 синтетических warmup-записей (`is_warmup: true`) — не ошибка

---

*Обновлён: 2026-06-22 (MON-001/002/003 — правила мониторинга на основе аудита 31 агента). Следующее обновление — при любом изменении правил или инфраструктуры.*

---

## Non-Issues (by design)

> Before flagging anything as a bug, check `data/AUDIT_BASELINE.json`. Items listed there are known states, not defects.

### Mac-only checks (false negatives in Linux sandbox)
- `com.spa.autopush.plist` — GoLiveChecker checks `~/Library/LaunchAgents/`. In Linux sandbox `~` ≠ `/Users/yuriikulieshov`, so check always fails. **On Mac host `autopush_installed` PASSes (current gate v6.0: 27/29).**
- Any `launchctl` or `launchd` command — macOS only.

### Missing files that are intentionally absent
- `data/sky_monitor.json` — GSM gate is inline in `cycle_runner.py:1289`. No separate file needed.
- `data/pnl_history.json` — superseded by `equity_curve_daily.json` and `paper_evidence_history.json`.

### Stale data (auto-regenerated each cycle)
- `data/tournament_results.json` — regenerated each cycle. composite_score=0.0 is correct for strategies with < 14 days of data.
- `data/equity_curve_daily.json` — contains 20 synthetic warmup entries (`is_warmup: true`). Expected, not corruption.

### Positions
- `spark_susds` at ≤10% — approved. T1 adapter with inline GSM fallback (APY 4.6%). Legitimate position.

### APY benchmark (recalibrated 2026-06-21)
- `apy_below_benchmark` activation uses a **realistic** benchmark: blended T1/T2 APY ≈ **4%**
  (paper track 4.11%). T1-only portfolio **cannot reliably hit 5%** — DeFiLlama 2026-06 means
  are Aave 3.64% / Compound 3.78% / Morpho Blue 6.87% / Yearn 4.93% / sUSDS 4.20%. There is **no
  hard «must achieve 5% APY» GoLive gate**; a sub-5% blended yield is by-design, not a defect.
  Spikes to 12–16% are single-spot and transient. See CLAUDE.md adapter table + `docs/DECISIONS.md`.

### Old push scripts
- `scripts/push_v*.sh` files with version ≤ `data/autopush_state.json:last_version` — dead/already-pushed. ~180 files are expected clutter.

### cycle_runner tournament
- Strategies S8, S9, S10, S14, S16–S21 excluded from tournament intentionally (T3/high-risk/pending). `strategy_registry.py` has all 25 but tournament subset = 15 is by design.
