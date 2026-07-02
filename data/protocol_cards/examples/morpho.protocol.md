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
- **audits:** **sourced (verified 2026-07-02):** deep multi-firm + **formal verification (Certora Prover — many core properties formally verified)**. Blue core: **Spearbit/Cantina/Morpho = 8 engagements since Mar-2022** + Trail of Bits; Vaults V2: **Spearbit, Blackthorn, ChainSecurity, Zellic + a Cantina competition**. Core is **~650 lines of code** (drastically reduced attack surface). "One of the most rigorously reviewed codebases in DeFi." Reports public (github.com/morpho-org/morpho-blue/audits). [L2]
- **bug_bounty:** **sourced (verified 2026-07-02):** active **Immunefi** program with significant rewards for responsible disclosure. [L2]
- **exploit_history:** `Morpho Blue core: no widely-reported principal-loss exploit as of 2026-07 (immutable ~650-LOC primitive, formally verified). Risk shifts to per-vault curators, not core. [L2]`
- **admin_keys:** **sourced (verified 2026-07-02):** **Morpho Blue is IMMUTABLE — NO admin keys, NO proxy pattern, NO upgrade mechanism.** Once deployed, code cannot change (deposit-time rules = withdrawal-time rules). The load-bearing key is per-vault: **MetaMorpho owner/curator/allocator roles** set caps/collateral — reviewed PER VAULT. [L2]
- **upgradeability:** `Morpho Blue: IMMUTABLE — no admin/proxy/upgrade (sourced); MetaMorpho vaults: owner/curator/allocator-configurable — per-vault review required`
- **oracle_dependencies:** `["per-market oracle chosen at market creation (a bad oracle = a bad isolated market)"]`
- **bridge_dependencies:** `["Base deployment inherits L2-bridge risk (T2)"]`
- **governance_model:** **sourced (verified 2026-07-02):** MORPHO token governance (limited scope — Blue core is immutable so governance canNOT touch deployed markets; timelocks+multisig for peripheral changes) + per-vault curators (the key trust party for vault users).

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
- **notes:** `SOURCED at the primitive level (2026-07-02): TVL ~$6.64B; Blue = IMMUTABLE ~650-LOC core (NO admin keys/proxy/upgrade), formally verified (Certora), 8 Spearbit-Cantina engagements + ToB, Vaults V2 by Spearbit/Blackthorn/ChainSecurity/Zellic, Immunefi bounty. Core DD is now COMPLETE. The residual real DD is per-VAULT (MetaMorpho curator) + per-MARKET (oracle/collateral) — a protocol card is necessary NOT sufficient; each vault (e.g. CAND-STEAK-001 Steakhouse USDC) needs its own curator+oracle review. Base = T2 (bridge). Adapter read-only/advisory.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/morpho-blue; github.com/morpho-org/morpho-blue/audits (Spearbit/Cantina 8 engagements since Mar-2022, ToB, Certora formal verification, ~650 LOC); Vaults V2 audits (Spearbit/Blackthorn/ChainSecurity/Zellic/Cantina); Immunefi bug-bounty; morpho.org (immutable no-admin-keys core + MORPHO governance + MetaMorpho curator model).

---

### Review checklist (docs/12 §5)
- [x] `admin_keys` (IMMUTABLE — no admin/proxy/upgrade), `audits`+`formal-verification` (Certora + 8 Spearbit-Cantina + ToB + Vaults-V2 tier-1), `bug_bounty` (Immunefi), `oracle_dependencies` (per market), `exploit_history` (none core), `governance` (MORPHO) — **core DD COMPLETE**; per-vault curator+oracle review still required before a specific vault (CAND-STEAK-001) clears
- [x] `tvl` sourced with a date (~$6.64B, DeFiLlama, 2026-07-02)
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy T2 cap — pending
- [x] `protocol_id` mapped to adapter keys (morpho, morpho_steakhouse)
