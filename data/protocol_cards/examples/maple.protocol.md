# Protocol Card — Maple Finance (institutional onchain credit)

> Deep-research cycle 10 (autonomous engine, item B). Created to **unblock CAND-SYRUP-001** (Maple
> syrupUSDC, WATCH/conditional). All facts web-sourced 2026-07-02 with evidence levels; unknowns =
> `requires verification`. Cross-refs: docs/12, docs/11, `data/strategy_candidates/maple_syrupusdc.candidate.md`,
> docs/decision_index.md.

## Identity
- **protocol_id:** `PC-MAPLE-001`
- **protocol_name:** `Maple Finance` (onchain institutional credit; Syrup product line — syrupUSDC/syrupUSDT)
- **category:** `lending` (institutional credit marketplace — NOT overcollateralized retail lending)
- **chains:** `["Ethereum", "+ verify (Solana syrup, etc.)"]`
- **website:** `https://maple.finance` <!-- requires verification -->
- **docs:** `https://docs.maple.finance` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `~$2.49B` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/maple-finance` (2,494,810,101). syrupUSDC pool ~$1.22B, syrupUSDT ~$436M (79% loans / 21% liquidity buffer). [L2]
- **tvl_trend:** `unknown — requires DeFiLlama history`
- **revenue/fees:** `TBD — requires data verification`
- **user_activity:** `institutional borrowers (trading firms, market makers, crypto funds) — requires verification`
- **protocol_age:** `Maple since 2021; V2 core + Syrup line current — requires exact dates`

## Credit model & custody (the DD core — SOURCED)
- **lending_model:** **sourced (2026-07-02):** institutional borrowers tap USDC from pools run by professional credit **underwriters**. Syrup loans are **mostly overcollateralized 120–170%** with BTC/ETH/stables held at custodians — a structural change from v1's undercollateralized model. [L2]
- **custody:** **sourced:** collateral held at **Anchorage, BitGo, Copper** (qualified custodians). [L2]
- **withdrawal_terms:** **sourced:** syrupUSDC withdrawals earn interest until processed, **FIFO** as liquidity frees up; **most < 24h, but up to 30 days** at size (the exit-liquidity constraint). Committed loans lock until matured. [L2]

## Security & trust surface
- **audits:** **sourced (2026-07-02):** Maple Core V2 = **7+ audits** (Spearbit/Cantina, Three Sigma, 0xMacro); the Nov-2025 Withdrawal-Manager upgrade = **2 audits (Spearbit + Sherlock)**; the **Syrup Router audited by Three Sigma**. Strong coverage. [L2]
- **bug_bounty:** `requires verification`
- **exploit_history:** **MATERIAL, sourced (2026-07-02):** **Maple v1 (2021–22) was UNDERCOLLATERALIZED and lost LPs ~$50M+** in the 2022 credit cycle (**Orthogonal Trading** default + M11/Babel). This was a **CREDIT default, not a contract exploit.** The protocol restructured; the **Syrup line reports ~3 years ZERO principal losses** under stricter overcollateralized underwriting. The precedent is the decisive DD flag. [L2]
- **admin_keys / upgradeability:** SYRUP / stSYRUP governance controls product launches, treasury, upgrades; **contracts ARE upgradeable** (Withdrawal Manager upgraded Nov-2025) — governance/upgrade risk. Exact multisig/timelock `requires verification`. Underwriters set loan terms (the key non-obvious trust party).
- **oracle_dependencies:** `collateral valuation (custodial + on-chain) — verify`
- **governance_model:** `SYRUP token + stSYRUP staking governance`

## Yield & incentives
- **token_incentives:** `SYRUP incentives possible; the syrupUSDC ~5.2% base yield is organic borrower interest (verify current incentive component).`
- **yield_sustainability:** `organic (borrower interest)` — durable while institutional credit demand persists; compresses/defaults in a crypto-credit downturn (2022 pattern).

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["CREDIT/counterparty default (mitigated: overcollat 120-170% + Anchorage/BitGo/Copper custody + ~3yr zero-loss Syrup) — but correlated to a crypto crash", "v1 $50M/2022 default PRECEDENT (undercollat model — the DD bar)", "underwriter-dependence (professional credit underwriters set terms)", "withdrawal-queue liquidity (FIFO, up to 30 days at size)", "governance/upgradeability (upgradeable contracts + SYRUP governance)"]`
- **PER-POOL DD (syrupUSDC, sourced 2026-07-02 — TID Research + live):** composition **79% loans ($1.27B) / 21% liquidity ($347M)**; loans = institutional credit backed by **BTC/XRP/cbBTC/HYPE at 125–333% collateral, averaging 160%+**; liquidity incl. $152.7M PYUSD + $105M USTB (Superstate T-bill). **ZERO loan defaults across >$600M cumulative originations.** Exit ~**12 bps flat, sub-minute** normal / redemption-queue (≤30d) binding only in stress. **Borrower concentration (THE residual): top-3 ~48.8% / top-1 ~19.3%** of the $1.27B book; syrupUSDC+syrupUSDT share borrowers (concentrates, not diversifies). **Live APY ~4.7%** (3-9% range; 9-12% = separate higher-risk tier). [L2]
- **risk_score:** `TBD — Risk Scoring v2 run pending (docs/14). Qualitatively LOW-MODERATE after DD (2026-07-02): 160%+ overcollat + 0-default >$600M + qualified collateral CLEAR the credit-underwriting; the binding residual is BORROWER CONCENTRATION (top-3 48.8%/top-1 19.3%) → a strict single-borrower + top-3 cap is the condition, counting syrupUSDC+syrupUSDT combined.`
- **max_allocation_recommendation:** `Advisory — a credit sleeve; STRICT sub-cap given the v1 precedent + credit-crash correlation. Exact % requires verification.`
- **monitoring_frequency:** `daily (pool APY/utilization/liquidity buffer) + on_event (default, underwriter change, governance upgrade, custody event)`
- **emergency_triggers:** `["borrower default / underwriter warning", "liquidity buffer drain (withdrawal queue lengthening)", "custody (Anchorage/BitGo/Copper) event", "governance/upgrade with adverse terms", "crypto-credit-cycle stress (2022 pattern)"]`

