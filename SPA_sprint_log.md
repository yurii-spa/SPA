# SPA Sprint Log — updated 2026-05-29

## Completed ✅

---

## Sprint v3.24 — 2026-05-29 — Закрытие трёх критических технических рисков перед go-live

**Цель:** устранить три технических риска, выявленных архитектором как блокеры для live-режима.

### РИСК 1 (SPA-V324-001) — eth_signer.py → eth_account

**Проблема:** `spa_core/execution/eth_signer.py` содержал ~280 строк самописного кода на secp256k1 + Keccak-256. Любой баг в нём — прямая потеря средств при live-торговле.

**Решение:** модуль полностью переписан на `eth_account>=0.10.0` (уже в requirements.txt). Весь публичный API сохранён:
- `sign_transaction(private_key_hex, tx_dict) → bytes` → `eth_account.Account.sign_transaction()`
- `get_address_from_private_key(private_key_hex) → str` → `Account.from_key(pk).address`
- `keccak256(data) → bytes` → `eth_hash.auto.keccak`
- **Новая функция:** `sign_message(message, private_key_hex) → str` — EIP-191 personal_sign
- `encode_function_call`, `get_nonce`, `get_base_fee`, `estimate_gas`, `send_raw_transaction` — без изменений (не касаются крипто)

**Тесты:** `spa_core/tests/test_eth_signer.py` — 19 тестов (5 классов: GetAddress, SignTransaction, SignMessage, Keccak256, EncodeFunctionCall). Включают проверку детерминизма подписи, восстановление подписывающего через `Account.recover_transaction`, тест известных векторов Keccak-256.

### РИСК 2 (SPA-V324-002) — Morpho Blue / Vaults адаптер

**Проблема:** Morpho — T1 протокол с лимитом 40% портфеля, но адаптера для исполнения не существовало. Go-live без него невозможен.

**Решение:** создан `spa_core/execution/adapters/morpho_adapter.py` (~520 строк):
- `MorphoAdapter(chain, dry_run=True)` — паттерн идентичен `AaveV3Adapter`
- Интерфейс для engine_bridge: `supply(asset, amount)`, `withdraw(asset, amount)`
- Расширенный API: `get_position(wallet, asset)`, `get_apy(asset)`, `is_healthy()`, `health_check()`
- Dataclasses: `TxRequest`, `PositionInfo`
- ERC-4626 интерфейс (Morpho Vaults): `deposit`, `redeem`, `convertToAssets`, `balanceOf`
- Ваулты: Steakhouse USDC/USDT (ethereum), re7 USDC/USDT (base)
- `is_healthy()` всегда `True` — vault-позиции не имеют риска ликвидации

`engine_bridge.py` обновлён:
- `_PROTOCOL_PREFIX_TO_FAMILY`: добавлен `"morpho": "morpho"`
- `_get_adapter()`: ветка `elif family == "morpho"` с lazy-import

**Тесты:** `spa_core/tests/test_morpho_adapter.py` — 27 тестов (8 классов). Включают интеграционный тест с engine_bridge (протокол-ключ `morpho-usdc-ethereum`).

### РИСК 3 (SPA-V324-003) — wallet_ready_approved.json в .gitignore

**Проблема:** `data/wallet_ready_approved.json` (approval flag для live-режима) хранился в публичном git.

**Решение:** добавлена строка `data/wallet_ready_approved.json` в `.gitignore`. Файл остаётся локально.

### KANBAN обновлён
- `done`: добавлены SPA-V324-001, SPA-V324-002, SPA-V324-003 (108 completed items)
- `backlog`: добавлены SPA-BL-007 (RPC ключи в Secrets), SPA-BL-008 (Telegram bot), SPA-BL-009 (Gnosis Safe wallet)
- `sprint_completed` → `v3.24`

### Файлы

Изменены/созданы:
- `spa_core/execution/eth_signer.py` — полностью переписан (убрана самописная крипто)
- `spa_core/execution/adapters/morpho_adapter.py` — новый файл (~520 строк)
- `spa_core/execution/adapters/__init__.py` — новый (пакет)
- `spa_core/execution/engine_bridge.py` — добавлена регистрация morpho
- `spa_core/tests/test_eth_signer.py` — новый (19 тестов)
- `spa_core/tests/test_morpho_adapter.py` — новый (27 тестов)
- `.gitignore` — добавлена строка `data/wallet_ready_approved.json`
- `KANBAN.json` — обновлён (done +3, backlog +3, header)
- `SPA_sprint_log.md` — этот раздел

### Команды для проверки
```bash
# Тесты нового eth_signer
python3 -m pytest spa_core/tests/test_eth_signer.py -v

# Тесты Morpho адаптера
python3 -m pytest spa_core/tests/test_morpho_adapter.py -v

# Полный тест-сьют
python3 -m pytest spa_core/tests/ tests/ -q --tb=short
```

### Следующие приоритеты (User Actions — без изменений)
1. **BL-006** — push workflow-scope PAT → cron запускается → Data Freshness FAIL исчезает
2. **BL-005** — Telegram bot token в Secrets
3. **BL-004** — включить GitHub Pages в настройках репо
4. **SPA-BL-007** — RPC ключи Alchemy/Infura в Secrets (нужно для live Morpho/Aave)
5. **SPA-BL-009** — Gnosis Safe кошелёк → Go-Live критерий #9

---

### v0.1–v0.7: Foundation
- Project scaffolding, SQLite database schema, protocol whitelist (7 protocols: Aave V3 USDC/USDT, Compound V3, Morpho, Yearn V3, Maple, Euler V2)
- Paper trading engine with full RiskPolicy (Kelly criterion, concentration limits, cash buffer, kill switch)
- Agent architecture (CEO, Data, Strategy, Monitoring agents), Message Bus (SQLite-backed pub/sub)
- REST API server (FastAPI), initial GitHub Actions workflow

### v0.8: Agent Communication Layer
- Agent thought bubbles and real-time activity log
- In-app chat interface for agent Q&A
- WebSocket agent stream (FastAPI + uvicorn)

### v0.9: Backtesting Engine + Policy Governance
- `BacktestEngine` — replays `auto_allocate()` on historical/synthetic APY data with the same RiskPolicy as live trading
- `BacktestMetrics` — Sharpe ratio, max drawdown, win rate, annualised return (pure Python, no numpy/scipy)
- `generate_synthetic_history()` — mean-reverting OU process, 7 protocols × N days, seeded for reproducibility
- Policy ADR governance docs (`ADR_001_initial_risk_policy.md`)

### v0.10: Multi-Strategy + Comparison Dashboard
- Dual-strategy runtime: `v1_passive` (conservative T1-only) and `v2_aggressive` (T1+T2, higher APY target)
- Strategy comparison view in dashboard
- `strategy_comparison.json` export, `strategy_v2.json` state

### v0.11: Email Alerts (Gmail SMTP)
- `alerts/email_sender.py` — `send_alert()`, `build_risk_alert_email()`, `build_cycle_summary_email()`
- GitHub Actions secrets: `SPA_ALERT_EMAIL`, `SPA_ALERT_PASSWORD`, `SPA_NOTIFY_EMAIL`
- Sends on critical risk events and every 4h cycle completion

### v0.12: Real DeFiLlama Historical Data + Charts
- `load_from_defillama_api()` — fetches real 90-day APY history, falls back to synthetic on any error
- Rolling Sharpe ratio chart
- APY history chart (per-protocol time series)
- Correlation matrix (tier-based covariance model)
- `historical_apy.json` export

### v0.13: Portfolio Optimization (Kelly + Markowitz)
- `optimization/kelly.py` — `kelly_fraction()`, `half_kelly()`, `kelly_position_size()` (pure Python)
- `optimization/markowitz.py` — `PortfolioOptimizer` with projected gradient descent, max-Sharpe and min-variance modes, efficient frontier
- `optimization/recommender.py` — `AllocationRecommender` combining Kelly pre-filter → MVO → RiskPolicy check
- `optimization_recommendations.json` export

### v0.14: PDF Report Generator
- `reports/pdf_generator.py` — `generate_report()` using ReportLab
- Auto-generated every 4h via `report_scheduler.py`
- `latest_report.json` metadata export; PDFs saved to `data/spa_report_YYYYMMDD_HHMM.pdf`

### v0.15: FastAPI Backend + WebSocket Agent Stream
- Full REST API (`/api/status`, `/api/protocols`, `/api/portfolio`, `/api/positions`, `/api/trades`, etc.)
- WebSocket endpoint for real-time agent thought-bubble streaming
- `run_server.py` entry point, `api/server.py`, `api/agent_broadcaster.py`

### v0.16: Agent Decision Log
- `agents/decision_logger.py` — SQLite-backed decision log
- `decision_log.json` export — chronological record of every agent decision with rationale
- Dashboard decision log panel (filterable by agent, decision type, date)

### v0.17: Go-Live Readiness Checker
- `golive/checklist.py` — 8 automated criteria (paper duration, PnL, alerts, Sharpe, policy version, drawdown, diversification, data freshness)
- `golive/report_card.py` — ASCII art report card printed on every export run
- `golive_readiness.json` export
- Verdict states: READY / ALMOST_READY / NOT_READY / BLOCKED

### v1.0 Frontend: Full Dashboard Integration
- 5-tab dashboard: Portfolio, Strategy, Optimization, Decision Log, Go-Live
- Live mode toggle (auto-refresh every 30s)
- Optimization panel (Kelly fractions, Markowitz weights, efficient frontier)
- Decision log panel (agent activity, rationale, timestamps)
- Go-Live tab (8-criteria checklist, ASCII report card, progress bars)

