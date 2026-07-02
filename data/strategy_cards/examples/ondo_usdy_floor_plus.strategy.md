# Strategy Card — Ondo USDY floor-plus (tokenized T-bill hold)

> Promoted from candidate **CAND-USDY-001** (edge-hunt cycle 1) now that the **Ondo issuer card
> `PC-ONDO-001` exists** (cycle 2) — the mandate's *approve-path* pipeline end-to-end:
> edge-hunt → issuer DD → Strategy Card. ADR-YL-008 spread-attribution now cites SOURCED issuer data,
> not assertions. Status: **research** (not approved). Numbers: TVL/custody L2-sourced (Ondo card);
> exact live APY still L1 (needs L2). Schema: `data/strategy_cards/schema.strategy_card.json`.

## Identity
- **strategy_id:** `SC-USDY-001`  (from CAND-USDY-001)
- **name:** `Ondo USDY floor-plus (tokenized T-bill hold)`
- **version:** `1.0`
- **category:** `rwa`
- **product_line:** `Core`  <!-- target; ~5% sits at the Preserve/Core boundary. A conservative floor-plus, NOT Enhanced/Max. -->
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["USDY (Ondo)"]`
- **protocols_used:** `["Ondo Finance (PC-ONDO-001)"]`
- **chains_used:** `["Ethereum (+ verify per market)"]`

## Yield source (the honesty core)
- **yield_source:** `Short-dated US Treasury coupon + insured bank-deposit interest, passed through by Ondo USDY LLC (a tokenized note).`
- **yield_mechanism:** `Hold USDY, accrue the T-bill coupon (92% Treasuries <6mo / 8% bank deposits — SOURCED, PC-ONDO-001).`
- **who_pays_the_yield:** `The US Treasury (bill coupon) + insured banks (deposit interest), via Ondo.`
- **why_yield_exists:** `Front-end sovereign rates; a single issuer captures slightly more than the diversified floor basket.`
- **why_yield_can_disappear:** `Rate cuts (floor moves); issuer/custodian event; banking-partner failure; redemption gating.`

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: ~4.8, high: ~5.2 }` — **L1** (observed via 2026 yield comparisons; needs L2 exact from Ondo)
- **observed_apy_range:** `~5% (L1)` — not yet paper-tracked
- **base_apy:** `~5% (T-bill coupon; NOT incentive-driven)`
- **incentive_apy:** `0 / N/A`
- **sustainable_apy_estimate:** `≈ front-end rate (moves with the floor)`
- **apy_evidence_level:** `L1` (needs L2 data-source verification of exact live USDY rate before paper test)

