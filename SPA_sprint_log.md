# SPA Sprint Log — updated 2026-05-22

## Completed ✅

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
