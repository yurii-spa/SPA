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

## 📊 Текущее состояние (2026-06-25)

> ⚠️ Живые цифры — `docs/SYSTEM_BRIEFING.md` (auto, 30 мин) + `data/golive_status.json` +
> `data/paper_trading_status.json`. Таблица ниже — снимок, может дрейфовать.

| Поле | Значение |
|---|---|
| Реальный трек | начат **2026-06-10** (всё до — демо, недействительно) |
| Дней трека | **16/30** (14 ещё нужно, target go-live **~2026-07-09**) |
| Капитал | **$100,180.31** (+0.18% за 16д) |
| Daily yield | **$9.91/день** · APY сегодня ~3.6% (regime VOLATILE) |
| GoLive | ⛔ **27/29 pass** — NOT READY (2 time-gated блокера) |
| Sprint | **v12.83** · Done: **1358** · Backlog: 0 |
| Агенты | ✅ **~42 загружено** (`launchctl list \| grep spa` = 42; agent_health crit=0; источник истины — launchctl / SYSTEM_BRIEFING, НЕ это число) |
| Repo | `yurii-spa/SPA` (GitHub) |
| Python | `/Users/yuriikulieshov/miniconda3/bin/python3` (всегда этот путь) |

**GoLive блокеры (оба — просто ожидание 30 трек-дней, нечего чинить кодом):**
- `gap_monitor_30d`: 16/30 трек-дней (14 дней просто ждать)
- `min_track_days_30`: то же что gap_monitor
- (`autopush_installed` теперь **PASS** на реальном Mac; в sandbox/CI всегда fails — проверяй через `launchctl list | grep spa`)

---

## ⚙️ LaunchAgents (установлены 2026-06-22, FAIL=0)

~42 агента в `~/Library/LaunchAgents/` — переживают перезагрузку. Таблица ниже —
лишь ключевые; полный актуальный список ВСЕГДА `launchctl list | grep spa` (это число
дрейфует, не доверяй ему — доверяй launchctl/SYSTEM_BRIEFING). `com.spa.system_briefing`
доустановлен 2026-06-24.

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
| `com.spa.strategy_lab_paper` | каждый час | ✅ |
| `com.spa.refusal` | 05:45 local (advisory) | ✅ |
| `com.spa.rates_desk_paper` | каждый час (advisory) | ✅ NEW |

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

Реестр — `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`. **35 адаптеров в реестре** (live-feed `num_adapters_live` в `paper_trading_status.json` ~34).
**Read-only домен** — никогда не пишет в `data/adapter_status.json` (execution-домен).
Проверка количества: `python3 -c "from spa_core.adapters import ADAPTER_REGISTRY; print(len(ADAPTER_REGISTRY))"`.

| Tier | Протоколы |
|---|---|
| T1 | Aave V3 (ETH/ARB/OP/POLY/BASE), Compound V3, Morpho Steakhouse, Spark sUSDS |
| T2 | Morpho Blue, Yearn V3, Euler V2, Maple, Fluid, sFRAX, sDAI, Ethena sUSDe, Ondo USDY, Pendle PT/YT, Aerodrome LP, **BTC-lending** |
| T3 | Points farming (advisory), leverage looping (IS_ADVISORY=True) |

**BTC lending (NEW, 2026-06-25):** read-only `tbtc_lending` + `cbbtc_lending` (`spa_core/adapters/btc_lending.py`,
T2, `IS_ADVISORY=True`/`RESEARCH_ONLY=True`). Честный **~0% APY** — BTC почти не *занимают* on-chain
(utilization ~2–6%, supply APY ~0–1.2%). WBTC исключён (BitGo→BiT Global governance overhang),
LBTC-restaking отклонён (points/airdrop-leverage). Advisory → никогда не аллоцирует live.

APY feed: `spa_core/adapters/defillama_feed.py` (DeFiLlama, TTL 300с).
Sky/sUSDS: `sky_susds` — 0% до подтверждённого GSM Pause Delay ≥ 48h (on-chain).

---

## 🏆 Стратегии (Tournament: S0–S77+)

Реестр: `spa_core/strategies/strategy_registry.py`.
Оркестратор: `spa_core/paper_trading/multi_strategy_runner.py`.

Все новые стратегии (S71+) имеют `IS_ADVISORY=True` — simulate only, не открывают live позиции.

---

## 🧪 Strategy Lab (NEW, 2026-06-25)

`spa_core/strategy_lab/` — несколько yield-стратегий и sleeve'ов прогоняются через **один общий
backtest-harness** + **один live paper-сервис** (без капитала) для честного risk-adjusted сравнения
против RWA-floor. Pluggable `Strategy` ABC (`base.py`); harness не меняется при добавлении стратегии.
stdlib-only, детерминированный, LLM запрещён в risk/kill. Полный док — `docs/STRATEGY_LAB.md`.

| id | что это |
|---|---|
| `variant_n` | LRT (eETH) спот + short ETH-perp, β≈0 (hedged) |
| `variant_d` | чистый LRT, без хеджа, β≈1 (directional, изолированный sleeve) |
| `eth_lst_neutral` | **NEW — SAFE hedged ETH**: PLAIN LST (stETH/rETH, НЕ LRT) + short perp, β≈0; рекомендуемый ETH-подход (LST ближе к пегу → меньше depeg-residual) |
| `rwa_sleeve` | **NEW — T1 RWA cash-floor**: держит tokenized-T-bills (BUIDL/USYC/USDY…), accrues по live-ставке; реализованный floor, не бенчмарк |
| baselines | `engine_a/b/c` (реальные Engine A/B/C) + `rwa_floor` (zero-vol бенчмарк) |

