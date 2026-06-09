# SPA Architect Review — 2026-05-22

**Reviewer:** Architect Agent (Claude Sonnet 4.6)
**Scope:** Full codebase review — engine, risk policy, data pipeline, go-live checklist, CI, alerts
**Go-Live Target:** 2026-07-15 (54 days away)
**Paper Trading:** Day 2 of 56 (started 2026-05-20)

---

## Executive Summary

SPA is a well-structured DeFi paper trading system with a solid two-layer architecture (deterministic risk layer + LLM advisory layer). The core paper trading engine, risk policy, and data pipeline are functionally complete. However, a thorough code review reveals **4 critical bugs that directly block go-live**, **7 logic issues that produce incorrect financial data or misleading metrics**, and **4 missing features** required before real capital can be deployed safely. The most severe issue: the go-live activation script (`activate.py`) will **never succeed in its current form** because `check_wallet_ready()` always returns PENDING, and the activator requires ALL 11 criteria to be PASS. This bug must be fixed before July 15 is achievable. The current APY gap (4.2% vs 7.3% target) is the largest business risk — Pendle PT integration is expected to close it but is unproven at scale.

---

## Go-Live Readiness: 6/10

The deterministic risk layer (policy.py) is solid and correctly enforces concentration limits, cash buffers, and kill switch logic. The paper trading engine is functionally correct. The primary blockers are: (1) the activation script permanent bug, (2) the CI workflow not fetching fresh data, (3) inconsistent go-live thresholds vs documented requirements, and (4) the APY gap still to be closed by Pendle. Six weeks of paper trading data accumulation is needed regardless — so fixing the code bugs in Week 1 costs nothing on the critical path.

---

## Critical Issues Found (must fix before go-live)

### CRIT-1: activate.py will NEVER succeed — permanent go-live blocker
**File:** `spa_core/golive/activate.py` line 101

```python
all_pass = all(c["status"] == "PASS" for c in criteria)
```

`check_wallet_ready()` is hardcoded to return `PENDING` (cannot auto-verify). Since `PENDING != "PASS"`, the activation script is permanently blocked. The go-live checklist's `_compute_verdict()` correctly excludes Wallet Ready from verdict evaluation (it's in `SETUP_CRITERIA`), but `activate.py` includes it in `all_pass`. **This means real-capital deployment can never be unlocked via `activate.py` in its current state.**

Fix: either mirror the checklist's SETUP_CRITERIA exclusion in `activate.py`, or add a `SPA_WALLET_CONFIRMED=1` env-var / sentinel-file that makes `check_wallet_ready()` return PASS after manual owner confirmation.

**KANBAN:** SPA-B001, SPA-F003 — Priority HIGH, Sprint v1.7

---

### CRIT-2: GitHub Actions workflow never fetches fresh APY data
**File:** `.github/workflows/spa-run.yml` line 43

```yaml
run: python spa_core/export_data.py
```

The `--fetch` flag is missing. Without it, `run_export(fetch=False)` only reads from whatever APY snapshots are already in SQLite and never calls the DeFiLlama API. Since there is no standalone data daemon running in GHA, **APY data in the database is never updated by the scheduled workflow**. Paper trading positions use stale APY rates; the `check_data_freshness` criterion will FAIL; and weighted APY calculations in Telegram reports will be wrong.

Fix: `python spa_core/export_data.py --fetch`

**KANBAN:** SPA-B002 — Priority HIGH, Sprint v1.7

---

### CRIT-3: MIN_PAPER_DAYS = 50, not 56 — go-live eligible 6 days early
**File:** `spa_core/golive/checklist.py` line 39

```python
MIN_PAPER_DAYS = 50    # minimum days of paper trading required
```

