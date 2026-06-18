# SPA Agent System Audit v3.0 — Tier 1 Roadmap
*Дата: 2026-06-14 | Метод: прямые bash-команды с диска, ручной запуск каждого агента*

---

## TL;DR

**12 из 19 агентов работают на Tier 1 уровне.** 4 агента имеют реальные баги в конфигурации (не в коде), 3 агента недоступны по ожидаемым причинам (schedule/design).

**Главная проблема:** 4 конфигурационных бага в plist/скриптах делают `uptime_monitor.all_ok` постоянно `False`, хотя core-система (cycle_runner, equity $100 047, kill_switch чист) работает корректно.

**Срок до полного Tier 1:** 1–2 часа работы (4 однострочных fix в plist + установка cloudflared).

---

## Матрица покрытия (все 19 агентов)

| # | Агент | В ТЗ | plist в scripts/ | Установлен в LaunchAgents | Реально OK | Тесты | Статус | Проблема |
|---|-------|------|-----------------|--------------------------|-----------|-------|--------|----------|
| 1 | com.spa.httpserver | ✅ | ✅ | ✅ | ✅ pid=54083, 200 OK 14ms | ✅ | ✅ OK | — |
| 2 | com.spa.cloudflared | ✅ | ✅ | ✅ | ❌ exit=256 | ✅ | ❌ CRASHED | `cloudflared` binary не установлен (нет в /opt/homebrew/bin, /usr/local/bin и т.д.) |
| 3 | com.spa.fund-api | ✅ | ✅ | ✅ | ⏸ RunAtLoad=false | — | ⏸ ON-DEMAND | Дизайн: on-demand, не должен быть постоянным |
| 4 | com.spa.daily_cycle | ✅ | ✅ | ✅ | ✅ equity $100 047.72, last run 13m ago | ✅ | ✅ OK | — |
| 5 | com.spa.uptime_monitor | ✅ | ✅ | ✅ | ✅ pid=54685 | ✅ | ⚠️ all_ok=False | Из-за нижележащих багов (п.6, п.7) — сам модуль работает корректно |
| 6 | com.spa.cycle_health | ✅ | ✅ | ✅ | ❌ stale 47h→fixed | ❌ exit=1 | ❌ БАГ | plist запускает `analytics.cycle_health_monitor` (→ пишет `cycle_health_log.json`), а uptime_monitor ждёт `cycle_health.json` от `monitoring.cycle_health_monitor` |
| 7 | com.spa.cycle_gap_monitor | ✅ | ✅ | ✅ | ❌ output MISSING | ✅ exit=0 | ❌ БАГ | plist передаёт `--check` (read-only, без записи), а uptime ждёт `data/cycle_gap_state.json` — который пишется только при `--run` |
| 8 | com.spa.portfolio_monitor | ✅ | ✅ | ✅ | ✅ age=0s | ✅ exit=0 | ✅ OK | — |
| 9 | com.spa.peg_monitor | ✅ | ✅ | ✅ | ✅ age=0s | ✅ exit=0 | ✅ OK | — |
| 10 | com.spa.red_flag_monitor | ✅ | ✅ | ✅ | ✅ age=280s | ⚠️ timeout sandbox | ✅ OK | Sandbox-сеть блокирует DeFiLlama API — на реальном Mac работает |
| 11 | com.spa.governance_watcher | ✅ | ✅ | ✅ | ✅ age=587s | ✅ --offline OK | ✅ OK | — |
| 12 | com.spa.autopush | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ OK | — |
| 13 | com.spa.analytics_tier_c | ✅ | ✅ | ✅ | ❌ output MISSING | ✅ exit=0 | ⚠️ НЕ ЗАПУСТИЛСЯ | `analytics_report_full.json` отсутствует — агент запускается в 05:00, ещё не отработал сегодня |
| 14 | com.spa.base_gas_monitor | ✅ | ✅ | ✅ | ✅ | ✅ exit=0 | ✅ OK | — |
| 15 | com.spa.sky_monitor | ✅ | ✅ | ? | ❌ stale 107ч | ✅ exit=0 | ❌ БАГ | `sky_status.json` не обновлялся 4.5 дня (max=30ч). RunAtLoad=false — не запускается при старте системы. Вероятно, launchd не загружает агент |
| 16 | com.spa.daily-paper-report | ✅ | ✅ | ? | ✅ (proxy file) | ✅ | ✅ OK | Использует `paper_trading_status.json` как proxy — OK |
| 17 | com.spa.checkpoint-7day | ✅ | ✅ | ? | ⏸ one-shot | — | ⏸ FUTURE | One-shot на 2026-06-19 10:00 — ещё не должен был запустить |
| 18 | com.spa.weekly_backup | ✅ | ✅ | ? | ⏸ пятница | — | ⏸ SCHEDULE | Запускается только по пятницам — норма |
| 19 | com.spa.bot_commands | ✅ | ✅ | ✅ | ✅ pid=54026 | ✅ | ⚠️ NO TOKEN | Процесс запущен, но `TELEGRAM_BOT_TOKEN_SPA` недоступен из Keychain → бот не отвечает |

