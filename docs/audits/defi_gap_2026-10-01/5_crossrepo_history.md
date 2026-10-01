> **Working evidence (EPISODIC), not canon.** Notes of a read-only auditor, 2026-10-01; the canonical findings are
> `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md` (ADR-530), where every P0 and headline number was re-measured.

# Audit 5 — Cross-repo DeFi capability + historical spec inventory

Read-only audit, 2026-10-01. SPA paths are relative to `~/Documents/SPA_mirror` unless prefixed.
Repos: `ED` = `~/Documents/earn-defi`, `DC` = `~/Documents/Claude/Projects/DeFi Checkup`,
`SB` = `~/Documents/studio_bridge`, `SO` = `~/Documents/studio_os`, `MEM` = `~/Documents/earn-defi-studio-memory`.
Live HTTP checks were read-only GETs.

---

## (A) Capability per repository

### earn-defi (ED): BTC MVRV-cycle allocator. Not a DeFi yield engine.
- **What runs:** the BTC Signal Engine (MVRV percentile, realized price, trend gates, M2). It has a hash-chained ledger, commit-reveal, replay, runway and kill conditions (`ED/CLAUDE.md:5`; `ED/earn_defi/{signals,regime,hashchain,commit_reveal,replay,runway}.py`; `ED/earn_defi/risk/{gate,kill_switch,kill_conditions}.py`).
- **Execution:** a WhiteBIT CEX executor with a `DryRunExecutor` and a `LiveExecutor` that reads its key from the Keychain (`ED/earn_defi/execution/whitebit.py:43,81`). It does nothing on-chain. There is no wallet signing or approval logic.
- **Yield engines A, B, C and the RWA floor are SPEC ONLY.**
  - Spec: `ED/docs/03-yield-engines.md:19-43`. A = Pendle PT, B = spot/perp basis, C = stable LP or Morpho/Veda vaults, plus the RWA floor.
  - `ED/config/engines_v0.1.json:3-4`: "PROPOSED … not wired". Only `btc_engine: true`; engines A, B, C and `rwa_floor` are all `false`.
  - `ED/earn_defi/allocator.py:1`: "pure function, NOT wired".
- **The one DeFi touchpoint is the stable leg** (`ED/earn_defi/stable_leg.py:1-20`).
  - The engine's idle USDT is virtually placed in **SPA's Conservative book**.
  - The rate is read from `https://api.earn-defi.com/api/tier1/packages`, field `packages.conservative.blended_net_apy_pct` (`ED/config/stable_leg_v0.1.json:21-22`).
  - It keeps its own hash chain `stable_leg_daily`, separate from the engine's NAV and kill switches. A missing rate is recorded as `UNMEASURED`.
  - Whitelist v0.2 copies SPA's four venues (Aave V3, Compound V3, Fluid, Maple). Their evidence fields are still "requires verification" (`ED/config/whitelist_v0.2.json` changelog).
- **Live:**
  - Seven launchd jobs `com.earn-defi.*`: daily, monitor, monthly, runway, backup, drill, realized-cap.
  - `daily` and `monitor` exit **2**. `/tmp/earn-defi/monitor.log` reads "CRIT system.mode INCIDENT — new positions forbidden" (last entry 2026-09-30T20:40Z).
  - The INCIDENT has been open since 09-19, caused by the Coinbase open-candle bug. The bug is fixed in `21c125e`; lifting the INCIDENT is a manual owner action (`docs/decisions/ADR-525…md:17-20`).
  - Public pages: `earn-defi.com/btc-engine/` (HTTP 200) is published through SPA's landing (`ED/deploy/publish_static_pages.sh:2-23`). Its data comes from `api.earn-defi.com/api/btc-engine/*.json` (`ED/README.md:36-37`).
- **Relation to SPA:** complementary and separate. Canon files it under **Trading → Crypto Spot**, not DeFi (`docs/CAPITAL_ARCHITECTURE.md:25-27`). Engine C and the RWA floor would **duplicate** SPA's Conservative book and `rwa_backstop`, but they are unbuilt. The stable leg is a **consumer** of SPA's published rate.

