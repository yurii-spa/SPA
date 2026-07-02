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
- **tvl:** `TBD — requires data verification (live via DeFiLlama project "compound-v3")`
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Compound since 2018; V3 (Comet) since 2022 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** `TBD — requires data verification`  <!-- Compound is heavily audited; source [{firm,scope,date}] before gate -->
- **bug_bounty:** `TBD — requires data verification`
- **exploit_history:** `TBD — requires data verification`  <!-- Compound V3 core: no widely-reported principal-loss exploit; a 2021 V2 distribution bug over-paid COMP rewards (not user-principal loss) — verify before relying -->
- **admin_keys:** `TBD — requires data verification`  <!-- COMP governance + timelock; source threshold/timelock. Load-bearing. -->
- **upgradeability:** `governance + timelock — requires verification of exact params`
- **oracle_dependencies:** `["Chainlink price feeds (breaks liquidations if it fails)"]`
- **bridge_dependencies:** `[]`  <!-- mainnet usage; L2 deployments would add bridge risk — verify -->
- **governance_model:** `COMP token governance + timelock`

## Yield & incentives
- **token_incentives:** `COMP rewards on some markets — the base USDC supply yield is organic (borrow-demand spread). Verify current incentives.`
- **yield_sustainability:** `organic` (lending spread) — verify per market.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["smart-contract risk (long track record + audits — verify)", "oracle risk (Chainlink)", "single-borrow-asset design per Comet market (concentration by design)", "utilization/withdrawal-at-size risk", "governance/timelock admin risk (verify)"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW (T1 foundational lending, mainnet).`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T1 cap (40% per protocol). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/utilization/TVL) + `on_event` (governance/oracle/exploit)
- **emergency_triggers:** `["core exploit", "oracle failure", "governance emergency action", "utilization spike blocking withdrawals"]`

## Provenance
- **notes:** `Compound V3 is a T1 lending venue alongside Aave V3 (CompoundV3Adapter, T1_CAP 0.40). Read-only/advisory adapter. Security fields UNVERIFIED = findings to source before a Strategy Card's protocol-review gate passes.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/12 §5)
- [ ] `admin_keys`, `upgradeability`, `oracle_dependencies`, `exploit_history`, `emergency_triggers` — **admin_keys / exploit_history UNVERIFIED (findings)**
- [ ] `tvl` / `revenue` / `fees` / `user_activity` sourced with a date — **pending (DeFiLlama compound-v3)**
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T1 cap — pending
- [x] `protocol_id` mapped to the adapter key (compound_v3)