DEV_STRATEGY_v1.0.md specifies "8+ weeks" = 56 days minimum. `engine.py` uses `MIN_PAPER_WEEKS = 8`. `KANBAN.json` SPA-016 also says "paper duration ≥56d". The checklist would signal PASS on Jul 9 instead of Jul 15. While 6 days is minor, it creates a paper trail inconsistency: the automated check contradicts every other documented requirement.

Fix: change `MIN_PAPER_DAYS = 56` in `checklist.py`.

**KANBAN:** SPA-B003 — Priority HIGH, Sprint v1.7

---

### CRIT-4: Sharpe threshold discrepancy — checklist ≥1.0 vs DEV_STRATEGY requirement ≥2.0
**File:** `spa_core/golive/checklist.py` lines 182–198, `check_strategy_performance()`

The automated checker marks PASS when `sharpe >= 1.0`. DEV_STRATEGY v1.0 requires `Sharpe ≥ 2.0` for go-live. This allows the system to declare READY at half the documented Sharpe requirement. The go-live decision is advisory (owner decides), but a misleading green-light from the automated checker creates false confidence.

Fix: raise PASS threshold to `2.0`, WARN range `1.0–2.0`, FAIL `< 1.0`.

**KANBAN:** SPA-B004 — Priority HIGH, Sprint v1.7

---

## Logic Issues Found

### LOGIC-1: Dual whitelist in defillama_fetcher.py — different protocols fetched vs stored vs exported

`WHITELIST` (15 pools, with pool_ids, used by `collect_once()` / `fetch_all()` → SQLite) differs from `POOL_WHITELIST` (12 pools, used by `DeFiLlamaFetcher.fetch_pools()` → dashboard export). The old whitelist includes Spark, Sky sUSDS, Fluid, and Ethena; the new whitelist includes Compound Arbitrum and Morpho Base. APY data written to the database does not match what the dashboard queries. This means protocol APY displayed in the dashboard may not match what the trading engine uses for decisions.

**KANBAN:** SPA-B005 — Priority HIGH, Sprint v1.7

---

### LOGIC-2: export_data.py APY tracker import fails silently

`export_data.py` line ~295: `from spa_core.analytics.apy_tracker import APYTracker`. The correct import (given `sys.path.insert(0, spa_core_dir)` at the top) is `from analytics.apy_tracker import APYTracker`. The `spa_core.` prefix causes `ImportError` unless the repo root is on `sys.path`. This section is wrapped in `try/except` so it silently fails — the 90-day rolling APY tracker never runs, meaning trend analysis and APY anomaly detection based on history are inoperative.

**KANBAN:** SPA-B006 — Priority MEDIUM, Sprint v1.7

---

### LOGIC-3: daily_report.py max drawdown displays as fraction, not percent

`alerts/daily_report.py` lines 176–177: fallback `max_dd = portfolio.get('total_drawdown_pct') or 0.0`. `status.json` stores `total_drawdown_pct` as a decimal (0.012 = 1.2%). Line 222 formats `{max_dd:.1f}%` without ×100, so 1.2% drawdown displays as "MaxDD: 0.0%" in the Telegram daily digest. Triggers when `advanced_analytics.json` is unavailable (e.g., first few days of paper trading).

**KANBAN:** SPA-B007 — Priority MEDIUM, Sprint v1.7

---

### LOGIC-4: check_diversification() uses deployed capital as denominator, not total capital

`checklist.py check_diversification()`: concentration is `amt / total_deployed`. RiskPolicy uses `amt / total_capital_usd` (including cash). When the portfolio is mostly cash (early paper trading, Day 2–14), the go-live checker shows 100% concentration on a single protocol even if it's only 30% of total capital. This would trigger a FAIL on the diversification criterion and could create confusion when the system is actually operating within risk limits.

**KANBAN:** SPA-B008 — Priority MEDIUM, Sprint v1.7

---

### LOGIC-5: check_drawdown_acceptable() FAIL threshold (4%) inconsistent with kill switch (5%)

