# A1 · CAPITAL → Indicator & Directional Trading Lab + BTC research — forensic findings

Epic RM-TRUTH-01, Phase 1 (read-only). Auditor run: 2026-10-05 ~10:10–10:20 CEST.
Sources: code/docs/ADRs from `~/Documents/SPA_mirror` @ `b36acda46` (2026-10-05 04:00 +0200);
live state from `~/Documents/SPA_Claude/data/trading_research/*`, `/tmp/spa_trading_research.log`,
`launchctl list`, `~/Documents/earn-defi/data/earn_defi.db`, `~/Documents/Claude/Projects/LOGOS/logos-desk/data/*`.
All SQLite reads used `sqlite3 -readonly`. Nothing in the prod tree, the mirror or any other repo was modified.
(The memory assembler was run with `SPA_MEMORY_INDEX` pointed at this scratchpad, so its index was built here and not in the prod tree.)

Outcome labels: **MEASURED** · **MEASURED-ZERO** · **NOT MEASURED** · **UNKNOWN**.

---

## 0. Headline (one screen)

1. **There have been three BTC engines, plus one more trading engine outside every repo.** None of them overwrote another's evidence.
   - (a) **research/btc_cycle**: an owner-supplied, external MVRV-cycle "ladder" backtest (v0.1 champion, with v0.2 and v0.3 rejected). It was archived under ADR-102 (2026-08-20). The champion's files were **never delivered**: `backtest.py` v0.1, `btc_dataset.csv`, `m2.csv`, fetch logic (ADR-102 §"Работа неполна"; ADR-118 "Честная граница").
   - (b) **SPA `btc_nav`** (ADR-118, 2026-08-22): a stdlib bookkeeper and agent, built in full but **never installed**. `data/btc_paper_trading.json` and `data/btc_cycle/` do not exist (MEASURED-ZERO). ADR-525 §5 declares it superseded.
   - (c) **earn-defi BTC Signal Engine**: a separate repo, `~/Documents/earn-defi` (68 commits). Live paper on config v0.3 since **2026-09-02**, shadow on v0.4, v0.5 pinned and not active. It is in **system_mode=INCIDENT since 2026-09-19** after a false KC-1 caused by an open Coinbase candle. The candle bug is fixed (`21c125e`, 2026-09-30); the incident is still not lifted, and lifting it is an owner action.
   - (d) **SPA Trading Research Engine v0** (ADR-525, 2026-09-30): an indicator lab with 138 BTC candidates. It is **running now**.
   - Outside every repo: **LOGOS desk**, a Polymarket "semantic arb" paper engine. It is not git-tracked and is alive under launchd, but has been a zombie since 2026-07-29 (see §6).
2. **Trading Research Engine forward paper is RUNNING and healthy (MEASURED):**
   - `launchctl list` shows `- 0 com.spa.trading_research`.
   - 428 ticks from 2026-09-30 21:22:52Z to 2026-10-05 08:04:07Z, all with ok=1. The log has 428 `START` lines and no non-zero `EXIT`.
   - No gap between ticks was longer than 20 min (MEASURED-ZERO). `late=0` and `gap_bars=0` across all 6,256 observations.
   - Evidence chain: `status.json` reports `evidence_verified: true`, `evidence_breaks: []`.
   - Last observation: bar closing **2026-10-05 08:00Z**, written by the tick at 08:04:07Z.
3. **No forward clock reset and no deleted history (MEASURED):**
   - All 138 candidates share one registration time, 1790803372716 = 2026-09-30 21:22:52Z.
   - Append-only triggers are present on every table.
   - The two stray copies in `/private/tmp/spa_c771_*` are exact **prefixes** of the live ledger: the hash at their max seq equals the live hash at that seq. They are not forks.
   - `evidence.db` is in the daily backup (`scripts/daily_backup.py:71`). It is present in `data/backups/spa_state_2026-10-01…05.tar.gz`.
4. **Qualification:**
   - 5/138 candidates are `BACKTEST_QUALIFIED → FORWARD_PAPER` and 133 are `REJECTED`. All 5 are spot long-only trend/breakout candidates.
   - **0 perp candidates qualified.**
   - Top rejection reason: `q_drawdown` (full-history MDD worse than −55%) in 122/133 rejections.
