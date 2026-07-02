# Protocol Card — <PROTOCOL_NAME>

> Fill-in template mirroring `schema.protocol_card.json`. One card per protocol.
> Research-layer artifact — NOT runtime data, never read by RiskPolicy or execution.
> **Never invent TVL/revenue/activity. Unknown numbers = `TBD — requires data verification`
> (with a last-verified date once sourced).**
> Cross-refs: docs/12 (this system), docs/11 (Strategy Cards), docs/14 (advisory Risk Scoring v2),
> docs/02 (existing adapters + dfb overlay). Map `protocol_id` to the adapter key where one exists.

## Identity
- **protocol_id:** `PC-XXXX`  <!-- stable unique id, never reused -->
- **protocol_name:** `<name>`  <!-- e.g. Aave V3 -->
- **category:** `<lending|dex|lp|rwa|derivatives|restaking|yield_aggregator|stablecoin_issuer|bridge|other>`
- **chains:** `[]`  <!-- cross-ref adapter chains -->
- **website:** `<url>`
- **docs:** `<url>`
- **app_url:** `<url>`

## Size & activity (never presented without a last-verified date)
- **tvl:** `TBD — requires data verification`  <!-- USD; cite adapter/DeFiLlama + date -->
- **tvl_trend:** `<rising|stable|declining|volatile|unknown>`
- **revenue:** `TBD — requires data verification`  <!-- annualized USD, if known -->
- **fees:** `TBD — requires data verification`  <!-- annualized USD, if known -->
- **user_activity:** `TBD — requires data verification`  <!-- active borrowers/depositors/unique users -->
- **protocol_age:** `<e.g. ~3y since 2021>`

## Security & trust surface (the due-diligence core)
- **audits:** `[]`  <!-- [{firm, scope, date}]; empty = none found, state so explicitly -->
- **bug_bounty:** `<program + size, or none>`
- **exploit_history:** `[]`  <!-- [{what, when, impact, resolution}]; empty = none known, state so -->
- **admin_keys:** `<who controls admin/upgrade keys; multisig threshold; timelock>`  <!-- most load-bearing field -->
- **upgradeability:** `<immutable|timelock|multisig|upgradeable_no_timelock|unknown>`
- **oracle_dependencies:** `[]`  <!-- oracles + what breaks if they fail -->
- **bridge_dependencies:** `[]`
- **governance_model:** `<token vote|council|DAO|off-chain>`

## Yield & incentives
- **token_incentives:** `<incentives inflating APY + expected duration>`
- **yield_sustainability:** `<organic|incentive_dependent|mixed|unsustainable|unknown>`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `[]`  <!-- red-team + overlay inputs -->
- **risk_score:** `TBD`  <!-- 0–100, higher = riskier (docs/14); advisory only -->
- **max_allocation_recommendation:** `TBD — requires data verification`  <!-- % of book; never exceeds RiskPolicy caps -->
- **monitoring_frequency:** `<continuous|daily|weekly|monthly|on_event>`
- **emergency_triggers:** `[]`  <!-- TVL collapse, admin-key change, exploit, oracle failure, governance capture -->

## Provenance
- **notes:** `<reviewer notes>`
- **created_at:** `<ISO-8601 UTC>`
- **updated_at:** `<ISO-8601 UTC>`

---

### Review checklist (docs/12 §5)
- [ ] `admin_keys`, `upgradeability`, `oracle_dependencies`, `exploit_history`, `emergency_triggers`
      filled substantively (unknown there is a finding, not a blank)
- [ ] `tvl` / `revenue` / `fees` / `user_activity` sourced with a last-verified date, else `TBD`
- [ ] `risk_score` + `max_allocation_recommendation` cite the dfb overlay / RiskPolicy caps (advisory only)
- [ ] `protocol_id` mapped to the adapter key where one exists
