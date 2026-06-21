# SPA — Аудит технической инфраструктуры
**Дата:** 2026-06-20 | **Аудитор:** Claude (read-only, без изменений файлов)

---

## 1. launchd Дэмоны

**Статус: ⚠️ WARNING — нет прямого доступа к ~/Library/LaunchAgents из sandbox, но косвенные признаки указывают на проблемы**

**Plist-файлы в репо:** 21 файл в `scripts/com.spa.*.plist`

Ключевые 4 дэмона по CLAUDE.md:

| Дэмон | Plist в репо | Подтверждение работы | Вывод |
|---|---|---|---|
| `com.spa.daily_cycle` | ✅ есть | ⚠️ Нет `logs/daily_cycle_20260620.log`, нет `logs/launchd_stdout/stderr.log`. Данные в data/ свежие (17:22 UTC) — цикл явно запускался, но НЕ через launchd-plist (скорее всего вручную) | **Неясно установлен ли** |
| `com.spa.autopush` | ✅ есть | ❌ GoLive checker: `autopush_installed: false`. `~/Library/LaunchAgents/com.spa.autopush.plist not found` | **НЕ УСТАНОВЛЕН** |
| `com.spa.httpserver` | ✅ есть | ⚠️ `logs/dashboard_server.err` — сервер работал 2026-06-18, возвращает 404 на все маршруты (/, /api/status, /health, /spa_data/) | **Работает, но с ошибками** |
| `com.spa.cloudflared` | ✅ есть | ⚠️ `logs/cloudflared.err` последняя запись: 2026-06-18 16:34 — "control stream failure". Активность с тех пор не зафиксирована | **Был активен 2 дня назад** |

**Критические наблюдения:**

- `run_daily_paper_cycle.sh` запускает `CPACycleWithEvidence` из `spa_core.backtesting` — это НЕ то же самое, что `python3 -m spa_core.paper_trading.cycle_runner --verbose` из CLAUDE.md. Два разных entry point для "ежедневного цикла".
- PATH в `com.spa.daily_cycle.plist` включает miniconda (`/Users/yuriikulieshov/miniconda3/bin`) — это правильно, но нужна проверка что plist загружен.
- `com.spa.autopush.plist` не имеет `EnvironmentVariables` с PATH/HOME → при установке может не найти python.

**Логи которые нужно проверить на машине:**
```bash
launchctl list | grep com.spa
tail -50 ~/Documents/SPA_Claude/logs/daily_cycle_20260620.log
```

---

## 2. Autopush Система

**Статус: ⚠️ WARNING — работает через manual/auto_push.sh, plist НЕ установлен**

| Параметр | Значение |
|---|---|
| `autopush_state.last_version` | 1204 |
| `autopush_state.total_pushed` | 26 (за текущую сессию) |
| `autopush_state.updated` | 2026-06-20T20:23:31 UTC |
| `.push_log` записей | **932** (932 скрипта выполнены) |
| push_v*.sh в scripts/ | **188 файлов** (push_v918 — push_v1204) |
| Последний push_v*.sh | `push_v1204.sh` |
| auto_push.log: результат | `pushed=5 skipped=182 failed=1` |

**Проблемы:**

- ❌ `auto_push_err.log` заполнен ошибками: `can't open file '/Users/.../scripts/push_to_github.py'`
  — старые push_v*.sh скрипты ищут `push_to_github.py` в `scripts/`, а он находится в корне репо.
  Текущие скрипты (вроде push_v966.sh) используют `${REPO_ROOT}/push_to_github.py` — ✅ правильно.
  Старые скрипты — сломаны. **`failed=1` в последнем прогоне** — один скрипт упал.

- ❌ Несколько push_v*.sh ссылаются на `~/.github_pat` как fallback (push_v818, push_v849, push_v859 и другие). Это файл-секрет в обход Keychain — нарушение SECRETS POLICY.

- ⚠️ `com.spa.autopush.plist` — единственный GoLive-блокер (25/26 pass). Не установлен.

- ℹ️ Пустой разрыв между `.push_log` (932 entries) и `scripts/push_v*.sh` (только 188 файлов): большинство push-скриптов генерировались, выполнялись и удалялись (или находятся в другом месте).

---

## 3. GitHub Репо