### DeFi Checkup (DC): a read-only wallet risk diagnostic. Not deployed today.
- **Wired pipeline:** `POST /api/analyze` (`DC/apps/web/src/app/api/analyze/route.ts:18`, rate-limited at :20) calls `analyzeWallet` (`DC/apps/web/src/lib/analyze.ts:299`). The steps:
  1. Resolve the input: 0x address, ENS name or DeBank URL.
  2. Read balances over JSON-RPC on 5 chains (ETH, Base, ARB, OP, POLY).
  3. Price tokens via DefiLlama.
  4. Scan approvals and lending positions (:389-390).
  5. `assembleReport` (:440) builds the report.
- **Engine `DC/packages/riskdesk/src`** (TS), by area:
  - Inputs: `resolver`, `adapters/rpc`, `snapshot` (schema and sha256 hash).
  - Detectors: `approvals/scan.ts`, `leverage/detect.ts`, `bridge/detect.ts`, `tailrisk/detect.ts`.
  - Valuation: `exitnav/engine.ts` with `haircuts.v0.ts` (the haircuts are labelled hypotheses); `yield/quality.ts` and `estimated_apy.ts` give reference APY, not realised yield.
  - Calculators: concentration, stablecoin/depeg, wallet hygiene, gas readiness, idle vs deployed.
  - Policy and output: `policy/riskpolicy.v0_1.ts`, `refusal/*`, `score/riskscore.ts`, `proof/proof.ts`.
- **Approvals and phishing:**
  - Source: Etherscan V2 `getLogs` on the Approval topic, with Alchemy `eth_getLogs` as fallback (`DC/apps/web/src/lib/approvals.ts:24,229-322`). A failure returns `null` ("not scanned"), not zero (:212-214).
  - `KNOWN_SPENDERS_BY_CHAIN` (`approvals.ts:141`) holds ETH 17, Base 12, and ARB/OP/POLY 14 each (12 shared L2 entries + 2).
  - Classification is **binary known/unknown** (:403). The registries have **no 'flagged' entries** (:29), so the `to_flagged` bucket is always empty.
  - **There is NO malicious-spender or phishing detection.**
  - Unlimited means ≥2^255. Stale means older than 180 days (`riskdesk/src/approvals/scan.ts:23`).
  - Known weaknesses:
    - The current allowance is taken from the last Approval event, so allowance can be overstated.
    - Same-block events are not ordered by logIndex (:381).
    - Provenance is hardcoded to `etherscan-logs` even when Alchemy answered (:418).
  - Approvals were "dark in prod" without an Etherscan key (`DC/BACKLOG_ARCHITECT.md:25`, DC-1).
- **Signing:**
  - The main `/check` flow takes an address only, no wallet.
  - `/cabinet` does request signatures through injected `window.ethereum`:
    - SIWE sign-in: `components/WalletLogin.tsx:39`, `lib/siweClient.ts:47`.
    - **Revoke** `approve(spender,0)` via `eth_sendTransaction`: `components/RevokeApprovalButton.tsx:39,45`, built in `lib/revokeTx.ts:33`.
    - USDC subscription payment: `components/SubscribeButton.tsx:40,45`.
  - No server key. viem only, no wagmi or WalletConnect.
  - **Possible defect:** the revoke button never checks or switches the wallet's chain.
- **Leverage and health factor (HF):** `DC/apps/web/src/lib/lending.ts`, all via `eth_call`.
  - Aave V3 `getUserAccountData` on 5 chains (:26-32, HF = word 5 / 1e18).
  - Spark: Ethereum only (:34-35).
  - Compound V3: stable Comets only, `borrowBalanceOf`; collateral and HF are null (:40-60,134-151).
  - No Morpho, Fluid or Euler (DC-8).
  - Thresholds: HF < 1.2 → refusal; LTV > 0.65 → flag (`riskdesk/src/policy/riskpolicy.v0_1.ts:179,191`). Both are labelled hypotheses.
