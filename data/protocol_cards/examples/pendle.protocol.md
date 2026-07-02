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
- **tvl:** `TBD — requires data verification`  <!-- source live via DeFiLlama (_PENDLE_PROJECT) + date; the adapter reads DeFiLlama but no committed TVL literal exists -->
- **tvl_trend:** `unknown`  <!-- requires verification from DeFiLlama history -->
- **revenue:** `TBD — requires data verification`
- **fees:** `TBD — requires data verification`
- **user_activity:** `TBD — requires data verification`
- **protocol_age:** `~4y (mainnet since ~2021) — requires verification`

## Security & trust surface (the due-diligence core — the load-bearing gaps)
- **audits:** `TBD — requires data verification`  <!-- list [{firm, scope, date}] from Pendle's published audits; empty here means NOT YET SOURCED, not "none" -->
- **bug_bounty:** `TBD — requires data verification`  <!-- program + max payout -->
- **exploit_history:** `TBD — requires data verification`  <!-- MUST verify: a 2024 exploit hit the Penpie ecosystem protocol (built on Pendle), reportedly not Pendle core — confirm scope + whether PT holders were ever at risk before relying on it -->
- **admin_keys:** `TBD — requires data verification`  <!-- who controls upgrade/admin keys, multisig threshold, timelock. THE most load-bearing field for a PT-to-maturity strategy — must be sourced before gate passes -->
- **upgradeability:** `unknown — requires data verification`
- **oracle_dependencies:** `["PT/implied-rate pricing (Pendle AMM + rate surface)"]`  <!-- what breaks if PT pricing/oracle fails: mark-to-market + exit — requires verification of exact oracle design -->
- **bridge_dependencies:** `[]`  <!-- single-chain PT usage per the desk's adapters; N/A unless a bridged underlying is used (verify per market) -->
- **governance_model:** `token governance (vePENDLE) — requires verification of exact powers`

## Yield & incentives
- **token_incentives:** `PENDLE emissions incentivize LP/PT/YT liquidity — presence + duration requires verification. NOTE: FixedCarry books the PT fixed rate, NOT emissions (incentive_apy ~0).`
- **yield_sustainability:** `mixed` — PT fixed carry is organic (a mispriced rate), but overall Pendle-market APYs can be incentive-inflated; the Rates Desk gate refuses tail-comp/incentive-only yield (1,070 refusals to date).

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **known_risks:** `["PT smart-contract / Pendle protocol risk", "PT rate/duration risk (MTM before maturity)", "PT/AMM exit-liquidity-at-size (the FixedCarry capacity constraint — realized-at-size INSUFFICIENT_DATA)", "underlying-asset risk (mitigated: refusal gate rejects toxic underlyings)", "admin-key/upgradeability (UNVERIFIED — treat as risk until sourced)"]`
- **risk_score:** `TBD — requires a Risk Scoring v2 run (docs/14). Qualitatively moderate; the unverified admin-key/exploit fields cap confidence.`
- **max_allocation_recommendation:** `TBD — requires data verification`  <!-- advisory; never exceeds RiskPolicy T2 caps (Pendle is a T2 protocol per CLAUDE.md) -->
- **monitoring_frequency:** `daily` (rate surface + refusal scan via `com.spa.rates_desk_paper`) + `on_event` (exploit/admin-change)
- **emergency_triggers:** `["Pendle core exploit", "admin-key change / suspicious upgrade", "PT/AMM liquidity collapse", "oracle/pricing failure", "underlying depeg"]`

## Provenance
- **notes:** `Fail-closed stance: because audits/exploit_history/admin_keys are UNVERIFIED here, this card does NOT yet satisfy the FixedCarry protocol-review gate — the empty security fields are findings, not blanks. Adapters confirm read-only/advisory usage (no on-chain execution, no state writes). Pendle is classified T2 in the runtime tier map (CLAUDE.md).`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/12 §5)
- [ ] `admin_keys`, `upgradeability`, `oracle_dependencies`, `exploit_history`, `emergency_triggers` filled substantively — **admin_keys / upgradeability / exploit_history are UNVERIFIED (findings, not blanks)**
- [ ] `tvl` / `revenue` / `fees` / `user_activity` sourced with a last-verified date — **pending (live via DeFiLlama _PENDLE_PROJECT)**
- [ ] `risk_score` + `max_allocation_recommendation` cite the dfb overlay / RiskPolicy T2 caps — pending
- [x] `protocol_id` mapped to the adapter keys (pendle_pt / pendle_pt_susde / pendle_pt_usdc)

> **Gate status for `SC-RDFC-001` (FixedCarry):** protocol-review = **NOT PASSED** — the three security
> fields (audits, exploit_history, admin_keys) must be sourced from Pendle's primary docs before this
> card clears the Strategy Card's protocol-review gate. This is the mandate/evidence discipline working:
> a protocol the desk already reads live is still not "reviewed" until its trust surface is documented.