**Статус: ⚠️ WARNING — гигантский uncommitted diff, дублирующиеся коммиты**

| Параметр | Значение |
|---|---|
| Remote | `https://github.com/yurii-spa/SPA.git` |
| Unpushed commits | 0 (в sync с origin) |
| **Modified files (git)** | **52** |
| **Untracked files** | **570** |
| **ИТОГО грязных файлов** | **622** |
| Дублирующиеся коммиты | v8.89 MP-1243 появляется **8+ раз** (одно и то же сообщение) |
| `[skip ci]` в последних 15 коммитах | **15/15** (100%) |

**Критически важно:** 570 untracked файлов — это потенциально ценный код, который никогда не был закоммичен. Если потеряется git tree → потеряются все эти файлы.

**Примеры untracked из `git status`:**
```
?? spa_core.analytics.defi_protocol_collateral_efficiency_scorer...
?? (множество файлов с длинными именами)
```

**Дублирующиеся коммиты** — признак push через API без check на существование. Мусор в истории.

---

## 4. Python Окружение и Зависимости

**Статус: ⚠️ WARNING — несоответствие требований CLAUDE.md**

| Пакет | Статус в системном Python 3.10 |
|---|---|
| web3 | ❌ MISSING |
| eth_account | ❌ MISSING |
| requests | ✅ OK |
| aiohttp | ❌ MISSING |
| pytest | ❌ MISSING (в системном Python) |
| pandas | ✅ OK |
| numpy | ✅ OK |
| psycopg2 | ❌ MISSING |
| telegram | ❌ MISSING |

**Runtime Python:** `/Users/yuriikulieshov/miniconda3/bin/python3` (plist использует его) — набор пакетов неизвестен из sandbox, но предположительно там установлен pytest и другие.

**Критически:** `spa_core/requirements.txt` содержит **11 внешних зависимостей**:
```
requests, pytest, pytest-cov, fastapi, uvicorn, pydantic,
reportlab, websockets, python-multipart, psycopg2-binary, alembic
```
CLAUDE.md: "**только stdlib** Python — без внешних зависимостей в runtime-коде".

Нет `requirements.txt` в корне репо который бы явно документировал **какие** компоненты stdlib-only, а какие нет. `-r spa_core/requirements.txt` вбирает всё.

---

## 5. CI/CD — GitHub Actions

**Статус: ❌ CRITICAL — CI де-факто выключен**

| Workflow | Файл |
|---|---|
| SPA CI (основной) | `ci.yml` |
| Деплой лендинга | `deploy-landing.yml` |
| CF Pages | `deploy-pages.yml` |
| SPA Frontend | `spa-frontend.yml` |
| Линтер | `spa-lint.yml` |
| Runner | `spa-run.yml` |
| Алерты | `spa_alerts.yml` |
| Тесты | `test.yml` |

**`[skip ci]` присутствует в 15/15 последних коммитах (100%).**

CI никогда не запускается. Тесты в GitHub Actions последний раз работали неизвестно когда.
Весь pipeline сломан де-факто: любые регрессии в spa_core/ проходят незамеченными.

**`ci.yml` делает правильные вещи** (smoke test import, pytest spa_core/tests/, forbidden import check, KANBAN health, SPAError audit, stdlib contract guard) — но они никогда не выполняются.

---

## 6. Тестовая Инфраструктура

**Статус: ⚠️ WARNING — нельзя запустить из sandbox (нет pytest в sandbox), CI пропускается**

| Метрика | Значение |
|---|---|
| `spa_core/tests/` файлов | **963** |
| `tests/` (корень) файлов | **249** |
| ИТОГО тест-файлов | **1,212** |
| pytest в системном python | ❌ не установлен |
| CI запускает тесты | ❌ никогда (`[skip ci]`) |

Тесты существуют в большом количестве, но их актуальность и pass rate неизвестны.
`ci.yml` корректно игнорирует `tests/test_golive_checker.py` (который требует живых данных).

---

## 7. Данные (data/) — состояние JSON

**Статус: ⚠️ WARNING — несколько аномалий**