`checklist.py` fails go-live at drawdown >4%, but `RiskPolicy.max_drawdown_stop = 5%`. DEV_STRATEGY requires ≤5%. A portfolio at 4.5% drawdown is: (a) within RiskPolicy — still running, (b) under DEV_STRATEGY go-live requirement, but (c) would FAIL the automated go-live checker. Creates inconsistency between running state and go-live eligibility.

**KANBAN:** SPA-B009 — Priority MEDIUM, Sprint v1.7

---

### LOGIC-6: _update_strategy_state() reads DB inside open write transaction — stale state

`engine.py _update_strategy_state(conn)` calls `self._load_portfolio_state()` which opens a second DB connection. This happens while the caller holds an uncommitted write transaction (e.g., INSERT paper_trade). The inner read may see pre-INSERT state in WAL mode. The Sharpe ratio stored in `strategy_state` lags by one trade cycle, which could affect monitoring dashboards.

**KANBAN:** SPA-B011 — Priority MEDIUM, Sprint v1.7

---

### LOGIC-7: auto_allocate_v2() L2 chain set includes Optimism+Polygon; RiskPolicy enforces Arbitrum+Base only

`engine.py` line 560: `_V2_L2_CHAINS = {"arbitrum", "base", "optimism", "polygon"}`. `RiskPolicy.l2_allocation_pct()` only counts `{"arbitrum", "base"}`. If Optimism or Polygon pools were added to the whitelist, v2_aggressive would apply an L2 cap that RiskPolicy doesn't enforce, creating an untested code path. Low risk today (no Optimism/Polygon pools in whitelist) but a latent inconsistency.

**KANBAN:** SPA-B010 — Priority LOW

---

## Missing Pieces

### MISSING-1: No agent stability tracking — go-live criterion absent
DEV_STRATEGY go-live requirement: "All agents stable ≥4 weeks." The 11-criterion checklist has no criterion for agent stability. There is no code to record when agents first became stable, track restart events, or verify 28-day continuous operation. This criterion cannot be evaluated automatically. Must be added as Criterion 12 before go-live, otherwise the checklist is incomplete relative to stated requirements.

**KANBAN:** SPA-F001 — Priority HIGH, Sprint v1.7

---

### MISSING-2: CI pytest excludes top-level tests/ directory (~40 tests)
`spa-run.yml` line 31: `python -m pytest spa_core/tests/ -q`. The top-level `tests/` directory contains `test_retry_logic.py`, `test_concurrent_fetch.py`, `test_rebalancing.py`, `test_integration_e2e.py`, `test_apy_tracker.py`, `test_dev_agents.py` and others (linked to SPA-B002 and the retry/caching sprint work). These tests never run in CI, so retry logic, concurrent fetch, and integration regressions go undetected.

**KANBAN:** SPA-F002 — Priority HIGH, Sprint v1.7

---

### MISSING-3: Wallet Ready criterion needs a manual-approval mechanism
`check_wallet_ready()` is permanently PENDING. For the go-live activator to work (after fixing CRIT-1), there needs to be a code path where the owner signals completion of the manual wallet setup. Current approach: owner creates `data/wallet_confirmed.sentinel` file, `check_wallet_ready()` checks for it, returns PASS if present with a note "Owner manually confirmed." This maintains security (manual step required, git-ignored file) while allowing the automation to proceed.

**KANBAN:** SPA-F003 — Priority HIGH, Sprint v1.7

---

### MISSING-4: Sky T1 promotion has no automated trigger or owner notification
`sky_monitor.py` checks the GSM Pause Delay but does not trigger any automated action when ≥48h is confirmed. No Telegram alert, no data/ sentinel, no whitelist update. Owner would not know the upgrade condition was met unless they read logs. A complete implementation would write a `data/sky_upgrade_pending.json` file and send a Telegram alert when the condition is met.

**KANBAN:** SPA-F004 — Priority MEDIUM

---

