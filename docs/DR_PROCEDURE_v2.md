> ⚠️ **SUPERSEDED — DO NOT FOLLOW for infra recovery.** The infrastructure
> sections of this document are **STALE** (retired `com.spa.httpserver`, the
> deleted `install_agents.sh`, pre-login-domain reboot assumptions). The
> **canonical** disaster-recovery procedure is
> **[`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md)** — use that.
> (The fund-level / investor-exit material in §7–8 here is not yet folded into
> the canonical doc and remains a historical reference only.)

---

# SPA Disaster Recovery Procedure v2

**Версия:** 2.0  
**Дата:** 2026-06-12  
**Владелец:** Yurii (yuriycooleshov@gmail.com)  
**Предыдущая версия:** DR_PROCEDURE_v1.md (MP-211)  
**Задача:** MP-362  
**Целевой RTO:** L1 ≤ 30 мин | L2 ≤ 1 час | L3 ≤ 4 часа  

> ⚠️ **Ключевое правило:** `approved=False` от RiskPolicy не может быть переопределён.  
> Kill switch, активированный автоматически — не сбрасывается без расследования.

---

## 1. Обзор

DR v2 охватывает **пять классов инцидентов**:

| Класс | Пример | Уровень |
|-------|--------|---------|
| Инфраструктура | цикл не запустился, launchd упал | L1 / L2 |
| Kill switch | drawdown ≥ 5%, позиции закрыты | L2 |
| Алертинг | Telegram молчит > 24ч | L2 |
| Данные | JSON corrupted, equity curve пуста | L3 |
| Fund-level | инвестор хочет выйти, конфликт подписантов | L3 |

Инфраструктура SPA: Mac mini (local launchd) → GitHub (autopush каждые 90 мин) → iCloud / Time Machine (SQLite). JSON-файлы в `data/` — основной state; GitHub — их golden copy.

**Что НЕ остановит торговлю SPA:**
- кратковременный сбой GitHub (пуши накапливаются, цикл работает)
- недоступность Cloudflare tunnel (дашборд отваливается, торговля продолжается)
- падение SQLite (analytics-кэш, не критично)

---

## 2. Уровни инцидентов

### L1 — Самовосстанавливается (≤ 30 мин)

Цикл пропустил один запуск. Launchd перезагрузится сам при следующем cron-триггере (08:00). Gap monitor фиксирует пробел, но gap ≤ 1 → предупреждение, не блок.

**Критерий:** пропуск ≤ 1 цикла, equity cursor продолжит работу следующим днём, статус gap_monitor — `minor_gap`.

**Действие:** проверить логи, запустить цикл вручную, убедиться что gap закрыт.

### L2 — Ручное вмешательство (≤ 1 час)

Kill switch сработал; Telegram молчит; autopush не пушит > 3 ч; цикл падает с ошибкой повторно.

**Критерий:** инцидент требует диагностики и ручного действия, но фонд продолжает существовать.

**Действие:** разделы 4–6 ниже.

### L3 — Остановка фонда (> 4 часов)

JSON state corrupted, equity curve неверна; весь Mac mini вышел из строя (требуется восстановление на новой машине); fund-level конфликт (инвестор, регулятор, утечка ключей).

**Критерий:** SPA не может корректно продолжить цикл без восстановления данных или немедленного ручного разбора ситуации с инвесторами.

**Действие:** разделы 7–8 ниже.

---

## 3. L1: Цикл не запустился

### Симптомы
- `data/paper_trading_status.json` — `last_cycle_ts` старше 25 часов
- Нет новых коммитов в репо > 26 ч
- `data/gap_monitor.json` сигнализирует о пробеле

### Диагностика

```bash
# Проверить что launchd-сервисы живы
launchctl list | grep com.spa

# Посмотреть лог последнего запуска цикла
tail -50 /tmp/spa_cycle.log
tail -20 /tmp/spa_cycle_err.log

# Статус всех сервисов SPA
launchctl list com.spa.daily_cycle
launchctl list com.spa.autopush
launchctl list com.spa.httpserver
launchctl list com.spa.cloudflared
```

### Восстановление

```bash
# 1. Если сервис выгружен — перезагрузить
cd ~/Documents/SPA_Claude
launchctl load com.spa.daily_cycle.plist
launchctl load com.spa.autopush.plist

# 2. Запустить цикл вручную (не ждать 08:00)
python3 -m spa_core.paper_trading.cycle_runner --verbose

# Ожидаемый вывод: "cycle complete", last_cycle_status: ok
```

```bash
# 3. Проверить gap monitor
python3 -m spa_core.paper_trading.gap_monitor
cat data/gap_monitor.json | python3 -m json.tool | grep -E "gap|status|consecutive"

# 4. Синхронизировать с GitHub
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json \
          data/golive_status.json data/gap_monitor.json \
  --message "DR-L1: manual cycle after launchd recovery"
```

**RTO оценка:** 15–30 мин.

---

## 4. L2: Kill switch активирован

Kill switch срабатывает при **drawdown портфеля ≥ 5%**. После срабатывания все позиции закрыты, новые ребалансы заблокированы до ручного сброса.

### Симптомы
- `data/kill_switch_status.json` → `"active": true`
- `data/risk_policy_blocks.json` содержит запись с `"trigger": "kill_switch"`
- Цикл завершается без ребаланса, пишет в лог `"kill_switch active — rebalance skipped"`

### Диагностика

```bash
# 1. Проверить статус kill switch
python3 -c "
import json
d = json.load(open('data/kill_switch_status.json'))
print('active:', d.get('active'))
print('reason:', d.get('reason'))
print('triggered_at:', d.get('triggered_at'))
print('drawdown:', d.get('drawdown_pct'))
"

# 2. Проверить equity curve — понять где просадка
python3 -c "
import json
bars = json.load(open('data/equity_curve_daily.json')).get('daily', [])
for b in bars[-7:]:
    print(b.get('date'), b.get('equity'), 'drawdown:', b.get('drawdown_pct'))
"

# 3. Посмотреть блокировки RiskPolicy
cat data/risk_policy_blocks.json | python3 -m json.tool | head -40
```

### Расследование (обязательно перед сбросом)

1. Найти причину drawdown: адаптер вернул некорректные данные? APY-feed anomaly? Реальная просадка протокола?
2. Проверить `data/apy_feed_anomaly_health_state.json` и `data/apy_feed_bounds_health_state.json`
3. Проверить `data/adapter_orchestrator_status.json` на ошибки
4. Убедиться что equity curve данные корректны (не ошибка учёта)

### Сброс (только после расследования)

```bash
# Сброс kill switch — только если причина устранена / ложная тревога
python3 -c "
import json, os, pathlib
ks = pathlib.Path('data/kill_switch_status.json')
d = json.load(open(ks))
d['active'] = False
d['reset_reason'] = 'DR-L2: расследование завершено, причина устранена'
d['reset_at'] = __import__('datetime').datetime.utcnow().isoformat() + 'Z'
tmp = ks.with_suffix('.json.tmp')
json.dump(d, open(tmp, 'w'), indent=2, ensure_ascii=False)
os.replace(tmp, ks)
print('Kill switch сброшен')
"

# Запустить цикл
python3 -m spa_core.paper_trading.cycle_runner --verbose
```

> ⚠️ **Если drawdown был реальным** — не сбрасывать до письменного анализа причины в `docs/ADR_013_incident_history.md`.

**RTO оценка:** 30–60 мин (расследование + сброс + 1 цикл).

---

## 5. L2: Telegram молчит

Telegram-бот — единственный канал алертов (ежедневный отчёт цикла, критические уведомления). Молчание > 24 ч при работающем цикле — инцидент L2.

### Симптомы
- Ежедневный отчёт не пришёл в запланированное время
- `data/alert_log.json` показывает `"telegram_ok": false`
- Ошибки в логе: `"TelegramError: 401 Unauthorized"` или `"ConnectionError"`

### Диагностика

```bash
# 1. Проверить лог алертов
cat data/alert_log.json | python3 -m json.tool | grep -A3 "telegram" | head -20

# 2. Проверить что токен существует в Keychain
security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w 2>&1 | head -c 20

# 3. Тест-пинг бота (заменить <TOKEN> и <CHAT_ID> актуальными значениями)
# Токен берётся из Keychain, не из файлов!
TOKEN=$(security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w)
CHAT_ID=$(security find-generic-password -s TELEGRAM_CHAT_ID_SPA -w)
curl -s "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}&text=SPA+DR+ping+test"
```

### Восстановление

**Вариант A — токен истёк:**
```bash
# Ротировать токен через @BotFather в Telegram:
# 1. Отправить /token боту @BotFather
# 2. Выбрать бота SPA
# 3. Получить новый токен
# 4. Записать в Keychain (НЕ в файлы!):
security add-generic-password -U -s TELEGRAM_BOT_TOKEN_SPA -a spa -w "NEW_TOKEN_HERE"
```

**Вариант B — сеть недоступна (временно):**
```bash
# Проверить доступность Telegram API
curl -I https://api.telegram.org 2>&1 | head -3
# Если недоступен — ждать восстановления, алерты накопятся и отправятся
```

**Fallback — email:**
```bash
# Если Telegram недоступен длительно — отправить себе email
python3 -c "
import smtplib, ssl
from email.mime.text import MIMEText
# Реквизиты берутся из Keychain, не хардкодятся
print('Отправить email вручную: yuriycooleshov@gmail.com')
print('Тема: [SPA ALERT] Telegram недоступен — ручной мониторинг')
"
# Открыть дашборд напрямую: http://localhost:8765
```

**RTO оценка:** 15–30 мин (ротация токена) | 0 мин (временный сбой сети — ждать).

---

## 6. L3: Corrupted JSON state

### Симптомы
- Цикл падает с `json.JSONDecodeError` или `KeyError: 'daily'`
- `data/equity_curve_daily.json` пуста или содержит мусор
- `data/current_positions.json` — отсутствует или повреждён

### Диагностика

```bash
# Проверить целостность ключевых файлов
for f in equity_curve_daily paper_trading_status current_positions trades golive_status gap_monitor; do
  python3 -c "import json; json.load(open('data/${f}.json')); print('OK: ${f}.json')" 2>&1
done

# Посмотреть .backup файлы (атомарные записи оставляют .backup при ошибке)
ls -la data/*.json.backup 2>/dev/null || echo "нет .backup файлов"
ls -la data/*.json.tmp 2>/dev/null    || echo "нет .tmp файлов"
```

### Восстановление из GitHub (приоритет 1)

```bash
cd ~/Documents/SPA_Claude

# Получить последний коммит
git fetch origin

# Посмотреть что изменилось vs GitHub
git diff origin/main -- data/ | head -50

# Восстановить повреждённые файлы из GitHub golden copy
git checkout origin/main -- data/equity_curve_daily.json
git checkout origin/main -- data/paper_trading_status.json
git checkout origin/main -- data/current_positions.json
git checkout origin/main -- data/trades.json
git checkout origin/main -- data/golive_status.json
git checkout origin/main -- data/gap_monitor.json

# Если нужно восстановить весь data/:
# git checkout origin/main -- data/
```

### Восстановление из .backup (приоритет 2)

```bash
# Если GitHub тоже устарел (autopush лежит > 90 мин) — использовать .backup
for f in data/*.json.backup; do
  target="${f%.backup}"
  echo "Восстанавливаю: $target из $f"
  cp "$f" "$target"
done
```

### Восстановление из iCloud (приоритет 3)

```bash
ls -la ~/Library/Mobile\ Documents/com~apple~CloudDocs/SPA_backups/ 2>/dev/null
# Скопировать нужные файлы вручную
```

### После восстановления

```bash
# 1. Проверить целостность восстановленных файлов
for f in equity_curve_daily paper_trading_status current_positions trades; do
  python3 -c "import json; d=json.load(open('data/${f}.json')); print('OK:', '${f}', list(d.keys())[:3])"
done

# 2. Запустить цикл
python3 -m spa_core.paper_trading.cycle_runner --verbose

# 3. Проверить gap monitor (пробел из-за downtime)
python3 -m spa_core.paper_trading.gap_monitor

# 4. Запустить data integrity check
python3 -m spa_core.audit.data_integrity

# 5. Синхронизировать с GitHub
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json \
          data/current_positions.json data/trades.json data/golive_status.json \
          data/gap_monitor.json \
  --message "DR-L3: state restored from backup"
```

**RTO оценка:** 30–90 мин (диагностика + git restore + цикл + верификация).

---

## 7. Fund-level: Инвестор хочет выйти

### Применимое право

ДПТ (Договір простого товариства, Глава 77 ЦКУ, ст. 1132–1143).  
Шаблон: `docs/legal/DOGOVIR_PROSTOGO_TOVARYSTVA_TEMPLATE.md`  
Onboarding: `docs/legal/ONBOARDING_CHECKLIST.md`

> ⚠️ **Не является юридической консультацией.** При спорах — обращаться к юристу.

### Стандартная процедура выхода (30-дневный notice)

**День 0 — Получение уведомления:**
- Инвестор направляет письменное уведомление о выходе (email / Telegram)
- Зафиксировать дату получения — это день T+0 для 30-дневного notice
- Ответить подтверждением получения в течение 24 часов

**День 1–3 — Расчёт доли:**
```bash
# Посмотреть текущие позиции и equity
python3 -c "
import json
pos = json.load(open('data/current_positions.json'))
status = json.load(open('data/paper_trading_status.json'))
print('Текущий equity:', status.get('current_equity'))
print('Позиции:', json.dumps(pos, indent=2, ensure_ascii=False))
"

# Посмотреть список инвесторов и их доли (если файл существует)
python3 -c "
import json, pathlib
p = pathlib.Path('data/investors.json')
if p.exists():
    d = json.load(open(p))
    print(json.dumps(d, indent=2, ensure_ascii=False))
else:
    print('data/investors.json не существует — доли в ДПТ')
"
```

**Pro-rata расчёт:**
```python
# Формула расчёта выплаты
# share_pct — доля инвестора согласно ДПТ (в %)
# current_equity — текущий equity фонда

current_equity = <из paper_trading_status.json>
share_pct = <из ДПТ / investors.json>
gross_payout = current_equity * (share_pct / 100)

# Учесть unrealized P&L позиций (все позиции ликвидны — DeFi lending)
# Вычесть комиссию управляющего согласно ДПТ, если применимо
net_payout = gross_payout  # уточнить по условиям ДПТ

print(f"Выплата инвестору: ${net_payout:,.2f} USDC")
```

**День 30 — Фактический выход:**
1. Уменьшить позиции пропорционально доле инвестора (виртуально в paper mode)
2. Обновить `data/investors.json` атомарной записью (tmp + os.replace)
3. Зафиксировать выход в `data/trades.json` как виртуальный redemption-трейд
4. Обновить `data/current_positions.json` с новым equity
5. Направить инвестору финальный отчёт (equity curve за период, итоговая доходность)
6. Запушить обновлённые файлы на GitHub

### Обновление investors.json

```python
# Атомарное обновление — всегда tmp + os.replace
import json, os, pathlib, datetime

investors_path = pathlib.Path("data/investors.json")

# Перечитать с диска перед записью (конкурентный процесс!)
if investors_path.exists():
    with open(investors_path) as f:
        doc = json.load(f)
else:
    doc = {"investors": [], "last_updated": None}

# Обновить запись инвестора
for inv in doc["investors"]:
    if inv["id"] == "<INVESTOR_ID>":
        inv["status"] = "exited"
        inv["exit_date"] = datetime.date.today().isoformat()
        inv["exit_equity_usd"] = <net_payout>

doc["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"

# Атомарная запись
tmp = investors_path.with_suffix(".json.tmp")
with open(tmp, "w") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)
os.replace(tmp, investors_path)
```

### Досрочный выход (до истечения 30 дней)

По условиям ДПТ досрочный выход возможен только по взаимному согласию управляющего. Процедура та же, но дата T+30 заменяется согласованной датой.

### Конфликт подписантов Gnosis Safe

Если управляющий (Yurii) недоступен и требуется операция с Gnosis Safe:

1. Собрать 2 из 3 подписантов (см. раздел 8 «Контакты»)
2. Выполнить транзакцию через Gnosis Safe UI с порогом 2-of-3
3. Задокументировать в `docs/ADR_013_incident_history.md`

---

## 8. Контакты

| Роль | Контакт | Канал |
|------|---------|-------|
| Управляющий (Owner) | Yurii Kulieshov | Telegram: @yuriikulieshov · yuriycooleshov@gmail.com |
| Gnosis Safe signer #2 | TBD | TBD |
| Gnosis Safe signer #3 | TBD | TBD |

**Gnosis Safe:** требует 2-of-3 подписей для операций с реальным капиталом (актуально после go-live).  
**В paper mode:** все операции виртуальные, Gnosis Safe не задействован.

**Эскалация L3:**
1. Yurii (основной) — 24/7 доступ
2. Если Yurii недоступен > 4 ч и требуется экстренное действие → Gnosis Safe 2-of-3

---

## 9. Ежеквартальный DR Drill

**Цель:** убедиться что процедуры работают и команда знакома с ними.

**Расписание:** раз в квартал (ближайший — конец Q3 2026).

**Инструмент:**

```bash
# Запустить kill switch drill (уже существует)
cd ~/Documents/SPA_Claude
python3 spa_core/golive/kill_switch_drill.py
# Документация: docs/kill_switch_drill.md
```

**Чеклист drill:**

| # | Действие | Ожидаемый результат |
|---|----------|---------------------|
| 1 | Запустить kill_switch_drill.py | drill завершён, kill_switch.active=False после сброса |
| 2 | Симулировать отсутствие цикла (остановить launchd) | gap_monitor фиксирует пробел |
| 3 | Восстановить из git restore | equity curve целая после checkout |
| 4 | Проверить data_integrity | все чеки OK |
| 5 | Проверить Telegram алерт | пришёл тестовый /ping |
| 6 | Запушить результаты drill | коммит с пометкой "DR-DRILL" |

**После drill:** добавить запись в `docs/ADR_013_incident_history.md` с датой, результатами и найденными проблемами.

---

## 10. Контрольный список восстановления (post-incident)

После любого DR-события пройти полный чеклист:

```bash
# Скрипт быстрой проверки (запустить после восстановления)
cd ~/Documents/SPA_Claude

echo "=== 1. launchd ==="
launchctl list | grep com.spa

echo "=== 2. HTTP server ==="
curl -s http://localhost:8765/health 2>&1 | head -3

echo "=== 3. Цикл ==="
python3 -m spa_core.paper_trading.cycle_runner --verbose 2>&1 | tail -5

echo "=== 4. Gap monitor ==="
python3 -m spa_core.paper_trading.gap_monitor 2>&1 | tail -3

echo "=== 5. GoLive checker ==="
python3 -m spa_core.paper_trading.golive_checker 2>&1 | tail -5

echo "=== 6. Kill switch ==="
python3 -c "import json; d=json.load(open('data/kill_switch_status.json')); print('active:', d.get('active'))" 2>&1

echo "=== 7. Data integrity ==="
python3 -m spa_core.audit.data_integrity 2>&1 | python3 -c "
import json, sys
d = json.load(sys.stdin)
for c in d.get('checks', []):
    print(c['check'], c['status'])
"

echo "=== 8. Git push ==="
python3 push_to_github.py \
  --files data/paper_trading_status.json data/equity_curve_daily.json \
          data/golive_status.json data/gap_monitor.json \
  --message "DR: post-incident state sync"
```

**Документирование инцидента:**

```bash
# Зафиксировать в incident history
# docs/ADR_013_incident_history.md — добавить вручную:
#   - дата/время обнаружения
#   - уровень (L1/L2/L3)
#   - симптомы
#   - причина
#   - шаги устранения
#   - RTO фактический
#   - что улучшить
```

---

## Временная шкала RTO

```
T+0h    Обнаружение (uptime_monitor / Telegram alert / ручное)
T+0.5h  Triage → определить уровень L1/L2/L3
T+1h    L1: завершено | L2: начата диагностика
T+2h    L2: завершено | L3: восстановление данных
T+3h    L3: цикл запущен, данные проверены
T+4h    ← RTO SLA L3: все сервисы подтверждены OK, push на GitHub
```

---

## Изменения относительно v1

| Раздел | Что добавлено |
|--------|---------------|
| §2 Уровни L1/L2/L3 | Формальная классификация инцидентов с RTO |
| §4 Kill switch | Детальная процедура расследования и сброса |
| §5 Telegram | Диагностика токена, fallback email, тест /ping |
| §7 Fund-level | Процедура выхода инвестора (ДПТ, 30д notice, pro-rata, investors.json) |
| §8 Контакты | Gnosis Safe 2-of-3 подписанты |
| §9 DR Drill | Ежеквартальный kill_switch_drill.py |

---

*Версия 2.0 — MP-362, 2026-06-12. Предыдущая версия: DR_PROCEDURE_v1.md (MP-211, 2026-06-11)*
