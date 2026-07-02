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
- **tvl:** `~$6.64B protocol-wide (Morpho Blue)` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/morpho-blue` (6,640,143,970.83). [L2]  (Base adapter literal ~$180M, 2026-06.)
- **tvl_trend:** `unknown — requires verification`
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `Morpho since ~2022; Morpho Blue since ~2024 — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** **sourced (verified 2026-07-02):** **25+ audits + formal verification** — Spearbit, Trail of Bits, Cantina + others; "one of the most rigorously reviewed codebases in DeFi." Reports public (morpho.org / github.com/morpho-org). [L2]
- **bug_bounty:** `Morpho bug-bounty exists — exact max payout requires verification`
- **exploit_history:** `Morpho Blue core: no widely-reported principal-loss exploit as of 2026-07 (immutable minimal primitive by design). Risk shifts to per-vault curators, not core. [L1→verify]`
- **admin_keys:** **sourced (verified 2026-07-02):** **Morpho Blue markets are IMMUTABLE — governance does NOT control deployed markets** (the security property: deposit-time rules = withdrawal-time rules). Critical governance changes use **timelocks + multisig**. The load-bearing key is per-vault: **MetaMorpho owner/curator/allocator roles** set caps/collateral — must be reviewed PER VAULT. [L2]
- **upgradeability:** `Morpho Blue: IMMUTABLE primitive (sourced); MetaMorpho vaults: owner/curator/allocator-configurable — per-vault review required`
- **oracle_dependencies:** `["per-market oracle chosen at market creation (a bad oracle = a bad isolated market)"]`
- **bridge_dependencies:** `["Base deployment inherits L2-bridge risk (T2)"]`
- **governance_model:** `Morpho DAO (limited scope — core is immutable; timelocks+multisig for critical changes) + per-vault curators (the key trust party for vault users) — sourced 2026-07-02`

## Yield & incentives
- **token_incentives:** `MORPHO incentives on some markets/vaults — verify. Base supply yield can be organic or incentive-boosted; the Rates Desk / dfb overlay screen per market.`
- **yield_sustainability:** `mixed` — organic isolated-lending spread vs incentive-boosted vaults; verify per market.

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["curator risk (MetaMorpho vault curator sets caps/collateral — the main non-obvious risk)", "per-market oracle risk (chosen at creation)", "isolated-market illiquidity", "L2-bridge risk (Base)", "smart-contract risk"]`
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW-MODERATE at the primitive level (~$6.64B, 25+ audits, immutable core), but the REAL risk is per-vault (curator) + per-market (oracle) — a protocol card cannot clear a specific vault. Confidence higher on core; per-vault review still required.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy T2 cap (20% per protocol). Exact % requires verification.`
- **monitoring_frequency:** `daily` (APY/TVL/caps) + `on_event` (curator action, oracle, exploit)
- **emergency_triggers:** `["curator caps/collateral change", "per-market oracle failure", "isolated-market bad debt", "L2-bridge incident", "core exploit"]`

## Provenance
- **notes:** `Now SOURCED at the primitive level (2026-07-02): TVL ~$6.64B (DeFiLlama), 25+ audits (Spearbit/ToB/Cantina), IMMUTABLE Blue core (governance can't touch deployed markets). BUT the real DD is per-VAULT (MetaMorpho curator) + per-MARKET (oracle/collateral) — a protocol card is necessary NOT sufficient; each vault the desk uses needs its own curator+oracle review. Base = T2 (bridge). Adapter read-only/advisory.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/morpho-blue; docs.morpho.org/governance; github.com/morpho-org (audits); Morpho protocol analyses (immutable markets + curator roles).

---

### Review checklist (docs/12 §5)
- [x] `admin_keys` (immutable core + curator model), `oracle_dependencies` (per market), `exploit_history` (none core), `governance` SOURCED — but **per-vault curator review still required** before a specific vault clears
- [x] `tvl` sourced with a date (~$6.64B, DeFiLlama, 2026-07-02)
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T2 cap — pending
- [x] `protocol_id` mapped to adapter keys (morpho, morpho_steakhouse)
