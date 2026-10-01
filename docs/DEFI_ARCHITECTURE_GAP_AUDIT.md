# DeFi Architecture Gap Audit — 2026-10-01

> Decision record: [ADR-530](decisions/ADR-530-defi-architecture-gap-audit.md) · owner directive «DEFI ARCHITECTURE
> GAP AUDIT» (2026-10-01) · code audited at origin/main `e6204fd23`, runtime = live `~/Documents/SPA_Claude/data/`
> read 07:30–08:10 UTC. Evidence notes of the five read-only auditors: `docs/audits/defi_gap_2026-10-01/`
> (working evidence; every P0 and every headline number below was re-measured by the orchestrating session —
> marked ✔). **Nothing was implemented** in this epic; RiskPolicy, limits, books and the site were not changed.
>
> Classification: **IMPLEMENTED** = executable code on a running path (cycle_runner / cycle_gates / allocator /
> a loaded launchd agent) AND live artifacts show it acting · **PARTIAL** = code exists but unwired / advisory /
> covers part of the scope · **MISSING** = documents only or nothing · **WRONG** = runs but contradicts its own
> canon or reality · **OBSOLETE** = superseded, still present · **UNKNOWN** = not established by evidence.

## A. Current DeFi architecture (as it actually runs)

```
DeFiLlama (+ protocol adapters, ADAPTER_REGISTRY 36) ─► adapter_orchestrator ─► adapter_status / apy_ranking
        │                                                                     (16/16 funded pools live APY+TVL)
        ▼
com.spa.daily_cycle 08:00 ─► cycle_runner ─► allocator (tuner optimized_yield) ─► RiskPolicy v1.0 gate
   │   gates by IMPORT: Tier-A signal_aggregator · EmergencyBreakers · RTMR posture · kill_switch (two-tier)
   │   economics: rebalance_economics (ADR-060) + cio_arming HOLD + churn damper
   ▼
CONSERVATIVE book  data/current_positions.json + equity_curve_daily.json (100 evidenced days, hash-chained)
BALANCED book      com.spa.hy_cycle hourly ─► sleeve_book ─► data/hy_paper_trading.json   (outside RiskPolicy)
AGGRESSIVE book    com.spa.lp_cycle hourly ─► sleeve_book ─► data/lp_paper_trading.json   (outside RiskPolicy)
advisory only      aggressive_lab · strategy_lab_paper · rates_desk · swarm  (is_advisory, outside RiskPolicy)
monitoring         rtmr_sense (peg/tvl/oracle/liquidity) · threat_reactor · peg_monitor · red_flag_monitor ·
                   agent_health · cycle_health · golive_checker (29/29)
publication        generate_track_snapshot ─► landing/src/data/track_snapshot.json ─► site_numbers (weekly) ─► earn-defi.com
```

Every live position in every book is **single-asset stablecoin lending / savings**; there is no LP, Pendle,
leverage, loop, perp or CLMM position anywhere in a book (✔ positions read 2026-10-01). Paper only:
`execution_mode: read_only_simulation`, live trading gate locked, `ready_for_live=false` (custody/MPC, external
audit, execution mode). Other repos: **earn-defi** is a BTC trading engine (Capital Architecture → Trading), its
DeFi yield engines A/B/C are `PROPOSED … not wired`; **DeFi Checkup** (wallet diagnostic, approvals + Aave/Spark HF
reading) is **not deployed** — `checkup.earn-defi.com` answers 404 «Application not found» (✔); Bridge / Studio OS /
Company Memory hold no DeFi logic by the 2026-08-27 boundary decision.

## B. The three current packages (from live evidence)

| | **Conservative** (alt «Preserve») | **Balanced** («Core») | **Aggressive** («Max Yield») |
|---|---|---|---|
| Names source | `landing/src/lib/tier_bands.json` | same | same |
| Engine → book | `cycle_runner` → `current_positions.json` | `hy_cycle` → `hy_paper_trading.json` (sleeve B, «HY/Carry») | `lp_cycle` → `lp_paper_trading.json` (sleeve C, «LP/Liquidity») |
| Audience (site copy) | stability, capital preservation | family offices / systematic yield | experienced, higher drawdown |
| Positions 10-01 ✔ | compound_v3 40k · maple 20k · fluid_fusdc 20k · morpho_blue_base 10k · aave_v3 5k · cash 5k | maple · fluid_fusdc · susde · morpho_steakhouse ≈ $24.9k each | maple $50.1k · fluid_fusdc $50.1k |
| Tier mix | **T1 45 % / T2 50 %** (maple, fluid, morpho_blue_base are T2 in `risk/protocol_risk_map.py`) ✔ | 3×T2 + susde (T3 in registry), no T1 | 2×T2 |
| Mechanic | plain supply | plain supply / staked-USDe hold | plain supply, **top-2 concentration** |
| Risk gate | **RiskPolicy v1.0** + kill SOFT −5 % / HARD −10 % | **outside RiskPolicy**; own kill −8 % (`hy_cycle.py:48` ✔) + CIO gate | **outside RiskPolicy**; own kill −25 % (`lp_cycle.py:51`), cap 60 %/name |
| APY math | `pos·apy/365` − modelled move cost (dust band `min_leg_frac`) | `accrue_book` − `book_move_cost` + MTM (coverage 25 %) | same as Balanced (MTM coverage 0 %) |
| Gross / net | net of a *modelled* cost only since 2026-09-10 (costs $50.15 total) → headline 4.92 % effectively gross for 80 of 100 days | net of modelled cost; **costs $1,223.52**, daily cost $48.03 vs yield $13.77 ✔ | **costs $632.76**, daily cost $24.01 vs yield $14.34 ✔ |
| Exit assumptions | TVL ≥ $5M live, capacity ≤ 1 % pool; no exit-time model | TVL floor only; maple 14-day queue / susde 7-day cooldown **not modelled** | same; 50 % in maple |
| Rebalance | ADR-060 trigger, payback ≤30 d, min hold, CIO HOLD (today HOLD: gain 0.081 pp, payback 226 d) | daily re-size of every leg; never re-ranks | same |
| Automation | `com.spa.daily_cycle` 08:00, loaded | `com.spa.hy_cycle` hourly (1 row/day), loaded | `com.spa.lp_cycle` hourly, loaded |
| Status | paper, **100 evidenced days**, NAV $101,477.05, max DD −0.039 % | paper/advisory, NAV $99,555.06 (below seed), 22 observed-rate days of 39 | paper/advisory, NAV $100,260.76, 22 of 39 |