5. **No champion exists.** CHAMPION_CANDIDATE and SHADOW need a recorded owner decision, and there are **0 such events**. ROBUST needs ≥30 forward days and ≥5 forward trades. The forward candidates have **0 closed trades** so far. The earliest possible ROBUST date is about 2026-10-31.
6. **Multi-asset support exists in architecture only.**
   - `ASSETS = {"BTC": "BTCUSDT"}` (`strategies.py:186`, "ETH/SOL are one line").
   - `1W` exists in `TF_MS` but not in `TIMEFRAMES_V0 = ("1h","4h","1D")`.
   - Equities and options are `ARCHITECTURE_ONLY` (ADR-560 lines 28, 94–96).
   - Gold appears only as a research adapter with an 8.0% fake fallback APY (`spa_core/adapters/gold_proxy_research.py`).
   - Macro regime exists only in earn-defi (M2 via FRED). SPA's `regime.py` is BTC-price-only.
7. **I found no repo or file holding "original owner indicator experiments"** (parameter sweeps, TradingView/Pine, gold/equity tests) anywhere I searched (see §7). This is **UNKNOWN**, not "never existed". If they existed, they likely lived in chat.

---

## 1. Lineage: OWNER INTENT → IDEA → DECISION → TASK → IMPLEMENTATION → TEST → PAPER → OUTCOME → STATE

### 1.1 Line A — BTC cycle ladder (research/btc_cycle → btc_nav)

| Step | Evidence |
|---|---|
| Owner intent | The owner brought an external backtest of a BTC "ladder" by cycle phase (ADR-102 "Что случилось"; card `nimbalyst-local/tracker/own-btc-dvizhok-ne-vlezaet-pod-stop-kran.md`, created 2026-08-20) |
| Idea / design | `docs/15_btc_cycle_framework.md`, `docs/36_btc_capital_cycle_machine.md` (L2, "requires verification"), added in `fa6764a34` (2026-07-02 yield-lab merge) |
| Decision 1 | **ADR-102** (2026-08-20, commit `25bb205af`, titled "ADR-101" in the commit message, so it was renumbered). v0.1 champion accepted *as a measurement*. Build NOT started because the engine's DD of −33…−37% does not fit under the −5/−10% kill-switch. Numbers quoted: k=1.0 → 36.1%/−43.4%; k=0.8 → 29.1%/−36.5%; k=0.7 → 25.8%/−32.6% |
| Owner answer | Card `own-btc-…` `owner_choice: 1` (separate NAV), answered 2026-08-22T09:15Z via Telegram |
| Decision 2 | **ADR-118** (2026-08-22, `966d98ef4`): separate paper-NAV, producer `research/btc_cycle/daily_signal.py` plus bookkeeper `spa_core/paper_trading/btc_nav.py`, agent `com.spa.btc_nav` (calendar 08:40), $25,000 virtual USDT |
| Test | `spa_core/tests/test_btc_nav_paper.py` (10 tests per ADR-118) |
| Paper | **Never started.** The plist is not in `~/Library/LaunchAgents` and not in `launchctl list`. `data/btc_paper_trading.json` and `data/btc_cycle/` are absent (MEASURED-ZERO). Blocker: the champion v0.1 files were never handed over ("NO_ENGINE") |
| Outcome | Superseded by ADR-525 §5 ("SPA `btc_nav` is superseded (left in place, not installed)") |
| Current state | Code is in place. `architecture/manifest.json:302` still lists `com.spa.btc_nav` with `intent: "designed"`, **not** "superseded". This is a small documentation drift |

### 1.2 Line B — earn-defi BTC Signal Engine (separate repo)

