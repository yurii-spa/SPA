# Protocol Card — Aave V3

> Real card mapped from the Aave V3 adapters (`spa_core/adapters/aave_v3*.py`) — the desk's core T1
> lending venue. Research-layer artifact — NOT runtime data, never read by RiskPolicy or execution.
> **No TVL/audit/exploit specifics are invented**; anything not sourced from the repo is
> `requires data verification`. Cross-refs: docs/12, docs/11, docs/14, docs/02.

## Identity
- **protocol_id:** `PC-AAVEV3-001`  <!-- maps to adapter keys: aave_v3 (ETH/ARB/OP/POLY) + aave_v3_base -->
- **protocol_name:** `Aave V3`
- **category:** `lending`
- **chains:** `["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base"]`  <!-- per CLAUDE.md tier map + aave_v3_base_adapter; verify the exact live set -->
- **website:** `https://aave.com` <!-- requires verification -->
- **docs:** `https://docs.aave.com` <!-- requires verification -->
- **app_url:** `https://app.aave.com` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `~$12.0B protocol-wide` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/aave-v3` (12,005,950,660.55). [L2]  (Base-chain USDC ~$400M is the adapter literal, 2026-06.)
- **tvl_trend:** `unknown — requires verification from DeFiLlama history`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `~5y+ (Aave since 2020; V3 since 2023) — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** **sourced (verified 2026-07-02):** Aave V3 audited by **Trail of Bits, ABDK, PeckShield, OpenZeppelin, SigmaPrime** + **continuous formal verification by Certora** (Certora Prover; e.g. Risk-Steward June 2024, static aToken Jan–Mar 2023). Among the most-audited DeFi protocols; reports public (docs.aave.com security-and-audits, Certora reports). [L2]
- **bug_bounty:** `Large Aave bug-bounty program exists — exact current max payout requires verification`
- **exploit_history:** `Aave V3 CORE has no widely-reported principal-loss exploit as of 2026-07 (verify). Aave has used isolated-market freezes/pauses defensively; no core drain reported.` [L1→verify]
- **admin_keys:** **sourced (verified 2026-07-02):** **Protocol Emergency Guardian holds the EMERGENCY_ADMIN role, a 5-of-9 multisig** (highly-active DAO entities) — can act in emergencies; a separate **Governance Guardian** cancels malicious/erroneous proposals (flagged at on-chain verification by Certora). [L2]
- **upgradeability:** `upgradeable via AAVE governance + timelock; emergency pause via the 5-of-9 Emergency Guardian (sourced). Exact timelock delay requires verification.`
- **oracle_dependencies:** `["Chainlink price feeds (what breaks: liquidations + borrow caps if feed fails)"]`  <!-- verify exact oracle set per chain -->
- **bridge_dependencies:** `["L2 deployments (Arbitrum/Optimism/Base) inherit L2-bridge risk — the reason aave_v3_base is tiered T2 despite Aave being T1"]`
- **governance_model:** `AAVE token governance + Governance Guardian (proposal cancel) + Protocol Emergency Guardian (EMERGENCY_ADMIN, 5-of-9 multisig) — sourced 2026-07-02`

## Yield & incentives
- **token_incentives:** `Aave has run incentive programs on some markets; the core USDC/stable lending yield is primarily organic (borrow-demand spread). Verify current incentives per market.`
- **yield_sustainability:** `organic` (lending spread from real borrow demand) — verify per market; incentive-inflated markets flagged separately.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["smart-contract risk (mitigated by long track record + heavy audits — verify)", "oracle risk (Chainlink dependency)", "L2-bridge risk on non-mainnet deployments (Base = T2)", "utilization/liquidity risk (withdrawal at size when utilization is high)", "governance/admin-key pause risk (verify)"]`
- **risk_score:** `TBD — requires a Risk Scoring v2 run (docs/14). Qualitatively LOW for mainnet T1: ~$12B TVL, most-audited + continuously formally-verified (Certora), no core principal-loss exploit, 5/9 emergency guardian. Confidence now HIGH (audits + admin-keys sourced). Base deployment higher (T2, bridge).`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T1 cap (40% per protocol) for mainnet; Base deployment by T2 cap (20%). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/utilization/TVL) + `on_event` (governance pause, oracle, exploit)
- **emergency_triggers:** `["core exploit", "oracle failure", "governance/Guardian emergency pause", "utilization spike blocking withdrawals", "L2-bridge incident (Base/Arb/Op)"]`

## Provenance
- **notes:** `Now SOURCED (2026-07-02): TVL ~$12.0B (DeFiLlama), audits (Trail of Bits/ABDK/PeckShield/OpenZeppelin/SigmaPrime + Certora formal verification), admin keys (5-of-9 Emergency Guardian + Governance Guardian). Aave V3 = desk core T1 lending venue; Base deployment T2 (L2-bridge). Adapters read-only/advisory. Remaining to verify: bug-bounty max payout, exact timelock delay, revenue/fees.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/aave-v3; docs.aave.com security-and-audits; Certora reports (certora.com/reports); OpenZeppelin Aave audit; Aave governance forum (Emergency/Governance Guardian, 5-of-9 multisig).

---

### Review checklist (docs/12 §5)
- [x] `admin_keys` (5/9 Emergency Guardian), `upgradeability`, `oracle_dependencies` (Chainlink), `governance` SOURCED; exploit_history L1 (no core drain, verify), bug-bounty pending
- [x] `tvl` sourced with a last-verified date (~$12.0B protocol-wide, DeFiLlama, 2026-07-02); revenue/fees/user_activity pending
- [ ] `risk_score` + `max_allocation_recommendation` — Risk Scoring v2 run pending (T1 40% / Base T2 20%)

> **Protocol-review gate:** substantially satisfied for mainnet Aave V3 — TVL, audits, admin-keys,
> governance, oracles all sourced 2026-07-02. Residual: bug-bounty payout + exact timelock delay + a
> formal Risk Scoring v2 run. The strongest-documented card in the set.
- [x] `protocol_id` mapped to the adapter keys (aave_v3, aave_v3_base)