## Tech Debt (post go-live acceptable)

**DEBT-1 (SPA-D001):** Dead code — `avg_days` variable in `close_position()` (engine.py line 225). Computed but never returned or used. Formula is also mathematically meaningless.

**DEBT-2 (SPA-D002):** Redundant check #7 in `check_new_position()`. For T1 protocols, `max_concentration_t1 == max_single_protocol == 40%` — check #7 can never fire without check #6. For T2, max_conc is 20% so #7 (at 40%) is unreachable. Dead code.

**DEBT-3 (SPA-D003):** Tests split across two directories (`spa_core/tests/` and `tests/`). Created during v1.6 but never consolidated. CI only covers half the test suite (linked to MISSING-2).

**DEBT-4 (SPA-D004):** `collect_once()` / `fetch_all()` use the old 15-pool `WHITELIST` module-level dict. The class-based interface uses the newer 12-pool `POOL_WHITELIST`. The SQLite ingestion path (called every export cycle) writes data for different protocols than what the dashboard queries. Should be unified after SPA-B005 resolution.

---

## 7-Week Roadmap to Go-Live (2026-05-22 → 2026-07-15)

### Week 1 — May 22–29: Fix critical bugs (all 4 before anything else)
**What must be done:**
- Fix activate.py permanent blocker (SPA-B001)
- Add `--fetch` to GHA workflow (SPA-B002)
- Set MIN_PAPER_DAYS=56 (SPA-B003)
- Raise Sharpe threshold to 2.0 (SPA-B004)
- Fix APY tracker import (SPA-B006)
- Fix daily_report max_dd display (SPA-B007)
- Fix CI pytest to include `tests/` (SPA-F002)
- Add agent stability tracking criterion (SPA-F001)
- Add wallet-confirmed sentinel mechanism (SPA-F003)

**Risk:** If workflow remains without `--fetch`, paper trading data is permanently stale. This is the single highest-priority fix.

**Success criteria:** All 4 critical bugs fixed, CI passes with both test directories, daily Telegram digest shows correct metrics, checklist shows correct thresholds.

---

### Week 2 — Jun 1–7: Data accumulation + whitelist unification
**What must be done:**
- Unify WHITELIST/POOL_WHITELIST into a single source of truth (SPA-B005)
- Resolve `collect_once()` / `fetch_all()` legacy path (SPA-D004)
- Verify DeFiLlama data is flowing into SQLite correctly after `--fetch` fix
- Monitor Pendle PT pool quality — confirm pools passing 7 gates
- Day 12–18: First meaningful PnL should appear

**Risk:** If DeFiLlama pool IDs have changed since last verification (2026-05-21), fetcher returns 0 pools and paper trading runs on stale data.

**Success criteria:** 12+ pools fetched per cycle, SQLite and export are consistent, Pendle PT ≥1 pool qualifying.

---

### Week 3 — Jun 8–14: Strategy validation + first Sharpe check
**What must be done:**
- Day 19–25 of paper trading
- First meaningful Sharpe ratio calculation (need ≥14 days of APY data)
- Run strategy tournament: v1_passive vs v2_aggressive
- Fix check_diversification() denominator (SPA-B008)
- Fix check_drawdown_acceptable() threshold alignment (SPA-B009)
- Agent stability clock starts (target: stable by Jul 6)

**Risk:** Current APY ~4.2% is below the 5% risk-free rate proxy, so strategy_state Sharpe will be negative. The *backtest* Sharpe (used by checklist) is separate — based on synthetic/historical DeFiLlama data — but real live Sharpe will look poor in dashboard.

**Success criteria:** Tournament runs without errors, diversification and drawdown criteria show correct values, backtest Sharpe >1.5.

---

