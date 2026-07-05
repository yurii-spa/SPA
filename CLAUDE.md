# SPA — Smart Passive Aggregator · CLAUDE.md

> **IMPORTANT — before working on this repository, read [`PROJECT_CONTROL/00_START_HERE.md`](PROJECT_CONTROL/00_START_HERE.md)** (source-of-truth, deploy topology, two-agent separation, verification commands). Consolidates existing docs; does not replace them.


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

## 📊 Текущее состояние (2026-06-27)

> ⚠️ Живые цифры — `docs/SYSTEM_BRIEFING.md` (auto, 30 мин) + `data/golive_status.json` +
> `data/paper_trading_status.json`. Таблица ниже — снимок, может дрейфовать.

| Поле | Значение |
|---|---|
| Реальный трек | anchor **2026-06-22** (evidenced; всё до — backfill/демо, недействительно) |
| Дней трека | **9/30** evidenced (21 ещё нужно, target go-live **~2026-07-21**) |
| Капитал | живые цифры — `data/golive_status.json` / SYSTEM_BRIEFING (снимок дрейфует) |
| GoLive | ⛔ **27/29 pass** — NOT READY (2 time-gated блокера) |
| Sprint | **v12.86+** · Backlog: 0 (точные счётчики — KANBAN.json) |
| Агенты | ✅ **~45 загружено** (`launchctl list \| grep -c com.spa` = 45 на этом Mac после retirement'ов; agent_health crit=0; источник истины — launchctl / SYSTEM_BRIEFING, НЕ это число — оно дрейфует) |
| Repo | `yurii-spa/SPA` (GitHub) |
| Python | `/Users/yuriikulieshov/miniconda3/bin/python3` (всегда этот путь) |

**GoLive блокеры (просто ожидание 30 трек-дней, нечего чинить кодом):**
- `gap_monitor_30d`: 9/30 evidenced трек-дней (21 день просто ждать)
- `min_track_days_30`: то же что gap_monitor
- (`autopush_installed` теперь **PASS** на реальном Mac; в sandbox/CI всегда fails — проверяй через `launchctl list | grep spa`)

---

## ⚙️ LaunchAgents (установлены 2026-06-22, FAIL=0)

**~45** агентов в `~/Library/LaunchAgents/` (`launchctl list | grep -c com.spa` = 45 на этом
Mac после retirement'ов) — переживают перезагрузку. Таблица ниже — лишь ключевые; полный
актуальный список ВСЕГДА `launchctl list | grep spa` (это число дрейфует, не доверяй ему —
доверяй launchctl/SYSTEM_BRIEFING). `com.spa.system_briefing` доустановлен 2026-06-24.

**RETIRED-агенты** (`RETIRED_LABELS` в `spa_core/monitoring/agent_health_monitor.py`, источник
истины): `bot_commands`, `httpserver`, `telegram_daily`, `telegram_weekly`, `morning_digest`,
`daily-paper-report` — их plist'ы удалены и они **НЕ** должны подниматься (revival → Telegram-409 /
duplicate-flood регрессия). `agent_health` и `verify_fleet_after_reboot.sh` скипают этот набор.

| Агент | Расписание | Статус |
|---|---|---|
| `com.spa.autopush` | каждые 90 мин | ✅ |
| `com.spa.rules_watchdog` | каждые 5 мин | ✅ |
| `com.spa.cycle_gap_monitor` | ежедневно | ✅ |
| `com.spa.daily_cycle` | 08:00 UTC | ✅ (логи в `/tmp/spa_daily_cycle.log` после миграции) |
| `com.spa.system_health_morning` | 08:30 UTC | ✅ |
| `com.spa.system_health_evening` | 20:30 UTC | ✅ |
| `com.spa.agent_health` | каждый час | ✅ |
| `com.spa.tournament_engine` | 09:00 UTC | ✅ NEW |
| `com.spa.cycle_health` | каждые 15 мин | ✅ |
| `com.spa.uptime_monitor` | каждые 5 мин | ✅ |
| `com.spa.cloudflared` | KeepAlive | ✅ |
| `com.spa.system_briefing` | каждые 30 мин | ✅ NEW |
| `com.spa.strategy_lab_paper` | каждый час | ✅ |
| `com.spa.refusal` | 05:45 local (advisory) | ✅ |
| `com.spa.rates_desk_paper` | каждый час (advisory) | ✅ |
| `com.spa.rwa_safety_board` | ежедневно (advisory) | ✅ NEW |
| `com.spa.daily_backup` | ежедневно | ✅ NEW |
| `com.spa.rtmr_sense` | KeepAlive (~45с tick) | ✅ NEW (RTMR sense-loop, paper) |

Переустановить все: `bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh`

### 🔄 После ребута / OS-обновления

Агенты — **gui-domain** LaunchAgents → грузятся при **логине пользователя** (НЕ при boot).
После ребута: **залогинься один раз** → launchd сам поднимет весь fleet (RunAtLoad запустит
one-shot'ы, KeepAlive — демоны apiserver/bot/cloudflared, расписания возобновятся; self_heal
добьёт отставших). Все plist'ы на исправленном стандарте (bash-wrapper + /tmp логи) → **никакого
exit-78** при загрузке (проверено симуляцией bootout+bootstrap = exit 0).

Подтвердить/вылечить fleet одной командой после логина:
```bash
bash ~/Documents/SPA_Claude/scripts/verify_fleet_after_reboot.sh   # → ✅ FLEET HEALTHY или что чинить
```
Хелпер идемпотентен, скипает RETIRED-агентов (bot_commands/httpserver/telegram_daily/weekly/
morning_digest/daily-paper-report — их plist'ы удалены, чтобы при ребуте не поднимались дубли → 409/флуд).

**Для ПОЛНОСТЬЮ автономного восстановления без логина** (owner-решение, security trade-off):
либо включить auto-login (`Системные настройки → Пользователи → Автовход` — пароль на boot не спросит),
либо перенести критичные демоны (apiserver/cloudflared/bot) в system-domain LaunchDaemons (boot без логина, нужен sudo).
Сейчас auto-login **ВКЛЮЧЁН** (audit 2026-06-28: `autoLoginUser` выставлен + `/etc/kcpassword`
присутствует) → после ребута fleet поднимается **без ручного логина** (launchd видит gui-сессию
сразу на boot). **Security trade-off (honest):** при включённом auto-login любой, у кого физический
доступ к Mac, получает разлоченную сессию на boot без пароля, а пароль пользователя хранится
обфусцированным (НЕ зашифрованным) в `/etc/kcpassword` — это сознательный выбор владельца в пользу
автономности fleet'а. Отключить → `sysadminctl -autologin off` (тогда вернётся требование одного
ручного логина после ребута, как описано выше).

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
├── launchd com.spa.apiserver — HTTP API port 8765 (FastAPI)
│     └── api.earn-defi.com (Cloudflare Tunnel)
│
└── Cloudflare Pages — earn-defi.com (Astro-сайт из landing/, deploy-landing.yml)
      landing/src/pages/dashboard.astro — ЕДИНЫЙ canonical дашборд
        (DashboardLive.jsx island, live via api.earn-defi.com, polls ~15s)
      docs/tournament.html — Tournament страница (live via /api/tournament)
```

> Legacy github.io дашборд (root `index.html` 756KB blob + `deploy-pages.yml` +
> `spa_frontend/` React-исходник) **удалён 2026-06-28**. Единственный дашборд теперь —
> `earn-defi.com/dashboard` (Astro). Единственный frontend-деплой — `deploy-landing.yml`.

**Стек:** Python 3, **только stdlib** в runtime. Атомарные записи: канонический
`spa_core.utils.atomic.atomic_save` → tmp-файл в **той же директории** + `os.replace(tmp, dst)`
(same-dir tmp ⇒ никакого cross-device EXDEV; не прямой `open(..., "w")`).

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
  `/api/rates-desk/decisions` (entries + refusals + proof_hash), `/api/rates-desk/proof` (proof-chain),
  `/api/refusal` (per-underlying SAFE/WATCH/REFUSE/UNKNOWN), `/api/strategy-lab/promotion` (sleeve promotion ladder).
- **Safety endpoint (NEW 2026-06-27):** `/api/live/safety` (`spa_core/api/routers/live.py`) — публичная
  surface двух-tier kill-switch'а (SOFT-derisk / HARD-kill state + текущий evidenced drawdown). Парная
  health-проверка — **`d6.safety_state`** в `spa_core/monitoring/system_health_monitor.py` (домен `d6_risk_gates`).

---

## 🧭 Structural Desk — research arc (3 тезиса, NEW 2026-06-26)

Конвергентный вывод research-арки: **edge — не yield, а структурная роль measurement / underwriting**
(быть тем, кто честно меряет/андеррайтит риск, который остальные не видят). Канонический человеко-читаемый
индекс — `docs/STRUCTURAL_DESK.md`. Все три — advisory / read-only, капитал не двигают, go-live трек не трогают.

| # | Тезис | Модуль | Вердикт |
|---|---|---|---|
| 1 | **Rates Desk** — refusal-first fair-value, харвест mispriced carry / отказ от tail-comp | `spa_core/strategy_lab/rates_desk/` | ✅ **GO** (FixedCarry validated → live-paper; carry leg реален → fundable) |
| 2 | **RWA Repo Backstop** — liquidation-NAV underwriter для tokenized-RWA collateral | `spa_core/strategy_lab/rwa_backstop/` | ◐ **measurement-GO / book NO-GO** (10/10 not-cash-like; Safety Board GO, сам андеррайтинг = relationships+capital+legal off-code) |
| 3 | **Liquidator** — balance-sheet liquidator для long-tail / nested collateral | `spa_core/strategy_lab/liquidator/` | ⛔ **NO-GO** (addressable ~$2–4M/yr gross << $20M bar) |

Детальные доки: `docs/RATES_DESK.md`, `docs/RATES_DESK_VALIDATION.md`, `docs/RWA_BACKSTOP_DERISK.md`,
`docs/LIQUIDATOR_DERISK.md`. Исходный research-prompt (генератор тезисов): `docs/RESEARCH_PROMPT_MOAT.md`.
Честная рамка: код доводит тезис до verdict; **$10M — это scale / trust / relationships вне кода** (custody,
whitelisting, CEX-execution, legal). Новые агенты арки: `com.spa.refusal`, `com.spa.rwa_safety_board`,
`com.spa.rates_desk_paper`. Новые страницы сайта: `/rates-desk`, `/rwa-backstop`, `/structural-desk`.

---

## 🛡️ Resilience Plane (NEW, 2026-06-27 — R-sprint)

DR-механизмы теперь **provably exercised**, не dormant. Все три пишут собственный status JSON,
а `resilience_status.py` сворачивает их в один posture-файл:

| Модуль | Что | Status JSON |
|---|---|---|
| `spa_core/dr/offsite_copy.py` (R6) | копирует свежайший backup-архив на отдельный destination + sha256-verify | `data/dr_offsite_status.json` |
| `spa_core/dr/drill_restore.py` (R7) | restore-from-backup drill (восстановление из архива, проверка) | `data/restore_drill_status.json` |
| `scripts/drill_fleet_down.py` (R4) → `spa_core/monitoring/` | fleet-down drill (симуляция падения агентов + self-heal) | `data/fleet_drill_status.json` |
| `spa_core/monitoring/resilience_status.py` (R8) | read-derive-write rollup трёх выше → единый posture (OK/WARNING) с freshness-окнами | `data/resilience_status.json` |

resilience_status: stdlib-only, детерминированный, fail-CLOSED; OK только если каждый proof
свежий И прошёл (offsite verified, drills all_ok); missing status → WARNING ("never run").
Post-reboot heal остаётся `scripts/verify_fleet_after_reboot.sh` (см. секцию «После ребута»).

---

## 🛰️ RTMR — Real-Time Monitoring & Reaction (NEW, 2026-07-05 — ADR-053)

`spa_core/monitoring/` (sense-loop + sensors + reaction + posture) — **живой сторож риска**: непрерывный
сервис (`com.spa.rtmr_sense`, KeepAlive, ~45с tick) следит за рынком в реальном времени и мгновенно
снижает риск между дневными циклами. Детерминированный, **LLM запрещён**, **fail-CLOSED**, **de-risk-only**,
**paper** (капитал не двигает; go-live трек не трогает). Полная петля: **sense → signal → reaction →
posture → дневной цикл слушается позы**. Карта интеграции (переиспользует существующие
peg_monitor/red_flag_monitor/threat_reactor/kill_switch, НЕ дублирует) — `docs/RTMR_INTEGRATION_MAP.md`.

- **4 сенсора** (`sensors/`), каждый на **multi-source кворуме 5–10 keyless-источников** (`_multisource.py`,
  fail-closed на расхождении/недоборе кворума): `peg` (депег стейблов — CoinGecko/DeFiLlama/Coinbase/Kraken/Binance),
  `tvl` (обвал TVL — DeFiLlama), `oracle` (здоровье оракула — Chainlink on-chain через keyless RPC),
  `liquidity` (ликвидность выхода). Регистрируются через `build.register_default_sensors()`.
- **Reaction-лестница** (`reaction.py`, de-risk-only, property-tested): stale→FREEZE, peg/tvl/liquidity
  critical→FULL_EXIT / warn→REDUCE, oracle critical→FREEZE. **systemic MARKET_EXIT только на СВЕЖИХ
  critical** (наш рейт-лимит/data-outage НЕ каскадит в ложный портфельный DEFENSIVE).
- **Posture-стор** (`posture.py`, `data/monitoring/risk_posture.json`): единый файл, который пишет
  emergency-path и **читает `cycle_runner` Step 2e** (`cycle_gates.apply_rtmr_posture_gate`, owner-approved
  S10.5b) — clamp target'ов, **no-op при NORMAL**. `asset_map.py` роутит asset-позу (депег USDC) на протоколы.
- **Устойчивость:** re-entry/самоочистка позы (N чистых тиков), staleness-гистерезис (freeze только
  после N подряд stale-тиков), per-sensor time budget (25с — медленный сенсор не виснет тик),
  ярусный кэш (цены 30с / TVL/oracle 300с), параллельные фетчи.
- **API** (`spa_core/api/routers/rtmr.py`): `/api/rtmr/status` (сводка), `/api/rtmr/signals` (лента),
  `/api/rtmr/posture`, `/api/rtmr/reactions`. **Сайт:** `/monitoring` (island `RtmrMonitor`, bilingual,
  fail-closed) + панель на `/dashboard` + callout на `/system`.

## 🌐 Сайт (rebuilt 2026-06-25, unified design system)

Лендинг (`landing/`, Astro → CF Pages, **earn-defi.com**) пересобран на едином дизайн-системе —
`docs/SITE_DESIGN_SYSTEM.md`. Канонические `SiteHeader`/`SiteFooter` в `Layout.astro` на каждой
странице (NOT touch — пушится параллельно). Console-homepage, новые страницы `/track-record`,
`/research`, `/system`, `/disclaimer`; приложение (дашборд) на **`/dashboard`** (canonical —
`landing/src/pages/dashboard.astro`, НЕ `/app`); публичная Proof-of-Reserves поверхность.
Двуязычно (EN|RU) по всему сайту.

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
| Kill switch | **two-tier ladder** (ADR-034/048): **SOFT −5%** de-risk / **HARD −10%** all-cash |

`approved=False` не может быть переопределён никем.

### 🛑 Two-tier kill-switch (ADR-034 + ADR-048, owner-approved 2026-06-27)

Drawdown-ответ — **одна лестница** над общим evidenced peak-to-current drawdown
(`spa_core/governance/kill_switch.py::evidenced_drawdown_pct` → `drawdown_tier`).
**ADR-048: HARD kill снижен 15→10, граница inclusive (`>=`), DL-02 примирён с kill'ом.**

| Tier | Порог | Эффект |
|---|---|---|
| **SOFT_DERISK** | drawdown ∈ **[5%, 10%)** | DE-RISK: halt new / no INCREASE (hold + reduce OK), edge-triggered WARNING. **НЕ ликвидирует.** Гейт — `spa_core/paper_trading/cycle_gates.py::apply_soft_derisk_gate` (caps `target_usd` → `min(target, held)`; new protocol → 0). |
| **HARD_KILL** | drawdown ≥ **10%** (inclusive) | Full kill → all-cash `{"cash": 1.0, …: 0.0}` (`check_drawdown_trigger`, теперь `>=`). **OWNS** the 10% peak-drawdown rung. |

Полная лестница эффектов вниз по drawdown'у: **SOFT 5% → HARD all-cash ≥10%**
(DL-01 2% single-day может HALT'нуть в любой точке; DL-02 10%-peak теперь **DEFERS**
к hard-kill'у в `run_cycle` — при ≥10% цикл идёт all-cash, не HOLD; DL-01 никогда не
deferred). RiskPolicy version **остаётся v1.0** — two-tier живёт в governance-слое,
`RiskConfig` не тронут.

**Pre-cutover readiness gate** — единственный авторитетный «все money-path защиты доказуемо
срабатывают»-артефакт перед любым cutover-размышлением: `spa_core/paper_trading/pre_cutover_gate.py`
/ CLI `scripts/pre_cutover_gate.py` / док `docs/PRE_CUTOVER_GATE.md`. **INERT** (`would_cutover`
всегда False, не двигает капитал, не импортирует `execution/`, refuses live `data/`); прогоняет
цикл через каждый failure-mode в sandbox и ASSERT'ит защитный ответ (HARD/SOFT/DL-01/DL-02/
RiskPolicy/analytics/NAV-reconcile/position-monitor/fail-safe HOLD). Advisory CI-step, не гейтит push.

**Day-1 OWNER-DECISIONS — ОБА RESOLVED в ADR-048 (owner-approved 2026-06-27):**
(1) DL-02 @10% больше не shadow'ит HARD-kill — kill снижен до 10% и DL-02 DEFERS к нему
(`run_cycle` Step 2a: DL-02-only HALT + armed kill → no early-return → all-cash override);
DL-01 daily-loss intact. (2) boundary-gap закрыт — `check_drawdown_trigger` теперь `>=`
(согласован с `drawdown_tier`), ровно 10.0% срабатывает.

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
| `spa_core/paper_trading/` | cycle_runner.py, golive_checker.py, gap_monitor.py, **cycle_gates.py** (`apply_soft_derisk_gate`), **pre_cutover_gate.py** (inert readiness gate) |
| `spa_core/strategies/` | Tournament стратегии S0–S77+ |
| `spa_core/strategy_lab/` | Pluggable sleeve harness + paper-сервис (LST/RWA sleeves) |
| `spa_core/strategy_lab/forward_analytics.py` | Risk-adjusted scorecard НА живых forward-сериях (T4 attribution vs RWA floor + T5 stress overlay) → `data/forward_analytics.json` → feeds `docs/FUNDABILITY.md`; insufficient-history → UNKNOWN |
| `spa_core/strategy_lab/rates_desk/` | **Thesis #1** — refusal-first Rates Desk (GO, live-paper) |
| `spa_core/strategy_lab/rwa_backstop/` | **Thesis #2** — RWA Collateral Safety Board (measurement-GO) |
| `spa_core/strategy_lab/liquidator/` | **Thesis #3** — balance-sheet liquidator de-risk (NO-GO probe) |
| `spa_core/risk/` | policy.py (детерминированный, LLM FORBIDDEN) |
| `spa_core/tournament/` | TournamentEngine, TournamentTelegram |
| `spa_core/api/` | FastAPI server (api.earn-defi.com:8765) |
| `spa_core/monitoring/` | system_health_monitor.py, agent_health.py, **resilience_status.py** (R8 rollup → `data/resilience_status.json`), drill_fleet_down.py |
| `spa_core/dr/` | **offsite_copy.py** (R6 offsite-copy + sha256 verify), drill_restore.py (R7 restore-from-backup drill) |
| `spa_core/execution/` | **НЕ импортировать** из read-only кода |
| `spa_core/family_fund/` | http_server.py (port 8765), pnl_attribution.py |
| `data/` | Все JSON-state файлы |
| `docs/` | SYSTEM_BRIEFING.md, ADR, tournament.html, index.html |
| `scripts/` | LaunchAgent plists, install_all_agents.sh, push_v*.sh, **verify_fleet_after_reboot.sh** (post-reboot fleet heal), **drill_fleet_down.py / drill_restore.py** (resilience-drill runners) |
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

## 🗂️ data/ git-политика (P3-3, 2026-06-26)

`.gitignore` теперь различает **runtime-only** vs **canonical-in-git** артефакты в `data/`,
чтобы каждый коммит не запекал транзиентное состояние в историю.

**Runtime-only (игнорируются — транзиентная per-run churn, код сам создаёт при отсутствии):**
- `data/*.json`, `data/**/*.json` — все live-снимки состояния и per-run отчёты
  (`daily_report_*.json`, `milestones/`, `daily_summaries/`, `monthly_reports/`, `reports/`)
- `*.db` / `*.sqlite`, `data/*.db-journal` (SQLite rollback journals)
- `data/backups/` — daily DB backup snapshots
- `data/*.jsonl` — append-only runtime audit / hash-chain логи (`audit_trail.jsonl`)

**⚠️ OWNER-GATED (оставлены tracked НАМЕРЕННО — НЕ untrack без решения владельца):**
`equity_curve_daily.json`, `golive_status.json`, `paper_evidence_history.json` —
сейчас закоммиченные track-снимки. Они **матчатся** правилом `data/*.json`, но остаются
в git, т.к. были закоммичены ДО этого правила. **OWNER-решение:** должны ли волатильные
track-снимки вообще жить в git (canonical-in-git vs runtime-only)? До решения — НЕ
`git rm --cached`.

> 🔓 **Зависимость снята (2026-06-28):** единственным потребителем этих committed-копий
> был legacy github.io дашборд (root `index.html` читал `STATIC_DATA_BASE`/`RAW_DATA_BASE`
> как static/offline fallback). Он **удалён** → ничего больше не читает закоммиченные
> копии (Astro-дашборд `dashboard.astro` берёт всё вживую из `api.earn-defi.com`, без
> committed-fallback). Untrack теперь **БЕЗОПАСЕН** — fallback больше нечего ломать.
> Решение всё ещё owner-gated; здесь только фиксируем, что технический блокер ушёл.

**Уже-tracked файлы, которые попали под новые ignore-правила** (нужен `git rm --cached`
на remote — `push_to_github.py` это не умеет, делает владелец вручную):
`data/backups/spa_2026-06-1[1-8].db` (8 шт.), `data/*.db-journal`
(`_probe`, `spa`, `spa_test`, `track`), `data/audit_trail.jsonl`.

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
4. **Атомарные записи** — `atomic_save` (same-dir tmp + `os.replace(tmp, dst)`), никогда прямой `open(..., "w")` на state-файлы.
5. **LLM запрещён** в risk / execution / monitoring компонентах.
6. **Не встраивать PAT** в файлы, не создавать `push_*.html`.
7. **RiskPolicy version = "v1.0"** весь paper-период; изменение → новый ADR.
8. **Sky/sUSDS = 0%** до подтверждённого GSM Pause Delay ≥ 48h on-chain.
9. **Атомарный KANBAN** — перечитывать с диска перед записью (конкурентный процесс).
10. **IS_ADVISORY=True** для всех новых стратегий T2/T3 до go-live.
11. **Деплой агента ТОЛЬКО через gate** — перед `launchctl load`/`bootstrap` любого нового/изменённого
    plist ВСЕГДА запускать `scripts/check_agent_before_deploy.sh <name>` (запуск вручную → exit 0 → лог
    создан → только потом load). Деплоить **≤3 агентов за раз** (батчами). Все агенты запускаются через
    **bash-wrapper** (`scripts/agent_template.sh` / `scripts/agent_<name>.sh`), **НИКОГДА** прямой
    `python3 -m` (или прямой miniconda-python) в `ProgramArguments` — launchd не может exec'нуть
    miniconda-python напрямую → **exit 78 EX_CONFIG** (программа даже не стартует, лог не пишется).
    **И:** `StandardOutPath`/`StandardErrorPath` агента должны указывать в **`/tmp/`**, НЕ в
    `~/Documents/SPA_Claude/logs/` — launchd-процессу TCC блокирует запись под `~/Documents` (Full Disk
    Access не выдан) → тоже **exit 78**. Wrapper сам пишет timestamped-лог в `/tmp/spa_<name>.log`.

---

*Обновлено: 2026-06-29 (v12.87 — doc-drift re-sync to authoritative source: state-table GoLive **27/29**
(было 26/29 — transient pre-dawn dip), трек **7/30** evidenced (anchor 2026-06-22, target ~2026-07-21),
agent-count ~45 (launchctl после retirement'ов, caveat сохранён); сайт-секция `/app`→**`/dashboard`**
(canonical, нет `/app`-страницы); auto-login **ВКЛЮЧЁН** (audit: autoLoginUser+kcpassword) с честным
security trade-off; doc-drift guard расширен — теперь пинит state-числа CLAUDE/CURRENT_STATE/README/RULES
к golive_status.json + kill_switch.py SOFT 5%/HARD 10%). v12.86 — Structural-Desk sprint consolidation: agent-count **51** (launchctl,
hedge сохранён); agent-table +rwa_safety_board +daily_backup; новая секция **Structural Desk** (3 тезиса:
#1 Rates Desk GO / #2 RWA Backstop measurement-GO·book-NO-GO / #3 Liquidator NO-GO) + индекс `docs/STRUCTURAL_DESK.md`;
repo-структура +strategy_lab/{rates_desk,rwa_backstop,liquidator}; endpoint-список +`/api/rates-desk/proof`
+`/api/strategy-lab/promotion`; доки RATES_DESK / RATES_DESK_VALIDATION / RWA_BACKSTOP_DERISK / LIQUIDATOR_DERISK /
RESEARCH_PROMPT_MOAT. v12.85 — добавлена секция **Rates Desk** (validated thesis-#1: RateSurface +
FairValueEngine refusal-first гейт + 4 trade-shape + FixedCarry GO; новый агент `com.spa.rates_desk_paper`
hourly advisory live-paper + `/api/rates-desk/*`; док `docs/RATES_DESK.md`); agent-table: +strategy_lab_paper
/refusal/rates_desk_paper). v12.84 — docs audit: state-table sync 16/30·$100,180·27/29, ~42 агента; реестр
**35 адаптеров** (+BTC tbtc/cbbtc advisory); секции **Strategy Lab** (eth_lst_neutral + rwa_sleeve + 5-venue
funding + real RWA floor ~3.4%) и **Сайт** (unified design system, /track-record /research /system /disclaimer
/app, EN|RU); source of truth = launchctl/SYSTEM_BRIEFING; agent_health честно зелёный.*

---

## 🧪 Yield Lab / AI Investment OS (research layer — docs-first, non-runtime)

A research/documentation layer is being scaffolded on branch `yield-lab-scaffolding` to evolve SPA
into an AI-native yield research + risk + decision-support system (Yield Lab, AI Investment OS,
Builder OS, Execution Support). **It never touches the runtime execution path, RiskPolicy, public
dashboard, or deployment.** Charter: `prompts/claude_code/yield_lab_master.md`. Authoritative index:
`docs/00_index.md`. Read `docs/06_spa_core_invariants.md` before any related work.

**Hard invariants this layer preserves (superset of the FORBIDDEN list above):**
- Deterministic **RiskPolicy v1.0** is the sole hard execution gate; **Risk Scoring v2 is advisory
  only**, never a gate, never in the execution path.
- **No LLM** in risk/execution/monitoring/kill. **No private keys / seed phrases / signing / fund
  movement** anywhere; **Execution Support is non-custodial**, human-in-the-loop.
- **APY claims require an evidence level (L0–L6, `docs/37`)** — never present paper/backtest as live;
  always show yield source + risk category + last-verified date. Never invent APY/TVL.
- Higher-yield strategies pass the **Yield Lab lifecycle** (`docs/07`) — yield-source + protocol +
  stablecoin + liquidity + risk + **Red Team** review + paper test + **human approval** — before any
  public/live use. **BTC/ETH cycle modules are decision-support, not auto-trading.**
- Default autonomy **Level 0/1** (research/recommendation). **External capital needs legal review.**

**Workflow (Builder OS, `docs/45`):** read `docs/00_index.md` → `docs/06` → the relevant architecture
doc → `docs/29_backlog.md`; pick ONE task; modify only required files; tests for code changes; docs
updated with behavior changes; **stop and ask before touching runtime/RiskPolicy/dashboard/deploy**;
one task per iteration, no big-bang rewrites, no hidden changes. **A research layer already partially
exists** (`spa_core/strategy_lab/{aggressive_lab,rates_desk,rwa_backstop,liquidator,underwriting}`,
`redteam/`, `riskwire/`, `dfb/`, `compliance/`) — the docs formalize/unify these, do NOT duplicate them
(`docs/02_current_architecture_audit.md`).
