# Protocol Card — Ondo Finance (USDY / OUSG issuer)

> Deep-research cycle (autonomous engine, item B). Issuer/Protocol Card for Ondo — created to **unblock
> candidate CAND-USDY-001** (Ondo USDY floor-plus sleeve). All facts web-sourced 2026-07-02 with
> evidence levels; unknowns = `requires verification`, never invented. Cross-refs: docs/12, docs/11,
> `data/strategy_candidates/ondo_usdy.candidate.md`, docs/38.

## Identity
- **protocol_id:** `PC-ONDO-001`
- **protocol_name:** `Ondo Finance` (tokenized US-Treasury issuer — USDY, OUSG)
- **category:** `rwa` (tokenized T-bills / stablecoin_issuer)
- **chains:** `["Ethereum", "+ others (Solana, etc. — verify which the desk would use)"]`
- **website:** `https://ondo.finance` <!-- requires verification -->
- **docs:** `https://docs.ondo.finance` <!-- requires verification -->
- **app_url:** `https://ondo.finance/usdy` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `~$3.56B` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/ondo-finance` (3,556,099,056.84). One of the largest tokenized-RWA issuers. [L2]
- **tvl_trend:** `unknown — requires DeFiLlama history`
- **revenue:** `management fee on AUM — exact rate requires verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `institutional + KYC'd non-US — requires verification`
- **protocol_age:** `Ondo since ~2021; USDY launched ~2023 — requires verification`

## Backing & custody (the RWA due-diligence core — SOURCED)
- **reserves/backing (USDY):** **sourced (verified 2026-07-02):** USDY is a **tokenized note = a debt claim on Ondo USDY LLC**, secured by **US Treasuries with <6-month maturity + bank demand deposits at insured US banks**. Composition **~92% Treasuries / ~8% bank deposits** (April 2026); the deposit slice = redemption-day liquidity. [L2]
- **custody:** **sourced:** Treasuries held at **Morgan Stanley**; **Ankura Trust** is custodian for the underlying Treasuries; bank deposits across multiple insured US banks; legal structure uses **segregated trusts** separating customer assets. [L2]
- **redemption_mechanism:** **sourced:** redemptions serviced via **wire transfer**; **a custodian failure freezes redemption** (the key operational tail). [L2]
- **transfer_restrictions:** **sourced:** enforced on-chain via **allowlist / blocklist / sanctions-list** contracts; **KYC + jurisdiction eligibility** checked before purchase (non-US-retail). → real exit-liquidity / composability friction. [L2]

## Security & trust surface
- **audits:** **partially sourced:** reserves **reviewed MONTHLY by an independent auditor** + third-party audits confirm reserves (attestation cadence = monthly). Smart-contract audit firms `require verification`. [L2 for reserves / L1 for code]
- **bug_bounty:** `requires verification`
- **exploit_history:** `no widely-reported principal-loss exploit as of 2026-07 (verify). Primary risk is off-chain (custodian/bank), not contract depeg.`
- **admin_keys:** **partially sourced:** Ondo controls the allowlist/blocklist/sanctions + redemption process (centralized issuer control — can restrict transfers/redemption). Exact multisig/timelock `requires verification`.
- **upgradeability:** `issuer-controlled — requires verification`
- **oracle_dependencies:** `NAV / price attestation (monthly + on-chain price) — verify design`
- **bridge_dependencies:** `per-chain (verify)`
- **governance_model:** `Centralized issuer (Ondo USDY LLC) + ONDO token governance (scope requires verification)`

## Yield & incentives
- **token_incentives:** `USDY yield is the organic T-bill coupon (NOT incentive-driven). ONDO token is separate governance/equity, not the USDY yield source.`
- **yield_sustainability:** `organic` — short-dated Treasury coupon; moves with the front end (the RWA floor itself).

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["CUSTODIAN failure → redemption freeze (the defining operational tail — sourced)", "single-issuer concentration (Ondo USDY LLC) vs the diversified floor basket", "banking-partner risk on the ~8% bank-deposit slice (SVB-type)", "KYC/transfer restrictions → thin secondary liquidity + slow exit at size", "rate/duration (low — <6mo WAM)", "regulatory (tokenized-security structure)"]`
- **risk_score:** `TBD — Risk Scoring v2 run pending (docs/14). Qualitatively LOW-MODERATE: real short-dated T-bill backing at Morgan Stanley/Ankura + monthly attestation (strong), offset by single-issuer + custodian-freeze + KYC-liquidity + the 8% banking slice. A conservative, bounded profile — NOT tail-comp.`
- **max_allocation_recommendation:** `Advisory — a floor-plus RWA sleeve; cap issuer concentration (do not replace the diversified floor basket with a single issuer). Exact % requires verification.`
- **monitoring_frequency:** `daily (peg/NAV) + monthly (attestation) + on_event (custodian/bank/redemption)`
- **emergency_triggers:** `["custodian (Ankura/Morgan Stanley) event", "bank-partner failure (deposit slice)", "redemption halt/freeze", "attestation miss", "regulatory action / transfer-restriction change"]`

## Provenance
- **notes:** `SOURCED 2026-07-02. Unblocks CAND-USDY-001: the candidate's ~160 bps spread over the floor now maps to DOCUMENTED accepted risks — single-issuer concentration, custodian-freeze tail, ~8% banking-partner exposure, KYC/liquidity friction — all bounded/measurable, NOT leverage/incentive/depeg tail. Strengthens the ADVANCE verdict. Remaining to verify: smart-contract audit firms, exact fee, admin multisig/timelock, exit-liquidity-at-size.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/ondo-finance; Ondo USDY reviews/docs (reserve 92/8 composition, Morgan Stanley + Ankura custody, monthly independent auditor, wire redemption, allowlist/KYC) — cryptoadventure / eco.com / quicknode 2026.

---

### Review checklist (docs/12 §5)
- [x] backing/custody/redemption/transfer-restrictions SOURCED (92/8, Morgan Stanley+Ankura, wire, allowlist/KYC)
- [x] `tvl` sourced with a date (~$3.56B, DeFiLlama, 2026-07-02); attestation cadence monthly
- [ ] smart-contract audit firms + admin multisig/timelock + exit-liquidity-at-size — pending
- [ ] `risk_score` — Risk Scoring v2 run pending

> **Unblocks CAND-USDY-001:** the candidate's spread-attribution now cites this sourced issuer card.
> The ~160 bps is bounded, documented risk-compensation (issuer/custody/banking/liquidity), not tail —
> the ADVANCE verdict holds, pending exact live-APY (L2) + a bps decomposition + an issuer-concentration cap.
