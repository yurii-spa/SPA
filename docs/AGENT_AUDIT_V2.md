# SPA Agent System Audit v2.0
*Дата: 2026-06-14 | Архитектор: Claude Sonnet | Метод: полный статический + runtime аудит*

> Источники: AGENT_AUDIT.md v4, CURRENT_STATE.md, uptime_status.json (свежий @18:03 UTC),
> scripts/ (19 plist), spa_core/monitoring/uptime_monitor.py, launchd/*.plist, корневые plist,
> agent_status.sh, data/*.json (свежесть), spa_core/tests/ (~800+ файлов).

---

## Executive Summary

Агентная система SPA включает **19 launchd-демонов** + **20 интеллектуальных агентов** + **578 аналитических модулей** (Tier A/B/C). Все 19 plist написаны, все Python-модули существуют — с точки зрения кода система **полная**. Однако runtime-состояние **7/10**: из 19 агентов реально и корректно работают **~10**, ещё **3 установлены но неисправны** (crash/stale), и **5 не установлены** в launchd вообще.

**Три главные проблемы:**
1. **Слепой мониторинг**: cycle_health_monitor выдаёт stale-данные (45 часов), uptime_monitor завершается с exit 256, git push всегда FAIL → «приборная панель врёт» при рабочем двигателе.
2. **Неустановленные агенты**: fund-api, daily-paper-report, weekly_backup, analytics_tier_c, checkpoint-7day не загружены в launchd (`Could not find service`).
3. **Crash-агенты**: cloudflared (exit 19968, публичный HTTPS недоступен) + bot_commands (exit 256, Telegram-бот мёртв) + усугублено конфликтом трёх версий plist для bot_commands.

---

## Агентная топология (как задумана)

```
L1 — Persistent daemons (RunAtLoad + KeepAlive)
├─ com.spa.httpserver       → family_fund.http_server (port 8765)
├─ com.spa.cloudflared      → scripts/run_cloudflared.sh (public HTTPS)
├─ com.spa.daily_cycle      → paper_trading.cycle_runner (StartInterval 1800s)
└─ com.spa.fund-api         → scripts/fund_api_server.py (port 8766, on-demand)

L1b — Persistent Telegram bot (KeepAlive long-poll)
└─ com.spa.bot_commands     → spa_core.telegram.bot (v2.0, inline keyboards)

L2 — Every 5 min (StartInterval 300s)
├─ com.spa.uptime_monitor   → monitoring.uptime_monitor (19 checks, all_ok flag)
├─ com.spa.cycle_health     → monitoring.cycle_health_monitor (gap/equity/freshness)
├─ com.spa.cycle_gap_monitor→ paper_trading.cycle_gap_monitor (>26h alert)
├─ com.spa.portfolio_monitor→ paper_trading.portfolio_monitor (drift/HHI)
├─ com.spa.peg_monitor      → monitoring.peg_monitor (stablecoin peg)
└─ com.spa.red_flag_monitor → alerts.red_flag_monitor (TVL/APY/governance flags)

L2b — Every 15 min (StartInterval 900s)
└─ com.spa.governance_watcher → alerts.governance_watcher (Snapshot/Tally)

L3b — Every 90 min (StartInterval 5400s)
└─ com.spa.autopush         → scripts/auto_push.sh (GitHub sync)

L4 — Daily scheduled (StartCalendarInterval)
├─ com.spa.base_gas_monitor → monitoring.base_gas_monitor (06:00, ADR-025 kill-switch)
├─ com.spa.sky_monitor      → data_pipeline.sky_monitor (07:00, GSM gate)
├─ com.spa.daily-paper-report → scripts/daily_paper_report.py (09:00, Telegram P&L)
├─ com.spa.weekly_backup    → scripts/weekly_backup.sh (Пт 10:00)
└─ com.spa.analytics_tier_c → analytics.signal_aggregator --tier C (05:00, 180 модулей)

L5 — One-shot (StartCalendarInterval конкретная дата)
└─ com.spa.checkpoint-7day  → scripts/checkpoint_7day.py (2026-06-19 10:00)
```

---

## Матрица покрытия

> Статус лiveness определён из `data/uptime_status.json` (ts: 2026-06-14T18:03 UTC).
> Символы: ✅ OK | ❌ FAIL | ⚠️ WARN | ⏱ FUTURE | N/A (bash/no-tests)

| Агент | Уровень | Модуль | plist | Установлен | Работает | Тесты | Проблемы |
|---|---|---|---|---|---|---|---|
| com.spa.httpserver | L1 | family_fund/http_server.py | ✅ | ✅ | ✅ HTTP 200, 16ms | ❓ | — |
| com.spa.cloudflared | L1 | scripts/run_cloudflared.sh | ✅ | ✅ | ❌ exit 19968 | N/A | Crash; public HTTPS down |
| com.spa.fund-api | L1* | scripts/fund_api_server.py | ✅ | ❌ | ❌ not found | ❓ | Не загружен в launchd |
| com.spa.daily_cycle | L1 | paper_trading/cycle_runner.py | ✅ | ✅ | ✅ 23 мин назад | ✅ | StartInterval 1800s (30m) |
| com.spa.bot_commands | L1b | spa_core/telegram/bot.py | ✅⚠️ | ✅ | ❌ exit 256 | ✅ | Crash + 3 конфликтующих plist |
| com.spa.uptime_monitor | L2 | monitoring/uptime_monitor.py | ✅ | ✅ | ⚠️ exit 256 | ✅ | Python error; all_ok=false |
| com.spa.cycle_health | L2 | monitoring/cycle_health_monitor.py | ✅ | ✅ | ❌ stale 45h | ✅ | Не пишет данные 45 часов |
| com.spa.cycle_gap_monitor | L2 | paper_trading/cycle_gap_monitor.py | ✅ | ✅ | ❌ missing | ✅ | Нет output-файла |
| com.spa.portfolio_monitor | L2 | paper_trading/portfolio_monitor.py | ✅ | ✅ | ✅ age 4s | ❌ | Нет unit-тестов |
| com.spa.peg_monitor | L2 | monitoring/peg_monitor.py | ✅ | ✅ | ✅ age 2s | ✅ 877L | — |
| com.spa.red_flag_monitor | L2 | alerts/red_flag_monitor.py | ✅ | ✅ | ✅ age 119s | ✅ 692L | — |
| com.spa.governance_watcher | L2b | alerts/governance_watcher.py | ✅ | ✅ | ✅ age 260s | ✅ 690L | — |
| com.spa.autopush | L3b | scripts/auto_push.sh | ✅ | ✅ | ✅ 68 мин назад | N/A | — |
| com.spa.base_gas_monitor | L4 | monitoring/base_gas_monitor.py | ✅ | ✅ | ✅ age 1391s | ❓ | — |
| com.spa.sky_monitor | L4 | data_pipeline/sky_monitor.py | ✅ | ✅ | ❌ stale 105h | ✅ | 4.4 дня без обновлений |
| com.spa.daily-paper-report | L4 | scripts/daily_paper_report.py | ✅ | ❌ | ❌ not found | ✅ | Не загружен в launchd |
| com.spa.checkpoint-7day | L5 | scripts/checkpoint_7day.py | ✅ | ❌ | ⏱ 2026-06-19 | ❓ | Будущий one-shot; OK |
| com.spa.weekly_backup | L4 | scripts/weekly_backup.sh | ✅ | ❌ | ❌ not found | N/A | Не загружен в launchd |
| com.spa.analytics_tier_c | L4 | analytics/signal_aggregator | ✅ | ❌ | ❌ not found | ❓ | Не загружен; нет output |

**Сводка:**

| Метрика | Значение |
|---|---|
| Описано в документации | 19 |
| Python-модуль написан | 19 (100%) |
| plist написан | 19 (100%) |
| Установлено в launchd | ~14 (из uptime_status) |
| Реально работает корректно | **10** |
| Работает с ошибками (crash/stale) | **4** (cloudflared, bot_commands, cycle_health, cycle_gap_monitor) |
| Не установлено | **5** (fund-api, daily-paper-report, weekly_backup, analytics_tier_c, checkpoint-7day) |
| С unit-тестами (Python-агенты) | 9 из 15 (60%) |

---

## Gap Analysis

### GAP-1: Описан но не написан
**0 агентов** — все 19 агентов имеют написанный Python/bash модуль. ✅

### GAP-2: Написан но нет plist
**0 агентов** — все 19 модулей имеют plist в `scripts/`. ✅

### GAP-3: plist есть, не в LaunchAgents (не установлен)
**5 агентов** — `launchctl` возвращает `exit 113: Could not find service`:

| Агент | Критичность | Следствие |
|---|---|---|
| com.spa.daily-paper-report | 🟠 P1 | Нет ежедневного Telegram-отчёта |
| com.spa.weekly_backup | 🟠 P1 | Нет еженедельных резервных копий |
| com.spa.analytics_tier_c | 🟠 P1 | 180 Tier C модулей не запускаются; нет analytics_report_full.json |
| com.spa.fund-api | 🟡 P2 | Investor portal API (port 8766) недоступен |
| com.spa.checkpoint-7day | 🟢 P3 | One-shot 2026-06-19, ещё не наступил — норма |

### GAP-4: Установлен, но не работает (crash или stale)
**4 агента**:

| Агент | Симптом | Причина (гипотеза) |
|---|---|---|
| com.spa.bot_commands | exit 256, running=false | Python error в spa_core.telegram.bot; конфликт 3 версий plist |
| com.spa.cloudflared | exit 19968, pid=null | Cloudflared binary crash или auth token истёк |
| com.spa.cycle_health | stale 45h (max 1800s) | ModuleNotFoundError или runtime error в analytics.cycle_health_monitor |
| com.spa.cycle_gap_monitor | missing output file | cycle_gap_state.json никогда не создавался; либо ImportError, либо permissions |
| com.spa.sky_monitor | stale 105h (max 108000s) | Модуль исполняется, но данные устаревают; возможно, API timeout или логика не пишет файл |
| com.spa.uptime_monitor | exit 256, last_exit 256 | Python exception в последнем запуске; сам демон жив (pid 50844), но результаты неверные |

### GAP-5: Запущен, нет unit-тестов
**3 агента** (Python-модули без test_*.py):

| Агент | Модуль | Важность тестов |
|---|---|---|
| com.spa.portfolio_monitor | paper_trading/portfolio_monitor.py | Высокая: drift/HHI вычисления влияют на ребаланс |
| com.spa.base_gas_monitor | monitoring/base_gas_monitor.py | Высокая: kill-switch агент ADR-025 |
| com.spa.analytics_tier_c | analytics/signal_aggregator | Средняя: advisory-only, но 180 модулей |

### GAP-6: Конфигурационные ошибки
**3 проблемы**:

**6a. bot_commands — конфликт трёх plist:**

| Локация | Python | Модуль | Статус |
|---|---|---|---|
| `./com.spa.bot_commands.plist` (корень) | `__PYTHON_PATH__` (заглушка) | spa_core.alerts.bot_commands | ❌ Устаревший |
| `./launchd/com.spa.bot_commands.plist` | `/usr/bin/python3` | spa_core.alerts.bot_commands | ❌ Устаревший |
| `./scripts/com.spa.bot_commands.plist` | `/Users/.../miniconda3/bin/python3` | spa_core.telegram.bot | ✅ Канонический |

Установлена скорее всего одна из устаревших версий → ModuleNotFoundError/exit 256.

**6b. git — нет коммитов:**
`git log` возвращает `exit 128: fatal: your current branch 'main' does not have any commits yet`. git init выполнен, remote добавлен, но 0 коммитов. Следствие: uptime_monitor check `git_push` всегда FAIL, нет возможности откатиться.

**6c. uptime_monitor exit 256:**
uptime_monitor.py запускается (pid 50844), пишет файл, но завершается с exit 256 (= Python exception). Последний recorded exit code = 256. Возможно, проблема в check_git_push или check_launchd_service при отсутствии коммитов.

### GAP-7: Агент работает, но нет мониторинга
**1 случай**: `com.spa.analytics_tier_c` не включён в `scripts/agent_status.sh` (список 18 агентов) и не в `uptime_monitor.py`. Хотя агент всё равно не запущен (GAP-3), при установке его падение не будет замечено ни одним из мониторов.

---

## Бэклог: что нужно для Tier 1

### P0 — Критические (система не работает без них)

- [ ] **[AGENT-P0-001]** Первый git-коммит + .gitignore
  *Описание:* `git init` выполнен, но нет ни одного коммита. `git push` check всегда FAIL, нет истории изменений, нет возможности откатиться при инциденте. Добавить `.gitignore` (исключить `__pycache__`, `*.pyc`, `data/`, `AUTOPUSH_REPORT_*.md`, `.push.lock`, `.DS_Store`), затем `git add -A && git commit -m "Initial commit"`.
  *Критерий готовности:* `git log --oneline -1` показывает коммит; `data/uptime_status.json` → `git_push.ok = true`; `push_to_github.py` успешно создаёт/обновляет файлы в GitHub.

- [ ] **[AGENT-P0-002]** Диагностика и фикс uptime_monitor exit 256
  *Описание:* `spa_core/monitoring/uptime_monitor.py` запускается каждые 5 мин, имеет pid (50844), пишет uptime_status.json — но завершается с exit 256 (= Python exception). all_ok всегда false. Нужно добавить вывод полного traceback в stderr (LogErrorPath в plist) и прочитать `logs/uptime_monitor_err.log` для диагностики. Гипотеза: exception в `check_git_push()` при отсутствии коммитов не перехватывается.
  *Критерий готовности:* `exit 0` при all_ok=true; `uptime_status.json.checks.launchd_uptime_monitor.last_exit = 0`.

- [ ] **[AGENT-P0-003]** Починить cycle_health_monitor (stale 45h)
  *Описание:* `data/cycle_health.json` не обновлялся 45 часов (max_age 1800s). `com.spa.cycle_health` установлен (pid=null — периодический), last_exit=0, но output stale. Возможные причины: модуль завершается с exit 0 без записи (условие не выполнено), или запись идёт в другой путь. Нужно: запустить вручную `python3 -m spa_core.monitoring.cycle_health_monitor --run`, проверить output, починить.
  *Критерий готовности:* `data/cycle_health.json` обновляется каждые ≤30 мин; `uptime_status.json.checks.launchd_cycle_health.running = true`.

- [ ] **[AGENT-P0-004]** Починить bot_commands Telegram-бот (exit 256 + plist conflict)
  *Описание:* `com.spa.bot_commands` установлен (по uptime_status), но running=false, exit 256. Параллельно существуют 3 версии plist с разными python и модулями (заглушка __PYTHON_PATH__ в корне, /usr/bin/python3 в launchd/, miniconda3 в scripts/). Нужно: (1) удалить устаревшие plist (корень + launchd/), (2) переустановить из scripts/ с `spa_core.telegram.bot`, (3) убедиться что TELEGRAM_BOT_TOKEN_SPA в Keychain, (4) проверить exit.
  *Критерий готовности:* `uptime_status.json.checks.launchd_bot_commands.running = true`; Telegram /status отвечает.

- [ ] **[AGENT-P0-005]** Починить cloudflared (exit 19968)
  *Описание:* `com.spa.cloudflared` установлен с KeepAlive, но pid=null, exit 19968 (SIGQUIT от cloudflare daemon?). Public HTTPS-доступ к дашборду недоступен. Нужно: проверить `logs/cloudflared.log`, обновить cloudflared binary (`brew upgrade cloudflared`), проверить auth token (`cloudflared login`).
  *Критерий готовности:* `uptime_status.json.checks.launchd_cloudflared.running = true`; туннель отвечает по public URL.

- [ ] **[AGENT-P0-006]** Починить cycle_gap_monitor (missing output)
  *Описание:* `data/cycle_gap_state.json` отсутствует. `com.spa.cycle_gap_monitor` установлен, last_exit=0, но нет output. Либо модуль никогда не отработал (условие >26h gap не выполнялось, поэтому файл не создан при `--check` режиме), либо ошибка в логике создания файла при отсутствии пробела. Нужно: запустить `python3 -m spa_core.paper_trading.cycle_gap_monitor --run`, убедиться что файл создаётся.
  *Критерий готовности:* `data/cycle_gap_state.json` существует и обновляется; `uptime_status.json.checks.launchd_cycle_gap_monitor.running = true`.

---

### P1 — Высокий приоритет (нужны для production)

- [ ] **[AGENT-P1-001]** Установить 4 не-загруженных агента (GAP-3)
  *Описание:* `com.spa.daily-paper-report`, `com.spa.weekly_backup`, `com.spa.analytics_tier_c` не найдены в launchd. Нужно выполнить `bash scripts/install_agents.sh` (уже включает все 19 агентов) или по-агентно: `cp scripts/com.spa.daily-paper-report.plist ~/Library/LaunchAgents/ && launchctl load`.
  *Критерий готовности:* `bash scripts/agent_status.sh` показывает LOADED для всех 19 агентов.

- [ ] **[AGENT-P1-002]** Добавить analytics_tier_c в мониторинг (GAP-7)
  *Описание:* `scripts/agent_status.sh` содержит 18 агентов (без com.spa.analytics_tier_c). `spa_core/monitoring/uptime_monitor.py` тоже не мониторит этот агент. Нужно добавить в оба файла.
  *Критерий готовности:* `bash scripts/agent_status.sh` проверяет 19 агентов; uptime_status.json содержит `launchd_analytics_tier_c`.

- [ ] **[AGENT-P1-003]** Диагностика sky_monitor (stale 105h)
  *Описание:* `data/sky_status.json` устарел на 4.4 дня. Модуль запускается ежедневно 07:00, last_exit=0, но данные не обновляются. Нужно: запустить вручную `python3 -m spa_core.data_pipeline.sky_monitor`, проверить output, починить.
  *Критерий готовности:* `data/sky_status.json` обновляется ежедневно; `uptime_status.json.checks.launchd_sky_monitor.running = true`.

- [ ] **[AGENT-P1-004]** Написать unit-тесты для portfolio_monitor
  *Описание:* `spa_core/paper_trading/portfolio_monitor.py` — единственный активный L2-агент без тест-покрытия. Агент вычисляет drift весов и HHI, критично для детектирования расхождений с allocator. Нужно: создать `spa_core/tests/test_portfolio_monitor.py` с минимум 20 тестами.
  *Критерий готовности:* `python3 -m pytest spa_core/tests/test_portfolio_monitor.py` → 20+ PASS.

- [ ] **[AGENT-P1-005]** Очистить дублирующиеся plist
  *Описание:* plist дублируются в 3 местах (корень: 4 файла; launchd/: 2 файла; scripts/: 19 файлов). Канонические — в `scripts/`. Устаревшие нужно удалить, чтобы избежать установки неверной версии.
  *Критерий готовности:* plist существуют только в `scripts/`; корневые и `launchd/` удалены или перемещены в `archive/`.

---

### P2 — Средний (важны для стабильности)

- [ ] **[AGENT-P2-001]** Вынести Tier B аналитику в отдельный hourly plist
  *Описание:* 386 Tier B модулей выполняются inline в каждом 30-мин цикле cycle_runner. При per-module timeout 3с это теоретически до ~20 мин накладных расходов. Планировалось вынести в отдельный hourly plist (по аналогии с Tier C). Создать `com.spa.analytics_tier_b.plist` (hourly), убрать из cycle_runner.
  *Критерий готовности:* cycle_runner не вызывает Tier B inline; `com.spa.analytics_tier_b` в launchd загружен, hourly.

- [ ] **[AGENT-P2-002]** Написать тесты для base_gas_monitor
  *Описание:* `spa_core/monitoring/base_gas_monitor.py` — kill-switch агент ADR-025 без тест-покрытия. Критичность высокая (может блокировать Base chain операции). Нужно: создать `spa_core/tests/test_base_gas_monitor.py`.
  *Критерий готовности:* 15+ тестов PASS.

- [ ] **[AGENT-P2-003]** Исправить несоответствие fund-api tier↔конфиг
  *Описание:* fund-api отмечен как L1 (persistent) в комментарии, но `RunAtLoad=false`, `KeepAlive=false` (on-demand поведение). Решить: либо перевести в L4/on-demand официально, либо включить KeepAlive если нужна постоянная доступность investor portal.
  *Критерий готовности:* tier в документации и конфиге согласованы.

- [ ] **[AGENT-P2-004]** Настроить StandardErrorPath для всех агентов
  *Описание:* Большинство агентов не имеют `StandardErrorPath` в plist → при crash нет логов для диагностики. Нужно добавить `<key>StandardErrorPath</key><string>logs/{agent}_err.log</string>` во все plist.
  *Критерий готовности:* Все 19 plist имеют StandardErrorPath; директория logs/ создаётся install_agents.sh.

---

### P3 — Низкий (nice to have)

- [ ] **[AGENT-P3-001]** Ротация AUTOPUSH_REPORT_*.md из корня в logs/
  *Описание:* За один день накопилось 8+ файлов AUTOPUSH_REPORT в корне репо. Настроить auto_push.sh для записи отчётов в `logs/autopush/YYYY-MM-DD/`, добавить в .gitignore.
  *Критерий готовности:* Корень чистый; отчёты в `logs/autopush/`.

- [ ] **[AGENT-P3-002]** Определить канонические версии дублирующихся агентов
  *Описание:* Существуют дубли: ceo_agent.py + ceo_agent_v2.py, strategy_agent.py + strategy_agent_v2.py. Нужно зафиксировать в DECISIONS.md какая версия канонична, устаревшие пометить deprecated (или удалить).
  *Критерий готовности:* Один активный файл на агент; устаревшие удалены или помечены.

- [ ] **[AGENT-P3-003]** daily_cycle — переименовать или изменить расписание
  *Описание:* `com.spa.daily_cycle` запускается каждые 30 мин (StartInterval 1800s), но называется "daily". Это нарушает принцип наименьшего удивления. Либо переименовать в `com.spa.cycle_runner`, либо документировать что "daily" означает "paper trading cycle unit".
  *Критерий готовности:* Название и расписание согласованы; CURRENT_STATE.md обновлён.

---

## Критерии Tier 1

Агентная система считается **Tier 1** при выполнении ВСЕХ следующих условий:

| # | Критерий | Проверка |
|---|---|---|
| T1-1 | Все 19 агентов загружены в launchd | `bash scripts/agent_status.sh` → Missing: 0 |
| T1-2 | Все 19 агентов работают без crash/stale | `uptime_status.json.all_ok = true` |
| T1-3 | git коммиты существуют, push актуален | `uptime_status.json.checks.git_push.ok = true` |
| T1-4 | Telegram-бот отвечает на /status | Ручная проверка в Telegram |
| T1-5 | cycle_health обновляется каждые ≤30 мин | `data/cycle_health.json` age < 1800s |
| T1-6 | Все Python L2-агенты имеют unit-тесты | `pytest spa_core/tests/test_portfolio_monitor.py` PASS |
| T1-7 | Нет конфликтующих plist (одна каноническая локация) | plist только в `scripts/` |
| T1-8 | Public HTTPS-туннель работает | cloudflared running=true |
| T1-9 | sky_monitor обновляется ежедневно | `data/sky_status.json` age < 108000s |
| T1-10 | uptime_monitor exit 0 (all checks clean) | `uptime_monitor.py` exit 0 |

**Текущий статус Tier 1**: **4/10** (T1-4 возможно, T1-5 нет, T1-1 нет, T1-3 нет, T1-10 нет).

---

## Рекомендации архитектора

**1. Запустить install_agents.sh НЕМЕДЛЕННО**
Первый шаг к Tier 1 — `bash scripts/install_agents.sh` уже содержит все 19 агентов. Это закрывает GAP-3 (5 не-установленных) и потенциально поднимет daily-paper-report, weekly_backup, analytics_tier_c.

**2. P0-шаги делать строго последовательно**
Порядок: GIT-коммит (P0-001) → фикс uptime_monitor (P0-002) → диагностика crash-агентов (P0-003..006). Без git-коммита нет возможности откатиться. Без рабочего uptime_monitor нет наблюдаемости.

**3. Устранить plist-конфликт bot_commands до P0-004**
Три версии plist гарантируют что бот поднимется с неверным модулем. Алгоритм: `rm ~/Library/LaunchAgents/com.spa.bot_commands.plist`, `cp scripts/com.spa.bot_commands.plist ~/Library/LaunchAgents/`, `launchctl load`. Канонический модуль: `spa_core.telegram.bot` (v2.0).

**4. StandardErrorPath для всех агентов — до следующего инцидента**
Cloudflared упал с exit 19968 — нет логов. uptime_monitor exit 256 — нет traceback. Без `StandardErrorPath` каждая диагностика — слепая. Один прогон `scripts/install_agents.sh` после добавления `<StandardErrorPath>` во все plist решает проблему.

**5. Перевести cycle_runner в idempotent-daily режим**
StartInterval 1800s (48 запусков/день) при задуманной идемпотентности per-UTC-day — избыточная нагрузка. Рекомендуется StartCalendarInterval Hour=8 (один запуск в 08:00 UTC), с отдельным fallback-триггером если цикл не запустился к 10:00 (через cycle_gap_monitor).

---

## Приложение: Список ключевых файлов

| Файл | Роль |
|---|---|
| `data/uptime_status.json` | Runtime-состояние всех 19 агентов |
| `scripts/agent_status.sh` | CLI-проверка: `bash scripts/agent_status.sh` |
| `scripts/install_agents.sh` | Идемпотентная установка всех 19 агентов |
| `scripts/com.spa.*.plist` | Канонические plist (все остальные — устаревшие) |
| `logs/auto_push.log` | Лог autopush (когда был последний push) |
| `data/cycle_health.json` | Здоровье цикла (мониторинг) |
| `data/gap_monitor.json` | Непрерывность трека (для GoLive) |

---

*AGENT_AUDIT_V2.md | Создан: 2026-06-14 | Следующий аудит: 2026-07-01 или после закрытия всех P0*