| Файл | Размер | Последнее изменение | Статус |
|---|---|---|---|
| `paper_trading_status.json` | 1,756 B | 2026-06-20 17:22:41 | ✅ Свежий |
| `golive_status.json` | 1,183 B | 2026-06-20 19:07:13 | ✅ Свежий |
| `adapter_status.json` | 9,684 B | 2026-06-20 17:22:42 | ✅ Свежий |
| `equity_curve_daily.json` | 18,986 B | 2026-06-20 17:22:41 | ✅ Свежий |
| `autopush_state.json` | 240 B | 2026-06-20 20:23:31 | ✅ Свежий |
| `gap_monitor.json` | 257 B | 2026-06-20 17:22:42 | ✅ Свежий |
| `trades.json` | 6,330 B | 2026-06-20 17:22:41 | ✅ Свежий |
| `current_positions.json` | 917 B | 2026-06-20 17:22:41 | ✅ Свежий |
| `risk_policy_blocks.json` | 10,046 B | 2026-06-20 14:33:12 | ✅ OK |
| `tournament_results.json` | — | — | ❌ **MISSING** |

**Текущий trading status:**
```
equity:            $100,120.13  (+$120.13 / +0.12%)
apy_today_pct:     4.3869%
days_running:      32
last_cycle_status: ok
kill_switch:       False
is_demo:           False
```

**Аномалия #1 — Equity curve: 20 pre-track записей** ❌
`equity_curve_daily.json` содержит **31 запись**: с `2026-05-21` по `2026-06-20`.
CLAUDE.md: реальный трек начат **2026-06-10**. Это означает 20 дней (21 мая — 9 июня) с `is_demo: false` — **до начала реального трека**. GoLive checker считает `no_demo_data: true` (проверяет только флаг is_demo на верхнем уровне, не даты), но track record содержит 20 "фантомных" дней.

**Аномалия #2 — risk_policy_blocks: массовые блокировки сегодня** ⚠️
2 блока зафиксированы 14:32-14:33 UTC сегодня. В каждом: **23 протокола вернули APY=0% и TVL=$0**:
```
aave_v3, aave_arbitrum, aave_v3_optimism, aave_v3_polygon,
morpho_steakhouse, spark_susds, euler_v2, maple, yearn_v3,
pendle, morpho_blue, susde, fluid_fusdc, sfrax, wusdm,
scrvusd, stusd, sdai, frax, aave_v3_base, morpho_blue_base,
moonwell_base, extra_finance_base
```
Живые позиции заморожены в старом составе (5 протоколов: compound_v3, aave_v3, yearn_v3, euler_v2, maple). Ребаланс заблокирован. Успешный цикл в 17:22 прошёл, но это значит что DeFiLlama feed был недоступен ранее.

**Аномалия #3 — golive_status.json: `checked_at: null`** ⚠️
Поле `checked_at` пустое несмотря на `timestamp: 2026-06-20T19:07:13`. Две даты вместо одной — потенциальная путаница в API.

**Аномалия #4 — tournament_results.json MISSING** ❌
Файл не существует. Tournament evaluator (S0-S10) не генерирует отчёт или сохраняет в другое место.

---

## 8. Cloudflare / earn-defi.com

**Статус: ⚠️ WARNING — cloudflared упал, HTTP сервер отдаёт 404**

**wrangler.toml** (CF Pages):
```toml
name = "earn-defi"
pages_build_output_dir = "landing/dist"
```

**cloudflared:**
- Последний лог: `2026-06-18 16:34` — `"control stream encountered a failure while serving"`
- Паттерн: цикличные reconnect → fail → retry — tunnel нестабилен
- После 2026-06-18 16:34 — нет активности в логах (2 дня молчания)

**HTTP сервер (family_fund/http_server, port 8765):**
- `dashboard_server.err` (2026-06-18): **404 на все запросы** — `/`, `/api/status`, `/health`, `/spa_data/`, `/index.html`
- Сервер работает но ни один маршрут не обслуживается. Вероятная причина: `http_server.py` запускается не из `~/Documents/SPA_Claude/` или неправильный working directory.

---

## 9. Безопасность: Секреты

**Статус: ✅ OK (с одним замечанием)**

- **Нет hardcoded PAT-токенов** в spa_core/ коде ✅
- PAT корректно читается из macOS Keychain (`GITHUB_PAT_SPA`) ✅
- `ANTHROPIC_API_KEY` только из `os.getenv()` ✅
- Telegram token только через `security find-generic-password` ✅

