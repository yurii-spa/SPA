# Protocol Card — Compound V3

> Real card mapped from `spa_core/adapters/compound*.py` (CompoundV3Adapter, TIER T1). Research-layer
> artifact — NOT runtime data, never read by RiskPolicy or execution. **No TVL/audit/exploit specifics
> invented**; unsourced = `requires data verification`. Cross-refs: docs/12, docs/11, docs/14, docs/02.

## Identity
- **protocol_id:** `PC-COMPV3-001`  <!-- maps to adapter: compound_v3 -->
- **protocol_name:** `Compound V3 (Comet)`
- **category:** `lending`
- **chains:** `["Ethereum"]`  <!-- adapter DEFILLAMA_CHAIN=Ethereum; Compound V3 also on L2s — verify which the desk uses -->
- **website:** `https://compound.finance` <!-- requires verification -->
- **docs:** `https://docs.compound.finance` <!-- requires verification -->
- **app_url:** `https://app.compound.finance` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `~$1.06B` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/compound-v3` (1,060,588,800.99). [L2]
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Compound since 2018; V3 (Comet) since 2022 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** **sourced (verified 2026-07-02):** OpenZeppelin + ChainSecurity; **twice-yearly audits by Trail of Bits + OpenZeppelin**. Compound III specifically: OpenZeppelin audit (July 2022) found + fixed a high-severity locked-funds issue in Comet/Bulker. Reports public (docs.compound.finance, OpenZeppelin blog). [L2]
- **bug_bounty:** `Compound bug-bounty exists — exact max payout requires verification`
- **exploit_history:** `Compound V3 (Comet) core: no widely-reported principal-loss exploit as of 2026-07. (2021 V2 COMP-distribution bug over-paid rewards — governance issue, NOT user-principal loss.) [L1→verify]`
- **admin_keys:** **sourced (verified 2026-07-02):** all Compound III instances are controlled by the **Timelock** (the Comet `governor` = Timelock address; same admin as Compound V2). Governance = **COMP token + GovernorBravo + Timelock**. Exact timelock delay requires verification. [L2]
- **upgradeability:** `governance-controlled via GovernorBravo + Timelock (Timelock is the governor of all V3 proxies/Configurator/factory/implementation) — sourced; exact delay requires verification`
- **oracle_dependencies:** `["Chainlink price feeds (breaks liquidations if it fails)"]`
- **bridge_dependencies:** `[]`  <!-- mainnet usage; L2 deployments would add bridge risk — verify -->
- **governance_model:** `COMP token + GovernorBravo + Timelock (sourced 2026-07-02)`

## Yield & incentives
- **token_incentives:** `COMP rewards on some markets — the base USDC supply yield is organic (borrow-demand spread). Verify current incentives.`
- **yield_sustainability:** `organic` (lending spread) — verify per market.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["smart-contract risk (long track record + audits — verify)", "oracle risk (Chainlink)", "single-borrow-asset design per Comet market (concentration by design)", "utilization/withdrawal-at-size risk", "governance/timelock admin risk (verify)"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW (T1, ~$1.06B, twice-yearly ToB+OZ audits, Timelock-governed, no core principal-loss exploit). Confidence now higher (audits + admin-keys sourced).`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T1 cap (40% per protocol). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/utilization/TVL) + `on_event` (governance/oracle/exploit)
- **emergency_triggers:** `["core exploit", "oracle failure", "governance emergency action", "utilization spike blocking withdrawals"]`

## Provenance
- **notes:** `Now SOURCED (2026-07-02): TVL ~$1.06B (DeFiLlama), audits (OZ/ChainSecurity + twice-yearly ToB+OZ), admin keys (COMP+GovernorBravo+Timelock). T1 lending alongside Aave V3 (CompoundV3Adapter, T1_CAP 0.40). Read-only/advisory adapter. Remaining: bug-bounty payout, exact timelock delay, revenue/fees.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/compound-v3; docs.compound.finance/governance; OpenZeppelin Compound III audit (July 2022).

---

### Review checklist (docs/12 §5)
- [x] `admin_keys` (COMP+GovernorBravo+Timelock), `upgradeability`, `oracle_dependencies` (Chainlink), `governance` SOURCED; exploit_history L1; bug-bounty pending
- [x] `tvl` sourced with a date (~$1.06B, DeFiLlama, 2026-07-02); revenue/fees/user_activity pending
- [ ] `risk_score` + `max_allocation_recommendation` — Risk Scoring v2 run pending (T1 40%)
- [x] `protocol_id` mapped to the adapter key (compound_v3)