- **5-venue funding feed** (`data/funding_feed.py`): медиана Binance / Bybit / OKX / KuCoin / Hyperliquid
  (HL hourly→8h нормализуется), ~2 года истории через пагинацию keyless-endpoint'ов.
- **Real RWA floor** (`data/rwa_feed.py`): live tokenized-T-bills (~$15B рынок), TVL-weighted ≈ **~3.4%** —
  НЕ хардкод; fail-closed, fallback на committed-литерал только если фид недоступен.
- Live paper: `com.spa.strategy_lab_paper` (launchd, hourly, restart-survival) →
  `scripts/strategy_lab_paper.py`; backtest → `scripts/strategy_lab_backtest.py`.

---

## 📐 Rates Desk (NEW, 2026-06-26 — validated thesis-#1 build)

`spa_core/strategy_lab/rates_desk/` — **on-chain rates/basis sleeve**: собирает живой fixed/implied-rate
`RateSurface` (Pendle PT / lending / boros) и прогоняет каждый underlying через **refusal-first** гейт.
Тезис: edge = risk-adjusted fair-value модель, которая **харвестит реальный mispriced carry и ОТКАЗЫВАЕТСЯ**
от yield, который лишь компенсация хвостового риска (ezETH / over-levered-USDe паттерн). stdlib-only,
детерминированный, **LLM запрещён** в risk/kill, **fail-CLOSED**. Полный док — `docs/RATES_DESK.md`.

- **Движок:** `feeds.build_surface` (live `RateSurface`) → `FairValueEngine` (kind-aware baseline − 5
  структурных хейркатов → fair implied yield) → **refusal-first гейт** `rate_policy.py` (`evaluate_entry` /
  `evaluate_hold`, композируется ПОД глобальным `RiskPolicy`, только строже) → `OpportunityEngine.scan`.
- **4 trade-shape** (`contracts.TradeShape`): `FIXED_CARRY` (A, PT-to-maturity — **единственный валидированный/live-paper**),
  `LEVERED_CARRY` (B), `BASIS_HEDGE` (C — **BLOCKED-NO-HEDGE**, отложен: CEX-leg не построен), `RATE_MATRIX` (D).
- **Sleeves** (`sleeves.py`, все `Strategy` ABC, `IS_ADVISORY=True`): `FixedCarrySleeve` (Phase-0, GO),
  + Phase-1 `BasisHedgeSleeve` / `LeveredCarrySleeve` / `RateMatrixSleeve` (research-only до прохождения гейта).
- **Валидация GO** (`docs/RATES_DESK_VALIDATION.md`): Assertion 1 (refusal fired early) = **PASS** —
  toxic LRT PT-книги отказаны structural-причинами по реальной 2024–2026 истории; Assertion 2 (survivor book
  beats ~3.4% RWA floor risk-adjusted across stress) = **GO** — carry leg реален → **fundable**.
- **Агент:** `com.spa.rates_desk_paper` (launchd, hourly, RunAtLoad, restart-survival, idempotent per UTC day)
  → `python3 -m spa_core.strategy_lab.rates_desk.paper_rates` (один tick) → растущий forward carry track в
  `data/rates_desk/paper/` + кормит proof-chain (entries И refusals). Advisory: капитал не двигает, go-live трек не трогает.
  Дневной refusal-scorer — отдельный `com.spa.refusal` → `data/refusal_status.json`.
- **API** (`spa_core/api/server.py`): `/api/rates-desk/surface`, `/api/rates-desk/opportunities`,
  `/api/rates-desk/decisions` (entries + refusals + proof_hash), `/api/refusal` (per-underlying SAFE/WATCH/REFUSE/UNKNOWN).

---

## 🌐 Сайт (rebuilt 2026-06-25, unified design system)

Лендинг (`landing/`, Astro → CF Pages, **earn-defi.com**) пересобран на едином дизайн-системе —
`docs/SITE_DESIGN_SYSTEM.md`. Канонические `SiteHeader`/`SiteFooter` в `Layout.astro` на каждой
странице (NOT touch — пушится параллельно). Console-homepage, новые страницы `/track-record`,
`/research`, `/system`, `/disclaimer`; приложение на `/app` (раньше `/dashboard`); публичная
Proof-of-Reserves поверхность. Двуязычно (EN|RU) по всему сайту.

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
| `golive_status.json` | 29 критериев GoLive (27/29 pass, NOT READY) |
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

*Обновлено: 2026-06-26 (v12.85 — добавлена секция **Rates Desk** (validated thesis-#1: RateSurface +
FairValueEngine refusal-first гейт + 4 trade-shape + FixedCarry GO; новый агент `com.spa.rates_desk_paper`
hourly advisory live-paper + `/api/rates-desk/*`; док `docs/RATES_DESK.md`); agent-table: +strategy_lab_paper
/refusal/rates_desk_paper). v12.84 — docs audit: state-table sync 16/30·$100,180·27/29, ~42 агента; реестр
**35 адаптеров** (+BTC tbtc/cbbtc advisory); секции **Strategy Lab** (eth_lst_neutral + rwa_sleeve + 5-venue
funding + real RWA floor ~3.4%) и **Сайт** (unified design system, /track-record /research /system /disclaimer
/app, EN|RU); source of truth = launchctl/SYSTEM_BRIEFING; agent_health честно зелёный.*
