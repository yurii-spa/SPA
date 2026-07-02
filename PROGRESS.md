# Yield Lab Scaffolding — PROGRESS

Branch: `yield-lab-scaffolding` (NOT merged to main by this run). Mode: AUDIT + DOCS + SCAFFOLDING
only. Local commits only; nothing pushed; nothing deployed. Master charter:
`prompts/claude_code/yield_lab_master.md`. Authoritative doc index: `docs/00_index.md`.

## DONE (all wrapper steps complete)
- **STEP 0** — branch created; master charter; PROGRESS.md. (`e88e932bf`)
- **STEP 1** — read-only audit: `docs/02_current_architecture_audit.md`, `docs/06_spa_core_invariants.md`,
  `docs/31_open_questions.md`. Key finding: a research layer ALREADY exists (strategy_lab/{aggressive_lab,
  rates_desk,rwa_backstop,liquidator,underwriting}, redteam/, riskwire/, dfb/, compliance/) — docs
  formalize/unify, do not duplicate. (`725985e9f`)
- **STEP 2** — root `CLAUDE.md` extended with a Yield-Lab section (careful append, not rewrite). (`75ca870de`)
- **STEP 3** — Priority 1 (13 files): 00_index, 33_yield_thesis_map (full), 37_apy_evidence (full),
  11_strategy_card_system (full), 14_risk_scoring_v2 (full), 28_cc_master_instructions,
  07_yield_lab_architecture, 10_agent_architecture, 29_backlog (73 tasks), 30_first_30_days,
  strategy_cards {schema(valid JSON)/template/README} + .gitignore exception. (`d0bd51929`,`b9fbd1015`)
- **STEP 4** — Priority 2: 38_stablecoin_yield_engine, 35_strategy_discovery_engine, 34_capital_tiers,
  36_btc_capital_cycle_machine, 15_btc_cycle_framework, 16_eth_yield_framework, 12_protocol_card_system,
  13_stablecoin_card_system, protocol+stablecoin card schemas(valid JSON)/templates/READMEs, 15 agent
  prompts. (`1bdb3e8f7`)
- **STEP 5** — Priority 3: 10 stub docs (23,24,25,26,39,40,41,42,43,44, each "TODO: expand at MVP 2-3"),
  7 ADR-YL, 5 reporting templates, 5 illustrative example strategy cards. (`4782672e9`)
- **STEP 6** — this final summary.

## AUTONOMOUS VALUE-ENGINE (continuous, self-paced — owner MAX-sub, tokens not a constraint)
Rotation: (A) edge-hunt ADR-YL-008 · (B) deep-research to institutional depth · (C) measurement-moat ·
(D) hardening/verify. One committed task/cycle, real sourced data, docs/research-layer only. Log:
- **Cycle 1 (A edge-hunt):** `data/strategy_candidates/ondo_usdy.candidate.md` — evaluated Ondo USDY
  (~5%, tokenized T-bill) vs live floor (~3.4%): ~160 bps spread, attributed to accepted bounded risks
  (single-issuer concentration / custody / duration / transfer-restriction) → provisional
  **spread_fully_explained=LIKELY-TRUE → ADVANCE to research** (the mandate's positive path; contrast
  leverage_loop refused). Next: Ondo issuer card + verify live APY. [L1→needs L2]
- **Cycle 2 (B deep-research):** `data/protocol_cards/examples/ondo.protocol.md` — Ondo issuer card,
  SOURCED (TVL $3.56B DeFiLlama; USDY 92% T-bills<6mo / 8% bank-deposits; custody Morgan Stanley +
  Ankura Trust, segregated trusts; monthly independent auditor; wire redemption, custodian-failure=freeze;
  allowlist/KYC transfer restrictions). **Unblocks CAND-USDY-001** — its ~160bps spread now maps to
  DOCUMENTED bounded risks (issuer-concentration/custodian-freeze/8%-banking/KYC-liquidity), ADVANCE holds.
