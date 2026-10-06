# RM-TRUTH-01 · A2 — Capital contours (excluding the indicator Trading Lab)

- Auditor: A2 (read-only). Measured: 2026-10-05 ~08:10–08:40 UTC.
- Code/ADRs: `~/Documents/SPA_mirror` @ `b36acda46` (2026-10-05 04:00 +0200). Prod code for
  `investment_cio`, `capital_shadow`, `research_factory`, `defi_engine` is byte-identical to the mirror
  (`diff -rq`, only `__pycache__` differs).
- Live state: `~/Documents/SPA_Claude/data` (mtimes quoted are local CEST = UTC+2 unless written with `Z`).
- Nothing was written outside `scratchpad/rmtruth/`. No launchctl action, no writer, no git mutation.
  The only executed code: read-only `json` parsing, `registry_loader.load_facts` (pure loader),
  `card_acceptance._probe_curated_facts_usable` (pure), `tar -xzO` of one member of a backup to stdout.
- Outcome vocabulary: **MEASURED** · **MEASURED-ZERO** · **NOT MEASURED**. `UNKNOWN_PURPOSE ≠ obsolete`.

---

## 0. Ten findings that matter most (each with its evidence)

1. **The main $100k track is intact and running; 104 evidenced days, anchor 2026-06-22.**
   `data/equity_curve_daily.json` (generated 2026-10-05T06:00:16Z): 136 bars = 20 `warmup` (05-21..06-09)
   + 11 `backfill` (06-10..06-20) + 1 `reconstructed` (06-21) + **104 `cycle`/evidenced** (06-22..10-05).
   Calendar holes: 07-19 and 07-27 (no bar). Realized max DD on evidenced bars −0.0393 %. MEASURED.
2. **The track's two money records disagree on 17 of 88 shared dates (max $55.82, 2026-09-11).**
   Reproduced independently: `paper_evidence.json` vs `equity_curve_daily.json` → exactly 17 dates, all
   ≥ 2026-09-09, worst +55.82 on 09-11. Root cause localized 2026-08-09 in
   `nimbalyst-local/tracker/own-32-evidence-vs-curve-diverge.md` (two writers: `cycle_reporting.py:490`
   vs `cycle_runner.py:2051`); a one-off realignment on 2026-09-09 (journal W37, ADR-283) zeroed it, the
   divergence restarted the same day. Fix is money-path → waits for owner (briefing line 72). MEASURED.
