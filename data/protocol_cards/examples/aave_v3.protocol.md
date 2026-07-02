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
- **tvl:** `Base-chain USDC ~$400M (adapter literal TVL_USD, data 2026-06 — re-verify live via DeFiLlama project "aave-v3"). Protocol-wide TVL: requires data verification.`
- **tvl_trend:** `unknown — requires verification from DeFiLlama history`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `~5y+ (Aave since 2020; V3 since 2023) — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** `TBD — requires data verification`  <!-- Aave is among the most-audited DeFi protocols; list [{firm, scope, date}] from Aave's published audits before the gate passes. Empty here = NOT YET SOURCED, not "none". -->
- **bug_bounty:** `TBD — requires data verification`  <!-- Aave runs a large bug-bounty; verify current max payout -->
- **exploit_history:** `TBD — requires data verification`  <!-- Aave V3 core has no widely-reported principal-loss exploit; VERIFY before relying (freeze incidents / isolated-market issues have occurred) -->
- **admin_keys:** `TBD — requires data verification`  <!-- Governance + Guardian multisig can pause markets; source the exact threshold/timelock. Load-bearing. -->
- **upgradeability:** `upgradeable via governance + timelock — requires verification of exact params`
- **oracle_dependencies:** `["Chainlink price feeds (what breaks: liquidations + borrow caps if feed fails)"]`  <!-- verify exact oracle set per chain -->
- **bridge_dependencies:** `["L2 deployments (Arbitrum/Optimism/Base) inherit L2-bridge risk — the reason aave_v3_base is tiered T2 despite Aave being T1"]`
- **governance_model:** `AAVE token governance + Guardian multisig (emergency pause) — verify powers`

## Yield & incentives
- **token_incentives:** `Aave has run incentive programs on some markets; the core USDC/stable lending yield is primarily organic (borrow-demand spread). Verify current incentives per market.`
- **yield_sustainability:** `organic` (lending spread from real borrow demand) — verify per market; incentive-inflated markets flagged separately.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["smart-contract risk (mitigated by long track record + heavy audits — verify)", "oracle risk (Chainlink dependency)", "L2-bridge risk on non-mainnet deployments (Base = T2)", "utilization/liquidity risk (withdrawal at size when utilization is high)", "governance/admin-key pause risk (verify)"]`
- **risk_score:** `TBD — requires a Risk Scoring v2 run (docs/14). Qualitatively LOW for mainnet T1 (foundational lending); Base deployment higher (T2, bridge).`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T1 cap (40% per protocol) for mainnet; Base deployment by T2 cap (20%). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/utilization/TVL) + `on_event` (governance pause, oracle, exploit)
- **emergency_triggers:** `["core exploit", "oracle failure", "governance/Guardian emergency pause", "utilization spike blocking withdrawals", "L2-bridge incident (Base/Arb/Op)"]`

## Provenance
- **notes:** `Aave V3 is the desk's core T1 lending venue (mainnet); the Base deployment is tiered T2 for L2-bridge risk (aave_v3_base_adapter, ~$400M USDC 2026-06). Adapters are read-only/advisory (no on-chain execution). Security fields (audits/exploit_history/admin_keys) UNVERIFIED here = findings to source before a Strategy Card's protocol-review gate passes; Aave's strong reputation does NOT substitute for documenting them.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/12 §5)
- [ ] `admin_keys`, `upgradeability`, `oracle_dependencies`, `exploit_history`, `emergency_triggers` filled substantively — **admin_keys / exploit_history UNVERIFIED (findings)**
- [ ] `tvl` / `revenue` / `fees` / `user_activity` sourced with a last-verified date — **partial (Base ~$400M 2026-06; protocol-wide pending)**
- [ ] `risk_score` + `max_allocation_recommendation` cite the dfb overlay / RiskPolicy caps — pending (T1 40% / Base T2 20%)
- [x] `protocol_id` mapped to the adapter keys (aave_v3, aave_v3_base)