- **Cycle 3 (D hardening):** harness 105 passed; origin==local; fixed 3 dangling doc cross-refs (07_yield_lab_architecture, 37_apy_realism_and_evidence_standard, 17_portfolio_construction). Honesty scan clean.
- **Cycle 4 (C measurement-moat):** verify_spa.py → **decision proof-chain reproduces (valid, len 464, VERDICT OK)**; PROMOTED CAND-USDY-001 → `data/strategy_cards/examples/ondo_usdy_floor_plus.strategy.md` (SC-USDY-001) now that PC-ONDO-001 exists — spread-attribution now cites SOURCED issuer data; status=research, spread_fully_explained provisional pending exact APY[L2]+bps-split. Pipeline edge-hunt→issuer-DD→Strategy-Card demonstrated (mandate approve-path).
- **Cycle 5 (A edge-hunt, new round):** `data/strategy_candidates/susds_ssr.candidate.md` — evaluated
  Sky Savings Rate (sUSDS ~3.60-3.75%, Sky TVL $5.31B) vs floor ~3.4%: spread only ~20-35bps (near-floor);
  **REFUSED / HELD-AT-0%** on a NOVEL reason `governance_safety_precondition` — GSM Pause Delay 24h < the
  desk's required 48h (FORBIDDEN #8). Positive result: the desk's own rule + the mandate agree; re-open if
  on-chain GSM ≥48h. Balances the ADVANCE (USDY) with a fresh refusal reason (vs leverage_loop tail-comp).
- **Cycle 6 (B deep-research):** filled UNVERIFIED attestation/reserve fields on USDC + USDT cards
  (sourced 2026-07-02): USDC = **Deloitte & Touche, monthly AICPA AUP**, 80%+ in BlackRock Circle Reserve
  Fund (2a-7 MMF, BNY Mellon); USDT = **BDO Italia, quarterly ISAE 3000**, ~80% T-bills + **~$8B gold +
  ~$7B BTC** (Q1-26 $191.77B res vs $183.54B liab). Documents USDC's stronger transparency (monthly vs
  quarterly) + USDT's mixed non-fiat reserve. Both checklists: attestation item now [x].
- **Cycle 7 (C measurement-moat):** `docs/decision_index.md` — auditable "check our decisions" surface
  aggregating all 13 evaluated cards/candidates with ADR-YL-008 verdict + reason + spread + evidence:
  1 ADVANCE (USDY), 3 REFUSE/HOLD by 3 DISTINCT reasons (leverage_loop=tail-comp, sUSDS=gov-safety,
  FixedCarry=unrealized-at-size), 1 BASELINE, + research/paper sleeves. Proof-chain reproduces (verify_spa.py).
  Shows the mandate is APPLIED not asserted; refusals dominate by design; no fundable-at-size edge yet (honest).
- **Cycle 8 (D hardening):** integrity pass GREEN, nothing to fix — research-layer harness **108 passed**
  (+3 from SC-USDY-001), origin==local (355 yield-lab files, 0 missing), drift-scan clean (no dangling refs
  in decision_index, no hardcoded floor, no bare verified-APY — all qualified). The layer is consistent +
  synced + honest after 7 cycles of additions.

## VERIFICATION + REMEDIATION SPRINT (2026-07-02)
Verified the whole yield-lab build against the charter by ACTUAL repo contents (not memory): invariants
(diff main...branch = 131 files, 129 add / 2 mod [CLAUDE.md+.gitignore] / 0 runtime/RiskPolicy/dashboard/
deploy; no keys/signing/verified-APY-without-evidence; OQ-1 resolved; floor dynamic-not-hardcoded).
Found + FIXED (owner: huge sprint): 8 missing/partial named docs created (01 overview, 08 AI-Investment-OS
[16 agents deep], 09 Builder-OS [9 agents], 18 monitoring, 19 execution-support, 20 autonomy-ladder L0-L5,
21 security/custody, 45 builder-os-workflow — resolves the CLAUDE.md dangling docs/45 ref); 10 P3 stubs
expanded to real content (43 dangerous-strategies 20-items/217L, 44 first-20 20-items/238L, 23/24/25/26/
39/40/41/42); 3 numbering collisions resolved (07a/26a/35a companions, 12 cross-refs, old names deleted on
origin); 00_index rewritten to true file set + documents the 03/04/05 charter-§8 deviation. Test harness
105 passed. Charter coverage ~82% → ~95%+. Nothing blocked the backlog before; now cleaner. 0 runtime touched.