**Замечание (не критично):**
10 старых push_v*.sh скриптов (v818, v849, v859, v828 и другие) содержат fallback `cat ~/.github_pat` — файл-секрет в дополнение к Keychain. Это допустимо как fallback, но расширяет attack surface.

**LLM_FORBIDDEN_AGENTS расхождение:**
- CLAUDE.md: `{risk, execution, monitoring}`
- `spa_core/agents/model_config.py`: `LLM_FORBIDDEN_AGENTS = {"risk", "execution"}` — **`monitoring` отсутствует**

---

## 10. Размер Кодовой Базы

**Статус: ✅ OK**

| Метрика | Значение |
|---|---|
| Python файлов в `spa_core/` | **2,199** |
| Строк кода в `spa_core/` | **352,569** |
| Тест-файлов в `spa_core/tests/` | **963** |
| Тест-файлов в `tests/` (корень) | **249** |
| Файлов в `scripts/` | **363** |
| — из них `push_v*.sh` | 188 |
| — из них `*.plist` | 21 |
| — из них `*.sh` | 266 |
| — из них `*.py` | 55 |
| — из них `*.command` | 15 |

Кодовая база большая и хорошо структурированная. Отношение тестов к коду ~44% (963/2199 файлов включают тесты).

---

## ПРИОРИТИЗИРОВАННЫЙ СПИСОК ПРОБЛЕМ

### P0 — Критические (блокируют go-live или целостность данных)

**P0-1: Equity curve содержит 20 pre-track записей с `is_demo: false`**
- Файл: `data/equity_curve_daily.json`
- Проблема: 20 записей (2026-05-21 → 2026-06-09) помечены как реальный трек, хотя реальный трек начат 2026-06-10. `no_demo_data` в GoLive checker проходит ошибочно (проверяет только top-level флаг).
- Риск: track record искажён на 20 дней. Если кто-то смотрит "30 честных дней" — они начинаются не с 10 июня.
- Действие: проверить как эти 20 дней попали туда; пересчитать `days_running` от 2026-06-10.

**P0-2: CI полностью выключен (`[skip ci]` в 100% коммитов)**
- Файл: все коммиты в git log
- Проблема: тест-сюит из 1,212 файлов никогда не выполняется автоматически. Регрессии невидимы.
- Действие: убрать `[skip ci]` хотя бы в критических коммитах; или добавить scheduled CI (раз в сутки без `push` trigger).

**P0-3: `com.spa.autopush` НЕ установлен — единственный GoLive блокер**
- Подтверждение: GoLive checker, `data/golive_status.json`
- Действие: `cp scripts/com.spa.autopush.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.spa.autopush.plist`

### P1 — Важные (деградация функциональности)

**P1-1: Нет подтверждения что daily_cycle работает через launchd**
- Доказательства: нет `logs/daily_cycle_20260620.log`, нет `logs/launchd_stdout.log`, нет `logs/launchd_stderr.log`.
- Данные в data/ свежие (17:22 UTC) — цикл запускается, но возможно вручную, не через launchd.
- Риск: если launchd не установлен — цикл не запустится в 08:00, когда пользователь не за компьютером.
- Действие: `launchctl list com.spa.daily_cycle` — проверить статус на реальной машине.

**P1-2: HTTP server отдаёт 404 на все маршруты**
- Файл: `logs/dashboard_server.err`
- Проблема: `/`, `/api/status`, `/health`, `/index.html` — всё 404. Инвесторский портал недоступен.
- Действие: проверить working directory `com.spa.httpserver.plist` и routes в `spa_core/family_fund/http_server.py`.

**P1-3: cloudflared падал 2026-06-18, статус неизвестен**
- Файл: `logs/cloudflared.err`
- Паттерн: "control stream failure" → retry loop. Внешний доступ к earn-defi.com может быть недоступен.
- Действие: `launchctl list com.spa.cloudflared` + `tail -f /tmp/spa_cloudflared.log`.

**P1-4: tournament_results.json MISSING**
- Следствие: Tournament tab в dashboard пуст. Multi-strategy runner (S0-S10) не пишет результаты.
- Действие: `python3 -m spa_core.paper_trading.multi_strategy_runner --verbose` и проверить куда пишет.