### Week 4 — Jun 15–21: APY gap tracking + pre-go-live prep
**What must be done:**
- Day 26–32 of paper trading
- APY gap tracker: Pendle PT expected to push weighted APY from 4.2% toward 6%+
- Sky GSM Pause Delay check — if condition met, trigger upgrade (SPA-F004)
- Begin Gnosis Safe setup (manual; needed for Wallet Ready PASS)
- Review whether v2_aggressive should run concurrently to compare strategies

**Risk:** APY gap remains >2pp (3.1pp currently). If Pendle pools are not qualifying or APY is lower than expected, the APY Gap criterion will FAIL at go-live.

**Success criteria:** Weighted APY >5.5%, APY Gap criterion WARN or better, Gnosis Safe creation started.

---

### Week 5 — Jun 22–28: Pre-go-live hardening
**What must be done:**
- Day 33–39 of paper trading
- Complete Gnosis Safe + hot wallet setup (docs/v2_activation_checklist.md Section B)
- Create `data/wallet_confirmed.sentinel` → Wallet Ready criterion becomes PASS
- Owner ADR sign-off (review checklist.py, policy.py, activate.py)
- PostgreSQL migration planning (FEAT-002 / BL-008)
- Security audit: API key rotation, confirm private keys not in git

**Risk:** Wallet setup takes longer than expected. Gnosis Safe multi-sig ceremony requires careful execution.

**Success criteria:** Wallet Ready PASS confirmed, `data/wallet_confirmed.sentinel` exists, all 11 criteria evaluated at least once as PASS or WARN (no FAIL).

---

### Week 6 — Jun 29–Jul 5: Final testing + dry run
**What must be done:**
- Day 40–46 of paper trading
- Dry run: execute `python -m spa_core.golive.activate` with test data dir and verify all 11 criteria show PASS
- Verify Telegram alerts are flowing correctly
- Run full test suite: `pytest spa_core/tests/ tests/ -v` — 140+ tests must pass
- Review ADR-001 and ADR-002 for any outdated sections
- Agent stability: Day 28 milestone = agents stable since Jun 7 qualifies

**Risk:** Any criterion still FAIL on Jul 1 leaves only 14 days to remediate.

**Success criteria:** Dry run `activate.py` outputs "All criteria PASS", agent stability ≥28 days, all tests green.

---

### Week 7 — Jul 7–15: Go-Live decision
**What must be done:**
- Day 47–56 of paper trading
- Jul 9: Paper Duration criterion passes (Day 50 if not fixed; Day 56 if SPA-B003 is fixed)
- Final checklist review with owner (Yurii)
- Owner signs off on ADR
- Jul 15: Run `python -m spa_core.golive.activate` with real data dir
- Type `I CONFIRM LIVE TRADING`

**Risk (MEDIUM):** Sharpe ≥2.0 may not be achievable in 56 days with current ~4.2% APY. The backtest Sharpe (used by the checker) is based on historical DeFiLlama data, not live paper trading performance. If Pendle closes the APY gap, live Sharpe improves but the checker reads backtest Sharpe.

**Risk (HIGH):** APY gap may not close sufficiently. If current APY stays at 4.2% (3.1pp below target) through Jul 15, the APY Gap criterion will FAIL.

**Success criteria:** All 11 criteria PASS or at most 1 WARN, owner reviews and approves, activation record written to `data/activation_record.json`.

---

## Immediate Next Sprint (Week 1, May 22–29)

These 5 tasks should be done immediately, in order of risk reduction:

**1. Fix GHA workflow: add `--fetch` flag** (SPA-B002, 0.2h)
Highest business impact. Without this, no new APY data ever enters the system via CI. One-line change.

**2. Fix activate.py: exclude Wallet Ready from all_pass check** (SPA-B001, 1h)
Removes the permanent go-live blocker. Change `all_pass` to exclude SETUP_CRITERIA, consistent with how `_compute_verdict()` works.

**3. Fix MIN_PAPER_DAYS=56 + Sharpe threshold=2.0** (SPA-B003+SPA-B004, 1h combined)
Two one-line changes that align the automated checker with documented requirements. Important for credibility of the automated go-live report.

