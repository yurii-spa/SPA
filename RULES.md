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
- **Статус (2026-06-12):** autopush НЕ установлен — plist-шаблон с заглушкой PYTHON_PATH
- **Разовый фикс:** `bash ~/Documents/SPA_Claude/mp009_fix_launchd.command`
- После фикса агенты никогда не упоминают пуш в отчётах — он происходит автоматически

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

| Сервис | Файл | Расписание | Лог |
|--------|------|------------|-----|
| Дневной цикл | cycle_runner.py | launchd 08:00 | /tmp/spa_cycle.log |
| Autopush | auto_push.py | launchd 90 мин | /tmp/spa_autopush.log |
| HTTP сервер | — | launchd | — |
| Cloudflare туннель | — | launchd | — |
| Агент-команда (Dev) | team_loop.py | launchd 4ч | SPA_Dev/spa_agents/logs/ |

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

## 📊 СОСТОЯНИЕ ПРОЕКТА (обновляется автоматически)

- **Спринт:** v4.47 (последний завершённый)
- **Done:** 91 задача
- **Backlog:** MP-017, UA-004, UA-006 (USER ACTION) + MP-126..135 (code-ready)
- **Track start:** 2026-06-10
- **Go-live:** ~2026-08-01

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

*Обновлён: 2026-06-21. Следующее обновление — при любом изменении правил или инфраструктуры.*

---

## Non-Issues (by design)

> Before flagging anything as a bug, check `data/AUDIT_BASELINE.json`. Items listed there are known states, not defects.

### Mac-only checks (false negatives in Linux sandbox)
- `com.spa.autopush.plist` — GoLiveChecker checks `~/Library/LaunchAgents/`. In Linux sandbox `~` ≠ `/Users/yuriikulieshov`, so check always fails. **On Mac host: 26/26 is correct.**
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