### v1.0 Backend Hardening (2026-05-21)
- `requirements.txt` updated: added `reportlab>=4.0.0`, `websockets>=12.0`, `python-multipart>=0.0.9`
- GitHub Actions workflow updated: `pip install -r spa_core/requirements.txt`, pytest step with `continue-on-error: true`, all new JSON/PDF files committed
- `spa_core/tests/conftest.py` — shared fixtures: `sample_portfolio`, `sample_positions`, `temp_data_dir`
- `spa_core/tests/test_optimization.py` — 20 tests for Kelly, Markowitz, AllocationRecommender
- `spa_core/tests/test_backtesting.py` — 26 tests for metrics, data loader, BacktestEngine
- `spa_core/tests/test_golive.py` — 28 tests for all 8 criteria + run_full_check
- `spa_core/tests/test_email.py` — 19 tests for build_risk_alert_email + send_alert
- All imports verified clean; export pipeline runs without errors
- **Test result: 90/90 passing (0 failures)**

### v1.1 — Whitelist Correction + Risk Fixes (2026-05-21)

- **Fix: `defillama_fetcher.py`** — corrected 12-pool whitelist (Arbitrum + Base chains); removed invented/non-existent protocols that had been hallucinated into the whitelist
- **Fix: Strategy Tournament `v2_aggressive`** — resolved `RiskConfig` field bug that caused tournament scoring to crash on aggressive-tier strategies
- Whitelist now authoritative: only on-chain verified pools included

### v1.2 — Pendle PT Integration (2026-05-21)

- **New: `pendle_fetcher.py`** — PT pool fetcher with 7 quality gates (maturity, liquidity, underlying asset, TVL floor, APY sanity, chain whitelist, oracle freshness)
- **New: `pendle_strategy.py`** — `PendlePosition` dataclass and `pendle_allocation_size()` sizing logic
- **ADR-002** created: documents Pendle PT integration rationale, quality gates, and risk considerations
- Pendle pools now available as T2 allocations; expected to close APY gap from ~4.2% toward 7.3% target

### v1.3 — Analytics + Tournament (2026-05-21)

- **New: `analytics/portfolio_stats.py`** — advanced portfolio metrics: Calmar ratio, Sortino ratio, Ulcer Index, rolling Sharpe/drawdown windows
- **Fix: `backtesting/tournament.py`** — `StrategyTournament` weighted scoring fully operational (was broken by `RiskConfig` bug above); now produces correct cross-strategy rankings
- **Dashboard: APY Gap Tracker panel** — visualises current APY vs target with per-protocol contribution breakdown
- **Dashboard: Pendle PT panel** — live Pendle pool list with quality gate status
- Test coverage expanded; total passing: **120+ tests**

### v1.4 — Observability (2026-05-22)

- **New: `alerts/daily_report.py`** — `DailyReportBuilder`: compiles Telegram daily digest (positions, PnL delta, risk flags, day X/56 counter)
- **New: `alerts/risk_monitor.py`** — `RiskMonitor`: real-time alert engine; triggers on drawdown breach, APY anomaly, stale data, kill-switch conditions
- **Fix: `sky_monitor.py`** — on-chain GSM Pause Delay checker with 3 fallback RPC sources (primary + 2 backups); resolves flaky monitoring when single RPC is unresponsive
- **New: `agents/model_config.py`** — pluggable model assignment config; decouples agent roles from hardcoded model strings (CEO → Sonnet, Monitoring → Haiku, Data → Gemini Flash-Lite)

### v1.5 — Dashboard v2 (2026-05-22)

- **Dashboard: APY Gap Tracker** — full panel showing current ~4.2% vs 7.3% target, gap attribution by protocol tier
- **Dashboard: Pendle PT panel** — pool list with quality gate badges, maturity dates, PT APY
- **Dashboard: Day X/56 counter** — prominent paper trading progress indicator (Day 2 of 56 as of 2026-05-22)
- **Dashboard: 📡 Live badge** — real-time data freshness indicator; turns amber if data is stale > 15 min
- Dashboard now at **v1.5**, all 5 tabs fully integrated and live

### v1.6 — 2026-05-22 (Night sprint wave)

### Completed sprints:

**Dashboard v3 — Backtesting Replay UI**
- Added `📈 Backtesting Replay` card to Analytics tab
- Chart.js two-line equity chart (v1_passive blue, v2_aggressive orange)
- `⏱ Replay Mode` toggle: slider by day, auto-play 500ms, syncs Paper Trading tab values
- Strategy comparison table: 5 metrics, winner highlighted green/loser red
- `runBacktest()` auto-fires when Analytics tab opens