**4. Fix daily_report.py max_dd fallback** (SPA-B007, 0.3h)
The Telegram daily digest is the primary monitoring tool. Incorrect drawdown display undermines trust in the reports.

**5. Add agent stability tracking skeleton** (SPA-F001, 4h)
Must start the stability clock NOW. If agent stability requires 28 days, starting Jun 1 means the criterion passes Jun 29 — 16 days before go-live. Starting May 22 means it passes Jun 19 — buffer included. If delayed, this becomes a go-live blocker.

**Total estimated time: ~6.5h**

---

## Architecture Assessment

The **two-layer architecture** (deterministic risk layer + LLM advisory layer) is architecturally sound and correctly implemented:

- `RiskPolicy` is pure Python, deterministic, never touched by agents. The `LLM_FORBIDDEN_AGENTS` set in `model_config.py` and the `approved=False` cannot-be-overridden contract are correctly enforced.
- The `DecisionLogger` provides a complete audit trail for every agent decision.
- The `MessageBus` (SQLite-backed pub/sub) is appropriate for paper trading scale; Redis migration is correctly deferred to go-live.
- The go-live gating mechanism (`activate.py` + `activation_record.json`) is a strong safety design — the wallet remains in PAPER mode until an explicit file is written.

**Structural concerns:**
1. The dual-whitelist in `defillama_fetcher.py` is the most significant architectural inconsistency. The module evolved from a script (`WHITELIST`) to a class (`POOL_WHITELIST`) without removing the old path. The SQLite ingestion path still uses the old whitelist.
2. The paper trading Sharpe stored in `strategy_state` (from `_update_strategy_state`) is a *cross-sectional* Sharpe (standard deviation of APY across current positions), which is not the same as the *time-series* Sharpe (standard deviation of daily returns over time) used in the backtest. The dashboard may show these interchangeably, confusing go-live evaluation.
3. The `tests/` top-level directory was created as an overflow but is invisible to CI. This is a testing infrastructure gap.

**Overall:** The architecture is clean and fit for purpose at paper trading scale. The risk governance approach is the strongest aspect of the design — the kill-switch, concentration limits, and policy versioning are production-grade.

---

## Confidence in Go-Live on 2026-07-15

**Overall Confidence: MEDIUM**

**What gives confidence:**
- Core paper trading engine, risk policy, and data pipeline are all functionally correct
- Test suite has 140+ tests with good coverage of critical paths
- Deterministic risk layer cannot be overridden by agents — this is the most important safety property
- All 4 critical bugs are 1–4 hour fixes that can be deployed in Week 1
- Architecture is sound and has no fundamental redesign risks

**What reduces confidence:**
- APY gap is 3.1 percentage points (4.2% actual vs 7.3% target). If Pendle PT doesn't close this gap, the `check_apy_gap` criterion will FAIL at go-live — and this is the *primary investment thesis* for the system
- Agent stability requires 28 days continuous — starting from scratch today, the earliest this can pass is Jun 19. Any agent crash resets the clock
- The Sharpe ≥2.0 requirement is ambitious for a system running at 4.2% APY in a 5%-risk-free-rate environment. Live Sharpe may be negative even if paper trading "works"
- Wallet setup (Gnosis Safe + hot wallet) is a manual task with no automated verification — human bottleneck
- Paper trading is only Day 2 of 56 — there are 54 more days of accumulation risk

**Bottom line:** July 15 is achievable if (a) the critical bugs are fixed this week, (b) Pendle PT delivers ≥6% weighted APY by Week 4, and (c) no significant drawdown events occur. The most likely reason go-live slips is the APY gap, not the code issues — all code issues are fixable in Week 1.

---

*Generated by SPA Architect Agent — 2026-05-22*
*All findings reference actual code read during this review session. No assumptions were made.*