| Step | Evidence |
|---|---|
| Owner intent | Package "earn-defi v1.0" (ADR-260 context). Owner decision D-01 (2026-09-04): a separate repo, not inside SPA (`earn-defi/docs/DECISIONS.md:7`) |
| Implementation | `~/Documents/earn-defi`: 68 commits, scaffold `3509555` 2026-09-04 01:38. Versioned configs `config/btc_engine_v0.1…v0.5.json`; `active.json` = `{"btc_engine":"0.3","btc_engine_shadow":"0.4"}` |
| Paper | `system_state.paper_start_date = 2026-09-02`. `nav_daily` has 32 rows (ids 1–32, dates 2026-09-02…2026-10-03, contiguous, `backfilled=0` for all). Row 1 is v0.1, row 2 is v0.2, rows 3–32 are v0.3. Start capital is 100,000 USDT. Last row: NAV 106,516.33, cum_return +6.52%, max_drawdown −4.73%, n_trades 1, BTC weight 0.696 |
| Read API in SPA | **ADR-260** (2026-09-08): `spa_core/api/routers/btc_engine.py` (pass-through of `~/Documents/earn-defi/site`). Whether it is live at the API was NOT MEASURED in this pass |
| Incident | `incidents` id 2, 2026-09-19T10:10:01Z: KC-1 "NAV at coinbase close 100,681.99 vs stored 103,182.82 (2.424% > 2.0%)", state **OPEN**. `system_state.system_mode=INCIDENT` (updated 2026-09-19T10:10:03Z). Alerts on every run: "system mode INCIDENT — new positions forbidden, reductions only" (alerts 80, 82). Root cause fixed in `21c125e` (2026-09-30) |
| Other | Fire drill 2026-10-01 is **FAIL 5/6** (incident 3). `launchctl` last exit codes: daily=2, monitor=2, drill=2, realized-cap=3. The daily job still writes NAV (run_log 10119 `run_daily OK`). Shadow verification has said "UNVERIFIED: no secondary observation" every day (alerts 81, 83) |
| Current state | Running, in INCIDENT mode, and the paper track continues. The `own-btc` card answer (choice 1, "separate NAV") is in practice fulfilled by **this** engine, not by `btc_nav` |

### 1.3 Line C — Trading Research Engine v0 (the indicator lab)

