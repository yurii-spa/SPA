# SPA Incident Response Playbook v1

**Версия:** 1.0  
**Дата:** 2026-06-11  
**Владелец:** Yurii (yuriycooleshov@gmail.com)  
**Задача:** MP-211

---

## 1. Severity Levels

| Уровень | Название | Определение | Время реакции |
|---------|----------|-------------|---------------|
| **P1** | Critical | Потеря данных / остановка цикла / финансовый риск | < 30 мин |
| **P2** | High | Деградация сервиса > 1 ч, autopush не работает | < 2 ч |
| **P3** | Medium | Dashboard stale, единичный timeout адаптера | < 8 ч |

---

## 2. Система обнаружения

### 2.1 Автоматические проверки
```bash
# Uptime monitor — запустить вручную:
python3 -m spa_core.monitoring.uptime_monitor

# Go-live checker:
python3 -m spa_core.paper_trading.golive_checker

# Gap monitor:
python3 -m spa_core.paper_trading.gap_monitor
```

### 2.2 Логи
```bash
# Основной цикл:
tail -100 /tmp/spa_cycle.log
tail -100 /tmp/spa_cycle_err.log

# Launchd логи (macOS):
tail -100 ~/Library/Logs/spa_autopush.log  2>/dev/null || echo "нет файла"
tail -100 ~/Library/Logs/spa_httpserver.log 2>/dev/null || echo "нет файла"

# Системный лог launchd:
log show --predicate 'subsystem == "com.spa"' --last 1h
```

### 2.3 Статус сервисов
```bash
launchctl list | grep com.spa
launchctl list com.spa.autopush
launchctl list com.spa.daily_cycle
launchctl list com.spa.httpserver
launchctl list com.spa.cloudflared
```

---

## 3. P1 — Critical

### P1-A: Цикл не работал > 2 ч

**Симптомы:**
- `uptime_monitor`: `cycle_freshness.ok = false`
- В `data/paper_trading_status.json`: `last_cycle_ts` старше 2 ч
- `data/gap_monitor.json`: присутствует пробел

**Диагностика:**
```bash
# 1. Проверить статус launchd
launchctl list com.spa.daily_cycle

# 2. Последний запуск цикла
python3 -c "import json; d=json.load(open('data/paper_trading_status.json')); print(d.get('last_cycle_ts'), d.get('last_cycle_status'))"

# 3. Логи ошибок
tail -100 /tmp/spa_cycle_err.log
tail -100 /tmp/spa_cycle.log | grep -E 'ERROR|CRITICAL|Traceback'

# 4. Gap monitor
python3 -m spa_core.paper_trading.gap_monitor
cat data/gap_monitor.json | python3 -m json.tool
```

**Ответ:**
```bash
# 5. Запустить цикл вручную
cd ~/Documents/SPA_Claude
python3 -m spa_core.paper_trading.cycle_runner --verbose

# 6. Если запустился — перезарегистрировать launchd
launchctl unload ~/Documents/SPA_Claude/com.spa.daily_cycle.plist 2>/dev/null
launchctl load ~/Documents/SPA_Claude/com.spa.daily_cycle.plist

# 7. Проверить результат
cat data/paper_trading_status.json | python3 -m json.tool | grep last_cycle
python3 -m spa_core.paper_trading.gap_monitor
```

**Восстановление подтверждено:** `last_cycle_status: "ok"` + gap_monitor без новых пробелов.

---

### P1-B: Drawdown > 5% / Kill-switch активирован

**Симптомы:**
- `data/kill_switch_status.json`: `active: true`
- `data/paper_trading_status.json`: `total_return_pct < -0.05`
- `data/risk_policy_blocks.json`: записи с `reason: "drawdown"`

**Диагностика:**
```bash
# 1. Kill switch
cat data/kill_switch_status.json | python3 -m json.tool

# 2. Equity curve
cat data/equity_curve_daily.json | python3 -c "
import json,sys
curve=json.load(sys.stdin)
last5=curve[-5:] if len(curve)>=5 else curve
for e in last5: print(e.get('date'), e.get('equity'))
"

# 3. Блокировки RiskPolicy
cat data/risk_policy_blocks.json | python3 -m json.tool | head -60

# 4. Позиции
cat data/current_positions.json | python3 -m json.tool
```

**Ответ:**  
⚠️ **НИКАКИХ автоматических действий с капиталом без ручного подтверждения.**

```bash
# Анализ причины drawdown:
python3 -m spa_core.paper_trading.cycle_runner --verbose 2>&1 | grep -E 'risk|drawdown|block'

# Просмотр последних трейдов:
cat data/trades.json | python3 -c "
import json,sys
trades=json.load(sys.stdin)
for t in trades[-5:]: print(t.get('ts'), t.get('action'), t.get('protocol'), t.get('amount_usd'))
"
```

**Эскалация:** немедленно уведомить владельца (yuriycooleshov@gmail.com), не снимать kill-switch без ручного review.

---

## 4. P2 — High

### P2-A: Feed недоступен > 1 ч

**Симптомы:**
- Цикл завершается с `"num_adapters_live": 0` или очень маленьким числом
- `data/adapter_status.json`: несколько адаптеров `status: "error"`

**Диагностика:**
```bash
# 1. Статус адаптеров
cat data/adapter_status.json | python3 -m json.tool

# 2. Проверить DeFiLlama напрямую
curl -s "https://yields.llama.fi/pools" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'pools: {len(d.get(\"data\",[]))}')"

# 3. Проверить сетевой доступ
curl -I https://yields.llama.fi/ 2>&1 | head -5

# 4. Логи адаптера
grep -E 'defillama|feed|adapter' /tmp/spa_cycle.log | tail -30
```