## Provenance
- **notes:** `SOURCED 2026-07-02. Unblocks CAND-SYRUP-001's protocol-review + custody + audit conditions: syrupUSDC's ~180bps spread is credit-risk-comp now BOUNDED (overcollat 120-170% + qualified custody + 3yr zero-loss + 7+ audits). REMAINING conditions before ADVANCE: per-pool overcollateralization + underwriter track-record DD + a strict issuer cap + full Red-Team (mandatory for credit) + exit-liquidity-at-size vs the up-to-30-day queue. The v1 $50M default keeps this WATCH, not clean-ADVANCE.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/maple-finance ($2.49B); Maple/Syrup docs + gitbook security + TID/OAK/Modular Capital/Vaasblock research (5.2% APY, overcollat 120-170%, Anchorage/BitGo/Copper custody, v1 $50M 2022 default, Syrup 3yr zero-loss, audits Spearbit-Cantina/Three-Sigma/0xMacro/Sherlock, FIFO withdrawal <24h–30d).

---

### Review checklist (docs/12 §5)
- [x] `audits` SOURCED (7+ Core V2 + Withdrawal-Manager + Syrup Router); `exploit_history` SOURCED (v1 $50M/2022 credit default; Syrup 3yr zero-loss); custody SOURCED (Anchorage/BitGo/Copper)
- [x] `tvl` sourced with a date (~$2.49B, DeFiLlama, 2026-07-02); withdrawal terms sourced (FIFO <24h–30d)
- [ ] `admin_keys` exact multisig/timelock + bug-bounty + per-pool overcollateralization + underwriter track-record — pending
- [ ] `risk_score` — Risk Scoring v2 run pending (T2, strict credit sub-cap advised)

> **Unblocks CAND-SYRUP-001 (partially):** protocol-review + audits + custody + exploit-history now
> sourced → the WATCH verdict's spread-attribution is documented. Still gated on per-pool overcollat +
> underwriter DD + strict cap + full red-team before the credit sleeve could ADVANCE to paper.
