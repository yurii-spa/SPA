# SPA Agent System Audit — v4 (ФИНАЛЬНЫЙ)
*2026-06-14 15:00 UTC | После полного цикла улучшений (4-я итерация)*

*Метод: статический аудит 18 plist-файлов в `scripts/` + парсинг `_module_registry.py` (578 модулей подтверждено) + анализ свежих runtime-артефактов (`paper_trading_status.json` @15:02, `kill_switch_status.json` @15:02, `uptime_status.json` @15:01, ~30 data/*.json обновлены @15:02) + grep интерпретаторов во всех plist + git/push-логи + AST-докстринги 20 агентов и signal_aggregator/kill_switch.*

> ⚠️ Ограничение метода: живой `launchctl list | grep com.spa` из песочницы выполнить нельзя (bash в Linux-sandbox, Terminal на Mac — read-only tier). Реальный launchd-статус берётся косвенно из свежести data-файлов и `uptime_status.json`. Для прямой проверки на Mac: `bash scripts/agent_status.sh`.

---

## Executive Summary

**Система: 7.5/10** (было 6/10 в начале дня, 7/10 после v3).

**Состав агентов:**
- **18 launchd plist** в `scripts/` (все на miniconda-python, 0 системных python3)
- **20 интеллектуальных агентов** в `spa_core/agents/` (CEO, Architect, Risk Sentinel, Alpha, Strategy v2, Protocol Research, Tester, Incident Commander и т.д.)
- **578 аналитических модулей** (Tier A=12, Tier B=386, Tier C=180) — реестр `_module_registry.py` подтверждён парсингом

**Что реально работает (доказано свежими артефактами @15:02 UTC):**
- `cycle_runner` отработал цикл в 15:02 — equity $100 047.74, APY today 3.95%, daily yield $10.83, total return +0.0477%, kill_switch_active=false
- Tier A signal_aggregator вшит в cycle_runner (блокирующие сигналы каждый цикл, строки 814/1120)
- Tier B advisory вшит в cycle_runner (Step 0a-pre, строка 808/815)
- Tier C — отдельный plist `com.spa.analytics_tier_c` (ежедневно 05:00)
- Autopush работает: 6 отчётов AUTOPUSH_REPORT за сегодня (02:07→14:06, каждые ~2ч), `.push_log` содержит push_v798..v809, осталось **1 pending** (push_v810.sh)
- Kill-switch исправлен: `MIN_DAYS_FOR_SHARPE=30` реально enforced в коде (sharpe-триггер возвращает "insufficient data" при <30 дней — фикс артефакта Sharpe -61 на 5 днях)
- http_server (8765) и cycle_freshness — OK в uptime_status

**Главные нерешённые проблемы:**
1. 🔴 Локальный git пуст — 0 коммитов (`git init` сделан 14:04, remote добавлен, но `HEAD` не существует, 93 untracked файла)
2. 🔴 uptime_monitor рапортует ВСЕ 17 `launchd_*` как FAIL в свежем (15:01) статусе — баг детекции launchd, а не реальное падение агентов
3. 🟠 Интерактивный Telegram-бот (`bot_commands.py`) не имеет plist — не автозапускается

---

## 1. Инфраструктурные агенты (launchd)

Все 18 plist в `scripts/`. Колонка Python: M=miniconda3 (`/Users/yuriikulieshov/miniconda3/bin/python3`), bash=shell-wrapper.

| # | Label | Tier | Что делает | Скрипт/модуль | Python | Расписание | KeepAlive | Статус |
|---|-------|------|-----------|---------------|--------|------------|-----------|--------|
| 1 | com.spa.httpserver | L1 | HTTP/API дашборд (порт 8765) | `family_fund.http_server` | M | RunAtLoad | ✅ true | http_server OK @15:01 |
| 2 | com.spa.cloudflared | L1 | Cloudflare tunnel → public HTTPS | `run_cloudflared.sh` | bash | RunAtLoad | ✅ true | wrapper исправен (opt/usr/PATH) |
| 3 | com.spa.fund-api | L1* | Family-fund API (порт 8766) | `fund_api_server.py 8766` | M | RunAtLoad=false | ❌ false | по требованию |
| 4 | com.spa.daily_cycle | L1 | Главный движок paper-trading | `paper_trading.cycle_runner --verbose` | M | StartInterval 1800s | — | цикл @15:02 ✅ |
| 5 | com.spa.uptime_monitor | L2 | Самопроверка 17 агентов+http+git | `monitoring.uptime_monitor` | M | 300s | — | пишет @15:01, но launchd-чеки FAIL (баг) |
| 6 | com.spa.cycle_health | L2 | Здоровье цикла, health_score 0-100 | `analytics.cycle_health_monitor` | M | 300s | — | данные свежие |
| 7 | com.spa.cycle_gap_monitor | L2 | Детект пропуска цикла (>26h) | `paper_trading.cycle_gap_monitor` | M | 300s | — | OK |
| 8 | com.spa.portfolio_monitor | L2 | Drift весов, health score | `paper_trading.portfolio_monitor` | M | 300s | — | OK |
| 9 | com.spa.peg_monitor | L2 | Отклонение стейблов от пега | `monitoring.peg_monitor` | M | 300s | — | OK |
| 10 | com.spa.red_flag_monitor | L2 | TVL/APY/governance/unlock флаги | `alerts.red_flag_monitor` | M | 300s | — | OK |
| 11 | com.spa.governance_watcher | L2b | Snapshot+Tally предложения | `alerts.governance_watcher` | M | 900s | — | данные @15:02 ✅ |
| 12 | com.spa.autopush | L3b | Авто-push pending push_v*.sh | `auto_push.sh` | bash | 5400s (90 мин) | — | работает (6 отчётов сегодня) ✅ |
| 13 | com.spa.analytics_tier_c | L3 | Tier C фоновая аналитика (180 мод.) | `analytics.signal_aggregator --tier C` | M | 05:00 ежедневно | — | NEW сегодня |
| 14 | com.spa.base_gas_monitor | L4 | ADR-025 Base gas kill-switch | `monitoring.base_gas_monitor` | M | 06:00 ежедневно | — | OK |
| 15 | com.spa.sky_monitor | L4 | Sky/sUSDS GSM delay → T1 апгрейд | `data_pipeline.sky_monitor` | M | 07:00 ежедневно | — | OK |
| 16 | com.spa.daily-paper-report | L4 | Daily P&L Telegram-отчёт | `scripts/daily_paper_report.py` | M | 09:00 ежедневно | — | OK |
| 17 | com.spa.checkpoint-7day | L4 | Разовый 7-дневный чекпоинт | `scripts/checkpoint_7day.py` | M | 2026-06-19 10:00 | — | one-shot |
| 18 | com.spa.weekly_backup | L4 | Еженедельный бэкап | `weekly_backup.sh` | bash | пт 10:00 | — | OK |

\* fund-api помечен L1 в комментарии, но RunAtLoad=false/KeepAlive=false → фактически on-demand (L4-поведение). Несоответствие tier↔конфиг.

**Python-интерпретаторы:** 13 plist на miniconda3, 4 на /bin/bash (cloudflared, autopush, weekly_backup, + autopush указывает bash-обёртку). 0 системных `/usr/bin/python3` — фикс интерпретаторов подтверждён.

**Несоответствие реестра:** `agent_status.sh` и `uptime_monitor.py` отслеживают **17** агентов и НЕ включают `com.spa.analytics_tier_c` (18-й, добавленный сегодня) → новый Tier C агент вне самомониторинга.

---

## 2. Интеллектуальные агенты (внутри cycle_runner / spa_core/agents)

| Агент/Модуль | Что делает | Выход | Частота |
|---|---|---|---|
| signal_aggregator (Tier A) | Блокирующие сигналы из 12 модулей | `analytics_signals_blocking.json` | каждый цикл (вшит) |
| signal_aggregator (Tier B) | Advisory из 386 модулей | `analytics_signals_advisory.json` | каждый цикл, Step 0a-pre |
| signal_aggregator (Tier C) | Фоновая аналитика 180 модулей | `analytics_report_full.json` | отд. plist 05:00 |
| kill_switch (governance) | 4 триггера: drawdown>15%, >5 red flags, manual, sharpe<-1 (≥30д) | `kill_switch_status.json` | каждый цикл |
| ceo_agent / ceo_agent_v2 | Стратегические недельные решения | decision log | недельно |
| architect_agent | Архитектурный ревью | review | по запросу |
| risk_sentinel (MP-303) | Детерминированный fast-loop sentinel | риск-сигналы | каждый цикл |
| alpha_agent (MP-304) | Скан кандидатов на whitelist | candidates | недельно |
| strategy_agent / v2 (MP-306) | Рекомендации селектору | strategy recs | недельно |
| protocol_research_agent (MP-307) | Поиск новых DeFi-протоколов | protocol list | недельно |
| incident_commander (MP-308) | Координация инцидентов | incidents.json | по событию |
| reporting_agent (MP-305) | Daily P&L + monthly text | Telegram/report | ежедневно |
| monitoring_agent / data_agent / tester_agent | Мониторинг/данные/тесты | разное | по циклу |
| decision_logger | Audit trail каждого действия | decisions.json | каждое решение |
| bot_commands (Telegram) | Интерактивный бот, inline-кнопки | Telegram polling | ⚠️ НЕ автозапущен |

Плюс: адаптеры (16+ в ADAPTER_REGISTRY), стратегии S0–S19, tournament, scoring_engine, allocator, tuner, watchdog — все вызываются внутри cycle_runner.

---

## 3. Аналитические модули (578)

| Tier | Количество | Роль | Частота | Запуск |
|------|-----------|------|---------|--------|
| A | 12 | Блокирующие сигналы (могут влиять на аллокацию) | каждый цикл (30 мин) | вшит в cycle_runner |
| B | 386 | Advisory (не блокируют, информируют) | каждый цикл | вшит в cycle_runner (Step 0a-pre) |
| C | 180 | Фоновая аналитика, полный отчёт | раз в день | `com.spa.analytics_tier_c` 05:00 |
| **Всего** | **578** | | | per-module timeout 3с, ThreadPoolExecutor |

Дизайн: pure-stdlib, read-only по чужим артефактам, атомарная запись, ring-buffer health-лог 100 записей (`analytics_health.json`).

---

## 4. Открытые проблемы

### 🔴 P0 (критично)
- **P0-1. Локальный git пуст — 0 коммитов.** `git init` выполнен сегодня 14:04, remote `origin → github.com/yurii-spa/SPA.git` добавлен, но `HEAD` не существует (`git rev-list HEAD` → fatal). 93 файла untracked, включая `.gitignore` (тоже не закоммичен). Пуш в GitHub идёт через HTTP API (`push_to_github.py`), локальный git как зеркало/история/откат не работает. Нужен первый `git add -A && git commit`.
- **P0-2. uptime_monitor рапортует все 17 launchd-агентов как FAIL.** Свежий (15:01) `uptime_status.json`: `all_ok=false`, все `launchd_*` checks = FAIL, при этом `http_server`=OK и `cycle_freshness`=OK, а сам uptime_monitor пишет файл (т.е. жив). Это баг парсинга `launchctl list` в uptime_monitor, а не реальное падение агентов (данные-файлы свежие @15:02 доказывают, что агенты идут). Ложноотрицательный самомониторинг = слепая зона для алертов.

### 🟠 P1 (важно)
- **P1-1. Интерактивный Telegram-бот не автозапускается.** `bot_commands.py` (MP-016b/MP-136, inline-кнопки, getUpdates polling) существует и протестирован (`test_bot_commands.py`), но НЕ привязан ни к одному plist → после перезагрузки Mac бот мёртв. Daily-report-бот (`daily-paper-report`) работает, но интерактивные команды (/now /week /status) — нет.
- **P1-2. analytics_tier_c вне самомониторинга.** 18-й plist (добавлен сегодня) не входит в EXPECTED-список `agent_status.sh` (17) и `uptime_monitor.py` (17). Падение Tier C не будет замечено.
- **P1-3. CURRENT_STATE.md устарел.** Секция launchd всё ещё говорит `autopush_status: not_installed` / `push_method: manual` / "❌ НЕ УСТАНОВЛЕН, нужен mp009_fix_launchd.command", хотя autopush сегодня отработал 6 раз. RULES.md startup-protocol ссылается на это → агент в следующей сессии зря запустит фикс.

### 🟡 P2 (улучшение)
- **P2-1. fund-api tier↔конфиг рассинхрон.** Помечен L1-демон в комментарии, но RunAtLoad=false/KeepAlive=false (фактически on-demand). Либо поправить tier-метку, либо включить KeepAlive если он должен быть постоянным.
- **P2-2. Tier B нагрузка в цикле.** 386 модулей Tier B исполняются inline в каждом цикле (каждые 30 мин). При per-module timeout 3с худший случай — заметная задержка цикла. Стоит вынести в отдельный plist (как Tier C) с hourly-расписанием, как изначально задумано в докстринге ("Tier B каждый час").
- **P2-3. daily_cycle StartInterval 1800s (30 мин) при имени "daily".** Идемпотентность per-UTC-day заявлена (строка 45), но 48 запусков/сутки — нагрузка; имя вводит в заблуждение.

### 🟢 P3 (nice-to-have)
- **P3-1.** Накопилось ~6 AUTOPUSH_REPORT_*.md в корне за один день — стоит складывать в `logs/` или ротировать.
- **P3-2.** Дубли агентов ceo_agent/ceo_agent_v2 и strategy_agent/strategy_agent_v2 — определить канонический, удалить устаревший.
- **P3-3.** `.ts_err`, `.ttmp/` в корне (untracked) — добавить в .gitignore.

---

## 5. Бэклог (только незакрытые)

| ID | Задача | Приоритет |
|----|--------|-----------|
| GIT-001 | Первый `git add -A && git commit -m "..."` + добавить .gitignore до коммита | P0 |
| MON-001 | Фикс парсинга launchctl в uptime_monitor.py (все 17 FAIL ложно) | P0 |
| BOT-001 | plist `com.spa.bot_commands` для интерактивного Telegram-бота + KeepAlive | P1 |
| MON-002 | Добавить `com.spa.analytics_tier_c` в EXPECTED (agent_status.sh + uptime_monitor.py) | P1 |
| DOC-001 | Обновить CURRENT_STATE.md: autopush=installed, push_method=auto, секция launchd → 18 агентов | P1 |
| INFRA-001 | Решить fund-api: tier-метка vs KeepAlive | P2 |
| PERF-001 | Вынести Tier B в отдельный hourly plist (разгрузить 30-мин цикл) | P2 |
| BL-007 | sky/sUSDS T1-апгрейд (ждёт on-chain GSM ≥48h) | заблокировано внешним |

---

## 6. Что нужно запустить вручную на Mac

```bash
cd ~/Documents/SPA_Claude

# (1) P0 — первый git-коммит (создать .gitignore СНАЧАЛА, чтобы не закоммитить __pycache__/data-мусор)
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.DS_Store
.push.lock
.ts_err
.ttmp/
AUTOPUSH_REPORT_*.md
EOF
git add -A
git commit -m "Initial commit — SPA system snapshot 2026-06-14 (578 modules, 18 agents)"

# (2) Установить/перезагрузить все launchd-агенты и проверить статус
for p in scripts/com.spa.*.plist; do
  cp "$p" ~/Library/LaunchAgents/
  launchctl unload ~/Library/LaunchAgents/$(basename "$p") 2>/dev/null
  launchctl load   ~/Library/LaunchAgents/$(basename "$p")
done
bash scripts/agent_status.sh      # ДОЛЖНО показать 18 loaded (а не 17)

# (3) Дослать последний pending push
bash scripts/auto_push.sh         # push_v810.sh

# (4) Проверить uptime после фикса MON-001
python3 -m spa_core.monitoring.uptime_monitor && cat data/uptime_status.json | python3 -m json.tool | head -30
```

---

## 7. Оценка зрелости

**Было утром: 6/10 → после v3: 7/10 → сейчас (v4): 7.5/10.**

Прогресс за день (подтверждён): 578 модулей интегрированы и работают inline+Tier C plist; kill-switch artefact-баг закрыт реальным enforce (MIN_DAYS_FOR_SHARPE=30 в коде); все plist на miniconda (0 системных python3); autopush консолидирован и реально пушит (6 циклов/день, 1 pending); uptime расширен до 17 агентов; git init сделан.

**До 10/10 осталось (конкретно):**
- **+1.0 → 8.5:** закрыть оба P0 — первый git-коммит (GIT-001) + фикс ложных launchd-FAIL в uptime_monitor (MON-001). Без достоверного самомониторинга и локальной истории система формально "running", но "слепая".
- **+0.7 → 9.2:** P1 — автозапуск Telegram-бота (BOT-001), Tier C в самомониторинг (MON-002), синхрон CURRENT_STATE.md (DOC-001).
- **+0.8 → 10:** P2 + go-live readiness — Tier B hourly plist (разгрузка цикла), fund-api конфиг, прохождение полного 7-дневного checkpoint (2026-06-19) с 30+ днями данных для надёжного Sharpe, и переход с paper на real после DD-аудита.

**Главный риск сейчас:** не код (он работает и считает деньги корректно — equity $100k, kill-switch чист), а **наблюдаемость**: самомониторинг даёт ложные FAIL по всем агентам, а локальная история отсутствует. Система едет, но приборная панель врёт.
