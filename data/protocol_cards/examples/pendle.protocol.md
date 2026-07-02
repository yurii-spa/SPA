# Protocol Card — Pendle

> Real card mapped from the existing Pendle adapters (`spa_core/adapters/pendle_pt*.py`,
> `pendle_adapter.py`) and its use in the Rates Desk FixedCarry sleeve. Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution. **No TVL/revenue/audit/exploit specifics
> are invented** — every metric not sourced from the repo is `requires data verification`, and the
> security fields (`audits`, `exploit_history`, `admin_keys`) are the load-bearing gaps that MUST be
> filled from primary sources before the FixedCarry Strategy Card (`SC-RDFC-001`) protocol-review gate
> can pass. Cross-refs: docs/12, docs/11, docs/14, docs/02, `data/strategy_cards/examples/rates_desk_fixed_carry.strategy.md`.

## Identity
- **protocol_id:** `PC-PENDLE-001`  <!-- maps to adapter keys: pendle_pt, pendle_pt_susde, pendle_pt_usdc, pendle_adapter -->
- **protocol_name:** `Pendle`
- **category:** `derivatives` (yield tokenization — splits a yield-bearing asset into PT (principal) + YT (yield))
- **chains:** `["Ethereum"]`  <!-- adapters use chain="Ethereum" / CHAIN_ID; Pendle also lives on other chains — requires verification of which the desk uses -->
- **website:** `https://www.pendle.finance` <!-- requires verification -->
- **docs:** `https://docs.pendle.finance` <!-- requires verification -->
- **app_url:** `https://app.pendle.finance` <!-- requires verification -->

## Size & activity (never presented without a last-verified date)
- **tvl:** `~$977.5M` — **verified 2026-07-02** via DeFiLlama `api.llama.fi/tvl/pendle` (977,509,682.86). [L2 data-source verified]
- **tvl_trend:** `unknown` — single-point read; trend requires DeFiLlama history (requires verification)
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `~4y (mainnet since ~2021; V2 since ~2023) — requires verification`