- **Position passport, exit plan, net APY, loss budget: NONE in DC.** The nearest pieces are the Exit-NAV range engine (`DC/docs/defi-checkup/08_EXIT_NAV_ENGINE.md`, `components/report/ExitNavRange.tsx`) and the per-section report cards.
- **Live status:**
  - `https://checkup.earn-defi.com/` returns **404**, and `/api/health` returns `{"code":404,"message":"Application not found"}` (Railway edge, measured 2026-10-01). DNS is a CNAME to `spaweb-production-2ee6.up.railway.app`.
  - SPA's own landing says the same: `landing/src/pages/index.astro:6-10` ("that service is gone … measured 2026-08-16"; `scripts/funnel_link_check.py` blocks links to it).
  - The repo has **uncommitted changes**: 15 modified files (+2159 lines) plus a staged `.husky/pre-commit`. Last commit `3dba8e0` (2026-07-15). There are 74 test files.
- **Relation to SPA:**
  - It was a **funnel**: CTAs to earn-defi.com `/packages`, `/methodology` and `/strategies` (`DC/apps/web/src/components/check/ReportDashboard.tsx:117-128`), plus analytics to `api.earn-defi.com/api/analytics/event` (`DC/apps/web/src/lib/track.ts:6`).
  - It reads no SPA data, and it **complements** SPA, which has no wallet scanner.
  - **Partial overlap:**
    - SPA `spa_core/execution/draft_prep.py:1-40` builds UNSIGNED de-risk drafts including `approve(spender,0)` (:77,137). It is CLI-only via `scripts/prepare_execution_draft.py`, with no launchd job.
    - SPA has HF analytics: `spa_core/analytics/collateral_ratio_monitor.py` is tier B in `_module_registry.py:49`, and `defi_leverage_safety_monitor` is tier C, written off (`_tier_c_writeoff.py:91`).

### Studio Bridge (SB): NO DeFi capability (by design)
- It is a planner→executor→review dev-cycle orchestrator (`SB/README.md:1-10`).
- DeFi-word hits in `SB/bridge/` are about owner approvals and the identity guard against an "Earn DeFi"-labelled SPA worktree (`SB/bridge/identity_guard.py:3-35`). No market, wallet or yield code.
- Live: launchd `com.studiobridge.coordinator` and `com.studiobridge.telegram` are running (status −15 = last exit by SIGTERM); `com.studiobridge.activation-engine` last exited 7. Release b19.6.33 (`architecture/memory_truth.json` facts[2]).

### Studio OS (SO) and Company Memory (MEM): NO DeFi capability (boundary decision)
- `MEM/decisions/owner/2026-08-27-studio-os-investment-engine-boundary.md:5-14`:
  - Studio OS holds no investment calculations, Strategy Cards, allocation rules or capital management.
  - SPA's investment part acts as the "Investment Engine".
  - STRAT-001 and STRAT-002 are removed from Studio OS.
- `SO/docs/PROJECT-BOUNDARIES.md:13-23`: SPA is outside scope and must not be modified.

### LOGOS: not DeFi
- Polymarket logical-arbitrage scanner with an LLM grouper and verifier (`LOGOS/logos-desk/scanner/*`).
- A design to port it to Deribit inverse options (`LOGOS/DERIBIT_PORT_ARCHITECTURE.md:1-10`, "code not written until Phase-0 verdict").
- Under Capital Architecture it would sit under Trading → Volatility/Options ("not started"). No yield or wallet code.

---

## (B) Spec inventory: doc → capability → declared status → implementation

MR = measured level in `docs/MATURITY_REGISTER.md` (generated **2026-08-22**, so it is ~6 weeks stale). Implementation counts exclude tests.

