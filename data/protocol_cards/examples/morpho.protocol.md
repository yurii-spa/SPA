# Protocol Card — Morpho

> Real card mapped from `spa_core/adapters/morpho*.py` (MorphoBlueAdapter, TIER T2, Base, TVL_USD
> literal ~$180M 2026-06). Research-layer artifact — NOT runtime data. **No specifics invented**;
> unsourced = `requires data verification`. Cross-refs: docs/12, docs/11, docs/14, docs/02.

## Identity
- **protocol_id:** `PC-MORPHO-001`  <!-- maps to adapters: morpho (Morpho Blue), morpho_steakhouse (curated vault) -->
- **protocol_name:** `Morpho (Blue + curated vaults)`
- **category:** `lending` (isolated-market lending primitive + curated MetaMorpho vaults)
- **chains:** `["Base", "Ethereum"]`  <!-- morpho adapter CHAIN=base; also mainnet — verify set -->
- **website:** `https://morpho.org` <!-- requires verification -->
- **docs:** `https://docs.morpho.org` <!-- requires verification -->
- **app_url:** `https://app.morpho.org` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `Base ~$180M (adapter literal TVL_USD, 2026-06 — re-verify live via DeFiLlama project "morpho"). Protocol-wide: requires data verification.`
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Morpho since ~2022; Morpho Blue since ~2024 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** `TBD — requires data verification`
- **bug_bounty:** `TBD — requires data verification`
- **exploit_history:** `TBD — requires data verification (Morpho Blue core is minimal/immutable by design; verify)`
- **admin_keys:** `TBD — requires data verification`  <!-- Blue primitive is largely immutable; the RISK shifts to the CURATOR of each MetaMorpho vault (who sets caps/collateral). Source curator identity + powers per vault. Load-bearing. -->
- **upgradeability:** `Morpho Blue: largely immutable primitive; MetaMorpho vaults: curator-configurable — requires verification`
- **oracle_dependencies:** `["per-market oracle chosen at market creation (a bad oracle = a bad isolated market)"]`
- **bridge_dependencies:** `["Base deployment inherits L2-bridge risk (T2)"]`
- **governance_model:** `Morpho DAO + per-vault curators (the curator is the key trust party for vault users)`

## Yield & incentives
- **token_incentives:** `MORPHO incentives on some markets/vaults — verify. Base supply yield can be organic or incentive-boosted; the Rates Desk / dfb overlay screen per market.`
- **yield_sustainability:** `mixed` — organic isolated-lending spread vs incentive-boosted vaults; verify per market.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["curator risk (MetaMorpho vault curator sets caps/collateral — the main non-obvious risk)", "per-market oracle risk (chosen at creation)", "isolated-market illiquidity", "L2-bridge risk (Base)", "smart-contract risk"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively moderate (T2); curator + per-market-oracle are the load-bearing variables.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T2 cap (20% per protocol). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/TVL/caps) + `on_event` (curator action, oracle, exploit)
- **emergency_triggers:** `["curator caps/collateral change", "per-market oracle failure", "isolated-market bad debt", "L2-bridge incident", "core exploit"]`

## Provenance
- **notes:** `Morpho's risk is unusual: the Blue primitive is minimal/immutable, so the real due-diligence is per-VAULT (MetaMorpho curator) and per-MARKET (oracle/collateral choice). A protocol-level card is necessary but NOT sufficient — each vault the desk uses needs its own curator+oracle review. Base = T2 (bridge). Adapter read-only/advisory.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/12 §5)
- [ ] `admin_keys` (curator per vault) / `oracle_dependencies` (per market) / `exploit_history` / `emergency_triggers` — **UNVERIFIED (findings); per-vault curator review required**
- [ ] `tvl` etc. sourced with a date — **partial (Base ~$180M 2026-06)**
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T2 cap — pending
- [x] `protocol_id` mapped to adapter keys (morpho, morpho_steakhouse)
