# SPA — Smart Passive Aggregator · CLAUDE.md

---

## ⚡ ПЕРВЫМ ДЕЛОМ (обязательно в начале каждой сессии)

**Прочитай `docs/SYSTEM_BRIEFING.md` прежде чем отвечать на любой вопрос о состоянии системы.**

```bash
cat ~/Documents/SPA_Claude/docs/SYSTEM_BRIEFING.md
```

Файл обновляется автоматически каждые 30 минут агентом `com.spa.system_briefing`.
Без этого чтения — нельзя говорить "всё работает", "агенты установлены", "portfolio в порядке".

**Триггеры для обязательного чтения:** "как дела", "что работает", "агенты", "portfolio",
"GoLive", "health", "daily cycle", "как система", любые вопросы об оперативном состоянии.

---

## Что это

SPA — автономный DeFi yield optimizer на стадии paper trading. Виртуальный капитал
**$100,000 USDC**: ежедневный цикл получает живые APY/TVL из whitelisted-протоколов,
прогоняет через детерминированный RiskPolicy и ребалансирует виртуальный портфель.

**Цель:** $1M/год дохода; оценка $100M через управление внешним AUM после подтверждённого
track record (30 честных дней → go-live). Финмодель — `MASTER_PLAN_v1.md`.

**Источник истины:** `MASTER_PLAN_v1.md` (задачи MP-xxx) → `KANBAN.json` → `docs/SYSTEM_BRIEFING.md`.

---

## 📊 Текущее состояние (2026-06-22)

| Поле | Значение |
|---|---|
| Реальный трек | начат **2026-06-10** (всё до — демо, недействительно) |
| Дней трека | **13/30** (17 ещё нужно, target go-live **~2026-07-09**) |
| Капитал | **$100,149.54** (+0.15% за 13д) |
| Daily yield | **$13.44/день** · APY сегодня ~4.9% |
| GoLive | ⛔ **26/29 pass** — NOT READY (3 блокера) |
| Sprint | **v12.82** · Done: **1358** · Backlog: 0 |
| Агенты | ✅ **12/12 установлены** (FAIL=0, 2026-06-22 14:48) |
| Push queue | 7 скриптов v1357–v1363 ждут autopush (~90 мин цикл) |
| Repo | `yurii-spa/SPA` (GitHub) |
| Python | `/Users/yuriikulieshov/miniconda3/bin/python3` (всегда этот путь) |

**GoLive блокеры:**
- `gap_monitor_30d`: 13/30 трек-дней (17 дней просто ждать)
- `autopush_installed`: always fails in sandbox/CI — на реальном Mac проверяй через `launchctl list | grep spa`
- `min_track_days_30`: то же что gap_monitor

---

## ⚙️ LaunchAgents (установлены 2026-06-22, FAIL=0)

Все 12 агентов в `~/Library/LaunchAgents/` — переживают перезагрузку.

| Агент | Расписание | Статус |
|---|---|---|
| `com.spa.autopush` | каждые 90 мин | ✅ |
| `com.spa.rules_watchdog` | каждые 5 мин | ✅ |
| `com.spa.cycle_gap_monitor` | ежедневно | ✅ |
| `com.spa.daily_cycle` | 08:00 UTC | ✅ (log missing — проверить) |
| `com.spa.system_health_morning` | 08:30 UTC | ✅ |
| `com.spa.system_health_evening` | 20:30 UTC | ✅ |
| `com.spa.agent_health` | каждый час | ✅ |
| `com.spa.tournament_engine` | 09:00 UTC | ✅ NEW |
| `com.spa.cycle_health` | каждые 15 мин | ✅ |
| `com.spa.uptime_monitor` | каждые 5 мин | ✅ |
| `com.spa.cloudflared` | KeepAlive | ✅ |
| `com.spa.morning_digest` | 08:05 UTC | ⚠️ exit=1 (Telegram issue) |
| `com.spa.system_briefing` | каждые 30 мин | ✅ NEW |

Переустановить все: `bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh`

---

## 🏗️ Архитектура (реальный runtime)