3. **`paper_evidence.json` is not a complete copy of the track.** 88 rows vs 104 evidenced bars:
   missing 06-22..06-29 (8) and **08-03..08-22 (20)**; contains 12 pre-anchor days 06-10..06-21 that the
   curve labels backfill/reconstructed. All 88 rows are tagged `strategy_id: "S7"` = "Diversified Max"
   (`spa_core/paper_trading/strategy_registry.py:266`), which is NOT the book that runs
   (`current_positions.json model_used: optimized_yield`, mandate `conservative-lending-v1`). The 08-03..08-22
   hole already existed in the 2026-09-22 offsite backup (74 rows); cause **NOT MEASURED** (oldest backup
   is 09-22; candidate: the 2026-08-24 `git checkout -- data/` incident, journal W35 #361 — unproven).
4. **Balanced/Aggressive histories were reset twice — both deliberate and recorded.**
   (a) 2026-08-24 owner-approved "clean $100k restart" wiped `daily_history` of the $66k legacy books
   (`hy_cycle.py:190-212`, marker `reseed_100k_done: true`); before that both books had **0 positions for
   918/929 idle cycles** since 06-22 (ADR-125). (b) 2026-10-02 00:55Z re-versioning (ADR-533): 39 rows
   (08-24..10-01) kept but closed as `*-legacy-lending`, classified `DISTORTED` (sleeve-econ-v1 charged
   gas on accrual drift, ADR-531). Current experiments have **4 valid periods** each. `start_date:
   2026-06-22` in both books is therefore misleading (history starts 2026-08-24). MEASURED.
5. **A BACKTEST number sits on the public shelf labelled as a measurement.**
   `landing/src/data/site_numbers.json → packages.conservative.apy = 3.7, kind "замер", annualisation
   "compound from evidenced anchor"`, source `track_snapshot.json → packages`, which is
   `scripts/generate_track_snapshot.py::_tier_packages()` ← `data/tier1_packages.json
   blended_net_apy_pct` = **tier1 backtest** of strategies s61/s27/s62/s77 (`basis: "validated (real-data
   backtest …)"`). No page reads that shelf APY (grep), but `/packages` renders
   `snap.packages.conservative.dd_pct` (= backtest `worst_dd_pct` 0.047 → "0.0%") under the label
   **"Worst drawdown: … realized to date (paper track)"** (`landing/src/pages/packages.astro:92-95`).
   Metric-type mislabel BACKTEST→REALIZED on a public page. Owner subject №2 (public numbers) — report only.
6. **Three different "cumulative return" numbers for the same main track.** 1.526 % (summary
   `total_return_pct`, from $100,000 incl. 32 warmup/backfill bars), 1.3893 % (`real_total_return_pct`, from
   06-22 open), 1.3733 % (`track_ledger.json`/defi_engine, from 06-22 close). `docs/SYSTEM_BRIEFING.md`
   prints "+1.53% over 104d evidenced" — `scripts/update_system_briefing.py:1161,1232` pairs the
   warmup-inclusive return with the evidenced-day count, and defaults to `0.0` on absence (inv. #17).
7. **"Realized" for the new sleeves excludes day 1.** defi_engine `track_realized_apy_net` and
   `cumulative_return_pct` start from the first row's close: Aggressive shows **+0.0685 %** (6.449 %/yr)
   while from the experiment's own `initial_state` (100,260.76 → 100,152.70) it is **−0.108 %**; the entry
   day (cost $64.11, −$176.63) is outside the metric. Balanced −0.0805 % (−7.08 %/yr) vs −0.067 % from
   initial state. MEASURED; definitional, not a bug claim.
8. **Capital Shadow says "no counterparty-risk source exists" as a hard-coded literal**
   (`spa_core/capital_shadow/readiness.py:195-197`) while ADR-560 WP-A05 built
   `research_factory/counterparty_registry.py` (covers factory candidates incl. Ethena; NOT Maple).
   Result: every DeFi sleeve readiness = BLOCKED with `counterparty_evidence: UNKNOWN — BLOCKS_ALL_PILOTS`.
   RECONNECT candidate (partial coverage). MEASURED (code).
9. **Research Factory `PAPER_ACTIVE` (=1, USYC) is NOT used as a system-wide paper count.** Consumers
   (grep, mirror): `investment_cio/research_universe.py` (labelled research universe, non-allocatable),
   `studio_os/mission_control.py` + `mission_ui` (labelled "research"/"Sherlock"). Zero hits in
   `spa_core/telegram`, `scripts/update_system_briefing.py`, `spa_core/owner_remote`, `landing/src`.
   MEASURED-ZERO for misuse (scope: those surfaces).
10. **Many parallel paper ledgers and name collisions** (§6): "Engine B/C" exist twice
    (`hy_paper_trading.json` $100k books vs `strategy_lab_paper/engine_b|c` at $20k/$10k), "Core" means
    Conservative in `tier_paper_rollup.json` but Balanced in ADR-125, `tier_paper_rollup.json` maps
    Balanced/Aggressive to aggressive_lab strategies (not to hy/lp books), `engine_a` ≡ `rwa_floor`
    (identical series), `rates_desk/equity_track.jsonl` is a hash-chained copy of the main curve, tier
    labels exist in **8 measured copies with 8 disagreements, 2 looser on the money path**
    (`defi_engine/status.json tier_authority`).

---

## 1. Contour: DeFi Yield — main $100k paper track ("Conservative")

| | evidence |
|---|---|
| Purpose | Honest 30-day+ paper track → go-live (CLAUDE.md "Что это"). |
| Owner intent → decision | MASTER_PLAN / owner mandates; honest reset to evidenced-only days 2026-06-26 (`git 5036fe542` "operator-approved honest track reset", anchor 06-22); ADR-034/048 kill-switch; ADR-109 displayed DD = gate DD; ADR-298 cost accounting; ADR-533 mandate `conservative-lending-v1`. |
| Implementation | `spa_core/paper_trading/cycle_runner.py` (+`allocator/allocator.py`, `risk/policy.py`, `governance/kill_switch.py`, `paper_trading/cio_arming.py`). |
| Runtime | `com.spa.daily_cycle` (launchd, 08:00 local, `scripts/run_daily_paper_cycle.sh`); `launchctl list` exit 0. |
| Canonical state | `data/equity_curve_daily.json` (track), `data/current_positions.json` (book), `data/trades.json` (34 executed states). |
| Secondary copies | `data/paper_evidence.json` (88 rows, S7 label, diverges 17/88), `data/track_ledger.json` (evidenced-only, 104, cum 1.3733 %), `data/rates_desk/equity_track.jsonl` (hash-chained copy, 104 rows, first close 100150.66 = curve 06-22), `data/paper_trading_status.json` (paper_start 06-10, `days_running` 118), `data/golive_status.json` (104, 29/29). |
| Freshness | curve/positions 2026-10-05T06:00Z; positions: compound_v3 40k, maple 20k, fluid_fusdc 20k, morpho_blue_base 10k, aave_v3 5k, cash 5k. |
| History | 2026-06-22 → 2026-10-05, holes 07-19, 07-27. Clobber 06-27..29 by `git reset --hard` healed from logs (`git 902c1e7c6`, 2026-07-01). Warmup/backfill bars preserved and labelled (not deleted). |
| Lost/damaged | Nothing lost in the curve now. `paper_evidence.json` missing 28 evidenced dates (see §0.3). |
| Known failures | own-32 dual-writer divergence (17/88); archive-replay WARNING 1/27 days (09-11, $50.15) — same date as the max divergence; 3 cumulative-return definitions; briefing mislabels; `S7` label. |
| Go-live | `golive_status.json`: ready True, 29/29, state `gate_passed_owner_decision_pending`, 18 consecutive ready days. CLAUDE.md says `ready_for_live=false` — that field comes from `spa_core/execution/readiness_audit.py`, a different question (custody). Two "ready" notions; not reconciled here. |

## 2. Contour: Balanced (`hy_cycle`) and Aggressive (`lp_cycle`) books

- Lineage: EPIC-1 S1.3 / EPIC-2 S2.2 created both on 2026-06-22 (`git 4f1f98906`, `a39a6abd4`) as "Engine B
  HY" ($66k) and "Engine C LP" ($33k) → ADR-103 (sleeve_book) → ADR-125 (2026-08-23, owner "начинай"/"Гоу B":
  $100k each, continuous deploy) → owner reset 2026-08-24 → ADR-531 (sleeve-econ-v2) → **ADR-533 (2026-10-01)
  mechanics: Balanced = Pendle PT fixed carry, Aggressive = simulated sUSDe/PYUSD Morpho loop** → owner
  2026-10-03 stop reference = current experiment peak.
- Runtime: `com.spa.hy_cycle`, `com.spa.lp_cycle` hourly (StartInterval 3600), exit 0; books written
  2026-10-05 08:02:52Z / 08:03:13Z; `paper_observations/{balanced,aggressive}.jsonl` 82 obs each, 0 missed
  runs/24 h (`defi_engine/status.json packages.*.data`).
- Balanced now: equity 99,488.68; 4 floating legs (maple, morpho_steakhouse, fluid_fusdc, susde) + 1 PT leg
  (PT-sUSDS 26-Nov-2026, cost basis $24,892.20, entry 2026-10-03, implied 4.834 %); drawdown vs experiment
  peak −0.08 % (threshold −8 %); decision "hold: no room within per-market/liquidity limits"; defi_engine
  finding: illiquid share 0.375 > 0.25 policy (advisory).
- Aggressive now: equity 100,155.71; 2 floating legs (maple, fluid_fusdc) + simulated loop (debt
  $116.7k, HF 1.307, entered 2026-10-02T00:55Z); finding: loop mechanic share 0.4998 vs advisory cap 0.10.
  Drawdown vs peak −0.10 % (threshold −25 %).
- `mtm_coverage_pct: 0.0` on both latest rows (floating legs accrued, not marked) — capital_shadow reads
  this as `mark_to_market_evidence: FAIL`.
- Public profile: `/packages` shows status rows from `package_status` (ADR-533/537) — "research targets up to
  6/12/20 %" per `landing/src/lib/tier_bands.json` (owner 2026-10-03: targets only).

## 3. Contour: defi_engine (ADR-532) + package_status read model (ADR-533/537)

- Derived/advisory, `money_path_effect: none`, `live_capital_usd: 0`. Published by the hy/lp CLI after
  each `--run` (`hy_cycle.py:609`, `lp_cycle.py:652`, lazy import, failure printed). Last
  `generated_at` 2026-10-05T08:03:15Z; code_version 7aff5b2fcc5d (sha of package files).
- Readers: `studio_os/mission_control.py`, `studio_os/director_report.py`, `api/routers/v1.py`
  (`/api/v1/packages/status`), `scripts/generate_track_snapshot.py`, `investment_cio`, `capital_shadow`.
- Findings live (status.json): conservative `loss_budget_unbound` (3 % budget vs nearest stop 5 %);
  balanced exit_liquidity 0.375; aggressive mechanic_cap loop 0.4998 / exit 0.250; tier copies looser on
  money path: `aave_v3_base` and `morpho_steakhouse` (policy_enforcer says T1, authority T2).
- Package A–D (ADR-532) still waiting for owner (ADR-533 table).

## 4. Contour: Market-neutral / Basis / Funding

| Item | State (evidence) |
|---|---|
| Canonical funding source | `strategy_lab/data/funding_feed.py` → `data/market_data/funding.json` (generated 2026-10-05T08:13Z), declared "the ONE canonical funding source" in ADR-560. ADR-564: "5 venues fetched, 0 persisted — the stored median is one venue's print". |
| Factory funding candidates | 42 `FUNDING_CAPTURE`: 40 `DATA_INSUFFICIENT`, 2 `SUPERSEDED` (`research_factory/status.json`); top blockers fees_measured / net_return_computable / paper_accounting_feasible (72 each across candidates). Binance/Bybit/OKX fee pages "render only by script" (ADR-564 round 5). → **blocked on fee evidence: CONFIRMED**. |
| aggressive_lab `susde_dn` (S71) | `data/aggressive_lab/susde_dn/realized_series.jsonl`: 915 rows 2024-03-05..2026-10-05; **62 `phase: forward` rows (08-05..10-05), all `mtm_source: realized_backtest_series`, 61 of 62 with identical `mtm_today_pct 0.021092`** → forward rows are backtest replays (confirms ADR-560 "frozen at 2026-07-05"). |
| swarm `blend_forward` | `data/swarm/blend_forward.json` (TRACKING, 62 common days, blend apy 4.1448 %, susde leg 11.99 %) uses the frozen susde_dn leg with `stale_legs: []` — the replay is counted as a forward leg. MEASURED. |
| strategy_lab `variant_n` | LRT + short ETH perp, equity 102,806.66, net 2.8067 % (`strategy_lab_paper/status.json`), series 104 rows from 06-24. CIO reads it as market_neutral strand (relabelled by ADR-560). |
| BTS chain / S_BASIS / S8 / lrt_neutral | SUPERSEDED by ADR-560 (recorded, not deleted). `com.spa.bts-feed`, `com.spa.bts-monitor` listed as **missing** from launchd in the briefing (expected-list drift — a monitor still expects superseded agents). |
| CIO sleeve | `market_neutral_basis`: observe-only, `allocatable=False`, no mandate. |
| capital_shadow | market_neutral_basis NOT_READY, all checks UNKNOWN "research/observe-only — never a pilot candidate". |

## 5. Contour: Treasury / RWA / Cash

- **Cash**: 5 % RiskPolicy floor ($5,000 in the main book) earns 0 % (ADR-554 Phase 0: "no accrual
  anywhere"). Balanced/Aggressive books have no cash field (`defi_engine` books.*.cash_reason).
- **USYC** (Circle/Hashnote, Ethereum `0x1364…9f2b`): `PAPER_ACTIVE`, paper_mode `REFERENCE_TRACK`
  (ledger `paper_admission_v2` + `paper_open` + one `paper_mark`, all at 2026-10-05T01:37:22Z — an off-schedule
  run; the scheduled 07:05Z run added no further mark). `forward_periods 0/30`. Base return 3.06999 %
  MEASURED from DeFiLlama pool 448a64ff (REPUTABLE_AGGREGATOR), net 3.07 % ESTIMATED_WITH_METHOD. The mark
  key is the oracle round of 2026-10-02T12:31:59Z. Evidence ceiling ISSUER_ASSERTED; LEGAL and RESERVES
  UNKNOWN → cannot become CIO_ELIGIBLE (ADR-564). **Internal contradiction in the same record**:
  `counterparty_summary.roles_unknown = [custodian, legal_entity]` (ADR-560 view) vs
  `evidence.counterparties.custodian/legal_entity = IDENTIFIED` (ADR-564 bundle).
- **OUSG** `DATA_INSUFFICIENT`, **USDY** `DATA_INSUFFICIENT`, **BUIDL** `COUNTERPARTY_UNKNOWN`, sBUIDL
  `DATA_INSUFFICIENT` (status.json). ADR-564: NEEDS_MORE_EVIDENCE (fees / net return not computable;
  BUIDL "not feasible with free evidence").
- Other treasury candidates: sUSDS/sDAI `DUPLICATE_EXPOSURE` (held via main book), USTB/USCC/TBILL
  `COUNTERPARTY_UNKNOWN`.
- Older RWA research tracks (still running, advisory): `strategy_lab_paper/rwa_sleeve` (net 3.39 %,
  from 06-26), `rwa_floor` (**identical series to `engine_a`**: equity 100972.534829, net 3.413223),
  `rwa_floor_curve.json` (102 points, 2026-10-05T03:50Z), `rwa_safety_board.json` (11 assets,
  `com.spa.rwa_safety_board` 05:50). These are not linked to the factory's USYC paper position (separate
  ledgers for the same asset class).

## 6. Duplicates and name collisions (all MEASURED unless marked)

| Class | Copies |
|---|---|
| Main-track money records | `equity_curve_daily.json` (canonical) · `paper_evidence.json` (88, S7, 17 diverge) · `track_ledger.json` · `rates_desk/equity_track.jsonl` · `paper_trading_status.json` · `golive_status.json` · `landing/src/data/track_snapshot.json` (as_of 10-02) · `site_numbers.json` (measured 10-01). |
| Paper ledgers (all running) | main book; hy/lp books; `aggressive_lab` (10 strategies, OUTSIDE_RISKPOLICY); `strategy_lab_paper` (12); `rates_desk/paper`; `swarm/blend_forward`; `swarm/eyc_allocator` (shadow); `shadow_paper_trading.json` (tournament top-5, 170 strategy-rows with `strategy_id: "unknown"`); `paper_evidence_history.json` (CPA evidence, from 08-23); `research_factory/ledger.jsonl` paper legs; `capital_shadow/ledger.jsonl` shadow fills; `investment_cio/ledger.jsonl`. Three hash-chained ledgers (cio, shadow, factory) — ADR-560 records the shared helper `utils/hash_ledger.py` migration as debt. |
| Strategy registries / ids | `paper_trading/strategy_registry.py` (S0–S10, S22–S25, S_BASIS); `strategies/strategy_registry.py` (StrategyMeta REGISTRY); `data/strategies/s0..s5*.json` (2026-06-20, frozen); tier1 backtest ids (s27, s61, s62, s77 in `tier1_packages.json`); tournament ids (s7_pendle_yt_aggressive, s12, s5, s2, s53 in `shadow_paper_trading.json` — `s7_…` ≠ registry `S7`); `strategy_mandates.py` (3 mandates, ADR-533); `defi_engine/mechanics.py` (14 mechanics); research_factory candidates (89) + `contract.MECHANISMS`; `trading_research` candidates (138, out of slice). |
| Tier labels | 8 copies measured by `defi_engine/tiers.py` (adapter_class, canon, data_registry, metadata, orchestrator_live, policy_enforcer, polled, registry), 8 disagreements, 2 looser on money path. ADR-510 (§71) counted 5 copies of the tier label in the trades census; ADR-486: 4 executed states T016–T019 (2026-08-27) held 40 % in morpho_steakhouse vs 20 % T2 cap because of a label copy. *(The brief cited ADR-484 for "5 copies"; ADR-484 is CIO economics — the 5-copies count is ADR-510, the bypass is ADR-486.)* |
| Package naming | Conservative = "Preserve" (alt) = "core" in `tier_paper_rollup.json` = `S7` in paper_evidence = `optimized_yield` model = `conservative-lending-v1`. Balanced = "Core" (ADR-125) = "Engine B HY/Carry" = `balanced-fixed-carry-v1`; `tier_paper_rollup.json` instead maps Balanced → {lrt_neutral, susde_dn, susde_spot} target "10-12%" headline 8.7 and Aggressive → 5 aggressive_lab strategies target "15-20%" headline 14.4 (`scripts/tier_paper_rollup.py`, run by `agent_aggressive_lab.sh:20`). Readers of `tier_paper_rollup.json`: none found outside its writer (grep). |
| Engine names | `strategy_lab_paper` `engine_a` ($100k), `engine_b` ($20k, "HY/carry"), `engine_c` ($10k, "LP") — the pre-ADR-125 HY 2 : LP 1 split, still running hourly and `is_advisory: False`, alongside the $100k hy/lp books with the same engine names. |
| Regime classifiers | four (ADR-554 G: `market_regime.json`, `hy_regime_log` proxy, `swarm/funding_regime.json`, trading `regime.py`); `hy_regime_log` still refreshed by hy_cycle (`refresh_hy_regime`) with proxy inputs. |
| Counterparty views | capital_shadow literal "none exists" · factory `counterparty_registry.py` · ADR-564 evidence bundles (disagree inside the USYC record). |

## 7. Investment CIO "Oracle" (ADR-554, ex-«Штирлиц»)

- `architecture/roles.json`: `chief_investment_officer`, display_name **Oracle** (ADR-554 text still says
  «Штирлиц»), authority NONE. Related pre-existing authorities kept separate: `cio_arming` PAPER_VETO
  (HOLD in 952/952 decisions per ADR-554 Phase 0), `investment_os/directive.py` PAPER_BRAKE,
  `chief_investment` ADVISORY_INPUT_TO_BRAKE (`com.spa.io_chief_investment` hourly).
- Runtime `com.spa.investment_cio` daily 09:30 local; `data/investment_cio/ledger.jsonl` **2 entries**
  (2026-10-04, 2026-10-05), anchors 2 (`data/investment_cio_anchors/anchors.jsonl`, local sibling — capital
  shadow flags "no off-host publication").
- Latest (2026-10-05T07:30:02Z): stance **INSUFFICIENT_EVIDENCE**, `recommended_weights {}`, confidence LOW,
  only defi_conservative eligible (MATURE, realized 4.9032 ≥ hurdle 3.6); balanced/aggressive IMMATURE 4/30;
  market_neutral_basis & trading_research observe-only; `evidence_cutoff_complete: false` (susde_dn series
  7.5 h old). No outcome measurement yet (horizons 7/30 d, ledger 1 day old). Readers: mission_control,
  capital_shadow.

## 8. Research Factory (ADR-560) + Sherlock evidence (ADR-564)

- Runtime `com.spa.research_factory` 09:05 local; last run 2026-10-05T07:05Z; integrity OK; ledger
  11.9 MB, kinds: evidence_observation 3424, transition 338, candidate_snapshot 214, evidence_bundle 179,
  admission_decision 179, admission_v2_report 179, run 5, paper_* 3 — **history starts 2026-10-04T13:22Z**.
- Denominators: scanned 17,102 · discovered 89 · paper_active 1 · cio_eligible 0 · observe_only 5 ·
  rejected 0. ADR-560/memory quoted 49 → 73 candidates; now 89 (growth, not a contradiction).
  9 candidates have `mechanism_id: null` (DATA_INSUFFICIENT) — third outcome, named.
- Sherlock facts: `load_facts` → **43 usable / 13 refused** (all 13 "reviewed_by is required"), matches
  ADR-564 round 5 "43 of 56"; probe `curated_facts_usable:fact-043..fact-055` → satisfied. MEASURED.
- `domain_decisions`: CASH_TREASURY / MARKET_NEUTRAL_BASIS / RWA_STABLE_YIELD / DEFI_DISCOVERY BUILD_NOW,
  TRADING_RESEARCH PROJECT_ONLY, EQUITIES/OPTIONS ARCHITECTURE_ONLY.

## 9. capital_shadow RM-LIVE-01 (ADR-556)

- `com.spa.capital_shadow` daily 09:45 local; ledger 176 entries 2026-10-04T06:13Z → 2026-10-05T07:45Z
  (transition 84, intent 36, simulation 24, shadow_fill 12, readiness 12, reconciliation 8); 24 simulation
  files; anchors 19 KB local.
- Readiness 2026-10-05: defi_conservative/balanced/aggressive **BLOCKED** (were NOT_READY on 10-04; same
  failing gates → change of display state, cause NOT MEASURED), cash / trading_research /
  market_neutral_basis NOT_READY. Failing gates (conservative): risk_evidence (depeg NOT_MEASURED),
  protocol_evidence (fluid_fusdc, maple, morpho_blue_base default-graded), counterparty UNKNOWN (literal),
  mark_to_market, reconciliation (no reconciliation rows on 2026-10-05; last 2026-10-04T07:45Z),
  execution_simulation + unwind (maple not simulatable), offhost_anchor, kill_switch_clear
  (`kill_switch_status.json` state CLEAR_PARTIAL — red_flags fallback, 4 non-live flags). Owner decisions
  pending: 4 (custody Safe, go-live, live admission, pilot amount).

## 10. Lost / surviving histories (summary)

| History | Status |
|---|---|
| Main curve 06-22→10-05 | SURVIVING, complete except 07-19, 07-27 (no bar). Pre-anchor warmup/backfill labelled, kept. |
| Main curve 06-27..29 | LOST then RECOVERED from cycle logs (`git 902c1e7c6`). |
| `paper_evidence.json` 08-03..08-22, 06-22..06-29 | MISSING (28 dates); cause NOT MEASURED; existed already in 09-22 backup. |
| hy/lp books 06-22→08-23 | RESET by owner 2026-08-24 (0 positions in that period; seed $66k/$33k). Not recoverable from git (only 06-22 commits). |
| hy/lp 08-24→10-01 | SURVIVING as closed `*-legacy-lending` experiments (39 rows, DISTORTED v1 economics). |
| `shadow_paper_trading.json` | created 06-22, daily_results start 2026-08-23 — earlier rows absent; cause NOT MEASURED. |
| `paper_evidence_history.json` (CPA) | initialized 06-10, rows start 2026-08-23 — earlier rows absent; cause NOT MEASURED. |
| susde_dn forward | ROWS SURVIVE but are replays (not forward evidence). |
| Factory / CIO / shadow ledgers | SURVIVING, young (from 2026-10-04). |
| `data/` 116-file rollback 2026-08-24 | 114/116 restored from 08-23 backup; 19.5 h window lost for 114 files; `swarm/dwell_hysteresis_status.json`, `statements/2026-06.json` lost (journal W35 #361). |

## 11. UNKNOWNs (named, not guessed)

1. Why `paper_evidence.json` lacks 08-03..08-22 and 06-22..06-29.
2. Why `shadow_paper_trading.json` and `paper_evidence_history.json` start on 2026-08-23.
3. Why capital_shadow DeFi sleeves moved NOT_READY → BLOCKED between 10-04 and 10-05 with the same failing gates.
4. Who ran the factory at 2026-10-05T01:37Z (not the launchd slot 07:05Z) — likely the ADR-564 delivery session; not verified.
5. Whether `tier_paper_rollup.json` has any reader (none found by grep in spa_core/scripts/landing) → UNKNOWN_PURPOSE.
6. Whether `strategy_lab_paper` engine_a/b/c are read by anything that treats them as the real books.
7. Swarm blend "rates" leg source (0.79 % over 62 d) — not traced in this slice.
8. `/api/tier1/packages` live values that override the static fallback client-side — not fetched (network not used).

## 12. Recommended actions (no action taken; owner-subject items flagged)

- REPAIR (money-path, owner): own-32 dual writer of the track; `S7` label in paper_evidence.
- REPAIR (owner subject №2): `/packages` conservative tail label (BACKTEST shown as "realized"), shelf
  `packages.*.apy kind: замер` for a tier1 backtest; briefing "+1.53 % over 104d evidenced".
- RECONNECT: capital_shadow counterparty gate → factory counterparty registry (plus a Maple source).
- RECONNECT/REPAIR: swarm blend_forward should mark the frozen susde leg stale (ADR-560 already labels it in the CIO).
- MERGE: rates_desk equity_track copy, track_ledger, paper_evidence → one derived view of the curve;
  `engine_a`/`rwa_floor` alias; strategy_lab engine_b/c vs hy/lp books naming.
- SUPERSEDED/UNKNOWN_PURPOSE: `tier_paper_rollup.json` (conflicting package mapping, no reader found),
  `data/strategies/s0..s5` (frozen 06-20), `strategy_summary.json`/`strategy_configs.json` (frozen June).
- KEEP: equity_curve_daily, hy/lp books + experiments, defi_engine, investment_cio, research_factory, capital_shadow.