| Doc | Promised capability | Declared status (path:line) | Implementation evidence |
|---|---|---|---|
| archive/founding_docs/v0.4.5…/Strategy_Passport_Template_v0.4.5_DRAFT.md | Strategy passport (limits, entry/exit triggers, kill criteria, paper requirements) | DRAFT, historical (`archive/founding_docs/README.md:31-34`: "not active rules") | Descendant: strategy cards `data/strategy_cards/` + `research/cards/validate.py`. No per-strategy passport object in code |
| (none — idea only) docs/ideas/2026-09-25-defai-pdf-review.md:63-65 | **Position passport** (8 questions), onboarding risk profile, signing hygiene / anti-phishing, net-APY-after-route, "who pays", exit-before-entry | idea, not promoted (:3-4) | **NONE.** `position_passport` has 0 code hits. The "passport" modules in `spa_core/monitoring/agent_passport*.py` and `spa_core/studio_os/memory/passports.py` are about AGENTS and memory, not positions |
| docs/08_ai_investment_os_architecture.md, docs/10_agent_architecture.md | 16 Investment OS analysts | no line (header "L0/L1"); MR L5, partial (MATURITY_REGISTER.md:45) | `spa_core/investment_os/agents/` (11 agents) |
| docs/07_yield_lab_architecture.md, docs/07a_sleeve_status.md | Yield Lab lifecycle, sleeves, net APY | 07:3 "Canonical (ADR-YL-009)"; MR L5 (:48) | `spa_core/strategy_lab/` (promotion, sleeve_verdict, underwriting), `spa_core/tournament/` |
| docs/11 / 12 / 13 _*_card_system.md | Strategy, protocol and stablecoin cards | 11:3, 12:3, 13:3 "research-layer… no runtime code"; MR L4 (:52) | `research/cards/validate.py`; cards in `data/strategy_cards` (11), `data/protocol_cards/examples` (7), `data/stablecoin_cards/examples` (5). No automatic producer. Only runtime reader: `spa_core/paper_trading/curator_registry.py:95` |
| docs/14_risk_scoring_v2.md | Advisory risk scoring v2 | 14:9 research; MR **L2** (:56) | No v2 module. Precursors live: `spa_core/risk/scoring_engine.py`, `spa_core/dfb/risk_overlay.py` |
| docs/15_btc_cycle_framework.md, docs/36_btc_capital_cycle_machine.md | BTC cycle ladder | 15:3 = 36:3 "L2 · @yurii · приёмка: phase detector module…"; MR L2 (:54) | NONE in SPA. `research/btc_cycle/` is archived; `defi_cycle_phase_detector` is written off (`_tier_c_writeoff.py:84`). Superseded in practice by ED (ADR-525:15) |
| docs/16_eth_yield_framework.md | ETH / LST / LRT yield | no line; MR L2 "no measurement" (:55) | No `eth_yield` module; LST strategies are scattered in `spa_core/strategies`, plus a card `eth_staking_lrt.strategy.md` |
| docs/17_portfolio_construction.md | Spread-based product lines, allocation proposals | 17:3 Canonical, "L0/L1" | `spa_core/allocator/`, `spa_core/strategy_lab/portfolio_book.py` |
| docs/33_yield_thesis_map.md | Yield-source map (loops, LP, PT, delta-neutral) | 33:3 Canonical, ILLUSTRATIVE | doc only |
| docs/34_capital_tiers_strategy.md | Capital tiers by AUM; **exit plan per position** (34:79) | 34:3 Canonical | Tier caps in `spa_core/risk/policy.py`. Per-position exit plan: **NONE** |
| docs/35_strategy_discovery_engine.md, 35a_screening_rubric.md | Strategy discovery funnel | no line; MR L2 (:57) | No engine (pieces exist: `spa_core/dfb/`, `spa_core/data_pipeline/gmx_v2_discovery.py`, `spa_core/tournament/`) |
| docs/37_apy_realism_and_evidence_standard.md | L0–L6 evidence; advertised / net / risk-adjusted APY | 37:3 Canonical | `net_apy` appears in ~186 code files (e.g. `spa_core/reporting/pnl_attribution.py`). No per-position "net APY after route" |
| docs/38_stablecoin_yield_engine.md | Stablecoin yield engine | no line; MR L5 (shared row :48) | `spa_core/strategy_lab/aggressive_lab/`, `spa_core/investment_os/agents/stablecoin_yield.py` |
| docs/39_investment_committee_workflow.md | 19-stage Investment Committee | no line; MR L2 "premature" (:58) | **NONE**. Broken link at :15 to `07_yield_lab_lifecycle.md` |
| docs/43_dangerous_strategies.md | Refuse-list, emergency exit sized before entry (:46) | no line; MR L2 "research doc" (:62) | **NONE** (no refuse-list module) |
| docs/44_research_first_20_strategies.md | First-20 research roster | MR L2 | doc only |
| docs/46_protection_lab.md | Historical stress replay against the kill ladder | 46:3 "L4 … `python3 -m spa_core.stress.protection_lab --all`" | `spa_core/stress/protection_lab/` (61 tests) ✔ |
| docs/LOOPING_STRATEGY.md | "Up to +50%" looping track, Looping Desk, guardians, auto-deleverage ladder, drawdown budget (:202) | :3 "L2 — VISION… **no code**" | **Claim stale:** `spa_core/strategies/{s21_aave_loop,s3_yield_loop,emode_looping,s73_leverage_loop}.py`, `spa_core/analytics/defi_leverage_looping_optimizer.py`, `defi_protocol_leverage_loop_risk_analyzer.py`. Looping Desk / Guardian / loss budget: NONE |
| docs/DEFI_STRATEGY_RESEARCH_2025.md | Lending, Pendle PT/YT, basis, delta-neutral, LP survey | per-row "Статус в SPA" (:34,50,66,82,100,182,206,223) | Present: aave_v3, compound_v3, morpho_blue, yearn_v3, `pendle_pt*.py` adapters, `pendle_yt.py`, `delta_neutral_susde.py`. Named-but-missing: `aave_v3_arbitrum.py`, `pendle_pt_rest.py` (:34,:100) |
| Basis / delta-neutral (no dedicated spec doc) | Market-neutral sleeves | CAPITAL_ARCHITECTURE.md:19 "paper, advisory" | `s72_basis_trade.py`, `s71_delta_neutral.py` (0 non-test importers; s71 named in `aggressive_lab/roster.py`), `s_basis.py`, `delta_neutral_susde.py` |
| LP / CLMM: docs/research/RS-volatile-clmm.md | Volatile CLMM LP | :3 "research, read-only" | `spa_core/risk/policy_lp.py` (1 importer, 0 tests), `spa_core/analytics/concentrated_liquidity_analyzer.py`, `spa_core/strategies/s76_concentrated_lp.py` (0 importers), `docs/research/clmm_model.py` |
| docs/THREE_TIER_YIELD_PRODUCT.md | Conservative / Balanced / Aggressive on aggressive_lab; separate per-tier policy profile (:73) | :3 "owner-directive (2026-07-10)" | `spa_core/strategy_lab/aggressive_lab/`; `spa_core/risk/policy_hy.py`, `policy_lp.py` |
| docs/PACKAGES.md | 3 packages, net-of-cost / risk-adjusted APY, Tier-1 validation | no line | `spa_core/backtesting/tier1/packages.py`, `spa_core/api/routers/tier1.py:33` (`/api/tier1/packages`, which ED reads) ✔ |
| docs/AI1_ROADMAP / AUDIT / SUMMARY / QUICKSTART, PROJECT_AI1_INDEX.md | Machine-readable allocation: tier_validator, rebalance engine | QUICKSTART:7 "DRAFT"; PROJECT_AI1_INDEX.md:4 "READY FOR PICKUP"; AI1_ROADMAP SUPERSEDED (`architecture/memory_truth.json` overrides[0]) | `spa_core/agents/tier_validator.py` **missing**; the rebalance engine is at `spa_core/analytics/rebalance_engine.py`, not the stated path |
| ED/docs/03-yield-engines.md | Pendle PT engine, basis engine, stable LP, RWA floor | ED/config/engines_v0.1.json:3 "PROPOSED… not wired" | **NONE wired** (`ED/earn_defi/allocator.py:1`) |
| DC/docs/defi-checkup/00-22 | Wallet diagnostic, Exit-NAV, approvals, leverage | DC/BACKLOG_ARCHITECT.md (2026-07-10) "code ahead of docs" | `DC/packages/riskdesk/src/*` ✔ (but not deployed) |