```
Mac Mini (production host) — earn-defi.com
│
├── launchd com.spa.daily_cycle (08:00 UTC)
│     └── python3 -m spa_core.paper_trading.cycle_runner --verbose
│           1. adapter orchestrator (read-only) → живой APY/TVL
│           2. multi_strategy_runner → стратегии S1–S77 (Tournament)
│           3. StrategyAllocator → целевая аллокация с cap'ами
│           4. RiskPolicy gate (детерминированный, LLM FORBIDDEN)
│           5. virtual rebalance → data/trades.json
│           6. daily yield accrual → data/equity_curve_daily.json
│           7. GoLiveChecker → data/golive_status.json (29 критериев)
│
├── launchd com.spa.autopush (каждые 90 мин)
│     └── обрабатывает push_v*.sh скрипты → GitHub
│
├── launchd com.spa.tournament_engine (09:00 UTC)
│     └── TournamentEngine.run_daily() → backtest→paper→live pipeline
│
├── launchd com.spa.system_briefing (каждые 30 мин)
│     └── update_system_briefing.py → docs/SYSTEM_BRIEFING.md
│
├── launchd com.spa.httpserver — HTTP API port 8765 (FastAPI)
│     └── api.earn-defi.com (Cloudflare Tunnel)
│
└── Cloudflare Pages — earn-defi.com (статика из docs/)
      docs/tournament.html — Tournament страница (live via /api/tournament)
      index.html — Dashboard v3.0 (live via /api/live/ping)
```

**Стек:** Python 3, **только stdlib** в runtime. Атомарные записи: `shutil.move` (не `os.replace` — cross-device в sandbox).

---

## 🎯 Tournament Engine (NEW, 2026-06-22)

```
spa_core/tournament/tournament_engine.py   — TournamentEngine.run_daily()
spa_core/tournament/tournament_telegram.py — daily Telegram alerts
launchd/com.spa.tournament_engine.plist    — запуск 09:00 UTC
data/mass_tournament_results.json          — 60 стратегий ранжированы по Sharpe
data/strategy_tournament.json             — 5 активных shadow traders
docs/tournament.html                       — live страница на сайте
```

Фазы: `backtest → paper_30d → live`. Promotion criteria: Sharpe ≥ 1.5, ≥ 7 дней paper, APY ≥ 3%, drawdown ≥ -15%.

---

## 📈 Адаптеры (spa_core/adapters/)

Реестр — `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`. **27 адаптеров live.**
**Read-only домен** — никогда не пишет в `data/adapter_status.json` (execution-домен).

| Tier | Протоколы |
|---|---|
| T1 | Aave V3 (ETH/ARB/OP/POLY/BASE), Compound V3, Morpho Steakhouse, Spark sUSDS |
| T2 | Morpho Blue, Yearn V3, Euler V2, Maple, Fluid, sFRAX, sDAI, Ethena sUSDe, Ondo USDY, Pendle PT/YT, Aerodrome LP |
| T3 | Points farming (advisory), leverage looping (IS_ADVISORY=True) |

APY feed: `spa_core/adapters/defillama_feed.py` (DeFiLlama, TTL 300с).
Sky/sUSDS: `sky_susds` — 0% до подтверждённого GSM Pause Delay ≥ 48h (on-chain).

---

## 🏆 Стратегии (Tournament: S0–S77+)

Реестр: `spa_core/strategies/strategy_registry.py`.
Оркестратор: `spa_core/paper_trading/multi_strategy_runner.py`.

Все новые стратегии (S71+) имеют `IS_ADVISORY=True` — simulate only, не открывают live позиции.

---

## 💰 RiskPolicy (LLM FORBIDDEN)

`spa_core/risk/policy.py` — детерминированный, никаких LLM-вызовов.

| Параметр | Значение |
|---|---|
| TVL floor | ≥ $5M на пул |
| Per-protocol cap | 40% T1 / 20% T2 |
| T2 total cap | ≤ 50% портфеля |
| APY-границы | 1% … 30% |
| Min cash buffer | ≥ 5% |
| Kill switch | drawdown ≥ 5% → всё закрыть |

`approved=False` не может быть переопределён никем.

---

## 🔑 Secrets & Push

```bash
# PAT из Keychain (никогда не хардкодить):
security find-generic-password -s GITHUB_PAT_SPA -w

# Push в GitHub:
cd ~/Documents/SPA_Claude
python3 push_to_github.py --files /abs/path/a.py --message "msg"
# Или через push_v*.sh скрипты → autopush (90 мин)

# Telegram tokens:
security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w
security find-generic-password -s TELEGRAM_CHAT_ID_SPA -w
```

