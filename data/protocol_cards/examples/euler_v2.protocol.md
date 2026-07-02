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
- **tvl:** `~$282M` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/euler-v2` (281,575,088.96). [L2]  (Smallest of the desk's lenders — capacity-relevant.)
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Euler V1 2022; exploited & wound down 2023; V2 relaunched ~2024 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** **sourced (verified 2026-07-02):** V2 relaunch backed by **31 audit reports** from **Certora, Omniscia, OtterSec, OpenZeppelin, Trail of Bits** (+ per one source, 45 audits across 13 firms), a **$1.25M Cantina audit competition**, a **$3.5M Hats "Capture the Flag"**, and a bug-bounty — **~$4M DAO security spend**. Exceptional post-hack security investment. [L2]
- **bug_bounty:** `Yes — part of the ~$4M V2 security program (sourced); exact max payout requires verification`
- **exploit_history:** **MATERIAL, sourced (verified 2026-07-02):** Euler **V1 suffered a ~$197M flash-loan exploit (March 2023)** (stETH/USDC/wBTC); **the attacker returned ~all funds**. **V2 is a ground-up "meta-lending" redesign** (modular EVK vaults + EVC), relaunched 2024 after the audit program above. The V1 vector is addressed by the redesign — but this history raises the bar. Sources: The Block, CoinDesk, DL News. [L2]
- **admin_keys:** `EUL governance + Guardian — exact threshold/timelock requires verification (load-bearing given the history)`
- **upgradeability:** `governance-controlled; per-vault (EVK) configurable — exact params require verification`
- **oracle_dependencies:** `["per-vault oracle configuration (EVK) — a bad oracle = a bad vault"]`
- **bridge_dependencies:** `[]`  <!-- verify per chain -->
- **governance_model:** `EUL token governance + Guardian`

## Yield & incentives
- **token_incentives:** `EUL incentives possible — verify. Screen per market via dfb overlay.`
- **yield_sustainability:** `mixed` — verify per vault.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["EXPLOIT HISTORY (V1 $197M 2023 — returned; V2 redesigned but this raises the bar)", "per-vault oracle/config risk (modular EVK)", "smart-contract risk (newer V2 codebase)", "governance/admin risk", "liquidity/withdrawal-at-size"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively HIGHER than Aave/Compound: V1 $197M exploit history + newer V2 code + smallest TVL (~$282M, capacity-limited), PARTLY offset by an exceptional 31-audit/$4M security program. T2 with elevated smart-contract + capacity weight; conservative sub-cap advised.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T2 cap (20% per protocol); the exploit history argues for a conservative sub-cap. Exact % requires verification.`
- **monitoring_frequency:** `daily` + `on_event` (exploit/oracle/governance)
- **emergency_triggers:** `["any exploit signal", "per-vault oracle failure", "bad debt in a vault", "governance emergency action"]`

## Provenance
- **notes:** `Now SOURCED (2026-07-02): TVL ~$282M (DeFiLlama, smallest lender = capacity-limited), V2 re-audit program (31 audits/Certora+ToB+OZ+OtterSec+Omniscia + $1.25M Cantina comp + $3.5M Hats CTF, ~$4M spend), V1 $197M/2023 exploit (funds returned) — V2 is a ground-up redesign. The exploit history + newest code + smallest TVL make it the highest-scrutiny lender in the set. Adapter read-only/advisory. T2, conservative sub-cap.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/euler-v2; The Block / CoinDesk / DL News (V1 hack + V2 relaunch/31-audits/$4M); euler.finance blog (Cantina audit competition).

---

### Review checklist (docs/12 §5)
- [x] `exploit_history` — **sourced (V1 $197M March-2023, funds returned; V2 redesign + 31 audits)**
- [x] `audits` + `bug_bounty` (program) SOURCED; `admin_keys` threshold/timelock still UNVERIFIED
- [x] `tvl` sourced with a date (~$282M, DeFiLlama, 2026-07-02)
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T2 cap (conservative sub-cap advised) — pending
- [x] `protocol_id` mapped to the adapter key (euler_v2)
