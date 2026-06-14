# SPA Disaster Recovery Playbook
*Дата: 2026-06-14 | Версия: 1.0*

> Назначение: пошаговое восстановление инфраструктуры SPA при отказах.
> Все команды — реальные из репозитория `~/Documents/SPA_Claude`.
> Источник истины по статусу инфраструктуры — `CURRENT_STATE.md` + `data/uptime_status.json`.
> Проверка статуса в любой момент: `bash ~/Documents/SPA_Claude/scripts/agent_status.sh`

---

## Карта инфраструктуры (что и где)

| Сервис | Label (launchd) | Запуск | Лог |
|--------|-----------------|--------|-----|
| HTTP дашборд (порт 8765) | `com.spa.httpserver` | persistent (RunAtLoad) | — |
| Cloudflare tunnel | `com.spa.cloudflared` | persistent | — |
| Uptime monitor | `com.spa.uptime_monitor` | каждые 300с | `/tmp/spa_uptime_monitor.log`, `/tmp/spa_uptime_monitor_err.log` |
| Дневной цикл (paper trading) | `com.spa.daily_cycle` | 08:00 | `/tmp/spa_cycle.log` |
| Autopush | `com.spa.autopush` | каждые 90 мин | `/tmp/spa_autopush.log` |
| Tier C analytics | `com.spa.analytics_tier_c` | 05:00 | — |
| Telegram bot (long-poll) | `com.spa.bot_commands` | KeepAlive | — |

- **Plist-шаблоны:** `scripts/com.spa.*.plist`
- **Установленные plist:** `~/Library/LaunchAgents/com.spa.*.plist`
- **Python:** `/Users/yuriikulieshov/miniconda3/bin/python3`
- **PAT в Keychain:** сервис `GITHUB_PAT_SPA` — `security find-generic-password -s GITHUB_PAT_SPA -w`
- **Репозиторий:** `yurii-spa/SPA` (GitHub)

---

## Сценарии и восстановление

### Сценарий 1: Mac Mini перезагрузился
**Симптомы:** agents не запускаются, dashboard недоступен на `localhost:8765`.

**Восстановление:**
1. Убедись, что включён автологин (System Settings → Users & Groups → Automatically log in as). Без него launchd-агенты в user-домене не стартуют до ручного логина.
2. При логине launchd автоматически загружает `~/Library/LaunchAgents/com.spa.*` (у всех `RunAtLoad=true`).
3. Если агенты не загрузились — переустановить:
   ```bash
   bash ~/Documents/SPA_Claude/scripts/install_agents.sh
   ```
   (скрипт idempotent: unload перед load, не трогает запущенные сервисы)
4. Проверить статус:
   ```bash
   bash ~/Documents/SPA_Claude/scripts/agent_status.sh
   launchctl list | grep com.spa
   ```
5. Проверить дашборд: открыть `http://localhost:8765` в браузере.

---

### Сценарий 2: cycle_runner не запускается
**Симптомы:** нет свежих данных в `data/paper_trading_status.json`, в дашборде "цикл устарел", uptime_monitor сигналит degraded.

**Восстановление:**
1. Проверить, загружен ли агент и его последний exit-код:
   ```bash
   launchctl list | grep com.spa.daily_cycle
   ```
   (вторая колонка = последний exit; ненулевой = ошибка)
2. Посмотреть лог:
   ```bash
   tail -50 /tmp/spa_cycle.log
   ```
3. Прогнать цикл вручную из корня репо, чтобы увидеть traceback:
   ```bash
   cd ~/Documents/SPA_Claude
   /Users/yuriikulieshov/miniconda3/bin/python3 cycle_runner.py
   ```
4. Частые причины:
   - Python-путь в plist не совпадает с реальным miniconda → исправить и `install_agents.sh`.
   - Повреждённый JSON в `data/*.json` (нарушено правило атомарной записи) → восстановить из `data/*.bak` или git.
   - Импорт-ошибка после правок модуля → запустить тесты: `python3 -m pytest spa_core/tests/ -q`.