**SECRETS POLICY:** Никогда не писать токены/ключи/PAT ни в один файл. Инцидент 2026-06-10 — PAT утёк в 90+ файлов.

---

## Структура репо

| Путь | Назначение |
|---|---|
| `spa_core/adapters/` | Read-only адаптеры + DeFiLlama feed |
| `spa_core/paper_trading/` | cycle_runner.py, golive_checker.py, gap_monitor.py |
| `spa_core/strategies/` | Tournament стратегии S0–S77+ |
| `spa_core/risk/` | policy.py (детерминированный, LLM FORBIDDEN) |
| `spa_core/tournament/` | TournamentEngine, TournamentTelegram |
| `spa_core/api/` | FastAPI server (api.earn-defi.com:8765) |
| `spa_core/monitoring/` | system_health_monitor.py, agent_health.py |
| `spa_core/execution/` | **НЕ импортировать** из read-only кода |
| `spa_core/family_fund/` | http_server.py (port 8765), pnl_attribution.py |
| `data/` | Все JSON-state файлы |
| `docs/` | SYSTEM_BRIEFING.md, ADR, tournament.html, index.html |
| `scripts/` | LaunchAgent plists, install_all_agents.sh, push_v*.sh |
| `launchd/` | LaunchAgent plists (tournament, rules_watchdog) |
| `KANBAN.json` | Kanban (источник MP-xxx задач) |

---

## Ключевые data/*.json

| Файл | Что |
|---|---|
| `golive_status.json` | 29 критериев GoLive (26/29 pass, NOT READY) |
| `gap_monitor.json` | Непрерывность трека (13/30 дней) |
| `trades.json` | Виртуальные трейды (ring-buffer 500) |
| `equity_curve_daily.json` | Дневная equity (ring-buffer 365) |
| `current_positions.json` | 23 активные позиции |
| `paper_trading_status.json` | Сводный статус (последний цикл 2026-06-22 06:00 UTC) |
| `system_health.json` | Health check по доменам |
| `mass_tournament_results.json` | 60 стратегий, Sharpe ranking |
| `strategy_tournament.json` | 5 shadow traders |

---

## Команды

```bash
# Статус агентов (на Mac):
bash ~/Documents/SPA_Claude/scripts/agent_status.sh
launchctl list | grep spa

# Дневной цикл вручную:
python3 -m spa_core.paper_trading.cycle_runner --verbose

# GoLive check:
python3 -m spa_core.paper_trading.golive_checker

# System health:
python3 -m spa_core.monitoring.system_health_monitor

# Обновить SYSTEM_BRIEFING.md сейчас:
python3 ~/Documents/SPA_Claude/scripts/update_system_briefing.py

# Все тесты:
python3 -m pytest spa_core/tests/ -v

# Переустановить всех агентов:
bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh

# Push:
python3 push_to_github.py --files /abs/path/file.py --message "vX.XX: desc"
```

---

## 🚫 FORBIDDEN (никогда не нарушать)

1. **SYSTEM_BRIEFING.md** — читать первым в каждой сессии, прежде чем говорить о состоянии системы.
2. **Не импортировать** `execution/` из read-only / paper-кода.
3. **Только stdlib** Python в runtime-коде — без внешних зависимостей.
4. **Атомарные записи** — `shutil.move(tmp, dst)`, никогда прямой `open(..., "w")` на state-файлы.
5. **LLM запрещён** в risk / execution / monitoring компонентах.
6. **Не встраивать PAT** в файлы, не создавать `push_*.html`.
7. **RiskPolicy version = "v1.0"** весь paper-период; изменение → новый ADR.
8. **Sky/sUSDS = 0%** до подтверждённого GSM Pause Delay ≥ 48h on-chain.
9. **Атомарный KANBAN** — перечитывать с диска перед записью (конкурентный процесс).
10. **IS_ADVISORY=True** для всех новых стратегий T2/T3 до go-live.

---

*Обновлено: 2026-06-22 (v12.82 — мигрировано в Claude Code; 12 агентов установлены; tournament engine; SYSTEM_BRIEFING.md mandatory read).*