**Gaps, no implementation anywhere:**
- position passport
- loss budget (in $)
- per-position exit plan / exit-before-entry
- malicious-spender / phishing detection (DC has known/unknown only)
- Investment Committee
- dangerous-strategy refuse-list module
- Risk Scoring v2
- Looping Desk / guardians

---

## (C) Superseded or stale concepts (old docs vs current canon)

| Old concept | Where it lives | Current canon |
|---|---|---|
| "HY 2 : LP 1 = $100k" split (Balanced $66k / Aggressive $33k) | old code comment; `docs/AGENT_REGISTRY.md:125` (HY $20k / LP $10k) | Each package is its own $100k book (`docs/decisions/ADR-125-three-tier-paper-tracks-start.md:27-31`) |
| `lp_cycle` = delta-neutral LP book, Aggressive empty | ADR-125:22 | CAPITAL_ARCHITECTURE.md:13 Aggressive = `lp_cycle` / `aggressive_lab` |
| Tier APY bands: PACKAGES.md 2–6 / 6–12 / 12%+; THREE_TIER 3.3–4 / 8–12 / 15–20%+; SiteHeader once "Preserve 6–8%" | `docs/PACKAGES.md:11-13`, `docs/THREE_TIER_YIELD_PRODUCT.md:17-21` | Single source `landing/src/lib/tier_bands.json` (`_note`); band values are owner-gated (subject #2) |
| Alt names Preserve / Core / Max-Yield | tier_bands.json `_note` | Primary names Conservative / Balanced / Aggressive; the alternate set is an open owner choice (#6) |
| `docs/adr/` registry | 56 files | SUPERSEDED by `docs/decisions/`; 5 number collisions (`architecture/memory_truth.json` facts[3]) |
| `PROJECT_CONTROL/` as entry point | `PROJECT_CONTROL/00_START_HERE.md` (still linked from CLAUDE.md header) | SUPERSEDED by CLAUDE.md + STATE.md + ROADMAP.md (memory_truth facts[4]) |
| `KANBAN.json` (MP-xxx) | still read by `spa_core/golive/readiness_checker.py`, `criteria.py`, `reporting/kanban_metrics.py`, `coordinator/sprint_coordinator.py` | SUPERSEDED by `nimbalyst-local/tracker` (memory_truth facts[5], "known debt") |
| 11+ roadmap files (AI1_ROADMAP, YIELD_STRATEGY_ROADMAP, PHASE2, FAMILY_FUND, EISENHOWER×2, PRODUCT_REDESIGN_H2, ATOMIC_MIGRATION) | docs/ | SUPERSEDED by `docs/ROADMAP.md` (memory_truth overrides[0-7]; ADR-527 §8) |
| SPA `btc_nav` (ADR-118), `research/btc_cycle`, docs 15/36 | SPA | superseded by earn-defi under Trading → Crypto Spot (ADR-525:38-39) |
| Founding docs: maxDD ≤ 2% success criterion, Strategy Passport | `archive/founding_docs/` | two-tier kill switch −5% / −10% (ADR-034/048); historical, "not active rules" (README.md:24-34) |
| "No code" for looping | LOOPING_STRATEGY.md:3 | stale; loop modules exist (see B) |
| `07_yield_lab_lifecycle.md` | 39:15 link | file is `07_yield_lab_architecture.md` |
| "Earn DeFi" label pointing at SPA worktrees | `SB/bridge/identity_guard.py:3-18` | Bridge refuses identity mismatch; earn-defi is a separate repo |
| DC as the SPA landing entry ("paste wallet") | old `WalletCheck` | removed (`landing/src/pages/index.astro:6-10`); entry is `/snapshot` |
| Sky/sUSDS "0% until GSM ≥48h" | DEFI_STRATEGY_RESEARCH_2025.md:82 | T1 since 2026-08-05 (ADR-065); the row itself notes this |
| ED whitelist v0.1 `maple_syrupusdc` | ED config v0.1 | v0.2 = SPA's four venues |
| MATURITY_REGISTER as current | generated 2026-08-22 | stale (pre-ADR-525); regenerate before citing levels |

---

## (D) Capital Architecture v1 (docs/CAPITAL_ARCHITECTURE.md, ADR-525): DeFi engine boundary and requirements

**The boundary:**
- **DeFi** = the SPA yield engine (`spa_core/…`, RiskPolicy v1.0, two-tier kill switch) with three branches (CAPITAL_ARCHITECTURE.md:10-13):
  - Conservative = the live $100k paper book
  - Balanced = `hy_cycle`
  - Aggressive = `lp_cycle` / `aggressive_lab`
- Separate branches **outside DeFi**:
  - Trading (`spa_core/trading_research`, plus ED under Crypto Spot) (:14-17, 25-27)
  - Cash/Treasury, which includes ED's stable leg (:18)
  - **Market Neutral / Basis**: the delta-neutral sleeves in strategy_lab / aggressive_lab (:19)
  - Future: RWA / Stable Yield via `rwa_backstop`, and Volatility/Options (:20-22)
- **Ownership (:29-38):** the engines own their signals, strategies, market data, positions, execution models and financial risk state. Studio OS / Bridge never own financial state. Studio OS only **reads published status** and renders it. Mutable engine state lives in runtime `data/`, never in an immutable release.
- **No cross-branch allocation by any engine** (:40-44). The Capital Allocator / Portfolio CIO is **not built**. When built, it will consume each engine's "published, evidence-backed metrics".
- **Permissions (:46-52):**
  - GREEN: research, backtest, paper.
  - YELLOW: promotion to CHAMPION_CANDIDATE / SHADOW, product-impacting config.
  - RED (owner only): real capital, orders, live API trading, **leverage activation**, prod risk limits, withdrawal permissions, secrets.

**What DeFi vNext must deliver.** Derived from the doc above; the ADR does not enumerate it.
1. **A published, evidence-backed status artifact** analogous to `data/trading_research/status.json` (:36), readable by Studio OS and the future CIO. Today DeFi exposes `/api/tier1/packages` and the paper-track files, not one engine status contract.
2. **A clean DeFi vs Market Neutral/Basis split.** Delta-neutral and basis sleeves currently live inside the DeFi code (`strategy_lab` / `aggressive_lab`) but are a separate branch in the hierarchy. vNext must either re-home them or tag them by branch.
3. **No cross-branch allocation inside DeFi.** ED's stable leg placing USDT into the Conservative book is a cross-engine flow. Per this doc it belongs to the future CIO; today it is a direct API read (`ED/config/stable_leg_v0.1.json:21`).
4. **Engine-owned risk state** remains RiskPolicy v1.0 plus the kill switch, unchanged (ADR-525:7-8 "no RiskPolicy / kill-switch change").
5. **Leverage (loops) is RED-gated.** Any vNext looping must stay paper and advisory.
6. **Roadmap position:** `docs/ROADMAP.md:19-24` orders the work as Memory → **DeFi Architecture Gap Audit (not started)** → **DeFi Engine vNext** → Build Loop → Owner Remote → Capital Allocator/CIO. No vNext spec doc exists yet: "vNext" appears only in ROADMAP.md:21 and ADR-527:57.

---

## (E) UNKNOWNs

1. Whether DC will be redeployed, and why the Railway app disappeared (404 since ≥2026-08-16). There is no deploy record in the repo, and its 15 uncommitted files (+2159 lines) have not been reviewed.
2. Whether DC prod ever had `ETHERSCAN_API_KEY` (DC-1). If not, approvals were "not scanned" in prod.
3. DC test count: 376 (commit messages) vs 222 (`BACKLOG_ARCHITECT.md:5`). Not run.
4. Whether ED's INCIDENT will be lifted. This is the owner's manual action (ED ADR-006). Not verified beyond the 09-30 monitor log.
5. Current measured L-levels: MATURITY_REGISTER is from 2026-08-22 and was not regenerated (a write action).
6. Whether `s71_delta_neutral`, `s72_basis_trade`, `s73_leverage_loop`, `s76_concentrated_lp` and `s40_pendle_pt_fixed` are reached at runtime. They have 0 static importers; s71 and s73 are named in `aggressive_lab/roster.py` (dynamic load not traced).
7. The exact wording of the three external PDFs (DeFAI ТЗ, "DeFi-архитектура" course, Kasatkin guide). They are not in the repo; only the summary `docs/ideas/2026-09-25-defai-pdf-review.md` exists. The "AI1 book" exists only as cited excerpts (`docs/journal/2026-W34.md:5184`). The source text was not found on disk.
8. The four founding PDFs (`archive/founding_docs/00_Admin/*.pdf`) were scanned via pdftotext. They contain no DeFi capability specs beyond the Strategy Passport mention (docs_architecture.pdf).
9. Why the Bridge activation-engine last exited with code 7. Not investigated (out of DeFi scope).