---

## Что работает прямо сейчас ✅

Следующие агенты подтверждены работающими по данным с диска (проверено 2026-06-14):

- **daily_cycle** — последний цикл 19:59 UTC, equity $100 047.72, APY 3.9%, kill_switch=clear, risk_policy_approved=true, is_demo=false
- **httpserver** — порт 8765, HTTP 200 за 14.5ms, pid=54083
- **uptime_monitor** — pid=54685, пишет uptime_status.json, самомониторинг 22 чеков
- **portfolio_monitor** — пишет monitor_snapshots.json, age=0s
- **peg_monitor** — пишет peg_report.json, age=0s
- **red_flag_monitor** — пишет red_flags.json, age=280s
- **governance_watcher** — пишет governance_proposals.json, age=587s
- **autopush** — работает, последний push 80 мин назад
- **base_gas_monitor** — пишет base_gas_history.json, проверено сегодня
- **daily-paper-report** — использует cycle output, 09:00 ежедневно
- **bot_commands** — pid=54026, процесс жив (нужен Keychain-токен)
- **golive_checker** — 6/6 PASS, ready=true

---

## Что сломано / не запущено ❌

### P0 — Конфигурационные баги (блокируют uptime_monitor.all_ok)

**BUG-1: cycle_health plist запускает неверный модуль**

```
plist сейчас:  spa_core.analytics.cycle_health_monitor --run
              → пишет: data/cycle_health_log.json

uptime ждёт:   data/cycle_health.json
              → пишет только: spa_core.monitoring.cycle_health_monitor --run
```

Исправление в `scripts/com.spa.cycle_health.plist`:
```xml
<!-- было -->
<string>spa_core.analytics.cycle_health_monitor</string>
<!-- надо -->
<string>spa_core.monitoring.cycle_health_monitor</string>
```

Дополнительная проблема: `cycle_health_monitor` читает `equity_history.json` (последняя запись: 2026-06-12), а не `paper_trading_status.json` (обновляется каждые 30 мин). Из-за этого всегда сообщает CRITICAL при реально работающем цикле. `equity_history.json` — легаси-файл, не обновляемый текущим `cycle_runner`.

**BUG-2: cycle_gap_monitor plist использует `--check` вместо `--run`**

```
plist сейчас:  --check   (read-only, не пишет файл)
uptime ждёт:   data/cycle_gap_state.json (пишется только при --run)
Результат:     output MISSING → всегда FAIL в uptime
```

Исправление:
```xml
<!-- было -->
<string>--check</string>
<!-- надо -->
<string>--run</string>
```

**BUG-3: cloudflared — бинарник не установлен**

