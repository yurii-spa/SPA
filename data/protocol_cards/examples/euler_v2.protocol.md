# Protocol Card — Euler V2

> Real card mapped from `spa_core/adapters/euler*.py` (EulerV2Adapter, T2). Research-layer artifact —
> NOT runtime data. **No specifics invented**; unsourced = `requires data verification`. Cross-refs:
> docs/12, docs/11, docs/14, docs/02.

## Identity
- **protocol_id:** `PC-EULERV2-001`  <!-- maps to adapter: euler_v2 -->
- **protocol_name:** `Euler V2`
- **category:** `lending` (modular lending — EVK vaults + EVC)
- **chains:** `["Ethereum"]`  <!-- verify live set -->
- **website:** `https://euler.finance` <!-- requires verification -->
- **docs:** `https://docs.euler.finance` <!-- requires verification -->
- **app_url:** `https://app.euler.finance` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `TBD — requires data verification (live via DeFiLlama project "euler-v2")`
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Euler V1 2022; exploited & wound down 2023; V2 relaunched ~2024 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** `TBD — requires data verification (V2 was heavily re-audited post-relaunch; source [{firm,scope,date}])`
- **bug_bounty:** `TBD — requires data verification`
- **exploit_history:** `MATERIAL — Euler V1 suffered a ~$197M flash-loan/donation exploit in March 2023; funds were subsequently returned by the attacker. V2 is a ground-up redesign. VERIFY exact figures + that V2's architecture addresses the V1 vector before any allocation. This is the single most important field on this card.`
- **admin_keys:** `TBD — requires data verification (governance + Guardian; source threshold/timelock). Load-bearing.`
- **upgradeability:** `governance-controlled — requires verification`
- **oracle_dependencies:** `["per-vault oracle configuration (EVK) — a bad oracle = a bad vault"]`
- **bridge_dependencies:** `[]`  <!-- verify per chain -->
- **governance_model:** `EUL token governance + Guardian`

## Yield & incentives
- **token_incentives:** `EUL incentives possible — verify. Screen per market via dfb overlay.`
- **yield_sustainability:** `mixed` — verify per vault.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["EXPLOIT HISTORY (V1 $197M 2023 — returned; V2 redesigned but this raises the bar)", "per-vault oracle/config risk (modular EVK)", "smart-contract risk (newer V2 codebase)", "governance/admin risk", "liquidity/withdrawal-at-size"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively HIGHER than Aave/Compound given the V1 exploit + newer V2 code — T2 with an elevated smart-contract weight.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T2 cap (20% per protocol); the exploit history argues for a conservative sub-cap. Exact % requires verification.`
- **monitoring_frequency:** `daily` + `on_event` (exploit/oracle/governance)
- **emergency_triggers:** `["any exploit signal", "per-vault oracle failure", "bad debt in a vault", "governance emergency action"]`

## Provenance
- **notes:** `Euler V2 carries a MATERIAL exploit history (V1, ~$197M, 2023, funds returned) — the redesigned V2 must be evaluated on its own re-audits; the exploit_history field is the decisive gate item. Adapter read-only/advisory. T2.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/12 §5)
- [~] `exploit_history` — **documented (V1 $197M 2023, returned)**; V2-specific re-audit status UNVERIFIED
- [ ] `admin_keys` / `upgradeability` / `oracle_dependencies` / `emergency_triggers` — UNVERIFIED (findings)
- [ ] `tvl` etc. sourced with a date — pending (DeFiLlama euler-v2)
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T2 cap (conservative sub-cap advised) — pending
- [x] `protocol_id` mapped to the adapter key (euler_v2)
