# Strategy Card — RWA Sleeve (tokenized T-bill cash floor)

> Real card mapped from the `rwa_sleeve` in `spa_core/strategy_lab/` (captured_sleeves.py: "the
> REALIZED tokenized-T-bill cash floor: it banks the floor (~3.4%), it does NOT beat it"). This card
> anchors ADR-YL-008: it **IS the baseline** — spread over the floor is ~0 by construction. Numbers
> `requires verification` unless sourced. Cross-refs: docs/11, docs/07, docs/37, docs/38, docs/adr/ADR-YL-008.

## Identity
- **strategy_id:** `SC-RWA-001`  <!-- maps to sleeve `rwa_sleeve` -->
- **name:** `RWA Sleeve — tokenized T-bill cash floor`
- **version:** `1.0`
- **category:** `rwa`
- **product_line:** `Preserve`
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["tokenized T-bills (BUIDL / USYC / USDY / OUSG / USTB — TVL-weighted)"]`
- **protocols_used:** `["RWA issuers (BlackRock/Securitize, Circle/Hashnote, Ondo, ... — Protocol/issuer cards TBD)"]`
- **chains_used:** `["Ethereum (+ verify)"]`

## Yield source (the honesty core)
- **yield_source:** `US Treasury bill coupon, tokenized (the risk-free-ish cash floor).`
- **yield_mechanism:** `RWA coupon pass-through (TVL-weighted across tokenized T-bill issuers).`
- **who_pays_the_yield:** `The US Treasury (bill coupon), passed through by the token issuer.`
- **why_yield_exists:** `Short-dated sovereign rates; the floor moves with the front end.`
- **why_yield_can_disappear:** `Rate cuts lower the floor; issuer/custody/redemption risk; regulatory change.`

## APY (never presented without an evidence level)
- **expected_apy_range:** `≈ the live RWA floor (~3.4%; dynamic from rwa_feed) — NOT a spread play`
- **observed_apy_range:** `≈ floor (banks it; does not beat it) — realized series in strategy_lab paper (requires verification)`
- **base_apy:** `≈ floor`
- **incentive_apy:** `0 / N/A`
- **sustainable_apy_estimate:** `= floor (moves with front-end rates)`
- **apy_evidence_level:** `L3` (paper-tracked; realized floor) — verify

## Spread over the floor (the mandate — ADR-YL-008)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live), as_of: 2026-07-01, fallback_used: requires verification }`
- **spread_over_floor_bps:** `≈ 0 by construction` — this sleeve IS the baseline; it realizes the floor, it does not exceed it (captured_sleeves.py `at_floor`).
- **spread_risk_explanation:** `[]` — N/A: there is no positive spread over the floor to attribute.
- **unexplained_spread_bps:** `0`
- **spread_fully_explained:** `true` (trivially — zero spread ⇒ zero unexplained). This card exists to **define the baseline** every Enhanced/Max card is measured against, not to beat it.

## Advisory scores (0–100; docs/14 — ADVISORY ONLY)
- **confidence_score:** `~70` (realized floor is well-understood) — advisory
- **risk_score:** `LOW — requires Risk Scoring v2 run; residual = issuer/custody/redemption + rate-duration (short)`
- **liquidity_score:** `moderate-high (tokenized T-bills; redemption windows vary by issuer)`
- **complexity_score:** `low`

## Capacity & capital
- **capacity_estimate:** `Large (the ~$15B tokenized-T-bill market) — requires verification`
- **min_capital:** `issuer minimums vary (some institutional) — requires verification`
- **max_capital:** `high (deep market)`
- **suitable_capital_tiers:** `["$100k → $100M+ (deep, but issuer minimums/KYC gate small tiers)"]`
- **lockup_period:** `redemption-window dependent per issuer`
- **withdrawal_time:** `T+0..T+2 depending on issuer (requires verification)`

## Risk dimensions (qualitative)
- **smart_contract_risk:** `token wrapper contracts (per issuer)`
- **stablecoin_risk:** `N/A directly (holds tokenized T-bills, not a stablecoin) — redemption to stables adds a step`
- **counterparty_risk:** `issuer + custodian (off-chain T-bill custody) — the main risk`
- **bridge_risk:** `N/A / per chain`
- **oracle_risk:** `NAV/pricing per issuer`
- **liquidation_risk:** `none (no leverage)`
- **regulatory_risk:** `RWA/securities surface (issuer-dependent)`
- **operational_risk:** `redemption windows; KYC/whitelisting`
- **concentration_risk:** `mitigated by TVL-weighting across issuers`
- **correlation_risk:** `rate-level correlation (it IS the rate)`
- **market_regime_risk:** `falls with rate cuts`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["tokenized-T-bill issuers/custodians", "rwa_feed (live floor)", "redemption rails to stablecoin"]`
- **assumptions:** `["issuer solvency + faithful coupon pass-through", "redemption available"]`
- **entry_conditions:** `["issuer whitelisted + reviewed"]`
- **exit_conditions:** `["redemption to stablecoin"]`
- **emergency_exit_conditions:** `["issuer/custody impairment", "redemption halt", "regulatory action"]`
- **monitoring_requirements:** `["live floor (rwa_feed)", "issuer TVL/attestations", "redemption health"]`
- **data_sources_required:** `["rwa_feed (data/rwa_feed.py)", "issuer disclosures"]`

## Validation & approval (promotion ledger)
- **validation_status:** `baseline (realized cash floor — the benchmark, not a spread candidate)`
- **paper_test_status:** `running (strategy_lab paper) — verify`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `n/a-as-baseline (issuer/custody DD still required for live use)`
- **approved_for_product_line:** `null` (research-layer card; the runtime rwa_feed is the live floor source)
- **final_recommendation:** `research-only / baseline` — use as the official ADR-YL-008 baseline; issuer-level DD required before any live allocation.
- **max_allocation:** `advisory; bounded by RiskPolicy`
- **review_frequency:** `daily (floor) / weekly`

## Provenance
- **owner:** `owner / IC`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `paper_testing`

---

### Promotion gate checklist (docs/11 §5)
- [x] **Spread fully explained (ADR-YL-008)** — TRUE trivially (spread = 0; this IS the baseline)
- [x] Clear yield source (T-bill coupon)
- [ ] APY evidence ≥ L3 — realized floor series requires verification
- [ ] Protocol/issuer review — issuer cards (BUIDL/USYC/USDY/...) TBD
- [ ] Risk review — Risk Scoring v2 not yet run
- [ ] Red-team — issuer/custody DD pending
- [x] Capacity — deep market (~$15B) — verify
- [ ] Liquidity review — per-issuer redemption windows
- [ ] Paper testing passed — running
- [ ] Human approval — no

> **Role in ADR-YL-008:** this sleeve is the **official baseline** — the ~3.4% live floor every
> Enhanced/Max card's spread is measured against. It is not a spread play (spread ≈ 0), and that is
> exactly the point: it banks the floor honestly, so everything else must *explain* the excess it earns
> over this.