**P1-5: 23 адаптера периодически возвращают APY=0 / TVL=$0**
- Файл: `data/risk_policy_blocks.json` (2 блока сегодня 14:32-14:33)
- Следствие: RiskPolicy блокирует ребаланс, портфель "заморожен" в старых позициях.
- Возможные причины: DeFiLlama API временно недоступен, rate limiting, timeout.
- Действие: проверить `data/adapter_status.json` на timestamp последнего успешного fetch; добавить retry или стale-cache в defillama_feed.py.

**P1-6: 622 грязных файла в git (570 untracked + 52 modified)**
- Риск: любой `git reset --hard` или clone с нуля уничтожит 570 файлов которых нет в remote.
- Действие: проверить какие из 570 untracked файлов ценны; добавить в .gitignore или закоммитить.

### P2 — Замечания (tech debt, не блокируют работу)

**P2-1: `monitoring` отсутствует в `LLM_FORBIDDEN_AGENTS` в коде**
- Файл: `spa_core/agents/model_config.py` строка 45
- CLAUDE.md декларирует `{risk, execution, monitoring}`, код имеет `{"risk", "execution"}`.
- Действие: добавить `"monitoring"` в set.

**P2-2: Дублирующиеся коммиты в git history**
- v8.89 MP-1243 появляется 8+ раз с разными хэшами. Мусор в истории.
- Причина: push_to_github.py через API не проверял существующие коммиты.
- Действие: косметически — `git rebase -i` для squash (осторожно, меняет хэши).

**P2-3: `spa_core/requirements.txt` нарушает декларацию "только stdlib"**
- Файл включает fastapi, uvicorn, pydantic, reportlab, alembic — явно не stdlib.
- CLAUDE.md: "только stdlib Python — без внешних зависимостей в runtime-коде".
- Вероятно это intentional для M5 REST API сервера, но нужна явная документация.

**P2-4: run_daily_paper_cycle.sh запускает `CPACycleWithEvidence` вместо `cycle_runner`**
- CLAUDE.md описывает `python3 -m spa_core.paper_trading.cycle_runner` как основной entry point.
- Plist запускает `spa_core.backtesting.cpa_cycle_with_evidence.CPACycleWithEvidence`.
- Это может быть OK (если CPA wrap вызывает cycle_runner внутри), но нужна проверка.

**P2-5: `golive_status.json` имеет `checked_at: null` при наличии `timestamp`**
- Два поля с датой вместо одного, одно пустое. Небольшая несогласованность API.

**P2-6: Старые push_v*.sh скриптов ищут `scripts/push_to_github.py`**
- `push_to_github.py` находится в корне, не в `scripts/`. Старые скрипты (до ~v900) падают.
- `auto_push_err.log` заполнен этими ошибками. `failed=1` в последнем прогоне.

---

## Итоговая таблица

| # | Проблема | Приоритет | Файл / источник |
|---|---|---|---|
| 1 | Pre-track данные в equity curve (20 дней до 2026-06-10) | **P0** | data/equity_curve_daily.json |
| 2 | CI полностью пропускается (`[skip ci]` 100%) | **P0** | git history |
| 3 | autopush launchd не установлен (GoLive блокер) | **P0** | golive_status.json |
| 4 | daily_cycle launchd — нет подтверждения работы | **P1** | logs/ (пустые) |
| 5 | HTTP server 404 на все маршруты | **P1** | logs/dashboard_server.err |
| 6 | cloudflared нестабилен (2 дня без активности) | **P1** | logs/cloudflared.err |
| 7 | tournament_results.json MISSING | **P1** | data/ |
| 8 | 23 адаптера периодически APY=0/TVL=0 | **P1** | risk_policy_blocks.json |
| 9 | 570 untracked файлов не в git | **P1** | git status |
| 10 | `monitoring` нет в LLM_FORBIDDEN_AGENTS | **P2** | agents/model_config.py |
| 11 | Дублирующиеся коммиты в истории | **P2** | git log |
| 12 | requirements.txt нарушает stdlib-only | **P2** | spa_core/requirements.txt |
| 13 | CPACycleWithEvidence ≠ cycle_runner в plist | **P2** | scripts/run_daily_paper_cycle.sh |
| 14 | Старые push scripts ищут push_to_github.py в scripts/ | **P2** | logs/auto_push_err.log |