## Security & trust surface (the due-diligence core)
- **audits:** **sourced (verified 2026-07-02):** Pendle V2 audited by **ChainSecurity** (Pendle V2 Core — "good level of security"; also audited the newer **Boros Markets**), **Spearbit**, **Ackee Blockchain** (V2 — no critical/high/low findings reported), **WatchPug**, **Least Authority**, **Dedaub**, **Dingbats**, + **Code4rena** wardens. Reports public in `github.com/pendle-finance` (docs/audits). Deep multi-firm coverage. [L2]  <!-- exact dates/scopes per PDF — spot-verify before live -->
- **bug_bounty:** **sourced (verified 2026-07-02):** Pendle runs a public **bug-bounty on Cantina** (`cantina.xyz/bounties` — Pendle Bounty). Max payout `requires verification` of the exact tier. [L2 program exists / L1 amount]
- **exploit_history:** **sourced (verified 2026-07-02):** the **Penpie hack (Sept 2024, ~$27M reentrancy)** hit **Penpie — a yield protocol BUILT ON Pendle — NOT Pendle core**. Pendle stated its platform was **unaffected** and **paused its contracts defensively** (protecting ~$70M). Affected assets were Pendle-related YT/LP tokens (wstETH, sUSDe, agETH, rswETH). Lesson: Pendle *core* has no principal-loss exploit to date, but **composability risk** on top of Pendle is real. Sources: Halborn, CoinDesk, The Defiant. [L2]
- **admin_keys:** **partially sourced:** Pendle **can pause its contracts** (confirmed — it did so in Sept-2024). Exact multisig threshold / timelock / key holders `requires verification` before live. [L1→needs L2]
- **upgradeability:** `pausable + governance-controlled (pause capability confirmed Sept-2024); exact timelock requires verification`
- **oracle_dependencies:** **sourced (verified 2026-07-02):** PT/implied-rate pricing uses a **TWAP-based oracle** on the Pendle AMM. Manipulation-resistance is **"good after the maximum allowable TWAP price change was lowered"** (per ChainSecurity's Boros Markets audit); residual note — **TWAP instability if the spread is high**. What breaks on oracle failure: PT mark-to-market + exit pricing. [L2]
- **bridge_dependencies:** `[]`  <!-- single-chain PT usage per the desk's adapters; N/A unless a bridged underlying is used (verify per market) -->
- **governance_model:** **sourced (verified 2026-07-02):** **vePENDLE** vote-escrow — lock PENDLE **up to 2 years** to (a) direct emissions (gauge votes), (b) vote on new pool listings, (c) capture protocol fees. Vote-escrow raises decentralization vs a plain multisig. [L2]

## Yield & incentives
- **token_incentives:** `PENDLE emissions incentivize LP/PT/YT liquidity — presence + duration requires verification. NOTE: FixedCarry books the PT fixed rate, NOT emissions (incentive_apy ~0).`
- **yield_sustainability:** `mixed` — PT fixed carry is organic (a mispriced rate), but overall Pendle-market APYs can be incentive-inflated; the Rates Desk gate refuses tail-comp/incentive-only yield (1,070 refusals to date).

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["PT rate/duration risk (MTM before maturity)", "PT/AMM exit-liquidity-at-size (the FixedCarry capacity constraint — realized-at-size INSUFFICIENT_DATA)", "COMPOSABILITY risk — protocols built ON Pendle can fail (Penpie $27M Sept-2024), even when Pendle core is safe", "underlying-asset risk (mitigated: refusal gate rejects toxic underlyings)", "admin-key threshold/timelock UNVERIFIED (pause capability confirmed)"]`
- **risk_score:** `TBD — requires a Risk Scoring v2 run (docs/14). Qualitatively LOW-MODERATE: strong multi-firm audit coverage + Pendle core has no principal-loss exploit; confidence now higher (audits + exploit history sourced). Residual: admin-key threshold + exit-liquidity-at-size.`
- **max_allocation_recommendation:** `TBD — requires data verification`  <!-- advisory; never exceeds RiskPolicy T2 caps (Pendle is a T2 protocol per CLAUDE.md) -->
- **monitoring_frequency:** `daily` (rate surface + refusal scan via `com.spa.rates_desk_paper`) + `on_event` (exploit/admin-change)
- **emergency_triggers:** `["Pendle core exploit", "admin-key change / suspicious upgrade", "PT/AMM liquidity collapse", "oracle/pricing failure", "underlying depeg"]`

## Provenance
- **notes:** `SOURCED (2026-07-02): TVL ~$977.5M (DeFiLlama); audits (ChainSecurity/Spearbit/Ackee/WatchPug/Least-Authority/Dedaub/Dingbats/Code4rena + Boros); bug-bounty (Cantina); oracle (TWAP, manipulation-resistant per Boros audit); governance (vePENDLE vote-escrow ≤2y); exploit history (Penpie $27M Sept-2024 = ecosystem-not-core; Pendle paused + unaffected). SINGLE remaining gap before LIVE: admin-key multisig threshold/timelock. Adapters read-only/advisory. Pendle = T2 (CLAUDE.md).`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **sources:** DeFiLlama api.llama.fi/tvl/pendle; ChainSecurity Pendle-V2-Core + Boros-Markets audits; Spearbit / Ackee / WatchPug / Least-Authority audits; Cantina bug-bounty (cantina.xyz/bounties); Pendle docs (vePENDLE ≤2y vote-escrow; Security page); Halborn / CoinDesk / The Defiant / Three Sigma on the Sept-2024 Penpie $27M reentrancy hack.

---

### Review checklist (docs/12 §5)
- [x] `audits` (multi-firm: ChainSecurity/Spearbit/Ackee/WatchPug/Least-Authority/Dedaub/Dingbats/Code4rena + Boros), `bug_bounty` (Cantina), `oracle_dependencies` (TWAP, manipulation-resistant), `exploit_history` (Penpie=ecosystem-not-core), `governance_model` (vePENDLE ≤2y) — **SOURCED 2026-07-02**
- [x] `tvl` sourced with a last-verified date (~$977.5M, DeFiLlama, 2026-07-02); revenue/fees/user_activity still pending
- [ ] `admin_keys` exact multisig threshold/timelock — **the SINGLE remaining load-bearing gap** (pause capability confirmed; threshold not)
- [ ] `risk_score` + `max_allocation_recommendation` — Risk Scoring v2 run pending (T2 cap)
- [x] `protocol_id` mapped to the adapter keys (pendle_pt / pendle_pt_susde / pendle_pt_usdc)

> **Gate status for `SC-RDFC-001` (FixedCarry):** protocol-review = **ONE FIELD FROM PASSING** — TVL,
> audits, **bug-bounty (Cantina)**, **oracle (TWAP)**, **governance (vePENDLE)**, and exploit history
> are now all sourced (2026-07-02). The **single remaining load-bearing gap is the admin-key
> multisig threshold/timelock** (pause capability is confirmed; the exact threshold is not). Honest
> evidence discipline: the gate has moved from "all-unverified" → "one on-chain field from clearing."