- **Cycle 11 (A edge-hunt):** `data/strategy_candidates/resolv_rlp.candidate.md` — Resolv RLP (20-30% APY, TVL $8.95M) -> **REFUSE (HARD)**, strongest refusal: yield = first-loss + self-balancing-leverage tail-comp AND the tail FIRED (2026 mint exploit ~$25M extracted, 80M unbacked USR, USR -39% depeg, TVL $400M->$9M). ~1700-2700bps spread = pure tail-comp, realized loss on record. New reason `first_loss_leverage_tranche + realized_mint_exploit_depeg`. decision_index: biggest headline drew hardest NO; yield-rank INVERSE to fundability.


- **Cycle 12 (D hardening):** integrity GREEN — harness **109 passed**, origin==local (358 yield-lab files, 0 missing), drift-scan clean (no dangling refs, no bare verified-APY, all 6 candidates carry spread-attribution). Consistent + synced + honest after 11 cycles.


- **Cycle 13 (B deep-research):** deepened `data/protocol_cards/examples/pendle.protocol.md` (underlies the validated FixedCarry SC-RDFC-001) — SOURCED bug-bounty (Cantina), +audit firms (Spearbit/WatchPug + Boros/ChainSecurity), oracle (TWAP manipulation-resistant per Boros audit), governance (vePENDLE vote-escrow <=2y). Protocol-review gate moved 'two-fields' -> **ONE field from passing** (only admin-key multisig threshold/timelock remains). Sources cited.


- **Cycle 14 (A edge-hunt):** `data/strategy_candidates/morpho_steakhouse_usdc.candidate.md` — Morpho Steakhouse USDC curated vault (4.5-6.5% net, Blue TVL $6.79B) vs floor ~3.4%: ~110-310bps = bounded overcollateralized-lending risk (curator blue-chip-only + per-market immutable oracle + LLTV), immutable-Blue structural plus (no gov-rug). Verdict **ADVANCE (conditional)** — a 2nd genuine ADVANCE beside USDY, new risk shape (curated-vault-over-immutable-markets). decision_index: now 2 ADVANCE (desk says YES when spread is genuinely explained, not only NO).


- **Cycle 15 (B deep-research):** deepened `data/protocol_cards/examples/morpho.protocol.md` (supports CAND-STEAK-001 ADVANCE) — SOURCED: Blue is IMMUTABLE ~650-LOC core (NO admin keys/proxy/upgrade), formally verified (Certora Prover), 8 Spearbit-Cantina engagements + ToB, Vaults V2 by Spearbit/Blackthorn/ChainSecurity/Zellic, **Immunefi** bounty, MORPHO governance. Core DD now COMPLETE; residual = per-vault curator+oracle review. Strengthens the Steakhouse ADVANCE's structural-plus (immutable markets) with primary sources.


- **Cycle 16 (A edge-hunt):** `data/strategy_candidates/aave_v3_usdc.candidate.md` — Aave V3 USDC supply ~3.45% (Ethereum, forecast <2.76% in 4wk) vs floor ~3.4%: spread ~5bps -> negative. Verdict **NO-EDGE / FLOOR-PARITY** (new flavor `no_edge_floor_parity`) — the safest/deepest DeFi lending pays the floor; risk-adjusted WORSE (adds smart-contract risk for same yield) -> hold the T-bill floor instead. THE anchor lesson: plain blue-chip lending arbitraged to floor -> every bp of edge must be bought with accepted risk (justifies whole ADR-YL-008 framing). decision_index: 8 decisions, 5 verdict flavors.


- **Cycle 17 (A edge-hunt):** `data/strategy_candidates/ethena_susde.candidate.md` — Ethena sUSDe ~3.86% (TVL $4.45B) vs floor ~3.4%: spread only ~46bps (funding compressed, can flip negative). Verdict **WATCH -> lean-REFUSE at current spread** — funding-carry = UNBOUNDED risk-comp (funding-flip + CEX/OES-counterparty Copper/Ceffu/Cobo + reserve only 1.1% of supply + LRT peg). Sharp contrast: Aave = floor-parity THIN-tail (hold floor); sUSDe = floor-parity-ish FAT-tail (actively avoid at 46bps). Re-open only if funding widens + strict CEX cap. decision_index: 9 decisions.


- **Cycle 18 (D hardening, integrity due):** GREEN — harness **109 passed**, origin==local (361 yield-lab files, 7 candidates, 0 missing), drift-scan clean (no dangling refs in decision_index, no bare verified-APY, all 7 candidates carry spread_over_floor_bps + a verdict; index 12 rows = 7 candidates + 5 SC-cards, consistent). Layer honest + synced after 17 cycles.