## Spread over the floor (the mandate — ADR-YL-008) — now issuer-sourced
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live; TVL-weighted basket), as_of: 2026-07-02, fallback_used: requires verification }`
- **spread_over_floor_bps:** `~160 bps` (≈5.0% − 3.4%). [L1 — pending exact APY]
- **spread_risk_explanation (each risk now cites PC-ONDO-001, sourced):**
  - `{ risk: "single-issuer concentration (Ondo USDY LLC) vs the diversified floor basket", bps: "est ~50-70 — requires exact decomposition", evidence: "PC-ONDO-001 (single issuer; floor basket = BUIDL/USYC/USDY/OUSG/USTB)" }`
  - `{ risk: "custodian-freeze tail (redemption freezes on custodian failure)", bps: "est ~30-50", evidence: "PC-ONDO-001 (Ankura Trust / Morgan Stanley; wire redemption; custodian-failure=freeze)" }`
  - `{ risk: "banking-partner exposure on the ~8% deposit slice (SVB-type)", bps: "est ~20-30", evidence: "PC-ONDO-001 (92/8 Treasuries/bank-deposits)" }`
  - `{ risk: "KYC/transfer-restriction liquidity (thin secondary exit, slow at size)", bps: "est ~20-40", evidence: "PC-ONDO-001 (allowlist/blocklist/sanctions + KYC)" }`
- **unexplained_spread_bps:** `~0 expected — the four SOURCED risks plausibly cover the ~160 bps, but the exact per-risk bps split is not yet computed (estimates above sum ~120-190, bracketing 160).`
- **spread_fully_explained:** `false (provisional-TRUE pending two numeric closures):` (1) exact live USDY APY at L2, (2) an exact bps decomposition summing to the spread. **The RISK MAPPING is now DOCUMENTED + sourced (issuer card), not asserted** — the remaining gap is numeric precision, not "is this risk-comp or real?". This is the mandate working as intended: a bounded, documented, floor-plus spread advancing toward approval, unlike the refused tail-comp (leverage_loop).

## Advisory scores (0–100; docs/14 — ADVISORY ONLY)
- **confidence_score:** `~55` (issuer DD sourced; exact APY + bps split pending)
- **risk_score:** `LOW-MODERATE — requires Risk Scoring v2 run; residual = single-issuer + custodian-freeze + 8% banking + KYC-liquidity (all bounded, no leverage/tail)`
- **liquidity_score:** `moderate (KYC/redemption-window friction — the binding exit constraint)`
- **complexity_score:** `low (buy-and-hold a tokenized note)`

## Capacity & capital
- **capacity_estimate:** `high (Ondo TVL ~$3.56B; deep RWA market) — but cap issuer concentration vs the floor basket`
- **min_capital / max_capital:** `issuer KYC minimums gate small tiers — requires verification`
- **suitable_capital_tiers:** `["$100k–$10M+ (deep; KYC gates the smallest)"]`
- **lockup_period:** `redemption-window dependent (wire; custodian-failure=freeze)`
- **withdrawal_time:** `T+? via wire redemption or secondary (KYC-limited) — requires verification`

## Risk dimensions (qualitative)
- **smart_contract_risk:** `Ondo USDY contracts — audit firms requires verification (PC-ONDO-001)`
- **stablecoin_risk:** `it IS a tokenized note; primary risk is issuer/custody not depeg`
- **counterparty_risk:** `Ondo + Ankura/Morgan Stanley + insured banks (the defining risk)`
- **bridge_risk:** `N/A single-chain (verify per market)`
- **oracle_risk:** `NAV attestation (monthly) + on-chain price`
- **liquidation_risk:** `none (no leverage)`
- **regulatory_risk:** `tokenized-security structure; KYC/jurisdiction restricted`
- **operational_risk:** `redemption process; KYC`
- **concentration_risk:** `single-issuer — MUST cap vs the diversified floor basket`
- **correlation_risk:** `rate-level (it is the front-end rate); low BTC/ETH beta`
- **market_regime_risk:** `falls with rate cuts`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["Ondo/Ankura/Morgan Stanley custody + insured banks (PC-ONDO-001)", "rwa_feed live floor", "USDY redemption rails"]`
- **assumptions:** `["custody + redemption hold under stress", "exact APY ≈ 5% (needs L2)"]`
- **entry_conditions:** `["issuer card reviewed (PC-ONDO-001 — partial: audits pending)", "exact APY verified L2", "issuer-concentration cap set"]`
- **exit_conditions:** `["redemption to stablecoin", "rate regime shift"]`
- **emergency_exit_conditions:** `["custodian/bank event", "redemption freeze", "attestation miss", "regulatory action"]`
- **monitoring_requirements:** `["peg/NAV daily", "attestation monthly", "custodian/bank + regulatory on-event"]`
- **data_sources_required:** `["Ondo transparency (attestation)", "rwa_feed (floor)", "DeFiLlama (Ondo TVL)"]`

## Validation & approval (promotion ledger)
- **validation_status:** `research` (promoted from candidate; issuer DD sourced)
- **paper_test_status:** `not_started` (needs a paper-test plan + L2 APY)
- **small_capital_test_status:** `not_started`
- **red_team_status:** `partial` (candidate red-team done; full ADR-YL-008 spread-attribution red-team pending exact bps)
- **approved_for_product_line:** `null` (NOT approved)
- **final_recommendation:** `research-only → advance-to-paper` once (1) exact live APY [L2] and (2) exact spread bps-decomposition + issuer-concentration cap are set. The thesis (bounded floor-plus, documented risk) is sound.
- **max_allocation:** `0 (advisory; IS_ADVISORY — moves no live capital)`
- **review_frequency:** `weekly (research) / daily once paper`

## Provenance
- **owner:** `owner / IC`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `research`

---

### Promotion gate checklist (docs/11 §5)
- [~] **Spread fully explained (ADR-YL-008)** — risk mapping SOURCED (PC-ONDO-001); pending exact APY [L2] + bps decomposition → provisional, not yet TRUE
- [x] Clear yield source (T-bill coupon + bank deposit, sourced)
- [ ] APY evidence ≥ L3 — currently L1 (needs L2 then paper L3)
- [~] Protocol review — PC-ONDO-001 exists (partial: audit firms pending)
- [ ] Stablecoin review — USDY is the note itself (issuer card covers it); a Stablecoin Card optional
- [ ] Risk review — Risk Scoring v2 run pending
- [ ] Red-team — full spread-attribution red-team pending exact bps
- [x] Capacity — Ondo ~$3.56B, deep (cap issuer concentration)
- [ ] Liquidity review — KYC/redemption exit-at-size to verify
- [ ] Paper testing — not started
- [ ] Human approval — no

> **Pipeline demonstrated:** CAND-USDY-001 (edge-hunt) → PC-ONDO-001 (issuer DD) → SC-USDY-001
> (this card). The mandate's *approve-path* in motion: a bounded floor-plus whose spread is now
> DOCUMENTED risk-compensation (issuer/custody/banking/KYC), advancing toward paper — the fundable
> middle between banking the floor and refusing tail-comp. Two numeric closures (exact APY, bps split)
> remain before `spread_fully_explained=true`.
