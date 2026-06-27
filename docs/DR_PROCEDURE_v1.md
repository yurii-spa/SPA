> ⚠️ **SUPERSEDED — DO NOT FOLLOW.** This document is **STALE** (references the
> deleted `install_agents.sh`, the retired `com.spa.httpserver`, and pre-rebuild
> assumptions). The **canonical** disaster-recovery procedure is
> **[`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md)** — use that. This file is
> retained for history only.

---

# SPA Disaster Recovery Procedure v1

**Версия:** 1.0  
**Дата:** 2026-06-11  
**Владелец:** Yurii (yuriycooleshov@gmail.com)  
**Задача:** MP-211  
**Целевой RTO:** < 4 часов от момента обнаружения до восстановления

---

## Обзор

SPA работает на Mac mini (локально). Данные резервируются по двум независимым каналам:

| Канал | Что | Частота | Куда |
|-------|-----|---------|------|
| autopush (launchd) | JSON data/, код | каждые 90 мин | GitHub |
| GitHub Pages | Дашборд + snapshots | при каждом push | github.io |
| iCloud / Time Machine | SQLite `data/spa.db`, `data/track.db` | непрерывно (iCloud) | Cloud |

**Важно:** JSON-файлы в `data/` — основной state SPA. GitHub — их golden copy.  
SQLite базы — кэш/аналитика; SPA продолжает работать без них при перезапуске с JSON.

---

## Сценарий A — Mac mini падает / перезагружается

### Симптомы
- SPA недоступен локально
- Dashboard на GitHub Pages устарел (> 2 ч нет обновлений)
- Нет новых коммитов в репо > 2 ч

### Шаги восстановления

```bash
# 1. После перезагрузки: проверить launchd сервисы
launchctl list | grep com.spa

# 2. Если сервисы не загружены — перезагрузить все:
cd ~/Documents/SPA_Claude
launchctl load com.spa.daily_cycle.plist
launchctl load com.spa.autopush.plist
launchctl load com.spa.httpserver.plist
launchctl load com.spa.cloudflared.plist

# Ожидаемый вывод: каждая команда без ошибок
```

```bash
# 3. Проверить что сервисы живы
launchctl list com.spa.autopush     # → должен показать PID
launchctl list com.spa.httpserver   # → должен показать PID

# 4. Запустить цикл вручную (не ждать 08:00)
cd ~/Documents/SPA_Claude
python3 -m spa_core.paper_trading.cycle_runner --verbose

# Ожидаемый вывод: "cycle complete", last_cycle_status: ok
```

```bash
# 5. Проверить gap monitor (нет ли пробела)
python3 -m spa_core.paper_trading.gap_monitor
cat data/gap_monitor.json | python3 -m json.tool | grep -E 'gap|status'

# 6. Запустить uptime monitor
python3 -m spa_core.monitoring.uptime_monitor
# Ожидаемый вывод: "Status: ALL OK ✓"
```

```bash
# 7. Принудительный пуш актуального состояния
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json \
          data/golive_status.json data/gap_monitor.json data/current_positions.json \
  --message "DR-A: post-reboot state sync"
```

**RTO оценка:** 15–30 мин (перезапуск сервисов + 1 цикл).

---

## Сценарий B — Данные повреждены / потеряны

### Симптомы
- `data/*.json` содержат мусор или отсутствуют
- Цикл падает с `json.JSONDecodeError` или `KeyError`
- `data/spa.db` недоступна

### Шаги восстановления

```bash
# 1. Определить масштаб повреждения
ls -la ~/Documents/SPA_Claude/data/*.json | wc -l
python3 -c "import json; json.load(open('data/paper_trading_status.json'))" 2>&1
python3 -c "import json; json.load(open('data/equity_curve_daily.json'))" 2>&1
```

```bash
# 2. Восстановить JSON из GitHub (последний коммит)
cd ~/Documents/SPA_Claude
git fetch origin
git status  # посмотреть что повреждено

# Восстановить конкретные файлы:
git checkout origin/main -- data/paper_trading_status.json
git checkout origin/main -- data/equity_curve_daily.json
git checkout origin/main -- data/current_positions.json
git checkout origin/main -- data/trades.json
git checkout origin/main -- data/golive_status.json
git checkout origin/main -- data/gap_monitor.json
```

```bash
# 3. Если нужно восстановить ВСЕ data/:
git checkout origin/main -- data/

# Проверить восстановленные файлы:
python3 -c "import json; d=json.load(open('data/paper_trading_status.json')); print('equity:', d.get('current_equity'), 'ts:', d.get('last_cycle_ts'))"
```

```bash
# 4. Восстановить SQLite из бэкапа (если data/spa.db повреждена)
ls -la data/backups/
ls -la ~/Library/Mobile\ Documents/com~apple~CloudDocs/SPA_backups/ 2>/dev/null

# Скопировать последний бэкап:
cp data/backups/spa_backup_latest.db data/spa.db 2>/dev/null || \
cp ~/Library/Mobile\ Documents/com~apple~CloudDocs/SPA_backups/spa_latest.db data/spa.db 2>/dev/null || \
echo "Бэкап не найден — SPA работает на JSON, SQLite не критична"
```

```bash
# 5. Запустить цикл и проверить
python3 -m spa_core.paper_trading.cycle_runner --verbose
python3 -m spa_core.monitoring.uptime_monitor
```

**RTO оценка:** 30–60 мин (git restore + 1 цикл).

---

## Сценарий C — GitHub недоступен

### Симптомы
- `push_to_github.py` возвращает ошибку HTTP 50x
- autopush пишет ошибки в лог
- GitHub Pages не обновляется

### Шаги восстановления

```bash
# 1. Проверить доступность GitHub
curl -I https://api.github.com 2>&1 | head -3
curl -I https://github.com 2>&1 | head -3
```

```bash
# 2. Проверить статус GitHub:
# https://www.githubstatus.com/
```

```bash
# 3. SPA продолжает работать локально — цикл НЕ ЗАВИСИТ от GitHub.
# Данные накапливаются локально. Запустить цикл нормально:
python3 -m spa_core.paper_trading.cycle_runner --verbose
```

```bash
# 4. Когда GitHub восстановится — разовый пуш всего накопленного:
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json \
          data/current_positions.json data/trades.json \
          data/golive_status.json data/gap_monitor.json \
  --message "DR-C: batch push after GitHub outage"
```

```bash
# 5. Проверить PAT (мог истечь)
security find-generic-password -s GITHUB_PAT_SPA -w 2>&1 | head -c 20
# Если 404/401 — ротировать PAT: docs/TOKEN_ROTATION_RUNBOOK.md
```

**RTO оценка:** 0 мин (SPA работает без GitHub); накопленные данные пушатся после восстановления.

---

## Сценарий D — Cloudflare tunnel упал

### Симптомы
- Dashboard недоступен по внешнему URL (cloudflare tunnel)
- `launchctl list com.spa.cloudflared` не показывает PID
- Локальный `http://localhost:8765` работает

### Шаги восстановления

```bash
# 1. Проверить статус tunnel
launchctl list com.spa.cloudflared
curl -s http://localhost:8765/health

# 2. Перезапустить cloudflared
launchctl unload ~/Documents/SPA_Claude/com.spa.cloudflared.plist
launchctl load ~/Documents/SPA_Claude/com.spa.cloudflared.plist

# 3. Проверить
launchctl list com.spa.cloudflared   # → PID должен появиться
sleep 5
curl -s http://localhost:8765/health  # локально должен работать
```

```bash
# 4. Если cloudflared binary отсутствует:
which cloudflared || echo "нужна установка"
# Установить: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# 5. Альтернатива: Dashboard доступен через GitHub Pages
echo "GitHub Pages: https://yurii-spa.github.io/SPA/"
# (данные = последний autopush, возможно устарел на 90 мин)
```

**RTO оценка:** 5–15 мин (перезапуск daemon).  
**Примечание:** Cloudflare tunnel — только для внешнего доступа к дашборду. SPA торгует без него.

---

## Контрольный список восстановления (≤ 15 пунктов)

Использовать после любого DR-события. Отметить каждый пункт:

| # | Проверка | Команда | Ожидаемый результат |
|---|----------|---------|---------------------|
| 1 | Launchd autopush жив | `launchctl list com.spa.autopush` | PID > 0 |
| 2 | Launchd httpserver жив | `launchctl list com.spa.httpserver` | PID > 0 |
| 3 | HTTP-сервер отвечает | `curl -s http://localhost:8765/health` | HTTP 200 |
| 4 | Цикл завершился успешно | `python3 -m spa_core.paper_trading.cycle_runner --verbose` | `cycle complete` |
| 5 | paper_trading_status актуален | `python3 -c "import json; d=json.load(open('data/paper_trading_status.json')); print(d['last_cycle_status'], d['last_cycle_ts'])"` | `ok`, timestamp свежий |
| 6 | Нет пробелов в gap monitor | `python3 -m spa_core.paper_trading.gap_monitor` | `no gaps` |
| 7 | Golive checker без новых блокеров | `python3 -m spa_core.paper_trading.golive_checker` | статус без регрессии |
| 8 | Equity curve в порядке | `python3 -c "import json; c=json.load(open('data/equity_curve_daily.json')); print(len(c), c[-1].get('equity') if c else 'empty')"` | > 0 записей |
| 9 | Uptime monitor всё OK | `python3 -m spa_core.monitoring.uptime_monitor` | `Status: ALL OK ✓` |
| 10 | Данные запушены на GitHub | `git -C ~/Documents/SPA_Claude log -1 --format="%ci %s"` | коммит < 3 ч назад |
| 11 | GitHub Pages обновился | `curl -s https://yurii-spa.github.io/SPA/ \| grep -c "SPA"` | > 0 |
| 12 | Kill switch неактивен | `python3 -c "import json; d=json.load(open('data/kill_switch_status.json')); print(d.get('active'))"` | `False` |
| 13 | RiskPolicy не блокирует | `cat data/risk_policy_blocks.json \| python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d), 'blocks')"` | 0 новых блокировок |
| 14 | Инцидент задокументирован | добавить в `data/incidents.json` | запись создана |
| 15 | Postmortem записан | см. `docs/PLAYBOOK_v1.md §7` | готово |

---

## Backup Strategy

```
SPA Data Backup Architecture
═══════════════════════════════════════════════════════════════

  Mac mini (primary)
  ├── ~/Documents/SPA_Claude/data/*.json   ← live state
  ├── ~/Documents/SPA_Claude/data/spa.db   ← SQLite (analytics)
  │
  ├── ──► GitHub (com.spa.autopush, 90 мин)
  │        └── github.com/yurii-spa/SPA/data/
  │             └── GitHub Pages: yurii-spa.github.io/SPA/
  │
  └── ──► iCloud Drive (автоматически, если папка в iCloud)
           └── Дополнительная копия spa.db

Recovery priority:
  1. GitHub → git checkout origin/main -- data/
  2. iCloud  → ~/Library/Mobile Documents/...
  3. Time Machine (если настроен)
```

---

## Временная шкала RTO

```
T+0h  Обнаружение (uptime_monitor / alert)
T+0.5h Triage + начало диагностики
T+1h  Применены шаги восстановления
T+2h  Цикл запущен и работает
T+3h  Данные запушены, dashboard обновлён
T+4h  ← RTO SLA: все сервисы подтверждены OK
```

---

*Версия 1.0 — MP-211, 2026-06-11*