| Step | Evidence |
|---|---|
| Owner intent | "Owner directive «CAPITAL ARCHITECTURE v1 + TRADING RESEARCH ENGINE v0», autonomous execution authorised in it" (ADR-525 header, 2026-09-30). **The verbatim directive text is not in any file I found** (`docs/OWNER_BACKLOG_*` stops at 2026-07-16; `docs/ideas` has no match). The source is **UNKNOWN** and was probably chat; the ADR records the decision, not the original wording |
| Pre-audit | ADR-525 Context: "SPA had **no directional price-trading engine**: every MA/momentum in `spa_core` runs on APY/TVL" |
| Decision | **ADR-525** (ACCEPTED 2026-09-30); `docs/TRADING_RESEARCH_ENGINE.md`; `docs/CAPITAL_ARCHITECTURE.md` |
| Implementation | `spa_core/trading_research/` (1,753 LOC, 13 modules). Commit `a7cc24059` 2026-09-30 23:13 +0200, plus fix `5e47491ad` 23:35 (honour `SPA_DATA_DIR` so the deploy gate's sandbox cannot write live evidence). Prod and mirror copies are identical (`diff -r` shows SAME) |
| Test | `spa_core/tests/test_trading_research.py` has 20 top-level `def test_`; the journal says "25 + 2 in the Director report". Tests were not run in this pass (NOT MEASURED) |
| Paper | Agent `com.spa.trading_research`, StartInterval 900 s, RunAtLoad. First tick 2026-09-30 21:22:52Z registered 138 candidates and made 419 stage events, running backtests on 79,833 1h bars |
| Outcome so far | 5 FORWARD_PAPER, 133 REJECTED, 0 ROBUST, 0 champion |
| Current state | Running. Readers: Director report (`spa_core/studio_os/director_report.py:410`), Mission Control, `research_factory/scanners/trading_research.py` (ADR-560, OBSERVE_ONLY), `investment_cio` sleeve (`allocatable=False`, abstains: "observe-only: no mandate") |

### 1.4 Line D — earlier BTC/ETH sleeves in strategy_lab (carry, not indicators)

- `spa_core/strategy_lab/strategies/btc_neutral.py`, `btc_lending_sleeve.py`, `eth_lst_neutral.py`, `eth_lst_staking.py` (commit `2182ec871`/`2d2ee81ed`, 2026-06-25).
- `data/strategy_lab_promotion.json` (mtime 2026-06-25): all four are `REJECT — does not beat the RWA floor; net APY not positive (0.0%)`.
- `data/strategy_lab_backtest.json` (2026-06-26) shows equity_first = equity_last (0.0 or 100000.0). The "0.0%" therefore looks like **no data rather than a measured zero**: equity of 0.0 means the series never ran. This is an instance of the invariant #17 class (absent observation presented as zero), noted but not verified further.
- These are not directional indicator strategies. They belong to Market-Neutral/Basis, not to the Trading Lab.

### 1.5 Line E — gold / anti-crisis (research-only placeholders)

- `spa_core/adapters/gold_proxy_research.py` and `spa_core/strategies/s20_anticrisis_research.py` (both 2026-06-19, MP-1315).
- The anti-crisis strategy uses **placeholder APYs** (BTC pool 25%, gold 15%, etc.).
- The adapter declares `FALLBACK_APY_PCT = 8.0` on network error. That is a fake fallback, which contradicts `.claude/rules/adapters.md` ("Никаких fake-fallback'ов"). It is RESEARCH_ONLY and no money path reads it; I did not verify who reads it.

---

## 2. Trading Research Engine v0 — measured state

**Data (MEASURED, `status.json` and `backtest.json` manifest)**
- Binance BTCUSDT 1h, 79,930 bars, from 1502942400000 (2017-08-17) to the last bar close at 2026-10-05 08:00Z.
- 28 historical 1h gaps, reported and not filled. 7,745 funding points.
- `data_conflicts` table: 0 rows (MEASURED-ZERO).

**Universe and backtest method (from the code and the backtest manifest)**
- 10 families × grids × BTC × {1h,4h,1D} × {spot_long v2, perp_ls_1x v2} = **138**. Observations break down as 46 candidates per timeframe.
- IS < 2023-01-01 ≤ OOS. Costs ×0/1/2/3. Spot costs 10 bps fee + 5 bps slippage per side; perp costs 5 + 5 bps plus funding.

**Qualification gates** (`ranking.py` THRESHOLDS): OOS Sharpe ≥0.8, IS ≥0.4, OOS@3× ≥0.5, trades ≥15, MDD ≥−55%, beats B&H on Calmar or by 15 pp MDD, neighbour median ≥0.3.

**Rejection reasons over the 133 rejected** (lifecycle_events evidence): q_drawdown 122 · q_cost_3x 108 · q_oos_sharpe 107 · q_vs_benchmark 84 · q_neighbours 82 · q_is_sharpe 51 · q_trades 5.

The highest-OOS candidates were rejected **only** for drawdown:
- `ma_cross@v1:BTC:4h:spot_long:ee9caf0d52` (EMA 50/200): OOS Sharpe 1.433, full MDD −61.6%.
- `price_vs_ma@v1:BTC:1D:spot_long:024a229345` (n=50): OOS 1.456, MDD −65.1%.
- `momentum@v1:BTC:1D:spot_long:330fada8c9` (n=72): OOS 1.159, MDD −71.2%.

That makes −55% MDD the binding gate.

**Forward-paper shortlist** (`backtest.json` regenerated 2026-10-04 22:01Z; forward data from evidence.db as of 08:04Z on 10-05):

| Candidate | params | IS Sh | OOS Sh | OOS@3× | full MDD | trades | fwd obs | fwd closed trades | fwd equity | latest target |
|---|---|---|---|---|---|---|---|---|---|---|
| supertrend@v1:BTC:1D:spot_long:cb4ee7a5a5 | n10, mult 2.0 | 1.192 | 1.017 | 0.874 | −54.8% | 66 | 4 | 0 | 1.01794 | long |
| donchian@v1:BTC:4h:spot_long:8f4bfc1d5a | entry 55 / exit 20 | 1.000 | 1.173 | 0.854 | −54.9% | 123 | 26 | 0 | 1.00000 | flat |
| supertrend_and_ma@v1:BTC:1D:spot_long:2be6f365aa | n10, mult 3.0, MA200 | 0.889 | 0.864 | 0.778 | −45.2% | 31 | 4 | 0 | 1.01794 | long |
| donchian@v1:BTC:1D:spot_long:0facf75089 | entry 20 / exit 10 | 1.260 | 0.887 | 0.776 | −54.3% | 43 | 4 | 0 | 1.01794 | long |
| supertrend@v1:BTC:4h:spot_long:7a05f87bf7 | n20, mult 3.0 | 0.907 | 0.990 | 0.516 | −47.1% | 221 | 26 | 0 | 1.00715 | long |

The B&H benchmark full-history MDD is −83.2% on 1D (`status.json.benchmark`).

Three of the five qualified candidates have full-history MDD between −54.3% and −54.9%, just inside the −55% gate. This is a robustness concern: they are marginal.

**BTC latest signal across all 138 candidates** (last target per candidate, MEASURED):

| Timeframe | long | flat | short |
|---|---|---|---|
| 1D | 38 | 7 | 1 |
| 4h | 40 | 5 | 1 |
| 1h | 32 | 10 | 4 |

The forward shortlist is 4 long and 1 flat (donchian 4h). Across the 6,256 observations, 150 trades closed in total; for the forward-paper five, the closed-trade count is 0.

**Defects and observations (not repaired)**
- **D1: `status.json` overstates forward bars by 1.** `forward_bars` = 5 and 27 versus 4 and 26 real observations. `forward_metrics()` prepends a synthetic seed point (`eq=[1.0]+…`, `forward.py`, `forward_metrics`). The Director report and the research_factory scanner show the inflated count. It is minor, but it is a representation error.
- **D2: OOS and the forward period overlap.** `backtest.json` is refreshed daily over all data, so OOS (≥2023-01-01 → now) absorbs the forward bars. The ROBUST rule compares forward Sharpe with an OOS Sharpe that already contains them. The qualification-time scores survive only as `score` in lifecycle evidence; for example, supertrend 1D was 0.8648 on 30.09 and is 0.8738 now. `backtest.json` itself is overwritten and not versioned (`data/trading_research/backtest.json` is not in the daily backup, which covers `data/*.json` top level plus `trading_research/evidence.db`).
- **D3: `market.db` is not backed up.** It is the immutable candle store. It can be refetched from Binance, but a refetch can disagree, and the `data_ref` hashes in observations depend on it. This is a residual risk.
- **D4: The first three ticks ran pre-fix code.** Code version `d138baef7dbf5fbe` was used from 21:22:52Z to 21:31:33Z, before `5e47491ad` at 21:35Z. The candidates carry `code_version=d138…`. All observations carry `279cd91f…` because the first observation bar opened at 22:00Z. Ticks 2 and 3, 12 s apart at 21:31Z, look like manual or deploy-gate runs (UNKNOWN which). They wrote 0 observations, so there is no contamination.
- **D5: the CIO lists each forward candidate twice** in `unchecked_protocols`, once as `tier=UNKNOWN` and once as `no capital allocated`. This is cosmetic.

---

## 3. Duplicates and overlap

| Duplicate set | Nature | Verdict |
|---|---|---|
| research/btc_cycle v0.1–v0.3 vs earn-defi `btc_engine_v0.1–v0.5` | **Name collision**: both use "v0.x" for different things. Research v0.2/v0.3 are *rejected* rule variants; earn-defi v0.3 is the *live* config (kill-switch completion) | Different lineages. A reader can mistake "v0.3 rejected" for "v0.3 live". Record this in the register |
| SPA `btc_nav` (ADR-118) vs earn-defi paper NAV | Same owner intent (separate BTC NAV, card choice 1) built twice; only earn-defi runs | `btc_nav` SUPERSEDED (ADR-525 §5); manifest not updated |
| docs/15 + docs/36 vs earn-defi docs/02-btc-signal-engine.md | Two design corpora for one MVRV-cycle engine | SPA docs SUPERSEDED (crossrepo audit `docs/audits/defi_gap_2026-10-01/5_crossrepo_history.md:161`) |
| trading_research (indicators) vs earn-defi (on-chain cycle) | Different families, same asset (BTC), same Capital slot "Trading → Crypto Spot" | Complementary. No shared evidence and no shared ledger. A future CIO must not double-count BTC beta |
| ADR-102 file vs commit message "ADR-101" | Renumbered | Note only |

---

## 4. Lost and surviving histories

- **Surviving:**
  - The `trading_research/evidence.db` chain is complete since registration, with daily backups from 10-01 to 10-05.
  - earn-defi `nav_daily` (32 hash-chained rows), `shadow_runs` 31, `signals` 32, plus earn-defi's own backup job (run_log 10124 `backup OK … offsite=ok`).
- **Lost or never delivered:**
  - The research/btc_cycle champion v0.1 (`backtest.py`, datasets, M2 fetch). ADR-102 and ADR-118 explicitly call it "главная потеря". Only v0.2 and v0.3 (both rejected) are in `research/btc_cycle/`.
  - The daily `backtest.json` snapshots: overwritten each day, with only the scores kept in lifecycle events.
- **Frozen (not lost):** the strategy_lab BTC/ETH sleeve artifacts, untouched since 2026-06-25/26.
- **No reset events found:**
  - trading_research: one registration timestamp, a contiguous tick sequence 1..428 with no gap over 20 min, triggers present, and stray copies that are prefixes.
  - earn-defi: contiguous ids 1..32 and dates 09-02..10-03 with no backfill. The day-1 row for 2026-09-02 was written 2026-09-03T23:56Z, about 18 min after the repo scaffold commit. That is a late first write for the as-of day and is **not flagged backfilled**. I treat this as UNKNOWN: probably legitimate T+1 settlement, but the "paper since 09-02" start predates the repo's existence.

---

## 5. Is forward paper running? (operational drift check)

| Engine | Running now? | Last observation | Drift |
|---|---|---|---|
| trading_research | **YES** (launchd exit 0; tick every ~15 min) | bar close 2026-10-05 08:00Z; tick 08:04:07Z; status.json generated 08:04:07Z (within its 2 h SLO) | None found |
| earn-defi v0.3 paper | YES, in **INCIDENT** mode (reductions only) | nav_daily date 2026-10-03, written 2026-10-04T10:10:04Z. The next run is 12:10 local, which had not happened at audit time | Incident open for 16 days although the root cause is fixed. Fire drill failing. Shadow source unverified daily |
| earn-defi v0.4 shadow | YES (31 shadow_runs) | NOT MEASURED in detail | — |
| btc_nav | NO, never installed | — | Superseded; manifest says "designed" |
| LOGOS desk | Process alive (pids 1742 and 1695), scan_stats updated 2026-10-05 07:56Z | **last scan with markets>0: 2026-07-29T06:10:55Z** (5,291 scan rows). `paper_trades.jsonl` last written 2026-07-15 (289 rows). scanner.log is 117 MB and has 260,154 lines containing `WARNING` | **Zombie for about 68 days**: alive, consuming resources, measuring nothing |

---

## 6. LOGOS desk (found outside every repo — flagged, not in my slice's core)

- Location: `~/Documents/Claude/Projects/LOGOS/logos-desk` (no `.git`: `git log` gives 0).
- Purpose: "Engine E1 (semantic arb) (paper mode)" on Polymarket. Claude groups markets semantically and a deterministic validator turns findings into paper trades (README).
- Kill criteria: KILL / GO / GREY after 2 weeks of data (README).
- launchd: `com.logos.desk` (`scanner.run --loop`) and `com.logos.dashboard` (`http.server 8777 --bind …`). The bind target was not checked further.
- State: every scan since 2026-07-29 reports `markets: 0`, `universe_complete: false`, `verifier.mode: SKIPPED_DEGRADED`, and the log shows `gamma-api.polymarket.com … Max retries exceeded`.
- A prior audit mentions it: `docs/audits/defi_gap_2026-10-01/5_crossrepo_history.md:96-99`. It belongs under "Trading → Volatility/Options (not started)". `DERIBIT_PORT_ARCHITECTURE.md` (2026-07-30) is design only.
- Recommendation: the owner decides between KILL (per its own README criteria) and REPAIR. Do not touch it in Phase 1.

---

## 7. Multi-asset: existing vs planned-but-never-built

| Item | State | Evidence |
|---|---|---|
| BTC 1h/4h/1D, spot + 1× perp paper | **Built and running** | strategies.py:187, status.json |
| 2h/8h/12h/1W | Plumbing only (`TF_MS`); not registered | market_data.py:26-27; strategies.py:187 |
| ETH / SOL indicator candidates | Planned ("one line") and **never built** | strategies.py:186 |
| Equities / traditional markets | **ARCHITECTURE_ONLY** | CAPITAL_ARCHITECTURE.md:17; ADR-560:28,94 |
| Options | ARCHITECTURE_ONLY (LOGOS→Deribit is design only) | ADR-560:96; LOGOS/DERIBIT_PORT_ARCHITECTURE.md |
| Gold | Research adapter with a fake 8% fallback; placeholder APYs | gold_proxy_research.py; s20_anticrisis_research.py |
| Macro regime | earn-defi only (M2/FRED; signals.inputs.m2_obs_date = 2026-08-01, so M2 lags about 2 months). SPA regime.py covers BTC price/vol only | earn-defi signals payload; regime.py |
| Capital Allocator / Portfolio CIO across trading | Explicitly "not built now" (ADR-525 §1). The later `investment_cio` (ADR-554) reads trading_research as observe-only | contract.py:67 |

**Search for "original indicator experiments":**
- Grep over `~/Documents`, `~/Desktop`, `~/Downloads` for supertrend / donchian / BTCUSDT / tradingview / pinescript, excluding the SPA trees, found only SPA worktree copies and UI-chart mentions. I found no owner-made sweeps or Pine scripts.
- Git history: `git log --all -S supertrend` first appears at `a7cc24059` (ADR-525). `-S BTCUSDT` first appears in strategy_lab, 2026-06-25.
- **UNKNOWN whether owner-side indicator experiments predate ADR-525.** If they did, they were not saved to files.

---

## 8. Repair or resume that would be needed (NOT done)

1. **earn-defi INCIDENT** (owner action per earn-defi ADR-006): review KC-1 on 2026-09-18 against fix `21c125e` and lift or keep with a written reason. Investigate the failed fire drill (5/6, 2026-10-01) and the non-zero launchd exits (daily 2, monitor 2, drill 2, realized-cap 3).
2. **trading_research D1**: correct `forward_bars` to count real observations, or rename it. Tell readers (Director report, research_factory).
3. **trading_research D2**: freeze the OOS end at the forward registration time (2026-09-30) for the ROBUST comparison, or record that the overlap exists. Version or keep the daily `backtest.json` snapshots, or at least the qualification-time metrics. This is a methodology decision, so it needs an ADR.
4. **D3**: add `trading_research/market.db` to the backup, or document that it is refetchable and how conflicts would be handled.
5. **Manifest drift**: set `com.spa.btc_nav` from intent `designed` to superseded (ADR-525 §5).
6. **LOGOS**: owner decision KILL or REPAIR. It is a zombie loop with a 117 MB log.
7. **gold_proxy_research** fake fallback 8.0: fix it or mark the adapter retired (rule `adapters.md`).
8. **Naming**: add a glossary line so that research/btc_cycle "v0.3 (rejected)" is not confused with earn-defi "v0.3 (live)".

## 9. Open UNKNOWNs

- U1: The verbatim owner directive behind ADR-525 (it exists only as a quoted title).
- U2: Whether owner indicator or parameter-sweep experiments predate ADR-525 (nothing on disk).
- U3: Who ran ticks 2 and 3 (21:31:21Z and 21:31:33Z on 09-30): the deploy gate or a manual run.
- U4: Whether `api.earn-defi.com/api/btc-engine/*` is serving now (NOT MEASURED; apiserver is a long-lived process).
- U5: Whether the strategy_lab BTC/ETH "net APY 0.0%" was a measured zero or "not measured". The evidence points to not measured.
- U6: The earn-defi day-1 NAV row was written after the as-of date, without a backfill flag.
- U7: Readers of `gold_proxy_research` / `s20_anticrisis_research`.
- U8: The test count discrepancy (20 `def test_` versus the journal's "25 + 2"). Tests were not executed.
