# SPA — Due-Diligence Pack (DD_PACK)

_A structured, auto-generated, REAL-DATA data-room for an LP / investor due-diligence review. Every number below is either read live from a `data/` file or lifted verbatim from a SHA-256-hashed row of `data/rates_desk/decision_log.jsonl` — and a build test (`spa_core/tests/test_dd_pack.py`) FAILS if any numeric claim in this document is not resolvable to one of those sources (the no-unsourced-number guard). stdlib-only, deterministic, fail-CLOSED. Honest: the track is THIN, the capacity is bounded, the capital is paper ($0 real)._

> **Don't trust us — check us.** Every hashed row cited here is reproducible by a skeptical third party with one zero-dependency script and SPA's public JSON, on a clean machine with none of our code:
>
> ```
> python3 scripts/verify_spa.py data/rates_desk/
> ```
>
> Recipe: `docs/PROOF_CHAIN_SPEC.md`. Public surfaces: `/refusals` (the decision log), `/exit-nav` (liquidation-NAV by size), `/proof-of-reserves` (honest paper NAV), `/track-record` (the accruing series), `/fundability` (this case, live).

---

## 1. Executive verdicts (at a glance)

| thesis | module | verdict | the honest boundary |
|---|---|---|---|
| **#1 Rates Desk** (refusal-first carry) | `spa_core/strategy_lab/rates_desk/` | **GO** — FixedCarry validated, live-paper | carry leg is real -> fundable; capacity-bound |
| **#2 RWA Repo Backstop** (liquidation-NAV underwriter) | `spa_core/strategy_lab/rwa_backstop/` | **measurement-GO / book NO-GO** | underwriting needs custody+legal+capital (off-code) |
| **#3 Liquidator** (balance-sheet liquidator) | `spa_core/strategy_lab/liquidator/` | **NO-GO** (published) | addressable market ~5-10x below the fundability bar |

**Proof-chain head (re-derived live, the fingerprint of the entire decision history):**

- chain valid: **yes** · length: **394** decisions
- head_hash: `0bbfe1fdab4c6a9ad0950454bcbcb1b41c126381f21a8600aa7f7321f5b3984c`

Reproduce + assert this exact head yourself:

```
python3 scripts/verify_spa.py --expect-head 0bbfe1fdab4c6a9ad0950454bcbcb1b41c126381f21a8600aa7f7321f5b3984c data/rates_desk/
```

---

## 2. The validated GO — a fully worked refused-vs-approved example

This is the differentiator made concrete: on the SAME engine, SAME day, the desk **refused** a toxic LRT carry book and **approved** a clean stable carry book — and BOTH decisions are hashed into the public chain. A great quoted rate cannot buy its way past a structural veto.

### 2a. REFUSAL — `ezeth` (seq #3, as_of 2024-09-01)

A real liquid-restaking-token PT book. The quoted rate looked attractive, but the fair-value engine subtracts structural haircuts and the result is NEGATIVE fair carry — the yield is **tail-risk compensation, not carry**. Refusal fires on structural grounds, *before* economics. **This is exactly the ezETH / over-levered-USDe pattern that blows up in a depeg.**

- verdict: **REFUSAL** · reason: **tail_veto** ("tail-comp veto: quoted rate is risk premium, not carry")
- net edge (fair carry after haircuts): **-47.77%/yr** — negative -> the quoted yield does not compensate for the structural risk it actually carries.

**Structural haircut breakdown (every term from the hashed `decomposition`):**

| term | value |
|---|---:|
| baseline (fair risk-free-ish anchor) | **2.90%** |
| peg haircut (depeg tail) | **6.40%** |
| liquidity haircut (exit depth) | **6.00%** |
| protocol haircut (smart-contract / governance) | **2.60%** |
| oracle haircut | **0.67%** |
| funding-flip haircut | **0.00%** |
| **total haircut** | **15.67%** |
| **fair yield (baseline − haircuts)** | **-12.77%** |

- max tolerated total haircut: **12.00%** — the realized total haircut exceeds it -> **structural veto**.
- approved size: **$0** (refused -> zero capital).