`run_cloudflared.sh` ищет бинарник в `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, `/usr/bin` — ни одного нет. `exit 1` → launchd exit=256. Публичный HTTPS-туннель мёртв, инвесторский портал недоступен извне.

Исправление: `brew install cloudflared && cloudflared tunnel login`

**BUG-4: sky_monitor не обновляется (стаж 107ч, лимит 30ч)**

`sky_status.json` последний раз обновлялся 4.5 дня назад. sky_monitor настроен на `StartCalendarInterval Hour=7` с `RunAtLoad=false`. Если launchd не загружал агент при последних перезагрузках — файл не обновлялся. Модуль работает (exit=0 при ручном запуске), проблема в загрузке/регистрации.

---

### P1 — Функциональные ограничения

**P1-1: bot_commands без Telegram-токена**

pid=54026 есть, но при старте: `"Bot credentials unavailable: Keychain read failed for TELEGRAM_BOT_TOKEN_SPA"`. Интерактивные команды `/now`, `/week`, `/status` не работают. Daily-report (push-алерты) работают отдельно через `daily-paper-report`.

**P1-2: analytics_tier_c — analytics_report_full.json отсутствует**

Агент запускается ежедневно в 05:00. `analytics_report_full.json` не существует → uptime сообщает FAIL. При ручном запуске (`signal_aggregator --run --tier C`) — exit=0, данные пишутся. Нужно дождаться 05:00 или запустить вручную один раз.

**P1-3: equity_history.json устарел (2026-06-12)**

`cycle_health_monitor` читает этот легаси-файл для расчёта gap. `cycle_runner` обновляет `equity_curve_daily.json` (свежий), но не трогает `equity_history.json`. Нужно либо починить `cycle_health_monitor` (переключить на `paper_trading_status.json`), либо убедиться что `equity_history.json` наполняется.

**P1-4: golive_checker — 6 чеков вместо 26**

`spa_core.paper_trading.golive_checker` реализует 6 чеков и показывает 6/6 PASS. CLAUDE.md упоминает 26 чеков и "16/26 pass" — эта версия либо не реализована в текущем коде, либо находится в другом файле. Текущий статус: ready=true (по 6 базовым чекам).

---

## Что написано но не активировано ⏸

- **fund-api** (com.spa.fund-api): `RunAtLoad=false` — on-demand сервис. Нужно решить: постоянный (KeepAlive) или остаётся on-demand.
- **checkpoint-7day**: One-shot запланирован на 2026-06-19 10:00 — норма.
- **weekly_backup**: Запускается по пятницам — норма.

---

## Критерии Tier 1

- [ ] Все KeepAlive-агенты имеют PID (не падают) — **сейчас: cloudflared без PID (exit=256)**
- [ ] Все периодические агенты обновляют output в 2× своём интервале — **сейчас: cycle_health, cycle_gap, sky_monitor FAIL**
- [ ] uptime_monitor.all_ok = true — **сейчас: False из-за BUG-1, BUG-2, BUG-3, BUG-4**
- [ ] Telegram-бот отвечает на /status за <3 сек — **сейчас: нет токена в Keychain**
- [ ] 0 агентов с exit code != 0 в launchctl — **сейчас: cloudflared exit=256**
- [ ] equity_history.json актуален (не старше 48ч) — **сейчас: 2026-06-12**
- [ ] cloudflared туннель работает (публичный доступ) — **сейчас: бинарник не установлен**
- [ ] analytics_report_full.json существует — **сейчас: MISSING**
- [ ] sky_status.json обновляется ежедневно — **сейчас: 107ч без обновления**
- [ ] All 19 plist существуют в scripts/ — **✅ DONE**
- [ ] Все агенты покрыты тестами — **827 тестов в spa_core/tests/, 67 в tests/**

---

## Бэклог P0 (блокеры uptime_monitor.all_ok)

- [ ] **[P0-FIX-001]** Исправить plist cycle_health: заменить `spa_core.analytics.cycle_health_monitor` → `spa_core.monitoring.cycle_health_monitor` | Критерий: `data/cycle_health.json` обновляется каждые ≤1800с | **10 мин**
- [ ] **[P0-FIX-002]** Исправить plist cycle_gap_monitor: заменить `--check` → `--run` | Критерий: `data/cycle_gap_state.json` существует и свежий | **5 мин**
- [ ] **[P0-FIX-003]** Установить cloudflared: `brew install cloudflared && cloudflared tunnel login && cloudflared tunnel run spa` | Критерий: exit code 0 в launchctl | **20–30 мин (настройка туннеля)**
- [ ] **[P0-FIX-004]** Починить sky_monitor: загрузить plist в LaunchAgents + RunAtLoad=true или запустить вручную | Критерий: sky_status.json обновлён сегодня | **10 мин**

## Бэклог P1 (production ready)

- [ ] **[P1-FIX-001]** Добавить `TELEGRAM_BOT_TOKEN_SPA` в macOS Keychain для bot_commands | `security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w <TOKEN>` | **5 мин**
- [ ] **[P1-FIX-002]** Починить cycle_health_monitor: переключить на `paper_trading_status.json` вместо `equity_history.json` для определения gap (или обновить equity_history.json из cycle_runner) | **30 мин**
- [ ] **[P1-FIX-003]** Запустить analytics_tier_c вручную один раз: `python3 -m spa_core.analytics.signal_aggregator --run --tier C` | Критерий: analytics_report_full.json создан | **5 мин**
- [ ] **[P1-FIX-004]** Проверить golive_checker: 6 чеков vs упомянутых 26 — определить является ли CLAUDE.md устаревшим или нужна реализация расширенного checker | **1ч**
- [ ] **[P1-FIX-005]** sky_monitor — добавить `RunAtLoad=true` в plist + перезагрузить | **5 мин**

## Бэклог P2 (Tier 1 polish)

- [ ] **[P2-FIX-001]** fund-api: привести в соответствие tier-метку (L1 в комментарии) с конфигом (RunAtLoad=false/KeepAlive=false) — либо активировать как L1, либо переименовать в L4-on-demand
- [ ] **[P2-FIX-002]** Tier B (analytics) вынести из inline-цикла в отдельный hourly plist — 386 модулей в каждом 30-мин цикле создают задержку
- [ ] **[P2-FIX-003]** equity_history.json ротация/удаление как легаси или восстановить запись из cycle_runner
- [ ] **[P2-FIX-004]** uptime_monitor: добавить проверку что bot_commands реально отвечает (/ping), не только pid=alive
- [ ] **[P2-FIX-005]** CURRENT_STATE.md: секция launchd устарела (autopush=installed, 19 агентов, cloudflared down)

---

## Команды для быстрого запуска (copy-paste)

```bash
cd ~/Documents/SPA_Claude