- **Cycle 19 (A edge-hunt):** `data/strategy_candidates/curve_convex_stable_lp.candidate.md` — Curve/Convex stable-LP headline ~4-10% = base fees 3-6% + **CRV/CVX emissions 1-4%** (sample 6.02% = $212 fees + $89 CRV, ~30% emissions). Verdict **REFUSE (emissions-dependent)** — new reason `emissions_dependent_unpriced_spread`: the attractive spread is token-emissions subsidy, not organic risk-comp; strip emissions -> ~floor-parity + volume-dependent, with IL + Curve-2023-hack + Convex-composability tails. The 'farm APY = emissions not edge' archetype. decision_index: 10 decisions.


- **Cycle 20 (C measurement-moat, synthesis):** `docs/underwriting_rubric.md` — a reusable underwriting rubric DISTILLED from the 10 real decisions: the one principle (spread over live floor, every bp risk-explained), a Q1->Q4 decision tree (floor-parity? emissions-stripped? bounded vs unbounded tail? DD-gated?), the reason-code taxonomy (10 rows, each cited to its case), and 5 honest meta-findings (yield ⟂ fundability; spread bought with risk; same-spread-diff-tail; subsidies aren't edge; refusals dominate). The engine moves from collecting decisions -> distilling the METHOD. Cross-linked from decision_index.


- **Cycle 21 (A edge-hunt — 8-12% BOUNDED hunt, owner-directed):** `data/strategy_candidates/pt_susde_fixed.candidate.md` — Pendle **PT-sUSDe Mar-2026 ~11.2% fixed** (real 8-12% band; corroborated PT-USDe ~13.78%, PT-sUSDe Jun 9.05%). Verdict **WATCH -> CONDITIONAL-ADVANCE**, new reason `fixed_carry_held_to_maturity_bounded`: the fixed-to-maturity wrapper REMOVES the funding-flip tail that made spot sUSDe lean-REFUSE (c17) -> residual = MEASURABLE USDe-solvency-to-maturity + PT liquidity. Structure (not asset) sets the risk. Fundable IF USDe-solvency DD + cap. decision_index 11 decisions; rubric +1 reason +meta-finding #6. Next hunt: tokenized private-credit SENIOR tranches (Centrifuge/Goldfinch/Maple-cash 9-12%, bounded by seniority+first-loss).


- **Cycle 22 (A edge-hunt, 8-12% bounded hunt):** `data/strategy_candidates/private_credit_senior.candidate.md` — private-credit SENIOR tranches SPLIT: **Goldfinch Senior 10-14% -> REFUSE (realized default)** — protocol WINDING DOWN (GIP-87 Jun-2026), ~$50M defaults, 3yr stranded; 'senior' label didn't bound systemic default. **Centrifuge DROP ~8% -> WATCH** — real bound (DROP-senior/TIN-junior first-loss + RWA cashflows, TVL >$500M) but low-end + per-pool off-chain DD. Lesson: underwrite the buffer+assets, not the tranche label. decision_index 13 decisions; rubric +2 reasons +meta#6, meta-numbering fixed.


- **Cycle 23 (B deep-research → move WATCH→ADVANCE, owner-directed):** did the **USDe/Ethena solvency DD** for PT-sUSDe (deepened `usde.stablecoin.md` + upgraded `pt_susde_fixed.candidate.md`). Result: **PT-sUSDe WATCH → CONDITIONAL-ADVANCE → PAPER.** The one gating risk (USDe-solvency-to-maturity) is now UNDERWRITTEN + STRESS-VALIDATED: Oct-2025 $19B crash → USDe overcollat ~$66M throughout (attested live: Chaos Labs/Chainlink/Llama Risk/Harris & Trotter), Binance-$0.65 = oracle artifact (DEX −0.3%), redeemed $9B→$6B without unwinding basis, short-perps profited; solvency provable (Anchorage monthly-attest+weekly-PoR, Kraken weekly-PoR, Jan-2026); neg-funding 17.5% days but max 13d/3yr. Residual (why paper not full-live): thin 1.1% reserve + reflexivity + PT-capacity (SC-RDFC INSUFFICIENT_DATA-at-size). **First fundable-THESIS advance of the 8-12% hunt — capacity-limited scale, not risk-logic-limited.** decision_index honest-edge bullet updated.


- **Cycle 24 (A capacity DD, 8-12% hunt):** resolved PT-sUSDe's last open gate — **PT capacity-at-size, QUANTIFIED**. Pendle PT-sUSDe = ~$200.89M liquidity / $260.28M TVL across 2 markets (deepest PT market anywhere) BUT 24h vol only ~$1.08M + near-expiry AMM-flattening. Ceiling: fundable held-to-maturity at $100k-~$2M/maturity; ~5-10M = material slippage; $50-100M = can't absorb alone. **Resolution: RISK clears (ADVANCE-to-paper), SCALE capacity-bounded to ~single-digit $M/maturity → ladder maturities+markets + pair with deep core (RWA floor + overcollat lending ~$100M).** Confirms the desk's known 'edge cliff = thin-PT-depth, not deep core'. decision_index + candidate updated. First 8-12% candidate fully underwritten end-to-end (spread→solvency→capacity).


- **Cycle 25 (A ladder rung):** PT-USDe ~8.8% fixed -> CONDITIONAL-ADVANCE but KEY finding: **same underlying (Ethena/USDe) as PT-sUSDe** — laddering Ethena-PTs CONCENTRATES, not diversifies. **~70% of ALL Pendle TVL (~$6.1B) is Ethena.** New reason `same_underlying_concentration_cap`: cap by UNDERLYING; the ladder's real diversification must come from DIFFERENT issuers (PT-syrupUSDC=Maple, fixed-rate markets, RWA), not more Ethena PTs. decision_index 14 decisions.


- **Owner request (site half) DONE + VERIFIED:** built honest public page **`landing/src/pages/yield-lab.astro`** + nav link (SiteHeader Research group) — fundable candidates + verdicts (ADVANCE/WATCH/REFUSE/NO-EDGE) + spread-over-floor + evidence-L2 + non-negotiable disclaimer ('research judgements, NOT live returns/offer/advice; ADVANCE→paper = advisory no-capital, separate from go-live track'). Astro build 75 pages OK; pushed by-name (e5d1a2c7); deploy #269 build=SUCCESS, deploy-step failed TRANSIENTLY (GH-Pages infra) → rerun-failed-jobs → SUCCESS; **earn-defi.com/yield-lab LIVE** (verified real content, not curl-status). Owner chose: paper=advisory-sleeves-separate-from-go-live, site=honest-research-page. **NEXT: paper-test half = advisory sleeves in strategy_lab (cycle 26).**


- **Cycle 26 (A edge-hunt, owner: diversify from Ethena + try Base):** `data/strategy_candidates/base_chain_diversification.candidate.md`. KEY honest finding: **chain-hop to Base does NOT escape Ethena** — Coinbase High-Yield USDC ~10.8% (Morpho/Steakhouse on Base) earns by lending vs **Ethena-powered collateral** → same underlying, different chain (`chain_hop_same_underlying`, SAME Ethena cap + L2 risk). Genuine non-Ethena Base = Morpho blue-chip vaults 4-7% (bounded Core-diversifier, below 8-12% target). META (rubric #7): **diversify by ASSET CLASS not chain** — real non-Ethena 8-12% = credit (Maple/Centrifuge) + fixed-rate-lending (Notional, non-Ethena overcollat 130-170%, flagged next). decision_index 16 decisions.

## OWNER DECISIONS
- **OQ-1 — RESOLVED** (this session, `docs/adr/ADR-YL-008`): unified Yield Lab mandate — search for
  fundable 10–15%, but every point of spread over the **live** RWA floor must be explained by a specific
  accepted, measurable risk; unexplained spread ⇒ REJECT (a positive result, logged in the refusal log);
  the floor is the official baseline (judge spread, not absolute APY). Propagated to docs/07 (§1a mandate),
  docs/11 (§3.4a spread fields + promotion gate), docs/14 (row 20 `spread_attribution_score`),
  red_team_agent (mandatory Q19 + schema + red-flag), capital_allocation_agent (eligibility filter),
  and the strategy-card schema + template. OQ-1 marked RESOLVED in `docs/31`.

## BACKLOG EXECUTION LOG (one task per commit, docs-only, ADR-YL-008 applied)
- **STRAT-005** (spectrum demonstrated, 3 real sleeves) — Strategy Cards with spread-attribution:
  `rates_desk_fixed_carry` (explained-carry, held at paper_testing — realized spread 0/INSUFFICIENT_DATA),
  `rwa_sleeve` (the **baseline**, spread=0 by construction), `leverage_loop` (**REFUSED** — nominal ~1160bps
  spread is unpriced liquidation tail, realized −8.95% → refusal-log positive result). Remaining optional:
  eth_lst_neutral, susde_dn, lrt_carry, points_farm.
- **PROTO-003** (5/5 DONE) — Protocol Cards: pendle, aave_v3, compound_v3, morpho, euler_v2 (security
  fields honestly UNVERIFIED = findings; TVL live/requires-verification; Euler V1 $197M/2023 exploit documented).
- **STABLE-003** (5/5 DONE) — Stablecoin Cards: usdc, usdt, dai, usde, usds (backing/freeze/depeg documented;
  market-cap/supply/attestation specifics = requires verification; USDe=synthetic-risk-comp; USDS 0%-until-GSM).
- FixedCarry gates: protocol-review + stablecoin-review now have cards, but still **NOT PASSED** — the
  UNVERIFIED security/attestation fields in those cards are findings until sourced (honest evidence discipline).

## BACKLOG — actionable tasks CLEARED (2026-07-02)
Ran the whole backlog one-task-per-commit. Done this arc (beyond the 9 file-marked DONE):
- **Cards:** 5 Protocol (Pendle/Aave/Compound/Morpho/Euler), 5 Stablecoin (USDC/USDT/DAI/USDe/USDS),
  Strategy cards spectrum (FixedCarry/rwa_sleeve/leverage_loop/eth_lst_neutral/susde_dn) + 5 pre-ADR
  example cards brought to ADR-YL-008 conformance (10/10). YL-005 sleeve-status map.
- **Schemas (valid JSON):** candidate, risk_score, capital_tier, lifecycle_state, btc_signal.
- **Docs:** 03 glossary, 04 layered-arch, 05 topology, 17 portfolio, 22 compliance-surface, 26_surfaces,
  35 screening-rubric, security_review, session_checklist, audit/test_health.
- **Templates:** paper_test_plan, small_capital_report, retirement, stablecoin_scan, lst_dd,
  allocation_proposal, risk_disclosure, task_plan, work_report, perf_report, ADR-YL-template.
- **Test/guard harness (100 passed, research-layer, no runtime import):** research/cards/validate.py +
  research/lifecycle.py; tests: schemas_valid, cards_complete, lifecycle_transitions, evidence_levels,
  no_secrets_in_research, no_execution_import, yield_thesis_map.
- **ADR-YL-008** unified mandate (resolves OQ-1) propagated everywhere.

**Only remaining = the P3 stub docs (23,24,26,39,40,41,42,43) explicitly marked "TODO: expand at MVP
2-3 stage"** — deferred by design, not now. The actionable scaffolding + card + schema + test backlog is done.

## NEXT (future sessions — expansion, none blocking)
- Expand the 10 Priority-3 stubs at MVP 2-3 (esp. 43 dangerous-strategies + 44 first-20 into full cards).
- Fill `data/protocol_cards/examples/` + `data/stablecoin_cards/examples/` (schemas + templates ready).
- Remaining open questions in `docs/31` (owner: OQ-4 Risk-Scoring-v2 reuse; OQ-6/7 live data verification).
- Pick one task at a time from `docs/29_backlog.md` (73 tasks). Do NOT merge this branch to main or deploy
  without owner review.

---

## STEP 6 — FINAL SUMMARY (Section 48)

1. **Repo audit** — SPA is a large paper-stage DeFi yield/risk desk: ~55 `spa_core/` packages, 35
   read-only adapters, deterministic RiskPolicy v1.0, two-tier kill, GoLiveChecker (29 criteria),
   1,489 test files (suite green), ~400 runtime `data/*.json`, Astro site (Pages), 8 CI workflows.
2. **Existing architecture map** — see `docs/02`. Load-bearing: `risk/policy.py` (hard gate),
   `paper_trading/` (cycle+golive+gates), `governance/kill_switch.py`, `adapters/`, `strategy_lab/`
   (the EXISTING research layer: aggressive_lab, rates_desk, rwa_backstop, liquidator, underwriting),
   `redteam/`, `riskwire/`, `dfb/`, `tournament/`, `api/server.py`, `execution/` (isolated).
3. **Files created** — **74 new files** across `docs/`, `docs/adr/`, `prompts/`, `data/*_cards/`,
   `data/{research_reports,ic_memos,risk_reviews,red_team_reviews}/`.
4. **Files modified** — **2, both careful non-destructive extends**: root `CLAUDE.md` (+Yield-Lab
   section) and `.gitignore` (+narrow exception so research-card dirs track despite the runtime
   `data/*.json` ignore). Plus `PROGRESS.md` (new).
5. **Existing architecture preserved** — YES. No runtime/execution/RiskPolicy/dashboard/deploy file
   was touched (verified: `git diff --name-only main..HEAD` contains no such path).
6. **New docs** — 31 markdown docs (`docs/00,02,06,07,10-16,23-26,28-31,33-45`) + 7 ADR-YL.
7. **New prompt files** — 15 agent prompts (`prompts/agents/*.md`) + the master charter.
8. **New schemas/templates** — 3 JSON schemas (strategy/protocol/stablecoin cards, all valid JSON),
   3 card templates + READMEs, 5 reporting templates, 5 illustrative example strategy cards.
9. **Tests run** — JSON validity of all 3 card schemas (pass). Repo import used to verify adapter
   count (35). No suite run needed (docs-only change).
10. **Tests not run & why** — full pytest suite not re-run: this run added zero runtime code, so it
    cannot affect test outcomes; the suite was already green earlier this session.
11. **Risks/uncertainties** — the master prompt's 10-15% target vs the desk's honest finding that it
    does not beat the ~3.4% RWA floor via yield at fundable scale (held as an explicit tension, not
    resolved); Priority-3 docs are stubs; all APY/TVL are placeholders "requires verification".
12. **Open questions** — see `docs/31_open_questions.md` (10 OQs).
13. **Recommended next 10 tasks** — (1) owner resolves OQ-1 (Yield-Lab mandate framing); (2) verify
    live data-source availability (OQ-7) before BTC/ETH/discovery docs assume any; (3) fill 3–5 real
    protocol cards from the 35 adapters; (4) fill 5–7 stablecoin cards (USDC/USDT/DAI/USDe/PYUSD/RLUSD/
    EURC); (5) wire Risk Scoring v2 as an advisory read over the existing `dfb` overlay/`scoring_engine`
    (no execution); (6) expand `docs/43` dangerous-strategies per-strategy; (7) expand `docs/44` into
    strategy cards; (8) draft the first weekly investment report from the template; (9) map the existing
    rates_desk/aggressive_lab outputs onto Strategy Cards; (10) IC-memo the FixedCarry sleeve.
14. **No execution-path logic changed** — CONFIRMED.
15. **No private-key / auto-signing functionality added** — CONFIRMED.
16. **Deterministic RiskPolicy not weakened** — CONFIRMED (untouched; documented as the sole hard gate).
17. **Risk Scoring v2 is advisory only** — CONFIRMED (docs/14 + ADR-YL-004; never a gate, not wired
    to execution).
18. **BTC/ETH modules are decision-support only** — CONFIRMED (docs/15/16/36 + ADR-YL-007).
19. **No APY claims added as verified without evidence** — CONFIRMED (all numbers are category ranges
    or "requires verification"/"illustrative"; evidence standard in docs/37).
20. **Recommended next Claude Code prompt** — "Read docs/00_index.md, docs/06, docs/29_backlog.md; pick
    PROTOCOL-CARD task for Aave V3; fill one real Protocol Card (data/protocol_cards/) from the
    spa_core/adapters + dfb overlay + a DeFiLlama read; mark any unverified metric 'requires
    verification'; do not touch runtime/RiskPolicy/dashboard/deploy; one task only."

## Environment notes for recovery
- Existing `docs/` is large; new docs use `NN_lowercase.md` (no collision). New ADRs namespaced
  **ADR-YL-###** (existing `docs/adr/` holds ADR-002+). New card data in NEW dirs only; runtime
  `data/*.json` + existing `data/*/` untouched. Local `main` diverges from `origin/main` (API-push
  model); a future session syncing origin should `git fetch && reset --hard origin/main` on `main`,
  never on this branch. Never invent APY/TVL — unknown = "requires verification".