**Hashes (re-derivable):**

- `entry_hash`  : `d521e6218863c54c0f8bef01a0a515740a667e08c32dde49431711f371f7f33a`
- `prev_hash`   : `537c633d9be3fdde3182821dc9b0badcd3bc9a281c854469b64a28c86bcb410d`
- `proof_hash`  : `f3aa57d1f305cfcf4c9a460802ccbdbfe6ac1328975b53a8a7b8dbadc2c57edc`

### 2b. ENTRY — `susde` (seq #4, as_of 2024-09-01)

The very next decision in the chain (its `prev_hash` == the refusal's `entry_hash` above, so the two are provably adjacent in the tamper-evident log). A clean stable-carry book: positive fair carry after the SAME haircut model, so the desk approves a depth-bounded size.

- verdict: **ENTRY (approved)** · net edge: **18.03%/yr** (positive -> real carry).
- quoted rate: **12.00%/yr** · total haircut: **7.53%** · fair yield: **-6.53%/yr**.
- approved size: **$4,062** (depth-bounded by the §9 exit-capacity rule — sizes DOWN rather than eat slippage).

**Hashes (re-derivable):**

- `entry_hash`  : `b7ba67aca34e8f4c672dd60cfb4565525a291b0ca550f4c193d925eedd06bdf9`
- `prev_hash`   : `d521e6218863c54c0f8bef01a0a515740a667e08c32dde49431711f371f7f33a`
- `proof_hash`  : `8d9a77d91c3953c4fc5e9a265a065ddd831db4fd5085480369006c02f6605b50`

**The point:** identical engine, identical haircut model, same day — the toxic book is refused on structure and the clean book is sized. The refusal is the product. Both are public and both are hashed.

---

## 3. The decision record (refusals AND entries, all hashed)

The public, hash-linked `data/rates_desk/decision_log.jsonl` carries **394** logged decisions:

- **207 refusals** — of which **154** structural tail-vetoes (toxic carry refused before economics) and **53** size-floor declines (real carry, but below the fundable depth floor).
- **187 entries** — approved, depth-bounded carry books.

Every row — entry AND refusal — is hashed. This is the surface no competitor publishes: **what we refused, and why.** Live human-readable view: `/refusals`. Machine: `/api/rates-desk/refusals`.

---

## 4. Honest capacity — what this actually clears today

The standalone rates-desk carry edge is REAL and survives every stress window — but it is **capacity-bound** by exit depth. The honest current numbers, live from the capacity model:

- fundable independent books today: **22** (of **25** harvestable markets).
- total depth-bounded deployable AUM: **$330,315** at an aggregate **22.93%/yr** net.
- carry ABOVE the RWA floor (**3.4%/yr**): **$64,779/yr**.
- that is **0.65%** of the $10M/yr target — a gap of **$9,935,221/yr**.

**Stated plainly:** the current real Pendle PT carry market is **too thin** to fund $10M/yr above the floor on its own. The rates desk is **one diversifying sleeve** of a larger book, not a standalone $10M business at today's depth. $10M needs the market to GROW (deeper pools), MORE venues/books, and/or the other sleeves carrying the balance — **plus** the off-code scale legs in §6. Combined across sleeves, after a correlation haircut, the honest figure is lower still. We do not claim $10M is reachable today.

---

## 5. The other two theses — the measurement-GO and the published NO-GO

### 5a. RWA Repo Backstop — measurement-GO / book NO-GO

"Lend against Liquidation NAV, not marketing NAV." The Safety Board measures, from free data, that RWA collateral is genuinely **not cash-like** on an executable on-chain exit:

- **11/11** assets not cash-like — LIQUID **0** · THIN **1** · REDEMPTION_ONLY **9** · UNSAFE **1**.
- max on-chain ERC-4626 NAV divergence from $1.00 marketing NAV: **8.17%**.

**Verdict:** the *measurement* layer is GO (deterministic, fail-closed, runs continuously). The underwriting *book* is NO-GO read-only — it needs whitelisting + redemption agreements + capital + legal, none of it buildable in code (see §6).

### 5b. Liquidator — NO-GO (published — we publish what we kill)

The long-tail / nested-collateral liquidation opportunity was measured read-only and published as a kill:

- gross addressable: **~$3.8M/yr** (top-20 ~**$2.2M/yr**).
- fundability bar: **~$20M/yr** -> the opportunity is ~5-10x **below** the bar.

**Verdict: NO-GO, published.** Too small to justify the custody + CEX + balance-sheet build. Publishing the kill is itself the credibility signal. Source of record: `docs/LIQUIDATOR_DERISK.md`.

---

## 6. The off-code gates — honestly, what stands between here and $10M

The code took each thesis to an honest verdict for free. But the same boundary appears across all three — **the code can measure and refuse; the $10M is off-code.** Stated plainly:

- **Custody / MPC** — institutional key management for real capital; not buildable in read-only paper code.
- **External audit** — independent code + controls audit of the execution path.
- **Legal** — fund structure, collateral perfection, redemption agreements, force-redemption rights; the RWA underwriting leg can only be *documented*, not *executed*, without it.
- **Real capital + relationships** — whitelisting / subscription access to redemption queues; the carry edge needs scale across many capacity-bound books, which needs AUM.

SPA contributes the cheapest, most defensible first layer: the transparent, fail-closed measurement-and-refusal engine that PROVES the mispricing — plus an honest record of exactly which off-code legs gate the business. **$10M is scale + decorrelation + trust + AUM, NOT reachable today** on $0 real capital.

---

## 7. The track status — THIN, honestly labeled

- evidenced track days: **6/30** — **accruing, not yet 30**. Only days backed by a real daily-cycle log count; the earlier backfill bars were reset OUT. The low number IS the credibility.
- honest anchor: **2026-06-22** · go-live target: **2026-07-21**.
- go-live criteria: **26/29 pass** — NOT READY. The remaining blockers are **time-gated** (track days to accrue) — nothing to fix in code.

- forward-track integrity: **all_ok** — **8** forward tracks, **0** failing (no duplicates / gaps / out-of-order / future-dated points).

- go-live dry-run harness: gates verified **inert** — NAV reconciliation **PASS**, live-trading gate active **no**, moves_capital **no**. The fail-closed chain fires WITHOUT moving any capital.

Live, regenerating view: `/track-record` (hash-anchored series + per-bar source labels). Verify the underlying chain: `python3 scripts/verify_spa.py data/rates_desk/`.

---

## 8. How a hostile LP checks every claim here

1. Download `scripts/verify_spa.py` (zero dependencies, no `spa_core` import, no network) and SPA's public artifacts: `data/rates_desk/decision_log.jsonl`, `data/rates_desk/exit_nav.json`, `data/rates_desk/anchors.jsonl`.
2. Run it on a clean machine:

```
python3 verify_spa.py data/rates_desk/
```

3. It re-derives EVERY decision `entry_hash`, every exit-NAV `proof_hash`, and the anchor head-checkpoints — and reports the precise `broken_at` if a single byte of history was altered after the fact. Exit 0 = everything reproduces.
4. Cross-check the worked example in §2: its `proof_hash` values are emitted by the same recipe (`docs/PROOF_CHAIN_SPEC.md`).

The append-only anchor ledger currently holds **1** head-checkpoint(s) (a genesis reset over the security-corrected chain head is auditable in the ledger note).

**Honesty contract for this doc:** every numeric token in DD_PACK.md is asserted (by `test_dd_pack.py`) to be present in the set of numbers sourced from `data/` files or hashed decision rows. A number that drifts from its source fails the build. There are no un-sourced claims.

---

_Regenerated 2026-06-28 03:04 UTC. All numbers live from `data/` (golive_status.json · rates_desk/{rates_desk_promotion,portfolio_capacity}.json · rates_desk/decision_log.jsonl · rates_desk/anchors.jsonl · rwa_safety_board.json · forward_track_integrity.json · golive_dry_run.json) and the hashed decision rows; Liquidator NO-GO figures from `docs/LIQUIDATOR_DERISK.md`. Regenerable via `python3 scripts/generate_dd_pack.py`. Mirror page: `/fundability`._