5. После фикса перезагрузить агент:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist
   launchctl load   ~/Library/LaunchAgents/com.spa.daily_cycle.plist
   ```

---

### Сценарий 3: Развёртывание на новую машину (полное)
**Цель:** поднять SPA с нуля на чистом macOS.

**Шаги:**
1. **Homebrew** (если нет):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. **Git + cloudflared:**
   ```bash
   brew install git
   brew install cloudflared
   ```
3. **Miniconda** (Python 3) — установить в `~/miniconda3`:
   ```bash
   curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh -o /tmp/miniconda.sh
   bash /tmp/miniconda.sh -b -p ~/miniconda3
   ~/miniconda3/bin/python3 --version   # подтвердить путь, ожидается /Users/<user>/miniconda3/bin/python3
   ```
4. **Клонировать репозиторий** в `~/Documents/SPA_Claude`:
   ```bash
   mkdir -p ~/Documents
   git clone https://github.com/yurii-spa/SPA.git ~/Documents/SPA_Claude
   ```
5. **Python-зависимости** (если есть requirements / pyproject):
   ```bash
   cd ~/Documents/SPA_Claude
   ~/miniconda3/bin/python3 -m pip install -r requirements.txt 2>/dev/null || true
   ```
6. **Keychain setup** — записать GitHub PAT и Telegram-токены в Keychain (вводит ПОЛЬЗОВАТЕЛЬ, не агент):
   ```bash
   bash ~/Documents/SPA_Claude/setup_pat.sh        # GITHUB_PAT_SPA
   # Telegram (если не настроен):
   security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w '<TOKEN>'
   security add-generic-password -s TELEGRAM_CHAT_ID_SPA   -a spa -w '<CHAT_ID>'
   ```
   Проверка: `security find-generic-password -s GITHUB_PAT_SPA -w`
7. **Проверить путь Python в install_agents.sh** — переменная `PYTHON` должна указывать на реальный miniconda (`/Users/<user>/miniconda3/bin/python3`). При другом имени пользователя — отредактировать plist-шаблоны.
8. **Установить launchd-агенты:**
   ```bash
   bash ~/Documents/SPA_Claude/scripts/install_agents.sh
   ```
9. **Включить автологин** (System Settings → Users & Groups) — обязательно для user-домена launchd.
10. **Проверка:**
    ```bash
    bash ~/Documents/SPA_Claude/scripts/agent_status.sh
    open http://localhost:8765
    ```

---

### Сценарий 4: GitHub push не работает (PAT истёк)
**Симптомы:** `/tmp/spa_autopush.log` показывает 401/403, новые коммиты не появляются в `yurii-spa/SPA`.

**Восстановление:**
1. Подтвердить причину — прогнать push вручную:
   ```bash
   cd ~/Documents/SPA_Claude
   bash scripts/auto_push.sh
   tail -30 /tmp/spa_autopush.log
   ```
   401/403 = PAT истёк или отозван.
2. Создать новый PAT на GitHub (Settings → Developer settings → Fine-grained tokens), scope `Contents: Read and write` для репозитория `yurii-spa/SPA`. **Это делает пользователь — агент не вводит токены и не создаёт аккаунты.**
3. Записать новый PAT в Keychain (ротация):
   ```bash
   bash ~/Documents/SPA_Claude/setup_pat.sh
   ```
   (перезаписывает сервис `GITHUB_PAT_SPA`)
4. Проверить, что `push_to_github.py` читает новый PAT (порядок: Keychain → env `GITHUB_PAT_SPA` → env `SPA_GITHUB_PAT` → `~/.github_pat`):
   ```bash
   security find-generic-password -s GITHUB_PAT_SPA -w | head -c 8; echo "…"
   bash scripts/auto_push.sh
   ```
5. **Запрет:** никогда не встраивать PAT в файлы (инцидент 2026-06-10 — токен утёк в 90+ файлов). Только Keychain / env / `~/.github_pat`.

---

### Сценарий 5: Kill-switch ложно активировался
**Симптомы:** торговый цикл остановлен kill-switch'ем, в логе сигнал по Sharpe при коротком треке.

**Контекст:** kill-switch на основе Sharpe требует минимум `MIN_DAYS_FOR_SHARPE = 30` дней данных. На малой выборке (~5 дней) Sharpe даёт ложные срабатывания (зафиксирован Sharpe -61). Текущий статус трека — `inactive` (трек < 30 дней с 2026-06-10).

**Восстановление:**
1. Проверить причину срабатывания:
   ```bash
   tail -50 /tmp/spa_cycle.log
   cat ~/Documents/SPA_Claude/data/kill_switch_status.json 2>/dev/null
   ```
2. Если срабатывание по Sharpe при числе дней трека < 30 — это ложное срабатывание (insufficient data должно трактоваться как no signal, см. RULES.md).
3. Убедиться, что число дней трека действительно меньше `MIN_DAYS_FOR_SHARPE`:
   ```bash
   cat ~/Documents/SPA_Claude/data/paper_trading_status.json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('track_start'), d.get('days'))"
   ```
4. Сбросить kill-switch только после подтверждения причины (manual review). Не отключать kill-switch навсегда — это защитный контур.
5. Если срабатывание корректное (реальный drawdown / нарушение лимитов) — не сбрасывать, разобрать причину в `docs/DECISIONS.md` и эскалировать.

---

### Сценарий 6: httpserver не отвечает на порту 8765
**Симптомы:** `http://localhost:8765` не открывается, дашборд недоступен; uptime_monitor помечает `launchd_httpserver` как degraded.

**Восстановление:**
1. Проверить, занят ли порт и каким процессом:
   ```bash
   lsof -i :8765
   launchctl list | grep com.spa.httpserver
   ```
2. Если процесс завис/осиротел — перезагрузить агент:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.spa.httpserver.plist
   launchctl load   ~/Library/LaunchAgents/com.spa.httpserver.plist
   ```
3. Если порт занят посторонним процессом — снять его и перезапустить агент:
   ```bash
   lsof -ti :8765 | xargs kill   # осторожно: убедись, что это именно httpserver
   launchctl load ~/Library/LaunchAgents/com.spa.httpserver.plist
   ```
4. Проверить свежесть данных в `data/uptime_status.json` (поле `checks.launchd_httpserver.running`):
   ```bash
   cat ~/Documents/SPA_Claude/data/uptime_status.json | python3 -m json.tool | grep -A4 httpserver
   ```
5. Подтвердить восстановление:
   ```bash
   curl -sI http://localhost:8765 | head -1
   bash ~/Documents/SPA_Claude/scripts/agent_status.sh
   ```

---

## Универсальные команды диагностики

```bash
# Полный статус всех агентов
bash ~/Documents/SPA_Claude/scripts/agent_status.sh

# Сырой список launchd
launchctl list | grep com.spa

# Свежесть инфраструктуры (JSON, atomic)
cat ~/Documents/SPA_Claude/data/uptime_status.json | python3 -m json.tool

# Переустановка всех агентов (idempotent)
bash ~/Documents/SPA_Claude/scripts/install_agents.sh

# Немедленный push
bash ~/Documents/SPA_Claude/scripts/auto_push.sh
```

---

*Связанные документы: `docs/DR_PROCEDURE_v1.md`, `docs/DR_PROCEDURE_v2.md`, `RULES.md`, `CURRENT_STATE.md`, `docs/ADR-032-push-strategy.md`.*