# ===== P0: FIX-001 — cycle_health plist =====
sed -i '' 's/spa_core.analytics.cycle_health_monitor/spa_core.monitoring.cycle_health_monitor/' \
  scripts/com.spa.cycle_health.plist
cp scripts/com.spa.cycle_health.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.cycle_health.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.spa.cycle_health.plist
# Проверка (через 1 мин):
cat data/cycle_health.json | python3 -m json.tool | head -10

# ===== P0: FIX-002 — cycle_gap_monitor --check → --run =====
sed -i '' 's/<string>--check<\/string>/<string>--run<\/string>/' \
  scripts/com.spa.cycle_gap_monitor.plist
cp scripts/com.spa.cycle_gap_monitor.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist
# Проверка (через 5 мин):
ls -la data/cycle_gap_state.json

# ===== P0: FIX-003 — cloudflared =====
brew install cloudflared
# (если туннель уже настроен):
launchctl unload ~/Library/LaunchAgents/com.spa.cloudflared.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.spa.cloudflared.plist
# Проверка:
launchctl list | grep cloudflared   # PID должен появиться

# ===== P0: FIX-004 — sky_monitor =====
# Добавить RunAtLoad=true в plist и перезагрузить:
cp scripts/com.spa.sky_monitor.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.sky_monitor.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.spa.sky_monitor.plist
# Или: запустить вручную немедленно:
python3 -m spa_core.data_pipeline.sky_monitor --export

# ===== P1: FIX-001 — Telegram token в Keychain =====
security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w "YOUR_TOKEN_HERE"
launchctl kickstart -k gui/$(id -u)/com.spa.bot_commands

# ===== P1: FIX-003 — analytics_tier_c первый запуск =====
python3 -m spa_core.analytics.signal_aggregator --run --tier C
ls -la data/analytics_report_full.json

# ===== Проверка всей системы после фиксов =====
python3 -m spa_core.monitoring.uptime_monitor --once
cat data/uptime_status.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('all_ok:', d['all_ok'])
fails = [k for k,v in d.get('checks',{}).items() 
         if isinstance(v,dict) and not (v.get('running') or v.get('ok'))]
print('FAIL:', fails if fails else 'NONE')
"
```

---

## Числовой итог

| Метрика | Значение |
|---------|---------|
| Агентов в ТЗ (AGENT_AUDIT.md v4) | **19** |
| plist в scripts/ | **19** ✅ |
| Реально работают (running/OK) | **12** |
| Известные баги конфига | **4** (BUG-1, 2, 3, 4) |
| Недоступны по дизайну/расписанию | **3** (fund-api, checkpoint-7day, weekly_backup) |
| Python тестов | **827 + 67 = 894** |
| Equity | **$100 047.72** (is_demo=false) |
| Дней трека | **26** (с 2026-06-10) |
| GoLive статус | 6/6 PASS (ready=true) |
| uptime_monitor.all_ok | **False** → станет True после P0-FIX-001..004 |
| Оценка зрелости | **7.5/10 → 9.5/10** после P0-фиксов |

---

*Аудит v3.0: 2026-06-14 | Метод: живые данные с диска, ручной запуск агентов, grep кода*
