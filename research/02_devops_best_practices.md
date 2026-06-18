# DevOps Best Practices для DeFi/FinTech на Mac Mini (Self-Hosted)

> **Контекст:** Система управляет реальным капиталом $10–100K. Стек: Python (stdlib only), macOS launchd, GitHub (code + state), Cloudflare Tunnel, один Mac Mini always-on. Дата исследования: 2026-06-18.

---

## Содержание

1. [Self-hosted GitHub Actions Runner на Mac — риски и митигации](#1-self-hosted-github-actions-runner-на-mac)
2. [Управление секретами через macOS Keychain](#2-управление-секретами-через-macos-keychain)
3. [Zero-downtime deploy для критических финансовых процессов](#3-zero-downtime-deploy)
4. [Rollback стратегия без прерывания торгового цикла](#4-rollback-стратегия)
5. [Log rotation и retention для финансовых данных](#5-log-rotation-и-retention)
6. [Monitoring setup за $0–50/мес](#6-monitoring-setup-0-50мес)
7. [Incident Response Playbook для команды 1–2 человека](#7-incident-response-playbook)

---

## 1. Self-hosted GitHub Actions Runner на Mac

### 1.1 Реальные риски (верифицированы)

**Критически важно:** На ноябрь 2025 задокументирован червь **Shai-Hulud**, который устанавливал rogue runners через скомпрометированные NPM-пакеты и использовал уязвимые CI-воркфлоу как C2-канал. Это не теоретический риск.

**Топ-4 реальных вектора атаки:**

| Вектор | Описание | Вероятность для private repo |
|---|---|---|
| Compromised action dependency | `uses: some-action@v1` → злоумышленник тэгает новый код под тем же тэгом | Средняя |
| Persistence между runs | Runner не ephemeral → malware остаётся между запусками | Высокая, если не ephemeral |
| Production co-location | Runner на той же машине, что и продакшн-данные | **Критическая** — прямой доступ к data/ и Keychain |
| Leaked GITHUB_TOKEN | `ACTIONS_ALLOW_UNSECURE_COMMANDS=true` и похожие настройки открывают токен | Средняя |

**Главная проблема для SPA:** Runner находится на той же машине, что и `data/trades.json`, `data/equity_curve_daily.json` и macOS Keychain с PAT. Компрометация runner = компрометация всего.

### 1.2 Mitigation — чеклист из 12 пунктов

#### Изоляция runner-процесса

```bash
# Создать отдельного macOS-пользователя без admin прав
sudo dscl . -create /Users/gh-runner
sudo dscl . -create /Users/gh-runner UserShell /bin/bash
sudo dscl . -create /Users/gh-runner UniqueID 502
sudo dscl . -create /Users/gh-runner PrimaryGroupID 20
sudo dscl . -create /Users/gh-runner NFSHomeDirectory /Users/gh-runner
sudo dscl . -passwd /Users/gh-runner <STRONG_PASSWORD>

# Runner запускается от имени gh-runner, а НЕ от основного пользователя
```

#### Ограничение scope GITHUB_TOKEN

В каждом `.github/workflows/*.yml`:
```yaml
permissions:
  contents: read      # минимум — только читать код
  # НЕ добавляй: actions: write, secrets: write, packages: write
```

#### Пиннинг actions по SHA (не по тэгу)

```yaml
# ПЛОХО — тэг может переопределиться:
- uses: actions/checkout@v4

# ХОРОШО — неизменяемый SHA:
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
```

#### Ephemeral runner конфигурация

```bash
# Запуск с флагом --ephemeral — runner удаляется после каждого job
./config.sh --url https://github.com/ORG/REPO --token TOKEN --ephemeral
```

Для launchd: настроить `KeepAlive` и `RunAtLoad`, чтобы runner перезапускался и регистрировался заново после каждого job.

#### Ограничение egress сети

Через macOS Application Firewall (или Little Snitch):
- Runner может обращаться только к `github.com`, `api.github.com`, `*.actions.githubusercontent.com`
- Прямые запросы к `0.0.0.0/0` — запрещены
- Production endpoints (Cloudflare Tunnel, DeFiLlama API) — запрещены из runner-процесса

#### Конфигурация `.env` файла runner

```bash
# /Users/gh-runner/actions-runner/.env
ACTIONS_RUNNER_HOOK_JOB_STARTED=/Users/gh-runner/hooks/pre-job.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/Users/gh-runner/hooks/post-job.sh
```

`pre-job.sh` — очищает `/tmp/gh-runner-workspace`, проверяет целостность.
`post-job.sh` — очищает workspace после завершения job.

### 1.3 Рекомендация для SPA

> **Вывод:** Не использовать self-hosted runner на production Mac Mini. Для CI (тесты, линтер) — использовать **GitHub-hosted runners** (Ubuntu, бесплатно 2000 мин/мес). Self-hosted runner использовать только если абсолютно необходимо для deploy, и только в изолированном macOS-пользователе без доступа к `data/` и Keychain основного пользователя.

---

## 2. Управление секретами через macOS Keychain

### 2.1 Архитектура (только stdlib)

macOS Keychain — единственный правильный выбор для секретов на изолированном Mac Mini. Никаких `.env` файлов с паролями, никаких hardcode в коде.

**Текущий паттерн в SPA (верный):**
```bash
security find-generic-password -s GITHUB_PAT_SPA -w
```

**Python-доступ (только stdlib, без `keyring` пакета):**
```python
import subprocess

def get_secret(service_name: str) -> str:
    """Читает секрет из macOS Keychain. Выбрасывает RuntimeError если нет."""
    result = subprocess.run(
        ['security', 'find-generic-password', '-s', service_name, '-w'],
        capture_output=True,
        text=True,
        timeout=5
    )
    if result.returncode != 0:
        raise RuntimeError(f"Секрет '{service_name}' не найден в Keychain: {result.stderr}")
    return result.stdout.strip()

# Использование:
pat = get_secret('GITHUB_PAT_SPA')
telegram_token = get_secret('SPA_TELEGRAM_BOT_TOKEN')
```

### 2.2 Добавление секретов (правильно)

```bash
# НЕ ТАК (пароль в истории shell):
security add-generic-password -s GITHUB_PAT_SPA -a spa -w "ghp_SECRETVALUE"

# ПРАВИЛЬНО (интерактивный ввод без сохранения в историю):
security add-generic-password -s GITHUB_PAT_SPA -a spa
# macOS сам попросит ввести пароль в защищённом промпте

# Или через скрипт setup_pat.sh (как уже есть в SPA):
bash setup_pat.sh
```

### 2.3 Keychain ACL — ограничение доступа приложений

По умолчанию macOS спрашивает подтверждение при первом доступе нового процесса к элементу Keychain. Для автоматизации launchd:

```bash
# Разрешить только конкретному Python-интерпретеру читать секрет
security add-generic-password \
  -s GITHUB_PAT_SPA \
  -a spa \
  -T /usr/bin/python3 \
  -T /usr/bin/security
```

Флаг `-T` задаёт список приложений с ACL-доступом без диалога.

### 2.4 Проблема с launchd-демонами

**Критический нюанс:** Если launchd-агент запускается при login (тип `LaunchAgent`), Login Keychain разблокирован. Если это `LaunchDaemon` (system-wide), Keychain может быть заблокирован.

Решение — использовать **LaunchAgent** (в `~/Library/LaunchAgents/`), а не LaunchDaemon. Именно так работает `com.spa.daily_cycle` — это правильная архитектура.

### 2.5 Ротация секретов

Чеклист ротации PAT (из `docs/TOKEN_ROTATION_RUNBOOK.md`):
1. Сгенерировать новый PAT на `github.com/settings/tokens`
2. `security delete-generic-password -s GITHUB_PAT_SPA`
3. `bash setup_pat.sh` (добавить новый)
4. Проверить: `python3 push_to_github.py --dry-run --files /tmp/test.txt --message "test"`
5. Revoke старый PAT

**Срок жизни PAT:** Максимум 90 дней (GitHub ограничение для fine-grained PAT). Установить напоминание в Calendar за 7 дней до истечения.

### 2.6 Что НИКОГДА не делать

- ❌ Не писать секреты в файлы (CLAUDE.md, .env, .command, JSON) — инцидент 2026-06-10
- ❌ Не передавать секреты через переменные окружения в launchd plist (они видны через `launchctl getenv`)
- ❌ Не логировать значения секретов даже в debug-режиме
- ❌ Не хранить в git (даже в `.gitignore`-файлах — `.gitignore` не гарантирует защиту)

---

## 3. Zero-Downtime Deploy

### 3.1 Единственно правильная стратегия для одного Mac Mini

Для одного сервера без load balancer оптимальна **атомарная symlink-стратегия**. Это промышленный стандарт (Capistrano, Deployer, DeployHQ), работающий как атомарный `rename()` syscall на уровне ОС.

```
/opt/spa/
├── releases/
│   ├── 20260610_120000/    ← старый релиз (backup)
│   ├── 20260615_090000/    ← предыдущий релиз (rollback target)
│   └── 20260618_080000/    ← новый релиз
├── current -> releases/20260618_080000   ← symlink (атомарный)
└── shared/
    └── data/               ← state файлы НЕ в releases/ (shared между релизами)
```

### 3.2 Deploy-скрипт для SPA

```bash
#!/usr/bin/env bash
# deploy.sh — Zero-downtime deploy для SPA
set -euo pipefail

REPO_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
RELEASES_DIR="$REPO_DIR/releases"
SHARED_DATA="$REPO_DIR/shared/data"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NEW_RELEASE="$RELEASES_DIR/$TIMESTAMP"

echo "🚀 Deploy started: $TIMESTAMP"

# Шаг 1: Проверить, не запущен ли цикл прямо сейчас
CYCLE_PID_FILE="/tmp/spa_cycle.pid"
if [ -f "$CYCLE_PID_FILE" ] && kill -0 "$(cat $CYCLE_PID_FILE)" 2>/dev/null; then
    echo "⏳ Торговый цикл активен. Ожидаем завершения (max 10 мин)..."
    for i in $(seq 1 60); do
        sleep 10
        kill -0 "$(cat $CYCLE_PID_FILE)" 2>/dev/null || break
        echo "  ...ещё работает ($((i*10)) сек)"
    done
fi

# Шаг 2: Backup data/
cp -r "$REPO_DIR/data" "/tmp/spa_data_backup_$TIMESTAMP"
echo "✅ Data backup: /tmp/spa_data_backup_$TIMESTAMP"

# Шаг 3: Создать новый release из git
mkdir -p "$NEW_RELEASE"
git -C "$REPO_DIR" archive HEAD | tar -xC "$NEW_RELEASE"
echo "✅ Release скопирован: $NEW_RELEASE"

# Шаг 4: Pre-flight проверка (без записи в data/)
python3 -m spa_core.paper_trading.golive_checker 2>/dev/null | grep -q "pass" \
    || echo "⚠️  GoLiveChecker имеет незакрытые issues (не блокирует deploy)"

# Шаг 5: Атомарный symlink-switch
ln -sfn "$NEW_RELEASE" "$REPO_DIR/current"
echo "✅ Symlink переключён: current → $TIMESTAMP"

# Шаг 6: Restart launchd-агентов
launchctl stop com.spa.daily_cycle 2>/dev/null || true
launchctl start com.spa.daily_cycle
echo "✅ com.spa.daily_cycle перезапущен"

launchctl stop com.spa.httpserver 2>/dev/null || true
launchctl start com.spa.httpserver
echo "✅ com.spa.httpserver перезапущен"

# Шаг 7: Cleanup (оставить последние 3 релиза)
ls -t "$RELEASES_DIR" | tail -n +4 | xargs -I{} rm -rf "$RELEASES_DIR/{}"
echo "✅ Старые релизы удалены (оставлено 3)"

echo "🎉 Deploy завершён: $TIMESTAMP"
```

### 3.3 Graceful Shutdown в cycle_runner.py

Для zero-downtime критически важно, чтобы `cycle_runner.py` обрабатывал `SIGTERM`:

```python
import signal
import sys
import os

_shutdown_requested = False

def _handle_sigterm(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    # Записать PID-файл удаления — следующая итерация цикла проверит флаг

signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)

# В основном цикле:
def run_cycle():
    if _shutdown_requested:
        print("SIGTERM получен, завершаем после текущей операции...")
        sys.exit(0)
    # ... основная логика цикла
```

### 3.4 Совместимость state-файлов между версиями

**Правило expand-contract для JSON state файлов:**

| Разрешено | Запрещено без миграции |
|---|---|
| Добавить новое поле | Удалить существующее поле |
| Изменить тип поля | Переименовать поле |
| Добавить новый файл | Изменить ring-buffer размер вниз |

Новый код должен корректно работать со state-файлами старого формата (graceful defaults).

---

## 4. Rollback Стратегия

### 4.1 Категории ситуаций

| Ситуация | Действие | Время |
|---|---|---|
| Deploy провалился до symlink-switch | Ничего не делать — старый код всё ещё активен | 0 сек |
| Deploy прошёл, баг обнаружен сразу | Rollback к предыдущему релизу | < 2 мин |
| Баг в data/*.json (повреждение) | Restore из backup + Git reset | 5–15 мин |
| Полный отказ Mac Mini | DR по `DR_PROCEDURE_v2.md` | 30–60 мин |

### 4.2 Быстрый rollback (< 2 мин)

```bash
#!/usr/bin/env bash
# rollback.sh — Откат к предыдущему релизу
set -euo pipefail

REPO_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
RELEASES_DIR="$REPO_DIR/releases"

# Найти предыдущий релиз
PREV_RELEASE=$(ls -t "$RELEASES_DIR" | sed -n '2p')
if [ -z "$PREV_RELEASE" ]; then
    echo "❌ Нет предыдущего релиза для отката!"
    exit 1
fi

echo "🔄 Откат к: $PREV_RELEASE"

# Проверить цикл
CYCLE_PID_FILE="/tmp/spa_cycle.pid"
if [ -f "$CYCLE_PID_FILE" ] && kill -0 "$(cat $CYCLE_PID_FILE)" 2>/dev/null; then
    echo "⏳ Останавливаем активный цикл перед откатом..."
    launchctl stop com.spa.daily_cycle
    sleep 5
fi

# Атомарный switch назад
ln -sfn "$RELEASES_DIR/$PREV_RELEASE" "$REPO_DIR/current"

# Перезапуск сервисов
launchctl start com.spa.daily_cycle
launchctl stop com.spa.httpserver && launchctl start com.spa.httpserver

echo "✅ Rollback завершён: current → $PREV_RELEASE"
```

### 4.3 Rollback data-файлов

```bash
# Если повреждён конкретный state-файл:
BACKUP_TS="20260618_080000"  # timestamp последнего известно-хорошего состояния
cp "/tmp/spa_data_backup_$BACKUP_TS/trades.json" data/trades.json
cp "/tmp/spa_data_backup_$BACKUP_TS/equity_curve_daily.json" data/equity_curve_daily.json

# Если backup в /tmp не сохранился — из GitHub:
python3 push_to_github.py --dry-run  # проверить доступ
# Восстановить из последнего коммита:
git show HEAD:data/trades.json > data/trades.json
```

### 4.4 Git-тэги для каждого production deploy

```bash
# В конце deploy.sh:
git -C "$REPO_DIR" tag "deploy-prod-$TIMESTAMP"
python3 push_to_github.py \
    --files "$REPO_DIR/.git/refs/tags/deploy-prod-$TIMESTAMP" \
    --message "deploy tag: $TIMESTAMP"
```

### 4.5 Правило «никогда не делай rollback во время rebalance»

```python
# Перед любым rollback — проверить:
import json, time

status = json.load(open('data/paper_trading_status.json'))
if status.get('cycle_running', False):
    raise RuntimeError("Откат запрещён — цикл активен. Дождитесь завершения.")
```

---

## 5. Log Rotation и Retention

### 5.1 Регуляторные требования для DeFi

| Юрисдикция / Стандарт | Требование | Применимость к SPA |
|---|---|---|
| SEC Rule 17a-4 (США) | 3–7 лет для broker-dealers | Только если есть лицензия; для family fund — advisory |
| EU GDPR | 7 лет для финансовых записей если EU-пользователи | Применимо если участники Family Fund в ЕС |
| Best Practice (DeFi) | 5 лет для trade history | **Рекомендуется** — для доверия инвесторов |
| Internal Audit | Минимум 2 года оперативных логов | **Применяется** |

**Вывод для SPA:** Минимум — 2 года trade records + 1 год operational logs. `data/trades.json` (ring-buffer 500) — это финансовый audit trail, он НИКОГДА не ротируется автоматически. Вместо этого — push в GitHub (постоянное хранение).

### 5.2 Классификация логов SPA

| Тип | Файл | Хранение | Стратегия |
|---|---|---|---|
| **Trade records** | `data/trades.json` | Вечно | Push в GitHub, ring-buffer 500 на диске |
| **Equity curve** | `data/equity_curve_daily.json` | 365 дней | Ring-buffer (уже реализован) |
| **Operational** | `/tmp/spa_cycle.log` | 90 дней | Rotation ежедневно |
| **Errors** | `/tmp/spa_cycle_err.log` | 365 дней | Rotation еженедельно |
| **Risk blocks** | `data/risk_policy_blocks.json` | 100 записей (ring) | Push в GitHub |
| **GoLive status** | `data/golive_status.json` | Snapshot при каждом изменении | Push в GitHub |

### 5.3 Настройка newsyslog (встроен в macOS)

Создать файл `/etc/newsyslog.d/spa.conf`:

```
# logfile                        mode  count  size(KB)  when  flags  pid_file  signal
/tmp/spa_cycle.log               644   90     10240     $D0   GJN
/tmp/spa_cycle_err.log           644   365    10240     $W0   GJN
/Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_logs.log  644  30  5120  $D0  GJN
```

Флаги: `G` = glob, `J` = bzip2 сжатие, `N` = не создавать если отсутствует.

```bash
# Проверить конфиг:
sudo newsyslog -nv

# Принудительная ротация:
sudo newsyslog /etc/newsyslog.d/spa.conf
```

### 5.4 Умная наблюдаемость (FinTech-подход)

**Принцип динамического семплинга** (из исследования OpsTree, 2026):

```python
# В cycle_runner.py — дифференцированное логирование
import logging

class SmartFinancialLogger:
    """100% ошибок, 10% успешных операций — снижает объём логов на 30-50%"""
    
    def log_trade(self, trade: dict, success: bool):
        if not success:
            logging.error("TRADE_FAILED: %s", trade)  # 100% ошибок
        elif trade.get('amount_usd', 0) > 1000:
            logging.info("TRADE_SIGNIFICANT: %s", trade)  # крупные трейды
        # Мелкие успешные трейды — только в debug (не в файл)
    
    def log_cycle_success(self, cycle_data: dict):
        # Только summary, не каждый шаг
        logging.info("CYCLE_OK: equity=%.2f apy=%.2f%%", 
                     cycle_data['equity'], cycle_data['apy'])
```

### 5.5 Долгосрочное хранение (cold tier)

**Для compliance-данных:** GitHub (уже используется) = бесплатное cold-хранение.

```bash
# Еженедельный архив логов → GitHub:
# В auto_push.py или отдельном скрипте:
WEEK=$(date +%Y-W%V)
gzip -c /tmp/spa_cycle.log > "logs/spa_cycle_$WEEK.log.gz"
python3 push_to_github.py \
    --files "logs/spa_cycle_$WEEK.log.gz" \
    --message "weekly log archive: $WEEK"
```

---

## 6. Monitoring Setup $0–50/мес

### 6.1 Рекомендованный стек для SPA (Tier 0 — $0/мес)

```
┌─────────────────────────────────────────────────────────────────┐
│                     SPA Monitoring Stack                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  External Check        Internal Check       Alerting           │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│  │ UptimeRobot  │────►│ Uptime Kuma  │────►│ Telegram Bot │   │
│  │ (free, 50    │     │ (self-hosted │     │ (free, $0)   │   │
│  │ monitors)    │     │ on Mac Mini) │     └──────────────┘   │
│  └──────────────┘     └──────────────┘                         │
│         │                    │                                  │
│         ▼                    ▼                                  │
│  HTTP check: dashboard   Process check:                        │
│  via Cloudflare Tunnel   launchd PID heartbeat                 │
│                          data/freshness check                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Инструменты и цены (2026)

| Инструмент | Free Tier | Paid | Что мониторит |
|---|---|---|---|
| **UptimeRobot** | 50 мониторов, 5-мин чек, личное использование | $9/мес (Solo, 1-мин чек) | HTTP/HTTPS dashboard URL через Cloudflare Tunnel |
| **Better Stack** | 10 мониторов, 3-мин чек, 3GB logs | $29/мес (Team, phone calls) | HTTP + heartbeat + incident management |
| **Uptime Kuma** | Полностью бесплатный, self-hosted | $0 | TCP, HTTP, process, DNS, heartbeat |
| **Grafana Cloud** | 10k метрик, 3 юзера, Prometheus | ~$8/мес за дополнительные метрики | Метрики APY, equity, drawdown |
| **Telegram Bot** | Полностью бесплатный | $0 | Алерты из любого источника |
| **ntfy.sh** | Self-hosted + cloud free tier | $0–$5/мес | Push-уведомления, альтернатива Telegram |

**Итого для SPA: $0/мес** (Uptime Kuma local + UptimeRobot free + Telegram Bot)

**Опциональный upgrade: $9/мес** (UptimeRobot Solo — 1-мин чеки вместо 5-мин)

### 6.3 Heartbeat endpoint в cycle_runner.py

```python
# В конце каждого успешного цикла — ping heartbeat URL
import urllib.request

def ping_heartbeat(url: str):
    """Уведомить Uptime Kuma/BetterStack что цикл живой"""
    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception as e:
        # Не прерывать цикл из-за мониторинга
        print(f"WARN: heartbeat ping failed: {e}")

# В конце cycle_runner.py:
HEARTBEAT_URL = "http://localhost:3001/api/push/KUMA_TOKEN?status=up&msg=cycle_ok"
ping_heartbeat(HEARTBEAT_URL)
```

Uptime Kuma алертит если heartbeat не получен за N минут (настраивается, например, 26 часов — если цикл раз в сутки не пришёл).

### 6.4 Telegram-алерты из Python (stdlib только)

```python
import urllib.request
import urllib.parse
import json

class TelegramAlerter:
    def __init__(self):
        import subprocess
        self.token = subprocess.check_output(
            ['security', 'find-generic-password', '-s', 'SPA_TELEGRAM_BOT_TOKEN', '-w'],
            text=True
        ).strip()
        self.chat_id = subprocess.check_output(
            ['security', 'find-generic-password', '-s', 'SPA_TELEGRAM_CHAT_ID', '-w'],
            text=True
        ).strip()
    
    def send(self, message: str, parse_mode: str = "HTML"):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = json.dumps({
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, 
                                      headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    
    def alert_critical(self, title: str, details: str):
        self.send(f"🚨 <b>CRITICAL: {title}</b>\n{details}")
    
    def alert_daily_ok(self, equity: float, apy: float):
        self.send(f"✅ <b>SPA Daily Cycle OK</b>\n"
                  f"Equity: ${equity:,.2f}\nAPY: {apy:.2f}%")
```

### 6.5 launchd health check script

```bash
#!/bin/bash
# check_spa_health.sh — запускать через cron или launchd каждые 30 минут

TELEGRAM_TOKEN=$(security find-generic-password -s SPA_TELEGRAM_BOT_TOKEN -w)
TELEGRAM_CHAT=$(security find-generic-password -s SPA_TELEGRAM_CHAT_ID -w)

send_alert() {
    curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT&text=$1" > /dev/null
}

# Проверить launchd-агенты
for SERVICE in com.spa.daily_cycle com.spa.httpserver com.spa.cloudflared; do
    STATUS=$(launchctl list | grep "$SERVICE" | awk '{print $1}')
    if [ "$STATUS" = "-" ]; then
        send_alert "⚠️ SPA ALERT: $SERVICE не запущен!"
    fi
done

# Проверить freshness data
LAST_CYCLE=$(python3 -c "
import json, time
s = json.load(open('/Users/yuriikulieshov/Documents/SPA_Claude/data/paper_trading_status.json'))
age = time.time() - s.get('last_cycle_timestamp', 0)
print(int(age / 3600))
" 2>/dev/null || echo "999")

if [ "$LAST_CYCLE" -gt "26" ]; then
    send_alert "🚨 SPA CRITICAL: Цикл не запускался $LAST_CYCLE часов!"
fi

echo "Health check OK: $(date)"
```

### 6.6 Что мониторить (приоритеты)

**P0 (critical):** equity_curve обновилась сегодня, trades.json не повреждён, launchd-сервисы живые, Cloudflare Tunnel доступен
**P1 (warning):** APY ниже порога, drawdown > 3%, GoLiveChecker регрессировал
**P2 (info):** Новый релиз задеплоен, PAT истекает через 7 дней

---

## 7. Incident Response Playbook

### 7.1 Severity уровни для SPA

| Severity | Описание | RTO | Пример |
|---|---|---|---|
| **P0 — Critical** | Потеря данных / риск капитала | < 15 мин | Повреждение trades.json, RiskPolicy bypass |
| **P1 — High** | Цикл не запустился / dashboard недоступен | < 30 мин | launchd упал, Cloudflare Tunnel отвалился |
| **P2 — Medium** | Деградация без угрозы капиталу | < 2 часа | Один адаптер вернул ошибку, GoLiveChecker регрессия |
| **P3 — Low** | Мониторинг / технический долг | Next business day | PAT скоро истекает, логи ротировались |

### 7.2 Playbook — P0: Потенциальная угроза данным

```
ТРИГГЕР: Алерт о несовпадении хэша data/trades.json ИЛИ 
         RiskPolicy вернул approved=True для заблокированной операции
         
ШАГ 1 (0–2 мин): ОСТАНОВИТЬ всё
  → launchctl stop com.spa.daily_cycle
  → launchctl stop com.spa.httpserver  
  → Зафиксировать время: echo "INCIDENT_START: $(date)" >> /tmp/spa_incident.log

ШАГ 2 (2–5 мин): ОЦЕНИТЬ масштаб
  → python3 -m spa_core.paper_trading.golive_checker
  → cat data/paper_trading_status.json | python3 -m json.tool
  → git -C /path/to/repo diff data/ — что изменилось?

ШАГ 3 (5–10 мин): ЗАЩИТИТЬ данные
  → cp -r data/ /tmp/spa_incident_snapshot_$(date +%Y%m%d_%H%M%S)/
  → python3 push_to_github.py --files data/trades.json data/equity_curve_daily.json \
      --message "INCIDENT: snapshot before investigation"

ШАГ 4 (10–30 мин): ИСПРАВИТЬ или ОТКАТИТЬ
  Если код — bash rollback.sh
  Если data — восстановить из последнего git commit или backup
  Если Keychain скомпрометирован — revoke PAT немедленно

ШАГ 5 (30+ мин): ВОЗОБНОВИТЬ
  → launchctl start com.spa.daily_cycle
  → Мониторить следующий цикл вручную через tail -f /tmp/spa_cycle.log

ШАГ 6 (после разрешения): POST-MORTEM
  → Записать в docs/incidents/YYYY-MM-DD-description.md
  → Обновить GoLiveChecker если нужно добавить критерий
  → Push в GitHub
```

### 7.3 Playbook — P1: Cloudflare Tunnel недоступен

```
ТРИГГЕР: UptimeRobot/BetterStack алерт — dashboard URL не отвечает

ШАГ 1 (0–2 мин): Верифицировать
  → curl -I https://your-spa-domain.workers.dev/
  → Если 5xx или timeout — проблема на стороне Cloudflare или локально

ШАГ 2 (2–5 мин): Перезапустить tunnel
  → launchctl stop com.spa.cloudflared
  → launchctl start com.spa.cloudflared
  → sleep 10 && curl -I https://your-spa-domain.workers.dev/

ШАГ 3 (5–10 мин): Если не помогло — проверить cloudflared
  → tail -50 /tmp/spa_cloudflared.log
  → cloudflared tunnel list  # проверить статус в API

ШАГ 4: Если Cloudflare down (глобальный инцидент)
  → Проверить https://www.cloudflarestatus.com/
  → Ничего не делать — ждать. Локальные процессы продолжают работать.

ВАЖНО: Недоступность dashboard ≠ недоступность торгового цикла.
Цикл работает локально независимо от Tunnel.
```

### 7.4 Playbook — P1: launchd-агент не запустился

```
ТРИГГЕР: Telegram-алерт от check_spa_health.sh или ручная проверка

ДИАГНОСТИКА:
  → launchctl list | grep com.spa
  → launchctl error <код> для расшифровки кода ошибки
  → tail -20 /tmp/spa_cycle_err.log

ТИПИЧНЫЕ ПРИЧИНЫ И РЕШЕНИЯ:

  Код -2 (файл не найден):
    → ls -la ~/Library/LaunchAgents/com.spa.daily_cycle.plist
    → Plist повреждён или удалён → восстановить из git

  Код 78 (load failed):
    → Проверить plist синтаксис: plutil -lint com.spa.daily_cycle.plist
    
  Бесконечный restart loop (ThrottleInterval):
    → launchctl disable com.spa.daily_cycle
    → Исправить ошибку в скрипте
    → launchctl enable com.spa.daily_cycle
    → launchctl start com.spa.daily_cycle

  Python не найден:
    → which python3
    → Обновить путь в plist (ProgramArguments)
```

### 7.5 Playbook — P3: PAT истекает

```
ТРИГГЕР: Плановое напоминание (Calendar, за 7 дней)

ШАГ 1: Сгенерировать новый PAT
  → github.com/settings/tokens/new
  → Scope: repo (только нужный репозиторий)
  → Срок: 90 дней (максимум для fine-grained PAT)
  → Сохранить ТОЛЬКО в Keychain, не в clipboard!

ШАГ 2: Обновить Keychain
  → security delete-generic-password -s GITHUB_PAT_SPA -a spa
  → bash setup_pat.sh

ШАГ 3: Проверить
  → python3 push_to_github.py --dry-run --files /tmp/test_pat.txt --message "PAT test"

ШАГ 4: Revoke старый PAT
  → github.com/settings/tokens → Revoke

ШАГ 5: Установить следующее напоминание через 83 дня
```

### 7.6 Contact Matrix (1–2 человека)

```
Роль           Контакт          Ответственность
-----------    --------         ----------------
Owner          Yurii (primary)  Все P0/P1 инциденты, финансовые решения
Backup         TBD (co-owner)   Если Owner недоступен > 30 мин при P0
Telegram group @SPA_Ops_Team    Оба участника, все алерты

Эскалация: P0 → попытка 1 → ожидание 15 мин → попытка 2 → 
           kill switch (launchctl stop com.spa.daily_cycle)
```

### 7.7 Автоматический Kill Switch

```python
# В cycle_runner.py — автоматический стоп при критическом drawdown
# Уже покрывается RiskPolicy (drawdown >= 5% → close all)
# Дополнительный circuit breaker на уровне CI:

def emergency_stop():
    """Вызвать при обнаружении критической аномалии."""
    import subprocess
    subprocess.run(['launchctl', 'stop', 'com.spa.daily_cycle'])
    
    # Уведомить
    alerter = TelegramAlerter()
    alerter.alert_critical(
        "EMERGENCY STOP ACTIVATED",
        "Торговый цикл остановлен автоматически. Требуется ручная проверка."
    )
    
    # Записать в лог
    with open('/tmp/spa_emergency_stop.log', 'a') as f:
        f.write(f"{datetime.now().isoformat()}: Emergency stop triggered\n")
```

---

## Сводная таблица рекомендаций

| Область | Инструмент | Цена | Приоритет |
|---|---|---|---|
| Secrets | macOS Keychain (stdlib subprocess) | $0 | P0 |
| Deploy | Atomic symlink + deploy.sh | $0 | P0 |
| Rollback | rollback.sh + git tags | $0 | P0 |
| Log rotation | macOS newsyslog | $0 | P1 |
| HTTP monitoring | UptimeRobot free (50 monitors) | $0 | P1 |
| Heartbeat | Uptime Kuma self-hosted | $0 | P1 |
| Alerting | Telegram Bot (stdlib) | $0 | P1 |
| Metrics viz | Grafana Cloud free tier | $0 | P2 |
| 1-min checks | UptimeRobot Solo | $9/мес | P2 |
| Phone calls | Better Stack Team | $29/мес | P3 |
| CI/CD | GitHub-hosted runners (2000 мин/мес free) | $0 | P1 |

**Итого для минимально жизнеспособного production setup: $0/мес**

---

## Источники

- [GitHub Actions Secure Use Reference](https://docs.github.com/en/actions/reference/security/secure-use)
- [Sysdig: How threat actors are using self-hosted GitHub Actions runners as backdoors](https://www.sysdig.com/blog/how-threat-actors-are-using-self-hosted-github-actions-runners-as-backdoors)
- [Wiz Blog: Hardening GitHub Actions — Lessons from Recent Attacks](https://www.wiz.io/blog/github-actions-security-guide)
- [DeepFrame: Self-hosted GitHub Actions runner security — 12 checks](https://deepframe.xyz/blog/self-hosted-github-actions-runner-security-checklist)
- [Orca Security: GitHub Actions Security Risks](https://orca.security/resources/blog/github-actions-security-risks/)
- [OpsTree: The FinTech Guide to Smart Observability (Feb 2026)](https://opstree.com/blog/fintech-guide-to-smart-observability/)
- [DeployHQ: Zero Downtime Deployment Strategies — Blue/Green, Canary & Rolling](https://www.deployhq.com/blog/zero-downtime-deployments-keeping-your-application-running-smoothly)
- [OpenObserve: Top 10 Log Monitoring Tools in 2025](https://openobserve.ai/blog/top-10-log-monitoring-tools-2025/)
- [Swimlane: How to Build an Incident Response Playbook in 9 Steps](https://swimlane.com/blog/incident-response-playbook/)
- [HackMag: Automate macOS Startup and Background Tasks with Python and launchctl](https://hackmag.com/security/launchctl-python)
- [Grafana: macOS service monitoring](https://grafana.com/solutions/macos/monitor/)
- [Uptime Kuma Official Site](https://uptimekuma.org/)
- [UptimeRobot Pricing 2026](https://uptimerobot.com/pricing/)
- [Better Stack Pricing 2026](https://betterstack.com/pricing)
- [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Cloudflare Access Policies](https://developers.cloudflare.com/cloudflare-one/policies/access/)
- [Python Atomic File Writes](https://code.activestate.com/recipes/579097-safely-and-atomically-write-to-a-file/)
- [GitGuardian: Python Secrets Management Best Practices](https://blog.gitguardian.com/how-to-handle-secrets-in-python/)
- [ELL Blog: Avoid Data Corruption by Syncing to Disk](https://blog.elijahlopez.ca/posts/data-corruption-atomic-writing/)

---

*Отчёт подготовлен: 2026-06-18. Верифицирован по 19 источникам. Все цены актуальны на дату составления.*