**Ответ:**
```bash
# Перезапустить цикл (адаптеры — read-only, безопасно):
python3 -m spa_core.paper_trading.cycle_runner --verbose

# Если DeFiLlama недоступен — cycle_runner использует кэш (TTL 300 с).
# Ждать восстановления сети, цикл самовосстановится.
```

---

### P2-B: Autopush не работал > 3 ч

**Симптомы:**
- `uptime_monitor`: `git_push.ok = false` (stale_hours > 3)
- `data/uptime_status.json`: `checks.git_push.stale_hours > 3`

**Диагностика:**
```bash
# 1. Статус launchd
launchctl list com.spa.autopush

# 2. Последний коммит
git -C ~/Documents/SPA_Claude log -3 --oneline --format="%ci %s"

# 3. Проверить PAT
security find-generic-password -s GITHUB_PAT_SPA -w 2>&1 | head -c 10

# 4. Тест пуша вручную
cd ~/Documents/SPA_Claude && python3 push_to_github.py --dry-run --files data/paper_trading_status.json --message "test"
```

**Ответ:**
```bash
# Ручной пуш данных:
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json data/golive_status.json \
  --message "P2 manual push: autopush recovery"

# Перезапустить autopush:
launchctl unload ~/Documents/SPA_Claude/com.spa.autopush.plist
launchctl load ~/Documents/SPA_Claude/com.spa.autopush.plist
launchctl list com.spa.autopush
```

**PAT ротация (если токен протух):**
```bash
# 1. Создать новый PAT на github.com/settings/tokens
# 2. Сохранить в Keychain:
bash ~/Documents/SPA_Claude/setup_pat.sh
# 3. Проверить:
security find-generic-password -s GITHUB_PAT_SPA -w
```
См. `docs/TOKEN_ROTATION_RUNBOOK.md`.

---

### P2-C: Adapter degraded > 3 ч

**Симптомы:**
- `data/adapter_status.json`: конкретный адаптер `status: "error"` длительно
- В позициях нет обновлений по этому протоколу

**Диагностика:**
```bash
# Состояние адаптеров
cat data/adapter_status.json | python3 -m json.tool

# Проверить on-chain endpoint вручную (пример Aave V3):
curl -s "https://yields.llama.fi/pools" | python3 -c "
import json,sys
pools=json.load(sys.stdin)['data']
aave=[p for p in pools if 'aave' in p.get('project','').lower() and p.get('symbol')=='USDC']
for p in aave[:3]: print(p.get('project'), p.get('apy'), p.get('tvlUsd'))
"
```

**Ответ:**  
Деградация одного T2-адаптера — не блокирует цикл. Система продолжает работать с оставшимися протоколами.  
Если деградирует T1 (Aave/Compound) — мониторить каждые 30 мин. При восстановлении endpoint адаптер подхватится автоматически при следующем цикле.

---

## 5. P3 — Medium

### P3-A: Dashboard stale

**Симптомы:**
- `https://yurii-spa.github.io/SPA/` показывает старые данные
- Autopush не пушил > 90 мин

**Диагностика и ответ:**
```bash
# Принудительный пуш дашборда:
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files index.html data/paper_trading_status.json data/equity_curve_daily.json \
  --message "P3 force-push: dashboard refresh"

# GitHub Pages обновляется через ~1-2 мин после пуша.
```

---

### P3-B: Single adapter timeout

**Симптомы:**
- Один адаптер отвечает медленно / с ошибкой в единичном цикле
- Остальные работают нормально

**Ответ:** Наблюдать. Если повторяется 3+ цикла подряд — поднимать до P2-C.

---

### P3-C: Git push stale (< 6 ч)

**Симптомы:**
- `git_push.stale_hours` между 3 и 6

**Ответ:**
```bash
launchctl list com.spa.autopush   # убедиться что жив
# Если мёртв — перезагрузить (см. P2-B)
```

---

## 6. Общий процесс (Detection → Resolution)

```
Обнаружение (uptime_monitor / логи)
    │
    ▼
Triage: определить severity (P1/P2/P3)
    │
    ▼
Диагностика: выполнить команды из секции выше
    │
    ▼
Response: применить конкретные шаги восстановления
    │
    ▼
Resolution: подтвердить что сервис работает:
    python3 -m spa_core.monitoring.uptime_monitor  → all_ok: true
    │
    ▼
Postmortem (для P1/P2): записать в data/incidents.json
```

---

## 7. Postmortem Template

После каждого P1/P2 инцидента — добавить запись в `data/incidents.json`:

```json
{
  "id": "INC-YYYYMMDD-001",
  "severity": "P1",
  "detected_at": "2026-06-11T10:00:00Z",
  "resolved_at": "2026-06-11T10:45:00Z",
  "duration_min": 45,
  "title": "Цикл не запустился",
  "root_cause": "launchd выгрузился после перезагрузки",
  "impact": "1 пропущенный цикл, gap в equity curve",
  "resolution": "перезагрузил plist, цикл запустился вручную",
  "prevention": "добавить RunAtLoad=true в plist"
}
```

---

## 8. Контакты и ссылки

| Ресурс | Адрес |
|--------|-------|
| Владелец | yuriycooleshov@gmail.com |
| Dashboard | https://yurii-spa.github.io/SPA/ |
| GitHub репо | https://github.com/yurii-spa/SPA |
| Локальный сервер | http://localhost:8765 |
| DR Procedure | `docs/DR_PROCEDURE_v1.md` |
| Token Rotation | `docs/TOKEN_ROTATION_RUNBOOK.md` |

---

*Версия 1.0 — MP-211, 2026-06-11*