**What makes «aggressive» aggressive:** neither riskier protocols nor more complex mechanics — **concentration
(2 names, up to 60 %) plus a wider stop on the same universe** (`lp_cycle.py:14-18` says so). Yield ≈ the other
two books (5.22 vs 5.05 vs 5.39 %). All complex mechanics live only in advisory labs.

## C. Capability matrix

Evidence paths are relative to the SPA repo; `data/` = live runtime. «Canon» = the rule/ADR that defines the
expected behaviour.

| # | Capability | Class | Expected | Current implementation · evidence | Canon | Runtime evidence | Risk if incomplete | Recommendation |
|---|---|---|---|---|---|---|---|---|
| 1 | Position Passport | MISSING | per-position record: mechanic, who pays, exit plan, loss budget, evidence level | none; `position_passport` 0 code hits; idea only `docs/ideas/2026-09-25-defai-pdf-review.md` (not promoted) | — | — | user cannot see what a position is | vNext: a DERIVED view over book + registry, not a new store |
| 2 | Net APY after all costs | PARTIAL / **WRONG in sleeves** | accrual − real move cost | main: `cycle_runner.py:2503-2535` + `rebalance_economics` dust band; sleeves: `sleeve_book.py:390-444` charges $12 ETH gas per leg on daily equity drift (`:318-322`) | ADR-298, ADR-060 | ✔ hy cost 48.03 vs yield 13.77/day; lp 24.01 vs 14.34 | Balanced/Aggressive tracks lose money by construction (≈17.5 % / 8.8 % a year) | **P0-1** |
| 3 | Source-of-yield explanation | MISSING (decision path) | base vs reward vs fees per pool | `defillama_feed.get_apy` returns total APY; `apy_decomposition_log.json` 100 rows all `unknown`/0.0, last 2026-08-03, still labelled «L2 live» by `investment_os/agents/yield_quality.py` | docs/37 | dead artifact presented as live | emissions scored as organic yield | P1 |
| 4 | Exit plan / exit liquidity | PARTIAL (advisory) | exit time + queue gated before entry | adapter consts maple `EXIT_LATENCY_HOURS=336`, susde 168; `paper_trading/exit_liquidity.py` unwired; `check_axes` default False (`risk/policy.py:661`) | docs/34 §79, docs/43 | `exit_liquidity_log.json` analyses a non-held position | 25–50 % of B/C in queued assets, ungated | P1 |
| 5 | User loss budget | MISSING (display only) | per-package max loss enforced | `tier_bands.json` «≤3 % / ≤10 % / ≤25 %» has no money-path reader | inv. #8 | only global 5/10 % ladder enforced | published Conservative 3 % < enforced SOFT 5 % | P1 (owner subject #2) |
| 6 | Protocol risk | IMPLEMENTED (labels) / PARTIAL (score) | graded per protocol, drives caps | tiers T1/T2/T3 + caps in `risk/policy.py:108-162`; `scoring_engine` offline bootstrap, all grades B (`data/risk_scores.json`) | ADR-019/041 | caps applied every cycle | score never differentiates | keep tiers; P2 live inputs |
| 7 | Strategy (mechanic) risk | MISSING | separate dimension | no mechanic field in any registry; `StrategySpec.tier` reuses protocol vocabulary «T1+T2» | — | — | loop on Aave would inherit Aave's T1 cap | P1 (§D) |
| 8 | Wallet / signing safety | PARTIAL (inert) | no live signing; exact approvals to allowlisted spenders | `execution/` signer scrubs key; Aave approve exact amount to hard-coded pools; nothing live; DC `/cabinet` signs SIWE/revoke/payment, revoke without chain check | inv. #6/#7 | `SPA_EXECUTION_MODE=''` | acceptable for paper | P2 before any live step |
| 9 | Phishing / malicious approval protection | MISSING | flag malicious spenders | DC `KNOWN_SPENDERS_BY_CHAIN` known/unknown only, no flagged set; SPA none | — | DC not deployed | none today (paper); required pre-live | P2 |
| 10 | Bridge risk | PARTIAL (proxy) | per-bridge/asset model | Base cap 20 %, L2 total 50 % (`policy.py:141,162`); `risk_axes` bridge axis never evaluated | ADR-008/025 | Base 10 % | chain cap, not bridge model | P2 |
| 11 | Stablecoin / depeg risk | PARTIAL / **WRONG (peg_monitor)** | depeg → reduce/exit on held assets | RTMR peg quorum (≥3 sources) → posture → `apply_rtmr_posture_gate` live; RiskPolicy depeg check dormant (no caller passes prices); `peg_monitor.get_peg_price` returns **1.0 when no price** (`monitoring/peg_monitor.py:251-267` ✔), watches 3 non-held adapters, read by `threat_reactor.py:83-96` | inv. #2, #17, ADR-053 | ✔ `peg_report.json` GREEN, deviation 0.0, price 1.0 | a blind sensor reports calm into the intraday kill path | **P0-3** |
| 12 | Oracle risk | PARTIAL / WRONG label | detect oracle divergence | RTMR oracle sensor (Chainlink) live; EB-02 «oracle divergence» compares live APY with hard-coded APY literals (`cycle_runner.py:1796-1801`) | ADR-030 | 16 signals info | per-market oracles (Morpho) not represented | P2; rename EB-02 |
| 13 | Smart-contract / dependency risk | PARTIAL (inert) | graded, influences sizing | `scoring_engine` 15 subscores, offline BOOTSTRAP each cycle (`cycle_runner.py:566-575`) | FEAT-RISK-001 | all B, maple/fluid not scored | never acts | P2 |
| 14 | Liquidity risk | PARTIAL | exit-liquidity watch on every held pool | capacity ≤1 % pool TVL; RTMR liquidity covers aave_v3/compound_v3/fluid only | ADR-009/053 | maple 20 % + morpho_blue_base 10 % unwatched | 30 % of main book without liquidity sensor | P1 |
| 15 | Rebalancing logic | IMPLEMENTED (main) / WRONG (sleeves) | violation + yield-improvement triggers | ALLOC-001 `cycle_runner.py:1253-1318`, ADR-060 shadow + `cio_arming`; sleeves `rebalance_book` keeps any eligible holding, never re-ranks (`sleeve_book.py:301-316`) ✔ | ADR-055/060 | main HOLD with numbers; Aggressive keeps maple 5.14 while compound 6.11 ranks first | sleeves contradict their docstring «top-2 by APY» | P1 |
| 16 | Anti-churn | IMPLEMENTED (main) | hysteresis, min hold, payback | `rebalance_economics.py:83-84,343-409`, churn damper, CIO | ADR-060 | main costs $50.15 over 132 bars | — | preserve |
| 17 | Gas / execution cost model | IMPLEMENTED (static) | real gas per chain | `backtesting/tier1/cost_model.py` flat ETH $12/leg, L2 $0.05–0.25, used by main and sleeves | ADR-060 | reconciles exactly | static, no gas feed; misapplied in sleeves | P2 live gas; P0-1 fix |
| 18 | Slippage model | PARTIAL | size/depth-aware | flat 8 bp; depth tool research-only (`rates_desk/depth_at_size.py`, artifact 2026-06-29) | — | — | wrong at size / PT / LP | P2 |
| 19 | Reward-token price risk | MISSING | haircut emission APY | only in advisory scoring | — | — | emissions treated as cash | P1 with #3 |
| 20 | Incentive decay | MISSING (books) / PARTIAL (lab) | — | `aggressive_lab/roster.py:610-615` PointsFarm only | — | decomposition dead | — | P2 |
| 21 | APY sustainability | PARTIAL | persistence / spike screen | allocator uses point-in-time APY; no median/rolling | — | aave_v3 4.99→12.67 entered ranking at face value | spike chasing (main protected only by payback) | P1 |
| 22 | Historical APY reliability | PARTIAL | ≥30–90 d per pool | own series `apy_series_daily.json` 56 days; `apy_history.json` empty | — | 56 d / 23 pools | regime not judgeable | P2 backfill |
| 23 | TVL / liquidity thresholds | IMPLEMENTED | ≥$5M **live** TVL, else freeze | `risk_gate.py:~406-430`, `risk/tvl_floor.py` | ADR-053 | 16/16 TVL live | pool vs protocol TVL under one name (RTMR $18.3B vs cycle $57.7M) | preserve; name the unit |
| 24 | Protocol concentration | IMPLEMENTED (denominator conflict) | ≤40 % T1 / ≤20 % T2 of capital | RiskPolicy on capital; DL-03 on deployed (`risk/daily_limits.py:368`) | ADR-019 | permanent false WARN «compound 42.1 %» | trains to ignore WARN | P1 align |
| 25 | Chain concentration | IMPLEMENTED | single ≤90 %, L2 ≤50 %, Base ≤20 % | `policy.py:581-600` | MP-352 | Ethereum 85 % | 90 % is loose | — |
| 26 | Stablecoin concentration | MISSING | explicit cap or explicit acceptance | none in RiskConfig | — | book 100 % USDC | single-asset depeg = whole book | P1 decision (ADR) |
| 27 | Strategy concentration | MISSING | cap per mechanic | no mechanic dimension | — | — | 100 % one mechanic possible | P1 with #7 |
| 28 | LP / impermanent loss | MISSING (books) | IL model + price feed | `lp_cycle.py:262` «IL не моделируется»; `il_drawdown_pct` = equity drawdown; lab `EthStableLP` killed 2026-07-15 | — | engine C holds 0 LP | «LP sleeve» without LP mechanics | P2 rename/build |
| 29 | CLMM | MISSING | — | `docs/research/clmm_model.py` not imported; analyzer written off | — | — | — | P3 |
| 30 | Range management | MISSING | — | none | — | — | — | P3 |
| 31 | Looping / recursive lending | PARTIAL (advisory lab) | — | `aggressive_lab/roster.py:552` LeverageLoop (liq proxy), strategies `s21_aave_loop`, `emode_looping`, `s73_leverage_loop` (no live caller); `docs/LOOPING_STRATEGY.md:3` «no code» is stale | Capital Architecture (leverage = RED) | lab equity 100,183 advisory | — | P3 (owner-gated) |
| 32 | Liquidation / health factor | PARTIAL (proxy) | position HF from oracle/LTV | lab proxy `levered_move ≤ −0.5/lev` (`roster.py:439-441`); DC reads Aave/Spark HF (not deployed) | — | no borrowing anywhere | n/a until leverage | P2 (RTMR sensor when leverage) |
| 33 | Leveraged yield | PARTIAL (advisory) | — | `swarm/leverage_brain.py` → all `REFUSED_NO_TELEMETRY` | — | — | — | P3 |
| 34 | Pendle / fixed-variable | PARTIAL (advisory paper) | — | `rates_desk` PT carry, `pendle_pt*` adapters, lab YT/PT-levered | — | rates_desk equity 100,207.76 «honest no-edge»; not in any book | — | P2 (PT to maturity into Balanced paper) |
| 35 | Basis / carry DeFi | PARTIAL (stale) | — | `strategies/s_basis.py` via tournament only; `basis_trade_opportunities.json` stale 08-29, literal spot 5.0 | Capital Architecture: Market-Neutral branch | — | belongs to another branch | re-home (P2) |
| 36 | Delta-neutral | PARTIAL (lab) / **WRONG (books)** | computed neutrality | lab `SusdeDeltaNeutral`; books stamp `is_delta_neutral: True` on every leg (`sleeve_book.py:312` ✔), `lp_cycle` treats missing as True | inv. #2 | maple/fluid credit book «delta-neutral» | tautological safety check | P1 |
| 37 | Funding-rate dependency | PARTIAL | Balanced reads real funding | `hy_cycle.py:129-142` APY stand-in, non-gating; real 5-venue feed drives `swarm/funding_regime` (YELLOW) | ADR-125 | Balanced holds 25 % susde without funding input; `perp_funding_rates.json` stale 08-29 | funding flip unseen | P1 (advisory first) |
| 38 | Active strategy supervision | IMPLEMENTED (fragmented) | one supervisor | kill ladder, Tier-A block, CIO arming on 3 books, threat_reactor, RTMR posture, CIO directive — four de-risk entry points; `intraday_actor.py`, `golive_checker_hy` unwired, `golive_lp` CLI-only | ADR-103/114 | all loaded | gaps between overlapping supervisors | P1 consolidate |
| 39 | Emergency exit | IMPLEMENTED (paper) | owner + automatic all-cash | `/pause` → `kill_switch_active.json` → ALL_CASH; `cio_kill_switch_controls.json` | ADR-048 | PRESENT 1 / CONFLATED 1 / ABSENT 1 | owner has liquidate but no hold-only button | P1 |
| 40 | Kill switch | IMPLEMENTED (drawdown) / **WRONG (red-flag trigger)** | SOFT 5 / HARD 10 + red flags | drawdown ladder wired (`cycle_runner.py:1408,1516`, `cycle_gates.py:148,178`); red-flag path ignores ALL flags when `fallback_used=true`, missing file ⇒ «not triggered» (`kill_switch.py:446-482` ✔) | ADR-034/048, inv. #2/#17 | ✔ `red_flags.json` 07:40Z fallback_used=true, 4 flags (2 CRITICAL) ignored; status «all triggers clear» | live CRITICAL flag cannot fire | **P0-2**; also `RiskConfig.max_drawdown_stop=0.05` still reported as «kill at 5 %» (`golive/checklist.py:259-277`) |
| 41 | Incident handling | PARTIAL | open → react → close | `data/incidents.json` (DefiLlama hacks, 1299, 26 tagged); `risk_alerts.json` «critical» with 51 July alerts never closed | — | stale criticals | «critical» means nothing | P1 lifecycle |
| 42 | Monitoring | IMPLEMENTED | loaded, fresh | 84+ `com.spa.*` loaded; `swarm_health`, `site_freshness` exit 1; `cycle_health` HEALTHY while replay FAIL 1/23 days ($50.15) | ADR-053 | agent_health 79/82 | aggregate green hides a track-integrity fail | P1 |
| 43 | Paper / shadow / canary lifecycle | PARTIAL (advisory) | research → paper → canary → full | `tier1_canary.json` advisory, 0 candidates; promotion engine «promote» on Sharpe 8.96–40.4 | ADR-023 | no capital effect | promotion signal not credible | P2 |
| 44 | Human approval gates | IMPLEMENTED (site + money locks) | ADR-285 three subjects | `check_owner_gate.py`, `safe_site_push.py`; `live_trading_gate.py` locked | ADR-285 | gate `active=false` | — | preserve |
| 45 | Real-capital promotion gates | PARTIAL (inventory-heavy) | evidence-based readiness | `golive_checker.py` 29 criteria, ~13 are file-exists/importable checks; `execution_readiness` names real blockers | ADR-011/057/059 | ✔ 29/29 ready, 100 days, 14 consecutive ready days; `ready_for_live=false` | «29/29» overstates readiness | P1 relabel / move real blockers in |
| 46 | Evidence / provenance | IMPLEMENTED | tamper-evident track | equity hash chain 100/100, book commit/reveal 22/22, cycle_inputs 57/57, audit_chain 26,866 re-derived; snapshot manifest missing ⇒ verifier FAILED; Bitcoin anchor unconfirmed | ADR-129 et al. | re-derived by auditor | external verification incomplete | preserve; P2 manifest |
| 47 | Reproducibility | PARTIAL | replay any evidenced day | `decision_reproducibility.json` 3/3 identical; `cycle_inputs.jsonl` only from 2026-09-09 | — | replay FAIL 1/23 | days before 09-09 not replayable | P2 |
| 48 | Strategy versioning | PARTIAL | code SHA + strategy version per record | only `policy_version v1.0`, `shadow-v1`; no code SHA in main-book records | — | — | cannot tie a result to code | P1 |
| 49 | Historical outcome tracking | IMPLEMENTED (advisory) | outcomes vs predictions | `investment_os/outcomes.jsonl` 57 rows, `allocation_rationale_history.jsonl` 77, `track_ledger.json` | — | — | — | preserve |
| 50 | Product explanation / transparency | **WRONG** | site matches books and canon | see §H; Conservative «Tier 1 only» vs 50 % T2 ✔; «No lock-up. T+1 … No withdrawal fee» ✔ (solicitation, inv. #8); «L6 · live evidenced» on paper ✔; Aggressive «leverage» with none in book | inv. #8, site-copy, docs/37 | ✔ live pages 2026-10-01 | public claims contradict the product | **P0-4** (owner subject #2) |
| 51 | Sleeve books under RiskPolicy | WRONG | every package book through the hard gate, or labelled outside it | B/C never call RiskPolicy; Aggressive maple 50 % vs T2 cap 20 %; site says the same kill switch applies | inv. #1, ADR-125 | ✔ positions | public «RiskPolicy applies to all» untrue | P1 |
| 52 | One APY definition | MISSING | one canonical «current yield» | 5.39 (`apy_today`) · 5.469 (`apy_now_pp`) · 5.757 (tuner) · 4.92 (site, annualised from anchor); Telegram simple vs site compound; lab `net_apy_pct` = cumulative return (`roster.py:229-233`) | docs/37, site-numbers rule | four values same morning | readers compare different quantities | P1 |
| 53 | One tier registry | WRONG | one source per protocol tier | five copies disagree: `ADAPTER_REGISTRY`, `ADAPTER_METADATA`, `POLLED_ADAPTERS` (11; rule says 8), `data/adapter_registry.json` (static 06-22, read by money path), `policy_enforcer.T1_ADAPTERS`; e.g. morpho_steakhouse T1/T2, aave_v3_base T1/T2 | adapters rule | open owner card on morpho_steakhouse | cap differs 2× by which copy is read | P1 |
| 54 | Published engine status contract | MISSING | one evidence-backed DeFi status for Studio OS / CIO | `/api/tier1/packages` (backtest) + track files; earn-defi reads the backtest number as «Conservative rate» | Capital Architecture §36 | — | consumers read the wrong number | P1 |
| 55 | Wallet diagnostic product (DeFi Checkup) | OBSOLETE (deployed) / PARTIAL (code) | live funnel or retired | code real (riskdesk TS, 74 test files), host 404 since ≥ 2026-08-16, 15 uncommitted files | — | ✔ 404 | dead funnel; uncommitted work at risk | owner decision (P2) |
| 56 | Owner-facing DeFi reporting | PARTIAL | all three books, costs, warnings | SYSTEM_BRIEFING covers Conservative only; Telegram gives Σ equity of B/C only | ADR-521 | — | owner never saw B/C lose money daily | P1 |

## D. Protocol risk vs strategy risk

**Finding: the system has ONE risk dimension.** Tier (T1/T2/T3) and one `risk_score` per adapter key fold the
mechanic into free text (`risk/protocol_risk_map.py`: maple «private credit / RWA» 0.45 T2, aerodrome «AMM LP +
emissions» 0.45 T2, ethena «delta-neutral, funding» 0.40 T2 — three mechanics, one number). `StrategySpec.tier`
(`paper_trading/strategy_registry.py:52-67`) expresses strategy risk in protocol vocabulary («T1+T2»).
`scoring_engine.yield_source_type` is the closest mechanic attribute but is averaged into a protocol grade and
runs offline. The only mechanic attributes that exist are **wrong** (`is_delta_neutral: True` stamped on every
sleeve leg). Consequence: Aave supply and an Aave loop would share Aave's T1 40 % cap. The UI shows protocol
risks under the heading «Strategy-Specific Risks»; no page separates the two.

**Required architecture (input for vNext, not designed here):** a second axis `mechanic ∈ {supply, rwa_credit,
staked_synthetic, lp_stable, lp_volatile, clmm, pt_fixed, yt, loop, basis, delta_neutral}` carried by every
position, with its own risk score, its own concentration cap and its own data needs (HF for loop, IL for LP,
funding for basis/synthetic, maturity for PT); risk of a position = f(protocol, mechanic). Caps per mechanic
are a RiskPolicy change ⇒ a new ADR; v1.0 stays frozen for the paper period, so the axis starts **advisory**.

## E. Active strategy support

| Mechanic | Executable? | Where it runs | Evidence |
|---|---|---|---|
| stable lending / savings | yes | **all three books** | positions ✔ |
| concentration (2×60 %) | yes | Aggressive book | `sleeve_book.py:54-56` |
| cost-aware rebalance / anti-churn | yes | Conservative (CIO-armed) | `allocation_rationale.json` HOLD |
| sUSDe carry (unhedged) | yes | Balanced book (25 %) | `hy_paper_trading.json` |
| delta-neutral sUSDe + short perp | yes | advisory lab | `susde_dn` equity 103,042.8 |
| Pendle PT to maturity | yes | advisory (rates_desk, strategy_lab_paper) | `rates_desk/paper/status.json` |
| Pendle YT · PT levered loop | yes | advisory lab | pendle_yt 120,667; pt_levered 100,731.7 |
| wstETH loop · levered restaking | yes (liq proxy) | advisory lab | leverage_loop 100,183 |
| points / emission farming | yes | advisory lab | points_farm 101,540 |
| ETH/stable LP with IL | dead | advisory lab, killed 2026-07-15 | `status.json` kill_reason |
| dynamic leverage recommendation | yes | swarm, all REFUSED | `leverage_brain.json` |
| funding regime | yes | swarm (YELLOW), not read by Balanced | `funding_regime.json` |
| basis scan | stale | analytics 08-29 | `basis_trade_opportunities.json` |
| CLMM / range management | no | research doc only | `docs/research/clmm_model.py` |
| recursive lending (Looping track) | no live | doc + lab | `docs/LOOPING_STRATEGY.md` |
| health-factor monitoring | no | lab proxy; DC (not deployed) | `roster.py:439` |

No complex mechanic has ever been held in a package book with observed rates; the Pendle/Ethena/Aerodrome legs
held 08-24…09-10 ran on fallback literals and were removed by ADR-292.

## F. Agents / roles (Agent Passport view)

| Target role | Existing equivalent | Missing responsibility | New role needed? |
|---|---|---|---|
| Opportunity Scanner | `agents/alpha_agent` (Mondays via `cycle_reporting.py:133-138`) + `discovery_step` daily; CIO house view `top_opportunities` | candidate → adapter is manual; house view republishes static-TVL `moonwell_base` as «L2 live» | **No** — extend; make house view respect `tvl_source` |
| Net Yield Calculator | `allocator/rebalance_economics` + `cio_arming` (in cycle) | persistence term; sleeve cost bug; one APY definition | **No** — extend |
| Loop Simulator | loop strategies via `mass_tournament`, `rates_desk/levered_stress` (shadow) | nothing while no leverage | **No** |
| Health Factor / Liquidation Monitor | none on money path (correct: nothing borrows) | — | **No** — when leverage exists: an RTMR sensor, not an agent |
| Rate Shock Monitor | EB-01 (T1 APY > 100 %), APY band 1–30 %, `red_flag_monitor` apy_spike on bootstrap baselines | RTMR has no rate sensor | **No** — add RTMR rate sensor |
| Oracle / Depeg Monitor | RTMR `com.spa.rtmr_sense` peg quorum + oracle (live, gate-wired) | `peg_monitor` blind (P0-3); no USDe quorum while Balanced holds susde | **No** — point threat_reactor at RTMR; retire/fix peg_monitor |
| Liquidity / Exit Agent | RTMR liquidity sensor (3 of 5 held pools), `com.spa.io_liquidity` (advisory, wrong position) | `exit_liquidity.py` unwired; maple / morpho_blue_base uncovered | **No** — wire + extend scopes |
| Strategy Supervisor | kill_switch, threat_reactor, RTMR posture, CIO directive + arming (four de-risk entry points) | no sleeve-level supervisor; `golive_checker_hy` unwired, `golive_lp` CLI only, `intraday_actor.py` unwired | **No new agent** — consolidate into one supervisor contract over existing modules |

Every target role exists under another name; none justifies a new agent. Passport coverage: decision origin
UNKNOWN for 50 of 87 agents (`python -m spa_core.studio_os.memory coverage`).

## G. Source-of-truth map

| Domain | Canonical | Writer | Readers | Conflicts / stale mirrors |
|---|---|---|---|---|
| Strategies | `spa_core/strategies/strategy_registry.py` (code) | — | tournament, cycle | `data/strategy_config.json` absent (default shadow); `strategy_configs*.json` duplicates; 12+ `strategy_lab_*.json` |
| Protocol adapters / tiers | `ADAPTER_REGISTRY` (36) | code | cycle via orchestrator | **five tier copies disagree** (#53); `data/adapter_registry.json` static 2026-06-22 still read by `risk_gate.py:253,348`, `cycle_runner.py:1199,2507`, `golive_checker.py:103` |
| APY | DeFiLlama → `adapter_orchestrator` → `adapter_status.json` | orchestrator | allocator, risk_gate | `apy_ranking.json` aave_v3 TVL $4.09M vs `current_positions` $57.7M same morning (pool identity, UNKNOWN); four «current APY» values (#52); `apy_history.json` dead |
| Positions (main) | `data/current_positions.json` | cycle_runner | API, snapshot, monitors | mirrors agree today |
| Paper state | `equity_curve_daily.json` (A), `hy_paper_trading.json` (B), `lp_paper_trading.json` (C) | cycle_runner, hy_cycle, lp_cycle | golive, snapshot, site | `golive_hy_report.json` stale 09-15 «PASS» while B below seed; `golive_lp_report.json` absent; four definitions of Balanced/Aggressive (books · lab blends · tier1 backtest · site prose) |
| Risk state | `kill_switch_status.json`, `derisk_status.json`, RTMR `risk_posture.json` | kill_switch, threat_reactor, rtmr | cycle gates | `data/risk_policy.json` (v2.0, 2026-06-20) contradicts v1.0 numbers but feeds red-flag params; `risk_alerts.json` stale critical; posture NORMAL with stale reason |
| GoLive | `data/golive_status.json` (live) | golive_checker | snapshot, briefing, Telegram | git-committed copy + CLAUDE.md header «27/29 · 13/30» stale vs live 29/29 · 100 days |
| Allocation | `allocation_rationale.json` (+ history) | cycle_runner | cio_arming | false hold message «$40,000 ≤ $200» (`risk_gate.hold_reason` lacks CIO branch); DL-03 vs RiskPolicy denominator |
| Incidents | `data/incidents.json` | writer UNKNOWN by name | — | `alert_log.json` stale 2026-08-24 |
| Approvals | tracker cards + `check_owner_gate.py` | `orchestrator_queue.py` | owner_decision_pending | prod tree 735 cards vs origin 1156 (prod read stale); `KANBAN.json` still read by `golive/readiness_checker.py` |

No new canonical store is proposed; every conflict above is resolved by naming the existing canonical source and
making the other copy derived or retired.

## H. Product / site gaps (live pages, 2026-10-01; no redesign)

| Item | Verdict | Evidence |
|---|---|---|
| What each strategy does | MISLEADING | /strategies/aggressive/ «Levered PT carry loops · Points · Unhedged directional restaking» vs book = maple + fluid supply; /methodology/ «Balanced paper tracked since June 22 … Conservative / Aggressive — not yet started» (inverted) ✔ |
| Composition | MISLEADING | /strategies/conservative/ «Tier 1 protocols only … No Tier 2 or Tier 3» vs 50 % T2 ✔; Spark listed, not held |
| Where yield comes from | PARTIAL | «All yield comes from lending market interest» while Balanced holds sUSDe |
| Gross vs net | MISLEADING | bands «net APY»; home «no costs charged» while costs are charged; /risk-disclosure «paper excludes gas and slippage» |
| Major risks | PARTIAL | per-page lists; Balanced «depeg Low, liquidation None» ignores sUSDe |
| Liquidity / exit time | MISLEADING + **inv. #8** | «No lock-up. Standard processing T+1 … up to 5 business days. No withdrawal fee.» ✔ vs /faq «no terms set» and /emergency-withdrawal «no withdrawal process» |
| Leverage / liquidation | MISLEADING (Aggressive) | claims leverage and liquidation-cascade risk for a book with none |
| Protocol vs strategy risk | ABSENT | no separate mechanic risk anywhere |
| Historical vs current yield | MISLEADING | hard-coded «~3.5 % / ~4.8 % / ~5 %»; calculator literal 3.3 % (`index.astro:188,206`); «go-live ≈ July 21, 2026» |
| Paper vs real | PARTIAL / MISLEADING | paper disclosed widely, but /packages «LIVE · evidenced · fundable», «L6 · live evidenced» ✔; FAQ present-tense «Gnosis Safe … no transaction goes through without confirmation» |
| Evidence level | PARTIAL | /methodology correctly says paper = L3; /packages says L6 for the same track |
| Kill switch for B/C | MISLEADING | «same non-overridable two-tier kill switch applies» vs −8 % / −25 % in code |

All fixes touch public numbers / legal wording ⇒ **owner subject №2**; they ship only through
`scripts/safe_site_push.py` with an owner card.

## I. Existing strengths (re-measured today — preserve)

1. **Deterministic RiskPolicy v1.0 on every cycle** (`risk_gate.py:288`, re-run after redistribution), blocks persisted with context (`risk_policy_blocks.json`, 100 records).
2. **Two-tier drawdown kill switch** wired at two points, all-cash override is a measured door, latency drill passes daily.
3. **TVL floor on live TVL only**, fail-closed, no constant stamping (16/16 live).
4. **Provenance discipline**: sleeves fund only `apy_source==live && tvl_source==live`; main zero-accrues fallback pools (ADR-298).
5. **Main-book economics**: payback / min-hold / turnover / reversal / churn damper / CIO in layers; HOLD with numbers; $50.15 costs in 132 bars.
6. **Gates by import**: Tier-A BLOCK zeroes target, EmergencyBreakers, RTMR posture, `_fundable` blocks 8 unevidenced pools today.
7. **RTMR peg sensor** with a real multi-source quorum (n_fresh 3–5).
8. **Tamper-evident evidence**: equity chain 100/100, commit/reveal 22/22, cycle_inputs, audit_chain all re-derive; allocator/tuner deterministic 3/3.
9. **Live-capital lock** in independent layers (gate key + prerequisites, `SPA_EXECUTION_MODE`, adapter `dry_run`, `execution_readiness` naming real blockers); exact-amount approvals to hard-coded pools.
10. **Honest advisory lab**: ten real-feed strategies with hash-chained forward series, labelled `is_advisory`, `outside_riskpolicy`.
11. **Owner gate on public numbers** (`check_owner_gate.py`), refusal-first culture, third outcome «not measured» used widely (MTM coverage, UNMEASURED stable leg).

## J. Priorities

### P0 — correctness / safety blockers

| ID | Gap | Why it matters | Subsystem | Dependency | Evidence | Acceptance criterion for the future fix |
|---|---|---|---|---|---|---|
| P0-1 | Sleeve books charge full gas on daily accrual drift | Balanced/Aggressive tracks are wrong by construction (−$34/day, −$10/day); any published number from them is false | `paper_trading/sleeve_book.py` (`rebalance_book` + `book_move_cost`) | none | ✔ `hy/lp_paper_trading.json` 2026-09-28…10-01 cost 48.03 / 24.01 vs yield 13–14 | with unchanged holdings and no new candidate, a replay of the last 22 observed days charges `cost_usd == 0` on drift-only days and `net_pnl == yield`; a genuine swap still pays the cost_model cost; the restated tracks are published only after owner approval (subject №2) |
| P0-2 | Kill-switch red-flag trigger fail-open | a live CRITICAL TVL-drop/governance flag on a held protocol cannot fire the kill; a missing file reads as «clear» (inv. #2, #17) | `governance/kill_switch.py:446-482` | none | ✔ `red_flags.json` 07:40Z `fallback_used=true`, 4 flags ignored; status «all triggers clear» | flags are filtered per flag by `source` (bootstrap-only flags ignored, live flags counted) — positive control: fallback document + ≥ threshold live CRITICAL flags on held protocols ⇒ triggered; missing/invalid file ⇒ a distinct «unmeasured» outcome, never «not triggered» |
| P0-3 | `peg_monitor` invents price 1.0 and watches non-held assets; its GREEN feeds `threat_reactor` | the intraday kill path reads a blind sensor as calm | `monitoring/peg_monitor.py:251-267`, `threat_reactor.py:83-96` | RTMR peg signals (exist) | ✔ `peg_report.json` GREEN, price 1.0 ×3, none held | no price field ⇒ `None` / unmeasured (never 1.0); monitored set == held stablecoin set; threat_reactor reads the RTMR quorum; a unit test with an entry lacking price fields yields «unmeasured», not GREEN |
| P0-4 | Public site contradicts books and canon, incl. solicitation wording | inv. #8 (no solicitation), docs/37 (paper ≠ L6), false «Tier 1 only», false leverage / kill-switch claims | `landing/**` (owner-gated) | owner decision (subject №2) | ✔ live pages quoted in §H | `site_content_audit` + a new contradiction check report zero mismatches between package pages and `track_snapshot` / books; the «No lock-up / T+1 / no fee» text is gone; evidence level of paper tracks = L3; owner approved via `safe_site_push.py` card |

### P1 — required for a credible product

| ID | Gap | Why | Subsystem | Dependency | Evidence | Acceptance |
|---|---|---|---|---|---|---|
| P1-1 | No strategy-mechanic risk axis (§D) | protocol tier stands in for mechanic risk; caps inherit wrongly | registries, RiskPolicy (advisory first) | ADR for any cap | §D | every position carries `mechanic`; advisory caps per mechanic computed each cycle; `is_delta_neutral` derived from mechanic, missing ⇒ fail-closed |
| P1-2 | Balanced/Aggressive outside RiskPolicy while public pages say otherwise | inv. #1 framing; maple 50 % vs T2 20 % | hy_cycle / lp_cycle | P1-1, owner (public copy) | positions | each sleeve book passes `check_portfolio_health(check_axes=True)` advisory every run with verdict persisted; site states the actual gate |
| P1-3 | Exit liquidity not gated; RTMR liquidity misses maple, morpho_blue_base | 25–50 % in 7–14-day queues; 30 % of main book unwatched | `exit_liquidity.py`, RTMR sensors, `risk_axes` | ADR (axes) | adapter consts; `signals/latest.json` scopes | every held pool has a liquidity sensor scope; exit latency per position published; illiquid share computed each cycle |
| P1-4 | Source-of-yield split missing; dead decomposition labelled live | emissions treated as organic | `defillama_feed`, ranking, `yield_quality` | none | `apy_decomposition_log.json` | ranking rows carry apyBase/apyReward; decomposition artifact fresh or marked unmeasured |
| P1-5 | No canonical APY definition; gross/net never shown | four «current APY» values; headline effectively gross 80/100 days | snapshot, books, Telegram, lab | owner for public wording | §C #52 | one named definition per published number; gross and net both computed; lab field renamed to cumulative return |
| P1-6 | Five tier registries disagree | cap differs 2× by copy | adapters / policy_enforcer / data/adapter_registry.json | open owner card (morpho_steakhouse) | §G | one canonical tier map; others derived; ratchet test |
| P1-7 | User loss budget display-only | promised 3 % < enforced 5 % | tier_bands / books | owner (subject №2) | §C #5 | each package budget bound to a per-book gate or the copy changed |
| P1-8 | Sleeves never re-rank; delta-neutral stamp | contradicts docstring and safety meaning | `sleeve_book.py` | P0-1 | §C #15, #36 | yield-improvement leg with the main path's hysteresis; neutrality computed |
| P1-9 | Supervision fragmented; `golive_checker_hy/lp`, `intraday_actor` unwired | sleeves have no readiness verdict; stale PASS | paper_trading | none | §F | one supervisor contract listing every de-risk entry point; sleeve readiness generated each run |
| P1-10 | GoLive 29/29 overstates readiness | ~13 checks are file-exists | `golive_checker.py` | none | §C #45 | criteria split into evidence vs inventory; real blockers (custody, audit) are criteria |
| P1-11 | Stablecoin concentration undecided | 100 % USDC | RiskPolicy (ADR) | engineering ADR (not an owner subject); advisory cap first | §C #26 | explicit ADR: accept with rationale or advisory cap |
| P1-12 | Code version not in records | results not tied to code | cycle records | none | §C #48 | every cycle record carries code SHA + strategy version |
| P1-13 | No rate-shock sensor; bootstrap apy_spike | intraday APY collapse unseen | RTMR | none | §F | RTMR rate sensor on held pools with measured baselines |
| P1-14 | Owner controls: hold-only missing; stale criticals; false hold reason; DL-03 denominator | owner can only liquidate; alarms lose meaning | telegram / risk_alerts / risk_gate / daily_limits | none | §C #39, #41, #24 | hold-only command maps to SOFT effect; alerts expire; hold_reason names the CIO HOLD; DL-03 on capital |
| P1-15 | No published DeFi engine status contract | Studio OS / CIO / earn-defi read the wrong number | publication | Capital Architecture | §C #54 | one `data/defi_engine/status.json`-style artifact (like trading_research) consumed by Studio OS and earn-defi |
| P1-16 | Owner reporting covers Conservative only | owner did not see B/C bleed | SYSTEM_BRIEFING, Telegram | none | §C #56 | brief + daily report show all three books with costs and warnings |

### P2 — capability expansion
Pendle PT to maturity in Balanced paper (#34); funding regime into Balanced (#37); live gas feed and depth-aware
slippage (#17, #18); APY persistence filter + DeFiLlama history backfill (#21, #22); IL model or rename the «LP»
sleeve (#28); risk scoring live inputs (#6, #13); per-market oracle (#12); bridge model (#10); snapshot manifest +
anchoring (#46); replay before 2026-09-09 (#47); promotion signal sanity (#43); allowance/phishing monitor before
any live step (#8, #9); Position Passport as a derived view (#1); decision on DeFi Checkup (#55); re-home basis /
delta-neutral to the Market-Neutral branch (#35).

### P3 — later / advanced
CLMM and range management (#29, #30); recursive lending, leveraged yield, YT, levered PT in books (#31, #33);
health-factor sensor (when leverage exists, #32); points farming; Investment Committee workflow; Risk Scoring v2.
Leverage activation is owner-only (Capital Architecture RED).

## K. DeFi Engine vNext — architecture input

**Preserve:** RiskPolicy v1.0 unchanged for the paper period; two-tier kill switch; live-only TVL/APY provenance;
main-book rebalance economics; gates-by-import; RTMR sense loop; hash-chained evidence; live-capital lock;
owner gate; the Conservative evidenced track (never reset).

**Repair first (P0):** sleeve cost accounting; red-flag kill trigger; peg_monitor; public package pages
(owner-approved).

**Add (P1):** mechanic axis (advisory); one book engine for all three packages; exit-liquidity model; source-of-
yield split; one APY definition with gross/net; one tier registry; published DeFi status contract; supervisor
contract; owner reporting for all books.

**Do NOT add:** new agents for the eight target roles (all exist — extend); a second position or tier store;
LLM in any risk / allocation decision; leverage, loops, CLMM or YT in package books; live execution; changes to
RiskPolicy thresholds without an ADR; cross-engine allocation inside DeFi (that is the future CIO).

**Proposed component boundaries (no new canonical store):**

| Component | Owns | Built from (existing) |
|---|---|---|
| Market data & evidence | APY/TVL with provenance, apyBase/apyReward, pool identity | adapters, `defillama_feed`, `adapter_orchestrator` |
| Protocol registry | one tier/mechanic map per pool | `ADAPTER_REGISTRY` (canonical); others derived |
| Book engine | the three package books, one accounting + cost path | `cycle_runner` main path generalised; `sleeve_book` economics retired into it |
| Risk | protocol axis (RiskPolicy v1.0, hard) + mechanic axis (advisory) + exit liquidity | `risk/policy.py`, `risk_axes`, `exit_liquidity.py` |
| Supervisor | one contract over kill switch, RTMR posture, threat_reactor, CIO | existing modules, no new agent |
| Monitoring | sensors for every held pool (peg, oracle, liquidity, **rate**) | RTMR `sense_loop.register_sensor` |
| Position Passport | derived per-position view (mechanic, who pays, exit, loss budget, evidence) | books + registry + risk outputs; never a store |
| Publication | `defi_engine` status artifact → snapshot → site_numbers | `generate_track_snapshot`, `site_numbers` |

**Migration constraints:** Conservative track continuity (100 evidenced days) must survive; Balanced/Aggressive
tracks are invalid until P0-1 — restating or resetting them, and any changed public number, is owner subject №2;
v1.0 policy frozen ⇒ mechanic caps advisory until an ADR; the live data/ tree is never reset; sync and deploy by
`.claude/rules/deployment.md`; one source per fact (retire `data/adapter_registry.json` money-path reads).

## N. UNKNOWN / unproven (named, not guessed)

- aave_v3 pool identity: ranking TVL $4.09M / APY 12.67 vs cycle $57.7M / 5.40 the same morning.
- Whether `apply_rtmr_posture_gate` has ever clamped a position (`monitoring/reaction_log.json` not parsed).
- Last `pre_cutover_gate` verdict (no `data/pre_cutover*.json`).
- Maple redemption-queue modelling anywhere.
- Writer of `data/incidents.json`.
- Whether `adapter_registry.json.fallback_apy` ever passed RiskPolicy on an evidenced day.
- What client-side JS renders on the site (api not fetched); RU copy not fully audited.
- Why DeFi Checkup's Railway app disappeared; whether it ever had the Etherscan key; its 15 uncommitted files.
- earn-defi INCIDENT (since 09-19) — lifting is the owner's manual action.
- Original external PDFs (DeFAI ТЗ, «DeFi-архитектура», Kasatkin guide) and the AI1 book are not on disk — only `docs/ideas/2026-09-25-defai-pdf-review.md` and cited excerpts.
- `MATURITY_REGISTER.md` (2026-08-22) is stale; L-levels must be regenerated before citing.
- `com.spa.swarm_health` and `com.spa.site_freshness` exit 1 — cause not investigated.
- Reachability of `s71/s72/s73/s76/s40` strategies at runtime (0 static importers).