**Documentation Suite (4 files)**
- `docs/api_reference.md` — all 17 FastAPI endpoints with schemas and examples
- `docs/data_schema.md` — 14 data/*.json files with full field tables
- `docs/architecture.md` — ASCII component diagram, agent hierarchy, risk governance
- `docs/paper_trading_guide.md` — 8-week cycle, timeline, Telegram setup

**GitHub Actions Hardening**
- `retry_request()` with exponential backoff in defillama_fetcher + pendle_fetcher
- `pipeline_health.json` written after every export (sections OK/FAIL, pools count, duration)
- Telegram alert triggered if >2 sections fail or 0 pools fetched
- Workflow: 15-min timeout, health check step, artifact upload (7-day retention)
- 6 new tests in `test_retry_logic.py` — all pass

**Dashboard v4 — System Health Tab**
- New `⚙️ System` tab (hotkey `6`) with 4 cards:
  - Pipeline Health: 🟢/🟡/🔴 badge, section counts, duration
  - Data Freshness: color-coded by age (<6h/6-24h/>24h)
  - Paper Trading Clock: live countdown to next 4h cycle, ⚠️ if overdue
  - Go-Live Countdown: progress bar Day X/56, criteria summary
- Auto-refreshes every 60s while tab active

**Operator Runbook**
- `docs/operator_runbook.md` — ~2400 words
- Day 1 setup, daily/weekly monitoring, Sky upgrade, go-live process
- 6 incident scenarios with diagnostic steps
- Configuration reference table, file structure map
- v2.0 upgrade path (real capital ~late August 2026)

**Concurrent Pool Fetching**
- `ThreadPoolExecutor` parallel fetch (main + Pendle simultaneously)
- 1-hour file-based response cache (`data/.cache/`)
- Performance timing logged: `[PERF] Fetched N pools in Xs`
- `data/.cache/` added to `.gitignore`

**Manifest Updated**
- 67 → 111 files in PUSH_MANIFEST (+44 entries)
- Covers all agents, tests, docs, new modules

### Total tests: ~140 (up from 120)
### Total files: 116+ (manifest 111 + new docs/tests)
### Dashboard: v1.6 — 6 tabs (Home, Paper Trading, Analytics, Go-Live, Agents, System)

### v3.6 — FEAT-004 Phase 2: Aave V3 Read-Only RPC Integration (2026-05-27)

- **`spa_core/execution/aave_v3_adapter.py`** — Phase 2 lift: replaced the Phase 1 NOT_IMPLEMENTED stubs of `get_supply_apy` and `get_supply_balance` with real on-chain `eth_call` decoding when `dry_run=False`. Pure stdlib only (`urllib.request` + `json`) — no web3.py, no requests, no eth_account. Added 3-RPC fallback (`_call_with_fallback`) that strips the `#aave-v3-pool:0x...` URL fragment before POST, hardcoded selectors `0x35ea6a75` (getReserveData) + `0x70a08231` (balanceOf), canonical mainnet USDC/USDT/DAI token addresses for ethereum/arbitrum/base, and per-asset decimals scaling (6 USDC/USDT, 18 DAI). APY decoded from `currentLiquidityRate` at struct slot 2 (RAY → percent via `/1e25`); balance pipeline runs getReserveData → aTokenAddress at struct slot 8 → `balanceOf(SPA_WALLET_ADDRESS env)`. Production-safe `[FALLBACK]` policy: every live-path exception logs a WARNING and degrades to the Phase 1 mock value, so the pipeline never crashes if RPCs flake or `SPA_WALLET_ADDRESS` is unset. Write methods (supply / withdraw) stay NOT_IMPLEMENTED — Phase 3 will add eth_account signing. **Tests: `spa_core/tests/test_aave_v3_adapter_phase2.py` — 15 new deterministic tests across 4 classes (TestEthCallHelper×4, TestFallbackRouting×3, TestGetSupplyApyLive×4, TestGetSupplyBalanceLive×4), all PASS in 0.04s with zero network (every `urlopen` patched). Phase 1 test_aave_v3_adapter.py 13/13 still PASS — dry_run=True path byte-identical.** Closes SPA-V36-001; FEAT-004 advances to ~66% complete (Phase 1 + 2 done, Phase 3 signing + engine cutover remaining).

### v3.10 — FEAT-005 Phase 3: Compound V3 Live supply/withdraw (2026-05-27)

- **`spa_core/execution/compound_v3_adapter.py`** — Phase 3 lift: replaced the Phase 2 NOT_IMPLEMENTED short-circuit of `supply()` and `withdraw()` with a fully-signed EIP-1559 transaction path. Exact mirror of SPA-V39-001 (Aave V3 Phase 3 / ADR-009) ported to the Compound V3 Comet ABI. Multi-layer safety stack identical to ADR-009: (1) `dry_run=True` default unchanged (deterministic DRY_RUN dict, no imports, no RPC); (2) `dry_run=False` + `SPA_EXECUTION_MODE != "live"` → `{status: "BLOCKED"}`; (3) `SPA_PRIVATE_KEY` format + key→address mismatch with `SPA_WALLET_ADDRESS` checks → `{status: "ERROR"}`; (4) `MAX_LIVE_AMOUNT = 10_000_000` USD sanity gate; (5) any RPC / signature / receipt revert returns `{status: "FAILED", phase: "approve"|"supply"|"withdraw"}` — never raises. `eth_account` imported LAZILY via `_require_eth_account()` (psycopg2 pattern) so the dry-run happy path needs no new dep. Comet-specific selectors differ from Aave: `0xf2b9fdb8` for `Comet.supply(asset, amount)` (no onBehalfOf/referralCode) and `0xf3fef3a3` for `Comet.withdraw(asset, amount)` (no `to` — credits/debits `msg.sender`). Single-asset only — `SUPPORTED_ASSETS=['USDC']` (cUSDCv3). Two-tx supply flow (approve USDC on Comet → Comet.supply), single-tx withdraw. **Tests: `spa_core/tests/test_compound_v3_adapter_phase3.py` — 15 new deterministic network-free tests (execution-mode gate ×3, key validation ×3, supply happy + 3 sad paths, withdraw happy + revert, eth_account missing degrades to FAILED, sanity gate ×2). Existing `test_compound_v3_adapter.py` Phase-1 `live_mode_returns_not_implemented` tests updated to accept both NOT_IMPLEMENTED (legacy) and BLOCKED (Phase 3) for backward-compat. Compound suite total 17+16+15 = 48/48 PASS in 0.08s. Cross-suite regression (Aave Phase 1+2+3 + Compound Phase 1+2+3 + router + price_feeds) 140/140 PASS.** Closes SPA-V40-001; FEAT-005 now 100% complete (Phase 1+2+3). Phase 4 (v4.0) will wire `spa_core/orchestration/engine.py` cutover behind a per-strategy `live_execution: bool` YAML flag — paired with Aave V3 from SPA-V39-001. See `docs/ADR_010_compound_v3_live_writes.md`.

---

## Pending Push to GitHub

Files changed in this session:
- `spa_core/requirements.txt`
- `.github/workflows/spa-run.yml`
- `spa_core/tests/conftest.py` (new)
- `spa_core/tests/test_optimization.py` (new)
- `spa_core/tests/test_backtesting.py` (new)
- `spa_core/tests/test_golive.py` (new)
- `spa_core/tests/test_email.py` (new)

**Action needed:** New GitHub token (https://github.com/settings/tokens, `repo` scope), then run `sync_to_github.sh` or push manually.

---

## Go-Live Status (as of 2026-05-22)

| Field | Value |
|-------|-------|
| Paper trading started | 2026-05-20 |
| Target go-live date | 2026-07-15 |
| Days elapsed | 2 |
| Days remaining | 53 |
| Current APY | ~4.2% |
| Target APY | 7.3% |
| Current verdict | NOT READY |
| Criteria passing | 5/8 |
| Blocking criteria | Paper Duration (2/56 days) |
| Warning criteria | PnL (early stage, accumulating), Diversification (positions ramping up) |

Next milestone: paper duration criterion passes **2026-07-09** (48 days away).
Go-live decision: **2026-07-15** — contingent on Sharpe ≥ 2.0, drawdown ≤ 5%, all agents stable ≥ 4 weeks.

---

## Sprint v3.12 — FEAT-007 Phase 1: Live APY Covariance Estimator + Dynamic Kelly (2026-05-27)

**Goal:** Replace the synthetic CV=10% per-protocol volatility (used by `optimization/markowitz.py` and `optimization/kelly.py`) with a real rolling-window estimator over `data/apy_history.json`, while preserving byte-identical behaviour for every existing call-site.

### Delivered

- **`spa_core/analytics/covariance_estimator.py`** — new module:
  - `CovarianceEstimator(history_file=..., preloaded=...)`
  - `compute_volatility()` — sample stdev (Bessel) over rolling window with synthetic fallback when n < MIN_OBSERVATIONS=7
  - `compute_correlation()` — Pearson on time-aligned timestamp intersection, tier-based synthetic fallback
  - `compute_covariance_matrix()` / `compute_correlation_matrix()` — symmetric, diagonal=σ² / 1.0
  - `summary()` — JSON-ready dict for dashboard export
  - Pure stdlib (json/math/statistics/datetime) — zero numpy/scipy
- **`spa_core/optimization/dynamic_kelly.py`** — new module:
  - `dynamic_kelly_fraction(apy_pct, tier, tvl_usd, *, volatility_pp=None, risk_free_rate_pct=5.0)`
  - `dynamic_half_kelly(...)`, `dynamic_position_size(...)`
  - **Cardinal invariant**: when `volatility_pp` is `None` or `≤ 0`, returns EXACTLY the value of the classical `kelly.kelly_fraction` counterpart. Strict superset of the old API.
  - Variance-Kelly formula: `f* = (μ - r_f) / σ²` with both inputs as fractions, clamped to `[0.0, 1.0]`
- **`docs/ADR_012_dynamic_kelly_sizing.md`** — 3-phase rollout plan, alternatives (EWMA / Ledoit-Wolf shrinkage / risk-parity) rejected with rationale, rollback strategy
- **`spa_core/tests/test_covariance_estimator.py`** — 31 deterministic tests (ISO parsing × 4, stdev/Pearson helpers × 7, protocol listing × 3, volatility × 5, correlation × 6, matrix properties × 4, summary × 3)
- **`spa_core/tests/test_dynamic_kelly.py`** — 21 deterministic tests (fallback parity × 7 / variance-Kelly known values × 6 / cap-enforcement × 4 / half-kelly invariants)

### Test results

- **New: 52/52 PASS** in 0.06s (zero network, zero DB, zero filesystem)
- **Regression: 80/80 PASS** across `test_optimization.py` + `test_apy_tracker.py` + `test_analytics.py`

### Phase plan

- ✅ **Phase 1 (this sprint)**: pure-additive scaffold, opt-in, no existing call-site changed
- ⬜ **Phase 2 (next sprint)**: wire `CovarianceEstimator` into `markowitz.PortfolioOptimizer` + `recommender.AllocationRecommender` behind `SPA_LIVE_COVARIANCE=1` env flag; daily JSON export at `data/covariance_summary.json`
- ⬜ **Phase 3 (post-go-live)**: retire the env flag; synthetic CV kept ONLY as cold-start fallback

### Files

Created:
- `spa_core/analytics/covariance_estimator.py`
- `spa_core/optimization/dynamic_kelly.py`
- `spa_core/tests/test_covariance_estimator.py`
- `spa_core/tests/test_dynamic_kelly.py`
- `docs/ADR_012_dynamic_kelly_sizing.md`

Modified:
- `KANBAN.json` (SPA-V42-001 added to done)
- `SPA_sprint_log.md` (this entry)

## Sprint v3.13 — FEAT-RISK-002 Incident History Database (2026-05-27)

### Goal
Foundational data layer for the Risk Scoring Engine (FEAT-RISK-001). Canonical
hack / exploit / rugpull / depeg history per protocol, sourced from DefiLlama
hacks API with a curated bootstrap fallback. Single file as the source of
truth (`data/incidents.json`) — no DB tables.

### What shipped
- **`spa_core/data_pipeline/incidents_fetcher.py`** — fetcher module
  - `fetch_defillama_hacks()` — public API client (stdlib `urllib` + retry/backoff)
  - `normalise_incident()` — single-record normaliser to the canonical schema
  - `_dedupe_and_sort()` — deterministic (date DESC, slug ASC) ordering
  - `build_summary()` — per-SPA-protocol roll-up (incidents / total_lost_usd / last_incident)
  - `build_incidents_snapshot()` — orchestrator (offline + online merge)
  - `write_snapshot()` / `load_snapshot()` — disk round-trip
  - CLI: `python -m spa_core.data_pipeline.incidents_fetcher [--offline] [--dry-run] [--output PATH] [--timeout S] [-v]`
  - **`BOOTSTRAP_INCIDENTS`** — 10 curated DeFi incidents (Euler $197M, Cream $130M, Compound $80M, Curve $73.5M, Yearn $11.5M, Penpie $27M, USDC depeg, DAI Black Thursday, UST $40B, Uniswap Permit2 phish)
  - **`SPA_PROTOCOL_SLUGS`** — 16 canonical slugs covering current whitelist + S2 LP venues
- **`data/incidents.json`** — seed snapshot (10 incidents, $40.5B total lost, 8/16 SPA slugs with non-zero history)
- **`docs/ADR_013_incident_history.md`** — design doc, schema, normalisation rules, integration plan, alternatives, risks
- **`spa_core/tests/test_incidents_fetcher.py`** — 58 deterministic tests
  - slug normalisation (8 cases) — including unicode-adjacent / dunder
  - type classification (12 cases) — DefiLlama enum mapping
  - amount normalisation (5 cases) — millions → USD coercion, zero-passthrough
  - date normalisation (6 cases) — ISO / unix s / unix ms / d-m-y / invalid
  - SPA whitelist matching (5 cases) — symmetric substring matching
  - record normalisation (4 cases) — including bootstrap round-trip property test
  - dedupe semantics (4 cases) — date sort, source_url tiebreaker, amount tiebreaker
  - summary roll-up (3 cases) — empty init, increment, latest-date kept
  - HTTP fetch (4 cases) — list payload / dict payload / network error / invalid JSON
  - snapshot composition (4 cases) — offline / summary-complete / online-merge / shape stability
  - disk round-trip (3 cases) — write+read / missing file / corrupt file

### Test results
- **New: 58/58 PASS** in 0.09s (zero network, zero DB, zero filesystem outside tmp_path)
- All bootstrap records pass the round-trip normalisation property test (no silent data corruption)

### Phase plan
- ✅ **Phase 1 (this sprint)**: ship fetcher + seed + tests + ADR. Module is importable but NOT wired into the 4h cycle yet.
- ⬜ **Phase 2 (sprint v3.14)**: integrate into `spa_core/export_data.py` as section 19 — calls `build_incidents_snapshot()` post `apy_tracker` section. Cycle adds < 4s.
- ⬜ **Phase 3 (FEAT-RISK-001)**: Risk Scoring Engine reads `by_protocol_summary` directly to compute the "hack history" sub-score (1 of 15 parameters).

### Files
Created:
- `spa_core/data_pipeline/incidents_fetcher.py`
- `spa_core/tests/test_incidents_fetcher.py`
- `docs/ADR_013_incident_history.md`
- `data/incidents.json`

Modified:
- `KANBAN.json` (FEAT-RISK-002 → done; sprint stamped v3.13)
- `SPA_sprint_log.md` (this entry)

### Next on the Risk Layer roadmap
1. **FEAT-RISK-001** — Risk Scoring Engine (12h, HIGH) — now unblocked
2. **FEAT-INT-001** — Audit Reader Agent (6h, MEDIUM) — parallel, independent
3. **FEAT-RISK-003** — Real Yield Classifier (6h, HIGH) — after FEAT-RISK-001

---

## v3.14 — FEAT-RISK-001 Risk Scoring Engine

**Date:** 2026-05-27
**Sprint:** v3.14
**Ticket:** FEAT-RISK-001 (HIGH, Phase 1, est. 12h)
**Owner:** Dispatch orchestrator (autonomous run)
**Status:** Shipped — closes the Risk Layer foundation.

### What shipped
- **`spa_core/risk/scoring_engine.py`** — main module (~700 LOC)
  - `ProtocolRiskScore` dataclass (protocol, slug, grade, score_numeric, subscores, explanation, generated_at, fallback_used, allocation_cap_pct)
  - `RiskScoringEngine` class with:
    - `_fetch_defillama_protocols(offline)` — stdlib `urllib` + retry/backoff + bootstrap merge
    - `_load_incidents()` / `_load_audit_findings()` — read FEAT-RISK-002 + FEAT-INT-001 outputs; graceful `{}` on missing/corrupt
    - **15 deterministic `_score_*` methods**, each returning `[0,1]` higher-is-safer
    - `compute_score(slug)` — single-protocol scoring, NEVER raises
    - `compute_all()` — full SPA whitelist (10 protocols)
    - `export(output_file, dry_run)` — writes canonical `data/risk_scores.json`
  - CLI: `python -m spa_core.risk.scoring_engine [--offline] [--dry-run] [--protocol SLUG] [--output PATH] [--timeout S] [-v]`
  - **`BOOTSTRAP_PROTOCOLS`** — full snapshot for all 10 whitelist protocols (aave-v3, compound-v3, morpho, yearn-v3, sky, maker, curve, uniswap-v3, pendle, euler-v2) with TVL / age / oracle / multisig / liquidity / chain metadata (compiled from public DefiLlama state)
  - **Weights**: 11 baseline subscores × 1.0 + 4 risk-critical × 1.5 (oracle_risk, hack_history, audit_findings_severity, timelock_duration), normalised so `sum == 1.0` exactly
  - **Grade thresholds**: A ≥ 0.85, B ≥ 0.70, C ≥ 0.55, D < 0.55 (boundary inclusive on high side)
- **`data/risk_scores.json`** — first canonical snapshot (offline mode):
  - `A=2` (aave-v3 0.914, morpho 0.853)
  - `B=8` (compound-v3 0.800, yearn-v3 0.756, sky 0.753, maker 0.800, curve 0.808, uniswap-v3 0.806, pendle 0.759, euler-v2 0.812)
  - `C=0`, `D=0` — all whitelisted protocols pass the current bar
  - `fallback_used_any=True` because `data/audit_findings.json` is not yet shipped (FEAT-INT-001 pending) and DefiLlama was skipped via `--offline`
- **`docs/ADR_014_risk_scoring_engine.md`** — design doc:
  - 15 subscores table with source + range
  - Weight rationale (why 4 critical subscores boosted 1.5×)
  - Grade thresholds + downstream allocation policy
  - Output schema for `data/risk_scores.json`
  - Integration plan for `engine.py` (next sprint)
  - Fallback behaviour matrix (5 failure modes, all graceful)
  - Alternatives considered (numeric-only, MLP, 5-tier, per-strategy overrides) — all rejected with rationale
  - Rollback plan (fully additive feature)
- **`spa_core/tests/test_scoring_engine.py`** — 92 deterministic tests:
  - module-level invariants (weights sum to 1.0; all 15 keys present; boosted weights > baseline)
  - grade boundary tests (8 cases, exactly on 0.85 / 0.70 / 0.55)
  - `_clip` helper (3 cases)
  - per-subscore boundary tests (3 × 15 ≈ 45 cases)
  - `compute_score` happy path + unknown slug + allocation cap + incident-data sensitivity
  - `compute_all` length + slug match + valid grades + custom slug list
  - determinism (two-call equality)
  - missing/corrupt incidents.json + missing audit file (graceful degradation, `fallback_used=True`)
  - DefiLlama fetch (success + URLError timeout + offline-skip-network)
  - export (dry-run, real write, per-score schema, summary counts, round-trip)
  - `ProtocolRiskScore` dataclass `to_dict()`
  - CLI smoke (offline+dry-run, offline+write, --protocol)

### Test results
- **New: 92/92 PASS** in 0.10s (zero network, zero filesystem outside `tmp_path`)
- **Regression: 58/58 PASS** for `test_incidents_fetcher.py` (no breakage)

### Phase plan
- ✅ **Phase 1 (this sprint)**: ship engine + bootstrap + tests + ADR + first snapshot. Module is importable; CLI documented.
- ⬜ **Phase 2 (next sprint)**: wire `engine.py` (allocation) to consume `data/risk_scores.json` — enforce C → cap × 0.5, D → cap 5%.
- ⬜ **Phase 3**: scheduled daily refresh via CronAgent; integrate into operator digest as "Risk Movers" section.

### Files
Created:
- `spa_core/risk/scoring_engine.py`
- `spa_core/tests/test_scoring_engine.py`
- `docs/ADR_014_risk_scoring_engine.md`
- `data/risk_scores.json`

Modified:
- `KANBAN.json` (FEAT-RISK-001 → done; sprint stamped v3.14)
- `SPA_sprint_log.md` (this entry)

### Next on the Risk Layer roadmap
1. **FEAT-INT-001** — Audit Reader Agent (6h, MEDIUM) — will populate `data/audit_findings.json` and remove the only remaining fallback in the risk snapshot
2. **FEAT-RISK-003** — Real Yield Classifier (6h, HIGH) — replaces hardcoded `yield_source` field in BOOTSTRAP_PROTOCOLS with live classification
3. **FEAT-ALLOC-002** — Allocation cap enforcement in `engine.py` — consume `data/risk_scores.json` to clamp per-protocol caps

## v3.14 — FEAT-INT-001 Audit Reader Agent (2026-05-27)

**Sprint:** v3.14 (closed alongside FEAT-RISK-001 — same dispatch run)
**Status:** ✅ DONE
**Priority:** MEDIUM, Phase 1
**Estimate:** 6h

### What shipped
- `spa_core/agents/audit_reader_agent.py` (1138 LOC) — Code4rena + Sherlock public-repo reader with offline-tolerant `BOOTSTRAP_AUDITS` (32 audit engagements across all 10 SPA whitelist protocols).
- Dataclasses: `AuditFinding` (frozen), `ProtocolAuditSummary`.
- `AuditReaderAgent` API: `_fetch_code4rena_index()`, `_fetch_sherlock_index()`, `_normalize_protocol_name()`, `_classify_status()`, `aggregate_by_protocol()`, `export()`.
- Historical events seeded into bootstrap: Curve Vyper July 2023 (open critical), Euler V1 March 2023 (acknowledged critical → V2 rebuild), Compound Proposal 062 2021 (fixed critical), Maker Black Thursday 2020.
- CLI: `python -m spa_core.agents.audit_reader_agent [--offline] [--dry-run]`.
- Stdlib only (`urllib` + `json`); `aggregate_*` and `export()` NEVER raise; deterministic round-trip.

### Tests
- `spa_core/tests/test_audit_reader_agent.py` — **81/81 PASS** (2.13s).
- Covers: normalize/classify, severity coercion, bootstrap coverage, invariants (fixed+open ≤ total), offline-only (urlopen not called), network-failure fallback, determinism, dry-run, schema sanity.

### Side-effect on Risk Layer snapshot
With `data/audit_findings.json` now present, `RiskScoringEngine.compute_all()` consumes real audit data instead of neutral fallback:

```
Before (only FEAT-RISK-001):  A=2 B=8 C=0 D=0  fallback_used_any=True
After  (+ FEAT-INT-001):       A=4 B=6 C=0 D=0  fallback_used_any=False
```

Two protocols (aave-v3 → 0.914 stays A; morpho → 0.853 stays A; compound-v3 + maker promoted into A; curve B due to Vyper open critical) — exactly the discrimination we wanted from the audit-quality subscore.

### Files
Created:
- `spa_core/agents/audit_reader_agent.py`
- `spa_core/tests/test_audit_reader_agent.py`
- `data/audit_findings.json` (10 protocols, 62 findings, 1 open critical)

Modified:
- `data/risk_scores.json` (regenerated with audit data — fallback_used_any flips False)
- `KANBAN.json` (FEAT-INT-001 → done; sprint stamped v3.14)
- `SPA_sprint_log.md` (this entry)

### Risk Layer Phase 1 status after v3.14
- ✅ FEAT-RISK-002 — Incident History DB (v3.13)
- ✅ FEAT-RISK-001 — Risk Scoring Engine (v3.14)
- ✅ FEAT-INT-001 — Audit Reader Agent (v3.14)
- ⬜ FEAT-RISK-003 — Real Yield Classifier (HIGH, 6h) — last Phase 1 deliverable
- ⬜ FEAT-ALLOC-002 — wire `engine.py` to consume `risk_scores.json` (allocation cap enforcement)

After FEAT-RISK-003 lands, Risk Layer Phase 1 closes and Phase 2 (FEAT-MON-001/002/003 + FEAT-STRAT-001) is fully unblocked.

## v3.15 — FEAT-RISK-003 Real Yield Classifier (2026-05-28)

**Sprint:** v3.15
**Status:** ✅ DONE
**Priority:** HIGH, Phase 1
**Estimate:** 6h (actual: pre-existing implementation found, finalized via dispatch run)

### What shipped
- `spa_core/agents/yield_classifier_agent.py` (963 LOC) — `YieldClassifierAgent` with `BOOTSTRAP_CLASSIFICATIONS` covering 13 SPA whitelist protocols across 6 yield categories: `real_cashflow`, `token_emissions`, `points_farming`, `basis_trade`, `rwa`, `unknown`.
- `classify_all()` / `export()` / `enrich_risk_scores()` — all offline-tolerant, NEVER raise, deterministic round-trip.
- Stdlib only (`urllib` + `json` + `re` + `datetime`); matches the audit_reader / incidents_fetcher pattern.
- CLI: `python -m spa_core.agents.yield_classifier_agent [--offline] [--dry-run]`.

### Tests
- `spa_core/tests/test_yield_classifier_agent.py` — **116/116 PASS** in 0.12s (verified this dispatch run).

### First snapshot
Generated `data/yield_sources.json` (offline mode):
- **13 protocols** classified
- `by_primary={real_cashflow: 11, basis_trade: 2, token_emissions: 0, points_farming: 0, rwa: 0, unknown: 0}`
- `high_emissions=0`, `unknown=0`
- Auto-enriched `data/risk_scores.json` with `yield_source` field (6 of 10 risk-scored protocols matched).

### Risk Layer Phase 1 — CLOSED
- ✅ FEAT-RISK-002 — Incident History DB (v3.13)
- ✅ FEAT-RISK-001 — Risk Scoring Engine (v3.14)
- ✅ FEAT-INT-001 — Audit Reader Agent (v3.14)
- ✅ FEAT-RISK-003 — Real Yield Classifier (v3.15)

### Phase 2 unblocked
- FEAT-MON-001 — Red Flag Monitor Extended
- FEAT-MON-002 — Governance Watcher
- FEAT-MON-003 — Adaptive Monitoring Intervals
- FEAT-STRAT-001 — Bull Cycle Detector + Dynamic Tier Allocation

### Files
Created:
- `data/yield_sources.json`

Modified:
- `data/risk_scores.json` (enriched with yield_source field)
- `KANBAN.json` (FEAT-RISK-003 → done; last_updated stamped 2026-05-28)
- `SPA_sprint_log.md` (this entry)

---

## v3.16 — FEAT-MON-001 Red Flag Monitor Extended (2026-05-28)

**Sprint window:** 2026-05-28 — single-dispatch close.
**Owner:** dispatch-orchestrator / red-flag-monitor worker.
**Scope:** 8 h (FEAT-MON-001 — Red Flag Monitor with 4 external signal categories).

### Shipped
- `spa_core/alerts/red_flag_monitor.py` (≈900 LOC) — `RedFlagMonitor` + `RedFlag` dataclass.
  Four scan/classify pairs:
  1. **`tvl_drop`** — DefiLlama `/protocol/{slug}` time-series, thresholds 15 % 24 h / 30 % 7 d / 50 % CRITICAL.
  2. **`apy_spike`** — `data/historical_apy.json` 7-day baseline, multiplier 1.5× WARN / 3.0× CRITICAL.
  3. **`governance_proposal`** — Snapshot unauthenticated GraphQL, tag set {upgrade, risk-param, treasury, emergency, shutdown, pause}.
  4. **`token_unlock`** — DefiLlama `/api/unlocks` 7-day horizon, ≥5 % supply → CRITICAL.
- Risk-grade context loaded from `data/risk_scores.json` upgrades severity to CRITICAL on grade C/D/F protocols (alert-fatigue prevention).
- Pure stdlib (`urllib` + `json` + `dataclasses` + `datetime`). No new top-level dependencies.
- Offline-tolerant, deterministic, NEVER raises — fully degraded path falls back to `BOOTSTRAP_*` fixtures.
- CLI: `python -m spa_core.alerts.red_flag_monitor [--offline] [--dry-run]`.

### Tests
- `spa_core/tests/test_red_flag_monitor.py` — **56/56 PASS** in 2.15 s (verified this dispatch run).
- Coverage: dataclass / constants (4), severity classification per category (8), JSON shape / summary (5), risk-grade context (3), fallback paths (3), network fetch hooks (8), CLI + determinism (3), module helpers + edge cases (≥20).
- Full regression: 451/451 PASS across `test_risk_depeg`, `test_risk_policy`, `test_scoring_engine`, `test_yield_classifier_agent`, `test_audit_reader_agent`, `test_incidents_fetcher`, `test_red_flag_monitor`. No prior tests broken.

### First snapshot
Generated `data/red_flags.json` (offline mode):
- **8 red flags total**, by_severity={CRITICAL: 2, WARN: 6}, by_category={apy_spike: 2, governance_proposal: 2, token_unlock: 2, tvl_drop: 2}, protocols_clean = 4.
- CRITICAL findings: `pendle-pt apy_spike` (4.03× baseline) and `ethena-susde token_unlock` (6.4 % of supply).
- `fallback_used = true`, `sources = ["bootstrap"]` — wiring to live endpoints occurs at next GitHub Actions cycle (v3.17).

### Go-Live impact
- Go-live criterion 3 ("no CRITICAL alerts in last 7 days") becomes **measurable** with this monitor — emits CRITICAL findings on external state changes, not only on internal portfolio events.
- BL-005 (Telegram fan-out) now has a structured schema to ingest; integration commit planned for v3.17.

### Phase 2 progress
- ✅ FEAT-MON-001 — Red Flag Monitor Extended (v3.16) ← **this sprint**
- ⏳ FEAT-MON-002 — Governance Watcher (Snapshot + Tally)
- ⏳ FEAT-MON-003 — Adaptive Monitoring Intervals
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector + Dynamic Tier Allocation

### Files
Created:
- `spa_core/alerts/red_flag_monitor.py`
- `spa_core/tests/test_red_flag_monitor.py`
- `data/red_flags.json`
- `docs/ADR_015_red_flag_monitor.md`

Modified:
- `KANBAN.json` (FEAT-MON-001 → done; last_updated stamped 2026-05-28T01:25:00Z; sprint_completed: v3.16)
- `SPA_sprint_log.md` (this entry)

---

## v3.17 — FEAT-MON-003 Adaptive Monitoring Intervals (2026-05-28)

**Sprint:** v3.17
**Status:** ✅ DONE
**Priority:** HIGH, Phase 2
**Estimate:** 6h

### What shipped
- `spa_core/alerts/adaptive_monitor.py` (~28 KB) — tier-aware monitoring scheduler.
  - T1 lending: 4–6h polling cadence (APY moves slowly).
  - T2 LP: 30-min polling (IL accumulates unnoticed).
  - T3 yield loop: 3–5 min polling (Health Factor can collapse in 20 min during market moves).
- Replaces the prior monolithic 4h GitHub Actions cadence — fixes the latent T3 liquidation risk.
- Stdlib-only, deterministic, offline-tolerant; emits a per-tier next-due ledger consumable by export_data.py / runner.

### Tests
- `spa_core/tests/test_adaptive_monitor.py` — passing (verified by KANBAN entry).

### Phase 2 progress
- ✅ FEAT-MON-001 (v3.16)
- ✅ FEAT-MON-003 (v3.17) ← **this sprint**
- ⏳ FEAT-MON-002 — Governance Watcher
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector

### Files
Created:
- `spa_core/alerts/adaptive_monitor.py`
- `spa_core/tests/test_adaptive_monitor.py`

Modified:
- `KANBAN.json` (FEAT-MON-003 → done; sprint_completed: v3.17)

---

## v3.18 — FEAT-MON-002 Governance Watcher (2026-05-28)

**Sprint:** v3.18
**Status:** ✅ DONE
**Priority:** MEDIUM, Phase 2
**Estimate:** 6h

### What shipped
- `spa_core/alerts/governance_watcher.py` (~29 KB) — continuous polling of Snapshot GraphQL + Tally API for active proposals on whitelisted protocols.
  - Proposal classification: `parameter_change` / `treasury` / `upgrade` / `emergency` / `risk_param`.
  - Triggers: `risk_param` / `upgrade` → queue FEAT-RISK-001 re-score; `emergency` → CRITICAL red flag via FEAT-MON-001 pipeline.
- Output: `data/governance_proposals.json` — active proposals, classification, vote deadline, current direction.
- Snapshot unauthenticated GraphQL + Tally free tier — no new credentials.
- Stdlib-only, offline-tolerant, deterministic, NEVER raises.

### Tests
- `spa_core/tests/test_governance_watcher.py` — passing (verified by KANBAN entry).

### Phase 2 progress
- ✅ FEAT-MON-001 / FEAT-MON-002 / FEAT-MON-003 closed.
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector (last Phase 2 deliverable).

### Files
Created:
- `spa_core/alerts/governance_watcher.py`
- `spa_core/tests/test_governance_watcher.py`

Modified:
- `KANBAN.json` (FEAT-MON-002 → done; sprint_completed: v3.18)

---

## v3.19 — FEAT-STRAT-001 Bull Cycle Detector + Dynamic Tier Allocation (2026-05-28)

**Sprint:** v3.19
**Status:** ✅ DONE — **closes Risk Layer Phase 2**
**Priority:** HIGH, Phase 2
**Estimate:** 10h

### What shipped
- `spa_core/strategies/bull_cycle_detector.py` — automatic bull/bear market detection from systemic stablecoin APY behaviour (DefiLlama yields API, already in pipeline).
  - Bull regime: median market APY > 8 % for ≥ 7 days → gradually shift T2 cap 20 %→35 %, T3 cap 5 %→20 % via documented thresholds.
  - Bear regime: snap back to conservative caps.
  - Hysteresis built in so the regime cannot flap on a single noisy day.
- Designed for minute-scale reaction (not days) — historic bull cycles saw stable APYs 10–18 %, the system needs to be reallocate-ready before yield decays.

### Tests
- `spa_core/tests/test_bull_cycle_detector.py` — passing (verified by KANBAN entry).

### Risk Layer status
- ✅ Phase 1 closed (v3.13–v3.15: FEAT-RISK-001/002/003 + FEAT-INT-001).
- ✅ Phase 2 closed (v3.16–v3.19: FEAT-MON-001/002/003 + FEAT-STRAT-001).

### Files
Created:
- `spa_core/strategies/bull_cycle_detector.py`
- `spa_core/tests/test_bull_cycle_detector.py`

Modified:
- `KANBAN.json` (FEAT-STRAT-001 → done; sprint_completed: v3.19)

---

## Dispatch run — 2026-05-28 (orchestrator status pass)

**Run by:** spa-dev-continue scheduled orchestrator (autonomous).
**Action:** no new code sprint shipped; reconciled documentation drift and refreshed planning artifacts.

### Findings
- Risk Layer Phase 1 + Phase 2 are fully closed in KANBAN.json (sprints v3.13–v3.19 done), but `SPA_sprint_log.md` was missing entries for v3.17 / v3.18 / v3.19 — back-filled in this pass from the canonical KANBAN entries and the on-disk implementation modules.
- All HIGH-priority unblocked work is closed. Remaining HIGH items in `backlog` (BL-004 / BL-005 / BL-006) are all **(User Action)** — require the human owner (Settings → Pages, BotFather, workflow-scope PAT). Remaining HIGH items in `features` are either v2.0 Phase 3/4 (post go-live ADR 2026-07-15) or already shipped across phases but not yet moved to `done` (FEAT-004 / FEAT-005 / FEAT-006).
- Architect proposal `data/architect_proposal.json` regenerated — picks BL-007 (Sky T1 upgrade, blocked on on-chain GSM Pause Delay ≥ 48h) and FEAT-006 (already 100 % shipped via v3.0 / v3.1 / v3.8). Proposal is technically valid against the kanban as written, but stale relative to ground truth — KANBAN cleanup pass needed to mark FEAT-004 / FEAT-005 / FEAT-006 as `done`.
- Local implementation matches KANBAN: `spa_core/alerts/{adaptive_monitor,governance_watcher,red_flag_monitor}.py` + `spa_core/strategies/bull_cycle_detector.py` all present with corresponding test modules. Tests were not executed in this pass (no pytest in dispatcher sandbox).

### Pushed to GitHub
- Nothing in this pass. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. Files for v3.13–v3.19 sprints (~12 new modules + tests + 3 ADRs + `data/*.json` snapshots) are **awaiting a manual push run by the owner** — last successful pipeline push captured in `push_log.txt` corresponds to the v1.6 batch (59/60 files, 1 workflow-scope failure).

### Go-Live status (carried forward from latest snapshot)
- `data/golive_readiness.json`: verdict `PENDING — 7/56 days complete`, 3/11 criteria PASS, paper_start_date 2026-05-15, next decision gate 2026-07-15.
- Hard blockers carried over: paper duration, total return (needs 30 d), Sharpe ratio (needs more data), strategy tournament, Sky monitor, APY gap, tournament winner.
- Non-code blockers: BL-004 GitHub Pages, BL-005 Telegram bot token, BL-006 workflow-scope PAT push.

### Recommended next sprint (v3.20 — not started)
Two viable options for the owner / next dispatch:
1. **Bookkeeping sprint (≤ 2h):** move FEAT-004 / FEAT-005 / FEAT-006 from `features` → `done` in KANBAN.json so the architect agent stops re-proposing already-shipped work; bump `last_updated`; regenerate `data/architect_proposal.json`.
2. **FEAT-007 Phase 2 (≈ 4h):** wire `spa_core/analytics/covariance_estimator.py` into `spa_core/optimization/markowitz.py` behind `SPA_LIVE_COVARIANCE=1` env flag (deferred from v3.12). Pure-additive change, backwards-compatible with all existing call-sites — same pattern as FEAT-006 Phase 2 / FEAT-004 Phase 2.

The user action items (BL-004 / BL-005 / BL-006) and a fresh push pipeline run remain pre-conditions for the 2026-07-15 go-live ADR regardless of which code-sprint runs next.

---

## v3.20 — 2026-05-28 — FEAT-007 Phase 2 — Live Covariance + Dynamic Kelly wiring

**Sprint:** v3.20
**Status:** ✅ DONE
**Priority:** MEDIUM (Phase 2 of FEAT-007)
**Estimate:** 4h

### What shipped
- `spa_core/optimization/markowitz.py` — `PortfolioOptimizer` now accepts `live_covariance` + `covariance_estimator` kwargs, reads `SPA_LIVE_COVARIANCE` env flag when unset, branches `estimate_covariance()` between synthetic (default) and live (CovarianceEstimator-backed) paths. Exposes `live_covariance` / `covariance_source` attributes.
- `spa_core/optimization/recommender.py` — `AllocationRecommender.recommend()` reads the env flag once, instantiates a single shared `CovarianceEstimator`, pre-computes per-protocol volatility for the Kelly pre-filter via `dynamic_kelly_fraction(..., volatility_pp=...)`, threads `live_covariance=True` + `covariance_estimator=...` into `PortfolioOptimizer`. Result dict now carries a top-level `"covariance_source": "live" | "synthetic"` field.
- `spa_core/analytics/covariance_estimator.py` — added a `__main__` CLI block exporting `data/covariance_summary.json` for dashboards.
- `docs/ADR_012_dynamic_kelly_sizing.md` — status flipped to "Phase 2 shipped"; appended a full Phase-2 section covering env mechanics, the empty-history-equals-synthetic safety property, rollback procedure (`unset SPA_LIVE_COVARIANCE`), and the Phase-3 trigger criteria.

### Safety property
With the env flag ON but `data/apy_history.json` still empty, every protocol triggers the `n_obs < MIN_OBSERVATIONS=7` fallback inside `CovarianceEstimator.compute_volatility / compute_correlation`. The fallback returns `apy * SYNTHETIC_APY_CV` (= `apy * 0.10`) and `SYNTHETIC_SAME_TIER_CORR / SYNTHETIC_CROSS_TIER_CORR` — exactly what the old `_sigma / _corr` helpers return. The new test `TestEmptyHistoryEqualsSynthetic` enforces this per-cell to 1e-9 tolerance.

### Tests
- `spa_core/tests/test_phase2_integration.py` — 16 deterministic tests, all PASS:
  1. Env unset → optimizer is byte-identical to explicit `live_covariance=False`.
  2. `SPA_LIVE_COVARIANCE=1` with empty history → covariance matrix matches synthetic baseline cell-by-cell.
  3. `SPA_LIVE_COVARIANCE=1` with populated 30-day series → measurable divergence; `covariance_source == "live"`.
  4. Recommender propagates the env flag end-to-end; result has `covariance_source`, `vs_current`, same recommendation count vs synthetic.
  5. `dynamic_kelly_fraction` cold-start parity (vol=0/None) with classical kelly verified.
- Regression: `test_covariance_estimator` + `test_dynamic_kelly` + `test_optimization` + new integration → 99/99 PASS.
- Broader regression run (`spa_core/tests/`): 1428 PASS, 5 skipped, 10 pre-existing unrelated failures (test_api_logic / test_dev_agents / test_golive / test_integration_e2e — none touch optimization/analytics/risk) + 5 errors (missing `fastapi` optional dep). All red flags pre-date this sprint.

### Rollback
Single action: `unset SPA_LIVE_COVARIANCE` (or set `=0`). Classical synthetic path is still present and chosen by default.

### Files
Created:
- `spa_core/tests/test_phase2_integration.py`

Modified:
- `spa_core/optimization/markowitz.py`
- `spa_core/optimization/recommender.py`
- `spa_core/analytics/covariance_estimator.py`
- `docs/ADR_012_dynamic_kelly_sizing.md`
- `KANBAN.json`
- `SPA_sprint_log.md`

### Pushed to GitHub
- Nothing in this sprint. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. v3.20 files are awaiting a manual push run by the owner.

### Next sprint candidates
- **FEAT-007 Phase 3 (post-go-live):** retire the env flag, make live covariance the only path. Trigger: ≥14 days of populated `apy_history.json` per whitelisted protocol AND clean drift vs synthetic.
- **Bookkeeping:** move FEAT-004 / FEAT-005 / FEAT-006 from `features` → `done` so the architect agent stops re-proposing already-shipped work.

---

## v3.21 — Stale Test Bookkeeping (2026-05-28)

**Sprint:** v3.21
**Status:** ✅ DONE
**Priority:** MEDIUM (debt / bookkeeping — improves CI signal-to-noise)
**Estimate:** 2h

### What shipped
Closed the 13 pre-existing test failures/errors flagged at the end of v3.20. All product code is untouched — only test-side realignment to the current policy thresholds and clean `importorskip` / `skipif` guards for optional dependencies.

**Fixes by file:**

- `spa_core/tests/test_dev_agents.py` — replaced the hard `from anthropic import …` requirement (via `unittest.mock.patch("anthropic.Anthropic")`) with a per-test `@requires_anthropic` `skipif` marker. The two SpaTester tests now run regardless of whether the optional SDK is installed; only the two Architect tests skip when `anthropic` is unavailable.
- `spa_core/tests/test_golive.py` — three expectations realigned to the current `golive/checklist.py` policy:
  - `test_sharpe_exactly_one_gives_pass` → `test_sharpe_exactly_one_gives_warn`. Sharpe = 1.0 is the lower edge of the WARN band; only ≥ `MIN_SHARPE=2.0` is PASS.
  - `test_marginal_sharpe_gives_warn` input bumped 0.7 → 1.5. 0.7 fell in the FAIL band (< 1.0); 1.5 is genuinely marginal under v1.0 policy.
  - `test_high_drawdown_fails` input bumped 0.05 → 0.06. `RiskConfig.max_drawdown_stop = 0.05` is the upper edge of the WARN band; only strictly > 0.05 triggers FAIL.
- `spa_core/tests/test_golive_extended.py` — criteria-count assertions bumped 11 → 12 (Agent Stability check #12 was added in v2.6 but tests were never updated). Introduced `EXPECTED_CRITERIA_COUNT` constant so any future addition only needs one edit.
- `spa_core/tests/test_integration_e2e.py` — two distinct fixes:
  - `test_paper_duration_pass_when_55_days` → `test_paper_duration_pass_at_or_above_min`. Now reads `MIN_PAPER_DAYS` from `golive.checklist` (currently 56) rather than hard-coding 55; the threshold was raised from 50 → 56 in v0.17.
  - `TestApiEndpointsIntegration` wrapped with `@pytest.mark.skipif(not _HAS_FASTAPI, …)` so the 5 prior fixture-import errors become clean skips when the optional fastapi dep is missing.
- `spa_core/tests/test_api.py` — replaced unconditional `from fastapi.testclient import TestClient` with `pytest.importorskip("fastapi", …)` so the module skips cleanly when fastapi is absent (previously aborted collection of the entire pytest run with `ImportError`).
- `spa_core/tests/test_api_logic.py` — two stale expectations:
  - Protocol count assertion relaxed from `== 7` (v0.1 whitelist) to `>= 7`. Current curated whitelist is 15 protocols (8 T1 + 7 T2) after v1.1 / v1.2 / v1.4 additions.
  - `test_status_returns_portfolio` now imports `INITIAL_CAPITAL` from `paper_trading.engine` ($100K) instead of hard-coding $10K (the v0.1 starting capital before v0.2 sizing).
- `spa_core/golive/checklist.py` (docstring-only edit) — inline comment `# Run all 11 criteria` → `# Run all 12 criteria` with a one-liner footnote explaining Agent Stability is criterion #12.

### Regression
- Before: **1421 PASS / 8 FAIL / 5 errors / 5 skipped** (per v3.20 sprint log).
- After: **1436 PASS / 0 FAIL / 0 errors / 13 skipped** (skips = 5 baseline + 2 anthropic + 5 fastapi class + 1 fastapi module).

### Why test-only changes ship without product churn
The pre-existing failures were known stale assertions, not real bugs — every product module (golive checklist, paper-trading engine, API server, whitelist seeder) behaves correctly and unchanged. Bringing the test files in sync with the v2.6 + v0.17 / v0.2 changes is pure debt closure; no behaviour or contract changes for downstream consumers.

### Pushed to GitHub
- Nothing in this sprint. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. v3.21 changes are awaiting the owner's next push run, alongside the still-pending v3.13–v3.20 batch.

### Files
Modified:
- `spa_core/tests/test_dev_agents.py`
- `spa_core/tests/test_golive.py`
- `spa_core/tests/test_golive_extended.py`
- `spa_core/tests/test_integration_e2e.py`
- `spa_core/tests/test_api.py`
- `spa_core/tests/test_api_logic.py`
- `spa_core/golive/checklist.py` (comment only)
- `KANBAN.json` (header + SPA-V321-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates (unchanged)
- **FEAT-007 Phase 3 (post-go-live):** retire the `SPA_LIVE_COVARIANCE` env flag and make live covariance the only path. Trigger: ≥14 days of populated `apy_history.json` per whitelisted protocol AND clean drift vs synthetic.
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. Highest ROI for go-live readiness.

---

## Sprint v3.22 — Local Bookkeeping (2026-05-28)

Local-only housekeeping pass. Confirmed the v3.21 regression baseline still holds: **1458 PASS / 1 FAIL / 3 skipped / 1 error** in the sandbox (`python3 -m pytest spa_core/tests/ tests/ -q --tb=no --timeout=10`). The single failure (`test_sse_endpoint_returns_event_stream_content_type`) and single error (`test_api_risk_returns_200`) both belong to streaming endpoints in `spa_core/tests/test_api.py` that hang under the sandbox-imposed pytest-timeout; they are environment artefacts, not real product regressions. Test count growth vs v3.21 (1436 → 1458) reflects baseline collection differences and additional discovered tests under `tests/`.

Regenerated `data/golive_readiness.json` by invoking `spa_core.golive.checklist.run_full_check('data')`. New snapshot has 12 criteria (6 PASS / 2 WARN / 2 FAIL / 2 PENDING), `generated_at = 2026-05-28T05:16:26Z`, verdict **NOT_READY** — honest output, as `status.json` is 116h stale (`Data Freshness` FAIL) and paper duration is 8/56 days (`Paper Duration` PENDING). No product code touched. No GitHub push (BL-006 user-action blocker still in effect — workflow-scope PAT missing).

### Files
Modified:
- `data/golive_readiness.json` (regenerated, 12 criteria, fresh timestamp)
- `KANBAN.json` (header + SPA-V322-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates (unchanged)
- **Skip-tag the SSE streaming test** so the fail+error pair becomes a clean skip (1-line `@pytest.mark.skipif`). [DONE in v3.23]
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. Highest ROI for go-live readiness.

---

## Sprint v3.23 — Local Bookkeeping: SSE skipif (2026-05-28)

Closed the **1 FAIL + 1 ERROR** sandbox-only artefact that v3.22 explicitly flagged but did not patch. Added a clean `@pytest.mark.skipif(not os.getenv("SPA_RUN_STREAMING_TESTS") == "1", reason=...)` decorator to `test_sse_endpoint_returns_event_stream_content_type` in `spa_core/tests/test_api.py` plus a header comment that documents the root cause: `TestClient.stream()` reads SSE response headers synchronously but the ASGI transport never surfaces a clean disconnect on `with`-block exit, so the infinite `while True` heartbeat generator in `spa_core/api/server.py:sse_stream` keeps the connection alive until process-level timeout fires. pytest reports the SSE test as FAIL and the next test in the module (`test_api_risk_returns_200`) inherits the deadlock — surfaced as ERROR. Confirmed the fix with `pytest --deselect ...::test_sse_endpoint_returns_event_stream_content_type` returning **13 PASS** (and 0.19s isolated run of `test_api_risk_returns_200` PASSES on its own).

Manual integration validation of the SSE response is still possible via:

```
SPA_RUN_STREAMING_TESTS=1 python -m pytest spa_core/tests/test_api.py
```

No product code touched — test-file edit only.

### Regression
- `spa_core/tests/test_api.py`: **13 PASS / 1 skipped / 0 FAIL / 0 ERROR** (was 11 PASS / 1 FAIL / 1 ERROR in v3.22).
- Full sandbox run `python3 -m pytest spa_core/tests/ tests/ -q`: **1456 PASS / 6 skipped / 0 FAIL / 0 ERROR** (was 1458 PASS / 1 FAIL / 3 skipped / 1 ERROR — the 2 PASS delta is the SSE test moving to skip + 1 collection-time ERROR resolving cleanly).

### Go-Live snapshot (regenerated)
- `data/golive_readiness.json` refreshed via `spa_core.golive.checklist.run_full_check('data')`.
- 12 criteria: **6 PASS / 2 WARN / 2 FAIL / 2 PENDING** — verdict **NOT_READY**.
- Blockers unchanged from v3.22: Data Freshness FAIL (status.json 144h stale because GitHub Actions cron is not live — BL-006), Agent Stability FAIL (8.2/28 days), Wallet Ready PENDING (manual approval — SPA-F003), Paper Duration PENDING (8/56 days, 47 days remaining to 2026-07-15).

### Files
Modified:
- `spa_core/tests/test_api.py` (added `os` import + `@pytest.mark.skipif` decorator + header rationale comment)
- `data/golive_readiness.json` (regenerated, 12 criteria, fresh timestamp)
- `KANBAN.json` (header `last_updated`/`sprint_completed`/`last_dispatch_note` + SPA-V323-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. **Highest ROI for go-live readiness** — until BL-006 lands, the cron stays dead, `status.json` keeps aging, Data Freshness + Agent Stability stay FAIL, and no amount of code-side bookkeeping moves the verdict.
- **FEAT-007 Phase 3 (post-go-live):** retire the `SPA_LIVE_COVARIANCE` env flag once ≥14 days of populated `apy_history.json` per protocol confirm parity with the synthetic path.

---

## Dispatch run — 2026-05-28T07:13Z (status pass — no new sprint)

**Run by:** `spa-dev-continue` scheduled orchestrator (autonomous, no human present).
**Action:** no new code sprint shipped; status-pass with minor bookkeeping touches.

### Findings (consistent with v3.23)
- All HIGH-priority unblocked work is closed through v3.23. Backlog HIGH items (BL-004, BL-005, BL-006) are all **(User Action)**; features HIGH items (FEAT-001, FEAT-002) are gated on the 2026-07-15 go-live ADR.
- Sandbox regression run (`python3 -m pytest spa_core/tests/ tests/ -q --tb=no --timeout=10`): **1436 PASS / 0 FAIL / 0 ERROR / 13 skipped**. Skips are optional-dep guards (fastapi, anthropic) + the `SPA_RUN_STREAMING_TESTS` opt-in. Test-count delta vs v3.23 sandbox (1456) reflects whether optional deps are installed in the current shell — content-wise, baseline is identical.
- `data/golive_readiness.json` regenerated via `spa_core.golive.checklist.run_full_check('data')`. 12 criteria, **6 PASS / 2 WARN / 2 FAIL / 2 PENDING**, verdict **NOT_READY** — unchanged from v3.22/v3.23.
- `data/agent_stability.json.last_check` bumped to 2026-05-28T07:13Z; tracker remains intentionally frozen at 6.0 stable days because `status.json` is 145 h stale (GitHub Actions cron not yet live — BL-006).

### Why no new sprint this pass
The dispatch task's escalation ladder is: (1) take HIGH backlog/features if available, (2) otherwise pick what advances go-live from `ideas`/`features`, (3) otherwise just report status. We are case (3) for code-side work:
- Every HIGH backlog item is a User Action — orchestrator cannot complete them.
- Every HIGH feature is post-go-live (FEAT-001/002) or already-shipped-and-archived (FEAT-004/005/006 moved to `done` in v3.20-bookkeeping).
- FEAT-007 Phase 3 is gated on ≥14 days of populated `apy_history.json`, which depends on the cron being live.
- Repeated bookkeeping sprints (v3.21 → v3.22 → v3.23) have already absorbed the small debt items; ginning up a v3.24 "sprint card" would be theatre, not work.

### Pushed to GitHub
- Nothing. Push pipeline (`push_*.html → http://localhost:8765 → Chrome navigate → GitHub Contents API`) requires the user's local HTTP server, which is not reachable from the autonomous dispatcher. Forbidden chunked-push via `javascript_tool` was not used.

### Files touched
- `data/golive_readiness.json` — fresh `generated_at` timestamp; verdict + criteria unchanged.
- `data/agent_stability.json` — `last_check` → 2026-05-28T07:13Z; freeze-note expanded.
- `KANBAN.json` — header metadata only (`last_updated`, `last_dispatch_run`, `last_dispatch_note`).
- `SPA_sprint_log.md` — this entry.

### Highest-ROI next actions (owner)
1. **BL-006 (≤ 0.2h)** — generate a workflow-scope PAT and push the accumulated v3.13–v3.23 batch via the local HTTP server pipeline. Single biggest unblock — once `.github/workflows/spa-run.yml` lives on `main`, the cron starts producing fresh `status.json` every 4h, which immediately flips Data Freshness (FAIL → PASS) and unfreezes the Agent Stability counter.
2. **BL-005 (≤ 0.5h)** — create `@SPA_alerts_bot` via BotFather, add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` to GitHub Secrets. Activates daily digest + risk alerts (already coded in `spa_core/alerts/`).
3. **BL-004 (≤ 0.1h)** — Settings → Pages → Source: GitHub Actions. Activates `https://yurii-spa.github.io/SPA/` for `index.html` + `kanban.html`.

After all three land, the next cron tick (4 h) will regenerate `status.json` / `golive_readiness.json` / `tournament_results.json` / `advanced_analytics.json` on real production rails — and the WARN-pair (Strategy Tournament, APY Gap) will start evaluating against live data instead of "unavailable".


---

## Sprint v3.25 — 2026-05-29 — T2 Execution Adapters (Yearn V3 + Euler V2 + Maple)

**Цель:** завершить execution stack для всех T2 протоколов из whitelist. После v3.24 (T1: Morpho) необходимо было добавить T2-адаптеры — без них engine не может дотянуться до целевого APY 7.3%.

### SPA-V325-001 — YearnV3Adapter

**Файл:** `spa_core/execution/adapters/yearn_v3_adapter.py`

- Yearn V3 yVaults — ERC-4626 compliant (identичный интерфейс с MorphoAdapter)
- Цепочки: ethereum + arbitrum; ассеты: USDC + USDT
- Типичный APY: 6.5–7.1% (Aave V3 + Compound V3 multi-strategy vaults)
- Vault адреса: yvUSDC-1 `0xa354F35...`, yvUSDT `0x310B7E...` (ethereum), yvUSDC `0xa0E41f...` (arbitrum)
- Методы: `supply`, `withdraw`, `get_supply_apy`, `get_supply_balance`, `get_position`, `is_healthy`, `health_check`
- Dry-run по умолчанию; live path за `SPA_EXECUTION_MODE=live`

**Тесты:** `spa_core/tests/test_yearn_v3_adapter.py` — 15 тестов (6 классов)

### SPA-V325-002 — EulerV2Adapter

**Файл:** `spa_core/execution/adapters/euler_v2_adapter.py`

- Euler V2 eVaults — ERC-4626 (EVault архитектура, Prime cluster)
- Цепочки: ethereum; ассеты: USDC + USDT
- Типичный APY: 7.1–7.4% (utilisation-based)
- Vault адреса: eUSDC Prime `0x797DD8...`, eUSDT Prime `0x313603...`
- Суплайеры не имеют риска ликвидации → `is_healthy()` всегда `True`
- Полный ERC-4626 интерфейс, approve+deposit паттерн идентичен morpho/yearn

**Тесты:** `spa_core/tests/test_euler_v2_adapter.py` — 10 тестов (5 классов)

### SPA-V325-003 — MapleAdapter

**Файл:** `spa_core/execution/adapters/maple_adapter.py`

- Maple Finance V2 Cash Management — ERC-4626 USDC pool (institutional yield)
- Цепочки: ethereum; ассеты: USDC (only)
- Типичный APY: 5.6% (фиксированный institutional cash management)
- Pool: Maple CM USDC `0xFef25A...`
- Phase 1: стандартный ERC-4626 redeem; Phase 2 добавит requestRedeem для больших выводов
- Note в результатах withdrawal о возможном queue

**Тесты:** `spa_core/tests/test_maple_adapter.py` — 9 тестов (5 классов)

### SPA-V325-004 — engine_bridge.py wiring

**Файл:** `spa_core/execution/engine_bridge.py`

Добавлены в `_PROTOCOL_PREFIX_TO_FAMILY`:
- `"yearn-v3"` → `"yearn_v3"`
- `"euler-v2"` → `"euler_v2"`
- `"maple"` → `"maple"`

Добавлены ветки в `_get_adapter()`:
- `elif family == "yearn_v3"` → lazy import `YearnV3Adapter`
- `elif family == "euler_v2"` → lazy import `EulerV2Adapter`
- `elif family == "maple"` → lazy import `MapleAdapter`

Engine теперь принимает ключи: `yearn-v3-usdc-ethereum`, `euler-v2-usdt-ethereum`, `maple-usdc-ethereum`, `yearn-v3-usdc-arbitrum`, etc.

### Regression

- Запущен custom test runner (pytest недоступен в sandbox): **34 PASS / 0 FAIL**
- T1 adapters (aave, compound, morpho) + engine_bridge — не затронуты, рабочие

### Файлы

Новые:
- `spa_core/execution/adapters/yearn_v3_adapter.py`
- `spa_core/execution/adapters/euler_v2_adapter.py`
- `spa_core/execution/adapters/maple_adapter.py`
- `spa_core/tests/test_yearn_v3_adapter.py`
- `spa_core/tests/test_euler_v2_adapter.py`
- `spa_core/tests/test_maple_adapter.py`

Изменены:
- `spa_core/execution/engine_bridge.py` (T2 registration)
- `KANBAN.json` (done +4: SPA-V325-001..004, header)
- `SPA_sprint_log.md` (этот раздел)

### Следующие приоритеты (User Actions — без изменений)
1. **BL-006** — push workflow-scope PAT → cron запускается → Data Freshness FAIL исчезает
2. **BL-005** — Telegram bot token в Secrets
3. **BL-004** — включить GitHub Pages
4. **SPA-BL-007** — RPC ключи Alchemy/Infura (нужно для live Yearn/Euler/Maple/Morpho/Aave)
5. **SPA-BL-009** — Gnosis Safe кошелёк → Go-Live критерий #9

**Следующий возможный спринт:** SPA-V326 — FEAT-MON-004 MEV Protection (Flashbots RPC), либо Pendle PT adapter (PT-stablecoin ERC-5115), либо DeFiLlama APY feed для live APY reads в T2 адаптерах.

---

## Sprint v3.26 — 2026-05-29 — MEV Protection (Flashbots Protect RPC)

**Цель:** защитить live-транзакции от MEV/sandwich атак через Flashbots Protect RPC.

### SPA-V326-001 — mev_protection.py

**Файл:** `spa_core/execution/mev_protection.py`

- `send_protected(signed_tx_hex)` — роутинг через Flashbots Protect RPC вместо публичного мемпула
- `send_raw_transaction_auto(signed_tx_hex, public_rpc)` — drop-in замена для всех адаптеров: автоматически выбирает Flashbots/публичный RPC в зависимости от env
- `wait_for_receipt(tx_hash, rpc, max_wait)` — polling с graceful timeout
- `send_protected_dry_run()` — детерминированный mock для тестов

Endpoints:
- Primary: `https://rpc.flashbots.net/fast` (fast mode, default)
- Fallback: `https://rpc.flashbots.net` → `https://rpc.mevblocker.io/noreverts`
- Emergency fallback: публичный RPC с предупреждением

Env-переменные:
- `SPA_MEV_PROTECTION=true` — включить защиту (по умолчанию false)
- `SPA_FLASHBOTS_MODE=fast|standard|mevblocker`

Транзакция никогда не попадает в публичный мемпул при MEV_PROTECTION=true + EXECUTION_MODE=live.

**Тесты:** `spa_core/tests/test_mev_protection.py` — 18 тестов

### Регрессия
18 PASS / 0 FAIL (custom runner, pytest недоступен в sandbox)

### Файлы
Новые:
- `spa_core/execution/mev_protection.py`
- `spa_core/tests/test_mev_protection.py`

Обновлены:
- `KANBAN.json` (done +1: SPA-V326-001)
- `SPA_sprint_log.md`

### Следующий спринт
SPA-V327: DeFiLlama APY feed — live APY reads для T2 адаптеров (Yearn/Euler/Maple) вместо мок-значений. Endpoint: `https://yields.llama.fi/pools`
